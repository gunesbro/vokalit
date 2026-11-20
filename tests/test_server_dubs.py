"""The Dub routes: import, transcribe, edit, generate (cancellable), export, and video files with byte ranges."""
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("VOKALIT_UV", "uv")
import dubs  # noqa: E402
import models  # noqa: E402
import workspace as ws  # noqa: E402
from conftest import make_wav  # noqa: E402
from test_server import _wait, api  # noqa: E402,F401  (the api fixture)

SEGMENTS = [{"start": 0.5, "end": 3.0, "text": "Merhaba."}, {"start": 4.0, "end": 9.0, "text": "Nas\u0131ls\u0131n?"}]


HEARD = []  # what the fake Whisper listened to


def _transcribed(api, tmp_path, monkeypatch, segments=SEGMENTS, separate=None):
    """A dub with sound and sentences. Voice separation is not installed unless `separate` (a fake) is given."""
    HEARD.clear()
    monkeypatch.setattr(models, "is_installed", lambda name: separate is not None or name != "demucs")
    if separate is not None:
        monkeypatch.setattr(models, "separate", separate)
    monkeypatch.setattr(models, "transcribe_segments",
                        lambda audio, language: HEARD.append(audio) or {"language": "tr", "segments": segments})
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

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None, timing=None):
        calls.append({"name": name, "text": text, "ref": ref, "language": language, "ref_text": ref_text})
        make_wav(out, 4.8)  # the sentence is spoken for 5 s: ends with its speaker
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


