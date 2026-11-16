# Vokalit Workspace — Design

Date: 2026-11-16 · Status: **approved** (v4 — UI approach changed to B)

Visual design (canvas): https://claude.ai/artifact/C1nriBHz4bLm6CuxN3s3gR — Studio, line details, settings, Characters, Models.

> Items marked "*(proposal)*" are the designer's calls, not the user's; they can be revised.

## 1. Intent

Vokalit is currently a one-shot tool: one reference voice, one text, one result. Recordings and
results are gone when the app closes. The goal is a **workspace people can come back to**:

- A voice (character) is created once and reused across sessions.
- Every generated clip records **which character/sample, which model and which text** produced it.
- Each piece of work is a separate **session**; old sessions can be reopened.
- **Podcast-style, multi-character** work is possible.
- The same line can be generated with **several models** and compared (the project's origin).
- Emotion and delivery are controlled in ways the models **actually support**: several voice samples
  per character (e.g. "calm", "excited"), and converting the user's own performance of a line into
  the character's voice.

What users do with the generated audio is their responsibility; the app does not police use.

## 2. Goals / non-goals / anti-goals

**Goals (this release)**
1. Sessions: create, list, open, rename, delete.
2. Characters: a library independent of sessions; each character has one or more labelled voice samples.
3. Session cast: library characters + session-only characters; a **Save as character** button moves a session-only character into the library.
4. Script: lines (character, sample, text, pause after); insert a line between any two lines; **drag-and-drop reordering** if the spike in the plan (Task 0) shows it works reliably in Gradio, otherwise up/down buttons.
5. Per-line generation; model(s) chosen at generation time; every attempt (take) is kept.
6. **Voice conversion (Chatterbox VC):** the user records the line, it is converted to the character's voice and becomes a take.
7. **Seed and generation settings, three levels:** model defaults → session settings (per model) → line settings (per model, overriding the session for that line's next takes). Each level resets to the one above ("Reset to model defaults", "Reset to session settings"). Each take records the seed and the settings it was generated with and shows "custom settings" when they differed from the session.
8. Choose a take (★), regenerate a single line, delete takes.
9. Export: selected takes + pauses → one audio file.

**Non-goals (later releases)**
- With OmniVoice: voice design (character from a description), recording prep (denoise, normalize,
  auto-transcribe). This design must accommodate them.
- Tags such as `[laughter]`, reading numbers.
- **Fine-tuning on your own recordings** (training a model for a character). Planned for the Characters screen later; see §6 extension point.
- Sound effects, fine-tuning, LLM text suggestions.
- Keyboard shortcuts.
- Transcript import (SRT/VTT, timestamps, screenplay format). User decision: later, possibly with a local language model. The simple `Character: text` paste stays.
- Cloud-sync folder warning (user decision: not needed).

**Anti-goals (failure even if it works)**
- Voice, text or output leaves the computer.
- User work is lost (unsaved script, lost recordings, outputs gone on close).
- UI that pretends a model supports something it does not (e.g. a free-text "instruction" box that does nothing).

## 3. Constraints

- pywebview window showing our own HTML/CSS/JS UI (approach B, §4). Messages are shown on the page.
- Models run in separate worker processes using the JSON-lines protocol (SPEC §5.2); this design adds two fields (§8).
- Models take **one** reference recording per generation; several samples means choosing one per line (they are not merged).
- Both models output 24 kHz mono.
- Code, UI and repository documents are English. User data (character names, labels, script text) may be in any language.
- Public repository: user data must never enter git.

## 4. Approaches

| | A) Stay on Gradio (**chosen**) | B) Custom web UI |
|---|---|---|
| How | Script editor drawn per line count with `@gr.render` | HTML/JS UI in the same window + small Python server |
| Pros | Builds on current code; one language; recorder, trim and player included | Full control, smooth editor |
| Cons | Gradio quirks; no drag-and-drop; may slow down on long scripts | 3–4× more code; recorder/trim/waveform from scratch |

Rejected: a Gradio custom component (needs a JS build toolchain; B's difficulty plus A's limits).

~~Choice A~~ — tried in the plan's Task 0 spike: Gradio could not get close to the canvas design and
drag-and-drop did not work. **Choice B**, user decision (2026-11-16): "write the UI ourselves". Storage
(`app/workspace.py`) and model layers (`app/models.py`, workers) are unchanged.

