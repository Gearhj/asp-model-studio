"""Governed MLB player-state prior authority for Stage 3 preprocessing.

This module is deliberately independent of every outcome model.  It turns the
subset of reviewed player-rate recommendations with an exact, already
materialized opportunity denominator into deterministic Beta-Binomial
preprocessing outputs.  A recommendation whose statistic-specific denominator
is not present in accepted Current Gold stays explicitly blocked; PA/BF is
never substituted merely because it is nearby.

Population hyperparameters are fit on caller-supplied chronological training
rows only.  The row-level rates/counts consumed here are the registered Gold
histories computed with ``source.gameDate < target.gameDate``.  Consequently,
the current PA outcome is neither an input nor a source column.  Missing source
or failed computation states fail closed and are never relabelled as rookies.
"""
from __future__ import annotations

import copy
import hashlib
import math
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..sports_datasets.consumer import canonical_json_bytes


AUTHORITY_NAME = "MLB_PLAYER_STATE_PRIOR_AUTHORITY_V1"
SCHEMA_VERSION = "MLB_PLAYER_STATE_PRIOR_AUTHORITY_SCHEMA_V1"
FITTED_SCHEMA_VERSION = "MLB_PLAYER_STATE_FITTED_PRIOR_V1"
DEVELOPMENT_END = "2026-08-13"
HISTORY_CUTOFF = "source.gameDate < target.gameDate (same-date rows excluded)"
MISSING_REASON_SUFFIX = "__missing_reason"
NUMERIC_INTEGER_TOLERANCE = 1e-6
PROBABILITY_EPSILON = 1e-9


