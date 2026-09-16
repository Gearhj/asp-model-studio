from __future__ import annotations

import numpy as np
import pytest

from server.sports_current_statcast import stage3_prior_estimators_v2 as estimators


def test_two_cell_adapter_is_beta_binomial_and_reliability_increases() -> None:
    fitted = estimators.fit_beta_binomial(
        [1, 3, 8],
        [2, 10, 10],
        family_id="TEST_WHIFF",
        success_cell="WHIFF",
        failure_cell="CONTACT",
    )
    assert fitted["alpha"] == fitted["priorAlpha"][0]
    assert fitted["beta"] == fitted["priorAlpha"][1]
    assert fitted["priorMean"] == fitted["alpha"] / (
        fitted["alpha"] + fitted["beta"]
    )
    posterior = estimators.dirichlet_posterior(
        [[0, 0], [1, 1], [8, 2]], [0, 2, 10], fitted
    )
    assert posterior["posteriorMean"][0, 0] == pytest.approx(
        fitted["priorMean"]
    )
    assert posterior["reliability"][0] == 0
    assert posterior["reliability"][1] < posterior["reliability"][2]
    assert np.all((posterior["posteriorMean"] >= 0) & (posterior["posteriorMean"] <= 1))
    assert np.allclose(posterior["posteriorMean"].sum(axis=1), 1.0)

    direct = estimators.fit_dirichlet_multinomial(
        [[1, 1], [3, 7], [8, 2]],
        [2, 10, 10],
        family_id="TEST_WHIFF",
        cell_names=["WHIFF", "CONTACT"],
    )
    assert fitted["priorAlpha"] == direct["priorAlpha"]
    assert fitted["priorComposition"] == direct["priorComposition"]
    assert fitted["priorConcentration"] == direct["priorConcentration"]
    direct_posterior = estimators.dirichlet_posterior(
        [[0, 0], [1, 1], [8, 2]], [0, 2, 10], direct
    )
    assert np.array_equal(
        posterior["posteriorMean"], direct_posterior["posteriorMean"]
    )
    assert np.array_equal(
        posterior["posteriorVariance"], direct_posterior["posteriorVariance"]
    )


def test_two_cell_rejects_success_above_trial_and_noninteger() -> None:
    with pytest.raises(estimators.PriorEstimatorV2Error) as above:
        estimators.fit_beta_binomial(
            [3], [2], family_id="X", success_cell="A", failure_cell="B"
        )
    assert above.value.code == "ESTIMATOR_BINOMIAL_RECONCILIATION_FAILED"
    with pytest.raises(estimators.PriorEstimatorV2Error) as noninteger:
        estimators.fit_beta_binomial(
            [1.5], [2], family_id="X", success_cell="A", failure_cell="B"
        )
    assert noninteger.value.code == "ESTIMATOR_COUNT_DOMAIN_INVALID"


def test_four_cell_dirichlet_retains_residual_and_reconciles_simplex() -> None:
    counts = np.asarray([[70, 20, 5, 5], [40, 30, 20, 10], [0, 0, 0, 0]])
    fitted = estimators.fit_dirichlet_multinomial(
        counts[:2],
        [100, 100],
        family_id="PITCH_COMPOSITION",
        cell_names=["FASTBALL", "BREAKING", "OFFSPEED", "OTHER"],
    )
    assert len(fitted["priorAlpha"]) == 4
    assert fitted["priorComposition"][3] > 0
    posterior = estimators.dirichlet_posterior(counts, [100, 100, 0], fitted)
    assert np.allclose(posterior["posteriorMean"].sum(axis=1), 1.0, atol=1e-14)
    assert posterior["posteriorMean"][0, 3] > 0
    assert np.allclose(
        posterior["posteriorCovariance"],
        np.swapaxes(posterior["posteriorCovariance"], 1, 2),
    )


