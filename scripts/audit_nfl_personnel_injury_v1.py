"""Reproduce the outcome-free NFL personnel/injury source audit and reports."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from server.sports_nfl_m1.personnel_capture import build_capture_plan
from server.sports_nfl_m1.personnel_evidence import canonical_json_bytes, status_vocabulary


DEFAULT_FOUNDATION = Path(r"C:\Users\james\asp-data-staging\nfl\foundation-v1")
DEFAULT_MANIFEST = DEFAULT_FOUNDATION / "manifests" / "sha256" / "c265041976e119fab5497f5b4f48a3cefe2db354af91f7144ede25065881d2bb" / "foundation-manifest.json"
DEFAULT_BRONZE_MANIFEST = Path(r"C:\Users\james\asp-data-staging\nfl\bronze-v1\manifests\sha256\c37ffbcebab5f758c9376c4553ec46931141c415e2b36ebe3b4b7bf063f38ec7\manifest.json")
DEFAULT_OUTPUT = Path("docs/nfl-personnel-injury-cold-start-v1")

TABLES = {
    "injuries": "snapshot_nfl_injury_report",
    "weekly_rosters": "snapshot_nfl_weekly_roster",
    "depth_charts": "snapshot_nfl_depth_chart",
    "snap_counts": "fact_nfl_snap_count",
    "players": "dim_nfl_player",
    "draft_picks": "dim_nfl_draft_pick",
    "games": "dim_nfl_game",
}


def ref(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "byteCount": len(raw)}


def write_json(path: Path, value: object) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    path.write_bytes(raw)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "byteCount": len(raw)}


def write_text(path: Path, value: str) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (value.rstrip() + "\n").encode("utf-8")
    path.write_bytes(raw)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "byteCount": len(raw)}


def svg_bars(path: Path, title: str, rows: list[tuple[str, float]], *, suffix: str = "") -> None:
    width, left, right, top, line = 900, 260, 110, 70, 32
    height = top + line * len(rows) + 55
    maximum = max((value for _, value in rows), default=1) or 1
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#fbfaf7"/>',
             f'<text x="24" y="34" font-family="Arial" font-size="20" font-weight="700" fill="#16243a">{title}</text>']
    for index, (label, value) in enumerate(rows):
        y = top + index * line
        bar = (width - left - right) * value / maximum
        parts += [f'<text x="24" y="{y + 17}" font-family="Arial" font-size="13" fill="#26384f">{label}</text>',
                  f'<rect x="{left}" y="{y}" width="{bar:.2f}" height="20" rx="3" fill="#2374ab"/>',
                  f'<text x="{left + bar + 8:.2f}" y="{y + 16}" font-family="Arial" font-size="12" fill="#26384f">{value:,.1f}{suffix}</text>']
    parts += [f'<text x="24" y="{height - 18}" font-family="Arial" font-size="11" fill="#637083">Generated from retained outcome-free metadata; finalized snapshots are not certified pregame vintages.</text>', '</svg>']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def svg_lines(path: Path, title: str, series: dict[str, list[tuple[int, float]]]) -> None:
    width, height, left, right, top, bottom = 900, 430, 70, 180, 60, 55
    years = sorted({year for rows in series.values() for year, _ in rows})
    maximum = max((value for rows in series.values() for _, value in rows), default=1) or 1
    colors = ["#2374ab", "#d1495b", "#2a9d8f", "#e09f3e"]
    x = lambda year: left + (width - left - right) * (year - min(years)) / max(1, max(years) - min(years))
    y = lambda value: top + (height - top - bottom) * (1 - value / maximum)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#fbfaf7"/>',
             f'<text x="24" y="32" font-family="Arial" font-size="20" font-weight="700" fill="#16243a">{title}</text>',
             f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#8a94a3"/>',
             f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#8a94a3"/>']
    for year in years:
        if year % 3 == 0 or year in {min(years), max(years)}:
            parts.append(f'<text x="{x(year)-12:.1f}" y="{height-bottom+22}" font-family="Arial" font-size="11" fill="#637083">{year}</text>')
    for index, (name, rows) in enumerate(series.items()):
        color = colors[index % len(colors)]
        points = " ".join(f"{x(year):.1f},{y(value):.1f}" for year, value in rows)
        parts += [f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.5"/>',
                  f'<rect x="{width-right+20}" y="{top+index*28}" width="14" height="14" fill="{color}"/>',
                  f'<text x="{width-right+42}" y="{top+12+index*28}" font-family="Arial" font-size="12" fill="#26384f">{name}</text>']
    parts += [f'<text x="24" y="{height-14}" font-family="Arial" font-size="11" fill="#637083">Rows by season; source definitions and completeness change over time.</text>', '</svg>']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def svg_unavailable(path: Path, title: str, explanation: str) -> None:
    value = f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="180" viewBox="0 0 900 180">
<rect width="100%" height="100%" fill="#fbfaf7"/><text x="24" y="36" font-family="Arial" font-size="20" font-weight="700" fill="#16243a">{title}</text>
<text x="24" y="88" font-family="Arial" font-size="30" font-weight="700" fill="#d1495b">UNAVAILABLE</text>
<text x="24" y="126" font-family="Arial" font-size="13" fill="#26384f">{explanation}</text>
</svg>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def table_paths(foundation: Path, manifest: dict[str, object]) -> dict[str, Path]:
    by_name = {str(row["tableName"]): row for row in manifest["objects"]}
    result = {}
    for short, table in TABLES.items():
        item = by_name[table]
        path = foundation / "objects" / "sha256" / str(item["manifestSha256"]) / "object.parquet"
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["fileSha256"]:
            raise RuntimeError(f"physical checksum mismatch: {table}")
        result[short] = path
    return result


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def query_rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, object]]:
    frame = con.execute(sql).fetchdf()
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundation-root", type=Path, default=DEFAULT_FOUNDATION)
    parser.add_argument("--foundation-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--bronze-manifest", type=Path, default=DEFAULT_BRONZE_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    out = args.output.resolve()
    manifest = json.loads(args.foundation_manifest.read_bytes())
    bronze = json.loads(args.bronze_manifest.read_bytes())
    paths = table_paths(args.foundation_root.resolve(), manifest)
    p = {key: sql_path(value) for key, value in paths.items()}
    con = duckdb.connect(database=":memory:")
    con.execute("SET threads=1")

    coverage = {}
    season_sql = {
        "injuries": "season BETWEEN 2009 AND 2024",
        "weekly_rosters": "season BETWEEN 2002 AND 2024",
        "depth_charts": "season BETWEEN 2001 AND 2024",
        "snap_counts": "season BETWEEN 2012 AND 2024",
    }
    for family, where in season_sql.items():
        coverage[family] = query_rows(con, f"SELECT season, count(*) AS \"rows\" FROM read_parquet('{p[family]}') WHERE {where} GROUP BY season ORDER BY season")

    identity_specs = {
        "injuries_gsis": ("injuries", "gsis_id", "canonical_player_id", "season BETWEEN 2009 AND 2024"),
        "weekly_rosters_gsis": ("weekly_rosters", "gsis_id", "canonical_player_id", "season BETWEEN 2002 AND 2024"),
        "depth_charts_gsis": ("depth_charts", "gsis_id", "canonical_player_id", "season BETWEEN 2001 AND 2024"),
        "snap_counts_pfr": ("snap_counts", "pfr_player_id", "pfr_id", "season BETWEEN 2012 AND 2024"),
        "draft_gsis": ("draft_picks", "gsis_id", "canonical_player_id", "season <= 2024"),
    }
    identity_rows = []
    for label, (family, source_id, player_id, where) in identity_specs.items():
        row = query_rows(con, f"""
            SELECT '{label}' AS "source",
                   count(*) AS records,
                   count(*) FILTER (WHERE s.{source_id} IS NOT NULL AND trim(cast(s.{source_id} AS VARCHAR)) <> '') identified,
                   count(*) FILTER (WHERE s.{source_id} IS NOT NULL AND trim(cast(s.{source_id} AS VARCHAR)) <> '' AND p.{player_id} IS NOT NULL) resolved,
                   count(*) FILTER (WHERE s.{source_id} IS NOT NULL AND trim(cast(s.{source_id} AS VARCHAR)) <> '' AND p.{player_id} IS NULL) unresolved
            FROM read_parquet('{p[family]}') s
            LEFT JOIN read_parquet('{p['players']}') p ON cast(s.{source_id} AS VARCHAR)=cast(p.{player_id} AS VARCHAR)
            WHERE {where}
        """)[0]
        row["exactMatchRateOfIdentified"] = row["resolved"] / row["identified"] if row["identified"] else None
        unique = query_rows(con, f"""
            SELECT count(DISTINCT cast(s.{source_id} AS VARCHAR)) FILTER (WHERE s.{source_id} IS NOT NULL AND trim(cast(s.{source_id} AS VARCHAR))<>'') unique_identified_players,
                   count(DISTINCT cast(s.{source_id} AS VARCHAR)) FILTER (WHERE s.{source_id} IS NOT NULL AND trim(cast(s.{source_id} AS VARCHAR))<>'' AND p.{player_id} IS NOT NULL) unique_resolved_players,
                   count(DISTINCT cast(s.{source_id} AS VARCHAR)) FILTER (WHERE s.{source_id} IS NOT NULL AND trim(cast(s.{source_id} AS VARCHAR))<>'' AND p.{player_id} IS NULL) unique_unresolved_players
            FROM read_parquet('{p[family]}') s LEFT JOIN read_parquet('{p['players']}') p
              ON cast(s.{source_id} AS VARCHAR)=cast(p.{player_id} AS VARCHAR) WHERE {where}
        """)[0]
        row.update(unique)
        row["exactMatchRateOfUniquePlayers"] = row["unique_resolved_players"] / row["unique_identified_players"] if row["unique_identified_players"] else None
        row["unresolvedPlayerIds"] = [item["player_id"] for item in query_rows(con, f"""
            SELECT DISTINCT cast(s.{source_id} AS VARCHAR) player_id
            FROM read_parquet('{p[family]}') s LEFT JOIN read_parquet('{p['players']}') p
              ON cast(s.{source_id} AS VARCHAR)=cast(p.{player_id} AS VARCHAR)
            WHERE {where} AND s.{source_id} IS NOT NULL AND trim(cast(s.{source_id} AS VARCHAR))<>'' AND p.{player_id} IS NULL
            ORDER BY player_id
        """)]
        identity_rows.append(row)

    anomalies = {
        "injuryDuplicateNaturalKeyRows": query_rows(con, f"SELECT count(*) n FROM (SELECT season,week,team,gsis_id,count(*) c FROM read_parquet('{p['injuries']}') WHERE season BETWEEN 2009 AND 2024 GROUP BY ALL HAVING c>1)")[0]["n"],
        "weeklyRosterPlayerWeekTeamConflicts": query_rows(con, f"SELECT count(*) n FROM (SELECT season,week,gsis_id,count(DISTINCT team) teams FROM read_parquet('{p['weekly_rosters']}') WHERE season BETWEEN 2002 AND 2024 AND gsis_id IS NOT NULL GROUP BY ALL HAVING teams>1)")[0]["n"],
        "normalizedNameCollisions": query_rows(con, f"SELECT count(*) n FROM (SELECT regexp_replace(lower(display_name),'[^a-z0-9]','','g') name_key,count(DISTINCT canonical_player_id) players FROM read_parquet('{p['players']}') WHERE display_name IS NOT NULL GROUP BY ALL HAVING players>1)")[0]["n"],
        "legacyTeamCodeRows": query_rows(con, f"SELECT count(*) n FROM read_parquet('{p['weekly_rosters']}') WHERE season BETWEEN 2002 AND 2024 AND team IN ('OAK','SD','STL')")[0]["n"],
        "canonicalFranchiseAliases": {"OAK": "LV", "SD": "LAC", "STL": "LAR", "LA": "LAR"},
        "duplicateCanonicalPlayerIds": query_rows(con, f"SELECT count(*) n FROM (SELECT canonical_player_id,count(*) c FROM read_parquet('{p['players']}') WHERE canonical_player_id IS NOT NULL GROUP BY 1 HAVING c>1)")[0]["n"],
        "pfrIdsMappedToMultipleCanonicalPlayers": query_rows(con, f"SELECT count(*) n FROM (SELECT pfr_id,count(DISTINCT canonical_player_id) c FROM read_parquet('{p['players']}') WHERE pfr_id IS NOT NULL GROUP BY 1 HAVING c>1)")[0]["n"],
        "espnIdsMappedToMultipleCanonicalPlayers": query_rows(con, f"SELECT count(*) n FROM (SELECT espn_id,count(DISTINCT canonical_player_id) c FROM read_parquet('{p['players']}') WHERE espn_id IS NOT NULL GROUP BY 1 HAVING c>1)")[0]["n"],
        "identityPolicy": "exact governed ID joins only; display-name collisions are measured but never used for resolution",
    }

    injury_status = query_rows(con, f"SELECT coalesce(nullif(trim(report_status),''),'NO_DESIGNATION') status,count(*) AS \"rows\" FROM read_parquet('{p['injuries']}') WHERE season BETWEEN 2009 AND 2024 GROUP BY 1 ORDER BY \"rows\" DESC")
    practice_status = query_rows(con, f"SELECT coalesce(nullif(trim(practice_status),''),'UNKNOWN') status,count(*) AS \"rows\" FROM read_parquet('{p['injuries']}') WHERE season BETWEEN 2009 AND 2024 GROUP BY 1 ORDER BY \"rows\" DESC")
    roster_status = query_rows(con, f"SELECT coalesce(nullif(trim(status),''),'UNKNOWN') status,count(*) AS \"rows\" FROM read_parquet('{p['weekly_rosters']}') WHERE season BETWEEN 2002 AND 2024 GROUP BY 1 ORDER BY \"rows\" DESC")
    position_burden = query_rows(con, f"""
      SELECT CASE WHEN position='QB' THEN 'QB' WHEN position IN ('OL','T','G','C') THEN 'OFFENSIVE_LINE'
                  WHEN position IN ('WR','TE','RB','FB') THEN 'SKILL' WHEN position IN ('DL','DE','DT','NT','LB','ILB','OLB','MLB') THEN 'DEFENSIVE_FRONT'
                  WHEN position IN ('DB','CB','S','SS','FS') THEN 'SECONDARY' WHEN position IN ('K','P','LS','KR','PR') THEN 'SPECIAL_TEAMS' ELSE 'OTHER' END position_group,
             count(*) listed_rows
      FROM read_parquet('{p['injuries']}') WHERE season BETWEEN 2009 AND 2024 GROUP BY 1 ORDER BY listed_rows DESC
    """)
    missingness = query_rows(con, f"""
      SELECT 'injury_missing_gsis' AS metric,count(*) AS "value" FROM read_parquet('{p['injuries']}') WHERE season BETWEEN 2009 AND 2024 AND (gsis_id IS NULL OR trim(gsis_id)='')
      UNION ALL SELECT 'injury_missing_date_modified',count(*) AS "value" FROM read_parquet('{p['injuries']}') WHERE season BETWEEN 2009 AND 2024 AND date_modified IS NULL
      UNION ALL SELECT 'injury_no_game_designation',count(*) AS "value" FROM read_parquet('{p['injuries']}') WHERE season BETWEEN 2009 AND 2024 AND (report_status IS NULL OR trim(report_status)='')
      UNION ALL SELECT 'roster_missing_gsis',count(*) AS "value" FROM read_parquet('{p['weekly_rosters']}') WHERE season BETWEEN 2002 AND 2024 AND (gsis_id IS NULL OR trim(gsis_id)='')
      UNION ALL SELECT 'roster_missing_experience',count(*) AS "value" FROM read_parquet('{p['weekly_rosters']}') WHERE season BETWEEN 2002 AND 2024 AND years_exp IS NULL
      UNION ALL SELECT 'depth_missing_gsis',count(*) AS "value" FROM read_parquet('{p['depth_charts']}') WHERE season BETWEEN 2001 AND 2024 AND (gsis_id IS NULL OR trim(gsis_id)='')
      UNION ALL SELECT 'depth_missing_observation_date',count(*) AS "value" FROM read_parquet('{p['depth_charts']}') WHERE season BETWEEN 2001 AND 2024 AND dt IS NULL
    """)
    qb_support = query_rows(con, f"""
      SELECT season,
             count(*) FILTER (WHERE years_exp=0 OR rookie_year=season) rookie_roster_rows,
             count(*) FILTER (WHERE years_exp BETWEEN 1 AND 2) low_experience_roster_rows,
             count(*) FILTER (WHERE years_exp>=3) experienced_roster_rows,
             count(*) FILTER (WHERE years_exp IS NULL) unknown_experience_roster_rows,
             count(*) total_qb_roster_rows
      FROM (SELECT DISTINCT season,week,team,gsis_id,years_exp,rookie_year FROM read_parquet('{p['weekly_rosters']}')
            WHERE season BETWEEN 2002 AND 2024 AND position='QB') GROUP BY season ORDER BY season
    """)

    injury_columns = ["season", "week", "team", "gsis_id", "date_modified"]
    game_columns = ["canonical_game_id", "season", "week", "game_date", "gametime", "canonical_home_team_id", "canonical_away_team_id"]
    injuries = pd.read_parquet(paths["injuries"], columns=injury_columns, filters=[("season", "<=", 2024)])
    games = pd.read_parquet(paths["games"], columns=game_columns, filters=[("season", "<=", 2024)])
    oriented = []
    for row in games.itertuples(index=False):
        if pd.isna(row.gametime):
            continue
        local = datetime.fromisoformat(f"{str(row.game_date)[:10]}T{str(row.gametime)[:5]}").replace(tzinfo=ZoneInfo("America/New_York"))
        kickoff = local.astimezone(timezone.utc)
        oriented.extend([(row.season, row.week, str(row.canonical_home_team_id), kickoff),
                         (row.season, row.week, str(row.canonical_away_team_id), kickoff)])
    kickoff = pd.DataFrame(oriented, columns=["season", "week", "team", "kickoff_utc"]).drop_duplicates(["season", "week", "team"], keep=False)
    injuries["team"] = injuries["team"].astype(str)
    injuries["date_modified"] = pd.to_datetime(injuries["date_modified"], utc=True, errors="coerce")
    timing = injuries.merge(kickoff, how="left", on=["season", "week", "team"])
    timing_summary = {
        "records": len(timing), "matchedUniqueTeamWeekKickoff": int(timing["kickoff_utc"].notna().sum()),
        "dateModifiedPresent": int(timing["date_modified"].notna().sum()),
        "dateModifiedBeforeKickoff": int((timing["date_modified"].notna() & timing["kickoff_utc"].notna() & (timing["date_modified"] < timing["kickoff_utc"])).sum()),
        "dateModifiedAtOrAfterKickoff": int((timing["date_modified"].notna() & timing["kickoff_utc"].notna() & (timing["date_modified"] >= timing["kickoff_utc"])).sum()),
        "qualification": "date_modified is a row update field, not a retained immutable release vintage; pre-kickoff values remain reconstructed research only",
    }

    source_families = {"injuries", "weekly_rosters", "depth_charts", "snap_counts", "players", "draft_picks", "participation", "weekly_player_stats", "schedules"}
    source_matrix = []
    for family in sorted(source_families):
        items = [row for row in bronze["partitions"] if row.get("familyId") == family]
        if not items:
            continue
        seasons = sorted({int(row["season"]) for row in items if row.get("season") is not None})
        source_matrix.append({"familyId": family, "seasons": seasons,
                              "minimumSeason": min(seasons) if seasons else None, "maximumSeason": max(seasons) if seasons else None,
                              "partitionCount": len(items), "rows": sum(int(row.get("rowCount") or 0) for row in items),
                              "bytes": sum(int(row.get("byteCount") or 0) for row in items),
                              "license": items[0].get("license"), "releaseTag": items[0].get("releaseTag"),
                              "releasePublishedAt": items[0].get("releasePublishedAt"),
                              "latestAssetUpdatedAt": max(str(row.get("assetUpdatedAt") or "") for row in items),
                              "latestRetrievalAt": max(str(row.get("retrievedAt") or "") for row in items),
                              "classification": {
                                  "injuries": "RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY",
                                  "weekly_rosters": "RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY",
                                  "depth_charts": "RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY",
                                  "snap_counts": "PROHIBITED_POSTGAME_EVIDENCE_FOR_TARGET; RECONSTRUCTED_RESEARCH_ONLY_WHEN_STRICTLY_PRIOR",
                                  "participation": "PROHIBITED_POSTGAME_EVIDENCE_FOR_TARGET; RECONSTRUCTED_RESEARCH_ONLY_WHEN_STRICTLY_PRIOR",
                                  "weekly_player_stats": "PROHIBITED_POSTGAME_EVIDENCE_FOR_TARGET; RECONSTRUCTED_RESEARCH_ONLY_WHEN_STRICTLY_PRIOR",
                                  "players": "IDENTITY_ONLY; CURRENT SNAPSHOT",
                                  "draft_picks": "STATIC PRE-CAREER FIELDS ONLY; CAREER OUTCOME FIELDS PROHIBITED",
                                  "schedules": "GAME IDENTITY; HISTORICAL REVISION VINTAGES NOT RETAINED",
                              }[family]})

    feature_registry = {
        "schemaVersion": "NFL_PERSONNEL_FEATURE_REGISTRY_V1", "overallHistoricalGate": "FAIL",
        "families": [
            {"family": "quarterback_continuity", "classification": "PROSPECTIVE_ONLY", "implemented": "contract and cold-start semantics",
             "blocker": "no certified target-game expected-QB publication vintage"},
            {"family": "quarterback_prior_performance", "classification": "RECONSTRUCTED_RESEARCH_ONLY", "implemented": "strictly prior history and league shrinkage",
             "blocker": "cannot attach to a certified historical expected target QB"},
            {"family": "rookie_sparse_qb", "classification": "PROSPECTIVE_ONLY", "implemented": "draft-aware cold-start state; missing draft is unknown",
             "blocker": "expected target QB and historical start state lack point-in-time authority"},
            {"family": "prior_role_roster_continuity", "classification": "RECONSTRUCTED_RESEARCH_ONLY", "implemented": "prior-game-only role helper",
             "blocker": "weekly roster/depth vintages have no retained revision archive; PFR snaps need crosswalk"},
            {"family": "injury_burden", "classification": "PROSPECTIVE_ONLY", "implemented": "status vocabulary and revision-aware record",
             "blocker": "finalized injury files lack immutable historical release vintages"},
            {"family": "target_game_actual_participation", "classification": "UNSUPPORTED", "implemented": "explicit rejection",
             "blocker": "postgame evidence is prohibited as a pregame input"},
            {"family": "transactions", "classification": "PROSPECTIVE_ONLY", "implemented": "none",
             "blocker": "roster status exists, but no retained historical effective/publication revision chain proves transaction timing"},
            {"family": "weather_venue", "classification": "OUT_OF_SCOPE_EXISTING", "implemented": "unchanged existing schedule fields",
             "blocker": "weather was explicitly outside this experiment"},
        ],
    }
    field_matrix = {"schemaVersion": "NFL_PERSONNEL_FIELD_ADMISSIBILITY_MATRIX_V1", "fields": [
        {"source": "injuries", "fields": ["gsis_id", "team", "season", "week", "position"], "classification": "RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY", "reason": "identity/grain exist but original physical release vintages are not retained"},
        {"source": "injuries", "fields": ["date_modified"], "classification": "RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY", "reason": "row update time is not immutable publication-byte proof"},
        {"source": "injuries", "fields": ["practice_status", "report_status", "injury fields"], "classification": "RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY; PROSPECTIVE_ONLY_FOR_MODEL_INPUT", "reason": "current final snapshots may contain corrections"},
        {"source": "weekly_rosters", "fields": ["gsis_id", "team", "week", "status", "depth_chart_position", "years_exp", "rookie_year"], "classification": "RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY; PROSPECTIVE_ONLY_FOR_MODEL_INPUT", "reason": "no per-row publication time or retained revision chain"},
        {"source": "depth_charts", "fields": ["gsis_id", "team", "week", "dt", "depth_position", "pos_rank"], "classification": "RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY; PROSPECTIVE_ONLY_FOR_MODEL_INPUT", "reason": "source/conventions changed and historical revisions are not retained"},
        {"source": "snap_counts", "fields": ["offense_snaps", "defense_snaps", "st_snaps", "percentages"], "classification": "PROHIBITED_POSTGAME_EVIDENCE_FOR_TARGET; RECONSTRUCTED_RESEARCH_ONLY_WHEN_STRICTLY_PRIOR", "reason": "realized participation is postgame"},
        {"source": "participation", "fields": ["play participants", "roles"], "classification": "PROHIBITED_POSTGAME_EVIDENCE_FOR_TARGET; RECONSTRUCTED_RESEARCH_ONLY_WHEN_STRICTLY_PRIOR", "reason": "realized play participation is postgame and CC BY-SA 4.0"},
        {"source": "weekly_player_stats", "fields": ["attempts", "EPA", "success", "CPOE", "sacks", "interceptions"], "classification": "PROHIBITED_POSTGAME_EVIDENCE_FOR_TARGET; RECONSTRUCTED_RESEARCH_ONLY_WHEN_STRICTLY_PRIOR", "reason": "target-game performance is postgame"},
        {"source": "players", "fields": ["canonical IDs and crosswalk IDs"], "classification": "IDENTITY_ONLY_CURRENT_SNAPSHOT", "reason": "usable for exact joins; not proof of historical team/status"},
        {"source": "draft_picks", "fields": ["draft season", "round", "pick", "team", "age", "college", "player IDs"], "classification": "HISTORICALLY_POINT_IN_TIME_ADMISSIBLE", "reason": "stable facts fixed before NFL career, subject to exact identity"},
        {"source": "draft_picks", "fields": ["games", "career AV", "starts", "career statistics", "awards"], "classification": "PROHIBITED_POSTGAME_EVIDENCE", "reason": "career outcomes would leak later evidence"},
        {"source": "schedules", "fields": ["game ID", "teams", "week", "date", "gametime"], "classification": "RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY; PROSPECTIVE_CAPTURE_SUPPORTED", "reason": "current schedule snapshot lacks old revision vintages"},
        {"source": "schedules", "fields": ["roof", "surface", "temperature", "wind"], "classification": "RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY", "scope": "OUT_OF_SCOPE", "reason": "weather/venue intentionally excluded from this experiment"},
        {"source": "pregame inactive publication", "fields": ["confirmed inactive"], "classification": "PROSPECTIVE_ONLY", "reason": "requires a separate source publication captured before cutoff"},
        {"source": "postgame result", "fields": ["actual starter", "actual participation"], "classification": "PROHIBITED_POSTGAME_EVIDENCE", "reason": "realized state cannot be substituted for expected pregame state"},
    ]}
    assessment = {
        "schemaVersion": "NFL_PERSONNEL_CHALLENGER_ASSESSMENT_V1", "status": "NOT_RUN",
        "overallDisposition": "INSUFFICIENT_ADMISSIBLE_EVIDENCE",
        "outcomesRead": {"2023": False, "2024": False, "2025": False, "2026": False},
        "reason": "No retained source proves the historical target-game expected quarterback, roster/depth state, and injury revision available before cutoff.",
        "plannedButNotExecuted": ["M1 baseline", "QB continuity/cold-start", "QB prior performance", "injury/personnel burden", "combined personnel block"],
        "advancementGate": "requires append-only pre-cutoff prospective captures with exact identity and sufficient supported game count",
        "metricsNotCalculated": ["score MAE", "margin MAE", "total MAE", "winner accuracy", "log loss", "binary Brier", "calibration"],
    }

    artifacts = {}
    artifacts["sourceAudit"] = write_json(out / "SOURCE_LICENSE_MATRIX.json", {"schemaVersion": "NFL_PERSONNEL_SOURCE_LICENSE_MATRIX_V1", "sources": source_matrix,
        "officialDocumentation": [
            {"url": "https://nflreadr.nflverse.com/articles/dictionary_injuries.html", "claim": "date_modified is when injury information was updated"},
            {"url": "https://github.com/nflverse/nflverse-rosters", "claim": "nflverse roster pipeline updates rosters, depth charts, practice reports, and injuries"},
            {"url": "https://github.com/nflverse/nflverse-data/releases", "claim": "data are distributed as GitHub release assets"},
            {"url": "https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md", "claim": "nflverse-data is CC BY 4.0; attribution and change notice required"},
            {"url": "https://github.com/nflverse/nflreadr/releases", "claim": "weekly-roster/depth/participation conventions changed over time"},
            {"url": "https://github.com/nflverse/nflverse-data/issues/102", "claim": "historical weekly-roster contemporaneity/revision question is open and unanswered"},
        ]})
    matrix_lines = ["# Provider, source and license matrix", "",
                    "All retained nflverse-data assets use CC BY 4.0 except participation, which uses CC BY-SA 4.0. The historical files are current finalized snapshots; a release-tag creation time is not a historical asset-vintage timestamp.", "",
                    "| Family | Seasons | Rows | Retained bytes | License | Classification |", "|---|---:|---:|---:|---|---|"]
    for item in source_matrix:
        season_text = f"{item['minimumSeason']}–{item['maximumSeason']}" if item["minimumSeason"] is not None else "static/current"
        license_id = (item.get("license") or {}).get("id", "UNKNOWN")
        matrix_lines.append(f"| {item['familyId']} | {season_text} | {item['rows']:,} | {item['bytes']:,} | {license_id} | {item['classification']} |")
    artifacts["sourceMatrixMarkdown"] = write_text(out / "SOURCE_AND_LICENSE_MATRIX.md", "\n".join(matrix_lines))
    artifacts["identity"] = write_json(out / "IDENTITY_RECONCILIATION.json", {"schemaVersion": "NFL_PERSONNEL_IDENTITY_RECONCILIATION_V1",
        "exactJoins": identity_rows, "anomalies": anomalies, "failClosed": True})
    artifacts["coverage"] = write_json(out / "HISTORICAL_COVERAGE.json", {"schemaVersion": "NFL_PERSONNEL_HISTORICAL_COVERAGE_V1",
        "coverageBySeason": coverage, "injuryTiming": timing_summary, "quarterbackRosterSupport": qb_support,
        "injuryGameStatus": injury_status, "practiceStatus": practice_status, "rosterStatus": roster_status, "positionGroupListedRows": position_burden,
        "missingnessCounts": missingness, "outcomeColumnsRead": [], "maximumSeasonRead": 2024})
    artifacts["vocabulary"] = write_json(out / "INJURY_STATUS_VOCABULARY.json", status_vocabulary())
    artifacts["features"] = write_json(out / "FEATURE_REGISTRY.json", feature_registry)
    artifacts["fieldAdmissibility"] = write_json(out / "FIELD_ADMISSIBILITY_MATRIX.json", field_matrix)
    artifacts["missingness"] = write_json(out / "MISSINGNESS_SPEC.json", {"schemaVersion": "NFL_PERSONNEL_MISSINGNESS_SPEC_V1",
        "states": ["PLAYER_ABSENT_FROM_REPORT", "PLAYER_REPORTED_HEALTHY", "SOURCE_NOT_PUBLISHED", "PLAYER_IDENTITY_UNRESOLVED", "STATUS_UNKNOWN", "NO_PRIOR_NFL_HISTORY", "NO_PRIOR_START", "STRUCTURAL_NOT_APPLICABLE"],
        "rule": "states are categorical and never collapsed to numeric zero", "observedCounts": missingness})
    artifacts["assessment"] = write_json(out / "ASSESSMENT.json", assessment)
    artifacts["capturePlan"] = write_json(out / "PROSPECTIVE_CAPTURE_PLAN.json", {**build_capture_plan(2026).content(), "status": "INACTIVE_DRY_RUN_ONLY"})
    network = {"schemaVersion": "NFL_PERSONNEL_NETWORK_ACTIVITY_V1", "authenticatedProviderCalls": 0,
               "downloadedArtifacts": 0, "costUsd": 0, "browserDocumentationRequests": [
                   {"url": item["url"], "responseBytes": None, "qualification": "browser tool does not expose physical response byte count"}
                   for item in json.loads((out / "SOURCE_LICENSE_MATRIX.json").read_text())["officialDocumentation"]],
               "capturePlannerRequests": 0, "capturePlannerResponseBytes": 0}
    artifacts["network"] = write_json(out / "NETWORK_ACTIVITY.json", network)

    svg_lines(out / "figures/source_coverage.svg", "Retained source coverage over time",
              {key: [(int(row["season"]), float(row["rows"])) for row in values] for key, values in coverage.items()})
    svg_bars(out / "figures/identity_resolution.svg", "Exact ID resolution among identified records",
             [(str(row["source"]), 100 * float(row["exactMatchRateOfUniquePlayers"] or 0)) for row in identity_rows], suffix="%")
    latest_qb = qb_support[-1]
    svg_bars(out / "figures/qb_experience_support.svg", "2024 QB roster-row experience support (not starts)",
             [(key.replace("_roster_rows", ""), float(latest_qb[key])) for key in ("rookie_roster_rows", "low_experience_roster_rows", "experienced_roster_rows", "unknown_experience_roster_rows")])
    svg_bars(out / "figures/injury_status_distribution.svg", "Historical finalized injury game-status rows",
             [(str(row["status"]), float(row["rows"])) for row in injury_status])
    svg_bars(out / "figures/position_group_burden.svg", "Listed injury rows by position group",
             [(str(row["position_group"]), float(row["listed_rows"])) for row in position_burden])
    svg_bars(out / "figures/missingness.svg", "Observed source-field missingness counts",
             [(str(row["metric"]), float(row["value"])) for row in missingness])
    svg_unavailable(out / "figures/qb_cold_start_frequency.svg", "Historically certified QB first-start frequency",
                    "No immutable expected-QB publication vintages exist; target-game starter outcomes were not opened.")

    write_text(out / "TIMING_AND_REVISION_AUDIT.md", f"""# Timing and revision audit

