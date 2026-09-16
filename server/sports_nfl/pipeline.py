"""End-to-end NFL data-foundation acquisition, normalization, and publication."""
from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb

from ..persistence.db import Database
from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from .bronze_acquisition import acquire_nflverse_bronze, verify_nflverse_bronze
from .canonical import materialize_canonical_silver
from .gold import FEATURE_ERA_CONTRACTS, FEATURE_FAMILY_CATALOG, materialize_gold
from .publication import publish_foundation, verify_foundation
from .registry import NFL_DATASET_ID, register_nfl_foundation
from .source_contracts import MANDATORY_FAMILIES, NFLVERSE_SOURCE_FAMILIES


DEFAULT_STAGING_ROOT = Path(r"C:\Users\james\asp-data-staging\nfl")
ALL_SEASONS = tuple(range(1920, 2027))


class NflFoundationError(RuntimeError):
    """A mandatory NFL foundation invariant failed."""


@dataclass(frozen=True)
class NflFoundationConfig:
    staging_root: Path = DEFAULT_STAGING_ROOT
    database_path: Path = Path(r".runtime\asp-model-studio\persistence\asp_model_studio.db")
    registered_by: str = "nfl-foundation-builder"
    seasons: tuple[int, ...] = ALL_SEASONS
    include_optional: bool = True
    acquire_sources: bool = True

    @property
    def bronze_root(self) -> Path:
        return Path(self.staging_root) / "bronze-v1"

    @property
    def foundation_root(self) -> Path:
        return Path(self.staging_root) / "foundation-v1"

    @property
    def report_root(self) -> Path:
        return Path(self.staging_root) / "reports"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _path(root: Path, partition: Mapping[str, Any]) -> Path:
    return (Path(root) / str(partition["relativePath"])).resolve()


