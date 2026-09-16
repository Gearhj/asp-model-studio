from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from server.sports_nfl_m1.distributions import (
    PairedResidualAuthority,
    ScoreDistributionError,
    make_common_random_numbers,
    reconcile_score_simulation,
    simulate_joint_scores,
    summarize_game_distribution,
)
from server.sports_nfl_m1.ensemble import (
    EnsembleError,
    cross_fitted_convex_blend,
    cross_fitted_meta_predictions,
    fit_convex_blend,
)
from server.sports_nfl_m1.metrics import (
    binary_probability_metrics,
    distribution_metrics,
    empirical_crps,
    line_event_metrics,
    paired_whole_game_bootstrap,
    quantile_calibration_table,
    score_point_metrics,
)


def _authority() -> PairedResidualAuthority:
    return PairedResidualAuthority.fit(
        actual_home=[24, 17, 31, 10, 27, 20],
        actual_away=[20, 24, 14, 13, 30, 17],
        predicted_home=[21, 21, 24, 17, 23, 21],
        predicted_away=[21, 21, 20, 17, 24, 20],
        row_ids=[f"train-{index}" for index in range(6)],
        row_dates=[f"2024-09-{index + 1:02d}" for index in range(6)],
        training_end="2024-12-31",
    )


def test_residual_authority_is_training_only_paired_and_immutable() -> None:
    authority = _authority()
    assert authority.row_count == 6
    assert abs(float(authority.home.mean())) < 1e-12
    assert abs(float(authority.away.mean())) < 1e-12
    assert len(authority.sha256) == 64
    with pytest.raises(ValueError):
        authority.home[0] = 99
    with pytest.raises(FrozenInstanceError):
        authority.training_end = "2025-12-31"  # type: ignore[misc]
    with pytest.raises(ScoreDistributionError, match="after training_end"):
        PairedResidualAuthority.fit(
            actual_home=[20, 21],
            actual_away=[17, 18],
            predicted_home=[20, 20],
            predicted_away=[18, 18],
            row_ids=["dev", "oot"],
            row_dates=["2024-12-31", "2025-01-01"],
            training_end="2024-12-31",
        )


def test_joint_simulation_is_reproducible_reconciled_and_preserves_dependence() -> None:
    authority = _authority()
    randoms = make_common_random_numbers(n_games=2, draws=4_000, seed=77)
    first = simulate_joint_scores(
        predicted_home_mean=[23.5, 20.0],
        predicted_away_mean=[20.5, 24.0],
        residual_authority=authority,
        draws=4_000,
        common_random_numbers=randoms,
    )
    second = simulate_joint_scores(
        predicted_home_mean=[23.5, 20.0],
        predicted_away_mean=[20.5, 24.0],
        residual_authority=authority,
        draws=4_000,
        common_random_numbers=randoms,
    )
    assert np.array_equal(first.home, second.home)
    assert np.array_equal(first.away, second.away)
    proof = reconcile_score_simulation(first)
    assert proof["minimumJointMass"] == pytest.approx(1.0)
    assert np.corrcoef(first.home[0], first.away[0])[0, 1] != pytest.approx(0.0)


def test_common_random_numbers_align_candidate_comparisons() -> None:
    authority = _authority()
    randoms = make_common_random_numbers(n_games=1, draws=1_000, seed=91)
    low = simulate_joint_scores(
        predicted_home_mean=[20],
        predicted_away_mean=[19],
        residual_authority=authority,
        draws=1_000,
        common_random_numbers=randoms,
    )
    high = simulate_joint_scores(
        predicted_home_mean=[23],
        predicted_away_mean=[19],
        residual_authority=authority,
        draws=1_000,
        common_random_numbers=randoms,
    )
    # Integer-shifted means plus identical residual/round draws produce a paired shift.
    assert np.array_equal(high.home - low.home, np.full((1, 1_000), 3))
    assert np.array_equal(high.away, low.away)


def test_game_summary_reconciles_win_spread_total_and_joint_mass() -> None:
    simulation = simulate_joint_scores(
        predicted_home_mean=[24],
        predicted_away_mean=[20],
        residual_authority=_authority(),
        draws=2_000,
        seed=3,
    )
    summary = summarize_game_distribution(
        simulation, 0, home_spread=-3.0, total_line=44.0
    )
    assert (
        summary["homeWinProbability"]
        + summary["awayWinProbability"]
        + summary["tieProbability"]
    ) == pytest.approx(1.0)
    assert (
        summary["homeCoverProbability"]
        + summary["awayCoverProbability"]
        + summary["spreadPushProbability"]
    ) == pytest.approx(1.0)
    assert (
        summary["overProbability"]
        + summary["underProbability"]
        + summary["totalPushProbability"]
    ) == pytest.approx(1.0)
    assert sum(simulation.joint_pmf(0).values()) == pytest.approx(1.0)
    assert summary["overtimeProbability"] is None


