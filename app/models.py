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
    "ru": "Russian", "sv": "Swedish", "sw": "Swahili", "tl": "Tagalog", "tr": "Turkish", "zh": "Chinese", "ne": "Nepali", "la": "Latin",
}

# OmniVoice's own list (646 languages, ISO 639 codes) read from the package it installs, in English. Vokalit's names
# above win where both have one.
with open(os.path.join(os.path.dirname(__file__), "omnivoice_languages.json"), encoding="utf-8") as _f:
    _OMNIVOICE_LANGUAGES = json.load(_f)["languages"]
LANGUAGE_NAMES = {**_OMNIVOICE_LANGUAGES, **LANGUAGE_NAMES}


# Sounds written into a line's text as [tag] (Vokalit's names, which are OmniVoice's). Each model gets them in its own
# syntax ("sounds"); models without a sound get the text without it, since they would read the tag aloud.
OMNIVOICE_TAGS = ["laughter", "sigh", "confirmation-en", "question-en", "question-ah", "question-oh", "question-ei",
                  "question-yi", "surprise-ah", "surprise-oh", "surprise-wa", "surprise-yo", "dissatisfaction-hnn"]
# Higgs TTS 3's controls, named like the others (hyphens, since "[" suggestions take letters and hyphens). The UI
# groups them: sounds, emotions, styles, delivery.
HIGGS_TAGS = ["cough", "crying", "screaming", "burping", "humming", "sniff", "sneeze",
              "elation", "amusement", "enthusiasm", "determination", "pride", "contentment", "affection", "relief",
              "contemplation", "confusion", "surprise", "awe", "longing", "arousal", "anger", "fear", "disgust",
              "bitterness", "sadness", "shame", "helplessness",
              "singing", "shouting", "whispering",
              "speed-very-slow", "speed-slow", "speed-fast", "speed-very-fast", "pitch-low", "pitch-high", "pause",
              "long-pause", "expressive-high", "expressive-low"]
TAGS = OMNIVOICE_TAGS + HIGGS_TAGS

# Higgs TTS 3 runs from a transformers packaging of Boson AI's weights. Its code is run from the Hub
# (trust_remote_code), so it and the codec are pinned to the commits checked on Windows (2026-11-18).
HIGGS_PORT = "multimodalart/higgs-audio-v3-tts-4b-transformers"
HIGGS_PORT_REVISION = "30f01593ee6a12efa586c92455afe4b76e45095d"
HIGGS_CODEC = "bosonai/higgs-audio-v2-tokenizer"
HIGGS_CODEC_REVISION = "815a03f1b57dcb5ae918db415f22cd0c8a6f0f54"
# Higgs's syntax for each tag. Sound effects are followed by their sound written out, as the model card advises.
_HIGGS_SFX = {"cough": "Ahem", "laughter": "Haha", "crying": "Boohoo", "screaming": "Aaah", "burping": "Burp",
              "humming": "Hmm", "sigh": "Ahh", "sniff": "Sff", "sneeze": "Achoo"}
_HIGGS_STYLES = ["singing", "shouting", "whispering"]
_HIGGS_PROSODY = ["speed-very-slow", "speed-slow", "speed-fast", "speed-very-fast", "pitch-low", "pitch-high", "pause",
                  "long-pause", "expressive-high", "expressive-low"]
HIGGS_SOUNDS = {
    **{tag: f"<|sfx:{tag}|>{word}" for tag, word in _HIGGS_SFX.items()},
    **{tag: f"<|emotion:{tag}|>" for tag in HIGGS_TAGS
       if tag not in _HIGGS_SFX and tag not in _HIGGS_STYLES and tag not in _HIGGS_PROSODY},
    **{tag: f"<|style:{tag}|>" for tag in _HIGGS_STYLES},
    **{tag: f"<|prosody:{tag.replace('-', '_')}|>" for tag in _HIGGS_PROSODY},
}
_TAG = re.compile(r"\[(" + "|".join(re.escape(tag) for tag in TAGS) + r")\]")


# VoxCPM2's Style suggestions: instructions in English, which its style control follows best.
VOXCPM_STYLES = [{"label": "Neutral", "value": ""}, {"label": "Happy", "value": "cheerful, warm"},
                 {"label": "Sad", "value": "sad, quiet"}, {"label": "Angry", "value": "angry, tense"},
                 {"label": "Calm", "value": "calm, slow"}, {"label": "Excited", "value": "excited, energetic"},
                 {"label": "Whispering", "value": "whispering"}, {"label": "Serious", "value": "serious, firm"}]


