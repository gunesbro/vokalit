"""Local HTTP server for the UI: static page, workspace audio files and a JSON API.

Listens on 127.0.0.1 only. Every API request must carry the per-run token; requests for another
Host are refused (DNS rebinding); the page may load nothing from outside (CSP). See spec 4.1.
"""
import json
import random
import re
import secrets
import subprocess
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
                ".svg": "image/svg+xml", ".json": "application/json"}

_httpd = None
_token = None
_ui_dir = None
_jobs = {}
_stop_flags = {}


class NotFound(Exception):
    pass


# --- Jobs ---------------------------------------------------------------------------------------


def _start_job(work):
    """Runs work(job) in a thread; the UI polls GET /api/jobs/<id>."""
    job = {"id": uuid.uuid4().hex, "state": "running", "progress": "", "log": "", "result": None, "error": ""}
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
            "size_gb": round(models.size_gb(name), 1) if installed else None,
            "settings": info["settings"], "supports_convert": info.get("supports_convert", False)}


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
    errors = []
    for name in model_names:
        if not models.is_installed(name):
            errors.append(f"{models.MODELS[name]['title']} is not installed.")
            continue
        settings = ws.effective_settings(session, line, name, models.default_settings(name))
        out = ws.new_take_path(session_id, line_id, name)
        try:
            seconds = models.generate(name, line["text"], str(ref) if ref else None, str(out), seed, settings)
        except Exception as error:
            errors.append(f"{models.MODELS[name]['title']}: {error}")
            continue
        ws.add_take(session_id, line_id, {
            "file": str(out), "kind": "tts", "model": name, "character_name": character["name"],
            "sample_label": sample_label, "text": line["text"], "seed": seed, "settings": settings,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "generation_seconds": seconds,
            "duration": round(ws.wav_duration(out), 2)})
    if errors:
        raise RuntimeError(" ".join(errors))


def _random_seed():
    return random.randint(0, 2**31 - 1)


# --- Routes -------------------------------------------------------------------------------------

_routes = []


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
    return {"gpu": _gpu_name()}


@route("GET", "/api/models")
def list_models(req):
    return [_model_view(name) for name in models.MODELS]


@route("POST", "/api/models/(?P<name>[a-z0-9_-]+)/install")
def install_model(req, name):
    def work(job):
        for kind, text in models.install(name):
            if kind == "status":
                job["progress"] = text
            else:
                job["log"] += text
        return _model_view(name)
    return _start_job(work)


@route("POST", "/api/models/(?P<name>[a-z0-9_-]+)/cancel")
def cancel_model(req, name):
    models.cancel_install(name)
    return {}


@route("POST", "/api/models/(?P<name>[a-z0-9_-]+)/remove")
def remove_model(req, name):
    models.remove(name)
    return _model_view(name)


@route("GET", "/api/characters")
def list_characters(req):
    return [{**data, "id": cid, "used_in": ws.sessions_using(cid)} for cid, data in ws.list_characters()]


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
    return {**data, "id": cid, "used_in": [] if _session_arg(req) else ws.sessions_using(cid)}


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
    upload = ws.workspace_temp_file(".wav")
    upload.write_bytes(req["raw"])
    try:
        ws.add_sample(cid, str(upload), req["query"].get("source", "upload"), _session_arg(req))
    finally:
        upload.unlink(missing_ok=True)
    return get_character(req, cid)


@route("PATCH", "/api/characters/(?P<cid>[0-9-]+)/samples/(?P<sample_id>s[0-9]+)")
def update_sample(req, cid, sample_id):
    if "label" in req["json"]:
        ws.set_sample_label(cid, sample_id, req["json"]["label"], _session_arg(req))
    if req["json"].get("default"):
        ws.set_default_sample(cid, sample_id, _session_arg(req))
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
    return _session_view(_session_or_404(sid))


@route("PATCH", "/api/sessions/(?P<sid>[0-9-]+)")
def update_session(req, sid):
    _session_or_404(sid)
    if "name" in req["json"]:
        ws.rename_session(sid, req["json"]["name"])
    if "models" in req["json"]:
        ws.set_session_models(sid, req["json"]["models"])
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
    ws.update_line(sid, lid, **req["json"])
    return get_session(req, sid)


@route("DELETE", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)")
def delete_line(req, sid, lid):
    ws.delete_line(sid, lid)
    return get_session(req, sid)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/lines/order")
def reorder_lines(req, sid):
    ws.reorder_lines(sid, req["json"]["order"])
    return get_session(req, sid)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/paste")
def paste_script(req, sid):
    added = ws.paste_script(sid, req["json"]["text"])
    return {"added": added, "session": get_session(req, sid)}


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
    return _start_job(lambda job: _generate_line(sid, lid, model_names, seed))


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
    return _start_job(work)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)/takes/select")
def select_take(req, sid, lid):
    ws.select_take(sid, lid, req["json"]["file"])
    return get_session(req, sid)


@route("DELETE", "/api/sessions/(?P<sid>[0-9-]+)/lines/(?P<lid>l[0-9]+)/takes")
def delete_take(req, sid, lid):
    ws.delete_take(sid, lid, req["json"]["file"])
    return get_session(req, sid)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/generate-missing")
def generate_missing(req, sid):
    body = req["json"]
    model_names = body.get("models") or ws.load_session(sid)["models"]
    if not model_names:
        raise ws.WorkspaceError("Choose at least one model to generate with.")
    seed = body.get("seed")
    stop = _stop_flags.setdefault(sid, threading.Event())
    stop.clear()

    def work(job):
        todo = [line["id"] for line in ws.load_session(sid)["lines"] if not line["takes"]]
        for number, line_id in enumerate(todo, 1):
            if stop.is_set():
                job["progress"] = f"Stopped after {number - 1} of {len(todo)} lines."
                return {"generated": number - 1}
            job["progress"] = f"Line {number}/{len(todo)}"
            _generate_line(sid, line_id, model_names, _random_seed() if seed in (None, "") else int(seed))
        return {"generated": len(todo)}
    return _start_job(work)


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/stop")
def stop_generation(req, sid):
    _stop_flags.setdefault(sid, threading.Event()).set()
    return {}


@route("POST", "/api/sessions/(?P<sid>[0-9-]+)/export")
def export_session(req, sid):
    return _start_job(lambda job: ws.export_session(sid).relative_to(ws.workspace_root()).as_posix())


# --- HTTP ---------------------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the console for real problems
        pass

    def _send(self, status, body=b"", content_type="application/json"):
        self.send_response(status)
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
            return self._file(ws.workspace_root(), unquote(path[len("/files/"):]), {".wav": "audio/wav"})
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

    def _file(self, root, relative, types):
        root = Path(root).resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file() or target.suffix not in types:
            return self._send(404)
        self._send(200, target.read_bytes(), types[target.suffix])

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
