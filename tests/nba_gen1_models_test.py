"""UNIT_ONLY synthetic model mechanics; never real NBA performance evidence."""
import unittest

import numpy as np
import pandas as pd

from server.sports_nba_gen1.features import FEATURE_COLUMNS
from server.sports_nba_gen1.models import PointModelError, fit_model


def unit_rows(count=100):
    rows = np.arange(count)
    features = pd.DataFrame({name: (rows % (index % 7 + 2)).astype(float)
                             for index, name in enumerate(FEATURE_COLUMNS)})
    features["game_id"] = [f"UNIT_ONLY_{i}" for i in rows]
    features["home_team_id"], features["away_team_id"] = "UNIT_HOME", "UNIT_AWAY"
    features["home_elo"] = 1500 + 4 * (rows % 7)
    features["away_elo"] = 1500 - 2 * (rows % 5)
    labels = features[["game_id", "home_team_id", "away_team_id"]].copy()
    labels["home_score"], labels["away_score"] = 103 + 2 * (rows % 5), 99 + (rows % 3)
    return features, labels


class NbaGen1ModelsTests(unittest.TestCase):
    def test_league_home_away_orientation_and_coherence(self):
        features, labels = unit_rows(10)
        labels["home_score"], labels["away_score"] = 90, 100
        model = fit_model("league", {}, features, labels)
        expected = model.predict(features.iloc[:2])
        np.testing.assert_array_equal(expected, [[90, 100], [90, 100]])
        np.testing.assert_array_equal(model.predict_margin_total(features.iloc[:2]), [[-10, 190], [-10, 190]])
        self.assertEqual(model.feature_names, ())

    def test_game_id_alignment_and_orientation_are_enforced(self):
        features, labels = unit_rows(10)
        first = fit_model("elo", {}, features, labels)
        reordered = fit_model("elo", {}, features, labels.iloc[::-1])
        np.testing.assert_array_equal(first.predict(features), reordered.predict(features))
        wrong = labels.copy()
        wrong.loc[0, "game_id"] = "UNIT_UNKNOWN"
        with self.assertRaises(PointModelError):
            fit_model("league", {}, features, wrong)
        wrong = labels.copy()
        wrong.loc[0, "home_team_id"] = "UNIT_AWAY"
        with self.assertRaisesRegex(PointModelError, "orientation"):
            fit_model("league", {}, features, wrong)
        with self.assertRaises(PointModelError):
            fit_model("league", {}, pd.concat([features, features.iloc[:1]]), labels)

    def test_training_only_imputation_and_scaling_are_frozen_at_prediction(self):
        features, labels = unit_rows(20)
        name, empty = FEATURE_COLUMNS[0], FEATURE_COLUMNS[1]
        features[name] = np.arange(20, dtype=float)
        features.loc[:3, name] = np.nan
        features[empty] = np.nan
        model = fit_model("ridge", {"alpha": 10}, features, labels)
        pipeline = model.estimators["margin_total"]
        imputer_before = pipeline.named_steps["imputer"].statistics_.copy()
        scale_before = pipeline.named_steps["scaler"].mean_.copy()
        future = features.iloc[:2].copy()
        future[name] = [1e6, np.nan]
        model.predict(future)
        np.testing.assert_array_equal(pipeline.named_steps["imputer"].statistics_, imputer_before)
        np.testing.assert_array_equal(pipeline.named_steps["scaler"].mean_, scale_before)
        self.assertEqual(imputer_before[0], np.median(np.arange(4, 20)))
        self.assertEqual(imputer_before[1], 0)
        self.assertIn(empty, model.diagnostic_coefficients["allMissingTrainingFeatures"])
        self.assertEqual(pipeline.named_steps["scaler"].n_features_in_, len(FEATURE_COLUMNS))

    def test_target_columns_are_not_features_and_prediction_order_is_preserved(self):
        features, labels = unit_rows(20)
        baseline = fit_model("ridge", {"alpha": 100}, features, labels)
        leaked = features.copy()
        leaked["home_score"] = labels["home_score"]
        leaked["away_score"] = labels["away_score"] * 100000
        checked = fit_model("ridge", {"alpha": 100}, leaked, labels)
        np.testing.assert_array_equal(baseline.predict(features), checked.predict(leaked))
        prediction = baseline.predict(features)
        np.testing.assert_array_equal(baseline.predict(features.iloc[::-1]), prediction[::-1])
        self.assertNotIn("home_score", baseline.feature_names)

    def test_all_families_are_deterministic_and_retain_coherent_expectations(self):
        features, labels = unit_rows()
        for family, params in (("league", {}), ("elo", {}), ("ridge", {"alpha": 10}),
                               ("hgb", {"l2_regularization": 10})):
            with self.subTest(family=family):
                first, second = fit_model(family, params, features, labels), fit_model(family, params, features, labels)
                predicted = first.predict(features.iloc[:4])
                np.testing.assert_array_equal(predicted, second.predict(features.iloc[:4]))
                mt = first.predict_margin_total(features.iloc[:4])
                np.testing.assert_allclose(predicted[:, 0] - predicted[:, 1], mt[:, 0], atol=1e-12)
                np.testing.assert_allclose(predicted.sum(axis=1), mt[:, 1], atol=1e-12)
                self.assertEqual(first.training_game_ids, tuple(features["game_id"]))
                self.assertEqual(first.training_identity_sha256, second.training_identity_sha256)
                if family == "hgb":
                    self.assertFalse(first.params["early_stopping"])

    def test_screen_cannot_expand_and_invalid_final_labels_fail(self):
        features, labels = unit_rows(10)
        for family, params in (("ridge", {"alpha": 1}), ("hgb", {"max_iter": 500}),
                               ("elo", {"weight": 2}), ("random_forest", {})):
            with self.subTest(family=family), self.assertRaises(PointModelError):
                fit_model(family, params, features, labels)
        labels["away_score"] = labels["home_score"]
        with self.assertRaises(PointModelError):
            fit_model("league", {}, features, labels)


if __name__ == "__main__":
    unittest.main()
