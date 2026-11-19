"""Dubs under workspace/dubs/<id>/: an audio or video file whose sentences are spoken again in another language, in
their own voices. Stored as tracks of clips (seconds, never pixels), so the timeline can grow into an editor.

dub.json, source.<ext> (the imported file), audio.wav (its sound, decoded by the window), refs/, takes/, exports/.
"""
import shutil
import threading
import time
import wave
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import soundfile as sf

import workspace as ws
from stretch import stretch

SOURCE_TYPES = {"wav", "mp3", "m4a", "ogg", "flac"}
VIDEO_TYPES = {"mp4", "webm"}
DEFAULT_ORIGINAL_VOLUME = 0.15
REFERENCE_PADDING = 0.15  # seconds kept around a sentence cut out as a voice reference
KEPT_FADE = 0.05  # seconds to fade the original up and down around a sentence that keeps it
MAX_SPEEDUP = 1.25  # a take is sped up at most this much to fit; beyond it speech stops sounding natural
FIT_GAP = 0.05  # seconds left free before the next sentence when a take is fitted
MIN_SPEED = 0.85  # a take that ends early is slowed down at most this much; slower drags
SHORT_GAP = 0.4  # seconds a take may end before its speaker does without counting as too short


class NeedsShorter(ws.WorkspaceError):
    """A take cannot be fitted by speeding it up: its translation has to be shorter."""


class NeedsLonger(ws.WorkspaceError):
    """A take ends too early even slowed down: its translation has to be longer."""


def _target(clip: dict, source: dict | None, room: float) -> float:
    """Where a dub clip's take should end, in seconds from its start: when its speaker stops, but never past the room
    before the next sentence. Without a source sentence there is no speaker to match: 0, never too short."""
    return min(room, source["end"] - clip["start"]) if source else 0.0


def _can_lengthen(duration: float, target: float) -> bool:
    """Slowed down to MIN_SPEED at most, the take ends within SHORT_GAP of the target."""
    return duration / MIN_SPEED >= target - SHORT_GAP


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
        "original_volume": DEFAULT_ORIGINAL_VOLUME,
        "tracks": [{"id": "original", "kind": "source", "clips": []}, _language_track("en")],
    })
    return dub_id


def _language_track(language: str, model: str | None = None, settings: dict | None = None,
                    sources: list[dict] = ()) -> dict:
    """A target language: its translations, takes and timing, model and settings, one clip per source sentence."""
    return {"id": f"dub-{language}", "kind": "speech", "language": language, "model": model, "settings": settings or {},
            "voice": {"mode": "original"}, "clips": [_new_clip(n, source) for n, source in enumerate(sources, 1)]}


def _new_clip(n: int, source: dict) -> dict:
    return {"id": f"d{n}", "source_clip": source["id"], "voice_from": source["id"], "start": source["start"],
            "translation": "", "takes": [], "selected": None}


def _migrate(data: dict) -> dict:
    """Dubs from before several languages: the single dub track takes the dub's target language, model and settings."""
    for track in data["tracks"][1:]:
        if "language" not in track:
            language = data.pop("target_language", "en")
            track.update({"id": f"dub-{language}", "language": language, "model": data.pop("model", None),
                          "settings": data.pop("settings", {})})
    return data


def set_source_audio(dub_id: str, wav_bytes: bytes) -> None:
    audio_path(dub_id).write_bytes(wav_bytes)
    with _editing(dub_id) as data:
        data["source"]["duration"] = round(ws.wav_duration(audio_path(dub_id)), 3)


def load_dub(dub_id: str) -> dict | None:
    data = ws._read_json(_file(dub_id))
    return None if data is None else _migrate(data)


def languages(data: dict) -> list[str]:
    return [track["language"] for track in data["tracks"][1:]]


def _track(data: dict, language: str | None) -> dict:
    """The dub track of `language` (None: the first language)."""
    tracks = data["tracks"][1:]
    track = tracks[0] if language is None else next((t for t in tracks if t["language"] == language), None)
    if track is None:
        raise ws.WorkspaceError("This dub has no such language.")
    return track