class PlayerPriorAuthorityError(RuntimeError):
    """A prior configuration, fitting input, or transformation failed closed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _binding(
    feature: str,
    *,
    side: str,
    statistic: str,
    method: str,
    exposure_feature: str | None,
    exposure_transform: str | None,
    exposure_definition: str,
    window: str,
    missing_indicators: Sequence[str],
    established_threshold: int | None,
    ready: bool,
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    player_key = (
        "batterCanonicalPlayerId" if side == "BATTER" else "pitcherCanonicalPlayerId"
    )
    status = "READY_GOVERNED_PRIOR_V1" if ready else "BLOCKED_REQUIRES_PRIOR_AUTHORITY"
    output_prefix = f"{feature}__prior_v1"
    return {
        "feature": feature,
        "side": side,
        "statisticType": statistic,
        "method": method,
        "status": status,
        "executable": ready,
        "blockedReason": blocked_reason,
        "playerIdentityFeature": player_key,
        "exposureFeature": exposure_feature,
        "exposureTransform": exposure_transform,
        "exposureDefinition": exposure_definition,
        "historyWindow": window,
        "historyCutoff": HISTORY_CUTOFF,
        "missingReasonFeature": f"{feature}{MISSING_REASON_SUFFIX}",
        "missingIndicatorFeatures": list(missing_indicators),
        "establishedThreshold": established_threshold,
        "populationPriorAuthority": (
            "TRAINING_FOLD_MLB_POPULATION_EMPIRICAL_BAYES"
            if ready
            else "UNAVAILABLE_UNTIL_REQUIRED_SUFFICIENT_STATISTIC_IS_REGISTERED"
        ),
        "hierarchy": ["PLAYER_HISTORY", "MLB_LEAGUE_POPULATION"],
        "roleAuthority": "NOT_AVAILABLE_IN_CURRENT_GOLD_NOT_INVENTED",
        "decayAuthority": (
            "NO_DECAY_ANNUAL_STATE_SOURCE_AGE_NOT_MATERIALIZED"
            if window == "LATEST_ELIGIBLE_PRIOR_SEASON"
            else "NO_ADDITIONAL_DECAY_ALREADY_RECENCY_BOUNDED_WINDOW"
        ),
        "rawFeatureDecision": "RETAIN_RAW_AND_ADD_GOVERNED_DERIVED_FAMILY",
        "derivedOutputs": {
            "posteriorMean": f"{output_prefix}__posterior_mean",
            "effectiveN": f"{output_prefix}__effective_n",
            "priorStrength": f"{output_prefix}__prior_strength",
            "posteriorStrength": f"{output_prefix}__posterior_strength",
            "posteriorVariance": f"{output_prefix}__posterior_variance",
            "posteriorStd": f"{output_prefix}__posterior_std",
            "posteriorReliability": f"{output_prefix}__posterior_reliability",
            "historyState": f"{output_prefix}__history_state",
            "priorLevel": f"{output_prefix}__prior_level",
            "observedSuccesses": f"{output_prefix}__observed_successes",
            "observedTrials": f"{output_prefix}__observed_trials",
            "priorAlpha": f"{output_prefix}__prior_alpha",
            "priorBeta": f"{output_prefix}__prior_beta",
            "posteriorAlpha": f"{output_prefix}__posterior_alpha",
            "posteriorBeta": f"{output_prefix}__posterior_beta",
            "decayWeight": f"{output_prefix}__decay_weight",
            "observationAgeDays": f"{output_prefix}__observation_age_days",
        },
    }


_BLOCKED = {
    "pitcher_whip": (
        "WHIP requires prior IPouts plus BB and H; BFP is not its denominator and "
        "those sufficient statistics are not materialized in Current Gold."
    ),
    "pitcher_era9": (
        "ERA9 requires prior IPouts and ER; BFP is not its denominator and those "
        "sufficient statistics are not materialized in Current Gold."
    ),
    "pitcher_gs_per_g": (
        "GS/G requires exact prior games and games-started counts; BFP is not a "
        "valid opportunity denominator and neither count is materialized in Current Gold."
    ),
    "batter_slg": (
        "SLG requires exact at-bats and total-base components; prior PA is not its "
        "denominator and the sufficient statistics are not materialized in Current Gold."
    ),
    "batter_obp": (
        "OBP requires AB+BB+HBP+SF opportunities; prior PA also includes sacrifice "
        "hits and cannot be substituted for the unmaterialized denominator."
    ),
    "batter_avg": (
        "AVG requires exact at-bats and hits; prior PA is not its denominator and "
        "at-bats are not materialized in Current Gold."
    ),
    "pitcher_last250_avg_fastball_velocity": (
        "Velocity shrinkage requires eligible-fastball count and within-window variance; "
        "the materialized BF count is not a velocity observation count."
    ),
    "pitcher_last250_whiff_rate": (
        "Pitcher whiff rate requires the exact classifiable-swing count; BF count is "
        "not the denominator and swing count is not materialized in Current Gold."
    ),
    "pitcher_last250_offspeed_usage": (
        "Pitch usage requires the exact all-pitch opportunity count; BF count is not "
        "the denominator and pitch count is not materialized in Current Gold."
    ),
    "pitcher_last250_fastball_usage": (
        "Pitch usage requires the exact all-pitch opportunity count; BF count is not "
        "the denominator and pitch count is not materialized in Current Gold."
    ),
    "pitcher_last250_breaking_usage": (
        "Pitch usage requires the exact all-pitch opportunity count; BF count is not "
        "the denominator and pitch count is not materialized in Current Gold."
    ),
    "batter_last100_whiff_rate": (
        "Batter whiff rate requires the exact classifiable-swing count; PA count is "
        "not the denominator and swing count is not materialized in Current Gold."
    ),
    "batter_last100_contact_rate": (
        "Batter contact rate requires the exact classifiable-swing count; PA count is "
        "not the denominator and swing count is not materialized in Current Gold."
    ),
}


_BINDINGS: tuple[dict[str, Any], ...] = (
    _binding("pitcher_whip", side="PITCHER", statistic="NON_BERNOULLI_RATE", method="GAMMA_POISSON_COMPONENT_SHRINKAGE_REQUIRED", exposure_feature=None, exposure_transform=None, exposure_definition="prior innings pitched from exact IPouts / 3", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("pitcher_prior_missing",), established_threshold=None, ready=False, blocked_reason=_BLOCKED["pitcher_whip"]),
    _binding("pitcher_era9", side="PITCHER", statistic="NON_BERNOULLI_RATE", method="GAMMA_POISSON_COMPONENT_SHRINKAGE_REQUIRED", exposure_feature=None, exposure_transform=None, exposure_definition="prior innings pitched from exact IPouts / 3", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("pitcher_prior_missing",), established_threshold=None, ready=False, blocked_reason=_BLOCKED["pitcher_era9"]),
    _binding("pitcher_so_per_bfp", side="PITCHER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES", exposure_feature="pitcher_log1p_bfp", exposure_transform="EXPM1_VALIDATE_INTEGER", exposure_definition="exact prior-season BFP recovered from registered log1p(BFP)", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("pitcher_prior_missing",), established_threshold=None, ready=True),
    _binding("pitcher_hr_per_bfp", side="PITCHER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES", exposure_feature="pitcher_log1p_bfp", exposure_transform="EXPM1_VALIDATE_INTEGER", exposure_definition="exact prior-season BFP recovered from registered log1p(BFP)", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("pitcher_prior_missing",), established_threshold=None, ready=True),
    _binding("pitcher_hbp_per_bfp", side="PITCHER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES", exposure_feature="pitcher_log1p_bfp", exposure_transform="EXPM1_VALIDATE_INTEGER", exposure_definition="exact prior-season BFP recovered from registered log1p(BFP)", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("pitcher_prior_missing",), established_threshold=None, ready=True),
    _binding("pitcher_gs_per_g", side="PITCHER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES_REQUIRES_G", exposure_feature=None, exposure_transform=None, exposure_definition="exact prior games", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("pitcher_prior_missing",), established_threshold=None, ready=False, blocked_reason=_BLOCKED["pitcher_gs_per_g"]),
    _binding("pitcher_bb_per_bfp", side="PITCHER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES", exposure_feature="pitcher_log1p_bfp", exposure_transform="EXPM1_VALIDATE_INTEGER", exposure_definition="exact prior-season BFP recovered from registered log1p(BFP)", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("pitcher_prior_missing",), established_threshold=None, ready=True),
    _binding("batter_so_per_pa", side="BATTER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES", exposure_feature="batter_log1p_pa", exposure_transform="EXPM1_VALIDATE_INTEGER", exposure_definition="exact prior-season PA recovered from registered log1p(PA)", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("batter_prior_missing",), established_threshold=None, ready=True),
    _binding("batter_slg", side="BATTER", statistic="NON_BERNOULLI_RATE", method="DIRICHLET_MULTINOMIAL_COMPONENT_SHRINKAGE_REQUIRED", exposure_feature=None, exposure_transform=None, exposure_definition="exact prior at-bats plus total-base components", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("batter_prior_missing",), established_threshold=None, ready=False, blocked_reason=_BLOCKED["batter_slg"]),
    _binding("batter_obp", side="BATTER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES_REQUIRES_OBP_OPPORTUNITIES", exposure_feature=None, exposure_transform=None, exposure_definition="exact prior AB+BB+HBP+SF", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("batter_prior_missing",), established_threshold=None, ready=False, blocked_reason=_BLOCKED["batter_obp"]),
    _binding("batter_hr_per_pa", side="BATTER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES", exposure_feature="batter_log1p_pa", exposure_transform="EXPM1_VALIDATE_INTEGER", exposure_definition="exact prior-season PA recovered from registered log1p(PA)", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("batter_prior_missing",), established_threshold=None, ready=True),
    _binding("batter_bb_hbp_per_pa", side="BATTER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES", exposure_feature="batter_log1p_pa", exposure_transform="EXPM1_VALIDATE_INTEGER", exposure_definition="exact prior-season PA recovered from registered log1p(PA)", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("batter_prior_missing",), established_threshold=None, ready=True),
    _binding("batter_avg", side="BATTER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES_REQUIRES_AB", exposure_feature=None, exposure_transform=None, exposure_definition="exact prior at-bats", window="LATEST_ELIGIBLE_PRIOR_SEASON", missing_indicators=("batter_prior_missing",), established_threshold=None, ready=False, blocked_reason=_BLOCKED["batter_avg"]),
    _binding("pitcher_last250_avg_fastball_velocity", side="PITCHER", statistic="CONTINUOUS_MEAN", method="NORMAL_NORMAL_REQUIRES_FASTBALL_COUNT_AND_VARIANCE", exposure_feature=None, exposure_transform=None, exposure_definition="eligible fastballs with finite release speed", window="LAST_250_COMPLETED_PRIOR_BF", missing_indicators=("pitcher_last250_insufficient", "pitcher_last250_velocity_missing"), established_threshold=250, ready=False, blocked_reason=_BLOCKED["pitcher_last250_avg_fastball_velocity"]),
    _binding("pitcher_last250_whiff_rate", side="PITCHER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_REQUIRES_SWING_COUNT", exposure_feature=None, exposure_transform=None, exposure_definition="classifiable swings inside last-250-BF window", window="LAST_250_COMPLETED_PRIOR_BF", missing_indicators=("pitcher_last250_insufficient", "pitcher_last250_whiff_missing"), established_threshold=250, ready=False, blocked_reason=_BLOCKED["pitcher_last250_whiff_rate"]),
    _binding("pitcher_last250_walk_rate", side="PITCHER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES", exposure_feature="pitcher_last250_bf_count", exposure_transform="VALIDATE_INTEGER", exposure_definition="exact completed prior BF in registered last-250-BF window", window="LAST_250_COMPLETED_PRIOR_BF", missing_indicators=("pitcher_last250_insufficient",), established_threshold=250, ready=True),
    _binding("pitcher_last250_strikeout_rate", side="PITCHER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES", exposure_feature="pitcher_last250_bf_count", exposure_transform="VALIDATE_INTEGER", exposure_definition="exact completed prior BF in registered last-250-BF window", window="LAST_250_COMPLETED_PRIOR_BF", missing_indicators=("pitcher_last250_insufficient",), established_threshold=250, ready=True),
    _binding("pitcher_last250_offspeed_usage", side="PITCHER", statistic="BOUNDED_PROPORTION", method="DIRICHLET_MULTINOMIAL_REQUIRES_PITCH_COUNT", exposure_feature=None, exposure_transform=None, exposure_definition="all pitch rows inside last-250-BF window", window="LAST_250_COMPLETED_PRIOR_BF", missing_indicators=("pitcher_last250_insufficient",), established_threshold=250, ready=False, blocked_reason=_BLOCKED["pitcher_last250_offspeed_usage"]),
    _binding("pitcher_last250_fastball_usage", side="PITCHER", statistic="BOUNDED_PROPORTION", method="DIRICHLET_MULTINOMIAL_REQUIRES_PITCH_COUNT", exposure_feature=None, exposure_transform=None, exposure_definition="all pitch rows inside last-250-BF window", window="LAST_250_COMPLETED_PRIOR_BF", missing_indicators=("pitcher_last250_insufficient",), established_threshold=250, ready=False, blocked_reason=_BLOCKED["pitcher_last250_fastball_usage"]),
    _binding("pitcher_last250_breaking_usage", side="PITCHER", statistic="BOUNDED_PROPORTION", method="DIRICHLET_MULTINOMIAL_REQUIRES_PITCH_COUNT", exposure_feature=None, exposure_transform=None, exposure_definition="all pitch rows inside last-250-BF window", window="LAST_250_COMPLETED_PRIOR_BF", missing_indicators=("pitcher_last250_insufficient",), established_threshold=250, ready=False, blocked_reason=_BLOCKED["pitcher_last250_breaking_usage"]),
    _binding("batter_last100_whiff_rate", side="BATTER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_REQUIRES_SWING_COUNT", exposure_feature=None, exposure_transform=None, exposure_definition="classifiable swings inside last-100-PA window", window="LAST_100_COMPLETED_PRIOR_PA", missing_indicators=("batter_last100_insufficient", "batter_last100_whiff_missing"), established_threshold=100, ready=False, blocked_reason=_BLOCKED["batter_last100_whiff_rate"]),
    _binding("batter_last100_contact_rate", side="BATTER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_REQUIRES_SWING_COUNT", exposure_feature=None, exposure_transform=None, exposure_definition="classifiable swings inside last-100-PA window", window="LAST_100_COMPLETED_PRIOR_PA", missing_indicators=("batter_last100_insufficient", "batter_last100_whiff_missing"), established_threshold=100, ready=False, blocked_reason=_BLOCKED["batter_last100_contact_rate"]),
    _binding("batter_last100_walk_hbp_rate", side="BATTER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES", exposure_feature="batter_last100_pa_count", exposure_transform="VALIDATE_INTEGER", exposure_definition="exact completed prior PA in registered last-100-PA window", window="LAST_100_COMPLETED_PRIOR_PA", missing_indicators=("batter_last100_insufficient",), established_threshold=100, ready=True),
    _binding("batter_last100_strikeout_rate", side="BATTER", statistic="BOUNDED_PROPORTION", method="BETA_BINOMIAL_EMPIRICAL_BAYES", exposure_feature="batter_last100_pa_count", exposure_transform="VALIDATE_INTEGER", exposure_definition="exact completed prior PA in registered last-100-PA window", window="LAST_100_COMPLETED_PRIOR_PA", missing_indicators=("batter_last100_insufficient",), established_threshold=100, ready=True),
)

_BY_FEATURE = {str(item["feature"]): item for item in _BINDINGS}
PRIOR_FEATURES = tuple(_BY_FEATURE)
SUPPORTED_PRIOR_FEATURES = frozenset(
    feature for feature, item in _BY_FEATURE.items() if item["executable"]
)
BLOCKED_PRIOR_FEATURES = frozenset(set(PRIOR_FEATURES) - set(SUPPORTED_PRIOR_FEATURES))


def _sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def feature_binding(feature: str) -> dict[str, Any] | None:
    binding = _BY_FEATURE.get(feature)
    return copy.deepcopy(binding) if binding is not None else None


def authority_configuration(*, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return the canonical, content-addressable scientific configuration."""

    config: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "authorityName": AUTHORITY_NAME,
        "implementationSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "methodFamily": "BETA_BINOMIAL_EMPIRICAL_BAYES",
        "populationFit": {
            "scope": "TRAINING_ROWS_OF_EACH_CHRONOLOGICAL_FOLD_ONLY",
            "unit": "LATEST_VALID_PLAYER_STATE_AT_OR_BEFORE_TRAINING_CUTOFF",
            "mean": "JEFFREYS_STABILIZED_POOLED_EVENT_RATE",
            "betweenPlayerVariance": "UNWEIGHTED_SAMPLE_VARIANCE_MINUS_MEAN_BINOMIAL_SAMPLING_VARIANCE",
            "priorStrength": "METHOD_OF_MOMENTS_CONCENTRATION",
            "underidentifiedFallback": "TRAINING_PLAYER_MEDIAN_EXPOSURE",
            "upperBound": "TRAINING_PLAYER_EXPOSURE_P95",
            "validationRowsFitParameters": False,
            "finalOotRowsFitParameters": False,
        },
        "numerics": {
            "integerTolerance": NUMERIC_INTEGER_TOLERANCE,
            "probabilityEpsilon": PROBABILITY_EPSILON,
            "zeroDenominator": "TRUE_COLD_START_ONLY_WITH_REGISTERED_INDICATOR_ELSE_FAIL_CLOSED",
            "reconstructedSuccesses": "rate_times_trials_must_be_integer_within_tolerance",
        },
        "hierarchy": {
            "levels": ["PLAYER_HISTORY", "MLB_LEAGUE_POPULATION"],
            "roleLevel": "NOT_AVAILABLE_IN_CURRENT_GOLD_NOT_INVENTED",
            "leagueSubgroup": "NOT_PROVABLE_PER_ROW_USE_GLOBAL_MLB",
        },
        "chronology": {
            "playerHistory": HISTORY_CUTOFF,
            "populationFit": "training-authorized rows only",
            "annualDecay": "NO_DECAY_SOURCE_AGE_NOT_MATERIALIZED",
            "rollingDecay": "NO_ADDITIONAL_DECAY_ALREADY_RECENCY_BOUNDED",
        },
        "reliabilityFormula": "observed_effective_n / (prior_strength + observed_effective_n)",
        "failurePrecedence": [
            "SOURCE_UNAVAILABLE",
            "COMPUTATION_FAILURE",
            "TRUE_COLD_START",
            "SPARSE_OR_ESTABLISHED_HISTORY",
        ],
        "modelFamilyResolution": {
            "TREE": ["RAW", "POSTERIOR", "EFFECTIVE_N", "POSTERIOR_RELIABILITY", "HISTORY_STATE"],
            "LINEAR": ["POSTERIOR", "LOG1P_EFFECTIVE_N", "POSTERIOR_RELIABILITY", "HISTORY_STATE"],
            "NEURAL_OR_DISTANCE": ["POSTERIOR", "LOG1P_EFFECTIVE_N", "POSTERIOR_RELIABILITY", "HISTORY_STATE"],
            "scientificValuesIdenticalAcrossFamilies": True,
            "scalingAuthority": "FIT_ON_CORRESPONDING_TRAINING_ROWS_ONLY",
        },
        "bindings": [copy.deepcopy(item) for item in _BINDINGS],
    }
    if overrides:
        for key, value in overrides.items():
            config[str(key)] = copy.deepcopy(value)
    return config


