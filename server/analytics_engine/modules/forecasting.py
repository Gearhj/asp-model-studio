from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from ..errors import InsufficientDataError
from ..result_builder import chart, result, table


def compute_forecast_diagnostics(frame: pd.DataFrame, context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    actual, forecast = parameters.get("actual_column") or parameters.get("target_column"), parameters.get("forecast_column") or parameters.get("prediction_column")
    timestamp = parameters.get("timestamp_column")
    columns=[actual,forecast]+([timestamp] if timestamp else []); work=frame[[c for c in columns if c in frame.columns]].copy(); work["actual"]=pd.to_numeric(work[actual],errors="coerce");work["forecast"]=pd.to_numeric(work[forecast],errors="coerce");work=work.dropna(subset=["actual","forecast"])
    if len(work)<3: raise InsufficientDataError("Forecast diagnostics require at least three paired actual and forecast observations.")
    error=work.actual-work.forecast; nonzero=work.actual!=0; denominator=work.actual.abs().sum()
    metrics={"observation_count":int(len(work)),"mae":float(error.abs().mean()),"rmse":float(np.sqrt((error**2).mean())),"mape":float((error[nonzero].abs()/work.actual[nonzero].abs()).mean()*100) if nonzero.any() else None,"smape":float((2*error.abs()/(work.actual.abs()+work.forecast.abs()).replace(0,np.nan)).mean()*100),"wape":float(error.abs().sum()/denominator*100) if denominator else None,"bias":float(error.mean()),"directional_accuracy":float(((work.actual.diff()*work.forecast.diff())>0).mean()*100)}
    if parameters.get("lower_column") in frame.columns and parameters.get("upper_column") in frame.columns:
        lower=pd.to_numeric(frame.loc[work.index,parameters["lower_column"]],errors="coerce"); upper=pd.to_numeric(frame.loc[work.index,parameters["upper_column"]],errors="coerce"); valid=lower.notna()&upper.notna(); metrics["interval_coverage"]=float(((work.actual[valid]>=lower[valid])&(work.actual[valid]<=upper[valid])).mean()*100) if valid.any() else None; metrics["interval_width"]=float((upper[valid]-lower[valid]).mean()) if valid.any() else None
    display=work.copy(); display["error"]=error
    if timestamp and timestamp in display: display=display.rename(columns={timestamp:"timestamp"})
    charts=[chart("actual_forecast","forecast_interval","Actual versus forecast",display.to_dict("records"),x_field="timestamp" if timestamp else "forecast",x_label="Period" if timestamp else "Forecast",y_fields=[{"field":"actual","label":"Actual"},{"field":"forecast","label":"Forecast"}])]
    warnings = ["Forecast bias is material relative to average actuals."] if abs(metrics["bias"]) > .1 * max(abs(work.actual.mean()), 1e-9) else []
    return result("forecast_diagnostics",context,parameters,statistics=metrics,tables=[table("forecast_errors","Forecast error distribution",display.to_dict("records"))],charts=charts,warnings=warnings)


def compute_backtest_metrics(frame: pd.DataFrame, context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    return compute_forecast_diagnostics(frame,context,parameters) | {"analysis_type":"forecast_backtest"}
