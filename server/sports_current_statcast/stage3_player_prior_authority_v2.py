"""Governed Wave 2 MLB player-state empirical-Bayes authority.

Wave 2 consumes the immutable sufficient-statistics companion published by
Wave 1.  It fits seven shared estimator instances for ten feature bindings,
with one immutable child per chronological fold and a separate all-development
child.  The module never imports an outcome model and never requests a target.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..persistence.db import Database
from ..sports_datasets.consumer import canonical_json_bytes
from . import stage3_player_prior_authority as prior_v1
from . import sufficient_stats
from .stage3_player_prior_artifact_store_v2 import (
    DEFAULT_AUTHORITY_ROOT,
    PriorArtifactStoreV2Error,
    load_artifact,
    load_current_bundle,
)
from .stage3_prior_estimators_v2 import (
    FLOAT64_CSS_TOLERANCE_MULTIPLIER,
    INTEGER_TOLERANCE,
    PROBABILITY_EPSILON,
    PriorEstimatorV2Error,
    dirichlet_posterior,
    fit_beta_binomial,
    fit_dirichlet_multinomial,
    fit_gamma_poisson_components,
    fit_normal_normal,
    gamma_poisson_posterior,
    normal_normal_posterior,
)


AUTHORITY_NAME = "MLB_PLAYER_STATE_PRIOR_AUTHORITY_V2"
SCHEMA_VERSION = "MLB_PLAYER_STATE_PRIOR_AUTHORITY_SCHEMA_V2"
DEFINITION_SCHEMA_VERSION = "MLB_PLAYER_STATE_PRIOR_DEFINITION_V2"
FITTED_SCHEMA_VERSION = "MLB_PLAYER_STATE_FITTED_PRIOR_V2"
BUNDLE_SCHEMA_VERSION = "MLB_PLAYER_STATE_PRIOR_FIT_BUNDLE_V2"
FOLD_CONTRACT_SCHEMA_VERSION = "MLB_PLAYER_STATE_PRIOR_FIVE_FOLD_CONTRACT_V1"
READY_GOVERNED_PRIOR_V2 = "READY_GOVERNED_PRIOR_V2"
DEVELOPMENT_START = "2023-03-30"
DEVELOPMENT_END = prior_v1.DEVELOPMENT_END
FINAL_OOT_START = "2026-08-14"
FINAL_OOT_END = "2026-08-27"
DEVELOPMENT_ROWS = 683_662
FINAL_OOT_ROWS = 14_067
HISTORY_CUTOFF = (
    "annual: season <= Y-1; rolling: source.gameDate < target.gameDate; "
    "same-date games excluded"
)
EXPECTED_COMPANION_MANIFEST_SHA256 = (
    "98673b65dc5eab61e39b16d1313c27bbb2cf908c525f80db579cb07a5cfdab33"
)
EXPECTED_GOLD_MANIFEST_SHA256 = (
    "67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758"
)
EXPECTED_COMPANION_REGISTRATION_ID = "sports-dataset-sufficient-stats-98673b65dc5eab61"
EXPECTED_COMPANION_DATASET_ID = "gold-table:gold_mlb_current_pa_sufficient_stats_v1"
EXPECTED_BINDING_AUTHORITY_CHECKSUM = (
    "dbee3d1f5f414e3edd28cee10cd563189438be1bc9c9e852f88c962a5a8f5287"
)
EXPECTED_BINDING_AUTHORITY_ID = (
    "MLB_SUFFICIENT_STATISTICS_BINDING_AUTHORITY_V1:sha256:"
    f"{EXPECTED_BINDING_AUTHORITY_CHECKSUM}"
)
EXPECTED_COMPANION_OBJECT_SHA256 = (
    "e58caddb54382037690d04b899a1c2f194a0089e0b73af6c0bbe2dfdcb2659d9",
    "8eaf2e551ac8bc19211188817485f76e47bdb98dd510c3506b131aa45a1b4515",
    "247687f7855132c13e860f9155c6334e3ec9f838b221e3003bce02ba6d6db851",
    "0dfad075fad4ff197833f60e1a0eb49287bc6c7aab475019d5a0d7de47bddf45",
    "350ff402906ede4f39ae164c39719a84c3514529ffdc65deebcab8cf0cf139ba",
)
EXPECTED_COMPANION_PHYSICAL_SCHEMA_SHA256 = (
    "8d5eb7f1318a4eed4642080b7ee3b445653401615d9ae44290a7b8b3ea85fb8f"
)
EXPECTED_COMPANION_VALIDATION_SHA256 = (
    "4a9209aa7e6850d2b3e2ec721514790c47fcc2c4f7072d2302183ff18a740fe7"
)
EXPECTED_SOURCE_CURRENT_SILVER_SHA256 = (
    "fcfb95724f2cc44ae45555897365497c538f5ea6303fe041dd4afa9697c62d2a"
)
EXPECTED_GOLD_UPSTREAM_AUTHORITY_SHA256 = (
    "66cba1ab11b7d61732d81c2db4f550c9d4c16eeab8c593071e4cb13c1cd01e09"
)
EXPECTED_GOLD_PARTITION_SHA256 = (
    "d3be5d47bc5a50e81e9fdf253a828ea43223b9a2dd6dc43851f198e4fbb926df",
    "a9b86250209061c8a31a815f7bdbbf3a78f817e908c07d581f75a957d8ddc833",
    "4c4af8a20b2b5f9b88d63753eff128a71f29117f8b28f3d647112a5b031721d4",
    "dae01549bf60070e220cbf6b65625a010352a38c54f831d96237d3d4d42a5230",
)
EXPECTED_ROW_IDENTITY_SHA256 = (
    "4be4b0ec6517d0a2b43f478c1da7d526c5fab160681c2167b7918a1fdfb7e3cc"
)
EXPECTED_OOT_FOOTER_SHA256 = (
    "a9afc4576be3225e75c7b6e9451b866276f0bb87c0f66aaf7dd35d3319d63fae"
)


class PlayerPriorAuthorityV2Error(RuntimeError):
    """A Wave 2 authority, evidence, fit, or transform failed closed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _normalized_file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _public_authority(authority: Any) -> dict[str, Any]:
    if callable(getattr(authority, "public", None)):
        return dict(authority.public())
    if isinstance(authority, Mapping):
        return dict(authority)
    return {}


_FAMILIES: dict[str, dict[str, Any]] = {
    "PITCHER_GS_APPEARANCE": {
        "method": "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES",
        "features": ("pitcher_gs_per_g",),
        "side": "PITCHER",
        "playerKey": "pitcherCanonicalPlayerId",
        "window": "LATEST_ELIGIBLE_PRIOR_SEASON",
        "indicatorColumns": ("pitcher_prior_missing",),
        "sourceColumns": ("pitcher_prior_g", "pitcher_prior_gs"),
        "exposureColumn": "pitcher_prior_g",
        "componentNames": ("START", "NON_START_APPEARANCE"),
        "formulaId": "PITCHER_GS_DIV_G_V1",
        "formula": "pitcher_prior_gs / pitcher_prior_g",
        "establishedThreshold": None,
    },
    "PITCHER_LAST250_WHIFF": {
        "method": "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES",
        "features": ("pitcher_last250_whiff_rate",),
        "side": "PITCHER",
        "playerKey": "pitcherCanonicalPlayerId",
        "window": "LAST_250_BATTERS_FACED_COMPLETED_DAYS_ONLY",
        "indicatorColumns": ("pitcher_last250_insufficient", "pitcher_last250_whiff_missing"),
        "sourceColumns": ("pitcher_last250_swing_count", "pitcher_last250_whiff_count"),
        "exposureColumn": "pitcher_last250_swing_count",
        "componentNames": ("WHIFF", "CONTACT"),
        "formulaId": "PITCHER_LAST250_WHIFF_DIV_SWING_V1",
        "formula": "pitcher_last250_whiff_count / pitcher_last250_swing_count",
        "establishedThreshold": 250,
    },
    "BATTER_LAST100_WHIFF": {
        "method": "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES",
        "features": ("batter_last100_whiff_rate",),
        "side": "BATTER",
        "playerKey": "batterCanonicalPlayerId",
        "window": "LAST_100_PLATE_APPEARANCES_COMPLETED_DAYS_ONLY",
        "indicatorColumns": ("batter_last100_insufficient", "batter_last100_whiff_missing"),
        "sourceColumns": ("batter_last100_swing_count", "batter_last100_whiff_count"),
        "exposureColumn": "batter_last100_swing_count",
        "componentNames": ("WHIFF", "CONTACT"),
        "formulaId": "BATTER_LAST100_WHIFF_DIV_SWING_V1",
        "formula": "batter_last100_whiff_count / batter_last100_swing_count",
        "establishedThreshold": 100,
    },
    "PITCHER_LAST250_PITCH_COMPOSITION": {
        "method": "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES",
        "features": (
            "pitcher_last250_fastball_usage",
            "pitcher_last250_breaking_usage",
            "pitcher_last250_offspeed_usage",
        ),
        "side": "PITCHER",
        "playerKey": "pitcherCanonicalPlayerId",
        "window": "LAST_250_BATTERS_FACED_COMPLETED_DAYS_ONLY",
        "indicatorColumns": ("pitcher_last250_insufficient",),
        "sourceColumns": (
            "pitcher_last250_pitch_count",
            "pitcher_last250_fastball_count",
            "pitcher_last250_breaking_count",
            "pitcher_last250_offspeed_count",
            "pitcher_last250_other_or_unclassified_pitch_count",
        ),
        "exposureColumn": "pitcher_last250_pitch_count",
        "componentNames": ("FASTBALL", "BREAKING", "OFFSPEED", "OTHER_OR_UNCLASSIFIED"),
        "formulaId": "PITCHER_LAST250_FULL_PITCH_COMPOSITION_V1",
        "formula": "{fastball,breaking,offspeed,other_or_unclassified} / all pitches",
        "establishedThreshold": 250,
    },
    "BATTER_PRIOR_AB_OUTCOME_COMPOSITION": {
        "method": "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES",
        "features": ("batter_avg", "batter_slg"),
        "side": "BATTER",
        "playerKey": "batterCanonicalPlayerId",
        "window": "LATEST_ELIGIBLE_PRIOR_SEASON",
        "indicatorColumns": ("batter_prior_missing",),
        "sourceColumns": (
            "batter_prior_ab",
            "batter_prior_h",
            "batter_prior_2b",
            "batter_prior_3b",
            "batter_prior_hr",
        ),
        "exposureColumn": "batter_prior_ab",
        "componentNames": ("SINGLE", "DOUBLE", "TRIPLE", "HOME_RUN", "NON_HIT_AT_BAT"),
        "formulaId": "BATTER_PRIOR_FIVE_CELL_AB_OUTCOME_V1",
        "formula": "{1B,2B,3B,HR,AB-H} / AB; AVG and SLG are posterior linear contrasts",
        "establishedThreshold": None,
    },
    "PITCHER_PRIOR_WHIP_COMPONENTS": {
        "method": "GAMMA_POISSON_COMPONENT_SHRINKAGE",
        "features": ("pitcher_whip",),
        "side": "PITCHER",
        "playerKey": "pitcherCanonicalPlayerId",
        "window": "LATEST_ELIGIBLE_PRIOR_SEASON",
        "indicatorColumns": ("pitcher_prior_missing",),
        "sourceColumns": ("pitcher_prior_ipouts", "pitcher_prior_h", "pitcher_prior_bb"),
        "exposureColumn": "pitcher_prior_ipouts",
        "componentNames": ("HITS_ALLOWED_PER_OUT", "WALKS_ALLOWED_PER_OUT"),
        "formulaId": "REGISTERED_WHIP_3_TIMES_H_PLUS_BB_DIV_IPOUTS_V1",
        "formula": "3 * (pitcher_prior_h + pitcher_prior_bb) / pitcher_prior_ipouts",
        "establishedThreshold": None,
    },
    "PITCHER_LAST250_FASTBALL_VELOCITY": {
        "method": "NORMAL_NORMAL_EMPIRICAL_BAYES",
        "features": ("pitcher_last250_avg_fastball_velocity",),
        "side": "PITCHER",
        "playerKey": "pitcherCanonicalPlayerId",
        "window": "LAST_250_BATTERS_FACED_COMPLETED_DAYS_ONLY",
        "indicatorColumns": ("pitcher_last250_insufficient", "pitcher_last250_velocity_missing"),
        "sourceColumns": (
            "pitcher_last250_fastball_velocity_count",
            "pitcher_last250_fastball_velocity_sum",
            "pitcher_last250_fastball_velocity_sumsq",
        ),
        "exposureColumn": "pitcher_last250_fastball_velocity_count",
        "componentNames": ("COUNT", "SUM", "SUMSQ"),
        "formulaId": "PITCHER_LAST250_FASTBALL_VELOCITY_SUFFICIENT_STATS_V1",
        "formula": "mean=sum/count; variance=(sumsq-sum^2/count)/(count-1)",
        "establishedThreshold": 250,
    },
}

FEATURE_TO_FAMILY: dict[str, str] = {
    feature: family_id
    for family_id, family in _FAMILIES.items()
    for feature in family["features"]
}
WAVE2_FEATURES = tuple(
    feature
    for feature in prior_v1.PRIOR_FEATURES
    if feature in FEATURE_TO_FAMILY
)
RETIRED_FEATURES = tuple(sorted(prior_v1.RETIRED_PRIOR_FEATURES))


def _feature_prefix(feature: str) -> str:
    return f"{feature}__prior_v2"


def _family_audit_outputs(feature: str, family_id: str) -> list[str]:
    """Return every materialized family output that is evidence, not a candidate.

    Shared composition evidence is repeated in each binding contract deliberately:
    a consumer resolving only one binding must still see that its posterior estimate
    came from one jointly fitted simplex rather than an independent rate model.
    """

    family = _FAMILIES[family_id]
    method = str(family["method"])
    if method in {
        "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES",
        "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES",
    }:
        prefix = f"mlb_prior_v2__{family_id.lower()}"
        output: list[str] = []
        for name in family["componentNames"]:
            token = str(name).lower()
            output.extend(
                (
                    f"{prefix}__posterior_{token}",
                    f"{prefix}__posterior_alpha_{token}",
                    f"{prefix}__posterior_variance_{token}",
                )
            )
        for left, left_name in enumerate(family["componentNames"]):
            for right, right_name in enumerate(family["componentNames"]):
                if right > left:
                    output.append(
                        f"{prefix}__posterior_covariance_{str(left_name).lower()}__{str(right_name).lower()}"
                    )
        return output
    prefix = _feature_prefix(feature)
    if method == "GAMMA_POISSON_COMPONENT_SHRINKAGE":
        return [
            f"{prefix}__hits_per_out_posterior_variance",
            f"{prefix}__walks_per_out_posterior_variance",
            f"{prefix}__posterior_shape_hits",
            f"{prefix}__posterior_shape_walks",
            f"{prefix}__posterior_rate",
        ]
    if method == "NORMAL_NORMAL_EMPIRICAL_BAYES":
        return [
            f"{prefix}__sample_mean",
            f"{prefix}__sample_variance",
            f"{prefix}__centered_sum_squares",
        ]
    raise PlayerPriorAuthorityV2Error(
        "PRIOR_V2_ESTIMATOR_UNSUPPORTED", f"Unsupported estimator for {family_id}."
    )


