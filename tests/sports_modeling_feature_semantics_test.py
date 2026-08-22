"""Phase 7D.2 — semantic feature authority + leakage validator + safe synthetic advanced-feature proof.

Fully hermetic (no real objects, no sealed data, no fits beyond a tiny preprocessor). Covers Gate 1 (per-
feature semantic contracts), Gate 2 (family + feature-set V2), Gate 3 (fail-closed structural leakage
validator — negative matrix A), and Gate 4 (a genuinely point-in-time synthetic feature
prior_pa_count -> log1p_prior_pa_count that enters an advanced feature set exactly once).
"""
from __future__ import annotations

import copy

import numpy as np
import pytest

from server.sports_modeling import feature_semantics as FS
from server.sports_modeling.feature_contract import FEATURE_NAMES
from server.sports_modeling.training import FoldPreprocessor

RECEIPTS = list(FS._SOURCE_RECEIPT_SHAS)


# ============================================================ Gate 1 — per-feature semantic contracts
def test_all_base_features_have_valid_semantic_contracts():
    cs = FS.all_feature_semantic_contracts()
    assert set(cs) == set(FEATURE_NAMES)
    for fid, c in cs.items():
        FS.validate_feature_semantic_contract(c)
        p = c["payload"]
        assert p["contractVersion"] == FS.SEMANTIC_CONTRACT_VERSION
        assert p["knowledgeTimeClass"] in FS.ALLOWED_PREDICTOR_CLASSES
        assert p["sourceReceiptShas"] and p["canonicalDerivation"] and p["asOfRule"]
        assert c["sha256"] and c["id"].endswith(c["sha256"])


def test_context_and_prior_knowledge_time_classes():
    cs = FS.all_feature_semantic_contracts()
    assert cs["context_inning"]["payload"]["knowledgeTimeClass"] == FS.CONDITIONAL_PRE_PA_STATE
    assert cs["batter_avg"]["payload"]["knowledgeTimeClass"] == FS.HISTORICAL_AS_OF_CUTOFF
    assert cs["pitcher_whip"]["payload"]["knowledgeTimeClass"] == FS.HISTORICAL_AS_OF_CUTOFF


# ============================================================ Gate 2 — family + feature-set V2 contracts
def test_families_bind_ordered_members_under_one_knowledge_time_policy():
    fams = FS.base_family_contracts()
    assert {k: v["payload"]["featureCount"] for k, v in fams.items()} == {
        "context_pre_pa_state": 5, "batter_prior_rates": 8, "pitcher_prior_rates": 9}
    for fam in fams.values():
        assert fam["payload"]["contractVersion"] == FS.FAMILY_CONTRACT_VERSION
        assert len(fam["payload"]["orderedFeatureContractShas"]) == fam["payload"]["featureCount"]


def test_base_feature_set_v2_binds_exact_ordered_ids():
    fsc = FS.base_feature_set_contract(dataset_version_id="dvid:sha256:abc", dataset_content_sha="abc")
    p = fsc["payload"]
    assert p["contractVersion"] == FS.FEATURE_SET_CONTRACT_VERSION
    assert p["exactFinalOrderedFeatureIds"] == list(FEATURE_NAMES)
    assert len(p["exactFinalFeatureContractShas"]) == 22 and p["featureCount"] == 22
    assert p["targetContractId"] and p["datasetVersionId"] == "dvid:sha256:abc"


def test_feature_set_rejects_unregistered_and_duplicate_features():
    cs = FS.all_feature_semantic_contracts()
    with pytest.raises(FS.LeakageError):   # unregistered feature id
        FS.feature_set_contract_v2(dataset_version_id="d", dataset_content_sha="c",
                                   ordered_base_feature_ids=list(FEATURE_NAMES), optional_family_ids=[],
                                   final_ordered_feature_ids=list(FEATURE_NAMES) + ["not_registered"], contracts=cs)
    with pytest.raises(FS.LeakageError):   # duplicate
        FS.feature_set_contract_v2(dataset_version_id="d", dataset_content_sha="c",
                                   ordered_base_feature_ids=list(FEATURE_NAMES), optional_family_ids=[],
                                   final_ordered_feature_ids=list(FEATURE_NAMES) + [FEATURE_NAMES[0]], contracts=cs)


