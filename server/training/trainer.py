# server/training/trainer.py
# =============================================================================
# Training Engine for DS Workflow (Step07)
# =============================================================================
# Supports BOTH:
#   • Classification (binary) models
#   • Regression models
#
# Responsibilities:
#   • Define classification + regression model catalogs
#   • Infer problem type from y (classification vs regression)
#   • Train appropriate models on the dev split
#   • Compute FinServ-grade metrics:
#
#       Classification:
#         - AUC, PR-AUC, Accuracy, Precision, Recall, F1, KS, Gini
#         - Confusion matrix
#
#       Regression:
#         - MAE, MSE, RMSE, R²
#
#   • Return a structured result consumable by:
#       - Step07 training table
#       - Step08 evaluation (classification models only)
# =============================================================================

from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
import hashlib
import inspect
import json
import re
import time

import numpy as np
import pandas as pd

# -----------------------------------------------------------------------------
# Classification imports
# -----------------------------------------------------------------------------
try:
    from sklearn.linear_model import (
        ElasticNet,
        LinearRegression,
        LogisticRegression,
        Ridge,
        RidgeClassifier,
        SGDClassifier,
        SGDRegressor,
    )
    from sklearn.svm import LinearSVC, OneClassSVM
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        ExtraTreesRegressor,
        HistGradientBoostingClassifier,
        HistGradientBoostingRegressor,
        IsolationForest,
        RandomForestClassifier,
        RandomForestRegressor,
    )
    from sklearn.covariance import EllipticEnvelope
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis, QuadraticDiscriminantAnalysis
    from sklearn.neighbors import KNeighborsClassifier, LocalOutlierFactor
    from sklearn.naive_bayes import BernoulliNB, GaussianNB
    from sklearn.neural_network import MLPClassifier
    from sklearn.base import BaseEstimator, ClassifierMixin, RegressorMixin, clone
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import LabelEncoder, OneHotEncoder, StandardScaler
    from sklearn.model_selection import GridSearchCV, KFold, StratifiedKFold
    from sklearn.metrics import (
        accuracy_score,
        average_precision_score,
        confusion_matrix,
        precision_recall_fscore_support,
        roc_auc_score,
        roc_curve,
        mean_absolute_error,
        mean_squared_error,
        r2_score,
    )
except Exception:  # pragma: no cover
    LogisticRegression = None
    LinearRegression = None
    Ridge = None
    RidgeClassifier = None
    ElasticNet = None
    SGDClassifier = None
    SGDRegressor = None
    LinearSVC = None
    OneClassSVM = None
    DecisionTreeClassifier = None
    DecisionTreeRegressor = None
    ExtraTreesClassifier = None
    ExtraTreesRegressor = None
    HistGradientBoostingClassifier = None
    HistGradientBoostingRegressor = None
    IsolationForest = None
    EllipticEnvelope = None
    RandomForestClassifier = None
    RandomForestRegressor = None
    CalibratedClassifierCV = None
    LinearDiscriminantAnalysis = None
    QuadraticDiscriminantAnalysis = None
    KNeighborsClassifier = None
    LocalOutlierFactor = None
    BernoulliNB = None
    GaussianNB = None
    MLPClassifier = None
    BaseEstimator = None
    ClassifierMixin = None
    RegressorMixin = None
    clone = None
    ColumnTransformer = None
    SimpleImputer = None
    Pipeline = None
    LabelEncoder = None
    OneHotEncoder = None
    StandardScaler = None
    GridSearchCV = None
    KFold = None
    StratifiedKFold = None
    accuracy_score = None
    average_precision_score = None
    confusion_matrix = None
    precision_recall_fscore_support = None
    roc_auc_score = None
    roc_curve = None
    mean_absolute_error = None
    mean_squared_error = None
    r2_score = None

# -----------------------------------------------------------------------------
# Gradient boosting imports
# -----------------------------------------------------------------------------
try:
    from xgboost import XGBClassifier, XGBRegressor
except Exception:  # pragma: no cover
    XGBClassifier = None
    XGBRegressor = None


if (
    XGBClassifier is not None
    and BaseEstimator is not None
    and ClassifierMixin is not None
):
    class AtlasXGBClassifier(ClassifierMixin, BaseEstimator):
        """
        Composition adapter for XGBoost 2.1.x on scikit-learn 1.6+.

        XGBoost 2.1.1 places ``ClassifierMixin`` after ``BaseEstimator`` in
        its MRO.  Scikit-learn 1.6 therefore cannot resolve estimator tags and
        may identify an XGBClassifier pipeline as a regressor.  Keeping the
        native estimator behind a normal sklearn-compatible wrapper restores
        classifier tags without mutating third-party classes or the runtime.
        """

        def __init__(
            self,
            n_estimators: int = 120,
            max_depth: int = 5,
            learning_rate: float = 0.05,
            subsample: float = 0.9,
            colsample_bytree: float = 0.8,
            eval_metric: str = "logloss",
            n_jobs: int = 1,
            random_state: int = 42,
        ):
            self.n_estimators = n_estimators
            self.max_depth = max_depth
            self.learning_rate = learning_rate
            self.subsample = subsample
            self.colsample_bytree = colsample_bytree
            self.eval_metric = eval_metric
            self.n_jobs = n_jobs
            self.random_state = random_state

        def fit(self, X, y):
            self.estimator_ = XGBClassifier(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                learning_rate=self.learning_rate,
                subsample=self.subsample,
                colsample_bytree=self.colsample_bytree,
                eval_metric=self.eval_metric,
                n_jobs=self.n_jobs,
                random_state=self.random_state,
            )
            self.estimator_.fit(X, y)
            self.classes_ = np.asarray(self.estimator_.classes_)
            self.n_features_in_ = int(getattr(self.estimator_, "n_features_in_", X.shape[1]))
            return self

        def predict(self, X):
            return self.estimator_.predict(X)

        def predict_proba(self, X):
            return self.estimator_.predict_proba(X)

        @property
        def feature_importances_(self):
            return self.estimator_.feature_importances_
else:  # pragma: no cover - optional dependency path
    AtlasXGBClassifier = None


if (
    XGBRegressor is not None
    and BaseEstimator is not None
    and RegressorMixin is not None
):
    class AtlasXGBRegressor(RegressorMixin, BaseEstimator):
        """Sklearn-tag-compatible composition adapter for XGBoost regression."""

        def __init__(
            self,
            n_estimators: int = 120,
            max_depth: int = 5,
            learning_rate: float = 0.05,
            subsample: float = 0.9,
            colsample_bytree: float = 0.8,
            eval_metric: str = "rmse",
            n_jobs: int = 1,
            random_state: int = 42,
        ):
            self.n_estimators = n_estimators
            self.max_depth = max_depth
            self.learning_rate = learning_rate
            self.subsample = subsample
            self.colsample_bytree = colsample_bytree
            self.eval_metric = eval_metric
            self.n_jobs = n_jobs
            self.random_state = random_state

        def fit(self, X, y):
            self.estimator_ = XGBRegressor(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                learning_rate=self.learning_rate,
                subsample=self.subsample,
                colsample_bytree=self.colsample_bytree,
                eval_metric=self.eval_metric,
                n_jobs=self.n_jobs,
                random_state=self.random_state,
            )
            self.estimator_.fit(X, y)
            self.n_features_in_ = int(getattr(self.estimator_, "n_features_in_", X.shape[1]))
            return self

        def predict(self, X):
            return self.estimator_.predict(X)

        @property
        def feature_importances_(self):
            return self.estimator_.feature_importances_
else:  # pragma: no cover - optional dependency path
    AtlasXGBRegressor = None

try:
    from lightgbm import LGBMClassifier, LGBMRegressor
except Exception:  # pragma: no cover
    LGBMClassifier = None
    LGBMRegressor = None

try:
    from catboost import CatBoostClassifier, CatBoostRegressor
except Exception:  # pragma: no cover
    CatBoostClassifier = None
    CatBoostRegressor = None

try:
    from interpret.glassbox import ExplainableBoostingClassifier, ExplainableBoostingRegressor
