"""Phase 7D.4 Gate 14 — TRUE interprocess concurrency (separate OS processes, isolated temp roots).

Uses real subprocesses (not threads pretending to be processes) contending on the SAME isolated runtime root
(via the ASP_MODEL_STUDIO_RUNTIME_ROOT env seam). Proves the create-once + interprocess-lock contracts under
genuine cross-process contention: a held lock excludes a second process; a dead owner's lock is reclaimed; the
evidence-registry mapping is create-once (idempotent for identical content, hard-conflict for divergent); the
canonical registry migration is idempotent across processes; the per-project exec lock serializes governed runs
across processes; and a completed immutable object stays verifiable with no partial/staging directory left behind.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit.interprocess_lock import LockBusy, interprocess_lock
from tests._hermetic_gen3 import build_hermetic_gen3

REPO = Path(__file__).resolve().parents[1]
_HEX = "a" * 64
_HEX2 = "b" * 64


def _env(tmp: Path) -> dict:
    return {**os.environ, "PYTHONPATH": str(REPO), "ASP_MODEL_STUDIO_RUNTIME_ROOT": str(tmp)}


def _popen(args, env):
    return subprocess.Popen([sys.executable, "-m", "tests._interprocess_worker", *args], cwd=str(REPO),
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _wait_token(proc, token, timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line == "":                       # EOF (process exited)
            return False
        if token in line:
            return True
    return False


def _run(args, env, timeout=90):
    return subprocess.run([sys.executable, "-m", "tests._interprocess_worker", *args], cwd=str(REPO),
                          env=env, capture_output=True, text=True, timeout=timeout)


# ---------------- 1/5. a held lock excludes a second process ----------------
def test_held_lock_excludes_a_second_process(tmp_path):
    # DETERMINISTIC protocol: the holder acquires and blocks on a RELEASE sentinel (no timing race). The contender is
    # attempted while the holder is provably still holding; only after that does the parent signal RELEASE.
    env = _env(tmp_path)
    lock = str(tmp_path / "exclusive.lock")
    release = tmp_path / "release.signal"
    holder = _popen(["holdlock", lock, str(release)], env)
    try:
        assert _wait_token(holder, "ACQUIRED"), "holder never acquired"
        busy = _run(["trylock", lock], env)          # a second PROCESS is excluded while the holder blocks on RELEASE
        assert busy.stdout.strip() == "BUSY", busy.stdout + busy.stderr
    finally:
        release.write_text("go", encoding="utf-8")   # deterministically release the holder
        holder.wait(timeout=20)
    free = _run(["trylock", lock], env)              # released after the holder exits
    assert free.stdout.strip() == "ACQUIRED"


# ---------------- 6. a dead owner's lock is reclaimed ----------------
def test_lock_reclaimed_after_owner_process_dies(tmp_path):
    env = _env(tmp_path)
    lock = str(tmp_path / "reclaim.lock")
    holder = _popen(["holdlock", lock, str(tmp_path / "never.signal")], env)  # holds (blocked on RELEASE) until killed
    assert _wait_token(holder, "ACQUIRED"), "holder never acquired"
    holder.kill(); holder.wait(timeout=20)           # owner dies while holding the lock
    time.sleep(0.3)
    with interprocess_lock(lock, blocking=False):    # reclaimed (dead owner pid) — no LockBusy
        pass


# ---------------- 3/4. evidence-registry create-once across processes ----------------
def test_evidence_registry_create_once_conflict_across_processes(tmp_path):
    env = _env(tmp_path)
    proj = "ip-evreg"
    a = _popen(["evput", proj, "run-A", _HEX], env)
    b = _popen(["evput", proj, "run-A", _HEX2], env)   # SAME run id, DIFFERENT receipt sha
    outs = sorted([a.communicate(timeout=30)[0].strip(), b.communicate(timeout=30)[0].strip()])
    assert outs == ["CONFLICT", "OK"], outs           # exactly one wins; the divergent write fails closed
    # the surviving mapping is intact + valid
    reg = json.loads((tmp_path / "sports-modeling/mlb-pa-gen3-v2/authority").rglob("registry.json").__next__().read_text())
    assert reg["schemaVersion"] == A.EVIDENCE_REGISTRY_V1 and reg["runs"]["run-A"] in (_HEX, _HEX2)


def test_evidence_registry_idempotent_for_identical_content_across_processes(tmp_path):
    env = _env(tmp_path)
    proj = "ip-evreg-idem"
    a = _popen(["evput", proj, "run-B", _HEX], env)
    b = _popen(["evput", proj, "run-B", _HEX], env)    # SAME run id, SAME sha -> both idempotent OK
    outs = sorted([a.communicate(timeout=30)[0].strip(), b.communicate(timeout=30)[0].strip()])
    assert outs == ["OK", "OK"], outs


# ---------------- 1/7. registry migration idempotent across processes ----------------
def test_registry_migration_idempotent_across_processes(tmp_path, monkeypatch):
    build_hermetic_gen3(tmp_path, monkeypatch, migrate=False)     # sidecars only; NOT yet migrated
    env = _env(tmp_path)
    a = _popen(["migrate"], env)
    b = _popen(["migrate"], env)
    oa = a.communicate(timeout=60)[0].strip(); ob = b.communicate(timeout=60)[0].strip()
    assert oa.startswith("MIGRATED ") and ob.startswith("MIGRATED ")
    assert oa.split()[1] == ob.split()[1]                         # deterministic, identical migration id
    cat = A.catalog()                                            # registry is valid + the object still verifies
    A._verify_object(next(e for e in cat if e["generation"] == "GEN3"))


# ---------------- 2/5/7. per-project exec lock serializes governed runs across processes ----------------
def test_project_exec_lock_serializes_runs_across_processes(tmp_path, monkeypatch):
    h = build_hermetic_gen3(tmp_path, monkeypatch)
    env = _env(tmp_path)
    proj = "ip-exec"
    release = tmp_path / "exec-release.signal"
    holder = _popen(["holdexec", proj, str(release)], env)       # hold the project's exec lock, blocked on RELEASE
    try:
        assert _wait_token(holder, "ACQUIRED"), "holder never acquired the exec lock"
        contender = _run(["execute", proj, h["researchId"]], env)   # a governed run in ANOTHER process is refused
        assert contender.stdout.strip() == "BUSY", contender.stdout + contender.stderr
    finally:
        release.write_text("go", encoding="utf-8")               # deterministically release the holder
        holder.wait(timeout=30)
    # after contention: a governed run completes and its immutable object stays verifiable; no partial/staging dir
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=h["researchId"])
    au = A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"],
                               model_family="governed_hgb", hyperparameters={"maxIter": 15})
    ev = A.execute(actor="t@asp", project_id=proj, run_authority_id=au["runAuthorityId"])
    v = A.verify_canonical_model_run_chain(project_id=proj, run_id=ev["experimentRunId"], require_current_binding=True)
    assert v["receiptSha256"]
    assert list(A.STATE_ROOT.rglob(".staging-*")) == []          # atomic publish left no partial object
