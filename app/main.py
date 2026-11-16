import os
import shutil

import gradio as gr
import webview

# Set by the start scripts so that uploaded/recorded audio never lands in the system temp folder.
TEMP_DIR = os.environ["GRADIO_TEMP_DIR"]

# System fonts only: the default theme would fetch fonts from Google Fonts.
THEME = gr.themes.Default(font=["system-ui", "sans-serif"], font_mono=["ui-monospace", "monospace"])


def build_ui():
    with gr.Blocks(title="Vokalit") as demo:
        gr.Markdown("# Vokalit")
        # No "share" button: it uploads the audio to Hugging Face.
        gr.Audio(label="Reference voice", sources=["upload", "microphone"], type="filepath", buttons=["download"])
    return demo


def main():
    shutil.rmtree(TEMP_DIR, ignore_errors=True)  # leftovers from a crashed session
    demo = build_ui()
    demo.launch(server_name="127.0.0.1", share=False, inbrowser=False, prevent_thread_lock=True, theme=THEME)
    # Gradio translates its built-in labels to the webview's language; keep the UI in English.
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--lang=en-US"  # Windows (WebView2)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--lang=en-US"  # Linux (Qt WebEngine)
    webview.create_window("Vokalit", demo.local_url, width=1100, height=850)
    webview.start()
    demo.close()
    shutil.rmtree(TEMP_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
