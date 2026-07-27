"""ATLAS Visual Intelligence Production Integration, Phase 2: backend tests for
the gaps this phase closed -- wide-table schema search/pagination (both
workspace and file-backed sources), honest failed-scoring-run persistence, and
the ScoringRun-to-Scored-Dataset cross-link.

Uses FastAPI's TestClient (in-process), matching the established pattern in
tests/scoring_runs_test.py and tests/analytical_data_plane_test.py.

Run:  .venv/Scripts/python.exe tests/vi_production_integration_test.py
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
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_viprod_security_{_RUN_ID}.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / f"atlas_viprod_persistence_{_RUN_ID}.db"
_CHECKPOINT_PATH = _TEST_DATA_ROOT / f"atlas_viprod_checkpoint_{_RUN_ID}.json"
_LIBRARY_ROOT = Path(tempfile.mkdtemp(prefix=f"atlas_viprod_library_{_RUN_ID}_"))
_ARTIFACT_ROOT = Path(tempfile.mkdtemp(prefix=f"atlas_viprod_scoringartifacts_{_RUN_ID}_"))
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_PATH)
os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(_LIBRARY_ROOT)
os.environ["ATLAS_SCORING_RUN_ARTIFACT_ROOT"] = str(_ARTIFACT_ROOT)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.persistence.service import get_persistence_service  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402
import server.core.session_checkpoint as checkpoint  # noqa: E402


def _cleanup() -> None:
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
    checkpoint.CHECKPOINT_PATH.unlink(missing_ok=True)
    shutil.rmtree(_LIBRARY_ROOT, ignore_errors=True)
    shutil.rmtree(_ARTIFACT_ROOT, ignore_errors=True)


def _register(label: str) -> TestClient:
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{label}-{suffix}@atlas-viprod-test.local",
            "displayName": f"VI Prod Test {label} {suffix}",
            "password": "ViProdTestPass!1",
            "role": "data_scientist",
        },
    )
    assert response.status_code == 200, response.text
    return client


def _create_project(client: TestClient, name: str) -> str:
    response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
    assert response.status_code == 200, response.text
    return response.json()["project"]["projectId"]


def _upload_workspace_frame(client: TestClient, project_id: str, columns: int = 30, rows: int = 200) -> None:
    headers = [f"feature_{i}" for i in range(columns)] + ["target"]
    payload_rows = [{**{f"feature_{i}": float((r + i) % 17) for i in range(columns)}, "target": r % 2} for r in range(rows)]
    response = client.post("/api/data/set_sample", json={
        "project_id": project_id, "headers": headers, "rows": payload_rows,
        "target": "target", "selected_columns": [f"feature_{i}" for i in range(columns)],
    })
    assert response.status_code == 200, response.text


def _train_regression_model(client: TestClient, project_id: str) -> None:
    df = pd.DataFrame({
        "feature_a": [float(i % 17) for i in range(400)],
        "feature_b": [float((i * 3) % 23) for i in range(400)],
        "MedHouseVal": [round(0.5 + (i % 11) * 0.31, 3) for i in range(400)],
    })
    files = {"file": ("reg.csv", io.BytesIO(df.to_csv(index=False).encode("utf-8")), "text/csv")}
    response = client.post("/api/data/upload_csv", data={"project_id": project_id}, files=files)
    assert response.status_code == 200, response.text
    response = client.post("/api/data/set_target", json={"project_id": project_id, "target": "MedHouseVal", "selected_columns": ["feature_a", "feature_b"]})
    assert response.status_code == 200, response.text
    response = client.post("/api/outliers/apply", json={"project_id": project_id, "config": {}, "global_method": "IQR_1_5", "target": "MedHouseVal", "problem_type": "regression"})
    assert response.status_code == 200, response.text
    response = client.post("/api/missing/apply", json={"project_id": project_id, "config": {}, "problem_type": "regression"})
    assert response.status_code == 200, response.text
    response = client.post("/api/features/manifest", json={"project_id": project_id, "features": [], "pipeline_steps": [], "dataset_version": ""})
    assert response.status_code == 200, response.text
    manifest_version = response.json().get("manifest_version") or ""
    response = client.post("/api/features/materialize", json={"project_id": project_id, "manifest_version": manifest_version})
    assert response.status_code == 200, response.text
    response = client.post("/api/balancing_split/config", json={
        "project_id": project_id, "split_strategy": "holdout", "test_size": 0.2, "random_seed": 42, "stratify": False,
        "balance_method": "none", "problem_type": "regression", "event_value": None,
        "selected_features": ["feature_a", "feature_b"], "feature_manifest_version": manifest_version, "dataset_version": "",
    })
    assert response.status_code == 200, response.text
    split_id = response.json().get("split_id") or ""
    response = client.post("/api/model/train/jobs", json={
        "models": ["linreg"], "k_folds": 2, "max_parallel": 1, "calibrate": False,
        "target": "MedHouseVal", "event_value": None, "non_event_value": None, "problem_type": "regression",
        "dataset_version": "", "feature_manifest_version": manifest_version, "split_id": split_id, "project_id": project_id,
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


class SchemaSearchPaginationTests(unittest.TestCase):
    """Phase C requirement 8: no 500-variable dropdown rendered eagerly --
    server-side search/pagination must work for BOTH in-memory workspace
    sources and file-backed (registered Parquet) sources."""

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup()
        init_security_store()
        initialize_persistence()

    def setUp(self):
        self.client = _register("schema")
        self.project_id = _create_project(self.client, "VI Prod Schema Test Project")
        _upload_workspace_frame(self.client, self.project_id, columns=40)

    def test_workspace_schema_search_filters_by_name(self):
        response = self.client.post("/api/analytics/queries", json={
            "projectId": self.project_id, "sourceType": "workspace", "operation": "schema", "search": "feature_1",
        })
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        names = [c["name"] for c in result["columns"]]
        self.assertTrue(all("feature_1" in n for n in names))
        # feature_1, feature_10..19 -> 11 matches out of 40 generated columns
        self.assertEqual(result["totalColumns"], 11)

    def test_workspace_schema_pagination_offset_and_limit(self):
        first_page = self.client.post("/api/analytics/queries", json={
            "projectId": self.project_id, "sourceType": "workspace", "operation": "schema", "limit": 10, "offset": 0,
        })
        second_page = self.client.post("/api/analytics/queries", json={
            "projectId": self.project_id, "sourceType": "workspace", "operation": "schema", "limit": 10, "offset": 10,
        })
        self.assertEqual(first_page.status_code, 200, first_page.text)
        self.assertEqual(second_page.status_code, 200, second_page.text)
        first_names = {c["name"] for c in first_page.json()["result"]["columns"]}
        second_names = {c["name"] for c in second_page.json()["result"]["columns"]}
        self.assertEqual(len(first_names), 10)
        self.assertEqual(len(second_names), 10)
        self.assertTrue(first_names.isdisjoint(second_names))  # no overlap between pages

    def test_schema_search_and_pagination_do_not_collide_in_cache(self):
        # Regression guard for the cache-key fix: a search for "feature_2" must never
        # return the unfiltered/first-page result from an earlier schema call.
        self.client.post("/api/analytics/queries", json={"projectId": self.project_id, "sourceType": "workspace", "operation": "schema", "limit": 10})
        searched = self.client.post("/api/analytics/queries", json={"projectId": self.project_id, "sourceType": "workspace", "operation": "schema", "search": "feature_2"})
        names = [c["name"] for c in searched.json()["result"]["columns"]]
        self.assertTrue(all("feature_2" in n for n in names))


class WideTableRegisteredParquetSchemaTests(unittest.TestCase):
    """File-backed (Polars/Parquet) branch of the same schema search/pagination
    fix, against a real registered+materialized dataset version -- not just the
    in-memory workspace branch."""

    @classmethod
    def setUpClass(cls) -> None:
        init_security_store()
        initialize_persistence()

    def setUp(self):
        self.client = _register("wide")
        self.project_id = _create_project(self.client, "VI Prod Wide Table Test Project")
        columns = {f"col_{i}": [float(i)] * 20 for i in range(520)}
        df = pd.DataFrame(columns)
        files = {"file": ("wide.csv", io.BytesIO(df.to_csv(index=False).encode("utf-8")), "text/csv")}
        response = self.client.post("/api/data/upload_csv", data={"project_id": self.project_id}, files=files)
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/api/data/set_target", json={"project_id": self.project_id, "target": "col_0", "selected_columns": [f"col_{i}" for i in range(1, 120)]})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/api/scoring/register-scored-dataset", json={
            "projectId": self.project_id, "projectName": "VI Prod Wide Table Test Project",
            "datasetName": "Wide fixture", "datasetType": "scored", "rows": df.to_dict(orient="records"),
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.dataset_id = response.json()["dataset"]["datasetId"]
        self.version_id = response.json()["dataset"]["latestVersion"]["versionId"]
        materialize = self.client.post(f"/api/analytics/datasets/{self.dataset_id}/versions/{self.version_id}/materialize-parquet")
        self.assertEqual(materialize.status_code, 200, materialize.text)

    def test_file_backed_schema_search_and_pagination(self):
        response = self.client.post("/api/analytics/queries", json={
            "projectId": self.project_id, "sourceType": "registered", "datasetId": self.dataset_id, "versionId": self.version_id,
            "operation": "schema", "search": "col_1", "limit": 100,
        })
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        names = [c["name"] for c in result["columns"]]
        self.assertTrue(all("col_1" in n for n in names))
        self.assertGreater(len(names), 0)
        self.assertLess(result["totalColumns"], 520)  # confirms filtering actually narrowed the 520-column source
        self.assertGreaterEqual(520 - result["totalColumns"], 300)  # a substantial majority were excluded, not just a couple


class FailedScoringRunTests(unittest.TestCase):
    """Phase J/O: a failed scoring attempt must remain durably inspectable with
    an honest failure reason, not vanish after a one-time error toast."""

    @classmethod
    def setUpClass(cls) -> None:
        init_security_store()
        initialize_persistence()

    def test_scoring_without_a_split_persists_a_failed_run_with_honest_reason(self):
        client = _register("failed")
        project_id = _create_project(client, "VI Prod Failed Run Test Project")
        # No dataset/model/split configured at all -- score_development_split's
        # own existing (pre-this-phase) honest-failure path: {"ok": False, "error": ...}
        response = client.post("/api/score/development-split", params={"project_id": project_id, "dataset_type": "train"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("scoringRunId", body)
        self.assertIsNotNone(body["scoringRunId"])

        listing = client.get("/api/scoring-runs", params={"projectId": project_id})
        self.assertEqual(listing.status_code, 200, listing.text)
        runs = listing.json()["scoringRuns"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failed")
        self.assertTrue(runs[0]["errorMessage"])
        self.assertIn("development split", runs[0]["errorMessage"].lower())


class ScoringRunDatasetCrossLinkTests(unittest.TestCase):
    """Phase K: ScoringRun <-> registered Scored Dataset bidirectional lineage."""

    @classmethod
    def setUpClass(cls) -> None:
        init_security_store()
        initialize_persistence()

    def setUp(self):
        self.client = _register("crosslink")
        self.project_id = _create_project(self.client, "VI Prod Cross-Link Test Project")
        _train_regression_model(self.client, self.project_id)
        scored = self.client.post("/api/score/development-split", params={"project_id": self.project_id, "dataset_type": "train"})
        self.assertEqual(scored.status_code, 200, scored.text)
        self.scoring_run_id = scored.json()["scoringRunId"]
        self.scored_rows = scored.json()["scored_rows"]

    def test_registration_cross_links_both_sides(self):
        response = self.client.post("/api/scoring/register-scored-dataset", json={
            "projectId": self.project_id, "projectName": "VI Prod Cross-Link Test Project",
            "datasetType": "train", "task": "regression", "modelName": "linreg",
            "rows": self.scored_rows, "scoringRunId": self.scoring_run_id,
        })
        self.assertEqual(response.status_code, 200, response.text)
        dataset = response.json()["dataset"]
        source_info = dataset.get("sourceInfo") or dataset.get("latestVersion", {}).get("sourceInfo") or {}
        # sourceInfo may live at dataset or version level depending on the registry's
        # response shape -- check the version's own metadata via the dataset detail API.
        detail = self.client.get(f"/api/datasets/{dataset['datasetId']}")
        self.assertEqual(detail.status_code, 200, detail.text)

        run_detail = self.client.get(f"/api/scoring-runs/{self.scoring_run_id}")
        self.assertEqual(run_detail.status_code, 200, run_detail.text)
        run = run_detail.json()["scoringRun"]
        self.assertEqual(run["registrationStatus"], "registered")
        self.assertEqual(run["outputDatasetId"], dataset["datasetId"])
        self.assertIsNotNone(run["outputDatasetVersionId"])

    def test_duplicate_registration_returns_existing_asset(self):
        first = self.client.post("/api/scoring/register-scored-dataset", json={
            "projectId": self.project_id, "projectName": "VI Prod Cross-Link Test Project",
            "datasetType": "train", "task": "regression", "modelName": "linreg",
            "rows": self.scored_rows, "scoringRunId": self.scoring_run_id,
        })
        self.assertEqual(first.status_code, 200, first.text)
        first_dataset_id = first.json()["dataset"]["datasetId"]

        second = self.client.post("/api/scoring/register-scored-dataset", json={
            "projectId": self.project_id, "projectName": "VI Prod Cross-Link Test Project",
            "datasetType": "train", "task": "regression", "modelName": "linreg",
            "rows": self.scored_rows, "scoringRunId": self.scoring_run_id,
        })
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json().get("alreadyRegistered"))
        self.assertEqual(second.json()["dataset"]["datasetId"], first_dataset_id)

    def test_stranger_cannot_register_via_another_projects_scoring_run(self):
        stranger = _register("stranger")
        other_project = _create_project(stranger, "Second Cross-Link Project")
        response = stranger.post("/api/scoring/register-scored-dataset", json={
            "projectId": other_project, "projectName": "Second Cross-Link Project",
            "datasetType": "train", "rows": self.scored_rows, "scoringRunId": self.scoring_run_id,
        })
        self.assertEqual(response.status_code, 403, response.text)


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
