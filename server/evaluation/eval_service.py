from typing import Any, Dict, List, Tuple
from datetime import datetime
import pickle
import re

import numpy as np
import pandas as pd

from ..core.dataset_store import DATASTORE
from ..core.result_store import RESULTS

try:
    from sklearn.metrics import (
        accuracy_score,
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
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.decomposition import PCA
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.neighbors import NearestNeighbors
    from sklearn.preprocessing import LabelEncoder
except Exception:  # pragma: no cover
    accuracy_score = None
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
    LinearRegression = None
    LogisticRegression = None
    PCA = None
    KMeans = None
    silhouette_score = None
    NearestNeighbors = None
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

    def _artifact(self, model_name: str):
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
        if isinstance(model, dict) and model.get("kind") == "rfe_logistic":
            prepared, _, _ = self._prepare_final_feature_frame(model, X)
            return np.asarray(model["model"].predict_proba(prepared)[:, 1], dtype=float)
        if isinstance(model, dict) and model.get("kind") == "rfe_regression":
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

    def decision_tree(self, model_name: str, max_depth: int = 4) -> Dict[str, Any]:
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
        if not estimator.__class__.__name__.lower().startswith("decisiontree"):
            return {"ok": False, "error": "The selected model is not a decision tree."}
        tree = getattr(estimator, "tree_", None)
        if tree is None:
            return {"ok": False, "error": "Decision tree structure is unavailable."}

        feature_names = [str(name).replace("num__", "").replace("cat__", "") for name in names]
        classes = [str(item) for item in getattr(estimator, "classes_", [])]
        max_depth = max(1, min(int(max_depth or 4), 5))
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []

        def walk(node_id: int, depth: int, x_min: float, x_max: float) -> None:
            left = int(tree.children_left[node_id])
            right = int(tree.children_right[node_id])
            samples = int(tree.n_node_samples[node_id])
            values = np.asarray(tree.value[node_id]).ravel()
            total = float(values.sum()) or 1.0
            positive_rate = float(values[-1] / total) if len(values) else 0.0
            predicted_index = int(np.argmax(values)) if len(values) else 0
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
                    "prediction": classes[predicted_index] if predicted_index < len(classes) else str(predicted_index),
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
        return {"ok": True, "nodes": nodes, "edges": edges, "max_depth": max_depth}

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

    def sensitivity_summary(self, model_name: str, top_n: int = 12) -> Dict[str, Any]:
        if model_name in ("final", "final_rfe"):
            model = RESULTS.get_final_model()
            final_metadata = RESULTS.get_final_model_metadata() or {}
            final_features = [
                str(feature)
                for feature in (final_metadata.get("features") or [])
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
            series = X_test[feature]
            scenarios: List[Dict[str, Any]] = []
            if pd.api.types.is_numeric_dtype(series):
                numeric = pd.to_numeric(series, errors="coerce")
                if numeric.dropna().empty:
                    continue
                for pct in [-0.2, -0.1, 0.1, 0.2]:
                    x_mod = X_test.copy()
                    x_mod[feature] = numeric * (1 + pct)
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
            rows.append(
                {
                    "feature": feature,
                    "baseline": baseline,
                    "max_abs_delta": abs(float(max_row["delta"])),
                    "worst_scenario": max_row["scenario"],
                    "worst_prediction": max_row["prediction"],
                    "worst_delta": max_row["delta"],
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

    def rfe(self, model_name: str = "", keep: int = 10) -> Dict[str, Any]:
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if X_train is None or X_test is None or y_train is None or y_test is None:
            return {"ok": False, "error": "No training split is available. Train models first."}
        prepared_train_all, prepared_test_all, feature_cols = self._prepare_rfe_design(X_train, X_test)
        if len(feature_cols) < 2:
            return {"ok": False, "error": "RFE requires at least two usable features after encoding. Confirm feature selection and preprocessing."}
        if self._is_regression_problem():
            return self._rfe_regression(
                model_name=model_name,
                keep=keep,
                numeric_cols=feature_cols,
                prepared_train=prepared_train_all,
                prepared_test=prepared_test_all,
            )
        if LogisticRegression is None or LabelEncoder is None or roc_auc_score is None:
            return {"ok": False, "error": "scikit-learn logistic regression metrics are unavailable."}

        numeric_cols = list(feature_cols)
        if len(numeric_cols) > 20:
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
                for row in sorted(single_feature_scores, key=lambda row: row["auc"], reverse=True)[:20]
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
    ) -> Dict[str, Any]:
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if LinearRegression is None:
            return {"ok": False, "error": "scikit-learn LinearRegression is unavailable."}
        if prepared_train is None or prepared_test is None:
            prepared_train, prepared_test, numeric_cols = self._prepare_rfe_design(X_train, X_test)

        y_train_arr = pd.to_numeric(pd.Series(y_train), errors="coerce").to_numpy(dtype=float)
        y_test_arr = pd.to_numeric(pd.Series(y_test), errors="coerce").to_numpy(dtype=float)
        if len(numeric_cols) > 24:
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
                for row in sorted(single_feature_scores, key=lambda row: row["rmse"])[:24]
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
            "rows": ranked_rows,
            "curve": curve_rows,
        }

    def save_rfe_model(self, model_name: str = "", keep: int = 10) -> Dict[str, Any]:
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if X_train is None or X_test is None or y_train is None or y_test is None:
            return {"ok": False, "error": "No training split is available. Train models first."}
        if self._is_regression_problem():
            return self._save_rfe_regression_model(model_name=model_name, keep=keep)
        if LogisticRegression is None:
            return {"ok": False, "error": "scikit-learn LogisticRegression is unavailable."}

        rfe_result = self.rfe(model_name=model_name, keep=keep)
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

        final_estimator = LogisticRegression(max_iter=3000, n_jobs=1, class_weight="balanced")
        final_estimator.fit(train_scaled[selected_features], y_train_arr)
        scores = final_estimator.predict_proba(test_scaled[selected_features])[:, 1]
        auc = float(roc_auc_score(y_test_arr, scores)) if roc_auc_score is not None else None

        artifact = {
            "kind": "rfe_logistic",
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
            "name": "Final Parsimonious RFE Logistic Model",
            "feature_count": len(selected_features),
            "features": selected_features,
            "holdout_auc": auc,
        }
        RESULTS.set_final_model(artifact, metadata)
        return {"ok": True, "metadata": metadata}

    def _save_rfe_regression_model(self, model_name: str = "", keep: int = 10) -> Dict[str, Any]:
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if LinearRegression is None:
            return {"ok": False, "error": "scikit-learn LinearRegression is unavailable."}

        rfe_result = self.rfe(model_name=model_name, keep=keep)
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
        final_estimator = LinearRegression()
        final_estimator.fit(train_scaled[selected_features], y_train_arr)
        preds = final_estimator.predict(test_scaled[selected_features])
        metrics = self._regression_metrics(pd.Series(y_test_arr), preds, n_features=len(selected_features))

        artifact = {
            "kind": "rfe_regression",
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
            "name": "Final Parsimonious RFE Regression Model",
            "problem_type": "regression",
            "feature_count": len(selected_features),
            "features": selected_features,
            "metrics": metrics,
            "holdout_rmse": metrics.get("rmse"),
            "holdout_r2": metrics.get("r2"),
            "holdout_adjusted_r2": metrics.get("adjusted_r2"),
        }
        RESULTS.set_final_model(artifact, metadata)
        return {"ok": True, "metadata": metadata}

    def save_selected_model_as_final(self, model_name: str = "") -> Dict[str, Any]:
        summary = RESULTS.get_last_summary() or {}
        ranked = summary.get("ranked") or []
        if not model_name:
            model_name = ranked[0].get("key") if ranked else ""
        artifact = self._artifact(model_name)
        if artifact is None:
            return {"ok": False, "error": "No fitted model artifact found for the selected model."}
        row = next((item for item in ranked if item.get("key") == model_name), {})
        X_train, _, _, _ = DATASTORE.get_splits()
        metadata = {
            "source_model": model_name,
            "model_key": model_name,
            "name": row.get("name") or model_name,
            "problem_type": summary.get("problem_type"),
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
            df = DATASTORE.processed_df if DATASTORE.processed_df is not None else DATASTORE.raw_df
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
                return final_model, metadata
        artifact = self._artifact(model_name)
        if artifact is None:
            ranked = (RESULTS.get_last_summary() or {}).get("ranked") or []
            default_key = ranked[0].get("key") if ranked else ""
            artifact = self._artifact(default_key)
            model_name = default_key
        if artifact is None:
            raise ValueError("No model artifact is available for scoring.")
        return artifact, {"model_key": model_name, "name": model_name}

    def export_model_bundle(self, model_name: str = "final") -> Tuple[bytes, str]:
        model, metadata = self._resolve_scoring_model(model_name)
        summary = RESULTS.get_last_summary() or {}
        X_train, _, _, _ = DATASTORE.get_splits()
        ranked = summary.get("ranked") or []
        selected_key = metadata.get("model_key") or model_name
        selected_summary = next((row for row in ranked if row.get("key") == selected_key), {})
        bundle = {
            "model": model,
            "metadata": {
                **metadata,
                "target": DATASTORE.target,
                "problem_type": summary.get("problem_type"),
                "feature_columns": list(X_train.columns) if X_train is not None else metadata.get("features", []),
                "selected_model_summary": selected_summary,
                "exported_at": datetime.now().isoformat(),
                "export_format": "pickle",
                "scoring_note": "Load bundle['model'] and call predict or predict_proba through the fitted preprocessing pipeline.",
            },
        }
        raw_name = str(metadata.get("name") or selected_key or "model")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_name).strip("_").lower() or "model"
        return pickle.dumps(bundle), f"{safe_name}_bundle.pkl"

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
        model, metadata = self._resolve_scoring_model(model_name)
        target = DATASTORE.target
        y_true = None
        X = df.copy()
        if target and target in X.columns:
            y_true = X[target].copy()
            X = X.drop(columns=[target])

        task = "regression" if self._is_regression_problem() else "classification"
        model_features = [str(feature) for feature in (metadata.get("features") or [])]
        matched_features: List[str] = []
        missing_features: List[str] = []
        if isinstance(model, dict) and model.get("kind") in ("rfe_logistic", "rfe_regression"):
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
            "preview": [
                {"row": int(i + 1), "score": float(score), "adjusted_score": float(adjusted), "prediction": float(label)}
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
                        "accuracy": float(accuracy_score(y_arr, labels)) if accuracy_score is not None else None,
                        "precision": float(precision_score(y_arr, labels, zero_division=0)) if precision_score is not None else None,
                        "recall": float(recall_score(y_arr, labels, zero_division=0)) if recall_score is not None else None,
                        "f1": float(f1_score(y_arr, labels, zero_division=0)) if f1_score is not None else None,
                        "confusion": confusion_matrix(y_arr, labels).tolist() if confusion_matrix is not None else None,
                    }
                    response["lift"] = self._lift_table(y_true, adjusted_scores)
            except Exception as exc:
                response["metrics_error"] = str(exc)

        if dataset_type.lower() == "oot":
            X_train, X_test, _, _ = DATASTORE.get_splits()
            scoring_reference = RESULTS.get_scoring_reference() or {}
            reference = scoring_reference.get("X")
            reference_scores = scoring_reference.get("scores")
            reference_kind = scoring_reference.get("kind")
            if reference is None:
                reference = X_train if X_train is not None else X_test
            if reference is not None:
                ref_scores = (
                    np.asarray(reference_scores, dtype=float)
                    if reference_scores is not None
                    else self._prior_correct_scores(
                        self._predict_score(model, reference),
                        correction_method,
                        original_prior,
                        model_prior,
                    )
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
                response["stability_reference"] = "uploaded_test" if reference_kind == "uploaded_test" else "development_split"
        return response

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


EVAL = EvaluationService()
