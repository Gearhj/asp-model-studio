from __future__ import annotations

import math
from typing import Any, Mapping

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_datasets.constants import (
    PARTITION_AUTHORITY_SHA,
    REGISTRATION_ID as DATASET_REGISTRATION_ID,
)
from server.sports_identity_bridges.constants import (
    ALIAS_AUTHORITY_SHA,
    BRIDGE_MANIFEST_SHA,
    BRIDGE_REGISTRATION_ID,
    DIMENSION_AUTHORITY_SHA,
)
from server.sports_modeling.feature_contract import CONTEXT_FEATURES
from server.sports_modeling.metrics import PA_CLASS_ORDER


CONTRACT_NAME = "MLB_DYNAMIC_PLAYER_STATE_V1"
CONTRACT_VERSION = "MLB_DYNAMIC_PLAYER_STATE_V1"
SEMANTIC_VERSION = "1.0.0"
CONTRACT_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_CONTRACT_V1"
DESCRIPTOR_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_DESCRIPTOR_V1"
TABLE_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_TABLE_V1"
CONTENT_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_CONTENT_V1"
HISTORY_INDEX_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_HISTORY_INDEX_V1"
HISTORY_INDEX_CONTENT_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_HISTORY_CONTENT_V1"
HISTORY_INDEX_DESCRIPTOR_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_HISTORY_DESCRIPTOR_V1"
TUNING_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_TUNING_V1"
EXPERIMENT_SCHEMA_VERSION = "MLB_DYNAMIC_PA_EXPERIMENT_V1"

TARGET_SEASONS: tuple[int, ...] = (2023, 2024, 2025)
SOURCE_SEASONS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)
ROLES: tuple[str, ...] = ("BATTER", "PITCHER")
STATE_KINDS: tuple[str, ...] = (
    "A_PRESEASON",
    "B_CUMULATIVE",
    "C_RECENCY",
)

REFERENCE_CLASS = "OTHER_REACH"
LOG_ODDS_CLASSES: tuple[str, ...] = tuple(
    class_name for class_name in PA_CLASS_ORDER if class_name != REFERENCE_CLASS
)
HALF_LIFE_GRID: tuple[int | None, ...] = (30, 60, 120, None)
PRIOR_ESS_GRID: tuple[int, ...] = (50, 150, 300)
LOGISTIC_C_GRID: tuple[float, ...] = (0.05, 0.2, 1.0)
BOOTSTRAP_RESAMPLES = 500
BOOTSTRAP_SEED = 20_260_817
DECISION_TOLERANCE = 1e-10
CALIBRATION_DEFECT_ABSOLUTE_TOLERANCE = 0.005

KEY_COLUMNS: tuple[str, ...] = (
    "game_date",
    "season",
    "canonical_player_uuid",
    "role",
    "state_kind",
    "policy_id",
)
STATE_VALUE_COLUMNS: tuple[str, ...] = (
    *(f"log_odds_{class_name.casefold()}" for class_name in LOG_ODDS_CLASSES),
    "effective_sample_size",
    "entropy",
    "days_since_evidence",
    "count_7d",
    "count_30d",
    "count_90d",
    "missing_history",
)
STATE_AUDIT_COLUMNS: tuple[str, ...] = (
    "eligible_event_count",
    "long_term_event_count",
    "recent_event_count",
    "recent_effective_count",
    "overlap_event_count",
    "last_evidence_date",
    "evidence_cutoff_exclusive",
)


def _prefixed(role: str, state: str) -> tuple[str, ...]:
    prefix = f"{role.casefold()}_{state.casefold()}_"
    return tuple(prefix + name for name in STATE_VALUE_COLUMNS)


BATTER_CUMULATIVE_FEATURES = _prefixed("BATTER", "B")
PITCHER_CUMULATIVE_FEATURES = _prefixed("PITCHER", "B")
BATTER_RECENCY_FEATURES = _prefixed("BATTER", "C")
PITCHER_RECENCY_FEATURES = _prefixed("PITCHER", "C")

