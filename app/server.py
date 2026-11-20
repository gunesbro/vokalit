"""Local HTTP server for the UI: static page, workspace audio files and a JSON API.

Listens on 127.0.0.1 only. Every API request must carry the per-run token; requests for another
Host are refused (DNS rebinding); the page may load nothing from outside (CSP). See spec 4.1.
"""
import functools
import json
import queue
import random
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import dubs
import models
import workspace as ws

CSP = "default-src 'self'; media-src 'self' blob:; img-src 'self' data:"
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
                ".svg": "image/svg+xml", ".json": "application/json", ".png": "image/png", ".ico": "image/x-icon"}

_httpd = None
_token = None
_ui_dir = None
_jobs = {}
_stop_flags = {}


class NotFound(Exception):
    pass


# --- Jobs ---------------------------------------------------------------------------------------


class Cancelled(Exception):
    """The user cancelled the job (POST /api/jobs/<id>/cancel)."""


def _start_job(work, session=None, kind=None, line=None, dub=None, clips=None):
    """Runs work(job) in a thread; the UI polls GET /api/jobs/<id>. Jobs tagged with a session are listed by
    GET /api/sessions/<sid>/jobs, so a screen opened later (or after switching tabs) shows them again."""
    job = {"id": uuid.uuid4().hex, "state": "running", "progress": "", "log": "", "result": None, "error": "",
           "session": session, "kind": kind, "line": line, "started": time.time(), "dub": dub, "clips": clips}
    _jobs[job["id"]] = job

    def run():
        models.set_owner(job["id"])  # so cancelling this job stops only its own model request
        try:
            job["result"] = work(job)
            job["state"] = "done"
        except Exception as error:  # shown to the user
            if isinstance(error, Cancelled) or job.get("cancelled"):
                job["state"] = "cancelled"
                return
            job["error"] = str(error)
            job["state"] = "failed"

    threading.Thread(target=run, daemon=True).start()
    return {"id": job["id"]}


# --- Views --------------------------------------------------------------------------------------


def _scope_session(session, char_id):
    entry = next((c for c in session["cast"] if c["character"] == char_id), None)
    return None if entry is None or entry["scope"] == "library" else session["id"]


def _session_view(session):
    defaults = {name: models.default_settings(name) for name in models.MODELS}
    cast = []
    for entry in session["cast"]:
        character = ws.cast_character(session, entry["character"])
        cast.append({**entry, "name": character["name"] if character else None,
                     "samples": character["samples"] if character else [],
                     "default_sample": character["default_sample"] if character else None})
    names = {c["character"]: c["name"] for c in cast}
    lines = []
    for line in session["lines"]:
        takes = [{**take,
                  "text_changed": ws.take_text_changed(line, take),
                  "custom_settings": take.get("model") in defaults
                  and ws.take_has_custom_settings(session, take, defaults[take["model"]])}
                 for take in line["takes"]]
        lines.append({**line, "character_name": names.get(line["character"]), "takes": takes})
    return {**session, "cast": cast, "lines": lines}


def _model_view(name):
    info = models.MODELS[name]
    installed = models.is_installed(name)
    return {"name": name, "title": info["title"], "summary": info["summary"], "url": info["url"],
            "license": info["license"],
            "disk_gb": info["disk_gb"], "installed": installed,
            "frees_gb": _frees_gb(name) if installed else None,
            "settings": info["settings"], "supports_convert": info.get("supports_convert", False),
            "languages": [{"code": c, "name": models.LANGUAGE_NAMES[c]} for c in info.get("languages", [])],
            "accent_setting": info.get("accent_setting"),
            "tags": list(info.get("sounds") or {}), "design": info.get("design")}


def _round(gb):
    return None if gb is None else round(gb, 1)


def _frees_gb(name):
    """What removing it frees; None while it is being measured."""
    return _round(models.sizes()["frees"].get(name))


def _component_view(name):
    """A row of the Models screen: Whisper (a tool) or a voice model."""
    info = models.spec(name)
    installed = models.is_installed(name)
    view = _model_view(name) if name in models.MODELS else {
        "name": name, "title": info["title"], "summary": info["summary"], "url": info["url"],
        "license": info["license"], "disk_gb": info["disk_gb"], "installed": installed,
        "frees_gb": _frees_gb(name) if installed else None}
    return {**view, "kind": "model" if name in models.MODELS else "tool", "recommended": info.get("recommended", False),
            "vram_gb": info.get("vram_gb"), "needs_gb": models.needs_gb(name), "runtime": models.runtime(name),
            "downloads": info.get("downloads", "PyPI and Hugging Face")}


def _check_component(name):
    try:
        models.spec(name)
    except KeyError:
        raise NotFound() from None


def _check_language(code, allow_none=False):
    if code is None and allow_none:
        return None
    if code not in models.LANGUAGE_NAMES:
        raise ws.WorkspaceError(f"Unknown language: {code}.")
    return code


# --- Generation ---------------------------------------------------------------------------------


def _line_context(session_id, line_id):
    session = ws.load_session(session_id)
    index = next((i for i, l in enumerate(session["lines"]) if l["id"] == line_id), None)
    if index is None:
        raise NotFound()
    line = session["lines"][index]
    character = ws.cast_character(session, line["character"])
    if character is None:
        raise ws.WorkspaceError(f"Line {index + 1} uses a deleted character. Choose another character first.")
    scope = _scope_session(session, line["character"])
    ref = ws.sample_path(line["character"], line["sample"], scope)
    sample = next((s for s in character["samples"] if ref and ref.name == Path(s["file"]).name), None)
    return session, line, character, ref, sample


def _line_models(session, line, model_names):
    """The chosen models that speak the line's language: the others are skipped. If none does, all of them (each then
    reports that it does not support the language)."""
    language = ws.effective_language(session, line)
    speaking = [n for n in model_names if language in models.MODELS[n].get("languages", [])]
    return speaking or list(model_names)


