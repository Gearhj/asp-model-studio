"""Phase 7D.3 — MODEL_RUN_EVIDENCE_BUNDLE_V2 / run-receipt / evidence-registry / activation matrices.

Hermetic (each in its own opaque project; one governed HGB run is reused via a module fixture with
tamper+restore). Covers Gate 13 (atomic publication + child/manifest/receipt/path tamper), Gate 14
(activation status matrix), and Gate 18 (evidence-registry concurrency/idempotency). No sealed data opened.
"""
from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit.gen3_authority import AuthorityError, StaleAuthorityError

REPO = Path(__file__).resolve().parents[1]
_HAS_V2 = (REPO / ".runtime/asp-model-studio/sports-modeling/mlb-pa-gen3-v2/registration.json").is_file()
pytestmark = pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")
ACTOR = "pytest-7d3@asp"


def _proj() -> str:
    return "test-7d3-" + uuid.uuid4().hex[:12]


def _gen3() -> str:
    return {c["generation"]: c["datasetVersionId"] for c in A.catalog()}["GEN3"]


@contextmanager
def _tamper(path: Path, new_bytes: bytes | None = None):
    orig = path.read_bytes()
    try:
        path.write_bytes(new_bytes if new_bytes is not None else orig + b"\x00tamper")
        yield
    finally:
        path.write_bytes(orig)


@contextmanager
def _renamed_away(path: Path):
    tmp = path.with_suffix(path.suffix + ".away")
    path.rename(tmp)
    try:
        yield
    finally:
        tmp.rename(path)


@pytest.fixture(scope="module")
def run_v2():
    proj = _proj()
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=_gen3())
    au = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"],
                               model_family="governed_hgb", hyperparameters={"maxIter": 40})
    ev = A.execute(actor=ACTOR, project_id=proj, run_authority_id=au["runAuthorityId"])
    rid = ev["experimentRunId"]
    v = A.verify_model_run_receipt(project_id=proj, run_id=rid)
    return {"proj": proj, "binding": b, "runId": rid, "receiptSha": v["receiptSha256"],
            "bundleSha": v["receipt"]["bundleManifestSha256"], "bundleDir": v["bundleDir"],
            "receiptFile": A._v2_receipt_dir(proj, v["receiptSha256"]) / "receipt.json"}


# ============================================================ Gate 13-A — atomic publication
def test_valid_v2_bundle_verifies_and_reload_reproduces(run_v2):
    v = A.verify_model_run_receipt(project_id=run_v2["proj"], run_id=run_v2["runId"])
    assert v["manifest"]["status"] == "COMPLETE" and len(v["manifest"]["children"]) == 29
    r = A.verify_estimator_reload_v2(project_id=run_v2["proj"], run_id=run_v2["runId"])
    assert r["bitForBitMatch"] is True and r["maxAbsProbabilityDiff"] == 0.0


def test_missing_mandatory_child_fails_closed(run_v2):
    child = run_v2["bundleDir"] / "aggregate-metrics.json"
    with _renamed_away(child):
        with pytest.raises(AuthorityError):
            A.verify_model_run_receipt(project_id=run_v2["proj"], run_id=run_v2["runId"])


def test_extra_prohibited_child_fails_closed(run_v2):
    extra = run_v2["bundleDir"] / "evil-extra.json"
    extra.write_bytes(b"{}")
    try:
        with pytest.raises(AuthorityError):
            A.verify_model_run_receipt(project_id=run_v2["proj"], run_id=run_v2["runId"])
    finally:
        extra.unlink(missing_ok=True)


# ============================================================ Gate 13-B — child tamper
@pytest.mark.parametrize("child", [
    "model.artifact", "preprocessor.artifact", "validation-probabilities.f64", "validation-target.json",
    "validation-row-ids.json", "aggregate-metrics.json", "per-class-metrics.json", "confusion-matrix.json",
    "reliability-diagnostics.json", "feature-set-contract.json", "feature-semantic-contracts.json",
    "model-request-receipt.json", "verified-object-receipt.json", "run-authority.json",
    "model-metadata.json", "code-environment-receipt.json", "child-sha-inventory.json",
])
def test_child_tamper_fails_closed(run_v2, child):
    with _tamper(run_v2["bundleDir"] / child):
        with pytest.raises(AuthorityError):
            A.verify_model_run_receipt(project_id=run_v2["proj"], run_id=run_v2["runId"])