def authority_checksum(*, configuration: Mapping[str, Any] | None = None) -> str:
    return _sha256(configuration or authority_configuration())


def project_authority_manifest(
    project_authority: Any,
    *,
    treatment_specification_key: str,
    treatment_source_sha256: str,
) -> dict[str, Any]:
    """Bind the checked-in authority to one exact project/Gold/spec source."""

    public = (
        dict(project_authority.public())
        if callable(getattr(project_authority, "public", None))
        else dict(project_authority)
        if isinstance(project_authority, Mapping)
        else {}
    )
    config = authority_configuration()
    content = {
        "schemaVersion": SCHEMA_VERSION,
        "authorityName": AUTHORITY_NAME,
        "method": "FEATURE_SPECIFIC_BETA_BINOMIAL_EMPIRICAL_BAYES",
        "hierarchy": config["hierarchy"]["levels"],
        "reliability": config["reliabilityFormula"],
        "foldLocal": "PASS",
        "pointInTime": "PASS",
        "configurationChecksum": authority_checksum(configuration=config),
        "projectId": public.get("projectId") or getattr(project_authority, "project_id", None),
        "goldDatasetId": public.get("goldDatasetId"),
        "goldManifestSha": public.get("goldManifestSha") or getattr(project_authority, "gold_manifest_sha", None),
        "contextualDatasetId": public.get("contextualDatasetId"),
        "contextualManifestSha": public.get("contextualManifestSha") or getattr(project_authority, "contextual_manifest_sha", None),
        "reviewDigest": public.get("reviewDigest") or getattr(project_authority, "review_digest", None),
        "treatmentSpecificationSource": {
            "key": treatment_specification_key,
            "sourceContentSha256": treatment_source_sha256,
        },
        "developmentCutoff": DEVELOPMENT_END,
        "finalOotPolicy": "LOCKED_NOT_OPENED_NOT_FIT",
        "readyFeatureCount": len(SUPPORTED_PRIOR_FEATURES),
        "blockedFeatureCount": len(BLOCKED_PRIOR_FEATURES),
        "featureCount": len(PRIOR_FEATURES),
        "bindings": config["bindings"],
    }
    checksum = _sha256(content)
    return {
        **content,
        "authorityChecksum": checksum,
        "authorityId": f"{AUTHORITY_NAME}:sha256:{checksum}",
    }


