"""Read-only source assembly for the MLB contextual Gold extension.

The source layer opens only already-landed, content-verified evidence.  It does
not acquire, repair, normalize, or overwrite Bronze/Silver/Gold.  Postgame
fields (innings and duration) are carried solely so a *later-date* team row can
describe its previous completed game; they are never joined to the same game's
plate appearances as predictors.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from ..sports_gold.silver_inputs import read_verified_columns, resolve_current_silver
from ..sports_silver import bronze_authority as bronze
from .pipeline import _load_json, _read_schedule_authority, verify_current_silver


LEGACY_BRONZE_ROOT = Path(r"C:\Users\james\asp-data-staging\mlb-advanced-bronze-v1")
CURRENT_BRONZE_ROOT = Path(r"C:\Users\james\asp-data-staging\mlb-current-statcast-bronze-v1")
LEGACY_SILVER_ROOT = Path(r"C:\Users\james\asp-data-staging\mlb-silver-v1")
CURRENT_SILVER_ROOT = Path(r"C:\Users\james\asp-data-staging\mlb-current-statcast-silver-v1")


class ContextSourceError(RuntimeError):
    """An immutable source did not reconcile to one deterministic game fact."""


@dataclass(frozen=True)
class ContextSourceGame:
    canonical_game_id: str
    season: int
    game_date: date
    home_team_id: str
    away_team_id: str
    venue_key: str
    scheduled_start_utc: datetime | None
    start_time_local: str | None
    series_game_number: int | None
    games_in_series: int | None
    doubleheader_game_number: int | None
    is_home_opener: bool
    duration_minutes: int | None
    innings_played: int | None
    source_game_id: str
    source_partition_id: str
    source_sha256: str
    source_cutoff: str | None


@dataclass(frozen=True)
class ContextSourceBundle:
    games: tuple[ContextSourceGame, ...]
    authorities: Mapping[str, Any]


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _strict_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = int(text)
    except (TypeError, ValueError):
        return None
    return number


def _parse_iso_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _schedule_fact_signature(game: Mapping[str, Any]) -> tuple[Any, ...]:
    """Pregame schedule identity only; deliberately excludes result fields."""

    teams = game.get("teams") or {}
    return (
        game.get("gamePk"),
        game.get("gameDate"),
        game.get("officialDate"),
        game.get("gameNumber"),
        game.get("doubleHeader"),
        game.get("seriesGameNumber"),
        game.get("gamesInSeries"),
        game.get("description"),
        game.get("dayNight"),
        (game.get("venue") or {}).get("id"),
        ((teams.get("home") or {}).get("team") or {}).get("id"),
        ((teams.get("away") or {}).get("team") or {}).get("id"),
    )


def _same_suspended_game(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Return true only for an explicitly linked original/resumption pair."""

    left_start = str(left.get("gameDate") or "")
    right_start = str(right.get("gameDate") or "")
    if not left_start or not right_start or left_start == right_start:
        return False
    earlier, later = (left, right) if left_start < right_start else (right, left)
    earlier_start = str(earlier.get("gameDate") or "")
    later_start = str(later.get("gameDate") or "")
    linked = (
        str(earlier.get("resumeDate") or "") == later_start
        and str(later.get("resumedFrom") or "") == earlier_start
    )
    teams_left = left.get("teams") or {}
    teams_right = right.get("teams") or {}
    stable_identity = (
        left.get("gamePk") == right.get("gamePk")
        and left.get("gameGuid") == right.get("gameGuid")
        and left.get("officialDate") == right.get("officialDate")
        and (left.get("venue") or {}).get("id") == (right.get("venue") or {}).get("id")
        and ((teams_left.get("home") or {}).get("team") or {}).get("id")
        == ((teams_right.get("home") or {}).get("team") or {}).get("id")
        and ((teams_left.get("away") or {}).get("team") or {}).get("id")
        == ((teams_right.get("away") or {}).get("team") or {}).get("id")
    )
    return bool(linked and stable_identity)