The retained Foundation is a **current finalized snapshot**, not an archive of every historical release. Injury `date_modified` is useful row metadata: {timing_summary['dateModifiedBeforeKickoff']:,} of {timing_summary['records']:,} retained rows match a unique team-week kickoff and carry an earlier modification time, while {timing_summary['dateModifiedAtOrAfterKickoff']:,} are at or after kickoff. This does not prove which physical bytes were available at a historical cutoff because later corrections can be present in the downloaded 2026 snapshot.

Weekly rosters have season/week and IDs but no retained row publication time. Depth charts have a date field, but the upstream source and conventions changed and no append-only historical revision chain is retained. Snap counts, participation, and player-game statistics are postgame. They are prohibited for the target game and may be used only after a conservative prior-game availability boundary.

The nflverse release tag creation time is not the publication time of each later-mutated season asset. `assetUpdatedAt` and the local 2026 retrieval time describe the artifact now; neither reconstructs the bytes that existed before an old kickoff. The open nflverse issue #102 asks this exact roster-vintage question and has no authoritative answer as of this audit.

Accordingly, no 2023–2024 outcome assessment was opened. The evidence gate failed before outcomes.
""")
    write_text(out / "QB_COLD_START_SPEC.md", """# Quarterback cold-start specification

The expected quarterback must come from a timestamped pregame record tied to the target team and game. Display-name matching is forbidden. `firstNflStart` means zero governed starts strictly before the feature cutoff; it is not inferred from the realized target-game starter. `rookie` requires a governed rookie-season field. A missing draft row is `DRAFT_STATUS_UNKNOWN`, never undrafted.

