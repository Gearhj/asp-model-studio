from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.metrics import accuracy_score, average_precision_score, balanced_accuracy_score, brier_score_loss, confusion_matrix, f1_score, log_loss, precision_recall_curve, precision_score, recall_score, roc_auc_score, roc_curve

from ..errors import InsufficientDataError, MissingProbabilityError
from ..interpretation import classification_findings
from ..result_builder import chart, result, table


def _arrays(frame: pd.DataFrame, target: str, score: str, threshold: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    work = pd.DataFrame({"y": pd.to_numeric(frame[target], errors="coerce"), "score": pd.to_numeric(frame[score], errors="coerce")}).dropna()
    if len(work) < 5: raise InsufficientDataError("Classification diagnostics require at least five non-missing target and probability observations.")
    classes = sorted(work.y.unique())
    if len(classes) != 2: raise InsufficientDataError("Classification diagnostics require a binary target with two observed classes.")
    y = (work.y == classes[-1]).astype(int).to_numpy(); probabilities = work.score.clip(0, 1).to_numpy(); prediction = (probabilities >= threshold).astype(int)
    return y, probabilities, prediction


def _ks(y: np.ndarray, score: np.ndarray) -> tuple[float, float]:
    fpr, tpr, thresholds = roc_curve(y, score)
    index = int(np.argmax(np.abs(tpr - fpr)))
    return float(abs(tpr[index] - fpr[index])), float(thresholds[index])


def compute_classification_diagnostics(frame: pd.DataFrame, context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    target, score = parameters.get("target_column"), parameters.get("score_column") or parameters.get("probability_column")
    if not score: raise MissingProbabilityError("ROC and precision-recall diagnostics require predicted probabilities.")
    threshold = float(parameters.get("threshold", .5)); y, probabilities, prediction = _arrays(frame, target, score, threshold)
    tn, fp, fn, tp = confusion_matrix(y, prediction, labels=[0, 1]).ravel()
    specificity = tn / max(tn + fp, 1); fpr_value = fp / max(fp + tn, 1); fnr = fn / max(fn + tp, 1)
    ks, ks_threshold = _ks(y, probabilities)
    metrics = {"observation_count": int(len(y)), "accuracy": accuracy_score(y, prediction), "balanced_accuracy": balanced_accuracy_score(y, prediction), "precision": precision_score(y, prediction, zero_division=0), "recall": recall_score(y, prediction, zero_division=0), "specificity": specificity, "f1": f1_score(y, prediction, zero_division=0), "false_positive_rate": fpr_value, "false_negative_rate": fnr, "positive_predictive_value": precision_score(y, prediction, zero_division=0), "negative_predictive_value": tn / max(tn + fn, 1), "roc_auc": roc_auc_score(y, probabilities), "pr_auc": average_precision_score(y, probabilities), "log_loss": log_loss(y, probabilities, labels=[0, 1]), "brier_score": brier_score_loss(y, probabilities), "ks_statistic": ks, "gini": 2 * roc_auc_score(y, probabilities) - 1, "prevalence": float(y.mean()), "predicted_positive_rate": float(prediction.mean()), "threshold": threshold}
    fpr, tpr, roc_thresholds = roc_curve(y, probabilities); precision, recall, pr_thresholds = precision_recall_curve(y, probabilities)
    calibration_y, calibration_p = calibration_curve(y, probabilities, n_bins=min(10, max(2, len(y) // 5)), strategy="quantile")
    decile = pd.DataFrame({"target": y, "score": probabilities}); decile["decile"] = pd.qcut(decile.score.rank(method="first"), min(10, len(decile)), labels=False, duplicates="drop") + 1
    decile_rows = []
    for decile_number, group in decile.groupby("decile", observed=True):
        event_rate = float(group.target.mean()); decile_rows.append({"decile": int(decile_number), "count": int(len(group)), "events": int(group.target.sum()), "event_rate": event_rate, "mean_score": float(group.score.mean()), "lift": event_rate / max(metrics["prevalence"], 1e-12)})
    threshold_rows = []
    for candidate in np.linspace(.05, .95, 19):
        candidate_prediction = (probabilities >= candidate).astype(int)
        threshold_rows.append({"threshold": float(candidate), "precision": precision_score(y, candidate_prediction, zero_division=0), "recall": recall_score(y, candidate_prediction, zero_division=0), "f1": f1_score(y, candidate_prediction, zero_division=0), "predicted_positive_rate": float(candidate_prediction.mean())})
    charts = [chart("roc", "roc", "ROC curve", [{"false_positive_rate": float(a), "true_positive_rate": float(b), "threshold": float(c)} for a,b,c in zip(fpr,tpr,roc_thresholds)], x_field="false_positive_rate", x_label="False positive rate", y_fields=[{"field":"true_positive_rate","label":"True positive rate"}], reference_lines=[{"x": 0, "y": 0, "x2": 1, "y2": 1, "label":"No-skill reference"}]), chart("precision_recall", "precision-recall", "Precision-recall curve", [{"recall":float(a),"precision":float(b)} for a,b in zip(recall,precision)], x_field="recall", x_label="Recall", y_fields=[{"field":"precision","label":"Precision"}]), chart("calibration", "calibration", "Calibration curve", [{"mean_predicted_probability":float(a),"fraction_of_positives":float(b)} for a,b in zip(calibration_p,calibration_y)], x_field="mean_predicted_probability", x_label="Predicted probability", y_fields=[{"field":"fraction_of_positives","label":"Observed event rate"}])]
    tables = [table("confusion_matrix", "Confusion matrix", [{"actual":"Negative","predicted_negative":int(tn),"predicted_positive":int(fp)}, {"actual":"Positive","predicted_negative":int(fn),"predicted_positive":int(tp)}]), table("threshold_performance", "Threshold performance", threshold_rows), table("decile_analysis", "Decile analysis", decile_rows), table("calibration_bins", "Calibration bins", [{"mean_predicted_probability":float(a),"observed_event_rate":float(b)} for a,b in zip(calibration_p,calibration_y)])]
    return result("classification_diagnostics", context, parameters, statistics=metrics, tables=tables, charts=charts, interpretations=classification_findings(metrics), diagnostics=[{"name":"ks_optimal_threshold","value":ks_threshold}])