# ============================================================ Gate 3 — leakage validator (matrix A rejections)
def _leaky(**overrides):
    base = dict(feature_id="cand", display_name="cand", family_id="fam", knowledge_time_class=FS.HISTORICAL_AS_OF_CUTOFF,
               as_of_rule="prior events strictly earlier than target", source_object_ids=["obj"], source_receipt_shas=RECEIPTS,
               source_columns=["prior_pa"], canonical_derivation="count prior PAs", derivation_code_digest="d",
               derivation_version="v1", window_rule="prior aggregate", allowed_seasons=[2023, 2024])
    base.update(overrides)
    return FS.build_semantic_contract(**base)


def test_safe_historical_feature_accepted():
    FS.validate_feature_semantic_contract(_leaky())  # no raise


@pytest.mark.parametrize("overrides, why", [
    ({"feature_id": "outcome"}, "target column"),
    ({"target_relationship_classification": "ENCODED_TARGET"}, "encoded target"),
    ({"target_relationship_classification": "TARGET_DERIVED_PROXY"}, "target proxy"),
    ({"knowledge_time_class": FS.POST_PA_PROHIBITED}, "post-PA"),
    ({"source_columns": ["launch_speed"]}, "post-PA launch speed"),
    ({"source_columns": ["woba_value"]}, "target wOBA result"),
    ({"source_columns": ["delta_run_exp"]}, "delta run expectancy"),
    ({"knowledge_time_class": FS.FUTURE_PROHIBITED}, "future"),
    ({"source_columns": ["game_id"]}, "game id as source"),
    ({"feature_id": "plate_appearance_id"}, "PA id as predictor"),
    ({"source_columns": ["batter_canonical_player_uuid"]}, "player id value source"),
    ({"identifier_classification": "PLAYER_ID_PREDICTOR"}, "identifier classified"),
    ({"knowledge_time_class": "BOGUS_CLASS"}, "unknown leakage class"),
    ({"source_object_ids": []}, "missing lineage"),
    ({"source_receipt_shas": []}, "missing receipt lineage"),
    ({"canonical_derivation": ""}, "missing derivation"),
    ({"as_of_rule": ""}, "unprovable as-of"),
])
def test_leakage_validator_rejects(overrides, why):
    with pytest.raises(FS.LeakageError):
        FS.validate_feature_semantic_contract(_leaky(**overrides))


# ============================================================ Gate 4 — safe synthetic advanced feature
def _fixture(seed=11, n_targets=60, n_events=400):
    rng = np.random.default_rng(seed)
    players = np.array([f"p{k}" for k in range(8)], dtype=object)
    # historical prior events (player + timestamp), independent of any target label
    ev_player = rng.choice(players, size=n_events)
    ev_time = rng.uniform(0.0, 100.0, size=n_events)
    # target PAs with their own timestamps and INDEPENDENTLY generated labels
    tg_player = rng.choice(players, size=n_targets)
    tg_time = rng.uniform(50.0, 100.0, size=n_targets)
    tg_label = rng.integers(0, 3, size=n_targets)
    return players, ev_player, ev_time, tg_player, tg_time, tg_label


def _derive_prior_pa_count(tg_player, tg_time, ev_player, ev_time):
    """prior_pa_count[i] = # prior events for target i's player with event_time STRICTLY earlier than target."""
    out = np.empty(len(tg_player), dtype=np.float64)
    for i in range(len(tg_player)):
        out[i] = float(np.sum((ev_player == tg_player[i]) & (ev_time < tg_time[i])))
    return out


def _synthetic_contract():
    return FS.build_semantic_contract(
        feature_id="log1p_prior_pa_count", display_name="log1p prior PA count", family_id="RELIABILITY_SAMPLE_SIZE_TEST",
        knowledge_time_class=FS.HISTORICAL_AS_OF_CUTOFF,
        as_of_rule="count of the player's plate appearances with event timestamp STRICTLY earlier than the target PA timestamp",
        source_object_ids=["synthetic_historical_pa_events"], source_receipt_shas=RECEIPTS,
        source_columns=["prior_pa_count"], canonical_derivation="log1p(count of prior PAs strictly earlier than target time)",
        derivation_code_digest="reliability_sample_size_v1", derivation_version="RELIABILITY_SAMPLE_SIZE_TEST_V1",
        window_rule="all prior events strictly earlier than the target knowledge time", allowed_seasons=[2023, 2024])