CANDIDATE_FEATURES: Mapping[str, tuple[str, ...]] = {
    "D0": (),
    "D1": CONTEXT_FEATURES + BATTER_CUMULATIVE_FEATURES,
    "D2": CONTEXT_FEATURES + PITCHER_CUMULATIVE_FEATURES,
    "D3": CONTEXT_FEATURES + BATTER_CUMULATIVE_FEATURES + PITCHER_CUMULATIVE_FEATURES,
    "D4": CONTEXT_FEATURES + BATTER_RECENCY_FEATURES + PITCHER_RECENCY_FEATURES,
}
CANDIDATE_LABELS: Mapping[str, str] = {
    "D0": "Frozen Phase 3 raw C4",
    "D1": "Context plus cumulative batter state",
    "D2": "Context plus cumulative pitcher state",
    "D3": "Context plus cumulative batter and pitcher state",
    "D4": "Context plus recency-weighted batter and pitcher state",
}

DECISION_ENUM: tuple[str, ...] = (
    "DYNAMIC_STATE_RESEARCH_CHALLENGER",
    "DYNAMIC_STATE_RESEARCH_BASELINE",
    "DYNAMIC_STATE_REJECTED",
    "DYNAMIC_STATE_BLOCKED",
)
COMMON_COMPONENT_FIELDS: frozenset[str] = frozenset(
    {
        "componentId",
        "componentType",
        "contractName",
        "contractSha",
        "descriptor",
        "candidates",
        "selected",
        "folds",
        "metrics",
        "calibration",
        "bootstrap",
        "coverage",
        "decision",
        "artifactIds",
    }
)

PARENT_MANIFEST_SHA = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
IDENTITY_JOIN_AUDIT_ID = (
    "sports-identity-join-audit:sha256:"
    "375ef4faef6716a8d66fe68b30c12bf8caff5b9255aa71fc4bd7354f9589b8b9"
)
PHASE3_RUN_ID = (
    "sports-pa-research-run:sha256:"
    "9ee241378320fb820aab2531a6525d2d4624d42e7ff6c406e147f28c6800fd07"
)
PHASE3_RUN_SHA = "dc62d2bd07df9ddd26494512c748a5859cf9667cdc901f002f6d2a86b619658e"
PHASE3_FEATURE_CONTRACT_SHA = (
    "fc3227fe1488f0cf422dc40c634a9b0b1c432828d479a68ea6ba7a0dce038d1e"
)
PHASE3_FEATURE_VIEW_ID = (
    "mlb-pa-feature-view:sha256:"
    "74b9c24bb57dd75061a5de0f967c4a57e492eab9e016be950a036292bf8f958b"
)
PHASE3_FEATURE_CONTENT_SHA = (
    "74b9c24bb57dd75061a5de0f967c4a57e492eab9e016be950a036292bf8f958b"
)
PHASE3_FEATURE_ARTIFACT_SHA = (
    "42884747dfb610564bf0c85ab30f6c16d09b2a01982ddbc4e9ccb485f2ddb53f"
)
PHASE3_FEATURE_MATERIALIZATION_ID = (
    "sports-pa-feature-materialization:sha256:"
    "ff425ca7a4aa0180837d3265fbb02d34484f6ea7a495cc5a5545bd9aeb836a55"
)
PHASE3_FOLD_2024_PREDICTION_SHA = (
    "85215c590d04dd9d97f6037b69522d0602214b4a244b7160289ba6db0c6ac8cd"
)
PHASE3_FOLD_2025_PREDICTION_SHA = (
    "0263d4fc031fe4851160ac3ee0cd86dcacdf2152a861ea3ade6fdab0f04d6be1"
)
EXPECTED_SOURCE_PARTITION_COUNT = 36


