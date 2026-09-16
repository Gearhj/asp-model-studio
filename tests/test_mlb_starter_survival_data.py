"""Focused semantic checks; synthetic rows are not real-data validation."""
import pandas as pd
import pytest

from server.sports_current_statcast.mlb_starter_survival_data import (
    add_pregame_history, align_raw_fd1, innings_notation_to_outs, parse_event_member, start_risks,
)


def fixture(*, removed=True, mid=False):
    text = "\n".join([
        "id,BOS202304010", "info,date,2023/04/01", "info,gametype,regular",
        "start,pitch001,Starter,1,0,1", "start,awayp001,Away,0,0,1",
        "play,1,0,batt0001,00,X,63", "play,1,0,batt0002,00,X,63",
        "play,1,0,batt0003,00,X,63",
    ] + ([f"play,2,0,batt0004,{'10,B' if mid else '00,'},NP", "sub,relief01,Relief,1,0,1"] if removed else []))
    raw = parse_event_member(text, "fixture.EVA")["BOS202304010"]
    rows = [{"inning": 1, "top_bottom": 0, "batter_id": "retrosheet:player:batt000"+str(i),
             "pitcher_id": "retrosheet:player:pitch001", "event_text": "63", "pa_terminal_token": "OUT",
             "plate_appearance_id": "pa"+str(i), "play_number": i, "outs_before": i-1, "outs_after": i,
             "home_score_after": 0, "visiting_score_after": 0, "base_mask_after": 0, "runs_scored": 0}
            for i in (1, 2, 3)]
    return raw, align_raw_fd1(raw, rows)


def test_boundary_state_orientation_and_baseball_innings():
    raw, rows = fixture()
    risks, start = start_risks(raw, rows, 1, complete=True)
    assert [r["endpoint"] for r in risks] == ["CONTINUE", "CONTINUE", "REMOVAL"]
    assert start["totalBf"] == 3 and start["totalOuts"] == 3
    assert risks[-1]["nextPitchInning"] == 2 and risks[-1]["pitchingTeamScoreMargin"] == 0
    # Later offensive scoring is not an input to this function or boundary.
    assert risks[-1]["inning"] == 1 and risks[-1]["outsInInning"] == 3
    assert innings_notation_to_outs("5.2") == 17
    with pytest.raises(ValueError):
        innings_notation_to_outs("5.3")


def test_game_end_unknown_and_mid_pa_are_not_hooks():
    raw, rows = fixture(removed=False)
    risks, summary = start_risks(raw, rows, 1, complete=True)
    assert risks[-1]["endpoint"] == "GAME_END" and risks[-1]["removalTarget"] is None
    assert summary["eligible"]
    risks, summary = start_risks(raw, rows, 1, complete=False)
    assert not risks and summary["endpoint"] == "UNKNOWN" and "CENSORED_UNKNOWN" in summary["exclusionReason"]
    raw, rows = fixture(mid=True)
    risks, summary = start_risks(raw, rows, 1, complete=True)
    assert not risks and summary["exclusionReason"] == "MID_PA_STARTER_CHANGE"


def test_history_excludes_same_day_and_held_starts():
    starts = pd.DataFrame([
        {"startId": "a", "gameDate": "2023-04-01", "pitcherId": "p", "eligible": True, "totalBf": 10},
        {"startId": "b", "gameDate": "2023-04-01", "pitcherId": "p", "eligible": True, "totalBf": 20},
        {"startId": "c", "gameDate": "2023-04-02", "pitcherId": "p", "eligible": False, "totalBf": 99},
        {"startId": "d", "gameDate": "2023-04-04", "pitcherId": "p", "eligible": True, "totalBf": 30},
    ])
    risks = starts[["startId", "gameDate"]].copy()
    enriched, risk = add_pregame_history(starts, risks)
    assert enriched.loc[1, "priorStartCount"] == 0
    assert enriched.loc[3, "priorStartCount"] == 2
    assert enriched.loc[3, "priorStartBfMean"] == 15
    assert enriched.loc[3, "daysRest"] == 2
    assert risk.loc[3, "latestHistoryCompletionDate"] == "2023-04-01"
