from __future__ import annotations

import hashlib
import json
import os
from types import SimpleNamespace
import uuid

from tests.hermetic_test_roots import make_test_root


_TEST_RUN_ID = uuid.uuid4().hex
_TEST_ROOT = make_test_root(
    f"special-value-legacy-refresh-{_TEST_RUN_ID}-",
    scope="temp",
)
_CHECKPOINT_PATH = _TEST_ROOT / "checkpoint" / f"workflow-{uuid.uuid4().hex}.json"
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_PATH)

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.analysis_partition.types import (
    ANALYSIS_PARTITION_REQUIRED,
    AnalysisPartitionError,
)
import server.core.session_checkpoint as checkpoint_module
from server.core.dataset_store import DatasetStore
from server.persistence.db import Database
from server.persistence.service import PersistenceService
from server.preprocessing import bureau_detection_router as router_module
from server.preprocessing import bureau_detection_service as service_module


checkpoint_module.CHECKPOINT_PATH = _CHECKPOINT_PATH


PROJECT_ID = "project-special-value-legacy-refresh"
DATASET_ID = "dataset-special-value-legacy-refresh"
VERSION_ID = "version-special-value-legacy-refresh"


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _authorization_record() -> dict[str, object]:
    target_base = {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "target": "bad_flag",
        "positive_value": 1,
        "negative_value": 0,
    }
    target_contract_id = f"target-contract-{_stable_hash(target_base)[:20]}"
    manifest_base = {
        **target_base,
        "target_contract_id": target_contract_id,
        "authorized_predictors": ["ExternalRiskEstimate"],
        "excluded_predictors": {},
        "selected_predictors": ["ExternalRiskEstimate"],
        "target_source_excluded": [],
        "target_source_detection_scope": "deferred_until_development_partition",
        "source": "data_acquisition",
    }
    predictor_authorization_id = (
        f"predictor-auth-{_stable_hash(manifest_base)[:20]}"
    )
    manifest = {
        **manifest_base,
        "predictor_authorization_id": predictor_authorization_id,
        "manifest_version": predictor_authorization_id,
        "artifact_hash": predictor_authorization_id.removeprefix("predictor-auth-"),
        "status": "current",
    }
    return {
        **manifest,
        "target_column": "bad_flag",
        "manifest_json": manifest,
    }


class _ExactAuthorizationRepository:
    def __init__(self) -> None:
        self.record = _authorization_record()

    def get_current_exact(
        self, project_id: str, dataset_id: str, dataset_version_id: str
    ) -> dict[str, object] | None:
        if (project_id, dataset_id, dataset_version_id) != (
            PROJECT_ID,
            DATASET_ID,
            VERSION_ID,
        ):
            return None
        return self.record


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api")
    app.dependency_overrides[router_module.require_user] = lambda: {
        "userId": "isolated-special-value-owner"
    }
    return TestClient(app, raise_server_exceptions=False)


