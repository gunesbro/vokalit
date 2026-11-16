# Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Vokalit into a workspace with sessions, a character library (multiple samples per character), a line-by-line script with takes, voice conversion, seeds and export.

**Architecture:** A UI-free storage module `app/workspace.py` owns every file under `workspace/` (JSON + WAV). `app/models.py` and the Chatterbox worker gain `seed`, settings and a `convert` task. **(Revised after Task 0, spec §4.1)** The UI is our own HTML/CSS/JS in `app/ui/`, served with its JSON API by a standard-library HTTP server (`app/server.py`) on 127.0.0.1 with a per-run token, shown in the pywebview window. Gradio is removed.

**Tech Stack:** Python 3.11, stdlib `http.server`/`wave`/`json`, pywebview, soundfile, numpy, plain JavaScript (ES modules, Web Audio API, HTML5 drag-and-drop), pytest + `node --test` (dev only), chatterbox-tts 0.1.7 (`ChatterboxMultilingualTTS`, `ChatterboxVC`).

**Spec:** `docs/superpowers/specs/2026-11-16-workspace-design.md` (read it first; section numbers below refer to it). **Visual design:** https://claude.ai/artifact/C1nriBHz4bLm6CuxN3s3gR (Studio, line details, settings, Characters, Models). Gradio will approximate it with a custom CSS theme; Task 0 measures how close it gets.

## Global Constraints

- All code, comments, UI text and repository documents are English. User data may be any language.
- User data lives only under `workspace/`; `.gitignore` contains `workspace/` (the old `voices/` line is removed).
- Messages are shown on the page (a message line).
- The UI loads nothing from outside 127.0.0.1: no CDN, no web fonts; CSP `default-src 'self'; media-src 'self' blob:; img-src 'self' data:`.
- Every API request needs the per-run token (header `X-Vokalit-Token`); `Host` must be `127.0.0.1:<port>`; `/files/` serves only inside `workspace/`.
- Minimum sample length: 10 seconds (`MIN_SAMPLE_SECONDS = 10`).
- Default pause after a line: 0.3 s (`DEFAULT_PAUSE = 0.3`).
- Take file name: `<line no, 2 digits>-<character-slug>-<model>-take<n>.wav`; export: `exports/<session-slug>-<YYYYmmdd-HHMMSS>.wav`.
- IDs: `YYYYmmdd-HHMMSS`, collisions get `-2`, `-3`, …; sample IDs `s1`, `s2`, …; line IDs `l1`, `l2`, … (never reused within a session).
- JSON writes are atomic (write `*.tmp`, then `os.replace`).
- Workers keep the network block (SPEC §5.3); no new network access anywhere.
- Every generated or converted take is written as 16-bit PCM WAV (`subtype="PCM_16"`), so export can join them with stdlib `wave`.
- Tests run with `python3 -m pytest tests -q` and `node --test app/ui/tests/` from the repo root, without GPU, network or real models.

## Review Focus

1. **Non-ASCII names in paths** (e.g. a character name with Turkish letters, in a OneDrive path): IDs are ASCII and slugs fold to ASCII → `test_slugify_folds_to_ascii` (Task 1).
2. **App killed while saving:** `session.json` must stay readable → `test_failed_save_keeps_previous_file` (Task 2).
3. **A take file deleted by hand or missing:** export reports which line, no crash → `test_export_reports_missing_take_file` (Task 3).
4. **Library character deleted while sessions use it:** sessions still load; lines keep the ID; take records intact; generation is refused with a message → `test_deleted_character_keeps_sessions_loadable` (Task 2) + UI check (Task 5).
5. **Pasted scripts with blank lines, wrapped lines and colons inside text** ("Host: It's 10:30"): split on the first colon only; blank lines ignored; a line without `Name:` continues the previous line → `test_paste_script_edge_cases` (Task 2).

---

## File Structure

