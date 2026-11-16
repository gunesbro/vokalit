"""User data under workspace/: characters, samples, sessions, takes, exports. No UI code.

See docs/superpowers/specs/2026-11-16-workspace-design.md, section 6.
"""
import json
import os
import re
import shutil
import time
import unicodedata
import wave
from pathlib import Path

import numpy as np
import soundfile as sf

MIN_SAMPLE_SECONDS = 10
DEFAULT_PAUSE = 0.3

_root = Path(__file__).resolve().parent.parent / "workspace"


class WorkspaceError(Exception):
    """A problem to show to the user as is."""


def init(root: Path) -> None:
    global _root
    _root = Path(root)


def workspace_root() -> Path:
    return _root


def workspace_temp_file(suffix: str) -> Path:
    """A fresh path for a short-lived file (e.g. an upload before it is converted)."""
    folder = _root / ".tmp"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{time.time_ns()}{suffix}"


def slugify(text: str) -> str:
    text = text.replace("\u0131", "i")  # dotless i has no ASCII decomposition
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def _id_key(item_id: str):
    base, _, suffix = item_id.partition("-")[2].partition("-")
    return item_id.split("-")[0], base, int(suffix or 1)


def new_id(parent: Path) -> str:
    base = time.strftime("%Y%m%d-%H%M%S")
    candidate, n = base, 1
    while (Path(parent) / candidate).exists():
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


# --- Characters ---------------------------------------------------------------------------------


def _characters_root(session_id: str | None) -> Path:
    if session_id is None:
        return _root / "characters"
    return _root / "sessions" / session_id / "characters"


def character_dir(char_id: str, session_id: str | None = None) -> Path:
    return _characters_root(session_id) / char_id


def _character_file(char_id: str, session_id: str | None) -> Path:
    return character_dir(char_id, session_id) / "character.json"


def _character_ids() -> set[str]:
    """Every character ID in the workspace: lines refer to characters by ID alone, so IDs are unique
    across the library and all sessions."""
    roots = [_characters_root(None), *_sessions_root().glob("*/characters")]
    return {p.name for root in roots if root.exists() for p in root.iterdir()}


def _new_character_id() -> str:
    taken = _character_ids()
    base = time.strftime("%Y%m%d-%H%M%S")
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def create_character(name: str, session_id: str | None = None) -> str:
    parent = _characters_root(session_id)
    parent.mkdir(parents=True, exist_ok=True)
    char_id = _new_character_id()
    (parent / char_id / "samples").mkdir(parents=True)
    data = {"name": name, "created": _now(), "default_sample": None, "samples": [], "next_sample": 1}
    _write_json(_character_file(char_id, session_id), data)
    return char_id


def load_character(char_id: str, session_id: str | None = None) -> dict | None:
    return _read_json(_character_file(char_id, session_id))


def _save_character(char_id: str, data: dict, session_id: str | None) -> None:
    _write_json(_character_file(char_id, session_id), data)


def list_characters(session_id: str | None = None) -> list[tuple[str, dict]]:
    root = _characters_root(session_id)
    if not root.exists():
        return []
    ids = [p.name for p in root.iterdir() if (p / "character.json").exists()]
    ids.sort(key=_id_key, reverse=True)
    return [(char_id, load_character(char_id, session_id)) for char_id in ids]


def rename_character(char_id: str, name: str, session_id: str | None = None) -> None:
    data = load_character(char_id, session_id)
    data["name"] = name
    _save_character(char_id, data, session_id)


