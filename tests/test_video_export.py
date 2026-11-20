"""Video export: the FFmpeg tool, and the dub's video with the dub as its sound (with the system's ffmpeg when there
is one; the tool's own copy is found the same way)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402
from test_server import api  # noqa: E402,F401  (the api fixture)


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


FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="no ffmpeg on this computer")
NAMES = {"en": "English", "de": "German", "tr": "Turkish"}


def _video(path, codec_args):
    """A 2 s test video with a tone, made by ffmpeg."""
    subprocess.run([FFMPEG, "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=24000", "-t", "2", *codec_args, str(path)],
                   check=True)
    return path


def _streams(path):
    """[(kind, codec, language, title)] of a media file, from ffmpeg's own listing."""
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    streams, current = [], None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Stream #"):
            kind = "video" if "Video:" in line else "audio" if "Audio:" in line else "other"
            codec = line.split(f"{kind.capitalize()}: ")[1].split()[0].rstrip(",") if kind != "other" else ""
            language = line.split("(")[1].split(")")[0] if "(" in line.split(":")[1] else None
            current = [kind, codec, language, None]
            streams.append(current)
        elif current is not None and line.split(":")[0].strip() in ("title", "handler_name") and current[3] is None:
            current[3] = line.split(":", 1)[1].strip()  # MP4 keeps a track's name as its handler name
    return [tuple(s) for s in streams]


@pytest.fixture
def video_dub(tmp_workspace, tmp_path):
    import dubs
    from conftest import make_wav

    def make(ext="mp4", name="Talk", languages=("en",)):
        args = ["-c:v", "libx264", "-c:a", "aac"] if ext == "mp4" else ["-c:v", "libvpx-vp9", "-c:a", "libopus"]
        video = _video(tmp_path / f"in.{ext}", args)
        dub = dubs.create_dub(name, video.read_bytes(), ext)
        dubs.set_source_audio(dub, make_wav(tmp_path / "a.wav", 2).read_bytes())
        dubs.set_transcript(dub, "tr", [{"start": 0.2, "end": 1.5, "text": "Merhaba."}])
        for code in languages[1:]:
            dubs.add_language(dub, code)
        take = dubs.new_take_path(dub, "d1", "en")
        make_wav(take, 1.0)
        dubs.add_take(dub, "d1", {"file": str(take), "seed": 1, "duration": 1.0}, "en")
        return dub
    return make


@needs_ffmpeg
def test_export_video_has_the_dub_language(video_dub):
    import dubs
    dub = video_dub()
    out = dubs.export_video(dub, "en", ffmpeg=FFMPEG, names=NAMES)
    assert out.suffix == ".mp4" and out.parent.name == "exports"
    streams = _streams(out)
    assert [s[0] for s in streams] == ["video", "audio"]
    assert streams[0][1] == "h264" and streams[1][1] == "aac"  # the video copied as it was
    assert streams[1][2] == "eng" and streams[1][3] == "English"


@needs_ffmpeg
def test_export_video_every_language(video_dub):
    import dubs
    dub = video_dub(languages=("en", "de"))
    out = dubs.export_video(dub, "en", every_language=True, ffmpeg=FFMPEG, names=NAMES)
    audio = [s for s in _streams(out) if s[0] == "audio"]
    assert [(s[2], s[3]) for s in audio] == [("eng", "English"), ("ger", "German"), ("tur", "Original")]
    assert "-all-" in out.name


@needs_ffmpeg
def test_export_video_webm_gets_opus(video_dub):
    import dubs
    out = dubs.export_video(video_dub(ext="webm"), "en", ffmpeg=FFMPEG, names=NAMES)
    assert out.suffix == ".webm" and [s[1] for s in _streams(out) if s[0] == "audio"] == ["opus"]


@needs_ffmpeg
def test_export_video_file_name_is_safe(video_dub):
    import dubs
    out = dubs.export_video(video_dub(name="Türkçe deneme"), "en", ffmpeg=FFMPEG, names=NAMES)
    assert out.name.startswith("turkce-deneme-en-")


def test_export_video_refuses_an_audio_dub(tmp_workspace, tmp_path):
    import dubs
    from conftest import make_wav
    dub = dubs.create_dub("Talk", b"x", "mp3")
    dubs.set_source_audio(dub, make_wav(tmp_path / "a.wav", 2).read_bytes())
    with pytest.raises(dubs.ws.WorkspaceError, match="no video"):
        dubs.export_video(dub, None, ffmpeg="ffmpeg", names=NAMES)


@needs_ffmpeg
def test_export_video_failure_leaves_nothing(video_dub):
    import dubs
    dub = video_dub()
    (dubs.dub_dir(dub) / "source.mp4").write_bytes(b"not a video")
    with pytest.raises(dubs.ws.WorkspaceError, match="could not be exported"):
        dubs.export_video(dub, "en", ffmpeg=FFMPEG, names=NAMES)
    folder = dubs.dub_dir(dub) / "exports"
    assert not folder.exists() or list(folder.iterdir()) == []
    assert not list(dubs.dub_dir(dub).glob("*.wav.tmp*")) and not list(dubs.dub_dir(dub).glob("video-*.wav"))


@needs_ffmpeg
def test_export_video_route(api, video_dub, monkeypatch):
    dub = video_dub(languages=("en", "de"))
    monkeypatch.setattr(models, "ffmpeg_path", lambda: FFMPEG)
    status, body, _ = api("POST", f"/api/dubs/{dub}/export-video?language=en", {"every_language": True})
    assert status == 200 and body["path"].endswith(".mp4") and "-all-" in body["path"]
    import workspace as ws
    audio = [s for s in _streams(ws.workspace_root() / body["path"]) if s[0] == "audio"]
    assert [s[3] for s in audio] == ["English", "German", "Original"]


def test_export_video_route_needs_the_tool(api, tmp_workspace, monkeypatch):
    import dubs
    dub = dubs.create_dub("Talk", b"x", "mp4")
    monkeypatch.setattr(models, "ffmpeg_path", lambda: None)
    status, body, _ = api("POST", f"/api/dubs/{dub}/export-video", {})
    assert status == 400 and "Install Video export (FFmpeg)" in body["error"]
