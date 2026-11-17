# OmniVoice, Whisper and shared PyTorch — Design

Date: 2026-11-17 · Status: **implemented** (2026-11-17; sizes to be measured on Windows). Added during implementation at the
user's request: Whisper's detected language fills the sample's language.

> Items marked "*(proposal)*" are the designer's calls, not the user's; they can be revised.

## 1. Intent

Vokalit was built to compare several local models on the same line; so far it has only Chatterbox. This adds
**OmniVoice** (k2-fsa) as the second model, so the user can hear how it voices the same characters (Turkish
especially) next to Chatterbox. OmniVoice also brings **non-verbal sounds** written into the text (`[laughter]`,
`[sigh]`, …), a first step towards directing the delivery, which Chatterbox cannot do.

OmniVoice clones better when it knows what is said in the voice sample, so every new sample is saved with a
**transcript**: the optional, recommended local **Whisper** component fills it in after trimming, or the user types
it. Adding a second PyTorch model would also download PyTorch (~5 GB) a second time; models will **share
identical PyTorch files** on disk, without being able to break each other.

## 2. Goals / non-goals / anti-goals

**Goals**
1. **Whisper component, optional and recommended.** Its own row on the Models screen marked "Recommended", with the
   reason. Runs on the CPU (faster-whisper, `large-v3-turbo`, int8), so the GPU stays free for the voice models.
   Nothing requires it and nothing installs it implicitly.