_locks = {}
_locks_guard = threading.Lock()


@contextmanager
def _editing(dub_id: str):
    """Load, change and save one dub under its lock, so a take added by a job while the user saves a translation does
    not overwrite either change."""
    with _locks_guard:
        lock = _locks.setdefault(dub_id, threading.RLock())
    with lock:
        data = load_dub(dub_id)
        if data is None:
            raise ws.WorkspaceError("This dub no longer exists.")
        yield data
        save_dub(dub_id, data)


def save_dub(dub_id: str, data: dict) -> None:
    ws._write_json(_file(dub_id), data, compact=True)


def list_dubs() -> list[tuple[str, dict]]:
    """Newest first."""
    if not _root().exists():
        return []
    ids = sorted((p.name for p in _root().iterdir() if (p / "dub.json").exists()), key=ws._id_key, reverse=True)
    return [(dub_id, load_dub(dub_id)) for dub_id in ids]


def rename_dub(dub_id: str, name: str) -> None:
    if not name.strip():
        raise ws.WorkspaceError("Give the dub a name.")
    with _editing(dub_id) as data:
        data["name"] = name.strip()


def delete_dub(dub_id: str) -> None:
    shutil.rmtree(dub_dir(dub_id), ignore_errors=True)


# --- Sentences ----------------------------------------------------------------------------------


def _source_clips(data: dict) -> list[dict]:
    return data["tracks"][0]["clips"]


def _dub_clips(data: dict, language: str | None = None) -> list[dict]:
    return _track(data, language)["clips"]


def _find(clips: list[dict], clip_id: str) -> dict:
    clip = next((c for c in clips if c["id"] == clip_id), None)
    if clip is None:
        raise ws.WorkspaceError("This sentence no longer exists. Reload the dub.")
    return clip


def set_transcript(dub_id: str, language: str, segments: list[dict]) -> None:
    """Replaces every sentence, and every language's translations and takes, with Whisper's sentences."""
    with _editing(dub_id) as data:
        shutil.rmtree(dub_dir(dub_id) / "takes", ignore_errors=True)
        data["source"]["language"] = language
        sources = [{"id": f"o{n}", "start": s["start"], "end": s["end"], "text": s["text"].strip()}
                   for n, s in enumerate(segments, 1)]
        data["tracks"] = [{"id": "original", "kind": "source", "clips": sources}] + [
            _language_track(t["language"], t.get("model"), t.get("settings"), sources) for t in data["tracks"][1:]]


def add_language(dub_id: str, language: str) -> None:
    with _editing(dub_id) as data:
        if language in languages(data):
            raise ws.WorkspaceError("The dub already has this language.")
        data["tracks"].append(_language_track(language, sources=_source_clips(data)))


def remove_language(dub_id: str, language: str) -> None:
    """Removes a language with its translations and takes."""
    with _editing(dub_id) as data:
        track = _track(data, language)
        if len(languages(data)) == 1:
            raise ws.WorkspaceError("A dub needs at least one language; this is the last one.")
        data["tracks"].remove(track)
        shutil.rmtree(dub_dir(dub_id) / "takes" / language, ignore_errors=True)


def set_language_options(dub_id: str, language: str | None, *, model: str | None = None,
                         settings: dict | None = None) -> None:
    with _editing(dub_id) as data:
        track = _track(data, language)
        if model is not None:
            track["model"] = model
        if settings is not None:
            track["settings"] = settings


def update_source_clip(dub_id: str, clip_id: str, text: str) -> None:
    with _editing(dub_id) as data:
        _find(_source_clips(data), clip_id)["text"] = text.strip()


def set_keep_original(dub_id: str, clip_id: str, keep: bool) -> None:
    """Marks a sentence (music, singing) to keep the original there, at full volume, in every language: it is not
    translated or generated."""
    with _editing(dub_id) as data:
        source = _find(_source_clips(data), clip_id)
        if keep:
            source["keep_original"] = True
        else:
            source.pop("keep_original", None)


