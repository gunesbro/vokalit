# SPEC — Vokalit

Local voice cloning and text-to-speech workspace.

> Status: **v2.0** (v1.14 was the Turkish single-page Gradio version; v2.0 is the workspace with our own UI).
> The workspace is specified in detail in `docs/workspace-design.md`;
> this file is the overview. Changes are made here (or in that design) first, then in code.

## 1. Purpose

Read text aloud in a voice cloned from a short reference recording (at least 10 s), entirely on the user's own
computer: no audio or text leaves the machine. Several open models can voice the same line so their results can be
compared. Work is organised in sessions (scripts with several characters, e.g. podcasts) and can be exported as one
file. Everything is done by clicking in a desktop window.

## 2. Scope (v2)

- Models: **Chatterbox Multilingual** (Resemble AI), **OmniVoice** (k2-fsa), **VoxCPM2** (OpenBMB) and
  **Higgs TTS 3** (Boson AI, via the pinned transformers packaging `multimodalart/higgs-audio-v3-tts-4b-transformers`
  and codec `bosonai/higgs-audio-v2-tokenizer`; full precision when >= 10.7 GB is free on loading, otherwise 8-bit,
  reported on the Models screen with the reason); the optional
  **Whisper** component (faster-whisper on the CPU) writes sample transcripts.
