from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..security.security_store import audit_event, require_user
from .credit_risk_store import (
    compute_readiness,
    create_credit_risk_evidence,
    export_profile_excel,
    get_profile,
    get_project_profile,
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
from .woe_iv_engine import load_dataset_frame
from .ml_engine import (
    create_ml_evidence,
    get_ml_model,
    get_project_ml_model,
    run_champion_comparison,
    save_ml_model,
    train_ml_model,
)
from .scorecard_engine import (
    create_scorecard_evidence,
    export_scorecard_excel,
    generate_scorecard_code,
    get_project_scorecard,
    get_scorecard_model,
    register_scorecard_model,
    train_scorecard,
)
from .woe_iv_engine import (
    apply_manual_bins,
    create_woe_iv_evidence,
    export_woe_iv_excel,
    generate_code,
    get_analysis,
    get_project_analysis,
    run_woe_iv,
    save_analysis,
)

import io


router = APIRouter(dependencies=[Depends(require_user)])


@router.get("/credit-risk/profile")
def read_credit_risk_profile(profileId: Optional[str] = None) -> dict:
    if profileId:
        return {"ok": True, "profile": get_profile(profileId)}
    profiles = list_profiles()
    first = get_profile(str(profiles[0].get("profileId"))) if profiles else None
    return {"ok": True, "profile": first}


@router.post("/credit-risk/profile")
def create_credit_risk_profile(payload: CreditRiskProfile) -> dict:
    profile = save_profile(payload.model_dump())
    audit_event("credit_risk.profile.saved", "credit_risk_profile", profile.get("profileId"), "success", metadata={"projectId": profile.get("projectId")})
    return {"ok": True, "profile": profile}


@router.put("/credit-risk/profile/{profile_id}")
def update_credit_risk_profile(profile_id: str, payload: CreditRiskProfile) -> dict:
    if payload.profileId and payload.profileId != profile_id:
        raise HTTPException(status_code=400, detail="Profile ID mismatch.")
    profile = save_profile({**payload.model_dump(), "profileId": profile_id})
    audit_event("credit_risk.profile.saved", "credit_risk_profile", profile.get("profileId"), "success", metadata={"projectId": profile.get("projectId")})
    return {"ok": True, "profile": profile}


@router.get("/credit-risk/profile/project/{project_id}")
def read_project_credit_risk_profile(project_id: str) -> dict:
    return {"ok": True, "profile": get_project_profile(project_id)}


@router.post("/credit-risk/readiness")
def post_credit_risk_readiness(payload: CreditRiskProfile) -> dict:
    return {"ok": True, "readiness": compute_readiness(payload.model_dump())}


@router.post("/credit-risk/dataset-summary")
def post_credit_risk_dataset_summary(payload: CreditRiskDatasetSummaryRequest) -> dict:
    dataset, resolved_version, df = load_dataset_frame(payload.datasetId, payload.datasetVersionId)
    versions = dataset.get("versions") or []
    version = next((item for item in versions if item.get("versionId") == resolved_version), versions[-1] if versions else {})
    row_count = int(version.get("rowCount") or df.shape[0])
    target = payload.targetColumn or ""
    event_value = "" if payload.eventValue is None else str(payload.eventValue)
    non_event_value = "" if payload.nonEventValue is None else str(payload.nonEventValue)
    total_rows = int(df.shape[0])
    good_count = 0
    bad_count = 0
    missing_count = 0
    indeterminate_count = 0
    if target and target in df.columns:
        series = df[target]
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
    special_rows = []
    for column in df.columns:
        numeric = df[column].astype(str).str.strip()
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
                    "specialValueRate": special_total / max(1, total_rows),
                    "recommendedTreatment": "Create special bins",
                }
            )
    full_available = total_rows == row_count
    summary = {
        "datasetId": dataset.get("datasetId"),
        "datasetName": dataset.get("name"),
        "datasetVersionId": resolved_version,
        "targetColumn": target,
        "eventValue": event_value,
        "nonEventValue": non_event_value,
        "scope": "full" if full_available else "preview",
        "rowCount": row_count,
        "profiledRows": total_rows,
        "totalRows": total_rows,
        "goodCount": good_count,
        "badCount": bad_count,
        "badRate": bad_count / max(1, good_count + bad_count),
        "indeterminateCount": indeterminate_count,
        "missingTargetCount": missing_count,
        "fullDatasetAvailable": full_available,
        "message": "" if full_available else "Full dataset artifact unavailable. Showing preview sample summary.",
        "specialValueProfile": special_rows,
    }
    return {"ok": True, "summary": summary}


