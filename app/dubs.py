"""Dubs under workspace/dubs/<id>/: an audio or video file whose sentences are spoken again in another language, in
their own voices. Stored as tracks of clips (seconds, never pixels), so the timeline can grow into an editor.

dub.json, source.<ext> (the imported file), audio.wav (its sound, decoded by the window), refs/, takes/, exports/.
"""
import os
import re
import shutil
import subprocess
import tempfile
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
REFERENCE_TARGET = 8.0  # seconds: a reference grows with the same speaker's nearby sentences until this long
REFERENCE_MAX = 10.0  # and never longer (the models clone best from 3-10 s)
REFERENCE_GAP = 0.25  # seconds of silence between the joined sentences
REFERENCE_WINDOW = 60.0  # seconds: only sentences this close are joined, so the moment's mood carries
MIN_REFERENCE_PIECE = 0.5  # seconds: shorter sentences add little and are often misheard
KEPT_FADE = 0.05  # seconds to fade the original up and down around a sentence that keeps it
MAX_SPEEDUP = 1.25  # a take is sped up at most this much to fit; beyond it speech stops sounding natural
FIT_GAP = 0.05  # seconds left free before the next sentence when a take is fitted
MIN_SPEED = 0.85  # a take that ends early is slowed down at most this much; slower drags
MIN_SENTENCE = 0.2  # seconds: the shortest sentence that can be added or retimed by hand
LEVEL_FRAME = 0.05  # seconds per frame when measuring how loud speech is
LEVEL_GATE_DB = 30  # frames this far below the loudest are pauses, not speech
LEVEL_MAX_GAIN_DB = 12  # a new take is raised or lowered at most this much to match its sentence
LEVEL_PEAK_DB = -1  # and never peaks above this (dBFS)
SHORT_GAP = 0.4  # seconds a take may end before its speaker does without counting as too short


class NeedsShorter(ws.WorkspaceError):
    """A take cannot be fitted by speeding it up: its translation has to be shorter."""


class NeedsLonger(ws.WorkspaceError):
    """A take ends too early even slowed down: its translation has to be longer."""


def _target(clip: dict, source: dict | None, room: float) -> float:
    """Where a dub clip's take should end, in seconds from its start: when its speaker stops, but never past the room
    before the next sentence. Without a source sentence there is no speaker to match: 0, never too short."""
    return min(room, source["end"] - clip["start"]) if source else 0.0


def _room(data: dict, clips: list[dict], clip: dict) -> float:
    """Seconds a clip's take may last: until FIT_GAP before the next sentence (by start) or the end of the file."""
    order = sorted(clips, key=lambda c: c["start"])
    following = order[order.index(clip) + 1:order.index(clip) + 2]
    limits = [c["start"] for c in following] + ([data["source"]["duration"]] if data["source"]["duration"] else [])
    return (min(limits) - clip["start"] - FIT_GAP) if limits else float("inf")


def generation_timing(dub_id: str, clip_id: str, language: str | None = None) -> dict | None:
    """For a model that can fix its length: where a clip's new take should end (as _target), and the speeds it may
    take to get there. None when there is no speaker to match or no room."""
    data = load_dub(dub_id)
    clips = _dub_clips(data, language)
    clip = _find(clips, clip_id)
    source = next((s for s in _source_clips(data) if s["id"] == clip.get("source_clip")), None)
    target = round(_target(clip, source, _room(data, clips, clip)), 2)
    if source is None or target <= 0:
        return None
    return {"target": target, "min_speed": MIN_SPEED, "max_speed": MAX_SPEEDUP}


def _can_lengthen(duration: float, target: float, pace: float = 1.0) -> bool:
    """Slowed down to MIN_SPEED of its natural pace at most (a timed take was made at `pace`), the take ends within
    SHORT_GAP of the target."""
    return duration / min(MIN_SPEED / pace, 1.0) >= target - SHORT_GAP


def _root() -> Path:
    return ws.workspace_root() / "dubs"


def dub_dir(dub_id: str) -> Path:
    return _root() / dub_id


def _file(dub_id: str) -> Path:
    return dub_dir(dub_id) / "dub.json"