def dynamic_state_schema_spec() -> dict[str, Any]:
    fields: list[dict[str, Any]] = [
        {
            "name": "stateRowId",
            "dtype": "string",
            "nullable": False,
            "role": "row_identity",
        },
        {
            "name": "rowContentSha",
            "dtype": "string",
            "nullable": False,
            "role": "row_checksum",
        },
        {"name": "game_date", "dtype": "string", "nullable": False, "role": "as_of_key"},
        {"name": "season", "dtype": "int16", "nullable": False, "role": "season_key"},
        {
            "name": "canonical_player_uuid",
            "dtype": "string",
            "nullable": False,
            "role": "identity_key",
        },
        {"name": "role", "dtype": "string", "nullable": False, "role": "role_key"},
        {"name": "state_kind", "dtype": "string", "nullable": False, "role": "state_key"},
        {"name": "policy_id", "dtype": "string", "nullable": False, "role": "policy_key"},
    ]
    fields.extend(
        {
            "name": f"log_odds_{class_name.casefold()}",
            "dtype": "float64",
            "nullable": False,
            "role": "feature",
        }
        for class_name in LOG_ODDS_CLASSES
    )
    fields.extend(
        [
            {
                "name": "effective_sample_size",
                "dtype": "float64",
                "nullable": False,
                "role": "feature",
            },
            {"name": "entropy", "dtype": "float64", "nullable": False, "role": "feature"},
            {
                "name": "days_since_evidence",
                "dtype": "int32",
                "nullable": True,
                "role": "feature",
            },
            {"name": "count_7d", "dtype": "int32", "nullable": False, "role": "feature"},
            {"name": "count_30d", "dtype": "int32", "nullable": False, "role": "feature"},
            {"name": "count_90d", "dtype": "int32", "nullable": False, "role": "feature"},
            {
                "name": "missing_history",
                "dtype": "bool",
                "nullable": False,
                "role": "feature",
            },
            {
                "name": "eligible_event_count",
                "dtype": "int32",
                "nullable": False,
                "role": "audit",
            },
            {
                "name": "long_term_event_count",
                "dtype": "int32",
                "nullable": False,
                "role": "audit",
            },
            {
                "name": "recent_event_count",
                "dtype": "int32",
                "nullable": False,
                "role": "audit",
            },
            {
                "name": "recent_effective_count",
                "dtype": "float64",
                "nullable": False,
                "role": "audit",
            },
            {
                "name": "overlap_event_count",
                "dtype": "int32",
                "nullable": False,
                "role": "audit",
            },
            {
                "name": "last_evidence_date",
                "dtype": "string",
                "nullable": True,
                "role": "audit",
            },
            {
                "name": "evidence_cutoff_exclusive",
                "dtype": "string",
                "nullable": False,
                "role": "audit",
            },
        ]
    )
    return {
        "schemaVersion": TABLE_SCHEMA_VERSION,
        "contractName": CONTRACT_NAME,
        "contractVersion": CONTRACT_VERSION,
        "primaryKey": ["stateRowId"],
        "naturalKey": list(KEY_COLUMNS),
        "fields": fields,
    }


def dynamic_state_schema_sha() -> str:
    return sha256_bytes(canonical_json_bytes(dynamic_state_schema_spec()))


def dynamic_history_index_schema_spec() -> dict[str, Any]:
    fields: list[dict[str, Any]] = [
        {"name": "historyRowId", "dtype": "string", "nullable": False, "role": "row_identity"},
        {"name": "rowContentSha", "dtype": "string", "nullable": False, "role": "row_checksum"},
        {
            "name": "canonical_player_uuid",
            "dtype": "string",
            "nullable": False,
            "role": "identity_grouping_only",
        },
        {"name": "role", "dtype": "string", "nullable": False, "role": "role_key"},
        {
            "name": "final_available_date",
            "dtype": "string",
            "nullable": False,
            "role": "availability_key",
        },
        {"name": "source_season", "dtype": "int16", "nullable": False, "role": "source_season"},
    ]
    fields.extend(
        {
            "name": f"count_{class_name.casefold()}",
            "dtype": "int32",
            "nullable": False,
            "role": "terminal_outcome_sufficient_statistic",
        }
        for class_name in PA_CLASS_ORDER
    )
    return {
        "schemaVersion": HISTORY_INDEX_SCHEMA_VERSION,
        "contractName": CONTRACT_NAME,
        "contractVersion": CONTRACT_VERSION,
        "primaryKey": ["historyRowId"],
        "naturalKey": [
            "canonical_player_uuid",
            "role",
            "final_available_date",
            "source_season",
        ],
        "fields": fields,
    }


def dynamic_history_index_schema_sha() -> str:
    return sha256_bytes(canonical_json_bytes(dynamic_history_index_schema_spec()))