| File | Responsibility |
|---|---|
| `app/workspace.py` (new) | All reads/writes under `workspace/`: characters, samples, sessions, cast, lines, takes, recordings, export, slugs, IDs. No Gradio. |
| `app/models.py` (modify) | `generate(..., seed)`, new `convert(...)`; install unchanged except VC download. |
| `workers/chatterbox/worker.py` (modify) | Seed, `task: "convert"` with lazily loaded `ChatterboxVC`, VC in `--download`, PCM_16 output. |
| `app/main.py` (rewrite) | Starts the server and the window. |
| `app/server.py` (new) | Local HTTP server: token, CSP, static UI, `/files/`, JSON API, background jobs. |
| `app/ui/` (new) | HTML/CSS/JS screens (Studio, Characters, Models), audio helpers, Node tests. |
| `tests/conftest.py` (new) | `tmp_workspace` fixture; `soundfile` shim (PCM_16 WAV via `wave` + numpy) used only when real `soundfile` is missing; helper `make_wav(path, seconds, sr=24000)`. |
| `tests/stubs/` (new) | Fake `torch`, `chatterbox.mtl_tts`, `chatterbox.vc` for worker tests. |
| `tests/test_characters.py`, `tests/test_sessions.py`, `tests/test_takes_export.py`, `tests/test_worker.py` (new) | Unit tests. |
| `requirements-dev.txt` (new) | `pytest`, `numpy`. |
| `SPEC.md`, `.gitignore` (modify) | English SPEC reflecting this design; `workspace/` ignored. |

---

### Task 0: Spike — drag-and-drop and the line row in Gradio (throwaway)

**Questions:** (a) can rows drawn with `@gr.render` be reordered by dragging, reliably, in the pywebview window? (b) how close can custom CSS get one collapsed line row (speaker, text, selected-take player, hover-only controls) and the line details panel to the canvas design?

- [ ] **Step 1:** In a scratch file outside `app/` (not committed), render 5 rows with `@gr.render`; inject a small script with `gr.Blocks(head=...)` that makes each row draggable (HTML5 drag events on a handle) and on drop writes the new ID order into a hidden `gr.Textbox`, then dispatches an `input` event; a `.change` handler prints the order and re-renders.
- [ ] **Step 2 (user, Windows):** drag rows 10 times, including after adding/removing rows (re-render). Pass = order always correct, no stuck state, no console errors.
- [ ] **Step 2b:** In the same scratch app, style 3 rows and one opened details panel with `gr.Blocks(css=...)` against the canvas; user compares side by side.
- [ ] **Step 3:** Report to the user. Drag pass → Task 7 implements dragging the same way and keeps ↑↓ in the ⋯ menu. Fail → ↑↓ only. If the row/panel look is far from the canvas, the user decides: accept the Gradio approximation or move the Studio editor to approach B (spec §4). Record the outcome in the design doc. Delete the scratch file either way.

### Task 1: Characters and samples storage

**Files:**
- Create: `app/workspace.py`, `tests/conftest.py`, `tests/test_characters.py`, `requirements-dev.txt`
- Modify: `.gitignore` (replace `voices/` block with `# User data (sessions, characters, recordings).\nworkspace/`)

**Interfaces:**
- Produces (in `app/workspace.py`):
  - `class WorkspaceError(Exception)` — message is user-facing English.
  - `MIN_SAMPLE_SECONDS = 10`, `DEFAULT_PAUSE = 0.3`
  - `init(root: Path) -> None` — sets the workspace root (default `ROOT/"workspace"` at import; tests call `init(tmp_path)`).
  - `slugify(text: str) -> str`
  - `new_id(parent: Path) -> str` — time-based, unique among `parent`'s children.
  - `character_dir(char_id: str, session_id: str | None = None) -> Path` (`None` = library)
  - `create_character(name: str, session_id: str | None = None) -> str`
  - `load_character(char_id: str, session_id: str | None = None) -> dict | None` (`None` if missing)
  - `list_characters(session_id: str | None = None) -> list[tuple[str, dict]]` (newest first)
  - `rename_character(char_id, name, session_id=None) -> None`
  - `add_sample(char_id, source_path: str, source: str, session_id=None) -> str` — converts any soundfile-readable input to PCM_16 WAV `samples/<id>.wav`; raises `WorkspaceError("The sample is 7.4 seconds long. It must be at least 10 seconds.")` when short; first sample becomes default; default label `"sample N"`.
  - `set_sample_label(char_id, sample_id, label, session_id=None)`, `set_default_sample(...)`, `delete_sample(...)` (default moves to the first remaining sample or `None`)
  - `sample_path(char_id, sample_id: str | None, session_id=None) -> Path | None` (`None` sample → default; no samples → `None`)
  - `delete_character(char_id: str) -> None` (library only; removes the folder)
  - `wav_duration(path: Path) -> float` (stdlib `wave`)