@router.post("/credit-risk/evidence")
def post_credit_risk_evidence(payload: CreditRiskEvidenceRequest) -> dict:
    profile = save_profile(payload.profile.model_dump())
    evidence = create_credit_risk_evidence(profile, payload.technique, payload.label, payload.supportsSections)
    audit_event("credit_risk.evidence.saved", "evidence", evidence.get("evidenceId"), "success", metadata={"technique": payload.technique, "projectId": profile.get("projectId")})
    return {"ok": True, "profile": profile, "evidence": evidence}


@router.post("/credit-risk/export/excel")
def export_credit_risk_excel(payload: CreditRiskProfile) -> StreamingResponse:
    profile = save_profile(payload.model_dump())
    content = export_profile_excel(profile)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="atlas-credit-risk-profile.xlsx"'},
    )


@router.post("/credit-risk/woe-iv/run")
def post_woe_iv_run(payload: WoeIvRunRequest) -> dict:
    analysis = run_woe_iv(payload.model_dump())
    audit_event(
        "credit_risk.woe_iv.run",
        "woe_iv_analysis",
        analysis.get("analysisId"),
        "success",
        metadata={"projectId": analysis.get("projectId"), "datasetId": analysis.get("datasetId")},
    )
    return {"ok": True, "analysis": analysis}


@router.get("/credit-risk/woe-iv/{analysis_id}")
def read_woe_iv_analysis(analysis_id: str) -> dict:
    analysis = get_analysis(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="WOE / IV analysis not found.")
    return {"ok": True, "analysis": analysis}


@router.get("/credit-risk/woe-iv/project/{project_id}")
def read_project_woe_iv_analysis(project_id: str) -> dict:
    return {"ok": True, "analysis": get_project_analysis(project_id)}


@router.post("/credit-risk/woe-iv/save")
def post_woe_iv_save(payload: WoeIvSaveRequest) -> dict:
    analysis = save_analysis(payload.analysis)
    audit_event(
        "credit_risk.woe_iv.saved",
        "woe_iv_analysis",
        analysis.get("analysisId"),
        "success",
        metadata={"projectId": analysis.get("projectId"), "datasetId": analysis.get("datasetId")},
    )
    return {"ok": True, "analysis": analysis}


@router.post("/credit-risk/woe-iv/apply-manual-bins")
def post_woe_iv_manual_bins(payload: WoeIvManualBinsRequest) -> dict:
    analysis = apply_manual_bins(payload.model_dump())
    audit_event(
        "credit_risk.woe_iv.manual_bins",
        "woe_iv_analysis",
        analysis.get("analysisId"),
        "success",
        metadata={"projectId": analysis.get("projectId"), "variable": payload.variable},
    )
    return {"ok": True, "analysis": analysis}


@router.post("/credit-risk/woe-iv/save-evidence")
def post_woe_iv_evidence(payload: WoeIvEvidenceRequest) -> dict:
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
def post_woe_iv_export(payload: WoeIvAnalysisIdRequest) -> StreamingResponse:
    content = export_woe_iv_excel(payload.analysisId)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="atlas-woe-iv-analysis.xlsx"'},
    )


@router.post("/credit-risk/woe-iv/generate-code")
def post_woe_iv_generate_code(payload: WoeIvRunRequest) -> dict:
    return {"ok": True, "generatedCode": generate_code(payload.model_dump())}


@router.post("/credit-risk/scorecard/train")
def post_scorecard_train(payload: ScorecardTrainRequest) -> dict:
    model = train_scorecard(payload.model_dump())
    audit_event(
        "credit_risk.scorecard.train",
        "scorecard_model",
        model.get("modelId"),
        "success",
        metadata={"projectId": model.get("projectId"), "datasetId": model.get("datasetId")},
    )
    return {"ok": True, "model": model}


@router.get("/credit-risk/scorecard/{model_id}")
def read_scorecard_model(model_id: str) -> dict:
    model = get_scorecard_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Scorecard model not found.")
    return {"ok": True, "model": model}


@router.get("/credit-risk/scorecard/project/{project_id}")
def read_project_scorecard_model(project_id: str) -> dict:
    return {"ok": True, "model": get_project_scorecard(project_id)}


