import json

import pytest

import workspace as ws
from conftest import make_wav


def _line_texts(session_id):
    return [line["text"] for line in ws.load_session(session_id)["lines"]]


def test_session_roundtrip(tmp_workspace):
    sid = ws.create_session("Episode 1")
    burak = ws.create_character("Burak")
    guest = ws.create_character("Guest", session_id=sid)
    ws.add_to_cast(sid, burak, "library")
    ws.add_to_cast(sid, guest, "session")
    ws.add_line(sid, burak, "one")
    ws.add_line(sid, guest, "two")
    ws.add_line(sid, burak, "three")
    data = ws.load_session(sid)
    assert data["name"] == "Episode 1"
    assert data["cast"] == [{"character": burak, "scope": "library"}, {"character": guest, "scope": "session"}]
    assert [(l["character"], l["text"], l["pause_after"]) for l in data["lines"]] == [
        (burak, "one", ws.DEFAULT_PAUSE), (guest, "two", ws.DEFAULT_PAUSE), (burak, "three", ws.DEFAULT_PAUSE)]
    assert ws.cast_character(data, guest)["name"] == "Guest"
    assert [s for s, _ in ws.list_sessions()] == [sid]


def test_default_session_name(tmp_workspace):
    sid = ws.create_session()
    assert ws.load_session(sid)["name"].startswith("Session 20")


def test_failed_save_keeps_previous_file(tmp_workspace):
    sid = ws.create_session("Safe")
    data = ws.load_session(sid)
    data["name"] = object()
    with pytest.raises(TypeError):
        ws.save_session(sid, data)
    assert ws.load_session(sid)["name"] == "Safe"
    assert not list((tmp_workspace / "sessions" / sid).glob("*.tmp"))


def test_remove_used_character_is_refused(tmp_workspace):
    sid = ws.create_session("E")
    burak = ws.create_character("Burak")
    other = ws.create_character("Other")
    ws.add_to_cast(sid, burak, "library")
    ws.add_to_cast(sid, other, "library")
    ws.add_line(sid, burak, "a")
    ws.add_line(sid, other, "b")
    ws.add_line(sid, burak, "c")
    with pytest.raises(ws.WorkspaceError, match="Burak is used by lines 1, 3"):
        ws.remove_from_cast(sid, burak)
    ws.delete_line(sid, ws.load_session(sid)["lines"][1]["id"])
    ws.remove_from_cast(sid, other)
    assert [c["character"] for c in ws.load_session(sid)["cast"]] == [burak]


def test_save_as_character_moves_folder(tmp_workspace, tmp_path):
    first = ws.create_session("First")
    guest = ws.create_character("Guest", session_id=first)
    ws.add_sample(guest, str(make_wav(tmp_path / "g.wav", 11)), "recording", session_id=first)
    ws.add_to_cast(first, guest, "session")
    ws.add_line(first, guest, "hi")
    ws.save_as_character(first, guest)
    data = ws.load_session(first)
    new_id = data["cast"][0]["character"]
    assert data["cast"][0]["scope"] == "library"
    assert data["lines"][0]["character"] == new_id
    assert (tmp_workspace / "characters" / new_id / "character.json").exists()
    assert ws.sample_path(new_id, None).exists()
    assert not (tmp_workspace / "sessions" / first / "characters" / guest).exists()
    second = ws.create_session("Second")
    ws.add_to_cast(second, new_id, "library")
    assert ws.cast_character(ws.load_session(second), new_id)["name"] == "Guest"
    assert ws.sessions_using(new_id) == ["Second", "First"]


def test_move_and_delete_line(tmp_workspace):
    sid = ws.create_session("E")
    cid = ws.create_character("A")
    ws.add_to_cast(sid, cid, "library")
    l1 = ws.add_line(sid, cid, "one")
    ws.add_line(sid, cid, "two")
    ws.move_line(sid, l1, 1)
    assert _line_texts(sid) == ["two", "one"]
    ws.move_line(sid, l1, 5)
    assert _line_texts(sid) == ["two", "one"]
    take = tmp_workspace / "sessions" / sid / "takes" / "02-a-chatterbox-take1.wav"
    make_wav(take, 1)
    data = ws.load_session(sid)
    data["lines"][1]["takes"] = [{"file": "takes/02-a-chatterbox-take1.wav"}]
    ws.save_session(sid, data)
    ws.delete_line(sid, l1)
    assert _line_texts(sid) == ["two"]
    assert not take.exists()


def test_insert_line_after(tmp_workspace):
    sid = ws.create_session("E")
    cid = ws.create_character("A")
    ws.add_to_cast(sid, cid, "library")
    l1 = ws.add_line(sid, cid, "one")
    l2 = ws.add_line(sid, cid, "two")
    l3 = ws.add_line(sid, cid, "between", after=l1)
    assert [l["id"] for l in ws.load_session(sid)["lines"]] == [l1, l3, l2]
    assert len({l1, l2, l3}) == 3