- [ ] **Step 1: Write failing tests** in `tests/test_characters.py`:
  - `test_slugify_folds_to_ascii`: `slugify("K\u0131z\u0131l \u015eahin!") == "kizil-sahin"`, `slugify("  ") == "x"`. (Write non-ASCII test input as escapes and map dotless i with the escape `\u0131`; no Turkish literals in code or tests.)
  - `test_create_and_list_characters`: two characters → `list_characters()` returns both, newest first; IDs differ even when created in the same second.
  - `test_add_sample_converts_and_sets_default`: 12 s WAV → sample `s1`, label `"sample 1"`, `default_sample == "s1"`, file exists and `wav_duration == 12.0` (±0.01).
  - `test_add_short_sample_is_rejected`: 7.4 s → `WorkspaceError` whose message contains `"7.4 seconds"`; no file written.
  - `test_delete_default_sample_moves_default`: s1, s2; delete s1 → default `s2`; delete s2 → default `None`, `sample_path(cid, None) is None`.
  - `test_unknown_sample_falls_back_to_default`: s1, s2 (default s1); delete s2 → `sample_path(cid, "s2")` returns the path of s1 (lines that used a deleted sample fall back to the default, spec §7.2).
  - `test_session_only_character_lives_in_session`: `create_character("Guest", session_id="S")` → under `sessions/S/characters/`.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_characters.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement** the functions above in `app/workspace.py`, the `tmp_workspace` fixture, `make_wav`, and the `soundfile` shim in `tests/conftest.py`.
- [ ] **Step 4: Run** the same command → PASS.
- [ ] **Step 5: Commit** `feat: character and sample storage`.

### Task 2: Sessions, cast and script lines

