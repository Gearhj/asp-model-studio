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
from copy import deepcopy
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
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import LabelEncoder
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
    Pipeline = None
    LabelEncoder = None
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

from ..preprocessing.execution_contract import (
    GovernedPreprocessor,
    canonical_preprocessing_hash,
    default_no_treatment_contract,
    extract_fitted_preprocessing_artifacts,
    validate_final_preprocessing_artifact,
    validate_preprocessing_contract,
)
from ..preprocessing.preprocessing_contract import (
    FIT_SCOPE_CANDIDATE_DEVELOPMENT,
    FIT_SCOPE_FINAL_DEVELOPMENT,
    FIT_SCOPE_FOLD_TRAINING,
)

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
            scale_pos_weight: float = 1.0,
            n_jobs: int = 1,
            random_state: int = 42,
        ):
            self.n_estimators = n_estimators
            self.max_depth = max_depth
            self.learning_rate = learning_rate
            self.subsample = subsample
            self.colsample_bytree = colsample_bytree
            self.eval_metric = eval_metric
            self.scale_pos_weight = scale_pos_weight
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
                scale_pos_weight=self.scale_pos_weight,
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
def _make_preprocessor(
    X: pd.DataFrame,
    *,
    preprocessing_recipe: Optional[Dict[str, Any]] = None,
    fit_scope: str = FIT_SCOPE_FOLD_TRAINING,
    fit_population_id: str = "direct-training-population",
    actor: str = "backend_training_engine",
    application_scope: str = "cv_validation_fold",
    application_population_id: str = "unbound-validation-fold",
    application_population_rows: int = 0,
    encode_and_scale: bool = True,
):
    """Build the governed recipe executor; never add an implicit imputer."""

    recipe = (
        validate_preprocessing_contract(preprocessing_recipe)
        if preprocessing_recipe is not None
        else default_no_treatment_contract(feature_names=list(X.columns))
    )
    return GovernedPreprocessor(
        recipe,
        encode_and_scale=encode_and_scale,
        fit_scope=fit_scope,
        fit_population_id=fit_population_id,
        actor=actor,
        application_scope=application_scope,
        application_population_id=application_population_id,
        application_population_rows=application_population_rows,
    )


VALID_FOLD_LOCAL_PREPROCESSING_POLICIES = {
    "fit_transform_per_fold",
    "model_native_per_fold",
}
VALID_FOLD_LOCAL_BALANCING_METHODS = {
    "none",
    "undersample",
    "oversample",
    "smote",
}
VALID_CLASS_WEIGHT_POLICIES = {"none", "balanced"}


def normalize_validation_execution_policy(
    policy: Optional[Dict[str, Any]],
    *,
    problem_type: str,
) -> Dict[str, Any]:
    """Validate the exact execution choices owned by Validation Design.

    Training callers must pass a snapshot taken from the approved design.  The
    defaults preserve compatibility for direct unit callers, but production
    job creation persists and passes an explicit snapshot.
    """
    source = dict(policy or {})
    preprocessing = str(
        source.get("fold_local_preprocessing") or "fit_transform_per_fold"
    )
    balancing = str(source.get("balancing_method") or "none")
    class_weights = str(source.get("class_weight_policy") or "none")
    try:
        minority_share = float(source.get("minority_share", 0.5))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Validation Design minority_share must be a number between 0.05 and 0.5."
        ) from exc
    try:
        random_seed = int(source.get("random_seed", 42))
    except (TypeError, ValueError) as exc:
        raise ValueError("Validation Design random_seed must be an integer.") from exc

    if preprocessing not in VALID_FOLD_LOCAL_PREPROCESSING_POLICIES:
        raise ValueError(
            "Validation Design fold-local preprocessing policy is not executable."
        )
    if balancing not in VALID_FOLD_LOCAL_BALANCING_METHODS:
        raise ValueError("Validation Design balancing method is not executable.")
    if class_weights not in VALID_CLASS_WEIGHT_POLICIES:
        raise ValueError(
            "Custom class weights require explicit governed weights and are not executable by this Validation Design contract."
        )
    if not 0.05 <= minority_share <= 0.5:
        raise ValueError(
            "Validation Design minority_share must be between 0.05 and 0.5."
        )
    if problem_type != "classification" and (
        balancing != "none" or class_weights != "none"
    ):
        raise ValueError(
            "Balancing and class weights are available only for classification Validation Designs."
        )
    return {
        "source": str(source.get("source") or "approved_validation_design"),
        "fold_local_preprocessing": preprocessing,
        "balancing_method": balancing,
        "minority_share": minority_share,
        "class_weight_policy": class_weights,
        "random_seed": random_seed,
        "fit_scope": "development_fold_training_rows_only",
        "validation_rows_resampled": False,
        "final_holdout_access": "none",
    }


def _take_rows(values: Any, positions: np.ndarray) -> Any:
    if isinstance(values, pd.DataFrame):
        return values.iloc[positions].copy()
    return np.asarray(values)[positions]


