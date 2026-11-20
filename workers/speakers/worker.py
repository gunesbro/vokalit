"""Speaker finder worker for Vokalit: tells who says each sentence of a dub, with SpeechBrain's ECAPA speaker
embeddings and grouping.py. Protocol: SPEC.md section 5.2.

python worker.py             serve requests on stdin/stdout (offline, network blocked)
python worker.py --download  download the model (used by Install)
python worker.py --selftest  group two synthetic voices and print the result (checks an install)

Request: {"task": "speakers", "audio": in.wav, "spans": [[start, end], ...], "count": int or null}.
Reply: {"labels": [int or null, ...]}, one per span. On the GPU when there is one, else on the CPU.
"""
import json
import os
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL = "speechbrain/spkrec-ecapa-voxceleb"
RATE = 16000  # what the model was trained on
LONGEST = 10.0  # seconds of a span embedded: its middle, enough to know a voice


def block_network():
    """Blocks connections, sends and name lookups (same as the other workers)."""

    def blocked(*args, **kwargs):
        raise RuntimeError("Network access is blocked in Vokalit workers (SPEC.md section 5.3).")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    socket.getaddrinfo = blocked


def cache():
    """Where the install keeps the model: the app's HF_HOME for this tool, or .local/speakers/cache when run by hand."""
    root = os.environ.get("HF_HOME") or str(HERE.parents[1] / ".local" / "speakers" / "cache")
    return Path(root) / "ecapa"


def load(download=False):
    import torch
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy

    device = "cuda" if torch.cuda.is_available() else "cpu"
    # Copied, not linked: Windows refuses symbolic links without developer mode.
    model = EncoderClassifier.from_hparams(source=MODEL if download else str(cache()), savedir=str(cache()),
                                           run_opts={"device": device}, local_strategy=LocalStrategy.COPY)
    model.eval()
    return model


def find(model, audio, spans, count):
    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio

    sys.path.insert(0, str(HERE))
    from grouping import group

    samples, rate = sf.read(audio, dtype="float32", always_2d=True)
    mono = torch.from_numpy(samples.mean(axis=1))
    sound = torchaudio.functional.resample(mono, rate, RATE) if rate != RATE else mono
    embeddings, durations = [], []
    for start, end in spans:
        durations.append(max(0.0, end - start))
        middle, half = (start + end) / 2, min(end - start, LONGEST) / 2
        piece = sound[max(0, round((middle - half) * RATE)):max(0, round((middle + half) * RATE))]
        if len(piece) == 0 or not bool(piece.abs().max() > 0):
            embeddings.append(None)
            continue
        if len(piece) < RATE:  # under a second: padded, so the model has enough frames
            piece = torch.nn.functional.pad(piece, (0, RATE - len(piece)))
        with torch.no_grad():
            embeddings.append(model.encode_batch(piece[None].to(model.device)).squeeze().cpu().numpy().astype(np.float64))
    return group(embeddings, durations, count)


def _out_of_memory(error):
    return "out of memory" in str(error).lower()


def selftest():
    import tempfile

    import numpy as np
    import soundfile as sf

    rate = 16000
    t = np.arange(2 * rate) / rate
    low, high = 0.3 * np.sin(2 * np.pi * 110 * t), 0.3 * np.sin(2 * np.pi * 330 * t) * np.sin(2 * np.pi * 3 * t)
    model = load()
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "in.wav")
        sf.write(path, np.concatenate([low, high, low, high]).astype("float32"), rate, subtype="PCM_16")
        start = time.perf_counter()
        labels = find(model, path, [[0, 2], [2, 4], [4, 6], [6, 8]], None)
        print(f"Speakers {labels} on {model.device} in {time.perf_counter() - start:.1f} s")


def main():
    if "--download" in sys.argv:
        load(download=True)
        return
    if "--selftest" in sys.argv:
        selftest()
        return

    block_network()  # before any library is imported
    reply = sys.stdout
    sys.stdout = sys.stderr  # library prints must not mix with protocol replies

    def send(**message):
        reply.write(json.dumps(message) + "\n")
        reply.flush()

    try:
        model = load()
    except Exception as error:
        send(ready=False, error=str(error), oom=_out_of_memory(error))
        return
    send(ready=True)
    for line in sys.stdin:
        request = json.loads(line)
        try:
            start = time.perf_counter()
            labels = find(model, request["audio"], request["spans"], request.get("count"))
            send(ok=True, labels=labels, seconds=round(time.perf_counter() - start, 1))
        except Exception as error:
            if _out_of_memory(error):
                import torch

                torch.cuda.empty_cache()
                send(ok=False, error=str(error), oom=True)
                continue
            # A CUDA error leaves the GPU context unusable for the rest of this process: exit, the app starts a new one.
            if "CUDA" in str(error) or "device-side assert" in str(error):
                send(ok=False, error=str(error), restart=True)
                sys.exit(1)
            send(ok=False, error=str(error))


if __name__ == "__main__":
    main()
