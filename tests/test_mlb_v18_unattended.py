"""Synthetic scheduler mechanics: no network, database, model, or source reads."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from server.sports_current_statcast import mlb_v18_unattended as unattended


NOW = datetime(2099, 4, 1, 16, tzinfo=timezone.utc)


class _Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def _game(game_id, *, minutes=120, day="2099-04-01", **extra):
    return {"gameId": game_id, "gameDate": day, "scheduledStartUtc": (NOW+timedelta(minutes=minutes)).isoformat(),
            "status": "Scheduled", "canonicalIdentityResolved": True, **extra}


def test_checkpoint_enforces_cutoff_restart_catchup_and_bounded_cooldown():
    for minutes in (-1, 0):
        decision = unattended.checkpoint(_game("CLOSED", minutes=minutes), {}, NOW)
        assert decision["closed"] and not decision["due"]
    final = unattended.checkpoint(_game("FINAL_CHECK", minutes=5), {}, NOW)
    assert final["reason"] == "FINAL_PUBLICATION_SAFETY_CUTOFF_T_MINUS_5"
    assert not final["due"]
    assert unattended.checkpoint(_game("FUTURE", minutes=1500), {}, NOW)["due"] is False
    game = _game("UPCOMING", minutes=45)
    assert unattended.checkpoint(game, {}, NOW)["due"] is True
    # An OS restart cannot release a persisted failure cooldown.
    previous = {"checkedAt": (NOW-timedelta(hours=2)).isoformat(), "retryAfterUtc": (NOW+timedelta(minutes=10)).isoformat()}
    assert unattended.checkpoint(game, previous, NOW)["reason"] == "BOUNDED_FAILURE_COOLDOWN"
    assert unattended.checkpoint(game, previous, NOW+timedelta(minutes=10))["due"] is True
    for minutes, interval in ((800, 360), (240, 60), (120, 30), (75, 15), (60, 5), (20, 5)):
        game = _game("CADENCE", minutes=minutes)
        previous = {"checkedAt": (NOW-timedelta(minutes=interval-1)).isoformat()}
        assert unattended.checkpoint(game, previous, NOW)["due"] is False
        previous["checkedAt"] = (NOW-timedelta(minutes=interval)).isoformat()
        assert unattended.checkpoint(game, previous, NOW)["due"] is True


def test_checkpoint_distinguishes_consumer_decision_and_research_publication_clocks():
    game = _game("CLOCKS", minutes=40)
    decision = unattended.checkpoint(game, {}, NOW)
    assert decision["consumerFinalPregameWindowOpensUtc"] == (NOW+timedelta(minutes=10)).isoformat()
    assert decision["consumerDecisionCutoffUtc"] == (NOW+timedelta(minutes=25)).isoformat()
    assert decision["consumerReadyTargetUtc"] == (NOW-timedelta(minutes=5)).isoformat()
    assert decision["producerResearchPublicationCutoffUtc"] == (NOW+timedelta(minutes=35)).isoformat()
    assert decision["consumerDecisionEligible"] is True
    assert decision["intervalMinutes"] == 5

    late_for_consumer = unattended.checkpoint(_game("LATE", minutes=10), {}, NOW)
    assert late_for_consumer["due"] is True
    assert late_for_consumer["consumerDecisionEligible"] is False
    assert unattended.retry_delay_minutes(game, 2, NOW) == 5
    assert unattended.retry_delay_minutes(_game("PAST", minutes=10), 2, NOW) == 60


def test_legacy_collector_binding_recovers_original_creation_clock_for_handoff(monkeypatch, tmp_path):
    fixture = Path(__file__).parent / "fixtures/mlb_v18_forecast_clock"
    object_id = "683a0c14751466ab34f703a3f60f8fb3ddcf9e00160a03d5eaa4402d25a2426e"
    object_dir = tmp_path / "objects/sha256" / object_id
    object_dir.mkdir(parents=True)
    for name in ("manifest.json", "forecast.json"):
        (object_dir / name).write_bytes((fixture / name).read_bytes())
    legacy_binding = {
        "gameId": "8cad9313-5d8d-4300-ac6d-66a74a6d3459",
        "objectSha256": object_id,
        "relativePath": f"objects/sha256/{object_id}",
        "forecastFile": "forecast.json",
        "manifestFile": "manifest.json",
        "capturedAt": "2026-09-14 19:30:31.978131+00:00",
        "scheduledStart": "2026-09-14 18:40:00-04:00",
    }
    assert "forecastCreatedAt" not in legacy_binding
    monkeypatch.setattr(unattended, "PUBLICATIONS", tmp_path)
    monkeypatch.setattr(unattended, "collect_slate_forecasts", lambda *_: [legacy_binding])
    monkeypatch.setattr(unattended, "current_handoff", lambda *_args, **_kwargs: {"status": "test"})
    monkeypatch.setattr(unattended, "current_import_receipt", lambda *_args, **_kwargs: {"status": "test"})
    report = {"discovery": {"slateDates": ["2026-09-14"]}, "games": [{
        "gameId": legacy_binding["gameId"], "gameDate": "2026-09-14",
        "scheduledStartUtc": "2026-09-14T22:40:00+00:00", "status": "UNCHANGED_NUMERICAL_FORECAST_REUSED",
    }]}
    unattended.assemble_handoffs(report)
    eligibility = report["games"][0]["consumerDecisionEligibility"]
    assert eligibility["forecastCreatedAt"] == "2026-09-14T19:38:03.000665+00:00"
    assert eligibility["creationClockResolution"]["source"] == "BOUND_IMMUTABLE_FORECAST_ARTIFACT"


def test_discovery_uses_eastern_today_and_next_available_slate_without_losing_local_games(tmp_path, monkeypatch):
    from server.sports_current_statcast import mlb_v18_current_sources as sources
    now = datetime(2099, 4, 2, 1, tzinfo=timezone.utc)  # April 1 in New York.
    calls = []
    monkeypatch.setattr(sources, "acquire_schedule_identity_projection", lambda **kwargs: calls.append(kwargs) or {"synthetic": True})
    rows = [{"mlbamGamePk": 1, "gameDate": "2099-04-01", "scheduledStartUtc": "2099-04-02T02:00:00Z", "status": "Scheduled"},
            {"mlbamGamePk": 2, "gameDate": "2099-04-03", "scheduledStartUtc": "2099-04-03T23:00:00Z", "status": "Scheduled"},
            {"mlbamGamePk": 3, "gameDate": "2099-04-04", "scheduledStartUtc": "2099-04-04T23:00:00Z", "status": "Scheduled"}]
    monkeypatch.setattr(sources, "schedule_identity_rows", lambda receipt: rows)
    mapping = {"1": {"game_id": "CANONICAL_ONE", "starts_at": datetime(2099, 4, 2, 2, tzinfo=timezone.utc), "status": "SCHEDULED"},
               "4": {"game_id": "LOCAL_OMITTED", "starts_at": datetime(2099, 4, 2, 3, tzinfo=timezone.utc), "status": "SCHEDULED"}}
    monkeypatch.setattr(unattended, "local_game_map", lambda start, through: mapping)
    result = unattended.discover(now, allow_free_network=True, root=tmp_path)
    assert result["slateDates"] == ["2099-04-01", "2099-04-03"]
    by_id = {row["gameId"]: row for row in result["games"]}
    assert set(by_id) == {"CANONICAL_ONE", "UNMAPPED_MLBAM:2", "LOCAL_OMITTED"}
    assert by_id["LOCAL_OMITTED"]["providerScheduleMissing"] is True
    assert by_id["UNMAPPED_MLBAM:2"]["canonicalIdentityResolved"] is False
    assert calls[0]["start"] == "2099-04-01"
    assert len(calls) == result["providerCalls"] == 1
    assert result["costUsd"] == 0


def test_tick_accounts_for_every_game_preserves_published_objects_and_skips_unchanged_work(tmp_path, monkeypatch):
    from scripts import run_mlb_v18_current_state as runner
    monkeypatch.setattr(unattended, "datetime", _Clock)
    monkeypatch.setattr(unattended, "PUBLICATIONS", tmp_path / "publications")
    monkeypatch.setenv("MLB_V18_DEPLOYED_COMMIT", "f" * 40)
    monkeypatch.setenv("MLB_V18_DEPLOYMENT_MANIFEST_SHA256", "e" * 64)
    games = [_game("NEW_PUBLISHED"), _game("MISSING_LINEUP"), _game("FAILED_VALIDATION"),
             _game("PREVIOUS_PUBLISHED", minutes=-60),
             _game("UNMAPPED", canonicalIdentityResolved=False),
             _game("PROVIDER_OMITTED", providerScheduleMissing=True),
             _game("NEXT_SLATE", minutes=1800, day="2099-04-02")]
    discovery = {"games": games, "slateDates": ["2099-04-01", "2099-04-02"], "providerCalls": 1}
    monkeypatch.setattr(unattended, "discover", lambda *args, **kwargs: deepcopy(discovery))
    monkeypatch.setattr(unattended, "preflight_participants", lambda due, *args, **kwargs: due)
    histories, runs, handoffs = [], [], []
    monkeypatch.setattr(unattended, "refresh_history", lambda *args, **kwargs: histories.append(True) or ("SYNTHETIC_ATTEMPT", {"providerCalls": 0}))
    def run(args):
        runs.append(args)
        return {"games": [{"gameId": "NEW_PUBLISHED", "status": "PUBLISHED", "objectSha256": "a"*64},
            {"gameId": "MISSING_LINEUP", "status": "SKIPPED", "blockers": [{"reason": "NO_CONFIRMED_LINEUP"}]},
            {"gameId": "FAILED_VALIDATION", "status": "FAILED", "reason": "SYNTHETIC_INVALID_SOURCE_CLOCK"}]}
    monkeypatch.setattr(runner, "run", run)
    forecasts = [{"gameId": "NEW_PUBLISHED", "objectSha256": "a"*64,
                  "forecastCreatedAt": (NOW-timedelta(minutes=10)).isoformat()},
                 {"gameId": "PREVIOUS_PUBLISHED", "objectSha256": "b"*64,
                  "forecastCreatedAt": (NOW-timedelta(minutes=10)).isoformat()}]
    monkeypatch.setattr(unattended, "collect_slate_forecasts", lambda root, day: forecasts if str(day) == "2099-04-01" else [])
    def handoff(root, day, forecasts, *, games):
        handoffs.append(deepcopy(games))
        return {"syntheticHandoff": True}
    monkeypatch.setattr(unattended, "current_handoff", handoff)
    monkeypatch.setattr(unattended, "current_import_receipt", lambda *args: {"syntheticReceipt": True})
    state_root, output_root = tmp_path / "state", tmp_path / "ticks"
    first = unattended.execute_tick(now=NOW, state_root=state_root, output_root=output_root)
    assert first["status"] == "BOUNDED_TICK_COMPLETED"
    assert first["deploymentIdentity"] == {"commit": "f" * 40, "manifestSha256": "e" * 64}
    assert first["timingContract"] == {
        "producerChecksBeginMinutesBeforeStart": 60,
        "producerDeliveryTargetMinutesBeforeStart": 45,
        "consumerFinalPregameWindowOpensMinutesBeforeStart": 30,
        "consumerDecisionCutoffMinutesBeforeStart": 15,
        "producerResearchPublicationCutoffMinutesBeforeStart": 5,
        "consumerImportCadenceMinutes": 5,
        "consumerEvaluationCadenceMinutes": 5,
        "dispatcherEarlyToleranceSeconds": 2,
        "deadlineTypesRemainIndependent": True,
    }
    by_id = {row["gameId"]: row for row in first["games"]}
    assert len(by_id) == len(games) == 7
    assert by_id["PREVIOUS_PUBLISHED"]["status"] == "PUBLISHED_BEFORE_FIRST_PITCH"
    assert by_id["NEW_PUBLISHED"]["consumerDecisionEligibility"]["eligible"] is True
    assert by_id["PREVIOUS_PUBLISHED"]["consumerDecisionEligibility"]["eligible"] is False
    assert by_id["MISSING_LINEUP"]["reason"] == "NO_CONFIRMED_LINEUP"
    assert by_id["UNMAPPED"]["reason"] == "CANONICAL_EVENT_NOT_REGISTERED_IN_LOCAL_IDENTITY_SOURCE"
    assert by_id["PROVIDER_OMITTED"]["reason"] == "PROVIDER_SCHEDULE_EVENT_NOT_CONFIRMED"
    assert by_id["NEXT_SLATE"]["reason"] == "FUTURE_GAME_BEYOND_24H_CAPTURE_WINDOW"
    assert set(runs[0].game_ids) == {"NEW_PUBLISHED", "MISSING_LINEUP", "FAILED_VALIDATION"}
    assert first["slates"][0]["publishedGames"] == 2
    assert len(handoffs[0]) == 6
    saved = json.loads((state_root / "state.json").read_text())
    assert saved["games"]["FAILED_VALIDATION"]["consecutiveFailures"] == 1
    assert saved["games"]["FAILED_VALIDATION"]["retryAfterUtc"] == (NOW+timedelta(minutes=5)).isoformat()
    second = unattended.execute_tick(now=NOW+timedelta(minutes=5), state_root=state_root, output_root=output_root)
    assert second["status"] == "BOUNDED_TICK_COMPLETED"
    assert len(histories) == len(runs) == 2
    assert next(row for row in second["games"] if row["gameId"] == "FAILED_VALIDATION")["reason"] == "SYNTHETIC_INVALID_SOURCE_CLOCK"
    assert first["modelFits"] == first["aispWrites"] == first["sealedEvaluationPayloadReads"] == first["costUsd"] == 0


def test_dispatcher_accepts_subsecond_early_owner_tick_and_labels_late_research_forecast(tmp_path, monkeypatch):
    monkeypatch.setattr(unattended, "datetime", _Clock)
    monkeypatch.setattr(unattended, "PUBLICATIONS", tmp_path / "publications")
    state_root, output_root = tmp_path / "state", tmp_path / "ticks"
    state_root.mkdir()
    (state_root / "state.json").write_text(json.dumps({
        "games": {},
        "nextTickUtc": (NOW + timedelta(milliseconds=650)).isoformat(),
    }))
    game = _game("LATE_RESEARCH", minutes=10)
    monkeypatch.setattr(unattended, "discover", lambda *args, **kwargs: {
        "games": [game], "slateDates": ["2099-04-01"], "providerCalls": 0,
    })
    monkeypatch.setattr(unattended, "preflight_participants", lambda due, *args, **kwargs: {})
    monkeypatch.setattr(unattended, "collect_slate_forecasts", lambda *args: [{
        "gameId": "LATE_RESEARCH", "objectSha256": "c"*64,
        "forecastCreatedAt": NOW.isoformat(),
    }])
    handoffs = []
    monkeypatch.setattr(unattended, "current_handoff", lambda root, day, forecasts, *, games: handoffs.append(games) or {})
    monkeypatch.setattr(unattended, "current_import_receipt", lambda *args: {})

    report = unattended.execute_tick(now=NOW, state_root=state_root, output_root=output_root)

    assert report["status"] == "BOUNDED_TICK_COMPLETED"
    delivery = handoffs[0][0]["consumerDecisionEligibility"]
    assert delivery["eligible"] is False
    assert delivery["reason"] == "FORECAST_CLOCK_AFTER_CONSUMER_DEADLINE_RESEARCH_ONLY"


def test_discovery_failure_retries_on_owner_cadence_when_games_are_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(unattended, "datetime", _Clock)
    monkeypatch.setattr(
        unattended, "discover",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic discovery outage")),
    )
    report = unattended.execute_tick(
        now=NOW, state_root=tmp_path / "state", output_root=tmp_path / "ticks",
    )
    assert report["status"] == "FAILED_BOUNDED_TICK"
    saved = json.loads((tmp_path / "state" / "state.json").read_text())
    assert saved["nextTickUtc"] == (NOW + timedelta(minutes=5)).isoformat()


def test_participant_readiness_uses_original_observation_age_and_requires_ordered_lineups():
    observed = (NOW-timedelta(minutes=10)).isoformat()
    captured = NOW.isoformat()
    snapshot = {"capturedAt": captured, "game": {"starts_at": (NOW+timedelta(hours=2)).isoformat()},
                "sides": [], "currentRoster": []}
    for side in ("AWAY", "HOME"):
        clocks = {"observedAt": observed, "availableAsOf": observed,
                  "ingestedAt": (NOW-timedelta(minutes=9)).isoformat()}
        snapshot["sides"].append({"side": side, "team": {"uuid": side},
            "starter": {**clocks, "mlbamId": side+"-pitcher"},
            "lineupAuthority": {**clocks, "status": "CONFIRMED"},
            "lineup": [{"batting_order": index, "mlbam": f"{side}-{index}"} for index in range(1, 10)]})
        snapshot["currentRoster"].append({"team_id": side, "position": "RP", "active_roster": True,
            "observed_at": (NOW-timedelta(hours=24)).isoformat()})
    assert unattended.participant_readiness(snapshot) == []
    stale = deepcopy(snapshot)
    # A fresh database read or ingestion cannot refresh the source's old observation.
    stale["sides"][0]["starter"].update(observedAt=(NOW-timedelta(hours=3)).isoformat(),
                                       availableAsOf=captured, ingestedAt=captured)
    assert unattended.participant_readiness(stale) == ["AWAY_STARTER_SOURCE_OBSERVATION_STALE"]
    missing = deepcopy(snapshot)
    missing["sides"][1]["lineupAuthority"]["status"] = "PROJECTED"
    missing["sides"][1]["lineup"] = []
    assert unattended.participant_readiness(missing) == ["HOME_CONFIRMED_ORDERED_NINE_PLAYER_LINEUP_UNAVAILABLE"]


def test_roster_readiness_projects_expiry_and_reports_source_failure_without_restamping():
    evidence = NOW - timedelta(hours=29, minutes=30)
    snapshot = {"capturedAt": NOW.isoformat(),
                "game": {"starts_at": (NOW+timedelta(minutes=60)).isoformat()},
                "sides": [{"side": "HOME", "team": {"uuid": "HOME", "abbreviation": "CHC",
                                                       "name": "Chicago Cubs"}}],
                "currentRoster": [{"team_id": "HOME", "position": "RP", "active_roster": True,
                                   "observed_at": evidence.isoformat()}],
                "rosterRefreshOwner": {"owner": "AISP_ASP_DAILY_PIPELINE", "provider": "MLB_STATS_API",
                    "latestIngestionRuns": [{"id": "failed-run", "started_at": (NOW-timedelta(hours=6)).isoformat(),
                        "completed_at": (NOW-timedelta(hours=5, minutes=59)).isoformat(),
                        "warnings": ["Chicago Cubs: MLB request failed: ConnectTimeout"]}]}}
    status = unattended.roster_readiness(snapshot)[0]
    assert status["evidenceTimestamp"] == evidence.isoformat()
    assert status["currentAgeHours"] == 29.5
    assert status["projectedAgeAtConsumerCutoffHours"] == 30.25
    assert status["states"][:2] == ["ROSTER_SOURCE_FAILED", "ROSTER_WILL_EXPIRE_BEFORE_DECISION"]
    assert status["lastRefreshResult"]["status"] == "ROSTER_SOURCE_FAILED"
    assert "29.5 hours ago" in status["userMessage"]

    snapshot["capturedAt"] = (NOW+timedelta(hours=2)).isoformat()
    stale = unattended.roster_readiness(snapshot)[0]
    assert "ROSTER_STALE_BLOCKING" in stale["states"]
    assert stale["evidenceTimestamp"] == evidence.isoformat()


def test_latest_roster_batch_excludes_old_active_rows_without_inventing_inactive_status():
    from scripts.inventory_mlb_current_slate import latest_roster_batches
    yesterday, today = NOW-timedelta(days=1), NOW-timedelta(hours=1)
    def row(player, observed, team="HOME"):
        return {"mlbam_id": player, "team_id": team, "source": "MLB_STATS_API", "source_mode": "LIVE",
                "observed_at": observed, "active_roster": True, "availability_status": "ACTIVE", "position": "RP"}
    observations = [row("OLD_REMOVED", yesterday), row("CURRENT_ONE", today), row("CURRENT_TWO", today),
                    row("AWAY_CURRENT", yesterday, "AWAY")]
    original = deepcopy(observations)
    selected, superseded = latest_roster_batches(observations)
    assert {item["mlbam_id"] for item in selected} == {"CURRENT_ONE", "CURRENT_TWO", "AWAY_CURRENT"}
    assert superseded == [observations[0]]
    assert superseded[0]["active_roster"] is True
    assert superseded[0]["availability_status"] == "ACTIVE"
    assert observations == original
