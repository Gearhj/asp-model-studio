"""Project-bound, development-only Outlier and Missing Value studios.

The module deliberately builds on :mod:`stage3_eda`'s accepted Current-Gold
authority and scanner.  Every analytical read is therefore project-bound and
has the final-OOT date predicate injected before Arrow materializes a target
column.  Treatment output is descriptive preview only; adopted records store a
fitting rule for later chronological, training-fold-local preprocessing.
"""
from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from ..persistence.db import Database
from ..persistence.repositories.stage3_treatment_repository import (
    Stage3TreatmentPersistenceError,
    Stage3TreatmentRepository,
)
from ..sports_datasets.consumer import canonical_json_bytes
from ..sports_gold.contracts import GOLD_CLASS_ORDER
from . import stage3_eda as eda


OUTLIER_DETECTION_METHODS = (
    "NO_STATISTICAL_DETECTION",
    "IQR_1_5",
    "IQR_3_0",
    "P95_UPPER",
    "P99_UPPER",
    "P05_P95",
    "P01_P99",
    "DOMAIN_BOUNDS",
)
OUTLIER_TREATMENTS = (
    "RETAIN",
    "FLAG_ONLY",
    "CAP_IQR",
    "WINSORIZE",
    "CAP_P95",
    "CAP_P99",
    "SET_MISSING",
    "EXCLUDE_ROW",
)
IMPUTATION_METHODS = (
    "RETAIN_WITH_INDICATOR",
    "MEAN",
    "MEDIAN",
    "MODE",
    "CONSTANT",
    "GOVERNED_PRIOR",
    "PREDICTED",
    "UNKNOWN_CATEGORY",
    "DROP_VARIABLE",
    "EXCLUDE_ROW",
)

DEFAULT_OUTLIER_METHOD = "IQR_1_5"
DEFAULT_OUTLIER_TREATMENT = "RETAIN"
DEFAULT_IMPUTATION_METHOD = "DATA_TYPE_AWARE"
_IMPUTATION_DEFAULT_ALIASES = {"DATA_TYPE_AWARE", "TYPE_AWARE_DEFAULT"}
MAX_PAGE_SIZE = 100
MAX_SELECTED_VARIABLES = 300
MAX_PREVIEW_PREDICTORS = 12
PREDICTED_PREVIEW_SEED = 731_026
PREDICTED_PREVIEW_MAX_TRAIN = 50_000
PREDICTED_PREVIEW_MAX_EVAL = 20_000
# One scan per variable made the project-bound gallery impractically slow.
# Thirty-two numeric predictors plus the small identity/support set keeps the
# transient frame bounded while reducing the accepted 157-variable authority
# to five deterministic parquet passes.
PROFILE_COLUMN_BATCH_SIZE = 32

_OUTLIER_SORT_FIELDS = frozenset({
    "numberOfOutliers", "variable", "label", "outlierPercent",
    "lowerTailCount", "upperTailCount", "dataType", "featureFamily",
    "core", "selectable", "active", "role", "developmentNonmissingN",
    "missingN", "lowerThreshold", "upperThreshold", "min", "q1",
    "median", "q3", "max", "mean", "standardDeviation",
    "selectedDetectionMethod", "selectedTreatment", "affectedGames",
    "affectedPlayers", "affectedBatters", "affectedPitchers", "status",
})
_MISSING_SORT_FIELDS = frozenset({
    "numberOfMissingValues", "variable", "missingPercent", "developmentN",
    "observedN", "dataType", "featureFamily", "role", "core", "selectable",
    "primaryReason", "noPriorHistoryCount", "insufficientHistoryCount",
    "sourceUnavailableCount", "computationFailureCount", "identityFailureCount",
    "selectedImputationMethod", "descriptivePreviewValue", "affectedGames",
    "affectedBatters", "affectedPitchers", "status",
})

# These are mathematical/physical domains declared by the frozen Gold feature
# definitions or the accepted simulation-state contract.  No heuristic bounds
# are inferred for any other variable.
_RATE_FEATURES = {
    "batter_last100_strikeout_rate",
    "batter_last100_walk_hbp_rate",
    "batter_last100_contact_rate",
    "batter_last100_whiff_rate",
    "pitcher_last250_strikeout_rate",
    "pitcher_last250_walk_rate",
    "pitcher_last250_whiff_rate",
    "pitcher_last250_fastball_usage",
    "pitcher_last250_breaking_usage",
    "pitcher_last250_offspeed_usage",
}
_GOVERNED_DOMAIN_BOUNDS: Mapping[str, tuple[float, float]] = {
    **{name: (0.0, 1.0) for name in _RATE_FEATURES},
    "context_outs_before": (0.0, 2.0),
    "context_bases_mask": (0.0, 7.0),
}
# No Current-Gold V1 feature definition registers a reusable hierarchical
# imputation-prior contract. This explicit empty authority prevents a rate or
# mathematical bound from being mistaken for scientific prior authority.
_GOVERNED_PRIOR_FEATURES: frozenset[str] = frozenset()

_RESULT_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_PROFILE_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_CACHE_LOCK = threading.RLock()
_PROFILE_KEY_LOCKS: dict[str, threading.Lock] = {}


class Stage3TreatmentError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)

    def public_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


def _stable_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _cache_get(key: str, *, profile: bool = False) -> dict[str, Any] | None:
    cache = _PROFILE_CACHE if profile else _RESULT_CACHE
    with _CACHE_LOCK:
        value = cache.get(key)
        if value is not None:
            cache.move_to_end(key)
        return value


def _cache_put(key: str, value: dict[str, Any], *, profile: bool = False) -> None:
    cache = _PROFILE_CACHE if profile else _RESULT_CACHE
    limit = 1024 if profile else 64
    with _CACHE_LOCK:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)


def _invalidate_policy_summary(authority: eda._Authority, kind: str) -> None:
    prefix = "outlier-summary:" if kind == "OUTLIER" else "missing-summary:"
    key = prefix + _stable_hash({"authority": authority.review_digest})
    with _CACHE_LOCK:
        _RESULT_CACHE.pop(key, None)


def _profile_key_lock(key: str) -> threading.Lock:
    with _CACHE_LOCK:
        return _PROFILE_KEY_LOCKS.setdefault(key, threading.Lock())


def _authority_payload(authority: eda._Authority) -> dict[str, Any]:
    public = {
        **authority.public(),
        "registrationId": authority.registration_id,
        "datasetVersionId": authority.dataset_version_id,
        "activationRevision": authority.activation_revision,
    }
    public["authorityKey"] = ":".join(
        (
            authority.source_manifest_sha,
            authority.gold_manifest_sha,
            authority.contextual_manifest_sha,
            authority.review_digest,
        )
    )
    return public


def _persistence_authority(authority: eda._Authority) -> dict[str, Any]:
    return {
        **_authority_payload(authority),
        "development": {
            "startDate": eda.DEVELOPMENT_START,
            "endDate": eda.DEVELOPMENT_END,
            "rows": eda.DEVELOPMENT_ROWS,
        },
        "finalOot": {
            "startDate": eda.EXPECTED_FINAL_OOT[0],
            "endDate": eda.EXPECTED_FINAL_OOT[1],
            "rows": eda.FINAL_OOT_ROWS,
            "locked": True,
        },
    }


def _assert_authority_key(authority: eda._Authority, payload: Mapping[str, Any]) -> None:
    supplied = str(payload.get("authorityKey") or "").strip()
    expected = str(_authority_payload(authority)["authorityKey"])
    if not supplied:
        raise Stage3TreatmentError(
            "TREATMENT_AUTHORITY_REQUIRED",
            "The exact project-bound Stage 3 authority key is required.",
            status_code=409,
        )
    if supplied != expected:
        raise Stage3TreatmentError(
            "TREATMENT_AUTHORITY_STALE",
            "The treatment request does not match the currently accepted Stage 2/Stage 3 authority.",
            status_code=409,
        )


def _audit(*, preprocessing_fits: int = 0) -> dict[str, Any]:
    return {
        **eda._audit_flags(),
        "sourceOrGoldMutated": False,
        "preprocessingPreviewActivity": {
            "predictedImputerFits": int(preprocessing_fits),
            "outcomeModelFits": 0,
            "registeredCandidates": 0,
            "promotions": 0,
        },
    }


def _population(filters: Mapping[str, Any], rows: int, aggregation: str) -> dict[str, Any]:
    return eda._population(filters=filters, rows=rows, aggregation=aggregation)


def _envelope(
    authority: eda._Authority,
    *,
    filters: Mapping[str, Any],
    rows: int,
    aggregation: str,
    data: Mapping[str, Any],
    cache_status: str = "MISS",
    duration_ms: float | None = None,
    preprocessing_fits: int = 0,
) -> dict[str, Any]:
    result = {
        "ok": True,
        "authority": _authority_payload(authority),
        "population": _population(filters, rows, aggregation),
        "audit": _audit(preprocessing_fits=preprocessing_fits),
        "data": eda._json_safe(dict(data)),
        "cacheStatus": cache_status,
    }
    if duration_ms is not None:
        result["queryDurationMs"] = round(duration_ms, 3)
    return result


def _filtered_population_rows(authority: eda._Authority, filters: Mapping[str, Any]) -> int:
    if not filters:
        return eda.DEVELOPMENT_ROWS
    identity = "canonicalPaId" if "canonicalPaId" in authority.schema.names else authority.schema.names[0]
    return len(eda._scan(authority, [identity], filters))


