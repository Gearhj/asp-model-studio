from __future__ import annotations

import bisect
import math
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from server.sports_datasets.constants import MANIFEST_SHA, PARTITION_AUTHORITY_SHA
from server.sports_datasets.consumer import (
    SportsDatasetManifestConsumer,
    ValidatedPackage,
    _validate_resolved_child,
    canonical_json_bytes,
    filesystem_identity,
    sha256_bytes,
    validate_package_relative_uri,
)
from server.sports_identity_bridges.constants import (
    ALIAS_AUTHORITY_SHA,
    BRIDGE_MANIFEST_SHA,
    DIMENSION_AUTHORITY_SHA,
)
from server.sports_identity_bridges.consumer import (
    MlbFd1IdentityBridgeAdapter,
    ValidatedIdentityBridge,
)
from server.sports_phase4.dynamic_contract import LOG_ODDS_CLASSES

from .participation_contract import (
    BULLPEN_FEATURES,
    BULLPEN_TRAILING_POOL_DAYS,
    EARLY_SEASON_DAYS,
    HISTORY_SEASONS,
    LINEUP_FEATURES,
    LINEUP_TRAILING_POOL_DAYS,
    STARTER_FEATURES,
    TARGET_SEASONS,
    contract_set_sha,
    validate_dynamic_descriptor,
)


FEATURE_VIEW_SCHEMA_VERSION = "MLB_PARTICIPATION_FEATURE_VIEWS_V1"
EXPECTED_SOURCE_ROWS: Mapping[str, int] = {
    "player_game_batting": 356_498,
    "starter_usage": 24_296,
    "bullpen_usage": 80_314,
}
EXPECTED_TARGET_ROWS: Mapping[str, Mapping[int, int]] = {
    "starter_usage": {2023: 4_860, 2024: 4_858, 2025: 4_860},
    "bullpen_usage": {2023: 15_770, 2024: 15_835, 2025: 16_008},
}
# Complete-lineup-eligible target games per season, derived from the registered FD1
# player_game_batting authority (manifest sha256:1b58d5d1…): every target-season game has a
# complete nine-batter starting lineup with batting orders 1..9 for both teams, so the
# eligible count equals the target-game count. Corrected from an earlier stale golden value
# (2_423 / 2_418 / 2_420) that predated the current governed manifest.
EXPECTED_COMPLETE_LINEUP_GAMES: Mapping[int, int] = {
    2023: 2_430,
    2024: 2_429,
    2025: 2_430,
}
DYNAMIC_REQUIRED_COLUMNS: tuple[str, ...] = (
    "game_date",
    "season",
    "canonical_player_uuid",
    "role",
    "state_kind",
    "policy_id",
    *(f"log_odds_{class_name.casefold()}" for class_name in LOG_ODDS_CLASSES),
    "effective_sample_size",
    "missing_history",
    "evidence_cutoff_exclusive",
)

_BATTING_COLUMNS: tuple[str, ...] = (
    "game_id",
    "game_date",
    "season",
    "team_id",
    "player_id",
    "final_available_date",
    "historical_reconstruction",
    "available_only_after_game_final",
    "future_evidence_allowed",
    "strict_same_game_pregame_eligible",
    "strict_prior_eligible_after_game_final",
    "enhanced_research_eligible",
    "actual_starting_lineup",
    "actual_batting_order",
    "stat_b_pa",
)

_STARTER_COLUMNS: tuple[str, ...] = (
    "usage_id",
    "game_id",
    "game_date",
    "season",
    "team_id",
    "player_id",
    "final_available_date",
    "historical_reconstruction",
    "available_only_after_game_final",
    "future_evidence_allowed",
    "strict_same_game_pregame_eligible",
    "strict_prior_eligible_after_game_final",
    "enhanced_research_eligible",
    "announcement_time_known",
    "actual_appearance_target",
    "actual_starter_target",
    "stat_p_bfp",
    "stat_p_ipouts",
)

_BULLPEN_COLUMNS: tuple[str, ...] = (
    "usage_id",
    "game_id",
    "game_date",
    "season",
    "team_id",
    "player_id",
    "final_available_date",
    "historical_reconstruction",
    "available_only_after_game_final",
    "future_evidence_allowed",
    "strict_same_game_pregame_eligible",
    "strict_prior_eligible_after_game_final",
    "enhanced_research_eligible",
    "announcement_time_known",
    "actual_appearance_target",
    "actual_starter_target",
    "stat_p_bfp",
    "stat_p_ipouts",
)


class ParticipationFeatureError(RuntimeError):
    """Fail-closed feature materialization error for Milestone B."""


@dataclass(frozen=True)
class DynamicStateSource:
    descriptor: Mapping[str, Any]
    table: pa.Table | None = None
    loader: Callable[
        [Mapping[str, Any], Sequence[tuple[str, str, str]]],
        pa.Table | tuple[pa.Table, bytes],
    ] | None = None


@dataclass(frozen=True)
class BuiltParticipationFeatureViews:
    lineup: pa.Table
    starter: pa.Table
    bullpen: pa.Table
    coverage: dict[str, tuple[dict[str, Any], ...]]
    dynamic_binding: dict[str, Any]
    contract_sha: str
    content_shas: dict[str, str]
    combined_content_sha: str
    parquet_bytes: dict[str, bytes]
    source_partition_ids: tuple[str, ...]

    @property
    def row_counts(self) -> dict[str, int]:
        return {
            "lineup": self.lineup.num_rows,
            "starter": self.starter.num_rows,
            "bullpen": self.bullpen.num_rows,
        }


@dataclass(frozen=True)
class _BatEvent:
    game_id: str
    game_date: str
    game_ordinal: int
    final_ordinal: int
    season: int
    team_id: str
    player_uuid: str
    started: bool
    batting_order: int | None
    plate_appearances: int


@dataclass(frozen=True)
class _PitchEvent:
    usage_id: str
    game_id: str
    game_date: str
    game_ordinal: int
    final_ordinal: int
    season: int
    team_id: str
    player_uuid: str
    bfp: int
    outs: int


def _require_columns(table: pa.Table, columns: Sequence[str], *, label: str) -> None:
    if not isinstance(table, pa.Table):
        raise TypeError(f"{label} must be a pyarrow Table")
    missing = sorted(set(columns) - set(table.column_names))
    if missing:
        raise ParticipationFeatureError(f"{label} is missing required columns: {missing}")