**Files:**
- Modify: `app/workspace.py`
- Create: `tests/test_sessions.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `create_session(name: str | None = None) -> str` (default name `"Session YYYY-MM-DD HH:MM"`)
  - `list_sessions() -> list[tuple[str, dict]]` (newest first)
  - `load_session(session_id) -> dict`, `save_session(session_id, data: dict) -> None` (atomic)
  - `rename_session(session_id, name)`, `delete_session(session_id)`
  - `add_to_cast(session_id, char_id, scope: "library" | "session")`, `remove_from_cast(session_id, char_id)` → `WorkspaceError("Burak is used by lines 1, 3. Change those lines first.")` when used
  - `save_as_character(session_id, char_id) -> None` — moves the folder to the library, sets scope `"library"`
  - `cast_character(session, char_id) -> dict | None` — loads from the right scope; `None` if deleted
  - `add_line(session_id, char_id, text="", pause_after=DEFAULT_PAUSE, after: str | None = None) -> str` (`after` = insert after that line ID; `None` = append)
  - `reorder_lines(session_id, line_ids: list[str]) -> None` (must be a permutation of the current IDs, else `WorkspaceError`)
  - `update_line(session_id, line_id, **fields)` — allowed: `character`, `sample`, `text`, `pause_after`
  - `move_line(session_id, line_id, delta: int)`, `delete_line(session_id, line_id)` (deletes its take files)
  - `paste_script(session_id, text: str) -> int` (lines added)
  - `sessions_using(char_id) -> list[str]` (session names, for delete confirmations)

- [ ] **Step 1: Write failing tests** in `tests/test_sessions.py`:
  - `test_session_roundtrip`: create, add library char + session char to cast, add 3 lines → `load_session` returns the same cast/lines/order.
  - `test_failed_save_keeps_previous_file`: `save_session` with an unserializable value raises; the file on disk still loads with the previous content and no `*.tmp` remains.
  - `test_remove_used_character_is_refused`: message names the character and the line numbers.
  - `test_save_as_character_moves_folder`: folder now under `workspace/characters/`, cast scope `"library"`, and a second session can `add_to_cast` it.
  - `test_move_and_delete_line`: order changes; deleting removes the line's take files.
  - `test_insert_line_after`: lines l1, l2; `add_line(..., after="l1")` → order l1, l3, l2.
  - `test_reorder_lines_requires_permutation`: `reorder_lines` with a missing or extra ID raises `WorkspaceError`; a valid permutation is saved.
  - `test_paste_script_edge_cases`: input `"Host: Hello\n\nGuest: It's 10:30\nand still going\nHost: Bye"` → 3 lines; line 2 text `"It's 10:30 and still going"`; new `Guest` is session-only with no samples; `Host` matched case-insensitively to an existing cast member.
  - `test_deleted_character_keeps_sessions_loadable`: delete a library character used in a session → `load_session` works, `cast_character(...) is None`, takes unchanged.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_sessions.py -q` → FAIL.
- [ ] **Step 3: Implement** the functions.
- [ ] **Step 4: Run** all tests → PASS.
- [ ] **Step 5: Commit** `feat: sessions, cast and script lines`.

### Task 3: Takes, recordings and export

**Files:**
- Modify: `app/workspace.py`
- Create: `tests/test_takes_export.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `new_take_path(session_id, line_id, model: str) -> Path` — name rule from Global Constraints; `n` = number of existing takes of the line + 1.
  - `new_recording_path(session_id, line_id) -> Path` — `recordings/<line no 2 digits>-take<n>.wav`
  - `set_session_models(session_id, models: list[str])`, `set_session_settings(session_id, model: str, settings: dict)`, `reset_session_settings(session_id, model)` (stored in `session.json`, spec §6)
  - `set_line_settings(session_id, line_id, model: str, overrides: dict)`, `reset_line_settings(session_id, line_id)`
  - `effective_settings(session: dict, line: dict, model: str, defaults: dict) -> dict` (defaults ← session ← line)
  - `take_has_custom_settings(session: dict, take: dict) -> bool`
  - `add_take(session_id, line_id, take: dict) -> None` — `take` holds the §6 fields (including `seed` and `settings` for tts); `file` is stored relative to the session folder; becomes `selected` if the line has none.
  - `select_take(session_id, line_id, file)`, `delete_take(session_id, line_id, file)` (removes the file; selects the newest remaining)
  - `take_text_changed(line: dict, take: dict) -> bool` (only for `kind == "tts"`)
  - `export_session(session_id) -> Path`

- [ ] **Step 1: Write failing tests** in `tests/test_takes_export.py`:
  - `test_take_names_and_selection`: two takes on line 1 for character "Burak" → names `01-burak-chatterbox-take1.wav`, `01-burak-omnivoice-take2.wav`; first is selected; deleting it selects the second.
  - `test_export_joins_selected_takes_and_pauses`: takes 1.0 s and 2.0 s, pauses 0.5 and 0.3 → export duration 3.8 s (±0.01), sample rate 24000, file under `exports/`.
  - `test_export_refuses_lines_without_takes`: message `"Lines 2, 3 have no takes yet."`; no file created.
  - `test_export_reports_missing_take_file`: selected file removed from disk → `WorkspaceError` naming line 1.
  - `test_export_refuses_mixed_sample_rates`: 24000 vs 16000 → `WorkspaceError` mentioning both rates.
  - `test_effective_settings_layers`: defaults `{a:1,b:2}`, session `{a:3}`, line `{b:4}` → `{a:3,b:4}`; `reset_line_settings` → `{a:3,b:2}`; `reset_session_settings` → `{a:1,b:2}`.
  - `test_custom_settings_flag`: a take whose settings differ from the session's → true; equal → false.
  - `test_text_changed_flag`: edit the line text → `take_text_changed` true for the old tts take, false for a convert take.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_takes_export.py -q` → FAIL.
