from __future__ import annotations

import hashlib
import math
import time
from array import array
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from server.sports_datasets.consumer import (
    ValidatedPackage,
    _validate_resolved_child,
    canonical_json_bytes,
    sha256_bytes,
    validate_package_relative_uri,
)
from server.sports_identity_bridges.consumer import ValidatedIdentityBridge
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_modeling.training import chronological_date_atomic_split

from .dynamic_contract import (
    CONTENT_SCHEMA_VERSION,
    CONTRACT_NAME,
    CONTRACT_VERSION,
    EXPECTED_SOURCE_PARTITION_COUNT,
    HALF_LIFE_GRID,
    HISTORY_INDEX_CONTENT_SCHEMA_VERSION,
    HISTORY_INDEX_DESCRIPTOR_SCHEMA_VERSION,
    HISTORY_INDEX_SCHEMA_VERSION,
    KEY_COLUMNS,
    LOG_ODDS_CLASSES,
    PRIOR_ESS_GRID,
    REFERENCE_CLASS,
    ROLES,
    SOURCE_SEASONS,
    STATE_KINDS,
    TABLE_SCHEMA_VERSION,
    TARGET_SEASONS,
    TUNING_SCHEMA_VERSION,
    dynamic_state_contract_payload,
    dynamic_state_contract_sha,
    dynamic_history_index_schema_sha,
    dynamic_history_index_schema_spec,
    dynamic_state_schema_sha,
    dynamic_state_schema_spec,
)


SOURCE_COLUMNS: tuple[str, ...] = (
    "plate_appearance_id",
    "game_id",
    "game_date",
    "season",
    "batter_id",
    "pitcher_id",
    "outcome",
    "final_available_date",
    "available_only_after_game_final",
    "future_evidence_allowed",
    "canonical_identity_resolved",
    "target_only_not_pregame_feature",
    "strict_same_game_pregame_eligible",
    "timing_risk_label",
)
TARGET_COLUMNS: tuple[str, ...] = (
    "plate_appearance_id",
    "game_id",
    "game_date",
    "season",
    "outcome",
    "batter_canonical_player_uuid",
    "pitcher_canonical_player_uuid",
)
EXPECTED_SOURCE_ROWS = 913_349
EXPECTED_TARGET_ROWS = 549_479
_CLASS_INDEX = {class_name: index for index, class_name in enumerate(PA_CLASS_ORDER)}
_REFERENCE_INDEX = _CLASS_INDEX[REFERENCE_CLASS]
_LOG_ODDS_INDEX = tuple(_CLASS_INDEX[class_name] for class_name in LOG_ODDS_CLASSES)
_PROBABILITY_FLOOR = 1e-12
_BATCH_ROWS = 24_000
_MAX_SNAPSHOT_CACHE_ROWS = 250_000


class DynamicStateIntegrityError(RuntimeError):
    """Raised when event-level state would violate an immutable authority or timing rule."""


@dataclass(frozen=True)
class FrozenDynamicPolicy:
    half_life_days: int | None
    prior_ess: int
    policy_id: str

    @classmethod
    def create(cls, *, half_life_days: int | None, prior_ess: int) -> "FrozenDynamicPolicy":
        if half_life_days not in HALF_LIFE_GRID:
            raise DynamicStateIntegrityError("dynamic half-life is outside the frozen grid")
        if prior_ess not in PRIOR_ESS_GRID:
            raise DynamicStateIntegrityError("dynamic prior ESS is outside the frozen grid")
        core = {
            "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_POLICY_IDENTITY_V1",
            "contractSha": dynamic_state_contract_sha(),
            "halfLifeDays": half_life_days,
            "priorEffectiveSampleSize": prior_ess,
        }
        return cls(
            half_life_days=half_life_days,
            prior_ess=prior_ess,
            policy_id="mlb-dynamic-player-state-policy:sha256:"
            + sha256_bytes(canonical_json_bytes(core)),
        )

    def public(self) -> dict[str, Any]:
        return {
            "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_POLICY_V1",
            "policyId": self.policy_id,
            "halfLifeDays": self.half_life_days,
            "priorEffectiveSampleSize": self.prior_ess,
            "availabilityPredicate": "source.final_available_date < target.game_date",
            "sameDateExcluded": True,
        }


@dataclass(frozen=True)
class DynamicPolicyTuning:
    policy: FrozenDynamicPolicy
    split_evidence: dict[str, Any]
    candidates: tuple[dict[str, Any], ...]

    def public(self) -> dict[str, Any]:
        return {
            "schemaVersion": TUNING_SCHEMA_VERSION,
            "objective": "MEAN_BATTER_PITCHER_POSTERIOR_PREDICTIVE_LOG_LOSS",
            "split": dict(self.split_evidence),
            "selectedPolicy": self.policy.public(),
            "candidates": [dict(item) for item in self.candidates],
            "selectionUses2024Or2025": False,
        }


@dataclass(frozen=True)
class _PlayerHistory:
    availability_ordinals: np.ndarray
    seasons: np.ndarray
    outcomes: np.ndarray
    prefix_counts: np.ndarray

    @classmethod
    def from_buffers(
        cls,
        availability_ordinals: array,
        seasons: array,
        outcomes: array,
    ) -> "_PlayerHistory":
        dates = np.asarray(availability_ordinals, dtype=np.int32)
        source_seasons = np.asarray(seasons, dtype=np.int16)
        classes = np.asarray(outcomes, dtype=np.int8)
        order = np.lexsort((classes, source_seasons, dates))
        dates = dates[order]
        source_seasons = source_seasons[order]
        classes = classes[order]
        prefix = np.zeros((classes.size + 1, len(PA_CLASS_ORDER)), dtype=np.float64)
        if classes.size:
            increments = np.zeros((classes.size, len(PA_CLASS_ORDER)), dtype=np.float64)
            increments[np.arange(classes.size), classes] = 1.0
            prefix[1:] = np.cumsum(increments, axis=0)
        return cls(dates, source_seasons, classes, prefix)


@dataclass(frozen=True)
class _StateSnapshot:
    probabilities: np.ndarray
    effective_sample_size: float
    entropy: float
    days_since_evidence: int | None
    window_counts: tuple[int, int, int]
    missing_history: bool
    eligible_event_count: int
    long_term_event_count: int
    recent_event_count: int
    recent_effective_count: float
    overlap_event_count: int
    last_evidence_date: str | None
    evidence_cutoff_exclusive: str


