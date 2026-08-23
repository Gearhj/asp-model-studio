"""Phase 7D.2 — semantic per-feature authority, family/feature-set contracts, and a fail-closed structural
leakage validator.

Every authorized predictor carries an immutable ``MLB_FEATURE_SEMANTIC_CONTRACT_V1`` record binding its
derivation, source lineage, knowledge-time class, and leakage classification, so a feature can NEVER be
authorized merely because a column name exists. Families (``MLB_FEATURE_FAMILY_CONTRACT_V1``) and feature sets
(``MLB_FEATURE_SET_CONTRACT_V2``) bind the exact ordered feature ids + their contract SHAs. The leakage
validator is STRUCTURAL (declared lineage/derivation/as-of, never statistical correlation): it rejects target,
target-derived, post-PA, future, and identifier features, and any feature whose lineage / derivation / as-of
rule / knowledge-time class is missing or unknown.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from . import gen3_contracts as GC
from .feature_contract import BATTER_FEATURES, CONTEXT_FEATURES, FEATURE_NAMES, PITCHER_FEATURES

SEMANTIC_CONTRACT_VERSION = "MLB_FEATURE_SEMANTIC_CONTRACT_V1"
FAMILY_CONTRACT_VERSION = "MLB_FEATURE_FAMILY_CONTRACT_V1"
FEATURE_SET_CONTRACT_VERSION = "MLB_FEATURE_SET_CONTRACT_V2"

# ------------------------------------------------------------------ knowledge-time taxonomy (Gate 1)
PREGAME_KNOWN = "PREGAME_KNOWN"
CONDITIONAL_PRE_PA_STATE = "CONDITIONAL_PRE_PA_STATE"
HISTORICAL_AS_OF_CUTOFF = "HISTORICAL_AS_OF_CUTOFF"
POST_PA_PROHIBITED = "POST_PA_PROHIBITED"
FUTURE_PROHIBITED = "FUTURE_PROHIBITED"
IDENTIFIER_NOT_PREDICTOR = "IDENTIFIER_NOT_PREDICTOR"
TARGET_PROHIBITED = "TARGET_PROHIBITED"

KNOWLEDGE_TIME_CLASSES = frozenset({
    PREGAME_KNOWN, CONDITIONAL_PRE_PA_STATE, HISTORICAL_AS_OF_CUTOFF,
    POST_PA_PROHIBITED, FUTURE_PROHIBITED, IDENTIFIER_NOT_PREDICTOR, TARGET_PROHIBITED,
})
ALLOWED_PREDICTOR_CLASSES = frozenset({PREGAME_KNOWN, CONDITIONAL_PRE_PA_STATE, HISTORICAL_AS_OF_CUTOFF})
PROHIBITED_PREDICTOR_CLASSES = frozenset({POST_PA_PROHIBITED, FUTURE_PROHIBITED,
                                          IDENTIFIER_NOT_PREDICTOR, TARGET_PROHIBITED})

# Gate 2 (7D.4 / B2) — leakageClassification is a strict CLOSED enum. Only explicit SAFE classes may enter an
# authorized feature set; unknown / blank / null / unregistered values are rejected before registration.
SAFE_LEAKAGE_CLASSES = frozenset({"SAFE_PREGAME", "SAFE_HISTORICAL_AS_OF", "SAFE_CONDITIONAL_PRE_PA"})
PROHIBITED_LEAKAGE_CLASSES = frozenset({"TARGET_PROHIBITED", "POST_PA_PROHIBITED", "FUTURE_PROHIBITED",
                                        "IDENTIFIER_PROHIBITED", "UNRESOLVED_PROHIBITED"})
LEAKAGE_CLASSIFICATIONS = SAFE_LEAKAGE_CLASSES | PROHIBITED_LEAKAGE_CLASSES
_KT_TO_SAFE_LEAKAGE = {PREGAME_KNOWN: "SAFE_PREGAME", CONDITIONAL_PRE_PA_STATE: "SAFE_CONDITIONAL_PRE_PA",
                       HISTORICAL_AS_OF_CUTOFF: "SAFE_HISTORICAL_AS_OF"}

# Fields that may NEVER appear as a derivation source (post-PA outcome / target / post-score / future).
PROHIBITED_SOURCE_FIELDS = frozenset({
    "outcome", "events", "description", "launch_speed", "launch_angle", "hit_distance",
    "woba_value", "woba_denom", "xwoba", "estimated_woba_using_speedangle", "babip_value", "iso_value",
    "delta_run_exp", "delta_home_win_exp", "delta_win_exp", "post_home_score", "post_away_score",
    "post_bat_score", "final_score", "bat_score_after", "hc_x", "hc_y",
})
# Identifier columns that are join keys, never ordinary numeric predictors.
IDENTIFIER_COLUMNS = frozenset({
    "plate_appearance_id", "pa_id", "row_id", "game_id", "game_pk",
    "batter", "pitcher", "player_id", "batter_canonical_player_uuid", "pitcher_canonical_player_uuid",
})

# Parent lineage the base features derive from (frozen authorities).
_SOURCE_OBJECT_IDS = (GC.PARENT_DATASET_ID,)
_SOURCE_RECEIPT_SHAS = (GC.PARENT_PARTITION_AUTHORITY_SHA, GC.PARENT_BRIDGE_MANIFEST_SHA)


class LeakageError(RuntimeError):
    """A feature / feature-set failed the fail-closed structural leakage validation."""


def _base_derivation_digest() -> str:
    return GC.base_feature_contract()["sha256"]


# ------------------------------------------------------------------ per-feature specification tables
# family -> shared knowledge-time policy
FAMILY_KNOWLEDGE_TIME = {
    "context_pre_pa_state": CONDITIONAL_PRE_PA_STATE,
    "batter_prior_rates": HISTORICAL_AS_OF_CUTOFF,
    "pitcher_prior_rates": HISTORICAL_AS_OF_CUTOFF,
}
_AS_OF_PRE_PA = "state resolved strictly BEFORE the target plate appearance begins (simulator-supplied pre-PA state)"
_AS_OF_PRIOR = "player_prior resolved with prior_season <= target_season - 1 AND eligible_from <= target_season; strictly earlier than the target PA knowledge time"

# featureId -> (displayName, family, canonicalDerivation, sourceColumns, imputationEligible, missingness)
_FEATURE_SPEC: dict[str, tuple[str, str, str, tuple[str, ...], bool, str]] = {
    "context_inning": ("Inning (pre-PA)", "context_pre_pa_state", "regulation/extra inning number in effect before the target PA", ("inning",), False, "always present in a regular-season PA"),
    "context_top_bottom": ("Half-inning (pre-PA)", "context_pre_pa_state", "0=top,1=bottom half in effect before the target PA", ("half_inning",), False, "always present"),
    "context_outs_before": ("Outs before PA", "context_pre_pa_state", "count of outs (0..2) before the target PA", ("outs_when_up",), False, "always present"),
    "context_base_mask_before": ("Base state before PA", "context_pre_pa_state", "3-bit base-occupancy mask (0..7) before the target PA", ("on_1b", "on_2b", "on_3b"), False, "always present"),
    "context_batting_score_diff_before": ("Batting-team score differential (pre-PA)", "context_pre_pa_state", "batting-team score minus fielding-team score before the target PA", ("bat_score", "fld_score"), False, "always present"),
    "batter_log1p_pa": ("Batter prior log1p(PA)", "batter_prior_rates", "log1p of the batter prior-season plate appearances (as-of cutoff)", ("batter_prior_pa",), True, "governed fill + batter_prior_missing indicator when no eligible prior"),
    "batter_avg": ("Batter prior AVG", "batter_prior_rates", "batter prior-season batting average (as-of cutoff)", ("batter_prior_hits", "batter_prior_at_bats"), True, "governed fill + batter_prior_missing when no prior"),
    "batter_obp": ("Batter prior OBP", "batter_prior_rates", "batter prior-season on-base percentage (as-of cutoff)", ("batter_prior_on_base", "batter_prior_pa"), True, "governed fill + batter_prior_missing when no prior"),
    "batter_slg": ("Batter prior SLG", "batter_prior_rates", "batter prior-season slugging (as-of cutoff)", ("batter_prior_total_bases", "batter_prior_at_bats"), True, "governed fill + batter_prior_missing when no prior"),
    "batter_so_per_pa": ("Batter prior SO/PA", "batter_prior_rates", "batter prior-season strikeouts per plate appearance", ("batter_prior_so", "batter_prior_pa"), True, "governed fill + batter_prior_missing when no prior"),
    "batter_bb_hbp_per_pa": ("Batter prior (BB+HBP)/PA", "batter_prior_rates", "batter prior-season walk+hbp per plate appearance", ("batter_prior_bb", "batter_prior_hbp", "batter_prior_pa"), True, "governed fill + batter_prior_missing when no prior"),
    "batter_hr_per_pa": ("Batter prior HR/PA", "batter_prior_rates", "batter prior-season home runs per plate appearance", ("batter_prior_hr", "batter_prior_pa"), True, "governed fill + batter_prior_missing when no prior"),
    "batter_prior_missing": ("Batter prior-missing flag", "batter_prior_rates", "1.0 when no eligible batter prior exists as-of the cutoff, else 0.0", ("batter_prior_season",), False, "the indicator itself; never imputed"),
    "pitcher_log1p_bfp": ("Pitcher prior log1p(BFP)", "pitcher_prior_rates", "log1p of pitcher prior-season batters faced (as-of cutoff)", ("pitcher_prior_bfp",), True, "governed fill + pitcher_prior_missing when no prior"),
    "pitcher_era9": ("Pitcher prior ERA9", "pitcher_prior_rates", "pitcher prior-season earned-run average per 9 (as-of cutoff)", ("pitcher_prior_er", "pitcher_prior_ip"), True, "governed fill + pitcher_prior_missing when no prior"),
    "pitcher_whip": ("Pitcher prior WHIP", "pitcher_prior_rates", "pitcher prior-season walks+hits per inning pitched", ("pitcher_prior_bb", "pitcher_prior_hits", "pitcher_prior_ip"), True, "governed fill + pitcher_prior_missing when no prior"),
    "pitcher_so_per_bfp": ("Pitcher prior SO/BFP", "pitcher_prior_rates", "pitcher prior-season strikeouts per batter faced", ("pitcher_prior_so", "pitcher_prior_bfp"), True, "governed fill + pitcher_prior_missing when no prior"),
    "pitcher_bb_per_bfp": ("Pitcher prior BB/BFP", "pitcher_prior_rates", "pitcher prior-season walks per batter faced", ("pitcher_prior_bb", "pitcher_prior_bfp"), True, "governed fill + pitcher_prior_missing when no prior"),
    "pitcher_hr_per_bfp": ("Pitcher prior HR/BFP", "pitcher_prior_rates", "pitcher prior-season home runs per batter faced", ("pitcher_prior_hr", "pitcher_prior_bfp"), True, "governed fill + pitcher_prior_missing when no prior"),
    "pitcher_hbp_per_bfp": ("Pitcher prior HBP/BFP", "pitcher_prior_rates", "pitcher prior-season hit-by-pitch per batter faced", ("pitcher_prior_hbp", "pitcher_prior_bfp"), True, "governed fill + pitcher_prior_missing when no prior"),
    "pitcher_gs_per_g": ("Pitcher prior GS/G", "pitcher_prior_rates", "pitcher prior-season games-started per game (role proxy)", ("pitcher_prior_gs", "pitcher_prior_g"), True, "governed fill + pitcher_prior_missing when no prior"),
    "pitcher_prior_missing": ("Pitcher prior-missing flag", "pitcher_prior_rates", "1.0 when no eligible pitcher prior exists as-of the cutoff, else 0.0", ("pitcher_prior_season",), False, "the indicator itself; never imputed"),
}


def feature_semantic_contract(feature_id: str) -> dict[str, Any]:
    """Build the immutable semantic contract for one governed base feature (Gate 1)."""
    if feature_id not in _FEATURE_SPEC:
        raise LeakageError(f"no semantic contract is defined for feature {feature_id!r}")
    display, family, derivation, source_cols, impute, missingness = _FEATURE_SPEC[feature_id]
    ktc = FAMILY_KNOWLEDGE_TIME[family]
    as_of = _AS_OF_PRE_PA if ktc == CONDITIONAL_PRE_PA_STATE else _AS_OF_PRIOR
    payload = {
        "contractVersion": SEMANTIC_CONTRACT_VERSION,
        "featureId": feature_id, "featureName": feature_id, "displayName": display,
        "dtype": "float64", "nullable": False, "featureFamilyId": family,
        "sourceObjectIds": list(_SOURCE_OBJECT_IDS), "sourceReceiptShas": list(_SOURCE_RECEIPT_SHAS),
        "sourceColumns": list(source_cols),
        "derivationType": "GOVERNED_FEATURE_VIEW_DERIVATION", "canonicalDerivation": derivation,
        "derivationCodeDigest": _base_derivation_digest(),
        "derivationVersion": "MLB_GEN3_BASE_FEATURE_CONTRACT_V1",
        "grain": "PLATE_APPEARANCE", "knowledgeTimeClass": ktc, "asOfRule": as_of,
        "windowRule": ("pre-PA in-game state (single point in time)" if ktc == CONDITIONAL_PRE_PA_STATE
                       else "full prior-season aggregate as-of the eligibility cutoff"),
        "allowedSeasons": [2021, 2022, 2023, 2024], "availabilityStart": 2021, "availabilityEnd": 2024,
        "missingnessSemantics": missingness, "imputationEligibility": bool(impute),
        "leakageClassification": _KT_TO_SAFE_LEAKAGE[ktc],
        "prohibitedSourceFields": sorted(PROHIBITED_SOURCE_FIELDS),
        "identifierClassification": "NOT_IDENTIFIER",
        "targetRelationshipClassification": "INDEPENDENT_OF_TARGET_PA_OUTCOME",
        "simulatorAvailability": ("SIMULATOR_SUPPLIED_PRE_PA_STATE" if ktc == CONDITIONAL_PRE_PA_STATE
                                  else "PREGAME_PRIOR_RESOLVED"),
        "sourceTerms": "MLB open data (FD1 parent) + Chadwick identity bridge; frozen governed feature-view derivation",
    }
    digest = sha256_bytes(canonical_json_bytes(payload))
    return {"id": f"{SEMANTIC_CONTRACT_VERSION}:{feature_id}:sha256:{digest}", "sha256": digest, "payload": payload}


def all_feature_semantic_contracts() -> dict[str, dict[str, Any]]:
    return {fid: feature_semantic_contract(fid) for fid in FEATURE_NAMES}


def build_semantic_contract(*, feature_id: str, display_name: str, family_id: str, knowledge_time_class: str,
                            as_of_rule: str, source_object_ids: list[str], source_receipt_shas: list[str],
                            source_columns: list[str], canonical_derivation: str, derivation_code_digest: str,
                            derivation_version: str, window_rule: str, allowed_seasons: list[int],
                            missingness_semantics: str = "", imputation_eligibility: bool = True,
                            leakage_classification: str = "SAFE_HISTORICAL_AS_OF",
                            identifier_classification: str = "NOT_IDENTIFIER",
                            target_relationship_classification: str = "INDEPENDENT_OF_TARGET_PA_OUTCOME",
                            dtype: str = "float64", nullable: bool = False,
                            simulator_availability: str = "PREGAME_PRIOR_RESOLVED",
                            source_terms: str = "declared historical fixture",
                            partition_columns: list[str] | None = None, order_columns: list[str] | None = None,
                            derivation_type: str = "DECLARED_DERIVATION") -> dict[str, Any]:
    """Generic immutable semantic-contract constructor (Gate 1) for an advanced/derived feature — used to
    register a scientifically-safe advanced feature (and, in tests, to construct the leaky variants that the
    validator must reject). The record carries the SAME mandatory lineage/derivation/as-of/knowledge-time
    fields as a base feature; nothing is authorized merely because a column exists.

    ``partition_columns`` / ``order_columns`` (Phase 7D.5A) declare grouping/ordering KEYS for a point-in-time
    aggregation feature (e.g. a per-batter count of strictly-earlier PAs). Identity/temporal keys may appear
    there — they determine the aggregation, not the feature's numeric VALUE — but the target / post-PA / future
    prohibition still applies to them, and an identifier may enter ``source_columns`` only when it is also a
    declared partition/order key."""
    payload = {
        "contractVersion": SEMANTIC_CONTRACT_VERSION,
        "featureId": feature_id, "featureName": feature_id, "displayName": display_name,
        "dtype": dtype, "nullable": bool(nullable), "featureFamilyId": family_id,
        "sourceObjectIds": list(source_object_ids), "sourceReceiptShas": list(source_receipt_shas),
        "sourceColumns": list(source_columns),
        "partitionColumns": list(partition_columns or []), "orderColumns": list(order_columns or []),
        "derivationType": derivation_type, "canonicalDerivation": canonical_derivation,
        "derivationCodeDigest": derivation_code_digest, "derivationVersion": derivation_version,
        "grain": "PLATE_APPEARANCE", "knowledgeTimeClass": knowledge_time_class, "asOfRule": as_of_rule,
        "windowRule": window_rule, "allowedSeasons": list(allowed_seasons),
        "availabilityStart": min(allowed_seasons) if allowed_seasons else None,
        "availabilityEnd": max(allowed_seasons) if allowed_seasons else None,
        "missingnessSemantics": missingness_semantics, "imputationEligibility": bool(imputation_eligibility),
        "leakageClassification": leakage_classification,
        "prohibitedSourceFields": sorted(PROHIBITED_SOURCE_FIELDS),
        "identifierClassification": identifier_classification,
        "targetRelationshipClassification": target_relationship_classification,
        "simulatorAvailability": simulator_availability, "sourceTerms": source_terms,
    }
    digest = sha256_bytes(canonical_json_bytes(payload))
    return {"id": f"{SEMANTIC_CONTRACT_VERSION}:{feature_id}:sha256:{digest}", "sha256": digest, "payload": payload}


# ------------------------------------------------------------------ leakage validator (Gate 3)
def validate_feature_semantic_contract(contract: Mapping[str, Any]) -> None:
    """Fail-closed STRUCTURAL validation of one semantic contract. Rejects target / target-derived / post-PA /
    future / identifier features, and any feature with missing lineage / derivation / as-of rule / unknown
    knowledge-time class / a prohibited source field. Never uses statistical correlation."""
    p = contract.get("payload", contract)
    if p.get("contractVersion") != SEMANTIC_CONTRACT_VERSION:
        raise LeakageError("feature semantic contract has the wrong contract version")
    fid = p.get("featureId")
    if not fid or not isinstance(fid, str):
        raise LeakageError("feature semantic contract has no feature id")
    ktc = p.get("knowledgeTimeClass")
    if ktc not in KNOWLEDGE_TIME_CLASSES:
        raise LeakageError(f"unknown knowledge-time class for {fid!r}")
    if ktc in PROHIBITED_PREDICTOR_CLASSES:
        raise LeakageError(f"feature {fid!r} has a prohibited knowledge-time class {ktc}")
    # Gate 2 (B2) — leakageClassification is a strict closed enum; only explicit SAFE classes may be authorized
    lc = p.get("leakageClassification")
    if lc not in LEAKAGE_CLASSIFICATIONS:
        raise LeakageError(f"feature {fid!r} has an unknown/blank leakage classification {lc!r}")
    if lc not in SAFE_LEAKAGE_CLASSES:
        raise LeakageError(f"feature {fid!r} has a prohibited leakage classification {lc}")
    # declared lineage + derivation + as-of are MANDATORY (structural provability)
    if not p.get("sourceObjectIds") or not p.get("sourceReceiptShas"):
        raise LeakageError(f"feature {fid!r} is missing source lineage (object/receipt)")
    if not p.get("sourceColumns"):
        raise LeakageError(f"feature {fid!r} is missing source columns")
    if not p.get("canonicalDerivation") or not p.get("derivationCodeDigest"):
        raise LeakageError(f"feature {fid!r} is missing its derivation identity")
    if not p.get("asOfRule"):
        raise LeakageError(f"feature {fid!r} has no provable as-of rule")
    # target / identifier classifications
    tr = str(p.get("targetRelationshipClassification", ""))
    if tr in ("IS_TARGET", "ENCODED_TARGET", "TARGET_DERIVED_PROXY") or "TARGET" in tr and tr != "INDEPENDENT_OF_TARGET_PA_OUTCOME":
        raise LeakageError(f"feature {fid!r} is target / target-derived")
    if str(p.get("identifierClassification", "")) not in ("NOT_IDENTIFIER", ""):
        raise LeakageError(f"feature {fid!r} is classified as an identifier, not a predictor")
    # the feature itself must not BE the target column or a raw identifier column
    if fid == GC.target_contract()["payload"]["targetColumn"] or fid == "outcome":
        raise LeakageError("the target column may never be authorized as a predictor")
    if fid in IDENTIFIER_COLUMNS:
        raise LeakageError(f"identifier column {fid!r} may never be an ordinary numeric predictor")
    # a prohibited (post-PA/target/future) field may never appear as ANY source/partition/order key
    src = set(str(c) for c in p.get("sourceColumns", []))
    partition = set(str(c) for c in p.get("partitionColumns", []))
    order = set(str(c) for c in p.get("orderColumns", []))
    leaked = (src | partition | order) & PROHIBITED_SOURCE_FIELDS
    if leaked:
        raise LeakageError(f"feature {fid!r} derives from prohibited source field(s): {sorted(leaked)}")
    # an identifier column may enter the derivation ONLY as a declared partition/order key (grouping/ordering),
    # never as a VALUE source (which would encode identity into the numeric feature).
    value_source = src - partition - order
    id_leaked = value_source & IDENTIFIER_COLUMNS
    if id_leaked:
        raise LeakageError(f"feature {fid!r} derives its VALUE from identifier column(s) (not as a partition/order "
                           f"key): {sorted(id_leaked)}")


def validate_registered_feature(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Validate + return the contract (raises LeakageError on any structural leak)."""
    validate_feature_semantic_contract(contract)
    return dict(contract.get("payload", contract))


