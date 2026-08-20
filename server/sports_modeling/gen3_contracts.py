"""Canonical, versioned, content-digested Gen-3 contracts (Phase 7A Gate 1).

Each contract is a deterministic canonical-JSON payload with a SHA-256 digest. They are validated
before materialization/execution and embedded (by digest) in every child artifact (feature-view
manifest, quarantine ledger, run authority). This replaces the Phase-7 "documentation label"
temporal contract with registered executable authority.
"""

from __future__ import annotations

from typing import Any

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from .feature_contract import (
    BATTER_FEATURES,
    CONTEXT_FEATURES,
    FEATURE_NAMES,
    PITCHER_FEATURES,
)
from .metrics import PA_CLASS_ORDER

# Parent authorities (frozen; verified by the builder before reading partitions).
PARENT_DATASET_ID = "asp.mlb.open-data.fd1"
PARENT_PARTITION_AUTHORITY_SHA = "8dec143b06622af068665b9fd1ad419a0353e76f0e0083b4c3459b8fce3cb437"
PARENT_BRIDGE_MANIFEST_SHA = "6b69e7dcf4c5db7615420ee9f6f6f797b0335e31ab475646291f3a4cf90c52cf"

GEN3_PRIOR_HISTORY_SEASONS = (2019, 2020)   # registered source history before each target season (not materialized here)
GEN3_DEVELOPMENT_SEASONS = (2021, 2022, 2023)
GEN3_VALIDATION_SEASON = 2024
GEN3_SEALED_SECONDARY_OOT_SEASON = 2025
GEN3_PROSPECTIVE_SEALED_SEASON = 2026
GEN3_RESEARCH_SEASONS = (2021, 2022, 2023, 2024)  # the physically-blinded default research frame


def _contract(name: str, semantic_version: str, body: dict[str, Any]) -> dict[str, Any]:
    payload = {"contract": name, "semanticVersion": semantic_version, **body}
    digest = sha256_bytes(canonical_json_bytes(payload))
    return {"id": f"{name}:sha256:{digest}", "sha256": digest, "payload": payload}


def target_contract() -> dict[str, Any]:
    return _contract("MLB_GEN3_TARGET_CONTRACT_V1", "1.0.0", {
        "targetColumn": "outcome",
        "classOrder": list(PA_CLASS_ORDER),
        "problemType": "MULTICLASS_CLASSIFICATION",
        "exclusions": ["no post-outcome / target-derived column may enter the predictor set"],
    })


def feature_schema_contract() -> dict[str, Any]:
    return _contract("MLB_GEN3_FEATURE_SCHEMA_V2", "2.0.0", {
        "predecessor": "MLB_PA_FEATURE_SCHEMA_V1",
        "change": "context_inning admits legitimate regulation+extra innings 1..16 (Gen-2 V1 capped at 14)",
        "contextInningMin": 1, "contextInningMax": 16,
        "identityColumns": ["plate_appearance_id", "game_id", "game_date", "season",
                            "batter_canonical_player_uuid", "pitcher_canonical_player_uuid"],
        "targetColumn": "outcome",
        "featureColumns": list(FEATURE_NAMES),
    })


def base_feature_contract() -> dict[str, Any]:
    return _contract("MLB_GEN3_BASE_FEATURE_CONTRACT_V1", "1.0.0", {
        "contextFeatures": list(CONTEXT_FEATURES),
        "batterFeatures": list(BATTER_FEATURES),
        "pitcherFeatures": list(PITCHER_FEATURES),
        "featureCount": len(FEATURE_NAMES),
        "derivation": "identical per-row math to the frozen Gen-2 build (feature_view helpers reused)",
    })


