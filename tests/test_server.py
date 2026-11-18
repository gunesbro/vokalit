import http.client
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402
import server  # noqa: E402
import workspace as ws  # noqa: E402
from conftest import make_wav  # noqa: E402

UI_DIR = Path(__file__).resolve().parent.parent / "app" / "ui"


@pytest.fixture
def api(tmp_workspace, tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html><head><title>t</title></head><body></body></html>", encoding="utf-8")
    url, token = server.start(ui)
    port = int(url.rsplit(":", 1)[1].rstrip("/"))

    def call(method, path, body=None, token_value=token, host=None, raw=None, content_type=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{port}"}
        if token_value:
            headers["X-Vokalit-Token"] = token_value
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        payload = response.read()
        conn.close()
        try:
            parsed = json.loads(payload) if payload else None
        except ValueError:
            parsed = payload.decode("utf-8", "replace")
        return response.status, parsed, dict(response.getheaders())

    call.token = token
    yield call
    server.stop()


def _wait(call, job_id):
    import time
    for _ in range(200):
        status, job, _ = call("GET", f"/api/jobs/{job_id}")
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_token_required(api):
    status, _, _ = api("GET", "/api/sessions", token_value=None)
    assert status == 403
    status, body, _ = api("GET", "/api/sessions")
    assert status == 200 and body == []


def test_foreign_host_refused(api):
    status, _, _ = api("GET", "/api/sessions", host="evil.example")
    assert status == 403
    status, _, _ = api("GET", "/", host="evil.example", token_value=None)
    assert status == 403


def test_files_path_traversal_refused(api, tmp_workspace):
    sid = ws.create_session("E")
    make_wav(ws.session_dir(sid) / "takes" / "a.wav", 1)
    status, _, headers = api("GET", f"/files/sessions/{sid}/takes/a.wav")
    assert status == 200 and headers["Content-Type"] == "audio/wav"
    for path in ("/files/../app/server.py", "/files/%2e%2e/%2e%2e/etc/passwd", f"/files/sessions/{sid}/session.json"):
        status, _, _ = api("GET", path)
        assert status == 404, path


def test_page_has_token_and_csp(api):
    status, page, headers = api("GET", "/", token_value=None)
    assert status == 200
    assert f'<meta name="vokalit-token" content="{api.token}">' in page
    assert "default-src 'self'" in headers["Content-Security-Policy"]


def test_session_lifecycle_over_api(api):
    _, session, _ = api("POST", "/api/sessions", {"name": "Episode 1"})
    sid = session["id"]
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    cid = character["id"]
    assert api("POST", f"/api/sessions/{sid}/cast", {"character": cid, "scope": "library"})[0] == 200
    _, a, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "one"})
    _, b, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "two"})
    assert api("PATCH", f"/api/sessions/{sid}/lines/{a['id']}", {"text": "first"})[0] == 200
    assert api("POST", f"/api/sessions/{sid}/lines/order", {"order": [b["id"], a["id"]]})[0] == 200
    _, view, _ = api("GET", f"/api/sessions/{sid}")
    assert [l["text"] for l in view["lines"]] == ["two", "first"]
    assert view["lines"][0]["character_name"] == "Burak"


def test_workspace_error_is_400_with_message(api):
    _, session, _ = api("POST", "/api/sessions", {"name": "E"})
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    sid, cid = session["id"], character["id"]
    api("POST", f"/api/sessions/{sid}/cast", {"character": cid, "scope": "library"})
    api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "one"})
    status, body, _ = api("DELETE", f"/api/sessions/{sid}/cast/{cid}")
    assert status == 400 and "Burak is used by lines 1" in body["error"]


def test_sample_upload_wav(api, tmp_path):
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    cid = character["id"]
    good = make_wav(tmp_path / "good.wav", 11).read_bytes()
    short = make_wav(tmp_path / "short.wav", 7).read_bytes()
    status, _, _ = api("POST", f"/api/characters/{cid}/samples?source=recording&transcript=Hi", raw=good, content_type="audio/wav")
    assert status == 200
    status, body, _ = api("POST", f"/api/characters/{cid}/samples?source=upload&transcript=Hi", raw=short, content_type="audio/wav")
    assert status == 400 and "must be at least 10 seconds" in body["error"]
    _, data, _ = api("GET", f"/api/characters/{cid}")
    assert [s["id"] for s in data["samples"]] == ["s1"]


def test_generate_job_with_fake_model(api, monkeypatch, tmp_path):
    calls = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        calls.append((name, text, ref, seed, settings, language))
        make_wav(out, 1)
        return 0.5

    monkeypatch.setattr(models, "generate", fake_generate)
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    _, session, _ = api("POST", "/api/sessions", {"name": "E"})
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    sid, cid = session["id"], character["id"]
    api("POST", f"/api/characters/{cid}/samples?source=upload&transcript=Hi", raw=make_wav(tmp_path / "s.wav", 11).read_bytes(),
        content_type="audio/wav")
    api("POST", f"/api/sessions/{sid}/cast", {"character": cid, "scope": "library"})
    _, line, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "Hello"})
    status, job, _ = api("POST", f"/api/sessions/{sid}/lines/{line['id']}/generate", {"models": ["chatterbox"], "seed": 7})
    assert status == 200
    done = _wait(api, job["id"])
    assert done["state"] == "done", done
    assert calls[0][1] == "Hello" and calls[0][3] == 7 and calls[0][2].endswith("s1.wav")
    assert calls[0][4] == models.default_settings("chatterbox")
    assert calls[0][5] == "en"
    _, view, _ = api("GET", f"/api/sessions/{sid}")
    take = view["lines"][0]["takes"][0]
    assert take["model"] == "chatterbox" and take["seed"] == 7 and take["sample_label"] == "sample 1"
    assert take["language"] == "en"
    assert view["lines"][0]["selected"] == take["file"]


