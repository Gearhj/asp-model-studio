from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from ..sports_datasets.constants import PARTITION_AUTHORITY_SHA as _PARENT_PARTITION_AUTHORITY_SHA
from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from ..sports_identity_bridges.constants import (
    ALIAS_AUTHORITY_SHA as _BRIDGE_ALIAS_AUTHORITY_SHA,
    DIMENSION_AUTHORITY_SHA as _BRIDGE_DIMENSION_AUTHORITY_SHA,
)
from .metrics import PA_CLASS_ORDER


FEATURE_CONTRACT_NAME = "MLB_PA_FEATURE_VIEW"
FEATURE_CONTRACT_VERSION = "MLB_PA_FEATURE_VIEW_V1"
FEATURE_CONTRACT_SCHEMA_VERSION = "MLB_PA_FEATURE_CONTRACT_V1"
FEATURE_VIEW_SCHEMA_VERSION = "MLB_PA_FEATURE_SCHEMA_V1"
RESEARCH_RUN_SCHEMA_VERSION = "MLB_PA_RESEARCH_RUN_V1"

PARENT_DATASET_ID = "asp.mlb.open-data.fd1"
PARENT_DATASET_VERSION_ID = (
    "asp.mlb.open-data.fd1:sha256:"
    "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
)
PARENT_MANIFEST_SHA = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
PARENT_PARTITION_AUTHORITY_SHA = _PARENT_PARTITION_AUTHORITY_SHA

# Keep the complete authorities here rather than accepting prefix matching.  The
# partition authority is imported from the parent package's frozen consumer at
# runtime and cross-checked below; this literal is deliberately completed there
# if the package constant changes.
BRIDGE_MANIFEST_SHA = "6b69e7dcf4c5db7615420ee9f6f6f797b0335e31ab475646291f3a4cf90c52cf"
BRIDGE_ALIAS_AUTHORITY_SHA = _BRIDGE_ALIAS_AUTHORITY_SHA
BRIDGE_DIMENSION_AUTHORITY_SHA = _BRIDGE_DIMENSION_AUTHORITY_SHA

TARGET_SEASONS: tuple[int, ...] = (2023, 2024, 2025)
EXPECTED_SEASON_ROWS: Mapping[int, int] = {
    2023: 184_104,
    2024: 182_449,
    2025: 182_926,
}
EXPECTED_TOTAL_ROWS = 549_479

CONTEXT_FEATURES: tuple[str, ...] = (
    "context_inning",
    "context_top_bottom",
    "context_outs_before",
    "context_base_mask_before",
    "context_batting_score_diff_before",
)
BATTER_FEATURES: tuple[str, ...] = (
    "batter_log1p_pa",
    "batter_avg",
    "batter_obp",
    "batter_slg",
    "batter_so_per_pa",
    "batter_bb_hbp_per_pa",
    "batter_hr_per_pa",
    "batter_prior_missing",
)
PITCHER_FEATURES: tuple[str, ...] = (
    "pitcher_log1p_bfp",
    "pitcher_era9",
    "pitcher_whip",
    "pitcher_so_per_bfp",
    "pitcher_bb_per_bfp",
    "pitcher_hr_per_bfp",
    "pitcher_hbp_per_bfp",
    "pitcher_gs_per_g",
    "pitcher_prior_missing",
)
FEATURE_NAMES: tuple[str, ...] = CONTEXT_FEATURES + BATTER_FEATURES + PITCHER_FEATURES

LINEAGE_COLUMNS: tuple[str, ...] = (
    "plate_appearance_id",
    "game_id",
    "game_date",
    "season",
    "outcome",
    "batter_canonical_player_uuid",
    "pitcher_canonical_player_uuid",
    "batter_prior_season",
    "batter_prior_eligible_from_season",
    "pitcher_prior_season",
    "pitcher_prior_eligible_from_season",
)

CANDIDATE_FEATURES: Mapping[str, tuple[str, ...]] = {
    "C0": (),
    "C1": CONTEXT_FEATURES,
    "C2": CONTEXT_FEATURES + BATTER_FEATURES,
    "C3": CONTEXT_FEATURES + PITCHER_FEATURES,
    "C4": FEATURE_NAMES,
}
C_GRID: tuple[float, ...] = (0.05, 0.2, 1.0)
DECISION_TOLERANCE = 1e-10