def dynamic_state_contract_payload() -> dict[str, Any]:
    return {
        "schemaVersion": CONTRACT_SCHEMA_VERSION,
        "contractName": CONTRACT_NAME,
        "contractVersion": CONTRACT_VERSION,
        "semanticVersion": SEMANTIC_VERSION,
        "sport": "MLB",
        "component": "DYNAMIC_PLAYER_STATE",
        "classOrder": list(PA_CLASS_ORDER),
        "referenceClass": REFERENCE_CLASS,
        "sourceSeasons": list(SOURCE_SEASONS),
        "targetSeasons": list(TARGET_SEASONS),
        "roles": list(ROLES),
        "stateKinds": [
            {
                "stateKind": "A_PRESEASON",
                "meaning": "Player history completed before January 1 of the target season, shrunk to the role-league distribution.",
                "movingWithinSeason": False,
            },
            {
                "stateKind": "B_CUMULATIVE",
                "meaning": "All player plate-appearance terminal outcomes whose final availability date is strictly before the target game date.",
                "movingWithinSeason": True,
            },
            {
                "stateKind": "C_RECENCY",
                "meaning": "Nonoverlapping long-term history through target season minus two plus exponentially decayed target-minus-one/current-season evidence completed strictly before the target game date.",
                "movingWithinSeason": True,
            },
        ],
        "temporalPolicy": {
            "sourceField": "plate_appearance.final_available_date",
            "targetField": "MLB_PA_FEATURE_VIEW_V1.game_date",
            "eligibilityPredicate": "source.final_available_date < target.game_date",
            "sameDateEvidenceExcluded": True,
            "doubleheaderSameDateEvidenceExcluded": True,
            "suspendedGameAvailabilityDelayedUntilFinalDate": True,
            "terminalOutcomeIsHistoricalStateOnly": True,
            "currentPlateAppearanceOutcomeExcluded": True,
        },
        "identityPolicy": {
            "sourceFields": ["plate_appearance.batter_id", "plate_appearance.pitcher_id"],
            "namespace": "RETROSHEET",
            "mapping": "exact parent_join_key to canonical_player_uuid",
            "unresolvedPolicy": "FAIL_CLOSED",
            "ambiguousPolicy": "FAIL_CLOSED",
        },
        "authorityBindings": {
            "dataset": {
                "registrationId": DATASET_REGISTRATION_ID,
                "manifestSha": PARENT_MANIFEST_SHA,
                "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
                "sourceFamily": "plate_appearance",
                "sourceSeasons": list(SOURCE_SEASONS),
                "descriptorSourcePartitionIdsRequired": True,
                "expectedSourcePartitionCount": EXPECTED_SOURCE_PARTITION_COUNT,
            },
            "identityBridge": {
                "registrationId": BRIDGE_REGISTRATION_ID,
                "manifestSha": BRIDGE_MANIFEST_SHA,
                "joinAuditId": IDENTITY_JOIN_AUDIT_ID,
                "aliasAuthoritySha": ALIAS_AUTHORITY_SHA,
                "dimensionAuthoritySha": DIMENSION_AUTHORITY_SHA,
            },
            "phase3": {
                "runId": PHASE3_RUN_ID,
                "runSha": PHASE3_RUN_SHA,
                "featureContractSha": PHASE3_FEATURE_CONTRACT_SHA,
                "featureViewId": PHASE3_FEATURE_VIEW_ID,
                "featureContentSha": PHASE3_FEATURE_CONTENT_SHA,
                "featureArtifactSha": PHASE3_FEATURE_ARTIFACT_SHA,
                "featureMaterializationId": PHASE3_FEATURE_MATERIALIZATION_ID,
                "foldPredictionShas": {
                    "2024": PHASE3_FOLD_2024_PREDICTION_SHA,
                    "2025": PHASE3_FOLD_2025_PREDICTION_SHA,
                },
                "classOrder": list(PA_CLASS_ORDER),
            },
        },
        "posteriorPolicy": {
            "roleLeagueShrinkage": True,
            "roleLeagueClassSmoothing": "LAPLACE_ONE_PER_CLASS",
            "halfLifeGridDays": list(HALF_LIFE_GRID),
            "priorEffectiveSampleSizeGrid": list(PRIOR_ESS_GRID),
            "tuningPopulation": "date-atomic chronological inner-2023 validation only",
            "objective": "mean batter/pitcher posterior-predictive multiclass log loss",
            "tieBreak": ["objective", "priorEffectiveSampleSize", "halfLifeGridOrdinal"],
            "freezeBefore2024": True,
            "recencyLongTermSourceSeasonPredicate": "source.season <= target.season - 2",
            "recencyRecentSourceSeasonPredicate": "source.season in {target.season - 1, target.season}",
            "recencyOverlapRequired": 0,
            "frozenEvaluation": {
                "seasons": [2024, 2025],
                "roles": list(ROLES),
                "stateKinds": list(STATE_KINDS),
                "metrics": ["logLoss", "brierScore"],
                "brierDefinition": "MEAN_SUMMED_ONE_VS_ALL_SQUARED_ERROR",
                "policyFrozenBeforeEvaluation": True,
                "selectionUses2024Or2025": False,
            },
        },
        "representation": {
            "logOddsClasses": list(LOG_ODDS_CLASSES),
            "logOddsReference": REFERENCE_CLASS,
            "probabilityFloor": 1e-12,
            "entropyUnit": "natural_log_nats",
            "windowDays": [7, 30, 90],
            "valueColumns": list(STATE_VALUE_COLUMNS),
            "auditColumns": list(STATE_AUDIT_COLUMNS),
            "keyColumns": list(KEY_COLUMNS),
            "rowIdentityPolicy": {
                "stateRowId": "mlb-dynamic-player-state-row:sha256 of contract SHA plus the canonical natural key",
                "rowContentSha": "SHA-256 of canonical semantic row content excluding stateRowId and rowContentSha",
                "duplicateNaturalKeyPolicy": "FAIL_CLOSED",
            },
            "historicalIndex": {
                "schemaVersion": HISTORY_INDEX_SCHEMA_VERSION,
                "schemaSha": dynamic_history_index_schema_sha(),
                "grain": "canonical_player_uuid + role + final_available_date + source_season",
                "statistics": [f"count_{name.casefold()}" for name in PA_CLASS_ORDER],
                "identityUse": "lineage and grouping only",
                "consumerPolicy": "load strict ignored-runtime artifact and derive C_RECENCY on demand with the same frozen policy",
                "targetRowsInjected": False,
            },
        },
        "candidatePolicy": {
            candidate_id: {
                "displayName": CANDIDATE_LABELS[candidate_id],
                "featureNames": list(features),
                "estimator": (
                    "FROZEN_PHASE3_RAW_C4" if candidate_id == "D0" else "MULTINOMIAL_LOGISTIC_L2"
                ),
            }
            for candidate_id, features in CANDIDATE_FEATURES.items()
        },
        "evaluationPolicy": {
            "logisticCGrid": list(LOGISTIC_C_GRID),
            "innerTuningSeason": 2023,
            "selectionSeason": 2024,
            "finalEvaluationSeason": 2025,
            "selectDynamicCandidateOn2024Only": True,
            "evaluateAllCandidatesOn2025AfterSelection": True,
            "d0NeverRefitOrRelabelled": True,
            "rawPredictionsPreserved": True,
            "temperatureFitSeason": 2024,
            "temperatureApplicationSeason": 2025,
            "calibrationEligibilityRule": "temperature is fit on 2024 and eligible only if scaled 2024 log loss and Brier score are each non-worse than raw within 1e-10",
            "calibrationFinalRetentionRule": "retain scaled final probabilities only if eligible on 2024 and scaled 2025 log loss and Brier score are each non-worse than raw within 1e-10; always preserve raw and scaled evidence",
            "bootstrapUnit": "game_id",
            "bootstrapResamples": BOOTSTRAP_RESAMPLES,
            "bootstrapSeed": BOOTSTRAP_SEED,
            "subgroups": ["missing_history", "effective_sample_size_band"],
            "challengerDecisionRule": {
                "probabilityVariant": "RAW_ONLY",
                "logLoss": "strictly better than D0 in both 2024 and 2025",
                "brierScore": "better or tied with D0 within 1e-10 in both folds",
                "calibrationDefect": (
                    "raw selected top-label ECE and every raw classwise ECE may exceed D0 "
                    "by at most 0.005 in each fold"
                ),
                "bootstrapIsDecisionGate": False,
            },
            "decisionEnum": list(DECISION_ENUM),
        },
        "artifactPolicy": {
            "bindingSchemaVersion": "MLB_DYNAMIC_PLAYER_STATE_ARTIFACT_BINDINGS_V1",
            "bodyBindingFields": [
                "schemaVersion",
                "createdAt",
                "codeRevision",
                "datasetManifestSha",
                "identityBridgeManifestSha",
                "phase3FeatureContractSha",
                "componentContractSha",
                "artifactType",
                "temporalFold",
                "sourcePartitionIds",
                "classOrder",
                "targetOrder",
            ],
            "referenceFields": [
                "artifactId",
                "artifactType",
                "logicalUri",
                "sha256",
                "byteCount",
                "mediaType",
            ],
            "selfDigestCircularityProhibited": True,
            "crossCodeRevisionReuse": (
                "stable state/history materialization carries its original creation/revision "
                "bindings and reuse requires exact freshly rebuilt semantic bytes"
            ),
        },
        "researchOnly": True,
        "deploymentAuthorized": False,
    }


