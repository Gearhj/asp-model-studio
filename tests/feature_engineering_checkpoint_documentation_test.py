from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.core.session_checkpoint import _decode, _encode_dataset  # noqa: E402
from server.preprocessing.preparation_documentation_router import (  # noqa: E402
    _feature_documentation,
)


class FeatureEngineeringCheckpointDocumentationTests(unittest.TestCase):
    def test_checkpoint_preserves_feature_manifest_when_sibling_leaf_is_unsupported(
        self,
    ) -> None:
        feature_manifest = {
            "project_id": "atlas-checkpoint-project",
            "dataset_id": "ds-checkpoint",
            "dataset_version_id": "v-checkpoint",
            "manifest_hash": "fm-checkpoint",
            "features": [
                {
                    "feature_name": "credit_history_span",
                    "origin": "arithmetic",
                    "selected": True,
                    "eligibility_status": "eligible",
                    "source_features": ["oldest_trade_months", "newest_trade_months"],
                }
            ],
        }
        store = SimpleNamespace(
            data_revision=12,
            raw_df=None,
            processed_df=None,
            target="bad_flag",
            X_train=None,
            X_test=None,
            y_train=None,
            y_test=None,
            meta={
                "feature_manifest": feature_manifest,
                "runtime_handle": object(),
                "nested_metadata": {
                    "retained": "yes",
                    "unsupported_leaf": object(),
                },
            },
        )

        encoded = _encode_dataset(store)
        restored_meta = _decode(encoded["meta"])

        self.assertEqual(restored_meta["feature_manifest"], feature_manifest)
        self.assertEqual(restored_meta["nested_metadata"]["retained"], "yes")
        self.assertIsNone(restored_meta["runtime_handle"])
        self.assertIsNone(restored_meta["nested_metadata"]["unsupported_leaf"])

    def test_documentation_confirms_selected_features_and_audits_excluded_plans(
        self,
    ) -> None:
        identity = {
            "project_id": "atlas-documentation-project",
            "dataset_id": "ds-documentation",
            "dataset_version_id": "v-documentation",
        }
        manifest_hash = "fm-documentation"
        manifest = {
            **identity,
            "dataset_version": identity["dataset_version_id"],
            "manifest_version": manifest_hash,
            "manifest_hash": manifest_hash,
            "validation_status": "passed",
            "materialization_status": "current",
            "materialized_manifest_hash": manifest_hash,
            "confirmation_status": "confirmed",
            "confirmed_manifest_hash": manifest_hash,
            "split_status": "stale",
            "features": [
                {
                    "feature_name": "ExternalRiskEstimate",
                    "origin": "original",
                    "selected": True,
                    "eligibility_status": "eligible",
                    "materialization_status": "source",
                },
                {
                    "feature_name": "risk_utilization_interaction",
                    "origin": "interaction",
                    "selected": True,
                    "eligibility_status": "eligible",
                    "materialization_status": "materialized",
                    "source_features": [
                        "ExternalRiskEstimate",
                        "PercentTradesWBalance",
                    ],
                    "formula_or_rule": (
                        "ExternalRiskEstimate * PercentTradesWBalance"
                    ),
                    "user_rationale": "Retain the selected interaction.",
                },
                {
                    "feature_name": "excluded_polynomial_draft",
                    "origin": "polynomial",
                    "selected": False,
                    "eligibility_status": "eligible",
                    "materialization_status": "not_materialized",
                    "source_features": ["AverageMInFile"],
                    "formula_or_rule": "AverageMInFile ** 2",
                    "exclusion_reason": "Not selected for this governed contract.",
                },
                {
                    "feature_name": "ineligible_date_draft",
                    "origin": "date",
                    "selected": True,
                    "eligibility_status": "ineligible",
                    "materialization_status": "not_materialized",
                    "source_features": ["AverageMInFile"],
                    "exclusion_reason": "No governed datetime source is available.",
                },
            ],
        }

        documentation = _feature_documentation(manifest, identity)

        self.assertEqual(documentation["status"], "confirmed")
        self.assertEqual(
            [row["feature_name"] for row in documentation["accepted_features"]],
            ["risk_utilization_interaction"],
        )
        self.assertEqual(
            documentation["materialized_features"],
            ["risk_utilization_interaction"],
        )
        self.assertEqual(
            [row["feature_name"] for row in documentation["excluded_features"]],
            ["excluded_polynomial_draft", "ineligible_date_draft"],
        )
        self.assertEqual(
            documentation["excluded_features"][0]["exclusion_reason"],
            "Not selected for this governed contract.",
        )
        self.assertEqual(documentation["split_status"], "stale")


if __name__ == "__main__":
    unittest.main()
