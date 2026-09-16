"""Retain the real current M1 inputs and publication bindings for a bounded update."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sports_nfl.gold import ROLLING_METRICS
from server.sports_nfl_m1.prospective_shadow import (
    _json_value, _load_targets, load_foundation_runtime, materialize_feature_vector,
    MODEL_MANIFEST_SHA256, MODEL_BINARY_SHA256,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selection", type=Path, help="Reuse the before snapshot's targets and selection clock")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Snapshot already exists; preserve it and choose a new path")
    now = datetime.now(timezone.utc)
    previous = json.loads(args.selection.read_bytes()) if args.selection else None
    selected_at = datetime.fromisoformat(previous["selectionAtUtc"]) if previous else now
    staging = Path("C:/Users/james/asp-data-staging/nfl")
    runtime = load_foundation_runtime(staging / "foundation-v1")
    targets, team_games, _ = _load_targets(runtime, as_of=selected_at)
    wanted = {x["canonicalGameId"] for x in previous["targets"]} if previous else None
    targets = [x for x in targets if (str(x["canonical_game_id"]) in wanted if wanted else x["scheduled_start_utc"] <= selected_at + timedelta(days=7))]
    pointers = {}
    for name, path in {
        "foundation": staging / "foundation-v1/current.json",
        "bronze": staging / "bronze-v1/current.json",
        "prospective": staging / "m1-prospective-shadow-v1/prospective-index.json",
    }.items():
        raw = path.read_bytes()
        pointers[name] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "byteCount": len(raw), "value": json.loads(raw)}
    bronze = json.loads((staging / "bronze-v1" / pointers["bronze"]["value"]["manifestRelativePath"]).read_bytes())
    current_rows = team_games.loc[team_games.season.eq(2026) & team_games.completed.eq(True)]
    facts = [{k: _json_value(v) for k, v in x.items()} for x in current_rows.to_dict("records")]
    latest = {}
    for metric in ROLLING_METRICS:
        valid = team_games.loc[team_games.completed.eq(True) & team_games[metric].notna()]
        latest[metric] = None if valid.empty else str(valid.game_date.max())
    records = []
    for target in targets:
        game = str(target["canonical_game_id"])
        vector = materialize_feature_vector(target, team_games)
        raw = json.dumps(vector, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        records.append({
            "canonicalGameId": game, "scheduledStartUtc": target["scheduled_start_utc"].isoformat(),
            "target": {k: _json_value(v) for k, v in target.items()}, "features": vector,
            "valuesAuditSha256": hashlib.sha256(raw).hexdigest(),
            "existingForecasts": pointers["prospective"]["value"]["events"].get(game),
        })
    tracked = subprocess.check_output(["git", "diff", "--name-only"], text=True).splitlines()
    payload = {
        "contract": "NFL_M1_INPUT_UPDATE_SNAPSHOT_V1", "createdAtUtc": now.isoformat(),
        "selectionAtUtc": selected_at.isoformat(), "windowDays": 7,
        "branch": subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "trackedWorkingFiles": [{"path": p, "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()} for p in tracked if Path(p).is_file()],
        "modelManifestSha256": MODEL_MANIFEST_SHA256, "modelBinarySha256": MODEL_BINARY_SHA256,
        "sourceCutoffUtc": runtime.schedule_as_of_utc,
        "pointers": pointers, "targets": records, "completed2026TeamFacts": facts,
        "latestCompletedDateByNumericalMetric": latest,
        "currentSourcePartitions": [x for x in bronze["partitions"] if x["familyId"] == "schedules" or (x.get("season") == 2026 and x["familyId"] in ("play_by_play", "weekly_player_stats", "weekly_team_stats"))],
        "playerFeaturesActiveInM1": False,
        "featureDefinition": "197 LONG_HISTORY_CORE features; completed strict-prior-date games; season-to-date and last 4/8/16 games; no target outcomes or market fields",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(), "targets": len(records), "completed2026TeamFacts": facts, "latestMetricDates": latest}, default=str))


if __name__ == "__main__":
    main()
