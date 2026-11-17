# VoxCPM2 model and GPU memory on the Models screen: design

Status: draft, waiting for the user's approval.

## 1. Intent

The user wants a voice model that speaks Turkish well and lets them set an emotion. Chatterbox and OmniVoice both
speak Turkish, but neither has emotion control. VoxCPM2 (OpenBMB) was chosen over these alternatives:

- Higgs TTS 3: borderline on a 12 GB card.
- Pocket TTS Turkish: emotion support exists only in a little-used package.
- Fish Audio S2: about 24 GB of GPU memory, and commercial use needs a separate license.
- Qwen3-TTS: does not speak Turkish.

VoxCPM2 has these properties:

- 30 languages, Turkish included.
- Cloning from a short sample.
- A free-form style instruction ("cheerful, slightly faster") that steers emotion and pace while keeping the
  cloned voice.
- Apache-2.0: commercial use allowed.
- About 8 GB of GPU memory.

A later step can try Trendyol-TTS, a Turkish fine-tune of VoxCPM2 that loads with the same library, through the same
worker. That step is not part of this design.

The user also asked that the Models screen show, before anything is downloaded, about how much GPU memory each
model needs. With four components and a 12 GB card, that number decides what the user installs.

## 2. Goals, non-goals, anti-goals

Goals:

- VoxCPM2 as a fourth component:
  - It is installed, removed, loaded, unloaded and memory-managed exactly like Chatterbox and OmniVoice.
  - It shares PyTorch files with them.
  - Its network access is blocked while it generates.
- A per-model **Style** setting for VoxCPM2:
  - It is free text, with clickable suggestions under the box that fill it in. This is option C, the user's
    choice.
  - It works at session level and per line, like the other settings.
- The Models screen shows each component's approximate GPU memory:
  - on the row before install;
  - in the install confirmation.
  - Whisper says it runs on the processor and uses no GPU memory.
- Export joins lines made by models with different sample rates. VoxCPM2 makes 48 kHz audio; the other models make
  24 kHz.

Non-goals:

- VoxCPM2's voice design mode: a voice from a description alone, no sample. Characters always have samples.
- VoxCPM2's continuation ("ultimate") cloning with a transcript: it does not take a style instruction (see §3).
- Sound tags for VoxCPM2: it has none, so `[laughter]` and the like are left out of its text.
- Trendyol-TTS: a later, separate step.
- Changing the emotion in the middle of a line. The user accepted one style per line.
- A warning when a model needs more GPU memory than the card has. Showing the number is what was asked.

Anti-goals:

- **Anything that sends a voice or text off the computer.** The worker blocks the network as the others do. The
  denoiser and the text normalizer must not download anything at generation time.
- **A setting that silently does nothing.** If the spike shows that style instructions do not work on Turkish
  text, stop and come back to the user before building the Style setting.
- **Breaking existing sessions.** Settings stored as numbers keep working, and takes made before this change export
  as before.

## 3. Facts this design relies on

From the model card and README (openbmb/VoxCPM2). The spike (§5.1) re-checks every one of these on the user's
Windows PC.

- Install with `pip install voxcpm`. Requires Python ≥ 3.10, PyTorch ≥ 2.5 and CUDA ≥ 12.0. Vokalit's
  `TORCH_CUDA` is torch 2.8.0 / cu128.
- Load: `VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)`.
- Generate: `model.generate(text=..., reference_wav_path=..., cfg_value=2.0, inference_timesteps=10, ...)`.
  - The output rate is `model.tts_model.sample_rate`, which is 48 kHz.
- Style control in cloning mode: the instruction goes in parentheses at the start of the text, for example
  `"(slightly faster, cheerful tone)This is a cloned voice with style control."`.
- Continuation cloning uses `prompt_wav_path` + `prompt_text` and continues from the sample. The README shows style
  control only with `reference_wav_path`.
- About 8 GB of GPU memory in bf16.
- A Turkish user's project reports that generations above about 30 s become unstable. Vokalit's script paste already
  splits long lines into chunks of about 250 characters (roughly 15–20 s of Turkish), so no extra splitting is
  planned. The spike measures a 250-character line.
- `generate` has `normalize` (an external text-normalization tool) and `denoise` options. Whether `normalize` works
  for Turkish, and whether it needs a download, is unknown. The spike decides.

## 4. Approaches considered

For the model:

- VoxCPM2 (chosen), against the alternatives in §1.

For the Style control (the user picked C):

- A) A list of preset emotions: easy to find, but limited.
- B) A free text box: anything can be written, but users may not know what to write.
- **C) A text box with suggestion buttons under it that fill it in (chosen):** easy to discover and still free.
  This needs a new "text" kind of setting.