def _binding_template(feature: str) -> dict[str, Any]:
    family_id = FEATURE_TO_FAMILY[feature]
    family = _FAMILIES[family_id]
    prefix = _feature_prefix(feature)
    model_candidates = [
        f"{prefix}__posterior_mean",
        f"{prefix}__log1p_effective_n",
        f"{prefix}__posterior_reliability",
        f"{prefix}__posterior_std",
    ]
    if feature == "pitcher_whip":
        model_candidates.extend(
            (
                f"{prefix}__hits_per_out_posterior_mean",
                f"{prefix}__walks_per_out_posterior_mean",
            )
        )
    audit_only = [
        f"{prefix}__effective_n",
        f"{prefix}__prior_strength",
        f"{prefix}__posterior_variance",
        f"{prefix}__history_state",
        f"{prefix}__prior_level",
        f"{prefix}__formula_id",
        f"{prefix}__family_id",
    ]
    audit_only.extend(_family_audit_outputs(feature, family_id))
    base = prior_v1.feature_binding(feature) or {"feature": feature}
    return {
        **copy.deepcopy(base),
        "feature": feature,
        "featureName": feature,
        "authorityName": AUTHORITY_NAME,
        "familyId": family_id,
        "method": family["method"],
        "requiredEstimator": family["method"],
        "status": prior_v1.BINDING_READY_REQUIRES_WAVE2_ENGINE,
        "executable": False,
        "selectable": False,
        "blockedReason": None,
        "playerIdentityFeature": family["playerKey"],
        "exposureFeature": family["exposureColumn"],
        "exposureDefinition": family["formula"],
        "historyWindow": family["window"],
        "historyCutoff": HISTORY_CUTOFF,
        "missingIndicatorFeatures": list(family["indicatorColumns"]),
        "establishedThreshold": family["establishedThreshold"],
        "formulaId": family["formulaId"],
        "operationFormula": family["formula"],
        "componentNames": list(family["componentNames"]),
        "requiredSufficientStatistics": list(family["sourceColumns"]),
        "populationPriorAuthority": "REQUIRES_VERIFIED_WAVE2_FIT_BUNDLE",
        "hierarchy": ["PLAYER_HISTORY", "MLB_LEAGUE_POPULATION"],
        "roleAuthority": "NOT_AVAILABLE_IN_CURRENT_GOLD_NOT_INVENTED",
        "decayAuthority": (
            "NO_DECAY_ANNUAL_STATE_SOURCE_AGE_NOT_MATERIALIZED"
            if family["window"] == "LATEST_ELIGIBLE_PRIOR_SEASON"
            else "NO_ADDITIONAL_DECAY_ALREADY_RECENCY_BOUNDED_WINDOW"
        ),
        "rawFeatureDecision": "RETAIN_RAW_FOR_QA_ONLY_DERIVED_OUTPUTS_REQUIRE_LATER_ABLATION",
        "outputContract": {
            "modelCandidateOutputs": model_candidates,
            "auditOnlyOutputs": audit_only,
            "recommendedAblationBundle": model_candidates[:3],
            "rawFeatureSelectable": False,
            "defaultSelected": False,
        },
        "derivedOutputs": {
            "posteriorMean": model_candidates[0],
            "log1pEffectiveN": model_candidates[1],
            "posteriorReliability": model_candidates[2],
            "posteriorStd": model_candidates[3],
            "effectiveN": audit_only[0],
            "priorStrength": audit_only[1],
            "posteriorVariance": audit_only[2],
            "historyState": audit_only[3],
            "priorLevel": audit_only[4],
            "formulaId": audit_only[5],
            "familyId": audit_only[6],
        },
    }


_BINDINGS = {feature: _binding_template(feature) for feature in WAVE2_FEATURES}


def authority_configuration() -> dict[str, Any]:
    estimator_path = Path(__file__).with_name("stage3_prior_estimators_v2.py")
    store_path = Path(__file__).with_name("stage3_player_prior_artifact_store_v2.py")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "authorityName": AUTHORITY_NAME,
        "implementationSha256": _normalized_file_sha(Path(__file__)),
        "estimatorImplementationSha256": _normalized_file_sha(estimator_path),
        "artifactStoreImplementationSha256": _normalized_file_sha(store_path),
        "families": copy.deepcopy(_FAMILIES),
        "featureToFamily": dict(FEATURE_TO_FAMILY),
        "populationFit": {
            "scope": "TRAINING_ROWS_OF_EACH_EXACT_CHRONOLOGICAL_FOLD_ONLY",
            "unit": "LATEST_VALID_PLAYER_STATE_AT_OR_BEFORE_TRAINING_CUTOFF",
            "deduplicationKey": ["familyId", "playerId", "game_date"],
            "sameDayExactDuplicates": "DROP",
            "sameDayConflicts": "FAIL_CLOSED",
            "validationRowsFitParameters": False,
            "finalOotRowsFitParameters": False,
        },
        "estimatorConfiguration": {
            "physicalFloatingPointDtype": "float64",
            "fixedOrderSummation": "MATH_FSUM_AFTER_DETERMINISTIC_PLAYER_STATE_ORDERING",
            "probabilityEpsilon": PROBABILITY_EPSILON,
            "dirichletMultinomial": {
                "populationCellPseudocount": 0.5,
                "fitMethod": "METHOD_OF_MOMENTS_ON_LATEST_TRAINING_ONLY_PLAYER_STATES",
                "concentrationCandidateAggregation": "DETERMINISTIC_MEDIAN_OF_POSITIVE_CELL_CANDIDATES",
                "underidentifiedFallback": "TRAINING_MEDIAN_EXPOSURE",
                "lowerBound": PROBABILITY_EPSILON,
                "upperBound": "TRAINING_EXPOSURE_LINEAR_P95",
            },
            "gammaPoissonComponents": {
                "componentCountPseudocount": 0.5,
                "exposureDenominatorPseudocount": 1.0,
                "fitMethod": "METHOD_OF_MOMENTS_ON_LATEST_TRAINING_ONLY_PLAYER_STATES",
                "equivalentExposureCandidateAggregation": "DETERMINISTIC_MEDIAN_OF_POSITIVE_COMPONENT_CANDIDATES",
                "underidentifiedFallback": "TRAINING_MEDIAN_EXPOSURE",
                "lowerBound": PROBABILITY_EPSILON,
                "upperBound": "TRAINING_EXPOSURE_LINEAR_P95",
            },
            "normalNormal": {
                "populationMean": "OBSERVATION_COUNT_WEIGHTED_AFTER_LATEST_PLAYER_STATE_DEDUPLICATION",
                "withinPlayerVariance": "POOLED_CENTERED_SUM_OF_SQUARES_OVER_POOLED_DEGREES_OF_FREEDOM",
                "betweenPlayerVariance": "SAMPLE_VARIANCE_OF_PLAYER_MEANS_MINUS_MEAN_SAMPLING_VARIANCE",
                "equivalentObservationCountFallback": "TRAINING_MEDIAN_OBSERVATION_COUNT",
                "lowerBound": PROBABILITY_EPSILON,
                "upperBound": "TRAINING_OBSERVATION_COUNT_LINEAR_P95",
                "negativeCssToleranceMultiplier": FLOAT64_CSS_TOLERANCE_MULTIPLIER,
                "velocityClipping": False,
            },
        },
        "foldContract": {
            "count": 5,
            "training": "EXPANDING",
            "validation": "CONTIGUOUS_DATE_ATOMIC_EQUAL_CANONICAL_GAME_COUNT",
            "warmup": "2023_DEVELOPMENT_ROWS_TRAINING_ONLY",
            "optimizer": "MIN_MAX_SCALED_DEVIATION_THEN_SQUARED_DEVIATION_THEN_ENDPOINTS",
            "featureSetRegistered": False,
        },
        "chronology": {"playerHistory": HISTORY_CUTOFF, "developmentEnd": DEVELOPMENT_END},
        "numerics": {
            "integerTolerance": INTEGER_TOLERANCE,
            "compositionSumTolerance": 1e-12,
            "negativeCssTolerance": "64 * float64_epsilon * max(abs(sumsq), abs(sum^2/n), 1)",
            "velocityClipping": False,
        },
        "failurePrecedence": [
            "SOURCE_UNAVAILABLE",
            "COMPUTATION_FAILURE",
            "TRUE_COLD_START",
            "TRUE_NO_OPPORTUNITY",
            "SPARSE_OR_ESTABLISHED_HISTORY",
        ],
        "rights": {
            "effectiveStatus": "GOVERNED_LOCAL_RESEARCH_ONLY",
            "allowedUse": "LOCAL_PRIVATE_MODEL_DEVELOPMENT",
            "attributionRequired": True,
            "commercialRights": "UNCLEAR_REQUIRES_REVIEW",
        },
        "prohibitedActivity": {
            "targetRead": False,
            "finalOotPayloadRead": False,
            "predictiveModelFit": False,
            "featureSetRegistration": False,
            "policyAdoption": False,
        },
        "bindings": [copy.deepcopy(_BINDINGS[feature]) for feature in WAVE2_FEATURES],
    }


def authority_configuration_checksum() -> str:
    return _sha256(authority_configuration())


def required_input_columns(features: Sequence[str] | None = None) -> tuple[str, ...]:
    selected = tuple(features or WAVE2_FEATURES)
    retired = sorted(set(selected) & set(RETIRED_FEATURES))
    if retired:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_FEATURE_RETIRED",
            f"Retired feature(s) have no Wave 2 executable output: {', '.join(retired)}.",
        )
    unknown = sorted(set(selected) - set(WAVE2_FEATURES))
    if unknown:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FEATURE_UNSUPPORTED", f"Unsupported Wave 2 feature(s): {', '.join(unknown)}."
        )
    columns = {"canonicalPaId", "canonicalGameId", "game_date", "season"}
    for feature in selected:
        family = _FAMILIES[FEATURE_TO_FAMILY[feature]]
        columns.add(family["playerKey"])
        columns.update(family["sourceColumns"])
        columns.update(family["indicatorColumns"])
    return tuple(sorted(columns))


def _manifest_file(root: Path, manifest_sha: str) -> Path:
    return (
        Path(root)
        / "sufficient-statistics"
        / "publications"
        / "sha256"
        / manifest_sha
        / "manifest.json"
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_MANIFEST_INVALID", f"{path} is not an object.")
    return value


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _oot_footer_null_evidence(path: Path, payload_columns: Sequence[str]) -> dict[str, Any]:
    with pq.ParquetFile(path) as parquet:
        column_indexes = {
            name: index for index, name in enumerate(parquet.schema_arrow.names)
        }
        evidence: list[dict[str, Any]] = []
        for name in payload_columns:
            index = column_indexes.get(name)
            if index is None:
                raise PlayerPriorAuthorityV2Error(
                    "PRIOR_V2_OOT_FOOTER_COLUMN_MISSING", f"FINAL_OOT footer lacks {name}."
                )
            null_count = 0
            num_values = 0
            for group_index in range(parquet.metadata.num_row_groups):
                column = parquet.metadata.row_group(group_index).column(index)
                statistics = column.statistics
                if statistics is None or statistics.null_count is None:
                    raise PlayerPriorAuthorityV2Error(
                        "PRIOR_V2_OOT_NULL_EVIDENCE_INCOMPLETE",
                        f"FINAL_OOT footer lacks complete null statistics for {name}.",
                    )
                null_count += int(statistics.null_count)
                num_values += int(statistics.num_values)
            if null_count != int(parquet.metadata.num_rows) or num_values != 0:
                raise PlayerPriorAuthorityV2Error(
                    "PRIOR_V2_OOT_PAYLOAD_MATERIALIZED",
                    f"FINAL_OOT payload {name} is not entirely unmaterialized.",
                )
            evidence.append({"column": name, "nullCount": null_count, "numValues": num_values})
        content = {
            "method": "PARQUET_FOOTER_COLUMN_STATISTICS_ONLY_NO_PAYLOAD_DECODE",
            "rowCount": int(parquet.metadata.num_rows),
            "payloadColumns": evidence,
        }
        return {**content, "checksum": _sha256(content)}


def _key_frame(paths: Sequence[Path]) -> pd.DataFrame:
    tables = [pq.read_table(path, columns=["canonicalPaId", "datasetRole"]) for path in paths]
    frame = pa.concat_tables(tables).to_pandas(split_blocks=True)
    if bool(frame[["canonicalPaId", "datasetRole"]].isna().any(axis=None)):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_KEY_IDENTITY_INVALID", "Authority key projection contains nulls.")
    if bool(frame.duplicated(["canonicalPaId"]).any()):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_KEY_IDENTITY_DUPLICATE", "Authority canonical PA keys are not unique.")
    return frame.sort_values(["canonicalPaId", "datasetRole"], kind="mergesort").reset_index(drop=True)


def _key_checksum(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for pa_id, role in frame[["canonicalPaId", "datasetRole"]].itertuples(index=False, name=None):
        digest.update(str(pa_id).encode("utf-8"))
        digest.update(b"\x1f")
        digest.update(str(role).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def authenticate_companion(
    database: Database,
    project_authority: Any,
    *,
    output_root: Path = sufficient_stats.DEFAULT_CURRENT_GOLD_ROOT,
    expected_registration_id: str = EXPECTED_COMPANION_REGISTRATION_ID,
    expected_manifest_sha256: str = EXPECTED_COMPANION_MANIFEST_SHA256,
) -> dict[str, Any]:
    """Authenticate companion/Gold identity while keeping OOT payload sealed."""

    public = _public_authority(project_authority)
    gold_sha = str(public.get("goldManifestSha") or getattr(project_authority, "gold_manifest_sha", ""))
    if gold_sha != EXPECTED_GOLD_MANIFEST_SHA256:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_GOLD_MANIFEST_MISMATCH",
            "The project Current Gold differs from the exact Wave 2 handoff.",
        )
    binding = sufficient_stats.registered_sufficient_statistics_authority(
        database,
        expected_gold_manifest_sha256=gold_sha,
        output_root=Path(output_root),
    )
    if binding is None:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_COMPANION_AUTHENTICATION_FAILED",
            "The inactive sufficient-statistics registration or one of its immutable children failed verification.",
        )
    manifest_sha = str(binding.get("manifestSha256") or "")
    if manifest_sha != expected_manifest_sha256:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_COMPANION_MANIFEST_MISMATCH", "The companion manifest differs from the Wave 2 handoff."
        )
    manifest_path = _manifest_file(Path(output_root), manifest_sha)
    if not manifest_path.is_file() or _file_sha(manifest_path) != manifest_sha:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_COMPANION_MANIFEST_INVALID", "Companion manifest content differs.")
    manifest = _load_json(manifest_path)
    partitions = list(manifest.get("partitions") or [])
    if len(partitions) != 5:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_COMPANION_PARTITIONS_INVALID", "Exactly five companion partitions are required.")
    resolved_root = Path(output_root).resolve()
    paths: list[Path] = []
    development_paths: list[Path] = []
    oot_paths: list[Path] = []
    for partition in partitions:
        path = (resolved_root / str(partition.get("relativePath") or "")).resolve()
        if not path.is_relative_to(resolved_root) or not path.is_file() or _file_sha(path) != partition.get("sha256"):
            raise PlayerPriorAuthorityV2Error("PRIOR_V2_COMPANION_PARTITION_INVALID", "A companion partition failed its path/SHA contract.")
        paths.append(path)
        if partition.get("partitionRole") == "DEVELOPMENT_SELECTION":
            development_paths.append(path)
        elif partition.get("partitionRole") == sufficient_stats.FINAL_OOT_SEALED:
            oot_paths.append(path)
    if len(development_paths) != 4 or len(oot_paths) != 1:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_COMPANION_ROLE_INVALID", "Companion partition roles differ.")
    allowed_oot = {"canonicalPaId", "datasetRole", "materialization_status", "materialization_reason"}
    payload_columns = [name for name in sufficient_stats.sufficient_statistics_schema().names if name not in allowed_oot]
    oot_footer = _oot_footer_null_evidence(oot_paths[0], payload_columns)
    oot_keys = pq.read_table(
        oot_paths[0],
        columns=["canonicalPaId", "datasetRole", "materialization_status", "materialization_reason"],
    ).to_pandas(split_blocks=True)
    if (
        len(oot_keys) != FINAL_OOT_ROWS
        or set(oot_keys["datasetRole"].astype(str)) != {"FINAL_OOT"}
        or set(oot_keys["materialization_status"].astype(str)) != {"UNMATERIALIZED"}
        or set(oot_keys["materialization_reason"].astype(str)) != {"FINAL_OOT_SEALED"}
    ):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_OOT_KEY_CONTRACT_INVALID", "FINAL_OOT key-only state differs.")

    gold_manifest_path = (
        resolved_root / "publications" / "sha256" / gold_sha / "manifest.json"
    )
    if not gold_manifest_path.is_file() or _file_sha(gold_manifest_path) != gold_sha:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_GOLD_MANIFEST_INVALID", "Current Gold manifest failed verification.")
    gold_manifest = _load_json(gold_manifest_path)
    gold_partitions = list(gold_manifest.get("partitions") or [])
    gold_paths = [(resolved_root / str(item["relativePath"])).resolve() for item in gold_partitions]
    if not gold_paths or any(not path.is_relative_to(resolved_root) or not path.is_file() for path in gold_paths):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_GOLD_PARTITIONS_INVALID", "Current Gold key partitions are unavailable.")
    if any(
        _file_sha(path) != str(item.get("sha256") or "")
        or path.stat().st_size != int(item.get("byteCount") or -1)
        for path, item in zip(gold_paths, gold_partitions, strict=True)
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_GOLD_PARTITION_CHECKSUM_MISMATCH",
            "A Current Gold parent partition failed its exact byte/SHA contract.",
        )
    companion_silver_sha = str(
        ((manifest.get("sourceAuthorities") or {}).get("currentSilver") or {}).get(
            "currentSilverManifestSha256"
        )
        or ""
    )
    gold_silver_sha = str(
        (gold_manifest.get("sourceAuthorities") or {}).get(
            "currentSilverManifestSha256"
        )
        or ""
    )
    declared_upstream = (manifest.get("sourceAuthorities") or {}).get(
        "goldDeclaredUpstream"
    ) or {}
    if (
        not re.fullmatch(r"[0-9a-f]{64}", companion_silver_sha)
        or companion_silver_sha != gold_silver_sha
        or declared_upstream.get("verifiedExact") is not True
        or ((declared_upstream.get("verification") or {}).get("currentSilverManifestSha256"))
        != "DIRECT_EXACT_MATCH"
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_CURRENT_SILVER_PARENT_MISMATCH",
            "Companion, Current Gold, and Current Silver parent identities do not reconcile.",
        )
    companion_keys = _key_frame(paths)
    gold_keys = _key_frame(gold_paths)
    if len(companion_keys) != len(gold_keys) or not companion_keys.equals(gold_keys):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_GOLD_COMPANION_KEY_MISMATCH", "Companion/Gold row identity differs.")
    roles = Counter(companion_keys["datasetRole"].astype(str))
    if roles != Counter({"DEVELOPMENT_SELECTION": DEVELOPMENT_ROWS, "FINAL_OOT": FINAL_OOT_ROWS}):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_COMPANION_ROLE_COUNTS_INVALID", "Companion role counts differ.")
    with database.connection() as connection:
        registration = connection.execute(
            "SELECT registration_id, active, validation_status, manifest_sha, rights_status FROM sports_dataset_registrations WHERE registration_id = ?",
            (expected_registration_id,),
        ).fetchone()
    if (
        registration is None
        or int(registration["active"]) != 0
        or str(registration["validation_status"]) != "VALID"
        or str(registration["manifest_sha"]) != manifest_sha
        or str(registration["rights_status"]) != "GOVERNED_LOCAL_RESEARCH_ONLY"
    ):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_COMPANION_REGISTRATION_INVALID", "Inactive companion registration differs.")
    key_sha = _key_checksum(companion_keys)
    public_evidence = {
        "registrationId": expected_registration_id,
        "registrationActive": False,
        "bindingAuthority": copy.deepcopy(binding),
        "datasetId": manifest["datasetId"],
        "manifestSha256": manifest_sha,
        "objectSha256": [str(item["sha256"]) for item in partitions],
        "physicalSchemaSha256": manifest["physicalSchema"]["sha256"],
        "validationEvidenceSha256": manifest["validationEvidenceSha256"],
        "sourceGoldManifestSha256": gold_sha,
        "sourceCurrentSilverManifestSha256": (
            manifest["sourceAuthorities"]["currentSilver"]["currentSilverManifestSha256"]
        ),
        "sourceGoldPartitionSha256": [str(item["sha256"]) for item in gold_partitions],
        "goldDeclaredUpstreamAuthoritySha256": declared_upstream.get("sha256"),
        "currentSilverParentMatch": True,
        "bindingAuthorityId": binding["authorityId"],
        "bindingAuthorityChecksum": binding["authorityChecksum"],
        "rights": copy.deepcopy(manifest["rights"]),
        "limitations": copy.deepcopy(manifest["limitations"]),
        "rowIdentity": {
            "method": "EXACT_CANONICAL_PA_ID_AND_ROLE_PROJECTION",
            "rowCount": len(companion_keys),
            "checksum": key_sha,
            "goldMatch": True,
        },
        "development": {"rows": DEVELOPMENT_ROWS, "partitions": 4},
        "finalOot": {
            "rows": FINAL_OOT_ROWS,
            "status": "KEY_ONLY_UNMATERIALIZED",
            "payloadRowsRead": 0,
            "payloadColumnsRead": [],
            "footerEvidence": oot_footer,
        },
    }
    authentication = {
        **public_evidence,
        "authenticationChecksum": _sha256(public_evidence),
        "_manifest": manifest,
        "_developmentPaths": development_paths,
        "_goldPaths": gold_paths,
    }
    _validate_companion_authentication(authentication, expected_project_gold_sha=gold_sha)
    return authentication


