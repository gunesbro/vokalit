"""Whisper worker for Vokalit: writes down what a voice sample says. Protocol: SPEC.md §5.2.

python worker.py             serve requests on stdin/stdout (offline, network blocked)
python worker.py --download  download the model (used by Install)

Runs faster-whisper on the CPU with int8 weights: no PyTorch, and the GPU stays free for the voice models.
"""
import json
import socket
import sys
import time

MODEL = "large-v3-turbo"


def block_network():
    """Blocks connections, sends and name lookups (same as the voice model workers)."""

    def blocked(*args, **kwargs):
        raise RuntimeError("Network access is blocked in Vokalit workers (SPEC.md §5.3).")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    socket.getaddrinfo = blocked


def load():
    from faster_whisper import WhisperModel

    return WhisperModel(MODEL, device="cpu", compute_type="int8")


def main():
    if "--download" in sys.argv:
        load()
        return

    block_network()  # before any library is imported
    reply = sys.stdout
    sys.stdout = sys.stderr  # library prints must not mix with protocol replies

    def send(**message):
        reply.write(json.dumps(message) + "\n")
        reply.flush()

    model = load()
    send(ready=True)
    for line in sys.stdin:
        request = json.loads(line)
        try:
            start = time.perf_counter()
            segments, _ = model.transcribe(request["audio"], language=request.get("language"), beam_size=5)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            send(ok=True, text=text, seconds=round(time.perf_counter() - start, 1))
        except Exception as error:
            send(ok=False, error=str(error))


if __name__ == "__main__":
    main()