def audio_path(dub_id: str) -> Path:
    """The source's sound as WAV (written by set_source_audio)."""
    return dub_dir(dub_id) / "audio.wav"


def voices_path(dub_id: str) -> Path:
    """The source's speech, separated from its music and effects (Demucs); same rate as audio.wav."""
    return dub_dir(dub_id) / "voices.wav"


def background_path(dub_id: str) -> Path:
    """The source's music and effects, without the speech."""
    return dub_dir(dub_id) / "background.wav"


def stems_temp(dub_id: str) -> tuple[Path, Path]:
    """Where a separation writes; keep_stems puts both in place, so half-written files never count."""
    return dub_dir(dub_id) / "voices.part.wav", dub_dir(dub_id) / "background.part.wav"


def keep_stems(dub_id: str) -> None:
    """Both new stems in place, or (a file in use can refuse a rename on Windows) the previous pair back."""
    pairs = list(zip(stems_temp(dub_id), (voices_path(dub_id), background_path(dub_id))))
    old = [(path, path.with_name(path.stem + ".old.wav")) for _, path in pairs if path.exists()]
    for path, aside in old:
        os.replace(path, aside)
    try:
        for temp, path in pairs:
            os.replace(temp, path)
    except OSError:
        for path, aside in old:
            os.replace(aside, path)
        raise
    for _, aside in old:
        aside.unlink(missing_ok=True)


def has_stems(dub_id: str) -> bool:
    return voices_path(dub_id).exists() and background_path(dub_id).exists()


def remove_stems(dub_id: str) -> None:
    for path in (voices_path(dub_id), background_path(dub_id), *stems_temp(dub_id)):
        path.unlink(missing_ok=True)


def _fitted(samples: np.ndarray, length: int) -> np.ndarray:
    """A stem trimmed or padded with silence to the sound's length (resampling can be a few samples off)."""
    return samples[:length] if len(samples) >= length else np.concatenate([samples, np.zeros(length - len(samples),
                                                                                           samples.dtype)])


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
        "original_volume": DEFAULT_ORIGINAL_VOLUME,  # the whole original under the dub, without separated stems
        "voices_volume": 0.0,  # the original voices under the dub, with stems (the background is always at full level)
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
    """Dubs from before several languages: the single dub track takes the dub's target language, model and settings.
    Dubs from before voice separation start with the original voices off once separated."""
    data.setdefault("voices_volume", 0.0)
    data.setdefault("speakers", [])
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
        data["last_sentence"] = len(sources)
        data["speakers"] = []  # new sentences: who says them is found again


def _next_sentence(data: dict) -> int:
    """The number of a new sentence's ids (o<n>, d<n>). A counter that only grows, so a sentence that undo can bring
    back never finds its id taken; dubs from before it start after their highest id."""
    if "last_sentence" not in data:
        numbers = [int(c["id"][1:]) for track in data["tracks"] for c in track["clips"]]
        data["last_sentence"] = max(numbers, default=0)
    data["last_sentence"] += 1
    return data["last_sentence"]


def _new_speaker(data: dict, name: str) -> dict:
    """A speaker with an id never used before in this dub (s<n>), so an undo step never points at someone else."""
    data["last_speaker"] = max([data.get("last_speaker", 0)] + [int(s["id"][1:]) for s in data["speakers"]]) + 1
    speaker = {"id": f"s{data['last_speaker']}", "name": name}
    data["speakers"].append(speaker)
    return speaker


def set_found_speakers(dub_id: str, labels: dict) -> int:
    """Who says each sentence, as the speaker finder grouped them ({sentence id: label}, None: unknown); by id, so a
    sentence deleted or moved while it searched cannot pass its speaker to a neighbour (one added meanwhile stays
    unknown). Replaces the speakers, named "Speaker 1..n", and every sentence's speaker. Returns how many there are."""
    with _editing(dub_id) as data:
        data["speakers"] = []
        # Label k is "Speaker k+1" (the finder numbers them by first appearance).
        ids = {label: _new_speaker(data, f"Speaker {label + 1}")["id"]
               for label in sorted({label for label in labels.values() if label is not None})}
        for source in _source_clips(data):
            label = labels.get(source["id"])
            if label is None:
                source.pop("speaker", None)
            else:
                source["speaker"] = ids[label]
        return len(ids)