def test_system_reports_gpu(api, monkeypatch):
    monkeypatch.setattr(server, "_gpu_name", lambda: "NVIDIA GeForce RTX 4070 SUPER, 12282 MiB")
    status, body, _ = api("GET", "/api/system")
    assert status == 200 and body["gpu"] == "NVIDIA GeForce RTX 4070 SUPER, 12282 MiB"


def test_models_have_summary(api):
    _, body, _ = api("GET", "/api/models")
    chatterbox = next(m for m in body if m["name"] == "chatterbox")
    assert "23 languages" in chatterbox["summary"]


def test_models_list_their_languages(api):
    _, body, _ = api("GET", "/api/models")
    chatterbox = next(m for m in body if m["name"] == "chatterbox")
    codes = [l["code"] for l in chatterbox["languages"]]
    assert len(codes) == 23 and "tr" in codes and "en" in codes
    assert {"code": "tr", "name": "Turkish"} in chatterbox["languages"]


def test_language_endpoints_validate_codes(api, tmp_path):
    _, session, _ = api("POST", "/api/sessions", {"name": "E"})
    sid = session["id"]
    status, body, _ = api("PATCH", f"/api/sessions/{sid}", {"language": "tr"})
    assert status == 200 and body["language"] == "tr"
    status, body, _ = api("PATCH", f"/api/sessions/{sid}", {"language": "klingon"})
    assert status == 400 and "Unknown language" in body["error"]
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    cid = character["id"]
    api("POST", f"/api/characters/{cid}/samples?source=upload&transcript=Hi", raw=make_wav(tmp_path / "s.wav", 11).read_bytes(),
        content_type="audio/wav")
    status, body, _ = api("PATCH", f"/api/characters/{cid}/samples/s1", {"language": "en"})
    assert status == 200 and body["samples"][0]["language"] == "en"
    api("POST", f"/api/sessions/{sid}/cast", {"character": cid, "scope": "library"})
    _, line, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "Hi"})
    status, body, _ = api("PATCH", f"/api/sessions/{sid}/lines/{line['id']}", {"language": "xx"})
    assert status == 400


def test_generation_with_unsupported_language_reports_model(api, monkeypatch):
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    _, session, _ = api("POST", "/api/sessions", {"name": "E"})
    sid = session["id"]
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    api("POST", f"/api/sessions/{sid}/cast", {"character": character["id"], "scope": "library"})
    _, line, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": character["id"], "text": "Hi"})
    monkeypatch.setitem(models.LANGUAGE_NAMES, "xx", "Testish")
    api("PATCH", f"/api/sessions/{sid}", {"language": "xx"})
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{line['id']}/generate", {"models": ["chatterbox"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed" and "Chatterbox Multilingual does not support Testish" in done["error"]


def test_reveal_opens_file_manager_for_workspace_audio(api, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(server, "_show_in_file_manager", lambda path: opened.append(path))
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    cid = character["id"]
    api("POST", f"/api/characters/{cid}/samples?source=upload&transcript=Hi", raw=make_wav(tmp_path / "s.wav", 11).read_bytes(),
        content_type="audio/wav")
    status, _, _ = api("POST", "/api/reveal", {"path": f"characters/{cid}/samples/s1.wav"})
    assert status == 200
    assert opened == [(ws.character_dir(cid) / "samples" / "s1.wav").resolve()]
    for bad in ("../outside.wav", f"characters/{cid}/character.json", "characters/nope.wav"):
        status, _, _ = api("POST", "/api/reveal", {"path": bad})
        assert status == 404, bad
    assert len(opened) == 1


def test_system_reports_platform(api):
    _, body, _ = api("GET", "/api/system")
    assert body["platform"] in ("win32", "linux", "darwin")


def _session_with_line(api, text):
    _, session, _ = api("POST", "/api/sessions", {"name": "E"})
    sid = session["id"]
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    api("POST", f"/api/sessions/{sid}/cast", {"character": character["id"], "scope": "library"})
    _, line, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": character["id"], "text": text})
    return sid, line["id"], character["id"]


def test_empty_line_is_not_generated(api, monkeypatch):
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", lambda *a: pytest.fail("generated an empty line"))
    sid, lid, _ = _session_with_line(api, "   ")
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{lid}/generate", {"models": ["chatterbox"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed" and "Line 1 is empty" in done["error"]


def test_generate_missing_skips_empty_lines(api, monkeypatch):
    generated = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        generated.append(text)
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", fake_generate)
    sid, _, cid = _session_with_line(api, "")
    api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "Hello"})
    api("PATCH", f"/api/sessions/{sid}", {"models": ["chatterbox"]})
    _, job, _ = api("POST", f"/api/sessions/{sid}/generate-missing", {})
    done = _wait(api, job["id"])
    assert done["state"] == "done" and generated == ["Hello"]
    assert done["result"] == {"generated": 1, "skipped_empty": 1}


