"""Model install/remove and worker processes. See SPEC.md §5 and §6."""
import contextlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCAL = os.path.join(ROOT, ".local")
UV = os.environ["VOKALIT_UV"]  # set by the start scripts

TORCH_CUDA = ["torch==2.8.0", "torchaudio==2.8.0", "--index-url", "https://download.pytorch.org/whl/cu128"]

# Display names for language codes (ISO 639-1). A model lists the codes it supports in MODELS[name]["languages"].
LANGUAGE_NAMES = {
    "ar": "Arabic", "da": "Danish", "de": "German", "el": "Greek", "en": "English", "es": "Spanish",
    "fi": "Finnish", "fr": "French", "he": "Hebrew", "hi": "Hindi", "it": "Italian", "ja": "Japanese",
    "ko": "Korean", "ms": "Malay", "nl": "Dutch", "no": "Norwegian", "pl": "Polish", "pt": "Portuguese",
    "ru": "Russian", "sv": "Swedish", "sw": "Swahili", "tr": "Turkish", "zh": "Chinese",
}

MODELS = {
    "chatterbox": {
        "title": "Chatterbox Multilingual",
        "summary": "23 languages \u00b7 cloning \u00b7 voice conversion",
        "url": "https://huggingface.co/ResembleAI/chatterbox",
        "disk_gb": 11.3,  # measured on Windows (SPEC.md §6.1)
        "license": "MIT",
        "supports_convert": True,
        "languages": ["ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja", "ko", "ms", "nl", "no",
                      "pl", "pt", "ru", "sv", "sw", "tr", "zh"],
        # When the sample's language differs from the line's, this setting value reduces the carried-over accent
        # (Chatterbox's own advice: cfg_weight 0).
        "accent_setting": {"key": "cfg_weight", "value": 0.0},
        "settings": [
            {"key": "exaggeration", "label": "Expressiveness", "min": 0.25, "max": 2.0, "step": 0.05, "default": 0.5,
             "help": "Higher is more emotional and dramatic. Above 1 can get unstable."},
            {"key": "cfg_weight", "label": "Pace control", "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.5,
             "help": "Lower gives slower, more deliberate speech. Try 0 if the accent drifts."},
            {"key": "temperature", "label": "Variation", "min": 0.05, "max": 5.0, "step": 0.05, "default": 0.8,
             "help": "Higher makes each take differ more."},
        ],
        "pip_steps": [
            ("PyTorch with CUDA", TORCH_CUDA),
            ("Other libraries", ["-r", os.path.join(ROOT, "workers", "chatterbox", "requirements.txt")]),
            ("Chatterbox", ["--no-deps", "chatterbox-tts==0.1.7"]),
        ],
    },
}

_workers = {}
_cancelled = set()


class Cancelled(Exception):
    pass


def model_dir(name):
    return os.path.join(LOCAL, name)


def _python(name):
    venv = os.path.join(model_dir(name), "venv")
    return os.path.join(venv, "Scripts", "python.exe") if sys.platform == "win32" else os.path.join(venv, "bin", "python")


def _worker_script(name):
    return os.path.join(ROOT, "workers", name, "worker.py")


def _marker(name):
    return os.path.join(model_dir(name), "installed")


def is_installed(name):
    return os.path.exists(_marker(name))


def installed_size_gb(name):
    """Disk use of an installed model. Measured once at install and kept in the marker file: walking tens of
    thousands of files on every request made the Models and Studio screens slow."""
    try:
        with open(_marker(name), encoding="utf-8") as f:
            return float(f.read().strip())
    except ValueError:  # installed before sizes were stored
        size = round(size_gb(name), 2)
        with open(_marker(name), "w", encoding="utf-8") as f:
            f.write(f"{size:.2f}")
        return size


def size_gb(name):
    seen, total = set(), 0
    for folder, _, files in os.walk(model_dir(name)):
        for file in files:
            try:
                stat = os.lstat(os.path.join(folder, file))
            except FileNotFoundError:  # a temporary file removed during an install
                continue
            if (stat.st_dev, stat.st_ino) not in seen:  # hard links count once
                seen.add((stat.st_dev, stat.st_ino))
                total += stat.st_size
    return total / 1e9


def _env(name, offline):
    cache = os.path.join(model_dir(name), "cache")
    env = dict(os.environ, HF_HOME=cache, TORCH_HOME=cache, HF_HUB_DISABLE_TELEMETRY="1", PYTHONUTF8="1")
    if offline:
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return env


def _run(command, env):
    """Runs a command. Yields its output lines, and None every few seconds while it is silent."""
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True, encoding="utf-8", errors="replace"
    )
    lines = queue.Queue()

    def read():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    try:
        while True:
            try:
                line = lines.get(timeout=3)
            except queue.Empty:
                yield None
                continue
            if line is None:
                break
            yield line
        returncode = process.wait()
    finally:
        if process.poll() is None:  # stopped early (cancel or error)
            process.kill()
    if returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}")


