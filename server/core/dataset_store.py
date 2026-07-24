# server/core/dataset_store.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Tuple

import pandas as pd

# Only ever used for the project half of the scope key when no request has
# gone through authorize_modeling_scope() (server/core/modeling_scope.py) at
# all -- i.e. non-HTTP callers such as direct service-layer test scripts
# (tests/predictive_modeling_repair_test.py), or (since Stage 6) a legacy,
# pre-Stage-6 checkpoint file with no explicit scope of its own (server/
# core/session_checkpoint.py's LEGACY_SCOPE). A real authenticated HTTP
# request that reaches an affected endpoint without a valid project_id is
# rejected by authorize_modeling_scope() with 400/403/404 before DATASTORE
# is ever touched, so this sentinel never appears for a genuine project
# workflow request -- see modeling_scope.py's module docstring. Since
# Stage 6, a real (non-legacy) checkpoint restores every scope explicitly
# by its own recorded (user_id, project_id) -- this sentinel is no longer
# involved in ordinary restart restoration at all.
UNSCOPED_PROJECT = "unscoped"


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
        for key in (
            "processed_stage",
            "outlier_application",
            "missing_application",
            "missing_config",
            "materialized_feature_names",
            "feature_manifest",
            "split_record",
            "split_status",
        ):
            self.meta.pop(key, None)

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

    def get_selected_columns(self) -> list[str]:
        """
        Return the governed feature list selected on Data Acquisition.

        The list intentionally excludes the target. Routers should use this
        instead of raw_df.columns when the user has deselected variables.
        """
        selected = self.meta.get("selected_columns")
        if not isinstance(selected, list):
            return []

        out: list[str] = []
        seen: set[str] = set()
        target = str(self.target) if self.target else None
        for column in selected:
            name = str(column)
            if not name or name == target or name in seen:
                continue
            out.append(name)
            seen.add(name)
        return out

    def get_base_df(self) -> Optional[pd.DataFrame]:
        """
        Return processed_df when present, otherwise raw_df.
        """
        if self.processed_df is not None:
            return self.processed_df
        if self.raw_df is not None:
            return self.raw_df
        return None

    def get_raw_active_df(self, include_target: bool = True) -> Optional[pd.DataFrame]:
        """Return the governed modeling columns from the registered source frame."""
        if self.raw_df is None or self.raw_df.empty:
            return self.raw_df

        selected = [column for column in self.get_selected_columns() if column in self.raw_df.columns]
        if not selected:
            return self.raw_df.copy()

        keep = list(selected)
        if include_target and self.target and self.target in self.raw_df.columns and self.target not in keep:
            keep.append(self.target)
        return self.raw_df.loc[:, keep].copy()

    def get_active_df(self, include_target: bool = True) -> Optional[pd.DataFrame]:
        """
        Return the current dataset restricted to selected modeling features.

        This is the canonical downstream view after Data Acquisition. The raw
        uploaded file may contain columns the user deselected; those columns
        should not leak into EDA, preprocessing, splitting, or training.
        """
        df = self.get_base_df()
        if df is None or df.empty:
            return df

        selected = [column for column in self.get_selected_columns() if column in df.columns]
        if not selected:
            return df.copy()

        keep = list(selected)
        if include_target and self.target and self.target in df.columns and self.target not in keep:
            keep.append(self.target)

        return df.loc[:, keep].copy()

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


# Keyed by an explicit (user_id, project_id) tuple -- not a concatenated
# string -- so there is no possible delimiter-collision between a user_id
# and a project_id that happened to contain the same separator character.
# Stage 2B: previously keyed by user_id alone (a plain str); that scheme is
# retired outright, not migrated -- see modeling_scope.py's module docstring
# and the delivery report's "Backward compatibility" section. _DATASTORES is
# a purely in-memory, process-lifetime cache (never persisted except via the
# separate, unmodified checkpoint mechanism), so a deploy of this change
# naturally starts every process with an empty dict; there is no old-format
# data to migrate or that could leak into a new-format lookup, because a
# 2-tuple key can never equal an old bare-string key.
_DATASTORES: Dict[Tuple[str, str], DatasetStore] = {}


def _scope_key() -> Tuple[str, str]:
    try:
        from ..security.security_store import active_user

        user = active_user() or {}
        user_id = str(user.get("userId") or "anonymous")
    except Exception:
        user_id = "anonymous"
    try:
        from .modeling_scope import active_project_id

        project_id = active_project_id() or UNSCOPED_PROJECT
    except Exception:
        project_id = UNSCOPED_PROJECT
    return (user_id, project_id)


def get_scoped_dataset_store(scope: Optional[Tuple[str, str]] = None) -> DatasetStore:
    """Look up (or lazily create) the DatasetStore for a scope.

    `scope`, when given, must be an explicit (user_id, project_id) tuple --
    this is the "preserve explicit test helpers for inspecting a specific
    scope" affordance; it bypasses contextvars entirely, which is exactly
    why it's useful for tests and for the rare internal caller that already
    knows precisely which scope it means. Real request handling always goes
    through the default (ambient, contextvar-resolved) path.
    """
    key = scope or _scope_key()
    if key not in _DATASTORES:
        _DATASTORES[key] = DatasetStore()
    return _DATASTORES[key]


def discard_scoped_dataset_store(scope: Tuple[str, str]) -> bool:
    """Drop one (user_id, project_id) scope from the in-memory registry.

    Stage 6.1 lifecycle repair: scopes used to live for the whole process
    lifetime even after their project was deleted, and save_checkpoint()
    re-serialized every resident scope on every save -- deleted projects
    therefore kept growing the checkpoint forever. Callers should go through
    session_checkpoint.discard_modeling_scopes(), which removes the matching
    DATASTORE and RESULTS scopes together.
    """
    return _DATASTORES.pop(scope, None) is not None


class DatasetStoreProxy:
    def current(self) -> DatasetStore:
        return get_scoped_dataset_store()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.current(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_ignored":
            super().__setattr__(name, value)
            return
        setattr(self.current(), name, value)


# Context-aware singleton facade used across the backend.
DATASTORE = DatasetStoreProxy()