def add_sample(char_id: str, source_path: str, source: str, session_id: str | None = None) -> str:
    audio, sample_rate = sf.read(source_path)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    duration = len(audio) / sample_rate
    if duration < MIN_SAMPLE_SECONDS:
        raise WorkspaceError(
            f"The sample is {duration:.1f} seconds long. It must be at least {MIN_SAMPLE_SECONDS} seconds."
        )
    data = load_character(char_id, session_id)
    number = data["next_sample"]
    sample_id = f"s{number}"
    file = f"samples/{sample_id}.wav"
    sf.write(character_dir(char_id, session_id) / file, audio, sample_rate, subtype="PCM_16")
    data["samples"].append({
        "id": sample_id, "label": f"sample {number}", "file": file,
        "duration": round(duration, 2), "source": source, "created": _now(),
    })
    data["next_sample"] = number + 1
    if data["default_sample"] is None:
        data["default_sample"] = sample_id
    _save_character(char_id, data, session_id)
    return sample_id


def _find_sample(data: dict, sample_id: str | None) -> dict | None:
    return next((s for s in data["samples"] if s["id"] == sample_id), None)


def set_sample_label(char_id: str, sample_id: str, label: str, session_id: str | None = None) -> None:
    data = load_character(char_id, session_id)
    _find_sample(data, sample_id)["label"] = label
    _save_character(char_id, data, session_id)


def set_sample_language(char_id: str, sample_id: str, language: str | None, session_id: str | None = None) -> None:
    data = load_character(char_id, session_id)
    _find_sample(data, sample_id)["language"] = language
    _save_character(char_id, data, session_id)


def set_default_sample(char_id: str, sample_id: str, session_id: str | None = None) -> None:
    data = load_character(char_id, session_id)
    data["default_sample"] = sample_id
    _save_character(char_id, data, session_id)


def delete_sample(char_id: str, sample_id: str, session_id: str | None = None) -> None:
    data = load_character(char_id, session_id)
    sample = _find_sample(data, sample_id)
    (character_dir(char_id, session_id) / sample["file"]).unlink(missing_ok=True)
    data["samples"].remove(sample)
    if data["default_sample"] == sample_id:
        data["default_sample"] = data["samples"][0]["id"] if data["samples"] else None
    _save_character(char_id, data, session_id)


def sample_path(char_id: str, sample_id: str | None, session_id: str | None = None) -> Path | None:
    """The sample's file; a missing or `None` sample falls back to the default; no samples gives None."""
    data = load_character(char_id, session_id)
    sample = _find_sample(data, sample_id) or _find_sample(data, data["default_sample"])
    if sample is None:
        return None
    return character_dir(char_id, session_id) / sample["file"]


def delete_character(char_id: str) -> None:
    shutil.rmtree(character_dir(char_id), ignore_errors=True)


# --- Sessions -----------------------------------------------------------------------------------


def _sessions_root() -> Path:
    return _root / "sessions"


def session_dir(session_id: str) -> Path:
    return _sessions_root() / session_id


def _session_file(session_id: str) -> Path:
    return session_dir(session_id) / "session.json"


def create_session(name: str | None = None) -> str:
    _sessions_root().mkdir(parents=True, exist_ok=True)
    newest = list_sessions()[:1]
    language = newest[0][1]["language"] if newest else "en"  # people usually stay in one language
    session_id = new_id(_sessions_root())
    session_dir(session_id).mkdir()
    data = {
        "id": session_id, "name": name or time.strftime("Session %Y-%m-%d %H:%M"), "created": _now(),
        "models": [], "settings": {}, "cast": [], "lines": [], "next_line": 1, "language": language,
    }
    save_session(session_id, data)
    return session_id


def load_session(session_id: str) -> dict:
    data = _read_json(_session_file(session_id))
    if data is not None:
        data.setdefault("language", "tr")  # sessions from before languages were all generated in Turkish
    return data


def save_session(session_id: str, data: dict) -> None:
    _write_json(_session_file(session_id), data)


def list_sessions() -> list[tuple[str, dict]]:
    root = _sessions_root()
    if not root.exists():
        return []
    ids = [p.name for p in root.iterdir() if (p / "session.json").exists()]
    ids.sort(key=_id_key, reverse=True)
    return [(session_id, load_session(session_id)) for session_id in ids]


