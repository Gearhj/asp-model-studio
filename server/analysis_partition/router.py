from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any, Dict

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.dataset_store import DATASTORE
from ..core.result_store import RESULTS
from ..core.pretraining_invalidation import invalidate_downstream_training_state
from ..core.modeling_scope import authorize_modeling_scope
from ..datasets.dataset_identity import assert_expected_active_identity
from ..preprocessing.predictor_authorization import (
    PredictorAuthorizationIntegrityError,
    verify_durable_predictor_authorization,
)
from ..security.security_store import require_user
from ..security.security_store import audit_event
from ..persistence.db import json_dumps, now_iso
from ..persistence.repositories.analysis_partition_repository import (
    AnalysisPartitionConflictError,
)
from ..persistence.service import get_persistence_service
from .service import analysis_partition_service
from .types import (
    AnalysisPartitionConfirmRequest,
    AnalysisPartitionDocumentationRequest,
    AnalysisPartitionError,
    AnalysisPartitionInvalidationRequest,
    AnalysisPartitionPreviewRequest,
    AnalysisPartitionResetPreviewRequest,
)


router = APIRouter()


def _atomic_restore(path: Path, payload: bytes | None) -> None:
    """Restore one snapshotted file without exposing a partial write."""

    if payload is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".compensate", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_frame(value: Any) -> Any:
    return value.copy(deep=True) if hasattr(value, "copy") else value


def _runtime_artifact_id(key: str, value: Any) -> str:
    if isinstance(value, dict):
        for candidate in (
            "feature_manifest_id", "manifest_hash", "manifest_version",
            "validation_design_id", "split_id", "training_job_id",
            "training_run_id", "candidate_contract_id", "candidate_decision_id",
            "evaluation_package_id", "model_version_id", "scoring_run_id",
            "id", "artifact_id",
        ):
            if str(value.get(candidate) or "").strip():
                return str(value[candidate])
    digest = hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    return f"runtime-{key}-{digest}"


def _external_inventory(store: Any, results: Any) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []

    def add(
        artifact_type: str,
        key: str,
        value: Any,
        *,
        source: str = "runtime:dataset_store",
        status: str = "current",
    ) -> None:
        if value in (None, "", {}, []):
            return
        inventory.append(
            {
                "artifact_type": artifact_type,
                "artifact_id": _runtime_artifact_id(key, value),
                "source_authority": source,
                "prior_status": status,
                "invalidation_status": "invalidated",
                "metadata": {"runtime_key": key},
            }
        )

    meta_types = {
        "outlier_application": "outlier_treatment",
        "missing_application": "missing_value_treatment",
        "missing_validation": "missing_value_validation",
        "feature_manifest": "feature_manifest",
        "feature_preview": "feature_preview",
        "validation_design": "validation_design",
        "split_record": "validation_split",
        "training_execution": "training_execution",
        "training_model_portfolio": "training_candidate_portfolio",
        "training_preflight": "training_preflight",
        "model_selection_decision": "candidate_decision",
        "active_training_job_id": "training_job",
    }
    for key, artifact_type in meta_types.items():
        add(artifact_type, key, store.meta.get(key))
    add("training_summary", "last_training_summary", results.last_training_summary, source="runtime:result_store")
    add("model_artifact_inventory", "model_artifacts", results.model_artifact_metadata or results.model_artifacts, source="runtime:result_store")
    add("final_model", "final_model_metadata", results.final_model_metadata, source="runtime:result_store")
    add("scoring_reference", "scoring_reference", results.scoring_reference, source="runtime:result_store")
    for package_id, package in sorted((results.evaluation_packages or {}).items()):
        add(
            "evaluation_package",
            str(package_id),
            {"evaluation_package_id": package_id, **(package or {})},
            source="runtime:result_store",
            status=str((package or {}).get("status") or "complete"),
        )
    for candidate_id, evaluation in sorted((results.holdout_evaluations or {}).items()):
        add(
            "holdout_evaluation",
            str(candidate_id),
            {"id": candidate_id, **(evaluation or {})},
            source="runtime:result_store",
            status=str((evaluation or {}).get("status") or "current"),
        )
    for record_id, record in sorted((results.selection_integrity_records or {}).items()):
        add(
            "candidate_contract",
            str(record_id),
            {"id": record_id, **(record or {})},
            source="runtime:result_store",
            status=str((record or {}).get("status") or "current"),
        )
    return inventory


class _NoopHoldoutGovernance:
    """Keep durable holdout invalidation inside the partition transaction."""

    @staticmethod
    def invalidate_holdout_exposure_for_partition(**_kwargs: Any) -> None:
        return None


class _PartitionDerivativeTransition:
    def __init__(
        self,
        *,
        store: Any,
        results: Any,
        file_snapshots: dict[Path, bytes | None],
        inventory: list[dict[str, Any]],
    ) -> None:
        self.store = store
        self.results = results
        self.file_snapshots = dict(file_snapshots)
        self.inventory = list(inventory)
        self._compensated = False
        self._store_snapshot = {
            "processed_df": _copy_frame(store.processed_df),
            "X_train": _copy_frame(store.X_train),
            "X_test": _copy_frame(store.X_test),
            "y_train": _copy_frame(store.y_train),
            "y_test": _copy_frame(store.y_test),
            "meta": copy.deepcopy(store.meta),
            "data_revision": int(store.data_revision),
        }
        self._result_snapshot = {
            "last_training_summary": copy.deepcopy(results.last_training_summary),
            "training_timestamp": results.training_timestamp,
            "model_availability": copy.deepcopy(results.model_availability),
            "model_artifacts": dict(results.model_artifacts),
            "model_artifact_metadata": copy.deepcopy(results.model_artifact_metadata),
            "final_model": results.final_model,
            "final_model_metadata": copy.deepcopy(results.final_model_metadata),
            "scoring_reference": copy.deepcopy(results.scoring_reference),
            "evaluation_packages": copy.deepcopy(results.evaluation_packages),
            "holdout_evaluations": copy.deepcopy(results.holdout_evaluations),
            "selection_integrity_records": copy.deepcopy(
                results.selection_integrity_records
            ),
        }

    def compensate(self) -> None:
        if self._compensated:
            return
        for path, payload in self.file_snapshots.items():
            _atomic_restore(path, payload)
        self.store.processed_df = self._store_snapshot["processed_df"]
        self.store.X_train = self._store_snapshot["X_train"]
        self.store.X_test = self._store_snapshot["X_test"]
        self.store.y_train = self._store_snapshot["y_train"]
        self.store.y_test = self._store_snapshot["y_test"]
        self.store.meta.clear()
        self.store.meta.update(copy.deepcopy(self._store_snapshot["meta"]))
        self.store.data_revision = int(self._store_snapshot["data_revision"])
        with self.results.state_lock:
            for key, value in self._result_snapshot.items():
                setattr(self.results, key, value)
        self._compensated = True