@dataclass(frozen=True)
class HistoricalOutcomeIndex:
    histories: dict[str, dict[str, _PlayerHistory]]
    source_row_count: int
    source_partition_ids: tuple[str, ...]
    resolved_reference_count: int
    unresolved_reference_count: int
    ambiguous_reference_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "_league_cache", {})
        object.__setattr__(self, "_snapshot_cache", {})

    def _league_probabilities(self, role: str, season: int) -> np.ndarray:
        cache: dict[tuple[str, int], np.ndarray] = getattr(self, "_league_cache")
        key = (role, season)
        cached = cache.get(key)
        if cached is not None:
            return cached
        cutoff = date(season, 1, 1).toordinal()
        counts = np.ones(len(PA_CLASS_ORDER), dtype=np.float64)
        for history in self.histories[role].values():
            index = int(np.searchsorted(history.availability_ordinals, cutoff, side="left"))
            counts += history.prefix_counts[index]
        probabilities = counts / counts.sum()
        probabilities.setflags(write=False)
        cache[key] = probabilities
        return probabilities

    def snapshot(
        self,
        *,
        role: str,
        canonical_player_uuid: str,
        target_game_date: str,
        target_season: int,
        state_kind: str,
        policy: FrozenDynamicPolicy,
    ) -> _StateSnapshot:
        if role not in ROLES or state_kind not in STATE_KINDS or target_season not in TARGET_SEASONS:
            raise DynamicStateIntegrityError("dynamic state key is outside the frozen domain")
        try:
            target = date.fromisoformat(target_game_date)
        except (TypeError, ValueError) as exc:
            raise DynamicStateIntegrityError("target game_date must be strict ISO date") from exc
        if target.year != target_season:
            raise DynamicStateIntegrityError("target game_date and season differ")
        cache: dict[tuple[Any, ...], _StateSnapshot] = getattr(self, "_snapshot_cache")
        cache_key = (
            role,
            canonical_player_uuid,
            target_game_date,
            target_season,
            state_kind,
            policy.policy_id,
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        history = self.histories[role].get(canonical_player_uuid)
        if history is None:
            history = _PlayerHistory.from_buffers(array("i"), array("h"), array("b"))
        target_ordinal = target.toordinal()
        preseason_ordinal = date(target_season, 1, 1).toordinal()
        target_index = int(
            np.searchsorted(history.availability_ordinals, target_ordinal, side="left")
        )
        preseason_index = int(
            np.searchsorted(history.availability_ordinals, preseason_ordinal, side="left")
        )
        league = self._league_probabilities(role, target_season)

        if state_kind == "A_PRESEASON":
            evidence_index = preseason_index
            actual_counts = history.prefix_counts[evidence_index].copy()
            long_term_count = evidence_index
            recent_count = 0
            recent_effective = 0.0
            anchor_ordinal = preseason_ordinal
        elif state_kind == "B_CUMULATIVE":
            evidence_index = target_index
            actual_counts = history.prefix_counts[evidence_index].copy()
            long_term_count = evidence_index
            recent_count = 0
            recent_effective = 0.0
            anchor_ordinal = target_ordinal
        else:
            evidence_index = target_index
            eligible_seasons = history.seasons[:evidence_index]
            eligible_outcomes = history.outcomes[:evidence_index]
            eligible_dates = history.availability_ordinals[:evidence_index]
            long_mask = eligible_seasons <= target_season - 2
            recent_mask = np.isin(eligible_seasons, (target_season - 1, target_season))
            overlap = long_mask & recent_mask
            if np.any(overlap) or int(long_mask.sum() + recent_mask.sum()) != evidence_index:
                raise DynamicStateIntegrityError(
                    "recency long-term and recent evidence do not form an exact nonoverlapping partition"
                )
            long_counts = np.bincount(
                eligible_outcomes[long_mask], minlength=len(PA_CLASS_ORDER)
            ).astype(np.float64)
            recent_outcomes = eligible_outcomes[recent_mask]
            recent_dates = eligible_dates[recent_mask]
            if policy.half_life_days is None:
                weights = np.ones(recent_outcomes.size, dtype=np.float64)
            else:
                ages = target_ordinal - recent_dates.astype(np.int64)
                if np.any(ages <= 0):
                    raise DynamicStateIntegrityError("same-date or future outcome entered recency state")
                weights = np.exp(-math.log(2.0) * ages / float(policy.half_life_days))
            recent_counts = np.bincount(
                recent_outcomes,
                weights=weights,
                minlength=len(PA_CLASS_ORDER),
            ).astype(np.float64)
            actual_counts = long_counts + recent_counts
            long_term_count = int(long_mask.sum())
            recent_count = int(recent_mask.sum())
            recent_effective = float(weights.sum())
            anchor_ordinal = target_ordinal

        posterior_counts = actual_counts + float(policy.prior_ess) * league
        effective_sample_size = float(posterior_counts.sum())
        if not math.isfinite(effective_sample_size) or effective_sample_size <= 0.0:
            raise DynamicStateIntegrityError("dynamic posterior has invalid effective sample size")
        probabilities = posterior_counts / effective_sample_size
        if (
            probabilities.shape != (len(PA_CLASS_ORDER),)
            or not np.isfinite(probabilities).all()
            or np.any(probabilities <= 0.0)
            or not math.isclose(float(probabilities.sum()), 1.0, rel_tol=0.0, abs_tol=1e-12)
        ):
            raise DynamicStateIntegrityError("dynamic posterior probabilities are invalid")

        evidence_dates = history.availability_ordinals[:evidence_index]
        if evidence_index:
            last_ordinal = int(evidence_dates[-1])
            last_evidence_date = date.fromordinal(last_ordinal).isoformat()
            days_since = anchor_ordinal - last_ordinal
            if days_since <= 0:
                raise DynamicStateIntegrityError("dynamic evidence is not strictly prior-date")
        else:
            last_evidence_date = None
            days_since = None
        window_counts = tuple(
            int(np.count_nonzero((anchor_ordinal - evidence_dates > 0) & (anchor_ordinal - evidence_dates <= days)))
            for days in (7, 30, 90)
        )
        entropy = float(-np.sum(probabilities * np.log(probabilities)))
        snapshot = _StateSnapshot(
            probabilities=probabilities,
            effective_sample_size=effective_sample_size,
            entropy=entropy,
            days_since_evidence=days_since,
            window_counts=window_counts,
            missing_history=evidence_index == 0,
            eligible_event_count=evidence_index,
            long_term_event_count=long_term_count,
            recent_event_count=recent_count,
            recent_effective_count=recent_effective,
            overlap_event_count=0,
            last_evidence_date=last_evidence_date,
            evidence_cutoff_exclusive=(
                date(target_season, 1, 1).isoformat()
                if state_kind == "A_PRESEASON"
                else target_game_date
            ),
        )
        # Tuning and full materialization visit millions of role/date/policy keys.  The
        # cache is only an optimization, so bound it without changing deterministic
        # values or traversal order.
        if len(cache) >= _MAX_SNAPSHOT_CACHE_ROWS:
            cache.clear()
        cache[cache_key] = snapshot
        return snapshot


@dataclass(frozen=True)
class BuiltDynamicPlayerState:
    table: pa.Table
    contract: dict[str, Any]
    contract_sha: str
    schema_spec: dict[str, Any]
    schema_sha: str
    content_sha: str
    parquet_bytes: bytes
    policy: FrozenDynamicPolicy
    tuning: DynamicPolicyTuning
    posterior_predictive: dict[str, Any]
    season_rows: dict[int, int]
    source_partition_ids: tuple[str, ...]
    source_row_count: int
    resolved_reference_count: int

    @property
    def row_count(self) -> int:
        return self.table.num_rows


@dataclass(frozen=True)
class BuiltHistoricalDynamicIndex:
    table: pa.Table
    schema_spec: dict[str, Any]
    schema_sha: str
    content_sha: str
    parquet_bytes: bytes
    source_partition_ids: tuple[str, ...]
    source_row_count: int
    resolved_reference_count: int

    @property
    def row_count(self) -> int:
        return self.table.num_rows


@dataclass
class _HistoryBuffers:
    dates: array
    seasons: array
    outcomes: array

    @classmethod
    def create(cls) -> "_HistoryBuffers":
        return cls(array("i"), array("h"), array("b"))


class HistoricalOutcomeAccumulator:
    def __init__(
        self,
        *,
        alias_rows: Sequence[Mapping[str, Any]] | Mapping[str, str],
        dimension_uuids: frozenset[str],
        source_partition_ids: Sequence[str] = (),
        progress: Any | None = None,
    ) -> None:
        self.aliases = exact_retrosheet_alias_map(alias_rows, dimension_uuids)
        self.dimension_uuids = dimension_uuids
        self.source_partition_ids = tuple(sorted(str(value) for value in source_partition_ids))
        self.progress = progress
        self._buffers: dict[str, dict[str, _HistoryBuffers]] = {
            role: defaultdict(_HistoryBuffers.create) for role in ROLES
        }
        self._seen_pa_ids: set[str] = set()
        self.source_row_count = 0
        self.resolved_reference_count = 0
        self.started = time.monotonic()
        self.last_emit = self.started

    def add_table(self, table: pa.Table) -> None:
        if not isinstance(table, pa.Table):
            raise TypeError("historical plate-appearance input must be a pyarrow Table")
        missing = [column for column in SOURCE_COLUMNS if column not in table.column_names]
        if missing:
            raise DynamicStateIntegrityError(
                f"historical plate-appearance schema is missing required fields: {missing}"
            )
        values = table.select(SOURCE_COLUMNS).to_pydict()
        for index in range(table.num_rows):
            pa_id = values["plate_appearance_id"][index]
            game_id = values["game_id"][index]
            game_date = values["game_date"][index]
            final_date = values["final_available_date"][index]
            season = values["season"][index]
            outcome = values["outcome"][index]
            if (
                not isinstance(pa_id, str)
                or not pa_id
                or pa_id in self._seen_pa_ids
                or not isinstance(game_id, str)
                or not game_id
            ):
                raise DynamicStateIntegrityError("historical plate-appearance lineage is blank or duplicated")
            self._seen_pa_ids.add(pa_id)
            if not isinstance(season, int) or season not in SOURCE_SEASONS:
                raise DynamicStateIntegrityError("historical plate-appearance season is outside 2021-2025")
            try:
                parsed_game_date = date.fromisoformat(game_date)
                parsed_final_date = date.fromisoformat(final_date)
            except (TypeError, ValueError) as exc:
                raise DynamicStateIntegrityError(
                    "historical game/final availability dates must be strict ISO dates"
                ) from exc
            if parsed_game_date.year != season or parsed_final_date < parsed_game_date:
                raise DynamicStateIntegrityError("historical final availability precedes its game date")
            if outcome not in _CLASS_INDEX:
                raise DynamicStateIntegrityError("historical outcome is outside the immutable class order")
            if (
                values["available_only_after_game_final"][index] is not True
                or values["future_evidence_allowed"][index] is not False
                or values["canonical_identity_resolved"][index] is not False
                or values["target_only_not_pregame_feature"][index] is not True
                or values["strict_same_game_pregame_eligible"][index] is not False
                or values["timing_risk_label"][index]
                != "RETROSPECTIVE_EVENT_OUTCOME_TIMING_RISK"
            ):
                raise DynamicStateIntegrityError(
                    "historical outcome timing flags differ from the registered retrospective contract"
                )
            final_ordinal = parsed_final_date.toordinal()
            class_index = _CLASS_INDEX[outcome]
            for role, field in (("BATTER", "batter_id"), ("PITCHER", "pitcher_id")):
                source_id = values[field][index]
                canonical_uuid = self.aliases.get(source_id)
                if canonical_uuid is None or canonical_uuid not in self.dimension_uuids:
                    raise DynamicStateIntegrityError(
                        f"historical {role.casefold()} identity is unresolved through the exact bridge"
                    )
                buffer = self._buffers[role][canonical_uuid]
                buffer.dates.append(final_ordinal)
                buffer.seasons.append(season)
                buffer.outcomes.append(class_index)
                self.resolved_reference_count += 1
            self.source_row_count += 1
            now = time.monotonic()
            if (
                self.progress is not None
                and (
                    self.source_row_count == 1
                    or self.source_row_count % 50_000 == 0
                    or now - self.last_emit >= 30.0
                )
            ):
                _emit(
                    self.progress,
                    "READING_DYNAMIC_HISTORY",
                    {
                        "rowsProcessed": self.source_row_count,
                        "referencesProcessed": self.resolved_reference_count,
                        "elapsedSeconds": round(now - self.started, 2),
                        "errors": 0,
                    },
                )
                self.last_emit = now

    def finish(self) -> HistoricalOutcomeIndex:
        histories = {
            role: {
                canonical_uuid: _PlayerHistory.from_buffers(
                    buffers.dates,
                    buffers.seasons,
                    buffers.outcomes,
                )
                for canonical_uuid, buffers in sorted(self._buffers[role].items())
            }
            for role in ROLES
        }
        return HistoricalOutcomeIndex(
            histories=histories,
            source_row_count=self.source_row_count,
            source_partition_ids=self.source_partition_ids,
            resolved_reference_count=self.resolved_reference_count,
            unresolved_reference_count=0,
            ambiguous_reference_count=0,
        )


def exact_retrosheet_alias_map(
    alias_rows: Sequence[Mapping[str, Any]] | Mapping[str, str],
    dimension_uuids: frozenset[str],
) -> dict[str, str]:
    if not isinstance(dimension_uuids, frozenset) or not dimension_uuids:
        raise DynamicStateIntegrityError("exact bridge dimension authority is required")
    if isinstance(alias_rows, Mapping):
        candidates: Iterable[tuple[Any, Any]] = alias_rows.items()
    else:
        candidates = (
            (row.get("parent_join_key"), row.get("canonical_player_uuid"))
            for row in alias_rows
            if row.get("namespace") == "RETROSHEET"
        )
    aliases: dict[str, str] = {}
    for raw_source, raw_uuid in candidates:
        if (
            not isinstance(raw_source, str)
            or not raw_source
            or not isinstance(raw_uuid, str)
            or raw_uuid not in dimension_uuids
        ):
            raise DynamicStateIntegrityError("RETROSHEET alias row is blank or outside the dimension")
        if raw_source in aliases:
            raise DynamicStateIntegrityError("RETROSHEET alias source is ambiguous or duplicated")
        aliases[raw_source] = raw_uuid
    if not aliases:
        raise DynamicStateIntegrityError("a non-empty exact RETROSHEET alias authority is required")
    return aliases


def build_historical_outcome_index(
    plate_appearance_tables: Sequence[pa.Table],
    *,
    alias_rows: Sequence[Mapping[str, Any]] | Mapping[str, str],
    dimension_uuids: frozenset[str],
    source_partition_ids: Sequence[str] = (),
    progress: Any | None = None,
) -> HistoricalOutcomeIndex:
    if not plate_appearance_tables:
        raise DynamicStateIntegrityError("historical plate-appearance partitions are required")
    accumulator = HistoricalOutcomeAccumulator(
        alias_rows=alias_rows,
        dimension_uuids=dimension_uuids,
        source_partition_ids=source_partition_ids,
        progress=progress,
    )
    for table in plate_appearance_tables:
        accumulator.add_table(table)
    return accumulator.finish()


def _validate_target_table(table: pa.Table, *, expected_rows: int | None) -> dict[str, list[Any]]:
    if not isinstance(table, pa.Table) or table.num_rows == 0:
        raise DynamicStateIntegrityError("Phase 3 target feature view must be non-empty")
    missing = [column for column in TARGET_COLUMNS if column not in table.column_names]
    if missing:
        raise DynamicStateIntegrityError(f"Phase 3 target feature view is missing fields: {missing}")
    if expected_rows is not None and table.num_rows != expected_rows:
        raise DynamicStateIntegrityError("Phase 3 target feature-view row count differs")
    values = table.select(TARGET_COLUMNS).to_pydict()
    seen: set[str] = set()
    for index in range(table.num_rows):
        pa_id = values["plate_appearance_id"][index]
        game_id = values["game_id"][index]
        game_date = values["game_date"][index]
        season = values["season"][index]
        outcome = values["outcome"][index]
        if (
            not isinstance(pa_id, str)
            or not pa_id
            or pa_id in seen
            or not isinstance(game_id, str)
            or not game_id
            or not isinstance(game_date, str)
            or not isinstance(season, int)
            or season not in TARGET_SEASONS
            or not game_date.startswith(f"{season:04d}-")
            or outcome not in _CLASS_INDEX
        ):
            raise DynamicStateIntegrityError("Phase 3 target lineage or class authority differs")
        seen.add(pa_id)
        for field in ("batter_canonical_player_uuid", "pitcher_canonical_player_uuid"):
            if not isinstance(values[field][index], str) or not values[field][index]:
                raise DynamicStateIntegrityError("Phase 3 target canonical player UUID is blank")
    return values


def tune_dynamic_policy(
    target_feature_view: pa.Table,
    history: HistoricalOutcomeIndex,
    *,
    progress: Any | None = None,
) -> DynamicPolicyTuning:
    values = _validate_target_table(target_feature_view, expected_rows=None)
    seasons = np.asarray(values["season"], dtype=np.int16)
    dates = np.asarray(values["game_date"], dtype=object)
    season_mask = seasons == 2023
    if not np.any(season_mask):
        raise DynamicStateIntegrityError("inner-2023 tuning requires 2023 target rows")
    _inner_train, inner_validation, split = chronological_date_atomic_split(
        dates,
        season_mask,
    )
    validation_indices = np.flatnonzero(inner_validation)
    objective_by_policy: list[dict[str, Any]] = []
    started = time.monotonic()
    processed = 0
    last_emit = started
    for half_life_ordinal, half_life in enumerate(HALF_LIFE_GRID):
        totals = {prior_ess: 0.0 for prior_ess in PRIOR_ESS_GRID}
        observations = 0
        for index in validation_indices:
            class_index = _CLASS_INDEX[str(values["outcome"][index])]
            target_date = str(values["game_date"][index])
            for role, field in (
                ("BATTER", "batter_canonical_player_uuid"),
                ("PITCHER", "pitcher_canonical_player_uuid"),
            ):
                player_uuid = str(values[field][index])
                for prior_ess in PRIOR_ESS_GRID:
                    policy = FrozenDynamicPolicy.create(
                        half_life_days=half_life,
                        prior_ess=prior_ess,
                    )
                    snapshot = history.snapshot(
                        role=role,
                        canonical_player_uuid=player_uuid,
                        target_game_date=target_date,
                        target_season=2023,
                        state_kind="C_RECENCY",
                        policy=policy,
                    )
                    totals[prior_ess] -= math.log(
                        max(float(snapshot.probabilities[class_index]), _PROBABILITY_FLOOR)
                    )
                observations += 1
            processed += 1
            now = time.monotonic()
            if progress is not None and (
                processed == 1 or processed % 25_000 == 0 or now - last_emit >= 30.0
            ):
                _emit(
                    progress,
                    "TUNING_DYNAMIC_STATE",
                    {
                        "rowsProcessed": processed,
                        "rowsTotal": int(validation_indices.size * len(HALF_LIFE_GRID)),
                        "halfLifeDays": half_life,
                        "elapsedSeconds": round(now - started, 2),
                        "errors": 0,
                    },
                )
                last_emit = now
        for prior_ess in PRIOR_ESS_GRID:
            policy = FrozenDynamicPolicy.create(
                half_life_days=half_life,
                prior_ess=prior_ess,
            )
            objective_by_policy.append(
                {
                    "policyId": policy.policy_id,
                    "halfLifeDays": half_life,
                    "halfLifeGridOrdinal": half_life_ordinal,
                    "priorEffectiveSampleSize": prior_ess,
                    "validationRows": int(validation_indices.size),
                    "roleObservations": observations,
                    "posteriorPredictiveLogLoss": float(totals[prior_ess] / observations),
                }
            )
    selected = min(
        objective_by_policy,
        key=lambda item: (
            item["posteriorPredictiveLogLoss"],
            item["priorEffectiveSampleSize"],
            item["halfLifeGridOrdinal"],
        ),
    )
    return DynamicPolicyTuning(
        policy=FrozenDynamicPolicy.create(
            half_life_days=selected["halfLifeDays"],
            prior_ess=selected["priorEffectiveSampleSize"],
        ),
        split_evidence=split,
        candidates=tuple(objective_by_policy),
    )


def evaluate_frozen_dynamic_state_posteriors(
    target_feature_view: pa.Table,
    history: HistoricalOutcomeIndex,
    *,
    policy: FrozenDynamicPolicy,
    progress: Any | None = None,
) -> dict[str, Any]:
    """Score every frozen role/state representation without influencing selection."""

    values = _validate_target_table(target_feature_view, expected_rows=None)
    totals: dict[tuple[str, str, int], list[float | int]] = {
        (role, state_kind, season): [0, 0.0, 0.0]
        for role in ROLES
        for state_kind in STATE_KINDS
        for season in (2024, 2025)
    }
    target_indices = [
        index
        for index, season in enumerate(values["season"])
        if season in (2024, 2025)
    ]
    if not target_indices or {int(values["season"][index]) for index in target_indices} != {
        2024,
        2025,
    }:
        raise DynamicStateIntegrityError(
            "frozen posterior-predictive evaluation requires 2024 and 2025 targets"
        )
    started = time.monotonic()
    last_emit = started
    for ordinal, index in enumerate(target_indices, start=1):
        season = int(values["season"][index])
        game_date = str(values["game_date"][index])
        class_index = _CLASS_INDEX[str(values["outcome"][index])]
        for role, field in (
            ("BATTER", "batter_canonical_player_uuid"),
            ("PITCHER", "pitcher_canonical_player_uuid"),
        ):
            player_uuid = str(values[field][index])
            for state_kind in STATE_KINDS:
                snapshot = history.snapshot(
                    role=role,
                    canonical_player_uuid=player_uuid,
                    target_game_date=game_date,
                    target_season=season,
                    state_kind=state_kind,
                    policy=policy,
                )
                probabilities = snapshot.probabilities
                realized_probability = float(probabilities[class_index])
                selected = max(realized_probability, _PROBABILITY_FLOOR)
                brier = float(
                    np.square(probabilities).sum() - 2.0 * realized_probability + 1.0
                )
                accumulator = totals[(role, state_kind, season)]
                accumulator[0] = int(accumulator[0]) + 1
                accumulator[1] = float(accumulator[1]) - math.log(selected)
                accumulator[2] = float(accumulator[2]) + brier
        now = time.monotonic()
        if progress is not None and (
            ordinal == 1
            or ordinal % 25_000 == 0
            or ordinal == len(target_indices)
            or now - last_emit >= 30.0
        ):
            _emit(
                progress,
                "EVALUATING_FROZEN_DYNAMIC_STATE_POSTERIORS",
                {
                    "rowsProcessed": ordinal,
                    "rowsTotal": len(target_indices),
                    "currentSeason": season,
                    "policyId": policy.policy_id,
                    "selectionUses2024Or2025": False,
                    "elapsedSeconds": round(now - started, 2),
                    "errors": 0,
                },
            )
            last_emit = now
    rows: list[dict[str, Any]] = []
    for role in ROLES:
        for state_kind in STATE_KINDS:
            for season in (2024, 2025):
                count, loss_sum, brier_sum = totals[(role, state_kind, season)]
                if not isinstance(count, int) or count <= 0:
                    raise DynamicStateIntegrityError(
                        "frozen posterior-predictive fold is empty"
                    )
                rows.append(
                    {
                        "role": role,
                        "stateKind": state_kind,
                        "validationSeason": season,
                        "rowCount": count,
                        "logLoss": float(loss_sum) / count,
                        "brierScore": float(brier_sum) / count,
                        "brierDefinition": "MEAN_SUMMED_ONE_VS_ALL_SQUARED_ERROR",
                    }
                )
    return {
        "schemaVersion": "MLB_DYNAMIC_STATE_POSTERIOR_PREDICTIVE_EVIDENCE_V1",
        "policyId": policy.policy_id,
        "policyFrozenBeforeEvaluation": True,
        "selectionUses2024Or2025": False,
        "probabilitySource": "FROZEN_ROLE_STATE_POSTERIOR",
        "classOrder": list(PA_CLASS_ORDER),
        "byRoleStateFold": rows,
    }


def _arrow_schema(*, metadata: Mapping[bytes, bytes] | None = None) -> pa.Schema:
    fields = [
        pa.field("stateRowId", pa.string(), nullable=False),
        pa.field("rowContentSha", pa.string(), nullable=False),
        pa.field("game_date", pa.string(), nullable=False),
        pa.field("season", pa.int16(), nullable=False),
        pa.field("canonical_player_uuid", pa.string(), nullable=False),
        pa.field("role", pa.string(), nullable=False),
        pa.field("state_kind", pa.string(), nullable=False),
        pa.field("policy_id", pa.string(), nullable=False),
    ]
    fields.extend(
        pa.field(f"log_odds_{class_name.casefold()}", pa.float64(), nullable=False)
        for class_name in LOG_ODDS_CLASSES
    )
    fields.extend(
        [
            pa.field("effective_sample_size", pa.float64(), nullable=False),
            pa.field("entropy", pa.float64(), nullable=False),
            pa.field("days_since_evidence", pa.int32(), nullable=True),
            pa.field("count_7d", pa.int32(), nullable=False),
            pa.field("count_30d", pa.int32(), nullable=False),
            pa.field("count_90d", pa.int32(), nullable=False),
            pa.field("missing_history", pa.bool_(), nullable=False),
            pa.field("eligible_event_count", pa.int32(), nullable=False),
            pa.field("long_term_event_count", pa.int32(), nullable=False),
            pa.field("recent_event_count", pa.int32(), nullable=False),
            pa.field("recent_effective_count", pa.float64(), nullable=False),
            pa.field("overlap_event_count", pa.int32(), nullable=False),
            pa.field("last_evidence_date", pa.string(), nullable=True),
            pa.field("evidence_cutoff_exclusive", pa.string(), nullable=False),
        ]
    )
    return pa.schema(fields, metadata=metadata)


def _semantic_state_row(
    *,
    game_date: str,
    season: int,
    canonical_player_uuid: str,
    role: str,
    state_kind: str,
    policy: FrozenDynamicPolicy,
    snapshot: _StateSnapshot,
) -> dict[str, Any]:
    reference_probability = max(
        float(snapshot.probabilities[_REFERENCE_INDEX]),
        _PROBABILITY_FLOOR,
    )
    row: dict[str, Any] = {
        "game_date": game_date,
        "season": season,
        "canonical_player_uuid": canonical_player_uuid,
        "role": role,
        "state_kind": state_kind,
        "policy_id": policy.policy_id,
    }
    for class_name, class_index in zip(LOG_ODDS_CLASSES, _LOG_ODDS_INDEX, strict=True):
        row[f"log_odds_{class_name.casefold()}"] = math.log(
            max(float(snapshot.probabilities[class_index]), _PROBABILITY_FLOOR)
            / reference_probability
        )
    row.update(
        {
            "effective_sample_size": snapshot.effective_sample_size,
            "entropy": snapshot.entropy,
            "days_since_evidence": snapshot.days_since_evidence,
            "count_7d": snapshot.window_counts[0],
            "count_30d": snapshot.window_counts[1],
            "count_90d": snapshot.window_counts[2],
            "missing_history": snapshot.missing_history,
            "eligible_event_count": snapshot.eligible_event_count,
            "long_term_event_count": snapshot.long_term_event_count,
            "recent_event_count": snapshot.recent_event_count,
            "recent_effective_count": snapshot.recent_effective_count,
            "overlap_event_count": snapshot.overlap_event_count,
            "last_evidence_date": snapshot.last_evidence_date,
            "evidence_cutoff_exclusive": snapshot.evidence_cutoff_exclusive,
        }
    )
    natural_key = {name: row[name] for name in KEY_COLUMNS}
    state_row_id = "mlb-dynamic-player-state-row:sha256:" + sha256_bytes(
        canonical_json_bytes(
            {
                "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_ROW_IDENTITY_V1",
                "contractSha": dynamic_state_contract_sha(),
                "naturalKey": natural_key,
            }
        )
    )
    row_content_sha = sha256_bytes(canonical_json_bytes(row))
    return {"stateRowId": state_row_id, "rowContentSha": row_content_sha, **row}


def _logical_content_sha(table: pa.Table, *, policy: FrozenDynamicPolicy) -> str:
    digest = hashlib.sha256()
    digest.update(
        canonical_json_bytes(
            {
                "schemaVersion": CONTENT_SCHEMA_VERSION,
                "contractSha": dynamic_state_contract_sha(),
                "schemaSha": dynamic_state_schema_sha(),
                "policyId": policy.policy_id,
                "rowCount": table.num_rows,
            }
        )
    )
    # Arrow IPC bytes retain physical chunk boundaries and buffer layout.  A
    # Parquet round trip therefore changes the stream even when every semantic
    # value is identical (the live state is built in 24k batches but read back
    # in 65,536-row Parquet groups).  Rebuild fixed-size batches from Python
    # values so the digest is a function of ordered values and the frozen
    # schema, independent of the input table's physical representation.
    canonical_schema = table.schema.remove_metadata()
    for offset in range(0, table.num_rows, _BATCH_ROWS):
        window = table.slice(offset, min(_BATCH_ROWS, table.num_rows - offset))
        batch = pa.RecordBatch.from_pydict(
            window.to_pydict(),
            schema=canonical_schema,
        )
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, canonical_schema) as writer:
            writer.write_batch(batch)
        digest.update(sink.getvalue().to_pybytes())
    return digest.hexdigest()