def _iso_ordinal(value: Any, *, label: str) -> int:
    if not isinstance(value, str):
        raise ParticipationFeatureError(f"{label} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ParticipationFeatureError(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ParticipationFeatureError(f"{label} must use canonical YYYY-MM-DD form")
    return parsed.toordinal()


def _strict_row_guard(values: Mapping[str, list[Any]], index: int, *, label: str) -> None:
    if (
        values["historical_reconstruction"][index] is not True
        or values["available_only_after_game_final"][index] is not True
        or values["future_evidence_allowed"][index] is not False
        or values["strict_same_game_pregame_eligible"][index] is not False
        or values["strict_prior_eligible_after_game_final"][index] is not True
        or values["enhanced_research_eligible"][index] is not True
    ):
        raise ParticipationFeatureError(f"{label} temporal/governance flags differ")
    game_ordinal = _iso_ordinal(values["game_date"][index], label=f"{label}.game_date")
    final_ordinal = _iso_ordinal(
        values["final_available_date"][index], label=f"{label}.final_available_date"
    )
    if final_ordinal < game_ordinal:
        raise ParticipationFeatureError(f"{label} final availability precedes its game date")


def _resolve_uuid(
    raw_player_id: Any,
    *,
    aliases: Mapping[str, str],
    dimensions: frozenset[str],
    label: str,
) -> str:
    if not isinstance(raw_player_id, str) or not raw_player_id:
        raise ParticipationFeatureError(f"{label} player_id is missing")
    canonical = aliases.get(raw_player_id)
    if not isinstance(canonical, str) or canonical not in dimensions:
        raise ParticipationFeatureError(f"{label} player_id did not resolve exactly through the bridge")
    return canonical


def _normalize_batting(
    table: pa.Table,
    *,
    aliases: Mapping[str, str],
    dimensions: frozenset[str],
) -> list[_BatEvent]:
    _require_columns(table, _BATTING_COLUMNS, label="player_game_batting")
    values = table.select(_BATTING_COLUMNS).to_pydict()
    events: list[_BatEvent] = []
    seen: set[tuple[str, str, str]] = set()
    for index in range(table.num_rows):
        _strict_row_guard(values, index, label="player_game_batting")
        season = values["season"][index]
        if type(season) is not int or season not in HISTORY_SEASONS:
            raise ParticipationFeatureError("player_game_batting season differs")
        game_id = values["game_id"][index]
        team_id = values["team_id"][index]
        if not isinstance(game_id, str) or not game_id or not isinstance(team_id, str) or not team_id:
            raise ParticipationFeatureError("player_game_batting grouping IDs are invalid")
        player_uuid = _resolve_uuid(
            values["player_id"][index],
            aliases=aliases,
            dimensions=dimensions,
            label="player_game_batting",
        )
        key = (game_id, team_id, player_uuid)
        if key in seen:
            raise ParticipationFeatureError("player_game_batting game/team/player key is duplicated")
        seen.add(key)
        started = values["actual_starting_lineup"][index]
        order = values["actual_batting_order"][index]
        plate_appearances = values["stat_b_pa"][index]
        if type(started) is not bool:
            raise ParticipationFeatureError("actual_starting_lineup must be Boolean")
        if order is not None and (type(order) is not int or not 1 <= order <= 9):
            raise ParticipationFeatureError("actual_batting_order must be null or in 1..9")
        if type(plate_appearances) is not int or plate_appearances < 0:
            raise ParticipationFeatureError("stat_b_pa must be a non-negative integer")
        game_date = values["game_date"][index]
        events.append(
            _BatEvent(
                game_id=game_id,
                game_date=game_date,
                game_ordinal=_iso_ordinal(game_date, label="player_game_batting.game_date"),
                final_ordinal=_iso_ordinal(
                    values["final_available_date"][index],
                    label="player_game_batting.final_available_date",
                ),
                season=season,
                team_id=team_id,
                player_uuid=player_uuid,
                started=started,
                batting_order=order,
                plate_appearances=plate_appearances,
            )
        )
    return sorted(events, key=lambda item: (item.final_ordinal, item.game_id, item.team_id, item.player_uuid))


def _normalize_pitching(
    table: pa.Table,
    *,
    aliases: Mapping[str, str],
    dimensions: frozenset[str],
    label: str,
    starter: bool,
) -> list[_PitchEvent]:
    columns = _STARTER_COLUMNS if starter else _BULLPEN_COLUMNS
    _require_columns(table, columns, label=label)
    values = table.select(columns).to_pydict()
    events: list[_PitchEvent] = []
    seen: set[str] = set()
    for index in range(table.num_rows):
        _strict_row_guard(values, index, label=label)
        season = values["season"][index]
        if type(season) is not int or season not in HISTORY_SEASONS:
            raise ParticipationFeatureError(f"{label} season differs")
        usage_id = values["usage_id"][index]
        game_id = values["game_id"][index]
        team_id = values["team_id"][index]
        if (
            not isinstance(usage_id, str)
            or not usage_id
            or usage_id in seen
            or not isinstance(game_id, str)
            or not game_id
            or not isinstance(team_id, str)
            or not team_id
        ):
            raise ParticipationFeatureError(f"{label} lineage/grouping IDs are invalid or duplicated")
        seen.add(usage_id)
        if values["announcement_time_known"][index] is not False:
            raise ParticipationFeatureError(f"{label} announcement timing unexpectedly became known")
        if values["actual_appearance_target"][index] is not True:
            raise ParticipationFeatureError(f"{label} actual appearance target differs")
        if values["actual_starter_target"][index] is not starter:
            raise ParticipationFeatureError(f"{label} starter/reliever target differs")
        bfp = values["stat_p_bfp"][index]
        outs = values["stat_p_ipouts"][index]
        if type(bfp) is not int or bfp < 0 or type(outs) is not int or outs < 0:
            raise ParticipationFeatureError(f"{label} BFP/outs targets must be non-negative integers")
        player_uuid = _resolve_uuid(
            values["player_id"][index], aliases=aliases, dimensions=dimensions, label=label
        )
        game_date = values["game_date"][index]
        events.append(
            _PitchEvent(
                usage_id=usage_id,
                game_id=game_id,
                game_date=game_date,
                game_ordinal=_iso_ordinal(game_date, label=f"{label}.game_date"),
                final_ordinal=_iso_ordinal(
                    values["final_available_date"][index], label=f"{label}.final_available_date"
                ),
                season=season,
                team_id=team_id,
                player_uuid=player_uuid,
                bfp=bfp,
                outs=outs,
            )
        )
    return sorted(events, key=lambda item: (item.final_ordinal, item.usage_id))


def _dynamic_lookup(
    source: DynamicStateSource | None,
    *,
    fixture_mode: bool,
    required_keys: frozenset[tuple[str, str, str]],
) -> tuple[dict[tuple[str, str, str], dict[str, float]], dict[str, Any]]:
    if source is None:
        if not fixture_mode:
            raise ParticipationFeatureError("live participation research requires bound dynamic state")
        return {}, {
            "status": "MISSING_FIXTURE_ONLY",
            "contractName": "MLB_DYNAMIC_PLAYER_STATE_V1",
            "fixtureOnly": True,
        }
    descriptor = validate_dynamic_descriptor(source.descriptor)
    if (source.table is None) == (source.loader is None):
        raise ParticipationFeatureError("dynamic state requires exactly one table or loader")
    artifact_bytes: bytes | None = None
    if source.table is not None:
        table = source.table
    else:
        loaded = source.loader(descriptor, tuple(sorted(required_keys)))  # type: ignore[misc]
        if isinstance(loaded, tuple):
            if len(loaded) != 2 or not isinstance(loaded[0], pa.Table) or not isinstance(loaded[1], bytes):
                raise ParticipationFeatureError("dynamic-state loader returned an invalid tuple")
            table, artifact_bytes = loaded
        else:
            table = loaded
    _require_columns(table, DYNAMIC_REQUIRED_COLUMNS, label="dynamic player state")
    if artifact_bytes is not None:
        if len(artifact_bytes) != descriptor["artifactBytes"]:
            raise ParticipationFeatureError("dynamic-state artifact byte count differs")
        if sha256_bytes(artifact_bytes) != descriptor["artifactSha"]:
            raise ParticipationFeatureError("dynamic-state artifact SHA differs")
    values = table.select(DYNAMIC_REQUIRED_COLUMNS).to_pydict()
    lookup: dict[tuple[str, str, str], dict[str, float]] = {}
    for index in range(table.num_rows):
        if values["state_kind"][index] != "C_RECENCY" or values["policy_id"][index] != descriptor[
            "selectedPolicyId"
        ]:
            continue
        game_date = values["game_date"][index]
        _iso_ordinal(game_date, label="dynamic_state.game_date")
        if values["evidence_cutoff_exclusive"][index] != game_date:
            raise ParticipationFeatureError("dynamic-state evidence cutoff must equal its target game date")
        season = values["season"][index]
        player_uuid = values["canonical_player_uuid"][index]
        role = values["role"][index]
        ess = values["effective_sample_size"][index]
        missing = values["missing_history"][index]
        if (
            type(season) is not int
            or season not in TARGET_SEASONS
            or not isinstance(player_uuid, str)
            or not player_uuid
            or role not in {"BATTER", "PITCHER"}
            or isinstance(ess, bool)
            or not isinstance(ess, (int, float))
            or not math.isfinite(float(ess))
            or float(ess) < 0.0
            or type(missing) is not bool
        ):
            raise ParticipationFeatureError("dynamic-state key/value domain differs")
        key = (game_date, player_uuid, role)
        if key in lookup:
            raise ParticipationFeatureError("dynamic state has duplicate selected date/player/role rows")
        dynamic_values = {
            "availability": 0.0 if missing else 1.0,
            "missingHistory": float(missing),
            "ess": float(ess),
        }
        for class_name in LOG_ODDS_CLASSES:
            column = f"log_odds_{class_name.casefold()}"
            value = values[column][index]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ParticipationFeatureError("dynamic-state log-odds value is non-finite")
            dynamic_values[column] = float(value)
        lookup[key] = dynamic_values
    if not lookup:
        raise ParticipationFeatureError("dynamic state has no rows for the selected C_RECENCY policy")
    if set(lookup) != set(required_keys):
        missing = len(required_keys - set(lookup))
        extra = len(set(lookup) - required_keys)
        raise ParticipationFeatureError(
            f"dynamic-state candidate keys differ: missing={missing} extra={extra}"
        )
    binding = {
        "status": "BOUND",
        "contractName": descriptor["contractName"],
        "contractSha": descriptor["contractSha"],
        "schemaSha": descriptor["schemaSha"],
        "contentSha": descriptor["contentSha"],
        "artifactSha": descriptor["artifactSha"],
        "artifactBytes": descriptor["artifactBytes"],
        "logicalUri": descriptor["logicalUri"],
        "selectedStateKind": "C_RECENCY",
        "selectedPolicyId": descriptor["selectedPolicyId"],
        "parent": dict(descriptor["parent"]),
        "identityBridge": dict(descriptor["identityBridge"]),
        "phase3": dict(descriptor["phase3"]),
        "fixtureOnly": False,
        "requiredKeyCount": len(required_keys),
    }
    return lookup, binding


def _fixture_dynamic() -> dict[str, float]:
    return {
        "availability": 0.0,
        "missingHistory": 1.0,
        "ess": 0.0,
        **{f"log_odds_{class_name.casefold()}": 0.0 for class_name in LOG_ODDS_CLASSES},
    }


def _early_cutoffs(targets: Sequence[tuple[int, int]]) -> dict[int, int]:
    starts: dict[int, int] = {}
    for season, ordinal in targets:
        starts[season] = min(starts.get(season, ordinal), ordinal)
    return {season: ordinal + EARLY_SEASON_DAYS - 1 for season, ordinal in starts.items()}


class _BatHistory:
    def __init__(self, events: Sequence[_BatEvent]) -> None:
        grouped: dict[tuple[str, str], list[_BatEvent]] = defaultdict(list)
        for event in events:
            grouped[(event.team_id, event.player_uuid)].append(event)
        self.grouped = {
            key: sorted(rows, key=lambda item: (item.final_ordinal, item.game_id))
            for key, rows in grouped.items()
        }
        self.ordinals = {
            key: [event.final_ordinal for event in rows] for key, rows in self.grouped.items()
        }

    def features(
        self,
        team_id: str,
        player_uuid: str,
        target_ordinal: int,
        season: int,
        *,
        early: bool,
        dynamic: Mapping[str, float],
    ) -> dict[str, float | None]:
        key = (team_id, player_uuid)
        rows = self.grouped.get(key, [])
        ordinals = self.ordinals.get(key, [])
        stop = bisect.bisect_left(ordinals, target_ordinal)
        prior = rows[:stop]
        output: dict[str, float | None] = {}
        for window in (7, 14, 30):
            start = bisect.bisect_left(ordinals, target_ordinal - window, 0, stop)
            window_rows = rows[start:stop]
            output[f"prior_starts_{window}d"] = float(sum(row.started for row in window_rows))
            output[f"prior_appearances_{window}d"] = float(len(window_rows))
            output[f"prior_pa_{window}d"] = float(sum(row.plate_appearances for row in window_rows))
        output["days_since_appearance"] = (
            float(target_ordinal - prior[-1].final_ordinal) if prior else None
        )
        prior_starts = [row for row in prior if row.started]
        output["days_since_start"] = (
            float(target_ordinal - prior_starts[-1].final_ordinal) if prior_starts else None
        )
        season_rows = [row for row in prior if row.season == season]
        output["season_start_rate"] = (
            float(sum(row.started for row in season_rows) / len(season_rows)) if season_rows else 0.0
        )
        trailing_orders = [
            int(row.batting_order)
            for row in prior_starts
            if row.batting_order is not None and row.final_ordinal >= target_ordinal - 30
        ]
        output["trailing_order_mean"] = (
            float(sum(trailing_orders) / len(trailing_orders)) if trailing_orders else None
        )
        if trailing_orders:
            counts = Counter(trailing_orders)
            output["trailing_order_mode"] = float(
                min(order for order, count in counts.items() if count == max(counts.values()))
            )
        else:
            output["trailing_order_mode"] = None
        output["prior_season_participation"] = float(
            sum(row.season == season - 1 for row in prior)
        )
        output["early_season_indicator"] = float(early)
        output["dynamic_batter_availability"] = dynamic["availability"]
        output["dynamic_batter_ess"] = dynamic["ess"]
        return output


class _PitchHistory:
    def __init__(self, events: Sequence[_PitchEvent]) -> None:
        grouped: dict[tuple[str, str], list[_PitchEvent]] = defaultdict(list)
        by_player: dict[str, list[_PitchEvent]] = defaultdict(list)
        by_team: dict[str, list[_PitchEvent]] = defaultdict(list)
        for event in events:
            grouped[(event.team_id, event.player_uuid)].append(event)
            by_player[event.player_uuid].append(event)
            by_team[event.team_id].append(event)
        self.grouped = {
            key: sorted(rows, key=lambda item: (item.final_ordinal, item.usage_id))
            for key, rows in grouped.items()
        }
        self.ordinals = {key: [row.final_ordinal for row in rows] for key, rows in self.grouped.items()}
        self.by_player = {
            key: sorted(rows, key=lambda item: (item.final_ordinal, item.usage_id))
            for key, rows in by_player.items()
        }
        self.player_ordinals = {
            key: [row.final_ordinal for row in rows] for key, rows in self.by_player.items()
        }
        self.by_team = {
            key: sorted(rows, key=lambda item: (item.final_ordinal, item.usage_id))
            for key, rows in by_team.items()
        }
        self.team_ordinals = {
            key: [row.final_ordinal for row in rows] for key, rows in self.by_team.items()
        }

    def starter_features(
        self,
        event: _PitchEvent,
        *,
        early: bool,
        dynamic: Mapping[str, float],
    ) -> dict[str, float | None]:
        rows = self.by_player.get(event.player_uuid, [])
        ordinals = self.player_ordinals.get(event.player_uuid, [])
        stop = bisect.bisect_left(ordinals, event.game_ordinal)
        prior = rows[:stop]
        output: dict[str, float | None] = {}
        for window in (7, 14, 30):
            start = bisect.bisect_left(ordinals, event.game_ordinal - window, 0, stop)
            window_rows = rows[start:stop]
            output[f"prior_starts_{window}d"] = float(len(window_rows))
            output[f"prior_bfp_{window}d"] = float(sum(row.bfp for row in window_rows))
            output[f"prior_outs_{window}d"] = float(sum(row.outs for row in window_rows))
        previous = prior[-1] if prior else None
        output["previous_start_bfp"] = float(previous.bfp) if previous else None
        output["previous_start_outs"] = float(previous.outs) if previous else None
        for count in (3, 5):
            trailing = prior[-count:]
            output[f"trailing_{count}_start_mean_bfp"] = (
                float(sum(row.bfp for row in trailing) / len(trailing)) if trailing else None
            )
            output[f"trailing_{count}_start_mean_outs"] = (
                float(sum(row.outs for row in trailing) / len(trailing)) if trailing else None
            )
        team_rows = self.by_team.get(event.team_id, [])
        team_stop = bisect.bisect_left(self.team_ordinals.get(event.team_id, []), event.game_ordinal)
        prior_team = team_rows[:team_stop]
        output["team_prior_date_mean_bfp"] = (
            float(sum(row.bfp for row in prior_team) / len(prior_team)) if prior_team else None
        )
        output["team_prior_date_mean_outs"] = (
            float(sum(row.outs for row in prior_team) / len(prior_team)) if prior_team else None
        )
        output["starts_previous_30d"] = output["prior_starts_30d"]
        output["days_rest"] = (
            float(event.game_ordinal - previous.final_ordinal) if previous else None
        )
        season_rows = [row for row in prior if row.season == event.season]
        output["season_to_date_start_count"] = float(len(season_rows))
        output["season_to_date_mean_bfp"] = (
            float(sum(row.bfp for row in season_rows) / len(season_rows)) if season_rows else None
        )
        output["season_to_date_mean_outs"] = (
            float(sum(row.outs for row in season_rows) / len(season_rows)) if season_rows else None
        )
        prior_season = [row for row in prior if row.season == event.season - 1]
        output["prior_season_bfp"] = float(sum(row.bfp for row in prior_season))
        output["prior_season_outs"] = float(sum(row.outs for row in prior_season))
        output["early_season_indicator"] = float(early)
        for class_name in LOG_ODDS_CLASSES:
            output[f"dynamic_pitcher_log_odds_{class_name.casefold()}"] = dynamic[
                f"log_odds_{class_name.casefold()}"
            ]
        output["dynamic_pitcher_missing_history"] = dynamic["missingHistory"]
        output["dynamic_pitcher_ess"] = dynamic["ess"]
        return output

    def bullpen_features(
        self,
        team_id: str,
        player_uuid: str,
        target_ordinal: int,
        season: int,
        *,
        early: bool,
        dynamic: Mapping[str, float],
    ) -> dict[str, float | None]:
        key = (team_id, player_uuid)
        rows = self.grouped.get(key, [])
        ordinals = self.ordinals.get(key, [])
        stop = bisect.bisect_left(ordinals, target_ordinal)
        prior = rows[:stop]
        output: dict[str, float | None] = {}
        for window in (1, 3, 7, 14):
            start = bisect.bisect_left(ordinals, target_ordinal - window, 0, stop)
            window_rows = rows[start:stop]
            if window != 1:
                output[f"appearances_{window}d"] = float(len(window_rows))
            output[f"prior_bfp_{window}d"] = float(sum(row.bfp for row in window_rows))
            output[f"prior_outs_{window}d"] = float(sum(row.outs for row in window_rows))
        output["days_since_relief"] = (
            float(target_ordinal - prior[-1].final_ordinal) if prior else None
        )
        prior_dates = {row.final_ordinal for row in prior}
        output["appeared_yesterday"] = float(target_ordinal - 1 in prior_dates)
        output["appeared_on_two_consecutive_prior_days"] = float(
            target_ordinal - 1 in prior_dates and target_ordinal - 2 in prior_dates
        )
        season_rows = [row for row in prior if row.season == season]
        output["season_appearance_count"] = float(len(season_rows))
        output["season_bfp"] = float(sum(row.bfp for row in season_rows))
        output["season_outs"] = float(sum(row.outs for row in season_rows))
        team_rows = self.by_team.get(team_id, [])
        team_stop = bisect.bisect_left(self.team_ordinals.get(team_id, []), target_ordinal)
        prior_team = team_rows[:team_stop]
        team_season = [row for row in prior_team if row.season == season]
        output["season_relief_share"] = (
            float(len(season_rows) / len(team_season)) if team_season else 0.0
        )
        output["prior_team_usage_rate"] = float(len(prior) / len(prior_team)) if prior_team else 0.0
        output["prior_season_relief"] = float(sum(row.season == season - 1 for row in prior))
        output["early_season_indicator"] = float(early)
        for class_name in LOG_ODDS_CLASSES:
            output[f"dynamic_pitcher_log_odds_{class_name.casefold()}"] = dynamic[
                f"log_odds_{class_name.casefold()}"
            ]
        output["dynamic_pitcher_missing_history"] = dynamic["missingHistory"]
        output["dynamic_pitcher_ess"] = dynamic["ess"]
        return output


def _candidate_pool_snapshots(
    events: Sequence[_BatEvent] | Sequence[_PitchEvent],
    targets: Sequence[tuple[int, str, str, int, str]],
    *,
    trailing_days: int,
) -> dict[tuple[str, str], dict[str, set[str]]]:
    """Return pool-source sets keyed by target game/team without consulting targets."""

    ordered_events = sorted(events, key=lambda item: (item.final_ordinal, item.game_id, item.player_uuid))
    ordered_targets = sorted(targets, key=lambda item: (item[0], item[1], item[2]))
    observed: dict[tuple[str, int], set[str]] = defaultdict(set)
    trailing: dict[str, deque[tuple[int, str]]] = defaultdict(deque)
    trailing_counts: dict[str, Counter[str]] = defaultdict(Counter)
    output: dict[tuple[str, str], dict[str, set[str]]] = {}
    pointer = 0
    current_date: int | None = None
    for target_ordinal, game_id, team_id, season, _game_date in ordered_targets:
        if target_ordinal != current_date:
            while pointer < len(ordered_events) and ordered_events[pointer].final_ordinal < target_ordinal:
                event = ordered_events[pointer]
                observed[(event.team_id, event.season)].add(event.player_uuid)
                trailing[event.team_id].append((event.final_ordinal, event.player_uuid))
                trailing_counts[event.team_id][event.player_uuid] += 1
                pointer += 1
            cutoff = target_ordinal - trailing_days
            for active_team, queue in trailing.items():
                counts = trailing_counts[active_team]
                while queue and queue[0][0] < cutoff:
                    _, player_uuid = queue.popleft()
                    counts[player_uuid] -= 1
                    if counts[player_uuid] <= 0:
                        del counts[player_uuid]
            current_date = target_ordinal
        output[(game_id, team_id)] = {
            "current": set(observed[(team_id, season)]),
            "trailing": set(trailing_counts[team_id]),
            "priorSeason": set(observed[(team_id, season - 1)]),
        }
    return output


def _float_field(name: str) -> pa.Field:
    return pa.field(name, pa.float64(), nullable=True)


def _lineup_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("candidate_row_id", pa.string(), nullable=False),
            pa.field("game_id", pa.string(), nullable=False),
            pa.field("game_date", pa.string(), nullable=False),
            pa.field("season", pa.int16(), nullable=False),
            pa.field("team_id", pa.string(), nullable=False),
            pa.field("canonical_player_uuid", pa.string(), nullable=False),
            pa.field("target_start", pa.bool_(), nullable=False),
            pa.field("target_batting_order", pa.int8(), nullable=True),
            pa.field("actual_lineup_size", pa.int8(), nullable=False),
            pa.field("complete_lineup_eligible", pa.bool_(), nullable=False),
            pa.field("pool_current_season", pa.bool_(), nullable=False),
            pa.field("pool_trailing_45d", pa.bool_(), nullable=False),
            pa.field("pool_prior_season_early", pa.bool_(), nullable=False),
            *[_float_field(name) for name in LINEUP_FEATURES],
        ]
    )


