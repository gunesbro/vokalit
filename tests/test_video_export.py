"""Video export: the FFmpeg tool, and the dub's video with the dub as its sound (with the system's ffmpeg when there
is one; the tool's own copy is found the same way)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402


def test_ffmpeg_is_a_tool():
    tool = models.TOOLS["ffmpeg"]
    assert "ffmpeg" not in models.MODELS and tool["title"] == "Video export (FFmpeg)"
    steps = [args for _, args in tool["pip_steps"]]
    assert models.TORCH_CUDA not in steps and steps == [["imageio-ffmpeg==0.6.0"]]
    assert "GPL" in tool["license"] and tool["vram_gb"] == 0


def test_ffmpeg_path_is_found_in_the_tool_venv(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "model_dir", lambda name: str(tmp_path / name))
    binaries = tmp_path / "ffmpeg" / "venv" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries"
    binaries.mkdir(parents=True)
    exe = binaries / "ffmpeg-win-x86_64-v7.1.exe"
    exe.write_bytes(b"")
    (binaries / "README.md").write_text("not it")
    monkeypatch.setattr(models, "is_installed", lambda name: name == "ffmpeg")
    assert models.ffmpeg_path() == str(exe)
    monkeypatch.setattr(models, "is_installed", lambda name: False)
    assert models.ffmpeg_path() is None