- Desktop window (pywebview) showing our own HTML/CSS/JS interface, served by a local server on `127.0.0.1`:
  - A line's text is edited in our own small editor: plain text with sound tags shown as chips (× removes one,
    typed `[laughter]` becomes a chip, paste is plain text, own undo history). Stored text keeps canonical tags;
    `MODELS[name]["sounds"]` converts each for the model, models without it drop them. `TAGS` is OmniVoice's 13
    sounds followed by Higgs TTS 3's controls (`HIGGS_TAGS`: effects, emotions, styles, delivery, hyphenated); the
    UI groups them as Sounds, Emotions, Styles and Delivery in *Add tag* and the `[` suggestions.
  - Language fields are search boxes (OmniVoice lists 646 languages); only languages every chosen model speaks are
    offered.
  - **Studio:** sessions; a cast of characters; script lines with takes; generate with one or more models; seed;
    generation settings at three levels (model defaults → session → line); voice conversion ("Perform this line");
    export of the selected takes to one file (WAV always; FLAC, MP3 and OGG Vorbis when the computer's libsndfile can
    write them). Export is enabled once every line has a take. An open line's export button (and its menu) exports only its selected take,
    without its pause, as `<session>-line-<n>-<time>.<fmt>`. Takes at a lower sample rate are converted to the
    highest one among the lines (linear interpolation), since VoxCPM2 writes 48 kHz and the others 24 kHz.
  - Settings are sliders (`min`, `max`, `step`) or, with `"type": "text"`, a text box (`max_length`, `placeholder`,
    `suggestions` as buttons that fill it). `models.clean_settings` checks them; text loses parentheses and extra
    whitespace. A line override equal to the session's value is not stored.
  - **Dub voice separation:** with the tool installed, transcribing a dub first separates its sound
    (`voices.wav`, `background.wav` next to `audio.wav`, written as `*.part.wav` and kept only when both are done,
    replacing a previous pair both or neither; a failure goes on with the full mix and says so); Whisper hears the
    voices, references are cut from them, and the export and preview play the background in full and the original
    voices at `voices_volume` (default 0, "Original voices"; `original_volume`, "Original", applies without stems).
    The More menu has "Separate voices (again)" and "Use the full mix" (deletes the stems). The timeline waveform is
    the voices'.
  - **Playback volume:** a speaker button at the bottom of the rail opens a slider (0-100 %, squared, kept between
    runs) and Mute; every sound the app plays follows it (players, Studio playback, the Dub preview), never exported
    or generated files (`volume.js`). It and the Dub panes' sizes are kept by the server (`GET`/`PATCH
    /api/preferences`, `.local/webview/preferences.json`): the page's own storage belongs to its address, whose port
    changes every launch.
  - **Characters:** a library of reusable voices, each with several labelled samples (recorded or uploaded, trimmed
    before saving), or designed from a description by OmniVoice (its attributes) or VoxCPM2 (free text).
    Session-only characters can be saved to the library.
  - **Models:** install / remove with size, GPU memory (`vram_gb`), location and license shown first; progress and a
    collapsible log.
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
- Resuming downloads, automatic updates. (Disk space is checked before an install: `models.needs_gb` is the size
  less PyTorch when it is already installed, plus 1 GB; the install is refused when that is more than is free.)

## 4. Models

| | Chatterbox Multilingual | OmniVoice | VoxCPM2 |
|---|---|---|---|
| Languages | 23 (Turkish via `language_id="tr"`) | 646, from its `utils/lang_map.py` (kept in `app/omnivoice_languages.json`); Vokalit's `ar` is sent as `arb` | 30 (from the model card; no language argument, it reads the text) |
| Size | ~500M parameters | ~0.6B parameters | 2B parameters |
| Measured disk use | 12.3 GB on Windows (libraries + weights) | ~9 GB estimate; PyTorch is shared with Chatterbox | 13.6 GB on Windows (8.6 GB environment, PyTorch shared; 5.0 GB weights) |
| VRAM | ~4.1 GB (measured, Windows) | ~2.6 GB (measured, Windows) | ~8.4 GB (measured, Windows: 5.8 GB loaded, 8.3 GB peak) |
| Reference | Audio file | Audio file + its transcript (`needs_transcript`; stored with every sample) | Audio file (`reference_wav_path`; no transcript, the mode its style instructions work in) |
| Sound tags (`[laughter]`, `[sigh]`, …) | No: removed from its text | Yes (`sounds`: each tag as itself) | No: removed from its text |
| Code license | MIT | Apache 2.0 | Apache 2.0 |
| **Weights license** | MIT | **CC-BY-NC (no commercial use)** | Apache 2.0 |
| Without a reference | Built-in default voice | "Auto Voice": random unless a seed is set | A random voice |
| Settings | Expressiveness, Pace control, Variation | Speed, Quality (diffusion steps, any whole number 16–64) | Style (text, sent as `(style)text`; parentheses in the line become commas), Style strength (`cfg_value` 1–3), Quality (`inference_timesteps` 4–30) |
| Voice conversion | Yes (`ChatterboxVC`) | No | No |
| Note | Adds a PerTh watermark to outputs | | 48 kHz output; denoiser and text normalizer off; `voxcpm==2.0.3` |

The license difference is shown in the install confirmation and in the README.

**Whisper** (`TOOLS["whisper"]`, never offered for generation): `faster-whisper==1.2.1`, model `large-v3-turbo`, int8
on the CPU (no PyTorch; the GPU stays free). Optional and recommended. When installed it transcribes a trimmed clip
before the sample is saved (the user can correct it) and detects its language; installing it transcribes every
sample without a transcript in the background. Without it the transcript is typed. A new sample cannot be saved
without a transcript; samples from before this rule fail only for models with `needs_transcript`.

**Voice separation** (`TOOLS["demucs"]`, Dub only): PyTorch (shared CUDA build) and `demucs==4.0.1`, model `htdemucs`,
on the GPU when there is one, else the CPU. It splits a dub's sound into voices (speech, singing) and background
(music, effects), one request per file, the network blocked like every worker. The code is MIT; the pretrained weights
have no clear license, so the install downloads them and Vokalit never ships them (shown on the Models screen).
`python worker.py --selftest` checks an install.

## 5. Architecture

```
┌──────────────────────────────────────────────┐
│ App process (.local/app/venv)                │
│  pywebview window ── HTTP ── local server    │  app/main.py, app/server.py
│  (app/ui: HTML/CSS/JS)        127.0.0.1      │  storage: app/workspace.py → workspace/
└──────┬───────────────┬───────────────┬───────┘
       │ JSON lines (stdin/stdout)     │
┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
│ Chatterbox  │ │ OmniVoice   │ │ VoxCPM2     │   each in its own venv;
│ worker      │ │ worker      │ │ worker      │   the model loads once and stays loaded
└─────────────┘ └─────────────┘ └─────────────┘
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
- The window does not run in private mode; its data is kept in `.local/webview/`. The server's port changes every
  launch, so the window's own memory of the microphone answer does not last: the page reports the answer
  (`POST /api/microphone`), "allowed" is kept as `.local/webview/microphone-allowed`, and on Windows the window then
  grants the microphone to Vokalit's own page without asking. After a block the flag is removed and it asks again.
- Samples, takes, recordings and exports are stored **unencrypted** in `workspace/` until the user deletes them.
  Temporary uploads go to `workspace/.tmp/`, which is cleared at start and exit.

**Workers (where audio is processed), enforced in code:**

- `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`.
- Before importing any library the worker blocks connecting, sending and name resolution
  (`socket.socket.connect`, `connect_ex`, `sendto`, `socket.getaddrinfo` raise). The `socket.socket` class itself
  is not replaced, because modules such as `ssl` subclass it at import. A library that tries the network stops
  with a clear error.
