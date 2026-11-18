r"""Throwaway check for Higgs TTS 3 (.superpowers/plans/2026-11-18-higgs.md, Task 0). Run from the repo root with
Vokalit closed. On Windows, double-click scripts\spike_higgs.bat: it picks a Turkish sample of one of your library
characters, with its transcript. Or pass a sample yourself:

    $env:UV_PYTHON_INSTALL_DIR="$PWD\.local\python"; .\.local\uv\uv.exe run --python 3.11 scripts\spike_higgs.py C:\path\to\sample.wav --transcript "what the sample says"

Needs the internet. It installs PyTorch (from the shared cache), transformers and bitsandbytes into
.local/spike-higgs/ and downloads the model (about 10 GB) there. Then it blocks the network and writes test files to
.local/spike-higgs/out/: bf16 first, then 8-bit in out/8bit/. Prints one JSON report, also saved as
out/report.json. Delete .local/spike-higgs/ afterwards, after installing the real model.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_OWN_UV = os.path.join(ROOT, ".local", "uv", "uv.exe" if sys.platform == "win32" else "uv")
UV = os.environ.get("VOKALIT_UV") or (_OWN_UV if os.path.exists(_OWN_UV) else None) or shutil.which("uv") or "uv"
WORK = os.path.join(ROOT, ".local", "spike-higgs")
OUT = os.path.join(WORK, "out")
PORT = "multimodalart/higgs-audio-v3-tts-4b-transformers"
CODEC = "bosonai/higgs-audio-v2-tokenizer"
TORCH_CUDA = ["torch==2.8.0", "torchaudio==2.8.0", "--index-url", "https://download.pytorch.org/whl/cu128"]  # app/models.py
LIBRARIES = ["transformers>=5.5", "accelerate", "soundfile", "bitsandbytes"]

FIRST = "Bunu yapmam\u0131 beklemiyordum,"
SECOND = "ger\u00e7ekten \u00e7ok \u015fa\u015f\u0131rd\u0131m."
SENTENCE = f"{FIRST} {SECOND}"
EMOTIONS = ["elation", "amusement", "enthusiasm", "determination", "pride", "contentment", "affection", "relief",
            "contemplation", "confusion", "surprise", "awe", "longing", "arousal", "anger", "fear", "disgust",
            "bitterness", "sadness", "shame", "helplessness"]
STYLES = ["singing", "shouting", "whispering"]
SFX = {"cough": "Ahem", "laughter": "Haha", "crying": "Boohoo", "screaming": "Aaah", "burping": "Burp",
       "humming": "Hmm", "sigh": "Ahh", "sniff": "Sff", "sneeze": "Achoo"}  # onomatopoeia from the model card
PROSODY_START = ["speed_very_slow", "speed_slow", "speed_fast", "speed_very_fast", "pitch_low", "pitch_high",
                 "expressive_high", "expressive_low"]
PROSODY_INLINE = ["pause", "long_pause"]


def venv_python():
    venv = os.path.join(WORK, "venv")
    return os.path.join(venv, "Scripts", "python.exe") if sys.platform == "win32" else os.path.join(venv, "bin", "python")


def run(args, env):
    result = subprocess.run(args, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    return result.returncode, result.stdout + result.stderr


def folder_gb(path):
    seen, total = set(), 0
    for folder, _, names in os.walk(path):
        for name in names:
            try:
                st = os.stat(os.path.join(folder, name))
            except OSError:
                continue
            if (st.st_dev, st.st_ino) not in seen or st.st_ino == 0:
                seen.add((st.st_dev, st.st_ino))
                total += st.st_size
    return round(total / 1e9, 2)


def block_network():
    """As in the workers: no connections, sends or name lookups."""
    import socket

    def blocked(*args, **kwargs):
        raise RuntimeError("Network access is blocked (spike).")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    socket.getaddrinfo = blocked


def child_download():
    from huggingface_hub import HfApi, snapshot_download

    report = {}
    try:
        report["port_sha"] = HfApi().model_info(PORT).sha
        snapshot_download(PORT, revision=report["port_sha"])
        report["codec_sha"] = HfApi().model_info(CODEC).sha
        snapshot_download(CODEC, revision=report["codec_sha"])
    except Exception as error:
        text = f"{type(error).__name__}: {error}"
        report["gated"] = "gated" in text.lower() or "401" in text or "403" in text
        report["download_error"] = text[:1500]
    print("REPORT " + json.dumps(report))


def _texts():
    runs = [("a_plain", SENTENCE)]
    runs += [(f"b_{e}", f"<|emotion:{e}|>{SENTENCE}") for e in EMOTIONS]
    runs += [(f"c_{s}", f"<|style:{s}|>{SENTENCE}") for s in STYLES]
    runs.append(("d_mid", f"<|emotion:sadness|>{FIRST} <|emotion:elation|>{SECOND}"))
    runs += [(f"e_{name}", f"{FIRST} <|sfx:{name}|>{word} {SECOND}") for name, word in SFX.items()]
    runs.append(("e_laughter_bare", f"{FIRST} <|sfx:laughter|> {SECOND}"))
    runs += [(f"f_{p}", f"<|prosody:{p}|>{SENTENCE}") for p in PROSODY_START]
    runs += [(f"f_{p}", f"{FIRST} <|prosody:{p}|>{SECOND}") for p in PROSODY_INLINE]
    return runs


def child_generate(sample, transcript, sha, codec_sha, mode):
    block_network()
    import inspect

    import numpy as np
    import soundfile as sf
    import torch
    from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer

    report = {"mode": mode, "torch": torch.__version__}
    folder = OUT if mode == "bf16" else os.path.join(OUT, "8bit")
    os.makedirs(folder, exist_ok=True)
    start = time.perf_counter()
    try:
        tokenizer = AutoTokenizer.from_pretrained(PORT, revision=sha, local_files_only=True)
        if mode == "bf16":
            model = AutoModelForCausalLM.from_pretrained(PORT, revision=sha, local_files_only=True,
                                                         trust_remote_code=True, dtype=torch.bfloat16).to("cuda").eval()
        else:
            from transformers import BitsAndBytesConfig

            model = AutoModelForCausalLM.from_pretrained(PORT, revision=sha, local_files_only=True,
                                                         trust_remote_code=True, dtype=torch.bfloat16,
                                                         quantization_config=BitsAndBytesConfig(load_in_8bit=True),
                                                         device_map="cuda").eval()
        # The port loads its codec lazily from the Hub's "main", which is not in an offline cache downloaded by
        # commit: load it here at its pinned commit and hand it over.
        codec = AutoModel.from_pretrained(CODEC, revision=codec_sha, local_files_only=True, dtype=torch.float32,
                                          trust_remote_code=True)
        model._audio_codec = codec.to(model.device).eval()
    except Exception as error:
        import traceback

        report["load_error"] = f"{type(error).__name__}: {error}"[:1500]
        report["load_traceback"] = traceback.format_exc()[-2500:]
        report["oom"] = "out of memory" in str(error).lower()
        print("REPORT " + json.dumps(report))
        return
    report["load_seconds"] = round(time.perf_counter() - start, 1)
    report["vram_after_load_gb"] = round(torch.cuda.max_memory_reserved() / 1e9, 2)
    report["generate_speech_signature"] = str(inspect.signature(model.generate_speech))
    rate = model.config.sample_rate
    report["sample_rate"] = rate
    audio, ref_rate = sf.read(sample, dtype="float32", always_2d=True)
    reference = torch.from_numpy(audio.mean(axis=1))

    runs = _texts() if mode == "bf16" else [r for r in _texts() if r[0] in ("a_plain", "b_anger", "b_sadness")]
    files = []
    for name, text in runs:
        torch.manual_seed(0)
        start = time.perf_counter()
        try:
            wav = model.generate_speech(text, tokenizer, reference_audio=reference, reference_sample_rate=ref_rate,
                                        reference_text=transcript, temperature=0.7, top_p=0.95)
            wav = np.asarray(wav.float().cpu() if hasattr(wav, "cpu") else wav, dtype="float32").reshape(-1)
            sf.write(os.path.join(folder, f"{name}.wav"), np.clip(wav, -1, 1), rate, subtype="PCM_16")
            files.append({"file": name, "seconds": round(time.perf_counter() - start, 1),
                          "duration": round(len(wav) / rate, 1)})
        except Exception as error:
            import traceback

            files.append({"file": name, "error": f"{type(error).__name__}: {error}"[:400]})
            if len(files) == 1:
                report["first_traceback"] = traceback.format_exc()[-2500:]
            if "out of memory" in str(error).lower():
                report["oom"] = True
                break
    report["files"] = files
    report["vram_peak_gb"] = round(torch.cuda.max_memory_reserved() / 1e9, 2)
    print("REPORT " + json.dumps(report, ensure_ascii=True))


def pick_sample():
    """A library character's Turkish sample, preferring one with a transcript. (path, transcript)"""
    found = []
    root = os.path.join(ROOT, "workspace", "characters")
    for char_id in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        try:
            with open(os.path.join(root, char_id, "character.json"), encoding="utf-8") as f:
                samples = json.load(f).get("samples", [])
        except (OSError, ValueError):
            continue
        for sample in samples:
            path = os.path.join(root, char_id, sample["file"])
            if os.path.exists(path):
                rank = (sample.get("language") == "tr", bool(sample.get("transcript")), sample.get("duration", 0) <= 30)
                found.append((rank, path, sample.get("transcript")))
    if not found:
        return None, None
    _, path, transcript = max(found, key=lambda item: item[0])
    return path, transcript