- [ ] **Step 3: Implement** using stdlib `wave` and numpy for silence (`int16` zeros, `round(pause * sr)` frames).
- [ ] **Step 4: Run** all tests → PASS.
- [ ] **Step 5: Commit** `feat: takes, recordings and export`.

### Task 4: Seed and voice conversion in the worker and models

**Files:**
- Modify: `workers/chatterbox/worker.py`, `app/models.py`
- Create: `tests/stubs/torch/__init__.py`, `tests/stubs/chatterbox/{__init__,mtl_tts,vc}.py`, `tests/test_worker.py`

**Interfaces:**
- Consumes: protocol in spec §8.
- Produces:
  - `models.generate(name, text, ref, out, seed: int, settings: dict) -> float` (seconds)
  - `models.MODELS[name]["settings"]: list[dict]` — `{key, label, min, max, step, default, help}`; Chatterbox: `exaggeration` "Expressiveness" 0.25–2.0 step 0.05 default 0.5; `cfg_weight` "Pace control" 0.0–1.0 step 0.05 default 0.5; `temperature` "Variation" 0.05–5.0 step 0.05 default 0.8 (help texts as on the canvas Settings artboard)
  - `models.default_settings(name) -> dict`, `models.validate_settings(name, settings: dict) -> dict` (fills defaults; `ValueError` on unknown key or out-of-range value)
  - `models.convert(name, source, ref, out) -> float` — `RuntimeError("Chatterbox Multilingual does not support voice conversion.")` style message for models without it (only `"chatterbox"` supports it; mark with `"supports_convert": True` in `MODELS`).
  - `models.MODELS[name]["supports_convert"]: bool`
  - Worker: `torch.manual_seed(request["seed"])` when `seed` is present; `task == "convert"` → `ChatterboxVC` loaded on first use (`ChatterboxVC.from_pretrained(device="cuda")`, `vc.generate(audio=source, target_voice_path=ref)`, `vc.sr`); `--download` also calls `ChatterboxVC.from_pretrained(device="cpu")`; outputs written with `subtype="PCM_16"`.

