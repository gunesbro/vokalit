"""Stub torch for worker tests: records the last seed."""
last_seed = None


def manual_seed(seed):
    global last_seed
    last_seed = seed


class cuda:
    @staticmethod
    def is_available():
        return True

    @staticmethod
    def memory_reserved():
        return 1_500_000_000

float16, float32 = "float16", "float32"