def _kept(data: dict) -> list[dict]:
    return [s for s in _source_clips(data) if s.get("keep_original")]


def delete_source_clip(dub_id: str, clip_id: str) -> None:
    """Deletes a sentence with its translation and takes; clips that took their voice from it use their own. The take
    files stay (they go with the dub), so undo can bring the sentence back."""
    with _editing(dub_id) as data:
        _find(_source_clips(data), clip_id)
        data["tracks"][0]["clips"] = [c for c in _source_clips(data) if c["id"] != clip_id]
        for track in data["tracks"][1:]:
            track["clips"] = [c for c in track["clips"] if c["source_clip"] != clip_id]
            for clip in track["clips"]:
                if clip["voice_from"] == clip_id:
                    clip["voice_from"] = clip["source_clip"]


def restore_sentence(dub_id: str, source: dict, clips: dict[str, dict], index: int,
                     voices: dict[str, list[str]] | None = None) -> None:
    """Puts a deleted sentence back at `index` (or at the end): its source clip, and its clip in each language as they
    were (`clips` by language). `voices`: per language, the clips that took their voice from it, pointed back at it."""
    with _editing(dub_id) as data:
        if any(c["id"] == source["id"] for c in _source_clips(data)):
            raise ws.WorkspaceError("This sentence is already there.")
        place = max(0, min(int(index), len(_source_clips(data))))
        _source_clips(data).insert(place, source)
        known = {c["id"] for c in _source_clips(data)}
        for track in data["tracks"][1:]:
            clip = clips.get(track["language"])
            if clip is None or any(c["id"] == clip["id"] for c in track["clips"]) or clip["source_clip"] != source["id"]:
                clip = {**_new_clip(0, source), "id": _free_clip_id(track)}  # a language added after the delete
            # Takes whose files are gone (the language was removed and added again) are forgotten.
            takes = [t for t in clip["takes"] if (dub_dir(dub_id) / t["file"]).exists()]
            clip = {**clip, "takes": takes,
                    "selected": clip["selected"] if any(t["file"] == clip["selected"] for t in takes) else None}
            track["clips"].insert(place, {**clip, "voice_from": clip["voice_from"] if clip["voice_from"] in known
                                          else source["id"]})
            for other in track["clips"]:
                if other["id"] in (voices or {}).get(track["language"], []):
                    other["voice_from"] = source["id"]


def _free_clip_id(track: dict) -> str:
    taken = {c["id"] for c in track["clips"]}
    n = 1
    while f"d{n}" in taken:
        n += 1
    return f"d{n}"


def update_dub_clip(dub_id: str, clip_id: str, *, start: float | None = None, translation: str | None = None,
                    voice_from: str | None = None, language: str | None = None) -> None:
    with _editing(dub_id) as data:
        clip = _find(_dub_clips(data, language), clip_id)
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


def set_translations(dub_id: str, translations: dict[str, str], language: str | None = None) -> None:
    """Several translations at once (a whole translated transcript pasted in), by dub clip id."""
    with _editing(dub_id) as data:
        clips = [_find(_dub_clips(data, language), clip_id) for clip_id in translations]
        for clip, text in zip(clips, translations.values()):
            clip["translation"] = str(text).strip()


def set_options(dub_id: str, *, original_volume: float | None = None) -> None:
    if original_volume is not None and not 0 <= original_volume <= 1:
        raise ws.WorkspaceError("The original's volume must be between 0 and 100 %.")
    with _editing(dub_id) as data:
        if original_volume is not None:
            data["original_volume"] = round(float(original_volume), 3)


# --- Takes --------------------------------------------------------------------------------------


def new_take_path(dub_id: str, clip_id: str, language: str | None = None) -> Path:
    folder = dub_dir(dub_id) / "takes" / (language or languages(load_dub(dub_id))[0])
    folder.mkdir(parents=True, exist_ok=True)
    n = 1
    while (folder / f"{clip_id}-{n}.wav").exists():
        n += 1
    return folder / f"{clip_id}-{n}.wav"


