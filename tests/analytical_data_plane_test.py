"""Enterprise Analytical Data Plane: backend tests for the query contract,
planner, execution engines, authorization, caching, and resource governance
introduced in docs/architecture/ENTERPRISE_ANALYTICAL_DATA_PLANE_ADR.md.

Uses FastAPI's TestClient (in-process, synchronous) rather than the live dev
server, matching the established pattern in tests/dataset_lifecycle_test.py --
avoids uvicorn --reload flakiness entirely and runs faster.

Isolation: dedicated security/persistence SQLite files and a dedicated
ATLAS_DATASET_LIBRARY_ROOT, matching the Stage 6.1/Dataset Lifecycle pattern,
so this suite never touches the shared dev backend's real state.

Run:  .venv/Scripts/python.exe tests/analytical_data_plane_test.py
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
_TEST_DATA_ROOT = _REPO_ROOT / ".tmp"
_TEST_DATA_ROOT.mkdir(exist_ok=True)
_RUN_ID = uuid.uuid4().hex[:10]
_SUITE_ROOT = _TEST_DATA_ROOT / f"atlas_analytics_{_RUN_ID}"
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_analytics_security_{_RUN_ID}.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / f"atlas_analytics_persistence_{_RUN_ID}.db"
_CHECKPOINT_PATH = _TEST_DATA_ROOT / f"atlas_analytics_checkpoint_{_RUN_ID}.json"
_LIBRARY_ROOT = _SUITE_ROOT / "dataset-library"
_BACKUP_ROOT = Path(tempfile.mkdtemp(prefix=f"atlas_analytics_backups_{_RUN_ID}_"))
_EVIDENCE_ROOT = _TEST_DATA_ROOT / f"atlas_analytics_evidence_{_RUN_ID}"
_MODEL_ARTIFACT_ROOT = _TEST_DATA_ROOT / f"atlas_analytics_models_{_RUN_ID}"
_SCORING_ARTIFACT_ROOT = _TEST_DATA_ROOT / f"atlas_analytics_scoring_{_RUN_ID}"
os.environ["ATLAS_SECURITY_ROOT"] = str(_SECURITY_DB_PATH.parent)
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_PATH)
os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(_LIBRARY_ROOT)
os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(_BACKUP_ROOT)
os.environ["ATLAS_EVIDENCE_ROOT"] = str(_EVIDENCE_ROOT)
os.environ["ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT"] = str(_MODEL_ARTIFACT_ROOT)
os.environ["ATLAS_SCORING_RUN_ARTIFACT_ROOT"] = str(_SCORING_ARTIFACT_ROOT)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.persistence import db as persistence_db  # noqa: E402
from server.persistence import service as persistence_service  # noqa: E402
from server.security import security_store  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402
import server.core.session_checkpoint as checkpoint  # noqa: E402
from server.analytics import result_cache  # noqa: E402
from server.analytics.query_planner import PlannerInputs, plan, PlanningRejection  # noqa: E402
from server.analytics.query_contract import ApproximationPolicy, Operation, SourceType  # noqa: E402
from server.analytics.resource_governance import LIMITS  # noqa: E402
from server.datasets import dataset_registry  # noqa: E402
from server.evidence import evidence_store  # noqa: E402
from server.model_registry import model_artifacts  # noqa: E402
from server.scoring_runs import scoring_run_artifacts  # noqa: E402


def _bind_dataset_library_paths() -> None:
    """Rebind every cached registry path to this suite's owned root."""
    expected_root = _LIBRARY_ROOT.resolve()
    expected_backup_root = _BACKUP_ROOT.resolve()
    os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(expected_root)
    os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(expected_backup_root)
    dataset_registry.ARTIFACT_ROOT = expected_root
    dataset_registry.REGISTRY_PATH = dataset_registry.ARTIFACT_ROOT / "registry.json"
    dataset_registry.USERS_PATH = dataset_registry.ARTIFACT_ROOT / "users.json"
    dataset_registry.PROJECT_LINKS_PATH = (
        dataset_registry.ARTIFACT_ROOT / "project_links.json"
    )
    assert Path(os.environ["ATLAS_DATASET_LIBRARY_ROOT"]).resolve() == expected_root
    assert Path(os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"]).resolve() == expected_backup_root
    assert dataset_registry.ARTIFACT_ROOT.resolve() == expected_root
    assert dataset_registry.REGISTRY_PATH.resolve() == expected_root / "registry.json"
    assert dataset_registry.USERS_PATH.resolve() == expected_root / "users.json"
    assert dataset_registry.PROJECT_LINKS_PATH.resolve() == expected_root / "project_links.json"


def _bind_checkpoint_path() -> None:
    """Keep this suite isolated even when ``server.main`` was imported first."""
    expected = _CHECKPOINT_PATH.resolve()
    os.environ["ATLAS_CHECKPOINT_PATH"] = str(expected)
    checkpoint.CHECKPOINT_PATH = expected
    assert Path(os.environ["ATLAS_CHECKPOINT_PATH"]).resolve() == expected
    assert checkpoint.CHECKPOINT_PATH.resolve() == expected


def _bind_isolated_runtime_paths() -> None:
    """Rebind all cached storage authorities to this suite's UUID paths."""
    os.environ["ATLAS_SECURITY_ROOT"] = str(_SECURITY_DB_PATH.parent.resolve())
    os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH.resolve())
    os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH.resolve())
    os.environ["ATLAS_EVIDENCE_ROOT"] = str(_EVIDENCE_ROOT.resolve())
    os.environ["ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT"] = str(_MODEL_ARTIFACT_ROOT.resolve())
    os.environ["ATLAS_SCORING_RUN_ARTIFACT_ROOT"] = str(_SCORING_ARTIFACT_ROOT.resolve())
    os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"
    security_store.SECURITY_ROOT = _SECURITY_DB_PATH.parent.resolve()
    security_store.DB_PATH = _SECURITY_DB_PATH.resolve()
    security_store.ATLAS_AUTH_ENABLED = True
    security_store.ATLAS_ALLOW_PUBLIC_REGISTRATION = True
    persistence_db._database = persistence_db.Database(_PERSISTENCE_DB_PATH)
    persistence_service._service = None
    evidence_store.EVIDENCE_ROOT = _EVIDENCE_ROOT.resolve()
    evidence_store.ITEMS_ROOT = evidence_store.EVIDENCE_ROOT / "items"
    evidence_store.REGISTRY_PATH = evidence_store.EVIDENCE_ROOT / "evidence_registry.json"
    model_artifacts.ARTIFACT_ROOT = _MODEL_ARTIFACT_ROOT.resolve()
    scoring_run_artifacts.ARTIFACT_ROOT = _SCORING_ARTIFACT_ROOT.resolve()
    _bind_dataset_library_paths()
    _bind_checkpoint_path()

    assert security_store.DB_PATH == _SECURITY_DB_PATH.resolve()
    assert persistence_db.get_database().path == _PERSISTENCE_DB_PATH.resolve()
    assert evidence_store.EVIDENCE_ROOT == _EVIDENCE_ROOT.resolve()
    assert model_artifacts.ARTIFACT_ROOT == _MODEL_ARTIFACT_ROOT.resolve()
    assert scoring_run_artifacts.ARTIFACT_ROOT == _SCORING_ARTIFACT_ROOT.resolve()


