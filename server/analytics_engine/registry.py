"""Central registry metadata for supported governed analytics calculations."""

ANALYSIS_TYPES = (
    "descriptive_profile", "data_quality_profile", "classification_diagnostics",
    "regression_diagnostics", "time_series_profile", "forecast_diagnostics",
    "forecast_backtest", "experiment_diagnostics", "anova", "power_analysis",
    "optimization_diagnostics", "llm_evaluation", "segment_diagnostics", "fairness_diagnostics",
)


def supported_analysis_types() -> list[str]:
    return list(ANALYSIS_TYPES)