def test_generate_selected_lines(api, monkeypatch):
    generated = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        generated.append(text)
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", fake_generate)
    sid, l1, cid = _session_with_line(api, "one")
    _, l2, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "two"})
    _, l3, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": ""})
    _, job, _ = api("POST", f"/api/sessions/{sid}/generate-lines",
                    {"lines": [l2["id"], l3["id"]], "models": ["chatterbox"]})
    done = _wait(api, job["id"])
    assert done["state"] == "done" and generated == ["two"]
    assert done["result"] == {"generated": 1, "skipped_empty": 1}


def test_bulk_line_endpoints(api):
    sid, l1, cid = _session_with_line(api, "one")
    _, l2, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "two"})
    status, body, _ = api("POST", f"/api/sessions/{sid}/lines/update", {"lines": [l1, l2["id"]], "fields": {"pause_after": 1.0}})
    assert status == 200 and [l["pause_after"] for l in body["lines"]] == [1.0, 1.0]
    status, body, _ = api("POST", f"/api/sessions/{sid}/lines/update", {"lines": [l1], "fields": {"language": "xx"}})
    assert status == 400
    status, body, _ = api("POST", f"/api/sessions/{sid}/lines/delete", {"lines": [l1]})
    assert status == 200 and [l["id"] for l in body["lines"]] == [l2["id"]]


def test_export_formats_endpoint_and_audio_files(api, monkeypatch, tmp_path):
    monkeypatch.setattr(ws, "export_formats", lambda: ["wav", "mp3"])
    status, body, _ = api("GET", "/api/export-formats")
    assert status == 200 and [f["id"] for f in body] == ["wav", "mp3"]
    assert all(f["label"] and f["note"] for f in body)
    sid, _, _ = _session_with_line(api, "one")
    exports = ws.session_dir(sid) / "exports"
    exports.mkdir()
    (exports / "a.mp3").write_bytes(b"ID3")
    opened = []
    monkeypatch.setattr(server, "_show_in_file_manager", lambda path: opened.append(path))
    status, _, _ = api("POST", "/api/reveal", {"path": f"sessions/{sid}/exports/a.mp3"})
    assert status == 200 and len(opened) == 1


def test_exports_and_trim_endpoints(api, monkeypatch):
    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        make_wav(out, 2)
        return 0.1

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", fake_generate)
    sid, lid, _ = _session_with_line(api, "one")
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{lid}/generate", {"models": ["chatterbox"]})
    _wait(api, job["id"])
    _, view, _ = api("GET", f"/api/sessions/{sid}")
    file = view["lines"][0]["takes"][0]["file"]
    status, body, _ = api("POST", f"/api/sessions/{sid}/lines/{lid}/takes/trim", {"file": file, "start": 0.2, "end": 1.2})
    assert status == 200 and len(body["lines"][0]["takes"]) == 2 and body["lines"][0]["takes"][1]["duration"] == 1.0
    status, body, _ = api("GET", f"/api/sessions/{sid}/exports")
    assert status == 200 and body == []
    _, job, _ = api("POST", f"/api/sessions/{sid}/export", {})
    _wait(api, job["id"])
    _, body, _ = api("GET", f"/api/sessions/{sid}/exports")
    assert len(body) == 1 and body[0]["path"].startswith(f"sessions/{sid}/exports/")
    status, body, _ = api("DELETE", f"/api/sessions/{sid}/exports", {"name": body[0]["name"]})
    assert status == 200 and body == []


def test_files_deleted_outside_the_app_are_removed(api, monkeypatch, tmp_path):
    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", fake_generate)
    sid, lid, cid = _session_with_line(api, "one")
    for name in ("s.wav", "t.wav"):
        api("POST", f"/api/characters/{cid}/samples?source=upload&transcript=Hi", raw=make_wav(tmp_path / name, 11).read_bytes(),
            content_type="audio/wav")
    for _ in range(2):
        _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{lid}/generate", {"models": ["chatterbox"]})
        _wait(api, job["id"])
    _, view, _ = api("GET", f"/api/sessions/{sid}")
    first, second = view["lines"][0]["takes"]
    api("POST", f"/api/sessions/{sid}/lines/{lid}/takes/select", {"file": second["file"]})
    (ws.session_dir(sid) / second["file"]).unlink()  # the selected take
    (ws.character_dir(cid) / "samples" / "s1.wav").unlink()  # the default sample
    _, view, _ = api("GET", f"/api/sessions/{sid}")
    line = view["lines"][0]
    assert [t["file"] for t in line["takes"]] == [first["file"]] and line["selected"] == first["file"]
    assert [x["id"] for x in view["cast"][0]["samples"]] == ["s2"] and view["cast"][0]["default_sample"] == "s2"
    assert [t["file"] for t in ws.load_session(sid)["lines"][0]["takes"]] == [first["file"]]  # saved, not just hidden
    (ws.character_dir(cid) / "samples" / "s2.wav").unlink()
    _, character, _ = api("GET", f"/api/characters/{cid}")
    assert character["samples"] == [] and character["default_sample"] is None


