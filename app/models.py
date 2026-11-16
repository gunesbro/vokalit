"""Model install/remove and worker processes. See SPEC.md §5 and §6."""
import json
import os
import shutil
import subprocess
import sys
import threading

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCAL = os.path.join(ROOT, ".local")
UV = os.environ["VOKALIT_UV"]  # set by the start scripts

TORCH_CUDA = ["torch==2.8.0", "torchaudio==2.8.0", "--index-url", "https://download.pytorch.org/whl/cu128"]

MODELS = {
    "chatterbox": {
        "title": "Chatterbox Multilingual",
        "source": "ResembleAI/chatterbox (Hugging Face)",
        "approx_download": "~6-8 GB (PyTorch with CUDA ~4-5 GB, other libraries, model ~2 GB)",
        "license": "MIT",
        "pip_steps": [
            TORCH_CUDA,
            ["-r", os.path.join(ROOT, "workers", "chatterbox", "requirements.txt")],
            ["--no-deps", "chatterbox-tts==0.1.7"],
        ],
    },
}

_workers = {}


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


def size_gb(name):
    total = 0
    for folder, _, files in os.walk(model_dir(name)):
        for file in files:
            path = os.path.join(folder, file)
            if not os.path.islink(path):
                total += os.path.getsize(path)
    return total / 1e9


def _env(name, offline):
    cache = os.path.join(model_dir(name), "cache")
    env = dict(os.environ, HF_HOME=cache, TORCH_HOME=cache, HF_HUB_DISABLE_TELEMETRY="1", PYTHONUTF8="1")
    if offline:
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return env


def _run(command, env):
    """Runs a command and yields its output lines."""
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True, encoding="utf-8", errors="replace"
    )
    yield from process.stdout
    if process.wait() != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}")


def install(name):
    """Yields log lines. On failure removes the half-installed model and raises."""
    env = _env(name, offline=False)
    try:
        yield from _run([UV, "venv", "--python", "3.11", os.path.join(model_dir(name), "venv")], env)
        for step in MODELS[name]["pip_steps"]:
            # --no-cache: nothing stays in the shared uv cache, so Remove frees all the space.
            yield from _run([UV, "pip", "install", "--no-cache", "--python", _python(name), *step], env)
        yield "Downloading model weights...\n"
        yield from _run([_python(name), _worker_script(name), "--download"], env)
    except Exception:
        remove(name)
        raise
    open(_marker(name), "w").close()
    yield f"Done. Disk usage: {size_gb(name):.1f} GB\n"


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


def generate(name, text, ref, out):
    """Returns the generation time in seconds. The model is loaded on first use and stays loaded."""
    try:
        if name not in _workers:
            _workers[name] = _Worker(name)
        reply = _workers[name].request({"text": text, "ref": ref, "out": out})
    except Exception:
        stop(name)
        raise
    if not reply["ok"]:
        raise RuntimeError(reply["error"])
    return reply["seconds"]


def stop(name):
    worker = _workers.pop(name, None)
    if worker:
        worker.process.kill()


def stop_all():
    for name in list(_workers):
        stop(name)
