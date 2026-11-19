"""Dubs under workspace/dubs/<id>/: an audio or video file whose sentences are spoken again in another language, in
their own voices. Stored as tracks of clips (seconds, never pixels), so the timeline can grow into an editor.

dub.json, source.<ext> (the imported file), audio.wav (its sound, decoded by the window), refs/, takes/, exports/.
"""
import shutil
import time
import wave
from pathlib import Path

import numpy as np
import soundfile as sf

import workspace as ws

SOURCE_TYPES = {"wav", "mp3", "m4a", "ogg", "flac"}
VIDEO_TYPES = {"mp4", "webm"}
DEFAULT_ORIGINAL_VOLUME = 0.15
REFERENCE_PADDING = 0.15  # seconds kept around a sentence cut out as a voice reference


def _root() -> Path:
    return ws.workspace_root() / "dubs"


def dub_dir(dub_id: str) -> Path:
    return _root() / dub_id


def _file(dub_id: str) -> Path:
    return dub_dir(dub_id) / "dub.json"


def audio_path(dub_id: str) -> Path:
    """The source's sound as WAV (written by set_source_audio)."""
    return dub_dir(dub_id) / "audio.wav"


def create_dub(name: str, source_bytes: bytes, ext: str) -> str:
    ext = (ext or "").lower()
    if ext not in SOURCE_TYPES | VIDEO_TYPES:
        raise ws.WorkspaceError(f"Vokalit cannot open .{ext} files. Use a video (MP4, WebM) or an audio file.")
    _root().mkdir(parents=True, exist_ok=True)
    dub_id = ws.new_id(_root())
    dub_dir(dub_id).mkdir()
    (dub_dir(dub_id) / f"source.{ext}").write_bytes(source_bytes)
    save_dub(dub_id, {
        "id": dub_id, "name": name.strip() or time.strftime("Dub %Y-%m-%d %H:%M"), "created": ws._now(),
        "source": {"file": f"source.{ext}", "kind": "video" if ext in VIDEO_TYPES else "audio", "duration": None,
                   "language": None},
        "target_language": "en", "model": None, "settings": {}, "original_volume": DEFAULT_ORIGINAL_VOLUME,
        "tracks": _empty_tracks(),
    })
    return dub_id


def _empty_tracks() -> list[dict]:
    return [{"id": "original", "kind": "source", "clips": []},
            {"id": "dub", "kind": "speech", "voice": {"mode": "original"}, "clips": []}]


def set_source_audio(dub_id: str, wav_bytes: bytes) -> None:
    audio_path(dub_id).write_bytes(wav_bytes)
    data = load_dub(dub_id)
    data["source"]["duration"] = round(ws.wav_duration(audio_path(dub_id)), 3)
    save_dub(dub_id, data)


def load_dub(dub_id: str) -> dict | None:
    return ws._read_json(_file(dub_id))


def save_dub(dub_id: str, data: dict) -> None:
    ws._write_json(_file(dub_id), data)


def list_dubs() -> list[tuple[str, dict]]:
    """Newest first."""
    if not _root().exists():
        return []
    ids = sorted((p.name for p in _root().iterdir() if (p / "dub.json").exists()), key=ws._id_key, reverse=True)
    return [(dub_id, load_dub(dub_id)) for dub_id in ids]


def rename_dub(dub_id: str, name: str) -> None:
    if not name.strip():
        raise ws.WorkspaceError("Give the dub a name.")
    data = load_dub(dub_id)
    data["name"] = name.strip()
    save_dub(dub_id, data)


def delete_dub(dub_id: str) -> None:
    shutil.rmtree(dub_dir(dub_id), ignore_errors=True)


# --- Sentences ----------------------------------------------------------------------------------


def _source_clips(data: dict) -> list[dict]:
    return data["tracks"][0]["clips"]


def _dub_clips(data: dict) -> list[dict]:
    return data["tracks"][1]["clips"]


def _find(clips: list[dict], clip_id: str) -> dict:
    clip = next((c for c in clips if c["id"] == clip_id), None)
    if clip is None:
        raise ws.WorkspaceError("This sentence no longer exists. Reload the dub.")
    return clip


