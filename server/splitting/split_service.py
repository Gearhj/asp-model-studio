from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import (
    GroupKFold,
    KFold,
    RepeatedStratifiedKFold,
    StratifiedGroupKFold,
    StratifiedKFold,
    TimeSeriesSplit,
    train_test_split,
)


@dataclass(frozen=True)
class SplitResult:
    X_train: pd.DataFrame
    X_test: pd.DataFrame | None
    y_train: pd.Series
    y_test: pd.Series | None
    original_train_rows: int
    original_train_distribution: dict[str, Any]
    applied_train_distribution: dict[str, Any]
    test_distribution: dict[str, Any]
    fold_architecture: dict[str, Any]
    training_index: list[Any]
    validation_index: list[Any]
    synthetic_rows_added: int
    rows_removed: int
    evaluation_population_role: str
    fold_local_preprocessing: str
    balancing_application_status: str
    sealed_holdout_rows: int


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
    """Materialize governed validation populations and training-only balancing."""

    def make_dev_split(
        self,
        frame: pd.DataFrame,
        target_col: str,
        selected_features: list[str],
        config: dict[str, Any],
    ) -> SplitResult:
        return self.make_validation_split(
            frame,
            target_col,
            selected_features,
            config,
        )

    def make_validation_split(
        self,
        frame: pd.DataFrame,
        target_col: str,
        selected_features: list[str],
        config: dict[str, Any],
        external_test_frame: pd.DataFrame | None = None,
        external_test_target: str | None = None,
        prepartitioned_development: pd.DataFrame | None = None,
        prepartitioned_holdout: pd.DataFrame | None = None,
        prepartitioned_development_target: pd.Series | None = None,
        prepartitioned_holdout_target: pd.Series | None = None,
        sealed_holdout_row_count: int | None = None,
    ) -> SplitResult:
        if target_col not in frame.columns:
            raise ValueError(f"Target column '{target_col}' is not available in the full dataset.")
        strategy = str(config.get("split_strategy") or "holdout")
        supported = {
            "holdout",
            "holdout_current",
            "separate_test",
            "separate_test_oot",
            "cross_validation",
            "hybrid",
        }
        if strategy not in supported:
            raise ValueError(f"Validation strategy '{strategy}' is not supported.")

        missing_features = [name for name in selected_features if name not in frame.columns]
        if missing_features:
            raise ValueError("Selected features are not materialized: " + ", ".join(missing_features))
        if not selected_features:
            raise ValueError("Select at least one eligible predictor before creating a split.")

        test_size = float(config.get("test_size", 0.2))
        if strategy in {"holdout", "holdout_current", "hybrid"} and not 0.1 <= test_size <= 0.5:
            raise ValueError("Holdout size must be between 10% and 50%.")
        random_seed = int(config.get("random_seed", 42))
        problem_type = str(config.get("problem_type") or "classification")
        event_value = config.get("event_value")

        if prepartitioned_holdout is not None or prepartitioned_holdout_target is not None:
            raise ValueError(
                "Validation Design must not materialize sealed final-holdout predictors or target values."
            )
        has_prepartition = (
            prepartitioned_development is not None
            and prepartitioned_development_target is not None
        )
        if (
            prepartitioned_development is None
        ) != (prepartitioned_development_target is None):
            raise ValueError(
                "Development predictors and target must be supplied together."
            )

        X = frame.loc[:, selected_features].copy()
        y = frame[target_col].copy()
        stratify = None
        if not has_prepartition:
            if y.isna().any():
                valid = y.notna()
                X = X.loc[valid]
                y = y.loc[valid]
            if len(y) < 4:
                raise ValueError(
                    "At least four valid target rows are required to create a development split."
                )
            if problem_type == "classification" and bool(
                config.get("stratify", True)
            ):
                counts = y.value_counts()
                if len(counts) < 2:
                    raise ValueError(
                        "The target contains one class. A stratified holdout cannot be created."
                    )
                if int(counts.min()) < 2:
                    raise ValueError(
                        "The minority class has fewer than two records. Both train and holdout sets need at least one event."
                    )
                stratify = y
        if has_prepartition:
            # These populations were sealed before EDA. Validation Design may
            # configure folds and training-only balancing, but it must never
            # redraw or infer their membership.
            development_constraint_frame = prepartitioned_development.copy()
            development_X = development_constraint_frame.loc[:, selected_features].copy()
            development_y = prepartitioned_development_target.copy()
            if development_X.empty:
                raise ValueError(
                    "The governed Analysis Partition must contain Development rows."
                )
            if len(development_X) != len(development_y):
                raise ValueError(
                    "The governed Development predictors and target are not aligned."
                )
            if not development_X.index.equals(development_y.index):
                raise ValueError(
                    "Development predictors and target do not preserve the sealed membership order."
                )
            if development_y.isna().any():
                raise ValueError(
                    "The governed development population contains rows without a target value."
                )

        evaluation_population_role = "untouched_holdout"
        if strategy in {"separate_test", "separate_test_oot"}:
            if external_test_frame is None or external_test_frame.empty:
                raise ValueError("Select an accessible immutable TEST dataset version.")
            resolved_external_target = str(external_test_target or target_col)
            missing_external = [
                name for name in selected_features if name not in external_test_frame.columns
            ]
            if missing_external:
                raise ValueError(
                    "The TEST dataset is missing governed predictors: "
                    + ", ".join(missing_external)
                )
            if resolved_external_target not in external_test_frame.columns:
                raise ValueError(
                    f"Mapped TEST target '{resolved_external_target}' is unavailable."
                )
            X_train = development_X.copy() if has_prepartition else X.copy()
            y_train = development_y.copy() if has_prepartition else y.copy()
            if has_prepartition:
                X_test = None
                y_test = None
                evaluation_population_role = "sealed_holdout_reference"
            else:
                X_test = external_test_frame.loc[:, selected_features].copy()
                y_test = external_test_frame[resolved_external_target].copy()
                valid_test = y_test.notna()
                X_test = X_test.loc[valid_test]
                y_test = y_test.loc[valid_test]
                evaluation_population_role = "separate_test"
        elif strategy == "cross_validation" and not has_prepartition:
            # The persisted fold architecture owns model selection. A fixed,
            # untouched reference fold is also materialized for legacy trainer
            # compatibility and is explicitly labelled as such downstream.
            fold_count = int(config.get("fold_count") or 5)
            if problem_type == "classification":
                splitter = StratifiedKFold(
                    n_splits=fold_count,
                    shuffle=bool(config.get("shuffle", True)),
                    random_state=random_seed if bool(config.get("shuffle", True)) else None,
                )
                split_iterator = splitter.split(X, y)
            else:
                splitter = KFold(
                    n_splits=fold_count,
                    shuffle=bool(config.get("shuffle", True)),
                    random_state=random_seed if bool(config.get("shuffle", True)) else None,
                )
                split_iterator = splitter.split(X)
            train_position, validation_position = next(iter(split_iterator))
            X_train = X.iloc[train_position].copy()
            y_train = y.iloc[train_position].copy()
            X_test = X.iloc[validation_position].copy()
            y_test = y.iloc[validation_position].copy()
            evaluation_population_role = "cv_reference_fold"
        elif has_prepartition:
            X_train = development_X.copy()
            y_train = development_y.copy()
            X_test = None
            y_test = None
            evaluation_population_role = "sealed_holdout_reference"
        else:
            X_train, X_test, y_train, y_test = train_test_split(
                X,
                y,
                test_size=test_size,
                random_state=random_seed,
                stratify=stratify,
            )

        original_train = target_distribution(y_train, event_value)
        resolved_holdout_rows = int(sealed_holdout_row_count or 0)
        test_distribution = (
            {
                "rows": resolved_holdout_rows,
                "status": "sealed",
                "target_statistics_withheld": True,
                "predictors_materialized": False,
                "target_accessed": False,
            }
            if evaluation_population_role == "sealed_holdout_reference"
            else target_distribution(y_test, event_value)
        )
        if problem_type == "classification" and len(y_train.value_counts()) == 2:
            if not original_train.get("events"):
                raise ValueError(
                    "The governed development population has no events. Correct the Analysis Partition before defining validation."
                )

        original_train_rows = int(len(y_train))
        training_index = list(y_train.index)
        validation_index = [] if y_test is None else list(y_test.index)
        fold_constraint_frame = (
            development_constraint_frame.copy()
            if has_prepartition
            else frame.loc[training_index].copy()
        )
        fold_architecture = self._build_fold_architecture(
            fold_constraint_frame,
            y_train,
            config,
        )
        balance_method = str(config.get("balance_method") or "none")
        fold_method = str(config.get("fold_method") or "none")
        fold_local_preprocessing = str(
            config.get("fold_local_preprocessing")
            or "fit_transform_per_fold"
        )
        if fold_local_preprocessing not in {
            "fit_transform_per_fold",
            "model_native_per_fold",
        }:
            raise ValueError(
                "Fold-local preprocessing must be fit_transform_per_fold or model_native_per_fold."
            )
        fold_local_balancing = (
            fold_method != "none"
            and balance_method in {"undersample", "oversample", "smote"}
        )
        if fold_local_balancing:
            if problem_type != "classification" or len(y_train.value_counts()) != 2:
                raise ValueError(
                    "Fold-local resampling requires a binary classification target."
                )
            # Persist the policy for the training engine.  Validation Design
            # must not pre-resample the development population because that
            # would contaminate validation folds and invalidate their stored
            # positional membership.
            balancing_application_status = "planned_fold_local_training_only"
        elif balance_method == "undersample":
            if problem_type != "classification" or len(y_train.value_counts()) != 2:
                raise ValueError("Training-only undersampling requires a binary classification target.")
            X_train, y_train = self._undersample_train(
                X_train,
                y_train,
                minority_share=float(config.get("minority_share", 0.5)),
                random_seed=random_seed,
            )
            balancing_application_status = "applied_training_population_only"
        elif balance_method == "oversample":
            if problem_type != "classification" or len(y_train.value_counts()) != 2:
                raise ValueError("Training-only oversampling requires a binary classification target.")
            X_train, y_train = self._oversample_train(
                X_train,
                y_train,
                minority_share=float(config.get("minority_share", 0.5)),
                random_seed=random_seed,
            )
            balancing_application_status = "applied_training_population_only"
        elif balance_method == "smote":
            if problem_type != "classification" or len(y_train.value_counts()) != 2:
                raise ValueError("Training-only SMOTE requires a binary classification target.")
            X_train, y_train = self._smote_train(
                X_train,
                y_train,
                minority_share=float(config.get("minority_share", 0.5)),
                random_seed=random_seed,
            )
            balancing_application_status = "applied_training_population_only"
        elif balance_method != "none":
            raise ValueError(f"Balancing method '{balance_method}' is not implemented by the split backend.")
        else:
            balancing_application_status = "not_requested"

        synthetic_rows_added = max(0, int(len(y_train)) - original_train_rows)
        rows_removed = max(0, original_train_rows - int(len(y_train)))
        return SplitResult(
            X_train=X_train,
            X_test=X_test,
            y_train=y_train,
            y_test=y_test,
            original_train_rows=original_train_rows,
            original_train_distribution=original_train,
            applied_train_distribution=target_distribution(y_train, event_value),
            test_distribution=test_distribution,
            fold_architecture=fold_architecture,
            training_index=training_index,
            validation_index=validation_index,
            synthetic_rows_added=synthetic_rows_added,
            rows_removed=rows_removed,
            evaluation_population_role=evaluation_population_role,
            fold_local_preprocessing=fold_local_preprocessing,
            balancing_application_status=balancing_application_status,
            sealed_holdout_rows=resolved_holdout_rows,
        )

    def _build_fold_architecture(
        self,
        constraint_frame: pd.DataFrame,
        y_train: pd.Series,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        method = str(config.get("fold_method") or "none")
        if method == "none":
            return {
                "enabled": False,
                "method": "none",
                "fold_count": 0,
                "repeats": 0,
                "folds": [],
                "execution_splits": [],
            }
        fold_count = int(config.get("fold_count") or 5)
        repeats = int(config.get("repeats") or 1)
        if not 2 <= fold_count <= 20:
            raise ValueError("Cross-validation folds must be between 2 and 20.")
        if not 1 <= repeats <= 10:
            raise ValueError("Cross-validation repeats must be between 1 and 10.")
        if len(y_train) < fold_count:
            raise ValueError("The training population has fewer rows than requested folds.")

        shuffle = bool(config.get("shuffle", True))
        seed = int(config.get("random_seed") or 42)
        problem_type = str(config.get("problem_type") or "classification")
        group_field = str(config.get("group_field") or "")
        time_field = str(config.get("time_field") or "")
        groups = None
        position_order = np.arange(len(y_train), dtype=int)
        splitter: Any
        split_args: tuple[Any, ...]
        if method == "k_fold":
            splitter = KFold(
                n_splits=fold_count,
                shuffle=shuffle,
                random_state=seed if shuffle else None,
            )
            split_args = (constraint_frame,)
        elif method in {"stratified_k_fold", "nested_cv"}:
            if problem_type != "classification":
                splitter = KFold(
                    n_splits=fold_count,
                    shuffle=shuffle,
                    random_state=seed if shuffle else None,
                )
                split_args = (constraint_frame,)
            else:
                counts = y_train.value_counts()
                if int(counts.min()) < fold_count:
                    raise ValueError(
                        "The minority class has fewer records than the requested number of stratified folds."
                    )
                splitter = StratifiedKFold(
                    n_splits=fold_count,
                    shuffle=shuffle,
                    random_state=seed if shuffle else None,
                )
                split_args = (constraint_frame, y_train)
        elif method == "repeated_stratified_k_fold":
            if problem_type != "classification":
                raise ValueError("Repeated stratified folds require classification.")
            counts = y_train.value_counts()
            if int(counts.min()) < fold_count:
                raise ValueError(
                    "The minority class has fewer records than the requested number of stratified folds."
                )
            splitter = RepeatedStratifiedKFold(
                n_splits=fold_count,
                n_repeats=repeats,
                random_state=seed,
            )
            split_args = (constraint_frame, y_train)
        elif method in {"group_k_fold", "stratified_group_k_fold"}:
            if not group_field or group_field not in constraint_frame.columns:
                raise ValueError("Select a governed group field for group-preserving folds.")
            groups = constraint_frame[group_field]
            if int(groups.nunique(dropna=True)) < fold_count:
                raise ValueError("The group field has fewer distinct groups than requested folds.")
            if method == "group_k_fold":
                splitter = GroupKFold(n_splits=fold_count)
                split_args = (constraint_frame, y_train, groups)
            else:
                if problem_type != "classification":
                    raise ValueError("Stratified group folds require classification.")
                splitter = StratifiedGroupKFold(
                    n_splits=fold_count,
                    shuffle=shuffle,
                    random_state=seed if shuffle else None,
                )
                split_args = (constraint_frame, y_train, groups)
        elif method == "time_series":
            if not time_field or time_field not in constraint_frame.columns:
                raise ValueError("Select a governed time field for time-series validation.")
            parsed = pd.to_datetime(constraint_frame[time_field], errors="coerce")
            if parsed.isna().any():
                raise ValueError("The governed time field contains values that cannot be ordered.")
            order = np.argsort(parsed.to_numpy())
            position_order = np.asarray(order, dtype=int)
            ordered_frame = constraint_frame.iloc[order]
            ordered_y = y_train.iloc[order]
            splitter = TimeSeriesSplit(n_splits=fold_count)
            split_args = (ordered_frame,)
            constraint_frame = ordered_frame
            y_train = ordered_y
        else:
            raise ValueError(f"Fold method '{method}' is not supported.")

        folds: list[dict[str, Any]] = []
        execution_splits: list[dict[str, list[int]]] = []
        for sequence, (train_positions, validation_positions) in enumerate(
            splitter.split(*split_args),
            start=1,
        ):
            governed_train_positions = position_order[
                np.asarray(train_positions, dtype=int)
            ]
            governed_validation_positions = position_order[
                np.asarray(validation_positions, dtype=int)
            ]
            execution_splits.append(
                {
                    "train_positions": [
                        int(value) for value in governed_train_positions
                    ],
                    "validation_positions": [
                        int(value) for value in governed_validation_positions
                    ],
                }
            )
            repeat_number = (sequence - 1) // fold_count + 1
            fold_number = (sequence - 1) % fold_count + 1
            train_target = y_train.iloc[train_positions]
            validation_target = y_train.iloc[validation_positions]
            fold_groups = None
            if groups is not None:
                fold_groups = int(
                    pd.Series(groups).iloc[validation_positions].nunique(dropna=True)
                )
            folds.append(
                {
                    "sequence": sequence,
                    "repeat": repeat_number,
                    "fold": fold_number,
                    "train_rows": int(len(train_positions)),
                    "validation_rows": int(len(validation_positions)),
                    "train_distribution": target_distribution(
                        train_target, config.get("event_value")
                    ),
                    "validation_distribution": target_distribution(
                        validation_target, config.get("event_value")
                    ),
                    "validation_groups": fold_groups,
                }
            )
        validation_sizes = [fold["validation_rows"] for fold in folds]
        return {
            "enabled": True,
            "method": method,
            "fold_count": fold_count,
            "repeats": repeats if method == "repeated_stratified_k_fold" else 1,
            "shuffle": shuffle,
            "random_seed": seed,
            "group_field": group_field or None,
            "time_field": time_field or None,
            "nested": method == "nested_cv",
            "inner_folds": int(config.get("inner_fold_count") or 3)
            if method == "nested_cv"
            else None,
            "fold_size_consistent": (
                max(validation_sizes) - min(validation_sizes) <= 1
                if validation_sizes
                else True
            ),
            "folds": folds,
            "execution_splits": execution_splits,
        }

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