def _validate_companion_rights(rights: Mapping[str, Any], limitations: Any) -> None:
    allowed = rights.get("allowedUses")
    sources = rights.get("sourceAuthorities")
    source_by_id = {
        str(item.get("rightsControlId") or ""): item
        for item in sources or []
        if isinstance(item, Mapping)
    }
    required_sources = {
        "CHADWICK_PERSONS_REGISTER", "MLB_STATCAST", "SABR_LAHMAN_MODERN_MLB"
    }
    if (
        rights.get("effectiveStatus") != "GOVERNED_LOCAL_RESEARCH_ONLY"
        or not isinstance(allowed, list)
        or "LOCAL_PRIVATE_MODEL_DEVELOPMENT" not in allowed
        or rights.get("attributionRequired") is not True
        or rights.get("commercialRights") != "UNCLEAR_REQUIRES_REVIEW"
        or rights.get("combinationRule")
        != "INTERSECTION_MOST_RESTRICTIVE_APPLICABLE_SOURCE_AUTHORITY"
        or not required_sources.issubset(source_by_id)
        or source_by_id["MLB_STATCAST"].get("status")
        != "GOVERNED_LOCAL_RESEARCH_ONLY"
        or not all(
            str(source_by_id[item].get("attribution") or "").strip()
            for item in required_sources
        )
        or not isinstance(limitations, list)
        or not limitations
        or not any(
            "Commercial" in str(item) and "review" in str(item)
            for item in limitations
        )
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_COMPANION_RIGHTS_INVALID",
            "Companion rights do not preserve the most-restrictive Statcast/Lahman/FD1 authority.",
        )


def _validate_oot_footer_evidence(footer: Mapping[str, Any]) -> None:
    content = {
        key: copy.deepcopy(value) for key, value in footer.items() if key != "checksum"
    }
    allowed = {
        "canonicalPaId", "datasetRole", "materialization_status", "materialization_reason"
    }
    expected_columns = [
        name
        for name in sufficient_stats.sufficient_statistics_schema().names
        if name not in allowed
    ]
    evidence = list(footer.get("payloadColumns") or [])
    if (
        footer.get("checksum") != _sha256(content)
        or footer.get("checksum") != EXPECTED_OOT_FOOTER_SHA256
        or footer.get("method")
        != "PARQUET_FOOTER_COLUMN_STATISTICS_ONLY_NO_PAYLOAD_DECODE"
        or footer.get("rowCount") != FINAL_OOT_ROWS
        or [item.get("column") for item in evidence if isinstance(item, Mapping)]
        != expected_columns
        or len(evidence) != len(expected_columns)
        or any(
            not isinstance(item, Mapping)
            or item.get("nullCount") != FINAL_OOT_ROWS
            or item.get("numValues") != 0
            for item in evidence
        )
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_OOT_FOOTER_EVIDENCE_INVALID",
            "FINAL_OOT footer evidence is incomplete, materialized, or not the exact handoff.",
        )


def _validate_companion_authentication(
    authentication: Mapping[str, Any],
    *,
    expected_project_gold_sha: str | None = None,
) -> dict[str, Any]:
    """Verify the portable receipt, not only the live files that produced it."""

    public = {
        key: copy.deepcopy(value)
        for key, value in authentication.items()
        if not str(key).startswith("_")
    }
    unsigned = {
        key: value for key, value in public.items() if key != "authenticationChecksum"
    }
    if public.get("authenticationChecksum") != _sha256(unsigned):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_COMPANION_RECEIPT_CHECKSUM_MISMATCH",
            "Companion authentication receipt failed content verification.",
        )
    if (
        public.get("registrationId") != EXPECTED_COMPANION_REGISTRATION_ID
        or public.get("registrationActive") is not False
        or public.get("datasetId") != EXPECTED_COMPANION_DATASET_ID
        or public.get("manifestSha256") != EXPECTED_COMPANION_MANIFEST_SHA256
        or list(public.get("objectSha256") or [])
        != list(EXPECTED_COMPANION_OBJECT_SHA256)
        or public.get("physicalSchemaSha256")
        != EXPECTED_COMPANION_PHYSICAL_SCHEMA_SHA256
        or public.get("validationEvidenceSha256")
        != EXPECTED_COMPANION_VALIDATION_SHA256
        or public.get("sourceGoldManifestSha256") != EXPECTED_GOLD_MANIFEST_SHA256
        or public.get("sourceCurrentSilverManifestSha256")
        != EXPECTED_SOURCE_CURRENT_SILVER_SHA256
        or list(public.get("sourceGoldPartitionSha256") or [])
        != list(EXPECTED_GOLD_PARTITION_SHA256)
        or public.get("goldDeclaredUpstreamAuthoritySha256")
        != EXPECTED_GOLD_UPSTREAM_AUTHORITY_SHA256
        or public.get("currentSilverParentMatch") is not True
        or public.get("bindingAuthorityId") != EXPECTED_BINDING_AUTHORITY_ID
        or public.get("bindingAuthorityChecksum")
        != EXPECTED_BINDING_AUTHORITY_CHECKSUM
        or (
            expected_project_gold_sha is not None
            and public.get("sourceGoldManifestSha256") != expected_project_gold_sha
        )
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_COMPANION_RECEIPT_IDENTITY_INVALID",
            "Companion authentication receipt differs from the exact Wave 2 handoff.",
        )
    binding = public.get("bindingAuthority")
    if (
        not isinstance(binding, Mapping)
        or not sufficient_stats._binding_authority_checksum_is_valid(binding)
        or binding.get("authorityId") != EXPECTED_BINDING_AUTHORITY_ID
        or binding.get("authorityChecksum") != EXPECTED_BINDING_AUTHORITY_CHECKSUM
        or binding.get("manifestSha256") != EXPECTED_COMPANION_MANIFEST_SHA256
        or list(binding.get("objectSha256") or [])
        != list(EXPECTED_COMPANION_OBJECT_SHA256)
        or binding.get("sourceGoldManifestSha256") != EXPECTED_GOLD_MANIFEST_SHA256
        or binding.get("sourceCurrentSilverManifestSha256")
        != EXPECTED_SOURCE_CURRENT_SILVER_SHA256
        or binding.get("physicalSchemaSha256")
        != EXPECTED_COMPANION_PHYSICAL_SCHEMA_SHA256
        or binding.get("validationEvidenceSha256")
        != EXPECTED_COMPANION_VALIDATION_SHA256
        or binding.get("rightsStatus") != "GOVERNED_LOCAL_RESEARCH_ONLY"
        or any(
            binding.get(key) is not True
            for key in (
                "verified", "integerValidation", "equivalenceValidation", "finalOotSealed"
            )
        )
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_COMPANION_BINDING_INVALID",
            "Companion binding authority is missing, malformed, or re-signed against different evidence.",
        )
    row_identity = public.get("rowIdentity") or {}
    development = public.get("development") or {}
    final_oot = public.get("finalOot") or {}
    if (
        row_identity.get("method") != "EXACT_CANONICAL_PA_ID_AND_ROLE_PROJECTION"
        or row_identity.get("rowCount") != DEVELOPMENT_ROWS + FINAL_OOT_ROWS
        or row_identity.get("checksum") != EXPECTED_ROW_IDENTITY_SHA256
        or row_identity.get("goldMatch") is not True
        or development != {"rows": DEVELOPMENT_ROWS, "partitions": 4}
        or final_oot.get("rows") != FINAL_OOT_ROWS
        or final_oot.get("status") != "KEY_ONLY_UNMATERIALIZED"
        or final_oot.get("payloadRowsRead") != 0
        or final_oot.get("payloadColumnsRead") != []
        or not isinstance(final_oot.get("footerEvidence"), Mapping)
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_COMPANION_POPULATION_INVALID",
            "Companion receipt does not prove exact development/OOT population identity.",
        )
    _validate_oot_footer_evidence(final_oot["footerEvidence"])
    rights = public.get("rights")
    if not isinstance(rights, Mapping):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_COMPANION_RIGHTS_INVALID", "Companion rights receipt is absent."
        )
    _validate_companion_rights(rights, public.get("limitations"))
    return public


def companion_evidence_reference(authentication: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_companion_authentication(authentication)


def load_authenticated_development_companion(authentication: Mapping[str, Any]) -> pd.DataFrame:
    paths = authentication.get("_developmentPaths")
    if not isinstance(paths, Sequence) or not paths:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_COMPANION_PATHS_MISSING", "Authenticated development paths are absent.")
    columns = [
        "canonicalPaId",
        "game_date",
        "season",
        "datasetRole",
        "materialization_status",
        *sufficient_stats.SUFFICIENT_STATISTIC_COLUMNS,
    ]
    tables = [pq.read_table(Path(path), columns=columns) for path in paths]
    frame = pa.concat_tables(tables).to_pandas(split_blocks=True)
    if (
        len(frame) != DEVELOPMENT_ROWS
        or set(frame["datasetRole"].astype(str)) != {"DEVELOPMENT_SELECTION"}
        or set(frame["materialization_status"].astype(str)) != {"DEVELOPMENT_MATERIALIZED"}
    ):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_DEVELOPMENT_SCAN_INVALID", "Development companion population differs.")
    return frame


def build_authority_definition(
    project_authority: Any,
    *,
    v1_authority_manifest: Mapping[str, Any],
    companion_authentication: Mapping[str, Any],
    treatment_specification_key: str,
    treatment_source_sha256: str,
    compiler_version: str,
    compiler_sha256: str,
) -> dict[str, Any]:
    public = _public_authority(project_authority)
    companion = companion_evidence_reference(companion_authentication)
    if companion.get("sourceGoldManifestSha256") != public.get("goldManifestSha"):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_DEFINITION_GOLD_MISMATCH", "Companion and project Gold differ.")
    output_contracts = {
        feature: copy.deepcopy(_BINDINGS[feature]["outputContract"])
        for feature in WAVE2_FEATURES
    }
    content = {
        "schemaVersion": DEFINITION_SCHEMA_VERSION,
        "authorityName": AUTHORITY_NAME,
        "configurationChecksum": authority_configuration_checksum(),
        "projectAuthority": public,
        "gold": {
            "datasetId": public.get("goldDatasetId"),
            "manifestSha256": public.get("goldManifestSha"),
            "contextualDatasetId": public.get("contextualDatasetId"),
            "contextualManifestSha256": public.get("contextualManifestSha"),
            "reviewDigest": public.get("reviewDigest"),
        },
        "companionAuthority": companion,
        "wave1PriorAuthority": {
            "authorityId": v1_authority_manifest.get("authorityId"),
            "authorityChecksum": v1_authority_manifest.get("authorityChecksum"),
            "configurationChecksum": v1_authority_manifest.get("configurationChecksum"),
        },
        "treatmentSpecificationSource": {
            "key": treatment_specification_key,
            "sourceContentSha256": treatment_source_sha256,
            "compilerVersion": compiler_version,
            "compilerSha256": compiler_sha256,
        },
        "developmentBoundary": {
            "startDate": DEVELOPMENT_START,
            "endDate": DEVELOPMENT_END,
            "rows": DEVELOPMENT_ROWS,
        },
        "finalOotIdentity": {
            "startDate": FINAL_OOT_START,
            "endDate": FINAL_OOT_END,
            "rows": FINAL_OOT_ROWS,
            "status": "KEY_ONLY_UNMATERIALIZED_LOCKED_UNOPENED",
            "payloadRowsRead": 0,
            "footerEvidenceChecksum": companion["finalOot"]["footerEvidence"]["checksum"],
        },
        "families": copy.deepcopy(_FAMILIES),
        "bindings": [copy.deepcopy(_BINDINGS[feature]) for feature in WAVE2_FEATURES],
        "outputContracts": output_contracts,
        "outputContractsChecksum": _sha256(output_contracts),
        "rights": copy.deepcopy(companion["rights"]),
        "limitations": [
            *list(companion["limitations"]),
            "Estimator parameters are preprocessing authority only; no feature set is registered.",
            "All predictive-model, scoring, calibration, promotion, and policy-adoption activity is prohibited.",
        ],
    }
    checksum = _sha256(content)
    return {
        **content,
        "definitionChecksum": checksum,
        "definitionId": f"{DEFINITION_SCHEMA_VERSION}:sha256:{checksum}",
    }


def _validate_definition(definition: Mapping[str, Any]) -> dict[str, Any]:
    content = {key: copy.deepcopy(value) for key, value in definition.items() if key not in {"definitionChecksum", "definitionId"}}
    checksum = _sha256(content)
    if definition.get("definitionChecksum") != checksum or definition.get("definitionId") != f"{DEFINITION_SCHEMA_VERSION}:sha256:{checksum}":
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_DEFINITION_CHECKSUM_MISMATCH", "Wave 2 definition failed content verification.")
    if definition.get("configurationChecksum") != authority_configuration_checksum():
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_CONFIGURATION_STALE", "Wave 2 definition does not bind current code/configuration.")
    companion = definition.get("companionAuthority")
    project_gold = (definition.get("gold") or {}).get("manifestSha256")
    if not isinstance(companion, Mapping):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_DEFINITION_COMPANION_INVALID",
            "Wave 2 definition lacks companion authority.",
        )
    verified_companion = _validate_companion_authentication(
        companion, expected_project_gold_sha=str(project_gold or "")
    )
    if canonical_json_bytes(definition.get("rights") or {}) != canonical_json_bytes(
        verified_companion["rights"]
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_DEFINITION_RIGHTS_MISMATCH",
            "Wave 2 definition relaxes companion rights.",
        )
    expected_limitations = [
        *list(verified_companion["limitations"]),
        "Estimator parameters are preprocessing authority only; no feature set is registered.",
        "All predictive-model, scoring, calibration, promotion, and policy-adoption activity is prohibited.",
    ]
    if list(definition.get("limitations") or []) != expected_limitations:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_DEFINITION_LIMITATIONS_MISMATCH",
            "Wave 2 definition does not preserve exact companion limitations.",
        )
    if ((definition.get("finalOotIdentity") or {}).get("payloadRowsRead") != 0):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_OOT_POLICY_INVALID", "Wave 2 definition indicates OOT payload access.")
    return {**content, "definitionChecksum": checksum, "definitionId": definition["definitionId"]}