def _starter_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("target_row_id", pa.string(), nullable=False),
            pa.field("game_id", pa.string(), nullable=False),
            pa.field("game_date", pa.string(), nullable=False),
            pa.field("season", pa.int16(), nullable=False),
            pa.field("team_id", pa.string(), nullable=False),
            pa.field("canonical_player_uuid", pa.string(), nullable=False),
            pa.field("conditioning", pa.string(), nullable=False),
            pa.field("target_bfp", pa.int16(), nullable=False),
            pa.field("target_outs", pa.int16(), nullable=False),
            *[_float_field(name) for name in STARTER_FEATURES],
        ]
    )


def _bullpen_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("candidate_row_id", pa.string(), nullable=False),
            pa.field("game_id", pa.string(), nullable=False),
            pa.field("game_date", pa.string(), nullable=False),
            pa.field("season", pa.int16(), nullable=False),
            pa.field("team_id", pa.string(), nullable=False),
            pa.field("canonical_player_uuid", pa.string(), nullable=False),
            pa.field("target_appearance", pa.bool_(), nullable=False),
            pa.field("target_bfp", pa.int16(), nullable=True),
            pa.field("target_outs", pa.int16(), nullable=True),
            pa.field("actual_team_reliever_count", pa.int8(), nullable=False),
            pa.field("pool_current_season", pa.bool_(), nullable=False),
            pa.field("pool_trailing_30d", pa.bool_(), nullable=False),
            pa.field("pool_prior_season_early", pa.bool_(), nullable=False),
            *[_float_field(name) for name in BULLPEN_FEATURES],
        ]
    )


