"""Model install/remove and worker processes. See SPEC.md §5 and §6."""
import contextlib
import json
import os
import queue
import re
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

# OmniVoice's own list (646 languages, ISO 639 codes) read from the package it installs, in English. Vokalit's names
# above win where both have one.
with open(os.path.join(os.path.dirname(__file__), "omnivoice_languages.json"), encoding="utf-8") as _f:
    _OMNIVOICE_LANGUAGES = json.load(_f)["languages"]
LANGUAGE_NAMES = {**_OMNIVOICE_LANGUAGES, **LANGUAGE_NAMES}


MODELS = {
    "chatterbox": {
        "title": "Chatterbox Multilingual",
        "summary": "23 languages \u00b7 cloning \u00b7 voice conversion",
        "url": "https://huggingface.co/ResembleAI/chatterbox",
        "disk_gb": 12.3,  # measured on Windows (SPEC.md §6.1)
        "license": "MIT",
        "supports_convert": True,
        "supports_tags": False,  # [laughter] and the like would be read aloud: they are removed from its text
        "needs_transcript": False,
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
    "omnivoice": {
        "title": "OmniVoice",
        "summary": "600+ languages \u00b7 cloning \u00b7 sound tags",
        "url": "https://huggingface.co/k2-fsa/OmniVoice",
        "disk_gb": 9.0,  # estimate until measured on Windows
        "license": "CC-BY-NC (non-commercial)",  # the weights, because of the training data; the code is Apache 2.0
        "supports_convert": False,
        "supports_tags": True,
        "needs_transcript": True,  # it copies a voice from the sample and what is said in it
        # Every language it lists, and "ar" (Chatterbox's Arabic), which it calls Standard Arabic.
        "languages": sorted(set(_OMNIVOICE_LANGUAGES) | {"ar"}),
        "language_codes": {"ar": "arb"},  # Vokalit's code -> the model's
        "settings": [
            {"key": "speed", "label": "Speed", "min": 0.5, "max": 2.0, "step": 0.05, "default": 1.0,
             "help": "Above 1 is faster."},
            {"key": "num_step", "label": "Quality", "min": 16, "max": 64, "step": 1, "default": 32,
             "help": "Higher sounds better but takes longer; 16 is quick. Sounds such as [laughter] come out clearer "
                     "when it is higher."},
        ],
        "pip_steps": [
            ("PyTorch with CUDA", TORCH_CUDA),  # the same files as Chatterbox's: shared, not downloaded again
            ("Other libraries", ["-r", os.path.join(ROOT, "workers", "omnivoice", "requirements.txt")]),
            ("OmniVoice", ["omnivoice==0.2.1"]),
        ],
    },
}

# Sounds written into a line's text as [tag] (OmniVoice performs them). Models without "supports_tags" get the text
# without them; they would read them aloud.
TAGS = ["laughter", "sigh", "confirmation-en", "question-en", "question-ah", "question-oh", "question-ei", "question-yi",
        "surprise-ah", "surprise-oh", "surprise-wa", "surprise-yo", "dissatisfaction-hnn"]
_TAG = re.compile(r"\[(?:" + "|".join(re.escape(tag) for tag in TAGS) + r")\]")


def text_for(name, text):
    """The line's text as `name` should get it: known tags removed unless the model performs them."""
    if MODELS[name].get("supports_tags"):
        return text
    return re.sub(r"\s+", " ", _TAG.sub(" ", text)).strip()


# Components that are not voice models. Whisper writes down what a voice sample says; some models need that.
TOOLS = {
    "whisper": {
        "title": "Whisper",
        "summary": "Writes down what each voice sample says. Some models copy a voice better with it; without Whisper "
                   "you type it.",
        "url": "https://github.com/SYSTRAN/faster-whisper",
        "disk_gb": 1.7,  # estimate; measured on Windows at the first install
        "license": "MIT",
        "recommended": True,
        # Runs on the CPU (int8): no PyTorch, and the GPU stays free for the voice models.
        "pip_steps": [("faster-whisper", ["faster-whisper==1.2.1"])],
    },
}


def spec(name):
    """A voice model's or a tool's entry. KeyError for anything else."""
    return MODELS[name] if name in MODELS else TOOLS[name]


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


def shared_dir():
    """Package files several components can share: one uv cache, hard-linked into each venv (SPEC.md \u00a76)."""
    return os.path.join(LOCAL, "shared")


def _components():
    return list(TOOLS) + list(MODELS)


def _inodes(folder):
    """{(dev, inode): (size, links, occurrences in folder)}"""
    found = {}
    for path, _, files in os.walk(folder):
        for file in files:
            try:
                stat = os.lstat(os.path.join(path, file))
            except FileNotFoundError:  # a temporary file removed meanwhile
                continue
            key = (stat.st_dev, stat.st_ino)
            size, links, count = found.get(key, (stat.st_size, stat.st_nlink, 0))
            found[key] = (size, links, count + 1)
    return found


def _size_gb(*folders):
    seen = {}
    for folder in folders:
        seen.update(_inodes(folder))
    return sum(size for size, _, _ in seen.values()) / 1e9


def size_gb(name):
    return _size_gb(model_dir(name))


def _walk_sizes():
    """What removing each installed component frees (its files no other component links to), and the total."""
    cache = _inodes(shared_dir())
    frees, everything = {}, dict(cache)
    for name in _components():
        if not is_installed(name):
            continue
        own = _inodes(model_dir(name))
        everything.update(own)
        frees[name] = sum(size for key, (size, links, count) in own.items()
                          if count + cache.get(key, (0, 0, 0))[2] >= links) / 1e9
    return {"frees": frees, "total_gb": sum(size for size, _, _ in everything.values()) / 1e9}


_sizes_lock = threading.Lock()


def refresh_sizes():
    with _sizes_lock:
        result = _walk_sizes()
        os.makedirs(LOCAL, exist_ok=True)
        with open(os.path.join(LOCAL, "sizes.json"), "w", encoding="utf-8") as f:
            json.dump(result, f)
        return result


def sizes():
    """Measured in the background after installs and removes; walking tens of thousands of files is slow (minutes
    on Windows), so a request never does it. Unknown sizes are missing (total None) until the measuring is done."""
    try:
        with open(os.path.join(LOCAL, "sizes.json"), encoding="utf-8") as f:
            result = json.load(f)
        if all(name in result["frees"] for name in _components() if is_installed(name)):
            return result
    except (FileNotFoundError, ValueError, KeyError):
        result = {"frees": {}, "total_gb": None}
    _measure_soon()
    return result


_measuring = threading.Lock()


def _measure_soon():
    """Starts measuring in the background unless it already runs."""
    if _measuring.acquire(blocking=False):
        def run():
            try:
                refresh_sizes()
            finally:
                _measuring.release()
        _start_background(run)


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
            _kill_tree(process)
    if returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}")