def _membership_checksum(frame: pd.DataFrame) -> str:
    """Hash exact date/game/PA membership in a platform-independent order."""

    required = ("game_date", "canonicalGameId", "canonicalPaId")
    missing = [column for column in required if column not in frame]
    if missing:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_MEMBERSHIP_COLUMNS_MISSING",
            f"Membership checksum is missing: {', '.join(missing)}.",
        )
    if any(bool(frame[column].isna().any()) for column in required):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_MEMBERSHIP_IDENTITY_INVALID",
            "Membership checksum cannot encode null date, game, or plate-appearance identity.",
        )
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if bool(dates.isna().any()):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_MEMBERSHIP_DATE_INVALID", "Membership contains an invalid game date."
        )
    ordered = pd.DataFrame(
        {
            "game_date": dates.dt.date.astype(str),
            "canonicalGameId": frame["canonicalGameId"].astype(str),
            "canonicalPaId": frame["canonicalPaId"].astype(str),
        }
    ).sort_values(list(required), kind="mergesort")
    digest = hashlib.sha256()
    for game_date, game_id, pa_id in ordered.itertuples(index=False, name=None):
        digest.update(f"{game_date}\x1f{game_id}\x1f{pa_id}\n".encode("utf-8"))
    return digest.hexdigest()


def build_five_fold_contract(frame: pd.DataFrame) -> dict[str, Any]:
    required = {"canonicalPaId", "canonicalGameId", "game_date"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FOLD_COLUMNS_MISSING", f"Fold construction is missing: {', '.join(missing)}.")
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if bool(dates.isna().any()) or len(frame) != DEVELOPMENT_ROWS or dates.min() != pd.Timestamp(DEVELOPMENT_START) or dates.max() != pd.Timestamp(DEVELOPMENT_END):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FOLD_POPULATION_INVALID", "Fold population boundary differs from development authority.")
    validation = pd.DataFrame({"date": dates, "game": frame["canonicalGameId"].astype("string")})
    validation = validation.loc[validation["date"].ge(pd.Timestamp("2024-01-01"))]
    if bool(validation["game"].isna().any()):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FOLD_GAME_ID_INVALID", "Fold population contains a missing canonical game ID.")
    date_counts = [
        (pd.Timestamp(date), int(group["game"].nunique()))
        for date, group in validation.groupby("date", sort=True)
    ]
    parts = 5
    counts = np.asarray([count for _date, count in date_counts], dtype=np.int64)
    prefix = np.concatenate((np.asarray([0], dtype=np.int64), np.cumsum(counts, dtype=np.int64)))
    total = int(prefix[-1])
    previous: dict[int, tuple[int, int, tuple[int, ...]]] = {0: (0, 0, ())}
    for block_number in range(1, parts + 1):
        current: dict[int, tuple[int, int, tuple[int, ...]]] = {}
        for end in range(block_number, len(date_counts) - (parts - block_number) + 1):
            best: tuple[int, int, tuple[int, ...]] | None = None
            for start in range(block_number - 1, end):
                prior = previous.get(start)
                if prior is None:
                    continue
                games = int(prefix[end] - prefix[start])
                deviation = abs(games * parts - total)
                candidate = (max(prior[0], deviation), prior[1] + deviation * deviation, (*prior[2], end))
                if best is None or candidate < best:
                    best = candidate
            if best is not None:
                current[end] = best
        previous = current
    optimum = previous.get(len(date_counts))
    if optimum is None:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FOLD_OPTIMIZATION_FAILED", "Unable to construct five date-atomic folds.")
    boundaries = [0, *optimum[2]]
    blocks = [date_counts[left:right] for left, right in zip(boundaries, boundaries[1:])]
    folds: list[dict[str, Any]] = []
    for number, block in enumerate(blocks, start=1):
        validation_start = block[0][0]
        validation_end = block[-1][0]
        train_mask = dates.lt(validation_start)
        validation_mask = dates.between(validation_start, validation_end, inclusive="both")
        record_content = {
            "foldId": f"GOVERNED_CHRONOLOGICAL_FOLD_{number}",
            "foldNumber": number,
            "trainStart": dates[train_mask].min().date().isoformat(),
            "trainEnd": dates[train_mask].max().date().isoformat(),
            "validationStart": validation_start.date().isoformat(),
            "validationEnd": validation_end.date().isoformat(),
            "trainRows": int(train_mask.sum()),
            "validationRows": int(validation_mask.sum()),
            "trainGames": int(frame.loc[train_mask, "canonicalGameId"].nunique()),
            "validationGames": int(frame.loc[validation_mask, "canonicalGameId"].nunique()),
            "trainingMembershipChecksum": _membership_checksum(frame.loc[train_mask]),
            "validationMembershipChecksum": _membership_checksum(frame.loc[validation_mask]),
            "preprocessingFitScope": "TRAINING_ROWS_OF_THIS_FOLD_ONLY",
            "validationStatisticsUsedForTraining": False,
            "finalOotUsed": False,
        }
        folds.append({**record_content, "checksum": _sha256(record_content)})
    contract_content = {
        "schemaVersion": FOLD_CONTRACT_SCHEMA_VERSION,
        "projectId": None,
        "algorithm": authority_configuration()["foldContract"],
        "developmentIdentity": {
            "startDate": DEVELOPMENT_START,
            "endDate": DEVELOPMENT_END,
            "rows": DEVELOPMENT_ROWS,
            "canonicalGameCount": int(frame["canonicalGameId"].nunique()),
            "membershipChecksum": _membership_checksum(frame),
        },
        "folds": folds,
        "targetColumnsRead": [],
        "featureSetRegistered": False,
    }
    checksum = _sha256(contract_content)
    return {**contract_content, "contractChecksum": checksum, "contractId": f"{FOLD_CONTRACT_SCHEMA_VERSION}:sha256:{checksum}"}


def bind_fold_contract_project(contract: Mapping[str, Any], project_id: str) -> dict[str, Any]:
    content = {key: copy.deepcopy(value) for key, value in contract.items() if key not in {"contractChecksum", "contractId"}}
    content["projectId"] = project_id
    checksum = _sha256(content)
    return {**content, "contractChecksum": checksum, "contractId": f"{FOLD_CONTRACT_SCHEMA_VERSION}:sha256:{checksum}"}


def _validate_fold_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    content = {
        key: copy.deepcopy(value)
        for key, value in contract.items()
        if key not in {"contractChecksum", "contractId"}
    }
    checksum = _sha256(content)
    expected_contract_id = f"{FOLD_CONTRACT_SCHEMA_VERSION}:sha256:{checksum}"
    if (
        contract.get("contractChecksum") != checksum
        or contract.get("contractId") != expected_contract_id
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FOLD_CONTRACT_CHECKSUM_MISMATCH",
            "Five-fold contract failed content verification.",
        )
    if contract.get("schemaVersion") != FOLD_CONTRACT_SCHEMA_VERSION:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FOLD_CONTRACT_SCHEMA_INVALID",
            "Five-fold contract schema differs from the registered authority.",
        )
    if canonical_json_bytes(contract.get("algorithm") or {}) != canonical_json_bytes(
        authority_configuration()["foldContract"]
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FOLD_ALGORITHM_MISMATCH",
            "Five-fold contract algorithm differs from the registered configuration.",
        )
    project_id = str(contract.get("projectId") or "").strip()
    if not project_id:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FOLD_PROJECT_INVALID",
            "Five-fold contract lacks its exact project identity.",
        )
    development = contract.get("developmentIdentity") or {}
    if (
        development.get("startDate") != DEVELOPMENT_START
        or development.get("endDate") != DEVELOPMENT_END
        or development.get("rows") != DEVELOPMENT_ROWS
        or not isinstance(development.get("canonicalGameCount"), int)
        or int(development.get("canonicalGameCount") or 0) <= 0
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(development.get("membershipChecksum") or "")
        )
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FOLD_DEVELOPMENT_IDENTITY_INVALID",
            "Five-fold contract does not bind the exact full-development population.",
        )
    folds = list(contract.get("folds") or [])
    if len(folds) != 5:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FOLD_COUNT_INVALID", "Exactly five chronological folds are required."
        )
    previous: Mapping[str, Any] | None = None
    for number, record in enumerate(folds, start=1):
        _validate_fold_record(record)
        expected_fold_id = f"GOVERNED_CHRONOLOGICAL_FOLD_{number}"
        if record.get("foldId") != expected_fold_id or record.get("foldNumber") != number:
            raise PlayerPriorAuthorityV2Error(
                "PRIOR_V2_FOLD_ORDER_INVALID",
                "Five-fold records are not in exact registered order.",
            )
        try:
            train_start = pd.Timestamp(str(record["trainStart"]))
            train_end = pd.Timestamp(str(record["trainEnd"]))
            validation_start = pd.Timestamp(str(record["validationStart"]))
            validation_end = pd.Timestamp(str(record["validationEnd"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise PlayerPriorAuthorityV2Error(
                "PRIOR_V2_FOLD_DATE_INVALID",
                "Five-fold record contains an invalid chronological boundary.",
            ) from exc
        counts = {
            key: record.get(key)
            for key in ("trainRows", "validationRows", "trainGames", "validationGames")
        }
        if (
            train_start != pd.Timestamp(DEVELOPMENT_START)
            or not train_start <= train_end < validation_start <= validation_end
            or validation_end > pd.Timestamp(DEVELOPMENT_END)
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in counts.values()
            )
            or record.get("preprocessingFitScope")
            != "TRAINING_ROWS_OF_THIS_FOLD_ONLY"
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(record.get("trainingMembershipChecksum") or "")
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(record.get("validationMembershipChecksum") or "")
            )
        ):
            raise PlayerPriorAuthorityV2Error(
                "PRIOR_V2_FOLD_STRUCTURE_INVALID",
                "Five-fold record violates chronological or population-count authority.",
            )
        if previous is not None:
            prior_validation_end = pd.Timestamp(str(previous["validationEnd"]))
            if (
                train_end != prior_validation_end
                or validation_start <= prior_validation_end
                or record["trainRows"]
                != previous["trainRows"] + previous["validationRows"]
                or record["trainGames"]
                != previous["trainGames"] + previous["validationGames"]
            ):
                raise PlayerPriorAuthorityV2Error(
                    "PRIOR_V2_FOLD_NOT_EXPANDING",
                    "Five-fold records are not an exact expanding, contiguous validation sequence.",
                )
        previous = record
    assert previous is not None
    if (
        previous.get("validationEnd") != DEVELOPMENT_END
        or previous["trainRows"] + previous["validationRows"]
        != development["rows"]
        or previous["trainGames"] + previous["validationGames"]
        != development["canonicalGameCount"]
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FOLD_COVERAGE_INVALID",
            "Five-fold validation does not end on and exhaust full development.",
        )
    if contract.get("targetColumnsRead") != [] or contract.get("featureSetRegistered") is not False:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FOLD_LEAKAGE_CONTRACT_INVALID",
            "Five-fold authority permits target or feature-set activity.",
        )
    return {
        **content,
        "contractChecksum": checksum,
        "contractId": expected_contract_id,
    }


def _validate_fold_record(record: Mapping[str, Any]) -> None:
    content = {key: copy.deepcopy(value) for key, value in record.items() if key != "checksum"}
    if record.get("checksum") != _sha256(content):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FOLD_CHECKSUM_MISMATCH", "Fold record failed content verification.")
    if record.get("validationStatisticsUsedForTraining") is not False or record.get("finalOotUsed") is not False:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FOLD_LEAKAGE_CONTRACT_INVALID", "Fold record permits unauthorized evidence.")


def _numeric(frame: pd.DataFrame, columns: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    missing_columns = [column for column in columns if column not in frame]
    if missing_columns:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_COMPONENT_COLUMNS_MISSING", f"Required components are missing: {', '.join(missing_columns)}.")
    matrix = np.column_stack(
        [pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=np.float64) for column in columns]
    )
    return matrix, ~np.isfinite(matrix).all(axis=1)


def _indicator(frame: pd.DataFrame, columns: Sequence[str]) -> np.ndarray:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_INDICATOR_COLUMNS_MISSING", f"Required indicators are missing: {', '.join(missing)}.")
    output = np.zeros(len(frame), dtype=bool)
    for column in columns:
        output |= pd.to_numeric(frame[column], errors="coerce").fillna(0).gt(0).to_numpy()
    return output


def _integer_domain(values: np.ndarray, *, label: str) -> np.ndarray:
    finite = np.isfinite(values)
    rounded = np.rint(values)
    invalid = finite & ((values < -INTEGER_TOLERANCE) | (np.abs(values - rounded) > INTEGER_TOLERANCE))
    if bool(invalid.any()):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_COUNT_DOMAIN_INVALID", f"{label} contains a noninteger or negative count.")
    output = values.copy()
    output[finite] = rounded[finite]
    return output