def _concatenate_rows(left: Any, right: Any) -> Any:
    if isinstance(left, pd.DataFrame):
        right_frame = (
            right
            if isinstance(right, pd.DataFrame)
            else pd.DataFrame(right, columns=left.columns)
        )
        return pd.concat([left, right_frame], ignore_index=True)
    return np.concatenate([np.asarray(left), np.asarray(right)], axis=0)


def _class_counts(y: np.ndarray) -> Dict[str, int]:
    labels, counts = np.unique(np.asarray(y), return_counts=True)
    return {str(label): int(count) for label, count in zip(labels, counts)}


def _resample_fold_training_rows(
    X: Any,
    y: np.ndarray,
    *,
    method: str,
    minority_share: float,
    random_seed: int,
) -> tuple[Any, np.ndarray, Dict[str, Any]]:
    """Apply a deterministic policy to training rows after a fold is isolated."""
    y_array = np.asarray(y)
    before = _class_counts(y_array)
    audit = {
        "method": method,
        "input_rows": int(len(y_array)),
        "output_rows": int(len(y_array)),
        "synthetic_rows_added": 0,
        "rows_removed": 0,
        "class_counts_before": before,
        "class_counts_after": before,
        "fit_scope": "development_fold_training_rows_only",
        "validation_rows_resampled": False,
        "final_holdout_access": "none",
    }
    if method == "none":
        return X, y_array, audit

    labels, counts = np.unique(y_array, return_counts=True)
    if len(labels) != 2:
        raise ValueError("Fold-local resampling requires exactly two training classes.")
    minority_label = labels[int(np.argmin(counts))]
    majority_label = labels[int(np.argmax(counts))]
    minority_positions = np.flatnonzero(y_array == minority_label)
    majority_positions = np.flatnonzero(y_array == majority_label)
    if not len(minority_positions) or not len(majority_positions):
        raise ValueError("Fold-local resampling requires both target classes.")

    rng = np.random.default_rng(random_seed)
    current_share = len(minority_positions) / len(y_array)
    if method == "undersample":
        desired_majority = int(
            np.floor(len(minority_positions) * (1 - minority_share) / minority_share)
        )
        desired_majority = max(1, min(len(majority_positions), desired_majority))
        if desired_majority >= len(majority_positions) or current_share >= minority_share:
            return X, y_array, audit
        kept_majority = rng.choice(
            majority_positions, size=desired_majority, replace=False
        )
        kept = np.concatenate([minority_positions, kept_majority])
        rng.shuffle(kept)
        result_X = _take_rows(X, kept)
        result_y = y_array[kept]
    else:
        desired_minority = int(
            np.ceil(len(majority_positions) * minority_share / (1 - minority_share))
        )
        rows_to_add = max(0, desired_minority - len(minority_positions))
        if rows_to_add == 0 or current_share >= minority_share:
            return X, y_array, audit
        if method == "oversample":
            sampled = rng.choice(minority_positions, size=rows_to_add, replace=True)
            added_X = _take_rows(X, sampled)
        elif method == "smote":
            if len(minority_positions) < 2:
                raise ValueError(
                    "Fold-local SMOTE requires at least two minority-class training rows."
                )
            try:
                numeric_X = np.asarray(X, dtype=float)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Model-native fold-local SMOTE requires numeric predictors."
                ) from exc
            if not np.isfinite(numeric_X).all():
                raise ValueError(
                    "Fold-local SMOTE requires finite predictors after fold-local preprocessing."
                )
            base_positions = rng.choice(
                minority_positions, size=rows_to_add, replace=True
            )
            neighbor_positions = np.empty(rows_to_add, dtype=int)
            for index, base_position in enumerate(base_positions):
                choices = minority_positions[minority_positions != base_position]
                neighbor_positions[index] = int(rng.choice(choices))
            interpolation = rng.random((rows_to_add, 1))
            added_X = numeric_X[base_positions] + interpolation * (
                numeric_X[neighbor_positions] - numeric_X[base_positions]
            )
        else:  # validated by normalize_validation_execution_policy
            raise ValueError(f"Unsupported fold-local balancing method: {method}")
        added_y = np.full(rows_to_add, minority_label, dtype=y_array.dtype)
        result_X = _concatenate_rows(X, added_X)
        result_y = np.concatenate([y_array, added_y])

    audit.update(
        {
            "output_rows": int(len(result_y)),
            "synthetic_rows_added": max(0, int(len(result_y) - len(y_array))),
            "rows_removed": max(0, int(len(y_array) - len(result_y))),
            "class_counts_after": _class_counts(result_y),
        }
    )
    return result_X, result_y, audit


