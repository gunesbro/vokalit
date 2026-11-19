"""Voice design: descriptions checked per model (OmniVoice takes fixed attributes, VoxCPM2 free text)."""
import os

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402


def test_omnivoice_takes_its_attributes():
    assert models.check_description("omnivoice", " Female, young adult ,high pitch, british accent ") == \
        "female, young adult, high pitch, british accent"
    assert models.check_description("omnivoice", "") == ""


@pytest.mark.parametrize("description", ["female, male", "angry", "whisper, whisper", "low pitch, very low pitch"])
def test_design_rejects_unknown_omnivoice_attributes(description):
    with pytest.raises(ValueError, match="OmniVoice"):
        models.check_description("omnivoice", description)


def test_voxcpm_takes_free_text():
    assert models.check_description("voxcpm", " a young woman (soft) ,  warm ") == "a young woman soft , warm"
    with pytest.raises(ValueError, match="200"):
        models.check_description("voxcpm", "a" * 201)


def test_design_needs_a_model_that_designs():
    for name in ("chatterbox", "higgs"):
        with pytest.raises(ValueError, match="cannot design"):
            models.check_description(name, "female")