def _family_evidence(frame: pd.DataFrame, family_id: str) -> dict[str, Any]:
    family = _FAMILIES[family_id]
    raw, missing = _numeric(frame, family["sourceColumns"])
    indicators = _indicator(frame, family["indicatorColumns"])
    all_missing = ~np.isfinite(raw).any(axis=1)
    annual = family["window"] == "LATEST_ELIGIBLE_PRIOR_SEASON"
    cold = all_missing & indicators & annual
    source_failure = missing & ~cold
    raw = raw.copy()
    raw[cold, :] = 0.0
    finite_rows = ~source_failure

    if family_id == "PITCHER_LAST250_FASTBALL_VELOCITY":
        raw[:, 0] = _integer_domain(raw[:, 0], label=family_id)
        exposure = raw[:, 0]
        components = raw
        zero_invalid = finite_rows & (exposure == 0.0) & (
            (np.abs(raw[:, 1]) > INTEGER_TOLERANCE) | (np.abs(raw[:, 2]) > INTEGER_TOLERANCE)
        )
        if bool(zero_invalid.any()):
            raise PlayerPriorAuthorityV2Error("PRIOR_V2_VELOCITY_ZERO_COUNT_INVALID", "Zero-count velocity state carries nonzero sums.")
    else:
        raw = _integer_domain(raw, label=family_id)
        if family_id == "PITCHER_GS_APPEARANCE":
            exposure = raw[:, 0]
            success = raw[:, 1]
            components = np.column_stack((success, exposure - success))
        elif family_id in {"PITCHER_LAST250_WHIFF", "BATTER_LAST100_WHIFF"}:
            exposure = raw[:, 0]
            success = raw[:, 1]
            components = np.column_stack((success, exposure - success))
        elif family_id == "PITCHER_LAST250_PITCH_COMPOSITION":
            exposure = raw[:, 0]
            components = raw[:, 1:]
        elif family_id == "BATTER_PRIOR_AB_OUTCOME_COMPOSITION":
            exposure, hits, doubles, triples, home_runs = raw.T
            singles = hits - doubles - triples - home_runs
            components = np.column_stack((singles, doubles, triples, home_runs, exposure - hits))
        elif family_id == "PITCHER_PRIOR_WHIP_COMPONENTS":
            exposure = raw[:, 0]
            components = raw[:, 1:]
        else:
            raise PlayerPriorAuthorityV2Error("PRIOR_V2_FAMILY_UNSUPPORTED", f"Unknown family {family_id}.")
        zero_exposure_with_components = finite_rows & (exposure == 0.0) & (
            components.sum(axis=1) > INTEGER_TOLERANCE
        )
        computation_failure = (
            zero_exposure_with_components
            if family_id == "PITCHER_PRIOR_WHIP_COMPONENTS"
            else np.zeros(len(frame), dtype=bool)
        )
        invalid = finite_rows & (
            (exposure < 0.0)
            | (components < -INTEGER_TOLERANCE).any(axis=1)
            | (zero_exposure_with_components & ~computation_failure)
        )
        if family_id in {
            "PITCHER_GS_APPEARANCE",
            "PITCHER_LAST250_WHIFF",
            "BATTER_LAST100_WHIFF",
            "PITCHER_LAST250_PITCH_COMPOSITION",
            "BATTER_PRIOR_AB_OUTCOME_COMPOSITION",
        }:
            invalid |= finite_rows & (np.abs(components.sum(axis=1) - exposure) > INTEGER_TOLERANCE)
        if bool(invalid.any()):
            raise PlayerPriorAuthorityV2Error(
                "PRIOR_V2_COMPONENT_RECONCILIATION_FAILED",
                f"{family_id} components violate their exact registered denominator.",
            )
    if family_id == "PITCHER_LAST250_FASTBALL_VELOCITY":
        computation_failure = np.zeros(len(frame), dtype=bool)
    zero = finite_rows & (exposure == 0.0) & ~computation_failure
    observed = finite_rows & (exposure > 0.0)
    true_cold = zero & cold
    true_no_opportunity = zero & ~cold
    state = np.full(len(frame), "SOURCE_UNAVAILABLE", dtype=object)
    state[computation_failure] = "COMPUTATION_FAILURE"
    state[true_cold] = "TRUE_COLD_START"
    state[true_no_opportunity] = "TRUE_NO_OPPORTUNITY"
    if annual:
        state[observed] = "PRIOR_SEASON_ONLY"
    else:
        threshold = float(family["establishedThreshold"])
        state[observed & (exposure < threshold)] = "SPARSE_HISTORY"
        state[observed & (exposure >= threshold)] = "ESTABLISHED_HISTORY"
    level = np.full(len(frame), "NONE_FAIL_CLOSED", dtype=object)
    level[computation_failure] = "MLB_LEAGUE_POPULATION_GOVERNED_FALLBACK"
    level[zero] = "MLB_LEAGUE_POPULATION"
    level[observed] = "PLAYER_HISTORY_PLUS_MLB_LEAGUE_POPULATION"
    return {
        "raw": raw,
        "exposure": exposure,
        "components": components,
        "sourceFailure": source_failure,
        "computationFailure": computation_failure,
        "cold": true_cold,
        "noOpportunity": true_no_opportunity,
        "observed": observed,
        "valid": zero | observed | computation_failure,
        "historyState": state,
        "priorLevel": level,
    }


def _states_checksum(family_id: str, states: pd.DataFrame, component_columns: Sequence[str]) -> str:
    records = [
        {
            "familyId": family_id,
            "playerId": str(row[0]),
            "game_date": pd.Timestamp(row[1]).date().isoformat(),
            "components": [float(value) for value in row[2:]],
        }
        for row in states[["player", "game_date", *component_columns]].itertuples(index=False, name=None)
    ]
    return hashlib.sha256(canonical_json_bytes(records)).hexdigest()


def _latest_family_states(frame: pd.DataFrame, family_id: str) -> tuple[pd.DataFrame, str]:
    family = _FAMILIES[family_id]
    evidence = _family_evidence(frame, family_id)
    if family["playerKey"] not in frame:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_PLAYER_ID_MISSING", f"{family_id} requires {family['playerKey']}.")
    players = frame[family["playerKey"]].astype("string")
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    valid = evidence["observed"] & players.notna().to_numpy() & dates.notna().to_numpy()
    component_columns = [f"component_{index}" for index in range(evidence["components"].shape[1])]
    states = pd.DataFrame(
        {
            "player": players[valid].astype(str).to_numpy(),
            "game_date": dates[valid].to_numpy(),
            **{
                column: evidence["components"][valid, index]
                for index, column in enumerate(component_columns)
            },
            "exposure": evidence["exposure"][valid],
        }
    )
    if states.empty:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_TRAINING_EVIDENCE_EMPTY", f"No valid player states exist for {family_id}.")
    compare = [*component_columns, "exposure"]
    same_day = states.groupby(["player", "game_date"], sort=False)[compare].nunique(dropna=False)
    if bool((same_day > 1).any(axis=None)):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_POINT_IN_TIME_STATE_CONFLICT", f"{family_id} has conflicting same-player/day states.")
    states = states.drop_duplicates(["player", "game_date", *compare])
    states = (
        states.sort_values(["player", "game_date"], kind="mergesort")
        .groupby("player", sort=True, as_index=False)
        .tail(1)
        .sort_values("player", kind="mergesort")
        .reset_index(drop=True)
    )
    return states, _states_checksum(family_id, states, [*component_columns, "exposure"])


def _fit_family(states: pd.DataFrame, family_id: str) -> dict[str, Any]:
    family = _FAMILIES[family_id]
    component_columns = [name for name in states.columns if name.startswith("component_")]
    components = states[component_columns].to_numpy(dtype=np.float64)
    exposure = states["exposure"].to_numpy(dtype=np.float64)
    try:
        if family["method"] == "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES":
            fitted = fit_beta_binomial(
                components[:, 0], exposure, family_id=family_id,
                success_cell=family["componentNames"][0], failure_cell=family["componentNames"][1],
            )
        elif family["method"] == "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES":
            fitted = fit_dirichlet_multinomial(
                components, exposure, family_id=family_id, cell_names=family["componentNames"]
            )
        elif family["method"] == "GAMMA_POISSON_COMPONENT_SHRINKAGE":
            fitted = fit_gamma_poisson_components(
                components, exposure, family_id=family_id, component_names=family["componentNames"]
            )
        elif family["method"] == "NORMAL_NORMAL_EMPIRICAL_BAYES":
            # Latest-state components are count/sum/sumsq while exposure repeats count.
            fitted = fit_normal_normal(
                components[:, 0], components[:, 1], components[:, 2], family_id=family_id
            )
        else:
            raise PlayerPriorAuthorityV2Error("PRIOR_V2_ESTIMATOR_UNSUPPORTED", f"Unsupported estimator for {family_id}.")
    except PriorEstimatorV2Error as exc:
        raise PlayerPriorAuthorityV2Error(exc.code, str(exc)) from exc
    return {
        **fitted,
        "features": list(family["features"]),
        "formulaId": family["formulaId"],
        "operationFormula": family["formula"],
        "playerIdentityFeature": family["playerKey"],
        "historyCutoff": HISTORY_CUTOFF,
    }


def fit_fold_authority(
    frame: pd.DataFrame,
    definition: Mapping[str, Any],
    fold_record: Mapping[str, Any],
    *,
    fold_contract_id: str,
    fold_contract_checksum: str,
    scope_kind: str = "CHRONOLOGICAL_FOLD",
    performance_sink: MutableMapping[str, float] | None = None,
) -> dict[str, Any]:
    import time

    verified_definition = _validate_definition(definition)
    _validate_fold_record(fold_record)
    if scope_kind not in {"CHRONOLOGICAL_FOLD", "FINAL_DEVELOPMENT"}:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_SCOPE_INVALID", f"Unsupported fit scope {scope_kind}.")
    required = required_input_columns()
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FIT_COLUMNS_MISSING", f"Fit frame is missing: {', '.join(missing)}.")
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if bool(dates.isna().any()) or (len(dates) and dates.max() > pd.Timestamp(DEVELOPMENT_END)):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FIT_DATE_INVALID", "Fit frame crosses or cannot prove the development boundary.")
    train_start = pd.Timestamp(str(fold_record["trainStart"]))
    train_end = pd.Timestamp(str(fold_record["trainEnd"]))
    mask = dates.between(train_start, train_end, inclusive="both")
    if not bool(mask.any()):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_TRAINING_WINDOW_EMPTY", "No rows are in the authorized training window.")
    training_rows = int(mask.sum())
    # Slice before reading any component, player, or indicator value.
    training = frame.loc[mask, list(required)]
    parameters: dict[str, Any] = {}
    population_checksums: dict[str, str] = {}
    for family_id in _FAMILIES:
        started = time.perf_counter()
        states, checksum = _latest_family_states(training, family_id)
        parameters[family_id] = _fit_family(states, family_id)
        population_checksums[family_id] = checksum
        if performance_sink is not None:
            performance_sink[family_id] = round((time.perf_counter() - started) * 1000.0, 3)
    content = {
        "schemaVersion": FITTED_SCHEMA_VERSION,
        "definitionId": verified_definition["definitionId"],
        "definitionChecksum": verified_definition["definitionChecksum"],
        "projectId": verified_definition["projectAuthority"].get("projectId"),
        "goldManifestSha256": verified_definition["gold"]["manifestSha256"],
        "companionManifestSha256": verified_definition["companionAuthority"]["manifestSha256"],
        "wave1PriorAuthorityId": verified_definition["wave1PriorAuthority"]["authorityId"],
        "scopeKind": scope_kind,
        "foldContractId": fold_contract_id,
        "foldContractChecksum": fold_contract_checksum,
        "foldId": fold_record["foldId"],
        "foldChecksum": fold_record["checksum"],
        "trainingStart": train_start.date().isoformat(),
        "trainingEnd": train_end.date().isoformat(),
        "trainingRows": training_rows,
        "trainingGames": int(training["canonicalGameId"].nunique()),
        # This field is scientific audit metadata and therefore derives from the
        # fixed authorized development population, not from whatever future or
        # validation-only rows happen to accompany this fit invocation.  The
        # latter must not perturb a training-only fitted authority identity.
        "rowsOutsideTrainingExcludedBeforeComponentRead": (
            int(verified_definition["developmentBoundary"]["rows"])
            - training_rows
        ),
        "trainingMembershipChecksum": _membership_checksum(training),
        "populationStateChecksums": population_checksums,
        "parameters": parameters,
        "featureBindings": list(WAVE2_FEATURES),
        "outputContractsChecksum": verified_definition["outputContractsChecksum"],
        "fitEvidence": {
            "populationUnit": "LATEST_VALID_PLAYER_STATE_AT_OR_BEFORE_TRAINING_CUTOFF",
            "validationFeatureValuesReadForFit": False,
            "targetColumnsRead": [],
            "finalOotRowsRead": 0,
            "modelFits": 0,
            "featureSetsRegistered": 0,
            "policiesAdopted": 0,
        },
    }
    checksum = _sha256(content)
    return {
        **content,
        "fittedChecksum": checksum,
        "fittedId": f"{FITTED_SCHEMA_VERSION}:{fold_record['foldId']}:sha256:{checksum}",
    }


def _all_finite_numbers(value: Any) -> bool:
    if isinstance(value, Mapping):
        return all(_all_finite_numbers(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return all(_all_finite_numbers(item) for item in value)
    if isinstance(value, (float, np.floating)):
        return math.isfinite(float(value))
    return True


def _finite_vector(
    value: Any,
    *,
    length: int,
    positive: bool = False,
    nonnegative: bool = False,
) -> list[float] | None:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) != length
    ):
        return None
    try:
        output = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in output):
        return None
    if positive and not all(item > 0.0 for item in output):
        return None
    if nonnegative and not all(item >= 0.0 for item in output):
        return None
    return output


def _finite_scalar(value: Any, *, positive: bool = False, nonnegative: bool = False) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        output = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(output):
        return None
    if positive and output <= 0.0:
        return None
    if nonnegative and output < 0.0:
        return None
    return output


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def _validate_fitted_parameters(family_id: str, parameter: Mapping[str, Any]) -> None:
    """Authenticate the exact estimator schema before any transform can execute."""

    family = _FAMILIES[family_id]
    common = {
        "features", "formulaId", "operationFormula", "playerIdentityFeature", "historyCutoff"
    }
    dirichlet = {
        "method", "familyId", "cellNames", "priorAlpha", "priorComposition",
        "priorConcentration", "playerStateCount", "totalObservedExposure",
        "totalObservedCellCounts", "sampleShareVariance",
        "meanMultinomialSamplingVariance", "correctedBetweenPlayerVariance",
        "identifiedConcentrationCandidates", "rawMethodOfMomentsConcentration",
        "underidentifiedFallbackUsed", "trainingMedianExposure", "trainingExposureP95",
    }
    beta_extra = {
        "alpha", "beta", "priorMean", "priorStrength", "totalObservedTrials",
        "totalObservedSuccesses", "sampleRateVariance", "meanBinomialSamplingVariance",
    }
    gamma = {
        "method", "familyId", "componentNames", "priorShape", "priorRate",
        "priorComponentMean", "priorEquivalentExposure", "playerStateCount",
        "totalObservedExposure", "totalObservedComponentCounts", "sampleRateVariance",
        "meanPoissonSamplingVariance", "correctedBetweenPlayerRateVariance",
        "identifiedEquivalentExposureCandidates", "rawEquivalentExposure",
        "underidentifiedFallbackUsed", "trainingMedianExposure", "trainingExposureP95",
    }
    normal = {
        "method", "familyId", "populationMean", "pooledWithinPlayerVariance",
        "correctedBetweenPlayerVariance", "governedBetweenPlayerVariance",
        "priorEquivalentObservationCount", "playerStateCount", "totalObservedCount",
        "samplePlayerMeanVariance", "meanPlayerSamplingVariance",
        "rawEquivalentObservationCount", "underidentifiedBetweenVarianceFallbackUsed",
        "pooledWithinVarianceFallbackUsed", "trainingMedianObservationCount",
        "trainingObservationCountP95", "tinyNegativeCssClampCount", "cssToleranceFormula",
    }
    method = family["method"]
    if method == "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES":
        expected_keys = dirichlet | beta_extra | common
        expected_method = method
    elif method == "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES":
        expected_keys = dirichlet | common
        expected_method = "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES_METHOD_OF_MOMENTS"
    elif method == "GAMMA_POISSON_COMPONENT_SHRINKAGE":
        expected_keys = gamma | common
        expected_method = method
    else:
        expected_keys = normal | common
        expected_method = "NORMAL_NORMAL_EMPIRICAL_BAYES"
    common_valid = (
        set(parameter) == expected_keys
        and parameter.get("method") == expected_method
        and parameter.get("familyId") == family_id
        and list(parameter.get("features") or []) == list(family["features"])
        and parameter.get("formulaId") == family["formulaId"]
        and parameter.get("operationFormula") == family["formula"]
        and parameter.get("playerIdentityFeature") == family["playerKey"]
        and parameter.get("historyCutoff") == HISTORY_CUTOFF
        and isinstance(parameter.get("playerStateCount"), int)
        and not isinstance(parameter.get("playerStateCount"), bool)
        and int(parameter.get("playerStateCount") or 0) > 0
        and _all_finite_numbers(parameter)
    )
    if not common_valid:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FITTED_PARAMETER_SCHEMA_INVALID",
            f"{family_id} fitted parameter schema or authority identity differs.",
        )

    if method in {
        "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES",
        "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES",
    }:
        cells = list(family["componentNames"])
        width = len(cells)
        alpha = _finite_vector(parameter.get("priorAlpha"), length=width, positive=True)
        composition = _finite_vector(
            parameter.get("priorComposition"), length=width, nonnegative=True
        )
        concentration = _finite_scalar(parameter.get("priorConcentration"), positive=True)
        totals = _finite_vector(
            parameter.get("totalObservedCellCounts"), length=width, nonnegative=True
        )
        vector_fields = (
            "sampleShareVariance", "meanMultinomialSamplingVariance"
        )
        diagnostics_valid = all(
            _finite_vector(parameter.get(name), length=width, nonnegative=True) is not None
            for name in vector_fields
        )
        if method == "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES":
            diagnostics_valid = diagnostics_valid and (
                _finite_vector(
                    parameter.get("correctedBetweenPlayerVariance"),
                    length=width,
                    nonnegative=True,
                )
                is not None
            )
        exposure = _finite_scalar(parameter.get("totalObservedExposure"), positive=True)
        if (
            parameter.get("cellNames") != cells
            or alpha is None
            or composition is None
            or concentration is None
            or totals is None
            or exposure is None
            or not diagnostics_valid
            or not _close(sum(composition), 1.0)
            or not _close(sum(alpha), concentration)
            or not _close(sum(totals), exposure)
            or any(not _close(a / concentration, p) for a, p in zip(alpha, composition, strict=True))
        ):
            raise PlayerPriorAuthorityV2Error(
                "PRIOR_V2_FITTED_PARAMETER_DOMAIN_INVALID",
                f"{family_id} Dirichlet parameters violate their exact simplex authority.",
            )
        if method == "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES":
            alpha_scalar = _finite_scalar(parameter.get("alpha"), positive=True)
            beta_scalar = _finite_scalar(parameter.get("beta"), positive=True)
            prior_mean = _finite_scalar(parameter.get("priorMean"), nonnegative=True)
            prior_strength = _finite_scalar(parameter.get("priorStrength"), positive=True)
            trials = _finite_scalar(parameter.get("totalObservedTrials"), positive=True)
            successes = _finite_scalar(parameter.get("totalObservedSuccesses"), nonnegative=True)
            if (
                alpha_scalar is None
                or beta_scalar is None
                or prior_mean is None
                or prior_strength is None
                or trials is None
                or successes is None
                or prior_mean > 1.0
                or successes > trials
                or not _close(alpha_scalar, alpha[0])
                or not _close(beta_scalar, alpha[1])
                or not _close(prior_mean, composition[0])
                or not _close(prior_strength, concentration)
                or not _close(trials, exposure)
                or not _close(successes, totals[0])
                or _finite_scalar(
                    parameter.get("correctedBetweenPlayerVariance"), nonnegative=True
                ) is None
            ):
                raise PlayerPriorAuthorityV2Error(
                    "PRIOR_V2_FITTED_PARAMETER_DOMAIN_INVALID",
                    f"{family_id} Beta adapter differs from its exact two-cell Dirichlet fit.",
                )
    elif method == "GAMMA_POISSON_COMPONENT_SHRINKAGE":
        components = list(family["componentNames"])
        width = len(components)
        shapes = _finite_vector(parameter.get("priorShape"), length=width, positive=True)
        means = _finite_vector(parameter.get("priorComponentMean"), length=width, positive=True)
        rate = _finite_scalar(parameter.get("priorRate"), positive=True)
        equivalent = _finite_scalar(parameter.get("priorEquivalentExposure"), positive=True)
        totals = _finite_vector(
            parameter.get("totalObservedComponentCounts"), length=width, nonnegative=True
        )
        diagnostics_valid = all(
            _finite_vector(parameter.get(name), length=width, nonnegative=True) is not None
            for name in (
                "sampleRateVariance", "meanPoissonSamplingVariance",
                "correctedBetweenPlayerRateVariance",
            )
        )
        if (
            parameter.get("componentNames") != components
            or shapes is None
            or means is None
            or rate is None
            or equivalent is None
            or totals is None
            or not diagnostics_valid
            or not _close(rate, equivalent)
            or any(not _close(shape / rate, mean) for shape, mean in zip(shapes, means, strict=True))
            or _finite_scalar(parameter.get("totalObservedExposure"), positive=True) is None
        ):
            raise PlayerPriorAuthorityV2Error(
                "PRIOR_V2_FITTED_PARAMETER_DOMAIN_INVALID",
                f"{family_id} Gamma-Poisson parameters violate component authority.",
            )
    else:
        population = _finite_scalar(parameter.get("populationMean"))
        pooled = _finite_scalar(parameter.get("pooledWithinPlayerVariance"), positive=True)
        corrected = _finite_scalar(
            parameter.get("correctedBetweenPlayerVariance"), nonnegative=True
        )
        governed = _finite_scalar(
            parameter.get("governedBetweenPlayerVariance"), positive=True
        )
        equivalent = _finite_scalar(
            parameter.get("priorEquivalentObservationCount"), positive=True
        )
        raw_equivalent = parameter.get("rawEquivalentObservationCount")
        raw_valid = raw_equivalent is None or _finite_scalar(raw_equivalent, positive=True) is not None
        integer_fields_valid = all(
            isinstance(parameter.get(name), int)
            and not isinstance(parameter.get(name), bool)
            and int(parameter.get(name)) >= 0
            for name in ("tinyNegativeCssClampCount",)
        )
        if (
            population is None
            or pooled is None
            or corrected is None
            or governed is None
            or equivalent is None
            or not raw_valid
            or not integer_fields_valid
            or not _close(governed, pooled / equivalent)
            or _finite_scalar(parameter.get("totalObservedCount"), positive=True) is None
            or _finite_scalar(parameter.get("samplePlayerMeanVariance"), nonnegative=True) is None
            or _finite_scalar(parameter.get("meanPlayerSamplingVariance"), nonnegative=True) is None
            or parameter.get("cssToleranceFormula")
            != "64 * float64_epsilon * max(abs(sumsq), abs(sum^2/n), 1)"
            or not all(
                isinstance(parameter.get(name), bool)
                for name in (
                    "underidentifiedBetweenVarianceFallbackUsed",
                    "pooledWithinVarianceFallbackUsed",
                )
            )
        ):
            raise PlayerPriorAuthorityV2Error(
                "PRIOR_V2_FITTED_PARAMETER_DOMAIN_INVALID",
                f"{family_id} Normal-Normal parameters violate variance authority.",
            )


