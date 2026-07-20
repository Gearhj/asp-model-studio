from datetime import datetime
from typing import Any, Dict, List, Tuple
import re

from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.result_store import RESULTS
from .trainer import MODEL_CATALOG, train_models


class TrainerService:
    """
    Service behind /api/model/train.

    This calls the real training engine in trainer.py using only the explicit,
    current validation split approved in Balance & Split.
    """

    MODEL_LABELS: Dict[str, str] = {
        key: spec.get("label", key) for key, spec in MODEL_CATALOG.items()
    }

    def _normalized(self, value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")

    def _target_aliases(self, target: str = "") -> set[str]:
        aliases = {
            self._normalized(target),
            self._normalized(DATASTORE.target),
        }
        source = DATASTORE.meta.get("source") if isinstance(DATASTORE.meta, dict) else {}
        if isinstance(source, dict):
            for key in ("target", "targetColumn", "originalTargetLabelColumn", "originalTargetLabel", "labelColumn"):
                aliases.add(self._normalized(source.get(key)))
        return {alias for alias in aliases if alias}

    def _is_target_derived_feature(self, column: Any, target: str = "") -> bool:
        name = self._normalized(column)
        if not name:
            return True
        for alias in self._target_aliases(target):
            if name == alias or name.startswith(f"{alias}_"):
                return True
        return False

    def _sanitize_feature_frame(self, frame, target: str = ""):
        if frame is None:
            return frame, []
        keep = [col for col in frame.columns if not self._is_target_derived_feature(col, target)]
        dropped = [str(col) for col in frame.columns if col not in keep]
        if not keep:
            raise ValueError("No usable feature columns remain after excluding target-derived fields.")
        return frame.loc[:, keep].copy(), dropped

    def _current_dataset_and_target(self):
        df = DATASTORE.get_active_df()
        if df is None or df.empty:
            raise ValueError("No dataset is loaded. Return to Data Acquisition and load a dataset first.")

        target = DATASTORE.target
        if not target or target not in df.columns:
            target = self._infer_target(df)
        if not target or target not in df.columns:
            raise ValueError("Target column is not set. Return to Data Acquisition and select a target.")

        return df, target

    def _infer_target(self, df):
        common = {"fraud", "target", "label", "class", "y", "bad", "default", "outcome", "response", "event"}
        for col in df.columns:
            if str(col).strip().lower() in common:
                DATASTORE.set_target(str(col))
                return str(col)
        for col in reversed(list(df.columns)):
            s = df[col].dropna()
            if s.empty:
                continue
            if 1 < len(s.unique()) <= 2:
                DATASTORE.set_target(str(col))
                return str(col)
        return None

    def _get_or_create_splits(self, k_folds: int) -> Tuple[Any, Any, Any, Any, List[str]]:
        """Compatibility name retained for callers; hidden split creation is prohibited."""
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if any(part is None for part in (X_train, X_test, y_train, y_test)):
            raise ValueError("A governed validation split has not been created. Return to Balance & Split.")
        if str(DATASTORE.meta.get("split_status") or "not_created") != "current":
            raise ValueError("The governed validation split is stale. Rebuild it in Balance & Split.")

        active_target = str(DATASTORE.target or getattr(y_train, "name", "") or "")
        manifest = DATASTORE.meta.get("feature_manifest") if isinstance(DATASTORE.meta.get("feature_manifest"), dict) else {}
        governed = [
            str(row.get("feature_name"))
            for row in manifest.get("features", [])
            if isinstance(row, dict) and row.get("selected") and row.get("eligibility_status") == "eligible"
        ]
        if not governed:
            governed = DATASTORE.get_selected_columns()
        missing = [column for column in governed if column not in X_train.columns or column not in X_test.columns]
        unexpected = [column for column in X_train.columns if governed and column not in governed]
        if missing:
            raise ValueError("The training split is missing approved predictors: " + ", ".join(missing))
        if unexpected:
            raise ValueError("The training split contains predictors outside the approved manifest: " + ", ".join(map(str, unexpected)))
        if governed:
            X_train = X_train.loc[:, governed].copy()
            X_test = X_test.loc[:, governed].copy()
        X_train, dropped_train = self._sanitize_feature_frame(X_train, active_target)
        X_test, dropped_test = self._sanitize_feature_frame(X_test, active_target)
        dropped = sorted(set(dropped_train + dropped_test))
        if dropped:
            raise ValueError("Target-derived fields reached the training contract: " + ", ".join(dropped))
        return X_train, X_test, y_train, y_test, []

    def get_availability(self) -> Dict[str, Any]:
        availability: Dict[str, bool] = {}
        labels: Dict[str, str] = {}

        for key, spec in MODEL_CATALOG.items():
            labels[key] = spec.get("label", key)
            factory = spec.get("factory")
            try:
                availability[key] = bool(factory and factory() is not None)
            except Exception:
                availability[key] = False

        RESULTS.set_model_availability(availability)
        return {"availability": availability, "labels": labels}

    def train(
        self,
        models: List[str],
        k_folds: int = 5,
        max_parallel: int = 1,
        calibrate: bool = False,
        use_pca: bool = False,
        grid_search: bool = False,
        grid_search_level: str = "quick",
        model_params: Dict[str, Dict[str, Any]] | None = None,
        project_id: str = "",
        dataset_version: str = "",
        target: str = "",
        problem_type: str = "",
    ) -> Dict[str, Any]:
        X_train, X_test, y_train, y_test, excluded_target_features = self._get_or_create_splits(k_folds)

        result = train_models(
            X_train=X_train,
            X_test=X_test,
            y_train=y_train,
            y_test=y_test,
            requested_models=models,
            grid_search=grid_search,
            grid_search_level=grid_search_level,
            model_params=model_params or {},
            calibrate=calibrate,
        )
        if not result.get("ok"):
            raise ValueError(result.get("error") or "No models were successfully trained.")

        summary = result["summary"]
        artifacts = summary.pop("_artifacts", {})
        detected_problem_type = str(summary.get("problem_type") or problem_type or "")
        active_target = str(target or DATASTORE.target or getattr(y_train, "name", "") or "")
        training_run_id = f"train-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        artifact_metadata = {
            key: {
                "project_id": str(project_id or ""),
                "dataset_version": str(dataset_version or ""),
                "target": active_target,
                "problem_type": detected_problem_type,
                "model_key": key,
                "training_run_id": training_run_id,
                "trained_at": datetime.now().isoformat(),
            }
            for key in artifacts.keys()
        }
        summary.update(
            {
                "project_id": str(project_id or ""),
                "dataset_version": str(dataset_version or ""),
                "target": active_target,
                "training_run_id": training_run_id,
                "n_train": int(len(y_train)),
                "n_test": int(len(y_test)),
                "n_features": int(X_train.shape[1]),
                "trained_feature_names": [str(column) for column in X_train.columns],
                "excluded_target_features": excluded_target_features,
                "k_folds": int(k_folds),
                "max_parallel": int(max_parallel),
                "calibrate": bool(calibrate),
                "use_pca": bool(use_pca),
                "grid_search": bool(grid_search),
                "grid_search_level": str(grid_search_level),
                "model_params": model_params or {},
                "status": "trained",
            }
        )

        RESULTS.set_model_artifacts(artifacts, artifact_metadata)
        safe_summary = json_safe(summary)
        RESULTS.set_last_summary(safe_summary)
        return safe_summary


TRAINER = TrainerService()