def test_reorder_lines_requires_permutation(tmp_workspace):
    sid = ws.create_session("E")
    cid = ws.create_character("A")
    ws.add_to_cast(sid, cid, "library")
    ids = [ws.add_line(sid, cid, t) for t in ("a", "b", "c")]
    with pytest.raises(ws.WorkspaceError):
        ws.reorder_lines(sid, ids[:2])
    with pytest.raises(ws.WorkspaceError):
        ws.reorder_lines(sid, ids + ["l99"])
    ws.reorder_lines(sid, [ids[2], ids[0], ids[1]])
    assert _line_texts(sid) == ["c", "a", "b"]


def test_paste_script_edge_cases(tmp_workspace):
    sid = ws.create_session("E")
    host = ws.create_character("Host")
    ws.add_to_cast(sid, host, "library")
    added, split = ws.paste_script(sid, "host: Hello\n\nGuest: It's 10:30\nand still going\nHost: Bye")
    data = ws.load_session(sid)
    assert (added, split) == (3, 0)
    assert [l["text"] for l in data["lines"]] == ["Hello", "It's 10:30 and still going", "Bye"]
    assert data["lines"][0]["character"] == host
    guest_entry = data["cast"][1]
    assert guest_entry["scope"] == "session"
    guest = ws.cast_character(data, guest_entry["character"])
    assert guest["name"] == "Guest" and guest["samples"] == []


def test_paste_script_without_speaker_is_refused(tmp_workspace):
    sid = ws.create_session("E")
    with pytest.raises(ws.WorkspaceError, match="speaker"):
        ws.paste_script(sid, "Just some text without a speaker")
    assert ws.load_session(sid)["lines"] == []


def test_deleted_character_keeps_sessions_loadable(tmp_workspace):
    sid = ws.create_session("E")
    cid = ws.create_character("Gone")
    ws.add_to_cast(sid, cid, "library")
    lid = ws.add_line(sid, cid, "still here")
    data = ws.load_session(sid)
    data["lines"][0]["takes"] = [{"file": "takes/x.wav", "character_name": "Gone"}]
    ws.save_session(sid, data)
    ws.delete_character(cid)
    data = ws.load_session(sid)
    assert ws.cast_character(data, cid) is None
    assert data["lines"][0]["id"] == lid
    assert data["lines"][0]["takes"] == [{"file": "takes/x.wav", "character_name": "Gone"}]


def test_session_file_is_readable_json(tmp_workspace):
    sid = ws.create_session("E")
    raw = json.loads((tmp_workspace / "sessions" / sid / "session.json").read_text(encoding="utf-8"))
    assert raw["name"] == "E" and raw["lines"] == [] and raw["cast"] == []


def test_session_language_defaults(tmp_workspace):
    first = ws.create_session("A")
    assert ws.load_session(first)["language"] == "en"
    ws.set_session_language(first, "tr")
    second = ws.create_session("B")
    assert ws.load_session(second)["language"] == "tr"  # follows the newest session


def test_old_session_without_language_reads_as_turkish(tmp_workspace):
    sid = ws.create_session("Old")
    data = ws.load_session(sid)
    del data["language"]
    ws.save_session(sid, data)
    assert ws.load_session(sid)["language"] == "tr"


def test_line_language_overrides_session(tmp_workspace):
    sid = ws.create_session("A")
    burak = ws.create_character("Burak")
    ws.add_to_cast(sid, burak, "library")
    lid = ws.add_line(sid, burak, "Hello")
    data = ws.load_session(sid)
    assert ws.effective_language(data, data["lines"][0]) == "en"
    ws.update_line(sid, lid, language="de")
    data = ws.load_session(sid)
    assert ws.effective_language(data, data["lines"][0]) == "de"
    ws.update_line(sid, lid, language=None)
    data = ws.load_session(sid)
    assert ws.effective_language(data, data["lines"][0]) == "en"


def test_sample_language_tag(tmp_workspace, tmp_path):
    cid = ws.create_character("Burak")
    sample = ws.add_sample(cid, str(make_wav(tmp_path / "a.wav", 11)), "upload")
    assert ws.load_character(cid)["samples"][0].get("language") is None
    ws.set_sample_language(cid, sample, "tr")
    assert ws.load_character(cid)["samples"][0]["language"] == "tr"
    ws.set_sample_language(cid, sample, None)
    assert ws.load_character(cid)["samples"][0]["language"] is None


