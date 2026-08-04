from __future__ import annotations

from typing import Any, Mapping

from fastapi import HTTPException

from ..analysis_partition.types import AnalysisPartitionError
from ..core.dataset_store import DATASTORE
from ..core.modeling_scope import authorize_modeling_scope
from ..datasets.dataset_identity import assert_expected_active_identity
from ..preprocessing.development_scope import (
    DevelopmentAnalysisScope,
    resolve_development_analysis_scope,
    scope_http_exception,
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _value(payload: Any, *names: str) -> Any:
    for name in names:
        if isinstance(payload, Mapping) and name in payload:
            return payload.get(name)
        if hasattr(payload, name):
            return getattr(payload, name)
    return None


def _consistent_value(payload: Any, *names: str) -> Any:
    values: list[Any] = []
    for name in names:
        present = isinstance(payload, Mapping) and name in payload
        present = present or hasattr(payload, name)
        if not present:
            continue
        value = payload.get(name) if isinstance(payload, Mapping) else getattr(payload, name)
        if value not in (None, ""):
            values.append(value)
    normalized = {_text(value) for value in values}
    if len(normalized) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "The stored Credit Risk artifact contains contradictory "
                f"aliases for {names[0]}."
            ),
        )
    return values[0] if values else None


def resolve_credit_risk_scope(
    payload: Any,
    user: Mapping[str, Any],
    *,
    access: str = "view",
) -> tuple[Any, dict[str, Any], DevelopmentAnalysisScope]:
    """Resolve one exact active, development-only Credit Risk scope.

    Credit Risk Studio is a project workflow surface.  Dataset identity,
    target semantics, predictor authorization, and Analysis Partition are
    therefore server authorities; client values are contradiction checks only.
    """

    project_id = _text(_value(payload, "projectId", "project_id"))
    dataset_id = _text(_value(payload, "datasetId", "dataset_id"))
    dataset_version_id = _text(
        _value(payload, "datasetVersionId", "dataset_version_id")
    )
    if not project_id or not dataset_id or not dataset_version_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "Credit Risk analysis requires the exact projectId, datasetId, "
                "and datasetVersionId. Latest/first-version fallback is prohibited."
            ),
        )
    authorize_modeling_scope(dict(user), project_id, access)
    store = DATASTORE.current()
    with store.state_lock:
        identity = assert_expected_active_identity(
            project_id,
            expected_dataset_id=dataset_id,
            expected_dataset_version_id=dataset_version_id,
            require_expected=True,
            user=dict(user),
            store=store,
        )
        try:
            scope = resolve_development_analysis_scope(
                store,
                identity,
                requested_target=_value(payload, "targetColumn", "target"),
                requested_event_value=_value(payload, "eventValue", "event_value"),
                requested_problem_type=_value(payload, "problemType", "problem_type"),
                expected_analysis_partition_id=_value(
                    payload,
                    "analysisPartitionId",
                    "analysis_partition_id",
                    "partition_id",
                ),
                expected_analysis_partition_revision=_value(
                    payload,
                    "analysisPartitionRevision",
                    "analysis_partition_revision",
                    "partition_revision",
                ),
                actor=user.get("userId"),
            )
        except AnalysisPartitionError as exc:
            raise scope_http_exception(exc) from exc
        normalized_problem = scope.problem_type.casefold().replace("-", "_").replace(" ", "_")
        if normalized_problem not in {"classification", "binary_classification"}:
            raise HTTPException(
                status_code=409,
                detail="Credit Risk WOE, scorecard, and underwriting model paths require a governed binary-classification target contract.",
            )
        if scope.event_value in (None, "") or scope.non_event_value in (None, ""):
            raise HTTPException(
                status_code=409,
                detail="The governed Credit Risk target contract must define exact event and non-event values.",
            )
        if _text(scope.event_value) == _text(scope.non_event_value):
            raise HTTPException(
                status_code=409,
                detail="The governed Credit Risk event and non-event values must be distinct.",
            )
        requested_non_event = _value(payload, "nonEventValue", "non_event_value")
        if requested_non_event not in (None, "") and _text(requested_non_event) != _text(scope.non_event_value):
            raise HTTPException(
                status_code=409,
                detail="The requested non-event value contradicts the exact governed target contract.",
            )
    return store, identity, scope


def resolve_credit_risk_project_scope(
    project_id: Any,
    user: Mapping[str, Any],
    *,
    access: str = "view",
) -> tuple[Any, dict[str, Any], DevelopmentAnalysisScope]:
    """Resolve current exact durable identity for a project-scoped read."""

    resolved_project_id = _text(project_id)
    authorize_modeling_scope(dict(user), resolved_project_id, access)
    store = DATASTORE.current()
    with store.state_lock:
        identity = assert_expected_active_identity(
            resolved_project_id,
            user=dict(user),
            store=store,
        )
    return resolve_credit_risk_scope(
        {
            "projectId": identity["project_id"],
            "datasetId": identity["dataset_id"],
            "datasetVersionId": identity["dataset_version_id"],
        },
        user,
        access=access,
    )


