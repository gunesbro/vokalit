# Sound chips — Design and plan

Date: 2026-11-17 · Status: **approved** (user chose approach A, "A'ya başla")

## Intent
Sound tags (`[laughter]`, `[sigh]`, …) are written into a line's text. The user wants them shown **as chips inside
the text**, removable with ×, added from a menu, and **converted for each model**: every model that performs sounds
gets its own syntax, models that don't skip them. Today only OmniVoice performs them; others (Dia `(laughs)`,
Chatterbox Turbo `[laugh]`, CosyVoice `[laughter]`) may follow.

## Decisions
- **Storage unchanged:** line text keeps canonical tags `[name]` (today's names = OmniVoice's 13). Existing lines
  need no migration.
- **Per-model conversion (server):** `MODELS[name]["sounds"] = {canonical: model text}`. `text_for` replaces each
  known canonical tag with the model's text, or removes it when the model has no entry. A model's `tags` in the view
  are the keys of its `sounds`. OmniVoice maps every tag to itself; Chatterbox has none.
- **Editor (approach A, user's choice):** a small editor of our own: a `contenteditable` field holding plain text and
  atomic chips (`contenteditable=false` spans with the sound's name and ×). Not rich text: paste is always plain
  text, formatting commands are ignored, Enter inserts a line break.
  - Chips: × or Backspace/Delete next to a chip removes it whole; typing `[laughter]` turns into a chip; pasted text
    has its tags turned into chips; the Add sound menu inserts a chip at the caret.
  - The value is the canonical text; the character counter, autosave and Generate button use it as before.
  - Undo: the browser's own; after an automatic conversion it may skip a step (accepted risk, checked in the
    browser).
- **Collapsed rows** show the same chips, read-only (no ×).
- Approaches considered: A (chosen) · B textarea with chips drawn behind it (× not clickable) · C a rich-text library
  (first large dependency).

## Plan
1. **Server conversion.** Test first (`tests/test_tags.py`): a fake model with `sounds={"laughter": "(laughs)"}`
   gets `"Hi (laughs) there [sigh]"` → `"Hi (laughs) there"`; OmniVoice unchanged; Chatterbox strips.
   Implement `sounds` on models, `text_for`, `tags` in `_model_view` = `list(sounds)`.
2. **Pure editor helpers** in `app/ui/editor.js`, tests in `app/ui/tests/editor.test.mjs`:
   `parseText(text, known) -> parts` (`{text}` / `{tag}`), `joinParts(parts) -> text`, round-trip; unknown
   brackets stay text.
3. **`soundEditor({ value, tags, labels, onInput, ariaLabel })`** in `editor.js` → `{ element, value, focus(),
   insert(tag) }`; caret kept across re-renders by its offset in the canonical text. Replace the line-details
   textarea; Add sound uses `insert`.
4. **Read-only chips** in collapsed rows (`renderParts`); CSS for chips.
5. **Browser checks** (typing, Backspace on a chip, ×, paste with a tag, typing `[sigh]`, Ctrl+Z, multi-line) and
   SPEC/README wording.
