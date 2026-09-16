from copy import deepcopy

import pytest

from server.sports_current_statcast.mlb_v19_source_evidence import (
    RIGHTS, descriptor, load_daily_capture, pitcher_workload, roster_membership, store_supplement,
)


def captures():
    return [{"day": f"2026-09-{day:02d}", "complete": True, "appearances": []}
            for day in range(3, 10)]


def test_missing_coverage_is_not_known_zero_and_no_future_or_sealed_history():
    data = captures()
    zero = pitcher_workload("1", data, target_day="2026-09-10")
    assert zero["windows"]["7"]["recordedPitchEvents"] == 0
    assert zero["windows"]["7"]["semanticState"] == "KNOWN_ZERO_RECORDED_PITCH_EXPOSURE"
    assert zero["calendarDaysSinceLatestRecordedPitch"] is None
    data[-1]["complete"] = False
    missing = pitcher_workload("1", data, target_day="2026-09-10")
    assert missing["windows"]["1"]["recordedPitchEvents"] is None
    assert missing["windows"]["1"]["semanticState"] == "SOURCE_GAP"
    for invalid in ("2026-09-10", "2026-08-20"):
        data[-1]["day"] = invalid
        with pytest.raises(ValueError):
            pitcher_workload("1", data, target_day="2026-09-10")


def test_exact_pitch_calendar_windows_and_rest_not_recovery_hours():
    data = captures()
    data[-1]["appearances"] = [{"gamePk": "9", "gameDate": "2026-09-09", "pitcherId": "1", "recordedPitchEvents": 21}]
    data[-3]["appearances"] = [{"gamePk": "7", "gameDate": "2026-09-07", "pitcherId": "1", "recordedPitchEvents": 18}]
    result = pitcher_workload("1", data, target_day="2026-09-10")
    assert result["windows"]["1"]["recordedPitchEvents"] == 21
    assert result["windows"]["3"]["recordedPitchEvents"] == 39
    assert result["windows"]["3"]["pitchBearingAppearances"] == 2
    assert result["calendarDaysSinceLatestRecordedPitch"] == 1
    assert result["actualRecoveryHours"] is None
    assert result["actualAvailability"] is None


def test_source_cutoff_and_seal_fail_before_attempting_payload_open(tmp_path):
    record = {"day": "2026-08-20", "family": "STATCAST"}
    with pytest.raises(ValueError, match="EXCLUDED_BEFORE_PAYLOAD_READ"):
        load_daily_capture({"day": record["day"]}, record, cutoff="2026-09-10T20:00:00Z", source_root=tmp_path)
    record.update(day="2026-09-09", observedAt="2026-09-11T01:00:00Z",
                  availableAsOf="2026-09-11T01:00:00Z", ingestedAt="2026-09-11T01:00:00Z")
    schedule = {**record, "family": "SCHEDULE"}
    with pytest.raises(ValueError, match="before the requested cutoff"):
        load_daily_capture(schedule, record, cutoff="2026-09-10T20:00:00Z", source_root=tmp_path)


def test_latest_selected_pool_preserves_superseded_and_immutable_cache(tmp_path):
    source = {"sourceIdentity": "MLB_STATS_API", "observedAt": "2026-09-10T10:00:00Z",
              "availableAsOf": "2026-09-10T10:00:00Z", "ingestedAt": "2026-09-10T10:00:00Z"}
    stale = {**source, **{k: "2026-09-09T10:00:00Z" for k in ("observedAt", "availableAsOf", "ingestedAt")}}
    rows = [{"side": "HOME", "mlbamId": "1", "source": source}, {"side": "HOME", "mlbamId": "2", "source": stale}]
    original = deepcopy(rows)
    result = roster_membership(rows, cutoff="2026-09-10T20:00:00Z")
    assert [r["mlbamId"] for r in result["currentSelectedPool"]] == ["1"]
    assert [r["mlbamId"] for r in result["supersededObservations"]] == ["2"]
    assert not result["fullRosterCompletenessEstablished"]
    assert rows == original
    first = store_supplement(result, tmp_path)
    assert first == store_supplement(result, tmp_path)
    changed = store_supplement({**result, "predecessorSha256": first["sha256"]}, tmp_path)
    assert changed["sha256"] != first["sha256"]


def test_pitch_orientation_automatic_exclusion_and_unknown_pitch_category(tmp_path):
    day = "2026-09-09"
    schedule = {"dates": [{"date": day, "games": [{"gamePk": 8, "officialDate": day, "gameType": "R",
        "gameDate": "2026-09-09T23:00:00Z", "status": {"detailedState": "Final"},
        "teams": {"home": {"team": {"id": 10}}, "away": {"team": {"id": 20}}}}]}]}
    schedule_ref = store_supplement(schedule, tmp_path, name="schedule.json")
    csv_path = tmp_path / "synthetic-pitch-fixture.csv"
    csv_path.write_text("game_date,game_pk,at_bat_number,pitch_number,description,pitcher,inning,inning_topbot,home_team,away_team,pitch_type\n"
        + f"{day},8,1,1,called_strike,11,1,Top,H,A,FF\n"
        + f"{day},8,1,2,automatic_ball,11,1,Top,H,A,\n"
        + f"{day},8,2,1,ball,22,1,Bot,H,A,\n", encoding="utf-8")
    base = {"day": day, "rights": RIGHTS, "observedAt": "2026-09-10T10:00:00Z",
        "availableAsOf": "2026-09-10T10:00:00Z", "ingestedAt": "2026-09-10T10:00:00Z", "_receipt": {}}
    result = load_daily_capture({**base, "family": "SCHEDULE", "raw": schedule_ref},
        {**base, "family": "STATCAST", "raw": descriptor(csv_path)},
        cutoff="2026-09-10T20:00:00Z", source_root=tmp_path)
    assert result["complete"]
    assert result["automaticEventsExcluded"] == 1
    assert result["recordedPitchEvents"] == 2
    observed = {r["pitcherId"]: r for r in result["appearances"]}
    assert observed["11"]["teamId"] == "10"
    assert observed["22"]["teamId"] == "20"
    assert observed["22"]["unclassifiedPitchEvents"] == 1