def test_automatic_detection_supersedes_legacy_review_contract(
    monkeypatch,
) -> None:
    """An exact legacy row self-heals through the panel's POST-then-GET order."""

    database_path = (
        _TEST_ROOT / "database" / f"atlas-isolated-{uuid.uuid4().hex}.db"
    )
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(database_path)
    assert database.initialize()["ok"] is True
    persistence = PersistenceService(database)
    persistence.projects.ensure(
        PROJECT_ID,
        {"project_name": "Isolated legacy special-value review fixture"},
    )

    store = DatasetStore()
    store.raw_df = pd.DataFrame(
        {
            "ExternalRiskEstimate": [40, -9, 70, -9],
            "bad_flag": pd.Series([0, 1, 0, 0], dtype="int64"),
        }
    )
    store.current = lambda: store
    authorization_repository = _ExactAuthorizationRepository()

    def exact_identity(project_id: str, **kwargs):
        if (
            project_id != PROJECT_ID
            or kwargs.get("expected_dataset_id") != DATASET_ID
            or kwargs.get("expected_dataset_version_id") != VERSION_ID
        ):
            raise HTTPException(status_code=409, detail="identity mismatch")
        return {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "activation_revision": 4,
            "dataset_content_hash": "isolated-special-value-source-checksum",
            "rows": len(store.raw_df),
        }

    def no_analysis_partition(*_args, **_kwargs):
        raise AnalysisPartitionError(
            ANALYSIS_PARTITION_REQUIRED,
            "No Analysis Partition is present in this isolated structural fixture.",
        )

    monkeypatch.setattr(router_module, "DATASTORE", store)
    monkeypatch.setattr(service_module, "DATASTORE", store)
    monkeypatch.setattr(router_module, "authorize_modeling_scope", lambda *_args: None)
    monkeypatch.setattr(router_module, "assert_expected_active_identity", exact_identity)
    monkeypatch.setattr(
        router_module,
        "get_persistence_service",
        lambda: SimpleNamespace(
            predictor_authorizations=authorization_repository,
            special_value_reviews=persistence.special_value_reviews,
        ),
    )
    monkeypatch.setattr(
        router_module,
        "resolve_development_analysis_scope",
        no_analysis_partition,
    )
    monkeypatch.setattr(
        router_module,
        "_trusted_catalog_special_definitions",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(router_module, "schedule_checkpoint_save", lambda: None)

    client = _client()
    request = {
        "project_id": PROJECT_ID,
        "expected_dataset_id": DATASET_ID,
        "expected_dataset_version_id": VERSION_ID,
        "target": "bad_flag",
        "event_value": 1,
        "manual_declaration": "auto",
    }

    initialized = client.post("/api/data/bureau-detection", json=request)
    assert initialized.status_code == 200, initialized.text
    initialized_review = initialized.json()["special_value_review"]
    assert initialized_review["revision"] == 1

    row = persistence.special_value_reviews.get_exact(
        PROJECT_ID, DATASET_ID, VERSION_ID
    )
    assert row is not None
    legacy_detection = dict(row["detection_json"])
    for field in (
        "structural_scope",
        "source_checksum",
        "full_governed_population_rows",
        "target_evidence_status",
    ):
        legacy_detection.pop(field, None)
    legacy_detection["target_analysis_scope"] = "development_partition"
    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE special_value_reviews
            SET detection_fingerprint = ?, detection_json = ?, revision = 7
            WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
            """,
            (
                "legacy-contract-fingerprint",
                json.dumps(legacy_detection, sort_keys=True),
                PROJECT_ID,
                DATASET_ID,
                VERSION_ID,
            ),
        )

    exact_params = {
        "project_id": PROJECT_ID,
        "expected_dataset_id": DATASET_ID,
        "expected_dataset_version_id": VERSION_ID,
    }
    stale = client.get("/api/data/special-value-review", params=exact_params)
    assert stale.status_code == 409, stale.text
    stale_detail = stale.json()["detail"]
    assert stale_detail["code"] == "special_value_review_stale"
    assert set(stale_detail["superseded_contract_fields"]) == {
        "structural_scope",
        "source_checksum",
        "full_governed_population_rows",
        "target_analysis_scope",
    }

    refreshed = client.post("/api/data/bureau-detection", json=request)
    assert refreshed.status_code == 200, refreshed.text
    refreshed_payload = refreshed.json()
    refreshed_review = refreshed_payload["special_value_review"]
    assert refreshed_review["revision"] == 8
    assert refreshed_review["structural_scope"] == (
        "full_governed_population_predictors_only"
    )
    assert refreshed_review["source_checksum"] == (
        "isolated-special-value-source-checksum"
    )
    assert refreshed_review["full_governed_population_rows"] == 4
    assert refreshed_review["target_analysis_scope"] == "not_available"
    assert refreshed_review["target_evidence_status"] == "unavailable"
    assert refreshed_payload["final_holdout_accessed"] is False

    retrieved = client.get("/api/data/special-value-review", params=exact_params)
    assert retrieved.status_code == 200, retrieved.text
    assert retrieved.json()["special_value_review"] == refreshed_review

    with database.connection() as connection:
        events = connection.execute(
            """
            SELECT revision, event_type
            FROM special_value_review_events
            ORDER BY created_at, revision
            """
        ).fetchall()
    assert [(row["revision"], row["event_type"]) for row in events] == [
        (1, "detection_initialized"),
        (8, "detection_refreshed"),
    ]