def _validate_fitted(fitted: Mapping[str, Any], *, definition: Mapping[str, Any] | None = None) -> dict[str, Any]:
    content = {key: copy.deepcopy(value) for key, value in fitted.items() if key not in {"fittedChecksum", "fittedId"}}
    checksum = _sha256(content)
    expected_id = f"{FITTED_SCHEMA_VERSION}:{fitted.get('foldId')}:sha256:{checksum}"
    if fitted.get("fittedChecksum") != checksum or fitted.get("fittedId") != expected_id:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FITTED_CHECKSUM_MISMATCH", "Fitted Wave 2 child failed content verification.")
    parameters = fitted.get("parameters")
    if not isinstance(parameters, Mapping) or set(parameters) != set(_FAMILIES):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FITTED_PARAMETER_SET_INVALID",
            "Fitted Wave 2 child lacks the exact seven estimator families.",
        )
    for family_id in _FAMILIES:
        parameter = parameters.get(family_id)
        if not isinstance(parameter, Mapping):
            raise PlayerPriorAuthorityV2Error(
                "PRIOR_V2_FITTED_PARAMETER_SCHEMA_INVALID",
                f"{family_id} fitted parameters are absent.",
            )
        _validate_fitted_parameters(family_id, parameter)
    if definition is not None:
        verified = _validate_definition(definition)
        if fitted.get("definitionId") != verified["definitionId"] or fitted.get("definitionChecksum") != verified["definitionChecksum"]:
            raise PlayerPriorAuthorityV2Error("PRIOR_V2_FITTED_DEFINITION_MISMATCH", "Fitted child binds a different definition.")
        exact_bindings = list(fitted.get("featureBindings") or []) == list(WAVE2_FEATURES)
        exact_families = set((fitted.get("parameters") or {}).keys()) == set(_FAMILIES)
        exact_lineage = (
            fitted.get("projectId") == verified["projectAuthority"].get("projectId")
            and fitted.get("goldManifestSha256") == verified["gold"]["manifestSha256"]
            and fitted.get("companionManifestSha256") == verified["companionAuthority"]["manifestSha256"]
            and fitted.get("wave1PriorAuthorityId") == verified["wave1PriorAuthority"]["authorityId"]
            and fitted.get("outputContractsChecksum") == verified["outputContractsChecksum"]
        )
        if not exact_bindings or not exact_families or not exact_lineage:
            raise PlayerPriorAuthorityV2Error(
                "PRIOR_V2_FITTED_LINEAGE_INVALID",
                "Fitted child does not carry the exact binding, family, or source lineage.",
            )
    fit_evidence = fitted.get("fitEvidence") or {}
    if (
        fit_evidence.get("validationFeatureValuesReadForFit") is not False
        or fit_evidence.get("targetColumnsRead") != []
        or fit_evidence.get("finalOotRowsRead") != 0
        or fit_evidence.get("modelFits") != 0
        or fit_evidence.get("featureSetsRegistered") != 0
        or fit_evidence.get("policiesAdopted") != 0
    ):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FITTED_OOT_EVIDENCE_INVALID", "Fitted child indicates OOT access.")
    return {**content, "fittedChecksum": checksum, "fittedId": expected_id}


def _validate_fold_child_record(
    fitted: Mapping[str, Any], fold_record: Mapping[str, Any]
) -> None:
    """Prove that a fitted child is attached to its exact stored fold record."""

    expected = {
        "scopeKind": "CHRONOLOGICAL_FOLD",
        "foldId": fold_record.get("foldId"),
        "foldChecksum": fold_record.get("checksum"),
        "trainingStart": fold_record.get("trainStart"),
        "trainingEnd": fold_record.get("trainEnd"),
        "trainingRows": fold_record.get("trainRows"),
        "trainingGames": fold_record.get("trainGames"),
    }
    membership = fold_record.get("trainingMembershipChecksum")
    if membership is not None:
        expected["trainingMembershipChecksum"] = membership
    mismatched = [key for key, value in expected.items() if fitted.get(key) != value]
    if mismatched:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_CHILD_FOLD_RECORD_MISMATCH",
            "Fitted child differs from its stored fold record: "
            + ", ".join(sorted(mismatched))
            + ".",
        )


def _valid_arrays(frame: pd.DataFrame, family_id: str) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray]:
    evidence = _family_evidence(frame, family_id)
    valid = evidence["valid"]
    components = evidence["components"].copy()
    exposure = evidence["exposure"].copy()
    components[~valid] = 0.0
    components[np.asarray(evidence["computationFailure"], dtype=bool)] = 0.0
    exposure[~valid] = 0.0
    return evidence, valid, components, exposure


def _mask_invalid(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    output = values.copy()
    if output.ndim == 1:
        output[~valid] = np.nan
    else:
        output[~valid, ...] = np.nan
    return output


def _common_feature_columns(
    feature: str,
    evidence: Mapping[str, Any],
    posterior_mean: np.ndarray,
    posterior_variance: np.ndarray,
    reliability: np.ndarray,
    prior_strength: float,
) -> dict[str, Any]:
    outputs = _BINDINGS[feature]["derivedOutputs"]
    valid = np.asarray(evidence["valid"], dtype=bool)
    effective = _mask_invalid(np.asarray(evidence["exposure"], dtype=np.float64), valid)
    variance = _mask_invalid(np.asarray(posterior_variance, dtype=np.float64), valid)
    return {
        outputs["posteriorMean"]: _mask_invalid(np.asarray(posterior_mean, dtype=np.float64), valid),
        outputs["log1pEffectiveN"]: np.log1p(effective),
        outputs["posteriorReliability"]: _mask_invalid(np.asarray(reliability, dtype=np.float64), valid),
        outputs["posteriorStd"]: np.sqrt(variance),
        outputs["effectiveN"]: effective,
        outputs["priorStrength"]: np.where(valid, float(prior_strength), np.nan),
        outputs["posteriorVariance"]: variance,
        outputs["historyState"]: np.asarray(evidence["historyState"], dtype=object),
        outputs["priorLevel"]: np.asarray(evidence["priorLevel"], dtype=object),
        outputs["formulaId"]: np.where(valid, _BINDINGS[feature]["formulaId"], None),
        outputs["familyId"]: np.where(valid, FEATURE_TO_FAMILY[feature], None),
    }


def transform_prior_family(frame: pd.DataFrame, fitted: Mapping[str, Any], family_id: str) -> pd.DataFrame:
    verified = _validate_fitted(fitted)
    if family_id not in _FAMILIES or family_id not in verified["parameters"]:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FAMILY_NOT_FITTED", f"No fitted parameters exist for {family_id}.")
    dates = pd.to_datetime(frame.get("game_date"), errors="coerce")
    if len(frame) and (bool(dates.isna().any()) or dates.max() > pd.Timestamp(DEVELOPMENT_END)):
        from .mlb_v18_prospective_transform import has_prospective_authority
        if not has_prospective_authority(frame):
            raise PlayerPriorAuthorityV2Error("PRIOR_V2_TRANSFORM_CROSSES_FINAL_OOT", "Wave 2 rejects rows outside authorized development before component access.")
    evidence, valid, components, exposure = _valid_arrays(frame, family_id)
    family = _FAMILIES[family_id]
    parameter = verified["parameters"][family_id]
    output: dict[str, Any] = {}
    try:
        if family["method"] in {
            "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES",
            "DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES",
        }:
            posterior = dirichlet_posterior(components, exposure, parameter)
            means = posterior["posteriorMean"]
            covariance = posterior["posteriorCovariance"]
            if family_id == "BATTER_PRIOR_AB_OUTCOME_COMPOSITION":
                weights = {
                    "batter_avg": np.asarray([1.0, 1.0, 1.0, 1.0, 0.0]),
                    "batter_slg": np.asarray([1.0, 2.0, 3.0, 4.0, 0.0]),
                }
                for feature, weight in weights.items():
                    estimate = means @ weight
                    variance = np.einsum("i,nij,j->n", weight, covariance, weight)
                    output.update(_common_feature_columns(feature, evidence, estimate, variance, posterior["reliability"], parameter["priorConcentration"]))
            else:
                feature_indexes = {
                    "pitcher_gs_per_g": 0,
                    "pitcher_last250_whiff_rate": 0,
                    "batter_last100_whiff_rate": 0,
                    "pitcher_last250_fastball_usage": 0,
                    "pitcher_last250_breaking_usage": 1,
                    "pitcher_last250_offspeed_usage": 2,
                }
                for feature in family["features"]:
                    index = feature_indexes[feature]
                    output.update(_common_feature_columns(feature, evidence, means[:, index], posterior["posteriorVariance"][:, index], posterior["reliability"], parameter["priorConcentration"]))
            family_prefix = f"mlb_prior_v2__{family_id.lower()}"
            for index, name in enumerate(family["componentNames"]):
                token = name.lower()
                output[f"{family_prefix}__posterior_{token}"] = _mask_invalid(means[:, index], valid)
                output[f"{family_prefix}__posterior_alpha_{token}"] = _mask_invalid(posterior["posteriorAlpha"][:, index], valid)
                output[f"{family_prefix}__posterior_variance_{token}"] = _mask_invalid(posterior["posteriorVariance"][:, index], valid)
            for left, left_name in enumerate(family["componentNames"]):
                for right, right_name in enumerate(family["componentNames"]):
                    if right > left:
                        output[f"{family_prefix}__posterior_covariance_{left_name.lower()}__{right_name.lower()}"] = _mask_invalid(covariance[:, left, right], valid)
        elif family["method"] == "GAMMA_POISSON_COMPONENT_SHRINKAGE":
            posterior = gamma_poisson_posterior(components, exposure, parameter)
            whip = 3.0 * posterior["posteriorMean"].sum(axis=1)
            variance = 9.0 * posterior["posteriorVariance"].sum(axis=1)
            feature = "pitcher_whip"
            output.update(_common_feature_columns(feature, evidence, whip, variance, posterior["reliability"], parameter["priorEquivalentExposure"]))
            prefix = _feature_prefix(feature)
            output[f"{prefix}__hits_per_out_posterior_mean"] = _mask_invalid(posterior["posteriorMean"][:, 0], valid)
            output[f"{prefix}__walks_per_out_posterior_mean"] = _mask_invalid(posterior["posteriorMean"][:, 1], valid)
            output[f"{prefix}__hits_per_out_posterior_variance"] = _mask_invalid(posterior["posteriorVariance"][:, 0], valid)
            output[f"{prefix}__walks_per_out_posterior_variance"] = _mask_invalid(posterior["posteriorVariance"][:, 1], valid)
            output[f"{prefix}__posterior_shape_hits"] = _mask_invalid(posterior["posteriorShape"][:, 0], valid)
            output[f"{prefix}__posterior_shape_walks"] = _mask_invalid(posterior["posteriorShape"][:, 1], valid)
            output[f"{prefix}__posterior_rate"] = _mask_invalid(posterior["posteriorRate"], valid)
        elif family["method"] == "NORMAL_NORMAL_EMPIRICAL_BAYES":
            posterior = normal_normal_posterior(components[:, 0], components[:, 1], components[:, 2], parameter)
            feature = "pitcher_last250_avg_fastball_velocity"
            output.update(_common_feature_columns(feature, evidence, posterior["posteriorMean"], posterior["posteriorVariance"], posterior["reliability"], parameter["priorEquivalentObservationCount"]))
            prefix = _feature_prefix(feature)
            output[f"{prefix}__sample_mean"] = _mask_invalid(posterior["sampleMean"], valid)
            output[f"{prefix}__sample_variance"] = _mask_invalid(posterior["sampleVariance"], valid)
            output[f"{prefix}__centered_sum_squares"] = _mask_invalid(posterior["centeredSumSquares"], valid)
        else:
            raise PlayerPriorAuthorityV2Error("PRIOR_V2_ESTIMATOR_UNSUPPORTED", f"Unsupported estimator for {family_id}.")
    except PriorEstimatorV2Error as exc:
        raise PlayerPriorAuthorityV2Error(exc.code, str(exc)) from exc
    return pd.DataFrame(output, index=frame.index)


def transform_prior_features(
    frame: pd.DataFrame,
    fitted: Mapping[str, Any],
    *,
    features: Sequence[str] | None = None,
) -> pd.DataFrame:
    selected = tuple(features or WAVE2_FEATURES)
    required_input_columns(selected)
    families = list(dict.fromkeys(FEATURE_TO_FAMILY[feature] for feature in selected))
    parts = [transform_prior_family(frame, fitted, family_id) for family_id in families]
    combined = pd.concat(parts, axis=1) if parts else pd.DataFrame(index=frame.index)
    if bool(combined.columns.duplicated().any()):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_OUTPUT_COLLISION", "Wave 2 derived output names collide.")
    allowed = {
        output
        for feature in selected
        for role in ("modelCandidateOutputs", "auditOnlyOutputs")
        for output in _BINDINGS[feature]["outputContract"][role]
    }
    # Preserve shared family audit evidence even though it is never a model
    # candidate; consumers can inspect it through the authority UI.
    shared = [column for column in combined if column.startswith("mlb_prior_v2__")]
    return combined[[column for column in combined if column in allowed or column in shared]]


def transform_prior_feature(frame: pd.DataFrame, fitted: Mapping[str, Any], feature: str) -> pd.DataFrame:
    required_input_columns([feature])
    family = transform_prior_family(frame, fitted, FEATURE_TO_FAMILY[feature])
    contract = _BINDINGS[feature]["outputContract"]
    columns = [*contract["modelCandidateOutputs"], *contract["auditOnlyOutputs"]]
    return family[[column for column in columns if column in family]]


def _diagnostic_quantiles(values: np.ndarray | pd.Series) -> dict[str, float]:
    series = pd.to_numeric(pd.Series(values), errors="coerce")
    series = series[np.isfinite(series.to_numpy(dtype=np.float64))]
    quantiles = (0.0, 0.25, 0.5, 0.75, 0.95, 1.0)
    return {str(q): float(series.quantile(q)) for q in quantiles}


def _raw_feature_estimate(evidence: Mapping[str, Any], feature: str) -> np.ndarray:
    components = np.asarray(evidence["components"], dtype=np.float64)
    exposure = np.asarray(evidence["exposure"], dtype=np.float64)
    observed = np.asarray(evidence["observed"], dtype=bool)
    output = np.full(len(exposure), np.nan, dtype=np.float64)
    if feature in {
        "pitcher_gs_per_g",
        "pitcher_last250_whiff_rate",
        "batter_last100_whiff_rate",
        "pitcher_last250_fastball_usage",
    }:
        numerator = components[:, 0]
    elif feature == "pitcher_last250_breaking_usage":
        numerator = components[:, 1]
    elif feature == "pitcher_last250_offspeed_usage":
        numerator = components[:, 2]
    elif feature == "batter_avg":
        numerator = components[:, :4].sum(axis=1)
    elif feature == "batter_slg":
        numerator = components @ np.asarray([1.0, 2.0, 3.0, 4.0, 0.0])
    elif feature == "pitcher_whip":
        numerator = 3.0 * components.sum(axis=1)
    elif feature == "pitcher_last250_avg_fastball_velocity":
        numerator = components[:, 1]
    else:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_DIAGNOSTIC_FEATURE_UNSUPPORTED", f"No raw diagnostic formula exists for {feature}."
        )
    np.divide(numerator, exposure, out=output, where=observed)
    return output


