from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from server.sports_current_statcast import mlb_v18_daily_slate as daily


CAPTURE = datetime(2026, 9, 8, 15, 0, tzinfo=UTC)
START = CAPTURE + timedelta(hours=4)


def snapshot(game_id: str = "game-1") -> dict:
    sides = []
    for name, abbreviation in (("AWAY", "AAA"), ("HOME", "BBB")):
        sides.append({
            "side": name,
            "team": {"uuid": f"{name.lower()}-uuid", "abbreviation": abbreviation, "name": abbreviation},
            "starter": {"mlbamId": f"{name}-starter", "availableAsOf": (CAPTURE - timedelta(hours=1)).isoformat()},
            "lineupAuthority": {"status": "PROJECTED_PRIOR_COMPLETE_LINEUP", "availableAsOf": (CAPTURE - timedelta(hours=2)).isoformat()},
            "lineup": [{"batting_order": value, "mlbam": f"{name}-{value}"} for value in range(1, 10)],
        })
    body = {
        "schemaVersion": "AISP_MLB_READ_ONLY_PREGAME_SNAPSHOT_V2",
        "capturedAt": CAPTURE.isoformat(),
        "game": {"game_id": game_id, "starts_at": START.isoformat(), "status": "SCHEDULED"},
        "sides": sides,
        "outcomesRead": False,
        "marketDataRead": False,
        "providerCalls": 0,
        "aispRowsModified": 0,
    }
    return {**body, "contentSha256": daily.sha_json(body)}


class FakeSource:
    def __init__(self, rows):
        self.rows = rows

    def capture_slate(self, **_kwargs):
        return CAPTURE, deepcopy(self.rows), 0


class FakeEngine:
    load_seconds = 0.125
    model_load_count = 1
    fit_count = 0

    def __init__(self, fail: dict[str, tuple[str, str]] | None = None, simulations: int = 5_000):
        self.calls = 0
        self.fail = fail or {}
        self.simulations = simulations

    def forecast(self, evidence):
        self.calls += 1
        game_id = evidence["game"]["game_id"]
        if game_id in self.fail:
            category, reason = self.fail[game_id]
            raise daily.DailySlateError(category, reason)
        forecast = {
            "gameId": game_id,
            "capturedAt": evidence["capturedAt"],
            "scheduledStart": evidence["game"]["starts_at"],
            "simulation": {"count": self.simulations, "illegalStateCount": 0,
                           "nonterminationCount": 0, "deterministicReplay": True},
            "timing": {"constructionSeconds": 0.01, "simulationSeconds": 0.02},
            **daily.RESEARCH_FLAGS,
        }
        return {
            "forecast": forecast,
            "evidence": evidence,
            "executionInputs": {"gameId": game_id},
            "representativePath": {"gameId": game_id, "events": [{"pa": 1}]},
        }


def config(tmp_path: Path, **changes) -> daily.PublishConfig:
    values = {"slate_date": date(2026, 9, 8), "output_root": tmp_path}
    values.update(changes)
    return daily.PublishConfig(**values)


def read_handoff(tmp_path: Path, receipt: dict) -> dict:
    return json.loads((tmp_path / receipt["handoffPath"]).read_text(encoding="utf-8"))


def test_valid_one_game_publication(tmp_path):
    result = daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot()]), engine=FakeEngine())
    assert result["forecastsCompleted"] == 1
    row = result["games"][0]
    assert row["status"] == "PUBLISHED"
    assert (tmp_path / row["artifactPath"] / "forecast.json").exists()


def test_multi_game_slate(tmp_path):
    engine = FakeEngine()
    result = daily.publish_daily_slate(config(tmp_path, workers=2), FakeSource([snapshot("g1"), snapshot("g2")]), engine=engine)
    assert result["gamesDiscovered"] == result["gamesEligible"] == result["forecastsCompleted"] == 2
    assert engine.calls == 2


def test_partial_failure_isolation(tmp_path):
    engine = FakeEngine({"g2": ("SIMULATION_FAILURE", "synthetic isolated failure")})
    result = daily.publish_daily_slate(config(tmp_path, workers=2), FakeSource([snapshot("g1"), snapshot("g2")]), engine=engine)
    assert result["forecastsCompleted"] == 1
    assert result["gamesFailed"] == 1
    assert result["games"][1]["category"] == "SIMULATION_FAILURE"


