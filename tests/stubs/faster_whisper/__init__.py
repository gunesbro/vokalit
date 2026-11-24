"""Stub faster-whisper: the transcript names the file and language; a path containing NET tries to connect."""
import os


class _Word:
    def __init__(self, start, end, word):
        self.start, self.end, self.word = start, end, word


class _Segment:
    def __init__(self, text, start=0.0, end=0.0):
        self.text, self.start, self.end = text, start, end
        self.words = [_Word(start, end, text)]
        self.avg_logprob = -0.25


class WhisperModel:
    def __init__(self, name, device="auto", compute_type="default"):
        print(f"stub whisper {name} loaded on {device} as {compute_type}")

    def transcribe(self, audio, language=None, **kwargs):
        if "NET" in audio:
            import socket
            socket.create_connection(("1.1.1.1", 443), timeout=1)
        # Two segments, as Whisper splits longer speech; their texts start with a space. Without a language it
        # "detects" Turkish.
        return iter([_Segment(f" heard:{os.path.basename(audio)}", 0.0, 2.5),
                     _Segment(f" :{language}", 3.0, 4.0)]), _Info(language or "tr")


class _Info:
    def __init__(self, language):
        self.language = language