def test_file_being_renamed_is_not_removed(tmp_workspace):
    sid = ws.create_session("E")
    cid = ws.create_character("Burak")
    ws.add_to_cast(sid, cid, "library")
    lid = ws.add_line(sid, cid, "one")
    out = ws.new_take_path(sid, lid, "chatterbox")
    make_wav(out, 1)
    ws.add_take(sid, lid, {"file": str(out), "kind": "tts", "model": "chatterbox"})
    out.rename(out.with_name(out.name + ".renaming"))  # mid-way through sync_file_names
    assert ws.remove_missing_takes(sid) is False
    assert len(ws.load_session(sid)["lines"][0]["takes"]) == 1


def test_running_jobs_of_a_session_are_listed(api, monkeypatch):
    import threading
    release = threading.Event()

    def slow_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        release.wait(5)
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", slow_generate)
    sid, lid, cid = _session_with_line(api, "one")
    _, l2, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "two"})
    _, single, _ = api("POST", f"/api/sessions/{sid}/lines/{lid}/generate", {"models": ["chatterbox"]})
    status, running, _ = api("GET", f"/api/sessions/{sid}/jobs")
    assert status == 200 and running == [{"id": single["id"], "kind": "generate", "line": lid, "started": running[0]["started"],
                                          "progress": ""}]
    release.set()
    _wait(api, single["id"])
    release.clear()
    _, batch, _ = api("POST", f"/api/sessions/{sid}/generate-lines", {"lines": [l2["id"]], "models": ["chatterbox"]})
    import time as _t
    for _ in range(50):
        _, running, _ = api("GET", f"/api/sessions/{sid}/jobs")
        if running and running[0]["line"]:
            break
        _t.sleep(0.05)
    assert running[0]["kind"] == "batch" and running[0]["line"] == l2["id"]
    release.set()
    _wait(api, batch["id"])
    _, running, _ = api("GET", f"/api/sessions/{sid}/jobs")
    assert running == []


def test_audio_files_support_range_requests(api, tmp_path):
    """Seeking in an <audio> element needs byte ranges; without them the browser restarts from 0."""
    sid, _, _ = _session_with_line(api, "one")
    take = ws.session_dir(sid) / "takes" / "a.wav"
    make_wav(take, 1)
    whole = take.read_bytes()
    url = server._httpd.server_address
    conn = http.client.HTTPConnection("127.0.0.1", url[1], timeout=10)
    conn.request("GET", f"/files/sessions/{sid}/takes/a.wav", headers={"Host": f"127.0.0.1:{url[1]}", "Range": "bytes=100-199"})
    response = conn.getresponse()
    body = response.read()
    assert response.status == 206 and body == whole[100:200]
    assert response.getheader("Content-Range") == f"bytes 100-199/{len(whole)}"
    assert response.getheader("Accept-Ranges") == "bytes"
    conn.request("GET", f"/files/sessions/{sid}/takes/a.wav", headers={"Host": f"127.0.0.1:{url[1]}", "Range": "bytes=1000-"})
    response = conn.getresponse()
    assert response.status == 206 and response.read() == whole[1000:]
    conn.request("GET", f"/files/sessions/{sid}/takes/a.wav", headers={"Host": f"127.0.0.1:{url[1]}"})
    response = conn.getresponse()
    assert response.status == 200 and response.read() == whole and response.getheader("Accept-Ranges") == "bytes"
    conn.close()


def test_clear_takes_endpoint(api, tmp_path):
    sid, lid, _ = _session_with_line(api, "one")
    out = ws.new_take_path(sid, lid, "chatterbox")
    make_wav(out, 1)
    ws.add_take(sid, lid, {"file": str(out), "kind": "tts", "model": "chatterbox"})
    status, body, _ = api("POST", f"/api/sessions/{sid}/takes/clear", {"lines": [lid]})
    assert status == 200 and body["removed"] == 1 and body["session"]["lines"][0]["takes"] == []


def test_new_sample_needs_a_transcript(api, tmp_path):
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    audio = make_wav(tmp_path / "s.wav", 11).read_bytes()
    status, body, _ = api("POST", f"/api/characters/{character['id']}/samples?source=upload&transcript=%20",
                          raw=audio, content_type="audio/wav")
    assert status == 400 and "Write what the sample says first" in body["error"]
    status, _, _ = api("POST", f"/api/characters/{character['id']}/samples?source=upload&transcript=Hi",
                       raw=audio, content_type="audio/wav")
    assert status == 200


def test_turkish_transcript_arrives_intact(api, tmp_path):
    from urllib.parse import quote
    text = "Merhaba, \u00e7ok g\u00fczel & 100% do\u011fru?"
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    status, body, _ = api("POST", f"/api/characters/{character['id']}/samples?source=upload&transcript={quote(text)}",
                          raw=make_wav(tmp_path / "s.wav", 11).read_bytes(), content_type="audio/wav")
    assert status == 200 and body["samples"][0]["transcript"] == text


