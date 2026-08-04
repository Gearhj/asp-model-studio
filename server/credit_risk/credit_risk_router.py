from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..security.security_store import audit_event, require_user
from .credit_risk_store import (
    compute_readiness,
    create_credit_risk_evidence,
    export_profile_excel,
    get_profile,
    get_project_profile_exact,
    list_profiles,
    save_profile,
)
from .credit_risk_types import CreditRiskEvidenceRequest, CreditRiskProfile
from .credit_risk_types import (
    ChampionComparisonRunRequest,
    ChampionDecisionRequest,
    ChampionEvidenceRequest,
    CreditRiskDatasetSummaryRequest,
    CreditRiskMlEvidenceRequest,
    CreditRiskMlTrainRequest,
    ScorecardEvidenceRequest,
    ScorecardModelIdRequest,
    ScorecardRegisterRequest,
    ScorecardTrainRequest,
    WoeIvAnalysisIdRequest,
    WoeIvEvidenceRequest,
    WoeIvManualBinsRequest,
    WoeIvRunRequest,
    WoeIvSaveRequest,
)
from ..datasets.dataset_identity import assert_expected_active_identity
from ..core.modeling_scope import authorize_modeling_scope
from .governed_scope import (
    artifact_scope_payload,
    canonical_scope_fields,
    require_artifact_scope,
    resolve_credit_risk_project_scope,
    resolve_credit_risk_scope,
)
from .ml_engine import (
    create_ml_evidence,
    get_ml_model,
    get_project_ml_model_exact,
    run_champion_comparison,
    save_ml_model,
    train_ml_model,
)
from .scorecard_engine import (
    create_scorecard_evidence,
    export_scorecard_excel,
    generate_scorecard_code,
    get_project_scorecard_exact,
    get_scorecard_model,
    register_scorecard_model,
    train_scorecard,
)
from .woe_iv_engine import (
    apply_manual_bins,
    authorized_predictors_for_request,
    create_woe_iv_evidence,
    export_woe_iv_excel,
    generate_code,
    get_analysis,
    get_project_analysis_exact,
    run_woe_iv,
    save_analysis,
)

import io


router = APIRouter(dependencies=[Depends(require_user)])


def _stored_artifact_scope(
    artifact: Mapping[str, Any],
    user: Mapping[str, Any],
    *,
    label: str,
    access: str = "view",
):
    _, _, scope = resolve_credit_risk_scope(
        artifact_scope_payload(artifact),
        user,
        access=access,
    )
    require_artifact_scope(artifact, scope, artifact_label=label)
    return scope


def _require_analysis(analysis_id: str) -> Dict[str, Any]:
    analysis = get_analysis(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="WOE / IV analysis not found.")
    return analysis


def _require_scorecard(model_id: str) -> Dict[str, Any]:
    model = get_scorecard_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Scorecard model not found.")
    return model


def _require_ml_model(model_id: str) -> Dict[str, Any]:
    model = get_ml_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="AI/ML underwriting model not found.")
    return model


def _profile_binding(
    profile: Mapping[str, Any],
    user: Mapping[str, Any],
    *,
    access: str,
    require_analysis_scope: bool,
):
    project_id = str(profile.get("projectId") or "").strip()
    authorize_modeling_scope(dict(user), project_id, access)
    dataset_id = str(profile.get("datasetId") or "").strip()
    dataset_version_id = str(profile.get("datasetVersionId") or "").strip()
    if bool(dataset_id) != bool(dataset_version_id):
        raise HTTPException(
            status_code=422,
            detail="Credit Risk profiles must bind datasetId and datasetVersionId together.",
        )
    if require_analysis_scope:
        _, _, scope = resolve_credit_risk_scope(profile, user, access=access)
        return scope
    if dataset_id:
        assert_expected_active_identity(
            project_id,
            expected_dataset_id=dataset_id,
            expected_dataset_version_id=dataset_version_id,
            require_expected=True,
            user=dict(user),
        )
    return None


