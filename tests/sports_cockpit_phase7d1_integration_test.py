"""Phase 7D.1 negative behavioral matrices for the final integration gates.

Covers (hermetically, each test in its OWN opaque project / temp registry — never mutating the shared
canonical registry): Gate 1 fail-closed registry (missing/malformed/schema/duplicate, no sidecar fallback),
Gate 2 deterministic byte-idempotent locked migration, Gate 3 verified research handle, Gate 5 no warm-cache
early return, Gate 13 strict control-plus-one-family ablation identity, Gate 18 TOCTOU-safe estimator reload
+ independent recompute, Gate 23 interprocess execution lock, Gate 24 binding same-version no-op / new-
revision. Heavy fits reuse one module governed-HGB run.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit.gen3_authority import AuthorityError, BusyError, StaleAuthorityError
from server.sports_cockpit.interprocess_lock import LockBusy, interprocess_lock

REPO = Path(__file__).resolve().parents[1]
from tests._runtime_probe import HAS_GEN3_V2 as _HAS_V2  # seam-aware: runs on the seeded isolated authority
pytestmark = pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")
ACTOR = "pytest-7d1@asp"


def _proj() -> str:
    return "test-7d1-" + uuid.uuid4().hex[:12]


def _gen3_dsid() -> str:
    return {c["generation"]: c["datasetVersionId"] for c in A.catalog()}["GEN3"]


# ============================================================ Gate 1 — fail-closed sole resolver
@pytest.fixture
def temp_registry(tmp_path, monkeypatch):
    """Point ASP_REGISTRY at a temp copy of the real registry so registry-shape tests never touch the
    shared canonical registry."""
    dst = tmp_path / "registry.json"
    if A.ASP_REGISTRY.is_file():
        dst.write_bytes(A.ASP_REGISTRY.read_bytes())
    monkeypatch.setattr(A, "ASP_REGISTRY", dst)
    return dst


def test_missing_registry_fails_closed_no_sidecar_fallback(temp_registry):
    temp_registry.unlink(missing_ok=True)
    with pytest.raises(AuthorityError):
        A.catalog()  # must NOT reconstruct an executable catalog from the publisher sidecars


def test_malformed_registry_fails_closed(temp_registry):
    temp_registry.write_text("{ this is not valid json ", encoding="utf-8")
    with pytest.raises(AuthorityError):
        A.catalog()


def test_wrong_schema_version_fails_closed(temp_registry):
    reg = json.loads(temp_registry.read_text())
    reg["schemaVersion"] = "ASP_DATASET_REGISTRY_V2"
    temp_registry.write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(AuthorityError):
        A.catalog()


def test_duplicate_dataset_ids_fail_closed(temp_registry):
    reg = json.loads(temp_registry.read_text())
    reg["datasets"].append(dict(reg["datasets"][0]))  # duplicate a version id
    temp_registry.write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(AuthorityError):
        A.catalog()


def test_duplicate_live_content_addresses_fail_closed(temp_registry):
    reg = json.loads(temp_registry.read_text())
    live = [d for d in reg["datasets"] if d.get("selectable") and not d.get("archived")]
    clash = dict(live[0]); clash["datasetVersionId"] = live[0]["datasetVersionId"] + ":dup"
    clash["logicalContentSha256"] = live[1]["logicalContentSha256"]  # collide the live content address
    reg["datasets"].append(clash)
    temp_registry.write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(AuthorityError):
        A.catalog()


def test_sealed_generation_marked_selectable_fails_closed(temp_registry):
    reg = json.loads(temp_registry.read_text())
    for d in reg["datasets"]:
        if str(d.get("generation", "")).endswith("_SEALED"):
            d["selectable"] = True
    temp_registry.write_text(json.dumps(reg), encoding="utf-8")
    with pytest.raises(AuthorityError):
        A.catalog()


# ============================================================ Gate 2 — deterministic idempotent migration
def test_migration_is_byte_idempotent(temp_registry):
    first = A.migrate_registry()
    bytes_after_first = temp_registry.read_bytes()
    second = A.migrate_registry()
    assert first["migrationId"] == second["migrationId"]      # deterministic id for the same end-state
    assert second["noop"] is True                             # exact rerun is a no-op
    assert temp_registry.read_bytes() == bytes_after_first    # file bytes unchanged


def test_migration_never_writes_before_or_timestamp(temp_registry):
    A.migrate_registry()
    reg = json.loads(temp_registry.read_text())
    assert set(reg.keys()) == {"schemaVersion", "migrationId", "datasets"}  # no volatile fields in the registry


def test_concurrent_migrations_do_not_diverge(temp_registry):
    ids = []
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        ids.append(A.migrate_registry()["migrationId"])

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(ids)) == 1                                 # every migration agreed on one end-state
    A._validate_registry_consistency(json.loads(temp_registry.read_text()))  # still valid


# ============================================================ Gate 3 — verified research handle
def test_verified_research_object_handle(temp_registry):
    A.migrate_registry()
    h = A.verified_research_object("GEN2")
    assert h["schemaVersion"] == "VERIFIED_RESEARCH_OBJECT_V1" and h["capability"] == "RESEARCH_OBJECT_READ"
    assert h["path"].is_file()
    for k in ("physicalParquetSha256", "logicalContentSha256", "schemaSha256", "contractBundleSha256",
              "canonicalObjectId", "orderedFeatures", "targetClassOrder"):
        assert h[k]
    assert 2025 not in (h["seasons"] or [])                   # no sealed season resident in a research object


def test_verified_handle_generation_specific_contracts(temp_registry):
    A.migrate_registry()
    g2 = A.verified_research_object("GEN2")
    g3 = A.verified_research_object("GEN3")
    assert "GEN2" in g2["contracts"]["target"] and "GEN3" in g3["contracts"]["target"]
    assert g2["logicalContentSha256"] != g3["logicalContentSha256"]


# ============================================================ Gate 5 — no warm verification cache
def test_verification_cache_is_retired(temp_registry):
    A.migrate_registry()
    A.verified_research_object("GEN2")
    assert A._VERIFIED_OBJECT_CACHE == {}                     # nothing is cached across governed reads


# ============================================================ Gate 13 — strict control+one-family identity
def test_strict_control_plus_one_family_accepts_prefix_plus_family():
    control = ["a", "b", "c"]
    challenger = ["a", "b", "c", "fam1", "fam2"]
    assert A._assert_strict_control_plus_one_family(control, challenger) == ["fam1", "fam2"]


@pytest.mark.parametrize("challenger, why", [
    (["a", "b"], "one-feature challenger replacing control (removed c)"),
    (["a", "c", "b", "fam1"], "reordered control"),
    (["a", "b", "x", "fam1"], "substituted control feature c->x"),
    (["a", "b", "c"], "empty added family"),
    (["a", "b", "c", "a"], "duplicate feature"),
    (["a", "b", "c", "b"], "added family duplicates a control feature"),
    (["x", "a", "b", "c", "fam1"], "prefix is not the control set"),
])
def test_strict_control_plus_one_family_rejections(challenger, why):
    control = ["a", "b", "c"]
    with pytest.raises(AuthorityError):
        A._assert_strict_control_plus_one_family(control, challenger)


# ============================================================ Gate 24 — binding same-version no-op / CAS
def test_same_version_binding_is_noop():
    proj, dsid = _proj(), _gen3_dsid()
    b1 = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=dsid)
    b2 = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=dsid)  # re-select same version
    assert b1["bindingId"] == b2["bindingId"] and b1["revision"] == b2["revision"]


def test_revision_reason_forces_new_revision():
    proj, dsid = _proj(), _gen3_dsid()
    b1 = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=dsid)
    b2 = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=dsid, revision_reason="explicit re-bind")
    assert b2["revision"] == b1["revision"] + 1


def test_binding_cas_conflict_rejected():
    proj, dsid = _proj(), _gen3_dsid()
    A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=dsid)  # revision 1
    with pytest.raises(StaleAuthorityError):
        A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=dsid, expected_revision=99)


# ============================================================ Gate 23 — interprocess execution lock
def test_execute_refuses_when_project_lock_is_held():
    proj, dsid = _proj(), _gen3_dsid()
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=dsid)
    au = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb")
    # plant a live foreign lock at the project's exec lock path -> a second heavy run is refused with BUSY
    lock_path = A._project_exec_lock_path(proj)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps({"pid": os.getpid(), "token": "foreign", "createdAt": time.time()}))
    try:
        with pytest.raises(BusyError):
            A.execute(actor=ACTOR, project_id=proj, run_authority_id=au["runAuthorityId"])
    finally:
        lock_path.unlink(missing_ok=True)


def test_interprocess_lock_is_same_thread_reentrant(tmp_path):
    lp = tmp_path / "exec.lock"
    with interprocess_lock(lp):
        with interprocess_lock(lp):           # same thread -> reentrant, no deadlock
            assert lp.is_file()
    assert not lp.is_file()

    result = {}

    def other():
        try:
            with interprocess_lock(lp, blocking=False):
                result["v"] = "acquired"
        except LockBusy:
            result["v"] = "busy"

    with interprocess_lock(lp):
        t = threading.Thread(target=other); t.start(); t.join()
    assert result["v"] == "busy"              # a different thread is excluded


# ============================================================ Gate 18 — TOCTOU-safe reload + recompute
@pytest.fixture(scope="module")
def hgb_run():
    proj, dsid = _proj(), {c["generation"]: c["datasetVersionId"] for c in A.catalog()}["GEN3"]
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=dsid)
    au = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb")
    ev = A.execute(actor=ACTOR, project_id=proj, run_authority_id=au["runAuthorityId"])
    return {"proj": proj, "runId": ev["experimentRunId"]}


def test_estimator_reload_returns_recorded_class(hgb_run):
    est = A.load_fitted_estimator(project_id=hgb_run["proj"], run_id=hgb_run["runId"])
    assert type(est).__name__ == "HistGradientBoostingClassifier"


def test_estimator_reload_fails_closed_on_byte_substitution(hgb_run):
    proj, run_id = hgb_run["proj"], hgb_run["runId"]
    est_path = A._state(proj, "evidence", run_id, "estimator.joblib")
    original = est_path.read_bytes()
    try:
        est_path.write_bytes(original + b"\x00tamper")   # same-file byte substitution
        with pytest.raises(AuthorityError):
            A.load_fitted_estimator(project_id=proj, run_id=run_id)
    finally:
        est_path.write_bytes(original)                    # restore the immutable bundle bytes


def test_verify_estimator_reload_recomputes_predictions(hgb_run):
    out = A.verify_estimator_reload(project_id=hgb_run["proj"], run_id=hgb_run["runId"])
    assert out["modelFamily"] == "governed_hgb" and out["validationRows"] > 0
    assert out["bitForBitMatch"] is True or (out["maxAbsProbabilityDiff"] is not None
                                             and out["maxAbsProbabilityDiff"] < 1e-9)


# ============================================================ Gate 21 — strict model request schemas
def test_logistic_rejects_any_hyperparameter():
    with pytest.raises(AuthorityError):
        A._validate_hyperparameters("governed_logistic", {"C": 0.1})   # NOT silently ignored


def test_logistic_accepts_empty_and_returns_fixed_policy():
    eff = A._validate_hyperparameters("governed_logistic", {})
    assert eff["penalty"] == "l2" and eff["maxIter"] and eff["cGrid"]


@pytest.mark.parametrize("hyper", [
    {"maxIter": 200.5},              # fractional int (no int() truncation)
    {"maxIter": True},               # bool masquerading as int
    {"maxIter": 10 ** 9},            # huge
    {"maxIter": 5},                  # below range
    {"learningRate": float("nan")},  # NaN
    {"learningRate": float("inf")},  # Inf
    {"learningRate": 0.0},           # not > 0
    {"learningRate": 2.0},           # above range
    {"maxDepth": 0},                 # below range
    {"maxDepth": 99},                # above range
    {"maxDepth": 3.5},               # fractional
    {"unknownKey": 1},               # unknown hyperparameter
])
def test_hgb_strict_rejections(hyper):
    with pytest.raises(AuthorityError):
        A._validate_hyperparameters("governed_hgb", hyper)


def test_hgb_accepts_valid_and_does_not_truncate():
    eff = A._validate_hyperparameters("governed_hgb", {"maxIter": 150, "learningRate": 0.05, "maxDepth": 4})
    assert eff["maxIter"] == 150 and eff["learningRate"] == 0.05 and eff["maxDepth"] == 4


def test_unsupported_family_rejected():
    with pytest.raises(AuthorityError):
        A._validate_hyperparameters("random_forest", {})


# ============================================================ Gate 11 — Phase 7B research entry point
def test_phase7b_research_entry_point_is_research_only(temp_registry):
    A.migrate_registry()
    from scripts import phase7b_research as P
    summ = P._research_summary("GEN2")
    assert summ["entryPoint"] == "PHASE_7B_RESEARCH_V1" and summ["capability"] == "RESEARCH_OBJECT_READ"
    assert summ["verificationState"] == "VERIFIED"
    assert 2025 not in summ["seasons"] and 2026 not in summ["seasons"]
    assert "Bronze normalization and feature creation are NOT enabled" in summ["note"]


def test_phase7b_research_refuses_sealed_or_unknown_generation():
    from scripts import phase7b_research as P
    for bad in ("GEN3_SEALED", "GEN2_SEALED", "bogus"):
        with pytest.raises(SystemExit):
            P._research_summary(bad)
