"""Runs the real OmniVoice worker in a subprocess against the stub omnivoice/torch (tests/stubs).
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
    old_local, old_steps = models.LOCAL, models.MODELS["omnivoice"]["pip_steps"]
    old_path = os.environ.get("PYTHONPATH")
    models.LOCAL = str(local)
    models.MODELS["omnivoice"]["pip_steps"] = []
    os.environ["PYTHONPATH"] = str(STUBS)
    log = "".join(text for kind, text in models.install("omnivoice") if kind == "log")
    yield log, local
    models.stop_all()
    models._join_background()
    models.LOCAL, models.MODELS["omnivoice"]["pip_steps"] = old_local, old_steps
    if old_path is None:
        os.environ.pop("PYTHONPATH")
    else:
        os.environ["PYTHONPATH"] = old_path


def _read(path):
    return Path(path).read_text(encoding="utf-8")


def test_download_does_not_load_asr(installed):
    log, _ = installed
    assert "stub omnivoice k2-fsa/OmniVoice loaded on cpu" in log
    assert "Whisper" not in log


def test_ref_text_and_settings_are_passed(installed):
    _, local = installed
    out = str(Path(local) / "clone.wav")
    models.generate("omnivoice", "hello", "/refs/me.wav", out, seed=7, settings={"num_step": 16, "speed": 1.2},
                    language="tr", ref_text="Merhaba")
    text = _read(out)
    for part in ("text=hello", "language=tr", "ref_audio=/refs/me.wav", "ref_text=Merhaba", "speed=1.2",
                 "num_step=16", "sr=24000", "subtype=PCM_16"):
        assert part in text, part
    assert "num_step=16.0" not in text  # steps are whole numbers


def test_seed_is_applied(installed):
    _, local = installed
    out = str(Path(local) / "seed.wav")
    models.generate("omnivoice", "hello", None, out, seed=42, settings={}, language="en")
    text = _read(out)
    assert "seed=42" in text and "ref_audio=None" in text and "num_step=32" in text and "speed=1.0" in text


def test_gpu_error_restarts_the_worker(installed):
    _, local = installed
    with pytest.raises(RuntimeError, match="restarted"):
        models.generate("omnivoice", "CRASH", None, str(Path(local) / "crash.wav"), seed=1, settings={}, language="en")
    assert "omnivoice" not in models._workers


def test_arabic_is_sent_as_standard_arabic(installed):
    _, local = installed
    out = str(Path(local) / "arabic.wav")
    models.generate("omnivoice", "marhaba", None, out, seed=1, settings={}, language="ar")
    assert "language=arb" in _read(out)


def test_out_of_memory_keeps_the_worker(installed):
    _, local = installed
    models.generate("omnivoice", "warm up", None, str(Path(local) / "w.wav"), seed=1, settings={}, language="en")
    process = models._workers["omnivoice"].process
    with pytest.raises(RuntimeError, match="Not enough GPU memory for OmniVoice"):
        models.generate("omnivoice", "OOM", None, str(Path(local) / "oom.wav"), seed=1, settings={}, language="en")
    assert models._workers["omnivoice"].process is process and process.poll() is None


def test_design_sends_the_attributes_as_instruct(installed):
    _, local = installed
    out = str(Path(local) / "design.wav")
    models.design("omnivoice", "hello", out, seed=3, language="en", description="female, british accent")
    text = _read(out)
    assert "ref_audio=None" in text and "instruct=female, british accent" in text and "seed=3" in text


def test_clone_sends_no_instruct(installed):
    _, local = installed
    out = str(Path(local) / "clone2.wav")
    models.generate("omnivoice", "hello", "/refs/me.wav", out, seed=1, settings={}, language="en", ref_text="Hi")
    assert "instruct=" not in _read(out)
