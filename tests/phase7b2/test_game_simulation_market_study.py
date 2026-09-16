from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_gold import game_simulation_market_study as S
from server.sports_gold.contracts import GOLD_FEATURES
from server.sports_gold.game_probability_adapter import (
    CANONICAL_CONTEXT,
    TEMPLATE_COLUMNS,
)
from server.sports_gold.game_simulation_inputs import (
    GameTruth,
    PredictionCohort,
    PregameGame,
    TeamPregame,
)
from server.sports_gold.walk_forward_ensemble import DIRECT_GOLD
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_phase5.whole_game_monte_carlo import GameSimResult


def _game(game_id: str = "canonical-game-a") -> PregameGame:
    suffix = game_id.rsplit("-", 1)[-1]
    return PregameGame(
        canonical_game_id=game_id,
        prediction_game_id=f"retrosheet:game:RETRO{suffix.upper()}",
        retrosheet_game_id=f"RETRO{suffix.upper()}",
        mlbam_game_pk="12345",
        game_date="2024-09-20",
        season=2024,
        game_type="R",
        game_number=0,
        park_id="park-a",
        away=TeamPregame(
            canonical_team_id="away-team",
            batting_order=tuple(f"away-batter-{index}" for index in range(1, 10)),
            starting_pitcher_id="away-starter",
        ),
        home=TeamPregame(
            canonical_team_id="home-team",
            batting_order=tuple(f"home-batter-{index}" for index in range(1, 10)),
            starting_pitcher_id="home-starter",
        ),
    )


def _feature_values() -> dict[str, float]:
    values = {name: 0.0 for name in GOLD_FEATURES}
    values.update(
        {
            "batter_avg": 0.250,
            "batter_obp": 0.320,
            "batter_slg": 0.410,
            "pitcher_era9": 4.0,
            "pitcher_whip": 1.25,
            "matchup_batter_bats_left": 1.0,
            "matchup_batter_bats_switch": 0.0,
            "matchup_batter_hand_missing": 0.0,
            "matchup_pitcher_throws_left": 0.0,
            "matchup_pitcher_hand_missing": 0.0,
            "matchup_platoon_advantage": 0.0,
        }
    )
    return values


