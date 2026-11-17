# SPEC — Vokalit

Local voice cloning and text-to-speech workspace.

> Status: **v2.0** (v1.14 was the Turkish single-page Gradio version; v2.0 is the workspace with our own UI).
> The workspace is specified in detail in `docs/superpowers/specs/2026-11-16-workspace-design.md`;
> this file is the overview. Changes are made here (or in that design) first, then in code.

## 1. Purpose

Read text aloud in a voice cloned from a short reference recording (at least 10 s), entirely on the user's own
computer: no audio or text leaves the machine. Several open models can voice the same line so their results can be
compared. Work is organised in sessions (scripts with several characters, e.g. podcasts) and can be exported as one
file. Everything is done by clicking in a desktop window.

## 2. Scope (v2)

- Models: **Chatterbox Multilingual** (Resemble AI) and **OmniVoice** (k2-fsa); the optional **Whisper** component
  (faster-whisper on the CPU) writes sample transcripts. Design: `docs/superpowers/specs/2026-11-17-omnivoice-design.md`.
- Desktop window (pywebview) showing our own HTML/CSS/JS interface, served by a local server on `127.0.0.1`:
  - **Studio:** sessions; a cast of characters; script lines with takes; generate with one or more models; seed;
    generation settings at three levels (model defaults → session → line); voice conversion ("Perform this line");
    export of the selected takes to one file (WAV always; FLAC, MP3 and OGG Vorbis when the computer's libsndfile can
    write them). Export is enabled once every line has a take.
  - **Characters:** a library of reusable voices, each with several labelled samples (recorded or uploaded, trimmed
    before saving). Session-only characters can be saved to the library.
  - **Models:** install / remove with size, location and license shown first; progress and a collapsible log.
- Hardware: **NVIDIA GPU (CUDA)**. Operating systems: Windows 10/11 and Linux.
- License: **MIT** (free use, including commercial; copies keep the copyright and license notice). It covers this
  repository's code only; models and libraries keep their own licenses.

## 3. Out of scope (v2)

- Automatic quality metrics (speaker similarity, WER, RTF).
- CPU and Apple Silicon (without an NVIDIA GPU the app says so).
- Command-line interface; one-click installers (.exe/.dmg); Docker.
- Fine-tuning (planned later on the Characters screen; the data model leaves room for it), streaming, cloud APIs.
- Transcript import (maybe later with a local language model), reading numbers aloud, voice design (a voice from a
  description).
- Disk space pre-check, resuming downloads, automatic updates.

## 4. Models

| | Chatterbox Multilingual | OmniVoice |
|---|---|---|
| Languages | 23 (Turkish via `language_id="tr"`) | 600+ |
| Size | ~500M parameters | ~0.6B parameters |
| Measured disk use | 12.3 GB on Windows (libraries + weights) | ~9 GB estimate; PyTorch is shared with Chatterbox |
| VRAM | ~3.5–4 GB | ~8 GB is enough (RTX 4090 test) |
| Reference | Audio file | Audio file + its transcript (`needs_transcript`; stored with every sample) |
| Sound tags (`[laughter]`, `[sigh]`, …) | No: removed from its text | Yes (`supports_tags`) |
| Code license | MIT | Apache 2.0 |
| **Weights license** | MIT | **CC-BY-NC (no commercial use)** |
| Without a reference | Built-in default voice | "Auto Voice": random unless a seed is set |
| Settings | Expressiveness, Pace control, Variation | Speed, Quality (diffusion steps 16–64) |
| Voice conversion | Yes (`ChatterboxVC`) | No |
| Note | Adds a PerTh watermark to outputs | |

The license difference is shown in the install confirmation and in the README.

**Whisper** (`TOOLS["whisper"]`, never offered for generation): `faster-whisper==1.2.1`, model `large-v3-turbo`, int8
on the CPU (no PyTorch; the GPU stays free). Optional and recommended. When installed it transcribes a trimmed clip
before the sample is saved (the user can correct it) and detects its language; installing it transcribes every
sample without a transcript in the background. Without it the transcript is typed. A new sample cannot be saved
without a transcript; samples from before this rule fail only for models with `needs_transcript`.

## 5. Architecture