def _generate_line(session_id, line_id, model_names, seed, job=None):
    session, line, character, ref, sample = _line_context(session_id, line_id)
    sample_label = sample["label"] if sample else "default voice"
    transcript = sample.get("transcript") if sample else None
    if not line["text"].strip():
        number = next(i for i, l in enumerate(session["lines"], 1) if l["id"] == line_id)
        raise ws.WorkspaceError(f"Line {number} is empty. Write its text first.")
    language = ws.effective_language(session, line)
    errors = []
    model_names = _line_models(session, line, model_names)
    for name in model_names:
        if not models.is_installed(name):
            errors.append(f"{models.MODELS[name]['title']} is not installed.")
            continue
        if language not in models.MODELS[name].get("languages", []):
            errors.append(f"{models.MODELS[name]['title']} does not support "
                          f"{models.LANGUAGE_NAMES.get(language, language)}.")
            continue
        if ref and not transcript and models.MODELS[name].get("needs_transcript"):
            errors.append(f"{models.MODELS[name]['title']}: This sample has no transcript. Add it on the Characters "
                          "screen or install Whisper.")
            continue
        text = models.text_for(name, line["text"])
        if not models.has_words(text):  # only tags: sounds it does not perform, or Higgs's emotions with no words
            number = next(i for i, l in enumerate(session["lines"], 1) if l["id"] == line_id)
            errors.append(f"{models.MODELS[name]['title']}: Line {number} is empty without its sound tags.")
            continue
        settings = ws.effective_settings(session, line, name, models.default_settings(name))
        out = ws.new_take_path(session_id, line_id, name)
        if job is not None:
            if job.get("cancelled"):
                raise Cancelled()
            job["model"] = name  # what cancelling stops
        try:
            seconds = models.generate(name, text, str(ref) if ref else None, str(out), seed, settings, language,
                                      ref_text=transcript)
        except Exception as error:
            if job is not None and job.get("cancelled"):
                Path(out).unlink(missing_ok=True)  # a take cut off halfway
                raise Cancelled() from None
            errors.append(f"{models.MODELS[name]['title']}: {error}")
            continue
        finally:
            if job is not None:
                job["model"] = None
        ws.add_take(session_id, line_id, {
            "file": str(out), "kind": "tts", "model": name, "character_name": character["name"],
            "sample_label": sample_label, "text": line["text"], "seed": seed, "settings": settings, "language": language,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "generation_seconds": seconds,
            "duration": round(ws.wav_duration(out), 2)})
    if errors:
        raise RuntimeError(" ".join(errors))


# --- Transcripts ---------------------------------------------------------------------------------

_transcribe_queue = queue.Queue()
_transcribing = set()  # (character, session or None, sample) queued or being transcribed
_transcribe_lock = threading.Lock()


def _transcribe_sample(cid, session_id, sample_id):
    sample = next(s for s in ws.load_character(cid, session_id)["samples"] if s["id"] == sample_id)
    try:
        heard = models.transcribe(str(ws.sample_path(cid, sample_id, session_id)), sample.get("language"))
    except RuntimeError as error:  # e.g. Whisper is not installed; shown to the user
        raise ws.WorkspaceError(str(error)) from None
    ws.set_sample_transcript(cid, sample_id, heard["text"], session_id)
    language = _known_language(heard["language"])
    if language and not sample.get("language"):  # a language the user chose is kept
        ws.set_sample_language(cid, sample_id, language, session_id)


def _known_language(code):
    """Whisper hears ~100 languages; samples keep only the ones Vokalit lists."""
    return code if code in models.LANGUAGE_NAMES else None


def _transcriber():
    while True:
        key = _transcribe_queue.get()
        try:
            _transcribe_sample(*key)
        except Exception as error:  # the sample stays without a transcript; the user can type it
            print(f"Transcribing sample {key} failed: {error}", file=sys.stderr)
        finally:
            with _transcribe_lock:
                _transcribing.discard(key)
            _transcribe_queue.task_done()


def transcribe_missing():
    """Writes down, one at a time in the background, every sample that has no transcript yet (after Whisper is
    installed, and at start-up when it is)."""
    with _transcribe_lock:
        if not getattr(transcribe_missing, "started", False):
            threading.Thread(target=_transcriber, daemon=True).start()
            transcribe_missing.started = True
        for key in ws.samples_without_transcript():
            if key not in _transcribing:
                _transcribing.add(key)
                _transcribe_queue.put(key)


def _transcriber_idle(timeout):
    """For tests: waits until every queued sample is done."""
    end = time.time() + timeout
    while _transcribing and time.time() < end:
        time.sleep(0.02)


def _mark_transcribing(cid, session_id, data):
    with _transcribe_lock:
        keys = set(_transcribing)
    return {**data, "samples": [{**s, "transcribing": True} if (cid, session_id, s["id"]) in keys else s
                                for s in data["samples"]]}


def _random_seed():
    return random.randint(0, 2**31 - 1)


# --- Routes -------------------------------------------------------------------------------------

_routes = []

# Audio files /files/ may serve and /api/reveal may show (all inside workspace/).
AUDIO_TYPES = {".wav": "audio/wav", ".flac": "audio/flac", ".mp3": "audio/mpeg", ".ogg": "audio/ogg"}
# Files /files/ serves: audio, and the dub sources (video, and audio types the window can read).
RANGE_CHUNK = 4 * 1024 * 1024  # bytes sent for an open-ended range request
MEDIA_TYPES = {**AUDIO_TYPES, ".m4a": "audio/mp4", ".mp4": "video/mp4", ".webm": "video/webm"}

RENAME_NOTICE = ("Some take files are open in another program, so their 01-, 02- numbers were not updated. "
                 "They will be on the next change.")


def route(method, pattern):
    def register(fn):
        _routes.append((method, re.compile(f"^{pattern}$"), fn))
        return fn
    return register


def _session_arg(req):
    return req["query"].get("session")


@route("GET", "/api/jobs/(?P<job_id>[0-9a-f]+)")
def get_job(req, job_id):
    if job_id not in _jobs:
        raise NotFound()
    return _jobs[job_id]


@route("POST", "/api/jobs/(?P<job_id>[0-9a-f]+)/cancel")
def cancel_job(req, job_id):
    """Cancels a generation: the model working for it is stopped at once (it loads again for the next take); a batch
    ends there."""
    job = _jobs.get(job_id)
    if job is None:
        raise NotFound()
    if job["state"] == "running":
        job["cancelled"] = True
        if job.get("model"):
            models.cancel(job["model"], job_id)
    return {}


@functools.cache  # the GPU does not change while the app runs; nvidia-smi takes a moment on Windows
def _gpu_name():
    """Name and memory of the first NVIDIA GPU, or None (nvidia-smi ships with the driver)."""
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else None


@route("GET", "/api/system")
def system(req):
    return {"gpu": _gpu_name(), "platform": sys.platform}