def set_speaker(dub_id: str, source_id: str, speaker: str | None) -> str | None:
    """A sentence's speaker: an id, "new" (a new speaker, named the lowest free "Speaker n"), or None (unknown).
    Returns the speaker's id."""
    with _editing(dub_id) as data:
        source = _find(_source_clips(data), source_id)
        if speaker == "new":
            names = {s["name"] for s in data["speakers"]}
            speaker = _new_speaker(data, next(f"Speaker {n}" for n in range(1, len(names) + 2)
                                              if f"Speaker {n}" not in names))["id"]
        elif speaker is not None and not any(s["id"] == speaker for s in data["speakers"]):
            raise ws.WorkspaceError("This speaker no longer exists.")
        if speaker is None:
            source.pop("speaker", None)
        else:
            source["speaker"] = speaker
        return speaker


def speakers_state(data: dict) -> dict:
    """The speakers and who says each sentence: what undoing a merge or a new search puts back."""
    return {"speakers": [dict(s) for s in data["speakers"]],
            "assignments": {s["id"]: s["speaker"] for s in _source_clips(data) if s.get("speaker")}}


def restore_speakers(dub_id: str, state: dict) -> None:
    """Puts speakers_state back (sentences no longer there are skipped; speakers not in the list are dropped)."""
    with _editing(dub_id) as data:
        data["speakers"] = [{"id": str(s["id"]), "name": str(s["name"])} for s in state.get("speakers") or []]
        data["last_speaker"] = max([data.get("last_speaker", 0)] + [int(s["id"][1:]) for s in data["speakers"]])
        known = {s["id"] for s in data["speakers"]}
        assignments = state.get("assignments") or {}
        for source in _source_clips(data):
            speaker = assignments.get(source["id"])
            if speaker in known:
                source["speaker"] = speaker
            else:
                source.pop("speaker", None)


def rename_speaker(dub_id: str, speaker_id: str, name: str) -> None:
    if not name.strip():
        raise ws.WorkspaceError("A speaker needs a name.")
    with _editing(dub_id) as data:
        speaker = next((s for s in data["speakers"] if s["id"] == speaker_id), None)
        if speaker is None:
            raise ws.WorkspaceError("This speaker no longer exists.")
        speaker["name"] = name.strip()


def merge_speakers(dub_id: str, speaker_id: str, into_id: str) -> None:
    """One person found as two: every sentence of `speaker_id` goes to `into_id`, and `speaker_id` is removed."""
    with _editing(dub_id) as data:
        ids = {s["id"] for s in data["speakers"]}
        if speaker_id == into_id or speaker_id not in ids or into_id not in ids:
            raise ws.WorkspaceError("Choose another speaker to merge into.")
        for source in _source_clips(data):
            if source.get("speaker") == speaker_id:
                source["speaker"] = into_id
        data["speakers"] = [s for s in data["speakers"] if s["id"] != speaker_id]


def _check_times(data: dict, start: float, end: float) -> None:
    if not (end - start >= MIN_SENTENCE):
        raise ws.WorkspaceError(f"A sentence must end after it starts and last at least {MIN_SENTENCE} s.")
    duration = data["source"]["duration"] or 0.0
    if start < 0 or end > duration:
        raise ws.WorkspaceError(f"A sentence must lie within the sound (0\u2013{duration:.1f} s).")


def _sort_sentences(data: dict) -> None:
    """Sentences in time order (stable), and every language's clips in the order of their sentences."""
    sources = data["tracks"][0]["clips"]
    sources.sort(key=lambda s: s["start"])
    order = {s["id"]: n for n, s in enumerate(sources)}
    for track in data["tracks"][1:]:
        track["clips"].sort(key=lambda c: order.get(c["source_clip"], len(order)))


