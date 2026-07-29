from typing import Any, Dict, List, Tuple
from datetime import datetime
import hashlib
import json
import re

import numpy as np
import pandas as pd

from ..core.dataset_store import DATASTORE
from ..core.result_store import RESULTS

try:
    from scipy import stats as scipy_stats
except Exception:  # pragma: no cover
    scipy_stats = None

try:
    from sklearn.metrics import (
        accuracy_score,
        average_precision_score,
        brier_score_loss,
        confusion_matrix,
        f1_score,
        mean_absolute_error,
        mean_squared_error,
        r2_score,
        precision_recall_curve,
        precision_score,
        recall_score,
        roc_auc_score,
        roc_curve,
    )
    from sklearn.inspection import permutation_importance
    from sklearn.base import clone
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.decomposition import PCA
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.neighbors import NearestNeighbors
    from sklearn.preprocessing import LabelEncoder
except Exception:  # pragma: no cover
    accuracy_score = None
    average_precision_score = None
    brier_score_loss = None
    confusion_matrix = None
    f1_score = None
    mean_absolute_error = None
    mean_squared_error = None
    r2_score = None
    precision_score = None
    recall_score = None
    precision_recall_curve = None
    roc_auc_score = None
    roc_curve = None
    permutation_importance = None
    clone = None
    CalibratedClassifierCV = None
    LinearRegression = None
    LogisticRegression = None
    PCA = None
    KMeans = None
    silhouette_score = None
    NearestNeighbors = None
    LabelEncoder = None


def _normalized_feature_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _target_aliases() -> set[str]:
    aliases = {
        _normalized_feature_name(DATASTORE.target),
        "bad_flag",
        "riskperformance",
    }
    source = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta, dict) else {}
    if isinstance(source, dict):
        for key in ("target", "targetColumn", "originalTargetLabelColumn", "originalTargetLabel", "labelColumn"):
            aliases.add(_normalized_feature_name(source.get(key)))
    return {alias for alias in aliases if alias}


def _is_target_derived_feature(feature: Any) -> bool:
    name = _normalized_feature_name(str(feature).replace("num__", "").replace("cat__", ""))
    return any(name == alias or name.startswith(f"{alias}_") for alias in _target_aliases())


def _filter_target_derived_rows(rows: List[Dict[str, Any]], feature_key: str = "feature") -> List[Dict[str, Any]]:
    return [row for row in rows if not _is_target_derived_feature(row.get(feature_key, ""))]


