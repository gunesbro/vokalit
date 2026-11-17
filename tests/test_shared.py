"""Models share identical package files through one uv cache (hard links); clean-up is automatic."""
import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("VOKALIT_UV", "uv")
import models  # noqa: E402


@pytest.fixture
def local(tmp_path, monkeypatch):
    """Two fake models "a" and "b". Installing links files from the shared cache into the model's venv, as uv does;
    each package also leaves a downloaded archive in the cache that no venv uses."""
    monkeypatch.setattr(models, "LOCAL", str(tmp_path))
    for name, packages in (("a", ["torch", "only-a"]), ("b", ["torch", "only-b"])):
        monkeypatch.setitem(models.MODELS, name, {"title": name.upper(), "settings": [],
                                                  "pip_steps": [(p, [p]) for p in packages]})
    gates = {}  # command word -> Event the fake waits for

    def fake_run(command, env):
        # uv's cache layout: unpacked packages in archive-v0/<id>/ (hard-linked into venvs), small index files that
        # point to them elsewhere (wheels-v5/...), and archives of downloads no venv ended up using.
        cache = Path(env["UV_CACHE_DIR"])
        if command[1] == "venv":
            Path(command[-1]).mkdir(parents=True)
        elif command[1] == "pip":
            package = command[-1]
            venv = Path(command[command.index("--python") + 1]).parent
            archive = cache / "archive-v0" / package
            unused = cache / "archive-v0" / f"unused-{package}"
            unused.mkdir(parents=True, exist_ok=True)
            (unused / "x.py").write_bytes(b"z" * 10)
            index = cache / "wheels-v5" / f"{package}.http"
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text(f"archive-v0/{package}")
            if package in gates:
                gates[package].wait(5)
            archive.mkdir(parents=True, exist_ok=True)
            source = archive / f"{package}.py"
            if not source.exists():
                source.write_bytes(package.encode() * 1000)
            os.link(source, venv / f"{package}.py")
        else:  # model weights
            Path(command[0]).parent.joinpath("weights.bin").write_bytes(b"w" * 500)
        yield "ok\n"

    monkeypatch.setattr(models, "_run", fake_run)
    monkeypatch.setattr(models, "_python", lambda name: os.path.join(models.model_dir(name), "venv", "python"))
    yield tmp_path, gates
    models._join_background()


def install(name):
    list(models.install(name))
    models._join_background()  # the clean-up and measuring after it run in the background


def test_two_models_share_cache_files(local):
    tmp_path, _ = local
    install("a")
    install("b")
    shared = Path(models.shared_dir()) / "uv-cache" / "archive-v0" / "torch" / "torch.py"
    assert os.stat(shared).st_nlink == 3
    sizes = models.sizes()
    torch_gb = 5000 / 1e9
    assert sizes["frees"]["a"] == pytest.approx((6000 + 500) / 1e9)  # only-a.py + weights, not torch
    index_files = sum(f.stat().st_size for f in (Path(models.shared_dir()) / "uv-cache" / "wheels-v5").iterdir())
    assert sizes["total_gb"] == pytest.approx((torch_gb * 1e9 + 6000 + 6000 + 1000 + index_files) / 1e9)


def test_remove_keeps_files_another_model_uses(local):
    install("a")
    install("b")
    models.remove("a")
    models._join_background()
    kept = Path(models.model_dir("b")) / "venv" / "torch.py"
    assert kept.read_bytes() == b"torch" * 1000
    assert os.stat(kept).st_nlink == 2
    archives = Path(models.shared_dir()) / "uv-cache" / "archive-v0"
    assert not (archives / "only-a").exists()
    assert not list(archives.glob("unused-*"))


def test_last_remove_deletes_the_shared_folder(local):
    install("a")
    install("b")
    models.remove("a")
    models.remove("b")
    models._join_background()
    assert not os.path.exists(models.shared_dir())


def test_cleanup_waits_for_a_running_install(local):
    _, gates = local
    gates["only-a"] = threading.Event()
    runner = threading.Thread(target=install, args=("a",))
    runner.start()
    archive = Path(models.shared_dir()) / "uv-cache" / "archive-v0" / "unused-only-a" / "x.py"
    for _ in range(100):
        if archive.exists():
            break
        time.sleep(0.02)
    cleaner = threading.Thread(target=models.clean_shared_cache)
    cleaner.start()
    cleaner.join(0.3)
    assert cleaner.is_alive() and archive.exists()  # a fresh download is not deleted before uv links it
    gates["only-a"].set()
    runner.join(5)
    cleaner.join(5)
    assert not cleaner.is_alive()
    assert (Path(models.model_dir("a")) / "venv" / "only-a.py").exists()


def test_second_install_is_refused(local):
    first = models.install("a")
    next(first)
    try:
        assert models.installing() == "a"
        with pytest.raises(RuntimeError, match="Another install is running"):
            install("b")
    finally:
        first.close()
    assert models.installing() is None


def test_unused_archives_are_cleaned_after_install(local):
    install("a")
    archives = Path(models.shared_dir()) / "uv-cache" / "archive-v0"
    assert not list(archives.glob("unused-*"))
    assert (archives / "torch" / "torch.py").exists()


def test_cache_index_files_are_kept(local):
    # uv finds a package it already has through these; deleting them would download PyTorch again for the next model
    install("a")
    assert (Path(models.shared_dir()) / "uv-cache" / "wheels-v5" / "torch.http").exists()


def test_sizes_are_read_from_the_file_without_walking(local, monkeypatch):
    install("a")
    walks = []
    monkeypatch.setattr(models, "_walk_sizes", lambda: walks.append(1) or {"frees": {}, "total_gb": 0})
    models.sizes()
    assert walks == []


def test_install_finishes_before_the_sizes_are_measured(local, monkeypatch):
    # Measuring walks tens of thousands of files (slow on Windows); the install must not wait for it.
    release = threading.Event()
    real = models._walk_sizes
    monkeypatch.setattr(models, "_walk_sizes", lambda: release.wait(5) and real())
    done = threading.Event()
    threading.Thread(target=lambda: (list(models.install("a")), done.set()), daemon=True).start()
    assert done.wait(2), "the install waited for the size measurement"
    assert models.is_installed("a")
    release.set()


def test_sizes_never_walk_in_a_request(local, monkeypatch):
    install("a")
    os.remove(os.path.join(models.LOCAL, "sizes.json"))
    walked = threading.Event()
    real = models._walk_sizes
    monkeypatch.setattr(models, "_walk_sizes", lambda: (walked.wait(5), real())[1])
    assert models.sizes() == {"frees": {}, "total_gb": None}  # unknown for now; measured in the background
    walked.set()
    models._join_background()
    assert "a" in models.sizes()["frees"]
