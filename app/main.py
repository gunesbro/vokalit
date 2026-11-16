import os
import shutil
import time

import gradio as gr
import soundfile as sf
import webview

import models

# Set by the start scripts so that uploaded/recorded audio never lands in the system temp folder.
TEMP_DIR = os.environ["GRADIO_TEMP_DIR"]
# The window's own data (e.g. the microphone permission) also stays inside the project folder.
WEBVIEW_DIR = os.path.join(models.LOCAL, "webview")
OUTPUTS_DIR = os.path.join(models.ROOT, "outputs")
MIN_REF_SECONDS = 10
CLONE, DEFAULT = "Clone voice", "Default voice"

# System fonts only: the default theme would fetch fonts from Google Fonts.
THEME = gr.themes.Default(font=["system-ui", "sans-serif"], font_mono=["ui-monospace", "monospace"])


def model_status(name):
    # The model page lists the supported languages.
    title = f"[{models.MODELS[name]['title']}]({models.MODELS[name]['url']})"
    if models.is_installed(name):
        return f"**{title}**: installed ({models.size_gb(name):.1f} GB)"
    return f"**{title}**: not installed"


def build_model_row(name):
    """Status, Install/Remove buttons, a confirmation box and the install log for one model."""
    info = models.MODELS[name]
    installed = models.is_installed(name)
    action = gr.State(None)
    with gr.Row():
        status = gr.Markdown(model_status(name))
        install_btn = gr.Button("Install", visible=not installed, scale=0)
        remove_btn = gr.Button("Remove", visible=installed, scale=0)
        cancel_install_btn = gr.Button("Cancel install", visible=False, scale=0)
    with gr.Group(visible=False) as confirm_box:
        confirm_text = gr.Markdown()
        with gr.Row():
            confirm_btn = gr.Button("Confirm", variant="primary")
            cancel_btn = gr.Button("Cancel")
    progress = gr.Markdown(visible=False)
    with gr.Accordion("Install log", open=False, visible=False) as log_box:
        log = gr.Textbox(show_label=False, lines=10, max_lines=10, autoscroll=True)

    def ask_install():
        text = (
            f"**Install {info['title']}?**\n\n"
            f"- Source: {info['url']}\n"
            f"- Disk space: about {info['disk_gb']} GB (PyTorch with CUDA, libraries and the model)\n"
            f"- Location: `.local/{name}/`\n"
            f"- License: {info['license']}"
        )
        return "install", text, gr.update(visible=True)

    def ask_remove():
        text = (
            f"**Remove {info['title']}?** This permanently deletes `.local/{name}/` "
            f"and frees {models.size_gb(name):.1f} GB."
        )
        return "remove", text, gr.update(visible=True)

    def finished():
        installed = models.is_installed(name)
        return {
            confirm_box: gr.update(visible=False),
            progress: gr.update(visible=False),
            status: model_status(name),
            install_btn: gr.update(visible=not installed),
            remove_btn: gr.update(visible=installed),
            cancel_install_btn: gr.update(visible=False),
        }

    def run(action):
        if action == "remove":
            models.remove(name)
            yield finished()
            return
        log_text = ""
        yield {
            confirm_box: gr.update(visible=False),
            progress: gr.update(visible=True, value="Starting..."),
            log_box: gr.update(visible=True),
            log: "",
            install_btn: gr.update(visible=False),
            cancel_install_btn: gr.update(visible=True),
        }
        try:
            for kind, text in models.install(name):
                if kind == "status":
                    yield {progress: text}
                else:
                    log_text += text
                    yield {log: log_text}
        except models.Cancelled:
            gr.Info("Install cancelled. Nothing was kept.")
        except Exception as error:
            yield finished()
            raise gr.Error(f"Install failed: {error}. See the install log.")
        yield finished()

    install_btn.click(ask_install, None, [action, confirm_text, confirm_box])
    remove_btn.click(ask_remove, None, [action, confirm_text, confirm_box])
    cancel_btn.click(lambda: gr.update(visible=False), None, confirm_box)
    cancel_install_btn.click(lambda: models.cancel_install(name), None, None)
    confirm_btn.click(
        run, action, [confirm_box, progress, log_box, log, status, install_btn, remove_btn, cancel_install_btn]
    )


def generate(mode, ref, text):
    if not text.strip():
        raise gr.Error("Enter some text to read.")
    if mode == CLONE:
        if ref is None:
            raise gr.Error("Record or upload a reference voice first.")
        if sf.info(ref).duration < MIN_REF_SECONDS:
            raise gr.Error(f"The reference voice must be at least {MIN_REF_SECONDS} seconds long.")
    else:
        ref = None
    if not any(models.is_installed(name) for name in models.MODELS):
        raise gr.Error("Install a model first.")
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results = []
    for name, info in models.MODELS.items():
        if not models.is_installed(name):
            results.append(gr.update(value=None, label=f"{info['title']} (not installed)"))
            continue
        out = os.path.join(OUTPUTS_DIR, f"{stamp}-{name}.wav")
        try:
            seconds = models.generate(name, text, ref, out)
        except Exception as error:
            raise gr.Error(f"{info['title']}: {error}")
        results.append(gr.update(value=out, label=f"{info['title']} (generated in {seconds} s)"))
    return results


def build_ui():
    with gr.Blocks(title="Vokalit") as demo:
        gr.Markdown("# Vokalit")
        with gr.Group():
            gr.Markdown("### Models")
            for name in models.MODELS:
                build_model_row(name)

        mode = gr.Radio([CLONE, DEFAULT], value=CLONE, label="Voice")
        # No buttons: "share" would upload the audio to Hugging Face, "download" is not needed.
        ref = gr.Audio(label="Reference voice", sources=["upload", "microphone"], type="filepath", buttons=[])
        text = gr.Textbox(label="Text", lines=4)
        generate_btn = gr.Button("Generate", variant="primary")
        results = [
            gr.Audio(label=info["title"], interactive=False, buttons=["download"]) for info in models.MODELS.values()
        ]
        gr.Markdown("Only use your own voice or voices you have permission to use.")

        mode.change(lambda m: gr.update(visible=m == CLONE), mode, ref)
        generate_btn.click(generate, [mode, ref, text], results)
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
    models.stop_all()
    shutil.rmtree(TEMP_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
