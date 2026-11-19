"""Dubbing: an audio or video file's sentences spoken again in another language, in their own voices."""
import os

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import dubs  # noqa: E402
import models  # noqa: E402
import workspace as ws  # noqa: E402
from conftest import make_wav  # noqa: E402

SEGMENTS = [{"start": 0.5, "end": 3.0, "text": "Merhaba."}, {"start": 4.0, "end": 9.0, "text": "Nas\u0131ls\u0131n?"}]


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


def test_create_dub_keeps_the_source_and_its_audio(tmp_workspace, tmp_path):
    dub = dubs.create_dub("Interview", b"video-bytes", "mp4")
    dubs.set_source_audio(dub, make_wav(tmp_path / "a.wav", 12).read_bytes())
    data = dubs.load_dub(dub)
    assert data["source"]["kind"] == "video" and data["source"]["file"] == "source.mp4"
    assert round(data["source"]["duration"], 1) == 12.0
    assert data["original_volume"] == 0.15 and (dubs.dub_dir(dub) / "source.mp4").read_bytes() == b"video-bytes"
    assert [d for d, _ in dubs.list_dubs()] == [dub]


def test_create_dub_refuses_unknown_types(tmp_workspace):
    for ext in ("exe", "../x", "", "MP4/../../x"):
        with pytest.raises(ws.WorkspaceError, match="cannot open"):
            dubs.create_dub("X", b"x", ext)
    assert dubs.list_dubs() == []


def test_create_dub_accepts_upper_case_extensions(tmp_workspace):
    dub = dubs.create_dub("X", b"x", "WAV")
    assert dubs.load_dub(dub)["source"] == {"file": "source.wav", "kind": "audio", "duration": None, "language": None}


def test_a_wav_source_is_not_overwritten_by_its_decoded_audio(tmp_workspace, tmp_path):
    dub = dubs.create_dub("X", b"original-wav-bytes", "wav")
    dubs.set_source_audio(dub, make_wav(tmp_path / "a.wav", 3).read_bytes())
    assert (dubs.dub_dir(dub) / "source.wav").read_bytes() == b"original-wav-bytes"
    assert round(ws.wav_duration(dubs.audio_path(dub)), 1) == 3.0