### 4.1 Architecture for B (builder's calls)

- **Server:** Python standard library `http.server.ThreadingHTTPServer` on `127.0.0.1`, a free port chosen at start.
  No web framework: fewer dependencies, smaller install, everything readable. Gradio is removed.
- **Access token:** a random token is generated at start and put into the page URL; every API request must send it
  (header `X-Vokalit-Token`). Other programs or websites on the same computer cannot use the API. Requests with a
  `Host` other than `127.0.0.1:<port>` are refused.
- **Content Security Policy:** every page response sends `default-src 'self'; media-src 'self' blob:; img-src 'self' data:`
  so the UI cannot load anything from the internet, even by mistake.
- **API:** JSON endpoints that map one-to-one to `workspace` / `models` functions; long operations (install,
  generation, export) run as background jobs that the UI polls (`GET /api/jobs/<id>`).
- **Files:** `GET /files/<path>` serves audio only from inside `workspace/`; paths are resolved and anything outside
  is refused.
- **UI:** `app/ui/` — `index.html`, `styles.css`, plain JavaScript modules; no build step, no external libraries,
  no CDN. Pure helpers (WAV encoding, trimming, waveform peaks) are tested with Node's built-in test runner.
- **Audio in the browser:** recording uses the Web Audio API and is encoded as 16-bit WAV in JavaScript; uploaded files
  (mp3, m4a, ogg, wav) are decoded with `decodeAudioData` and also sent as WAV. The server only ever receives WAV.
  Microphone choice via `enumerateDevices`. Trimming is a draggable range on the waveform before a sample is saved.
- **Drag-and-drop:** native HTML5 drag events on script rows; the new order is sent to `reorder_lines`.

## 5. User decisions

- Every generation is kept; which voice, model and text produced it is recorded.
- Sessions are separate; old ones can be reopened.
- Multi-character (podcast-style) work is in scope.
- The model is chosen **at generation time**; a line can be generated with several models; the model is recorded and **hinted in the file name**.
- UI technology: our own HTML/CSS/JS (approach B), after the Gradio spike failed.
- Characters can be created outside sessions; a character created inside a session moves to the library **via a button**, otherwise it stays in that session only.
- A character can have several voice recordings.
- No cloud-sync folder warning.
- This release: voice conversion and seed. With the OmniVoice step: voice design and recording prep.
- Lines can be inserted between lines and reordered by dragging.
- Transcript import is postponed.
- Generation settings in this release, at session level (header Settings button) and line level (line details), each resettable to the level above; fine-tuning later on the Characters screen, and the structure must allow it.
- The model choice must scale to many models (a multi-select dropdown, not side-by-side checkboxes).

## 6. Data model and storage

All user data lives under `workspace/` in the project root *(proposal: one folder = easy backup, one `.gitignore` line)*.

```
workspace/
├── characters/<character-id>/
│   ├── character.json
│   └── samples/<sample-id>.wav
└── sessions/<session-id>/
    ├── session.json
    ├── characters/<character-id>/...   # session-only characters, same layout
    ├── recordings/*.wav                # the user's own recordings for voice conversion
    ├── takes/*.wav
    └── exports/*.wav
```

- IDs derive from creation time (`20261116-161400`); collisions get `-2`, `-3`.
- A session-only character has **the same layout** as a library one; "Save as character" moves the folder to `workspace/characters/` and updates the session's reference.
- Files are readable JSON *(proposal: transparency — users can see what is stored where)*.

### character.json

```json
{
  "name": "Burak",
  "created": "2026-11-16T16:30:00",
  "default_sample": "s1",
  "samples": [
    {"id": "s1", "label": "calm",    "file": "samples/s1.wav", "duration": 12.4, "source": "recording", "created": "..."},
    {"id": "s2", "label": "excited", "file": "samples/s2.wav", "duration": 11.0, "source": "upload",    "created": "..."}
  ]
}
```

- **Extension point for fine-tuning (later):** a character may get `"finetunes": {"<model>": {"path": "finetunes/<model>/", "created": "..."}}` and a `finetunes/` folder; samples are the training data source. Workers will accept an optional `checkpoint` path. Nothing of this is built now; the layout must not block it.
- A character may have no samples: it then uses **the model's default voice** (for OmniVoice that means a random voice per generation; the UI says so).

