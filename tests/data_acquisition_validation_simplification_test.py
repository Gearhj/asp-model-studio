from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault(
    "ATLAS_CHECKPOINT_PATH",
    str(
        Path(tempfile.gettempdir())
        / f"atlas_data_validation_simplification_{uuid.uuid4().hex[:10]}.json"
    ),
)

from server.core.dataset_store import DATASTORE  # noqa: E402
from server.preprocessing.bureau_detection_service import (  # noqa: E402
    detect_bureau_data,
)
from server.preprocessing.bureau_detection_types import (  # noqa: E402
    BureauDetectionRequest,
    BureauMetadataInput,
)
from server.splitting.split_router import _current_status  # noqa: E402
from server.splitting.split_service import split_service  # noqa: E402


def governed_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ExternalRiskEstimate": [
                -9,
                -8,
                -7,
                64,
                67,
                70,
                None,
                "parse-failure",
                72,
                74,
            ],
            "MSinceMostRecentDelq": [
                -9,
                12,
                18,
                -8,
                22,
                25,
                29,
                31,
                35,
                40,
            ],
            "NumTotalTrades": [10, 11, 9, 12, 15, 14, 8, 17, 19, 16],
            "bad_flag": [1, 0, 1, 0, 1, 0, 0, 1, 0, 1],
        }
    )


class SpecialValueContractTests(unittest.TestCase):
    def tearDown(self):
        DATASTORE.reset_all()

    def test_detection_exposes_table_counts_without_merging_semantics(self):
        frame = governed_frame()
        DATASTORE.reset_all()
        DATASTORE.set_raw(frame)
        DATASTORE.set_target("bad_flag")
        DATASTORE.meta["event_value"] = 1

        result = detect_bureau_data(
            BureauDetectionRequest(
                project_id="special-value-contract",
                target="bad_flag",
                event_value=1,
                metadata=[
                    BureauMetadataInput(
                        variableName="ExternalRiskEstimate",
                        bureauSource="HELOC data dictionary",
                    ),
                    BureauMetadataInput(
                        variableName="MSinceMostRecentDelq",
                        bureauSource="HELOC data dictionary",
                    ),
                ],
            )
        )

        self.assertTrue(result["detected"])
        self.assertEqual(result["row_count"], 10)
        # The same row can carry specials in two variables and is counted once.
        self.assertEqual(result["rows_with_special_values"], 4)
        by_name = {row["variable"]: row for row in result["variables"]}
        risk = by_name["ExternalRiskEstimate"]
        self.assertEqual(risk["special_value_count"], 3)
        self.assertEqual(risk["ordinary_value_count"], 5)
        self.assertEqual(risk["null_count"], 1)
        self.assertEqual(risk["parse_failure_count"], 1)
        for special in risk["special_values"]:
            self.assertIn("event_count", special)
            self.assertIn("event_rate", special)
            self.assertIn("regular_event_rate", special)
            self.assertIn("event_rate_delta", special)


class ValidationDefaultContractTests(unittest.TestCase):
    def tearDown(self):
        DATASTORE.reset_all()

    def test_target_distribution_is_available_before_a_split_exists(self):
        frame = governed_frame()
        DATASTORE.reset_all()
        DATASTORE.set_raw(frame)
        DATASTORE.set_target("bad_flag")
        DATASTORE.meta["dataset_version"] = "heloc-target-contract-v1"
        DATASTORE.meta["event_value"] = 1

        status = _current_status()
        self.assertEqual(status["status"], "not_created")
        self.assertFalse(status["has_split"])
        distribution = status["distributions"]["full_dataset"]
        self.assertEqual(distribution["rows"], 10)
        self.assertEqual(distribution["events"], 5)
        self.assertEqual(distribution["non_events"], 5)
        self.assertAlmostEqual(distribution["event_rate"], 0.5)

    def test_standard_hybrid_design_keeps_cv_inside_untouched_holdout_split(self):
        rows = 200
        frame = pd.DataFrame(
            {
                "bureau_score": [500 + index % 100 for index in range(rows)],
                "trade_count": [5 + index % 20 for index in range(rows)],
                "bad_flag": [index % 2 for index in range(rows)],
            }
        )
        result = split_service.make_validation_split(
            frame,
            "bad_flag",
            ["bureau_score", "trade_count"],
            {
                "split_strategy": "hybrid",
                "test_size": 0.2,
                "random_seed": 42,
                "stratify": True,
                "problem_type": "classification",
                "event_value": 1,
                "balance_method": "none",
                "minority_share": 0.5,
                "fold_method": "stratified_k_fold",
                "fold_count": 5,
                "repeats": 1,
                "shuffle": True,
            },
        )

        self.assertEqual(len(result.y_train), 160)
        self.assertEqual(len(result.y_test), 40)
        self.assertEqual(result.evaluation_population_role, "untouched_holdout")
        self.assertEqual(result.fold_architecture["fold_count"], 5)
        self.assertEqual(result.synthetic_rows_added, 0)
        self.assertEqual(result.rows_removed, 0)
        for fold in result.fold_architecture["folds"]:
            self.assertGreater(fold["validation_distribution"]["events"], 0)
            self.assertGreater(
                fold["validation_distribution"]["non_events"],
                0,
            )


if __name__ == "__main__":
    unittest.main()
