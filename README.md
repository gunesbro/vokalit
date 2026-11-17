<p align="center"><img src="app/ui/icon.svg" width="112" alt="Vokalit icon"></p>

# Vokalit

**A local voice cloning and text-to-speech studio.** Clone a voice from a short recording, write a script with several
characters, generate takes, compare them and export the result — all on your own computer with an NVIDIA GPU.
Your voice, your text and the generated audio never leave your machine.

![The Studio: a script with several characters, takes for each line, and Play all](docs/images/studio.png)

- **Studio** — sessions with a cast of characters and a script. Generate one or more takes per line, pick the best,
  trim it, listen to the whole script with *Play all*, and export it as one file (WAV, FLAC, MP3 or OGG).
- **Characters** — a library of reusable voices. Each character can have several samples (e.g. *calm*, *excited*, or
  one per language), recorded in the app or uploaded, and trimmed before saving.
- **Models** — install and remove open models with one click. Size, location and license are shown before anything
  is downloaded, and *Remove* frees all of it.
- **Generation settings** — per model, at three levels: model defaults → session → line. A seed makes a take
  reproducible.
- **Perform this line** — record a line with your own delivery and convert it to a character's voice.
- **Languages** — per session or per line, limited to what the selected models support; a search box finds a
  language among OmniVoice's 646.
- **Sound tags** — laughter, sighs and other sounds as chips inside a line's text (*Add sound*, or type
  `[laughter]`; × removes one). Each model gets them in its own syntax; models that cannot perform them get the text
  without them. OmniVoice performs them, more clearly with a higher Quality.
- **Transcripts** — every sample keeps what is said in it, which some models use to copy the voice. The optional
  Whisper component writes it for you (and detects the language); otherwise you type it.

## Screenshots

**Line details** — text, sample, language and pause; generate with one or more models; per-line settings; takes
to compare, trim and pick; and *Perform this line* to convert your own recording.

![Line details with takes, line settings and Perform this line](docs/images/line-details.png)

**Characters** — reusable voices with several labelled samples, each tagged with its language.

![Characters with samples](docs/images/characters.png)

**Models** — install and remove models; size and license are shown first.

![Models](docs/images/models.png)

<sub>Screenshots use made-up demo data; no real voices were used.</sub>

## Models

**Models are not included in the download.** The repository contains only the app (a few hundred KB). You install
the models you want from the app's **Models** screen, which shows each model's size, location and license and asks
before downloading anything. Each model goes into its own folder under `.local/`, and **Remove** deletes it again.