Prior performance uses completed earlier games only and records player-season attempts, starts, EPA/dropback, success, sack, interception and CPOE support where governed. The initial shrinkage order is current player-season, player prior seasons, experience cohort, then league prior. The implemented pure helper currently performs transparent player-history plus league-prior shrinkage; cohort estimation remains blocked until a prospective expected-QB population exists.

Existing M1 lagged passer mixtures remain team usage context. They do not identify the expected target starter and are not duplicated or relabelled here.
""")
    write_text(out / "PROSPECTIVE_CAPTURE_CONTRACT.md", """# Prospective capture contract

The inactive capture planner targets seven public nflverse release assets: schedule, injuries, weekly roster, depth chart, snap counts, players and draft picks. One manual capture permits at most seven GETs, 64 MiB of response bytes and 2 GiB retained. Raw bytes remain outside Git, content-addressed by SHA-256. Receipts retain release tag, asset name, URL, ETag/Last-Modified when supplied, retrieval time, physical hash, byte count and license. Identical objects are reused.

Scheduling is inactive. A later authorized owner can run:

```powershell
python scripts/capture_nfl_personnel_evidence_v1.py --season 2026
python scripts/capture_nfl_personnel_evidence_v1.py --season 2026 --execute --rights-approved
```

The first command is always zero-network. The second is the explicit live path and must use the external default root. Captures grant research evidence only and no model, forecast, AISP, exchange, policy or scheduler authority.
""")
    write_text(out / "FROZEN_STUDY_DESIGN.md", """# Frozen historical study gate

