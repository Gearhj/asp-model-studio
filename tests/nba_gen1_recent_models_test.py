"""Synthetic UNIT_ONLY checks; these cases are not NBA forecasting evidence."""
from copy import deepcopy
from io import BytesIO
import unittest

import joblib
import numpy as np
import pandas as pd

from server.sports_nba_gen1.historical_features import historical_feature_contract
from server.sports_nba_gen1.models import PointModelError
from server.sports_nba_gen1.recent_models import fit_reduced_model


def unit_rows(count=100):
    from server.sports_nba_gen1.recent_features import recent_feature_contract

    contract = recent_feature_contract()
    rows = np.arange(count)
    features = pd.DataFrame({name: (rows % (index % 7 + 2)).astype(float)
                             for index, name in enumerate(contract["numericFeatures"])})
    features["game_id"] = [f"UNIT_ONLY_RECENT_{i}" for i in rows]
    features["home_team_id"], features["away_team_id"] = "UNIT_HOME", "UNIT_AWAY"
    features["neutral_site"], features["target_eligible"] = False, True
    labels = features[["game_id", "home_team_id", "away_team_id"]].copy()
    labels["home_score"], labels["away_score"] = 103 + 2 * (rows % 5), 99 + (rows % 3)
    return features, labels, contract


class NbaGen1RecentModelsTests(unittest.TestCase):
    def test_exact_governed_contract_prevents_source_target_columns(self):
        features, labels, contract = unit_rows(20)
        original = fit_reduced_model("ridge", {"alpha": 10}, features, labels)
        features["home_score"] = labels["home_score"]
        features["away_score"] = labels["away_score"] * 100000
        features["publisher_elo_after_game"] = 1e9
        tested = fit_reduced_model("ridge", {"alpha": 10}, features, labels,
                                   feature_names=tuple(contract["numericFeatures"]),
                                   feature_contract=contract)
        np.testing.assert_array_equal(original.predict(features), tested.predict(features))
        self.assertEqual(original.training_identity_sha256, tested.training_identity_sha256)
        self.assertNotIn("home_score", original.feature_names)
        forged = deepcopy(contract)
        forged["numericFeatures"].append("home_score")
        with self.assertRaisesRegex(PointModelError, "governed"):
            fit_reduced_model("ridge", {}, features, labels, feature_contract=forged)
        with self.assertRaisesRegex(PointModelError, "tuple"):
            fit_reduced_model("ridge", {}, features, labels,
                              feature_names=tuple(contract["numericFeatures"][:-1]))

    def test_historical_contract_is_explicitly_reproducible(self):
        features, labels, _ = unit_rows(20)
        contract = historical_feature_contract()
        model = fit_reduced_model("ridge", {}, features, labels,
                                  feature_contract=contract,
                                  feature_names=tuple(contract["numericFeatures"]))
        self.assertEqual(model.feature_names, tuple(contract["numericFeatures"]))
        self.assertEqual(model.feature_contract_sha256, contract["sha256"])

    def test_training_only_preprocessing_and_missing_history(self):
        features, labels, contract = unit_rows()
        name, empty = contract["numericFeatures"][:2]
        features[name] = np.arange(100, dtype=float)
        features.loc[:3, name] = np.nan
        features[empty] = np.nan
        for family in ("ridge", "hgb"):
            with self.subTest(family=family):
                model = fit_reduced_model(family, {}, features, labels)
                pipelines = ([model.estimators["margin_total"]] if family == "ridge"
                             else [model.estimators["margin"], model.estimators["total"]])
                statistics = [p.named_steps["imputer"].statistics_.copy() for p in pipelines]
                means = pipelines[0].named_steps["scaler"].mean_.copy() if family == "ridge" else None
                future = features.iloc[:2].copy()
                future[name] = [1e6, np.nan]
                model.predict(future)
                for pipeline, before in zip(pipelines, statistics):
                    np.testing.assert_array_equal(pipeline.named_steps["imputer"].statistics_, before)
                    self.assertEqual(before[0], np.median(np.arange(4, 100)))
                    self.assertEqual(before[1], 0)
                if means is not None:
                    np.testing.assert_array_equal(pipelines[0].named_steps["scaler"].mean_, means)
                self.assertIn(empty, model.diagnostic_coefficients["allMissingTrainingFeatures"])

    def test_identity_orientation_and_target_alignment(self):
        features, labels, _ = unit_rows(20)
        first = fit_reduced_model("ridge", {}, features, labels)
        reordered = fit_reduced_model("ridge", {}, features, labels.iloc[::-1])
        np.testing.assert_array_equal(first.predict(features), reordered.predict(features))
        self.assertEqual(first.training_identity_sha256, reordered.training_identity_sha256)
        wrong = labels.copy()
        wrong.loc[0, "home_team_id"] = "UNIT_WRONG_HOME"
        with self.assertRaisesRegex(PointModelError, "orientation"):
            fit_reduced_model("ridge", {}, features, wrong)
        with self.assertRaisesRegex(PointModelError, "home_team_id"):
            fit_reduced_model("ridge", {}, features, labels.drop(columns=["home_team_id"]))
        wrong = labels.copy()
        wrong.loc[0, "game_id"] = "UNIT_OTHER"
        with self.assertRaises(PointModelError):
            fit_reduced_model("ridge", {}, features, wrong)

    def test_training_hash_binds_actual_feature_and_label_values(self):
        features, labels, contract = unit_rows(20)
        first = fit_reduced_model("ridge", {}, features, labels)
        changed = features.copy()
        changed.loc[0, contract["numericFeatures"][0]] += 0.25
        feature_changed = fit_reduced_model("ridge", {}, changed, labels)
        self.assertNotEqual(first.training_identity_sha256, feature_changed.training_identity_sha256)
        self.assertNotEqual(first.training_feature_values_sha256, feature_changed.training_feature_values_sha256)
        changed_labels = labels.copy()
        changed_labels.loc[0, "home_score"] += 1
        label_changed = fit_reduced_model("ridge", {}, features, changed_labels)
        self.assertNotEqual(first.training_identity_sha256, label_changed.training_identity_sha256)
        self.assertNotEqual(first.training_target_values_sha256, label_changed.training_target_values_sha256)

    def test_determinism_reload_order_and_coherent_means(self):
        features, labels, _ = unit_rows()
        for family, params in (("ridge", {"alpha": 100}), ("hgb", {"l2_regularization": 50})):
            with self.subTest(family=family):
                first = fit_reduced_model(family, params, features, labels)
                second = fit_reduced_model(family, params, features, labels)
                future = features.iloc[:5]
                predicted = first.predict(future)
                np.testing.assert_array_equal(predicted, second.predict(future))
                np.testing.assert_array_equal(first.predict(future.iloc[::-1]), predicted[::-1])
                stream = BytesIO()
                joblib.dump(first, stream)
                stream.seek(0)
                np.testing.assert_array_equal(predicted, joblib.load(stream).predict(future))
                mt = first.predict_margin_total(future)
                np.testing.assert_allclose(predicted[:, 0] - predicted[:, 1], mt[:, 0], atol=1e-12)
                np.testing.assert_allclose(predicted.sum(axis=1), mt[:, 1], atol=1e-12)
                self.assertEqual(first.training_game_ids, tuple(features["game_id"]))
                self.assertEqual(first.predict(future.iloc[:0]).shape, (0, 2))
                if family == "hgb":
                    self.assertFalse(first.params["early_stopping"])
                    self.assertEqual(first.params["max_iter"], 150)

    def test_neutral_ineligible_and_invalid_scores_fail(self):
        features, labels, _ = unit_rows(20)
        for field, value in (("neutral_site", True), ("target_eligible", False)):
            wrong = features.copy()
            wrong.loc[0, field] = value
            with self.subTest(field=field), self.assertRaises(PointModelError):
                fit_reduced_model("ridge", {}, wrong, labels)
        labels["away_score"] = labels["home_score"]
        with self.assertRaisesRegex(PointModelError, "untied"):
            fit_reduced_model("ridge", {}, features, labels)

    def test_bounded_screen_cannot_expand(self):
        features, labels, _ = unit_rows(20)
        for family, params in (("ridge", {"alpha": 1}), ("hgb", {"max_iter": 500}),
                               ("hgb", {"l2_regularization": 1}), ("elo", {})):
            with self.subTest(family=family, params=params), self.assertRaises(PointModelError):
                fit_reduced_model(family, params, features, labels)


if __name__ == "__main__":
    unittest.main()
