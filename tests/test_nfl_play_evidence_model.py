import pickle

import numpy as np
import pandas as pd
import pytest

from server.sports_nfl_m1.play_evidence import classify_play, normalize_partition
from server.sports_nfl_m1.play_model import fit_play_model, evaluate_play_components


def raw(play_id, **changes):
    row = dict(season=2023, game_id="2023_01_A_B", game_date="2023-09-01", week=1,
               home_team="A", away_team="B", season_type="REG", play_id=play_id, fixed_drive=1,
               posteam="A", defteam="B", yardline_100=65., qtr=1, quarter_seconds_remaining=900-play_id*10,
               half_seconds_remaining=1800-play_id*10, down=1, ydstogo=10, score_differential=0,
               play_type="run", desc="Runner up the middle", yards_gained=4., rush_attempt=1,
               home_score=21, away_score=17, first_down=0, fumble=0, fumble_lost=0)
    row.update(changes)
    return row


def plays_fixture():
    rows = []
    for index, (kind, yards, seconds) in enumerate([("RUSH", 4., 37.), ("PASS_COMPLETE", 13., 25.),
                                                   ("PASS_INCOMPLETE", 0., 5.), ("INTERCEPTION", 0., 7.)] * 20):
        rows.append(dict(season=2023, game_id=f"G{index//4}", date="2023-09-01", play_id=index,
                         offense_team="A", defense_team="B", phase="SCRIMMAGE", quarter=1,
                         quarter_seconds=600., half_seconds=1500., down=1, yards_to_go=10., yardline_100=65.,
                         score_differential=0., type=kind, yards=yards, seconds=seconds,
                         air_yards=20. if kind == "INTERCEPTION" else (8. if kind == "PASS_COMPLETE" else None),
                         return_yards=8. if kind == "INTERCEPTION" else 0., kick_distance=None,
                         turnover=kind == "INTERCEPTION", fumble=False, fumble_lost=False, touchdown=False,
                         safety=False, first_down=yards >= 10, kick_success=None, touchback=False,
                         ball_end_yardline_100=45. if kind == "INTERCEPTION" else 65.-yards,
                         turnover_yardline_100=45. if kind == "INTERCEPTION" else None,
                         return_end_yardline_100=53. if kind == "INTERCEPTION" else None,
                         receiving_start_yardline_100=None, location_evidence_status="OBSERVED_AIR_YARDS_OFFSET",
                         penalty_accepted=False, penalty_yards=None, penalty_offense=None,
                         penalty_no_play=False, penalty_automatic_first_down=False))
    return pd.DataFrame(rows)


def state(**changes):
    result = dict(offense_team="A", defense_team="B", phase="SCRIMMAGE", quarter=1,
                  quarter_seconds=600., half_seconds=1500., down=1, yards_to_go=10., yardline_100=65.,
                  score_differential=0., season=2024)
    result.update(changes)
    return result


def test_explicit_sneak_only_and_penalty_boundary():
    assert classify_play(raw(1, desc="Quarterback short run up middle"))[0] == "RUSH"
    assert classify_play(raw(1, desc="Quarterback sneak"))[0] == "QB_SNEAK"
    supported = raw(1, play_type="no_play", penalty=1, penalty_type="False Start", penalty_team="A", penalty_yards=5)
    assert classify_play(supported)[0] == "PENALTY"
    assert classify_play({**supported, "desc": "Offsetting penalties"})[0] is None
    assert classify_play({**supported, "play_type": "run"})[0] is None
    assert classify_play(raw(1, play_type="punt", punt_attempt=1, fumble=1))[1] == "ONSIDE_MUFF_BLOCKED_OR_FREE_KICK_UNSUPPORTED"


def test_compound_interception_incomplete_spike_fumbles_excluded_but_completed_pass_supported():
    for flag in ("interception", "incomplete_pass", "qb_spike"):
        for lost in (0, 1):
            row = raw(1, play_type="pass", rush_attempt=0, fumble=1, fumble_lost=lost, **{flag: 1})
            assert classify_play(row) == (None, "COMPOUND_FUMBLE_PASS_SEQUENCE_UNSUPPORTED")
            normalized, audit = normalize_partition(pd.DataFrame([row, raw(2)]), expected_season=2023)
            assert normalized.empty
            assert audit["exclusions"]["COMPOUND_FUMBLE_PASS_SEQUENCE_UNSUPPORTED"] == 1
    completed = raw(1, play_type="pass", rush_attempt=0, complete_pass=1, fumble=1, fumble_lost=1)
    assert classify_play(completed) == ("PASS_COMPLETE", None)