def _show_in_file_manager(path):
    """Opens the folder with the file selected (Windows) or the folder (Linux/macOS). No shell is involved."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


@route("POST", "/api/reveal")
def reveal(req):
    """Shows an audio file of the workspace in the system file manager."""
    root = ws.workspace_root().resolve()
    target = (root / str(req["json"].get("path", ""))).resolve()
    if not target.is_relative_to(root) or not target.is_file() or target.suffix not in AUDIO_TYPES:
        raise NotFound()
    _show_in_file_manager(target)
    return {}


@route("GET", "/api/models")
def list_models(req):
    return [_model_view(name) for name in models.MODELS]


@route("GET", "/api/components")
def list_components(req):
    """The Models screen: tools (Whisper) first, then the voice models."""
    names = list(models.TOOLS) + list(models.MODELS)
    running = next((j for j in _jobs.values() if j["kind"] == "install" and j["state"] == "running"), None)
    return {"items": [_component_view(name) for name in names], "total_gb": _round(models.sizes()["total_gb"]),
            "free_gb": round(free_gb(), 1),
            "installing": models.installing(),
            # A screen opened during an install (after switching tabs, or a restart of the window) follows it.
            "install_job": {"id": running["id"], "name": running["line"]} if running else None}


def free_gb():
    """Free space on the drive models are installed to (.local/, or the nearest folder that exists)."""
    folder = Path(models.LOCAL)
    while not folder.exists() and folder.parent != folder:
        folder = folder.parent
    return shutil.disk_usage(folder).free / 1e9


@route("POST", "/api/models/(?P<name>[a-z0-9_-]+)/install")
def install_model(req, name):
    _check_component(name)
    need, free = models.needs_gb(name), free_gb()
    if need > free:  # checked before anything is downloaded
        raise ws.WorkspaceError(f"Not enough disk space for {models.spec(name)['title']}: it needs about {need} GB "
                                f"and {free:.1f} GB is free on this drive. Free some space or remove a model you "
                                "do not use, then try again.")

    def work(job):
        for kind, text in models.install(name):
            if kind == "status":
                job["progress"] = text
            else:
                job["log"] += text
        if name == "whisper":
            transcribe_missing()
        return _component_view(name)
    return _start_job(work, kind="install", line=name)


@route("POST", "/api/models/(?P<name>[a-z0-9_-]+)/cancel")
def cancel_model(req, name):
    _check_component(name)
    models.cancel_install(name)
    return {}


@route("POST", "/api/models/(?P<name>[a-z0-9_-]+)/remove")
def remove_model(req, name):
    _check_component(name)
    if models.runtime(name).get("busy"):  # removing would kill the take in progress
        raise ws.WorkspaceError(f"{models.spec(name)['title']} is generating. Wait for it to finish or cancel it, "
                                "then remove it.")
    models.remove(name)
    return _component_view(name)


@route("POST", "/api/models/(?P<name>[a-z0-9_-]+)/unload")
def unload_model(req, name):
    _check_component(name)
    models.unload(name)
    return _component_view(name)


@route("POST", "/api/transcribe")
def transcribe_clip(req):
    """What is said in a trimmed clip that is not saved yet (the add-sample step)."""
    language = _check_language(req["query"].get("language"), allow_none=True)
    clip = ws.workspace_temp_file(".wav")
    clip.write_bytes(req["raw"])
    try:
        heard = models.transcribe(str(clip), language)
        return {"text": heard["text"], "language": _known_language(heard["language"])}
    except RuntimeError as error:
        raise ws.WorkspaceError(str(error)) from None
    finally:
        clip.unlink(missing_ok=True)


@route("GET", "/api/characters")
def list_characters(req):
    sessions = ws.list_sessions()  # read once, not once per character

    def used(cid):
        return [d["name"] for _, d in sessions if any(c["character"] == cid and c["scope"] == "library" for c in d["cast"])]

    for cid, _ in ws.list_characters():
        ws.remove_missing_samples(cid)
    return [{**_mark_transcribing(cid, None, data), "id": cid, "used_in": used(cid)} for cid, data in ws.list_characters()]


@route("POST", "/api/characters")
def create_character(req):
    session_id = req["json"].get("session")
    cid = ws.create_character(req["json"]["name"], session_id=session_id)
    if session_id:
        ws.add_to_cast(session_id, cid, "session")
    return {**ws.load_character(cid, session_id), "id": cid}


@route("GET", "/api/characters/(?P<cid>[0-9-]+)")
def get_character(req, cid):
    data = ws.load_character(cid, _session_arg(req))
    if data is None:
        raise NotFound()
    if ws.remove_missing_samples(cid, _session_arg(req)):
        data = ws.load_character(cid, _session_arg(req))
    return {**_mark_transcribing(cid, _session_arg(req), data), "id": cid,
            "used_in": [] if _session_arg(req) else ws.sessions_using(cid)}


DESIGN_CANDIDATES = 3


@route("POST", "/api/characters/(?P<cid>[0-9-]+)/design")
def design_voice(req, cid):
    """Speaks a text in DESIGN_CANDIDATES voices made from a description (no sample), to keep one as a sample. The
    candidates are short-lived files in workspace/.tmp/."""
    if ws.load_character(cid, _session_arg(req)) is None:
        raise NotFound()
    body = req["json"]
    name, text = body.get("model", ""), (body.get("text") or "").strip()
    if name not in models.MODELS:
        raise ws.WorkspaceError("Choose a model.")
    description = models.check_description(name, body.get("description"))
    if not models.is_installed(name):
        raise ws.WorkspaceError(f"{models.MODELS[name]['title']} is not installed. Install it in Models.")
    language = body.get("language")
    if language not in models.MODELS[name].get("languages", []):
        raise ws.WorkspaceError(f"{models.MODELS[name]['title']} does not support "
                                f"{models.LANGUAGE_NAMES.get(language, language)}.")
    if not text:
        raise ws.WorkspaceError("Write the text the voices should read.")

    def work(job):
        candidates = []
        for number in range(1, DESIGN_CANDIDATES + 1):
            if job.get("cancelled"):
                raise Cancelled()
            job["progress"] = f"Voice {number} of {DESIGN_CANDIDATES}"
            out, seed = ws.workspace_temp_file(".wav"), random.randint(0, 2**31 - 1)
            job["model"] = name  # what cancelling stops
            try:
                models.design(name, text, str(out), seed, language, description)
            except Exception:
                if job.get("cancelled"):
                    out.unlink(missing_ok=True)
                    raise Cancelled() from None
                raise
            finally:
                job["model"] = None
            candidates.append({"file": out.relative_to(ws.workspace_root()).as_posix(), "seed": seed,
                               "seconds": round(ws.wav_duration(out), 2)})
        return {"candidates": candidates, "text": text, "language": language, "description": description}
    return _start_job(work, kind="design")


@route("PATCH", "/api/characters/(?P<cid>[0-9-]+)")
def rename_character(req, cid):
    ws.rename_character(cid, req["json"]["name"], _session_arg(req))
    return get_character(req, cid)


@route("DELETE", "/api/characters/(?P<cid>[0-9-]+)")
def delete_character(req, cid):
    ws.delete_character(cid)
    return {}


@route("POST", "/api/characters/(?P<cid>[0-9-]+)/samples")
def add_sample(req, cid):
    transcript = req["query"].get("transcript", "").strip()
    if not transcript:
        raise ws.WorkspaceError("Write what the sample says first.")
    language = _check_language(req["query"].get("language"), allow_none=True)
    upload = ws.workspace_temp_file(".wav")
    upload.write_bytes(req["raw"])
    try:
        sample_id = ws.add_sample(cid, str(upload), req["query"].get("source", "upload"), _session_arg(req),
                                  transcript=transcript)
    finally:
        upload.unlink(missing_ok=True)
    if language:
        ws.set_sample_language(cid, sample_id, language, _session_arg(req))
    if req["query"].get("label", "").strip():
        ws.set_sample_label(cid, sample_id, req["query"]["label"].strip(), _session_arg(req))
    return get_character(req, cid)


@route("PATCH", "/api/characters/(?P<cid>[0-9-]+)/samples/(?P<sample_id>s[0-9]+)")
def update_sample(req, cid, sample_id):
    if "label" in req["json"]:
        ws.set_sample_label(cid, sample_id, req["json"]["label"], _session_arg(req))
    if "language" in req["json"]:
        ws.set_sample_language(cid, sample_id, _check_language(req["json"]["language"], allow_none=True),
                               _session_arg(req))
    if "transcript" in req["json"]:
        ws.set_sample_transcript(cid, sample_id, req["json"]["transcript"], _session_arg(req))
    if req["json"].get("default"):
        ws.set_default_sample(cid, sample_id, _session_arg(req))
    return get_character(req, cid)


@route("POST", "/api/characters/(?P<cid>[0-9-]+)/samples/(?P<sample_id>s[0-9]+)/transcribe")
def transcribe_sample(req, cid, sample_id):
    _transcribe_sample(cid, _session_arg(req), sample_id)
    return get_character(req, cid)


@route("DELETE", "/api/characters/(?P<cid>[0-9-]+)/samples/(?P<sample_id>s[0-9]+)")
def delete_sample(req, cid, sample_id):
    ws.delete_sample(cid, sample_id, _session_arg(req))
    return get_character(req, cid)


@route("GET", "/api/sessions")
def list_sessions(req):
    return [{"id": sid, "name": data["name"], "created": data["created"], "lines": len(data["lines"])}
            for sid, data in ws.list_sessions()]


@route("POST", "/api/sessions")
def create_session(req):
    sid = ws.create_session(req["json"].get("name"))
    installed = [name for name in models.MODELS if models.is_installed(name)]
    if installed:
        ws.set_session_models(sid, installed[:1])
    return get_session(req, sid)


def _session_or_404(sid):
    if not (ws.session_dir(sid) / "session.json").exists():
        raise NotFound()
    return ws.load_session(sid)


@route("GET", "/api/sessions/(?P<sid>[0-9-]+)")
def get_session(req, sid):
    """Also forgets takes and samples deleted outside the app (in File Explorer), so they simply disappear."""
    session = _session_or_404(sid)
    changed = ws.remove_missing_takes(sid)
    for entry in session["cast"]:
        changed |= ws.remove_missing_samples(entry["character"], sid if entry["scope"] == "session" else None)
    return _session_view(ws.load_session(sid) if changed else session)


@route("PATCH", "/api/sessions/(?P<sid>[0-9-]+)")
def update_session(req, sid):
    _session_or_404(sid)
    if "name" in req["json"]:
        ws.rename_session(sid, req["json"]["name"])
    if "models" in req["json"]:
        ws.set_session_models(sid, req["json"]["models"])
    if "language" in req["json"]:
        ws.set_session_language(sid, _check_language(req["json"]["language"]))
    return get_session(req, sid)


@route("DELETE", "/api/sessions/(?P<sid>[0-9-]+)")
def delete_session(req, sid):
    ws.delete_session(sid)
    return {}


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/cast")
def add_to_cast(req, sid):
    ws.add_to_cast(sid, req["json"]["character"], req["json"].get("scope", "library"))
    return get_session(req, sid)


@route("DELETE", "/api/sessions/(?P<sid>[0-9-]+)/cast/(?P<cid>[0-9-]+)")
def remove_from_cast(req, sid, cid):
    ws.remove_from_cast(sid, cid)
    return get_session(req, sid)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/cast/(?P<cid>[0-9-]+)/save")
def save_as_character(req, sid, cid):
    ws.save_as_character(sid, cid)
    return get_session(req, sid)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/lines")
def add_line(req, sid):
    body = req["json"]
    line_id = ws.add_line(sid, body["character"], body.get("text", ""),
                          body.get("pause_after", ws.DEFAULT_PAUSE), after=body.get("after"))
    return {"id": line_id, "session": get_session(req, sid)}


@route("PATCH", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)")
def update_line(req, sid, lid):
    if "language" in req["json"]:
        _check_language(req["json"]["language"], allow_none=True)
    ws.update_line(sid, lid, **req["json"])
    return get_session(req, sid)


@route("DELETE", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)")
def delete_line(req, sid, lid):
    renamed = ws.delete_line(sid, lid)
    return {**get_session(req, sid), **({} if renamed else {"notice": RENAME_NOTICE})}


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/lines/order")
def reorder_lines(req, sid):
    renamed = ws.reorder_lines(sid, req["json"]["order"])
    return {**get_session(req, sid), **({} if renamed else {"notice": RENAME_NOTICE})}


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/paste")
def paste_script(req, sid):
    split_long = req["json"].get("split", True)
    added, split = ws.paste_script(sid, req["json"]["text"], split_over=300 if split_long else None, chunk=250)
    return {"added": added, "split": split, "session": get_session(req, sid)}


@route("PUT", "/api/sessions/(?P<sid>[0-9-]+)/settings/(?P<model>[a-z0-9_-]+)")
def set_session_settings(req, sid, model):
    ws.set_session_settings(sid, model, models.validate_settings(model, req["json"]))
    return get_session(req, sid)


@route("DELETE", "/api/sessions/(?P<sid>[0-9-]+)/settings/(?P<model>[a-z0-9_-]+)")
def reset_session_settings(req, sid, model):
    ws.reset_session_settings(sid, model)
    return get_session(req, sid)


@route("PUT", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)/settings/(?P<model>[a-z0-9_-]+)")
def set_line_settings(req, sid, lid, model):
    overrides = models.clean_settings(model, req["json"])
    base = ws.effective_settings(ws.load_session(sid), {"settings": {}}, model, models.default_settings(model))
    ws.set_line_settings(sid, lid, model, {key: value for key, value in overrides.items() if value != base.get(key)})
    return get_session(req, sid)


@route("DELETE", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)/settings")
def reset_line_settings(req, sid, lid):
    ws.reset_line_settings(sid, lid)
    return get_session(req, sid)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)/generate")
def generate_line(req, sid, lid):
    body = req["json"]
    model_names = body.get("models") or ws.load_session(sid)["models"]
    if not model_names:
        raise ws.WorkspaceError("Choose at least one model to generate with.")
    seed = body.get("seed")
    seed = _random_seed() if seed in (None, "") else int(seed)
    return _start_job(lambda job: _generate_line(sid, lid, model_names, seed, job), session=sid, kind="generate",
                      line=lid)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)/convert")
def convert_line(req, sid, lid):
    name = next((n for n in models.MODELS if models.MODELS[n].get("supports_convert") and models.is_installed(n)), None)
    if name is None:
        raise ws.WorkspaceError("Install Chatterbox Multilingual to convert recordings.")
    _, line, character, ref, sample = _line_context(sid, lid)
    sample_label = sample["label"] if sample else "default voice"
    recording = ws.new_recording_path(sid, lid)
    recording.write_bytes(req["raw"])

    def work(job):
        out = ws.new_take_path(sid, lid, f"{name}-vc")
        seconds = models.convert(name, str(recording), str(ref) if ref else None, str(out))
        ws.add_take(sid, lid, {
            "file": str(out), "kind": "convert", "model": f"{name}-vc", "character_name": character["name"],
            "sample_label": sample_label, "source_recording": str(recording),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "generation_seconds": seconds,
            "duration": round(ws.wav_duration(out), 2)})
    return _start_job(work, session=sid, kind="convert", line=lid)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)/takes/select")
def select_take(req, sid, lid):
    ws.select_take(sid, lid, req["json"]["file"])
    return get_session(req, sid)


@route("DELETE", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)/takes")
def delete_take(req, sid, lid):
    ws.delete_take(sid, lid, req["json"]["file"])
    return get_session(req, sid)


def _batch_job(req, sid, pick):
    """Generates the lines `pick(session)` returns, in script order, skipping empty ones. Cancelling the job (Stop)
    ends it at once, cutting off the current take."""
    body = req["json"]
    model_names = body.get("models") or ws.load_session(sid)["models"]
    if not model_names:
        raise ws.WorkspaceError("Choose at least one model to generate with.")
    seed = body.get("seed")
    stop = _stop_flags.setdefault(sid, threading.Event())
    stop.clear()

    def work(job):
        session = ws.load_session(sid)
        chosen = pick(session)
        lines = [line for line in chosen if line["text"].strip()]
        skipped = len(chosen) - len(lines)
        seeds = {line["id"]: _random_seed() if seed in (None, "") else int(seed) for line in lines}  # one per line
        # Model by model: each model loads once and does all its lines, then makes room for the next, instead of
        # swapping models on every line when they do not fit on the GPU together.
        steps = [(name, line["id"]) for name in model_names for line in lines
                 if name in _line_models(session, line, model_names)]
        done_lines = set()
        for number, (name, line_id) in enumerate(steps, 1):
            if stop.is_set():
                job["progress"] = f"Stopped after {number - 1} of {len(steps)} takes."
                return {"generated": len(done_lines), "skipped_empty": skipped}
            title = models.MODELS[name]["title"].split(" ")[0]
            job["progress"] = f"{title} \u00b7 take {number}/{len(steps)}"
            job["line"] = line_id
            try:
                _generate_line(sid, line_id, [name], seeds[line_id], job)
            except Cancelled:
                job["progress"] = f"Stopped after {number - 1} of {len(steps)} takes."
                raise
            done_lines.add(line_id)
        return {"generated": len(lines), "skipped_empty": skipped}
    return _start_job(work, session=sid, kind="batch")


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/generate-missing")
def generate_missing(req, sid):
    return _batch_job(req, sid, lambda session: [line for line in session["lines"] if not line["takes"]])


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/generate-lines")
def generate_lines(req, sid):
    wanted = set(req["json"].get("lines", []))
    return _batch_job(req, sid, lambda session: [line for line in session["lines"] if line["id"] in wanted])


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/lines/update")
def update_lines(req, sid):
    fields = req["json"].get("fields", {})
    if "language" in fields:
        _check_language(fields["language"], allow_none=True)
    ws.update_lines(sid, req["json"]["lines"], **fields)
    return get_session(req, sid)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/takes/clear")
def clear_takes(req, sid):
    removed = ws.clear_takes(sid, req["json"].get("lines", []))
    return {"removed": removed, "session": get_session(req, sid)}


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/lines/delete")
def delete_lines(req, sid):
    renamed = ws.delete_lines(sid, req["json"]["lines"])
    return {**get_session(req, sid), **({} if renamed else {"notice": RENAME_NOTICE})}


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/stop")
def stop_generation(req, sid):
    _stop_flags.setdefault(sid, threading.Event()).set()
    return {}


def _microphone_flag():
    return Path(models.LOCAL) / "webview" / "microphone-allowed"


def microphone_allowed():
    """Whether the user allowed the microphone before. The window then grants it without asking again (main.py);
    the server's port, and so the page's address, changes every launch, so the window's own memory does not help."""
    return _microphone_flag().exists()