def validate_dynamic_state_table(
    table: pa.Table,
    *,
    policy: FrozenDynamicPolicy,
) -> None:
    """Validate the normalized table at the semantic row boundary.

    This deliberately recomputes both identities instead of trusting Parquet metadata.
    Downstream training therefore binds to the same semantic state rows that were
    materialized, even when the input came from a reused checkpoint.
    """

    expected_schema = _arrow_schema()
    if not isinstance(table, pa.Table) or table.num_rows == 0:
        raise DynamicStateIntegrityError("dynamic state table must be non-empty")
    if table.schema.remove_metadata() != expected_schema:
        raise DynamicStateIntegrityError("dynamic state table schema differs from the contract")
    distinct_ids = pc.count_distinct(table["stateRowId"]).as_py()
    if distinct_ids != table.num_rows:
        raise DynamicStateIntegrityError("dynamic state row identity is duplicated")
    for batch in table.to_batches(max_chunksize=65_536):
        for row in batch.to_pylist():
            if row["policy_id"] != policy.policy_id:
                raise DynamicStateIntegrityError("dynamic state row uses an unfrozen policy")
            if row["role"] not in ROLES or row["state_kind"] not in STATE_KINDS:
                raise DynamicStateIntegrityError("dynamic state row key is outside the frozen domain")
            semantic = dict(row)
            observed_row_id = semantic.pop("stateRowId")
            observed_content_sha = semantic.pop("rowContentSha")
            expected_content_sha = sha256_bytes(canonical_json_bytes(semantic))
            expected_row_id = "mlb-dynamic-player-state-row:sha256:" + sha256_bytes(
                canonical_json_bytes(
                    {
                        "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_ROW_IDENTITY_V1",
                        "contractSha": dynamic_state_contract_sha(),
                        "naturalKey": {name: row[name] for name in KEY_COLUMNS},
                    }
                )
            )
            if observed_content_sha != expected_content_sha or observed_row_id != expected_row_id:
                raise DynamicStateIntegrityError("dynamic state row identity or checksum differs")


