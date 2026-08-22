"""Phase 7D.4 closure — B2-full (Gate 3/13) safe advanced feature through the REAL production chain, and
B6 (Gate 10) V2-only feature-family comparison.

Hermetic + isolated (never touches the shared .runtime): a real Gen-3 research object carrying ``prior_pa_count``
and its safe derived ``log1p_prior_pa_count`` is published through the ACTUAL production publisher, registered with
a complete MLB_FEATURE_SET_CONTRACT_V2, then run through registration -> binding -> request -> run -> V2 evidence
-> activation -> evaluation. Leaky variants are rejected through the production registration/request path BEFORE any
COMPLETE evidence. The feature-family comparison resolves BOTH arms only through the canonical V2 chain and emits an
immutable content-addressed comparison receipt. No external download, no Bronze, no real 2025.
"""
from __future__ import annotations

import json
import warnings

import pytest

warnings.filterwarnings("ignore")

from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit.gen3_authority import AuthorityError, StaleAuthorityError
from server.sports_modeling.feature_contract import FEATURE_NAMES
from tests._hermetic_gen3 import (
    ADVANCED_FEATURE, advanced_feature_set_spec, advanced_semantic_contract, build_hermetic_gen3,
)

ACTOR = "pytest-7d4-prod@asp"


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    return build_hermetic_gen3(tmp_path, monkeypatch)


# =============================================================== B2-full — safe feature through the full chain
def test_safe_advanced_feature_traverses_full_production_chain(hermetic):
    proj = "p7d4-b2full"
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=hermetic["researchId"])
    # base + advanced authorities differ; the advanced feature is bound last, exactly once
    base = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                                 hyperparameters={"maxIter": 20}, feature_set="base")
    adv = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                                hyperparameters={"maxIter": 20}, feature_set="advanced")
    assert base["featureSetSha256"] != adv["featureSetSha256"]
    assert ADVANCED_FEATURE not in base["featureSet"]
    assert adv["featureSet"].count(ADVANCED_FEATURE) == 1 and adv["featureSet"][-1] == ADVANCED_FEATURE
    assert list(adv["featureSet"][:len(FEATURE_NAMES)]) == list(FEATURE_NAMES)   # exact base prefix

    # fit on 2021-2023, evaluate on 2024, publish V2 evidence + immutable receipt + registry entry
    ev = A.execute(actor=ACTOR, project_id=proj, run_authority_id=adv["runAuthorityId"])
    rid = ev["experimentRunId"]
    assert ev["sealedSeasonsAccessed"] == [] and 2025 not in ev["seasonsInObject"]
    assert ev["developmentSeasons"] == [2021, 2022, 2023] and ev["validationSeason"] == 2024

    # the immutable parent chain reconstructs and cross-checks
    v = A.verify_canonical_model_run_chain(project_id=proj, run_id=rid, expected_binding_revision=b["revision"])
    assert v["orderedFeatures"][-1] == ADVANCED_FEATURE and len(v["orderedFeatures"]) == len(FEATURE_NAMES) + 1

    # temporary isolated activation + Active Candidate + Evaluation reads (all through the chain)
    A.activate_candidate(actor=ACTOR, project_id=proj, run_id=rid, expected_binding_revision=b["revision"])
    ac = A.get_active_candidate(project_id=proj)
    assert ac["runId"] == rid and ac["run"]["runAuthorityId"] == adv["runAuthorityId"]
    ce = A.active_candidate_evaluation(project_id=proj)
    assert ce["recomputationMatchesStored"] and ce["featureCount"] == len(FEATURE_NAMES) + 1
    assert "2025" not in json.dumps(ce["metrics"])
    reg = A.active_candidate_registry_evidence(project_id=proj)
    assert reg["modelSha256"] and reg["predictionSha256"] and reg["runReceiptSha256"] == v["receiptSha256"]


# =============================================================== B2 — leaky variants rejected on the production path
def _leaky_spec(**overrides):
    return advanced_feature_set_spec(contract=advanced_semantic_contract(**overrides))


def _incomplete_spec():
    c = advanced_semantic_contract()
    c["payload"].pop("derivationCodeDigest")          # strip a mandatory derivation identity
    return advanced_feature_set_spec(contract=c)