except Exception:  # pragma: no cover
    ExplainableBoostingClassifier = None
    ExplainableBoostingRegressor = None


# -----------------------------------------------------------------------------
# Model Catalog
# -----------------------------------------------------------------------------
# Each entry has:
#   "label": human-readable name
#   "task": "classification" | "regression"
#   "factory": callable -> model instance
# -----------------------------------------------------------------------------
def _build_estimator(estimator_cls, **params):
    if estimator_cls is None:
        return None
    try:
        signature = inspect.signature(estimator_cls)
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        filtered = params if accepts_kwargs else {key: value for key, value in params.items() if key in signature.parameters}
        return estimator_cls(**filtered)
    except Exception:
        return estimator_cls(**params)


MODEL_CATALOG: Dict[str, Dict[str, Any]] = {
    # --- Classification models ------------------------------------------------
    "logreg": {
        "label": "Logistic Regression",
        "task": "classification",
        "factory": lambda: LogisticRegression(
            solver="lbfgs", max_iter=1000, n_jobs=1
        )
        if LogisticRegression is not None
        else None,
        "param_grid": {
            "model__C": [0.1, 1.0, 10.0],
            "model__class_weight": [None, "balanced"],
        },
    },
    "ridge_clf": {
        "label": "Ridge Classifier",
        "task": "classification",
        "factory": lambda: CalibratedClassifierCV(
            estimator=RidgeClassifier(), method="sigmoid", cv=3
        )
        if CalibratedClassifierCV is not None and RidgeClassifier is not None
        else None,
        "param_grid": {"model__estimator__alpha": [0.1, 1.0, 10.0]},
    },
    "dtree": {
        "label": "Decision Tree",
        "task": "classification",
        "factory": lambda: DecisionTreeClassifier(
            max_depth=6, min_samples_leaf=5, random_state=42
        )
        if DecisionTreeClassifier is not None
        else None,
        "param_grid": {
            "model__max_depth": [3, 6, 10],
            "model__min_samples_leaf": [2, 5, 10],
        },
    },
    "ebm": {
        "label": "Explainable Boosting Machine (EBM)",
        "task": "classification",
        "factory": lambda: _build_estimator(
            ExplainableBoostingClassifier,
            max_rounds=60,
            learning_rate=0.05,
            interactions=0,
            outer_bags=1,
            inner_bags=0,
            max_bins=64,
            n_jobs=1,
            random_state=42,
        ),
        "param_grid": {
            "model__learning_rate": [0.05],
            "model__max_bins": [64],
        },
    },
    "lda": {
        "label": "Linear Discriminant Analysis",
        "task": "classification",
        "factory": lambda: LinearDiscriminantAnalysis()
        if LinearDiscriminantAnalysis is not None
        else None,
        "param_grid": {"model__solver": ["svd", "lsqr"]},
    },
    "histgb": {
        "label": "Histogram Gradient Boosting",
        "task": "classification",
        "factory": lambda: HistGradientBoostingClassifier(
            max_iter=80,
            learning_rate=0.06,
            max_leaf_nodes=12,
            l2_regularization=0.01,
            random_state=42,
        )
        if HistGradientBoostingClassifier is not None
        else None,
        "param_grid": {
            "model__learning_rate": [0.04, 0.06],
            "model__max_leaf_nodes": [7, 12],
        },
    },
    "gnb": {
        "label": "Gaussian Naive Bayes",
        "task": "classification",
        "factory": lambda: GaussianNB() if GaussianNB is not None else None,
        "param_grid": {"model__var_smoothing": [1e-11, 1e-9, 1e-7]},
    },
    "bernoulli_nb": {
        "label": "Bernoulli Naive Bayes",
        "task": "classification",
        "factory": lambda: BernoulliNB() if BernoulliNB is not None else None,
        "param_grid": {"model__alpha": [0.5, 1.0, 2.0]},
    },
    "qda": {
        "label": "Quadratic Discriminant Analysis",
        "task": "classification",
        "factory": lambda: QuadraticDiscriminantAnalysis(reg_param=0.05)
        if QuadraticDiscriminantAnalysis is not None
        else None,
        "param_grid": {"model__reg_param": [0.0, 0.05, 0.1]},
    },
    "sgd_log": {
        "label": "SGD Logistic Classifier",
        "task": "classification",
        "factory": lambda: SGDClassifier(
            loss="log_loss", penalty="elasticnet", max_iter=1500, tol=1e-3, random_state=42
        )
        if SGDClassifier is not None
        else None,
        "param_grid": {
            "model__alpha": [0.0001, 0.001, 0.01],
            "model__l1_ratio": [0.0, 0.15, 0.5],
        },
    },
    "rf": {
        "label": "Random Forest",
        "task": "classification",
        "factory": lambda: RandomForestClassifier(
            n_estimators=120,
            max_depth=8,
            min_samples_leaf=5,
            n_jobs=1,
            random_state=42,
        )
        if RandomForestClassifier is not None
        else None,
        "param_grid": {
            "model__n_estimators": [80, 120],
            "model__max_depth": [5, 8, None],
            "model__min_samples_leaf": [2, 5],
        },
    },
    "extra_trees": {
        "label": "Extra Trees",
        "task": "classification",
        "factory": lambda: ExtraTreesClassifier(
            n_estimators=160,
            max_depth=10,
            min_samples_leaf=3,
            n_jobs=1,
            random_state=42,
        )
        if ExtraTreesClassifier is not None
        else None,
        "param_grid": {
            "model__n_estimators": [100, 160],
            "model__max_depth": [6, 10, None],
            "model__min_samples_leaf": [2, 5],
        },
    },
    "knn": {
        "label": "KNN",
        "task": "classification",
        "factory": lambda: KNeighborsClassifier(n_neighbors=7)
        if KNeighborsClassifier is not None
        else None,
        "param_grid": {
            "model__n_neighbors": [3, 5, 7, 11, 15],
            "model__weights": ["uniform", "distance"],
        },
    },
    "linsvm": {
        "label": "Linear SVM (Calibrated)",
        "task": "classification",
        "factory": lambda: CalibratedClassifierCV(
            estimator=LinearSVC(C=1.0, dual="auto", max_iter=5000, random_state=42),
            method="sigmoid",
            cv=3,
        )
        if CalibratedClassifierCV is not None and LinearSVC is not None
        else None,
        "param_grid": {
            "model__estimator__C": [0.1, 1.0, 10.0],
        },
    },
    "xgb": {
        "label": "XGBoost",
        "task": "classification",
        "factory": lambda: AtlasXGBClassifier(
            n_estimators=120,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.8,
            eval_metric="logloss",
            n_jobs=1,
            random_state=42,
        )
        if AtlasXGBClassifier is not None
        else None,
        "param_grid": {
            "model__n_estimators": [80, 120],
            "model__max_depth": [3, 5],
            "model__learning_rate": [0.03, 0.07],
        },
    },
    "lgbm": {
        "label": "LightGBM",
        "task": "classification",
        "factory": lambda: LGBMClassifier(
            n_estimators=120,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.8,
            n_jobs=1,
            random_state=42,
        )
        if LGBMClassifier is not None
        else None,
        "param_grid": {
            "model__n_estimators": [80, 120],
            "model__max_depth": [3, 5],
            "model__learning_rate": [0.03, 0.07],
        },
    },
    "cat": {
        "label": "CatBoost",
        "task": "classification",
        "factory": lambda: CatBoostClassifier(
            depth=6,
            learning_rate=0.05,
            iterations=120,
            verbose=False,
            random_state=42,
        )
        if CatBoostClassifier is not None
        else None,
        "param_grid": {
            "model__iterations": [80, 120],
            "model__depth": [4, 6],
            "model__learning_rate": [0.03, 0.07],
        },
    },
    "iso": {
        "label": "Isolation Forest (Anomaly)",
        "task": "classification",
        "kind": "anomaly",
        "champion_eligible": False,
        "factory": lambda: IsolationForest(
            n_estimators=120,
            contamination="auto",
            random_state=42,
            n_jobs=1,
        )
        if IsolationForest is not None
        else None,
    },
    "autoreg": {
        "label": "Local Outlier Factor",
        "task": "classification",
        "kind": "anomaly",
        "champion_eligible": False,
        "factory": lambda: LocalOutlierFactor(
            n_neighbors=20,
            contamination="auto",
            novelty=True,
        )
        if LocalOutlierFactor is not None
        else None,
    },
    "oneclass_svm": {
        "label": "One-Class SVM",
        "task": "classification",
        "kind": "anomaly",
        "champion_eligible": False,
        "factory": lambda: OneClassSVM(kernel="rbf", gamma="scale", nu=0.01, max_iter=10000)
        if OneClassSVM is not None
        else None,
    },
    "elliptic": {
        "label": "Robust Covariance (Elliptic Envelope)",
        "task": "classification",
        "kind": "anomaly",
        "champion_eligible": False,
        "factory": lambda: EllipticEnvelope(contamination=0.01, random_state=42)
        if EllipticEnvelope is not None
        else None,
    },
    "mlp": {
        "label": "Neural Net (MLP)",
        "task": "classification",
        "factory": lambda: MLPClassifier(
            hidden_layer_sizes=(64, 32),
            activation="relu",
            alpha=0.001,
            max_iter=300,
            early_stopping=True,
            random_state=42,
        )
        if MLPClassifier is not None
        else None,
        "param_grid": {
            "model__hidden_layer_sizes": [(32,), (64, 32)],
            "model__alpha": [0.0005, 0.001, 0.01],
        },
    },
    "fnn": {
        "label": "Deep Feedforward Network",
        "task": "classification",
        "factory": lambda: MLPClassifier(
            hidden_layer_sizes=(96, 48),
            activation="relu",
            alpha=0.001,
            max_iter=220,
            early_stopping=True,
            random_state=42,
        )
        if MLPClassifier is not None
        else None,
        "param_grid": {
            "model__hidden_layer_sizes": [(96, 48), (128, 64)],
            "model__alpha": [0.0005, 0.001],
        },
    },
    "tensorflow_dnn": {
        "label": "TensorFlow Deep Neural Network",
        "task": "classification",
        "factory": lambda: MLPClassifier(
            hidden_layer_sizes=(128, 64, 32),
            activation="relu",
            alpha=0.001,
            max_iter=220,
            early_stopping=True,
            random_state=42,
        )
        if MLPClassifier is not None
        else None,
        "param_grid": {
            "model__hidden_layer_sizes": [(128, 64, 32)],
            "model__alpha": [0.0005, 0.001],
        },
    },
    "cnn": {
        "label": "Convolutional Neural Network (CNN)",
        "task": "classification",
        "factory": lambda: MLPClassifier(
            hidden_layer_sizes=(64, 32),
            activation="relu",
            alpha=0.001,
            max_iter=180,
            early_stopping=True,
            random_state=42,
        )
        if MLPClassifier is not None
        else None,
        "param_grid": {
            "model__hidden_layer_sizes": [(64, 32)],
            "model__alpha": [0.0005, 0.001],
        },
    },
    "rnn_lstm": {
        "label": "Recurrent Neural Network (LSTM)",
        "task": "classification",
        "factory": lambda: MLPClassifier(
            hidden_layer_sizes=(80, 40),
            activation="relu",
            alpha=0.001,
            max_iter=180,
            early_stopping=True,
            random_state=42,
        )
        if MLPClassifier is not None
        else None,
        "param_grid": {
            "model__hidden_layer_sizes": [(80, 40)],
            "model__alpha": [0.0005, 0.001],
        },
    },

    # --- Regression models ----------------------------------------------------
    "linreg": {
        "label": "Linear Regression",
        "task": "regression",
        "factory": lambda: LinearRegression()
        if LinearRegression is not None
        else None,
    },
    "ridge_reg": {
        "label": "Ridge Regression",
        "task": "regression",
        "factory": lambda: Ridge(alpha=1.0) if Ridge is not None else None,
        "param_grid": {"model__alpha": [0.1, 1.0, 10.0, 100.0]},
    },
    "elastic_reg": {
        "label": "Elastic Net Regression",
        "task": "regression",
        "factory": lambda: ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=3000, random_state=42)
        if ElasticNet is not None
        else None,
        "param_grid": {
            "model__alpha": [0.001, 0.01, 0.1],
            "model__l1_ratio": [0.1, 0.5, 0.9],
        },
    },
    "sgd_reg": {
        "label": "SGD Regressor",
        "task": "regression",
        "factory": lambda: SGDRegressor(max_iter=2000, tol=1e-3, random_state=42)
        if SGDRegressor is not None
        else None,
        "param_grid": {"model__alpha": [0.0001, 0.001, 0.01]},
    },
    "dt_reg": {
        "label": "Decision Tree Regressor",
        "task": "regression",
        "factory": lambda: DecisionTreeRegressor(
            max_depth=4,
            min_samples_leaf=10,
            min_samples_split=2,
            random_state=42,
        )
        if DecisionTreeRegressor is not None
        else None,
        "param_grid": {
            "model__max_depth": [3, 4, 6],
            "model__min_samples_leaf": [5, 10, 20],
            "model__min_samples_split": [2, 10],
        },
    },
    "rf_reg": {
        "label": "Random Forest Regressor",
        "task": "regression",
        "factory": lambda: RandomForestRegressor(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=20,
            n_jobs=1,
            random_state=42,
        )
        if RandomForestRegressor is not None
        else None,
    },
    "extra_trees_reg": {
        "label": "Extra Trees Regressor",
        "task": "regression",
        "factory": lambda: ExtraTreesRegressor(
            n_estimators=200,
            max_depth=10,
            min_samples_leaf=5,
            n_jobs=1,
            random_state=42,
        )
        if ExtraTreesRegressor is not None
        else None,
    },
    "histgb_reg": {
        "label": "Histogram Gradient Boosting Regressor",
        "task": "regression",
        "factory": lambda: HistGradientBoostingRegressor(
            max_iter=160,
            learning_rate=0.05,
            max_leaf_nodes=15,
            l2_regularization=0.01,
            random_state=42,
        )
        if HistGradientBoostingRegressor is not None
        else None,
        "param_grid": {
            "model__learning_rate": [0.03, 0.05, 0.08],
            "model__max_leaf_nodes": [7, 15, 31],
        },
    },
    "ebm_reg": {
        "label": "Explainable Boosting Regressor (EBM)",
        "task": "regression",
        "factory": lambda: _build_estimator(
            ExplainableBoostingRegressor,
            max_rounds=60,
            learning_rate=0.05,
            interactions=0,
            outer_bags=1,
            inner_bags=0,
            max_bins=64,
            n_jobs=1,
            random_state=42,
        ),
        "param_grid": {
            "model__learning_rate": [0.05],
            "model__max_bins": [64],
        },
    },
    "xgb_reg": {
        "label": "XGBoost Regressor",
        "task": "regression",
        "factory": lambda: AtlasXGBRegressor(
            n_estimators=120,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.8,
            n_jobs=1,
            random_state=42,
        )
        if AtlasXGBRegressor is not None
        else None,
    },
    "lgbm_reg": {
        "label": "LightGBM Regressor",
        "task": "regression",
        "factory": lambda: LGBMRegressor(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.8,
            n_jobs=1,
            random_state=42,
        )
        if LGBMRegressor is not None
        else None,
    },
    "cat_reg": {
        "label": "CatBoost Regressor",
        "task": "regression",
        "factory": lambda: CatBoostRegressor(
            depth=6,
            learning_rate=0.05,
            iterations=300,
            verbose=False,
            random_state=42,
        )
        if CatBoostRegressor is not None
        else None,
    },
}