def _preview_derivative_inventory(
    record: Dict[str, Any], store: Any, results: Any
) -> list[dict[str, Any]]:
    """Read-only exact affected-artifact inventory for reset preflight."""

    from ..eda.documentation_service import eda_documentation_service
    from ..features.feature_manifest_store import _identity_dir

    inventory = _external_inventory(store, results)
    eda_preflight = eda_documentation_service.preflight_invalidation(
        str(record.get("project_id") or ""),
        expected_dataset_id=str(record.get("dataset_id") or ""),
        expected_dataset_version_id=str(record.get("dataset_version_id") or ""),
    )
    confirmation_id = str(eda_preflight.get("current_confirmation_id") or "").strip()
    if confirmation_id:
        inventory.append(
            {
                "artifact_type": "eda_confirmation",
                "artifact_id": confirmation_id,
                "source_authority": "file:eda_documentation",
                "prior_status": "confirmed",
                "invalidation_status": "invalidated",
                "metadata": {"project_id": record.get("project_id")},
            }
        )
    identity = {
        "project_id": record.get("project_id"),
        "dataset_id": record.get("dataset_id"),
        "dataset_version_id": record.get("dataset_version_id"),
    }
    feature_path = _identity_dir(identity) / "current.json"
    if feature_path.exists():
        feature_record = json.loads(feature_path.read_text(encoding="utf-8"))
        manifest_hash = str(feature_record.get("manifest_hash") or "").strip()
        if manifest_hash:
            inventory.append(
                {
                    "artifact_type": "feature_manifest",
                    "artifact_id": manifest_hash,
                    "source_authority": "file:feature_manifest",
                    "prior_status": str(
                        ((feature_record.get("manifest") or {}).get("materialization_status"))
                        or "current"
                    ),
                    "invalidation_status": "invalidated",
                    "metadata": {
                        "definition_checksum": feature_record.get("definition_checksum")
                    },
                }
            )
    return analysis_partition_service.repository.inventory_downstream(
        record, external_inventory=inventory
    )


def _canonical_contract_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    try:
        if bool(pd.isna(value)):
            return "__missing__"
    except (TypeError, ValueError):
        pass
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        default=str,
    )


def _authoritative_partition_request(
    payload: Any,
    user: Dict[str, Any],
    *,
    permission: str,
    publish_authority: bool = False,
) -> tuple[Any, Dict[str, Any], Dict[str, Any]]:
    """Resolve one exact durable dataset/target/predictor authority snapshot."""

    values = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    project_id = str(values.get("project_id") or "").strip()
    dataset_id = str(values.get("dataset_id") or "").strip()
    dataset_version_id = str(values.get("dataset_version_id") or "").strip()
    authorize_modeling_scope(user, project_id, permission)
    store = DATASTORE.current()
    identity = assert_expected_active_identity(
        project_id,
        expected_dataset_id=dataset_id,
        expected_dataset_version_id=dataset_version_id,
        require_expected=True,
        user=user,
        store=store,
    )
    if int(identity.get("activation_revision") or 0) <= 0:
        raise AnalysisPartitionError(
            "dataset_identity_unavailable",
            "The exact Dataset Library version does not have a positive durable activation revision.",
            recovery="Explicitly activate the exact registered dataset version before continuing.",
            identifiers={
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
            },
        )

    persistence = get_persistence_service()
    authorization_record = persistence.predictor_authorizations.get_current_exact(
        project_id,
        dataset_id,
        dataset_version_id,
    )
    try:
        manifest = verify_durable_predictor_authorization(
            authorization_record,
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
        )
    except PredictorAuthorizationIntegrityError as exc:
        raise AnalysisPartitionError(
            "predictor_authorization_required",
            "The exact durable predictor authorization failed integrity verification.",
            recovery="Reconfirm Data Acquisition for the exact active Dataset Library version.",
            identifiers={
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
            },
        ) from exc

    frame = getattr(store, "raw_df", None)
    target = str(manifest.get("target") or "").strip()
    if not isinstance(frame, pd.DataFrame) or frame.empty or target not in frame.columns:
        raise AnalysisPartitionError(
            "target_contract_stale",
            "The verified target is unavailable in the exact active Dataset Library artifact.",
            recovery="Reopen Data Acquisition and reconfirm the target contract.",
            identifiers={
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "target": target,
            },
        )

    positive_value = manifest.get("positive_value")
    negative_value = manifest.get("negative_value")
    if positive_value is None and negative_value is None:
        problem_type = "regression"
    elif (
        positive_value is not None
        and negative_value is not None
        and _canonical_contract_scalar(positive_value)
        != _canonical_contract_scalar(negative_value)
    ):
        problem_type = "classification"
    else:
        raise AnalysisPartitionError(
            "target_contract_stale",
            "The durable target mapping cannot establish a verified supervised problem type.",
            recovery="Reconfirm a complete classification mapping or a numeric regression target.",
            identifiers={
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "target": target,
            },
        )
    if problem_type == "regression":
        numeric = pd.to_numeric(frame[target], errors="coerce").astype(float)
        finite_count = int(np.isfinite(numeric.to_numpy(dtype=float, copy=False)).sum())
        if finite_count < 2:
            raise AnalysisPartitionError(
                "target_contract_stale",
                "The durable target contract does not identify a usable numeric regression outcome.",
                recovery="Correct the target definition in Data Acquisition.",
                identifiers={"project_id": project_id, "target": target},
            )

    authority = {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "target_contract_id": str(manifest.get("target_contract_id") or "").strip(),
        "target": target,
        "positive_value": positive_value,
        "negative_value": negative_value,
        "predictor_authorization_id": str(
            manifest.get("predictor_authorization_id") or ""
        ).strip(),
        "problem_type": problem_type,
    }
    text_fields = (
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "target_contract_id",
        "target",
        "predictor_authorization_id",
        "problem_type",
    )
    for field in text_fields:
        supplied = str(values.get(field) or "").strip()
        if supplied and supplied != str(authority[field]):
            raise AnalysisPartitionError(
                "target_contract_stale"
                if field in {"target", "target_contract_id", "problem_type"}
                else "predictor_authorization_required"
                if field == "predictor_authorization_id"
                else "dataset_identity_unavailable",
                f"The requested {field} contradicts the exact durable Data Acquisition authority.",
                recovery="Reload Data Acquisition and use the backend-authoritative contract.",
                identifiers={
                    "project_id": project_id,
                    "field": field,
                    "supplied": supplied,
                    "authoritative": authority[field],
                },
            )
    for field in ("positive_value", "negative_value"):
        if field in values and _canonical_contract_scalar(values.get(field)) != _canonical_contract_scalar(
            authority[field]
        ):
            raise AnalysisPartitionError(
                "target_contract_stale",
                f"The requested {field} contradicts the durable target mapping.",
                recovery="Reload Data Acquisition and use the backend-authoritative target mapping.",
                identifiers={"project_id": project_id, "field": field},
            )

    authorized_predictors = [
        str(value).strip()
        for value in manifest.get("authorized_predictors", [])
        if str(value).strip()
    ]
    missing_predictors = sorted(
        {name for name in authorized_predictors if name not in frame.columns}
    )
    if missing_predictors:
        raise AnalysisPartitionError(
            "predictor_authorization_required",
            "The durable predictor authorization references fields absent from the exact registered artifact.",
            recovery="Reconfirm Data Acquisition for this exact version.",
            identifiers={
                "project_id": project_id,
                "missing_authorized_predictors": missing_predictors,
            },
        )

    calculation_store = store if publish_authority else copy.copy(store)
    if not publish_authority:
        calculation_store.meta = dict(store.meta)
    with calculation_store.state_lock:
        calculation_store.set_target(target)
        calculation_store.meta["target_contract_id"] = authority["target_contract_id"]
        calculation_store.meta["predictor_authorization_id"] = authority[
            "predictor_authorization_id"
        ]
        calculation_store.meta["predictor_authorization"] = dict(manifest)
        calculation_store.meta["predictor_authorization_manifest"] = dict(manifest)
        calculation_store.meta["selected_columns"] = authorized_predictors
        calculation_store.meta["event_value"] = positive_value
        calculation_store.meta["non_event_value"] = negative_value
        calculation_store.meta["problem_type"] = problem_type

    return calculation_store, {**values, **authority}, identity