def _included_field_definitions() -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    context = {
        "context_inning": (["inning"], "integer identity", "int16"),
        "context_top_bottom": (["top_bottom"], "fixed categorical one-hot", "int8"),
        "context_outs_before": (["outs_before"], "fixed categorical one-hot", "int8"),
        "context_base_mask_before": (["base_mask_before"], "fixed categorical one-hot", "int8"),
        "context_batting_score_diff_before": (
            ["top_bottom", "visiting_score_before", "home_score_before"],
            "batting-side conditional score subtraction",
            "int16",
        ),
    }
    prior = {
        "batter_log1p_pa": (["metrics_json.AB", "metrics_json.BB", "metrics_json.HBP", "metrics_json.SF", "metrics_json.SH"], "log1p(AB+BB+HBP+SF+SH)"),
        "batter_avg": (["metrics_json.H", "metrics_json.AB"], "H/AB"),
        "batter_obp": (["metrics_json.H", "metrics_json.BB", "metrics_json.HBP", "metrics_json.AB", "metrics_json.SF"], "(H+BB+HBP)/(AB+BB+HBP+SF)"),
        "batter_slg": (["metrics_json.H", "metrics_json.2B", "metrics_json.3B", "metrics_json.HR", "metrics_json.AB"], "(H+2B+2*3B+3*HR)/AB"),
        "batter_so_per_pa": (["metrics_json.SO", "metrics_json.AB", "metrics_json.BB", "metrics_json.HBP", "metrics_json.SF", "metrics_json.SH"], "SO/PA"),
        "batter_bb_hbp_per_pa": (["metrics_json.BB", "metrics_json.HBP", "metrics_json.AB", "metrics_json.SF", "metrics_json.SH"], "(BB+HBP)/PA"),
        "batter_hr_per_pa": (["metrics_json.HR", "metrics_json.AB", "metrics_json.BB", "metrics_json.HBP", "metrics_json.SF", "metrics_json.SH"], "HR/PA"),
        "batter_prior_missing": (["canonical_player_id", "domain", "season", "eligible_from_season"], "boolean(no eligible BATTING prior)"),
        "pitcher_log1p_bfp": (["metrics_json.BFP"], "log1p(BFP)"),
        "pitcher_era9": (["metrics_json.ER", "metrics_json.IPouts"], "27*ER/IPouts"),
        "pitcher_whip": (["metrics_json.BB", "metrics_json.H", "metrics_json.IPouts"], "3*(BB+H)/IPouts"),
        "pitcher_so_per_bfp": (["metrics_json.SO", "metrics_json.BFP"], "SO/BFP"),
        "pitcher_bb_per_bfp": (["metrics_json.BB", "metrics_json.BFP"], "BB/BFP"),
        "pitcher_hr_per_bfp": (["metrics_json.HR", "metrics_json.BFP"], "HR/BFP"),
        "pitcher_hbp_per_bfp": (["metrics_json.HBP", "metrics_json.BFP"], "HBP/BFP"),
        "pitcher_gs_per_g": (["metrics_json.GS", "metrics_json.G"], "GS/G"),
        "pitcher_prior_missing": (["canonical_player_id", "domain", "season", "eligible_from_season"], "boolean(no eligible PITCHING prior)"),
    }
    for order, name in enumerate(FEATURE_NAMES):
        if name in context:
            physical, transform, dtype = context[name]
            definitions.append(
                {
                    "featureName": name,
                    "sourceFamily": "plate_appearance",
                    "physicalFields": physical,
                    "semanticRole": "conditional_pre_terminal_pa_state",
                    "included": True,
                    "reason": "Verified state immediately before the modeled plate appearance terminates.",
                    "dtype": dtype,
                    "transformation": transform,
                    "missingnessPolicy": "reject null or out-of-domain state",
                    "temporalRule": "same plate appearance pre-terminal state; not claimed pregame-known",
                    "joinRule": "none",
                    "featureOrder": order,
                }
            )
        else:
            physical, transform = prior[name]
            role = "BATTING" if name.startswith("batter_") else "PITCHING"
            definitions.append(
                {
                    "featureName": name,
                    "sourceFamily": "player_prior",
                    "physicalFields": physical,
                    "semanticRole": "event_aligned_y_minus_one_player_prior",
                    "included": True,
                    "reason": "Stable numeric rate, volume, or explicit role-level prior missingness.",
                    "dtype": "bool" if name.endswith("_missing") else "float64",
                    "transformation": transform,
                    "missingnessPolicy": (
                        "false/true explicit indicator" if name.endswith("_missing")
                        else "invalid denominator remains missing; fold-training-only imputation"
                    ),
                    "temporalRule": "source season <= target-1 and eligible_from_season <= target",
                    "joinRule": f"exact canonical UUID; domain={role}; latest eligible source season",
                    "featureOrder": order,
                }
            )
    return definitions


