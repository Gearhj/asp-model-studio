from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


CANONICAL_DATASET_LINEAGE_CONTRACT = "canonical_dataset_version"


class CanonicalEvidenceLineage(BaseModel):
    """Exact immutable Dataset Library identity carried by governed evidence.

    Camel-case fields used by the legacy Evidence Graph are deliberately not
    accepted as substitutes. They are emitted later as derived compatibility
    aliases only after these canonical fields have been authorized and checked
    against the active modeling scope.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version_id: str = Field(min_length=1)
    lineage_contract: Literal["canonical_dataset_version"] = (
        CANONICAL_DATASET_LINEAGE_CONTRACT
    )

    @field_validator("project_id", "dataset_id", "dataset_version_id")
    @classmethod
    def identifiers_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Canonical evidence identifiers cannot be blank.")
        return cleaned


EVIDENCE_TYPES = {
    "dataset",
    "sql_query",
    "sql_result",
    "eda",
    "missing_values",
    "outliers",
    "feature_engineering",
    "vif",
    "model_training",
    "model_selection",
    "evaluation",
    "model_diagnostics",
    "chart",
    "notebook",
    "documentation",
    "governance",
    "decision",
    "export",
    "optimization_decision_charter",
    "optimization_input_bundle",
    "optimization_data_profile",
    "optimization_route_normalization",
    "optimization_formulation_readiness",
    "optimization_objective",
    "optimization_decision_variables",
    "optimization_constraints",
    "optimization_solver_configuration",
    "optimization_baseline",
    "optimization_scenarios",
    "optimization_solver_run",
    "optimization_solution",
    "optimization_sensitivity",
    "optimization_validation",
    "optimization_recommendation",
    "optimization_implementation_plan",
    "optimization_monitoring_plan",
    "optimization_documentation_package",
    "optimization_reproducibility_code",
    "optimization_code_reproducibility",
}

EVIDENCE_STATUSES = {"draft", "ready", "needs_review", "accepted", "deprecated"}
EVIDENCE_IMPORTANCE = {"low", "medium", "high", "critical"}

FINANCIAL_SERVICES_TAGS = {
    "credit_risk",
    "fraud",
    "aml",
    "marketing",
    "profitability",
    "model_risk",
    "fair_lending",
    "underwriting",
    "portfolio_management",
    "monitoring",
    "governance",
}

DOCUMENTATION_SECTIONS = {
    "dataset": ["Data Sources", "Data Quality", "Population Definition"],
    "sql_query": ["Data Sources", "Lineage"],
    "sql_result": ["Data Sources", "Lineage"],
    "eda": ["Exploratory Data Analysis"],
    "missing_values": ["Missing Value Strategy"],
    "outliers": ["Outlier Strategy"],
    "feature_engineering": ["Feature Engineering"],
    "vif": ["Model Diagnostics", "Feature Importance"],
    "model_training": ["Candidate Models", "Model Training"],
    "model_selection": ["Champion Model", "Model Selection Rationale"],
    "evaluation": ["Performance Summary", "ROC and PR Summary", "Lift / Decile Analysis"],
    "model_diagnostics": ["Model Diagnostics", "Interpretability Notes"],
    "chart": ["Exploratory Data Analysis", "Appendix"],
    "notebook": ["Appendix", "Reproducibility"],
    "documentation": ["Model Development Document"],
    "governance": ["Governance", "Fair Lending / Compliance Considerations"],
    "decision": ["Decision Journal Appendix"],
    "export": ["Appendix"],
    "optimization_decision_charter": ["Executive Summary", "Business Decision"],
    "optimization_input_bundle": ["Data Inputs", "Data Quality"],
    "optimization_data_profile": ["Data Inputs", "Data Quality"],
    "optimization_route_normalization": ["Data Inputs", "Decision Variables"],
    "optimization_formulation_readiness": ["Formulation Readiness"],
    "optimization_objective": ["Objective Function"],
    "optimization_decision_variables": ["Decision Variables"],
    "optimization_constraints": ["Constraints"],
    "optimization_solver_configuration": ["Solver Configuration"],
    "optimization_baseline": ["Baseline and Scenarios"],
    "optimization_scenarios": ["Baseline and Scenarios", "Sensitivity and Tradeoffs"],
    "optimization_solver_run": ["Optimization Results", "Reproducibility Appendix"],
    "optimization_solution": ["Optimization Results"],
    "optimization_sensitivity": ["Sensitivity and Tradeoffs"],
    "optimization_validation": ["Validation"],
    "optimization_recommendation": ["Recommendation"],
    "optimization_implementation_plan": ["Implementation Plan"],
    "optimization_monitoring_plan": ["Monitoring Plan"],
    "optimization_documentation_package": [
        "Executive Summary",
        "Business Decision",
        "Data Inputs",
        "Formulation Readiness",
        "Objective Function",
        "Decision Variables",
        "Constraints",
        "Solver Configuration",
        "Baseline and Scenarios",
        "Optimization Results",
        "Sensitivity and Tradeoffs",
        "Validation",
        "Recommendation",
        "Implementation Plan",
        "Monitoring Plan",
        "Limitations",
        "Approvals",
        "Reproducibility Appendix",
        "Python Code",
        "SAS-Compatible Code",
    ],
    "optimization_reproducibility_code": ["Reproducibility Appendix", "Python Code", "SAS-Compatible Code"],
    "optimization_code_reproducibility": ["Reproducibility Appendix", "Python Code", "SAS-Compatible Code"],
}
