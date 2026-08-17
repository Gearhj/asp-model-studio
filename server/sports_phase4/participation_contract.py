from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from server.sports_datasets.constants import MANIFEST_SHA, PARTITION_AUTHORITY_SHA
from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_identity_bridges.constants import (
    ALIAS_AUTHORITY_SHA,
    BRIDGE_MANIFEST_SHA,
    DIMENSION_AUTHORITY_SHA,
)
from server.sports_phase4.dynamic_contract import (
    CONTRACT_NAME as DYNAMIC_CONTRACT_NAME,
    HISTORY_INDEX_DESCRIPTOR_SCHEMA_VERSION,
    LOG_ODDS_CLASSES,
    dynamic_history_index_schema_sha,
    dynamic_state_contract_sha,
    dynamic_state_contract_payload,
    dynamic_state_schema_sha,
)


LINEUP_CONTRACT_NAME = "MLB_LINEUP_PROJECTION_V1"
LINEUP_CONTRACT_VERSION = "MLB_LINEUP_PROJECTION_V1"
STARTER_CONTRACT_NAME = "MLB_STARTER_DURATION_V1"
STARTER_CONTRACT_VERSION = "MLB_STARTER_DURATION_V1"
BULLPEN_CONTRACT_NAME = "MLB_BULLPEN_USAGE_V1"
BULLPEN_CONTRACT_VERSION = "MLB_BULLPEN_USAGE_V1"

CONTRACT_SCHEMA_VERSION = "MLB_PARTICIPATION_CONTRACT_SET_V1"
DYNAMIC_CONTRACT_ID = DYNAMIC_CONTRACT_NAME
DYNAMIC_CONTRACT_SHA = dynamic_state_contract_sha()
DYNAMIC_SCHEMA_SHA = dynamic_state_schema_sha()
DYNAMIC_LOGICAL_URI_PREFIX = (
    "asp-model-studio-runtime://sports-phase4/mlb-dynamic-player-state-v1/"
)
PARTICIPATION_SCHEMA_VERSION = "MLB_PARTICIPATION_USAGE_V1"
TARGET_SEASONS: tuple[int, ...] = (2023, 2024, 2025)
HISTORY_SEASONS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)
INNER_TUNING_SEASON = 2023
SELECTION_SEASON = 2024
FINAL_EVALUATION_SEASON = 2025
EARLY_SEASON_DAYS = 45
LINEUP_TRAILING_POOL_DAYS = 45
BULLPEN_TRAILING_POOL_DAYS = 30
ACCEPTABLE_POOL_COVERAGE = 0.95
DECISION_TOLERANCE = 1e-10
RANDOM_SEED = 20_260_817
COMPONENT_CHECKPOINT_SCHEMA_VERSION = "MLB_PARTICIPATION_COMPONENT_CHECKPOINT_V1"
COMPONENT_CHECKPOINT_ARTIFACT_TYPE = "COMPONENT_CHECKPOINT"
BLOCKED_FAILURE_CODE = "COMPONENT_MODELING_FAILURE"
BLOCKED_STAGES: tuple[str, ...] = (
    "LINEUP_FIT",
    "LINEUP_EVALUATION",
    "STARTER_FIT",
    "STARTER_EVALUATION",
    "BULLPEN_FIT",
    "BULLPEN_EVALUATION",
)
COMPONENT_CHECKPOINT_FILENAMES: Mapping[str, str] = {
    "LINEUP_PROJECTION": "lineup_projection-component-checkpoint.json",
    "STARTER_DURATION": "starter_duration-component-checkpoint.json",
    "BULLPEN_USAGE": "bullpen_usage-component-checkpoint.json",
}

LOGISTIC_C_GRID: tuple[float, ...] = (0.05, 0.2, 1.0)
RIDGE_ALPHA_GRID: tuple[float, ...] = (0.1, 1.0, 10.0)
DEFAULT_MAX_ITER = 2_000
DEFAULT_TOLERANCE = 1e-7
HGB_MAX_ITER = 100
HGB_MAX_DEPTH = 4
HGB_LEARNING_RATE = 0.05

LINEUP_DECISION_ENUM: tuple[str, ...] = (
    "LINEUP_RESEARCH_COMPONENT",
    "LINEUP_RESEARCH_BASELINE",
    "LINEUP_REJECTED",
    "LINEUP_BLOCKED",
)
STARTER_DECISION_ENUM: tuple[str, ...] = (
    "STARTER_DURATION_RESEARCH_COMPONENT",
    "STARTER_DURATION_RESEARCH_BASELINE",
    "STARTER_DURATION_REJECTED",
    "STARTER_DURATION_BLOCKED",
)
BULLPEN_DECISION_ENUM: tuple[str, ...] = (
    "BULLPEN_USAGE_RESEARCH_COMPONENT",
    "BULLPEN_USAGE_RESEARCH_BASELINE",
    "BULLPEN_USAGE_REJECTED",
    "BULLPEN_USAGE_BLOCKED",
)

