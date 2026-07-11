from __future__ import annotations

from typing import Any, Dict, List

FINANCIAL_DOMAINS = {
    "credit_risk": "Credit Risk / Underwriting",
    "fraud_aml": "Fraud / AML",
    "marketing_profitability": "Marketing / Profitability",
    "model_risk_governance": "Model Risk / Governance",
    "portfolio_risk": "Portfolio Risk",
    "decision_strategy": "Decision Strategy",
}

CREDIT_RISK_TECHNIQUES = {
    "pdo": {"category": "Underwriting Model Techniques", "label": "PDO Scaling"},
    "woe": {"category": "Underwriting Model Techniques", "label": "Weight of Evidence"},
    "iv": {"category": "Underwriting Model Techniques", "label": "Information Value"},
    "manual_binning": {"category": "Underwriting Model Techniques", "label": "Manual Characteristic Binning"},
    "reject_inference": {"category": "Underwriting Model Techniques", "label": "Reject Inference"},
    "ttc": {"category": "Portfolio Risk", "label": "Through-the-Cycle Calibration"},
    "pit": {"category": "Portfolio Risk", "label": "Point-in-Time Calibration"},
    "psi": {"category": "Portfolio Risk", "label": "Population Stability Index"},
    "challenger_champion": {"category": "Portfolio Risk", "label": "Challenger / Champion"},
    "adverse_action": {"category": "Regulatory / Governance", "label": "Adverse Action Engineering"},
    "fair_lending": {"category": "Regulatory / Governance", "label": "Fair Lending Testing"},
    "monotonic_constraints": {"category": "Regulatory / Governance", "label": "Monotonic Variable Constraints"},
    "cutoff_optimization": {"category": "Decision Strategy", "label": "Cutoff Optimization"},
    "strategy_trees": {"category": "Decision Strategy", "label": "Strategy Trees / Rule Overlays"},
    "risk_based_pricing": {"category": "Decision Strategy", "label": "Risk-Based Pricing"},
    "monotonic_gbm": {"category": "Modern Underwriting", "label": "Monotonic GBM"},
    "surrogate_scorecard": {"category": "Modern Underwriting", "label": "Surrogate Scorecard"},
    "scorecard_scaling": {"category": "Modern Underwriting", "label": "Scorecard Scaling"},
    "odds_calibration": {"category": "Modern Underwriting", "label": "Odds Calibration"},
}

CREDIT_RISK_REQUIRED_TECHNIQUES = [
    "woe",
    "iv",
    "manual_binning",
    "pdo",
    "adverse_action",
    "fair_lending",
    "psi",
    "cutoff_optimization",
    "challenger_champion",
]

CREDIT_RISK_DOCUMENTATION_MAPPING = {
    "pdo": ["Model Interpretation", "Champion Model", "Appendix"],
    "woe": ["Feature Engineering", "Interpretability Notes", "Appendix"],
    "iv": ["Feature Engineering", "Model Diagnostics", "Appendix"],
    "manual_binning": ["Feature Engineering", "Interpretability Notes", "Fair Lending / Compliance Considerations"],
    "reject_inference": ["Data Sources", "Target Definition", "Model Limitations"],
    "ttc": ["Performance Summary", "Monitoring Recommendations"],
    "pit": ["Performance Summary", "Monitoring Recommendations"],
    "psi": ["Model Diagnostics", "Monitoring Recommendations"],
    "challenger_champion": ["Candidate Models", "Champion Model", "Monitoring Recommendations"],
    "adverse_action": ["Interpretability Notes", "Fair Lending / Compliance Considerations"],
    "fair_lending": ["Fair Lending / Compliance Considerations", "Model Limitations"],
    "monotonic_constraints": ["Feature Engineering", "Interpretability Notes", "Fair Lending / Compliance Considerations"],
    "cutoff_optimization": ["Champion Model", "Performance Summary", "Model Limitations"],
    "strategy_trees": ["Model Purpose", "Implementation Plan", "Monitoring Recommendations"],
    "risk_based_pricing": ["Intended Use", "Fair Lending / Compliance Considerations", "Model Limitations"],
    "monotonic_gbm": ["Candidate Models", "Interpretability Notes", "Fair Lending / Compliance Considerations"],
    "surrogate_scorecard": ["Model Interpretation", "Model Limitations", "Appendix"],
    "scorecard_scaling": ["Champion Model", "Model Interpretation", "Appendix"],
    "odds_calibration": ["Performance Summary", "Model Diagnostics", "Appendix"],
}


def infer_financial_domain(task_type: str | None = None, target: str | None = None) -> Dict[str, Any]:
    text = f"{task_type or ''} {target or ''}".lower()
    credit_terms = ["default", "delinq", "chargeoff", "charge_off", "bad", "loss", "approval", "underwriting", "risk", "class"]
    fraud_terms = ["fraud", "aml", "kyc", "suspicious"]
    marketing_terms = ["response", "conversion", "attrition", "activation", "profit", "roi"]
    if any(term in text for term in fraud_terms):
        return {"domain": "fraud_aml", "label": FINANCIAL_DOMAINS["fraud_aml"], "confidence": 82}
    if any(term in text for term in credit_terms):
        return {"domain": "credit_risk", "label": FINANCIAL_DOMAINS["credit_risk"], "confidence": 86}
    if any(term in text for term in marketing_terms):
        return {"domain": "marketing_profitability", "label": FINANCIAL_DOMAINS["marketing_profitability"], "confidence": 76}
    return {"domain": "model_risk_governance", "label": FINANCIAL_DOMAINS["model_risk_governance"], "confidence": 55}


def credit_risk_checklist(items: List[Dict[str, Any]], project_id: str | None = None, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    rows = [item for item in items if not project_id or item.get("projectId") == project_id]
    evidence_by_technique: Dict[str, List[Dict[str, Any]]] = {}
    for item in rows:
        technique = str(item.get("financialTechnique") or "")
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        keys = [technique] if technique else []
        keys.extend(tag for tag in tags if tag in CREDIT_RISK_TECHNIQUES)
        if item.get("financialDomain") == "credit_risk" and not keys:
            keys.append("credit_risk")
        for key in set(keys):
            evidence_by_technique.setdefault(key, []).append(item)

    checklist = []
    for technique, meta in CREDIT_RISK_TECHNIQUES.items():
        matches = evidence_by_technique.get(technique, [])
        ready = [item for item in matches if item.get("status") in {"ready", "accepted"}]
        required = technique in CREDIT_RISK_REQUIRED_TECHNIQUES
        status = "ready" if ready else "needs_review" if matches else "missing" if required else "optional"
        checklist.append(
            {
                "technique": technique,
                "label": meta["label"],
                "category": meta["category"],
                "required": required,
                "status": status,
                "count": len(matches),
                "ready": len(ready),
                "documentationSections": CREDIT_RISK_DOCUMENTATION_MAPPING.get(technique, []),
            }
        )

    required_items = [item for item in checklist if item["required"]]
    ready_required = [item for item in required_items if item["status"] == "ready"]
    return {
        "domain": "credit_risk",
        "label": FINANCIAL_DOMAINS["credit_risk"],
        "totalRequired": len(required_items),
        "readyRequired": len(ready_required),
        "coverageScore": round(len(ready_required) / max(1, len(required_items)) * 100),
        "items": checklist,
        "missingRequired": [item["technique"] for item in required_items if item["status"] == "missing"],
        "context": context or {},
    }
