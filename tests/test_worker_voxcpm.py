"""Runs the real VoxCPM2 worker in a subprocess against the stub voxcpm/torch (tests/stubs).
Needs `uv` and `python3.11` on PATH, like tests/test_worker.py."""
import importlib.util
import os
from pathlib import Path

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402

STUBS = Path(__file__).resolve().parent / "stubs"
WORKER = Path(__file__).resolve().parent.parent / "workers" / "voxcpm" / "worker.py"
LANGUAGES = ["ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "id", "it", "ja", "km", "ko", "lo", "ms",
             "my", "nl", "no", "pl", "pt", "ru", "sv", "sw", "th", "tl", "tr", "vi", "zh"]


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    local = tmp_path_factory.mktemp("local")
    old_local, old_steps = models.LOCAL, models.MODELS["voxcpm"]["pip_steps"]
    old_path = os.environ.get("PYTHONPATH")
    models.LOCAL = str(local)
    models.MODELS["voxcpm"]["pip_steps"] = []
    os.environ["PYTHONPATH"] = str(STUBS)
    log = "".join(text for kind, text in models.install("voxcpm") if kind == "log")
    yield log, local
    models.stop_all()
    models._join_background()
    models.LOCAL, models.MODELS["voxcpm"]["pip_steps"] = old_local, old_steps
    if old_path is None:
        os.environ.pop("PYTHONPATH")
    else:
        os.environ["PYTHONPATH"] = old_path


def _read(path):
    return Path(path).read_text(encoding="utf-8")


def _generate(local, name, text, style="", **settings):
    out = str(Path(local) / f"{name}.wav")
    models.generate("voxcpm", text, "/refs/me.wav", out, seed=7,
                    settings=models.validate_settings("voxcpm", {"style": style, **settings}), language="tr")
    return _read(out)


def test_download_loads_without_denoiser(installed):
    log, _ = installed
    assert "stub voxcpm openbmb/VoxCPM2 denoiser=False" in log


def test_download_stays_off_the_gpu(installed):
    log, _ = installed
    assert "denoiser=False device=cpu optimize=False" in log


def test_style_is_sent_in_parentheses(installed):
    _, local = installed
    text = _generate(local, "style", "Merhaba.", style="cheerful, warm", cfg_value=2.5, inference_timesteps=12)
    for part in ("text=(cheerful, warm)Merhaba.", "reference_wav_path=/refs/me.wav", "denoise=False",
                 "normalize=False", "cfg_value=2.5", "inference_timesteps=12", "seed=7"):
        assert part in text, part
    assert "inference_timesteps=12.0" not in text  # steps are whole numbers


def test_empty_style_sends_plain_text(installed):
    _, local = installed
    assert "text=Merhaba.|" in _generate(local, "plain", "Merhaba.")


def test_take_is_written_at_the_model_rate(installed):
    _, local = installed
    text = _generate(local, "rate", "Merhaba.")
    assert "sr=48000" in text and "subtype=PCM_16" in text


def test_out_of_memory_keeps_the_worker(installed):
    _, local = installed
    _generate(local, "warm", "warm up")
    process = models._workers["voxcpm"].process
    with pytest.raises(RuntimeError, match="Not enough GPU memory for VoxCPM2"):
        _generate(local, "oom", "OOM")
    assert models._workers["voxcpm"].process is process and process.poll() is None


def test_text_parentheses_become_commas():
    spec = importlib.util.spec_from_file_location("voxcpm_worker", WORKER)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    assert worker.prompt("(Ahmet) Geldim.", "") == "Ahmet, Geldim."
    assert worker.prompt("Bir (iki) \u00fc\u00e7.", "calm") == "(calm)Bir iki, \u00fc\u00e7."
    assert worker.prompt("Merhaba.", "") == "Merhaba."


def test_sounds_are_left_out():
    assert models.text_for("voxcpm", "Hi [laughter] there") == "Hi there"


def test_voxcpm_speaks_its_languages_and_has_names():
    assert models.MODELS["voxcpm"]["languages"] == LANGUAGES
    assert all(code in models.LANGUAGE_NAMES for code in LANGUAGES)


def test_style_setting_has_suggestions():
    style = models.MODELS["voxcpm"]["settings"][0]
    assert style["key"] == "style" and style["type"] == "text" and style["default"] == ""
    assert [s["label"] for s in style["suggestions"]] == ["Neutral", "Happy", "Sad", "Angry", "Calm", "Excited",
                                                          "Whispering", "Serious"]
    assert models.default_settings("voxcpm") == {"style": "", "cfg_value": 2.0, "inference_timesteps": 10}


def test_cancel_stops_the_worker_at_once(installed):
    import threading
    import time
    _, local = installed
    _generate(local, "warm2", "warm up")
    errors = []

    def run():
        models.set_owner("job-1")
        try:
            _generate(local, "slow", "SLOW")
        except RuntimeError as error:
            errors.append(str(error))

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.5)
    started = time.monotonic()
    assert models.cancel("voxcpm", "job-2") is False  # another job's request is left alone
    assert models.cancel("voxcpm", "job-1") is True
    thread.join(10)
    assert not thread.is_alive() and errors and time.monotonic() - started < 5
    assert "voxcpm" not in models._workers
    assert "text=Merhaba.|" in _generate(local, "again", "Merhaba.")  # the next take loads it again
