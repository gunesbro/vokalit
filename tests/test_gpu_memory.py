"""GPU memory: idle models make room for a new one; out of memory is retried once after unloading the others, then
reported clearly. Fake workers stand in for the model processes."""
import os
import threading

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402


class FakeWorker:
    """Replies with the next of `script[name]` ("ok", "oom", "oom-load")."""
    script = {}
    started = []

    def __init__(self, name):
        self.name = name
        self.lock = threading.Lock()
        self.last_used = 0.0
        FakeWorker.started.append(name)
        if FakeWorker.script.get(name) and FakeWorker.script[name][0] == "oom-load":
            FakeWorker.script[name].pop(0)
            raise models.OutOfGpuMemory("CUDA out of memory while loading")
        self.process = type("P", (), {"kill": lambda self: None, "wait": lambda self, timeout=None: 0})()

    def request(self, message):
        answer = FakeWorker.script.get(self.name, ["ok"]).pop(0) if FakeWorker.script.get(self.name) else "ok"
        if answer == "oom":
            return {"ok": False, "error": "CUDA out of memory. Tried to allocate 2.00 GiB", "oom": True}
        return {"ok": True, "seconds": 1.0}


@pytest.fixture
def fakes(monkeypatch):
    monkeypatch.setattr(models, "_Worker", FakeWorker)
    monkeypatch.setattr(models, "_free_vram_gb", lambda: None)  # unknown unless a test says otherwise
    monkeypatch.setitem(models.MODELS, "big", {"title": "Big", "vram_gb": 8, "settings": []})
    monkeypatch.setitem(models.MODELS, "small", {"title": "Small", "vram_gb": 2, "settings": []})
    FakeWorker.script, FakeWorker.started = {}, []
    models._workers.clear()
    yield
    models._workers.clear()


def test_out_of_memory_unloads_idle_models_and_retries(fakes):
    models._request("small", {})
    FakeWorker.script["big"] = ["oom", "ok"]
    assert models._request("big", {})["ok"]
    assert "small" not in models._workers  # it made room
    assert "big" in models._workers


def test_out_of_memory_while_loading_is_retried_too(fakes):
    models._request("small", {})
    FakeWorker.script["big"] = ["oom-load"]
    assert models._request("big", {})["ok"]
    assert FakeWorker.started == ["small", "big", "big"] and "small" not in models._workers


def test_still_out_of_memory_gives_a_clear_message(fakes):
    FakeWorker.script["big"] = ["oom", "oom"]
    with pytest.raises(RuntimeError) as error:
        models._request("big", {})
    message = str(error.value)
    assert message.startswith("Not enough GPU memory for Big")
    assert "Close other programs that use the GPU" in message
    assert "Variation" not in message


def test_a_busy_model_is_not_unloaded(fakes):
    models._request("small", {})
    FakeWorker.script["big"] = ["oom", "oom"]
    with models._workers["small"].lock:  # generating right now
        with pytest.raises(RuntimeError, match="Not enough GPU memory"):
            models._request("big", {})
    assert "small" in models._workers


def test_room_is_made_before_loading_when_the_gpu_is_full(fakes, monkeypatch):
    models._request("small", {})
    models._workers["small"].last_used = 1.0
    monkeypatch.setattr(models, "_free_vram_gb", lambda: 3.0 if "small" in models._workers else 9.0)
    models._request("big", {})  # needs 8 GB, 3 are free: the idle model goes first
    assert "small" not in models._workers and "big" in models._workers


def test_nothing_is_unloaded_when_there_is_room(fakes, monkeypatch):
    models._request("small", {})
    monkeypatch.setattr(models, "_free_vram_gb", lambda: 10.0)
    models._request("big", {})
    assert {"small", "big"} <= set(models._workers)


def test_least_recently_used_goes_first(fakes, monkeypatch):
    models._request("small", {})
    monkeypatch.setitem(models.MODELS, "mid", {"title": "Mid", "vram_gb": 2, "settings": []})
    models._request("mid", {})
    models._workers["small"].last_used, models._workers["mid"].last_used = 5.0, 1.0
    free = {"gb": 6.5}  # big needs 8 GB + 0.5 GB headroom
    monkeypatch.setattr(models, "_free_vram_gb", lambda: free["gb"])
    original_stop = models.stop
    monkeypatch.setattr(models, "stop", lambda name: (original_stop(name), free.update(gb=free["gb"] + 2))[0])
    models._request("big", {})  # unloading one 2 GB model is enough
    assert "mid" not in models._workers and "small" in models._workers