def test_probability_point_and_distribution_metrics_are_finite() -> None:
    probability = binary_probability_metrics([1, 0, 1, 0], [0.8, 0.3, 0.7, 0.1])
    assert 0 < probability["logLoss"] < 1
    assert 0 <= probability["ece"] <= 1
    assert probability["calibrationStatus"] in {"COMPLETE", "OPTIMIZATION_FAILED"}
    point = score_point_metrics(
        actual_home=[24, 17],
        actual_away=[20, 21],
        predicted_home=[23, 19],
        predicted_away=[21, 20],
    )
    assert point["homePointsMae"] == pytest.approx(1.5)
    simulation = simulate_joint_scores(
        predicted_home_mean=[23, 19],
        predicted_away_mean=[21, 20],
        residual_authority=_authority(),
        draws=2_000,
        seed=11,
    )
    metrics = distribution_metrics(
        simulation, actual_home=[24, 17], actual_away=[20, 21]
    )
    assert np.isfinite(metrics["jointScoreNegativeLogLikelihood"])
    assert 0 <= metrics["interval"]["totalPointsCoverage"] <= 1
    assert all(np.isfinite(list(metrics["crps"].values())))


def test_crps_is_zero_for_perfect_degenerate_distribution() -> None:
    assert empirical_crps([17, 17, 17], 17) == pytest.approx(0.0)
    table = quantile_calibration_table([[17, 17], [20, 20]], [17, 20])
    assert len(table) == 5
    assert all(row["observedAtOrBelow"] == 1.0 for row in table)


def test_line_metrics_report_pushes_without_forcing_binary_outcomes() -> None:
    simulation = simulate_joint_scores(
        predicted_home_mean=[24, 21, 27],
        predicted_away_mean=[20, 20, 23],
        residual_authority=_authority(),
        draws=1_000,
        seed=17,
    )
    result = line_event_metrics(
        simulation,
        actual_home=[24, 20, 28],
        actual_away=[20, 20, 21],
        home_spread=[-4, 1.5, -3.5],
        total_line=[44, 41.5, 49.5],
    )
    assert result["homeCover"]["pushRows"] == 1
    assert result["homeCover"]["eligibleRows"] == 2
    assert result["over"]["pushRows"] == 1


def test_paired_bootstrap_is_seeded_and_resamples_whole_game_differences() -> None:
    candidate = np.asarray([0.1, 0.2, 0.3, 0.4])
    baseline = np.asarray([0.2, 0.3, 0.4, 0.5])
    first = paired_whole_game_bootstrap(candidate, baseline, resamples=500, seed=8)
    second = paired_whole_game_bootstrap(candidate, baseline, resamples=500, seed=8)
    assert first == second
    assert first["pointEstimate"] == pytest.approx(-0.1)
    assert first["lower"] == pytest.approx(-0.1)
    assert first["upper"] == pytest.approx(-0.1)


def test_convex_blend_weights_are_bounded_and_sum_to_one() -> None:
    base = np.asarray([[0.2, 0.8], [0.4, 0.6], [0.8, 0.2], [0.7, 0.3]])
    truth = np.asarray([0, 0, 1, 1])
    blend = fit_convex_blend(base, truth, objective="binary_log_loss")
    assert sum(blend.weights) == pytest.approx(1.0)
    assert all(0 <= weight <= 1 for weight in blend.weights)
    assert np.all((blend.predict(base) >= 0) & (blend.predict(base) <= 1))
    single = fit_convex_blend(base[:, :1], truth, objective="mse")
    assert single.weights == (1.0,)


def test_cross_fitted_blend_never_uses_validation_fold_labels() -> None:
    base = np.asarray(
        [
            [0.1, 0.9],
            [0.2, 0.8],
            [0.8, 0.2],
            [0.9, 0.1],
            [0.3, 0.7],
            [0.7, 0.3],
        ]
    )
    truth = np.asarray([0, 0, 1, 1, 0, 1])
    folds = np.asarray([1, 1, 2, 2, 3, 3])
    result = cross_fitted_convex_blend(base, truth, folds, objective="binary_log_loss")
    assert np.isfinite(result.predictions).all()
    for held_out, training in result.training_folds_by_validation_fold.items():
        assert held_out not in training
    with pytest.raises(EnsembleError, match="disjoint"):
        cross_fitted_convex_blend(
            base,
            truth,
            folds,
            training_folds_by_validation_fold={1: [1], 2: [1], 3: [1]},
        )


class _TrainingMeanEstimator:
    def fit(self, features: np.ndarray, target: np.ndarray) -> "_TrainingMeanEstimator":
        self.value = float(np.mean(target))
        return self

    def predict(self, features: np.ndarray) -> np.ndarray:
        return np.repeat(self.value, features.shape[0])


def test_generic_meta_stacker_is_fresh_and_cross_fitted() -> None:
    features = np.arange(12, dtype=float).reshape(6, 2)
    truth = np.asarray([0, 0, 1, 1, 1, 1], dtype=float)
    folds = np.asarray([1, 1, 2, 2, 3, 3])
    result = cross_fitted_meta_predictions(
        features,
        truth,
        folds,
        estimator_factory=_TrainingMeanEstimator,
    )
    # Fold 1 predictions use folds 2+3 only, never fold 1 labels.
    assert np.all(result.predictions[folds == 1] == 1.0)
    # Fold 3 predictions use folds 1+2 only (mean 0.5), never fold 3 labels.
    assert np.all(result.predictions[folds == 3] == 0.5)
    assert result.training_rows_by_validation_fold == {1: 4, 2: 4, 3: 4}
