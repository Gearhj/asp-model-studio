# server/evaluation/eval_router.py

import io
import hashlib
import json
import uuid
from typing import Any, Dict

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from ..core.modeling_scope import authorize_modeling_scope
from ..core.result_store import RESULTS
from ..core.session_checkpoint import flush_checkpoint, schedule_checkpoint_save
from ..model_registry import model_registry_service as REGISTRY
from ..security.security_store import audit_event, require_user
from ..scoring_runs.scoring_run_service import create_failed_scoring_run, create_scoring_run
from .eval_service import EVAL, SELECTION_REVIEW_EVIDENCE_SCOPE


router = APIRouter()


def _context(
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
    candidate_id: str,
    training_job_id: str,
    training_run_id: str,
    feature_manifest_version: str,
    validation_design_id: str,
    validation_design_version: str,
    split_id: str,
    target: str,
    problem_type: str,
    candidate_decision_id: str,
) -> dict:
    return {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "candidate_id": candidate_id,
        "training_job_id": training_job_id,
        "training_run_id": training_run_id,
        "feature_manifest_version": feature_manifest_version,
        "validation_design_id": validation_design_id,
        "validation_design_version": validation_design_version,
        "split_id": split_id,
        "target": target,
        "problem_type": problem_type,
        "candidate_decision_id": candidate_decision_id,
    }


def _lineage_context(
    project_id: str = Query(...),
    dataset_id: str = Query(...),
    dataset_version_id: str = Query(...),
    candidate_id: str = Query(...),
    training_job_id: str = Query(...),
    training_run_id: str = Query(...),
    feature_manifest_version: str = Query(...),
    validation_design_id: str = Query(...),
    validation_design_version: str = Query(...),
    split_id: str = Query(...),
    target: str = Query(...),
    problem_type: str = Query(...),
    candidate_decision_id: str = Query(""),
    evaluation_package_id: str = Query(""),
    evidence_scope: str = Query(""),
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    normalized_scope = str(evidence_scope or "").strip()
    if normalized_scope not in {"", SELECTION_REVIEW_EVIDENCE_SCOPE}:
        raise HTTPException(
            status_code=422,
            detail=(
                "Unsupported evidence_scope. Use the governed reporting path "
                "or explicit selection_review."
            ),
        )
    normalized_decision_id = str(candidate_decision_id or "").strip()
    if (
        normalized_scope != SELECTION_REVIEW_EVIDENCE_SCOPE
        and not normalized_decision_id
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Exact Evaluation lineage is required: "
                "candidate_decision_id"
            ),
        )
    return {
        **_context(
        project_id=project_id,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        candidate_id=candidate_id,
        training_job_id=training_job_id,
        training_run_id=training_run_id,
        feature_manifest_version=feature_manifest_version,
        validation_design_id=validation_design_id,
        validation_design_version=validation_design_version,
        split_id=split_id,
        target=target,
        problem_type=problem_type,
        candidate_decision_id=normalized_decision_id,
        ),
        "evaluation_package_id": str(evaluation_package_id).strip(),
        "evidence_scope": normalized_scope,
        "_actor_user_id": str(user.get("userId") or ""),
    }


def _version_bound_value(version: Dict[str, Any], aliases: tuple[str, ...]) -> list[str]:
    lineage = version.get("lineage") if isinstance(version.get("lineage"), dict) else {}
    model_contract = (
        version.get("modelContract")
        if isinstance(version.get("modelContract"), dict)
        else {}
    )
    candidate_contract = (
        version.get("candidateContract")
        if isinstance(version.get("candidateContract"), dict)
        else model_contract.get("candidateContract")
        if isinstance(model_contract.get("candidateContract"), dict)
        else lineage.get("candidateContract")
        if isinstance(lineage.get("candidateContract"), dict)
        else {}
    )
    values: list[str] = []
    for source in (version, lineage, model_contract, candidate_contract):
        for alias in aliases:
            value = str(source.get(alias) or "").strip()
            if value and value not in values:
                values.append(value)
    return values