def _gold_frame(game: PregameGame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for batter_id in (*game.away.batting_order, *game.home.batting_order):
        rows.append(
            {
                "game_date": game.game_date,
                "batterCanonicalPlayerId": batter_id,
                "pitcherCanonicalPlayerId": "unused-pitcher",
                "outcome": "MUST_NOT_BE_READ",
                "actualRelieverId": "MUST_NOT_BE_READ",
                "substitutionPlayerId": "MUST_NOT_BE_READ",
                **_feature_values(),
            }
        )
    for starter_id in (game.away.starting_pitcher_id, game.home.starting_pitcher_id):
        rows.append(
            {
                "game_date": game.game_date,
                "batterCanonicalPlayerId": "unused-batter",
                "pitcherCanonicalPlayerId": starter_id,
                "outcome": "MUST_NOT_BE_READ",
                "actualRelieverId": "MUST_NOT_BE_READ",
                "substitutionPlayerId": "MUST_NOT_BE_READ",
                **_feature_values(),
            }
        )
    return pd.DataFrame(rows)


def _simulation_result(game: PregameGame) -> GameSimResult:
    away = np.tile(np.asarray([1, 4, 2, 3], dtype=np.int64), 125)
    home = np.tile(np.asarray([3, 2, 4, 4], dtype=np.int64), 125)
    first_away = np.tile(np.asarray([0, 2, 1, 3], dtype=np.int64), 125)
    first_home = np.tile(np.asarray([1, 1, 1, 2], dtype=np.int64), 125)
    return GameSimResult(
        game_id=game.prediction_game_id,
        n_sims=500,
        away_runs=away,
        home_runs=home,
        innings=np.full(500, 9, dtype=np.int64),
        pa_counts=np.full(500, 70, dtype=np.int64),
        home_win=home > away,
        nonterminated=0,
        illegal_states=0,
        first_five_away_runs=first_away,
        first_five_home_runs=first_home,
    )


def _summary(game_id: str = "canonical-game-a") -> dict[str, Any]:
    game = _game(game_id)
    truth = GameTruth(
        canonical_game_id=game.canonical_game_id,
        away_runs=2,
        home_runs=5,
        first_five_away_runs=1,
        first_five_home_runs=1,
        first_five_source="SYNTHETIC_FIXTURE",
    )
    return S.summarize_game_simulation(
        _simulation_result(game),
        cohort_id="FOLD_1",
        candidate_id=DIRECT_GOLD,
        game=game,
        truth=truth,
        adapter_record={
            "templateRowCount": 18,
            "substitutionsUsed": False,
            "actualRelieversUsed": False,
            "targetOutcomeColumnsAccepted": False,
        },
    )


def test_pregame_template_is_exact_ordered_18_and_ignores_actual_game_fields() -> None:
    game = _game()
    gold = _gold_frame(game)
    template, state, evidence = S.build_pregame_templates(gold, game)

    assert template.shape == (18, len(TEMPLATE_COLUMNS))
    assert tuple(template.columns) == TEMPLATE_COLUMNS
    assert template["batting_side"].tolist() == ["AWAY"] * 9 + ["HOME"] * 9
    assert template["batting_order_slot"].tolist() == list(range(1, 10)) * 2
    assert template["batterCanonicalPlayerId"].tolist() == [
        *game.away.batting_order,
        *game.home.batting_order,
    ]
    assert template["pitcherCanonicalPlayerId"].tolist() == [
        *([game.home.starting_pitcher_id] * 9),
        *([game.away.starting_pitcher_id] * 9),
    ]
    assert template["plate_appearance_id"].tolist() == [
        *(
            f"phase7b6:pregame:{game.canonical_game_id}:away:{slot}"
            for slot in range(1, 10)
        ),
        *(
            f"phase7b6:pregame:{game.canonical_game_id}:home:{slot}"
            for slot in range(1, 10)
        ),
    ]
    for column, value in CANONICAL_CONTEXT.items():
        assert template[column].tolist() == [value] * 18
    assert template["context_top_bottom"].tolist() == [0] * 9 + [1] * 9
    assert tuple(state.columns) == (
        "plate_appearance_id",
        "game_date",
        "batterCanonicalPlayerId",
        "pitcherCanonicalPlayerId",
    )
    assert state["game_date"].tolist() == [game.game_date] * 18
    assert not {"outcome", "actualRelieverId", "substitutionPlayerId"}.intersection(
        template.columns
    )
    assert evidence["sourceRecords"] == 20
    assert evidence["actualSubstitutionRowsUsed"] == 0
    assert evidence["actualRelieverRowsUsed"] == 0
    assert evidence["outcomeColumnsRead"] == 0

    duplicate = replace(
        game,
        away=replace(
            game.away,
            batting_order=(*game.away.batting_order[:8], game.away.batting_order[0]),
        ),
    )
    with pytest.raises(S.GameSimulationMarketStudyError, match="nine unique"):
        S.build_pregame_templates(gold, duplicate)
    ten_batters = replace(
        game,
        away=replace(
            game.away, batting_order=(*game.away.batting_order, "substitute-10")
        ),
    )
    with pytest.raises(S.GameSimulationMarketStudyError, match="nine unique"):
        S.build_pregame_templates(gold, ten_batters)


def test_pregame_stance_history_is_strictly_prior_and_context_variation_is_allowed() -> (
    None
):
    game = _game()
    gold = _gold_frame(game)

    def observation(
        batter_id: str,
        day: str,
        *,
        bats_left: float,
        pitcher_throws_left: float,
    ) -> dict[str, Any]:
        row = dict(gold.loc[gold["batterCanonicalPlayerId"].eq(batter_id)].iloc[0])
        row.update(
            {
                "game_date": day,
                "pitcherCanonicalPlayerId": (
                    f"historical-pitcher-{int(pitcher_throws_left)}"
                ),
                "matchup_batter_bats_left": bats_left,
                "matchup_batter_hand_missing": 0.0,
                "matchup_pitcher_throws_left": pitcher_throws_left,
                "matchup_pitcher_hand_missing": 0.0,
            }
        )
        return row

    extra = pd.DataFrame(
        [
            # Same announced-pitcher hand: only 9/18 may be used. The conflicting
            # same-day row also proves realized stance is no longer an invariant snapshot.
            observation(
                "away-batter-1",
                "2024-09-18",
                bats_left=1.0,
                pitcher_throws_left=0.0,
            ),
            observation(
                "away-batter-1",
                game.game_date,
                bats_left=0.0,
                pitcher_throws_left=0.0,
            ),
            observation(
                "away-batter-1",
                "2024-09-21",
                bats_left=0.0,
                pitcher_throws_left=0.0,
            ),
            # No same-hand history: one unambiguous prior career stance may fall back.
            observation(
                "away-batter-2",
                "2024-09-18",
                bats_left=1.0,
                pitcher_throws_left=1.0,
            ),
            # Ambiguous career stance with no same-hand history must become missing.
            observation(
                "away-batter-3",
                "2024-09-17",
                bats_left=0.0,
                pitcher_throws_left=1.0,
            ),
            observation(
                "away-batter-3",
                "2024-09-18",
                bats_left=1.0,
                pitcher_throws_left=1.0,
            ),
        ]
    )
    gold = pd.concat([gold, extra], ignore_index=True)

    template, _state, evidence = S.build_pregame_templates(gold, game)
    away = template.loc[template["batting_side"].eq("AWAY")].reset_index(drop=True)
    assert away.loc[0, "matchup_batter_bats_left"] == 1.0
    assert away.loc[0, "matchup_batter_hand_missing"] == 0.0
    assert away.loc[1, "matchup_batter_bats_left"] == 1.0
    assert away.loc[1, "matchup_batter_hand_missing"] == 0.0
    assert away.loc[2, "matchup_batter_bats_left"] == 0.0
    assert away.loc[2, "matchup_batter_hand_missing"] == 1.0
    assert away["matchup_batter_bats_switch"].eq(0.0).all()

    stance = {row["batterId"]: row for row in evidence["batterStanceEvidence"]}
    assert stance["away-batter-1"]["sourceKind"] == (
        "MOST_RECENT_PRIOR_SAME_PITCHER_HAND"
    )
    assert stance["away-batter-1"]["sourceDate"] == "2024-09-18"
    assert stance["away-batter-2"]["sourceKind"] == (
        "SINGLE_UNAMBIGUOUS_PRIOR_CAREER_STANCE"
    )
    assert stance["away-batter-2"]["sourceDate"] == "2024-09-18"
    assert stance["away-batter-3"]["sourceKind"] == (
        "PRIOR_CAREER_STANCE_AMBIGUOUS_OR_UNAVAILABLE"
    )
    assert stance["away-batter-3"]["sourceDate"] is None
    assert all(
        row["sourceDate"] is None or row["sourceDate"] < game.game_date
        for row in stance.values()
    )
    assert evidence["batterStanceSameDayRowsUsed"] == 0
    assert evidence["batterStanceFutureRowsUsed"] == 0
    assert evidence["batterSwitchFeaturePolicy"] == "FROZEN_GOLD_VALUE_NO_INFERENCE"


def test_pregame_batter_without_on_or_before_snapshot_uses_governed_cold_start() -> (
    None
):
    game = _game()
    rookie_id = "rookie-with-only-future-gold-row"
    rookie_game = replace(
        game,
        away=replace(
            game.away,
            batting_order=(rookie_id, *game.away.batting_order[1:]),
        ),
    )
    gold = _gold_frame(game)
    future = dict(
        gold.loc[
            gold["batterCanonicalPlayerId"].eq(game.away.batting_order[0])
        ].iloc[0]
    )
    future.update(
        {
            "game_date": "2024-09-21",
            "batterCanonicalPlayerId": rookie_id,
            "batter_log1p_pa": 99.0,
            "batter_avg": 0.999,
            "batter_prior_pa_count": 999.0,
            "batter_last100_pa_count": 100.0,
            "matchup_batter_bats_left": 1.0,
            "matchup_batter_hand_missing": 0.0,
        }
    )
    index = S.PregameFeatureIndex(
        pd.concat([gold, pd.DataFrame([future])], ignore_index=True)
    )

    values, lookup_evidence = index.lookup(
        player_id=rookie_id,
        score_date=rookie_game.game_date,
        role="batter",
    )
    assert lookup_evidence == {
        "playerId": rookie_id,
        "role": "BATTER",
        "sourceKind": "ROLE_COLD_START_NO_PRIOR_GOLD_SNAPSHOT",
        "sourceDate": None,
        "scoreDate": rookie_game.game_date,
        "sameDayStrictPriorFeatureSnapshot": False,
        "fallbackDays": None,
        "sameDayRowsUsed": 0,
        "futureRowsUsed": 0,
        "coldStart": True,
    }
    assert np.isnan(values["batter_log1p_pa"])
    assert np.isnan(values["batter_avg"])
    assert values["batter_prior_missing"] == 1.0
    assert values["batter_prior_pa_count"] == 0.0
    assert values["batter_last100_pa_count"] == 0.0
    assert values["batter_last100_insufficient"] == 1.0
    assert values["batter_last100_whiff_missing"] == 1.0
    assert values["matchup_batter_bats_switch"] == 0.0
    assert values["matchup_batter_hand_missing"] == 1.0

    template, _state, evidence = S.build_pregame_templates(index, rookie_game)
    rookie = template.loc[
        template["batterCanonicalPlayerId"].eq(rookie_id)
    ].iloc[0]
    assert np.isnan(rookie["batter_log1p_pa"])
    assert np.isnan(rookie["batter_avg"])
    assert rookie["batter_prior_missing"] == 1.0
    assert rookie["batter_prior_pa_count"] == 0.0
    assert rookie["batter_last100_pa_count"] == 0.0
    assert rookie["batter_last100_insufficient"] == 1.0
    assert rookie["batter_last100_whiff_missing"] == 1.0
    assert rookie["matchup_batter_bats_left"] == 0.0
    assert rookie["matchup_batter_bats_switch"] == 0.0
    assert rookie["matchup_batter_hand_missing"] == 1.0
    assert evidence["sourceRecords"] == 20
    assert evidence["sameDaySourceRecords"] == 19
    assert evidence["priorFallbackSourceRecords"] == 0
    assert evidence["coldStartSourceRecords"] == 1
    assert evidence["playerFeatureFutureRowsUsed"] == 0
    assert evidence["batterStanceFutureRowsUsed"] == 0
    assert evidence["coldStartPlayerFeatureEvidence"] == [lookup_evidence]


def test_simulation_summary_has_full_game_first_five_distributions_and_stability() -> (
    None
):
    record = _summary()
    assert record["nSimulations"] == 500
    assert record["classOrder"] == list(PA_CLASS_ORDER)
    assert record["homeWinProbability"] == pytest.approx(0.75)
    assert record["awayWinProbability"] == pytest.approx(0.25)
    assert record["expectedAwayRuns"] == pytest.approx(2.5)
    assert record["expectedHomeRuns"] == pytest.approx(3.25)
    assert record["expectedTotalRuns"] == pytest.approx(5.75)
    assert sum(row["count"] for row in record["jointScoreDistribution"]) == 500
    assert sum(
        row["probability"] for row in record["jointScoreDistribution"]
    ) == pytest.approx(1.0)
    assert sum(
        row["probability"] for row in record["runDifferenceDistribution"]
    ) == pytest.approx(1.0)
    assert sum(
        row["probability"] for row in record["totalRunsDistribution"]
    ) == pytest.approx(1.0)

    first = record["firstFive"]
    assert first["completedSimulations"] == 500
    assert first["completionRate"] == 1.0
    assert first["awayWinProbability"] == pytest.approx(0.50)
    assert first["tieProbability"] == pytest.approx(0.25)
    assert first["homeWinProbability"] == pytest.approx(0.25)
    assert first["expectedAwayRuns"] == pytest.approx(1.5)
    assert first["expectedHomeRuns"] == pytest.approx(1.25)
    assert first["expectedTotalRuns"] == pytest.approx(2.75)
    assert sum(row["count"] for row in first["jointScoreDistribution"]) == 500
    assert [
        row["simulations"] for row in record["simulationStability"]["prefixes"]
    ] == [
        100,
        250,
        500,
    ]
    assert set(record["simulationStability"]["maximumAbsoluteDriftVsFinal"]) == {
        "homeWinProbability",
        "expectedAwayRuns",
        "expectedHomeRuns",
        "expectedTotalRuns",
        "expectedRunDifference",
    }
    assert record["pregamePolicy"]["substitutionsUsed"] is False
    assert record["pregamePolicy"]["actualRelieversUsed"] is False


def test_game_level_metrics_match_hand_calculation_including_first_five() -> None:
    first = _summary("canonical-game-a")
    second = copy.deepcopy(first)
    second["canonicalGameId"] = "canonical-game-b"
    second["homeWinProbability"] = 0.25
    second["awayWinProbability"] = 0.75
    second["expectedAwayRuns"] = 4.0
    second["expectedHomeRuns"] = 2.0
    second["expectedTotalRuns"] = 6.0
    second["truth"].update(
        {
            "awayRuns": 3,
            "homeRuns": 1,
            "homeWon": False,
            "firstFiveAvailable": True,
            "firstFiveAwayRuns": 1,
            "firstFiveHomeRuns": 2,
        }
    )
    second["firstFive"].update(
        {
            "awayWinProbability": 0.20,
            "tieProbability": 0.30,
            "homeWinProbability": 0.50,
            "expectedAwayRuns": 1.2,
            "expectedHomeRuns": 2.1,
            "expectedTotalRuns": 3.3,
        }
    )

    metrics = S.game_level_metrics([first, second])
    assert metrics["gameCount"] == 2
    assert metrics["moneylineLogLoss"] == pytest.approx(-np.log(0.75))
    assert metrics["moneylineBrier"] == pytest.approx(0.0625)
    assert metrics["calibration"]["ece"] == pytest.approx(0.25)
    assert metrics["winnerAccuracy"] == 1.0
    assert metrics["awayRunMae"] == pytest.approx(0.75)
    assert metrics["homeRunMae"] == pytest.approx(1.375)
    assert metrics["meanTeamRunMae"] == pytest.approx(1.0625)
    assert metrics["totalRunMae"] == pytest.approx(1.625)

    first_five = metrics["firstFive"]
    assert first_five["availableGames"] == 2
    assert first_five["coverage"] == 1.0
    assert first_five["threeWayLogLoss"] == pytest.approx(
        -0.5 * (np.log(0.25) + np.log(0.50))
    )
    assert first_five["summedBrier"] == pytest.approx((0.875 + 0.38) / 2)
    assert first_five["winnerTieAccuracy"] == pytest.approx(0.5)
    assert first_five["awayRunMae"] == pytest.approx(0.35)
    assert first_five["homeRunMae"] == pytest.approx(0.175)
    assert first_five["meanTeamRunMae"] == pytest.approx(0.2625)
    assert first_five["totalRunMae"] == pytest.approx(0.525)
    assert set(metrics["simulationStability"]) == {
        "homeWinProbability",
        "expectedAwayRuns",
        "expectedHomeRuns",
        "expectedTotalRuns",
        "expectedRunDifference",
    }
    assert metrics["nonterminated"] == 0
    assert metrics["illegalStates"] == 0

    with pytest.raises(S.GameSimulationMarketStudyError, match="duplicates"):
        S.game_level_metrics([first, first])


def test_common_rng_and_direct_e10_cohort_reconcile_one_game(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game = _game()
    truth = GameTruth(
        canonical_game_id=game.canonical_game_id,
        away_runs=2,
        home_runs=5,
        first_five_away_runs=1,
        first_five_home_runs=1,
        first_five_source="SYNTHETIC_FIXTURE",
    )
    uniform = np.full((1, len(PA_CLASS_ORDER)), 1.0 / len(PA_CLASS_ORDER))
    cohort = PredictionCohort(
        cohort_id="HOLDOUT",
        start_date=game.game_date,
        end_date=game.game_date,
        row_ids=("observed-pa-1",),
        canonical_game_ids_by_row=(game.canonical_game_id,),
        game_ids_by_row=(game.prediction_game_id,),
        game_ids=(game.prediction_game_id,),
        canonical_game_ids=(game.canonical_game_id,),
        labels=(PA_CLASS_ORDER[0],),
        probability_matrices={DIRECT_GOLD: uniform},
        reliability={},
    )
    inputs = SimpleNamespace(
        games={game.canonical_game_id: game},
        truth={game.canonical_game_id: truth},
        study=SimpleNamespace(
            request={
                "folds": [
                    {
                        "foldId": "FOLD_5",
                        "trainEnd": "2024-09-19",
                        "validationEnd": game.game_date,
                    }
                ]
            }
        ),
    )
    frame = pd.DataFrame(
        {
            "plate_appearance_id": ["observed-pa-1"],
            "canonicalGameId": [game.canonical_game_id],
            "game_date": [game.game_date],
        }
    )

    class FakeEngine:
        history_end_day = "2024-09-19"

        def score_snapshot(
            self, _state: pd.DataFrame, _ledger: object
        ) -> SimpleNamespace:
            return SimpleNamespace(probability_matrices={}, reliability={})

    class FakeDirect:
        def predict_proba(self, template: pd.DataFrame) -> np.ndarray:
            return np.full(
                (len(template), len(PA_CLASS_ORDER)), 1.0 / len(PA_CLASS_ORDER)
            )

    class FakeAdapter:
        def record(self) -> dict[str, Any]:
            return {
                "templateRowCount": 18,
                "substitutionsUsed": False,
                "actualRelieversUsed": False,
                "targetOutcomeColumnsAccepted": False,
            }

        def provider(self, candidate: str) -> str:
            return candidate

    template = pd.DataFrame(
        {"plate_appearance_id": [f"pregame-{index}" for index in range(18)]}
    )
    state = pd.DataFrame(
        {
            "plate_appearance_id": template["plate_appearance_id"],
            "game_date": [game.game_date] * 18,
        }
    )
    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_simulate_game(**kwargs: Any) -> GameSimResult:
        captured.append(
            (str(kwargs["probability_provider"]), kwargs["rng_lineage"].as_dict())
        )
        return _simulation_result(game)

    monkeypatch.setattr(S, "EXPECTED_COHORT_GAMES", {"HOLDOUT": 1})
    monkeypatch.setattr(
        S, "fit_walk_forward_state", lambda *_args, **_kwargs: FakeEngine()
    )
    monkeypatch.setattr(
        S,
        "build_pregame_templates",
        lambda *_args, **_kwargs: (
            template,
            state,
            {
                "sourceRecords": 20,
                "priorFallbackSourceRecords": 0,
                "actualSubstitutionRowsUsed": 0,
                "actualRelieverRowsUsed": 0,
                "outcomeColumnsRead": 0,
            },
        ),
    )
    monkeypatch.setattr(
        S.ChronologicalDirectLedger, "aligned", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        S, "build_pregame_probability_adapter", lambda *_args, **_kwargs: FakeAdapter()
    )
    monkeypatch.setattr(S, "simulate_game", fake_simulate_game)
    monkeypatch.setattr(
        S, "_score_and_advance_observed_day", lambda *_args, **_kwargs: None
    )

    records, evidence = S._simulate_cohort(
        cohort=cohort,
        inputs=inputs,
        frame=frame,
        feature_index=object(),
        full_ledger=object(),
        direct_model=FakeDirect(),
        e10_stacker=object(),
        transition_sampler=object(),
        progress=lambda _message: None,
    )
    assert [candidate for candidate, _lineage in captured] == list(S.CANDIDATE_ORDER)
    assert captured[0][1] == captured[1][1]
    assert captured[0][1]["masterSeed"] == S.MASTER_SEED
    assert captured[0][1]["gameKey"] == game.prediction_game_id
    assert [record["candidateId"] for record in records] == list(S.CANDIDATE_ORDER)
    assert records[0]["jointScoreDistribution"] == records[1]["jointScoreDistribution"]
    assert evidence["gameCount"] == 1
    assert evidence["candidateResultCount"] == 2
    assert evidence["actualSubstitutionsUsed"] == 0
    assert evidence["actualRelieversUsed"] == 0


def test_zero_odds_board_is_exact_all_no_bet_and_has_no_roi_value() -> None:
    record = _summary()
    board = S.unavailable_shadow_board(record)
    assert board["canonicalGameId"] == record["canonicalGameId"]
    assert board["scheduledStartUtc"] is None
    assert board["scheduledStartAuthority"] == "UNAVAILABLE"
    assert [row["marketFamily"] for row in board["rows"]] == [
        *[
            family.value
            for family in S.MARKET_FAMILY_ORDER
            if family is not S.MarketFamily.TEAM_TOTAL
        ],
        "TEAM_TOTAL",
        "TEAM_TOTAL",
    ]
    assert [
        row["subjectTeamId"]
        for row in board["rows"]
        if row["marketFamily"] == "TEAM_TOTAL"
    ] == [record["homeTeamId"], record["awayTeamId"]]
    assert len(board["rows"]) == 7
    assert all(row["state"] == "NO_BET" for row in board["rows"])
    assert all(row["stakeFraction"] == 0.0 for row in board["rows"])
    assert all(row["sportsbookId"] is None for row in board["rows"])
    assert all(row["quoteTimestampUtc"] is None for row in board["rows"])
    assert board["sameGameExposureFraction"] == 0.0
    assert board["dailyExposureFraction"] == 0.0
    assert board["historicalRoiReported"] is False
    assert board["shadowOnly"] is True
    assert board["executionAllowed"] is False
    forbidden_keys = {"roi", "profit", "return", "clv", "settlement", "payout"}
    assert forbidden_keys.isdisjoint(
        {str(key).lower() for row in board["rows"] for key in row}
    )


def test_request_and_result_hashes_are_canonical_sensitive_and_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = {
        "schemaVersion": S.REQUEST_SCHEMA_VERSION,
        "simulation": {"masterSeed": S.MASTER_SEED, "simulationsPerGame": 500},
        "paEngines": list(S.CANDIDATE_ORDER),
    }
    reordered = {
        "paEngines": list(S.CANDIDATE_ORDER),
        "simulation": {"simulationsPerGame": 500, "masterSeed": S.MASTER_SEED},
        "schemaVersion": S.REQUEST_SCHEMA_VERSION,
    }
    request_sha = S._sha256_bytes(canonical_json_bytes(request))
    assert request_sha == S._sha256_bytes(canonical_json_bytes(reordered))
    changed_request = copy.deepcopy(request)
    changed_request["simulation"]["masterSeed"] += 1
    assert request_sha != S._sha256_bytes(canonical_json_bytes(changed_request))

    results = {
        "schemaVersion": S.RESULT_SCHEMA_VERSION,
        "requestSha256": request_sha,
        "status": "GAME_SIMULATION_MARKET_MVP_COMPLETE",
        "historicalRoiReported": False,
    }
    results_sha = S._sha256_bytes(canonical_json_bytes(results))
    changed_results = {**results, "status": "TAMPERED"}
    assert results_sha != S._sha256_bytes(canonical_json_bytes(changed_results))

    results_text = json.dumps(results)
    results_bytes = results_text.encode("utf-8")
    artifact = {
        "bytes": len(results_bytes),
        "sha256": S._sha256_bytes(results_bytes),
    }
    manifest = {
        "schemaVersion": "MLB_GOLD_GAME_SIMULATION_MARKET_MVP_MANIFEST_V1",
        "request": request,
        "requestSha256": request_sha,
        "resultsSha256": results_sha,
        "artifacts": {"results.json": artifact},
    }

    class MemoryPath:
        def __init__(
            self,
            root_name: str,
            files: dict[str, str],
            relative: str = "",
        ) -> None:
            self._root_name = root_name
            self._files = files
            self._relative = relative

        def __truediv__(self, relative: str) -> "MemoryPath":
            return MemoryPath(self._root_name, self._files, str(relative))

        @property
        def name(self) -> str:
            if not self._relative:
                return self._root_name
            return PurePosixPath(self._relative).name

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return self._files[self._relative]

        def rglob(self, pattern: str) -> list["MemoryPath"]:
            assert pattern == "*"
            return [
                MemoryPath(self._root_name, self._files, relative)
                for relative in self._files
            ]

        def is_file(self) -> bool:
            return self._relative in self._files

        def relative_to(self, other: "MemoryPath") -> PurePosixPath:
            assert other._root_name == self._root_name
            return PurePosixPath(self._relative)

    files = {
        "manifest.json": json.dumps(manifest),
        "results.json": results_text,
    }
    final_root = MemoryPath(request_sha, files)

    def memory_sha256_file(path: MemoryPath) -> tuple[int, str]:
        content = path.read_text(encoding="utf-8").encode("utf-8")
        return len(content), S._sha256_bytes(content)

    monkeypatch.setattr(S, "_sha256_file", memory_sha256_file)
    assert S._verify_existing(final_root, reordered) == results

    bad_request_manifest = {**manifest, "requestSha256": "0" * 64}
    files["manifest.json"] = json.dumps(bad_request_manifest)
    with pytest.raises(S.GameSimulationMarketStudyError, match="request address"):
        S._verify_existing(final_root, request)

    tampered = {**results, "status": "TAMPERED"}
    tampered_text = json.dumps(tampered)
    tampered_bytes = tampered_text.encode("utf-8")
    bad_result_manifest = {
        **manifest,
        "artifacts": {
            "results.json": {
                "bytes": len(tampered_bytes),
                "sha256": S._sha256_bytes(tampered_bytes),
            }
        },
    }
    files["manifest.json"] = json.dumps(bad_result_manifest)
    files["results.json"] = tampered_text
    with pytest.raises(S.GameSimulationMarketStudyError, match="result identity"):
        S._verify_existing(final_root, request)
