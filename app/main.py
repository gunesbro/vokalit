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
    """Puts the Vokalit icon on the title bar and taskbar button. Built from the PNG (System.Drawing.Icon refuses
    PNG files and some .ico variants), and every error is caught here: an exception on the window's thread would
    otherwise close the app."""
    def apply():
        try:
            from System.Drawing import Bitmap, Icon

            form.Icon = Icon.FromHandle(Bitmap(str(UI_DIR / "icon.png")).GetHicon())
        except Exception as error:  # cosmetic only
            print(f"Could not set the window icon: {error}")

    try:
        from System import Action

        form = window.native
        form.Invoke(Action(apply))
    except Exception as error:  # cosmetic only
        print(f"Could not set the window icon: {error}")


def main():
    shutil.rmtree(workspace.workspace_root() / ".tmp", ignore_errors=True)  # leftovers from a crash
    models.delete_removed()
    models._start_background(models.clean_shared_cache)  # e.g. after an install the app was closed during
    url, _ = server.start(UI_DIR)
    _windows_app_id()
    window = webview.create_window("Vokalit", url, width=1440, height=900, min_size=(1100, 700),
                                   background_color="#111214")
    if sys.platform == "win32":
        window.events.shown += lambda: _windows_window_icon(window)
    # Not private mode, so the microphone permission is remembered between launches.
    options = {"private_mode": False, "storage_path": WEBVIEW_DIR}
    if sys.platform != "win32":
        # Linux (GTK/Qt) takes a PNG. On Windows, pywebview would load it with System.Drawing.Icon, which refuses
        # PNG files and stops the app, so the Windows icon is set by _windows_window_icon instead.
        options["icon"] = str(UI_DIR / "icon.png")
    try:
        webview.start(**options)
    except TypeError:  # older pywebview without the icon option
        options.pop("icon", None)
        webview.start(**options)
    server.stop()
    models.stop_all()
    shutil.rmtree(workspace.workspace_root() / ".tmp", ignore_errors=True)


if __name__ == "__main__":
    main()