def required_input_columns(features: Sequence[str] | None = None) -> tuple[str, ...]:
    selected = tuple(features or sorted(SUPPORTED_PRIOR_FEATURES))
    columns = {"game_date", "canonicalPaId"}
    for feature in selected:
        binding = _BY_FEATURE.get(feature)
        if binding is None or not binding["executable"]:
            raise PlayerPriorAuthorityError(
                "PRIOR_FEATURE_NOT_EXECUTABLE", f"{feature} has no executable V1 prior binding."
            )
        columns.add(feature)
        columns.add(str(binding["playerIdentityFeature"]))
        columns.add(str(binding["exposureFeature"]))
        columns.update(str(name) for name in binding["missingIndicatorFeatures"])
    return tuple(sorted(columns))


def _indicator_mask(frame: pd.DataFrame, binding: Mapping[str, Any]) -> np.ndarray:
    names = [str(value) for value in binding["missingIndicatorFeatures"]]
    missing = [name for name in names if name not in frame]
    if missing:
        raise PlayerPriorAuthorityError(
            "PRIOR_INDICATOR_INPUT_MISSING",
            f"{binding['feature']} requires registered indicator column(s): {', '.join(missing)}.",
        )
    # The first indicator is the zero/sparse-history authority.  Specialized
    # swing/velocity indicators never make a feature executable by themselves.
    return (
        pd.to_numeric(frame[names[0]], errors="coerce").fillna(0).gt(0).to_numpy()
    )


def _exposure(
    frame: pd.DataFrame, binding: Mapping[str, Any]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    column = str(binding["exposureFeature"])
    if column not in frame:
        raise PlayerPriorAuthorityError(
            "PRIOR_EXPOSURE_INPUT_MISSING",
            f"{binding['feature']} requires exact exposure column {column}.",
        )
    raw = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=np.float64)
    cold_indicator = _indicator_mask(frame, binding)
    missing_raw = ~np.isfinite(raw)
    # Registered annual exposure features are themselves null for genuine no
    # prior history. Only the annual prior-missing flag authorizes zero. A
    # rolling ``insufficient`` flag means 0..window-1 observations and cannot
    # prove that a missing exposure is zero.
    indicator_authorizes_zero = (
        binding["historyWindow"] == "LATEST_ELIGIBLE_PRIOR_SEASON"
    )
    raw = raw.copy()
    raw[missing_raw & cold_indicator & indicator_authorizes_zero] = 0.0
    source_unavailable = missing_raw & ~(
        cold_indicator & indicator_authorizes_zero
    )
    if binding["exposureTransform"] == "EXPM1_VALIDATE_INTEGER":
        values = np.expm1(raw)
    else:
        values = raw
    finite = np.isfinite(values)
    rounded = np.rint(values)
    invalid = finite & (
        (values < -NUMERIC_INTEGER_TOLERANCE)
        | (np.abs(values - rounded) > NUMERIC_INTEGER_TOLERANCE)
    )
    values[finite & ~invalid] = rounded[finite & ~invalid]
    values[invalid] = np.nan
    return values, source_unavailable, invalid


