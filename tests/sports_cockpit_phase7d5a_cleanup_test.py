"""Phase 7D.5A (Workstream F) — the incomplete-namespace quarantine utility verifies exactly and fails closed.

Hermetic: builds a fake incomplete namespace under a temp STATE_ROOT and exercises the utility; never touches the
shared .runtime.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from server.sports_cockpit import gen3_authority as A
from scripts import quarantine_incomplete_test_namespace as Q

PID = "test-fake-incomplete"
BID = "b" * 32
RSHA = "a" * 64
AID = "c" * 32


def _make_namespace(state_root, *, complete=False, active=False):
    key = hashlib.sha256(PID.encode()).hexdigest()[:32]
    base = state_root / key
    (base / "bindings").mkdir(parents=True); (base / "bindings" / f"{BID}.json").write_text("{}")
    (base / "authorities").mkdir(parents=True); (base / "authorities" / f"{AID}.json").write_text("{}")
    (base / "requests").mkdir(parents=True); (base / "requests" / f"{RSHA}.json").write_text("{}")
    (base / "active-binding.json").write_text(json.dumps({"bindingId": BID, "revision": 1}))
    if complete:
        (base / "runs").mkdir(parents=True); (base / "runs" / ("0" * 32 + ".json")).write_text('{"status":"COMPLETE"}')
    if active:
        (base / "active-candidate.json").write_text("{}")
    return base


@pytest.fixture()
def state(tmp_path, monkeypatch):
    sr = tmp_path / "state"; sr.mkdir()
    monkeypatch.setattr(A, "STATE_ROOT", sr)
    return sr


def test_verify_and_quarantine_moves_incomplete_namespace(state):
    base = _make_namespace(state)
    out = Q.quarantine(PID, BID, RSHA, AID, "test", apply=False)
    assert out["action"] == "DRY_RUN" and set(out["before"]) >= {"active-binding.json"}
    out2 = Q.quarantine(PID, BID, RSHA, AID, "test", apply=True)
    assert out2["action"] == "QUARANTINED" and out2["afterExists"] is False
    assert not base.exists()                                   # moved out of the authority state root
    dest = base.parents[3] / "quarantine" / "incomplete-test-namespaces"
    moved = list(dest.iterdir())
    assert moved and (moved[0] / "_quarantine-manifest.json").is_file()


def test_refuses_on_identity_mismatch(state):
    _make_namespace(state)
    with pytest.raises(Q.NamespaceCleanupError):
        Q.quarantine(PID, "WRONGBINDING", RSHA, AID, "test", apply=False)


def test_refuses_when_complete_evidence_present(state):
    _make_namespace(state, complete=True)
    with pytest.raises(Q.NamespaceCleanupError):
        Q.quarantine(PID, BID, RSHA, AID, "test", apply=False)


def test_refuses_when_active_candidate_present(state):
    _make_namespace(state, active=True)
    with pytest.raises(Q.NamespaceCleanupError):
        Q.quarantine(PID, BID, RSHA, AID, "test", apply=False)