MODELS = {
    "chatterbox": {
        "title": "Chatterbox Multilingual",
        "summary": "23 languages \u00b7 cloning \u00b7 voice conversion",
        "url": "https://huggingface.co/ResembleAI/chatterbox",
        "disk_gb": 12.3,  # measured on Windows (SPEC.md §6.1)
        "license": "MIT",
        "supports_convert": True,
        "needs_transcript": False,
        "vram_gb": 4.1,  # measured on an RTX 4070 SUPER (Windows): ~4.1 GB; used to make room before loading
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
        "vram_gb": 2.7,  # measured on an RTX 4070 SUPER (Windows): ~2.6 GB
        "sounds": {tag: f"[{tag}]" for tag in OMNIVOICE_TAGS},  # Vokalit's first sound tags are OmniVoice's
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
    "voxcpm": {
        "title": "VoxCPM2",
        "summary": "30 languages \u00b7 cloning \u00b7 style instructions",
        "url": "https://huggingface.co/openbmb/VoxCPM2",
        "disk_gb": 13.6,  # measured on Windows: 8.6 GB environment (PyTorch shared with other models) + 5.0 GB model
        "license": "Apache-2.0",
        "supports_convert": False,
        "needs_transcript": False,  # clones from the sample alone, the mode its style instructions work with
        "vram_gb": 8.4,  # measured on an RTX 4070 SUPER (Windows): 5.8 GB loaded, 8.3 GB peak
        "languages": ["ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "id", "it", "ja", "km", "ko", "lo",
                      "ms", "my", "nl", "no", "pl", "pt", "ru", "sv", "sw", "th", "tl", "tr", "vi", "zh"],
        "settings": [
            {"key": "style", "type": "text", "label": "Style", "default": "", "max_length": 200,
             "placeholder": "e.g. cheerful, a little faster", "suggestions": VOXCPM_STYLES,
             "help": "How the line is said, in a few English words. The effect can be subtle, especially in Turkish; "
                     "a higher Style strength makes it stronger."},
            {"key": "cfg_value", "label": "Style strength", "min": 1.0, "max": 3.0, "step": 0.1, "default": 2.0,
             "help": "Higher follows the style and the text more closely; above 2.5 can sound strained."},
            {"key": "inference_timesteps", "label": "Quality", "min": 4, "max": 30, "step": 1, "default": 10,
             "help": "Higher sounds better but takes longer."},
        ],
        "pip_steps": [
            ("PyTorch with CUDA", TORCH_CUDA),  # voxcpm 2.0.3 accepts this build: shared with the other models
            ("VoxCPM2", ["voxcpm==2.0.3"]),
        ],
    },
    "higgs": {
        "title": "Higgs TTS 3",
        "summary": "102 languages \u00b7 cloning \u00b7 emotions and sounds",
        "url": "https://huggingface.co/bosonai/higgs-tts-3-4b",
        # measured on Windows: 7.8 GB environment (PyTorch shared with other models) + 10.1 GB model and codec
        "disk_gb": 17.9,
        "license": "Non-commercial; monetized creator content allowed with the credit \u201cBoson AI's Higgs Audio\u201d",
        "supports_convert": False,
        "needs_transcript": True,  # cloning is much better with what the sample says
        # Measured on an RTX 4070 SUPER (Windows): 8-bit 6.1 GB peak (used when less than 10.7 GB is free), bf16
        # 9.7 GB peak and about three times faster (used on cards with room for it).
        "vram_gb": 6.1,
        "languages": ("af ar hy as ast az ba eu be bn bs bg ca ceb ckb zh hr cs da nl mhr en eo et fi fr gl ka de el "
                      "gu ht ha he hi hu id it ja jv kn kk ko rw ky lv ln lt luo mk ms ml mt mi mr mn ne no oc fa pl "
                      "pt ro ru nso sr sn sk sl es sw sv tl tg ta te th tr uk ur ug uz vi xh zu sq ny pa lg is ga kab "
                      "kea kam la lb om ps sd so umb cy").split(),
        "sounds": HIGGS_SOUNDS,
        "settings": [
            {"key": "temperature", "label": "Variation", "min": 0.3, "max": 1.2, "step": 0.05, "default": 0.7,
             "help": "Higher sounds livelier and more varied; lower is steadier."},
        ],
        "env": {"HIGGS_PORT": HIGGS_PORT, "HIGGS_PORT_REVISION": HIGGS_PORT_REVISION,
                "HIGGS_CODEC": HIGGS_CODEC, "HIGGS_CODEC_REVISION": HIGGS_CODEC_REVISION},
        "pip_steps": [
            ("PyTorch with CUDA", TORCH_CUDA),  # transformers 5.23 accepts this build: shared with the other models
            ("Higgs libraries", ["transformers==5.23.0", "accelerate==1.16.0", "bitsandbytes==0.50.2",
                                 "soundfile==0.14.0"]),
        ],
    },
}

def text_for(name, text):
    """The line's text as `name` should get it: each sound tag in the model's own syntax ("sounds"), or removed when
    the model does not perform it."""
    sounds = MODELS[name].get("sounds") or {}
    converted = _TAG.sub(lambda m: f" {sounds[m.group(1)]} " if m.group(1) in sounds else " ", text)
    return re.sub(r"[ \t]+", " ", converted).strip() if converted != text else text


def has_words(text):
    """Whether a model's text (after text_for) has something to say besides control tags like Higgs's
    <|emotion:anger|>. A sound effect counts: it is followed by its sound ("Haha")."""
    return bool(re.sub(r"<\|[^|]*\|>", " ", text).strip())


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


PYTORCH_GB = 5.0  # PyTorch with CUDA: stored once in the shared cache and used by every model that installs it


def _uses_pytorch(name):
    return any(args is TORCH_CUDA for _, args in spec(name).get("pip_steps", []))


def needs_gb(name):
    """Disk space installing `name` needs: its size, less PyTorch when an installed model already has it, plus 1 GB of
    room. An estimate on the safe side (sizes were measured on Windows)."""
    need = spec(name)["disk_gb"]
    if _uses_pytorch(name) and any(other != name and _uses_pytorch(other) and is_installed(other)
                                   for other in [*TOOLS, *MODELS]):
        need -= PYTORCH_GB
    return round(need + 1, 1)


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
    env = dict(os.environ, HF_HOME=cache, TORCH_HOME=cache, HF_HUB_DISABLE_TELEMETRY="1", PYTHONUTF8="1",
               **spec(name).get("env", {}))
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


IDLE_SECONDS = 5 * 60  # a model unused this long leaves the GPU (or, for Whisper, memory); the next request loads it
_owner = threading.local()  # the job the current thread works for (server.py sets it), so cancel() stops only its own
_starting = {}  # name -> worker still loading


def set_owner(owner):
    """Marks the current thread's requests as `owner`'s (a job id), for cancel()."""
    _owner.value = owner


def cancel(name, owner):
    """Stops `name` if it is loading or generating for `owner`: its process is killed, so the request fails at once.
    The next take loads the model again. False if `name` is not working for `owner`."""
    for worker in (_workers.get(name), _starting.get(name)):
        if worker is not None and owner is not None and worker.owner == owner:
            if _workers.get(name) is worker:
                _workers.pop(name, None)
            _kill_tree(worker.process)
            return True
    return False


class _Worker:
    def __init__(self, name):
        self.owner = getattr(_owner, "value", None)  # the job it is loading or generating for
        self.lock = threading.Lock()
        self.last_used = time.monotonic()
        self.vram_gb = None  # GPU memory the model holds, as the worker reports it
        self.mode = None  # how a worker chose to load, if it can choose ({label, reason}; Higgs: precision)
        # stderr is inherited, so the worker's logs appear in the console window.
        self.process = subprocess.Popen(
            [_python(name), _worker_script(name)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=_env(name, offline=True),
            text=True,
            encoding="utf-8",
        )
        _starting[name] = self
        try:
            ready = self._read()
        finally:
            _starting.pop(name, None)
        self.owner = None
        self.vram_gb = ready.get("vram_gb")
        self.mode = ready.get("mode")
        if not ready.get("ready"):
            self.process.kill()
            if ready.get("oom"):
                raise OutOfGpuMemory(ready.get("error", ""))
            raise RuntimeError(ready.get("error", "The model failed to start."))

    def _read(self):
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("The model process stopped unexpectedly. See the console window for details.")
        return json.loads(line)

    def request(self, message):
        with self.lock:
            self.owner = getattr(_owner, "value", None)
            try:
                self.process.stdin.write(json.dumps(message) + "\n")
                self.process.stdin.flush()
                reply = self._read()
                self.vram_gb = reply.get("vram_gb", self.vram_gb)
                return reply
            finally:
                self.owner = None
                self.last_used = time.monotonic()


def _unload_idle(now=None):
    """Stops workers that have not been used for IDLE_SECONDS, unless one is busy right now."""
    now = time.monotonic() if now is None else now
    for name, worker in list(_workers.items()):
        if now - worker.last_used > IDLE_SECONDS and worker.lock.acquire(blocking=False):
            try:
                if _workers.get(name) is worker:
                    stop(name)
            finally:
                worker.lock.release()


def runtime(name):
    """Whether the component is loaded right now, for the Models screen: busy (generating), the GPU memory it holds,
    and the seconds until it is unloaded for being idle."""
    worker = _workers.get(name)
    if worker is None:
        return {"loaded": False}
    busy = worker.lock.locked()
    left = None if busy else max(0, round(IDLE_SECONDS - (time.monotonic() - worker.last_used)))
    return {"loaded": True, "busy": busy, "vram_gb": worker.vram_gb, "unloads_in": left, "mode": worker.mode}


def unload(name):
    """Unloads a component now. ValueError while it is generating."""
    worker = _workers.get(name)
    if worker is None:
        return
    if not worker.lock.acquire(blocking=False):
        raise ValueError(f"{spec(name)['title']} is generating; it can be unloaded when it is done.")
    try:
        if _workers.get(name) is worker:
            stop(name)
    finally:
        worker.lock.release()


def _watch_idle():
    while True:
        time.sleep(30)
        _unload_idle()


_watcher = None


def default_settings(name):
    return {s["key"]: s["default"] for s in MODELS[name]["settings"]}


def clean_settings(name, settings):
    """The given settings checked and cleaned, without defaults. ValueError on a key the model does not declare or a
    bad value. Text settings lose their parentheses (VoxCPM2 reads text in parentheses as an instruction) and extra
    whitespace."""
    spec = {s["key"]: s for s in MODELS[name]["settings"]}
    cleaned = {}
    for key, value in settings.items():
        if key not in spec:
            raise ValueError(f"{MODELS[name]['title']} has no setting '{key}'.")
        s = spec[key]
        if s.get("type") == "text":
            if not isinstance(value, str):
                raise ValueError(f"{s['label']} must be text.")
            value = " ".join(re.sub(r"[()]", " ", value).split())
            if len(value) > s["max_length"]:
                raise ValueError(f"{s['label']} can be at most {s['max_length']} characters.")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not s["min"] <= value <= s["max"]:
            raise ValueError(f"{s['label']} must be between {s['min']} and {s['max']}.")
        cleaned[key] = value
    return cleaned


def validate_settings(name, settings):
    """Fills in defaults. ValueError on a key the model does not declare or a bad value (see clean_settings)."""
    return {**default_settings(name), **clean_settings(name, settings)}


class OutOfGpuMemory(RuntimeError):
    """A model could not load: the GPU has no room for it."""


def _free_vram_gb():
    """Free memory of the first NVIDIA GPU in GB, or None when it cannot be read."""
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=5)
        return int(result.stdout.strip().splitlines()[0]) / 1024 if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def _make_room(name, need=None):
    """Stops other workers that are not busy, least recently used first: until `need` GB are free on the GPU, or
    (need None, after an out-of-memory error) all of them."""
    for other, worker in sorted(list(_workers.items()), key=lambda item: item[1].last_used):
        if other == name:
            continue
        if need is not None:
            free = _free_vram_gb()
            if free is None or free >= need:
                return
        if worker.lock.acquire(blocking=False):  # a busy model keeps its memory
            try:
                if _workers.get(other) is worker:
                    stop(other)
            finally:
                worker.lock.release()


def _out_of_memory(name):
    return RuntimeError(
        f"Not enough GPU memory for {spec(name)['title']}, even after unloading the other models. Close other programs "
        "that use the GPU (games, video editors, other AI tools), or generate with one model at a time.")


def _send(name, message):
    try:
        if name not in _workers:
            need = spec(name).get("vram_gb")
            if need:
                _make_room(name, need + 0.5)  # make room before loading, not after failing
            _workers[name] = _Worker(name)
            global _watcher
            if _watcher is None:  # unloads idle models from now on
                _watcher = threading.Thread(target=_watch_idle, daemon=True)
                _watcher.start()
        return _workers[name].request(message)
    except Exception:
        stop(name)
        raise


def _request(name, message):
    """Sends one request to the component's worker and returns its reply. The worker is started on first use and
    stopped after IDLE_SECONDS unused. Out of GPU memory: the other idle models are unloaded and it is tried once more;
    if it still does not fit, a clear message."""
    for attempt in (1, 2):
        try:
            reply = _send(name, message)
        except OutOfGpuMemory:
            reply = {"ok": False, "oom": True}
        if reply["ok"] or not reply.get("oom"):
            break
        if attempt == 2:
            raise _out_of_memory(name)
        _make_room(name)
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
    """Unloads a component: its process and the processes it started. On Windows a venv's python.exe starts the real
    interpreter as a child, which holds the GPU memory; killing only the parent could leave it running."""
    worker = _workers.pop(name, None)
    if worker:
        _kill_tree(worker.process)


def stop_all():
    for name in list(_workers):
        stop(name)
