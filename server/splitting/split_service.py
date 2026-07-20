from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split


@dataclass(frozen=True)
class SplitResult:
    X_train: pd.DataFrame
    X_test: pd.DataFrame
    y_train: pd.Series
    y_test: pd.Series
    original_train_rows: int
    original_train_distribution: dict[str, Any]
    applied_train_distribution: dict[str, Any]
    test_distribution: dict[str, Any]


def target_distribution(series: pd.Series, event_value: Any | None = None) -> dict[str, Any]:
    values = series.dropna()
    counts = values.value_counts(dropna=False)
    result: dict[str, Any] = {
        "rows": int(len(series)),
        "valid_rows": int(len(values)),
        "missing_rows": int(series.isna().sum()),
        "classes": {str(label): int(count) for label, count in counts.items()},
    }
    if len(counts) != 2:
        result.update({"event_value": event_value, "events": None, "non_events": None, "event_rate": None})
        return result

    labels = list(counts.index)
    resolved_event = event_value
    if resolved_event is None or not any(str(label) == str(resolved_event) for label in labels):
        resolved_event = next((label for label in labels if str(label).strip() == "1"), labels[-1])
    event_label = next(label for label in labels if str(label) == str(resolved_event))
    events = int(counts[event_label])
    result.update({
        "event_value": event_label.item() if hasattr(event_label, "item") else event_label,
        "events": events,
        "non_events": int(len(values) - events),
        "event_rate": float(events / len(values)) if len(values) else None,
    })
    return result


