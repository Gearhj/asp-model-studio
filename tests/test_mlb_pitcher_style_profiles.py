"""Focused synthetic temporal/support checks for the new profile calculation."""
from __future__ import annotations

import json
import io

import numpy as np
import pandas as pd
import pytest

from server.sports_current_statcast.mlb_pitcher_style_profiles import (
    GROUPS, STYLE_FEATURES, IDENTITY_COLUMNS, identity_mask, profiles_from_pitches, require_matching_identity,
)


def starts():
    return pd.DataFrame([{"startId": "start-a", "pitcherId": "retrosheet:player:test0001",
                          "gameDate": "2023-07-01", "gameId": "retrosheet:game:BAL202307010"}])


def pitches():
    rows = []
    for date, game in (("2023-06-01", "111"), ("2023-06-10", "112"), ("2023-06-20", "113")):
        for i in range(100):
            rows.append({"game_date": date, "game_pk": game, "game_type": "R", "pitcher": "123",
                "at_bat_number": str(i//4+1), "pitch_number": str(i%4+1), "p_throws": "L",
                "pitch_type": "FF" if i < 70 else "CU", "release_speed": 90+i/100,
                "pfx_x": .7, "pfx_z": .5, "release_pos_x": 2.1, "release_pos_z": 5.8,
                "release_extension": 6.1, "sourcePartitionId": "fixture-"+date,
                "sourceCaptureAtUtc": "2026-08-21T20:00:00Z"})
    return pd.DataFrame(rows)


def build(frame=None):
    return profiles_from_pitches(starts(), pitches() if frame is None else frame,
                                 {"retrosheet:player:test0001": "123"}).iloc[0]


def test_prior_window_excludes_same_day_future_and_stale_history():
    baseline = build()
    extra = pitches()
    extra["release_speed"] = 200.0
    additions = []
    for date in ("2022-06-30", "2023-07-01", "2023-07-02"):
        copy = extra.copy()
        copy["game_date"] = date
        additions.append(copy)
    changed = build(pd.concat([pitches(), *additions], ignore_index=True))
    pd.testing.assert_series_equal(baseline[STYLE_FEATURES], changed[STYLE_FEATURES])
    assert changed.profilePitchCount == 300
    assert changed.profileLatestGameDate == "2023-06-20"
    assert changed.profileEarliestGameDate == "2023-06-01"


def test_measured_quantiles_and_usage_reconcile_without_clipping():
    row = build()
    assert row.profileSupported
    assert row.profilePriorDateCount == 3
    assert row.style_throws_left == 1
    assert row.style_FF_usage == .7
    assert row.style_CU_KC_usage == .3
    assert sum(row[f"style_{group}_usage"] for group in GROUPS) == pytest.approx(1)
    values = pitches().query("pitch_type == 'FF'").release_speed.to_numpy()
    assert row.style_FF_speed_median_mph == np.quantile(values, .5, method="linear")
    assert row.style_FF_speed_p90_mph == np.quantile(values, .9, method="linear")
    assert row.style_FF_pfx_x_median_ft == .7
    assert row.style_FF_release_x_median_ft == 2.1  # no invented hand sign-flip
    assert len(STYLE_FEATURES) == 73


def test_unknown_types_and_insufficient_measurements_are_explicit():
    frame = pitches()
    frame.loc[frame.index[:20], "pitch_type"] = ""
    frame.loc[frame.index[20:29], "pitch_type"] = "ST"
    row = build(frame)
    assert row.style_UNKNOWN_usage == pytest.approx(20/300)
    assert row.style_SL_ST_usage == pytest.approx(9/300)
    assert np.isnan(row.style_SL_ST_speed_median_mph)
    supports = json.loads(row.profileMeasurementSupportJson)
    assert supports["SL_ST_speed_median_mph"] == 9
    assert json.loads(row.profileSourcePitchTypeStatsJson)["ST"]["pitchCount"] == 9


def test_support_and_hand_fail_closed_without_invented_values():
    assert "FEWER_THAN_200_PRIOR_PITCHES" in build(pitches().iloc[:199]).profileUnsupportedReason
    assert "FEWER_THAN_3_PRIOR_APPEARANCE_DATES" in build(pitches().iloc[:200]).profileUnsupportedReason
    frame = pitches()
    frame.loc[0, "p_throws"] = "R"
    row = build(frame)
    assert not row.profileSupported
    assert "THROWING_HAND_MISSING_OR_INCONSISTENT" in row.profileUnsupportedReason
    assert np.isnan(row.style_throws_left)
    row = profiles_from_pitches(starts(), pitches(), {}).iloc[0]
    assert not row.profileSupported
    assert "PITCHER_IDENTITY_UNMAPPED" in row.profileUnsupportedReason


def test_identity_gate_holds_all_nine_and_unapproved_game_pool():
    keys = ["823343", "824235", "822693", "824237", "823182", "823342", "824316", "824233", "822694"]
    frame = pd.DataFrame({"game_pk": keys+["111", "112"], "game_date": ["2026-08-17"]*9+["2023-06-01"]*2,
                          "game_type": ["R"]*11})
    mask = identity_mask(frame, permitted_game_pks=set(keys+["111"]))
    assert mask.tolist() == [False]*9+[True, False]


def test_direct_builder_rejects_sealed_payload_and_future_targets():
    frame = pitches()
    frame.loc[0, ["game_pk", "game_date"]] = ["823343", "2026-08-17"]
    with pytest.raises(ValueError, match="UNGATED_SOURCE"):
        build(frame)
    targets = starts()
    targets["gameDate"] = "2026-08-17"
    with pytest.raises(ValueError, match="OUTSIDE_DECLARED"):
        profiles_from_pitches(targets, pitches(), {})


def test_csv_header_order_preserves_identity_values_and_detects_real_changes():
    # The retained Savant CSV orders game_date before game_pk. pandas ignores
    # the requested usecols ordering; this reproduced the real loader failure.
    csv = ("pitch_type,game_date,pitcher,game_type,game_pk,at_bat_number,pitch_number,release_speed\n"
           "FF,2023-06-01,123,R,111,1,1,92\n"
           "CU,2023-06-01,123,R,111,1,2,79\n")
    identities = pd.read_csv(io.StringIO(csv), usecols=IDENTITY_COLUMNS, dtype=str, keep_default_na=False)
    payload = pd.read_csv(io.StringIO(csv), usecols=IDENTITY_COLUMNS+["pitch_type", "release_speed"],
                          dtype=str, keep_default_na=False)
    assert list(identities.columns) != IDENTITY_COLUMNS
    assert not payload[IDENTITY_COLUMNS].equals(identities)  # original defect
    require_matching_identity(identities, payload)
    changed = payload.copy()
    changed.loc[0, "game_pk"] = "999"
    with pytest.raises(ValueError, match="IDENTITY_CHANGED"):
        require_matching_identity(identities, changed)
    with pytest.raises(ValueError, match="IDENTITY_CHANGED"):
        require_matching_identity(identities, payload.iloc[::-1].reset_index(drop=True))
