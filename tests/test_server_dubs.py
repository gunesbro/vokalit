"""The Dub routes: import, transcribe, edit, generate (cancellable), export, and video files with byte ranges."""
import os
import threading
import time

os.environ.setdefault("VOKALIT_UV", "uv")
import dubs  # noqa: E402
import models  # noqa: E402
import workspace as ws  # noqa: E402
from conftest import make_wav  # noqa: E402
from test_server import _wait, api  # noqa: E402,F401  (the api fixture)

SEGMENTS = [{"start": 0.5, "end": 3.0, "text": "Merhaba."}, {"start": 4.0, "end": 9.0, "text": "Nas\u0131ls\u0131n?"}]


def _transcribed(api, tmp_path, monkeypatch, segments=SEGMENTS):
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "transcribe_segments", lambda audio, language: {"language": "tr", "segments": segments})
    status, dub, _ = api("POST", "/api/dubs?name=Talk&ext=mp4", raw=b"video-bytes", content_type="video/mp4")
    assert status == 200, dub
    status, dub, _ = api("POST", f"/api/dubs/{dub['id']}/audio", raw=make_wav(tmp_path / "a.wav", 12).read_bytes(),
                         content_type="audio/wav")
    assert status == 200 and round(dub["source"]["duration"]) == 12
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/transcribe", {})
    done = _wait(api, job["id"])
    assert done["state"] == "done", done
    return done["result"]


def test_import_refuses_unknown_types(api, tmp_workspace):
    for ext in ("exe", "..%2Fx", ""):
        status, body, _ = api("POST", f"/api/dubs?name=X&ext={ext}", raw=b"x", content_type="application/octet-stream")
        assert status == 400 and "cannot open" in body["error"]
    assert not (tmp_workspace / "dubs").exists() or list((tmp_workspace / "dubs").iterdir()) == []


