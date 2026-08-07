from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Mapping
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from ..analysis_partition.types import (
    ANALYSIS_PARTITION_DOCUMENTATION_PENDING,
    ANALYSIS_PARTITION_REQUIRED,
    AnalysisPartitionError,
)
from ..bureau_metadata.crosswalk_router import (
    resolve_exact_semantic_handoff_for_user,
)
from ..core.modeling_scope import authorize_modeling_scope
from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.session_checkpoint import schedule_checkpoint_save
from ..datasets.dataset_identity import assert_expected_active_identity
from ..persistence.service import get_persistence_service
from ..persistence.repositories.special_value_review_repository import (
    SpecialValueReviewConflictError,
    SpecialValueReviewStateError,
)
from ..security.security_store import require_user
from .bureau_detection_service import detect_bureau_data
from .bureau_detection_types import (
    BureauDetectionRequest,
    SpecialValueReviewUpdateRequest,
)
from .predictor_authorization import (
    PredictorAuthorizationIntegrityError,
    verify_durable_predictor_authorization,
)
from .development_scope import resolve_development_analysis_scope
from .special_value_review_service import (
    SpecialValueReviewValidationError,
    detection_fingerprint,
    evaluate_review,
    initial_review_state,
    public_review_contract,
)


router = APIRouter()
logger = logging.getLogger("atlas.bureau_detection")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _trusted_catalog_special_definitions(
    *,
    identity: dict[str, Any],
    user: Dict[str, Any],
) -> dict[str, dict[float, str]]:
    """Resolve bounded provider codes only from an exact approved mapping.

    Catalog entitlement, binding, or crosswalk absence is intentionally
    nonblocking: dataset-observed candidates must still reach Special-Value
    Review.  Contradictory provider semantics are never substituted from a
    latest, first, or browser-supplied catalog.
    """

    try:
        payload = resolve_exact_semantic_handoff_for_user(
            project_id=_text(identity.get("project_id")),
            dataset_id=_text(identity.get("dataset_id")),
            dataset_version_id=_text(identity.get("dataset_version_id")),
            user=user,
        )
    except HTTPException as exc:
        if exc.status_code in {403, 404, 409, 503}:
            return {}
        raise

    resolved: dict[str, dict[float, str]] = {}
    for raw_annotation in payload.get("annotations", []):
        annotation = (
            raw_annotation if isinstance(raw_annotation, dict) else {}
        )
        if annotation.get("provider_authoritative") is not True:
            continue
        field = _text(annotation.get("dataset_field"))
        if not field:
            continue
        definitions: dict[float, str] = {}
        for raw_definition in annotation.get("special_definitions", []):
            definition = (
                raw_definition if isinstance(raw_definition, dict) else {}
            )
            try:
                value = float(_text(definition.get("value_code")))
            except (TypeError, ValueError):
                continue
            definitions[value] = (
                _text(definition.get("meaning"))
                or "Provider catalog special value"
            )
        if definitions:
            resolved[field] = definitions
    return resolved


