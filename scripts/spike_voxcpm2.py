r"""Throwaway check for docs/superpowers/plans/2026-11-17-voxcpm2.md, Task 0. Run from the repo root, with Vokalit
closed. On Windows, double-click scripts\spike_voxcpm2.bat: it picks a Turkish sample of one of your library
characters (with its transcript). Or pass a sample yourself:

    Windows (PowerShell):
        $env:UV_PYTHON_INSTALL_DIR="$PWD\.local\python"; .\.local\uv\uv.exe run --python 3.11 scripts\spike_voxcpm2.py C:\path\to\sample.wav --transcript "what the sample says"
    Linux:
        UV_PYTHON_INSTALL_DIR="$PWD/.local/python" .local/uv/uv run --python 3.11 scripts/spike_voxcpm2.py /path/to/sample.wav

--transcript is optional (only used for one continuation-cloning comparison).

Needs the internet: it installs PyTorch (from the shared cache, so usually not downloaded again) and voxcpm into
.local/spike-voxcpm/, and downloads the VoxCPM2 weights (about 5 GB) there. Then it blocks the network and generates
test files into .local/spike-voxcpm/out/. Prints one JSON report (also saved as out/report.json); send it back,
listen to the files and say what you hear. Delete .local/spike-voxcpm/ afterwards.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_OWN_UV = os.path.join(ROOT, ".local", "uv", "uv.exe" if sys.platform == "win32" else "uv")  # the copy start.bat fetches
UV = os.environ.get("VOKALIT_UV") or (_OWN_UV if os.path.exists(_OWN_UV) else None) or shutil.which("uv") or "uv"
WORK = os.path.join(ROOT, ".local", "spike-voxcpm")
OUT = os.path.join(WORK, "out")
MODEL = "openbmb/VoxCPM2"
TORCH_CUDA = ["torch==2.8.0", "torchaudio==2.8.0", "--index-url", "https://download.pytorch.org/whl/cu128"]  # app/models.py

SENTENCE = "Toplant\u0131 3 Mart'ta saat 14:30'da ba\u015fl\u0131yor, l\u00fctfen ge\u00e7 kalmay\u0131n."
SHORT = ("D\u00fcn ak\u015fam eve d\u00f6nerken ya\u011fmur bast\u0131rd\u0131. \u015eemsiyemi unuttu\u011fum i\u00e7in "
         "s\u0131r\u0131ls\u0131klam oldum, ama yine de g\u00fcld\u00fcm. Kap\u0131y\u0131 a\u00e7t\u0131\u011f\u0131mda "
         "annem s\u0131cak bir \u00e7ay demlemi\u015fti. Oturduk, uzun uzun konu\u015ftuk; sanki y\u0131llard\u0131r "
         "g\u00f6r\u00fc\u015fmemi\u015f gibiydik.")
LONG = SHORT + (" Sonra eski foto\u011fraf alb\u00fcmlerini \u00e7\u0131kard\u0131. Her sayfada ba\u015fka bir "
                "hik\u00e2ye vard\u0131: bisikletten d\u00fc\u015ft\u00fc\u011f\u00fcm g\u00fcn, ilk okul g\u00fcn\u00fcm, "
                "dedemin bah\u00e7esindeki kiraz a\u011fac\u0131. Saat gece yar\u0131s\u0131n\u0131 ge\u00e7mi\u015fti ki "
                "fark ettik. Yar\u0131n erken kalkmam gerekti\u011fini bildi\u011fim halde kalkmak istemedim. "
                "Baz\u0131 ak\u015famlar b\u00f6yledir, zaman durur ve insan sadece o an\u0131 ya\u015famak ister.")
PAREN = "(Ahmet) Geldim."
STYLES = {  # draft presets (spec section 5.4): English and Turkish wording
    "happy": ("cheerful, warm", "ne\u015feli, s\u0131cak"),
    "sad": ("sad, quiet", "\u00fczg\u00fcn, sessiz"),
    "angry": ("angry, tense", "k\u0131zg\u0131n, gergin"),
    "calm": ("calm, slow", "sakin, yava\u015f"),
    "excited": ("excited, energetic", "heyecanl\u0131, enerjik"),
    "whispering": ("whispering", "f\u0131s\u0131ldayarak"),
    "serious": ("serious, firm", "ciddi, kararl\u0131"),
}


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
    from voxcpm import VoxCPM

    VoxCPM.from_pretrained(MODEL, load_denoiser=False)


def child_generate(sample, transcript):
    block_network()
    import inspect

    import numpy as np
    import soundfile as sf
    import torch
    from voxcpm import VoxCPM

    report = {"torch": torch.__version__, "cuda": torch.cuda.is_available()}
    start = time.perf_counter()
    model = VoxCPM.from_pretrained(MODEL, load_denoiser=False)
    report["load_seconds"] = round(time.perf_counter() - start, 1)
    report["vram_after_load_gb"] = round(torch.cuda.max_memory_reserved() / 1e9, 2)
    report["sample_rate"] = model.tts_model.sample_rate
    report["generate_signature"] = str(inspect.signature(model.generate))
    report["from_pretrained_signature"] = str(inspect.signature(VoxCPM.from_pretrained))

    runs = [("a_no_style", SENTENCE, {})]
    for name, (english, turkish) in STYLES.items():
        runs.append((f"b_{name}_en", f"({english}){SENTENCE}", {}))
        runs.append((f"c_{name}_tr", f"({turkish}){SENTENCE}", {}))
    runs += [("d_normalize_on", SENTENCE, {"normalize": True}), ("d_normalize_off", SENTENCE, {"normalize": False}),
             (f"f_short_{len(SHORT)}chars", SHORT, {}), (f"f_long_{len(LONG)}chars", LONG, {}),
             ("g_paren_no_style", PAREN, {}), ("g_paren_cheerful", f"(cheerful){PAREN}", {})]
    files = []
    for name, text, extra in runs:
        files.append(_one(model, name, dict(text=text, reference_wav_path=sample, **extra), sf, np, torch))
    if transcript:
        files.append(_one(model, "e_continuation", dict(text=SENTENCE, prompt_wav_path=sample, prompt_text=transcript),
                          sf, np, torch))
    report["files"] = files
    report["vram_peak_gb"] = round(torch.cuda.max_memory_reserved() / 1e9, 2)
    print("REPORT " + json.dumps(report, ensure_ascii=True))


def _one(model, name, kwargs, sf, np, torch):
    kwargs = {"cfg_value": 2.0, "inference_timesteps": 10, "denoise": False, **kwargs}
    torch.manual_seed(0)
    start = time.perf_counter()
    try:
        wav = model.generate(**kwargs)
        path = os.path.join(OUT, f"{name}.wav")
        sf.write(path, np.asarray(wav), model.tts_model.sample_rate, subtype="PCM_16")
        return {"file": f"{name}.wav", "seconds": round(time.perf_counter() - start, 1),
                "duration": round(len(wav) / model.tts_model.sample_rate, 1)}
    except Exception as error:
        return {"file": name, "error": f"{type(error).__name__}: {error}"[:500]}


def pick_sample():
    """A library character's Turkish sample, preferring one with a transcript; then any sample. (path, transcript)"""
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


