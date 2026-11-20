"""Stub OmniVoice: the "audio" it returns describes what generate() received."""
import torch


class _Estimator:
    def estimate_duration(self, target_text, ref_text, ref_duration):
        return ref_duration * len(target_text) / len(ref_text) if ref_text else 0.0


class _Config:
    frame_rate = 25


class _Tokenizer:
    config = _Config()


class OmniVoice:
    duration_estimator = _Estimator()
    audio_tokenizer = _Tokenizer()

    @classmethod
    def from_pretrained(cls, name, device_map=None, dtype=None):
        print(f"stub omnivoice {name} loaded on {device_map} as {dtype}")
        return cls()

    def generate(self, text, language=None, ref_text=None, ref_audio=None, speed=None, **kwargs):
        if ref_audio and not ref_text:
            print("stub omnivoice would load its own Whisper")
        if text == "CRASH":
            raise RuntimeError("CUDA error: device-side assert triggered")
        if text == "OOM":
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        extra = "|".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return [f"text={text}|language={language}|ref_audio={ref_audio}|ref_text={ref_text}|speed={speed}|{extra}"
                f"|seed={torch.last_seed}"]
