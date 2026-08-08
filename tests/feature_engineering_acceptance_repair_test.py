"""Focused backend acceptance contracts for the Feature Engineering repair.

This suite never opens the live Dataset Library, persistence databases, or
workflow checkpoint.  It supplies one exact synthetic canonical identity and
binds both Feature Manifest persistence and checkpoint configuration to a
unique temporary directory before importing the backend modules.

Run:
    .venv/Scripts/python.exe tests/feature_engineering_acceptance_repair_test.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

TEST_DATA_ROOT = (REPOSITORY_ROOT / ".tmp" / "test-data").resolve()
TEST_DATA_ROOT.mkdir(parents=True, exist_ok=True)
TEST_ROOT = (
    TEST_DATA_ROOT / f"atlas_feature_acceptance_{uuid.uuid4().hex[:16]}"
).resolve()
TEST_ROOT.mkdir(parents=True, exist_ok=False)
CHECKPOINT_PATH = TEST_ROOT / "workflow_checkpoint.json"
DEFAULT_MANIFEST_ROOT = TEST_ROOT / "feature_manifests"
os.environ["ATLAS_CHECKPOINT_PATH"] = str(CHECKPOINT_PATH)
os.environ["ATLAS_FEATURE_MANIFEST_ROOT"] = str(DEFAULT_MANIFEST_ROOT)

from server.core.dataset_store import DATASTORE  # noqa: E402
import server.core.session_checkpoint as checkpoint  # noqa: E402
from server.features.feature_service import (  # noqa: E402
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


PROJECT_ID = "atlas-feature-acceptance-isolated"
DATASET_ID = "ds-feature-acceptance-isolated"
DATASET_VERSION_ID = "v-feature-acceptance-isolated"
TARGET = "bad_flag"
TARGET_SOURCE = "RiskPerformance"


def identity_kwargs() -> dict[str, str]:
    return {
        "project_id": PROJECT_ID,
        "expected_dataset_id": DATASET_ID,
        "expected_dataset_version_id": DATASET_VERSION_ID,
        "legacy_dataset_version": DATASET_VERSION_ID,
    }


def exact_test_identity(
    project_id: str,
    *,
    expected_dataset_id: str = "",
    expected_dataset_version_id: str = "",
    legacy_dataset_version: str = "",
    require_expected: bool = False,
    **_unused: object,
) -> dict[str, str]:
    """Synthetic stand-in for the immutable Dataset Library authority."""

    if require_expected:
        assert expected_dataset_id == DATASET_ID
        assert expected_dataset_version_id == DATASET_VERSION_ID
    assert project_id == PROJECT_ID
    assert not legacy_dataset_version or legacy_dataset_version == DATASET_VERSION_ID
    return {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": DATASET_VERSION_ID,
    }


def governed_frame() -> pd.DataFrame:
    """Small deterministic frame with ordinary, missing, and bureau values."""

    row_count = 80
    target = [index % 2 for index in range(row_count)]
    external_risk = [float(40 + index) for index in range(row_count)]
    external_risk[3] = -9.0
    external_risk[7] = -8.0
    external_risk[11] = -7.0
    external_risk[13] = float("nan")
    revolving_burden = [float(((index // 2) % 12) * 10) for index in range(row_count)]
    revolving_burden[5] = -9.0
    total_trades = [float(12 + ((index // 2) % 20)) for index in range(row_count)]
    satisfactory_trades = [value - float((index // 4) % 4) for index, value in enumerate(total_trades)]
    application_dates = [
        (pd.Timestamp("2023-01-01") + pd.Timedelta(days=index)).date().isoformat()
        for index in range(row_count)
    ]
    return pd.DataFrame(
        {
            TARGET_SOURCE: ["Bad" if value else "Good" for value in target],
            "ExternalRiskEstimate": external_risk,
            "PercentTradesNeverDelq": [
                float(55 + ((index // 2) % 20) * 2) for index in range(row_count)
            ],
            "NetFractionRevolvingBurden": revolving_burden,
            "AverageMInFile": [
                float(24 + ((index // 2) % 30)) for index in range(row_count)
            ],
            "NumTotalTrades": total_trades,
            "NumSatisfactoryTrades": satisfactory_trades,
            "application_date": application_dates,
            "account_date_note": ["not-a-date" for _ in range(row_count)],
            TARGET: target,
        }
    )


def configure_store() -> None:
    DATASTORE.reset_all()
    frame = governed_frame()
    DATASTORE.set_raw(frame)
    DATASTORE.set_target(TARGET)
    # Include both forbidden inputs deliberately. The backend authorization
    # contract, rather than the caller, must own their exclusion.
    DATASTORE.meta["selected_columns"] = [str(column) for column in frame.columns]
    DATASTORE.meta.update(
        {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": DATASET_VERSION_ID,
            "dataset_version": DATASET_VERSION_ID,
            "dataset_identity_status": "current",
            "activation_revision": 1,
        }
    )


def update_request(
    features: list[FeatureDefinitionInput],
) -> FeatureManifestUpdateRequest:
    return FeatureManifestUpdateRequest(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        dataset_version_id=DATASET_VERSION_ID,
        dataset_version=DATASET_VERSION_ID,
        features=features,
    )


def interaction_definition(*, selected: bool = True) -> FeatureDefinitionInput:
    return FeatureDefinitionInput(
        feature_name="Acceptance_ExternalRisk_x_NeverDelq",
        display_name="External risk x never delinquent",
        origin="interaction",
        source_features=["ExternalRiskEstimate", "PercentTradesNeverDelq"],
        transformation_type="interaction",
        formula_or_rule="ExternalRiskEstimate * PercentTradesNeverDelq",
        output_datatype="numeric",
        selected=selected,
        config={
            "preserve_bureau_special_values": True,
            "special_value_policy": "preserve_source_sentinel",
        },
    )


def numeric_bin_definition(*, selected: bool = True) -> FeatureDefinitionInput:
    return FeatureDefinitionInput(
        feature_name="Acceptance_ExternalRisk_Band",
        display_name="External risk band",
        origin="numeric_bin",
        source_features=["ExternalRiskEstimate"],
        transformation_type="numeric_bin",
        formula_or_rule="cut(ExternalRiskEstimate; 60, 70, 80)",
        output_datatype="categorical",
        selected=selected,
        config={
            "binning_mode": "custom",
            "cut_points": [60, 70, 80],
            "labels": ["Below 60", "60 to 69", "70 to 79", "80 or above"],
            "missing_label": "Missing",
            "special_value_label": "Bureau special",
            "special_value_policy": "separate_category",
            "preserve_bureau_special_values": True,
        },
    )


def rule_definition(*, selected: bool = True) -> FeatureDefinitionInput:
    return FeatureDefinitionInput(
        feature_name="Acceptance_High_Revolving_Burden",
        display_name="High revolving burden",
        origin="categorical_rule",
        source_features=["NetFractionRevolvingBurden"],
        transformation_type="categorical_rule",
        formula_or_rule="NetFractionRevolvingBurden >= 75",
        output_datatype="categorical",
        selected=selected,
        config={
            "rules": [
                {
                    "op": "greater_than_or_equal",
                    "value": 75,
                    "then_label": "75 or above",
                }
            ],
            "else_label": "Below 75",
            "special_value_label": "Bureau special",
            "special_value_policy": "separate_category",
            "preserve_bureau_special_values": True,
        },
    )


def polynomial_definition(*, selected: bool = True) -> FeatureDefinitionInput:
    return FeatureDefinitionInput(
        feature_name="Acceptance_AverageMInFile_Squared",
        display_name="Average months in file squared",
        origin="polynomial",
        source_features=["AverageMInFile"],
        transformation_type="polynomial",
        formula_or_rule="AverageMInFile ^ 2",
        output_datatype="numeric",
        selected=selected,
        config={
            "degree": 2,
            "preserve_bureau_special_values": True,
            "review_warnings": [
                {"code": "polynomial_scale_review"},
                {"code": "polynomial_multicollinearity_review"},
            ],
        },
    )


def arithmetic_definition(*, selected: bool = True) -> FeatureDefinitionInput:
    return FeatureDefinitionInput(
        feature_name="Acceptance_Unsatisfactory_Trades",
        display_name="Unsatisfactory trades",
        origin="arithmetic",
        source_features=["NumTotalTrades", "NumSatisfactoryTrades"],
        transformation_type="arithmetic",
        formula_or_rule="NumTotalTrades - NumSatisfactoryTrades",
        output_datatype="numeric",
        selected=selected,
        config={
            "operation": "subtract",
            "left_unit": "count",
            "right_unit": "count",
            "result_unit": "count",
            "result_domain": "nonnegative",
            "domain_evidence": {
                "left_greater_than_or_equal_right": True,
                "note": "Satisfactory trades are a subset of total trades.",
            },
            "preserve_bureau_special_values": True,
        },
    )


def date_derived_definition(*, selected: bool = True) -> FeatureDefinitionInput:
    return FeatureDefinitionInput(
        feature_name="Acceptance_Application_Month",
        display_name="Application month",
        origin="date-derived",
        source_features=["application_date"],
        transformation_type="date-derived",
        formula_or_rule="month(application_date)",
        output_datatype="numeric",
        selected=selected,
        config={"component": "month"},
    )


def all_builder_definitions() -> list[FeatureDefinitionInput]:
    return [
        interaction_definition(),
        numeric_bin_definition(),
        rule_definition(),
        polynomial_definition(),
        arithmetic_definition(),
        date_derived_definition(),
    ]


class FeatureEngineeringAcceptanceRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case_root = TEST_ROOT / self._testMethodName
        self.manifest_root = self.case_root / "feature_manifests"
        self.checkpoint_path = self.case_root / "workflow_checkpoint.json"
        self.case_root.mkdir(parents=True, exist_ok=True)
        os.environ["ATLAS_FEATURE_MANIFEST_ROOT"] = str(self.manifest_root)
        os.environ["ATLAS_CHECKPOINT_PATH"] = str(self.checkpoint_path)
        checkpoint.CHECKPOINT_PATH = self.checkpoint_path.resolve()
        configure_store()
        self.identity_patch = patch(
            "server.features.feature_service.assert_expected_active_identity",
            side_effect=exact_test_identity,
        )
        self.checkpoint_schedule_patch = patch(
            "server.features.feature_service.schedule_checkpoint_save",
            return_value=True,
        )
        self.identity_patch.start()
        self.checkpoint_schedule_patch.start()

    def tearDown(self) -> None:
        self.checkpoint_schedule_patch.stop()
        self.identity_patch.stop()
        DATASTORE.reset_all()

    def _save_preview_materialize(
        self,
        definitions: list[FeatureDefinitionInput],
        *,
        preview_payload: list[FeatureDefinitionInput] | None = None,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        manifest = update_manifest(update_request(definitions))
        preview = preview_features(
            preview_payload if preview_payload is not None else definitions,
            20,
            str(manifest["manifest_hash"]),
            **identity_kwargs(),
        )
        materialized = materialize_manifest(
            str(manifest["manifest_hash"]),
            str(preview["preview_hash"]),
            **identity_kwargs(),
        )
        return manifest, preview, materialized

    def test_zero_feature_contract_saves_previews_materializes_and_confirms(self) -> None:
        manifest, preview, materialized = self._save_preview_materialize([])
        confirmed = confirm_manifest(
            str(manifest["manifest_hash"]),
            str(materialized["materialization_hash"]),
            **identity_kwargs(),
        )

        self.assertEqual(preview["created_features"], [])
        self.assertEqual(preview["columns"], [])
        self.assertEqual(materialized["engineered_feature_count"], 0)
        self.assertEqual(materialized["materialized_features"], [])
        self.assertEqual(confirmed["confirmation_status"], "confirmed")
        self.assertEqual(
            confirmed["confirmed_manifest_hash"], manifest["manifest_hash"]
        )
        self.assertEqual(
            confirmed["materialized_manifest_hash"], manifest["manifest_hash"]
        )
        self.assertEqual(confirmed["persistence_status"], "persisted")

    def test_all_six_builders_materialize_deterministically_with_bureau_values(self) -> None:
        definitions = all_builder_definitions()
        manifest, preview, materialized = self._save_preview_materialize(definitions)
        expected_names = [definition.feature_name for definition in definitions]

        self.assertEqual(preview["created_features"], expected_names)
        self.assertEqual(materialized["materialized_features"], expected_names)
        self.assertEqual(materialized["engineered_feature_count"], 6)
        self.assertEqual(materialized["manifest_hash"], manifest["manifest_hash"])
        frame = DATASTORE.processed_df
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertTrue(set(expected_names).issubset(frame.columns))
        self.assertEqual(frame.loc[3, "Acceptance_ExternalRisk_x_NeverDelq"], -9.0)
        self.assertEqual(frame.loc[3, "Acceptance_ExternalRisk_Band"], "Bureau special")
        self.assertEqual(frame.loc[13, "Acceptance_ExternalRisk_Band"], "Missing")
        self.assertEqual(frame.loc[5, "Acceptance_High_Revolving_Burden"], "Bureau special")
        self.assertEqual(
            frame.loc[10, "Acceptance_AverageMInFile_Squared"],
            frame.loc[10, "AverageMInFile"] ** 2,
        )
        self.assertGreaterEqual(
            float(frame["Acceptance_Unsatisfactory_Trades"].min()), 0.0
        )
        self.assertEqual(frame.loc[0, "Acceptance_Application_Month"], 1)
        self.assertEqual(frame.loc[31, "Acceptance_Application_Month"], 2)
        original_date = next(
            row
            for row in manifest["features"]
            if row["feature_name"] == "application_date"
        )
        self.assertRegex(str(original_date["output_datatype"]), r"date|time")
        refreshed = get_manifest(**identity_kwargs())
        engineered = {
            row["feature_name"]: row
            for row in refreshed["features"]
            if row["origin"] != "original"
        }
        self.assertEqual(set(engineered), set(expected_names))
        for row in engineered.values():
            self.assertEqual(row["materialization_status"], "materialized")
            self.assertEqual(row["profile_scope"], "full_dataset")
            self.assertEqual(row["summary_statistics"]["row_count"], len(frame))

    def test_target_target_source_and_numeric_duration_date_are_rejected(self) -> None:
        baseline = get_manifest(**identity_kwargs())
        original_names = {
            row["feature_name"]
            for row in baseline["features"]
            if row["origin"] == "original"
        }
        self.assertNotIn(TARGET, original_names)
        target_source_row = next(
            row
            for row in baseline["features"]
            if row["feature_name"] == TARGET_SOURCE
        )
        self.assertEqual(target_source_row["eligibility_status"], "excluded")
        self.assertFalse(target_source_row["selected"])
        self.assertIn("Deterministic source", target_source_row["exclusion_reason"])

        unsafe_definitions = [
            (
                FeatureDefinitionInput(
                    feature_name="Acceptance_Target_Squared",
                    origin="polynomial",
                    source_features=[TARGET],
                    transformation_type="polynomial",
                    formula_or_rule=f"{TARGET} ^ 2",
                    config={"degree": 2},
                ),
                "cannot use the target column",
            ),
            (
                FeatureDefinitionInput(
                    feature_name="Acceptance_Target_Source_Rule",
                    origin="categorical_rule",
                    source_features=[TARGET_SOURCE],
                    transformation_type="categorical_rule",
                    formula_or_rule=f"{TARGET_SOURCE} == Bad",
                    output_datatype="categorical",
                    config={
                        "rules": [
                            {"op": "equals", "value": "Bad", "then_label": "Bad"}
                        ],
                        "else_label": "Good",
                    },
                ),
                "excluded predictor",
            ),
            (
                FeatureDefinitionInput(
                    feature_name="Acceptance_Fake_File_Year",
                    origin="date-derived",
                    source_features=["AverageMInFile"],
                    transformation_type="date-derived",
                    formula_or_rule="year(AverageMInFile)",
                    config={"component": "year"},
                ),
                "requires a governed date or timestamp predictor",
            ),
            (
                FeatureDefinitionInput(
                    feature_name="Acceptance_Arbitrary_Text_Year",
                    origin="date-derived",
                    source_features=["account_date_note"],
                    transformation_type="date-derived",
                    formula_or_rule="year(account_date_note)",
                    config={"component": "year"},
                ),
                "requires a governed date or timestamp predictor",
            ),
        ]

        for definition, message in unsafe_definitions:
            with self.subTest(feature=definition.feature_name):
                with self.assertRaisesRegex(ValueError, message):
                    update_manifest(update_request([definition]))

    def test_excluded_planned_feature_is_not_previewed_or_materialized(self) -> None:
        selected = interaction_definition()
        excluded = polynomial_definition(selected=False).model_copy(
            update={"exclusion_reason": "Acceptance-only definition excluded by reviewer."}
        )
        manifest, preview, materialized = self._save_preview_materialize(
            [selected, excluded],
            # The request payload deliberately contains the excluded definition;
            # the saved manifest remains the execution authority.
            preview_payload=[selected, excluded.model_copy(update={"selected": True})],
        )

        self.assertEqual(preview["created_features"], [selected.feature_name])
        self.assertEqual(materialized["materialized_features"], [selected.feature_name])
        frame = DATASTORE.processed_df
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertIn(selected.feature_name, frame.columns)
        self.assertNotIn(excluded.feature_name, frame.columns)
        refreshed = get_manifest(**identity_kwargs())
        excluded_row = next(
            row
            for row in refreshed["features"]
            if row["feature_name"] == excluded.feature_name
        )
        self.assertFalse(excluded_row["selected"])
        self.assertEqual(excluded_row["creation_status"], "planned")
        self.assertEqual(excluded_row["materialization_status"], "not_materialized")
        self.assertEqual(excluded_row["profile_scope"], "not_profiled")
        self.assertEqual(excluded_row["summary_statistics"], {})
        self.assertEqual(materialized["manifest_hash"], manifest["manifest_hash"])

    def test_invalid_bin_and_arithmetic_contracts_fail_closed(self) -> None:
        invalid_definitions = [
            (
                numeric_bin_definition().model_copy(
                    update={
                        "feature_name": "Acceptance_Invalid_Bin_Labels",
                        "config": {
                            **numeric_bin_definition().config,
                            "labels": ["Low", "Middle", "High"],
                        },
                    }
                ),
                "labels must contain exactly one non-empty label more",
            ),
            (
                numeric_bin_definition().model_copy(
                    update={
                        "feature_name": "Acceptance_Unordered_Bins",
                        "config": {
                            **numeric_bin_definition().config,
                            "cut_points": [70, 60, 80],
                        },
                    }
                ),
                "must be unique and strictly increasing",
            ),
            (
                FeatureDefinitionInput(
                    feature_name="Acceptance_Incompatible_Units",
                    origin="arithmetic",
                    source_features=["NumTotalTrades", "ExternalRiskEstimate"],
                    transformation_type="arithmetic",
                    formula_or_rule="NumTotalTrades - ExternalRiskEstimate",
                    config={
                        "operation": "subtract",
                        "left_unit": "count",
                        "right_unit": "score",
                        "result_domain": "unrestricted",
                    },
                ),
                "compatible governed units",
            ),
            (
                FeatureDefinitionInput(
                    feature_name="Acceptance_Negative_Domain",
                    origin="arithmetic",
                    source_features=["NumSatisfactoryTrades", "NumTotalTrades"],
                    transformation_type="arithmetic",
                    formula_or_rule="NumSatisfactoryTrades - NumTotalTrades",
                    config={
                        "operation": "subtract",
                        "left_unit": "count",
                        "right_unit": "count",
                        "result_domain": "nonnegative",
                    },
                ),
                "violates the governed nonnegative domain",
            ),
        ]

        for definition, message in invalid_definitions:
            with self.subTest(feature=definition.feature_name):
                with self.assertRaisesRegex(ValueError, message):
                    update_manifest(update_request([definition]))

    def test_repeat_materialization_is_idempotent(self) -> None:
        manifest, preview, first = self._save_preview_materialize(
            [interaction_definition()]
        )
        revision_after_first = int(DATASTORE.current().data_revision)
        history_after_first = list(get_manifest(**identity_kwargs())["execution_history"])

        second = materialize_manifest(
            str(manifest["manifest_hash"]),
            str(preview["preview_hash"]),
            **identity_kwargs(),
        )

        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(second["materialization_hash"], first["materialization_hash"])
        self.assertEqual(second["materialized_features"], first["materialized_features"])
        self.assertEqual(int(DATASTORE.current().data_revision), revision_after_first)
        self.assertEqual(
            get_manifest(**identity_kwargs())["execution_history"], history_after_first
        )

    def test_manifest_version_is_durable_and_reloads_by_exact_identity(self) -> None:
        saved = update_manifest(update_request([interaction_definition()]))
        identity_path = (
            self.manifest_root / PROJECT_ID / DATASET_ID / DATASET_VERSION_ID
        )
        version_files = list((identity_path / "versions").glob("*.json"))
        self.assertEqual(len(version_files), 1)
        version_record = json.loads(version_files[0].read_text(encoding="utf-8"))
        self.assertEqual(version_record["manifest_hash"], saved["manifest_hash"])
        self.assertEqual(version_record["project_id"], PROJECT_ID)
        self.assertEqual(version_record["dataset_id"], DATASET_ID)
        self.assertEqual(version_record["dataset_version_id"], DATASET_VERSION_ID)
        self.assertTrue(version_record["definition_checksum"])

        DATASTORE.meta.pop("feature_manifest", None)
        DATASTORE.meta.pop("feature_preview", None)
        DATASTORE.meta.pop("materialized_feature_names", None)
        reloaded = get_manifest(**identity_kwargs())

        self.assertEqual(reloaded["manifest_hash"], saved["manifest_hash"])
        self.assertEqual(
            reloaded["definition_checksum"], version_record["definition_checksum"]
        )
        self.assertEqual(reloaded["persistence_status"], "persisted")
        self.assertEqual(
            [
                row["feature_name"]
                for row in reloaded["features"]
                if row["origin"] != "original"
            ],
            [interaction_definition().feature_name],
        )
        # A read/reload cannot create another immutable version record.
        self.assertEqual(len(list((identity_path / "versions").glob("*.json"))), 1)

    def test_prior_split_remains_stale_through_save_and_materialization(self) -> None:
        frame = governed_frame()
        predictors = frame.drop(columns=[TARGET])
        DATASTORE.set_splits(
            predictors.iloc[:60],
            predictors.iloc[60:],
            frame[TARGET].iloc[:60],
            frame[TARGET].iloc[60:],
        )
        DATASTORE.meta["split_status"] = "current"

        manifest = update_manifest(update_request([interaction_definition()]))
        self.assertEqual(manifest["split_status"], "stale")
        self.assertEqual(DATASTORE.meta["split_status"], "stale")
        self.assertIsNone(DATASTORE.X_train)
        preview = preview_features(
            [interaction_definition()],
            20,
            str(manifest["manifest_hash"]),
            **identity_kwargs(),
        )
        materialized = materialize_manifest(
            str(manifest["manifest_hash"]),
            str(preview["preview_hash"]),
            **identity_kwargs(),
        )

        self.assertEqual(materialized["materialization_status"], "current")
        self.assertEqual(get_manifest(**identity_kwargs())["split_status"], "stale")
        self.assertEqual(DATASTORE.meta["split_status"], "stale")
        self.assertIsNone(DATASTORE.X_train)


def tearDownModule() -> None:
    DATASTORE.reset_all()
    os.environ["ATLAS_FEATURE_MANIFEST_ROOT"] = str(DEFAULT_MANIFEST_ROOT)
    os.environ["ATLAS_CHECKPOINT_PATH"] = str(CHECKPOINT_PATH)
    checkpoint.CHECKPOINT_PATH = CHECKPOINT_PATH
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
