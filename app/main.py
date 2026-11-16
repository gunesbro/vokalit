import os
import shutil
from pathlib import Path

import webview

import models
import server
import workspace

UI_DIR = Path(__file__).resolve().parent / "ui"
# The window's own data (e.g. the microphone permission) stays inside the project folder.
WEBVIEW_DIR = os.path.join(models.LOCAL, "webview")


def main():
    shutil.rmtree(workspace.workspace_root() / ".tmp", ignore_errors=True)  # leftovers from a crash
    url, _ = server.start(UI_DIR)
    webview.create_window("Vokalit", url, width=1440, height=900, min_size=(1100, 700), background_color="#111214")
    # Not private mode, so the microphone permission is remembered between launches.
    webview.start(private_mode=False, storage_path=WEBVIEW_DIR)
    server.stop()
    models.stop_all()
    shutil.rmtree(workspace.workspace_root() / ".tmp", ignore_errors=True)


if __name__ == "__main__":
    main()