def _adjustment_by_exposure(
    posterior: np.ndarray | pd.Series,
    raw: np.ndarray,
    exposure: np.ndarray,
) -> dict[str, Any]:
    posterior_values = pd.to_numeric(pd.Series(posterior), errors="coerce").to_numpy(dtype=np.float64)
    valid = np.isfinite(posterior_values) & np.isfinite(raw) & np.isfinite(exposure) & (exposure > 0.0)
    adjustment = posterior_values[valid] - raw[valid]
    observed_exposure = exposure[valid]
    low_cutoff = float(pd.Series(observed_exposure).quantile(0.25))
    high_cutoff = float(pd.Series(observed_exposure).quantile(0.75))
    low = adjustment[observed_exposure <= low_cutoff]
    high = adjustment[observed_exposure >= high_cutoff]
    return {
        "posteriorMinusRawQuantiles": _diagnostic_quantiles(adjustment),
        "absoluteAdjustmentQuantiles": _diagnostic_quantiles(np.abs(adjustment)),
        "exposureLowerQuartile": low_cutoff,
        "exposureUpperQuartile": high_cutoff,
        "lowExposureAbsoluteAdjustmentQuantiles": _diagnostic_quantiles(np.abs(low)),
        "highExposureAbsoluteAdjustmentQuantiles": _diagnostic_quantiles(np.abs(high)),
    }


def development_diagnostics(frame: pd.DataFrame, fitted: Mapping[str, Any]) -> dict[str, Any]:
    verified = _validate_fitted(fitted)
    diagnostics: dict[str, Any] = {}
    for family_id, family in _FAMILIES.items():
        transformed = transform_prior_family(frame, verified, family_id)
        evidence = _family_evidence(frame, family_id)
        parameter = verified["parameters"][family_id]
        representative = family["features"][0]
        outputs = _BINDINGS[representative]["derivedOutputs"]
        reliability = pd.to_numeric(transformed[outputs["posteriorReliability"]], errors="coerce")
        effective = pd.to_numeric(transformed[outputs["effectiveN"]], errors="coerce")
        posterior = pd.to_numeric(transformed[outputs["posteriorMean"]], errors="coerce")
        item: dict[str, Any] = {
            "method": family["method"],
            "features": list(family["features"]),
            "playerStateCount": parameter["playerStateCount"],
            "reliabilityQuantiles": _diagnostic_quantiles(reliability),
            "effectiveNQuantiles": _diagnostic_quantiles(effective),
            "posteriorQuantiles": _diagnostic_quantiles(posterior),
            "zeroOpportunityCount": int(np.asarray(evidence["noOpportunity"]).sum()),
            "trueColdStartCount": int(np.asarray(evidence["cold"]).sum()),
            "sourceFailureCount": int(np.asarray(evidence["sourceFailure"]).sum()),
            "computationFailureCount": int(np.asarray(evidence["computationFailure"]).sum()),
            "targetColumnsRead": [],
        }
        feature_adjustments: dict[str, Any] = {}
        exposure_values = np.asarray(evidence["exposure"], dtype=np.float64)
        for feature in family["features"]:
            feature_posterior = transformed[_BINDINGS[feature]["derivedOutputs"]["posteriorMean"]]
            feature_adjustments[feature] = _adjustment_by_exposure(
                feature_posterior,
                _raw_feature_estimate(evidence, feature),
                exposure_values,
            )
        item["featureAdjustmentDiagnostics"] = feature_adjustments
        if "priorComposition" in parameter:
            item.update({"priorComposition": parameter["priorComposition"], "priorConcentration": parameter["priorConcentration"]})
        if family["method"] == "BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES":
            item["priorMean"] = parameter["priorMean"]
            item["priorStrength"] = parameter["priorStrength"]
            item["posteriorMinusRawQuantiles"] = feature_adjustments[representative]["posteriorMinusRawQuantiles"]
        if family_id == "PITCHER_LAST250_PITCH_COMPOSITION":
            shared = [f"mlb_prior_v2__{family_id.lower()}__posterior_{name.lower()}" for name in family["componentNames"]]
            simplex = transformed[shared].sum(axis=1) - 1.0
            item["maximumSimplexAbsoluteError"] = float(simplex.abs().max())
            item["posteriorResidualShareQuantiles"] = _diagnostic_quantiles(transformed[shared[-1]])
            raw_residual = np.full(len(exposure_values), np.nan, dtype=np.float64)
            observed = np.asarray(evidence["observed"], dtype=bool)
            np.divide(
                np.asarray(evidence["components"], dtype=np.float64)[:, -1],
                exposure_values,
                out=raw_residual,
                where=observed,
            )
            item["rawResidualShareQuantiles"] = _diagnostic_quantiles(raw_residual)
            item["sharedFourCellAuthority"] = True
        elif family_id == "BATTER_PRIOR_AB_OUTCOME_COMPOSITION":
            avg = transformed[_BINDINGS["batter_avg"]["derivedOutputs"]["posteriorMean"]]
            slg = transformed[_BINDINGS["batter_slg"]["derivedOutputs"]["posteriorMean"]]
            item["posteriorAvgQuantiles"] = _diagnostic_quantiles(avg)
            item["posteriorSlgQuantiles"] = _diagnostic_quantiles(slg)
            item["lowAbShrinkage"] = {
                feature: value["lowExposureAbsoluteAdjustmentQuantiles"]
                for feature, value in feature_adjustments.items()
            }
            item["countDomainViolations"] = 0
            item["usesEightClassTargetTaxonomy"] = False
        elif family_id == "PITCHER_PRIOR_WHIP_COMPONENTS":
            item["hitsPerOutPrior"] = parameter["priorComponentMean"][0]
            item["walksPerOutPrior"] = parameter["priorComponentMean"][1]
            item["priorEquivalentOuts"] = parameter["priorEquivalentExposure"]
            item["posteriorWhipQuantiles"] = _diagnostic_quantiles(posterior)
            item["adjustmentByIpouts"] = feature_adjustments["pitcher_whip"]
            item["registeredFormula"] = "3 * (H + BB) / IPouts"
            item["usesBfpDenominator"] = False
            item["includesHbp"] = False
        elif family_id == "PITCHER_LAST250_FASTBALL_VELOCITY":
            item["populationMean"] = parameter["populationMean"]
            item["betweenPlayerVariance"] = parameter["governedBetweenPlayerVariance"]
            item["pooledWithinPlayerVariance"] = parameter["pooledWithinPlayerVariance"]
            item["nZeroCount"] = int((evidence["exposure"] == 0).sum())
            item["nOneCount"] = int((evidence["exposure"] == 1).sum())
            item["velocityClippedCount"] = 0
            raw_velocity = _raw_feature_estimate(evidence, "pitcher_last250_avg_fastball_velocity")
            velocity_posterior = pd.to_numeric(posterior, errors="coerce").to_numpy(dtype=np.float64)
            finite = np.isfinite(raw_velocity) & np.isfinite(velocity_posterior)
            item["rawMinusPosteriorQuantiles"] = _diagnostic_quantiles(
                raw_velocity[finite] - velocity_posterior[finite]
            )
            item["extremeValueAudit"] = {
                "rawMinimum": float(raw_velocity[finite].min()),
                "rawMaximum": float(raw_velocity[finite].max()),
                "posteriorMinimum": float(velocity_posterior[finite].min()),
                "posteriorMaximum": float(velocity_posterior[finite].max()),
                "clippingApplied": False,
            }
        diagnostics[family_id] = item
    content = {
        "schemaVersion": "MLB_PLAYER_STATE_PRIOR_V2_DEVELOPMENT_DIAGNOSTICS_V1",
        "fittedId": verified["fittedId"],
        "fittedChecksum": verified["fittedChecksum"],
        "developmentRows": len(frame),
        "families": diagnostics,
        "targetColumnsRead": [],
        "finalOotRowsRead": 0,
    }
    return {**content, "checksum": _sha256(content)}


def assemble_fit_bundle(
    definition: Mapping[str, Any],
    fold_children: Sequence[Mapping[str, Any]],
    final_development_child: Mapping[str, Any],
    *,
    fold_contract: Mapping[str, Any],
    definition_artifact_sha256: str,
    fold_contract_artifact_sha256: str,
    fold_artifact_sha256: Sequence[str],
    final_artifact_sha256: str,
) -> dict[str, Any]:
    verified_definition = _validate_definition(definition)
    verified_contract = _validate_fold_contract(fold_contract)
    development = verified_contract["developmentIdentity"]
    definition_boundary = verified_definition["developmentBoundary"]
    if (
        verified_contract.get("projectId")
        != verified_definition["projectAuthority"].get("projectId")
        or any(
            development.get(key) != definition_boundary.get(key)
            for key in ("startDate", "endDate", "rows")
        )
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FOLD_DEFINITION_SCOPE_MISMATCH",
            "Five-fold contract differs from the definition project/development scope.",
        )
    if len(fold_children) != 5 or len(fold_artifact_sha256) != 5:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FOLD_COUNT_INVALID", "Exactly five fitted fold children are required.")
    verified_folds = [_validate_fitted(child, definition=verified_definition) for child in fold_children]
    final = _validate_fitted(final_development_child, definition=verified_definition)
    if any(child["scopeKind"] != "CHRONOLOGICAL_FOLD" for child in verified_folds) or final["scopeKind"] != "FINAL_DEVELOPMENT":
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_CHILD_SCOPE_INVALID", "Fold/final child scopes differ.")
    contract_ids = {child["foldContractId"] for child in [*verified_folds, final]}
    contract_checksums = {child["foldContractChecksum"] for child in [*verified_folds, final]}
    if len(contract_ids) != 1 or len(contract_checksums) != 1:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_CHILD_FOLD_CONTRACT_MISMATCH",
            "Fitted children do not bind one exact five-fold contract.",
        )
    if contract_ids != {verified_contract["contractId"]} or contract_checksums != {
        verified_contract["contractChecksum"]
    }:
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_CHILD_FOLD_CONTRACT_MISMATCH",
            "Fitted children do not bind the supplied five-fold contract.",
        )
    fold_numbers = [int(str(child["foldId"]).rsplit("_", 1)[-1]) for child in verified_folds]
    if fold_numbers != [1, 2, 3, 4, 5]:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FOLD_ORDER_INVALID", "Fitted folds are not the ordered five-fold authority.")
    for child, record in zip(
        verified_folds, verified_contract["folds"], strict=True
    ):
        _validate_fold_child_record(child, record)
    expected_final_record = {
        "foldId": "FINAL_DEVELOPMENT",
        "foldNumber": 0,
        "trainStart": development["startDate"],
        "trainEnd": development["endDate"],
        "validationStart": None,
        "validationEnd": None,
        "trainRows": development["rows"],
        "validationRows": 0,
        "trainGames": development["canonicalGameCount"],
        "validationGames": 0,
        "trainingMembershipChecksum": development["membershipChecksum"],
        "preprocessingFitScope": "ALL_AUTHORIZED_DEVELOPMENT_ROWS_ONLY",
        "validationStatisticsUsedForTraining": False,
        "finalOotUsed": False,
    }
    expected_final = {
        "scopeKind": "FINAL_DEVELOPMENT",
        "foldId": "FINAL_DEVELOPMENT",
        "foldChecksum": _sha256(expected_final_record),
        "trainingStart": development["startDate"],
        "trainingEnd": development["endDate"],
        "trainingRows": development["rows"],
        "trainingGames": development["canonicalGameCount"],
        "trainingMembershipChecksum": development["membershipChecksum"],
    }
    if any(final.get(key) != value for key, value in expected_final.items()):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FINAL_DEVELOPMENT_SCOPE_INVALID",
            "Final-development fit is not the exact whole-development population.",
        )
    content = {
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "authorityName": AUTHORITY_NAME,
        "definition": {
            "definitionId": verified_definition["definitionId"],
            "definitionChecksum": verified_definition["definitionChecksum"],
            "artifactSha256": definition_artifact_sha256,
        },
        "projectId": verified_definition["projectAuthority"].get("projectId"),
        "goldManifestSha256": verified_definition["gold"]["manifestSha256"],
        "companionManifestSha256": verified_definition["companionAuthority"]["manifestSha256"],
        "companionBindingAuthorityId": verified_definition["companionAuthority"]["bindingAuthorityId"],
        "wave1PriorAuthority": verified_definition["wave1PriorAuthority"],
        "configurationChecksum": verified_definition["configurationChecksum"],
        "outputContractsChecksum": verified_definition["outputContractsChecksum"],
        "foldContract": {
            "contractId": verified_contract["contractId"],
            "contractChecksum": verified_contract["contractChecksum"],
            "artifactSha256": fold_contract_artifact_sha256,
        },
        "foldAuthorities": [
            {
                "foldId": child["foldId"],
                "fittedId": child["fittedId"],
                "fittedChecksum": child["fittedChecksum"],
                "artifactSha256": artifact_sha,
                "trainingStart": child["trainingStart"],
                "trainingEnd": child["trainingEnd"],
                "trainingRows": child["trainingRows"],
                "trainingGames": child["trainingGames"],
                "trainingMembershipChecksum": child["trainingMembershipChecksum"],
                "foldContractId": child["foldContractId"],
                "foldContractChecksum": child["foldContractChecksum"],
                "foldChecksum": child["foldChecksum"],
            }
            for child, artifact_sha in zip(verified_folds, fold_artifact_sha256, strict=True)
        ],
        "finalDevelopmentAuthority": {
            "fittedId": final["fittedId"],
            "fittedChecksum": final["fittedChecksum"],
            "artifactSha256": final_artifact_sha256,
            "trainingStart": final["trainingStart"],
            "trainingEnd": final["trainingEnd"],
            "trainingRows": final["trainingRows"],
            "trainingGames": final["trainingGames"],
            "trainingMembershipChecksum": final["trainingMembershipChecksum"],
            "foldChecksum": final["foldChecksum"],
            "foldContractId": final["foldContractId"],
            "foldContractChecksum": final["foldContractChecksum"],
        },
        "bindings": list(WAVE2_FEATURES),
        "bindingStatus": READY_GOVERNED_PRIOR_V2,
        "finalOotIdentity": verified_definition["finalOotIdentity"],
        "rights": verified_definition["rights"],
        "limitations": verified_definition["limitations"],
        "audit": {
            "preprocessingFits": 6,
            "predictiveModelFits": 0,
            "scores": 0,
            "calibrations": 0,
            "promotions": 0,
            "featureSetsRegistered": 0,
            "policiesAdopted": 0,
            "goldRowsMutated": 0,
            "companionRowsMutated": 0,
            "historicalArtifactMutations": 0,
            "finalOotPayloadRowsRead": 0,
            "finalOotPayloadRowsTransformed": 0,
        },
    }
    checksum = _sha256(content)
    return {**content, "authorityChecksum": checksum, "authorityId": f"{AUTHORITY_NAME}:sha256:{checksum}"}


