import pytest

import workspace as ws
from conftest import make_wav


def test_slugify_folds_to_ascii():
    assert ws.slugify("K\u0131z\u0131l \u015eahin!") == "kizil-sahin"
    assert ws.slugify("  ") == "x"


def test_create_and_list_characters(tmp_workspace):
    first = ws.create_character("Burak")
    second = ws.create_character("Narrator")
    assert first != second
    listed = ws.list_characters()
    assert [cid for cid, _ in listed] == [second, first]
    assert listed[0][1]["name"] == "Narrator"


def test_add_sample_converts_and_sets_default(tmp_workspace, tmp_path):
    cid = ws.create_character("Burak")
    sid = ws.add_sample(cid, str(make_wav(tmp_path / "in.wav", 12)), "recording")
    data = ws.load_character(cid)
    assert sid == "s1"
    assert data["samples"][0]["label"] == "sample 1"
    assert data["default_sample"] == "s1"
    path = ws.sample_path(cid, None)
    assert path.exists()
    assert ws.wav_duration(path) == pytest.approx(12.0, abs=0.01)


def test_add_short_sample_is_rejected(tmp_workspace, tmp_path):
    cid = ws.create_character("Burak")
    with pytest.raises(ws.WorkspaceError, match="7.4 seconds"):
        ws.add_sample(cid, str(make_wav(tmp_path / "short.wav", 7.4)), "recording")
    assert ws.load_character(cid)["samples"] == []
    assert not list((ws.character_dir(cid) / "samples").glob("*.wav"))


def test_delete_default_sample_moves_default(tmp_workspace, tmp_path):
    cid = ws.create_character("Burak")
    ws.add_sample(cid, str(make_wav(tmp_path / "a.wav", 11)), "recording")
    ws.add_sample(cid, str(make_wav(tmp_path / "b.wav", 11)), "upload")
    ws.delete_sample(cid, "s1")
    assert ws.load_character(cid)["default_sample"] == "s2"
    ws.delete_sample(cid, "s2")
    assert ws.load_character(cid)["default_sample"] is None
    assert ws.sample_path(cid, None) is None


def test_unknown_sample_falls_back_to_default(tmp_workspace, tmp_path):
    cid = ws.create_character("Burak")
    ws.add_sample(cid, str(make_wav(tmp_path / "a.wav", 11)), "recording")
    ws.add_sample(cid, str(make_wav(tmp_path / "b.wav", 11)), "upload")
    ws.delete_sample(cid, "s2")
    assert ws.sample_path(cid, "s2") == ws.sample_path(cid, "s1")


def test_session_only_character_lives_in_session(tmp_workspace):
    cid = ws.create_character("Guest", session_id="S")
    assert ws.character_dir(cid, "S") == tmp_workspace / "sessions" / "S" / "characters" / cid
    assert (ws.character_dir(cid, "S") / "character.json").exists()
    assert ws.list_characters() == []


def test_sample_keeps_its_transcript(tmp_workspace, tmp_path):
    cid = ws.create_character("Burak")
    sid = ws.add_sample(cid, str(make_wav(tmp_path / "a.wav", 11)), "recording", transcript="Merhaba, d\u00fcnya.")
    assert ws.load_character(cid)["samples"][0]["transcript"] == "Merhaba, d\u00fcnya."
    ws.set_sample_transcript(cid, sid, "  Merhaba d\u00fcnya  ")
    assert ws.load_character(cid)["samples"][0]["transcript"] == "Merhaba d\u00fcnya"


def test_empty_transcript_is_refused(tmp_workspace, tmp_path):
    cid = ws.create_character("Burak")
    sid = ws.add_sample(cid, str(make_wav(tmp_path / "a.wav", 11)), "recording", transcript="Hi")
    with pytest.raises(ws.WorkspaceError, match="A transcript cannot be empty"):
        ws.set_sample_transcript(cid, sid, "   ")


def test_samples_without_transcript_lists_library_and_session_characters(tmp_workspace, tmp_path):
    library = ws.create_character("Burak")
    ws.add_sample(library, str(make_wav(tmp_path / "a.wav", 11)), "recording")
    ws.add_sample(library, str(make_wav(tmp_path / "b.wav", 11)), "recording", transcript="Done")
    session = ws.create_session("Episode")
    guest = ws.create_character("Guest", session_id=session)
    ws.add_sample(guest, str(make_wav(tmp_path / "c.wav", 11)), "upload", session_id=session)
    assert sorted(ws.samples_without_transcript(), key=str) == sorted(
        [(library, None, "s1"), (guest, session, "s1")], key=str)
