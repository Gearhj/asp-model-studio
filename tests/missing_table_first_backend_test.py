from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from server.core.dataset_store import DATASTORE
from server.preprocessing import missing_router
from server.preprocessing.missing_router import _distribution_profile


class MissingTableFirstBackendTest(unittest.TestCase):
    def test_numeric_distribution_separates_nulls_specials_and_ordinary_values(self):
        profile = _distribution_profile(
            pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, -7.0, -8.0, None])
        )

        self.assertEqual(profile["kind"], "numeric")
        self.assertEqual(profile["observed_count"], 5)
        self.assertEqual(profile["ordinary_numeric_count"], 5)
        self.assertEqual(profile["missing_count"], 1)
        self.assertEqual(profile["special_value_count"], 2)
        self.assertEqual(
            sum(bin_row["count"] for bin_row in profile["bins"]),
            5,
        )
        self.assertEqual(
            profile["reference_cutoffs"]["method"],
            "1.5 IQR ordinary-value reference",
        )
        self.assertIn(
            "not missing-value treatments",
            profile["cutoff_semantics"],
        )

    def test_categorical_distribution_is_honest_about_cutoffs(self):
        profile = _distribution_profile(
            pd.Series(["current", "current", "late", None], dtype="object")
        )

        self.assertEqual(profile["kind"], "categorical")
        self.assertEqual(profile["observed_count"], 3)
        self.assertEqual(profile["missing_count"], 1)
        self.assertIsNone(profile["reference_cutoffs"])
        self.assertIn("not applicable", profile["cutoff_semantics"])
        self.assertEqual(
            sum(bin_row["count"] for bin_row in profile["bins"]),
            3,
        )

    def test_summary_exposes_table_stats_iv_and_full_population_histograms(self):
        frame = pd.DataFrame(
            {
                "score": [10.0, 11.0, 12.0, 40.0, -7.0, None],
                "segment": ["a", "a", "b", "b", "a", None],
                "bad_flag": [0, 0, 0, 1, 1, 1],
            }
        )
        previous_target = DATASTORE.target
        previous_meta = dict(DATASTORE.meta)
        DATASTORE.target = "bad_flag"
        identity = {
            "project_id": "project-test",
            "dataset_id": "dataset-test",
            "dataset_version_id": "dataset-version-test-v1",
        }
        DATASTORE.meta = {
            **identity,
            "dataset_version": identity["dataset_version_id"],
        }
        try:
            with (
                patch.object(
                    missing_router,
                    "authorize_modeling_scope",
                    return_value=None,
                ),
                patch.object(
                    missing_router,
                    "_pre_missing_df",
                    return_value=frame,
                ),
                patch.object(
                    missing_router,
                    "_feature_columns",
                    return_value=["score", "segment"],
                ),
                patch.object(
                    missing_router,
                    "_authorization_with_full_source_exclusions",
                    return_value={
                        "authorized_predictors": ["score", "segment"],
                        "excluded_predictors": {},
                        "target_source_excluded": [],
                    },
                ),
                patch.object(
                    missing_router,
                    "assert_expected_active_identity",
                    return_value=identity,
                ),
            ):
                payload = missing_router.missing_summary(
                    project_id="project-test",
                    event_value=1,
                    problem_type="classification",
                    expected_dataset_id=identity["dataset_id"],
                    expected_dataset_version_id=identity[
                        "dataset_version_id"
                    ],
                    dataset_id=None,
                    dataset_version_id=None,
                    dataset_version=None,
                    user={"id": "user-test"},
                )
        finally:
            DATASTORE.target = previous_target
            DATASTORE.meta = previous_meta

        score = payload["stats"]["score"]
        self.assertEqual(payload["scope"], "full_dataset")
        self.assertEqual(score["missing"], 1)
        self.assertEqual(score["special_value_count"], 1)
        self.assertEqual(score["observed_count"], 4)
        self.assertEqual(score["distribution"]["observed_count"], 4)
        self.assertEqual(
            sum(row["count"] for row in score["distribution"]["bins"]),
            4,
        )
        self.assertIsInstance(score["information_value"], float)
        for key in (
            "distinct_count",
            "mean",
            "standard_deviation",
            "minimum",
            "first_quartile",
            "median",
            "third_quartile",
            "maximum",
        ):
            self.assertIn(key, score)


if __name__ == "__main__":
    unittest.main()