def test_dirichlet_rejects_dropped_or_negative_component() -> None:
    with pytest.raises(estimators.PriorEstimatorV2Error) as mismatch:
        estimators.fit_dirichlet_multinomial(
            [[5, 2, 1, 0]],
            [10],
            family_id="PITCH",
            cell_names=["A", "B", "C", "D"],
        )
    assert mismatch.value.code == "ESTIMATOR_COMPOSITION_RECONCILIATION_FAILED"
    with pytest.raises(estimators.PriorEstimatorV2Error) as negative:
        estimators.fit_dirichlet_multinomial(
            [[5, 2, -1, 4]],
            [10],
            family_id="PITCH",
            cell_names=["A", "B", "C", "D"],
        )
    assert negative.value.code == "ESTIMATOR_COUNT_DOMAIN_INVALID"


def test_five_cell_posterior_avg_and_slg_are_linear_contrasts() -> None:
    fitted = estimators.fit_dirichlet_multinomial(
        [[10, 3, 1, 2, 24], [8, 4, 0, 1, 27]],
        [40, 40],
        family_id="BATTING",
        cell_names=["1B", "2B", "3B", "HR", "OUT"],
    )
    posterior = estimators.dirichlet_posterior(
        [[10, 3, 1, 2, 24]], [40], fitted
    )
    composition = posterior["posteriorMean"][0]
    avg = composition[:4].sum()
    slg = composition @ np.asarray([1.0, 2.0, 3.0, 4.0, 0.0])
    assert avg == pytest.approx(1.0 - composition[4])
    assert slg >= avg


def test_gamma_poisson_preserves_whip_formula_and_shrinks_without_clipping() -> None:
    fitted = estimators.fit_gamma_poisson_components(
        [[20, 10], [40, 20], [3, 2]],
        [100, 200, 20],
        family_id="WHIP",
        component_names=["H", "BB"],
    )
    posterior = estimators.gamma_poisson_posterior(
        [[20, 10], [8, 4], [0, 0]], [100, 4, 0], fitted
    )
    whip = 3.0 * posterior["posteriorMean"].sum(axis=1)
    raw_extreme = 3.0 * (8 + 4) / 4
    assert whip[1] < raw_extreme
    assert whip[1] > 0
    assert whip[2] == pytest.approx(3.0 * sum(fitted["priorComponentMean"]))
    assert posterior["reliability"][2] == 0
    expected_means = (
        np.asarray([[20, 10], [8, 4], [0, 0]], dtype=np.float64)
        + np.asarray(fitted["priorShape"])[None, :]
    ) / (
        np.asarray([100, 4, 0], dtype=np.float64)[:, None]
        + float(fitted["priorRate"])
    )
    assert np.array_equal(posterior["posteriorMean"], expected_means)


def test_gamma_poisson_rejects_positive_counts_at_zero_exposure() -> None:
    fitted = estimators.fit_gamma_poisson_components(
        [[2, 1], [4, 2]],
        [10, 20],
        family_id="WHIP",
        component_names=["H", "BB"],
    )
    with pytest.raises(estimators.PriorEstimatorV2Error) as error:
        estimators.gamma_poisson_posterior([[1, 0]], [0], fitted)
    assert error.value.code == "ESTIMATOR_GAMMA_POISSON_INPUT_INVALID"


