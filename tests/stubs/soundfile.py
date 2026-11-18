"""Stub soundfile for worker tests: writes the stub model's description as text."""


def write(path, data, samplerate, subtype=None):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{data}|sr={samplerate}|subtype={subtype}")


class _Audio:
    def mean(self, axis=None):
        return "ref-audio"


def read(path, dtype=None, always_2d=False):
    return _Audio(), 16000