LINEUP_FEATURES: tuple[str, ...] = (
    "prior_starts_7d",
    "prior_starts_14d",
    "prior_starts_30d",
    "prior_appearances_7d",
    "prior_appearances_14d",
    "prior_appearances_30d",
    "prior_pa_7d",
    "prior_pa_14d",
    "prior_pa_30d",
    "days_since_appearance",
    "days_since_start",
    "season_start_rate",
    "trailing_order_mean",
    "trailing_order_mode",
    "prior_season_participation",
    "early_season_indicator",
    "dynamic_batter_availability",
    "dynamic_batter_ess",
)

DYNAMIC_PITCHER_LOG_ODDS_FEATURES: tuple[str, ...] = tuple(
    f"dynamic_pitcher_log_odds_{class_name.casefold()}" for class_name in LOG_ODDS_CLASSES
)

STARTER_FEATURES: tuple[str, ...] = (
    "prior_starts_7d",
    "prior_starts_14d",
    "prior_starts_30d",
    "prior_bfp_7d",
    "prior_bfp_14d",
    "prior_bfp_30d",
    "prior_outs_7d",
    "prior_outs_14d",
    "prior_outs_30d",
    "previous_start_bfp",
    "previous_start_outs",
    "trailing_3_start_mean_bfp",
    "trailing_3_start_mean_outs",
    "trailing_5_start_mean_bfp",
    "trailing_5_start_mean_outs",
    "team_prior_date_mean_bfp",
    "team_prior_date_mean_outs",
    "starts_previous_30d",
    "days_rest",
    "season_to_date_start_count",
    "season_to_date_mean_bfp",
    "season_to_date_mean_outs",
    "prior_season_bfp",
    "prior_season_outs",
    "early_season_indicator",
    *DYNAMIC_PITCHER_LOG_ODDS_FEATURES,
    "dynamic_pitcher_missing_history",
    "dynamic_pitcher_ess",
)

BULLPEN_FEATURES: tuple[str, ...] = (
    "appearances_3d",
    "appearances_7d",
    "appearances_14d",
    "prior_bfp_1d",
    "prior_bfp_3d",
    "prior_bfp_7d",
    "prior_bfp_14d",
    "prior_outs_1d",
    "prior_outs_3d",
    "prior_outs_7d",
    "prior_outs_14d",
    "days_since_relief",
    "appeared_yesterday",
    "appeared_on_two_consecutive_prior_days",
    "season_appearance_count",
    "season_relief_share",
    "season_bfp",
    "season_outs",
    "prior_team_usage_rate",
    "prior_season_relief",
    "early_season_indicator",
    *DYNAMIC_PITCHER_LOG_ODDS_FEATURES,
    "dynamic_pitcher_missing_history",
    "dynamic_pitcher_ess",
)

LINEUP_CANDIDATES: Mapping[str, Mapping[str, Any]] = {
    "L0": {
        "displayName": "Trailing start-frequency baseline",
        "estimator": "TRAILING_START_FREQUENCY",
        "features": (),
        "optional": False,
    },
    "L1": {
        "displayName": "Regularized lineup logistic",
        "estimator": "SKLEARN_LOGISTIC_L2",
        "features": LINEUP_FEATURES,
        "optional": False,
    },
    "L2": {
        "displayName": "Bounded histogram-gradient lineup challenger",
        "estimator": "SKLEARN_HIST_GRADIENT_BOOSTING",
        "features": LINEUP_FEATURES,
        "optional": True,
    },
}

STARTER_CANDIDATES: Mapping[str, Mapping[str, Any]] = {
    "S0": {
        "displayName": "Global training duration mean and median",
        "estimator": "GLOBAL_TRAINING_LOCATION",
        "features": (),
        "optional": False,
    },
    "S1": {
        "displayName": "Pitcher rolling duration baseline",
        "estimator": "PITCHER_ROLLING_LOCATION",
        "features": (),
        "optional": False,
    },
    "S2": {
        "displayName": "Regularized linear duration model",
        "estimator": "SKLEARN_RIDGE",
        "features": STARTER_FEATURES,
        "optional": False,
    },
    "S3": {
        "displayName": "Bounded histogram-gradient duration challenger",
        "estimator": "SKLEARN_HIST_GRADIENT_BOOSTING",
        "features": STARTER_FEATURES,
        "optional": True,
    },
}

BULLPEN_CANDIDATES: Mapping[str, Mapping[str, Any]] = {
    "B0": {
        "displayName": "Prior recency/workload heuristic",
        "estimator": "RECENCY_WORKLOAD_HEURISTIC",
        "features": (),
        "optional": False,
    },
    "B1": {
        "displayName": "Regularized bullpen-appearance logistic",
        "estimator": "SKLEARN_LOGISTIC_L2",
        "features": BULLPEN_FEATURES,
        "optional": False,
    },
    "B2": {
        "displayName": "Bounded histogram-gradient bullpen challenger",
        "estimator": "SKLEARN_HIST_GRADIENT_BOOSTING",
        "features": BULLPEN_FEATURES,
        "optional": True,
    },
}

_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_PHASE3_RUN_RE = re.compile(r"sports-pa-research-run:sha256:[0-9a-f]{64}\Z")
_JOIN_AUDIT_RE = re.compile(r"sports-identity-join-audit:sha256:[0-9a-f]{64}\Z")


