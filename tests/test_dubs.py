"""Dubbing: an audio or video file's sentences spoken again in another language, in their own voices."""
import os
from pathlib import Path

import numpy as np
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
    assert dub_track["language"] == "en" and dub_track["id"] == "dub-en"
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
    dubs.set_options(dub, original_volume=0.4)
    dubs.set_language_options(dub, "en", model="higgs", settings={"higgs": {"temperature": 0.5}})
    data = dubs.load_dub(dub)
    track = data["tracks"][1]
    assert (track["language"], track["model"], data["original_volume"]) == ("en", "higgs", 0.4)
    assert track["settings"] == {"higgs": {"temperature": 0.5}}
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
    assert clip["selected"] == "takes/en/d1-2.wav" and [t["file"] for t in clip["takes"]] == ["takes/en/d1-1.wav",
                                                                                           "takes/en/d1-2.wav"]
    dubs.select_take(dub, "d1", "takes/en/d1-1.wav")
    assert dubs.load_dub(dub)["tracks"][1]["clips"][0]["selected"] == "takes/en/d1-1.wav"
    with pytest.raises(ws.WorkspaceError):
        dubs.select_take(dub, "d1", "takes/en/other.wav")


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
    assert text == "Nas\u0131ls\u0131n?" and round(ws.wav_duration(path), 2) == 5.3


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
    assert dubs.fit(data) == {"d1": {"state": "long", "over": 0.8, "need": 1.25, "can_fit": True},
                              "d2": {"state": "long", "over": 0.5, "need": 1.1, "can_fit": True},
                              "d3": {"state": "missing", "over": 0.0}}


def test_fit_uses_start_order_and_the_file_end():
    data = {"source": {"duration": 10.0}, "tracks": [{"clips": []}, {"clips": [
        {"id": "d2", "start": 6.0, "selected": "b", "takes": [{"file": "b", "duration": 4.5}]},
        {"id": "d1", "start": 1.0, "selected": "a", "takes": [{"file": "a", "duration": 2.0}]}]}]}
    assert dubs.fit(data) == {"d1": {"state": "fits", "over": 0.0}, "d2": {"state": "long", "over": 0.5, "need": 1.14, "can_fit": True}}


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


def test_concurrent_changes_are_not_lost(tmp_workspace, monkeypatch):
    # A take added by a generate job while the user saves a translation: both must stay.
    import threading
    import time
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    take = dubs.new_take_path(dub, "d1")
    make_wav(take, 1)
    real_write = ws._write_json

    def slow_write(path, data, **options):
        time.sleep(0.05)
        real_write(path, data, **options)

    monkeypatch.setattr(ws, "_write_json", slow_write)
    threads = [threading.Thread(target=dubs.add_take, args=(dub, "d1", {"file": str(take), "seed": 1, "duration": 1.0})),
               threading.Thread(target=dubs.update_dub_clip, args=(dub, "d2"), kwargs={"translation": "How are you?"})]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    clips = dubs.load_dub(dub)["tracks"][1]["clips"]
    assert clips[0]["selected"] == "takes/en/d1-1.wav" and clips[1]["translation"] == "How are you?"