def _event_headers(
    manifest: Mapping[str, Any], root: Path, seasons: tuple[int, ...]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    headers: dict[str, dict[str, Any]] = {}
    lineage: list[dict[str, Any]] = []
    partitions = {p.year: p for p in bronze.partitions(manifest, source="retrosheet") if "events" in p.relative_path}
    for season in seasons:
        partition = partitions.get(season)
        if partition is None:
            raise ContextSourceError(f"Retrosheet event archive missing for {season}")
        path = partition.absolute_path(root)
        if not path.is_file() or _sha_file(path) != partition.file_sha256:
            raise ContextSourceError(f"Retrosheet event archive SHA differs for {season}")
        lineage.append({
            "partitionId": partition.partition_id,
            "relativePath": partition.relative_path,
            "sha256": partition.file_sha256,
        })
        with zipfile.ZipFile(path) as archive:
            for member in sorted(name for name in archive.namelist() if name.upper().endswith((".EVA", ".EVN"))):
                current_id: str | None = None
                info: dict[str, str] = {}

                def flush() -> None:
                    if not current_id:
                        return
                    record = {
                        "retroGameId": current_id,
                        "site": info.get("site"),
                        "startTimeLocal": info.get("starttime"),
                        "dayNight": info.get("daynight"),
                        "gameDate": str(info.get("date") or "").replace("/", ""),
                        "sourcePartitionId": partition.partition_id,
                        "sourceMember": member,
                        "sourceSha256": partition.file_sha256,
                    }
                    prior = headers.get(current_id)
                    if prior is not None and prior != record:
                        raise ContextSourceError(f"conflicting Retrosheet event headers: {current_id}")
                    headers[current_id] = record

                for raw_line in archive.read(member).decode("latin-1").splitlines():
                    fields = [item.strip().strip('"') for item in raw_line.split(",")]
                    if not fields:
                        continue
                    if fields[0] == "id":
                        flush()
                        current_id = fields[1] if len(fields) > 1 else None
                        info = {}
                    elif fields[0] == "info" and len(fields) >= 3:
                        info[fields[1]] = fields[2]
                flush()
    return headers, lineage


def _game_log_workload(
    manifest: Mapping[str, Any], root: Path, seasons: tuple[int, ...]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    workload: dict[str, dict[str, Any]] = {}
    lineage: list[dict[str, Any]] = []
    partitions = {p.year: p for p in bronze.partitions(manifest, source="retrosheet") if "game-logs" in p.relative_path}
    for season in seasons:
        partition = partitions.get(season)
        if partition is None:
            raise ContextSourceError(f"Retrosheet game-log archive missing for {season}")
        path = partition.absolute_path(root)
        if not path.is_file() or _sha_file(path) != partition.file_sha256:
            raise ContextSourceError(f"Retrosheet game-log archive SHA differs for {season}")
        lineage.append({
            "partitionId": partition.partition_id,
            "relativePath": partition.relative_path,
            "sha256": partition.file_sha256,
        })
        member = f"gl{season}.txt"
        with zipfile.ZipFile(path) as archive:
            rows = csv.reader(io.StringIO(archive.read(member).decode("latin-1")))
            for index, raw in enumerate(rows):
                fields = [item.strip() for item in raw]
                if len(fields) != 161:
                    raise ContextSourceError(f"{member}:{index} does not contain 161 governed fields")
                retro_id = f"{fields[6]}{fields[0]}{fields[1]}"
                length_outs = _strict_int(fields[11])
                duration = _strict_int(fields[18])
                workload[retro_id] = {
                    "durationMinutes": duration,
                    "inningsPlayed": ((length_outs + 5) // 6 if length_outs is not None else None),
                    "parkId": fields[16] or None,
                    "dayNight": fields[12] or None,
                    "sourcePartitionId": partition.partition_id,
                    "sourceMember": member,
                    "sourceLine": index,
                    "sourceSha256": partition.file_sha256,
                }
    return workload, lineage


def _legacy_games(
    *, bronze_root: Path, silver_root: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = bronze.verify_bronze_manifest(Path(bronze_root))
    headers, event_lineage = _event_headers(manifest, Path(bronze_root), (2023, 2024))
    workload, log_lineage = _game_log_workload(manifest, Path(bronze_root), (2023, 2024))
    dim_handle = resolve_current_silver(Path(silver_root), "dim_game")
    team_handle = resolve_current_silver(Path(silver_root), "fact_team_game")
    pa_handle = resolve_current_silver(Path(silver_root), "fact_statcast_plate_appearance")
    dim = read_verified_columns(
        dim_handle,
        ["canonicalGameId", "mlbamGamePk", "gameDate", "season", "homeTeam", "awayTeam", "gameType", "retrosheetGameId", "gameNumber"],
        seasons=(2023, 2024),
    ).to_pandas()
    teams = read_verified_columns(
        team_handle,
        ["canonicalGameId", "retroGameId", "homeAway", "parkId", "season"],
        seasons=(2023, 2024),
    ).to_pandas()
    home_parks = {
        str(row.canonicalGameId): str(row.parkId)
        for row in teams.itertuples(index=False)
        if str(row.homeAway) == "home"
    }
    pa = read_verified_columns(
        pa_handle, ["canonicalGameId", "season", "inning"], seasons=(2023, 2024)
    ).to_pandas()
    pa["inning"] = pd.to_numeric(pa["inning"], errors="raise")
    max_innings = {
        str(key): int(value)
        for key, value in pa.groupby("canonicalGameId", sort=False)["inning"].max().items()
    }
    rows: list[dict[str, Any]] = []
    for row in dim.itertuples(index=False):
        if str(row.gameType) != "R":
            continue
        retro_id = str(row.retrosheetGameId or "")
        if not retro_id:
            continue
        header = headers.get(retro_id) or {}
        prior = workload.get(retro_id) or {}
        park_id = str(home_parks.get(str(row.canonicalGameId)) or prior.get("parkId") or header.get("site") or "")
        if not park_id:
            raise ContextSourceError(f"legacy game has no exact park identity: {row.canonicalGameId}")
        workload_innings = prior.get("inningsPlayed")
        observed_innings = max_innings.get(str(row.canonicalGameId))
        rows.append({
            "canonicalGameId": str(row.canonicalGameId),
            "sourceGameId": retro_id,
            "season": int(row.season),
            "gameDate": date.fromisoformat(str(row.gameDate)),
            "homeTeam": str(row.homeTeam),
            "awayTeam": str(row.awayTeam),
            "venueSource": "RETROSHEET",
            "venueSourceId": park_id,
            "startTimeLocal": header.get("startTimeLocal"),
            "scheduledStartUtc": None,
            "seriesGameNumber": None,
            "gamesInSeries": None,
            "doubleheaderGameNumber": (_strict_int(row.gameNumber) or None),
            "isHomeOpener": False,
            "durationMinutes": prior.get("durationMinutes"),
            "inningsPlayed": observed_innings if observed_innings is not None else workload_innings,
            "sourcePartitionId": str(header.get("sourcePartitionId") or prior.get("sourcePartitionId") or ""),
            "sourceSha256": str(header.get("sourceSha256") or prior.get("sourceSha256") or ""),
            "sourceCutoff": None,
        })
    return rows, {
        "bronzeManifestSha256": bronze.EXPECTED_BRONZE_MANIFEST_SHA256,
        "dimGame": dim_handle.identity(),
        "factTeamGame": team_handle.identity(),
        "factPlateAppearance": pa_handle.identity(),
        "eventArchives": event_lineage,
        "gameLogArchives": log_lineage,
    }


def _current_games(
    *, bronze_root: Path, silver_root: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    schedule, schedule_sha = _read_schedule_authority(Path(bronze_root))
    verified = verify_current_silver(Path(silver_root))
    manifest = _load_json(Path(str(verified["manifestPath"])))
    paths: list[Path] = []
    partition_by_date: dict[str, Mapping[str, Any]] = {}
    for receipt in manifest.get("partitions") or []:
        partition_by_date[str(receipt.get("partitionDate") or "")] = receipt
        item = (receipt.get("objects") or {}).get("plate_appearance") or {}
        if int(item.get("rowCount") or 0):
            path = Path(silver_root) / str(item.get("relativePath") or "")
            if not path.is_file() or _sha_file(path) != item.get("sha256"):
                raise ContextSourceError("current Silver PA partition SHA differs")
            paths.append(path)
    if not paths:
        raise ContextSourceError("current Silver has no PA partitions")
    table = ds.dataset([str(path) for path in paths], format="parquet").to_table(columns=[
        "canonicalGameId", "mlbamGamePk", "season", "gameDate", "homeTeam", "awayTeam", "inning",
    ])
    frame = table.to_pandas()
    frame["inning"] = pd.to_numeric(frame["inning"], errors="raise")
    grouped = frame.groupby("canonicalGameId", sort=False)
    games_from_pa: dict[str, dict[str, Any]] = {}
    by_pk: dict[str, str] = {}
    for canonical_id, game in grouped:
        first = game.iloc[0]
        if any(game[column].astype(str).nunique(dropna=False) != 1 for column in ("mlbamGamePk", "season", "gameDate", "homeTeam", "awayTeam")):
            raise ContextSourceError(f"current game context differs inside PA facts: {canonical_id}")
        row = {
            "canonicalGameId": str(canonical_id),
            "mlbamGamePk": str(first["mlbamGamePk"]),
            "season": int(first["season"]),
            "gameDate": date.fromisoformat(str(first["gameDate"])),
            "homeTeam": str(first["homeTeam"]),
            "awayTeam": str(first["awayTeam"]),
            "inningsPlayed": int(game["inning"].max()),
        }
        games_from_pa[str(canonical_id)] = row
        by_pk[row["mlbamGamePk"]] = str(canonical_id)

    completed = {str(item["gamePk"]): item for item in schedule.get("completedGames") or []}
    raw_by_pk: dict[str, tuple[dict[str, Any], Mapping[str, Any]]] = {}
    raw_lineage: list[dict[str, Any]] = []
    for snapshot in schedule.get("snapshots") or []:
        raw_path = Path(bronze_root) / str(snapshot.get("rawRelativePath") or "")
        expected = str(snapshot.get("rawSha256") or "")
        if not raw_path.is_file() or _sha_file(raw_path) != expected:
            raise ContextSourceError("raw MLB schedule snapshot SHA differs")
        raw_lineage.append({
            "snapshotId": snapshot.get("snapshotId"),
            "relativePath": snapshot.get("rawRelativePath"),
            "sha256": expected,
        })
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        for day in raw.get("dates") or []:
            for game in day.get("games") or []:
                game_pk = str(game.get("gamePk") or "")
                if game_pk not in completed:
                    continue
                # A postponed listing and its eventual completed makeup can
                # coexist under one gamePk in the same landed response. Select
                # the completed schedule record that matches the governed
                # completed-game inventory; do not compare or carry scores,
                # winners, or any other target-game result field.
                expected_state = str(completed[game_pk].get("detailedState") or "")
                observed_state = str((game.get("status") or {}).get("detailedState") or "")
                if expected_state and observed_state != expected_state:
                    continue
                prior = raw_by_pk.get(game_pk)
                if prior is not None and _schedule_fact_signature(prior[0]) != _schedule_fact_signature(game):
                    prior_start = _parse_iso_utc(prior[0].get("gameDate"))
                    candidate_start = _parse_iso_utc(game.get("gameDate"))
                    signatures_without_start_match = (
                        _schedule_fact_signature(prior[0])[:1]
                        + _schedule_fact_signature(prior[0])[2:]
                        == _schedule_fact_signature(game)[:1]
                        + _schedule_fact_signature(game)[2:]
                    )
                    if (
                        prior_start is None
                        or candidate_start is None
                        or prior_start == candidate_start
                        or not (
                            signatures_without_start_match
                            or _same_suspended_game(prior[0], game)
                        )
                    ):
                        raise ContextSourceError(f"conflicting raw schedule game: {game_pk}")
                    # Suspended games may expose both the original first pitch
                    # and the later resumption as Final.  The feature authority
                    # is the original (earliest) scheduled first pitch.
                    if candidate_start < prior_start:
                        raw_by_pk[game_pk] = (game, snapshot)
                elif prior is None:
                    raw_by_pk[game_pk] = (game, snapshot)

    rows: list[dict[str, Any]] = []
    for canonical_id, source in games_from_pa.items():
        game_pk = source["mlbamGamePk"]
        raw_pair = raw_by_pk.get(game_pk)
        if raw_pair is None:
            raise ContextSourceError(f"current PA game absent from completed raw schedule: {game_pk}")
        raw, snapshot = raw_pair
        completed_row = completed[game_pk]
        venue = raw.get("venue") or {}
        receipt = partition_by_date.get(source["gameDate"].isoformat()) or {}
        request = receipt.get("request") or {}
        game_number = _strict_int(raw.get("gameNumber"))
        doubleheader = str(raw.get("doubleHeader") or "N") != "N"
        description = str(raw.get("description") or "").casefold()
        rows.append({
            **source,
            "sourceGameId": game_pk,
            "venueSource": "MLB_STATS_API",
            "venueSourceId": str(venue.get("id") or ""),
            "venueName": str(venue.get("name") or ""),
            "startTimeLocal": None,
            "scheduledStartUtc": _parse_iso_utc(raw.get("gameDate")),
            "seriesGameNumber": _strict_int(raw.get("seriesGameNumber")),
            "gamesInSeries": _strict_int(raw.get("gamesInSeries")),
            "doubleheaderGameNumber": (game_number if doubleheader else None),
            "isHomeOpener": "home opener" in description,
            "durationMinutes": None,
            "sourcePartitionId": str(snapshot.get("snapshotId") or ""),
            "sourceSha256": str(snapshot.get("rawSha256") or ""),
            "sourceCutoff": str(request.get("sourceCutoff") or "") or None,
            "completedState": completed_row.get("detailedState"),
        })
    return rows, {
        "currentSilverManifestSha256": str(verified["manifestSha256"]),
        "scheduleAuthoritySha256": schedule_sha,
        "rawScheduleSnapshots": raw_lineage,
        "duplicateSchedulePolicy": "COMPLETED_RECORD_THEN_EARLIEST_SCHEDULED_FIRST_PITCH",
    }


def load_context_source_bundle(
    *,
    legacy_bronze_root: Path = LEGACY_BRONZE_ROOT,
    current_bronze_root: Path = CURRENT_BRONZE_ROOT,
    legacy_silver_root: Path = LEGACY_SILVER_ROOT,
    current_silver_root: Path = CURRENT_SILVER_ROOT,
) -> ContextSourceBundle:
    """Return deterministic 2023--2026 regular-season game evidence."""

    legacy, legacy_authority = _legacy_games(
        bronze_root=Path(legacy_bronze_root), silver_root=Path(legacy_silver_root)
    )
    current, current_authority = _current_games(
        bronze_root=Path(current_bronze_root), silver_root=Path(current_silver_root)
    )
    raw_rows = legacy + current
    # Historical Retrosheet exposes game membership but not an explicit series
    # number.  Complete it deterministically from the landed schedule: a series
    # is a contiguous same-home/same-away/same-venue block with at most one
    # off-day.  This uses schedule identity only, never a result.
    blocks: dict[tuple[int, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for raw in raw_rows:
        blocks[(int(raw["season"]), str(raw["homeTeam"]), str(raw["awayTeam"]), str(raw["venueSourceId"]))].append(raw)
    for candidates in blocks.values():
        candidates.sort(key=lambda row: (
            row["gameDate"], _strict_int(row.get("doubleheaderGameNumber")) or 0,
            str(row["canonicalGameId"]),
        ))
        series: list[list[dict[str, Any]]] = []
        for raw in candidates:
            if not series or (raw["gameDate"] - series[-1][-1]["gameDate"]).days > 2:
                series.append([raw])
            else:
                series[-1].append(raw)
        for group in series:
            for position, raw in enumerate(group, 1):
                if _strict_int(raw.get("seriesGameNumber")) is None:
                    raw["seriesGameNumber"] = position
                if _strict_int(raw.get("gamesInSeries")) is None:
                    raw["gamesInSeries"] = len(group)
    first_home: dict[tuple[int, str], tuple[date, str]] = {}
    for raw in sorted(raw_rows, key=lambda row: (row["gameDate"], str(row["canonicalGameId"]))):
        key = (int(raw["season"]), str(raw["homeTeam"]))
        first_home.setdefault(key, (raw["gameDate"], str(raw["canonicalGameId"])))
    for raw in raw_rows:
        key = (int(raw["season"]), str(raw["homeTeam"]))
        raw["isHomeOpener"] = bool(raw.get("isHomeOpener")) or first_home.get(key) == (
            raw["gameDate"], str(raw["canonicalGameId"])
        )
    seen: set[str] = set()
    games: list[ContextSourceGame] = []
    for raw in sorted(raw_rows, key=lambda row: (row["gameDate"], str(row["canonicalGameId"]))):
        canonical_id = str(raw["canonicalGameId"])
        if canonical_id in seen:
            raise ContextSourceError(f"duplicate canonical game source: {canonical_id}")
        seen.add(canonical_id)
        venue_source = str(raw.get("venueSource") or "")
        venue_source_id = str(raw.get("venueSourceId") or "")
        if not venue_source_id:
            raise ContextSourceError(f"game lacks exact venue source id: {canonical_id}")
        games.append(ContextSourceGame(
            canonical_game_id=canonical_id,
            season=int(raw["season"]),
            game_date=raw["gameDate"],
            home_team_id=str(raw["homeTeam"]),
            away_team_id=str(raw["awayTeam"]),
            venue_key=f"{venue_source}:{venue_source_id}",
            scheduled_start_utc=raw.get("scheduledStartUtc"),
            start_time_local=str(raw.get("startTimeLocal") or "") or None,
            series_game_number=_strict_int(raw.get("seriesGameNumber")),
            games_in_series=_strict_int(raw.get("gamesInSeries")),
            doubleheader_game_number=_strict_int(raw.get("doubleheaderGameNumber")),
            is_home_opener=bool(raw.get("isHomeOpener")),
            duration_minutes=_strict_int(raw.get("durationMinutes")),
            innings_played=_strict_int(raw.get("inningsPlayed")),
            source_game_id=str(raw.get("sourceGameId") or ""),
            source_partition_id=str(raw.get("sourcePartitionId") or ""),
            source_sha256=str(raw.get("sourceSha256") or ""),
            source_cutoff=str(raw.get("sourceCutoff") or "") or None,
        ))
    if {game.season for game in games} != {2023, 2024, 2025, 2026}:
        raise ContextSourceError("context source seasons do not reconcile to 2023--2026")
    return ContextSourceBundle(
        games=tuple(games),
        authorities={"legacy": legacy_authority, "current": current_authority},
    )


__all__ = [
    "ContextSourceBundle",
    "ContextSourceError",
    "ContextSourceGame",
    "load_context_source_bundle",
]