def _development_target_checksum(
    values: Any,
    *,
    target: str,
    event_value: Any,
    development_partition_id: str,
) -> str:
    canonical_values: list[str] = []
    for raw in values.tolist():
        item = getattr(raw, "item", None)
        if callable(item):
            try:
                raw = item()
            except (TypeError, ValueError):
                pass
        if raw is None:
            canonical_values.append("null")
        elif isinstance(raw, bool):
            canonical_values.append(f"bool:{str(raw).lower()}")
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            canonical_values.append(f"number:{format(float(raw), '.15g')}")
        else:
            canonical_values.append(f"text:{str(raw)}")
    payload = json.dumps(
        {
            "target": target,
            "event_value": json_safe(event_value),
            "development_partition_id": development_partition_id,
            "population_count": len(canonical_values),
            "values": canonical_values,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _error_detail(
    *,
    code: str,
    message: str,
    corrective_action: str,
    correlation_id: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "code": code,
        "message": message,
        "corrective_action": corrective_action,
        "correlation_id": correlation_id,
        **dict(context or {}),
    }


def _governed_error(
    status_code: int,
    *,
    code: str,
    message: str,
    corrective_action: str,
    correlation_id: str,
    context: dict[str, Any] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=_error_detail(
            code=code,
            message=message,
            corrective_action=corrective_action,
            correlation_id=correlation_id,
            context=context,
        ),
        headers={"X-Request-Correlation-ID": correlation_id},
    )


def _expected_identity(
    request: BureauDetectionRequest,
    *,
    user: Dict[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    expected_dataset_id = _text(request.expected_dataset_id)
    expected_version_id = _text(request.expected_dataset_version_id)
    if not expected_dataset_id or not expected_version_id:
        raise _governed_error(
            422,
            code="dataset_identity_required",
            message=(
                "Credit bureau detection requires the exact active dataset and "
                "dataset-version identifiers."
            ),
            corrective_action="Reload Data Acquisition before retrying detection.",
            correlation_id=correlation_id,
        )
    try:
        return assert_expected_active_identity(
            request.project_id,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_version_id,
            require_expected=True,
            user=user,
        )
    except HTTPException as exc:
        status_code = 422 if exc.status_code == 422 else 409
        raise _governed_error(
            status_code,
            code=(
                "dataset_identity_required"
                if status_code == 422
                else "dataset_identity_mismatch"
            ),
            message=(
                "The requested dataset identity is incomplete."
                if status_code == 422
                else "The requested dataset identity is not the exact active Dataset Library version."
            ),
            corrective_action="Reload Data Acquisition and retry against its active version.",
            correlation_id=correlation_id,
        ) from exc


def _exact_predictor_authorization(
    identity: dict[str, Any],
    *,
    requested_target: Any,
    correlation_id: str,
) -> tuple[dict[str, Any], str]:
    project_id = _text(identity.get("project_id"))
    dataset_id = _text(identity.get("dataset_id"))
    dataset_version_id = _text(identity.get("dataset_version_id"))
    record = (
        get_persistence_service()
        .predictor_authorizations.get_current_exact(
            project_id,
            dataset_id,
            dataset_version_id,
        )
    )
    if not isinstance(record, dict):
        raise _governed_error(
            409,
            code="predictor_authorization_required",
            message=(
                "The exact Data Acquisition predictor authorization is not available "
                "for this dataset version."
            ),
            corrective_action="Return to Data Acquisition and confirm its predictor authorization.",
            correlation_id=correlation_id,
        )
    try:
        manifest = verify_durable_predictor_authorization(
            record,
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
        )
    except PredictorAuthorizationIntegrityError as exc:
        raise _governed_error(
            409,
            code="predictor_authorization_stale",
            message="The current Data Acquisition predictor authorization cannot be verified.",
            corrective_action="Return to Data Acquisition and reconfirm its predictor authorization.",
            correlation_id=correlation_id,
        ) from exc

    expected = {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
    }
    record_matches = all(_text(record.get(key)) == value for key, value in expected.items())
    manifest_matches = all(_text(manifest.get(key)) == value for key, value in expected.items())
    authorization_id = _text(
        manifest.get("predictor_authorization_id")
        or record.get("predictor_authorization_id")
    )
    if (
        _text(record.get("status")).casefold() != "current"
        or not record_matches
        or not manifest_matches
        or not authorization_id
    ):
        raise _governed_error(
            409,
            code="predictor_authorization_stale",
            message="The Data Acquisition predictor authorization does not match the active dataset version.",
            corrective_action="Return to Data Acquisition and reconfirm its predictor authorization.",
            correlation_id=correlation_id,
        )

    record_target = _text(record.get("target_column"))
    manifest_target = _text(manifest.get("target") or manifest.get("target_column"))
    if record_target and manifest_target and record_target != manifest_target:
        raise _governed_error(
            409,
            code="predictor_authorization_stale",
            message="The current predictor authorization contains a contradictory target contract.",
            corrective_action="Return to Data Acquisition and reconfirm its target and predictor authorization.",
            correlation_id=correlation_id,
        )
    target = manifest_target or record_target
    if not target:
        raise _governed_error(
            409,
            code="predictor_authorization_stale",
            message="The current predictor authorization does not contain a governed target.",
            corrective_action="Return to Data Acquisition and reconfirm its target and predictor authorization.",
            correlation_id=correlation_id,
        )
    supplied_target = _text(requested_target)
    if supplied_target and supplied_target != target:
        raise _governed_error(
            409,
            code="target_contract_mismatch",
            message="The requested target does not match the exact Data Acquisition target contract.",
            corrective_action="Reload Data Acquisition and retry with its governed target.",
            correlation_id=correlation_id,
        )
    return manifest, target


def _target_analysis_context(
    identity: dict[str, Any],
    authorization: dict[str, Any],
    *,
    target: str,
    requested_event_value: Any,
    correlation_id: str,
    actor: Any = None,
    expected_analysis_partition_id: Any = None,
    expected_analysis_partition_revision: Any = None,
) -> dict[str, Any]:
    """Resolve development-only target evidence without touching holdout rows."""

    project_id = _text(identity.get("project_id"))
    dataset_id = _text(identity.get("dataset_id"))
    dataset_version_id = _text(identity.get("dataset_version_id"))
    predictors = [
        _text(value)
        for value in authorization.get("authorized_predictors", [])
        if _text(value)
    ]
    try:
        scope = resolve_development_analysis_scope(
            DATASTORE.current(),
            identity,
            requested_target=target,
            requested_event_value=requested_event_value,
            expected_analysis_partition_id=expected_analysis_partition_id,
            expected_analysis_partition_revision=(
                expected_analysis_partition_revision
            ),
            actor=actor,
        )
    except AnalysisPartitionError as exc:
        raise _governed_error(
            exc.status_code,
            code=exc.code,
            message=exc.message,
            corrective_action=exc.recovery
            or "Return to Data Acquisition and restore the exact Analysis Partition.",
            correlation_id=correlation_id,
        ) from exc

    development_partition_id = _text(
        scope.partition.get("development_partition_id")
    )
    return {
        "authorized_predictors": predictors,
        "target_analysis_features": scope.development_features,
        "target_analysis_target": scope.development_target,
        "target_analysis_scope": "development_population",
        "analysis_partition_id": _text(
            scope.partition.get("analysis_partition_id")
        ),
        "analysis_partition_revision": int(
            scope.partition.get("revision") or 0
        ),
        "development_partition_id": development_partition_id,
        "analysis_partition_assignment_hash": _text(
            scope.partition.get("assignment_hash")
        ),
        "analysis_partition_artifact_hash": _text(
            scope.partition.get("artifact_hash")
        ),
        "development_target_checksum": _development_target_checksum(
            scope.development_target,
            target=target,
            event_value=scope.event_value,
            development_partition_id=development_partition_id,
        ),
        "governed_event_value": scope.event_value,
        "analysis_metadata": scope.metadata(),
    }


def _optional_target_analysis_context(
    identity: dict[str, Any],
    authorization: dict[str, Any],
    *,
    target: str,
    requested_event_value: Any,
    correlation_id: str,
    actor: Any = None,
) -> dict[str, Any]:
    """Return development evidence when eligible, otherwise structural-only.

    Special-value review intentionally precedes Analysis Partition creation in
    Data Acquisition. Absence of that not-yet-created authority must not form a
    workflow deadlock. Contradictory or stale authorities continue to fail
    closed; only a genuinely absent/documentation-pending partition yields an
    explicitly target-free structural review.
    """

    try:
        return _target_analysis_context(
            identity,
            authorization,
            target=target,
            requested_event_value=requested_event_value,
            correlation_id=correlation_id,
            actor=actor,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if _text(detail.get("code")) not in {
            ANALYSIS_PARTITION_REQUIRED,
            ANALYSIS_PARTITION_DOCUMENTATION_PENDING,
        }:
            raise
        return {
            "authorized_predictors": [
                _text(value)
                for value in authorization.get("authorized_predictors", [])
                if _text(value)
            ],
            "target_analysis_features": None,
            "target_analysis_target": None,
            "target_analysis_scope": "not_available",
            "analysis_partition_id": None,
            "analysis_partition_revision": None,
            "development_partition_id": None,
            "analysis_partition_assignment_hash": None,
            "analysis_partition_artifact_hash": None,
            "development_target_checksum": None,
            "governed_event_value": None,
            "analysis_metadata": {
                "analytical_scope": (
                    "full_governed_population_predictors_only"
                ),
                "structural_scope": (
                    "full_governed_population_predictors_only"
                ),
                "target_analysis_scope": "not_available",
                "target_evidence_status": "unavailable",
                "target_evidence_unavailable_reason": _text(
                    detail.get("code")
                ),
                "source_checksum": _text(
                    identity.get("dataset_content_hash")
                ),
                "full_governed_population_rows": int(
                    identity.get("rows")
                    or identity.get("row_count")
                    or 0
                ),
                "development_rows": 0,
                "holdout_excluded": True,
                "final_holdout_accessed": False,
                "final_holdout_used_for_selection": False,
                "raw_dataset_target_fallback_used": False,
            },
        }


def _sync_special_value_review(
    detection: dict[str, Any],
    *,
    identity: dict[str, Any],
    authorization: dict[str, Any],
    user: Dict[str, Any],
) -> dict[str, Any]:
    state = initial_review_state(detection)
    repository = get_persistence_service().special_value_reviews
    row = repository.sync_detection(
        {
            "project_id": _text(identity.get("project_id")),
            "dataset_id": _text(identity.get("dataset_id")),
            "dataset_version_id": _text(identity.get("dataset_version_id")),
            "activation_revision": int(identity.get("activation_revision") or 0),
            "predictor_authorization_id": _text(
                authorization.get("predictor_authorization_id")
            ),
            "target_contract_id": _text(authorization.get("target_contract_id")),
            "detection_fingerprint": detection_fingerprint(detection),
            "detection": detection,
            "actor_user_id": _text(user.get("userId")) or "atlas-user",
            **state,
        }
    )
    return public_review_contract(row)


#: Fields the CURRENT public review contract requires. A durable row written
#: before these existed can never satisfy the browser contract validator, so it
#: must be reported as superseded rather than served as if it were valid.
_CURRENT_CONTRACT_REQUIRED_TEXT = (
    "source_checksum",
    "structural_scope",
)
_CURRENT_CONTRACT_SCOPES = {"development_population", "not_available"}


def _superseded_contract_reasons(detection: Mapping[str, Any]) -> list[str]:
    """Why a persisted detection predates the current contract schema.

    PROVEN DEFECT this guards: the HELOC review persisted at revision 7 carried
    `target_analysis_scope="development_partition"` plus null `structural_scope`,
    `source_checksum`, and `full_governed_population_rows`.
    `_exact_review_row` never inspected those fields,
    so the row was served as a valid contract; the browser validator then
    correctly rejected it as an identity mismatch. Neither side offered a
    recovery path, so the Special Values section stayed blocked permanently with
    an error that named the wrong cause.
    """

    reasons: list[str] = []
    for field in _CURRENT_CONTRACT_REQUIRED_TEXT:
        if not _text(detection.get(field)):
            reasons.append(field)
    if int(detection.get("full_governed_population_rows") or 0) <= 0:
        reasons.append("full_governed_population_rows")
    scope = _text(detection.get("target_analysis_scope"))
    if scope not in _CURRENT_CONTRACT_SCOPES:
        reasons.append("target_analysis_scope")
    target_evidence = detection.get("target_evidence")
    target_evidence = (
        target_evidence if isinstance(target_evidence, Mapping) else {}
    )
    status = _text(
        target_evidence.get("status")
        or detection.get("target_evidence_status")
    )
    if status and status not in {"available", "unavailable"}:
        reasons.append("target_evidence_status")
    return reasons


def _exact_review_row(
    *,
    identity: dict[str, Any],
    authorization: dict[str, Any],
    target: str,
    actor: Any,
    correlation_id: str,
    expected_analysis_partition_id: Any = None,
    expected_analysis_partition_revision: Any = None,
) -> dict[str, Any]:
    project_id = _text(identity.get("project_id"))
    dataset_id = _text(identity.get("dataset_id"))
    version_id = _text(identity.get("dataset_version_id"))
    row = get_persistence_service().special_value_reviews.get_exact(
        project_id, dataset_id, version_id
    )
    if not isinstance(row, dict):
        raise _governed_error(
            404,
            code="special_value_review_required",
            message="The exact backend special-value detection has not been initialized.",
            corrective_action="Run the Data Acquisition special-value detection for this exact version.",
            correlation_id=correlation_id,
        )
    detection = row.get("detection_json")
    detection = detection if isinstance(detection, dict) else {}
    superseded = _superseded_contract_reasons(detection)
    if superseded:
        raise _governed_error(
            409,
            code="special_value_review_stale",
            message=(
                "The durable special-value review predates the current review "
                "contract and cannot be validated."
            ),
            corrective_action=(
                "Re-run Data Acquisition special-value detection for this exact "
                "Dataset Version to regenerate the review."
            ),
            correlation_id=correlation_id,
            context={
                "special_value_review": public_review_contract(row),
                "superseded_contract_fields": superseded,
            },
        )
    target_evidence = detection.get("target_evidence")
    target_evidence = target_evidence if isinstance(target_evidence, dict) else {}
    target_evidence_available = bool(target_evidence.get("available")) or (
        _text(detection.get("target_analysis_scope"))
        == "development_population"
    )
    analysis_context: dict[str, Any] = {}
    if target_evidence_available:
        stored_partition_id = _text(detection.get("analysis_partition_id"))
        stored_partition_revision = int(
            detection.get("analysis_partition_revision") or 0
        )
        if not stored_partition_id or stored_partition_revision <= 0:
            raise _governed_error(
                409,
                code="special_value_review_stale",
                message=(
                    "The durable target-informed special-value review has "
                    "incomplete Analysis Partition lineage."
                ),
                corrective_action=(
                    "Refresh special-value detection for the exact current "
                    "Analysis Partition."
                ),
                correlation_id=correlation_id,
                context={"special_value_review": public_review_contract(row)},
            )
        requested_partition_id = _text(expected_analysis_partition_id)
        requested_partition_revision = (
            int(expected_analysis_partition_revision)
            if expected_analysis_partition_revision is not None
            else None
        )
        if requested_partition_id and (
            requested_partition_id != stored_partition_id
            or requested_partition_revision != stored_partition_revision
        ):
            raise _governed_error(
                409,
                code="special_value_review_stale",
                message=(
                    "The requested special-value review is bound to a different "
                    "Analysis Partition revision."
                ),
                corrective_action="Reload Data Acquisition before continuing.",
                correlation_id=correlation_id,
                context={"special_value_review": public_review_contract(row)},
            )
        try:
            analysis_context = _target_analysis_context(
                identity,
                authorization,
                target=target,
                requested_event_value=None,
                correlation_id=correlation_id,
                actor=actor,
                expected_analysis_partition_id=stored_partition_id,
                expected_analysis_partition_revision=stored_partition_revision,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            raise _governed_error(
                409,
                code="special_value_review_stale",
                message=(
                    "The target-informed special-value review is stale for the "
                    "current Analysis Partition."
                ),
                corrective_action=(
                    "Refresh special-value detection against the exact current "
                    "Analysis Partition before saving or confirming."
                ),
                correlation_id=correlation_id,
                context={
                    "special_value_review": public_review_contract(row),
                    "upstream_code": _text(detail.get("code")),
                },
            ) from exc
    elif _text(expected_analysis_partition_id):
        raise _governed_error(
            409,
            code="special_value_review_stale",
            message=(
                "This structural special-value review has no target-aware "
                "Analysis Partition evidence."
            ),
            corrective_action=(
                "Refresh detection after the Analysis Partition is available."
            ),
            correlation_id=correlation_id,
            context={"special_value_review": public_review_contract(row)},
        )

    partition_lineage_matches = (
        not target_evidence_available
        or (
            _text(detection.get("analysis_partition_id"))
            == _text(analysis_context.get("analysis_partition_id"))
            and int(detection.get("analysis_partition_revision") or 0)
            == int(analysis_context.get("analysis_partition_revision") or 0)
            and _text(detection.get("development_partition_id"))
            == _text(analysis_context.get("development_partition_id"))
            and _text(detection.get("analysis_partition_assignment_hash"))
            == _text(
                analysis_context.get("analysis_partition_assignment_hash")
            )
            and _text(detection.get("analysis_partition_artifact_hash"))
            == _text(
                analysis_context.get("analysis_partition_artifact_hash")
            )
            and _text(detection.get("development_target_checksum"))
            == _text(analysis_context.get("development_target_checksum"))
        )
    )
    source_checksum_matches = (
        _text(detection.get("source_checksum"))
        == _text(identity.get("dataset_content_hash"))
    )
    lineage_matches = (
        _text(row.get("predictor_authorization_id"))
        == _text(authorization.get("predictor_authorization_id"))
        and _text(row.get("target_contract_id"))
        == _text(authorization.get("target_contract_id"))
        and partition_lineage_matches
        and source_checksum_matches
    )
    revision_matches = int(row.get("activation_revision") or 0) == int(
        identity.get("activation_revision") or 0
    )
    if not lineage_matches or not revision_matches:
        raise _governed_error(
            409,
            code="special_value_review_stale",
            message=(
                "The durable special-value review does not match the exact active "
                "dataset, Analysis Partition, or development-target evidence."
            ),
            corrective_action=(
                "Refresh special-value detection for the exact active dataset "
                "and current Analysis Partition."
            ),
            correlation_id=correlation_id,
            context={"special_value_review": public_review_contract(row)},
        )
    return row


@router.post("/data/bureau-detection")
def bureau_detection(request: BureauDetectionRequest, user: Dict[str, Any] = Depends(require_user)):
    correlation_id = f"bureau-{uuid.uuid4().hex}"
    try:
        authorize_modeling_scope(user, request.project_id, "edit")
        identity = _expected_identity(
            request,
            user=user,
            correlation_id=correlation_id,
        )
        authorization, target = _exact_predictor_authorization(
            identity,
            requested_target=request.target,
            correlation_id=correlation_id,
        )
        analysis_context = _optional_target_analysis_context(
            identity,
            authorization,
            target=target,
            requested_event_value=request.event_value,
            correlation_id=correlation_id,
            actor=user.get("userId"),
        )
        catalog_special_definitions = _trusted_catalog_special_definitions(
            identity=identity,
            user=user,
        )
        # Browser-supplied metadata is not an authority.  Normal Data
        # Acquisition detection uses only exact server-resolved catalog
        # definitions plus conservative dataset-observed candidates.
        bound_request = request.model_copy(
            update={"target": target, "metadata": []}
        )
        result = detect_bureau_data(
            bound_request,
            trusted_catalog_special_definitions=(
                catalog_special_definitions
            ),
            **analysis_context,
        )
        result.update(
            {
                "project_id": _text(identity.get("project_id")),
                "dataset_id": _text(identity.get("dataset_id")),
                "dataset_version_id": _text(identity.get("dataset_version_id")),
                "activation_revision": int(identity.get("activation_revision") or 0),
                "predictor_authorization_id": _text(
                    authorization.get("predictor_authorization_id")
                ),
                "target_contract_id": _text(authorization.get("target_contract_id")),
                "correlation_id": correlation_id,
            }
        )
        safe_result = json_safe(result)
        # Fail inside the guarded boundary if a future analytical value is not
        # representable as strict JSON. FastAPI must never discover that only
        # after the route has already published review state.
        json.dumps(safe_result, allow_nan=False)
        safe_result["special_value_review"] = _sync_special_value_review(
            safe_result,
            identity=identity,
            authorization=authorization,
            user=user,
        )

        prior_present = "bureau_review" in DATASTORE.meta
        prior_review = DATASTORE.meta.get("bureau_review")
        DATASTORE.meta["bureau_review"] = safe_result
        try:
            schedule_checkpoint_save()
        except Exception:
            if prior_present:
                DATASTORE.meta["bureau_review"] = prior_review
            else:
                DATASTORE.meta.pop("bureau_review", None)
            raise
        return safe_result
    except HTTPException:
        raise
    except ValueError as exc:
        logger.info(
            "Bureau detection governed state unavailable correlation_id=%s project_id=%s exception_type=%s",
            correlation_id,
            _text(request.project_id),
            type(exc).__name__,
        )
        raise _governed_error(
            409,
            code="dataset_artifact_unavailable",
            message="The exact active dataset artifact is unavailable for credit bureau detection.",
            corrective_action="Reload Data Acquisition and retry against the active dataset version.",
            correlation_id=correlation_id,
        ) from exc
    except Exception as exc:
        logger.exception(
            "Unexpected bureau detection failure correlation_id=%s project_id=%s exception_type=%s",
            correlation_id,
            _text(request.project_id),
            type(exc).__name__,
        )
        raise _governed_error(
            500,
            code="bureau_detection_unavailable",
            message="Credit bureau detection could not be completed.",
            corrective_action="Retry the request. If it continues to fail, provide the reference ID to support.",
            correlation_id=correlation_id,
        ) from exc


@router.get("/data/special-value-review")
def get_special_value_review(
    project_id: str = Query(min_length=1),
    expected_dataset_id: str = Query(min_length=1),
    expected_dataset_version_id: str = Query(min_length=1),
    expected_analysis_partition_id: str | None = Query(default=None),
    expected_analysis_partition_revision: int | None = Query(
        default=None,
        ge=1,
    ),
    user: Dict[str, Any] = Depends(require_user),
):
    correlation_id = f"special-review-{uuid.uuid4().hex}"
    authorize_modeling_scope(user, project_id, "view")
    identity = _expected_identity(
        BureauDetectionRequest(
            project_id=project_id,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_dataset_version_id,
        ),
        user=user,
        correlation_id=correlation_id,
    )
    if bool(_text(expected_analysis_partition_id)) != bool(
        expected_analysis_partition_revision is not None
    ):
        raise _governed_error(
            422,
            code="analysis_partition_identity_required",
            message="Analysis Partition ID and revision must be supplied together.",
            corrective_action="Reload Data Acquisition before retrieving the review.",
            correlation_id=correlation_id,
        )
    authorization, target = _exact_predictor_authorization(
        identity,
        requested_target=None,
        correlation_id=correlation_id,
    )
    row = _exact_review_row(
        identity=identity,
        authorization=authorization,
        target=target,
        actor=user.get("userId"),
        correlation_id=correlation_id,
        expected_analysis_partition_id=expected_analysis_partition_id,
        expected_analysis_partition_revision=(
            expected_analysis_partition_revision
        ),
    )
    return {
        "ok": True,
        "special_value_review": public_review_contract(row),
        "correlation_id": correlation_id,
    }


@router.put("/data/special-value-review")
def update_special_value_review(
    request: SpecialValueReviewUpdateRequest,
    user: Dict[str, Any] = Depends(require_user),
):
    correlation_id = f"special-review-{uuid.uuid4().hex}"
    authorize_modeling_scope(user, request.project_id, "edit")
    identity = _expected_identity(
        BureauDetectionRequest(
            project_id=request.project_id,
            expected_dataset_id=request.expected_dataset_id,
            expected_dataset_version_id=request.expected_dataset_version_id,
        ),
        user=user,
        correlation_id=correlation_id,
    )
    authorization, target = _exact_predictor_authorization(
        identity,
        requested_target=None,
        correlation_id=correlation_id,
    )
    row = _exact_review_row(
        identity=identity,
        authorization=authorization,
        target=target,
        actor=user.get("userId"),
        correlation_id=correlation_id,
        expected_analysis_partition_id=request.expected_analysis_partition_id,
        expected_analysis_partition_revision=(
            request.expected_analysis_partition_revision
        ),
    )
    if request.detection_fingerprint != _text(row.get("detection_fingerprint")):
        raise _governed_error(
            409,
            code="special_value_detection_stale",
            message="The submitted review targets an outdated backend detection.",
            corrective_action="Reload the exact special-value review and reapply the draft.",
            correlation_id=correlation_id,
            context={"special_value_review": public_review_contract(row)},
        )
    try:
        evaluated = evaluate_review(
            row.get("detection_json") or {},
            request.variable_decisions,
            intent=request.intent,
        )
        saved = get_persistence_service().special_value_reviews.save_review(
            {
                "project_id": request.project_id,
                "dataset_id": request.expected_dataset_id,
                "dataset_version_id": request.expected_dataset_version_id,
                "detection_fingerprint": request.detection_fingerprint,
                "reviewer_rationale": request.reviewer_rationale,
                "actor_user_id": _text(user.get("userId")) or "atlas-user",
                **evaluated,
            },
            expected_revision=request.expected_revision,
        )
    except SpecialValueReviewValidationError as exc:
        raise _governed_error(
            409,
            code=exc.code,
            message=exc.message,
            corrective_action="Resolve every backend-detected open item before confirmation.",
            correlation_id=correlation_id,
            context={
                "open_items": exc.open_items,
                "special_value_review": public_review_contract(row),
            },
        ) from exc
    except SpecialValueReviewConflictError as exc:
        raise _governed_error(
            409,
            code="special_value_review_revision_conflict",
            message=str(exc),
            corrective_action="Reload the durable review before saving again.",
            correlation_id=correlation_id,
            context={
                "special_value_review": public_review_contract(exc.current)
            },
        ) from exc
    except SpecialValueReviewStateError as exc:
        raise _governed_error(
            409,
            code="special_value_review_required",
            message=str(exc),
            corrective_action="Run detection for the exact active dataset version.",
            correlation_id=correlation_id,
        ) from exc
    contract = public_review_contract(saved)
    DATASTORE.meta["special_value_review"] = contract
    schedule_checkpoint_save()
    return {
        "ok": True,
        "special_value_review": contract,
        "correlation_id": correlation_id,
    }

