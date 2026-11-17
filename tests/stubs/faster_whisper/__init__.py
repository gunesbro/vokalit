"""Stub faster-whisper: the transcript names the file and language; a path containing NET tries to connect."""
import os


class _Segment:
    def __init__(self, text):
        self.text = text


class WhisperModel:
    def __init__(self, name, device="auto", compute_type="default"):
        print(f"stub whisper {name} loaded on {device} as {compute_type}")

    def transcribe(self, audio, language=None, **kwargs):
        if "NET" in audio:
            import socket
            socket.create_connection(("1.1.1.1", 443), timeout=1)
        # Two segments, as Whisper splits longer speech; their texts start with a space. Without a language it
        # "detects" Turkish.
        return iter([_Segment(f" heard:{os.path.basename(audio)}"), _Segment(f" :{language}")]), _Info(language or "tr")


class _Info:
    def __init__(self, language):
        self.language = language
