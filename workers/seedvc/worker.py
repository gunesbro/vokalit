"""Voice conversion worker for Vokalit (Seed-VC): says a recording again in another voice, keeping its words, timing,
intonation and feeling. Dub uses it to turn a native speaker's take into the original speaker's voice, so the dub keeps
the speaker's voice without their accent. Protocol: SPEC.md section 5.2.

python worker.py             serve requests on stdin/stdout (offline, network blocked)
python worker.py --download  download Seed-VC's code (GitHub, a fixed commit) and its weights (used by Install)

Requests: {"task": "convert", "source", "ref", "out"} writes `source` in the voice of `ref` to `out` (16-bit PCM);
{"task": "pitch", "audio"} replies {"hz": median pitch of its voiced part, or null}.

Seed-VC is GPL-3.0. Its code is downloaded to this computer by the install and run here, never shipped with Vokalit.
"""
import argparse
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = "Plachtaa/seed-vc"
REVISION = "51383efd921027683c89e5348211d93ff12ac2a8"  # 2025: the v1 speech model this was measured with
DIFFUSION_STEPS = 30  # Seed-VC's default for offline conversion
CFG_RATE = 0.7


def block_network():
    """Blocks connections, sends and name lookups (same as the other workers)."""

    def blocked(*args, **kwargs):
        raise RuntimeError("Network access is blocked in Vokalit workers (SPEC.md section 5.3).")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    socket.getaddrinfo = blocked


def code_dir():
    """Seed-VC's code and its checkpoints folder: in the app's HF_HOME for this tool, or .local/seedvc/cache by hand."""
    root = os.environ.get("HF_HOME") or str(HERE.parents[1] / ".local" / "seedvc" / "cache")
    return Path(root) / f"seed-vc-{REVISION}"


def download_code():
    folder = code_dir()
    if folder.exists():
        return folder
    url = f"https://codeload.github.com/{REPO}/zip/{REVISION}"
    with urllib.request.urlopen(url, timeout=120) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    temp = folder.with_name(folder.name + ".part")
    shutil.rmtree(temp, ignore_errors=True)
    archive.extractall(temp)
    (inner,) = list(temp.iterdir())  # the archive holds one folder, seed-vc-<revision>
    inner.rename(folder)
    shutil.rmtree(temp, ignore_errors=True)
    return folder


def load():
    """Seed-VC's speech model (22 kHz, no pitch conditioning: the source's own pitch is kept), loaded once. Its
    script reads relative paths (configs, ./checkpoints), so it runs from its folder."""
    folder = code_dir()
    os.chdir(folder)
    sys.path.insert(0, str(folder))
    import inference  # Seed-VC's inference.py

    args = argparse.Namespace(source=None, target=None, output=None, diffusion_steps=DIFFUSION_STEPS,
                              length_adjust=1.0, inference_cfg_rate=CFG_RATE, f0_condition=False,
                              auto_f0_adjust=False, semi_tone_shift=0, checkpoint=None, config=None, fp16=True)
    loaded = inference.load_models(args)
    inference.load_models = lambda _args: loaded  # its main() loads them on every call otherwise
    return inference, args


def convert(engine, source, ref, out):
    import soundfile as sf

    inference, args = engine
    with tempfile.TemporaryDirectory() as folder:
        inference.main(argparse.Namespace(**{**vars(args), "source": source, "target": ref, "output": folder}))
        (made,) = list(Path(folder).glob("*.wav"))
        audio, rate = sf.read(str(made), dtype="float32")
    sf.write(out, audio.clip(-1, 1), rate, subtype="PCM_16")


def pitch(audio):
    """Median pitch (Hz) of the voiced, louder part of a recording, or None."""
    import librosa
    import numpy as np

    samples, rate = librosa.load(audio, sr=16000)
    if len(samples) < 1600:
        return None
    f0 = librosa.yin(samples, fmin=60, fmax=500, sr=rate, frame_length=1024)
    rms = librosa.feature.rms(y=samples, frame_length=1024, hop_length=256)[0][:len(f0)]
    voiced = f0[:len(rms)][rms > rms.max() * 10 ** (-30 / 20)]
    return round(float(np.median(voiced)), 1) if len(voiced) else None


def _out_of_memory(error):
    return "out of memory" in str(error).lower()


def main():
    if "--download" in sys.argv:
        download_code()
        load()  # downloads the weights into its checkpoints folder
        return

    block_network()  # before any library is imported
    reply = sys.stdout
    sys.stdout = sys.stderr  # library prints must not mix with protocol replies

    def send(**message):
        reply.write(json.dumps(message) + "\n")
        reply.flush()

    try:
        import torch

        engine = load()
    except Exception as error:
        send(ready=False, error=str(error), oom=_out_of_memory(error))
        return
    send(ready=True, vram_gb=round(torch.cuda.memory_reserved() / 1e9, 2) if torch.cuda.is_available() else 0)
    for line in sys.stdin:
        request = json.loads(line)
        try:
            start = time.perf_counter()
            if request.get("task") == "pitch":
                send(ok=True, hz=pitch(request["audio"]), seconds=round(time.perf_counter() - start, 1))
                continue
            convert(engine, request["source"], request["ref"], request["out"])
            send(ok=True, out=request["out"], seconds=round(time.perf_counter() - start, 1))
        except Exception as error:
            if _out_of_memory(error):
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