def rename_session(session_id: str, name: str) -> None:
    data = load_session(session_id)
    data["name"] = name
    save_session(session_id, data)


def set_session_language(session_id: str, language: str) -> None:
    data = load_session(session_id)
    data["language"] = language
    save_session(session_id, data)


def effective_language(session: dict, line: dict) -> str:
    return line.get("language") or session["language"]


def delete_session(session_id: str) -> None:
    shutil.rmtree(session_dir(session_id), ignore_errors=True)


# --- Cast ---------------------------------------------------------------------------------------


def _cast_entry(session: dict, char_id: str) -> dict | None:
    return next((c for c in session["cast"] if c["character"] == char_id), None)


def cast_character(session: dict, char_id: str) -> dict | None:
    """The character's data from the library or the session; None if it was deleted."""
    entry = _cast_entry(session, char_id)
    if entry is None:
        return None
    return load_character(char_id, None if entry["scope"] == "library" else session["id"])


def add_to_cast(session_id: str, char_id: str, scope: str) -> None:
    data = load_session(session_id)
    if _cast_entry(data, char_id) is None:
        data["cast"].append({"character": char_id, "scope": scope})
        save_session(session_id, data)


def remove_from_cast(session_id: str, char_id: str) -> None:
    data = load_session(session_id)
    used = [str(n) for n, line in enumerate(data["lines"], 1) if line["character"] == char_id]
    if used:
        character = cast_character(data, char_id)
        name = character["name"] if character else "This character"
        raise WorkspaceError(f"{name} is used by lines {', '.join(used)}. Change those lines first.")
    data["cast"] = [c for c in data["cast"] if c["character"] != char_id]
    save_session(session_id, data)


def save_as_character(session_id: str, char_id: str) -> None:
    """Moves a session-only character to the library so other sessions can use it."""
    library = _characters_root(None)
    library.mkdir(parents=True, exist_ok=True)
    shutil.move(str(character_dir(char_id, session_id)), str(library / char_id))  # IDs are workspace-unique
    data = load_session(session_id)
    _cast_entry(data, char_id)["scope"] = "library"
    save_session(session_id, data)


def sessions_using(char_id: str) -> list[str]:
    """Names of sessions whose cast uses this library character, newest first."""
    return [
        data["name"] for _, data in list_sessions()
        if any(c["character"] == char_id and c["scope"] == "library" for c in data["cast"])
    ]


# --- Script lines -------------------------------------------------------------------------------

_LINE_FIELDS = {"character", "sample", "text", "pause_after", "language"}


def _line_index(data: dict, line_id: str) -> int:
    return next(i for i, line in enumerate(data["lines"]) if line["id"] == line_id)


def add_line(session_id: str, char_id: str, text: str = "", pause_after: float = DEFAULT_PAUSE,
             after: str | None = None) -> str:
    data = load_session(session_id)
    line_id = f"l{data['next_line']}"
    data["next_line"] += 1
    line = {"id": line_id, "character": char_id, "sample": None, "text": text, "pause_after": pause_after,
            "settings": {}, "selected": None, "takes": [], "language": None}
    position = len(data["lines"]) if after is None else _line_index(data, after) + 1
    data["lines"].insert(position, line)
    save_session(session_id, data)
    return line_id


def update_line(session_id: str, line_id: str, **fields) -> None:
    unknown = set(fields) - _LINE_FIELDS
    if unknown:
        raise ValueError(f"Unknown line fields: {sorted(unknown)}")
    data = load_session(session_id)
    data["lines"][_line_index(data, line_id)].update(fields)
    save_session(session_id, data)


def move_line(session_id: str, line_id: str, delta: int) -> None:
    data = load_session(session_id)
    index = _line_index(data, line_id)
    line = data["lines"].pop(index)
    data["lines"].insert(max(0, min(len(data["lines"]), index + delta)), line)
    save_session(session_id, data)