def _considered_exclusions() -> list[dict[str, Any]]:
    def excluded(
        name: str,
        family: str,
        fields: list[str],
        semantic_role: str,
        reason: str,
        *,
        dtype: str = "source-defined",
        temporal_rule: str = "excluded",
        join_rule: str = "none",
    ) -> dict[str, Any]:
        return {
            "featureName": name,
            "sourceFamily": family,
            "physicalFields": fields,
            "semanticRole": semantic_role,
            "included": False,
            "reason": reason,
            "dtype": dtype,
            "transformation": "none; excluded before feature-view projection",
            "missingnessPolicy": "not applicable because excluded",
            "temporalRule": temporal_rule,
            "joinRule": join_rule,
            "featureOrder": None,
        }

    return [
        excluded(
            "terminal_outcome",
            "plate_appearance",
            ["source_terminal_token", "outcome", "terminal_play_id", "terminal_play_number"],
            "target",
            "Terminal target is retained only as the label and never projected into the model matrix.",
            temporal_rule="known only when the plate appearance terminates",
        ),
        excluded(
            "post_terminal_state",
            "plate_appearance",
            ["outs_after", "base_mask_after", "runs_scored"],
            "post_terminal_state",
            "State is downstream of the modeled terminal outcome.",
            temporal_rule="post-terminal",
        ),
        excluded(
            "source_provenance",
            "plate_appearance/player_prior",
            [
                "source_key", "source_mode", "source_version_id", "evidence_mode",
                "source_filename", "source_row_number", "source_row_checksum",
                "source_file_sha256", "row_checksum", "source_releases",
                "source_logical_tables", "source_logical_uris", "source_file_sha256s",
                "source_row_numbers", "source_row_sha256s", "source_derivation_checksum",
            ],
            "provenance",
            "Lineage-only values can encode source identity and are never predictors.",
        ),
        excluded(
            "identity_fields",
            "plate_appearance/player_prior",
            [
                "plate_appearance_id", "game_id", "retrosheet_game_id", "batter_id",
                "pitcher_id", "canonical_player_id", "lahman_player_id", "player_id",
                "visiting_team_id", "home_team_id", "batting_team_id", "pitching_team_id",
            ],
            "join_grouping_lineage",
            "Identifiers are restricted to exact joins, row lineage, date splits, and game-cluster bootstrap.",
            join_rule="exact stored-key/UUID join only; never model matrix",
        ),
        excluded(
            "actual_participants",
            "player_game_batting/player_game_pitching/starter_usage",
            ["actual_starter_target", "actual_appearance_target", "participant_evidence", "appearance_sequence"],
            "retrospective_actual_participation",
            "Historical actual participants are not proven pregame-known and are outside this PA component.",
            temporal_rule="retrospective actual participation",
            join_rule="not joined",
        ),
        excluded(
            "actual_weather",
            "weather",
            ["temperature_f", "wind_speed_mph", "wind_direction", "precipitation", "sky", "field_condition"],
            "historical_game_context",
            "Historical actual weather timing is not proven pregame and is outside this component.",
            temporal_rule="retrospective; prospective availability unproven",
            join_rule="not joined",
        ),
        excluded(
            "batter_side",
            "plate_appearance",
            ["batter_side"],
            "platoon_context",
            "Field is absent from the approved FD1 plate-appearance schema.",
            dtype="absent",
        ),
        excluded(
            "pitcher_hand",
            "plate_appearance",
            ["pitcher_hand"],
            "platoon_context",
            "Field is absent from the approved FD1 plate-appearance schema.",
            dtype="absent",
        ),
        excluded(
            "platoon",
            "derived",
            ["batter_side", "pitcher_hand"],
            "platoon_context",
            "Cannot be derived because both handedness inputs are absent.",
            dtype="absent",
        ),
    ]


