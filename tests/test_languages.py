"""Languages: OmniVoice offers its full list (646); codes are shared between models, Arabic is translated."""
import os

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402


def test_omnivoice_offers_all_its_languages():
    codes = {c for c in models.MODELS["omnivoice"]["languages"]}
    assert len(codes) == 647  # 646 of its own + "ar", sent to it as Standard Arabic
    assert {"tr", "en", "yue", "ckb", "nb", "ar"} <= codes


def test_every_language_has_an_english_name():
    for name in models.MODELS:
        for code in models.MODELS[name]["languages"]:
            assert models.LANGUAGE_NAMES.get(code), code
    assert models.LANGUAGE_NAMES["tr"] == "Turkish"
    assert models.LANGUAGE_NAMES["ar"] == "Arabic"  # Chatterbox's name is kept
    assert models.LANGUAGE_NAMES["ajg"] == "Aja (Benin)"
    assert models.LANGUAGE_NAMES["nb"] == "Norwegian Bokmål"


def test_chatterbox_languages_are_all_shared_with_omnivoice():
    omni = set(models.MODELS["omnivoice"]["languages"])
    assert set(models.MODELS["chatterbox"]["languages"]) <= omni


def test_model_code_translates_arabic_for_omnivoice():
    assert models.model_language("omnivoice", "ar") == "arb"
    assert models.model_language("omnivoice", "tr") == "tr"
    assert models.model_language("chatterbox", "ar") == "ar"
