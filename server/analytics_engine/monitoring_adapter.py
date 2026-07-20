from __future__ import annotations
from typing import Any, Dict

METRIC_MAPPING={"classification_diagnostics":[("ROC AUC","performance","lower_is_worse"),("PR AUC","performance","lower_is_worse"),("KS","stability","lower_is_worse"),("Brier score","calibration","higher_is_worse")],"regression_diagnostics":[("RMSE","performance","higher_is_worse"),("MAE","performance","higher_is_worse"),("Bias","performance","two_sided")],"forecast_diagnostics":[("WAPE","performance","higher_is_worse"),("MAE","performance","higher_is_worse"),("RMSE","performance","higher_is_worse"),("Bias","performance","two_sided"), ("Interval coverage","calibration","lower_is_worse")],"optimization_diagnostics":[("Objective value","performance","lower_is_worse"),("Constraint utilization","operational","higher_is_worse")]}

def monitoring_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    return {"eligible_metrics":[{"metric_name":name,"category":category,"direction":direction} for name,category,direction in METRIC_MAPPING.get(result.get("analysis_type"),[])]}
