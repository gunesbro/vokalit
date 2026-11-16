import sys
import types
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


def _install_soundfile_shim():
    """Minimal stand-in for `soundfile` (16-bit PCM WAV only), used when the real one is not installed."""
    try:
        import soundfile  # noqa: F401
        return
    except ImportError:
        pass

    shim = types.ModuleType("soundfile")

    def read(path, dtype="float64"):
        with wave.open(str(path), "rb") as w:
            frames = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
            if w.getnchannels() > 1:
                frames = frames.reshape(-1, w.getnchannels())
            return frames.astype(dtype) / 32768.0, w.getframerate()

    def write(path, data, samplerate, subtype="PCM_16"):
        data = np.asarray(data)
        channels = 1 if data.ndim == 1 else data.shape[1]
        pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(samplerate)
            w.writeframes(pcm.tobytes())

    shim.read = read
    shim.write = write
    sys.modules["soundfile"] = shim


_install_soundfile_shim()


def make_wav(path, seconds, sr=24000):
    """Writes a quiet 16-bit mono tone of the given length and returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(round(seconds * sr))) / sr
    pcm = (0.1 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


@pytest.fixture
def tmp_workspace(tmp_path):
    import workspace

    workspace.init(tmp_path / "workspace")
    return tmp_path / "workspace"