The proposed fixed comparison was M1, M1 plus QB continuity/cold-start, M1 plus QB prior performance, M1 plus injury/personnel burden and the combined admissible block. Development would be 2020–2022; 2023–2024 would be reused diagnostic evidence with calendar-week clustered uncertainty. The estimator, 197 M1 features, metrics and segment definitions would remain fixed.

The gate did not pass. Historical expected-quarterback, roster/depth and injury revisions cannot be proven from retained immutable pre-cutoff bytes. Therefore no outcomes, fits, comparisons, segment scores or advancement decisions were produced. Running the final fitted M1 artifact over these rows would not repair the missing input chronology.
""")
    write_text(out / "GENERATION2_RECOMMENDATION.md", """# Generation 2 recommendation

Disposition: **INSUFFICIENT_ADMISSIBLE_EVIDENCE**.

Start one inactive-to-active prospective evidence stream under the existing NFL owner only after separate activation approval. Capture schedule, injuries, weekly roster, depth chart and identity assets at declared pregame checkpoints. Accumulate exact expected-QB and revision evidence before evaluating the existing fixed M1 recipe. Keep prior-game snaps and player performance on a conservative completion-plus-publication lag. Do not estimate status-to-availability weights until a Development population exists.

The next dependency is an append-only run of the capture contract across enough 2026 game-weeks to measure supported-game coverage and freeze a chronological challenger. No production or consumer change is justified now.
""")
    write_text(out / "CLAUDE_HANDOFF.md", """# Claude / AISP handoff