def dynamic_state_table_content_sha(
    table: pa.Table,
    *,
    policy: FrozenDynamicPolicy,
) -> str:
    validate_dynamic_state_table(table, policy=policy)
    return _logical_content_sha(table, policy=policy)


def _history_arrow_schema(*, metadata: Mapping[bytes, bytes] | None = None) -> pa.Schema:
    fields = [
        pa.field("historyRowId", pa.string(), nullable=False),
        pa.field("rowContentSha", pa.string(), nullable=False),
        pa.field("canonical_player_uuid", pa.string(), nullable=False),
        pa.field("role", pa.string(), nullable=False),
        pa.field("final_available_date", pa.string(), nullable=False),
        pa.field("source_season", pa.int16(), nullable=False),
    ]
    fields.extend(
        pa.field(f"count_{class_name.casefold()}", pa.int32(), nullable=False)
        for class_name in PA_CLASS_ORDER
    )
    return pa.schema(fields, metadata=metadata)


def _history_semantic_row(
    *,
    canonical_player_uuid: str,
    role: str,
    final_available_date: str,
    source_season: int,
    counts: np.ndarray,
) -> dict[str, Any]:
    semantic: dict[str, Any] = {
        "canonical_player_uuid": canonical_player_uuid,
        "role": role,
        "final_available_date": final_available_date,
        "source_season": source_season,
    }
    semantic.update(
        {
            f"count_{class_name.casefold()}": int(counts[index])
            for index, class_name in enumerate(PA_CLASS_ORDER)
        }
    )
    natural_key = {
        name: semantic[name]
        for name in (
            "canonical_player_uuid",
            "role",
            "final_available_date",
            "source_season",
        )
    }
    history_row_id = "mlb-dynamic-history-row:sha256:" + sha256_bytes(
        canonical_json_bytes(
            {
                "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_HISTORY_ROW_IDENTITY_V1",
                "contractSha": dynamic_state_contract_sha(),
                "naturalKey": natural_key,
            }
        )
    )
    return {
        "historyRowId": history_row_id,
        "rowContentSha": sha256_bytes(canonical_json_bytes(semantic)),
        **semantic,
    }


