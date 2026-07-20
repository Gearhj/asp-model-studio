from __future__ import annotations

from typing import Dict, List


ValidationTemplate = Dict[str, object]


OPTIMIZATION_ITEMS = [
    ("business_context", "Business purpose and intended use", "Decision, objective, owner, constraints, and deployment context are clear."),
    ("data_lineage", "Data lineage and source control", "Input tables, versions, transformations, and approvals are traceable."),
    ("formulation", "Mathematical formulation", "Objective, decision variables, constraints, feasibility logic, and units are reproducible."),
    ("solver", "Solver configuration", "Algorithm, parameters, convergence, infeasibility handling, and reproducibility settings are documented."),
    ("scenario_testing", "Scenario and sensitivity testing", "Stress cases, binding constraints, reduced costs, and stability are reviewed."),
    ("recommendation", "Recommendation and implementation", "Recommended action, alternatives, caveats, owner, and monitoring plan are complete."),
]

PREDICTIVE_ITEMS = [
    ("business_context", "Business purpose and model use", "Purpose, target, population, horizon, and decision use are documented."),
    ("data_quality", "Data quality and lineage", "Source data, splits, target construction, leakage controls, and exclusions are traceable."),
    ("feature_governance", "Feature governance", "Feature selection, transformations, special values, and prohibited fields are reviewed."),
    ("model_development", "Model development", "Algorithms, tuning, challenger models, calibration, and reproducibility are documented."),
    ("performance", "Performance and stability", "Holdout, OOT, segment, fairness, stability, and monitoring evidence are reviewed."),
    ("implementation", "Implementation readiness", "Champion model, score export, cutoff policy, rollback, and monitoring plan are complete."),
]

AB_TEST_ITEMS = [
    ("experiment_design", "Experiment design", "Hypothesis, unit, treatment, control, outcome, guardrails, and assignment are clear."),
    ("data_integrity", "Experiment data integrity", "Full dataset, treatment exposure, conversion mapping, duplicates, and exclusions are verified."),
    ("randomization", "Randomization and balance", "Allocation, baseline balance, spillover, and sample-size power are reviewed."),
    ("analysis", "Experiment analysis", "Lift, confidence intervals, p-values, segment effects, and multiple comparisons are reviewed."),
    ("decision", "Decision recommendation", "Launch, holdout, run-longer, segmented, or no-launch recommendation is supported."),
]

EXPERIMENTAL_DESIGN_ITEMS = [
    ("design_context", "Design context", "Research question, factors, levels, blocks, and response variables are defined."),
    ("power", "Power and sample size", "Detectable effect, replication, randomization, and feasibility are reviewed."),
    ("run_plan", "Experiment run plan", "Execution order, blocking, randomization, collection controls, and contamination risks are documented."),
    ("analysis", "Analysis plan", "ANOVA, interactions, response surface, contrasts, and assumptions are reviewed."),
    ("decision", "Decision path", "Optimization, robust settings, or follow-up experiment criteria are clear."),
]

TIME_SERIES_ITEMS = [
    ("time_index", "Time index and frequency", "Date/time field, frequency, timezone, aggregation grain, and irregular intervals are reviewed."),
    ("target_coverage", "Target definition and coverage", "Forecast target, date range, entity coverage, missing timestamps, duplicates, and zero or negative values are documented."),
    ("temporal_split", "Temporal split and backtest design", "Rolling, expanding, or holdout-by-date validation preserves temporal order and leakage controls."),
    ("feature_calendar", "Feature and calendar design", "Lag, rolling, calendar, event, intervention, exogenous, and future-known features are governed."),
    ("model_comparison", "Model comparison and backtesting", "Baseline, statistical, machine-learning, and anomaly candidates are compared with selected metrics."),
    ("diagnostics", "Forecast diagnostics and stability", "Residuals, bias, interval coverage, horizon error, anomalies, drift, and regime changes are reviewed."),
    ("scenarios", "Scenario and stress testing", "Future shocks, downturns, fraud spikes, operational outages, and business events are stress tested."),
    ("monitoring", "Recommendation and monitoring plan", "Forecast use, limitations, thresholds, reforecast triggers, cadence, and escalation are complete."),
    ("reproducibility", "Documentation and reproducibility", "Evidence inventory, Python code, SAS-compatible template, exports, and approval record are traceable."),
]

