import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from stretch import stretch  # noqa: E402

RATE = 24000


def tone(seconds, frequency=220.0):
    t = np.arange(int(seconds * RATE)) / RATE
    return (0.5 * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


def peak_frequency(samples):
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return np.fft.rfftfreq(len(samples), 1 / RATE)[int(np.argmax(spectrum))]


def test_stretch_length():
    out = stretch(tone(2.0), RATE, 1.25)
    assert abs(len(out) / RATE - 1.6) < 0.016


def test_stretch_keeps_pitch():
    out = stretch(tone(2.0), RATE, 1.2)
    assert abs(peak_frequency(out) - 220.0) < 3


def test_stretch_factor_one_is_unchanged_length():
    samples = tone(1.5)
    out = stretch(samples, RATE, 1.0)
    assert len(out) == len(samples)


def test_stretch_short_input():
    samples = tone(0.01)  # shorter than one frame
    out = stretch(samples, RATE, 1.2)
    assert len(out) == len(samples)


def test_stretch_keeps_the_level():
    out = stretch(tone(2.0), RATE, 1.15)
    middle = out[len(out) // 4: -len(out) // 4]
    assert 0.4 < np.max(np.abs(middle)) <= 0.55  # no doubled or halved overlap
