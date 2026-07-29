from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault(
    "ATLAS_CHECKPOINT_PATH",
    str(
        Path(tempfile.gettempdir())
        / f"atlas_table_first_contract_{uuid.uuid4().hex[:10]}.json"
    ),
)

from server.core.dataset_store import DATASTORE  # noqa: E402
from server.preprocessing.missing_router import missing_summary  # noqa: E402
from server.preprocessing.outlier_service import outlier_service  # noqa: E402
import server.preprocessing.missing_router as missing_router_module  # noqa: E402


PROJECT_ID = "table-first-contract"
USER = {"userId": "table-first-contract-owner"}


def modeling_frame(*, include_true_null: bool = True) -> pd.DataFrame:
    row_count = 96
    target = [1 if index % 4 == 0 else 0 for index in range(row_count)]
    signal = [float(35 + ((index * 7) % 54)) for index in range(row_count)]
    signal[2] = -9.0
    signal[7] = -8.0
    signal[13] = -7.0
    signal[-1] = 450.0
    if include_true_null:
        signal[19] = np.nan
    return pd.DataFrame(
        {
            "signal_driver": signal,
            "secondary": [
                float(5 + ((index * 11 + index // 3) % 31))
                for index in range(row_count)
            ],
            "bad_flag": target,
        }
    )


def configure(frame: pd.DataFrame) -> None:
    DATASTORE.reset_all()
    DATASTORE.set_raw(frame)
    DATASTORE.set_target("bad_flag")
    DATASTORE.meta["selected_columns"] = ["signal_driver", "secondary"]
    DATASTORE.meta["dataset_version"] = "table-first-v1"


class TableFirstBackendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original_authorize = missing_router_module.authorize_modeling_scope
        missing_router_module.authorize_modeling_scope = (
            lambda user, project_id, permission: project_id
        )

    @classmethod
    def tearDownClass(cls) -> None:
        missing_router_module.authorize_modeling_scope = cls.original_authorize

    def tearDown(self) -> None:
        DATASTORE.reset_all()

    def test_outlier_summary_supports_table_stats_iv_and_active_cutoff_histograms(
        self,
    ) -> None:
        frame = modeling_frame()
        configure(frame)

        payload = outlier_service.summary(
            frame,
            target="bad_flag",
            event_value=1,
            problem_type="classification",
            selected_columns=DATASTORE.get_selected_columns(),
        )

        self.assertEqual(payload["scope"], "full_dataset")
        self.assertEqual(len(payload["features"]), 2)
        signals = [
            abs(float(row["signal_metric"] or 0))
            for row in payload["features"]
        ]
        self.assertEqual(signals, sorted(signals, reverse=True))

        row = next(
            item
            for item in payload["features"]
            if item["feature"] == "signal_driver"
        )
        for field in (
            "datatype",
            "nonmissing_count",
            "ordinary_nonmissing_count",
            "missing_count",
            "distinct_count",
            "mean",
            "standard_deviation",
            "minimum",
            "maximum",
            "signal_metric",
            "rendered_sample",
            "rendered_sample_count",
            "quantiles",
            "methods",
        ):
            self.assertIn(field, row)
        self.assertEqual(
            set(row["quantiles"]),
            {"p01", "p05", "p25", "median", "p75", "p95", "p99"},
        )
        self.assertNotIn(-9.0, row["rendered_sample"])
        self.assertNotIn(-8.0, row["rendered_sample"])
        self.assertNotIn(-7.0, row["rendered_sample"])
        self.assertEqual(row["special_value_count"], 3)
        self.assertEqual(row["missing_count"], 1)

        active = row["methods"]["IQR_1_5"]
        self.assertLess(active["lower_threshold"], active["upper_threshold"])
        self.assertGreaterEqual(active["outlier_count"], 1)
        self.assertGreater(active["outlier_rate"], 0)

    def test_outlier_apply_resolves_global_inheritance_without_overwriting_override(
        self,
    ) -> None:
        frame = modeling_frame()
        configure(frame)

        _, applications = outlier_service.apply(
            frame,
            config={
                "signal_driver": "USE_GLOBAL",
                "secondary": "NONE",
            },
            global_method="PCT_05_95",
            target="bad_flag",
            selected_columns=DATASTORE.get_selected_columns(),
        )

        applied = {row["feature"]: row for row in applications}
        self.assertEqual(
            applied["signal_driver"]["applied_method"], "PCT_05_95"
        )
        self.assertEqual(applied["secondary"]["applied_method"], "NONE")
        self.assertEqual(applied["secondary"]["changed_values"], 0)

    def test_missing_summary_separates_nulls_and_specials_and_supplies_histograms(
        self,
    ) -> None:
        configure(modeling_frame())

        payload = missing_summary(PROJECT_ID, event_value=1, user=USER)
        row = payload["stats"]["signal_driver"]

        self.assertEqual(payload["scope"], "full_dataset")
        for field in (
            "missing",
            "missingPct",
            "nonmissing_count",
            "observed_count",
            "distinct_count",
            "mean",
            "mode",
            "standard_deviation",
            "minimum",
            "first_quartile",
            "median",
            "third_quartile",
            "maximum",
            "information_value",
            "association_status",
            "distribution",
        ):
            self.assertIn(field, row)
        self.assertEqual(row["missing"], 1)
        self.assertEqual(row["special_value_count"], 3)
        self.assertEqual(
            row["observed_count"],
            len(modeling_frame()) - row["missing"] - row["special_value_count"],
        )
        self.assertIsInstance(row["information_value"], float)
        self.assertIsNotNone(row["mode"])

        distribution = row["distribution"]
        self.assertEqual(distribution["kind"], "numeric")
        self.assertEqual(distribution["missing_count"], 1)
        self.assertEqual(distribution["special_value_count"], 3)
        self.assertEqual(
            sum(item["count"] for item in distribution["bins"]),
            distribution["ordinary_numeric_count"],
        )
        self.assertLess(
            distribution["reference_cutoffs"]["lower"],
            distribution["reference_cutoffs"]["upper"],
        )
        self.assertIn(
            "not missing-value treatments",
            distribution["cutoff_semantics"],
        )

    def test_zero_null_summary_retains_stats_iv_and_distribution_evidence(
        self,
    ) -> None:
        configure(modeling_frame(include_true_null=False))

        payload = missing_summary(PROJECT_ID, event_value=1, user=USER)
        row = payload["stats"]["signal_driver"]

        self.assertEqual(row["missing"], 0)
        self.assertEqual(row["distribution"]["missing_count"], 0)
        self.assertGreater(len(row["distribution"]["bins"]), 0)
        self.assertIsNotNone(row["distribution"]["reference_cutoffs"])
        self.assertIsInstance(row["information_value"], float)
        self.assertEqual(row["special_value_count"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
