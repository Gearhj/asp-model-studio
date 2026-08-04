from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

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
from server.analysis_partition.service import analysis_partition_service
from tests.analysis_partition_fixture import GovernedAnalysisFixture


PROJECT_ID = "project-eda-contract-isolated"
DATASET_ID = "dataset-eda-contract-isolated"
VERSION_ID = "version-eda-contract-isolated"
MANIFEST_ID = "manifest-eda-contract-isolated"
PREDICTORS = ["ExternalRiskEstimate", "NumInqLast6M", "NumInqLast6Mexcl7days"]
SOURCE_ROWS = 160
DEVELOPMENT_SHARE = 0.8
DEVELOPMENT_ROWS = int(SOURCE_ROWS * DEVELOPMENT_SHARE)
HOLDOUT_ROWS = SOURCE_ROWS - DEVELOPMENT_ROWS
_ACTIVE_FIXTURE: GovernedAnalysisFixture | None = None


def _source() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = SOURCE_ROWS
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
    if _ACTIVE_FIXTURE is None:
        raise AssertionError("Governed Analysis fixture was not initialized.")
    _ACTIVE_FIXTURE.install(
        store,
        dataset_id=DATASET_ID,
        dataset_version_id=VERSION_ID,
        target="bad_flag",
        authorized_predictors=PREDICTORS,
        development_share=DEVELOPMENT_SHARE,
        random_seed=(
            42 if split_id == "split-eda-contract-isolated" else 43
        ),
        reset_existing=(split_id != "split-eda-contract-isolated"),
    )
    return store, source


def _authorization(store: DatasetStore) -> dict:
    # The durable Data Acquisition manifest deliberately records its authoring
    # source as ``data_acquisition`` because that value participates in its
    # checksum.  Workspace resolution verifies that exact manifest and then
    # publishes this wrapper source for the analytical-contract boundary.
    return {
        **dict(store.meta["predictor_authorization"]),
        "source": "data_acquisition_predictor_authorization",
    }


def _contract(store: DatasetStore, source: pd.DataFrame) -> dict:
    return build_governed_eda_contract(
        project_id=PROJECT_ID,
        full_frame=source,
        target="bad_flag",
        event_value=1,
        authorization=_authorization(store),
        store=store,
        created_by="isolated-test",
    )