def set_transcript(dub_id: str, language: str, segments: list[dict]) -> None:
    """Replaces every sentence, translation and take with Whisper's sentences."""
    data = load_dub(dub_id)
    shutil.rmtree(dub_dir(dub_id) / "takes", ignore_errors=True)
    data["source"]["language"] = language
    data["tracks"] = _empty_tracks()
    for n, segment in enumerate(segments, 1):
        _source_clips(data).append({"id": f"o{n}", "start": segment["start"], "end": segment["end"],
                                    "text": segment["text"].strip()})
        _dub_clips(data).append({"id": f"d{n}", "source_clip": f"o{n}", "voice_from": f"o{n}",
                                 "start": segment["start"], "translation": "", "takes": [], "selected": None})
    save_dub(dub_id, data)


def update_source_clip(dub_id: str, clip_id: str, text: str) -> None:
    data = load_dub(dub_id)
    _find(_source_clips(data), clip_id)["text"] = text.strip()
    save_dub(dub_id, data)


def delete_source_clip(dub_id: str, clip_id: str) -> None:
    """Deletes a sentence with its translation and takes; clips that took their voice from it use their own."""
    data = load_dub(dub_id)
    _find(_source_clips(data), clip_id)
    data["tracks"][0]["clips"] = [c for c in _source_clips(data) if c["id"] != clip_id]
    for clip in _dub_clips(data):
        if clip["source_clip"] == clip_id:
            for take in clip["takes"]:
                (dub_dir(dub_id) / take["file"]).unlink(missing_ok=True)
    data["tracks"][1]["clips"] = [c for c in _dub_clips(data) if c["source_clip"] != clip_id]
    for clip in _dub_clips(data):
        if clip["voice_from"] == clip_id:
            clip["voice_from"] = clip["source_clip"]
    save_dub(dub_id, data)


def update_dub_clip(dub_id: str, clip_id: str, *, start: float | None = None, translation: str | None = None,
                    voice_from: str | None = None) -> None:
    data = load_dub(dub_id)
    clip = _find(_dub_clips(data), clip_id)
    if start is not None:
        duration = data["source"]["duration"]
        if start < 0 or (duration is not None and start > duration):
            raise ws.WorkspaceError("A sentence must start inside the file.")
        clip["start"] = round(float(start), 3)
    if translation is not None:
        clip["translation"] = translation.strip()
    if voice_from is not None:
        _find(_source_clips(data), voice_from)
        clip["voice_from"] = voice_from
    save_dub(dub_id, data)


def set_options(dub_id: str, *, target_language: str | None = None, model: str | None = None,
                settings: dict | None = None, original_volume: float | None = None) -> None:
    """Checked values only: languages and settings are checked by the caller against the models."""
    data = load_dub(dub_id)
    if target_language is not None:
        data["target_language"] = target_language
    if model is not None:
        data["model"] = model
    if settings is not None:
        data["settings"] = settings
    if original_volume is not None:
        if not 0 <= original_volume <= 1:
            raise ws.WorkspaceError("The original's volume must be between 0 and 100 %.")
        data["original_volume"] = round(float(original_volume), 3)
    save_dub(dub_id, data)


# --- Takes --------------------------------------------------------------------------------------


def new_take_path(dub_id: str, clip_id: str) -> Path:
    folder = dub_dir(dub_id) / "takes"
    folder.mkdir(exist_ok=True)
    n = 1
    while (folder / f"{clip_id}-{n}.wav").exists():
        n += 1
    return folder / f"{clip_id}-{n}.wav"


def add_take(dub_id: str, clip_id: str, take: dict) -> None:
    """Adds a generated take (its file relative to the dub) and selects it."""
    data = load_dub(dub_id)
    clip = _find(_dub_clips(data), clip_id)
    file = Path(take["file"]).resolve().relative_to(dub_dir(dub_id).resolve()).as_posix()
    clip["takes"].append({**take, "file": file})
    clip["selected"] = file
    save_dub(dub_id, data)


def select_take(dub_id: str, clip_id: str, file: str) -> None:
    data = load_dub(dub_id)
    clip = _find(_dub_clips(data), clip_id)
    if not any(t["file"] == file for t in clip["takes"]):
        raise ws.WorkspaceError("This take no longer exists.")
    clip["selected"] = file
    save_dub(dub_id, data)


