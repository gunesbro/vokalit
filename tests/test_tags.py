"""Sound tags such as [laughter]: models without tag support never get them (they would read them aloud)."""
import os

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402


def test_tags_are_removed_for_models_without_tags():
    text = "Hi [laughter] there [sigh]"
    assert models.text_for("chatterbox", text) == "Hi there"
    assert models.text_for("omnivoice", text) == text


def test_unknown_brackets_are_kept():
    assert models.text_for("chatterbox", "[note] hi [question-ah]") == "[note] hi"


OMNIVOICE = ["laughter", "sigh", "confirmation-en", "question-en", "question-ah", "question-oh", "question-ei",
             "question-yi", "surprise-ah", "surprise-oh", "surprise-wa", "surprise-yo", "dissatisfaction-hnn"]
HIGGS_NEW = ["cough", "crying", "screaming", "burping", "humming", "sniff", "sneeze",
             "elation", "amusement", "enthusiasm", "determination", "pride", "contentment", "affection", "relief",
             "contemplation", "confusion", "surprise", "awe", "longing", "arousal", "anger", "fear", "disgust",
             "bitterness", "sadness", "shame", "helplessness",
             "singing", "shouting", "whispering",
             "speed-very-slow", "speed-slow", "speed-fast", "speed-very-fast", "pitch-low", "pitch-high", "pause",
             "long-pause", "expressive-high", "expressive-low"]


def test_every_tag_is_known():
    assert models.TAGS == OMNIVOICE + HIGGS_NEW


def test_new_tags_are_stripped_for_other_models():
    for name in ("chatterbox", "voxcpm"):
        assert models.text_for(name, "[anger] Hi [cough] there [long-pause] ok") == "Hi there ok"


def test_surprise_emotion_and_surprise_sound_are_distinct():
    assert models.text_for("omnivoice", "[surprise] a [surprise-ah]") == "a [surprise-ah]"


def test_each_model_gets_its_own_sound_syntax(monkeypatch):
    monkeypatch.setitem(models.MODELS, "dia", {"title": "Dia", "settings": [], "sounds": {"laughter": "(laughs)"}})
    assert models.text_for("dia", "Hi [laughter] there [sigh]") == "Hi (laughs) there"


def test_models_list_the_sounds_they_perform():
    assert list(models.MODELS["omnivoice"]["sounds"]) == OMNIVOICE
    assert models.MODELS["omnivoice"]["sounds"]["laughter"] == "[laughter]"
    assert not models.MODELS["chatterbox"].get("sounds")