def _validate_bundle(
    bundle: Mapping[str, Any],
    *,
    expected_definition: Mapping[str, Any],
    root: Path,
) -> dict[str, Any]:
    content = {key: copy.deepcopy(value) for key, value in bundle.items() if key not in {"authorityChecksum", "authorityId"}}
    checksum = _sha256(content)
    if bundle.get("authorityChecksum") != checksum or bundle.get("authorityId") != f"{AUTHORITY_NAME}:sha256:{checksum}":
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_BUNDLE_CHECKSUM_MISMATCH", "Wave 2 parent authority failed content verification.")
    definition = _validate_definition(expected_definition)
    reference = bundle.get("definition") or {}
    if reference.get("definitionId") != definition["definitionId"] or reference.get("definitionChecksum") != definition["definitionChecksum"]:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_BUNDLE_DEFINITION_STALE", "Wave 2 parent binds a stale definition.")
    try:
        stored_definition = load_artifact(str(reference.get("artifactSha256") or ""), root=root)
    except PriorArtifactStoreV2Error as exc:
        raise PlayerPriorAuthorityV2Error(exc.code, str(exc)) from exc
    if canonical_json_bytes(stored_definition) != canonical_json_bytes(definition):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_DEFINITION_ARTIFACT_MISMATCH", "Stored Wave 2 definition differs.")
    fold_contract_reference = bundle.get("foldContract") or {}
    try:
        stored_fold_contract = load_artifact(
            str(fold_contract_reference.get("artifactSha256") or ""), root=root
        )
    except PriorArtifactStoreV2Error as exc:
        raise PlayerPriorAuthorityV2Error(exc.code, str(exc)) from exc
    verified_fold_contract = _validate_fold_contract(stored_fold_contract)
    development = verified_fold_contract["developmentIdentity"]
    definition_boundary = definition["developmentBoundary"]
    if (
        verified_fold_contract["contractId"] != fold_contract_reference.get("contractId")
        or verified_fold_contract["contractChecksum"]
        != fold_contract_reference.get("contractChecksum")
        or verified_fold_contract.get("projectId")
        != definition["projectAuthority"].get("projectId")
        or any(
            development.get(key) != definition_boundary.get(key)
            for key in ("startDate", "endDate", "rows")
        )
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FOLD_CONTRACT_REFERENCE_MISMATCH",
            "Wave 2 parent references a different five-fold contract.",
        )
    child_refs = list(bundle.get("foldAuthorities") or [])
    final_ref = bundle.get("finalDevelopmentAuthority") or {}
    if len(child_refs) != 5:
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_FOLD_COUNT_INVALID", "Wave 2 parent lacks five folds.")
    for reference_item, fold_record in zip(
        child_refs, verified_fold_contract["folds"], strict=True
    ):
        try:
            child = load_artifact(str(reference_item.get("artifactSha256") or ""), root=root)
        except PriorArtifactStoreV2Error as exc:
            raise PlayerPriorAuthorityV2Error(exc.code, str(exc)) from exc
        verified_child = _validate_fitted(child, definition=definition)
        reference_fields = (
            "foldId", "fittedId", "fittedChecksum", "trainingStart",
            "trainingEnd", "trainingRows", "trainingGames",
            "trainingMembershipChecksum",
            "foldContractId", "foldContractChecksum", "foldChecksum",
        )
        if any(
            verified_child.get(key) != reference_item.get(key)
            for key in reference_fields
        ):
            raise PlayerPriorAuthorityV2Error("PRIOR_V2_CHILD_REFERENCE_MISMATCH", "Wave 2 parent child reference differs.")
        _validate_fold_child_record(verified_child, fold_record)
        if (
            verified_child["foldContractId"] != verified_fold_contract["contractId"]
            or verified_child["foldContractChecksum"]
            != verified_fold_contract["contractChecksum"]
        ):
            raise PlayerPriorAuthorityV2Error(
                "PRIOR_V2_CHILD_FOLD_CONTRACT_MISMATCH",
                "A fitted child references a different five-fold contract.",
            )
    try:
        final_child = load_artifact(
            str(final_ref.get("artifactSha256") or ""), root=root
        )
    except PriorArtifactStoreV2Error as exc:
        raise PlayerPriorAuthorityV2Error(exc.code, str(exc)) from exc
    verified_final = _validate_fitted(final_child, definition=definition)
    final_reference_fields = (
        "fittedId", "fittedChecksum", "trainingStart", "trainingEnd",
        "trainingRows", "trainingGames", "trainingMembershipChecksum",
        "foldChecksum", "foldContractId", "foldContractChecksum",
    )
    expected_final_record = {
        "foldId": "FINAL_DEVELOPMENT",
        "foldNumber": 0,
        "trainStart": development["startDate"],
        "trainEnd": development["endDate"],
        "validationStart": None,
        "validationEnd": None,
        "trainRows": development["rows"],
        "validationRows": 0,
        "trainGames": development["canonicalGameCount"],
        "validationGames": 0,
        "trainingMembershipChecksum": development["membershipChecksum"],
        "preprocessingFitScope": "ALL_AUTHORIZED_DEVELOPMENT_ROWS_ONLY",
        "validationStatisticsUsedForTraining": False,
        "finalOotUsed": False,
    }
    exact_final_scope = {
        "trainingStart": development["startDate"],
        "trainingEnd": development["endDate"],
        "trainingRows": development["rows"],
        "trainingGames": development["canonicalGameCount"],
        "trainingMembershipChecksum": development["membershipChecksum"],
        "foldChecksum": _sha256(expected_final_record),
    }
    if (
        verified_final.get("scopeKind") != "FINAL_DEVELOPMENT"
        or verified_final.get("foldId") != "FINAL_DEVELOPMENT"
        or any(
            verified_final.get(key) != final_ref.get(key)
            for key in final_reference_fields
        )
        or any(
            verified_final.get(key) != value
            for key, value in exact_final_scope.items()
        )
        or verified_final.get("foldContractId") != verified_fold_contract["contractId"]
        or verified_final.get("foldContractChecksum")
        != verified_fold_contract["contractChecksum"]
    ):
        raise PlayerPriorAuthorityV2Error(
            "PRIOR_V2_FINAL_CHILD_REFERENCE_MISMATCH",
            "Wave 2 parent final-development child reference differs.",
        )
    if bundle.get("bindingStatus") != READY_GOVERNED_PRIOR_V2 or list(bundle.get("bindings") or []) != list(WAVE2_FEATURES):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_BINDING_SET_INVALID", "Wave 2 parent binding set differs.")
    audit = bundle.get("audit") or {}
    forbidden = (
        "predictiveModelFits", "scores", "calibrations", "promotions",
        "featureSetsRegistered", "policiesAdopted", "goldRowsMutated",
        "companionRowsMutated", "historicalArtifactMutations",
        "finalOotPayloadRowsRead", "finalOotPayloadRowsTransformed",
    )
    if any(int(audit.get(key, -1)) != 0 for key in forbidden):
        raise PlayerPriorAuthorityV2Error("PRIOR_V2_PROHIBITED_ACTIVITY_RECORDED", "Wave 2 bundle records prohibited activity.")
    return {**content, "authorityChecksum": checksum, "authorityId": bundle["authorityId"]}


def resolve_current_fit_bundle(
    *,
    project_id: str,
    expected_definition: Mapping[str, Any],
    root: Path = DEFAULT_AUTHORITY_ROOT,
) -> dict[str, Any] | None:
    try:
        bundle = load_current_bundle(project_id, root=root)
    except PriorArtifactStoreV2Error as exc:
        raise PlayerPriorAuthorityV2Error(exc.code, str(exc)) from exc
    if bundle is None:
        return None
    return _validate_bundle(bundle, expected_definition=expected_definition, root=root)


def load_final_development_child(bundle: Mapping[str, Any], *, root: Path = DEFAULT_AUTHORITY_ROOT) -> dict[str, Any]:
    reference = bundle.get("finalDevelopmentAuthority") or {}
    try:
        child = load_artifact(str(reference.get("artifactSha256") or ""), root=root)
    except PriorArtifactStoreV2Error as exc:
        raise PlayerPriorAuthorityV2Error(exc.code, str(exc)) from exc
    return _validate_fitted(child)


def _ready_binding(feature: str, bundle: Mapping[str, Any]) -> dict[str, Any]:
    binding = copy.deepcopy(_BINDINGS[feature])
    binding.update(
        {
            "status": READY_GOVERNED_PRIOR_V2,
            "executable": True,
            "selectable": False,
            "estimatorImplementationStatus": "IMPLEMENTED_FITTED_TESTED_CONTENT_ADDRESSED_V2",
            "populationPriorAuthority": "VERIFIED_FOLD_LOCAL_AND_FINAL_DEVELOPMENT_WAVE2_FIT_BUNDLE",
            "authorityId": bundle["authorityId"],
            "authorityChecksum": bundle["authorityChecksum"],
            "fittedFoldStatus": "FIVE_CONTENT_ADDRESSED_CHILDREN_VERIFIED",
            "foldContract": copy.deepcopy(bundle["foldContract"]),
            "fittedFoldAuthorities": copy.deepcopy(bundle["foldAuthorities"]),
            "finalDevelopmentAuthority": copy.deepcopy(bundle["finalDevelopmentAuthority"]),
            "companionBindingIdentity": bundle["companionBindingAuthorityId"],
            "pointInTime": "PASS",
            "foldLocal": "PASS",
            "effectiveSampleSizeSupport": True,
            "reliabilitySupport": True,
            "uncertaintySupport": True,
        }
    )
    return binding


def combined_project_authority_manifest(
    v1_manifest: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    bindings: list[dict[str, Any]] = []
    for item in v1_manifest.get("bindings") or []:
        feature = str(item.get("feature") or "")
        bindings.append(_ready_binding(feature, bundle) if feature in FEATURE_TO_FAMILY else copy.deepcopy(dict(item)))
    counter = Counter(str(item.get("status") or "") for item in bindings)
    executable = [str(item["feature"]) for item in bindings if item.get("executable")]
    return {
        **{key: copy.deepcopy(value) for key, value in v1_manifest.items() if key not in {"authorityId", "authorityChecksum", "bindings", "statusCounts", "featureSets"}},
        "schemaVersion": SCHEMA_VERSION,
        "authorityName": AUTHORITY_NAME,
        "method": "FEATURE_SPECIFIC_V1_PLUS_WAVE2_SHARED_EMPIRICAL_BAYES_AUTHORITY",
        "authorityId": bundle["authorityId"],
        "authorityChecksum": bundle["authorityChecksum"],
        "fitBundleId": bundle["authorityId"],
        "fitBundleChecksum": bundle["authorityChecksum"],
        "wave1AuthorityId": v1_manifest["authorityId"],
        "wave1AuthorityChecksum": v1_manifest["authorityChecksum"],
        "companionBindingAuthorityId": bundle["companionBindingAuthorityId"],
        "foldContract": copy.deepcopy(bundle["foldContract"]),
        "foldAuthorities": copy.deepcopy(bundle["foldAuthorities"]),
        "finalDevelopmentAuthority": copy.deepcopy(bundle["finalDevelopmentAuthority"]),
        "foldLocal": "PASS",
        "pointInTime": "PASS",
        "statusCounts": {
            prior_v1.READY_GOVERNED_PRIOR_V1: int(counter[prior_v1.READY_GOVERNED_PRIOR_V1]),
            READY_GOVERNED_PRIOR_V2: int(counter[READY_GOVERNED_PRIOR_V2]),
            prior_v1.BINDING_READY_REQUIRES_WAVE2_ENGINE: int(counter[prior_v1.BINDING_READY_REQUIRES_WAVE2_ENGINE]),
            prior_v1.RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION: int(counter[prior_v1.RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION]),
            prior_v1.BLOCKED_REQUIRES_PRIOR_AUTHORITY: int(counter[prior_v1.BLOCKED_REQUIRES_PRIOR_AUTHORITY]),
        },
        "featureSets": {
            "executable": executable,
            "executableV1": [str(item["feature"]) for item in bindings if item.get("status") == prior_v1.READY_GOVERNED_PRIOR_V1],
            "executableV2": [str(item["feature"]) for item in bindings if item.get("status") == READY_GOVERNED_PRIOR_V2],
            "bindingReadyRequiresWave2Engine": [str(item["feature"]) for item in bindings if item.get("status") == prior_v1.BINDING_READY_REQUIRES_WAVE2_ENGINE],
            "retiredByScientificDecision": [str(item["feature"]) for item in bindings if item.get("status") == prior_v1.RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION],
            "blockedByMissingEvidence": [str(item["feature"]) for item in bindings if item.get("status") == prior_v1.BLOCKED_REQUIRES_PRIOR_AUTHORITY],
        },
        "readyFeatureCount": len(executable),
        "readyV1FeatureCount": int(counter[prior_v1.READY_GOVERNED_PRIOR_V1]),
        "readyV2FeatureCount": int(counter[READY_GOVERNED_PRIOR_V2]),
        "bindingReadyRequiresWave2EngineFeatureCount": int(counter[prior_v1.BINDING_READY_REQUIRES_WAVE2_ENGINE]),
        "retiredFeatureCount": int(counter[prior_v1.RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION]),
        "blockedFeatureCount": int(counter[prior_v1.BLOCKED_REQUIRES_PRIOR_AUTHORITY]),
        "bindings": bindings,
    }


def feature_binding(feature: str, *, bundle: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    if feature not in _BINDINGS:
        return None
    return _ready_binding(feature, bundle) if bundle is not None else copy.deepcopy(_BINDINGS[feature])


__all__ = [
    "AUTHORITY_NAME",
    "BUNDLE_SCHEMA_VERSION",
    "DEFINITION_SCHEMA_VERSION",
    "EXPECTED_COMPANION_MANIFEST_SHA256",
    "EXPECTED_COMPANION_REGISTRATION_ID",
    "EXPECTED_GOLD_MANIFEST_SHA256",
    "FEATURE_TO_FAMILY",
    "FITTED_SCHEMA_VERSION",
    "PlayerPriorAuthorityV2Error",
    "READY_GOVERNED_PRIOR_V2",
    "RETIRED_FEATURES",
    "WAVE2_FEATURES",
    "assemble_fit_bundle",
    "authenticate_companion",
    "authority_configuration",
    "authority_configuration_checksum",
    "bind_fold_contract_project",
    "build_authority_definition",
    "build_five_fold_contract",
    "combined_project_authority_manifest",
    "companion_evidence_reference",
    "development_diagnostics",
    "feature_binding",
    "fit_fold_authority",
    "load_authenticated_development_companion",
    "load_final_development_child",
    "required_input_columns",
    "resolve_current_fit_bundle",
    "transform_prior_family",
    "transform_prior_feature",
    "transform_prior_features",
]
