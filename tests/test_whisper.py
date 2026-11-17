"""Runs the real Whisper worker in a subprocess against the stub faster_whisper (tests/stubs).
Needs `uv` and `python3.11` on PATH, like tests/test_worker.py."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402

STUBS = Path(__file__).resolve().parent / "stubs"


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    local = tmp_path_factory.mktemp("local")
    old_local, old_steps = models.LOCAL, models.TOOLS["whisper"]["pip_steps"]
    old_path = os.environ.get("PYTHONPATH")
    models.LOCAL = str(local)
    models.TOOLS["whisper"]["pip_steps"] = []
    os.environ["PYTHONPATH"] = str(STUBS)
    log = "".join(text for kind, text in models.install("whisper") if kind == "log")
    yield log
    models.stop_all()
    models._join_background()
    models.LOCAL, models.TOOLS["whisper"]["pip_steps"] = old_local, old_steps
    if old_path is None:
        os.environ.pop("PYTHONPATH")
    else:
        os.environ["PYTHONPATH"] = old_path


def test_download_loads_turbo_on_cpu(installed):
    assert "stub whisper large-v3-turbo loaded on cpu as int8" in installed


def test_transcribe_returns_text_and_language(installed):
    assert models.transcribe("/samples/s1.wav", "en") == {"text": "heard:s1.wav :en", "language": "en"}
    assert models.transcribe("/samples/s2.wav", None) == {"text": "heard:s2.wav :None", "language": "tr"}


def test_network_blocked_in_whisper_worker(installed):
    with pytest.raises(RuntimeError, match="Network access is blocked"):
        models.transcribe("/samples/NET.wav", None)


def test_transcribe_without_whisper_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "LOCAL", str(tmp_path))
    with pytest.raises(RuntimeError, match="Whisper is not installed"):
        models.transcribe("/samples/s1.wav", None)


def test_whisper_is_not_a_voice_model():
    assert "whisper" not in models.MODELS
    assert models.spec("whisper")["title"] == "Whisper"