LLM_ITEMS = [
    ("use_case_risk", "Use case risk and allowed behavior", "Workflow mode, users, customer impact, prohibited uses, sensitive data, and human review are documented."),
    ("source_inventory", "Source inventory and permitted use", "Documents, datasets, source owners, versions, hashes, PII handling, freshness, and inclusion rules are traceable."),
    ("task_schema", "Task design and output schema", "Task type, schema, citations, confidence requirements, refusal behavior, escalation, labels, or extraction fields are defined."),
    ("prompt_design", "Prompt and instruction design", "System, developer, and user prompts, examples, guardrails, citation rules, and versioning are reviewed."),
    ("retrieval", "Retrieval configuration", "Chunking, embeddings, index label, metadata filters, reranking, citation coverage, and no-source fallback are reviewed where applicable."),
    ("evaluation", "Evaluation dataset and results", "Golden cases, edge cases, adversarial cases, metrics, reviewer sampling, and failure severity are documented."),
    ("safety", "Safety, compliance, and red-team review", "Prompt injection, leakage, hallucination, unsupported answer, privacy, UDAAP, fair lending, and escalation controls are reviewed."),
    ("human_review", "Human review and quality control", "Reviewer role, sampling strategy, overrides, escalation, rubric, thresholds, and QA cadence are defined."),
    ("deployment_monitoring", "Deployment and monitoring", "Deployment mode, model/provider version, prompt version, source version, monitoring metrics, incidents, and re-evaluation triggers are complete."),
    ("reproducibility", "Documentation and reproducibility", "Prompt package, source registry, evaluation outputs, evidence inventory, Python code, SQL/SAS templates, and approval record are traceable."),
]

GENERIC_ITEMS = [
    ("context", "Purpose and scope", "The project objective, decision owner, and intended use are documented."),
    ("data", "Data and evidence", "Inputs, lineage, outputs, and evidence artifacts are traceable."),
    ("methodology", "Methodology", "The analytical method, assumptions, limitations, and reproducibility are documented."),
    ("decision", "Decision and monitoring", "Recommendation, implementation owner, monitoring, and review cadence are documented."),
]


TEMPLATES: Dict[str, ValidationTemplate] = {
    "optimization": {"template_id": "optimization", "name": "Optimization validation", "items": OPTIMIZATION_ITEMS},
    "predictive_modeling": {"template_id": "predictive_modeling", "name": "Predictive modeling validation", "items": PREDICTIVE_ITEMS},
    "ab_testing": {"template_id": "ab_testing", "name": "A/B testing validation", "items": AB_TEST_ITEMS},
    "experimental_design": {"template_id": "experimental_design", "name": "Experimental design validation", "items": EXPERIMENTAL_DESIGN_ITEMS},
    "time_series_forecasting": {"template_id": "time_series_forecasting", "name": "Time Series & Forecasting validation", "items": TIME_SERIES_ITEMS},
    "llm_generative_ai": {"template_id": "llm_generative_ai", "name": "LLM / Generative AI validation", "items": LLM_ITEMS},
    "generic": {"template_id": "generic", "name": "Generic analytical validation", "items": GENERIC_ITEMS},
}


def template_for_project(project: dict) -> ValidationTemplate:
    project_type = str(project.get("project_type") or "").lower()
    workflow_type = str(project.get("workflow_type") or "").lower()
    template_id = str(project.get("template_id") or "").lower()
    joined = " ".join([project_type, workflow_type, template_id])
    if "optimization" in joined:
        return TEMPLATES["optimization"]
    if "ab" in joined or "a/b" in joined:
        return TEMPLATES["ab_testing"]
    if "experimental" in joined or "experiment" in joined:
        return TEMPLATES["experimental_design"]
    if "time_series_forecasting" in joined or "time series" in joined or "time-series" in joined or "forecasting" in joined:
        return TEMPLATES["time_series_forecasting"]
    if "llm_generative_ai" in joined or "generative ai" in joined or "generative-ai" in joined or "llm" in joined:
        return TEMPLATES["llm_generative_ai"]
    if "predictive" in joined or "model" in joined or "credit" in joined:
        return TEMPLATES["predictive_modeling"]
    return TEMPLATES["generic"]


def checklist_items(template: ValidationTemplate) -> List[dict]:
    template_id = str(template["template_id"])
    return [
        {
            "template_id": template_id,
            "category": str(label).split(" and ")[0],
            "item_key": key,
            "item_label": label,
            "item_description": description,
            "sort_order": index + 1,
        }
        for index, (key, label, description) in enumerate(template["items"])  # type: ignore[index]
    ]
