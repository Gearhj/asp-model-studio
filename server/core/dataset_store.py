# server/core/dataset_store.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Tuple

import pandas as pd


@dataclass
class DatasetStore:
    """
    Central in-memory dataset registry for the DS Workflow backend.

    Responsibilities
    ---------------
    - Hold the *raw* dataset loaded in Step 1 (Data Acquisition).
    - Optionally hold a *processed* dataset after Steps 3–5
      (outliers, missing values, feature engineering).
    - Track the target column name.
    - Hold the final dev/train/test splits created in Step 6.
    - Provide helper methods used by metadata/EDA, splitting, and training.

    Design notes
    ------------
    - All setters copy DataFrames/Series to avoid accidental mutation.
    - Routers should be tolerant of `None` values and handle absence of data.
    """

    # Core datasets
    raw_df: Optional[pd.DataFrame] = None
    processed_df: Optional[pd.DataFrame] = None

    # Target column name (if known)
    target: Optional[str] = None

    # Splits created in Step 6
    X_train: Optional[pd.DataFrame] = None
    X_test: Optional[pd.DataFrame] = None
    y_train: Optional[pd.Series] = None
    y_test: Optional[pd.Series] = None

    # Optional place to hang arbitrary metadata if needed later
    meta: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Reset helpers
    # ------------------------------------------------------------------
    def reset_all(self) -> None:
        """
        Clear all stored data: raw/processed, target, splits, metadata.
        """
        self.raw_df = None
        self.processed_df = None
        self.target = None
        self.X_train = None
        self.X_test = None
        self.y_train = None
        self.y_test = None
        self.meta.clear()

    def reset_splits(self) -> None:
        """
        Clear only the dev/train/test splits (Step 6 outputs).
        """
        self.X_train = None
        self.X_test = None
        self.y_train = None
        self.y_test = None

    # ------------------------------------------------------------------
    # Core setters
    # ------------------------------------------------------------------
    def set_raw(self, df: pd.DataFrame) -> None:
        """
        Set the raw dataset (Step 1 output).

        This invalidates any processed dataset and any existing splits.
        """
        if df is None or df.empty:
            self.raw_df = None
            self.processed_df = None
            self.reset_splits()
            return

        self.raw_df = df.copy()
        self.processed_df = None
        self.reset_splits()

    def set_processed(self, df: pd.DataFrame) -> None:
        """
        Set the processed dataset (after Steps 3–5).

        This also invalidates existing splits since the feature space changed.
        """
        if df is None or df.empty:
            self.processed_df = None
            self.reset_splits()
            return

        self.processed_df = df.copy()
        self.reset_splits()

    def set_target(self, col_name: Optional[str]) -> None:
        """
        Set or clear the target column name.

        Routers should ensure the column actually exists before relying on it.
        """
        self.target = col_name

    def set_splits(
        self,
        X_train: Optional[pd.DataFrame],
        X_test: Optional[pd.DataFrame],
        y_train: Optional[pd.Series],
        y_test: Optional[pd.Series],
    ) -> None:
        """
        Store the dev/train/test splits created in Step 6.

        These are used by the training service in Step 7.
        """
        self.X_train = X_train.copy() if X_train is not None else None
        self.X_test = X_test.copy() if X_test is not None else None
        self.y_train = y_train.copy() if y_train is not None else None
        self.y_test = y_test.copy() if y_test is not None else None

    # ------------------------------------------------------------------
    # Core getters
    # ------------------------------------------------------------------
    def get_splits(self) -> Tuple[
        Optional[pd.DataFrame],
        Optional[pd.DataFrame],
        Optional[pd.Series],
        Optional[pd.Series],
    ]:
        """
        Return the four dev/train/test split components.

        Callers must handle None values.
        """
        return self.X_train, self.X_test, self.y_train, self.y_test


# Singleton instance used across the backend
DATASTORE = DatasetStore()