# --- References, fit, export --------------------------------------------------------------------


def _read(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path), "rb") as w:
        return w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def _write(path: Path, rate: int, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype("<i2").tobytes())


def cut_reference(dub_id: str, clip_id: str) -> tuple[Path, str]:
    """The voice reference for a dub clip: only the original audio of its "voice from" sentence (never neighbours,
    which in a dialogue are often the other speaker), with a little padding; and that sentence's text."""
    data = load_dub(dub_id)
    source = _find(_source_clips(data), _find(_dub_clips(data), clip_id)["voice_from"])
    rate, samples = _read(audio_path(dub_id))
    first = max(0, round((source["start"] - REFERENCE_PADDING) * rate))
    last = min(len(samples), round((source["end"] + REFERENCE_PADDING) * rate))
    folder = dub_dir(dub_id) / "refs"
    folder.mkdir(exist_ok=True)
    path = folder / f"{source['id']}.wav"
    _write(path, rate, samples[first:last])
    return path, source["text"]


def _selected_duration(clip: dict) -> float | None:
    take = next((t for t in clip["takes"] if t["file"] == clip["selected"]), None)
    return take["duration"] if take else None


def fit(data: dict) -> dict[str, dict]:
    """Per dub clip: "missing" (no take), "fits", or "long" with `over` = seconds it runs into the next clip (by start)
    or past the end of the file."""
    clips = sorted(_dub_clips(data), key=lambda c: c["start"])
    end_of_file = data["source"]["duration"]
    result = {}
    for i, clip in enumerate(clips):
        duration = _selected_duration(clip)
        if duration is None:
            result[clip["id"]] = {"state": "missing", "over": 0.0}
            continue
        limits = [c["start"] for c in clips[i + 1:i + 2]] + ([end_of_file] if end_of_file is not None else [])
        over = round(clip["start"] + duration - min(limits), 1) if limits else 0.0
        result[clip["id"]] = {"state": "long", "over": over} if over > 0 else {"state": "fits", "over": 0.0}
    return result


def export_dub(dub_id: str, fmt: str = "wav") -> Path:
    """Mixes every selected take at its start over the original (at original_volume) into exports/<name>-<time>.<fmt>.
    Sentences without a take are silent; the original still plays under them."""
    if fmt not in ws.export_formats():
        raise ws.WorkspaceError(f"This computer cannot export {fmt.upper()} files.")
    data = load_dub(dub_id)
    if not audio_path(dub_id).exists():
        raise ws.WorkspaceError("The dub has no sound yet. Import the file again.")
    source_rate, source = _read(audio_path(dub_id))
    takes = []
    for n, clip in enumerate(_dub_clips(data), 1):
        if not clip["selected"]:
            continue
        path = dub_dir(dub_id) / clip["selected"]
        if not path.exists():
            raise ws.WorkspaceError(f"Sentence {n}: the selected take file is missing ({clip['selected']}). "
                                    "Generate it again or choose another take.")
        takes.append((clip["start"], *_read(path)))
    # Models write different sample rates (VoxCPM2 48 kHz, others 24 kHz): mix at the highest, so nothing is lost.
    rate = max([source_rate] + [take_rate for _, take_rate, _ in takes])
    original = source if source_rate == rate else ws._resample(source, source_rate, rate)
    mix = original.astype(np.float64) * data["original_volume"]
    for start, take_rate, samples in takes:
        samples = samples if take_rate == rate else ws._resample(samples, take_rate, rate)
        first = round(start * rate)
        if first + len(samples) > len(mix):
            mix = np.concatenate([mix, np.zeros(first + len(samples) - len(mix))])
        mix[first:first + len(samples)] += samples
    mix = np.clip(np.round(mix), -32768, 32767).astype("<i2")
    folder = dub_dir(dub_id) / "exports"
    folder.mkdir(exist_ok=True)
    out = folder / f"{ws.slugify(data['name'])}-{time.strftime('%Y%m%d-%H%M%S')}.{fmt}"
    if fmt == "wav":
        _write(out, rate, mix)
    else:
        major, subtype = ws.EXPORT_ENCODINGS[fmt]
        sf.write(str(out), mix.astype(np.float32) / 32768, rate, format=major, subtype=subtype)
    return out