def _authorize_partition_documentation_retry(
    request: AnalysisPartitionDocumentationRequest,
    user: Dict[str, Any],
) -> tuple[Any, Dict[str, Any]]:
    """Authorize exact documentation recovery without loading target values."""

    authorize_modeling_scope(user, request.project_id, "edit")
    store = DATASTORE.current()
    identity = assert_expected_active_identity(
        request.project_id,
        expected_dataset_id=request.dataset_id,
        expected_dataset_version_id=request.dataset_version_id,
        require_expected=True,
        user=user,
        store=store,
    )
    if int(identity.get("activation_revision") or 0) <= 0:
        raise AnalysisPartitionError(
            "dataset_identity_unavailable",
            "The exact Dataset Library version does not have a positive durable activation revision.",
            recovery="Explicitly activate the exact registered dataset version before retrying documentation.",
            identifiers={
                "project_id": request.project_id,
                "dataset_id": request.dataset_id,
                "dataset_version_id": request.dataset_version_id,
            },
        )

    persistence = get_persistence_service()
    authorization_record = persistence.predictor_authorizations.get_current_exact(
        request.project_id,
        request.dataset_id,
        request.dataset_version_id,
    )
    try:
        manifest = verify_durable_predictor_authorization(
            authorization_record,
            project_id=request.project_id,
            dataset_id=request.dataset_id,
            dataset_version_id=request.dataset_version_id,
        )
    except PredictorAuthorizationIntegrityError as exc:
        raise AnalysisPartitionError(
            "predictor_authorization_required",
            "The exact durable predictor authorization failed integrity verification.",
            recovery="Reconfirm Data Acquisition for the exact active Dataset Library version.",
            identifiers={
                "project_id": request.project_id,
                "dataset_id": request.dataset_id,
                "dataset_version_id": request.dataset_version_id,
            },
        ) from exc

    authority = {
        "target": str(manifest.get("target") or "").strip(),
        "target_contract_id": str(
            manifest.get("target_contract_id") or ""
        ).strip(),
        "predictor_authorization_id": str(
            manifest.get("predictor_authorization_id") or ""
        ).strip(),
    }
    for field, supplied in (
        ("target", request.target),
        ("target_contract_id", request.target_contract_id),
        ("predictor_authorization_id", request.predictor_authorization_id),
    ):
        if supplied != authority[field]:
            raise AnalysisPartitionError(
                (
                    "predictor_authorization_required"
                    if field == "predictor_authorization_id"
                    else "target_contract_stale"
                ),
                f"The requested {field} contradicts the exact durable Data Acquisition authority.",
                recovery="Reload Data Acquisition and retry against the exact displayed partition contract.",
                identifiers={
                    "project_id": request.project_id,
                    "field": field,
                },
            )

    record = analysis_partition_service.current(
        request.project_id,
        request.dataset_id,
        request.dataset_version_id,
        target=authority["target"],
        target_contract_id=authority["target_contract_id"],
        predictor_authorization_id=authority["predictor_authorization_id"],
    )
    # A checksum-valid historical row is not automatically target authority.
    # Resolve native-v2 or integrity-gated legacy-v1 semantics without loading
    # any target values before allowing documentation sidecars to be written.
    analysis_partition_service.target_authority_compatibility(record)
    if (
        str(record.get("analysis_partition_id") or "")
        != request.analysis_partition_id
        or int(record.get("revision") or 0) != request.revision
    ):
        raise AnalysisPartitionError(
            "analysis_partition_contradictory",
            "The exact current Analysis Partition changed before documentation recovery began.",
            recovery="Reload Data Acquisition and retry only against the newly displayed partition ID and revision.",
            identifiers={
                "project_id": request.project_id,
                "analysis_partition_id": request.analysis_partition_id,
                "revision": request.revision,
            },
        )
    return store, record


def _documentation_identity(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "analysis_partition_id": str(record.get("analysis_partition_id") or ""),
        "project_id": str(record.get("project_id") or ""),
        "dataset_id": str(record.get("dataset_id") or ""),
        "dataset_version_id": str(record.get("dataset_version_id") or ""),
        "revision": int(record.get("revision") or 0),
        "assignment_hash": str(record.get("assignment_hash") or ""),
        "artifact_hash": str(record.get("artifact_hash") or ""),
    }


