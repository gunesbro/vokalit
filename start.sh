#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# uv is used to set up Python. Use the copy inside this folder, a system-wide one, or download it.
UV_VERSION="0.11.32"
UV="$PWD/.local/uv/uv"
if [ ! -x "$UV" ]; then
    if command -v uv >/dev/null 2>&1; then
        UV="uv"
    else
        echo "Vokalit needs uv (a Python package manager) to set itself up."
        echo "It will be downloaded from GitHub (astral-sh/uv $UV_VERSION, about 20 MB) into .local/uv/"
        echo "Nothing outside this folder is changed."
        read -r -p "Download uv now? [y/N] " answer
        [ "$answer" = "y" ] || [ "$answer" = "Y" ] || exit 1
        mkdir -p .local/uv
        curl -fL "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-x86_64-unknown-linux-gnu.tar.gz" \
            | tar -xz -C .local/uv --strip-components=1
    fi
fi

# Keep everything inside the project folder.
export UV_CACHE_DIR="$PWD/.local/uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.local/python"
export GRADIO_ANALYTICS_ENABLED=False
export HF_HUB_DISABLE_TELEMETRY=1
export GRADIO_TEMP_DIR="$PWD/.local/tmp"

VENV=".local/app/venv"
[ -d "$VENV" ] || "$UV" venv --python 3.11 "$VENV"
"$UV" pip install --python "$VENV/bin/python" -r app/requirements.txt
exec "$VENV/bin/python" app/main.py
