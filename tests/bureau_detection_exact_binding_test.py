from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid


_TEST_ROOT = (
    Path(__file__).resolve().parents[1]
    / ".tmp"
    / f"bureau-detection-exact-{uuid.uuid4().hex}"
)
_CHECKPOINT_PATH = _TEST_ROOT / "workflow_checkpoint.json"
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_PATH)

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.analysis_partition.types import (
    ANALYSIS_PARTITION_REQUIRED,
    AnalysisPartitionError,
)
from server.core import session_checkpoint as checkpoint_module
from server.core.dataset_store import DatasetStore
from server.preprocessing import bureau_detection_router as router_module
from server.preprocessing import bureau_detection_service as service_module
from server.preprocessing.bureau_detection_service import detect_bureau_data
from server.preprocessing.bureau_detection_types import BureauDetectionRequest


# ``server.main`` may already be imported by a larger pytest session, so bind
# both the environment and the module's cached path to this UUID-owned fixture
# before any HTTP route can schedule a checkpoint mutation.
_TEST_ROOT.mkdir(parents=True, exist_ok=True)
checkpoint_module.CHECKPOINT_PATH = _CHECKPOINT_PATH


PROJECT_ID = "project-bureau-exact"
DATASET_ID = "dataset-bureau-exact"
VERSION_ID = "version-bureau-exact"


def _request(**updates: object) -> BureauDetectionRequest:
    payload = {
        "project_id": PROJECT_ID,
        "expected_dataset_id": DATASET_ID,
        "expected_dataset_version_id": VERSION_ID,
        "target": "bad_flag",
        "event_value": 1,
    }
    payload.update(updates)
    return BureauDetectionRequest(**payload)


def _store() -> DatasetStore:
    store = DatasetStore()
    store.raw_df = pd.DataFrame(
        {
            "ExternalRiskEstimate": [40, -9, 70, -9],
            "bad_flag": pd.Series([0, 1, 0, 0], dtype="int64"),
        }
    )
    # A downstream treatment artifact intentionally contradicts the source.
    # Bureau structure must continue to come from raw_df.
    store.processed_df = pd.DataFrame(
        {
            "ExternalRiskEstimate": [999, 999, 999, 999],
            "bad_flag": [1, 1, 1, 1],
        }
    )
    store.target = None
    return store


def _authorization_record() -> dict[str, object]:
    target_base = {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "target": "bad_flag",
        "positive_value": 1,
        "negative_value": 0,
    }
    stable = lambda payload: hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    target_contract_id = f"target-contract-{stable(target_base)[:20]}"
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
    authorization_id = f"predictor-auth-{stable(manifest_base)[:20]}"
    manifest = {
        **manifest_base,
        "predictor_authorization_id": authorization_id,
        "manifest_version": authorization_id,
        "artifact_hash": authorization_id.removeprefix("predictor-auth-"),
        "status": "current",
    }
    return {
        **manifest,
        "target_column": "bad_flag",
        "status": "current",
        "manifest_json": manifest,
    }


def test_service_uses_raw_frame_and_development_only_target_evidence(monkeypatch):
    store = _store()
    monkeypatch.setattr(service_module, "DATASTORE", store)
    development_features = store.raw_df.iloc[[0, 1]][
        ["ExternalRiskEstimate"]
    ].copy()
    development_target = store.raw_df.iloc[[0, 1]]["bad_flag"].copy()

    result = detect_bureau_data(
        _request(),
        authorized_predictors=["ExternalRiskEstimate"],
        target_analysis_features=development_features,
        target_analysis_target=development_target,
        target_analysis_scope="development_population",
        analysis_partition_id="analysis-partition-exact",
        analysis_partition_revision=1,
        development_partition_id="development-exact",
        governed_event_value=1,
    )

    variable = result["variables"][0]
    assert result["row_count"] == 4
    assert variable["special_value_count"] == 2
    assert variable["special_values"][0]["event_count"] == 1
    assert variable["special_values"][0]["event_rate"] == 1.0
    assert result["target_analysis_scope"] == "development_population"
    assert result["final_holdout_accessed"] is False
    assert isinstance(result["event_value"], int)
    json.dumps(result, allow_nan=False)


