"""Voice separation worker for Vokalit: splits a dub's sound into voices and background with Demucs. Protocol: SPEC.md
section 5.2.

python worker.py             serve requests on stdin/stdout (offline, network blocked)
python worker.py --download  download the model (used by Install)
python worker.py --selftest  separate a few seconds of test sound and print what came out (checks an install)

Request: {"task": "separate", "audio": in.wav, "voices": out.wav, "background": out.wav}. Mono 16-bit WAVs in and out,
at the input's rate. On the GPU when there is one, else on the CPU (slower).
"""
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

MODEL = "htdemucs"


def block_network():
    """Blocks connections, sends and name lookups (same as the other workers)."""

    def blocked(*args, **kwargs):
        raise RuntimeError("Network access is blocked in Vokalit workers (SPEC.md section 5.3).")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    socket.getaddrinfo = blocked


def use_installed_weights():
    """The weights the install downloaded (.local/demucs/cache), also when this is run by hand (--selftest); the app
    sets TORCH_HOME itself."""
    os.environ.setdefault("TORCH_HOME", str(Path(__file__).resolve().parents[2] / ".local" / "demucs" / "cache"))


def load():
    import torch
    from demucs.pretrained import get_model

    model = get_model(MODEL)  # cached under TORCH_HOME (the tool's folder) by --download
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return model.to(device), device


def separate(model, device, audio, voices, background):
    import soundfile as sf
    import torch
    import torchaudio
    from demucs.apply import apply_model

    samples, rate = sf.read(audio, dtype="float32", always_2d=True)
    mono = torch.from_numpy(samples.mean(axis=1))
    wav = torchaudio.functional.resample(mono, rate, model.samplerate) if rate != model.samplerate else mono
    mix = wav.repeat(model.audio_channels, 1)  # the model's channels from the mono sound
    # Normalized as Demucs' own command does; the stems are scaled back.
    scale = mix.mean(0).std() + 1e-8
    shift = mix.mean(0).mean()
    with torch.no_grad():  # long sounds go through in overlapping segments, so memory stays bounded on the GPU
        sources = apply_model(model, ((mix - shift) / scale)[None], split=True, overlap=0.25, device=device)[0]
    sources = sources.cpu() * scale
    vocals = model.sources.index("vocals")
    stems = {voices: sources[vocals].mean(0), background: (sources.sum(0) - sources[vocals]).mean(0)}
    for path, stem in stems.items():
        out = torchaudio.functional.resample(stem, model.samplerate, rate) if rate != model.samplerate else stem
        sf.write(path, out[:len(mono)].clamp(-1, 1).numpy(), rate, subtype="PCM_16")  # the app fits the length


def _out_of_memory(error):
    return "out of memory" in str(error).lower()


def selftest():
    import numpy as np
    import soundfile as sf

    rate = 24000
    t = np.arange(3 * rate) / rate
    sound = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.05 * np.random.default_rng(0).standard_normal(len(t))
    model, device = load()
    with tempfile.TemporaryDirectory() as folder:
        paths = [os.path.join(folder, name) for name in ("in.wav", "voices.wav", "background.wav")]
        sf.write(paths[0], sound.astype("float32"), rate, subtype="PCM_16")
        start = time.perf_counter()
        separate(model, device, *paths)
        for path in paths[1:]:
            out, out_rate = sf.read(path)
            print(f"{os.path.basename(path)}: {len(out) / out_rate:.2f} s at {out_rate} Hz")
        print(f"Separated on {device} in {time.perf_counter() - start:.1f} s")


def main():
    use_installed_weights()
    if "--download" in sys.argv:
        load()
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
        model, device = load()
    except Exception as error:
        send(ready=False, error=str(error), oom=_out_of_memory(error))
        return
    send(ready=True)
    for line in sys.stdin:
        request = json.loads(line)
        try:
            start = time.perf_counter()
            separate(model, device, request["audio"], request["voices"], request["background"])
            send(ok=True, seconds=round(time.perf_counter() - start, 1))
        except Exception as error:
            if _out_of_memory(error):
                import torch

                torch.cuda.empty_cache()
                send(ok=False, error=str(error), oom=True)
                continue
            # A CUDA error leaves the GPU context unusable for the rest of this process. Report it and exit; the app
            # starts a fresh worker (as the voice model workers do).
            if "CUDA" in str(error) or "device-side assert" in str(error):
                send(ok=False, error=str(error), restart=True)
                sys.exit(1)
            send(ok=False, error=str(error))


if __name__ == "__main__":
    main()
