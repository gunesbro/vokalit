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
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

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


def _start_job(work, session=None, kind=None, line=None):
    """Runs work(job) in a thread; the UI polls GET /api/jobs/<id>. Jobs tagged with a session are listed by
    GET /api/sessions/<sid>/jobs, so a screen opened later (or after switching tabs) shows them again."""
    job = {"id": uuid.uuid4().hex, "state": "running", "progress": "", "log": "", "result": None, "error": "",
           "session": session, "kind": kind, "line": line, "started": time.time()}
    _jobs[job["id"]] = job

    def run():
        try:
            job["result"] = work(job)
            job["state"] = "done"
        except Exception as error:  # shown to the user
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
            "frees_gb": round(models.sizes()["frees"].get(name, 0.0), 1) if installed else None,
            "settings": info["settings"], "supports_convert": info.get("supports_convert", False),
            "languages": [{"code": c, "name": models.LANGUAGE_NAMES[c]} for c in info.get("languages", [])],
            "accent_setting": info.get("accent_setting")}


def _component_view(name):
    """A row of the Models screen: Whisper (a tool) or a voice model."""
    info = models.spec(name)
    installed = models.is_installed(name)
    view = _model_view(name) if name in models.MODELS else {
        "name": name, "title": info["title"], "summary": info["summary"], "url": info["url"],
        "license": info["license"], "disk_gb": info["disk_gb"], "installed": installed,
        "frees_gb": round(models.sizes()["frees"].get(name, 0.0), 1) if installed else None}
    return {**view, "kind": "model" if name in models.MODELS else "tool", "recommended": info.get("recommended", False)}


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
    return session, line, character, ref, (sample["label"] if sample else "default voice")


def _generate_line(session_id, line_id, model_names, seed):
    session, line, character, ref, sample_label = _line_context(session_id, line_id)
    if not line["text"].strip():
        number = next(i for i, l in enumerate(session["lines"], 1) if l["id"] == line_id)
        raise ws.WorkspaceError(f"Line {number} is empty. Write its text first.")
    language = ws.effective_language(session, line)
    errors = []
    for name in model_names:
        if not models.is_installed(name):
            errors.append(f"{models.MODELS[name]['title']} is not installed.")
            continue
        if language not in models.MODELS[name].get("languages", []):
            errors.append(f"{models.MODELS[name]['title']} does not support "
                          f"{models.LANGUAGE_NAMES.get(language, language)}.")
            continue
        settings = ws.effective_settings(session, line, name, models.default_settings(name))
        out = ws.new_take_path(session_id, line_id, name)
        try:
            seconds = models.generate(name, line["text"], str(ref) if ref else None, str(out), seed, settings, language)
        except Exception as error:
            errors.append(f"{models.MODELS[name]['title']}: {error}")
            continue
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
    return {"items": [_component_view(name) for name in names], "total_gb": round(models.sizes()["total_gb"], 1),
            "installing": models.installing()}


@route("POST", "/api/models/(?P<name>[a-z0-9_-]+)/install")
def install_model(req, name):
    _check_component(name)

    def work(job):
        for kind, text in models.install(name):
            if kind == "status":
                job["progress"] = text
            else:
                job["log"] += text
        if name == "whisper":
            transcribe_missing()
        return _component_view(name)
    return _start_job(work)


@route("POST", "/api/models/(?P<name>[a-z0-9_-]+)/cancel")
def cancel_model(req, name):
    _check_component(name)
    models.cancel_install(name)
    return {}


@route("POST", "/api/models/(?P<name>[a-z0-9_-]+)/remove")
def remove_model(req, name):
    _check_component(name)
    models.remove(name)
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
    models.validate_settings(model, req["json"])
    ws.set_line_settings(sid, lid, model, req["json"])
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
    return _start_job(lambda job: _generate_line(sid, lid, model_names, seed), session=sid, kind="generate", line=lid)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)/convert")
def convert_line(req, sid, lid):
    name = next((n for n in models.MODELS if models.MODELS[n].get("supports_convert") and models.is_installed(n)), None)
    if name is None:
        raise ws.WorkspaceError("Install Chatterbox Multilingual to convert recordings.")
    _, line, character, ref, sample_label = _line_context(sid, lid)
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
    """Generates the lines `pick(session)` returns, in script order, skipping empty ones; Stop ends it after the
    current line."""
    body = req["json"]
    model_names = body.get("models") or ws.load_session(sid)["models"]
    if not model_names:
        raise ws.WorkspaceError("Choose at least one model to generate with.")
    seed = body.get("seed")
    stop = _stop_flags.setdefault(sid, threading.Event())
    stop.clear()

    def work(job):
        chosen = pick(ws.load_session(sid))
        todo = [line["id"] for line in chosen if line["text"].strip()]
        skipped = len(chosen) - len(todo)
        for number, line_id in enumerate(todo, 1):
            if stop.is_set():
                job["progress"] = f"Stopped after {number - 1} of {len(todo)} lines."
                return {"generated": number - 1, "skipped_empty": skipped}
            job["progress"] = f"Line {number}/{len(todo)}"
            job["line"] = line_id
            _generate_line(sid, line_id, model_names, _random_seed() if seed in (None, "") else int(seed))
        return {"generated": len(todo), "skipped_empty": skipped}
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


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/export")
def export_session(req, sid):
    fmt = req["json"].get("format", "wav")
    return _start_job(lambda job: ws.export_session(sid, fmt).relative_to(ws.workspace_root()).as_posix(),
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
            return self._file(ws.workspace_root(), unquote(path[len("/files/"):]), AUDIO_TYPES, ranges=True)
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
        data = target.read_bytes()
        if not ranges:
            return self._send(200, data, types[target.suffix])
        # Byte ranges let the <audio> element seek (clicking a waveform); without them it restarts from 0.
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        if not match or not (match.group(1) or match.group(2)):
            return self._send(200, data, types[target.suffix], {"Accept-Ranges": "bytes"})
        size = len(data)
        if match.group(1):
            start, end = int(match.group(1)), min(int(match.group(2) or size - 1), size - 1)
        else:  # last N bytes
            start, end = max(0, size - int(match.group(2))), size - 1
        if start >= size or start > end:
            return self._send(416, b"", types[target.suffix], {"Content-Range": f"bytes */{size}"})
        self._send(206, data[start:end + 1], types[target.suffix],
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
