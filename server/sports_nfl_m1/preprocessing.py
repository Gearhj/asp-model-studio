"""Fold-local preprocessing for the NFL M1 candidate suite."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .contracts import M1_SCHEMA_VERSION, NflM1IntegrityError, assert_valid_model_predictors


DEFAULT_CATEGORICAL_FEATURES = frozenset(
    {
        "game_type",
        "roof",
        "surface",
        "stadium",
        "weather_description",
        "time_zone_change_direction",
    }
)


def _row_id_sha256(row_ids: Iterable[object] | None) -> str | None:
    if row_ids is None:
        return None
    payload = json.dumps([str(item) for item in row_ids], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class FoldLocalPreprocessor:
    """Median-impute/standardize numerics and one-hot encode categoricals.

    Every learned statistic is obtained only from the frame passed to ``fit``.
    Numeric missing indicators are retained by ``SimpleImputer``.  An entirely
    absent numeric source-era feature remains present (neutral zero after
    scaling) and is paired with its missing indicator rather than silently
    being interpreted as a real zero.
    """

    feature_names: tuple[str, ...]
    categorical_features: tuple[str, ...]
    transformer: ColumnTransformer
    training_row_count: int
    training_row_id_sha256: str | None

    @classmethod
    def fit(
        cls,
        frame: pd.DataFrame,
        feature_names: Sequence[str],
        *,
        categorical_features: Sequence[str] | None = None,
        training_row_ids: Iterable[object] | None = None,
    ) -> "FoldLocalPreprocessor":
        names = assert_valid_model_predictors(feature_names)
        if frame.empty:
            raise NflM1IntegrityError("fold-local preprocessing requires training rows")
        row_id_values = None if training_row_ids is None else tuple(training_row_ids)
        if row_id_values is not None and len(row_id_values) != len(frame):
            raise NflM1IntegrityError("training row identities must match the training rows")
        missing = [name for name in names if name not in frame.columns]
        if missing:
            raise NflM1IntegrityError(f"training frame is missing predictors: {missing}")
        if categorical_features is None:
            categoricals = tuple(name for name in names if name in DEFAULT_CATEGORICAL_FEATURES)
        else:
            categoricals = tuple(str(name) for name in categorical_features)
        unknown_categoricals = sorted(set(categoricals) - set(names))
        if unknown_categoricals:
            raise NflM1IntegrityError(
                f"categorical declarations are not predictors: {unknown_categoricals}"
            )
        numerics = tuple(name for name in names if name not in categoricals)
        transformer = ColumnTransformer(
            transformers=[
                (
                    "numeric",
                    Pipeline(
                        steps=[
                            (
                                "imputer",
                                SimpleImputer(
                                    strategy="median",
                                    add_indicator=True,
                                    keep_empty_features=True,
                                ),
                            ),
                            ("standardizer", StandardScaler()),
                        ]
                    ),
                    list(numerics),
                ),
                (
                    "categorical",
                    Pipeline(
                        steps=[
                            (
                                "imputer",
                                SimpleImputer(
                                    strategy="constant",
                                    fill_value="SOURCE_OR_HISTORY_MISSING",
                                    keep_empty_features=True,
                                ),
                            ),
                            (
                                "one_hot",
                                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                            ),
                        ]
                    ),
                    list(categoricals),
                ),
            ],
            remainder="drop",
            sparse_threshold=0.0,
            verbose_feature_names_out=True,
        )
        prepared = cls._prepare(frame, numerics, categoricals)
        transformer.fit(prepared)
        fitted = cls(
            feature_names=names,
            categorical_features=categoricals,
            transformer=transformer,
            training_row_count=len(frame),
            training_row_id_sha256=_row_id_sha256(row_id_values),
        )
        fitted.transform(frame)
        return fitted

    @staticmethod
    def _prepare(
        frame: pd.DataFrame,
        numeric_features: Sequence[str],
        categorical_features: Sequence[str],
    ) -> pd.DataFrame:
        columns: dict[str, pd.Series] = {}
        for name in numeric_features:
            try:
                columns[name] = pd.to_numeric(frame[name], errors="raise")
            except (TypeError, ValueError) as exc:
                raise NflM1IntegrityError(f"numeric predictor is not numeric: {name}") from exc
        for name in categorical_features:
            values = frame[name].astype("object")
            columns[name] = values.where(pd.notna(values), "SOURCE_OR_HISTORY_MISSING")
        # Construct once so the 197-column authority is contiguous. Repeated
        # column insertion fragments the frame and materially slows every fold.
        return pd.DataFrame(columns, index=frame.index)

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        missing = [name for name in self.feature_names if name not in frame.columns]
        if missing:
            raise NflM1IntegrityError(f"scoring frame is missing predictors: {missing}")
        numerics = tuple(name for name in self.feature_names if name not in self.categorical_features)
        prepared = self._prepare(frame, numerics, self.categorical_features)
        matrix = np.asarray(self.transformer.transform(prepared), dtype=np.float64)
        if matrix.ndim != 2 or matrix.shape[0] != len(frame) or not np.isfinite(matrix).all():
            raise NflM1IntegrityError("fold-local preprocessing produced an invalid matrix")
        return np.ascontiguousarray(matrix)

    @property
    def expanded_feature_names(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self.transformer.get_feature_names_out())

    def state(self) -> dict[str, object]:
        numeric = tuple(name for name in self.feature_names if name not in self.categorical_features)
        numeric_pipeline = self.transformer.named_transformers_["numeric"]
        categorical_pipeline = self.transformer.named_transformers_["categorical"]
        imputer = numeric_pipeline.named_steps["imputer"]
        one_hot = categorical_pipeline.named_steps["one_hot"]
        return {
            "schemaVersion": M1_SCHEMA_VERSION,
            "featureNames": list(self.feature_names),
            "categoricalFeatures": list(self.categorical_features),
            "numericFeatures": list(numeric),
            "numericImputation": "TRAINING_FOLD_MEDIAN_WITH_MISSING_INDICATOR",
            "numericImputationStatistics": [float(value) for value in imputer.statistics_],
            "categoricalTreatment": "TRAINING_FOLD_ONE_HOT_UNKNOWN_IGNORED",
            "categoricalValues": {
                name: [str(value) for value in values]
                for name, values in zip(self.categorical_features, one_hot.categories_, strict=True)
            },
            "expandedFeatureNames": list(self.expanded_feature_names),
            "trainingRowCount": self.training_row_count,
            "trainingRowIdSha256": self.training_row_id_sha256,
            "fitScope": "TRAINING_ROWS_OF_THIS_FOLD_ONLY",
        }


__all__ = ["DEFAULT_CATEGORICAL_FEATURES", "FoldLocalPreprocessor"]
