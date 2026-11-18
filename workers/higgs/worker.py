"""Higgs TTS 3 worker for Vokalit. Protocol: SPEC.md §5.2.

python worker.py             serve requests on stdin/stdout (offline, network blocked)
python worker.py --download  download the model and its codec (used by Install)

The model is a transformers packaging of Boson AI's weights whose code comes from the Hub (trust_remote_code). It
and its codec are pinned to commits (HIGGS_* in the environment, set by app/models.py) and loaded from the cache only.
Tags arrive already in Higgs's syntax (<|emotion:anger|>, <|sfx:cough|>Ahem, ...): app/models.py converts them.
"""
import json
import os
import socket
import sys
import time

PORT, PORT_REVISION = os.environ.get("HIGGS_PORT"), os.environ.get("HIGGS_PORT_REVISION")
CODEC, CODEC_REVISION = os.environ.get("HIGGS_CODEC"), os.environ.get("HIGGS_CODEC_REVISION")
BF16_NEEDS_GB = 10.7  # measured peak 9.66 GB at bf16, plus room; with less free memory it loads in 8-bit
TOP_P = 0.95


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


def load(torch):
    """The model at bf16 when the GPU has room for it, otherwise in 8-bit (about a third of the speed). Its codec is
    loaded here at the pinned commit; the model would otherwise fetch it from the Hub on first use.
    Returns (model, tokenizer, mode); mode says which was chosen and why, for the Models screen."""
    from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    free_gb = torch.cuda.mem_get_info()[0] / 1e9
    options = dict(revision=PORT_REVISION, local_files_only=True, trust_remote_code=True, dtype=torch.bfloat16)
    if free_gb >= BF16_NEEDS_GB:
        model = AutoModelForCausalLM.from_pretrained(PORT, **options).to("cuda").eval()
        mode = {"label": "Full precision",
                "reason": f"{free_gb:.1f} GB was free on loading, enough for full precision (the faster mode)."}
    else:
        model = AutoModelForCausalLM.from_pretrained(
            PORT, **options, quantization_config=BitsAndBytesConfig(load_in_8bit=True), device_map="cuda").eval()
        mode = {"label": "8-bit",
                "reason": f"8-bit: only {free_gb:.1f} GB was free on loading (full precision needs {BF16_NEEDS_GB} GB). "
                          "About 3\u00d7 slower; close other apps and Unload to load in full precision."}
    codec = AutoModel.from_pretrained(CODEC, revision=CODEC_REVISION, local_files_only=True, dtype=torch.float32,
                                      trust_remote_code=True)
    model._audio_codec = codec.to(model.device).eval()
    tokenizer = AutoTokenizer.from_pretrained(PORT, revision=PORT_REVISION, local_files_only=True)
    return model, tokenizer, mode


def main():
    if "--download" in sys.argv:
        from huggingface_hub import snapshot_download

        snapshot_download(PORT, revision=PORT_REVISION)
        snapshot_download(CODEC, revision=CODEC_REVISION)
        return

    block_network()  # before any library is imported
    reply = sys.stdout
    sys.stdout = sys.stderr  # library prints must not mix with protocol replies

    def send(**message):
        reply.write(json.dumps(message) + "\n")
        reply.flush()

    import soundfile as sf
    import torch

    if not torch.cuda.is_available():
        send(ready=False, error="No NVIDIA GPU with CUDA was found.")
        return
    try:
        model, tokenizer, mode = load(torch)
    except Exception as error:  # e.g. no room on the GPU: the app makes room and tries again
        send(ready=False, error=str(error), oom=_out_of_memory(error))
        return
    send(ready=True, vram_gb=round(torch.cuda.memory_reserved() / 1e9, 2), mode=mode)

    for line in sys.stdin:
        request = json.loads(line)
        try:
            start = time.perf_counter()
            if request.get("seed") is not None:
                torch.manual_seed(request["seed"])
            reference = {}
            if request.get("ref"):
                audio, rate = sf.read(request["ref"], dtype="float32", always_2d=True)
                reference = dict(reference_audio=torch.from_numpy(audio.mean(axis=1)), reference_sample_rate=rate,
                                 reference_text=request.get("ref_text"))
            # The line's language is not passed: Higgs reads it from the text.
            wav = model.generate_speech(request["text"], tokenizer, **reference,
                                        temperature=request.get("settings", {}).get("temperature", 0.7), top_p=TOP_P)
            audio = wav.float().cpu().numpy().reshape(-1).clip(-1, 1)
            sf.write(request["out"], audio, model.config.sample_rate, subtype="PCM_16")
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
