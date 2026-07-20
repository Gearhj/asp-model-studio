from __future__ import annotations

from typing import Any


def monitoring_baselines(statistics: dict[str, Any], analysis_type: str) -> list[dict[str, Any]]:
    metric_names = {
        "classification_diagnostics": ["roc_auc", "pr_auc", "ks_statistic", "calibration_error"],
        "regression_diagnostics": ["mae", "rmse", "mean_residual"],
        "forecast_diagnostics": ["mae", "rmse", "wape", "bias", "interval_coverage"],
        "optimization_diagnostics": ["objective_value", "optimality_gap"],
    }.get(analysis_type, [])
    return [{"metric": name, "baseline": statistics[name], "direction": "lower_is_better" if name in {"mae", "rmse", "wape", "bias", "calibration_error", "optimality_gap"} else "higher_is_better"} for name in metric_names if statistics.get(name) is not None]
