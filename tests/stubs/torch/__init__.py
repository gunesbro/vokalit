"""Stub torch for worker tests: records the last seed."""
last_seed = None


def manual_seed(seed):
    global last_seed
    last_seed = seed


class cuda:
    @staticmethod
    def is_available():
        return True