def install(name):
    """Yields ("log", line) and ("status", text). On failure or cancel removes the half-installed model and raises."""
    remove(name)  # leftovers of an interrupted install
    _cancelled.discard(name)
    env = _env(name, offline=False)
    # A per-model uv cache: its growth shows download progress, and it is deleted after the install.
    uv_cache = os.path.join(model_dir(name), "uv-cache")
    env["UV_CACHE_DIR"] = uv_cache
    steps = [("Python environment", [UV, "venv", "--python", "3.11", os.path.join(model_dir(name), "venv")])]
    for label, args in MODELS[name]["pip_steps"]:
        steps.append((label, [UV, "pip", "install", "--python", _python(name), *args]))
    steps.append(("Model weights", [_python(name), _worker_script(name), "--download"]))
    started = last_status = time.monotonic()
    try:
        for number, (label, command) in enumerate(steps, 1):
            yield "log", f"--- Step {number}/{len(steps)}: {label}\n"
            with contextlib.closing(_run(command, env)) as output:
                for line in output:
                    if name in _cancelled:
                        raise Cancelled()
                    if line:
                        yield "log", line
                    now = time.monotonic()
                    if now - last_status >= 3:
                        last_status = now
                        elapsed = int(now - started)
                        size = size_gb(name)
                        percent = min(99, int(100 * size / MODELS[name]["disk_gb"]))
                        yield "status", (
                            f"Step {number}/{len(steps)}: {label} · {percent}% · "
                            f"{size:.2f} of ~{MODELS[name]['disk_gb']} GB · {elapsed // 60}m {elapsed % 60:02d}s"
                        )
    except Exception:
        remove(name)
        raise
    shutil.rmtree(uv_cache, ignore_errors=True)  # the venv keeps its own (hard-linked) copies
    size = round(size_gb(name), 2)
    with open(_marker(name), "w", encoding="utf-8") as f:
        f.write(f"{size:.2f}")
    yield "log", f"Done. Disk usage: {size:.1f} GB\n"


def cancel_install(name):
    """The running install stops within a few seconds and cleans up."""
    _cancelled.add(name)


def remove(name):
    stop(name)
    shutil.rmtree(model_dir(name), ignore_errors=True)


class _Worker:
    def __init__(self, name):
        self.lock = threading.Lock()
        # stderr is inherited, so the worker's logs appear in the console window.
        self.process = subprocess.Popen(
            [_python(name), _worker_script(name)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=_env(name, offline=True),
            text=True,
            encoding="utf-8",
        )
        ready = self._read()
        if not ready.get("ready"):
            self.process.kill()
            raise RuntimeError(ready.get("error", "The model failed to start."))

    def _read(self):
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("The model process stopped unexpectedly. See the console window for details.")
        return json.loads(line)

    def request(self, message):
        with self.lock:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
            return self._read()


def default_settings(name):
    return {s["key"]: s["default"] for s in MODELS[name]["settings"]}


def validate_settings(name, settings):
    """Fills in defaults. ValueError on a key the model does not declare or a value out of range."""
    spec = {s["key"]: s for s in MODELS[name]["settings"]}
    for key, value in settings.items():
        if key not in spec:
            raise ValueError(f"{MODELS[name]['title']} has no setting '{key}'.")
        if not spec[key]["min"] <= value <= spec[key]["max"]:
            raise ValueError(f"{spec[key]['label']} must be between {spec[key]['min']} and {spec[key]['max']}.")
    return {**default_settings(name), **settings}


def _ask(name, message):
    """Sends one request to the model's worker. The model is loaded on first use and stays loaded."""
    try:
        if name not in _workers:
            _workers[name] = _Worker(name)
        reply = _workers[name].request(message)
    except Exception:
        stop(name)
        raise
    if not reply["ok"]:
        raise RuntimeError(reply["error"])
    return reply["seconds"]


def generate(name, text, ref, out, seed, settings, language):
    """Returns the generation time in seconds."""
    if language not in MODELS[name].get("languages", []):
        raise ValueError(f"{MODELS[name]['title']} does not support {LANGUAGE_NAMES.get(language, language)}.")
    settings = validate_settings(name, settings)
    return _ask(name, {"text": text, "ref": ref, "out": out, "seed": seed, "settings": settings, "language": language})


def convert(name, source, ref, out):
    """Speaks `source` (the user's recording) in the voice of `ref` (None = built-in voice)."""
    if not MODELS[name].get("supports_convert"):
        raise RuntimeError(f"{MODELS[name]['title']} does not support voice conversion.")
    return _ask(name, {"task": "convert", "source": source, "ref": ref, "out": out})


def stop(name):
    worker = _workers.pop(name, None)
    if worker:
        worker.process.kill()


def stop_all():
    for name in list(_workers):
        stop(name)
