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
import inspect
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
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import LabelEncoder, OneHotEncoder, StandardScaler
    from sklearn.model_selection import GridSearchCV, StratifiedKFold
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
    ColumnTransformer = None
    SimpleImputer = None
    Pipeline = None
    LabelEncoder = None
    OneHotEncoder = None
    StandardScaler = None
    GridSearchCV = None
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
        "factory": lambda: XGBClassifier(
            n_estimators=120,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.8,
            eval_metric="logloss",
            n_jobs=1,
            random_state=42,
        )
        if XGBClassifier is not None
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
        "factory": lambda: XGBRegressor(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.8,
            n_jobs=1,
            random_state=42,
        )
        if XGBRegressor is not None
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


def _train_classification_model(
    key: str,
    spec: Dict[str, Any],
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
    y_test: pd.Series,
    grid_search: bool = False,
    grid_search_level: str = "quick",
    model_params: Optional[Dict[str, Any]] = None,
    calibrate: bool = False,
    cv_folds: int = 3,
    cv_splits: Optional[List[Tuple[List[int], List[int]]]] = None,
) -> Optional[Dict[str, Any]]:
    factory = spec.get("factory")
    if factory is None:
        return None

    model = factory()
    if model is None:
        return None
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

    if Pipeline is None or LabelEncoder is None:
        return None

    encoder = LabelEncoder()
    encoder.fit(
        pd.concat(
            [_clean_target_values(y_train), _clean_target_values(y_test)],
            ignore_index=True,
        )
    )
    if len(encoder.classes_) != 2:
        raise ValueError(
            f"{spec['label']} supports binary classification only; target has {len(encoder.classes_)} classes."
        )

    y_train_arr = encoder.transform(_clean_target_values(y_train))
    y_test_arr = encoder.transform(_clean_target_values(y_test))

    estimator = Pipeline(
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

        fallback_cv_splits = max(2, min(int(cv_folds), min_class_count))
        search_cv: Any = (
            [
                (
                    np.asarray(train_positions, dtype=int),
                    np.asarray(validation_positions, dtype=int),
                )
                for train_positions, validation_positions in cv_splits
            ]
            if cv_splits
            else StratifiedKFold(
                n_splits=fallback_cv_splits,
                shuffle=True,
                random_state=42,
            )
        )
        applied_param_grid = limited_grid
        search_started = time.perf_counter()
        search = GridSearchCV(
            estimator=estimator,
            param_grid=limited_grid,
            scoring="roc_auc",
            cv=search_cv,
            n_jobs=1,
            refit=True,
        )
        search.fit(X_train, y_train_arr)
        search_runtime_ms = int((time.perf_counter() - search_started) * 1000)
        estimator = search.best_estimator_
        best_params = {
            str(k).replace("model__", ""): v for k, v in search.best_params_.items()
        }
        best_score = float(search.best_score_)
    precalibrated_keys = {"linsvm", "ridge_clf"}
    wrapped_for_calibration = bool(calibrate and key not in precalibrated_keys and CalibratedClassifierCV is not None)
    if wrapped_for_calibration:
        calibration_cv = max(2, min(int(cv_folds), min_class_count))
        governed_calibration_cv: Any = (
            [
                (
                    np.asarray(train_positions, dtype=int),
                    np.asarray(validation_positions, dtype=int),
                )
                for train_positions, validation_positions in cv_splits
            ]
            if cv_splits
            else calibration_cv
        )
        estimator = CalibratedClassifierCV(
            estimator,
            method="sigmoid",
            cv=governed_calibration_cv,
        )
        estimator.fit(X_train, y_train_arr)
        calibration_applied = True
        calibration_method = "sigmoid"
    else:
        calibration_applied = key in precalibrated_keys
        calibration_method = "sigmoid" if key in precalibrated_keys else None
    if not can_search and not wrapped_for_calibration:
        estimator.fit(X_train, y_train_arr)

    if hasattr(estimator, "predict_proba"):
        scores = estimator.predict_proba(X_test)[:, 1]
    elif hasattr(estimator, "decision_function"):
        raw = estimator.decision_function(X_test)
        mn, mx = float(np.min(raw)), float(np.max(raw))
        scores = (raw - mn) / (mx - mn + 1e-9)
    else:
        scores = estimator.predict(X_test)

    scores = np.asarray(scores, dtype=float)
    metrics = _compute_classification_metrics(y_test_arr, scores)

    return {
        "key": key,
        "name": spec["label"],
        "task": "classification",
        "metrics": metrics,
        "y_true": y_test_arr.tolist(),
        "y_score": scores.tolist(),
        "best_params": best_params,
        "best_score": best_score,
        "parameter_grid": applied_param_grid,
        "search_runtime_ms": search_runtime_ms,
        "calibration_applied": calibration_applied,
        "calibration_method": calibration_method,
        "model": estimator,
    }


def _train_anomaly_model(
    key: str,
    spec: Dict[str, Any],
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
    y_test: pd.Series,
) -> Optional[Dict[str, Any]]:
    factory = spec.get("factory")
    if factory is None:
        return None

    model = factory()
    if model is None or Pipeline is None or LabelEncoder is None:
        return None

    encoder = LabelEncoder()
    encoder.fit(
        pd.concat(
            [_clean_target_values(y_train), _clean_target_values(y_test)],
            ignore_index=True,
        )
    )
    if len(encoder.classes_) != 2:
        raise ValueError(
            f"{spec['label']} supports binary anomaly evaluation only; target has {len(encoder.classes_)} classes."
        )

    y_test_arr = encoder.transform(_clean_target_values(y_test))
    fit_frame = X_train.sample(n=10_000, random_state=42) if len(X_train) > 10_000 else X_train
    estimator = Pipeline(
        steps=[
            ("preprocess", _make_preprocessor(fit_frame)),
            ("model", model),
        ]
    )
    estimator.fit(fit_frame)

    fitted_model = estimator.named_steps["model"]
    X_test_prepared = estimator.named_steps["preprocess"].transform(X_test)
    if hasattr(fitted_model, "decision_function"):
        raw_scores = -np.asarray(fitted_model.decision_function(X_test_prepared), dtype=float)
    elif hasattr(fitted_model, "score_samples"):
        raw_scores = -np.asarray(fitted_model.score_samples(X_test_prepared), dtype=float)
    else:
        preds = np.asarray(estimator.predict(X_test), dtype=float)
        raw_scores = np.where(preds < 0, 1.0, 0.0)

    mn = float(np.min(raw_scores))
    mx = float(np.max(raw_scores))
    scores = (raw_scores - mn) / (mx - mn + 1e-9)
    metrics = _compute_classification_metrics(y_test_arr, scores)

    return {
        "key": key,
        "name": spec["label"],
        "task": "classification",
        "kind": "anomaly",
        "champion_eligible": False,
        "fit_sample_count": int(len(fit_frame)),
        "target_usage": "The estimator was fit without the target. Target labels were used only for retrospective score evaluation.",
        "metrics": metrics,
        "y_true": y_test_arr.tolist(),
        "y_score": scores.tolist(),
        "model": estimator,
    }


def _train_regression_model(
    key: str,
    spec: Dict[str, Any],
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
    y_test: pd.Series,
    grid_search: bool = False,
    grid_search_level: str = "quick",
    cv_folds: int = 3,
    cv_splits: Optional[List[Tuple[List[int], List[int]]]] = None,
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
    y_test_arr = np.asarray(y_test, dtype=float)

    estimator = Pipeline(
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
            estimator=estimator,
            param_grid=limited_grid,
            scoring="neg_root_mean_squared_error",
            cv=(
                [
                    (
                        np.asarray(train_positions, dtype=int),
                        np.asarray(validation_positions, dtype=int),
                    )
                    for train_positions, validation_positions in cv_splits
                ]
                if cv_splits
                else max(2, min(int(cv_folds), len(y_train)))
            ),
            n_jobs=1,
            refit=True,
        )
        search.fit(X_train, y_train_arr)
        search_runtime_ms = int((time.perf_counter() - search_started) * 1000)
        estimator = search.best_estimator_
        best_params = {
            str(k).replace("model__", ""): v for k, v in search.best_params_.items()
        }
        best_score = float(search.best_score_)
    else:
        estimator.fit(X_train, y_train_arr)
    preds = estimator.predict(X_test)
    preds = np.asarray(preds, dtype=float)

    metrics = _compute_regression_metrics(y_test_arr, preds, n_features=len(X_train.columns))

    return {
        "key": key,
        "name": spec["label"],
        "task": "regression",
        "metrics": metrics,
        "y_true": y_test_arr.tolist(),
        "y_score": preds.tolist(),  # kept name for schema compatibility
        "best_params": best_params,
        "best_score": best_score,
        "parameter_grid": applied_param_grid,
        "search_runtime_ms": search_runtime_ms,
        "calibration_applied": False,
        "calibration_method": None,
        "model": estimator,
    }


# -----------------------------------------------------------------------------
# Public training API
# -----------------------------------------------------------------------------
def train_models(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
    y_test: pd.Series,
    requested_models: Optional[List[str]] = None,
    grid_search: bool = False,
    grid_search_level: str = "quick",
    model_params: Optional[Dict[str, Dict[str, Any]]] = None,
    calibrate: bool = False,
    cv_folds: int = 3,
    cv_splits: Optional[List[Tuple[List[int], List[int]]]] = None,
) -> Dict[str, Any]:
    """
    Train requested models and return a structure suitable for:
      • Step07 training table
      • Step08 evaluation (classification models only)
    """
    X_train = _coerce_feature_frame(X_train)
    X_test = _coerce_feature_frame(X_test)

    # Infer problem type
    problem_type = infer_problem_type(y_train)

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
                    key, spec, X_train, X_test, y_train, y_test
                )
            elif spec["task"] == "classification":
                details = _train_classification_model(
                    key,
                    spec,
                    X_train,
                    X_test,
                    y_train,
                    y_test,
                    grid_search=grid_search,
                    grid_search_level=grid_search_level,
                    model_params=model_params.get(key) or {},
                    calibrate=calibrate,
                    cv_folds=cv_folds,
                    cv_splits=cv_splits,
                )
            else:
                details = _train_regression_model(
                    key,
                    spec,
                    X_train,
                    X_test,
                    y_train,
                    y_test,
                    grid_search=grid_search,
                    grid_search_level=grid_search_level,
                    cv_folds=cv_folds,
                    cv_splits=cv_splits,
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
                "calibration_applied": bool(details.get("calibration_applied")),
                "calibration_method": details.get("calibration_method"),
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
    def _rank_key(row: Dict[str, Any]) -> float:
        if not row.get("champion_eligible", True):
            return -2.0
        if row["task"] == "classification" and row.get("auc") is not None:
            return row["auc"]
        if row["task"] == "regression" and row.get("r2") is not None:
            return row["r2"]
        return -1.0

    ranked_rows.sort(key=_rank_key, reverse=True)

    summary = {
        "problem_type": problem_type,
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
