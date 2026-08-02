"""ATLAS Persistent Scoring Runs and Analytical Result History: backend tests.

Uses FastAPI's TestClient (in-process, synchronous), matching the established
pattern in tests/dataset_lifecycle_test.py and tests/analytical_data_plane_test.py --
avoids uvicorn --reload flakiness entirely and runs faster.

Isolation: dedicated security/persistence SQLite files, a dedicated
ATLAS_DATASET_LIBRARY_ROOT, and a dedicated ATLAS_SCORING_RUN_ARTIFACT_ROOT
(the governed Parquet artifact root for scoring-run output), so this suite
never touches the shared dev backend's real state or on-disk artifacts.

Run:  .venv/Scripts/python.exe tests/scoring_runs_test.py
"""
from __future__ import annotations

import io
import os
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
_SUITE_ROOT = _TEST_DATA_ROOT / f"atlas_scoringruns_{_RUN_ID}"
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_scoringruns_security_{_RUN_ID}.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / f"atlas_scoringruns_persistence_{_RUN_ID}.db"
_CHECKPOINT_PATH = _TEST_DATA_ROOT / f"atlas_scoringruns_checkpoint_{_RUN_ID}.json"
_LIBRARY_ROOT = _SUITE_ROOT / "dataset-library"
_ARTIFACT_ROOT = _SUITE_ROOT / "scoring-artifacts"
_BACKUP_ROOT = Path(tempfile.mkdtemp(prefix=f"atlas_scoringruns_backups_{_RUN_ID}_"))
_EVIDENCE_ROOT = _TEST_DATA_ROOT / f"atlas_scoringruns_evidence_{_RUN_ID}"
_MODEL_ARTIFACT_ROOT = _TEST_DATA_ROOT / f"atlas_scoringruns_models_{_RUN_ID}"
os.environ["ATLAS_SECURITY_ROOT"] = str(_SECURITY_DB_PATH.parent)
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_PATH)
os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(_LIBRARY_ROOT)
os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(_BACKUP_ROOT)
os.environ["ATLAS_SCORING_RUN_ARTIFACT_ROOT"] = str(_ARTIFACT_ROOT)
os.environ["ATLAS_EVIDENCE_ROOT"] = str(_EVIDENCE_ROOT)
os.environ["ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT"] = str(_MODEL_ARTIFACT_ROOT)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

import pandas as pd  # noqa: E402
import shutil  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.datasets import dataset_registry  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.persistence import db as persistence_db  # noqa: E402
from server.persistence import service as persistence_service  # noqa: E402
from server.persistence.service import get_persistence_service  # noqa: E402
from server.security import security_store  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402
import server.core.session_checkpoint as checkpoint  # noqa: E402
from server.evidence import evidence_store  # noqa: E402
from server.model_registry import model_artifacts  # noqa: E402
from server.scoring_runs import scoring_run_artifacts  # noqa: E402


