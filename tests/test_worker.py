"""Runs the real Chatterbox worker in a subprocess against stub torch/chatterbox (tests/stubs).
Needs `uv` and `python3.11` on PATH (the install step creates a real venv, without packages)."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402

STUBS = Path(__file__).resolve().parent / "stubs"


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    local = tmp_path_factory.mktemp("local")
    old_local, old_steps = models.LOCAL, models.MODELS["chatterbox"]["pip_steps"]
    old_path = os.environ.get("PYTHONPATH")
    models.LOCAL = str(local)
    models.MODELS["chatterbox"]["pip_steps"] = []
    os.environ["PYTHONPATH"] = str(STUBS)
    log = "".join(text for kind, text in models.install("chatterbox") if kind == "log")
    yield log, local
    models.stop_all()
    models.LOCAL, models.MODELS["chatterbox"]["pip_steps"] = old_local, old_steps
    if old_path is None:
        os.environ.pop("PYTHONPATH")
    else:
        os.environ["PYTHONPATH"] = old_path


def _out(local, name):
    return str(Path(local) / name)


def _read(path):
    return Path(path).read_text(encoding="utf-8")


def test_download_loads_vc(installed):
    log, _ = installed
    assert "stub tts loaded on cpu" in log
    assert "stub vc loaded on cpu" in log


def test_seed_is_applied(installed):
    _, local = installed
    out = _out(local, "seed.wav")
    models.generate("chatterbox", "hello", None, out, seed=42, settings={}, language="tr")
    assert "seed=42" in _read(out)
    assert "subtype=PCM_16" in _read(out)


def test_settings_are_passed_to_generate(installed):
    _, local = installed
    out = _out(local, "settings.wav")
    models.generate("chatterbox", "hello", None, out, seed=1, settings={"exaggeration": 0.7}, language="tr")
    text = _read(out)
    assert "exaggeration=0.7" in text and "cfg_weight=0.5" in text and "temperature=0.8" in text


def test_unknown_setting_is_rejected():
    with pytest.raises(ValueError):
        models.validate_settings("chatterbox", {"foo": 1})
    with pytest.raises(ValueError):
        models.validate_settings("chatterbox", {"exaggeration": 9})
    assert models.validate_settings("chatterbox", {}) == models.default_settings("chatterbox") == {
        "exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8}


def test_default_voice_restored_after_clone(installed):
    _, local = installed
    clone, default = _out(local, "clone.wav"), _out(local, "default.wav")
    models.generate("chatterbox", "a", "/refs/me.wav", clone, seed=1, settings={}, language="tr")
    models.generate("chatterbox", "b", None, default, seed=1, settings={}, language="tr")
    assert "voice=CLONE:/refs/me.wav" in _read(clone)
    assert "voice=BUILTIN" in _read(default)


def test_convert_uses_vc_and_default_voice(installed):
    _, local = installed
    first, second = _out(local, "c1.wav"), _out(local, "c2.wav")
    models.convert("chatterbox", "/rec/line.wav", None, first)
    models.convert("chatterbox", "/rec/line.wav", "/refs/me.wav", second)
    assert "target=None" in _read(first)
    assert "vc_loads=1" in _read(second) and "target=/refs/me.wav" in _read(second)


def test_network_still_blocked_in_convert(installed):
    _, local = installed
    with pytest.raises(RuntimeError, match="Network access is blocked"):
        models.convert("chatterbox", "/rec/NET.wav", None, _out(local, "net.wav"))


def test_convert_unsupported_model_is_refused():
    models.MODELS["fake"] = {"title": "Fake", "supports_convert": False, "settings": []}
    try:
        with pytest.raises(RuntimeError, match="Fake does not support voice conversion"):
            models.convert("fake", "/rec/a.wav", None, "/tmp/x.wav")
    finally:
        del models.MODELS["fake"]


def test_language_is_passed(installed):
    _, local = installed
    out = _out(local, "language.wav")
    models.generate("chatterbox", "hello", None, out, seed=1, settings={}, language="en")
    assert "language=en" in _read(out)


def test_unsupported_language_is_refused():
    with pytest.raises(ValueError, match="does not support"):
        models.generate("chatterbox", "hello", None, "/x.wav", seed=1, settings={}, language="xx")


def test_gpu_error_restarts_the_worker(installed):
    _, local = installed
    models.generate("chatterbox", "warm up", None, _out(local, "warm.wav"), seed=1, settings={}, language="tr")
    first = models._workers["chatterbox"].process
    with pytest.raises(RuntimeError, match="restarted"):
        models.generate("chatterbox", "CRASH", None, _out(local, "crash.wav"), seed=1, settings={}, language="tr")
    assert "chatterbox" not in models._workers and first.wait(timeout=10) is not None
    out = _out(local, "after.wav")
    models.generate("chatterbox", "works again", None, out, seed=1, settings={}, language="tr")
    assert "text=works again" in _read(out)


def test_worker_exits_when_the_app_is_gone(installed):
    # If the app is killed (e.g. from Task Manager), the OS closes its end of the worker's stdin; the worker must then
    # exit and free the GPU memory.
    _, local = installed
    models.generate("chatterbox", "warm up", None, _out(local, "warm2.wav"), seed=1, settings={}, language="tr")
    process = models._workers["chatterbox"].process
    process.stdin.close()  # what the OS does when the app dies
    assert process.wait(timeout=10) == 0
    models._workers.pop("chatterbox", None)


def test_idle_model_is_unloaded(installed):
    # A model not used for IDLE_SECONDS leaves the GPU; the next take loads it again.
    _, local = installed
    models.generate("chatterbox", "warm up", None, _out(local, "idle.wav"), seed=1, settings={}, language="tr")
    worker = models._workers["chatterbox"]
    models._unload_idle(now=worker.last_used + models.IDLE_SECONDS - 1)
    assert "chatterbox" in models._workers  # not idle long enough
    models._unload_idle(now=worker.last_used + models.IDLE_SECONDS + 1)
    assert "chatterbox" not in models._workers
    assert worker.process.wait(timeout=10) is not None
    out = _out(local, "after-idle.wav")
    models.generate("chatterbox", "loaded again", None, out, seed=1, settings={}, language="tr")
    assert "text=loaded again" in _read(out)


def test_busy_model_is_not_unloaded(installed):
    _, local = installed
    models.generate("chatterbox", "warm up", None, _out(local, "busy.wav"), seed=1, settings={}, language="tr")
    worker = models._workers["chatterbox"]
    with worker.lock:  # a take is being generated
        models._unload_idle(now=worker.last_used + models.IDLE_SECONDS + 1)
    assert "chatterbox" in models._workers
