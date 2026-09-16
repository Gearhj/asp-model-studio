"""Synthetic recovery process guards; no sports data or estimator fits."""
import json
from types import SimpleNamespace

import pytest

from scripts import recover_mlb_corrected_hgb as recovery


def _worker_environment(monkeypatch, tmp_path, processes, active=()):
    monkeypatch.setattr(recovery.lab, "_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(recovery.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=json.dumps(processes)))
    monkeypatch.setattr(recovery.jobs, "list_model_development_jobs", lambda *a: {"jobs": list(active)})


def test_worker_guard_accepts_absent_failed_threads_without_killing(monkeypatch, tmp_path):
    _worker_environment(monkeypatch, tmp_path, [{"ProcessId": 42, "ParentProcessId": 1, "Name": "python.exe"}])
    result = recovery.verify_workers(None)
    assert result["status"] == "NO_FAILED_ATTEMPT_WORKERS_ACTIVE"
    assert result["processesTerminated"] == result["locksRemoved"] == 0


@pytest.mark.parametrize("processes", [
    [{"ProcessId": 61036, "ParentProcessId": 1, "Name": "python.exe"}],
    [{"ProcessId": 72, "ParentProcessId": 61036, "Name": "python.exe"}],
    [{"ProcessId": 72, "ParentProcessId": 61036, "Name": "python.exe"}, {"ProcessId": 73, "ParentProcessId": 72, "Name": "python.exe"}],
])
def test_worker_guard_rejects_failed_coordinator_or_descendants(monkeypatch, tmp_path, processes):
    _worker_environment(monkeypatch, tmp_path, processes)
    with pytest.raises(RuntimeError, match="RECOVERY_WORKERS_NOT_CLEAR"):
        recovery.verify_workers(None)


def test_worker_guard_rejects_active_project_job(monkeypatch, tmp_path):
    _worker_environment(monkeypatch, tmp_path, [], [{"jobId": "active", "status": "RUNNING"}])
    with pytest.raises(RuntimeError, match="RECOVERY_WORKERS_NOT_CLEAR"):
        recovery.verify_workers(None)


def test_worker_guard_never_reclaims_existing_lock(monkeypatch, tmp_path):
    _worker_environment(monkeypatch, tmp_path, [])
    lock = tmp_path / "locks" / f"{recovery.PROJECT_ID}.model-development.lock"
    lock.parent.mkdir()
    lock.write_text('{"pid":61036}', encoding="utf8")
    with pytest.raises(RuntimeError, match="RECOVERY_WORKERS_NOT_CLEAR"):
        recovery.verify_workers(None)
    assert lock.read_text(encoding="utf8") == '{"pid":61036}'


def test_recovery_does_not_reuse_failed_identity():
    assert recovery.RECOVERY_FOLDER != "corrected-hgb-study"
    assert recovery.RECOVERY_BATCH != recovery.original.BATCH_NAME
    assert recovery.FAILED_STUDY == "94ce59613407da613b40c1fb7357e148b1053fc064977eeec6efb32acea7e4d0"