def canonical_scope_fields(scope: DevelopmentAnalysisScope) -> dict[str, Any]:
    metadata = scope.metadata()
    return {
        **metadata,
        "targetColumn": scope.target,
        "eventValue": scope.event_value,
        "event_value": scope.event_value,
        "nonEventValue": scope.non_event_value,
        "non_event_value": scope.non_event_value,
        "targetContractId": metadata["target_contract_id"],
        "analysisPartitionId": metadata["partition_id"],
        "analysisPartitionRevision": metadata["partition_revision"],
        "developmentPopulationId": metadata["population_id"],
        "sourceChecksum": metadata["source_checksum"],
    }


def require_artifact_scope(
    artifact: Mapping[str, Any],
    scope: DevelopmentAnalysisScope,
    *,
    artifact_label: str,
) -> None:
    """Reject stale, cross-project, cross-version, or unscoped artifacts."""

    expected = canonical_scope_fields(scope)
    comparisons = (
        ("project", _consistent_value(artifact, "projectId", "project_id"), expected["project_id"]),
        ("dataset", _consistent_value(artifact, "datasetId", "dataset_id"), expected["dataset_id"]),
        (
            "dataset version",
            _consistent_value(artifact, "datasetVersionId", "dataset_version_id"),
            expected["dataset_version_id"],
        ),
        (
            "target column",
            _consistent_value(artifact, "targetColumn", "target_column", "target"),
            expected["target"],
        ),
        (
            "event value",
            _consistent_value(artifact, "eventValue", "event_value"),
            expected["eventValue"],
        ),
        (
            "non-event value",
            _consistent_value(artifact, "nonEventValue", "non_event_value"),
            expected["nonEventValue"],
        ),
        (
            "target contract",
            _consistent_value(artifact, "targetContractId", "target_contract_id"),
            expected["target_contract_id"],
        ),
        (
            "Analysis Partition",
            _consistent_value(artifact, "analysisPartitionId", "analysis_partition_id", "partition_id"),
            expected["partition_id"],
        ),
        (
            "Analysis Partition revision",
            _consistent_value(
                artifact,
                "analysisPartitionRevision",
                "analysis_partition_revision",
                "partition_revision",
            ),
            expected["partition_revision"],
        ),
        (
            "development population",
            _consistent_value(artifact, "developmentPopulationId", "development_partition_id", "population_id"),
            expected["population_id"],
        ),
        (
            "source checksum",
            _consistent_value(artifact, "sourceChecksum", "source_checksum"),
            expected["source_checksum"],
        ),
    )
    for field, actual, governed in comparisons:
        if not _text(actual) or _text(actual) != _text(governed):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"The {artifact_label} does not match the exact current {field}. "
                    "Reload or regenerate it from the active governed development population."
                ),
            )
    if _text(_consistent_value(artifact, "analysis_scope", "analytical_scope", "scope")) != "development_population":
        raise HTTPException(
            status_code=409,
            detail=f"The {artifact_label} is not a development-population artifact.",
        )
    if _value(artifact, "holdout_excluded") is not True:
        raise HTTPException(
            status_code=409,
            detail=f"The {artifact_label} does not prove final-holdout exclusion.",
        )
    for flag in (
        "final_holdout_accessed",
        "final_holdout_used_for_selection",
        "raw_dataset_target_fallback_used",
        "browser_target_semantics_used",
    ):
        if _value(artifact, flag) is not False:
            raise HTTPException(
                status_code=409,
                detail=f"The {artifact_label} has missing or contradictory safety flag {flag}.",
            )
    if _text(_value(artifact, "scope_resolution")) != "durable_current_exact":
        raise HTTPException(
            status_code=409,
            detail=f"The {artifact_label} does not prove exact durable scope resolution.",
        )
    if _text(_value(artifact, "row_selection_method")) != "verified_positional_assignment":
        raise HTTPException(
            status_code=409,
            detail=f"The {artifact_label} does not prove positional development-population selection.",
        )


def artifact_scope_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Build contradiction-only resolver input from a stored artifact."""

    return {
        "projectId": _consistent_value(artifact, "projectId", "project_id"),
        "datasetId": _consistent_value(artifact, "datasetId", "dataset_id"),
        "datasetVersionId": _consistent_value(
            artifact, "datasetVersionId", "dataset_version_id"
        ),
        "targetColumn": _consistent_value(artifact, "targetColumn", "target"),
        "eventValue": _consistent_value(artifact, "eventValue", "event_value"),
        "nonEventValue": _consistent_value(
            artifact, "nonEventValue", "non_event_value"
        ),
        "analysisPartitionId": _consistent_value(
            artifact,
            "analysisPartitionId",
            "analysis_partition_id",
            "partition_id",
        ),
        "analysisPartitionRevision": _consistent_value(
            artifact,
            "analysisPartitionRevision",
            "analysis_partition_revision",
            "partition_revision",
        ),
    }
