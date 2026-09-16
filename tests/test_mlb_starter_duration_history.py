"""Focused coverage for the new source adapter, not a model test campaign."""
import copy
import gzip
import json
from pathlib import Path

import pytest

from server.sports_current_statcast.mlb_starter_duration_history import (
    completion_from_observed_clocks, parse_statsapi_start,
)


SAFE_2025 = Path("C:/Users/james/ai-sports-predictor/data/raw/historical/mlb_stats_api/2025/03/2025-03-27_0dcb6179999216b17548307a.json.gz")


def test_retained_real_feed_bf_outs_and_mid_pa_guard():
    if not SAFE_2025.exists():
        pytest.skip("Optional retained nonsealed2025 real-data fixture absent")
    feed = json.loads(gzip.decompress(SAFE_2025.read_bytes()))["payload"]
    metadata = {"gamePk": 778559, "gameDate": "2025-03-27", "completionDate": "2025-03-27",
                "statusFinal": True, "suspendedOrResumed": False, "evidenceSource": "RETAINED_REAL_FEED_FIXTURE"}
    actual = parse_statsapi_start(feed, pitcher_mlbam_id=664285, completion_metadata=metadata)
    assert actual["eligible"] and (actual["totalBf"], actual["totalOuts"], actual["endpoint"]) == (26, 21, "REMOVAL")
    changed = copy.deepcopy(feed)
    substitution = next(e for p in changed["liveData"]["plays"]["allPlays"] for e in p["playEvents"]
                        if e.get("details", {}).get("eventType") == "pitching_substitution" and e.get("player", {}).get("id") == 650556)
    substitution["count"]["balls"] = 1
    assert parse_statsapi_start(changed, pitcher_mlbam_id=664285, completion_metadata=metadata)["exclusionReason"] == "MID_PA_STARTER_CHANGE"


def test_protected_metadata_rejects_before_any_feed_access():
    class ForbiddenFeed(dict):
        def get(self, *args, **kwargs):
            raise AssertionError("Protected payload touched")
    with pytest.raises(ValueError, match="PROTECTED_GAME_OUTSIDE_THREE_GAME_EXCEPTION"):
        parse_statsapi_start(ForbiddenFeed(), pitcher_mlbam_id=664285,
                            completion_metadata={"gameDate": "2026-08-17", "gamePk": 823344})


def test_clock_inversion_retained_but_cross_date_completion_unproven():
    # Explicitly synthetic timing-only transport fixture. No model fit/claim.
    game = {"gameDate": "2026-05-13", "gamePk": 1, "scheduleMetadata": {
        "gamePk": 1, "officialDate": "2026-05-13", "status": {"abstractGameState": "Final"}}}
    feed = {"gameData": {"datetime": {"officialDate": "2026-05-13", "originalDate": "2026-05-13"},
                         "venue": {"timeZone": {"id": "America/New_York"}}, "status": {"abstractGameState": "Final"}},
            "liveData": {"plays": {"allPlays": [{"about": {"startTime": "2026-05-14T00:53:14Z", "endTime": "2026-05-14T00:53:06Z"}}]}}}
    proof = completion_from_observed_clocks(game, feed)
    assert proof["completionDate"] == "2026-05-13" and proof["invertedWithinPaClockIndices"] == [0]
    feed["liveData"]["plays"]["allPlays"][0]["about"]["endTime"] = "2026-05-15T00:53:06Z"
    assert completion_from_observed_clocks(game, feed)["completionDate"] is None
