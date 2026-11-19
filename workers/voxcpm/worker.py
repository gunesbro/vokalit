"""VoxCPM2 worker for Vokalit. Protocol: SPEC.md §5.2.

python worker.py             serve requests on stdin/stdout (offline, network blocked)
python worker.py --download  download the model weights (used by Install)

VoxCPM2 clones the voice from the sample alone (reference_wav_path), the mode in which a style instruction written in
parentheses at the start of the text steers how it is said. The denoiser and the text normalizer stay off: the
denoiser is another model that would need a download, and the normalizer is made for Chinese and English.
"""
import json
import re
import socket
import sys
import time

MODEL = "openbmb/VoxCPM2"


def block_network():
    """Blocks connections, sends and name lookups. The socket class itself stays, since libraries
    (e.g. ssl) subclass it when they are imported."""

    def blocked(*args, **kwargs):
        raise RuntimeError("Network access is blocked in Vokalit workers (SPEC.md §5.3).")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    socket.getaddrinfo = blocked


def prompt(text, style):
    """The text VoxCPM2 gets: "(style)text". Parentheses in the line itself become commas, since the model would
    take a parenthesised part as an instruction and not say it."""
    text = re.sub(r"\s*\)\s*", ", ", re.sub(r"\(\s*", "", text))
    text = re.sub(r"\s*,(\s*,)+", ",", text)
    text = re.sub(r",\s*([.!?;:])", r"\1", text).strip(" ,")
    return f"({style}){text}" if style else text


def _out_of_memory(error):
    """torch.cuda.OutOfMemoryError (and the same text from libraries that wrap it)."""
    return "out of memory" in str(error).lower()


def main():
    if "--download" in sys.argv:
        from voxcpm import VoxCPM

        # On the CPU and without compiling: the GPU may be busy with other models while this one installs.
        VoxCPM.from_pretrained(MODEL, load_denoiser=False, device="cpu", optimize=False)
        return

    block_network()  # before any library is imported
    reply = sys.stdout
    sys.stdout = sys.stderr  # library prints must not mix with protocol replies

    def send(**message):
        reply.write(json.dumps(message) + "\n")
        reply.flush()

    import soundfile as sf
    import torch
    from voxcpm import VoxCPM

    if not torch.cuda.is_available():
        send(ready=False, error="No NVIDIA GPU with CUDA was found.")
        return
    try:
        model = VoxCPM.from_pretrained(MODEL, load_denoiser=False)
    except Exception as error:  # e.g. no room on the GPU: the app makes room and tries again
        send(ready=False, error=str(error), oom=_out_of_memory(error))
        return
    send(ready=True, vram_gb=round(torch.cuda.memory_reserved() / 1e9, 2))

    for line in sys.stdin:
        request = json.loads(line)
        try:
            start = time.perf_counter()
            if request.get("seed") is not None:
                torch.manual_seed(request["seed"])
            settings = request.get("settings", {})
            # The line's language is not passed: VoxCPM2 reads it from the text.
            # A voice design request has a description and no reference: it goes where a style would.
            style = request.get("description") or settings.get("style", "")
            audio = model.generate(text=prompt(request["text"], style),
                                   reference_wav_path=request.get("ref"),
                                   cfg_value=settings.get("cfg_value", 2.0),
                                   inference_timesteps=int(settings.get("inference_timesteps", 10)),
                                   normalize=False, denoise=False)
            # 16-bit PCM at the model's own rate (48 kHz); export joins it with 24 kHz takes.
            sf.write(request["out"], audio, model.tts_model.sample_rate, subtype="PCM_16")
            send(ok=True, out=request["out"], seconds=round(time.perf_counter() - start, 1),
                 vram_gb=round(torch.cuda.memory_reserved() / 1e9, 2))  # shown on the Models screen
        except Exception as error:
            if _out_of_memory(error):  # recoverable: free the cache and let the app make room
                if hasattr(torch.cuda, "empty_cache"):
                    torch.cuda.empty_cache()
                send(ok=False, error=str(error), oom=True)
                continue
            # A CUDA error leaves the GPU context unusable for the rest of this process. Report it and exit; the app
            # starts a fresh worker.
            if "CUDA" in str(error) or "device-side assert" in str(error):
                send(ok=False, error=str(error), restart=True)
                sys.exit(1)
            send(ok=False, error=str(error))


if __name__ == "__main__":
    main()
