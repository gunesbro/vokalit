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


_handlers = []  # .NET event handlers stay referenced for the window's lifetime


def _windows_microphone(window, url):
    """The server's port, and so the page's address, changes every launch, so the window would ask for the
    microphone every time. Once the user has allowed it (server.microphone_allowed), it is granted to Vokalit's own
    page without asking; until then, and after a block, the window asks as usual. An error here only means the
    window asks again, so it is caught."""
    if _handlers:  # "loaded" fires after every page load; hook once
        return

    def hook():
        try:
            from Microsoft.Web.WebView2.Core import CoreWebView2PermissionKind, CoreWebView2PermissionState

            def requested(sender, args):
                if (args.PermissionKind == CoreWebView2PermissionKind.Microphone and str(args.Uri).startswith(url)
                        and server.microphone_allowed()):
                    args.State = CoreWebView2PermissionState.Allow

            window.native.browser.webview.CoreWebView2.PermissionRequested += requested
            _handlers.append(requested)
        except Exception as error:
            print(f"Could not remember the microphone permission: {error}")

    try:
        from System import Action

        window.native.Invoke(Action(hook))
    except Exception as error:
        print(f"Could not remember the microphone permission: {error}")


def main():
    shutil.rmtree(workspace.workspace_root() / ".tmp", ignore_errors=True)  # leftovers from a crash
    models.delete_removed()
    models._start_background(models.clean_shared_cache)  # e.g. after an install the app was closed during
    url, _ = server.start(UI_DIR)
    if models.is_installed("whisper"):
        server.transcribe_missing()  # samples added while it was missing, or left when the app closed
    _windows_app_id()
    window = webview.create_window("Vokalit", url, width=1440, height=900, min_size=(1100, 700),
                                   background_color="#111214")
    if sys.platform == "win32":
        window.events.shown += lambda: _windows_window_icon(window)
        window.events.loaded += lambda: _windows_microphone(window, url)
    # Not private mode: the window keeps its data (and the remembered microphone answer, see _windows_microphone).
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
