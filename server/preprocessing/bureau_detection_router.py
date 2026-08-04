from __future__ import annotations

import json
import logging
from typing import Any, Dict
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from ..analysis_partition.types import AnalysisPartitionError
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
        "development_partition_id": _text(
            scope.partition.get("development_partition_id")
        ),
        "governed_event_value": scope.event_value,
        "analysis_metadata": scope.metadata(),
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


def _exact_review_row(
    *,
    identity: dict[str, Any],
    authorization: dict[str, Any],
    correlation_id: str,
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
    lineage_matches = (
        _text(row.get("predictor_authorization_id"))
        == _text(authorization.get("predictor_authorization_id"))
        and _text(row.get("target_contract_id"))
        == _text(authorization.get("target_contract_id"))
    )
    revision_matches = int(row.get("activation_revision") or 0) == int(
        identity.get("activation_revision") or 0
    )
    if not lineage_matches or not revision_matches:
        raise _governed_error(
            409,
            code="special_value_review_stale",
            message="The durable special-value review does not match the exact active authority.",
            corrective_action="Refresh special-value detection for the exact active dataset version.",
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
        analysis_context = _target_analysis_context(
            identity,
            authorization,
            target=target,
            requested_event_value=request.event_value,
            correlation_id=correlation_id,
            actor=user.get("userId"),
        )
        bound_request = request.model_copy(update={"target": target})
        result = detect_bureau_data(bound_request, **analysis_context)
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
    authorization, _target = _exact_predictor_authorization(
        identity,
        requested_target=None,
        correlation_id=correlation_id,
    )
    row = _exact_review_row(
        identity=identity,
        authorization=authorization,
        correlation_id=correlation_id,
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
    authorization, _target = _exact_predictor_authorization(
        identity,
        requested_target=None,
        correlation_id=correlation_id,
    )
    row = _exact_review_row(
        identity=identity,
        authorization=authorization,
        correlation_id=correlation_id,
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