For mixed sample rates at export:

- Make every VoxCPM2 take 24 kHz in the worker. Simplest, but throws away VoxCPM2's 48 kHz.
- **Convert every line to the session's highest rate at export (chosen, my call):** keeps VoxCPM2's quality, and
  upsampling a 24 kHz take loses nothing.
- Store a rate per session and convert at generation time: more moving parts for no gain.

## 5. Design

### 5.1 Spike (Task 0, run by the user on Windows)

A throwaway script under `scripts/` (removed after use, like the OmniVoice spike). It:

1. Installs `voxcpm` into a temporary venv with Vokalit's `TORCH_CUDA` and records:
   - the resolved `voxcpm` version and its dependencies;
   - whether it accepts torch 2.8.0 or forces another torch, in which case we install it `--no-deps` as with
     Chatterbox.
2. Downloads the model. It then blocks the network the way the workers do (`HF_HUB_OFFLINE=1`, socket block) and
   loads the model again, to prove generation needs nothing from the network.
3. Clones the user's Turkish sample (a path given on the command line) for one Turkish sentence with numbers in it,
   in these variants:
   - no style;
   - each draft preset (§5.4) written in English;
   - each draft preset written in Turkish;
   - `normalize` on and off;
   - one continuation-cloning run with the sample's transcript, for comparison.
4. Generates one 250-character and one 500-character Turkish line, to check stability. Lines the user types are
   never split, and splitting at paste is optional, so VoxCPM2 can receive long lines.
5. Generates a line that starts with a parenthesis, e.g. "(Ahmet) Geldim.", with and without a style, to see
   whether the model takes the text's own parenthesis as an instruction.
6. Writes a JSON report with:
   - the versions;
   - peak `torch.cuda.max_memory_reserved()`;
   - load and generation seconds;
   - the output sample rate;
   - the file list;
   - any exception.

   The user listens to the files and reports back.

What the spike decides:

- the pinned `voxcpm` version and whether it is installed with `--no-deps`;
- `vram_gb` and `disk_gb`;
- whether preset instructions are written in English or Turkish;
- `normalize` on or off;
- the default and range of the two sliders (§5.3).

If style does nothing on Turkish text, the VoxCPM2 work stops and comes back to the user (anti-goal).

Order of work *(my call)*: the GPU-memory display (§5.2), text settings (§5.4) and mixed-rate export (§5.5) do not
depend on the spike, so they are built while the user runs it. Text settings stay useful, because their first user
is VoxCPM2 and they are tested against a stub model. Only the VoxCPM2 model and worker (§5.3) wait for the spike's
report.

Two outcomes are decided now *(my calls)*:

- **Long lines unstable** (the 500-character line drifts or speeds up, the 250-character one does not): the worker
  generates sentence by sentence and joins the parts with a short pause. This is what the Turkish project in §3
  does, and it stays inside the worker. If both lines are fine, nothing extra is built.
- **A leading parenthesis in the text is read as an instruction**: the text sent to VoxCPM2 has its parentheses
  replaced by commas, so "(Ahmet) Geldim." is spoken as "Ahmet, Geldim." instead of silently becoming a style.
  If it is not read as an instruction, the text is sent unchanged.

### 5.2 Models screen: GPU memory

- Every voice model's spec has `vram_gb`. VoxCPM2 starts at the estimate 8.0 and is replaced by the spike's
  measured value. The server sends `vram_gb` with each component. Tools have none.
- Row text before install: `Not installed · ~12.3 GB disk · ~4.1 GB GPU memory`. For Whisper:
  `Not installed · ~1.7 GB disk · runs on the processor`.
- Install confirmation, a new list item after "Disk space":
  `GPU memory: about 4.1 GB while it is loaded. Vokalit unloads it after 5 minutes unused, and unloads other models
  when it needs room.`
  - Whisper's existing disk line already says it runs on the processor, so it gets no extra item.
- The installed row's runtime line is unchanged.

### 5.3 VoxCPM2 model

`MODELS["voxcpm"]`:

- `title`: "VoxCPM2".
- `summary`: "30 languages · cloning · style and emotion".
- `url`: https://huggingface.co/openbmb/VoxCPM2.
- `license`: "Apache-2.0".
- `supports_convert`: False.
- `needs_transcript`: False. Cloning uses `reference_wav_path` only, which is what style control works with.
- No `sounds`, so tags are stripped by `text_for`.
- `vram_gb` and `disk_gb`: from the spike.
- `languages`: the 30 codes on the card: ar, da, de, el, en, es, fi, fr, he, hi, id, it, ja, km, ko, lo, ms, my, nl,
  no, pl, pt, ru, sv, sw, th, tl, tr, vi, zh. All but `tl` already have a name in `LANGUAGE_NAMES`, since
  OmniVoice's list is merged in. `"tl": "Tagalog"` is added.
  - The model takes no language argument. The worker ignores the line's language; the existing language check
    still skips VoxCPM2 for other languages.
