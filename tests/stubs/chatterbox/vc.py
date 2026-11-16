"""Stub ChatterboxVC: counts loads; a source path containing NET tries to connect."""
from chatterbox.mtl_tts import _Wav


class ChatterboxVC:
    sr = 24000
    loads = 0

    @classmethod
    def from_pretrained(cls, device):
        print(f"stub vc loaded on {device}")
        cls.loads += 1
        return cls()

    def generate(self, audio, target_voice_path=None):
        if "NET" in audio:
            import socket
            socket.create_connection(("1.1.1.1", 443), timeout=1)
        return _Wav(f"vc_loads={ChatterboxVC.loads}|source={audio}|target={target_voice_path}")