def test_transcript_can_be_corrected(api, tmp_path):
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    cid = character["id"]
    api("POST", f"/api/characters/{cid}/samples?source=upload&transcript=Hi", raw=make_wav(tmp_path / "s.wav", 11).read_bytes(),
        content_type="audio/wav")
    status, body, _ = api("PATCH", f"/api/characters/{cid}/samples/s1", {"transcript": "Hello there"})
    assert status == 200 and body["samples"][0]["transcript"] == "Hello there"
    status, body, _ = api("PATCH", f"/api/characters/{cid}/samples/s1", {"transcript": ""})
    assert status == 400 and "cannot be empty" in body["error"]


def test_transcribe_endpoint_without_whisper(api, tmp_path, monkeypatch):
    monkeypatch.setattr(models, "LOCAL", str(tmp_path / "local"))
    status, body, _ = api("POST", "/api/transcribe", raw=make_wav(tmp_path / "s.wav", 11).read_bytes(),
                          content_type="audio/wav")
    assert status == 400 and body["error"] == "Whisper is not installed."


def test_transcribe_endpoint_passes_the_language(api, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(models, "transcribe",
                        lambda audio, language: calls.append(language) or {"text": "Hello", "language": "tr"})
    status, body, _ = api("POST", "/api/transcribe?language=tr", raw=make_wav(tmp_path / "s.wav", 11).read_bytes(),
                          content_type="audio/wav")
    assert status == 200 and body == {"text": "Hello", "language": "tr"} and calls == ["tr"]


def test_unknown_detected_language_is_dropped(api, tmp_path, monkeypatch):
    monkeypatch.setattr(models, "transcribe", lambda audio, language: {"text": "Salve", "language": "xx"})
    status, body, _ = api("POST", "/api/transcribe", raw=make_wav(tmp_path / "s.wav", 11).read_bytes(),
                          content_type="audio/wav")
    assert status == 200 and body == {"text": "Salve", "language": None}


def test_new_sample_takes_the_detected_language(api, tmp_path):
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    status, body, _ = api("POST", f"/api/characters/{character['id']}/samples?source=upload&transcript=Hi&language=tr",
                          raw=make_wav(tmp_path / "s.wav", 11).read_bytes(), content_type="audio/wav")
    assert status == 200 and body["samples"][0]["language"] == "tr"


def test_saved_sample_can_be_transcribed_again(api, tmp_path, monkeypatch):
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    cid = character["id"]
    api("POST", f"/api/characters/{cid}/samples?source=upload&transcript=Old", raw=make_wav(tmp_path / "s.wav", 11).read_bytes(),
        content_type="audio/wav")
    api("PATCH", f"/api/characters/{cid}/samples/s1", {"language": "en"})
    monkeypatch.setattr(models, "transcribe",
                        lambda audio, language: {"text": f"New {language} {Path(audio).name}", "language": language})
    status, body, _ = api("POST", f"/api/characters/{cid}/samples/s1/transcribe")
    assert status == 200 and body["samples"][0]["transcript"] == "New en s1.wav"


def test_components_lists_whisper_first(api, tmp_path, monkeypatch):
    monkeypatch.setattr(models, "LOCAL", str(tmp_path / "local"))
    status, body, _ = api("GET", "/api/components")
    assert status == 200
    first = body["items"][0]
    assert first["name"] == "whisper" and first["kind"] == "tool" and first["recommended"] is True
    assert {item["kind"] for item in body["items"][1:]} == {"model"}
    assert body["installing"] is None and "total_gb" in body


def test_missing_transcripts_are_written_in_the_background(api, tmp_workspace, tmp_path, monkeypatch):
    import threading
    cid = ws.create_character("Burak")
    ws.add_sample(cid, str(make_wav(tmp_path / "a.wav", 11)), "recording")
    ws.add_sample(cid, str(make_wav(tmp_path / "b.wav", 11)), "recording")
    ws.set_sample_language(cid, "s2", "en")
    release = threading.Event()

    def fake(audio, language):
        release.wait(5)
        return {"text": f"heard {Path(audio).name}", "language": "tr"}

    monkeypatch.setattr(models, "transcribe", fake)
    server.transcribe_missing()
    _, body, _ = api("GET", f"/api/characters/{cid}")
    assert all(s.get("transcribing") for s in body["samples"])
    release.set()
    server._transcriber_idle(5)
    _, body, _ = api("GET", f"/api/characters/{cid}")
    assert [s["transcript"] for s in body["samples"]] == ["heard s1.wav", "heard s2.wav"]
    assert [s.get("language") for s in body["samples"]] == ["tr", "en"]  # a chosen language is kept
    assert not any(s.get("transcribing") for s in body["samples"])


def test_old_sample_without_transcript_fails_for_omnivoice_only(api, tmp_workspace, monkeypatch, tmp_path):
    calls = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        calls.append((name, ref_text))
        make_wav(out, 1)
        return 0.5

    monkeypatch.setattr(models, "generate", fake_generate)
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    cid = ws.create_character("Burak")
    ws.add_sample(cid, str(make_wav(tmp_path / "old.wav", 11)), "recording")  # saved before transcripts existed
    _, session, _ = api("POST", "/api/sessions", {"name": "E"})
    sid = session["id"]
    api("POST", f"/api/sessions/{sid}/cast", {"character": cid, "scope": "library"})
    _, line, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "Hello"})
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{line['id']}/generate", {"models": ["chatterbox", "omnivoice"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed"
    assert "OmniVoice: This sample has no transcript. Add it on the Characters screen or install Whisper." in done["error"]
    assert calls == [("chatterbox", None)]
    _, view, _ = api("GET", f"/api/sessions/{sid}")
    assert [t["model"] for t in view["lines"][0]["takes"]] == ["chatterbox"]


