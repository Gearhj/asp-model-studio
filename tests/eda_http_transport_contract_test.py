"""HTTP transport and restart-shaped authority tests for governed EDA."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.analytics import target_intelligence_router
from server.analysis_partition.service import analysis_partition_service
from server.core.dataset_store import DatasetStore
from server.eda import eda_router
import server.eda.workspace_service as workspace_service_module
from server.eda.analytical_contract import EDAAnalyticalContractError
from server.eda.workspace_service import (
    _predictor_authorization,
    eda_workspace_service,
)
from server.eda.workspace_types import (
    EDARelationshipSampleRequest,
    EDAVifResolutionDecisionRequest,
    EDAVifResolutionPlanRequest,
    EDAVifSimulationRequest,
    EDAWorkspaceRequest,
    TargetByPredictorRequest,
)
from tests.analysis_partition_fixture import GovernedAnalysisFixture


PROJECT_ID = "eda-http-transport-project"
DATASET_ID = "ds-eda-http-transport"
VERSION_ID = "v-eda-http-transport"
TARGET = "bad_flag"
PREDICTORS = ["risk", "balance", "inquiries"]


def _request_json() -> dict[str, object]:
    return {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "activation_revision": 1,
        "expected_dataset_id": DATASET_ID,
        "expected_dataset_version_id": VERSION_ID,
        "dataset_version": VERSION_ID,
        "target_contract_id": "target-contract-test",
        "target": TARGET,
        "positive_value": 1,
        "negative_value": 0,
        "event_value": "1",
        "non_event_value": "0",
        "problem_type": "classification",
        "predictor_authorization_id": "predictor-auth-test",
        "analysis_partition_id": "analysis-partition-test",
        "analysis_partition_revision": 1,
        "special_value_review_id": "special-review-test",
        "special_value_review_revision": 1,
        "selected_features": [],
    }


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(eda_router.router, prefix="/api/eda")
    app.dependency_overrides[eda_router.require_user] = lambda: {
        "userId": "eda-http-transport-owner"
    }
    return TestClient(app, raise_server_exceptions=False)


class EDAHTTPErrorAndSerializationContractTest(unittest.TestCase):
    def test_numpy_event_values_are_serialized_inside_the_guarded_route(self) -> None:
        result = {
            "ok": True,
            "positive_value": np.int64(1),
            "negative_value": np.int64(0),
            "nested": {"events": [np.int64(3)]},
        }
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ), patch.object(
            eda_router.eda_workspace_service,
            "section",
            return_value=result,
        ) as section_call:
            response = _client().post(
                "/api/eda/workspace/overview",
                json=_request_json(),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "positive_value": 1,
                "negative_value": 0,
                "nested": {"events": [3]},
            },
        )
        self.assertRegex(
            response.headers["x-request-correlation-id"],
            r"^eda-[0-9a-f]{32}$",
        )
        self.assertTrue(
            section_call.call_args.kwargs["canonical_lineage_required"]
        )

    def test_selected_features_only_relationship_vif_is_target_free(self) -> None:
        request = {
            "project_id": PROJECT_ID,
            "expected_dataset_id": DATASET_ID,
            "expected_dataset_version_id": VERSION_ID,
            "dataset_version": VERSION_ID,
            "selected_features": ["risk", "balance"],
        }
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ), patch.object(
            eda_router.eda_workspace_service,
            "predictor_only_relationships",
            return_value={
                "ok": True,
                "analysis_mode": "predictor_only_diagnostic",
                "target_association": [],
            },
        ) as predictor_only_call, patch.object(
            eda_router.eda_workspace_service,
            "section",
        ) as section_call:
            response = _client().post(
                "/api/eda/workspace/relationships",
                json=request,
            )

        self.assertEqual(response.status_code, 200, response.text)
        predictor_only_call.assert_called_once()
        section_call.assert_not_called()
        self.assertEqual(response.json()["target_association"], [])

    def test_canonical_relationship_request_never_uses_predictor_only_path(self) -> None:
        request = {
            **_request_json(),
            "selected_features": ["risk", "balance"],
        }
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ), patch.object(
            eda_router.eda_workspace_service,
            "section",
            return_value={"ok": True, "target_association": []},
        ) as section_call, patch.object(
            eda_router.eda_workspace_service,
            "predictor_only_relationships",
        ) as predictor_only_call:
            response = _client().post(
                "/api/eda/workspace/relationships",
                json=request,
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(
            section_call.call_args.kwargs["canonical_lineage_required"]
        )
        predictor_only_call.assert_not_called()

    def test_missing_and_stale_authorization_return_correlated_409(self) -> None:
        cases = (
            "predictor_authorization_required",
            "predictor_authorization_stale",
        )
        for code in cases:
            with self.subTest(code=code), patch.object(
                eda_router,
                "authorize_modeling_scope",
                return_value=PROJECT_ID,
            ), patch.object(
                eda_router.eda_workspace_service,
                "section",
                side_effect=EDAAnalyticalContractError(
                    "The governed predictor authorization is not current.",
                    code=code,
                    recovery="Return to Data Acquisition and reconfirm it.",
                    stale_artifacts=["predictor_eda"],
                ),
            ):
                response = _client().post(
                    "/api/eda/workspace/overview",
                    json=_request_json(),
                )

            self.assertEqual(response.status_code, 409, response.text)
            detail = response.json()["detail"]
            self.assertEqual(detail["code"], code)
            self.assertEqual(detail["stale_artifacts"], ["predictor_eda"])
            self.assertRegex(detail["correlation_id"], r"^eda-[0-9a-f]{32}$")
            self.assertEqual(
                response.headers["x-request-correlation-id"],
                detail["correlation_id"],
            )

    def test_expected_request_error_returns_correlated_nonempty_422(self) -> None:
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ), patch.object(
            eda_router.eda_workspace_service,
            "section",
            side_effect=ValueError("Unsupported governed EDA section."),
        ):
            response = _client().post(
                "/api/eda/workspace/not-a-section",
                json=_request_json(),
            )

        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "eda_request_invalid")
        self.assertTrue(detail["message"])
        self.assertEqual(
            response.headers["x-request-correlation-id"],
            detail["correlation_id"],
        )

    def test_dataset_identity_exception_is_normalized_to_correlated_409(self) -> None:
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ), patch.object(
            eda_router.eda_workspace_service,
            "section",
            side_effect=HTTPException(status_code=409, detail="internal identity mismatch detail"),
        ):
            response = _client().post(
                "/api/eda/workspace/overview",
                json=_request_json(),
            )

        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "dataset_identity_mismatch")
        self.assertNotIn("internal identity mismatch detail", response.text)
        self.assertEqual(
            response.headers["x-request-correlation-id"],
            detail["correlation_id"],
        )

    def test_unexpected_error_is_safe_correlated_and_logged_server_side(self) -> None:
        sensitive_detail = "C:\\secret\\regulated.csv token=do-not-expose"
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ), patch.object(
            eda_router.eda_workspace_service,
            "section",
            side_effect=RuntimeError(sensitive_detail),
        ), patch.object(eda_router.logger, "exception") as logged:
            response = _client().post(
                "/api/eda/workspace/overview",
                json=_request_json(),
            )

        self.assertEqual(response.status_code, 500, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "internal_eda_execution_error")
        self.assertRegex(detail["correlation_id"], r"^eda-[0-9a-f]{32}$")
        self.assertEqual(
            response.headers["x-request-correlation-id"],
            detail["correlation_id"],
        )
        self.assertNotIn("secret", response.text.casefold())
        self.assertNotIn("regulated.csv", response.text.casefold())
        self.assertNotIn("traceback", response.text.casefold())
        logged.assert_called_once()
        self.assertIn(detail["correlation_id"], logged.call_args.args)

    def test_nested_eda_routes_preserve_precise_canonical_lineage_409(self) -> None:
        cases = (
            (
                "/api/eda/target-by-predictor",
                "target_by_predictor",
                {"predictor": "risk"},
            ),
            (
                "/api/eda/vif-simulation",
                "vif_simulation",
                {"excluded_feature": "risk"},
            ),
            (
                "/api/eda/vif-resolution-plan",
                "vif_resolution_plan",
                {},
            ),
            (
                "/api/eda/vif-resolution-plan/decision",
                "vif_resolution_decision",
                {"plan_id": "vif-plan-test", "action": "defer"},
            ),
            (
                "/api/eda/relationship-sample",
                "relationship_sample",
                {"x_feature": "risk", "y_feature": "balance"},
            ),
        )
        for path, service_method, extras in cases:
            with self.subTest(path=path), patch.object(
                eda_router,
                "authorize_modeling_scope",
                return_value=PROJECT_ID,
            ), patch.object(
                eda_router.eda_workspace_service,
                service_method,
                side_effect=EDAAnalyticalContractError(
                    "The requested Analysis Partition revision is stale.",
                    code="analysis_partition_stale",
                    recovery="Reload Data Acquisition and retry.",
                    stale_artifacts=["relationship_eda"],
                ),
            ):
                response = _client().post(
                    path,
                    json={**_request_json(), **extras},
                )

            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(
                response.json()["detail"],
                {
                    "ok": False,
                    "code": "analysis_partition_stale",
                    "message": "The requested Analysis Partition revision is stale.",
                    "recovery": "Reload Data Acquisition and retry.",
                    "stale_artifacts": ["relationship_eda"],
                },
            )


class EDANestedCanonicalLineageServiceContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.request_values = _request_json()

    def _assert_strict_dataset_entry(self, method_name: str, request: object) -> None:
        marker = EDAAnalyticalContractError(
            "stop after strict handoff capture",
            code="eda_canonical_lineage_required",
        )
        with patch.object(
            eda_workspace_service,
            "_dataset",
            side_effect=marker,
        ) as dataset_call:
            with self.assertRaises(EDAAnalyticalContractError):
                if method_name == "vif_resolution_decision":
                    getattr(eda_workspace_service, method_name)(
                        request,
                        actor_id="nested-lineage-test",
                    )
                else:
                    getattr(eda_workspace_service, method_name)(request)
        self.assertTrue(dataset_call.call_args.kwargs["canonical_lineage_required"])
        canonical = dataset_call.call_args.args[0]
        for field in (
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "activation_revision",
            "target_contract_id",
            "target",
            "positive_value",
            "negative_value",
            "predictor_authorization_id",
            "analysis_partition_id",
            "analysis_partition_revision",
            "special_value_review_id",
            "special_value_review_revision",
        ):
            self.assertEqual(
                getattr(canonical, field),
                self.request_values[field],
                field,
            )

    def test_every_nested_calculation_enters_the_strict_dataset_resolver(self) -> None:
        cases = (
            (
                "_target_by_predictor_locked",
                TargetByPredictorRequest(
                    **self.request_values,
                    predictor="risk",
                ),
            ),
            (
                "_vif_simulation_locked",
                EDAVifSimulationRequest(
                    **self.request_values,
                    excluded_feature="risk",
                ),
            ),
            (
                "_vif_resolution_plan_locked",
                EDAVifResolutionPlanRequest(**self.request_values),
            ),
            (
                "vif_resolution_decision",
                EDAVifResolutionDecisionRequest(
                    **self.request_values,
                    plan_id="vif-plan-test",
                    action="defer",
                ),
            ),
            (
                "_relationship_sample_locked",
                EDARelationshipSampleRequest(
                    **self.request_values,
                    x_feature="risk",
                    y_feature="balance",
                ),
            ),
        )
        for method_name, request in cases:
            with self.subTest(method=method_name):
                self._assert_strict_dataset_entry(method_name, request)

    def test_nested_response_envelope_exposes_full_canonical_lineage(self) -> None:
        contract = {
            "contract_version": "eda-contract-v-test",
            "artifact_id": "eda-artifact-test",
            "artifact_hash": "eda-hash-test",
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "activation_revision": 7,
            "target": TARGET,
            "target_contract_id": "target-contract-test",
            "problem_type": "classification",
            "positive_value": 1,
            "negative_value": 0,
            "predictor_authorization_id": "predictor-auth-test",
            "analysis_partition_id": "analysis-partition-test",
            "analysis_partition_revision": 5,
            "analysis_partition_artifact_hash": "partition-artifact-test",
            "analysis_partition_assignment_hash": "partition-assignment-test",
            "special_value_review_id": "special-review-test",
            "special_value_review_revision": 3,
            "rows_used": 80,
            "population_rows": 100,
            "rows_excluded": 20,
            "exclusion_reasons": ["sealed_final_holdout_excluded"],
            "analysis_population_id": "development-test",
            "split_id": "analysis-partition-test",
        }
        result = eda_workspace_service._canonical_nested_response_lineage(
            contract,
            analysis_source="eda.test",
            analysis_scope={"sampled": True},
        )

        for field in (
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "activation_revision",
            "target_contract_id",
            "target",
            "positive_value",
            "negative_value",
            "predictor_authorization_id",
            "analysis_partition_id",
            "analysis_partition_revision",
            "analysis_partition_artifact_hash",
            "analysis_partition_assignment_hash",
            "special_value_review_id",
            "special_value_review_revision",
        ):
            self.assertEqual(result[field], contract[field], field)
        self.assertEqual(result["scope"], "development_population")
        self.assertFalse(result["final_holdout_accessed"])
        self.assertTrue(result["analysis_scope"]["sampled"])
        self.assertIn(
            "sealed_final_holdout_excluded",
            result["analysis_scope"]["exclusionReasons"],
        )

    def test_vif_decision_rejects_a_plan_from_an_old_partition_revision(self) -> None:
        contract = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "activation_revision": 1,
            "target_contract_id": "target-contract-test",
            "target": TARGET,
            "positive_value": 1,
            "negative_value": 0,
            "predictor_authorization_id": "predictor-auth-test",
            "analysis_partition_id": "analysis-partition-test",
            "analysis_partition_revision": 2,
            "special_value_review_id": "special-review-test",
            "special_value_review_revision": 1,
        }
        plan = {"inputs": {**contract, "analysis_partition_revision": 1}}
        with self.assertRaises(EDAAnalyticalContractError) as raised:
            eda_workspace_service._require_current_vif_plan_lineage(plan, contract)
        self.assertEqual(raised.exception.code, "vif_resolution_plan_stale")


class TargetIntelligenceCanonicalLineageAdapterTest(unittest.TestCase):
    @staticmethod
    def _payload() -> target_intelligence_router.TargetByPredictorRequest:
        canonical = {
            key: value
            for key, value in _request_json().items()
            if key
            not in {
                "problem_type",
                "selected_features",
            }
        }
        return target_intelligence_router.TargetByPredictorRequest(
            projectId=PROJECT_ID,
            datasetId=DATASET_ID,
            versionId=VERSION_ID,
            target=TARGET,
            predictor="risk",
            analysisType="numeric_quantile",
            eventValue=1,
            canonicalLineage=canonical,
        )

    def test_analytics_adapter_carries_every_canonical_field_to_eda(self) -> None:
        with patch.object(
            target_intelligence_router,
            "_check_project_access",
        ), patch.object(
            target_intelligence_router,
            "_require_active_version",
            return_value={
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
            },
        ), patch.object(
            eda_workspace_service,
            "target_by_predictor",
            return_value={"ok": True},
        ) as target_call:
            result = target_intelligence_router.target_by_predictor(
                self._payload(),
                {"userId": "nested-lineage-test"},
            )

        self.assertEqual(result, {"ok": True})
        adapted = target_call.call_args.args[0]
        for field in (
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "activation_revision",
            "target_contract_id",
            "target",
            "positive_value",
            "negative_value",
            "predictor_authorization_id",
            "analysis_partition_id",
            "analysis_partition_revision",
            "special_value_review_id",
            "special_value_review_revision",
        ):
            self.assertEqual(
                getattr(adapted, field),
                getattr(self._payload().canonicalLineage, field),
                field,
            )

    def test_analytics_adapter_preserves_the_precise_readiness_code(self) -> None:
        with patch.object(
            target_intelligence_router,
            "_check_project_access",
        ), patch.object(
            target_intelligence_router,
            "_require_active_version",
            return_value={
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
            },
        ), patch.object(
            eda_workspace_service,
            "target_by_predictor",
            side_effect=EDAAnalyticalContractError(
                "The Special-Value Review revision is stale.",
                code="special_value_review_stale",
                recovery="Reload Data Acquisition.",
                stale_artifacts=["predictor_eda"],
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                target_intelligence_router.target_by_predictor(
                    self._payload(),
                    {"userId": "nested-lineage-test"},
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail["code"],
            "special_value_review_stale",
        )


class EDAStrictPredictorAuthorityAndCacheTest(unittest.TestCase):
    def test_durable_predictor_inventory_is_not_reclassified_under_same_id(self) -> None:
        frame = pd.DataFrame(
            {
                "risk": [1.0, 2.0, 3.0, 4.0],
                # Deliberately deterministic of the target. EDA is a reader of
                # this durable inventory and must not silently reclassify it.
                "upstream_signal": [0, 1, 0, 1],
                TARGET: [0, 1, 0, 1],
            }
        )
        manifest = {
            "predictor_authorization_id": "predictor-auth-verbatim",
            "manifest_version": "predictor-auth-verbatim",
            "authorized_predictors": ["risk", "upstream_signal"],
            "excluded_predictors": {},
            "target_source_excluded": [],
            "target_source_fields": [],
        }
        self.assertFalse(
            hasattr(workspace_service_module, "_detect_frame_target_sources"),
            "Target-source discovery belongs to Data Acquisition, not EDA.",
        )
        authorization = _predictor_authorization(
            frame,
            TARGET,
            durable_manifest=manifest,
        )
        self.assertEqual(
            authorization["authorized_predictors"],
            ["risk", "upstream_signal"],
        )
        self.assertEqual(
            authorization["predictor_authorization_id"],
            "predictor-auth-verbatim",
        )

    def test_workspace_cache_key_ignores_ambient_partition_metadata(self) -> None:
        store = DatasetStore()
        store.set_raw(
            pd.DataFrame(
                {"risk": [1.0, 2.0], "balance": [2.0, 3.0], TARGET: [0, 1]}
            )
        )
        store.meta.update(
            {
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                "activation_revision": 1,
                "analysis_partition": {
                    "analysis_partition_id": "ambient-stale-a",
                    "revision": 99,
                    "artifact_hash": "ambient-stale-a",
                },
            }
        )
        request = EDAWorkspaceRequest(**_request_json())
        authorization = {
            "manifest_version": "predictor-auth-test",
            "authorized_predictors": ["risk", "balance"],
        }
        contract = {
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "activation_revision": 1,
            "target_contract_id": "target-contract-test",
            "predictor_authorization_id": "predictor-auth-test",
            "analysis_partition_id": "analysis-partition-current",
            "analysis_partition_revision": 4,
            "special_value_review_id": "special-review-test",
            "special_value_review_revision": 2,
            "positive_value": 1,
            "problem_type": "classification",
            "target_artifact": {"artifact_hash": "target-artifact-test"},
            "development_scope": {
                "analysis_partition_status": "current",
                "analysis_partition_artifact_hash": "partition-artifact-current",
                "analysis_partition_assignment_hash": "assignment-current",
            },
        }
        with patch(
            "server.core.dataset_store.DatasetStoreProxy.current",
            return_value=store,
        ):
            first = eda_workspace_service._key(
                "relationships",
                request,
                store.raw_df,
                TARGET,
                authorization,
                "workspace-fingerprint",
                contract,
            )
            store.meta["analysis_partition"] = {
                "analysis_partition_id": "ambient-stale-b",
                "revision": 100,
                "artifact_hash": "ambient-stale-b",
            }
            second = eda_workspace_service._key(
                "relationships",
                request,
                store.raw_df,
                TARGET,
                authorization,
                "workspace-fingerprint",
                contract,
            )

        self.assertEqual(first, second)

    def test_feature_vif_compatibility_is_exact_and_target_free(self) -> None:
        store = DatasetStore()
        store.set_processed(
            pd.DataFrame(
                {
                    "risk": [1.0, 2.0, 3.0, 4.0, 5.0],
                    "balance": [5.0, 4.0, 3.0, 2.0, 1.0],
                    TARGET: [0, 1, 0, 1, 0],
                }
            )
        )
        manifest = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "manifest_hash": "feature-manifest-test",
            "manifest_version": "feature-manifest-test",
            "materialized_manifest_hash": "feature-manifest-test",
            "materialization_status": "current",
            "features": [
                {
                    "feature_name": "risk",
                    "selected": True,
                    "eligibility_status": "eligible",
                },
                {
                    "feature_name": "balance",
                    "selected": True,
                    "eligibility_status": "eligible",
                },
            ],
        }
        identity = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "activation_revision": 1,
        }
        request = EDAWorkspaceRequest(
            project_id=PROJECT_ID,
            expected_dataset_id=DATASET_ID,
            expected_dataset_version_id=VERSION_ID,
            dataset_version=VERSION_ID,
            selected_features=["risk", "balance"],
        )
        with patch(
            "server.core.dataset_store.DatasetStoreProxy.current",
            return_value=store,
        ), patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value=identity,
        ), patch(
            "server.features.feature_manifest_store.load_current_manifest",
            return_value=manifest,
        ), patch(
            "server.eda.workspace_service._restore_target_from_exact_predictor_authorization",
            side_effect=AssertionError("Target authority must not be resolved."),
        ) as target_restore, patch.object(
            analysis_partition_service,
            "current",
            side_effect=AssertionError("Analysis Partition must not be resolved."),
        ) as partition_lookup:
            result = eda_workspace_service.predictor_only_relationships(
                request
            )

        target_restore.assert_not_called()
        partition_lookup.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertFalse(result["target_accessed"])
        self.assertFalse(result["target_association_exposed"])
        self.assertEqual(result["target_association"], [])
        self.assertEqual(result["pairwise_sample"], [])
        self.assertNotIn("target", result)


class EDAFreshProcessExactAuthorityHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        # Acceptance-shaped HELOC population size: the governed 80/20
        # Analysis Partition must reconstruct exactly 5,020 development rows
        # while leaving 1,255 sealed-holdout rows untouched.
        rows = 6_275
        target = np.asarray([index % 2 for index in range(rows)], dtype=np.int64)
        frame = pd.DataFrame(
            {
                "risk": np.linspace(20.0, 95.0, rows),
                "balance": np.asarray(
                    [float((index * 7) % 103) for index in range(rows)]
                ),
                "inquiries": np.asarray(
                    [int((index * 3) % 11) for index in range(rows)],
                    dtype=np.int64,
                ),
                TARGET: target,
            }
        )
        self.store = DatasetStore()
        self.store.set_raw(frame)
        self.store.set_target(TARGET)
        self.store.meta.update(
            {
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                # Recovered Dataset Library metadata deliberately omits target.
                "source": {
                    "kind": "dataset_library",
                    "datasetId": DATASET_ID,
                    "version": VERSION_ID,
                    "rowCount": rows,
                    "columnCount": len(frame.columns),
                },
            }
        )
        self.fixture = GovernedAnalysisFixture(project_id=PROJECT_ID)
        self.installed = self.fixture.install(
            self.store,
            dataset_id=DATASET_ID,
            dataset_version_id=VERSION_ID,
            target=TARGET,
            authorized_predictors=PREDICTORS,
            positive_value=np.int64(1),
            negative_value=np.int64(0),
            development_share=0.8,
        )

        # Model a fresh process after exact recovered-registry activation: the
        # frame and identity are present, but target/checkpoint/FE projections
        # are not. The durable authorization and Analysis Partition remain.
        self.store.set_target(None)
        for key in (
            "target_contract_id",
            "target_contract",
            "predictor_authorization_id",
            "predictor_authorization",
            "predictor_authorization_manifest",
            "feature_manifest",
            "selected_columns",
        ):
            self.store.meta.pop(key, None)
        eda_workspace_service._cache.clear()
        eda_workspace_service._contract_cache.clear()

    def tearDown(self) -> None:
        eda_workspace_service._cache.clear()
        eda_workspace_service._contract_cache.clear()
        self.fixture.close()

    def test_exact_authority_restores_target_and_uses_development_only(self) -> None:
        identity = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "activation_revision": 1,
        }
        request_payload = _request_json()
        request_payload.update(
            {
                "target_contract_id": self.installed["authorization"][
                    "target_contract_id"
                ],
                "predictor_authorization_id": self.installed[
                    "authorization"
                ]["predictor_authorization_id"],
                "analysis_partition_id": self.installed["record"][
                    "analysis_partition_id"
                ],
                "analysis_partition_revision": self.installed["record"][
                    "revision"
                ],
                "special_value_review_id": self.installed[
                    "special_value_review"
                ]["special_value_review_id"],
                "special_value_review_revision": self.installed[
                    "special_value_review"
                ]["revision"],
            }
        )
        repository = self.fixture.persistence.predictor_authorizations
        original_get_current_exact = repository.get_current_exact
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ), patch(
            "server.core.dataset_store.DatasetStoreProxy.current",
            return_value=self.store,
        ), patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value=identity,
        ), patch.object(
            repository,
            "get_current_exact",
            wraps=original_get_current_exact,
        ) as exact_lookup, patch.object(
            analysis_partition_service,
            "materialize_validation",
            side_effect=AssertionError(
                "EDA must not request the combined development/holdout accessor."
            ),
        ) as combined_accessor:
            response = _client().post(
                "/api/eda/workspace/overview",
                json=request_payload,
            )
            direct = eda_workspace_service.section(
                "overview",
                EDAWorkspaceRequest(**request_payload),
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        contract = payload["governed_analytical_contract"]
        self.assertEqual(contract["analysis_scope"], "development_population")
        self.assertEqual(contract["rows_used"], 5_020)
        self.assertEqual(contract["rows_excluded"], 1_255)
        self.assertEqual(contract["activation_revision"], 1)
        self.assertEqual(
            contract["target_contract_id"],
            request_payload["target_contract_id"],
        )
        self.assertEqual(
            contract["predictor_authorization_id"],
            request_payload["predictor_authorization_id"],
        )
        self.assertEqual(
            contract["analysis_partition_id"],
            request_payload["analysis_partition_id"],
        )
        self.assertEqual(
            contract["analysis_partition_revision"],
            request_payload["analysis_partition_revision"],
        )
        self.assertEqual(
            contract["special_value_review_id"],
            request_payload["special_value_review_id"],
        )
        self.assertEqual(
            contract["special_value_review_revision"],
            request_payload["special_value_review_revision"],
        )
        self.assertFalse(contract["final_holdout_accessed"])
        self.assertFalse(contract["final_holdout_used_for_selection"])
        self.assertEqual(self.store.target, TARGET)
        self.assertEqual(
            self.store.meta["target_contract_id"],
            self.installed["authorization"]["target_contract_id"],
        )
        self.assertNotIn("feature_manifest", self.store.meta)
        exact_lookup.assert_called_with(
            PROJECT_ID,
            DATASET_ID,
            VERSION_ID,
            None,
        )
        self.assertGreaterEqual(exact_lookup.call_count, 1)
        combined_accessor.assert_not_called()
        self.assertIs(type(direct["governed_analytical_contract"]["positive_value"]), int)
        self.assertIs(type(direct["governed_analytical_contract"]["negative_value"]), int)
        self.assertRegex(
            response.headers["x-request-correlation-id"],
            r"^eda-[0-9a-f]{32}$",
        )

    def test_http_handoff_checks_actual_prerequisites_before_missing_request_lineage(self) -> None:
        identity = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "activation_revision": 1,
        }
        request_payload = _request_json()
        request_payload.update(
            {
                "predictor_authorization_id": self.installed[
                    "authorization"
                ]["predictor_authorization_id"],
                "analysis_partition_id": self.installed["record"][
                    "analysis_partition_id"
                ],
                "analysis_partition_revision": self.installed["record"][
                    "revision"
                ],
                "special_value_review_id": self.installed[
                    "special_value_review"
                ]["special_value_review_id"],
                "special_value_review_revision": self.installed[
                    "special_value_review"
                ]["revision"],
            }
        )
        request_payload.pop("target_contract_id")

        special_reviews = self.fixture.persistence.special_value_reviews
        original_get_exact = special_reviews.get_exact
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ), patch(
            "server.core.dataset_store.DatasetStoreProxy.current",
            return_value=self.store,
        ), patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value=identity,
        ), patch.object(
            special_reviews,
            "get_exact",
            wraps=original_get_exact,
        ) as review_lookup:
            response = _client().post(
                "/api/eda/workspace/overview",
                json=request_payload,
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "eda_canonical_lineage_required",
        )
        review_lookup.assert_called_once_with(
            PROJECT_ID,
            DATASET_ID,
            VERSION_ID,
        )

    def test_incomplete_special_review_blocks_before_target_materialization(self) -> None:
        identity = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "activation_revision": 1,
        }
        request_payload = _request_json()
        request_payload.update(
            {
                "target_contract_id": self.installed["authorization"][
                    "target_contract_id"
                ],
                "predictor_authorization_id": self.installed[
                    "authorization"
                ]["predictor_authorization_id"],
                "analysis_partition_id": self.installed["record"][
                    "analysis_partition_id"
                ],
                "analysis_partition_revision": self.installed["record"][
                    "revision"
                ],
                "special_value_review_id": self.installed[
                    "special_value_review"
                ]["special_value_review_id"],
                "special_value_review_revision": self.installed[
                    "special_value_review"
                ]["revision"],
            }
        )
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ), patch(
            "server.core.dataset_store.DatasetStoreProxy.current",
            return_value=self.store,
        ), patch(
            "server.eda.workspace_service.assert_expected_active_identity",
            return_value=identity,
        ), patch(
            "server.eda.workspace_service._resolve_current_special_value_review",
            side_effect=EDAAnalyticalContractError(
                "The Special-Value Review is incomplete.",
                code="special_value_review_required",
            ),
        ), patch.object(
            analysis_partition_service,
            "materialize_development",
            side_effect=AssertionError(
                "Target values must not be materialized before prerequisites pass."
            ),
        ) as materialize:
            response = _client().post(
                "/api/eda/workspace/overview",
                json=request_payload,
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "special_value_review_required",
        )
        materialize.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
