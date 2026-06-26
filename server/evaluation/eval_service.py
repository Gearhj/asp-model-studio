from typing import Any, Dict, List

import numpy as np
import pandas as pd

from ..core.dataset_store import DATASTORE
from ..core.result_store import RESULTS

try:
    from sklearn.metrics import precision_recall_curve, roc_auc_score, roc_curve
    from sklearn.inspection import permutation_importance
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import LabelEncoder
except Exception:  # pragma: no cover
    precision_recall_curve = None
    roc_auc_score = None
    roc_curve = None
    permutation_importance = None
    LogisticRegression = None
    LabelEncoder = None


class EvaluationService:
    def _model_result(self, model_name: str) -> Dict[str, Any] | None:
        summary = RESULTS.get_last_summary() or {}
        raw = summary.get("raw") or {}
        return raw.get(model_name)

    def get_curves(self, model_name: str) -> Dict[str, Any]:
        result = self._model_result(model_name)
        if not result:
            return {"ok": False, "error": "No fitted results found for this model."}

        metrics = result.get("metrics") or {}
        y_true = np.asarray(result.get("y_true") or [], dtype=float)
        y_score = np.asarray(result.get("y_score") or [], dtype=float)

        response: Dict[str, Any] = {
            "ok": True,
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

    def _artifact(self, model_name: str):
        return RESULTS.get_model_artifact(model_name)

    def _test_data(self):
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if X_test is None or y_test is None:
            raise ValueError("No evaluation split is available. Train models first.")
        return X_train, X_test, y_train, y_test

    def _predict_score(self, model: Any, X: pd.DataFrame) -> np.ndarray:
        if hasattr(model, "predict_proba"):
            return np.asarray(model.predict_proba(X)[:, 1], dtype=float)
        if hasattr(model, "decision_function"):
            raw = np.asarray(model.decision_function(X), dtype=float)
            return (raw - np.min(raw)) / (np.max(raw) - np.min(raw) + 1e-9)
        return np.asarray(model.predict(X), dtype=float)

    def feature_importance(self, model_name: str) -> Dict[str, Any]:
        model = self._artifact(model_name)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, y_test = self._test_data()

        rows: List[Dict[str, Any]] = []
        estimator = getattr(model, "named_steps", {}).get("model") if hasattr(model, "named_steps") else model
        native = getattr(estimator, "feature_importances_", None)
        if native is not None:
            preprocess = model.named_steps.get("preprocess") if hasattr(model, "named_steps") else None
            names = preprocess.get_feature_names_out() if preprocess is not None and hasattr(preprocess, "get_feature_names_out") else X_test.columns
            rows = [
                {
                    "feature": str(name).replace("num__", "").replace("cat__", ""),
                    "importance": abs(float(value)),
                    "direction": float(value),
                    "source": "native",
                }
                for name, value in zip(names, native)
            ]
        elif permutation_importance is not None:
            result = permutation_importance(model, X_test, y_test, n_repeats=5, random_state=42, n_jobs=1)
            rows = [
                {
                    "feature": str(feature),
                    "importance": abs(float(value)),
                    "direction": float(value),
                    "source": "permutation",
                }
                for feature, value in zip(X_test.columns, result.importances_mean)
            ]

        rows.sort(key=lambda row: row["importance"], reverse=True)
        return {"ok": True, "rows": rows[:30]}

    def hyperparameters(self, model_name: str) -> Dict[str, Any]:
        result = self._model_result(model_name) or {}
        summary = RESULTS.get_last_summary() or {}
        ranked = summary.get("ranked") or []
        row = next((item for item in ranked if item.get("key") == model_name), {})
        params = result.get("best_params") or row.get("best_params") or {}
        score = result.get("best_score") or row.get("best_score")
        if not params:
            model = self._artifact(model_name)
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

    def model_details(self, model_name: str) -> Dict[str, Any]:
        model = self._artifact(model_name)
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
            rows = [
                {
                    "feature": str(name).replace("num__", "").replace("cat__", ""),
                    "coefficient": float(value),
                    "odds_ratio": float(np.exp(value)),
                }
                for name, value in zip(names, coef)
            ]
            rows.sort(key=lambda row: abs(row["coefficient"]), reverse=True)
            return {"ok": True, "kind": "equation", "intercept": intercept, "coefficients": rows[:40]}

        if estimator.__class__.__name__.lower().startswith("decisiontree"):
            try:
                from sklearn.tree import export_text

                tree_text = export_text(estimator, feature_names=[str(n) for n in names], max_depth=4)
            except Exception as exc:
                tree_text = f"Unable to export tree text: {exc}"
            return {"ok": True, "kind": "tree", "tree_text": tree_text}

        return {"ok": True, "kind": "generic", "message": f"{estimator.__class__.__name__} uses model-agnostic interpretation panels below."}

    def pdp(self, model_name: str, feature: str) -> Dict[str, Any]:
        model = self._artifact(model_name)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, _ = self._test_data()
        if feature not in X_test.columns:
            return {"ok": False, "error": f"Feature '{feature}' was not found."}

        x = X_test.copy()
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
            "rows": rows,
        }

    def sensitivity(self, model_name: str, feature: str) -> Dict[str, Any]:
        model = self._artifact(model_name)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, _ = self._test_data()
        if feature not in X_test.columns:
            return {"ok": False, "error": f"Feature '{feature}' was not found."}
        baseline = float(np.mean(self._predict_score(model, X_test)))
        rows = []
        if pd.api.types.is_numeric_dtype(X_test[feature]):
            for pct in [-0.2, -0.1, 0.0, 0.1, 0.2]:
                x_mod = X_test.copy()
                x_mod[feature] = pd.to_numeric(x_mod[feature], errors="coerce") * (1 + pct)
                pred = float(np.mean(self._predict_score(model, x_mod)))
                rows.append({"scenario": f"{pct:+.0%}", "prediction": pred, "delta": pred - baseline})
        else:
            for value in X_test[feature].astype(str).value_counts().head(8).index:
                x_mod = X_test.copy()
                x_mod[feature] = value
                pred = float(np.mean(self._predict_score(model, x_mod)))
                rows.append({"scenario": str(value), "prediction": pred, "delta": pred - baseline})
        return {"ok": True, "baseline": baseline, "rows": rows}

    def shap_summary(self, model_name: str) -> Dict[str, Any]:
        model = self._artifact(model_name)
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
        rows.sort(key=lambda row: abs(row["importance"]), reverse=True)
        return {
            "ok": True,
            "method": "Holdout replacement impact",
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

    def _encode_binary_target(self, y_train: pd.Series, y_test: pd.Series):
        if LabelEncoder is None:
            raise ValueError("scikit-learn label encoding is unavailable.")
        encoder = LabelEncoder()
        encoder.fit(pd.concat([pd.Series(y_train), pd.Series(y_test)], ignore_index=True).astype(str))
        if len(encoder.classes_) != 2:
            raise ValueError("This analysis requires a binary target.")
        return encoder.transform(pd.Series(y_train).astype(str)), encoder.transform(pd.Series(y_test).astype(str))

    def rfe(self, model_name: str = "", keep: int = 10) -> Dict[str, Any]:
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if X_train is None or X_test is None or y_train is None or y_test is None:
            return {"ok": False, "error": "No training split is available. Train models first."}
        numeric_cols = [col for col in X_train.columns if pd.api.types.is_numeric_dtype(X_train[col])]
        if len(numeric_cols) < 2:
            return {"ok": False, "error": "RFE currently requires at least two numeric features."}
        if LogisticRegression is None or LabelEncoder is None or roc_auc_score is None:
            return {"ok": False, "error": "scikit-learn logistic regression metrics are unavailable."}

        if len(numeric_cols) > 20:
            single_feature_scores: List[Dict[str, Any]] = []
            for feature in numeric_cols:
                try:
                    med = X_train[[feature]].median(numeric_only=True)
                    train_one = X_train[[feature]].fillna(med)
                    test_one = X_test[[feature]].fillna(med)
                    y_train_tmp, y_test_tmp = self._encode_binary_target(y_train, y_test)
                    single_feature_scores.append(
                        {
                            "feature": feature,
                            "auc": self._score_feature_subset(train_one, test_one, y_train_tmp, y_test_tmp, [feature]),
                        }
                    )
                except Exception:
                    single_feature_scores.append({"feature": feature, "auc": 0.5})
            numeric_cols = [
                row["feature"]
                for row in sorted(single_feature_scores, key=lambda row: row["auc"], reverse=True)[:20]
            ]

        medians = X_train[numeric_cols].median(numeric_only=True)
        prepared_train = X_train[numeric_cols].fillna(medians)
        prepared_test = X_test[numeric_cols].fillna(medians)
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

        best_count = max(curve_rows, key=lambda row: row["display_auc"])["feature_count"]
        recommended_count = best_count
        for row in curve_rows[1:]:
            marginal = row.get("marginal_auc")
            if marginal is not None and marginal <= 0.001:
                recommended_count = int(row["feature_count"])
                break

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
                "importance": float(removal_auc.get(feature, 0.0)),
                "rank": index,
                "selected": index <= requested_keep,
            }
            for index, feature in enumerate(final_order, start=1)
        ]

        return {
            "ok": True,
            "model": model_name,
            "recommended_count": recommended_count,
            "best_count": best_count,
            "selected_count": requested_keep,
            "rows": ranked_rows,
            "curve": curve_rows,
        }

    def decision_boundary(
        self,
        model_name: str,
        x_feature: str = "",
        y_feature: str = "",
        resolution: int = 60,
    ) -> Dict[str, Any]:
        model = self._artifact(model_name)
        if model is None:
            return {"ok": False, "error": "No fitted model artifact found."}
        _, X_test, _, y_test = self._test_data()
        numeric_cols = [col for col in X_test.columns if pd.api.types.is_numeric_dtype(X_test[col])]
        if len(numeric_cols) < 2:
            return {"ok": False, "error": "Decision boundary requires at least two numeric features."}

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


EVAL = EvaluationService()