def _governed_profile_payload(
    profile: Mapping[str, Any],
    scope: Any,
) -> Dict[str, Any]:
    return {
        **dict(profile),
        **canonical_scope_fields(scope),
        "projectId": scope.identity["project_id"],
        "datasetId": scope.identity["dataset_id"],
        "datasetVersionId": scope.identity["dataset_version_id"],
        "targetColumn": scope.target,
        "eventValue": scope.event_value,
        "nonEventValue": scope.non_event_value,
    }


@router.get("/credit-risk/profile")
def read_credit_risk_profile(
    profileId: Optional[str] = None,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    if not profileId:
        raise HTTPException(
            status_code=422,
            detail="An exact profileId is required; global first/latest profile fallback is prohibited.",
        )
    profile = get_profile(profileId)
    if not profile:
        raise HTTPException(status_code=404, detail="Credit Risk profile not found.")
    project_id = str(profile.get("projectId") or "")
    dataset_id = str(profile.get("datasetId") or "")
    dataset_version_id = str(profile.get("datasetVersionId") or "")
    if not project_id or not dataset_id or not dataset_version_id:
        raise HTTPException(
            status_code=409,
            detail="The Credit Risk profile does not contain exact project/dataset/version identity.",
        )
    assert_expected_active_identity(
        project_id,
        expected_dataset_id=dataset_id,
        expected_dataset_version_id=dataset_version_id,
        require_expected=True,
        user=user,
    )
    return {"ok": True, "profile": profile}


@router.post("/credit-risk/profile")
def create_credit_risk_profile(
    payload: CreditRiskProfile,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    _profile_binding(payload.model_dump(), user, access="edit", require_analysis_scope=False)
    profile = save_profile(payload.model_dump())
    audit_event("credit_risk.profile.saved", "credit_risk_profile", profile.get("profileId"), "success", metadata={"projectId": profile.get("projectId")})
    return {"ok": True, "profile": profile}


@router.put("/credit-risk/profile/{profile_id}")
def update_credit_risk_profile(
    profile_id: str,
    payload: CreditRiskProfile,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    if payload.profileId and payload.profileId != profile_id:
        raise HTTPException(status_code=400, detail="Profile ID mismatch.")
    candidate = {**payload.model_dump(), "profileId": profile_id}
    _profile_binding(candidate, user, access="edit", require_analysis_scope=False)
    profile = save_profile(candidate)
    audit_event("credit_risk.profile.saved", "credit_risk_profile", profile.get("profileId"), "success", metadata={"projectId": profile.get("projectId")})
    return {"ok": True, "profile": profile}


@router.get("/credit-risk/profile/project/{project_id}")
def read_project_credit_risk_profile(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    identity = assert_expected_active_identity(project_id, user=user)
    try:
        profile = get_project_profile_exact(
            project_id,
            str(identity["dataset_id"]),
            str(identity["dataset_version_id"]),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "profile": profile}


@router.post("/credit-risk/readiness")
def post_credit_risk_readiness(
    payload: CreditRiskProfile,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    _profile_binding(payload.model_dump(), user, access="view", require_analysis_scope=True)
    return {"ok": True, "readiness": compute_readiness(payload.model_dump())}


@router.post("/credit-risk/dataset-summary")
def post_credit_risk_dataset_summary(
    payload: CreditRiskDatasetSummaryRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    store, identity, scope = resolve_credit_risk_scope(
        payload,
        user,
        access="view",
    )
    dataset = identity.get("dataset") or {}
    version = identity.get("version") or {}
    target = scope.target
    event_value = "" if scope.event_value is None else str(scope.event_value)
    non_event_value = "" if scope.non_event_value is None else str(scope.non_event_value)
    requested_non_event = "" if payload.nonEventValue is None else str(payload.nonEventValue)
    if requested_non_event and requested_non_event != non_event_value:
        raise HTTPException(
            status_code=409,
            detail="The requested non-event value contradicts the exact governed target contract.",
        )
    series = scope.development_target
    total_rows = int(len(series))
    good_count = 0
    bad_count = 0
    missing_count = 0
    indeterminate_count = 0
    if target:
        normalized = series.astype(str).str.strip()
        missing_mask = series.isna() | normalized.eq("")
        event_mask = normalized.eq(event_value)
        if non_event_value:
            good_mask = normalized.eq(non_event_value)
            indeterminate_mask = ~(event_mask | good_mask | missing_mask)
        else:
            good_mask = ~(event_mask | missing_mask)
            indeterminate_mask = normalized.ne(event_value) & ~missing_mask
        bad_count = int(event_mask.sum())
        good_count = int(good_mask.sum())
        missing_count = int(missing_mask.sum())
        indeterminate_count = int(indeterminate_mask.sum()) if non_event_value else 0
    with store.state_lock:
        rechecked_identity = assert_expected_active_identity(
            payload.projectId,
            expected_dataset_id=identity["dataset_id"],
            expected_dataset_version_id=identity["dataset_version_id"],
            require_expected=True,
            user=user,
            store=store,
        )
        if str(rechecked_identity.get("dataset_content_hash") or "") != str(
            scope.metadata().get("source_checksum") or ""
        ):
            raise HTTPException(
                status_code=409,
                detail="The active dataset checksum changed while the Credit Risk summary was being prepared.",
            )
        structural = store.get_raw_active_df(include_target=False)
        structural = structural.copy() if structural is not None else None
    if structural is None or structural.empty:
        raise HTTPException(
            status_code=409,
            detail="The exact full structural predictor frame is unavailable.",
        )
    special_rows = []
    for column in scope.authorized_predictors:
        if column not in structural.columns:
            raise HTTPException(
                status_code=409,
                detail=f"Authorized predictor {column!r} is absent from the active structural frame.",
            )
        numeric = structural[column].astype(str).str.strip()
        counts = {value: int(numeric.eq(value).sum()) for value in ["-7", "-8", "-9"]}
        special_total = sum(counts.values())
        if special_total:
            special_rows.append(
                {
                    "variable": str(column),
                    "countMinus7": counts["-7"],
                    "countMinus8": counts["-8"],
                    "countMinus9": counts["-9"],
                    "specialValueCount": special_total,
                    "specialValueRate": special_total / max(1, len(structural)),
                    "recommendedTreatment": "Create special bins",
                }
            )
    row_count = int(version.get("rowCount") or len(structural))
    full_available = int(len(structural)) == row_count
    scope_fields = canonical_scope_fields(scope)
    summary = {
        "projectId": identity.get("project_id"),
        "datasetId": dataset.get("datasetId"),
        "datasetName": dataset.get("name"),
        "datasetVersionId": identity.get("dataset_version_id"),
        "targetColumn": target,
        "eventValue": event_value,
        "nonEventValue": non_event_value,
        "scope": "development_population",
        "rowCount": total_rows,
        "profiledRows": total_rows,
        "totalRows": total_rows,
        "structuralRowCount": int(len(structural)),
        "goodCount": good_count,
        "badCount": bad_count,
        "badRate": bad_count / max(1, good_count + bad_count),
        "indeterminateCount": indeterminate_count,
        "missingTargetCount": missing_count,
        "fullDatasetAvailable": full_available,
        "message": "Target composition uses the exact governed development population; special-value structure uses full authorized predictors only.",
        "specialValueProfile": special_rows,
        **scope_fields,
    }
    return {"ok": True, "summary": summary}


@router.post("/credit-risk/evidence")
def post_credit_risk_evidence(
    payload: CreditRiskEvidenceRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    profile_payload = payload.profile.model_dump()
    scope = _profile_binding(profile_payload, user, access="edit", require_analysis_scope=True)
    profile = save_profile(_governed_profile_payload(profile_payload, scope))
    evidence = create_credit_risk_evidence(profile, payload.technique, payload.label, payload.supportsSections)
    audit_event("credit_risk.evidence.saved", "evidence", evidence.get("evidenceId"), "success", metadata={"technique": payload.technique, "projectId": profile.get("projectId")})
    return {"ok": True, "profile": profile, "evidence": evidence}


@router.post("/credit-risk/export/excel")
def export_credit_risk_excel(
    payload: CreditRiskProfile,
    user: Dict[str, Any] = Depends(require_user),
) -> StreamingResponse:
    profile_payload = payload.model_dump()
    scope = _profile_binding(profile_payload, user, access="view", require_analysis_scope=True)
    profile = _governed_profile_payload(profile_payload, scope)
    content = export_profile_excel(profile)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="atlas-credit-risk-profile.xlsx"'},
    )


@router.post("/credit-risk/woe-iv/run")
def post_woe_iv_run(
    payload: WoeIvRunRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    _, _, scope = resolve_credit_risk_scope(payload, user, access="edit")
    analysis = run_woe_iv(payload.model_dump(), scope)
    audit_event(
        "credit_risk.woe_iv.run",
        "woe_iv_analysis",
        analysis.get("analysisId"),
        "success",
        metadata={"projectId": analysis.get("projectId"), "datasetId": analysis.get("datasetId")},
    )
    return {"ok": True, "analysis": analysis}


@router.get("/credit-risk/woe-iv/{analysis_id}")
def read_woe_iv_analysis(
    analysis_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    analysis = _require_analysis(analysis_id)
    _stored_artifact_scope(analysis, user, label="WOE / IV analysis")
    return {"ok": True, "analysis": analysis}


@router.get("/credit-risk/woe-iv/project/{project_id}")
def read_project_woe_iv_analysis(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    _, identity, scope = resolve_credit_risk_project_scope(project_id, user)
    fields = canonical_scope_fields(scope)
    analysis = get_project_analysis_exact(
        project_id,
        str(identity["dataset_id"]),
        str(identity["dataset_version_id"]),
        str(fields["partition_id"]),
        int(fields["partition_revision"]),
    )
    if analysis:
        require_artifact_scope(analysis, scope, artifact_label="WOE / IV analysis")
    return {"ok": True, "analysis": analysis}


@router.post("/credit-risk/woe-iv/save")
def post_woe_iv_save(
    payload: WoeIvSaveRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    analysis_id = str(payload.analysis.get("analysisId") or "")
    analysis = _require_analysis(analysis_id)
    _stored_artifact_scope(
        analysis,
        user,
        label="WOE / IV analysis",
        access="edit",
    )
    # The analytical payload is server-authored.  This compatibility action
    # persists only the already stored authoritative artifact and never trusts
    # client-supplied bins, metrics, target semantics, or scope fields.
    analysis = save_analysis(analysis)
    audit_event(
        "credit_risk.woe_iv.saved",
        "woe_iv_analysis",
        analysis.get("analysisId"),
        "success",
        metadata={"projectId": analysis.get("projectId"), "datasetId": analysis.get("datasetId")},
    )
    return {"ok": True, "analysis": analysis}


@router.post("/credit-risk/woe-iv/apply-manual-bins")
def post_woe_iv_manual_bins(
    payload: WoeIvManualBinsRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    stored = _require_analysis(payload.analysisId)
    scope = _stored_artifact_scope(
        stored,
        user,
        label="WOE / IV analysis",
        access="edit",
    )
    analysis = apply_manual_bins(payload.model_dump(), scope)
    audit_event(
        "credit_risk.woe_iv.manual_bins",
        "woe_iv_analysis",
        analysis.get("analysisId"),
        "success",
        metadata={"projectId": analysis.get("projectId"), "variable": payload.variable},
    )
    return {"ok": True, "analysis": analysis}


@router.post("/credit-risk/woe-iv/save-evidence")
def post_woe_iv_evidence(
    payload: WoeIvEvidenceRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    stored = _require_analysis(payload.analysisId)
    _stored_artifact_scope(stored, user, label="WOE / IV analysis", access="edit")
    evidence = create_woe_iv_evidence(payload.analysisId, payload.technique, payload.label)
    audit_event(
        "credit_risk.woe_iv.evidence.saved",
        "evidence",
        evidence.get("evidenceId"),
        "success",
        metadata={"analysisId": payload.analysisId, "technique": payload.technique},
    )
    return {"ok": True, "evidence": evidence}


@router.post("/credit-risk/woe-iv/export/excel")
def post_woe_iv_export(
    payload: WoeIvAnalysisIdRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> StreamingResponse:
    stored = _require_analysis(payload.analysisId)
    _stored_artifact_scope(stored, user, label="WOE / IV analysis")
    content = export_woe_iv_excel(payload.analysisId)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="atlas-woe-iv-analysis.xlsx"'},
    )


@router.post("/credit-risk/woe-iv/generate-code")
def post_woe_iv_generate_code(
    payload: WoeIvRunRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    _, _, scope = resolve_credit_risk_scope(payload, user, access="view")
    predictors = authorized_predictors_for_request(
        payload.model_dump(), scope, limit=10
    )
    settings = {
        **payload.model_dump(),
        **canonical_scope_fields(scope),
        "projectId": scope.identity["project_id"],
        "datasetId": scope.identity["dataset_id"],
        "datasetVersionId": scope.identity["dataset_version_id"],
        "targetColumn": scope.target,
        "eventValue": scope.event_value,
        "predictorColumns": predictors,
    }
    return {"ok": True, "generatedCode": generate_code(settings)}


@router.post("/credit-risk/scorecard/train")
def post_scorecard_train(
    payload: ScorecardTrainRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    _, _, scope = resolve_credit_risk_scope(payload, user, access="edit")
    model = train_scorecard(payload.model_dump(), scope)
    audit_event(
        "credit_risk.scorecard.train",
        "scorecard_model",
        model.get("modelId"),
        "success",
        metadata={"projectId": model.get("projectId"), "datasetId": model.get("datasetId")},
    )
    return {"ok": True, "model": model}


@router.get("/credit-risk/scorecard/{model_id}")
def read_scorecard_model(
    model_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    model = _require_scorecard(model_id)
    _stored_artifact_scope(model, user, label="scorecard model")
    return {"ok": True, "model": model}


@router.get("/credit-risk/scorecard/project/{project_id}")
def read_project_scorecard_model(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    _, identity, scope = resolve_credit_risk_project_scope(project_id, user)
    fields = canonical_scope_fields(scope)
    model = get_project_scorecard_exact(
        project_id,
        str(identity["dataset_id"]),
        str(identity["dataset_version_id"]),
        str(fields["partition_id"]),
        int(fields["partition_revision"]),
    )
    if model:
        require_artifact_scope(model, scope, artifact_label="scorecard model")
    return {"ok": True, "model": model}


@router.post("/credit-risk/scorecard/export/excel")
def post_scorecard_export(
    payload: ScorecardModelIdRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> StreamingResponse:
    model = _require_scorecard(payload.modelId)
    _stored_artifact_scope(model, user, label="scorecard model")
    content = export_scorecard_excel(payload.modelId)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="atlas-credit-risk-scorecard.xlsx"'},
    )


@router.post("/credit-risk/scorecard/save-evidence")
def post_scorecard_evidence(
    payload: ScorecardEvidenceRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    model = _require_scorecard(payload.modelId)
    _stored_artifact_scope(model, user, label="scorecard model", access="edit")
    evidence = create_scorecard_evidence(payload.modelId, payload.technique, payload.label)
    audit_event(
        "credit_risk.scorecard.evidence.saved",
        "evidence",
        evidence.get("evidenceId"),
        "success",
        metadata={"modelId": payload.modelId, "technique": payload.technique},
    )
    return {"ok": True, "evidence": evidence}


@router.post("/credit-risk/scorecard/generate-code")
def post_scorecard_generate_code(
    payload: ScorecardTrainRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    _, _, scope = resolve_credit_risk_scope(payload, user, access="view")
    requested = [str(value) for value in payload.selectedVariables]
    unauthorized = [value for value in requested if value not in scope.authorized_predictors]
    if unauthorized:
        raise HTTPException(
            status_code=409,
            detail="Generated scorecard code requested unauthorized predictors.",
        )
    settings = {
        **payload.model_dump(),
        **canonical_scope_fields(scope),
        "targetColumn": scope.target,
        "eventValue": scope.event_value,
        "selectedVariables": requested,
    }
    return {"ok": True, "generatedCode": generate_scorecard_code(settings)}


@router.post("/credit-risk/scorecard/register-model")
def post_scorecard_register(
    payload: ScorecardRegisterRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    stored = _require_scorecard(payload.modelId)
    _stored_artifact_scope(stored, user, label="scorecard model", access="edit")
    model = register_scorecard_model(payload.modelId, payload.champion)
    audit_event("credit_risk.scorecard.registered", "scorecard_model", model.get("modelId"), "success", metadata={"champion": model.get("champion")})
    return {"ok": True, "model": model}


@router.post("/credit-risk/ml/train")
def post_ml_train(
    payload: CreditRiskMlTrainRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    _, _, scope = resolve_credit_risk_scope(payload, user, access="edit")
    model = train_ml_model(payload.model_dump(), scope)
    audit_event(
        "credit_risk.ml.train",
        "credit_risk_ml_model",
        model.get("modelId"),
        "success",
        metadata={"projectId": model.get("projectId"), "datasetId": model.get("datasetId"), "modelType": model.get("modelType")},
    )
    return {"ok": True, "model": model}


@router.get("/credit-risk/ml/{model_id}")
def read_ml_model(
    model_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    model = _require_ml_model(model_id)
    _stored_artifact_scope(model, user, label="AI/ML underwriting model")
    return {"ok": True, "model": model}


@router.get("/credit-risk/ml/project/{project_id}")
def read_project_ml_model(
    project_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    _, identity, scope = resolve_credit_risk_project_scope(project_id, user)
    fields = canonical_scope_fields(scope)
    model = get_project_ml_model_exact(
        project_id,
        str(identity["dataset_id"]),
        str(identity["dataset_version_id"]),
        str(fields["partition_id"]),
        int(fields["partition_revision"]),
    )
    if model:
        require_artifact_scope(model, scope, artifact_label="AI/ML underwriting model")
    return {"ok": True, "model": model}


@router.post("/credit-risk/ml/export/excel")
def post_ml_export_excel(
    payload: ScorecardModelIdRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> StreamingResponse:
    model = _require_ml_model(payload.modelId)
    _stored_artifact_scope(model, user, label="AI/ML underwriting model")
    import pandas as pd

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame([model.get("metrics") or {}]).to_excel(writer, sheet_name="Metrics", index=False)
        pd.DataFrame(model.get("featureImportance") or []).to_excel(writer, sheet_name="Feature Importance", index=False)
        pd.DataFrame(model.get("decileLift") or []).to_excel(writer, sheet_name="Decile Lift", index=False)
        pd.DataFrame(model.get("calibrationTable") or []).to_excel(writer, sheet_name="Calibration", index=False)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="atlas-credit-risk-ml-model.xlsx"'},
    )


@router.post("/credit-risk/ml/save-evidence")
def post_ml_evidence(
    payload: CreditRiskMlEvidenceRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    model = _require_ml_model(payload.modelId)
    _stored_artifact_scope(model, user, label="AI/ML underwriting model", access="edit")
    evidence = create_ml_evidence(payload.modelId, payload.technique, payload.label)
    audit_event("credit_risk.ml.evidence.saved", "evidence", evidence.get("evidenceId"), "success", metadata={"modelId": payload.modelId, "technique": payload.technique})
    return {"ok": True, "evidence": evidence}


@router.post("/credit-risk/champion-comparison/run")
def post_champion_comparison(
    payload: ChampionComparisonRunRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    request = payload.model_dump()
    profile = request.get("profile") or {}
    _, _, scope = resolve_credit_risk_scope(profile, user, access="edit")
    scorecard_client = request.get("scorecardModel") or {}
    ml_client = request.get("mlModel") or {}
    scorecard = None
    ml_model = None
    if scorecard_client:
        model_id = str(scorecard_client.get("modelId") or "")
        if not model_id:
            raise HTTPException(status_code=422, detail="An exact scorecard modelId is required for comparison.")
        scorecard = _require_scorecard(model_id)
        require_artifact_scope(scorecard, scope, artifact_label="scorecard model")
    if ml_client:
        model_id = str(ml_client.get("modelId") or "")
        if not model_id:
            raise HTTPException(status_code=422, detail="An exact AI/ML modelId is required for comparison.")
        ml_model = _require_ml_model(model_id)
        require_artifact_scope(ml_model, scope, artifact_label="AI/ML underwriting model")
    comparison = run_champion_comparison(
        {
            "profile": profile,
            "scorecardModel": scorecard,
            "mlModel": ml_model,
            "scopeMetadata": canonical_scope_fields(scope),
        }
    )
    audit_event("credit_risk.champion_comparison.run", "credit_risk_comparison", comparison.get("projectId"), "success", metadata={"projectId": comparison.get("projectId")})
    return {"ok": True, "comparison": comparison}


@router.post("/credit-risk/champion-comparison/save-decision")
def post_champion_decision(
    payload: ChampionDecisionRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    profile = payload.profile.model_dump()
    decision = payload.decision.model_dump()
    _, _, scope = resolve_credit_risk_scope(profile, user, access="edit")
    selected_model_id = str(decision.get("selectedModelId") or "")
    if not selected_model_id:
        raise HTTPException(status_code=422, detail="An exact selectedModelId is required.")
    selected_model = get_scorecard_model(selected_model_id) or get_ml_model(selected_model_id)
    if not selected_model:
        raise HTTPException(status_code=404, detail="Selected Credit Risk model not found.")
    require_artifact_scope(selected_model, scope, artifact_label="selected Credit Risk model")
    profile = _governed_profile_payload(profile, scope)
    profile["championDecision"] = decision
    profile["championModelId"] = decision.get("selectedModelId")
    profile["championModelType"] = decision.get("selectedModelType")
    profile["championDecisionStatus"] = "Ready"
    saved = save_profile(profile)
    audit_event("credit_risk.champion_decision.saved", "credit_risk_profile", saved.get("profileId"), "success", metadata={"projectId": saved.get("projectId"), "championModelType": saved.get("championModelType")})
    return {"ok": True, "profile": saved, "decision": saved.get("championDecision")}


@router.post("/credit-risk/champion-comparison/save-evidence")
def post_champion_evidence(
    payload: ChampionEvidenceRequest,
    user: Dict[str, Any] = Depends(require_user),
) -> dict:
    raw_profile = payload.profile.model_dump()
    _, _, scope = resolve_credit_risk_scope(raw_profile, user, access="edit")
    champion_id = str(raw_profile.get("championModelId") or "")
    if champion_id:
        model = get_scorecard_model(champion_id) or get_ml_model(champion_id)
        if not model:
            raise HTTPException(status_code=404, detail="Champion Credit Risk model not found.")
        require_artifact_scope(model, scope, artifact_label="champion Credit Risk model")
    profile = save_profile(_governed_profile_payload(raw_profile, scope))
    evidence = create_credit_risk_evidence(profile, "champion_challenger", payload.label, ["Champion Model", "Candidate Models", "Monitoring Recommendations"])
    audit_event("credit_risk.champion_comparison.evidence.saved", "evidence", evidence.get("evidenceId"), "success", metadata={"projectId": profile.get("projectId")})
    return {"ok": True, "profile": profile, "evidence": evidence}