class ParticipationContractError(ValueError):
    """Raised when Milestone B evidence differs from the frozen contract."""


def canonical_sha(payload: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(payload)))


def _candidate_payload(candidates: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {
        candidate_id: {
            "displayName": str(config["displayName"]),
            "estimator": str(config["estimator"]),
            "featureNames": list(config["features"]),
            "optional": bool(config["optional"]),
        }
        for candidate_id, config in candidates.items()
    }


def _common_contract(component: str, contract_name: str, contract_version: str) -> dict[str, Any]:
    return {
        "contractName": contract_name,
        "contractVersion": contract_version,
        "semanticVersion": "1.0.0",
        "component": component,
        "historySeasons": list(HISTORY_SEASONS),
        "targetSeasons": list(TARGET_SEASONS),
        "temporalPolicy": {
            "sourceField": "final_available_date",
            "targetField": "game_date",
            "eligibilityPredicate": "source.final_available_date < target.game_date",
            "sameDateEvidenceExcluded": True,
            "doubleheaderSameDateEvidenceExcluded": True,
            "currentTargetParticipantInjectionProhibited": True,
            "idsAreGroupingAndLineageOnly": True,
        },
        "foldPolicy": {
            "innerTuningSeason": INNER_TUNING_SEASON,
            "innerSplit": "DATE_ATOMIC_CHRONOLOGICAL",
            "selectionTrainingSeasons": [2023],
            "selectionSeason": SELECTION_SEASON,
            "finalTrainingSeasons": [2023, 2024],
            "finalEvaluationSeason": FINAL_EVALUATION_SEASON,
            "finalEvaluationMayNotAffectSelection": True,
        },
        "dynamicStatePolicy": {
            "requiredLiveContract": DYNAMIC_CONTRACT_ID,
            "liveBindingRequired": True,
            "fixtureOnlyMissingInputPermitted": True,
            "identityKey": ["game_date", "canonical_player_uuid", "role"],
            "requiredUpstreamBindings": ["historyIndex", "dynamicComponentId"],
        },
        "decisionPolicy": {
            "acceptableCoverageThreshold": ACCEPTABLE_POOL_COVERAGE,
            "componentRequiresImprovementInBoth2024And2025": True,
            "mixedValidEvidence": "BASELINE",
            "consistentlyWorse": "REJECTED",
            "integrityFailure": "BLOCKED",
            "rosterCoverageLimitationAloneIsNotBlocked": True,
        },
        "researchOnly": True,
        "deploymentAuthorized": False,
    }


def lineup_contract_payload() -> dict[str, Any]:
    payload = _common_contract("LINEUP_PROJECTION", LINEUP_CONTRACT_NAME, LINEUP_CONTRACT_VERSION)
    payload.update(
        {
            "schemaVersion": CONTRACT_SCHEMA_VERSION,
            "target": {
                "family": "player_game_batting",
                "fields": ["actual_starting_lineup", "actual_batting_order"],
                "grain": ["game_id", "team_id", "canonical_player_uuid"],
                "targetOnly": True,
            },
            "candidatePool": {
                "union": [
                    "current-season prior team appearances",
                    f"trailing {LINEUP_TRAILING_POOL_DAYS}-day prior team participation",
                    f"prior-season team participation during first {EARLY_SEASON_DAYS} season days",
                ],
                "uncoveredPositivesMeasured": True,
                "lackOfRosterFeed": "EXPLICIT_COVERAGE_AND_PROSPECTIVE_LIMITATION",
            },
            "featureNames": list(LINEUP_FEATURES),
            "candidates": _candidate_payload(LINEUP_CANDIDATES),
            "orderEstimator": {
                "model": "DETERMINISTIC_PROBABILITY_WEIGHTED_HISTORICAL_ORDER",
                "selectionSize": 9,
                "targetField": "actual_batting_order",
            },
            "metrics": [
                "poolCoverage",
                "uncoveredPositiveCount",
                "binaryLogLoss",
                "brierScore",
                "averagePrecision",
                "top9Recall",
                "topNinePrecision",
                "topNineF1",
                "completeLineupRate",
                "completeLineupRecoveryRate",
                "exactLineupRate",
                "exactOrderRate",
                "battingOrderMae",
                "exactBattingPositionRate",
                "earlySeasonTop9Recall",
                "laterSeasonTop9Recall",
                "stratifiedMetrics",
            ],
            "decisionPolicy": {
                "enum": list(LINEUP_DECISION_ENUM),
                "componentRequires": "selected improves against L0 in both frozen folds with acceptable candidate-pool coverage",
            },
        }
    )
    return payload


def starter_contract_payload() -> dict[str, Any]:
    payload = _common_contract("STARTER_DURATION", STARTER_CONTRACT_NAME, STARTER_CONTRACT_VERSION)
    payload.update(
        {
            "schemaVersion": CONTRACT_SCHEMA_VERSION,
            "conditioning": "CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY",
            "target": {
                "family": "starter_usage",
                "identityField": "actual_starter_target",
                "primaryField": "stat_p_bfp",
                "secondaryField": "stat_p_ipouts",
                "targetOnly": True,
            },
            "featureNames": list(STARTER_FEATURES),
            "candidates": _candidate_payload(STARTER_CANDIDATES),
            "inningReachThresholdOuts": [15, 18, 21],
            "inningReachEstimator": "BOUNDED_LOGISTIC_L2",
            "metrics": [
                "bfpMae",
                "bfpRmse",
                "bfpMedianAbsoluteError",
                "outsMae",
                "outsRmse",
                "outsMedianAbsoluteError",
                "reach15LogLoss",
                "reach18LogLoss",
                "reach21LogLoss",
                "reach15Brier",
                "reach18Brier",
                "reach21Brier",
                "earlySeasonBfpMae",
                "priorStartHistoryCoverage",
                "historyStratifiedMetrics",
            ],
            "decisionPolicy": {
                "enum": list(STARTER_DECISION_ENUM),
                "componentRequires": "selected improves BFP MAE and RMSE against both S0 and S1 in both frozen folds",
            },
        }
    )
    return payload


def bullpen_contract_payload() -> dict[str, Any]:
    payload = _common_contract("BULLPEN_USAGE", BULLPEN_CONTRACT_NAME, BULLPEN_CONTRACT_VERSION)
    payload.update(
        {
            "schemaVersion": CONTRACT_SCHEMA_VERSION,
            "target": {
                "family": "bullpen_usage",
                "field": "actual_appearance_target",
                "durationFields": ["stat_p_bfp", "stat_p_ipouts"],
                "targetOnly": True,
                "zeroRelieverTeamGamesRequired": True,
            },
            "candidatePool": {
                "union": [
                    "current-season prior team relief appearances",
                    f"trailing {BULLPEN_TRAILING_POOL_DAYS}-day prior team relief appearances",
                    f"prior-season team relief appearances during first {EARLY_SEASON_DAYS} season days",
                ],
                "uncoveredPositivesMeasured": True,
                "lackOfRosterFeed": "EXPLICIT_COVERAGE_AND_PROSPECTIVE_LIMITATION",
            },
            "featureNames": list(BULLPEN_FEATURES),
            "candidates": _candidate_payload(BULLPEN_CANDIDATES),
            "metrics": [
                "poolCoverage",
                "uncoveredPositiveCount",
                "binaryLogLoss",
                "brierScore",
                "averagePrecision",
                "teamGameSetRecall",
                "teamGameSetJaccard",
                "top3Recall",
                "top5Recall",
                "relieverCountMae",
                "expectedRelieverCountMae",
                "zeroRelieverAccuracy",
                "conditionalBfpMae",
                "conditionalOutsMae",
                "earlySeasonSetRecall",
                "recentUseStratifiedMetrics",
            ],
            "decisionPolicy": {
                "enum": list(BULLPEN_DECISION_ENUM),
                "componentRequires": {
                    "rawLogLoss": "strictly better than B0 in both folds",
                    "rawBrier": "non-worse than B0 in both folds within 1e-10",
                    "rawTargetAppearanceEceMaximum": 0.05,
                    "topLabelCalibration": "SECONDARY_NON_GOVERNING_EVIDENCE",
                    "reliabilityBins": "all ten registered bins finite and nonempty in both folds",
                    "poolCoverageMinimum": ACCEPTABLE_POOL_COVERAGE,
                },
            },
        }
    )
    return payload


def contract_set_payload() -> dict[str, Any]:
    return {
        "schemaVersion": CONTRACT_SCHEMA_VERSION,
        "contracts": {
            "lineup": lineup_contract_payload(),
            "starter": starter_contract_payload(),
            "bullpen": bullpen_contract_payload(),
        },
    }


def contract_set_sha() -> str:
    return canonical_sha(contract_set_payload())


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise ParticipationContractError(f"{label} must be a lowercase SHA-256")
    return value


def _required_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ParticipationContractError(f"{label} must be an object")
    return value


def validate_dynamic_descriptor(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and freeze the external Milestone A trust anchors without importing it."""

    descriptor = _required_mapping(descriptor, "dynamic-state descriptor")
    required = {
        "contractName",
        "contractSha",
        "schemaSha",
        "contentSha",
        "artifactSha",
        "artifactBytes",
        "logicalUri",
        "parent",
        "identityBridge",
        "phase3",
        "selectedPolicy",
        "historyIndex",
        "dynamicComponentId",
    }
    missing = sorted(required - set(descriptor))
    if missing:
        raise ParticipationContractError(
            f"dynamic-state descriptor is missing required fields: {missing}"
        )
    if descriptor["contractName"] != DYNAMIC_CONTRACT_ID:
        raise ParticipationContractError("dynamic-state contractName differs")
    for key in ("contractSha", "schemaSha", "contentSha", "artifactSha"):
        _require_sha(descriptor[key], f"dynamic-state {key}")
    if descriptor["contractSha"] != DYNAMIC_CONTRACT_SHA:
        raise ParticipationContractError("dynamic-state contractSha differs")
    if descriptor["schemaSha"] != DYNAMIC_SCHEMA_SHA:
        raise ParticipationContractError("dynamic-state schemaSha differs")
    if type(descriptor["artifactBytes"]) is not int or descriptor["artifactBytes"] <= 0:
        raise ParticipationContractError("dynamic-state artifactBytes must be positive")
    logical_uri = descriptor["logicalUri"]
    artifact_sha = descriptor["artifactSha"]
    expected_prefix = f"{DYNAMIC_LOGICAL_URI_PREFIX}objects/sha256/{artifact_sha[:2]}/{artifact_sha}/"
    if not isinstance(logical_uri, str) or not logical_uri.startswith(expected_prefix):
        raise ParticipationContractError("dynamic-state logicalUri is outside the governed namespace")
    selected_policy = _required_mapping(
        descriptor["selectedPolicy"], "dynamic-state selectedPolicy"
    )
    if not isinstance(selected_policy.get("policyId"), str) or not selected_policy["policyId"]:
        raise ParticipationContractError("dynamic-state selectedPolicyId is required")
    history_index = _required_mapping(
        descriptor["historyIndex"], "dynamic-state historyIndex"
    )
    required_history_keys = {
        "schemaVersion",
        "contractName",
        "contractSha",
        "schemaSha",
        "contentSha",
        "artifactId",
        "artifactSha",
        "artifactBytes",
        "logicalUri",
        "mediaType",
        "rowCount",
        "sourceRowCount",
        "resolvedReferenceCount",
        "sourcePartitionIds",
        "authorityBindings",
    }
    if set(history_index) != required_history_keys:
        raise ParticipationContractError("dynamic-state historyIndex fields differ")
    for key in ("contractSha", "schemaSha", "contentSha", "artifactSha"):
        _require_sha(history_index.get(key), f"dynamic-state historyIndex.{key}")
    history_sha = history_index["artifactSha"]
    if (
        history_index.get("schemaVersion") != HISTORY_INDEX_DESCRIPTOR_SCHEMA_VERSION
        or history_index.get("contractName") != DYNAMIC_CONTRACT_NAME
        or history_index.get("contractSha") != DYNAMIC_CONTRACT_SHA
        or history_index.get("schemaSha") != dynamic_history_index_schema_sha()
        or history_index.get("mediaType") != "application/vnd.apache.parquet"
        or history_index.get("artifactId")
        != f"sports-phase4-artifact:dynamic_history_index:sha256:{history_sha}"
        or not isinstance(history_index.get("logicalUri"), str)
        or not history_index["logicalUri"].startswith(
            f"{DYNAMIC_LOGICAL_URI_PREFIX}objects/sha256/{history_sha[:2]}/{history_sha}/"
        )
        or history_index.get("authorityBindings")
        != {
            "dataset": dynamic_state_contract_payload()["authorityBindings"]["dataset"],
            "identityBridge": dynamic_state_contract_payload()["authorityBindings"]["identityBridge"],
        }
    ):
        raise ParticipationContractError("dynamic-state historyIndex authority differs")
    for key in ("artifactBytes", "rowCount", "sourceRowCount", "resolvedReferenceCount"):
        if type(history_index.get(key)) is not int or history_index[key] <= 0:
            raise ParticipationContractError(f"dynamic-state historyIndex.{key} differs")
    if history_index["resolvedReferenceCount"] != 2 * history_index["sourceRowCount"]:
        raise ParticipationContractError("dynamic-state historyIndex counts do not reconcile")
    partition_ids = history_index.get("sourcePartitionIds")
    if (
        not isinstance(partition_ids, list)
        or not partition_ids
        or partition_ids != sorted(set(partition_ids))
        or any(not isinstance(value, str) or not value for value in partition_ids)
    ):
        raise ParticipationContractError("dynamic-state historyIndex partitions differ")
    dynamic_component_id = descriptor["dynamicComponentId"]
    if (
        not isinstance(dynamic_component_id, str)
        or re.fullmatch(
            r"sports-phase4-component:dynamic-player-state:sha256:[0-9a-f]{64}",
            dynamic_component_id,
        )
        is None
    ):
        raise ParticipationContractError("dynamic-state dynamicComponentId differs")

    frozen_authorities = dynamic_state_contract_payload()["authorityBindings"]
    parent = _required_mapping(descriptor["parent"], "dynamic-state parent")
    bridge = _required_mapping(descriptor["identityBridge"], "dynamic-state identityBridge")
    phase3 = _required_mapping(descriptor["phase3"], "dynamic-state phase3")
    if dict(parent) != frozen_authorities["dataset"]:
        raise ParticipationContractError("dynamic-state parent authority differs")
    if dict(bridge) != frozen_authorities["identityBridge"]:
        raise ParticipationContractError("dynamic-state identity-bridge authority differs")
    if dict(phase3) != frozen_authorities["phase3"]:
        raise ParticipationContractError("dynamic-state Phase 3 authority differs")
    normalized = dict(descriptor)
    normalized["selectedPolicyId"] = selected_policy["policyId"]
    return normalized


@dataclass(frozen=True)
class LineupDecisionEvidence:
    improvement_2024: float
    improvement_2025: float
    coverage_2024: float
    coverage_2025: float
    integrity_failure: str | None = None


@dataclass(frozen=True)
class StarterDecisionEvidence:
    bfp_mae_vs_s0_2024: float
    bfp_rmse_vs_s0_2024: float
    bfp_mae_vs_s1_2024: float
    bfp_rmse_vs_s1_2024: float
    bfp_mae_vs_s0_2025: float
    bfp_rmse_vs_s0_2025: float
    bfp_mae_vs_s1_2025: float
    bfp_rmse_vs_s1_2025: float
    integrity_failure: str | None = None


@dataclass(frozen=True)
class BullpenDecisionEvidence:
    logloss_improvement_2024: float
    logloss_improvement_2025: float
    brier_improvement_2024: float
    brier_improvement_2025: float
    coverage_2024: float
    coverage_2025: float
    calibration_acceptable_2024: bool
    calibration_acceptable_2025: bool
    integrity_failure: str | None = None


def _finite_evidence(values: Mapping[str, Any]) -> None:
    for label, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ParticipationContractError(f"{label} must be finite")


def _decision_payload(
    *,
    component: str,
    decision: str,
    allowed: Sequence[str],
    rationale: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if decision not in allowed:
        raise ParticipationContractError("component decision is outside its frozen enum")
    blocked = decision.endswith("_BLOCKED")
    rejected = decision.endswith("_REJECTED")
    return {
        "schemaVersion": f"MLB_{component}_DECISION_V1",
        "decision": decision,
        "rationale": rationale,
        "coverageThreshold": ACCEPTABLE_POOL_COVERAGE,
        "evidence": dict(evidence),
        "limitations": [
            "Retrospective reconstruction is not prospective proof.",
            "No governed roster, transaction, injury, option, or announcement feed is present.",
            "Uncovered actual participants are measured and are never injected into candidate pools.",
        ],
        "recommendedNextStep": (
            "Preserve the research component and validate prospectively with a governed roster authority."
            if not blocked and not rejected
            else "Resolve the recorded integrity failure before rerunning."
            if blocked
            else "Retain the baseline and revise the challenger without consulting 2025 selection evidence."
        ),
    }


_BLOCKED_DECISION_TEXT: Mapping[str, Mapping[str, Any]] = {
    "LINEUP_PROJECTION": {
        "decision": "LINEUP_BLOCKED",
        "schemaVersion": "MLB_LINEUP_PROJECTION_DECISION_V1",
        "rationale": (
            "Lineup execution was blocked by a component-local modeling failure "
            "after feature-authority validation."
        ),
    },
    "STARTER_DURATION": {
        "decision": "STARTER_DURATION_BLOCKED",
        "schemaVersion": "MLB_STARTER_DURATION_DECISION_V1",
        "rationale": (
            "Starter-duration execution was blocked by a component-local modeling "
            "failure after feature-authority validation."
        ),
    },
    "BULLPEN_USAGE": {
        "decision": "BULLPEN_USAGE_BLOCKED",
        "schemaVersion": "MLB_BULLPEN_USAGE_DECISION_V1",
        "rationale": (
            "Bullpen-usage execution was blocked by a component-local modeling "
            "failure after feature-authority validation."
        ),
    },
}
BLOCKED_DECISION_LIMITATIONS: tuple[str, ...] = (
    "Retrospective reconstruction is not prospective proof.",
    "No governed roster, transaction, injury, option, or announcement feed is present.",
    "Uncovered actual participants are measured and are never injected into candidate pools.",
    "No model-selection or fold-metric claim is available for this blocked component.",
)
BLOCKED_RECOMMENDED_NEXT_STEP = (
    "Resolve the component-local modeling failure and resume from the validated "
    "feature checkpoint."
)


def blocked_component_decision(component_type: str, blocked_stage: str) -> dict[str, Any]:
    """Return the only public decision evidence allowed for a local component failure."""

    if component_type not in _BLOCKED_DECISION_TEXT or blocked_stage not in BLOCKED_STAGES:
        raise ParticipationContractError("blocked component type/stage differs")
    expected_prefix = {
        "LINEUP_PROJECTION": "LINEUP_",
        "STARTER_DURATION": "STARTER_",
        "BULLPEN_USAGE": "BULLPEN_",
    }[component_type]
    if not blocked_stage.startswith(expected_prefix):
        raise ParticipationContractError("blocked stage belongs to another component")
    text = _BLOCKED_DECISION_TEXT[component_type]
    return {
        "schemaVersion": text["schemaVersion"],
        "decision": text["decision"],
        "rationale": text["rationale"],
        "coverageThreshold": ACCEPTABLE_POOL_COVERAGE,
        "evidence": {
            "executionStatus": "BLOCKED",
            "failureCode": BLOCKED_FAILURE_CODE,
            "blockedStage": blocked_stage,
            "resumable": True,
        },
        "limitations": list(BLOCKED_DECISION_LIMITATIONS),
        "recommendedNextStep": BLOCKED_RECOMMENDED_NEXT_STEP,
    }


def lineup_decision(evidence: LineupDecisionEvidence) -> dict[str, Any]:
    _finite_evidence(
        {
            "improvement_2024": evidence.improvement_2024,
            "improvement_2025": evidence.improvement_2025,
            "coverage_2024": evidence.coverage_2024,
            "coverage_2025": evidence.coverage_2025,
        }
    )
    if not 0.0 <= evidence.coverage_2024 <= 1.0 or not 0.0 <= evidence.coverage_2025 <= 1.0:
        raise ParticipationContractError("lineup coverage must be in [0,1]")
    if evidence.integrity_failure:
        decision = "LINEUP_BLOCKED"
        rationale = f"Integrity failure: {evidence.integrity_failure.strip()}"
    elif (
        evidence.improvement_2024 > DECISION_TOLERANCE
        and evidence.improvement_2025 > DECISION_TOLERANCE
        and min(evidence.coverage_2024, evidence.coverage_2025) >= ACCEPTABLE_POOL_COVERAGE
    ):
        decision = "LINEUP_RESEARCH_COMPONENT"
        rationale = "The selected lineup challenger improved on L0 in both folds with acceptable pool coverage."
    elif (
        evidence.improvement_2024 < -DECISION_TOLERANCE
        and evidence.improvement_2025 < -DECISION_TOLERANCE
    ):
        decision = "LINEUP_REJECTED"
        rationale = "The selected lineup challenger was worse than L0 in both folds."
    else:
        decision = "LINEUP_RESEARCH_BASELINE"
        rationale = "Lineup evidence was valid but mixed, tied, or below the frozen coverage threshold."
    return _decision_payload(
        component="LINEUP_PROJECTION",
        decision=decision,
        allowed=LINEUP_DECISION_ENUM,
        rationale=rationale,
        evidence={
            "logLossImprovement2024": float(evidence.improvement_2024),
            "logLossImprovement2025": float(evidence.improvement_2025),
            "coverage2024": float(evidence.coverage_2024),
            "coverage2025": float(evidence.coverage_2025),
            "integrityFailure": evidence.integrity_failure,
        },
    )


def starter_decision(evidence: StarterDecisionEvidence) -> dict[str, Any]:
    values = {
        "bfpMaeVsS0_2024": evidence.bfp_mae_vs_s0_2024,
        "bfpRmseVsS0_2024": evidence.bfp_rmse_vs_s0_2024,
        "bfpMaeVsS1_2024": evidence.bfp_mae_vs_s1_2024,
        "bfpRmseVsS1_2024": evidence.bfp_rmse_vs_s1_2024,
        "bfpMaeVsS0_2025": evidence.bfp_mae_vs_s0_2025,
        "bfpRmseVsS0_2025": evidence.bfp_rmse_vs_s0_2025,
        "bfpMaeVsS1_2025": evidence.bfp_mae_vs_s1_2025,
        "bfpRmseVsS1_2025": evidence.bfp_rmse_vs_s1_2025,
    }
    _finite_evidence(values)
    comparison_values = tuple(values.values())
    if evidence.integrity_failure:
        decision = "STARTER_DURATION_BLOCKED"
        rationale = f"Integrity failure: {evidence.integrity_failure.strip()}"
    elif all(value > DECISION_TOLERANCE for value in comparison_values):
        decision = "STARTER_DURATION_RESEARCH_COMPONENT"
        rationale = "The selected duration challenger improved BFP MAE and RMSE against S0 and S1 in both folds."
    elif all(value < -DECISION_TOLERANCE for value in comparison_values):
        decision = "STARTER_DURATION_REJECTED"
        rationale = "The selected duration challenger was worse than S0 and S1 on both governing metrics in both folds."
    else:
        decision = "STARTER_DURATION_RESEARCH_BASELINE"
        rationale = "Starter-duration evidence was valid but mixed or tied across the governed comparisons."
    return _decision_payload(
        component="STARTER_DURATION",
        decision=decision,
        allowed=STARTER_DECISION_ENUM,
        rationale=rationale,
        evidence={**{key: float(value) for key, value in values.items()}, "integrityFailure": evidence.integrity_failure},
    )


def bullpen_decision(evidence: BullpenDecisionEvidence) -> dict[str, Any]:
    _finite_evidence(
        {
            "logloss_improvement_2024": evidence.logloss_improvement_2024,
            "logloss_improvement_2025": evidence.logloss_improvement_2025,
            "brier_improvement_2024": evidence.brier_improvement_2024,
            "brier_improvement_2025": evidence.brier_improvement_2025,
            "coverage_2024": evidence.coverage_2024,
            "coverage_2025": evidence.coverage_2025,
        }
    )
    if not 0.0 <= evidence.coverage_2024 <= 1.0 or not 0.0 <= evidence.coverage_2025 <= 1.0:
        raise ParticipationContractError("bullpen coverage must be in [0,1]")
    if type(evidence.calibration_acceptable_2024) is not bool or type(evidence.calibration_acceptable_2025) is not bool:
        raise ParticipationContractError("bullpen calibration gates must be booleans")
    if evidence.integrity_failure:
        decision = "BULLPEN_USAGE_BLOCKED"
        rationale = f"Integrity failure: {evidence.integrity_failure.strip()}"
    elif (
        evidence.logloss_improvement_2024 > DECISION_TOLERANCE
        and evidence.logloss_improvement_2025 > DECISION_TOLERANCE
        and evidence.brier_improvement_2024 >= -DECISION_TOLERANCE
        and evidence.brier_improvement_2025 >= -DECISION_TOLERANCE
        and min(evidence.coverage_2024, evidence.coverage_2025) >= ACCEPTABLE_POOL_COVERAGE
        and evidence.calibration_acceptable_2024
        and evidence.calibration_acceptable_2025
    ):
        decision = "BULLPEN_USAGE_RESEARCH_COMPONENT"
        rationale = "The selected bullpen challenger improved on B0 in both folds with acceptable calibration and coverage."
    elif (
        evidence.logloss_improvement_2024 < -DECISION_TOLERANCE
        and evidence.logloss_improvement_2025 < -DECISION_TOLERANCE
    ):
        decision = "BULLPEN_USAGE_REJECTED"
        rationale = "The selected bullpen challenger was worse than B0 in both folds."
    else:
        decision = "BULLPEN_USAGE_RESEARCH_BASELINE"
        rationale = "Bullpen evidence was valid but mixed, tied, insufficiently calibrated, or below the coverage threshold."
    return _decision_payload(
        component="BULLPEN_USAGE",
        decision=decision,
        allowed=BULLPEN_DECISION_ENUM,
        rationale=rationale,
        evidence={
            "logLossImprovement2024": float(evidence.logloss_improvement_2024),
            "logLossImprovement2025": float(evidence.logloss_improvement_2025),
            "brierImprovement2024": float(evidence.brier_improvement_2024),
            "brierImprovement2025": float(evidence.brier_improvement_2025),
            "coverage2024": float(evidence.coverage_2024),
            "coverage2025": float(evidence.coverage_2025),
            "calibrationAcceptable2024": evidence.calibration_acceptable_2024,
            "calibrationAcceptable2025": evidence.calibration_acceptable_2025,
            "integrityFailure": evidence.integrity_failure,
        },
    )


def require_no_id_features(feature_names: Sequence[str]) -> None:
    forbidden = tuple(
        name
        for name in feature_names
        if name.casefold().endswith("_id")
        or "uuid" in name.casefold()
        or "player_id" in name.casefold()
        or "team_id" in name.casefold()
        or "game_id" in name.casefold()
    )
    if forbidden:
        raise ParticipationContractError(f"IDs may not be model features: {forbidden}")


for _features in (LINEUP_FEATURES, STARTER_FEATURES, BULLPEN_FEATURES):
    require_no_id_features(_features)


__all__ = [
    "ACCEPTABLE_POOL_COVERAGE",
    "BULLPEN_CANDIDATES",
    "BULLPEN_CONTRACT_NAME",
    "BULLPEN_CONTRACT_VERSION",
    "BULLPEN_FEATURES",
    "BULLPEN_TRAILING_POOL_DAYS",
    "BULLPEN_DECISION_ENUM",
    "BullpenDecisionEvidence",
    "DECISION_TOLERANCE",
    "DEFAULT_MAX_ITER",
    "DEFAULT_TOLERANCE",
    "DYNAMIC_CONTRACT_ID",
    "DYNAMIC_CONTRACT_SHA",
    "DYNAMIC_LOGICAL_URI_PREFIX",
    "DYNAMIC_PITCHER_LOG_ODDS_FEATURES",
    "DYNAMIC_SCHEMA_SHA",
    "EARLY_SEASON_DAYS",
    "FINAL_EVALUATION_SEASON",
    "HGB_LEARNING_RATE",
    "HGB_MAX_DEPTH",
    "HGB_MAX_ITER",
    "HISTORY_SEASONS",
    "INNER_TUNING_SEASON",
    "LINEUP_CANDIDATES",
    "LINEUP_CONTRACT_NAME",
    "LINEUP_CONTRACT_VERSION",
    "LINEUP_DECISION_ENUM",
    "LINEUP_FEATURES",
    "LINEUP_TRAILING_POOL_DAYS",
    "LOGISTIC_C_GRID",
    "PARTICIPATION_SCHEMA_VERSION",
    "ParticipationContractError",
    "RANDOM_SEED",
    "RIDGE_ALPHA_GRID",
    "SELECTION_SEASON",
    "STARTER_CANDIDATES",
    "STARTER_CONTRACT_NAME",
    "STARTER_CONTRACT_VERSION",
    "STARTER_DECISION_ENUM",
    "STARTER_FEATURES",
    "LineupDecisionEvidence",
    "StarterDecisionEvidence",
    "TARGET_SEASONS",
    "bullpen_contract_payload",
    "canonical_sha",
    "bullpen_decision",
    "contract_set_payload",
    "contract_set_sha",
    "lineup_contract_payload",
    "lineup_decision",
    "require_no_id_features",
    "starter_contract_payload",
    "starter_decision",
    "validate_dynamic_descriptor",
]
