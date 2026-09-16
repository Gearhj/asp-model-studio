"""Read-only NFL M1 data authority and population evidence.

This module deliberately does not materialize data or instantiate an estimator.
It resolves the immutable NFL Foundation publication, accounts for every game,
and exposes only predictor-safe feature and market-evaluation contracts.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_nfl.gold import GAME_GOLD_ID, MARKET_FIELDS, PLAY_GOLD_ID
from server.sports_nfl.publication import (
    CURRENT_CONTRACT,
    FOUNDATION_CONTRACT,
    verify_foundation,
    verify_parquet_object,
)


DEFAULT_NFL_STAGING_ROOT = Path(r"C:\Users\james\asp-data-staging\nfl")
GAME_TABLE = "gold_nfl_game_pregame_v1"
PLAY_TABLE = "gold_nfl_play_state_v1"
SCHEDULE_TABLE = "snapshot_nfl_schedule"
MARKET_TABLE = "snapshot_nfl_market_line"
FINAL_GAME_TYPES = frozenset({"REG", "POST", "WC", "DIV", "CON", "SB"})


class NflM1DataError(RuntimeError):
    """The registered NFL modeling population cannot be reconciled."""


@dataclass(frozen=True)
class FoundationPaths:
    foundation_root: Path
    dataset_id: str
    dataset_version_id: str
    foundation_manifest_sha256: str
    game_gold_id: str
    game_manifest_sha256: str
    game_path: Path
    game_row_count: int
    game_ordered_predictors: tuple[str, ...]
    play_gold_id: str
    play_manifest_sha256: str
    play_path: Path
    play_row_count: int
    schedule_manifest_sha256: str
    schedule_path: Path
    schedule_row_count: int
    market_manifest_sha256: str
    market_path: Path
    market_row_count: int
    feature_families: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class SeasonPopulation:
    season: int
    minimum_date: date
    maximum_date: date
    game_count: int
    regular_season_games: int
    postseason_games: int


@dataclass(frozen=True)
class GamePopulationAudit:
    source_schedule_rows: int
    gold_rows: int
    eligible_gold_rows: int
    duplicate_gold_identities: int
    gold_exclusions: Mapping[str, int]
    source_exclusions: Mapping[str, int]
    eligible_source_not_in_gold: tuple[str, ...]
    gold_not_in_eligible_source: tuple[str, ...]
    complete_eligible_seasons: tuple[int, ...]
    seasons: tuple[SeasonPopulation, ...]


@dataclass(frozen=True)
class MarketSeasonCoverage:
    season: int
    eligible_games: int
    joined_market_rows: int
    complete_two_sided_moneylines: int
    complete_two_sided_spreads: int
    complete_two_sided_totals: int


@dataclass(frozen=True)
class MarketCoverage:
    eligible_games: int
    joined_market_rows: int
    complete_two_sided_moneylines: int
    complete_two_sided_spreads: int
    complete_two_sided_totals: int
    unmatched_game_ids: tuple[str, ...]
    timing_semantics: tuple[str, ...]
    core_predictor_eligible_rows: int
    by_season: tuple[MarketSeasonCoverage, ...]


@dataclass(frozen=True)
class FeatureTierAvailability:
    tier: str
    status: str
    usable_columns: tuple[str, ...]
    unavailable_requirements: tuple[str, ...]
    distinct_from_long_history_core: bool
    reason: str


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NflM1DataError(f"invalid NFL authority JSON: {path}") from exc
    if not isinstance(value, dict):
        raise NflM1DataError(f"NFL authority JSON must be an object: {path}")
    return value


def _verify_required_foundation(
    root: Path, manifest_sha: str | None, *, deep_verify: bool
) -> dict[str, Any]:
    root = Path(root).resolve()
    current = _load_json(root / "current.json")
    if current.get("contract") != CURRENT_CONTRACT:
        raise NflM1DataError("NFL current pointer contract differs")
    current_sha = str(current.get("currentManifestSha256") or "")
    if manifest_sha is None:
        manifest_sha = current_sha
    elif manifest_sha != current_sha:
        raise NflM1DataError("requested NFL foundation is not the current registered authority")
    if deep_verify:
        return verify_foundation(root, manifest_sha)

    manifest_path = (
        root
        / "manifests"
        / "sha256"
        / manifest_sha
        / "foundation-manifest.json"
    )
    manifest = _load_json(manifest_path)
    if manifest.get("manifestContract") != FOUNDATION_CONTRACT:
        raise NflM1DataError("NFL foundation contract differs")
    body = {
        key: value
        for key, value in manifest.items()
        if key not in {"manifestSha256", "datasetVersionId"}
    }
    actual_sha = sha256_bytes(canonical_json_bytes(body))
    expected_version = f"{manifest.get('datasetId')}:sha256:{actual_sha}"
    if (
        actual_sha != manifest_sha
        or manifest.get("manifestSha256") != actual_sha
        or manifest.get("datasetVersionId") != expected_version
        or current.get("datasetVersionId") != expected_version
    ):
        raise NflM1DataError("NFL foundation/current identity differs")

    required_names = {GAME_TABLE, PLAY_TABLE, SCHEDULE_TABLE, MARKET_TABLE}
    refs = {
        str(item.get("tableName")): item
        for item in manifest.get("objects") or []
        if str(item.get("tableName")) in required_names
    }
    if set(refs) != required_names:
        raise NflM1DataError("NFL foundation lacks an M1-required object")
    verified_objects = []
    for table_name in sorted(required_names):
        ref = refs[table_name]
        verified = verify_parquet_object(root, str(ref.get("manifestSha256") or ""))
        for key in ("layer", "tableName", "rowCount", "fileSha256", "manifestSha256"):
            if canonical_json_bytes(ref.get(key)) != canonical_json_bytes(
                verified["manifest"].get(key)
            ):
                raise NflM1DataError(f"NFL foundation relationship differs: {table_name}/{key}")
        verified_objects.append(verified)
    return {
        "manifest": manifest,
        "manifestPath": manifest_path,
        "objects": verified_objects,
        "datasetVersionId": expected_version,
        "manifestSha256": actual_sha,
    }


def resolve_nfl_m1_authority(
    foundation_root: Path = DEFAULT_NFL_STAGING_ROOT / "foundation-v1",
    manifest_sha: str | None = None,
    *,
    deep_verify: bool = True,
) -> FoundationPaths:
    """Resolve and cryptographically verify the exact M1 input objects."""

    verified = _verify_required_foundation(
        Path(foundation_root), manifest_sha, deep_verify=deep_verify
    )
    by_name = {
        str(item["manifest"]["tableName"]): item for item in verified["objects"]
    }
    missing = {GAME_TABLE, PLAY_TABLE, SCHEDULE_TABLE, MARKET_TABLE} - set(by_name)
    if missing:
        raise NflM1DataError(f"verified NFL foundation lacks: {sorted(missing)}")
    game = by_name[GAME_TABLE]
    play = by_name[PLAY_TABLE]
    schedule = by_name[SCHEDULE_TABLE]
    market = by_name[MARKET_TABLE]
    game_contract = game["manifest"].get("tableContract") or {}
    play_contract = play["manifest"].get("tableContract") or {}
    if game_contract.get("datasetId") != GAME_GOLD_ID:
        raise NflM1DataError("NFL game Gold identity differs")
    if play_contract.get("datasetId") != PLAY_GOLD_ID:
        raise NflM1DataError("NFL play Gold identity differs")
    predictors = tuple(str(value) for value in game_contract.get("orderedPredictors") or ())
    physical = {str(item["name"]) for item in game["manifest"].get("schema") or []}
    if not predictors or not set(predictors).issubset(physical):
        raise NflM1DataError("NFL game predictor contract differs from physical schema")
    if set(MARKET_FIELDS) & set(predictors):
        raise NflM1DataError("market evidence appears in the NFL predictor contract")
    family_contracts = {
        str(name): tuple(str(value) for value in values)
        for name, values in (verified["manifest"].get("featureFamilies") or {}).items()
    }
    return FoundationPaths(
        foundation_root=Path(foundation_root).resolve(),
        dataset_id=str(verified["manifest"]["datasetId"]),
        dataset_version_id=str(verified["datasetVersionId"]),
        foundation_manifest_sha256=str(verified["manifestSha256"]),
        game_gold_id=GAME_GOLD_ID,
        game_manifest_sha256=str(game["manifest"]["manifestSha256"]),
        game_path=Path(game["path"]),
        game_row_count=int(game["manifest"]["rowCount"]),
        game_ordered_predictors=predictors,
        play_gold_id=PLAY_GOLD_ID,
        play_manifest_sha256=str(play["manifest"]["manifestSha256"]),
        play_path=Path(play["path"]),
        play_row_count=int(play["manifest"]["rowCount"]),
        schedule_manifest_sha256=str(schedule["manifest"]["manifestSha256"]),
        schedule_path=Path(schedule["path"]),
        schedule_row_count=int(schedule["manifest"]["rowCount"]),
        market_manifest_sha256=str(market["manifest"]["manifestSha256"]),
        market_path=Path(market["path"]),
        market_row_count=int(market["manifest"]["rowCount"]),
        feature_families=family_contracts,
    )


def _gold_exclusion_reason(row: Mapping[str, Any]) -> str | None:
    game_type = str(row.get("game_type") or "").upper()
    state = str(row.get("game_state") or "").upper()
    if game_type in {"PRE", "PRESEASON"}:
        return "PRESEASON"
    if not row.get("canonical_game_id") or not row.get("canonical_home_team_id") or not row.get("canonical_away_team_id"):
        return "INVALID_HOME_AWAY_IDENTITY"
    if state in {"CANCELLED", "CANCELED", "POSTPONED"}:
        return "CANCELLED_OR_POSTPONED"
    if state != "FINAL" or row.get("home_points") is None or row.get("away_points") is None:
        return "NO_FINAL_SCORE_TRUTH"
    if game_type not in FINAL_GAME_TYPES:
        return "UNSUPPORTED_GAME_TYPE"
    if float(row["home_points"]) < 0 or float(row["away_points"]) < 0:
        return "INVALID_FINAL_SCORE_TRUTH"
    return None


def _schedule_exclusion_reason(row: Mapping[str, Any]) -> str | None:
    game_type = str(row.get("game_type") or "").upper()
    if game_type in {"PRE", "PRESEASON"}:
        return "PRESEASON"
    if not row.get("game_id") or not row.get("home_team") or not row.get("away_team"):
        return "INVALID_HOME_AWAY_IDENTITY"
    if row.get("home_score") is None or row.get("away_score") is None:
        return "NO_FINAL_SCORE_TRUTH"
    if game_type not in FINAL_GAME_TYPES:
        return "UNSUPPORTED_GAME_TYPE"
    if float(row["home_score"]) < 0 or float(row["away_score"]) < 0:
        return "INVALID_FINAL_SCORE_TRUTH"
    return None


def _read_rows(path: Path, columns: Sequence[str]) -> list[dict[str, Any]]:
    try:
        return pq.read_table(Path(path), columns=list(columns)).to_pylist()
    except Exception as exc:  # pyarrow has several format/schema exception types
        raise NflM1DataError(f"cannot read registered NFL table: {path}") from exc


def load_eligible_games(paths: FoundationPaths) -> list[dict[str, Any]]:
    """Return eligible Gold games after explicit, reproducible accounting."""

    rows = _read_rows(paths.game_path, pq.read_schema(paths.game_path).names)
    exclusions = Counter(
        reason for row in rows if (reason := _gold_exclusion_reason(row)) is not None
    )
    if exclusions:
        raise NflM1DataError(
            f"registered NFL Gold contains excluded rows: {dict(sorted(exclusions.items()))}"
        )
    return rows


def audit_game_population(paths: FoundationPaths) -> GamePopulationAudit:
    gold_columns = (
        "canonical_game_id", "season", "game_type", "game_date",
        "canonical_home_team_id", "canonical_away_team_id", "home_points",
        "away_points", "game_state", "governed_population",
    )
    schedule_columns = (
        "game_id", "season", "game_type", "gameday", "home_team",
        "away_team", "home_score", "away_score",
    )
    gold = _read_rows(paths.game_path, gold_columns)
    schedule = _read_rows(paths.schedule_path, schedule_columns)
    if len(gold) != paths.game_row_count or len(schedule) != paths.schedule_row_count:
        raise NflM1DataError("registered NFL row count differs from physical data")

    identity_counts = Counter(str(row.get("canonical_game_id") or "") for row in gold)
    duplicate_rows = sum(count - 1 for identity, count in identity_counts.items() if identity and count > 1)
    gold_exclusions = Counter(
        reason for row in gold if (reason := _gold_exclusion_reason(row)) is not None
    )
    source_exclusions = Counter(
        reason for row in schedule if (reason := _schedule_exclusion_reason(row)) is not None
    )
    eligible_gold = [row for row in gold if _gold_exclusion_reason(row) is None]
    eligible_source = [row for row in schedule if _schedule_exclusion_reason(row) is None]
    gold_ids = {str(row["canonical_game_id"]) for row in eligible_gold}
    source_ids = {str(row["game_id"]) for row in eligible_source}

    by_season: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible_gold:
        by_season[int(row["season"])].append(row)
    seasons = []
    for season, season_rows in sorted(by_season.items()):
        dates = [row["game_date"] for row in season_rows]
        seasons.append(
            SeasonPopulation(
                season=season,
                minimum_date=min(dates),
                maximum_date=max(dates),
                game_count=len(season_rows),
                regular_season_games=sum(str(row["game_type"]).upper() == "REG" for row in season_rows),
                postseason_games=sum(str(row["game_type"]).upper() != "REG" for row in season_rows),
            )
        )

    source_by_season: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in schedule:
        source_by_season[int(row["season"])].append(row)
    complete_seasons = tuple(
        season
        for season, rows in sorted(source_by_season.items())
        if rows and all(_schedule_exclusion_reason(row) is None for row in rows)
    )
    audit = GamePopulationAudit(
        source_schedule_rows=len(schedule),
        gold_rows=len(gold),
        eligible_gold_rows=len(eligible_gold),
        duplicate_gold_identities=duplicate_rows,
        gold_exclusions=dict(sorted(gold_exclusions.items())),
        source_exclusions=dict(sorted(source_exclusions.items())),
        eligible_source_not_in_gold=tuple(sorted(source_ids - gold_ids)),
        gold_not_in_eligible_source=tuple(sorted(gold_ids - source_ids)),
        complete_eligible_seasons=complete_seasons,
        seasons=tuple(seasons),
    )
    if (
        duplicate_rows
        or audit.eligible_source_not_in_gold
        or audit.gold_not_in_eligible_source
        or audit.gold_exclusions
    ):
        raise NflM1DataError("registered NFL Gold population does not reconcile")
    return audit


def audit_market_coverage(
    paths: FoundationPaths, eligible_games: Sequence[Mapping[str, Any]]
) -> MarketCoverage:
    columns = (
        "canonical_game_id", "season", "home_moneyline", "away_moneyline",
        "spread_line", "home_spread_price", "away_spread_price", "total_line",
        "over_price", "under_price", "timing_semantics", "core_predictor_eligible",
    )
    market_rows = _read_rows(paths.market_path, columns)
    if len(market_rows) != paths.market_row_count:
        raise NflM1DataError("registered market row count differs from physical data")
    market_by_id: dict[str, dict[str, Any]] = {}
    duplicates = set()
    for row in market_rows:
        game_id = str(row.get("canonical_game_id") or "")
        if game_id in market_by_id:
            duplicates.add(game_id)
        market_by_id[game_id] = row
    if duplicates:
        raise NflM1DataError("market snapshot has duplicate game identities")

    grouped: dict[int, list[tuple[Mapping[str, Any], Mapping[str, Any] | None]]] = defaultdict(list)
    for game in eligible_games:
        grouped[int(game["season"])].append(
            (game, market_by_id.get(str(game["canonical_game_id"])))
        )

    def complete(row: Mapping[str, Any] | None, names: Sequence[str]) -> bool:
        return row is not None and all(row.get(name) is not None for name in names)

    season_results = []
    unmatched = []
    for season, joined in sorted(grouped.items()):
        for game, market in joined:
            if market is None:
                unmatched.append(str(game["canonical_game_id"]))
        season_results.append(
            MarketSeasonCoverage(
                season=season,
                eligible_games=len(joined),
                joined_market_rows=sum(market is not None for _, market in joined),
                complete_two_sided_moneylines=sum(
                    complete(market, ("home_moneyline", "away_moneyline"))
                    for _, market in joined
                ),
                complete_two_sided_spreads=sum(
                    complete(market, ("spread_line", "home_spread_price", "away_spread_price"))
                    for _, market in joined
                ),
                complete_two_sided_totals=sum(
                    complete(market, ("total_line", "over_price", "under_price"))
                    for _, market in joined
                ),
            )
        )
    semantics = tuple(
        sorted(
            {
                str(row["timing_semantics"])
                for row in market_rows
                if row.get("timing_semantics") is not None
            }
        )
    )
    return MarketCoverage(
        eligible_games=sum(item.eligible_games for item in season_results),
        joined_market_rows=sum(item.joined_market_rows for item in season_results),
        complete_two_sided_moneylines=sum(item.complete_two_sided_moneylines for item in season_results),
        complete_two_sided_spreads=sum(item.complete_two_sided_spreads for item in season_results),
        complete_two_sided_totals=sum(item.complete_two_sided_totals for item in season_results),
        unmatched_game_ids=tuple(sorted(unmatched)),
        timing_semantics=semantics,
        core_predictor_eligible_rows=sum(bool(row.get("core_predictor_eligible")) for row in market_rows),
        by_season=tuple(season_results),
    )


def assess_feature_tiers(paths: FoundationPaths) -> tuple[FeatureTierAvailability, ...]:
    """Classify the requested M1 tiers against the actual game-Gold columns."""

    schema = set(pq.read_schema(paths.game_path).names)
    core = tuple(paths.game_ordered_predictors)
    recent = tuple(
        name
        for name in core
        if any(token in name for token in ("_season_to_date", "_last_4", "_last_8", "_last_16"))
        or name in {"home_prior_season_games", "away_prior_season_games"}
    )
    rest = tuple(
        name
        for name in (
            "game_month", "game_weekday", "division_game", "roof", "surface",
            "home_days_since_previous_game", "away_days_since_previous_game",
            "home_short_week", "away_short_week", "home_bye_or_long_rest",
            "away_bye_or_long_rest",
        )
        if name in schema
    )
    return (
        FeatureTierAvailability(
            tier="LONG_HISTORY_CORE",
            status="MATERIALIZED",
            usable_columns=core,
            unavailable_requirements=(),
            distinct_from_long_history_core=False,
            reason=f"Exact {len(core)}-column registered game-Gold predictor contract.",
        ),
        FeatureTierAvailability(
            tier="CORE_PLUS_RECENT_FORM",
            status="PARTIAL_NOT_DISTINCT",
            usable_columns=recent,
            unavailable_requirements=(
                "previous_season_performance_carryover",
                "exponentially_weighted_recent_state",
            ),
            distinct_from_long_history_core=False,
            reason="Last-4/8/16 and season-to-date state are already inside LONG_HISTORY_CORE; no governed EW or prior-season-performance columns exist.",
        ),
        FeatureTierAvailability(
            tier="CORE_PLUS_QUARTERBACK",
            status="NOT_POINT_IN_TIME_MATERIALIZABLE",
            usable_columns=(),
            unavailable_requirements=tuple(paths.feature_families.get("QUARTERBACK", ())),
            distinct_from_long_history_core=False,
            reason="Only target-game quarterback observations with unproven timing are present and explicitly excluded from predictors.",
        ),
        FeatureTierAvailability(
            tier="CORE_PLUS_ROSTER_USAGE",
            status="SOURCE_TABLE_ONLY",
            usable_columns=(),
            unavailable_requirements=tuple(paths.feature_families.get("ROSTER_AND_USAGE", ())),
            distinct_from_long_history_core=False,
            reason="Roster/snap sources exist, but no game-level pregame-cutoff derivation is registered in Gold.",
        ),
        FeatureTierAvailability(
            tier="CORE_PLUS_REST_TRAVEL_WEATHER",
            status="PARTIAL",
            usable_columns=rest,
            unavailable_requirements=(
                "travel_distance", "time_zone_change", "local_kickoff_time",
                "point_in_time_weather",
            ),
            distinct_from_long_history_core=False,
            reason="Rest/calendar plus roof/surface are materialized; travel and governed pregame weather are not.",
        ),
        FeatureTierAvailability(
            tier="RECENT_RICH",
            status="SOURCE_TABLE_ONLY",
            usable_columns=(),
            unavailable_requirements=tuple(
                paths.feature_families.get("ADVANCED_TRACKING_AND_PARTICIPATION", ())
                + paths.feature_families.get("RECENT_CHARTING", ())
            ),
            distinct_from_long_history_core=False,
            reason="NGS/FTN/participation/snap evidence is published separately but has no registered pregame game-level feature derivation.",
        ),
        FeatureTierAvailability(
            tier="HIERARCHICAL_LONG_PLUS_RICH",
            status="DEPENDENCY_NOT_MATERIALIZED",
            usable_columns=core,
            unavailable_requirements=("point_in_time_recent_rich_residual_inputs",),
            distinct_from_long_history_core=False,
            reason="The long-history core is usable; the recent-rich correction inputs are not a game-Gold authority.",
        ),
    )


__all__ = [
    "DEFAULT_NFL_STAGING_ROOT",
    "FeatureTierAvailability",
    "FoundationPaths",
    "GamePopulationAudit",
    "MarketCoverage",
    "MarketSeasonCoverage",
    "NflM1DataError",
    "SeasonPopulation",
    "assess_feature_tiers",
    "audit_game_population",
    "audit_market_coverage",
    "load_eligible_games",
    "resolve_nfl_m1_authority",
]