def _parquet(table: pa.Table, *, component: str, contract_sha: str, dynamic_binding: Mapping[str, Any]) -> bytes:
    metadata = {
        b"schemaVersion": FEATURE_VIEW_SCHEMA_VERSION.encode("ascii"),
        b"component": component.encode("ascii"),
        b"contractSha": contract_sha.encode("ascii"),
        b"dynamicBinding": canonical_json_bytes(dict(dynamic_binding)),
    }
    materialized = table.replace_schema_metadata(metadata)
    sink = pa.BufferOutputStream()
    pq.write_table(
        materialized,
        sink,
        compression="zstd",
        compression_level=9,
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=65_536,
    )
    return sink.getvalue().to_pybytes()


def build_participation_views_from_tables(
    batting_table: pa.Table,
    starter_table: pa.Table,
    bullpen_table: pa.Table,
    *,
    retrosheet_aliases: Mapping[str, str],
    dimension_uuids: frozenset[str],
    dynamic_state: DynamicStateSource | None,
    fixture_mode: bool = False,
    source_partition_ids: Sequence[str] = (),
    progress: Callable[[str, Mapping[str, Any]], None] | None = None,
) -> BuiltParticipationFeatureViews:
    """Pure deterministic builder shared by governed execution and small fixtures."""

    if not retrosheet_aliases or not isinstance(dimension_uuids, frozenset) or not dimension_uuids:
        raise ParticipationFeatureError("exact bridge aliases and dimension UUIDs are required")
    started = time.monotonic()

    def emit(stage: str, **evidence: Any) -> None:
        if progress is not None:
            progress(stage, {"stage": stage, "elapsedSeconds": time.monotonic() - started, **evidence})

    emit("NORMALIZING_PARTICIPATION_TARGETS")
    batting = _normalize_batting(
        batting_table, aliases=retrosheet_aliases, dimensions=dimension_uuids
    )
    starters = _normalize_pitching(
        starter_table,
        aliases=retrosheet_aliases,
        dimensions=dimension_uuids,
        label="starter_usage",
        starter=True,
    )
    relievers = _normalize_pitching(
        bullpen_table,
        aliases=retrosheet_aliases,
        dimensions=dimension_uuids,
        label="bullpen_usage",
        starter=False,
    )
    target_batting: dict[tuple[str, str], list[_BatEvent]] = defaultdict(list)
    for event in batting:
        if event.season in TARGET_SEASONS:
            target_batting[(event.game_id, event.team_id)].append(event)
    target_starters = [event for event in starters if event.season in TARGET_SEASONS]
    if not target_batting or not target_starters:
        raise ParticipationFeatureError("primary-season lineup/starter targets are required")
    starter_games: dict[tuple[str, str], _PitchEvent] = {}
    for event in target_starters:
        key = (event.game_id, event.team_id)
        if key in starter_games:
            raise ParticipationFeatureError("starter_usage must contain exactly one row per team-game")
        starter_games[key] = event
    if set(target_batting) != set(starter_games):
        raise ParticipationFeatureError("lineup and starter target team-games differ")
    target_game_teams: dict[str, list[tuple[int, list[_BatEvent]]]] = defaultdict(list)
    for (game_id, _team_id), rows in target_batting.items():
        target_game_teams[game_id].append((rows[0].season, rows))
    complete_lineup_eligible: dict[str, bool] = {}
    complete_games_by_season: Counter[int] = Counter()
    target_games_by_season: Counter[int] = Counter()
    for game_id, team_rows in target_game_teams.items():
        if not fixture_mode and len(team_rows) != 2:
            raise ParticipationFeatureError(
                "live complete-lineup authority requires exactly two teams per game"
            )
        seasons = {season for season, _rows in team_rows}
        if len(seasons) != 1:
            raise ParticipationFeatureError("complete-lineup game seasons differ")
        game_season = next(iter(seasons))
        target_games_by_season[game_season] += 1
        eligible = all(
            len([row for row in rows if row.started]) == 9
            and {row.batting_order for row in rows if row.started} == set(range(1, 10))
            for _season, rows in team_rows
        )
        complete_lineup_eligible[game_id] = eligible
        if eligible:
            complete_games_by_season[game_season] += 1
    if not fixture_mode and dict(complete_games_by_season) != dict(
        EXPECTED_COMPLETE_LINEUP_GAMES
    ):
        raise ParticipationFeatureError(
            "derived complete-lineup eligibility differs from the parent manifest authority"
        )
    early_cutoffs = _early_cutoffs(
        [(event.season, event.game_ordinal) for event in target_starters]
    )
    target_keys = [
        (event.game_ordinal, event.game_id, event.team_id, event.season, event.game_date)
        for event in target_starters
    ]

    lineup_pools = _candidate_pool_snapshots(
        batting, target_keys, trailing_days=LINEUP_TRAILING_POOL_DAYS
    )
    bullpen_pools = _candidate_pool_snapshots(
        relievers, target_keys, trailing_days=BULLPEN_TRAILING_POOL_DAYS
    )
    required_dynamic_keys: set[tuple[str, str, str]] = set()
    for target in target_starters:
        early = target.game_ordinal <= early_cutoffs[target.season]
        lineup_sources = lineup_pools[(target.game_id, target.team_id)]
        lineup_candidates = set(lineup_sources["current"]) | set(lineup_sources["trailing"])
        bullpen_sources = bullpen_pools[(target.game_id, target.team_id)]
        bullpen_candidates = set(bullpen_sources["current"]) | set(bullpen_sources["trailing"])
        if early:
            lineup_candidates |= set(lineup_sources["priorSeason"])
            bullpen_candidates |= set(bullpen_sources["priorSeason"])
        if complete_lineup_eligible[target.game_id]:
            required_dynamic_keys.update(
                (target.game_date, player_uuid, "BATTER")
                for player_uuid in lineup_candidates
            )
        required_dynamic_keys.update(
            (target.game_date, player_uuid, "PITCHER") for player_uuid in bullpen_candidates
        )
        required_dynamic_keys.add((target.game_date, target.player_uuid, "PITCHER"))
    dynamic_lookup, dynamic_binding = _dynamic_lookup(
        dynamic_state,
        fixture_mode=fixture_mode,
        required_keys=frozenset(required_dynamic_keys),
    )
    bat_history = _BatHistory(batting)
    starter_history = _PitchHistory(starters)
    bullpen_history = _PitchHistory(relievers)

    lineup_rows: list[dict[str, Any]] = []
    lineup_coverage: dict[int, dict[str, Any]] = {
        season: {
            "season": season,
            "targetTeamGames": 0,
            "candidateRows": 0,
            "actualPositiveRows": 0,
            "coveredPositiveRows": 0,
            "uncoveredPositiveRows": 0,
            "emptyCandidatePools": 0,
            "completePoolCoverageTeamGames": 0,
            "completeLineupEligibleGames": complete_games_by_season.get(season, 0),
            "completeLineupExcludedGames": (
                target_games_by_season.get(season, 0)
                - complete_games_by_season.get(season, 0)
            ),
            "eligibleTargetTeamGames": 0,
            "excludedTargetTeamGames": 0,
            "allTargetActualPositiveRows": 0,
        }
        for season in TARGET_SEASONS
    }
    emit("BUILDING_LINEUP_CANDIDATE_POOL")
    for item_index, target in enumerate(sorted(target_starters, key=lambda row: (row.game_ordinal, row.game_id, row.team_id))):
        key = (target.game_id, target.team_id)
        targets = target_batting[key]
        positives = {row.player_uuid: row for row in targets if row.started}
        evidence = lineup_coverage[target.season]
        evidence["targetTeamGames"] += 1
        evidence["allTargetActualPositiveRows"] += len(positives)
        if not complete_lineup_eligible[target.game_id]:
            evidence["excludedTargetTeamGames"] += 1
            continue
        if len(positives) != 9:
            raise ParticipationFeatureError(
                "eligible lineup target must contain exactly nine starter markers"
            )
        evidence["eligibleTargetTeamGames"] += 1
        early = target.game_ordinal <= early_cutoffs[target.season]
        sources = lineup_pools[key]
        candidates = set(sources["current"]) | set(sources["trailing"])
        if early:
            candidates |= set(sources["priorSeason"])
        covered = set(positives) & candidates
        evidence["candidateRows"] += len(candidates)
        evidence["actualPositiveRows"] += len(positives)
        evidence["coveredPositiveRows"] += len(covered)
        evidence["uncoveredPositiveRows"] += len(positives) - len(covered)
        evidence["emptyCandidatePools"] += int(not candidates)
        evidence["completePoolCoverageTeamGames"] += int(len(covered) == len(positives))
        for player_uuid in sorted(candidates):
            dynamic = dynamic_lookup.get((target.game_date, player_uuid, "BATTER"))
            if dynamic is None:
                if not fixture_mode:
                    raise ParticipationFeatureError("dynamic batter state is missing for a candidate row")
                dynamic = _fixture_dynamic()
            target_row = positives.get(player_uuid)
            row = {
                "candidate_row_id": f"lineup:{target.game_id}:{target.team_id}:{player_uuid}",
                "game_id": target.game_id,
                "game_date": target.game_date,
                "season": target.season,
                "team_id": target.team_id,
                "canonical_player_uuid": player_uuid,
                "target_start": target_row is not None,
                "target_batting_order": target_row.batting_order if target_row else None,
                "actual_lineup_size": len(positives),
                "complete_lineup_eligible": complete_lineup_eligible[target.game_id],
                "pool_current_season": player_uuid in sources["current"],
                "pool_trailing_45d": player_uuid in sources["trailing"],
                "pool_prior_season_early": early and player_uuid in sources["priorSeason"],
                **bat_history.features(
                    target.team_id,
                    player_uuid,
                    target.game_ordinal,
                    target.season,
                    early=early,
                    dynamic=dynamic,
                ),
            }
            lineup_rows.append(row)
        if progress is not None and (item_index + 1) % 1_000 == 0:
            emit("BUILDING_LINEUP_CANDIDATE_POOL", teamGamesProcessed=item_index + 1)

    starter_rows: list[dict[str, Any]] = []
    starter_coverage: dict[int, dict[str, Any]] = {
        season: {
            "season": season,
            "targetRows": 0,
            "dynamicRowsBound": 0,
            "fixtureDefaultDynamicRows": 0,
            "conditioning": "CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY",
        }
        for season in TARGET_SEASONS
    }
    emit("BUILDING_STARTER_DURATION_VIEW")
    for target in sorted(target_starters, key=lambda row: (row.game_ordinal, row.game_id, row.team_id)):
        early = target.game_ordinal <= early_cutoffs[target.season]
        dynamic = dynamic_lookup.get((target.game_date, target.player_uuid, "PITCHER"))
        coverage_item = starter_coverage[target.season]
        coverage_item["targetRows"] += 1
        if dynamic is None:
            if not fixture_mode:
                raise ParticipationFeatureError("dynamic pitcher state is missing for a starter row")
            dynamic = _fixture_dynamic()
            coverage_item["fixtureDefaultDynamicRows"] += 1
        else:
            coverage_item["dynamicRowsBound"] += 1
        starter_rows.append(
            {
                "target_row_id": f"starter:{target.usage_id}",
                "game_id": target.game_id,
                "game_date": target.game_date,
                "season": target.season,
                "team_id": target.team_id,
                "canonical_player_uuid": target.player_uuid,
                "conditioning": "CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY",
                "target_bfp": target.bfp,
                "target_outs": target.outs,
                **starter_history.starter_features(target, early=early, dynamic=dynamic),
            }
        )

    actual_relievers: dict[tuple[str, str], dict[str, _PitchEvent]] = defaultdict(dict)
    for event in relievers:
        if event.season not in TARGET_SEASONS:
            continue
        key = (event.game_id, event.team_id)
        if event.player_uuid in actual_relievers[key]:
            raise ParticipationFeatureError("bullpen target player is duplicated within a team-game")
        actual_relievers[key][event.player_uuid] = event
        if key not in starter_games:
            raise ParticipationFeatureError("bullpen target lacks its starter team-game backbone")

    bullpen_rows: list[dict[str, Any]] = []
    bullpen_coverage: dict[int, dict[str, Any]] = {
        season: {
            "season": season,
            "targetTeamGames": 0,
            "zeroRelieverTeamGames": 0,
            "candidateRows": 0,
            "actualPositiveRows": 0,
            "coveredPositiveRows": 0,
            "uncoveredPositiveRows": 0,
            "emptyCandidatePools": 0,
            "emptyPoolZeroRelieverTeamGames": 0,
            "emptyPoolPositiveRelieverTeamGames": 0,
            "emptyPoolActualPositiveRows": 0,
            "earlySeasonTeamGames": 0,
            "earlySeasonActualPositiveRows": 0,
            "completePoolCoverageTeamGames": 0,
        }
        for season in TARGET_SEASONS
    }
    emit("BUILDING_BULLPEN_CANDIDATE_POOL")
    for target in sorted(target_starters, key=lambda row: (row.game_ordinal, row.game_id, row.team_id)):
        key = (target.game_id, target.team_id)
        positives = actual_relievers.get(key, {})
        early = target.game_ordinal <= early_cutoffs[target.season]
        sources = bullpen_pools[key]
        candidates = set(sources["current"]) | set(sources["trailing"])
        if early:
            candidates |= set(sources["priorSeason"])
        covered = set(positives) & candidates
        evidence = bullpen_coverage[target.season]
        evidence["targetTeamGames"] += 1
        evidence["zeroRelieverTeamGames"] += int(not positives)
        evidence["candidateRows"] += len(candidates)
        evidence["actualPositiveRows"] += len(positives)
        evidence["coveredPositiveRows"] += len(covered)
        evidence["uncoveredPositiveRows"] += len(positives) - len(covered)
        evidence["emptyCandidatePools"] += int(not candidates)
        evidence["emptyPoolZeroRelieverTeamGames"] += int(not candidates and not positives)
        evidence["emptyPoolPositiveRelieverTeamGames"] += int(not candidates and bool(positives))
        evidence["emptyPoolActualPositiveRows"] += len(positives) if not candidates else 0
        evidence["earlySeasonTeamGames"] += int(early)
        evidence["earlySeasonActualPositiveRows"] += len(positives) if early else 0
        evidence["completePoolCoverageTeamGames"] += int(len(covered) == len(positives))
        for player_uuid in sorted(candidates):
            dynamic = dynamic_lookup.get((target.game_date, player_uuid, "PITCHER"))
            if dynamic is None:
                if not fixture_mode:
                    raise ParticipationFeatureError("dynamic pitcher state is missing for a bullpen candidate")
                dynamic = _fixture_dynamic()
            target_row = positives.get(player_uuid)
            bullpen_rows.append(
                {
                    "candidate_row_id": f"bullpen:{target.game_id}:{target.team_id}:{player_uuid}",
                    "game_id": target.game_id,
                    "game_date": target.game_date,
                    "season": target.season,
                    "team_id": target.team_id,
                    "canonical_player_uuid": player_uuid,
                    "target_appearance": target_row is not None,
                    "target_bfp": target_row.bfp if target_row else None,
                    "target_outs": target_row.outs if target_row else None,
                    "actual_team_reliever_count": len(positives),
                    "pool_current_season": player_uuid in sources["current"],
                    "pool_trailing_30d": player_uuid in sources["trailing"],
                    "pool_prior_season_early": early and player_uuid in sources["priorSeason"],
                    **bullpen_history.bullpen_features(
                        target.team_id,
                        player_uuid,
                        target.game_ordinal,
                        target.season,
                        early=early,
                        dynamic=dynamic,
                    ),
                }
            )

    lineup_table = pa.Table.from_pylist(lineup_rows, schema=_lineup_schema()).sort_by(
        [("season", "ascending"), ("game_date", "ascending"), ("game_id", "ascending"), ("team_id", "ascending"), ("canonical_player_uuid", "ascending")]
    )
    starter_view = pa.Table.from_pylist(starter_rows, schema=_starter_schema()).sort_by(
        [("season", "ascending"), ("game_date", "ascending"), ("game_id", "ascending"), ("team_id", "ascending")]
    )
    bullpen_table_out = pa.Table.from_pylist(bullpen_rows, schema=_bullpen_schema()).sort_by(
        [("season", "ascending"), ("game_date", "ascending"), ("game_id", "ascending"), ("team_id", "ascending"), ("canonical_player_uuid", "ascending")]
    )
    for by_season in (lineup_coverage, bullpen_coverage):
        for item in by_season.values():
            positives = item["actualPositiveRows"]
            item["poolCoverage"] = (
                float(item["coveredPositiveRows"] / positives) if positives else 1.0
            )
    for item in starter_coverage.values():
        item["dynamicCoverage"] = float(item["dynamicRowsBound"] / item["targetRows"])
    contracts_sha = contract_set_sha()
    parquet = {
        "lineup": _parquet(lineup_table, component="LINEUP_PROJECTION", contract_sha=contracts_sha, dynamic_binding=dynamic_binding),
        "starter": _parquet(starter_view, component="STARTER_DURATION", contract_sha=contracts_sha, dynamic_binding=dynamic_binding),
        "bullpen": _parquet(bullpen_table_out, component="BULLPEN_USAGE", contract_sha=contracts_sha, dynamic_binding=dynamic_binding),
    }
    content_shas = {name: sha256_bytes(content) for name, content in parquet.items()}
    combined = sha256_bytes(
        canonical_json_bytes(
            {
                "schemaVersion": FEATURE_VIEW_SCHEMA_VERSION,
                "contractSha": contracts_sha,
                "dynamicBinding": dynamic_binding,
                "componentContentShas": content_shas,
                "rowCounts": {
                    "lineup": lineup_table.num_rows,
                    "starter": starter_view.num_rows,
                    "bullpen": bullpen_table_out.num_rows,
                },
            }
        )
    )
    emit(
        "PARTICIPATION_FEATURE_VIEWS_COMPLETE",
        lineupRows=lineup_table.num_rows,
        starterRows=starter_view.num_rows,
        bullpenRows=bullpen_table_out.num_rows,
    )
    return BuiltParticipationFeatureViews(
        lineup=lineup_table,
        starter=starter_view,
        bullpen=bullpen_table_out,
        coverage={
            "lineup": tuple(lineup_coverage[season] for season in TARGET_SEASONS),
            "starter": tuple(starter_coverage[season] for season in TARGET_SEASONS),
            "bullpen": tuple(bullpen_coverage[season] for season in TARGET_SEASONS),
        },
        dynamic_binding=dynamic_binding,
        contract_sha=contracts_sha,
        content_shas=content_shas,
        combined_content_sha=combined,
        parquet_bytes=parquet,
        source_partition_ids=tuple(sorted(str(item) for item in source_partition_ids)),
    )