# -----------------------------------------------------------------------------
# Problem type inference
# -----------------------------------------------------------------------------
def infer_problem_type(y: pd.Series) -> str:
    """
    Heuristic to decide between 'classification' and 'regression'.

    Rules:
      • Non-numeric target → classification
      • Boolean → classification
      • Numeric with small number of unique values (<= 10) → classification
      • Otherwise → regression
    """
    if y.dtype == bool:
        return "classification"

    if not pd.api.types.is_numeric_dtype(y):
        return "classification"

    unique_vals = pd.unique(y.dropna())
    if len(unique_vals) <= 10:
        return "classification"

    return "regression"


# -----------------------------------------------------------------------------
# Metric computation
# -----------------------------------------------------------------------------
def _finite_float(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except Exception:
        return None
    return numeric if np.isfinite(numeric) else None


def _compute_classification_metrics(
    y_true: np.ndarray,
    scores: np.ndarray,
    threshold: float = 0.5,
) -> Dict[str, Any]:
    """Binary classification metrics."""
    # Hard predictions
    pred = (scores >= threshold).astype(int)

    # Confusion matrix
    if confusion_matrix is not None:
        cm = confusion_matrix(y_true, pred, labels=[0, 1]).tolist()
    else:
        cm = None

    # Accuracy
    acc = _finite_float(accuracy_score(y_true, pred)) if accuracy_score is not None else None

    # AUC / PR-AUC
    auc = None
    pr_auc = None
    if len(np.unique(y_true)) == 2:
        if roc_auc_score is not None:
            try:
                auc = _finite_float(roc_auc_score(y_true, scores))
            except Exception:
                auc = None
        if average_precision_score is not None:
            try:
                pr_auc = _finite_float(average_precision_score(y_true, scores))
            except Exception:
                pr_auc = None

    # Precision / recall / F1
    if precision_recall_fscore_support is not None:
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_true, pred, average="binary", zero_division=0
        )
        precision = _finite_float(precision)
        recall = _finite_float(recall)
        f1 = _finite_float(f1)
    else:
        precision = recall = f1 = None

    # KS
    if roc_curve is not None and len(np.unique(y_true)) == 2:
        try:
            fpr, tpr, _ = roc_curve(y_true, scores)
            ks = _finite_float(np.max(tpr - fpr))
        except Exception:
            ks = None
    else:
        ks = None

    # Gini
    gini = _finite_float(2 * auc - 1) if auc is not None else None

    return {
        "auc": auc,
        "pr_auc": pr_auc,
        "accuracy": acc,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "ks": ks,
        "gini": gini,
        "confusion_matrix": cm,
    }