class GovernedEDAAnalyticalContractTest(unittest.TestCase):
    def setUp(self) -> None:
        global _ACTIVE_FIXTURE
        _ACTIVE_FIXTURE = GovernedAnalysisFixture(project_id=PROJECT_ID)

    def tearDown(self) -> None:
        global _ACTIVE_FIXTURE
        if _ACTIVE_FIXTURE is not None:
            _ACTIVE_FIXTURE.close()
        _ACTIVE_FIXTURE = None

    def test_contract_has_exact_identity_scope_policy_and_shared_artifacts(self) -> None:
        store, source = _store()
        result = _contract(store, source)

        self.assertTrue(result["backend_authoritative"])
        self.assertEqual(result["project_id"], PROJECT_ID)
        self.assertEqual(result["dataset_id"], DATASET_ID)
        self.assertEqual(result["dataset_version_id"], VERSION_ID)
        self.assertEqual(
            result["predictor_manifest_id"],
            store.meta["predictor_authorization_id"],
        )
        self.assertEqual(result["analysis_scope"], "development_population")
        self.assertEqual(result["rows_used"], DEVELOPMENT_ROWS)
        self.assertEqual(result["rows_excluded"], HOLDOUT_ROWS)
        self.assertEqual(result["exclusion_reasons"], ["sealed_final_holdout_excluded"])
        self.assertFalse(result["final_holdout_accessed"])
        self.assertFalse(result["final_holdout_used_for_selection"])
        self.assertTrue(result["special_value_policy_id"].startswith("eda-special-policy-"))
        self.assertTrue(result["target_artifact"]["artifact_id"].startswith("eda-target-"))
        self.assertEqual(result["target_artifact"]["analysis_scope"], "development_population")
        self.assertEqual(
            result["target_artifact"]["population_rows"], DEVELOPMENT_ROWS
        )
        self.assertEqual(
            result["target_artifact"]["event_count"],
            int((store.y_train.astype(str) == "1").sum()),
        )
        self.assertEqual(set(result["predictor_artifacts"]), set(PREDICTORS))
        self.assertTrue(result["relationship_artifact"]["artifact_id"].startswith("eda-relationships-"))

    def test_contract_derives_target_semantics_from_partition_when_request_omits_them(self) -> None:
        store, source = _store()
        result = build_governed_eda_contract(
            project_id=PROJECT_ID,
            full_frame=source,
            target="bad_flag",
            event_value=None,
            authorization=_authorization(store),
            store=store,
            created_by="isolated-test",
        )

        self.assertEqual(result["problem_type"], "classification")
        self.assertEqual(result["positive_value"], 1)
        self.assertEqual(result["negative_value"], 0)
        self.assertEqual(
            result["development_scope"]["target_authority_source"],
            "sealed_analysis_partition",
        )

    def test_contract_rejects_event_value_that_contradicts_partition(self) -> None:
        store, source = _store()
        with self.assertRaises(EDAAnalyticalContractError) as raised:
            build_governed_eda_contract(
                project_id=PROJECT_ID,
                full_frame=source,
                target="bad_flag",
                event_value=0,
                authorization=_authorization(store),
                store=store,
                created_by="isolated-test",
            )

        self.assertEqual(raised.exception.code, "target_contract_stale")

    def test_workspace_rejects_client_target_semantics_that_contradict_partition(self) -> None:
        store, _source_frame = _store()
        identity = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
        }
        service = EDAWorkspaceService()
        requests = (
            EDAWorkspaceRequest(
                project_id=PROJECT_ID,
                expected_dataset_id=DATASET_ID,
                expected_dataset_version_id=VERSION_ID,
                target="bad_flag",
                event_value=0,
                problem_type="classification",
            ),
            EDAWorkspaceRequest(
                project_id=PROJECT_ID,
                expected_dataset_id=DATASET_ID,
                expected_dataset_version_id=VERSION_ID,
                target="bad_flag",
                event_value=None,
                problem_type="regression",
            ),
        )
        with patch(
            "server.core.dataset_store.DatasetStoreProxy.current",
            return_value=store,
        ), patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value=identity,
        ):
            for request in requests:
                with self.subTest(request=request.model_dump()):
                    with self.assertRaises(EDAAnalyticalContractError) as raised:
                        service.authorized_dataset(request)
                    self.assertEqual(
                        raised.exception.code,
                        "target_contract_stale",
                    )

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
            self.assertEqual(lineage["rows_used"], DEVELOPMENT_ROWS)
            self.assertEqual(lineage["rows_excluded"], HOLDOUT_ROWS)
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
        assert _ACTIVE_FIXTURE is not None
        _ACTIVE_FIXTURE.install(
            store,
            dataset_id=DATASET_ID,
            dataset_version_id=VERSION_ID,
            target="loss",
            authorized_predictors=PREDICTORS,
            positive_value=None,
            negative_value=None,
            development_share=0.8,
            stratification_policy="none",
        )
        result = build_governed_eda_contract(
            project_id=PROJECT_ID,
            full_frame=source,
            target="loss",
            event_value=None,
            authorization=_authorization(store),
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
        store.X_test = pd.DataFrame(
            {
                feature: np.arange(HOLDOUT_ROWS) * 1_000
                for feature in PREDICTORS
            }
        )
        store.y_test = pd.Series([1, 0] * (HOLDOUT_ROWS // 2))
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
        development_tail = store.X_train.index[-20:]
        store.raw_df.loc[development_tail, "ExternalRiskEstimate"] = 25
        changed = _contract(store, source)
        self.assertNotEqual(baseline["artifact_hash"], changed["artifact_hash"])

        store.meta["dataset_version_id"] = "wrong-version"
        with self.assertRaisesRegex(EDAAnalyticalContractError, "different exact"):
            _contract(store, source)

    def test_missing_or_stale_split_fails_closed(self) -> None:
        store, source = _store()
        analysis_partition_service.invalidate(
            PROJECT_ID,
            "Isolated stale-partition test.",
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
            target="bad_flag",
            store=store,
        )
        with self.assertRaisesRegex(EDAAnalyticalContractError, "no partition is current"):
            _contract(store, source)

    def test_correlation_and_vif_disclose_development_rows_and_special_policy(self) -> None:
        store, source = _store()
        relationship = _contract(store, source)["relationship_artifact"]
        self.assertEqual(relationship["analysis_scope"], "development_population")
        self.assertEqual(relationship["population_rows"], DEVELOPMENT_ROWS)
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
        self.assertEqual(
            target["analysis_scope"]["splitId"],
            store.meta["analysis_partition_id"],
        )
        self.assertEqual(
            target["governed_target_artifact"]["artifact_id"],
            target["development_target_profile"]["artifact_id"],
        )
        self.assertEqual(
            target["development_target_profile"]["population_rows"],
            DEVELOPMENT_ROWS,
        )
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

        self.assertEqual(observed["rows"], DEVELOPMENT_ROWS)
        self.assertEqual(observed["target_rows"], DEVELOPMENT_ROWS)
        # The development resolver intentionally resets the selected durable
        # positions before passing them to section factories, so downstream
        # joins cannot recover or conflate source-row labels.
        self.assertEqual(observed["indices"], list(range(DEVELOPMENT_ROWS)))
        self.assertEqual(result["row_count"], SOURCE_ROWS)
        self.assertEqual(
            result["analysis_scope"]["populationRows"], DEVELOPMENT_ROWS
        )

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
            predictor_manifest_id=store.meta["predictor_authorization_id"],
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

            holdout_index = store.y_test.index
            store.raw_df.loc[holdout_index, "bad_flag"] = (
                1 - store.raw_df.loc[holdout_index, "bad_flag"]
            )
            store.raw_df.loc[holdout_index, "ExternalRiskEstimate"] = np.nan
            store.raw_df.loc[holdout_index, "NumInqLast6M"] = 999_999
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
            store.meta["analysis_partition_id"],
        )
        self.assertFalse(
            baseline_sample["governance"]["final_holdout_accessed"]
        )

    def test_holdout_only_target_change_cannot_change_profiles_fingerprints_or_cache_identity(self) -> None:
        store, _source_frame = _store()
        identity = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
        }
        request = EDAWorkspaceRequest(
            project_id=PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
            target="bad_flag",
            event_value=1,
            problem_type="classification",
        )
        service = EDAWorkspaceService()

        with patch(
            "server.core.dataset_store.DatasetStoreProxy.current",
            return_value=store,
        ), patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value=identity,
        ), patch.object(
            analysis_partition_service,
            "materialize_validation",
            side_effect=AssertionError(
                "EDA must not materialize or index final-holdout target rows"
            ),
        ):
            baseline_overview = service.section("overview", request)
            baseline_target = service.section("target", request)
            holdout_index = store.y_test.index
            store.raw_df.loc[holdout_index, "bad_flag"] = (
                1 - store.raw_df.loc[holdout_index, "bad_flag"]
            )
            changed_overview = service.section("overview", request)
            changed_target = service.section("target", request)

        self.assertEqual(changed_overview["cache_status"], "hit")
        self.assertEqual(changed_target["cache_status"], "hit")
        self.assertEqual(
            baseline_overview["workspace_compatibility_scope"][
                "datasetFingerprint"
            ],
            changed_overview["workspace_compatibility_scope"][
                "datasetFingerprint"
            ],
        )
        self.assertEqual(
            baseline_overview["target_profile"],
            changed_overview["target_profile"],
        )
        self.assertEqual(
            baseline_target["profile"], changed_target["profile"]
        )
        self.assertEqual(
            baseline_target["identity"], changed_target["identity"]
        )
        self.assertEqual(
            baseline_target["target_quality"],
            changed_target["target_quality"],
        )
        self.assertEqual(
            baseline_target["full_population_assessment"],
            changed_target["full_population_assessment"],
        )
        self.assertEqual(
            baseline_target["profile"]["valid_count"], DEVELOPMENT_ROWS
        )
        self.assertEqual(
            baseline_target["identity"]["population_row_count"],
            DEVELOPMENT_ROWS,
        )
        self.assertEqual(
            baseline_target["full_population_assessment"]["source"],
            "eda_development_population",
        )
        self.assertEqual(
            baseline_target["target_profile_scope"],
            "development_population",
        )
        self.assertFalse(
            baseline_target["full_population_assessment"][
                "finalHoldoutAccessed"
            ]
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
        self.assertEqual(result["sourceRowCount"], DEVELOPMENT_ROWS)
        self.assertEqual(
            result["analysisScope"]["splitId"],
            store.meta["analysis_partition_id"],
        )
        self.assertTrue(result["artifactId"].startswith("eda-predictor-"))
        self.assertFalse(result["finalHoldoutAccessed"])
        self.assertTrue(any(row.get("isBureauSpecialGroup") for row in result["rows"]))

    def test_stale_training_objects_cannot_influence_direct_post_acquisition_eda(self) -> None:
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
            pairwise_features=["NumInqLast6M", "NumInqLast6Mexcl7days"],
        )
        target_request = TargetByPredictorRequest(
            project_id=PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
            target="bad_flag",
            event_value=1,
            predictor="ExternalRiskEstimate",
            analysis_type="numeric_quantile",
            bands=10,
        )
        with patch(
            "server.core.dataset_store.DatasetStoreProxy.current",
            return_value=store,
        ), patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value=identity,
        ):
            baseline = EDAWorkspaceService()
            baseline_relationships = baseline.section(
                "relationships", workspace_request
            )
            baseline_target = baseline.target_by_predictor(target_request)

            # These are downstream compatibility projections and may contain a
            # different split after a reopen. Direct post-Data Acquisition EDA
            # must ignore them completely.
            store.X_train = pd.DataFrame(
                {feature: [999_999.0] * 8 for feature in PREDICTORS}
            )
            store.y_train = pd.Series([1] * 8, name="bad_flag")

            changed = EDAWorkspaceService()
            changed_relationships = changed.section(
                "relationships", workspace_request
            )
            changed_target = changed.target_by_predictor(target_request)

        self.assertEqual(
            baseline_relationships["pairwise_sample"],
            changed_relationships["pairwise_sample"],
        )
        self.assertEqual(baseline_target["rows"], changed_target["rows"])
        self.assertEqual(baseline_target["sourceRowCount"], DEVELOPMENT_ROWS)

    def test_duplicate_source_labels_cannot_pull_holdout_into_target_source_detection(self) -> None:
        source = _source()
        positions = np.arange(len(source))
        development, holdout = train_test_split(
            positions,
            test_size=1.0 - DEVELOPMENT_SHARE,
            random_state=42,
            shuffle=True,
            stratify=source["bad_flag"].astype(str).tolist(),
        )
        source["DevelopmentOnlyTargetSource"] = 0
        source.loc[development, "DevelopmentOnlyTargetSource"] = source.loc[
            development, "bad_flag"
        ].to_numpy()
        # The same value maps to both target classes on holdout, so a leaked
        # full-population scan would not identify this as deterministic.
        source.loc[holdout, "DevelopmentOnlyTargetSource"] = 0
        source.index = pd.Index(["duplicate-label"] * len(source))

        store = DatasetStore()
        store.set_raw(source)
        store.set_target("bad_flag")
        predictors = [*PREDICTORS, "DevelopmentOnlyTargetSource"]
        store.meta.update(
            {
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                "source": {
                    "kind": "dataset_library",
                    "filename": "HELOC.csv",
                },
                "selected_columns": predictors,
            }
        )
        if _ACTIVE_FIXTURE is None:
            raise AssertionError("Governed Analysis fixture was not initialized.")
        _ACTIVE_FIXTURE.install(
            store,
            dataset_id=DATASET_ID,
            dataset_version_id=VERSION_ID,
            target="bad_flag",
            authorized_predictors=predictors,
            development_share=DEVELOPMENT_SHARE,
            random_seed=42,
        )
        identity = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
        }
        with patch(
            "server.core.dataset_store.DatasetStoreProxy.current",
            return_value=store,
        ), patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value=identity,
        ):
            _frame_result, _target, _y, _problem, _event, authorization = (
                EDAWorkspaceService().authorized_dataset(
                    EDAWorkspaceRequest(
                        project_id=PROJECT_ID,
                        expected_dataset_id=DATASET_ID,
                        expected_dataset_version_id=VERSION_ID,
                        target="bad_flag",
                        event_value=1,
                    )
                )
            )

        self.assertIn(
            "DevelopmentOnlyTargetSource",
            authorization["target_source_excluded"],
        )
        self.assertNotIn(
            "DevelopmentOnlyTargetSource",
            authorization["authorized_predictors"],
        )

    def test_production_eda_sources_do_not_reference_holdout_objects_or_combined_accessor(self) -> None:
        root = Path(__file__).resolve().parents[1] / "server" / "eda"
        forbidden = (
            "X_train",
            "y_train",
            "X_test",
            "y_test",
            "_X_holdout",
            "_y_holdout",
            "get_splits(",
        )
        offenders: list[str] = []
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    offenders.append(f"{path.name}:{token}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
