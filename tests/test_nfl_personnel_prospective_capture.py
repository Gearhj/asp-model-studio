from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from server.sports_nfl_m1.personnel_capture import build_capture_plan
from server.sports_nfl_m1.personnel_evidence import canonical_json_bytes
from server.sports_nfl_m1.personnel_prospective import (
    due_slot, load_outcome_free_schedule, project_capture, requests_used_on_utc_day,
)


def put_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def foundation(root: Path) -> None:
    object_id = "a" * 64
    target = root / "objects" / "sha256" / object_id / "object.parquet"
    target.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist([{
        "game_id": "2026_02_AAA_BBB", "season": 2026, "game_type": "REG", "week": 2,
        "gameday": "2026-09-20", "gametime": "13:00", "away_team": "AAA", "home_team": "BBB",
        "away_score": 99, "home_score": 98, "result": -1, "total": 197,
    }]), target)
    manifest = {"objects": [{"tableName": "snapshot_nfl_schedule", "manifestSha256": object_id}]}
    manifest_path = root / "manifests" / "foundation.json"
    put_json(manifest_path, manifest)
    put_json(root / "CURRENT.json", {"relativeManifestPath": "manifests/foundation.json"})


def test_live_plan_omits_schedule_and_stays_within_budget() -> None:
    plan = build_capture_plan(2026, include_schedule=False)
    assert len(plan.assets) == 6
    assert "schedules" not in {item.family_id for item in plan.assets}


def test_isolated_deployment_uses_minimal_package_initializer() -> None:
    from scripts.build_nfl_personnel_capture_deployment import DEPLOYMENT_MEMBERS
    mapping = dict(DEPLOYMENT_MEMBERS)
    assert mapping["server/sports_nfl_m1/personnel_deployment_init.py"] == "server/sports_nfl_m1/__init__.py"
    assert "server/sports_nfl_m1/__init__.py" not in mapping


def test_slot_gate_is_timezone_aware_and_idempotent() -> None:
    now = datetime(2026, 9, 17, 11, 20, tzinfo=timezone.utc)  # 07:20 EDT Thursday
    key = due_slot(now, [])
    assert key == "2026-09-17T07:15:00[EDT]"
    assert due_slot(now, [key]) is None


def test_schedule_projection_never_reads_outcomes(tmp_path: Path) -> None:
    foundation(tmp_path)
    rows, lineage = load_outcome_free_schedule(tmp_path)
    assert rows == [{"eventId": "2026_02_AAA_BBB", "season": 2026, "week": 2,
                     "awayTeamId": "AAA", "homeTeamId": "BBB", "kickoffUtc": "2026-09-20T17:00:00Z"}]
    assert "away_score" not in lineage["readColumns"]
    assert "away_score" in lineage["excludedOutcomeAndMarketColumns"]


def test_projection_records_probable_not_confirmed_qb(tmp_path: Path) -> None:
    base = tmp_path / "foundation"
    foundation(base)
    raw = tmp_path / "raw"
    families = {
        "injuries": [{"season": 2026, "week": 2, "team": "AAA", "gsis_id": "QB1", "position": "QB", "report_status": "Questionable"}],
        "weekly_rosters": [
            {"season": 2026, "week": 2, "game_type": "REG", "team": "AAA", "position": "QB", "status": "ACT", "gsis_id": "QB1"},
            {"season": 2026, "week": 2, "game_type": "REG", "team": "BBB", "position": "QB", "status": "ACT", "gsis_id": "QB2"},
        ],
        "depth_charts": [
            {"dt": "2026-09-17T06:00:00Z", "team": "AAA", "gsis_id": "QB1", "pos_abb": "QB", "pos_rank": 1},
            {"dt": "2026-09-17T06:00:00Z", "team": "BBB", "gsis_id": "QB2", "pos_abb": "QB", "pos_rank": 1},
        ],
        "snap_counts": [{"game_id": "2026_01_AAA_CCC", "season": 2026, "week": 1, "team": "AAA", "pfr_player_id": "p1", "position": "QB", "offense_snaps": 60}],
        "players": [{"gsis_id": "QB1", "display_name": "Fixture Quarterback", "position": "QB"}],
        "draft_picks": [{"season": 2025, "round": 1, "pick": 1, "team": "AAA", "gsis_id": "QB1", "position": "QB"}],
    }
    objects = []
    for family, rows in families.items():
        path = raw / f"{family}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        objects.append({"familyId": family, "disposition": "WRITTEN_NEW_OBJECT", "objectPath": str(path),
                        "physicalSha256": digest, "retrievedAtUtc": "2026-09-17T12:00:00Z"})
    receipt = {"capturedAtUtc": "2026-09-17T12:00:00Z", "objects": objects}
    result = project_capture(capture_receipt=receipt, data_root=tmp_path / "data", foundation_root=base)
    assert result["week"] == 2 and result["gameCount"] == 1
    assert result["expectedQuarterbackDispositions"]["PROBABLE_FROM_CURRENT_DEPTH_CHART"] == 2
    assert result["expectedQuarterbackDispositions"]["CONFIRMED_PREGAME"] == 0


def test_daily_request_counter_counts_receipts_only(tmp_path: Path) -> None:
    put_json(tmp_path / "receipts" / "sha256" / ("b" * 64) / "receipt.json",
             {"capturedAtUtc": "2026-09-17T12:00:00Z", "requestCount": 6})
    put_json(tmp_path / "receipts" / "sha256" / ("c" * 64) / "receipt.json",
             {"capturedAtUtc": "2026-09-16T12:00:00Z", "requestCount": 6})
    assert requests_used_on_utc_day(tmp_path, "2026-09-17") == 6
