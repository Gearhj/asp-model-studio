from typing import Any, Dict, List, Tuple

from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.result_store import RESULTS
from ..splitting.split_service import split_service
from .trainer import MODEL_CATALOG, train_models


class TrainerService:
    """
    Service behind /api/model/train.

    This calls the real training engine in trainer.py. If Step 6 has not
    materialized splits yet, it creates a conservative holdout split from the
    current loaded dataset so the Train Selected button performs actual fits.
    """

    MODEL_LABELS: Dict[str, str] = {
        key: spec.get("label", key) for key, spec in MODEL_CATALOG.items()
    }

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

    def _get_or_create_splits(self, k_folds: int) -> Tuple[Any, Any, Any, Any]:
        X_train, X_test, y_train, y_test = DATASTORE.get_splits()
        if X_train is not None and X_test is not None and y_train is not None and y_test is not None:
            return X_train, X_test, y_train, y_test

        df, target = self._current_dataset_and_target()
        X_train, X_test, y_train, y_test, _ = split_service.make_dev_split(
            df,
            target,
            {
                "split_strategy": "kfold" if k_folds > 2 else "holdout",
                "k_folds": int(k_folds),
                "balance_method": "none",
                "balance_ratio": "80/20",
            },
        )
        DATASTORE.set_splits(X_train, X_test, y_train, y_test)
        return X_train, X_test, y_train, y_test

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
    ) -> Dict[str, Any]:
        X_train, X_test, y_train, y_test = self._get_or_create_splits(k_folds)

        result = train_models(
            X_train=X_train,
            X_test=X_test,
            y_train=y_train,
            y_test=y_test,
            requested_models=models,
            grid_search=grid_search,
            grid_search_level=grid_search_level,
            model_params=model_params or {},
        )
        if not result.get("ok"):
            raise ValueError(result.get("error") or "No models were successfully trained.")

        summary = result["summary"]
        artifacts = summary.pop("_artifacts", {})
        summary.update(
            {
                "n_train": int(len(y_train)),
                "n_test": int(len(y_test)),
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

        RESULTS.set_model_artifacts(artifacts)
        safe_summary = json_safe(summary)
        RESULTS.set_last_summary(safe_summary)
        return safe_summary


TRAINER = TrainerService()