def _prepare_interpretation_context(
    user: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    model_version_id = str(context.get("model_version_id") or "").strip()
    if not model_version_id:
        return context
    version = REGISTRY.get_version(user, model_version_id)
    if str(version.get("modelVersionId") or "").strip() != model_version_id:
        raise HTTPException(status_code=409, detail="The registry returned a different model version.")
    if (
        str(version.get("publicationStatus") or "").strip() != "finalized"
        or str(version.get("lineageStatus") or "").strip() != "verified"
    ):
        raise HTTPException(
            status_code=409,
            detail="The requested registered model version is not finalized with verified lineage.",
        )
    aliases = {
        "project_id": ("projectId", "project_id"),
        "dataset_id": ("datasetId", "dataset_id", "trainingDatasetId", "training_dataset_id"),
        "dataset_version_id": (
            "datasetVersionId",
            "dataset_version_id",
            "trainingDatasetVersionId",
            "training_dataset_version_id",
        ),
        "candidate_id": ("candidateId", "candidate_id"),
        "training_job_id": ("trainingJobId", "training_job_id"),
        "training_run_id": ("trainingRunId", "training_run_id"),
        "feature_manifest_version": (
            "featureManifestVersion",
            "featureManifestHash",
            "feature_manifest_version",
            "feature_manifest_hash",
        ),
        "validation_design_id": ("validationDesignId", "validation_design_id"),
        "validation_design_version": (
            "validationDesignVersion",
            "validation_design_version",
        ),
        "split_id": ("splitId", "split_id"),
        "target": ("target", "targetName", "target_name"),
        "problem_type": ("problemType", "problem_type"),
        "evaluation_package_id": ("evaluationPackageId", "evaluation_package_id"),
        "candidate_decision_id": ("candidateDecisionId", "candidate_decision_id"),
    }
    if (
        str(context.get("evidence_scope") or "").strip()
        == SELECTION_REVIEW_EVIDENCE_SCOPE
    ):
        aliases.pop("evaluation_package_id", None)
        aliases.pop("candidate_decision_id", None)
    for field, field_aliases in aliases.items():
        expected = str(context.get(field) or "").strip()
        values = _version_bound_value(version, field_aliases)
        if not expected or not values:
            raise HTTPException(
                status_code=409,
                detail=f"The registered model version is missing its exact {field} binding.",
            )
        if any(value != expected for value in values):
            raise HTTPException(
                status_code=409,
                detail=f"The registered model version does not match the exact {field}.",
            )
    artifact = REGISTRY.load_version_artifact(
        user,
        model_version_id,
        expected_project_id=context["project_id"],
    )
    return {
        **context,
        "_registered_artifact": artifact,
        "_registered_version": version,
    }


def _interpretation_context(
    evaluation_package_id: str = Query(""),
    model_version_id: str = Query(""),
    context: Dict[str, Any] = Depends(_lineage_context),
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    authorize_modeling_scope(user, context["project_id"], "view")
    normalized_package_id = str(evaluation_package_id or "").strip()
    if (
        str(context.get("evidence_scope") or "").strip()
        != SELECTION_REVIEW_EVIDENCE_SCOPE
        and not normalized_package_id
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Exact Interpretation lineage is required: "
                "evaluation_package_id"
            ),
        )
    return _prepare_interpretation_context(
        user,
        {
            **context,
            "evaluation_package_id": normalized_package_id,
            "model_version_id": str(model_version_id).strip(),
        },
    )


def _request_context(request: Dict[str, Any]) -> dict:
    required = (
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
        "candidate_decision_id",
        "evaluation_package_id",
    )
    missing = [field for field in required if not str(request.get(field) or "").strip()]
    if missing:
        raise HTTPException(
            status_code=422,
            detail="Exact Evaluation lineage is required: " + ", ".join(missing),
        )
    lineage_fields = required[:-1]
    return {
        **_context(**{field: str(request[field]).strip() for field in lineage_fields}),
        "evaluation_package_id": str(request["evaluation_package_id"]).strip(),
    }


def _lineage_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    if payload.get("lineage_error"):
        raise HTTPException(status_code=409, detail=str(payload.get("error") or "Evaluation lineage mismatch."))
    return payload


def _evaluation_response(
    model: str,
    context: Dict[str, Any],
    payload: Dict[str, Any],
    analysis_type: str,
    actor_user_id: str,
) -> Dict[str, Any]:
    if (
        str(context.get("evidence_scope") or "").strip()
        == SELECTION_REVIEW_EVIDENCE_SCOPE
    ):
        population = (
            "development_out_of_fold"
            if analysis_type in {"curves", "deciles", "command_center"}
            else "development_population"
        )
        return _lineage_response(
            EVAL.bind_selection_review(
                model,
                context,
                payload,
                analysis_type,
                population,
            )
        )
    bound = EVAL.bind_evaluation_package(
        model,
        context,
        payload,
        analysis_type,
        actor_user_id=actor_user_id,
    )
    if bound.get("ok"):
        package = bound.get("evaluation_package")
        complete = (
            analysis_type == "command_center"
            and isinstance(package, dict)
            and package.get("status") == "complete"
        )
        if complete:
            try:
                checkpointed = flush_checkpoint()
            except Exception:
                checkpointed = False
            if not checkpointed:
                RESULTS.delete_evaluation_package(
                    str(bound.get("evaluation_package_id") or "")
                )
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "The completed evaluation package could not be durably "
                        "checkpointed. Retry Evaluation before continuing."
                    ),
                )
        else:
            schedule_checkpoint_save()
    return _lineage_response(bound)


def _interpretation_response(
    model: str,
    context: Dict[str, Any],
    payload: Dict[str, Any],
    analysis_type: str,
) -> Dict[str, Any]:
    if (
        str(context.get("evidence_scope") or "").strip()
        == SELECTION_REVIEW_EVIDENCE_SCOPE
    ):
        return _lineage_response(
            EVAL.bind_selection_review(
                model,
                context,
                payload,
                analysis_type,
                "development_population",
            )
        )
    return _lineage_response(
        EVAL.bind_interpretation_artifact(
            model,
            context,
            payload,
            analysis_type,
            context.get("evaluation_package_id") or "",
        )
    )


