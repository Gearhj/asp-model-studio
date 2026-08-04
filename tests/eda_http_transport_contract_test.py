"""HTTP transport and restart-shaped authority tests for governed EDA."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.analysis_partition.service import analysis_partition_service
from server.core.dataset_store import DatasetStore
from server.eda import eda_router
from server.eda.analytical_contract import EDAAnalyticalContractError
from server.eda.workspace_service import eda_workspace_service
from server.eda.workspace_types import EDAWorkspaceRequest
from tests.analysis_partition_fixture import GovernedAnalysisFixture


PROJECT_ID = "eda-http-transport-project"
DATASET_ID = "ds-eda-http-transport"
VERSION_ID = "v-eda-http-transport"
TARGET = "bad_flag"
PREDICTORS = ["risk", "balance", "inquiries"]


def _request_json() -> dict[str, object]:
    return {
        "project_id": PROJECT_ID,
        "expected_dataset_id": DATASET_ID,
        "expected_dataset_version_id": VERSION_ID,
        "dataset_version": VERSION_ID,
        "target": TARGET,
        "event_value": "1",
        "problem_type": "classification",
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
        ):
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
        }
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
                json=_request_json(),
            )
            direct = eda_workspace_service.section(
                "overview",
                EDAWorkspaceRequest(**_request_json()),
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        contract = payload["governed_analytical_contract"]
        self.assertEqual(contract["analysis_scope"], "development_population")
        self.assertEqual(contract["rows_used"], 5_020)
        self.assertEqual(contract["rows_excluded"], 1_255)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