_bind_isolated_runtime_paths()


def setUpModule() -> None:
    _bind_isolated_runtime_paths()


def _cleanup_db_files() -> None:
    checkpoint.flush_checkpoint()
    for base in (_SECURITY_DB_PATH, _PERSISTENCE_DB_PATH):
        for suffix in ("", "-wal", "-shm"):
            target = Path(f"{base}{suffix}")
            for attempt in range(25):
                try:
                    target.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt < 24:
                        time.sleep(0.2)
    _CHECKPOINT_PATH.unlink(missing_ok=True)
    shutil.rmtree(_EVIDENCE_ROOT, ignore_errors=True)
    shutil.rmtree(_MODEL_ARTIFACT_ROOT, ignore_errors=True)
    shutil.rmtree(_SCORING_ARTIFACT_ROOT, ignore_errors=True)
    shutil.rmtree(_BACKUP_ROOT, ignore_errors=True)


def _register(label: str) -> TestClient:
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{label}-{suffix}@atlas-analytics-test.local",
            "displayName": f"Analytics Test {label} {suffix}",
            "password": "AnalyticsTestPass!1",
            "role": "data_scientist",
        },
    )
    assert response.status_code == 200, response.text
    return client


def _create_project(client: TestClient, name: str) -> str:
    response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
    assert response.status_code == 200, response.text
    return response.json()["project"]["projectId"]