def test_transcript_is_sent_with_the_sample(api, monkeypatch, tmp_path):
    calls = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        calls.append((name, ref_text))
        make_wav(out, 1)
        return 0.5

    monkeypatch.setattr(models, "generate", fake_generate)
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    _, session, _ = api("POST", "/api/sessions", {"name": "E"})
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    sid, cid = session["id"], character["id"]
    api("POST", f"/api/characters/{cid}/samples?source=upload&transcript=Merhaba", raw=make_wav(tmp_path / "s.wav", 11).read_bytes(),
        content_type="audio/wav")
    api("POST", f"/api/sessions/{sid}/cast", {"character": cid, "scope": "library"})
    _, line, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "Hello"})
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{line['id']}/generate", {"models": ["omnivoice"]})
    assert _wait(api, job["id"])["state"] == "done"
    assert calls == [("omnivoice", "Merhaba")]


def test_line_of_only_tags_is_skipped_for_chatterbox(api, monkeypatch):
    generated = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        assert text.strip(), "an empty text reached a model"
        generated.append((name, text))
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", fake_generate)
    sid, lid, _ = _session_with_line(api, "[laughter]")
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{lid}/generate", {"models": ["chatterbox", "omnivoice"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed" and "Chatterbox Multilingual: Line 1 is empty" in done["error"]
    assert generated == [("omnivoice", "[laughter]")]


def test_chatterbox_gets_the_text_without_tags_and_the_take_keeps_them(api, monkeypatch):
    generated = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        generated.append(text)
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", fake_generate)
    sid, lid, _ = _session_with_line(api, "Well [sigh] fine.")
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{lid}/generate", {"models": ["chatterbox"]})
    assert _wait(api, job["id"])["state"] == "done"
    assert generated == ["Well fine."]
    _, view, _ = api("GET", f"/api/sessions/{sid}")
    assert view["lines"][0]["takes"][0]["text"] == "Well [sigh] fine."


def test_models_list_their_tags(api):
    _, listed, _ = api("GET", "/api/models")
    tags = {m["name"]: m["tags"] for m in listed}
    assert tags["chatterbox"] == [] and tags["omnivoice"] == models.OMNIVOICE_TAGS


def test_model_without_the_language_is_skipped_when_another_speaks_it(api, monkeypatch):
    generated = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        generated.append(name)
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", fake_generate)
    sid, lid, _ = _session_with_line(api, "Hello")
    api("PATCH", f"/api/sessions/{sid}/lines/{lid}", {"language": "mhr"})  # Eastern Mari: OmniVoice only
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{lid}/generate", {"models": ["chatterbox", "omnivoice"]})
    assert _wait(api, job["id"])["state"] == "done"
    assert generated == ["omnivoice"]


def test_batch_generates_model_by_model(api, monkeypatch):
    # Each model loads once: all lines with the first model, then all with the next (no swapping per line when the
    # models do not fit on the GPU together). A line keeps one seed across models.
    calls = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        calls.append((name, text, seed))
        make_wav(out, 1)
        return 0.1

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", fake_generate)
    sid, first, cid = _session_with_line(api, "One")
    api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "Two"})
    _, third, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "Three"})
    api("PATCH", f"/api/sessions/{sid}/lines/{third['id']}", {"language": "mhr"})  # Eastern Mari: OmniVoice only
    _, job, _ = api("POST", f"/api/sessions/{sid}/generate-missing", {"models": ["chatterbox", "omnivoice"]})
    assert _wait(api, job["id"])["state"] == "done"
    assert [(n, t) for n, t, _ in calls] == [("chatterbox", "One"), ("chatterbox", "Two"),
                                             ("omnivoice", "One"), ("omnivoice", "Two"), ("omnivoice", "Three")]
    seeds = {t: {s for n, tt, s in calls if tt == t} for t in ("One", "Two", "Three")}
    assert all(len(s) == 1 for s in seeds.values())


def test_running_install_is_listed_so_a_new_screen_can_follow_it(api, monkeypatch, tmp_path):
    import threading
    monkeypatch.setattr(models, "LOCAL", str(tmp_path / "local"))
    release = threading.Event()

    def slow_install(name):
        yield "status", "Step 1/3: Python environment"
        release.wait(5)

    monkeypatch.setattr(models, "install", slow_install)
    _, job, _ = api("POST", "/api/models/omnivoice/install")
    try:
        _, listed, _ = api("GET", "/api/components")
        assert listed["install_job"] == {"id": job["id"], "name": "omnivoice"}
    finally:
        release.set()
    _wait(api, job["id"])
    _, listed, _ = api("GET", "/api/components")
    assert listed["install_job"] is None


