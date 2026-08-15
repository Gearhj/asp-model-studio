from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import pandas as pd
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault(
    "ATLAS_CHECKPOINT_PATH",
    str(
        Path(tempfile.gettempdir())
        / f"atlas_preparation_premium_{uuid.uuid4().hex[:10]}.json"
    ),
)

from server.core.dataset_store import DATASTORE  # noqa: E402
from server.features.feature_service import (  # noqa: E402
    _apply_feature,
    _normalize_engineered,
    get_manifest,
    preview_features,
)
import server.features.feature_service as feature_service_module  # noqa: E402
from server.features.feature_types import FeatureDefinitionInput  # noqa: E402
from server.preprocessing.missing_router import (  # noqa: E402
    MissingApplyRequest,
    MissingValidateRequest,
    apply_missing_values,
    missing_summary,
    validate_missing_values,
)
from server.preprocessing.outlier_service import outlier_service  # noqa: E402
from server.preprocessing.preprocessing_contract import (  # noqa: E402
    PREPROCESSING_CONTRACT_VERSION,
    fit_metadata,
    fit_outlier_recipe,
    resolve_special_value_contract,
    scope_lineage,
)
from server.preprocessing.predictor_authorization import (  # noqa: E402
    bureau_special_summary,
    governed_predictor_authorization,
)
import server.preprocessing.missing_router as missing_router_module  # noqa: E402


PROJECT_ID = "preparation-premium-test"
USER = {"userId": "preparation-premium-owner"}
DATASET_ID = "dataset-preparation-premium"
DATASET_VERSION_ID = "dataset-version-preparation-premium-v1"


def canonical_identity() -> dict[str, str]:
    return {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": DATASET_VERSION_ID,
    }


def resolve_test_identity(
    project_id: str = "",
    *,
    expected_dataset_id: str = "",
    expected_dataset_version_id: str = "",
    legacy_dataset_version: str = "",
    **_kwargs,
) -> dict[str, str]:
    identity = canonical_identity()
    resolved_project_id = str(project_id or DATASTORE.meta.get("project_id") or "")
    if resolved_project_id != identity["project_id"]:
        raise AssertionError("Test requested a different project identity.")
    supplied = {
        "dataset_id": str(expected_dataset_id or ""),
        "dataset_version_id": str(
            expected_dataset_version_id or legacy_dataset_version or ""
        ),
    }
    if any(
        value and value != identity[key]
        for key, value in supplied.items()
    ):
        raise AssertionError("Test requested a different dataset identity.")
    return identity


def frame_with_heloc_semantics(null_value: float | None = None) -> pd.DataFrame:
    rows = 120
    target = [1 if index % 3 == 0 else 0 for index in range(rows)]
    risk = ["Bad" if value == 1 else "Good" for value in target]
    external = [float(40 + (index % 50)) for index in range(rows)]
    external[3] = -9.0
    external[7] = -8.0
    external[11] = -7.0
    external[-1] = 999.0
    if null_value is None:
        average = [float(30 + index % 20) for index in range(rows)]
    else:
        average = [float(30 + index % 20) for index in range(rows)]
        average[5] = null_value
    return pd.DataFrame(
        {
            "RiskPerformance": risk,
            "ExternalRiskEstimate": external,
            "AverageMInFile": average,
            "NumTotalTrades": [10 + index % 7 for index in range(rows)],
            "NumSatisfactoryTrades": [8 + index % 5 for index in range(rows)],
            "bad_flag": target,
        }
    )


def configure(frame: pd.DataFrame, include_target_source_in_selection: bool = False):
    DATASTORE.reset_all()
    DATASTORE.set_raw(frame)
    DATASTORE.set_target("bad_flag")
    selected = [
        "ExternalRiskEstimate",
        "AverageMInFile",
        "NumTotalTrades",
        "NumSatisfactoryTrades",
    ]
    if include_target_source_in_selection:
        selected.insert(0, "RiskPerformance")
    DATASTORE.meta.update(
        {
            **canonical_identity(),
            "dataset_version": DATASET_VERSION_ID,
            "selected_columns": selected,
        }
    )


def _test_authorization() -> dict[str, object]:
    predictors = list(DATASTORE.get_selected_columns())
    return {
        "predictor_authorization_id": "premium-authorization-v2",
        "authorized_predictors": predictors,
        "excluded_predictors": {"bad_flag": "Modeling target"},
        "target_source_excluded": [],
    }


