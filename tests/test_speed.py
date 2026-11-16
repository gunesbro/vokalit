"""The screens must open fast: no folder walks or subprocesses per request."""
import os

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402
import server  # noqa: E402


def _fake_install(tmp_path, monkeypatch, marker_text):
    monkeypatch.setattr(models, "LOCAL", str(tmp_path))
    folder = tmp_path / "chatterbox"
    folder.mkdir()
    (folder / "weights.bin").write_bytes(b"x" * 1000)
    (folder / "installed").write_text(marker_text)
    walks = []
    real = models.size_gb
    monkeypatch.setattr(models, "size_gb", lambda name: walks.append(name) or real(name))
    return walks


def test_installed_size_comes_from_the_marker(tmp_path, monkeypatch):
    walks = _fake_install(tmp_path, monkeypatch, "11.30")
    assert models.installed_size_gb("chatterbox") == 11.3
    assert walks == []


def test_old_marker_is_measured_once(tmp_path, monkeypatch):
    walks = _fake_install(tmp_path, monkeypatch, "")
    first = models.installed_size_gb("chatterbox")
    second = models.installed_size_gb("chatterbox")
    assert first == second
    assert walks == ["chatterbox"]


def test_gpu_name_runs_nvidia_smi_once(monkeypatch):
    calls = []

    class Result:
        returncode, stdout = 0, "NVIDIA GeForce RTX 4070 SUPER, 12282 MiB\n"

    monkeypatch.setattr(server.subprocess, "run", lambda *a, **k: calls.append(1) or Result())
    server._gpu_name.cache_clear()
    assert server._gpu_name() == server._gpu_name() == "NVIDIA GeForce RTX 4070 SUPER, 12282 MiB"
    assert len(calls) == 1
    server._gpu_name.cache_clear()


def test_character_list_reads_sessions_once(tmp_workspace, monkeypatch):
    import workspace as ws
    a, b = ws.create_character("A"), ws.create_character("B")
    sid = ws.create_session("Episode")
    ws.add_to_cast(sid, a, "library")
    reads = []
    real = ws.list_sessions
    monkeypatch.setattr(ws, "list_sessions", lambda: reads.append(1) or real())
    listed = {c["id"]: c["used_in"] for c in server.list_characters({})}
    assert listed == {a: ["Episode"], b: []}
    assert len(reads) == 1
