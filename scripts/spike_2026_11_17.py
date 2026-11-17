"""Throwaway check for docs/superpowers/plans/2026-11-17-omnivoice.md, Task 0. Run from the repo root:

    uv run --python 3.11 scripts/spike_2026_11_17.py

Needs uv and the internet (it installs small packages into a temporary folder inside .local and deletes it).
Prints one JSON report; paste it back into the conversation.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UV = os.environ.get("VOKALIT_UV") or shutil.which("uv") or "uv"


def venv_python(venv):
    return os.path.join(venv, "Scripts", "python.exe") if sys.platform == "win32" else os.path.join(venv, "bin", "python")


def site_packages(venv):
    out = subprocess.run([venv_python(venv), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def run(args, env):
    result = subprocess.run(args, capture_output=True, text=True, env=env)
    return result.returncode, (result.stdout + result.stderr)[-2000:]


def main():
    os.makedirs(os.path.join(ROOT, ".local"), exist_ok=True)
    work = tempfile.mkdtemp(prefix="spike-", dir=os.path.join(ROOT, ".local"))  # same drive as the real installs
    env = dict(os.environ, UV_CACHE_DIR=os.path.join(work, "uv-cache"), UV_LINK_MODE="hardlink")
    report = {"platform": sys.platform, "python": sys.version.split()[0]}
    try:
        # 1. Hard links from one shared cache into two environments.
        files = []
        for name in ("a", "b"):
            venv = os.path.join(work, name)
            run([UV, "venv", "--python", "3.11", venv], env)
            code, log = run([UV, "pip", "install", "--python", venv_python(venv), "six==1.16.0"], env)
            if code:
                report[f"six_install_{name}"] = log
            files.append(os.path.join(site_packages(venv), "six.py"))
        stats = [os.stat(f) for f in files if os.path.exists(f)]
        report["hardlink"] = {
            "same_inode": len(stats) == 2 and stats[0].st_ino == stats[1].st_ino and stats[0].st_ino != 0,
            "st_nlink": [s.st_nlink for s in stats],
            "expected_nlink": 3,
        }

        # 2. OmniVoice's API, read from its source (without torch).
        venv = os.path.join(work, "omni")
        run([UV, "venv", "--python", "3.11", venv], env)
        code, log = run([UV, "pip", "install", "--python", venv_python(venv), "--no-deps", "omnivoice==0.2.1"], env)
        omni = {"install_ok": code == 0}
        if code:
            omni["log"] = log
        else:
            package = os.path.join(site_packages(venv), "omnivoice")
            signatures, language_lines, asr_lines = [], [], []
            for folder, _, names in os.walk(package):
                for file in names:
                    if not file.endswith(".py"):
                        continue
                    path = os.path.join(folder, file)
                    rel = os.path.relpath(path, package)
                    text = open(path, encoding="utf-8", errors="replace").read()
                    for match in re.finditer(r"def (generate|from_pretrained|__init__)\((.*?)\)\s*(->[^:]*)?:", text, re.S):
                        signatures.append(f"{rel}: def {match.group(1)}({' '.join(match.group(2).split())})")
                    for number, line in enumerate(text.splitlines(), 1):
                        if "language" in line and len(language_lines) < 60:
                            language_lines.append(f"{rel}:{number}: {line.strip()}")
                        if re.search(r"\basr\b|asr_|whisper", line, re.I) and len(asr_lines) < 60:
                            asr_lines.append(f"{rel}:{number}: {line.strip()}")
            omni.update(signatures=signatures, language_lines=language_lines, asr_lines=asr_lines)
        report["omnivoice"] = omni

        # 3. faster-whisper on this machine.
        venv = os.path.join(work, "whisper")
        run([UV, "venv", "--python", "3.11", venv], env)
        code, log = run([UV, "pip", "install", "--python", venv_python(venv), "faster-whisper"], env)
        fw = {"install_ok": code == 0}
        if code:
            fw["log"] = log
        else:
            code, out = run([venv_python(venv), "-c",
                             "import faster_whisper, ctranslate2; print(faster_whisper.__version__, ctranslate2.__version__)"], env)
            fw["import_ok"] = code == 0
            fw["versions"] = out.strip()[-300:]
        report["faster_whisper"] = fw
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