def test_clock_only_consecutive_live_same_period_and_try_zero():
    frame = pd.DataFrame([raw(1), raw(2, play_type="no_play", desc="Timeout", yards_gained=0), raw(3),
                          raw(4, qtr=2, quarter_seconds_remaining=900, half_seconds_remaining=900)])
    normalized, audit = normalize_partition(frame, expected_season=2023)
    assert normalized.iloc[0]["seconds"] == 20
    assert len(normalized) == 1
    assert audit["exclusions"]["NO_CONSECUTIVE_SAME_PERIOD_CLOCK"] == 2
    frame = pd.DataFrame([raw(1, play_type="extra_point", extra_point_attempt=1, extra_point_result="good"),
                          raw(2, quarter_seconds_remaining=890, half_seconds_remaining=1790)])
    normalized, _ = normalize_partition(frame, expected_season=2023)
    assert normalized.iloc[0]["seconds"] == 0
    assert normalized.iloc[0]["type"] == "EXTRA_POINT"


def test_kickoff_team_frame_and_joint_return():
    frame = pd.DataFrame([raw(1, play_type="kickoff", kickoff_attempt=1, yardline_100=35,
                              kick_distance=60, return_yards=20, touchback=0), raw(2)])
    normalized, _ = normalize_partition(frame, expected_season=2023)
    row = normalized.iloc[0]
    assert row["offense_team"] == "B" and row["defense_team"] == "A"
    assert row["yardline_100"] == 65
    assert row["ball_end_yardline_100"] == 5
    assert row["return_end_yardline_100"] == 25
    assert row["receiving_start_yardline_100"] == 75


def test_source_field_goal_and_try_enums_are_not_interchangeable():
    for changes, success in ((dict(play_type="field_goal", field_goal_attempt=1, field_goal_result="made", kick_distance=40), True),
                             (dict(play_type="field_goal", field_goal_attempt=1, field_goal_result="missed", kick_distance=40), False),
                             (dict(play_type="run", two_point_attempt=1, two_point_conv_result="failure"), False),
                             (dict(play_type="run", two_point_attempt=1, two_point_conv_result="success"), True)):
        normalized, _ = normalize_partition(pd.DataFrame([raw(1, **changes), raw(2)]), expected_season=2023)
        assert bool(normalized.iloc[0]["kick_success"]) is success


def test_fumble_recovery_explicit_spot_and_missing_not_invented():
    row = raw(1, posteam="AA", defteam="BB", fumble=1, fumble_lost=1, yards_gained=2, return_yards=0,
              fumble_recovery_1_yards=15, desc="FUMBLES. RECOVERED by BB-Player at AA 40. return")
    normalized, _ = normalize_partition(pd.DataFrame([row, raw(2)]), expected_season=2023)
    assert normalized.iloc[0]["turnover_yardline_100"] == 60
    assert normalized.iloc[0]["return_end_yardline_100"] == 75
    assert normalized.iloc[0]["return_yards"] == 15
    normalized, audit = normalize_partition(pd.DataFrame([{**row, "desc": "FUMBLES"}, raw(2)]), expected_season=2023)
    assert normalized.empty
    assert audit["exclusions"]["TURNOVER_LOCATION_OR_RETURN_UNAVAILABLE"] == 1


def test_sealed_input_and_strict_cutoff_fail_closed():
    with pytest.raises(ValueError):
        normalize_partition(pd.DataFrame([raw(1, season=2025)]), expected_season=2025)
    plays = plays_fixture()
    with pytest.raises(ValueError):
        fit_play_model(plays, end_season=2025)
    with pytest.raises(ValueError):
        fit_play_model(pd.concat([plays, plays.assign(season=2025)]), end_season=2024)
    with pytest.raises(ValueError):
        fit_play_model(plays, end_season=2023, cutoff_date="2023-09-01")
    model = fit_play_model(plays, end_season=2023, cutoff_date="2023-09-02")
    assert model.training_plays == len(plays)


def test_joint_outcome_determinism_reload_and_location_translation():
    model = fit_play_model(plays_fixture(), end_season=2023)
    rng = np.random.default_rng(41)
    results = [model.sample(state(yardline_100=55.), rng) for _ in range(30)]
    clone = pickle.loads(pickle.dumps(model))
    rng = np.random.default_rng(41)
    assert results == [clone.sample(state(yardline_100=55.), rng) for _ in range(30)]
    for row in results:
        assert (row["type"], row["yards"], row["seconds"]) in {("RUSH", 4., 37.), ("PASS_COMPLETE", 13., 25.), ("PASS_INCOMPLETE", 0., 5.), ("INTERCEPTION", 0., 7.)}
        if row["type"] == "INTERCEPTION":
            assert row["turnover_yardline_100"] == 35.
            assert row["return_end_yardline_100"] == 43.


