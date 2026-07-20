from __future__ import annotations

import uuid
from typing import Any, Callable, Dict

from fastapi import HTTPException

from ..persistence.db import now_iso
from ..persistence.service import get_persistence_service
from .dataset_adapter import load_dataset
from .errors import AnalyticalEngineError
from .evidence_adapter import capture
from .monitoring_adapter import monitoring_payload
from .validation_adapter import validation_payload
from .documentation_adapter import documentation_payload
from .code_generation import reproducible_code
from .modules.classification import compute_classification_diagnostics
from .modules.data_quality import compute_data_quality_scorecard
from .modules.descriptive import compute_dataset_profile
from .modules.experimentation import compute_anova, compute_experiment_diagnostics, compute_power_analysis
from .modules.fairness import compute_fairness_diagnostics, compute_segment_diagnostics
from .modules.forecasting import compute_backtest_metrics, compute_forecast_diagnostics
from .modules.llm_evaluation import compute_llm_evaluation
from .modules.optimization import compute_optimization_diagnostics
from .modules.regression import compute_regression_diagnostics
from .modules.time_series import compute_time_series_profile


class AnalyticsEngineService:
    def __init__(self, persistence: Any | None = None) -> None:
        self.persistence = persistence or get_persistence_service()
        self.registry: Dict[str, Callable[..., Dict[str, Any]]] = {"descriptive_profile": compute_dataset_profile, "data_quality_profile": compute_data_quality_scorecard, "classification_diagnostics": compute_classification_diagnostics, "regression_diagnostics": compute_regression_diagnostics, "time_series_profile": compute_time_series_profile, "forecast_diagnostics": compute_forecast_diagnostics, "forecast_backtest": compute_backtest_metrics, "experiment_diagnostics": compute_experiment_diagnostics, "anova": compute_anova, "power_analysis": compute_power_analysis, "optimization_diagnostics": compute_optimization_diagnostics, "llm_evaluation": compute_llm_evaluation, "segment_diagnostics": compute_segment_diagnostics, "fairness_diagnostics": compute_fairness_diagnostics}

    def capabilities(self) -> Dict[str, Any]:
        return {"analysis_types": sorted(self.registry), "chart_ready_contract": True, "persistence": "SQLite", "dataset_requirement": "Registered dataset references resolve governed full artifacts; active session datasets are explicitly labeled."}

    def run(self, analysis_type: str, payload: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
        if analysis_type not in self.registry: raise HTTPException(status_code=404, detail=f"Analysis type '{analysis_type}' is not supported.")
        run_id=f"arun_{uuid.uuid4().hex[:16]}"; context={"project_id":payload.get("project_id") or payload.get("projectId"),"workflow_type":payload.get("workflow_type") or payload.get("workflowType"),"requested_by_user_id":user.get("userId"),"source_run_record_id":payload.get("source_run_record_id") or payload.get("runRecordId")}
        parameters=payload.get("parameters") or {key:value for key,value in payload.items() if key not in {"project_id","projectId","workflow_type","workflowType","dataset_id","datasetId","dataset_version_id","datasetVersionId","versionId","source_run_record_id","runRecordId","parameters"}}
        run={"analytical_run_id":run_id,"project_id":context["project_id"],"workflow_type":context["workflow_type"],"analysis_type":analysis_type,"analysis_version":"1.0.0","dataset_id":payload.get("dataset_id") or payload.get("datasetId"),"dataset_version_id":payload.get("dataset_version_id") or payload.get("datasetVersionId") or payload.get("versionId"),"source_run_record_id":context["source_run_record_id"],"status":"running","requested_by_user_id":user.get("userId"),"parameter_json":parameters,"input_reference_json":{},"created_at":now_iso()}
        self.persistence.analytics.upsert_run(run)
        try:
            if analysis_type in {"power_analysis"}: output=self.registry[analysis_type](context, parameters)
            elif analysis_type in {"optimization_diagnostics","llm_evaluation"}: output=self.registry[analysis_type](payload.get("input") or payload, context, parameters)
            else:
                frame, reference=load_dataset(payload); context.update(reference); run["dataset_id"]=reference.get("dataset_id");run["dataset_version_id"]=reference.get("dataset_version_id"); run["input_reference_json"]={"profile_scope":reference.get("profile_scope"),"dataset_name":reference.get("dataset_name"),"row_count":len(frame)}; output=self.registry[analysis_type](frame,context,parameters)
            output["evidence_payload"]={"analysis_type":analysis_type,"statistics":output.get("statistics"),"warnings":output.get("warnings"),"tables":output.get("tables"),"charts":output.get("charts"),"lineage":output.get("lineage")}; output["documentation_payload"]=documentation_payload(output); output["validation_payload"]=validation_payload(output); output["monitoring_payload"]=monitoring_payload(output)
            output.setdefault("metadata", {})["reproducible_code"] = reproducible_code(analysis_type, context, parameters)
            run.update({"status":output.get("status") or "completed","completed_at":now_iso(),"result_summary_json":output.get("statistics"),"warning_count":len(output.get("warnings") or []),"reproducibility_json":output.get("metadata",{}).get("reproducibility",{}),"metadata_json":{"analysis_id":output.get("analysis_id")}}); self.persistence.analytics.upsert_run(run); self.persistence.analytics.replace_outputs(run_id,output)
            if context.get("project_id"): self.persistence.audit.create({"audit_id":f"audit_{uuid.uuid4().hex[:16]}","project_id":context["project_id"],"user_id":user.get("userId"),"action_type":"analytical_run_completed","entity_type":"analytical_run","entity_id":run_id,"title":"Analytical run completed","summary":analysis_type,"created_at":now_iso(),"metadata_json":{"status":run["status"]}})
            return {"run":self.persistence.analytics.get_run(run_id),"result":output}
        except AnalyticalEngineError as error:
            run.update({"status":"insufficient_data" if error.__class__.__name__=="InsufficientDataError" else "failed","completed_at":now_iso(),"error_message":str(error)});self.persistence.analytics.upsert_run(run);raise HTTPException(status_code=error.status_code,detail=str(error))
        except Exception as error:
            run.update({"status":"failed","completed_at":now_iso(),"error_message":str(error)});self.persistence.analytics.upsert_run(run);raise

    def run_detail(self, run_id: str) -> Dict[str, Any]:
        run=self.persistence.analytics.get_run(run_id)
        if not run: raise HTTPException(status_code=404,detail="Analytical run was not found.")
        return {"run":run,"result":self.persistence.analytics.full_result(run_id)}

    def cancel(self, run_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
        run = self.persistence.analytics.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Analytical run was not found.")
        if run.get("status") not in {"queued", "running"}:
            return {"run": run, "message": "Only queued or running analytical runs can be cancelled."}
        run.update({"status": "cancelled", "completed_at": now_iso(), "error_message": "Cancelled by user."})
        self.persistence.analytics.upsert_run(run)
        if run.get("project_id"):
            self.persistence.audit.create({"audit_id":f"audit_{uuid.uuid4().hex[:16]}","project_id":run["project_id"],"user_id":user.get("userId"),"action_type":"analytical_run_cancelled","entity_type":"analytical_run","entity_id":run_id,"title":"Analytical run cancelled","summary":run["analysis_type"],"created_at":now_iso(),"metadata_json":{}})
        return {"run": self.persistence.analytics.get_run(run_id)}

    def capture_evidence(self, run_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
        detail=self.run_detail(run_id); return {"evidence":capture(self.persistence,detail["run"],detail["result"] or {},user)}
