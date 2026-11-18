"""Runs the real Higgs TTS 3 worker in a subprocess against stub transformers/torch (tests/stubs).
Needs `uv` and `python3.11` on PATH, like tests/test_worker.py."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402

STUBS = Path(__file__).resolve().parent / "stubs"
LANGUAGES = ("af ar hy as ast az ba eu be bn bs bg ca ceb ckb zh hr cs da nl mhr en eo et fi fr gl ka de el gu ht ha "
             "he hi hu id it ja jv kn kk ko rw ky lv ln lt luo mk ms ml mt mi mr mn ne no oc fa pl pt ro ru nso sr sn "
             "sk sl es sw sv tl tg ta te th tr uk ur ug uz vi xh zu sq ny pa lg is ga kab kea kam la lb om ps sd so umb "
             "cy").split()


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    local = tmp_path_factory.mktemp("local")
    old_local, old_steps = models.LOCAL, models.MODELS["higgs"]["pip_steps"]
    old_path = os.environ.get("PYTHONPATH")
    models.LOCAL = str(local)
    models.MODELS["higgs"]["pip_steps"] = []
    os.environ["PYTHONPATH"] = str(STUBS)
    log = "".join(text for kind, text in models.install("higgs") if kind == "log")
    yield log, local
    models.stop_all()
    models._join_background()
    models.LOCAL, models.MODELS["higgs"]["pip_steps"] = old_local, old_steps
    os.environ.pop("STUB_GPU_FREE_GB", None)
    if old_path is None:
        os.environ.pop("PYTHONPATH")
    else:
        os.environ["PYTHONPATH"] = old_path


def _generate(local, name, text, ref_text="Merhaba dostum.", **settings):
    out = str(Path(local) / f"{name}.wav")
    models.generate("higgs", models.text_for("higgs", text), "/refs/me.wav", out, seed=7,
                    settings=models.validate_settings("higgs", settings), language="tr", ref_text=ref_text)
    return Path(out).read_text(encoding="utf-8")


def test_download_pins_the_revisions(installed):
    log, _ = installed
    assert f"stub download {models.HIGGS_PORT}@{models.HIGGS_PORT_REVISION}" in log
    assert f"stub download {models.HIGGS_CODEC}@{models.HIGGS_CODEC_REVISION}" in log


def test_tags_reach_the_model(installed):
    _, local = installed
    text = _generate(local, "tags", "[anger] Merhaba [cough] dostum [long-pause] tamam")
    assert "text=<|emotion:anger|> Merhaba <|sfx:cough|>Ahem dostum <|prosody:long_pause|> tamam|" in text


def test_reference_transcript_and_settings_are_passed(installed):
    _, local = installed
    text = _generate(local, "ref", "Merhaba.", temperature=0.9)
    for part in ("reference_audio=ref-audio", "reference_sample_rate=16000", "reference_text=Merhaba dostum.",
                 "temperature=0.9", "top_p=0.95", "seed=7", f"codec=codec@{models.HIGGS_CODEC_REVISION}",
                 "sr=24000", "subtype=PCM_16"):
        assert part in text, part


def test_precision_follows_free_gpu_memory(installed):
    _, local = installed
    models.unload("higgs")
    os.environ["STUB_GPU_FREE_GB"] = "16"
    assert "precision=bf16" in _generate(local, "big", "Merhaba.")
    mode = models.runtime("higgs")["mode"]
    assert mode["label"] == "Full precision" and "16.0 GB" in mode["reason"]
    models.unload("higgs")
    os.environ["STUB_GPU_FREE_GB"] = "9.8"
    assert "precision=8bit" in _generate(local, "small", "Merhaba.")
    mode = models.runtime("higgs")["mode"]
    assert mode["label"] == "8-bit" and "9.8 GB" in mode["reason"] and "10.7 GB" in mode["reason"]


def test_oom_is_reported(installed):
    _, local = installed
    _generate(local, "warm", "warm up")
    with pytest.raises(RuntimeError, match="Not enough GPU memory for Higgs TTS 3"):
        _generate(local, "oom", "OOM")


def test_higgs_performs_every_higgs_tag_and_no_omnivoice_question():
    sounds = models.MODELS["higgs"]["sounds"]
    assert set(models.HIGGS_TAGS) <= set(sounds) and "question-ah" not in sounds
    assert sounds["laughter"] == "<|sfx:laughter|>Haha" and sounds["whispering"] == "<|style:whispering|>"
    assert models.text_for("higgs", "[surprise] a [surprise-ah]") == "<|emotion:surprise|> a"


def test_higgs_languages_have_names():
    assert models.MODELS["higgs"]["languages"] == LANGUAGES
    assert all(code in models.LANGUAGE_NAMES for code in LANGUAGES)