def add_take(dub_id: str, clip_id: str, take: dict, language: str | None = None) -> None:
    """Adds a generated take (its file relative to the dub) and selects it."""
    file = Path(take["file"]).resolve().relative_to(dub_dir(dub_id).resolve()).as_posix()
    with _editing(dub_id) as data:
        clip = _find(_dub_clips(data, language), clip_id)
        clip["takes"].append({**take, "file": file})
        clip["selected"] = file


def select_take(dub_id: str, clip_id: str, file: str | None, language: str | None = None) -> None:
    """`file` None: no take selected (undo of a sentence's first generation)."""
    with _editing(dub_id) as data:
        clip = _find(_dub_clips(data, language), clip_id)
        if file is not None and not any(t["file"] == file for t in clip["takes"]):
            raise ws.WorkspaceError("This take no longer exists.")
        clip["selected"] = file


def clear_takes(dub_id: str, language: str) -> int:
    """Deletes every take of one language, files included (also those kept for undoing deleted sentences); the
    sentences and translations stay. Returns how many takes the sentences had. Not undoable."""
    with _editing(dub_id) as data:
        clips = _track(data, language)["clips"]
        removed = sum(len(c["takes"]) for c in clips)
        for clip in clips:
            clip["takes"] = []
            clip["selected"] = None
    shutil.rmtree(dub_dir(dub_id) / "takes" / language, ignore_errors=True)  # after the save: nothing points at them
    return removed


def select_takes(dub_id: str, selections: dict, language: str | None = None) -> None:
    """Several clips' takes at once ({clip id: file or None}), in one save: undoing a generation or a fit of thousands
    of sentences. All or nothing."""
    with _editing(dub_id) as data:
        clips = {c["id"]: c for c in _dub_clips(data, language)}
        for clip_id, file in selections.items():
            clip = clips.get(clip_id)
            if clip is None or (file is not None and not any(t["file"] == file for t in clip["takes"])):
                raise ws.WorkspaceError("This take no longer exists.")
        for clip_id, file in selections.items():
            clips[clip_id]["selected"] = file


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


def cut_reference(dub_id: str, clip_id: str, language: str | None = None) -> tuple[Path, str]:
    """The voice reference for a dub clip: only the original audio of its "voice from" sentence (never neighbours,
    which in a dialogue are often the other speaker), with a little padding; and that sentence's text."""
    data = load_dub(dub_id)
    source = _find(_source_clips(data), _find(_dub_clips(data, language), clip_id)["voice_from"])
    rate, samples = _read(audio_path(dub_id))
    first = max(0, round((source["start"] - REFERENCE_PADDING) * rate))
    last = min(len(samples), round((source["end"] + REFERENCE_PADDING) * rate))
    folder = dub_dir(dub_id) / "refs"
    folder.mkdir(exist_ok=True)
    path = folder / f"{source['id']}.wav"
    _write(path, rate, samples[first:last])
    return path, source["text"]


