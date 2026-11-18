from pathlib import Path

import pytest

import workspace as ws
from conftest import make_wav


def _session_with_lines(texts, name="Episode 1", character="Burak"):
    sid = ws.create_session(name)
    cid = ws.create_character(character)
    ws.add_to_cast(sid, cid, "library")
    return sid, [ws.add_line(sid, cid, t) for t in texts]


def _add_take(sid, lid, model, seconds, sr=24000, **extra):
    path = ws.new_take_path(sid, lid, model)
    make_wav(path, seconds, sr)
    take = {"file": str(path), "kind": "tts", "model": model, "text": "x", **extra}
    ws.add_take(sid, lid, take)
    return path


def _line(sid, lid):
    return next(l for l in ws.load_session(sid)["lines"] if l["id"] == lid)


def test_take_names_and_selection(tmp_workspace):
    sid, (lid,) = _session_with_lines(["Hello"])
    first = _add_take(sid, lid, "chatterbox", 1)
    second = _add_take(sid, lid, "omnivoice", 1)
    assert first.name == "01-burak-chatterbox-take1.wav"
    assert second.name == "01-burak-omnivoice-take2.wav"
    line = _line(sid, lid)
    assert line["selected"] == "takes/01-burak-chatterbox-take1.wav"
    assert [t["file"] for t in line["takes"]] == ["takes/01-burak-chatterbox-take1.wav",
                                                  "takes/01-burak-omnivoice-take2.wav"]
    ws.delete_take(sid, lid, "takes/01-burak-chatterbox-take1.wav")
    assert not first.exists()
    assert _line(sid, lid)["selected"] == "takes/01-burak-omnivoice-take2.wav"


def test_take_number_is_not_reused_after_delete(tmp_workspace):
    sid, (lid,) = _session_with_lines(["Hello"])
    _add_take(sid, lid, "chatterbox", 1)
    second = _add_take(sid, lid, "chatterbox", 1)
    ws.delete_take(sid, lid, "takes/01-burak-chatterbox-take1.wav")
    third = _add_take(sid, lid, "chatterbox", 1)
    assert third.name == "01-burak-chatterbox-take3.wav"
    assert second.exists()


def test_recording_path_uses_line_number(tmp_workspace):
    sid, (_, lid) = _session_with_lines(["a", "b"])
    assert ws.new_recording_path(sid, lid) == ws.session_dir(sid) / "recordings" / "02-take1.wav"


def test_select_take(tmp_workspace):
    sid, (lid,) = _session_with_lines(["Hello"])
    _add_take(sid, lid, "chatterbox", 1)
    _add_take(sid, lid, "chatterbox", 1)
    ws.select_take(sid, lid, "takes/01-burak-chatterbox-take2.wav")
    assert _line(sid, lid)["selected"] == "takes/01-burak-chatterbox-take2.wav"


def test_export_joins_selected_takes_and_pauses(tmp_workspace):
    sid, (l1, l2) = _session_with_lines(["one", "two"])
    ws.update_line(sid, l1, pause_after=0.5)
    _add_take(sid, l1, "chatterbox", 1.0)
    _add_take(sid, l2, "chatterbox", 2.0)
    out = ws.export_session(sid)
    assert out.parent == ws.session_dir(sid) / "exports"
    assert out.name.startswith("episode-1-")
    assert ws.wav_duration(out) == pytest.approx(3.8, abs=0.01)
    import wave
    with wave.open(str(out)) as w:
        assert w.getframerate() == 24000


def test_export_refuses_lines_without_takes(tmp_workspace):
    sid, (l1, _, _) = _session_with_lines(["one", "two", "three"])
    _add_take(sid, l1, "chatterbox", 1.0)
    with pytest.raises(ws.WorkspaceError, match="Lines 2, 3 have no takes yet."):
        ws.export_session(sid)
    assert not (ws.session_dir(sid) / "exports").exists()


def test_export_reports_missing_take_file(tmp_workspace):
    sid, (l1,) = _session_with_lines(["one"])
    path = _add_take(sid, l1, "chatterbox", 1.0)
    path.unlink()
    with pytest.raises(ws.WorkspaceError, match="Line 1"):
        ws.export_session(sid)


def test_resample_doubles_length():
    import numpy as np
    out = ws._resample(np.array([0, 100, 200], "<i2"), 24000, 48000)
    assert len(out) == 6 and out.dtype == np.int16 and out[0] == 0
    assert all(b >= a for a, b in zip(out, out[1:]))


