from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import uuid
from unittest.mock import Mock, patch


# Resolve every application-owned storage root before importing server modules.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_TEST_ROOT = (_REPOSITORY_ROOT / ".tmp" / f"repro-context-{uuid.uuid4().hex}").resolve()
_TEST_ROOT.mkdir(parents=True, exist_ok=True)
_ISOLATED_ENVIRONMENT = {
    "ATLAS_ENV": "test",
    "ATLAS_TEST_MODE": "1",
    "ATLAS_SECURITY_ROOT": str(_TEST_ROOT / "security"),
    "ATLAS_SECURITY_DB_PATH": str(_TEST_ROOT / "security" / "security.db"),
    "ATLAS_SQLITE_PATH": str(_TEST_ROOT / "persistence" / "atlas.db"),
    "ATLAS_CHECKPOINT_PATH": str(_TEST_ROOT / "checkpoints" / "checkpoint.json"),
    "ATLAS_DATASET_LIBRARY_ROOT": str(_TEST_ROOT / "dataset-library"),
    "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": str(_TEST_ROOT / "dataset-library-backups"),
    "ATLAS_EVIDENCE_ROOT": str(_TEST_ROOT / "evidence"),
    "ATLAS_FEATURE_MANIFEST_ROOT": str(_TEST_ROOT / "feature-manifests"),
    "ATLAS_VIF_PLAN_ROOT": str(_TEST_ROOT / "vif-plans"),
    "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT": str(_TEST_ROOT / "model-registry"),
    "ATLAS_SCORING_RUN_ARTIFACT_ROOT": str(_TEST_ROOT / "scoring-runs"),
    "ATLAS_AUTH_ENABLED": "true",
}
os.environ.update(_ISOLATED_ENVIRONMENT)
for _name, _value in _ISOLATED_ENVIRONMENT.items():
    if _name.endswith(("ROOT", "PATH")):
        _resolved = Path(_value).resolve()
        if _TEST_ROOT != _resolved and _TEST_ROOT not in _resolved.parents:
            raise RuntimeError(f"{_name} escaped the isolated test root.")

from server.analysis_partition.service import analysis_partition_service  # noqa: E402
from server.core import metadata_router  # noqa: E402


PROJECT_ID = "project-repro-isolated"
DATASET_ID = "dataset-repro-isolated"
VERSION_ID = "version-repro-isolated-1"
TARGET_CONTRACT_ID = "target-contract-repro"
AUTHORIZATION_ID = "predictor-auth-repro"


def _identity() -> dict:
    return {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "dataset_version_label": "Version 1",
        "dataset_source_type": "registered_upload",
        "activation_revision": 3,
        "dataset": {"name": "Repro Safety Dataset"},
        "version": {"rowCount": 120, "columnCount": 5},
        # A physical path may exist inside the durable resolver, but it must
        # never cross the endpoint boundary.
        "artifact_path": _TEST_ROOT / "dataset-library" / "data_full.csv",
    }


def _manifest() -> dict:
    return {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "target_contract_id": TARGET_CONTRACT_ID,
        "target": "outcome",
        "positive_value": 1,
        "negative_value": 0,
        "predictor_authorization_id": AUTHORIZATION_ID,
        "status": "current",
        "authorized_predictors": ["feature_a", "feature_b"],
        "selected_predictors": ["feature_a", "feature_b"],
        "excluded_predictors": {
            "source_outcome": "Not selected in the governed predictor manifest",
            "atlas_split": "Split or fold metadata cannot be used as a predictor",
        },
        "target_source_excluded": [],
        "target_source_detection_scope": "deferred_until_development_partition",
    }


def _partition() -> dict:
    return {
        "analysis_partition_id": "analysis-partition-repro-r2",
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "target_contract_id": TARGET_CONTRACT_ID,
        "target_column": "outcome",
        "predictor_authorization_id": AUTHORIZATION_ID,
        "revision": 2,
        "status": "current",
        "development_share": 0.8,
        "holdout_share": 0.2,
        "development_count": 96,
        "holdout_count": 24,
        "random_seed": 42,
        "stratification_policy": "target",
        "stratification_field": "outcome",
        "final_holdout_status": "sealed",
        "holdout_isolation_status": "verified",
        # These integrity fields may be read by the service but may never be
        # returned by the metadata-only endpoint.
        "row_assignments_json": {
            "development_positions": list(range(96)),
            "holdout_positions": list(range(96, 120)),
        },
        "event_counts_json": {
            "development": {"event": 12},
            "holdout": {"event": 3},
        },
        "assignment_hash": "internal-only",
        "artifact_hash": "internal-only",
    }