```
┌──────────────────────────────────────────────┐
│ App process (.local/app/venv)                │
│  pywebview window ── HTTP ── local server    │  app/main.py, app/server.py
│  (app/ui: HTML/CSS/JS)        127.0.0.1      │  storage: app/workspace.py → workspace/
└──────┬───────────────┬───────────────────────┘
       │ JSON lines (stdin/stdout)
┌──────▼──────┐ ┌──────▼──────┐
│ Chatterbox  │ │ OmniVoice   │   each in its own venv;
│ worker      │ │ worker      │   the model loads once and stays loaded
└─────────────┘ └─────────────┘
```

### 5.1 Separate environments

Each model runs in its own venv (torch/transformers versions can conflict). The app's environment has no torch.

### 5.2 Worker protocol

The app starts a worker per installed model on first use. The worker loads the model once, then reads one JSON
object per line from stdin and writes one per line to stdout. Logs go to stderr.

```
→ {"text": "...", "ref": "<path>|null", "out": "<path>", "seed": 1234567, "settings": {...}, "language": "en"}  # text to speech
→ {"task": "convert", "source": "<path>", "ref": "<path>|null", "out": "<path>"}          # Chatterbox only
← {"ok": true, "out": "<path>", "seconds": 1.2}
← {"ok": false, "error": "message"}
```

- On start the worker writes `{"ready": true}` once (model loaded) or `{"ready": false, "error": "..."}`.
- `language` is an ISO 639-1 code from the model's `languages` list (`app/models.py`); the app refuses other codes
  before asking the worker. Sessions have a language, a line can override it, and samples can be tagged with the
  language they are spoken in: when it differs from the line's, the line details warn about accent carry-over and
  offer the model's `accent_setting` (Chatterbox: Pace control 0). Takes record their language.
- A missing `task` means text to speech. `ref: null` uses the model's default voice. `settings` keys must be declared
  in that model's settings schema (`app/models.py`); unknown keys are rejected.
- The seed is applied with `torch.manual_seed` (and CUDA) before generating.
- `--download` only downloads the weights (text to speech and voice conversion) and exits; used during install.
- Library output that would go to stdout is redirected to stderr; stdout is only for the protocol. Text is UTF-8
  (`PYTHONUTF8=1`).
- Workers open no network port and stop when the app closes.

### 5.3 Local server and interface

- `ThreadingHTTPServer` (standard library) on `127.0.0.1` with a random port; nothing listens on other interfaces.
- A random token per run is put into the page; every `/api/` request must send it (`X-Vokalit-Token`). Requests
  whose `Host` is not `127.0.0.1:<port>` are refused.
- Content Security Policy: `default-src 'self'; media-src 'self' blob:; img-src 'self' data:`. No CDN, no remote
  fonts, no build step: plain ES modules in `app/ui/`.
- `/files/` serves only `.wav` files inside `workspace/`.
- The interface builds the page with DOM text nodes only (no `innerHTML`), so names and lines typed by the user are
  never parsed as HTML.
- Microphone recording and file decoding happen in the window (Web Audio); audio is sent to the local server as WAV.
- Long tasks (install, generation, export) run as background jobs that the page polls.

### 5.4 Privacy and transparency

**Rule:** the user's voice, text and generated audio never leave the computer. The network is used only when the
user presses "Install" and confirms, to download packages and model weights.

**App process:**

- Binds to `127.0.0.1` only; `HF_HUB_DISABLE_TELEMETRY=1`.
- The window does not run in private mode so the microphone permission is remembered; its data is kept in
  `.local/webview/`.
- Samples, takes, recordings and exports are stored **unencrypted** in `workspace/` until the user deletes them.
  Temporary uploads go to `workspace/.tmp/`, which is cleared at start and exit.

**Workers (where audio is processed), enforced in code:**

- `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`.
- Before importing any library the worker blocks connecting, sending and name resolution
  (`socket.socket.connect`, `connect_ex`, `sendto`, `socket.getaddrinfo` raise). The `socket.socket` class itself
  is not replaced, because modules such as `ssl` subclass it at import. A library that tries the network stops
  with a clear error.
- Everything needed at generation time (Whisper's model and Chatterbox's voice conversion model included) is
  downloaded **during install**. OmniVoice always gets the sample's transcript, so it never needs its own Whisper.