def _validate_authorities(parent: ValidatedPackage, bridge: ValidatedIdentityBridge) -> None:
    if not isinstance(parent, ValidatedPackage) or not isinstance(bridge, ValidatedIdentityBridge):
        raise TypeError("governed construction requires already validated package and bridge objects")
    SportsDatasetManifestConsumer.validate_manifest_contract(parent.manifest)
    MlbFd1IdentityBridgeAdapter.validate_manifest_contract(bridge.manifest)
    if parent.manifest.get("manifest_sha256") != MANIFEST_SHA or parent.partition_authority_sha != PARTITION_AUTHORITY_SHA:
        raise ParticipationFeatureError("parent dataset authorities differ")
    parent_binding = bridge.manifest.get("parent_binding")
    totals = bridge.manifest.get("totals")
    if (
        bridge.manifest.get("bridge_manifest_sha256") != BRIDGE_MANIFEST_SHA
        or not isinstance(parent_binding, Mapping)
        or parent_binding.get("parent_dataset_manifest_sha256") != MANIFEST_SHA
        or parent_binding.get("parent_partition_authority_sha256") != PARTITION_AUTHORITY_SHA
        or not isinstance(totals, Mapping)
        or totals.get("alias_authority_sha256") != ALIAS_AUTHORITY_SHA
        or totals.get("dimension_authority_sha256") != DIMENSION_AUTHORITY_SHA
    ):
        raise ParticipationFeatureError("identity bridge authorities differ")
    if filesystem_identity(parent.package_root) != parent.root_identity:
        raise ParticipationFeatureError("validated parent package root identity changed")
    if filesystem_identity(bridge.package_root) != bridge.root_identity:
        raise ParticipationFeatureError("validated bridge root identity changed")