def feature_schema_spec() -> dict[str, Any]:
    """Return the frozen logical Arrow projection used by the feature view."""

    fields = [
        {"name": "plate_appearance_id", "dtype": "string", "nullable": False, "role": "lineage"},
        {"name": "game_id", "dtype": "string", "nullable": False, "role": "cluster"},
        {"name": "game_date", "dtype": "string", "nullable": False, "role": "split"},
        {"name": "season", "dtype": "int16", "nullable": False, "role": "split"},
        {"name": "outcome", "dtype": "string", "nullable": False, "role": "target"},
        {"name": "batter_canonical_player_uuid", "dtype": "string", "nullable": False, "role": "lineage"},
        {"name": "pitcher_canonical_player_uuid", "dtype": "string", "nullable": False, "role": "lineage"},
        {"name": "batter_prior_season", "dtype": "int16", "nullable": True, "role": "lineage"},
        {"name": "batter_prior_eligible_from_season", "dtype": "int16", "nullable": True, "role": "lineage"},
        {"name": "pitcher_prior_season", "dtype": "int16", "nullable": True, "role": "lineage"},
        {"name": "pitcher_prior_eligible_from_season", "dtype": "int16", "nullable": True, "role": "lineage"},
        {"name": "context_inning", "dtype": "int16", "nullable": False, "role": "feature"},
        {"name": "context_top_bottom", "dtype": "int8", "nullable": False, "role": "feature"},
        {"name": "context_outs_before", "dtype": "int8", "nullable": False, "role": "feature"},
        {"name": "context_base_mask_before", "dtype": "int8", "nullable": False, "role": "feature"},
        {"name": "context_batting_score_diff_before", "dtype": "int16", "nullable": False, "role": "feature"},
    ]
    for name in BATTER_FEATURES + PITCHER_FEATURES:
        fields.append(
            {
                "name": name,
                "dtype": "bool" if name.endswith("_missing") else "float64",
                "nullable": False if name.endswith("_missing") else True,
                "role": "feature",
            }
        )
    return {
        "schemaVersion": FEATURE_VIEW_SCHEMA_VERSION,
        "contractName": FEATURE_CONTRACT_NAME,
        "contractVersion": FEATURE_CONTRACT_VERSION,
        "fields": fields,
    }


def feature_schema_sha() -> str:
    return sha256_bytes(canonical_json_bytes(feature_schema_spec()))


