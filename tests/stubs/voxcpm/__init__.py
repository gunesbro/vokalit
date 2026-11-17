"""Stub VoxCPM: the "audio" it returns describes what generate() received."""
import torch


class _TTSModel:
    sample_rate = 48000


class VoxCPM:
    tts_model = _TTSModel()

    @classmethod
    def from_pretrained(cls, hf_model_id="openbmb/VoxCPM2", load_denoiser=True, **kwargs):
        print(f"stub voxcpm {hf_model_id} denoiser={load_denoiser} device={kwargs.get('device')} "
              f"optimize={kwargs.get('optimize', True)}")
        return cls()

    def generate(self, text, reference_wav_path=None, cfg_value=None, inference_timesteps=None, **kwargs):
        if text == "CRASH":
            raise RuntimeError("CUDA error: device-side assert triggered")
        if text == "OOM":
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        extra = "|".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return (f"text={text}|reference_wav_path={reference_wav_path}|cfg_value={cfg_value}"
                f"|inference_timesteps={inference_timesteps}|{extra}|seed={torch.last_seed}")