class _ExactAuthorizationRepository:
    def __init__(self, record: dict[str, object] | None):
        self.record = record
        self.calls: list[tuple[str, str, str]] = []

    def get_current_exact(self, project_id: str, dataset_id: str, version_id: str):
        self.calls.append((project_id, dataset_id, version_id))
        return self.record


class _SpecialReviewRepository:
    def __init__(self):
        self.row: dict[str, object] | None = None

    def sync_detection(self, record: dict[str, object]):
        self.row = {
            "special_value_review_id": "special-review-exact",
            "project_id": record["project_id"],
            "dataset_id": record["dataset_id"],
            "dataset_version_id": record["dataset_version_id"],
            "activation_revision": record["activation_revision"],
            "predictor_authorization_id": record["predictor_authorization_id"],
            "target_contract_id": record["target_contract_id"],
            "detection_fingerprint": record["detection_fingerprint"],
            "detection_json": record["detection"],
            "decisions_json": [],
            "reviewer_rationale": "",
            "status": record["status"],
            "detected_count": record["detected_count"],
            "reviewed_count": 0,
            "open_count": record["open_count"],
            "blocks_confirmation": record["blocks_confirmation"],
            "blocks_continuation": record["blocks_continuation"],
            "revision": 1,
            "confirmed_at": None,
            "updated_at": "2026-08-03T00:00:00+00:00",
        }
        return self.row

    def get_exact(self, *_args):
        return self.row

    def save_review(self, record, *, expected_revision):
        if self.row is None:
            raise AssertionError("Detection must initialize the review first.")
        if int(self.row["revision"]) != int(expected_revision):
            raise router_module.SpecialValueReviewConflictError(
                "The fixture review changed concurrently.", current=self.row
            )
        self.row = {
            **self.row,
            "decisions_json": record["decisions"],
            "reviewer_rationale": record["reviewer_rationale"],
            "status": record["status"],
            "detected_count": record["detected_count"],
            "reviewed_count": record["reviewed_count"],
            "open_count": record["open_count"],
            "blocks_confirmation": record["blocks_confirmation"],
            "blocks_continuation": record["blocks_continuation"],
            "revision": int(self.row["revision"]) + 1,
            "confirmed_at": (
                "2026-08-03T00:01:00+00:00"
                if record["status"] == "confirmed"
                else None
            ),
        }
        return self.row


