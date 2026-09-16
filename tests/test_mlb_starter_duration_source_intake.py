"""Single focused no-network regression for protected source and budget guards."""
import json
import pytest

from scripts import acquire_mlb_starter_duration_history as intake


def test_projection_and_shared_interrupted_request_budget_fail_closed(tmp_path, monkeypatch):
    from server.sports_current_statcast import mlb_starter_duration_quarantine as quarantine
    # Metadata's outer 'stats' grouping is not a grant to nested numerical 'stat'.
    safe = {"stats": [{"splits": [{"date": "2026-08-20", "game": {"gamePk": 123}}]}]}
    intake._check_projection(safe, intake.LOG_FIELDS)
    with pytest.raises(ValueError, match="SERVER_METADATA_PROJECTION_NOT_HONORED"):
        intake._check_projection({"stats": [{"splits": [{"stat": {"battersFaced": 22}}]}]}, intake.LOG_FIELDS)
    assert intake._protected("2026-08-14T00:00:00Z")
    assert intake._protected("2026-08-27")
    assert not intake._protected("2026-08-28")
    monkeypatch.setattr(intake, "INTAKE", tmp_path)
    requests = tmp_path / "requests"
    requests.mkdir()
    start = {"reservedBytes": 8192}
    (requests / "0001.started.json").write_text(json.dumps(start), encoding="utf-8")
    pending = intake._accounting()
    assert pending["requestAttempts"] == 1
    assert pending["budgetAccountedBytes"] == 8192
    assert pending["incompleteAttemptsReservedAtMaximum"] == 1
    (requests / "0001.completed.json").write_text(json.dumps({"completedAt": "2026-09-11T00:00:00Z",
                                                            "downloadedBytes": 400}), encoding="utf-8")
    finished = intake._accounting()
    assert finished["requestAttempts"] == 1
    assert finished["budgetAccountedBytes"] == finished["downloadedOriginalBytes"] == 400
    assert finished["incompleteAttemptsReservedAtMaximum"] == 0
    # Preserve an original pre-fix manifest; cache-run telemetry must not create
    # new source identity or refresh the original evidence availability clock.
    first = {"schemaVersion": intake.SCHEMA, "through": "2026-09-10", "games": [],
             "startedAt": "2026-09-11T18:00:00Z", "completedAt": "2026-09-11T18:01:00Z",
             "cachedSourcesReused": 0, "accounting": {"requestAttempts": 32},
             "safe2025ProjectionProbe": {"cached": False, "accounting": {"requestAttempts": 1},
                                          "receipt": {"raw": {"sha256": "original-source"}}}}
    original_ref = intake._store(intake._bytes(first), ".intake-manifest.json")
    later = json.loads(json.dumps(first))
    later.update(startedAt="2026-09-11T19:00:00Z", completedAt="2026-09-11T19:01:00Z",
                 cachedSourcesReused=31, accounting={"requestAttempts": 57})
    later["safe2025ProjectionProbe"].update(cached=True, accounting={"requestAttempts": 57})
    ref, manifest, reused, _ = intake._stable_intake_manifest(later)
    assert reused and ref == original_ref
    assert manifest["completedAt"] == first["completedAt"]
    repeated_ref, _, repeated, _ = intake._stable_intake_manifest(later)
    assert repeated and repeated_ref == original_ref
    # A protected request cannot inspect even a cache before exact tuple authority.
    def denied(*args):
        raise ValueError("PROTECTED_GAME_OUTSIDE_THREE_GAME_EXCEPTION")
    monkeypatch.setattr(quarantine, "assert_prospective_source_allowed", denied)
    with pytest.raises(ValueError, match="PROTECTED_GAME_OUTSIDE_THREE_GAME_EXCEPTION"):
        intake._request("https://statsapi.mlb.com/api/v1.1/game/999/feed/live", family="AUTHORIZED_PROSPECTIVE_STARTER_HISTORY_ONLY",
            cache_scope="denied", protected_scope={"pitcherMlbamId": "664285", "gamePk": 999, "gameDate": "2026-08-20"})
    fields = set(intake.starter_feed_fields("664285").split(","))
    assert {"ID664285", "isTopInning", "originBase", "runner", "gamesStarted", "battersFaced", "startTime", "endTime"} <= fields
    assert not {"pitchData", "hitData", "launchSpeed", "launchAngle", "ID690279"}.intersection(fields)
    native = {"gameData": {"players": {"ID123": {"seasonStats": {"notAllowed": 999}}}},
              "liveData": {"boxscore": {"teams": {"away": {"players": {
                  "ID664285": {"stats": {"pitching": {"battersFaced": 22}}, "seasonStats": {"pitching": {"battersFaced": 999}}},
                  "ID123": {"stats": {"pitching": {"battersFaced": 999}}}}}}}}}
    projected, projection = intake._project_native_starter_feed(native, "664285")
    assert projected["gameData"]["players"] == {}
    assert projected["liveData"]["boxscore"]["teams"]["away"]["players"] == {
        "ID664285": {"stats": {"pitching": {"battersFaced": 22}}}}
    assert projection["unknownFieldsForwarded"] is False
    # Once the narrow authority exists, resume chooses its guarded successor,
    # never recreates the old intentionally partial nonsealed intake.
    (tmp_path / "protected-source-authority.json").write_text("{}", encoding="utf-8")
    sentinel = {"manifestRef": {"sha256": "synthetic-authorized-successor"}}
    monkeypatch.setattr(intake, "acquire_authorized_three_game_supplement", lambda **kwargs: sentinel)
    assert intake.run_bounded_intake(allow_free_network=False) == sentinel
