"""OmniVoice worker for Vokalit. Protocol: SPEC.md §5.2.

python worker.py             serve requests on stdin/stdout (offline, network blocked)
python worker.py --download  download the model weights (used by Install)

OmniVoice would load its own Whisper when a reference comes without its transcript; Vokalit always sends the
sample's transcript, so that never happens (and could not: the network is blocked).
"""
import json
import socket
import sys
import time

MODEL = "k2-fsa/OmniVoice"
SAMPLE_RATE = 24000


def block_network():
    """Blocks connections, sends and name lookups. The socket class itself stays, since libraries
    (e.g. ssl) subclass it when they are imported."""

    def blocked(*args, **kwargs):
        raise RuntimeError("Network access is blocked in Vokalit workers (SPEC.md §5.3).")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    socket.getaddrinfo = blocked


def _out_of_memory(error):
    """torch.cuda.OutOfMemoryError (and the same text from libraries that wrap it)."""
    return "out of memory" in str(error).lower()


def timed_duration(timing, natural, speed=1.0):
    """The length to generate a dub take to: the target (where its speaker stops), but no more than max_speed faster
    or min_speed slower than its natural pace (`natural` seconds, divided by the speed setting). No estimate: None,
    its natural length."""
    pace = natural / speed
    if pace <= 0:
        return None
    return round(min(max(timing["target"], pace / timing["max_speed"]), pace / timing["min_speed"]), 2)


def _natural_seconds(model, text, prompt):
    """How long OmniVoice would speak `text` in the reference's pace, as it estimates when given no duration: from
    the prompt's tokens (the reference once its silence is removed) and text, in tokens (its boost for short texts is
    set in tokens)."""
    frame_rate = model.audio_tokenizer.config.frame_rate
    tokens = model.duration_estimator.estimate_duration(text, prompt.ref_text, prompt.ref_audio_tokens.size(-1))
    return tokens / frame_rate


def main():
    if "--download" in sys.argv:
        import torch
        from omnivoice import OmniVoice

        OmniVoice.from_pretrained(MODEL, device_map="cpu", dtype=torch.float32)
        return

    block_network()  # before any library is imported
    reply = sys.stdout
    sys.stdout = sys.stderr  # library prints must not mix with protocol replies

    def send(**message):
        reply.write(json.dumps(message) + "\n")
        reply.flush()

    import soundfile as sf
    import torch
    from omnivoice import OmniVoice

    if not torch.cuda.is_available():
        send(ready=False, error="No NVIDIA GPU with CUDA was found.")
        return
    try:
        model = OmniVoice.from_pretrained(MODEL, device_map="cuda:0", dtype=torch.float16)
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
            # Without a reference OmniVoice picks a random voice (repeatable with a seed), or designs one from the
            # description's attributes ("female, low pitch"; checked by the app).
            designed = request.get("description") and not request.get("ref")
            options = {"instruct": request["description"]} if designed else {}
            reference = {"ref_audio": request.get("ref"), "ref_text": request.get("ref_text")}
            pace = None
            if request.get("timing") and request.get("ref") and request.get("ref_text"):
                # A dub take, as long as its speaker speaks. The prompt is what OmniVoice clones from (the reference
                # without its silence), so the natural length is estimated as it would be.
                prompt = model.create_voice_clone_prompt(request["ref"], request["ref_text"])
                natural = _natural_seconds(model, request["text"], prompt)
                duration = timed_duration(request["timing"], natural, settings.get("speed", 1.0))
                if duration:
                    reference = {"voice_clone_prompt": prompt}
                    # No silence added around it: the take lasts what was asked.
                    options.update(duration=duration, pad_duration=0)
                    pace = round(natural / duration, 2)
            audio = model.generate(text=request["text"], language=request.get("language"), **reference,
                                   speed=settings.get("speed", 1.0), num_step=int(settings.get("num_step", 32)),
                                   **options)
            # 16-bit PCM so the app can join takes with the standard wave module.
            sf.write(request["out"], audio[0], SAMPLE_RATE, subtype="PCM_16")
            send(ok=True, out=request["out"], seconds=round(time.perf_counter() - start, 1),
                 vram_gb=round(torch.cuda.memory_reserved() / 1e9, 2),  # shown on the Models screen
                 **({"pace": pace} if pace else {}))
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