def _rates_and_successes(
    frame: pd.DataFrame, binding: Mapping[str, Any]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    feature = str(binding["feature"])
    if feature not in frame:
        raise PlayerPriorAuthorityError(
            "PRIOR_RAW_FEATURE_MISSING", f"Required prior feature {feature} is absent."
        )
    rates = pd.to_numeric(frame[feature], errors="coerce").to_numpy(dtype=np.float64)
    exposure, source_failure, exposure_failure = _exposure(frame, binding)
    finite_rate = np.isfinite(rates)
    rate_domain_failure = finite_rate & ((rates < 0.0) | (rates > 1.0))
    reconstructed = rates * exposure
    rounded = np.rint(reconstructed)
    integer_failure = (
        finite_rate
        & np.isfinite(exposure)
        & (exposure > 0.0)
        & (np.abs(reconstructed - rounded) > NUMERIC_INTEGER_TOLERANCE)
    )
    successes = rounded.astype(np.float64)
    successes[~finite_rate | ~np.isfinite(exposure)] = np.nan
    numeric_failure = (
        rate_domain_failure
        | integer_failure
        | (finite_rate & np.isfinite(exposure) & (exposure <= 0.0))
        | (np.isfinite(exposure) & (exposure < 0.0))
    )
    return (
        rates,
        exposure,
        successes,
        source_failure,
        exposure_failure | rate_domain_failure | integer_failure | numeric_failure,
    )


def _explicit_reason_masks(frame: pd.DataFrame, feature: str) -> tuple[np.ndarray, np.ndarray]:
    column = f"{feature}{MISSING_REASON_SUFFIX}"
    if column not in frame:
        empty = np.zeros(len(frame), dtype=bool)
        return empty, empty.copy()
    reasons = frame[column].fillna("").astype(str).str.upper()
    source = reasons.isin(
        {"SOURCE_UNAVAILABLE", "SOURCE_MISSING", "SOURCE_NOT_AVAILABLE_FOR_ERA", "IDENTITY_FAILURE"}
    ).to_numpy()
    computation = reasons.eq("COMPUTATION_FAILURE").to_numpy()
    return source, computation


def _latest_player_states(
    frame: pd.DataFrame,
    binding: Mapping[str, Any],
    training_mask: np.ndarray,
) -> pd.DataFrame:
    # Slice first so no feature, exposure, indicator, or player value from a
    # validation/future row is even read while fitting population parameters.
    # ``fit_prior_authority`` reads only ``game_date`` across the caller frame
    # to establish this membership boundary.
    training_frame = frame.loc[training_mask]
    rates, exposure, successes, source_failures, numeric_failures = _rates_and_successes(
        training_frame, binding
    )
    feature = str(binding["feature"])
    explicit_source_failures, explicit_computation_failures = _explicit_reason_masks(
        training_frame, feature
    )
    player_key = str(binding["playerIdentityFeature"])
    if player_key not in training_frame:
        raise PlayerPriorAuthorityError(
            "PRIOR_PLAYER_IDENTITY_MISSING", f"{feature} requires {player_key}."
        )
    players = training_frame[player_key].astype("string")
    dates = pd.to_datetime(training_frame["game_date"], errors="coerce")
    valid = (
        ~source_failures
        & ~numeric_failures
        & ~explicit_source_failures
        & ~explicit_computation_failures
        & players.notna().to_numpy()
        & dates.notna().to_numpy()
        & np.isfinite(rates)
        & np.isfinite(exposure)
        & (exposure > 0.0)
        & np.isfinite(successes)
    )
    states = pd.DataFrame(
        {
            "player": players[valid].astype(str).to_numpy(),
            "game_date": dates[valid].to_numpy(),
            "rate": rates[valid],
            "trials": exposure[valid],
            "successes": successes[valid],
        }
    )
    if states.empty:
        raise PlayerPriorAuthorityError(
            "PRIOR_TRAINING_EVIDENCE_EMPTY",
            f"No valid training evidence exists for {feature}.",
        )
    same_day = states.groupby(["player", "game_date"], sort=False)[["rate", "trials"]].nunique()
    if bool((same_day > 1).any(axis=None)):
        raise PlayerPriorAuthorityError(
            "PRIOR_POINT_IN_TIME_STATE_CONFLICT",
            f"{feature} has conflicting states for one player/date under the completed-day cutoff.",
        )
    states = states.drop_duplicates(["player", "game_date", "rate", "trials", "successes"])
    return (
        states.sort_values(["player", "game_date"], kind="mergesort")
        .groupby("player", sort=True, as_index=False)
        .tail(1)
        .sort_values("player", kind="mergesort")
        .reset_index(drop=True)
    )


def _fit_beta_binomial(states: pd.DataFrame) -> dict[str, Any]:
    trials = states["trials"].to_numpy(dtype=np.float64)
    successes = states["successes"].to_numpy(dtype=np.float64)
    rates = successes / trials
    total_trials = float(trials.sum())
    total_successes = float(successes.sum())
    mean = float((total_successes + 0.5) / (total_trials + 1.0))
    mean = float(np.clip(mean, PROBABILITY_EPSILON, 1.0 - PROBABILITY_EPSILON))
    sample_variance = float(np.var(rates, ddof=1)) if len(rates) > 1 else 0.0
    sampling_variance = float(np.mean(mean * (1.0 - mean) / trials))
    corrected_variance = max(0.0, sample_variance - sampling_variance)
    raw_strength = (
        mean * (1.0 - mean) / corrected_variance - 1.0
        if corrected_variance > PROBABILITY_EPSILON
        else math.nan
    )
    median_exposure = float(np.median(trials))
    exposure_p95 = float(np.quantile(trials, 0.95))
    fallback_used = not math.isfinite(raw_strength) or raw_strength <= 0.0
    strength = median_exposure if fallback_used else raw_strength
    strength = float(np.clip(strength, PROBABILITY_EPSILON, max(exposure_p95, PROBABILITY_EPSILON)))
    alpha = float(mean * strength)
    beta = float((1.0 - mean) * strength)
    return {
        "method": "BETA_BINOMIAL_EMPIRICAL_BAYES_METHOD_OF_MOMENTS",
        "alpha": alpha,
        "beta": beta,
        "priorMean": mean,
        "priorStrength": strength,
        "playerStateCount": int(len(states)),
        "totalObservedTrials": total_trials,
        "totalObservedSuccesses": total_successes,
        "sampleRateVariance": sample_variance,
        "meanBinomialSamplingVariance": sampling_variance,
        "correctedBetweenPlayerVariance": corrected_variance,
        "rawMethodOfMomentsStrength": raw_strength if math.isfinite(raw_strength) else None,
        "underidentifiedFallbackUsed": fallback_used,
        "trainingMedianExposure": median_exposure,
        "trainingExposureP95": exposure_p95,
    }


def _validated_authority_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    content = {
        key: copy.deepcopy(value)
        for key, value in manifest.items()
        if key not in {"authorityChecksum", "authorityId"}
    }
    checksum = _sha256(content)
    expected_id = f"{AUTHORITY_NAME}:sha256:{checksum}"
    if str(manifest.get("authorityChecksum") or "") != checksum:
        raise PlayerPriorAuthorityError(
            "PRIOR_AUTHORITY_CHECKSUM_MISMATCH",
            "Project-bound prior authority failed its content-address check.",
        )
    if str(manifest.get("authorityId") or "") != expected_id:
        raise PlayerPriorAuthorityError(
            "PRIOR_AUTHORITY_ID_MISMATCH",
            "Project-bound prior authority ID does not match its content.",
        )
    if str(manifest.get("authorityName") or "") != AUTHORITY_NAME:
        raise PlayerPriorAuthorityError(
            "PRIOR_AUTHORITY_NAME_MISMATCH",
            "Project-bound prior authority uses an unsupported authority name.",
        )
    if str(manifest.get("configurationChecksum") or "") != authority_checksum():
        raise PlayerPriorAuthorityError(
            "PRIOR_AUTHORITY_CONFIGURATION_STALE",
            "Project-bound prior authority does not bind the current implementation configuration.",
        )
    required = {
        "projectId": manifest.get("projectId"),
        "goldDatasetId": manifest.get("goldDatasetId"),
        "goldManifestSha": manifest.get("goldManifestSha"),
        "treatmentSpecificationSource": manifest.get("treatmentSpecificationSource"),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise PlayerPriorAuthorityError(
            "PRIOR_AUTHORITY_PROJECT_BINDING_MISSING",
            f"Project-bound prior authority is missing: {', '.join(sorted(missing))}.",
        )
    if manifest.get("finalOotPolicy") != "LOCKED_NOT_OPENED_NOT_FIT":
        raise PlayerPriorAuthorityError(
            "PRIOR_AUTHORITY_FINAL_OOT_POLICY_INVALID",
            "Project-bound prior authority must keep final OOT locked and outside fitting.",
        )
    return {**content, "authorityChecksum": checksum, "authorityId": expected_id}


def fit_prior_authority(
    frame: pd.DataFrame,
    *,
    training_end: str,
    authority_manifest: Mapping[str, Any],
    fold_id: str,
    features: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Fit frozen population priors from dates up to ``training_end`` only.

    Rows after the cutoff are inspected only for their date-mask membership;
    no feature value from them participates in a fitted statistic.  Production
    callers should still scan the training partition directly so final OOT is
    never materialized in the first place.
    """

    started = time.perf_counter()
    verified_authority = _validated_authority_manifest(authority_manifest)
    selected = tuple(features or sorted(SUPPORTED_PRIOR_FEATURES))
    required = required_input_columns(selected)
    missing_inputs = [column for column in required if column not in frame]
    if missing_inputs:
        raise PlayerPriorAuthorityError(
            "PRIOR_FIT_INPUT_COLUMNS_MISSING",
            f"Prior fitting input is missing: {', '.join(missing_inputs)}.",
        )
    if "game_date" not in frame:
        raise PlayerPriorAuthorityError("PRIOR_GAME_DATE_MISSING", "game_date is required.")
    cutoff = pd.Timestamp(training_end)
    if cutoff > pd.Timestamp(DEVELOPMENT_END):
        raise PlayerPriorAuthorityError(
            "PRIOR_CUTOFF_CROSSES_FINAL_OOT",
            f"Prior fitting cutoff {training_end} exceeds development end {DEVELOPMENT_END}.",
        )
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if bool(dates.isna().any()):
        raise PlayerPriorAuthorityError(
            "PRIOR_GAME_DATE_INVALID", "Every candidate fitting row requires a valid game_date."
        )
    training_mask = dates.le(cutoff).to_numpy()
    if not bool(training_mask.any()):
        raise PlayerPriorAuthorityError(
            "PRIOR_TRAINING_WINDOW_EMPTY", "No rows are at or before the training cutoff."
        )
    parameters: dict[str, Any] = {}
    for feature in selected:
        binding = _BY_FEATURE[feature]
        states = _latest_player_states(frame, binding, training_mask)
        parameters[feature] = {
            **_fit_beta_binomial(states),
            "exposureFeature": binding["exposureFeature"],
            "playerIdentityFeature": binding["playerIdentityFeature"],
            "historyCutoff": binding["historyCutoff"],
            "decayAuthority": binding["decayAuthority"],
        }
    training_dates = dates[training_mask]
    content = {
        "schemaVersion": FITTED_SCHEMA_VERSION,
        "authorityId": verified_authority["authorityId"],
        "authorityChecksum": verified_authority["authorityChecksum"],
        "authorityConfigurationChecksum": verified_authority["configurationChecksum"],
        "projectId": verified_authority["projectId"],
        "goldDatasetId": verified_authority["goldDatasetId"],
        "goldManifestSha": verified_authority["goldManifestSha"],
        "treatmentSpecificationSource": verified_authority[
            "treatmentSpecificationSource"
        ],
        "foldId": fold_id,
        "trainingStart": training_dates.min().date().isoformat(),
        "trainingEnd": cutoff.date().isoformat(),
        "trainingRows": int(training_mask.sum()),
        "rowsAfterTrainingCutoffExcluded": int((~training_mask).sum()),
        "features": list(selected),
        "parameters": parameters,
        "fitEvidence": {
            "populationUnit": "LATEST_VALID_PLAYER_STATE_AT_OR_BEFORE_TRAINING_CUTOFF",
            "validationFeatureValuesReadForFit": False,
            "targetColumnRead": False,
            "finalOotRowsFit": 0,
            "modelFits": 0,
            "scores": 0,
        },
    }
    checksum = _sha256(content)
    return {
        **content,
        "fittedChecksum": checksum,
        "fittedId": f"{FITTED_SCHEMA_VERSION}:{fold_id}:sha256:{checksum}",
        "fitDurationMs": round((time.perf_counter() - started) * 1000.0, 3),
    }


def _validate_fitted(fitted: Mapping[str, Any]) -> None:
    content = {
        key: value
        for key, value in fitted.items()
        if key not in {"fittedChecksum", "fittedId", "fitDurationMs"}
    }
    checksum = _sha256(content)
    if checksum != str(fitted.get("fittedChecksum") or ""):
        raise PlayerPriorAuthorityError(
            "PRIOR_FITTED_CHECKSUM_MISMATCH", "Fitted prior evidence failed its checksum."
        )
    expected_id = (
        f"{FITTED_SCHEMA_VERSION}:{fitted.get('foldId')}:sha256:{checksum}"
    )
    if str(fitted.get("fittedId") or "") != expected_id:
        raise PlayerPriorAuthorityError(
            "PRIOR_FITTED_ID_MISMATCH",
            "Fitted prior evidence ID does not match its schema, fold, and checksum.",
        )


def transform_prior_feature(
    frame: pd.DataFrame,
    fitted: Mapping[str, Any],
    feature: str,
) -> pd.DataFrame:
    """Return canonical derived preprocessing outputs for one raw feature."""

    _validate_fitted(fitted)
    if feature not in fitted.get("parameters", {}):
        raise PlayerPriorAuthorityError(
            "PRIOR_FEATURE_NOT_FITTED", f"No fitted population parameters exist for {feature}."
        )
    binding = _BY_FEATURE.get(feature)
    if binding is None or not binding["executable"]:
        raise PlayerPriorAuthorityError(
            "PRIOR_FEATURE_NOT_EXECUTABLE", f"{feature} has no executable V1 prior binding."
        )
    required = required_input_columns([feature])
    missing_inputs = [column for column in required if column not in frame]
    if missing_inputs:
        raise PlayerPriorAuthorityError(
            "PRIOR_TRANSFORM_INPUT_COLUMNS_MISSING",
            f"Prior transformation input is missing: {', '.join(missing_inputs)}.",
        )
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if bool(dates.isna().any()):
        raise PlayerPriorAuthorityError(
            "PRIOR_TRANSFORM_GAME_DATE_INVALID",
            "Prior transformation requires a valid game_date for every row.",
        )
    if len(dates) and dates.max() > pd.Timestamp(DEVELOPMENT_END):
        raise PlayerPriorAuthorityError(
            "PRIOR_TRANSFORM_CROSSES_FINAL_OOT",
            f"V1 prior transformation cannot read rows after {DEVELOPMENT_END}.",
        )
    rates, exposure, successes, inferred_source, numeric_failure = _rates_and_successes(
        frame, binding
    )
    explicit_source, explicit_computation = _explicit_reason_masks(frame, feature)
    cold_indicator = _indicator_mask(frame, binding)
    finite_rate = np.isfinite(rates)
    finite_exposure = np.isfinite(exposure)
    source_failure = (
        explicit_source
        | inferred_source
        # A missing registered rate beside a valid positive source exposure is
        # an unavailable source component, not a legitimate no-history state.
        # Only an explicit COMPUTATION_FAILURE reason may override this class.
        | (finite_exposure & (exposure > 0.0) & ~finite_rate)
    ) & ~explicit_computation
    computation_failure = (
        explicit_computation
        | numeric_failure
        | (finite_rate & (~finite_exposure | (exposure <= 0.0)))
    ) & ~source_failure
    cold = (
        ~source_failure
        & ~computation_failure
        & ~finite_rate
        & finite_exposure
        & (exposure == 0.0)
        & cold_indicator
    )
    observed = (
        ~source_failure
        & ~computation_failure
        & finite_rate
        & finite_exposure
        & (exposure > 0.0)
        & np.isfinite(successes)
    )
    unresolved = ~(source_failure | computation_failure | cold | observed)
    computation_failure |= unresolved

    parameter = fitted["parameters"][feature]
    alpha = float(parameter["alpha"])
    beta = float(parameter["beta"])
    n = len(frame)
    effective_n = np.full(n, np.nan, dtype=np.float64)
    observed_successes = np.full(n, np.nan, dtype=np.float64)
    effective_n[cold] = 0.0
    observed_successes[cold] = 0.0
    effective_n[observed] = exposure[observed]
    observed_successes[observed] = successes[observed]
    posterior_alpha = alpha + observed_successes
    posterior_beta = beta + effective_n - observed_successes
    posterior_strength = posterior_alpha + posterior_beta
    posterior_mean = posterior_alpha / posterior_strength
    posterior_variance = (
        posterior_alpha
        * posterior_beta
        / (posterior_strength**2 * (posterior_strength + 1.0))
    )
    posterior_std = np.sqrt(posterior_variance)
    reliability = effective_n / (float(parameter["priorStrength"]) + effective_n)

    state = np.full(n, "COMPUTATION_FAILURE", dtype=object)
    state[source_failure] = "SOURCE_UNAVAILABLE"
    state[cold] = "TRUE_COLD_START"
    if binding["historyWindow"] == "LATEST_ELIGIBLE_PRIOR_SEASON":
        state[observed] = "PRIOR_SEASON_ONLY"
    else:
        threshold = float(binding["establishedThreshold"])
        state[observed & (exposure < threshold)] = "SPARSE_HISTORY"
        state[observed & (exposure >= threshold)] = "ESTABLISHED_HISTORY"
    level = np.full(n, "NONE_FAIL_CLOSED", dtype=object)
    level[cold] = "MLB_LEAGUE_POPULATION"
    level[observed] = "PLAYER_HISTORY_PLUS_MLB_LEAGUE_POPULATION"

    outputs = binding["derivedOutputs"]
    valid_posterior = cold | observed
    prior_alpha = np.where(valid_posterior, alpha, np.nan)
    prior_beta = np.where(valid_posterior, beta, np.nan)
    prior_strength = np.where(valid_posterior, float(parameter["priorStrength"]), np.nan)
    return pd.DataFrame(
        {
            outputs["posteriorMean"]: posterior_mean,
            outputs["effectiveN"]: effective_n,
            outputs["priorStrength"]: prior_strength,
            outputs["posteriorStrength"]: posterior_strength,
            outputs["posteriorVariance"]: posterior_variance,
            outputs["posteriorStd"]: posterior_std,
            outputs["posteriorReliability"]: reliability,
            outputs["historyState"]: state,
            outputs["priorLevel"]: level,
            outputs["observedSuccesses"]: observed_successes,
            outputs["observedTrials"]: effective_n,
            outputs["priorAlpha"]: prior_alpha,
            outputs["priorBeta"]: prior_beta,
            outputs["posteriorAlpha"]: posterior_alpha,
            outputs["posteriorBeta"]: posterior_beta,
            outputs["decayWeight"]: np.where(valid_posterior, 1.0, np.nan),
            # Exact age is not in Current Gold.  V1 explicitly uses no decay
            # rather than fabricating an observation date.
            outputs["observationAgeDays"]: np.full(n, np.nan, dtype=np.float64),
        },
        index=frame.index,
    )


def transform_prior_features(
    frame: pd.DataFrame,
    fitted: Mapping[str, Any],
    *,
    features: Sequence[str] | None = None,
) -> pd.DataFrame:
    selected = tuple(features or fitted.get("features") or ())
    parts = [transform_prior_feature(frame, fitted, feature) for feature in selected]
    return pd.concat(parts, axis=1) if parts else pd.DataFrame(index=frame.index)


def preprocessing_identity(
    *,
    fitted: Mapping[str, Any],
    model_family: str,
    scaler_fit_rows_checksum: str | None = None,
) -> dict[str, Any]:
    """Bind downstream family/scaling evidence to the frozen prior fit."""

    _validate_fitted(fitted)
    family = model_family.upper()
    if family not in {"TREE", "LINEAR", "NEURAL_OR_DISTANCE"}:
        raise PlayerPriorAuthorityError(
            "PRIOR_MODEL_FAMILY_UNSUPPORTED", f"Unsupported model family {model_family}."
        )
    if family != "TREE" and not str(scaler_fit_rows_checksum or "").strip():
        raise PlayerPriorAuthorityError(
            "PRIOR_SCALER_FIT_EVIDENCE_REQUIRED",
            f"{family} preprocessing requires a training-row scaler checksum.",
        )
    content = {
        "schemaVersion": "MLB_PLAYER_PRIOR_PREPROCESSOR_BINDING_V1",
        "authorityId": fitted["authorityId"],
        "fittedPriorId": fitted["fittedId"],
        "fittedPriorChecksum": fitted["fittedChecksum"],
        "modelFamily": family,
        "scientificValueAuthority": "CANONICAL_VALUES_IDENTICAL_ACROSS_MODEL_FAMILIES",
        "scaling": (
            "NONE_TREE_NATIVE" if family == "TREE" else "TRAINING_ROWS_ONLY"
        ),
        "scalerFitRowsChecksum": scaler_fit_rows_checksum,
        "modelFitCreated": False,
    }
    checksum = _sha256(content)
    return {
        **content,
        "checksum": checksum,
        "id": f"MLB_PLAYER_PRIOR_PREPROCESSOR_BINDING_V1:sha256:{checksum}",
    }


def development_diagnostics(
    frame: pd.DataFrame,
    fitted: Mapping[str, Any],
    *,
    features: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Compute target-free aggregate diagnostics without retaining derived rows."""

    started = time.perf_counter()
    selected = tuple(features or fitted.get("features") or ())
    if "game_date" not in frame:
        raise PlayerPriorAuthorityError(
            "PRIOR_DIAGNOSTIC_GAME_DATE_MISSING",
            "Development diagnostics require game_date boundary evidence.",
        )
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if bool(dates.isna().any()):
        raise PlayerPriorAuthorityError(
            "PRIOR_DIAGNOSTIC_GAME_DATE_INVALID",
            "Development diagnostics require a valid date for every row.",
        )
    if len(dates) and dates.max() > pd.Timestamp(DEVELOPMENT_END):
        raise PlayerPriorAuthorityError(
            "PRIOR_DIAGNOSTIC_CROSSES_FINAL_OOT",
            f"Development diagnostics cannot read rows after {DEVELOPMENT_END}.",
        )
    overall_states: Counter[str] = Counter()
    overall_levels: Counter[str] = Counter()
    row_state_presence: dict[str, np.ndarray] = {}
    row_level_presence: dict[str, np.ndarray] = {}
    per_feature: dict[str, Any] = {}
    all_reliability: list[np.ndarray] = []
    all_effective_n: list[np.ndarray] = []
    all_adjustments: list[np.ndarray] = []
    for feature in selected:
        binding = _BY_FEATURE[feature]
        transformed = transform_prior_feature(frame, fitted, feature)
        outputs = binding["derivedOutputs"]
        states = transformed[outputs["historyState"]]
        levels = transformed[outputs["priorLevel"]]
        state_counts = Counter(states.astype(str))
        level_counts = Counter(levels.astype(str))
        overall_states.update(state_counts)
        overall_levels.update(level_counts)
        for state_name in state_counts:
            present = states.eq(state_name).to_numpy()
            row_state_presence.setdefault(
                state_name, np.zeros(len(frame), dtype=bool)
            )[:] |= present
        for level_name in level_counts:
            present = levels.eq(level_name).to_numpy()
            row_level_presence.setdefault(
                level_name, np.zeros(len(frame), dtype=bool)
            )[:] |= present
        reliability = pd.to_numeric(
            transformed[outputs["posteriorReliability"]], errors="coerce"
        ).to_numpy(dtype=np.float64)
        effective_n = pd.to_numeric(
            transformed[outputs["effectiveN"]], errors="coerce"
        ).to_numpy(dtype=np.float64)
        posterior = pd.to_numeric(
            transformed[outputs["posteriorMean"]], errors="coerce"
        ).to_numpy(dtype=np.float64)
        raw = pd.to_numeric(frame[feature], errors="coerce").to_numpy(dtype=np.float64)
        adjustment = posterior - raw
        all_reliability.append(reliability[np.isfinite(reliability)])
        all_effective_n.append(effective_n[np.isfinite(effective_n)])
        all_adjustments.append(adjustment[np.isfinite(adjustment)])
        month = dates.dt.to_period("M").astype(str)
        adjustment_frame = pd.DataFrame({"month": month, "adjustment": adjustment})
        adjustment_by_month = {
            str(key): float(value)
            for key, value in adjustment_frame.groupby("month", sort=True)["adjustment"].median().dropna().items()
        }
        adjustment_state_frame = pd.DataFrame(
            {"state": states.astype(str), "adjustment": adjustment}
        )
        adjustment_by_state = {
            str(key): float(value)
            for key, value in adjustment_state_frame.groupby("state", sort=True)["adjustment"].median().dropna().items()
        }
        per_feature[feature] = {
            "historyStateCounts": dict(sorted(state_counts.items())),
            "priorLevelCounts": dict(sorted(level_counts.items())),
            "medianReliability": _finite_quantile(reliability, 0.5),
            "reliabilityQuantiles": _quantiles(reliability),
            "effectiveSampleSizeQuantiles": _quantiles(effective_n),
            "posteriorMinusRawQuantiles": _quantiles(adjustment),
            "medianAdjustmentBySeasonMonth": adjustment_by_month,
            "medianAdjustmentByHistoryState": adjustment_by_state,
        }
    reliability_values = np.concatenate(all_reliability) if all_reliability else np.array([])
    effective_values = np.concatenate(all_effective_n) if all_effective_n else np.array([])
    adjustment_values = np.concatenate(all_adjustments) if all_adjustments else np.array([])
    return {
        "schemaVersion": "MLB_PLAYER_STATE_PRIOR_DIAGNOSTICS_V1",
        "scope": "DEVELOPMENT_ONLY_FEATURE_CELLS",
        "authorityId": fitted["authorityId"],
        "fittedPriorId": fitted["fittedId"],
        "rows": int(len(frame)),
        "featureCount": len(selected),
        "dateBoundary": {
            "minimum": dates.min().date().isoformat() if len(dates) else None,
            "maximum": dates.max().date().isoformat() if len(dates) else None,
            "authorizedDevelopmentEnd": DEVELOPMENT_END,
            "validated": True,
        },
        "historyStateCounts": dict(sorted(overall_states.items())),
        "priorLevelCounts": dict(sorted(overall_levels.items())),
        "rowHistoryStatePresenceCounts": {
            key: int(value.sum()) for key, value in sorted(row_state_presence.items())
        },
        "rowPriorLevelPresenceCounts": {
            key: int(value.sum()) for key, value in sorted(row_level_presence.items())
        },
        "rowsUsingPlayerHistory": int(
            row_level_presence.get(
                "PLAYER_HISTORY_PLUS_MLB_LEAGUE_POPULATION",
                np.zeros(len(frame), dtype=bool),
            ).sum()
        ),
        "rowsUsingRolePrior": 0,
        "rowsUsingLeaguePrior": int(
            row_level_presence.get(
                "MLB_LEAGUE_POPULATION", np.zeros(len(frame), dtype=bool)
            ).sum()
        ),
        "trueColdStartRows": int(
            row_state_presence.get(
                "TRUE_COLD_START", np.zeros(len(frame), dtype=bool)
            ).sum()
        ),
        "medianReliability": _finite_quantile(reliability_values, 0.5),
        "reliabilityQuantiles": _quantiles(reliability_values),
        "effectiveSampleSizeQuantiles": _quantiles(effective_values),
        "posteriorMinusRawQuantiles": _quantiles(adjustment_values),
        "perFeature": per_feature,
        "targetRead": False,
        "finalOotRowsRead": 0,
        "modelFits": 0,
        "durationMs": round((time.perf_counter() - started) * 1000.0, 3),
    }


def _finite_quantile(values: np.ndarray, quantile: float) -> float | None:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    return float(np.quantile(finite, quantile)) if len(finite) else None


def _quantiles(values: np.ndarray) -> dict[str, float | None]:
    return {
        label: _finite_quantile(values, value)
        for label, value in (("p0", 0.0), ("p25", 0.25), ("p50", 0.5), ("p75", 0.75), ("p90", 0.9), ("p100", 1.0))
    }


__all__ = [
    "AUTHORITY_NAME",
    "BLOCKED_PRIOR_FEATURES",
    "DEVELOPMENT_END",
    "FITTED_SCHEMA_VERSION",
    "PRIOR_FEATURES",
    "PlayerPriorAuthorityError",
    "SCHEMA_VERSION",
    "SUPPORTED_PRIOR_FEATURES",
    "authority_checksum",
    "authority_configuration",
    "development_diagnostics",
    "feature_binding",
    "fit_prior_authority",
    "preprocessing_identity",
    "project_authority_manifest",
    "required_input_columns",
    "transform_prior_feature",
    "transform_prior_features",
]
