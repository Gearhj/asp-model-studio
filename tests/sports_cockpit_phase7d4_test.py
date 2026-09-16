"""Phase 7D.4 — production semantic authority, mandatory request receipt, canonical parent-chain verifier,
final-drift transaction, and 2025-script retirement.

Hermetic (each run in its own opaque project; one governed HGB run reused with forge+restore). The crown-jewel
test builds a fully self-consistent forged bundle+receipt+registry that the NARROW receipt verifier accepts but
the CANONICAL chain verifier rejects (it disagrees with the current contracts).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit.gen3_authority import AuthorityError, StaleAuthorityError
from server.sports_modeling import feature_semantics as FS
from server.sports_modeling.feature_contract import FEATURE_NAMES

REPO = Path(__file__).resolve().parents[1]
from tests._runtime_probe import HAS_GEN3_V2 as _HAS_V2  # seam-aware: runs on the seeded isolated authority
ACTOR = "pytest-7d4@asp"


def _proj() -> str:
    return "test-7d4-" + uuid.uuid4().hex[:12]


def _gen3() -> str:
    return {c["generation"]: c["datasetVersionId"] for c in A.catalog()}["GEN3"]


# ============================================================ B2 — strict closed leakage enum
def test_leakage_enum_rejects_unknown_blank_and_prohibited():
    cs = FS.all_feature_semantic_contracts()
    assert {c["payload"]["leakageClassification"] for c in cs.values()} <= FS.SAFE_LEAKAGE_CLASSES
    import copy
    for bad in ("BOGUS_UNKNOWN", "", None, "TARGET_PROHIBITED", "POST_PA_PROHIBITED"):
        c = copy.deepcopy(cs["batter_avg"]); c["payload"]["leakageClassification"] = bad
        with pytest.raises(FS.LeakageError):
            FS.validate_feature_semantic_contract(c)


# ============================================================ B1 — non-base sets require complete V2 semantics
def test_non_base_bare_namelist_feature_set_is_refused():
    entry = {"generation": "GEN3", "featureSets": {"adv_namelist": list(FEATURE_NAMES) + ["log1p_prior_pa_count"]}}
    with pytest.raises(AuthorityError):
        A._resolve_feature_set(entry, "adv_namelist")   # bare list has no semantic authority -> refused


def test_non_base_v2_semantic_set_is_accepted_and_leakage_validated():
    safe = FS.build_semantic_contract(
        feature_id="log1p_prior_pa_count", display_name="log1p prior PA count", family_id="RELIABILITY_SAMPLE_SIZE_TEST",
        knowledge_time_class=FS.HISTORICAL_AS_OF_CUTOFF, as_of_rule="strictly earlier than target time",
        source_object_ids=["synthetic_events"], source_receipt_shas=list(FS._SOURCE_RECEIPT_SHAS),
        source_columns=["prior_pa_count"], canonical_derivation="log1p(count prior PAs strictly earlier)",
        derivation_code_digest="reliability_v1", derivation_version="RSST_V1", window_rule="prior aggregate",
        allowed_seasons=[2023, 2024], leakage_classification="SAFE_HISTORICAL_AS_OF")
    spec = {"contractVersion": FS.FEATURE_SET_CONTRACT_VERSION,
            "exactFinalOrderedFeatureIds": list(FEATURE_NAMES) + ["log1p_prior_pa_count"],
            "semanticContracts": [safe]}
    entry = {"generation": "GEN3", "featureSets": {"advanced": spec}}
    fsc = A._resolve_feature_set(entry, "advanced")
    assert fsc["payload"]["featureOrder"][-1] == "log1p_prior_pa_count"
    # a leaky advanced feature (target proxy) is rejected at resolution
    leaky = FS.build_semantic_contract(
        feature_id="target_proxy", display_name="proxy", family_id="X", knowledge_time_class=FS.HISTORICAL_AS_OF_CUTOFF,
        as_of_rule="x", source_object_ids=["o"], source_receipt_shas=list(FS._SOURCE_RECEIPT_SHAS),
        source_columns=["outcome"], canonical_derivation="d", derivation_code_digest="d", derivation_version="v",
        window_rule="w", allowed_seasons=[2024], leakage_classification="SAFE_HISTORICAL_AS_OF")
    spec2 = {"contractVersion": FS.FEATURE_SET_CONTRACT_VERSION,
             "exactFinalOrderedFeatureIds": list(FEATURE_NAMES) + ["target_proxy"], "semanticContracts": [leaky]}
    with pytest.raises(AuthorityError):
        A._resolve_feature_set({"generation": "GEN3", "featureSets": {"adv2": spec2}}, "adv2")


# ============================================================ B8 — 2025-capable scripts retired before open
@pytest.mark.parametrize("script", [
    "run_mlb_e1_e2_incremental_signal_study", "phase7_ablation", "run_mlb_base_out_transition",
    "run_mlb_projected_participation_ablation", "run_mlb_simulation_input_layer", "run_mlb_starter_identity",
    "run_mlb_whole_game_monte_carlo",
])
def test_ordinary_2025_scripts_exit_before_any_open(script):
    r = subprocess.run([sys.executable, "-m", f"scripts.{script}"], cwd=str(REPO),
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PYTHONPATH": str(REPO)})
    assert r.returncode == 2, f"{script} did not exit(2): rc={r.returncode}"
    assert "RETIRED (Phase 7D.4 Gate 12)" in (r.stderr + r.stdout)


# ============================================================ heavy: one governed HGB run
@pytest.fixture(scope="module")
def run(request):
    if not _HAS_V2:
        pytest.skip("Gen-3 v2 authority not published")
    proj = _proj()
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=_gen3())
    au = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"],
                               model_family="governed_hgb", hyperparameters={"maxIter": 40})
    ev = A.execute(actor=ACTOR, project_id=proj, run_authority_id=au["runAuthorityId"])
    return {"proj": proj, "binding": b, "authority": au, "runId": ev["experimentRunId"]}


# ---- B4 canonical chain: valid accepted; activation + eval route through it ----
def test_canonical_chain_accepts_valid_run(run):
    v = A.verify_canonical_model_run_chain(project_id=run["proj"], run_id=run["runId"],
                                           expected_binding_revision=run["binding"]["revision"])
    assert len(v["classOrder"]) == 8 and v["orderedFeatures"] == list(FEATURE_NAMES)
    act = A.activate_candidate(actor=ACTOR, project_id=run["proj"], run_id=run["runId"],
                               expected_binding_revision=run["binding"]["revision"])
    assert act["schemaVersion"] == "ACTIVE_CANDIDATE_REVIEW_V2"
    ce = A.active_candidate_evaluation(project_id=run["proj"])
    assert ce["recomputationMatchesStored"] and "2025" not in json.dumps(ce["metrics"])


# ---- B4 crown jewel: coordinated forgery accepted by the narrow verifier, rejected by the chain ----
def _forge_self_consistent_bundle(proj: str, run_id: str, mutate_authority) -> str:
    """Rebuild a fully self-consistent bundle (children+inventory+manifest), a matching receipt, and remap the
    registry — mutating one field of the bundled run-authority child. Returns the new receipt sha."""
    v = A.verify_model_run_receipt(project_id=proj, run_id=run_id)
    bdir, manifest = v["bundleDir"], v["manifest"]
    children = {n: A._v2_child_bytes(bdir, manifest, n) for n in A._V2_CONTENT_CHILDREN}
    auth = json.loads(children["run-authority.json"].decode("utf-8")); mutate_authority(auth)
    children["run-authority.json"] = A.canonical_json_bytes(auth)
    child_shas = {n: hashlib.sha256(b).hexdigest() for n, b in children.items()}
    inv = A.canonical_json_bytes({"schemaVersion": "MODEL_RUN_CHILD_SHA_INVENTORY_V1",
                                  "children": dict(sorted(child_shas.items()))})
    all_shas = {**child_shas, A._V2_CHILD_SHA_INVENTORY: hashlib.sha256(inv).hexdigest()}
    new_manifest = {k: vv for k, vv in manifest.items() if k not in ("bundleManifestSha256", "children")}
    new_manifest["children"] = {n: {"file": n, "sha256": s} for n, s in sorted(all_shas.items())}
    man_bytes = A.canonical_json_bytes(new_manifest); man_sha = hashlib.sha256(man_bytes).hexdigest()
    final = A._v2_objects_dir(proj, man_sha); final.mkdir(parents=True, exist_ok=True)
    for n, b in children.items():
        (final / n).write_bytes(b)
    (final / A._V2_CHILD_SHA_INVENTORY).write_bytes(inv); (final / A._V2_MANIFEST_NAME).write_bytes(man_bytes)
    rec = json.loads((A._v2_receipt_dir(proj, v["receiptSha256"]) / "receipt.json").read_text(encoding="utf-8"))
    rec = {k: vv for k, vv in rec.items() if k != "receiptSha256"}; rec["bundleManifestSha256"] = man_sha
    rsha = A.sha256_bytes(A.canonical_json_bytes(rec)); rec["receiptSha256"] = rsha
    rd = A._v2_receipt_dir(proj, rsha); rd.mkdir(parents=True, exist_ok=True)
    (rd / "receipt.json").write_text(json.dumps(rec), encoding="utf-8")
    regp = A._evidence_registry_path(proj); reg = json.loads(regp.read_text(encoding="utf-8"))
    reg["runs"][run_id] = rsha; regp.write_text(json.dumps(reg), encoding="utf-8")
    return rsha


def test_coordinated_forgery_accepted_by_narrow_verifier_rejected_by_chain(run):
    proj = _proj()   # isolated project so we don't corrupt the module run's registry
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=_gen3())
    au = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb", hyperparameters={"maxIter": 30})
    ev = A.execute(actor=ACTOR, project_id=proj, run_authority_id=au["runAuthorityId"])
    rid = ev["experimentRunId"]
    # forge: change the bundled authority's targetContractSha256 to a bogus (but internally consistent) value
    _forge_self_consistent_bundle(proj, rid, lambda a: a.__setitem__("targetContractSha256", "dead" * 16))
    # the NARROW receipt verifier accepts (all file hashes are internally consistent)
    A.verify_model_run_receipt(project_id=proj, run_id=rid)
    # the CANONICAL chain verifier REJECTS (authority target contract disagrees with the current contract)
    with pytest.raises(AuthorityError):
        A.verify_canonical_model_run_chain(project_id=proj, run_id=rid, require_current_binding=False)
    # activation (which uses the chain) also rejects
    with pytest.raises(AuthorityError):
        A.activate_candidate(actor=ACTOR, project_id=proj, run_id=rid)


# ---- B4: superseded binding rejected on activation + active read ----
def test_superseded_binding_rejected_by_chain(run):
    proj = run["proj"]
    A.activate_candidate(actor=ACTOR, project_id=proj, run_id=run["runId"], expected_binding_revision=run["binding"]["revision"])
    A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=_gen3(), revision_reason="rebind")  # supersede
    assert A.get_active_candidate(project_id=proj) is None                     # STALE
    with pytest.raises(StaleAuthorityError):
        A.activate_candidate(actor=ACTOR, project_id=proj, run_id=run["runId"], expected_binding_revision=1)


# ---- B3: the immutable request receipt is mandatory ----
def test_missing_request_receipt_fails_closed(run):
    proj = _proj()
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=_gen3())
    au = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb", hyperparameters={"maxIter": 30})
    rr = au["modelRequestReceiptSha256"]
    A._state(proj, "requests", f"{rr}.json").unlink()                          # delete the immutable receipt
    with pytest.raises(AuthorityError):                                        # execute reconstructs -> fail closed
        A.execute(actor=ACTOR, project_id=proj, run_authority_id=au["runAuthorityId"])


# ---- B7: injected late drift between post-fit and final publication ----
def test_injected_late_drift_yields_no_complete_evidence(run, monkeypatch):
    proj = _proj()
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=_gen3())
    au = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb", hyperparameters={"maxIter": 30})
    monkeypatch.setattr(A, "_final_publication_code_identity",
                        lambda: {"codeRevision": "DRIFTED", "worktreeContentSha256": "DRIFTED", "dirty": True})
    with pytest.raises(StaleAuthorityError):
        A.execute(actor=ACTOR, project_id=proj, run_authority_id=au["runAuthorityId"])
    # no run is registered in the evidence registry -> no COMPLETE evidence, not activatable
    regp = A._evidence_registry_path(proj)
    reg = json.loads(regp.read_text(encoding="utf-8")) if regp.is_file() else {"runs": {}}
    assert not reg.get("runs")