def add_source_clip(dub_id: str, start: float, end: float, text: str = "") -> str:
    """A sentence Whisper missed, added by hand: in time order, with an empty clip at its start in every language.
    Returns its id."""
    start, end = round(float(start), 3), round(float(end), 3)
    with _editing(dub_id) as data:
        _check_times(data, start, end)
        n = _next_sentence(data)
        source = {"id": f"o{n}", "start": start, "end": end, "text": text.strip()}
        place = sum(1 for s in _source_clips(data) if s["start"] <= start)
        _source_clips(data).insert(place, source)
        for track in data["tracks"][1:]:
            track["clips"].insert(place, _new_clip(n, source))
        _sort_sentences(data)  # clips may not have followed the sentences' order exactly
    return source["id"]


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


def update_source_clip(dub_id: str, clip_id: str, text: str | None = None, start: float | None = None,
                       end: float | None = None) -> None:
    """A sentence's text, or its times: a new start moves its clip in every language by as much (a clip moved by hand
    keeps its offset), and the sentences stay in time order."""
    with _editing(dub_id) as data:
        source = _find(_source_clips(data), clip_id)
        if text is not None:
            source["text"] = text.strip()
        if start is None and end is None:
            return
        new_start = source["start"] if start is None else round(float(start), 3)
        new_end = source["end"] if end is None else round(float(end), 3)
        _check_times(data, new_start, new_end)
        shift = new_start - source["start"]
        source["start"], source["end"] = new_start, new_end
        for track in data["tracks"][1:]:
            for clip in track["clips"]:
                if clip["source_clip"] == clip_id:
                    clip["start"] = round(max(0.0, clip["start"] + shift), 3)
        _sort_sentences(data)


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
        if source.get("speaker") not in {s["id"] for s in data["speakers"]}:  # merged away meanwhile
            source = {k: v for k, v in source.items() if k != "speaker"}
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


def set_options(dub_id: str, *, original_volume: float | None = None, voices_volume: float | None = None) -> None:
    if original_volume is not None and not 0 <= original_volume <= 1:
        raise ws.WorkspaceError("The original's volume must be between 0 and 100 %.")
    if voices_volume is not None and not 0 <= voices_volume <= 1:
        raise ws.WorkspaceError("The original voices' volume must be between 0 and 100 %.")
    with _editing(dub_id) as data:
        if original_volume is not None:
            data["original_volume"] = round(float(original_volume), 3)
        if voices_volume is not None:
            data["voices_volume"] = round(float(voices_volume), 3)


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


def delete_takes(dub_id: str, files_by_clip: dict, language: str | None = None) -> int:
    """Deletes takes, files included: {clip id: [files], or None for all of its takes}. A sentence whose selected take
    goes uses its newest remaining one. Returns how many were deleted. Not undoable."""
    with _editing(dub_id) as data:
        by_id = {c["id"]: c for c in _dub_clips(data, language)}  # one lookup table: a tab can hold 30k sentences
        gone = []
        for clip_id, files in files_by_clip.items():
            clip = by_id.get(clip_id)
            if clip is None:
                raise ws.WorkspaceError("This sentence no longer exists. Reload the dub.")
            doomed = clip["takes"] if files is None else [t for t in clip["takes"] if t["file"] in set(files)]
            if files is not None and len(doomed) != len(set(files)):
                raise ws.WorkspaceError("This take no longer exists.")
            clip["takes"] = [t for t in clip["takes"] if t not in doomed]
            if clip["selected"] in {t["file"] for t in doomed}:
                clip["selected"] = clip["takes"][-1]["file"] if clip["takes"] else None
            gone += [t["file"] for t in doomed]
    for file in gone:  # after the save: nothing points at them
        try:
            (dub_dir(dub_id) / file).unlink(missing_ok=True)
        except OSError:  # in use (Windows, a file being played): the dub no longer refers to it either way
            pass
    return len(gone)


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


def _read_span(path: Path, start: float, end: float) -> tuple[int, np.ndarray]:
    """Only the samples from `start` to `end` seconds (fewer past the end of the file): a sentence of a long sound
    without reading all of it."""
    with wave.open(str(path), "rb") as w:
        rate, frames = w.getframerate(), w.getnframes()
        first = min(frames, max(0, round(start * rate)))
        w.setpos(first)
        return rate, np.frombuffer(w.readframes(max(0, min(frames, round(end * rate)) - first)), dtype="<i2")


def _write(path: Path, rate: int, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype("<i2").tobytes())