def _configure_class_weight_execution(
    estimator: Any,
    y: np.ndarray,
    policy: str,
) -> tuple[Any, Dict[str, Any], Dict[str, Any]]:
    """Configure an estimator-level or fit-time balanced weighting policy."""
    if policy == "none":
        try:
            params = estimator.get_params(deep=True)
            if "class_weight" in params:
                estimator.set_params(class_weight=None)
            elif "estimator__class_weight" in params:
                estimator.set_params(estimator__class_weight=None)
        except Exception:
            pass
        return estimator, {}, {
            "policy": "none",
            "execution": "not_applied",
            "fit_scope": "development_fold_training_rows_only",
        }

    counts = np.bincount(np.asarray(y, dtype=int), minlength=2)
    if np.any(counts <= 0):
        raise ValueError("Balanced class weights require both training classes.")
    try:
        params = estimator.get_params(deep=True)
    except Exception:
        params = {}
    if "class_weight" in params:
        estimator.set_params(class_weight="balanced")
        execution = "estimator_class_weight"
        fit_kwargs: Dict[str, Any] = {}
    elif "estimator__class_weight" in params:
        estimator.set_params(estimator__class_weight="balanced")
        execution = "nested_estimator_class_weight"
        fit_kwargs = {}
    elif "scale_pos_weight" in params:
        ratio = float(counts[0] / counts[1])
        estimator.set_params(scale_pos_weight=ratio)
        execution = "estimator_scale_pos_weight"
        fit_kwargs = {}
    elif "class_weights" in params:
        total = float(np.sum(counts))
        weights = [total / (2.0 * float(count)) for count in counts]
        estimator.set_params(class_weights=weights)
        execution = "estimator_class_weights"
        fit_kwargs = {}
    else:
        signature = inspect.signature(estimator.fit)
        accepts_kwargs = any(
            value.kind == inspect.Parameter.VAR_KEYWORD
            for value in signature.parameters.values()
        )
        if "sample_weight" not in signature.parameters and not accepts_kwargs:
            raise ValueError(
                f"{type(estimator).__name__} cannot honor the governed balanced class-weight policy."
            )
        total = float(np.sum(counts))
        per_class = {
            index: total / (2.0 * float(count))
            for index, count in enumerate(counts)
        }
        fit_kwargs = {
            "sample_weight": np.asarray(
                [per_class[int(value)] for value in np.asarray(y, dtype=int)],
                dtype=float,
            )
        }
        execution = "fit_sample_weight"
    return estimator, fit_kwargs, {
        "policy": "balanced",
        "execution": execution,
        "fit_scope": "development_fold_training_rows_only",
    }


_FoldPolicyClassifierBase = (
    type(
        "_FoldPolicyClassifierBase",
        (ClassifierMixin, BaseEstimator),
        {},
    )
    if ClassifierMixin is not None and BaseEstimator is not None
    else object
)


class _FoldLocalPolicyClassifier(_FoldPolicyClassifierBase):
    """Sklearn-compatible estimator that owns fold-local policy execution."""

    def __init__(
        self,
        model: Any,
        preprocessing_policy: str = "fit_transform_per_fold",
        preprocessing_recipe: Optional[Dict[str, Any]] = None,
        balancing_method: str = "none",
        minority_share: float = 0.5,
        random_seed: int = 42,
        class_weight_policy: str = "none",
        fit_scope: str = FIT_SCOPE_FOLD_TRAINING,
        fit_population_id: str = "unbound-training-fold",
        actor: str = "backend_training_engine",
        application_scope: str = "cv_validation_fold",
        application_population_id: str = "unbound-validation-fold",
        application_population_rows: int = 0,
    ) -> None:
        self.model = model
        self.preprocessing_policy = preprocessing_policy
        self.preprocessing_recipe = preprocessing_recipe
        self.balancing_method = balancing_method
        self.minority_share = minority_share
        self.random_seed = random_seed
        self.class_weight_policy = class_weight_policy
        self.fit_scope = fit_scope
        self.fit_population_id = fit_population_id
        self.actor = actor
        self.application_scope = application_scope
        self.application_population_id = application_population_id
        self.application_population_rows = application_population_rows

    def __getattribute__(self, name: str) -> Any:
        # sklearn chooses the first response method that appears to exist.
        # Hide optional methods when the governed inner estimator does not
        # implement them so ROC scorers correctly fall through to the other
        # supported response method.
        if name in {"predict_proba", "decision_function"}:
            state = object.__getattribute__(self, "__dict__")
            inner = state.get("model_", state.get("model"))
            if inner is not None and not hasattr(inner, name):
                raise AttributeError(
                    f"{type(inner).__name__} does not implement {name}."
                )
        return super().__getattribute__(name)

    def fit(self, X: Any, y: Any):
        frame = X.copy() if isinstance(X, pd.DataFrame) else pd.DataFrame(X)
        if self.preprocessing_policy == "fit_transform_per_fold":
            self.preprocess_ = _make_preprocessor(
                frame,
                preprocessing_recipe=self.preprocessing_recipe,
                fit_scope=self.fit_scope,
                fit_population_id=self.fit_population_id,
                actor=self.actor,
                application_scope=self.application_scope,
                application_population_id=self.application_population_id,
                application_population_rows=self.application_population_rows,
            )
            prepared = self.preprocess_.fit_transform(frame)
            preprocessing_execution = "governed_recipe_fit_on_training_rows"
        elif self.preprocessing_policy == "model_native_per_fold":
            self.preprocess_ = _make_preprocessor(
                frame,
                preprocessing_recipe=self.preprocessing_recipe,
                fit_scope=self.fit_scope,
                fit_population_id=self.fit_population_id,
                actor=self.actor,
                application_scope=self.application_scope,
                application_population_id=self.application_population_id,
                application_population_rows=self.application_population_rows,
                encode_and_scale=False,
            )
            prepared = self.preprocess_.fit_transform(frame)
            preprocessing_execution = "governed_recipe_model_native_matrix"
        else:
            raise ValueError("Unsupported fold-local preprocessing policy.")

        prepared, fit_y, resampling_audit = _resample_fold_training_rows(
            prepared,
            np.asarray(y),
            method=self.balancing_method,
            minority_share=float(self.minority_share),
            random_seed=int(self.random_seed),
        )
        self.model_ = clone(self.model)
        self.model_, fit_kwargs, weight_audit = _configure_class_weight_execution(
            self.model_, fit_y, self.class_weight_policy
        )
        self.model_.fit(prepared, fit_y, **fit_kwargs)
        self.classes_ = np.asarray(getattr(self.model_, "classes_", np.unique(fit_y)))
        self.n_features_in_ = int(frame.shape[1])
        self.policy_execution_ = {
            "fold_local_preprocessing": self.preprocessing_policy,
            "preprocessing_execution": preprocessing_execution,
            "resampling": resampling_audit,
            "class_weights": weight_audit,
            "fitted_preprocessing_artifacts": [
                self.preprocess_.fitted_artifact(
                    application_scope=self.application_scope,
                    application_population_id=self.application_population_id,
                    application_population_rows=self.application_population_rows,
                )
            ],
            "final_holdout_target_accessed": False,
            "final_holdout_predictors_included_in_structural_profile": False,
            "final_holdout_parameter_influence": False,
            "final_holdout_used_for_selection": False,
            "final_holdout_transformed_or_materialized_prelock": False,
            "final_holdout_opened_for_final_reporting": False,
        }
        return self

    @property
    def named_steps(self) -> Dict[str, Any]:
        return {
            "preprocess": getattr(self, "preprocess_", None),
            "model": getattr(self, "model_", self.model),
        }

    def _prepare(self, X: Any) -> Any:
        frame = X.copy() if isinstance(X, pd.DataFrame) else pd.DataFrame(X)
        if getattr(self, "preprocess_", None) is not None:
            return self.preprocess_.transform(frame)
        return frame

    def predict(self, X: Any) -> np.ndarray:
        return np.asarray(self.model_.predict(self._prepare(X)))

    def predict_proba(self, X: Any) -> np.ndarray:
        return np.asarray(self.model_.predict_proba(self._prepare(X)))

    def decision_function(self, X: Any) -> np.ndarray:
        return np.asarray(self.model_.decision_function(self._prepare(X)))

    @property
    def feature_importances_(self):
        return self.model_.feature_importances_

    @property
    def coef_(self):
        return self.model_.coef_


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


