"""Bounded acquisition of licensed hoopR NBA team-game box exports.

NBA.com Stats is intentionally not contacted: its published terms are
incompatible with the intended downstream use. This downloader has no retry
loop, enforces request/byte ceilings, and writes content-addressed raw evidence
outside Git.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.request

import pandas as pd

SEASONS = tuple(range(2019, 2027))
BOX_URL = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_team_boxscores/team_box_{season}.parquet"
SCHEDULE_URL = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_schedules/nba_schedule_{season}.parquet"
MAX_REQUESTS = 20
MAX_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 32 * 1024 * 1024
DELAY_SECONDS = 2.0
REQUIRED_GROUPS = {
    "game": ("game_id", "game_uid"),
    "team": ("team_id", "team_uid"),
    "date": ("game_date", "game_date_time"),
    "fgm": ("field_goals_made", "fgm"),
    "fga": ("field_goals_attempted", "fga"),
    "fg3m": ("three_point_field_goals_made", "fg3m"),
    "fg3a": ("three_point_field_goals_attempted", "fg3a"),
    "ftm": ("free_throws_made", "ftm"),
    "fta": ("free_throws_attempted", "fta"),
    "oreb": ("offensive_rebounds", "oreb"),
    "dreb": ("defensive_rebounds", "dreb"),
    "reb": ("total_rebounds", "rebounds", "reb"),
    "tov": ("turnovers", "tov"),
    "points": ("team_score", "points", "pts"),
}


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def schema_fingerprint(frame: pd.DataFrame) -> str:
    value = [(str(name), str(dtype)) for name, dtype in frame.dtypes.items()]
    return hashlib.sha256(canonical_json(value)).hexdigest()


def inspect(raw: bytes, kind: str) -> dict:
    import io
    frame = pd.read_parquet(io.BytesIO(raw))
    lower = {str(c).lower(): str(c) for c in frame.columns}
    groups = REQUIRED_GROUPS if kind == "team_box" else {
        "game": ("game_id", "id"), "date": ("game_date_time", "date"),
        "season": ("season",), "season_type": ("season_type",),
        "home": ("home_id",), "away": ("away_id",),
        "period": ("status_period",), "completed": ("status_type_completed",),
    }
    resolved = {}
    for role, choices in groups.items():
        match = next((lower[c] for c in choices if c in lower), None)
        if match is None:
            raise RuntimeError(f"schema instability: missing required {role} field")
        resolved[role] = match
    return {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "columnNames": [str(c) for c in frame.columns],
        "requiredFieldMapping": resolved,
        "schemaFingerprint": schema_fingerprint(frame),
    }


def fetch(kind: str, season: int, root: Path) -> tuple[dict, bytes]:
    template = BOX_URL if kind == "team_box" else SCHEDULE_URL
    filename = f"team_box_{season}.parquet" if kind == "team_box" else f"nba_schedule_{season}.parquet"
    release = "espn_nba_team_boxscores" if kind == "team_box" else "espn_nba_schedules"
    url = template.format(season=season)
    request = urllib.request.Request(url, headers={"User-Agent": "ASP-Model-Studio/1.0 governed historical research"})
    retrieved = datetime.now(timezone.utc).isoformat()
    with urllib.request.urlopen(request, timeout=90) as response:  # nosec B310: fixed allowlisted HTTPS template
        status = int(response.status)
        if status != 200:
            raise RuntimeError(f"access refusal for {season}: HTTP {status}")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_FILE_BYTES:
            raise RuntimeError(f"season {season} exceeds per-file byte guard")
        raw = response.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise RuntimeError(f"season {season} exceeds per-file byte guard")
        headers = {k: v for k, v in response.headers.items() if k.lower() in {
            "content-type", "content-length", "etag", "last-modified", "x-github-request-id"
        }}
        final_url = response.geturl()
    if raw[:4] != b"PAR1" or raw[-4:] != b"PAR1":
        raise RuntimeError(f"non-Parquet response for {season}")
    sha = hashlib.sha256(raw).hexdigest()
    target = root / "raw" / "sha256" / sha / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != raw:
        raise RuntimeError("content-address collision")
    target.write_bytes(raw)
    return {
        "kind": kind,
        "seasonEndYear": season,
        "seasonLabel": f"{season-1}-{str(season)[-2:]}",
        "seasonType": "MIXED_SOURCE_ROWS_REQUIRE_GOVERNED_FILTER",
        "endpoint": "SportsDataverse GitHub release asset",
        "parameters": {"release": release, "asset": filename},
        "requestedUrl": url,
        "resolvedUrl": final_url,
        "retrievedAtUtc": retrieved,
        "httpStatus": status,
        "responseHeaders": headers,
        "sha256": sha,
        "bytes": len(raw),
        "path": str(target.resolve()),
        "predecessor": None,
        "correctionOf": None,
    }, raw


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    plan = {
        "source": "SportsDataverse/hoopR ESPN-derived team boxes",
        "urls": [BOX_URL.format(season=s) for s in SEASONS] + [SCHEDULE_URL.format(season=s) for s in SEASONS],
        "maximumRequests": MAX_REQUESTS,
        "maximumBytes": MAX_BYTES,
        "minimumDelaySeconds": DELAY_SECONDS,
        "retries": 0,
        "costUsd": 0,
        "execute": bool(args.execute),
    }
    print(json.dumps(plan, indent=2))
    if not args.execute:
        return
    root.mkdir(parents=True, exist_ok=True)
    if (root / "acquisition-receipt.json").exists():
        raise RuntimeError("receipt exists; use a new immutable acquisition identity")
    ledger_path = root / "request-ledger.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_bytes())
    else:
        # The first response was retained by the original fail-closed run before
        # the missing-minutes exception. Preserve it without making a duplicate
        # request; exact response headers are unavailable and stay disclosed.
        existing = list((root / "raw" / "sha256").glob("*/team_box_2019.parquet"))
        ledger = {"schemaVersion": "NBA_GEN2_ACQUISITION_REQUEST_LEDGER_V1", "requests": []}
        if existing:
            raw = existing[0].read_bytes()
            profile = inspect(raw, "team_box")
            ledger["requests"].append({
                "kind": "team_box", "seasonEndYear": 2019, "seasonLabel": "2018-19",
                "seasonType": "MIXED_SOURCE_ROWS_REQUIRE_GOVERNED_FILTER",
                "endpoint": "SportsDataverse GitHub release asset",
                "parameters": {"release": "espn_nba_team_boxscores", "asset": "team_box_2019.parquet"},
                "requestedUrl": BOX_URL.format(season=2019), "resolvedUrl": None,
                "retrievedAtUtc": datetime.fromtimestamp(existing[0].stat().st_ctime, timezone.utc).isoformat(),
                "httpStatus": 200, "responseHeaders": {}, "responseHeaderQualification": "Unavailable: original run failed before ledger persistence; no duplicate request made.",
                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "path": str(existing[0].resolve()),
                "schemaFingerprint": profile["schemaFingerprint"], "profile": profile,
                "predecessor": None, "correctionOf": None,
            })
            write_json(ledger_path, ledger)
    requests = ledger["requests"]
    total = sum(int(x["bytes"]) for x in requests)
    done = {(x["kind"], int(x["seasonEndYear"])) for x in requests}
    assets = [("team_box", season) for season in SEASONS] + [("schedule", season) for season in SEASONS]
    pending = [(kind, season) for kind, season in assets if (kind, season) not in done]
    for offset, (kind, season) in enumerate(pending):
        if len(requests) >= MAX_REQUESTS:
            raise RuntimeError("request ceiling")
        record, raw = fetch(kind, season, root)
        total += record["bytes"]
        if total > MAX_BYTES:
            raise RuntimeError("response-byte ceiling")
        requests.append(record)
        write_json(ledger_path, ledger)
        try:
            profile = inspect(raw, kind)
        except Exception as exc:
            write_json(root / "acquisition-failure.json", {
                "failedAtUtc": datetime.now(timezone.utc).isoformat(), "request": record,
                "successfulHttpRequests": len(requests), "responseBytes": total,
                "error": str(exc), "disposition": "STOPPED_FAIL_CLOSED",
            })
            raise
        record["schemaFingerprint"] = profile["schemaFingerprint"]
        record["profile"] = profile
        write_json(ledger_path, ledger)
        if offset + 1 < len(pending):
            time.sleep(DELAY_SECONDS)
    receipt = {
        "schemaVersion": "NBA_GEN2_TEAM_BOX_ACQUISITION_RECEIPT_V1",
        "completedAtUtc": datetime.now(timezone.utc).isoformat(),
        "classification": "CATEGORY_A_RECONSTRUCTED_HISTORICAL_EVIDENCE",
        "provider": "SportsDataverse/hoopR-nba-data",
        "underlyingSource": "ESPN",
        "license": "CC BY 4.0",
        "nbaComRequests": 0,
        "successfulHttpRequests": len(requests),
        "responseBytes": total,
        "costUsd": 0,
        "requests": requests,
        "historicalVintageQualification": "Current retrieval does not establish original historical publication timing.",
    }
    raw = canonical_json(receipt)
    sha = hashlib.sha256(raw).hexdigest()
    receipt["contentIdentitySha256"] = sha
    final = canonical_json(receipt)
    (root / "acquisition-receipt.json").write_bytes(final)
    print(json.dumps({"receipt": str(root / "acquisition-receipt.json"), "sha256": hashlib.sha256(final).hexdigest(), "requests": len(requests), "bytes": total}, indent=2))


if __name__ == "__main__":
    main()