def _loudness(samples: np.ndarray, rate: int) -> float | None:
    """How loud speech is, in dB of 16-bit full scale: the mean power of the LEVEL_FRAME frames within LEVEL_GATE_DB
    of the loudest, so pauses do not count. None for no sound."""
    size = min(max(1, round(LEVEL_FRAME * rate)), len(samples))  # a sound shorter than a frame is one frame
    if size == 0:
        return None
    frames = samples[:len(samples) // size * size].astype(np.float64).reshape(-1, size)
    power = (frames ** 2).mean(axis=1)
    if power.max() <= 0:
        return None
    speech = power[power >= power.max() * 10 ** (-LEVEL_GATE_DB / 10)]
    return 10 * np.log10(speech.mean() / 32767 ** 2)


def match_level(dub_id: str, clip_id: str, take: Path, language: str | None = None) -> float:
    """Raises or lowers a new take to how loud its sentence was spoken (the voices when separated, else the whole
    sound), at most LEVEL_MAX_GAIN_DB and never peaking above LEVEL_PEAK_DB. Rewrites the take; returns the gain in
    dB, 0.0 (untouched) when either is silent."""
    data = load_dub(dub_id)
    source = _find(_source_clips(data), _find(_dub_clips(data, language), clip_id)["source_clip"])
    rate, original = _read_span(voices_path(dub_id) if has_stems(dub_id) else audio_path(dub_id), source["start"],
                                source["end"])
    take_rate, samples = _read(take)
    wanted = _loudness(original, rate)
    current = _loudness(samples, take_rate)
    if wanted is None or current is None:
        return 0.0
    gain = min(max(wanted - current, -LEVEL_MAX_GAIN_DB), LEVEL_MAX_GAIN_DB)
    peak = int(np.abs(samples.astype(np.int32)).max())
    gain = min(gain, 20 * np.log10(32767 * 10 ** (LEVEL_PEAK_DB / 20) / peak))
    _write(take, take_rate, np.clip(np.round(samples * 10 ** (gain / 20)), -32768, 32767))
    return round(float(gain), 2)


def _reference_pieces(data: dict, base: dict) -> list[dict]:
    """The sentences a reference is made of, in time order: `base`, then (when its speaker is known) the same speaker's
    sentences nearest in time, within REFERENCE_WINDOW, until REFERENCE_TARGET seconds, never past REFERENCE_MAX. Never
    another speaker's: in a dialogue the neighbours are often the other person."""
    length = lambda s: s["end"] - s["start"] + 2 * REFERENCE_PADDING  # noqa: E731
    pieces, total = [base], length(base)
    speaker = base.get("speaker")
    if speaker and total < REFERENCE_TARGET:
        distance = lambda s: max(0.0, s["start"] - base["end"], base["start"] - s["end"])  # noqa: E731
        kept = {s["id"] for s in _kept(data)}
        nearby = sorted((s for s in _source_clips(data) if s.get("speaker") == speaker and s["id"] != base["id"]
                         and s["id"] not in kept and s["text"].strip()  # its words go in the reference's text
                         and s["end"] - s["start"] >= MIN_REFERENCE_PIECE
                         and distance(s) <= REFERENCE_WINDOW), key=distance)
        for source in nearby:
            if total >= REFERENCE_TARGET:
                break
            if total + REFERENCE_GAP + length(source) <= REFERENCE_MAX:
                pieces.append(source)
                total += REFERENCE_GAP + length(source)
    return sorted(pieces, key=lambda s: s["start"])


def cut_reference(dub_id: str, clip_id: str, language: str | None = None) -> tuple[Path, str]:
    """The voice reference for a dub clip: its "voice from" sentence, joined with the same speaker's nearby sentences
    (_reference_pieces), each with a little padding and a short silence between; and their text, in the same order."""
    data = load_dub(dub_id)
    base = _find(_source_clips(data), _find(_dub_clips(data, language), clip_id)["voice_from"])
    sound = voices_path(dub_id) if has_stems(dub_id) else audio_path(dub_id)  # clean speech when separated
    pieces = _reference_pieces(data, base)
    # Sentences whose padded spans touch are one stretch of speech: read once, so nothing is heard twice and no
    # silence cuts a word the text runs straight through.
    stretches = []
    for source in pieces:
        start, end = source["start"] - REFERENCE_PADDING, source["end"] + REFERENCE_PADDING
        if stretches and start <= stretches[-1][1]:
            stretches[-1][1] = max(stretches[-1][1], end)
        else:
            stretches.append([start, end])
    parts, rate = [], None
    for n, (start, end) in enumerate(stretches):
        rate, samples = _read_span(sound, start, end)
        if n:
            parts.append(np.zeros(round(REFERENCE_GAP * rate), dtype=samples.dtype))
        parts.append(samples)
    folder = dub_dir(dub_id) / "refs"
    folder.mkdir(exist_ok=True)
    path = folder / f"{base['id']}.wav"
    _write(path, rate, np.concatenate(parts))
    return path, " ".join(s["text"] for s in pieces if s["text"])


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
    room = _room(data, clips, clip)
    if room <= 0:
        raise NeedsShorter(f"Sentence {number} has no time before the next sentence. Move it or shorten the translation.")
    target = _target(clip, next((s for s in _source_clips(data) if s["id"] == clip["source_clip"]), None), room)
    pace = base.get("pace", 1.0)  # a timed take was already made faster or slower than natural: the limits count it
    if base["duration"] > room:  # too long: faster, to end before the next sentence
        speed = base["duration"] / room
        if round(speed * pace, 2) > MAX_SPEEDUP:  # as shown: a speed shown as 1.25x is within the limit
            raise NeedsShorter(f"Sentence {number} would need {speed * pace:.2f}\u00d7 faster. Shorten the translation.")
    elif base["duration"] < target - SHORT_GAP:  # ends while the speaker still talks: slower, up to MIN_SPEED
        if not _can_lengthen(base["duration"], target, pace):
            raise NeedsLonger(f"Sentence {number} would need {base['duration'] / target * pace:.2f}\u00d7 to last as "
                              "long as its speaker. Lengthen the translation.")
        speed = max(base["duration"] / target, min(MIN_SPEED / pace, 1.0))
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
        if selected.get("speed") and _original_take(clip, selected) is not selected:  # sped up to fit: still listed
            # under "Too long", with how much (not once its original is deleted: there is nothing to go back to)
            result[clip["id"]]["speed"] = selected["speed"]
        room = (min(limits) - clip["start"] - FIT_GAP) if limits else float("inf")
        base = _original_take(clip, selected)
        original, pace = base["duration"], base.get("pace", 1.0)  # a timed take's limits count its pace
        if over > 0:
            need = round(original / room, 2) if room > 0 else None
            result[clip["id"]].update(need=need, can_fit=need is not None and round(need * pace, 2) <= MAX_SPEEDUP)
            continue
        target = _target(clip, sources.get(clip.get("source_clip")), room)
        under = round(target - duration, 1)
        if duration < target - SHORT_GAP:  # the speaker is still talking when it ends
            result[clip["id"]].update(state="short", under=under, need=round(original / target, 2),
                                      can_fit=_can_lengthen(original, target, pace))
    return result


def export_dub(dub_id: str, fmt: str = "wav", language: str | None = None) -> Path:
    """The dub's sound (mix_dub) as exports/<name>-<language>-<time>.<fmt>."""
    if fmt not in ws.export_formats():
        raise ws.WorkspaceError(f"This computer cannot export {fmt.upper()} files.")
    data = load_dub(dub_id)
    rate, mix = mix_dub(dub_id, language)
    out = _export_path(dub_id, data, _track(data, language)["language"], fmt)
    if fmt == "wav":
        _write(out, rate, mix)
    else:
        major, subtype = ws.EXPORT_ENCODINGS[fmt]
        sf.write(str(out), mix.astype(np.float32) / 32768, rate, format=major, subtype=subtype)
    return out


def _export_path(dub_id: str, data: dict, label: str, ext: str) -> Path:
    folder = dub_dir(dub_id) / "exports"
    folder.mkdir(exist_ok=True)
    return folder / f"{ws.slugify(data['name'])}-{label}-{time.strftime('%Y%m%d-%H%M%S')}.{ext}"


# ISO 639-2/B codes for a video's audio tracks (players show them), for every two-letter code the app offers;
# three-letter codes (ISO 639-3) are kept as they are.
LANGUAGE_TAGS = {"ab": "abk", "af": "afr", "am": "amh", "an": "arg", "ar": "ara", "as": "asm", "az": "aze",
                 "ba": "bak", "be": "bel", "bg": "bul", "bn": "ben", "bo": "tib", "br": "bre", "bs": "bos",
                 "ca": "cat", "cs": "cze", "cv": "chv", "cy": "wel", "da": "dan", "de": "ger", "dv": "div",
                 "el": "gre", "en": "eng", "eo": "epo", "es": "spa", "et": "est", "eu": "baq", "fa": "per",
                 "ff": "ful", "fi": "fin", "fr": "fre", "fy": "fry", "ga": "gle", "gl": "glg", "gn": "grn",
                 "gu": "guj", "gv": "glv", "ha": "hau", "he": "heb", "hi": "hin", "hr": "hrv", "ht": "hat",
                 "hu": "hun", "hy": "arm", "hz": "her", "ia": "ina", "id": "ind", "ig": "ibo", "ik": "ipk",
                 "is": "ice", "it": "ita", "ja": "jpn", "jv": "jav", "ka": "geo", "kj": "kua", "kk": "kaz",
                 "km": "khm", "kn": "kan", "ko": "kor", "ks": "kas", "kw": "cor", "ky": "kir", "la": "lat",
                 "lb": "ltz", "lg": "lug", "ln": "lin", "lo": "lao", "lt": "lit", "lv": "lav", "mi": "mao",
                 "mk": "mac", "ml": "mal", "mn": "mon", "mr": "mar", "ms": "may", "mt": "mlt", "my": "bur",
                 "nb": "nob", "ne": "nep", "ng": "ndo", "nl": "dut", "nn": "nno", "no": "nor", "ny": "nya",
                 "oc": "oci", "om": "orm", "os": "oss", "pa": "pan", "pl": "pol", "ps": "pus", "pt": "por",
                 "rm": "roh", "ro": "rum", "ru": "rus", "rw": "kin", "sa": "san", "sc": "srd", "sd": "snd",
                 "si": "sin", "sk": "slo", "sl": "slv", "sn": "sna", "so": "som", "sq": "alb", "sr": "srp",
                 "sv": "swe", "sw": "swa", "ta": "tam", "te": "tel", "tg": "tgk", "th": "tha", "ti": "tir",
                 "tk": "tuk", "tl": "tgl", "tn": "tsn", "tr": "tur", "tt": "tat", "tw": "twi", "ug": "uig",
                 "uk": "ukr", "ur": "urd", "uz": "uzb", "vi": "vie", "wo": "wol", "xh": "xho", "yi": "yid",
                 "yo": "yor", "zh": "chi", "zu": "zul"}


def export_video(dub_id: str, language: str | None = None, every_language: bool = False, ffmpeg: str | None = None,
                 names: dict | None = None) -> Path:
    """The dub's video as it is (copied, not encoded again) with the dub as its sound: `language`'s mix, or every
    language's then the original sound, each its own track (`names`: language names for the track titles). MP4 gets
    AAC, WebM gets Opus, in the source's own container. `ffmpeg`: the program's path. Nothing is left on failure."""
    data = load_dub(dub_id)
    if data["source"]["kind"] != "video":
        raise ws.WorkspaceError("This dub has no video. Export the sound instead.")
    if not ffmpeg:
        raise ws.WorkspaceError("Install Video export (FFmpeg) on the Models screen.")
    names = names or {}
    ext = Path(data["source"]["file"]).suffix.lstrip(".")
    codes = languages(data) if every_language else [_track(data, language)["language"]]
    tracks = [(code, names.get(code, code)) for code in codes]
    if every_language:
        tracks.append((data["source"]["language"], "Original"))
    out = _export_path(dub_id, data, "all" if every_language else codes[0], ext)
    n = 2
    while out.exists():  # two exports in the same second: a failure must never delete the earlier one
        out = out.with_name(f"{out.stem.rsplit('~', 1)[0]}~{n}{out.suffix}")
        n += 1
    temporary = []
    try:
        for n, (code, _) in enumerate(tracks):
            handle, name = tempfile.mkstemp(prefix="video-", suffix=".wav.tmp", dir=dub_dir(dub_id))  # own names:
            os.close(handle)  # two exports at once do not share their inputs
            path = Path(name)
            temporary.append(path)
            if n < len(codes):
                _write(path, *mix_dub(dub_id, code))
            else:  # the original sound, as imported
                _write(path, *_read(audio_path(dub_id)))
        args = [ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-protocol_whitelist", "file",
                "-i", str(dub_dir(dub_id) / data["source"]["file"])]
        for path in temporary:
            args += ["-i", str(path)]
        args += ["-map", "0:v:0"] + [arg for n in range(len(tracks)) for arg in ("-map", f"{n + 1}:a:0")]
        args += ["-c:v", "copy"] + (["-c:a", "libopus", "-b:a", "128k"] if ext == "webm" else ["-c:a", "aac", "-b:a", "192k"])
        for n, (code, title) in enumerate(tracks):
            # MP4 keeps a track's name as its handler name, Matroska/WebM as its title: both are set.
            args += [f"-metadata:s:a:{n}", f"language={LANGUAGE_TAGS.get(code, code or 'und')}",
                     f"-metadata:s:a:{n}", f"title={title}", f"-metadata:s:a:{n}", f"handler_name={title}",
                     f"-disposition:a:{n}", "default" if n == 0 else "0"]
        # FFmpeg writes UTF-8 (paths with \u015e or \u011f included); Windows' own code page cannot read it.
        result = subprocess.run(args + [str(out)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise ws.WorkspaceError(f"The video could not be exported: {_ffmpeg_reason(result)}")
        return out
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)


def _ffmpeg_reason(result) -> str:
    """FFmpeg's error lines (it is run at -loglevel error, so they are few), without their "[muxer @ 0x...]" prefixes
    and repeats: the reason is often not the last line."""
    lines = []
    for line in result.stderr.splitlines():
        line = re.sub(r"^\[[^\]]*@ 0x[0-9a-f]+\]\s*", "", line.strip())
        if line and line not in lines:
            lines.append(line)
    return " ".join(lines)[:400] or f"FFmpeg stopped with code {result.returncode}"


def mix_dub(dub_id: str, language: str | None = None) -> tuple[int, np.ndarray]:
    """The dub's sound as 16-bit samples: every selected take at its start over the original (at original_volume);
    with separated stems, over the background at full level and the original voices at voices_volume. Sentences
    without a take are silent; the original still plays under them."""
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

    def at_rate(samples):
        return samples if source_rate == rate else ws._resample(samples, source_rate, rate)

    # Separated: the background at full level and the original voices at their volume; otherwise the whole original.
    stems = has_stems(dub_id)
    original = at_rate(_fitted(_read(voices_path(dub_id))[1], len(source)) if stems else source)
    background = at_rate(_fitted(_read(background_path(dub_id))[1], len(source))) if stems else None
    volume = float(data["voices_volume"] if stems else data["original_volume"])
    # Under the dub at its volume, and at full volume where a sentence keeps the original (short fades, no clicks).
    gain = np.full(len(original), volume)
    fade = max(1, round(KEPT_FADE * rate))
    for source in kept:
        first, last = max(0, round(source["start"] * rate)), min(len(gain), round(source["end"] * rate))
        gain[first:last] = 1.0
        for i in range(fade):
            level = volume + (1 - volume) * (1 - (i + 1) / (fade + 1))
            for at in (first - 1 - i, last + i):
                if 0 <= at < len(gain):
                    gain[at] = max(gain[at], level)
    mix = original.astype(np.float64) * gain
    if background is not None:
        mix += background[:len(mix)]
    for start, take_rate, samples in takes:
        samples = samples if take_rate == rate else ws._resample(samples, take_rate, rate)
        first = round(start * rate)
        if first + len(samples) > len(mix):
            mix = np.concatenate([mix, np.zeros(first + len(samples) - len(mix))])
        mix[first:first + len(samples)] += samples
    return rate, np.clip(np.round(mix), -32768, 32767).astype("<i2")