# ------------------------------------------------------------------ family + feature-set contracts (Gate 2)
def feature_family_contract(family_id: str, ordered_feature_ids: list[str],
                            contracts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """MLB_FEATURE_FAMILY_CONTRACT_V1 — bind a family's ordered feature ids + their contract SHAs under one
    shared knowledge-time policy. Every member is leakage-validated first."""
    if not ordered_feature_ids:
        raise LeakageError(f"feature family {family_id!r} is empty")
    kt_policies = set()
    ordered_ids, ordered_shas = [], []
    for fid in ordered_feature_ids:
        c = contracts[fid]
        validate_feature_semantic_contract(c)
        p = c["payload"]
        if p["featureFamilyId"] != family_id:
            raise LeakageError(f"feature {fid!r} does not belong to family {family_id!r}")
        kt_policies.add(p["knowledgeTimeClass"])
        ordered_ids.append(c["id"]); ordered_shas.append(c["sha256"])
    if len(kt_policies) != 1:
        raise LeakageError(f"family {family_id!r} mixes knowledge-time policies: {sorted(kt_policies)}")
    payload = {
        "contractVersion": FAMILY_CONTRACT_VERSION, "familyId": family_id, "familyName": family_id,
        "orderedFeatureIds": ordered_ids, "orderedFeatureContractShas": ordered_shas,
        "sourceReceiptShas": list(_SOURCE_RECEIPT_SHAS), "sharedKnowledgeTimeClass": next(iter(kt_policies)),
        "derivationVersion": "MLB_GEN3_BASE_FEATURE_CONTRACT_V1", "featureCount": len(ordered_ids),
    }
    digest = sha256_bytes(canonical_json_bytes(payload))
    return {"id": f"{FAMILY_CONTRACT_VERSION}:{family_id}:sha256:{digest}", "sha256": digest, "payload": payload}


def feature_set_contract_v2(*, dataset_version_id: str, dataset_content_sha: str,
                            ordered_base_feature_ids: list[str], optional_family_ids: list[str],
                            final_ordered_feature_ids: list[str],
                            contracts: Mapping[str, Mapping[str, Any]], name: str = "base") -> dict[str, Any]:
    """MLB_FEATURE_SET_CONTRACT_V2 — bind the exact final ordered feature ids + their contract SHAs, the base
    ids, the optional family ids, and the target contract. Every feature is leakage-validated; duplicates and
    unknown features are rejected."""
    if len(final_ordered_feature_ids) != len(set(final_ordered_feature_ids)):
        raise LeakageError("feature set has duplicate features")
    final_shas = []
    for fid in final_ordered_feature_ids:
        if fid not in contracts:
            raise LeakageError(f"feature {fid!r} in the set has no registered semantic contract")
        validate_feature_semantic_contract(contracts[fid])
        final_shas.append(contracts[fid]["sha256"])
    payload = {
        "contractVersion": FEATURE_SET_CONTRACT_VERSION, "name": name,
        "datasetId": GC.PARENT_DATASET_ID, "datasetVersionId": dataset_version_id,
        "datasetContentSha256": dataset_content_sha,
        "orderedBaseFeatureIds": list(ordered_base_feature_ids), "orderedOptionalFamilyIds": list(optional_family_ids),
        "exactFinalOrderedFeatureIds": list(final_ordered_feature_ids), "exactFinalFeatureContractShas": final_shas,
        "targetContractId": GC.target_contract()["id"], "targetContractSha256": GC.target_contract()["sha256"],
        "knowledgeTimeCompatible": True, "featureCount": len(final_ordered_feature_ids),
    }
    digest = sha256_bytes(canonical_json_bytes(payload))
    return {"id": f"{FEATURE_SET_CONTRACT_VERSION}:{name}:sha256:{digest}", "sha256": digest, "payload": payload}


# ------------------------------------------------------------------ the canonical governed base authority
BASE_FAMILY_ORDER = ("context_pre_pa_state", "batter_prior_rates", "pitcher_prior_rates")
_FAMILY_MEMBERS = {
    "context_pre_pa_state": list(CONTEXT_FEATURES),
    "batter_prior_rates": list(BATTER_FEATURES),
    "pitcher_prior_rates": list(PITCHER_FEATURES),
}


def base_family_contracts() -> dict[str, dict[str, Any]]:
    contracts = all_feature_semantic_contracts()
    return {fam: feature_family_contract(fam, _FAMILY_MEMBERS[fam], contracts) for fam in BASE_FAMILY_ORDER}


def base_feature_set_contract(*, dataset_version_id: str, dataset_content_sha: str) -> dict[str, Any]:
    """The governed base feature set (22 features) as a V2 contract for a registered dataset version."""
    contracts = all_feature_semantic_contracts()
    return feature_set_contract_v2(
        dataset_version_id=dataset_version_id, dataset_content_sha=dataset_content_sha,
        ordered_base_feature_ids=list(FEATURE_NAMES), optional_family_ids=[],
        final_ordered_feature_ids=list(FEATURE_NAMES), contracts=contracts, name="base")