- [ ] **Step 1: Write failing tests** in `tests/test_worker.py` (they install a stub "model" with empty `pip_steps` into a temp `.local`, as in the earlier manual harness; need `uv` and `python3.11` on PATH):
  - `test_seed_is_applied`: stub torch records the last seed; the stub model returns it in the output → output file contains `seed=42`.
  - `test_settings_are_passed_to_generate`: `settings={"exaggeration": 0.7}` → stub `generate` received `exaggeration=0.7`, `cfg_weight=0.5`, `temperature=0.8`.
  - `test_unknown_setting_is_rejected`: `validate_settings("chatterbox", {"foo": 1})` and `{"exaggeration": 9}` raise `ValueError`.
  - `test_convert_uses_vc_and_default_voice`: `convert(..., ref=None)` → stub VC called with `target_voice_path=None`; VC loaded once across two calls.
  - `test_default_voice_restored_after_clone`: keep the existing regression (clone → default uses built-in conds).
  - `test_network_still_blocked_in_convert`: stub VC tries a socket connect → reply `ok: false` with "Network access is blocked".
  - `test_download_loads_vc`: install log shows both stub loads on `cpu`.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_worker.py -q` → FAIL.
- [ ] **Step 3: Implement** worker and models changes.
- [ ] **Step 4: Run** all tests → PASS.
- [ ] **Step 5: Commit** `feat: seed and voice conversion`.
- [ ] **Step 6 (user, Windows):** remove and reinstall Chatterbox; record the new "Disk usage" and update `disk_gb` in `MODELS`. Same seed + text twice → identical audio.

### Task 5: Local server and API

**Files:**
- Create: `app/server.py`, `tests/test_server.py`
- Modify: `app/main.py` (start the server and the window; remove Gradio), `app/requirements.txt` (drop `gradio`; keep `soundfile`, `numpy`, `pywebview`), `start.sh`/`start.bat` (drop Gradio env vars; keep `GRADIO_TEMP_DIR` → rename to `VOKALIT_TEMP_DIR`)


**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `server.start(ui_dir: Path, port: int = 0) -> tuple[str, str]` (base URL, token), `server.stop()`. Routes (all JSON unless noted; `{"error": "..."}` with HTTP 400 for `WorkspaceError`/`ValueError`):
  - `GET /` → `ui/index.html` with the token injected as `<meta name="vokalit-token">`; `GET /ui/<file>` static.
  - `GET /files/<relative path under workspace>` → audio (`audio/wav`), 404 outside `workspace/`.
  - Models: `GET /api/models` (title, url, license, disk_gb, installed, size_gb, settings, supports_convert), `POST /api/models/<name>/install` → job, `POST /api/models/<name>/cancel`, `POST /api/models/<name>/remove`.
  - Characters: `GET/POST /api/characters`, `GET/PATCH/DELETE /api/characters/<id>` (`?session=` for session-only), `POST /api/characters/<id>/samples` (body: WAV bytes, `?source=recording|upload`), `PATCH/DELETE /api/characters/<id>/samples/<sid>`.
  - Sessions: `GET/POST /api/sessions`, `GET/PATCH/DELETE /api/sessions/<id>`, cast (`POST/DELETE /api/sessions/<id>/cast`, `POST .../cast/<cid>/save`), lines (`POST .../lines`, `PATCH/DELETE .../lines/<lid>`, `POST .../lines/order`, `POST .../paste`), settings (`PUT .../settings/<model>`, `DELETE .../settings/<model>`, `PUT/DELETE .../lines/<lid>/settings`), takes (`POST .../lines/<lid>/generate` → job, `POST .../lines/<lid>/convert` body WAV → job, `POST .../lines/<lid>/takes/select`, `DELETE .../lines/<lid>/takes`), `POST .../generate-missing` → job, `POST .../stop`, `POST .../export` → job.
  - Jobs: `GET /api/jobs/<id>` → `{"state": "running"|"done"|"failed", "progress": str, "log": str, "result": any, "error": str}`.

- [ ] **Step 1: Write failing tests** in `tests/test_server.py` (start the server on port 0 with a temp workspace; call it with `urllib`):
  - `test_token_required`: API call without the token → 403; with it → 200.
  - `test_foreign_host_refused`: `Host: evil.example` → 403.
  - `test_files_path_traversal_refused`: `/files/../app/server.py` and an encoded `%2e%2e` variant → 404.
  - `test_page_has_token_and_csp`: `GET /` contains the token meta tag; response has the CSP header.
  - `test_session_lifecycle_over_api`: create session, add character + line, `PATCH` text, reorder → `GET` shows the change.
  - `test_workspace_error_is_400_with_message`: removing a used character → 400 with the workspace message.
  - `test_sample_upload_wav`: POST 11 s WAV bytes → sample listed; 7 s → 400 "must be at least 10 seconds".
  - `test_generate_job_with_fake_model`: monkeypatch `models.generate` to write a WAV; generate job reaches `done` and the line has a take.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_server.py -q` → FAIL.
- [ ] **Step 3: Implement** `app/server.py`; `app/main.py` starts it and opens `webview.create_window("Vokalit", url)` (private_mode False, storage in `.local/webview`, `--lang=en-US`).
- [ ] **Step 4: Run** all tests → PASS.
- [ ] **Step 5: Commit** `feat: local server and API; remove Gradio`.

