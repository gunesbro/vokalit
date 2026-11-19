"""Dubbing: an audio or video file's sentences spoken again in another language, in their own voices."""
import os

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402


def test_split_long_segments_cuts_at_sentence_ends():
    words = [{"start": i, "end": i + 0.9, "word": w} for i, w in
             enumerate(["One", "two.", "Three", "four", "five.", "Six", "seven", "eight", "nine", "ten."] * 2)]
    long = {"start": 0.0, "end": 19.9, "text": "...", "words": words}
    parts = models.split_long_segments([long], limit=8.0)
    assert all(p["end"] - p["start"] <= 8.0 for p in parts)
    assert all(p["text"].endswith(".") for p in parts)
    assert parts[0]["start"] == 0.0 and parts[-1]["end"] == 19.9
    assert " ".join(p["text"] for p in parts) == " ".join(w["word"] for w in words)


def test_split_long_segments_cuts_after_the_last_word_that_fits_without_a_sentence_end():
    words = [{"start": i, "end": i + 0.9, "word": f"w{i}"} for i in range(20)]
    parts = models.split_long_segments([{"start": 0.0, "end": 19.9, "text": "...", "words": words}], limit=8.0)
    assert all(p["end"] - p["start"] <= 8.0 for p in parts) and len(parts) == 3


def test_split_long_segments_keeps_short_ones_and_drops_words():
    short = {"start": 1.0, "end": 3.0, "text": "Hi.", "words": [{"start": 1.0, "end": 3.0, "word": "Hi."}]}
    assert models.split_long_segments([short]) == [{"start": 1.0, "end": 3.0, "text": "Hi."}]