def main():
    parser = argparse.ArgumentParser(description="VoxCPM2 spike for Vokalit (see the docstring).")
    parser.add_argument("sample", nargs="?", help="a Turkish voice sample (.wav); default: one from your workspace")
    parser.add_argument("--transcript", help="what the sample says (optional)")
    parser.add_argument("--child", choices=["download", "generate"], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child == "download":
        return child_download()
    if args.child == "generate":
        return child_generate(args.sample, args.transcript)

    if args.sample:
        sample, transcript = os.path.abspath(args.sample), args.transcript
    else:
        sample, transcript = pick_sample()
        if not sample:
            return print("No voice sample found in workspace/characters. Pass one: spike_voxcpm2.py sample.wav")
        args.transcript = transcript
    print(f"[spike] sample: {sample}", flush=True)
    os.makedirs(OUT, exist_ok=True)
    env = dict(os.environ, UV_CACHE_DIR=os.path.join(ROOT, ".local", "shared", "uv-cache"), UV_LINK_MODE="hardlink",
               UV_PYTHON_INSTALL_DIR=os.path.join(ROOT, ".local", "python"), HF_HOME=os.path.join(WORK, "hf"),
               HF_HUB_DISABLE_TELEMETRY="1", PYTHONUTF8="1")
    report = {"platform": sys.platform, "sample": os.path.basename(sample), "transcript": bool(args.transcript)}
    steps = [("venv", [UV, "venv", "--python", "3.11", os.path.join(WORK, "venv")]),
             ("torch", [UV, "pip", "install", "--python", venv_python(), *TORCH_CUDA]),
             ("voxcpm", [UV, "pip", "install", "--python", venv_python(), "voxcpm"])]
    for label, command in steps:
        print(f"[spike] {label}...", flush=True)
        code, log = run(command, env)
        if code:
            report[f"{label}_failed"] = log[-3000:]
            return print(json.dumps(report, indent=2))
        if label == "voxcpm":
            report["voxcpm_install_log"] = log[-1500:]  # shows whether torch was replaced
    report["voxcpm_show"] = run([UV, "pip", "show", "--python", venv_python(), "voxcpm"], env)[1][-800:]
    report["torch_after_install"] = run([venv_python(), "-c", "import torch; print(torch.__version__)"], env)[1].strip()[-200:]

    print("[spike] downloading the model (about 5 GB)...", flush=True)
    code, log = run([venv_python(), __file__, sample, "--child", "download"], env)
    if code:
        report["download_failed"] = log[-3000:]
        return print(json.dumps(report, indent=2))

    print("[spike] generating with the network blocked (a few minutes)...", flush=True)
    offline = dict(env, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    command = [venv_python(), __file__, sample, "--child", "generate"]
    if args.transcript:
        command += ["--transcript", args.transcript]
    code, log = run(command, offline)
    lines = [line for line in log.splitlines() if line.startswith("REPORT ")]
    if lines:
        report["generate"] = json.loads(lines[-1][len("REPORT "):])
    if code or not lines:
        report["generate_log"] = log[-3000:]
    report["venv_gb"] = folder_gb(os.path.join(WORK, "venv"))
    report["model_gb"] = folder_gb(os.path.join(WORK, "hf"))
    text = json.dumps(report, indent=2)
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"[spike] files: {OUT}")


if __name__ == "__main__":
    main()
