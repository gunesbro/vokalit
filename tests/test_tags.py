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


def test_every_tag_is_known():
    assert models.TAGS == ["laughter", "sigh", "confirmation-en", "question-en", "question-ah", "question-oh",
                           "question-ei", "question-yi", "surprise-ah", "surprise-oh", "surprise-wa", "surprise-yo",
                           "dissatisfaction-hnn"]