def test_single_factor_scenario_odds_and_pace():
    model = fit_play_model(plays_fixture(), end_season=2023)
    baseline = model.probabilities(state())
    risk = model.probabilities(state(), "ELEVATED_TURNOVER")
    assert risk["INTERCEPTION"] / risk["RUSH"] == pytest.approx(1.25 * baseline["INTERCEPTION"] / baseline["RUSH"])
    passing = model.probabilities(state(), "PASS_HEAVY")
    assert passing["PASS_COMPLETE"] / passing["RUSH"] == pytest.approx(1.25 * baseline["PASS_COMPLETE"] / baseline["RUSH"])
    base = model.sample(state(), np.random.default_rng(9))
    faster = model.sample(state(), np.random.default_rng(9), "FASTER_PACE")
    assert faster["seconds"] == pytest.approx(.9 * base["seconds"])
    assert {k: v for k, v in faster.items() if k != "seconds"} == {k: v for k, v in base.items() if k != "seconds"}
    with pytest.raises(ValueError):
        model.sample(state(), np.random.default_rng(9), "FITTED_UNDECLARED_SCENARIO")


def test_try_intent_does_not_use_action_dependent_spot():
    plays = plays_fixture().iloc[:2].copy()
    plays.loc[:, "phase"] = "TRY"
    plays.loc[:, "type"] = ["EXTRA_POINT", "TWO_POINT"]
    plays.loc[:, "yardline_100"] = [15., 2.]
    model = fit_play_model(plays, end_season=2023)
    assert model.probabilities(state(phase="TRY", yardline_100=2)) == model.probabilities(state(phase="TRY", yardline_100=15))


def test_unknown_team_is_empirical_prior_and_missing_season_decay():
    model = fit_play_model(plays_fixture(), end_season=2023)
    probabilities = model.probabilities(state(offense_team="NEW", defense_team="NEW"))
    assert probabilities["RUSH"] == pytest.approx(.25)
    state_2025 = model.current_team_state("A", "B", 2025)
    assert state_2025["missingSeasonDiscount"] == pytest.approx(.65 ** 2)
    assert state_2025["teams"]["A"]["offense"] == pytest.approx(80 * .65 ** 2)


def test_missing_or_nonfinite_preplay_state_fails_closed():
    model = fit_play_model(plays_fixture(), end_season=2023)
    for key in ("offense_team", "defense_team", "season", "quarter", "quarter_seconds", "half_seconds",
                "phase", "down", "yards_to_go", "yardline_100", "score_differential"):
        missing = state()
        missing.pop(key)
        with pytest.raises(ValueError):
            model.probabilities(missing)
    with pytest.raises(ValueError):
        model.probabilities(state(yardline_100=float("nan")))


def test_exact_fractional_field_support_cache_does_not_alias_boundaries():
    plays = plays_fixture().iloc[:2].copy()
    plays.loc[:, "type"] = ["RUSH", "INTERCEPTION"]
    plays.loc[:, "turnover"] = [False, True]
    plays["air_yards"] = [float("nan"), 20.]
    plays["turnover_yardline_100"] = [float("nan"), 45.]
    plays.loc[:, "return_yards"] = [0., 9.97]
    model = fit_play_model(plays, end_season=2023)
    a = model.probabilities(state(yardline_100=10.01))
    b = model.probabilities(state(yardline_100=10.04))
    assert a["INTERCEPTION"] == 0
    assert b["INTERCEPTION"] > 0


def test_touchback_donor_must_reach_current_endzone():
    plays = plays_fixture().iloc[:2].copy()
    plays["phase"] = "KICKOFF"
    plays["type"] = "KICKOFF"
    plays["touchback"] = [True, False]
    plays["kick_distance"] = [65., 60.]
    plays["return_end_yardline_100"] = [0., 25.]
    model = fit_play_model(plays, end_season=2023)
    results = [model.sample(state(phase="KICKOFF", yardline_100=80), np.random.default_rng(i)) for i in range(10)]
    assert all(not row["touchback"] for row in results)


def test_component_validation_keeps_labels_out_and_is_chronological():
    train = plays_fixture()
    model = fit_play_model(train, end_season=2023)
    valid = train.assign(season=2024, date="2024-09-01")
    result = evaluate_play_components(model, valid)
    assert result["heldoutPlayCount"] == 80
    assert result["multiclassLogLoss"] == pytest.approx(np.log(4))
    assert result["phaseOnlyUnconditionalBaselineLogLoss"] == pytest.approx(np.log(4))
    with pytest.raises(ValueError):
        evaluate_play_components(model, train)
