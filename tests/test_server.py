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
    status, _, _ = api("POST", f"/api/characters/{cid}/samples?source=recording", raw=good, content_type="audio/wav")
    assert status == 200
    status, body, _ = api("POST", f"/api/characters/{cid}/samples?source=upload", raw=short, content_type="audio/wav")
    assert status == 400 and "must be at least 10 seconds" in body["error"]
    _, data, _ = api("GET", f"/api/characters/{cid}")
    assert [s["id"] for s in data["samples"]] == ["s1"]


def test_generate_job_with_fake_model(api, monkeypatch, tmp_path):
    calls = []

    def fake_generate(name, text, ref, out, seed, settings, language):
        calls.append((name, text, ref, seed, settings, language))
        make_wav(out, 1)
        return 0.5

    monkeypatch.setattr(models, "generate", fake_generate)
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    _, session, _ = api("POST", "/api/sessions", {"name": "E"})
    _, character, _ = api("POST", "/api/characters", {"name": "Burak"})
    sid, cid = session["id"], character["id"]
    api("POST", f"/api/characters/{cid}/samples?source=upload", raw=make_wav(tmp_path / "s.wav", 11).read_bytes(),
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
    api("POST", f"/api/characters/{cid}/samples?source=upload", raw=make_wav(tmp_path / "s.wav", 11).read_bytes(),
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
    api("POST", f"/api/characters/{cid}/samples?source=upload", raw=make_wav(tmp_path / "s.wav", 11).read_bytes(),
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

    def fake_generate(name, text, ref, out, seed, settings, language):
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

    def fake_generate(name, text, ref, out, seed, settings, language):
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