class EvaluationService:
    @staticmethod
    def _active_model_binding(expected: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Return the governed workspace identity that a model may be bound to.

        The active DATASTORE state is authoritative for data, feature, and split
        identity. The last training summary contributes the immutable training
        run identity, but is never used to paper over a missing active manifest
        or split after an upstream change invalidates them.
        """
        expected = expected or {}
        summary = RESULTS.get_last_summary() or {}
        manifest = DATASTORE.meta.get("feature_manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        split_record = DATASTORE.meta.get("split_record")
        split_record = split_record if isinstance(split_record, dict) else {}
        validation_design = split_record.get("validation_design")
        if not isinstance(validation_design, dict):
            validation_design = DATASTORE.meta.get("validation_design")
        validation_design = validation_design if isinstance(validation_design, dict) else {}
        source = DATASTORE.meta.get("source")
        source = source if isinstance(source, dict) else {}
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        split_materialized = all(value is not None for value in (X_train, X_test, y_train, y_test))

        project_id = str(expected.get("project_id") or "").strip()
        if not project_id:
            try:
                from ..core.modeling_scope import active_project_id

                project_id = str(active_project_id() or "").strip()
            except Exception:
                project_id = ""
        if not project_id:
            # Direct service tests do not establish the HTTP ContextVar. The
            # summary is still an immutable training-produced binding there.
            project_id = str(summary.get("project_id") or "").strip()

        return {
            "project_id": project_id,
            "dataset_id": str(
                DATASTORE.meta.get("dataset_id")
                or source.get("datasetId")
                or source.get("dataset_id")
                or summary.get("dataset_id")
                or ""
            ).strip(),
            "dataset_version": str(
                DATASTORE.meta.get("dataset_version")
                or DATASTORE.meta.get("version_id")
                or manifest.get("dataset_version")
                or ""
            ).strip(),
            "target": str(DATASTORE.target or "").strip(),
            "problem_type": str(expected.get("problem_type") or summary.get("problem_type") or "").strip(),
            "feature_manifest_version": str(
                manifest.get("manifest_version")
                or manifest.get("feature_manifest_version")
                or ""
            ).strip(),
            "split_id": str(split_record.get("split_id") or "").strip() if split_materialized else "",
            "split_materialized": split_materialized,
            "validation_design_id": str(
                validation_design.get("validation_design_id")
                or validation_design.get("design_id")
                or ""
            ).strip(),
            "validation_design_version": str(
                validation_design.get("design_version")
                or validation_design.get("validation_design_version")
                or ""
            ).strip(),
            "training_job_id": str(
                summary.get("training_job_id")
                or summary.get("training_run_id")
                or ""
            ).strip(),
        }

    def _final_model_context_mismatch(
        self,
        metadata: Dict[str, Any] | None,
        expected: Dict[str, Any] | None = None,
    ) -> str:
        """Fail closed when a final artifact is detached from active lineage."""
        metadata = metadata or {}
        binding = self._active_model_binding(expected)

        active_requirements = [
            ("project_id", "project"),
            ("dataset_version", "dataset version"),
            ("target", "target"),
            ("feature_manifest_version", "feature manifest"),
            ("split_id", "governed split"),
        ]
        for key, label in active_requirements:
            if not str(binding.get(key) or "").strip():
                return (
                    f"The active workspace has no current {label} binding. "
                    "Reconfirm preparation, recreate the governed split, and retrain before using a final model."
                )

        artifact_requirements = [
            ("project_id", "project"),
            ("dataset_version", "dataset version"),
            ("target", "target"),
            ("problem_type", "problem type"),
            ("feature_manifest_version", "feature manifest"),
            ("split_id", "governed split"),
        ]
        for key, label in artifact_requirements:
            actual = str(metadata.get(key) or "").strip()
            current = str(binding.get(key) or "").strip()
            if not actual:
                return (
                    f"The final model is missing its {label} binding. "
                    "Retrain and save a new final model before scoring or export."
                )
            if current and actual != current:
                return (
                    f"The final model is stale because its {label} does not match the active workspace. "
                    "Retrain and save a new final model."
                )

        training_job_id = str(
            metadata.get("training_job_id")
            or metadata.get("training_run_id")
            or ""
        ).strip()
        if not training_job_id:
            return (
                "The final model is missing its training job binding. "
                "Retrain and save a new final model before scoring or export."
            )

        for key, label in (
            ("validation_design_id", "validation design"),
            ("validation_design_version", "validation design version"),
        ):
            current = str(binding.get(key) or "").strip()
            actual = str(metadata.get(key) or "").strip()
            if current and not actual:
                return (
                    f"The final model is missing its {label} binding. "
                    "Retrain under the approved validation design."
                )
            if current and actual != current:
                return (
                    f"The final model is stale because its {label} does not match the active workspace. "
                    "Retrain under the current validation design."
                )
        return ""

    def _promotion_context_mismatch(
        self,
        model_name: str,
        expected: Dict[str, Any] | None = None,
    ) -> str:
        """Validate the selected fitted artifact before promoting it to final."""
        binding = self._active_model_binding(expected)
        metadata = RESULTS.get_model_artifact_metadata(model_name) or {}
        summary = RESULTS.get_last_summary() or {}

        # The active workspace binding is authoritative. Empty or stale
        # request snapshots must never override current dataset/target identity.
        basic_mismatch = self._artifact_context_mismatch(model_name, {**(expected or {}), **binding})
        if basic_mismatch:
            return basic_mismatch
        if not binding.get("split_materialized") or not binding.get("split_id"):
            return "The governed split is no longer current. Recreate the split and retrain before saving a final model."

        checks = [
            ("feature_manifest_version", "feature manifest"),
            ("split_id", "governed split"),
        ]
        for key, label in checks:
            current = str(binding.get(key) or "").strip()
            actual = str(metadata.get(key) or "").strip()
            if not current:
                return f"The active workspace has no current {label}. Reconfirm preparation and retrain."
            if not actual:
                return f"The selected model artifact is missing its {label} binding. Please retrain this model."
            if actual != current:
                return f"The selected model artifact does not match the current {label}. Please retrain this model."

        artifact_run = str(metadata.get("training_run_id") or metadata.get("training_job_id") or "").strip()
        summary_run = str(summary.get("training_job_id") or summary.get("training_run_id") or "").strip()
        if not artifact_run:
            return "The selected model artifact is missing its training job binding. Please retrain this model."
        if not summary_run or artifact_run != summary_run:
            return "The selected model artifact is not part of the active training result. Please retrain this model."

        for key, label in (
            ("validation_design_id", "validation design"),
            ("validation_design_version", "validation design version"),
        ):
            current = str(binding.get(key) or "").strip()
            actual = str(metadata.get(key) or "").strip()
            if current and not actual:
                return f"The selected model artifact is missing its {label} binding. Please retrain this model."
            if current and actual != current:
                return f"The selected model artifact does not match the current {label}. Please retrain this model."
        return ""

    def _final_binding_metadata(
        self,
        model_name: str,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        binding = self._active_model_binding(context)
        artifact_metadata = RESULTS.get_model_artifact_metadata(model_name) or {}
        summary = RESULTS.get_last_summary() or {}
        return {
            "project_id": binding.get("project_id"),
            "dataset_id": binding.get("dataset_id") or artifact_metadata.get("dataset_id"),
            "dataset_version": binding.get("dataset_version"),
            "target": binding.get("target"),
            "problem_type": binding.get("problem_type"),
            "feature_manifest_version": binding.get("feature_manifest_version"),
            "split_id": binding.get("split_id"),
            "validation_design_id": binding.get("validation_design_id") or None,
            "validation_design_version": binding.get("validation_design_version") or None,
            "training_job_id": (
                artifact_metadata.get("training_job_id")
                or artifact_metadata.get("training_run_id")
                or summary.get("training_job_id")
                or summary.get("training_run_id")
            ),
            "training_run_id": (
                artifact_metadata.get("training_run_id")
                or artifact_metadata.get("training_job_id")
                or summary.get("training_job_id")
                or summary.get("training_run_id")
            ),
        }

    def _artifact_context_mismatch(self, model_name: str, expected: Dict[str, Any] | None = None) -> str:
        expected = expected or {}
        metadata = RESULTS.get_model_artifact_metadata(model_name)
        if not metadata:
            if any(expected.get(key) for key in ("project_id", "dataset_version", "target", "problem_type")):
                return "The selected model artifact is not scoped to the current project. Please retrain this model for this project."
            return ""

        checks = [
            ("project_id", "project"),
            ("dataset_version", "dataset version"),
            ("target", "target"),
            ("problem_type", "problem type"),
        ]
        for key, label in checks:
            expected_value = str(expected.get(key) or "").strip()
            actual_value = str(metadata.get(key) or "").strip()
            if expected_value and actual_value and expected_value != actual_value:
                return f"The selected model artifact does not match the current {label}. Please retrain {model_name} for this project."
            if expected_value and not actual_value:
                return f"The selected model artifact is missing {label} metadata. Please retrain {model_name} for this project."
        if metadata.get("model_key") and str(metadata.get("model_key")) != str(model_name):
            return f"The selected model artifact returned key {metadata.get('model_key')}, not {model_name}. Please retrain this model."
        return ""

    def _artifact_debug(self, model_name: str, expected: Dict[str, Any] | None = None) -> Dict[str, Any]:
        expected = expected or {}
        metadata = RESULTS.get_model_artifact_metadata(model_name)
        summary = RESULTS.get_last_summary() or {}
        result = self._model_result(model_name) or {}
        return {
            "selected_model_key": model_name,
            "requested_project_id": expected.get("project_id") or "",
            "requested_dataset_version": expected.get("dataset_version") or "",
            "requested_target": expected.get("target") or "",
            "requested_problem_type": expected.get("problem_type") or "",
            "returned_model_key": metadata.get("model_key") or model_name,
            "returned_project_id": metadata.get("project_id") or summary.get("project_id") or "",
            "returned_dataset_version": metadata.get("dataset_version") or summary.get("dataset_version") or "",
            "returned_target": metadata.get("target") or summary.get("target") or "",
            "returned_problem_type": metadata.get("problem_type") or result.get("task") or summary.get("problem_type") or "",
            "training_run_id": metadata.get("training_run_id") or summary.get("training_run_id") or "",
            "artifact_has_metadata": bool(metadata),
        }

    def _model_result(self, model_name: str) -> Dict[str, Any] | None:
        summary = RESULTS.get_last_summary() or {}
        raw = summary.get("raw") or {}
        return raw.get(model_name)

    def get_curves(self, model_name: str) -> Dict[str, Any]:
        result = self._model_result(model_name)
        if not result:
            return {"ok": False, "error": "No fitted results found for this model."}

        metrics = result.get("metrics") or {}
        task = result.get("task") or (RESULTS.get_last_summary() or {}).get("problem_type")
        y_true = np.asarray(result.get("y_true") or [], dtype=float)
        y_score = np.asarray(result.get("y_score") or [], dtype=float)

        if task == "regression":
            response: Dict[str, Any] = {
                "ok": True,
                "task": "regression",
                "metrics": {
                    "mae": metrics.get("mae"),
                    "mse": metrics.get("mse"),
                    "rmse": metrics.get("rmse"),
                    "r2": metrics.get("r2"),
                    "adjusted_r2": metrics.get("adjusted_r2"),
                },
            }
            if len(y_true) and len(y_score):
                residuals = y_true - y_score
                abs_residuals = np.abs(residuals)
                response["residuals"] = {
                    "points": [
                        {
                            "actual": float(actual),
                            "predicted": float(predicted),
                            "residual": float(residual),
                        }
                        for actual, predicted, residual in zip(y_true[:1200], y_score[:1200], residuals[:1200])
                    ],
                    "summary": {
                        "mean_residual": float(np.mean(residuals)),
                        "median_residual": float(np.median(residuals)),
                        "std_residual": float(np.std(residuals)),
                        "mean_abs_residual": float(np.mean(abs_residuals)),
                        "p95_abs_residual": float(np.percentile(abs_residuals, 95)),
                    },
                }
                bins = np.histogram(residuals, bins=min(24, max(8, int(np.sqrt(len(residuals))))))
                response["residual_histogram"] = {
                    "counts": bins[0].astype(int).tolist(),
                    "edges": bins[1].astype(float).tolist(),
                }
            return response

        response: Dict[str, Any] = {
            "ok": True,
            "task": "classification",
            "metrics": {
                "precision": metrics.get("precision"),
                "recall": metrics.get("recall"),
                "f1": metrics.get("f1"),
                "auc": metrics.get("auc"),
                "pr_auc": metrics.get("pr_auc"),
            },
            "confusion": metrics.get("confusion_matrix"),
        }

        if len(y_true) and len(y_score) and roc_curve is not None:
            fpr, tpr, _ = roc_curve(y_true, y_score)
            response["roc"] = {"fpr": fpr.tolist(), "tpr": tpr.tolist()}

        if len(y_true) and len(y_score) and precision_recall_curve is not None:
            precision, recall, _ = precision_recall_curve(y_true, y_score)
            response["pr"] = {
                "precision": precision.tolist(),
                "recall": recall.tolist(),
            }

        return response

    def get_deciles(self, model_name: str) -> Dict[str, Any]:
        result = self._model_result(model_name)
        if not result:
            return {"ok": False, "deciles": [], "error": "No fitted results found for this model."}

        y_true = np.asarray(result.get("y_true") or [], dtype=float)
        y_score = np.asarray(result.get("y_score") or [], dtype=float)
        if not len(y_true) or not len(y_score):
            return {"ok": True, "deciles": []}

        order = np.argsort(-y_score)
        y_sorted = y_true[order]
        base_rate = float(np.mean(y_sorted)) if len(y_sorted) else 0.0

        rows: List[Dict[str, Any]] = []
        for idx, bucket in enumerate(np.array_split(y_sorted, 10), start=1):
            if not len(bucket):
                continue
            event_rate = float(np.mean(bucket))
            rows.append(
                {
                    "decile": idx,
                    "n": int(len(bucket)),
                    "positives": int(np.sum(bucket)),
                    "event_rate": event_rate,
                    "lift": float(event_rate / base_rate) if base_rate > 0 else 0.0,
                }
            )

        return {"ok": True, "deciles": rows}

    def get_evaluation_command_center(
        self,
        model_name: str,
        threshold: float = 0.5,
        review_capacity: float = 0.1,
    ) -> Dict[str, Any]:
        """Build classifier diagnostics only from the fitted holdout artifact."""
        result = self._model_result(model_name)
        if not result:
            return {"ok": False, "error": "No fitted results found for this model."}
        if str(result.get("task") or "classification") != "classification":
            return {"ok": False, "error": "Threshold diagnostics apply only to supervised classification models."}

        y_true = np.asarray(result.get("y_true") or [], dtype=float)
        y_score = np.asarray(result.get("y_score") or [], dtype=float)
        if not len(y_true) or not len(y_score) or len(y_true) != len(y_score):
            return {"ok": False, "error": "Persisted holdout labels and scores are unavailable for this model."}

        y_true = (y_true > 0.5).astype(int)
        y_score = np.clip(y_score.astype(float), 0.0, 1.0)
        active_threshold = float(np.clip(threshold, 0.0, 1.0))
        capacity = float(np.clip(review_capacity, 0.001, 1.0))

        def threshold_row(value: float) -> Dict[str, Any]:
            predicted = (y_score >= value).astype(int)
            tn = int(np.sum((y_true == 0) & (predicted == 0)))
            fp = int(np.sum((y_true == 0) & (predicted == 1)))
            fn = int(np.sum((y_true == 1) & (predicted == 0)))
            tp = int(np.sum((y_true == 1) & (predicted == 1)))
            predicted_positives = tp + fp
            positives = tp + fn
            precision = float(tp / predicted_positives) if predicted_positives else 0.0
            recall = float(tp / positives) if positives else 0.0
            fpr = float(fp / (fp + tn)) if fp + tn else 0.0
            f1 = float(2 * precision * recall / (precision + recall)) if precision + recall else 0.0
            alert_rate = float(predicted_positives / len(y_true)) if len(y_true) else 0.0
            return {
                "threshold": float(value),
                "predicted_positives": predicted_positives,
                "review_volume": predicted_positives,
                "precision": precision,
                "recall": recall,
                "false_positives": fp,
                "false_negatives": fn,
                "true_positives": tp,
                "true_negatives": tn,
                "fraud_capture": recall,
                "false_positive_rate": fpr,
                "f1": f1,
                "expected_alert_rate": alert_rate,
                "confusion": [[tn, fp], [fn, tp]],
            }

        unique_scores = np.unique(y_score)
        if len(unique_scores) > 201:
            candidate_thresholds = np.quantile(unique_scores, np.linspace(0.0, 1.0, 201))
        else:
            candidate_thresholds = unique_scores
        candidates = [threshold_row(float(value)) for value in candidate_thresholds]
        max_f1 = max(candidates, key=lambda row: row["f1"])
        recall_candidates = [row for row in candidates if row["recall"] >= 0.8]
        precision_candidates = [row for row in candidates if row["precision"] >= 0.8]
        target_recall = max(recall_candidates, key=lambda row: (row["precision"], row["threshold"])) if recall_candidates else max(candidates, key=lambda row: row["recall"])
        target_precision = max(precision_candidates, key=lambda row: (row["recall"], -row["threshold"])) if precision_candidates else max(candidates, key=lambda row: row["precision"])
        capacity_threshold = float(np.quantile(y_score, max(0.0, 1.0 - capacity)))

        order = np.argsort(-y_score)
        sorted_true = y_true[order]
        sorted_score = y_score[order]
        positives = int(np.sum(sorted_true))
        base_rate = float(np.mean(sorted_true)) if len(sorted_true) else 0.0
        deciles: List[Dict[str, Any]] = []
        cumulative_positives = 0
        for index, positions in enumerate(np.array_split(np.arange(len(sorted_true)), 10), start=1):
            if not len(positions):
                continue
            bucket = sorted_true[positions]
            bucket_scores = sorted_score[positions]
            bucket_positives = int(np.sum(bucket))
            cumulative_positives += bucket_positives
            event_rate = float(np.mean(bucket))
            deciles.append({
                "decile": index,
                "n": int(len(bucket)),
                "positives": bucket_positives,
                "event_rate": event_rate,
                "lift": float(event_rate / base_rate) if base_rate else 0.0,
                "cumulative_positives": cumulative_positives,
                "capture_rate": float(cumulative_positives / positives) if positives else 0.0,
                "population_rate": float(np.max(positions) + 1) / len(sorted_true),
                "min_score": float(np.min(bucket_scores)),
                "max_score": float(np.max(bucket_scores)),
                "mean_score": float(np.mean(bucket_scores)),
            })

        top_capture: Dict[str, Dict[str, Any]] = {}
        for pct in (0.01, 0.03, 0.05, 0.10):
            count = max(1, int(np.ceil(len(sorted_true) * pct)))
            top_events = int(np.sum(sorted_true[:count]))
            top_rate = float(np.mean(sorted_true[:count])) if count else 0.0
            top_capture[f"{int(pct * 100)}%"] = {
                "rows": count,
                "events": top_events,
                "capture_rate": float(top_events / positives) if positives else 0.0,
                "lift": float(top_rate / base_rate) if base_rate else 0.0,
            }

        calibration_rows: List[Dict[str, Any]] = []
        for bucket in np.array_split(np.argsort(y_score), 10):
            if not len(bucket):
                continue
            calibration_rows.append({
                "predicted": float(np.mean(y_score[bucket])),
                "observed": float(np.mean(y_true[bucket])),
                "n": int(len(bucket)),
            })
        if len(calibration_rows) >= 2:
            predicted_means = np.asarray([row["predicted"] for row in calibration_rows], dtype=float)
            observed_means = np.asarray([row["observed"] for row in calibration_rows], dtype=float)
            slope, intercept = np.polyfit(predicted_means, observed_means, 1)
            calibration_slope = float(slope)
            calibration_intercept = float(intercept)
        else:
            calibration_slope = None
            calibration_intercept = None

        metrics = result.get("metrics") or {}
        ranked = (RESULTS.get_last_summary() or {}).get("ranked") or []
        ranked_row = next((row for row in ranked if row.get("key") == model_name), {})
        return {
            "ok": True,
            "model": model_name,
            "evaluation_role": "TEST",
            "test_status": "Available - governed holdout",
            "oot_status": "Not loaded",
            "observation_count": int(len(y_true)),
            "event_count": positives,
            "event_rate": base_rate,
            "threshold": threshold_row(active_threshold),
            "presets": {
                "maximize_f1": float(max_f1["threshold"]),
                "target_recall": float(target_recall["threshold"]),
                "target_precision": float(target_precision["threshold"]),
                "review_capacity": capacity_threshold,
                "current_governed": 0.5,
            },
            "lift": {
                "base_rate": base_rate,
                "deciles": deciles,
                "top_capture": top_capture,
            },
            "calibration": {
                "rows": calibration_rows,
                "brier_score": float(np.mean((y_score - y_true) ** 2)),
                "slope": calibration_slope,
                "intercept": calibration_intercept,
                "method": ranked_row.get("calibration_method") or ("Applied" if ranked_row.get("calibration_applied") else "Not applied"),
                "prevalence_correction": "Not applied during Evaluation",
            },
            "stability": {
                "internal_validation_status": "Available" if ranked_row.get("best_score") is not None else "Not recorded",
                "internal_validation_score": ranked_row.get("best_score"),
                "test_metrics": {
                    "roc_auc": metrics.get("auc"),
                    "pr_auc": metrics.get("pr_auc"),
                    "precision": metrics.get("precision"),
                    "recall": metrics.get("recall"),
                    "f1": metrics.get("f1"),
                },
                "oot_metrics": None,
            },
        }

    def _artifact(self, model_name: str, expected: Dict[str, Any] | None = None):
        mismatch = self._artifact_context_mismatch(model_name, expected)
        if mismatch:
            return None
        return RESULTS.get_model_artifact(model_name)

    def _test_data(self):
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if X_test is None or y_test is None:
            raise ValueError("No evaluation split is available. Train models first.")
        return X_train, X_test, y_train, y_test

    def _prepare_final_feature_frame(self, model: Dict[str, Any], X: pd.DataFrame) -> Tuple[pd.DataFrame, List[str], List[str]]:
        features = [str(feature) for feature in model["features"]]
        if model.get("dummy_columns"):
            encoded = pd.get_dummies(X.copy(), dummy_na=True)
            dummy_columns = [str(feature) for feature in model.get("dummy_columns", [])]
            prepared = encoded.reindex(columns=dummy_columns, fill_value=0)
            matched = [feature for feature in features if feature in prepared.columns]
            missing = [feature for feature in features if feature not in encoded.columns and "__" not in feature]
            for feature in features:
                if feature not in prepared.columns:
                    prepared[feature] = np.nan
            prepared = prepared[features].apply(pd.to_numeric, errors="coerce")
            prepared = prepared.fillna(model["medians"])
            prepared = (prepared - model["means"]) / model["stds"]
            return prepared[features], matched, missing
        normalized_columns = {str(col).strip().lower(): col for col in X.columns}
        prepared = pd.DataFrame(index=X.index)
        matched: List[str] = []
        missing: List[str] = []
        for feature in features:
            source_col = feature if feature in X.columns else normalized_columns.get(feature.strip().lower())
            if source_col is None:
                prepared[feature] = np.nan
                missing.append(feature)
            else:
                prepared[feature] = X[source_col]
                matched.append(feature)
            prepared[feature] = pd.to_numeric(prepared[feature], errors="coerce")
        prepared = prepared.fillna(model["medians"])
        prepared = (prepared - model["means"]) / model["stds"]
        return prepared[features], matched, missing

    def _predict_score(self, model: Any, X: pd.DataFrame) -> np.ndarray:
        if isinstance(model, dict) and model.get("kind") in {"rfe_logistic", "rfe_classifier"}:
            prepared, _, _ = self._prepare_final_feature_frame(model, X)
            return np.asarray(model["model"].predict_proba(prepared)[:, 1], dtype=float)
        if isinstance(model, dict) and model.get("kind") in {"rfe_regression", "rfe_regressor"}:
            prepared, _, _ = self._prepare_final_feature_frame(model, X)
            return np.asarray(model["model"].predict(prepared), dtype=float)
        if hasattr(model, "predict_proba"):
            return np.asarray(model.predict_proba(X)[:, 1], dtype=float)
        if hasattr(model, "decision_function"):
            raw = np.asarray(model.decision_function(X), dtype=float)
            return (raw - np.min(raw)) / (np.max(raw) - np.min(raw) + 1e-9)
        return np.asarray(model.predict(X), dtype=float)

    def _predict_label(self, model: Any, X: pd.DataFrame) -> np.ndarray:
        scores = self._predict_score(model, X)
        return (scores >= 0.5).astype(int)

    def feature_importance(self, model_name: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, y_test = self._test_data()
        if X_test is None or X_test.empty:
            return {"ok": False, "error": "No governed holdout data is available for feature importance."}

        sample = X_test.sample(n=5_000, random_state=42) if len(X_test) > 5_000 else X_test
        y_series = pd.Series(np.asarray(y_test), index=X_test.index)
        y_sample = y_series.loc[sample.index]
        estimator = getattr(model, "named_steps", {}).get("model") if hasattr(model, "named_steps") else model
        preprocess = model.named_steps.get("preprocess") if hasattr(model, "named_steps") else None
        transformed_names = (
            list(preprocess.get_feature_names_out())
            if preprocess is not None and hasattr(preprocess, "get_feature_names_out")
            else list(X_test.columns)
        )
        raw_columns = [str(column) for column in X_test.columns]

        def original_feature(name: Any) -> str:
            cleaned = str(name).replace("num__", "").replace("cat__", "")
            if cleaned in raw_columns:
                return cleaned
            matches = [column for column in raw_columns if cleaned.startswith(f"{column}_")]
            return max(matches, key=len) if matches else cleaned

        def aggregate(values: Any, source: str) -> List[Dict[str, Any]]:
            grouped: Dict[str, Dict[str, Any]] = {}
            for name, value in zip(transformed_names, np.asarray(values).ravel()):
                feature = original_feature(name)
                row = grouped.setdefault(feature, {"feature": feature, "importance": 0.0, "direction": 0.0, "source": source})
                row["importance"] += abs(float(value))
                row["direction"] += float(value)
            return list(grouped.values())

        rows: List[Dict[str, Any]] = []
        method = "unavailable"
        coefficients = getattr(estimator, "coef_", None)
        native = getattr(estimator, "feature_importances_", None)
        if coefficients is not None:
            coef = np.asarray(coefficients, dtype=float)
            if coef.ndim > 1:
                coef = np.mean(coef, axis=0)
            rows = aggregate(coef, "coefficient magnitude")
            method = "coefficient magnitude"
        elif native is not None:
            rows = aggregate(native, "native feature importance")
            method = "native feature importance"
        elif permutation_importance is not None:
            scoring = "neg_root_mean_squared_error" if self._is_regression_problem() else "roc_auc"
            result = permutation_importance(
                model,
                sample,
                y_sample,
                n_repeats=3,
                random_state=42,
                n_jobs=1,
                scoring=scoring,
            )
            rows = [
                {
                    "feature": str(feature),
                    "importance": abs(float(value)),
                    "direction": float(value),
                    "source": "holdout permutation importance",
                }
                for feature, value in zip(sample.columns, result.importances_mean)
            ]
            method = "holdout permutation importance"

        rows = _filter_target_derived_rows(rows)
        rows.sort(key=lambda row: row["importance"], reverse=True)
        return {"ok": True, "rows": rows[:30], "method": method, "sample_count": int(len(sample))}

    def hyperparameters(self, model_name: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        result = self._model_result(model_name) or {}
        summary = RESULTS.get_last_summary() or {}
        ranked = summary.get("ranked") or []
        row = next((item for item in ranked if item.get("key") == model_name), {})
        params = result.get("best_params") or row.get("best_params") or {}
        score = result.get("best_score") or row.get("best_score")
        if not params:
            model = self._artifact(model_name, context)
            estimator = getattr(model, "named_steps", {}).get("model") if hasattr(model, "named_steps") else model
            if estimator is not None and hasattr(estimator, "get_params"):
                raw_params = estimator.get_params(deep=False)
                params = {
                    key: value
                    for key, value in raw_params.items()
                    if isinstance(value, (str, int, float, bool, type(None), tuple))
                }
        rows = [{"parameter": str(key), "value": str(value)} for key, value in sorted(params.items())]
        return {"ok": True, "best_score": score, "rows": rows}

    def model_details(self, model_name: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        estimator = getattr(model, "named_steps", {}).get("model") if hasattr(model, "named_steps") else model
        preprocess = model.named_steps.get("preprocess") if hasattr(model, "named_steps") else None
        names = (
            preprocess.get_feature_names_out()
            if preprocess is not None and hasattr(preprocess, "get_feature_names_out")
            else []
        )

        if hasattr(estimator, "coef_"):
            coef = np.asarray(estimator.coef_).ravel()
            intercept = float(np.asarray(getattr(estimator, "intercept_", [0])).ravel()[0])
            is_classifier = hasattr(estimator, "classes_")
            inference = None if is_classifier else self._linear_regression_inference(model, estimator, names)
            inference_by_feature = {
                str(row.get("feature")): row
                for row in (inference or {}).get("coefficient_rows", [])
            }
            rows = [
                {
                    "feature": str(name).replace("num__", "").replace("cat__", ""),
                    "coefficient": float(value),
                    "standardized_coefficient": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("standardized_coefficient"),
                    "standardized_weight": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("standardized_weight"),
                    "standard_error": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("standard_error"),
                    "t_statistic": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("t_statistic"),
                    "p_value": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("p_value"),
                    "ci_lower": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("ci_lower"),
                    "ci_upper": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("ci_upper"),
                    "confidence_interval_lower": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("confidence_interval_lower"),
                    "confidence_interval_upper": inference_by_feature.get(str(name).replace("num__", "").replace("cat__", ""), {}).get("confidence_interval_upper"),
                    "odds_ratio": float(np.exp(value)) if is_classifier else None,
                }
                for name, value in zip(names, coef)
            ]
            rows = _filter_target_derived_rows(rows)
            rows.sort(key=lambda row: abs(row["coefficient"]), reverse=True)
            for rank, row in enumerate(rows, start=1):
                row["absolute_rank"] = rank
            return {
                "ok": True,
                "kind": "equation",
                "model_type": "classification" if is_classifier else "regression",
                "debug": self._artifact_debug(model_name, context),
                "intercept": intercept,
                "coefficients": rows[:40],
                "inference_available": bool((inference or {}).get("ok")),
                "inference_message": (inference or {}).get("message"),
                "model_fit": (inference or {}).get("model_fit"),
            }

        if estimator.__class__.__name__.lower().startswith("decisiontree"):
            try:
                from sklearn.tree import export_text

                tree_text = export_text(estimator, feature_names=[str(n) for n in names], max_depth=4)
            except Exception as exc:
                tree_text = f"Unable to export tree text: {exc}"
            return {"ok": True, "kind": "tree", "tree_text": tree_text}

        return {"ok": True, "kind": "generic", "message": f"{estimator.__class__.__name__} uses model-agnostic interpretation panels below."}

    def _linear_regression_inference(self, model: Any, estimator: Any, names: Any) -> Dict[str, Any]:
        try:
            X_train, _, y_train, _ = self._test_data()
            if X_train is None or y_train is None:
                return {"ok": False, "message": "Statistical inference unavailable because training data is unavailable."}
            preprocess = model.named_steps.get("preprocess") if hasattr(model, "named_steps") else None
            if preprocess is None or not hasattr(preprocess, "transform"):
                return {"ok": False, "message": "Statistical inference unavailable because the fitted preprocessing design matrix is unavailable."}
            matrix = preprocess.transform(X_train)
            if hasattr(matrix, "toarray"):
                matrix = matrix.toarray()
            X = np.asarray(matrix, dtype=float)
            y = np.asarray(y_train, dtype=float).ravel()
            if X.ndim != 2 or len(y) != X.shape[0]:
                return {"ok": False, "message": "Statistical inference unavailable because the transformed design matrix does not align to the target vector."}
            n_obs, n_predictors = X.shape
            residual_df = int(n_obs - n_predictors - 1)
            if residual_df <= 0 or n_obs < 3:
                return {"ok": False, "message": "Statistical inference unavailable because residual degrees of freedom are invalid."}

            X_design = np.column_stack([np.ones(n_obs), X])
            rank = int(np.linalg.matrix_rank(X_design))
            if rank < X_design.shape[1]:
                return {"ok": False, "message": "Statistical inference unavailable because the transformed design matrix is singular."}

            coef = np.asarray(estimator.coef_, dtype=float).ravel()
            intercept = float(np.asarray(getattr(estimator, "intercept_", [0])).ravel()[0])
            params = np.concatenate([[intercept], coef])
            y_hat = X_design @ params
            residuals = y - y_hat
            rss = float(np.sum(residuals ** 2))
            mse = rss / residual_df
            xtx_inv = np.linalg.inv(X_design.T @ X_design)
            covariance = mse * xtx_inv
            std_errors = np.sqrt(np.maximum(np.diag(covariance), 0))
            t_stats = np.divide(params, std_errors, out=np.full_like(params, np.nan, dtype=float), where=std_errors > 0)

            if scipy_stats is None:
                p_values = np.full_like(t_stats, np.nan, dtype=float)
                critical = np.nan
                message = "Statistical inference unavailable because SciPy is unavailable."
            else:
                p_values = 2 * scipy_stats.t.sf(np.abs(t_stats), residual_df)
                critical = float(scipy_stats.t.ppf(0.975, residual_df))
                message = "OLS inference computed from the transformed design matrix used by the fitted pipeline."

            y_std = float(np.std(y, ddof=1)) or 1.0
            x_stds = np.std(X, axis=0, ddof=1)
            feature_names = [str(name).replace("num__", "").replace("cat__", "") for name in names]
            coefficient_rows = []
            for idx, (feature, coefficient) in enumerate(zip(feature_names, coef), start=1):
                se = float(std_errors[idx])
                ci_delta = float(critical * se) if np.isfinite(critical) else np.nan
                coefficient_rows.append(
                    {
                        "feature": feature,
                        "variable": feature,
                        "coefficient": float(coefficient),
                        "standardized_coefficient": float(coefficient * (x_stds[idx - 1] / y_std)) if np.isfinite(x_stds[idx - 1]) else None,
                        "standardized_weight": float(coefficient * (x_stds[idx - 1] / y_std)) if np.isfinite(x_stds[idx - 1]) else None,
                        "standard_error": se if np.isfinite(se) else None,
                        "t_statistic": float(t_stats[idx]) if np.isfinite(t_stats[idx]) else None,
                        "p_value": float(p_values[idx]) if np.isfinite(p_values[idx]) else None,
                        "ci_lower": float(coefficient - ci_delta) if np.isfinite(ci_delta) else None,
                        "ci_upper": float(coefficient + ci_delta) if np.isfinite(ci_delta) else None,
                        "confidence_interval_lower": float(coefficient - ci_delta) if np.isfinite(ci_delta) else None,
                        "confidence_interval_upper": float(coefficient + ci_delta) if np.isfinite(ci_delta) else None,
                    }
                )

            y_mean = float(np.mean(y))
            tss = float(np.sum((y - y_mean) ** 2))
            r2 = float(1 - rss / tss) if tss > 0 else 0.0
            adjusted_r2 = float(1 - (1 - r2) * ((n_obs - 1) / residual_df)) if residual_df > 0 else 0.0
            ess = max(tss - rss, 0.0)
            f_statistic = None
            prob_f_statistic = None
            if n_predictors > 0 and residual_df > 0 and rss > 0:
                f_statistic = float((ess / n_predictors) / (rss / residual_df))
                if scipy_stats is not None and np.isfinite(f_statistic):
                    prob_f_statistic = float(scipy_stats.f.sf(f_statistic, n_predictors, residual_df))
            sigma2_mle = max(rss / n_obs, np.finfo(float).eps)
            log_likelihood = float(-0.5 * n_obs * (np.log(2 * np.pi * sigma2_mle) + 1))
            parameter_count = int(n_predictors + 1)
            aic = float(2 * parameter_count - 2 * log_likelihood)
            bic = float(np.log(n_obs) * parameter_count - 2 * log_likelihood)
            try:
                condition_number = float(np.linalg.cond(X_design))
            except Exception:
                condition_number = None
            return {
                "ok": scipy_stats is not None,
                "message": message,
                "coefficient_rows": coefficient_rows,
                "model_fit": {
                    "dependent_variable": str(getattr(y_train, "name", "Target") or "Target"),
                    "model_type": "Linear Regression",
                    "r2": r2,
                    "adjusted_r2": adjusted_r2,
                    "rmse": float(np.sqrt(np.mean(residuals ** 2))),
                    "mae": float(np.mean(np.abs(residuals))),
                    "mse": float(np.mean(residuals ** 2)),
                    "n_observations": int(n_obs),
                    "n_predictors": int(n_predictors),
                    "residual_df": residual_df,
                    "residual_standard_error": float(np.sqrt(mse)),
                    "f_statistic": f_statistic,
                    "prob_f_statistic": prob_f_statistic,
                    "aic": aic,
                    "bic": bic,
                    "log_likelihood": log_likelihood,
                    "condition_number": condition_number,
                },
            }
        except Exception:
            return {"ok": False, "message": "Statistical inference unavailable because the fitted pipeline could not be evaluated for OLS inference."}

    def decision_tree(self, model_name: str, max_depth: int = 4, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        estimator = getattr(model, "named_steps", {}).get("model") if hasattr(model, "named_steps") else model
        preprocess = model.named_steps.get("preprocess") if hasattr(model, "named_steps") else None
        names = (
            preprocess.get_feature_names_out()
            if preprocess is not None and hasattr(preprocess, "get_feature_names_out")
            else []
        )
        if not estimator.__class__.__name__.lower().startswith("decisiontree"):
            return {"ok": False, "error": "The selected model is not a decision tree."}
        tree = getattr(estimator, "tree_", None)
        if tree is None:
            return {"ok": False, "error": "Decision tree structure is unavailable."}

        feature_names = [str(name).replace("num__", "").replace("cat__", "") for name in names]
        classes = [str(item) for item in getattr(estimator, "classes_", [])]
        is_classifier = bool(classes)
        max_depth = max(1, min(int(max_depth or 4), 5))
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []

        def walk(node_id: int, depth: int, x_min: float, x_max: float) -> None:
            left = int(tree.children_left[node_id])
            right = int(tree.children_right[node_id])
            samples = int(tree.n_node_samples[node_id])
            values = np.asarray(tree.value[node_id]).ravel()
            total = float(values.sum()) or 1.0
            positive_rate = float(values[-1] / total) if is_classifier and len(values) else 0.0
            prediction_value = float(values[0]) if len(values) else 0.0
            predicted_index = int(np.argmax(values)) if is_classifier and len(values) else 0
            feature_index = int(tree.feature[node_id])
            feature = feature_names[feature_index] if 0 <= feature_index < len(feature_names) else ""
            threshold = float(tree.threshold[node_id]) if feature else None
            is_leaf = left == -1 or right == -1 or depth >= max_depth
            x = (x_min + x_max) / 2
            nodes.append(
                {
                    "id": int(node_id),
                    "depth": int(depth),
                    "x": float(x),
                    "leaf": bool(is_leaf),
                    "feature": feature,
                    "threshold": threshold,
                    "samples": samples,
                    "positive_rate": positive_rate,
                    "prediction": classes[predicted_index] if is_classifier and predicted_index < len(classes) else f"{prediction_value:.4f}",
                    "prediction_value": prediction_value,
                    "model_type": "classification" if is_classifier else "regression",
                }
            )
            if is_leaf:
                return
            mid = (x_min + x_max) / 2
            edges.extend(
                [
                    {"source": int(node_id), "target": left, "label": "Yes"},
                    {"source": int(node_id), "target": right, "label": "No"},
                ]
            )
            walk(left, depth + 1, x_min, mid)
            walk(right, depth + 1, mid, x_max)

        walk(0, 0, 0.0, 1.0)
        return {"ok": True, "nodes": nodes, "edges": edges, "max_depth": max_depth, "model_type": "classification" if is_classifier else "regression"}

    def knn_clusters(self, model_name: str, max_points: int = 900) -> Dict[str, Any]:
        try:
            model = self._artifact(model_name)
            if model is None:
                return {"ok": False, "error": "No fitted model artifact found."}
            estimator = getattr(model, "named_steps", {}).get("model") if hasattr(model, "named_steps") else model
            if "kneighbors" not in estimator.__class__.__name__.lower() and not hasattr(estimator, "kneighbors"):
                return {"ok": False, "error": "The selected model is not a KNN model."}
            _, X_test, _, y_test = self._test_data()
            if X_test is None or X_test.empty:
                return {"ok": False, "error": "No holdout data is available for KNN visualization."}
            if PCA is None or NearestNeighbors is None:
                return {"ok": False, "error": "PCA is unavailable for KNN visualization."}

            sample = X_test.copy()
            y_full = pd.Series(y_test, index=X_test.index)
            if len(sample) > max_points:
                sample = sample.sample(n=max_points, random_state=42)
            y_sample = y_full.loc[sample.index].reset_index(drop=True)
            sample = sample.reset_index(drop=True)

            preprocess = model.named_steps.get("preprocess") if hasattr(model, "named_steps") else None
            if preprocess is not None and hasattr(preprocess, "transform"):
                matrix = preprocess.transform(sample)
                if hasattr(matrix, "toarray"):
                    matrix = matrix.toarray()
                matrix = np.asarray(matrix, dtype=float)
            else:
                numeric_cols = [col for col in sample.columns if pd.api.types.is_numeric_dtype(sample[col])]
                if len(numeric_cols) < 2:
                    return {"ok": False, "error": "KNN cluster view requires at least two numeric features."}
                numeric = sample[numeric_cols].apply(pd.to_numeric, errors="coerce")
                numeric = numeric.fillna(numeric.median(numeric_only=True))
                matrix = ((numeric - numeric.mean()) / numeric.std().replace(0, 1).fillna(1)).to_numpy()

            if matrix.shape[1] < 2:
                return {"ok": False, "error": "KNN cluster view requires at least two transformed features."}
            pca = PCA(n_components=2)
            coords = pca.fit_transform(matrix)
            model_neighbors = int(getattr(estimator, "n_neighbors", 5) or 5)
            display_neighbors = max(2, min(5, model_neighbors))
            nn = NearestNeighbors(n_neighbors=min(display_neighbors + 1, len(matrix)))
            nn.fit(matrix)
            distances, neighbor_indices = nn.kneighbors(matrix)
            scores = self._predict_score(model, sample)
            predictions = (scores >= 0.5).astype(int)
            try:
                _, y_arr = self._encode_binary_target(y_sample, y_sample)
            except Exception:
                y_arr = np.zeros(len(sample), dtype=int)

            x_vals = coords[:, 0]
            y_vals = coords[:, 1]
            x_min, x_max = float(np.quantile(x_vals, 0.01)), float(np.quantile(x_vals, 0.99))
            y_min, y_max = float(np.quantile(y_vals, 0.01)), float(np.quantile(y_vals, 0.99))
            if x_min == x_max:
                x_min -= 1
                x_max += 1
            if y_min == y_max:
                y_min -= 1
                y_max += 1
            x_pad = (x_max - x_min) * 0.08
            y_pad = (y_max - y_min) * 0.08
            x_min -= x_pad
            x_max += x_pad
            y_min -= y_pad
            y_max += y_pad

            grid_resolution = 82
            xs = np.linspace(x_min, x_max, grid_resolution)
            ys = np.linspace(y_min, y_max, grid_resolution)
            xx, yy = np.meshgrid(xs, ys)
            pca_grid = np.column_stack([xx.ravel(), yy.ravel()])
            feature_grid = pca.inverse_transform(pca_grid)
            if hasattr(estimator, "predict_proba"):
                grid_scores = np.asarray(estimator.predict_proba(feature_grid)[:, -1], dtype=float)
            elif hasattr(estimator, "decision_function"):
                raw = np.asarray(estimator.decision_function(feature_grid), dtype=float)
                grid_scores = (raw - np.min(raw)) / (np.max(raw) - np.min(raw) + 1e-9)
            else:
                grid_scores = np.asarray(estimator.predict(feature_grid), dtype=float)
            grid_predictions = (grid_scores >= 0.5).astype(int)
            region_labels = np.zeros(len(pca_grid), dtype=int)
            cluster_count = 1
            cluster_method = "nearest-neighbor"
            cluster_diagnostics: List[Dict[str, Any]] = []
            if KMeans is not None and silhouette_score is not None and len(coords) >= 30:
                best_score = -1.0
                best_model = None
                max_clusters = min(8, max(2, len(coords) // 25))
                try:
                    one_cluster = KMeans(n_clusters=1, n_init=10, random_state=42)
                    one_cluster.fit(coords)
                    cluster_diagnostics.append(
                        {"k": 1, "inertia": float(one_cluster.inertia_), "silhouette": None}
                    )
                except Exception:
                    pass
                for candidate_k in range(2, max_clusters + 1):
                    try:
                        candidate = KMeans(n_clusters=candidate_k, n_init=10, random_state=42)
                        labels = candidate.fit_predict(coords)
                        if len(set(labels)) < 2:
                            continue
                        score = float(silhouette_score(coords, labels))
                        cluster_diagnostics.append(
                            {"k": int(candidate_k), "inertia": float(candidate.inertia_), "silhouette": score}
                        )
                        if score > best_score:
                            best_score = score
                            best_model = candidate
                    except Exception:
                        continue
                if best_model is not None:
                    region_labels = best_model.predict(pca_grid)
                    cluster_count = int(best_model.n_clusters)
                    cluster_method = "silhouette-kmeans-on-pca"
            if cluster_count <= 1:
                nearest_grid = NearestNeighbors(n_neighbors=1)
                nearest_grid.fit(coords)
                nearest_indices = nearest_grid.kneighbors(pca_grid, return_distance=False).ravel()
                region_labels = np.asarray(nearest_indices % 8, dtype=int)
                cluster_count = int(min(8, len(coords)))
            grid_rows = [
                {
                    "x": float(pca_grid[index, 0]),
                    "y": float(pca_grid[index, 1]),
                    "score": float(grid_scores[index]),
                    "prediction": int(grid_predictions[index]),
                    "region": int(region_labels[index]),
                }
                for index in range(len(pca_grid))
            ]
            points = [
                {
                    "id": int(index),
                    "x": float(x),
                    "y": float(y),
                    "class": int(y_arr[index]) if index < len(y_arr) else 0,
                    "prediction": int(predictions[index]) if index < len(predictions) else 0,
                    "score": float(scores[index]) if index < len(scores) else 0.0,
                }
                for index, (x, y) in enumerate(coords)
            ]
            edges: List[Dict[str, Any]] = []
            seen_edges = set()
            max_edges = 1600
            for source, neighbors in enumerate(neighbor_indices):
                for neighbor in neighbors[1:]:
                    a, b = sorted((int(source), int(neighbor)))
                    if a == b or (a, b) in seen_edges:
                        continue
                    seen_edges.add((a, b))
                    edges.append(
                        {
                            "source": int(source),
                            "target": int(neighbor),
                            "same_prediction": bool(predictions[source] == predictions[neighbor]),
                            "same_class": bool(y_arr[source] == y_arr[neighbor]) if source < len(y_arr) and neighbor < len(y_arr) else False,
                            "distance": float(distances[source][list(neighbors).index(neighbor)]),
                        }
                    )
                    if len(edges) >= max_edges:
                        break
                if len(edges) >= max_edges:
                    break
            return {
                "ok": True,
                "points": points,
                "grid": grid_rows,
                "neighbor_edges": edges,
                "x_domain": [x_min, x_max],
                "y_domain": [y_min, y_max],
                "neighbor_count": model_neighbors,
                "display_neighbors": display_neighbors,
                "grid_resolution": grid_resolution,
                "cluster_count": cluster_count,
                "cluster_method": cluster_method,
                "cluster_diagnostics": cluster_diagnostics,
                "sample_size": int(len(points)),
            }
        except Exception as exc:
            return {"ok": False, "error": f"KNN cluster visualization failed: {exc}"}

    def pdp(self, model_name: str, feature: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, _ = self._test_data()
        if feature not in X_test.columns:
            return {"ok": False, "error": f"Feature '{feature}' was not found."}

        x = X_test.sample(n=2_500, random_state=42).copy() if len(X_test) > 2_500 else X_test.copy()
        s = x[feature]
        if pd.api.types.is_numeric_dtype(s):
            grid = np.quantile(pd.to_numeric(s, errors="coerce").dropna(), np.linspace(0.05, 0.95, 20))
        else:
            grid = s.astype(str).value_counts().head(12).index.to_numpy()

        rows = []
        for value in grid:
            x_mod = x.copy()
            x_mod[feature] = value
            rows.append(
                {
                    "value": float(value) if pd.api.types.is_numeric_dtype(s) else str(value),
                    "label": f"{float(value):,.4g}" if pd.api.types.is_numeric_dtype(s) else str(value),
                    "prediction": float(np.mean(self._predict_score(model, x_mod))),
                }
            )
        return {
            "ok": True,
            "feature": feature,
            "kind": "numeric" if pd.api.types.is_numeric_dtype(s) else "categorical",
            "sample_count": int(len(x)),
            "rows": rows,
        }

    def sensitivity(self, model_name: str, feature: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, _ = self._test_data()
        if feature not in X_test.columns:
            return {"ok": False, "error": f"Feature '{feature}' was not found."}
        sample = X_test.sample(n=2_500, random_state=42).copy() if len(X_test) > 2_500 else X_test.copy()
        baseline = float(np.mean(self._predict_score(model, sample)))
        rows = []
        if pd.api.types.is_numeric_dtype(sample[feature]):
            for pct in [-0.2, -0.1, 0.0, 0.1, 0.2]:
                x_mod = sample.copy()
                x_mod[feature] = pd.to_numeric(x_mod[feature], errors="coerce") * (1 + pct)
                pred = float(np.mean(self._predict_score(model, x_mod)))
                rows.append({"scenario": f"{pct:+.0%}", "prediction": pred, "delta": pred - baseline})
        else:
            for value in sample[feature].astype(str).value_counts().head(8).index:
                x_mod = sample.copy()
                x_mod[feature] = value
                pred = float(np.mean(self._predict_score(model, x_mod)))
                rows.append({"scenario": str(value), "prediction": pred, "delta": pred - baseline})
        return {"ok": True, "baseline": baseline, "sample_count": int(len(sample)), "rows": rows}

    def sensitivity_summary(self, model_name: str, top_n: int = 12) -> Dict[str, Any]:
        excluded_sensitivity_features = {"riskperformance", "bad_flag", "atlas_split"}
        if model_name in ("final", "final_rfe"):
            model = RESULTS.get_final_model()
            final_metadata = RESULTS.get_final_model_metadata() or {}
            final_features = [
                str(feature)
                for feature in (final_metadata.get("features") or [])
                if str(feature).lower() not in excluded_sensitivity_features
            ]
        else:
            model = self._artifact(model_name)
            final_features = []
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, _ = self._test_data()
        if X_test is None or X_test.empty:
            return {"ok": False, "error": "No holdout data is available."}

        baseline = float(np.mean(self._predict_score(model, X_test)))
        if final_features:
            ordered = [feature for feature in final_features if feature in X_test.columns]
        else:
            importance = self.feature_importance(model_name).get("rows", [])
            ordered = [str(row.get("feature", "")).replace("num__", "").replace("cat__", "") for row in importance]
            ordered += [str(col) for col in X_test.columns if str(col) not in ordered]

        rows: List[Dict[str, Any]] = []
        for feature in ordered:
            if feature not in X_test.columns:
                continue
            if str(feature).lower() in excluded_sensitivity_features:
                continue
            series = X_test[feature]
            scenarios: List[Dict[str, Any]] = []
            special_value_note = ""
            if pd.api.types.is_numeric_dtype(series):
                numeric = pd.to_numeric(series, errors="coerce")
                if numeric.dropna().empty:
                    continue
                special_mask = numeric.isin([-7, -8, -9])
                if bool(special_mask.any()):
                    special_value_note = (
                        "Sensitivity analysis excludes special bureau values from percentage perturbation. "
                        "Special values require separate bin-level or reason-code review."
                    )
                for pct in [-0.2, 0.2]:
                    x_mod = X_test.copy()
                    x_mod[feature] = numeric.where(special_mask, numeric * (1 + pct))
                    pred = float(np.mean(self._predict_score(model, x_mod)))
                    scenarios.append({"scenario": f"{pct:+.0%}", "prediction": pred, "delta": pred - baseline})
            else:
                for value in series.astype(str).value_counts().head(3).index:
                    x_mod = X_test.copy()
                    x_mod[feature] = value
                    pred = float(np.mean(self._predict_score(model, x_mod)))
                    scenarios.append({"scenario": str(value), "prediction": pred, "delta": pred - baseline})
            if not scenarios:
                continue
            max_row = max(scenarios, key=lambda row: abs(float(row["delta"])))
            negative_row = next((row for row in scenarios if row["scenario"] == "-20%"), None)
            positive_row = next((row for row in scenarios if row["scenario"] == "+20%"), None)
            positive_delta = float(positive_row["delta"]) if positive_row else float(max_row["delta"])
            if positive_delta > 0:
                direction = "increases_bad_risk"
                direction_explanation = "Increasing this feature increases predicted bad risk."
            elif positive_delta < 0:
                direction = "decreases_bad_risk"
                direction_explanation = "Increasing this feature decreases predicted bad risk."
            else:
                direction = "neutral"
                direction_explanation = "Increasing this feature has no material direction in the selected sensitivity scenarios."
            largest_direction = (
                "Largest impact occurs when this feature is decreased."
                if max_row["scenario"] == "-20%"
                else "Largest impact occurs when this feature is increased."
                if max_row["scenario"] == "+20%"
                else f"Largest impact occurs at scenario {max_row['scenario']}."
            )
            rows.append(
                {
                    "feature": feature,
                    "baseline": baseline,
                    "baseline_prediction": baseline,
                    "negative_scenario_prediction": negative_row["prediction"] if negative_row else None,
                    "positive_scenario_prediction": positive_row["prediction"] if positive_row else None,
                    "max_abs_delta": abs(float(max_row["delta"])),
                    "worst_scenario": max_row["scenario"],
                    "worst_prediction": max_row["prediction"],
                    "worst_delta": max_row["delta"],
                    "largest_scenario": max_row["scenario"],
                    "delta": max_row["delta"],
                    "direction": direction,
                    "direction_explanation": f"{direction_explanation} {largest_direction}",
                    "special_value_note": special_value_note,
                    "scenarios": scenarios,
                }
            )
            if len(rows) >= max(1, min(int(top_n or 12), 30)):
                break

        rows.sort(key=lambda row: row["max_abs_delta"], reverse=True)
        return {"ok": True, "baseline": baseline, "rows": rows}

    def vif_summary(self, model_name: str = "final") -> Dict[str, Any]:
        if LinearRegression is None:
            return {"ok": False, "error": "scikit-learn LinearRegression is unavailable."}
        X_train, _, _, _ = DATASTORE.get_splits()
        if X_train is None or X_train.empty:
            return {"ok": False, "error": "No training split is available."}

        metadata = RESULTS.get_final_model_metadata() or {}
        features = [str(feature) for feature in (metadata.get("features") or []) if str(feature) in X_train.columns]
        if model_name not in ("final", "final_rfe") or not features:
            return {"ok": False, "error": "Save a final RFE model before running VIF."}

        numeric_features = []
        work = pd.DataFrame(index=X_train.index)
        for feature in features:
            series = pd.to_numeric(X_train[feature], errors="coerce")
            if series.notna().sum() >= 2:
                work[feature] = series
                numeric_features.append(feature)
        if len(numeric_features) < 2:
            return {"ok": True, "rows": [], "message": "VIF requires at least two numeric final-model variables."}

        if len(work) > 10000:
            work = work.sample(n=10000, random_state=42)
        work = work.fillna(work.median(numeric_only=True))

        rows: List[Dict[str, Any]] = []
        for feature in numeric_features:
            other_features = [col for col in numeric_features if col != feature]
            y = work[feature].to_numpy(dtype=float)
            x = work[other_features].to_numpy(dtype=float)
            if x.shape[1] == 0 or float(np.std(y)) == 0:
                r2 = 0.0
            else:
                reg = LinearRegression()
                reg.fit(x, y)
                r2 = float(reg.score(x, y))
            tolerance = max(1.0 - r2, 1e-9)
            vif = float(1.0 / tolerance)
            if vif < 5:
                status = "pass"
            elif vif < 10:
                status = "warning"
            else:
                status = "fail"
            rows.append(
                {
                    "feature": feature,
                    "vif": vif,
                    "tolerance": tolerance,
                    "r_squared": r2,
                    "status": status,
                }
            )
        rows.sort(key=lambda row: row["vif"], reverse=True)
        return {
            "ok": True,
            "model": metadata,
            "features": numeric_features,
            "rows": rows,
        }

    def vsi_summary(self, model_name: str, top_n: int = 40) -> Dict[str, Any]:
        model = self._artifact(model_name)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        X_train, X_test, _, _ = DATASTORE.get_splits()
        if X_train is None or X_test is None:
            return {"ok": False, "error": "No train/holdout split is available."}

        final_metadata = RESULTS.get_final_model_metadata() or {}
        metadata_features = final_metadata.get("features") if model_name in ("final", "final_rfe") else []
        features = [
            str(feature)
            for feature in (metadata_features or [])
            if str(feature) in X_train.columns and str(feature) in X_test.columns
        ]
        if not features:
            importance = self.feature_importance(model_name).get("rows", [])
            features = [
                str(row.get("feature", "")).replace("num__", "").replace("cat__", "")
                for row in importance
                if str(row.get("feature", "")).replace("num__", "").replace("cat__", "") in X_train.columns
                and str(row.get("feature", "")).replace("num__", "").replace("cat__", "") in X_test.columns
            ]
        features += [str(col) for col in X_train.columns if str(col) in X_test.columns and str(col) not in features]

        rows: List[Dict[str, Any]] = []
        for feature in features:
            if pd.api.types.is_numeric_dtype(X_train[feature]):
                value = self._stability_index_numeric(X_train[feature], X_test[feature])
            else:
                value = self._stability_index_categorical(X_train[feature], X_test[feature])
            rows.append({"feature": feature, "value": value, "status": self._status(value)})
            if len(rows) >= max(1, min(int(top_n or 40), 100)):
                break
        rows.sort(key=lambda row: row["value"], reverse=True)
        return {"ok": True, "reference": "development_train", "comparison": "development_holdout", "rows": rows}

    def shap_summary(self, model_name: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, _ = self._test_data()
        if X_test.empty:
            return {"ok": True, "method": "Holdout replacement impact", "rows": []}

        sample = X_test
        if len(sample) > 1000:
            sample = sample.sample(n=1000, random_state=42)
        baseline = self._predict_score(model, sample)
        rows: List[Dict[str, Any]] = []
        for feature in sample.columns:
            x_mod = sample.copy()
            series = x_mod[feature]
            if pd.api.types.is_numeric_dtype(series):
                replacement = pd.to_numeric(series, errors="coerce").median()
            else:
                mode = series.astype(str).mode(dropna=True)
                replacement = mode.iloc[0] if len(mode) else ""
            x_mod[feature] = replacement
            perturbed = self._predict_score(model, x_mod)
            impact = float(np.mean(np.abs(baseline - perturbed)))
            signed = float(np.mean(baseline - perturbed))
            rows.append(
                {
                    "feature": str(feature),
                    "importance": impact,
                    "source": "replacement impact",
                    "signed_effect": signed,
                }
            )
        rows = _filter_target_derived_rows(rows)
        rows.sort(key=lambda row: abs(row["importance"]), reverse=True)
        return {
            "ok": True,
            "method": "Holdout replacement impact",
            "sample_count": int(len(sample)),
            "rows": rows[:30],
        }

    def _score_feature_subset(
        self,
        train: pd.DataFrame,
        test: pd.DataFrame,
        y_train: np.ndarray,
        y_test: np.ndarray,
        features: List[str],
    ) -> float:
        estimator = LogisticRegression(max_iter=3000, n_jobs=1, class_weight="balanced")
        estimator.fit(train[features], y_train)
        scores = estimator.predict_proba(test[features])[:, 1]
        return float(roc_auc_score(y_test, scores))

    def _score_regression_feature_subset(
        self,
        train: pd.DataFrame,
        test: pd.DataFrame,
        y_train: np.ndarray,
        y_test: np.ndarray,
        features: List[str],
    ) -> float:
        estimator = LinearRegression()
        estimator.fit(train[features], y_train)
        preds = estimator.predict(test[features])
        mse = float(mean_squared_error(y_test, preds)) if mean_squared_error is not None else float(np.mean((y_test - preds) ** 2))
        return float(np.sqrt(mse))

    def _prepare_rfe_design(self, X_train: pd.DataFrame, X_test: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
        train = X_train.copy()
        test = X_test.copy()
        combined = pd.concat([train, test], axis=0, ignore_index=True)
        encoded = pd.get_dummies(combined, dummy_na=True)
        encoded.columns = [str(col) for col in encoded.columns]
        encoded = encoded.apply(pd.to_numeric, errors="coerce")
        encoded = encoded.loc[:, encoded.notna().any(axis=0)]
        if encoded.empty:
            return pd.DataFrame(index=X_train.index), pd.DataFrame(index=X_test.index), []
        train_encoded = encoded.iloc[: len(train)].copy()
        test_encoded = encoded.iloc[len(train) :].copy()
        train_encoded.index = X_train.index
        test_encoded.index = X_test.index
        medians = train_encoded.median(numeric_only=True)
        train_encoded = train_encoded.fillna(medians)
        test_encoded = test_encoded.fillna(medians)
        variable_cols = [
            str(col)
            for col in train_encoded.columns
            if float(train_encoded[col].std(skipna=True) or 0.0) > 1e-12
        ]
        return train_encoded[variable_cols], test_encoded[variable_cols], variable_cols

    def _encode_binary_target(self, y_train: pd.Series, y_test: pd.Series):
        if LabelEncoder is None:
            raise ValueError("scikit-learn label encoding is unavailable.")
        encoder = LabelEncoder()
        encoder.fit(pd.concat([pd.Series(y_train), pd.Series(y_test)], ignore_index=True).astype(str))
        if len(encoder.classes_) != 2:
            raise ValueError("This analysis requires a binary target.")
        return encoder.transform(pd.Series(y_train).astype(str)), encoder.transform(pd.Series(y_test).astype(str))

    def _source_estimator_for_refit(self, model_name: str, task: str) -> Tuple[Any, Dict[str, Any]]:
        artifact = self._artifact(model_name)
        fallback = LogisticRegression(max_iter=3000, n_jobs=1, class_weight="balanced") if task == "classification" else LinearRegression()
        metadata: Dict[str, Any] = {
            "source_model": model_name,
            "feature_selection_method": "bounded backward elimination with a logistic surrogate" if task == "classification" else "bounded backward elimination with a linear surrogate",
            "source_estimator_class": "",
            "final_estimator_class": fallback.__class__.__name__,
            "calibration_preserved": False,
            "refit_fallback": False,
        }
        if artifact is None or clone is None:
            metadata["refit_fallback"] = True
            metadata["refit_fallback_reason"] = "The selected fitted estimator could not be cloned; ATLAS used the governed transparent fallback."
            return fallback, metadata

        candidate = artifact.get("model") if isinstance(artifact, dict) else artifact
        outer_calibrated = candidate.__class__.__name__ == "CalibratedClassifierCV"
        if outer_calibrated:
            base = getattr(candidate, "estimator", None) or getattr(candidate, "base_estimator", None)
            if base is not None:
                candidate = base
        if hasattr(candidate, "named_steps"):
            candidate = candidate.named_steps.get("model", candidate)

        metadata["source_estimator_class"] = candidate.__class__.__name__
        try:
            estimator = clone(candidate)
            if outer_calibrated and task == "classification" and CalibratedClassifierCV is not None:
                estimator = CalibratedClassifierCV(
                    estimator,
                    method=str(getattr(artifact, "method", "sigmoid") or "sigmoid"),
                    cv=3,
                )
                metadata["calibration_preserved"] = True
            metadata["final_estimator_class"] = estimator.__class__.__name__
            return estimator, metadata
        except Exception as exc:
            metadata["refit_fallback"] = True
            metadata["refit_fallback_reason"] = f"The selected estimator could not be cloned ({exc}); ATLAS used the governed transparent fallback."
            return fallback, metadata

    def _source_model_label(self, model_name: str) -> str:
        summary = RESULTS.get_last_summary() or {}
        row = next((item for item in (summary.get("ranked") or []) if item.get("key") == model_name), {})
        return str(row.get("name") or model_name or "Selected Estimator")

    def rfe(self, model_name: str = "", keep: int = 10, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context) if model_name else None
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if X_train is None or X_test is None or y_train is None or y_test is None:
            return {"ok": False, "error": "No training split is available. Train models first."}
        full_train_rows = int(len(X_train))
        full_test_rows = int(len(X_test))
        full_train_index = X_train.index
        full_test_index = X_test.index
        if len(X_train) > 15_000:
            X_train = X_train.sample(n=15_000, random_state=42)
            y_train = pd.Series(np.asarray(y_train), index=full_train_index).loc[X_train.index]
        if len(X_test) > 8_000:
            X_test = X_test.sample(n=8_000, random_state=42)
            y_test = pd.Series(np.asarray(y_test), index=full_test_index).loc[X_test.index]
        prepared_train_all, prepared_test_all, feature_cols = self._prepare_rfe_design(X_train, X_test)
        if len(feature_cols) < 2:
            return {"ok": False, "error": "RFE requires at least two usable features after encoding. Confirm feature selection and preprocessing."}
        if self._is_regression_problem():
            result = self._rfe_regression(
                model_name=model_name,
                keep=keep,
                numeric_cols=feature_cols,
                prepared_train=prepared_train_all,
                prepared_test=prepared_test_all,
                y_train=y_train,
                y_test=y_test,
            )
            result.update({"full_train_rows": full_train_rows, "full_test_rows": full_test_rows, "analysis_train_rows": int(len(X_train)), "analysis_test_rows": int(len(X_test))})
            return result
        if LogisticRegression is None or LabelEncoder is None or roc_auc_score is None:
            return {"ok": False, "error": "scikit-learn logistic regression metrics are unavailable."}

        numeric_cols = list(feature_cols)
        screened_feature_count = len(numeric_cols)
        if len(numeric_cols) > 14:
            single_feature_scores: List[Dict[str, Any]] = []
            for feature in numeric_cols:
                try:
                    y_train_tmp, y_test_tmp = self._encode_binary_target(y_train, y_test)
                    single_feature_scores.append(
                        {
                            "feature": feature,
                            "auc": self._score_feature_subset(prepared_train_all, prepared_test_all, y_train_tmp, y_test_tmp, [feature]),
                        }
                    )
                except Exception:
                    single_feature_scores.append({"feature": feature, "auc": 0.5})
            numeric_cols = [
                row["feature"]
                for row in sorted(single_feature_scores, key=lambda row: row["auc"], reverse=True)[:14]
            ]

        prepared_train = prepared_train_all[numeric_cols].copy()
        prepared_test = prepared_test_all[numeric_cols].copy()
        means = prepared_train.mean()
        stds = prepared_train.std().replace(0, 1).fillna(1)
        prepared_train = (prepared_train - means) / stds
        prepared_test = (prepared_test - means) / stds

        try:
            y_train_arr, y_test_arr = self._encode_binary_target(y_train, y_test)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        remaining = list(numeric_cols)
        elimination_path: List[Dict[str, Any]] = [
            {
                "feature_count": len(remaining),
                "auc": self._score_feature_subset(prepared_train, prepared_test, y_train_arr, y_test_arr, remaining),
                "removed_feature": None,
                "features": list(remaining),
            }
        ]
        removal_auc: Dict[str, float] = {}

        while len(remaining) > 1:
            candidates: List[Dict[str, Any]] = []
            for feature in remaining:
                subset = [col for col in remaining if col != feature]
                auc = self._score_feature_subset(prepared_train, prepared_test, y_train_arr, y_test_arr, subset)
                candidates.append({"feature": feature, "auc": auc, "subset": subset})
            best = max(candidates, key=lambda item: item["auc"])
            removed = str(best["feature"])
            removal_auc[removed] = float(best["auc"])
            remaining = list(best["subset"])
            elimination_path.append(
                {
                    "feature_count": len(remaining),
                    "auc": float(best["auc"]),
                    "removed_feature": removed,
                    "features": list(remaining),
                }
            )

        if remaining:
            removal_auc[remaining[0]] = float(elimination_path[-1]["auc"])

        ascending = sorted(elimination_path, key=lambda row: row["feature_count"])
        curve_rows: List[Dict[str, Any]] = []
        previous_display_auc = None
        best_seen = 0.0
        for row in ascending:
            actual_auc = float(row["auc"])
            best_seen = max(best_seen, actual_auc)
            marginal = None if previous_display_auc is None else float(best_seen - previous_display_auc)
            features = list(row["features"])
            added_feature = ""
            if curve_rows:
                previous_features = set(curve_rows[-1]["features"])
                added = [feature for feature in features if feature not in previous_features]
                added_feature = added[0] if added else ""
            elif features:
                added_feature = features[0]
            curve_rows.append(
                {
                    "feature_count": int(row["feature_count"]),
                    "auc": actual_auc,
                    "display_auc": float(best_seen),
                    "marginal_auc": marginal,
                    "added_feature": added_feature,
                    "removed_feature": row.get("removed_feature"),
                    "features": features,
                }
            )
            previous_display_auc = best_seen

        best_row = max(curve_rows, key=lambda row: row["auc"])
        best_auc = float(best_row["auc"])
        best_count = int(best_row["feature_count"])

        # Recommend the smallest model that is effectively tied with the best
        # observed holdout AUC. Do not stop at the first small marginal change:
        # RFE curves can dip early and then improve again after noisy features
        # are removed.
        auc_tolerance = 0.001
        recommended_count = min(
            int(row["feature_count"])
            for row in curve_rows
            if float(row["auc"]) >= best_auc - auc_tolerance
        )

        selected_curve = min(
            curve_rows,
            key=lambda row: abs(int(row["feature_count"]) - max(1, min(int(keep), len(numeric_cols)))),
        )
        selected_feature_set = set(selected_curve.get("features", []))
        final_order = [feature for feature in numeric_cols if feature in selected_feature_set]
        final_order += [feature for feature in numeric_cols if feature not in selected_feature_set]

        requested_keep = max(1, min(int(keep), len(final_order)))
        ranked_rows = [
            {
                "feature": feature,
                "importance": float(removal_auc.get(feature, 0.0)),
                "rank": index,
                "selected": index <= requested_keep,
            }
            for index, feature in enumerate(final_order, start=1)
        ]

        return {
            "ok": True,
            "task": "classification",
            "metric": "auc",
            "model": model_name,
            "recommended_count": recommended_count,
            "best_count": best_count,
            "best_auc": best_auc,
            "auc_tolerance": auc_tolerance,
            "selected_count": requested_keep,
            "screened_feature_count": screened_feature_count,
            "rfe_candidate_limit": 14,
            "full_train_rows": full_train_rows,
            "full_test_rows": full_test_rows,
            "analysis_train_rows": int(len(X_train)),
            "analysis_test_rows": int(len(X_test)),
            "rows": ranked_rows,
            "curve": curve_rows,
        }

    def _rfe_regression(
        self,
        model_name: str,
        keep: int,
        numeric_cols: List[str],
        prepared_train: pd.DataFrame | None = None,
        prepared_test: pd.DataFrame | None = None,
        y_train: pd.Series | None = None,
        y_test: pd.Series | None = None,
    ) -> Dict[str, Any]:
        X_train, X_test, stored_y_train, stored_y_test = DATASTORE.get_splits()
        y_train = y_train if y_train is not None else stored_y_train
        y_test = y_test if y_test is not None else stored_y_test
        if LinearRegression is None:
            return {"ok": False, "error": "scikit-learn LinearRegression is unavailable."}
        if prepared_train is None or prepared_test is None:
            prepared_train, prepared_test, numeric_cols = self._prepare_rfe_design(X_train, X_test)

        y_train_arr = pd.to_numeric(pd.Series(y_train), errors="coerce").to_numpy(dtype=float)
        y_test_arr = pd.to_numeric(pd.Series(y_test), errors="coerce").to_numpy(dtype=float)
        screened_feature_count = len(numeric_cols)
        if len(numeric_cols) > 16:
            single_feature_scores: List[Dict[str, Any]] = []
            for feature in numeric_cols:
                try:
                    single_feature_scores.append(
                        {
                            "feature": feature,
                            "rmse": self._score_regression_feature_subset(prepared_train, prepared_test, y_train_arr, y_test_arr, [feature]),
                        }
                    )
                except Exception:
                    single_feature_scores.append({"feature": feature, "rmse": float("inf")})
            numeric_cols = [
                row["feature"]
                for row in sorted(single_feature_scores, key=lambda row: row["rmse"])[:16]
            ]

        prepared_train = prepared_train[numeric_cols].copy()
        prepared_test = prepared_test[numeric_cols].copy()
        means = prepared_train.mean()
        stds = prepared_train.std().replace(0, 1).fillna(1)
        prepared_train = (prepared_train - means) / stds
        prepared_test = (prepared_test - means) / stds

        remaining = list(numeric_cols)
        elimination_path: List[Dict[str, Any]] = [
            {
                "feature_count": len(remaining),
                "rmse": self._score_regression_feature_subset(prepared_train, prepared_test, y_train_arr, y_test_arr, remaining),
                "removed_feature": None,
                "features": list(remaining),
            }
        ]
        removal_rmse: Dict[str, float] = {}

        while len(remaining) > 1:
            candidates: List[Dict[str, Any]] = []
            for feature in remaining:
                subset = [col for col in remaining if col != feature]
                rmse = self._score_regression_feature_subset(prepared_train, prepared_test, y_train_arr, y_test_arr, subset)
                candidates.append({"feature": feature, "rmse": rmse, "subset": subset})
            best = min(candidates, key=lambda item: item["rmse"])
            removed = str(best["feature"])
            removal_rmse[removed] = float(best["rmse"])
            remaining = list(best["subset"])
            elimination_path.append(
                {
                    "feature_count": len(remaining),
                    "rmse": float(best["rmse"]),
                    "removed_feature": removed,
                    "features": list(remaining),
                }
            )

        if remaining:
            removal_rmse[remaining[0]] = float(elimination_path[-1]["rmse"])

        ascending = sorted(elimination_path, key=lambda row: row["feature_count"])
        curve_rows: List[Dict[str, Any]] = []
        previous_display_rmse = None
        best_seen = float("inf")
        for row in ascending:
            actual_rmse = float(row["rmse"])
            best_seen = min(best_seen, actual_rmse)
            marginal = None if previous_display_rmse is None else float(previous_display_rmse - best_seen)
            features = list(row["features"])
            added_feature = ""
            if curve_rows:
                previous_features = set(curve_rows[-1]["features"])
                added = [feature for feature in features if feature not in previous_features]
                added_feature = added[0] if added else ""
            elif features:
                added_feature = features[0]
            curve_rows.append(
                {
                    "feature_count": int(row["feature_count"]),
                    "rmse": actual_rmse,
                    "display_rmse": float(best_seen),
                    "marginal_rmse": marginal,
                    "added_feature": added_feature,
                    "removed_feature": row.get("removed_feature"),
                    "features": features,
                }
            )
            previous_display_rmse = best_seen

        best_row = min(curve_rows, key=lambda row: row["rmse"])
        best_rmse = float(best_row["rmse"])
        best_count = int(best_row["feature_count"])
        rmse_tolerance = max(best_rmse * 0.005, 1e-6)
        recommended_count = min(
            int(row["feature_count"])
            for row in curve_rows
            if float(row["rmse"]) <= best_rmse + rmse_tolerance
        )

        final_order = []
        for step in curve_rows:
            added = step.get("added_feature")
            if added and added not in final_order:
                final_order.append(added)
        if len(final_order) != len(numeric_cols):
            final_order = final_order + [feature for feature in numeric_cols if feature not in final_order]

        requested_keep = max(1, min(int(keep), len(final_order)))
        ranked_rows = [
            {
                "feature": feature,
                "importance": float(removal_rmse.get(feature, best_rmse)),
                "rank": index,
                "selected": index <= requested_keep,
            }
            for index, feature in enumerate(final_order, start=1)
        ]

        return {
            "ok": True,
            "task": "regression",
            "metric": "rmse",
            "model": model_name,
            "recommended_count": recommended_count,
            "best_count": best_count,
            "best_rmse": best_rmse,
            "rmse_tolerance": rmse_tolerance,
            "selected_count": requested_keep,
            "screened_feature_count": screened_feature_count,
            "rfe_candidate_limit": 16,
            "rows": ranked_rows,
            "curve": curve_rows,
        }

    def save_rfe_model(self, model_name: str = "", keep: int = 10, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mismatch = self._promotion_context_mismatch(model_name, context) if model_name else None
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if X_train is None or X_test is None or y_train is None or y_test is None:
            return {"ok": False, "error": "No training split is available. Train models first."}
        if self._is_regression_problem():
            return self._save_rfe_regression_model(model_name=model_name, keep=keep, context=context)
        if LogisticRegression is None:
            return {"ok": False, "error": "scikit-learn LogisticRegression is unavailable."}

        rfe_result = self.rfe(model_name=model_name, keep=keep, context=context)
        if not rfe_result.get("ok"):
            return rfe_result
        selected_features = [
            row["feature"]
            for row in rfe_result.get("rows", [])
            if int(row.get("rank", 9999)) <= int(rfe_result.get("selected_count", keep))
        ]
        if not selected_features:
            return {"ok": False, "error": "RFE did not return any selected features."}

        try:
            y_train_arr, y_test_arr = self._encode_binary_target(y_train, y_test)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        train_all, test_all, dummy_columns = self._prepare_rfe_design(X_train, X_test)
        selected_features = [feature for feature in selected_features if feature in train_all.columns]
        if not selected_features:
            return {"ok": False, "error": "Selected RFE features are unavailable after encoding."}
        train = train_all[selected_features].copy()
        test = test_all[selected_features].copy()
        medians = train.median(numeric_only=True)
        train = train.fillna(medians)
        test = test.fillna(medians)
        means = train.mean()
        stds = train.std().replace(0, 1).fillna(1)
        train_scaled = (train - means) / stds
        test_scaled = (test - means) / stds

        final_estimator, refit_metadata = self._source_estimator_for_refit(model_name, "classification")
        final_estimator.fit(train_scaled[selected_features], y_train_arr)
        scores = self._predict_score(final_estimator, test_scaled[selected_features])
        auc = float(roc_auc_score(y_test_arr, scores)) if roc_auc_score is not None else None

        artifact = {
            "kind": "rfe_classifier",
            "model": final_estimator,
            "features": selected_features,
            "dummy_columns": dummy_columns,
            "medians": medians,
            "means": means,
            "stds": stds,
        }
        metadata = {
            "source_model": model_name,
            "model_key": "final_rfe",
            "name": f"Final RFE {self._source_model_label(model_name)}",
            **self._final_binding_metadata(model_name, context),
            "feature_count": len(selected_features),
            "features": selected_features,
            "holdout_auc": auc,
            **refit_metadata,
        }
        RESULTS.set_final_model(artifact, metadata)
        return {"ok": True, "metadata": metadata}

    def _save_rfe_regression_model(self, model_name: str = "", keep: int = 10, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if LinearRegression is None:
            return {"ok": False, "error": "scikit-learn LinearRegression is unavailable."}

        rfe_result = self.rfe(model_name=model_name, keep=keep, context=context)
        if not rfe_result.get("ok"):
            return rfe_result
        selected_features = [
            row["feature"]
            for row in rfe_result.get("rows", [])
            if int(row.get("rank", 9999)) <= int(rfe_result.get("selected_count", keep))
        ]
        if not selected_features:
            return {"ok": False, "error": "RFE did not return any selected features."}

        train_all, test_all, dummy_columns = self._prepare_rfe_design(X_train, X_test)
        selected_features = [feature for feature in selected_features if feature in train_all.columns]
        if not selected_features:
            return {"ok": False, "error": "Selected RFE features are unavailable after encoding."}
        train = train_all[selected_features].copy()
        test = test_all[selected_features].copy()
        medians = train.median(numeric_only=True)
        train = train.fillna(medians)
        test = test.fillna(medians)
        means = train.mean()
        stds = train.std().replace(0, 1).fillna(1)
        train_scaled = (train - means) / stds
        test_scaled = (test - means) / stds

        y_train_arr = pd.to_numeric(pd.Series(y_train), errors="coerce").to_numpy(dtype=float)
        y_test_arr = pd.to_numeric(pd.Series(y_test), errors="coerce").to_numpy(dtype=float)
        final_estimator, refit_metadata = self._source_estimator_for_refit(model_name, "regression")
        final_estimator.fit(train_scaled[selected_features], y_train_arr)
        preds = final_estimator.predict(test_scaled[selected_features])
        metrics = self._regression_metrics(pd.Series(y_test_arr), preds, n_features=len(selected_features))

        artifact = {
            "kind": "rfe_regressor",
            "model": final_estimator,
            "features": selected_features,
            "dummy_columns": dummy_columns,
            "medians": medians,
            "means": means,
            "stds": stds,
        }
        metadata = {
            "source_model": model_name,
            "model_key": "final_rfe_regression",
            "name": f"Final RFE {self._source_model_label(model_name)}",
            **self._final_binding_metadata(model_name, context),
            "feature_count": len(selected_features),
            "features": selected_features,
            "metrics": metrics,
            "holdout_rmse": metrics.get("rmse"),
            "holdout_r2": metrics.get("r2"),
            "holdout_adjusted_r2": metrics.get("adjusted_r2"),
            **refit_metadata,
        }
        RESULTS.set_final_model(artifact, metadata)
        return {"ok": True, "metadata": metadata}

    def final_model_status(self, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        artifact = RESULTS.get_final_model()
        metadata = RESULTS.get_final_model_metadata() or {}
        mismatch = self._final_model_context_mismatch(metadata, context) if artifact is not None else ""
        if artifact is not None:
            summary = RESULTS.get_last_summary() or {}
            ranked = summary.get("ranked") or []
            source = next((row for row in ranked if row.get("key") == metadata.get("source_model")), {})
            X_train, _, y_train, _ = DATASTORE.get_splits()
            enriched = dict(metadata)
            enriched.setdefault("final_model_version", "final-model-v1")
            enriched.setdefault("feature_selection_method", "Recursive Feature Elimination")
            enriched.setdefault("preprocessing_pipeline", "Governed encoding, median imputation, and standardization")
            enriched.setdefault("calibration_method", source.get("calibration_method") or ("Applied" if source.get("calibration_applied") else "Not applied"))
            if y_train is not None:
                y_numeric = pd.to_numeric(pd.Series(y_train), errors="coerce").dropna()
                if len(y_numeric) and set(np.unique(y_numeric)).issubset({0, 1}):
                    enriched.setdefault("modeled_event_rate", float(np.mean(y_numeric)))
            source_meta = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta, dict) else {}
            if isinstance(source_meta, dict):
                for key in ("natural_event_rate", "original_event_rate", "population_event_rate"):
                    value = source_meta.get(key)
                    if isinstance(value, (int, float)):
                        enriched.setdefault("natural_event_rate", float(value))
                        break
            hash_payload = json.dumps(enriched, sort_keys=True, default=str).encode("utf-8")
            enriched["artifact_hash"] = hashlib.sha256(hash_payload).hexdigest()
            metadata = enriched
        return {
            "ok": True,
            "ready": artifact is not None and not mismatch,
            "artifact_present": artifact is not None,
            "stale": bool(artifact is not None and mismatch),
            "blocker": mismatch or None,
            "metadata": metadata if artifact is not None else {},
        }

    def save_selected_model_as_final(
        self,
        model_name: str = "",
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        summary = RESULTS.get_last_summary() or {}
        ranked = summary.get("ranked") or []
        if not model_name:
            model_name = ranked[0].get("key") if ranked else ""
        mismatch = self._promotion_context_mismatch(model_name, context) if model_name else ""
        if mismatch:
            return {
                "ok": False,
                "error": mismatch,
                "debug": self._artifact_debug(model_name, {**self._active_model_binding(context), **(context or {})}),
            }
        artifact = self._artifact(model_name)
        if artifact is None:
            return {"ok": False, "error": "No fitted model artifact found for the selected model."}
        row = next((item for item in ranked if item.get("key") == model_name), {})
        X_train, _, _, _ = DATASTORE.get_splits()
        metadata = {
            "source_model": model_name,
            "model_key": model_name,
            "name": row.get("name") or model_name,
            **self._final_binding_metadata(model_name, context),
            "source_estimator_class": artifact.__class__.__name__,
            "final_estimator_class": artifact.__class__.__name__,
            "feature_count": int(len(X_train.columns)) if X_train is not None else None,
            "features": list(X_train.columns) if X_train is not None else [],
            "metrics": {
                key: row.get(key)
                for key in ("auc", "pr_auc", "accuracy", "f1", "mae", "mse", "rmse", "r2", "adjusted_r2")
                if row.get(key) is not None
            },
        }
        RESULTS.set_final_model(artifact, metadata)
        return {"ok": True, "metadata": metadata}

    def _stability_index_numeric(self, expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
        exp = pd.to_numeric(expected, errors="coerce").dropna()
        act = pd.to_numeric(actual, errors="coerce").dropna()
        if exp.empty or act.empty:
            return 0.0
        quantiles = np.unique(np.quantile(exp, np.linspace(0, 1, bins + 1)))
        internal_edges = quantiles[1:-1]
        if len(internal_edges) < 1:
            min_value = float(exp.min())
            max_value = float(exp.max())
            if min_value == max_value:
                internal_edges = np.asarray([min_value], dtype=float)
            else:
                internal_edges = np.linspace(min_value, max_value, min(bins, 4) + 1)[1:-1]
        edges = np.concatenate(([-np.inf], np.unique(internal_edges), [np.inf]))
        exp_counts = pd.cut(exp, edges, include_lowest=True, duplicates="drop").value_counts(sort=False)
        act_counts = pd.cut(act, edges, include_lowest=True, duplicates="drop").value_counts(sort=False)
        return self._psi_from_counts(exp_counts.to_numpy(), act_counts.to_numpy())

    def _stability_index_categorical(self, expected: pd.Series, actual: pd.Series) -> float:
        exp = expected.astype(str).fillna("__missing__")
        act = actual.astype(str).fillna("__missing__")
        cats = sorted(set(exp.unique()).union(set(act.unique())))
        exp_counts = np.asarray([(exp == cat).sum() for cat in cats], dtype=float)
        act_counts = np.asarray([(act == cat).sum() for cat in cats], dtype=float)
        return self._psi_from_counts(exp_counts, act_counts)

    def _psi_from_counts(self, expected_counts: np.ndarray, actual_counts: np.ndarray) -> float:
        expected_pct = expected_counts.astype(float) / max(float(expected_counts.sum()), 1.0)
        actual_pct = actual_counts.astype(float) / max(float(actual_counts.sum()), 1.0)
        expected_pct = np.clip(expected_pct, 1e-6, None)
        actual_pct = np.clip(actual_pct, 1e-6, None)
        return float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))

    def _status(self, value: float) -> str:
        if value < 0.10:
            return "pass"
        if value < 0.25:
            return "warning"
        return "fail"

    def _positive_rate(self, y: pd.Series) -> float | None:
        labels = pd.Series(y).dropna().astype(str)
        classes = sorted(labels.unique())
        if len(classes) != 2:
            return None
        return float((labels == classes[-1]).mean())

    def _is_regression_problem(self) -> bool:
        summary = RESULTS.get_last_summary() or {}
        if summary.get("problem_type") == "regression":
            return True
        ranked = summary.get("ranked") or []
        return any(row.get("task") == "regression" for row in ranked)

    def _regression_metrics(self, y_true: pd.Series, predictions: np.ndarray, n_features: int = 0) -> Dict[str, Any]:
        y = pd.to_numeric(pd.Series(y_true), errors="coerce")
        pred = pd.Series(np.asarray(predictions, dtype=float), index=y.index)
        valid = y.notna() & pred.notna()
        if not valid.any():
            return {}
        y_arr = y[valid].to_numpy(dtype=float)
        pred_arr = pred[valid].to_numpy(dtype=float)
        mse = float(mean_squared_error(y_arr, pred_arr)) if mean_squared_error is not None else float(np.mean((y_arr - pred_arr) ** 2))
        mae = float(mean_absolute_error(y_arr, pred_arr)) if mean_absolute_error is not None else float(np.mean(np.abs(y_arr - pred_arr)))
        r2 = float(r2_score(y_arr, pred_arr)) if r2_score is not None else None
        n_obs = int(len(y_arr))
        p = int(max(n_features, 0))
        adjusted_r2 = (
            float(1 - (1 - r2) * (n_obs - 1) / max(n_obs - p - 1, 1))
            if r2 is not None and n_obs > p + 1
            else None
        )
        residuals = y_arr - pred_arr
        return {
            "mae": mae,
            "mse": mse,
            "rmse": float(np.sqrt(mse)),
            "r2": r2,
            "adjusted_r2": adjusted_r2,
            "mean_residual": float(np.mean(residuals)),
            "mean_abs_residual": float(np.mean(np.abs(residuals))),
        }

    def _default_priors(self) -> Dict[str, Any]:
        prevalence = DATASTORE.meta.get("target_prevalence") or {}
        X_train, _, y_train, _ = DATASTORE.get_splits()
        model_prior = prevalence.get("train")
        if model_prior is None and y_train is not None:
            model_prior = self._positive_rate(y_train)
        original_prior = prevalence.get("original")
        if original_prior is None:
            df = DATASTORE.get_active_df()
            target = DATASTORE.target
            if df is not None and target and target in df.columns:
                original_prior = self._positive_rate(df[target])
        return {
            "original_prior": original_prior,
            "model_prior": model_prior,
            "split_config": DATASTORE.meta.get("split_config") or {},
            "train_rows": int(len(X_train)) if X_train is not None else None,
        }

    def _prior_correct_scores(
        self,
        scores: np.ndarray,
        method: str = "none",
        original_prior: float | None = None,
        model_prior: float | None = None,
    ) -> np.ndarray:
        method = str(method or "none").lower()
        scores = np.asarray(scores, dtype=float)
        if method in ("none", "raw", ""):
            return scores
        if method not in ("prior_odds", "pozzolo"):
            return scores
        if original_prior is None or model_prior is None:
            return scores
        original_prior = float(np.clip(original_prior, 1e-6, 1 - 1e-6))
        model_prior = float(np.clip(model_prior, 1e-6, 1 - 1e-6))
        score_odds = np.clip(scores, 1e-9, 1 - 1e-9) / np.clip(1 - scores, 1e-9, 1)
        prior_factor = (original_prior / (1 - original_prior)) / (model_prior / (1 - model_prior))
        corrected_odds = score_odds * prior_factor
        return corrected_odds / (1 + corrected_odds)

    def _lift_table(self, y_true: pd.Series, scores: np.ndarray, deciles: int = 10) -> List[Dict[str, Any]]:
        labels = pd.Series(y_true).astype(str)
        classes = sorted(pd.Series(y_true).dropna().astype(str).unique())
        if len(classes) != 2:
            return []
        y_arr = (labels == classes[-1]).astype(int).to_numpy()
        scores = np.asarray(scores, dtype=float)
        if len(scores) != len(y_arr):
            return []
        order = np.argsort(-scores)
        y_sorted = y_arr[order]
        score_sorted = scores[order]
        total_positives = int(np.sum(y_sorted))
        base_rate = float(np.mean(y_sorted)) if len(y_sorted) else 0.0
        cumulative_positives = 0
        rows: List[Dict[str, Any]] = []
        for decile, indices in enumerate(np.array_split(np.arange(len(y_sorted)), deciles), start=1):
            if not len(indices):
                continue
            bucket_y = y_sorted[indices]
            bucket_scores = score_sorted[indices]
            positives = int(np.sum(bucket_y))
            cumulative_positives += positives
            event_rate = float(np.mean(bucket_y)) if len(bucket_y) else 0.0
            rows.append(
                {
                    "decile": int(decile),
                    "n": int(len(indices)),
                    "positives": positives,
                    "event_rate": event_rate,
                    "lift": float(event_rate / base_rate) if base_rate > 0 else 0.0,
                    "cumulative_positives": int(cumulative_positives),
                    "capture_rate": float(cumulative_positives / total_positives) if total_positives > 0 else 0.0,
                    "min_score": float(np.min(bucket_scores)),
                    "max_score": float(np.max(bucket_scores)),
                    "mean_score": float(np.mean(bucket_scores)),
                }
            )
        return rows

    def _resolve_scoring_model(self, model_name: str = "") -> Tuple[Any, Dict[str, Any]]:
        if model_name in ("", "final", "final_rfe"):
            final_model = RESULTS.get_final_model()
            metadata = RESULTS.get_final_model_metadata() or {}
            if final_model is not None:
                mismatch = self._final_model_context_mismatch(metadata)
                if mismatch:
                    raise ValueError(mismatch)
                return final_model, metadata
            raise ValueError("No governed final model is available for scoring. Save a current trained model as final first.")
        artifact = self._artifact(model_name)
        if artifact is None:
            raise ValueError("No model artifact is available for scoring.")
        mismatch = self._promotion_context_mismatch(model_name)
        if mismatch:
            raise ValueError(mismatch)
        metadata = RESULTS.get_model_artifact_metadata(model_name) or {}
        summary = RESULTS.get_last_summary() or {}
        X_train, _, _, _ = DATASTORE.get_splits()
        return artifact, {
            **metadata,
            "model_key": model_name,
            "name": next(
                (row.get("name") for row in (summary.get("ranked") or []) if row.get("key") == model_name),
                model_name,
            ),
            "features": list(X_train.columns) if X_train is not None else [],
        }

    def export_model_bundle(self, model_name: str = "final") -> Tuple[bytes, str]:
        _, metadata = self._resolve_scoring_model(model_name)
        summary = RESULTS.get_last_summary() or {}
        X_train, _, _, _ = DATASTORE.get_splits()
        ranked = summary.get("ranked") or []
        selected_key = metadata.get("model_key") or model_name
        selected_summary = next((row for row in ranked if row.get("key") == selected_key), {})
        manifest = {
            "schema": "atlas.model_manifest.v1",
            "metadata": {
                **metadata,
                "target": DATASTORE.target,
                "problem_type": summary.get("problem_type"),
                "feature_columns": list(X_train.columns) if X_train is not None else metadata.get("features", []),
                "selected_model_summary": selected_summary,
                "exported_at": datetime.now().isoformat(),
                "export_format": "json_manifest",
            },
            "deployment_status": "manifest_only",
            "scoring_note": "ATLAS does not export executable model objects through this endpoint. Use the manifest for governed review and deploy through a signed model registry or approved ONNX/skops pipeline.",
            "metrics": selected_summary.get("metrics") or {},
            "hyperparameters": selected_summary.get("best_params") or {},
            "ranked_models": ranked,
        }
        raw_name = str(metadata.get("name") or selected_key or "model")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_name).strip("_").lower() or "model"
        return json.dumps(manifest, indent=2, sort_keys=True, default=str).encode("utf-8"), f"{safe_name}_manifest.json"

    def score_dataset(
        self,
        df: pd.DataFrame,
        dataset_type: str = "test",
        model_name: str = "final",
        correction_method: str = "none",
        original_prior: float | None = None,
        model_prior: float | None = None,
    ) -> Dict[str, Any]:
        if df is None or df.empty:
            return {"ok": False, "error": "Uploaded scoring dataset is empty."}
        try:
            model, metadata = self._resolve_scoring_model(model_name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "stale_model": True}
        target = DATASTORE.target
        y_true = None
        original_df = df.reset_index(drop=True).copy()
        X = df.copy()
        if target and target in X.columns:
            y_true = X[target].copy()
            X = X.drop(columns=[target])

        task = "regression" if self._is_regression_problem() else "classification"
        model_features = [str(feature) for feature in (metadata.get("features") or [])]
        matched_features: List[str] = []
        missing_features: List[str] = []
        if isinstance(model, dict) and model.get("kind") in ("rfe_logistic", "rfe_regression", "rfe_classifier", "rfe_regressor"):
            _, matched_features, missing_features = self._prepare_final_feature_frame(model, X)
            model_features = [str(feature) for feature in model.get("features", model_features)]
        else:
            normalized_columns = {str(col).strip().lower(): col for col in X.columns}
            for feature in model_features:
                if feature in X.columns or feature.strip().lower() in normalized_columns:
                    matched_features.append(feature)
                else:
                    missing_features.append(feature)
        scores = self._predict_score(model, X)
        priors = self._default_priors()
        if original_prior is None:
            original_prior = priors.get("original_prior")
        if model_prior is None:
            model_prior = priors.get("model_prior")
        adjusted_scores = (
            scores
            if task == "regression"
            else self._prior_correct_scores(scores, correction_method, original_prior, model_prior)
        )
        labels = (adjusted_scores >= 0.5).astype(int) if task == "classification" else adjusted_scores
        scored_df = build_full_scored_output_frame(
            original_df=original_df,
            target=str(target) if target else None,
            y_true=y_true,
            scores=np.asarray(scores),
            adjusted_scores=np.asarray(adjusted_scores),
            labels=np.asarray(labels),
            task=task,
            split=dataset_type,
        )
        response: Dict[str, Any] = {
            "ok": True,
            "task": task,
            "dataset_type": dataset_type,
            "model": metadata,
            "rows": int(len(X)),
            "score_summary": {
                "min": float(np.min(scores)) if len(scores) else None,
                "mean": float(np.mean(scores)) if len(scores) else None,
                "max": float(np.max(scores)) if len(scores) else None,
            },
            "scoring_diagnostics": {
                "model_feature_count": int(len(model_features)),
                "matched_feature_count": int(len(matched_features)),
                "missing_features": missing_features,
                "prediction_std": float(np.std(scores)) if len(scores) else None,
                "constant_prediction": bool(len(scores) > 1 and float(np.std(scores)) < 1e-10),
            },
            "adjusted_score_summary": {
                "min": float(np.min(adjusted_scores)) if len(adjusted_scores) else None,
                "mean": float(np.mean(adjusted_scores)) if len(adjusted_scores) else None,
                "max": float(np.max(adjusted_scores)) if len(adjusted_scores) else None,
            },
            "probability_correction": {
                "method": correction_method,
                "original_prior": original_prior,
                "model_prior": model_prior,
                "default_original_prior": priors.get("original_prior"),
                "default_model_prior": priors.get("model_prior"),
                "split_config": priors.get("split_config"),
            },
            "target_column": str(target) if target else None,
            "scored_rows": dataframe_to_json_records(scored_df),
            "scored_columns": [str(column) for column in scored_df.columns],
            "scored_row_scope": "full_scored_output",
            "preview": [
                {
                    "row": int(i + 1),
                    "score": float(score),
                    "adjusted_score": float(adjusted),
                    "prediction": float(label),
                    **(
                        {"actual": safe_numeric_preview_value(pd.Series(y_true).iloc[i]), str(target): safe_numeric_preview_value(pd.Series(y_true).iloc[i])}
                        if y_true is not None and i < len(pd.Series(y_true))
                        else {}
                    ),
                }
                for i, (score, adjusted, label) in enumerate(zip(scores[:25], adjusted_scores[:25], labels[:25]))
            ],
        }

        if task == "regression":
            response["probability_correction"] = {"method": "not_applicable"}

        if dataset_type.lower() == "test":
            RESULTS.set_scoring_reference(
                {
                    "kind": "uploaded_test",
                    "model_key": metadata.get("model_key") or model_name,
                    "model_name": metadata.get("name") or model_name,
                    "features": list(metadata.get("features") or []),
                    "X": X.copy(),
                    "scores": np.asarray(adjusted_scores, dtype=float),
                }
            )

        if y_true is not None and task == "regression":
            response["metrics"] = self._regression_metrics(y_true, adjusted_scores, n_features=X.shape[1])
        elif y_true is not None and LabelEncoder is not None:
            try:
                encoder = LabelEncoder()
                y_arr = encoder.fit_transform(pd.Series(y_true).astype(str))
                if len(encoder.classes_) == 2:
                    response["metrics"] = {
                        "auc": float(roc_auc_score(y_arr, adjusted_scores)) if roc_auc_score is not None else None,
                        "pr_auc": float(average_precision_score(y_arr, adjusted_scores)) if average_precision_score is not None else None,
                        "accuracy": float(accuracy_score(y_arr, labels)) if accuracy_score is not None else None,
                        "precision": float(precision_score(y_arr, labels, zero_division=0)) if precision_score is not None else None,
                        "recall": float(recall_score(y_arr, labels, zero_division=0)) if recall_score is not None else None,
                        "f1": float(f1_score(y_arr, labels, zero_division=0)) if f1_score is not None else None,
                        "brier_score": float(brier_score_loss(y_arr, adjusted_scores)) if brier_score_loss is not None else None,
                        "event_rate": float(np.mean(y_arr)) if len(y_arr) else None,
                        "confusion": confusion_matrix(y_arr, labels).tolist() if confusion_matrix is not None else None,
                    }
                    if roc_curve is not None:
                        fpr, tpr, _ = roc_curve(y_arr, adjusted_scores)
                        response["metrics"]["ks"] = float(np.max(tpr - fpr)) if len(fpr) else None
                    response["lift"] = self._lift_table(y_true, adjusted_scores)
            except Exception as exc:
                response["metrics_error"] = str(exc)

        if dataset_type.lower() in {"test", "oot"}:
            X_train, X_test, _, _ = DATASTORE.get_splits()
            reference = X_train if X_train is not None else X_test
            if reference is not None:
                ref_scores = self._prior_correct_scores(
                    self._predict_score(model, reference),
                    correction_method,
                    original_prior,
                    model_prior,
                )
                response["psi"] = {
                    "name": "score",
                    "value": self._stability_index_numeric(pd.Series(ref_scores), pd.Series(adjusted_scores)),
                }
                response["psi"]["status"] = self._status(response["psi"]["value"])
                vsi_rows = []
                model_features = [
                    str(feature)
                    for feature in (metadata.get("features") or [])
                    if str(feature) in reference.columns and str(feature) in X.columns
                ]
                common = model_features or [col for col in reference.columns if col in X.columns]
                for col in common:
                    if pd.api.types.is_numeric_dtype(reference[col]):
                        value = self._stability_index_numeric(reference[col], X[col])
                    else:
                        value = self._stability_index_categorical(reference[col], X[col])
                    vsi_rows.append({"feature": col, "value": value, "status": self._status(value)})
                vsi_rows.sort(key=lambda row: row["value"], reverse=True)
                response["vsi"] = vsi_rows[:50]
                response["vsi_scope"] = "model_features" if model_features else "all_common_features"
                response["stability_reference"] = "development_train"
        return response

    def score_development_split(
        self,
        dataset_type: str = "train",
        model_name: str = "final",
        correction_method: str = "none",
        original_prior: float | None = None,
        model_prior: float | None = None,
    ) -> Dict[str, Any]:
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        split_key = str(dataset_type or "train").lower()
        if split_key == "test":
            X, y = X_test, y_test
        else:
            X, y = X_train, y_train
            split_key = "train"
        if X is None or y is None:
            return {"ok": False, "error": f"No {split_key.upper()} development split is available. Train models first."}
        df = X.copy()
        target = DATASTORE.target or getattr(y, "name", None) or "target"
        df[str(target)] = pd.Series(y).reset_index(drop=True).values
        result = self.score_dataset(
            df=df,
            dataset_type=split_key,
            model_name=model_name,
            correction_method=correction_method,
            original_prior=original_prior,
            model_prior=model_prior,
        )
        if result.get("ok"):
            result["dataset_identity"] = f"Governed development {split_key.upper()} split"
            result["dataset_version"] = DATASTORE.meta.get("dataset_version") or "Not recorded"
        return result

    def decision_boundary(
        self,
        model_name: str,
        x_feature: str = "",
        y_feature: str = "",
        resolution: int = 60,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        mismatch = self._artifact_context_mismatch(model_name, context)
        if mismatch:
            return {"ok": False, "error": mismatch, "debug": self._artifact_debug(model_name, context)}
        model = self._artifact(model_name, context)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, y_test = self._test_data()
        numeric_cols = [col for col in X_test.columns if pd.api.types.is_numeric_dtype(X_test[col])]
        if len(numeric_cols) < 2:
            return {"ok": False, "error": "Decision boundary requires at least two numeric features."}

        if PCA is not None and (not x_feature or not y_feature or x_feature.startswith("PCA") or y_feature.startswith("PCA")):
            numeric = X_test[numeric_cols].copy()
            for col in numeric_cols:
                numeric[col] = pd.to_numeric(numeric[col], errors="coerce")
            medians = numeric.median(numeric_only=True)
            numeric = numeric.fillna(medians)
            means = numeric.mean()
            stds = numeric.std().replace(0, 1).fillna(1)
            scaled = (numeric - means) / stds
            pca = PCA(n_components=2)
            coords = pca.fit_transform(scaled)
            x_vals = coords[:, 0]
            y_vals = coords[:, 1]
            x_min, x_max = float(np.quantile(x_vals, 0.02)), float(np.quantile(x_vals, 0.98))
            y_min, y_max = float(np.quantile(y_vals, 0.02)), float(np.quantile(y_vals, 0.98))
            resolution = max(25, min(80, int(resolution or 60)))
            xs = np.linspace(x_min, x_max, resolution)
            ys = np.linspace(y_min, y_max, resolution)
            grid_rows: List[Dict[str, Any]] = []
            base = pd.DataFrame([X_test.iloc[0].copy() for _ in range(resolution)])
            for y_val in ys:
                pca_batch = np.column_stack([xs, np.full_like(xs, y_val)])
                inverse_scaled = pca.inverse_transform(pca_batch)
                numeric_batch = pd.DataFrame(inverse_scaled, columns=numeric_cols) * stds + means
                batch = base.copy()
                for col in numeric_cols:
                    batch[col] = numeric_batch[col].to_numpy()
                scores = self._predict_score(model, batch)
                for x_val, score in zip(xs, scores):
                    grid_rows.append({"x": float(x_val), "y": float(y_val), "score": float(score)})
            try:
                _, y_test_arr = self._encode_binary_target(y_test, y_test)
            except Exception:
                y_test_arr = np.zeros(len(X_test), dtype=int)
            points = [
                {"x": float(px), "y": float(py), "class": int(y_test_arr[i]) if i < len(y_test_arr) else 0}
                for i, (px, py) in enumerate(coords[:500])
            ]
            return {
                "ok": True,
                "x_feature": "PCA 1",
                "y_feature": "PCA 2",
                "x_domain": [x_min, x_max],
                "y_domain": [y_min, y_max],
                "resolution": resolution,
                "grid": grid_rows,
                "points": points,
                "numeric_features": ["PCA 1", "PCA 2"] + numeric_cols,
            }

        importance = self.feature_importance(model_name).get("rows", [])
        ordered = [row["feature"] for row in importance if row.get("feature") in numeric_cols]
        ordered += [col for col in numeric_cols if col not in ordered]
        x_name = x_feature if x_feature in numeric_cols else ordered[0]
        y_name = y_feature if y_feature in numeric_cols and y_feature != x_name else ordered[1]

        work = X_test.copy()
        base_row: Dict[str, Any] = {}
        for col in work.columns:
            if pd.api.types.is_numeric_dtype(work[col]):
                base_row[col] = float(pd.to_numeric(work[col], errors="coerce").median())
            else:
                mode = work[col].astype(str).mode(dropna=True)
                base_row[col] = mode.iloc[0] if len(mode) else ""

        x_values = pd.to_numeric(work[x_name], errors="coerce").dropna()
        y_values = pd.to_numeric(work[y_name], errors="coerce").dropna()
        if x_values.empty or y_values.empty:
            return {"ok": False, "error": "Selected boundary features do not have numeric values."}
        x_min, x_max = float(x_values.quantile(0.02)), float(x_values.quantile(0.98))
        y_min, y_max = float(y_values.quantile(0.02)), float(y_values.quantile(0.98))
        if x_min == x_max:
            x_min -= 1
            x_max += 1
        if y_min == y_max:
            y_min -= 1
            y_max += 1

        resolution = max(25, min(80, int(resolution or 60)))
        xs = np.linspace(x_min, x_max, resolution)
        ys = np.linspace(y_min, y_max, resolution)
        grid_rows: List[Dict[str, Any]] = []
        for y_val in ys:
            batch = pd.DataFrame([base_row.copy() for _ in xs])
            batch[x_name] = xs
            batch[y_name] = y_val
            scores = self._predict_score(model, batch)
            for x_val, score in zip(xs, scores):
                grid_rows.append({"x": float(x_val), "y": float(y_val), "score": float(score)})

        try:
            _, y_test_arr = self._encode_binary_target(y_test, y_test)
        except Exception:
            y_test_arr = np.zeros(len(work), dtype=int)
        points_df = work[[x_name, y_name]].copy()
        points_df[x_name] = pd.to_numeric(points_df[x_name], errors="coerce")
        points_df[y_name] = pd.to_numeric(points_df[y_name], errors="coerce")
        points = []
        for idx, row in points_df.dropna().head(500).iterrows():
            pos = list(work.index).index(idx) if idx in work.index else 0
            points.append(
                {
                    "x": float(row[x_name]),
                    "y": float(row[y_name]),
                    "class": int(y_test_arr[pos]) if pos < len(y_test_arr) else 0,
                }
            )

        return {
            "ok": True,
            "x_feature": x_name,
            "y_feature": y_name,
            "x_domain": [x_min, x_max],
            "y_domain": [y_min, y_max],
            "resolution": resolution,
            "grid": grid_rows,
            "points": points,
            "numeric_features": numeric_cols,
        }

def safe_numeric_preview_value(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            return float(value)
        if isinstance(value, (int, float, str, bool)):
            return value
        return float(value)
    except Exception:
        return str(value)


def dataframe_to_json_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if df is None or df.empty:
        return records
    for raw in df.to_dict(orient="records"):
        records.append({str(key): safe_numeric_preview_value(value) for key, value in raw.items()})
    return records


def build_full_scored_output_frame(
    original_df: pd.DataFrame,
    target: str | None,
    y_true: pd.Series | None,
    scores: np.ndarray,
    adjusted_scores: np.ndarray,
    labels: np.ndarray,
    task: str,
    split: str,
) -> pd.DataFrame:
    scored = original_df.reset_index(drop=True).copy()
    if "row" not in {str(column).lower() for column in scored.columns}:
        scored.insert(0, "row", np.arange(1, len(scored) + 1))

    if task == "regression":
        predictions = pd.Series(adjusted_scores, index=scored.index, dtype="float64")
        scored["predicted_value"] = predictions
        scored["prediction"] = predictions
        if y_true is not None:
            actual = pd.to_numeric(pd.Series(y_true).reset_index(drop=True), errors="coerce")
            if target:
                scored[target] = pd.Series(y_true).reset_index(drop=True)
            scored["actual"] = actual
            residual = actual - predictions
            scored["atlas_residual"] = residual
            scored["atlas_abs_residual"] = residual.abs()
            scored["atlas_squared_residual"] = residual * residual
            scored["atlas_percent_error"] = residual.where(actual != 0) / actual.where(actual != 0)
        else:
            scored["actual"] = None
            scored["atlas_residual"] = None
            scored["atlas_abs_residual"] = None
            scored["atlas_squared_residual"] = None
            scored["atlas_percent_error"] = None
    else:
        scored["score"] = pd.Series(scores, index=scored.index, dtype="float64")
        scored["adjusted_score"] = pd.Series(adjusted_scores, index=scored.index, dtype="float64")
        scored["prediction"] = pd.Series(labels, index=scored.index)
        if y_true is not None:
            if target:
                scored[target] = pd.Series(y_true).reset_index(drop=True)
            scored["actual"] = pd.Series(y_true).reset_index(drop=True)

    scored["split"] = str(split or "").upper()
    return scored


EVAL = EvaluationService()
