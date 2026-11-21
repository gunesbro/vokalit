"""OmniVoice worker for Vokalit. Protocol: SPEC.md §5.2.

python worker.py             serve requests on stdin/stdout (offline, network blocked)
python worker.py --download  download the model weights (used by Install)

OmniVoice would load its own Whisper when a reference comes without its transcript; Vokalit always sends the
sample's transcript, so that never happens (and could not: the network is blocked).
"""
import contextlib
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


def guidance_weights(accent):
    """The guidance weights (reference, text) for "Native accent" 0-1, or None when it is off. OmniVoice's own guidance
    (guidance_scale 2) is (3, 3); 1 is (2, 5), the dubbing setting the Accent Analogy Guidance paper (arXiv 2609.29123)
    found more native at some cost in likeness to the sample."""
    if not accent or accent <= 0:
        return None
    x = min(float(accent), 1.0)
    return (round(3 - x, 3), round(3 + 2 * x, 3))


def dual_guidance(c, u, t, a_s, a_t):
    """Classifier-free guidance with separate weights: unconditional u, text only t, text and reference c (log-probs).
    A lower reference weight and a higher text weight take less of the sample's accent."""
    return u + a_t * (t - u) + a_s * (c - t)


@contextlib.contextmanager
def accent_guidance(model, weights):
    """For one generate call, OmniVoice's guidance with separate reference and text weights (dual_guidance): its input
    preparation also builds the text alone (no reference), its forward pass also predicts from that, and its token
    choice mixes the three. Built on OmniVoice 0.2.1's internals; one text per call (dub and Studio lines), else its
    own guidance."""
    if weights is None:
        yield
        return
    prepare, forward, predict = model._prepare_inference_inputs, model.forward, model._predict_tokens_with_scoring
    held = {}

    def prepare_also_text(text, num_target_tokens, ref_text=None, ref_audio_tokens=None, lang=None, instruct=None,
                          denoise=True):
        inputs = prepare(text, num_target_tokens, ref_text, ref_audio_tokens, lang, instruct, denoise)
        if ref_audio_tokens is not None:  # the same text, language and style, without the reference
            alone = prepare(text, num_target_tokens, None, None, lang, instruct, denoise)
            held["prefix"] = alone["input_ids"][..., :-num_target_tokens]
        else:  # never another text's prefix
            held.pop("prefix", None)
        return inputs

    def forward_also_text(*args, **kwargs):
        import torch

        output = forward(*args, **kwargs)
        held.pop("text", None)
        ids, mask = kwargs.get("input_ids"), kwargs.get("audio_mask")
        if "prefix" in held and ids is not None and mask is not None and ids.size(0) == 2:
            length = int(mask[1].sum())  # the unconditional row holds just the target tokens so far
            whole = torch.cat([held["prefix"], ids[1:2, :, :length]], dim=2)
            size = whole.size(2)
            audio = torch.zeros(1, size, dtype=torch.bool, device=whole.device)
            audio[0, size - length:] = True
            attention = torch.ones(1, 1, size, size, dtype=torch.bool, device=whole.device)
            logits = forward(input_ids=whole, audio_mask=audio, attention_mask=attention).logits.to(torch.float32)
            held["text"] = logits[:, :, size - length:, :]
        return output

    def predict_mixed(c_logits, u_logits, gen_config):
        import torch.nn.functional as F

        text = held.get("text")
        if text is None or text.shape != c_logits.shape:  # a batch of several texts: OmniVoice's own guidance
            return predict(c_logits, u_logits, gen_config)
        mixed = dual_guidance(F.log_softmax(c_logits, dim=-1), F.log_softmax(u_logits, dim=-1),
                              F.log_softmax(text, dim=-1), *weights)
        held["mixed"] = held.get("mixed", 0) + 1
        return predict(mixed, mixed, gen_config)  # equal inputs: its own guidance adds nothing, the rest is the same
    predict_mixed.weights = weights

    names = ("_prepare_inference_inputs", "forward", "_predict_tokens_with_scoring")
    before = {name: model.__dict__[name] for name in names if name in model.__dict__}  # e.g. a loader's own hooks
    model._prepare_inference_inputs = prepare_also_text
    model.forward = forward_also_text
    model._predict_tokens_with_scoring = predict_mixed
    try:
        yield
    finally:  # exactly what the model had
        for name in names:
            if name in before:
                setattr(model, name, before[name])
            else:
                model.__dict__.pop(name, None)
    if not held.get("mixed"):  # OmniVoice decoded some other way: say so rather than ignore the setting
        raise RuntimeError("Native accent could not be applied: this OmniVoice version works differently. "
                           "Set Native accent to 0.")


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
            # "Native accent": less of the sample's accent when it is in another language than the line.
            guided = accent_guidance(model, guidance_weights(settings.get("accent")) if request.get("ref") else None)
            with guided:
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
