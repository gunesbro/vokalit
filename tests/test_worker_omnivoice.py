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


def test_timed_duration_clamps_to_natural_pace():
    import importlib.util
    path = Path(__file__).resolve().parent.parent / "workers" / "omnivoice" / "worker.py"
    spec = importlib.util.spec_from_file_location("omnivoice_worker", path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    t = {"min_speed": 0.85, "max_speed": 1.25}
    assert worker.timed_duration({**t, "target": 2.0}, 2.0) == 2.0
    assert worker.timed_duration({**t, "target": 1.0}, 2.0) == 1.6  # at most 1.25x faster
    assert worker.timed_duration({**t, "target": 4.0}, 2.0) == 2.35  # at most 0.85x slower
    assert worker.timed_duration({**t, "target": 3.0}, 0.0) is None  # no estimate: its natural length
    assert worker.timed_duration({**t, "target": 1.0}, 2.0, speed=2.0) == 1.0  # the speed setting sets the pace


def test_timed_duration_keeps_its_natural_pace_within_the_room():
    import importlib.util
    path = Path(__file__).resolve().parent.parent / "workers" / "omnivoice" / "worker.py"
    spec = importlib.util.spec_from_file_location("omnivoice_worker", path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    t = {"min_speed": 0.85, "max_speed": 1.25}
    assert worker.timed_duration({**t, "target": 1.0, "room": 3.0}, 2.0) == 2.0  # ends after the speaker: natural
    assert worker.timed_duration({**t, "target": 1.0, "room": 1.8}, 2.0) == 1.8  # until the next sentence
    assert worker.timed_duration({**t, "target": 1.0, "room": 1.0}, 2.0) == 1.6  # at most 1.25x faster
    assert worker.timed_duration({**t, "target": 2.2, "room": 3.0}, 2.0) == 2.2  # slowed to end with the speaker


def _ref_with_silence(path):
    """1 s of silence, then 2 s of tone: OmniVoice's prompt keeps the 2 s."""
    import wave

    import numpy as np
    t = np.arange(48000) / 24000
    pcm = np.concatenate([np.zeros(24000), 0.1 * np.sin(2 * np.pi * 220 * t)]) * 32767
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm.astype("<i2").tobytes())
    return path


def test_timing_is_sent_as_duration(installed, tmp_path):
    _, local = installed
    ref = _ref_with_silence(tmp_path / "ref.wav")
    out = str(Path(local) / "timed.wav")
    timing = {"target": 3.2, "min_speed": 0.85, "max_speed": 1.25}
    models.generate("omnivoice", "abcdef", str(ref), out, seed=1, settings={}, language="en", ref_text="abcd",
                    timing=timing)
    text = _read(out)
    # Natural 3.0 s: 6 letters at 2 s (the prompt's speech, not the file's 3 s) per 4; 3.2 is within the speeds.
    assert "duration=3.2" in text and "voice_clone_prompt=" in text
    assert "pad_duration=0" in text  # no silence added after the length asked for
    assert timing["pace"] == round(3.0 / 3.2, 2)  # how much faster than natural, for Fit


def test_timing_without_reference_text_generates_naturally(installed, tmp_path):
    _, local = installed
    ref = _ref_with_silence(tmp_path / "ref2.wav")
    out = str(Path(local) / "notext.wav")
    models.generate("omnivoice", "abcdef", str(ref), out, seed=1, settings={}, language="en", ref_text="",
                    timing={"target": 0.6, "min_speed": 0.85, "max_speed": 1.25})
    assert "duration=" not in _read(out)


def test_no_timing_sends_no_duration(installed):
    _, local = installed
    out = str(Path(local) / "untimed.wav")
    models.generate("omnivoice", "hello", "/refs/me.wav", out, seed=1, settings={}, language="en", ref_text="Hi")
    assert "duration=" not in _read(out) and "pad_duration" not in _read(out) and "ref_audio=/refs/me.wav" in _read(out)


def _worker():
    import importlib.util
    path = Path(__file__).resolve().parent.parent / "workers" / "omnivoice" / "worker.py"
    spec = importlib.util.spec_from_file_location("omnivoice_worker_accent", path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    return worker


def test_native_accent_weights():
    worker = _worker()
    assert worker.guidance_weights(0) is None and worker.guidance_weights(None) is None
    assert worker.guidance_weights(1.0) == (2.0, 5.0)  # the dubbing setting of the paper
    assert worker.guidance_weights(0.5) == (2.5, 4.0)
    assert worker.guidance_weights(3) == (2.0, 5.0)  # never past it


def test_dual_guidance_mixes_three_predictions():
    import numpy as np
    worker = _worker()
    c, u, t = np.array([0.0, -1.0]), np.array([-2.0, -0.5]), np.array([-1.0, -1.0])
    assert np.allclose(worker.dual_guidance(c, u, t, 3, 3), u + 3 * (c - u))  # equal weights: plain guidance
    assert np.allclose(worker.dual_guidance(c, u, t, 2, 5), u + 5 * (t - u) + 2 * (c - t))


def test_native_accent_guides_only_that_call(installed, tmp_path):
    """The stub never runs OmniVoice's decoding, so the guidance cannot be applied: the worker says so rather than
    hand back a take that silently ignored the setting. The next call is OmniVoice's own again."""
    from conftest import make_wav
    _, local = installed
    ref = make_wav(tmp_path / "ref.wav", 2)
    out = str(Path(local) / "accent.wav")
    with pytest.raises(RuntimeError, match="could not be applied"):
        models.generate("omnivoice", "hello", str(ref), out, seed=1, settings={"accent": 1.0}, language="tr",
                        ref_text="Hi")
    again = str(Path(local) / "plain.wav")
    models.generate("omnivoice", "hello", str(ref), again, seed=1, settings={}, language="tr", ref_text="Hi")
    assert "guidance=" not in _read(again)  # put back after the call


def test_native_accent_restores_what_the_model_had():
    worker = _worker()

    class Model:
        def _prepare_inference_inputs(self, *a):
            return "class"

        def forward(self, *a, **k):
            return "class"

        def _predict_tokens_with_scoring(self, *a):
            return "class"

    model = Model()
    own = model.forward = lambda *a, **k: "its own"  # e.g. a loader's hook on the instance
    with pytest.raises(RuntimeError):
        with worker.accent_guidance(model, (2.0, 5.0, 0)):
            pass  # nothing decoded: the guidance was never applied
    assert model.forward is own and "_predict_tokens_with_scoring" not in model.__dict__


def test_native_accent_is_an_omnivoice_setting():
    spec = {s["key"]: s for s in models.MODELS["omnivoice"]["settings"]}["accent"]
    assert spec["default"] == 0 and spec["min"] == 0 and spec["max"] == 1 and spec["label"] == "Native accent"


def test_guidance_plan_keeps_the_reference_weight_for_accent_removal():
    worker = _worker()
    assert worker.guidance_plan(0, 0) is None
    assert worker.guidance_plan(1.0, 0) == (2.0, 5.0, 0)  # Native accent alone, as before
    assert worker.guidance_plan(0, 5) == (3.0, 5.0, 5)  # the paper's OmniVoice setting: the sample keeps its weight
    assert worker.guidance_plan(0.5, 5) == (2.5, 5.0, 5)


def test_aag_mix_takes_out_the_accent_direction():
    import numpy as np
    worker = _worker()
    c, u, t = np.array([0.0, -1.0]), np.array([-2.0, -0.5]), np.array([-1.0, -1.0])
    src = [np.array([-0.2, -0.9]), np.array([-0.4, -0.7])]
    tgt = [np.array([-0.5, -0.5]), np.array([-0.6, -0.6])]
    assert np.allclose(worker.aag_mix(c, u, t, src, tgt, 3, 5, 0), worker.dual_guidance(c, u, t, 3, 5))
    expected = worker.dual_guidance(c, u, t, 3, 5) - 5 / 2 * ((src[0] - tgt[0]) + (src[1] - tgt[1]))
    assert np.allclose(worker.aag_mix(c, u, t, src, tgt, 3, 5, 5), expected)


def test_accent_removal_is_refused_when_it_cannot_be_applied(installed, tmp_path):
    from conftest import make_wav
    _, local = installed
    ref = make_wav(tmp_path / "ref.wav", 2)
    proxies = [{"gender": g, "src": str(make_wav(tmp_path / f"{g}-src.wav", 2)), "src_text": "konnichiwa",
                "tgt": str(make_wav(tmp_path / f"{g}-tgt.wav", 2)), "tgt_text": "merhaba"} for g in ("female", "male")]
    out = str(Path(local) / "aag.wav")
    with pytest.raises(RuntimeError, match="could not be applied"):
        models.generate("omnivoice", "hello", str(ref), out, seed=1, settings={"accent_removal": 5}, language="tr",
                        ref_text="Hi", proxies=proxies)


def test_accent_removal_is_an_omnivoice_setting():
    spec = {s["key"]: s for s in models.MODELS["omnivoice"]["settings"]}["accent_removal"]
    assert (spec["default"], spec["min"], spec["max"], spec["step"]) == (0, 0, 8, 0.5)
    assert models.MODELS["omnivoice"]["accent_removal"] is True


def test_branch_rows_mark_a_sample_s_tokens_as_audio():
    """A proxy branch's prefix holds its sample's audio tokens: they are audio to the model, like the line's own
    sample, not text (the text-alone branch has none)."""
    worker = _worker()
    # prefixes of 10 (text alone), 30 (text, then a sample from 12), 25 (a sample from 9); 5 target tokens
    assert worker.branch_layout([10, 30, 25], [10, 12, 9], 5) == [(15, 10), (35, 12), (30, 9)]