def test_export_joins_mixed_sample_rates_at_the_highest(tmp_workspace):
    import wave
    sid, (l1, l2) = _session_with_lines(["one", "two"])
    ws.update_line(sid, l1, pause_after=0.5)
    ws.update_line(sid, l2, pause_after=0.5)
    _add_take(sid, l1, "chatterbox", 1.0, sr=24000)
    _add_take(sid, l2, "voxcpm", 1.0, sr=48000)
    out = ws.export_session(sid)
    with wave.open(str(out)) as w:
        assert w.getframerate() == 48000
        assert w.getnframes() == 48000 * 3


def test_effective_settings_layers(tmp_workspace):
    sid, (lid,) = _session_with_lines(["one"])
    defaults = {"a": 1, "b": 2}
    ws.set_session_settings(sid, "m", {"a": 3})
    ws.set_line_settings(sid, lid, "m", {"b": 4})
    session = ws.load_session(sid)
    assert ws.effective_settings(session, _line(sid, lid), "m", defaults) == {"a": 3, "b": 4}
    ws.reset_line_settings(sid, lid)
    assert ws.effective_settings(ws.load_session(sid), _line(sid, lid), "m", defaults) == {"a": 3, "b": 2}
    ws.reset_session_settings(sid, "m")
    assert ws.effective_settings(ws.load_session(sid), _line(sid, lid), "m", defaults) == {"a": 1, "b": 2}


def test_session_models_are_stored(tmp_workspace):
    sid = ws.create_session("E")
    ws.set_session_models(sid, ["chatterbox", "omnivoice"])
    assert ws.load_session(sid)["models"] == ["chatterbox", "omnivoice"]


def test_custom_settings_flag(tmp_workspace):
    sid = ws.create_session("E")
    defaults = {"a": 1, "b": 2}
    ws.set_session_settings(sid, "m", {"a": 3})
    session = ws.load_session(sid)
    assert ws.take_has_custom_settings(session, {"model": "m", "settings": {"a": 3, "b": 4}}, defaults)
    assert not ws.take_has_custom_settings(session, {"model": "m", "settings": {"a": 3, "b": 2}}, defaults)
    assert not ws.take_has_custom_settings(session, {"model": "m", "kind": "convert"}, defaults)


def test_text_changed_flag(tmp_workspace):
    sid, (lid,) = _session_with_lines(["old text"])
    tts = {"kind": "tts", "text": "old text"}
    convert = {"kind": "convert"}
    ws.update_line(sid, lid, text="new text")
    line = _line(sid, lid)
    assert ws.take_text_changed(line, tts)
    assert not ws.take_text_changed(line, convert)


def _files(sid):
    return sorted(p.relative_to(ws.session_dir(sid)).as_posix()
                  for p in ws.session_dir(sid).rglob("*.wav"))


def test_reorder_renumbers_take_files(tmp_workspace):
    sid, (l1, l2) = _session_with_lines(["one", "two"])
    _add_take(sid, l1, "chatterbox", 1)
    _add_take(sid, l2, "chatterbox", 1)
    assert _files(sid) == ["takes/01-burak-chatterbox-take1.wav", "takes/02-burak-chatterbox-take1.wav"]
    first = (ws.session_dir(sid) / "takes/01-burak-chatterbox-take1.wav").read_bytes()
    assert ws.reorder_lines(sid, [l2, l1]) is True
    data = ws.load_session(sid)
    assert [l["id"] for l in data["lines"]] == [l2, l1]
    assert data["lines"][1]["takes"][0]["file"] == "takes/02-burak-chatterbox-take1.wav"
    assert data["lines"][1]["selected"] == "takes/02-burak-chatterbox-take1.wav"
    assert data["lines"][0]["selected"] == "takes/01-burak-chatterbox-take1.wav"
    assert (ws.session_dir(sid) / "takes/02-burak-chatterbox-take1.wav").read_bytes() == first  # the swap kept content
    assert _files(sid) == ["takes/01-burak-chatterbox-take1.wav", "takes/02-burak-chatterbox-take1.wav"]


def test_delete_and_insert_renumber_recordings_too(tmp_workspace):
    sid, (l1, l2, l3) = _session_with_lines(["one", "two", "three"])
    _add_take(sid, l3, "chatterbox", 1)
    recording = ws.new_recording_path(sid, l3)
    make_wav(recording, 1)
    out = ws.new_take_path(sid, l3, "chatterbox-vc")
    make_wav(out, 1)
    ws.add_take(sid, l3, {"file": str(out), "kind": "convert", "model": "chatterbox-vc", "source_recording": str(recording)})
    assert ws.delete_line(sid, l1) is True
    assert _files(sid) == ["recordings/02-take2.wav", "takes/02-burak-chatterbox-take1.wav",
                           "takes/02-burak-chatterbox-vc-take2.wav"]
    ws.add_line(sid, ws.load_session(sid)["lines"][0]["character"], "new", after=l2)
    assert _files(sid) == ["recordings/03-take2.wav", "takes/03-burak-chatterbox-take1.wav",
                           "takes/03-burak-chatterbox-vc-take2.wav"]
    take = ws.load_session(sid)["lines"][2]["takes"][1]
    assert take["source_recording"] == "recordings/03-take2.wav"