def _safe_partition_path(parent: ValidatedPackage, partition: Mapping[str, Any]) -> Path:
    uri = validate_package_relative_uri(partition.get("package_relative_uri"))
    root = parent.package_root.resolve(strict=True)
    return _validate_resolved_child(root, root.joinpath(*PurePosixPath(uri).parts), logical_uri=uri)


def _read_family(
    parent: ValidatedPackage,
    family: str,
    columns: Sequence[str],
    *,
    progress: Callable[[str, Mapping[str, Any]], None] | None,
) -> tuple[pa.Table, list[str]]:
    partitions = sorted(
        [
            item
            for item in parent.partitions
            if item.get("family") == family and item.get("season") in HISTORY_SEASONS
        ],
        key=lambda item: (int(item["season"]), int(item.get("month") or 0), str(item["partition_id"])),
    )
    if not partitions:
        raise ParticipationFeatureError(f"registered {family} partitions are missing")
    tables: list[pa.Table] = []
    rows = 0
    for index, partition in enumerate(partitions, start=1):
        table = pq.read_table(_safe_partition_path(parent, partition), columns=list(columns), use_threads=False)
        if table.num_rows != partition.get("row_count"):
            raise ParticipationFeatureError(f"registered {family} partition row count changed")
        tables.append(table)
        rows += table.num_rows
        if progress is not None:
            progress(
                f"READING_{family.upper()}_PARTITIONS",
                {
                    "stage": f"READING_{family.upper()}_PARTITIONS",
                    "partitionsProcessed": index,
                    "partitionsTotal": len(partitions),
                    "rowsProcessed": rows,
                },
            )
    return pa.concat_tables(tables, promote_options="none"), [str(item["partition_id"]) for item in partitions]


