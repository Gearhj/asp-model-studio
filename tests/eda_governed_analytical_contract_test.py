from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from server.core.dataset_store import DatasetStore
from server.eda.analytical_contract import (
    EDAAnalyticalContractError,
    MONOTONICITY_TOLERANCE,
    _classify_monotonicity_with_tolerance,
    _reversal_count,
    build_governed_eda_contract,
    classify_feature_values,
)
from server.eda.workspace_service import EDAWorkspaceService
from server.eda.workspace_types import (
    EDARelationshipSampleRequest,
    EDAWorkspaceRequest,
    TargetByPredictorRequest,
)


PROJECT_ID = "project-eda-contract-isolated"
DATASET_ID = "dataset-eda-contract-isolated"
VERSION_ID = "version-eda-contract-isolated"
MANIFEST_ID = "manifest-eda-contract-isolated"
PREDICTORS = ["ExternalRiskEstimate", "NumInqLast6M", "NumInqLast6Mexcl7days"]


def _source() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = 160
    inquiry = rng.poisson(3, rows).astype(float)
    inquiry_excluding = inquiry + rng.normal(0, 0.05, rows)
    risk = np.linspace(20, 95, rows)
    risk[:6] = [-9, -8, -7, -9, -8, -7]
    target = ((risk > 58).astype(int) ^ (rng.random(rows) < 0.12)).astype(int)
    return pd.DataFrame(
        {
            "ExternalRiskEstimate": risk,
            "NumInqLast6M": inquiry,
            "NumInqLast6Mexcl7days": inquiry_excluding,
            "bad_flag": target,
        }
    )


def _store(*, split_id: str = "split-eda-contract-isolated") -> tuple[DatasetStore, pd.DataFrame]:
    source = _source()
    store = DatasetStore()
    store.set_raw(source)
    store.set_target("bad_flag")
    store.meta.update(
        {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "source": {"kind": "dataset_library", "filename": "HELOC.csv"},
            "selected_columns": list(PREDICTORS),
            "feature_manifest": {
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                "manifest_version": MANIFEST_ID,
                "features": [
                    {
                        "feature_name": feature,
                        "selected": True,
                        "eligibility_status": "eligible",
                        "leakage_status": "reviewed",
                    }
                    for feature in PREDICTORS
                ],
            },
        }
    )
    development = source.iloc[:120]
    holdout = source.iloc[120:]
    store.set_splits(
        development[PREDICTORS],
        holdout[PREDICTORS],
        development["bad_flag"],
        holdout["bad_flag"],
    )
    store.meta.update(
        {
            "split_status": "current",
            "split_record": {
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                "split_id": split_id,
                "target": "bad_flag",
                "feature_manifest_version": MANIFEST_ID,
                "selection_partition_id": f"development:{split_id}",
                "n_train": 120,
                "n_test": 40,
                "final_holdout_status": "sealed",
                "holdout_isolation_status": "verified",
            },
        }
    )
    return store, source


def _authorization() -> dict:
    return {
        "manifest_version": MANIFEST_ID,
        "authorized_predictors": list(PREDICTORS),
    }


def _contract(store: DatasetStore, source: pd.DataFrame) -> dict:
    return build_governed_eda_contract(
        project_id=PROJECT_ID,
        full_frame=source,
        target="bad_flag",
        event_value=1,
        authorization=_authorization(),
        store=store,
        created_by="isolated-test",
    )


