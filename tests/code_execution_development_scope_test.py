from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi import HTTPException

from server.analysis_partition.service import analysis_partition_service
from server.code_execution.dataset_binding import (
    bind_development_dataset,
    runtime_contract_description,
    stage_dataset_for_sandbox,
)
from server.core.dataset_store import DATASTORE
from server.core.modeling_scope import set_active_project_id
from server import python_execution
from server.notebooks import notebook_router
from server.notebooks.notebook_store import normalize_notebook
from tests.analysis_partition_fixture import GovernedAnalysisFixture


PROJECT_ID = "project-code-development-scope"
DATASET_ID = "dataset-code-development-scope"
VERSION_ID = "version-code-development-scope-v1"
TARGET = "event"
PREDICTORS = ["signal", "noise"]
USER = {"userId": "governed-analysis-test", "role": "analyst"}


class GovernedCodeExecutionScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        set_active_project_id(PROJECT_ID)
        self.store = DATASTORE.current()
        self.store.reset_all()
        frame = pd.DataFrame(
            {
                "signal": np.arange(48, dtype=float),
                "noise": np.arange(48, dtype=float) * -0.5,
                "unauthorized_sentinel": [f"forbidden-{value}" for value in range(48)],
                TARGET: [0, 1] * 24,
            },
            index=pd.Index([position // 2 for position in range(48)]),
        )
        self.store.set_raw(frame)
        self.store.set_target(TARGET)
        self.store.meta.update(
            {
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                "selected_columns": list(PREDICTORS),
            }
        )
        self.fixture = GovernedAnalysisFixture(project_id=PROJECT_ID)
        self.installation = self.fixture.install(
            self.store,
            dataset_id=DATASET_ID,
            dataset_version_id=VERSION_ID,
            target=TARGET,
            authorized_predictors=PREDICTORS,
            positive_value=1,
            negative_value=0,
            excluded_predictors={
                "unauthorized_sentinel": "Synthetic unauthorized sentinel",
            },
            development_share=0.8,
            random_seed=97,
        )
        self.identity = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
        }
        self.partition = self.installation["record"]

    def tearDown(self) -> None:
        self.fixture.close()
        self.store.reset_all()
        set_active_project_id(None)

    def _request(self, **context_updates):
        context = {
            "datasetId": DATASET_ID,
            "versionId": VERSION_ID,
            "target": TARGET,
            "eventValue": 1,
            "nonEventValue": 0,
            "targetContractId": self.partition["target_contract_id"],
            "analysisPartitionId": self.partition["analysis_partition_id"],
            "analysisPartitionRevision": self.partition["revision"],
            **context_updates,
        }
        return python_execution.PythonRunRequest(
            page="EDA",
            userCode="print(len(df))",
            projectId=PROJECT_ID,
            workflowStep="step02",
            context=context,
        )

    def _route(self, request):
        captured = {}

        def capture_run(received, *, governed_bound=None):
            captured["request"] = received
            captured["bound"] = governed_bound
            return {"ok": True, "runtimeContract": runtime_contract_description(governed_bound)}

        with (
            patch.object(python_execution, "authorize_modeling_scope", return_value=PROJECT_ID),
            patch.object(python_execution, "active_dataset_identity", return_value=dict(self.identity)),
            patch.object(python_execution, "assert_expected_active_identity", return_value=dict(self.identity)),
            patch.object(python_execution, "get_persistence_service", return_value=self.fixture.persistence),
            patch.object(python_execution, "run_python_request", side_effect=capture_run),
        ):
            response = python_execution.run_python(request, USER)
        return response, captured

    def test_predictive_execution_binds_only_verified_development_positions(self):
        with patch.object(
            analysis_partition_service,
            "materialize_validation",
            side_effect=AssertionError("Final holdout materialization is forbidden."),
        ):
            response, captured = self._route(self._request())

        bound = captured["bound"]
        positions = self.partition["row_assignments_json"]["development_positions"]
        expected = self.store.raw_df.iloc[positions]
        self.assertEqual(bound.row_count, len(positions))
        self.assertEqual(bound.development_frame[TARGET].tolist(), expected[TARGET].tolist())
        self.assertEqual(bound.development_frame["signal"].tolist(), expected["signal"].tolist())
        self.assertEqual(bound.development_frame.index.tolist(), list(range(len(positions))))
        self.assertNotIn("unauthorized_sentinel", bound.development_frame.columns)
        self.assertEqual(bound.analytical_scope, "development_population")
        self.assertTrue(bound.holdout_excluded)
        self.assertEqual(response["runtimeContract"]["partitionId"], self.partition["analysis_partition_id"])
        self.assertEqual(response["runtimeContract"]["partitionRevision"], self.partition["revision"])
        self.assertEqual(response["runtimeContract"]["source"], "sealed_analysis_partition_development")
        self.assertEqual(captured["request"].context["previewRows"], [])

    def test_staged_extract_contains_no_holdout_rows_and_survives_holdout_target_changes(self):
        response, captured = self._route(self._request())
        before = captured["bound"]
        holdout_positions = self.partition["row_assignments_json"]["holdout_positions"]
        target_position = self.store.raw_df.columns.get_loc(TARGET)
        self.store.raw_df.iloc[holdout_positions, target_position] = 9
        _, after_capture = self._route(self._request())
        after = after_capture["bound"]
        self.assertEqual(before.development_frame.to_dict("records"), after.development_frame.to_dict("records"))
        self.assertNotIn(9, after.development_frame[TARGET].tolist())

        stage_root = Path(__file__).resolve().parents[1] / ".tmp"
        with (
            patch.object(after.development_frame, "to_csv") as write_csv,
            patch(
                "server.code_execution.dataset_binding.shutil.copyfile",
                side_effect=AssertionError("The registered full artifact must not be copied."),
            ),
        ):
            staged = stage_dataset_for_sandbox(after, stage_root)
        write_csv.assert_called_once_with(staged, index=False)
        self.assertEqual(len(after.development_frame), self.partition["development_count"])
        self.assertNotIn(9, after.development_frame[TARGET].tolist())
        self.assertNotIn("unauthorized_sentinel", after.development_frame.columns)

    def test_missing_stale_and_cross_identity_contracts_fail_closed(self):
        with self.assertRaises(HTTPException) as missing:
            self._route(
                self._request(
                    analysisPartitionId="",
                    analysisPartitionRevision=0,
                    targetContractId="",
                )
            )
        self.assertEqual(missing.exception.status_code, 422)

        with self.assertRaises(HTTPException) as stale:
            self._route(self._request(analysisPartitionId="analysis-partition-stale"))
        self.assertEqual(stale.exception.status_code, 409)

        with self.assertRaises(HTTPException) as stale_revision:
            self._route(
                self._request(
                    analysisPartitionRevision=int(self.partition["revision"]) + 1,
                )
            )
        self.assertEqual(stale_revision.exception.status_code, 409)

        crossed = self._request(versionId="other-version")
        with (
            patch.object(python_execution, "authorize_modeling_scope", return_value=PROJECT_ID),
            patch.object(python_execution, "active_dataset_identity", return_value=dict(self.identity)),
            patch.object(
                python_execution,
                "assert_expected_active_identity",
                side_effect=HTTPException(status_code=409, detail="Exact version mismatch."),
            ),
            patch.object(python_execution, "get_persistence_service", return_value=self.fixture.persistence),
        ):
            with self.assertRaises(HTTPException) as cross_version:
                python_execution.run_python(crossed, USER)
        self.assertEqual(cross_version.exception.status_code, 409)

    def test_target_contract_and_class_mapping_contradictions_fail_closed(self):
        contradictions = [
            {"targetContractId": "target-contract-wrong"},
            {"target": "wrong_target"},
            {"eventValue": 9},
            {"nonEventValue": 9},
        ]
        for updates in contradictions:
            with self.subTest(updates=updates):
                with self.assertRaises(HTTPException) as rejected:
                    self._route(self._request(**updates))
                self.assertEqual(rejected.exception.status_code, 409)

    def test_internal_predictive_executor_cannot_resolve_registered_artifact_without_bound(self):
        request = self._request()
        with (
            patch.object(
                python_execution.sandbox_policy,
                "describe_capability",
                return_value=SimpleNamespace(
                    available=True,
                    state="executable",
                    reason="",
                ),
            ),
            patch.object(
                python_execution,
                "project_requires_development_binding",
                return_value=True,
            ),
            patch.object(
                python_execution,
                "resolve_bound_dataset",
                side_effect=AssertionError(
                    "Registered artifact resolution must not be attempted."
                ),
            ),
        ):
            with self.assertRaises(HTTPException) as rejected:
                python_execution.run_python_request(request)
        self.assertEqual(rejected.exception.status_code, 409)

    def test_predictive_notebook_routes_through_same_exact_development_binding(self):
        payload = notebook_router.RunCellRequest(
            cellId="cell-python",
            cellType="python",
            source="print(len(df))",
            projectId=PROJECT_ID,
            primaryDatasetId=DATASET_ID,
            primaryVersionId=VERSION_ID,
            target=TARGET,
            eventValue=1,
            nonEventValue=0,
            targetContractId=self.partition["target_contract_id"],
            analysisPartitionId=self.partition["analysis_partition_id"],
            analysisPartitionRevision=self.partition["revision"],
        )
        captured = {}

        def route_through_governed_endpoint(request, user):
            captured["initial_context"] = dict(request.context)
            response, routed = self._route(request)
            captured.update(routed)
            return response

        with (
            patch.object(
                notebook_router,
                "authorize_modeling_scope",
                return_value=PROJECT_ID,
            ),
            patch.object(
                notebook_router,
                "project_requires_development_binding",
                return_value=True,
            ),
            patch.object(
                notebook_router,
                "dataset_context",
                side_effect=AssertionError(
                    "Predictive Notebook must not read a registered preview artifact."
                ),
            ),
            patch.object(
                notebook_router,
                "run_python",
                side_effect=route_through_governed_endpoint,
            ),
        ):
            result = notebook_router.run_cell(payload, user=USER)

        self.assertTrue(result["ok"])
        self.assertEqual(captured["initial_context"]["previewRows"], [])
        self.assertEqual(
            captured["initial_context"]["targetContractId"],
            self.partition["target_contract_id"],
        )
        self.assertEqual(
            captured["initial_context"]["analysisPartitionRevision"],
            self.partition["revision"],
        )
        bound = captured["bound"]
        self.assertEqual(bound.analytical_scope, "development_population")
        self.assertTrue(bound.holdout_excluded)
        self.assertNotIn("unauthorized_sentinel", bound.development_frame.columns)
        notebook_preview = captured["request"].context["previewRows"]
        self.assertEqual(len(notebook_preview), self.partition["development_count"])
        self.assertNotIn("unauthorized_sentinel", notebook_preview[0])

    def test_predictive_notebook_blocks_other_engines_before_preview_access(self):
        for cell_type in ("sql", "r", "sas_compatible"):
            payload = notebook_router.RunCellRequest(
                cellId=f"cell-{cell_type}",
                cellType=cell_type,
                source="select 1" if cell_type == "sql" else "print(1)",
                projectId=PROJECT_ID,
                primaryDatasetId=DATASET_ID,
                primaryVersionId=VERSION_ID,
            )
            with (
                self.subTest(cell_type=cell_type),
                patch.object(
                    notebook_router,
                    "authorize_modeling_scope",
                    return_value=PROJECT_ID,
                ),
                patch.object(
                    notebook_router,
                    "project_requires_development_binding",
                    return_value=True,
                ),
                patch.object(
                    notebook_router,
                    "dataset_context",
                    side_effect=AssertionError(
                        "Predictive Notebook must not read preview artifacts."
                    ),
                ),
            ):
                with self.assertRaises(HTTPException) as rejected:
                    notebook_router.run_cell(payload, user=USER)
            self.assertEqual(rejected.exception.status_code, 409)

    def test_non_predictive_notebook_retains_registered_preview_behavior(self):
        preview = [{"value": 7}]
        captured = {}

        def capture_run(request, *, governed_bound=None):
            captured["request"] = request
            captured["bound"] = governed_bound
            return {"ok": True, "status": "success", "stdout": "ok"}

        payload = notebook_router.RunCellRequest(
            cellId="cell-non-predictive",
            cellType="python",
            source="print(preview_rows)",
            projectId="project-experimental-design",
            primaryDatasetId="dataset-experimental-design",
            primaryVersionId="version-experimental-design-v1",
        )
        with (
            patch.object(
                notebook_router,
                "authorize_modeling_scope",
                return_value=payload.projectId,
            ),
            patch.object(
                notebook_router,
                "project_requires_development_binding",
                return_value=False,
            ),
            patch.object(
                notebook_router,
                "dataset_context",
                return_value={"previewRows": preview, "preview_rows": preview},
            ),
            patch.object(
                notebook_router,
                "run_python",
                side_effect=AssertionError(
                    "Non-predictive execution must retain its legacy route."
                ),
            ),
            patch.object(
                notebook_router,
                "run_python_request",
                side_effect=capture_run,
            ),
        ):
            result = notebook_router.run_cell(payload, user=USER)

        self.assertTrue(result["ok"])
        self.assertEqual(captured["request"].context["previewRows"], preview)
        self.assertIsNone(captured["bound"])

    def test_notebook_persistence_keeps_exact_predictive_scope(self):
        notebook = normalize_notebook(
            {
                "projectId": PROJECT_ID,
                "primaryDatasetId": DATASET_ID,
                "primaryVersionId": VERSION_ID,
                "target": TARGET,
                "eventValue": 1,
                "nonEventValue": 0,
                "targetContractId": self.partition["target_contract_id"],
                "analysisPartitionId": self.partition["analysis_partition_id"],
                "analysisPartitionRevision": self.partition["revision"],
            }
        )
        self.assertEqual(notebook["target"], TARGET)
        self.assertEqual(notebook["eventValue"], 1)
        self.assertEqual(notebook["nonEventValue"], 0)
        self.assertEqual(
            notebook["targetContractId"], self.partition["target_contract_id"]
        )
        self.assertEqual(
            notebook["analysisPartitionId"],
            self.partition["analysis_partition_id"],
        )
        self.assertEqual(
            notebook["analysisPartitionRevision"], self.partition["revision"]
        )

    def test_registered_identity_without_project_scope_is_rejected(self):
        request = python_execution.PythonRunRequest(
            userCode="print(1)",
            context={"datasetId": DATASET_ID, "versionId": VERSION_ID},
        )
        with self.assertRaises(HTTPException) as rejected:
            python_execution.run_python(request, USER)
        self.assertEqual(rejected.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