def test_missing_starter_is_explicit_skip(tmp_path):
    value = snapshot()
    value["sides"][0]["starter"]["mlbamId"] = None
    result = daily.publish_daily_slate(config(tmp_path), FakeSource([value]), engine=FakeEngine())
    assert result["gamesSkipped"] == 1
    assert result["games"][0]["category"] == "MISSING_REQUIRED_EVIDENCE"


def test_missing_lineup_is_explicit_skip(tmp_path):
    value = snapshot()
    value["sides"][1]["lineup"] = []
    result = daily.publish_daily_slate(config(tmp_path), FakeSource([value]), engine=FakeEngine())
    assert result["gamesSkipped"] == 1
    assert "lineup" in result["games"][0]["reason"]


def test_invalid_participant_mapping_is_explicit_skip(tmp_path):
    engine = FakeEngine({"game-1": ("INVALID_PARTICIPANT_MAPPING", "unresolved crosswalk")})
    result = daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot()]), engine=engine)
    assert result["gamesSkipped"] == 1
    assert result["games"][0]["category"] == "INVALID_PARTICIPANT_MAPPING"


def test_game_at_or_after_start_is_never_forecast(tmp_path):
    value = snapshot()
    value["game"]["starts_at"] = value["capturedAt"]
    engine = FakeEngine()
    result = daily.publish_daily_slate(config(tmp_path), FakeSource([value]), engine=engine)
    assert result["games"][0]["category"] == "GAME_ALREADY_STARTED"
    assert engine.calls == 0


def test_pregame_evidence_timestamps_are_enforced(tmp_path):
    value = snapshot()
    value["sides"][0]["lineupAuthority"]["availableAsOf"] = (CAPTURE + timedelta(seconds=1)).isoformat()
    result = daily.publish_daily_slate(config(tmp_path), FakeSource([value]), engine=FakeEngine())
    assert result["gamesSkipped"] == 1
    assert "cutoff" in result["games"][0]["reason"]


def test_exact_rerun_is_idempotent(tmp_path):
    engine = FakeEngine()
    first = daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot()]), engine=engine)
    second = daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot()]), engine=engine)
    assert first["games"][0]["objectSha256"] == second["games"][0]["objectSha256"]
    assert second["duplicatesReused"] == 1
    assert second["games"][0]["status"] == "DUPLICATE_ALREADY_PUBLISHED"
    assert engine.calls == 1


def test_existing_artifact_checksum_is_verified(tmp_path):
    engine = FakeEngine()
    first = daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot()]), engine=engine)
    (tmp_path / first["games"][0]["artifactPath"] / "forecast.json").write_text("tampered", encoding="utf-8")
    second = daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot()]), engine=engine)
    assert second["gamesFailed"] == 1
    assert second["games"][0]["category"] == "PERSISTENCE_PUBLICATION_FAILURE"


def test_no_refit_and_one_model_load_are_recorded(tmp_path):
    result = daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot("g1"), snapshot("g2")]), engine=FakeEngine())
    assert result["executionAccounting"]["modelLoads"] == 1
    assert result["executionAccounting"]["modelFits"] == 0


def test_exactly_5000_simulations_are_enforced(tmp_path):
    result = daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot()]), engine=FakeEngine(simulations=4_999))
    assert result["gamesFailed"] == 1
    assert result["games"][0]["category"] == "SIMULATION_FAILURE"
    assert result["executionAccounting"]["simulationsPerPublishedGame"] == 5_000


def test_gen1_and_aisp_non_mutation_are_explicit(tmp_path):
    result = daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot()]), engine=FakeEngine())
    assert result["gen1RowsModified"] == result["aispRowsModified"] == result["providerCalls"] == 0
    assert result["executionAllowedInAISP"] is False
    assert result["wageringAuthority"] is False


def test_handoff_is_narrow_verifiable_and_research_only(tmp_path):
    result = daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot()]), engine=FakeEngine())
    handoff = read_handoff(tmp_path, result)
    body = {key: value for key, value in handoff.items() if key not in {"handoffId", "handoffSha256"}}
    assert daily.sha_json(body) == handoff["handoffSha256"] == result["handoffSha256"]
    assert handoff["schemaVersion"] == daily.HANDOFF_SCHEMA
    assert handoff["forecasts"][0]["gameId"] == "game-1"
    assert handoff["researchShadowOnly"] is True and handoff["executionAllowedInAISP"] is False