def test_locked_file_keeps_all_names(tmp_workspace, monkeypatch):
    sid, (l1, l2) = _session_with_lines(["one", "two"])
    _add_take(sid, l1, "chatterbox", 1)
    _add_take(sid, l2, "chatterbox", 1)
    before = _files(sid)
    real, calls = ws.os.replace, []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) == 3:  # fails half way, e.g. a file open in another program on Windows
            raise PermissionError("in use")
        return real(src, dst)

    monkeypatch.setattr(ws.os, "replace", flaky)
    assert ws.reorder_lines(sid, [l2, l1]) is False
    monkeypatch.setattr(ws.os, "replace", real)
    data = ws.load_session(sid)
    assert [l["id"] for l in data["lines"]] == [l2, l1]  # the new order is kept
    assert _files(sid) == before
    assert all((ws.session_dir(sid) / t["file"]).exists() for l in data["lines"] for t in l["takes"])


def test_delete_lines_removes_several_and_renumbers(tmp_workspace):
    sid, (l1, l2, l3, l4) = _session_with_lines(["one", "two", "three", "four"])
    _add_take(sid, l2, "chatterbox", 1)
    _add_take(sid, l4, "chatterbox", 1)
    assert ws.delete_lines(sid, [l1, l2]) is True
    data = ws.load_session(sid)
    assert [l["id"] for l in data["lines"]] == [l3, l4]
    assert _files(sid) == ["takes/02-burak-chatterbox-take1.wav"]


def test_update_lines_sets_fields_on_several(tmp_workspace):
    sid, (l1, l2, l3) = _session_with_lines(["one", "two", "three"])
    other = ws.create_character("Guest")
    ws.add_to_cast(sid, other, "library")
    ws.update_lines(sid, [l1, l3], character=other, sample=None)
    data = ws.load_session(sid)
    assert [l["character"] for l in data["lines"]] == [other, data["lines"][1]["character"], other]
    with pytest.raises(ValueError):
        ws.update_lines(sid, [l1], takes=[])


class _FakeSoundfile:
    """Records sf.write calls; reports which formats libsndfile can write."""
    def __init__(self, formats):
        self.formats, self.writes = formats, []

    def available_formats(self):
        return {f: f for f in self.formats}

    def available_subtypes(self, fmt):
        return {"FLAC": {"PCM_16": ""}, "MP3": {"MPEG_LAYER_III": ""}, "OGG": {"VORBIS": ""}}.get(fmt, {})

    def write(self, path, data, rate, format=None, subtype=None):
        self.writes.append((Path(path).suffix, format, subtype, rate, len(data), data.dtype.kind))
        Path(path).write_bytes(b"encoded")


def test_export_formats_follow_libsndfile(monkeypatch):
    monkeypatch.setattr(ws, "sf", _FakeSoundfile(["WAV", "FLAC", "OGG"]))
    assert ws.export_formats() == ["wav", "flac", "ogg"]
    monkeypatch.setattr(ws, "sf", _FakeSoundfile(["WAV", "FLAC", "OGG", "MP3"]))
    assert ws.export_formats() == ["wav", "flac", "mp3", "ogg"]
    monkeypatch.setattr(ws, "sf", object())  # no format list at all: WAV only
    assert ws.export_formats() == ["wav"]


def test_export_to_mp3_encodes_the_joined_audio(tmp_workspace, monkeypatch):
    fake = _FakeSoundfile(["WAV", "FLAC", "OGG", "MP3"])
    monkeypatch.setattr(ws, "sf", fake)
    sid, (l1, l2) = _session_with_lines(["one", "two"])
    _add_take(sid, l1, "chatterbox", 1.0)
    _add_take(sid, l2, "chatterbox", 0.5)
    out = ws.export_session(sid, "mp3")
    assert out.suffix == ".mp3" and out.read_bytes() == b"encoded"
    suffix, fmt, subtype, rate, frames, kind = fake.writes[0]
    assert (suffix, fmt, subtype, rate, kind) == (".mp3", "MP3", "MPEG_LAYER_III", 24000, "f")
    assert frames == round((1.0 + 0.5 + 2 * ws.DEFAULT_PAUSE) * 24000)
    assert not list(out.parent.glob("*.wav"))  # no leftover WAV


def test_export_refuses_unknown_format(tmp_workspace):
    sid, (l1,) = _session_with_lines(["one"])
    _add_take(sid, l1, "chatterbox", 1.0)
    with pytest.raises(ws.WorkspaceError, match="cannot export"):
        ws.export_session(sid, "aiff")


