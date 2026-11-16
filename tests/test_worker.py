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
    models.generate("chatterbox", "hello", None, out, seed=42, settings={})
    assert "seed=42" in _read(out)
    assert "subtype=PCM_16" in _read(out)


def test_settings_are_passed_to_generate(installed):
    _, local = installed
    out = _out(local, "settings.wav")
    models.generate("chatterbox", "hello", None, out, seed=1, settings={"exaggeration": 0.7})
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
    models.generate("chatterbox", "a", "/refs/me.wav", clone, seed=1, settings={})
    models.generate("chatterbox", "b", None, default, seed=1, settings={})
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