- `pip_steps`:
  - ("PyTorch with CUDA", TORCH_CUDA);
  - ("Other libraries", `-r workers/voxcpm/requirements.txt`) if the spike shows any are needed;
  - ("VoxCPM2", pinned `voxcpm`).
- `settings`:
  - `style`: the text setting (§5.4).
  - `cfg_value`: label "Style strength". Range about 1.0–3.0, step 0.1, default 2.0. Help: "Higher follows the
    style more closely; too high can sound strained." The model card warns that 2.5 can clip.
  - `inference_timesteps`: label "Quality". Whole numbers, about 4–30, default 10. Help: "Higher sounds better but
    takes longer."
  - The spike settles the exact ranges and defaults.

`workers/voxcpm/worker.py` follows `workers/omnivoice/worker.py`:

- `--download` loads the model once on the CPU so the files are cached.
- When serving, it blocks the network before importing, sends the `ready`, `vram_gb` and `oom` replies, and has the
  same OOM and CUDA-error handling.
- It seeds with `torch.manual_seed`.
- It loads with `load_denoiser=False` and generates with `denoise=False`. The denoiser is a separate model that
  could try to download.
- Text sent to the model: `f"({style}){text}"` when the style is not empty, otherwise `text`.
- `reference_wav_path` is the sample.
- `normalize` and `retry_badcase` are as the spike decides.
- It writes 16-bit PCM WAV at the model's own rate (48 kHz).

### 5.4 Text settings and the Style control

- A setting spec may have `"type": "text"`; specs without a type are sliders as today. A text spec has `key`,
  `label`, `default` (`""`), `max_length` (200), `help` and `suggestions`, a list of `{label, value}`.
- `validate_settings`:
  - A text value must be a string of at most `max_length` characters. Parentheses are removed and whitespace is
    collapsed, because the value is wrapped in parentheses.
  - Slider values must still be numbers in range. A string for a slider is a ValueError, not a crash.
- UI (`settings.js`): next to `sliders`, a text control:
  - a label;
  - a one-line input with a placeholder, e.g. "e.g. cheerful, a little faster";
  - a row of suggestion buttons. A click replaces the input's text with the suggestion's value and commits it.
    A second click on the same suggestion clears the input.
  - The note under it reads "Same as session" or "Session: cheerful", like the sliders.
  - Typing commits on blur and on Enter, not on each keystroke.
  - Changed values are highlighted the same way as sliders.
- The line settings tab and the session settings both render text specs with this control. Reset per model tab,
  the take "custom settings" mark and stored take settings work unchanged, since they compare plain values.
- Draft suggestions:
  - Neutral (empty);
  - Happy ("cheerful, warm");
  - Sad ("sad, quiet");
  - Angry ("angry, tense");
  - Calm ("calm, slow");
  - Excited ("excited, energetic");
  - Whispering ("whispering");
  - Serious ("serious, firm").

  The spike decides whether the values are English or Turkish. Turkish values are written with `\u` escapes in
  code.

### 5.5 Export with mixed sample rates

`workspace.export_session`:

- Read every selected take first.
- The output rate is the highest rate among them.
- Takes at a lower rate are converted to it. Linear interpolation with NumPy is enough for upsampling, and no new
  app dependency is needed. Pauses use the output rate.
- The error "different sample rate than line 1" goes away.
- A session where all takes share one rate exports byte-for-byte as before.

### 5.6 Documentation

README and SPEC:

- the VoxCPM2 model;
- its license;
- the Style setting;
- GPU memory on the Models screen;
- export at the highest sample rate.

## 6. Constraints

- All code, UI text and repo docs are in English. Non-ASCII characters are written as escapes in code and tests.
- Tests run without a GPU and without network, using stub workers and a stub uv, like the existing
  `tests/stubs/omnivoice`.
- Real-model checks are done by the user on Windows (RTX 4070 SUPER, 12 GB).
- Work goes directly on main.

## 7. Left to the builder

- The exact wording of help texts and the placeholder.
- The CSS of the suggestion buttons, which should fit the existing chips.
- Where in `models.js` the GPU-memory text is assembled.
- How the spike script is structured.