def _persistence(*, active: bool = True, authorization: object = object(), partition: object = object()):
    project_dataset_activations = Mock()
    project_dataset_activations.get_project_state.return_value = {
        "active_selection": (
            {
                "activation_status": "active",
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                "activation_revision": 3,
            }
            if active
            else None
        )
    }
    predictor_authorizations = Mock()
    predictor_authorizations.get_current_exact.return_value = (
        {"manifest_json": _manifest()} if not isinstance(authorization, type(None)) else None
    )
    analysis_partitions = Mock()
    analysis_partitions.get_current_exact.return_value = (
        _partition() if not isinstance(partition, type(None)) else None
    )
    return SimpleNamespace(
        project_dataset_activations=project_dataset_activations,
        predictor_authorizations=predictor_authorizations,
        analysis_partitions=analysis_partitions,
    )


def _call(persistence):
    with (
        patch.object(metadata_router, "authorize_modeling_scope", return_value=PROJECT_ID),
        patch.object(metadata_router, "get_persistence_service", return_value=persistence),
        patch.object(metadata_router, "durable_active_dataset_identity", return_value=_identity()),
        patch.object(metadata_router, "verify_durable_predictor_authorization", return_value=_manifest()),
        patch.object(analysis_partition_service, "current", return_value=_partition()) as current,
        patch.object(analysis_partition_service, "target_authority_compatibility", return_value={}),
    ):
        response = metadata_router.get_reproducibility_context(
            PROJECT_ID,
            {"userId": "isolated-repro-user"},
        )
    return response, current


def _all_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _all_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_keys(child)


def test_exact_current_context_is_metadata_only_and_never_falls_back():
    persistence = _persistence()
    response, current = _call(persistence)

    assert response["state"] == "current"
    assert response["identity"] == {
        "project_id": PROJECT_ID,
        "dataset_name": "Repro Safety Dataset",
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "dataset_version_label": "Version 1",
        "source_type": "registered_upload",
        "activation_revision": 3,
        "governed_population_rows": 120,
        "source_columns": 5,
    }
    assert response["target_contract"]["target"] == "outcome"
    assert response["predictor_authorization"]["authorized_predictors"] == [
        "feature_a",
        "feature_b",
    ]
    assert response["predictor_authorization"]["funnel"] == {
        "source_column_count": 5,
        "target_exclusions": [
            {
                "field": "outcome",
                "reason": "Selected modeling outcome; never authorized as a predictor",
            }
        ],
        "candidate_predictor_count": 4,
        "selected_predictor_count": 2,
        "authorized_predictor_count": 2,
        "additional_exclusions": {
            "source_outcome": "Not selected in the governed predictor manifest",
            "atlas_split": "Split or fold metadata cannot be used as a predictor",
        },
        "model_ready_status": "not_established_in_data_acquisition",
    }
    assert response["analysis_partition"]["development_rows"] == 96
    assert response["analysis_partition"]["sealed_holdout_rows"] == 24
    assert response["authority"] == {
        "binding": "exact_registered_version",
        "fallback_used": False,
        "browser_state_authoritative": False,
        "row_data_included": False,
        "assignments_included": False,
        "target_aggregates_included": False,
        "final_holdout_access": "protected_metadata_only",
    }
    keys = set(_all_keys(response))
    assert "artifact_path" not in keys
    assert "row_assignments_json" not in keys
    assert "event_counts_json" not in keys
    assert "assignment_hash" not in keys
    assert "artifact_hash" not in keys
    persistence.predictor_authorizations.get_current_exact.assert_called_once_with(
        PROJECT_ID,
        DATASET_ID,
        VERSION_ID,
    )
    persistence.analysis_partitions.get_current_exact.assert_called_once_with(
        PROJECT_ID,
        DATASET_ID,
        VERSION_ID,
    )
    current.assert_called_once_with(
        PROJECT_ID,
        DATASET_ID,
        VERSION_ID,
        target="outcome",
        target_contract_id=TARGET_CONTRACT_ID,
        predictor_authorization_id=AUTHORIZATION_ID,
    )


def test_pending_states_publish_no_stale_subordinate_contract():
    identity_pending, _ = _call(_persistence(active=False))
    assert identity_pending["state"] == "identity_pending"
    assert identity_pending["identity"] is None
    assert identity_pending["target_contract"] is None

    target_pending, _ = _call(_persistence(authorization=None))
    assert target_pending["state"] == "target_pending"
    assert target_pending["identity"]["dataset_version_id"] == VERSION_ID
    assert target_pending["target_contract"] is None
    assert target_pending["analysis_partition"] is None

    partition_pending, _ = _call(_persistence(partition=None))
    assert partition_pending["state"] == "partition_pending"
    assert partition_pending["target_contract"]["target"] == "outcome"
    assert partition_pending["predictor_authorization"][
        "predictor_authorization_id"
    ] == AUTHORIZATION_ID
    assert partition_pending["analysis_partition"] is None