- GPU memory: before a model loads, other models that are not generating are unloaded (least recently used first)
  until `vram_gb` + 0.5 GB are free (`nvidia-smi`). An out-of-memory error, while loading or generating, does not
  crash the worker: the app unloads the other idle models and tries once more, then says "Not enough GPU memory for
  <model>…" with what to do.
- Several models in one batch (Generate missing, bulk Generate): model by model, so each loads once; a line keeps
  one seed across models, and a model that does not speak a line's language skips it.
- The Models screen shows, for each installed component, whether it is loaded right now (GPU memory as the worker
  reports it, "generating", or how long until it unloads for being idle) with an Unload button; it looks every 5 s.
  An install keeps being followed when the screen is left and opened again, or the window is reopened.
- A worker starts on its first request and is stopped after 5 minutes without one (`IDLE_SECONDS`), so models do
  not hold GPU memory while unused; the next request loads it again. A worker also exits when the app is gone,
  however it ended (its stdin closes).
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
  links, so one install cannot change another's files. After every install, cancel and remove, unpacked packages
  (`archive-v0/<id>/`) that no environment links to (every file has link count 1) are deleted; uv's small index files
  stay, so the next model finds PyTorch in the cache. `.local/shared/` goes with the last component. The clean-up
  waits for a running install; only one install runs at a time. Where hard links are impossible uv copies, and the
  clean-up empties the cache (each environment has its own copy).
- **Progress:** no percentage (download sizes are not known in advance). A bar with one segment per step: finished
  steps filled, the running one animated. Under it a status line updated every few seconds
  (`Step 2/5: PyTorch with CUDA · 1.42 GB on disk · 3m 12s`; size = growth of the model folder and the shared cache,
  hard links counted once),
  above a collapsible log.
- **Cancel** stops the running process within seconds and deletes `.local/<model>/`. Install always clears leftovers
  of an interrupted install first, and so does every start of the app (a folder without the `installed` marker:
  the app closed, crashed or lost power during an install). A finished install writes `.local/<model>/installed`.
- **Remove** shows the folder and the space it frees (files no other component links to), then, after confirmation,
  stops the worker and deletes `.local/<model>/`; then the shared cache is cleaned. The Models screen also shows the
  total of all components.

## 7. Interface

All interface text is English. The visual design is the design canvas; behaviour is specified in `docs/workspace-design.md`
(§7 Studio, Characters, Models). Summary:

