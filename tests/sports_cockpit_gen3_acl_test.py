"""Phase 7A.3 — two-user / two-project authorization + path containment + downstream invalidation
(Gates 9/21/22/25). Real persistence + SharingService (no source-string assertions, no shared runtime
ids): each project is a real DB project owned by a distinct user; the Gen-3 authority state root is an
isolated temp dir. Proves cross-project reads/writes are blocked, traversal-shaped project ids cannot
escape the fixed root, and a dataset-binding change invalidates the active candidate.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from server.persistence.db import Database
from server.persistence.service import PersistenceService
from server.core.modeling_scope import authorize_modeling_scope
from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit.gen3_authority import AuthorityError

REPO = Path(__file__).resolve().parents[1]
from tests._runtime_probe import HAS_GEN3_V2 as _HAS_V2  # seam-aware: runs on the seeded isolated authority

USER_A = {"userId": "user-a", "status": "active"}
USER_B = {"userId": "user-b", "status": "active"}
PROJ_A = "acl-project-a"
PROJ_B = "acl-project-b"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "acl.db")); db.initialize()
    svc = PersistenceService(db)
    for pid, owner in ((PROJ_A, "user-a"), (PROJ_B, "user-b")):
        svc.projects.upsert({"project_id": pid, "project_name": pid, "project_type": "predictive-modeling",
                             "owner_user_id": owner})
    # isolated authority root (Gate 25)
    monkeypatch.setattr(A, "STATE_ROOT", tmp_path / "authority")
    # access-denied audit writes to the security store, which refuses non-isolated DBs in tests; the ACL
    # decision itself is what we assert, so the audit side effect is neutralized here.
    with patch("server.persistence.service.get_persistence_service", return_value=svc), \
         patch("server.security.security_store.audit_event", lambda *a, **k: None):
        yield svc


# ---------------- Gate 21: two-user / two-project authorization ----------------
def test_owner_is_authorized_and_non_owner_is_forbidden(env):
    assert authorize_modeling_scope(USER_A, PROJ_A, "edit") == PROJ_A
    assert authorize_modeling_scope(USER_A, PROJ_A, "view") == PROJ_A
    assert authorize_modeling_scope(USER_B, PROJ_B, "edit") == PROJ_B
    # cross-project: A has no permission on B, and B none on A
    for user, other in ((USER_A, PROJ_B), (USER_B, PROJ_A)):
        with pytest.raises(HTTPException) as ei:
            authorize_modeling_scope(user, other, "view")
        assert ei.value.status_code == 403


def test_unknown_and_blank_projects_are_rejected(env):
    with pytest.raises(HTTPException) as ei:
        authorize_modeling_scope(USER_A, "does-not-exist", "view")
    assert ei.value.status_code == 404
    with pytest.raises(HTTPException) as ei:
        authorize_modeling_scope(USER_A, "   ", "view")
    assert ei.value.status_code == 400


@pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")
def test_cross_project_state_is_isolated(env):
    # A (authorized on A) binds Gen-3; B must not see A's binding/runs, and vice versa.
    gen3 = next(c["datasetVersionId"] for c in A.catalog() if c["generation"] == "GEN3")
    pa = authorize_modeling_scope(USER_A, PROJ_A, "edit")
    A.create_binding(actor="user-a", project_id=pa, dataset_version_id=gen3)
    assert A.active_binding(project_id=pa) is not None
    pb = authorize_modeling_scope(USER_B, PROJ_B, "edit")
    assert A.active_binding(project_id=pb) is None            # B has no binding
    # A's opaque storage key differs from B's; neither shares state
    assert A._project_key(PROJ_A) != A._project_key(PROJ_B)


# ---------------- Gate 22: path containment (opaque storage key) ----------------
def test_traversal_shaped_project_ids_cannot_escape_the_fixed_root(env):
    root = A.STATE_ROOT.resolve()
    for evil in ["../../etc/passwd", r"..\..\windows", "C:\\Windows", r"\\server\share", "a/../../b",
                 "con", "with space ", "trailing.", "mixed/..\\x"]:
        key = A._project_key(evil)
        assert all(ch in "0123456789abcdef" for ch in key) and len(key) == 32   # opaque hex, no separators
        p = A._state(evil, "bindings", "x.json").resolve()
        assert root in p.parents                                                  # strictly contained
    # empty project id is rejected outright
    with pytest.raises(AuthorityError):
        A._project_key("")


# ---------------- Gate 9: downstream invalidation on binding change ----------------
@pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")
def test_binding_change_invalidates_active_candidate(env):
    gen2 = next(c["datasetVersionId"] for c in A.catalog() if c["generation"] == "GEN2")
    gen3 = next(c["datasetVersionId"] for c in A.catalog() if c["generation"] == "GEN3")
    pa = authorize_modeling_scope(USER_A, PROJ_A, "edit")
    b = A.create_binding(actor="user-a", project_id=pa, dataset_version_id=gen2)
    au = A.issue_run_authority(actor="user-a", project_id=pa, binding_id=b["bindingId"], model_family="governed_hgb")
    ev = A.execute(actor="user-a", project_id=pa, run_authority_id=au["runAuthorityId"])
    A.activate_candidate(actor="user-a", project_id=pa, run_id=ev["experimentRunId"])
    assert A.get_active_candidate(project_id=pa) is not None
    # changing the dataset binding must clear the active candidate (server-side invalidation)
    A.create_binding(actor="user-a", project_id=pa, dataset_version_id=gen3)
    assert A.get_active_candidate(project_id=pa) is None
    stale = json.loads(A._state(pa, "activations", f"{ev['experimentRunId']}.json").read_text())
    assert stale["status"] == "STALE"