def feature_contract_payload() -> dict[str, Any]:
    """Frozen, outcome-independent feature/model policy for Phase 3."""

    return {
        "schemaVersion": FEATURE_CONTRACT_SCHEMA_VERSION,
        "contractName": FEATURE_CONTRACT_NAME,
        "contractVersion": FEATURE_CONTRACT_VERSION,
        "sport": "MLB",
        "component": "PLATE_APPEARANCE_SIMULATOR",
        "population": "strict_deployable",
        "seasons": list(TARGET_SEASONS),
        "classOrder": list(PA_CLASS_ORDER),
        "timingBoundary": {
            "scope": "CONDITIONAL_PRE_TERMINAL_PLATE_APPEARANCE_STATE",
            "notClaimedPregameKnown": True,
            "strictSameGamePregameEligible": False,
            "allowedPhysicalFields": [
                "inning",
                "top_bottom",
                "outs_before",
                "base_mask_before",
                "visiting_score_before",
                "home_score_before",
            ],
            "topBottomConvention": {
                "0": "VISITING_TEAM_BATS",
                "1": "HOME_TEAM_BATS",
            },
            "battingScoreDifference": (
                "top_bottom=0: visiting_score_before-home_score_before; "
                "top_bottom=1: home_score_before-visiting_score_before"
            ),
            "excluded": [
                "post_terminal_state",
                "terminal_outcome_as_feature",
                "handedness_absent",
                "platoon_absent",
                "ids_as_predictors",
            ],
        },
        "priorPolicy": {
            "identityJoin": "EXACT_CANONICAL_UUID_ONLY",
            "selection": "LATEST_SOURCE_SEASON_WITH_ELIGIBLE_FROM_SEASON_LE_TARGET",
            "domains": {"batter": "BATTING", "pitcher": "PITCHING"},
            "sameSeasonSourceRejected": True,
            "invalidDenominator": "MISSING",
            "imputation": "FOLD_TRAINING_ONLY_MEAN_WITH_EMPTY_COLUMN_ZERO_GUARD",
            "missingIndicators": ["batter_prior_missing", "pitcher_prior_missing"],
        },
        "featureNames": list(FEATURE_NAMES),
        "fieldDefinitions": _included_field_definitions(),
        "consideredExclusions": _considered_exclusions(),
        "candidateFeatures": {
            key: list(value) for key, value in CANDIDATE_FEATURES.items()
        },
        "experimentPolicy": {
            "cGrid": list(C_GRID),
            "penalty": "L2",
            "solver": "LBFGS",
            "multiclass": "TRUE_MULTINOMIAL",
            "innerSplit": "CHRONOLOGICAL_DATE_ATOMIC_2023_FIRST_CUMULATIVE_GE_80_PERCENT",
            "selectionOrder": ["logLoss", "brierScore", "candidateOrdinal"],
            "candidateValidation": "FIT_2023_VALIDATE_2024",
            "frozenFinalValidation": "REFIT_2023_2024_VALIDATE_2025",
            "minimumFinalRefits": ["C0", "C1", "SELECTED"],
            "no2025Tuning": True,
            "convergence": "FAIL_CLOSED",
        },
        "calibrationPolicy": {
            "method": "SCALAR_TEMPERATURE_ON_LOG_PROBABILITIES",
            "fitSeason": 2024,
            "applicationSeason": 2025,
            "retention": "LOG_LOSS_AND_BRIER_NON_WORSE_WITH_ABSOLUTE_TOLERANCE",
            "tolerance": DECISION_TOLERANCE,
        },
        "bootstrapPolicy": {
            "unit": "game_id",
            "folds": [2024, 2025],
            "comparators": ["C0", "C1"],
            "defaultResamples": 500,
            "defaultSeed": 20260817,
        },
        "terminalDecisionPolicy": {
            "frozenBeforeLiveEvaluation": True,
            "tolerance": DECISION_TOLERANCE,
            "challenger": {
                "logLoss": "SELECTED_STRICTLY_BEATS_C0_IN_2024_AND_2025",
                "brier": "SELECTED_NON_WORSE_THAN_C0_IN_2024_AND_2025",
                "calibration": (
                    "FINAL_SELECTED_TOP_LABEL_ECE_NON_WORSE_THAN_C0_IN_BOTH_FOLDS_"
                    "AND_ALL_CLASSWISE_ECE_FINITE"
                ),
                "integrity": "ALL_REQUIRED_FITS_CONVERGED_AND_ALL_GOVERNANCE_CHECKS_PASS",
            },
            "baseline": "VALID_MIXED_SMALL_OR_UNCERTAIN_EVIDENCE",
            "rejected": (
                "ALL_SUBSTANTIVE_C1_C4_WORSE_OR_UNSTABLE_IN_2024_AND_FROZEN_SELECTED_"
                "CONSISTENTLY_WORSE_THAN_C0_IN_2025"
            ),
            "blocked": "INTEGRITY_OR_EXECUTION_FAILURE_ONLY",
        },
        "schemaSha256": feature_schema_sha(),
    }


def feature_contract_sha(payload: Mapping[str, Any] | None = None) -> str:
    value = feature_contract_payload() if payload is None else deepcopy(dict(payload))
    return sha256_bytes(canonical_json_bytes(value))


def canonical_sha(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(value)))


__all__ = [
    "BRIDGE_ALIAS_AUTHORITY_SHA",
    "BRIDGE_DIMENSION_AUTHORITY_SHA",
    "BRIDGE_MANIFEST_SHA",
    "BATTER_FEATURES",
    "CANDIDATE_FEATURES",
    "CONTEXT_FEATURES",
    "C_GRID",
    "DECISION_TOLERANCE",
    "EXPECTED_SEASON_ROWS",
    "EXPECTED_TOTAL_ROWS",
    "FEATURE_CONTRACT_NAME",
    "FEATURE_CONTRACT_SCHEMA_VERSION",
    "FEATURE_CONTRACT_VERSION",
    "FEATURE_NAMES",
    "FEATURE_VIEW_SCHEMA_VERSION",
    "LINEAGE_COLUMNS",
    "PARENT_DATASET_ID",
    "PARENT_DATASET_VERSION_ID",
    "PARENT_MANIFEST_SHA",
    "PARENT_PARTITION_AUTHORITY_SHA",
    "PITCHER_FEATURES",
    "RESEARCH_RUN_SCHEMA_VERSION",
    "TARGET_SEASONS",
    "canonical_sha",
    "feature_contract_payload",
    "feature_contract_sha",
    "feature_schema_sha",
    "feature_schema_spec",
]