def test_normal_sufficient_statistics_and_n_zero_one_behavior() -> None:
    stats = estimators.normal_sufficient_statistics(
        [0, 1, 3], [0.0, 95.0, 285.0], [0.0, 9025.0, 27077.0]
    )
    assert np.isnan(stats["sampleMean"][0])
    assert stats["sampleMean"][1] == 95.0
    assert np.isnan(stats["sampleVariance"][1])
    assert stats["sampleVariance"][2] == pytest.approx(1.0)
    fitted = estimators.fit_normal_normal(
        [2, 3, 4],
        [180.0, 285.0, 400.0],
        [16250.0, 27077.0, 40006.0],
        family_id="VELOCITY",
    )
    posterior = estimators.normal_normal_posterior(
        [0, 1, 3], [0.0, 110.0, 285.0], [0.0, 12100.0, 27077.0], fitted
    )
    assert posterior["reliability"][0] == 0
    assert posterior["posteriorMean"][0] == fitted["populationMean"]
    assert posterior["sampleMean"][1] == 110.0
    assert posterior["posteriorMean"][1] < 110.0
    assert posterior["posteriorMean"][1] > fitted["populationMean"]
    expected_reliability = (
        1.0 * fitted["governedBetweenPlayerVariance"]
        / (
            fitted["governedBetweenPlayerVariance"]
            + fitted["pooledWithinPlayerVariance"]
        )
    )
    assert posterior["reliability"][1] == pytest.approx(expected_reliability)
    assert posterior["posteriorMean"][1] == pytest.approx(
        expected_reliability * 110.0
        + (1.0 - expected_reliability) * fitted["populationMean"]
    )


def test_normal_tiny_negative_css_clamps_but_material_negative_fails() -> None:
    tiny = np.nextafter(2.0, 0.0)
    stats = estimators.normal_sufficient_statistics([2], [2.0], [tiny])
    assert stats["centeredSumSquares"][0] == 0.0
    assert bool(stats["tinyNegativeCssClamped"][0])
    with pytest.raises(estimators.PriorEstimatorV2Error) as error:
        estimators.normal_sufficient_statistics([2], [2.0], [1.0])
    assert error.value.code == "ESTIMATOR_NORMAL_NEGATIVE_VARIANCE"
    with pytest.raises(estimators.PriorEstimatorV2Error) as singleton:
        estimators.normal_sufficient_statistics([1], [90.0], [10000.0])
    assert singleton.value.code == "ESTIMATOR_NORMAL_SINGLETON_RECONCILIATION_FAILED"
    exact_singleton = estimators.normal_sufficient_statistics(
        [1], [90.0], [8100.0]
    )
    assert exact_singleton["centeredSumSquares"][0] == 0.0
    assert bool(exact_singleton["singletonCssClamped"][0])


def test_all_fitters_are_order_and_thread_limit_deterministic() -> None:
    from threadpoolctl import threadpool_limits

    counts = np.asarray([[7, 2, 1, 0], [3, 3, 2, 2], [5, 1, 3, 1]])
    totals = np.asarray([10, 10, 10])
    first = estimators.fit_dirichlet_multinomial(
        counts,
        totals,
        family_id="ORDER",
        cell_names=["A", "B", "C", "D"],
    )
    second = estimators.fit_dirichlet_multinomial(
        counts[::-1],
        totals[::-1],
        family_id="ORDER",
        cell_names=["A", "B", "C", "D"],
    )
    assert first == second

    success = np.asarray([2, 7, 4], dtype=np.float64)
    gamma_counts = np.asarray([[8, 3], [2, 1], [11, 4]], dtype=np.float64)
    normal_n = np.asarray([3, 5, 2], dtype=np.float64)
    normal_sum = np.asarray([279.0, 470.0, 190.0], dtype=np.float64)
    normal_sumsq = np.asarray([25949.0, 44190.0, 18052.0], dtype=np.float64)

    def fitted_set(limit: int, reverse: bool) -> tuple[dict, dict, dict]:
        order = np.asarray([2, 1, 0]) if reverse else np.asarray([0, 1, 2])
        with threadpool_limits(limits=limit):
            beta = estimators.fit_beta_binomial(
                success[order], totals[order], family_id="BETA_ORDER",
                success_cell="YES", failure_cell="NO",
            )
            gamma = estimators.fit_gamma_poisson_components(
                gamma_counts[order], totals[order], family_id="GAMMA_ORDER",
                component_names=["A", "B"],
            )
            normal = estimators.fit_normal_normal(
                normal_n[order], normal_sum[order], normal_sumsq[order],
                family_id="NORMAL_ORDER",
            )
        return beta, gamma, normal

    assert fitted_set(1, False) == fitted_set(4, True)