def _raise_documentation_contradiction(
    expected: Dict[str, Any], current: Dict[str, Any] | None = None
) -> None:
    current_identity = _documentation_identity(current or {})
    raise AnalysisPartitionError(
        "analysis_partition_contradictory",
        "The exact current Analysis Partition changed while documentation was being completed.",
        recovery=(
            "Reload Data Acquisition and retry documentation only against the "
            "newly displayed current partition ID and revision."
        ),
        identifiers={
            "project_id": expected.get("project_id"),
            "analysis_partition_id": expected.get("analysis_partition_id"),
            "revision": expected.get("revision"),
            "current_analysis_partition_id": current_identity.get(
                "analysis_partition_id"
            ),
            "current_revision": current_identity.get("revision"),
        },
    )


def _require_exact_current_documentation_partition(
    expected: Dict[str, Any],
) -> Dict[str, Any]:
    repository = analysis_partition_service.repository
    current = repository.get_current_exact(
        str(expected.get("project_id") or ""),
        str(expected.get("dataset_id") or ""),
        str(expected.get("dataset_version_id") or ""),
    )
    if current is None or _documentation_identity(current) != _documentation_identity(
        expected
    ):
        _raise_documentation_contradiction(expected, current)
    return analysis_partition_service._validate_integrity(current)


def _update_documentation_status_exact(
    expected: Dict[str, Any],
    *,
    evidence_status: str,
    evidence_ref: str,
    mdd_status: str,
    mdd_ref: str,
) -> Dict[str, Any]:
    try:
        return analysis_partition_service.repository.update_documentation_status(
            str(expected.get("analysis_partition_id") or ""),
            expected_current=expected,
            evidence_status=evidence_status,
            evidence_ref=evidence_ref,
            mdd_status=mdd_status,
            mdd_ref=mdd_ref,
        )
    except AnalysisPartitionConflictError as exc:
        _raise_documentation_contradiction(expected, exc.current)
    raise AssertionError("unreachable")


def _record_partition_evidence(
    result: Dict[str, Any],
    user: Dict[str, Any],
    *,
    audit_action: str = "modeling.analysis_partition.confirmed",
) -> str:
    partition = result.get("analysis_partition")
    if not isinstance(partition, dict) or not partition.get(
        "analysis_partition_id"
    ):
        return ""
    timestamp = now_iso()
    project_id = str(partition.get("project_id") or "")
    partition_id = str(partition["analysis_partition_id"])
    persistence = get_persistence_service()
    persistence.ensure_project(project_id, user)
    evidence_id = f"ev-{partition_id}"
    incoming_preview = (
        result.get("preview") if isinstance(result.get("preview"), dict) else {}
    )
    existing_evidence = persistence.evidence.get(evidence_id)
    existing_payload = (
        existing_evidence.get("payload_json")
        if isinstance(existing_evidence, dict)
        and isinstance(existing_evidence.get("payload_json"), dict)
        else {}
    )
    existing_preview = (
        existing_payload.get("partition_preview")
        if isinstance(existing_payload.get("partition_preview"), dict)
        else {}
    )
    # A service-level idempotent replay intentionally returns an abbreviated
    # preview.  Do not overwrite the original creation decision evidence with
    # that abbreviated status object after a partial documentation failure.
    creation_preview = (
        existing_preview
        if existing_preview
        and not any(
            key in incoming_preview
            for key in (
                "class_counts",
                "full_target_summary",
                "holdout_target_summary",
            )
        )
        else incoming_preview
    )
    persistence.evidence.upsert(
        {
            "evidence_id": evidence_id,
            "project_id": project_id,
            "workflow_type": "predictive_modeling",
            "step_id": "step01",
            "artifact_type": "analysis_partition",
            "status": "approved",
            "title": "Sealed Analysis Partition",
            "summary": (
                f"Development {partition.get('development_count')} rows; "
                f"sealed final holdout {partition.get('holdout_count')} rows; "
                f"revision {partition.get('revision')}."
            ),
            "source_ref": partition_id,
            "artifact_hash": partition.get("artifact_hash"),
            "created_by": str(user.get("userId") or "atlas-user"),
            "created_at": partition.get("created_at") or timestamp,
            "captured_at": timestamp,
            "approved_at": timestamp,
            "payload_json": {
                **partition,
                "partition_preview": creation_preview,
                "workflow_step": "step01",
                "analysis_scope": "development_population",
                "final_holdout_accessed": False,
                "final_holdout_used_for_selection": False,
                "governance_statement": (
                    "Target-directed EDA is authorized only for the exact "
                    "development partition; final holdout membership is sealed."
                ),
            },
        }
    )
    recorded_evidence = persistence.evidence.get(evidence_id)
    if (
        not isinstance(recorded_evidence, dict)
        or str(recorded_evidence.get("source_ref") or "") != partition_id
        or str(recorded_evidence.get("artifact_hash") or "")
        != str(partition.get("artifact_hash") or "")
    ):
        raise RuntimeError(
            "The exact Analysis Partition evidence failed durable read-back verification."
        )
    audit_event(
        audit_action,
        "project",
        project_id,
        "success",
        metadata={
            "analysisPartitionId": partition_id,
            "revision": partition.get("revision"),
            "datasetId": partition.get("dataset_id"),
            "datasetVersionId": partition.get("dataset_version_id"),
            "developmentPartitionId": partition.get(
                "development_partition_id"
            ),
            "sealedHoldoutPartitionId": partition.get(
                "sealed_holdout_partition_id"
            ),
            "reused": bool(result.get("reused")),
        },
        user_id=user.get("userId"),
    )
    return evidence_id


