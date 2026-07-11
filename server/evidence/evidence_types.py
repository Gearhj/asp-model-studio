from __future__ import annotations

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
}