def _source_coverage(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in manifest.get("partitions") or []:
        grouped[str(item["familyId"])].append(item)
    missing_by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in manifest.get("optionalMissing") or []:
        missing_by_family[str(item["familyId"])].append(item)
    results = []
    for family_id in manifest.get("requestedFamilies") or []:
        contract = NFLVERSE_SOURCE_FAMILIES[family_id]
        parts = grouped.get(family_id, [])
        seasons = sorted(
            {
                int(value)
                for item in parts
                for value in (
                    list((item.get("coverage") or {}).get("seasons") or [])
                    + ([item.get("season")] if item.get("season") is not None else [])
                )
            }
        )
        dates = [
            str(value)
            for item in parts
            for value in ((item.get("coverage") or {}).get("minimumDate"), (item.get("coverage") or {}).get("maximumDate"))
            if value
        ]
        rows_by_season: dict[int, int] = defaultdict(int)
        for item in parts:
            season_counts = (item.get("coverage") or {}).get("rowCountsBySeason") or []
            for season_count in season_counts:
                rows_by_season[int(season_count["season"])] += int(season_count["rowCount"])
            # Some nflverse season-scoped assets (participation, FTN, depth,
            # and the valid zero-row 2012 snap file) do not carry a physical
            # season column.  Their governed release partition still binds an
            # exact season, which is the truthful authority for coverage.
            if not season_counts and item.get("season") is not None:
                rows_by_season[int(item["season"])] += int(item["rowCount"])
        results.append(
            {
                "familyId": family_id,
                "mandatory": contract.mandatory,
                "status": (
                    "COMPLETE"
                    if parts and not missing_by_family.get(family_id)
                    else "PARTIAL"
                    if parts
                    else "NOT_AVAILABLE"
                ),
                "partitionCount": len(parts),
                "rowCount": sum(int(item["rowCount"]) for item in parts),
                "byteCount": sum(int(item["byteCount"]) for item in parts),
                "seasons": seasons,
                "rowsBySeason": [
                    {"season": season, "rowCount": rows_by_season[season]}
                    for season in sorted(rows_by_season)
                ],
                "minimumDate": min(dates) if dates else None,
                "maximumDate": max(dates) if dates else None,
                "missingSeasons": [item.get("season") for item in missing_by_family.get(family_id, [])],
                "releaseTags": sorted({str(item["releaseTag"]) for item in parts}),
                "latestSourceUpdate": max((str(item["assetUpdatedAt"]) for item in parts), default=None),
                "licenseIds": sorted({str((item.get("license") or {}).get("id")) for item in parts}),
                "schemaVariantCount": len({str(item["physicalSchemaSha256"]) for item in parts}),
            }
        )
    return results


def _sql_path(path: Path) -> str:
    return "'" + str(path).replace("'", "''").replace("\\", "/") + "'"


def _quality_report(
    bronze_root: Path,
    bronze: Mapping[str, Any],
    silver: Mapping[str, Any],
    gold: Mapping[str, Any],
) -> dict[str, Any]:
    by_family = defaultdict(list)
    for item in bronze.get("partitions") or []:
        by_family[item["familyId"]].append(_path(bronze_root, item))
    schedule = by_family["schedules"][0]
    pbp_paths = by_family["play_by_play"]
    players = Path(silver["byName"]["dim_nfl_player"]["path"])
    rosters = Path(silver["byName"]["snapshot_nfl_seasonal_roster"]["path"])
    player_stats = Path(silver["byName"]["fact_nfl_player_week"]["path"])
    dim_game = Path(silver["byName"]["dim_nfl_game"]["path"])
    fact_play = Path(silver["byName"]["fact_nfl_play"]["path"])
    market = Path(silver["byName"]["snapshot_nfl_market_line"]["path"])
    gold_game = Path(gold["byName"]["gold_nfl_game_pregame_v1"]["path"])
    gold_play = Path(gold["byName"]["gold_nfl_play_state_v1"]["path"])
    pbp_literal = "[" + ",".join(_sql_path(path) for path in pbp_paths) + "]"
    connection = duckdb.connect(database=":memory:")
    try:
        schedule_by_season_type = [
            {"season": int(row[0]), "gameType": row[1], "scheduledGames": int(row[2]), "completedGames": int(row[3])}
            for row in connection.execute(
                f"SELECT season, game_type, count(*), count(*) FILTER (WHERE home_score IS NOT NULL AND away_score IS NOT NULL) "
                f"FROM read_parquet({_sql_path(schedule)}) GROUP BY season, game_type ORDER BY season, game_type"
            ).fetchall()
        ]
        pbp_by_season_type = [
            {"season": int(row[0]), "gameType": row[1], "games": int(row[2]), "plays": int(row[3])}
            for row in connection.execute(
                f"SELECT season, season_type, count(DISTINCT game_id), count(*) "
                f"FROM read_parquet({pbp_literal}, union_by_name=true) GROUP BY season, season_type ORDER BY season, season_type"
            ).fetchall()
        ]
        pbp_duplicates = int(connection.execute(
            f"SELECT coalesce(sum(n-1),0) FROM (SELECT count(*) n FROM read_parquet({_sql_path(fact_play)}) "
            "GROUP BY canonical_game_id, canonical_play_id HAVING count(*) > 1)"
        ).fetchone()[0])
        schedule_duplicates = int(connection.execute(
            f"SELECT coalesce(sum(n-1),0) FROM (SELECT count(*) n FROM read_parquet({_sql_path(dim_game)}) "
            "GROUP BY canonical_game_id HAVING count(*) > 1)"
        ).fetchone()[0])
        pbp_without_schedule = int(connection.execute(
            f"SELECT count(*) FROM (SELECT DISTINCT canonical_game_id FROM read_parquet({_sql_path(fact_play)})) p "
            f"LEFT JOIN read_parquet({_sql_path(dim_game)}) g USING(canonical_game_id) WHERE g.canonical_game_id IS NULL"
        ).fetchone()[0])
        completed_without_pbp = int(connection.execute(
            f"SELECT count(*) FROM read_parquet({_sql_path(dim_game)}) g LEFT JOIN "
            f"(SELECT DISTINCT canonical_game_id FROM read_parquet({_sql_path(fact_play)})) p USING(canonical_game_id) "
            "WHERE g.game_state='FINAL' AND g.game_type IN ('REG','POST','WC','DIV','CON','SB') AND g.season BETWEEN 1999 AND 2025 "
            "AND p.canonical_game_id IS NULL"
        ).fetchone()[0])
        impossible_clock = int(connection.execute(
            f"SELECT count(*) FROM read_parquet({_sql_path(fact_play)}) "
            "WHERE quarter < 1 OR quarter > 10 OR game_seconds_remaining < 0 OR game_seconds_remaining > 3600"
        ).fetchone()[0])
        impossible_scores = int(connection.execute(
            f"SELECT count(*) FROM read_parquet({_sql_path(dim_game)}) WHERE home_points < 0 OR away_points < 0"
        ).fetchone()[0])
        player_duplicate_ids = int(connection.execute(
            f"SELECT count(*) FROM (SELECT canonical_player_id FROM read_parquet({_sql_path(players)}) "
            "WHERE canonical_player_id IS NOT NULL GROUP BY canonical_player_id HAVING count(*) > 1)"
        ).fetchone()[0])
        roster_missing_gsis = int(connection.execute(
            f"SELECT count(*) FROM read_parquet({_sql_path(rosters)}) WHERE gsis_id IS NULL OR trim(gsis_id)=''"
        ).fetchone()[0])
        stat_unresolved_players = int(connection.execute(
            f"SELECT count(*) FROM (SELECT DISTINCT player_id FROM read_parquet({_sql_path(player_stats)}) "
            f"WHERE player_id IS NOT NULL) s LEFT JOIN read_parquet({_sql_path(players)}) p "
            "ON s.player_id=p.canonical_player_id WHERE p.canonical_player_id IS NULL"
        ).fetchone()[0])
        market_rows, market_two_sided_ml, market_spread, market_total = connection.execute(
            f"SELECT count(*), count(*) FILTER (WHERE away_moneyline IS NOT NULL AND home_moneyline IS NOT NULL), "
            "count(*) FILTER (WHERE spread_line IS NOT NULL AND away_spread_price IS NOT NULL AND home_spread_price IS NOT NULL), "
            "count(*) FILTER (WHERE total_line IS NOT NULL AND over_price IS NOT NULL AND under_price IS NOT NULL) "
            f"FROM read_parquet({_sql_path(market)})"
        ).fetchone()
        current_schedule = connection.execute(
            f"SELECT count(*), count(*) FILTER (WHERE game_state='FINAL'), min(game_date), max(game_date) "
            f"FROM read_parquet({_sql_path(dim_game)}) WHERE season=2026"
        ).fetchone()
        current_completed_pbp = connection.execute(
            f"SELECT count(*) FILTER (WHERE p.canonical_game_id IS NOT NULL), "
            "count(*) FILTER (WHERE p.canonical_game_id IS NULL), max(g.game_date) "
            f"FROM read_parquet({_sql_path(dim_game)}) g LEFT JOIN "
            f"(SELECT DISTINCT canonical_game_id FROM read_parquet({_sql_path(fact_play)})) p USING(canonical_game_id) "
            "WHERE g.season=2026 AND g.game_state='FINAL'"
        ).fetchone()
        gold_counts = connection.execute(
            f"SELECT (SELECT count(*) FROM read_parquet({_sql_path(gold_game)})), "
            f"(SELECT count(*) FROM read_parquet({_sql_path(gold_play)}))"
        ).fetchone()
    finally:
        connection.close()
    return {
        "scheduleBySeasonAndGameType": schedule_by_season_type,
        "pbpBySeasonAndGameType": pbp_by_season_type,
        "identity": {
            "duplicateGameIdentities": schedule_duplicates,
            "duplicatePlayIdentities": pbp_duplicates,
            "duplicateCanonicalPlayerIdentities": player_duplicate_ids,
            "rosterRowsMissingGsisId": roster_missing_gsis,
            "unresolvedDistinctStatPlayerIds": stat_unresolved_players,
            "ambiguousIdentityCount": 0,
        },
        "reconciliation": {
            "pbpGamesWithoutSchedule": pbp_without_schedule,
            "completed1999To2025RegPostGamesWithoutPbp": completed_without_pbp,
        },
        "stateQuality": {"impossibleClockRows": impossible_clock, "impossibleScoreGames": impossible_scores},
        "marketCoverage": {
            "records": int(market_rows), "completeTwoSidedMoneyline": int(market_two_sided_ml),
            "completeTwoSidedSpread": int(market_spread), "completeTwoSidedTotal": int(market_total),
            "timingSemantics": "MARKET_SNAPSHOT_TIMING_UNPROVEN", "corePredictorEligible": False,
        },
        "current2026": {
            "scheduledGames": int(current_schedule[0]), "completedGames": int(current_schedule[1]),
            "minimumDate": current_schedule[2].isoformat() if current_schedule[2] else None,
            "maximumDate": current_schedule[3].isoformat() if current_schedule[3] else None,
            "completedGameEvidence": "NOT_YET_AVAILABLE" if int(current_schedule[1]) == 0 else "AVAILABLE",
            "completedGamesWithPbp": int(current_completed_pbp[0]),
            "completedGamesWithoutPbp": int(current_completed_pbp[1]),
            "latestCompletedGameDate": current_completed_pbp[2].isoformat() if current_completed_pbp[2] else None,
            "evidenceScope": "VERIFIED_INGESTED_SOURCES_NOT_PROVIDER_AVAILABILITY",
        },
        "gold": {"pregameGames": int(gold_counts[0]), "eligiblePlayStates": int(gold_counts[1])},
        "modelsFitted": 0,
    }


def _rights(bronze: Mapping[str, Any]) -> list[dict[str, Any]]:
    present = {str(item["familyId"]) for item in bronze.get("partitions") or []}
    records = [
        {
            "rightsControlId": "nflverse-data-cc-by-4.0",
            "displayName": "nflverse-data release assets",
            "sourceName": "nflverse / nflverse-data",
            "status": "LOCAL_PRIVATE_RESEARCH",
            "allowedUses": ["LOCAL_PRIVATE_RESEARCH", "INTERNAL_DATA_QUALITY_REVIEW"],
            "prohibitedUses": ["PUBLIC_REDISTRIBUTION_WITHOUT_SOURCE_REVIEW", "REAL_MONEY_WAGERING_EXECUTION"],
            "attribution": "nflverse / nflverse-data; individual upstream fields retain their own rights boundaries.",
            "controls": {"sourceSpecificReviewRequired": True, "rawDataCommittedToGit": False},
            "metadata": {"licenseId": "CC-BY-4.0", "thirdPartyRightsNotAssumed": True},
        }
    ]
    if present & {"participation", "ftn_charting"}:
        records.append(
            {
                "rightsControlId": "ftn-participation-cc-by-sa-4.0",
                "displayName": "FTN charting and participation",
                "sourceName": "FTN Data via nflverse",
                "status": "LOCAL_PRIVATE_RESEARCH_SHARE_ALIKE",
                "allowedUses": ["LOCAL_PRIVATE_RESEARCH"],
                "prohibitedUses": ["PUBLIC_REDISTRIBUTION_WITHOUT_ATTRIBUTION_AND_SHARE_ALIKE_REVIEW"],
                "attribution": "FTN Data via nflverse",
                "controls": {"shareAlikeReviewRequired": True},
                "metadata": {"licenseId": "CC-BY-SA-4.0"},
            }
        )
    if present & {"pfr_advanced_passing", "pfr_advanced_rushing", "pfr_advanced_receiving", "pfr_advanced_defense", "contracts"}:
        records.append(
            {
                "rightsControlId": "third-party-upstream-boundary",
                "displayName": "PFR / OverTheCap-derived enrichment boundary",
                "sourceName": "Upstream third-party evidence distributed through nflverse",
                "status": "RIGHTS_UNRESOLVED_FOR_REDISTRIBUTION",
                "allowedUses": ["LOCAL_PRIVATE_RESEARCH"],
                "prohibitedUses": ["PUBLIC_REDISTRIBUTION", "COMMERCIAL_REUSE_WITHOUT_REVIEW"],
                "attribution": "Preserve nflverse and named upstream-source attribution.",
                "controls": {"rightsReviewRequiredBeforeBroaderUse": True},
                "metadata": {},
            }
        )
    return records


def _limitations(bronze: Mapping[str, Any], quality: Mapping[str, Any]) -> list[dict[str, Any]]:
    optional = bronze.get("optionalMissing") or []
    current = quality["current2026"]
    return [
        {
            "limitationId": "nfl-2026-ingested-completed-game-coverage",
            "scope": "CURRENT_SEASON",
            "description": (
                f"Verified ingested 2026 schedule has {current['completedGames']} completed games; "
                f"{current['completedGamesWithPbp']} have PBP and {current['completedGamesWithoutPbp']} do not. "
                "These are local coverage counts, not a claim that newer provider evidence is unavailable. "
                "Only completed prior-date evidence enters the unchanged rolling feature definition."
            ),
        },
        {
            "limitationId": "nfl-market-timing-unproven",
            "scope": "MARKET_LINES",
            "description": "Schedule market fields have no quote-observation timestamp; they remain separate benchmark evidence and are not called opening or closing lines.",
        },
        {
            "limitationId": "nfl-starter-weather-timing-unproven",
            "scope": "PREGAME_FEATURES",
            "description": "Schedule starter and weather fields lack a governed pregame observation timestamp and are excluded from the core Gold predictor contract.",
        },
        {
            "limitationId": "nfl-source-era-gaps",
            "scope": "OPTIONAL_ENRICHMENTS",
            "description": f"Advanced families begin in later eras and {len(optional)} requested optional season/assets were unavailable; missing eras are explicit rather than zero-filled.",
        },
        {
            "limitationId": "nfl-name-only-identity-prohibited",
            "scope": "IDENTITY",
            "description": f"Rows lacking governed GSIS/source identifiers remain unresolved; roster missing GSIS rows={quality['identity']['rosterRowsMissingGsisId']} and no name-only fuzzy match is authorized.",
        },
    ]


def _feature_era_coverage(quality: Mapping[str, Any]) -> dict[str, Any]:
    """Describe observed source coverage without changing the frozen Gold contract."""
    eras = {name: dict(value) for name, value in FEATURE_ERA_CONTRACTS.items()}
    current = quality["current2026"]
    eras["CURRENT_SEASON"] = {
        "season": 2026,
        "materializationState": (
            "COMPLETED_PRIOR_GAME_EVIDENCE_IN_CORE_ROLLING_FEATURES"
            if current["completedGamesWithPbp"] else
            "SCHEDULE_SCORES_ONLY_PENDING_INGESTED_PBP"
            if current["completedGames"] else
            "NO_COMPLETED_GAMES_IN_INGESTED_SCHEDULE"
        ),
        "completedGames": current["completedGames"],
        "completedGamesWithPbp": current["completedGamesWithPbp"],
        "completedGamesWithoutPbp": current["completedGamesWithoutPbp"],
        "targetGameOutcomesEligible": False,
        "featureDefinitionsChanged": False,
    }
    return eras


def build_nfl_foundation(config: NflFoundationConfig = NflFoundationConfig()) -> dict[str, Any]:
    families: Sequence[str] = tuple(NFLVERSE_SOURCE_FAMILIES) if config.include_optional else MANDATORY_FAMILIES
    if config.acquire_sources:
        bronze_sha = acquire_nflverse_bronze(config.bronze_root, config.seasons, family_ids=families)
        bronze = verify_nflverse_bronze(config.bronze_root, bronze_sha)
    else:
        bronze = verify_nflverse_bronze(config.bronze_root)
        bronze_sha = sha256_bytes(canonical_json_bytes(bronze))
        if set(bronze.get("requestedFamilies") or []) != set(families):
            raise NflFoundationError("verified Bronze family scope differs from the requested foundation")
    silver = materialize_canonical_silver(config.bronze_root, config.foundation_root, bronze_manifest_sha=bronze_sha)
    gold = materialize_gold(config.foundation_root, silver["byName"])
    quality = _quality_report(config.bronze_root, bronze, silver, gold)
    if quality["identity"]["duplicateGameIdentities"] or quality["identity"]["duplicatePlayIdentities"]:
        raise NflFoundationError("canonical NFL game/play identity is duplicated")
    if quality["reconciliation"]["pbpGamesWithoutSchedule"]:
        raise NflFoundationError("one or more canonical PBP games lack schedule identity")
    source_families = _source_coverage(bronze)
    missing_mandatory = [item["familyId"] for item in source_families if item["mandatory"] and item["status"] != "COMPLETE"]
    if missing_mandatory:
        raise NflFoundationError(f"mandatory NFL source families incomplete: {missing_mandatory}")
    schedule_rows = quality["scheduleBySeasonAndGameType"]
    coverage = {
        "seasons": sorted({int(item["season"]) for item in schedule_rows}),
        "minimumDate": min(
            str((item.get("coverage") or {}).get("minimumDate"))
            for item in bronze["partitions"] if item["familyId"] == "schedules"
        ),
        "maximumDate": max(
            str((item.get("coverage") or {}).get("maximumDate"))
            for item in bronze["partitions"] if item["familyId"] == "schedules"
        ),
        "sourceFamilies": source_families,
        "mandatoryFamiliesComplete": True,
        "optionalFamiliesPresent": [item["familyId"] for item in source_families if not item["mandatory"] and item["status"] == "COMPLETE"],
        "optionalFamiliesMissing": [item["familyId"] for item in source_families if not item["mandatory"] and item["status"] != "COMPLETE"],
        "featureEraContracts": _feature_era_coverage(quality),
        "currentSeasonScheduledGames": quality["current2026"]["scheduledGames"],
        "currentSeasonCompletedGames": quality["current2026"]["completedGames"],
        "syncHealth": {"status": "INITIAL_FOUNDATION_COMPLETE", "latestSuccessfulAtUtc": datetime.now(timezone.utc).isoformat()},
    }
    source_authority = {**bronze, "manifestSha256": bronze_sha}
    published_at = datetime.now(timezone.utc).isoformat()
    objects = list(silver["objects"]) + list(gold["objects"])
    foundation = publish_foundation(
        config.foundation_root, dataset_id=NFL_DATASET_ID, objects=objects,
        source_manifest=source_authority, coverage=coverage, quality=quality,
        feature_families=FEATURE_FAMILY_CATALOG, limitations=_limitations(bronze, quality),
        rights=_rights(bronze), published_at=published_at,
    )
    database = Database(config.database_path)
    database.initialize()
    registration = register_nfl_foundation(
        database, foundation, user_id=config.registered_by,
        logical_root=f"nfl-foundation://sha256/{foundation['manifestSha256']}",
    )
    report = {
        "status": "COMPLETE", "builtAtUtc": published_at,
        "bronzeManifestSha256": bronze_sha,
        "foundationManifestSha256": foundation["manifestSha256"],
        "datasetVersionId": foundation["datasetVersionId"],
        "registration": registration, "coverage": coverage, "quality": quality,
        "objects": [
            {
                "layer": item["manifest"]["layer"], "tableName": item["manifest"]["tableName"],
                "rowCount": item["manifest"]["rowCount"], "manifestSha256": item["manifest"]["manifestSha256"],
            }
            for item in objects
        ],
        "featureFamilies": {key: list(value) for key, value in FEATURE_FAMILY_CATALOG.items()},
        "featureEraContracts": _feature_era_coverage(quality),
        "rights": foundation["manifest"]["rights"],
        "limitations": foundation["manifest"]["limitations"],
        "modelsFitted": 0, "modelsScored": 0, "modelsPromoted": 0,
    }
    _atomic_json(config.report_root / "current-foundation.json", report)
    return report


__all__ = ["ALL_SEASONS", "DEFAULT_STAGING_ROOT", "NflFoundationConfig", "NflFoundationError", "build_nfl_foundation"]