def test_set_translations_saves_many_at_once(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    dubs.update_dub_clip(dub, "d2", translation="Old.")
    dubs.set_translations(dub, {"d1": " Hello. "})
    clips = dubs.load_dub(dub)["tracks"][1]["clips"]
    assert [c["translation"] for c in clips] == ["Hello.", "Old."]
    with pytest.raises(ws.WorkspaceError):
        dubs.set_translations(dub, {"d9": "x"})
    assert dubs.load_dub(dub)["tracks"][1]["clips"][0]["translation"] == "Hello."


def _with_take(dub, clip_id):
    take = dubs.new_take_path(dub, clip_id)
    make_wav(take, 1)
    dubs.add_take(dub, clip_id, {"file": str(take), "seed": 1, "duration": 1.0})
    return take


def test_deleting_a_sentence_keeps_its_take_files(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    take = _with_take(dub, "d2")
    dubs.delete_source_clip(dub, "o2")
    assert take.exists()  # so undo can bring the sentence back with its takes


def test_restore_sentence_puts_it_back_with_its_takes(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    _with_take(dub, "d1")
    dubs.update_dub_clip(dub, "d1", translation="Hello.")
    before = dubs.load_dub(dub)
    source, clip = before["tracks"][0]["clips"][0], before["tracks"][1]["clips"][0]
    dubs.delete_source_clip(dub, "o1")
    dubs.restore_sentence(dub, source, {"en": clip}, 0)
    after = dubs.load_dub(dub)
    assert after["tracks"] == before["tracks"]
    dubs.delete_source_clip(dub, "o1")
    dubs.delete_source_clip(dub, "o2")
    dubs.restore_sentence(dub, source, {"en": clip}, 5)  # the place no longer exists: appended
    assert [c["id"] for c in dubs.load_dub(dub)["tracks"][1]["clips"]] == ["d1"]


def test_restore_refuses_an_existing_sentence(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    data = dubs.load_dub(dub)
    with pytest.raises(ws.WorkspaceError):
        dubs.restore_sentence(dub, data["tracks"][0]["clips"][0], {"en": data["tracks"][1]["clips"][0]}, 0)


def test_select_take_none_clears_the_choice(tmp_workspace):
    # Undo of a first generation: the sentence had no take selected before.
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    _with_take(dub, "d1")
    dubs.select_take(dub, "d1", None)
    clip = dubs.load_dub(dub)["tracks"][1]["clips"][0]
    assert clip["selected"] is None and len(clip["takes"]) == 1


def test_restore_sentence_points_voices_back_at_it(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    dubs.update_dub_clip(dub, "d2", voice_from="o1")
    data = dubs.load_dub(dub)
    source, clip = data["tracks"][0]["clips"][0], data["tracks"][1]["clips"][0]
    dubs.delete_source_clip(dub, "o1")
    dubs.restore_sentence(dub, source, {"en": clip}, 0, voices={"en": ["d2"]})
    assert dubs.load_dub(dub)["tracks"][1]["clips"][1]["voice_from"] == "o1"


def _payload(data, source_id):
    """As the window's sentencePayload: what restore_sentence needs to put a sentence back."""
    sources = data["tracks"][0]["clips"]
    index = next(n for n, s in enumerate(sources) if s["id"] == source_id)
    return {"source": sources[index], "index": index,
            "clips": {t["language"]: next(c for c in t["clips"] if c["source_clip"] == source_id) for t in data["tracks"][1:]},
            "voices": {t["language"]: [c["id"] for c in t["clips"] if c["source_clip"] != source_id
                                       and c["voice_from"] == source_id] for t in data["tracks"][1:]}}


def test_join_with_next_makes_one_sentence_of_two(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    dubs.set_translations(dub, {"d1": "Hello.", "d2": "How are you?"})
    assert dubs.join_with_next(dub, "o1") == "o2"
    data = dubs.load_dub(dub)
    assert data["tracks"][0]["clips"] == [{**SEGMENTS[0], "id": "o1", "end": 9.0, "text": "Merhaba. Nasılsın?"}]
    assert [(c["id"], c["translation"]) for c in data["tracks"][1]["clips"]] == [("d1", "Hello. How are you?")]
    with pytest.raises(ws.WorkspaceError):  # nothing after it
        dubs.join_with_next(dub, "o1")


def test_join_refuses_a_kept_sentence(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    dubs.set_keep_original(dub, "o2", True)
    with pytest.raises(ws.WorkspaceError):
        dubs.join_with_next(dub, "o1")


def test_split_joined_puts_both_back(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS + [{"start": 10.0, "end": 11.0, "text": "Iyi."}])
    dubs.set_translations(dub, {"d1": "Hello.", "d2": "How are you?"})
    _with_take(dub, "d2")
    dubs.update_dub_clip(dub, "d3", voice_from="o2")
    before = dubs.load_dub(dub)
    first, second = _payload(before, "o1"), _payload(before, "o2")
    dubs.join_with_next(dub, "o1")
    assert dubs.load_dub(dub)["tracks"][1]["clips"][1]["voice_from"] == "o1"  # its voice now comes from the joined one
    dubs.split_joined(dub, first["source"], first["clips"], second)
    assert dubs.load_dub(dub)["tracks"] == before["tracks"]


def test_old_single_language_dubs_are_migrated(tmp_workspace):
    dub = dubs.create_dub("Old", b"x", "mp3")
    data = dubs.load_dub(dub)
    data.update({"target_language": "de", "model": "higgs", "settings": {"higgs": {"temperature": 0.4}}})
    data["tracks"][1] = {"id": "dub", "kind": "speech", "voice": {"mode": "original"}, "clips": []}
    dubs.save_dub(dub, data)
    track = dubs.load_dub(dub)["tracks"][1]
    assert (track["id"], track["language"], track["model"]) == ("dub-de", "de", "higgs")
    assert track["settings"] == {"higgs": {"temperature": 0.4}}
    assert dubs.languages(dubs.load_dub(dub)) == ["de"]


def test_languages_have_their_own_translations_takes_and_timing(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    dubs.add_language(dub, "de")
    assert dubs.languages(dubs.load_dub(dub)) == ["en", "de"]
    dubs.update_dub_clip(dub, "d1", translation="Hallo.", start=1.0, language="de")
    take = dubs.new_take_path(dub, "d1", language="de")
    assert take.parent.name == "de" and take.name == "d1-1.wav"
    make_wav(take, 1)
    dubs.add_take(dub, "d1", {"file": str(take), "seed": 1, "duration": 1.0}, language="de")
    data = dubs.load_dub(dub)
    en, de = data["tracks"][1]["clips"][0], data["tracks"][2]["clips"][0]
    assert (en["translation"], en["start"], en["selected"]) == ("", 0.5, None)
    assert (de["translation"], de["start"], de["selected"]) == ("Hallo.", 1.0, "takes/de/d1-1.wav")
    assert dubs.fit(data, "de")["d1"]["state"] != "missing" and dubs.fit(data, "en")["d1"]["state"] == "missing"
    assert "-de-" in dubs.export_dub(dub, language="de").name
    with pytest.raises(ws.WorkspaceError):
        dubs.add_language(dub, "de")


def test_removing_languages(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.add_language(dub, "fr")
    dubs.remove_language(dub, "en")
    assert dubs.languages(dubs.load_dub(dub)) == ["fr"]
    with pytest.raises(ws.WorkspaceError, match="last"):
        dubs.remove_language(dub, "fr")


def test_sentences_are_shared_by_every_language(tmp_workspace):
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    dubs.add_language(dub, "de")
    assert [c["id"] for c in dubs.load_dub(dub)["tracks"][2]["clips"]] == ["d1", "d2"]
    data = dubs.load_dub(dub)
    source = data["tracks"][0]["clips"][0]
    clips = {"en": data["tracks"][1]["clips"][0], "de": data["tracks"][2]["clips"][0]}
    dubs.delete_source_clip(dub, "o1")
    assert [len(t["clips"]) for t in dubs.load_dub(dub)["tracks"]] == [1, 1, 1]
    dubs.restore_sentence(dub, source, clips, 0)
    assert dubs.load_dub(dub)["tracks"] == data["tracks"]
    dubs.set_transcript(dub, "tr", SEGMENTS[:1])
    assert [len(t["clips"]) for t in dubs.load_dub(dub)["tracks"]] == [1, 1, 1]


def test_restore_sentence_forgets_takes_whose_files_are_gone(tmp_workspace):
    # Undo of a delete after its language was removed and added again: the old take files no longer exist.
    dub = dubs.create_dub("I", b"x", "mp3")
    dubs.set_transcript(dub, "tr", SEGMENTS)
    dubs.add_language(dub, "de")
    take = _with_take_in(dub, "d2", "de")
    data = dubs.load_dub(dub)
    source, clips = data["tracks"][0]["clips"][1], {"de": data["tracks"][2]["clips"][1]}
    dubs.delete_source_clip(dub, "o2")
    dubs.remove_language(dub, "de")
    dubs.add_language(dub, "de")
    assert not take.exists()
    dubs.restore_sentence(dub, source, clips, 1)
    clip = dubs.load_dub(dub)["tracks"][2]["clips"][1]
    assert clip["takes"] == [] and clip["selected"] is None


def _with_take_in(dub, clip_id, language):
    take = dubs.new_take_path(dub, clip_id, language=language)
    make_wav(take, 1)
    dubs.add_take(dub, clip_id, {"file": str(take), "seed": 1, "duration": 1.0}, language=language)
    return take


def test_keep_original_marks_a_sentence_in_every_language(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    dubs.add_language(dub, "de")
    dubs.set_keep_original(dub, "o2", True)
    data = dubs.load_dub(dub)
    assert data["tracks"][0]["clips"][1]["keep_original"] is True
    assert dubs.fit(data, "en")["d2"] == {"state": "kept", "over": 0.0} == dubs.fit(data, "de")["d2"]
    dubs.set_keep_original(dub, "o2", False)
    assert "keep_original" not in dubs.load_dub(dub)["tracks"][0]["clips"][1]


def test_export_plays_kept_sentences_at_full_volume(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)  # sentence 2 is 4.0-9.0 s
    dubs.set_keep_original(dub, "o2", True)
    rate, samples = _read_wav(dubs.export_dub(dub))
    loud, quiet = abs(samples[int(5 * rate): int(8 * rate)]).max(), abs(samples[int(10 * rate): int(11 * rate)]).max()
    assert loud > 0.1 * 32767 * 0.9 and quiet < 0.1 * 32767 * 0.2


def test_dub_json_is_written_compact(tmp_workspace):
    did = dubs.create_dub("Compact", b"video-bytes", "mp4")
    data = dubs.load_dub(did)
    dubs.save_dub(did, data)
    text = (dubs.dub_dir(did) / "dub.json").read_text(encoding="utf-8")
    assert "\n  " not in text
    assert dubs.load_dub(did) == data


def _long_take(tmp_path, seconds):
    """A dub whose first sentence (0.5 s; the next starts at 4.0 s, so 3.45 s of room) has a take of `seconds`."""
    dub = _dub_with_audio(tmp_path, seconds=12)
    take = dubs.new_take_path(dub, "d1")
    make_wav(take, seconds)
    dubs.add_take(dub, "d1", {"file": str(take), "seed": 1, "duration": float(seconds)})
    return dub


def test_fit_take_speeds_up_to_the_slot(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 4.0)
    speed = dubs.fit_take(dub, "d1")
    clip = dubs.load_dub(dub)["tracks"][1]["clips"][0]
    fitted = next(t for t in clip["takes"] if t["file"] == clip["selected"])
    assert len(clip["takes"]) == 2 and fitted["file"] != clip["takes"][0]["file"]
    assert abs(speed - 4.0 / 3.45) < 0.01 and fitted["speed"] == round(speed, 2)
    assert fitted["duration"] <= 3.46 and abs(ws.wav_duration(dubs.dub_dir(dub) / fitted["file"]) - 3.45) < 0.02
    assert fitted["from"] == clip["takes"][0]["file"]


def test_fit_refuses_over_the_limit(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 5.0)
    with pytest.raises(dubs.NeedsShorter, match="1.45\u00d7 faster"):
        dubs.fit_take(dub, "d1")
    assert len(dubs.load_dub(dub)["tracks"][1]["clips"][0]["takes"]) == 1


def test_fit_refuses_a_take_that_fits(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 3.0)
    with pytest.raises(ws.WorkspaceError, match="already fits"):
        dubs.fit_take(dub, "d1")


def test_fit_with_no_room_before_the_next_sentence(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 3.0)
    dubs.update_dub_clip(dub, "d2", start=0.5)
    with pytest.raises(dubs.NeedsShorter, match="no time"):
        dubs.fit_take(dub, "d1")


def test_fit_without_a_take_or_its_file(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 4.0)
    with pytest.raises(ws.WorkspaceError, match="no take yet"):
        dubs.fit_take(dub, "d2")
    clip = dubs.load_dub(dub)["tracks"][1]["clips"][0]
    (dubs.dub_dir(dub) / clip["selected"]).unlink()
    with pytest.raises(ws.WorkspaceError, match="missing"):
        dubs.fit_take(dub, "d1")


def test_fitting_again_starts_from_the_original_take(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 4.0)
    dubs.fit_take(dub, "d1")
    dubs.update_dub_clip(dub, "d2", start=3.8)  # less room: 3.25 s
    speed = dubs.fit_take(dub, "d1")
    clip = dubs.load_dub(dub)["tracks"][1]["clips"][0]
    fitted = next(t for t in clip["takes"] if t["file"] == clip["selected"])
    assert abs(speed - 4.0 / 3.25) < 0.01 and fitted["from"] == clip["takes"][0]["file"]


def test_fit_shows_the_speed(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 4.0)
    dubs.fit_take(dub, "d1")
    assert dubs.fit(dubs.load_dub(dub))["d1"] == {"state": "fits", "over": 0.0, "speed": 1.16}


def test_select_takes_changes_several_at_once(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 4.0)
    first = dubs.load_dub(dub)["tracks"][1]["clips"][0]["selected"]
    take = dubs.new_take_path(dub, "d2")
    make_wav(take, 1.0)
    dubs.add_take(dub, "d2", {"file": str(take), "seed": 1, "duration": 1.0})
    second = dubs.load_dub(dub)["tracks"][1]["clips"][1]["selected"]
    dubs.select_takes(dub, {"d1": None, "d2": None})
    assert [c["selected"] for c in dubs.load_dub(dub)["tracks"][1]["clips"]] == [None, None]
    with pytest.raises(ws.WorkspaceError, match="no longer exists"):
        dubs.select_takes(dub, {"d1": first, "d2": "takes/en/gone.wav"})
    assert [c["selected"] for c in dubs.load_dub(dub)["tracks"][1]["clips"]] == [None, None]  # all or nothing
    dubs.select_takes(dub, {"d1": first, "d2": second})
    assert [c["selected"] for c in dubs.load_dub(dub)["tracks"][1]["clips"]] == [first, second]


def test_fit_tells_long_takes_the_speed_they_need(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 4.0)  # 3.45 s of room
    take = dubs.new_take_path(dub, "d2")
    make_wav(take, 10.0)  # 7.95 s to the end of the file
    dubs.add_take(dub, "d2", {"file": str(take), "seed": 1, "duration": 10.0})
    result = dubs.fit(dubs.load_dub(dub))
    assert result["d1"]["need"] == 1.16 and result["d2"]["need"] == 1.26


def test_fit_need_comes_from_the_original_take(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 4.0)
    dubs.fit_take(dub, "d1")
    dubs.update_dub_clip(dub, "d2", start=3.0)  # the fitted take is long again: 2.45 s of room
    result = dubs.fit(dubs.load_dub(dub))["d1"]
    assert result["state"] == "long" and result["need"] == round(4.0 / 2.45, 2)


def test_fit_need_without_room_is_none(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 4.0)
    dubs.update_dub_clip(dub, "d2", start=0.5)
    assert dubs.fit(dubs.load_dub(dub))["d1"]["need"] is None


def test_fit_limit_is_on_the_speed_as_shown(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 4.3294)  # 1.2549x: shown as 1.25x, so it is fitted, not refused as "1.25x faster"
    assert dubs.fit(dubs.load_dub(dub))["d1"]["need"] == 1.25
    assert round(dubs.fit_take(dub, "d1"), 2) == 1.25


def test_clear_takes_removes_one_language_s_takes(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 4.0)
    dubs.update_dub_clip(dub, "d1", translation="Hello.")
    dubs.add_language(dub, "de")
    other = dubs.new_take_path(dub, "d1", "de")
    make_wav(other, 1.0)
    dubs.add_take(dub, "d1", {"file": str(other), "seed": 1, "duration": 1.0}, language="de")
    assert dubs.clear_takes(dub, "en") == 1
    data = dubs.load_dub(dub)
    en = dubs._track(data, "en")["clips"][0]
    assert en["takes"] == [] and en["selected"] is None and en["translation"] == "Hello."
    assert not (dubs.dub_dir(dub) / "takes" / "en").exists()
    assert dubs._track(data, "de")["clips"][0]["takes"] and other.exists()


def test_fit_marks_a_take_that_ends_before_the_speaker(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 1.9)  # the first sentence is spoken 0.5-3.0 s: 2.5 s to fill
    assert dubs.fit(dubs.load_dub(dub))["d1"] == {"state": "short", "over": 0.0, "under": 0.6, "need": 0.76, "can_fit": True}


def test_a_take_close_to_the_speaker_s_end_fits(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 2.2)  # 0.3 s early: within SHORT_GAP
    assert dubs.fit(dubs.load_dub(dub))["d1"]["state"] == "fits"


def test_fit_take_lengthens_a_short_take(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 1.9)
    speed = dubs.fit_take(dub, "d1")
    assert speed == dubs.MIN_SPEED  # 0.76 would be needed; 0.85 brings it within SHORT_GAP
    clip = dubs.load_dub(dub)["tracks"][1]["clips"][0]
    slower = next(t for t in clip["takes"] if t["file"] == clip["selected"])
    assert slower["speed"] == 0.85 and abs(slower["duration"] - 1.9 / 0.85) < 0.02
    assert dubs.fit(dubs.load_dub(dub))["d1"] == {"state": "fits", "over": 0.0, "speed": 0.85}


def test_fit_take_refuses_a_take_far_too_short(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 1.5)  # even at 0.85x it ends 0.74 s early
    assert dubs.fit(dubs.load_dub(dub))["d1"]["can_fit"] is False
    with pytest.raises(dubs.NeedsLonger, match="Lengthen the translation"):
        dubs.fit_take(dub, "d1")


def _stems(dub, voices_value, background_value, voices_extra=0, background_extra=0):
    """Writes constant stems the length of the dub's sound (plus or minus a few samples)."""
    import numpy as np
    rate, audio = dubs._read(dubs.audio_path(dub))
    dubs._write(dubs.voices_path(dub), rate, np.full(len(audio) + voices_extra, voices_value))
    dubs._write(dubs.background_path(dub), rate, np.full(len(audio) + background_extra, background_value))
    return rate, len(audio)


def test_references_come_from_the_voices(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    _stems(dub, 1234, 5000)
    path, _ = dubs.cut_reference(dub, "d1")
    _, samples = _read_wav(path)
    assert set(samples.tolist()) == {1234}


def test_export_with_stems_plays_the_background_full_and_voices_at_their_volume(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    rate, _ = _stems(dub, 2000, 1000)
    dubs.set_options(dub, voices_volume=0.5)
    _, mix = _read_wav(dubs.export_dub(dub))
    assert mix[int(10 * rate)] == 2000  # background 1000 + voices 2000 at 50 %
    dubs.set_keep_original(dub, "o1", True)  # spoken 0.5-3.0 s: the whole original there
    _, mix = _read_wav(dubs.export_dub(dub))
    assert mix[int(1.5 * rate)] == 3000 and mix[int(10 * rate)] == 2000


def test_stems_of_another_length_are_fitted(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    rate, length = _stems(dub, 2000, 1000, voices_extra=-10, background_extra=10)
    _, mix = _read_wav(dubs.export_dub(dub))
    assert len(mix) == length and mix[-1] == 1000  # the short voices are padded with silence (voices off by default)


def test_half_written_stems_do_not_count(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    assert not dubs.has_stems(dub)
    voices, background = dubs.stems_temp(dub)
    make_wav(voices, 12)
    make_wav(background, 12)
    assert not dubs.has_stems(dub)  # not kept yet
    dubs.keep_stems(dub)
    assert dubs.has_stems(dub) and not voices.exists()
    dubs.background_path(dub).unlink()
    assert not dubs.has_stems(dub)
    dubs.remove_stems(dub)
    assert not dubs.voices_path(dub).exists()


def test_voices_volume_starts_off_and_is_checked(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    assert dubs.load_dub(dub)["voices_volume"] == 0.0
    with pytest.raises(ws.WorkspaceError, match="voices"):
        dubs.set_options(dub, voices_volume=1.5)


def test_separating_again_replaces_both_stems_or_neither(tmp_workspace, tmp_path, monkeypatch):
    """A file in use (Windows) can refuse the second rename: the old pair stays, never new voices with an old background."""
    dub = _dub_with_audio(tmp_path, seconds=12)
    _stems(dub, 1000, 2000)
    for temp, value in zip(dubs.stems_temp(dub), (3000, 4000)):
        rate, audio = dubs._read(dubs.audio_path(dub))
        dubs._write(temp, rate, np.full(len(audio), value))
    real = os.replace

    def busy(source, target):  # the new background cannot be put in place
        if str(source).endswith("background.part.wav"):
            raise PermissionError("in use")
        real(source, target)

    monkeypatch.setattr(dubs.os, "replace", busy)
    with pytest.raises(PermissionError):
        dubs.keep_stems(dub)
    assert set(dubs._read(dubs.voices_path(dub))[1].tolist()) == {1000}
    assert set(dubs._read(dubs.background_path(dub))[1].tolist()) == {2000}


def _timed_dub(tmp_path, next_start):
    """A sentence spoken 1.0-5.0 s, its dub clip at 1.0 s, and a next sentence starting at `next_start`."""
    dub = dubs.create_dub("Talk", b"x", "mp3")
    dubs.set_source_audio(dub, make_wav(tmp_path / "source.wav", 12).read_bytes())
    dubs.set_transcript(dub, "tr", [{"start": 1.0, "end": 5.0, "text": "Bir."},
                                    {"start": max(next_start, 1.0), "end": 11.0, "text": "Iki."}])
    return dub


def test_generation_timing_targets_where_the_speaker_stops(tmp_workspace, tmp_path):
    dub = _timed_dub(tmp_path, 8.0)
    # At the earliest where the speaker stops, at the latest before the next sentence.
    assert dubs.generation_timing(dub, "d1") == {"target": 4.0, "room": round(7.0 - dubs.FIT_GAP, 2),
                                                 "min_speed": 0.85, "max_speed": 1.25}


def test_generation_timing_stops_before_the_next_sentence(tmp_workspace, tmp_path):
    dub = _timed_dub(tmp_path, 3.0)
    timing = dubs.generation_timing(dub, "d1")
    assert timing["target"] == timing["room"] == round(2.0 - dubs.FIT_GAP, 2)


def test_generation_timing_is_none_without_room(tmp_workspace, tmp_path):
    dub = _timed_dub(tmp_path, 8.0)
    dubs.update_dub_clip(dub, "d2", start=1.0)  # the next sentence moved onto this one
    assert dubs.generation_timing(dub, "d1") is None


def _tone(amplitude, seconds=2.0, rate=24000):
    import numpy as np
    t = np.arange(int(seconds * rate)) / rate
    return np.round(amplitude * 32767 * np.sin(2 * np.pi * 220 * t)).astype("<i2")


def _level_dub(tmp_path, original, take):
    """A dub whose sound is a tone of amplitude `original` and whose first sentence (0.5-3.0 s) has a take of
    amplitude `take`. Returns the dub and the take's path."""
    dub = _dub_with_audio(tmp_path, seconds=12)
    dubs._write(dubs.audio_path(dub), 24000, _tone(original, 12))
    path = dubs.new_take_path(dub, "d1")
    dubs._write(path, 24000, _tone(take))
    return dub, path


def _span_loudness(dub, path):
    rate, samples = dubs._read(path)
    return dubs._loudness(samples, rate)


def test_match_level_raises_a_quiet_take(tmp_workspace, tmp_path):
    dub, take = _level_dub(tmp_path, 0.2, 0.08)
    gain = dubs.match_level(dub, "d1", take)
    rate, audio = dubs._read(dubs.audio_path(dub))
    assert abs(_span_loudness(dub, take) - dubs._loudness(audio[int(0.5 * rate):int(3.0 * rate)], rate)) < 0.1
    assert abs(gain - 7.96) < 0.05


def test_match_level_gain_is_clamped(tmp_workspace, tmp_path):
    dub, take = _level_dub(tmp_path, 0.2, 0.001)
    assert dubs.match_level(dub, "d1", take) == 12.0
    dub, take = _level_dub(tmp_path, 0.001, 0.5)
    assert dubs.match_level(dub, "d1", take) == -12.0


def test_match_level_keeps_the_peak_under_minus_one_dbfs(tmp_workspace, tmp_path):
    dub, take = _level_dub(tmp_path, 0.6, 0.5)
    rate, samples = dubs._read(take)
    samples = samples.copy()
    samples[100] = round(0.85 * 32767)
    dubs._write(take, rate, samples)
    dubs.match_level(dub, "d1", take)
    _, after = dubs._read(take)
    assert abs(after.astype(int)).max() <= round(32767 * 10 ** (-1 / 20)) + 1


def test_match_level_leaves_the_take_when_the_original_is_silent(tmp_workspace, tmp_path):
    dub, take = _level_dub(tmp_path, 0.0, 0.1)
    before = take.read_bytes()
    assert dubs.match_level(dub, "d1", take) == 0.0 and take.read_bytes() == before


def test_match_level_measures_the_voices_stem(tmp_workspace, tmp_path):
    import numpy as np
    dub, take = _level_dub(tmp_path, 0.01, 0.1)
    rate, audio = dubs._read(dubs.audio_path(dub))
    dubs._write(dubs.voices_path(dub), rate, _tone(0.2, 12))
    dubs._write(dubs.background_path(dub), rate, np.zeros(len(audio)))
    dubs.match_level(dub, "d1", take)
    assert abs(_span_loudness(dub, take) - _span_loudness(dub, dubs.voices_path(dub))) < 0.1


def test_match_level_keeps_one_speaker_at_one_level(tmp_workspace, tmp_path):
    import numpy as np
    dub, take = _level_dub(tmp_path, 0.2, 0.1)
    rate, audio = dubs._read(dubs.audio_path(dub))
    loud, quiet = _tone(0.2, 3.5), _tone(0.05, 12 - 3.5)
    dubs._write(dubs.audio_path(dub), rate, np.concatenate([loud, quiet]))  # sentence 1 shouted, sentence 2 quiet
    speaker = dubs.set_speaker(dub, "o1", "new")
    dubs.set_speaker(dub, "o2", speaker)
    dubs.match_level(dub, "d1", take)
    data = dubs.load_dub(dub)
    _, both = dubs._read_span(dubs.audio_path(dub), 0.5, 3.0)
    _, second = dubs._read_span(dubs.audio_path(dub), data["tracks"][0]["clips"][1]["start"],
                                data["tracks"][0]["clips"][1]["end"])
    assert abs(_span_loudness(dub, take) - dubs._loudness(np.concatenate([both, second]), rate)) < 0.1


def test_match_level_with_a_sentence_past_the_end(tmp_workspace, tmp_path):
    dub, take = _level_dub(tmp_path, 0.2, 0.1)
    dubs._write(dubs.audio_path(dub), 24000, _tone(0.2, 0.3))  # the sound ends before the sentence starts
    before = take.read_bytes()
    assert dubs.match_level(dub, "d1", take) == 0.0 and take.read_bytes() == before


def _paced_take(tmp_path, seconds, pace):
    """As _long_take, with a take a timed model made `pace` times its natural speed."""
    dub = _dub_with_audio(tmp_path, seconds=12)
    take = dubs.new_take_path(dub, "d1")
    make_wav(take, seconds)
    dubs.add_take(dub, "d1", {"file": str(take), "seed": 1, "duration": float(seconds), "pace": pace})
    return dub


def test_fit_counts_the_speed_a_take_was_generated_at(tmp_workspace, tmp_path):
    dub = _paced_take(tmp_path, 4.0, 1.2)  # 1.16x more would make it 1.39x its natural pace
    assert dubs.fit(dubs.load_dub(dub))["d1"]["can_fit"] is False
    with pytest.raises(dubs.NeedsShorter, match="1.39\u00d7 faster"):
        dubs.fit_take(dub, "d1")


def test_fit_does_not_slow_a_take_generated_slow(tmp_workspace, tmp_path):
    dub = _paced_take(tmp_path, 1.9, 0.85)  # already as slow as speech may go
    assert dubs.fit(dubs.load_dub(dub))["d1"]["can_fit"] is False
    with pytest.raises(dubs.NeedsLonger):
        dubs.fit_take(dub, "d1")


def test_generation_timing_is_none_when_the_room_rounds_to_nothing(tmp_workspace, tmp_path):
    dub = _timed_dub(tmp_path, 8.0)
    dubs.update_dub_clip(dub, "d2", start=1.0 + dubs.FIT_GAP + 0.004)
    assert dubs.generation_timing(dub, "d1") is None


def test_a_sentence_s_level_and_reference_read_only_its_span(tmp_workspace, tmp_path, monkeypatch):
    dub, take = _level_dub(tmp_path, 0.2, 0.08)
    whole = dubs._read

    def only_takes(path):  # reading all of a long file per sentence is slow
        assert Path(path).name not in ("audio.wav", "voices.wav"), path
        return whole(path)

    monkeypatch.setattr(dubs, "_read", only_takes)
    assert abs(dubs.match_level(dub, "d1", take) - 7.96) < 0.05
    path, _ = dubs.cut_reference(dub, "d1")
    rate, samples = whole(path)
    assert abs(len(samples) / rate - (2.5 + 2 * dubs.REFERENCE_PADDING)) < 0.01


def _three_takes(tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    files = []
    for seconds in (1.0, 1.5, 2.0):
        take = dubs.new_take_path(dub, "d1")
        make_wav(take, seconds)
        dubs.add_take(dub, "d1", {"file": str(take), "seed": 1, "duration": seconds})
        files.append(dubs.load_dub(dub)["tracks"][1]["clips"][0]["selected"])
    return dub, files


def test_delete_takes_removes_one_and_selects_the_newest_left(tmp_workspace, tmp_path):
    dub, files = _three_takes(tmp_path)
    assert dubs.delete_takes(dub, {"d1": [files[2]]}) == 1
    clip = dubs.load_dub(dub)["tracks"][1]["clips"][0]
    assert [t["file"] for t in clip["takes"]] == files[:2] and clip["selected"] == files[1]
    assert not (dubs.dub_dir(dub) / files[2]).exists() and (dubs.dub_dir(dub) / files[0]).exists()


def test_delete_takes_of_whole_sentences(tmp_workspace, tmp_path):
    dub, files = _three_takes(tmp_path)
    assert dubs.delete_takes(dub, {"d1": None, "d2": None}) == 3
    clip = dubs.load_dub(dub)["tracks"][1]["clips"][0]
    assert clip["takes"] == [] and clip["selected"] is None
    assert not any((dubs.dub_dir(dub) / f).exists() for f in files)


def test_delete_takes_refuses_an_unknown_file(tmp_workspace, tmp_path):
    dub, files = _three_takes(tmp_path)
    with pytest.raises(dubs.ws.WorkspaceError, match="no longer exists"):
        dubs.delete_takes(dub, {"d1": ["takes/en/d1-9.wav"]})
    assert len(dubs.load_dub(dub)["tracks"][1]["clips"][0]["takes"]) == 3


def _two_languages(tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)  # sentences at 0.5-3.0 and 4.0-9.0
    dubs.add_language(dub, "de")
    return dub


def test_add_source_clip_inserts_by_time_in_every_language(tmp_workspace, tmp_path):
    dub = _two_languages(tmp_path)
    assert dubs.add_source_clip(dub, 3.2, 3.8) == "o3"
    data = dubs.load_dub(dub)
    assert [s["id"] for s in data["tracks"][0]["clips"]] == ["o1", "o3", "o2"]
    assert data["tracks"][0]["clips"][1] == {"id": "o3", "start": 3.2, "end": 3.8, "text": ""}
    for track in data["tracks"][1:]:
        clip = track["clips"][1]
        assert clip["id"] == "d3" and clip["source_clip"] == "o3" and clip["start"] == 3.2 and clip["translation"] == ""


def test_added_ids_never_reuse_a_deleted_sentence_s(tmp_workspace, tmp_path):
    dub = _two_languages(tmp_path)
    assert dubs.add_source_clip(dub, 10.0, 11.0) == "o3"
    dubs.delete_source_clip(dub, "o3")
    assert dubs.add_source_clip(dub, 10.0, 11.0) == "o4"


@pytest.mark.parametrize("start,end", [(5.0, 5.0), (5.0, 5.1), (11.5, 12.5), (-0.5, 1.0), (6.0, 5.0)])
def test_add_source_clip_refuses_bad_times(tmp_workspace, tmp_path, start, end):
    dub = _two_languages(tmp_path)
    with pytest.raises(dubs.ws.WorkspaceError, match="A sentence must"):
        dubs.add_source_clip(dub, start, end)


def test_retiming_moves_its_clips_and_keeps_time_order(tmp_workspace, tmp_path):
    dub = _two_languages(tmp_path)
    dubs.update_dub_clip(dub, "d1", start=0.7, language="de")  # moved by hand: keeps its offset
    dubs.update_source_clip(dub, "o1", start=10.0, end=11.0)
    data = dubs.load_dub(dub)
    assert [s["id"] for s in data["tracks"][0]["clips"]] == ["o2", "o1"]
    assert data["tracks"][0]["clips"][1] == {"id": "o1", "start": 10.0, "end": 11.0, "text": "Merhaba."}
    en, de = (track["clips"] for track in data["tracks"][1:])
    assert [c["id"] for c in en] == [c["id"] for c in de] == ["d2", "d1"]
    assert en[1]["start"] == 10.0 and de[1]["start"] == 10.2
    dubs.update_source_clip(dub, "o1", start=0.5, end=3.0)
    data = dubs.load_dub(dub)
    assert [s["id"] for s in data["tracks"][0]["clips"]] == ["o1", "o2"]
    assert [c["id"] for c in data["tracks"][2]["clips"]] == ["d1", "d2"] and data["tracks"][2]["clips"][0]["start"] == 0.7


def test_retiming_refuses_bad_times(tmp_workspace, tmp_path):
    dub = _two_languages(tmp_path)
    with pytest.raises(dubs.ws.WorkspaceError, match="A sentence must"):
        dubs.update_source_clip(dub, "o1", end=0.6)  # 0.1 s long
    with pytest.raises(dubs.ws.WorkspaceError, match="A sentence must"):
        dubs.update_source_clip(dub, "o2", end=13.0)


def test_fit_forgets_the_speed_when_the_original_take_is_gone(tmp_workspace, tmp_path):
    dub = _long_take(tmp_path, 3.9)  # room 3.45 s: fitted at 1.13x
    dubs.fit_take(dub, "d1")
    original = dubs.load_dub(dub)["tracks"][1]["clips"][0]["takes"][0]["file"]
    dubs.delete_takes(dub, {"d1": [original]})
    assert "speed" not in dubs.fit(dubs.load_dub(dub))["d1"]  # nothing to go back to: no longer listed as fitted


def test_bulk_delete_looks_each_sentence_up_once(tmp_workspace, tmp_path, monkeypatch):
    dub, _ = _three_takes(tmp_path)
    calls = []
    find = dubs._find
    monkeypatch.setattr(dubs, "_find", lambda clips, clip_id: calls.append(clip_id) or find(clips, clip_id))
    assert dubs.delete_takes(dub, {"d1": None, "d2": None}) == 3
    assert calls == []  # one lookup table, not a scan per sentence (30k sentences: tens of seconds)


def test_delete_takes_goes_on_when_a_file_is_busy(tmp_workspace, tmp_path, monkeypatch):
    dub, files = _three_takes(tmp_path)
    unlink = Path.unlink

    def busy(path, missing_ok=False):  # Windows: a file being read cannot be deleted
        if path.name == Path(files[0]).name:
            raise PermissionError("in use")
        return unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", busy)
    assert dubs.delete_takes(dub, {"d1": None}) == 3
    assert dubs.load_dub(dub)["tracks"][1]["clips"][0]["takes"] == []
    assert not (dubs.dub_dir(dub) / files[1]).exists() and not (dubs.dub_dir(dub) / files[2]).exists()


def _speakers(dub):
    data = dubs.load_dub(dub)
    return data["speakers"], [s.get("speaker") for s in data["tracks"][0]["clips"]]


def test_found_speakers_are_named_and_assigned(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    assert dubs.set_found_speakers(dub, {"o1": 1, "o2": 0}) == 2
    speakers, assigned = _speakers(dub)
    assert speakers == [{"id": "s1", "name": "Speaker 1"}, {"id": "s2", "name": "Speaker 2"}]
    assert assigned == ["s2", "s1"]


def test_finding_again_never_reuses_ids(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    dubs.set_found_speakers(dub, {"o1": 0, "o2": 1})
    dubs.set_found_speakers(dub, {"o1": 0, "o2": 0})
    assert _speakers(dub) == ([{"id": "s3", "name": "Speaker 1"}], ["s3", "s3"])


def test_new_speaker_takes_the_lowest_free_name(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    dubs.set_found_speakers(dub, {"o1": 0, "o2": 1})
    dubs.rename_speaker(dub, "s1", "  Ali ")
    new = dubs.set_speaker(dub, "o2", "new")
    speakers, assigned = _speakers(dub)
    assert new == "s3" and speakers[-1] == {"id": "s3", "name": "Speaker 1"} and speakers[0]["name"] == "Ali"
    assert assigned == ["s1", "s3"]
    assert dubs.set_speaker(dub, "o1", None) is None and _speakers(dub)[1] == [None, "s3"]
    with pytest.raises(dubs.ws.WorkspaceError, match="no longer exists"):
        dubs.set_speaker(dub, "o1", "s9")


def test_merge_and_restore(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    dubs.set_found_speakers(dub, {"o1": 0, "o2": 1})
    before = dubs.speakers_state(dubs.load_dub(dub))
    assert before == {"speakers": [{"id": "s1", "name": "Speaker 1"}, {"id": "s2", "name": "Speaker 2"}],
                      "assignments": {"o1": "s1", "o2": "s2"}}
    dubs.merge_speakers(dub, "s2", "s1")
    assert _speakers(dub) == ([{"id": "s1", "name": "Speaker 1"}], ["s1", "s1"])
    with pytest.raises(dubs.ws.WorkspaceError):
        dubs.merge_speakers(dub, "s1", "s1")
    dubs.restore_speakers(dub, before)
    assert dubs.speakers_state(dubs.load_dub(dub)) == before
    assert dubs.set_speaker(dub, "o1", "new") == "s3"  # the counter stays past restored ids


def test_restored_sentence_drops_a_merged_speaker(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    dubs.set_found_speakers(dub, {"o1": 0, "o2": 1})
    data = dubs.load_dub(dub)
    source, clip = data["tracks"][0]["clips"][1], data["tracks"][1]["clips"][1]
    dubs.delete_source_clip(dub, "o2")
    dubs.merge_speakers(dub, "s2", "s1")
    dubs.restore_sentence(dub, source, {"en": clip}, 1)
    assert "speaker" not in dubs.load_dub(dub)["tracks"][0]["clips"][1]


def test_transcribing_again_clears_speakers(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    dubs.set_found_speakers(dub, {"o1": 0, "o2": 1})
    dubs.set_transcript(dub, "tr", SEGMENTS)
    assert _speakers(dub) == ([], [None, None])


def test_rename_refuses_an_empty_name(tmp_workspace, tmp_path):
    dub = _dub_with_audio(tmp_path, seconds=12)
    dubs.set_found_speakers(dub, {"o1": 0, "o2": 1})
    with pytest.raises(dubs.ws.WorkspaceError, match="needs a name"):
        dubs.rename_speaker(dub, "s1", "  ")


def _talk(tmp_path, seconds, sentences):
    """A dub of `seconds` whose sentences are (start, end, speaker label or None), texts T1, T2, ..."""
    dub = dubs.create_dub("Talk", b"x", "mp3")
    dubs.set_source_audio(dub, make_wav(tmp_path / "talk.wav", seconds).read_bytes())
    dubs.set_transcript(dub, "tr", [{"start": a, "end": b, "text": f"T{n}"} for n, (a, b, _) in enumerate(sentences, 1)])
    dubs.set_found_speakers(dub, {f"o{n}": label for n, (_, _, label) in enumerate(sentences, 1)})
    return dub


def _reference(dub, clip_id):
    path, text = dubs.cut_reference(dub, clip_id)
    rate, samples = dubs._read(path)
    return round(len(samples) / rate, 2), text


def _joined(*seconds):
    """How long a reference joined from sentences of these lengths is: each padded, with a gap between them."""
    return round(sum(seconds) + len(seconds) * 2 * dubs.REFERENCE_PADDING + (len(seconds) - 1) * dubs.REFERENCE_GAP, 2)


def test_reference_adds_the_nearest_same_speaker_sentences(tmp_workspace, tmp_path):
    dub = _talk(tmp_path, 70, [(16.0, 19.0, 0), (20.0, 22.0, 0), (22.5, 24.0, 1), (32.0, 35.0, 0), (62.0, 65.0, 0)])
    seconds, text = _reference(dub, "d2")
    assert text == "T1 T2 T4"  # 1 s before, itself, 10 s after; the other speaker's and the far one are not used
    assert abs(seconds - _joined(3, 2, 3)) < 0.01


def test_reference_never_passes_ten_seconds(tmp_workspace, tmp_path):
    dub = _talk(tmp_path, 70, [(14.0, 19.0, 0), (20.0, 22.0, 0), (27.0, 31.0, 0), (42.0, 43.0, 0)])
    seconds, text = _reference(dub, "d2")
    assert text == "T1 T2 T4" and seconds <= dubs.REFERENCE_MAX  # the 4 s one would pass 10 s: skipped


def test_reference_stays_within_the_window(tmp_workspace, tmp_path):
    dub = _talk(tmp_path, 100, [(20.0, 22.0, 0), (92.0, 95.0, 0)])
    assert _reference(dub, "d1") == (_joined(2), "T1")


def test_reference_skips_kept_and_very_short_sentences(tmp_workspace, tmp_path):
    dub = _talk(tmp_path, 70, [(16.0, 19.0, 0), (20.0, 22.0, 0), (23.0, 23.4, 0)])
    dubs.set_keep_original(dub, "o1", True)
    assert _reference(dub, "d2")[1] == "T2"


def test_a_long_or_unknown_base_is_used_alone(tmp_workspace, tmp_path):
    dub = _talk(tmp_path, 70, [(10.0, 18.5, 0), (19.0, 22.0, 0), (30.0, 32.0, None), (33.0, 36.0, 0)])
    assert _reference(dub, "d1")[1] == "T1"
    assert _reference(dub, "d3")[1] == "T3"


def test_reference_comes_from_the_voice_from_sentence(tmp_workspace, tmp_path):
    dub = _talk(tmp_path, 70, [(16.0, 19.0, 1), (20.0, 22.0, 0), (23.0, 25.0, 1), (26.0, 27.0, 0)])
    dubs.update_dub_clip(dub, "d2", voice_from="o3")
    assert _reference(dub, "d2")[1] == "T1 T3"


def test_reference_reads_the_voices_stem(tmp_workspace, tmp_path):
    import numpy as np
    dub = _talk(tmp_path, 70, [(16.0, 19.0, 0), (20.0, 22.0, 0)])
    rate, audio = dubs._read(dubs.audio_path(dub))
    dubs._write(dubs.voices_path(dub), rate, audio)
    dubs._write(dubs.background_path(dub), rate, np.zeros(len(audio)))
    dubs._write(dubs.audio_path(dub), rate, np.zeros(len(audio)))  # only the voices have sound
    path, _ = dubs.cut_reference(dub, "d2")
    assert abs(dubs._read(path)[1].astype(int)).max() > 0


def test_found_speakers_go_by_sentence_not_by_place(tmp_workspace, tmp_path):
    """Sentences deleted or reordered while the speakers were being found keep the right speaker."""
    dub = _dub_with_audio(tmp_path, seconds=12)
    added = dubs.add_source_clip(dub, 10.0, 11.0)  # not in the search: stays unknown
    dubs.set_found_speakers(dub, {"o2": 0, "gone": 1, "o1": 1})
    assert _speakers(dub)[1] == ["s2", "s1", None] and added == "o3"


def test_touching_sentences_are_read_once(tmp_workspace, tmp_path):
    """Two sentences that touch are one stretch of speech: read once, no repeated padding, no gap between them."""
    dub = _talk(tmp_path, 70, [(20.0, 23.0, 0), (23.0, 26.0, 0)])
    seconds, text = _reference(dub, "d1")
    assert text == "T1 T2" and abs(seconds - (6 + 2 * dubs.REFERENCE_PADDING)) < 0.01


def test_reference_skips_sentences_without_text(tmp_workspace, tmp_path):
    dub = _talk(tmp_path, 70, [(16.0, 19.0, 0), (20.0, 22.0, 0)])
    dubs.update_source_clip(dub, "o1", text="")
    assert _reference(dub, "d2") == (_joined(2), "T2")


def test_accent_voice_texts_join_sentences(tmp_workspace, tmp_path):
    dub = _talk(tmp_path, 70, [(1.0, 2.0, None), (3.0, 4.0, None), (5.0, 6.0, None)])
    for n, words in enumerate(["Hello there my friend.", "How have you been lately?", "It is nice to see you."], 1):
        dubs.update_dub_clip(dub, f"d{n}", translation=words)
    source, target = dubs.accent_voice_texts(dub, "en")
    assert source == "T1 T2 T3"  # all there is (under 60 characters)
    assert target == "Hello there my friend. How have you been lately? It is nice to see you."


def test_accent_voice_texts_need_translations(tmp_workspace, tmp_path):
    dub = _talk(tmp_path, 70, [(1.0, 2.0, None)])
    with pytest.raises(dubs.ws.WorkspaceError, match="needs translations"):
        dubs.accent_voice_texts(dub, "en")


def test_accent_voices_are_kept_until_transcribing_again(tmp_workspace, tmp_path):
    dub = _talk(tmp_path, 70, [(1.0, 2.0, None)])
    assert dubs.accent_voices(dub, "en") is None
    voices = []
    for gender in ("female", "male"):
        src, tgt = dubs.accent_voice_path(dub, "en", gender, "src"), dubs.accent_voice_path(dub, "en", gender, "tgt")
        make_wav(src, 1)
        make_wav(tgt, 1)
        voices.append({"gender": gender, "src": str(src), "src_text": "T1", "tgt": str(tgt), "tgt_text": "Hi."})
    dubs.save_accent_voices(dub, "en", voices)
    assert dubs.accent_voices(dub, "en") == voices
    Path(voices[1]["src"]).unlink()
    assert dubs.accent_voices(dub, "en") is None  # a missing file: made again
    dubs.set_transcript(dub, "tr", SEGMENTS)
    assert not (dubs.dub_dir(dub) / "accent").exists()


def test_accent_voice_texts_skip_a_sentence_too_long_to_fit(tmp_workspace, tmp_path):
    dub = _talk(tmp_path, 70, [(1.0, 2.0, None), (3.0, 4.0, None)])
    dubs.update_source_clip(dub, "o1", text="x" * 250)
    dubs.update_dub_clip(dub, "d1", translation="y" * 250)
    dubs.update_dub_clip(dub, "d2", translation="Fine.")
    assert dubs.accent_voice_texts(dub, "en") == ("T2", "Fine.")


def test_accent_voice_texts_count_cjk_as_longer(tmp_workspace, tmp_path):
    """A Japanese or Chinese character takes several times as long to say: the sample stays a few seconds long."""
    dub = _talk(tmp_path, 70, [(n, n + 0.5, None) for n in range(1, 30)])
    for n in range(1, 30):
        dubs.update_source_clip(dub, f"o{n}", text="こんにちは")  # 5 kana
        dubs.update_dub_clip(dub, f"d{n}", translation="Hello there.")
    source, _ = dubs.accent_voice_texts(dub, "en")
    assert 20 <= len(source.replace(" ", "")) <= 40  # 4-8 sentences, not 30+
