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
