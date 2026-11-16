"""Chatterbox Multilingual worker for Vokalit. Protocol: SPEC.md §5.2.

python worker.py             serve requests on stdin/stdout (offline, network blocked)
python worker.py --download  download the model weights (used by Install)
"""
import json
import socket
import sys
import time

LANGUAGE = "tr"


def block_network():
    def blocked(*args, **kwargs):
        raise RuntimeError("Network access is blocked in Vokalit workers (SPEC.md §5.3).")

    socket.socket = blocked


def main():
    if "--download" in sys.argv:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        ChatterboxMultilingualTTS.from_pretrained(device="cpu")
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
    send(ready=True)

    for line in sys.stdin:
        request = json.loads(line)
        try:
            start = time.perf_counter()
            # No reference means the model's built-in default voice.
            wav = model.generate(request["text"], language_id=LANGUAGE, audio_prompt_path=request.get("ref"))
            sf.write(request["out"], wav.squeeze(0).cpu().numpy(), model.sr)
            send(ok=True, out=request["out"], seconds=round(time.perf_counter() - start, 1))
        except Exception as error:
            send(ok=False, error=str(error))


if __name__ == "__main__":
    main()