@route("POST", "/api/microphone")
def remember_microphone(req):
    """The page reports the answer to the microphone prompt: allowed is remembered, blocked asks again next time."""
    flag = _microphone_flag()
    if req["json"].get("allowed") is True:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
    else:
        flag.unlink(missing_ok=True)
    return {}


PREFERENCES = {"volume", "dubSizes"}  # what the page keeps here: the playback volume, the Dub panes' sizes
_preferences_lock = threading.Lock()


def _preferences_file():
    return Path(models.LOCAL) / "webview" / "preferences.json"


@route("GET", "/api/preferences")
def get_preferences(req):
    """The page's preferences. Kept here, not in the page's storage: that belongs to the page's address, and the
    server's port (part of it) changes every launch."""
    return ws._read_json(_preferences_file()) or {}


@route("PATCH", "/api/preferences")
def set_preferences(req):
    unknown = set(req["json"]) - PREFERENCES
    if unknown:
        raise ws.WorkspaceError(f"Unknown preference: {', '.join(sorted(unknown))}.")
    with _preferences_lock:
        path = _preferences_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        ws._write_json(path, {**(ws._read_json(path) or {}), **req["json"]})
    return {}


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/export")
def export_session(req, sid):
    fmt, line = req["json"].get("format", "wav"), req["json"].get("line")  # line: export only that line
    return _start_job(lambda job: ws.export_session(sid, fmt, line).relative_to(ws.workspace_root()).as_posix(),
                      session=sid, kind="export")