2. **Transcripts (user's flow).** Adding a sample: record or upload → trim → the transcript field is filled by
   Whisper when installed (the user may edit it) or must be typed when not → Save becomes possible once the field
   has text. Installing Whisper also transcribes every existing sample without one. Saved transcripts are shown
   under the sample and can be corrected.
3. **OmniVoice** installs and removes like Chatterbox and generates takes wherever Chatterbox does: single line,
   Generate missing, bulk Generate, several models at once. It always receives the sample's stored transcript.
4. **Sound tags.** An "Add sound" menu next to the line text inserts a tag at the cursor.
5. **Models without tag support never read tags aloud** (user's requirement).
6. **Shared PyTorch.** Models that need the same package files share one copy on disk. Requirements (user's):
   installing a model never breaks another; any model can be removed at any time as today; everything this needs
   (sharing, clean-up) happens automatically, unseen.
7. The non-commercial weights license is stated where the user decides to install, and in the README.

**Non-goals (later)**
- Voice design (a character from a description such as "female, low pitch").
- OmniVoice's 600+ languages in the UI: it offers the languages Vokalit already lists *(proposal; a searchable
  600-language list is its own piece of work)*.
- A warning when exporting a session that contains OmniVoice takes.
- Voice conversion with OmniVoice (it has none; "Perform this line" keeps using Chatterbox).
- Whisper on the GPU.

**Anti-goals**
- Audio or text leaving the computer after install (Whisper and the models run with the network blocked).
- One model's install, update or removal breaking another model.
- Remove leaving disk space behind (once every model and Whisper are removed, `.local` holds no model files).
- Tags spoken as words by any model.
- Chatterbox generation stopping because a sample (e.g. one saved before this release) has no transcript
  (Chatterbox never uses them).

## 3. Facts this design relies on

Checked against the projects' pages (2026-11); the plan's first task re-checks them in the installed packages:
- **OmniVoice** `pip install omnivoice` (0.2.1); NVIDIA install uses `torch==2.8.0+cu128`, the same as Chatterbox.
  `OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16)`;
  `model.generate(text=..., ref_audio=..., ref_text=..., num_step=32, speed=1.0, ...)` returns a list of 24 kHz
  numpy arrays. Without `ref_audio` it uses a random "auto voice" (a seed makes it repeatable). Tags: `[laughter]`,
  `[sigh]`, `[confirmation-en]`, `[question-en]`, `[question-ah]`, `[question-oh]`, `[question-ei]`, `[question-yi]`,
  `[surprise-ah]`, `[surprise-oh]`, `[surprise-wa]`, `[surprise-yo]`, `[dissatisfaction-hnn]`. Code Apache 2.0;
  **weights CC-BY-NC** (because of the training data; no paid commercial license exists).
  Not yet known: how `generate` takes the language — the first task finds out.
- **faster-whisper**: the same Whisper weights on CTranslate2, same accuracy, no PyTorch; `WhisperModel(
  "large-v3-turbo", device="cpu", compute_type="int8")`; `transcribe(path, language=...)`. Turbo is near large-v3
  in English; if it is weak on the user's Turkish samples, switching to `large-v3` is a one-line change.
- **uv** installs packages by hard-linking files from its cache into the environment (Windows and Linux), and
  falls back to copying where hard links are impossible.

## 4. Approaches considered

**Transcripts**
- A. OmniVoice transcribes on every generation (its built-in Whisper) — slower every take, mistakes unseen.
- B. Transcribe each sample once inside the OmniVoice worker, store it, allow corrections — samples added before
  OmniVoice wait for their first OmniVoice take.
- C. Whisper as its own **required** component, transcribing every sample when it is added — considered and
  dropped by the user: it forces a download on everyone and an install order.
- D. **Filled in by an optional, recommended Whisper component before saving, or typed by the user; required to
  save** — *chosen by the user*: no forced download, and every new sample has a checked transcript.

**Whisper engine**
- PyTorch Whisper on the GPU: ~7 GB with its environment. **faster-whisper on the CPU** — *chosen*: ~1–2 GB,
  same accuracy, a few seconds per sample.

**PyTorch per model**
- Separate copies (today): simple, ~5 GB per model. **Shared files through one uv cache** — *chosen*: one copy of
  identical files, environments stay separate.

## 5. Design

### 5.1 Models screen
```
Component                Status                      License
Whisper  Recommended     Not installed · ~1.7 GB     MIT                     [Install]
Writes down what each voice sample says. Some models copy a voice better with it; without Whisper you type it.
Chatterbox Multilingual  Installed · frees 6.9 GB    MIT                     [Remove]
OmniVoice                Not installed               CC-BY-NC (non-commercial)  [Install]
All components: 15.2 GB
```
- Whisper is the first row, with a "Recommended" mark and the sentence above *(wording is a proposal)*.
- Installing or removing Whisper never affects the models. Removing it keeps the stored transcripts; new samples
  are then typed.
- Sizes: each component shows what removing it frees; a total line under the list. Both are measured after every
  install and remove (in the background), not on page load.
- OmniVoice's install confirmation: "License: CC-BY-NC — the model's weights may not be used commercially."

### 5.2 Shared package files
- All installs use one uv cache, `.local/shared/uv-cache`, instead of a per-model cache. Each component still has
  its own environment in `.local/<name>/venv`.
- Why one model cannot break another: an environment holds links to cache files; installing, upgrading or
  removing packages in one environment adds or removes links, never changes a file's contents. A model that needs a
  different version simply gets other files.
- **Automatic clean-up** after every install, cancel and remove, in the background: delete every unpacked package
  in the cache (`archive-v0/<id>/`) that no environment uses any more (all its files have a hard-link count of 1).
  uv's small index files stay — they are how uv finds a package it already has. When no component is installed,
  delete `.local/shared` entirely.
- Where hard links are impossible uv copies; then every cache file has a link count of 1 and the clean-up removes
  the whole cache — the same as today's behaviour.
- Two installs at the same time are not allowed (the Install buttons of other rows are disabled while one runs)
  *(proposal; keeps the clean-up simple)*.
- "frees X GB" = the size of the component's files that nothing else links to.
- Existing Chatterbox installs keep their own copies; nothing is migrated.
- Install progress ("N GB on disk") counts the component's folder plus the shared cache's growth since the install
  started, since downloads now land in the shared cache.
- The plan's first task confirms on Windows that uv hard-links (not copies) into the environments.

### 5.3 Whisper component
- A `components` entry "whisper" (installed and removed from the Models screen like a model, never offered for
  generation).
  Install: a small environment with `faster-whisper` (pinned) and the `large-v3-turbo` model downloaded into its
  cache.
- `workers/whisper/worker.py`, same protocol as the other workers (network blocked, `ready`, JSON lines):
  `{"task": "transcribe", "audio": path, "language": code-or-null}` → `{"ok": true, "text": "..."}`. Loads on first
  use; stopped when the app closes.
- Requests: transcribe a trimmed clip before it is saved (5.3a), and, after Whisper is installed, every saved
  sample without a transcript, one at a time in the background. The language picked for the sample (when set) is
  passed to Whisper.
- Sample field `transcript`: string; absent only for samples saved before this release.

### 5.3a Adding and editing transcripts
- The add-sample step (after trimming, before saving) gets a text field "What does this sample say?", and **Save
  is enabled only when it has text** (user's decision, for every sample, whichever models are installed).
  - Whisper installed: once trimming is done, the trimmed clip is sent to Whisper; the field shows "Transcribing…"
    and is filled with the result; the user may edit it. Changing the trim afterwards transcribes again unless the
    user has already edited the text *(proposal)*. If transcription fails, the field stays empty with the error
    under it and the user types.
  - A **"Transcribe again"** button beside the field (Whisper installed only) replaces the text with a fresh
    transcription of the current trim (user's idea).
  - Whisper not installed: under the field, "Type exactly what is said in the sample. Some models use it to copy
    the voice. Install Whisper on the Models screen to have it written for you." (with a link to Models). No model
    is named: more models that need transcripts will come (user's decision).
- The server refuses a new sample without a transcript.
- Under each saved sample (Characters screen and the session character card): the transcript in muted text with an
  edit pencil (an empty text cannot be saved) and, when Whisper is installed, "Transcribe again" (replaces the
  text). Samples saved before this release show "No transcript · Add" (and "Transcribing…" while Whisper works
  through them).
- Samples cannot change after saving, so a stored transcript stays valid; deleting a sample deletes it.
- Models declare `needs_transcript` (OmniVoice: true, Chatterbox: false). A take from such a model whose sample has
  no transcript (only older samples) fails with "This sample has no transcript. Add it on the Characters screen or
  install Whisper." Models that do not need it ignore transcripts.

### 5.4 OmniVoice model
- `MODELS["omnivoice"]`: title "OmniVoice", summary "600+ languages · cloning · sound tags", license
  "CC-BY-NC (non-commercial)", `supports_convert: False`, `supports_tags: True`, languages = the codes Vokalit
  lists, no `accent_setting`.
- Install steps: PyTorch with CUDA (same pins as Chatterbox, so shared), other libraries
  (`workers/omnivoice/requirements.txt`), `omnivoice==0.2.1`, model weights (OmniVoice only — it never transcribes;
  it is loaded so that its own Whisper is not loaded).
- `workers/omnivoice/worker.py` follows the Chatterbox worker; the generate request adds `ref_text`.
- Settings *(proposal)*: **Speed** 0.5–2.0, default 1.0 ("Above 1 is faster"); **Quality** = diffusion steps
  16–64, step 16, default 32 ("Higher sounds better but takes longer; 16 is quick").
- Seeds as for Chatterbox. A character with no sample: OmniVoice's random auto voice; the "default voice" wording
  gains "(random for OmniVoice unless a seed is set)".
- Disk size: measured on the user's Windows machine at first install, then written into `disk_gb`, README, SPEC.

### 5.5 Sound tags
- `MODELS[name]["supports_tags"]`; the known tag list lives in one place on the server and is sent to the UI.
- Before a model without tag support gets the text, every known tag is removed and doubled spaces collapsed; other
  bracketed text is left alone. If nothing is left, that model skips the line with the empty-line message.
- Line details: an "Add sound" button beside the text opens a menu with friendly names for all 13 tags
  *(proposal)*; choosing one inserts the tag at the cursor and saves the line. Shown when a tag-capable model is
  installed; tooltip "Only OmniVoice performs these sounds; other models skip them."
- Takes record the text as written, with tags.

### 5.6 Documentation
README (Whisper, OmniVoice row with license note, sizes, shared PyTorch in one sentence), SPEC §4–§6 ("emotion
tags" leaves out-of-scope), this file's status.

## 6. Constraints
- Everything in the repo in English; no network after install; each component in its own environment; tests run
  without a GPU or network (workers and uv stubbed); real-model checks by the user on Windows.
- VRAM: Chatterbox ~4 GB + OmniVoice (0.6B, fp16) fit in 12 GB; Whisper uses none.

## 7. Left to the builder
- How OmniVoice takes the language (after the first task's check).
- The tag menu's labels and look (existing popover styles).
- How sizes are cached and refreshed after clean-up.
