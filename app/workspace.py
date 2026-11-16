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

import soundfile as sf

MIN_SAMPLE_SECONDS = 10
DEFAULT_PAUSE = 0.3

_root = Path(__file__).resolve().parent.parent / "workspace"


class WorkspaceError(Exception):
    """A problem to show to the user as is."""


def init(root: Path) -> None:
    global _root
    _root = Path(root)


def slugify(text: str) -> str:
    text = text.replace("ı", "i")  # dotless i has no ASCII decomposition
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


def create_character(name: str, session_id: str | None = None) -> str:
    parent = _characters_root(session_id)
    parent.mkdir(parents=True, exist_ok=True)
    char_id = new_id(parent)
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