def _publish_final_version(
    user: Dict[str, Any],
    context: Dict[str, Any],
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Publish the just-created final artifact through the durable registry."""
    candidate_id = context["candidate_id"]
    evaluation_package_id = context["evaluation_package_id"]
    metadata = result.get("metadata") or {}
    handoff = EVAL.registry_promotion_handoff(
        candidate_id,
        context,
        metadata,
        evaluation_package_id,
    )
    if not handoff.get("ready"):
        raise HTTPException(status_code=409, detail=str(handoff.get("error") or "Registry handoff is not ready."))
    fitted_object = result.get("_fitted_object")
    if fitted_object is None:
        raise HTTPException(
            status_code=409,
            detail="The exact resolved candidate artifact is unavailable for durable publication.",
        )
    promotion_metadata = handoff.get("promotion_metadata")
    promotion_metadata = (
        promotion_metadata if isinstance(promotion_metadata, dict) else {}
    )
    candidate_model_name = str(
        promotion_metadata.get("model_name") or ""
    ).strip()
    if not candidate_model_name:
        raise HTTPException(
            status_code=409,
            detail="The exact candidate has no durable human-readable model name.",
        )

    metrics_summary = metadata.get("metrics") or {
        key: metadata.get(key)
        for key in ("holdout_auc", "holdout_rmse", "holdout_r2", "holdout_adjusted_r2")
        if metadata.get(key) is not None
    }
    interpretation_summary = {
        "selectedFeatures": metadata.get("features") or [],
        "featureCount": metadata.get("feature_count"),
        "method": "Recursive Feature Elimination" if str(metadata.get("model_key") or "").startswith("final_rfe") else "Selected trained candidate",
    }
    publication = REGISTRY.create_model_version(
        user,
        context["project_id"],
        model_name=(
            f"ATLAS::{context['dataset_id']}::"
            f"{context['dataset_version_id']}::{context['target']}"
        ),
        candidate_model_name=candidate_model_name,
        problem_type=context["problem_type"],
        algorithm=str(handoff["algorithm_id"]),
        algorithm_version=str(handoff.get("algorithm_version") or metadata.get("source_estimator_class") or "unknown"),
        fitted_object=fitted_object,
        hyperparameters=handoff.get("hyperparameters") or {},
        training_parameters=handoff.get("training_parameters") or {},
        metrics_summary=metrics_summary,
        evaluation_summary=handoff.get("evaluation_summary") or {},
        interpretation_summary=interpretation_summary,
        training_run_id=context["training_run_id"],
        dataset_id=context["dataset_id"],
        dataset_version_id=context["dataset_version_id"],
        feature_manifest_version=context["feature_manifest_version"],
        training_timestamp=handoff["candidate_contract"].get("created_at"),
        lineage=handoff["lineage"],
        candidate_contract=handoff["candidate_contract"],
        evaluation_package_id=handoff["evaluation_package_id"],
        idempotency_key=handoff["idempotency_key"],
    )
    model = publication.get("model")
    version = publication.get("modelVersion")
    promotion = publication.get("promotion")
    expected_version = {
        "projectId": context["project_id"],
        "datasetId": context["dataset_id"],
        "datasetVersionId": context["dataset_version_id"],
        "candidateId": context["candidate_id"],
        "trainingRunId": context["training_run_id"],
        "featureManifestVersion": context["feature_manifest_version"],
        "evaluationPackageId": handoff["evaluation_package_id"],
        "candidateDecisionId": context["candidate_decision_id"],
    }
    if not isinstance(model, dict) or not isinstance(version, dict) or not isinstance(promotion, dict):
        raise HTTPException(status_code=409, detail="The durable registry returned an incomplete publication response.")
    if any(str(version.get(key) or "") != value for key, value in expected_version.items()):
        raise HTTPException(status_code=409, detail="The durable model version does not match the exact candidate lineage.")
    if (
        promotion.get("status") != "finalized"
        or promotion.get("artifactVerified") is not True
        or str(promotion.get("lineageStatus") or "") != "verified"
    ):
        raise HTTPException(status_code=409, detail="The durable model publication is not finalized and verified.")

    model_version_id = str(version.get("modelVersionId") or "")
    if not model_version_id:
        raise HTTPException(status_code=409, detail="The durable registry did not return an exact modelVersionId.")
    enriched_metadata = {
        **metadata,
        "model_id": model.get("modelId"),
        "modelId": model.get("modelId"),
        "model_version_id": model_version_id,
        "modelVersionId": model_version_id,
        "publication_status": promotion["status"],
        "artifact_verified": True,
        "registry_checksum": promotion.get("checksum"),
        "lineage_status": promotion.get("lineageStatus"),
    }
    RESULTS.set_final_model(fitted_object, enriched_metadata)
    return {
        "ok": True,
        "metadata": enriched_metadata,
        "model": model,
        "modelVersion": version,
        "promotion": promotion,
    }


def _audit_promotion_event(
    *,
    user: Dict[str, Any],
    outcome: str,
    correlation_id: str,
    context: Dict[str, Any],
    publication: Dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    version = (publication or {}).get("modelVersion") or {}
    promotion = (publication or {}).get("promotion") or {}
    metadata = {
        "projectId": context.get("project_id"),
        "candidateId": context.get("candidate_id"),
        "evaluationPackageId": context.get("evaluation_package_id"),
        "datasetVersionId": context.get("dataset_version_id"),
        "modelVersionId": version.get("modelVersionId"),
        "checksum": promotion.get("checksum"),
        "previousChampionVersionId": version.get("previousChampionVersionId"),
        "correlationId": correlation_id,
    }
    if error is not None:
        metadata["errorClass"] = error.__class__.__name__
    try:
        audit_event(
            "model.promotion.succeeded" if outcome == "success" else "model.promotion.failed",
            "model_version" if version.get("modelVersionId") else "model_candidate",
            version.get("modelVersionId") or context.get("candidate_id"),
            outcome,
            reason=None if error is None else "Model promotion did not complete.",
            metadata=metadata,
            user_id=str(user.get("userId") or ""),
        )
    except Exception:
        # Publication/audit failures must retain the original user-safe result;
        # the audit sink never receives fitted objects or raw exception text.
        pass


def _promotion_response(
    request: Dict[str, Any],
    user: Dict[str, Any],
    *,
    rfe: bool,
) -> Dict[str, Any] | JSONResponse:
    correlation_id = f"promotion-{uuid.uuid4().hex}"
    context: Dict[str, Any] = {
        key: str(request.get(key) or "").strip()
        for key in (
            "project_id",
            "dataset_version_id",
            "candidate_id",
            "evaluation_package_id",
        )
    }
    try:
        context = _request_context(request)
        authorize_modeling_scope(user, context["project_id"], "edit")
        if rfe:
            result = EVAL.save_rfe_model(
                model_name=context["candidate_id"],
                keep=int(request.get("keep") or 10),
                context=context,
                evaluation_package_id=context["evaluation_package_id"],
            )
        else:
            result = EVAL.save_selected_model_as_final(
                model_name=context["candidate_id"],
                context=context,
                evaluation_package_id=context["evaluation_package_id"],
            )
        if not result.get("ok"):
            raise HTTPException(
                status_code=409,
                detail=str(result.get("error") or "The exact model promotion preconditions were not met."),
            )
        publication = _publish_final_version(user, context, result)
        schedule_checkpoint_save()
        _audit_promotion_event(
            user=user,
            outcome="success",
            correlation_id=correlation_id,
            context=context,
            publication=publication,
        )
        return {**publication, "correlation_id": correlation_id}
    except Exception as exc:
        _audit_promotion_event(
            user=user,
            outcome="failure",
            correlation_id=correlation_id,
            context=context,
            error=exc,
        )
        if isinstance(exc, HTTPException):
            status_code = int(exc.status_code)
            error_message = str(exc.detail)
        else:
            status_code = 500
            error_message = "Durable model publication could not be completed."
        return JSONResponse(
            status_code=status_code,
            content={
                "ok": False,
                "error": error_message,
                "correlation_id": correlation_id,
            },
        )


@router.get("/eval/curves")
def get_curves(
    context: Dict[str, Any] = Depends(_lineage_context),
    user: Dict[str, Any] = Depends(require_user),
):
    """Return governed holdout curves or explicit persisted-OOF review curves."""
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _evaluation_response(candidate_id, context, EVAL.get_curves(candidate_id, context), "curves", str(user.get("userId") or ""))


@router.get("/eval/deciles")
def get_deciles(
    context: Dict[str, Any] = Depends(_lineage_context),
    user: Dict[str, Any] = Depends(require_user),
):
    """Return governed holdout deciles or explicit persisted-OOF review deciles."""
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _evaluation_response(candidate_id, context, EVAL.get_deciles(candidate_id, context), "deciles", str(user.get("userId") or ""))


@router.get("/eval/command_center")
def get_evaluation_command_center(
    threshold: float | None = None,
    review_capacity: float = 0.1,
    context: Dict[str, Any] = Depends(_lineage_context),
    user: Dict[str, Any] = Depends(require_user),
):
    """Return governed reporting or explicit read-only selection review.

    The endpoint never optimizes or recommends thresholds from final-holdout
    labels or scores. Selection review uses persisted OOF evidence only.
    """
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _evaluation_response(
        candidate_id,
        context,
        EVAL.get_evaluation_command_center(
            candidate_id,
            threshold=threshold,
            review_capacity=review_capacity,
            context=context,
        ),
        "command_center",
        str(user.get("userId") or ""),
    )


@router.get("/eval/tree")
def get_decision_tree(
    max_depth: int = 4,
    context: Dict[str, Any] = Depends(_lineage_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _evaluation_response(
        candidate_id,
        context,
        EVAL.decision_tree(candidate_id, max_depth=max_depth, context=context),
        "decision_tree",
        str(user.get("userId") or ""),
    )


@router.get("/eval/knn_clusters")
def get_knn_clusters(
    max_points: int = 900,
    context: Dict[str, Any] = Depends(_lineage_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _evaluation_response(
        candidate_id,
        context,
        EVAL.knn_clusters(candidate_id, max_points=max_points, context=context),
        "knn_clusters",
        str(user.get("userId") or ""),
    )


@router.get("/interpretation/importance")
def get_feature_importance(
    context: Dict[str, Any] = Depends(_interpretation_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _interpretation_response(
        candidate_id, context, EVAL.feature_importance(candidate_id, context), "feature_importance"
    )


@router.get("/interpretation/details")
def get_model_details(
    context: Dict[str, Any] = Depends(_interpretation_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _interpretation_response(
        candidate_id, context, EVAL.model_details(candidate_id, context), "model_details"
    )


@router.get("/interpretation/debug")
def get_model_debug(
    context: Dict[str, Any] = Depends(_interpretation_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _interpretation_response(
        candidate_id, context, EVAL.model_details(candidate_id, context), "model_debug"
    )


@router.get("/interpretation/hyperparameters")
def get_hyperparameters(
    context: Dict[str, Any] = Depends(_interpretation_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _interpretation_response(
        candidate_id, context, EVAL.hyperparameters(candidate_id, context), "hyperparameters"
    )


@router.get("/interpretation/pdp")
def get_pdp(
    feature: str,
    context: Dict[str, Any] = Depends(_interpretation_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _interpretation_response(
        candidate_id, context, EVAL.pdp(candidate_id, feature, context), "partial_dependence"
    )


@router.get("/interpretation/sensitivity")
def get_sensitivity(
    feature: str,
    context: Dict[str, Any] = Depends(_interpretation_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _interpretation_response(
        candidate_id, context, EVAL.sensitivity(candidate_id, feature, context), "sensitivity"
    )


@router.get("/interpretation/sensitivity_summary")
def get_sensitivity_summary(
    top_n: int = 12,
    context: Dict[str, Any] = Depends(_interpretation_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _interpretation_response(
        candidate_id,
        context,
        EVAL.sensitivity_summary(candidate_id, top_n=top_n, context=context),
        "sensitivity_summary",
    )


@router.get("/interpretation/vsi")
def get_vsi_summary(
    top_n: int = 40,
    context: Dict[str, Any] = Depends(_interpretation_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _interpretation_response(
        candidate_id, context, EVAL.vsi_summary(candidate_id, top_n=top_n, context=context), "vsi"
    )


@router.get("/interpretation/vif")
def get_vif_summary(
    context: Dict[str, Any] = Depends(_interpretation_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _interpretation_response(
        candidate_id, context, EVAL.vif_summary(candidate_id, context=context), "vif"
    )


@router.get("/interpretation/shap")
def get_shap_summary(
    context: Dict[str, Any] = Depends(_interpretation_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _interpretation_response(
        candidate_id, context, EVAL.shap_summary(candidate_id, context), "shap_summary"
    )


@router.get("/interpretation/decision_boundary")
def get_decision_boundary(
    x_feature: str = "",
    y_feature: str = "",
    context: Dict[str, Any] = Depends(_interpretation_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _interpretation_response(
        candidate_id,
        context,
        EVAL.decision_boundary(
            model_name=candidate_id,
            x_feature=x_feature,
            y_feature=y_feature,
            context=context,
        ),
        "decision_boundary",
    )


@router.get("/interpretation/rfe")
def get_rfe(
    keep: int = 10,
    context: Dict[str, Any] = Depends(_interpretation_context),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, context["project_id"], "view")
    candidate_id = context["candidate_id"]
    return _interpretation_response(
        candidate_id,
        context,
        EVAL.rfe(model_name=candidate_id, keep=keep, context=context),
        "recursive_feature_elimination",
    )


@router.post("/interpretation/rfe/save_final")
def save_rfe_final_model(request: dict, user: Dict[str, Any] = Depends(require_user)):
    return _promotion_response(request, user, rfe=True)


@router.post("/model/save_final")
def save_selected_final_model(request: dict, user: Dict[str, Any] = Depends(require_user)):
    return _promotion_response(request, user, rfe=False)


@router.get("/model/final/status")
def get_final_model_status(
    project_id: str = Query(...),
    dataset_id: str = Query(...),
    dataset_version_id: str = Query(...),
    target: str = Query(...),
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    resolved = REGISTRY.resolve_current_version_by_exact_context(
        user,
        project_id=project_id,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        target_name=target,
    )
    version = resolved.get("modelVersion")
    if resolved.get("status") != "ready" or not isinstance(version, dict):
        return {
            "ok": True,
            "ready": False,
            "artifact_present": False,
            "stale": False,
            "blocker": resolved.get("reason") or "No exact current registered model version is available.",
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "target": target,
            "metadata": {},
            "recovery": resolved,
            "modelVersion": None,
        }
    model_version_id = str(resolved.get("modelVersionId") or version.get("modelVersionId") or "")
    lineage = version.get("lineage") if isinstance(version.get("lineage"), dict) else {}
    model_name = str(resolved.get("modelName") or "").strip()
    metadata = {
        **version,
        "project_id": project_id,
        "dataset_id": dataset_id,
        "training_dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "training_dataset_version_id": dataset_version_id,
        "target": target,
        "target_name": target,
        "candidate_id": version.get("candidateId") or lineage.get("candidateId"),
        "training_run_id": version.get("trainingRunId") or lineage.get("trainingRunId"),
        "feature_manifest_version": version.get("featureManifestVersion") or lineage.get("featureManifestVersion"),
        "validation_design_id": version.get("validationDesignId") or lineage.get("validationDesignId"),
        "validation_design_version": lineage.get("validationDesignVersion"),
        "split_id": version.get("splitId") or lineage.get("splitId"),
        "model_id": resolved.get("modelId"),
        "name": model_name,
        "model_name": model_name,
        "modelName": model_name,
        "model_version_id": model_version_id,
        "modelId": resolved.get("modelId"),
        "modelVersionId": model_version_id,
        "publication_status": resolved.get("publicationStatus"),
        "promotion_status": resolved.get("publicationStatus"),
        "lineage_status": resolved.get("lineageStatus"),
        "artifact_verified": resolved.get("artifactVerified") is True,
        "artifact_verification_status": "verified" if resolved.get("artifactVerified") is True else "unverified",
        "artifact_checksum": resolved.get("checksum"),
        "checksum": resolved.get("checksum"),
        "artifact_format": resolved.get("artifactFormat"),
        "designation": "champion",
        "champion_status": "champion",
    }
    required_readiness = (
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "target",
        "candidate_id",
        "training_run_id",
        "feature_manifest_version",
        "validation_design_id",
        "split_id",
        "model_version_id",
        "artifact_checksum",
        "promotion_status",
        "lineage_status",
        "designation",
    )
    if any(not str(metadata.get(key) or "").strip() for key in required_readiness):
        raise HTTPException(status_code=409, detail="The exact current model version is missing durable readiness lineage.")
    if (
        metadata["promotion_status"] != "finalized"
        or metadata["lineage_status"] != "verified"
        or metadata["artifact_verified"] is not True
        or metadata["designation"] != "champion"
    ):
        raise HTTPException(status_code=409, detail="The exact current model version is not finalized, verified, and champion-designated.")
    return {
        "ok": True,
        "ready": True,
        "artifact_present": True,
        "stale": False,
        "blocker": None,
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "target": target,
        "model_version_id": model_version_id,
        "modelVersionId": model_version_id,
        "metadata": metadata,
        "recovery": resolved,
        "modelVersion": version,
    }


@router.get("/model/export")
def export_model(
    project_id: str = Query(...),
    model_version_id: str = Query(...),
    format: str = "json",
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "view")
    if format.lower() not in {"json", "manifest"}:
        return {
            "ok": False,
            "error": "Only JSON model manifests are exported. Executable model objects must be deployed through a signed model registry or approved ONNX/skops pipeline.",
        }
    artifact = REGISTRY.load_version_artifact(
        user,
        model_version_id,
        expected_project_id=project_id,
    )
    version = REGISTRY.get_version(user, model_version_id)
    content = json.dumps(
        {
            "exportType": "registered_model_manifest_v1",
            "modelVersion": version,
            "artifactClass": artifact.__class__.__name__,
            "artifactModule": artifact.__class__.__module__,
            "note": "The executable artifact remains in verified durable registry storage.",
        },
        sort_keys=True,
        indent=2,
        default=str,
    ).encode("utf-8")
    filename = f"atlas_model_{model_version_id}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _resolve_exact_scoring_version(
    user: Dict[str, Any],
    *,
    project_id: str,
    model_version_id: str,
    dataset_id: str,
    dataset_version_id: str,
    target: str,
) -> tuple[Any, Dict[str, Any]]:
    """Resolve one immutable registry version for scoring, never a champion.

    The caller authorizes ``project_id`` before entering this helper.  The
    registry independently authorizes the version's owning project, and the
    explicit comparisons below prevent a caller who can access two projects
    from combining one project's version with the other's scoring context.
    """

    requested = {
        "projectId": str(project_id or "").strip(),
        "modelVersionId": str(model_version_id or "").strip(),
        "datasetId": str(dataset_id or "").strip(),
        "datasetVersionId": str(dataset_version_id or "").strip(),
        "targetName": str(target or "").strip(),
    }
    missing = [key for key, value in requested.items() if not value]
    if missing:
        raise HTTPException(
            status_code=422,
            detail="Exact scoring context is required: " + ", ".join(missing),
        )

    version = REGISTRY.get_version(user, requested["modelVersionId"])
    for field in ("modelVersionId", "projectId", "datasetId", "datasetVersionId", "targetName"):
        if str(version.get(field) or "").strip() != requested[field]:
            raise HTTPException(
                status_code=409,
                detail=f"The exact registered model version does not match {field}.",
            )
    if (
        str(version.get("publicationStatus") or "").casefold() != "finalized"
        or str(version.get("lineageStatus") or "").casefold() != "verified"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The exact registered model version is not finalized with "
                "verified lineage."
            ),
        )

    lineage = version.get("lineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    candidate_contract = lineage.get("candidateContract")
    if not isinstance(candidate_contract, dict):
        raise HTTPException(
            status_code=409,
            detail="The exact registered model version has no frozen candidate contract.",
        )
    model_contract = (
        version.get("modelContract")
        if isinstance(version.get("modelContract"), dict)
        else {}
    )
    target_definition = candidate_contract.get("target_definition")
    target_definition = target_definition if isinstance(target_definition, dict) else {}
    problem_type = str(
        candidate_contract.get("problem_type")
        or target_definition.get("problem_type")
        or ""
    ).strip().casefold()
    if problem_type not in {"classification", "regression"}:
        raise HTTPException(
            status_code=409,
            detail="The exact registered model version has no valid frozen problem type.",
        )

    # This is the only executable-artifact load in either scoring route.  The
    # registry verifies checksum, immutable lineage, and project ownership as
    # part of deserialization; there is deliberately no RESULTS/latest/final
    # recovery branch.
    artifact = REGISTRY.load_version_artifact(
        user,
        requested["modelVersionId"],
        expected_project_id=requested["projectId"],
    )

    interpretation = version.get("interpretationSummary")
    interpretation = interpretation if isinstance(interpretation, dict) else {}
    features = interpretation.get("selectedFeatures")
    if not isinstance(features, list):
        features = [
            *list(candidate_contract.get("selected_original_features") or []),
            *list(candidate_contract.get("selected_engineered_features") or []),
        ]
    threshold_configuration = candidate_contract.get("threshold_configuration")
    threshold_configuration = (
        threshold_configuration
        if isinstance(threshold_configuration, dict)
        else {}
    )
    locked_threshold = version.get("lockedThreshold")
    if locked_threshold is None:
        locked_threshold = threshold_configuration.get("locked_threshold")
    positive_class = lineage.get("positiveClass")
    if positive_class is None:
        positive_class = candidate_contract.get("positive_class")

    metadata = {
        "modelId": version.get("modelId"),
        "modelVersionId": requested["modelVersionId"],
        "modelVersion": version.get("versionNumber"),
        "model_key": str(
            version.get("algorithm")
            or candidate_contract.get("algorithm_id")
            or requested["modelVersionId"]
        ),
        "name": str(
            version.get("algorithm")
            or candidate_contract.get("algorithm_id")
            or requested["modelVersionId"]
        ),
        "project_id": requested["projectId"],
        "projectId": requested["projectId"],
        "dataset_id": requested["datasetId"],
        "datasetId": requested["datasetId"],
        "dataset_version_id": requested["datasetVersionId"],
        "datasetVersionId": requested["datasetVersionId"],
        "target": requested["targetName"],
        "target_name": requested["targetName"],
        "targetName": requested["targetName"],
        "problem_type": problem_type,
        "problemType": problem_type,
        "features": [str(value) for value in features],
        "trained_feature_names": [str(value) for value in features],
        "feature_manifest_version": version.get("featureManifestVersion"),
        "featureManifestVersion": version.get("featureManifestVersion"),
        "candidate_contract": candidate_contract,
        "candidateContract": candidate_contract,
        "candidate_decision_id": model_contract.get("candidateDecisionId"),
        "candidateDecisionId": model_contract.get("candidateDecisionId"),
        "final_preprocessing_artifact": model_contract.get(
            "finalPreprocessingArtifact"
        ),
        "preprocessing_contract_version": model_contract.get(
            "preprocessingContractVersion"
        ),
        "preprocessing_policy_id": model_contract.get(
            "preprocessingPolicyId"
        ),
        "preprocessing_policy_revision": model_contract.get(
            "preprocessingPolicyRevision"
        ),
        "preprocessing_policy_hash": model_contract.get(
            "preprocessingPolicyHash"
        ),
        "final_preprocessing_artifact_checksum": model_contract.get(
            "finalPreprocessingArtifactChecksum"
        ),
        "preprocessing_fit_scope": model_contract.get(
            "preprocessingFitScope"
        ),
        "preprocessing_fit_population_id": model_contract.get(
            "preprocessingFitPopulationId"
        ),
        "preprocessing_fit_population_rows": model_contract.get(
            "preprocessingFitPopulationRows"
        ),
        "locked_threshold": locked_threshold,
        "lockedThreshold": locked_threshold,
        "threshold_source": version.get("thresholdSource")
        or threshold_configuration.get("threshold_source"),
        "positive_class": positive_class,
        "positiveClass": positive_class,
        "publication_status": "finalized",
        "publicationStatus": "finalized",
        "lineage_status": "verified",
        "lineageStatus": "verified",
        "artifactVerified": True,
        "artifactChecksum": version.get("checksum"),
        "trainingTimestamp": version.get("trainingTimestamp"),
        "lineage": lineage,
    }
    return artifact, metadata


@router.post("/score/upload")
async def score_upload(
    file: UploadFile = File(...),
    project_id: str = Query(...),
    model_version_id: str = Query(...),
    dataset_id: str = Query(...),
    dataset_version_id: str = Query(...),
    target: str = Query(...),
    dataset_type: str = "test",
    correction_method: str = "none",
    original_prior: float | None = None,
    model_prior: float | None = None,
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "edit")
    artifact, model_metadata = _resolve_exact_scoring_version(
        user,
        project_id=project_id,
        model_version_id=model_version_id,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        target=target,
    )
    content = await file.read()
    df = pd.read_csv(io.BytesIO(content))
    result = EVAL.score_dataset(
        df=df,
        dataset_type=dataset_type,
        correction_method=correction_method,
        original_prior=original_prior,
        model_prior=model_prior,
        model_artifact=artifact,
        model_metadata=model_metadata,
    )
    result.setdefault("model", model_metadata)
    exact_context = {
        "datasetIdentity": file.filename or f"{dataset_type.upper()} upload",
        "source": "csv_upload",
        "projectId": project_id,
        "datasetId": dataset_id,
        "datasetVersionId": dataset_version_id,
        "target": target,
        "modelId": model_metadata.get("modelId"),
        "modelVersion": model_metadata.get("modelVersion"),
        "modelVersionId": model_version_id,
        "featureManifestVersion": model_metadata.get("featureManifestVersion"),
        "problemType": model_metadata.get("problemType"),
    }
    if result.get("ok"):
        result["dataset_identity"] = file.filename or f"{dataset_type.upper()} upload"
        result["dataset_version"] = f"sha256:{hashlib.sha256(content).hexdigest()[:16]}"
        date_candidates = [
            column for column in df.columns
            if any(token in str(column).strip().lower() for token in ("date", "time", "timestamp", "as_of", "asof"))
        ]
        for column in date_candidates:
            parsed = pd.to_datetime(df[column], errors="coerce")
            if parsed.notna().mean() >= 0.8:
                result["period"] = {
                    "column": str(column),
                    "start": parsed.min().isoformat(),
                    "end": parsed.max().isoformat(),
                }
                break
        scoring_run = create_scoring_run(
            user, project_id, dataset_type, result,
            dataset_context=exact_context,
        )
        if not scoring_run:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Scoring completed, but its exact durable scoring-run "
                    "record could not be persisted. No success was returned."
                ),
            )
        result["scoringRunId"] = scoring_run["scoringRunId"]
        schedule_checkpoint_save()
    else:
        failed_run = create_failed_scoring_run(
            user, project_id, dataset_type, str(result.get("error") or "Scoring failed."),
            dataset_context=exact_context,
        )
        if not failed_run:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Scoring failed and its exact durable failure record could "
                    "not be persisted."
                ),
            )
        result["scoringRunId"] = failed_run["scoringRunId"]
    return result


@router.post("/score/development-split")
def score_development_split(
    project_id: str = Query(...),
    model_version_id: str = Query(...),
    dataset_id: str = Query(...),
    dataset_version_id: str = Query(...),
    target: str = Query(...),
    dataset_type: str = "train",
    correction_method: str = "none",
    original_prior: float | None = None,
    model_prior: float | None = None,
    user: Dict[str, Any] = Depends(require_user),
):
    authorize_modeling_scope(user, project_id, "edit")
    artifact, model_metadata = _resolve_exact_scoring_version(
        user,
        project_id=project_id,
        model_version_id=model_version_id,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        target=target,
    )
    result = EVAL.score_development_split(
        dataset_type=dataset_type,
        correction_method=correction_method,
        original_prior=original_prior,
        model_prior=model_prior,
        model_artifact=artifact,
        model_metadata=model_metadata,
    )
    result.setdefault("model", model_metadata)
    exact_context = {
        "datasetIdentity": result.get("dataset_identity"),
        "source": "development_split",
        "projectId": project_id,
        "datasetId": dataset_id,
        "datasetVersionId": dataset_version_id,
        "target": target,
        "modelId": model_metadata.get("modelId"),
        "modelVersion": model_metadata.get("modelVersion"),
        "modelVersionId": model_version_id,
        "featureManifestVersion": model_metadata.get("featureManifestVersion"),
        "problemType": model_metadata.get("problemType"),
    }
    if result.get("ok"):
        scoring_run = create_scoring_run(
            user, project_id, result.get("dataset_type", dataset_type), result,
            dataset_context=exact_context,
        )
        if not scoring_run:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Scoring completed, but its exact durable scoring-run "
                    "record could not be persisted. No success was returned."
                ),
            )
        result["scoringRunId"] = scoring_run["scoringRunId"]
        schedule_checkpoint_save()
    else:
        failed_run = create_failed_scoring_run(
            user, project_id, dataset_type, str(result.get("error") or "Scoring failed."),
            dataset_context=exact_context,
        )
        if not failed_run:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Scoring failed and its exact durable failure record could "
                    "not be persisted."
                ),
            )
        result["scoringRunId"] = failed_run["scoringRunId"]
    return result