def reorder_lines(session_id: str, line_ids: list[str]) -> None:
    data = load_session(session_id)
    by_id = {line["id"]: line for line in data["lines"]}
    if sorted(line_ids) != sorted(by_id):
        raise WorkspaceError("The script changed while reordering. Try again.")
    data["lines"] = [by_id[line_id] for line_id in line_ids]
    save_session(session_id, data)


def delete_line(session_id: str, line_id: str) -> None:
    data = load_session(session_id)
    line = data["lines"].pop(_line_index(data, line_id))
    for take in line["takes"]:
        for key in ("file", "source_recording"):
            if take.get(key):
                (session_dir(session_id) / take[key]).unlink(missing_ok=True)
    save_session(session_id, data)


_SPEAKER = re.compile(r"^\s*([^:]{1,40}?)\s*:\s*(.*)$")


def paste_script(session_id: str, text: str) -> int:
    """Adds `Character: text` lines. A line without a speaker continues the previous line.
    Unknown characters become session-only characters without samples."""
    parsed = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        match = _SPEAKER.match(raw)
        if match and len(match.group(1).split()) <= 3:
            parsed.append([match.group(1), match.group(2).strip()])
        elif parsed:
            parsed[-1][1] = f"{parsed[-1][1]} {raw.strip()}".strip()
        else:
            raise WorkspaceError(f'The first line has no speaker. Start lines with "Name: text".')
    data = load_session(session_id)
    by_name = {}
    for entry in data["cast"]:
        character = cast_character(data, entry["character"])
        if character:
            by_name.setdefault(character["name"].casefold(), entry["character"])
    for name, _ in parsed:
        if name.casefold() not in by_name:
            char_id = create_character(name, session_id=session_id)
            add_to_cast(session_id, char_id, "session")
            by_name[name.casefold()] = char_id
    for name, line_text in parsed:
        add_line(session_id, by_name[name.casefold()], line_text)
    return len(parsed)


# --- Takes and recordings -----------------------------------------------------------------------


def _line(data: dict, line_id: str) -> dict:
    return data["lines"][_line_index(data, line_id)]


def _take_number(line: dict) -> int:
    return line.get("next_take", 1)  # never reused, so a deleted take's file name is never taken again


def new_take_path(session_id: str, line_id: str, model: str) -> Path:
    data = load_session(session_id)
    line = _line(data, line_id)
    character = cast_character(data, line["character"])
    slug = slugify(character["name"]) if character else "deleted"
    number = _line_index(data, line_id) + 1
    folder = session_dir(session_id) / "takes"
    folder.mkdir(exist_ok=True)
    return folder / f"{number:02d}-{slug}-{slugify(model)}-take{_take_number(line)}.wav"


def new_recording_path(session_id: str, line_id: str) -> Path:
    data = load_session(session_id)
    folder = session_dir(session_id) / "recordings"
    folder.mkdir(exist_ok=True)
    number = _line_index(data, line_id) + 1
    return folder / f"{number:02d}-take{_take_number(_line(data, line_id))}.wav"


def _relative(session_id: str, path) -> str:
    path = Path(path)
    if path.is_absolute():
        path = path.relative_to(session_dir(session_id))
    return path.as_posix()


def add_take(session_id: str, line_id: str, take: dict) -> None:
    data = load_session(session_id)
    line = _line(data, line_id)
    take = dict(take, file=_relative(session_id, take["file"]))
    if take.get("source_recording"):
        take["source_recording"] = _relative(session_id, take["source_recording"])
    line["takes"].append(take)
    line["next_take"] = _take_number(line) + 1
    if line["selected"] is None:
        line["selected"] = take["file"]
    save_session(session_id, data)


def select_take(session_id: str, line_id: str, file: str) -> None:
    data = load_session(session_id)
    _line(data, line_id)["selected"] = file
    save_session(session_id, data)


