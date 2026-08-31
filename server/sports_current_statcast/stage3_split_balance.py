"""Project-bound, development-only Stage 3 Split & Balance authority.

The module derives chronological fold contracts from the accepted Current Gold
publication.  It reads target labels only through :mod:`stage3_eda`'s scanner,
whose Arrow predicate excludes final OOT before target columns are materialized.
It computes fold metadata and optional training-fold-only weighting rules; it
contains no model fitting, scoring, tuning, calibration, or promotion path.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from ..persistence.db import Database, json_dumps
from ..persistence.repositories.stage3_split_contract_repository import (
    NO_CURRENT_SPLIT_CONTRACT,
    Stage3SplitContractPersistenceError,
    Stage3SplitContractRepository,
)
from ..sports_datasets.consumer import canonical_json_bytes
from ..sports_gold.contracts import GOLD_CLASS_ORDER
from . import stage3_eda as eda
from .gold import CURRENT_GOLD_DATASET_ID


SPLIT_BALANCE_SCHEMA_VERSION = "SPORTS_STAGE3_SPLIT_BALANCE_V1"
SPLIT_CONTRACT_SCHEMA_VERSION = "SPORTS_STAGE3_SPLIT_CONTRACT_V1"
RECOMMENDED_FOLD_COUNT = 5
RECOMMENDED_SEED = 731_026
INITIAL_TRAINING_SEASON = 2023
FIRST_VALIDATION_SEASON = 2024

_RANDOM_METHOD_TOKENS = (
    "RANDOM",
    "SHUFFLE",
    "STRATIFIED_K_FOLD",
    "STRATIFIED K-FOLD",
    "ROW_LEVEL",
    "SMOTE",
    "OVERSAMPL",
    "UNDERSAMPL",
)
_ALLOWED_CLASS_POLICIES = {
    "NATURAL_BASE_RATES",
    "INVERSE_FREQUENCY_CLASS_WEIGHTS",
    "EFFECTIVE_NUMBER_CLASS_WEIGHTS",
    "FOCAL_LOSS_CHALLENGER",
}


class Stage3SplitBalanceError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)

    def public_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


@dataclass(frozen=True)
class _Columns:
    game: str
    game_date: str
    outcome: str
    batter: str | None
    pitcher: str | None
    cold_start: tuple[str, ...]
    insufficient_history: tuple[str, ...]
    missing_features: tuple[str, ...]


FeatureSetValidator = Callable[
    [Database, Mapping[str, Any], Sequence[str]], Mapping[str, Any]
]
_FEATURE_SET_VALIDATOR: FeatureSetValidator | None = None


def configure_feature_set_validator(validator: FeatureSetValidator | None) -> None:
    """Install the exact registered-feature-set validator used by integration.

    The default implementation performs a strict authority-bound lookup only
    when the additive ``stage3_feature_set_versions`` table exists.  Tests and
    the feature-engineering integration may inject the repository validator
    without creating a second feature-set authority.
    """

    global _FEATURE_SET_VALIDATOR
    _FEATURE_SET_VALIDATOR = validator


def _stable_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _authority_payload(authority: eda._Authority) -> dict[str, Any]:
    public = {
        **authority.public(),
        "registrationId": authority.registration_id,
        "datasetVersionId": authority.dataset_version_id,
        "activationRevision": int(authority.activation_revision),
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
            "rows": int(eda.DEVELOPMENT_ROWS),
        },
        "finalOot": {
            "startDate": eda.EXPECTED_FINAL_OOT[0],
            "endDate": eda.EXPECTED_FINAL_OOT[1],
            "rows": int(eda.FINAL_OOT_ROWS),
            "locked": True,
        },
    }


def _resolve_authority(database: Database, project_id: str) -> eda._Authority:
    authority = eda._resolve_authority(database, project_id)
    public = authority.public()
    if authority.project_id != project_id:
        raise Stage3SplitBalanceError(
            "SPLIT_PROJECT_AUTHORITY_MISMATCH",
            "The resolved Stage 3 authority belongs to another project.",
            status_code=409,
        )
    if public.get("goldDatasetId") != CURRENT_GOLD_DATASET_ID:
        raise Stage3SplitBalanceError(
            "SPLIT_GOLD_AUTHORITY_MISMATCH",
            "Split & Balance requires the exact project-bound Current Gold authority.",
            status_code=409,
        )
    for field, value in (
        ("sourceManifestSha", authority.source_manifest_sha),
        ("goldManifestSha", authority.gold_manifest_sha),
        ("contextualManifestSha", authority.contextual_manifest_sha),
        ("reviewDigest", authority.review_digest),
    ):
        if len(str(value)) != 64:
            raise Stage3SplitBalanceError(
                "SPLIT_AUTHORITY_INCOMPLETE",
                f"The project-bound {field} is not a complete SHA-256 identity.",
                status_code=409,
            )
    return authority


def _assert_authority_key(
    authority: eda._Authority, payload: Mapping[str, Any]
) -> None:
    expected = _authority_payload(authority)["authorityKey"]
    supplied = str(payload.get("authorityKey") or "").strip()
    if not supplied:
        raise Stage3SplitBalanceError(
            "SPLIT_AUTHORITY_REQUIRED",
            "The exact project-bound Split & Balance authority key is required.",
            status_code=409,
        )
    if supplied != expected:
        raise Stage3SplitBalanceError(
            "SPLIT_AUTHORITY_STALE",
            "The Split & Balance request does not match the accepted project/Gold authority.",
            status_code=409,
        )


def _audit() -> dict[str, Any]:
    return {
        **eda._audit_flags(),
        "finalOotTargetsMaterialized": False,
        "sourceOrGoldMutated": False,
        "modelActivity": {
            "fits": 0,
            "scores": 0,
            "tunes": 0,
            "calibrations": 0,
            "selections": 0,
            "promotions": 0,
        },
        "splitActivity": {
            "foldContractsGenerated": True,
            "randomSplits": 0,
            "rowLevelSplits": 0,
            "modelsFit": 0,
            "modelsScored": 0,
            "modelsRegistered": 0,
            "promotions": 0,
        },
    }


def _population(rows: int) -> dict[str, Any]:
    return {
        "scope": "DEVELOPMENT_ONLY",
        "rows": int(rows),
        "developmentRows": int(eda.DEVELOPMENT_ROWS),
        "developmentStartDate": eda.DEVELOPMENT_START,
        "developmentEndDate": eda.DEVELOPMENT_END,
        "finalOotRows": int(eda.FINAL_OOT_ROWS),
        "finalOotStartDate": eda.EXPECTED_FINAL_OOT[0],
        "finalOotEndDate": eda.EXPECTED_FINAL_OOT[1],
        "finalOotLocked": True,
        "finalOotTargetCountsExposed": False,
        "aggregation": "CANONICAL_GAME_DATE_ATOMIC_SPLIT_CONTRACT",
    }


def _envelope(
    authority: eda._Authority, data: Mapping[str, Any], *, rows: int
) -> dict[str, Any]:
    return {
        "ok": True,
        "authority": _authority_payload(authority),
        "population": _population(rows),
        "audit": _audit(),
        "data": eda._json_safe(dict(data)),
    }


def _normalize_payload(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise Stage3SplitBalanceError(
            "SPLIT_REQUEST_INVALID", "The Split & Balance request must be an object."
        )
    serialized = json_dumps(dict(payload), {}).upper()
    if any(token in serialized for token in _RANDOM_METHOD_TOKENS):
        raise Stage3SplitBalanceError(
            "SPLIT_RANDOM_METHOD_PROHIBITED",
            "Random, stratified-random, row-level, SMOTE, over-, and undersampling are unavailable for this project.",
        )
    return payload


def _column(
    names: set[str], aliases: Sequence[str], *, required: bool = True
) -> str | None:
    found = next((name for name in aliases if name in names), None)
    if found is None and required:
        raise Stage3SplitBalanceError(
            "SPLIT_REQUIRED_COLUMN_MISSING",
            f"Current Gold lacks required split field: {aliases[0]}.",
            status_code=409,
        )
    return found


def _metadata_missing_features(authority: eda._Authority) -> tuple[str, ...]:
    try:
        variables = eda._variables(authority)
    except Exception:
        return ()
    names = set(authority.schema.names)
    return tuple(
        str(item["name"])
        for item in variables
        if item.get("selectable") is True
        and str(item.get("name")) in names
        and float(item.get("missingPercent") or 0.0) > 0.0
    )


def _development_frame(authority: eda._Authority) -> tuple[pd.DataFrame, _Columns]:
    names = set(authority.schema.names)
    game = _column(names, ("canonicalGameId", "canonical_game_id", "game_id"))
    game_date = _column(names, ("game_date", "gameDate", "game_date_local"))
    outcome = _column(names, ("outcome", "pa_outcome"))
    batter = _column(
        names,
        ("batterCanonicalPlayerId", "batter_canonical_player_id"),
        required=False,
    )
    pitcher = _column(
        names,
        ("pitcherCanonicalPlayerId", "pitcher_canonical_player_id"),
        required=False,
    )
    cold_start = tuple(
        name
        for name in (
            "batter_prior_missing",
            "pitcher_prior_missing",
        )
        if name in names
    )
    insufficient = tuple(
        name
        for name in (
            "batter_last100_insufficient",
            "pitcher_last250_insufficient",
        )
        if name in names
    )
    missing_features = _metadata_missing_features(authority)
    support = [
        str(game),
        str(game_date),
        str(outcome),
        *([batter] if batter else []),
        *([pitcher] if pitcher else []),
        *cold_start,
        *insufficient,
    ]
    requested = list(dict.fromkeys([*support, *missing_features]))
    frame = eda._scan(
        authority,
        requested,
        {"startDate": eda.DEVELOPMENT_START, "endDate": eda.DEVELOPMENT_END},
    )
    if len(frame) != int(eda.DEVELOPMENT_ROWS):
        raise Stage3SplitBalanceError(
            "SPLIT_DEVELOPMENT_ROW_MISMATCH",
            f"Expected {eda.DEVELOPMENT_ROWS:,} development rows, found {len(frame):,}.",
            status_code=409,
        )
    parsed_dates = pd.to_datetime(frame[str(game_date)], errors="coerce")
    if parsed_dates.isna().any():
        raise Stage3SplitBalanceError(
            "SPLIT_GAME_DATE_INVALID", "At least one development row lacks a valid game date."
        )
    frame = frame.copy()
    frame["__game_date"] = parsed_dates.dt.normalize()
    actual_start = frame["__game_date"].min().date().isoformat()
    actual_end = frame["__game_date"].max().date().isoformat()
    if (actual_start, actual_end) != (eda.DEVELOPMENT_START, eda.DEVELOPMENT_END):
        raise Stage3SplitBalanceError(
            "SPLIT_DEVELOPMENT_DATE_MISMATCH",
            "The materialized development date range does not match the accepted authority.",
            status_code=409,
        )
    if frame[str(game)].isna().any():
        raise Stage3SplitBalanceError(
            "SPLIT_GAME_IDENTITY_MISSING",
            "Every development row must carry a canonical game identity.",
            status_code=409,
        )
    game_date_counts = frame.groupby(str(game), dropna=False)["__game_date"].nunique()
    if bool((game_date_counts != 1).any()):
        raise Stage3SplitBalanceError(
            "SPLIT_GAME_DATE_CONTRADICTION",
            "A canonical game maps to more than one calendar date.",
            status_code=409,
        )
    target = frame[str(outcome)].astype(str)
    invalid_classes = sorted(set(target.unique()) - set(GOLD_CLASS_ORDER))
    if invalid_classes:
        raise Stage3SplitBalanceError(
            "SPLIT_TARGET_TAXONOMY_MISMATCH",
            "Development rows contain classes outside the governed eight-class taxonomy: "
            + ", ".join(invalid_classes),
            status_code=409,
        )
    frame["__outcome"] = target
    if missing_features:
        missing = frame[list(missing_features)].isna()
        frame["__physical_missing_cells"] = missing.sum(axis=1).astype("int64")
        frame["__physical_missing_row"] = missing.any(axis=1)
    else:
        frame["__physical_missing_cells"] = 0
        frame["__physical_missing_row"] = False
    keep = list(
        dict.fromkeys(
            [
                *support,
                *missing_features,
                "__game_date",
                "__outcome",
                "__physical_missing_cells",
                "__physical_missing_row",
            ]
        )
    )
    frame = frame[keep].copy()
    return frame, _Columns(
        game=str(game),
        game_date=str(game_date),
        outcome=str(outcome),
        batter=batter,
        pitcher=pitcher,
        cold_start=cold_start,
        insufficient_history=insufficient,
        missing_features=missing_features,
    )


def _truthy(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").fillna(0).ne(0)
    return series.fillna("").astype(str).str.upper().isin(
        {"1", "TRUE", "YES", "Y", "MISSING", "NO_PRIOR_HISTORY"}
    )


def _class_distribution(frame: pd.DataFrame) -> list[dict[str, Any]]:
    counts = frame["__outcome"].value_counts()
    rows = len(frame)
    return [
        {
            "value": label,
            "count": int(counts.get(label, 0)),
            "percent": float(100.0 * int(counts.get(label, 0)) / rows)
            if rows
            else 0.0,
        }
        for label in GOLD_CLASS_ORDER
    ]


def _composition(frame: pd.DataFrame, period: str) -> list[dict[str, Any]]:
    periods = (
        frame["__game_date"].dt.year.astype(str)
        if period == "season"
        else frame["__game_date"].dt.to_period("M").astype(str)
    )
    result: list[dict[str, Any]] = []
    for value in sorted(periods.unique()):
        subset = frame.loc[periods == value]
        for item in _class_distribution(subset):
            result.append({period: int(value) if period == "season" else value, **item})
    return result


def _profile(frame: pd.DataFrame, columns: _Columns) -> dict[str, Any]:
    rows = len(frame)
    cold = pd.Series(False, index=frame.index)
    for name in columns.cold_start:
        cold |= _truthy(frame[name])
    insufficient = pd.Series(False, index=frame.index)
    for name in columns.insufficient_history:
        insufficient |= _truthy(frame[name])
    distribution = _class_distribution(frame)
    positive_counts = [item["count"] for item in distribution if item["count"] > 0]
    rare = min(positive_counts) if positive_counts else 0
    dominant = max(positive_counts) if positive_counts else 0
    missing_cells = int(frame["__physical_missing_cells"].sum())
    missing_rows = int(frame["__physical_missing_row"].sum())
    missing_by_feature = [
        {
            "feature": name,
            "missingCells": int(frame[name].isna().sum()),
            "missingPercent": (
                float(100.0 * frame[name].isna().mean()) if rows else 0.0
            ),
        }
        for name in columns.missing_features
    ]
    return {
        "rows": rows,
        "games": int(frame[columns.game].nunique(dropna=True)),
        "dates": int(frame["__game_date"].nunique()),
        "startDate": frame["__game_date"].min().date().isoformat() if rows else None,
        "endDate": frame["__game_date"].max().date().isoformat() if rows else None,
        "batters": int(frame[columns.batter].nunique(dropna=True)) if columns.batter else 0,
        "pitchers": int(frame[columns.pitcher].nunique(dropna=True)) if columns.pitcher else 0,
        "coldStart": {
            "rows": int(cold.sum()),
            "percent": float(100.0 * cold.mean()) if rows else 0.0,
            "insufficientHistoryRows": int(insufficient.sum()),
            "insufficientHistoryPercent": (
                float(100.0 * insufficient.mean()) if rows else 0.0
            ),
        },
        "physicalMissingness": {
            "featuresEvaluated": len(columns.missing_features),
            "featureNames": list(columns.missing_features),
            "byFeature": missing_by_feature,
            "missingCells": missing_cells,
            "rowsWithMissing": missing_rows,
            "rowsWithMissingPercent": (
                float(100.0 * missing_rows / rows) if rows else 0.0
            ),
            "missingCellPercent": (
                float(
                    100.0
                    * missing_cells
                    / (rows * len(columns.missing_features))
                )
                if rows and columns.missing_features
                else 0.0
            ),
        },
        "classDistribution": distribution,
        "rarestClassCount": rare,
        "dominantClassCount": dominant,
        "dominantToRarestRatio": float(dominant / rare) if rare else None,
    }


def _class_policy(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = payload.get("classPolicy") or "NATURAL_BASE_RATES"
    if isinstance(raw, Mapping):
        strategy = str(raw.get("strategy") or "NATURAL_BASE_RATES").upper()
        beta = float(raw.get("beta") or 0.999)
        gamma = float(raw.get("gamma") or 2.0)
    else:
        strategy = str(raw).upper()
        beta = 0.999
        gamma = 2.0
    aliases = {
        "NONE": "NATURAL_BASE_RATES",
        "NATURAL": "NATURAL_BASE_RATES",
        "INVERSE_FREQUENCY": "INVERSE_FREQUENCY_CLASS_WEIGHTS",
        "EFFECTIVE_NUMBER": "EFFECTIVE_NUMBER_CLASS_WEIGHTS",
        "FOCAL_LOSS": "FOCAL_LOSS_CHALLENGER",
    }
    strategy = aliases.get(strategy, strategy)
    if strategy not in _ALLOWED_CLASS_POLICIES:
        raise Stage3SplitBalanceError(
            "SPLIT_CLASS_POLICY_INVALID",
            "Class policy must retain natural rates or define a training-fold-only weighting challenger.",
        )
    if not 0.0 < beta < 1.0:
        raise Stage3SplitBalanceError(
            "SPLIT_EFFECTIVE_NUMBER_BETA_INVALID", "Effective-number beta must be between zero and one."
        )
    if gamma <= 0 or not np.isfinite(gamma):
        raise Stage3SplitBalanceError(
            "SPLIT_FOCAL_GAMMA_INVALID", "Focal-loss gamma must be finite and positive."
        )
    return {
        "strategy": strategy,
        "baseRates": "NATURAL_OBSERVED_DISTRIBUTION",
        "randomOversampling": False,
        "smote": False,
        "undersampling": False,
        "fitScope": "EACH_TRAINING_FOLD_ONLY",
        "validationFrequenciesUsed": False,
        "finalOotFrequenciesUsed": False,
        "beta": beta if strategy == "EFFECTIVE_NUMBER_CLASS_WEIGHTS" else None,
        "focalGamma": gamma if strategy == "FOCAL_LOSS_CHALLENGER" else None,
        "automaticAdoption": False,
    }


def _training_weights(
    distribution: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> dict[str, float | None]:
    counts = {str(item["value"]): int(item["count"]) for item in distribution}
    positive = {label: count for label, count in counts.items() if count > 0}
    strategy = policy["strategy"]
    if strategy in {"NATURAL_BASE_RATES", "FOCAL_LOSS_CHALLENGER"}:
        return {label: 1.0 if counts[label] > 0 else None for label in GOLD_CLASS_ORDER}
    if strategy == "INVERSE_FREQUENCY_CLASS_WEIGHTS":
        total = sum(positive.values())
        classes = len(positive)
        return {
            label: float(total / (classes * counts[label])) if counts[label] else None
            for label in GOLD_CLASS_ORDER
        }
    beta = float(policy["beta"])
    raw = {
        label: (1.0 - beta) / (1.0 - beta ** counts[label])
        for label in positive
    }
    normalization = sum(raw[label] * positive[label] for label in positive) / sum(
        positive.values()
    )
    return {
        label: float(raw[label] / normalization) if label in raw else None
        for label in GOLD_CLASS_ORDER
    }


def _balanced_date_blocks(
    date_game_counts: Sequence[tuple[pd.Timestamp, int]], parts: int
) -> list[list[pd.Timestamp]]:
    if len(date_game_counts) < parts:
        raise Stage3SplitBalanceError(
            "SPLIT_VALIDATION_DATES_INSUFFICIENT",
            f"At least {parts} distinct validation dates are required.",
        )
    counts = np.asarray(
        [count for _date, count in date_game_counts], dtype=np.int64
    )
    if np.any(counts <= 0):
        raise Stage3SplitBalanceError(
            "SPLIT_VALIDATION_GAME_COUNTS_INVALID",
            "Every governed validation date must contain at least one canonical game.",
        )
    # Global date-atomic optimum: minimize the maximum scaled deviation from
    # equal game counts, then squared deviation, then endpoint tuple.  Integer
    # arithmetic and the lexicographic tie-break make the result reproducible.
    prefix = np.concatenate(
        (np.asarray([0], dtype=np.int64), np.cumsum(counts, dtype=np.int64))
    )
    total = int(prefix[-1])
    previous: dict[int, tuple[int, int, tuple[int, ...]]] = {0: (0, 0, ())}
    for block_number in range(1, parts + 1):
        current: dict[int, tuple[int, int, tuple[int, ...]]] = {}
        minimum_end = block_number
        maximum_end = len(date_game_counts) - (parts - block_number)
        for end in range(minimum_end, maximum_end + 1):
            best: tuple[int, int, tuple[int, ...]] | None = None
            for start in range(block_number - 1, end):
                prior = previous.get(start)
                if prior is None:
                    continue
                segment_games = int(prefix[end] - prefix[start])
                scaled_deviation = abs(segment_games * parts - total)
                candidate = (
                    max(prior[0], scaled_deviation),
                    prior[1] + scaled_deviation * scaled_deviation,
                    (*prior[2], end),
                )
                if best is None or candidate < best:
                    best = candidate
            if best is not None:
                current[end] = best
        previous = current
    optimum = previous.get(len(date_game_counts))
    if optimum is None or len(optimum[2]) != parts:
        raise Stage3SplitBalanceError(
            "SPLIT_EQUAL_GAME_OPTIMIZATION_FAILED",
            "The global equal-game date-atomic fold optimization failed.",
        )
    boundaries = [0, *optimum[2]]
    return [
        [date_value for date_value, _count in date_game_counts[left:right]]
        for left, right in zip(boundaries, boundaries[1:])
    ]


def _selected_feature_set_ids(payload: Mapping[str, Any]) -> list[str]:
    raw = payload.get("selectedFeatureSetIds") or []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise Stage3SplitBalanceError(
            "SPLIT_FEATURE_SET_IDS_INVALID", "selectedFeatureSetIds must be an ordered list."
        )
    values = [str(value).strip() for value in raw if str(value).strip()]
    if len(values) != len(set(values)):
        raise Stage3SplitBalanceError(
            "SPLIT_FEATURE_SET_IDS_DUPLICATE", "Selected feature-set identities must be unique."
        )
    return values


def _default_feature_set_validation(
    database: Database,
    authority: Mapping[str, Any],
    selected_ids: Sequence[str],
) -> Mapping[str, Any]:
    if not selected_ids:
        return {
            "valid": False,
            "missingIds": [],
            "unavailableActiveFeatures": [],
            "reason": "At least one registered project-bound feature-set version is required.",
        }
    with database.connection() as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'stage3_feature_set_versions'"
        ).fetchone()
        if exists is None:
            return {
                "valid": False,
                "missingIds": list(selected_ids),
                "unavailableActiveFeatures": [],
                "reason": "The registered project feature-set authority is not available.",
            }
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(stage3_feature_set_versions)"
            ).fetchall()
        }
        id_column = next(
            (
                name
                for name in ("feature_set_id", "feature_set_version_id")
                if name in columns
            ),
            None,
        )
        status_column = next(
            (name for name in ("feature_set_status", "status") if name in columns),
            None,
        )
        checksum_column = next(
            (name for name in ("content_sha256", "checksum") if name in columns),
            None,
        )
        required = {
            "project_id",
            "registration_id",
            "dataset_version_id",
            "activation_revision",
            "source_dataset_id",
            "source_manifest_sha",
            "gold_manifest_sha",
            "contextual_manifest_sha",
            "authority_review_digest",
        }
        if (
            id_column is None
            or status_column is None
            or checksum_column is None
            or not required.issubset(columns)
        ):
            return {
                "valid": False,
                "missingIds": list(selected_ids),
                "unavailableActiveFeatures": [],
                "reason": "The feature-set table lacks the exact registration authority columns.",
            }
        placeholders = ",".join("?" for _ in selected_ids)
        rows = connection.execute(
            f"""
            SELECT {id_column} AS feature_set_id, {status_column} AS status,
                   {checksum_column} AS checksum
            FROM stage3_feature_set_versions
            WHERE project_id = ? AND registration_id = ?
              AND dataset_version_id = ? AND activation_revision = ?
              AND source_dataset_id = ? AND source_manifest_sha = ?
              AND gold_manifest_sha = ? AND contextual_manifest_sha = ?
              AND authority_review_digest = ?
              AND {id_column} IN ({placeholders})
            """,
            (
                authority["projectId"],
                authority["registrationId"],
                authority["datasetVersionId"],
                int(authority["activationRevision"]),
                authority["sourceDatasetId"],
                authority["sourceManifestSha"],
                authority["goldManifestSha"],
                authority["contextualManifestSha"],
                authority["reviewDigest"],
                *selected_ids,
            ),
        ).fetchall()
    registered = {
        str(row["feature_set_id"]): str(row["checksum"])
        for row in rows
        if str(row["status"]).upper() in {"ADOPTED", "REGISTERED", "CURRENT"}
        and len(str(row["checksum"])) == 64
    }
    missing = [value for value in selected_ids if value not in registered]
    return {
        "valid": not missing,
        "missingIds": missing,
        "unavailableActiveFeatures": [],
        "registeredFeatureSets": [
            {"featureSetId": value, "checksum": registered[value]}
            for value in selected_ids
            if value in registered
        ],
        "reason": (
            "Every selected feature set is registered to this project and authority."
            if not missing
            else "Some selected feature sets are absent, unregistered, or authority-stale."
        ),
    }


def _feature_set_validation(
    database: Database,
    authority: eda._Authority,
    selected_ids: Sequence[str],
) -> dict[str, Any]:
    validator = _FEATURE_SET_VALIDATOR or _default_feature_set_validation
    result = dict(
        validator(database, _persistence_authority(authority), selected_ids)
    )
    return {
        "valid": result.get("valid") is True,
        "missingIds": list(result.get("missingIds") or []),
        "unavailableActiveFeatures": list(
            result.get("unavailableActiveFeatures") or []
        ),
        "registeredFeatureSets": list(result.get("registeredFeatureSets") or []),
        "reason": str(result.get("reason") or "Feature-set validation failed closed."),
    }


def _fold_record(
    frame: pd.DataFrame,
    columns: _Columns,
    *,
    fold_number: int,
    train_mask: pd.Series,
    validation_mask: pd.Series,
    embargo_mask: pd.Series,
    class_policy: Mapping[str, Any],
    selected_feature_set_ids: Sequence[str],
) -> dict[str, Any]:
    train = frame.loc[train_mask]
    validation = frame.loc[validation_mask]
    if train.empty or validation.empty:
        raise Stage3SplitBalanceError(
            "SPLIT_FOLD_EMPTY", f"Fold {fold_number} has an empty training or validation population."
        )
    train_profile = _profile(train, columns)
    validation_profile = _profile(validation, columns)
    identity = {
        "foldNumber": fold_number,
        "training": train_profile,
        "validation": validation_profile,
        "embargoDaysRepresented": int(frame.loc[embargo_mask, "__game_date"].nunique()),
        "embargoRows": int(embargo_mask.sum()),
        "classPolicy": dict(class_policy),
        "classWeights": _training_weights(
            train_profile["classDistribution"], class_policy
        ),
        "selectedFeatureSetIds": list(selected_feature_set_ids),
        "preprocessingFitScope": "TRAINING_ROWS_OF_THIS_FOLD_ONLY",
        "validationStatisticsUsedForTraining": False,
        "finalOotUsed": False,
    }
    return {
        **identity,
        "trainStart": train_profile["startDate"],
        "trainEnd": train_profile["endDate"],
        "validationStart": validation_profile["startDate"],
        "validationEnd": validation_profile["endDate"],
        "trainRows": train_profile["rows"],
        "validationRows": validation_profile["rows"],
        "trainGames": train_profile["games"],
        "validationGames": validation_profile["games"],
        "trainDates": train_profile["dates"],
        "validationDates": validation_profile["dates"],
        "trainBatters": train_profile["batters"],
        "validationBatters": validation_profile["batters"],
        "trainPitchers": train_profile["pitchers"],
        "validationPitchers": validation_profile["pitchers"],
        "checksum": _stable_hash(identity),
    }


def _quality_gates(
    frame: pd.DataFrame,
    columns: _Columns,
    folds: Sequence[Mapping[str, Any]],
    *,
    selected_validation: Mapping[str, Any],
    fold_count: int,
    training_policy: str,
    allow_gaps: bool,
) -> list[dict[str, Any]]:
    validation_game_ids: list[str] = []
    validation_date_ranges: list[tuple[str, str]] = []
    for fold in folds:
        start = pd.Timestamp(fold["validationStart"])
        end = pd.Timestamp(fold["validationEnd"])
        subset = frame.loc[frame["__game_date"].between(start, end)]
        validation_game_ids.extend(subset[columns.game].astype(str).unique().tolist())
        validation_date_ranges.append((str(fold["validationStart"]), str(fold["validationEnd"])))
    unique_assignments = len(validation_game_ids) == len(set(validation_game_ids))
    first_validation_start = min(
        pd.Timestamp(start) for start, _end in validation_date_ranges
    )
    validation_universe = set(
        frame.loc[
            frame["__game_date"] >= first_validation_start, columns.game
        ].astype(str)
    )
    complete_assignment = set(validation_game_ids) == validation_universe
    nonoverlap = all(
        validation_date_ranges[index][1] < validation_date_ranges[index + 1][0]
        for index in range(len(validation_date_ranges) - 1)
    )
    class_nonzero = all(
        all(
            int(item["count"]) > 0
            for item in fold["training"]["classDistribution"]
        )
        and all(
            int(item["count"]) > 0
            for item in fold["validation"]["classDistribution"]
        )
        for fold in folds
    )
    unavailable = list(selected_validation.get("unavailableActiveFeatures") or [])
    checks = [
        ("PROJECT_SOURCE_IDENTITY_MATCH", True, "Exact project source authority resolved."),
        ("GOLD_IDENTITY_MATCH", True, "Exact project-bound Current Gold authority resolved."),
        (
            "DEVELOPMENT_COVERAGE_EXACT",
            len(frame) == int(eda.DEVELOPMENT_ROWS),
            f"{len(frame):,} development rows are represented exactly.",
        ),
        ("FINAL_OOT_EXCLUDED", True, "Final OOT labels were never materialized."),
        (
            "FINAL_OOT_LABELS_NOT_QUERIED",
            True,
            "The target scan is predicate-limited to the accepted development cutoff before materialization.",
        ),
        (
            "FIVE_FOLDS_REQUIRED",
            fold_count == RECOMMENDED_FOLD_COUNT,
            f"The contract contains {fold_count} folds; registration requires five.",
        ),
        ("DATE_ORDER_VALID", all(fold["trainEnd"] < fold["validationStart"] for fold in folds), "Every training window ends before validation begins."),
        ("TRAINING_PRECEDES_VALIDATION", all(fold["training"]["endDate"] < fold["validation"]["startDate"] for fold in folds), "No validation date enters its training fold."),
        ("CANONICAL_GAME_ATOMIC", True, "Canonical games map to one date and one fold assignment."),
        ("CALENDAR_DATE_ATOMIC", True, "All rows on a game date remain together."),
        ("VALIDATION_WINDOWS_NON_OVERLAPPING", nonoverlap, "Validation date windows do not overlap."),
        ("VALIDATION_ASSIGNMENT_UNIQUE", unique_assignments, "Every validation game is assigned at most once."),
        (
            "VALIDATION_ASSIGNMENT_COMPLETE",
            complete_assignment or allow_gaps,
            (
                "Every governed game from the first validation date through the development cutoff is assigned exactly once."
                if complete_assignment
                else (
                    "Explicit manual gaps are enabled; "
                    f"{len(set(validation_game_ids)):,} of {len(validation_universe):,} governed validation-universe games are assigned."
                )
                if allow_gaps
                else "At least one governed game from the validation universe is unassigned."
            ),
        ),
        ("PREPROCESSING_TRAINING_FOLD_ONLY", True, "All preprocessing remains a per-training-fold rule."),
        ("NO_RANDOM_SPLIT", True, "No random, stratified-random, or row-level split is available."),
        ("EXPANDING_TRAINING_WINDOWS", training_policy != "EXPANDING_WINDOW" or all(int(folds[index]["trainGames"]) < int(folds[index + 1]["trainGames"]) for index in range(len(folds) - 1)), "Training game populations grow monotonically."),
        ("FEATURE_SET_VERSIONS_REGISTERED", selected_validation.get("valid") is True, str(selected_validation.get("reason") or "Feature-set registration is unresolved.")),
        ("NO_UNAVAILABLE_FEATURE_ACTIVE", not unavailable, "No unavailable feature is active." if not unavailable else "Unavailable active features: " + ", ".join(unavailable)),
        ("FOLD_CLASS_COUNTS_NONZERO", class_nonzero, "Every governed class has nonzero train and validation support where represented."),
        ("ZERO_MODEL_ACTIVITY", True, "Generating or registering this contract fits and scores zero models."),
    ]
    return [
        {"code": code, "status": "PASS" if passed else "FAIL", "blocking": True, "detail": detail}
        for code, passed, detail in checks
    ]


def _design_contract(
    database: Database,
    authority: eda._Authority,
    frame: pd.DataFrame,
    columns: _Columns,
    *,
    mode: str,
    folds: Sequence[Mapping[str, Any]],
    class_policy: Mapping[str, Any],
    selected_feature_set_ids: Sequence[str],
    embargo_days: int,
    minimum_training_games: int,
    minimum_validation_games: int,
    training_policy: str,
    allow_gaps: bool,
    seed: int,
    boundary_rule: str,
) -> dict[str, Any]:
    validation = _feature_set_validation(
        database, authority, selected_feature_set_ids
    )
    gates = _quality_gates(
        frame,
        columns,
        folds,
        selected_validation=validation,
        fold_count=len(folds),
        training_policy=training_policy,
        allow_gaps=allow_gaps,
    )
    contract = {
        "schemaVersion": SPLIT_CONTRACT_SCHEMA_VERSION,
        "mode": mode,
        "foldCount": len(folds),
        "development": {
            "startDate": eda.DEVELOPMENT_START,
            "endDate": eda.DEVELOPMENT_END,
            "rows": int(eda.DEVELOPMENT_ROWS),
            "games": int(frame[columns.game].nunique()),
            "dates": int(frame["__game_date"].nunique()),
        },
        "finalOot": {
            "startDate": eda.EXPECTED_FINAL_OOT[0],
            "endDate": eda.EXPECTED_FINAL_OOT[1],
            "rows": int(eda.FINAL_OOT_ROWS),
            "locked": True,
            "targetsAccessed": False,
        },
        "groupingUnit": "CANONICAL_GAME",
        "datePolicy": "DATE_ATOMIC",
        "trainingPolicy": training_policy,
        "validationBalanceUnit": "CANONICAL_GAME_COUNT",
        "boundaryRule": boundary_rule,
        "embargoDays": embargo_days,
        "minimumTrainingGames": minimum_training_games,
        "minimumValidationGames": minimum_validation_games,
        "allowGaps": allow_gaps,
        "preprocessingScope": "FIT_INSIDE_EACH_TRAINING_FOLD_ONLY",
        "deterministicSeed": seed,
        "deterministicSeedUsedForDateSplit": False,
        "classPolicy": dict(class_policy),
        "selectedFeatureSetIds": list(selected_feature_set_ids),
        "selectedFeatureSets": validation["registeredFeatureSets"],
        "featureSetValidation": validation,
        "folds": list(folds),
        "qualityGates": gates,
        "allBlockingGatesPass": all(item["status"] == "PASS" for item in gates),
        "modelActivity": {"fits": 0, "scores": 0, "promotions": 0},
    }
    contract["checksum"] = _stable_hash(contract)
    return contract


def _configuration(payload: Mapping[str, Any]) -> dict[str, Any]:
    fold_count = int(payload.get("foldCount") or RECOMMENDED_FOLD_COUNT)
    if fold_count != RECOMMENDED_FOLD_COUNT:
        raise Stage3SplitBalanceError(
            "SPLIT_FOLD_COUNT_INVALID",
            "This project requires exactly five chronological folds before registration.",
        )
    embargo_days = int(payload.get("embargoDays") or 0)
    if not 0 <= embargo_days <= 30:
        raise Stage3SplitBalanceError(
            "SPLIT_EMBARGO_INVALID", "Embargo days must be between 0 and 30."
        )
    minimum_training_games = int(payload.get("minimumTrainingGames") or 1)
    minimum_validation_games = int(payload.get("minimumValidationGames") or 1)
    if minimum_training_games < 1 or minimum_validation_games < 1:
        raise Stage3SplitBalanceError(
            "SPLIT_MINIMUM_GAMES_INVALID", "Minimum training and validation games must be positive."
        )
    seed = int(payload.get("deterministicSeed") or RECOMMENDED_SEED)
    training_policy = str(
        payload.get("trainingPolicy") or payload.get("windowPolicy") or "EXPANDING_WINDOW"
    ).upper()
    training_policy = {
        "EXPANDING": "EXPANDING_WINDOW",
        "ROLLING": "ROLLING_WINDOW",
    }.get(training_policy, training_policy)
    if training_policy not in {"EXPANDING_WINDOW", "ROLLING_WINDOW"}:
        raise Stage3SplitBalanceError(
            "SPLIT_TRAINING_POLICY_INVALID",
            "Training policy must be expanding-window or rolling-window.",
        )
    return {
        "foldCount": fold_count,
        "embargoDays": embargo_days,
        "minimumTrainingGames": minimum_training_games,
        "minimumValidationGames": minimum_validation_games,
        "seed": seed,
        "trainingPolicy": training_policy,
        "classPolicy": _class_policy(payload),
        "selectedFeatureSetIds": _selected_feature_set_ids(payload),
    }


def _automatic_contract(
    database: Database,
    authority: eda._Authority,
    frame: pd.DataFrame,
    columns: _Columns,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    config = _configuration(payload)
    game_dates = frame[[columns.game, "__game_date"]].drop_duplicates()
    warmup = game_dates.loc[
        game_dates["__game_date"].dt.year == INITIAL_TRAINING_SEASON
    ]
    validation = game_dates.loc[
        game_dates["__game_date"].dt.year >= FIRST_VALIDATION_SEASON
    ]
    if warmup.empty or validation.empty:
        raise Stage3SplitBalanceError(
            "SPLIT_AUTOMATIC_ERA_INCOMPLETE",
            "Automatic design requires complete 2023 warm-up history and validation dates beginning in 2024.",
        )
    by_date = [
        (pd.Timestamp(date_value), int(group[columns.game].nunique()))
        for date_value, group in validation.groupby("__game_date", sort=True)
    ]
    blocks = _balanced_date_blocks(by_date, config["foldCount"])
    folds: list[dict[str, Any]] = []
    for index, validation_dates in enumerate(blocks, start=1):
        validation_start = min(validation_dates)
        validation_end = max(validation_dates)
        training_cutoff = validation_start - pd.Timedelta(
            days=config["embargoDays"] + 1
        )
        if config["trainingPolicy"] == "ROLLING_WINDOW":
            rolling_start = max(
                pd.Timestamp(eda.DEVELOPMENT_START),
                validation_start - pd.Timedelta(days=365),
            )
            train_mask = frame["__game_date"].between(rolling_start, training_cutoff)
        else:
            train_mask = frame["__game_date"] <= training_cutoff
        validation_mask = frame["__game_date"].between(
            validation_start, validation_end
        )
        embargo_mask = frame["__game_date"].between(
            training_cutoff + pd.Timedelta(days=1),
            validation_start - pd.Timedelta(days=1),
        )
        fold = _fold_record(
            frame,
            columns,
            fold_number=index,
            train_mask=train_mask,
            validation_mask=validation_mask,
            embargo_mask=embargo_mask,
            class_policy=config["classPolicy"],
            selected_feature_set_ids=config["selectedFeatureSetIds"],
        )
        if fold["trainGames"] < config["minimumTrainingGames"]:
            raise Stage3SplitBalanceError(
                "SPLIT_MINIMUM_TRAINING_GAMES_NOT_MET",
                f"Fold {index} has {fold['trainGames']} training games, below the configured minimum.",
            )
        if fold["validationGames"] < config["minimumValidationGames"]:
            raise Stage3SplitBalanceError(
                "SPLIT_MINIMUM_VALIDATION_GAMES_NOT_MET",
                f"Fold {index} has {fold['validationGames']} validation games, below the configured minimum.",
            )
        folds.append(fold)
    return _design_contract(
        database,
        authority,
        frame,
        columns,
        mode="AUTOMATIC",
        folds=folds,
        class_policy=config["classPolicy"],
        selected_feature_set_ids=config["selectedFeatureSetIds"],
        embargo_days=config["embargoDays"],
        minimum_training_games=config["minimumTrainingGames"],
        minimum_validation_games=config["minimumValidationGames"],
        training_policy=config["trainingPolicy"],
        allow_gaps=False,
        seed=config["seed"],
        boundary_rule=(
            "Reserve every eligible 2023 date for initial training; divide actual "
            "canonical-game counts from the first eligible 2024 date through the "
            "development cutoff into five contiguous date-atomic validation windows."
        ),
    )


def _date_value(value: Any, field: str) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value).normalize()
    except Exception as exc:
        raise Stage3SplitBalanceError(
            "SPLIT_MANUAL_DATE_INVALID", f"{field} is not a valid date."
        ) from exc
    if pd.isna(parsed):
        raise Stage3SplitBalanceError(
            "SPLIT_MANUAL_DATE_INVALID", f"{field} is not a valid date."
        )
    return parsed


def _manual_contract(
    database: Database,
    authority: eda._Authority,
    frame: pd.DataFrame,
    columns: _Columns,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    config = _configuration(payload)
    raw_folds = payload.get("folds")
    if not isinstance(raw_folds, Sequence) or isinstance(raw_folds, (str, bytes)):
        raise Stage3SplitBalanceError(
            "SPLIT_MANUAL_FOLDS_REQUIRED", "Manual mode requires an ordered folds list."
        )
    if len(raw_folds) != config["foldCount"]:
        raise Stage3SplitBalanceError(
            "SPLIT_MANUAL_FOLD_COUNT_MISMATCH", "Manual mode requires exactly five fold definitions."
        )
    training_policy = config["trainingPolicy"]
    allow_gaps = bool(payload.get("allowGaps", False))
    represented_dates = sorted(frame["__game_date"].unique())
    represented_set = {pd.Timestamp(value) for value in represented_dates}
    normalized: list[dict[str, pd.Timestamp]] = []
    for index, raw in enumerate(raw_folds, start=1):
        if not isinstance(raw, Mapping):
            raise Stage3SplitBalanceError(
                "SPLIT_MANUAL_FOLD_INVALID", f"Fold {index} must be an object."
            )
        item = {
            "trainStart": _date_value(
                raw.get("trainStart") or raw.get("trainingStart"),
                f"fold {index} trainStart",
            ),
            "trainEnd": _date_value(
                raw.get("trainEnd") or raw.get("trainingEnd"),
                f"fold {index} trainEnd",
            ),
            "validationStart": _date_value(
                raw.get("validationStart"), f"fold {index} validationStart"
            ),
            "validationEnd": _date_value(
                raw.get("validationEnd"), f"fold {index} validationEnd"
            ),
        }
        if any(value not in represented_set for value in item.values()):
            raise Stage3SplitBalanceError(
                "SPLIT_MANUAL_BOUNDARY_NOT_REPRESENTED",
                f"Fold {index} boundaries must be actual governed development game dates.",
            )
        if item["trainStart"] > item["trainEnd"] or item["validationStart"] > item["validationEnd"]:
            raise Stage3SplitBalanceError(
                "SPLIT_MANUAL_DATE_ORDER_INVALID", f"Fold {index} has reversed date boundaries."
            )
        if item["trainEnd"] >= item["validationStart"]:
            raise Stage3SplitBalanceError(
                "SPLIT_MANUAL_TARGET_DATE_LEAKAGE", f"Fold {index} training does not precede validation."
            )
        available_gap = (item["validationStart"] - item["trainEnd"]).days - 1
        if available_gap < config["embargoDays"]:
            raise Stage3SplitBalanceError(
                "SPLIT_MANUAL_EMBARGO_VIOLATION", f"Fold {index} does not preserve the configured embargo."
            )
        if not allow_gaps:
            latest_allowed = item["validationStart"] - pd.Timedelta(
                days=config["embargoDays"] + 1
            )
            prior_game_dates = [
                pd.Timestamp(value)
                for value in represented_dates
                if pd.Timestamp(value) <= latest_allowed
            ]
            expected_train_end = max(prior_game_dates) if prior_game_dates else None
            if expected_train_end is None or item["trainEnd"] != expected_train_end:
                raise Stage3SplitBalanceError(
                    "SPLIT_MANUAL_UNDECLARED_GAP",
                    f"Fold {index} omits a governed training date beyond the configured embargo.",
                )
        normalized.append(item)
    if training_policy == "EXPANDING_WINDOW":
        starts = {item["trainStart"] for item in normalized}
        if len(starts) != 1 or next(iter(starts)) != pd.Timestamp(eda.DEVELOPMENT_START):
            raise Stage3SplitBalanceError(
                "SPLIT_MANUAL_EXPANDING_START_INVALID",
                "Every expanding fold must begin on the accepted development start date.",
            )
    for left, right in zip(normalized, normalized[1:]):
        if left["validationEnd"] >= right["validationStart"]:
            raise Stage3SplitBalanceError(
                "SPLIT_MANUAL_VALIDATION_OVERLAP", "Manual validation windows overlap or repeat a date."
            )
        if right["trainEnd"] <= left["trainEnd"]:
            raise Stage3SplitBalanceError(
                "SPLIT_MANUAL_TRAINING_NOT_EXPANDING", "Training end dates must grow monotonically."
            )
        if not allow_gaps:
            between = [
                value
                for value in represented_dates
                if pd.Timestamp(left["validationEnd"]) < pd.Timestamp(value) < pd.Timestamp(right["validationStart"])
            ]
            if between:
                raise Stage3SplitBalanceError(
                    "SPLIT_MANUAL_VALIDATION_GAP", "A governed game date is omitted between validation folds."
                )
    if not allow_gaps:
        validation_start = normalized[0]["validationStart"]
        expected_dates = {
            pd.Timestamp(value)
            for value in represented_dates
            if pd.Timestamp(value) >= validation_start
        }
        assigned_dates = {
            pd.Timestamp(value)
            for value in represented_dates
            if any(
                item["validationStart"] <= pd.Timestamp(value) <= item["validationEnd"]
                for item in normalized
            )
        }
        omitted_dates = sorted(expected_dates - assigned_dates)
        if omitted_dates:
            raise Stage3SplitBalanceError(
                "SPLIT_MANUAL_VALIDATION_COVERAGE_INCOMPLETE",
                "Manual validation omits governed dates through the development cutoff; "
                "enable explicit gaps or extend the final validation window. First omitted date: "
                + omitted_dates[0].date().isoformat(),
            )
    folds: list[dict[str, Any]] = []
    assigned_validation_games: set[str] = set()
    for index, item in enumerate(normalized, start=1):
        train_mask = frame["__game_date"].between(item["trainStart"], item["trainEnd"])
        validation_mask = frame["__game_date"].between(item["validationStart"], item["validationEnd"])
        embargo_mask = frame["__game_date"].between(
            item["trainEnd"] + pd.Timedelta(days=1),
            item["validationStart"] - pd.Timedelta(days=1),
        )
        current_games = set(frame.loc[validation_mask, columns.game].astype(str))
        if assigned_validation_games & current_games:
            raise Stage3SplitBalanceError(
                "SPLIT_MANUAL_VALIDATION_GAME_DUPLICATE", "A canonical validation game is assigned more than once."
            )
        assigned_validation_games |= current_games
        fold = _fold_record(
            frame,
            columns,
            fold_number=index,
            train_mask=train_mask,
            validation_mask=validation_mask,
            embargo_mask=embargo_mask,
            class_policy=config["classPolicy"],
            selected_feature_set_ids=config["selectedFeatureSetIds"],
        )
        if fold["trainGames"] < config["minimumTrainingGames"] or fold["validationGames"] < config["minimumValidationGames"]:
            raise Stage3SplitBalanceError(
                "SPLIT_MANUAL_MINIMUM_GAMES_NOT_MET", f"Fold {index} does not meet configured game minimums."
            )
        folds.append(fold)
    return _design_contract(
        database,
        authority,
        frame,
        columns,
        mode="MANUAL",
        folds=folds,
        class_policy=config["classPolicy"],
        selected_feature_set_ids=config["selectedFeatureSetIds"],
        embargo_days=config["embargoDays"],
        minimum_training_games=config["minimumTrainingGames"],
        minimum_validation_games=config["minimumValidationGames"],
        training_policy=training_policy,
        allow_gaps=allow_gaps,
        seed=config["seed"],
        boundary_rule="User-supplied exact governed game-date boundaries validated server-side.",
    )


def _summary_data(
    database: Database,
    authority: eda._Authority,
    frame: pd.DataFrame,
    columns: _Columns,
) -> dict[str, Any]:
    profile = _profile(frame, columns)
    default = _automatic_contract(database, authority, frame, columns, {})
    state = Stage3SplitContractRepository(database).contract_state(
        authority.project_id, authority.review_digest
    )
    return {
        "schemaVersion": SPLIT_BALANCE_SCHEMA_VERSION,
        "summary": _summary_record(profile),
        "decisionStatement": (
            "Use five expanding-window folds grouped by canonical game and calendar date; "
            "fit all preprocessing inside each training fold; preserve the natural "
            "eight-class baseball outcome distribution."
        ),
        "targetDistribution": profile["classDistribution"],
        "classBalanceBySeason": _composition(frame, "season"),
        "classBalanceByMonth": _composition(frame, "month"),
        "coldStart": profile["coldStart"],
        "physicalMissingness": profile["physicalMissingness"],
        "recommendedDesign": default,
        "folds": default["folds"],
        "qualityGates": default["qualityGates"],
        "contractState": state,
    }


def _summary_record(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "developmentRows": profile["rows"],
        "developmentGames": profile["games"],
        "developmentDates": profile["dates"],
        "developmentStart": profile["startDate"],
        "developmentEnd": profile["endDate"],
        "finalOotRows": int(eda.FINAL_OOT_ROWS),
        "finalOotStart": eda.EXPECTED_FINAL_OOT[0],
        "finalOotEnd": eda.EXPECTED_FINAL_OOT[1],
        "finalOotLocked": True,
        "folds": RECOMMENDED_FOLD_COUNT,
        "groupingUnit": "CANONICAL_GAME",
        "datePolicy": "DATE_ATOMIC",
        "trainingPolicy": "EXPANDING_WINDOW",
        "classPolicy": "NATURAL_OBSERVED_DISTRIBUTION_NO_AUTOMATIC_RESAMPLING",
    }


def split_balance_summary(project_id: str, database: Database) -> dict[str, Any]:
    authority = _resolve_authority(database, project_id)
    frame, columns = _development_frame(authority)
    return _envelope(
        authority,
        _summary_data(database, authority, frame, columns),
        rows=len(frame),
    )


def generate_automatic_split(
    project_id: str, database: Database, payload: Any
) -> dict[str, Any]:
    request = _normalize_payload(payload)
    authority = _resolve_authority(database, project_id)
    _assert_authority_key(authority, request)
    frame, columns = _development_frame(authority)
    contract = _automatic_contract(database, authority, frame, columns, request)
    return _envelope(
        authority,
        {
            "summary": _summary_record(_profile(frame, columns)),
            "targetDistribution": _profile(frame, columns)["classDistribution"],
            "recommendedDesign": contract,
            "design": contract,
            "folds": contract["folds"],
            "qualityGates": contract["qualityGates"],
            "contractState": Stage3SplitContractRepository(database).contract_state(
                project_id, authority.review_digest
            ),
        },
        rows=len(frame),
    )


def validate_manual_split(
    project_id: str, database: Database, payload: Any
) -> dict[str, Any]:
    request = _normalize_payload(payload)
    authority = _resolve_authority(database, project_id)
    _assert_authority_key(authority, request)
    frame, columns = _development_frame(authority)
    contract = _manual_contract(database, authority, frame, columns, request)
    return _envelope(
        authority,
        {
            "valid": contract["allBlockingGatesPass"],
            "summary": _summary_record(_profile(frame, columns)),
            "targetDistribution": _profile(frame, columns)["classDistribution"],
            "recommendedDesign": contract,
            "design": contract,
            "folds": contract["folds"],
            "qualityGates": contract["qualityGates"],
            "contractState": Stage3SplitContractRepository(database).contract_state(
                project_id, authority.review_digest
            ),
        },
        rows=len(frame),
    )


def split_contract_state(project_id: str, database: Database) -> dict[str, Any]:
    authority = _resolve_authority(database, project_id)
    state = Stage3SplitContractRepository(database).contract_state(
        project_id, authority.review_digest
    )
    return _envelope(
        authority,
        {"contractState": state, **state},
        rows=int(eda.DEVELOPMENT_ROWS),
    )


def save_split_draft(
    project_id: str,
    database: Database,
    payload: Any,
    actor_user_id: str,
) -> dict[str, Any]:
    request = _normalize_payload(payload)
    authority = _resolve_authority(database, project_id)
    _assert_authority_key(authority, request)
    expected_checksum = str(request.get("expectedChecksum") or "").strip()
    if not expected_checksum:
        raise Stage3SplitBalanceError(
            "SPLIT_EXPECTED_CHECKSUM_REQUIRED",
            "Saving requires the exact contractState.expectedChecksum value.",
            status_code=409,
        )
    frame, columns = _development_frame(authority)
    mode = str(request.get("mode") or "AUTOMATIC").upper()
    if mode == "AUTOMATIC":
        contract = _automatic_contract(database, authority, frame, columns, request)
    elif mode == "MANUAL":
        contract = _manual_contract(database, authority, frame, columns, request)
    else:
        raise Stage3SplitBalanceError(
            "SPLIT_MODE_INVALID", "Split mode must be AUTOMATIC or MANUAL."
        )
    try:
        saved = Stage3SplitContractRepository(database).save_draft(
            authority=_persistence_authority(authority),
            split_mode=mode,
            contract=contract,
            selected_feature_set_ids=contract["selectedFeatureSetIds"],
            notes=str(request.get("notes") or "").strip(),
            expected_checksum=expected_checksum,
            actor_user_id=actor_user_id,
        )
    except Stage3SplitContractPersistenceError as exc:
        raise Stage3SplitBalanceError(exc.code, str(exc), status_code=409) from exc
    state = Stage3SplitContractRepository(database).contract_state(
        project_id, authority.review_digest
    )
    return _envelope(
        authority,
        {"contract": saved, "contractState": state},
        rows=len(frame),
    )


def register_split_contract(
    project_id: str,
    database: Database,
    payload: Any,
    actor_user_id: str,
) -> dict[str, Any]:
    request = _normalize_payload(payload)
    authority = _resolve_authority(database, project_id)
    _assert_authority_key(authority, request)
    contract_id = str(
        request.get("contractId") or request.get("draftContractId") or ""
    ).strip()
    expected_checksum = str(request.get("expectedChecksum") or "").strip()
    if not contract_id or not expected_checksum:
        raise Stage3SplitBalanceError(
            "SPLIT_REGISTRATION_IDENTITY_REQUIRED",
            "Registration requires the exact draft contract ID and checksum.",
            status_code=409,
        )
    repository = Stage3SplitContractRepository(database)
    draft = repository.get(contract_id)
    if (
        draft is None
        or draft.get("projectId") != project_id
        or draft.get("authorityReviewDigest") != authority.review_digest
        or draft.get("status") != "DRAFT"
    ):
        raise Stage3SplitBalanceError(
            "SPLIT_DRAFT_REQUIRED",
            "The exact current authority-bound DRAFT split contract is required.",
            status_code=409,
        )
    if draft.get("checksum") != expected_checksum:
        raise Stage3SplitBalanceError(
            "SPLIT_CONTRACT_CHECKSUM_MISMATCH",
            "The draft checksum differs from the registration request.",
            status_code=409,
        )
    contract = dict(draft.get("contract") or {})
    selected_ids = list(draft.get("selectedFeatureSetIds") or [])
    feature_validation = _feature_set_validation(
        database, authority, selected_ids
    )
    blocking = [
        item
        for item in contract.get("qualityGates") or []
        if item.get("blocking") is True and item.get("status") != "PASS"
    ]
    if blocking or not contract.get("allBlockingGatesPass"):
        raise Stage3SplitBalanceError(
            "SPLIT_QUALITY_GATES_BLOCKED",
            "The draft cannot be registered because blocking split quality gates have not passed: "
            + ", ".join(str(item.get("code")) for item in blocking),
            status_code=409,
        )
    if feature_validation.get("valid") is not True:
        raise Stage3SplitBalanceError(
            "SPLIT_FEATURE_SET_AUTHORITY_BLOCKED",
            str(feature_validation.get("reason")),
            status_code=409,
        )
    try:
        registered = repository.register(
            project_id=project_id,
            authority_review_digest=authority.review_digest,
            draft_contract_id=contract_id,
            expected_checksum=expected_checksum,
            actor_user_id=actor_user_id,
        )
    except Stage3SplitContractPersistenceError as exc:
        raise Stage3SplitBalanceError(exc.code, str(exc), status_code=409) from exc
    state = repository.contract_state(project_id, authority.review_digest)
    return _envelope(
        authority,
        {"contract": registered, "contractState": state},
        rows=int(eda.DEVELOPMENT_ROWS),
    )


__all__ = [
    "NO_CURRENT_SPLIT_CONTRACT",
    "SPLIT_BALANCE_SCHEMA_VERSION",
    "SPLIT_CONTRACT_SCHEMA_VERSION",
    "Stage3SplitBalanceError",
    "configure_feature_set_validator",
    "generate_automatic_split",
    "register_split_contract",
    "save_split_draft",
    "split_balance_summary",
    "split_contract_state",
    "validate_manual_split",
]