class TestDevelopmentScope:
    target = "bad_flag"
    event_value = 1
    non_event_value = 0
    problem_type = "classification"
    partition = {
        "analysis_partition_id": "analysis-partition-premium",
        "revision": 1,
    }

    @property
    def predictor_authorization(self):
        return _test_authorization()

    @property
    def development_features(self):
        return DATASTORE.get_raw_active_df(include_target=False)

    @property
    def development_target(self):
        return DATASTORE.raw_df["bad_flag"].copy()

    def materialize_aligned_features(self, frame):
        return frame.loc[:, self.predictor_authorization["authorized_predictors"]].copy()

    def metadata(self):
        return {
            "scope": "development_population",
            "analysis_scope": "development_population",
            "target_directed_scope": "development_population",
            "structural_scope": "full_governed_population_predictors_only",
            "analysis_partition_id": self.partition["analysis_partition_id"],
            "analysis_partition_revision": 1,
            "final_holdout_accessed": False,
            "final_holdout_used_for_selection": False,
        }


def install_current_none_outlier_policy() -> None:
    scope = TestDevelopmentScope()
    identity = canonical_identity()
    special_contract = resolve_special_value_contract(
        identity=identity,
        scope=scope,
        store=DATASTORE.current(),
    )
    lineage = scope_lineage(scope, special_contract)
    policy = {
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "artifact_kind": "approved_outlier_policy",
        "status": "approved",
        "outlier_policy_id": "op-premium-none",
        "outlier_policy_revision": 1,
        "global_method": "NONE",
        "config": {
            feature: "NONE"
            for feature in scope.predictor_authorization["authorized_predictors"]
        },
        "rationales": {},
        "analytical_types": {},
    }
    preview_fit = fit_outlier_recipe(
        scope.development_features,
        policy=policy,
        fit=fit_metadata(
            fit_scope="development_preview",
            population_id="premium-development",
            population_count=len(scope.development_features),
            lineage=lineage,
            actor="preparation-premium-test",
            application_scope="development_population_preview",
            application_population_id="premium-development",
            application_population_rows=len(scope.development_features),
        ),
        special_value_contract=special_contract,
    )
    DATASTORE.meta["outlier_policy"] = policy
    DATASTORE.meta["outlier_application"] = {
        **lineage,
        "preprocessing_contract_version": PREPROCESSING_CONTRACT_VERSION,
        "artifact_kind": "outlier_policy_approval",
        "state": "approved",
        "approved_policy": policy,
        "development_preview_fit": preview_fit,
    }


class PredictorAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_feature_identity = feature_service_module._active_identity
        feature_service_module._active_identity = resolve_test_identity

    @classmethod
    def tearDownClass(cls):
        feature_service_module._active_identity = cls.original_feature_identity

    def tearDown(self):
        DATASTORE.reset_all()

    def test_deterministic_target_source_is_detected_even_when_unselected(self):
        frame = frame_with_heloc_semantics()
        configure(frame)
        authorization = governed_predictor_authorization(
            frame,
            target="bad_flag",
            selected_columns=DATASTORE.get_selected_columns(),
        )
        self.assertIn("RiskPerformance", authorization["target_source_excluded"])
        self.assertNotIn(
            "RiskPerformance", authorization["authorized_predictors"]
        )

    def test_client_selection_cannot_reauthorize_target_source(self):
        frame = frame_with_heloc_semantics()
        configure(frame, include_target_source_in_selection=True)
        authorization = governed_predictor_authorization(
            frame,
            target="bad_flag",
            selected_columns=DATASTORE.get_selected_columns(),
        )
        self.assertEqual(
            authorization["excluded_predictors"]["RiskPerformance"],
            "Deterministic source of the modeling target",
        )
        self.assertNotIn(
            "RiskPerformance", authorization["authorized_predictors"]
        )

    def test_feature_manifest_marks_target_source_ineligible(self):
        frame = frame_with_heloc_semantics()
        configure(frame, include_target_source_in_selection=True)
        manifest = get_manifest()
        risk = next(
            row
            for row in manifest["features"]
            if row["feature_name"] == "RiskPerformance"
        )
        self.assertEqual(risk["eligibility_status"], "excluded")
        self.assertFalse(risk["selected"])
        self.assertIn("Deterministic source", risk["exclusion_reason"])

    def test_engineered_feature_cannot_reference_target_source(self):
        frame = frame_with_heloc_semantics()
        configure(frame, include_target_source_in_selection=True)
        definition = FeatureDefinitionInput(
            feature_name="unsafe_feature",
            origin="categorical_rule",
            source_features=["RiskPerformance"],
            transformation_type="categorical_rule",
            formula_or_rule="RiskPerformance == Bad",
            output_datatype="categorical",
            config={
                "rules": [
                    {"op": "equals", "value": "Bad", "then_label": "bad"}
                ]
            },
        )
        with self.assertRaisesRegex(ValueError, "excluded predictor"):
            _normalize_engineered(
                definition,
                {"ExternalRiskEstimate", "AverageMInFile"},
                set(),
                canonical_identity(),
            )


