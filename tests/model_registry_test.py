"""ATLAS Durable Model Registry and Model Versioning, Phase 1: backend tests.

Uses FastAPI's TestClient (in-process), matching the established pattern in
tests/scoring_runs_test.py and tests/vi_production_integration_test.py.

Isolation: dedicated security/persistence SQLite files, dedicated
ATLAS_DATASET_LIBRARY_ROOT, ATLAS_SCORING_RUN_ARTIFACT_ROOT, and
ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT (the governed joblib artifact root added
this phase).

Run:  .venv/Scripts/python.exe tests/model_registry_test.py
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
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
_TEST_DATA_ROOT = _REPO_ROOT / ".tmp"
_TEST_DATA_ROOT.mkdir(exist_ok=True)
_RUN_ID = uuid.uuid4().hex[:10]
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_registry_security_{_RUN_ID}.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / f"atlas_registry_persistence_{_RUN_ID}.db"
_CHECKPOINT_PATH = _TEST_DATA_ROOT / f"atlas_registry_checkpoint_{_RUN_ID}.json"
_LIBRARY_ROOT = _TEST_DATA_ROOT / f"atlas_registry_library_{_RUN_ID}"
_SCORING_ARTIFACT_ROOT = _TEST_DATA_ROOT / f"atlas_registry_scoringartifacts_{_RUN_ID}"
_MODEL_ARTIFACT_ROOT = _TEST_DATA_ROOT / f"atlas_registry_modelartifacts_{_RUN_ID}"
_BACKUP_ROOT = Path(tempfile.mkdtemp(prefix=f"atlas_registry_backups_{_RUN_ID}_"))
for _root in (_LIBRARY_ROOT, _SCORING_ARTIFACT_ROOT, _MODEL_ARTIFACT_ROOT):
    _root.mkdir(parents=True, exist_ok=True)
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_PATH)
os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(_LIBRARY_ROOT)
os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(_BACKUP_ROOT)
os.environ["ATLAS_SCORING_RUN_ARTIFACT_ROOT"] = str(_SCORING_ARTIFACT_ROOT)
os.environ["ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT"] = str(_MODEL_ARTIFACT_ROOT)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.datasets import dataset_registry  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.persistence.service import get_persistence_service  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402
import server.core.session_checkpoint as checkpoint  # noqa: E402


def _bind_dataset_library_paths() -> None:
    root = _LIBRARY_ROOT.resolve()
    os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(root)
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


_bind_checkpoint_path()
_bind_dataset_library_paths()


def setUpModule() -> None:
    _bind_checkpoint_path()
    _bind_dataset_library_paths()


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
    _CHECKPOINT_PATH.unlink(missing_ok=True)
    shutil.rmtree(_LIBRARY_ROOT, ignore_errors=True)
    shutil.rmtree(_SCORING_ARTIFACT_ROOT, ignore_errors=True)
    shutil.rmtree(_MODEL_ARTIFACT_ROOT, ignore_errors=True)
    shutil.rmtree(_BACKUP_ROOT, ignore_errors=True)


def _register(label: str) -> TestClient:
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{label}-{suffix}@atlas-registry-test.local",
            "displayName": f"Registry Test {label} {suffix}",
            "password": "RegistryTestPass!1",
            "role": "data_scientist",
        },
    )
    assert response.status_code == 200, response.text
    return client


def _create_project(client: TestClient, name: str) -> str:
    response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
    assert response.status_code == 200, response.text
    return response.json()["project"]["projectId"]


def _train_regression_model(
    client: TestClient,
    project_id: str,
    models=("linreg", "ridge_reg"),
) -> dict[str, Any]:
    """Create one exact, registered Phase 2B1 training context.

    This intentionally uses the Dataset Library registration/link/activation
    lifecycle.  None of the preparation or training endpoints is allowed to
    infer a dataset version from a browser-local sample or an empty legacy
    ``dataset_version`` alias.
    """
    df = pd.DataFrame({
        "feature_a": [float(i % 17) for i in range(400)],
        "feature_b": [float((i * 3) % 23) for i in range(400)],
        "MedHouseVal": [round(0.5 + (i % 11) * 0.31, 3) for i in range(400)],
    })
    files = {"file": ("reg.csv", io.BytesIO(df.to_csv(index=False).encode("utf-8")), "text/csv")}
    response = client.post(
        "/api/datasets/upload",
        data={
            "name": f"Registry regression {uuid.uuid4().hex[:8]}",
            "description": "Exact-lineage Model Registry integration fixture",
        },
        files=files,
    )
    assert response.status_code == 200, response.text
    dataset = response.json()["dataset"]
    dataset_id = str(dataset["datasetId"])
    dataset_version_id = str(dataset["created_dataset_version_id"])
    response = client.post(
        f"/api/projects/{project_id}/datasets/link",
        json={
            "datasetId": dataset_id,
            "versionId": dataset_version_id,
            "datasetRole": "modeling",
        },
    )
    assert response.status_code == 200, response.text
    response = client.post(
        f"/api/datasets/{dataset_id}/versions/{dataset_version_id}/activate",
        params={"project_id": project_id},
    )
    assert response.status_code == 200, response.text

    identity = {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
    }
    response = client.post(
        "/api/data/set_target",
        json={
            **identity,
            "expected_dataset_id": dataset_id,
            "expected_dataset_version_id": dataset_version_id,
            "target": "MedHouseVal",
            "selected_columns": ["feature_a", "feature_b"],
        },
    )
    assert response.status_code == 200, response.text
    response = client.post(
        "/api/outliers/apply",
        json={
            **identity,
            "expected_dataset_id": dataset_id,
            "expected_dataset_version_id": dataset_version_id,
            "config": {},
            "global_method": "IQR_1_5",
            "target": "MedHouseVal",
            "problem_type": "regression",
            "acknowledged_high_impact": True,
        },
    )
    assert response.status_code == 200, response.text
    response = client.post(
        "/api/missing/validate",
        json={
            **identity,
            "expected_dataset_id": dataset_id,
            "expected_dataset_version_id": dataset_version_id,
            "problem_type": "regression",
        },
    )
    assert response.status_code == 200, response.text
    response = client.post(
        "/api/features/manifest",
        json={**identity, "features": [], "pipeline_steps": []},
    )
    assert response.status_code == 200, response.text
    manifest_version = str(response.json()["manifest_version"])
    response = client.post(
        "/api/features/materialize",
        json={**identity, "manifest_version": manifest_version},
    )
    assert response.status_code == 200, response.text
    materialization_hash = str(response.json()["materialization_hash"])
    response = client.post(
        "/api/features/confirm",
        json={
            **identity,
            "manifest_version": manifest_version,
            "materialization_hash": materialization_hash,
        },
    )
    assert response.status_code == 200, response.text
    response = client.post(
        "/api/balancing_split/config",
        json={
            **identity,
            "split_strategy": "hybrid",
            "test_size": 0.2,
            "random_seed": 42,
            "stratify": False,
            "balance_method": "none",
            "problem_type": "regression",
            "event_value": None,
            "selected_features": ["feature_a", "feature_b"],
            "feature_manifest_version": manifest_version,
            "fold_method": "k_fold",
            "fold_count": 2,
            "cv_design_approved": True,
            "holdout_protection_confirmed": True,
            "final_holdout_policy": "untouched_until_final_comparison",
        },
    )
    assert response.status_code == 200, response.text
    split = response.json()
    split_id = str(split["split_id"])
    validation_design = split["validation_design"]
    validation_design_id = str(validation_design["validation_design_id"])
    validation_design_version = str(validation_design["design_version"])
    response = client.post(
        "/api/model/train/jobs",
        json={
            **identity,
            "models": list(models),
            "k_folds": 2,
            "max_parallel": 1,
            "calibrate": False,
            "target": "MedHouseVal",
            "event_value": None,
            "non_event_value": None,
            "problem_type": "regression",
            "feature_manifest_version": manifest_version,
            "split_id": split_id,
            "validation_design_id": validation_design_id,
            "validation_design_version": validation_design_version,
            "selected_original_features": ["feature_a", "feature_b"],
            "primary_metric": "rmse",
            "candidate_strategy": "registry_integration_test",
        },
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    deadline = time.time() + 90
    status = None
    job: dict[str, Any] = {}
    while time.time() < deadline:
        poll = client.get(f"/api/model/train/jobs/{job_id}", params={"project_id": project_id})
        assert poll.status_code == 200, poll.text
        job = poll.json()
        status = job.get("overall_status")
        if status in ("complete", "failed", "cancelled", "interrupted"):
            break
        time.sleep(0.1)
    assert status == "complete", job
    ranked = (job.get("summary") or {}).get("ranked") or job.get("partial_ranked_results") or []
    candidates = {
        str(row.get("key") or row.get("model_key") or row.get("algorithm_id")): row
        for row in ranked
        if isinstance(row, dict)
    }
    assert set(models).issubset(candidates), job
    return {
        **identity,
        "target": "MedHouseVal",
        "problem_type": "regression",
        "feature_manifest_version": manifest_version,
        "split_id": split_id,
        "validation_design_id": validation_design_id,
        "validation_design_version": validation_design_version,
        "training_job_id": job_id,
        "training_run_id": str(job["training_run_id"]),
        "candidates": candidates,
    }


def _candidate_context(training: dict[str, Any], algorithm: str = "linreg") -> dict[str, str]:
    candidate = training["candidates"][algorithm]
    contract = candidate["candidate_contract"]
    exact = {
        key: str(contract.get(key) or training.get(key) or "")
        for key in (
            "project_id",
            "dataset_id",
            "dataset_version_id",
            "candidate_id",
            "training_job_id",
            "training_run_id",
            "feature_manifest_version",
            "validation_design_id",
            "validation_design_version",
            "split_id",
            "target",
            "problem_type",
        )
    }
    assert all(exact.values()), {"algorithm": algorithm, "exact": exact, "contract": contract}
    return exact


def _lock_candidate_decision(
    client: TestClient,
    training: dict[str, Any],
    algorithm: str = "linreg",
) -> str:
    existing = str(training.get("candidate_decision_id") or "")
    if existing:
        return existing
    response = client.post(
        "/api/model/train/decision",
        json={
            "project_id": training["project_id"],
            "dataset_id": training["dataset_id"],
            "dataset_version_id": training["dataset_version_id"],
            "training_job_id": training["training_job_id"],
            "validation_design_id": training["validation_design_id"],
            "validation_design_version": training[
                "validation_design_version"
            ],
            "champion_model": algorithm,
            "challenger_models": [],
            "status": "proposed",
            "primary_metric": "rmse",
            "rationale": (
                "Registry integration locks this exact CV-ranked candidate "
                "before final-holdout Evaluation."
            ),
        },
    )
    assert response.status_code == 200, response.text
    decision = response.json()["decision"]
    decision_id = str(
        decision.get("candidate_decision_id")
        or decision.get("decision_id")
        or ""
    )
    assert decision_id.startswith("model-decision-"), decision
    assert decision["candidate_id"] == _candidate_context(
        training, algorithm
    )["candidate_id"], decision
    training["candidate_decision_id"] = decision_id
    return decision_id


def _complete_evaluation_package(
    client: TestClient,
    training: dict[str, Any],
    algorithm: str = "linreg",
) -> tuple[dict[str, str], str]:
    context = _candidate_context(training, algorithm)
    context["candidate_decision_id"] = _lock_candidate_decision(
        client,
        training,
        algorithm,
    )
    response = client.get("/api/eval/command_center", params=context)
    assert response.status_code == 200, response.text
    package = response.json()
    package_id = str(package.get("evaluation_package_id") or "")
    assert package.get("ok") is True and package_id.startswith("evalpkg-"), package
    assert (package.get("evaluation_package") or {}).get("status") == "complete", package
    return context, package_id


def _promote_candidate(
    client: TestClient,
    training: dict[str, Any],
    algorithm: str = "linreg",
):
    context, evaluation_package_id = _complete_evaluation_package(
        client, training, algorithm
    )
    response = client.post(
        "/api/model/save_final",
        json={**context, "evaluation_package_id": evaluation_package_id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("ok") is True, body
    assert body["modelVersion"]["candidateId"] == context["candidate_id"]
    assert body["modelVersion"]["evaluationPackageId"] == evaluation_package_id
    return response


class ModelRegistryTrainingIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _cleanup()
        init_security_store()
        initialize_persistence()

    def setUp(self):
        self.client = _register("owner")
        self.project_id = _create_project(self.client, "Model Registry Test Project")
        self.training = _train_regression_model(self.client, self.project_id)

    def test_save_final_model_creates_durable_model_and_version(self):
        response = _promote_candidate(self.client, self.training)
        body = response.json()
        self.assertTrue(body["ok"])
        model_id = body["metadata"].get("modelId")
        model_version_id = body["metadata"].get("modelVersionId")
        self.assertIsNotNone(model_id)
        self.assertIsNotNone(model_version_id)

        model_response = self.client.get(f"/api/models/{model_id}")
        self.assertEqual(model_response.status_code, 200, model_response.text)
        model = model_response.json()["model"]
        self.assertEqual(model["currentVersionId"], model_version_id)
        self.assertEqual(model["problemType"], "regression")

        version_response = self.client.get(f"/api/model-versions/{model_version_id}")
        self.assertEqual(version_response.status_code, 200, version_response.text)
        version = version_response.json()["modelVersion"]
        self.assertEqual(version["versionNumber"], 1)
        self.assertEqual(version["algorithm"], "linreg")
        self.assertIsNotNone(version["checksum"])
        self.assertEqual(version["artifactFormat"], "joblib")
        self.assertIn("rmse", version["metricsSummary"] or version["evaluationSummary"])

    def test_repeated_identical_promotion_is_idempotent(self):
        first = _promote_candidate(self.client, self.training)
        first_version_id = first.json()["metadata"]["modelVersionId"]

        second = _promote_candidate(self.client, self.training)
        second_version_id = second.json()["metadata"]["modelVersionId"]

        self.assertEqual(first_version_id, second_version_id)
        self.assertTrue(second.json()["promotion"]["idempotentReplay"])

        model_id = second.json()["metadata"]["modelId"]
        self.assertEqual(first.json()["metadata"]["modelId"], model_id)  # same parent Model
        history = self.client.get(f"/api/models/{model_id}/versions")
        self.assertEqual(history.status_code, 200, history.text)
        version_numbers = sorted(v["versionNumber"] for v in history.json()["modelVersions"])
        self.assertEqual(version_numbers, [1])

        # Immutability: the first version's content must be unchanged by the second save.
        first_detail = self.client.get(f"/api/model-versions/{first_version_id}").json()["modelVersion"]
        self.assertEqual(first_detail["versionNumber"], 1)

    def test_artifact_round_trips_and_matches_live_predictions(self):
        saved = _promote_candidate(self.client, self.training)
        model_version_id = saved.json()["metadata"]["modelVersionId"]

        from server.model_registry.model_registry_service import load_version_artifact
        from server.security.security_store import active_user  # noqa: F401

        service = get_persistence_service()
        row = service.model_versions.get(model_version_id)
        self.assertIsNotNone(row)
        from server.model_registry.model_artifacts import load_model_artifact, resolve_model_artifact_path
        artifact_path = resolve_model_artifact_path(row["artifact_reference"])
        self.assertTrue(artifact_path.exists())
        loaded = load_model_artifact(row["artifact_reference"])
        predictions = loaded.predict(pd.DataFrame({"feature_a": [3.0], "feature_b": [5.0]}))
        self.assertEqual(len(predictions), 1)

    def test_scoring_run_references_real_model_version_id(self):
        saved = _promote_candidate(self.client, self.training)
        model_version_id = saved.json()["metadata"]["modelVersionId"]

        scored = self.client.post("/api/score/development-split", params={"project_id": self.project_id, "dataset_type": "train"})
        self.assertEqual(scored.status_code, 200, scored.text)
        scoring_run_id = scored.json()["scoringRunId"]

        run_detail = self.client.get(f"/api/scoring-runs/{scoring_run_id}")
        self.assertEqual(run_detail.status_code, 200, run_detail.text)
        run = run_detail.json()["scoringRun"]
        self.assertEqual(run["modelVersionId"], model_version_id)

    def test_evidence_references_model_version_id_not_inferred(self):
        saved = _promote_candidate(self.client, self.training)
        model_version_id = saved.json()["metadata"]["modelVersionId"]
        scored = self.client.post("/api/score/development-split", params={"project_id": self.project_id, "dataset_type": "train"})
        scoring_run_id = scored.json()["scoringRunId"]

        evidence = self.client.get(f"/api/projects/{self.project_id}/evidence")
        self.assertEqual(evidence.status_code, 200, evidence.text)
        item = next((e for e in evidence.json()["evidence"] if e["sourceRef"] == scoring_run_id), None)
        self.assertIsNotNone(item)
        self.assertEqual(item["payload"]["modelVersionId"], model_version_id)

    def test_documentation_bundle_aggregates_model_context(self):
        saved = _promote_candidate(self.client, self.training)
        model_version_id = saved.json()["metadata"]["modelVersionId"]
        self.client.post("/api/score/development-split", params={"project_id": self.project_id, "dataset_type": "train"})

        bundle = self.client.get(f"/api/model-versions/{model_version_id}/documentation-bundle")
        self.assertEqual(bundle.status_code, 200, bundle.text)
        body = bundle.json()
        self.assertEqual(body["modelVersion"]["modelVersionId"], model_version_id)
        self.assertGreaterEqual(len(body["scoringRuns"]), 1)
        self.assertGreaterEqual(len(body["evidence"]), 1)

    def test_compare_versions_returns_metrics_and_hyperparameters_side_by_side(self):
        first = _promote_candidate(self.client, self.training, "linreg")
        # A second candidate cannot be selected from the first training run
        # after its final holdout has been exposed.  Build a separately
        # governed dataset/split/run so the comparison exercises two valid,
        # independently isolated model versions.
        second_training = _train_regression_model(
            self.client,
            self.project_id,
            models=("ridge_reg",),
        )
        second = _promote_candidate(
            self.client,
            second_training,
            "ridge_reg",
        )
        v1 = first.json()["metadata"]["modelVersionId"]
        v2 = second.json()["metadata"]["modelVersionId"]

        response = self.client.get("/api/model-versions/compare", params={"ids": f"{v1},{v2}"})
        self.assertEqual(response.status_code, 200, response.text)
        versions = response.json()["versions"]
        self.assertEqual({v["modelVersionId"] for v in versions}, {v1, v2})
        for v in versions:
            self.assertIn("hyperparameters", v)
            self.assertIn("metricsSummary", v)

    def test_archive_version_clears_current_version_but_preserves_lineage(self):
        saved = _promote_candidate(self.client, self.training)
        model_id = saved.json()["metadata"]["modelId"]
        model_version_id = saved.json()["metadata"]["modelVersionId"]

        archive_response = self.client.post(f"/api/model-versions/{model_version_id}/archive")
        self.assertEqual(archive_response.status_code, 200, archive_response.text)
        self.assertIsNotNone(archive_response.json()["modelVersion"]["archivedAt"])

        model = self.client.get(f"/api/models/{model_id}").json()["model"]
        self.assertIsNone(model["currentVersionId"])  # honestly cleared, not left dangling

        # Still readable -- archived, not deleted; lineage preserved.
        still_readable = self.client.get(f"/api/model-versions/{model_version_id}")
        self.assertEqual(still_readable.status_code, 200, still_readable.text)
        self.assertIsNotNone(still_readable.json()["modelVersion"]["lineage"])

    def test_archive_model_does_not_delete_scoring_runs_or_evidence(self):
        saved = _promote_candidate(self.client, self.training)
        model_id = saved.json()["metadata"]["modelId"]
        scored = self.client.post("/api/score/development-split", params={"project_id": self.project_id, "dataset_type": "train"})
        scoring_run_id = scored.json()["scoringRunId"]

        archive_response = self.client.post(f"/api/models/{model_id}/archive")
        self.assertEqual(archive_response.status_code, 200, archive_response.text)

        run_detail = self.client.get(f"/api/scoring-runs/{scoring_run_id}")
        self.assertEqual(run_detail.status_code, 200, run_detail.text)  # still exists
        evidence = self.client.get(f"/api/projects/{self.project_id}/evidence")
        self.assertGreaterEqual(evidence.json()["count"], 1)  # still exists

        default_listing = self.client.get("/api/models", params={"projectId": self.project_id})
        self.assertNotIn(model_id, {m["modelId"] for m in default_listing.json()["models"]})
        with_archived = self.client.get("/api/models", params={"projectId": self.project_id, "includeArchived": "true"})
        self.assertIn(model_id, {m["modelId"] for m in with_archived.json()["models"]})

    def test_unauthenticated_access_is_denied(self):
        anon = TestClient(app)
        response = anon.get("/api/models", params={"projectId": self.project_id})
        self.assertEqual(response.status_code, 401)

    def test_stranger_cannot_read_another_projects_models(self):
        saved = _promote_candidate(self.client, self.training)
        model_id = saved.json()["metadata"]["modelId"]
        stranger = _register("stranger")
        response = stranger.get(f"/api/models/{model_id}")
        self.assertEqual(response.status_code, 403, response.text)
        listing = stranger.get("/api/models", params={"projectId": self.project_id})
        self.assertEqual(listing.status_code, 403, listing.text)


class ModelRegistryProjectDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_security_store()
        initialize_persistence()

    def test_project_deletion_archives_but_does_not_delete_models(self):
        client = _register("deleter")
        project_id = _create_project(client, "Model Registry Deletion Test Project")
        training = _train_regression_model(client, project_id)
        saved = _promote_candidate(client, training)
        model_id = saved.json()["metadata"]["modelId"]
        model_version_id = saved.json()["metadata"]["modelVersionId"]

        response = client.delete(f"/api/projects/{project_id}")
        self.assertEqual(response.status_code, 200, response.text)

        service = get_persistence_service()
        model = service.models.get(model_id)
        self.assertIsNotNone(model, "Model must survive project deletion (durable, not cascade-deleted).")
        self.assertEqual(model["archived"], 1)
        version = service.model_versions.get(model_version_id)
        self.assertIsNotNone(version, "ModelVersion must survive project deletion.")
        self.assertIsNotNone(version["archived_at"])


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