def knowledge_time_contract() -> dict[str, Any]:
    return _contract("MLB_GEN3_KNOWLEDGE_TIME_CONTRACT_V1", "1.0.0", {
        "rule": "pregame -> final; every feature must use only information known before the scheduled start of the target game",
        "priorEligibility": "player_prior for target season S resolves latest row with prior_season <= S-1 and eligible_from <= S; strict < knowledge_time",
        "priorBlind2021": "no <=2020 player_prior exists -> all 2021 target PAs are prior-blind (surfaced via *_prior_missing)",
        "prohibited": ["same-game events", "launch_speed/angle", "woba/babip/iso value",
                       "delta_run_exp", "final score", "actual PA count", "post scores"],
    })


def temporal_contract() -> dict[str, Any]:
    return _contract("MLB_GEN3_TEMPORAL_CONTRACT_V1", "1.0.0", {
        "priorHistory": list(GEN3_PRIOR_HISTORY_SEASONS),
        "development": list(GEN3_DEVELOPMENT_SEASONS),
        "validationSelection": GEN3_VALIDATION_SEASON,
        "sealedSecondaryOot": GEN3_SEALED_SECONDARY_OOT_SEASON,
        "prospectiveSealed": GEN3_PROSPECTIVE_SEALED_SEASON,
        "researchFrameSeasons": list(GEN3_RESEARCH_SEASONS),
        "invariants": ["2025 never a development/tuning/selection fold",
                       "2025 not loaded into the default research frame (physical blinding)",
                       "2026 untouched"],
    })


def preprocessing_contract() -> dict[str, Any]:
    """The GOVERNED Gen-2 preprocessing policy (FoldPreprocessor): mean impute + standardization,
    fit on training rows of the fit only; one-hot for the 3 categorical context features."""
    return _contract("MLB_GEN3_PREPROCESSING_CONTRACT_V1", "1.0.0", {
        "numericImputation": "FOLD_TRAINING_ONLY_MEAN_WITH_EMPTY_COLUMN_ZERO_GUARD",
        "numericScaling": "STANDARDIZE_ZERO_MEAN_UNIT_STD_DDOF0",
        "categoricalEncoding": {"context_top_bottom": [0, 1], "context_outs_before": [0, 1, 2],
                                "context_base_mask_before": list(range(8))},
        "imputationScope": "TRAINING_ROWS_OF_THIS_FIT_ONLY",
        "authority": "server.sports_modeling.training.FoldPreprocessor",
    })


def population_contract() -> dict[str, Any]:
    return _contract("MLB_GEN3_POPULATION_CONTRACT_V1", "1.0.0", {
        "acceptedPopulations": ["GEN2_PRIMARY_2023_2025", "GEN2_PRIOR_ONLY_2021_2022"],
        "requiredStrictPopulation": "GEN2_STRICT_DEPLOYABLE_RECONSTRUCTION",
        "regularSeasonScope": "regular season target PAs only",
        "quarantineReasons": {
            "BATTING_TEAM_CONVENTION_ANOMALY": "batting_team_id conflicts with the home/visitor-by-half convention used for score_difference; fail-closed until the exact semantics are resolved by source evidence",
        },
        "includedNow": "legitimate innings 15-16 are INCLUDED under MLB_GEN3_FEATURE_SCHEMA_V2 (no longer quarantined)",
        "exclusionRule": "no outcome- or metric-dependent exclusion; all quarantine predicates are structural and outcome-independent",
    })


def all_contracts() -> dict[str, dict[str, Any]]:
    return {
        "target": target_contract(),
        "featureSchema": feature_schema_contract(),
        "baseFeature": base_feature_contract(),
        "knowledgeTime": knowledge_time_contract(),
        "temporal": temporal_contract(),
        "preprocessing": preprocessing_contract(),
        "population": population_contract(),
    }


def contract_digests() -> dict[str, str]:
    return {name: c["sha256"] for name, c in all_contracts().items()}


def contract_bundle_sha() -> str:
    """A single digest over the full ordered contract set — the Gen-3 authority fingerprint."""
    return sha256_bytes(canonical_json_bytes({name: c["sha256"] for name, c in sorted(all_contracts().items())}))