**Transparency:**

- README "Privacy" section: data flow, when and where the network is used (PyPI, Hugging Face, GitHub for uv), and
  how users can check it themselves: after installing models, disconnect from the internet and keep working.
- Known limit (in the README): on Windows, Microsoft's WebView2 component that draws the window may send its own
  diagnostic data to Microsoft; audio content is not part of it.

### 5.5 Public repository

- No audio files in the repo: `.gitignore` excludes common audio formats, `workspace/` and `.local/`. `samples/`
  holds text only.
- README sections required: **Privacy** (above) and **Responsible use** (use only your own voice or voices you have
  permission to use; do not remove Chatterbox's watermark; do not attach other people's recordings to bug reports).
- Chatterbox's PerTh watermark is not disabled.

## 6. Install and remove

**Principle:** everything stays in the project folder. Deleting the folder deletes everything.

```
.local/uv/                # uv itself (downloaded if needed)
.local/python/            # UV_PYTHON_INSTALL_DIR (Python downloaded by uv)
.local/app/venv/          # app environment
.local/webview/           # window data (microphone permission, etc.)
.local/<model>/venv/      # model (or Whisper) environment
.local/<model>/cache/     # HF_HOME, TORCH_HOME
.local/shared/uv-cache/   # one uv cache for every component; its files are hard-linked into the environments
.local/sizes.json         # what removing each component frees, and the total (measured after installs/removes)
workspace/                # the user's characters, sessions, takes and exports
```

Nothing has to be installed beforehand except the NVIDIA driver.

- `start.bat` (Windows) / `start.sh` (Linux) look for uv in `.local/uv/`, then on the system. If neither exists they
  explain and ask (`[y/N]`, default No), then download a pinned uv release from GitHub (astral-sh/uv) into
  `.local/uv/`. PATH and system settings are not touched. uv also downloads Python into `.local/python/`.
- The scripts set the environment, create the app environment if needed and open the window; on errors the
  Windows window stays open so the message can be read.

### 6.1 Model install details

- Confirmation first: model name with a link to its page (supported languages), disk space, location, license,
  and that it downloads from PyPI and Hugging Face. Nothing is downloaded without confirmation.
- **PyTorch:** `torch==2.8.0` + `torchaudio==2.8.0`, CUDA 12.8 build (supports RTX 50 series). The NVIDIA driver must
  support CUDA 12.8.
- **Chatterbox:** `chatterbox-tts==0.1.7` installed with `--no-deps` (its `torch==2.6.0` pin does not support RTX 50);
  the other dependencies are listed in `workers/chatterbox/requirements.txt` with upstream pins.
- **Shared uv cache:** `UV_CACHE_DIR=.local/shared/uv-cache`, `UV_LINK_MODE=hardlink`. Identical package files
  (PyTorch) are stored once and linked into every environment that needs them; an environment only gains or loses
  links, so one install cannot change another's files. After every install, cancel and remove, cache files no
  environment links to (link count 1) are deleted, and `.local/shared/` goes with the last component. The clean-up
  waits for a running install; only one install runs at a time. Where hard links are impossible uv copies, and the
  clean-up empties the cache (each environment has its own copy).
- **Progress:** no percentage (download sizes are not known in advance). A bar with one segment per step: finished
  steps filled, the running one animated. Under it a status line updated every few seconds
  (`Step 2/5: PyTorch with CUDA · 1.42 GB on disk · 3m 12s`; size = growth of the model folder and the shared cache,
  hard links counted once),
  above a collapsible log.
- **Cancel** stops the running process within seconds and deletes `.local/<model>/`. Install always clears leftovers
  of an interrupted install first. A finished install writes `.local/<model>/installed`.
- **Remove** shows the folder and the space it frees (files no other component links to), then, after confirmation,
  stops the worker and deletes `.local/<model>/`; then the shared cache is cleaned. The Models screen also shows the
  total of all components.

## 7. Interface

All interface text is English. The visual design is the design canvas; behaviour is specified in the design doc
(§7 Studio, Characters, Models). Summary:

