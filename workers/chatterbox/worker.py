"""Chatterbox Multilingual worker for Vokalit. Protocol: SPEC.md §5.2.

python worker.py             serve requests on stdin/stdout (offline, network blocked)
python worker.py --download  download the model weights (used by Install)
"""
import json
import socket
import sys
import time

def block_network():
    """Blocks connections, sends and name lookups. The socket class itself stays, since libraries
    (e.g. ssl) subclass it when they are imported."""

    def blocked(*args, **kwargs):
        raise RuntimeError("Network access is blocked in Vokalit workers (SPEC.md §5.3).")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    socket.getaddrinfo = blocked


def main():
    if "--download" in sys.argv:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        from chatterbox.vc import ChatterboxVC

        ChatterboxMultilingualTTS.from_pretrained(device="cpu")
        ChatterboxVC.from_pretrained(device="cpu")
        return

    block_network()  # before any library is imported
    reply = sys.stdout
    sys.stdout = sys.stderr  # library prints must not mix with protocol replies

    def send(**message):
        reply.write(json.dumps(message) + "\n")
        reply.flush()

    import soundfile as sf
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    if not torch.cuda.is_available():
        send(ready=False, error="No NVIDIA GPU with CUDA was found.")
        return
    model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
    # Cloning replaces model.conds (the active voice); keep the built-in voice to restore it.
    default_conds = model.conds
    send(ready=True)

    vc = None  # the conversion model loads on the first convert request

    for line in sys.stdin:
        request = json.loads(line)
        try:
            start = time.perf_counter()
            if request.get("task", "tts") == "convert":
                if vc is None:
                    from chatterbox.vc import ChatterboxVC

                    vc = ChatterboxVC.from_pretrained(device="cuda")
                wav = vc.generate(audio=request["source"], target_voice_path=request.get("ref"))
                sample_rate = vc.sr
            else:
                if request.get("seed") is not None:
                    torch.manual_seed(request["seed"])
                if not request.get("ref"):
                    model.conds = default_conds  # otherwise the last cloned voice would be used
                wav = model.generate(request["text"], language_id=request.get("language", "tr"),
                                     audio_prompt_path=request.get("ref"),
                                     **request.get("settings", {}))
                sample_rate = model.sr
            # 16-bit PCM so the app can join takes with the standard wave module.
            sf.write(request["out"], wav.squeeze(0).cpu().numpy(), sample_rate, subtype="PCM_16")
            send(ok=True, out=request["out"], seconds=round(time.perf_counter() - start, 1))
        except Exception as error:
            send(ok=False, error=str(error))


if __name__ == "__main__":
    main()