No consumer action is authorized or required. No model or forecast package exists. AISP must not display expected quarterback, injury burden, fair price, edge or personnel explanation from this audit.

The source audit supports only these statements: finalized nflverse injury, roster, depth, snap, player and draft assets exist locally; exact ID coverage is measured; target-game snaps/participation are prohibited; and historical release vintages are insufficient for a point-in-time challenger. The prospective contract is inactive and research-only.

If future captures create an assessed model, any consumer handoff must bind the exact capture receipt, cutoff, expected-QB identity, missingness states, model artifact and authority. This document grants no AISP write, publication, decision or position authority.
""")
    write_text(out / "REPRODUCTION.md", """# Reproduction

From the branch worktree, using the existing project environment:

```powershell
C:/Users/james/asp-model-studio/.venv/Scripts/python.exe -m scripts.audit_nfl_personnel_injury_v1
C:/Users/james/asp-model-studio/.venv/Scripts/python.exe -m scripts.capture_nfl_personnel_evidence_v1 --season 2026
C:/Users/james/asp-model-studio/.venv/Scripts/python.exe -m pytest tests/test_nfl_personnel_evidence.py -q
```

The audit opens only identity, schedule-without-score, roster, depth, injury, draft and snap metadata through 2024. It does not open 2023–2026 outcomes. The capture command shown is plan-only and performs no network I/O.
""")
    report = f"""# NFL quarterback, personnel and injury evidence foundation