class GovernedEDAAnalyticalContractTest(unittest.TestCase):
    def test_contract_has_exact_identity_scope_policy_and_shared_artifacts(self) -> None:
        store, source = _store()
        result = _contract(store, source)

        self.assertTrue(result["backend_authoritative"])
        self.assertEqual(result["project_id"], PROJECT_ID)
        self.assertEqual(result["dataset_id"], DATASET_ID)
        self.assertEqual(result["dataset_version_id"], VERSION_ID)
        self.assertEqual(result["predictor_manifest_id"], MANIFEST_ID)
        self.assertEqual(result["analysis_scope"], "development_population")
        self.assertEqual(result["rows_used"], 120)
        self.assertEqual(result["rows_excluded"], 40)
        self.assertEqual(result["exclusion_reasons"], ["sealed_final_holdout_excluded"])
        self.assertFalse(result["final_holdout_accessed"])
        self.assertFalse(result["final_holdout_used_for_selection"])
        self.assertTrue(result["special_value_policy_id"].startswith("eda-special-policy-"))
        self.assertTrue(result["target_artifact"]["artifact_id"].startswith("eda-target-"))
        self.assertEqual(result["target_artifact"]["analysis_scope"], "development_population")
        self.assertEqual(result["target_artifact"]["population_rows"], 120)
        self.assertEqual(
            result["target_artifact"]["event_count"],
            int((store.y_train.astype(str) == "1").sum()),
        )
        self.assertEqual(set(result["predictor_artifacts"]), set(PREDICTORS))
        self.assertTrue(result["relationship_artifact"]["artifact_id"].startswith("eda-relationships-"))

    def test_each_governed_artifact_carries_complete_independent_lineage(self) -> None:
        store, source = _store()
        result = _contract(store, source)
        predictor = result["predictor_artifacts"]["ExternalRiskEstimate"]
        artifacts = [
            result["target_artifact"],
            predictor,
            predictor["iv_woe"],
            predictor["monotonicity"],
            result["relationship_artifact"],
        ]
        required = {
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "target",
            "positive_value",
            "negative_value",
            "predictor_manifest_id",
            "split_id",
            "analysis_population_id",
            "population_rows",
            "rows_used",
            "rows_excluded",
            "exclusion_reasons",
            "special_value_policy_id",
            "missing_value_policy",
            "binning_specification",
            "calculation_method",
            "artifact_id",
            "artifact_version",
            "artifact_hash",
            "created_by",
            "created_at",
            "backend_authoritative",
        }
        for artifact in artifacts:
            lineage = artifact["governed_lineage"]
            self.assertEqual(set(lineage).intersection(required), required)
            self.assertEqual(lineage["artifact_id"], artifact["artifact_id"])
            self.assertEqual(lineage["artifact_hash"], artifact["artifact_hash"])
            self.assertEqual(lineage["rows_used"], 120)
            self.assertEqual(lineage["rows_excluded"], 40)
            self.assertFalse(lineage["final_holdout_accessed"])

    def test_bureau_special_values_are_neither_null_outliers_nor_quantile_members(self) -> None:
        store, source = _store()
        contract = _contract(store, source)
        artifact = contract["predictor_artifacts"]["ExternalRiskEstimate"]
        classification = classify_feature_values(
            "ExternalRiskEstimate",
            source["ExternalRiskEstimate"],
            meta=store.meta,
            target=source["bad_flag"],
            event_value=1,
        )

        self.assertEqual(classification["counts"]["bureau_special_value"], 6)
        self.assertEqual(classification["counts"]["true_null"], 0)
        self.assertTrue(
            bool(
                (
                    classification["ordinary_outlier_mask"]
                    & classification["masks"]["bureau_special_value"]
                ).sum()
                == 0
            )
        )
        ordinary_bins = [
            row
            for row in artifact["iv_woe"]["bins"]
            if row["bin_type"] == "ordinary_valid_range"
        ]
        self.assertTrue(all(float(row["lower"]) >= 20 for row in ordinary_bins))
        self.assertEqual(artifact["special_values"]["values_are_true_nulls"], False)
        self.assertEqual(artifact["special_values"]["values_are_ordinary_outliers"], False)
        self.assertEqual(artifact["special_values"]["values_enter_ordinary_quantiles"], False)
        self.assertTrue(
            all(group["event_rate"] is not None for group in artifact["special_values"]["groups"])
        )
        self.assertTrue(
            all(
                "event_rate" not in group
                for group in artifact["special_values"]["full_population_groups"]
            )
        )
        self.assertEqual(
            artifact["value_classification"]["base_mutually_exclusive_classes"],
            [
                "true_null",
                "bureau_special_value",
                "ordinary_valid_value",
                "parse_failure",
            ],
        )
        self.assertEqual(
            artifact["value_classification"]["derived_subsets"][
                "ordinary_numeric_outlier"
            ]["parent_class"],
            "ordinary_valid_value",
        )

    def test_positive_sentinels_follow_per_feature_governed_policy(self) -> None:
        values = pd.Series([42, 96, 97, 98, 99, 55], name="PercentTradesNeverDelq")
        target = pd.Series([0, 1, 0, 1, 1, 0])
        heloc_meta = {"source": {"filename": "HELOC.csv"}}
        fallback = classify_feature_values(
            "PercentTradesNeverDelq",
            values,
            meta=heloc_meta,
            target=target,
            event_value=1,
        )
        self.assertEqual(fallback["counts"]["bureau_special_value"], 4)
        self.assertEqual(
            {group["code"] for group in fallback["special_groups"]},
            {96, 97, 98, 99},
        )

        governed_meta = {
            **heloc_meta,
            "bureau_review": {
                "variables": [
                    {
                        "variable": "PercentTradesNeverDelq",
                        "likely_bureau": True,
                        "special_value_policy": {
                            "included_codes": [96],
                            "definitions": {"96": "Bureau exception"},
                        },
                    }
                ]
            },
        }
        governed = classify_feature_values(
            "PercentTradesNeverDelq",
            values,
            meta=governed_meta,
            target=target,
            event_value=1,
        )
        self.assertEqual(governed["counts"]["bureau_special_value"], 1)
        self.assertTrue(bool(governed["masks"]["ordinary_valid_value"].loc[4]))

    def test_iv_woe_and_monotonicity_preserve_governed_metadata(self) -> None:
        store, source = _store()
        artifact = _contract(store, source)["predictor_artifacts"]["ExternalRiskEstimate"]
        iv = artifact["iv_woe"]
        monotonicity = artifact["monotonicity"]

        self.assertEqual(artifact["iv"], iv["iv"])
        self.assertEqual(iv["requested_bins"], 10)
        self.assertGreater(iv["effective_nonempty_bins"], 1)
        self.assertLessEqual(iv["effective_nonempty_bins"], 10)
        self.assertEqual(iv["WoE_smoothing_constant"], 0.5)
        self.assertEqual(iv["empty_interval_policy"], "suppressed")
        self.assertTrue(
            all(
                row["count"] >= iv["minimum_bin_population"]
                for row in iv["bins"]
                if row["bin_type"] == "ordinary_valid_range"
            )
        )
        self.assertTrue(all("[" in row["label"] or "(" in row["label"] for row in iv["bins"] if row["bin_type"] == "ordinary_valid_range"))
        self.assertEqual(monotonicity["analysis_scope"], "development_population")
        self.assertEqual(monotonicity["effective_bins"], iv["effective_nonempty_bins"])
        self.assertEqual(monotonicity["special_value_policy"], "excluded_from_ordinary_monotonicity_and_reported_as_named_groups")

    def test_monotonicity_label_and_reversal_count_share_one_tolerance(self) -> None:
        rates = [0.10, 0.103, 0.10]
        self.assertEqual(
            _classify_monotonicity_with_tolerance(
                rates, MONOTONICITY_TOLERANCE
            ),
            "Flat",
        )
        self.assertEqual(_reversal_count(rates, MONOTONICITY_TOLERANCE), 0)

    def test_regression_marks_iv_woe_and_event_monotonicity_not_applicable(self) -> None:
        source = _source().drop(columns=["bad_flag"])
        source["loss"] = (
            2.5 * source["NumInqLast6M"]
            + np.linspace(0, 10, len(source))
        )
        store = DatasetStore()
        store.set_raw(source)
        store.set_target("loss")
        store.meta.update(
            {
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                "source": {"kind": "dataset_library", "filename": "HELOC.csv"},
                "selected_columns": list(PREDICTORS),
                "feature_manifest": {
                    "manifest_version": MANIFEST_ID,
                    "features": [
                        {
                            "feature_name": feature,
                            "selected": True,
                            "eligibility_status": "eligible",
                            "leakage_status": "reviewed",
                        }
                        for feature in PREDICTORS
                    ],
                },
            }
        )
        development = source.iloc[:120]
        holdout = source.iloc[120:]
        store.set_splits(
            development[PREDICTORS],
            holdout[PREDICTORS],
            development["loss"],
            holdout["loss"],
        )
        store.meta.update(
            {
                "split_status": "current",
                "split_record": {
                    "project_id": PROJECT_ID,
                    "dataset_id": DATASET_ID,
                    "dataset_version_id": VERSION_ID,
                    "split_id": "split-regression",
                    "target": "loss",
                    "feature_manifest_version": MANIFEST_ID,
                    "selection_partition_id": "development:split-regression",
                    "n_train": 120,
                    "n_test": 40,
                    "final_holdout_status": "sealed",
                    "holdout_isolation_status": "verified",
                },
            }
        )
        result = build_governed_eda_contract(
            project_id=PROJECT_ID,
            full_frame=source,
            target="loss",
            event_value=None,
            authorization=_authorization(),
            store=store,
            created_by="isolated-test",
        )
        artifact = result["predictor_artifacts"]["NumInqLast6M"]
        self.assertEqual(result["problem_type"], "regression")
        self.assertIsNone(artifact["iv"])
        self.assertFalse(artifact["iv_woe"]["applicable"])
        self.assertEqual(artifact["iv_woe"]["bins"], [])
        self.assertFalse(artifact["monotonicity"]["applicable"])
        self.assertEqual(
            artifact["monotonicity"]["valid_value_shape"],
            "Not applicable",
        )
        self.assertIsNotNone(artifact["correlation_with_target"])

    def test_holdout_objects_are_not_accessed_and_holdout_changes_do_not_change_target_artifacts(self) -> None:
        store, source = _store()
        baseline = _contract(store, source)
        # Change only the isolated holdout objects. The governed source and
        # development partition stay fixed; target-directed artifacts must be
        # byte-for-byte identical.
        store.X_test = pd.DataFrame({feature: np.arange(40) * 1_000 for feature in PREDICTORS})
        store.y_test = pd.Series([1, 0] * 20)
        changed = _contract(store, source)
        self.assertEqual(baseline["artifact_hash"], changed["artifact_hash"])
        self.assertEqual(
            baseline["target_artifact"]["artifact_hash"],
            changed["target_artifact"]["artifact_hash"],
        )
        self.assertEqual(
            baseline["predictor_artifacts"]["ExternalRiskEstimate"]["iv_artifact_id"],
            changed["predictor_artifacts"]["ExternalRiskEstimate"]["iv_artifact_id"],
        )

    def test_development_change_changes_artifact_and_split_change_invalidates_identity(self) -> None:
        store, source = _store()
        baseline = _contract(store, source)
        store.X_train = store.X_train.copy()
        store.X_train.loc[store.X_train.index[-20:], "ExternalRiskEstimate"] = 25
        changed = _contract(store, source)
        self.assertNotEqual(baseline["artifact_hash"], changed["artifact_hash"])

        stale = deepcopy(store.meta["split_record"])
        stale["dataset_version_id"] = "wrong-version"
        store.meta["split_record"] = stale
        with self.assertRaisesRegex(EDAAnalyticalContractError, "identity mismatch"):
            _contract(store, source)

    def test_missing_or_stale_split_fails_closed(self) -> None:
        store, source = _store()
        store.meta["split_status"] = "stale"
        with self.assertRaisesRegex(EDAAnalyticalContractError, "current durable development split"):
            _contract(store, source)

    def test_correlation_and_vif_disclose_development_rows_and_special_policy(self) -> None:
        store, source = _store()
        relationship = _contract(store, source)["relationship_artifact"]
        self.assertEqual(relationship["analysis_scope"], "development_population")
        self.assertEqual(relationship["population_rows"], 120)
        self.assertEqual(relationship["correlation"]["methods_supported"], ["pearson", "spearman"])
        self.assertEqual(relationship["correlation"]["complete_case_policy"], "pairwise_complete")
        correlation_scope = relationship["correlation"]
        pair_counts = [
            correlation_scope["pairwise_row_counts"][left][right]
            for left in range(len(correlation_scope["columns"]))
            for right in range(left + 1, len(correlation_scope["columns"]))
        ]
        self.assertEqual(correlation_scope["rows_used_min"], min(pair_counts))
        self.assertEqual(correlation_scope["rows_used_max"], max(pair_counts))
        self.assertEqual(
            correlation_scope["rows_excluded_max"],
            relationship["population_rows"] - min(pair_counts),
        )
        self.assertEqual(
            correlation_scope["rows_excluded_min"],
            relationship["population_rows"] - max(pair_counts),
        )
        self.assertEqual(relationship["vif_scope"]["missing_value_treatment"], "complete_case")
        self.assertEqual(relationship["vif_scope"]["special_value_representation"], "excluded_from_ordinary_numeric_matrix")
        self.assertIn("ExternalRiskEstimate", relationship["vif_by_feature"])

    def test_workspace_sections_reuse_one_contract_and_harmonized_predictor_ids(self) -> None:
        store, _source_frame = _store()
        identity = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
        }
        service = EDAWorkspaceService()
        request = EDAWorkspaceRequest(
            project_id=PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
            target="bad_flag",
            event_value=1,
            problem_type="classification",
        )
        with patch("server.core.dataset_store.DatasetStoreProxy.current", return_value=store), patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value=identity,
        ):
            target = service.section("target", request)
            predictors = service.section("predictors", request)
            relationships = service.section("relationships", request)

        contract_ids = {
            target["governed_analytical_contract"]["artifact_id"],
            predictors["governed_analytical_contract"]["artifact_id"],
            relationships["governed_analytical_contract"]["artifact_id"],
        }
        self.assertEqual(len(contract_ids), 1)
        self.assertEqual(target["analysis_scope"]["mode"], "governed_version")
        self.assertEqual(target["analysis_scope"]["splitId"], "split-eda-contract-isolated")
        self.assertEqual(
            target["governed_target_artifact"]["artifact_id"],
            target["development_target_profile"]["artifact_id"],
        )
        self.assertEqual(target["development_target_profile"]["population_rows"], 120)
        predictor_id = predictors["governed_predictor_artifacts"]["ExternalRiskEstimate"]["artifact_id"]
        self.assertEqual(
            predictor_id,
            target["governed_predictor_artifacts"]["ExternalRiskEstimate"]["artifact_id"],
        )
        self.assertEqual(
            relationships["vif"],
            predictors["governed_relationship_artifact"]["vif"],
        )

    def test_target_directed_section_factory_receives_development_rows_only(self) -> None:
        store, _source_frame = _store()
        identity = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
        }
        service = EDAWorkspaceService()
        request = EDAWorkspaceRequest(
            project_id=PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
            target="bad_flag",
            event_value=1,
            problem_type="classification",
        )
        observed: dict[str, object] = {}
        original = service._predictors

        def spy(df, target, y, problem, event, request):
            observed["rows"] = len(df)
            observed["target_rows"] = len(y)
            observed["indices"] = list(df.index)
            return original(df, target, y, problem, event, request)

        with patch("server.core.dataset_store.DatasetStoreProxy.current", return_value=store), patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value=identity,
        ), patch.object(service, "_predictors", side_effect=spy):
            result = service.section("predictors", request)

        self.assertEqual(observed["rows"], 120)
        self.assertEqual(observed["target_rows"], 120)
        self.assertEqual(observed["indices"], list(range(120)))
        self.assertEqual(result["row_count"], 160)
        self.assertEqual(result["analysis_scope"]["populationRows"], 120)

    def test_holdout_target_change_cannot_change_authorization_or_target_colored_sample(self) -> None:
        store, _source_frame = _store()
        identity = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
        }
        workspace_request = EDAWorkspaceRequest(
            project_id=PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
            target="bad_flag",
            event_value=1,
            problem_type="classification",
        )
        sample_request = EDARelationshipSampleRequest(
            project_id=PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
            dataset_version=VERSION_ID,
            target="bad_flag",
            event_value=1,
            problem_type="classification",
            predictor_manifest_id=MANIFEST_ID,
            x_feature="NumInqLast6M",
            y_feature="NumInqLast6Mexcl7days",
            sample_limit=100,
        )
        with patch("server.core.dataset_store.DatasetStoreProxy.current", return_value=store), patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value=identity,
        ):
            baseline_service = EDAWorkspaceService()
            baseline_target = baseline_service.section("target", workspace_request)
            baseline_findings = baseline_service.section("findings", workspace_request)
            baseline_sample = baseline_service.relationship_sample(sample_request)

            store.raw_df.loc[120:, "bad_flag"] = 1 - store.raw_df.loc[120:, "bad_flag"]
            store.raw_df.loc[120:, "ExternalRiskEstimate"] = np.nan
            store.raw_df.loc[120:, "NumInqLast6M"] = 999_999
            changed_service = EDAWorkspaceService()
            changed_target = changed_service.section("target", workspace_request)
            changed_findings = changed_service.section("findings", workspace_request)
            changed_sample = changed_service.relationship_sample(sample_request)

        self.assertEqual(
            baseline_target["predictor_authorization"],
            changed_target["predictor_authorization"],
        )
        self.assertEqual(
            baseline_target["predictor_preview"],
            changed_target["predictor_preview"],
        )
        self.assertEqual(baseline_findings["findings"], changed_findings["findings"])
        self.assertEqual(
            baseline_findings["carry_forward"], changed_findings["carry_forward"]
        )
        self.assertEqual(baseline_sample["points"], changed_sample["points"])
        self.assertEqual(baseline_sample["pair_metrics"], changed_sample["pair_metrics"])
        self.assertEqual(
            baseline_sample["analysis_scope"]["splitId"],
            "split-eda-contract-isolated",
        )
        self.assertFalse(
            baseline_sample["governance"]["final_holdout_accessed"]
        )

    def test_target_by_predictor_is_development_only_and_carries_artifact_identity(self) -> None:
        store, _source_frame = _store()
        identity = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
        }
        service = EDAWorkspaceService()
        request = TargetByPredictorRequest(
            project_id=PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
            target="bad_flag",
            event_value=1,
            predictor="ExternalRiskEstimate",
            analysis_type="numeric_quantile",
            bands=10,
        )
        with patch("server.core.dataset_store.DatasetStoreProxy.current", return_value=store), patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value=identity,
        ):
            result = service.target_by_predictor(request)

        self.assertEqual(result["scope"], "development_population")
        self.assertEqual(result["sourceRowCount"], 120)
        self.assertEqual(result["analysisScope"]["splitId"], "split-eda-contract-isolated")
        self.assertTrue(result["artifactId"].startswith("eda-predictor-"))
        self.assertFalse(result["finalHoldoutAccessed"])
        self.assertTrue(any(row.get("isBureauSpecialGroup") for row in result["rows"]))

    def test_production_eda_sources_do_not_reference_holdout_objects_or_combined_accessor(self) -> None:
        root = Path(__file__).resolve().parents[1] / "server" / "eda"
        forbidden = ("X_test", "y_test", "_X_holdout", "_y_holdout", "get_splits(")
        offenders: list[str] = []
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    offenders.append(f"{path.name}:{token}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
