"""Governed whole-game scoring, reconciliation, and blocked public readiness."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
import shutil
import uuid

import numpy as np
import pytest

from server.persistence.db import Database
from server.persistence.repositories.project_repository import ProjectRepository
from server.persistence.repositories.run_repository import RunRepository
from server.sports_current_statcast import stage3_game_scoring as gs
from server.sports_current_statcast.stage3_game_inputs import build_stage3_game_inputs
from server.sports_current_statcast.stage3_game_probability_adapter import (
    FINAL_DEVELOPMENT_MODEL,
    FOLD_VALIDATION_MODEL,
    VerifiedStage3ArtifactBinding,
)
from server.sports_current_statcast.stage3_model_laboratory import EXPECTED_PROJECT_ID
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5 import whole_game_monte_carlo as mc
from tests.sports_stage3_game_inputs_test import evidence, feature_order


PROBABILITIES = np.array([0.225, 0.085, 0.033, 0.140, 0.045, 0.005, 0.440, 0.027])
PROBABILITIES /= PROBABILITIES.sum()


class ConstantPipeline:
    ordered_features = feature_order()
    target_order = PA_CLASS_ORDER

    def predict_proba(self, frame):
        assert tuple(frame.columns) == self.ordered_features
        return np.repeat(PROBABILITIES[None, :], len(frame), axis=0)


def game_inputs():
    return build_stage3_game_inputs(evidence(), ordered_features=feature_order())


def artifact(*, role=FOLD_VALIDATION_MODEL):
    return VerifiedStage3ArtifactBinding(
        artifact_id="stage3-artifact-fixture",
        manifest_sha256="a" * 64,
        model_sha256="b" * 64,
        feature_set_checksum="c" * 64,
        ordered_features=feature_order(),
        target_order=PA_CLASS_ORDER,
        pipeline=ConstantPipeline(),
        model_role=role,
        training_end_date="2026-05-01" if role == FOLD_VALIDATION_MODEL else "2026-08-13",
        fold_number=5 if role == FOLD_VALIDATION_MODEL else None,
        validation_start_date="2026-05-02" if role == FOLD_VALIDATION_MODEL else None,
        validation_end_date="2026-08-13" if role == FOLD_VALIDATION_MODEL else None,
    )


def tiny_sampler() -> mc.FastTransitionSampler:
    records = [
        {
            "pa_outcome": outcome,
            "outs_before": 0,
            "base_mask_before": 0,
            "outs_after": 1,
            "base_mask_after": 0,
            "runs_scored": 0,
            "season": 2021,
        }
        for outcome in bt.PA_CLASSES
    ]
    return mc.FastTransitionSampler(
        bt.fit(records, alpha=0.5, min_cell=1, seasons=(2021,))
    )


def simulator_result() -> mc.GameSimResult:
    away = np.array([1, 4, 2, 5, 0, 3], dtype=np.int64)
    home = np.array([3, 2, 5, 1, 2, 4], dtype=np.int64)
    return mc.GameSimResult(
        game_id="fixture-game",
        n_sims=6,
        away_runs=away,
        home_runs=home,
        innings=np.array([9, 9, 10, 9, 11, 9], dtype=np.int64),
        pa_counts=np.array([70, 72, 78, 69, 81, 74], dtype=np.int64),
        home_win=home > away,
        nonterminated=0,
        illegal_states=0,
        first_five_away_runs=np.array([1, 2, 1, 3, 0, 1], dtype=np.int64),
        first_five_home_runs=np.array([2, 1, 2, 0, 1, 1], dtype=np.int64),
    )


def test_distribution_outputs_reconcile_joint_margins_totals_wins_and_first_five():
    result = simulator_result()
    output = gs.build_game_distribution_output(result)

    assert output["reconciliation"]["status"] == "PASSED"
    assert sum(row["probability"] for row in output["jointScoreDistribution"]) == pytest.approx(1.0)
    assert output["expectedAwayRuns"] == pytest.approx(result.away_runs.mean())
    assert output["expectedHomeRuns"] == pytest.approx(result.home_runs.mean())
    assert output["homeWinProbability"] + output["awayWinProbability"] == pytest.approx(1.0)
    assert (
        output["firstFive"]["homeWinProbability"]
        + output["firstFive"]["awayWinProbability"]
        + output["firstFive"]["tieProbability"]
        == pytest.approx(1.0)
    )


def test_reconciliation_rejects_tampered_distribution():
    result = simulator_result()
    output = gs.build_game_distribution_output(result)
    tampered = copy.deepcopy(output)
    tampered["jointScoreDistribution"][0]["count"] += 1

    with pytest.raises(gs.Stage3GameScoringError) as raised:
        gs.reconcile_game_distribution_output(result, tampered)
    assert raised.value.code == "JOINT_SCORE_RECONCILIATION_FAILED"


def test_historical_games_require_the_containing_fold_and_final_model_is_prospective_only():
    inputs = game_inputs()
    usage = gs.validate_scoring_model_usage(
        inputs, artifact(), scoring_mode=gs.HISTORICAL_OOF_SCORING
    )
    assert usage["foldModelUsed"] == "FOLD_5"

    with pytest.raises(gs.Stage3GameScoringError) as raised:
        gs.validate_scoring_model_usage(
            inputs,
            artifact(role=FINAL_DEVELOPMENT_MODEL),
            scoring_mode=gs.HISTORICAL_OOF_SCORING,
        )
    assert raised.value.code == "HISTORICAL_OOF_REQUIRES_FOLD_PIPELINE"

    with pytest.raises(gs.Stage3GameScoringError) as raised:
        gs.validate_scoring_model_usage(
            inputs,
            artifact(role=FINAL_DEVELOPMENT_MODEL),
            scoring_mode=gs.PROSPECTIVE_SCORING,
        )
    assert raised.value.code == "FINAL_MODEL_RETROSPECTIVE_USE_PROHIBITED"


def test_final_oot_is_rejected_before_any_model_usage():
    inputs = replace(
        game_inputs(),
        game_date="2026-08-20",
        scheduled_first_pitch="2026-08-20T17:00:00Z",
    )
    with pytest.raises(gs.Stage3GameScoringError) as raised:
        gs.validate_scoring_model_usage(
            inputs, artifact(), scoring_mode=gs.HISTORICAL_OOF_SCORING
        )
    assert raised.value.code == "FINAL_OOT_SCORING_PROHIBITED"


def test_end_to_end_simulation_is_fixed_seed_reproducible_and_hash_bound():
    sampler = tiny_sampler()
    sampler_sha = gs.transition_sampler_sha256(sampler)
    common = {
        "transition_sampler": sampler,
        "transition_model_sha256": sampler_sha,
        "expected_transition_model_sha256": sampler_sha,
        "draws": 64,
        "seed": 20260903,
        "scoring_mode": gs.HISTORICAL_OOF_SCORING,
    }
    first = gs.score_governed_game(game_inputs(), artifact(), **common).record()
    second = gs.score_governed_game(game_inputs(), artifact(), **common).record()

    assert first == second
    assert first["foldModelUsed"] == "FOLD_5"
    assert first["reconciliation"]["status"] == "PASSED"
    assert first["transitionModelSha256"] == sampler_sha
    assert first["externalProviderCalls"] == 0
    assert first["actualTargetOutcomesRead"] is False
    assert len(first["scoringReceiptSha256"]) == 64


def test_transition_authority_mismatch_stops_before_simulation():
    sampler = tiny_sampler()
    with pytest.raises(gs.Stage3GameScoringError) as raised:
        gs.score_governed_game(
            game_inputs(),
            artifact(),
            transition_sampler=sampler,
            transition_model_sha256="d" * 64,
            expected_transition_model_sha256="d" * 64,
            draws=32,
            seed=1,
            scoring_mode=gs.HISTORICAL_OOF_SCORING,
        )
    assert raised.value.code == "SIMULATOR_TRANSITION_AUTHORITY_MISMATCH"


def test_transition_sampler_digest_changes_with_actual_sampler_content():
    sampler = tiny_sampler()
    before = gs.transition_sampler_sha256(sampler)
    sampler._trans[0] = sampler._trans[0].copy()
    sampler._trans[0][0, 2] += 1

    after = gs.transition_sampler_sha256(sampler)

    assert before != after


def test_public_summary_and_enqueue_are_provider_free_and_fail_closed():
    # Ordinary mkdir inherits the test worker ACL on Windows; pytest's tmp_path may not.
    root = Path.cwd() / f".stage3-game-scoring-test-{uuid.uuid4().hex}"
    root.mkdir()
    try:
        database = Database(root / "game-scoring.sqlite")
        database.initialize()
        ProjectRepository(database).upsert(
            {
                "project_id": EXPECTED_PROJECT_ID,
                "project_name": "MLB 2026 Current-Data Game Forecast Challenger",
                "owner_user_id": "user-1",
            }
        )

        summary = gs.game_scoring_summary(database, EXPECTED_PROJECT_ID)
        assert summary["games"] == []
        assert summary["currentJob"] is None
        assert summary["results"] == []
        assert summary["readiness"]["ready"] is False
        assert summary["activity"] == {
            "providerCalls": 0,
            "finalOotTargetAccessed": False,
            "actualTargetOutcomesRead": False,
            "gamesDiscovered": 0,
            "jobs": [],
        }

        with pytest.raises(gs.Stage3GameScoringError) as raised:
            gs.enqueue_game_scoring_job(
                database,
                EXPECTED_PROJECT_ID,
                {
                    "artifactId": "stage3-artifact-fixture",
                    "gameIds": ["mlb:game:future"],
                    "draws": 10_000,
                    "seed": 7,
                },
                actor_user_id="user-1",
            )
        assert raised.value.status_code == 409
        assert raised.value.code == "GOVERNED_PREGAME_LINEUP_STARTER_AUTHORITY_UNAVAILABLE"
        assert [
            row
            for row in RunRepository(database).list_for_project(EXPECTED_PROJECT_ID)
            if row.get("run_type") == gs.GAME_SCORING_JOB_TYPE
        ] == []
    finally:
        shutil.rmtree(root, ignore_errors=True)
