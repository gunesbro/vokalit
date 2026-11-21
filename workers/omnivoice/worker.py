"""OmniVoice worker for Vokalit. Protocol: SPEC.md §5.2.

python worker.py             serve requests on stdin/stdout (offline, network blocked)
python worker.py --download  download the model weights (used by Install)

OmniVoice would load its own Whisper when a reference comes without its transcript; Vokalit always sends the
sample's transcript, so that never happens (and could not: the network is blocked).
"""
import contextlib
import json
import os
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


def guidance_plan(accent, removal):
    """(reference weight, text weight, accent removal) for "Native accent" and "Accent removal", or None for OmniVoice's
    own guidance. Removal keeps the sample's weight (its mood) and takes the accent out instead (Accent Analogy
    Guidance, arXiv 2609.29123: (3, 5, 5) on OmniVoice); Native accent lowers the sample's weight."""
    weights = guidance_weights(accent) or (3.0, 3.0)
    if removal and removal > 0:
        return (weights[0], max(5.0, weights[1]), removal)
    return None if weights == (3.0, 3.0) else (*weights, 0)


def aag_mix(c, u, t, sources, targets, a_s, a_t, beta):
    """dual_guidance minus the accent direction: for each proxy voice, its prediction with a sample in the original's
    language minus with a sample in the line's language (the voice cancels, the accent remains), averaged, times beta."""
    mixed = dual_guidance(c, u, t, a_s, a_t)
    if beta and sources:
        mixed = mixed - beta / len(sources) * sum(src - tgt for src, tgt in zip(sources, targets))
    return mixed


@contextlib.contextmanager
def accent_guidance(model, plan, proxies=()):
    """For one generate call, OmniVoice's guidance as `plan` (guidance_plan) asks: its input preparation also builds
    the text alone and, for accent removal, the text with each proxy voice's two samples (`proxies`: [(prompt in the
    original's language, prompt in the line's)]); its forward pass also predicts those, in one padded batch; its token
    choice mixes them (aag_mix). Built on OmniVoice 0.2.1's internals; one text per call (dub and Studio lines), else
    its own guidance. Raises when the guidance was never applied, rather than ignore the setting."""
    if plan is None:
        yield
        return
    a_s, a_t, beta = plan
    proxies = list(proxies) if beta else []
    prepare, forward, predict = model._prepare_inference_inputs, model.forward, model._predict_tokens_with_scoring
    held = {}

    def prepare_also_branches(text, num_target_tokens, ref_text=None, ref_audio_tokens=None, lang=None, instruct=None,
                              denoise=True):
        inputs = prepare(text, num_target_tokens, ref_text, ref_audio_tokens, lang, instruct, denoise)
        if ref_audio_tokens is None:  # never another text's branches
            held.pop("prefixes", None)
            return inputs
        cut = lambda tokens, ref: prepare(text, num_target_tokens, getattr(ref, "ref_text", None),  # noqa: E731
                                          getattr(ref, "ref_audio_tokens", None), lang, instruct,
                                          denoise)["input_ids"][..., :-num_target_tokens]
        prefixes = [cut(None, None)]  # the same text, language and style, without a sample
        for source, target in proxies:
            prefixes += [cut(None, source), cut(None, target)]
        held["prefixes"] = prefixes
        held["length"] = num_target_tokens
        return inputs

    def forward_also_branches(*args, **kwargs):
        import torch

        held.pop("branches", None)
        output = forward(*args, **kwargs)
        ids = kwargs.get("input_ids")
        if "prefixes" in held and ids is not None and ids.size(0) == 2:
            length, prefixes = held["length"], held["prefixes"]
            target = ids[1:2, :, :length]  # the unconditional row holds just the target tokens so far
            sizes = [p.size(2) + length for p in prefixes]
            size, rows = max(sizes), len(prefixes)
            batch = torch.full((rows, ids.size(1), size), model.config.audio_mask_id, dtype=ids.dtype, device=ids.device)
            audio = torch.zeros(rows, size, dtype=torch.bool, device=ids.device)
            attention = torch.zeros(rows, 1, size, size, dtype=torch.bool, device=ids.device)
            for k, (prefix, end) in enumerate(zip(prefixes, sizes)):  # left-aligned, padded as OmniVoice pads
                batch[k, :, :end] = torch.cat([prefix, target], dim=2)[0]
                audio[k, end - length:end] = True
                attention[k, :, :end, :end] = True
                if end < size:
                    pad = torch.arange(end, size, device=ids.device)
                    attention[k, :, pad, pad] = True
            logits = forward(input_ids=batch, audio_mask=audio, attention_mask=attention).logits.to(torch.float32)
            held["branches"] = [logits[k:k + 1, :, end - length:end, :] for k, end in enumerate(sizes)]
        return output

    def predict_mixed(c_logits, u_logits, gen_config):
        import torch.nn.functional as F

        branches = held.get("branches")
        if not branches or any(b.shape != c_logits.shape for b in branches):  # several texts: its own guidance
            return predict(c_logits, u_logits, gen_config)
        lp = lambda x: F.log_softmax(x, dim=-1)  # noqa: E731
        text, pairs = lp(branches[0]), branches[1:]
        mixed = aag_mix(lp(c_logits), lp(u_logits), text, [lp(b) for b in pairs[0::2]], [lp(b) for b in pairs[1::2]],
                        a_s, a_t, beta)
        held["mixed"] = held.get("mixed", 0) + 1
        return predict(mixed, mixed, gen_config)  # equal inputs: its own guidance adds nothing, the rest is the same
    predict_mixed.weights = (a_s, a_t) if not beta else (a_s, a_t, beta)

    names = ("_prepare_inference_inputs", "forward", "_predict_tokens_with_scoring")
    before = {name: model.__dict__[name] for name in names if name in model.__dict__}  # e.g. a loader's own hooks
    model._prepare_inference_inputs = prepare_also_branches
    model.forward = forward_also_branches
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
                           "Set Native accent and Accent removal to 0.")


_prompts = {}  # (path, modified, text) -> voice clone prompt: the accent voices are the same for every line of a dub


def _prompt(model, path, text):
    key = (path, os.path.getmtime(path), text)
    if key not in _prompts:
        if len(_prompts) > 16:
            _prompts.clear()
        _prompts[key] = model.create_voice_clone_prompt(path, text)
    return _prompts[key]


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
            # "Native accent" and "Accent removal": less of the sample's accent when it is in another language than
            # the line. Removal needs the dub's accent voices (proxies); without them (Studio) it is off.
            proxies = [(_prompt(model, p["src"], p["src_text"]), _prompt(model, p["tgt"], p["tgt_text"]))
                       for p in request.get("proxies") or []]
            plan = guidance_plan(settings.get("accent"), settings.get("accent_removal") if proxies else 0)
            guided = accent_guidance(model, plan if request.get("ref") else None, proxies)
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