@route("GET", "/api/sessions/(?P<sid>[0-9-]+)/jobs")
def session_jobs(req, sid):
    """Jobs of this session that are still running (generate, batch, convert, export)."""
    return [{key: job[key] for key in ("id", "kind", "line", "started", "progress")}
            for job in list(_jobs.values()) if job["session"] == sid and job["state"] == "running"]


EXPORT_INFO = {
    "wav": ("WAV", "Lossless, largest file. Best for editing."),
    "flac": ("FLAC", "Lossless and about half the size of WAV."),
    "mp3": ("MP3", "Small, plays everywhere. Good for sharing."),
    "ogg": ("OGG Vorbis", "Small, open format."),
}


@route("GET", "/api/sessions/(?P<sid>[0-9-]+)/exports")
def list_exports(req, sid):
    _session_or_404(sid)
    return ws.list_exports(sid)


@route("DELETE", "/api/sessions/(?P<sid>[0-9-]+)/exports")
def delete_export(req, sid):
    ws.delete_export(sid, str(req["json"].get("name", "")))
    return ws.list_exports(sid)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)/takes/trim")
def trim_take(req, sid, lid):
    body = req["json"]
    ws.trim_take(sid, lid, body["file"], float(body["start"]), float(body["end"]), replace=bool(body.get("replace")))
    return get_session(req, sid)