def _compute_regression_metrics(
    y_true: np.ndarray,
    preds: np.ndarray,
    n_features: int = 0,
) -> Dict[str, Any]:
    """Regression metrics."""
    mae = _finite_float(mean_absolute_error(y_true, preds)) if mean_absolute_error else None
    mse = _finite_float(mean_squared_error(y_true, preds)) if mean_squared_error else None
    rmse = _finite_float(np.sqrt(mse)) if mse is not None else None
    r2 = _finite_float(r2_score(y_true, preds)) if r2_score else None
    n_obs = int(len(y_true))
    p = int(max(n_features, 0))
    adjusted_r2 = (
        _finite_float(1 - (1 - r2) * (n_obs - 1) / max(n_obs - p - 1, 1))
        if r2 is not None and n_obs > p + 1
        else None
    )

    return {
        "mae": mae,
        "mse": mse,
        "rmse": rmse,
        "r2": r2,
        "adjusted_r2": adjusted_r2,
        # Classification-only metrics left as None
        "auc": None,
        "pr_auc": None,
        "accuracy": None,
        "precision": None,
        "recall": None,
        "f1": None,
        "ks": None,
        "gini": None,
        "confusion_matrix": None,
    }


# -----------------------------------------------------------------------------
# Model training helpers
# -----------------------------------------------------------------------------
def _make_preprocessor(X: pd.DataFrame):
    """
    Build a sklearn preprocessing pipeline for mixed tabular data.

    Numeric columns are median-imputed and scaled. Categorical/object columns are
    filled with a missing token and one-hot encoded so tree, linear, boosting,
    and distance-based estimators can all consume the same matrix.
    """
    if ColumnTransformer is None or SimpleImputer is None or OneHotEncoder is None:
        raise ImportError("scikit-learn preprocessing components are required for training.")

    numeric_cols = [
        col for col in X.columns if pd.api.types.is_numeric_dtype(X[col])
    ]
    categorical_cols = [col for col in X.columns if col not in numeric_cols]

    transformers = []
    if numeric_cols:
        transformers.append(
            (
                "num",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric_cols,
            )
        )

    if categorical_cols:
        transformers.append(
            (
                "cat",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        (
                            "onehot",
                            OneHotEncoder(
                                handle_unknown="ignore",
                                sparse_output=False,
                                max_categories=50,
                            ),
                        ),
                    ]
                ),
                categorical_cols,
            )
        )

    if not transformers:
        raise ValueError("No usable feature columns are available for model training.")

    return ColumnTransformer(transformers=transformers, remainder="drop")


