"""Changing a sound's speed without changing its pitch (WSOLA), to fit a dub take into its sentence's time."""
import numpy as np

FRAME_SECONDS = 0.04  # one piece of sound; pieces overlap by half
SEARCH_SECONDS = 0.01  # how far a piece may move to line up with the one before it


def stretch(samples: np.ndarray, rate: int, factor: float) -> np.ndarray:
    """`samples` (mono) played `factor` times faster at the same pitch: the result is len / factor long.

    Pieces are taken from the input every frame/2 * factor samples and laid down every frame/2 samples; each piece is
    moved by up to SEARCH_SECONDS to where it best continues the previous one (cross-correlation), so the overlaps add
    in phase instead of cancelling."""
    samples = np.asarray(samples, dtype=np.float64)
    frame = int(rate * FRAME_SECONDS)
    hop = frame // 2
    search = int(rate * SEARCH_SECONDS)
    if factor == 1 or len(samples) < frame:
        return samples.astype(np.float32)
    out_length = int(round(len(samples) / factor))
    count = out_length // hop + 1
    pad = frame + 2 * search
    source = np.concatenate([np.zeros(pad), samples, np.zeros(pad + frame + int(hop * factor) + 1)])
    window = np.hanning(frame + 1)[:frame]  # periodic: overlapping by half, the windows add up to 1
    out = np.zeros(count * hop + frame)
    weight = np.zeros_like(out)
    size = 1 << int(np.ceil(np.log2(2 * frame + 2 * search)))
    previous = None
    for k in range(count):
        nominal = pad + int(round(k * hop * factor))
        if previous is None:
            position = nominal
        else:
            follow = source[previous + hop:previous + hop + frame]  # what would naturally come next
            start = nominal - search
            region = source[start:start + frame + 2 * search]
            correlation = np.fft.irfft(np.fft.rfft(region, size) * np.conj(np.fft.rfft(follow, size)), size)
            position = start + int(np.argmax(correlation[:2 * search + 1]))
        out[k * hop:k * hop + frame] += window * source[position:position + frame]
        weight[k * hop:k * hop + frame] += window
        previous = position
    out, weight = out[:out_length], weight[:out_length]
    return np.divide(out, weight, out=np.zeros_like(out), where=weight > 1e-6).astype(np.float32)