@route("GET", "/api/export-formats")
def export_formats(req):
    return [{"id": f, "label": EXPORT_INFO[f][0], "note": EXPORT_INFO[f][1]} for f in ws.export_formats()]


# --- Dubs ---------------------------------------------------------------------------------------


def _dub_or_404(did):
    data = dubs.load_dub(did)
    if data is None:
        raise NotFound()
    return data


def _dub_view(did, notice=None):
    data = _dub_or_404(did)
    folder = dubs.dub_dir(did) / "exports"
    exports = sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True) if folder.exists() else []
    return {**data, "stems": dubs.has_stems(did), "languages": dubs.languages(data), "fit": {code: dubs.fit(data, code) for code in dubs.languages(data)},
            **({"notice": notice} if notice else {}),
            "exports": [{"name": p.name, "path": p.relative_to(ws.workspace_root()).as_posix()} for p in exports]}


def _dub_language(req, data):
    """The dub language a request acts on: ?language=<code>, or the first one."""
    code = req["query"].get("language")
    if code is not None and code not in dubs.languages(data):
        raise ws.WorkspaceError("This dub has no such language.")
    return code or dubs.languages(data)[0]


def _dub_jobs(did):
    return [job for job in list(_jobs.values()) if job.get("dub") == did and job["state"] == "running"]


_dub_job_lock = threading.Lock()


def _dub_free(did):
    """One job at a time per dub: two would write the same take files, and transcribing deletes them."""
    if _dub_jobs(did):
        raise ws.WorkspaceError("This dub is already working. Wait for it to finish or cancel it.")


def _start_dub_job(did, work, kind, clips=None, language=None):
    with _dub_job_lock:  # checked and started together, so two quick clicks cannot both start
        _dub_free(did)
        started = _start_job(work, kind=kind, dub=did, clips=clips)
        _jobs[started["id"]]["language"] = language
        return started


@route("GET", "/api/dubs/(?P<did>[0-9-]+)/jobs")
def dub_jobs(req, did):
    """The dub's running job, so a screen opened later follows it again."""
    _dub_or_404(did)
    return [{"id": j["id"], "kind": j["kind"], "progress": j["progress"], "clips": j["clips"] or [],
             "language": j.get("language")} for j in _dub_jobs(did)]


@route("GET", "/api/dubs")
def list_dubs(req):
    return [{"id": did, "name": d["name"], "created": d["created"], "kind": d["source"]["kind"],
             "duration": d["source"]["duration"], "clips": len(d["tracks"][1]["clips"])} for did, d in dubs.list_dubs()]


@route("POST", "/api/dubs")
def create_dub(req):
    """The imported file as the raw body; its audio follows in POST /api/dubs/<id>/audio (decoded by the window)."""
    did = dubs.create_dub(req["query"].get("name", ""), req["raw"], req["query"].get("ext", ""))
    return _dub_view(did)


@route("POST", "/api/dubs/(?P<did>[0-9-]+)/audio")
def set_dub_audio(req, did):
    _dub_or_404(did)
    dubs.set_source_audio(did, req["raw"])
    return _dub_view(did)


@route("GET", "/api/dubs/(?P<did>[0-9-]+)")
def get_dub(req, did):
    return _dub_view(did)


@route("PATCH", "/api/dubs/(?P<did>[0-9-]+)")
def update_dub(req, did):
    """Name and the original's volume; model and settings are those of ?language (default: the first)."""
    code = _dub_language(req, _dub_or_404(did))
    body = req["json"]
    if "name" in body:
        dubs.rename_dub(did, str(body["name"]))
    model = body.get("model")
    if model is not None and model not in models.MODELS:
        raise ws.WorkspaceError("Choose a model.")
    settings = body.get("settings")
    if settings is not None:
        settings = {name: models.clean_settings(name, values) for name, values in settings.items()
                    if name in models.MODELS}
    volume = None if body.get("original_volume") is None else float(body["original_volume"])
    voices = None if body.get("voices_volume") is None else float(body["voices_volume"])
    dubs.set_options(did, original_volume=volume, voices_volume=voices)
    dubs.set_language_options(did, code, model=model, settings=settings)
    return _dub_view(did)


@route("POST", "/api/dubs/(?P<did>[0-9-]+)/languages")
def add_dub_language(req, did):
    _dub_or_404(did)
    dubs.add_language(did, _check_language(req["json"].get("language")))
    return _dub_view(did)


@route("DELETE", "/api/dubs/(?P<did>[0-9-]+)/languages/(?P<code>[a-z]{2,3}(?:-[A-Za-z0-9]+)?)")
def remove_dub_language(req, did, code):
    _dub_or_404(did)
    with _dub_job_lock:  # a generation cannot start for it between the check and the removal
        if any(j.get("language") == code for j in _dub_jobs(did)):
            raise ws.WorkspaceError("This language is generating. Wait for it to finish or cancel it.")
        dubs.remove_language(did, code)
    return _dub_view(did)


@route("DELETE", "/api/dubs/(?P<did>[0-9-]+)")
def delete_dub(req, did):
    _dub_or_404(did)
    dubs.delete_dub(did)
    return {}


@route("POST", "/api/dubs/(?P<did>[0-9-]+)/transcribe")
def transcribe_dub(req, did):
    """Whisper writes the sentences and their times; replaces every sentence, translation and take."""
    _dub_or_404(did)
    if not models.is_installed("whisper"):
        raise ws.WorkspaceError("Whisper is not installed. Install it in Models.")
    if not dubs.audio_path(did).exists():
        raise ws.WorkspaceError("The dub has no sound yet. Import the file again.")
    _dub_free(did)

    def work(job):
        # With Voice separation installed, the voices are separated first: Whisper hears them without the music.
        notice = None
        if models.is_installed("demucs") and not dubs.has_stems(did):
            try:
                _separate(job, did)
            except Cancelled:
                raise
            except Exception as error:  # e.g. out of GPU memory: the sentences can still be found in the full mix
                notice = f"The voices could not be separated ({error}); the full mix was used."
        if job.get("cancelled"):  # cancelled between separating and listening: nothing was being stopped
            raise Cancelled()
        audio = dubs.voices_path(did) if dubs.has_stems(did) else dubs.audio_path(did)
        job["progress"] = "Finding the sentences\u2026"
        job["model"] = "whisper"  # what cancelling stops
        try:
            heard = models.transcribe_segments(str(audio), None)
        except Exception:
            if job.get("cancelled"):
                raise Cancelled() from None
            raise
        finally:
            job["model"] = None
        if job.get("cancelled"):
            raise Cancelled()
        dubs.set_transcript(did, heard["language"], heard["segments"])
        notices = [notice, None if heard["segments"] else "No speech was found in this file."]
        return _dub_view(did, " ".join(n for n in notices if n) or None)
    return _start_dub_job(did, work, "transcribe")


