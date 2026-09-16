"""Phase 7D.5A.2 (Repair 4) — one canonical eligibility decision enforced at every ordinary-model boundary.

A quarantined Silver dataset (or any contradictory / sealed / archived registry state) can never enter selection,
binding, run-authority, execution, or activation; a caller-supplied ``selectable``/``modelEligible`` cannot override
status; a rejected id never silently falls back to the base dataset; and a contradictory registry fails closed at
catalog resolution.
"""
from __future__ import annotations

import json
import uuid

import pytest

from server.sports_cockpit import gen3_authority as A
from tests._hermetic_gen3 import build_hermetic_gen3

ACTOR = "q7d5a2@asp"
SILVER_ID = "silver:src:sha256:" + "a" * 64


def _proj():
    return "q-" + uuid.uuid4().hex[:10]


# ---------------------------------------------------------------- pure canonical decision
@pytest.mark.parametrize("entry", [
    {"datasetVersionId": "d", "status": "QUARANTINED", "quarantine": "QUARANTINED", "modelEligible": False,
     "approvedForTraining": False, "selectable": True},                       # the exact Codex contradictory state
    {"datasetVersionId": "d", "status": "SILVER_NORMALIZED", "selectable": True},
    {"datasetVersionId": "d", "generation": "GEN3_SEALED", "status": "SEALED_OOT_RESTRICTED", "selectable": True},
    {"datasetVersionId": "d", "archived": True, "selectable": True},
    {"datasetVersionId": "d", "modelEligible": False, "selectable": True},
])
def test_contradictory_registry_entry_fails_closed(entry):
    with pytest.raises(A.AuthorityError):
        A.assert_registry_entry_consistent(entry)
    with pytest.raises(A.AuthorityError):
        A.assert_canonical_eligibility(entry)


def test_caller_selectable_true_cannot_override_quarantined_status():
    # status QUARANTINED with a caller-forged selectable=true is a CONTRADICTION, not an authorization
    with pytest.raises(A.AuthorityError):
        A.assert_canonical_eligibility({"datasetVersionId": "d", "status": "QUARANTINED", "selectable": True})


def test_silver_prefixed_id_is_rejected_by_the_decision():
    with pytest.raises(A.AuthorityError):
        A.assert_canonical_eligibility(SILVER_ID)


# ---------------------------------------------------------------- boundary enforcement (no hermetic state needed)
def test_direct_binding_with_a_silver_id_fails_before_resolution():
    with pytest.raises(A.AuthorityError):
        A.create_binding(actor=ACTOR, project_id=_proj(), dataset_version_id=SILVER_ID)


def test_resolve_version_rejects_silver_id_no_fallback_to_base():
    # rejection must NOT silently fall back to the base dataset
    with pytest.raises(A.AuthorityError):
        A._resolve_version(SILVER_ID)


# ---------------------------------------------------------------- hermetic catalog + full-chain enforcement
_HAS_V2 = __import__("tests._runtime_probe", fromlist=["HAS_GEN3_V2"]).HAS_GEN3_V2
pytestmark_hermetic = pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")


@pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")
def test_contradictory_registry_fails_closed_at_catalog(tmp_path, monkeypatch):
    build_hermetic_gen3(tmp_path, monkeypatch)
    reg_path = A.ASP_REGISTRY
    reg = json.loads(reg_path.read_text())
    # inject a forged quarantined+selectable entry into the canonical registry
    reg["datasets"].append({"datasetVersionId": "forged-bad", "status": "QUARANTINED", "quarantine": "QUARANTINED",
                            "selectable": True, "generation": "GEN3"})
    reg_path.write_text(json.dumps(reg))
    with pytest.raises(A.AuthorityError):
        A.catalog()


@pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")
def test_valid_gen3_binding_and_run_still_authorized(tmp_path, monkeypatch):
    # the canonical decision does NOT block a legitimate selectable research dataset
    build_hermetic_gen3(tmp_path, monkeypatch)
    gen3 = {c["generation"]: c["datasetVersionId"] for c in A.catalog()}["GEN3"]
    proj = _proj()
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=gen3)
    au = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"],
                               model_family="governed_hgb", hyperparameters={"maxIter": 10})
    assert au["runAuthorityId"]


@pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")
def test_binding_a_sealed_generation_is_rejected(tmp_path, monkeypatch):
    build_hermetic_gen3(tmp_path, monkeypatch)
    sealed = [e["datasetVersionId"] for e in A.catalog() if e["generation"].endswith("_SEALED")]
    assert sealed
    with pytest.raises(A.AuthorityError):
        A.create_binding(actor=ACTOR, project_id=_proj(), dataset_version_id=sealed[0])
