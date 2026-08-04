from __future__ import annotations

import importlib
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException

from server.analysis_partition.service import analysis_partition_service
from server.analysis_partition.types import (
    ANALYSIS_PARTITION_REQUIRED,
    ANALYSIS_PARTITION_STALE,
    AnalysisPartitionError,
)
from server.core.dataset_store import DATASTORE
from server.core.modeling_scope import set_active_project_id

from tests.analysis_partition_fixture import GovernedAnalysisFixture
from tests.preprocessing_development_scope_test import (
    DATASET_ID,
    IDENTITY,
    PREDICTORS,
    PROJECT_ID,
    TARGET,
    VERSION_ID,
    _synthetic_frame,
)


metadata_router = importlib.import_module("server.core.metadata_router")


class BrowserSampleScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        set_active_project_id(PROJECT_ID)
        self.store = DATASTORE.current()
        self.store.reset_all()
        self.store.set_raw(_synthetic_frame(duplicate_index=True))
        self.store.set_target(TARGET)
        self.store.meta.update(
            {
                **IDENTITY,
                "dataset_version": VERSION_ID,
                "selected_columns": list(PREDICTORS),
            }
        )
        self.fixture = GovernedAnalysisFixture(project_id=PROJECT_ID)
        self.installation = self.fixture.install(
            self.store,
            dataset_id=DATASET_ID,
            dataset_version_id=VERSION_ID,
            target=TARGET,
            authorized_predictors=PREDICTORS,
            positive_value=1,
            negative_value=0,
            development_share=0.8,
            random_seed=73,
        )
        self.identity = {
            **IDENTITY,
            "activation_revision": 1,
            "dataset_content_hash": self.store.meta["dataset_content_hash"],
            "dataset": {"target": TARGET},
        }

    def tearDown(self) -> None:
        self.fixture.close()
        self.store.reset_all()
        set_active_project_id(None)

    def _sample(self, max_rows: int = 5000) -> dict:
        with (
            patch.object(
                metadata_router,
                "authorize_modeling_scope",
                return_value=PROJECT_ID,
            ),
            patch.object(
                metadata_router,
                "assert_expected_active_identity",
                return_value=dict(self.identity),
            ),
            patch.object(
                metadata_router,
                "get_persistence_service",
                return_value=self.fixture.persistence,
            ),
        ):
            return metadata_router.get_sample(
                project_id=PROJECT_ID,
                max_rows=max_rows,
                expected_dataset_id=DATASET_ID,
                expected_dataset_version_id=VERSION_ID,
                user={"userId": "governed-analysis-test"},
            )

    def test_current_partition_returns_only_positional_development_predictors(self):
        result = self._sample()
        positions = self.installation["record"]["row_assignments_json"][
            "development_positions"
        ]
        expected = self.store.raw_df.iloc[positions].loc[:, result["headers"]]

        pd.testing.assert_frame_equal(
            pd.DataFrame(result["rows"]),
            expected.reset_index(drop=True),
            check_dtype=False,
        )
        self.assertEqual(set(result["headers"]), set(PREDICTORS))
        self.assertNotIn(TARGET, result["headers"])
        self.assertTrue(all(TARGET not in row for row in result["rows"]))
        self.assertFalse(result["target_values_included"])
        self.assertEqual(
            result["scope"]["analytical_scope"],
            "development_population_predictors_only",
        )
        self.assertTrue(result["scope"]["holdout_excluded"])
        self.assertFalse(result["scope"]["holdout_target_accessed"])
        self.assertEqual(
            result["scope"]["partition_id"],
            self.installation["record"]["analysis_partition_id"],
        )

    def test_holdout_target_changes_do_not_change_browser_sample(self):
        before = self._sample()
        holdout_positions = self.installation["record"]["row_assignments_json"][
            "holdout_positions"
        ]
        target_position = self.store.raw_df.columns.get_loc(TARGET)
        current = self.store.raw_df.iloc[holdout_positions, target_position]
        self.store.raw_df.iloc[holdout_positions, target_position] = (
            1 - current.to_numpy()
        )
        after = self._sample()
        pd.testing.assert_frame_equal(
            pd.DataFrame(before["rows"]),
            pd.DataFrame(after["rows"]),
            check_dtype=False,
        )
        self.assertTrue(all(TARGET not in row for row in after["rows"]))

    def test_true_prepartition_scope_is_full_population_but_target_free(self):
        with patch.object(
            analysis_partition_service,
            "current",
            side_effect=AnalysisPartitionError(
                ANALYSIS_PARTITION_REQUIRED,
                "Synthetic project has not created its first partition.",
            ),
        ):
            result = self._sample(max_rows=20)
        self.assertEqual(len(result["rows"]), 20)
        self.assertTrue(all(TARGET not in row for row in result["rows"]))
        self.assertEqual(
            result["scope"]["analytical_scope"],
            "full_governed_population_predictors_only",
        )
        self.assertFalse(result["scope"]["holdout_excluded"])
        self.assertFalse(result["scope"]["target_values_included"])
        self.assertEqual(result["scope"]["partition_revision"], 0)

    def test_stale_partition_fails_closed_without_full_population_fallback(self):
        with patch.object(
            analysis_partition_service,
            "current",
            side_effect=AnalysisPartitionError(
                ANALYSIS_PARTITION_STALE,
                "Synthetic stale partition.",
            ),
        ):
            with self.assertRaises(HTTPException) as captured:
                self._sample()
        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail["code"], ANALYSIS_PARTITION_STALE
        )


if __name__ == "__main__":
    unittest.main()
