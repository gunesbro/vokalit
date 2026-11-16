import os
import shutil
import sys
from pathlib import Path

import webview

import models
import server
import workspace

UI_DIR = Path(__file__).resolve().parent / "ui"
# The window's own data (e.g. the microphone permission) stays inside the project folder.
WEBVIEW_DIR = os.path.join(models.LOCAL, "webview")


def _windows_app_id():
    """Windows groups taskbar buttons by app ID; without one the window shows under Python's icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Vokalit.App")
    except Exception as error:  # cosmetic only
        print(f"Could not set the taskbar app ID: {error}")


def _windows_window_icon(window):
    """Puts the Vokalit icon on the title bar and taskbar button (pywebview's own icon option is Linux-only)."""
    try:
        from System import Action
        from System.Drawing import Icon

        form = window.native
        form.Invoke(Action(lambda: setattr(form, "Icon", Icon(str(UI_DIR / "icon.ico")))))
    except Exception as error:  # cosmetic only
        print(f"Could not set the window icon: {error}")


def main():
    shutil.rmtree(workspace.workspace_root() / ".tmp", ignore_errors=True)  # leftovers from a crash
    url, _ = server.start(UI_DIR)
    _windows_app_id()
    window = webview.create_window("Vokalit", url, width=1440, height=900, min_size=(1100, 700),
                                   background_color="#111214")
    if sys.platform == "win32":
        window.events.shown += lambda: _windows_window_icon(window)
    # Not private mode, so the microphone permission is remembered between launches.
    try:
        webview.start(private_mode=False, storage_path=WEBVIEW_DIR, icon=str(UI_DIR / "icon.png"))
    except TypeError:  # older pywebview without the icon option
        webview.start(private_mode=False, storage_path=WEBVIEW_DIR)
    server.stop()
    models.stop_all()
    shutil.rmtree(workspace.workspace_root() / ".tmp", ignore_errors=True)


if __name__ == "__main__":
    main()