@router.post("/credit-risk/scorecard/export/excel")
def post_scorecard_export(payload: ScorecardModelIdRequest) -> StreamingResponse:
    content = export_scorecard_excel(payload.modelId)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="atlas-credit-risk-scorecard.xlsx"'},
    )


@router.post("/credit-risk/scorecard/save-evidence")
def post_scorecard_evidence(payload: ScorecardEvidenceRequest) -> dict:
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
def post_scorecard_generate_code(payload: ScorecardTrainRequest) -> dict:
    return {"ok": True, "generatedCode": generate_scorecard_code(payload.model_dump())}


@router.post("/credit-risk/scorecard/register-model")
def post_scorecard_register(payload: ScorecardRegisterRequest) -> dict:
    model = register_scorecard_model(payload.modelId, payload.champion)
    audit_event("credit_risk.scorecard.registered", "scorecard_model", model.get("modelId"), "success", metadata={"champion": model.get("champion")})
    return {"ok": True, "model": model}


@router.post("/credit-risk/ml/train")
def post_ml_train(payload: CreditRiskMlTrainRequest) -> dict:
    model = train_ml_model(payload.model_dump())
    audit_event(
        "credit_risk.ml.train",
        "credit_risk_ml_model",
        model.get("modelId"),
        "success",
        metadata={"projectId": model.get("projectId"), "datasetId": model.get("datasetId"), "modelType": model.get("modelType")},
    )
    return {"ok": True, "model": model}


@router.get("/credit-risk/ml/{model_id}")
def read_ml_model(model_id: str) -> dict:
    model = get_ml_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="AI/ML underwriting model not found.")
    return {"ok": True, "model": model}


@router.get("/credit-risk/ml/project/{project_id}")
def read_project_ml_model(project_id: str) -> dict:
    return {"ok": True, "model": get_project_ml_model(project_id)}


@router.post("/credit-risk/ml/export/excel")
def post_ml_export_excel(payload: ScorecardModelIdRequest) -> StreamingResponse:
    model = get_ml_model(payload.modelId)
    if not model:
        raise HTTPException(status_code=404, detail="AI/ML underwriting model not found.")
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
def post_ml_evidence(payload: CreditRiskMlEvidenceRequest) -> dict:
    evidence = create_ml_evidence(payload.modelId, payload.technique, payload.label)
    audit_event("credit_risk.ml.evidence.saved", "evidence", evidence.get("evidenceId"), "success", metadata={"modelId": payload.modelId, "technique": payload.technique})
    return {"ok": True, "evidence": evidence}


@router.post("/credit-risk/champion-comparison/run")
def post_champion_comparison(payload: ChampionComparisonRunRequest) -> dict:
    comparison = run_champion_comparison(payload.model_dump())
    audit_event("credit_risk.champion_comparison.run", "credit_risk_comparison", comparison.get("projectId"), "success", metadata={"projectId": comparison.get("projectId")})
    return {"ok": True, "comparison": comparison}


@router.post("/credit-risk/champion-comparison/save-decision")
def post_champion_decision(payload: ChampionDecisionRequest) -> dict:
    profile = payload.profile.model_dump()
    decision = payload.decision.model_dump()
    profile["championDecision"] = decision
    profile["championModelId"] = decision.get("selectedModelId")
    profile["championModelType"] = decision.get("selectedModelType")
    profile["championDecisionStatus"] = "Ready"
    saved = save_profile(profile)
    audit_event("credit_risk.champion_decision.saved", "credit_risk_profile", saved.get("profileId"), "success", metadata={"projectId": saved.get("projectId"), "championModelType": saved.get("championModelType")})
    return {"ok": True, "profile": saved, "decision": saved.get("championDecision")}


@router.post("/credit-risk/champion-comparison/save-evidence")
def post_champion_evidence(payload: ChampionEvidenceRequest) -> dict:
    profile = save_profile(payload.profile.model_dump())
    evidence = create_credit_risk_evidence(profile, "champion_challenger", payload.label, ["Champion Model", "Candidate Models", "Monitoring Recommendations"])
    audit_event("credit_risk.champion_comparison.evidence.saved", "evidence", evidence.get("evidenceId"), "success", metadata={"projectId": profile.get("projectId")})
    return {"ok": True, "profile": profile, "evidence": evidence}