# ============================================================ Gate 13-C — manifest / receipt / index tamper
def test_manifest_tamper_fails_closed(run_v2):
    with _tamper(run_v2["bundleDir"] / "bundle-manifest.json"):
        with pytest.raises(AuthorityError):
            A.verify_model_run_receipt(project_id=run_v2["proj"], run_id=run_v2["runId"])


def test_receipt_tamper_fails_closed(run_v2):
    with _tamper(run_v2["receiptFile"]):
        with pytest.raises(AuthorityError):
            A.verify_model_run_receipt(project_id=run_v2["proj"], run_id=run_v2["runId"])


def test_registry_index_tamper_fails_closed(run_v2):
    reg_path = A._evidence_registry_path(run_v2["proj"])
    reg = json.loads(reg_path.read_text())
    tampered = json.loads(reg_path.read_text())
    tampered["runs"][run_v2["runId"]] = "de" * 32   # point run id at a non-existent receipt sha
    with _tamper(reg_path, json.dumps(tampered).encode()):
        with pytest.raises(AuthorityError):
            A.verify_model_run_receipt(project_id=run_v2["proj"], run_id=run_v2["runId"])
    assert json.loads(reg_path.read_text()) == reg   # restored


def test_coordinated_child_and_manifest_tamper_fails_closed(run_v2):
    # tamper a child AND rewrite the manifest's recorded sha for it: the manifest bytes change, so the manifest
    # no longer matches its content-address -> fail closed (content-addressing defeats coordinated tamper)
    bdir = run_v2["bundleDir"]
    man_path = bdir / "bundle-manifest.json"
    child_path = bdir / "aggregate-metrics.json"
    man = json.loads(man_path.read_text()); orig_child = child_path.read_bytes(); orig_man = man_path.read_bytes()
    try:
        new_child = orig_child[:-1] + b" "  # keep valid json-ish bytes; different content
        child_path.write_bytes(new_child)
        import hashlib
        man["children"]["aggregate-metrics.json"]["sha256"] = hashlib.sha256(new_child).hexdigest()
        man_path.write_text(json.dumps(man))
        with pytest.raises(AuthorityError):
            A.verify_model_run_receipt(project_id=run_v2["proj"], run_id=run_v2["runId"])
    finally:
        child_path.write_bytes(orig_child); man_path.write_bytes(orig_man)


def test_v2_child_name_guard_rejects_unsafe_names():
    # the fixed child-name guard (Gate 7) rejects traversal / absolute / drive / mixed-separator / uppercase
    # names; every mandatory child + the manifest is an allowed lowercase safe name. (Any in-place manifest
    # tamper that injects such a name is ALSO caught earlier by the manifest content-address check.)
    for bad in ["../evil", "..\\evil", "/abs", "C:evil", "a/b", "a\\b", "spaces bad", "UPPER.json", ".hidden"]:
        assert not A._V2_SAFE_NAME.match(bad)
    for good in list(A._V2_MANDATORY_CHILDREN) + [A._V2_MANIFEST_NAME]:
        assert A._V2_SAFE_NAME.match(good), good


# ============================================================ Gate 14 — activation status matrix
def test_complete_run_activates_and_reverifies(run_v2):
    act = A.activate_candidate(actor=ACTOR, project_id=run_v2["proj"], run_id=run_v2["runId"],
                               expected_binding_revision=run_v2["binding"]["revision"])
    assert act["schemaVersion"] == "ACTIVE_CANDIDATE_REVIEW_V2" and act["experimentRunId"] == run_v2["runId"]
    dc = A.get_active_candidate(project_id=run_v2["proj"])
    assert dc["run"]["runAuthorityId"] == act["runAuthorityId"]
    ev = A.active_candidate_evaluation(project_id=run_v2["proj"])
    assert ev["recomputationMatchesStored"] is True and "frozen2025" not in json.dumps(ev)