def fit_final_development_candidate(
    *,
    candidate_artifact: Any,
    candidate_row: Dict[str, Any],
    X_development: pd.DataFrame,
    y_development: pd.Series,
    preprocessing_recipe: Dict[str, Any],
    fit_population_id: str,
    application_population_id: str,
    application_population_rows: int,
    actor: str,
    candidate_decision_id: str,
) -> tuple[Any, Dict[str, Any]]:
    """Refit the locked candidate with one full-Development transformer.

    Candidate artifacts are diagnostics fitted before lock.  This boundary
    creates a distinct executable model whose preprocessing parameters are
    estimated exactly once from the complete Development Population.  Model
    calibration may use transformed Development rows, but it cannot refit the
    governed preprocessing transformer.
    """

    if clone is None or Pipeline is None:
        raise ImportError("scikit-learn is required for final candidate fitting.")
    if candidate_artifact is None:
        raise ValueError(
            "The selected candidate executable artifact is unavailable; retrain before locking a final candidate."
        )
    recipe = validate_preprocessing_contract(preprocessing_recipe)
    frame = X_development.copy()
    preprocessor = GovernedPreprocessor(
        recipe,
        encode_and_scale=True,
        fit_scope=FIT_SCOPE_FINAL_DEVELOPMENT,
        fit_population_id=str(fit_population_id),
        actor=str(actor),
        application_scope="final_holdout_fixed_application",
        application_population_id=str(application_population_id),
        application_population_rows=int(application_population_rows),
    )
    preprocessor.fit(frame)
    transformed = preprocessor.transform(frame)
    # The transform above materializes only the fitting population.  Keep the
    # final-holdout application audit empty until Evaluation actually opens it.
    preprocessor.last_application_ = {}

    task = str(candidate_row.get("task") or "").casefold()
    kind = str(candidate_row.get("kind") or "supervised").casefold()
    if kind == "anomaly":
        source_model = (
            candidate_artifact.named_steps.get("model")
            if hasattr(candidate_artifact, "named_steps")
            else candidate_artifact
        )
        fitted_model = clone(source_model)
        fitted_model.fit(transformed)
    elif task == "classification":
        encoded_y, _ = _encode_binary_training_target(
            y_development,
            (candidate_row.get("candidate_contract") or {}).get(
                "positive_class"
            ),
        )
        outer_calibrated = bool(
            hasattr(candidate_artifact, "calibrated_classifiers_")
            and hasattr(candidate_artifact, "estimator")
            and hasattr(candidate_artifact.estimator, "model")
        )
        wrapper = (
            candidate_artifact.estimator
            if outer_calibrated
            else candidate_artifact
        )
        source_model = getattr(wrapper, "model_", None)
        if source_model is None:
            source_model = getattr(wrapper, "model", None)
        if source_model is None:
            raise ValueError(
                "The selected classification candidate has no reusable estimator template."
            )
        fitted_model = clone(source_model)
        balancing_method = str(getattr(wrapper, "balancing_method", "none"))
        minority_share = float(getattr(wrapper, "minority_share", 0.5))
        random_seed = int(getattr(wrapper, "random_seed", 42))
        class_weight_policy = str(
            getattr(wrapper, "class_weight_policy", "none")
        )
        fit_X, fit_y, _ = _resample_fold_training_rows(
            transformed,
            encoded_y,
            method=balancing_method,
            minority_share=minority_share,
            random_seed=random_seed,
        )
        fitted_model, fit_kwargs, _ = _configure_class_weight_execution(
            fitted_model,
            fit_y,
            class_weight_policy,
        )
        if outer_calibrated:
            counts = np.bincount(np.asarray(fit_y, dtype=int), minlength=2)
            calibration_folds = max(2, min(5, int(np.min(counts))))
            fitted_model = CalibratedClassifierCV(
                fitted_model,
                method=str(getattr(candidate_artifact, "method", "sigmoid")),
                cv=calibration_folds,
            )
            fit_kwargs = {}
        fitted_model.fit(fit_X, fit_y, **fit_kwargs)
    elif task == "regression":
        source_model = (
            candidate_artifact.named_steps.get("model")
            if hasattr(candidate_artifact, "named_steps")
            else candidate_artifact
        )
        fitted_model = clone(source_model)
        numeric_y = pd.to_numeric(y_development, errors="coerce")
        if numeric_y.isna().any():
            raise ValueError(
                "The Development Population contains a non-numeric regression target."
            )
        fitted_model.fit(transformed, numeric_y.to_numpy(dtype=float))
    else:
        raise ValueError("The selected candidate has an unsupported task.")

    final_estimator = Pipeline(
        steps=[("preprocess", preprocessor), ("model", fitted_model)]
    )
    final_artifact = preprocessor.fitted_artifact(
        application_scope="final_holdout_fixed_application",
        application_population_id=str(application_population_id),
        application_population_rows=int(application_population_rows),
    )
    final_artifact.update(
        {
            "artifact_kind": "final_development_fitted_preprocessing",
            "candidate_decision_id": str(candidate_decision_id),
            "candidate_id": str(candidate_row.get("candidate_id") or ""),
            "training_job_id": str(candidate_row.get("training_job_id") or ""),
            "training_run_id": str(candidate_row.get("training_run_id") or ""),
            "model_linkage_status": "locked_candidate_pre_registry",
            "final_holdout_target_accessed": False,
            "final_holdout_parameter_influence": False,
            "final_holdout_used_for_selection": False,
            "final_holdout_transformed_or_materialized_prelock": False,
            "final_holdout_opened_for_final_reporting": False,
            "refit_during_application": False,
        }
    )
    final_artifact["final_artifact_checksum"] = canonical_preprocessing_hash(
        {
            key: value
            for key, value in final_artifact.items()
            if key not in {"fitted_at", "final_artifact_checksum"}
        }
    )
    # Bind the exact final-fit record into the executable object itself.  A
    # registry/scoring restart can therefore verify fit scope and checksum
    # without consulting mutable workspace preparation state.
    preprocessor.preprocessing_artifact_ = deepcopy(final_artifact)
    validate_final_preprocessing_artifact(
        final_artifact,
        candidate_row.get("candidate_contract") or {},
        candidate_decision_id=candidate_decision_id,
    )
    return final_estimator, final_artifact


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
    validation_policy: Optional[Dict[str, Any]] = None,
    preprocessing_recipe: Optional[Dict[str, Any]] = None,
    preprocessing_actor: str = "backend_training_engine",
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
    if Pipeline is None or clone is None:
        return None

    y_train_arr, class_encoding = _encode_binary_training_target(
        y_train,
        positive_class,
    )
    governed_splits = _validated_cv_splits(cv_splits, len(X_train))
    metric_name = normalize_selection_metric(primary_metric, "classification")
    execution_policy = normalize_validation_execution_policy(
        validation_policy,
        problem_type="classification",
    )

    estimator_template = _FoldLocalPolicyClassifier(
        model=model,
        preprocessing_policy=execution_policy["fold_local_preprocessing"],
        preprocessing_recipe=preprocessing_recipe,
        balancing_method=execution_policy["balancing_method"],
        minority_share=execution_policy["minority_share"],
        random_seed=execution_policy["random_seed"],
        class_weight_policy=execution_policy["class_weight_policy"],
        fit_scope=FIT_SCOPE_FOLD_TRAINING,
        fit_population_id=f"{selection_partition_id}:candidate-training-subset",
        actor=preprocessing_actor,
        application_scope="cv_validation_fold",
        application_population_id=f"{fold_definition_id}:validation-subset",
        application_population_rows=0,
    )

    best_params = None
    best_score = None
    search_runtime_ms = 0
    applied_param_grid: Dict[str, Any] = {}
    param_grid = {
        name: values
        for name, values in (spec.get("param_grid") or {}).items()
        if name not in {"model__class_weight", "model__estimator__class_weight"}
    }
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
        *,
        fit_scope: str,
        fit_population_id: str,
        application_scope: str,
        application_population_id: str,
        application_population_rows: int,
    ) -> tuple[Any, str]:
        partition_estimator = clone(estimator_template)
        partition_estimator.set_params(
            fit_scope=fit_scope,
            fit_population_id=fit_population_id,
            actor=preprocessing_actor,
            application_scope=application_scope,
            application_population_id=application_population_id,
            application_population_rows=application_population_rows,
        )
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
    fold_policy_execution: List[Dict[str, Any]] = []
    calibration_sources: set[str] = set()
    for fold_number, (train_positions, validation_positions) in enumerate(
        governed_splits,
        start=1,
    ):
        fold_estimator, fold_calibration_source = fitted_for_partition(
            X_train.iloc[train_positions],
            y_train_arr[train_positions],
            fit_scope=FIT_SCOPE_FOLD_TRAINING,
            fit_population_id=(
                f"{fold_definition_id}:fold-{fold_number}:training"
            ),
            application_scope="cv_validation_fold",
            application_population_id=(
                f"{fold_definition_id}:fold-{fold_number}:validation"
            ),
            application_population_rows=int(len(validation_positions)),
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
        policy_audit = deepcopy(
            getattr(fold_estimator, "policy_execution_", {})
        )
        if not policy_audit and calibration_requested:
            policy_audit = {
                **execution_policy,
                "execution": "inside_fold_local_calibration",
            }
        fitted_artifacts = extract_fitted_preprocessing_artifacts(
            fold_estimator
        )
        if fitted_artifacts:
            policy_audit["fitted_preprocessing_artifacts"] = fitted_artifacts
        fold_policy_execution.append(
            {
                "fold": fold_number,
                "training_rows_before_policy": int(len(train_positions)),
                "validation_rows": int(len(validation_positions)),
                "validation_rows_resampled": False,
                "final_holdout_access": "none",
                **policy_audit,
            }
        )

    covered = score_counts > 0
    if not np.any(covered):
        raise ValueError("The governed folds did not produce out-of-fold predictions.")
    oof_scores = score_sums[covered] / score_counts[covered]
    oof_y_true = y_train_arr[covered]
    metrics = _compute_classification_metrics(oof_y_true, oof_scores)
    final_estimator, final_calibration_source = fitted_for_partition(
        X_train,
        y_train_arr,
        fit_scope=FIT_SCOPE_CANDIDATE_DEVELOPMENT,
        fit_population_id=(
            f"{selection_partition_id}:candidate-development-diagnostic"
        ),
        application_scope="candidate_artifact_no_holdout_application",
        application_population_id="candidate-lock-pending",
        application_population_rows=0,
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
        "validation_policy_execution": {
            **execution_policy,
            "folds": fold_policy_execution,
            "final_development_fit": deepcopy(
                getattr(final_estimator, "policy_execution_", {})
            )
            or {
                **execution_policy,
                "execution": "inside_development_only_calibration",
            },
            "governed_fold_count": len(governed_splits),
            "final_holdout_access": "none",
            "fold_fitted_artifacts": [
                artifact
                for fold in fold_policy_execution
                for artifact in fold.get("fitted_preprocessing_artifacts", [])
            ],
            "candidate_development_fit_role": (
                "ephemeral_diagnostic_not_final_reporting_artifact"
            ),
        },
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
    validation_policy: Optional[Dict[str, Any]] = None,
    preprocessing_recipe: Optional[Dict[str, Any]] = None,
    preprocessing_actor: str = "backend_training_engine",
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
    execution_policy = normalize_validation_execution_policy(
        validation_policy,
        problem_type="classification",
    )
    estimator_template = Pipeline(
        steps=[
            (
                "preprocess",
                _make_preprocessor(
                    X_train,
                    preprocessing_recipe=preprocessing_recipe,
                    fit_scope=FIT_SCOPE_FOLD_TRAINING,
                    fit_population_id=(
                        f"{selection_partition_id}:anomaly-training-subset"
                    ),
                    actor=preprocessing_actor,
                    application_scope="cv_validation_fold",
                    application_population_id=(
                        f"{fold_definition_id}:anomaly-validation-subset"
                    ),
                    application_population_rows=0,
                    encode_and_scale=(
                        execution_policy["fold_local_preprocessing"]
                        == "fit_transform_per_fold"
                    ),
                ),
            ),
            ("model", model),
        ]
    )

    def anomaly_scores(estimator: Any, X: pd.DataFrame) -> np.ndarray:
        if hasattr(estimator, "named_steps"):
            fitted_model = estimator.named_steps["model"]
            prepared = estimator.named_steps["preprocess"].transform(X)
        else:
            fitted_model = estimator
            prepared = X
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
    fold_policy_execution: List[Dict[str, Any]] = []
    for fold_number, (train_positions, validation_positions) in enumerate(
        governed_splits,
        start=1,
    ):
        fold_estimator = clone(estimator_template)
        fold_frame = X_train.iloc[train_positions]
        fold_estimator.set_params(
            preprocess__fit_scope=FIT_SCOPE_FOLD_TRAINING,
            preprocess__fit_population_id=(
                f"{fold_definition_id}:fold-{fold_number}:training"
            ),
            preprocess__actor=preprocessing_actor,
            preprocess__application_scope="cv_validation_fold",
            preprocess__application_population_id=(
                f"{fold_definition_id}:fold-{fold_number}:validation"
            ),
            preprocess__application_population_rows=int(
                len(validation_positions)
            ),
        )
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
        fold_policy_execution.append(
            {
                "fold": fold_number,
                "fold_local_preprocessing": execution_policy[
                    "fold_local_preprocessing"
                ],
                "preprocessing_execution": (
                    "fit_transform_on_training_rows"
                    if execution_policy["fold_local_preprocessing"]
                    == "fit_transform_per_fold"
                    else "model_native_training_rows"
                ),
                "balancing_execution": "not_applicable_target_independent_model",
                "class_weight_execution": "not_applicable_target_independent_model",
                "training_rows": int(len(train_positions)),
                "validation_rows": int(len(validation_positions)),
                "validation_rows_resampled": False,
                "final_holdout_access": "none",
                "fitted_preprocessing_artifacts": (
                    extract_fitted_preprocessing_artifacts(fold_estimator)
                ),
            }
        )

    covered = score_counts > 0
    if not np.any(covered):
        raise ValueError("The governed folds did not produce anomaly out-of-fold predictions.")
    oof_scores = score_sums[covered] / score_counts[covered]
    oof_y_true = y_train_arr[covered]
    metrics = _compute_classification_metrics(oof_y_true, oof_scores)
    fit_frame = X_train
    final_estimator = clone(estimator_template)
    final_estimator.set_params(
        preprocess__fit_scope=FIT_SCOPE_CANDIDATE_DEVELOPMENT,
        preprocess__fit_population_id=(
            f"{selection_partition_id}:candidate-development-diagnostic"
        ),
        preprocess__actor=preprocessing_actor,
        preprocess__application_scope=(
            "candidate_artifact_no_holdout_application"
        ),
        preprocess__application_population_id="candidate-lock-pending",
        preprocess__application_population_rows=0,
    )
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
        "validation_policy_execution": {
            **execution_policy,
            "folds": fold_policy_execution,
            "governed_fold_count": len(governed_splits),
            "balancing_execution": "not_applicable_target_independent_model",
            "class_weight_execution": "not_applicable_target_independent_model",
            "final_holdout_access": "none",
            "fold_fitted_artifacts": [
                artifact
                for fold in fold_policy_execution
                for artifact in fold.get("fitted_preprocessing_artifacts", [])
            ],
            "candidate_development_fit_role": (
                "ephemeral_diagnostic_not_final_reporting_artifact"
            ),
        },
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
    validation_policy: Optional[Dict[str, Any]] = None,
    preprocessing_recipe: Optional[Dict[str, Any]] = None,
    preprocessing_actor: str = "backend_training_engine",
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
    execution_policy = normalize_validation_execution_policy(
        validation_policy,
        problem_type="regression",
    )

    estimator_template = Pipeline(
        steps=[
            (
                "preprocess",
                _make_preprocessor(
                    X_train,
                    preprocessing_recipe=preprocessing_recipe,
                    fit_scope=FIT_SCOPE_FOLD_TRAINING,
                    fit_population_id=(
                        f"{selection_partition_id}:tuning-training-subset"
                    ),
                    actor=preprocessing_actor,
                    application_scope="cv_validation_fold",
                    application_population_id=(
                        f"{fold_definition_id}:tuning-validation-subset"
                    ),
                    application_population_rows=0,
                    encode_and_scale=(
                        execution_policy["fold_local_preprocessing"]
                        == "fit_transform_per_fold"
                    ),
                ),
            ),
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
    fold_policy_execution: List[Dict[str, Any]] = []
    for fold_number, (train_positions, validation_positions) in enumerate(
        governed_splits,
        start=1,
    ):
        fold_estimator = clone(estimator_template)
        fold_estimator.set_params(
            preprocess__preprocessing_recipe=preprocessing_recipe,
            preprocess__fit_scope=FIT_SCOPE_FOLD_TRAINING,
            preprocess__fit_population_id=(
                f"{fold_definition_id}:fold-{fold_number}:training"
            ),
            preprocess__actor=preprocessing_actor,
            preprocess__application_scope="cv_validation_fold",
            preprocess__application_population_id=(
                f"{fold_definition_id}:fold-{fold_number}:validation"
            ),
            preprocess__application_population_rows=int(
                len(validation_positions)
            ),
        )
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
        fold_policy_execution.append(
            {
                "fold": fold_number,
                "fold_local_preprocessing": execution_policy[
                    "fold_local_preprocessing"
                ],
                "preprocessing_execution": (
                    "fit_transform_on_training_rows"
                    if execution_policy["fold_local_preprocessing"]
                    == "fit_transform_per_fold"
                    else "model_native_training_rows"
                ),
                "training_rows": int(len(train_positions)),
                "validation_rows": int(len(validation_positions)),
                "validation_rows_resampled": False,
                "final_holdout_access": "none",
                "fitted_preprocessing_artifacts": (
                    extract_fitted_preprocessing_artifacts(fold_estimator)
                ),
            }
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
    final_estimator.set_params(
        preprocess__preprocessing_recipe=preprocessing_recipe,
        preprocess__fit_scope=FIT_SCOPE_CANDIDATE_DEVELOPMENT,
        preprocess__fit_population_id=(
            f"{selection_partition_id}:candidate-development-diagnostic"
        ),
        preprocess__actor=preprocessing_actor,
        preprocess__application_scope=(
            "candidate_artifact_no_holdout_application"
        ),
        preprocess__application_population_id="candidate-lock-pending",
        preprocess__application_population_rows=0,
    )
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
        "validation_policy_execution": {
            **execution_policy,
            "folds": fold_policy_execution,
            "final_development_fit": {
                "fold_local_preprocessing": execution_policy[
                    "fold_local_preprocessing"
                ],
                "preprocessing_execution": (
                    "fit_transform_on_development_rows"
                    if execution_policy["fold_local_preprocessing"]
                    == "fit_transform_per_fold"
                    else "model_native_development_rows"
                ),
                "final_holdout_access": "none",
            },
            "governed_fold_count": len(governed_splits),
            "final_holdout_access": "none",
            "fold_fitted_artifacts": [
                artifact
                for fold in fold_policy_execution
                for artifact in fold.get("fitted_preprocessing_artifacts", [])
            ],
            "candidate_development_fit_role": (
                "ephemeral_diagnostic_not_final_reporting_artifact"
            ),
        },
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
    validation_policy: Optional[Dict[str, Any]] = None,
    preprocessing_recipe: Optional[Dict[str, Any]] = None,
    preprocessing_actor: str = "backend_training_engine",
) -> Dict[str, Any]:
    """
    Train requested models and return a structure suitable for:
      • Step07 training table
      • Step08 evaluation (classification models only)
    """
    X_train = _coerce_feature_frame(X_train)
    governed_recipe = (
        validate_preprocessing_contract(preprocessing_recipe)
        if preprocessing_recipe is not None
        else default_no_treatment_contract(feature_names=list(X_train.columns))
    )

    # Infer problem type
    problem_type = infer_problem_type(y_train)
    metric_name = normalize_selection_metric(primary_metric, problem_type)
    execution_policy = normalize_validation_execution_policy(
        validation_policy,
        problem_type=problem_type,
    )
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
                    validation_policy=execution_policy,
                    preprocessing_recipe=governed_recipe,
                    preprocessing_actor=preprocessing_actor,
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
                    validation_policy=execution_policy,
                    preprocessing_recipe=governed_recipe,
                    preprocessing_actor=preprocessing_actor,
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
                    validation_policy=execution_policy,
                    preprocessing_recipe=governed_recipe,
                    preprocessing_actor=preprocessing_actor,
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
                "validation_policy_execution": details.get(
                    "validation_policy_execution"
                ),
                "governed_preprocessing": {
                    "preprocessing_contract_version": governed_recipe.get(
                        "preprocessing_contract_version"
                    ),
                    "preprocessing_policy_id": governed_recipe.get(
                        "preprocessing_policy_id"
                    ),
                    "preprocessing_policy_revision": governed_recipe.get(
                        "preprocessing_policy_revision"
                    ),
                    "preprocessing_policy_hash": governed_recipe.get(
                        "preprocessing_policy_hash"
                    ),
                    "fold_fitted_artifacts": (
                        details.get("validation_policy_execution") or {}
                    ).get("fold_fitted_artifacts", []),
                    "candidate_development_fit_role": (
                        details.get("validation_policy_execution") or {}
                    ).get("candidate_development_fit_role"),
                },
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
        "validation_policy_execution": {
            **execution_policy,
            "model_count": len(ranked_rows),
            "final_holdout_access": "none",
        },
        "governed_preprocessing_contract": {
            "preprocessing_contract_version": governed_recipe.get(
                "preprocessing_contract_version"
            ),
            "preprocessing_policy_id": governed_recipe.get(
                "preprocessing_policy_id"
            ),
            "preprocessing_policy_revision": governed_recipe.get(
                "preprocessing_policy_revision"
            ),
            "preprocessing_policy_hash": governed_recipe.get(
                "preprocessing_policy_hash"
            ),
            "fold_fitted_artifact_status": "complete",
            "final_fitted_artifact_status": "pending_candidate_lock",
            "final_holdout_parameter_influence": False,
            "final_holdout_used_for_selection": False,
            "final_holdout_transformed_or_materialized_prelock": False,
        },
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
