from __future__ import annotations

from typing import Any, Dict, List


def finding(title: str, text: str, *, severity: str = "info", statistic: Dict[str, Any] | None = None, implication: str | None = None, action: str | None = None) -> Dict[str, Any]:
    return {"type": "deterministic_rule", "title": title, "finding": text, "severity": severity, "supporting_statistic": statistic or {}, "implication": implication, "recommended_action": action}


def distribution_findings(statistics: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if abs(float(statistics.get("skewness") or 0)) > 1:
        findings.append(finding("Skewed distribution", "The selected variable is materially skewed.", severity="warning", statistic={"skewness": statistics.get("skewness")}, action="Review transformation or robust treatment options."))
    if float(statistics.get("missing_percent") or 0) > 10:
        findings.append(finding("Missingness requires review", "More than 10% of values are missing.", severity="warning", statistic={"missing_percent": statistics.get("missing_percent")}, action="Review data collection and treatment policy."))
    return findings


def classification_findings(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    prevalence = float(metrics.get("prevalence") or 0)
    if prevalence < 0.05 or prevalence > 0.95:
        findings.append(finding("Class imbalance", "The target prevalence is highly imbalanced; accuracy alone can be misleading.", severity="warning", statistic={"prevalence": prevalence}, action="Review PR AUC, recall, calibration, and threshold tradeoffs."))
    if metrics.get("brier_score") is not None and float(metrics["brier_score"]) > 0.20:
        findings.append(finding("Calibration review", "The Brier score indicates probability calibration should be reviewed.", severity="warning", statistic={"brier_score": metrics["brier_score"]}, action="Review calibration bins before operational use."))
    return findings