## Outcome

**INSUFFICIENT_ADMISSIBLE_EVIDENCE.** The requested historical challenger was not run. Retained nflverse snapshots support an identity-safe contract, descriptive coverage audit, strictly prior helpers and an inactive prospective capture path. They do not preserve the physical historical release vintages needed to prove the target-game expected quarterback, roster/depth state and injury revision before kickoff.

## Evidence inspected

- Injury reports: {sum(row['rows'] for row in coverage['injuries']):,} rows, 2009–2024 in the admitted audit.
- Weekly rosters: {sum(row['rows'] for row in coverage['weekly_rosters']):,} rows, 2002–2024.
- Depth charts: {sum(row['rows'] for row in coverage['depth_charts']):,} rows, 2001–2024.
- Snap counts: {sum(row['rows'] for row in coverage['snap_counts']):,} rows, 2012–2024; target-game values prohibited.
- Player and draft identity tables were inspected only for crosswalk/static fields. Career outcome fields in the draft table were excluded.
- Game schedule columns supplied identity, orientation, week, date and time only. Score/outcome columns were not loaded.

## Main findings

1. `date_modified` gives useful injury-row timing but no immutable release-vintage proof. Current assets can contain later corrections.
2. Weekly rosters and depth charts lack a retained append-only publication/revision chain for old cutoffs. An official upstream issue asking about contemporaneous roster vintages remains unanswered.
3. Prior-game snaps and player performance can be used only after completion and a conservative publication boundary. They cannot identify the target-game starter.
4. Existing M1 already models lagged team passer usage. This work adds the missing evidence semantics; it does not relabel that mixture as current-quarterback identity.
5. Identity resolution is exact-ID only. Name collisions, trades and legacy team aliases are measured and fail closed where ambiguous.
6. Existing schedule data contains venue and weather fields, but weather remains outside this experiment and unchanged.