def test_components_say_which_models_are_loaded(api, monkeypatch, tmp_path):
    import threading
    import time

    class Loaded:
        lock = threading.Lock()
        last_used = time.monotonic() - 60
        vram_gb = 2.4
        mode = None

    monkeypatch.setitem(models._workers, "omnivoice", Loaded())
    try:
        _, listed, _ = api("GET", "/api/components")
        runtime = {item["name"]: item["runtime"] for item in listed["items"]}
        assert runtime["chatterbox"] == {"loaded": False}
        omni = runtime["omnivoice"]
        assert omni["loaded"] and not omni["busy"] and omni["vram_gb"] == 2.4
        assert models.IDLE_SECONDS - 70 <= omni["unloads_in"] <= models.IDLE_SECONDS - 50
    finally:
        models._workers.pop("omnivoice", None)


def test_unload_stops_a_model_but_not_while_it_generates(api, monkeypatch):
    import threading
    import time
    stopped = []

    class Loaded:
        lock = threading.Lock()
        last_used = time.monotonic()
        vram_gb = None

    monkeypatch.setattr(models, "stop", lambda name: stopped.append(name) or models._workers.pop(name, None))
    worker = Loaded()
    monkeypatch.setitem(models._workers, "omnivoice", worker)
    with worker.lock:
        status, body, _ = api("POST", "/api/models/omnivoice/unload")
    assert status == 400 and "generating" in body["error"] and stopped == []
    status, body, _ = api("POST", "/api/models/omnivoice/unload")
    assert status == 200 and stopped == ["omnivoice"] and body["runtime"] == {"loaded": False}


def test_components_show_gpu_memory(api, tmp_path, monkeypatch):
    monkeypatch.setattr(models, "LOCAL", str(tmp_path / "local"))
    status, body, _ = api("GET", "/api/components")
    items = {item["name"]: item for item in body["items"]}
    assert items["chatterbox"]["vram_gb"] == 4.1
    assert items["omnivoice"]["vram_gb"] == 2.7
    assert items["whisper"]["vram_gb"] is None


STYLE = {"key": "style", "type": "text", "label": "Style", "default": "", "max_length": 200, "help": "",
         "placeholder": "", "suggestions": [{"label": "Happy", "value": "cheerful"}]}


@pytest.fixture
def text_setting(monkeypatch):
    monkeypatch.setitem(models.MODELS["chatterbox"], "settings", [*models.MODELS["chatterbox"]["settings"], STYLE])


def test_text_setting_is_cleaned(text_setting):
    assert models.clean_settings("chatterbox", {"style": "  happy (very)\n warm "}) == {"style": "happy very warm"}
    assert models.clean_settings("chatterbox", {"style": " ( ) "}) == {"style": ""}


def test_text_setting_too_long(text_setting):
    with pytest.raises(ValueError, match="200"):
        models.clean_settings("chatterbox", {"style": "a" * 201})


def test_text_setting_must_be_text(text_setting):
    with pytest.raises(ValueError):
        models.clean_settings("chatterbox", {"style": 3})


def test_slider_rejects_a_string(api):
    _, session, _ = api("POST", "/api/sessions", {"name": "E"})
    status, body, _ = api("PUT", f"/api/sessions/{session['id']}/settings/chatterbox", {"exaggeration": "a"})
    assert status == 400 and "Expressiveness" in body["error"]


def test_line_settings_store_cleaned_text(api, text_setting):
    sid, lid, _ = _session_with_line(api, "Hello.")
    status, body, _ = api("PUT", f"/api/sessions/{sid}/lines/{lid}/settings/chatterbox", {"style": "(sad)"})
    assert status == 200
    assert ws.load_session(sid)["lines"][0]["settings"]["chatterbox"] == {"style": "sad"}


def test_line_text_override_equal_to_session_is_not_stored(api, text_setting):
    sid, lid, _ = _session_with_line(api, "Hello.")
    api("PUT", f"/api/sessions/{sid}/settings/chatterbox", {"style": "sad"})
    status, _, _ = api("PUT", f"/api/sessions/{sid}/lines/{lid}/settings/chatterbox", {"style": "(sad)"})
    assert status == 200
    assert "chatterbox" not in ws.load_session(sid)["lines"][0]["settings"]


def test_microphone_permission_is_remembered(api, tmp_path, monkeypatch):
    monkeypatch.setattr(models, "LOCAL", str(tmp_path / "local"))
    assert server.microphone_allowed() is False
    assert api("POST", "/api/microphone", {"allowed": True})[0] == 200
    assert server.microphone_allowed() is True
    assert api("POST", "/api/microphone", {"allowed": False})[0] == 200  # blocked: ask again next time
    assert server.microphone_allowed() is False


def test_line_of_only_new_tags_is_empty_for_other_models(api, monkeypatch):
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", lambda *a, **k: pytest.fail("generated tags as text"))
    sid, lid, _ = _session_with_line(api, "[anger] [pause]")
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{lid}/generate", {"models": ["chatterbox"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed" and "Line 1 is empty without its sound tags" in done["error"]


