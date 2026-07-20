from __future__ import annotations

from typing import Any, Dict, List


def _metric(name: str, category: str, definition: str, direction: str = "lower_is_worse", warning: float | None = None, breach: float | None = None, unit: str | None = None) -> Dict[str, Any]:
    return {
        "metric_name": name,
        "metric_category": category,
        "metric_definition": definition,
        "metric_direction": direction,
        "warning_threshold": warning,
        "breach_threshold": breach,
        "unit": unit,
        "cadence": "monthly",
    }


MONITORING_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "predictive_modeling": {
        "template_id": "predictive_modeling",
        "label": "Predictive Modeling",
        "metrics": [
            _metric("AUC", "model performance", "Area under ROC curve.", "lower_is_worse", 0.70, 0.65),
            _metric("PR-AUC", "model performance", "Precision-recall area under curve.", "lower_is_worse", 0.50, 0.40),
            _metric("KS", "model performance", "Kolmogorov-Smirnov separation statistic.", "lower_is_worse", 0.25, 0.20),
            _metric("Precision", "model performance", "Positive predictive value.", "lower_is_worse", 0.40, 0.30),
            _metric("Recall", "model performance", "True positive capture rate.", "lower_is_worse", 0.40, 0.30),
            _metric("F1", "model performance", "Harmonic mean of precision and recall.", "lower_is_worse", 0.40, 0.30),
            _metric("Lift", "model performance", "Top decile or selected-band lift.", "lower_is_worse", 1.20, 1.00),
            _metric("Calibration error", "calibration", "Absolute calibration error.", "higher_is_worse", 0.05, 0.10),
            _metric("PSI", "input drift", "Population stability index.", "higher_is_worse", 0.10, 0.25),
            _metric("VSI", "input drift", "Variable stability index.", "higher_is_worse", 0.10, 0.25),
            _metric("Prediction distribution drift", "prediction drift", "Shift in model score distribution.", "higher_is_worse", 0.10, 0.25),
            _metric("Score decile stability", "stability", "Observed decile movement from baseline.", "higher_is_worse", 0.10, 0.20),
            _metric("Missingness rate", "data quality", "Share of missing inputs.", "higher_is_worse", 0.05, 0.10),
            _metric("Outlier rate", "data quality", "Share of outlier inputs.", "higher_is_worse", 0.05, 0.10),
            _metric("Approval rate", "operational usage", "Approval or positive decision rate.", "two_sided", None, None, "%"),
            _metric("Segment performance", "stability", "Lowest segment performance versus baseline.", "lower_is_worse", 0.70, 0.60),
            _metric("Adverse impact ratio", "fairness/compliance", "Protected-class or proxy adverse impact ratio.", "lower_is_worse", 0.80, 0.70),
        ],
    },
    "credit_risk": {
        "template_id": "credit_risk",
        "label": "Credit Risk",
        "metrics": [
            _metric("KS", "model performance", "Credit model separation statistic.", "lower_is_worse", 0.25, 0.20),
            _metric("AUC", "model performance", "Area under ROC curve.", "lower_is_worse", 0.70, 0.65),
            _metric("Bad rate by score band", "calibration", "Observed bad rate by score band.", "higher_is_worse", 0.03, 0.05),
            _metric("Calibration by decile", "calibration", "Observed versus expected decile gap.", "higher_is_worse", 0.05, 0.10),
            _metric("PSI", "input drift", "Population stability index.", "higher_is_worse", 0.10, 0.25),
            _metric("VSI", "input drift", "Variable stability index.", "higher_is_worse", 0.10, 0.25),
            _metric("Approval rate", "operational usage", "Credit approval rate.", "two_sided", None, None, "%"),
            _metric("Override rate", "operational usage", "Manual override rate.", "higher_is_worse", 0.05, 0.10),
            _metric("Delinquency roll rate", "performance", "Roll rate into delinquency status.", "higher_is_worse", 0.03, 0.05),
            _metric("Adverse impact ratio", "fairness/compliance", "Fair-lending adverse impact ratio.", "lower_is_worse", 0.80, 0.70),
            _metric("Policy exception rate", "compliance", "Exception rate from credit policy.", "higher_is_worse", 0.03, 0.05),
            _metric("Risk tier stability", "stability", "Population movement by risk tier.", "higher_is_worse", 0.10, 0.20),
        ],
    },
    "optimization": {
        "template_id": "optimization",
        "label": "Optimization",
        "metrics": [
            _metric("Realized objective value", "performance", "Actual objective value after implementation.", "lower_is_worse"),
            _metric("Realized versus optimized cost", "performance", "Actual cost variance from optimized plan.", "higher_is_worse", 0.05, 0.10),
            _metric("Constraint breach count", "constraints", "Number of production constraint breaches.", "higher_is_worse", 1, 3),
            _metric("Demand fulfilled", "service", "Share of demand fulfilled.", "lower_is_worse", 0.95, 0.90),
            _metric("Capacity utilization", "operations", "Used capacity versus available capacity.", "two_sided"),
            _metric("Allocation override rate", "operations", "Manual override rate from recommended allocations.", "higher_is_worse", 0.05, 0.10),
            _metric("Infeasible decisions", "constraints", "Count of infeasible routes or decisions.", "higher_is_worse", 1, 3),
            _metric("Re-optimization trigger count", "operations", "Number of re-optimization triggers.", "higher_is_worse", 1, 3),
            _metric("Scenario breach", "scenario tracking", "Scenario assumption breach count.", "higher_is_worse", 1, 3),
            _metric("Input refresh status", "data quality", "Input freshness and completeness.", "lower_is_worse", 0.95, 0.90),
            _metric("Actual vs recommended decision variance", "operations", "Variance from approved recommendation.", "higher_is_worse", 0.05, 0.10),
        ],
    },
    "time_series_forecasting": {
        "template_id": "time_series_forecasting",
        "label": "Time Series & Forecasting",
        "metrics": [
            _metric("Forecast error", "forecast performance", "Forecast error for monitored horizon.", "higher_is_worse", 0.15, 0.25),
            _metric("WAPE", "forecast performance", "Weighted absolute percentage error.", "higher_is_worse", 0.15, 0.25),
            _metric("MAPE", "forecast performance", "Mean absolute percentage error.", "higher_is_worse", 0.15, 0.25),
            _metric("MAE", "forecast performance", "Mean absolute error.", "higher_is_worse"),
            _metric("RMSE", "forecast performance", "Root mean squared error.", "higher_is_worse"),
            _metric("Bias", "forecast performance", "Forecast bias.", "two_sided"),
            _metric("Interval coverage", "forecast performance", "Observed coverage of prediction intervals.", "lower_is_worse", 0.80, 0.70),
            _metric("Data freshness", "data quality", "Freshness of forecast input feed.", "lower_is_worse", 0.95, 0.90),
            _metric("Missing timestamps", "data quality", "Missing period count.", "higher_is_worse", 1, 3),
            _metric("Volume drift", "drift", "Volume movement from baseline.", "higher_is_worse", 0.10, 0.25),
            _metric("Seasonality drift", "drift", "Seasonality pattern change.", "higher_is_worse", 0.10, 0.25),
            _metric("Anomaly rate", "stability", "Share of anomalous periods.", "higher_is_worse", 0.05, 0.10),
            _metric("Forecast override rate", "operations", "Manual forecast override rate.", "higher_is_worse", 0.05, 0.10),
            _metric("Backtest degradation", "performance", "Backtest performance degradation.", "higher_is_worse", 0.05, 0.10),
            _metric("Reforecast trigger count", "operations", "Number of reforecast triggers.", "higher_is_worse", 1, 3),
        ],
    },
    "llm_generative_ai": {
        "template_id": "llm_generative_ai",
        "label": "LLM / Generative AI",
        "metrics": [
            _metric("Groundedness", "quality", "Share of outputs grounded in approved sources.", "lower_is_worse", 0.90, 0.80),
            _metric("Citation accuracy", "quality", "Share of citations that support the answer.", "lower_is_worse", 0.90, 0.80),
            _metric("Hallucination rate", "quality", "Share of outputs with unsupported claims.", "higher_is_worse", 0.03, 0.05),
            _metric("Refusal correctness", "safety", "Correct handling of refusal scenarios.", "lower_is_worse", 0.90, 0.80),
            _metric("Policy compliance", "safety", "Share of outputs passing policy checks.", "lower_is_worse", 0.95, 0.90),
            _metric("Escalation rate", "operations", "Human escalation rate.", "higher_is_worse", 0.10, 0.20),
            _metric("Reviewer override rate", "operations", "Reviewer override rate.", "higher_is_worse", 0.05, 0.10),
            _metric("User feedback score", "quality", "Average user feedback score.", "lower_is_worse", 3.5, 3.0),
            _metric("Prompt injection attempts", "security", "Detected prompt injection attempts.", "higher_is_worse", 1, 3),
            _metric("Data leakage incidents", "security", "Confirmed data leakage incidents.", "higher_is_worse", 1, 1),
            _metric("Source freshness", "retrieval", "Approved source freshness.", "lower_is_worse", 0.90, 0.80),
            _metric("Retrieval failure rate", "retrieval", "Retrieval failure rate.", "higher_is_worse", 0.05, 0.10),
            _metric("Latency", "operations", "Response latency.", "higher_is_worse"),
            _metric("Cost", "operations", "Unit cost.", "higher_is_worse"),
            _metric("Input topic drift", "drift", "Input topic distribution drift.", "higher_is_worse", 0.10, 0.25),
        ],
    },
    "experimentation": {
        "template_id": "experimentation",
        "label": "Experimentation",
        "metrics": [
            _metric("Experiment result status", "decision quality", "Current experiment result state.", "lower_is_worse"),
            _metric("Metric lift stability", "performance", "Lift stability after decision.", "lower_is_worse", 0.90, 0.80),
            _metric("Conversion rate", "performance", "Observed conversion rate after experiment decision.", "two_sided"),
            _metric("Guardrail metric breaches", "risk", "Guardrail breach count.", "higher_is_worse", 1, 3),
            _metric("Sample ratio mismatch", "data quality", "Assignment balance deviation.", "higher_is_worse", 0.02, 0.05),
            _metric("Segment drift", "drift", "Segment composition drift.", "higher_is_worse", 0.10, 0.25),
            _metric("Post-launch performance", "performance", "Launch performance versus experiment estimate.", "lower_is_worse", 0.90, 0.80),
            _metric("Implementation adherence", "operations", "Adherence to approved rollout plan.", "lower_is_worse", 0.95, 0.90),
        ],
    },
    "generic": {
        "template_id": "generic",
        "label": "Generic Monitoring",
        "metrics": [
            _metric("Data freshness", "data quality", "Freshness of production data feed.", "lower_is_worse", 0.95, 0.90),
            _metric("Data quality", "data quality", "Overall production data quality score.", "lower_is_worse", 0.95, 0.90),
            _metric("Evidence completeness", "governance", "Monitoring evidence completeness.", "lower_is_worse", 0.90, 0.80),
            _metric("Performance status", "performance", "Overall production performance score.", "lower_is_worse", 0.90, 0.80),
            _metric("Open issue count", "operations", "Open production issue count.", "higher_is_worse", 1, 3),
            _metric("Documentation status", "governance", "Monitoring documentation completeness.", "lower_is_worse", 0.90, 0.80),
        ],
    },
}


def normalize_workflow_type(value: str | None) -> str:
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if "credit" in key and "risk" in key:
        return "credit_risk"
    if "optimization" in key:
        return "optimization"
    if "time" in key or "forecast" in key:
        return "time_series_forecasting"
    if "llm" in key or "generative" in key:
        return "llm_generative_ai"
    if "ab" in key or "experiment" in key:
        return "experimentation"
    if "predictive" in key or "classification" in key or "regression" in key:
        return "predictive_modeling"
    return key or "generic"


def template_for_workflow(workflow_type: str | None) -> Dict[str, Any]:
    key = normalize_workflow_type(workflow_type)
    return MONITORING_TEMPLATES.get(key) or MONITORING_TEMPLATES["generic"]


def list_templates() -> List[Dict[str, Any]]:
    return list(MONITORING_TEMPLATES.values())