- **Rail:** Studio, Characters, Models, and a GPU status dot.
- **Studio:** session list with search; header with session name, "Generate with" (multi-select of installed
  models), Settings (session settings per model), Seed, Export, Generate missing / Stop (cancels the take in progress: the model's process is stopped and loads again next time); cast strip; script rows
  (speaker, sample, text, selected take player) with drag-and-drop reordering, "+ Insert line" between lines and a
  ⋯ menu; line details with text, sample, pause, Generate with + seed, line settings ("Reset to session settings"),
  takes (select, play, "custom settings", "text changed", "Use these settings", delete) and "Perform this line";
  "Paste script" (`Name: text` lines; a name not in the cast uses the library character of that name when there is exactly one, otherwise a new session-only character); "Play all" in the footer plays the selected takes in order with each line's
  pause (previous/next, Space to pause, "Play from here" in the line menu; lines without takes are skipped).
  Lines can be ticked (Shift+click for a range, Ctrl+A for all, Esc to clear) for bulk Generate, Character, Sample,
  Pause (one value for all; empty with "mixed" when they differ), Delete takes and Delete lines; the session menu has "Delete empty lines".
- **Dub:** list of dubs (new from a file or by dropping one, rename, delete); import reads the file's sound in the
  window (MP4, WebM, WAV, MP3, M4A, OGG, FLAC; size and length shown, a warning past 20 minutes; a video whose sound
  the window cannot read asks for its audio as a separate file) and copies the file into `workspace/dubs/<id>/`;
  Whisper (timed segments, long ones split at sentence ends) makes the sentences, shared by every target language;
  each language is a tab ("+ Add language"; x removes one, confirmed, not undoable) with its own translations, takes,
  timing, model and settings (one dub track per language; old dubs migrate on load). Layout: top bar (name, source
  language -> language tabs, model, settings, progress "translated / voiced / too long", Undo/Redo, Generate missing, Export, Transcribe again);
  a compact table (#, time, original, translation edited in place, status), filters with counts (All, Untranslated,
  No take, Too long, Too short), "Copy for translation" (numbered, each line with the original's speaking time and the most its
  translation may take, until the next sentence: "[2.8 s, at most 3.4 s]"; an instruction naming the target language
  and asking for translations about as long as the original, never longer than the most) and "Paste
  translations" (placed by number, or in order, a copied-back time dropped; summary of found and missing; one request);
  only the rows in view are drawn (fixed 38 px rows; the row being typed in stays drawn), lookups are built once per
  change, and the timeline draws only the clips around its window, so tens of thousands of sentences stay quick;
  dub.json is written compact. Fit: a too-long take is sped up with the same pitch (WSOLA, `app/stretch.py`) to end
  0.05 s before the next sentence, as a new selected take that remembers its original (fitting again starts from it),
  up to 1.25x; beyond that, "Shorten the translation". "Fit" on the selected sentence, "Fit N" in the Too long tab (a
  job, cancellable); sped-up sentences stay under Too long, showing their speed ("1.18x") in the table, the details
  and the takes list; Too long splits into Can fit (needs at most 1.25x, from the original take), Fitted, and Need
  shorter (more than 1.25x, or no time before the next sentence; the reason is shown); likewise Too short (a take ending more than 0.4 s before its speaker,
  or before the next sentence): Can lengthen (slowed to at most 0.85x it ends within 0.4 s of its speaker), Lengthened,
  Need longer, with "Lengthen N"; "Use originals N" (and "Use the original" on one sentence) selects the takes
  stretched ones were made from, undoable; the only installed model that
  speaks a language is also chosen when a job ends (an import opens the screen while Whisper listens); on the right the video
  (muted; or a clock for audio) with the original under the takes through Web Audio, and the selected sentence:
  original text (the voice sample's transcript), translation, Voice from (a search list; default this sentence; never neighbours,
  which may be another speaker), takes to pick and play, Generate, Delete; below, the timeline (`timeline.js`: lanes and
  clips in seconds, a ~30 s window that follows the playhead, zoom, the original's waveform, overlaps in red, Dub
  clips dragged). Playback marks the sentence being played and selects it unless you are typing. Keys: Up/Down,
  Enter (edit), Ctrl+Enter (generate), Space, K (keep the original). "Keep the original here" marks a sentence (on
  the source clip, so in every language): it is left out of translating, Generate and the "Untranslated"/"No take"
  filters (an "Original" filter lists them); the preview and the export play the original at full volume there,
  with 50 ms fades, and skip its takes. Undo/Redo (Ctrl+Z, Ctrl+Shift+Z/Ctrl+Y outside text boxes), per dub
  while the app runs, last 100 steps: text and translation edits, pasted translations, moves, Voice from, take
  choice, deleted sentences (their take files stay until the dub is deleted), generations (the previous takes are
  selected again, in one request), fits (likewise), model, language, settings, volume, name. Transcribing again is confirmed and not undoable; so is "Delete all takes of <language>" (in the menu: every take of
  the language shown, files included; sentences and translations stay; that language's take steps leave the undo list).
  With the separation tool the menu also has "Separate voices (again)" (a job, cancellable; Whisper is skipped when
  it is cancelled before listening) and "Use the full mix…" (confirmed; deletes the stems); the volume slider then
  reads "Original voices" (the background always plays in full), otherwise "Original". The rail's speaker button
  sets the master playback volume.
- **Characters:** list; editable name; "used in" sessions; delete (confirmed, lists sessions); samples table
  (★ default, play, label, waveform, length/source, delete); add a sample by recording (microphone choice, timer,
  level, 10 s hint) or upload, then trim and "Add sample"; or "Design voice": model (designable models that are not
  installed are listed but disabled), language, a default ~15-20 s text, the description (OmniVoice: gender, age, pitch,
  English accent selects and Whisper; VoxCPM2: a text box), "Generate 3 voices" (Cancel while running; candidates under 10 s are
  marked "Too short" and cannot be kept) and "Keep this one", which opens the same review with the text, language and description (as the label) filled in; the source is
  "designed". The open Design panel keeps its choices, running job and results while the app runs, so leaving the
  screen and coming back shows them again. Note: "Only use your own voice or voices you have permission to use."
- Coming back to Studio or Characters opens the session or character that was open last (while the app runs), not
  the first in the list.
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
├── docs/                      # workspace design (workspace-design.md) and README images
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
10. The workspace criteria in `docs/workspace-design.md` (§11) hold.

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
