"""Stub ChatterboxMultilingualTTS: output text describes what generate() received."""
import torch


class _Wav:
    def __init__(self, value):
        self.value = value

    def squeeze(self, _):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.value


class ChatterboxMultilingualTTS:
    sr = 24000

    @classmethod
    def from_pretrained(cls, device):
        print(f"stub tts loaded on {device}")
        model = cls()
        model.conds = "BUILTIN"
        return model

    def generate(self, text, language_id, audio_prompt_path=None, exaggeration=0.5, cfg_weight=0.5,
                 temperature=0.8):
        if text == "CRASH":  # what a CUDA device-side assert looks like from Python
            raise RuntimeError("CUDA error: device-side assert triggered")
        if audio_prompt_path:
            self.conds = f"CLONE:{audio_prompt_path}"
        return _Wav(f"voice={self.conds}|language={language_id}|seed={torch.last_seed}|exaggeration={exaggeration}"
                    f"|cfg_weight={cfg_weight}|temperature={temperature}|text={text}")