## Implemented

- Immutable pregame personnel record with source/effective/retrieval/cutoff clocks, revision predecessor and physical row digest.
- Append-only correction validation, exact-ID resolution, explicit injury/availability vocabulary and eight distinct missingness states.
- Strictly prior quarterback-performance shrinkage helper, cold-start semantics and target-game snap rejection.
- Seven-request, 64 MiB inactive 2026 capture plan with 2 GiB retained ceiling and content-addressed raw bytes outside Git.
- Deterministic outcome-free audit and six SVG evidence figures.

## Historical experiment

No assessment results exist. The gate failed before 2023–2024 outcomes were read. This is not `NO_INCREMENTAL_VALUE`; predictive value remains unknown.

## External activity

Official public documentation was read through the browser. The browser tool does not expose physical response byte counts, so those bytes are recorded as unavailable rather than invented. No authenticated provider request, artifact download, sportsbook call or paid request occurred; cost was $0. The capture planner executed in dry-run mode only.

## Next dependency

Activate the prospective capture under a separately authorized existing NFL owner, preserving pre-cutoff revisions for expected quarterback, injuries, roster and depth. After enough supported 2026 game-weeks accrue, freeze the fixed M1 block comparison before outcomes.
"""
    artifacts["report"] = write_text(out / "REPORT.md", report)

    index = {"schemaVersion": "NFL_PERSONNEL_INJURY_COLD_START_INDEX_V1",
             "evidenceAsOfUtc": manifest["publishedAt"],
             "foundationManifest": ref(args.foundation_manifest), "bronzeManifest": ref(args.bronze_manifest),
             "implementation": [ref(Path(__file__).resolve()),
                                ref(Path("scripts/capture_nfl_personnel_evidence_v1.py").resolve()),
                                ref(Path("server/sports_nfl_m1/personnel_evidence.py").resolve()),
                                ref(Path("server/sports_nfl_m1/personnel_capture.py").resolve()),
                                ref(Path("tests/test_nfl_personnel_evidence.py").resolve())],
             "maximumSeasonRead": 2024, "outcomeColumnsRead": [], "assessmentStatus": "NOT_RUN",
             "overallDisposition": "INSUFFICIENT_ADMISSIBLE_EVIDENCE",
             "artifacts": artifacts}
    index_id = hashlib.sha256(canonical_json_bytes(index)).hexdigest()
    write_json(out / "ARTIFACT_INDEX.json", {**index, "contentIdentitySha256": index_id})
    print(json.dumps({"status": "COMPLETE", "output": str(out), "contentIdentitySha256": index_id,
                      "maximumSeasonRead": 2024, "outcomesRead": False,
                      "overallDisposition": "INSUFFICIENT_ADMISSIBLE_EVIDENCE"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
