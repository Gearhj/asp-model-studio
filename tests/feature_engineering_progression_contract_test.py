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
        / f"atlas_feature_progression_{uuid.uuid4().hex[:10]}.json"
    ),
)

from server.core.dataset_store import DATASTORE  # noqa: E402
from server.features.feature_service import (  # noqa: E402
    _apply_feature,
    confirm_manifest,
    get_manifest,
    materialize_manifest,
    preview_features,
    update_manifest,
)
from server.features.feature_types import (  # noqa: E402
    FeatureDefinitionInput,
    FeatureManifestUpdateRequest,
)


PROJECT_ID = "feature-progression-contract"


def governed_frame() -> pd.DataFrame:
    rows = 80
    target = [index % 2 for index in range(rows)]
    bureau_score = [float(500 + index) for index in range(rows)]
    bureau_score[3] = -9.0
    bureau_score[7] = -8.0
    bureau_score[11] = -7.0
    return pd.DataFrame(
        {
            "RiskPerformance": [
                "Bad" if value == 1 else "Good" for value in target
            ],
            "bureau_score": bureau_score,
            # Repeat every value once in each target class so this ordinary
            # predictor cannot be mistaken for a deterministic target source.
            "trade_count": [
                float(5 + (index // 2) % 12) for index in range(rows)
            ],
            "bad_flag": target,
        }
    )


def configure() -> None:
    DATASTORE.reset_all()
    DATASTORE.set_raw(governed_frame())
    DATASTORE.set_target("bad_flag")
    # Deliberately include both forbidden fields. Server authorization, not the
    # client selection, owns the exclusion.
    DATASTORE.meta["selected_columns"] = [
        "bad_flag",
        "RiskPerformance",
        "bureau_score",
        "trade_count",
    ]
    DATASTORE.meta["dataset_version"] = "feature-progression-v1"


def safe_definition() -> FeatureDefinitionInput:
    return FeatureDefinitionInput(
        feature_id="feature-bureau-trade",
        feature_name="bureau_score_x_trade_count",
        origin="interaction",
        source_features=["bureau_score", "trade_count"],
        transformation_type="interaction",
        formula_or_rule="bureau_score * trade_count",
        output_datatype="numeric",
        config={"preserve_bureau_special_values": True},
    )


class FeatureEngineeringProgressionBackendTests(unittest.TestCase):
    def tearDown(self) -> None:
        DATASTORE.reset_all()

    def test_client_selection_cannot_reintroduce_target_or_target_source(self):
        configure()
        manifest = get_manifest()
        names = {row["feature_name"] for row in manifest["features"]}
        self.assertNotIn("bad_flag", names)
        source = next(
            row
            for row in manifest["features"]
            if row["feature_name"] == "bureau_score"
        )
        self.assertEqual(source["profile_scope"], "full_dataset")
        self.assertGreater(source["summary_statistics"]["row_count"], 0)
        self.assertIn("standard_deviation", source["summary_statistics"])

        target_source = next(
            row
            for row in manifest["features"]
            if row["feature_name"] == "RiskPerformance"
        )
        self.assertEqual(target_source["eligibility_status"], "excluded")
        self.assertFalse(target_source["selected"])
        self.assertIn("Deterministic source", target_source["exclusion_reason"])

        unsafe = FeatureDefinitionInput(
            feature_name="target_source_reentry",
            origin="categorical_rule",
            source_features=["RiskPerformance"],
            transformation_type="categorical_rule",
            formula_or_rule="RiskPerformance == Bad",
            output_datatype="categorical",
            config={
                "rules": [
                    {
                        "op": "equals",
                        "value": "Bad",
                        "then_label": "bad",
                    }
                ]
            },
        )
        with self.assertRaisesRegex(ValueError, "excluded predictor"):
            update_manifest(
                FeatureManifestUpdateRequest(
                    project_id=PROJECT_ID,
                    dataset_version="feature-progression-v1",
                    features=[unsafe],
                )
            )

    def test_bureau_special_values_survive_feature_transformation(self):
        frame = governed_frame()
        binned = _apply_feature(
            frame,
            {
                "feature_name": "bureau_band",
                "origin": "numeric_bin",
                "source_features": ["bureau_score"],
                "config": {
                    "cut_points": [540.0],
                    "labels": ["lower", "higher"],
                    "preserve_bureau_special_values": True,
                },
            },
        )
        self.assertEqual(binned.iloc[3], "Bureau special -9")
        self.assertEqual(binned.iloc[7], "Bureau special -8")
        self.assertEqual(binned.iloc[11], "Bureau special -7")

    def test_reviewer_deselection_of_ordinary_original_is_hash_stable(self):
        configure()
        initial = get_manifest()
        trade_count = next(
            row
            for row in initial["features"]
            if row["feature_name"] == "trade_count"
        )
        reviewer_reason = "Reviewer excluded after redundancy review."
        deselected = FeatureDefinitionInput(**trade_count).model_copy(
            update={
                "selected": False,
                "exclusion_reason": reviewer_reason,
            }
        )

        saved = update_manifest(
            FeatureManifestUpdateRequest(
                project_id=PROJECT_ID,
                dataset_version="feature-progression-v1",
                features=[deselected],
            )
        )
        saved_row = next(
            row
            for row in saved["features"]
            if row["feature_name"] == "trade_count"
        )
        self.assertEqual(saved_row["eligibility_status"], "eligible")
        self.assertFalse(saved_row["selected"])
        self.assertEqual(saved_row["exclusion_reason"], reviewer_reason)

        refreshed = get_manifest()
        refreshed_row = next(
            row
            for row in refreshed["features"]
            if row["feature_name"] == "trade_count"
        )
        self.assertEqual(refreshed["manifest_hash"], saved["manifest_hash"])
        self.assertEqual(refreshed_row["eligibility_status"], "eligible")
        self.assertFalse(refreshed_row["selected"])
        self.assertEqual(refreshed_row["exclusion_reason"], reviewer_reason)

    def test_confirmation_requires_exact_previewed_materialization(self):
        configure()
        definition = safe_definition()
        manifest = update_manifest(
            FeatureManifestUpdateRequest(
                project_id=PROJECT_ID,
                dataset_version="feature-progression-v1",
                features=[definition],
            )
        )
        refreshed = get_manifest()
        self.assertEqual(
            refreshed["manifest_hash"],
            manifest["manifest_hash"],
            "an immediate manifest refresh must not change the saved contract hash",
        )

        with self.assertRaisesRegex(ValueError, "Materialize"):
            confirm_manifest(manifest["manifest_hash"], "")
        with self.assertRaisesRegex(ValueError, "Preview"):
            materialize_manifest(manifest["manifest_hash"], "")

        preview = preview_features(
            [definition],
            20,
            manifest["manifest_hash"],
        )
        materialized = materialize_manifest(
            manifest["manifest_hash"],
            preview["preview_hash"],
        )
        confirmed = confirm_manifest(
            manifest["manifest_hash"],
            materialized["materialization_hash"],
        )

        self.assertEqual(confirmed["confirmation_status"], "confirmed")
        self.assertEqual(
            confirmed["confirmed_manifest_hash"],
            confirmed["manifest_hash"],
        )
        self.assertEqual(
            confirmed["materialized_manifest_hash"],
            confirmed["manifest_hash"],
        )

    def test_a_changed_contract_invalidates_confirmation(self):
        configure()
        definition = safe_definition()
        manifest = update_manifest(
            FeatureManifestUpdateRequest(
                project_id=PROJECT_ID,
                dataset_version="feature-progression-v1",
                features=[definition],
            )
        )
        refreshed = get_manifest()
        self.assertEqual(
            refreshed["manifest_hash"],
            manifest["manifest_hash"],
            "an immediate manifest refresh must not change the saved contract hash",
        )
        preview = preview_features(
            [definition],
            20,
            manifest["manifest_hash"],
        )
        materialized = materialize_manifest(
            manifest["manifest_hash"],
            preview["preview_hash"],
        )
        confirm_manifest(
            manifest["manifest_hash"],
            materialized["materialization_hash"],
        )

        changed = definition.model_copy(
            update={
                "origin": "arithmetic",
                "transformation_type": "arithmetic",
                "formula_or_rule": "bureau_score + trade_count",
                "config": {
                    "operation": "add",
                    "preserve_bureau_special_values": True,
                },
            }
        )
        stale = update_manifest(
            FeatureManifestUpdateRequest(
                project_id=PROJECT_ID,
                dataset_version="feature-progression-v1",
                features=[changed],
            )
        )
        self.assertEqual(stale["materialization_status"], "stale")
        self.assertEqual(stale["confirmation_status"], "required")
        self.assertEqual(stale["confirmed_manifest_hash"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
