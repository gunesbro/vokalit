import os
import shutil

import gradio as gr
import webview

# Set by the start scripts so that uploaded/recorded audio never lands in the system temp folder.
TEMP_DIR = os.environ["GRADIO_TEMP_DIR"]
# The window's own data (e.g. the microphone permission) also stays inside the project folder.
WEBVIEW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".local", "webview")

# System fonts only: the default theme would fetch fonts from Google Fonts.
THEME = gr.themes.Default(font=["system-ui", "sans-serif"], font_mono=["ui-monospace", "monospace"])


def build_ui():
    with gr.Blocks(title="Vokalit") as demo:
        gr.Markdown("# Vokalit")
        # No buttons: "share" would upload the audio to Hugging Face, "download" is not needed.
        gr.Audio(label="Reference voice", sources=["upload", "microphone"], type="filepath", buttons=[])
    return demo


def main():
    shutil.rmtree(TEMP_DIR, ignore_errors=True)  # leftovers from a crashed session
    demo = build_ui()
    demo.launch(server_name="127.0.0.1", share=False, inbrowser=False, prevent_thread_lock=True, theme=THEME)
    # Gradio translates its built-in labels to the webview's language; keep the UI in English.
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--lang=en-US"  # Windows (WebView2)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--lang=en-US"  # Linux (Qt WebEngine)
    webview.create_window("Vokalit", demo.local_url, width=1100, height=850)
    # Not private mode, so the microphone permission is remembered between launches.
    webview.start(private_mode=False, storage_path=WEBVIEW_DIR)
    demo.close()
    shutil.rmtree(TEMP_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
