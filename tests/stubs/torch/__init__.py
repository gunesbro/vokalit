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

    @staticmethod
    def mem_get_info():  # (free, total) bytes; STUB_GPU_FREE_GB sets the free part
        import os
        return int(float(os.environ.get("STUB_GPU_FREE_GB", "12")) * 1e9), 12_000_000_000

float16, float32, bfloat16 = "float16", "float32", "bfloat16"


def from_numpy(array):
    return array
