# OmniVoice, Whisper and Shared PyTorch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OmniVoice as a second voice model, an optional Whisper component that writes sample transcripts, sound tags, and shared PyTorch files between model environments.

**Architecture:** Components (Whisper as a tool, voice models) install into `.local/<name>/venv` through one shared uv cache whose hard-linked files are cleaned automatically. Each component has a worker speaking the existing JSON-lines protocol; the server stores a `transcript` on every sample and passes it to models that declare `needs_transcript`. Tags are stripped from text for models without `supports_tags`.

**Tech Stack:** Python 3.11 stdlib server, uv, pywebview, vanilla ES modules; faster-whisper (CPU, int8, `large-v3-turbo`); omnivoice 0.2.1 on torch 2.8.0+cu128.

**Spec:** `docs/superpowers/specs/2026-11-17-omnivoice-design.md`

## Global Constraints

- Everything in the repo is English; non-ASCII characters in code and tests are written as escapes (`ç`); the
  check `grep -rnP "[\x{00C7}\x{00E7}\x{011E}\x{011F}\x{0130}\x{0131}\x{00D6}\x{00F6}\x{015E}\x{015F}\x{00DC}\x{00FC}]" app workers tests` prints nothing.
- No network after install: workers call `block_network()` before importing libraries; installs download everything
  generation needs.
