"""Focused durable Scoring continuation contracts.

These tests are intentionally hermetic: persistence is initialized only in an
isolated temporary database, and they do not touch a live project, write a real
scoring artifact, or start a service.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from server.evaluation import eval_service
from server.persistence.db import Database
from server.persistence.repositories.scoring_run_repository import ScoringRunRepository
from server.scoring_runs import scoring_run_service


def test_scoring_run_repository_filters_the_exact_continuation_identity(monkeypatch) -> None:
    repository = object.__new__(ScoringRunRepository)
    captured: dict[str, object] = {}

    def capture(query: str, params: tuple[object, ...]):
        captured.update(query=query, params=params)
        return []

    monkeypatch.setattr(repository, "_many", capture)

    repository.list(
        project_id="project-exact",
        dataset_id="dataset-exact",
        dataset_version_id="dataset-version-exact",
        model_version_id="model-version-exact",
        target="bad_flag",
        status="completed",
    )

    query = str(captured["query"])
    for column in (
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "model_version_id",
        "target",
        "status",
    ):
        assert f"{column} = ?" in query
    assert "archived_at IS NULL" in query
    assert captured["params"] == (
        "project-exact",
        "dataset-exact",
        "dataset-version-exact",
        "model-version-exact",
        "bad_flag",
        "completed",
        200,
    )


def test_completed_scoring_run_persists_final_model_exact_identity(monkeypatch) -> None:
    saved: dict[str, object] = {}

    class FakeScoringRuns:
        @staticmethod
        def upsert(record):
            saved.update(record)
            return record

    service = SimpleNamespace(
        scoring_runs=FakeScoringRuns(),
        evidence=SimpleNamespace(upsert=lambda _record: None),
    )
    monkeypatch.setattr(scoring_run_service, "authorize_modeling_scope", lambda *_args: None)
    monkeypatch.setattr(
        scoring_run_service,
        "write_scoring_run_parquet",
        lambda *_args: {"path": "isolated-scoring.parquet", "checksum": "sha256-exact"},
    )
    monkeypatch.setattr(scoring_run_service, "get_persistence_service", lambda: service)

    result = scoring_run_service.create_scoring_run(
        {"userId": "user-exact"},
        "project-exact",
        "train",
        {
            "ok": True,
            "task": "classification",
            "rows": 1,
            "scored_rows": [{"prediction": 1}],
            "model": {
                "modelId": "model-exact",
                "modelVersionId": "model-version-exact",
                "training_dataset_id": "dataset-exact",
                "training_dataset_version_id": "dataset-version-exact",
                "target_name": "bad_flag",
            },
        },
    )

    assert result is not None
    assert saved["project_id"] == "project-exact"
    assert saved["dataset_id"] == "dataset-exact"
    assert saved["dataset_version_id"] == "dataset-version-exact"
    assert saved["model_version_id"] == "model-version-exact"
    assert saved["target"] == "bad_flag"
    assert saved["status"] == "completed"
    assert saved["checksum"] == "sha256-exact"
    assert saved["archived_at"] is None


def test_real_score_response_persists_the_exact_promoted_identity(monkeypatch) -> None:
    """Exercise the production EvaluationService -> ScoringRun handoff.

    The durable continuation gate reads the training dataset identity from the
    final-model metadata returned by ``score_dataset``.  Keep this test on the
    real score response construction so a future response-shape change cannot
    silently create an unqueryable completed run.
    """

    class ExactClassificationModel:
        @staticmethod
        def predict_proba(frame: pd.DataFrame) -> np.ndarray:
            probabilities = np.asarray([0.2, 0.8], dtype=float)[: len(frame)]
            return np.column_stack((1.0 - probabilities, probabilities))

    final_metadata = {
        "model_key": "logreg",
        "name": "Exact governed logistic regression",
        "features": ["feature_a"],
        "modelId": "model-exact",
        "modelVersionId": "model-version-exact",
        "project_id": "project-exact",
        "dataset_id": "dataset-exact",
        "dataset_version_id": "dataset-version-exact",
        "target": "bad_flag",
    }
    monkeypatch.setattr(
        eval_service.EVAL,
        "_resolve_scoring_model",
        lambda _model_name: (ExactClassificationModel(), final_metadata),
    )
    monkeypatch.setattr(eval_service.EVAL, "_is_regression_problem", lambda: False)
    monkeypatch.setattr(
        eval_service.EVAL,
        "_default_priors",
        lambda: {
            "original_prior": 0.5,
            "model_prior": 0.5,
            "split_config": {},
            "train_rows": 2,
        },
    )
    monkeypatch.setattr(
        eval_service,
        "DATASTORE",
        SimpleNamespace(target="bad_flag"),
    )

    score_result = eval_service.EVAL.score_dataset(
        pd.DataFrame(
            {
                "feature_a": [1.0, 2.0],
                "bad_flag": [0, 1],
            }
        ),
        dataset_type="train",
        model_name="final",
    )
    assert score_result["ok"] is True
    assert score_result["target_column"] == "bad_flag"
    assert score_result["model"] is final_metadata

    saved: dict[str, object] = {}

    class FakeScoringRuns:
        @staticmethod
        def upsert(record):
            saved.update(record)
            return record

    service = SimpleNamespace(
        scoring_runs=FakeScoringRuns(),
        evidence=SimpleNamespace(upsert=lambda _record: None),
    )
    monkeypatch.setattr(scoring_run_service, "authorize_modeling_scope", lambda *_args: None)
    monkeypatch.setattr(
        scoring_run_service,
        "write_scoring_run_parquet",
        lambda *_args: {"path": "isolated-real-score.parquet", "checksum": "sha256-real-score"},
    )
    monkeypatch.setattr(scoring_run_service, "get_persistence_service", lambda: service)

    persisted = scoring_run_service.create_scoring_run(
        {"userId": "user-exact"},
        "project-exact",
        "train",
        score_result,
        dataset_context={
            "datasetIdentity": "Governed development TRAIN split",
            "source": "development_split",
        },
    )

    assert persisted is not None
    assert saved["project_id"] == "project-exact"
    assert saved["dataset_id"] == "dataset-exact"
    assert saved["dataset_version_id"] == "dataset-version-exact"
    assert saved["target"] == "bad_flag"
    assert saved["model_version_id"] == "model-version-exact"
    assert saved["partition"] == "train"
    assert saved["status"] == "completed"
    assert saved["checksum"] == "sha256-real-score"


def test_exact_identity_round_trips_through_the_real_scoring_run_table(tmp_path) -> None:
    database = Database(tmp_path / "scoring-continuation.db")
    health = database.initialize()
    assert health["ok"] is True
    timestamp = "2026-08-08T00:00:00+00:00"
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO projects (
              project_id, project_name, project_type, workflow_type,
              status, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "project-exact",
                "Exact scoring continuation",
                "predictive-modeling",
                "predictive-modeling",
                "active",
                timestamp,
                timestamp,
                "{}",
            ),
        )

    repository = ScoringRunRepository(database)
    repository.upsert(
        {
            "scoring_run_id": "scoring-run-exact",
            "project_id": "project-exact",
            "user_id": "user-exact",
            "dataset_id": "dataset-exact",
            "dataset_version_id": "dataset-version-exact",
            "dataset_identity": "Governed development TRAIN split",
            "partition": "train",
            "model_id": "logreg",
            "model_version": "display-only-version",
            "model_version_id": "model-version-exact",
            "problem_type": "classification",
            "target": "bad_flag",
            "status": "completed",
            "created_at": timestamp,
            "completed_at": timestamp,
            "row_count": 2,
            "output_artifact_path": "isolated-real-score.parquet",
            "checksum": "sha256-real-score",
            "updated_at": timestamp,
        }
    )

    exact = repository.list(
        project_id="project-exact",
        dataset_id="dataset-exact",
        dataset_version_id="dataset-version-exact",
        model_version_id="model-version-exact",
        target="bad_flag",
        status="completed",
    )
    assert len(exact) == 1
    assert exact[0]["scoring_run_id"] == "scoring-run-exact"
    assert exact[0]["dataset_id"] == "dataset-exact"
    assert exact[0]["dataset_version_id"] == "dataset-version-exact"
    assert exact[0]["model_version_id"] == "model-version-exact"
    assert exact[0]["target"] == "bad_flag"
    assert exact[0]["checksum"] == "sha256-real-score"

    for mismatched_filter in (
        {"dataset_id": "other-dataset"},
        {"dataset_version_id": "other-version"},
        {"model_version_id": "other-model-version"},
        {"target": "other_target"},
    ):
        assert repository.list(
            project_id="project-exact",
            status="completed",
            **mismatched_filter,
        ) == []
