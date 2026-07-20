from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Depends
from ..security.security_store import require_user
from .service import AnalyticsEngineService

router=APIRouter(prefix="/api/analytics-engine",dependencies=[Depends(require_user)])
def service() -> AnalyticsEngineService: return AnalyticsEngineService()

@router.get("/capabilities")
def capabilities(_:Dict[str,Any]=Depends(require_user)): return {"ok":True,**service().capabilities()}
@router.get("/analysis-types")
def analysis_types(_:Dict[str,Any]=Depends(require_user)): return {"ok":True,"items":service().capabilities()["analysis_types"]}
@router.get("/runs")
def runs(project_id:str|None=None,analysis_type:str|None=None,status:str|None=None,_:Dict[str,Any]=Depends(require_user)): return {"ok":True,"items":service().persistence.analytics.list_runs(project_id=project_id,analysis_type=analysis_type,status=status)}
@router.get("/runs/{run_id}")
def get_run(run_id:str,_:Dict[str,Any]=Depends(require_user)): return {"ok":True,**service().run_detail(run_id)}
@router.get("/projects/{project_id}/runs")
def project_runs(project_id:str,_:Dict[str,Any]=Depends(require_user)): return {"ok":True,"items":service().persistence.analytics.list_runs(project_id=project_id)}
@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id:str,user:Dict[str,Any]=Depends(require_user)): return {"ok":True,**service().cancel(run_id,user)}
@router.post("/runs/{run_id}/capture-evidence")
def capture_run(run_id:str,user:Dict[str,Any]=Depends(require_user)): return {"ok":True,**service().capture_evidence(run_id,user)}
@router.post("/runs/{run_id}/add-to-documentation")
def add_documentation(run_id:str,_:Dict[str,Any]=Depends(require_user)):
    detail=service().run_detail(run_id);return {"ok":True,"documentation_payload":(detail.get("result") or {}).get("documentation_payload",{})}

def _endpoint(analysis_type:str):
    def handler(payload:Dict[str,Any],user:Dict[str,Any]=Depends(require_user)): return {"ok":True,**service().run(analysis_type,payload,user)}
    return handler

for _path,_type in [("/descriptive/profile","descriptive_profile"),("/data-quality/profile","data_quality_profile"),("/classification/diagnostics","classification_diagnostics"),("/regression/diagnostics","regression_diagnostics"),("/time-series/profile","time_series_profile"),("/forecasting/diagnostics","forecast_diagnostics"),("/forecasting/backtest","forecast_backtest"),("/experimentation/diagnostics","experiment_diagnostics"),("/experimentation/anova","anova"),("/experimentation/power","power_analysis"),("/optimization/diagnostics","optimization_diagnostics"),("/llm/evaluation","llm_evaluation"),("/segments/diagnostics","segment_diagnostics"),("/fairness/diagnostics","fairness_diagnostics")]: router.add_api_route(_path,_endpoint(_type),methods=["POST"])