def _normalize_request(
    authority: eda._Authority,
    payload: Any,
    variables: Sequence[str] = (),
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise Stage3TreatmentError("TREATMENT_REQUEST_INVALID", "The request body must be an object.")
    _assert_authority_key(authority, payload)
    try:
        filters = eda._normalize_filters(payload.get("filters"), set(authority.schema.names), variables)
    except eda.Stage3EdaError as exc:
        raise Stage3TreatmentError(exc.code, str(exc), status_code=exc.status_code) from exc
    if filters.get("outcomes"):
        raise Stage3TreatmentError(
            "TARGET_DERIVED_TREATMENT_PROHIBITED",
            "Treatment thresholds, fill values, and policy previews cannot be conditioned on the governed outcome target.",
        )
    return payload, filters


def _catalog(authority: eda._Authority) -> dict[str, dict[str, Any]]:
    return {str(item["name"]): dict(item) for item in eda._variables(authority)}


def _looks_binary(name: str, meta: Mapping[str, Any]) -> bool:
    category = str(meta.get("category") or "").upper()
    return (
        meta.get("role") == "MISSINGNESS_INDICATOR"
        or name.startswith("is_")
        or "BINARY" in name.upper()
        or name.endswith(("_indicator", "_missing", "_insufficient"))
        or name.startswith(("played_", "crossed_", "returned_", "first_game_"))
        or name in {
            "same_league_game", "interleague_game", "division_game", "same_division",
            "doubleheader_today", "doubleheader_yesterday", "previous_game_was_away",
            "previous_game_was_home", "repeat_opponent_within_7_days",
            "repeat_opponent_within_14_days", "series_rematch_indicator",
            "matchup_batter_bats_left", "matchup_batter_bats_switch",
            "matchup_pitcher_throws_left", "matchup_platoon_advantage",
        }
        or "BINARY" in category
    )


def _eligible_outlier_meta(authority: eda._Authority, *, include_advanced: bool) -> list[dict[str, Any]]:
    rows = []
    for meta in _catalog(authority).values():
        if not meta.get("selectable") or meta.get("dataType") != "numeric":
            continue
        if meta.get("role") not in {"PREGAME_FEATURE", "SIMULATION_GENERATED_STATE"}:
            continue
        if not include_advanced and (meta.get("role") == "SIMULATION_GENERATED_STATE" or _looks_binary(str(meta["name"]), meta)):
            continue
        rows.append(meta)
    return rows


def _eligible_missing_meta(authority: eda._Authority) -> list[dict[str, Any]]:
    return [
        meta
        for meta in _catalog(authority).values()
        if meta.get("selectable")
        and meta.get("role") in {"PREGAME_FEATURE", "MISSINGNESS_INDICATOR", "SIMULATION_GENERATED_STATE"}
    ]


def _outlier_exclusion_reason(meta: Mapping[str, Any]) -> str:
    if not meta.get("selectable"):
        return "NOT_SELECTABLE_BY_ACCEPTED_FEATURE_CONTRACT"
    if meta.get("dataType") != "numeric":
        return "OUTLIER_DIAGNOSTICS_REQUIRE_NUMERIC_DATA"
    return f"{meta.get('role') or 'UNKNOWN'}_ROLE_NOT_ELIGIBLE_FOR_OUTLIER_TREATMENT"


def _missing_exclusion_reason(meta: Mapping[str, Any]) -> str:
    if not meta.get("selectable"):
        return "NOT_SELECTABLE_BY_ACCEPTED_FEATURE_CONTRACT"
    return f"{meta.get('role') or 'UNKNOWN'}_ROLE_NOT_ELIGIBLE_FOR_IMPUTATION"


def _excluded_outlier_row(meta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "numberOfOutliers": None,
        "variable": str(meta["name"]),
        "label": meta.get("label"),
        "outlierPercent": None,
        "lowerTailCount": None,
        "upperTailCount": None,
        "dataType": meta.get("dataType"),
        "featureFamily": meta.get("featureFamily"),
        "role": meta.get("role"),
        "core": bool(meta.get("core")),
        "selectable": bool(meta.get("selectable")),
        "eligible": False,
        "active": False,
        "role": meta.get("role"),
        "developmentNonmissingN": None,
        "missingN": None,
        "lowerThreshold": None,
        "upperThreshold": None,
        "min": None,
        "q1": None,
        "median": None,
        "q3": None,
        "max": None,
        "mean": None,
        "standardDeviation": None,
        "selectedDetectionMethod": None,
        "selectedTreatment": None,
        "treatmentValueOrBounds": "Read-only metadata inspection; no treatment is authorized.",
        "affectedGames": None,
        "affectedPlayers": None,
        "affectedBatters": None,
        "affectedPitchers": None,
        "status": "NOT_EVALUATED",
        "exclusionReason": _outlier_exclusion_reason(meta),
        "override": False,
        "eligibleDetectionMethods": [],
        "eligibleTreatments": [],
        "ineligibleReasons": {"ALL": _outlier_exclusion_reason(meta)},
        "previewLabel": "READ-ONLY EXCLUDED METADATA — NOT EVALUATED",
    }


def _excluded_missing_row(meta: Mapping[str, Any]) -> dict[str, Any]:
    reason = _missing_exclusion_reason(meta)
    return {
        "numberOfMissingValues": None,
        "variable": str(meta["name"]),
        "missingPercent": None,
        "developmentN": None,
        "observedN": None,
        "dataType": meta.get("dataType"),
        "featureFamily": meta.get("featureFamily"),
        "role": meta.get("role"),
        "core": bool(meta.get("core")),
        "selectable": bool(meta.get("selectable")),
        "eligible": False,
        "primaryReason": "NOT_EVALUATED",
        "noPriorHistoryCount": None,
        "insufficientHistoryCount": None,
        "sourceUnavailableCount": None,
        "computationFailureCount": None,
        "identityFailureCount": None,
        "pairedMissingnessIndicator": None,
        "governedPriorAvailable": False,
        "governedPriorUnavailableReason": reason,
        "selectedImputationMethod": None,
        "imputedValueOrPolicy": "Read-only metadata inspection; no imputation is authorized.",
        "descriptivePreviewValue": None,
        "descriptivePreviewOnly": True,
        "eligibleMethods": [],
        "ineligibleMethodReasons": {"ALL": reason},
        "affectedGames": None,
        "affectedBatters": None,
        "affectedPitchers": None,
        "status": "NOT_EVALUATED",
        "exclusionReason": reason,
        "override": False,
        "previewLabel": "READ-ONLY EXCLUDED METADATA — NOT EVALUATED",
    }


def _finite_numeric(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").astype(float)
    return numeric.where(np.isfinite(numeric), np.nan)


def _statistics(values: pd.Series) -> dict[str, Any]:
    clean = _finite_numeric(values).dropna()
    if clean.empty:
        return {
            "count": 0,
            "missingCount": int(len(values)),
            "min": None,
            "p01": None,
            "p05": None,
            "q1": None,
            "median": None,
            "q3": None,
            "p95": None,
            "p99": None,
            "max": None,
            "mean": None,
            "std": None,
        }
    q = clean.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
    return {
        "count": int(len(clean)),
        "missingCount": int(len(values) - len(clean)),
        "min": float(clean.min()),
        "p01": float(q.loc[0.01]),
        "p05": float(q.loc[0.05]),
        "q1": float(q.loc[0.25]),
        "median": float(q.loc[0.5]),
        "q3": float(q.loc[0.75]),
        "p95": float(q.loc[0.95]),
        "p99": float(q.loc[0.99]),
        "max": float(clean.max()),
        "mean": float(clean.mean()),
        "std": float(clean.std(ddof=1)) if len(clean) > 1 else 0.0,
    }


def _detection_bounds(
    variable: str,
    statistics: Mapping[str, Any],
    method: str,
) -> tuple[float | None, float | None]:
    if method not in OUTLIER_DETECTION_METHODS:
        raise Stage3TreatmentError("OUTLIER_METHOD_UNSUPPORTED", f"Unsupported outlier detection method: {method}.")
    if method == "NO_STATISTICAL_DETECTION":
        return None, None
    if int(statistics.get("count") or 0) == 0:
        return None, None
    q1 = float(statistics["q1"])
    q3 = float(statistics["q3"])
    if method in {"IQR_1_5", "IQR_3_0"}:
        factor = 1.5 if method == "IQR_1_5" else 3.0
        width = q3 - q1
        return q1 - factor * width, q3 + factor * width
    if method == "P95_UPPER":
        return None, float(statistics["p95"])
    if method == "P99_UPPER":
        return None, float(statistics["p99"])
    if method == "P05_P95":
        return float(statistics["p05"]), float(statistics["p95"])
    if method == "P01_P99":
        return float(statistics["p01"]), float(statistics["p99"])
    bounds = _GOVERNED_DOMAIN_BOUNDS.get(variable)
    if bounds is None:
        raise Stage3TreatmentError(
            "DOMAIN_BOUNDS_UNAVAILABLE",
            f"{variable} has no registered physical or mathematical bounds.",
        )
    return bounds


def _outlier_masks(
    values: pd.Series,
    lower: float | None,
    upper: float | None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    numeric = _finite_numeric(values)
    low = numeric.lt(lower) if lower is not None else pd.Series(False, index=values.index)
    high = numeric.gt(upper) if upper is not None else pd.Series(False, index=values.index)
    return low, high, low | high


def _entity_counts(frame: pd.DataFrame, mask: pd.Series) -> dict[str, int]:
    def unique(name: str) -> int:
        return int(frame.loc[mask, name].nunique(dropna=True)) if name in frame else 0

    batter = unique("batterCanonicalPlayerId")
    pitcher = unique("pitcherCanonicalPlayerId")
    player_values = []
    for name in ("batterCanonicalPlayerId", "pitcherCanonicalPlayerId"):
        if name in frame:
            player_values.append(frame.loc[mask, name])
    players = int(pd.concat(player_values, ignore_index=True).nunique(dropna=True)) if player_values else 0
    return {
        "affectedGames": unique("canonicalGameId"),
        "affectedBatters": batter,
        "affectedPitchers": pitcher,
        "affectedPlayers": players,
    }


def _outlier_profile_key(authority: eda._Authority, variable: str, filters: Mapping[str, Any]) -> str:
    return "outlier-profile:" + _stable_hash(
        {"authority": authority.review_digest, "variable": variable, "filters": dict(filters)}
    )


def _calculate_outlier_profile(
    frame: pd.DataFrame, variable: str
) -> dict[str, Any]:
    statistics = _statistics(frame[variable])
    methods: dict[str, Any] = {}
    for method in OUTLIER_DETECTION_METHODS:
        if method == "DOMAIN_BOUNDS" and variable not in _GOVERNED_DOMAIN_BOUNDS:
            continue
        if method == "NO_STATISTICAL_DETECTION":
            methods[method] = {
                "method": method,
                "lowerThreshold": None,
                "upperThreshold": None,
                # The workbook carries semantic recommendations but no exact
                # outlier-count export.  Null is intentionally different from
                # a measured zero-outlier result.
                "lowerTailCount": None,
                "upperTailCount": None,
                "outlierCount": None,
                "outlierPercent": None,
                "affectedGames": None,
                "affectedBatters": None,
                "affectedPitchers": None,
                "affectedPlayers": None,
            }
            continue
        lower, upper = _detection_bounds(variable, statistics, method)
        low, high, mask = _outlier_masks(frame[variable], lower, upper)
        methods[method] = {
            "method": method,
            "lowerThreshold": lower,
            "upperThreshold": upper,
            "lowerTailCount": int(low.sum()),
            "upperTailCount": int(high.sum()),
            "outlierCount": int(mask.sum()),
            "outlierPercent": eda._percent(int(mask.sum()), len(frame)),
            **_entity_counts(frame, mask),
        }
    return {"statistics": statistics, "methods": methods, "rows": len(frame)}


def _prime_outlier_profiles(
    authority: eda._Authority,
    metas: Sequence[Mapping[str, Any]],
    filters: Mapping[str, Any],
    *,
    union_method: str | None = None,
    union_spec: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, int] | None:
    """Populate variable profiles using bounded column batches.

    Summary requests also build an exact union mask. Each batch is scanned in
    the same dataset order and canonical PA identities are checked before its
    mask is merged, so union counts never become predictor-cell sums.
    """
    union_key = "outlier-union:" + _stable_hash(
        {
            "authority": authority.review_digest,
            "filters": dict(filters),
            "method": union_method,
            "specification": {key: dict(value) for key, value in (union_spec or {}).items()},
        }
    )
    union_requested = union_method is not None or union_spec is not None
    if union_requested:
        cached_union = _cache_get(union_key, profile=True)
        if cached_union is not None:
            return {key: int(value) for key, value in cached_union.items()}
    requested_metas = list(metas)
    if not union_requested:
        requested_metas = [
            meta
            for meta in requested_metas
            if _cache_get(_outlier_profile_key(authority, str(meta["name"]), filters), profile=True) is None
        ]
    if not requested_metas:
        return None
    entity_columns = [
        name
        for name in (
            "canonicalPaId", "canonicalGameId", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId"
        )
        if name in authority.schema.names
    ]
    union_mask: np.ndarray | None = None
    identity_frame: pd.DataFrame | None = None
    canonical_ids: pd.Series | None = None
    for offset in range(0, len(requested_metas), PROFILE_COLUMN_BATCH_SIZE):
        group = requested_metas[offset:offset + PROFILE_COLUMN_BATCH_SIZE]
        variables = [str(meta["name"]) for meta in group]
        frame = eda._scan(authority, list(dict.fromkeys([*variables, *entity_columns])), filters).reset_index(drop=True)
        if union_requested:
            if identity_frame is None:
                identity_frame = frame[entity_columns].copy()
                union_mask = np.zeros(len(frame), dtype=bool)
                if "canonicalPaId" in frame:
                    canonical_ids = frame["canonicalPaId"].astype(str).copy()
            elif len(frame) != len(identity_frame):
                raise Stage3TreatmentError("TREATMENT_ROW_RECONCILIATION_FAILED", "Batched profile scans returned different development row counts.")
            elif canonical_ids is not None and not frame["canonicalPaId"].astype(str).equals(canonical_ids):
                raise Stage3TreatmentError("TREATMENT_ROW_RECONCILIATION_FAILED", "Batched profile scans returned a different canonical PA order.")
        group_union = np.zeros(len(frame), dtype=bool)
        for meta in group:
            variable = str(meta["name"])
            profile = _calculate_outlier_profile(frame, variable)
            _cache_put(_outlier_profile_key(authority, variable, filters), profile, profile=True)
            if union_requested:
                active = (union_spec or {}).get(variable)
                if active is not None and not bool(active.get("included", True)):
                    continue
                active_method = str((active or {}).get("method") or union_method or DEFAULT_OUTLIER_METHOD)
                if active_method == "NO_STATISTICAL_DETECTION":
                    continue
                method_result = profile["methods"].get(active_method)
                if method_result is None:
                    continue
                lower = (active or {}).get("lowerThreshold", method_result["lowerThreshold"])
                upper = (active or {}).get("upperThreshold", method_result["upperThreshold"])
                low, high, mask = _outlier_masks(
                    frame[variable], lower, upper
                )
                del low, high
                group_union |= mask.to_numpy(dtype=bool)
        if union_requested and union_mask is not None:
            union_mask |= group_union
    if not union_requested or union_mask is None or identity_frame is None:
        return None
    mask_series = pd.Series(union_mask, index=identity_frame.index)
    result = {"affectedRows": int(union_mask.sum()), **_entity_counts(identity_frame, mask_series)}
    _cache_put(union_key, result, profile=True)
    return result


def _outlier_profile_all_methods(
    authority: eda._Authority,
    meta: Mapping[str, Any],
    filters: Mapping[str, Any],
) -> dict[str, Any]:
    variable = str(meta["name"])
    key = _outlier_profile_key(authority, variable, filters)
    cached = _cache_get(key, profile=True)
    if cached is not None:
        return cached
    with _profile_key_lock(key):
        cached = _cache_get(key, profile=True)
        if cached is not None:
            return cached
        _prime_outlier_profiles(authority, [meta], filters)
        result = _cache_get(key, profile=True)
        if result is None:
            raise Stage3TreatmentError("OUTLIER_PROFILE_UNAVAILABLE", f"Unable to profile {variable}.")
        return result


def _eligible_detection_methods(variable: str) -> list[str]:
    methods = list(OUTLIER_DETECTION_METHODS[:-1])
    if variable in _GOVERNED_DOMAIN_BOUNDS:
        methods.append("DOMAIN_BOUNDS")
    return methods


def _effective_outlier_method(
    variable: str,
    requested_method: str,
    *,
    explicit_override: bool,
) -> tuple[str, bool]:
    """Resolve a heterogeneous global detection control for one variable."""
    requested = str(requested_method).upper()
    if requested not in OUTLIER_DETECTION_METHODS:
        raise Stage3TreatmentError(
            "OUTLIER_METHOD_UNSUPPORTED",
            f"Unsupported outlier detection method: {requested}.",
        )
    eligible = _eligible_detection_methods(variable)
    if requested in eligible:
        return requested, False
    if explicit_override:
        raise Stage3TreatmentError(
            "OUTLIER_METHOD_INELIGIBLE",
            f"{requested} is not eligible for {variable}.",
        )
    # Global controls are expressly "where eligible". A variable without a
    # declared physical/mathematical domain remains on the governed default;
    # no synthetic bounds are inferred merely to satisfy the global control.
    return DEFAULT_OUTLIER_METHOD, True


def _custom_outlier_bounds(settings: Mapping[str, Any]) -> tuple[float | None, float | None] | None:
    """Validate an explicit user-authored threshold override.

    Custom bounds are policy inputs, never values inferred from validation or
    final-OOT evidence. Either side may be left open, but at least one bound
    must be present and a two-sided interval must be ordered.
    """
    raw_lower = settings.get("customLowerThreshold")
    raw_upper = settings.get("customUpperThreshold")
    if raw_lower is None and raw_upper is None:
        return None

    def parse(raw: Any, label: str) -> float | None:
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise Stage3TreatmentError("OUTLIER_CUSTOM_THRESHOLD_INVALID", f"{label} must be finite numeric.") from exc
        if not math.isfinite(value):
            raise Stage3TreatmentError("OUTLIER_CUSTOM_THRESHOLD_INVALID", f"{label} must be finite numeric.")
        return value

    lower, upper = parse(raw_lower, "customLowerThreshold"), parse(raw_upper, "customUpperThreshold")
    if lower is not None and upper is not None and lower >= upper:
        raise Stage3TreatmentError(
            "OUTLIER_CUSTOM_THRESHOLD_INVALID",
            "customLowerThreshold must be strictly less than customUpperThreshold.",
        )
    return lower, upper


def _outlier_result_for_bounds(
    authority: eda._Authority,
    variable: str,
    filters: Mapping[str, Any],
    lower: float | None,
    upper: float | None,
) -> dict[str, Any]:
    columns = [
        variable,
        *[
            name
            for name in ("canonicalGameId", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId")
            if name in authority.schema.names
        ],
    ]
    frame = eda._scan(authority, columns, filters)
    low, high, mask = _outlier_masks(frame[variable], lower, upper)
    return {
        "lowerThreshold": lower,
        "upperThreshold": upper,
        "lowerTailCount": int(low.sum()),
        "upperTailCount": int(high.sum()),
        "outlierCount": int(mask.sum()),
        "outlierPercent": eda._percent(int(mask.sum()), len(frame)),
        **_entity_counts(frame, mask),
    }


def _outlier_row(
    authority: eda._Authority,
    meta: Mapping[str, Any],
    filters: Mapping[str, Any],
    method: str,
    treatment: str,
    override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    variable = str(meta["name"])
    explicit_method = bool(
        override is not None
        and "detectionMethod" in override
        and str(override.get("detectionMethod") or "").strip()
    )
    requested_method = str((override or {}).get("detectionMethod") or method).upper()
    selected_method, global_method_fallback = _effective_outlier_method(
        variable,
        requested_method,
        explicit_override=explicit_method,
    )
    selected_treatment = str((override or {}).get("treatment") or treatment).upper()
    if selected_treatment not in OUTLIER_TREATMENTS:
        raise Stage3TreatmentError("OUTLIER_TREATMENT_UNSUPPORTED", f"Unsupported outlier treatment: {selected_treatment}.")
    if (
        selected_method == "NO_STATISTICAL_DETECTION"
        and selected_treatment != "RETAIN"
    ):
        raise Stage3TreatmentError(
            "OUTLIER_TREATMENT_INELIGIBLE",
            "NO_STATISTICAL_DETECTION is compatible only with RETAIN because no detected set exists to transform.",
        )
    profile = _outlier_profile_all_methods(authority, meta, filters)
    custom_bounds = _custom_outlier_bounds(override or {})
    if selected_method == "NO_STATISTICAL_DETECTION" and custom_bounds is not None:
        raise Stage3TreatmentError(
            "OUTLIER_CUSTOM_THRESHOLD_INELIGIBLE",
            "Custom detection thresholds cannot be combined with NO_STATISTICAL_DETECTION.",
        )
    selected = (
        _outlier_result_for_bounds(authority, variable, filters, *custom_bounds)
        if custom_bounds is not None
        else profile["methods"][selected_method]
    )
    statistics = profile["statistics"]
    included = (override or {}).get("included", True)
    if not isinstance(included, bool):
        raise Stage3TreatmentError("OUTLIER_INCLUDE_FLAG_INVALID", "included must be a boolean.")
    treatment_value: Any = (
        "No statistical detector is fitted; semantic/domain validation remains declarative."
        if selected_method == "NO_STATISTICAL_DETECTION"
        else "Original values retained"
    )
    if selected_treatment == "CAP_IQR":
        treatment_value = f"Fold-local IQR fences · preview [{selected['lowerThreshold']}, {selected['upperThreshold']}]"
    elif selected_treatment == "WINSORIZE":
        params = dict((override or {}).get("params") or {})
        if (override or {}).get("winsorLowerPercentile") is not None:
            params["lowerPercentile"] = (override or {}).get("winsorLowerPercentile")
        if (override or {}).get("winsorUpperPercentile") is not None:
            params["upperPercentile"] = (override or {}).get("winsorUpperPercentile")
        lower_pct, upper_pct = float(params.get("lowerPercentile", 1.0)), float(params.get("upperPercentile", 99.0))
        if not 0 <= lower_pct < upper_pct <= 100:
            raise Stage3TreatmentError("WINSORIZATION_BOUNDS_INVALID", "Winsorization percentiles must satisfy 0 <= lower < upper <= 100.")
        treatment_value = f"Fold-local WINSORIZATION · P{lower_pct:g}/P{upper_pct:g}"
    elif selected_treatment in {"CAP_P95", "CAP_P99"}:
        treatment_value = f"Fold-local {selected_treatment} · preview {statistics['p95' if selected_treatment == 'CAP_P95' else 'p99']}"
    elif selected_treatment == "SET_MISSING":
        treatment_value = "Detected outliers become physical missing values; downstream imputation is required."
    elif selected_treatment == "EXCLUDE_ROW":
        treatment_value = "Detected development rows are excluded inside each training fold only."
    if not included:
        treatment_value = "Excluded from preprocessing policy; original values retained."
    return {
        "numberOfOutliers": selected["outlierCount"],
        "variable": variable,
        "label": meta.get("label"),
        "outlierPercent": selected["outlierPercent"],
        "lowerTailCount": selected["lowerTailCount"],
        "upperTailCount": selected["upperTailCount"],
        "dataType": meta.get("dataType"),
        "featureFamily": meta.get("featureFamily"),
        "core": bool(meta.get("core")),
        "selectable": bool(meta.get("selectable")),
        "eligible": True,
        "exclusionReason": None,
        "active": included,
        "role": meta.get("role"),
        "developmentNonmissingN": statistics["count"],
        "missingN": statistics["missingCount"],
        "lowerThreshold": selected["lowerThreshold"],
        "upperThreshold": selected["upperThreshold"],
        "min": statistics["min"],
        "q1": statistics["q1"],
        "median": statistics["median"],
        "q3": statistics["q3"],
        "max": statistics["max"],
        "mean": statistics["mean"],
        "standardDeviation": statistics["std"],
        "selectedDetectionMethod": selected_method,
        "requestedGlobalDetectionMethod": method,
        "globalMethodFallback": global_method_fallback,
        "methodResolution": (
            f"{method} is not eligible for this variable; governed row default {selected_method} applies."
            if global_method_fallback
            else "Explicit variable override" if explicit_method else "Global method applies"
        ),
        "selectedTreatment": selected_treatment,
        "treatmentValueOrBounds": treatment_value,
        "affectedGames": selected["affectedGames"],
        "affectedPlayers": selected["affectedPlayers"],
        "affectedBatters": selected["affectedBatters"],
        "affectedPitchers": selected["affectedPitchers"],
        "status": (
            "EXCLUDED_FROM_POLICY"
            if not included
            else "NOT_STATISTICALLY_EVALUATED"
            if selected_method == "NO_STATISTICAL_DETECTION"
            else "OUTLIERS_FOUND"
            if selected["outlierCount"]
            else "NO_OUTLIERS_FOUND"
        ),
        "override": bool(override),
        "eligibleDetectionMethods": _eligible_detection_methods(variable),
        "eligibleTreatments": (
            ["RETAIN"]
            if selected_method == "NO_STATISTICAL_DETECTION"
            else list(OUTLIER_TREATMENTS)
        ),
        "ineligibleReasons": ({"DOMAIN_BOUNDS": "No registered physical or mathematical bounds."} if variable not in _GOVERNED_DOMAIN_BOUNDS else {}),
        "previewLabel": "DESCRIPTIVE PREVIEW — FOLD-LOCAL VALUES WILL DIFFER",
    }


def _overrides(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = payload.get("overrides") or {}
    if isinstance(raw, list):
        return {
            str(item.get("variable") or ""): item
            for item in raw
            if isinstance(item, Mapping) and str(item.get("variable") or "")
        }
    if isinstance(raw, Mapping):
        return {str(key): value for key, value in raw.items() if isinstance(value, Mapping)}
    raise Stage3TreatmentError("TREATMENT_OVERRIDES_INVALID", "Per-variable overrides must be an object or list.")


def _table_controls(payload: Mapping[str, Any]) -> tuple[int, int, str, str]:
    page = max(1, int(payload.get("page") or 1))
    page_size = max(1, min(int(payload.get("pageSize") or 50), MAX_PAGE_SIZE))
    sort = payload.get("sort") or {}
    if not isinstance(sort, Mapping):
        raise Stage3TreatmentError("TREATMENT_SORT_INVALID", "sort must be an object.")
    field = str(sort.get("field") or "numberOfOutliers")
    direction = str(sort.get("direction") or "desc").lower()
    if direction not in {"asc", "desc"}:
        raise Stage3TreatmentError("TREATMENT_SORT_INVALID", "sort.direction must be asc or desc.")
    return page, page_size, field, direction


def _filter_catalog_rows(rows: list[dict[str, Any]], payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    search = str(payload.get("search") or "").strip().casefold()
    families = {
        str(value)
        for value in (payload.get("families") or payload.get("featureFamilies") or [])
    }
    data_types = {str(value) for value in payload.get("dataTypes") or []}
    core_scope = str(payload.get("coreScope") or "ALL").upper()
    severity = str(payload.get("severity") or "ALL").upper()
    selected = {str(value) for value in payload.get("selectedVariables") or []}
    if len(selected) > MAX_SELECTED_VARIABLES:
        raise Stage3TreatmentError("TREATMENT_SELECTION_TOO_LARGE", f"At most {MAX_SELECTED_VARIABLES} variables may be selected.")
    output = []
    for row in rows:
        if search and search not in f"{row.get('variable', '')} {row.get('label', '')}".casefold():
            continue
        if families and str(row.get("featureFamily")) not in families:
            continue
        if data_types and str(row.get("dataType")) not in data_types:
            continue
        if core_scope == "CORE" and not row.get("core"):
            continue
        if core_scope == "CONTEXTUAL" and row.get("core"):
            continue
        count = int(row.get("numberOfOutliers", row.get("numberOfMissingValues", 0)) or 0)
        percent = float(row.get("outlierPercent", row.get("missingPercent", 0.0)) or 0.0)
        if "numberOfOutliers" in row:
            if severity in {"AFFECTED", "WITH_OUTLIERS"} and not count:
                continue
            if severity == "NONE" and count:
                continue
            if severity == "HIGH" and percent < 10.0:
                continue
            if severity not in {"ALL", "", "AFFECTED", "WITH_OUTLIERS", "NONE", "HIGH"}:
                raise Stage3TreatmentError("TREATMENT_SEVERITY_INVALID", f"Unsupported outlier severity: {severity}.")
        else:
            cold_count = int(row.get("noPriorHistoryCount", 0) or 0) + int(row.get("insufficientHistoryCount", 0) or 0)
            failure_count = int(row.get("sourceUnavailableCount", 0) or 0) + int(row.get("computationFailureCount", 0) or 0)
            if severity in {"AFFECTED", "PHYSICAL_MISSING"} and not count:
                continue
            if severity in {"NONE", "COMPLETE"} and count:
                continue
            if severity == "HIGH" and percent < 10.0:
                continue
            if severity == "COLD_START" and not cold_count:
                continue
            if severity == "SOURCE_FAILURE" and not failure_count:
                continue
            if severity not in {"ALL", "", "AFFECTED", "PHYSICAL_MISSING", "NONE", "COMPLETE", "HIGH", "COLD_START", "SOURCE_FAILURE"}:
                raise Stage3TreatmentError("TREATMENT_SEVERITY_INVALID", f"Unsupported missingness severity: {severity}.")
        # Selection is batch-action state, not a table visibility filter. The
        # browser may select variables across pages without making all other
        # eligible rows disappear from the project-bound diagnostic table.
        output.append(row)
    return output


def _prefilter_meta(
    metas: Sequence[Mapping[str, Any]], payload: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    """Apply metadata-only controls before any Arrow value scan."""
    search = str(payload.get("search") or "").strip().casefold()
    families = {
        str(value)
        for value in (payload.get("families") or payload.get("featureFamilies") or [])
    }
    data_types = {str(value) for value in payload.get("dataTypes") or []}
    core_scope = str(payload.get("coreScope") or "ALL").upper()
    if core_scope not in {"ALL", "", "CORE", "CONTEXTUAL"}:
        raise Stage3TreatmentError("TREATMENT_CORE_SCOPE_INVALID", f"Unsupported coreScope: {core_scope}.")
    result = []
    for meta in metas:
        if search and search not in f"{meta.get('name', '')} {meta.get('label', '')}".casefold():
            continue
        if families and str(meta.get("featureFamily")) not in families:
            continue
        if data_types and str(meta.get("dataType")) not in data_types:
            continue
        if core_scope == "CORE" and not meta.get("core"):
            continue
        if core_scope == "CONTEXTUAL" and meta.get("core"):
            continue
        result.append(meta)
    return result


def _sort_and_page(
    rows: list[dict[str, Any]],
    payload: Mapping[str, Any],
    *,
    default_field: str,
    allowed_fields: frozenset[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    page, page_size, field, direction = _table_controls({**payload, "sort": payload.get("sort") or {"field": default_field, "direction": "desc"}})
    if field not in allowed_fields:
        raise Stage3TreatmentError("TREATMENT_SORT_INVALID", f"Unsupported sort field: {field}.")
    if any(
        value is not None and not isinstance(value, (str, int, float, bool, np.integer, np.floating))
        for value in (row.get(field) for row in rows)
    ):
        raise Stage3TreatmentError(
            "TREATMENT_SORT_INVALID",
            f"Sort field {field} is not scalar for every returned row.",
        )
    def key(row: Mapping[str, Any]) -> tuple[bool, Any, str]:
        value = row.get(field)
        return value is None, value if value is not None else 0, str(row.get("variable") or "")
    rows = sorted(rows, key=key, reverse=direction == "desc")
    start = (page - 1) * page_size
    return rows[start:start + page_size], {
        "page": page,
        "pageSize": page_size,
        "totalRows": len(rows),
        "totalPages": math.ceil(len(rows) / page_size) if rows else 0,
        "sort": {"field": field, "direction": direction},
    }


def _outlier_rows(
    authority: eda._Authority,
    filters: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    method = str(payload.get("method") or payload.get("globalMethod") or DEFAULT_OUTLIER_METHOD).upper()
    treatment = str(payload.get("treatment") or payload.get("globalTreatment") or DEFAULT_OUTLIER_TREATMENT).upper()
    if method not in OUTLIER_DETECTION_METHODS:
        raise Stage3TreatmentError("OUTLIER_METHOD_UNSUPPORTED", f"Unsupported outlier detection method: {method}.")
    if treatment not in OUTLIER_TREATMENTS:
        raise Stage3TreatmentError("OUTLIER_TREATMENT_UNSUPPORTED", f"Unsupported outlier treatment: {treatment}.")
    overrides = _overrides(payload)
    eligible_all = _eligible_outlier_meta(authority, include_advanced=bool(payload.get("includeAdvanced")))
    eligible_names = {str(meta["name"]) for meta in eligible_all}
    invalid_overrides = sorted(set(overrides) - eligible_names)
    if invalid_overrides:
        raise Stage3TreatmentError(
            "OUTLIER_VARIABLE_INELIGIBLE",
            "Outlier overrides cannot target read-only/excluded metadata: " + ", ".join(invalid_overrides),
        )
    metas = _prefilter_meta(eligible_all, payload)
    _prime_outlier_profiles(authority, metas, filters)
    def build(meta: Mapping[str, Any]) -> dict[str, Any]:
        return _outlier_row(authority, meta, filters, method, treatment, overrides.get(str(meta["name"])))
    return [build(meta) for meta in metas]


def _active_outlier_union_spec(
    metas: Sequence[Mapping[str, Any]],
    global_method: str,
    overrides: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    specification: dict[str, dict[str, Any]] = {}
    for meta in metas:
        variable = str(meta["name"])
        override = overrides.get(variable)
        explicit_method = bool(
            override is not None
            and "detectionMethod" in override
            and str(override.get("detectionMethod") or "").strip()
        )
        method, _fallback = _effective_outlier_method(
            variable,
            str((override or {}).get("detectionMethod") or global_method),
            explicit_override=explicit_method,
        )
        custom = _custom_outlier_bounds(override or {})
        specification[variable] = {
            "method": method,
            "included": (override or {}).get("included", True),
            **(
                {"lowerThreshold": custom[0], "upperThreshold": custom[1]}
                if custom is not None
                else {}
            ),
        }
    return specification


def outlier_summary(
    database: Database, project_id: str, *, authority_key: str
) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    _assert_get_authority(authority, authority_key)
    cache_key = "outlier-summary:" + _stable_hash({"authority": authority.review_digest})
    cached = _cache_get(cache_key)
    if cached is not None:
        return {**cached, "cacheStatus": "HIT", "queryDurationMs": 0.0}
    started = time.perf_counter()
    metas = _eligible_outlier_meta(authority, include_advanced=False)
    union = _prime_outlier_profiles(authority, metas, {}, union_method=DEFAULT_OUTLIER_METHOD) or {}
    rows = _outlier_rows(authority, {}, {})
    affected = [row for row in rows if int(row["numberOfOutliers"]) > 0]
    top = max(rows, key=lambda row: int(row["numberOfOutliers"]), default=None)
    policy = _frontend_policy(_policy_state_data(database, authority, "OUTLIER"), kind="OUTLIER")
    data = {
        "status": "ANALYZED" if affected else "NO_OUTLIERS",
        "eligibleVariables": len(rows),
        "variablesWithOutliers": len(affected),
        "totalAffectedRows": int(union.get("affectedRows") or 0),
        "affectedGames": int(union.get("affectedGames") or 0),
        "affectedBatters": int(union.get("affectedBatters") or 0),
        "affectedPitchers": int(union.get("affectedPitchers") or 0),
        "activeDetectionMethod": DEFAULT_OUTLIER_METHOD,
        "activeTreatment": DEFAULT_OUTLIER_TREATMENT,
        "highestAffectedVariable": top["variable"] if top else None,
        "highestAffectedCount": top["numberOfOutliers"] if top else None,
        "highestAffectedPercent": top["outlierPercent"] if top else None,
        "policy": policy,
        "previewOnly": True,
        "finalOotLocked": True,
        "foldLocalIntegrity": "DESCRIPTIVE PREVIEW — FOLD-LOCAL VALUES WILL DIFFER",
        "supportedDetectionMethods": list(OUTLIER_DETECTION_METHODS),
        "supportedTreatments": list(OUTLIER_TREATMENTS),
    }
    response = _envelope(authority, filters={}, rows=eda.DEVELOPMENT_ROWS, aggregation="SERVER_AGGREGATE", data=data, duration_ms=(time.perf_counter() - started) * 1000)
    _cache_put(cache_key, response)
    return response


def outlier_table(database: Database, project_id: str, payload: Any) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    payload, filters = _normalize_request(authority, payload)
    started = time.perf_counter()
    method = str(payload.get("method") or payload.get("globalMethod") or DEFAULT_OUTLIER_METHOD).upper()
    treatment = str(payload.get("treatment") or payload.get("globalTreatment") or DEFAULT_OUTLIER_TREATMENT).upper()
    if method not in OUTLIER_DETECTION_METHODS:
        raise Stage3TreatmentError("OUTLIER_METHOD_UNSUPPORTED", f"Unsupported outlier detection method: {method}.")
    if treatment not in OUTLIER_TREATMENTS:
        raise Stage3TreatmentError("OUTLIER_TREATMENT_UNSUPPORTED", f"Unsupported outlier treatment: {treatment}.")
    overrides = _overrides(payload)
    eligible_all = _eligible_outlier_meta(
        authority,
        include_advanced=bool(payload.get("includeAdvanced")),
    )
    eligible_names = {str(meta["name"]) for meta in eligible_all}
    invalid_overrides = sorted(set(overrides) - eligible_names)
    if invalid_overrides:
        raise Stage3TreatmentError(
            "OUTLIER_VARIABLE_INELIGIBLE",
            "Outlier overrides cannot target read-only/excluded metadata: " + ", ".join(invalid_overrides),
        )
    visible_metas = _prefilter_meta(
        list(_catalog(authority).values()) if payload.get("includeAdvanced") else eligible_all,
        payload,
    )
    metas = [meta for meta in visible_metas if str(meta["name"]) in eligible_names]
    excluded_metas = [meta for meta in visible_metas if str(meta["name"]) not in eligible_names]
    union_spec = _active_outlier_union_spec(metas, method, overrides)
    union = _prime_outlier_profiles(
        authority,
        metas,
        filters,
        union_spec=union_spec,
    ) or {}
    eligible_rows = [
        _outlier_row(
            authority,
            meta,
            filters,
            method,
            treatment,
            overrides.get(str(meta["name"])),
        )
        for meta in metas
    ]
    all_rows = [*eligible_rows, *[_excluded_outlier_row(meta) for meta in excluded_metas]]
    rows = _filter_catalog_rows(all_rows, payload)
    eligible_count = len(metas)
    active_evaluated = [
        row
        for row in eligible_rows
        if row.get("active")
        and row.get("selectedDetectionMethod") != "NO_STATISTICAL_DETECTION"
        and row.get("numberOfOutliers") is not None
    ]
    active_affected = [
        row for row in all_rows
        if row.get("active") and int(row.get("numberOfOutliers") or 0) > 0
    ]
    top = max(active_affected, key=lambda row: int(row["numberOfOutliers"]), default=None)
    statistically_evaluated = bool(active_evaluated)
    active_summary = {
        "status": (
            "NOT_EVALUATED"
            if not statistically_evaluated
            else "ANALYZED"
            if active_affected
            else "NO_OUTLIERS"
        ),
        "eligibleVariables": eligible_count,
        "variablesWithOutliers": len(active_affected) if statistically_evaluated else None,
        "totalAffectedRows": (
            int(union.get("affectedRows") or 0) if statistically_evaluated else None
        ),
        "affectedGames": (
            int(union.get("affectedGames") or 0) if statistically_evaluated else None
        ),
        "affectedBatters": (
            int(union.get("affectedBatters") or 0) if statistically_evaluated else None
        ),
        "affectedPitchers": (
            int(union.get("affectedPitchers") or 0) if statistically_evaluated else None
        ),
        "highestAffectedVariable": top["variable"] if top else None,
        "highestAffectedCount": top["numberOfOutliers"] if top else None,
        "highestAffectedPercent": top["outlierPercent"] if top else None,
        "activeDetectionMethod": method,
        "activeTreatment": treatment,
        "filtersApplied": dict(filters),
        "previewOnly": True,
    }
    paged, pagination = _sort_and_page(
        rows,
        payload,
        default_field="numberOfOutliers",
        allowed_fields=_OUTLIER_SORT_FIELDS,
    )
    represented_rows = (
        int(eligible_rows[0]["developmentNonmissingN"]) + int(eligible_rows[0]["missingN"])
        if eligible_rows
        else _filtered_population_rows(authority, filters)
    )
    return _envelope(
        authority,
        filters=filters,
        rows=represented_rows,
        aggregation="SERVER_AGGREGATE_PAGINATED",
        data={
            "rows": paged,
            "page": pagination["page"],
            "pageSize": pagination["pageSize"],
            "totalRows": pagination["totalRows"],
            "totalPages": pagination["totalPages"],
            "eligibleRows": eligible_count,
            "excludedRows": len(excluded_metas),
            "excludedMetadataRows": len(excluded_metas),
            "activeSummary": active_summary,
            "rawRowExportAllowed": False,
        },
        duration_ms=(time.perf_counter() - started) * 1000,
    )


def _target_composition(frame: pd.DataFrame, mask: pd.Series | None = None) -> list[dict[str, Any]]:
    if "outcome" not in frame:
        return []
    selected = frame if mask is None else frame.loc[mask]
    counts = selected["outcome"].astype(str).value_counts()
    total = int(counts.sum())
    return [
        {
            "value": outcome,
            "count": int(counts.get(outcome, 0)),
            "percent": eda._percent(int(counts.get(outcome, 0)), total),
        }
        for outcome in GOLD_CLASS_ORDER
    ]


def _shared_distribution(
    original: pd.Series,
    transformed: pd.Series,
    *,
    bins: int = 30,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    left = _finite_numeric(original).dropna().to_numpy(dtype=float)
    right = _finite_numeric(transformed).dropna().to_numpy(dtype=float)
    combined = np.concatenate([left, right]) if left.size or right.size else np.array([], dtype=float)
    if combined.size == 0:
        return ({"chartType": "EMPTY", "rows": []}, {"chartType": "EMPTY", "rows": []}, {"shared": True, "binEdges": []})
    unique = np.unique(combined)
    if unique.size <= 12:
        values = sorted(float(value) for value in unique)
        before_counts = Counter(float(value) for value in left)
        after_counts = Counter(float(value) for value in right)
        return (
            {"chartType": "FREQUENCY_BAR", "rows": [{"value": value, "count": int(before_counts[value])} for value in values]},
            {"chartType": "FREQUENCY_BAR", "rows": [{"value": value, "count": int(after_counts[value])} for value in values]},
            {"shared": True, "categories": values},
        )
    count = max(5, min(int(bins), eda.MAX_BINS))
    minimum, maximum = float(np.min(combined)), float(np.max(combined))
    edges = np.linspace(minimum - 0.5, maximum + 0.5, count + 1) if minimum == maximum else np.linspace(minimum, maximum, count + 1)
    left_counts, _ = np.histogram(left, bins=edges)
    right_counts, _ = np.histogram(right, bins=edges)
    def rows(counts: np.ndarray) -> list[dict[str, Any]]:
        return [
            {"binStart": float(edges[index]), "binEnd": float(edges[index + 1]), "count": int(value)}
            for index, value in enumerate(counts)
        ]
    return (
        {"chartType": "HISTOGRAM", "rows": rows(left_counts)},
        {"chartType": "HISTOGRAM", "rows": rows(right_counts)},
        {"shared": True, "binEdges": [float(value) for value in edges], "xMin": float(edges[0]), "xMax": float(edges[-1])},
    )


def _box(values: pd.Series) -> dict[str, Any]:
    stats = _statistics(values)
    if not stats["count"]:
        return {key: None for key in ("min", "q1", "median", "q3", "max")}
    return {key: stats[key] for key in ("min", "q1", "median", "q3", "max")}


def _outlier_detail_data(
    authority: eda._Authority,
    variable: str,
    filters: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    catalog = _catalog(authority)
    meta = catalog.get(variable)
    if not meta or not meta.get("selectable") or meta.get("dataType") != "numeric":
        raise Stage3TreatmentError("OUTLIER_VARIABLE_INELIGIBLE", f"{variable} is not an eligible numeric predictor.")
    explicit_method = any(
        key in payload and str(payload.get(key) or "").strip()
        for key in ("detectionMethod", "method")
    )
    requested_method = str(
        payload.get("detectionMethod")
        or payload.get("method")
        or payload.get("globalMethod")
        or DEFAULT_OUTLIER_METHOD
    ).upper()
    method, global_method_fallback = _effective_outlier_method(
        variable,
        requested_method,
        explicit_override=explicit_method,
    )
    requested_treatment = str(payload.get("treatment") or DEFAULT_OUTLIER_TREATMENT).upper()
    included = payload.get("included", True)
    if not isinstance(included, bool):
        raise Stage3TreatmentError("OUTLIER_INCLUDE_FLAG_INVALID", "included must be a boolean.")
    treatment = requested_treatment if included else "RETAIN"
    if requested_treatment not in OUTLIER_TREATMENTS:
        raise Stage3TreatmentError("OUTLIER_TREATMENT_UNSUPPORTED", f"Unsupported outlier treatment: {requested_treatment}.")
    if method == "NO_STATISTICAL_DETECTION" and treatment != "RETAIN":
        raise Stage3TreatmentError(
            "OUTLIER_TREATMENT_INELIGIBLE",
            "NO_STATISTICAL_DETECTION is compatible only with RETAIN because no detected set exists to transform.",
        )
    requested = [
        variable,
        *[
            name
            for name in ("canonicalGameId", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "outcome")
            if name in authority.schema.names
        ],
    ]
    frame = eda._scan(authority, requested, filters)
    values = _finite_numeric(frame[variable])
    before_stats = _statistics(values)
    lower, upper = _detection_bounds(variable, before_stats, method)
    custom_bounds = _custom_outlier_bounds(payload)
    if method == "NO_STATISTICAL_DETECTION" and custom_bounds is not None:
        raise Stage3TreatmentError(
            "OUTLIER_CUSTOM_THRESHOLD_INELIGIBLE",
            "Custom detection thresholds cannot be combined with NO_STATISTICAL_DETECTION.",
        )
    if custom_bounds is not None:
        lower, upper = custom_bounds
    low, high, detected = _outlier_masks(values, lower, upper)
    params = dict(payload.get("params") or {})
    if payload.get("winsorLowerPercentile") is not None:
        params["lowerPercentile"] = payload.get("winsorLowerPercentile")
    if payload.get("winsorUpperPercentile") is not None:
        params["upperPercentile"] = payload.get("winsorUpperPercentile")
    transformed = values.copy()
    retained_rows = pd.Series(True, index=frame.index)
    cap_low = cap_high = set_missing = excluded = 0
    treatment_lower, treatment_upper = lower, upper
    formula = "x' = x"
    if treatment == "CAP_IQR":
        factor = 3.0 if method == "IQR_3_0" else 1.5
        q1, q3 = float(before_stats["q1"]), float(before_stats["q3"])
        treatment_lower, treatment_upper = q1 - factor * (q3 - q1), q3 + factor * (q3 - q1)
        cap_low = int(transformed.lt(treatment_lower).sum())
        cap_high = int(transformed.gt(treatment_upper).sum())
        transformed = transformed.clip(lower=treatment_lower, upper=treatment_upper)
        formula = f"x' = min(max(x, training-fold Q1 - {factor}×IQR), training-fold Q3 + {factor}×IQR)"
    elif treatment == "WINSORIZE":
        lower_pct = float(params.get("lowerPercentile", 1.0))
        upper_pct = float(params.get("upperPercentile", 99.0))
        if not 0 <= lower_pct < upper_pct <= 100:
            raise Stage3TreatmentError("WINSORIZATION_BOUNDS_INVALID", "Winsorization percentiles must satisfy 0 <= lower < upper <= 100.")
        clean = transformed.dropna()
        treatment_lower = float(clean.quantile(lower_pct / 100.0)) if len(clean) else None
        treatment_upper = float(clean.quantile(upper_pct / 100.0)) if len(clean) else None
        cap_low = int(transformed.lt(treatment_lower).sum()) if treatment_lower is not None else 0
        cap_high = int(transformed.gt(treatment_upper).sum()) if treatment_upper is not None else 0
        transformed = transformed.clip(lower=treatment_lower, upper=treatment_upper)
        formula = f"x' = Winsorize(x, training-fold P{lower_pct:g}, P{upper_pct:g})"
    elif treatment in {"CAP_P95", "CAP_P99"}:
        treatment_lower = None
        treatment_upper = float(before_stats["p95" if treatment == "CAP_P95" else "p99"])
        cap_high = int(transformed.gt(treatment_upper).sum())
        transformed = transformed.clip(upper=treatment_upper)
        formula = f"x' = min(x, training-fold {'P95' if treatment == 'CAP_P95' else 'P99'})"
    elif treatment == "SET_MISSING":
        transformed.loc[detected] = np.nan
        set_missing = int(detected.sum())
        formula = "x' = missing when the training-fold detection rule marks x as an outlier"
    elif treatment == "EXCLUDE_ROW":
        retained_rows = ~detected
        excluded = int(detected.sum())
        transformed = transformed.loc[retained_rows]
        formula = "exclude row inside the applicable training fold when its value breaches the fitted detection rule"
    elif treatment == "FLAG_ONLY":
        formula = "x' = x; add fold-local outlier_indicator = 1 for detected values"
    after_stats = _statistics(transformed)
    after_frame = frame.loc[retained_rows]
    entity = _entity_counts(frame, detected)
    changed = cap_low + cap_high + set_missing + excluded
    unique_count = int(values.dropna().nunique())
    genuinely_continuous = not _looks_binary(variable, meta) and unique_count > 12
    before_preview, edges = _numeric_distribution_preview(
        values,
        force_continuous=genuinely_continuous,
    )
    after_preview, _ = _numeric_distribution_preview(
        transformed,
        edges=edges or None,
        imputed_mask=(detected.loc[transformed.index] if treatment not in {"RETAIN", "FLAG_ONLY", "EXCLUDE_ROW"} else None),
        force_continuous=genuinely_continuous,
    )
    if edges:
        shared_axis = {
            "minimum": edges[0],
            "maximum": edges[-1],
            "binEdges": edges,
            "categories": [],
        }
    else:
        before_categories = {
            str(item["value"]): dict(item) for item in before_preview.get("categories") or []
        }
        after_categories = {
            str(item["value"]): dict(item) for item in after_preview.get("categories") or []
        }
        category_values = sorted(
            set(before_categories) | set(after_categories),
            key=lambda value: float(value),
        )
        empty = lambda value: {"value": value, "count": 0, "percent": 0.0, "imputedCount": 0}
        before_preview["categories"] = [before_categories.get(value, empty(value)) for value in category_values]
        after_preview["categories"] = [after_categories.get(value, empty(value)) for value in category_values]
        shared_axis = {
            "minimum": None,
            "maximum": None,
            "binEdges": [],
            "categories": category_values,
        }
    warning = None
    statistically_evaluated = method != "NO_STATISTICAL_DETECTION"
    detected_count = int(detected.sum()) if statistically_evaluated else None
    reported_entity = (
        entity
        if statistically_evaluated
        else {
            "affectedGames": None,
            "affectedBatters": None,
            "affectedPitchers": None,
            "affectedPlayers": None,
        }
    )
    if not statistically_evaluated:
        warning = (
            "NOT EVALUATED: no statistical detector or exact outlier-count claim is active; "
            "semantic/domain validation remains declarative."
        )
    elif not included:
        warning = "Variable excluded from the preprocessing policy; preview retains original values."
    if treatment == "EXCLUDE_ROW":
        warning = "HIGH RISK: row exclusion can bias the modeling population; target/entity concentrations are descriptive development-only evidence."
    data = {
        "variable": variable,
        "label": meta.get("label"),
        "dataType": meta.get("dataType"),
        "featureFamily": meta.get("featureFamily"),
        "detectionMethod": method,
        "requestedGlobalDetectionMethod": payload.get("globalMethod"),
        "globalMethodFallback": global_method_fallback,
        "methodResolution": (
            f"{requested_method} is not eligible for this variable; governed row default {method} applies."
            if global_method_fallback
            else "Explicit variable method" if explicit_method else "Global/default method applies"
        ),
        "treatment": treatment,
        "evaluationStatus": (
            "ANALYZED" if statistically_evaluated else "NOT_EVALUATED"
        ),
        "previewLabel": "DESCRIPTIVE PREVIEW — FOLD-LOCAL VALUES WILL DIFFER",
        "thresholds": {
            "lower": lower,
            "upper": upper,
            "formula": "Explicit user-authored policy threshold(s)" if custom_bounds is not None else {
                "IQR_1_5": "Q1 - 1.5×IQR / Q3 + 1.5×IQR",
                "IQR_3_0": "Q1 - 3.0×IQR / Q3 + 3.0×IQR",
                "P95_UPPER": "value > P95",
                "P99_UPPER": "value > P99",
                "P05_P95": "value < P05 or value > P95",
                "P01_P99": "value < P01 or value > P99",
                "DOMAIN_BOUNDS": "value outside registered mathematical/physical bounds",
                "NO_STATISTICAL_DETECTION": "no statistical threshold is fitted; validate registered semantic/domain rules",
            }[method],
            "fittingRule": (
                "Detection parameters are fit on each chronological training fold only."
                if statistically_evaluated
                else "No statistical detection parameters are fit."
            ),
        },
        "treatmentBounds": {"lower": treatment_lower, "upper": treatment_upper},
        "detected": {
            "lowerCount": int(low.sum()) if statistically_evaluated else None,
            "upperCount": int(high.sum()) if statistically_evaluated else None,
            "totalCount": detected_count,
            "percent": (
                eda._percent(detected_count, len(frame))
                if detected_count is not None
                else None
            ),
            **reported_entity,
        },
        "before": before_preview,
        "after": after_preview,
        "sharedAxis": shared_axis,
        "effect": {
            "originalCount": len(frame),
            "postTreatmentCount": int(retained_rows.sum()),
            "changedRows": changed,
            "unchangedRows": len(frame) - changed,
            "cappedLow": cap_low,
            "cappedHigh": cap_high,
            "excluded": excluded,
            "setMissing": set_missing,
            "populationLossPercent": eda._percent(excluded, len(frame)),
            "original": {key: before_stats.get(key) for key in ("min", "max", "mean", "median", "std")},
            "transformed": {key: after_stats.get(key) for key in ("min", "max", "mean", "median", "std")},
            **{
                key: reported_entity[key]
                for key in ("affectedGames", "affectedBatters", "affectedPitchers")
            },
            "targetCompositionBefore": _target_composition(frame),
            "targetCompositionAfter": _target_composition(after_frame),
            "formula": formula,
        },
        "eligibleDetectionMethods": _eligible_detection_methods(variable),
        "eligibleTreatments": (
            ["RETAIN"]
            if not statistically_evaluated
            else list(OUTLIER_TREATMENTS)
        ),
        "warning": warning,
        "previewOnly": True,
        "pendingMissingValueRequirement": treatment == "SET_MISSING",
        "activeSummary": {
            "status": (
                "NOT_EVALUATED"
                if not statistically_evaluated
                else "ANALYZED"
                if detected_count
                else "NO_OUTLIERS"
            ),
            "eligibleVariables": 1,
            "variablesWithOutliers": (
                1 if detected_count else 0
            ) if statistically_evaluated else None,
            "totalAffectedRows": detected_count,
            "affectedGames": reported_entity["affectedGames"],
            "affectedBatters": reported_entity["affectedBatters"],
            "affectedPitchers": reported_entity["affectedPitchers"],
            "highestAffectedVariable": variable if detected_count else None,
            "highestAffectedCount": detected_count if detected_count else None,
            "highestAffectedPercent": (
                eda._percent(detected_count, len(frame)) if detected_count else None
            ),
            "activeDetectionMethod": method,
            "activeTreatment": treatment,
            "filtersApplied": dict(filters),
            "previewOnly": True,
        },
    }
    return data, len(frame)


def _outlier_detail_or_preview(
    database: Database, project_id: str, payload: Any, *, operation: str
) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    if not isinstance(payload, Mapping):
        raise Stage3TreatmentError("TREATMENT_REQUEST_INVALID", "The request body must be an object.")
    variable = str(payload.get("variable") or "").strip()
    payload, filters = _normalize_request(authority, payload, [variable] if variable else [])
    if not variable:
        raise Stage3TreatmentError("OUTLIER_VARIABLE_REQUIRED", "An exact variable is required.")
    key = f"outlier-{operation}:" + _stable_hash(
        {
            "project": project_id,
            "authority": authority.review_digest,
            "variable": variable,
            "filters": filters,
            "method": payload.get("detectionMethod") or payload.get("method"),
            "globalMethod": payload.get("globalMethod"),
            "treatment": payload.get("treatment"),
            "params": payload.get("params") or {},
            "winsorLowerPercentile": payload.get("winsorLowerPercentile"),
            "winsorUpperPercentile": payload.get("winsorUpperPercentile"),
            "customLowerThreshold": payload.get("customLowerThreshold"),
            "customUpperThreshold": payload.get("customUpperThreshold"),
            "included": payload.get("included", True),
            "policyVersion": payload.get("policyVersion"),
        }
    )
    cached = _cache_get(key)
    if cached is not None:
        return {**cached, "cacheStatus": "HIT", "queryDurationMs": 0.0}
    started = time.perf_counter()
    data, rows = _outlier_detail_data(authority, variable, filters, payload)
    response = _envelope(
        authority,
        filters=filters,
        rows=rows,
        aggregation="SERVER_AGGREGATE_TREATMENT_PREVIEW",
        data=data,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
    _cache_put(key, response)
    return response


def outlier_detail(database: Database, project_id: str, payload: Any) -> dict[str, Any]:
    return _outlier_detail_or_preview(database, project_id, payload, operation="detail")


def outlier_preview(database: Database, project_id: str, payload: Any) -> dict[str, Any]:
    return _outlier_detail_or_preview(database, project_id, payload, operation="preview")


def _paired_indicator(variable: str, catalog: Mapping[str, Mapping[str, Any]]) -> str | None:
    explicit = {
        "batter_last100_contact_rate": "batter_last100_whiff_missing",
        "batter_last100_whiff_rate": "batter_last100_whiff_missing",
        "pitcher_last250_whiff_rate": "pitcher_last250_whiff_missing",
        "pitcher_last250_avg_fastball_velocity": "pitcher_last250_velocity_missing",
    }
    if variable in explicit and explicit[variable] in catalog:
        return explicit[variable]
    for candidate in (f"{variable}_missing", f"{variable}_missing_indicator"):
        if candidate in catalog:
            return candidate
    return None


def _missing_profile_key(authority: eda._Authority, variable: str, filters: Mapping[str, Any]) -> str:
    return "missing-profile:" + _stable_hash(
        {"authority": authority.review_digest, "variable": variable, "filters": dict(filters)}
    )


def _missing_reason_masks(
    frame: pd.DataFrame,
    variable: str,
    missing: pd.Series,
    reason_memberships: Mapping[str, Mapping[str, pd.Series]] | None = None,
) -> dict[str, pd.Series]:
    masks = {
        reason: pd.Series(False, index=frame.index)
        for reason in (
            "NO_PRIOR_HISTORY", "INSUFFICIENT_HISTORY", "SOURCE_MISSING",
            "IDENTITY_FAILURE", "COMPUTATION_FAILURE", "SOURCE_NOT_AVAILABLE_FOR_ERA",
        )
    }
    def flag(column: str) -> pd.Series:
        if column not in frame:
            return pd.Series(False, index=frame.index)
        return pd.to_numeric(frame[column], errors="coerce").fillna(0).gt(0)
    reason_column = (
        "batting_missing_reason" if variable.startswith("batting_")
        else "fielding_missing_reason" if variable.startswith("fielding_")
        else None
    )
    if reason_column and reason_column in frame:
        memberships = (reason_memberships or {}).get(reason_column)
        if memberships is None:
            normalized = (
                frame[reason_column]
                .fillna("")
                .astype(str)
                .str.upper()
                .str.replace("|", ",", regex=False)
                .str.replace(" ", "", regex=False)
            )
            dummies = normalized.str.get_dummies(sep=",")
            memberships = {
                reason: (
                    dummies[reason].astype(bool)
                    if reason in dummies
                    else pd.Series(False, index=frame.index)
                )
                for reason in masks
            }
        matched = pd.Series(False, index=frame.index)
        for reason in masks:
            reason_mask = missing & memberships[reason]
            masks[reason] = reason_mask
            matched |= reason_mask
        masks["SOURCE_MISSING"] |= missing & ~matched
    elif variable.startswith("batter_"):
        no_prior = missing & flag("batter_prior_missing")
        insufficient = missing & ~no_prior & flag("batter_last100_insufficient")
        masks["NO_PRIOR_HISTORY"] = no_prior
        masks["INSUFFICIENT_HISTORY"] = insufficient
        masks["SOURCE_MISSING"] = missing & ~no_prior & ~insufficient
    elif variable.startswith("pitcher_"):
        no_prior = missing & flag("pitcher_prior_missing")
        insufficient = missing & ~no_prior & flag("pitcher_last250_insufficient")
        masks["NO_PRIOR_HISTORY"] = no_prior
        masks["INSUFFICIENT_HISTORY"] = insufficient
        masks["SOURCE_MISSING"] = missing & ~no_prior & ~insufficient
    else:
        masks["SOURCE_MISSING"] = missing.copy()
    return masks


def _prime_missing_profiles(
    authority: eda._Authority,
    metas: Sequence[Mapping[str, Any]],
    filters: Mapping[str, Any],
    *,
    union_reasons: bool = False,
) -> dict[str, int] | None:
    union_key = "missing-union:" + _stable_hash(
        {"authority": authority.review_digest, "filters": dict(filters)}
    )
    if union_reasons:
        cached_union = _cache_get(union_key, profile=True)
        if cached_union is not None:
            return {key: int(value) for key, value in cached_union.items()}
    catalog = _catalog(authority)
    scan_metas: list[Mapping[str, Any]] = []
    for meta in metas:
        variable = str(meta["name"])
        key = _missing_profile_key(authority, variable, filters)
        if not filters and float(meta.get("missingPercent") or 0.0) == 0.0:
            if _cache_get(key, profile=True) is None:
                _cache_put(key, {
                    "rows": eda.DEVELOPMENT_ROWS, "missingCount": 0, "missingPercent": 0.0,
                    "observedCount": eda.DEVELOPMENT_ROWS, "reasonCounts": {},
                    "previewMean": None, "previewMedian": None, "previewMode": None,
                    "pairedIndicator": _paired_indicator(variable, catalog), "affectedGames": 0,
                    "affectedBatters": 0, "affectedPitchers": 0, "affectedPlayers": 0,
                }, profile=True)
            continue
        if union_reasons or _cache_get(key, profile=True) is None:
            scan_metas.append(meta)
    if not scan_metas:
        return None
    support_columns = [
        name for name in (
            "canonicalPaId", "canonicalGameId", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId",
            "batter_prior_missing", "batter_last100_insufficient", "pitcher_prior_missing",
            "pitcher_last250_insufficient", "batting_missing_reason", "fielding_missing_reason",
        ) if name in authority.schema.names
    ]
    physical_union: np.ndarray | None = None
    source_union: np.ndarray | None = None
    computation_union: np.ndarray | None = None
    identity_frame: pd.DataFrame | None = None
    canonical_ids: pd.Series | None = None
    reason_memberships: dict[str, dict[str, pd.Series]] | None = None
    for offset in range(0, len(scan_metas), PROFILE_COLUMN_BATCH_SIZE):
        group = scan_metas[offset:offset + PROFILE_COLUMN_BATCH_SIZE]
        variables = [str(meta["name"]) for meta in group]
        frame = eda._scan(authority, list(dict.fromkeys([*variables, *support_columns])), filters).reset_index(drop=True)
        if identity_frame is None:
            if union_reasons:
                identity_frame = frame[support_columns].copy()
                physical_union = np.zeros(len(frame), dtype=bool)
                source_union = np.zeros(len(frame), dtype=bool)
                computation_union = np.zeros(len(frame), dtype=bool)
            else:
                identity_frame = frame[[name for name in support_columns if name in frame]].copy()
            if "canonicalPaId" in frame:
                canonical_ids = frame["canonicalPaId"].astype(str).copy()
            reason_memberships = {}
            for reason_column in ("batting_missing_reason", "fielding_missing_reason"):
                if reason_column not in frame:
                    continue
                normalized = (
                    frame[reason_column]
                    .fillna("")
                    .astype(str)
                    .str.upper()
                    .str.replace("|", ",", regex=False)
                    .str.replace(" ", "", regex=False)
                )
                dummies = normalized.str.get_dummies(sep=",")
                reason_memberships[reason_column] = {
                    reason: (
                        dummies[reason].astype(bool)
                        if reason in dummies
                        else pd.Series(False, index=frame.index)
                    )
                    for reason in (
                        "NO_PRIOR_HISTORY", "INSUFFICIENT_HISTORY", "SOURCE_MISSING",
                        "IDENTITY_FAILURE", "COMPUTATION_FAILURE", "SOURCE_NOT_AVAILABLE_FOR_ERA",
                    )
                }
        elif len(frame) != len(identity_frame):
            raise Stage3TreatmentError("TREATMENT_ROW_RECONCILIATION_FAILED", "Batched missingness scans returned different row counts.")
        elif canonical_ids is not None and not frame["canonicalPaId"].astype(str).equals(canonical_ids):
            raise Stage3TreatmentError("TREATMENT_ROW_RECONCILIATION_FAILED", "Batched missingness scans returned a different canonical PA order.")
        for meta in group:
            variable = str(meta["name"])
            series = frame[variable]
            missing = series.isna()
            if meta.get("dataType") == "numeric":
                missing |= ~np.isfinite(pd.to_numeric(series, errors="coerce").astype(float))
                observed = _finite_numeric(series).dropna()
                preview_mean = float(observed.mean()) if len(observed) else None
                preview_median = float(observed.median()) if len(observed) else None
                preview_mode = None
                if _looks_binary(variable, meta) and len(observed):
                    modes = observed.mode()
                    preview_mode = float(modes.iloc[0]) if len(modes) else None
            else:
                observed = series.dropna()
                modes = observed.mode()
                preview_mean = preview_median = None
                preview_mode = (
                    modes.iloc[0].item()
                    if len(modes) and hasattr(modes.iloc[0], "item")
                    else modes.iloc[0] if len(modes) else None
                )
            reason_masks = _missing_reason_masks(
                frame,
                variable,
                missing,
                reason_memberships=reason_memberships,
            )
            reasons = {reason: int(mask.sum()) for reason, mask in reason_masks.items() if int(mask.sum())}
            result = {
                "rows": len(frame), "missingCount": int(missing.sum()),
                "missingPercent": eda._percent(int(missing.sum()), len(frame)),
                "observedCount": int(len(frame) - missing.sum()), "reasonCounts": reasons,
                "previewMean": preview_mean, "previewMedian": preview_median,
                "previewMode": preview_mode,
                "pairedIndicator": _paired_indicator(variable, catalog), **_entity_counts(frame, missing),
            }
            _cache_put(_missing_profile_key(authority, variable, filters), result, profile=True)
            if union_reasons and physical_union is not None and source_union is not None and computation_union is not None:
                physical_union |= missing.to_numpy(dtype=bool)
                source_mask = reason_masks["SOURCE_MISSING"] | reason_masks["SOURCE_NOT_AVAILABLE_FOR_ERA"]
                source_union |= source_mask.to_numpy(dtype=bool)
                computation_union |= reason_masks["COMPUTATION_FAILURE"].to_numpy(dtype=bool)
    if not union_reasons or identity_frame is None or physical_union is None or source_union is None or computation_union is None:
        return None
    cold = np.zeros(len(identity_frame), dtype=bool)
    for column in ("batter_prior_missing", "batter_last100_insufficient", "pitcher_prior_missing", "pitcher_last250_insufficient"):
        if column in identity_frame:
            cold |= pd.to_numeric(identity_frame[column], errors="coerce").fillna(0).gt(0).to_numpy(dtype=bool)
    result = {
        "rowsWithPhysicalMissing": int(physical_union.sum()),
        "sourceUnavailableRows": int(source_union.sum()),
        "computationFailureRows": int(computation_union.sum()),
        "coldStartRows": int(cold.sum()),
    }
    _cache_put(union_key, result, profile=True)
    return result


def _imputation_eligibility(meta: Mapping[str, Any], variable: str) -> tuple[list[str], dict[str, str]]:
    role = str(meta.get("role") or "")
    data_type = str(meta.get("dataType") or "")
    reasons: dict[str, str] = {}
    if role == "SIMULATION_GENERATED_STATE":
        reasons = {
            method: "Simulation-generated state must be supplied by the simulator at forecast time, not imputed from historical target-game state."
            for method in IMPUTATION_METHODS
            if method != "RETAIN_WITH_INDICATOR"
        }
        return ["RETAIN_WITH_INDICATOR"], reasons
    if role in {"IDENTIFIER", "GROUPING", "TARGET", "TIME", "RESEARCH_ONLY", "EXCLUDED"}:
        return [], {method: f"{role} fields are not eligible for predictor imputation." for method in IMPUTATION_METHODS}
    if _looks_binary(variable, meta):
        methods = ["RETAIN_WITH_INDICATOR", "MODE", "CONSTANT", "PREDICTED", "DROP_VARIABLE", "EXCLUDE_ROW"]
        if variable in _GOVERNED_PRIOR_FEATURES:
            methods.insert(4, "GOVERNED_PRIOR")
        reasons["MEAN"] = "Mean imputation is not permitted for binary predictors."
        reasons["MEDIAN"] = "Median imputation is not permitted for binary predictors."
        reasons["UNKNOWN_CATEGORY"] = "UNKNOWN_CATEGORY is valid only for nominal categorical predictors."
    elif data_type == "numeric":
        methods = ["RETAIN_WITH_INDICATOR", "MEAN", "MEDIAN", "CONSTANT", "PREDICTED", "DROP_VARIABLE", "EXCLUDE_ROW"]
        if variable in _GOVERNED_PRIOR_FEATURES:
            methods.insert(5, "GOVERNED_PRIOR")
        reasons["MODE"] = "Mode imputation requires binary, categorical, low-cardinality, or explicitly governed ordinal semantics."
        reasons["UNKNOWN_CATEGORY"] = "UNKNOWN_CATEGORY is valid only for categorical predictors."
    else:
        methods = ["RETAIN_WITH_INDICATOR", "MODE", "CONSTANT", "PREDICTED", "UNKNOWN_CATEGORY", "DROP_VARIABLE", "EXCLUDE_ROW"]
        reasons["MEAN"] = "Mean imputation is valid only for continuous numeric predictors."
        reasons["MEDIAN"] = "Median imputation requires a numeric or governed ordinal predictor."
        if variable in _GOVERNED_PRIOR_FEATURES:
            methods.insert(4, "GOVERNED_PRIOR")
        else:
            reasons["GOVERNED_PRIOR"] = "No registered categorical hierarchy or league-prior contract exists for this variable."
    if variable not in _GOVERNED_PRIOR_FEATURES:
        reasons["GOVERNED_PRIOR"] = "No registered hierarchical or league-prior contract exists for this variable."
    return methods, reasons


def _default_imputation(meta: Mapping[str, Any]) -> str:
    if meta.get("role") == "SIMULATION_GENERATED_STATE":
        return "RETAIN_WITH_INDICATOR"
    if _looks_binary(str(meta.get("name") or ""), meta):
        return "MODE"
    return "MEDIAN" if meta.get("dataType") == "numeric" else "MODE"


def _effective_imputation_method(
    meta: Mapping[str, Any],
    variable: str,
    requested_method: str,
    *,
    explicit_override: bool,
) -> tuple[str, bool]:
    """Resolve a heterogeneous global imputation control for one variable."""
    requested = str(requested_method).upper()
    if requested in _IMPUTATION_DEFAULT_ALIASES:
        return _default_imputation(meta), False
    if requested not in IMPUTATION_METHODS:
        raise Stage3TreatmentError(
            "IMPUTATION_METHOD_UNSUPPORTED",
            f"Unsupported imputation method: {requested}.",
        )
    eligible, reasons = _imputation_eligibility(meta, variable)
    if requested in eligible:
        return requested, False
    if explicit_override:
        raise Stage3TreatmentError(
            "IMPUTATION_METHOD_INELIGIBLE",
            reasons.get(requested) or f"{requested} is not eligible for {variable}.",
        )
    # MEDIAN/MODE global controls are "where eligible". Mixed-type and
    # simulator-supplied rows retain their registered type-aware default.
    fallback = _default_imputation(meta)
    if fallback not in eligible:
        raise Stage3TreatmentError(
            "IMPUTATION_METHOD_INELIGIBLE",
            f"No governed default imputation method is eligible for {variable}.",
        )
    return fallback, True


def _missing_profile(
    authority: eda._Authority,
    meta: Mapping[str, Any],
    filters: Mapping[str, Any],
) -> dict[str, Any]:
    variable = str(meta["name"])
    key = _missing_profile_key(authority, variable, filters)
    cached = _cache_get(key, profile=True)
    if cached is not None:
        return cached
    with _profile_key_lock(key):
        cached = _cache_get(key, profile=True)
        if cached is not None:
            return cached
        _prime_missing_profiles(authority, [meta], filters)
        result = _cache_get(key, profile=True)
        if result is None:
            raise Stage3TreatmentError("MISSING_PROFILE_UNAVAILABLE", f"Unable to profile {variable}.")
        return result


def _missing_row(
    database: Database,
    authority: eda._Authority,
    meta: Mapping[str, Any],
    filters: Mapping[str, Any],
    global_method: str,
    override: Mapping[str, Any] | None,
) -> dict[str, Any]:
    variable = str(meta["name"])
    profile = _missing_profile(authority, meta, filters)
    eligible, reasons = _imputation_eligibility(meta, variable)
    explicit_method = bool(
        override is not None
        and "method" in override
        and str(override.get("method") or "").strip()
    )
    requested_method = str((override or {}).get("method") or global_method).upper()
    selected, global_method_fallback = _effective_imputation_method(
        meta,
        variable,
        requested_method,
        explicit_override=explicit_method,
    )
    count = int(profile["missingCount"])
    reason_counts = dict(profile["reasonCounts"])
    ordinary_reasons = {
        "NO_PRIOR_HISTORY": int(reason_counts.get("NO_PRIOR_HISTORY", 0)),
        "INSUFFICIENT_HISTORY": int(reason_counts.get("INSUFFICIENT_HISTORY", 0)),
        "SOURCE_UNAVAILABLE": int(reason_counts.get("SOURCE_NOT_AVAILABLE_FOR_ERA", 0) + reason_counts.get("SOURCE_MISSING", 0)),
        "COMPUTATION_FAILURE": int(reason_counts.get("COMPUTATION_FAILURE", 0)),
        "IDENTITY_FAILURE": int(reason_counts.get("IDENTITY_FAILURE", 0)),
    }
    primary = max(ordinary_reasons, key=ordinary_reasons.get) if count and any(ordinary_reasons.values()) else "NONE"
    policy_label = {
        "MEAN": f"Development preview mean = {profile.get('previewMean')!r}; fold-local training mean is authoritative",
        "MEDIAN": f"Development preview median = {profile.get('previewMedian')!r}; fold-local training median is authoritative",
        "MODE": f"Development preview mode = {profile.get('previewMode')!r}; fold-local training mode is authoritative",
        "CONSTANT": f"Constant · {(override or {}).get('constantValue', 'value required')}",
        "PREDICTED": "Row-specific · preview not run",
        "GOVERNED_PRIOR": "Training-fold governed hierarchy / league prior",
        "UNKNOWN_CATEGORY": "Explicit UNKNOWN category",
        "RETAIN_WITH_INDICATOR": "Missing retained · indicator preserved",
        "DROP_VARIABLE": "Variable removed from candidate contract",
        "EXCLUDE_ROW": "Missing rows excluded inside fold",
    }[selected]
    if selected == "PREDICTED":
        predictors, excluded = _predictor_contract(
            authority,
            variable,
            override or {},
            require_explicit_nonempty=True,
        )
        seed = _canonical_predicted_preview_seed(override or {})
        specification = _predicted_preview_specification(variable, predictors, excluded, filters, seed)
        completed = _latest_predicted_preview(database, authority, variable, specification)
        policy_label = "Row-specific · OOF preview available" if completed else "Row-specific · preview not run"
    return {
        "numberOfMissingValues": count,
        "variable": variable,
        "missingPercent": profile["missingPercent"],
        "developmentN": profile["rows"],
        "observedN": profile["observedCount"],
        "dataType": meta.get("dataType"),
        "featureFamily": meta.get("featureFamily"),
        "core": bool(meta.get("core")),
        "selectable": bool(meta.get("selectable")),
        "eligible": True,
        "exclusionReason": None,
        "primaryReason": primary,
        "noPriorHistoryCount": ordinary_reasons["NO_PRIOR_HISTORY"],
        "insufficientHistoryCount": ordinary_reasons["INSUFFICIENT_HISTORY"],
        "sourceUnavailableCount": ordinary_reasons["SOURCE_UNAVAILABLE"],
        "computationFailureCount": ordinary_reasons["COMPUTATION_FAILURE"],
        "identityFailureCount": ordinary_reasons["IDENTITY_FAILURE"],
        "pairedMissingnessIndicator": profile["pairedIndicator"],
        "canonicalPredictedPreviewSeed": PREDICTED_PREVIEW_SEED,
        "governedPriorAvailable": variable in _GOVERNED_PRIOR_FEATURES,
        "governedPriorUnavailableReason": (
            None
            if variable in _GOVERNED_PRIOR_FEATURES
            else "No registered hierarchical or league-prior authority exists for this variable."
        ),
        "selectedImputationMethod": selected,
        "requestedGlobalImputationMethod": global_method,
        "globalMethodFallback": global_method_fallback,
        "methodResolution": (
            f"{global_method} is not eligible for this variable; governed type-aware default {selected} applies."
            if global_method_fallback
            else "Explicit variable override" if explicit_method else "Global/type-aware method applies"
        ),
        "imputedValueOrPolicy": policy_label,
        "descriptivePreviewValue": {
            "MEAN": profile.get("previewMean"),
            "MEDIAN": profile.get("previewMedian"),
            "MODE": profile.get("previewMode"),
        }.get(selected),
        "descriptivePreviewOnly": True,
        "eligibleMethods": eligible,
        "ineligibleMethodReasons": reasons,
        "affectedGames": profile["affectedGames"],
        "affectedBatters": profile["affectedBatters"],
        "affectedPitchers": profile["affectedPitchers"],
        "status": "PHYSICAL_MISSINGNESS" if count else "COMPLETE",
        "override": bool(override),
        "coldStartStatus": "COLD START — LEGITIMATE STATE" if ordinary_reasons["NO_PRIOR_HISTORY"] or ordinary_reasons["INSUFFICIENT_HISTORY"] else None,
        "previewLabel": "DESCRIPTIVE PREVIEW VALUES — FINAL VALUES ARE FIT INSIDE EACH CHRONOLOGICAL TRAINING FOLD",
    }


def _missing_rows(
    database: Database,
    authority: eda._Authority,
    filters: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    global_method = str(payload.get("globalMethod") or DEFAULT_IMPUTATION_METHOD).upper()
    if global_method in _IMPUTATION_DEFAULT_ALIASES:
        global_method = DEFAULT_IMPUTATION_METHOD
    if global_method not in _IMPUTATION_DEFAULT_ALIASES and global_method not in IMPUTATION_METHODS:
        raise Stage3TreatmentError("IMPUTATION_METHOD_UNSUPPORTED", f"Unsupported global imputation method: {global_method}.")
    overrides = _overrides(payload)
    metas = _prefilter_meta(_eligible_missing_meta(authority), payload)
    _prime_missing_profiles(authority, metas, filters)
    def build(meta: Mapping[str, Any]) -> dict[str, Any]:
        return _missing_row(database, authority, meta, filters, global_method, overrides.get(str(meta["name"])))
    return [build(meta) for meta in metas]


def _rows_with_any_missing(
    authority: eda._Authority,
    variables: Sequence[str],
    filters: Mapping[str, Any],
) -> int:
    if not variables:
        return 0
    requested = list(dict.fromkeys([*variables, *eda._filter_columns(filters)]))
    dataset = eda.pads.dataset([str(path) for path in authority.paths], format="parquet")
    count = 0
    for batch in dataset.scanner(
        columns=requested,
        filter=eda._arrow_filter(authority, filters),
        use_threads=True,
        batch_size=16_384,
    ).to_batches():
        frame = batch.to_pandas(split_blocks=True)
        mask = frame[list(variables)].isna().any(axis=1)
        count += int(mask.sum())
    return count


def _policy_state_data(database: Database, authority: eda._Authority, kind: str) -> dict[str, Any]:
    try:
        state = Stage3TreatmentRepository(database).policy_state(
            authority.project_id, kind, authority.review_digest
        )
    except Exception as exc:
        # A pre-migration running process must be represented honestly rather
        # than as a false zero/adopted state.
        if "no such table" in str(exc).lower():
            return {"latestDraft": None, "adopted": None, "history": [], "persistenceStatus": "MIGRATION_REQUIRED"}
        raise
    return {**state, "persistenceStatus": "READY"}


def _frontend_policy(state: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    # A successor draft must be the editable/current surface even when an
    # earlier version remains adopted. The adopted version stays visible in
    # immutable history until the successor is explicitly adopted.
    selected = state.get("latestDraft") or state.get("adopted")
    policy = dict((selected or {}).get("policy") or {})
    history = []
    adopted_id = (state.get("adopted") or {}).get("policyId")
    for item in state.get("history") or []:
        status = item.get("status")
        if status == "ADOPTED" and item.get("policyId") != adopted_id:
            status = "SUPERSEDED"
        item_policy = dict(item.get("policy") or {})
        history.append({
            "policyVersion": item.get("policyVersion"),
            "status": status,
            "createdAt": item.get("createdAt"),
            "adoptedAt": item.get("createdAt") if item.get("status") == "ADOPTED" else None,
            "user": item.get("createdByUserId"),
            "checksum": item.get("checksum"),
            "notes": item.get("notes") or "",
            "globalMethod": item.get("globalMethod"),
            "globalTreatment": item_policy.get("globalTreatment"),
            "variableCount": len(item_policy.get("overrides") or {}),
            "policyId": item.get("policyId"),
        })
    return {
        "kind": "outliers" if kind == "OUTLIER" else "missing",
        "status": "DRAFT" if state.get("latestDraft") else "ADOPTED" if state.get("adopted") else "NO_TREATMENT_ADOPTED",
        "policyVersion": selected.get("policyVersion") if selected else None,
        "policyId": selected.get("policyId") if selected else None,
        "checksum": selected.get("checksum") if selected else None,
        "globalMethod": selected.get("globalMethod") if selected else (DEFAULT_OUTLIER_METHOD if kind == "OUTLIER" else DEFAULT_IMPUTATION_METHOD),
        "globalTreatment": policy.get("globalTreatment") if kind == "OUTLIER" else None,
        "overrides": policy.get("overrides") or {},
        "coldStartDefault": (
            policy.get("coldStartDefault") or "RETAIN_WITH_INDICATOR"
            if kind == "IMPUTATION"
            else None
        ),
        "governedPriorAvailable": bool(_GOVERNED_PRIOR_FEATURES) if kind == "IMPUTATION" else None,
        "governedPriorEligibleVariables": (
            sorted(_GOVERNED_PRIOR_FEATURES) if kind == "IMPUTATION" else []
        ),
        "canonicalPredictedPreviewSeed": (
            PREDICTED_PREVIEW_SEED if kind == "IMPUTATION" else None
        ),
        "notes": selected.get("notes") if selected else "",
        "versions": history,
        "fittingRule": "FIT EVERY LEARNED PARAMETER ON THE TRAINING ROWS OF EACH CHRONOLOGICAL FOLD ONLY",
        "developmentCutoff": eda.DEVELOPMENT_END,
        "finalOotIdentity": f"{eda.EXPECTED_FINAL_OOT[0]} through {eda.EXPECTED_FINAL_OOT[1]} · {eda.FINAL_OOT_ROWS:,} rows · LOCKED",
        "persistenceStatus": state.get("persistenceStatus", "READY"),
    }


def missing_summary(
    database: Database, project_id: str, *, authority_key: str
) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    _assert_get_authority(authority, authority_key)
    cache_key = "missing-summary:" + _stable_hash({"authority": authority.review_digest})
    cached = _cache_get(cache_key)
    if cached is not None:
        return {**cached, "cacheStatus": "HIT", "queryDurationMs": 0.0}
    started = time.perf_counter()
    metas = _eligible_missing_meta(authority)
    union = _prime_missing_profiles(authority, metas, {}, union_reasons=True) or {}
    rows = _missing_rows(database, authority, {}, {})
    affected = [row for row in rows if int(row["numberOfMissingValues"]) > 0]
    top = max(rows, key=lambda row: int(row["numberOfMissingValues"]), default=None)
    physical_cells = sum(int(row["numberOfMissingValues"]) for row in rows)
    policy = _frontend_policy(_policy_state_data(database, authority, "IMPUTATION"), kind="IMPUTATION")
    data = {
        "status": "ANALYZED" if affected else "NO_MISSING_VALUES",
        "eligiblePredictors": len(rows),
        "predictorsWithPhysicalMissing": len(affected),
        "rowsWithPhysicalMissing": int(union.get("rowsWithPhysicalMissing") or 0),
        "macroPredictorCellMissingPercent": eda._percent(physical_cells, eda.DEVELOPMENT_ROWS * len(rows)),
        "largestMissingPercent": top["missingPercent"] if top else None,
        "largestMissingVariable": top["variable"] if top else None,
        "coldStartRows": int(union.get("coldStartRows") or 0),
        "sourceUnavailableRows": int(union.get("sourceUnavailableRows") or 0),
        "computationFailureRows": int(union.get("computationFailureRows") or 0),
        "missingnessIndicatorCount": sum(1 for meta in _eligible_missing_meta(authority) if meta.get("role") == "MISSINGNESS_INDICATOR"),
        "activeGlobalMethod": DEFAULT_IMPUTATION_METHOD,
        "canonicalPredictedPreviewSeed": PREDICTED_PREVIEW_SEED,
        "policy": policy,
    }
    response = _envelope(authority, filters={}, rows=eda.DEVELOPMENT_ROWS, aggregation="SERVER_AGGREGATE", data=data, duration_ms=(time.perf_counter() - started) * 1000)
    _cache_put(cache_key, response)
    return response


def missing_table(database: Database, project_id: str, payload: Any) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    payload, filters = _normalize_request(authority, payload)
    started = time.perf_counter()
    eligible_all = _eligible_missing_meta(authority)
    eligible_names = {str(meta["name"]) for meta in eligible_all}
    overrides = _overrides(payload)
    invalid_overrides = sorted(set(overrides) - eligible_names)
    if invalid_overrides:
        raise Stage3TreatmentError(
            "MISSING_VARIABLE_INELIGIBLE",
            "Imputation overrides cannot target read-only/excluded metadata: " + ", ".join(invalid_overrides),
        )
    eligible_rows = _missing_rows(database, authority, filters, payload)
    excluded_metas: list[Mapping[str, Any]] = []
    if payload.get("includeAdvanced"):
        visible_metas = _prefilter_meta(list(_catalog(authority).values()), payload)
        excluded_metas = [meta for meta in visible_metas if str(meta["name"]) not in eligible_names]
    all_rows = [*eligible_rows, *[_excluded_missing_row(meta) for meta in excluded_metas]]
    eligible_count = len(eligible_rows)
    rows = _filter_catalog_rows(all_rows, payload)
    paged, pagination = _sort_and_page(
        rows,
        payload,
        default_field="numberOfMissingValues",
        allowed_fields=_MISSING_SORT_FIELDS,
    )
    represented_rows = int(eligible_rows[0]["developmentN"]) if eligible_rows else _filtered_population_rows(authority, filters)
    active_global_method = str(payload.get("globalMethod") or DEFAULT_IMPUTATION_METHOD).upper()
    if active_global_method in _IMPUTATION_DEFAULT_ALIASES:
        active_global_method = DEFAULT_IMPUTATION_METHOD
    data = {
        "rows": paged,
        "page": pagination["page"],
        "pageSize": pagination["pageSize"],
        "totalRows": pagination["totalRows"],
        "totalPages": pagination["totalPages"],
        "eligibleRows": eligible_count,
        "excludedRows": len(excluded_metas),
        "excludedMetadataRows": len(excluded_metas),
        "activeGlobalMethod": active_global_method,
        "canonicalPredictedPreviewSeed": PREDICTED_PREVIEW_SEED,
    }
    return _envelope(
        authority,
        filters=filters,
        rows=represented_rows,
        aggregation="SERVER_AGGREGATE_PAGINATED",
        data=data,
        duration_ms=(time.perf_counter() - started) * 1000,
    )


def _numeric_distribution_preview(
    values: pd.Series,
    *,
    edges: Sequence[float] | None = None,
    imputed_mask: pd.Series | None = None,
    force_continuous: bool = False,
) -> tuple[dict[str, Any], list[float]]:
    numeric = _finite_numeric(values)
    observed = numeric.dropna().to_numpy(dtype=float)
    missing = int(numeric.isna().sum())
    unique = np.unique(observed)
    if not force_continuous and unique.size <= 2:
        categories = []
        for value in unique:
            mask = numeric.eq(value)
            categories.append({
                "value": str(float(value)),
                "count": int(mask.sum()),
                "percent": eda._percent(int(mask.sum()), len(numeric)),
                "imputedCount": int((mask & imputed_mask).sum()) if imputed_mask is not None else 0,
            })
        return {
            "kind": "BINARY",
            "categories": categories,
            "missingCount": missing,
            "observedCount": int(len(observed)),
            "box": _box(numeric),
        }, []
    if not force_continuous and unique.size <= 12:
        categories = []
        for value in sorted(float(item) for item in unique):
            mask = numeric.eq(value)
            categories.append({
                "value": str(value),
                "count": int(mask.sum()),
                "percent": eda._percent(int(mask.sum()), len(numeric)),
                "imputedCount": int((mask & imputed_mask).sum()) if imputed_mask is not None else 0,
            })
        return {
            "kind": "LOW_CARDINALITY",
            "categories": categories,
            "missingCount": missing,
            "observedCount": int(len(observed)),
            "box": _box(numeric),
        }, []
    if edges is None:
        if not observed.size:
            bin_edges = np.array([], dtype=float)
        elif float(np.min(observed)) == float(np.max(observed)):
            bin_edges = np.linspace(float(observed[0]) - 0.5, float(observed[0]) + 0.5, 31)
        else:
            bin_edges = np.linspace(float(np.min(observed)), float(np.max(observed)), 31)
    else:
        bin_edges = np.asarray(edges, dtype=float)
    counts, _ = np.histogram(observed, bins=bin_edges) if bin_edges.size else (np.array([], dtype=int), bin_edges)
    imputed_counts = np.zeros_like(counts)
    if imputed_mask is not None and bin_edges.size:
        imputed = numeric.loc[imputed_mask].dropna().to_numpy(dtype=float)
        imputed_counts, _ = np.histogram(imputed, bins=bin_edges)
    histogram = [
        {
            "binStart": float(bin_edges[index]),
            "binEnd": float(bin_edges[index + 1]),
            "count": int(count),
            "percent": eda._percent(int(count), len(numeric)),
            "imputedCount": int(imputed_counts[index]),
        }
        for index, count in enumerate(counts)
    ]
    return {
        "kind": "CONTINUOUS",
        "histogram": histogram,
        "box": _box(numeric),
        "missingCount": missing,
        "observedCount": int(len(observed)),
    }, [float(value) for value in bin_edges]


def _categorical_distribution_preview(
    values: pd.Series,
    *,
    imputed_mask: pd.Series | None = None,
) -> dict[str, Any]:
    missing = values.isna()
    normalized = values.astype(object).where(~missing, "MISSING").astype(str)
    counts = normalized.value_counts().head(eda.MAX_CATEGORIES)
    categories = []
    for value, count in counts.items():
        mask = normalized.eq(value)
        categories.append({
            "value": str(value),
            "count": int(count),
            "percent": eda._percent(int(count), len(values)),
            "imputedCount": int((mask & imputed_mask).sum()) if imputed_mask is not None else 0,
        })
    return {
        "kind": "CATEGORICAL",
        "categories": categories,
        "missingCount": int(missing.sum()),
        "observedCount": int((~missing).sum()),
    }


def _available_imputer_predictors(
    authority: eda._Authority,
    variable: str,
) -> list[str]:
    """Return the complete, deterministic cutoff-safe predictor catalog.

    The selection limit applies to one preview fit, not to the catalog shown
    to the reviewer.  Returning the full eligible catalog prevents a current
    selection from accidentally shrinking the set of variables that can be
    selected next.
    """
    return [
        name
        for name, meta in _catalog(authority).items()
        if name != variable
        and meta.get("selectable")
        and meta.get("dataType") == "numeric"
        and meta.get("role") in {"PREGAME_FEATURE", "MISSINGNESS_INDICATOR"}
        and not str(name).endswith("_missing")
    ]


def _canonical_predicted_preview_seed(payload: Mapping[str, Any]) -> int:
    raw = payload.get("seed")
    if raw is None or raw == "":
        return PREDICTED_PREVIEW_SEED
    try:
        supplied = int(raw)
    except (TypeError, ValueError) as exc:
        raise Stage3TreatmentError(
            "PREDICTED_PREVIEW_SEED_INVALID",
            f"Predicted-imputation seed must be {PREDICTED_PREVIEW_SEED}.",
        ) from exc
    if supplied != PREDICTED_PREVIEW_SEED:
        raise Stage3TreatmentError(
            "PREDICTED_PREVIEW_SEED_MISMATCH",
            f"Predicted-imputation seed is frozen at {PREDICTED_PREVIEW_SEED}.",
            status_code=409,
        )
    return PREDICTED_PREVIEW_SEED


def _predictor_contract(
    authority: eda._Authority,
    variable: str,
    payload: Mapping[str, Any],
    *,
    require_explicit_nonempty: bool = False,
) -> tuple[list[str], list[dict[str, str]]]:
    catalog = _catalog(authority)
    predictor_set_supplied = "predictorSet" in payload
    requested = [str(value) for value in payload.get("predictorSet") or []]
    if require_explicit_nonempty and predictor_set_supplied and not requested:
        raise Stage3TreatmentError(
            "PREDICTED_PREVIEW_NO_PREDICTORS",
            "An explicitly selected predicted-imputation predictor set cannot be empty.",
        )
    if len(requested) > MAX_PREVIEW_PREDICTORS:
        raise Stage3TreatmentError(
            "PREDICTED_PREVIEW_PREDICTOR_LIMIT",
            f"At most {MAX_PREVIEW_PREDICTORS} imputer predictors may be selected.",
        )
    excluded = [
        {"field": "outcome", "reason": "Governed PA target is always excluded from imputer predictors."},
        {"field": variable, "reason": "The variable being imputed cannot predict itself."},
        {"field": "canonicalGameId", "reason": "Game identity is used only to enforce grouped folds."},
        {"field": "canonicalPaId", "reason": "Row identity is used only for deterministic sampling/audit."},
        {"field": "final OOT", "reason": "2026-08-14 through 2026-08-27 is never opened by this preview."},
    ]
    if requested:
        invalid = [
            name for name in requested
            if name not in catalog
            or not catalog[name].get("selectable")
            or catalog[name].get("role") not in {"PREGAME_FEATURE", "MISSINGNESS_INDICATOR"}
            or name in {variable, "outcome"}
        ]
        if invalid:
            raise Stage3TreatmentError(
                "PREDICTED_PREVIEW_PREDICTOR_INELIGIBLE",
                f"Ineligible predicted-imputer fields: {', '.join(sorted(invalid))}.",
            )
        predictors = requested
    else:
        # A bounded, deterministic default uses only accepted numeric pregame
        # predictors.  Missing predictor cells are resolved by the fold-local
        # median stage inside the preprocessing-preview pipeline.
        predictors = _available_imputer_predictors(authority, variable)[:MAX_PREVIEW_PREDICTORS]
    if not predictors:
        raise Stage3TreatmentError(
            "PREDICTED_PREVIEW_NO_PREDICTORS",
            "No cutoff-safe predictors are available for a predicted-imputation preview.",
        )
    return predictors, excluded


def _predicted_preview_specification(
    variable: str,
    predictors: Sequence[str],
    excluded: Sequence[Mapping[str, str]],
    filters: Mapping[str, Any],
    seed: int,
) -> dict[str, Any]:
    return {
        "contractVersion": "STAGE3_PREDICTED_IMPUTATION_PREVIEW_V1",
        "variable": variable,
        "predictors": list(predictors),
        "excludedFields": [dict(item) for item in excluded],
        "filters": dict(filters),
        "design": "THREE EXPANDING, DATE-ATOMIC, GAME-GROUPED DEVELOPMENT-ONLY FOLDS",
        "trainingRowCapPerFold": PREDICTED_PREVIEW_MAX_TRAIN,
        "evaluationRowCapPerFold": PREDICTED_PREVIEW_MAX_EVAL,
        "seed": int(seed),
        "estimator": "HIST_GRADIENT_BOOSTING_V1",
        "hyperparameters": {
            "maxIter": 50,
            "maxLeafNodes": 15,
            "learningRate": 0.08,
            "l2Regularization": 1.0,
        },
        "targetOutcomeExcluded": True,
        "sameGameLeakageProhibited": True,
        "finalOotExcluded": True,
        "registeredAsOutcomeModel": False,
    }


def _assert_no_predicted_imputation_cycles(
    dependencies: Mapping[str, Sequence[str]],
) -> None:
    """Reject direct or transitive cycles among predicted imputers."""
    nodes = set(dependencies)
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(variable: str) -> None:
        if variable in visited:
            return
        if variable in visiting:
            start = visiting.index(variable)
            cycle = [*visiting[start:], variable]
            raise Stage3TreatmentError(
                "PREDICTED_IMPUTATION_DEPENDENCY_CYCLE",
                "Circular predicted-imputation dependency is prohibited: " + " -> ".join(cycle),
                status_code=409,
            )
        visiting.append(variable)
        for predictor in dependencies.get(variable, ()):
            if predictor in nodes:
                visit(predictor)
        visiting.pop()
        visited.add(variable)

    for variable in sorted(nodes):
        visit(variable)


def _latest_predicted_preview(
    database: Database,
    authority: eda._Authority,
    variable: str,
    specification: Mapping[str, Any],
) -> dict[str, Any] | None:
    try:
        stored = Stage3TreatmentRepository(database).latest_preview(
            authority.project_id, variable, authority.review_digest, specification
        )
    except Exception as exc:
        if "no such table" in str(exc).lower():
            return None
        raise
    if not stored:
        return None
    summary = dict(stored.get("summary") or {})
    return {
        **summary,
        "status": "COMPLETE",
        "artifactChecksum": stored.get("artifactSha256"),
    }


def _missing_detail_data(
    database: Database,
    authority: eda._Authority,
    variable: str,
    filters: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    catalog = _catalog(authority)
    meta = catalog.get(variable)
    if not meta or not meta.get("selectable"):
        raise Stage3TreatmentError("MISSING_VARIABLE_INELIGIBLE", f"{variable} is not an eligible predictor.")
    explicit_method = any(
        key in payload and str(payload.get(key) or "").strip()
        for key in ("imputationMethod", "method")
    )
    requested_method = str(
        payload.get("imputationMethod")
        or payload.get("method")
        or payload.get("globalMethod")
        or DEFAULT_IMPUTATION_METHOD
    ).upper()
    method, global_method_fallback = _effective_imputation_method(
        meta,
        variable,
        requested_method,
        explicit_override=explicit_method,
    )
    eligible, ineligible = _imputation_eligibility(meta, variable)
    columns = [
        variable,
        *[
            name
            for name in (
                "canonicalGameId", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId",
                "batter_prior_missing", "batter_last100_insufficient",
                "pitcher_prior_missing", "pitcher_last250_insufficient",
                "batting_missing_reason", "fielding_missing_reason",
            )
            if name in authority.schema.names
        ],
    ]
    frame = eda._scan(authority, columns, filters)
    original = frame[variable].copy()
    if meta.get("dataType") == "numeric":
        original = _finite_numeric(original)
    missing = original.isna()
    transformed = original.copy()
    imputed = pd.Series(False, index=frame.index)
    fill_value: Any = None
    fill_policy = ""
    formula = "x' = x"
    retained_missing = int(missing.sum())
    fill_count = 0
    domain_violations = 0
    predictor_set, excluded_fields = _predictor_contract(
        authority,
        variable,
        payload,
        require_explicit_nonempty=method == "PREDICTED",
    )
    preview_seed = _canonical_predicted_preview_seed(payload)
    preview_specification = _predicted_preview_specification(
        variable, predictor_set, excluded_fields, filters, preview_seed
    )
    predicted = (
        _latest_predicted_preview(database, authority, variable, preview_specification)
        if method == "PREDICTED"
        else None
    )
    if method == "MEAN":
        fill_value = float(original.dropna().mean()) if int((~missing).sum()) else None
        transformed.loc[missing] = fill_value
        imputed = missing & transformed.notna()
        fill_policy = "Training-fold mean"
        formula = "missing x' = mean(x) learned on the corresponding chronological training fold only"
    elif method == "MEDIAN":
        fill_value = float(original.dropna().median()) if int((~missing).sum()) else None
        transformed.loc[missing] = fill_value
        imputed = missing & transformed.notna()
        fill_policy = "Training-fold median"
        formula = "missing x' = median(x) learned on the corresponding chronological training fold only"
    elif method == "MODE":
        modes = original.dropna().mode()
        fill_value = modes.iloc[0].item() if len(modes) and hasattr(modes.iloc[0], "item") else modes.iloc[0] if len(modes) else None
        transformed.loc[missing] = fill_value
        imputed = missing & transformed.notna()
        fill_policy = "Training-fold mode"
        formula = "missing x' = deterministic mode learned on the corresponding chronological training fold only"
    elif method == "CONSTANT":
        raw = payload.get("constantValue")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            raise Stage3TreatmentError("IMPUTATION_CONSTANT_REQUIRED", "A nonempty constant value is required.")
        if meta.get("dataType") == "numeric":
            try:
                fill_value = float(raw)
            except (TypeError, ValueError) as exc:
                raise Stage3TreatmentError("IMPUTATION_CONSTANT_INVALID", "The constant must be finite numeric for this variable.") from exc
            if not math.isfinite(fill_value):
                raise Stage3TreatmentError("IMPUTATION_CONSTANT_INVALID", "The constant must be finite numeric for this variable.")
            if _looks_binary(variable, meta) and fill_value not in {0.0, 1.0}:
                raise Stage3TreatmentError("IMPUTATION_CONSTANT_OUT_OF_DOMAIN", "A binary constant must be exactly 0 or 1.")
            bounds = _GOVERNED_DOMAIN_BOUNDS.get(variable)
            if bounds and not bounds[0] <= fill_value <= bounds[1]:
                raise Stage3TreatmentError("IMPUTATION_CONSTANT_OUT_OF_DOMAIN", f"The constant must remain within the governed domain {bounds}.")
        else:
            fill_value = str(raw)
        transformed.loc[missing] = fill_value
        imputed = missing
        fill_policy = "Explicit validated constant"
        formula = "missing x' = the explicit policy constant"
    elif method == "UNKNOWN_CATEGORY":
        fill_value = "UNKNOWN"
        transformed.loc[missing] = fill_value
        imputed = missing
        fill_policy = "Explicit UNKNOWN category"
        formula = "missing x' = explicit UNKNOWN category"
    elif method == "GOVERNED_PRIOR":
        fill_value = float(original.dropna().mean()) if meta.get("dataType") == "numeric" and int((~missing).sum()) else None
        transformed.loc[missing] = fill_value
        imputed = missing & transformed.notna()
        fill_policy = "Descriptive league-prior preview; hierarchy is refit from cutoff-valid training history"
        formula = "missing x' = the most specific available governed prior learned inside the training fold"
    elif method == "PREDICTED":
        fill_policy = "Row-specific · OOF preview available" if predicted else "Row-specific · preview not run"
        formula = "one deterministic imputer per variable and training fold; target, same-game labels, and final OOT are excluded"
    elif method == "DROP_VARIABLE":
        fill_policy = "Variable removed from the candidate feature contract"
        formula = "variable is excluded; no row values are rewritten"
    elif method == "EXCLUDE_ROW":
        transformed = transformed.loc[~missing]
        fill_policy = "Rows missing this variable are excluded inside the applicable fold"
        formula = "exclude row inside the fold when this variable is physically missing"
    else:
        fill_policy = "Physical missingness retained; paired indicator preserved"
        formula = "x' = x; preserve/create the paired missingness indicator"
    fill_count = int(imputed.sum()) if method != "PREDICTED" else int((predicted or {}).get("missingRowsImputed") or 0)
    retained_missing = max(0, int(missing.sum()) - fill_count)
    if variable in _GOVERNED_DOMAIN_BOUNDS and meta.get("dataType") == "numeric":
        lower, upper = _GOVERNED_DOMAIN_BOUNDS[variable]
        finite = _finite_numeric(transformed)
        domain_violations = int((finite.lt(lower) | finite.gt(upper)).sum())
    if meta.get("dataType") == "numeric":
        before, edges = _numeric_distribution_preview(original)
        after, _ = _numeric_distribution_preview(transformed, edges=edges or None, imputed_mask=imputed)
        original_stats = _statistics(original)
        transformed_stats = _statistics(transformed)
        original_categories: list[dict[str, Any]] = before.get("categories") or []
        transformed_categories: list[dict[str, Any]] = after.get("categories") or []
        axis = {"minimum": edges[0] if edges else original_stats["min"], "maximum": edges[-1] if edges else original_stats["max"], "binEdges": edges}
    else:
        before = _categorical_distribution_preview(original)
        after = _categorical_distribution_preview(transformed, imputed_mask=imputed)
        original_stats = transformed_stats = {"mean": None, "median": None, "std": None}
        original_categories = before.get("categories") or []
        transformed_categories = after.get("categories") or []
        axis = {"minimum": None, "maximum": None, "binEdges": []}
    if method == "PREDICTED" and predicted and predicted.get("after"):
        # A completed preview persists only bounded aggregate evidence. Merge
        # its cross-fitted row-specific predictions with observed development
        # values for an honest combined after chart; no raw rows are stored or
        # returned.
        before = dict(predicted.get("observedDistribution") or before)
        after = dict(predicted["after"])
        axis = dict(predicted.get("sharedAxis") or axis)
        aggregate_effect = dict(predicted.get("aggregateEffect") or {})
        original_stats = {
            **original_stats,
            **dict(aggregate_effect.get("original") or {}),
        }
        transformed_stats = {
            **transformed_stats,
            **dict(aggregate_effect.get("combined") or {}),
        }
        original_categories = before.get("categories") or []
        transformed_categories = after.get("categories") or []
        domain_violations = int(predicted.get("domainBoundViolations") or 0)
    reasons = eda._reason_counts(frame, variable, missing)
    entity = _entity_counts(frame, missing)
    data = {
        "variable": variable,
        "dataType": meta.get("dataType"),
        "featureFamily": meta.get("featureFamily"),
        "method": method,
        "requestedGlobalImputationMethod": payload.get("globalMethod"),
        "globalMethodFallback": global_method_fallback,
        "methodResolution": (
            f"{requested_method} is not eligible for this variable; governed type-aware default {method} applies."
            if global_method_fallback
            else "Explicit variable method" if explicit_method else "Global/type-aware method applies"
        ),
        "fillValue": fill_value,
        "fillPolicy": fill_policy,
        "before": before,
        "after": after,
        "sharedAxis": axis,
        "pairedIndicator": _paired_indicator(variable, catalog),
        "canonicalPredictedPreviewSeed": PREDICTED_PREVIEW_SEED,
        "governedPriorAvailable": variable in _GOVERNED_PRIOR_FEATURES,
        "governedPriorUnavailableReason": (
            None
            if variable in _GOVERNED_PRIOR_FEATURES
            else "No registered hierarchical or league-prior authority exists for this variable."
        ),
        "coldStartHandling": "COLD START — LEGITIMATE STATE; preserve reason/indicator and fit the selected rule inside each training fold.",
        "sourceFailureHandling": "SOURCE/COMPUTATION FAILURE remains separately reason-coded and reviewable; it is never silently treated as cold start.",
        "availablePredictors": _available_imputer_predictors(authority, variable),
        "eligiblePredictors": predictor_set,
        "excludedPredictorFields": excluded_fields,
        "predictedPreview": predicted,
        "imputedDistribution": (
            predicted.get("imputedDistribution") if predicted else None
        ),
        "eligibleMethods": eligible,
        "ineligibleMethodReasons": ineligible,
        "effect": {
            "missingCount": int(missing.sum()),
            "observedCount": int((~missing).sum()),
            "fillCount": fill_count,
            "retainedMissingCount": retained_missing,
            "domainViolations": domain_violations,
            **{key: entity[key] for key in ("affectedGames", "affectedBatters", "affectedPitchers")},
            "original": {key: original_stats.get(key) for key in ("mean", "median", "std")},
            "transformed": {key: transformed_stats.get(key) for key in ("mean", "median", "std")},
            "originalCategories": original_categories,
            "transformedCategories": transformed_categories,
            "reasonCounts": reasons,
            "formula": formula,
            "fittingRule": "DESCRIPTIVE PREVIEW VALUES — FINAL VALUES ARE FIT INSIDE EACH CHRONOLOGICAL TRAINING FOLD",
        },
    }
    return data, len(frame)


def _missing_detail_or_preview(
    database: Database, project_id: str, payload: Any, *, operation: str
) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    if not isinstance(payload, Mapping):
        raise Stage3TreatmentError("TREATMENT_REQUEST_INVALID", "The request body must be an object.")
    variable = str(payload.get("variable") or "").strip()
    payload, filters = _normalize_request(authority, payload, [variable] if variable else [])
    if not variable:
        raise Stage3TreatmentError("MISSING_VARIABLE_REQUIRED", "An exact variable is required.")
    key = f"missing-{operation}:" + _stable_hash(
        {
            "project": project_id,
            "authority": authority.review_digest,
            "variable": variable,
            "filters": filters,
            "method": payload.get("imputationMethod") or payload.get("method"),
            "globalMethod": payload.get("globalMethod"),
            "constantValue": payload.get("constantValue"),
            "predictorSet": payload.get("predictorSet") or [],
            "policyVersion": payload.get("policyVersion"),
        }
    )
    cached = _cache_get(key)
    if cached is not None:
        return {**cached, "cacheStatus": "HIT", "queryDurationMs": 0.0}
    started = time.perf_counter()
    data, rows = _missing_detail_data(database, authority, variable, filters, payload)
    response = _envelope(
        authority,
        filters=filters,
        rows=rows,
        aggregation="SERVER_AGGREGATE_IMPUTATION_PREVIEW",
        data=data,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
    _cache_put(key, response)
    return response


def missing_detail(database: Database, project_id: str, payload: Any) -> dict[str, Any]:
    return _missing_detail_or_preview(database, project_id, payload, operation="detail")


def missing_preview(database: Database, project_id: str, payload: Any) -> dict[str, Any]:
    return _missing_detail_or_preview(database, project_id, payload, operation="preview")


def _bounded_indices(frame: pd.DataFrame, mask: pd.Series, limit: int, seed: int) -> pd.Index:
    indexes = frame.index[mask]
    if len(indexes) <= limit:
        return indexes
    identity = (
        frame.loc[indexes, "canonicalPaId"].astype(str)
        if "canonicalPaId" in frame
        else pd.Series(indexes.astype(str), index=indexes)
    )
    hashes = pd.util.hash_pandas_object(identity + f":{seed}", index=False)
    return hashes.nsmallest(limit).index


def _predicted_distribution(values: Sequence[Any], *, numeric: bool) -> list[dict[str, Any]]:
    if not values:
        return []
    if numeric:
        array = np.asarray(values, dtype=float)
        if float(np.min(array)) == float(np.max(array)):
            edges = np.linspace(float(array[0]) - 0.5, float(array[0]) + 0.5, 21)
        else:
            edges = np.linspace(float(np.min(array)), float(np.max(array)), 21)
        counts, _ = np.histogram(array, bins=edges)
        return [
            {
                "binStart": float(edges[index]),
                "binEnd": float(edges[index + 1]),
                "count": int(count),
                "percent": eda._percent(int(count), len(array)),
                "imputedCount": int(count),
            }
            for index, count in enumerate(counts)
        ]
    counts = pd.Series(values, dtype=object).astype(str).value_counts()
    return [
        {"value": str(value), "count": int(count), "percent": eda._percent(int(count), len(values)), "imputedCount": int(count)}
        for value, count in counts.items()
    ]


def predicted_imputation_preview(
    database: Database,
    project_id: str,
    payload: Any,
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    if not isinstance(payload, Mapping):
        raise Stage3TreatmentError("TREATMENT_REQUEST_INVALID", "The request body must be an object.")
    variable = str(payload.get("variable") or "").strip()
    payload, filters = _normalize_request(authority, payload, [variable] if variable else [])
    if not variable:
        raise Stage3TreatmentError("MISSING_VARIABLE_REQUIRED", "An exact variable is required.")
    if filters.get("outcomes"):
        raise Stage3TreatmentError(
            "TARGET_DERIVED_TREATMENT_PROHIBITED",
            "Predicted-imputation previews cannot filter or condition on the governed outcome target.",
        )
    catalog = _catalog(authority)
    meta = catalog.get(variable)
    if not meta or not meta.get("selectable") or meta.get("role") == "SIMULATION_GENERATED_STATE":
        raise Stage3TreatmentError("PREDICTED_PREVIEW_VARIABLE_INELIGIBLE", f"{variable} is not eligible for predicted imputation.")
    predictors, excluded = _predictor_contract(
        authority,
        variable,
        payload,
        require_explicit_nonempty=True,
    )
    nonnumeric = [name for name in predictors if catalog[name].get("dataType") != "numeric"]
    if nonnumeric:
        raise Stage3TreatmentError(
            "PREDICTED_PREVIEW_PREDICTOR_INELIGIBLE",
            "The bounded V1 predicted-imputation preview accepts numeric cutoff-safe predictors only: " + ", ".join(nonnumeric),
        )
    seed = _canonical_predicted_preview_seed(payload)
    specification = _predicted_preview_specification(variable, predictors, excluded, filters, seed)
    repository = Stage3TreatmentRepository(database)
    repository.record_preview_request(
        project_id=project_id,
        variable=variable,
        authority_review_digest=authority.review_digest,
        actor_user_id=actor_user_id,
        specification=specification,
    )
    started = time.perf_counter()
    columns = list(dict.fromkeys([variable, *predictors, "game_date", "canonicalGameId", "canonicalPaId"]))
    columns = [name for name in columns if name in authority.schema.names]
    frame = eda._scan(authority, columns, filters)
    frame["game_date"] = frame["game_date"].astype(str)
    unique_dates = np.asarray(sorted(frame["game_date"].dropna().unique()))
    if len(unique_dates) < 8:
        raise Stage3TreatmentError(
            "PREDICTED_PREVIEW_TEMPORAL_EVIDENCE_INSUFFICIENT",
            "At least eight distinct development dates are required for the chronological preview.",
        )
    boundaries = [0, len(unique_dates) // 4, len(unique_dates) // 2, (3 * len(unique_dates)) // 4, len(unique_dates)]
    y = frame[variable]
    numeric_target = meta.get("dataType") == "numeric"
    if numeric_target:
        y = _finite_numeric(y)
    else:
        y = y.astype(object).where(y.notna(), None)
    X = frame[predictors].apply(pd.to_numeric, errors="coerce")
    oof_truth: list[Any] = []
    oof_predictions: list[Any] = []
    probability_rows: list[np.ndarray] = []
    probability_labels: list[list[str]] = []
    missing_predictions: list[Any] = []
    fold_rows = []
    fits = 0
    domain_clipped_predictions = 0
    bounds = _GOVERNED_DOMAIN_BOUNDS.get(variable)
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline

    for fold_index in range(1, 4):
        validation_dates = unique_dates[boundaries[fold_index]:boundaries[fold_index + 1]]
        if not len(validation_dates):
            continue
        validation_start, validation_end = str(validation_dates[0]), str(validation_dates[-1])
        train_mask = frame["game_date"].lt(validation_start) & y.notna()
        validation_mask = frame["game_date"].isin(validation_dates)
        eval_mask = validation_mask & y.notna()
        missing_mask = validation_mask & y.isna()
        train_index = _bounded_indices(frame, train_mask, PREDICTED_PREVIEW_MAX_TRAIN, seed + fold_index)
        eval_index = _bounded_indices(frame, eval_mask, PREDICTED_PREVIEW_MAX_EVAL, seed + 100 + fold_index)
        missing_index = frame.index[missing_mask]
        if len(train_index) < 20 or len(eval_index) == 0:
            continue
        estimator: Any
        if numeric_target:
            estimator = HistGradientBoostingRegressor(
                loss="squared_error",
                max_iter=50,
                max_leaf_nodes=15,
                learning_rate=0.08,
                l2_regularization=1.0,
                random_state=seed,
            )
        else:
            if pd.Series(y.loc[train_index]).nunique(dropna=True) < 2:
                continue
            estimator = HistGradientBoostingClassifier(
                loss="log_loss",
                max_iter=50,
                max_leaf_nodes=15,
                learning_rate=0.08,
                l2_regularization=1.0,
                random_state=seed,
            )
        pipeline = Pipeline([("fold_median", SimpleImputer(strategy="median")), ("imputer", estimator)])
        pipeline.fit(X.loc[train_index], y.loc[train_index])
        fits += 1
        predicted_eval = pipeline.predict(X.loc[eval_index])
        if numeric_target and bounds:
            raw_eval = np.asarray(predicted_eval, dtype=float)
            predicted_eval = np.clip(raw_eval, bounds[0], bounds[1])
            domain_clipped_predictions += int(np.count_nonzero(predicted_eval != raw_eval))
        oof_truth.extend(y.loc[eval_index].tolist())
        oof_predictions.extend(predicted_eval.tolist())
        if not numeric_target:
            probability_rows.append(pipeline.predict_proba(X.loc[eval_index]))
            probability_labels.append([str(value) for value in pipeline.named_steps["imputer"].classes_])
        if len(missing_index):
            predicted_missing = pipeline.predict(X.loc[missing_index])
            if numeric_target and bounds:
                raw_missing = np.asarray(predicted_missing, dtype=float)
                predicted_missing = np.clip(raw_missing, bounds[0], bounds[1])
                domain_clipped_predictions += int(np.count_nonzero(predicted_missing != raw_missing))
            missing_predictions.extend(predicted_missing.tolist())
        fold_rows.append({
            "fold": fold_index,
            "trainEndDate": max(frame.loc[train_index, "game_date"]),
            "validationStartDate": validation_start,
            "validationEndDate": validation_end,
            "trainingRows": len(train_index),
            "evaluationRows": len(eval_index),
            "missingRowsPredicted": len(missing_index),
            "sameDateOverlap": False,
        })
    if not fits or not oof_truth:
        raise Stage3TreatmentError(
            "PREDICTED_PREVIEW_FIT_UNAVAILABLE",
            "The bounded chronological preview could not form a valid training/evaluation fold.",
        )
    mae = rmse = accuracy = log_loss_value = None
    if numeric_target:
        truth_array = np.asarray(oof_truth, dtype=float)
        prediction_array = np.asarray(oof_predictions, dtype=float)
        residual = prediction_array - truth_array
        mae = float(np.mean(np.abs(residual)))
        rmse = float(np.sqrt(np.mean(np.square(residual))))
    else:
        truth_strings = np.asarray([str(value) for value in oof_truth])
        prediction_strings = np.asarray([str(value) for value in oof_predictions])
        accuracy = float(np.mean(truth_strings == prediction_strings))
        labels = sorted(set(truth_strings) | {label for group in probability_labels for label in group})
        remapped = []
        cursor = 0
        for probabilities, fold_labels in zip(probability_rows, probability_labels):
            matrix = np.full((len(probabilities), len(labels)), 1e-15, dtype=float)
            for source_index, label in enumerate(fold_labels):
                matrix[:, labels.index(label)] = probabilities[:, source_index]
            matrix /= matrix.sum(axis=1, keepdims=True)
            remapped.append(matrix)
            cursor += len(probabilities)
        if remapped:
            from sklearn.metrics import log_loss
            log_loss_value = float(log_loss(truth_strings[:cursor], np.vstack(remapped), labels=labels))
    domain_violations = 0
    if bounds and missing_predictions:
        predicted_numeric = np.asarray(missing_predictions, dtype=float)
        domain_violations = int(((predicted_numeric < bounds[0]) | (predicted_numeric > bounds[1])).sum())
    observed_series = y.dropna().reset_index(drop=True)
    imputed_series = pd.Series(
        missing_predictions,
        dtype="float64" if numeric_target else "object",
    )
    combined_series = pd.concat([observed_series, imputed_series], ignore_index=True)
    combined_imputed_mask = pd.Series(
        [False] * len(observed_series) + [True] * len(imputed_series),
        dtype=bool,
    )
    if numeric_target:
        after_aggregate, shared_edges = _numeric_distribution_preview(
            combined_series,
            imputed_mask=combined_imputed_mask,
            force_continuous=True,
        )
        before_aggregate, _ = _numeric_distribution_preview(
            y.reset_index(drop=True),
            edges=shared_edges or None,
            force_continuous=True,
        )
        imputed_aggregate, _ = _numeric_distribution_preview(
            imputed_series,
            edges=shared_edges or None,
            force_continuous=True,
        )
        shared_axis = {
            "minimum": shared_edges[0] if shared_edges else _statistics(combined_series)["min"],
            "maximum": shared_edges[-1] if shared_edges else _statistics(combined_series)["max"],
            "binEdges": shared_edges,
        }
        original_statistics = _statistics(y)
        combined_statistics = _statistics(combined_series)
    else:
        before_aggregate = _categorical_distribution_preview(y.reset_index(drop=True))
        after_aggregate = _categorical_distribution_preview(
            combined_series,
            imputed_mask=combined_imputed_mask,
        )
        imputed_aggregate = _categorical_distribution_preview(imputed_series)
        shared_axis = {"minimum": None, "maximum": None, "binEdges": []}
        original_statistics = combined_statistics = {"mean": None, "median": None, "std": None}
    runtime = time.perf_counter() - started
    summary = {
        "status": "COMPLETE",
        "variable": variable,
        "availablePredictors": _available_imputer_predictors(authority, variable),
        "eligiblePredictors": predictors,
        "excludedFields": excluded,
        "design": "Three expanding, date-atomic, game-grouped folds; predictors and median preprocessing fit on training rows only.",
        "folds": fold_rows,
        "missingRowsImputed": len(missing_predictions),
        "oofCoveragePercent": eda._percent(len(oof_predictions), int(frame[variable].notna().sum())),
        "estimator": "HistGradientBoostingRegressor" if numeric_target else "HistGradientBoostingClassifier",
        "hyperparameters": {"maxIter": 50, "maxLeafNodes": 15, "learningRate": 0.08, "l2Regularization": 1.0},
        "mae": mae,
        "rmse": rmse,
        "accuracy": accuracy,
        "logLoss": log_loss_value,
        "predictedDistribution": _predicted_distribution(missing_predictions, numeric=numeric_target),
        "observedDistribution": before_aggregate,
        "imputedDistribution": imputed_aggregate,
        "after": after_aggregate,
        "sharedAxis": shared_axis,
        "aggregateEffect": {
            "observedCount": int(len(observed_series)),
            "imputedCount": int(len(imputed_series)),
            "combinedCount": int(len(combined_series)),
            "originalMissingCount": int(y.isna().sum()),
            "previewUnfilledMissingCount": max(0, int(y.isna().sum()) - int(len(imputed_series))),
            "original": {
                key: original_statistics.get(key) for key in ("mean", "median", "std")
            },
            "combined": {
                key: combined_statistics.get(key) for key in ("mean", "median", "std")
            },
            "semantics": "Observed development values plus row-specific cross-fitted missing-value predictions; no final-OOT rows and no outcome target.",
        },
        "domainBoundViolations": domain_violations,
        "domainClippedPredictions": domain_clipped_predictions,
        "runtimeSeconds": round(runtime, 3),
        "seed": seed,
        "canonicalPredictedPreviewSeed": PREDICTED_PREVIEW_SEED,
        "artifactChecksum": "PENDING_PERSISTENCE",
        "label": "PREPROCESSING PREVIEW · NOT AN OUTCOME MODEL · NOT AN ADOPTED IMPUTER",
        "rowSpecific": True,
        "targetOutcomeExcluded": True,
        "finalOotExcluded": True,
    }
    stored = repository.save_preview(
        authority=_persistence_authority(authority),
        variable=variable,
        specification=specification,
        summary=summary,
        seed=seed,
        actor_user_id=actor_user_id,
    )
    summary["artifactChecksum"] = stored["artifactSha256"]
    return _envelope(
        authority,
        filters=filters,
        rows=len(frame),
        aggregation="BOUNDED_CROSS_FITTED_PREPROCESSING_PREVIEW",
        data=summary,
        duration_ms=runtime * 1000,
        preprocessing_fits=fits,
    )


def _assert_get_authority(authority: eda._Authority, authority_key: str | None) -> None:
    _assert_authority_key(authority, {"authorityKey": authority_key or ""})


def treatment_policy(
    database: Database,
    project_id: str,
    kind: str,
    *,
    authority_key: str,
) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    _assert_get_authority(authority, authority_key)
    normalized = "OUTLIER" if kind.lower() == "outliers" else "IMPUTATION" if kind.lower() == "missing" else ""
    if not normalized:
        raise Stage3TreatmentError("TREATMENT_KIND_INVALID", "Treatment kind must be outliers or missing.")
    state = _policy_state_data(database, authority, normalized)
    return _envelope(
        authority,
        filters={},
        rows=eda.DEVELOPMENT_ROWS,
        aggregation="IMMUTABLE_POLICY_HISTORY",
        data=_frontend_policy(state, kind=normalized),
    )


def _validate_policy_payload(
    database: Database,
    authority: eda._Authority,
    kind: str,
    payload: Mapping[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any], str]:
    catalog = _catalog(authority)
    notes = str(payload.get("notes") or "").strip()
    overrides = {name: dict(value) for name, value in _overrides(payload).items()}
    if "outcome" in overrides:
        raise Stage3TreatmentError(
            "TARGET_DERIVED_TREATMENT_PROHIBITED",
            "The governed target cannot receive or determine a preprocessing policy.",
        )
    unknown = [name for name in overrides if name not in catalog or not catalog[name].get("selectable")]
    if unknown:
        raise Stage3TreatmentError("TREATMENT_VARIABLE_INELIGIBLE", f"Unknown or nonselectable treatment variables: {', '.join(sorted(unknown))}.")
    if kind == "OUTLIER":
        global_method = str(payload.get("globalMethod") or DEFAULT_OUTLIER_METHOD).upper()
        global_treatment = str(payload.get("globalTreatment") or DEFAULT_OUTLIER_TREATMENT).upper()
        if global_method not in OUTLIER_DETECTION_METHODS:
            raise Stage3TreatmentError("OUTLIER_METHOD_UNSUPPORTED", f"Unsupported outlier detection method: {global_method}.")
        if global_treatment not in OUTLIER_TREATMENTS:
            raise Stage3TreatmentError("OUTLIER_TREATMENT_UNSUPPORTED", f"Unsupported outlier treatment: {global_treatment}.")
        for variable, override in overrides.items():
            explicit_method = bool(
                "detectionMethod" in override
                and str(override.get("detectionMethod") or "").strip()
            )
            requested_method = str(override.get("detectionMethod") or global_method).upper()
            treatment = str(override.get("treatment") or global_treatment).upper()
            included = override.get("included", True)
            if not isinstance(included, bool):
                raise Stage3TreatmentError("OUTLIER_INCLUDE_FLAG_INVALID", f"included must be boolean for {variable}.")
            _custom_outlier_bounds(override)
            if catalog[variable].get("dataType") != "numeric":
                raise Stage3TreatmentError("OUTLIER_METHOD_INELIGIBLE", f"Outlier treatment is not eligible for nonnumeric {variable}.")
            _effective_outlier_method(
                variable,
                requested_method,
                explicit_override=explicit_method,
            )
            if treatment not in OUTLIER_TREATMENTS:
                raise Stage3TreatmentError("OUTLIER_TREATMENT_UNSUPPORTED", f"Unsupported outlier treatment: {treatment}.")
            if treatment == "WINSORIZE":
                lower = float(override.get("winsorLowerPercentile", 1.0))
                upper = float(override.get("winsorUpperPercentile", 99.0))
                if not 0 <= lower < upper <= 100:
                    raise Stage3TreatmentError("WINSORIZATION_BOUNDS_INVALID", "Winsorization percentiles must satisfy 0 <= lower < upper <= 100.")
        policy = {
            "globalMethod": global_method,
            "globalTreatment": global_treatment,
            "overrides": overrides,
            "thresholdAuthority": "FITTING_RULE_ONLY",
            "descriptivePreviewThresholdsAreAuthoritative": False,
        }
    else:
        global_method = str(payload.get("globalMethod") or DEFAULT_IMPUTATION_METHOD).upper()
        if global_method in _IMPUTATION_DEFAULT_ALIASES:
            global_method = DEFAULT_IMPUTATION_METHOD
        if global_method not in _IMPUTATION_DEFAULT_ALIASES and global_method not in IMPUTATION_METHODS:
            raise Stage3TreatmentError("IMPUTATION_METHOD_UNSUPPORTED", f"Unsupported global imputation method: {global_method}.")
        allowed_cold_start = {"GOVERNED_PRIOR_WITH_INDICATOR", "RETAIN_WITH_INDICATOR", "REVIEW_REQUIRED"}
        allowed_source_failure = {"REVIEW_REQUIRED", "RETAIN_WITH_INDICATOR", "DROP_VARIABLE"}
        cold_start_default = str(payload.get("coldStartDefault") or "RETAIN_WITH_INDICATOR").upper()
        source_failure_default = str(payload.get("sourceFailureDefault") or "REVIEW_REQUIRED").upper()
        indicator_default = str(payload.get("indicatorDefault") or "RETAIN").upper()
        if cold_start_default not in allowed_cold_start:
            raise Stage3TreatmentError("COLD_START_POLICY_INVALID", f"Unsupported cold-start rule: {cold_start_default}.")
        if cold_start_default == "GOVERNED_PRIOR_WITH_INDICATOR" and not _GOVERNED_PRIOR_FEATURES:
            raise Stage3TreatmentError(
                "COLD_START_GOVERNED_PRIOR_UNAVAILABLE",
                "No Current-Gold predictor has a registered hierarchical/league-prior authority; use RETAIN_WITH_INDICATOR.",
            )
        if source_failure_default not in allowed_source_failure:
            raise Stage3TreatmentError("SOURCE_FAILURE_POLICY_INVALID", f"Unsupported source-failure rule: {source_failure_default}.")
        if indicator_default not in {"RETAIN", "DROP"}:
            raise Stage3TreatmentError("MISSING_INDICATOR_POLICY_INVALID", "indicatorDefault must be RETAIN or DROP.")
        predicted_dependencies: dict[str, list[str]] = {}
        for variable, override in overrides.items():
            explicit_method = bool(
                "method" in override and str(override.get("method") or "").strip()
            )
            requested_method = str(override.get("method") or global_method).upper()
            resolved_method, _fallback = _effective_imputation_method(
                catalog[variable],
                variable,
                requested_method,
                explicit_override=explicit_method,
            )
            if resolved_method == "PREDICTED":
                predictors, _excluded = _predictor_contract(
                    authority,
                    variable,
                    override,
                    require_explicit_nonempty=True,
                )
                predicted_dependencies[variable] = predictors
        _assert_no_predicted_imputation_cycles(predicted_dependencies)
        for variable, override in overrides.items():
            explicit_method = bool(
                "method" in override and str(override.get("method") or "").strip()
            )
            requested_method = str(override.get("method") or global_method).upper()
            method, _fallback = _effective_imputation_method(
                catalog[variable],
                variable,
                requested_method,
                explicit_override=explicit_method,
            )
            if method == "CONSTANT":
                raw = override.get("constantValue")
                if raw is None or (isinstance(raw, str) and not raw.strip()):
                    raise Stage3TreatmentError("IMPUTATION_CONSTANT_REQUIRED", f"{variable} requires a nonempty constant value.")
                if catalog[variable].get("dataType") == "numeric":
                    try:
                        constant = float(raw)
                    except (TypeError, ValueError) as exc:
                        raise Stage3TreatmentError("IMPUTATION_CONSTANT_INVALID", f"{variable} requires a finite numeric constant.") from exc
                    if not math.isfinite(constant):
                        raise Stage3TreatmentError("IMPUTATION_CONSTANT_INVALID", f"{variable} requires a finite numeric constant.")
                    if _looks_binary(variable, catalog[variable]) and constant not in {0.0, 1.0}:
                        raise Stage3TreatmentError("IMPUTATION_CONSTANT_OUT_OF_DOMAIN", f"{variable} requires constant 0 or 1.")
                    bounds = _GOVERNED_DOMAIN_BOUNDS.get(variable)
                    if bounds and not bounds[0] <= constant <= bounds[1]:
                        raise Stage3TreatmentError("IMPUTATION_CONSTANT_OUT_OF_DOMAIN", f"{variable} constant must remain within {bounds}.")
            if method == "PREDICTED":
                predictor_set, excluded = _predictor_contract(
                    authority,
                    variable,
                    override,
                    require_explicit_nonempty=True,
                )
                seed = _canonical_predicted_preview_seed(override)
                specification = _predicted_preview_specification(variable, predictor_set, excluded, {}, seed)
                completed = Stage3TreatmentRepository(database).latest_preview(
                    authority.project_id, variable, authority.review_digest, specification
                )
                summary = dict((completed or {}).get("summary") or {})
                checksum = str((completed or {}).get("artifactSha256") or "")
                safe = (
                    bool(completed)
                    and len(checksum) == 64
                    and all(character in "0123456789abcdef" for character in checksum.lower())
                    and summary.get("status") == "COMPLETE"
                    and summary.get("targetOutcomeExcluded") is True
                    and summary.get("finalOotExcluded") is True
                    and int(summary.get("domainBoundViolations") or 0) == 0
                )
                if not safe:
                    raise Stage3TreatmentError(
                        "PREDICTED_PREVIEW_REQUIRED",
                        f"{variable} requires a matching completed, domain-safe, target-free predicted-imputation preview before adoption.",
                        status_code=409,
                    )
                override["predictorSet"] = predictor_set
                override["seed"] = seed
                override["predictedPreviewArtifactSha256"] = checksum
                override["predictedPreviewSpecificationSha256"] = _stable_hash(specification)
            cold_start_method = str(override.get("coldStartMethod") or cold_start_default).upper()
            source_failure_method = str(override.get("sourceFailureMethod") or source_failure_default).upper()
            retain_indicator = override.get("retainIndicator", indicator_default == "RETAIN")
            if cold_start_method not in allowed_cold_start:
                raise Stage3TreatmentError("COLD_START_POLICY_INVALID", f"Unsupported cold-start rule for {variable}: {cold_start_method}.")
            if cold_start_method == "GOVERNED_PRIOR_WITH_INDICATOR" and variable not in _GOVERNED_PRIOR_FEATURES:
                raise Stage3TreatmentError(
                    "COLD_START_GOVERNED_PRIOR_UNAVAILABLE",
                    f"{variable} has no registered hierarchical/league-prior authority.",
                )
            if source_failure_method not in allowed_source_failure:
                raise Stage3TreatmentError("SOURCE_FAILURE_POLICY_INVALID", f"Unsupported source-failure rule for {variable}: {source_failure_method}.")
            if not isinstance(retain_indicator, bool):
                raise Stage3TreatmentError("MISSING_INDICATOR_POLICY_INVALID", f"retainIndicator must be boolean for {variable}.")
        policy = {
            "globalMethod": global_method,
            "overrides": overrides,
            "coldStartDefault": cold_start_default,
            "sourceFailureDefault": source_failure_default,
            "indicatorDefault": indicator_default,
            "governedPriorEligibleVariables": sorted(_GOVERNED_PRIOR_FEATURES),
        }
    fitting_rule = {
        "contractVersion": "STAGE3_FOLD_LOCAL_PREPROCESSING_POLICY_V1",
        "fitScope": "TRAINING_ROWS_OF_EACH_CHRONOLOGICAL_FOLD_ONLY",
        "validationTransform": "PARAMETERS_FROM_CORRESPONDING_TRAINING_FOLD_ONLY",
        "finalOotTransform": "ONCE_AFTER_SELECTION_USING_COMPLETE_DEVELOPMENT_FIT",
        "sameGameLeakageProhibited": True,
        "targetOutcomeInputsProhibited": True,
        "finalOotParameterFittingProhibited": True,
        "sourceOrGoldMutation": False,
        "outcomeModelActivity": False,
    }
    return global_method, policy, fitting_rule, notes


def save_treatment_policy_draft(
    database: Database,
    project_id: str,
    kind: str,
    payload: Any,
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    payload, filters = _normalize_request(authority, payload)
    if filters:
        raise Stage3TreatmentError(
            "POLICY_FILTER_SCOPE_PROHIBITED",
            "An adopted preprocessing policy must bind the complete development population, not a transient browser filter.",
        )
    normalized = "OUTLIER" if kind.lower() == "outliers" else "IMPUTATION" if kind.lower() == "missing" else ""
    if not normalized:
        raise Stage3TreatmentError("TREATMENT_KIND_INVALID", "Treatment kind must be outliers or missing.")
    global_method, policy, fitting_rule, notes = _validate_policy_payload(database, authority, normalized, payload)
    try:
        Stage3TreatmentRepository(database).save_draft(
            authority=_persistence_authority(authority),
            policy_kind=normalized,
            global_method=global_method,
            policy=policy,
            fitting_rule=fitting_rule,
            notes=notes,
            actor_user_id=actor_user_id,
        )
    except Stage3TreatmentPersistenceError as exc:
        raise Stage3TreatmentError("TREATMENT_POLICY_PERSISTENCE_FAILED", str(exc), status_code=409) from exc
    state = _policy_state_data(database, authority, normalized)
    _invalidate_policy_summary(authority, normalized)
    return _envelope(
        authority,
        filters={},
        rows=eda.DEVELOPMENT_ROWS,
        aggregation="IMMUTABLE_POLICY_DRAFT",
        data=_frontend_policy(state, kind=normalized),
    )


def adopt_treatment_policy(
    database: Database,
    project_id: str,
    kind: str,
    payload: Any,
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    payload, filters = _normalize_request(authority, payload)
    if filters:
        raise Stage3TreatmentError("POLICY_FILTER_SCOPE_PROHIBITED", "Policy adoption must bind the complete development population.")
    normalized = "OUTLIER" if kind.lower() == "outliers" else "IMPUTATION" if kind.lower() == "missing" else ""
    if not normalized:
        raise Stage3TreatmentError("TREATMENT_KIND_INVALID", "Treatment kind must be outliers or missing.")
    policy_id = str(payload.get("policyId") or payload.get("draftPolicyId") or "").strip()
    if not policy_id:
        raise Stage3TreatmentError("TREATMENT_DRAFT_REQUIRED", "An exact immutable draft policyId is required for adoption.")
    expected_checksum = str(payload.get("expectedChecksum") or "").strip()
    if expected_checksum:
        state = Stage3TreatmentRepository(database).policy_state(
            project_id,
            normalized,
            authority.review_digest,
        )
        draft = next(
            (item for item in state.get("history") or [] if item.get("policyId") == policy_id),
            None,
        )
        if draft is None or str(draft.get("checksum") or "") != expected_checksum:
            raise Stage3TreatmentError(
                "TREATMENT_DRAFT_CHECKSUM_MISMATCH",
                "The requested immutable draft checksum does not match the saved policy content.",
                status_code=409,
            )
    try:
        Stage3TreatmentRepository(database).adopt(
            project_id=project_id,
            policy_kind=normalized,
            authority_review_digest=authority.review_digest,
            draft_policy_id=policy_id,
            actor_user_id=actor_user_id,
        )
    except Stage3TreatmentPersistenceError as exc:
        raise Stage3TreatmentError("TREATMENT_POLICY_ADOPTION_FAILED", str(exc), status_code=409) from exc
    state = _policy_state_data(database, authority, normalized)
    _invalidate_policy_summary(authority, normalized)
    return _envelope(
        authority,
        filters={},
        rows=eda.DEVELOPMENT_ROWS,
        aggregation="IMMUTABLE_POLICY_ADOPTION",
        data=_frontend_policy(state, kind=normalized),
    )


__all__ = [
    "IMPUTATION_METHODS",
    "OUTLIER_DETECTION_METHODS",
    "OUTLIER_TREATMENTS",
    "Stage3TreatmentError",
    "adopt_treatment_policy",
    "missing_detail",
    "missing_preview",
    "missing_summary",
    "missing_table",
    "outlier_detail",
    "outlier_preview",
    "outlier_summary",
    "outlier_table",
    "predicted_imputation_preview",
    "save_treatment_policy_draft",
    "treatment_policy",
]