def _record_partition_mdd(
    result: Dict[str, Any],
    user: Dict[str, Any],
    evidence_ref: str,
    *,
    include_target_distribution: bool = True,
    accept_existing_exact_content: bool = False,
) -> str:
    """Create one idempotent Data Acquisition-owned MDD data section."""

    partition = result.get("analysis_partition")
    if not isinstance(partition, dict) or not partition.get(
        "analysis_partition_id"
    ):
        return ""
    project_id = str(partition.get("project_id") or "")
    partition_id = str(partition["analysis_partition_id"])
    digest = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:20]
    document_id = f"mdd-document-{digest}"
    version_id = f"mdd-version-{partition_id}"
    section_id = f"mdd-section-{partition_id}"
    block_id = f"mdd-block-{partition_id}"
    evidence_link_id = f"mdd-evidence-link-{partition_id}"
    timestamp = now_iso()
    actor = str(user.get("userId") or "atlas-user")
    persistence = get_persistence_service()
    persistence.ensure_project(project_id, user)
    evidence = persistence.evidence.get(evidence_ref) if evidence_ref else None
    evidence_payload = (
        evidence.get("payload_json")
        if isinstance(evidence, dict)
        and isinstance(evidence.get("payload_json"), dict)
        else {}
    )
    durable_partition = persistence.analysis_partitions.get(partition_id) or {}
    content = persistence.analysis_partitions.build_mdd_content(
        durable_partition or partition,
        evidence_ref,
        evidence_payload,
        include_target_distribution=include_target_distribution,
    )
    with persistence.database.transaction() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO mdd_documents (
              mdd_document_id, project_id, template_version_id,
              current_validated_version_id, created_by_user_id, created_at,
              updated_at, metadata_json
            ) VALUES (?, ?, NULL, NULL, ?, ?, ?, ?)
            """,
            (
                document_id,
                project_id,
                actor,
                timestamp,
                timestamp,
                json_dumps({"source": "analysis_partition"}, {}),
            ),
        )
        connection.execute(
            "UPDATE mdd_documents SET updated_at = ? WHERE mdd_document_id = ?",
            (timestamp, document_id),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO mdd_document_versions (
              mdd_document_version_id, mdd_document_id, version_number,
              status, prior_validated_version_id, summary_of_changes,
              created_by_user_id, created_at, submitted_at, metadata_json
            ) VALUES (?, ?, ?, 'working_draft', NULL, ?, ?, ?, NULL, ?)
            """,
            (
                version_id,
                document_id,
                f"analysis-partition-r{partition.get('revision')}",
                "Data Acquisition Analysis Partition recorded.",
                actor,
                timestamp,
                json_dumps(
                    {
                        "analysis_partition_id": partition_id,
                        "evidence_ref": evidence_ref,
                    },
                    {},
                ),
            ),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO mdd_sections (
              mdd_section_id, mdd_document_version_id, section_id,
              section_number, title, status, not_applicable_rationale,
              metadata_json
            ) VALUES (?, ?, 'data.analysis_partition', '3.2', ?,
                      'working_draft', NULL, ?)
            """,
            (
                section_id,
                version_id,
                "Development and Final Evaluation Populations",
                json_dumps({"owner_step": "step01"}, {}),
            ),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO mdd_content_blocks (
              block_id, mdd_section_id, block_type, title, content_json,
              source_type, source_reference_json, generated_indicator,
              review_status, created_by_user_id, created_at, updated_at,
              metadata_json
            ) VALUES (?, ?, 'structured_data', ?, ?, 'evidence', ?,
                      'system_generated', 'draft', ?, ?, ?, ?)
            """,
            (
                block_id,
                section_id,
                "Sealed Analysis Partition",
                json_dumps(content, {}),
                json_dumps(
                    {
                        "analysis_partition_id": partition_id,
                        "evidence_id": evidence_ref,
                    },
                    {},
                ),
                actor,
                timestamp,
                timestamp,
                json_dumps({"owner_step": "step01"}, {}),
            ),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO mdd_evidence_links (
              mdd_evidence_link_id, mdd_section_id,
              evidence_reference_json, canonical_version_reference,
              created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_link_id,
                section_id,
                json_dumps({"evidence_id": evidence_ref}, {}),
                partition_id,
                timestamp,
                json_dumps({"owner_step": "step01"}, {}),
            ),
        )
        section_row = connection.execute(
            "SELECT mdd_section_id FROM mdd_sections WHERE mdd_section_id = ? AND mdd_document_version_id = ?",
            (section_id, version_id),
        ).fetchone()
        block_row = connection.execute(
            "SELECT content_json FROM mdd_content_blocks WHERE block_id = ? AND mdd_section_id = ?",
            (block_id, section_id),
        ).fetchone()
        link_row = connection.execute(
            "SELECT canonical_version_reference FROM mdd_evidence_links WHERE mdd_evidence_link_id = ? AND mdd_section_id = ?",
            (evidence_link_id, section_id),
        ).fetchone()
        if (
            section_row is None
            or block_row is None
            or link_row is None
            or str(link_row["canonical_version_reference"] or "")
            != partition_id
        ):
            raise RuntimeError(
                "The exact Analysis Partition MDD section failed durable read-back verification."
            )
    verification_record = {
        **dict(durable_partition or partition),
        "evidence_status": "recorded",
        "evidence_ref": evidence_ref,
        "mdd_status": "recorded",
        "mdd_ref": section_id,
    }
    readiness = persistence.analysis_partitions.documentation_readiness(
        verification_record
    )
    if not readiness.get("evidence_ready") or not readiness.get("mdd_ready"):
        raise RuntimeError(
            "The exact Analysis Partition MDD section failed durable content and evidence verification."
        )
    return section_id