### Task 6: UI shell and Models screen

**Files:**
- Create: `app/ui/index.html`, `app/ui/styles.css`, `app/ui/app.js` (router, API client with token, message line, job polling), `app/ui/models.js`

Behavior: left rail (Studio, Characters, Models, GPU status), the Models screen of the canvas (status, size, license, link opening in the system browser, Install with confirmation, progress bar + percentage, collapsible log, Cancel, Remove with confirmation). Colors, spacing and type from the canvas (`#111214` background, `#e9a15b` accent, system fonts).

- [ ] **Step 1 (user, Windows):** start the app; Models screen matches the canvas; install/cancel/remove work; external link opens in the browser.
- [ ] **Step 2: Run** all tests → PASS.
- [ ] **Step 3: Commit** `feat: UI shell and Models screen`.

### Task 7: Characters screen and browser audio helpers

**Files:**
- Create: `app/ui/audio.js` (pure: `encodeWav(samples: Float32Array, sampleRate) -> ArrayBuffer`, `trim(samples, sampleRate, startSec, endSec) -> Float32Array`, `peaks(samples, buckets) -> number[]`; browser: `record(deviceId)`, `decodeFile(file)`), `app/ui/waveform.js`, `app/ui/characters.js`, `app/ui/tests/audio.test.mjs`

**Interfaces:** `characters.samplePanel(container, charId, sessionId|null)` reused by Studio for session-only characters.

- [ ] **Step 1: Write failing tests** in `app/ui/tests/audio.test.mjs`: `encodeWav` header (RIFF, 16-bit, mono, rate, data length) and clipping at ±1; `trim(…, 1, 2)` length = 1 s of samples; `peaks` returns `buckets` values in 0..1.
- [ ] **Step 2: Run** `node --test app/ui/tests/` → FAIL.
- [ ] **Step 3: Implement** helpers, waveform, Characters screen per canvas (list, rename, samples with ★/▶/label/delete, record with microphone choice + timer + 10 s hint, trim range, upload, delete character listing sessions).
- [ ] **Step 4: Run** node and pytest suites → PASS.
- [ ] **Step 5 (user, Windows):** record, trim, upload mp3, set default, delete sample; spec §11 criteria 5, 10.
- [ ] **Step 6: Commit** `feat: Characters screen`.

### Task 8: Studio screen

**Files:**
- Create: `app/ui/studio.js` (sessions list + search, header with Generate with multi-select, Settings popover, Export, Generate missing/Stop; cast strip; script rows with drag-and-drop, hover controls, insert-line dividers; line details panel with takes, line settings, Perform this line; paste script dialog), `app/ui/settings.js`

Decisions: rows follow the canvas exactly; one details panel open at a time; drag uses HTML5 DnD on the row handle and calls `POST .../lines/order`; ↑/↓ stay in the ⋯ menu; "Use these settings" fills the seed field and the line settings.

- [ ] **Step 1 (user, Windows):** spec §11 criteria 1–4, 6–9, 13, 14 and Review Focus 4–5.
- [ ] **Step 2: Run** all tests → PASS.
- [ ] **Step 3: Commit** `feat: Studio screen`.

### Task 9: SPEC in English and cleanup

**Files:**
- Modify: `SPEC.md` (translate to English; replace §5.2/§7/§7.1 with a summary and a pointer to the design doc), `.gitignore` (drop `outputs/`), README not in scope.

- [ ] **Step 1:** `grep -rnP "[\x{00C7}\x{00E7}\x{011E}\x{011F}\x{0130}\x{0131}\x{00D6}\x{00F6}\x{015E}\x{015F}\x{00DC}\x{00FC}]" --exclude-dir=.git --exclude-dir=.superpowers . | grep -v "^./samples/"` → no output.
- [ ] **Step 2:** all tests → PASS; `git status` clean after a manual run.
- [ ] **Step 3: Commit** `docs: English SPEC for the workspace`.
