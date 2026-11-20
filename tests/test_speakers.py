"""The speaker finder: grouping voices by their embeddings (pure), and the tool's install and requests. The worker
itself needs PyTorch, SpeechBrain and the model; it is checked on a real install with `python worker.py --selftest`."""
import importlib.util
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402

WORKERS = Path(__file__).resolve().parent.parent / "workers" / "speakers"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"speakers_{name}", WORKERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def grouping():
    return _load("grouping")


def _voice(direction, rng, noise=0.05):
    base = np.zeros(8)
    base[direction] = 1.0
    return base + rng.normal(0, noise, 8)


def test_two_voices_make_two_groups_by_first_appearance(grouping):
    rng = np.random.default_rng(1)
    embeddings = [_voice(1, rng), _voice(0, rng), _voice(1, rng), _voice(0, rng)]
    assert grouping.group(embeddings, [2.0] * 4) == [0, 1, 0, 1]


def test_count_forces_the_number_of_groups(grouping):
    rng = np.random.default_rng(2)
    three = [_voice(d, rng) for d in (0, 1, 2, 0, 1, 2)]
    assert len(set(grouping.group(three, [2.0] * 6, count=2))) == 2
    two = [_voice(d, rng) for d in (0, 1, 0, 1)]
    labels = grouping.group(two, [2.0] * 4, count=3)
    assert len(set(labels)) <= 3 and min(labels) == 0


def test_short_spans_join_the_nearest_group(grouping):
    rng = np.random.default_rng(3)
    embeddings = [_voice(0, rng), _voice(1, rng), _voice(1, rng, noise=0.2), _voice(0, rng)]
    labels = grouping.group(embeddings, [2.0, 2.0, 0.5, 2.0])
    assert labels[2] == labels[1] != labels[0]


def test_no_long_spans_is_one_group(grouping):
    rng = np.random.default_rng(4)
    assert grouping.group([_voice(d, rng) for d in (0, 1, 2)], [0.6] * 3) == [0, 0, 0]


def test_a_span_without_sound_has_no_speaker(grouping):
    rng = np.random.default_rng(5)
    assert grouping.group([_voice(0, rng), None, _voice(1, rng)], [2.0, 2.0, 2.0]) == [0, None, 1]


def test_many_spans_cluster_a_sample_and_label_all(grouping, monkeypatch):
    rng = np.random.default_rng(6)
    monkeypatch.setattr(grouping, "MAX_CLUSTERED", 100)
    directions = [i % 2 for i in range(2500)]
    labels = grouping.group([_voice(d, rng) for d in directions], [2.0] * 2500)
    assert set(labels) == {0, 1} and all(label == d for label, d in zip(labels, directions))


def test_speakers_is_a_tool():
    tool = models.TOOLS["speakers"]
    assert "speakers" not in models.MODELS
    assert tool["title"] == "Speaker finder (SpeechBrain ECAPA)"
    steps = [args for _, args in tool["pip_steps"]]
    assert models.TORCH_CUDA in steps and any("speechbrain==1.1.0" in args for args in steps)
    assert "Apache" in tool["license"] and "Hugging Face" in tool["downloads"]


def test_find_speakers_needs_the_tool(monkeypatch):
    monkeypatch.setattr(models, "is_installed", lambda name: False)
    with pytest.raises(RuntimeError, match="speaker finder is not installed"):
        models.find_speakers("a.wav", [[0.0, 1.0]])


def test_find_speakers_sends_one_request(monkeypatch):
    sent = []
    monkeypatch.setattr(models, "is_installed", lambda name: True)
    monkeypatch.setattr(models, "_request", lambda name, message: sent.append((name, message)) or {"ok": True, "labels": [0]})
    assert models.find_speakers("a.wav", [[0.0, 1.0]]) == [0]
    assert sent == [("speakers", {"task": "speakers", "audio": "a.wav", "spans": [[0.0, 1.0]], "count": None})]


def test_the_worker_uses_the_installed_model_when_run_by_hand(monkeypatch):
    monkeypatch.delenv("HF_HOME", raising=False)
    worker = _load("worker")
    assert worker.cache().as_posix().endswith(".local/speakers/cache/ecapa")