class _PartitionAuthority:
    def __init__(self, store: DatasetStore, *, current: bool = True):
        self.store = store
        self.current_partition = current
        self.current_calls: list[tuple[object, ...]] = []
        self.development_calls = 0

    def current(self, *args, **kwargs):
        self.current_calls.append((*args, kwargs))
        if not self.current_partition:
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_REQUIRED,
                "No partition has been confirmed.",
            )
        return {
            "analysis_partition_id": "analysis-partition-exact",
            "development_partition_id": "development-exact",
        }

    def materialize_development(self, store, partition, authorized_predictors=None):
        assert store is self.store
        assert authorized_predictors == ["ExternalRiskEstimate"]
        self.development_calls += 1
        frame = store.raw_df.iloc[[0, 1]][authorized_predictors].copy()
        target = store.raw_df.iloc[[0, 1]]["bad_flag"].copy()
        return frame, target

    def materialize_validation(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("Bureau detection must never materialize final holdout rows.")


def _bind_route(monkeypatch, *, current_partition: bool = True):
    store = _store()
    store.current = lambda: store
    repository = _ExactAuthorizationRepository(_authorization_record())
    special_reviews = _SpecialReviewRepository()
    repository.special_reviews = special_reviews
    partition_authority = _PartitionAuthority(store, current=current_partition)
    checkpoint_calls: list[bool] = []
    identity_calls: list[dict[str, object]] = []

    def exact_identity(project_id: str, **kwargs):
        identity_calls.append({"project_id": project_id, **kwargs})
        if (
            project_id != PROJECT_ID
            or kwargs["expected_dataset_id"] != DATASET_ID
            or kwargs["expected_dataset_version_id"] != VERSION_ID
        ):
            raise HTTPException(status_code=409, detail="identity mismatch")
        return {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "activation_revision": 4,
        }

    monkeypatch.setattr(router_module, "DATASTORE", store)
    monkeypatch.setattr(service_module, "DATASTORE", store)
    monkeypatch.setattr(router_module, "authorize_modeling_scope", lambda *args: None)
    monkeypatch.setattr(router_module, "assert_expected_active_identity", exact_identity)
    monkeypatch.setattr(
        router_module,
        "get_persistence_service",
        lambda: SimpleNamespace(
            predictor_authorizations=repository,
            special_value_reviews=special_reviews,
        ),
    )
    def exact_development_scope(store_arg, identity, **kwargs):
        partition_authority.current_calls.append((identity, kwargs))
        if not partition_authority.current_partition:
            raise AnalysisPartitionError(
                ANALYSIS_PARTITION_REQUIRED,
                "No partition has been confirmed.",
            )
        frame, target = partition_authority.materialize_development(
            store_arg,
            {"analysis_partition_id": "analysis-partition-exact"},
            authorized_predictors=["ExternalRiskEstimate"],
        )
        return SimpleNamespace(
            development_features=frame,
            development_target=target,
            event_value=1,
            partition={
                "analysis_partition_id": "analysis-partition-exact",
                "revision": 1,
                "development_partition_id": "development-exact",
            },
            metadata=lambda: {
                "analytical_scope": "development_population",
                "population_id": "development-exact",
                "population_count": int(len(target)),
                "partition_id": "analysis-partition-exact",
                "partition_revision": 1,
                "holdout_excluded": True,
                "source_checksum": "synthetic-bureau-checksum",
                "actor": str(kwargs.get("actor") or "bureau-owner"),
                "timestamp": "2026-08-04T12:00:00+00:00",
            },
        )

    monkeypatch.setattr(
        router_module,
        "resolve_development_analysis_scope",
        exact_development_scope,
    )
    monkeypatch.setattr(
        router_module,
        "schedule_checkpoint_save",
        lambda: checkpoint_calls.append(True),
    )
    return store, repository, partition_authority, checkpoint_calls, identity_calls


def _http_client() -> TestClient:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api")
    app.dependency_overrides[router_module.require_user] = lambda: {
        "userId": "bureau-owner"
    }
    return TestClient(app, raise_server_exceptions=False)


def test_route_binds_fresh_process_to_exact_identity_and_development_partition(monkeypatch):
    store, repository, partition, checkpoints, identity_calls = _bind_route(monkeypatch)

    result = router_module.bureau_detection(
        _request(target=None), {"userId": "bureau-owner"}
    )

    assert repository.calls == [(PROJECT_ID, DATASET_ID, VERSION_ID)]
    assert identity_calls[0]["require_expected"] is True
    assert partition.development_calls == 1
    assert result["project_id"] == PROJECT_ID
    assert result["dataset_id"] == DATASET_ID
    assert result["dataset_version_id"] == VERSION_ID
    assert result["activation_revision"] == 4
    assert result["target"] == "bad_flag"
    assert result["target_analysis_scope"] == "development_population"
    assert result["final_holdout_accessed"] is False
    assert store.meta["bureau_review"] == result
    assert checkpoints == [True]


def test_http_transport_returns_nonempty_json_safe_response(monkeypatch):
    _bind_route(monkeypatch)
    response = _http_client().post(
        "/api/data/bureau-detection",
        json=_request().model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert isinstance(payload["event_value"], int)
    assert payload["target_analysis_scope"] == "development_population"
    assert payload["final_holdout_accessed"] is False
    assert payload["correlation_id"].startswith("bureau-")
    review = payload["special_value_review"]
    assert review["authority"] == "backend_durable_exact_version"
    assert review["browser_cache_authority"] is False
    assert review["detected_count"] == 1
    assert review["reviewed_count"] == 0
    assert review["open_count"] == 1
    assert review["blocks_confirmation"] is True
    assert review["blocks_continuation"] is True


def test_prepartition_route_fails_closed_without_target_analysis(monkeypatch):
    store, _, partition, checkpoints, _ = _bind_route(
        monkeypatch, current_partition=False
    )
    with pytest.raises(HTTPException) as captured:
        router_module.bureau_detection(
            _request(), {"userId": "bureau-owner"}
        )
    assert partition.development_calls == 0
    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == ANALYSIS_PARTITION_REQUIRED
    assert "bureau_review" not in store.meta
    assert checkpoints == []


@pytest.mark.parametrize(
    ("updates", "expected_status", "expected_code"),
    [
        (
            {"expected_dataset_id": None},
            422,
            "dataset_identity_required",
        ),
        (
            {"target": "wrong_target"},
            409,
            "target_contract_mismatch",
        ),
    ],
)
def test_binding_failures_are_controlled_and_do_not_publish(
    monkeypatch, updates, expected_status, expected_code
):
    store, _, _, checkpoints, _ = _bind_route(monkeypatch)
    with pytest.raises(HTTPException) as captured:
        router_module.bureau_detection(
            _request(**updates), {"userId": "bureau-owner"}
        )
    assert captured.value.status_code == expected_status
    assert captured.value.detail["code"] == expected_code
    assert captured.value.detail["correlation_id"].startswith("bureau-")
    assert "bureau_review" not in store.meta
    assert checkpoints == []


def test_tampered_predictor_authorization_checksum_is_rejected_before_publish(
    monkeypatch,
):
    store, repository, partition, checkpoints, _ = _bind_route(monkeypatch)
    assert repository.record is not None
    repository.record["artifact_hash"] = "tampered-artifact-hash"

    with pytest.raises(HTTPException) as captured:
        router_module.bureau_detection(_request(), {"userId": "bureau-owner"})

    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == "predictor_authorization_stale"
    assert partition.current_calls == []
    assert "bureau_review" not in store.meta
    assert checkpoints == []


def test_unexpected_failure_returns_safe_correlated_500_without_mutation(monkeypatch):
    store, _, _, checkpoints, _ = _bind_route(monkeypatch)
    monkeypatch.setattr(
        router_module,
        "detect_bureau_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret detail")),
    )
    with pytest.raises(HTTPException) as captured:
        router_module.bureau_detection(_request(), {"userId": "bureau-owner"})
    assert captured.value.status_code == 500
    assert captured.value.detail["code"] == "bureau_detection_unavailable"
    assert "secret detail" not in str(captured.value.detail)
    assert captured.value.detail["correlation_id"].startswith("bureau-")
    assert "bureau_review" not in store.meta
    assert checkpoints == []