def _history_content_sha(
    table: pa.Table,
    *,
    source_partition_ids: Sequence[str],
    source_row_count: int,
    resolved_reference_count: int,
) -> str:
    digest = hashlib.sha256()
    digest.update(
        canonical_json_bytes(
            {
                "schemaVersion": HISTORY_INDEX_CONTENT_SCHEMA_VERSION,
                "contractSha": dynamic_state_contract_sha(),
                "schemaSha": dynamic_history_index_schema_sha(),
                "rowCount": table.num_rows,
                "sourceRowCount": source_row_count,
                "resolvedReferenceCount": resolved_reference_count,
                "sourcePartitionIds": list(source_partition_ids),
            }
        )
    )
    # Match the semantic-value normalization used by the state-table digest.
    # Parquet reloads the live 24k materialization batches as 65,536-row groups;
    # hashing those physical Arrow buffers would make an unchanged history index
    # fail its own checkpoint verification.
    canonical_schema = table.schema.remove_metadata()
    for offset in range(0, table.num_rows, _BATCH_ROWS):
        window = table.slice(offset, min(_BATCH_ROWS, table.num_rows - offset))
        batch = pa.RecordBatch.from_pydict(
            window.to_pydict(),
            schema=canonical_schema,
        )
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, canonical_schema) as writer:
            writer.write_batch(batch)
        digest.update(sink.getvalue().to_pybytes())
    return digest.hexdigest()