### session.json

```json
{
  "name": "Episode 1",
  "created": "2026-11-16T16:14:00",
  "models": ["chatterbox"],
  "settings": {"chatterbox": {"exaggeration": 0.7, "cfg_weight": 0.5, "temperature": 0.8}},
  "cast": [
    {"character": "20261116-163000", "scope": "library"},
    {"character": "20261116-164500", "scope": "session"}
  ],
  "lines": [
    {
      "id": "l1",
      "character": "20261116-163000",
      "sample": null,
      "text": "We're talking about local AI today.",
      "pause_after": 0.3,
      "settings": {"chatterbox": {"exaggeration": 1.1}},
      "selected": "takes/01-burak-chatterbox-take2.wav",
      "takes": [
        {
          "file": "takes/01-burak-chatterbox-take2.wav",
          "kind": "tts",
          "model": "chatterbox",
          "character_name": "Burak",
          "sample_label": "calm",
          "text": "We're talking about local AI today.",
          "seed": 1234567,
          "settings": {"exaggeration": 0.7, "cfg_weight": 0.5, "temperature": 0.8},
          "created": "2026-11-16T16:20:11",
          "generation_seconds": 2.1,
          "duration": 3.4
        },
        {
          "file": "takes/01-burak-chatterbox-vc-take3.wav",
          "kind": "convert",
          "model": "chatterbox-vc",
          "character_name": "Burak",
          "sample_label": "calm",
          "source_recording": "recordings/01-take3.wav",
          "created": "...", "generation_seconds": 1.2, "duration": 3.6
        }
      ]
    }
  ]
}
```

- `line.sample`: `null` = the character's default sample; otherwise a sample ID.
- `line.settings`: only the keys that override the session, per model; `{}` = follow the session. Effective settings = model defaults ← session ← line.
- **A take record is a snapshot:** text, character name, sample label, model and seed are stored as they were at generation time. History stays correct if the line is edited or the character/sample is deleted later.
- **File name** *(proposal)*: `<line no, 2 digits>-<character-slug>-<model>-take<n>.wav`. The line number is the position at generation time and is not updated if lines move (a hint only; `session.json` is authoritative). Slug: lowercase, ASCII-folded, non-alphanumerics → `-`.
- **Autosave:** `session.json` / `character.json` are written on every change (temp file, then rename — never half-written). There is no Save button.

## 7. Screens

Three tabs: **Studio**, **Characters** and **Models** (user decision: models get their own screen).

### 7.0 Models

One row per model: name (link to the model page, which lists supported languages), status and disk usage,
license, Install/Remove with the confirmation box, progress line, Cancel install and the collapsible install
log — the existing Models section, moved to its own tab. Studio shows checkboxes only for installed models;
with none installed it shows "Install a model in the Models tab." 

### 7.1 Studio

```
┌ Sessions ─────────┐ ┌ Episode 1 ─────────────────────────────────────────────────────┐
│ ● Episode 1       │ │ Cast                                                           │
│   Intro test      │ │  Burak  (library)                                    [✕]       │
│   ...             │ │  Guest  (this session)  [Save as character]          [✕]       │
│ [+ New session]   │ │  [+ Add from library ▾]  [+ New character in session]          │
│                   │ │                                                                │
│ [Delete session]  │ │ Models: [✓] Chatterbox  [ ] OmniVoice     Seed: [random ]      │
└───────────────────┘ │                                                                │
                      │ 1 [Burak ▾][calm ▾] [We're talking about...    ] pause[0.3] ↑↓✕│
                      │   Takes: ▶ chatterbox #1 ▶ chatterbox #2 ★  [Generate] [Convert]│
                      │ 2 [Guest ▾][—    ] [Sounds great.              ] pause[0.3] ↑↓✕│
                      │   Takes: (none)                             [Generate] [Convert]│
                      │ [+ Line]   [Paste script…]                                     │
                      │                                                                │
                      │ [Generate missing lines] [Stop]  [Export]   message line       │
                      └────────────────────────────────────────────────────────────────┘
```