def test_http_unexpected_failure_is_nonempty_safe_and_correlated(monkeypatch):
    _bind_route(monkeypatch)
    monkeypatch.setattr(
        router_module,
        "detect_bureau_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("C:\\secret\\regulated.csv token=do-not-expose")
        ),
    )
    response = _http_client().post(
        "/api/data/bureau-detection",
        json=_request().model_dump(mode="json"),
    )
    assert response.status_code == 500
    assert response.text
    detail = response.json()["detail"]
    assert detail["code"] == "bureau_detection_unavailable"
    assert "regulated.csv" not in response.text
    assert response.headers["x-request-correlation-id"] == detail["correlation_id"]


def test_durable_review_api_blocks_incomplete_confirmation_and_accepts_exact_revision(
    monkeypatch,
):
    _bind_route(monkeypatch)
    client = _http_client()
    detection_response = client.post(
        "/api/data/bureau-detection",
        json=_request().model_dump(mode="json"),
    )
    assert detection_response.status_code == 200, detection_response.text
    initial = detection_response.json()["special_value_review"]
    assert initial["open_items"] == ["ExternalRiskEstimate"]

    incomplete = client.put(
        "/api/data/special-value-review",
        json={
            "project_id": PROJECT_ID,
            "expected_dataset_id": DATASET_ID,
            "expected_dataset_version_id": VERSION_ID,
            "expected_revision": initial["revision"],
            "detection_fingerprint": initial["detection_fingerprint"],
            "intent": "confirm",
            "variable_decisions": [],
        },
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["detail"]["code"] == "special_value_review_incomplete"
    assert incomplete.json()["detail"]["open_items"] == ["ExternalRiskEstimate"]

    draft = client.put(
        "/api/data/special-value-review",
        json={
            "project_id": PROJECT_ID,
            "expected_dataset_id": DATASET_ID,
            "expected_dataset_version_id": VERSION_ID,
            "expected_revision": initial["revision"],
            "detection_fingerprint": initial["detection_fingerprint"],
            "intent": "draft",
            "variable_decisions": [
                {
                    "variable": "ExternalRiskEstimate",
                    "policy": "preserve_informative",
                    "rationale": "",
                    "overrides": [],
                }
            ],
        },
    )
    assert draft.status_code == 200, draft.text
    ready = draft.json()["special_value_review"]
    assert ready["status"] == "ready_for_confirmation"
    assert ready["open_count"] == 0
    assert ready["blocks_confirmation"] is False
    assert ready["blocks_continuation"] is True

    confirmed = client.put(
        "/api/data/special-value-review",
        json={
            "project_id": PROJECT_ID,
            "expected_dataset_id": DATASET_ID,
            "expected_dataset_version_id": VERSION_ID,
            "expected_revision": ready["revision"],
            "detection_fingerprint": ready["detection_fingerprint"],
            "intent": "confirm",
            "variable_decisions": ready["variable_decisions"],
            "reviewer_rationale": "Confirmed against the exact detected values.",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    final = confirmed.json()["special_value_review"]
    assert final["status"] == "confirmed"
    assert final["reviewed_count"] == final["detected_count"] == 1
    assert final["open_count"] == 0
    assert final["blocks_continuation"] is False

    retrieved = client.get(
        "/api/data/special-value-review",
        params={
            "project_id": PROJECT_ID,
            "expected_dataset_id": DATASET_ID,
            "expected_dataset_version_id": VERSION_ID,
        },
    )
    assert retrieved.status_code == 200, retrieved.text
    assert retrieved.json()["special_value_review"] == final


def test_review_api_rejects_stale_revision_and_unknown_backend_variable(monkeypatch):
    _bind_route(monkeypatch)
    client = _http_client()
    initial = client.post(
        "/api/data/bureau-detection", json=_request().model_dump(mode="json")
    ).json()["special_value_review"]
    unknown = client.put(
        "/api/data/special-value-review",
        json={
            "project_id": PROJECT_ID,
            "expected_dataset_id": DATASET_ID,
            "expected_dataset_version_id": VERSION_ID,
            "expected_revision": initial["revision"],
            "detection_fingerprint": initial["detection_fingerprint"],
            "intent": "draft",
            "variable_decisions": [
                {
                    "variable": "NotBackendDetected",
                    "policy": "preserve_informative",
                }
            ],
        },
    )
    assert unknown.status_code == 409
    assert unknown.json()["detail"]["code"] == "unknown_special_value_variable"

    first = client.put(
        "/api/data/special-value-review",
        json={
            "project_id": PROJECT_ID,
            "expected_dataset_id": DATASET_ID,
            "expected_dataset_version_id": VERSION_ID,
            "expected_revision": initial["revision"],
            "detection_fingerprint": initial["detection_fingerprint"],
            "intent": "draft",
            "variable_decisions": [
                {
                    "variable": "ExternalRiskEstimate",
                    "policy": "preserve_informative",
                }
            ],
        },
    )
    assert first.status_code == 200
    stale = client.put(
        "/api/data/special-value-review",
        json={
            "project_id": PROJECT_ID,
            "expected_dataset_id": DATASET_ID,
            "expected_dataset_version_id": VERSION_ID,
            "expected_revision": initial["revision"],
            "detection_fingerprint": initial["detection_fingerprint"],
            "intent": "draft",
            "variable_decisions": [
                {
                    "variable": "ExternalRiskEstimate",
                    "policy": "preserve_informative",
                }
            ],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "special_value_review_revision_conflict"


def test_review_api_cannot_cross_project_scope(monkeypatch):
    _bind_route(monkeypatch)
    client = _http_client()
    response = client.get(
        "/api/data/special-value-review",
        params={
            "project_id": "other-project",
            "expected_dataset_id": DATASET_ID,
            "expected_dataset_version_id": VERSION_ID,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dataset_identity_mismatch"