def delete_take(session_id: str, line_id: str, file: str) -> None:
    data = load_session(session_id)
    line = _line(data, line_id)
    take = next(t for t in line["takes"] if t["file"] == file)
    line["takes"].remove(take)
    for key in ("file", "source_recording"):
        if take.get(key):
            (session_dir(session_id) / take[key]).unlink(missing_ok=True)
    if line["selected"] == file:
        line["selected"] = line["takes"][-1]["file"] if line["takes"] else None
    save_session(session_id, data)


def take_text_changed(line: dict, take: dict) -> bool:
    return take.get("kind") == "tts" and take.get("text") != line["text"]


# --- Models and generation settings (spec 6: model defaults <- session <- line) -----------------


def set_session_models(session_id: str, models: list[str]) -> None:
    data = load_session(session_id)
    data["models"] = list(models)
    save_session(session_id, data)


def set_session_settings(session_id: str, model: str, settings: dict) -> None:
    data = load_session(session_id)
    data["settings"][model] = dict(settings)
    save_session(session_id, data)


def reset_session_settings(session_id: str, model: str) -> None:
    data = load_session(session_id)
    data["settings"].pop(model, None)
    save_session(session_id, data)


def set_line_settings(session_id: str, line_id: str, model: str, overrides: dict) -> None:
    data = load_session(session_id)
    _line(data, line_id)["settings"][model] = dict(overrides)
    save_session(session_id, data)


def reset_line_settings(session_id: str, line_id: str) -> None:
    data = load_session(session_id)
    _line(data, line_id)["settings"] = {}
    save_session(session_id, data)


def _session_level(session: dict, model: str, defaults: dict) -> dict:
    return {**defaults, **session["settings"].get(model, {})}


def effective_settings(session: dict, line: dict, model: str, defaults: dict) -> dict:
    return {**_session_level(session, model, defaults), **line["settings"].get(model, {})}


def take_has_custom_settings(session: dict, take: dict, defaults: dict) -> bool:
    """True when a take was generated with settings that differ from the session's current ones."""
    if "settings" not in take:
        return False
    session_level = _session_level(session, take["model"], defaults)
    return any(session_level.get(key) != value for key, value in take["settings"].items())


# --- Export -------------------------------------------------------------------------------------


def export_session(session_id: str) -> Path:
    """Joins each line's selected take and its pause into exports/<session>-<time>.wav."""
    data = load_session(session_id)
    missing = [str(n) for n, line in enumerate(data["lines"], 1) if not line["selected"]]
    if missing:
        if len(missing) == 1:
            raise WorkspaceError(f"Line {missing[0]} has no takes yet.")
        raise WorkspaceError(f"Lines {', '.join(missing)} have no takes yet.")
    if not data["lines"]:
        raise WorkspaceError("The script is empty.")
    chunks, rate = [], None
    for n, line in enumerate(data["lines"], 1):
        path = session_dir(session_id) / line["selected"]
        if not path.exists():
            raise WorkspaceError(f"Line {n}: the selected take file is missing ({line['selected']}). "
                                 "Generate it again or choose another take.")
        with wave.open(str(path), "rb") as w:
            if rate is None:
                rate = w.getframerate()
            elif w.getframerate() != rate:
                raise WorkspaceError(f"Line {n} has a different sample rate than line 1 "
                                     f"({rate} Hz and {w.getframerate()} Hz), so they cannot be joined.")
            chunks.append(np.frombuffer(w.readframes(w.getnframes()), dtype="<i2"))
        chunks.append(np.zeros(round(line["pause_after"] * rate), dtype="<i2"))
    folder = session_dir(session_id) / "exports"
    folder.mkdir(exist_ok=True)
    out = folder / f"{slugify(data['name'])}-{time.strftime('%Y%m%d-%H%M%S')}.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.concatenate(chunks).tobytes())
    return out