class SplitService:
    """Create an explicit governed holdout and optionally balance training rows only."""

    def make_dev_split(
        self,
        frame: pd.DataFrame,
        target_col: str,
        selected_features: list[str],
        config: dict[str, Any],
    ) -> SplitResult:
        if target_col not in frame.columns:
            raise ValueError(f"Target column '{target_col}' is not available in the full dataset.")
        if config.get("split_strategy", "holdout") != "holdout":
            raise ValueError("Only explicit holdout splitting is available on this page. Cross-validation is configured during Model Training.")

        missing_features = [name for name in selected_features if name not in frame.columns]
        if missing_features:
            raise ValueError("Selected features are not materialized: " + ", ".join(missing_features))
        if not selected_features:
            raise ValueError("Select at least one eligible predictor before creating a split.")

        test_size = float(config.get("test_size", 0.2))
        if not 0.1 <= test_size <= 0.5:
            raise ValueError("Holdout size must be between 10% and 50%.")
        random_seed = int(config.get("random_seed", 42))
        problem_type = str(config.get("problem_type") or "classification")
        event_value = config.get("event_value")

        X = frame.loc[:, selected_features].copy()
        y = frame[target_col].copy()
        if y.isna().any():
            valid = y.notna()
            X = X.loc[valid]
            y = y.loc[valid]
        if len(y) < 4:
            raise ValueError("At least four valid target rows are required to create a development split.")

        stratify = None
        if problem_type == "classification" and bool(config.get("stratify", True)):
            counts = y.value_counts()
            if len(counts) < 2:
                raise ValueError("The target contains one class. A stratified holdout cannot be created.")
            if int(counts.min()) < 2:
                raise ValueError("The minority class has fewer than two records. Both train and holdout sets need at least one event.")
            stratify = y

        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=test_size,
            random_state=random_seed,
            stratify=stratify,
        )

        original_train = target_distribution(y_train, event_value)
        test_distribution = target_distribution(y_test, event_value)
        if problem_type == "classification" and len(y.value_counts()) == 2:
            if not original_train.get("events") or not test_distribution.get("events"):
                raise ValueError("The proposed split leaves train or holdout without an event. Increase the data or change the holdout size.")

        original_train_rows = int(len(y_train))
        balance_method = str(config.get("balance_method") or "none")
        if balance_method == "undersample":
            if problem_type != "classification" or len(y_train.value_counts()) != 2:
                raise ValueError("Training-only undersampling requires a binary classification target.")
            X_train, y_train = self._undersample_train(
                X_train,
                y_train,
                minority_share=float(config.get("minority_share", 0.5)),
                random_seed=random_seed,
            )
        elif balance_method == "oversample":
            if problem_type != "classification" or len(y_train.value_counts()) != 2:
                raise ValueError("Training-only oversampling requires a binary classification target.")
            X_train, y_train = self._oversample_train(
                X_train,
                y_train,
                minority_share=float(config.get("minority_share", 0.5)),
                random_seed=random_seed,
            )
        elif balance_method == "smote":
            if problem_type != "classification" or len(y_train.value_counts()) != 2:
                raise ValueError("Training-only SMOTE requires a binary classification target.")
            X_train, y_train = self._smote_train(
                X_train,
                y_train,
                minority_share=float(config.get("minority_share", 0.5)),
                random_seed=random_seed,
            )
        elif balance_method != "none":
            raise ValueError(f"Balancing method '{balance_method}' is not implemented by the split backend.")

        return SplitResult(
            X_train=X_train,
            X_test=X_test,
            y_train=y_train,
            y_test=y_test,
            original_train_rows=original_train_rows,
            original_train_distribution=original_train,
            applied_train_distribution=target_distribution(y_train, event_value),
            test_distribution=test_distribution,
        )

    @staticmethod
    def _undersample_train(
        X_train: pd.DataFrame,
        y_train: pd.Series,
        minority_share: float,
        random_seed: int,
    ) -> tuple[pd.DataFrame, pd.Series]:
        if not 0.05 <= minority_share <= 0.5:
            raise ValueError("The requested minority share must be between 5% and 50%.")
        counts = y_train.value_counts()
        minority_label = counts.idxmin()
        majority_label = counts.idxmax()
        minority_index = y_train.index[y_train == minority_label].to_numpy()
        majority_index = y_train.index[y_train == majority_label].to_numpy()
        desired_majority = int(len(minority_index) * (1 - minority_share) / minority_share)
        desired_majority = max(1, min(desired_majority, len(majority_index)))
        rng = np.random.default_rng(random_seed)
        selected_majority = rng.choice(majority_index, size=desired_majority, replace=False)
        selected_index = np.concatenate([minority_index, selected_majority])
        rng.shuffle(selected_index)
        return X_train.loc[selected_index].copy(), y_train.loc[selected_index].copy()

    @staticmethod
    def _oversample_train(
        X_train: pd.DataFrame,
        y_train: pd.Series,
        minority_share: float,
        random_seed: int,
    ) -> tuple[pd.DataFrame, pd.Series]:
        if not 0.05 <= minority_share <= 0.5:
            raise ValueError("The requested minority share must be between 5% and 50%.")
        counts = y_train.value_counts()
        minority_label = counts.idxmin()
        majority_label = counts.idxmax()
        minority_index = y_train.index[y_train == minority_label].to_numpy()
        majority_count = int(counts[majority_label])
        desired_minority = int(np.ceil(majority_count * minority_share / (1 - minority_share)))
        additional_rows = max(0, desired_minority - len(minority_index))
        if additional_rows == 0:
            return X_train.copy(), y_train.copy()

        rng = np.random.default_rng(random_seed)
        sampled_index = rng.choice(minority_index, size=additional_rows, replace=True)
        synthetic_index = [f"oversample_{idx}" for idx in range(additional_rows)]
        X_extra = X_train.loc[sampled_index].copy()
        X_extra.index = synthetic_index
        y_extra = pd.Series([minority_label] * additional_rows, index=synthetic_index, name=y_train.name)
        X_out = pd.concat([X_train.copy(), X_extra], axis=0)
        y_out = pd.concat([y_train.copy(), y_extra], axis=0)
        return X_out, y_out

    @staticmethod
    def _smote_train(
        X_train: pd.DataFrame,
        y_train: pd.Series,
        minority_share: float,
        random_seed: int,
    ) -> tuple[pd.DataFrame, pd.Series]:
        if not 0.05 <= minority_share <= 0.5:
            raise ValueError("The requested minority share must be between 5% and 50%.")
        counts = y_train.value_counts()
        minority_label = counts.idxmin()
        majority_label = counts.idxmax()
        minority_rows = X_train.loc[y_train == minority_label].copy()
        majority_count = int(counts[majority_label])
        desired_minority = int(np.ceil(majority_count * minority_share / (1 - minority_share)))
        additional_rows = max(0, desired_minority - len(minority_rows))
        if additional_rows == 0:
            return X_train.copy(), y_train.copy()
        if len(minority_rows) < 2:
            raise ValueError("SMOTE requires at least two minority-class training records.")

        rng = np.random.default_rng(random_seed)
        numeric_columns = minority_rows.select_dtypes(include=[np.number]).columns.tolist()
        if not numeric_columns:
            raise ValueError("SMOTE requires at least one numeric predictor. Use minority oversampling instead.")

        synthetic_index = [f"smote_{idx}" for idx in range(additional_rows)]
        base_positions = rng.integers(0, len(minority_rows), size=additional_rows)
        peer_positions = rng.integers(0, len(minority_rows) - 1, size=additional_rows)
        peer_positions = np.where(peer_positions >= base_positions, peer_positions + 1, peer_positions)

        X_extra = minority_rows.iloc[base_positions].reset_index(drop=True).copy()
        peer_rows = minority_rows.iloc[peer_positions].reset_index(drop=True)
        interpolation_weights = rng.random(additional_rows)
        base_numeric = X_extra.loc[:, numeric_columns].apply(pd.to_numeric, errors="coerce").astype(float).to_numpy()
        peer_numeric = peer_rows.loc[:, numeric_columns].apply(pd.to_numeric, errors="coerce").astype(float).to_numpy()
        X_extra.loc[:, numeric_columns] = base_numeric + interpolation_weights[:, None] * (peer_numeric - base_numeric)
        X_extra.index = synthetic_index
        y_extra = pd.Series([minority_label] * additional_rows, index=synthetic_index, name=y_train.name)
        X_out = pd.concat([X_train.copy(), X_extra], axis=0, copy=False)
        y_out = pd.concat([y_train.copy(), y_extra], axis=0, copy=False)
        return X_out, y_out


split_service = SplitService()