def test_transcript_makes_paired_tracks(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    original, dub_track = dubs.load_dub(dub)["tracks"]
    assert [c["id"] for c in original["clips"]] == ["o1", "o2"]
    assert original["clips"][0] == {"id": "o1", "start": 0.5, "end": 3.0, "text": "Merhaba."}
    assert dub_track["clips"][1] == {"id": "d2", "source_clip": "o2", "voice_from": "o2", "start": 4.0,
                                     "translation": "", "takes": [], "selected": None}
    assert dubs.load_dub(dub)["source"]["language"] == "tr"


def test_transcript_without_speech_leaves_an_empty_dub(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", [])
    assert [t["clips"] for t in dubs.load_dub(dub)["tracks"]] == [[], []]


def test_editing_and_deleting_source_sentences(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    dubs.update_source_clip(dub, "o1", "  Merhaba!  ")
    assert dubs.load_dub(dub)["tracks"][0]["clips"][0]["text"] == "Merhaba!"
    with pytest.raises(ws.WorkspaceError):
        dubs.update_source_clip(dub, "o9", "x")


def test_deleting_a_voice_source_falls_back(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    dubs.update_dub_clip(dub, "d1", voice_from="o2")
    dubs.delete_source_clip(dub, "o2")
    data = dubs.load_dub(dub)
    assert [c["id"] for c in data["tracks"][0]["clips"]] == ["o1"]
    clips = data["tracks"][1]["clips"]
    assert [c["id"] for c in clips] == ["d1"] and clips[0]["voice_from"] == "o1"


def test_voice_from_must_be_a_source_sentence(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    with pytest.raises(ws.WorkspaceError):
        dubs.update_dub_clip(dub, "d1", voice_from="o7")


def test_dub_clip_start_must_be_inside_the_source(tmp_workspace, tmp_path):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_source_audio(dub, make_wav(tmp_path / "a.wav", 12).read_bytes())
    dubs.set_transcript(dub, "tr", SEGMENTS)
    for bad in (-0.1, 12.5):
        with pytest.raises(ws.WorkspaceError):
            dubs.update_dub_clip(dub, "d1", start=bad)
    dubs.update_dub_clip(dub, "d1", start=1.25, translation=" Hello. ")
    clip = dubs.load_dub(dub)["tracks"][1]["clips"][0]
    assert clip["start"] == 1.25 and clip["translation"] == "Hello."


def test_options_are_checked(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_options(dub, target_language="en", model="higgs", settings={"higgs": {"temperature": 0.5}},
                     original_volume=0.4)
    data = dubs.load_dub(dub)
    assert (data["target_language"], data["model"], data["original_volume"]) == ("en", "higgs", 0.4)
    assert data["settings"] == {"higgs": {"temperature": 0.5}}
    with pytest.raises(ws.WorkspaceError):
        dubs.set_options(dub, original_volume=1.5)


def test_rename_and_delete(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.rename_dub(dub, "  Talk  ")
    assert dubs.load_dub(dub)["name"] == "Talk"
    dubs.delete_dub(dub)
    assert dubs.load_dub(dub) is None and dubs.list_dubs() == []


def test_takes_are_numbered_and_selected(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    first = dubs.new_take_path(dub, "d1")
    make_wav(first, 2)
    dubs.add_take(dub, "d1", {"file": str(first), "seed": 1, "duration": 2.0})
    second = dubs.new_take_path(dub, "d1")
    make_wav(second, 2)
    dubs.add_take(dub, "d1", {"file": str(second), "seed": 2, "duration": 2.0})
    assert (first.name, second.name) == ("d1-1.wav", "d1-2.wav")
    clip = dubs.load_dub(dub)["tracks"][1]["clips"][0]
    assert clip["selected"] == "takes/d1-2.wav" and [t["file"] for t in clip["takes"]] == ["takes/d1-1.wav",
                                                                                           "takes/d1-2.wav"]
    dubs.select_take(dub, "d1", "takes/d1-1.wav")
    assert dubs.load_dub(dub)["tracks"][1]["clips"][0]["selected"] == "takes/d1-1.wav"
    with pytest.raises(ws.WorkspaceError):
        dubs.select_take(dub, "d1", "takes/other.wav")


def _dub_with_audio(tmp_path, seconds):
    dub = dubs.create_dub("Talk", b"x", "mp3")
    dubs.set_source_audio(dub, make_wav(tmp_path / "source.wav", seconds).read_bytes())
    dubs.set_transcript(dub, "tr", SEGMENTS)
    return dub


def _read_wav(path):
    import wave

    import numpy as np
    with wave.open(str(path), "rb") as w:
        return w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(int)


def test_cut_reference_uses_only_the_chosen_sentence(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    path, text = dubs.cut_reference(dub, "d1")
    assert text == "Merhaba." and round(ws.wav_duration(path), 2) == 2.8  # 0.5-3.0 plus 0.15 s each side
    dubs.update_dub_clip(dub, "d1", voice_from="o2")
    path, text = dubs.cut_reference(dub, "d1")
    assert text == "Nasılsın?" and round(ws.wav_duration(path), 2) == 5.3


def test_cut_reference_stays_inside_the_file(tmp_workspace, tmp_path):
    dub = dubs.create_dub("Talk", b"x", "mp3")
    dubs.set_source_audio(dub, make_wav(tmp_path / "source.wav", 3).read_bytes())
    dubs.set_transcript(dub, "tr", [{"start": 0.05, "end": 2.95, "text": "Hi."}])
    assert round(ws.wav_duration(dubs.cut_reference(dub, "d1")[0]), 2) == 3.0


def test_fit_reports_overlaps_and_missing_takes():
    data = {"source": {"duration": 10.0}, "tracks": [{"clips": []}, {"clips": [
        {"id": "d1", "start": 0.5, "selected": "a", "takes": [{"file": "a", "duration": 4.3}]},
        {"id": "d2", "start": 4.0, "selected": "b", "takes": [{"file": "b", "duration": 6.0}]},
        {"id": "d3", "start": 9.5, "selected": None, "takes": []}]}]}
    assert dubs.fit(data) == {"d1": {"state": "long", "over": 0.8}, "d2": {"state": "long", "over": 0.5},
                              "d3": {"state": "missing", "over": 0.0}}


def test_fit_uses_start_order_and_the_file_end():
    data = {"source": {"duration": 10.0}, "tracks": [{"clips": []}, {"clips": [
        {"id": "d2", "start": 6.0, "selected": "b", "takes": [{"file": "b", "duration": 4.5}]},
        {"id": "d1", "start": 1.0, "selected": "a", "takes": [{"file": "a", "duration": 2.0}]}]}]}
    assert dubs.fit(data) == {"d1": {"state": "fits", "over": 0.0}, "d2": {"state": "long", "over": 0.5}}


def test_export_mixes_takes_at_their_times(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    take = dubs.new_take_path(dub, "d2")
    make_wav(take, 2)
    dubs.add_take(dub, "d2", {"file": str(take), "seed": 1, "duration": 2.0})
    dubs.set_options(dub, original_volume=0.0)
    out = dubs.export_dub(dub)
    rate, samples = _read_wav(out)
    assert out.parent.name == "exports" and len(samples) == 12 * rate
    assert abs(samples[: int(3.9 * rate)]).max() == 0 and abs(samples[int(4.1 * rate): int(5.9 * rate)]).max() > 0


def test_export_keeps_the_original_underneath(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    rate, samples = _read_wav(dubs.export_dub(dub))  # no takes yet: the original alone, at 15 %
    peak = abs(samples).max()
    assert 0.1 * 32767 * 0.13 < peak < 0.1 * 32767 * 0.17


def test_export_names_a_missing_take(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    take = dubs.new_take_path(dub, "d1")
    make_wav(take, 2)
    dubs.add_take(dub, "d1", {"file": str(take), "seed": 1, "duration": 2.0})
    take.unlink()
    with pytest.raises(ws.WorkspaceError, match="Sentence 1"):
        dubs.export_dub(dub)
