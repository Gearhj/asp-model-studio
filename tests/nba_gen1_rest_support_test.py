"""UNIT_ONLY ordinary-rest mechanics; synthetic games are not forecasting evidence."""
from copy import deepcopy
from io import BytesIO
import unittest

import joblib
import numpy as np
import pandas as pd

from server.sports_nba_gen1.models import PointModelError
from server.sports_nba_gen1.recent_features import FEATURE_COLUMNS
from server.sports_nba_gen1.rest_support import (
    CHANGED_COLUMNS, VERSION, feature_contract, fit_rest_model,
    learn_rest_support, transform_rest,
)


def unit_rows(count=80):
    index = np.arange(count)
    frame = pd.DataFrame({name: (index % 7 + offset % 5).astype(float)
                          for offset, name in enumerate(FEATURE_COLUMNS)})
    frame["game_id"] = [f"UNIT_ONLY_REST_{i}" for i in index]
    frame["home_team_id"], frame["away_team_id"] = "UNIT_HOME", "UNIT_AWAY"
    frame["target_eligible"], frame["neutral_site"] = True, False
    frame["home_elo"], frame["away_elo"] = 1500 + index % 7, 1500 - index % 5
    frame["home_court"] = 1.0
    for side in ("home", "away"):
        frame[f"{side}_rest_days"] = (index % 3).astype(float)
        frame[f"{side}_rest_known"] = 1
        frame[f"{side}_season_games_played"] = index + 1
        frame[f"{side}_back_to_back"] = (index % 3 == 0).astype(int)
        frame.loc[0, f"{side}_season_games_played"] = 0
        frame.loc[0, f"{side}_rest_days"] = 130 if side == "home" else 129
        frame.loc[0, f"{side}_back_to_back"] = 0
    frame.loc[count - 1, "home_rest_days"] = 8
    frame.loc[count - 1, "away_rest_days"] = 9
    frame["difference_rest_days"] = frame.home_rest_days - frame.away_rest_days
    labels = frame[["game_id", "home_team_id", "away_team_id"]].copy()
    labels["home_score"], labels["away_score"] = 105 + index % 5, 99 + index % 3
    return frame, labels