def _separate(job, did):
    """Separates the dub's voices from its music and effects (Demucs). Written to temporary files and kept only when
    both are done, so a failure or a cancel leaves the stems as they were."""
    voices, background = dubs.stems_temp(did)
    job["progress"] = "Separating voices\u2026"
    job["model"] = "demucs"  # what cancelling stops
    try:
        models.separate(str(dubs.audio_path(did)), str(voices), str(background))
        if job.get("cancelled"):
            raise Cancelled()
    except Exception:
        for path in (voices, background):
            path.unlink(missing_ok=True)
        if job.get("cancelled"):
            raise Cancelled() from None
        raise
    finally:
        job["model"] = None
    dubs.keep_stems(did)


@route("POST", "/api/dubs/(?P<did>[0-9-]+)/separate")
def separate_dub(req, did):
    """Separates the voices of a dub that already has its sentences (they stay)."""
    _dub_or_404(did)
    if not models.is_installed("demucs"):
        raise ws.WorkspaceError("Voice separation is not installed. Install it in Models.")
    if not dubs.audio_path(did).exists():
        raise ws.WorkspaceError("The dub has no sound yet. Import the file again.")

    def work(job):
        _separate(job, did)
        return _dub_view(did)
    return _start_dub_job(did, work, "separate")


@route("DELETE", "/api/dubs/(?P<did>[0-9-]+)/separate")
def use_full_mix(req, did):
    """Deletes the separated voices and background: the original sound is used again."""
    _dub_or_404(did)
    with _dub_job_lock:
        _dub_free(did)
        dubs.remove_stems(did)
    return _dub_view(did)


@route("PATCH", "/api/dubs/(?P<did>[0-9-]+)/source/(?P<oid>o[0-9]+)")
def update_dub_source(req, did, oid):
    _dub_or_404(did)
    body = req["json"]
    if "text" in body:
        dubs.update_source_clip(did, oid, str(body["text"]))
    if "keep_original" in body:
        dubs.set_keep_original(did, oid, bool(body["keep_original"]))
    return _dub_view(did)


@route("DELETE", "/api/dubs/(?P<did>[0-9-]+)/source/(?P<oid>o[0-9]+)")
def delete_dub_source(req, did, oid):
    _dub_or_404(did)
    dubs.delete_source_clip(did, oid)
    return _dub_view(did)


@route("POST", "/api/dubs/(?P<did>[0-9-]+)/source/restore")
def restore_dub_sentence(req, did):
    """Undo of a deleted sentence: puts it back as it was."""
    _dub_or_404(did)
    body = req["json"]
    dubs.restore_sentence(did, dict(body["source"]), {str(k): dict(v) for k, v in (body.get("clips") or {}).items()},
                          int(body.get("index", 0)),
                          voices={str(k): [str(v) for v in ids] for k, ids in (body.get("voices") or {}).items()})
    return _dub_view(did)


@route("PATCH", "/api/dubs/(?P<did>[0-9-]+)/clips/(?P<cid>d[0-9]+)")
def update_dub_clip(req, did, cid):
    code = _dub_language(req, _dub_or_404(did))
    body = req["json"]
    dubs.update_dub_clip(did, cid, start=float(body["start"]) if "start" in body else None,
                         translation=body.get("translation"), voice_from=body.get("voice_from"), language=code)
    return _dub_view(did)


@route("PATCH", "/api/dubs/(?P<did>[0-9-]+)/translations")
def set_dub_translations(req, did):
    code = _dub_language(req, _dub_or_404(did))
    dubs.set_translations(did, dict(req["json"].get("translations") or {}), language=code)
    return _dub_view(did)


@route("POST", "/api/dubs/(?P<did>[0-9-]+)/clips/(?P<cid>d[0-9]+)/select")
def select_dub_take(req, did, cid):
    code = _dub_language(req, _dub_or_404(did))
    file = req["json"].get("file")
    dubs.select_take(did, cid, None if file is None else str(file), language=code)
    return _dub_view(did)


@route("POST", "/api/dubs/(?P<did>[0-9-]+)/takes/clear")
def clear_dub_takes(req, did):
    """Deletes every take of the language (?language), files included. Not while the dub is working."""
    code = _dub_language(req, _dub_or_404(did))
    with _dub_job_lock:
        _dub_free(did)
        removed = dubs.clear_takes(did, code)
    return {**_dub_view(did), "removed": removed}


@route("POST", "/api/dubs/(?P<did>[0-9-]+)/select")
def select_dub_takes(req, did):
    """Several sentences' takes in one request: {selections: {clip id: file or null}}."""
    code = _dub_language(req, _dub_or_404(did))
    selections = req["json"].get("selections") or {}
    dubs.select_takes(did, {str(k): None if v is None else str(v) for k, v in selections.items()}, language=code)
    return _dub_view(did)


@route("POST", "/api/dubs/(?P<did>[0-9-]+)/generate")
def generate_dub(req, did):
    """Speaks the given sentences' translations in the target language, each cloning its "voice from" sentence."""
    data = _dub_or_404(did)
    language = _dub_language(req, data)
    track = next(t for t in data["tracks"][1:] if t["language"] == language)
    name = track["model"]
    if name not in models.MODELS:
        raise ws.WorkspaceError("Choose a model for the dub.")
    if not models.is_installed(name):
        raise ws.WorkspaceError(f"{models.MODELS[name]['title']} is not installed. Install it in Models.")
    if language not in models.MODELS[name].get("languages", []):
        raise ws.WorkspaceError(f"{models.MODELS[name]['title']} does not support "
                                f"{models.LANGUAGE_NAMES.get(language, language)}.")
    ids = [str(c) for c in req["json"].get("clips", [])]
    _dub_free(did)
    seed = req["json"].get("seed")
    seed = None if seed in (None, "") else int(seed)

    def work(job):
        errors = []
        for i, cid in enumerate(ids, 1):
            if job.get("cancelled"):
                raise Cancelled()
            job["progress"] = f"Sentence {i} of {len(ids)}"
            current = dubs.load_dub(did)
            track_now = next((t for t in current["tracks"][1:] if t["language"] == language), None)
            if track_now is None:
                break  # the language was removed meanwhile
            clips = track_now["clips"]
            number = next((n for n, c in enumerate(clips, 1) if c["id"] == cid), None)
            if number is None:
                continue  # deleted meanwhile
            clip = clips[number - 1]
            if any(s["id"] == clip["source_clip"] and s.get("keep_original") for s in current["tracks"][0]["clips"]):
                errors.append(f"Sentence {number} keeps the original.")
                continue
            text = models.text_for(name, clip["translation"])
            if not models.has_words(text):
                errors.append(f"Sentence {number} has no translation yet.")
                continue
            ref, ref_text = dubs.cut_reference(did, cid, language)
            settings = models.validate_settings(name, track_now["settings"].get(name, {}))
            take_seed = _random_seed() if seed is None else seed
            out = dubs.new_take_path(did, cid, language)
            # A model that can fix its length is told where the speaker stops.
            timed = {"timing": dubs.generation_timing(did, cid, language)} if models.MODELS[name].get("timed") else {}
            job["model"] = name  # what cancelling stops
            try:
                seconds = models.generate(name, text, str(ref), str(out), take_seed, settings, language,
                                          ref_text=ref_text, **timed)
            except Exception as error:
                if job.get("cancelled"):
                    out.unlink(missing_ok=True)  # a take cut off halfway
                    raise Cancelled() from None
                errors.append(f"Sentence {number}: {error}")
                continue
            finally:
                job["model"] = None
            if ws.wav_duration(out) < 0.05:  # no sound: the window cannot play it
                out.unlink(missing_ok=True)
                errors.append(f"Sentence {number}: the model returned no sound. Generate it again or change the translation.")
                continue
            dubs.match_level(did, cid, out, language)  # as loud as its sentence was spoken
            dubs.add_take(did, cid, {"file": str(out), "seed": take_seed, "model": name, "settings": settings,
                                     "language": language, "text": clip["translation"],
                                     "generation_seconds": seconds, "duration": round(ws.wav_duration(out), 2)},
                          language)
        if errors:
            raise RuntimeError(" ".join(errors))
        return _dub_view(did)
    return _start_dub_job(did, work, "generate", ids, language)