def test_higgs_needs_a_transcript(api, tmp_workspace, monkeypatch, tmp_path):
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", lambda *a, **k: pytest.fail("generated without a transcript"))
    cid = ws.create_character("Burak")
    ws.add_sample(cid, str(make_wav(tmp_path / "old.wav", 11)), "recording")  # no transcript
    _, session, _ = api("POST", "/api/sessions", {"name": "E"})
    sid = session["id"]
    api("POST", f"/api/sessions/{sid}/cast", {"character": cid, "scope": "library"})
    _, line, _ = api("POST", f"/api/sessions/{sid}/lines", {"character": cid, "text": "Merhaba", "language": "tr"})
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{line['id']}/generate", {"models": ["higgs"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed" and "Higgs TTS 3: This sample has no transcript" in done["error"]


def test_higgs_line_without_words_is_empty(api, monkeypatch):
    calls = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        calls.append(text)
        make_wav(out, 1)
        return 0.5

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", fake_generate)
    sid, lid, _ = _session_with_line(api, "[anger] [pause]")
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{lid}/generate", {"models": ["higgs"]})
    done = _wait(api, job["id"])
    assert done["state"] == "failed" and "Line 1 is empty without its sound tags" in done["error"] and not calls
    api("PATCH", f"/api/sessions/{sid}/lines/{lid}", {"text": "[laughter]"})  # a sound alone is spoken ("Haha")
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{lid}/generate", {"models": ["higgs"]})
    assert _wait(api, job["id"])["state"] == "done" and calls == ["<|sfx:laughter|>Haha"]


def test_higgs_install_shows_the_required_credit():
    assert "Boson AI's Higgs Audio" in models.MODELS["higgs"]["license"]


def test_cancel_stops_a_generating_line(api, monkeypatch):
    import threading
    cancelled = threading.Event()
    calls = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        Path(out).write_bytes(b"partial")
        cancelled.wait(5)
        raise RuntimeError("The model process stopped unexpectedly.")

    def fake_cancel(name, owner):
        calls.append((name, owner))
        cancelled.set()
        return True

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", fake_generate)
    monkeypatch.setattr(models, "cancel", fake_cancel)
    sid, lid, _ = _session_with_line(api, "Hello.")
    _, job, _ = api("POST", f"/api/sessions/{sid}/lines/{lid}/generate", {"models": ["chatterbox"]})
    import time
    time.sleep(0.2)
    assert api("POST", f"/api/jobs/{job['id']}/cancel", {})[0] == 200
    done = _wait(api, job["id"])
    assert done["state"] == "cancelled" and calls == [("chatterbox", job["id"])]
    session = ws.load_session(sid)
    assert session["lines"][0]["takes"] == []
    assert not list((ws.session_dir(sid) / "takes").glob("*")) if (ws.session_dir(sid) / "takes").exists() else True


def test_cancel_stops_a_batch_at_once(api, monkeypatch):
    import threading
    started = threading.Event()
    release = threading.Event()
    generated = []

    def fake_generate(name, text, ref, out, seed, settings, language, ref_text=None):
        started.set()
        if not generated:
            release.wait(5)
            raise RuntimeError("The model process stopped unexpectedly.")
        generated.append(text)
        make_wav(out, 1)
        return 0.5

    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "generate", fake_generate)
    monkeypatch.setattr(models, "cancel", lambda name, owner: release.set() or True)
    sid, lid, _ = _session_with_line(api, "One.")
    api("POST", f"/api/sessions/{sid}/lines", {"character": ws.load_session(sid)["cast"][0]["character"], "text": "Two."})
    _, job, _ = api("POST", f"/api/sessions/{sid}/generate-missing", {"models": ["chatterbox"]})
    started.wait(5)
    api("POST", f"/api/jobs/{job['id']}/cancel", {})
    done = _wait(api, job["id"])
    assert done["state"] == "cancelled" and done["progress"] == "Stopped after 0 of 2 takes." and generated == []


def test_cancel_kills_only_the_jobs_own_request(monkeypatch):
    killed = []

    class Fake:
        def __init__(self, owner):
            self.owner, self.process = owner, owner

    monkeypatch.setattr(models, "_kill_tree", killed.append)
    monkeypatch.setitem(models._workers, "chatterbox", Fake("job-a"))
    assert models.cancel("chatterbox", "job-b") is False and killed == []
    assert models.cancel("chatterbox", "job-a") is True and killed == ["job-a"]
    assert "chatterbox" not in models._workers


def test_remove_waits_while_the_model_generates(api, monkeypatch):
    import threading
    import time
    removed = []

    class Loaded:
        lock = threading.Lock()
        last_used = time.monotonic()
        vram_gb = None
        mode = None

    monkeypatch.setattr(models, "remove", lambda name, maintain=True: removed.append(name))
    worker = Loaded()
    monkeypatch.setitem(models._workers, "omnivoice", worker)
    with worker.lock:
        status, body, _ = api("POST", "/api/models/omnivoice/remove")
    assert status == 400 and "generating" in body["error"] and removed == []
    models._workers.pop("omnivoice", None)
    status, _, _ = api("POST", "/api/models/omnivoice/remove")
    assert status == 200 and removed == ["omnivoice"]
