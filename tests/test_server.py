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

    def fake_generate(name, text, ref, out, seed, settings):
        calls.append((name, text, ref, seed, settings))
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
    _, view, _ = api("GET", f"/api/sessions/{sid}")
    take = view["lines"][0]["takes"][0]
    assert take["model"] == "chatterbox" and take["seed"] == 7 and take["sample_label"] == "sample 1"
    assert view["lines"][0]["selected"] == take["file"]
