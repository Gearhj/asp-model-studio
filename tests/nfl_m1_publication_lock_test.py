"""Focused coverage of the shared producer lock; no models or real inputs."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from server.sports_nfl_m1 import prospective_shadow as producer


def test_other_process_keeps_even_an_old_live_lock(tmp_path, monkeypatch):
    lock = tmp_path / "nfl-m1-publication.lock"
    code = """
import sys
from server.sports_cockpit.interprocess_lock import interprocess_lock
with interprocess_lock(sys.argv[1], stale_after=float('inf')):
    print('LOCKED', flush=True)
    sys.stdin.readline()
"""
    child = subprocess.Popen([sys.executable, "-c", code, str(lock)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        metadata = json.loads(lock.read_text())
        metadata["createdAt"] = 0  # Age must not revoke a live publisher.
        lock.write_text(json.dumps(metadata))
        monkeypatch.setattr(producer, "_activate_2026_shadow_unlocked",
                            lambda **kwargs: pytest.fail("contender accessed numerical work"))
        result = producer.activate_2026_shadow(publication_root=tmp_path)
        assert result["status"] == "LOCK_BUSY"
        assert result["forecastsCreated"] == result["forecastInferenceRows"] == 0
        assert json.loads(lock.read_text())["token"] == metadata["token"]
    finally:
        child.communicate("release\n", timeout=10)
    assert child.returncode == 0
    assert not lock.exists()


def test_arguments_and_failure_release_are_preserved(tmp_path, monkeypatch):
    arguments = {"publication_root": tmp_path, "rolling_window_days": 7,
                 "snapshot_types": ("CURRENT",), "producer_revision": "frozen", "dry_run": True}
    def fail(**kwargs):
        assert all(kwargs[key] == value for key, value in arguments.items())
        raise ValueError("existing failure")
    monkeypatch.setattr(producer, "_activate_2026_shadow_unlocked", fail)
    with pytest.raises(ValueError, match="existing failure"):
        producer.activate_2026_shadow(**arguments)
    assert not (tmp_path / "nfl-m1-publication.lock").exists()
    monkeypatch.setattr(producer, "_activate_2026_shadow_unlocked", lambda **kwargs: {"status": "DRY_RUN"})
    result = producer.activate_2026_shadow(**arguments)
    assert result["status"] == "DRY_RUN"
    assert result["publicationLock"]["ownerPid"] == os.getpid()
    assert result["publicationLock"]["liveOwnerAgeExpiry"] is False