- **Sessions:** list (newest first), new session (default name "Session 2026-11-16 16:14"), name editable in the header *(proposal)*, delete (confirmed, permanent: the folder is removed, including session-only characters — the confirmation says so).
- **Cast:**
  - **Add from library:** adds a library character to the cast (a reference, not a copy).
  - **New character in session:** a session-only character (name + optional samples, using the same sample component as the Characters tab, in a small panel inside the cast).
  - **Save as character:** moves a session-only character to the library so other sessions can use it.
  - A character used by lines cannot be removed from the cast (explained in the message line).
- **Generate with:** a multi-select dropdown of installed models; closed it shows the selected names ("3 models" when long). Stored as `session.models` (default: first installed model *(proposal)*). Line and batch generation produce one take **per selected model**. The line details panel has the same dropdown for that generation.
- **Session settings:** the header Settings button opens a panel under it with one tab per selected model (sliders with help text) and "Reset to model defaults"; stored in `session.settings`.
- **Line settings:** in the line details, "Settings for this line" shows the same sliders per model; changed values are highlighted with the session value next to them ("Session: 0.70") and a count ("1 change from session settings"); "Reset to session settings" clears `line.settings`. Settings are declared per model in `models.MODELS[name]["settings"]` (key, label, min, max, step, default, help), so a new model brings its own.
- **Seed:** empty = random (the value used is stored in the take); filled = that value. "Use these settings" on a take copies its seed into the seed field and its settings into that line's settings *(proposal)*.
- **Line (collapsed, see canvas):** speaker (color dot, name, sample label under it), text, and on the right the selected take's player with "<model> · N takes" — or a Generate button when there are none. Drag handle and ⋯ menu (Convert, Delete, Move up/down) appear on hover. Pause shows on the divider between lines ("0.3 s pause"); "+ Insert line" appears there on hover, adding an empty line with the previous line's character.
- **Line details (opened by clicking a line):** edit text, sample and pause; "Generate with" dropdown + seed + "Generate N takes"; line settings (above); the takes list (select, play, model, seed, "custom settings" mark, "Use these settings", delete); "Perform this line" (voice conversion).
- **Takes:** each take has a player + label (model or "converted", take no., sample label), ★ select, delete. The first take is selected automatically. If the selected take is deleted, the newest remaining take is selected *(proposal)*. If the line's text differs from the take's text, the take shows "text changed" *(proposal)*.
- **Convert:** opens a record/upload area under the line; the user performs the line; Chatterbox VC converts it to the line's character/sample. The user's recording is kept in `recordings/` (to convert again).
- **Paste script…** *(proposal)*: paste `Character: text` lines; characters not in the cast are added as **session-only** characters (without samples); lines are appended.
- **Generate missing lines:** generates lines that have no takes, in order; progress in the message line ("Line 3/12…"). **Stop** stops after the current line *(proposal)*.
- **Export:** the selected take of each line + `pause_after` silence, in order → `exports/<session-slug>-<time>.wav`, shown with a player and download. If any line has no takes, nothing is exported and the message lists those lines.

### 7.2 Characters

```
┌ Characters ─────────┐ ┌ Burak ───────────────────────────────────────────────────────┐
│ ● Burak   2 samples │ │ Name [Burak                ]         used in 2 sessions      │
│   Narrator 1 sample │ │ Samples                                                      │
│   ...               │ │  ★ calm      12.4 s  ▶  label[calm     ]           [Delete]  │
│ [+ New character]   │ │    excited   11.0 s  ▶  label[excited  ]           [Delete]  │
│                     │ │ Add a sample: [Upload | Record] (Gradio trim available)      │
│                     │ │   → added automatically when recording stops / upload ends   │
│                     │ │ Only use your own voice or voices you have permission to use.│
│                     │ │ [Delete character]                                           │
└─────────────────────┘ └──────────────────────────────────────────────────────────────┘
```

- A finished recording/upload becomes a sample when the user confirms the trim ("Add sample"); without trimming it is one click. Default label "sample N", editable. ★ sets the default sample.
- Trimming: drag the start/end handles on the new recording's waveform, then it is added. Added samples are not trimmed again *(proposal)*; re-record instead.
- Audio shorter than 10 s is not added as a sample (the message states its length).
- **Delete character:** confirmed, permanent. Sessions using it are listed in the confirmation; afterwards they show it as "deleted character", lines remain but a different character must be chosen to generate *(proposal)*. Existing take records are kept.
- **Delete sample:** confirmed; lines using it fall back to the default sample.