def test_dub_import_transcribe_and_edit(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    assert [c["text"] for c in dub["tracks"][0]["clips"]] == ["Merhaba.", "Nas\u0131ls\u0131n?"]
    assert dub["fit"] == {"en": {"d1": {"state": "missing", "over": 0.0}, "d2": {"state": "missing", "over": 0.0}}}
    status, listed, _ = api("GET", "/api/dubs")
    assert status == 200 and listed[0]["id"] == dub["id"] and listed[0]["kind"] == "video" and listed[0]["clips"] == 2
    status, dub, _ = api("PATCH", f"/api/dubs/{dub['id']}/clips/d1", {"translation": "Hello.", "start": 0.75})
    assert status == 200 and dub["tracks"][1]["clips"][0]["translation"] == "Hello."
    status, body, _ = api("PATCH", f"/api/dubs/{dub['id']}/clips/d1", {"start": 30})
    assert status == 400
    status, dub, _ = api("PATCH", f"/api/dubs/{dub['id']}/source/o1", {"text": "Selam."})
    assert dub["tracks"][0]["clips"][0]["text"] == "Selam."
    status, dub, _ = api("DELETE", f"/api/dubs/{dub['id']}/source/o2")
    assert [c["id"] for c in dub["tracks"][1]["clips"]] == ["d1"]


def test_dub_options_are_checked(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    status, body, _ = api("PATCH", f"/api/dubs/{dub['id']}", {"model": "nope"})
    assert status == 400
    status, body, _ = api("PATCH", f"/api/dubs/{dub['id']}?language=xx", {"model": "higgs"})
    assert status == 400
    status, dub, _ = api("PATCH", f"/api/dubs/{dub['id']}", {"name": "Talk 2", "model": "higgs", "original_volume": 0.3})
    assert (dub["name"], dub["tracks"][1]["model"], dub["original_volume"]) == ("Talk 2", "higgs", 0.3)


def test_dub_languages_routes(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    calls = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        calls.append((name, text, language))
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "generate", fake_generate)
    status, dub, _ = api("POST", f"/api/dubs/{dub['id']}/languages", {"language": "de"})
    assert status == 200 and dub["languages"] == ["en", "de"] and set(dub["fit"]) == {"en", "de"}
    assert api("POST", f"/api/dubs/{dub['id']}/languages", {"language": "xx"})[0] == 400
    api("PATCH", f"/api/dubs/{dub['id']}?language=de", {"model": "higgs"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d1?language=de", {"translation": "Hallo."})
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate?language=de", {"clips": ["d1"]})
    done = _wait(api, job["id"])
    assert done["state"] == "done" and calls == [("higgs", "Hallo.", "de")]
    assert done["result"]["tracks"][2]["clips"][0]["selected"] == "takes/de/d1-1.wav"
    assert done["result"]["tracks"][1]["clips"][0]["selected"] is None
    status, body, _ = api("POST", f"/api/dubs/{dub['id']}/export?language=de", {"format": "wav"})
    assert "-de-" in body["path"]
    status, dub, _ = api("DELETE", f"/api/dubs/{dub['id']}/languages/en")
    assert dub["languages"] == ["de"]


def test_transcribe_without_speech_notices(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch, segments=[])
    assert dub["notice"] == "No speech was found in this file." and dub["tracks"][1]["clips"] == []


def test_transcribe_needs_whisper(api, tmp_path, monkeypatch):
    monkeypatch.setattr(models, "is_installed", lambda name: name != "whisper")
    _, dub, _ = api("POST", "/api/dubs?name=Talk&ext=wav", raw=make_wav(tmp_path / "s.wav", 2).read_bytes(),
                    content_type="audio/wav")
    api("POST", f"/api/dubs/{dub['id']}/audio", raw=make_wav(tmp_path / "a.wav", 2).read_bytes(),
        content_type="audio/wav")
    status, body, _ = api("POST", f"/api/dubs/{dub['id']}/transcribe", {})
    assert status == 400 and "Whisper is not installed" in body["error"]


def test_dub_generate_uses_its_own_sentence_as_reference(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    calls = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        calls.append({"name": name, "text": text, "ref": ref, "language": language, "ref_text": ref_text})
        make_wav(out, 1.5)
        return 0.5

    monkeypatch.setattr(models, "generate", fake_generate)
    api("PATCH", f"/api/dubs/{dub['id']}", {"model": "omnivoice"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d2", {"translation": "How are you?"})
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d2"], "seed": 7})
    done = _wait(api, job["id"])
    assert done["state"] == "done", done
    assert calls == [{"name": "omnivoice", "text": "How are you?", "ref": calls[0]["ref"], "language": "en",
                      "ref_text": "Nas\u0131ls\u0131n?"}]
    assert calls[0]["ref"].endswith("o2.wav")
    clip = done["result"]["tracks"][1]["clips"][1]
    assert clip["selected"] == "takes/en/d2-1.wav" and clip["takes"][0]["seed"] == 7
    assert done["result"]["fit"]["en"]["d2"] == {"state": "fits", "over": 0.0}


def test_dub_generate_refuses_empty_translation(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    api("PATCH", f"/api/dubs/{dub['id']}", {"model": "omnivoice"})
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d1"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed" and "Sentence 1 has no translation yet." in done["error"]


def test_dub_generate_needs_a_model(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    status, body, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d1"]})
    assert status == 400 and "Choose a model" in body["error"]


def test_dub_generate_can_be_cancelled(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    release, cancelled = threading.Event(), []

    def slow_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        release.wait(5)
        raise RuntimeError("The model process stopped unexpectedly.")

    monkeypatch.setattr(models, "generate", slow_generate)
    monkeypatch.setattr(models, "cancel", lambda name, owner: cancelled.append(name) or release.set() or True)
    api("PATCH", f"/api/dubs/{dub['id']}", {"model": "omnivoice"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d1", {"translation": "Hello."})
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d1"]})
    for _ in range(100):
        if server_job(job["id"]).get("model"):
            break
        time.sleep(0.02)
    api("POST", f"/api/jobs/{job['id']}/cancel", {})
    assert _wait(api, job["id"])["state"] == "cancelled" and cancelled == ["omnivoice"]
    assert dubs.load_dub(dub["id"])["tracks"][1]["clips"][0]["takes"] == []


def server_job(job_id):
    import server
    return server._jobs[job_id]


def test_dub_export(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    status, body, _ = api("POST", f"/api/dubs/{dub['id']}/export", {"format": "wav"})
    assert status == 200 and body["path"].startswith(f"dubs/{dub['id']}/exports/") and body["path"].endswith(".wav")
    assert api("GET", f"/api/dubs/{dub['id']}")[1]["exports"][0]["path"] == body["path"]


def test_files_serve_video_ranges(api, tmp_workspace):
    dub = dubs.create_dub("V", bytes(range(256)) * 4096, "mp4")
    assert api("GET", f"/files/dubs/{dub}/source.mp4")[0] == 200
    status, body, headers = api("GET", f"/files/dubs/{dub}/source.mp4", extra_headers={"Range": "bytes=10-19"})
    assert status == 206 and headers["Content-Type"] == "video/mp4"
    assert headers["Content-Range"] == "bytes 10-19/1048576" and headers["Content-Length"] == "10"


def test_deleting_a_dub(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    assert api("DELETE", f"/api/dubs/{dub['id']}")[0] == 200
    assert api("GET", f"/api/dubs/{dub['id']}")[0] == 404


def test_files_send_open_ended_ranges_a_part_at_a_time(api, tmp_workspace):
    import server
    dub = dubs.create_dub("V", b"\0" * (server.RANGE_CHUNK + 10), "mp4")
    status, _, headers = api("GET", f"/files/dubs/{dub}/source.mp4", extra_headers={"Range": "bytes=0-"})
    assert status == 206 and headers["Content-Range"] == f"bytes 0-{server.RANGE_CHUNK - 1}/{server.RANGE_CHUNK + 10}"


def test_cancelling_a_transcription_stops_whisper(api, tmp_path, monkeypatch):
    release, cancelled = threading.Event(), []

    def slow_segments(audio, language):
        release.wait(5)
        raise RuntimeError("The model process stopped unexpectedly.")

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "transcribe_segments", slow_segments)
    monkeypatch.setattr(models, "cancel", lambda name, owner: cancelled.append(name) or release.set() or True)
    _, dub, _ = api("POST", "/api/dubs?name=T&ext=wav", raw=b"x", content_type="audio/wav")
    api("POST", f"/api/dubs/{dub['id']}/audio", raw=make_wav(tmp_path / "a.wav", 2).read_bytes(), content_type="audio/wav")
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/transcribe", {})
    for _ in range(100):
        if server_job(job["id"]).get("model"):
            break
        time.sleep(0.02)
    api("POST", f"/api/jobs/{job['id']}/cancel", {})
    assert _wait(api, job["id"])["state"] == "cancelled" and cancelled == ["whisper"]


def test_one_job_at_a_time_per_dub(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    release = threading.Event()

    def slow_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        release.wait(5)
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "generate", slow_generate)
    api("PATCH", f"/api/dubs/{dub['id']}", {"model": "omnivoice"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d1", {"translation": "Hello."})
    _, first, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d1"]})
    status, body, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d1"]})
    assert status == 400 and "already working" in body["error"]
    status, body, _ = api("POST", f"/api/dubs/{dub['id']}/transcribe", {})
    assert status == 400 and "already working" in body["error"]
    status, running, _ = api("GET", f"/api/dubs/{dub['id']}/jobs")
    assert status == 200 and [j["id"] for j in running] == [first["id"]] and running[0]["kind"] == "generate"
    assert running[0]["clips"] == ["d1"]
    release.set()
    assert _wait(api, first["id"])["state"] == "done"
    assert api("GET", f"/api/dubs/{dub['id']}/jobs")[1] == []


def test_paste_all_translations(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    status, dub, _ = api("PATCH", f"/api/dubs/{dub['id']}/translations",
                         {"translations": {"d1": "Hello.", "d2": "How are you?"}})
    assert status == 200 and [c["translation"] for c in dub["tracks"][1]["clips"]] == ["Hello.", "How are you?"]


def test_restore_route(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    source, clip = dub["tracks"][0]["clips"][1], dub["tracks"][1]["clips"][1]
    api("DELETE", f"/api/dubs/{dub['id']}/source/o2")
    status, dub, _ = api("POST", f"/api/dubs/{dub['id']}/source/restore",
                         {"source": source, "clips": {"en": clip}, "index": 1})
    assert status == 200 and [c["id"] for c in dub["tracks"][1]["clips"]] == ["d1", "d2"]


def test_a_generating_language_cannot_be_removed(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    release = threading.Event()

    def slow_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        release.wait(5)
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "generate", slow_generate)
    api("POST", f"/api/dubs/{dub['id']}/languages", {"language": "de"})
    api("PATCH", f"/api/dubs/{dub['id']}?language=de", {"model": "omnivoice"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d1?language=de", {"translation": "Hallo."})
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate?language=de", {"clips": ["d1"]})
    status, body, _ = api("DELETE", f"/api/dubs/{dub['id']}/languages/de")
    assert status == 400 and "generating" in body["error"]
    release.set()
    assert _wait(api, job["id"])["state"] == "done"


def test_kept_sentences_are_not_generated(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    monkeypatch.setattr(models, "generate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("generated")))
    api("PATCH", f"/api/dubs/{dub['id']}", {"model": "omnivoice"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d1", {"translation": "Hello."})
    status, dub, _ = api("PATCH", f"/api/dubs/{dub['id']}/source/o1", {"keep_original": True})
    assert status == 200 and dub["fit"]["en"]["d1"]["state"] == "kept"
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d1"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed" and "Sentence 1 keeps the original" in done["error"]


def _take(dub_id, clip_id, seconds):
    take = dubs.new_take_path(dub_id, clip_id)
    make_wav(take, seconds)
    dubs.add_take(dub_id, clip_id, {"file": str(take), "seed": 1, "duration": float(seconds)})


def test_fit_route_runs_a_job(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    _take(dub["id"], "d1", 4.0)  # 3.45 s of room: 1.16x
    _take(dub["id"], "d2", 10.0)  # 7.95 s to the end of the file: would need 1.26x
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/fit?language=en", {"clips": ["d1", "d2"]})
    assert server_job(job["id"])["kind"] == "fit"
    done = _wait(api, job["id"])
    assert done["state"] == "done", done
    assert done["result"]["notice"] == "Fitted 1 sentence. 1 needs a shorter translation."
    assert done["result"]["fit"]["en"]["d1"]["speed"] == 1.16 and done["result"]["fit"]["en"]["d2"]["state"] == "long"


def test_fitting_one_sentence_says_why_not(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    _take(dub["id"], "d2", 10.0)
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/fit", {"clips": ["d2"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed" and "1.26\u00d7 faster" in done["error"]


def test_select_route_changes_several_takes(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    _take(dub["id"], "d1", 1.0)
    status, body, _ = api("POST", f"/api/dubs/{dub['id']}/select?language=en", {"selections": {"d1": None}})
    assert status == 200 and body["tracks"][1]["clips"][0]["selected"] is None