def dynamic_state_contract_sha(payload: Mapping[str, Any] | None = None) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            dict(payload) if payload is not None else dynamic_state_contract_payload()
        )
    )


def validate_dynamic_component_evidence(
    component: Mapping[str, Any],
    *,
    artifact_references: list[Mapping[str, Any]] | None = None,
) -> None:
    """Validate the stable registry-facing common component projection."""

    if not isinstance(component, Mapping) or set(component) != COMMON_COMPONENT_FIELDS:
        raise ValueError("dynamic component common field set differs")
    if component.get("componentType") != "DYNAMIC_PLAYER_STATE":
        raise ValueError("dynamic componentType differs")
    if component.get("contractName") != CONTRACT_NAME:
        raise ValueError("dynamic contractName differs")
    if component.get("contractSha") != dynamic_state_contract_sha():
        raise ValueError("dynamic contract SHA differs")
    candidates = component.get("candidates")
    if not isinstance(candidates, list) or [row.get("candidateId") for row in candidates] != [
        "D0",
        "D1",
        "D2",
        "D3",
        "D4",
    ]:
        raise ValueError("dynamic candidates differ")
    by_id = {row["candidateId"]: row for row in candidates}
    selected = component.get("selected")
    if not isinstance(selected, Mapping) or selected.get("candidateId") not in {
        "D1",
        "D2",
        "D3",
        "D4",
    }:
        raise ValueError("dynamic selected candidate differs")
    expected_selected = min(
        candidates[1:],
        key=lambda row: (
            row["foldMetrics"][0]["metrics"]["logLoss"],
            row["foldMetrics"][0]["metrics"]["brierScore"],
            row["ordinal"],
        ),
    )["candidateId"]
    if selected["candidateId"] != expected_selected:
        raise ValueError("dynamic selection does not reconcile to raw 2024 evidence")
    folds = component.get("folds")
    if not isinstance(folds, list) or [row.get("validationSeason") for row in folds] != [
        2024,
        2025,
    ]:
        raise ValueError("dynamic folds must be exactly 2024 and 2025")
    d0_folds = by_id["D0"]["foldMetrics"]
    if (
        d0_folds[0].get("trainingSeasons") != [2023]
        or d0_folds[1].get("trainingSeasons") != [2023, 2024]
        or by_id["D0"].get("config", {}).get("refit") is not False
        or by_id["D0"].get("config", {}).get("relabelled") is not False
    ):
        raise ValueError("dynamic D0 frozen-fold provenance differs")
    metrics = component.get("metrics")
    if not isinstance(metrics, Mapping) or set(metrics) != {
        "schemaVersion",
        "classOrder",
        "governingProbabilityVariant",
        "selectedCandidateId",
        "baselineCandidateId",
        "statePosteriorPredictive",
        "byCandidate",
    }:
        raise ValueError("dynamic metrics summary fields differ")
    posterior = metrics.get("statePosteriorPredictive")
    if not isinstance(posterior, Mapping) or set(posterior) != {
        "schemaVersion",
        "policyId",
        "policyFrozenBeforeEvaluation",
        "selectionUses2024Or2025",
        "probabilitySource",
        "classOrder",
        "byRoleStateFold",
    }:
        raise ValueError("dynamic state posterior-predictive evidence differs")
    descriptor = component.get("descriptor")
    selected_policy = (
        descriptor.get("selectedPolicy") if isinstance(descriptor, Mapping) else None
    )
    expected_posterior_keys = [
        (role, state_kind, season)
        for role in ROLES
        for state_kind in STATE_KINDS
        for season in (2024, 2025)
    ]
    posterior_rows = posterior.get("byRoleStateFold")
    if (
        posterior.get("schemaVersion")
        != "MLB_DYNAMIC_STATE_POSTERIOR_PREDICTIVE_EVIDENCE_V1"
        or not isinstance(selected_policy, Mapping)
        or posterior.get("policyId") != selected_policy.get("policyId")
        or posterior.get("policyFrozenBeforeEvaluation") is not True
        or posterior.get("selectionUses2024Or2025") is not False
        or posterior.get("probabilitySource") != "FROZEN_ROLE_STATE_POSTERIOR"
        or posterior.get("classOrder") != list(PA_CLASS_ORDER)
        or not isinstance(posterior_rows, list)
        or [
            (row.get("role"), row.get("stateKind"), row.get("validationSeason"))
            for row in posterior_rows
            if isinstance(row, Mapping)
        ]
        != expected_posterior_keys
    ):
        raise ValueError("dynamic state posterior-predictive authority differs")
    fold_rows = {
        int(row["validationSeason"]): int(row["validationRows"])
        for row in folds
    }
    for row in posterior_rows:
        if not isinstance(row, Mapping) or set(row) != {
            "role",
            "stateKind",
            "validationSeason",
            "rowCount",
            "logLoss",
            "brierScore",
            "brierDefinition",
        }:
            raise ValueError("dynamic state posterior-predictive row fields differ")
        season = int(row["validationSeason"])
        if (
            row.get("rowCount") != fold_rows[season]
            or row.get("brierDefinition")
            != "MEAN_SUMMED_ONE_VS_ALL_SQUARED_ERROR"
            or isinstance(row.get("logLoss"), bool)
            or not isinstance(row.get("logLoss"), (int, float))
            or not math.isfinite(float(row["logLoss"]))
            or float(row["logLoss"]) < 0.0
            or isinstance(row.get("brierScore"), bool)
            or not isinstance(row.get("brierScore"), (int, float))
            or not math.isfinite(float(row["brierScore"]))
            or not 0.0 <= float(row["brierScore"]) <= 2.0
        ):
            raise ValueError("dynamic state posterior-predictive metric differs")
    calibration = component.get("calibration")
    if not isinstance(calibration, Mapping):
        raise ValueError("dynamic calibration evidence is required")
    raw = calibration.get("raw")
    scaled = calibration.get("scaled")
    if not isinstance(raw, Mapping) or not isinstance(scaled, Mapping):
        raise ValueError("dynamic raw/scaled calibration evidence is required")
    eligible_2024 = (
        scaled["2024"]["logLoss"] <= raw["2024"]["logLoss"] + DECISION_TOLERANCE
        and scaled["2024"]["brierScore"]
        <= raw["2024"]["brierScore"] + DECISION_TOLERANCE
    )
    nonworse_2025 = (
        scaled["2025"]["logLoss"] <= raw["2025"]["logLoss"] + DECISION_TOLERANCE
        and scaled["2025"]["brierScore"]
        <= raw["2025"]["brierScore"] + DECISION_TOLERANCE
    )
    if (
        calibration.get("eligibleOn2024") is not eligible_2024
        or calibration.get("nonWorseningOn2025") is not nonworse_2025
        or calibration.get("retainedAfter2025Gate") is not (eligible_2024 and nonworse_2025)
    ):
        raise ValueError("dynamic calibration retention does not reconcile")
    decision = component.get("decision")
    if (
        not isinstance(decision, Mapping)
        or decision.get("decision") not in DECISION_ENUM
        or decision.get("decisionProbabilityVariant") != "RAW"
        or decision.get("scaledEvidenceCanEarnChallenger") is not False
        or decision.get("bootstrapUsedAsDecisionGate") is not False
    ):
        raise ValueError("dynamic decision evidence differs")
    artifact_ids = component.get("artifactIds")
    if (
        not isinstance(artifact_ids, list)
        or artifact_ids != sorted(artifact_ids)
        or len(set(artifact_ids)) != len(artifact_ids)
    ):
        raise ValueError("dynamic artifact identities differ")
    if artifact_references is not None:
        expected_ids = sorted(str(row.get("artifactId")) for row in artifact_references)
        if artifact_ids != expected_ids:
            raise ValueError("dynamic component/artifact inventory does not reconcile")
        artifact_types = [row.get("artifactType") for row in artifact_references]
        for required_type in (
            "DYNAMIC_STATE_POSTERIOR_PREDICTIVE",
            "DYNAMIC_MODEL_CARD",
            "DYNAMIC_FINAL_CHECKPOINT",
        ):
            if artifact_types.count(required_type) != 1:
                raise ValueError(f"dynamic {required_type} artifact inventory differs")
    core = dict(component)
    component_id = core.pop("componentId")
    expected_component_id = (
        "sports-phase4-component:dynamic-player-state:sha256:"
        + sha256_bytes(canonical_json_bytes(core))
    )
    if component_id != expected_component_id:
        raise ValueError("dynamic component identity differs")