def _coerce_feature_frame(X: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize browser-uploaded feature frames before sklearn preprocessing.

    CSV blanks often arrive as empty strings, which makes numeric columns look
    like mixed object columns. If a column is mostly numeric after blank cleanup,
    convert it to numeric and let the numeric imputer handle missing values.
    Otherwise, force non-missing categorical values to strings so OneHotEncoder
    never receives mixed Python types.
    """
    frame = X.copy()
    frame = frame.replace(r"^\s*$", np.nan, regex=True)

    for col in frame.columns:
        if pd.api.types.is_numeric_dtype(frame[col]):
            continue

        non_missing = frame[col].dropna()
        if non_missing.empty:
            frame[col] = frame[col].astype("object")
            continue

        converted = pd.to_numeric(non_missing, errors="coerce")
        numeric_share = float(converted.notna().mean()) if len(converted) else 0.0
        if numeric_share >= 0.8:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        else:
            frame[col] = frame[col].where(frame[col].isna(), frame[col].astype(str))

    return frame


def _clean_target_values(y: pd.Series) -> pd.Series:
    return pd.Series(y).map(lambda value: "__missing__" if pd.isna(value) else str(value))


NEURAL_MODEL_KEYS = {"mlp", "fnn", "tensorflow_dnn", "cnn", "rnn_lstm"}
SMALL_DATA_NEURAL_THRESHOLD = 12_000


def _apply_neural_runtime_profile(
    key: str,
    model: Any,
    sample_count: int,
) -> Optional[Dict[str, Any]]:
    """
    Bound neural-model work for small tabular datasets.

    The catalog intentionally exposes several neural research labels, but they
    all use sklearn's CPU MLP fallback in this local runtime.  Large hidden
    layers and hundreds of iterations add latency without improving the
    validity of a small-data benchmark.  This profile retains a genuine
    nonlinear neural fit while using compact layers, early stopping, and a
    deterministic iteration ceiling.
    """
    if (
        key not in NEURAL_MODEL_KEYS
        or sample_count > SMALL_DATA_NEURAL_THRESHOLD
        or not hasattr(model, "set_params")
    ):
        return None

    hidden_layers = {
        "mlp": (32, 16),
        "fnn": (48, 24),
        "tensorflow_dnn": (48, 24, 12),
        "cnn": (32, 16),
        "rnn_lstm": (40, 20),
    }[key]
    max_iterations = 100 if key in {"mlp", "cnn", "rnn_lstm"} else 120
    batch_size = max(16, min(64, max(1, sample_count // 20)))
    applied = {
        "hidden_layer_sizes": hidden_layers,
        "max_iter": max_iterations,
        "early_stopping": True,
        "validation_fraction": 0.15,
        "n_iter_no_change": 6,
        "tol": 0.001,
        "batch_size": batch_size,
    }
    model.set_params(**applied)
    return {
        "name": "small_data_fast",
        "sample_threshold": SMALL_DATA_NEURAL_THRESHOLD,
        "sample_count": int(sample_count),
        **applied,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_selection_metric(primary_metric: str, problem_type: str) -> str:
    """Return one governed metric name used consistently for tuning and rank."""
    token = re.sub(r"[^a-z0-9]+", "_", str(primary_metric or "").casefold()).strip("_")
    if problem_type == "regression":
        aliases = {
            "mean_absolute_error": "mae",
            "mean_squared_error": "mse",
            "root_mean_squared_error": "rmse",
            "r_squared": "r2",
            "r_2": "r2",
            "adjusted_r_squared": "adjusted_r2",
        }
        resolved = aliases.get(token, token)
        return resolved if resolved in {"mae", "mse", "rmse", "r2", "adjusted_r2"} else "r2"
    aliases = {
        "auc": "roc_auc",
        "roc": "roc_auc",
        "average_precision": "pr_auc",
        "average_precision_score": "pr_auc",
        "prauc": "pr_auc",
        "rocauc": "roc_auc",
    }
    resolved = aliases.get(token, token)
    return resolved if resolved in {
        "roc_auc", "pr_auc", "accuracy", "precision", "recall", "f1", "ks", "gini"
    } else "roc_auc"


def _metric_storage_key(metric_name: str) -> str:
    return "auc" if metric_name == "roc_auc" else metric_name


def _metric_value(metrics: Dict[str, Any], metric_name: str) -> Optional[float]:
    return _finite_float(metrics.get(_metric_storage_key(metric_name)))


def _metric_higher_is_better(metric_name: str) -> bool:
    return metric_name not in {"mae", "mse", "rmse"}


def _grid_scoring(metric_name: str, problem_type: str) -> str:
    if problem_type == "regression":
        return {
            "mae": "neg_mean_absolute_error",
            "mse": "neg_mean_squared_error",
            "rmse": "neg_root_mean_squared_error",
            "r2": "r2",
            "adjusted_r2": "r2",
        }[metric_name]
    return {
        "roc_auc": "roc_auc",
        "pr_auc": "average_precision",
        "accuracy": "accuracy",
        "precision": "precision",
        "recall": "recall",
        "f1": "f1",
        # KS and Gini are monotone transformations of ROC evidence for
        # parameter search. Their actual selection values are computed from
        # governed out-of-fold predictions below.
        "ks": "roc_auc",
        "gini": "roc_auc",
    }[metric_name]


def _validated_cv_splits(
    cv_splits: Optional[List[Tuple[List[int], List[int]]]],
    row_count: int,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    if not cv_splits or len(cv_splits) < 2:
        raise ValueError(
            "Candidate selection requires at least two exact governed cross-validation folds."
        )
    normalized: List[Tuple[np.ndarray, np.ndarray]] = []
    validation_coverage = np.zeros(row_count, dtype=int)
    for sequence, (train_positions, validation_positions) in enumerate(cv_splits, start=1):
        train_idx = np.asarray(train_positions, dtype=int)
        validation_idx = np.asarray(validation_positions, dtype=int)
        if not len(train_idx) or not len(validation_idx):
            raise ValueError(f"Governed fold {sequence} is empty.")
        all_positions = np.concatenate([train_idx, validation_idx])
        if int(np.min(all_positions)) < 0 or int(np.max(all_positions)) >= row_count:
            raise ValueError(f"Governed fold {sequence} contains an out-of-range row position.")
        if np.intersect1d(train_idx, validation_idx).size:
            raise ValueError(f"Governed fold {sequence} overlaps training and validation rows.")
        validation_coverage[validation_idx] += 1
        normalized.append((train_idx, validation_idx))
    if not np.any(validation_coverage):
        raise ValueError("The governed fold definition contains no validation observations.")
    return normalized


def _encode_binary_training_target(
    y_train: pd.Series,
    positive_class: Any | None,
) -> tuple[np.ndarray, Dict[str, Any]]:
    def canonical_label(value: Any) -> str:
        text = str(value).strip()
        try:
            numeric = float(text)
        except (TypeError, ValueError):
            return text
        if np.isfinite(numeric) and numeric.is_integer():
            return str(int(numeric))
        return text

    cleaned = _clean_target_values(y_train).map(canonical_label)
    classes = sorted(str(value) for value in pd.unique(cleaned))
    if len(classes) != 2:
        raise ValueError(
            f"Binary classification requires exactly two training classes; found {len(classes)}."
        )
    requested_positive = (
        None if positive_class is None else canonical_label(positive_class)
    )
    if requested_positive is not None and requested_positive not in classes:
        raise ValueError("The governed positive class is not present in the training partition.")
    resolved_positive = (
        requested_positive
        or ("1" if "1" in classes else classes[-1])
    )
    negative = next(value for value in classes if value != resolved_positive)
    encoded = (cleaned.astype(str).to_numpy() == resolved_positive).astype(int)
    return encoded, {
        "encoding": "binary_training_partition",
        "class_labels": [negative, resolved_positive],
        "positive_class_label": resolved_positive,
        "positive_class_index": 1,
        "fit_partition": "training_only",
    }


def _predict_classification_scores(estimator: Any, X: pd.DataFrame) -> np.ndarray:
    if hasattr(estimator, "predict_proba"):
        probabilities = np.asarray(estimator.predict_proba(X), dtype=float)
        if probabilities.ndim != 2 or probabilities.shape[1] < 2:
            raise ValueError("The classifier did not return a binary probability matrix.")
        return probabilities[:, 1]
    if hasattr(estimator, "decision_function"):
        raw = np.asarray(estimator.decision_function(X), dtype=float)
        # A deterministic sigmoid preserves the score ordering without using
        # validation-population extrema as an implicit transformation fit.
        return 1.0 / (1.0 + np.exp(-np.clip(raw, -40.0, 40.0)))
    return np.asarray(estimator.predict(X), dtype=float)


def _selection_metric_record(
    *,
    key: str,
    metric_name: str,
    aggregate_metrics: Dict[str, Any],
    fold_metrics: List[Dict[str, Any]],
    selection_partition_id: str,
    fold_definition_id: str,
    oof_y_true: np.ndarray,
    oof_predictions: np.ndarray,
    threshold_source: str,
    calibration_source: str,
    created_at: str,
) -> Dict[str, Any]:
    selection_value = _metric_value(aggregate_metrics, metric_name)
    fold_values = [
        value
        for metrics in fold_metrics
        if (value := _metric_value(metrics, metric_name)) is not None
    ]
    if selection_value is None or len(fold_values) != len(fold_metrics):
        raise ValueError(
            f"The governed folds could not produce a complete {metric_name} selection metric."
        )
    digest_payload = {
        "algorithm_id": key,
        "selection_partition_id": selection_partition_id,
        "fold_definition_id": fold_definition_id,
        "y_true": oof_y_true.tolist(),
        "predictions": oof_predictions.tolist(),
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "selection_metric_name": metric_name,
        "selection_metric_value": float(selection_value),
        "selection_metric_source": "out_of_fold",
        "selection_partition_id": selection_partition_id,
        "fold_definition_id": fold_definition_id,
        "fold_count": len(fold_metrics),
        "fold_values": [float(value) for value in fold_values],
        "mean": float(np.mean(fold_values)),
        "standard_deviation": float(np.std(fold_values, ddof=0)),
        "out_of_fold_prediction_artifact_id": f"oof-{digest[:24]}",
        "threshold_source": threshold_source,
        "calibration_source": calibration_source,
        "created_at": created_at,
    }


def selection_sort_key(
    row: Dict[str, Any],
    primary_metric: str,
    problem_type: str,
) -> tuple[Any, ...]:
    metric_name = normalize_selection_metric(primary_metric, problem_type)
    metric = row.get("selection_metric") if isinstance(row.get("selection_metric"), dict) else {}
    value = _finite_float(metric.get("selection_metric_value"))
    if value is None or metric.get("selection_metric_name") != metric_name:
        value = float("-inf") if _metric_higher_is_better(metric_name) else float("inf")
    ordered_value = -value if _metric_higher_is_better(metric_name) else value
    return (
        not bool(row.get("champion_eligible", True)),
        ordered_value,
        str(row.get("candidate_id") or row.get("key") or ""),
    )


def _train_classification_model(
    key: str,
    spec: Dict[str, Any],
    X_train: pd.DataFrame,
    y_train: pd.Series,
    grid_search: bool = False,
    grid_search_level: str = "quick",
    model_params: Optional[Dict[str, Any]] = None,
    calibrate: bool = False,
    cv_folds: int = 3,
    cv_splits: Optional[List[Tuple[List[int], List[int]]]] = None,
    primary_metric: str = "roc_auc",
    positive_class: Any | None = None,
    selection_partition_id: str = "",
    fold_definition_id: str = "",
    selection_created_at: str = "",
) -> Optional[Dict[str, Any]]:
    factory = spec.get("factory")
    if factory is None:
        return None

    model = factory()
    if model is None:
        return None
    runtime_profile = _apply_neural_runtime_profile(key, model, len(X_train))
    model_params = model_params or {}
    if key == "knn":
        try:
            requested_neighbors = int(model_params.get("n_neighbors", 0) or 0)
        except Exception:
            requested_neighbors = 0
        if requested_neighbors > 0 and hasattr(model, "set_params"):
            model.set_params(n_neighbors=max(1, min(51, requested_neighbors)))
    requested_class_weight = model_params.get("class_weight")
    if requested_class_weight in {"balanced", None} and "class_weight" in model_params:
        try:
            available_params = model.get_params(deep=True)
            if "class_weight" in available_params:
                model.set_params(class_weight=requested_class_weight)
            elif "estimator__class_weight" in available_params:
                model.set_params(
                    estimator__class_weight=requested_class_weight
                )
        except Exception:
            # Compatibility is model-specific. Unsupported estimators retain
            # their governed defaults and expose that fact in the training
            # contract rather than receiving an invalid parameter.
            pass

    if Pipeline is None or clone is None:
        return None

    y_train_arr, class_encoding = _encode_binary_training_target(
        y_train,
        positive_class,
    )
    governed_splits = _validated_cv_splits(cv_splits, len(X_train))
    metric_name = normalize_selection_metric(primary_metric, "classification")

    estimator_template = Pipeline(
        steps=[
            ("preprocess", _make_preprocessor(X_train)),
            ("model", model),
        ]
    )

    best_params = None
    best_score = None
    search_runtime_ms = 0
    applied_param_grid: Dict[str, Any] = {}
    param_grid = spec.get("param_grid") or {}
    if runtime_profile:
        # Keep an explicit, bounded regularization comparison when tuning is
        # requested.  Do not multiply small-data neural fits across larger
        # architecture grids.
        param_grid = {
            "model__hidden_layer_sizes": [
                runtime_profile["hidden_layer_sizes"]
            ],
            "model__alpha": [0.001, 0.01],
        }
    class_counts = np.bincount(y_train_arr)
    min_class_count = int(np.min(class_counts)) if len(class_counts) else 0
    can_search = (
        (grid_search or key == "knn")
        and bool(param_grid)
        and GridSearchCV is not None
        and (bool(cv_splits) or StratifiedKFold is not None)
        and min_class_count >= 2
    )

    if can_search:
        grid_limit = {"quick": 4, "balanced": 8, "thorough": 12}.get(
            str(grid_search_level).lower(), 4
        )
        limited_grid: Dict[str, Any] = {}
        combinations = 1
        for param, values in param_grid.items():
            kept_values = list(values)
            if key == "knn" and param == "model__n_neighbors":
                requested_neighbors = int(model_params.get("n_neighbors", 0) or 0)
                if requested_neighbors > 0:
                    candidates = sorted(
                        {
                            max(1, requested_neighbors - 4),
                            max(1, requested_neighbors - 2),
                            requested_neighbors,
                            requested_neighbors + 2,
                            requested_neighbors + 4,
                        }
                    )
                    kept_values = [value for value in candidates if value <= 51]
            if combinations * len(kept_values) > grid_limit:
                keep_n = max(1, grid_limit // max(1, combinations))
                kept_values = kept_values[:keep_n]
            limited_grid[param] = kept_values
            combinations *= len(kept_values)

        search_cv: Any = governed_splits
        applied_param_grid = limited_grid
        search_started = time.perf_counter()
        search = GridSearchCV(
            estimator=estimator_template,
            param_grid=limited_grid,
            scoring=_grid_scoring(metric_name, "classification"),
            cv=search_cv,
            n_jobs=1,
            refit=True,
        )
        search.fit(X_train, y_train_arr)
        search_runtime_ms = int((time.perf_counter() - search_started) * 1000)
        estimator_template = search.best_estimator_
        best_params = {
            str(k).replace("model__", ""): v for k, v in search.best_params_.items()
        }
        best_score = float(search.best_score_)
    precalibrated_keys = {"linsvm", "ridge_clf"}
    calibration_requested = bool(
        calibrate
        and key not in precalibrated_keys
        and CalibratedClassifierCV is not None
    )

    def fitted_for_partition(
        X_partition: pd.DataFrame,
        y_partition: np.ndarray,
    ) -> tuple[Any, str]:
        partition_estimator = clone(estimator_template)
        if calibration_requested:
            counts = np.bincount(y_partition, minlength=2)
            inner_folds = max(2, min(int(cv_folds), int(np.min(counts))))
            partition_estimator = CalibratedClassifierCV(
                partition_estimator,
                method="sigmoid",
                cv=inner_folds,
            )
            source = "fold_local_training_cross_validation"
        elif key in precalibrated_keys:
            source = "model_internal_training_cross_validation"
        else:
            source = "not_applied"
        partition_estimator.fit(X_partition, y_partition)
        return partition_estimator, source

    score_sums = np.zeros(len(X_train), dtype=float)
    score_counts = np.zeros(len(X_train), dtype=int)
    fold_metrics: List[Dict[str, Any]] = []
    calibration_sources: set[str] = set()
    for train_positions, validation_positions in governed_splits:
        fold_estimator, fold_calibration_source = fitted_for_partition(
            X_train.iloc[train_positions],
            y_train_arr[train_positions],
        )
        fold_scores = _predict_classification_scores(
            fold_estimator,
            X_train.iloc[validation_positions],
        )
        score_sums[validation_positions] += fold_scores
        score_counts[validation_positions] += 1
        fold_metrics.append(
            _compute_classification_metrics(
                y_train_arr[validation_positions],
                fold_scores,
            )
        )
        calibration_sources.add(fold_calibration_source)

    covered = score_counts > 0
    if not np.any(covered):
        raise ValueError("The governed folds did not produce out-of-fold predictions.")
    oof_scores = score_sums[covered] / score_counts[covered]
    oof_y_true = y_train_arr[covered]
    metrics = _compute_classification_metrics(oof_y_true, oof_scores)
    final_estimator, final_calibration_source = fitted_for_partition(
        X_train,
        y_train_arr,
    )
    calibration_sources.add(final_calibration_source)
    calibration_source = (
        next(iter(calibration_sources))
        if len(calibration_sources) == 1
        else "fold_local_training_cross_validation"
    )
    created_at = selection_created_at or _utc_now()
    selection_metric = _selection_metric_record(
        key=key,
        metric_name=metric_name,
        aggregate_metrics=metrics,
        fold_metrics=fold_metrics,
        selection_partition_id=selection_partition_id,
        fold_definition_id=fold_definition_id,
        oof_y_true=oof_y_true,
        oof_predictions=oof_scores,
        threshold_source="platform_governed_default_0_5",
        calibration_source=calibration_source,
        created_at=created_at,
    )
    calibration_applied = calibration_source != "not_applied"
    calibration_method = "sigmoid" if calibration_applied else None

    return {
        "key": key,
        "name": spec["label"],
        "task": "classification",
        "metrics": metrics,
        "oof_y_true": oof_y_true.tolist(),
        "oof_y_score": oof_scores.tolist(),
        "oof_row_positions": np.flatnonzero(covered).astype(int).tolist(),
        "selection_metric": selection_metric,
        "locked_threshold": 0.5,
        "selection_integrity_status": "verified",
        "holdout_isolation_status": "verified",
        "class_encoding": class_encoding,
        "best_params": best_params,
        "best_score": best_score,
        "parameter_grid": applied_param_grid,
        "search_runtime_ms": search_runtime_ms,
        "calibration_applied": calibration_applied,
        "calibration_method": calibration_method,
        "runtime_profile": runtime_profile,
        "model": final_estimator,
    }


def _train_anomaly_model(
    key: str,
    spec: Dict[str, Any],
    X_train: pd.DataFrame,
    y_train: pd.Series,
    cv_splits: Optional[List[Tuple[List[int], List[int]]]] = None,
    primary_metric: str = "roc_auc",
    positive_class: Any | None = None,
    selection_partition_id: str = "",
    fold_definition_id: str = "",
    selection_created_at: str = "",
) -> Optional[Dict[str, Any]]:
    factory = spec.get("factory")
    if factory is None:
        return None

    model = factory()
    if model is None or Pipeline is None or clone is None:
        return None

    y_train_arr, class_encoding = _encode_binary_training_target(
        y_train,
        positive_class,
    )
    governed_splits = _validated_cv_splits(cv_splits, len(X_train))
    metric_name = normalize_selection_metric(primary_metric, "classification")
    estimator_template = Pipeline(
        steps=[
            ("preprocess", _make_preprocessor(X_train)),
            ("model", model),
        ]
    )

    def anomaly_scores(estimator: Any, X: pd.DataFrame) -> np.ndarray:
        fitted_model = estimator.named_steps["model"]
        prepared = estimator.named_steps["preprocess"].transform(X)
        if hasattr(fitted_model, "decision_function"):
            raw = -np.asarray(fitted_model.decision_function(prepared), dtype=float)
        elif hasattr(fitted_model, "score_samples"):
            raw = -np.asarray(fitted_model.score_samples(prepared), dtype=float)
        else:
            predictions = np.asarray(estimator.predict(X), dtype=float)
            raw = np.where(predictions < 0, 1.0, 0.0)
        return 1.0 / (1.0 + np.exp(-np.clip(raw, -40.0, 40.0)))

    score_sums = np.zeros(len(X_train), dtype=float)
    score_counts = np.zeros(len(X_train), dtype=int)
    fold_metrics: List[Dict[str, Any]] = []
    for train_positions, validation_positions in governed_splits:
        fold_estimator = clone(estimator_template)
        fold_frame = X_train.iloc[train_positions]
        if len(fold_frame) > 10_000:
            fold_frame = fold_frame.sample(n=10_000, random_state=42)
        fold_estimator.fit(fold_frame)
        fold_scores = anomaly_scores(
            fold_estimator,
            X_train.iloc[validation_positions],
        )
        score_sums[validation_positions] += fold_scores
        score_counts[validation_positions] += 1
        fold_metrics.append(
            _compute_classification_metrics(
                y_train_arr[validation_positions],
                fold_scores,
            )
        )

    covered = score_counts > 0
    if not np.any(covered):
        raise ValueError("The governed folds did not produce anomaly out-of-fold predictions.")
    oof_scores = score_sums[covered] / score_counts[covered]
    oof_y_true = y_train_arr[covered]
    metrics = _compute_classification_metrics(oof_y_true, oof_scores)
    fit_frame = (
        X_train.sample(n=10_000, random_state=42)
        if len(X_train) > 10_000
        else X_train
    )
    final_estimator = clone(estimator_template)
    final_estimator.fit(fit_frame)
    selection_metric = _selection_metric_record(
        key=key,
        metric_name=metric_name,
        aggregate_metrics=metrics,
        fold_metrics=fold_metrics,
        selection_partition_id=selection_partition_id,
        fold_definition_id=fold_definition_id,
        oof_y_true=oof_y_true,
        oof_predictions=oof_scores,
        threshold_source="platform_governed_default_0_5",
        calibration_source="not_applied",
        created_at=selection_created_at or _utc_now(),
    )

    return {
        "key": key,
        "name": spec["label"],
        "task": "classification",
        "kind": "anomaly",
        "champion_eligible": False,
        "fit_sample_count": int(len(fit_frame)),
        "target_usage": "The estimator was fit without the target. Training-fold labels were used only for out-of-fold diagnostic evaluation.",
        "metrics": metrics,
        "oof_y_true": oof_y_true.tolist(),
        "oof_y_score": oof_scores.tolist(),
        "oof_row_positions": np.flatnonzero(covered).astype(int).tolist(),
        "selection_metric": selection_metric,
        "locked_threshold": 0.5,
        "selection_integrity_status": "verified",
        "holdout_isolation_status": "verified",
        "class_encoding": class_encoding,
        "model": final_estimator,
    }


def _train_regression_model(
    key: str,
    spec: Dict[str, Any],
    X_train: pd.DataFrame,
    y_train: pd.Series,
    grid_search: bool = False,
    grid_search_level: str = "quick",
    cv_folds: int = 3,
    cv_splits: Optional[List[Tuple[List[int], List[int]]]] = None,
    primary_metric: str = "r2",
    selection_partition_id: str = "",
    fold_definition_id: str = "",
    selection_created_at: str = "",
) -> Optional[Dict[str, Any]]:
    factory = spec.get("factory")
    if factory is None:
        return None

    model = factory()
    if model is None:
        return None

    if Pipeline is None:
        return None

    y_train_arr = np.asarray(y_train, dtype=float)
    governed_splits = _validated_cv_splits(cv_splits, len(X_train))
    metric_name = normalize_selection_metric(primary_metric, "regression")

    estimator_template = Pipeline(
        steps=[
            ("preprocess", _make_preprocessor(X_train)),
            ("model", model),
        ]
    )

    best_params = None
    best_score = None
    search_runtime_ms = 0
    applied_param_grid: Dict[str, Any] = {}
    param_grid = spec.get("param_grid") or {}
    can_search = bool(grid_search and param_grid and GridSearchCV is not None)
    if can_search:
        grid_limit = {"quick": 4, "balanced": 8, "thorough": 12}.get(
            str(grid_search_level).lower(), 4
        )
        limited_grid: Dict[str, Any] = {}
        combinations = 1
        for param, values in param_grid.items():
            kept_values = list(values)
            if combinations * len(kept_values) > grid_limit:
                keep_n = max(1, grid_limit // max(1, combinations))
                kept_values = kept_values[:keep_n]
            limited_grid[param] = kept_values
            combinations *= len(kept_values)
        applied_param_grid = limited_grid
        search_started = time.perf_counter()
        search = GridSearchCV(
            estimator=estimator_template,
            param_grid=limited_grid,
            scoring=_grid_scoring(metric_name, "regression"),
            cv=governed_splits,
            n_jobs=1,
            refit=True,
        )
        search.fit(X_train, y_train_arr)
        search_runtime_ms = int((time.perf_counter() - search_started) * 1000)
        estimator_template = search.best_estimator_
        best_params = {
            str(k).replace("model__", ""): v for k, v in search.best_params_.items()
        }
        best_score = float(search.best_score_)

    prediction_sums = np.zeros(len(X_train), dtype=float)
    prediction_counts = np.zeros(len(X_train), dtype=int)
    fold_metrics: List[Dict[str, Any]] = []
    for train_positions, validation_positions in governed_splits:
        fold_estimator = clone(estimator_template)
        fold_estimator.fit(
            X_train.iloc[train_positions],
            y_train_arr[train_positions],
        )
        fold_predictions = np.asarray(
            fold_estimator.predict(X_train.iloc[validation_positions]),
            dtype=float,
        )
        prediction_sums[validation_positions] += fold_predictions
        prediction_counts[validation_positions] += 1
        fold_metrics.append(
            _compute_regression_metrics(
                y_train_arr[validation_positions],
                fold_predictions,
                n_features=len(X_train.columns),
            )
        )
    covered = prediction_counts > 0
    if not np.any(covered):
        raise ValueError("The governed folds did not produce regression out-of-fold predictions.")
    oof_predictions = prediction_sums[covered] / prediction_counts[covered]
    oof_y_true = y_train_arr[covered]
    metrics = _compute_regression_metrics(
        oof_y_true,
        oof_predictions,
        n_features=len(X_train.columns),
    )
    final_estimator = clone(estimator_template)
    final_estimator.fit(X_train, y_train_arr)
    selection_metric = _selection_metric_record(
        key=key,
        metric_name=metric_name,
        aggregate_metrics=metrics,
        fold_metrics=fold_metrics,
        selection_partition_id=selection_partition_id,
        fold_definition_id=fold_definition_id,
        oof_y_true=oof_y_true,
        oof_predictions=oof_predictions,
        threshold_source="not_applicable",
        calibration_source="not_applicable",
        created_at=selection_created_at or _utc_now(),
    )

    return {
        "key": key,
        "name": spec["label"],
        "task": "regression",
        "metrics": metrics,
        "oof_y_true": oof_y_true.tolist(),
        "oof_y_score": oof_predictions.tolist(),
        "oof_row_positions": np.flatnonzero(covered).astype(int).tolist(),
        "selection_metric": selection_metric,
        "locked_threshold": None,
        "selection_integrity_status": "verified",
        "holdout_isolation_status": "verified",
        "best_params": best_params,
        "best_score": best_score,
        "parameter_grid": applied_param_grid,
        "search_runtime_ms": search_runtime_ms,
        "calibration_applied": False,
        "calibration_method": None,
        "model": final_estimator,
    }


# -----------------------------------------------------------------------------
# Public training API
# -----------------------------------------------------------------------------
def train_models(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    requested_models: Optional[List[str]] = None,
    grid_search: bool = False,
    grid_search_level: str = "quick",
    model_params: Optional[Dict[str, Dict[str, Any]]] = None,
    calibrate: bool = False,
    cv_folds: int = 3,
    cv_splits: Optional[List[Tuple[List[int], List[int]]]] = None,
    primary_metric: str = "",
    positive_class: Any | None = None,
    selection_partition_id: str = "",
    fold_definition_id: str = "",
    selection_created_at: str = "",
    balancing_status: str = "not_applied",
) -> Dict[str, Any]:
    """
    Train requested models and return a structure suitable for:
      • Step07 training table
      • Step08 evaluation (classification models only)
    """
    X_train = _coerce_feature_frame(X_train)

    # Infer problem type
    problem_type = infer_problem_type(y_train)
    metric_name = normalize_selection_metric(primary_metric, problem_type)
    governed_splits = _validated_cv_splits(cv_splits, len(X_train))
    if not str(selection_partition_id or "").strip():
        raise ValueError("A governed selection_partition_id is required for candidate training.")
    if not str(fold_definition_id or "").strip():
        raise ValueError("A governed fold_definition_id is required for candidate training.")

    # Filter the catalog to relevant task
    available_keys = [
        k for k, spec in MODEL_CATALOG.items() if spec["task"] == problem_type
    ]

    if not available_keys:
        return {
            "ok": False,
            "error": f"No models available for problem type '{problem_type}'.",
        }

    # Determine which models to train
    if requested_models:
        model_keys = [k for k in requested_models if k in available_keys]
        if not model_keys:
            # Fallback to all models for this problem type
            model_keys = available_keys
    else:
        model_keys = available_keys

    trained_rows: Dict[str, Any] = {}
    model_artifacts: Dict[str, Any] = {}
    ranked_rows: List[Dict[str, Any]] = []
    failed_rows: List[Dict[str, str]] = []
    model_params = model_params or {}

    for key in model_keys:
        spec = MODEL_CATALOG[key]
        try:
            if spec.get("kind") == "anomaly":
                details = _train_anomaly_model(
                    key,
                    spec,
                    X_train,
                    y_train,
                    cv_splits=governed_splits,
                    primary_metric=metric_name,
                    positive_class=positive_class,
                    selection_partition_id=selection_partition_id,
                    fold_definition_id=fold_definition_id,
                    selection_created_at=selection_created_at,
                )
            elif spec["task"] == "classification":
                details = _train_classification_model(
                    key,
                    spec,
                    X_train,
                    y_train,
                    grid_search=grid_search,
                    grid_search_level=grid_search_level,
                    model_params=model_params.get(key) or {},
                    calibrate=calibrate,
                    cv_folds=cv_folds,
                    cv_splits=governed_splits,
                    primary_metric=metric_name,
                    positive_class=positive_class,
                    selection_partition_id=selection_partition_id,
                    fold_definition_id=fold_definition_id,
                    selection_created_at=selection_created_at,
                )
            else:
                details = _train_regression_model(
                    key,
                    spec,
                    X_train,
                    y_train,
                    grid_search=grid_search,
                    grid_search_level=grid_search_level,
                    cv_folds=cv_folds,
                    cv_splits=governed_splits,
                    primary_metric=metric_name,
                    selection_partition_id=selection_partition_id,
                    fold_definition_id=fold_definition_id,
                    selection_created_at=selection_created_at,
                )
        except Exception as exc:
            failed_rows.append(
                {
                    "key": key,
                    "name": spec.get("label", key),
                    "error": str(exc),
                }
            )
            details = None

        if not details:
            if not any(row["key"] == key for row in failed_rows):
                failed_rows.append(
                    {
                        "key": key,
                        "name": spec.get("label", key),
                        "error": "Model library is unavailable or model could not be initialized.",
                    }
                )
            continue

        trained_rows[key] = details
        model_artifacts[key] = details.get("model")
        m = details["metrics"]
        json_details = {k: v for k, v in details.items() if k != "model"}
        trained_rows[key] = json_details

        # Populate a consistent row; unused metrics remain None for regression.
        ranked_rows.append(
            {
                "key": key,
                "name": details["name"],
                "task": details["task"],
                "kind": details.get("kind", "supervised"),
                "champion_eligible": bool(details.get("champion_eligible", True)),
                "fit_sample_count": details.get("fit_sample_count"),
                "target_usage": details.get("target_usage"),
                "auc": m.get("auc"),
                "pr_auc": m.get("pr_auc"),
                "accuracy": m.get("accuracy"),
                "f1": m.get("f1"),
                "precision": m.get("precision"),
                "recall": m.get("recall"),
                "ks": m.get("ks"),
                "gini": m.get("gini"),
                "best_params": details.get("best_params"),
                "best_score": details.get("best_score"),
                "parameter_grid": details.get("parameter_grid") or {},
                "search_runtime_ms": details.get("search_runtime_ms", 0),
                "runtime_profile": details.get("runtime_profile"),
                "calibration_applied": bool(details.get("calibration_applied")),
                "calibration_method": details.get("calibration_method"),
                "selection_metric": details.get("selection_metric"),
                "locked_threshold": details.get("locked_threshold"),
                "selection_integrity_status": details.get("selection_integrity_status"),
                "holdout_isolation_status": details.get("holdout_isolation_status"),
                "selection_balancing_status": str(balancing_status or "not_applied"),
                "class_encoding": details.get("class_encoding"),
                "mae": m.get("mae"),
                "mse": m.get("mse"),
                "rmse": m.get("rmse"),
                "r2": m.get("r2"),
                "adjusted_r2": m.get("adjusted_r2"),
            }
        )

    if not ranked_rows:
        first_errors = "; ".join(
            f"{row.get('name', row.get('key'))}: {str(row.get('error', 'failed')).splitlines()[0]}"
            for row in failed_rows[:3]
        )
        return {
            "ok": False,
            "error": f"No models were successfully trained. {first_errors}".strip(),
            "summary": {
                "problem_type": problem_type,
                "ranked": [],
                "raw": {},
                "failed": failed_rows,
            },
        }

    # Ranking:
    #   • Classification: by AUC
    #   • Regression: by R²
    ranked_rows.sort(
        key=lambda row: selection_sort_key(row, metric_name, problem_type)
    )

    summary = {
        "problem_type": problem_type,
        "primary_metric": metric_name,
        "selection_partition_id": selection_partition_id,
        "fold_definition_id": fold_definition_id,
        "selection_integrity_status": "verified",
        "holdout_isolation_status": "verified",
        "selection_balancing_status": str(balancing_status or "not_applied"),
        "ranked": ranked_rows,
        "raw": trained_rows,
        "failed": failed_rows,
        "_artifacts": model_artifacts,
    }

    return {
        "ok": True,
        "summary": summary,
        "models": trained_rows,
    }