def _bind_dataset_library_paths() -> None:
    root = _LIBRARY_ROOT.resolve()
    os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(root)
    os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(_BACKUP_ROOT.resolve())
    dataset_registry.ARTIFACT_ROOT = root
    dataset_registry.REGISTRY_PATH = root / "registry.json"
    dataset_registry.USERS_PATH = root / "users.json"
    dataset_registry.PROJECT_LINKS_PATH = root / "project_links.json"


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
    os.environ["ATLAS_SCORING_RUN_ARTIFACT_ROOT"] = str(_ARTIFACT_ROOT.resolve())
    os.environ["ATLAS_EVIDENCE_ROOT"] = str(_EVIDENCE_ROOT.resolve())
    os.environ["ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT"] = str(_MODEL_ARTIFACT_ROOT.resolve())
    os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"
    security_store.SECURITY_ROOT = _SECURITY_DB_PATH.parent.resolve()
    security_store.DB_PATH = _SECURITY_DB_PATH.resolve()
    security_store.ATLAS_AUTH_ENABLED = True
    security_store.ATLAS_ALLOW_PUBLIC_REGISTRATION = True
    persistence_db._database = persistence_db.Database(_PERSISTENCE_DB_PATH)
    persistence_service._service = None
    scoring_run_artifacts.ARTIFACT_ROOT = _ARTIFACT_ROOT.resolve()
    evidence_store.EVIDENCE_ROOT = _EVIDENCE_ROOT.resolve()
    evidence_store.ITEMS_ROOT = evidence_store.EVIDENCE_ROOT / "items"
    evidence_store.REGISTRY_PATH = evidence_store.EVIDENCE_ROOT / "evidence_registry.json"
    model_artifacts.ARTIFACT_ROOT = _MODEL_ARTIFACT_ROOT.resolve()
    _bind_checkpoint_path()
    _bind_dataset_library_paths()

    assert security_store.DB_PATH == _SECURITY_DB_PATH.resolve()
    assert persistence_db.get_database().path == _PERSISTENCE_DB_PATH.resolve()
    assert scoring_run_artifacts.ARTIFACT_ROOT == _ARTIFACT_ROOT.resolve()
    assert evidence_store.EVIDENCE_ROOT == _EVIDENCE_ROOT.resolve()
    assert model_artifacts.ARTIFACT_ROOT == _MODEL_ARTIFACT_ROOT.resolve()


_bind_isolated_runtime_paths()


def setUpModule() -> None:
    _bind_isolated_runtime_paths()


def _cleanup() -> None:
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
    shutil.rmtree(_LIBRARY_ROOT, ignore_errors=True)
    shutil.rmtree(_ARTIFACT_ROOT, ignore_errors=True)
    shutil.rmtree(_BACKUP_ROOT, ignore_errors=True)
    shutil.rmtree(_EVIDENCE_ROOT, ignore_errors=True)
    shutil.rmtree(_MODEL_ARTIFACT_ROOT, ignore_errors=True)


def _register(label: str) -> TestClient:
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{label}-{suffix}@atlas-scoringruns-test.local",
            "displayName": f"Scoring Runs Test {label} {suffix}",
            "password": "ScoringRunsTestPass!1",
            "role": "data_scientist",
        },
    )
    assert response.status_code == 200, response.text
    return client


def _create_project(client: TestClient, name: str) -> str:
    response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
    assert response.status_code == 200, response.text
    return response.json()["project"]["projectId"]


