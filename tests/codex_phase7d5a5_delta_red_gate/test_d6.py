"""D6 delta-red tests: containment must precede every filesystem operation."""
from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from server.sports_cockpit.path_containment import ContainmentError, is_reparse_point
from server.sports_modeling import silver_publish as SP


SIG = "D6_PRE_IO_CONTAINMENT_ORDER:"


def _junction(link: Path, target: Path) -> None:
    if os.name != "nt":
        raise AssertionError("D6_PRE_IO_CONTAINMENT_ORDER requires real Windows junctions")
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert is_reparse_point(link), f"mklink did not create a reparse point: {link}"


def _remove_junction(link: Path) -> None:
    result = subprocess.run(
        ["cmd", "/c", "rmdir", str(link)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _same(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def test_object_root_junction_is_rejected_before_mkdir(tmp_path: Path, monkeypatch) -> None:
    objects_root = tmp_path / "silver" / "objects" / "sha256"
    outside = tmp_path / "outside-object-root"
    _junction(objects_root, outside)
    events: list[str] = []
    original = Path.mkdir

    def mkdir_spy(path: Path, *args, **kwargs):
        if _same(path, objects_root):
            events.append("mkdir")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir_spy)
    try:
        with pytest.raises(ContainmentError):
            SP._atomic_publish_children(
                objects_root,
                objects_root / ("a" * 64),
                {"manifest.json": b"{}"},
                manifest_name="manifest.json",
            )
        assert events == [], f"{SIG} object-root operations occurred before rejection: {events}"
        assert list(outside.iterdir()) == []
    finally:
        _remove_junction(objects_root)


def test_final_object_junction_is_rejected_before_exists(tmp_path: Path, monkeypatch) -> None:
    objects_root = tmp_path / "silver" / "objects" / "sha256"
    objects_root.mkdir(parents=True)
    final = objects_root / ("b" * 64)
    outside = tmp_path / "outside-final-object"
    _junction(final, outside)
    events: list[str] = []
    original = Path.exists

    def exists_spy(path: Path):
        if _same(path, final):
            events.append("exists")
        return original(path)

    monkeypatch.setattr(Path, "exists", exists_spy)
    try:
        with pytest.raises(ContainmentError):
            SP._atomic_publish_children(
                objects_root,
                final,
                {"manifest.json": b"{}"},
                manifest_name="manifest.json",
            )
        assert events == [], f"{SIG} final-object operations occurred before rejection: {events}"
        assert list(outside.iterdir()) == []
    finally:
        _remove_junction(final)


def test_registry_parent_junction_is_rejected_before_mkdir(tmp_path: Path, monkeypatch) -> None:
    silver_root = tmp_path / "silver-root"
    outside = tmp_path / "outside-registry-parent"
    _junction(silver_root, outside)
    events: list[str] = []
    original = Path.mkdir

    def mkdir_spy(path: Path, *args, **kwargs):
        if _same(path, silver_root):
            events.append("mkdir")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir_spy)
    try:
        with pytest.raises(ContainmentError):
            SP._register(silver_root, "source-v1", "c" * 64, "d" * 64, 1, [2024])
        assert events == [], f"{SIG} registry-parent operations occurred before rejection: {events}"
        assert list(outside.iterdir()) == []
    finally:
        _remove_junction(silver_root)


def test_registry_path_is_rejected_before_exists_or_read(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "registry-root"
    root.mkdir()
    registry_path = root / "registry.json"
    outside = tmp_path / "outside-registry-path"
    _junction(registry_path, outside)
    lock_path = root / ".registry.lock"
    events: list[str] = []
    original_lock = SP.interprocess_lock
    original_is_file = Path.is_file
    original_read_text = Path.read_text

    @contextmanager
    def lock_spy(*args, **kwargs):
        events.append("lock-file creation")
        with original_lock(*args, **kwargs):
            yield

    def is_file_spy(path: Path):
        if _same(path, registry_path):
            events.append("exists")
        return original_is_file(path)

    def read_text_spy(path: Path, *args, **kwargs):
        if _same(path, registry_path):
            events.append("read")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(SP, "interprocess_lock", lock_spy)
    monkeypatch.setattr(Path, "is_file", is_file_spy)
    monkeypatch.setattr(Path, "read_text", read_text_spy)
    try:
        with pytest.raises(ContainmentError):
            SP._locked_registry_put(
                registry_path,
                lock_path,
                root,
                "DELTA_REGISTRY_V1",
                "key",
                {"value": 1},
            )
        assert events == [], f"{SIG} registry-path operations occurred before rejection: {events}"
        assert list(outside.iterdir()) == []
    finally:
        _remove_junction(registry_path)


def test_lock_parent_is_rejected_before_lock_file_creation(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "registry-root"
    root.mkdir()
    lock_parent = root / "locks"
    outside = tmp_path / "outside-lock-parent"
    _junction(lock_parent, outside)
    events: list[str] = []
    original_lock = SP.interprocess_lock

    @contextmanager
    def lock_spy(*args, **kwargs):
        events.append("lock-file creation")
        with original_lock(*args, **kwargs):
            yield

    monkeypatch.setattr(SP, "interprocess_lock", lock_spy)
    try:
        with pytest.raises(ContainmentError):
            SP._locked_registry_put(
                root / "registry.json",
                lock_parent / ".registry.lock",
                root,
                "DELTA_REGISTRY_V1",
                "key",
                {"value": 1},
            )
        assert events == [], f"{SIG} lock operation occurred before containment: {events}"
        assert list(outside.iterdir()) == []
    finally:
        _remove_junction(lock_parent)