def build_mlb_participation_feature_views_v1(
    parent: ValidatedPackage,
    identity_bridge: ValidatedIdentityBridge,
    *,
    dynamic_state: DynamicStateSource,
    progress: Callable[[str, Mapping[str, Any]], None] | None = None,
) -> BuiltParticipationFeatureViews:
    """Read only the registered authorities and build the governed Milestone B views."""

    _validate_authorities(parent, identity_bridge)
    batting, batting_ids = _read_family(
        parent, "player_game_batting", _BATTING_COLUMNS, progress=progress
    )
    starters, starter_ids = _read_family(
        parent, "starter_usage", _STARTER_COLUMNS, progress=progress
    )
    bullpen, bullpen_ids = _read_family(
        parent, "bullpen_usage", _BULLPEN_COLUMNS, progress=progress
    )
    for family, table in (
        ("player_game_batting", batting),
        ("starter_usage", starters),
        ("bullpen_usage", bullpen),
    ):
        if table.num_rows != EXPECTED_SOURCE_ROWS[family]:
            raise ParticipationFeatureError(f"{family} source row count differs")
    for family, table in (("starter_usage", starters), ("bullpen_usage", bullpen)):
        seasons = table["season"].combine_chunks().to_pylist()
        observed = Counter(int(value) for value in seasons if int(value) in TARGET_SEASONS)
        if dict(observed) != dict(EXPECTED_TARGET_ROWS[family]):
            raise ParticipationFeatureError(f"{family} target-season row counts differ")
    return build_participation_views_from_tables(
        batting,
        starters,
        bullpen,
        retrosheet_aliases=identity_bridge.retrosheet_aliases,
        dimension_uuids=identity_bridge.dimension_uuids,
        dynamic_state=dynamic_state,
        fixture_mode=False,
        source_partition_ids=[*batting_ids, *starter_ids, *bullpen_ids],
        progress=progress,
    )


__all__ = [
    "BuiltParticipationFeatureViews",
    "DYNAMIC_REQUIRED_COLUMNS",
    "EXPECTED_COMPLETE_LINEUP_GAMES",
    "DynamicStateSource",
    "EXPECTED_SOURCE_ROWS",
    "EXPECTED_TARGET_ROWS",
    "FEATURE_VIEW_SCHEMA_VERSION",
    "ParticipationFeatureError",
    "build_mlb_participation_feature_views_v1",
    "build_participation_views_from_tables",
]