def build_historical_dynamic_index(
    history: HistoricalOutcomeIndex,
    *,
    code_revision: str,
) -> BuiltHistoricalDynamicIndex:
    if not isinstance(code_revision, str) or not code_revision.strip():
        raise ValueError("code_revision must be non-empty")
    schema = _history_arrow_schema()
    columns: dict[str, list[Any]] = {field.name: [] for field in schema}
    batches: list[pa.RecordBatch] = []

    def flush() -> None:
        if not columns["historyRowId"]:
            return
        batches.append(pa.RecordBatch.from_pydict(columns, schema=schema))
        for values in columns.values():
            values.clear()

    for role in ROLES:
        for player_uuid, player_history in sorted(history.histories[role].items()):
            start = 0
            size = int(player_history.outcomes.size)
            while start < size:
                final_ordinal = int(player_history.availability_ordinals[start])
                source_season = int(player_history.seasons[start])
                end = start + 1
                while (
                    end < size
                    and int(player_history.availability_ordinals[end]) == final_ordinal
                    and int(player_history.seasons[end]) == source_season
                ):
                    end += 1
                counts = np.bincount(
                    player_history.outcomes[start:end],
                    minlength=len(PA_CLASS_ORDER),
                )
                row = _history_semantic_row(
                    canonical_player_uuid=player_uuid,
                    role=role,
                    final_available_date=date.fromordinal(final_ordinal).isoformat(),
                    source_season=source_season,
                    counts=counts,
                )
                for name in columns:
                    columns[name].append(row[name])
                if len(columns["historyRowId"]) >= _BATCH_ROWS:
                    flush()
                start = end
    flush()
    table = pa.Table.from_batches(batches, schema=schema)
    if table.num_rows == 0:
        raise DynamicStateIntegrityError("historical dynamic index may not be empty")
    content_sha = _history_content_sha(
        table,
        source_partition_ids=history.source_partition_ids,
        source_row_count=history.source_row_count,
        resolved_reference_count=history.resolved_reference_count,
    )
    metadata = {
        b"artifactSchemaVersion": HISTORY_INDEX_SCHEMA_VERSION.encode("utf-8"),
        b"contractName": CONTRACT_NAME.encode("utf-8"),
        b"contractSha": dynamic_state_contract_sha().encode("ascii"),
        b"schemaSha": dynamic_history_index_schema_sha().encode("ascii"),
        b"contentSha": content_sha.encode("ascii"),
        b"rowCount": str(table.num_rows).encode("ascii"),
        b"sourceRowCount": str(history.source_row_count).encode("ascii"),
        b"resolvedReferenceCount": str(history.resolved_reference_count).encode("ascii"),
        b"sourcePartitionIds": canonical_json_bytes(list(history.source_partition_ids)),
    }
    sink = pa.BufferOutputStream()
    pq.write_table(
        table.replace_schema_metadata(metadata),
        sink,
        compression="zstd",
        compression_level=9,
        use_dictionary=False,
        write_statistics=True,
        version="2.6",
        data_page_version="1.0",
        row_group_size=65_536,
    )
    return BuiltHistoricalDynamicIndex(
        table=table,
        schema_spec=dynamic_history_index_schema_spec(),
        schema_sha=dynamic_history_index_schema_sha(),
        content_sha=content_sha,
        parquet_bytes=sink.getvalue().to_pybytes(),
        source_partition_ids=history.source_partition_ids,
        source_row_count=history.source_row_count,
        resolved_reference_count=history.resolved_reference_count,
    )