def _kill_tree(process):
    """Also stops the command's child processes (uv's installers, downloads), which would keep files open."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
    process.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)


_install_lock = threading.Lock()  # one install at a time; the cache clean-up waits for it
_installing = None


def installing():
    return _installing


def install(name):
    """Yields ("log", line) and ("status", text). On failure or cancel removes the half-installed component and
    raises. Afterwards, unused cache files are deleted and sizes measured."""
    global _installing
    if not _install_lock.acquire(blocking=False):
        raise RuntimeError("Another install is running. Wait for it to finish.")
    _installing = name
    try:
        yield from _install(name)
    finally:
        _installing = None
        _install_lock.release()
        _start_background(_maintain)  # the install is done; this can take minutes on Windows


def _maintain():
    clean_shared_cache()
    refresh_sizes()


def _install(name):
    _wait_for_delete(model_dir(name))
    remove(name, maintain=False)  # leftovers of an interrupted install
    _wait_for_delete(model_dir(name))
    _cancelled.discard(name)
    env = _env(name, offline=False)
    # One cache for every component: uv hard-links its files into each venv, so identical packages (PyTorch) are
    # stored once.
    env["UV_CACHE_DIR"] = os.path.join(shared_dir(), "uv-cache")
    env["UV_LINK_MODE"] = "hardlink"
    steps = [("Python environment", [UV, "venv", "--python", "3.11", os.path.join(model_dir(name), "venv")])]
    for label, args in spec(name)["pip_steps"]:
        steps.append((label, [UV, "pip", "install", "--python", _python(name), *args]))
    steps.append(("Model weights", [_python(name), _worker_script(name), "--download"]))
    # The size on disk is measured by a thread: walking tens of thousands of files takes seconds on Windows, and the
    # steps and the log must not wait for it. The screen counts the elapsed time itself.
    measured = {"gb": None}
    stop = threading.Event()

    def measure():
        at_start = _size_gb(shared_dir())
        while not stop.is_set():
            measured["gb"] = max(0.0, _size_gb(model_dir(name), shared_dir()) - at_start)
            stop.wait(3)

    threading.Thread(target=measure, daemon=True).start()

    def status(number, label):
        size = "measuring size\u2026" if measured["gb"] is None else f"{measured['gb']:.2f} GB on disk"
        return "status", f"Step {number}/{len(steps)}: {label} \u00b7 {size}"

    try:
        for number, (label, command) in enumerate(steps, 1):
            yield "log", f"--- Step {number}/{len(steps)}: {label}\n"
            yield status(number, label)
            last_status = time.monotonic()
            with contextlib.closing(_run(command, env)) as output:
                for line in output:
                    if name in _cancelled:
                        raise Cancelled()
                    if line:
                        yield "log", line
                    if time.monotonic() - last_status >= 3:
                        last_status = time.monotonic()
                        yield status(number, label)
    except BaseException:  # also GeneratorExit: a closed install leaves nothing half-done
        stop.set()
        remove(name, maintain=False)
        raise
    stop.set()
    with open(_marker(name), "w", encoding="utf-8"):
        pass
    yield "log", "Done.\n"


def cancel_install(name):
    """The running install stops within a few seconds and cleans up."""
    _cancelled.add(name)


def remove(name, maintain=True):
    """Deleting tens of thousands of files takes minutes on Windows, so the folder is renamed (instant) and
    deleted in the background; then unused cache files are deleted and sizes measured (`maintain`)."""
    stop(name)
    folder = model_dir(name)
    if not os.path.exists(folder):
        return
    with contextlib.suppress(FileNotFoundError):
        os.remove(_marker(name))  # not installed from now on, whatever happens below
    trash = os.path.join(LOCAL, f".removing-{name}-{time.time_ns()}")
    for _ in range(8):  # a killed process may hold its files for a moment
        try:
            os.rename(folder, trash)
            break
        except PermissionError:
            time.sleep(0.25)
    else:
        trash = folder  # still locked: delete it in place; an install waits for that (_wait_for_delete)
    _delete_in_background(trash, maintain)


_deleting = {}  # folder -> thread deleting it in place
_background = []  # every maintenance thread, so tests can wait for them


def _start_background(target, *args):
    thread = threading.Thread(target=target, args=args, daemon=True)
    _background.append(thread)
    thread.start()
    return thread


def _join_background():
    while _background:
        _background.pop().join()


def _delete(path, maintain):
    shutil.rmtree(path, ignore_errors=True)
    if maintain:
        _maintain()


def _delete_in_background(path, maintain=False):
    _deleting[path] = _start_background(_delete, path, maintain)


def _wait_for_delete(path):
    thread = _deleting.pop(path, None)
    if thread:
        thread.join()


def clean_shared_cache():
    """Deletes unpacked packages in the cache that no venv uses any more (every file of the archive has a link
    count of 1: downloads of a cancelled install, packages of removed components), and the whole shared folder once
    nothing is installed. uv's small index files are kept: they are how it finds a package it already has (deleting
    them would download PyTorch again for the next model). Waits for a running install, whose fresh downloads are
    not linked yet."""
    with _install_lock:
        folder = shared_dir()
        if not any(is_installed(name) for name in _components()):
            shutil.rmtree(folder, ignore_errors=True)
            return
        archives = os.path.join(folder, "uv-cache", "archive-v0")
        with contextlib.suppress(FileNotFoundError):
            for entry in os.scandir(archives):
                if entry.is_dir(follow_symlinks=False) and not _linked(entry.path):
                    shutil.rmtree(entry.path, ignore_errors=True)


def _linked(folder):
    """Whether any file in `folder` is also linked from somewhere else (a venv)."""
    for path, _, files in os.walk(folder):
        for file in files:
            with contextlib.suppress(OSError):
                if os.lstat(os.path.join(path, file)).st_nlink > 1:
                    return True
    return False


def delete_removed():
    """At start: deletes what a remove left behind when the app closed before it finished, and components whose
    install never finished (the app closed, crashed or lost power during it: the folder has no "installed" marker)."""
    with contextlib.suppress(FileNotFoundError):
        for entry in os.scandir(LOCAL):
            if entry.name.startswith(".removing-") and entry.is_dir():
                _delete_in_background(entry.path)
    for name in _components():
        if os.path.isdir(model_dir(name)) and not is_installed(name):
            remove(name)


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


def _request(name, message):
    """Sends one request to the component's worker and returns its reply. The worker is started on first use and
    stays loaded."""
    try:
        if name not in _workers:
            _workers[name] = _Worker(name)
        reply = _workers[name].request(message)
    except Exception:
        stop(name)
        raise
    if not reply["ok"]:
        if reply.get("restart"):
            stop(name)  # the worker exited; the next request starts a fresh one
            raise RuntimeError(
                f"The GPU stopped with an internal error, so {spec(name)['title']} was restarted (the next take "
                "loads it again). If it keeps happening with these settings, lower Variation or Expressiveness, or "
                f"try another seed. Details: {reply['error']}")
        raise RuntimeError(reply["error"])
    return reply


def _ask(name, message):
    return _request(name, message)["seconds"]


def transcribe(audio, language):
    """What is said in `audio`, written by Whisper (on the CPU): {"text", "language"}. `language`: a code, or None to
    detect it."""
    if not is_installed("whisper"):
        raise RuntimeError("Whisper is not installed.")
    reply = _request("whisper", {"task": "transcribe", "audio": audio, "language": language})
    return {"text": reply["text"], "language": reply.get("language")}


def model_language(name, code):
    """The code `name` expects for Vokalit's language `code`."""
    return MODELS[name].get("language_codes", {}).get(code, code)


def generate(name, text, ref, out, seed, settings, language, ref_text=None):
    """Returns the generation time in seconds. `ref_text`: what is said in `ref` (models that need it)."""
    if language not in MODELS[name].get("languages", []):
        raise ValueError(f"{MODELS[name]['title']} does not support {LANGUAGE_NAMES.get(language, language)}.")
    settings = validate_settings(name, settings)
    return _ask(name, {"text": text, "ref": ref, "out": out, "seed": seed, "settings": settings,
                       "language": model_language(name, language), "ref_text": ref_text})


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