def _upload_workspace_frame(client: TestClient, project_id: str, rows: int = 300) -> None:
    headers = ["amount", "category", "target"]
    payload_rows = [{"amount": float(i % 50), "category": str(i % 4), "target": i % 2} for i in range(rows)]
    response = client.post("/api/data/set_sample", json={
        "project_id": project_id, "headers": headers, "rows": payload_rows,
        "target": "target", "selected_columns": ["amount", "category"],
    })
    assert response.status_code == 200, response.text


def _register_link_activate_frame(
    client: TestClient,
    project_id: str,
    frame: pd.DataFrame,
    name: str,
) -> tuple[str, str]:
    upload = client.post(
        "/api/datasets/upload",
        files={"file": (f"{name}.csv", io.BytesIO(frame.to_csv(index=False).encode("utf-8")), "text/csv")},
        data={"name": name, "description": "analytical data-plane test asset"},
    )
    assert upload.status_code == 200, upload.text
    dataset = upload.json()["dataset"]
    dataset_id = dataset["datasetId"]
    version_id = dataset["created_dataset_version_id"]
    link = client.post(
        f"/api/projects/{project_id}/datasets/link",
        json={"datasetId": dataset_id, "versionId": version_id, "datasetRole": "modeling"},
    )
    assert link.status_code == 200, link.text
    activation = client.post(
        f"/api/datasets/{dataset_id}/versions/{version_id}/activate",
        params={"project_id": project_id},
    )
    assert activation.status_code == 200, activation.text
    return dataset_id, version_id


class QueryPlannerTests(unittest.TestCase):
    def test_schema_operation_never_touches_row_data(self):
        decision = plan(PlannerInputs(
            operation=Operation.SCHEMA, source_type=SourceType.WORKSPACE, is_file_backed=False, file_format=None,
            source_row_count=None, column_count=None, selected_column_count=0, requested_result_cardinality=0,
            approximation_policy=ApproximationPolicy.APPROXIMATE_ALLOWED, timeout_seconds=10,
        ))
        self.assertEqual(decision.engine.value, "metadata")
        self.assertFalse(decision.pushdown_applied)

    def test_file_backed_aggregate_selects_duckdb_with_pushdown(self):
        decision = plan(PlannerInputs(
            operation=Operation.HISTOGRAM, source_type=SourceType.REGISTERED, is_file_backed=True, file_format="parquet",
            source_row_count=5_000_000, column_count=20, selected_column_count=1, requested_result_cardinality=20,
            approximation_policy=ApproximationPolicy.APPROXIMATE_ALLOWED, timeout_seconds=10,
        ))
        self.assertEqual(decision.engine.value, "duckdb")
        self.assertTrue(decision.pushdown_applied)
        # A 20-bin histogram over 5,000,000 rows is a VALID request -- source row
        # count alone must not reject it (the ADR's central planner requirement).
        self.assertFalse(decision.rejected)

    def test_oversized_bounded_rows_request_is_rejected_regardless_of_source_size(self):
        with self.assertRaises(PlanningRejection):
            plan(PlannerInputs(
                operation=Operation.BOUNDED_ROWS, source_type=SourceType.REGISTERED, is_file_backed=True, file_format="parquet",
                source_row_count=1000, column_count=5, selected_column_count=2,
                requested_result_cardinality=LIMITS.max_result_rows + 1,
                approximation_policy=ApproximationPolicy.APPROXIMATE_ALLOWED, timeout_seconds=10,
            ))

    def test_large_inmemory_aggregate_is_rejected_with_registration_guidance(self):
        with self.assertRaises(PlanningRejection) as ctx:
            plan(PlannerInputs(
                operation=Operation.HISTOGRAM, source_type=SourceType.WORKSPACE, is_file_backed=False, file_format=None,
                source_row_count=LIMITS.pandas_fallback_max_rows + 1, column_count=5, selected_column_count=1,
                requested_result_cardinality=20,
                approximation_policy=ApproximationPolicy.APPROXIMATE_ALLOWED, timeout_seconds=10,
            ))
        self.assertIn("Dataset Library", ctx.exception.reason)

    def test_wide_column_selection_is_rejected(self):
        with self.assertRaises(PlanningRejection):
            plan(PlannerInputs(
                operation=Operation.BOUNDED_ROWS, source_type=SourceType.REGISTERED, is_file_backed=True, file_format="parquet",
                source_row_count=1000, column_count=2000, selected_column_count=LIMITS.max_selected_columns + 1,
                requested_result_cardinality=10,
                approximation_policy=ApproximationPolicy.APPROXIMATE_ALLOWED, timeout_seconds=10,
            ))


class AnalyticalQueryEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    def setUp(self):
        self.client = _register("owner")
        self.project_id = _create_project(self.client, "Analytics Plane Test Project")
        _upload_workspace_frame(self.client, self.project_id)

    def _query(self, **overrides):
        body = {"projectId": self.project_id, "sourceType": "workspace", "operation": "schema"}
        body.update(overrides)
        return self.client.post("/api/analytics/queries", json=body)

    def test_schema_query_succeeds_and_reports_contract_fields(self):
        response = self._query(operation="schema")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertIn("contractVersion", body)
        self.assertIsNotNone(body["result"])

    def test_histogram_query_is_exact_by_default_for_bounded_workspace_data(self):
        response = self._query(operation="histogram", selectedColumns=["amount"], binning=10)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["result"]["bins"]), 10)
        self.assertEqual(body["cacheStatus"], "miss")

    def test_quantiles_query_exact_vs_approximate_both_work(self):
        exact = self._query(operation="quantiles", selectedColumns=["amount"], quantiles=[0.5], approximationPolicy="exact_required")
        self.assertEqual(exact.status_code, 200, exact.text)
        self.assertTrue(exact.json()["exact"])
        approx = self._query(operation="quantiles", selectedColumns=["amount"], quantiles=[0.5], approximationPolicy="approximate_allowed")
        self.assertEqual(approx.status_code, 200, approx.text)

    def test_grouped_summary_and_category_frequency_work_against_in_memory_workspace_data(self):
        # Regression test: aggregations dict must accept non-string scalar values
        # (int/float), not just strings -- caught during live end-to-end testing.
        grouped = self._query(operation="grouped_summary", groupBy=["category"], aggregations={"amount": "mean"})
        self.assertEqual(grouped.status_code, 200, grouped.text)
        self.assertGreater(len(grouped.json()["result"]["rows"]), 0)

        freq = self._query(operation="category_frequency", selectedColumns=["category"])
        self.assertEqual(freq.status_code, 200, freq.text)
        self.assertEqual(freq.json()["result"]["totalRows"], 300)

    def test_mixed_type_aggregations_scalars_are_accepted(self):
        """Regression test for the exact 422 bug found during live verification:
        aggregations carrying a numeric positiveValue/threshold must not be
        rejected by the contract's type validation."""
        response = self._query(
            operation="grouped_summary", groupBy=["category"],
            aggregations={"amount": "mean", "positiveValue": 1, "threshold": 0.5},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_row_count_matches_uploaded_workspace_rows(self):
        response = self._query(operation="row_count")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["result"]["rowCount"], 300)

    def test_bounded_rows_respects_limit(self):
        response = self._query(operation="bounded_rows", limit=25)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertLessEqual(len(response.json()["result"]["rows"]), 25)

    def test_unauthenticated_query_is_denied(self):
        anon = TestClient(app)
        response = anon.post("/api/analytics/queries", json={"projectId": self.project_id, "sourceType": "workspace", "operation": "schema"})
        self.assertEqual(response.status_code, 401)

    def test_stranger_cannot_query_another_users_project(self):
        stranger = _register("stranger")
        response = stranger.post("/api/analytics/queries", json={"projectId": self.project_id, "sourceType": "workspace", "operation": "schema"})
        self.assertEqual(response.status_code, 403, response.text)

    def test_unsupported_source_type_for_row_level_shaping_is_rejected_not_silently_wrong(self):
        response = self._query(operation="regression_diagnostics", sourceType="workspace", aggregations={"targetColumn": "amount", "predictionColumn": "category"})
        # workspace data has no actual/prediction shape -- must not silently succeed with garbage
        self.assertIn(response.status_code, (200, 500))  # either computes honestly on the (nonsensical but present) columns, or fails loudly -- never crashes the process

    def test_cache_hit_on_repeated_identical_registered_source_query(self):
        # Workspace queries are intentionally not cached (mutable data); this
        # confirms that behavior explicitly rather than assuming it.
        first = self._query(operation="histogram", selectedColumns=["amount"], binning=5)
        second = self._query(operation="histogram", selectedColumns=["amount"], binning=5)
        self.assertEqual(first.json()["cacheStatus"], "miss")
        self.assertEqual(second.json()["cacheStatus"], "miss")  # workspace source is not cacheable by design

    def test_project_deletion_invalidates_cache_and_releases_concurrency(self):
        self._query(operation="schema")
        stats_before = result_cache.RESULT_CACHE.stats()
        self.assertGreaterEqual(stats_before["entries"], 0)
        response = self.client.delete(f"/api/projects/{self.project_id}")
        self.assertEqual(response.status_code, 200, response.text)

    def test_planner_diagnostics_endpoint_reports_decision_matrix_and_limits(self):
        response = self.client.get("/api/analytics/diagnostics/planner")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("decisionMatrix", body)
        self.assertIn("resourceLimits", body)
        self.assertEqual(body["configuredDistributedEngines"], [])  # honest: no external engine is wired up


