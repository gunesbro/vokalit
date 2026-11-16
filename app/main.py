import os
import shutil
import uuid

import gradio as gr
import soundfile as sf
import webview

# Set by the start scripts so that uploaded/recorded audio never lands in the system temp folder.
TEMP_DIR = os.environ["GRADIO_TEMP_DIR"]

# System fonts only: the default theme would fetch fonts from Google Fonts.
THEME = gr.themes.Default(font=["system-ui", "sans-serif"], font_mono=["ui-monospace", "monospace"])


def on_new_audio(path):
    """A new recording/upload becomes the original that 'Undo trim' returns to."""
    return path


def reset_range(path):
    if path is None:
        return 0, 0
    return 0, round(sf.info(path).duration, 2)


def trim(path, start, end):
    if path is None:
        raise gr.Error("Record or upload a reference voice first.")
    data, sample_rate = sf.read(path)
    clip = data[int(start * sample_rate):int(end * sample_rate)]
    if len(clip) == 0:
        raise gr.Error("Nothing left after trimming. Check Start and End.")
    os.makedirs(TEMP_DIR, exist_ok=True)
    out = os.path.join(TEMP_DIR, f"trimmed-{uuid.uuid4().hex}.wav")
    sf.write(out, clip, sample_rate)
    return out


def build_ui():
    with gr.Blocks(title="Vokalit") as demo:
        gr.Markdown("# Vokalit")
        original = gr.State(None)
        # No "share" button: it uploads the audio to Hugging Face.
        # editable=False hides Gradio's own trim tools; ours are below.
        audio = gr.Audio(
            label="Reference voice",
            sources=["upload", "microphone"],
            type="filepath",
            buttons=["download"],
            editable=False,
        )
        with gr.Row():
            start = gr.Number(label="Start (s)", value=0, minimum=0, precision=2)
            end = gr.Number(label="End (s)", value=0, minimum=0, precision=2)
            trim_btn = gr.Button("Trim")
            undo_btn = gr.Button("Undo trim")

        audio.upload(on_new_audio, audio, original)
        audio.stop_recording(on_new_audio, audio, original)
        audio.change(reset_range, audio, [start, end])
        trim_btn.click(trim, [audio, start, end], audio)
        undo_btn.click(lambda path: path, original, audio)
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