_LEAKY = {
    "target_derived": _leaky_spec(source_columns=["outcome"]),
    "post_pa": _leaky_spec(source_columns=["launch_speed"]),
    "future": _leaky_spec(knowledge_time="FUTURE_PROHIBITED"),
    "identifier_derived": _leaky_spec(source_columns=["batter"]),
    "prohibited_leakage_class": _leaky_spec(leakage="TARGET_PROHIBITED"),
    "unknown_leakage_class": _leaky_spec(leakage="BOGUS_UNKNOWN"),
    "blank_leakage_class": _leaky_spec(leakage=""),
    "incomplete_semantic_authority": _incomplete_spec(),
    "bare_namelist": [*FEATURE_NAMES, ADVANCED_FEATURE],   # a bare ordered list, no V2 semantic authority
}


@pytest.mark.parametrize("kind", list(_LEAKY))
def test_leaky_advanced_feature_rejected_before_any_complete_evidence(tmp_path, monkeypatch, kind):
    h = build_hermetic_gen3(tmp_path, monkeypatch, advanced_spec=_LEAKY[kind])
    proj = f"p7d4-leak-{kind}"
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=h["researchId"])
    # the rejection happens at run-authority issuance (feature-set resolution), BEFORE any fit/evidence
    with pytest.raises(AuthorityError):
        A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                              hyperparameters={"maxIter": 20}, feature_set="advanced")
    # no COMPLETE evidence / registry entry / activation was produced for the rejected request
    regp = A._evidence_registry_path(proj)
    reg = json.loads(regp.read_text(encoding="utf-8")) if regp.is_file() else {"runs": {}}
    assert not reg.get("runs")
    assert not A._state(proj, "active-candidate.json").is_file()


# =============================================================== B6 — V2-only feature-family comparison
def test_v2_only_feature_family_comparison_and_immutable_receipt(hermetic):
    proj = "p7d4-b6"
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=hermetic["researchId"])
    out = A.run_feature_family_ablation(actor=ACTOR, project_id=proj, binding_id=b["bindingId"],
                                        model_family="governed_hgb", control_feature_set="base",
                                        challenger_feature_set="advanced", hyperparameters={"maxIter": 20},
                                        bootstrap_iterations=200)
    assert out["schemaVersion"] == "MODEL_FEATURE_FAMILY_COMPARISON_RECEIPT_V1"
    assert out["validationSeason"] == 2024 and out["featureFamilyAdded"] == [ADVANCED_FEATURE]
    assert out["featureFamilyId"].startswith("MLB_FEATURE_FAMILY_CONTRACT_V1:") and out["featureFamilySha256"]
    assert out["control"]["runId"] != out["challenger"]["runId"]
    assert out["control"]["featureSetSha256"] != out["challenger"]["featureSetSha256"]
    # both arms bind IMMUTABLE V2 artifacts (run receipt + content-addressed bundle), not V1/mutable evidence
    for arm in (out["control"], out["challenger"]):
        assert arm["runReceiptSha256"] and arm["bundleManifestSha256"]
        v = A.verify_canonical_model_run_chain(project_id=proj, run_id=arm["runId"], require_current_binding=True)
        assert v["receiptSha256"] == arm["runReceiptSha256"]
    assert out["uncertainty"]["method"] == "PAIRED_GAME_CLUSTER_BOOTSTRAP" and out["uncertainty"]["iterations"] == 200
    assert "2025" not in json.dumps(out["classConditionalLogLossDelta"]) and "2025" not in json.dumps(out["metricDelta"])
    # the comparison receipt is immutable + content-addressed (create-once)
    comp = A._state(proj, "comparisons", "sha256", f"{out['comparisonReceiptSha256']}.json")
    assert comp.is_file()
    stored = json.loads(comp.read_text(encoding="utf-8"))
    assert stored["comparisonReceiptSha256"] == out["comparisonReceiptSha256"]
    assert A.sha256_bytes(A.canonical_json_bytes({k: v for k, v in stored.items() if k != "comparisonReceiptSha256"})) \
        == out["comparisonReceiptSha256"]


def test_comparison_arm_resolution_rejects_a_superseded_binding(hermetic):
    proj = "p7d4-b6-stale"
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=hermetic["researchId"])
    au = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb",
                               hyperparameters={"maxIter": 20}, feature_set="base")
    ev = A.execute(actor=ACTOR, project_id=proj, run_authority_id=au["runAuthorityId"])
    # the V2-only arm resolver resolves fine under the current binding
    A._v2_validation_evidence(proj, ev["experimentRunId"])
    A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=hermetic["researchId"], revision_reason="rebind")
    # after supersession the same run no longer resolves as a comparison arm (fail-closed, not a V1 fallback)
    with pytest.raises(StaleAuthorityError):
        A._v2_validation_evidence(proj, ev["experimentRunId"])