def test_list_exports_newest_first(tmp_workspace):
    import os
    sid, (l1,) = _session_with_lines(["one"])
    _add_take(sid, l1, "chatterbox", 1.0)
    first = ws.export_session(sid)
    second = first.with_name("episode-1-later.wav")
    second.write_bytes(first.read_bytes())
    os.utime(second, (first.stat().st_mtime + 60,) * 2)
    exports = ws.list_exports(sid)
    assert [e["name"] for e in exports] == ["episode-1-later.wav", first.name]
    assert exports[0]["path"] == f"sessions/{sid}/exports/episode-1-later.wav"
    assert exports[0]["format"] == "wav" and exports[0]["size"] > 0 and exports[0]["created"]
    ws.delete_export(sid, "episode-1-later.wav")
    assert [e["name"] for e in ws.list_exports(sid)] == [first.name]
    with pytest.raises(ws.WorkspaceError):
        ws.delete_export(sid, "../session.json")


def test_trim_take_adds_a_trimmed_copy(tmp_workspace):
    import wave
    sid, (l1,) = _session_with_lines(["one"])
    original = _add_take(sid, l1, "chatterbox", 2.0, seed=7)
    rel = ws.load_session(sid)["lines"][0]["takes"][0]["file"]
    new = ws.trim_take(sid, l1, rel, 0.5, 1.5)
    line = ws.load_session(sid)["lines"][0]
    assert len(line["takes"]) == 2 and line["selected"] == new
    take = line["takes"][1]
    assert take["trimmed_from"] == rel and take["trim"] == [0.5, 1.5] and take["seed"] == 7
    assert take["model"] == "chatterbox" and take["duration"] == 1.0
    with wave.open(str(ws.session_dir(sid) / new)) as w:
        assert w.getnframes() == 24000
    assert original.exists()  # the original take is kept
    with pytest.raises(ws.WorkspaceError):
        ws.trim_take(sid, l1, rel, 1.5, 1.6)  # shorter than 0.3 s


def test_clear_takes_keeps_the_lines(tmp_workspace):
    sid, (l1, l2, l3) = _session_with_lines(["one", "two", "three"])
    for lid in (l1, l2, l3):
        _add_take(sid, lid, "chatterbox", 1)
    _add_take(sid, l1, "chatterbox", 1)
    removed = ws.clear_takes(sid, [l1, l3])
    data = ws.load_session(sid)
    assert removed == 3
    assert [len(l["takes"]) for l in data["lines"]] == [0, 1, 0]
    assert [l["selected"] is None for l in data["lines"]] == [True, False, True]
    assert [l["text"] for l in data["lines"]] == ["one", "two", "three"]
    assert _files(sid) == ["takes/02-burak-chatterbox-take1.wav"]


def test_trim_take_can_replace_the_original(tmp_workspace):
    sid, (l1,) = _session_with_lines(["one"])
    original = _add_take(sid, l1, "chatterbox", 2.0, seed=7)
    _add_take(sid, l1, "chatterbox", 1.0)
    rel = ws.load_session(sid)["lines"][0]["takes"][0]["file"]
    data = ws.load_session(sid)
    data["lines"][0]["takes"][0]["source_recording"] = "recordings/01-take1.wav"
    ws.save_session(sid, data)
    rec = ws.session_dir(sid) / "recordings/01-take1.wav"
    make_wav(rec, 1)
    new = ws.trim_take(sid, l1, rel, 0.5, 1.5, replace=True)
    line = ws.load_session(sid)["lines"][0]
    assert [t["file"] for t in line["takes"]] == [line["takes"][0]["file"], new] and len(line["takes"]) == 2
    assert rel not in [t["file"] for t in line["takes"]] and not original.exists()
    take = next(t for t in line["takes"] if t["file"] == new)
    assert line["selected"] == new and take["trim"] == [0.5, 1.5] and "trimmed_from" not in take
    assert take["source_recording"] == "recordings/01-take1.wav" and rec.exists()  # the recording moves along


def test_export_one_line_without_its_pause(tmp_workspace):
    import wave
    sid, (l1, l2) = _session_with_lines(["one", "two"])
    ws.update_line(sid, l2, pause_after=0.5)
    _add_take(sid, l2, "chatterbox", 1.0, sr=24000)  # line 1 has no take: not needed for one line
    out = ws.export_session(sid, "wav", line_id=l2)
    assert "-line-2-" in out.name and out.parent.name == "exports"
    with wave.open(str(out)) as w:
        assert w.getframerate() == 24000 and w.getnframes() == 24000


def test_export_one_line_needs_a_take(tmp_workspace):
    sid, (l1,) = _session_with_lines(["one"])
    with pytest.raises(ws.WorkspaceError, match="no takes"):
        ws.export_session(sid, "wav", line_id=l1)
