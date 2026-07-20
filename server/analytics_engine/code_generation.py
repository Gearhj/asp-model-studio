from __future__ import annotations

from typing import Any


SAS_PROCEDURES = {
    "classification_diagnostics": "PROC LOGISTIC or PROC HPLOGISTIC",
    "regression_diagnostics": "PROC REG or PROC GLM",
    "time_series_profile": "PROC TIMESERIES, PROC ARIMA, or PROC ESM",
    "forecast_diagnostics": "PROC TIMESERIES or PROC ESM",
    "experiment_diagnostics": "PROC GLM or PROC MIXED",
    "optimization_diagnostics": "PROC OPTMODEL",
}


def reproducible_code(analysis_type: str, context: dict[str, Any], parameters: dict[str, Any]) -> dict[str, str]:
    dataset = context.get("dataset_name") or context.get("dataset_id") or "<registered_dataset_reference>"
    parameter_lines = "\n".join(f"{key} = {value!r}" for key, value in parameters.items()) or "# Use ATLAS result parameters."
    python = (
        "import pandas as pd\n"
        "# Resolve this governed Dataset Library reference in the ATLAS execution environment.\n"
        f"dataset_reference = {dataset!r}\n{parameter_lines}\n"
        f"# Reproduce the {analysis_type} calculation with the documented inputs above.\n"
    )
    sas = SAS_PROCEDURES.get(analysis_type, "Use the SAS procedure appropriate for the documented analytical method.")
    return {"python": python, "sas_guidance": f"SAS-compatible implementation guidance: {sas}. This guidance is not a claim of identical SAS output."}
