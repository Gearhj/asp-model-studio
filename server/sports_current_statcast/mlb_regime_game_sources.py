"""Bounded Development-only game identities and optional score diagnostics.

No combined 2026 schedule, mixed-OOT contextual row group or AISP surface is opened.
Team identities are canonical Silver abbreviations, not guesses from game IDs.
Post-score evidence is evaluation-only and never contributes to predictor inputs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import pyarrow.parquet as pq

from server.sports_gold.silver_inputs import read_verified_columns, resolve_current_silver
from .mlb_regime_simulation import RegimeSimulationError


SILVER_SHA = "fcfb95724f2cc44ae45555897365497c538f5ea6303fe041dd4afa9697c62d2a"
LEGACY_DIM_SHA = "1afa766640c202742f270184b81a26056080c79a2a726279e1cb961b7e78e456"
TEAM_DIM_SHA = "2a758bdc3f9949bd5c89cc9eb3e2552741e84ce93558cc0f746d4a6db2a928cf"
SAFE_END = "2026-08-06"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_development_game_context(
    observations: pd.DataFrame,
    *,
    staging_root: Path = Path("C:/Users/james/asp-data-staging"),
    score_game_ids: Sequence[str] = (),
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return canonical game/team IDs, original team codes and optional scores.

    Caller supplies exactly its eligible Development game/date inventory. Only
    safe dated Silver partitions are read. Optional raw last-pitch post scores
    are bounded to twenty explicitly named games; these are labeled retrospective
    diagnostics, not prospective features or independently verified official scores.
    """
    required = {"canonicalGameId", "game_date"}
    if observations.empty or not required.issubset(observations.columns):
        raise RegimeSimulationError("game/date inventory is required")
    wanted = observations[["canonicalGameId", "game_date"]].drop_duplicates().copy()
    if wanted.isna().any().any() or wanted["canonicalGameId"].duplicated().any():
        raise RegimeSimulationError("game/date inventory has missing or conflicting identities")
    wanted = wanted.astype(str)
    if not wanted["game_date"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise RegimeSimulationError("exact game dates are required")
    if not wanted["game_date"].between("2023-03-30", SAFE_END).all():
        raise RegimeSimulationError("game source request is outside physically safe Development")
    score_ids = set(str(value) for value in score_game_ids)
    if len(score_ids) > 20 or not score_ids.issubset(set(wanted["canonicalGameId"])):
        raise RegimeSimulationError("score diagnostics require at most twenty explicitly requested games")
    root = Path(staging_root)
    records: list[pd.DataFrame] = []
    evidence: list[dict[str, Any]] = []
    dates = set(wanted["game_date"])
    legacy_years = tuple(sorted({int(day[:4]) for day in dates if day < "2025-01-01"}))
    if legacy_years:
        handle = resolve_current_silver(root / "mlb-silver-v1", "dim_game")
        if handle.manifest_sha256 != LEGACY_DIM_SHA:
            raise RegimeSimulationError("legacy game dimension authority differs")
        legacy = read_verified_columns(
            handle, ["canonicalGameId", "gameDate", "homeTeam", "awayTeam", "season"],
            seasons=legacy_years,
        ).to_pandas()
        records.append(legacy.drop(columns=["season"]))
        evidence.append({"kind": "LEGACY_SILVER_DIM_GAME", **handle.identity()})
    current_dates = sorted(day for day in dates if day >= "2025-01-01")
    scores: list[dict[str, Any]] = []
    if current_dates:
        silver_root = root / "mlb-current-statcast-silver-v1"
        manifest_path = silver_root / "publications/sha256" / SILVER_SHA / "manifest.json"
        if _hash_file(manifest_path) != SILVER_SHA:
            raise RegimeSimulationError("current Silver manifest bytes differ")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        by_date = {item["partitionDate"]: item for item in manifest["partitions"]}
        bronze_root = root / "mlb-current-statcast-bronze-v1"
        bronze = None
        if score_ids:
            bronze = json.loads((bronze_root / "manifests/bronze-manifest.json").read_text(encoding="utf-8"))
        raw_by_id = {item["partitionId"]: item for item in bronze["partitions"]} if bronze else {}
        for day in current_dates:
            receipt = by_date.get(day)
            if not receipt or receipt.get("sourceStatus") != "COMPLETE":
                raise RegimeSimulationError(f"complete daily Silver source unavailable: {day}")
            item = receipt["objects"]["plate_appearance"]
            path = (silver_root / item["relativePath"]).resolve()
            if not path.is_relative_to(silver_root.resolve()):
                raise RegimeSimulationError("daily Silver object escaped source root")
            parquet = pq.ParquetFile(path)
            date_index = parquet.schema_arrow.names.index("gameDate")
            for index in range(parquet.num_row_groups):
                statistics = parquet.metadata.row_group(index).column(date_index).statistics
                if statistics is None or not statistics.has_min_max or statistics.min != day or statistics.max != day:
                    raise RegimeSimulationError("daily Silver date range is not physically isolated")
            # Hash only after proving every row group belongs to the safe requested day.
            if path.stat().st_size != item["byteCount"] or _hash_file(path) != item["sha256"]:
                raise RegimeSimulationError("daily Silver object bytes differ")
            identity = parquet.read(columns=["canonicalGameId", "mlbamGamePk", "gameDate", "homeTeam", "awayTeam"]).to_pandas().drop_duplicates()
            if identity["canonicalGameId"].duplicated().any() or not identity["gameDate"].eq(day).all():
                raise RegimeSimulationError("daily Silver game identity is ambiguous")
            records.append(identity.drop(columns=["mlbamGamePk"]))
            evidence.append({"kind": "DAILY_CURRENT_SILVER_IDENTITIES", "date": day, "path": str(path),
                             "sha256": item["sha256"], "rows": int(parquet.metadata.num_rows),
                             "columnsRead": ["canonicalGameId", "mlbamGamePk", "gameDate", "homeTeam", "awayTeam"]})
            score_identity = identity[identity["canonicalGameId"].isin(score_ids)]
            if score_identity.empty:
                continue
            raw_record = raw_by_id.get(receipt["request"]["sourcePartitionId"])
            if not raw_record or raw_record["minDate"] != day or raw_record["maxDate"] != day:
                raise RegimeSimulationError("score source is not isolated to the requested safe day")
            raw_path = (bronze_root / raw_record["relativePath"]).resolve()
            if not raw_path.is_relative_to(bronze_root.resolve()) or _hash_file(raw_path) != receipt["request"]["sourcePartitionSha256"]:
                raise RegimeSimulationError("raw score source identity differs")
            columns = ["game_pk", "game_date", "at_bat_number", "pitch_number", "post_away_score", "post_home_score"]
            raw = pd.read_csv(raw_path, usecols=columns)
            if not raw["game_date"].astype(str).eq(day).all():
                raise RegimeSimulationError("raw score source date differs")
            raw["game_pk"] = pd.to_numeric(raw["game_pk"], errors="raise").astype("int64")
            for name in ("at_bat_number", "pitch_number"):
                raw[name] = pd.to_numeric(raw[name], errors="raise")
            if raw.duplicated(["game_pk", "at_bat_number", "pitch_number"]).any():
                raise RegimeSimulationError("raw terminal pitch ordering is ambiguous")
            final = raw.sort_values(["game_pk", "at_bat_number", "pitch_number"]).groupby("game_pk").tail(1).set_index("game_pk")
            final_pks = set(receipt["request"]["finalGamePks"])
            for game_id, game_pk in score_identity[["canonicalGameId", "mlbamGamePk"]].itertuples(index=False, name=None):
                if int(game_pk) not in final_pks or int(game_pk) not in final.index:
                    continue
                last = final.loc[int(game_pk)]
                scores.append({"canonicalGameId": str(game_id), "actualAway": last["post_away_score"],
                               "actualHome": last["post_home_score"],
                               "scoreAuthority": "FINAL_GAME_LAST_ORDERED_RAW_PITCH_POST_SCORE_DIAGNOSTIC"})
            evidence.append({"kind": "EVALUATION_ONLY_RAW_LAST_PITCH_SCORES", "date": day,
                             "path": str(raw_path), "sha256": raw_record["fileSha256"], "columnsRead": columns,
                             "finalGameAuthoritySha256": receipt["counts"]["finalGameAuthoritySha256"]})
    all_games = pd.concat(records, ignore_index=True).rename(columns={
        "gameDate": "game_date", "homeTeam": "homeTeamId", "awayTeam": "awayTeamId"
    })
    all_games = all_games.drop_duplicates()
    if all_games["canonicalGameId"].duplicated().any():
        raise RegimeSimulationError("cross-source game identity is ambiguous")
    result = wanted.merge(all_games, on=["canonicalGameId", "game_date"], how="left", validate="one_to_one")
    if result[["homeTeamId", "awayTeamId"]].isna().any().any() or result["homeTeamId"].eq(result["awayTeamId"]).any():
        raise RegimeSimulationError("requested game has no exact pair of distinct Silver teams")
    team_handle = resolve_current_silver(root / "mlb-silver-v1", "dim_team")
    if team_handle.manifest_sha256 != TEAM_DIM_SHA:
        raise RegimeSimulationError("registered cross-era team identity authority differs")
    team_map = read_verified_columns(
        team_handle, ["canonicalTeamId", "teamAbbrev", "retroTeamCode"]
    ).to_pandas()
    if len(team_map) != 30 or any(team_map[name].isna().any() or team_map[name].duplicated().any()
                                 for name in ("canonicalTeamId", "teamAbbrev", "retroTeamCode")):
        raise RegimeSimulationError("registered team map is not a complete one-to-one authority")
    team_lookup = team_map.set_index("teamAbbrev")
    for side in ("home", "away"):
        source = result[f"{side}TeamId"].astype(str)
        if not source.isin(team_lookup.index).all():
            raise RegimeSimulationError("Silver team code is outside its declared canonical abbreviation namespace")
        result[f"{side}TeamSourceCode"] = source
        result[f"{side}TeamAbbrev"] = source
        result[f"{side}TeamRetrosheetCode"] = source.map(team_lookup["retroTeamCode"])
        result[f"{side}TeamId"] = source.map(team_lookup["canonicalTeamId"])
    evidence.append({"kind": "REGISTERED_CROSS_ERA_TEAM_MAP", **team_handle.identity(),
                     "mapping": team_map.to_dict(orient="records"),
                     "sourceCodesAlreadyInCanonicalSilverAbbreviationNamespace": True})
    if scores:
        result = result.merge(pd.DataFrame(scores), on="canonicalGameId", how="left", validate="one_to_one")
    else:
        result["actualAway"] = None
        result["actualHome"] = None
        result["scoreAuthority"] = None
    return result, {
        "schemaVersion": "MLB_REGIME_DEVELOPMENT_GAME_SOURCE_EVIDENCE_V1", "games": len(result),
        "teamIdentityKind": "REGISTERED_CANONICAL_TEAM_ID_WITH_PRESERVED_SOURCE_AND_RETROSHEET_CODES",
        "scoreDiagnosticGames": len(scores), "sources": evidence,
        "pregameParticipantAuthority": "UNAVAILABLE_NO_ORIGINAL_ANNOUNCEMENT_VINTAGE",
        "finalOotPayloadRowsRead": 0, "mixedOotRowGroupsReadOrHashed": 0,
        "maximumPermittedDate": SAFE_END,
        "rights": ["LOCAL_PRIVATE_MODEL_DEVELOPMENT", "GOVERNED_LOCAL_RESEARCH_ONLY", "ATTRIBUTION_REQUIRED", "COMMERCIAL_RIGHTS_REVIEW_REQUIRED"],
    }
