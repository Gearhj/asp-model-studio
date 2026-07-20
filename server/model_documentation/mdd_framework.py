"""Validator-aligned MDD template and lifecycle rules used by Documentation Studio."""
from __future__ import annotations

COMMON_BACKBONE = [
    ("admin", "Document Administration", True),
    ("objectives", "1. Model Objectives, Business Context, and Key Model Risks", True),
    ("framework", "2. Model Framework and Summary of Development Outcome", True),
    ("data", "3. Model Data and Inputs", True),
    ("development", "4. Model Estimation, Development, Calibration, Fitting, or Solution Construction", True),
    ("testing", "5. Model Testing and Performance", True),
    ("implementation", "6. Production Implementation and Control", True),
    ("monitoring", "7. Ongoing Performance Monitoring", True),
    ("supporting_material", "Supporting Material", False),
]

FAMILY_REQUIREMENTS = {
    "predictive_classification": ["threshold selection", "decile analysis", "calibration", "segment performance"],
    "predictive_regression": ["residual diagnostics", "error by target range", "multicollinearity"],
    "credit_risk": ["intended use", "fair lending review", "adverse action explainability", "monitoring"],
    "time_series_forecasting": ["temporal split", "forecast horizon", "baseline comparison", "seasonality", "backtesting"],
    "optimization": ["objective", "decision variables", "constraints", "solver status", "feasibility", "sensitivity"],
    "ab_testing": ["hypothesis", "estimand", "randomization", "power", "implementation fidelity"],
    "experimental_design": ["factors", "levels", "randomization", "blocking", "ANOVA"],
    "llm_genai": ["component architecture", "grounding", "safety", "adversarial testing", "human review", "fallback"],
    "graph_analytics": ["graph construction", "node and edge provenance", "network diagnostics"],
    "computer_vision": ["labeling", "dataset shift", "image quality", "human review"],
    "reinforcement_learning": ["reward design", "policy constraints", "simulation", "fallback"],
    "generic_quantitative": ["methodology", "assumptions", "testing", "monitoring"],
}

DOCUMENT_STATUSES = {"working_draft", "internal_review", "management_review", "management_approved", "proposed_for_validation", "under_validation", "validation_changes_required", "validated_current", "superseded", "withdrawn", "archived"}

def family_for_project(project_type: str, task_type: str = "") -> str:
    value = f"{project_type} {task_type}".lower()
    if "time series" in value or "forecast" in value: return "time_series_forecasting"
    if "optimization" in value: return "optimization"
    if "a/b" in value or "ab testing" in value: return "ab_testing"
    if "experimental" in value: return "experimental_design"
    if "llm" in value or "generative" in value: return "llm_genai"
    if "regression" in value: return "predictive_regression"
    if "credit" in value: return "credit_risk"
    return "predictive_classification" if "classification" in value else "generic_quantitative"

def template_sections(family: str):
    return [*COMMON_BACKBONE, *[(f"method_{i}", requirement.title(), True) for i, requirement in enumerate(FAMILY_REQUIREMENTS.get(family, FAMILY_REQUIREMENTS["generic_quantitative"]), 1)]]

def changed_sections_not_disclosed(changes: list[dict], summary_sections: list[str]) -> list[str]:
    return sorted({item.get("section_id") for item in changes if item.get("section_id") and item.get("section_id") not in summary_sections})