## 8. Generation flow and worker protocol

**Text to speech (tts):**
1. Line character + sample → `ref` (sample file path) or `None` (character without samples → model default voice).
2. Seed is chosen (random if the field is empty).
3. One request per checked model; output is written straight to `takes/`.
4. The take is added to `session.json`; it becomes the selected take if the line has none.
5. If one model fails, the others continue; the error is shown in the message line.

**Voice conversion (convert):** the user's recording is saved to `recordings/` → conversion request to the Chatterbox worker → take (`kind: "convert"`, `model: "chatterbox-vc"`).

**Protocol additions (SPEC §5.2):** (`settings` keys must be declared in that model's settings schema; unknown keys are rejected)

```
→ {"text": "...", "ref": "<path>|null", "out": "<path>", "seed": 1234567, "settings": {...}}   # tts
→ {"task": "convert", "source": "<path>", "ref": "<path>|null", "out": "<path>"}          # Chatterbox only
← {"ok": true, "out": "<path>", "seconds": 1.2}
```

- Missing `task` means `tts` (backward compatible).
- The Chatterbox worker applies the seed with `torch.manual_seed` (+ CUDA) before generating.
- The conversion model (`ChatterboxVC`) loads on the first conversion request and stays loaded. `ref: null` → VC's built-in voice.
- **Install:** the VC model files must also be downloaded at install time (`--download` also loads VC). Existing Chatterbox installs must be reinstalled (currently one user). Which extra files are downloaded and the measured size are verified during the build.

## 9. Privacy

- `workspace/` is in `.gitignore`; the root `voices/` line is removed.
- The temp folder (`.local/tmp`) behaves as before; samples and conversion recordings are **copied** into `workspace/`.
- Voice conversion also runs in the worker, under the network block.

## 10. Relation to existing code

- `app/models.py`: install/worker management unchanged; `generate()` takes a seed; new `convert()`.
- `workers/chatterbox/worker.py`: seed, `task: "convert"`, VC in `--download`.
- `app/main.py` starts the local server and the window; `app/server.py` (new) holds the API; `app/ui/` (new) the page. Storage is `app/workspace.py`, tested without any UI.
- The `outputs/` folder goes away (replaced by `takes/` and `exports/`). No migration (no users yet).
- SPEC.md is updated (translated to English, §7 and §7.1 replaced by this structure).

## 11. Success criteria

1. A session with two characters (one from the library, one session-only) and 3 lines is created; after closing and reopening the app, everything (cast, lines, sample choices, takes, ★) is restored.
2. Generating a line with two models produces two takes whose labels and file names show the model.
3. Regenerating a line adds a take and keeps the old ones; ★ changes the selection.
4. Same text, sample, model and seed produce the same audio (verified for Chatterbox).
5. Takes made with two samples of a character ("calm", "excited") are audibly different and record the right label.
6. Convert: the user's recording becomes the character's voice; the take shows as "converted"; the source recording is in `recordings/`.
7. After "Save as character", the character can be added to another session's cast; the first session keeps using it from the library.
8. Export joins selected takes and pauses in order into one file (duration = takes + pauses).
9. After editing a line's text, the old take keeps the old text and shows "text changed".
10. Deleting a character/sample does not break existing take records.
11. `git status` never shows `workspace/` content.
12. Unit tests for `app/workspace.py` (create session/character, save/load, Save as character, export join, delete), `app/server.py` (token, Host check, path traversal, endpoints) and the JS audio helpers.
13. Drag-and-drop reorders lines reliably in the app window (10 drags, including after adding/removing lines).
14. The page loads nothing from outside `127.0.0.1` (verified with the window's network inspector or by running offline).

## 12. Left to the builder

- Exact layout and labels follow the canvas; small deviations are the builder's call.
- Rendering performance on long scripts (100+ lines) is measured; virtualizing may be added if slow (ask the user first).
- Slug and ID details.
- Which files VC downloads and the effect on install size.