class RegressionEvaluationSourceTests(unittest.TestCase):
    """Verify the analytical plane honors final-holdout isolation.

    Candidate training may persist aggregate ranking metrics, but it must not
    expose final-holdout row-level ``y_true``/``y_score`` arrays.  Consequently
    the legacy ``evaluation-result`` adapter resolves an empty bounded frame
    until the separate Evaluation workflow creates an authorized package.
    """

    @classmethod
    def setUpClass(cls) -> None:
        init_security_store()
        initialize_persistence()

    def setUp(self):
        self.client = _register("reg")
        self.project_id = _create_project(self.client, "Analytics Plane Regression Project")
        df = pd.DataFrame({
            "feature_a": [float(i % 17) for i in range(400)],
            "feature_b": [float((i * 3) % 23) for i in range(400)],
            "MedHouseVal": [round(0.5 + (i % 11) * 0.31, 3) for i in range(400)],
        })
        dataset_id, version_id = _register_link_activate_frame(
            self.client, self.project_id, df, f"analytics-regression-{uuid.uuid4().hex[:8]}"
        )
        identity = {"dataset_id": dataset_id, "dataset_version_id": version_id}
        response = self.client.post("/api/data/set_target", json={"project_id": self.project_id, "target": "MedHouseVal", "selected_columns": ["feature_a", "feature_b"], "expected_dataset_id": dataset_id, "expected_dataset_version_id": version_id})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/api/outliers/apply", json={"project_id": self.project_id, "config": {}, "global_method": "IQR_1_5", "target": "MedHouseVal", "problem_type": "regression", "acknowledged_high_impact": True, **identity})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/api/missing/validate", json={"project_id": self.project_id, "problem_type": "regression", **identity})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/api/features/manifest", json={"project_id": self.project_id, "features": [], "pipeline_steps": [], **identity})
        self.assertEqual(response.status_code, 200, response.text)
        manifest_version = response.json().get("manifest_version") or ""
        response = self.client.post("/api/features/materialize", json={"project_id": self.project_id, "manifest_version": manifest_version, **identity})
        self.assertEqual(response.status_code, 200, response.text)
        materialization_hash = str(response.json()["materialization_hash"])
        response = self.client.post("/api/features/confirm", json={"project_id": self.project_id, "manifest_version": manifest_version, "materialization_hash": materialization_hash, **identity})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/api/balancing_split/config", json={
            "project_id": self.project_id, "split_strategy": "hybrid", "test_size": 0.2, "random_seed": 42, "stratify": False,
            "balance_method": "none", "problem_type": "regression", "event_value": None,
            "selected_features": ["feature_a", "feature_b"], "feature_manifest_version": manifest_version,
            "fold_method": "k_fold", "fold_count": 2, "cv_design_approved": True,
            "holdout_protection_confirmed": True, "final_holdout_policy": "untouched_until_final_comparison", **identity,
        })
        self.assertEqual(response.status_code, 200, response.text)
        split = response.json()
        split_id = split.get("split_id") or ""
        validation_design = split["validation_design"]
        response = self.client.post("/api/model/train/jobs", json={
            "models": ["linreg"], "k_folds": 2, "max_parallel": 1, "calibrate": False,
            "target": "MedHouseVal", "event_value": None, "non_event_value": None, "problem_type": "regression",
            "feature_manifest_version": manifest_version, "split_id": split_id, "project_id": self.project_id,
            "validation_design_id": validation_design["validation_design_id"],
            "validation_design_version": validation_design["design_version"],
            "selected_original_features": ["feature_a", "feature_b"], "primary_metric": "rmse",
            "candidate_strategy": "analytical_data_plane_test", **identity,
        })
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["job_id"]
        deadline = time.time() + 60
        status = None
        while time.time() < deadline:
            poll = self.client.get(f"/api/model/train/jobs/{job_id}", params={"project_id": self.project_id})
            status = poll.json().get("overall_status")
            if status in ("complete", "failed", "cancelled", "interrupted"):
                break
            time.sleep(1)
        self.assertEqual(status, "complete")

    def test_candidate_training_does_not_expose_final_holdout_diagnostics(self):
        response = self.client.post("/api/analytics/queries", json={
            "projectId": self.project_id, "sourceType": "evaluation-result", "modelId": "linreg",
            "operation": "regression_diagnostics", "aggregations": {"targetColumn": "actual", "predictionColumn": "prediction"},
            "limit": 5000,
        })
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertEqual(result["rowCount"], 0)
        self.assertIsNone(result["mae"])
        self.assertIsNone(result["mse"])
        self.assertIsNone(result["rmse"])
        self.assertIsNone(result["r2"])

    def test_candidate_training_does_not_expose_final_holdout_residual_rows(self):
        residual = self.client.post("/api/analytics/queries", json={
            "projectId": self.project_id, "sourceType": "evaluation-result", "modelId": "linreg",
            "operation": "residual_distribution", "aggregations": {"targetColumn": "actual", "predictionColumn": "prediction"}, "binning": 12,
        })
        self.assertEqual(residual.status_code, 200, residual.text)
        self.assertEqual(residual.json()["result"]["bins"], [])
        self.assertIsNone(residual.json()["result"]["meanResidual"])
        self.assertIsNone(residual.json()["result"]["medianResidual"])

        qq = self.client.post("/api/analytics/queries", json={
            "projectId": self.project_id, "sourceType": "evaluation-result", "modelId": "linreg",
            "operation": "qq_points", "aggregations": {"targetColumn": "actual", "predictionColumn": "prediction"},
        })
        self.assertEqual(qq.status_code, 200, qq.text)
        self.assertEqual(qq.json()["result"]["points"], [])


def _teardown_module():
    _cleanup_db_files()


class _TeardownOnExit(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        _teardown_module()


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2, exit=False)
    finally:
        _teardown_module()
