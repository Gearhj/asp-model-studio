# server/splitting/split_service.py
# =============================================================================
# Split & Balancing Service for DS Workflow (Step06)
# =============================================================================
# This module encapsulates:
#   • Train/test splitting logic
#   • Optional undersampling for class imbalance
#   • Future hooks for SMOTE / class weights
#
# It does NOT know about FastAPI or DatasetStore directly; it operates on
# DataFrames/Series and a config dict.
# =============================================================================

from __future__ import annotations
from typing import Dict, Any, Tuple, Optional

import numpy as np
import pandas as pd

try:
    from sklearn.model_selection import train_test_split
except Exception:  # pragma: no cover
    train_test_split = None


class SplitService:
    """
    Service for creating train/test splits and applying simple imbalance handling.
    """

    def __init__(self):
        if train_test_split is None:
            raise ImportError("scikit-learn is required for splitting.")

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    def make_dev_split(
        self,
        df: pd.DataFrame,
        target_col: str,
        config: Dict[str, Any],
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, float]:
        """
        Create X_train, X_test, y_train, y_test based on the given config.

        Parameters
        ----------
        df : DataFrame
            Full dataset at Step06 (typically processed_df).
        target_col : str
            Name of the target column.
        config : dict
            {
              "split_strategy": "holdout" | "kfold",   # currently only holdout
              "k_folds": int,
              "balance_method": "none" | "undersample" | "smote" | "class_weight",
              "balance_ratio": "80/20",  # interpreted as maj/min for undersample
            }

        Returns
        -------
        X_train, X_test, y_train, y_test, test_size
        """
        if target_col not in df.columns:
            raise ValueError(f"Target column '{target_col}' not in dataset.")

        y = df[target_col]
        X = df.drop(columns=[target_col])

        # Split ratio for holdout
        split_strategy = str(config.get("split_strategy", "holdout")).lower()
        balance_method = str(config.get("balance_method", "none")).lower()
        balance_ratio = str(config.get("balance_ratio", "80/20"))

        test_size = 0.30  # default

        if split_strategy == "holdout":
            # Interpret "80/20" etc as train/test
            try:
                a_str, b_str = balance_ratio.split("/")
                a = float(a_str)
                b = float(b_str)
                total = a + b
                if total > 0 and b > 0:
                    test_size = b / total
            except Exception:
                # keep default 0.30 on parse failure
                pass

        # For now, "kfold" still uses a single holdout split; a future revision
        # can implement true K-fold cross-validation with OOF metrics.
        stratify = y if self._is_binary_series(y) else None

        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=test_size,
            random_state=42,
            stratify=stratify,
        )

        # Apply imbalance handling on training split
        if balance_method == "undersample" and self._is_binary_series(y_train):
            X_train, y_train = self._undersample_train(
                X_train, y_train, balance_ratio
            )

        # TODO: implement SMOTE / class_weight branches here in future phases.

        return X_train, X_test, y_train, y_test, float(test_size)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def _is_binary_series(s: pd.Series) -> bool:
        vals = s.dropna().unique()
        return len(vals) == 2

    @staticmethod
    def _undersample_train(
        X_train: pd.DataFrame,
        y_train: pd.Series,
        balance_ratio: str,
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Simple majority undersampling on the training split.

        balance_ratio: "80/20" etc interpreted as maj/min ratio.
        """
        y_arr = np.asarray(y_train)
        classes, counts = np.unique(y_arr, return_counts=True)

        if len(classes) < 2:
            return X_train, y_train

        maj_class = classes[np.argmax(counts)]
        min_class = classes[np.argmin(counts)]

        maj_idx = np.where(y_arr == maj_class)[0]
        min_idx = np.where(y_arr == min_class)[0]

        if len(maj_idx) == 0 or len(min_idx) == 0:
            return X_train, y_train

        # Parse desired ratio
        try:
            a_str, b_str = balance_ratio.split("/")
            a = float(a_str)
            b = float(b_str)
        except Exception:
            a, b = 80.0, 20.0

        if b <= 0:
            return X_train, y_train

        desired_maj = int(len(min_idx) * (a / b))
        desired_maj = max(1, min(desired_maj, len(maj_idx)))

        rng = np.random.default_rng(42)
        keep_maj = rng.choice(maj_idx, size=desired_maj, replace=False)
        keep_idx = np.concatenate([keep_maj, min_idx])

        # Reindex
        X_bal = X_train.iloc[keep_idx]
        y_bal = y_train.iloc[keep_idx]

        return X_bal, y_bal


# Singleton instance
split_service = SplitService()