def test_dub_generate_gives_omnivoice_its_target(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    timings = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None, timing=None):
        timings.append(dict(timing))
        timing["pace"] = 1.1  # what the worker reports
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "generate", fake_generate)
    api("PATCH", f"/api/dubs/{dub['id']}", {"model": "omnivoice"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d2", {"translation": "How are you?"})
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d2"]})
    assert _wait(api, job["id"])["state"] == "done"
    assert timings == [{"target": 5.0, "min_speed": 0.85, "max_speed": 1.25}]  # spoken 4.0-9.0 s
    take = dubs.load_dub(dub["id"])["tracks"][1]["clips"][1]["takes"][0]
    assert take["pace"] == 1.1  # Fit counts it


def test_dub_generate_target_stops_before_the_next_sentence(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    timings = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None, timing=None):
        timings.append(timing)
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "generate", fake_generate)
    api("PATCH", f"/api/dubs/{dub['id']}", {"model": "omnivoice"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d2", {"start": 2.0})  # the speaker of d1 talks until 3.0 s
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d1", {"translation": "Hello."})
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d1"]})
    assert _wait(api, job["id"])["state"] == "done"
    assert timings[0]["target"] == 1.45  # 2.0 - 0.5 - FIT_GAP


def _two_translated(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "generate", fake_generate)
    api("PATCH", f"/api/dubs/{dub['id']}", {"model": "higgs"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d1", {"translation": "Hello."})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d2", {"translation": "How are you?"})
    return dub


def test_a_level_error_fails_only_its_sentence(api, tmp_path, monkeypatch):
    dub = _two_translated(api, tmp_path, monkeypatch)
    matched = dubs.match_level

    def broken(did, cid, take, language=None):
        if cid == "d1":
            raise OSError("cannot read the take")
        return matched(did, cid, take, language)

    monkeypatch.setattr(dubs, "match_level", broken)
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d1", "d2"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed" and "Sentence 1: cannot read the take" in done["error"]
    clips = dubs.load_dub(dub["id"])["tracks"][1]["clips"]
    assert clips[0]["takes"] == [] and len(clips[1]["takes"]) == 1
    assert not (dubs.dub_dir(dub["id"]) / "takes" / "en" / "d1-1.wav").exists()  # not left behind


def test_a_timing_error_fails_only_its_sentence(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None, timing=None):
        make_wav(out, 1)
        return 0.1

    def broken(did, cid, language=None):
        if cid == "d1":
            raise ValueError("no timing")
        return None

    monkeypatch.setattr(models, "generate", fake_generate)
    monkeypatch.setattr(dubs, "generation_timing", broken)
    api("PATCH", f"/api/dubs/{dub['id']}", {"model": "omnivoice"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d1", {"translation": "Hello."})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d2", {"translation": "How are you?"})
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d1", "d2"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed" and "Sentence 1: no timing" in done["error"]
    assert len(dubs.load_dub(dub["id"])["tracks"][1]["clips"][1]["takes"]) == 1


def test_dub_generate_gives_other_models_no_target(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):  # no timing
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "generate", fake_generate)
    api("PATCH", f"/api/dubs/{dub['id']}", {"model": "higgs"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d2", {"translation": "How are you?"})
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d2"]})
    done = _wait(api, job["id"])
    assert done["state"] == "done", done


def test_generated_takes_match_their_sentence_level(api, tmp_path, monkeypatch):
    import numpy as np
    dub = _transcribed(api, tmp_path, monkeypatch)  # its sound is a 0.1 tone

    def quiet(name, text, ref, out, seed, settings, language, ref_text=None):
        t = np.arange(24000) / 24000
        dubs._write(Path(out), 24000, np.round(0.04 * 32767 * np.sin(2 * np.pi * 220 * t)))
        return 0.1

    monkeypatch.setattr(models, "generate", quiet)
    api("PATCH", f"/api/dubs/{dub['id']}", {"model": "higgs"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d1", {"translation": "Hello."})
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d1"]})
    done = _wait(api, job["id"])
    assert done["state"] == "done", done
    _, samples = dubs._read(dubs.dub_dir(dub["id"]) / done["result"]["tracks"][1]["clips"][0]["selected"])
    assert abs(abs(samples.astype(int)).max() / (0.1 * 32767) - 1) < 0.02


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

    def slow_generate(name, text, ref, out, seed, settings, language, ref_text=None, timing=None):
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

    monkeypatch.setattr(models, "is_installed", lambda name: name != "demucs")
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

    def slow_generate(name, text, ref, out, seed, settings, language, ref_text=None, timing=None):
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

    def slow_generate(name, text, ref, out, seed, settings, language, ref_text=None, timing=None):
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


def test_clear_takes_route(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    _take(dub["id"], "d1", 1.0)
    status, body, _ = api("POST", f"/api/dubs/{dub['id']}/takes/clear?language=en", {})
    assert status == 200 and body["removed"] == 1 and body["tracks"][1]["clips"][0]["takes"] == []


def test_fit_route_lengthens_and_counts_the_ones_needing_longer(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    _take(dub["id"], "d1", 1.9)  # 2.5 s spoken: lengthened at 0.85x
    _take(dub["id"], "d2", 2.0)  # 5 s spoken: far too short
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/fit", {"clips": ["d1", "d2"]})
    done = _wait(api, job["id"])
    assert done["result"]["notice"] == "Fitted 1 sentence. 1 needs a longer translation."
    assert done["result"]["fit"]["en"]["d1"]["speed"] == 0.85


def test_a_take_without_sound_is_not_kept(api, tmp_path, monkeypatch):
    """A take with no samples cannot be played (the window cannot decode it): it is refused, not added."""
    dub = _transcribed(api, tmp_path, monkeypatch)

    def silent(name, text, ref, out, seed, settings, language, ref_text=None, timing=None):
        make_wav(out, 0)
        return 0.1

    monkeypatch.setattr(models, "generate", silent)
    api("PATCH", f"/api/dubs/{dub['id']}", {"model": "omnivoice"})
    api("PATCH", f"/api/dubs/{dub['id']}/clips/d1", {"translation": "Hello."})
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/generate", {"clips": ["d1"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed" and "Sentence 1: the model returned no sound" in done["error"]
    assert dubs.load_dub(dub["id"])["tracks"][1]["clips"][0]["takes"] == []
    assert not (dubs.dub_dir(dub["id"]) / "takes" / "en" / "d1-1.wav").exists()


def _separator(calls):
    """A fake Demucs: writes stems the length of the sound."""
    def separate(audio, voices, background):
        calls.append((audio, voices, background))
        make_wav(voices, 12)
        make_wav(background, 12)
    return separate


def test_transcribe_separates_first_when_it_can(api, tmp_path, monkeypatch):
    calls = []
    dub = _transcribed(api, tmp_path, monkeypatch, separate=_separator(calls))
    assert dub["stems"] is True and dubs.has_stems(dub["id"])
    assert calls[0][0].endswith("audio.wav") and HEARD == [str(dubs.voices_path(dub["id"]))]


def test_transcribe_without_the_tool_is_unchanged(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    assert dub["stems"] is False and HEARD == [str(dubs.audio_path(dub["id"]))]


def test_transcribe_again_does_not_separate_again(api, tmp_path, monkeypatch):
    calls = []
    dub = _transcribed(api, tmp_path, monkeypatch, separate=_separator(calls))
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/transcribe", {})
    assert _wait(api, job["id"])["state"] == "done"
    assert len(calls) == 1 and HEARD[-1] == str(dubs.voices_path(dub["id"]))


def test_a_failed_separation_uses_the_full_mix(api, tmp_path, monkeypatch):
    def broken(audio, voices, background):
        make_wav(voices, 1)  # half written
        raise RuntimeError("out of GPU memory")
    dub = _transcribed(api, tmp_path, monkeypatch, separate=broken)
    assert dub["notice"] == "The voices could not be separated (out of GPU memory); the full mix was used."
    assert HEARD == [str(dubs.audio_path(dub["id"]))] and not dubs.has_stems(dub["id"])
    assert not any(path.exists() for path in dubs.stems_temp(dub["id"]))


def test_cancelling_separation_leaves_no_stems(api, tmp_path, monkeypatch):
    release, cancelled = threading.Event(), []

    def slow(audio, voices, background):
        make_wav(voices, 1)
        release.wait(5)
        raise RuntimeError("The model process stopped unexpectedly.")

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "separate", slow)
    monkeypatch.setattr(models, "cancel", lambda name, owner: cancelled.append(name) or release.set() or True)
    _, dub, _ = api("POST", "/api/dubs?name=T&ext=wav", raw=b"x", content_type="audio/wav")
    api("POST", f"/api/dubs/{dub['id']}/audio", raw=make_wav(tmp_path / "a.wav", 2).read_bytes(), content_type="audio/wav")
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/transcribe", {})
    for _ in range(100):
        if server_job(job["id"]).get("model"):
            break
        time.sleep(0.02)
    api("POST", f"/api/jobs/{job['id']}/cancel", {})
    assert _wait(api, job["id"])["state"] == "cancelled" and cancelled == ["demucs"]
    assert not dubs.has_stems(dub["id"]) and not any(path.exists() for path in dubs.stems_temp(dub["id"]))


def test_separate_route_and_full_mix_route(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    status, body, _ = api("POST", f"/api/dubs/{dub['id']}/separate", {})
    assert status == 400 and "Voice separation is not installed" in body["error"]
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "separate", _separator([]))
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/separate", {})
    done = _wait(api, job["id"])
    assert done["state"] == "done" and done["result"]["stems"] is True
    assert done["result"]["tracks"][0]["clips"] == dub["tracks"][0]["clips"]  # the sentences stay
    status, body, _ = api("DELETE", f"/api/dubs/{dub['id']}/separate")
    assert status == 200 and body["stems"] is False and not dubs.voices_path(dub["id"]).exists()


def test_voices_volume_option(api, tmp_path, monkeypatch):
    dub = _transcribed(api, tmp_path, monkeypatch)
    status, body, _ = api("PATCH", f"/api/dubs/{dub['id']}", {"voices_volume": 0.3})
    assert status == 200 and body["voices_volume"] == 0.3


def test_a_cancel_between_separating_and_listening_stops_before_whisper(api, tmp_path, monkeypatch):
    import server
    real_keep = dubs.keep_stems

    def keep_then_cancel(dub_id):  # the cancel lands after the separation, before Whisper starts
        real_keep(dub_id)
        next(j for j in server._jobs.values() if j["kind"] == "transcribe" and j["state"] == "running")["cancelled"] = True

    monkeypatch.setattr(dubs, "keep_stems", keep_then_cancel)
    HEARD.clear()
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "separate", _separator([]))
    monkeypatch.setattr(models, "transcribe_segments", lambda audio, language: HEARD.append(audio) or {"language": "tr", "segments": SEGMENTS})
    _, dub, _ = api("POST", "/api/dubs?name=T&ext=wav", raw=b"x", content_type="audio/wav")
    api("POST", f"/api/dubs/{dub['id']}/audio", raw=make_wav(tmp_path / "a.wav", 2).read_bytes(), content_type="audio/wav")
    _, job, _ = api("POST", f"/api/dubs/{dub['id']}/transcribe", {})
    assert _wait(api, job["id"])["state"] == "cancelled" and HEARD == []