- **Rail:** Studio, Characters, Models, and a GPU status dot.
- **Studio:** session list with search; header with session name, "Generate with" (multi-select of installed
  models), Settings (session settings per model), Seed, Export, Generate missing / Stop; cast strip; script rows
  (speaker, sample, text, selected take player) with drag-and-drop reordering, "+ Insert line" between lines and a
  ⋯ menu; line details with text, sample, pause, Generate with + seed, line settings ("Reset to session settings"),
  takes (select, play, "custom settings", "text changed", "Use these settings", delete) and "Perform this line";
  "Paste script" (`Name: text` lines); "Play all" in the footer plays the selected takes in order with each line's
  pause (previous/next, Space to pause, "Play from here" in the line menu; lines without takes are skipped).
  Lines can be ticked (Shift+click for a range, Ctrl+A for all, Esc to clear) for bulk Generate, Character, Sample
  and Delete; the session menu has "Delete empty lines".
- **Characters:** list; editable name; "used in" sessions; delete (confirmed, lists sessions); samples table
  (★ default, play, label, waveform, length/source, delete); add a sample by recording (microphone choice, timer,
  level, 10 s hint) or upload, then trim and "Add sample". Note: "Only use your own voice or voices you have
  permission to use."
- **Models:** as in §6.1.
- Messages appear on the page (a message line per screen), not as pop-up toasts.

## 8. Repository structure

```
vokalit/
├── CLAUDE.md, SPEC.md, README.md, LICENSE (MIT)
├── start.sh / start.bat
├── app/
│   ├── requirements.txt       # numpy, soundfile, pywebview
│   ├── main.py                # starts the server and the window
│   ├── server.py              # local HTTP API
│   ├── workspace.py           # storage under workspace/
│   ├── models.py              # model table, install/remove, workers
│   └── ui/                    # HTML/CSS/JS (+ tests/ for node --test)
├── workers/<model>/           # requirements.txt + worker.py
├── tests/                     # pytest (stubs for torch/chatterbox; no GPU or network needed)
├── docs/superpowers/          # design docs and plans
├── samples/                   # sample texts (no audio)
├── workspace/                 # user data — .gitignore
└── .local/                    # .gitignore
```

Tests: `python3 -m pytest tests -q` and `node --test "app/ui/tests/*.test.mjs"`.

## 9. Success criteria

1. On a clean Windows or Linux machine with an NVIDIA GPU (no uv, no Python): run `start` → uv download prompt →
   the window opens.
2. The install confirmation shows name, size, location and license; nothing is downloaded without confirmation.
3. "Remove" leaves no `.local/<model>/`, and nothing new appeared in the home folder caches
   (`~/.cache/huggingface`, `~/.cache/torch`, `~/.cache/pip`, `~/.cache/uv`).
4. Without a GPU the app says so clearly.
5. Turkish text with Turkish-specific letters (see `samples/`) is read correctly, checked by listening.
6. A second generation does not reload the model (clearly faster than the first).
7. With the network disconnected after installing, everything keeps working; during generation no connection other
   than `127.0.0.1` is opened (Linux `ss -tnp`, Windows Resource Monitor > Network).
8. No Turkish text in code (`app/`, `workers/`, scripts): a search for Turkish letters
   (`grep -rnP "[\x{00C7}\x{00E7}\x{011E}\x{011F}\x{0130}\x{0131}\x{00D6}\x{00F6}\x{015E}\x{015F}\x{00DC}\x{00FC}]"`)
   finds results only in `samples/`.
9. No audio files in the repo (`git ls-files | grep -iE "\.(wav|mp3|flac|ogg|m4a|webm)$"` is empty) and the README
   has Privacy and Responsible use sections.
10. The workspace criteria in the design doc (§11) hold.

## 10. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Microphone permission in the pywebview window (especially Linux) | No recording | Upload still works; tested on Windows. |
| pywebview on Linux needs Qt/GTK system packages | Harder install | README lists the packages. |
| A library writes outside `.local` | Criterion 3 fails | Measured per model; environment variables added as needed. |
| Long text exceeds a model's limit | Cut or broken audio | Split into lines; limits measured per model. |

## 11. Assumptions

- Python 3.11 (downloaded by uv).
- Code is entirely English: names, comments, log and error messages, interface text. Turkish appears only in
  `samples/` and in documents written for the maintainer (e.g. the Turkish part of the README).
- A model can be used without installing the others.

## 12. Open questions

None.