_HISTORY_DESCRIPTOR_KEYS = {
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


def historical_dynamic_index_descriptor(
    built: BuiltHistoricalDynamicIndex,
    artifact_reference: Mapping[str, Any],
) -> dict[str, Any]:
    expected_artifact_fields = {
        "artifactId",
        "artifactType",
        "logicalUri",
        "sha256",
        "byteCount",
        "mediaType",
    }
    if set(artifact_reference) != expected_artifact_fields:
        raise DynamicStateIntegrityError("historical index artifact reference shape differs")
    if artifact_reference["artifactType"] != "DYNAMIC_HISTORY_INDEX":
        raise DynamicStateIntegrityError("historical index artifact type differs")
    authority = dynamic_state_contract_payload()["authorityBindings"]
    return {
        "schemaVersion": HISTORY_INDEX_DESCRIPTOR_SCHEMA_VERSION,
        "contractName": CONTRACT_NAME,
        "contractSha": dynamic_state_contract_sha(),
        "schemaSha": built.schema_sha,
        "contentSha": built.content_sha,
        "artifactId": artifact_reference["artifactId"],
        "artifactSha": artifact_reference["sha256"],
        "artifactBytes": artifact_reference["byteCount"],
        "logicalUri": artifact_reference["logicalUri"],
        "mediaType": artifact_reference["mediaType"],
        "rowCount": built.row_count,
        "sourceRowCount": built.source_row_count,
        "resolvedReferenceCount": built.resolved_reference_count,
        "sourcePartitionIds": list(built.source_partition_ids),
        "authorityBindings": {
            "dataset": authority["dataset"],
            "identityBridge": authority["identityBridge"],
        },
    }


def _validate_history_descriptor(descriptor: Mapping[str, Any]) -> None:
    if not isinstance(descriptor, Mapping) or set(descriptor) != _HISTORY_DESCRIPTOR_KEYS:
        raise DynamicStateIntegrityError("historical index descriptor field set differs")
    authority = dynamic_state_contract_payload()["authorityBindings"]
    expected = {
        "schemaVersion": HISTORY_INDEX_DESCRIPTOR_SCHEMA_VERSION,
        "contractName": CONTRACT_NAME,
        "contractSha": dynamic_state_contract_sha(),
        "schemaSha": dynamic_history_index_schema_sha(),
        "mediaType": "application/vnd.apache.parquet",
        "authorityBindings": {
            "dataset": authority["dataset"],
            "identityBridge": authority["identityBridge"],
        },
    }
    for name, value in expected.items():
        if descriptor.get(name) != value:
            raise DynamicStateIntegrityError(f"historical index descriptor {name} differs")
    for name in ("contentSha", "artifactSha"):
        value = descriptor.get(name)
        if not isinstance(value, str) or len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise DynamicStateIntegrityError(f"historical index descriptor {name} is invalid")
    for name in ("artifactBytes", "rowCount", "sourceRowCount", "resolvedReferenceCount"):
        value = descriptor.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise DynamicStateIntegrityError(f"historical index descriptor {name} is invalid")
    if descriptor["resolvedReferenceCount"] != 2 * descriptor["sourceRowCount"]:
        raise DynamicStateIntegrityError("historical index reference count differs")
    partition_ids = descriptor.get("sourcePartitionIds")
    if (
        not isinstance(partition_ids, list)
        or not partition_ids
        or partition_ids != sorted(partition_ids)
        or len(set(partition_ids)) != len(partition_ids)
        or not all(isinstance(value, str) and value for value in partition_ids)
    ):
        raise DynamicStateIntegrityError("historical index source partition identities differ")
    artifact_id = descriptor.get("artifactId")
    if not isinstance(artifact_id, str) or not artifact_id.endswith(descriptor["artifactSha"]):
        raise DynamicStateIntegrityError("historical index artifact identity differs")
    logical_uri = descriptor.get("logicalUri")
    if (
        not isinstance(logical_uri, str)
        or f"/sha256/{descriptor['artifactSha'][:2]}/{descriptor['artifactSha']}/" not in logical_uri
    ):
        raise DynamicStateIntegrityError("historical index logical URI differs")


def load_historical_dynamic_index(
    artifact_bytes: bytes,
    *,
    descriptor: Mapping[str, Any],
) -> HistoricalOutcomeIndex:
    _validate_history_descriptor(descriptor)
    if not isinstance(artifact_bytes, bytes) or not artifact_bytes:
        raise DynamicStateIntegrityError("historical index artifact bytes are required")
    if len(artifact_bytes) != descriptor["artifactBytes"]:
        raise DynamicStateIntegrityError("historical index artifact byte count differs")
    if sha256_bytes(artifact_bytes) != descriptor["artifactSha"]:
        raise DynamicStateIntegrityError("historical index artifact SHA differs")
    try:
        table = pq.read_table(pa.BufferReader(artifact_bytes))
        metadata = pq.ParquetFile(pa.BufferReader(artifact_bytes)).schema_arrow.metadata or {}
    except Exception as exc:
        raise DynamicStateIntegrityError("historical index artifact is unreadable") from exc
    if table.schema.remove_metadata() != _history_arrow_schema():
        raise DynamicStateIntegrityError("historical index table schema differs")
    expected_metadata = {
        b"artifactSchemaVersion": HISTORY_INDEX_SCHEMA_VERSION.encode("utf-8"),
        b"contractName": CONTRACT_NAME.encode("utf-8"),
        b"contractSha": dynamic_state_contract_sha().encode("ascii"),
        b"schemaSha": dynamic_history_index_schema_sha().encode("ascii"),
        b"contentSha": descriptor["contentSha"].encode("ascii"),
        b"rowCount": str(descriptor["rowCount"]).encode("ascii"),
        b"sourceRowCount": str(descriptor["sourceRowCount"]).encode("ascii"),
        b"resolvedReferenceCount": str(descriptor["resolvedReferenceCount"]).encode("ascii"),
        b"sourcePartitionIds": canonical_json_bytes(descriptor["sourcePartitionIds"]),
    }
    for name, value in expected_metadata.items():
        if metadata.get(name) != value:
            raise DynamicStateIntegrityError("historical index Parquet metadata differs")
    if table.num_rows != descriptor["rowCount"]:
        raise DynamicStateIntegrityError("historical index row count differs")
    if pc.count_distinct(table["historyRowId"]).as_py() != table.num_rows:
        raise DynamicStateIntegrityError("historical index row identity is duplicated")
    buffers: dict[str, dict[str, _HistoryBuffers]] = {
        role: defaultdict(_HistoryBuffers.create) for role in ROLES
    }
    represented_references = 0
    for batch in table.to_batches(max_chunksize=65_536):
        for row in batch.to_pylist():
            if row["role"] not in ROLES:
                raise DynamicStateIntegrityError("historical index role differs")
            try:
                final_ordinal = date.fromisoformat(row["final_available_date"]).toordinal()
            except (TypeError, ValueError) as exc:
                raise DynamicStateIntegrityError("historical index final date differs") from exc
            source_season = row["source_season"]
            if not isinstance(source_season, int) or source_season not in SOURCE_SEASONS:
                raise DynamicStateIntegrityError("historical index source season differs")
            semantic = dict(row)
            observed_row_id = semantic.pop("historyRowId")
            observed_row_sha = semantic.pop("rowContentSha")
            counts = np.asarray(
                [semantic[f"count_{name.casefold()}"] for name in PA_CLASS_ORDER],
                dtype=np.int64,
            )
            if np.any(counts < 0) or int(counts.sum()) <= 0:
                raise DynamicStateIntegrityError("historical index sufficient statistics differ")
            expected = _history_semantic_row(
                canonical_player_uuid=semantic["canonical_player_uuid"],
                role=semantic["role"],
                final_available_date=semantic["final_available_date"],
                source_season=source_season,
                counts=counts,
            )
            if observed_row_id != expected["historyRowId"] or observed_row_sha != expected["rowContentSha"]:
                raise DynamicStateIntegrityError("historical index row identity or checksum differs")
            buffer = buffers[row["role"]][row["canonical_player_uuid"]]
            for class_index, count in enumerate(counts.tolist()):
                if count:
                    buffer.dates.extend([final_ordinal] * count)
                    buffer.seasons.extend([source_season] * count)
                    buffer.outcomes.extend([class_index] * count)
                    represented_references += count
    if represented_references != descriptor["resolvedReferenceCount"]:
        raise DynamicStateIntegrityError("historical index represented reference count differs")
    content_sha = _history_content_sha(
        table.replace_schema_metadata(None),
        source_partition_ids=descriptor["sourcePartitionIds"],
        source_row_count=descriptor["sourceRowCount"],
        resolved_reference_count=descriptor["resolvedReferenceCount"],
    )
    if content_sha != descriptor["contentSha"]:
        raise DynamicStateIntegrityError("historical index semantic content SHA differs")
    histories = {
        role: {
            player_uuid: _PlayerHistory.from_buffers(item.dates, item.seasons, item.outcomes)
            for player_uuid, item in sorted(buffers[role].items())
        }
        for role in ROLES
    }
    return HistoricalOutcomeIndex(
        histories=histories,
        source_row_count=descriptor["sourceRowCount"],
        source_partition_ids=tuple(descriptor["sourcePartitionIds"]),
        resolved_reference_count=descriptor["resolvedReferenceCount"],
        unresolved_reference_count=0,
        ambiguous_reference_count=0,
    )


def dynamic_state_rows_for_keys(
    history: HistoricalOutcomeIndex,
    keys: Sequence[tuple[str, str, str]],
    *,
    policy: FrozenDynamicPolicy,
) -> pa.Table:
    if not keys:
        raise DynamicStateIntegrityError("on-demand dynamic state keys are required")
    normalized: set[tuple[str, str, str]] = set()
    for item in keys:
        if not isinstance(item, tuple) or len(item) != 3:
            raise DynamicStateIntegrityError("on-demand dynamic state key shape differs")
        game_date, player_uuid, role = item
        try:
            parsed = date.fromisoformat(game_date)
        except (TypeError, ValueError) as exc:
            raise DynamicStateIntegrityError("on-demand target game date differs") from exc
        if (
            parsed.year not in TARGET_SEASONS
            or not isinstance(player_uuid, str)
            or not player_uuid
            or role not in ROLES
        ):
            raise DynamicStateIntegrityError("on-demand dynamic state key is outside the domain")
        if item in normalized:
            raise DynamicStateIntegrityError("on-demand dynamic state key is duplicated")
        normalized.add(item)
    schema = _arrow_schema()
    rows = []
    for game_date, player_uuid, role in sorted(normalized):
        snapshot = history.snapshot(
            role=role,
            canonical_player_uuid=player_uuid,
            target_game_date=game_date,
            target_season=int(game_date[:4]),
            state_kind="C_RECENCY",
            policy=policy,
        )
        rows.append(
            _semantic_state_row(
                game_date=game_date,
                season=int(game_date[:4]),
                canonical_player_uuid=player_uuid,
                role=role,
                state_kind="C_RECENCY",
                policy=policy,
                snapshot=snapshot,
            )
        )
    table = pa.Table.from_pylist(rows, schema=schema)
    validate_dynamic_state_table(table, policy=policy)
    return table


def _content_parquet(
    table: pa.Table,
    *,
    content_sha: str,
    policy: FrozenDynamicPolicy,
    code_revision: str,
) -> bytes:
    metadata = {
        b"artifactSchemaVersion": TABLE_SCHEMA_VERSION.encode("utf-8"),
        b"contractName": CONTRACT_NAME.encode("utf-8"),
        b"contractVersion": CONTRACT_VERSION.encode("utf-8"),
        b"contractSha": dynamic_state_contract_sha().encode("ascii"),
        b"schemaSha": dynamic_state_schema_sha().encode("ascii"),
        b"contentSha": content_sha.encode("ascii"),
        b"policyId": policy.policy_id.encode("utf-8"),
        b"rowCount": str(table.num_rows).encode("ascii"),
    }
    sink = pa.BufferOutputStream()
    pq.write_table(
        table.replace_schema_metadata(metadata),
        sink,
        compression="zstd",
        compression_level=9,
        use_dictionary=False,
        write_statistics=True,
        version="2.6",
        data_page_version="1.0",
        row_group_size=65_536,
    )
    return sink.getvalue().to_pybytes()


def materialize_dynamic_player_state(
    target_feature_view: pa.Table,
    history: HistoricalOutcomeIndex,
    tuning: DynamicPolicyTuning,
    *,
    code_revision: str,
    expected_target_rows: int | None = None,
    progress: Any | None = None,
) -> BuiltDynamicPlayerState:
    if not isinstance(code_revision, str) or not code_revision.strip():
        raise ValueError("code_revision must be a non-empty content-bound descriptor")
    values = _validate_target_table(target_feature_view, expected_rows=expected_target_rows)
    posterior_predictive = evaluate_frozen_dynamic_state_posteriors(
        target_feature_view,
        history,
        policy=tuning.policy,
        progress=progress,
    )
    target_keys: set[tuple[str, int, str, str]] = set()
    for index in range(target_feature_view.num_rows):
        game_date = str(values["game_date"][index])
        season = int(values["season"][index])
        target_keys.add(
            (game_date, season, str(values["batter_canonical_player_uuid"][index]), "BATTER")
        )
        target_keys.add(
            (game_date, season, str(values["pitcher_canonical_player_uuid"][index]), "PITCHER")
        )
    ordered_keys = sorted(target_keys)
    schema = _arrow_schema()
    batches: list[pa.RecordBatch] = []
    columns: dict[str, list[Any]] = {field.name: [] for field in schema}
    season_rows: Counter[int] = Counter()
    seen_row_ids: set[str] = set()
    started = time.monotonic()
    last_emit = started
    total_rows = len(ordered_keys) * len(STATE_KINDS)
    processed = 0

    def flush() -> None:
        if not columns["stateRowId"]:
            return
        batch = pa.RecordBatch.from_pydict(columns, schema=schema)
        batches.append(batch)
        for values_list in columns.values():
            values_list.clear()

    for game_date, season, player_uuid, role in ordered_keys:
        for state_kind in STATE_KINDS:
            snapshot = history.snapshot(
                role=role,
                canonical_player_uuid=player_uuid,
                target_game_date=game_date,
                target_season=season,
                state_kind=state_kind,
                policy=tuning.policy,
            )
            row = _semantic_state_row(
                game_date=game_date,
                season=season,
                canonical_player_uuid=player_uuid,
                role=role,
                state_kind=state_kind,
                policy=tuning.policy,
                snapshot=snapshot,
            )
            if row["stateRowId"] in seen_row_ids:
                raise DynamicStateIntegrityError("dynamic state row identity is duplicated")
            seen_row_ids.add(row["stateRowId"])
            for name in columns:
                columns[name].append(row[name])
            season_rows[season] += 1
            processed += 1
            if len(columns["stateRowId"]) >= _BATCH_ROWS:
                flush()
            now = time.monotonic()
            if progress is not None and (
                processed == 1
                or processed % 50_000 == 0
                or processed == total_rows
                or now - last_emit >= 30.0
            ):
                _emit(
                    progress,
                    "MATERIALIZING_DYNAMIC_PLAYER_STATE",
                    {
                        "rowsProcessed": processed,
                        "rowsTotal": total_rows,
                        "currentSeason": season,
                        "stateKind": state_kind,
                        "elapsedSeconds": round(now - started, 2),
                        "errors": 0,
                    },
                )
                last_emit = now
    flush()
    table = pa.Table.from_batches(batches, schema=schema)
    if table.num_rows != total_rows:
        raise DynamicStateIntegrityError("dynamic state row count differs after materialization")
    content_sha = _logical_content_sha(table, policy=tuning.policy)
    parquet_bytes = _content_parquet(
        table,
        content_sha=content_sha,
        policy=tuning.policy,
        code_revision=code_revision,
    )
    return BuiltDynamicPlayerState(
        table=table,
        contract=dynamic_state_contract_payload(),
        contract_sha=dynamic_state_contract_sha(),
        schema_spec=dynamic_state_schema_spec(),
        schema_sha=dynamic_state_schema_sha(),
        content_sha=content_sha,
        parquet_bytes=parquet_bytes,
        policy=tuning.policy,
        tuning=tuning,
        posterior_predictive=posterior_predictive,
        season_rows=dict(sorted(season_rows.items())),
        source_partition_ids=history.source_partition_ids,
        source_row_count=history.source_row_count,
        resolved_reference_count=history.resolved_reference_count,
    )


def build_dynamic_player_state_from_tables(
    historical_plate_appearance_tables: Sequence[pa.Table],
    target_feature_view: pa.Table,
    *,
    alias_rows: Sequence[Mapping[str, Any]] | Mapping[str, str],
    dimension_uuids: frozenset[str],
    code_revision: str,
    source_partition_ids: Sequence[str] = (),
    expected_target_rows: int | None = None,
    progress: Any | None = None,
) -> BuiltDynamicPlayerState:
    history = build_historical_outcome_index(
        historical_plate_appearance_tables,
        alias_rows=alias_rows,
        dimension_uuids=dimension_uuids,
        source_partition_ids=source_partition_ids,
        progress=progress,
    )
    tuning = tune_dynamic_policy(target_feature_view, history, progress=progress)
    return materialize_dynamic_player_state(
        target_feature_view,
        history,
        tuning,
        code_revision=code_revision,
        expected_target_rows=expected_target_rows,
        progress=progress,
    )


def _safe_partition_path(parent: ValidatedPackage, partition: Mapping[str, Any]) -> Path:
    logical_uri = validate_package_relative_uri(partition.get("package_relative_uri"))
    root = parent.package_root.resolve(strict=True)
    candidate = root.joinpath(*PurePosixPath(logical_uri).parts)
    return _validate_resolved_child(root, candidate, logical_uri=logical_uri)


def _load_registered_historical_outcomes(
    parent: ValidatedPackage,
    identity_bridge: ValidatedIdentityBridge,
    *,
    progress: Any | None = None,
) -> HistoricalOutcomeIndex:
    partitions = sorted(
        (
            partition
            for partition in parent.partitions
            if partition.get("family") == "plate_appearance"
            and partition.get("season") in SOURCE_SEASONS
        ),
        key=lambda item: (
            item.get("season"),
            item.get("month") or 0,
            item.get("partition_id"),
        ),
    )
    if len(partitions) != EXPECTED_SOURCE_PARTITION_COUNT:
        raise DynamicStateIntegrityError("exactly 36 registered plate-appearance partitions are required")
    partition_ids = tuple(str(item["partition_id"]) for item in partitions)
    accumulator = HistoricalOutcomeAccumulator(
        alias_rows=identity_bridge.aliases,
        dimension_uuids=identity_bridge.dimension_uuids,
        source_partition_ids=partition_ids,
        progress=progress,
    )
    for ordinal, partition in enumerate(partitions, start=1):
        path = _safe_partition_path(parent, partition)
        try:
            table = pq.read_table(path, columns=list(SOURCE_COLUMNS))
        except Exception as exc:
            raise DynamicStateIntegrityError(
                "registered historical plate-appearance partition is unreadable"
            ) from exc
        if table.num_rows != partition.get("row_count"):
            raise DynamicStateIntegrityError("registered historical partition row count changed")
        accumulator.add_table(table)
        _emit(
            progress,
            "READING_REGISTERED_PA_PARTITIONS",
            {
                "partitionsProcessed": ordinal,
                "partitionsTotal": len(partitions),
                "rowsProcessed": accumulator.source_row_count,
                "errors": 0,
            },
        )
    history = accumulator.finish()
    if history.source_row_count != EXPECTED_SOURCE_ROWS:
        raise DynamicStateIntegrityError("historical plate-appearance source row count differs")
    if history.resolved_reference_count != 2 * EXPECTED_SOURCE_ROWS:
        raise DynamicStateIntegrityError("historical batter/pitcher identity coverage differs")
    return history


def build_mlb_dynamic_player_state_bundle_v1(
    parent: ValidatedPackage,
    identity_bridge: ValidatedIdentityBridge,
    target_feature_view: pa.Table,
    *,
    code_revision: str,
    progress: Any | None = None,
) -> tuple[BuiltDynamicPlayerState, BuiltHistoricalDynamicIndex]:
    history = _load_registered_historical_outcomes(
        parent,
        identity_bridge,
        progress=progress,
    )
    tuning = tune_dynamic_policy(target_feature_view, history, progress=progress)
    state = materialize_dynamic_player_state(
        target_feature_view,
        history,
        tuning,
        code_revision=code_revision,
        expected_target_rows=EXPECTED_TARGET_ROWS,
        progress=progress,
    )
    historical_index = build_historical_dynamic_index(history, code_revision=code_revision)
    return state, historical_index


def build_mlb_dynamic_player_state_v1(
    parent: ValidatedPackage,
    identity_bridge: ValidatedIdentityBridge,
    target_feature_view: pa.Table,
    *,
    code_revision: str,
    progress: Any | None = None,
) -> BuiltDynamicPlayerState:
    state, _historical_index = build_mlb_dynamic_player_state_bundle_v1(
        parent,
        identity_bridge,
        target_feature_view,
        code_revision=code_revision,
        progress=progress,
    )
    return state


def _emit(progress: Any | None, stage: str, evidence: Mapping[str, Any]) -> None:
    if progress is not None:
        progress(stage, {"stage": stage, **dict(evidence)})


__all__ = [
    "BuiltDynamicPlayerState",
    "BuiltHistoricalDynamicIndex",
    "DynamicPolicyTuning",
    "DynamicStateIntegrityError",
    "FrozenDynamicPolicy",
    "HistoricalOutcomeAccumulator",
    "HistoricalOutcomeIndex",
    "SOURCE_COLUMNS",
    "TARGET_COLUMNS",
    "build_dynamic_player_state_from_tables",
    "build_historical_dynamic_index",
    "build_historical_outcome_index",
    "build_mlb_dynamic_player_state_bundle_v1",
    "build_mlb_dynamic_player_state_v1",
    "dynamic_state_table_content_sha",
    "dynamic_state_rows_for_keys",
    "evaluate_frozen_dynamic_state_posteriors",
    "exact_retrosheet_alias_map",
    "historical_dynamic_index_descriptor",
    "load_historical_dynamic_index",
    "materialize_dynamic_player_state",
    "tune_dynamic_policy",
    "validate_dynamic_state_table",
]