def _child_report(log):
    lines = [line for line in log.splitlines() if line.startswith("REPORT ")]
    return json.loads(lines[-1][len("REPORT "):]) if lines else None


def main():
    parser = argparse.ArgumentParser(description="Higgs TTS 3 spike for Vokalit (see the docstring).")
    parser.add_argument("sample", nargs="?", help="a Turkish voice sample (.wav); default: one from your workspace")
    parser.add_argument("--transcript", help="what the sample says")
    parser.add_argument("--child", choices=["download", "bf16", "8bit"], help=argparse.SUPPRESS)
    parser.add_argument("--sha", help=argparse.SUPPRESS)
    parser.add_argument("--codec-sha", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child == "download":
        return child_download()
    if args.child:
        return child_generate(args.sample, args.transcript, args.sha, args.codec_sha, args.child)

    if args.sample:
        sample = os.path.abspath(args.sample)
    else:
        sample, args.transcript = pick_sample()
        if not sample:
            return print("No voice sample found in workspace/characters. Pass one: spike_higgs.py sample.wav")
    print(f"[spike] sample: {sample} (transcript: {'yes' if args.transcript else 'no'})", flush=True)
    os.makedirs(OUT, exist_ok=True)
    env = dict(os.environ, UV_CACHE_DIR=os.path.join(ROOT, ".local", "shared", "uv-cache"), UV_LINK_MODE="hardlink",
               UV_PYTHON_INSTALL_DIR=os.path.join(ROOT, ".local", "python"), HF_HOME=os.path.join(WORK, "hf"),
               HF_HUB_DISABLE_TELEMETRY="1", PYTHONUTF8="1")
    report = {"platform": sys.platform, "sample": os.path.basename(sample), "transcript": bool(args.transcript)}

    def finish():
        report["venv_gb"] = folder_gb(os.path.join(WORK, "venv"))
        report["model_gb"] = folder_gb(os.path.join(WORK, "hf"))
        text = json.dumps(report, indent=2)
        with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
            f.write(text)
        print(text)
        print(f"[spike] files: {OUT}")

    steps = [("venv", [UV, "venv", "--allow-existing", "--python", "3.11", os.path.join(WORK, "venv")]),
             ("torch", [UV, "pip", "install", "--python", venv_python(), *TORCH_CUDA]),
             ("libraries", [UV, "pip", "install", "--python", venv_python(), *LIBRARIES])]
    for label, command in steps:
        print(f"[spike] {label}...", flush=True)
        code, log = run(command, env)
        if code:
            report[f"{label}_failed"] = log[-3000:]
            return finish()
        if label == "libraries":
            report["libraries_log"] = log[-1500:]
    for package in ("transformers", "accelerate", "bitsandbytes"):
        report[f"{package}_show"] = run([UV, "pip", "show", "--python", venv_python(), package], env)[1][:300]
    report["torch_after_install"] = run([venv_python(), "-c", "import torch; print(torch.__version__)"], env)[1].strip()[-200:]

    print("[spike] downloading the model (about 10 GB)...", flush=True)
    code, log = run([venv_python(), __file__, sample, "--child", "download"], env)
    download = _child_report(log) or {"download_log": log[-3000:]}
    report.update(download)
    if "port_sha" not in download or "download_error" in download:
        return finish()

    offline = dict(env, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    for mode in ("bf16", "8bit"):
        print(f"[spike] generating ({mode}) with the network blocked, several minutes...", flush=True)
        command = [venv_python(), __file__, sample, "--child", mode, "--sha", download["port_sha"],
                   "--codec-sha", download["codec_sha"]]
        if args.transcript:
            command += ["--transcript", args.transcript]
        code, log = run(command, offline)
        report[mode] = _child_report(log) or {"log": log[-3000:]}
        if code and "log" not in report[mode]:
            report[mode]["log"] = log[-1500:]
    finish()


if __name__ == "__main__":
    main()