def fit_take(dub_id: str, clip_id: str, language: str | None = None) -> float:
    """Speeds a clip's selected take up (same pitch) to end FIT_GAP before the next sentence, or slows one that ends
    while its speaker still talks down to end with them, as a new selected take that remembers the take it came from;
    fitting again starts from that one, not from a stretched copy. Returns the speed. Refused when it already fits, or
    would need more than MAX_SPEEDUP (NeedsShorter) or less than MIN_SPEED (NeedsLonger)."""
    data = load_dub(dub_id)
    clips = _dub_clips(data, language)
    clip = _find(clips, clip_id)
    number = clips.index(clip) + 1
    if clip["source_clip"] in {s["id"] for s in _kept(data)}:
        raise ws.WorkspaceError(f"Sentence {number} keeps the original.")
    selected = next((t for t in clip["takes"] if t["file"] == clip["selected"]), None)
    if selected is None:
        raise ws.WorkspaceError(f"Sentence {number} has no take yet.")
    base = _original_take(clip, selected)
    path = dub_dir(dub_id) / base["file"]
    if not path.exists():
        raise ws.WorkspaceError(f"Sentence {number}: the take file is missing ({base['file']}). Generate it again.")
    order = sorted(clips, key=lambda c: c["start"])  # the next sentence as fit() sees it
    following = order[order.index(clip) + 1:order.index(clip) + 2]
    limits = [c["start"] for c in following] + ([data["source"]["duration"]] if data["source"]["duration"] else [])
    room = (min(limits) - clip["start"] - FIT_GAP) if limits else float("inf")
    if room <= 0:
        raise NeedsShorter(f"Sentence {number} has no time before the next sentence. Move it or shorten the translation.")
    target = _target(clip, next((s for s in _source_clips(data) if s["id"] == clip["source_clip"]), None), room)
    if base["duration"] > room:  # too long: faster, to end before the next sentence
        speed = base["duration"] / room
        if round(speed, 2) > MAX_SPEEDUP:  # as shown: a speed shown as 1.25x is within the limit
            raise NeedsShorter(f"Sentence {number} would need {speed:.2f}\u00d7 faster. Shorten the translation.")
    elif base["duration"] < target - SHORT_GAP:  # ends while the speaker still talks: slower, up to MIN_SPEED
        if not _can_lengthen(base["duration"], target):
            raise NeedsLonger(f"Sentence {number} would need {base['duration'] / target:.2f}\u00d7 to last as long as "
                              "its speaker. Lengthen the translation.")
        speed = max(base["duration"] / target, MIN_SPEED)
    else:  # the take it came from fits as it is (the next sentence moved): use that one
        if selected is base:
            raise ws.WorkspaceError(f"Sentence {number} already fits.")
        select_take(dub_id, clip_id, base["file"], language)
        return 1.0
    rate, samples = _read(path)
    faster = stretch(samples.astype(np.float32) / 32768, rate, speed)
    out = new_take_path(dub_id, clip_id, language)
    _write(out, rate, np.clip(np.round(faster * 32768), -32768, 32767))
    take = {key: value for key, value in base.items() if key not in ("file", "duration", "speed", "from")}
    add_take(dub_id, clip_id, {**take, "file": str(out), "duration": round(len(faster) / rate, 2),
                               "speed": round(speed, 2), "from": base["file"]}, language)
    return speed


def _original_take(clip: dict, take: dict) -> dict:
    """The take a sped-up take was made from (itself when it was not sped up, or its original is gone)."""
    return next((t for t in clip["takes"] if t["file"] == take.get("from")), take)


def _selected_duration(clip: dict) -> float | None:
    take = next((t for t in clip["takes"] if t["file"] == clip["selected"]), None)
    return take["duration"] if take else None


def fit(data: dict, language: str | None = None) -> dict[str, dict]:
    """Per dub clip: "missing" (no take), "fits", or "long" with `over` = seconds it runs into the next clip (by start)
    or past the end of the file, or "short" with `under` = seconds it ends before its speaker (more than SHORT_GAP);
    "speed" too when its take was stretched to fit; for a long or short one "need", the speed its original take would
    need (None: no time before the next sentence), and "can_fit", whether fit_take can do it."""
    clips = sorted(_dub_clips(data, language), key=lambda c: c["start"])
    end_of_file = data["source"]["duration"]
    kept = {s["id"] for s in _kept(data)}
    sources = {s["id"]: s for s in _source_clips(data)}
    result = {}
    for i, clip in enumerate(clips):
        if clip.get("source_clip") in kept:
            result[clip["id"]] = {"state": "kept", "over": 0.0}
            continue
        duration = _selected_duration(clip)
        if duration is None:
            result[clip["id"]] = {"state": "missing", "over": 0.0}
            continue
        limits = [c["start"] for c in clips[i + 1:i + 2]] + ([end_of_file] if end_of_file is not None else [])
        over = round(clip["start"] + duration - min(limits), 1) if limits else 0.0
        result[clip["id"]] = {"state": "long", "over": over} if over > 0 else {"state": "fits", "over": 0.0}
        selected = next(t for t in clip["takes"] if t["file"] == clip["selected"])
        if selected.get("speed"):  # sped up to fit: still listed under "Too long", with how much
            result[clip["id"]]["speed"] = selected["speed"]
        room = (min(limits) - clip["start"] - FIT_GAP) if limits else float("inf")
        original = _original_take(clip, selected)["duration"]
        if over > 0:
            need = round(original / room, 2) if room > 0 else None
            result[clip["id"]].update(need=need, can_fit=need is not None and need <= MAX_SPEEDUP)
            continue
        target = _target(clip, sources.get(clip.get("source_clip")), room)
        under = round(target - duration, 1)
        if duration < target - SHORT_GAP:  # the speaker is still talking when it ends
            result[clip["id"]].update(state="short", under=under, need=round(original / target, 2),
                                      can_fit=_can_lengthen(original, target))
    return result