def test_split_sentences_matches_the_ui():
    assert ws.split_sentences("One. Two! Three?", 9) == ["One. Two!", "Three?"]
    assert ws.split_sentences("A sentence... Next one; still going. Last", 20) == [
        "A sentence...", "Next one;", "still going. Last"]
    long = " ".join(["word"] * 100)
    parts = ws.split_sentences(long, 120)
    assert all(len(p) <= 120 for p in parts) and " ".join(parts) == long
    assert ws.split_sentences("   ", 10) == []


def test_paste_splits_long_speeches(tmp_workspace):
    sid = ws.create_session("E")
    speech = " ".join(f"Sentence number {n} is here." for n in range(1, 31))  # ~830 characters
    added, split = ws.paste_script(sid, f"Host: Hi.\nGuest: {speech}", split_over=300, chunk=250)
    lines = ws.load_session(sid)["lines"]
    assert added == len(lines) and split == 1
    assert lines[0]["text"] == "Hi."
    guest = [l["text"] for l in lines[1:]]
    assert len(guest) > 1 and all(len(t) <= 250 for t in guest) and " ".join(guest) == speech
    assert len({l["character"] for l in lines[1:]}) == 1


def test_paste_can_keep_long_speeches(tmp_workspace):
    sid = ws.create_session("E")
    speech = "word " * 200
    added, split = ws.paste_script(sid, f"Guest: {speech}", split_over=None)
    assert (added, split) == (1, 0)


def _character_with_two_samples(tmp_path):
    cid = ws.create_character("Burak")
    ws.add_sample(cid, str(make_wav(tmp_path / "a.wav", 11)), "recording", transcript="A")
    ws.add_sample(cid, str(make_wav(tmp_path / "b.wav", 11)), "recording", transcript="B")
    return cid  # default sample: s1


def test_new_line_keeps_the_sample_that_was_default_when_it_was_added(tmp_workspace, tmp_path):
    cid = _character_with_two_samples(tmp_path)
    sid = ws.create_session("Episode")
    ws.add_to_cast(sid, cid, "library")
    lid = ws.add_line(sid, cid, "Hello")
    ws.set_default_sample(cid, "s2")
    assert ws.load_session(sid)["lines"][0]["sample"] == "s1"
    assert ws.load_session(sid)["lines"][0]["id"] == lid
    ws.add_line(sid, cid, "Later")
    assert ws.load_session(sid)["lines"][1]["sample"] == "s2"


def test_changing_a_lines_character_takes_that_characters_default(tmp_workspace, tmp_path):
    first = _character_with_two_samples(tmp_path)
    second = _character_with_two_samples(tmp_path)
    ws.set_default_sample(second, "s2")
    sid = ws.create_session("Episode")
    ws.add_to_cast(sid, first, "library")
    ws.add_to_cast(sid, second, "library")
    lid = ws.add_line(sid, first, "Hello")
    ws.update_line(sid, lid, character=second, sample=None)
    assert ws.load_session(sid)["lines"][0]["sample"] == "s2"
    ws.update_lines(sid, [lid], character=first, sample=None)
    assert ws.load_session(sid)["lines"][0]["sample"] == "s1"


def test_lines_from_before_get_the_current_default_once(tmp_workspace, tmp_path):
    cid = _character_with_two_samples(tmp_path)
    sid = ws.create_session("Episode")
    ws.add_to_cast(sid, cid, "library")
    lid = ws.add_line(sid, cid, "Hello")
    data = ws.load_session(sid)
    data["lines"][0]["sample"] = None  # how lines were saved before
    ws.save_session(sid, data)
    assert ws.load_session(sid)["lines"][0]["sample"] == "s1"
    ws.set_default_sample(cid, "s2")
    assert ws.load_session(sid)["lines"][0]["sample"] == "s1"


def test_line_of_a_character_without_samples_follows_its_first_sample(tmp_workspace, tmp_path):
    cid = ws.create_character("Guest")
    sid = ws.create_session("Episode")
    ws.add_to_cast(sid, cid, "library")
    ws.add_line(sid, cid, "Hello")
    assert ws.load_session(sid)["lines"][0]["sample"] is None  # default voice
    ws.add_sample(cid, str(make_wav(tmp_path / "a.wav", 11)), "recording", transcript="A")
    assert ws.load_session(sid)["lines"][0]["sample"] == "s1"


def test_clearing_one_models_line_settings_keeps_the_others(tmp_workspace):
    cid = ws.create_character("Burak")
    sid = ws.create_session("Episode")
    ws.add_to_cast(sid, cid, "library")
    lid = ws.add_line(sid, cid, "Hello")
    ws.set_line_settings(sid, lid, "chatterbox", {"exaggeration": 0.9})
    ws.set_line_settings(sid, lid, "omnivoice", {"speed": 1.2})
    ws.set_line_settings(sid, lid, "omnivoice", {})
    assert ws.load_session(sid)["lines"][0]["settings"] == {"chatterbox": {"exaggeration": 0.9}}