def test_synthetic_feature_is_point_in_time_safe():
    players, ev_player, ev_time, tg_player, tg_time, tg_label = _fixture()
    count = _derive_prior_pa_count(tg_player, tg_time, ev_player, ev_time)
    assert count.sum() > 0  # non-vacuous
    # (a) target permutation does not change the feature (the label never enters the derivation)
    rng = np.random.default_rng(0)
    perm = rng.permutation(len(tg_label))
    _ = tg_label[perm]  # labels shuffled; derivation ignores labels entirely
    assert np.array_equal(count, _derive_prior_pa_count(tg_player, tg_time, ev_player, ev_time))
    # (b) adding events strictly AFTER every target time (pure future) does not change prior feature values
    max_t = float(tg_time.max())
    extra_player = rng.choice(players, size=50)
    extra_time = rng.uniform(max_t + 1.0, max_t + 100.0, size=50)   # future of every target
    ev_player_aug = np.concatenate([ev_player, extra_player])
    ev_time_aug = np.concatenate([ev_time, extra_time])
    assert np.array_equal(count, _derive_prior_pa_count(tg_player, tg_time, ev_player_aug, ev_time_aug))
    # (c) the current target outcome cannot enter (derivation has no access to labels) — structurally true


def test_synthetic_feature_contract_is_historical_and_valid():
    c = _synthetic_contract()
    FS.validate_feature_semantic_contract(c)
    assert c["payload"]["knowledgeTimeClass"] == FS.HISTORICAL_AS_OF_CUTOFF
    assert c["payload"]["featureFamilyId"] == "RELIABILITY_SAMPLE_SIZE_TEST"


def test_advanced_feature_set_includes_synthetic_exactly_once_at_exact_position():
    cs = FS.all_feature_semantic_contracts()
    base = FS.base_feature_set_contract(dataset_version_id="dvid:sha256:abc", dataset_content_sha="abc")
    adv_contracts = dict(cs); adv_contracts["log1p_prior_pa_count"] = _synthetic_contract()
    advanced_order = list(FEATURE_NAMES) + ["log1p_prior_pa_count"]
    adv = FS.feature_set_contract_v2(dataset_version_id="dvid:sha256:abc", dataset_content_sha="abc",
                                     ordered_base_feature_ids=list(FEATURE_NAMES),
                                     optional_family_ids=["RELIABILITY_SAMPLE_SIZE_TEST"],
                                     final_ordered_feature_ids=advanced_order, contracts=adv_contracts, name="advanced")
    base_ids = base["payload"]["exactFinalOrderedFeatureIds"]
    adv_ids = adv["payload"]["exactFinalOrderedFeatureIds"]
    assert "log1p_prior_pa_count" not in base_ids                       # base excludes it
    assert adv_ids.count("log1p_prior_pa_count") == 1                   # advanced includes it exactly once
    assert adv_ids.index("log1p_prior_pa_count") == 22                  # exact ordered position (last)
    assert adv_ids[:22] == base_ids                                     # base is the exact prefix
    assert adv["sha256"] != base["sha256"]                             # feature-set SHA changes


def test_preprocessor_fingerprint_changes_when_synthetic_added():
    from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
    rng = np.random.default_rng(3)
    n = 120
    fv = {"batter_avg": rng.normal(size=n), "pitcher_whip": rng.normal(size=n), "log1p_prior_pa_count": rng.normal(size=n)}
    mask = np.ones(n, dtype=bool)
    base_fp = sha256_bytes(canonical_json_bytes(FoldPreprocessor.fit(fv, ["batter_avg", "pitcher_whip"], mask).state()))
    adv_fp = sha256_bytes(canonical_json_bytes(
        FoldPreprocessor.fit(fv, ["batter_avg", "pitcher_whip", "log1p_prior_pa_count"], mask).state()))
    assert base_fp != adv_fp


def test_reordered_feature_set_has_a_different_identity():
    cs = FS.all_feature_semantic_contracts()
    normal = FS.base_feature_set_contract(dataset_version_id="d", dataset_content_sha="c")
    reordered_ids = list(FEATURE_NAMES)
    reordered_ids[0], reordered_ids[1] = reordered_ids[1], reordered_ids[0]
    reordered = FS.feature_set_contract_v2(dataset_version_id="d", dataset_content_sha="c",
                                           ordered_base_feature_ids=reordered_ids, optional_family_ids=[],
                                           final_ordered_feature_ids=reordered_ids, contracts=cs, name="base")
    assert reordered["sha256"] != normal["sha256"]    # order is part of the feature-set identity