- Each component has its own environment `.local/<name>/venv`; nothing is migrated for existing Chatterbox installs.
- Tests run without GPU or network: `python3 -m pytest tests -q` and `node --test "app/ui/tests/*.test.mjs"` both pass
  after every task. Real models are checked by the user on Windows.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and **no** session URL line
  (user's instruction); push with `timeout 120 git -c push.negotiate=true push` to `main`.
- Copy fixed by the spec (verbatim):
  - Whisper row: "Writes down what each voice sample says. Some models copy a voice better with it; without Whisper you type it."
  - Add-sample hint without Whisper: "Type exactly what is said in the sample. Some models use it to copy the voice. Install Whisper on the Models screen to have it written for you."
  - Missing transcript at generation: "This sample has no transcript. Add it on the Characters screen or install Whisper."
  - OmniVoice license in the install confirmation: "License: CC-BY-NC — the model's weights may not be used commercially."
  - Tag menu tooltip: "Only OmniVoice performs these sounds; other models skip them."

## Review Focus

1. **Clean-up during an install** — a cache file freshly downloaded (link count 1) must never be deleted before uv links it: clean-up waits for a running install (test in Task 1).
2. **Removing one model while another uses shared files** — the other model's environment keeps every file and still works (test in Task 1).
3. **Turkish transcripts** sent with a new sample (`transcript=Merhaba, çok güzel`) arrive intact (test in Task 2).
4. **A line that is only tags** (`[laughter]`) generated with Chatterbox is skipped with the empty-line message, not sent as an empty string (test in Task 6).
5. **Older samples without a transcript** — OmniVoice fails with the spec's message, Chatterbox still generates (test in Task 5).

---

### Task 0: Windows spike (user runs it)

**Files:**
- Create: `scripts/spike_2026_11_17.py` (throwaway; deleted in Task 7)

**Interfaces:**
- Produces: ledger rulings for later tasks — the OmniVoice `generate` language keyword, how to load OmniVoice without its own Whisper, the pinned `faster-whisper` version, and whether hard links work.

- [ ] **Step 1: Write the spike script.** Run with `uv run --python 3.11 scripts/spike_2026_11_17.py` from the repo root; uses only the stdlib and `uv` (`VOKALIT_UV` or `uv` on PATH); works in a temp folder next to `.local` (same drive); prints one JSON report and deletes its folder. Checks:
  - Two venvs installed with the same `UV_CACHE_DIR` and `UV_LINK_MODE=hardlink`, each with `six==1.16.0`: for `six.py` in both, report `os.stat(...).st_ino` equality and `st_nlink` (expected 3: cache + 2 venvs).
  - A third venv with `uv pip install --no-deps omnivoice==0.2.1`: read the installed `omnivoice` sources as text and report the full `def generate(` signature, the `def from_pretrained(` signature (or the class `__init__` kwargs mentioning `asr`), and every line containing `language`.
  - `uv pip install faster-whisper` in a fourth venv: report its version and whether `python -c "import faster_whisper, ctranslate2"` succeeds.
- [ ] **Step 2: Ask the user to run it on Windows and paste the output.** Record each finding in the ledger as `Task 0: Ruling: ...`. If `st_nlink` is not 3, stop and bring it to the user: the shared-cache design (Task 1) rests on it.
- [ ] **Step 3: Commit** `scripts/spike_2026_11_17.py` with "chore: spike script for OmniVoice and shared packages".

### Task 1: Shared package files, install lock, sizes

**Files:**
- Modify: `app/models.py` (install, remove, `_run` env, sizes)
- Modify: `app/server.py:88-97` (`_model_view` sizes), `app/main.py` (startup clean-up)
- Test: `tests/test_shared.py`

**Interfaces:**
- Produces:
  - `models.shared_dir() -> str` = `os.path.join(LOCAL, "shared")`; the uv cache is `shared_dir()/uv-cache`.
  - Install env adds `UV_CACHE_DIR=<shared>/uv-cache`, `UV_LINK_MODE=hardlink`; the per-model `uv-cache` folder is gone.
  - `models.install(name)` raises `RuntimeError("Another install is running. Wait for it to finish.")` when one runs.
  - `models.installing() -> str | None` — name of the running install.
  - `models.clean_shared_cache() -> None` — waits for a running install; deletes cache files with `st_nlink == 1` and empty dirs; deletes `shared_dir()` when no component is installed.
  - `models.refresh_sizes() -> dict` and `models.sizes() -> dict`, shape `{"frees": {name: gb}, "total_gb": gb}`, stored in `LOCAL/sizes.json`; `sizes()` computes once when the file is missing.
  - `_model_view` replaces `size_gb` with `frees_gb` (from `sizes()`), and the list views get `total_gb` in Task 2's `/api/components`.
  - `installed_size_gb` and the marker's size content are no longer read (marker file stays as the "installed" flag).

- [ ] **Step 1: Write the failing tests** in `tests/test_shared.py` (fake components built with `os.link` from a fake cache under `tmp_path`, `models.LOCAL` monkeypatched; a fake `_run` that links cache files into the venv):
  - `test_two_models_share_cache_files`: after installing A and B, a cache file linked into both has `st_nlink == 3`; `sizes()["frees"]` counts it for neither; `total_gb` counts it once.
  - `test_remove_keeps_files_another_model_uses`: remove A, wait for the background delete; B's linked file exists with unchanged content and `st_nlink == 2`; A-only files are gone from the cache.
  - `test_last_remove_deletes_the_shared_folder`: remove A and B; `not os.path.exists(models.shared_dir())`.
  - `test_cleanup_waits_for_a_running_install`: start an install generator that is paused after creating a cache file with link count 1; call `clean_shared_cache()` in a thread; it has not returned and the file still exists; finish the install; the cleanup returns.
  - `test_second_install_is_refused`: while one install generator is open, `list(models.install("other"))` raises `RuntimeError` matching "Another install is running".
  - `test_downloaded_archives_are_cleaned_after_install`: a cache file never linked into a venv is deleted when the install ends.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_shared.py -q`. Expected: FAIL (`shared_dir` missing).
- [ ] **Step 3: Implement in `app/models.py`.** One `threading.Lock` held for the whole install (acquired non-blocking → the "Another install" error); clean-up and `refresh_sizes` run after the lock is released, also after a failed or cancelled install; `remove()`'s background thread runs rmtree → `clean_shared_cache()` → `refresh_sizes()`. Progress line size = one walk over the component folder and the shared cache with a shared seen-inode set, minus the cache size at install start. Frees algorithm: per component, group its files by `(st_dev, st_ino)`; a file frees space when its occurrences inside the folder equal `st_nlink`. `main.py` calls `clean_shared_cache()` in a background thread next to `delete_removed()`.
- [ ] **Step 4: Run** `python3 -m pytest tests -q`. Expected: all pass (update `tests/test_speed.py` expectations that read the old marker size to read `frees_gb`).
- [ ] **Step 5: Commit** "feat: models share identical package files; automatic clean-up".

### Task 2: Whisper component and transcripts on the server

**Files:**
- Modify: `app/models.py` (`TOOLS`, `spec(name)`, `_request`, `transcribe`)
- Create: `workers/whisper/worker.py`, `tests/stubs/faster_whisper/__init__.py`
- Modify: `app/workspace.py` (sample transcript), `app/server.py` (routes, background transcription), `app/main.py`
- Test: `tests/test_whisper.py`, `tests/test_characters.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: Task 1 install/remove/sizes (tools install and remove through the same functions).
- Produces:
  - `models.TOOLS = {"whisper": {"title": "Whisper", "summary": "Writes down what each voice sample says. Some models copy a voice better with it; without Whisper you type it.", "url": "https://github.com/SYSTRAN/faster-whisper", "license": "MIT", "disk_gb": 1.7, "recommended": True, "pip_steps": [("faster-whisper", ["faster-whisper==<Task 0 version>"])]}}`.
  - `models.spec(name) -> dict` (MODELS or TOOLS; `KeyError` otherwise); install, remove, cancel, titles and workers use it.
  - `models._request(name, message) -> dict` (the reply); `_ask` keeps returning `seconds` on top of it.
  - `models.transcribe(audio: str, language: str | None) -> str`; raises `RuntimeError("Whisper is not installed.")` when missing.
  - Worker protocol: `{"task": "transcribe", "audio": path, "language": code|null}` → `{"ok": true, "text": "...", "seconds": n}`. `--download` loads `WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")`; serving loads it the same way after `block_network()`; no CUDA check.
  - `ws.add_sample(char_id, source_path, source, session_id=None, transcript=None) -> str` stores `"transcript"` when given.
  - `ws.set_sample_transcript(char_id, sample_id, text, session_id=None) -> None` — `WorkspaceError("A transcript cannot be empty.")` for blank text.
  - `ws.samples_without_transcript() -> list[tuple[str, str | None, str]]` — `(char_id, session_id, sample_id)` over the library and every session's characters.
  - Routes:
    - `GET /api/components` → `{"items": [view...], "total_gb": gb}`; tools first; each view has `"kind": "tool"|"model"`, `"recommended"`, `"frees_gb"`, plus the model fields of `_model_view`; `"installing"`: name or null.
    - `POST /api/transcribe?language=xx` (raw WAV body) → `{"text": "..."}`; 400 with "Whisper is not installed." when missing.
    - `POST /api/characters/<cid>/samples?source=...&transcript=...` → 400 "Write what the sample says first." when `transcript` is blank.
    - `PATCH .../samples/<sid>` accepts `{"transcript": "..."}`.
    - `POST .../samples/<sid>/transcribe` → re-transcribes the saved sample (with its language) and returns the character.
    - Install/cancel/remove routes accept tool names (validate with `spec`).
  - Character views mark `"transcribing": true` on samples queued or being transcribed in the background.
  - `server.transcribe_missing() -> None` — background thread, one sample at a time; started after Whisper's install succeeds and at app start when Whisper is installed.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_whisper.py` (real worker subprocess with the stub, like `tests/test_worker.py`): `test_transcribe_returns_text` (stub echoes `"heard:<file name>:<language>"`), `test_network_blocked_in_whisper_worker`, `test_transcribe_without_whisper_is_refused`.
  - `tests/test_characters.py`: `test_sample_keeps_its_transcript`, `test_empty_transcript_is_refused`, `test_samples_without_transcript_lists_library_and_session_characters`.
  - `tests/test_server.py`: `test_new_sample_needs_a_transcript` (400 without, 200 with), `test_turkish_transcript_arrives_intact` (`transcript=Merhaba, çok güzel` URL-encoded → stored exactly), `test_transcribe_endpoint_without_whisper` (400 + message), `test_components_lists_whisper_first`, `test_missing_transcripts_are_written_in_the_background` (fake `models.transcribe`; two old samples get transcripts; `transcribing` is true while the fake blocks).
- [ ] **Step 2: Run** `python3 -m pytest tests -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the interfaces above. Background transcription uses one worker thread and a set of `(cid, session_id, sample_id)` keys for `transcribing`; a failure logs to stderr and leaves the sample without a transcript.
- [ ] **Step 4: Run** `python3 -m pytest tests -q`. Expected: all pass.
- [ ] **Step 5: Commit** "feat: Whisper component; samples keep a transcript".

### Task 3: Models screen with components

**Files:**
- Modify: `app/ui/models.js`, `app/ui/styles.css`

**Interfaces:**
- Consumes: `GET /api/components` (Task 2); install/cancel/remove routes.

- [ ] **Step 1: Switch the screen to `/api/components`.** Whisper row first with a "Recommended" tag next to its title and its summary sentence; status "Installed · frees N GB" / "Not installed · ~N GB"; a line "All components: N GB" under the list; while any install runs (`installing` or a local job) every other Install button is disabled with title "Another install is running."; OmniVoice's confirmation shows the license line from Global Constraints when `license` starts with "CC-BY-NC".
- [ ] **Step 2: Verify in the browser harness** (dev server with fake installs, `/home/claude/dev`): screenshot shows the Whisper row first with "Recommended", the total line, and a disabled Install on another row during a fake install.
- [ ] **Step 3: Run** both test suites. Expected: pass.
- [ ] **Step 4: Commit** "feat: Models screen lists Whisper and shows shared sizes".

### Task 4: Transcripts on the Characters screen

**Files:**
- Modify: `app/ui/characters.js` (`samplePanel`, `addSample.showReview`, `sampleRow`), `app/ui/styles.css`

**Interfaces:**
- Consumes: `/api/components` (is Whisper installed), `POST /api/transcribe`, sample routes with `transcript` (Task 2).

- [ ] **Step 1: Add-sample review.** A textarea "What does this sample say?" under the range editor. Whisper installed: transcribe the trimmed clip when the review opens and 800 ms after the last range change, unless the user has typed in the field; show "Transcribing…" meanwhile; a "Transcribe again" button always replaces the text; an error shows under the field and leaves it editable. Whisper not installed: the hint from Global Constraints with a link to `#/models`. "Add sample" is enabled only when the range is long enough **and** the field has text; the POST adds `&transcript=<encodeURIComponent(text)>`.
- [ ] **Step 2: Sample rows.** Under each row (full width): the transcript in muted text with an edit pencil (inline textarea, Save/Cancel; blank text keeps Save disabled); "Transcribe again" when Whisper is installed; "No transcript · Add" when absent; "Transcribing…" when `sample.transcribing`. Rows refresh every 2 s while any sample is transcribing.
- [ ] **Step 3: Verify in the browser harness** with a fake `/api/transcribe`: the field fills after opening a review, typing stops auto-fill, Save stays disabled while empty; the same panel inside the Studio character card shows transcripts.
- [ ] **Step 4: Run** both test suites. Expected: pass.
- [ ] **Step 5: Commit** "feat: write or check the transcript when adding a sample".

### Task 5: OmniVoice model

**Files:**
- Modify: `app/models.py` (`MODELS["omnivoice"]`, `generate` signature), `app/server.py` (`_line_context`, `_generate_line`), `app/ui/studio.js` (default voice wording)
- Create: `workers/omnivoice/worker.py`, `workers/omnivoice/requirements.txt`, `tests/stubs/omnivoice/__init__.py`
- Test: `tests/test_worker_omnivoice.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: Task 0 rulings (language keyword, loading without ASR), Task 2 `transcript` on samples.
- Produces:
  - `MODELS["omnivoice"]`: title "OmniVoice", summary "600+ languages · cloning · sound tags", url "https://huggingface.co/k2-fsa/OmniVoice", license "CC-BY-NC (non-commercial)", `disk_gb` placeholder 9.0 (replaced by the user's measurement in Task 7), `supports_convert: False`, `supports_tags: True`, `needs_transcript: True`, languages = Chatterbox's list, settings `speed` ("Speed", 0.5–2.0, step 0.05, default 1.0, help "Above 1 is faster.") and `num_step` ("Quality", 16–64, step 16, default 32, help "Higher sounds better but takes longer; 16 is quick."), pip steps: PyTorch with CUDA (`TORCH_CUDA`), "Other libraries" (`-r workers/omnivoice/requirements.txt`), "OmniVoice" (`omnivoice==0.2.1`).
  - `MODELS["chatterbox"]` gains `supports_tags: False`, `needs_transcript: False`.
  - `models.generate(name, text, ref, out, seed, settings, language, ref_text=None) -> float`; the request carries `"ref_text"`.
  - Worker: `OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16, <no-ASR option from Task 0>)`; `generate(text=..., ref_audio=ref, ref_text=ref_text, <language kw>, num_step=int(...), speed=...)`; seed via `torch.manual_seed`; writes `audio[0]` at 24000 Hz as PCM_16; CUDA errors exit with `restart` like Chatterbox. `--download` loads OmniVoice on CPU only.
  - `_line_context` also returns the sample dict; `_generate_line` refuses a `needs_transcript` model when `ref` exists and the sample has no transcript, with the spec's message prefixed by the model title, and keeps generating the other models.
  - Studio "default voice" labels for a character without samples gain " (random for OmniVoice unless a seed is set)" in the line-details sample select tooltip only *(proposal: the short labels stay short)*.
- [ ] **Step 1: Write the failing tests.** `tests/test_worker_omnivoice.py` (stub `omnivoice` writes its kwargs to the out file): `test_ref_text_and_settings_are_passed` (`ref_text=Merhaba`, `num_step=16`, `speed=1.2` in the file), `test_seed_is_applied`, `test_download_does_not_load_asr`. `tests/test_server.py`: `test_old_sample_without_transcript_fails_for_omnivoice_only` (fake `models.generate`; Chatterbox take added, error names OmniVoice and the spec's message).
- [ ] **Step 2: Run** `python3 -m pytest tests -q`. Expected: new tests FAIL.
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** `python3 -m pytest tests -q`. Expected: all pass.
- [ ] **Step 5: Commit** "feat: OmniVoice model".

### Task 6: Sound tags

**Files:**
- Modify: `app/models.py` (`TAGS`, `text_for`), `app/server.py` (`_generate_line`, `_model_view` adds `tags`), `app/ui/script.js` (`insertTag`), `app/ui/studio.js` (Add sound menu), `app/ui/styles.css`
- Test: `tests/test_tags.py`, `app/ui/tests/script.test.mjs`, `tests/test_server.py`

**Interfaces:**
- Produces:
  - `models.TAGS = ["laughter", "sigh", "confirmation-en", "question-en", "question-ah", "question-oh", "question-ei", "question-yi", "surprise-ah", "surprise-oh", "surprise-wa", "surprise-yo", "dissatisfaction-hnn"]` (written in text as `[tag]`).
  - `models.text_for(name, text) -> str` — unchanged for `supports_tags` models; otherwise removes every `[known-tag]`, collapses runs of spaces, strips.
  - `_model_view(name)["tags"]` = `TAGS` for tag models, `[]` otherwise.
  - `script.js`: `export function insertTag(value, start, end, tag) -> { value, caret }` — inserts `[tag]` at the selection, adding a space before/after when the neighbour is not whitespace.
  - Friendly menu labels *(proposal)*: Laughter, Sigh, "Yes" (confirmation), Question (en), Question "ah?", "oh?", "ei?", "yi?", Surprise "ah!", "oh!", "wa!", "yo!", Dissatisfied "hnn".
- [ ] **Step 1: Write the failing tests.**
  - `tests/test_tags.py`: `test_tags_are_removed_for_models_without_tags` (`"Hi [laughter] there [sigh]"` → `"Hi there"` for chatterbox; unchanged for omnivoice), `test_unknown_brackets_are_kept` (`"[note] hi"` unchanged).
  - `tests/test_server.py`: `test_line_of_only_tags_is_skipped_for_chatterbox` (text `"[laughter]"`, models chatterbox + omnivoice with fake generate: OmniVoice take added, error mentions "is empty" for Chatterbox, fake never called with an empty text).
  - `app/ui/tests/script.test.mjs`: `insertTag("Hello world", 5, 5, "laughter")` → `{ value: "Hello [laughter] world", caret: 16 }`; at the start of an empty string → `"[laughter] "`.
- [ ] **Step 2: Run** both suites. Expected: new tests FAIL.
- [ ] **Step 3: Implement.** `_generate_line` sends `models.text_for(name, line["text"])`; when it is empty, that model gets the empty-line error and the others continue; takes keep `line["text"]`. Line details: "Add sound" button (ghost, small) in the row under the textarea next to the character counter, shown when an installed model has tags; opens a `popover` menu; choosing inserts with `insertTag`, refocuses the textarea, and saves through the existing `saveText`; tooltip from Global Constraints.
- [ ] **Step 4: Run** both suites and verify the menu in the browser harness. Expected: pass; the tag appears at the cursor and persists after closing and reopening the line.
- [ ] **Step 5: Commit** "feat: sound tags; models without tags skip them".

### Task 7: Documentation and Windows check

**Files:**
- Modify: `README.md`, `SPEC.md`, `app/models.py` (`disk_gb` of OmniVoice and Whisper), `docs/superpowers/specs/2026-11-17-omnivoice-design.md` (status "implemented")
- Delete: `scripts/spike_2026_11_17.py`

- [ ] **Step 1: Update docs.** README: Whisper row (optional, recommended, CPU, MIT), OmniVoice row with "weights for non-commercial use (CC-BY-NC)", one sentence on shared PyTorch, sizes. SPEC: §2 models now, §3 remove "emotion tags" from out of scope, §4 table (OmniVoice column: transcript from the sample, sound tags), §6 install (shared cache, clean-up).
- [ ] **Step 2: Ask the user to check on Windows:** install Whisper, add a sample (field fills, editable), install OmniVoice (license line, Chatterbox's PyTorch not downloaded again, total size), generate the same line with both models, a line with `[laughter]`, remove OmniVoice then Chatterbox still generates, remove everything and `.local` holds only `webview`. Write the measured sizes into `disk_gb`, README and SPEC.
- [ ] **Step 3: Run** both suites and the Turkish-character grep. Expected: pass, no output.
- [ ] **Step 4: Commit** "docs: OmniVoice, Whisper and shared packages".