class OutlierSpecialValueTests(unittest.TestCase):
    def tearDown(self):
        DATASTORE.reset_all()

    def test_special_values_are_profiled_separately(self):
        frame = frame_with_heloc_semantics()
        configure(frame)
        summary = outlier_service.summary(
            DATASTORE.get_raw_active_df(),
            target="bad_flag",
            event_value=1,
            problem_type="classification",
            selected_columns=DATASTORE.get_selected_columns(),
            predictor_authorization=_test_authorization(),
            target_analysis_features=DATASTORE.get_raw_active_df(
                include_target=False
            ),
            target_analysis_target=DATASTORE.raw_df["bad_flag"],
        )
        external = next(
            row
            for row in summary["features"]
            if row["feature"] == "ExternalRiskEstimate"
        )
        self.assertEqual(external["special_value_count"], 3)
        self.assertEqual(
            external["special_values"], {"-9": 1, "-8": 1, "-7": 1}
        )
        self.assertEqual(external["ordinary_nonmissing_count"], 117)

    def test_special_values_do_not_define_ordinary_thresholds_or_counts(self):
        frame = frame_with_heloc_semantics()
        configure(frame)
        summary = outlier_service.summary(
            DATASTORE.get_raw_active_df(),
            target="bad_flag",
            event_value=1,
            problem_type="classification",
            selected_columns=DATASTORE.get_selected_columns(),
            predictor_authorization=_test_authorization(),
            target_analysis_features=DATASTORE.get_raw_active_df(
                include_target=False
            ),
            target_analysis_target=DATASTORE.raw_df["bad_flag"],
        )
        external = next(
            row
            for row in summary["features"]
            if row["feature"] == "ExternalRiskEstimate"
        )
        self.assertGreater(
            external["methods"]["IQR_1_5"]["lower_threshold"], -7
        )
        self.assertLess(
            external["methods"]["IQR_1_5"]["outlier_count"], 4
        )

    def test_apply_preserves_bureau_special_values(self):
        frame = frame_with_heloc_semantics()
        configure(frame)
        active = DATASTORE.get_raw_active_df()
        treated, applications = outlier_service.apply(
            active,
            config={"ExternalRiskEstimate": "IQR_1_5"},
            global_method="IQR_1_5",
            target="bad_flag",
            selected_columns=DATASTORE.get_selected_columns(),
            predictor_authorization=_test_authorization(),
            rationales={
                "ExternalRiskEstimate": "Continuous provider risk score."
            },
            analytical_types={
                "ExternalRiskEstimate": {
                    "analytical_type": "numeric_continuous",
                    "source": "provider_metadata",
                    "authoritative_support": "HELOC score definition",
                    "reason": "Continuous provider risk score.",
                }
            },
        )
        self.assertEqual(
            treated.loc[[3, 7, 11], "ExternalRiskEstimate"].tolist(),
            [-9.0, -8.0, -7.0],
        )
        external = next(
            row
            for row in applications
            if row["feature"] == "ExternalRiskEstimate"
        )
        self.assertEqual(external["special_values_preserved"], 3)

    def test_feature_override_takes_precedence_over_global_default(self):
        frame = frame_with_heloc_semantics()
        configure(frame)
        _, applications = outlier_service.apply(
            DATASTORE.get_raw_active_df(),
            config={"ExternalRiskEstimate": "NONE"},
            global_method="PCT_05_95",
            target="bad_flag",
            selected_columns=DATASTORE.get_selected_columns(),
            predictor_authorization=_test_authorization(),
        )
        external = next(
            row
            for row in applications
            if row["feature"] == "ExternalRiskEstimate"
        )
        self.assertEqual(external["applied_method"], "NONE")
        self.assertEqual(external["changed_values"], 0)


class MissingValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_authorize = missing_router_module.authorize_modeling_scope
        cls.original_save = missing_router_module.save_checkpoint
        cls.original_missing_identity = (
            missing_router_module.assert_expected_active_identity
        )
        cls.original_development_scope = missing_router_module._development_scope
        missing_router_module.authorize_modeling_scope = (
            lambda user, project_id, permission: project_id
        )
        missing_router_module.save_checkpoint = lambda: True
        missing_router_module.assert_expected_active_identity = (
            resolve_test_identity
        )
        missing_router_module._development_scope = (
            lambda *args, **kwargs: TestDevelopmentScope()
        )

    @classmethod
    def tearDownClass(cls):
        missing_router_module.authorize_modeling_scope = cls.original_authorize
        missing_router_module.save_checkpoint = cls.original_save
        missing_router_module.assert_expected_active_identity = (
            cls.original_missing_identity
        )
        missing_router_module._development_scope = cls.original_development_scope

    def tearDown(self):
        DATASTORE.reset_all()

    def test_special_values_are_not_true_nulls(self):
        frame = frame_with_heloc_semantics()
        configure(frame)
        payload = missing_summary(
            PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=DATASET_VERSION_ID,
            dataset_id=None,
            dataset_version_id=None,
            dataset_version=None,
            user=USER,
        )
        external = payload["stats"]["ExternalRiskEstimate"]
        self.assertEqual(external["missing"], 0)
        # Exact governed-special disclosure comes from the persisted feature/value
        # contract.  Reserved bureau sentinels remain protected from estimator
        # fitting even when that feature has not been authorized for the governed
        # special-value disclosure.
        self.assertEqual(external["special_value_count"], 0)
        self.assertEqual(external["protected_sentinel_excluded_count"], 3)

    def test_zero_null_validation_does_not_materialize_backend_frame(self):
        configure(frame_with_heloc_semantics())
        install_current_none_outlier_policy()
        self.assertIsNone(DATASTORE.processed_df)
        payload = validate_missing_values(
            MissingValidateRequest(
                project_id=PROJECT_ID,
                expected_dataset_id=DATASET_ID,
                expected_dataset_version_id=DATASET_VERSION_ID,
                preprocessing_contract_version=2,
                analysis_partition_id="analysis-partition-premium",
                analysis_partition_revision=1,
                expected_predictor_authorization_id="premium-authorization-v2",
                expected_special_value_review_revision=0,
            ),
            user=USER,
        )
        self.assertEqual(
            payload["validation"]["status"],
            "validated_no_treatment_required",
        )
        self.assertFalse(payload["validation"]["backend_materialization"])
        self.assertIsNone(DATASTORE.processed_df)

    def test_zero_null_apply_is_rejected_without_materialization(self):
        configure(frame_with_heloc_semantics())
        with self.assertRaises(HTTPException) as raised:
            apply_missing_values(
                MissingApplyRequest(project_id=PROJECT_ID, config={}),
                user=USER,
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNone(DATASTORE.processed_df)


class FeaturePreviewSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_feature_identity = feature_service_module._active_identity
        feature_service_module._active_identity = resolve_test_identity

    @classmethod
    def tearDownClass(cls):
        feature_service_module._active_identity = cls.original_feature_identity

    def tearDown(self):
        DATASTORE.reset_all()

    def test_preview_is_nonmutating(self):
        frame = frame_with_heloc_semantics()
        configure(frame)
        before = DATASTORE.raw_df.copy(deep=True)
        definition = FeatureDefinitionInput(
            feature_name="non_satisfactory_trade_count",
            origin="arithmetic",
            source_features=["NumTotalTrades", "NumSatisfactoryTrades"],
            transformation_type="arithmetic",
            formula_or_rule="NumTotalTrades - NumSatisfactoryTrades",
            output_datatype="numeric",
            config={"operation": "subtract"},
        )
        payload = preview_features([definition], 20)
        self.assertIn(
            "non_satisfactory_trade_count", payload["created_features"]
        )
        self.assertIsNone(DATASTORE.processed_df)
        pd.testing.assert_frame_equal(DATASTORE.raw_df, before)

    def test_quantile_bins_and_special_values_are_separate(self):
        frame = frame_with_heloc_semantics()
        feature = {
            "feature_name": "external_risk_band",
            "origin": "numeric_bin",
            "source_features": ["ExternalRiskEstimate"],
            "config": {
                "binning_mode": "quantile",
                "quantiles": [0.2, 0.4, 0.6, 0.8],
                "labels": [
                    "Very low",
                    "Low",
                    "Mid",
                    "High",
                    "Very high",
                ],
                "missing_label": "Special or missing",
                "preserve_bureau_special_values": True,
            },
        }
        output = _apply_feature(frame, feature)
        self.assertEqual(output.iloc[3], "Bureau special -9")
        self.assertEqual(output.iloc[7], "Bureau special -8")
        self.assertEqual(output.iloc[11], "Bureau special -7")
        self.assertGreaterEqual(output.nunique(), 5)

    def test_special_sentinel_is_not_squared(self):
        frame = frame_with_heloc_semantics()
        frame.loc[0, "AverageMInFile"] = -7
        output = _apply_feature(
            frame,
            {
                "feature_name": "average_months_in_file_squared",
                "origin": "polynomial",
                "source_features": ["AverageMInFile"],
                "config": {
                    "degree": 2,
                    "preserve_bureau_special_values": True,
                },
            },
        )
        self.assertEqual(output.iloc[0], -7)
        self.assertEqual(output.iloc[1], frame.iloc[1]["AverageMInFile"] ** 2)

    def test_bureau_special_summary_never_counts_null(self):
        summary = bureau_special_summary(
            pd.Series([-9, -8, -7, None, 10, 20])
        )
        self.assertEqual(summary["special_value_count"], 3)
        self.assertEqual(sum(summary["special_values"].values()), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