def test_fabricated_run_rejected(run_v2):
    with pytest.raises(AuthorityError):
        A.activate_candidate(actor=ACTOR, project_id=run_v2["proj"], run_id="ff" * 16)


def test_non_complete_receipt_status_rejected(run_v2):
    r = json.loads(run_v2["receiptFile"].read_text())
    r["status"] = "RUNNING"  # any non-COMPLETE status (also breaks the receipt sha -> double fail-closed)
    with _tamper(run_v2["receiptFile"], json.dumps(r).encode()):
        with pytest.raises(AuthorityError):
            A.activate_candidate(actor=ACTOR, project_id=run_v2["proj"], run_id=run_v2["runId"])


def test_missing_bundle_rejected(run_v2):
    with _renamed_away(run_v2["bundleDir"] / "bundle-manifest.json"):
        with pytest.raises(AuthorityError):
            A.activate_candidate(actor=ACTOR, project_id=run_v2["proj"], run_id=run_v2["runId"])


@pytest.mark.parametrize("child", ["model-metadata.json", "aggregate-metrics.json", "feature-set-contract.json",
                                   "model-request-receipt.json"])
def test_tampered_bundle_child_rejected_at_activation(run_v2, child):
    with _tamper(run_v2["bundleDir"] / child):
        with pytest.raises(AuthorityError):
            A.activate_candidate(actor=ACTOR, project_id=run_v2["proj"], run_id=run_v2["runId"])


def test_stale_and_cross_project_rejected(run_v2):
    proj = run_v2["proj"]
    # wrong expected binding revision -> rejected
    with pytest.raises(StaleAuthorityError):
        A.activate_candidate(actor=ACTOR, project_id=proj, run_id=run_v2["runId"], expected_binding_revision=999)
    # cross-project: the run id is not registered in a different project's evidence registry
    other = _proj()
    A.create_binding(actor=ACTOR, project_id=other, dataset_version_id=_gen3())
    with pytest.raises(AuthorityError):
        A.activate_candidate(actor=ACTOR, project_id=other, run_id=run_v2["runId"])


def test_active_candidate_read_reverifies_after_tamper(run_v2):
    A.activate_candidate(actor=ACTOR, project_id=run_v2["proj"], run_id=run_v2["runId"],
                         expected_binding_revision=run_v2["binding"]["revision"])
    with _tamper(run_v2["bundleDir"] / "validation-probabilities.f64"):
        with pytest.raises(AuthorityError):
            A.get_active_candidate(project_id=run_v2["proj"])
    # restored -> resolves again
    assert A.get_active_candidate(project_id=run_v2["proj"])["experimentRunId"] == run_v2["runId"]


# ============================================================ Gate 18 — evidence registry concurrency
def test_registry_same_run_same_receipt_is_idempotent():
    proj = _proj()
    rid, sha = uuid.uuid4().hex, "a" * 64
    A._evidence_registry_put(proj, rid, sha)
    A._evidence_registry_put(proj, rid, sha)   # idempotent, no error
    assert A._evidence_registry_get(proj, rid) == sha


def test_registry_same_run_different_receipt_conflicts():
    proj = _proj()
    rid = uuid.uuid4().hex
    A._evidence_registry_put(proj, rid, "a" * 64)
    with pytest.raises(AuthorityError):
        A._evidence_registry_put(proj, rid, "b" * 64)


def test_registry_concurrent_same_receipt_no_partial():
    proj = _proj()
    rid, sha = uuid.uuid4().hex, "c" * 64
    errors = []

    def worker():
        try:
            A._evidence_registry_put(proj, rid, sha)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and A._evidence_registry_get(proj, rid) == sha


def test_registry_missing_or_corrupt_fails_closed():
    proj = _proj()
    with pytest.raises(AuthorityError):
        A._evidence_registry_get(proj, uuid.uuid4().hex)   # missing registry
    p = A._evidence_registry_path(proj)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json")
    with pytest.raises(AuthorityError):
        A._evidence_registry_get(proj, uuid.uuid4().hex)   # corrupt registry
