"""Phase 7D — behavioral acceptance for the Phase 7B acquisition gate (upgraded to the V2 world in 7D.4).

Hermetic + isolated (never touches shared .runtime): builds a temporary canonical registry + immutable object
roots with REAL published Gen-3 research/sealed objects (the research object carries ``prior_pa_count`` + its safe
derived ``log1p_prior_pa_count`` feature, registered as a complete MLB_FEATURE_SET_CONTRACT_V2), then exercises the
PRODUCTION resolver/authority/evidence code. Proves: one immutable registry as sole resolver; complete object
verification + path containment + cache safety; generation-specific feature contracts + advanced-feature
propagation into the run; canonical 2024-only feature-family comparison (V2-only, immutable receipt); atomic
content-addressed V2 evidence + child tamper rejection on the active read; loadable fitted HGB estimator;
activation that rejects fabricated runs; and run-authority reconstruction/forgery rejection. No 2025 is ever scored.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.sports_cockpit import gen3_authority as A
from tests._hermetic_gen3 import ADVANCED_FEATURE, build_hermetic_gen3


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    return build_hermetic_gen3(tmp_path, monkeypatch)


# ---------------- A. registry sole resolver ----------------
def test_registry_is_sole_resolver_with_four_entries_and_zero_opens(hermetic):
    A.reset_object_open_log()
    cat = A.catalog()
    assert A.object_open_log() == []
    gens = sorted(e["generation"] for e in cat)
    assert gens == ["GEN2", "GEN2_SEALED", "GEN3", "GEN3_SEALED"]
    assert sum(1 for e in cat if e["selectable"]) == 2
    reg = json.loads(A.ASP_REGISTRY.read_text())
    assert reg["schemaVersion"] == "ASP_DATASET_REGISTRY_V3" and reg.get("migrationId")


# ---------------- C. object verifier ----------------
def test_object_verifier_containment_and_tamper(hermetic):
    e = next(x for x in A.catalog() if x["generation"] == "GEN3")
    A._verify_object(e)                      # baseline passes
    A.reset_object_open_log()
    evil = {**e, "objectPath": str(Path("C:/Windows/System32/evil.parquet"))}
    with pytest.raises(A.AuthorityError):
        A._verify_object(evil)
    assert A.object_open_log() == []         # outside-root rejected BEFORE any open
    with pytest.raises(A.AuthorityError):    # forged logical sha
        A._verify_object({**e, "logicalContentSha256": "0" * 64})
    with pytest.raises(A.AuthorityError):    # sealed refused to ordinary capability
        A._verify_object(next(x for x in A.catalog() if x["generation"] == "GEN3_SEALED"))


def test_verification_cache_rejects_same_size_substitution(hermetic):
    e = next(x for x in A.catalog() if x["generation"] == "GEN3")
    path, _ = A._verify_object(e)            # warms the (retired) cache
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF             # flip a byte (same size)
    path.write_bytes(bytes(data))
    with pytest.raises(A.AuthorityError):    # physical SHA recomputed -> tamper
        A._verify_object(e)


# ---------------- D/Gate 11. advanced-feature propagation ----------------
def test_advanced_feature_enters_the_canonical_run(hermetic):
    proj = "p7d-prop"
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=hermetic["researchId"])
    base = A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                                 hyperparameters={"maxIter": 20}, feature_set="base")
    adv = A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                                hyperparameters={"maxIter": 20}, feature_set="advanced")
    assert base["featureSetSha256"] != adv["featureSetSha256"]
    assert base["canonicalEffectiveConfigSha256"] != adv["canonicalEffectiveConfigSha256"]
    assert ADVANCED_FEATURE not in base["featureSet"]
    assert adv["featureSet"].count(ADVANCED_FEATURE) == 1 and adv["featureSet"][-1] == ADVANCED_FEATURE
    ev_base = A.execute(actor="t@asp", project_id=proj, run_authority_id=base["runAuthorityId"])
    ev_adv = A.execute(actor="t@asp", project_id=proj, run_authority_id=adv["runAuthorityId"])
    assert ev_base["preprocessorFingerprint"] != ev_adv["preprocessorFingerprint"]
    assert ev_adv["sealedSeasonsAccessed"] == [] and 2025 not in ev_adv["seasonsInObject"]
    # a client cannot name an unregistered/arbitrary feature set
    with pytest.raises(A.AuthorityError):
        A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                              hyperparameters={"maxIter": 20}, feature_set="arbitrary_injection")


# ---------------- E/Gate 10. canonical 2024-only V2-only feature-family comparison ----------------
def test_feature_family_ablation_is_2024_only_and_paired(hermetic):
    proj = "p7d-abl"
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=hermetic["researchId"])
    out = A.run_feature_family_ablation(actor="t@asp", project_id=proj, binding_id=b["bindingId"],
                                        model_family="governed_hgb", control_feature_set="base",
                                        challenger_feature_set="advanced", hyperparameters={"maxIter": 20},
                                        bootstrap_iterations=200)
    assert out["schemaVersion"] == "MODEL_FEATURE_FAMILY_COMPARISON_RECEIPT_V1"
    assert out["validationSeason"] == 2024 and out["featureFamilyAdded"] == [ADVANCED_FEATURE]
    assert out["control"]["runId"] != out["challenger"]["runId"]
    assert out["control"]["featureSetSha256"] != out["challenger"]["featureSetSha256"]
    assert out["control"]["runReceiptSha256"] and out["challenger"]["bundleManifestSha256"]
    assert out["uncertainty"]["method"] == "PAIRED_GAME_CLUSTER_BOOTSTRAP" and out["uncertainty"]["iterations"] == 200
    assert "comparisonReceiptSha256" in out and "2025" not in json.dumps(out["classConditionalLogLossDelta"])


# ---------------- F/G/Gate 16. V2 evidence + activation integrity ----------------
def test_evidence_activation_and_estimator(hermetic):
    proj = "p7d-evi"
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=hermetic["researchId"])
    au = A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                               hyperparameters={"maxIter": 20})
    ev = A.execute(actor="t@asp", project_id=proj, run_authority_id=au["runAuthorityId"]); rid = ev["experimentRunId"]
    assert type(A.load_fitted_estimator_v2(project_id=proj, run_id=rid)).__name__ == "HistGradientBoostingClassifier"
    A.activate_candidate(actor="t@asp", project_id=proj, run_id=rid, expected_binding_revision=b["revision"])
    assert A.get_active_candidate(project_id=proj)["runId"] == rid
    # fabricated run (not in the evidence registry) rejected
    with pytest.raises(A.AuthorityError):
        A.activate_candidate(actor="t@asp", project_id=proj, run_id="0" * 32)
    # a V2 bundle child tamper is caught by the canonical chain on the active read (child SHA no longer matches)
    v = A.verify_model_run_receipt(project_id=proj, run_id=rid)
    (v["bundleDir"] / "aggregate-metrics.json").write_bytes(b'{"tampered":true}')
    with pytest.raises(A.AuthorityError):
        A.get_active_candidate(project_id=proj)


# ---------------- H/Gate 17. authority reconstruction / forgery ----------------
def test_authority_forgery_rejected(hermetic):
    proj = "p7d-auth"
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=hermetic["researchId"])
    au = A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                               hyperparameters={"maxIter": 20})
    for field, val in (("generation", "GEN2"), ("bindingRevision", 999), ("seed", 42)):
        forged = {**A.get_run_authority(project_id=proj, run_authority_id=au["runAuthorityId"]), field: val}
        A._write_json_atomic(A._state(proj, "authorities", forged["runAuthorityId"] + ".json"), forged)
        with pytest.raises(A.AuthorityError):
            A.execute(actor="t@asp", project_id=proj, run_authority_id=forged["runAuthorityId"])
        A._write_json_atomic(A._state(proj, "authorities", au["runAuthorityId"] + ".json"), au)  # restore