def _invalidate_partition_derivatives(
    request: Any, user: Dict[str, Any]
) -> _PartitionDerivativeTransition | None:
    if not request.reset_existing:
        return None
    store = DATASTORE.current()
    results = RESULTS.current()
    with store.state_lock:
        # Validate the exact current authority and the file-backed EDA scope
        # before changing any derivative.  The replacement partition is not
        # persisted until this entire callback returns successfully.
        analysis_partition_service.current(
            request.project_id,
            request.dataset_id,
            request.dataset_version_id,
            target=request.target,
            target_contract_id=request.target_contract_id,
            predictor_authorization_id=request.predictor_authorization_id,
        )
        from ..eda.documentation_service import eda_documentation_service
        from ..features.feature_manifest_store import _atomic_write, _identity_dir

        eda_preflight = eda_documentation_service.preflight_invalidation(
            request.project_id,
            expected_dataset_id=request.dataset_id,
            expected_dataset_version_id=request.dataset_version_id,
        )
        eda_path = eda_documentation_service._path(request.project_id)
        identity = {
            "project_id": request.project_id,
            "dataset_id": request.dataset_id,
            "dataset_version_id": request.dataset_version_id,
        }
        feature_path = _identity_dir(identity) / "current.json"
        file_snapshots = {
            eda_path: eda_path.read_bytes() if eda_path.exists() else None,
            feature_path: feature_path.read_bytes() if feature_path.exists() else None,
        }
        inventory = _external_inventory(store, results)
        confirmation_id = str(
            eda_preflight.get("current_confirmation_id") or ""
        ).strip()
        if confirmation_id:
            inventory.append(
                {
                    "artifact_type": "eda_confirmation",
                    "artifact_id": confirmation_id,
                    "source_authority": "file:eda_documentation",
                    "prior_status": "confirmed",
                    "invalidation_status": "invalidated",
                    "metadata": {"project_id": request.project_id},
                }
            )
        feature_record: dict[str, Any] | None = None
        if feature_path.exists():
            feature_record = json.loads(feature_path.read_text(encoding="utf-8"))
            if any(
                str(feature_record.get(key) or "") != str(identity[key])
                for key in ("project_id", "dataset_id", "dataset_version_id")
            ):
                raise RuntimeError(
                    "The durable Feature Manifest current pointer does not match the exact reset scope."
                )
            manifest_hash = str(feature_record.get("manifest_hash") or "").strip()
            if not manifest_hash:
                raise RuntimeError(
                    "The durable Feature Manifest current pointer has no exact manifest hash."
                )
            inventory.append(
                {
                    "artifact_type": "feature_manifest",
                    "artifact_id": manifest_hash,
                    "source_authority": "file:feature_manifest",
                    "prior_status": str(
                        ((feature_record.get("manifest") or {}).get("materialization_status"))
                        or "current"
                    ),
                    "invalidation_status": "invalidated",
                    "metadata": {"definition_checksum": feature_record.get("definition_checksum")},
                }
            )
        transition = _PartitionDerivativeTransition(
            store=store,
            results=results,
            file_snapshots=file_snapshots,
            inventory=inventory,
        )
        reason = (
            "The Analysis Partition was explicitly reset; target-directed EDA "
            "and downstream artifacts are stale."
        )
        actor = str(user.get("userId") or "atlas-user")
        try:
            invalidate_downstream_training_state(
                reason,
                store=store,
                result_store=results,
                split_status="not_created",
                invalidated_by=actor,
                governance_repository=_NoopHoldoutGovernance(),
            )
            # Runtime Evaluation/candidate packages are caches of immutable
            # durable evidence. Clearing the cache prevents them from remaining
            # current; the durable records and reset ledger preserve history.
            with results.state_lock:
                results.evaluation_packages = {}
                results.selection_integrity_records = {}

            with eda_documentation_service._lock:
                eda_record = eda_documentation_service._read(request.project_id)
                changed = eda_documentation_service._mark_current_stale(
                    eda_record,
                    "The governed Analysis Partition was explicitly reset.",
                    upstream_revision=str(request.expected_current_revision or ""),
                    changed_source_fields=["analysis_partition_revision"],
                    stale_sections=[
                        {
                            "section": "overview",
                            "classification": "analytical",
                            "changed_source_fields": [
                                "analysis_partition_id",
                                "analysis_partition_revision",
                            ],
                        }
                    ],
                )
                if changed:
                    eda_documentation_service._write(eda_record)

            if feature_record is not None:
                feature_manifest = feature_record.get("manifest")
                if not isinstance(feature_manifest, dict):
                    raise RuntimeError(
                        "The durable Feature Manifest current pointer has no manifest payload."
                    )
                feature_manifest["materialization_status"] = "stale"
                feature_manifest["feature_set_status"] = "stale"
                feature_manifest["split_status"] = "not_created"
                feature_manifest["analysis_partition_status"] = "stale"
                feature_manifest["analysis_partition_invalidation"] = {
                    "prior_analysis_partition_id": request.expected_current_partition_id,
                    "prior_revision": request.expected_current_revision,
                    "reason": request.reset_reason,
                    "invalidated_by": actor,
                    "invalidated_at": now_iso(),
                }
                feature_record["manifest"] = feature_manifest
                feature_record["updated_at"] = now_iso()
                _atomic_write(feature_path, feature_record)

            store.processed_df = None
            for key in (
                "outlier_application",
                "missing_application",
                "missing_config",
                "missing_validation",
                "materialized_feature_names",
                "feature_manifest",
                "feature_preview",
                "training_model_portfolio",
            ):
                store.meta.pop(key, None)
        except Exception:
            transition.compensate()
            raise
        return transition


def _raise_contract_error(exc: AnalysisPartitionError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.as_detail(),
    ) from exc


@router.post("/preview")
def preview_analysis_partition(
    request: AnalysisPartitionPreviewRequest,
    user: Dict[str, Any] = Depends(require_user),
):
    """Return a deterministic, non-mutating preview for the exact authority."""

    try:
        store, authoritative, _identity = _authoritative_partition_request(
            request, user, permission="view"
        )
        with store.state_lock:
            return analysis_partition_service.preview(
                store,
                authoritative,
                enforce_sealed_holdout=True,
            )
    except AnalysisPartitionError as exc:
        _raise_contract_error(exc)


@router.post("/reset-preview")
def reset_preview_analysis_partition(
    request: AnalysisPartitionResetPreviewRequest,
    user: Dict[str, Any] = Depends(require_user),
):
    """Preview one alternate design bound to an exact current partition."""

    try:
        store, authoritative, _identity = _authoritative_partition_request(
            request, user, permission="view"
        )
        with store.state_lock:
            return analysis_partition_service.reset_preview(store, authoritative)
    except AnalysisPartitionError as exc:
        _raise_contract_error(exc)


@router.get("/status")
def analysis_partition_status(
    project_id: str = Query(..., min_length=1),
    dataset_id: str = Query(..., min_length=1),
    dataset_version_id: str = Query(..., min_length=1),
    target: str = Query(default=""),
    target_contract_id: str = Query(default=""),
    predictor_authorization_id: str = Query(default=""),
    user: Dict[str, Any] = Depends(require_user),
):
    """Resolve only the exact current durable Analysis Partition."""

    try:
        store, authoritative, _identity = _authoritative_partition_request(
            {
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "target": target,
                "target_contract_id": target_contract_id,
                "predictor_authorization_id": predictor_authorization_id,
            },
            user,
            permission="view",
        )
        record = analysis_partition_service.current(
            project_id,
            dataset_id,
            dataset_version_id,
            target=authoritative["target"],
            target_contract_id=authoritative["target_contract_id"],
            predictor_authorization_id=authoritative[
                "predictor_authorization_id"
            ],
        )
        # Never present an ambiguous legacy target contract as a current (or
        # documentation-pending) Analysis Partition merely because membership
        # checksums are valid.
        analysis_partition_service.target_authority_compatibility(record)
        safe = analysis_partition_service.publish_safe(store, record)
        documentation = analysis_partition_service.repository.documentation_readiness(
            record
        )
        if not documentation.get("ready"):
            return {
                "ok": True,
                "code": "analysis_partition_documentation_pending",
                "readiness": "documentation_pending",
                "message": (
                    "The exact sealed Analysis Partition is durable, but its evidence "
                    "and MDD documentation are not both durably verified."
                ),
                "recovery": (
                    "Complete Partition Documentation to retry only the missing "
                    "documentation sidecars. Membership will not be recalculated."
                ),
                "analysis_partition": safe,
                "documentation": {
                    **documentation,
                    "readiness": "documentation_pending",
                    "retryable": True,
                },
                "reused": True,
            }
        return {
            "ok": True,
            "code": "analysis_partition_current",
            "readiness": "current",
            "analysis_partition": safe,
            "reused": False,
        }
    except AnalysisPartitionError as exc:
        _raise_contract_error(exc)


