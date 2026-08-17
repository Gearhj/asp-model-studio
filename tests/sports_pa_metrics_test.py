from __future__ import annotations

import json
import math
import unittest

import numpy as np

from server.sports_modeling import (
    CALIBRATION_RETENTION_TOLERANCE,
    DEFAULT_BOOTSTRAP_RESAMPLES,
    PA_CLASS_ORDER,
    encode_labels,
    evaluate_multiclass,
    fit_temperature_scaling,
    game_cluster_bootstrap,
    per_row_log_loss,
    temperature_scale,
    validate_probability_matrix,
)


def probabilities_with_true_class_confidence(
    labels: np.ndarray, confidence: float | np.ndarray
) -> np.ndarray:
    values = np.asarray(confidence, dtype=np.float64)
    if values.ndim == 0:
        values = np.full(labels.size, float(values))
    probabilities = np.empty((labels.size, len(PA_CLASS_ORDER)), dtype=np.float64)
    for row, (label, row_confidence) in enumerate(zip(labels, values, strict=True)):
        probabilities[row] = (1.0 - row_confidence) / (len(PA_CLASS_ORDER) - 1)
        probabilities[row, label] = row_confidence
    return probabilities


class SportsPaMetricsTests(unittest.TestCase):
    def test_frozen_class_order_and_strict_probability_validation(self) -> None:
        self.assertEqual(
            PA_CLASS_ORDER,
            (
                "STRIKEOUT",
                "WALK_HBP_CI",
                "HOME_RUN",
                "SINGLE",
                "DOUBLE",
                "TRIPLE",
                "BIP_OUT",
                "OTHER_REACH",
            ),
        )
        valid = np.full((2, 8), 0.125)
        np.testing.assert_array_equal(validate_probability_matrix(valid), valid)

        invalid_cases = [
            np.full((2, 7), 1.0 / 7.0),
            np.full((2, 8), 0.1),
            np.asarray([[np.nan, *([1.0 / 7.0] * 7)]]),
            np.asarray([[-0.1, 1.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]),
            np.ones(8),
        ]
        for invalid in invalid_cases:
            with self.subTest(shape=invalid.shape), self.assertRaises(
                (TypeError, ValueError)
            ):
                validate_probability_matrix(invalid)

        with self.assertRaises(ValueError):
            validate_probability_matrix(valid, class_order=tuple(reversed(PA_CLASS_ORDER)))
        with self.assertRaises(TypeError):
            encode_labels([True, False])
        with self.assertRaises(ValueError):
            encode_labels(["STRIKEOUT", "NOT_A_CLASS"])

    def test_metrics_preserve_summed_brier_and_fixed_order_evidence(self) -> None:
        labels = np.arange(8, dtype=np.int64)
        probabilities = probabilities_with_true_class_confidence(labels, 0.93)
        evidence = evaluate_multiclass(labels, probabilities, n_bins=5)
        json.dumps(evidence, allow_nan=False)

        self.assertEqual(evidence["classOrder"], list(PA_CLASS_ORDER))
        self.assertEqual(evidence["rowCount"], 8)
        self.assertAlmostEqual(evidence["logLoss"], -math.log(0.93))
        self.assertAlmostEqual(evidence["brierScore"], 0.0056)
        self.assertEqual(evidence["brierDefinition"], "MEAN_SUMMED_ONE_VS_ALL_SQUARED_ERROR")
        self.assertEqual(evidence["top1Accuracy"], 1.0)
        self.assertEqual(evidence["balancedAccuracy"], 1.0)
        self.assertEqual(evidence["macroF1"], 1.0)
        self.assertEqual(evidence["weightedF1"], 1.0)
        self.assertEqual(evidence["confusionMatrix"], np.eye(8, dtype=int).tolist())

        for class_name in PA_CLASS_ORDER:
            self.assertAlmostEqual(evidence["realizedPrevalence"][class_name], 0.125)
            self.assertAlmostEqual(evidence["predictedPrevalence"][class_name], 0.125)
            self.assertAlmostEqual(evidence["classwiseBrier"][class_name], 0.0007)
            self.assertEqual(
                sum(
                    item["count"]
                    for item in evidence["classwiseReliability"][class_name]
                ),
                8,
            )
            self.assertEqual(
                sum(
                    item["count"]
                    for item in evidence["probabilityHistograms"][class_name]
                ),
                8,
            )
        self.assertEqual(
            sum(item["count"] for item in evidence["topLabelReliability"]), 8
        )

    def test_temperature_scaling_uses_only_2024_and_retains_improvement(self) -> None:
        labels = np.tile(np.arange(8, dtype=np.int64), 10)
        probabilities = np.full((labels.size, 8), 0.15 / 7.0)
        for row, label in enumerate(labels):
            predicted = label if row % 4 else (label + 1) % 8
            probabilities[row, predicted] = 0.85

        result = fit_temperature_scaling(
            labels,
            probabilities,
            source_seasons=np.full(labels.size, 2024, dtype=np.int64),
        )
        self.assertTrue(result.optimizer_success)
        self.assertTrue(result.retained)
        self.assertGreater(result.fitted_temperature, 1.0)
        self.assertLess(
            result.scaled_evidence["logLoss"], result.raw_evidence["logLoss"]
        )
        self.assertLessEqual(
            result.scaled_evidence["brierScore"],
            result.raw_evidence["brierScore"] + CALIBRATION_RETENTION_TOLERANCE,
        )
        np.testing.assert_allclose(result.final_probabilities, result.scaled_probabilities)
        json.dumps(result.evidence(), allow_nan=False)
        self.assertEqual(result.evidence()["finalSelection"], "SCALED")

        mixed_seasons = np.full(labels.size, 2024, dtype=np.int64)
        mixed_seasons[-1] = 2025
        with self.assertRaisesRegex(ValueError, "restricted to frozen 2024"):
            fit_temperature_scaling(
                labels,
                probabilities,
                source_seasons=mixed_seasons,
            )
        with self.assertRaises(ValueError):
            temperature_scale(probabilities, 0.0)
        uniform = np.full((2, 8), 0.125)
        np.testing.assert_allclose(temperature_scale(uniform, 1e-320), uniform)

    def test_temperature_candidate_is_rejected_when_brier_worsens(self) -> None:
        labels = np.asarray([3, 4, 1, 4], dtype=np.int64)
        probabilities = np.asarray(
            [
                [
                    0.03295405377268593,
                    0.23672971012524452,
                    0.157843111031685,
                    0.11790782352248004,
                    0.19007676608044416,
                    0.002296829748568069,
                    0.08486288704813762,
                    0.17732881867075467,
                ],
                [
                    0.08555447953768514,
                    0.05225542932709981,
                    0.05054588411911827,
                    0.22070133130508504,
                    0.2954871189662154,
                    0.038828604569323674,
                    0.21770261417319434,
                    0.0389245380022784,
                ],
                [
                    0.16803795575799807,
                    0.05917480732833311,
                    0.0642217517561961,
                    0.28556513284456514,
                    0.04195759886151383,
                    0.0421710588788324,
                    0.2715568618078709,
                    0.06731483276469058,
                ],
                [
                    0.0902626209529978,
                    0.036726470757597426,
                    0.10619216330871545,
                    0.2487065023620547,
                    0.26170146074974976,
                    0.005911688177105211,
                    0.1625779970227514,
                    0.08792109666902831,
                ],
            ],
            dtype=np.float64,
        )
        result = fit_temperature_scaling(
            labels,
            probabilities,
            source_seasons=np.full(labels.size, 2024, dtype=np.int64),
        )
        self.assertLessEqual(
            result.scaled_evidence["logLoss"], result.raw_evidence["logLoss"]
        )
        self.assertGreater(
            result.scaled_evidence["brierScore"], result.raw_evidence["brierScore"]
        )
        self.assertFalse(result.retained)
        self.assertEqual(result.retained_temperature, 1.0)
        self.assertEqual(result.rejection_reason, "GOVERNING_METRIC_WORSENED")
        np.testing.assert_array_equal(result.final_probabilities, result.raw_probabilities)
        self.assertEqual(result.evidence()["finalSelection"], "RAW")

    def test_game_cluster_bootstrap_is_deterministic_and_samples_whole_games(self) -> None:
        labels = np.asarray([0, 1, 2, 3, 4, 5], dtype=np.int64)
        games = np.asarray(["game-a", "game-a", "game-b", "game-b", "game-b", "game-b"])
        selected = probabilities_with_true_class_confidence(
            labels, np.asarray([0.90, 0.90, 0.45, 0.45, 0.45, 0.45])
        )
        comparator = probabilities_with_true_class_confidence(
            labels, np.asarray([0.60, 0.60, 0.70, 0.70, 0.70, 0.70])
        )

        first = game_cluster_bootstrap(
            labels,
            selected,
            comparator,
            games,
            n_resamples=25,
            seed=11,
        )
        second = game_cluster_bootstrap(
            labels,
            selected,
            comparator,
            games,
            n_resamples=25,
            seed=11,
        )
        self.assertEqual(first, second)
        permutation = np.asarray([5, 1, 3, 0, 4, 2])
        permuted = game_cluster_bootstrap(
            labels[permutation],
            selected[permutation],
            comparator[permutation],
            games[permutation],
            n_resamples=25,
            seed=11,
        )
        self.assertEqual(first, permuted)
        json.dumps(first, allow_nan=False)
        self.assertEqual(DEFAULT_BOOTSTRAP_RESAMPLES, 500)
        self.assertEqual(first["resamplingUnit"], "game_id")
        self.assertFalse(first["rowsSampledIndependently"])
        self.assertEqual(first["clusterCount"], 2)
        self.assertEqual(first["clusterDrawsPerReplicate"], 2)
        self.assertEqual(
            game_cluster_bootstrap(
                labels,
                selected,
                comparator,
                games,
                n_resamples=2,
                seed=0,
            )["seed"],
            0,
        )

        row_differences = per_row_log_loss(labels, selected) - per_row_log_loss(
            labels, comparator
        )
        cluster_counts = np.asarray([2.0, 4.0])
        cluster_sums = np.asarray(
            [row_differences[:2].sum(), row_differences[2:].sum()]
        )
        rng = np.random.default_rng(11)
        expected = []
        for _ in range(25):
            drawn = rng.integers(0, 2, size=2)
            expected.append(cluster_sums[drawn].sum() / cluster_counts[drawn].sum())
        np.testing.assert_allclose(
            first["logLossDifference"]["replicateDifferences"], expected
        )

        with self.assertRaisesRegex(ValueError, "at least two unique games"):
            game_cluster_bootstrap(
                labels,
                selected,
                comparator,
                np.asarray(["only-game"] * labels.size),
                n_resamples=5,
            )
        with self.assertRaises(ValueError):
            game_cluster_bootstrap(
                labels,
                selected,
                comparator,
                games,
                class_order=tuple(reversed(PA_CLASS_ORDER)),
                n_resamples=5,
            )
        with self.assertRaisesRegex(ValueError, "at least two"):
            game_cluster_bootstrap(
                labels,
                selected,
                comparator,
                games,
                n_resamples=1,
                seed=0,
            )


if __name__ == "__main__":
    unittest.main()