| Component | Languages | Disk space | License |
|---|---|---|---|
| [Whisper](https://github.com/SYSTRAN/faster-whisper) (optional, recommended) — writes sample transcripts, runs on the CPU | ~100 | ~1.7 GB | MIT |
| [Chatterbox Multilingual](https://huggingface.co/ResembleAI/chatterbox) (Resemble AI) | 23 | ~12.3 GB (measured on Windows) | MIT |
| [OmniVoice](https://huggingface.co/k2-fsa/OmniVoice) (k2-fsa) — cloning, sound tags | 646 | ~9 GB, less when Chatterbox is installed | Code Apache 2.0; **weights CC-BY-NC: no commercial use** |

Each component has its own environment, so one model's packages can never break another's. Identical files — above
all PyTorch with CUDA, about 5 GB — are stored once and shared between models; files nothing uses any more are
deleted automatically, and removing the last component frees everything.

What you do with OmniVoice's output must be non-commercial: its weights are licensed CC-BY-NC because of its training
data, and no paid license is offered.

## Requirements

- **NVIDIA GPU** with an up-to-date driver that supports CUDA 12.8. RTX 20 series or newer is a safe choice; RTX 50
  series is supported. Chatterbox needs about 4 GB of video memory.
- **Windows 10/11** (tested) or **Linux** (less tested).
- An internet connection only while installing. Nothing else needs to be installed beforehand: Vokalit downloads its
  own Python and packages into its folder, and the models are installed later from inside the app.
- Disk space: a few hundred MB for the app and its Python, plus the models you choose to install (see above).

## Getting started

1. Download the repository (green **Code** button → **Download ZIP**) and extract it, or `git clone` it.
2. Start it:
   - **Windows:** double-click `start.bat`.
   - **Linux:** run `./start.sh`.

   The first start asks to download [uv](https://github.com/astral-sh/uv) (about 20 MB) unless you already have it.
   uv then sets up Python and the app's packages inside the folder. This takes a few minutes once.
3. In the window, open **Models** and install a model — this is the large download, and the app cannot generate
   speech until at least one model is installed. The confirmation shows the download size, where it goes and
   its license. Installing **Whisper** too saves you typing what each sample says.
4. Open **Characters**, create a character and add a sample: at least 10 seconds of clear speech. The first ~10
   seconds matter most, so trim away silence and noise. Then check what the sample says (Whisper writes it) or type
   it exactly.
5. Open **Studio**, create a session, add the character to the cast, write or paste lines (`Name: text`), and
   **Generate**.

Tips: hover over a control to see what it does. *Space* plays and pauses *Play all*; *Esc* closes a line;
*Ctrl+A* selects all lines for bulk actions.

## Privacy

Vokalit is built so that your voice cannot leave your computer.

- **The network is used only when you install something:** uv from GitHub, packages from PyPI and the PyTorch
  index, model weights from Hugging Face. Nothing is downloaded without your confirmation.
- **The models run offline.** Each model runs in its own process that blocks network connections before any library
  is loaded, with Hugging Face's offline mode on. Everything a model needs at generation time is downloaded during
  install.
- **The window talks only to the app on your computer** (`127.0.0.1`, a random port, a per-run token). The page loads
  nothing from the internet.
- **Check it yourself:** after installing a model, disconnect from the internet and keep working — everything works.
  While generating, Windows Resource Monitor (Network tab) or `ss -tnp` on Linux shows no connection other than
  `127.0.0.1`.
- **Your data is stored unencrypted** in the `workspace/` folder (characters, samples, sessions, takes, recordings,
  exports) until you delete it. Delete the folder to remove everything.
- **Known limit:** on Windows the window is drawn by Microsoft Edge WebView2, which may send its own diagnostic data
  to Microsoft. Audio content is not part of it.

## Responsible use

- Only use your own voice, or voices you have clear permission to use.
- Do not use cloned voices to deceive or impersonate anyone. What you do with the audio you generate is your
  responsibility.
- Chatterbox adds an inaudible watermark (Resemble AI's PerTh) to what it generates. Vokalit does not disable it;
  please do not remove it.
- When reporting a problem, do not attach other people's recordings.

## Where things are

Everything stays inside the Vokalit folder; deleting the folder removes all of it.

```
.local/            uv, Python, the app environment, window data, and one folder per installed model
workspace/         your characters, sessions, takes, recordings and exports
```

Use the folder button next to a sample, take or export to show it in File Explorer.

## Troubleshooting

- **The window closes right away on Windows:** run `start.bat` from a Command Prompt to read the error.
- **"The GPU stopped with an internal error":** a CUDA error stopped the model, so it was restarted automatically.
  Try again; if it repeats with the same settings, lower *Variation* or *Expressiveness*, or use another seed.
- **Long lines get cut off or drift:** models work best with a sentence or two per line. Use *Split into N lines*.
- **An accent from another language:** use a sample in the line's language, or *Reduce accent* in the line.
- **Linux: the window does not open:** the Qt web engine may need system libraries; the console names the missing
  one. Install it with your package manager.

## Development

```
python3 -m pytest tests -q              # Python tests (no GPU or network needed; models are stubbed)
node --test "app/ui/tests/*.test.mjs"   # interface helpers
```

The interface is plain HTML, CSS and JavaScript modules in `app/ui/` (no build step, no CDN); the local server is
`app/server.py`, storage is `app/workspace.py`, and each model has a worker in `workers/<model>/`.
[SPEC.md](SPEC.md) describes the design.

## License

[MIT](LICENSE): use, change and share it freely, including commercially; keep the copyright and license notice
in copies. The models and libraries it downloads have their own licenses, shown before installing.