__all__ = [
    "BATTER_CUMULATIVE_FEATURES",
    "BATTER_RECENCY_FEATURES",
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "CALIBRATION_DEFECT_ABSOLUTE_TOLERANCE",
    "CANDIDATE_FEATURES",
    "CANDIDATE_LABELS",
    "COMMON_COMPONENT_FIELDS",
    "CONTENT_SCHEMA_VERSION",
    "CONTRACT_NAME",
    "CONTRACT_VERSION",
    "DECISION_ENUM",
    "DECISION_TOLERANCE",
    "DESCRIPTOR_SCHEMA_VERSION",
    "EXPERIMENT_SCHEMA_VERSION",
    "EXPECTED_SOURCE_PARTITION_COUNT",
    "HALF_LIFE_GRID",
    "HISTORY_INDEX_CONTENT_SCHEMA_VERSION",
    "HISTORY_INDEX_DESCRIPTOR_SCHEMA_VERSION",
    "HISTORY_INDEX_SCHEMA_VERSION",
    "IDENTITY_JOIN_AUDIT_ID",
    "KEY_COLUMNS",
    "LOGISTIC_C_GRID",
    "LOG_ODDS_CLASSES",
    "PARENT_MANIFEST_SHA",
    "PHASE3_FEATURE_ARTIFACT_SHA",
    "PHASE3_FEATURE_CONTENT_SHA",
    "PHASE3_FEATURE_CONTRACT_SHA",
    "PHASE3_FEATURE_MATERIALIZATION_ID",
    "PHASE3_FEATURE_VIEW_ID",
    "PHASE3_FOLD_2024_PREDICTION_SHA",
    "PHASE3_FOLD_2025_PREDICTION_SHA",
    "PHASE3_RUN_ID",
    "PHASE3_RUN_SHA",
    "PRIOR_ESS_GRID",
    "PITCHER_CUMULATIVE_FEATURES",
    "PITCHER_RECENCY_FEATURES",
    "REFERENCE_CLASS",
    "ROLES",
    "SEMANTIC_VERSION",
    "SOURCE_SEASONS",
    "STATE_AUDIT_COLUMNS",
    "STATE_KINDS",
    "STATE_VALUE_COLUMNS",
    "TABLE_SCHEMA_VERSION",
    "TARGET_SEASONS",
    "TUNING_SCHEMA_VERSION",
    "dynamic_state_contract_payload",
    "dynamic_state_contract_sha",
    "dynamic_history_index_schema_sha",
    "dynamic_history_index_schema_spec",
    "dynamic_state_schema_sha",
    "dynamic_state_schema_spec",
    "validate_dynamic_component_evidence",
]