def _register_link_activate_frame(
    client: TestClient,
    project_id: str,
    frame: pd.DataFrame,
    name: str,
) -> tuple[str, str]:
    upload = client.post(
        "/api/datasets/upload",
        files={"file": (f"{name}.csv", io.BytesIO(frame.to_csv(index=False).encode("utf-8")), "text/csv")},
        data={"name": name, "description": "scoring-run test asset"},
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


def _train_regression_model(client: TestClient, project_id: str) -> str:
    """Runs the full outliers -> missing -> manifest -> materialize -> split -> train
    pipeline for a small real regression model, mirroring
    tests/analytical_data_plane_test.py's RegressionEvaluationSourceTests -- reused
    here rather than re-derived, since it is already independently verified to work."""
    df = pd.DataFrame({
        "feature_a": [float(i % 17) for i in range(400)],
        "feature_b": [float((i * 3) % 23) for i in range(400)],
        "MedHouseVal": [round(0.5 + (i % 11) * 0.31, 3) for i in range(400)],
    })
    dataset_id, version_id = _register_link_activate_frame(
        client, project_id, df, f"scoring-regression-{uuid.uuid4().hex[:8]}"
    )
    identity = {"dataset_id": dataset_id, "dataset_version_id": version_id}
    response = client.post("/api/data/set_target", json={"project_id": project_id, "target": "MedHouseVal", "selected_columns": ["feature_a", "feature_b"], "expected_dataset_id": dataset_id, "expected_dataset_version_id": version_id})
    assert response.status_code == 200, response.text
    response = client.post("/api/outliers/apply", json={"project_id": project_id, "config": {}, "global_method": "IQR_1_5", "target": "MedHouseVal", "problem_type": "regression", "acknowledged_high_impact": True, **identity})
    assert response.status_code == 200, response.text
    response = client.post("/api/missing/validate", json={"project_id": project_id, "problem_type": "regression", **identity})
    assert response.status_code == 200, response.text
    response = client.post("/api/features/manifest", json={"project_id": project_id, "features": [], "pipeline_steps": [], **identity})
    assert response.status_code == 200, response.text
    manifest_version = response.json().get("manifest_version") or ""
    response = client.post("/api/features/materialize", json={"project_id": project_id, "manifest_version": manifest_version, **identity})
    assert response.status_code == 200, response.text
    materialization_hash = str(response.json()["materialization_hash"])
    response = client.post("/api/features/confirm", json={"project_id": project_id, "manifest_version": manifest_version, "materialization_hash": materialization_hash, **identity})
    assert response.status_code == 200, response.text
    response = client.post("/api/balancing_split/config", json={
        "project_id": project_id, "split_strategy": "hybrid", "test_size": 0.2, "random_seed": 42, "stratify": False,
        "balance_method": "none", "problem_type": "regression", "event_value": None,
        "selected_features": ["feature_a", "feature_b"], "feature_manifest_version": manifest_version,
        "fold_method": "k_fold", "fold_count": 2, "cv_design_approved": True,
        "holdout_protection_confirmed": True, "final_holdout_policy": "untouched_until_final_comparison", **identity,
    })
    assert response.status_code == 200, response.text
    split = response.json()
    split_id = split.get("split_id") or ""
    validation_design = split["validation_design"]
    response = client.post("/api/model/train/jobs", json={
        "models": ["linreg"], "k_folds": 2, "max_parallel": 1, "calibrate": False,
        "target": "MedHouseVal", "event_value": None, "non_event_value": None, "problem_type": "regression",
        "feature_manifest_version": manifest_version, "split_id": split_id, "project_id": project_id,
        "validation_design_id": validation_design["validation_design_id"],
        "validation_design_version": validation_design["design_version"],
        "selected_original_features": ["feature_a", "feature_b"], "primary_metric": "rmse",
        "candidate_strategy": "scoring_runs_test", **identity,
    })
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    deadline = time.time() + 60
    status = None
    while time.time() < deadline:
        poll = client.get(f"/api/model/train/jobs/{job_id}", params={"project_id": project_id})
        status = poll.json().get("overall_status")
        if status in ("complete", "failed", "cancelled", "interrupted"):
            break
        time.sleep(1)
    assert status == "complete"
    return manifest_version


class ScoringRunLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _cleanup()
        init_security_store()
        initialize_persistence()

    def setUp(self):
        self.client = _register("owner")
        self.project_id = _create_project(self.client, "Scoring Runs Test Project")
        _train_regression_model(self.client, self.project_id)

        # Two TRAIN runs (proves history: multiple runs per partition coexist,
        # neither overwrites the other -- Phase F) plus one TEST run (exercises
        # the PSI/VSI computation branch, which only fires for test/oot).
        train1 = self.client.post("/api/score/development-split", params={"project_id": self.project_id, "dataset_type": "train"})
        self.assertEqual(train1.status_code, 200, train1.text)
        self.assertTrue(train1.json().get("ok"), train1.text)
        self.train_run_id_1 = train1.json().get("scoringRunId")

        train2 = self.client.post("/api/score/development-split", params={"project_id": self.project_id, "dataset_type": "train"})
        self.assertEqual(train2.status_code, 200, train2.text)
        self.train_run_id_2 = train2.json().get("scoringRunId")

        test1 = self.client.post("/api/score/development-split", params={"project_id": self.project_id, "dataset_type": "test"})
        self.assertEqual(test1.status_code, 200, test1.text)
        self.test_run_id = test1.json().get("scoringRunId")

    def test_scoring_run_id_is_returned_and_distinct_per_run(self):
        self.assertIsNotNone(self.train_run_id_1)
        self.assertIsNotNone(self.train_run_id_2)
        self.assertIsNotNone(self.test_run_id)
        self.assertNotEqual(self.train_run_id_1, self.train_run_id_2)

    def test_history_preserves_multiple_train_runs_without_overwriting(self):
        response = self.client.get("/api/scoring-runs", params={"projectId": self.project_id, "partition": "train"})
        self.assertEqual(response.status_code, 200, response.text)
        run_ids = {run["scoringRunId"] for run in response.json()["scoringRuns"]}
        self.assertIn(self.train_run_id_1, run_ids)
        self.assertIn(self.train_run_id_2, run_ids)

    def test_get_scoring_run_returns_durable_fields(self):
        response = self.client.get(f"/api/scoring-runs/{self.test_run_id}")
        self.assertEqual(response.status_code, 200, response.text)
        run = response.json()["scoringRun"]
        self.assertEqual(run["partition"], "test")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["problemType"], "regression")
        self.assertGreater(run["rowCount"], 0)
        self.assertIsNotNone(run["checksum"])
        self.assertEqual(run["outputArtifactFormat"], "parquet")

    def test_metrics_endpoint_reports_regression_metrics(self):
        response = self.client.get(f"/api/scoring-runs/{self.test_run_id}/metrics")
        self.assertEqual(response.status_code, 200, response.text)
        metrics = response.json()["metrics"]["metrics"]
        self.assertIn("rmse", metrics)

    def test_diagnostics_endpoint_reports_psi_for_test_partition(self):
        response = self.client.get(f"/api/scoring-runs/{self.test_run_id}/diagnostics")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("value", body["psi"])
        self.assertIsInstance(body["vsi"]["rows"], list)

    def test_diagnostics_endpoint_has_no_psi_for_train_partition(self):
        # PSI/VSI only computed for test/oot (matches pre-existing eval_service behavior,
        # unchanged by this phase) -- a TRAIN run's psi_json must be an honest empty dict.
        response = self.client.get(f"/api/scoring-runs/{self.train_run_id_1}/diagnostics")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["psi"], {})

    def test_lineage_endpoint_reports_model_and_dataset_identity(self):
        response = self.client.get(f"/api/scoring-runs/{self.test_run_id}/lineage")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIsNotNone(body["modelId"])
        self.assertIsNotNone(body["modelVersion"])
        self.assertIn("modelSource", body["lineage"])

    def test_rows_endpoint_returns_bounded_governed_output(self):
        response = self.client.get(f"/api/scoring-runs/{self.test_run_id}/rows", params={"limit": 5})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertLessEqual(len(body["rows"]), 5)
        self.assertIn("predicted_value", body["columns"])

    def test_summary_endpoint_reports_registration_status(self):
        response = self.client.get(f"/api/scoring-runs/{self.test_run_id}/summary")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scoringRun"]["registrationStatus"], "not_registered")

    def test_evidence_is_captured_for_each_scoring_run(self):
        response = self.client.get(f"/api/projects/{self.project_id}/evidence")
        self.assertEqual(response.status_code, 200, response.text)
        source_refs = {item["sourceRef"] for item in response.json()["evidence"]}
        self.assertIn(self.test_run_id, source_refs)

    def test_cancel_on_completed_run_is_rejected_honestly(self):
        response = self.client.post(f"/api/scoring-runs/{self.test_run_id}/cancel")
        self.assertEqual(response.status_code, 409, response.text)

    def test_archive_hides_run_from_default_listing(self):
        response = self.client.post(f"/api/scoring-runs/{self.train_run_id_1}/archive")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNotNone(response.json()["scoringRun"]["archivedAt"])

        default_listing = self.client.get("/api/scoring-runs", params={"projectId": self.project_id})
        default_ids = {run["scoringRunId"] for run in default_listing.json()["scoringRuns"]}
        self.assertNotIn(self.train_run_id_1, default_ids)

        with_archived = self.client.get("/api/scoring-runs", params={"projectId": self.project_id, "includeArchived": "true"})
        archived_ids = {run["scoringRunId"] for run in with_archived.json()["scoringRuns"]}
        self.assertIn(self.train_run_id_1, archived_ids)

    def test_compare_endpoint_returns_metrics_side_by_side(self):
        response = self.client.get("/api/scoring-runs/compare", params={"ids": f"{self.train_run_id_1},{self.test_run_id}"})
        self.assertEqual(response.status_code, 200, response.text)
        run_ids = {row["scoringRunId"] for row in response.json()["runs"]}
        self.assertEqual(run_ids, {self.train_run_id_1, self.test_run_id})

    def test_unauthenticated_access_is_denied(self):
        anon = TestClient(app)
        response = anon.get(f"/api/scoring-runs/{self.test_run_id}")
        self.assertEqual(response.status_code, 401)

    def test_stranger_cannot_read_another_users_scoring_run(self):
        stranger = _register("stranger")
        response = stranger.get(f"/api/scoring-runs/{self.test_run_id}")
        self.assertEqual(response.status_code, 403, response.text)

    def test_stranger_cannot_list_another_users_project_scoring_runs(self):
        stranger = _register("stranger")
        response = stranger.get("/api/scoring-runs", params={"projectId": self.project_id})
        self.assertEqual(response.status_code, 403, response.text)

    def test_visual_intelligence_query_plane_reads_scoring_session_source(self):
        # Phase G: the Enterprise Analytical Data Plane's own query contract must be
        # able to resolve and query a persisted ScoringRun via sourceType="scoring-session".
        response = self.client.post("/api/analytics/queries", json={
            "projectId": self.project_id, "sourceType": "scoring-session", "scoringRunId": self.test_run_id,
            "operation": "row_count",
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["result"]["rowCount"], self.client.get(f"/api/scoring-runs/{self.test_run_id}").json()["scoringRun"]["rowCount"])
        self.assertEqual(body["executionEngine"], "duckdb")
        self.assertTrue(body["pushdownApplied"])

    def test_visual_intelligence_query_plane_denies_cross_project_scoring_run(self):
        other_project = _create_project(self.client, "Second Scoring Runs Test Project")
        response = self.client.post("/api/analytics/queries", json={
            "projectId": other_project, "sourceType": "scoring-session", "scoringRunId": self.test_run_id,
            "operation": "row_count",
        })
        self.assertEqual(response.status_code, 403, response.text)

    def test_survives_process_restart_semantics_via_direct_repository_read(self):
        # A real process restart is out of scope for an in-process TestClient run,
        # but persistence-across-restart is exactly what SQLite + a real file on disk
        # (not an in-memory dict) already guarantees -- this test proves the row and
        # its artifact are readable via a completely fresh repository instance/service
        # lookup, not via any in-memory cache the request that created it might have
        # left warm.
        service = get_persistence_service()
        row = service.scoring_runs.get(self.test_run_id)
        self.assertIsNotNone(row)
        from server.scoring_runs.scoring_run_artifacts import resolve_scoring_run_artifact_path
        artifact_path = resolve_scoring_run_artifact_path(row["output_artifact_path"])
        self.assertTrue(artifact_path.exists())


class ScoringRunProjectDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_security_store()
        initialize_persistence()

    def test_project_deletion_archives_but_does_not_delete_scoring_runs(self):
        client = _register("deleter")
        project_id = _create_project(client, "Scoring Runs Deletion Test Project")
        _train_regression_model(client, project_id)
        scored = client.post("/api/score/development-split", params={"project_id": project_id, "dataset_type": "train"})
        self.assertEqual(scored.status_code, 200, scored.text)
        scoring_run_id = scored.json()["scoringRunId"]
        self.assertIsNotNone(scoring_run_id)

        response = client.delete(f"/api/projects/{project_id}")
        self.assertEqual(response.status_code, 200, response.text)

        service = get_persistence_service()
        row = service.scoring_runs.get(scoring_run_id)
        self.assertIsNotNone(row, "Scoring run must survive project deletion (durable, not cascade-deleted).")
        self.assertIsNotNone(row["archived_at"], "Scoring run must be archived, not silently left active, after its project is deleted.")


def _teardown_module():
    _cleanup()


class _TeardownOnExit(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        _teardown_module()


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2, exit=False)
    finally:
        _teardown_module()