@route("POST", "/api/dubs/(?P<did>[0-9-]+)/fit")
def fit_dub(req, did):
    """Fits the given sentences' takes, as a job: too long ones sped up to end before the next sentence, too short ones
    slowed to end with their speaker. One sentence that cannot be fitted fails with the reason; several report how many
    were fitted and how many need a shorter or a longer translation."""
    language = _dub_language(req, _dub_or_404(did))
    ids = [str(c) for c in req["json"].get("clips", [])]
    _dub_free(did)

    def work(job):
        fitted, shorter, longer, problems = 0, [], [], []
        for i, cid in enumerate(ids, 1):
            if job.get("cancelled"):
                raise Cancelled()
            job["progress"] = f"Sentence {i} of {len(ids)}"
            try:
                dubs.fit_take(did, cid, language)
                fitted += 1
            except dubs.NeedsShorter as error:
                shorter.append(str(error))
            except dubs.NeedsLonger as error:
                longer.append(str(error))
            except ws.WorkspaceError as error:
                problems.append(str(error))
        if len(ids) == 1 and (shorter or longer or problems):
            raise ws.WorkspaceError((shorter + longer + problems)[0])
        notice = f"Fitted {fitted} sentence{'' if fitted == 1 else 's'}."
        if shorter:
            notice += f" {len(shorter)} need{'s' if len(shorter) == 1 else ''} a shorter translation."
        if longer:
            notice += f" {len(longer)} need{'s' if len(longer) == 1 else ''} a longer translation."
        if problems:
            notice += f" {len(problems)} could not be fitted: {problems[0]}"
        return _dub_view(did, notice)
    return _start_dub_job(did, work, "fit", ids, language)


@route("POST", "/api/dubs/(?P<did>[0-9-]+)/export")
def export_dub(req, did):
    code = _dub_language(req, _dub_or_404(did))
    out = dubs.export_dub(did, str(req["json"].get("format", "wav")), code)
    return {"path": out.relative_to(ws.workspace_root()).as_posix()}


# --- HTTP ---------------------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the console for real problems
        pass

    def _send(self, status, body=b"", content_type="application/json", headers=None):
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, value):
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def _host_ok(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_address[1]}"

    def _handle(self, method):
        if not self._host_ok():
            return self._send(403)
        url = urlparse(self.path)
        path = url.path
        if method == "GET" and path == "/":
            return self._index()
        if method == "GET" and path.startswith("/ui/"):
            return self._file(_ui_dir, unquote(path[len("/ui/"):]), STATIC_TYPES)
        if method == "GET" and path.startswith("/files/"):
            return self._file(ws.workspace_root(), unquote(path[len("/files/"):]), MEDIA_TYPES, ranges=True)
        if not path.startswith("/api/"):
            return self._send(404)
        if not secrets.compare_digest(self.headers.get("X-Vokalit-Token", ""), _token):
            return self._send(403)
        for route_method, pattern, fn in _routes:
            match = pattern.match(path)
            if route_method == method and match:
                return self._call(fn, match.groupdict(), url)
        return self._send(404)

    def _call(self, fn, args, url):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        is_json = self.headers.get("Content-Type", "").startswith("application/json")
        req = {"raw": raw, "json": json.loads(raw) if raw and is_json else {},
               "query": {k: v[0] for k, v in parse_qs(url.query).items()}}
        try:
            self._json(200, fn(req, **args))
        except NotFound:
            self._send(404)
        except (ws.WorkspaceError, ValueError) as error:
            self._json(400, {"error": str(error)})
        except Exception as error:
            self._json(500, {"error": f"Unexpected error: {error}"})

    def _index(self):
        page = (_ui_dir / "index.html").read_text(encoding="utf-8")
        page = page.replace("</head>", f'<meta name="vokalit-token" content="{_token}">\n</head>', 1)
        self._send(200, page.encode("utf-8"), STATIC_TYPES[".html"])

    def _file(self, root, relative, types, ranges=False):
        root = Path(root).resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file() or target.suffix not in types:
            return self._send(404)
        # Byte ranges let <audio> and <video> seek (clicking a waveform); without them they restart from 0.
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip()) if ranges else None
        if not match or not (match.group(1) or match.group(2)):
            accept = {"Accept-Ranges": "bytes"} if ranges else None
            return self._send(200, target.read_bytes(), types[target.suffix], accept)
        size = target.stat().st_size  # only the requested bytes are read: a dub's video can be large
        if match.group(1):
            start, end = int(match.group(1)), min(int(match.group(2) or size - 1), size - 1)
        else:  # last N bytes
            start, end = max(0, size - int(match.group(2))), size - 1
        if start >= size or start > end:
            return self._send(416, b"", types[target.suffix], {"Content-Range": f"bytes */{size}"})
        if not match.group(2):  # "bytes=N-": a part at a time, the player asks for the rest
            end = min(end, start + RANGE_CHUNK - 1)
        with open(target, "rb") as f:
            f.seek(start)
            part = f.read(end - start + 1)
        self._send(206, part, types[target.suffix],
                   {"Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{size}"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


def start(ui_dir, port=0):
    """Starts serving in a background thread. Returns (base URL, token)."""
    global _httpd, _token, _ui_dir
    _ui_dir = Path(ui_dir)
    _token = secrets.token_urlsafe(24)
    _httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=_httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{_httpd.server_address[1]}/", _token


def stop():
    global _httpd
    if _httpd:
        _httpd.shutdown()
        _httpd.server_close()
        _httpd = None
