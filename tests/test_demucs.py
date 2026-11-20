"""The voice separation tool (Demucs): how it is installed and asked. The worker itself needs PyTorch and the model;
it is checked on a real install with `python worker.py --selftest`."""
import os

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402


def test_demucs_is_a_tool():
    tool = models.TOOLS["demucs"]
    assert "demucs" not in models.MODELS
    assert tool["title"] == "Voice separation (Demucs)"
    steps = [args for _, args in tool["pip_steps"]]
    assert models.TORCH_CUDA in steps
    assert any(arg.startswith("demucs==") for args in steps for arg in args)
    assert "weights" in tool["license"]


def test_separate_needs_the_tool(monkeypatch):
    monkeypatch.setattr(models, "is_installed", lambda name: False)
    with pytest.raises(RuntimeError, match="Voice separation is not installed"):
        models.separate("in.wav", "voices.wav", "background.wav")


def test_separate_sends_one_request(monkeypatch):
    sent = []
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "_request", lambda name, message: sent.append((name, message)) or {"ok": True, "seconds": 1})
    models.separate("in.wav", "voices.wav", "background.wav")
    assert sent == [("demucs", {"task": "separate", "audio": "in.wav", "voices": "voices.wav", "background": "background.wav"})]


def test_demucs_disk_counts_pytorch_unless_another_model_has_it(monkeypatch):
    monkeypatch.setattr(models, "is_installed", lambda name: False)
    assert models.needs_gb("demucs") == round(models.TOOLS["demucs"]["disk_gb"] + 1, 1) >= models.PYTORCH_GB + 1
    monkeypatch.setattr(models, "is_installed", lambda name: name == "omnivoice")
    assert 1 <= models.needs_gb("demucs") < models.PYTORCH_GB  # PyTorch shared: never negative


def test_demucs_says_it_uses_the_gpu_and_where_it_downloads_from():
    tool = models.TOOLS["demucs"]
    assert tool["vram_gb"] > 0
    assert "download.pytorch.org" in tool["downloads"]


def test_the_worker_finds_the_installed_weights_when_run_by_hand(monkeypatch):
    """--selftest run by hand must use the weights the install downloaded, not ~/.cache/torch."""
    import importlib.util
    from pathlib import Path
    monkeypatch.delenv("TORCH_HOME", raising=False)
    path = Path(__file__).resolve().parent.parent / "workers" / "demucs" / "worker.py"
    worker = importlib.util.module_from_spec(importlib.util.spec_from_file_location("demucs_worker", path))
    worker.__spec__.loader.exec_module(worker)
    worker.use_installed_weights()
    assert os.environ["TORCH_HOME"] == os.path.join(str(path.parent.parent.parent), ".local", "demucs", "cache")
    monkeypatch.setenv("TORCH_HOME", "/elsewhere")
    worker.use_installed_weights()
    assert os.environ["TORCH_HOME"] == "/elsewhere"  # the app's own setting wins