def test_recovery_handoff_aggregates_prior_slate_objects(tmp_path):
    daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot("g1")]), engine=FakeEngine())
    recovery = daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot("g2")]), engine=FakeEngine())
    assert recovery["handoffForecasts"] == 2
    assert [row["gameId"] for row in read_handoff(tmp_path, recovery)["forecasts"]] == ["g1", "g2"]


def test_handoff_only_rebuild_does_not_execute_model(tmp_path):
    daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot("g1")]), engine=FakeEngine())
    rebuilt = daily.rebuild_slate_handoff(tmp_path, date(2026, 9, 8))
    assert rebuilt["mode"] == "HANDOFF_REBUILD_NO_MODEL_EXECUTION"
    assert rebuilt["handoffForecasts"] == 1
    assert rebuilt["executionAccounting"]["modelLoads"] == rebuilt["executionAccounting"]["modelFits"] == 0


def test_three_view_pointer_is_bound_into_successor_handoff(tmp_path, monkeypatch):
    published = daily.publish_daily_slate(
        config(tmp_path), FakeSource([snapshot("g1")]), engine=FakeEngine()
    )
    object_sha = published["games"][0]["objectSha256"]
    references = {}
    for key, family, digit in (
        ("playGeometry", "play-geometry", "a"),
        ("populationGeometry", "population-geometry", "b"),
    ):
        digest = digit * 64
        references[key] = {
            "supplementSha256": digest,
            "relativePath": f"{family}/sha256/{digest}",
            "manifestFile": "manifest.json",
        }
    from server.sports_current_statcast import mlb_v18_daily_views as views
    monkeypatch.setattr(
        views,
        "view_references",
        lambda output_root, supplied_sha: references if supplied_sha == object_sha else None,
    )

    rebuilt = daily.rebuild_slate_handoff(tmp_path, date(2026, 9, 8))
    handoff = read_handoff(tmp_path, rebuilt)
    assert handoff["schemaVersion"] == daily.HANDOFF_SCHEMA_V2
    assert handoff["forecasts"][0]["playGeometry"] == references["playGeometry"]
    assert handoff["forecasts"][0]["populationGeometry"] == references["populationGeometry"]


def test_status_reloads_receipt_handoff_and_all_game_objects(tmp_path):
    daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot("g1"), snapshot("g2")]), engine=FakeEngine())
    status = daily.read_status(tmp_path, date(2026, 9, 8))
    assert status["verification"] == "PASS"
    assert status["verifiedForecasts"] == 2


def test_dry_run_has_no_model_execution_or_output(tmp_path):
    result = daily.publish_daily_slate(config(tmp_path, dry_run=True), FakeSource([snapshot()]))
    assert result["gamesEligible"] == 1 and result["forecastsCompleted"] == 0
    assert list(tmp_path.iterdir()) == []


def test_bullpen_rule_uses_latest_nonstarter_rows_and_last_eight():
    rows = []
    for pitcher in range(10):
        rows.append({"canonicalPaId": f"pa-{pitcher}-a", "pitcherCanonicalPlayerId": f"p{pitcher}", "game_date": "2026-07-20", "feature": pitcher})
        rows.append({"canonicalPaId": f"pa-{pitcher}-b", "pitcherCanonicalPlayerId": f"p{pitcher}", "game_date": "2026-08-01", "feature": pitcher + 100})
    frame = pd.DataFrame(rows)
    selected = {row["canonicalPaId"] for row in rows}
    result = daily.select_bullpen_rows(frame, ["feature"], selected, "p9")
    assert [row["feature"] for row in result] == list(range(101, 109))


def test_object_manifest_binds_every_artifact_checksum(tmp_path):
    result = daily.publish_daily_slate(config(tmp_path), FakeSource([snapshot()]), engine=FakeEngine())
    object_dir = tmp_path / result["games"][0]["artifactPath"]
    manifest = json.loads((object_dir / "manifest.json").read_text(encoding="utf-8"))
    for record in manifest["artifacts"]:
        raw = (object_dir / record["relativePath"]).read_bytes()
        assert len(raw) == record["bytes"]
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