def export_dub(dub_id: str, fmt: str = "wav", language: str | None = None) -> Path:
    """Mixes every selected take at its start over the original (at original_volume) into exports/<name>-<time>.<fmt>.
    Sentences without a take are silent; the original still plays under them."""
    if fmt not in ws.export_formats():
        raise ws.WorkspaceError(f"This computer cannot export {fmt.upper()} files.")
    data = load_dub(dub_id)
    if not audio_path(dub_id).exists():
        raise ws.WorkspaceError("The dub has no sound yet. Import the file again.")
    source_rate, source = _read(audio_path(dub_id))
    takes = []
    track = _track(data, language)
    kept = _kept(data)
    for n, clip in enumerate(track["clips"], 1):
        if not clip["selected"] or clip["source_clip"] in {s["id"] for s in kept}:
            continue
        path = dub_dir(dub_id) / clip["selected"]
        if not path.exists():
            raise ws.WorkspaceError(f"Sentence {n}: the selected take file is missing ({clip['selected']}). "
                                    "Generate it again or choose another take.")
        takes.append((clip["start"], *_read(path)))
    # Models write different sample rates (VoxCPM2 48 kHz, others 24 kHz): mix at the highest, so nothing is lost.
    rate = max([source_rate] + [take_rate for _, take_rate, _ in takes])
    original = source if source_rate == rate else ws._resample(source, source_rate, rate)
    # The original under the dub at its volume, and at full volume where a sentence keeps it (short fades, no clicks).
    gain = np.full(len(original), float(data["original_volume"]))
    fade = max(1, round(KEPT_FADE * rate))
    for source in kept:
        first, last = max(0, round(source["start"] * rate)), min(len(gain), round(source["end"] * rate))
        gain[first:last] = 1.0
        for i in range(fade):
            level = data["original_volume"] + (1 - data["original_volume"]) * (1 - (i + 1) / (fade + 1))
            for at in (first - 1 - i, last + i):
                if 0 <= at < len(gain):
                    gain[at] = max(gain[at], level)
    mix = original.astype(np.float64) * gain
    for start, take_rate, samples in takes:
        samples = samples if take_rate == rate else ws._resample(samples, take_rate, rate)
        first = round(start * rate)
        if first + len(samples) > len(mix):
            mix = np.concatenate([mix, np.zeros(first + len(samples) - len(mix))])
        mix[first:first + len(samples)] += samples
    mix = np.clip(np.round(mix), -32768, 32767).astype("<i2")
    folder = dub_dir(dub_id) / "exports"
    folder.mkdir(exist_ok=True)
    out = folder / f"{ws.slugify(data['name'])}-{track['language']}-{time.strftime('%Y%m%d-%H%M%S')}.{fmt}"
    if fmt == "wav":
        _write(out, rate, mix)
    else:
        major, subtype = ws.EXPORT_ENCODINGS[fmt]
        sf.write(str(out), mix.astype(np.float32) / 32768, rate, format=major, subtype=subtype)
    return out