class NbaGen1RestSupportTests(unittest.TestCase):
    def test_support_is_pooled_symmetric_and_fitting_only(self):
        train, _ = unit_rows()
        support = learn_rest_support(train)
        self.assertEqual(support["maximumDays"], 9)
        self.assertEqual(support["minimumDays"], 0)
        self.assertEqual(support["observedTeamExposures"], {"home": 79, "away": 79})
        future = train.iloc[:2].copy()
        future["home_season_games_played"], future["away_season_games_played"] = 10, 10
        future["home_rest_days"], future["away_rest_days"] = [9, 12], [12, 9]
        saved = deepcopy(support)
        treated, _ = transform_rest(future, support)
        self.assertEqual(treated.home_rest_known.tolist(), [1, 0])
        self.assertEqual(treated.away_rest_known.tolist(), [0, 1])
        self.assertEqual(support, saved)
        later_train = train.copy()
        later_train.loc[2, "away_rest_days"] = 12
        self.assertEqual(learn_rest_support(later_train)["maximumDays"], 12)
        self.assertEqual(support["maximumDays"], 9)

    def test_missing_opener_outside_and_back_to_back_categories(self):
        train, _ = unit_rows()
        frame = train.iloc[:4].copy()
        for side in ("home", "away"):
            frame[f"{side}_rest_days"] = [130, np.nan, 10, 0]
            frame[f"{side}_rest_known"] = [1, 0, 1, 1]
            frame[f"{side}_season_games_played"] = [0, 5, 5, 5]
            frame[f"{side}_back_to_back"] = [0, 0, 0, 1]
        frame.loc[3, "away_rest_days"] = 2
        frame.loc[3, "away_back_to_back"] = 0
        frame["difference_rest_days"] = frame.home_rest_days - frame.away_rest_days
        treated, audit = transform_rest(frame, learn_rest_support(train))
        self.assertEqual(audit.home_reason.tolist(), [
            "SEASON_OPENER_NO_ORDINARY_REST", "MISSING_RECORDED_DATE",
            "OUTSIDE_FITTING_REST_SUPPORT", "ORDINARY_REST_SUPPORTED"])
        self.assertTrue(treated.home_rest_days.iloc[:3].isna().all())
        self.assertEqual(treated.home_rest_known.tolist(), [0, 0, 0, 1])
        self.assertEqual(treated.home_back_to_back.tolist(), [0, 0, 0, 1])
        self.assertEqual(treated.away_back_to_back.tolist(), [0, 0, 0, 0])
        self.assertTrue(treated.difference_rest_days.iloc[:3].isna().all())
        self.assertEqual(treated.difference_rest_days.iloc[3], -2)
        self.assertEqual(audit.raw_home_rest_days.iloc[0], 130)
        self.assertEqual(audit.raw_home_rest_known.iloc[0], 1)

    def test_remaining_71_inputs_elo_metadata_and_raw_frame_are_unchanged(self):
        frame, _ = unit_rows()
        before = frame.copy(deep=True)
        treated, audit = transform_rest(frame, learn_rest_support(frame))
        unchanged = [name for name in FEATURE_COLUMNS if name not in CHANGED_COLUMNS]
        self.assertEqual(len(unchanged), 71)
        pd.testing.assert_frame_equal(frame, before)
        pd.testing.assert_frame_equal(treated[unchanged], before[unchanged])
        pd.testing.assert_frame_equal(treated[["game_id", "home_team_id", "away_team_id"]],
                                      before[["game_id", "home_team_id", "away_team_id"]])
        np.testing.assert_array_equal(treated.elo_home_win_probability, before.elo_home_win_probability)
        np.testing.assert_array_equal(audit.raw_difference_rest_days, before.difference_rest_days)

    def test_difference_is_masked_then_independently_imputed_from_training(self):
        train, labels = unit_rows()
        train["home_rest_days"], train["away_rest_days"] = 2.0, 1.0
        train["home_back_to_back"], train["away_back_to_back"] = 0, 0
        train["difference_rest_days"] = 1.0
        model = fit_rest_model(train, labels)
        future = train.iloc[:1].copy()
        future["home_season_games_played"], future["away_season_games_played"] = 0, 5
        future["home_rest_days"], future["away_rest_days"] = 130.0, 0.0
        future["difference_rest_days"] = 130.0
        treated, _ = transform_rest(future, model.rest_support)
        self.assertTrue(treated.home_rest_days.isna().all())
        self.assertTrue(treated.difference_rest_days.isna().all())
        pipe = model.estimators["margin_total"]
        imputed = pipe.named_steps["imputer"].transform(treated[list(model.feature_names)].to_numpy(float))[0]
        positions = {name: model.feature_names.index(name) for name in CHANGED_COLUMNS}
        self.assertEqual(imputed[positions["home_rest_days"]], 2)
        self.assertEqual(imputed[positions["away_rest_days"]], 0)
        self.assertEqual(imputed[positions["difference_rest_days"]], 1)
        self.assertNotEqual(imputed[positions["difference_rest_days"]],
                            imputed[positions["home_rest_days"]] - imputed[positions["away_rest_days"]])
        self.assertIn("independently imputed", feature_contract()["difference"])

    def test_single_recipe_identity_prediction_and_serialization(self):
        train, labels = unit_rows()
        first, second = fit_rest_model(train, labels), fit_rest_model(train, labels)
        self.assertEqual(first.params, {"alpha": 100.0})
        self.assertEqual(first.screen_version, VERSION)
        self.assertEqual(first.feature_contract_sha256, feature_contract()["sha256"])
        self.assertEqual(first.training_identity_sha256, second.training_identity_sha256)
        self.assertEqual(first.training_game_ids, tuple(train.game_id))
        future = train.iloc[:5].copy()
        predicted = first.predict(future)
        np.testing.assert_array_equal(predicted, second.predict(future))
        np.testing.assert_array_equal(first.predict(future.iloc[::-1]), predicted[::-1])
        treated, audit = transform_rest(future, first.rest_support)
        pd.testing.assert_frame_equal(first.support_audit(future), audit)
        mt = first.estimators["margin_total"].predict(treated[list(first.feature_names)].to_numpy(float))
        expected = np.column_stack(((mt[:, 1] + mt[:, 0]) / 2, (mt[:, 1] - mt[:, 0]) / 2))
        np.testing.assert_array_equal(predicted, expected)
        stream = BytesIO()
        joblib.dump(first, stream)
        stream.seek(0)
        restored = joblib.load(stream)
        np.testing.assert_array_equal(predicted, restored.predict(future))
        self.assertEqual(first.predict(future.iloc[:0]).shape, (0, 2))

    def test_prediction_never_refits_support_imputer_or_scaler(self):
        train, labels = unit_rows()
        model = fit_rest_model(train, labels)
        pipe = model.estimators["margin_total"]
        support = deepcopy(model.rest_support)
        medians, means = pipe.named_steps["imputer"].statistics_.copy(), pipe.named_steps["scaler"].mean_.copy()
        future = train.iloc[:2].copy()
        future["home_rest_days"], future["away_rest_days"] = 100000.0, 200000.0
        model.predict(future)
        self.assertEqual(support, model.rest_support)
        np.testing.assert_array_equal(medians, pipe.named_steps["imputer"].statistics_)
        np.testing.assert_array_equal(means, pipe.named_steps["scaler"].mean_)

    def test_malformed_support_and_no_training_support_fail_closed(self):
        train, _ = unit_rows()
        support = learn_rest_support(train)
        bad_values = [None, {}, {**support, "schema": "UNDECLARED"}, {**support, "minimumDays": 1}]
        bad_values.extend({**support, "maximumDays": maximum} for maximum in (-1, np.nan, np.inf, True, 1.5))
        for value in bad_values:
            with self.subTest(support=value), self.assertRaises(PointModelError):
                transform_rest(train, value)
        no_support = train.copy()
        no_support["home_season_games_played"], no_support["away_season_games_played"] = 0, 0
        with self.assertRaisesRegex(PointModelError, "No observed"):
            learn_rest_support(no_support)

    def test_invalid_raw_calendar_and_identity_inputs_are_not_hidden(self):
        train, labels = unit_rows()
        for name, value in (("home_rest_days", -1), ("home_rest_days", np.inf), ("home_rest_days", 1.5),
                            ("home_rest_days", np.nan), ("home_rest_known", 2),
                            ("home_season_games_played", -1), ("home_season_games_played", 1.5)):
            wrong = train.copy()
            wrong[name] = wrong[name].astype(float)
            wrong.loc[2, name] = value
            with self.subTest(name=name, value=value), self.assertRaises(PointModelError):
                learn_rest_support(wrong)
        wrong = labels.copy()
        wrong.loc[2, "home_team_id"] = "UNIT_OTHER"
        with self.assertRaisesRegex(PointModelError, "orientation"):
            fit_rest_model(train, wrong)
        wrong = train.copy()
        wrong.loc[2, "neutral_site"] = True
        with self.assertRaises(PointModelError):
            learn_rest_support(wrong)


if __name__ == "__main__":
    unittest.main()