@router.post("/complete-documentation")
def complete_analysis_partition_documentation(
    request: AnalysisPartitionDocumentationRequest,
    user: Dict[str, Any] = Depends(require_user),
):
    """Idempotently complete sidecars for one immutable sealed partition."""

    stage = "authorization"
    evidence_ref = ""
    try:
        store, authorized_record = _authorize_partition_documentation_retry(
            request, user
        )
        with analysis_partition_service._project_lock(request.project_id):
            # Re-resolve under the same project lock used by confirmation so a
            # reset cannot race documentation recovery.
            current = analysis_partition_service.current(
                request.project_id,
                request.dataset_id,
                request.dataset_version_id,
                target=request.target,
                target_contract_id=request.target_contract_id,
                predictor_authorization_id=request.predictor_authorization_id,
            )
            analysis_partition_service.target_authority_compatibility(current)
            if (
                str(current.get("analysis_partition_id") or "")
                != request.analysis_partition_id
                or int(current.get("revision") or 0) != request.revision
            ):
                raise AnalysisPartitionError(
                    "analysis_partition_contradictory",
                    "The exact current Analysis Partition changed before documentation recovery acquired its lock.",
                    recovery="Reload Data Acquisition and use the newly displayed partition ID and revision.",
                    identifiers={
                        "project_id": request.project_id,
                        "analysis_partition_id": request.analysis_partition_id,
                        "revision": request.revision,
                    },
                )

            before_identity = {
                "analysis_partition_id": str(
                    current.get("analysis_partition_id") or ""
                ),
                "revision": int(current.get("revision") or 0),
                "artifact_hash": str(current.get("artifact_hash") or ""),
                "assignment_hash": str(current.get("assignment_hash") or ""),
                "row_assignments": json.dumps(
                    current.get("row_assignments_json") or {},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
            if before_identity != {
                "analysis_partition_id": str(
                    authorized_record.get("analysis_partition_id") or ""
                ),
                "revision": int(authorized_record.get("revision") or 0),
                "artifact_hash": str(
                    authorized_record.get("artifact_hash") or ""
                ),
                "assignment_hash": str(
                    authorized_record.get("assignment_hash") or ""
                ),
                "row_assignments": json.dumps(
                    authorized_record.get("row_assignments_json") or {},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }:
                raise AnalysisPartitionError(
                    "analysis_partition_contradictory",
                    "The sealed Analysis Partition changed while documentation recovery was authorized.",
                    recovery="Reload Data Acquisition before retrying documentation.",
                    identifiers={
                        "project_id": request.project_id,
                        "analysis_partition_id": request.analysis_partition_id,
                        "revision": request.revision,
                    },
                )

            readiness = analysis_partition_service.repository.documentation_readiness(
                current
            )
            if readiness.get("ready"):
                safe = analysis_partition_service.publish_safe(store, current)
                return {
                    "ok": True,
                    "code": "analysis_partition_documentation_already_complete",
                    "readiness": "current",
                    "analysis_partition": safe,
                    "documentation": readiness,
                    "reused": True,
                    "partition_mutated": False,
                }

            safe_partition = analysis_partition_service.safe_record(current)
            documentation_result = {
                "ok": True,
                "readiness": "documentation_pending",
                "analysis_partition": safe_partition,
                "preview": {},
                "reused": True,
            }

            stage = "evidence"
            evidence_ref = _record_partition_evidence(
                documentation_result,
                user,
                audit_action=(
                    "modeling.analysis_partition.documentation_retried"
                ),
            )
            _update_documentation_status_exact(
                current,
                evidence_status="recorded",
                evidence_ref=evidence_ref,
                mdd_status="pending",
                mdd_ref=str(current.get("mdd_ref") or ""),
            )
            _require_exact_current_documentation_partition(current)

            stage = "mdd"
            mdd_ref = _record_partition_mdd(
                documentation_result,
                user,
                evidence_ref,
                include_target_distribution=False,
                accept_existing_exact_content=True,
            )
            _update_documentation_status_exact(
                current,
                evidence_status="recorded",
                evidence_ref=evidence_ref,
                mdd_status="recorded",
                mdd_ref=mdd_ref,
            )
            _require_exact_current_documentation_partition(current)

            stage = "readback"
            refreshed = _require_exact_current_documentation_partition(current)
            after_identity = {
                "analysis_partition_id": str(
                    refreshed.get("analysis_partition_id") or ""
                ),
                "revision": int(refreshed.get("revision") or 0),
                "artifact_hash": str(refreshed.get("artifact_hash") or ""),
                "assignment_hash": str(refreshed.get("assignment_hash") or ""),
                "row_assignments": json.dumps(
                    refreshed.get("row_assignments_json") or {},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
            documentation = (
                analysis_partition_service.repository.documentation_readiness(
                    refreshed
                )
            )
            if after_identity != before_identity or not documentation.get("ready"):
                raise RuntimeError(
                    "Exact documentation read-back did not preserve and verify the sealed partition."
                )
            # The readiness read uses its own connection. Re-resolve current
            # once more so a cross-process reset committed during that read
            # cannot produce a successful response for the superseded row.
            refreshed = _require_exact_current_documentation_partition(current)
            safe = analysis_partition_service.publish_safe(store, refreshed)
            return {
                "ok": True,
                "code": "analysis_partition_documentation_completed",
                "readiness": "current",
                "analysis_partition": safe,
                "documentation": documentation,
                "reused": True,
                "partition_mutated": False,
            }
    except AnalysisPartitionError as exc:
        _raise_contract_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "ok": False,
                "code": "analysis_partition_documentation_pending",
                "message": (
                    "The sealed Analysis Partition remains durable, but its "
                    "documentation retry did not complete."
                ),
                "recovery": (
                    "Retry Complete Partition Documentation. No membership was "
                    "recalculated or replaced."
                ),
                "documentation_stage": stage,
                "identifiers": {
                    "project_id": request.project_id,
                    "dataset_id": request.dataset_id,
                    "dataset_version_id": request.dataset_version_id,
                    "analysis_partition_id": request.analysis_partition_id,
                    "revision": request.revision,
                    "durable_partition_created": True,
                    "evidence_recorded": bool(evidence_ref),
                },
            },
        ) from exc


@router.post("/confirm")
def confirm_analysis_partition(
    request: AnalysisPartitionConfirmRequest,
    user: Dict[str, Any] = Depends(require_user),
):
    """Confirm or explicitly reset a sealed pre-EDA partition."""

    try:
        store, authoritative, _identity = _authoritative_partition_request(
            request, user, permission="edit", publish_authority=True
        )
        with store.state_lock:
            result = analysis_partition_service.confirm(
                store,
                authoritative,
                user,
                before_reset_persist=(
                    lambda: _invalidate_partition_derivatives(request, user)
                )
                if request.reset_existing
                else None,
                require_preview_contract=True,
            )
        partition = result.get("analysis_partition") or {}
        documentation_authority = _require_exact_current_documentation_partition(
            partition
        )
        try:
            evidence_ref = _record_partition_evidence(result, user)
            mdd_ref = _record_partition_mdd(result, user, evidence_ref)
            documented = _update_documentation_status_exact(
                documentation_authority,
                evidence_status="recorded",
                evidence_ref=evidence_ref,
                mdd_status="recorded",
                mdd_ref=mdd_ref,
            )
        except AnalysisPartitionError:
            raise
        except Exception as exc:
            raise AnalysisPartitionError(
                "analysis_partition_integrity_failed",
                "The Analysis Partition was created, but exact evidence and MDD persistence did not complete.",
                recovery="Do not continue into EDA until the exact partition documentation is reconciled.",
                identifiers={
                    "analysis_partition_id": partition.get(
                        "analysis_partition_id"
                    ),
                    "revision": partition.get("revision"),
                    "durable_partition_created": True,
                },
            ) from exc
        exact_partition_id = str(partition.get("analysis_partition_id") or "")
        exact_revision = int(partition.get("revision") or 0)
        refreshed = _require_exact_current_documentation_partition(
            documentation_authority
        )
        documentation = (
            analysis_partition_service.repository.documentation_readiness(
                refreshed
            )
        )
        if (
            int(refreshed.get("revision") or 0) != exact_revision
            or str(documented.get("analysis_partition_id") or "")
            != exact_partition_id
            or str(refreshed.get("evidence_ref") or "") != evidence_ref
            or str(refreshed.get("mdd_ref") or "") != mdd_ref
            or not documentation.get("ready")
        ):
            raise AnalysisPartitionError(
                "analysis_partition_integrity_failed",
                "The exact confirmed Analysis Partition could not be verified after evidence and MDD persistence.",
                recovery="Do not continue into EDA; refresh the exact partition status.",
                identifiers={
                    "analysis_partition_id": exact_partition_id,
                    "revision": exact_revision,
                },
            )
        refreshed = _require_exact_current_documentation_partition(
            documentation_authority
        )
        result["analysis_partition"] = analysis_partition_service.publish_safe(
            store, refreshed
        )
        return result
    except AnalysisPartitionError as exc:
        _raise_contract_error(exc)


@router.get("/reset-impact")
def analysis_partition_reset_impact(
    project_id: str = Query(..., min_length=1),
    dataset_id: str = Query(..., min_length=1),
    dataset_version_id: str = Query(..., min_length=1),
    user: Dict[str, Any] = Depends(require_user),
):
    """Preview invalidation before the user elects to replace membership."""

    try:
        store, authoritative, _identity = _authoritative_partition_request(
            {
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
            },
            user,
            permission="view",
        )
        record = analysis_partition_service.current(
            project_id,
            dataset_id,
            dataset_version_id,
            target=authoritative["target"],
            target_contract_id=authoritative["target_contract_id"],
            predictor_authorization_id=authoritative[
                "predictor_authorization_id"
            ],
        )
        inventory = _preview_derivative_inventory(record, store, RESULTS.current())
        return {
            "ok": True,
            "code": "analysis_partition_reset_impact",
            "analysis_partition": analysis_partition_service.safe_record(record),
            "impacts": analysis_partition_service.impact_for_reset(record),
            "affected_artifacts": inventory,
            "affected_artifact_count": len(inventory),
            "requires_explicit_reset": True,
            "requires_invalidation_acknowledgement": True,
        }
    except AnalysisPartitionError as exc:
        _raise_contract_error(exc)


@router.post("/invalidate")
def invalidate_analysis_partition(
    request: AnalysisPartitionInvalidationRequest,
    user: Dict[str, Any] = Depends(require_user),
):
    """Explicit internal/upstream lifecycle transition; never deletes rows."""

    try:
        store, authoritative, _identity = _authoritative_partition_request(
            {
                "project_id": request.project_id,
                "dataset_id": request.expected_dataset_id,
                "dataset_version_id": request.expected_dataset_version_id,
                "target": request.expected_target,
            },
            user,
            permission="edit",
            publish_authority=True,
        )
        current = analysis_partition_service.current(
            request.project_id,
            request.expected_dataset_id,
            request.expected_dataset_version_id,
            target=authoritative["target"],
            target_contract_id=authoritative["target_contract_id"],
            predictor_authorization_id=authoritative[
                "predictor_authorization_id"
            ],
        )
        transition_request = SimpleNamespace(
            reset_existing=True,
            project_id=request.project_id,
            dataset_id=request.expected_dataset_id,
            dataset_version_id=request.expected_dataset_version_id,
            target=authoritative["target"],
            target_contract_id=authoritative["target_contract_id"],
            predictor_authorization_id=authoritative[
                "predictor_authorization_id"
            ],
            expected_current_partition_id=current["analysis_partition_id"],
            expected_current_revision=int(current["revision"]),
            reset_reason=request.reason,
        )
        return analysis_partition_service.invalidate(
            request.project_id,
            request.reason,
            user,
            expected_dataset_id=request.expected_dataset_id or None,
            expected_dataset_version_id=request.expected_dataset_version_id or None,
            target=authoritative["target"],
            store=store,
            expected_current_partition_id=current["analysis_partition_id"],
            expected_current_revision=int(current["revision"]),
            before_invalidation_persist=lambda: _invalidate_partition_derivatives(
                transition_request, user
            ),
        )
    except AnalysisPartitionError as exc:
        _raise_contract_error(exc)
