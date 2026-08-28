"""Immutable MLB Stats API schedule authority for the current Statcast extension.

This module is deliberately narrow: it preserves the provider's raw schedule JSON,
records its exact SHA-256, and publishes a deterministic inventory of completed MLB
regular-season games.  It does not normalize Statcast rows, call model code, or make
non-final games eligible for downstream completeness checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from . import CURRENT_STATCAST_MAX_DATE
from .download import http_download, sha256_file
from .manifest import canonical_json_bytes, sha256_bytes
from .safety import BronzeBoundaryError, assert_current_statcast_date_allowed, contained_path


SCHEDULE_AUTHORITY_CONTRACT = "MLB_CURRENT_STATCAST_SCHEDULE_AUTHORITY_V1"
SCHEDULE_SNAPSHOT_CONTRACT = "MLB_STATS_API_REGULAR_SCHEDULE_SNAPSHOT_V1"
SCHEDULE_ENDPOINT = "https://statsapi.mlb.com/api/v1/schedule"
COMPLETED_DETAILED_STATES = frozenset({"Final", "Completed Early"})


class ScheduleAuthorityError(RuntimeError):
    """The official schedule response or its persisted authority is invalid."""


Downloader = Callable[..., dict[str, Any]]


def schedule_url(start_date: str, end_date: str) -> str:
    """Return the bounded official MLB regular-season schedule URL."""

    start = assert_current_statcast_date_allowed(start_date)
    end = assert_current_statcast_date_allowed(end_date)
    if start > end:
        raise BronzeBoundaryError(f"schedule start date {start} is after end date {end}")
    query = urlencode(
        {
            "sportId": "1",
            "gameTypes": "R",
            "startDate": start,
            "endDate": end,
        }
    )
    return f"{SCHEDULE_ENDPOINT}?{query}"


def _as_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ScheduleAuthorityError(f"{field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ScheduleAuthorityError(f"{field} must be an integer") from exc
    if parsed <= 0:
        raise ScheduleAuthorityError(f"{field} must be positive")
    return parsed


def _team_identity(side: Any, *, field: str) -> tuple[int, str | None]:
    if not isinstance(side, dict) or not isinstance(side.get("team"), dict):
        raise ScheduleAuthorityError(f"missing {field}.team identity")
    team = side["team"]
    team_id = _as_int(team.get("id"), field=f"{field}.team.id")
    name = team.get("name")
    return team_id, str(name) if name is not None else None


def _status_text(status: dict[str, Any], field: str) -> str | None:
    value = status.get(field)
    return str(value) if value is not None else None


def _validate_provider_date(value: str, *, field: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ScheduleAuthorityError(f"{field} is not a valid YYYY-MM-DD date: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ScheduleAuthorityError(f"{field} is not a canonical YYYY-MM-DD date: {value!r}")
    return value


def _exclusion_reason(
    *, official_date: str, start_date: str, end_date: str, detailed_state: str
) -> str | None:
    if official_date > CURRENT_STATCAST_MAX_DATE:
        return "OFFICIAL_DATE_AFTER_AUTHORIZED_CUTOFF"
    if official_date > end_date:
        return "OFFICIAL_DATE_AFTER_REQUEST_WINDOW"
    if official_date < start_date:
        return "OFFICIAL_DATE_BEFORE_REQUEST_WINDOW"
    if detailed_state not in COMPLETED_DETAILED_STATES:
        return "STATUS_NOT_COMPLETED"
    return None


def _observation_key(observation: dict[str, Any]) -> bytes:
    return canonical_json_bytes(observation)


def _merge_schedule_observations(
    prior: dict[str, Any], current: dict[str, Any], *, game_pk: int
) -> dict[str, Any]:
    """Reconcile provider status progression for one immutable game identity.

    A broad Stats API range can repeat the same ``gamePk`` under its original
    postponed schedule date and its completed makeup date. Identity must remain
    byte-equivalent; the sole allowed state progression has exactly one completed
    observation, which becomes authoritative. All observations remain enumerated.
    """

    non_status_keys = set(prior).union(current) - {"detailedState", "scheduleObservations"}
    differing_identity = [key for key in sorted(non_status_keys) if prior.get(key) != current.get(key)]
    if differing_identity:
        raise ScheduleAuthorityError(
            f"conflicting duplicate schedule identity for gamePk {game_pk}; "
            f"differing fields: {differing_identity}"
        )

    prior_state = prior["detailedState"]
    current_state = current["detailedState"]
    if prior_state == current_state:
        selected = dict(prior)
    else:
        prior_completed = prior_state in COMPLETED_DETAILED_STATES
        current_completed = current_state in COMPLETED_DETAILED_STATES
        if prior_completed == current_completed:
            raise ScheduleAuthorityError(
                f"ambiguous duplicate schedule statuses for gamePk {game_pk}: "
                f"{sorted({prior_state, current_state})}"
            )
        selected = dict(prior if prior_completed else current)

    observations = {
        _observation_key(observation): observation
        for observation in prior.get("scheduleObservations", [])
        + current.get("scheduleObservations", [])
    }
    selected["scheduleObservations"] = [
        observations[key] for key in sorted(observations)
    ]
    return selected


def parse_schedule_payload(raw: bytes, *, start_date: str, end_date: str) -> dict[str, Any]:
    """Parse one raw Stats API response into completed and excluded game inventories.

    Only ``Final`` and ``Completed Early`` are admitted to ``completedGames``. Every
    other status remains visible in ``excludedGames`` but cannot contribute to the
    current-season schedule authority.
    """

    start = assert_current_statcast_date_allowed(start_date)
    end = assert_current_statcast_date_allowed(end_date)
    if start > end:
        raise BronzeBoundaryError(f"schedule start date {start} is after end date {end}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScheduleAuthorityError("MLB Stats API schedule response is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("dates"), list):
        raise ScheduleAuthorityError("MLB Stats API schedule response has no dates array")

    seen: dict[int, dict[str, Any]] = {}
    for date_entry in payload.get("dates", []):
        if not isinstance(date_entry, dict) or not isinstance(date_entry.get("games", []), list):
            raise ScheduleAuthorityError("schedule date entry has no games array")
        entry_date = str(date_entry.get("date") or "")
        assert_current_statcast_date_allowed(entry_date)
        if entry_date < start or entry_date > end:
            raise ScheduleAuthorityError(
                f"schedule entry date {entry_date} is outside request [{start}, {end}]"
            )
        for game in date_entry.get("games", []):
            if not isinstance(game, dict):
                raise ScheduleAuthorityError("schedule game entry is not an object")
            game_pk = _as_int(game.get("gamePk"), field="gamePk")
            official_date = _validate_provider_date(
                str(game.get("officialDate") or entry_date), field=f"gamePk {game_pk} officialDate"
            )
            game_type = str(game.get("gameType") or "")
            if game_type != "R":
                raise ScheduleAuthorityError(
                    f"gamePk {game_pk} has non-regular gameType {game_type!r} in regular-season response"
                )
            status = game.get("status")
            if not isinstance(status, dict):
                raise ScheduleAuthorityError(f"gamePk {game_pk} has no status object")
            detailed_state = str(status.get("detailedState") or "")
            if not detailed_state:
                raise ScheduleAuthorityError(f"gamePk {game_pk} has no detailedState")
            teams = game.get("teams")
            if not isinstance(teams, dict):
                raise ScheduleAuthorityError(f"gamePk {game_pk} has no teams object")
            away_id, away_name = _team_identity(teams.get("away"), field="teams.away")
            home_id, home_name = _team_identity(teams.get("home"), field="teams.home")
            observation = {
                "scheduleDate": entry_date,
                "officialDate": official_date,
                "detailedState": detailed_state,
                "abstractGameState": _status_text(status, "abstractGameState"),
                "codedGameState": _status_text(status, "codedGameState"),
                "statusCode": _status_text(status, "statusCode"),
                "reason": _status_text(status, "reason"),
                "providerGameDate": _status_text(game, "gameDate"),
            }
            record = {
                "gamePk": game_pk,
                "gameDate": official_date,
                "season": int(official_date[:4]),
                "gameType": "R",
                "detailedState": detailed_state,
                "awayTeamId": away_id,
                "awayTeamName": away_name,
                "homeTeamId": home_id,
                "homeTeamName": home_name,
                "scheduleObservations": [observation],
            }
            prior = seen.get(game_pk)
            seen[game_pk] = (
                _merge_schedule_observations(prior, record, game_pk=game_pk)
                if prior is not None
                else record
            )

    completed: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for record in seen.values():
        reason = _exclusion_reason(
            official_date=record["gameDate"],
            start_date=start,
            end_date=end,
            detailed_state=record["detailedState"],
        )
        authoritative_record = {**record, "authorityExclusionReason": reason}
        (excluded if reason else completed).append(authoritative_record)
    completed.sort(key=lambda record: (record["gameDate"], record["gamePk"]))
    excluded.sort(key=lambda record: (record["gameDate"], record["gamePk"]))
    return {
        "completedGames": completed,
        "excludedGames": excluded,
    }


def _snapshot_id(start_date: str, end_date: str) -> str:
    return f"mlb-stats-api/regular/{start_date}/{end_date}"


def _raw_relative_path(start_date: str, end_date: str) -> str:
    return f"mlb-stats-api/regular/start={start_date}/end={end_date}/schedule.json"


def _verify_json(path: Path) -> None:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScheduleAuthorityError("downloaded schedule response is not valid UTF-8 JSON") from exc


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScheduleAuthorityError("persisted schedule authority manifest is invalid JSON") from exc
    if manifest.get("manifestContract") != SCHEDULE_AUTHORITY_CONTRACT or manifest.get("manifestVersion") != 1:
        raise ScheduleAuthorityError("persisted schedule authority manifest has the wrong contract/version")
    if not isinstance(manifest.get("snapshots", []), list):
        raise ScheduleAuthorityError("persisted schedule authority manifest has no snapshots array")
    return manifest


def _snapshot_range(snapshot: dict[str, Any]) -> tuple[str, str]:
    return str(snapshot.get("startDate") or ""), str(snapshot.get("endDate") or "")


def _ranges_overlap(left: tuple[str, str], right: tuple[str, str]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]


def _season_counts(completed: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    years = sorted({record["season"] for record in completed + excluded})
    result: list[dict[str, Any]] = []
    for season in years:
        accepted = [record for record in completed if record["season"] == season]
        rejected = [record for record in excluded if record["season"] == season]
        statuses = Counter(record["detailedState"] for record in accepted + rejected)
        result.append(
            {
                "season": season,
                "scheduledGameCount": len(accepted) + len(rejected),
                "completedGameCount": len(accepted),
                "excludedGameCount": len(rejected),
                "statusCounts": dict(sorted(statuses.items())),
            }
        )
    return result


def _build_manifest(root: Path, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    completed_by_pk: dict[int, dict[str, Any]] = {}
    excluded_by_pk: dict[int, dict[str, Any]] = {}
    for snapshot in sorted(snapshots, key=lambda item: item["snapshotId"]):
        raw_path = contained_path(root, *Path(snapshot["rawRelativePath"]).parts)
        if not raw_path.is_file():
            raise ScheduleAuthorityError(f"authoritative raw schedule is missing: {snapshot['rawRelativePath']}")
        actual_sha = sha256_file(raw_path)
        if actual_sha != snapshot.get("rawSha256"):
            raise ScheduleAuthorityError(
                f"authoritative raw schedule SHA mismatch for {snapshot['snapshotId']}: "
                f"expected {snapshot.get('rawSha256')}, got {actual_sha}"
            )
        parsed = parse_schedule_payload(
            raw_path.read_bytes(), start_date=snapshot["startDate"], end_date=snapshot["endDate"]
        )
        for destination, records in (
            (completed_by_pk, parsed["completedGames"]),
            (excluded_by_pk, parsed["excludedGames"]),
        ):
            for record in records:
                prior = destination.get(record["gamePk"])
                if prior is not None and prior != record:
                    raise ScheduleAuthorityError(
                        f"conflicting game identity across snapshots for gamePk {record['gamePk']}"
                    )
                destination[record["gamePk"]] = record
    collision = set(completed_by_pk).intersection(excluded_by_pk)
    if collision:
        raise ScheduleAuthorityError(f"gamePks appear as both completed and excluded: {sorted(collision)}")
    completed = sorted(completed_by_pk.values(), key=lambda record: (record["gameDate"], record["gamePk"]))
    excluded = sorted(excluded_by_pk.values(), key=lambda record: (record["gameDate"], record["gamePk"]))
    return {
        "manifestContract": SCHEDULE_AUTHORITY_CONTRACT,
        "manifestVersion": 1,
        "source": "MLB Stats API",
        "sportId": 1,
        "gameType": "R",
        "acceptedDetailedStates": sorted(COMPLETED_DETAILED_STATES),
        "snapshotCount": len(snapshots),
        "snapshots": sorted(snapshots, key=lambda item: item["snapshotId"]),
        "completedGameCount": len(completed),
        "completedGames": completed,
        "excludedGameCount": len(excluded),
        "excludedGames": excluded,
        "seasonCounts": _season_counts(completed, excluded),
    }


def acquire_schedule_authority(
    staging_root: Path,
    *,
    start_date: str,
    end_date: str,
    downloader: Downloader = http_download,
) -> dict[str, Any]:
    """Acquire or resume one immutable schedule snapshot and rebuild its authority.

    The supplied staging root is expected to be outside Git. Existing raw bytes are
    reused without a provider call. If a recorded raw file changes, verification
    fails closed instead of downloading over it.
    """

    root = Path(staging_root)
    start = assert_current_statcast_date_allowed(start_date)
    end = assert_current_statcast_date_allowed(end_date)
    if start > end:
        raise BronzeBoundaryError(f"schedule start date {start} is after end date {end}")
    manifest_path = contained_path(root, "manifests", "mlb-stats-api-schedule-authority.json")
    prior_manifest = _load_manifest(manifest_path)
    snapshots = list(prior_manifest.get("snapshots", [])) if prior_manifest else []
    snapshot_id = _snapshot_id(start, end)
    raw_relative = _raw_relative_path(start, end)
    raw_path = contained_path(root, *Path(raw_relative).parts)
    existing = next((item for item in snapshots if item.get("snapshotId") == snapshot_id), None)

    for snapshot in snapshots:
        if snapshot.get("snapshotId") == snapshot_id:
            continue
        if _ranges_overlap((start, end), _snapshot_range(snapshot)):
            raise ScheduleAuthorityError(
                f"schedule request [{start}, {end}] overlaps immutable snapshot "
                f"[{snapshot.get('startDate')}, {snapshot.get('endDate')}]"
            )

    if raw_path.is_file():
        raw_sha = sha256_file(raw_path)
        if existing is not None and raw_sha != existing.get("rawSha256"):
            raise ScheduleAuthorityError(
                f"authoritative raw schedule SHA mismatch for {snapshot_id}: "
                f"expected {existing.get('rawSha256')}, got {raw_sha}"
            )
    else:
        if existing is not None:
            raise ScheduleAuthorityError(f"recorded authoritative raw schedule is missing: {raw_relative}")
        receipt = downloader(
            schedule_url(start, end),
            raw_path,
            expect_not_html=True,
            verify_fn=_verify_json,
        )
        if not raw_path.is_file():
            raise ScheduleAuthorityError("schedule downloader did not create the requested raw artifact")
        raw_sha = sha256_file(raw_path)
        receipt_sha = receipt.get("sha256") if isinstance(receipt, dict) else None
        if receipt_sha is not None and receipt_sha != raw_sha:
            raise ScheduleAuthorityError("schedule downloader receipt SHA does not match persisted raw bytes")

    parsed = parse_schedule_payload(raw_path.read_bytes(), start_date=start, end_date=end)
    snapshot = {
        "snapshotContract": SCHEDULE_SNAPSHOT_CONTRACT,
        "snapshotId": snapshot_id,
        "startDate": start,
        "endDate": end,
        "requestUrl": schedule_url(start, end),
        "rawRelativePath": raw_relative,
        "rawByteCount": raw_path.stat().st_size,
        "rawSha256": raw_sha,
        "completedGameCount": len(parsed["completedGames"]),
        "excludedGameCount": len(parsed["excludedGames"]),
    }
    snapshots = [item for item in snapshots if item.get("snapshotId") != snapshot_id] + [snapshot]
    manifest = _build_manifest(root, snapshots)
    body = canonical_json_bytes(manifest)
    manifest_sha = sha256_bytes(body)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_bytes(body)
    tmp.replace(manifest_path)
    sha_path = manifest_path.with_suffix(".sha256")
    sha_path.write_text(f"{manifest_sha}  {manifest_path.name}\n", encoding="utf-8")
    return {
        "manifestPath": str(manifest_path),
        "manifestSha256": manifest_sha,
        "rawPath": str(raw_path),
        "rawSha256": raw_sha,
        "completedGameCount": manifest["completedGameCount"],
        "excludedGameCount": manifest["excludedGameCount"],
        "seasonCounts": manifest["seasonCounts"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire immutable official MLB regular-season schedule authority")
    parser.add_argument("--staging-root", required=True, type=Path)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    args = parser.parse_args(argv)
    result = acquire_schedule_authority(
        args.staging_root,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
