from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from server.sports_current_statcast.mlb_v18_game_baseline import (
    CALIBRATION_REQUIRED,
    calibration_decision,
    reconstruct_transitions,
    simulator_specification,
)


REPORT = Path("outputs/mlb-corrected-treatment/corrected-hgb-recovery-1-comparison-12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d.json")
BASELINE_ROOT = Path("outputs/mlb-v18-pa-game-baseline/sha256/5d0525475d26c63b275f2534badf668173b2a149c885327ad1dbcc4a6c5533ee")


def _comparison():
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_calibration_decision_uses_all_predeclared_dimensions_without_fit():
    decision = calibration_decision(_comparison())
    assert decision["disposition"] == CALIBRATION_REQUIRED
    assert decision["modelsFit"] == 0
    assert not decision["checks"]["maximumPopulatedReliabilityBandGap"]["pass"]
    assert decision["worstPopulatedReliabilityBand"]["observations"] >= 1000
    assert {row["name"] for row in decision["sparseNonGatingSubgroups"]} == {
        "BATTING_NO_PRIOR_GAME", "FIELDING_NO_PRIOR_GAME", "EITHER_TEAM_NO_PRIOR_GAME"
    }


def test_transition_reconstruction_handles_same_half_and_half_switch():
    frame = pd.DataFrame([
        {"canonicalPaId": "p1", "plate_appearance_id": "retrosheet:pa:g:1", "canonicalGameId": "g", "game_id": "rg", "game_date": "2023-04-01", "season": 2023, "outcome": "SINGLE", "context_inning": 1, "context_top_bottom": 0, "context_outs_before": 0, "context_base_mask_before": 0, "context_batting_score_diff_before": 0},
        {"canonicalPaId": "p2", "plate_appearance_id": "retrosheet:pa:g:2", "canonicalGameId": "g", "game_id": "rg", "game_date": "2023-04-01", "season": 2023, "outcome": "BIP_OUT", "context_inning": 1, "context_top_bottom": 0, "context_outs_before": 0, "context_base_mask_before": 1, "context_batting_score_diff_before": 0},
        {"canonicalPaId": "p3", "plate_appearance_id": "retrosheet:pa:g:3", "canonicalGameId": "g", "game_id": "rg", "game_date": "2023-04-01", "season": 2023, "outcome": "STRIKEOUT", "context_inning": 1, "context_top_bottom": 0, "context_outs_before": 2, "context_base_mask_before": 0, "context_batting_score_diff_before": 0},
        {"canonicalPaId": "p4", "plate_appearance_id": "retrosheet:pa:g:4", "canonicalGameId": "g", "game_id": "rg", "game_date": "2023-04-01", "season": 2023, "outcome": "STRIKEOUT", "context_inning": 1, "context_top_bottom": 1, "context_outs_before": 0, "context_base_mask_before": 0, "context_batting_score_diff_before": 0},
    ])
    transitions, ledger = reconstruct_transitions(frame)
    assert len(transitions) == 3
    assert ledger["excludedByReason"] == {"TERMINAL_PA_NO_SUCCESSOR_STATE": 1}
    assert transitions.iloc[0]["base_mask_after"] == 1
    assert transitions.iloc[2]["outs_after"] == 3


def test_simulator_spec_fails_closed_without_oracle_participants():
    spec = simulator_specification(_comparison())
    assert spec["simulationProtocol"]["v18GamesSimulated"] == 0
    assert spec["participants"]["oracleAnalysisRun"] is False
    assert spec["blockedEvaluation"]["game"] is True


def test_published_transition_foundation_separates_fit_and_evaluation_coverage():
    result = json.loads((BASELINE_ROOT / "results.json").read_text(encoding="utf-8"))
    evidence = json.loads((BASELINE_ROOT / "transition-evaluation.json").read_text(encoding="utf-8"))
    assert result["paEstimatorFits"] == result["calibrationFits"] == 0
    assert result["transitionFoldsScheduled"] == 5
    assert result["transitionFoldsFit"] == 4
    assert result["transitionFoldsEvaluated"] == 3
    assert [row["foldNumber"] for row in evidence["folds"] if row["evaluationCompleted"]] == [1, 2, 3]
    assert evidence["folds"][3]["status"].startswith("FIT_COMPLETE_EVALUATION_BLOCKED")
    assert evidence["folds"][4]["transitionEstimatorFitStarted"] is False
    for fold in evidence["folds"][:3]:
        assert fold["evaluation"]["model"]["topTransitionExpectedCalibrationError"] >= 0.0
        assert sum(row["observations"] for row in fold["evaluation"]["model"]["topTransitionReliabilityBands"]) == fold["reconstructedEligibleValidationTransitions"]
