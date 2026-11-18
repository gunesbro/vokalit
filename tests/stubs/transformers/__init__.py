"""Stub transformers for the Higgs worker: the "audio" it returns describes what generate_speech() received."""
import torch


class _Text:
    """Stands in for tensors/arrays: every method returns itself, str() is the description."""

    def __init__(self, text):
        self.text = text

    def __getattr__(self, name):
        return lambda *args, **kwargs: self

    def __str__(self):
        return self.text


class BitsAndBytesConfig:
    def __init__(self, load_in_8bit=False):
        self.load_in_8bit = load_in_8bit


class AutoTokenizer:
    @staticmethod
    def from_pretrained(repo, revision=None, local_files_only=False, **kwargs):
        print(f"stub tokenizer {repo}@{revision} offline={local_files_only}")
        return "tokenizer"


class _Config:
    sample_rate = 24000


class _Higgs:
    config = _Config()
    device = "cuda"

    def __init__(self, precision):
        self.precision = precision
        self._audio_codec = None

    def to(self, device):
        return self

    def eval(self):
        return self

    def generate_speech(self, text, tokenizer, *, reference_audio=None, reference_sample_rate=None, reference_text=None,
                        temperature=1.0, top_p=None, **kwargs):
        if text == "CRASH":
            raise RuntimeError("CUDA error: device-side assert triggered")
        if text == "OOM":
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        return _Text(f"text={text}|reference_audio={reference_audio}|reference_sample_rate={reference_sample_rate}"
                     f"|reference_text={reference_text}|temperature={temperature}|top_p={top_p}"
                     f"|precision={self.precision}|codec={self._audio_codec}|seed={torch.last_seed}")


class AutoModelForCausalLM:
    @staticmethod
    def from_pretrained(repo, revision=None, local_files_only=False, trust_remote_code=False, quantization_config=None,
                        **kwargs):
        precision = "8bit" if quantization_config and quantization_config.load_in_8bit else "bf16"
        print(f"stub higgs {repo}@{revision} offline={local_files_only} remote={trust_remote_code} {precision}")
        return _Higgs(precision)


class _Codec:
    def __init__(self, revision):
        self.revision = revision

    def to(self, device):
        return self

    def eval(self):
        return self

    def __str__(self):
        return f"codec@{self.revision}"


class AutoModel:
    @staticmethod
    def from_pretrained(repo, revision=None, local_files_only=False, **kwargs):
        return _Codec(revision)
