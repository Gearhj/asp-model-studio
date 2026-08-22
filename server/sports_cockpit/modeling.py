"""Fold-local preprocessing, model families, and challenger experiments for the cockpit.

Every learned statistic is fitted on the development season (2023) only. The frozen final
season (2025) never participates in fitting/tuning/selection. Evaluation is delegated to the
shared ``server.sports_modeling.metrics.evaluate_multiclass`` authority so cockpit challengers
are numerically comparable to the registered D3 champion.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier

from server.sports_modeling.metrics import PA_CLASS_ORDER, encode_labels, evaluate_multiclass

from . import engine as E
from . import features_builder as FB
from .engine import (
    ALL_FEATURES,
    BINARY_FEATURES,
    CATEGORICAL_VALUES,
    COCKPIT_ROOT,
    COCKPIT_SCHEMA_VERSION,
    CONTINUOUS_FEATURES,
    DEV_SEASON,
    FROZEN_SEASON,
    VAL_SEASON,
    CockpitError,
    feature_kind,
    load_frame,
)


def working_frame(config: Mapping[str, Any]) -> tuple[Any, list[str]]:
    """Frame with any engineered features materialized, plus their names."""
    frame, names = FB.apply_engineered(load_frame(), config.get("engineeredFeatures") or [])
    return frame, names

_XGB = None
_LGBM = None
try:  # optional, both confirmed installed but keep import fail-closed
    import xgboost as _xgb_mod

    _XGB = _xgb_mod
except Exception:  # pragma: no cover
    _XGB = None
try:
    import lightgbm as _lgbm_mod

    _LGBM = _lgbm_mod
except Exception:  # pragma: no cover
    _LGBM = None


AVAILABLE_FAMILIES = {
    "logistic": True,
    "random_forest": True,
    "extra_trees": True,
    "hist_gradient_boosting": True,
    "mlp": True,
    "xgboost": _XGB is not None,
    "lightgbm": _LGBM is not None,
    "svm": True,  # LinearSVC + calibration on a bounded sample
}

# Simulator whole-game replay requires a multinomial-logistic authority (Phase 5 FastD3Fold).
SIMULATOR_ELIGIBLE_FAMILIES = {"logistic"}


# ----------------------------------------------------------------------------------------
# Outlier + missing policy (fold-local)
# ----------------------------------------------------------------------------------------
def _outlier_bounds(values: np.ndarray, method: str, params: Mapping[str, Any]) -> tuple[float, float] | None:
    finite = values[np.isfinite(values)]
    if finite.size == 0 or method in (None, "none"):
        return None
    if method == "iqr":
        k = float(params.get("k", 1.5))
        q1, q3 = np.percentile(finite, [25, 75])
        iqr = q3 - q1
        return float(q1 - k * iqr), float(q3 + k * iqr)
    if method == "mad":
        k = float(params.get("k", 3.0))
        med = float(np.median(finite))
        mad = float(np.median(np.abs(finite - med))) or 1e-9
        return med - k * 1.4826 * mad, med + k * 1.4826 * mad
    if method == "zscore":
        k = float(params.get("k", 3.0))
        mu, sd = float(finite.mean()), float(finite.std()) or 1e-9
        return mu - k * sd, mu + k * sd
    if method in ("percentile", "winsorize"):
        lo = float(params.get("lower", 1.0))
        hi = float(params.get("upper", 99.0))
        return float(np.percentile(finite, lo)), float(np.percentile(finite, hi))
    return None


@dataclass
class Preprocessor:
    features: tuple[str, ...]
    outlier_policy: dict[str, Any]
    missing_policy: dict[str, Any]
    state: dict[str, dict[str, Any]] = field(default_factory=dict)
    add_indicator: bool = False
    expanded_names: list[str] = field(default_factory=list)

    @classmethod
    def fit(
        cls,
        frame: pd.DataFrame,
        features: Sequence[str],
        outlier_policy: Mapping[str, Any] | None,
        missing_policy: Mapping[str, Any] | None,
    ) -> "Preprocessor":
        outlier_policy = dict(outlier_policy or {"globalMethod": "none", "overrides": {}})
        missing_policy = dict(missing_policy or {"globalMethod": "median", "overrides": {}})
        add_indicator = bool(missing_policy.get("addIndicator", False))
        dev_mask = frame["season"].to_numpy() == DEV_SEASON
        state: dict[str, dict[str, Any]] = {}
        expanded: list[str] = []
        for name in features:
            kind = feature_kind(name)
            dev_vals = frame[name].to_numpy()[dev_mask]
            if kind == "categorical":
                state[name] = {"kind": "categorical", "categories": list(CATEGORICAL_VALUES[name])}
                expanded.extend(f"{name}={c}" for c in CATEGORICAL_VALUES[name])
                continue
            # outlier bounds (continuous only)
            bounds = None
            if kind == "continuous":
                ov = dict(outlier_policy.get("overrides", {}).get(name, {}))
                method = ov.get("method", outlier_policy.get("globalMethod", "none"))
                params = ov.get("params", outlier_policy.get("params", {}))
                if "lower" in ov and "upper" in ov and method not in ("iqr", "mad", "zscore"):
                    bounds = (float(ov["lower"]), float(ov["upper"]))
                else:
                    bounds = _outlier_bounds(dev_vals, method, params)
            clipped = dev_vals.copy()
            if bounds is not None:
                clipped = np.clip(clipped, bounds[0], bounds[1])
            # missing fill
            mv = dict(missing_policy.get("overrides", {}).get(name, {}))
            mmethod = mv.get("method", missing_policy.get("globalMethod", "median"))
            finite = clipped[np.isfinite(clipped)]
            if mmethod == "mean":
                fill = float(finite.mean()) if finite.size else 0.0
            elif mmethod == "most_frequent":
                fill = float(pd.Series(finite).mode().iloc[0]) if finite.size else 0.0
            elif mmethod == "constant":
                fill = float(mv.get("value", missing_policy.get("constant", 0.0)))
            else:  # median (default) / indicator_median
                fill = float(np.median(finite)) if finite.size else 0.0
            imputed = np.where(np.isfinite(clipped), clipped, fill)
            mean = float(imputed.mean())
            scale = float(imputed.std()) or 1.0
            state[name] = {
                "kind": kind,
                "outlierBounds": bounds,
                "imputeFill": fill,
                "imputeMethod": mmethod,
                "standMean": mean,
                "standScale": scale,
            }
            expanded.append(name)
            if add_indicator and kind == "continuous":
                expanded.append(f"{name}__missing")
        return cls(
            features=tuple(features),
            outlier_policy=outlier_policy,
            missing_policy=missing_policy,
            state=state,
            add_indicator=add_indicator,
            expanded_names=expanded,
        )

    def transform(self, frame: pd.DataFrame, mask: np.ndarray) -> np.ndarray:
        columns: list[np.ndarray] = []
        for name in self.features:
            st = self.state[name]
            vals = frame[name].to_numpy()[mask]
            if st["kind"] == "categorical":
                for c in st["categories"]:
                    columns.append((vals == c).astype(np.float64)[:, None])
                continue
            missing_mask = ~np.isfinite(vals)
            clipped = vals
            if st.get("outlierBounds") is not None:
                lo, hi = st["outlierBounds"]
                clipped = np.clip(vals, lo, hi)
            imputed = np.where(np.isfinite(clipped), clipped, st["imputeFill"])
            standardized = (imputed - st["standMean"]) / st["standScale"]
            columns.append(standardized[:, None])
            if self.add_indicator and st["kind"] == "continuous":
                columns.append(missing_mask.astype(np.float64)[:, None])
        if not columns:
            return np.empty((int(mask.sum()), 0), dtype=np.float64)
        return np.ascontiguousarray(np.concatenate(columns, axis=1), dtype=np.float64)


# ----------------------------------------------------------------------------------------
# Model families
# ----------------------------------------------------------------------------------------
def _build_estimator(family: str, hyper: Mapping[str, Any]):
    hyper = dict(hyper or {})
    if family == "logistic":
        # lbfgs is multinomial by default in sklearn >=1.5; omit multi_class to avoid deprecation.
        return LogisticRegression(
            C=float(hyper.get("C", 1.0)),
            max_iter=int(hyper.get("maxIter", 2000)),
            solver="lbfgs",
        )
    if family == "random_forest":
        return RandomForestClassifier(
            n_estimators=int(hyper.get("nEstimators", 200)),
            max_depth=hyper.get("maxDepth", 12) and int(hyper.get("maxDepth", 12)),
            min_samples_leaf=int(hyper.get("minSamplesLeaf", 50)),
            max_features=hyper.get("maxFeatures", "sqrt"),
            n_jobs=-1,
            random_state=20260819,
        )
    if family == "extra_trees":
        return ExtraTreesClassifier(
            n_estimators=int(hyper.get("nEstimators", 200)),
            max_depth=hyper.get("maxDepth", 14) and int(hyper.get("maxDepth", 14)),
            min_samples_leaf=int(hyper.get("minSamplesLeaf", 50)),
            max_features=hyper.get("maxFeatures", "sqrt"),
            n_jobs=-1,
            random_state=20260819,
        )
    if family == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(
            learning_rate=float(hyper.get("learningRate", 0.1)),
            max_iter=int(hyper.get("maxIter", 200)),
            max_depth=hyper.get("maxDepth", None) and int(hyper.get("maxDepth")),
            l2_regularization=float(hyper.get("l2", 0.0)),
            random_state=20260819,
        )
    if family == "mlp":
        layers = tuple(int(x) for x in hyper.get("hiddenLayers", [64, 32]))
        return MLPClassifier(
            hidden_layer_sizes=layers,
            alpha=float(hyper.get("alpha", 1e-4)),
            learning_rate_init=float(hyper.get("learningRate", 1e-3)),
            max_iter=int(hyper.get("maxIter", 80)),
            early_stopping=True,
            random_state=20260819,
        )
    if family == "xgboost":
        if _XGB is None:
            raise CockpitError("xgboost is not installed")
        return _XGB.XGBClassifier(
            n_estimators=int(hyper.get("nEstimators", 300)),
            max_depth=int(hyper.get("maxDepth", 6)),
            learning_rate=float(hyper.get("learningRate", 0.1)),
            subsample=float(hyper.get("subsample", 0.8)),
            colsample_bytree=float(hyper.get("colsampleBytree", 0.8)),
            objective="multi:softprob",
            num_class=len(PA_CLASS_ORDER),
            tree_method="hist",
            n_jobs=-1,
            random_state=20260819,
        )
    if family == "lightgbm":
        if _LGBM is None:
            raise CockpitError("lightgbm is not installed")
        return _LGBM.LGBMClassifier(
            n_estimators=int(hyper.get("nEstimators", 300)),
            num_leaves=int(hyper.get("numLeaves", 31)),
            learning_rate=float(hyper.get("learningRate", 0.1)),
            subsample=float(hyper.get("subsample", 0.8)),
            n_jobs=-1,
            random_state=20260819,
            verbose=-1,
        )
    if family == "svm":
        from sklearn.svm import LinearSVC
        from sklearn.calibration import CalibratedClassifierCV

        base = LinearSVC(C=float(hyper.get("C", 1.0)), max_iter=int(hyper.get("maxIter", 3000)))
        return CalibratedClassifierCV(base, method="sigmoid", cv=3)
    raise CockpitError(f"unknown model family: {family}")


def _predict_proba_aligned(estimator, X: np.ndarray) -> np.ndarray:
    """Return (n, 8) probabilities aligned to PA_CLASS_ORDER encoding 0..7."""
    proba = np.asarray(estimator.predict_proba(X), dtype=np.float64)
    classes = np.asarray(estimator.classes_)
    n_classes = len(PA_CLASS_ORDER)
    if proba.shape[1] == n_classes and np.array_equal(classes, np.arange(n_classes)):
        out = proba
    else:
        out = np.zeros((proba.shape[0], n_classes), dtype=np.float64)
        for col, cls in enumerate(classes):
            out[:, int(cls)] = proba[:, col]
    # renormalize defensively
    row_sums = out.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    return out / row_sums


def _feature_importance(estimator, family: str, expanded: Sequence[str]) -> list[dict[str, Any]]:
    try:
        if family == "logistic":
            coef = np.abs(np.asarray(estimator.coef_)).mean(axis=0)
        elif family in ("random_forest", "extra_trees", "hist_gradient_boosting", "xgboost", "lightgbm"):
            imp = getattr(estimator, "feature_importances_", None)
            if imp is None:
                return []
            coef = np.asarray(imp, dtype=np.float64)
        else:
            return []
        pairs = sorted(zip(expanded, coef.tolist()), key=lambda kv: kv[1], reverse=True)
        return [{"feature": f, "importance": float(v)} for f, v in pairs[:20]]
    except Exception:
        return []


# ----------------------------------------------------------------------------------------
# Outlier / missing before-after summaries (fold-local, development)
# ----------------------------------------------------------------------------------------
def outlier_summary(policy: Mapping[str, Any] | None, features: Sequence[str] | None = None) -> dict[str, Any]:
    frame = load_frame()
    dev_mask = frame["season"].to_numpy() == DEV_SEASON
    features = list(features or CONTINUOUS_FEATURES)
    treated = [f for f in features if feature_kind(f) == "continuous"]
    total = int(dev_mask.sum())
    entries = []
    total_flagged = 0
    for name in treated:
        vals = frame[name].to_numpy()[dev_mask]
        finite = vals[np.isfinite(vals)]
        ov = dict((policy or {}).get("overrides", {}).get(name, {}))
        method = ov.get("method", (policy or {}).get("globalMethod", "iqr"))
        params = ov.get("params", (policy or {}).get("params", {}))
        if "lower" in ov and "upper" in ov and method not in ("iqr", "mad", "zscore"):
            bounds = (float(ov["lower"]), float(ov["upper"]))
        else:
            bounds = _outlier_bounds(vals, method, params)
        flagged = 0
        after = finite
        if bounds is not None and finite.size:
            flagged = int(((finite < bounds[0]) | (finite > bounds[1])).sum())
            after = np.clip(finite, bounds[0], bounds[1])
        total_flagged += flagged
        entries.append(
            {
                "feature": name,
                "role": E.feature_role(name),
                "method": method if bounds is not None else "none",
                "bounds": {"lower": bounds[0], "upper": bounds[1]} if bounds else None,
                "beforeMin": float(finite.min()) if finite.size else None,
                "beforeMax": float(finite.max()) if finite.size else None,
                "afterMin": float(after.min()) if after.size else None,
                "afterMax": float(after.max()) if after.size else None,
                "flagged": flagged,
                "flaggedPct": float(flagged / total) if total else 0.0,
                "beforeHistogram": _hist(finite, finite),
                "afterHistogram": _hist(after, finite),
            }
        )
    entries.sort(key=lambda e: e["flagged"], reverse=True)
    return {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "scope": "FOLD_LOCAL_DEVELOPMENT_2023",
        "totalObservations": total,
        "featuresAnalyzed": len(treated),
        "featuresWithOutliers": sum(1 for e in entries if e["flagged"] > 0),
        "totalFlagged": total_flagged,
        "flaggedPct": float(total_flagged / (total * max(len(treated), 1))) if total else 0.0,
        "features": entries,
    }


def _hist(values: np.ndarray, ref: np.ndarray, bins: int = 24) -> list[dict[str, Any]]:
    if ref.size == 0:
        return []
    lo, hi = float(np.percentile(ref, 0.5)), float(np.percentile(ref, 99.5))
    if hi <= lo:
        hi = lo + 1.0
    edges = np.linspace(lo, hi, bins + 1)
    counts, _ = np.histogram(np.clip(values, lo, hi), bins=edges)
    return [{"lo": float(edges[i]), "hi": float(edges[i + 1]), "count": int(counts[i])} for i in range(bins)]


def _dev_fill_value(method: str, finite: np.ndarray, constant: float) -> tuple[float | None, str]:
    """Development-fold fill value matching the Preprocessor exactly. The governed model matrix must
    be complete (no cockpit model family accepts raw NaN), so 'none' resolves to the median fallback."""
    if finite.size == 0:
        return None, method
    if method == "mean":
        return float(finite.mean()), "mean"
    if method == "most_frequent":
        return float(pd.Series(finite).mode().iloc[0]), "most_frequent"
    if method == "constant":
        return float(constant), "constant"
    if method == "none":
        return float(np.median(finite)), "none_median_fallback"
    return float(np.median(finite)), "median"


def _impute_after_hist(before: list[dict[str, Any]], fill: float, missing: int) -> list[dict[str, Any]]:
    """After-imputation histogram: the observed histogram plus the imputed mass as a spike in the bin
    that contains the fill value (bins are shared with the before histogram for a valid comparison)."""
    after = [dict(b) for b in before]
    if not after:
        return after
    clamped = min(max(fill, after[0]["lo"]), after[-1]["hi"])
    idx = next((i for i, b in enumerate(after) if clamped >= b["lo"] and (clamped < b["hi"] or i == len(after) - 1)), 0)
    after[idx]["count"] += missing
    return after


def missing_summary(policy: Mapping[str, Any] | None, features: Sequence[str] | None = None) -> dict[str, Any]:
    """Fold-local (development 2023) missingness: real per-feature counts, dev-fold fill statistics,
    per-season descriptive rates, and before/after imputation histograms for continuous features.
    Validation (2024) and frozen final (2025) contribute descriptive rates only — never fill values."""
    frame = load_frame()
    season = frame["season"].to_numpy()
    dev_mask = season == DEV_SEASON
    total = int(dev_mask.sum())
    features = list(features or ALL_FEATURES)
    add_indicator = bool((policy or {}).get("addIndicator", False))
    global_method = (policy or {}).get("globalMethod", "median")
    global_constant = float((policy or {}).get("constant", 0.0))
    entries = []
    total_missing = 0
    for name in features:
        kind = feature_kind(name)
        col = frame[name].to_numpy()
        dev_col = col[dev_mask]
        finite_mask = np.isfinite(dev_col)
        missing = int((~finite_mask).sum())
        finite = dev_col[finite_mask]
        total_missing += missing
        mv = dict((policy or {}).get("overrides", {}).get(name, {}))
        method = mv.get("method", global_method)
        constant = float(mv.get("value", global_constant))
        fill, resolved = _dev_fill_value(method, finite, constant) if missing > 0 else (None, method)
        by_season = {}
        for s in (DEV_SEASON, VAL_SEASON, FROZEN_SEASON):
            sc = col[season == s]
            by_season[str(s)] = float((~np.isfinite(sc)).sum() / len(sc)) if len(sc) else 0.0
        indicator_applied = bool(add_indicator and kind == "continuous" and missing > 0)
        before_hist = after_hist = None
        if kind == "continuous" and missing > 0 and fill is not None and finite.size:
            before_hist = _hist(finite, finite)
            after_hist = _impute_after_hist(before_hist, fill, missing)
        entries.append(
            {
                "feature": name,
                "role": E.feature_role(name),
                "kind": kind,
                "missing": missing,
                "missingPct": float(missing / total) if total else 0.0,
                "nonMissing": total - missing,
                "method": method,
                "resolvedMethod": resolved,
                "fillValue": fill,
                "indicator": indicator_applied,
                "bySeason": by_season,
                "beforeHistogram": before_hist,
                "afterHistogram": after_hist,
            }
        )
    entries.sort(key=lambda e: e["missing"], reverse=True)
    total_cells = total * max(len(features), 1)
    dev_matrix = frame.loc[dev_mask, features].to_numpy() if features else np.empty((total, 0))
    rows_affected = int((~np.isfinite(dev_matrix)).any(axis=1).sum()) if features else 0
    return {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "scope": "FOLD_LOCAL_DEVELOPMENT_2023",
        "totalObservations": total,
        "featuresAnalyzed": len(features),
        "continuousFeatures": sum(1 for n in features if feature_kind(n) == "continuous"),
        "categoricalFeatures": sum(1 for n in features if feature_kind(n) != "continuous"),
        "featuresWithMissing": sum(1 for e in entries if e["missing"] > 0),
        "totalMissing": total_missing,
        "missingCellPct": float(total_missing / total_cells) if total_cells else 0.0,
        "rowsAffected": rows_affected,
        "rowsAffectedPct": float(rows_affected / total) if total else 0.0,
        "addIndicator": add_indicator,
        "features": entries,
    }


# ----------------------------------------------------------------------------------------
# Experiment run + champion comparison
# ----------------------------------------------------------------------------------------
def _config_sha(config: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


class LegacyModelingRetiredError(CockpitError):
    """Phase 7D.2 Gate 12 — the legacy in-process modeling execution / frozen-2025 result path is retired. It
    fit and scored a frozen 2025 fold; the canonical, server-authorized path is
    server.sports_cockpit.gen3_authority (2024-only validation; 2025 physically sealed)."""


_LEGACY_RETIRED_MSG = (
    "legacy modeling execution is RETIRED (Phase 7D.2 Gate 12): it fit/scored a frozen 2025 fold. Use the "
    "canonical gen3_authority run path (create_binding -> issue_run_authority -> execute -> activate_candidate); "
    "validation is 2024-only and 2025 is sealed."
)


def _fit_and_evaluate(
    frame: pd.DataFrame,
    features: Sequence[str],
    family: str,
    hyper: Mapping[str, Any],
    outlier_policy: Mapping[str, Any] | None,
    missing_policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    raise LegacyModelingRetiredError(_LEGACY_RETIRED_MSG)  # Gate 12 — retired before any data open
    dev_mask = frame["season"].to_numpy() == DEV_SEASON
    val_mask = frame["season"].to_numpy() == VAL_SEASON
    frozen_mask = frame["season"].to_numpy() == FROZEN_SEASON
    pre = Preprocessor.fit(frame, features, outlier_policy, missing_policy)
    X_dev = pre.transform(frame, dev_mask)
    y_dev = encode_labels(frame.loc[dev_mask, "outcome"].to_numpy())
    t0 = time.time()
    est = _build_estimator(family, hyper)
    est.fit(X_dev, y_dev)
    fit_seconds = time.time() - t0
    result = {"fitSeconds": fit_seconds, "expandedFeatures": pre.expanded_names}
    for season, mask, key in ((VAL_SEASON, val_mask, "val2024"), (FROZEN_SEASON, frozen_mask, "frozen2025")):
        X = pre.transform(frame, mask)
        proba = _predict_proba_aligned(est, X)
        labels = frame.loc[mask, "outcome"].to_numpy()
        result[key] = evaluate_multiclass(labels, proba)
    result["importance"] = _feature_importance(est, family, pre.expanded_names)
    result["_estimator"] = est
    result["_preprocessor"] = pre
    return result


def fit_cockpit_model(config: Mapping[str, Any]) -> tuple[Any, "Preprocessor"]:
    """Fit a cockpit model on 2023 development ONLY and return (estimator, preprocessor) for the whole-game
    simulator / inference. This is NOT a frozen-2025 path (it never fits or scores 2025), so it is retained."""
    frame, _ = working_frame(config)
    features = list(config.get("features") or ALL_FEATURES)
    family = config.get("family", "logistic")
    hyper = dict(config.get("hyperparameters") or {})
    outlier_policy = config.get("outlierPolicy") or {"globalMethod": "none"}
    missing_policy = config.get("missingPolicy") or {"globalMethod": "median"}
    pre = Preprocessor.fit(frame, features, outlier_policy, missing_policy)
    dev_mask = frame["season"].to_numpy() == DEV_SEASON
    X_dev = pre.transform(frame, dev_mask)
    y_dev = encode_labels(frame.loc[dev_mask, "outcome"].to_numpy())
    est = _build_estimator(family, hyper)
    est.fit(X_dev, y_dev)
    return est, pre


_CHAMP_CACHE: dict[str, Any] = {}


def champion_baseline() -> dict[str, Any]:
    """In-pipeline reproduction of D3 champion C4 (all 22 features, tuned C) for fair comparison."""
    raise LegacyModelingRetiredError(_LEGACY_RETIRED_MSG)  # Gate 12 — retired before any data open
    if "champ" in _CHAMP_CACHE:
        return _CHAMP_CACHE["champ"]
    frame = load_frame()
    best = None
    for c in (0.05, 0.2, 1.0):
        res = _fit_and_evaluate(
            frame, ALL_FEATURES, "logistic", {"C": c, "maxIter": 2000},
            {"globalMethod": "none"}, {"globalMethod": "mean"},
        )
        ll = res["val2024"]["logLoss"]
        if best is None or ll < best["val2024"]["logLoss"]:
            best = res
            best_c = c
    payload = {
        "family": "logistic",
        "featureCount": len(ALL_FEATURES),
        "C": best_c,
        "val2024": {k: best["val2024"][k] for k in ("logLoss", "brierScore", "topLabelEce")},
        "frozen2025": {k: best["frozen2025"][k] for k in ("logLoss", "brierScore", "topLabelEce")},
        "registeredReference": E._champion_reference(),
    }
    _CHAMP_CACHE["champ"] = payload
    return payload


def run_experiment(config: Mapping[str, Any], persist: bool = True) -> dict[str, Any]:
    raise LegacyModelingRetiredError(_LEGACY_RETIRED_MSG)  # Gate 12 — retired before any data open
    frame, engineered_names = working_frame(config)
    features = list(config.get("features") or ALL_FEATURES)
    allowed = set(ALL_FEATURES) | set(engineered_names)
    unknown = [f for f in features if f not in allowed]
    if unknown:
        raise CockpitError(f"unknown features requested: {unknown}")
    if not features:
        raise CockpitError("at least one feature is required")
    family = config.get("family", "logistic")
    if family not in AVAILABLE_FAMILIES:
        raise CockpitError(f"unknown family: {family}")
    if not AVAILABLE_FAMILIES[family]:
        raise CockpitError(f"family not installed: {family}")
    hyper = dict(config.get("hyperparameters") or {})
    outlier_policy = config.get("outlierPolicy") or {"globalMethod": "none"}
    missing_policy = config.get("missingPolicy") or {"globalMethod": "median"}

    res = _fit_and_evaluate(frame, features, family, hyper, outlier_policy, missing_policy)
    champ = champion_baseline()

    def _delta(a, b):
        return {
            "logLoss": a["logLoss"] - b["logLoss"],
            "brierScore": a["brierScore"] - b["brierScore"],
            "topLabelEce": a["topLabelEce"] - b["topLabelEce"],
        }

    comparison = {
        "val2024": _delta(res["val2024"], champ["val2024"]),
        "frozen2025": _delta(res["frozen2025"], champ["frozen2025"]),
        "beatsChampion2024": res["val2024"]["logLoss"] < champ["val2024"]["logLoss"],
        "beatsChampionFrozen": res["frozen2025"]["logLoss"] < champ["frozen2025"]["logLoss"],
    }

    config_norm = {
        "features": features,
        "family": family,
        "hyperparameters": hyper,
        "outlierPolicy": outlier_policy,
        "missingPolicy": missing_policy,
        "engineeredFeatures": list(config.get("engineeredFeatures") or []),
    }
    experiment_id = f"cockpit-exp-{_config_sha(config_norm)}"
    payload = {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "experimentId": experiment_id,
        "config": config_norm,
        "family": family,
        "familyLabel": E_family_label(family),
        "featureCount": len(features),
        "expandedFeatureCount": len(res["expandedFeatures"]),
        "fitSeconds": res["fitSeconds"],
        "simulatorEligible": family in SIMULATOR_ELIGIBLE_FAMILIES,
        "metrics": {"val2024": res["val2024"], "frozen2025": res["frozen2025"]},
        "headline": {
            "val2024": {k: res["val2024"][k] for k in ("logLoss", "brierScore", "topLabelEce")},
            "frozen2025": {k: res["frozen2025"][k] for k in ("logLoss", "brierScore", "topLabelEce")},
        },
        "champion": champ,
        "comparison": comparison,
        "importance": res["importance"],
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "leakageGuards": {
            "frozenSeasonExcludedFromFitting": True,
            "foldLocalPreprocessing": True,
            "targetColumnNeverAFeature": "outcome" not in features,
        },
    }
    if persist:
        _persist_experiment(experiment_id, payload)
    return payload


def E_family_label(family: str) -> str:
    return E.FAMILY_LABELS.get(family, {"svm": "Linear SVM (calibrated)"}.get(family, family))


def _persist_experiment(experiment_id: str, payload: Mapping[str, Any]) -> None:
    out_dir = COCKPIT_ROOT / "experiments"
    out_dir.mkdir(parents=True, exist_ok=True)
    slim = {k: v for k, v in payload.items()}
    (out_dir / f"{experiment_id}.json").write_text(json.dumps(slim), encoding="utf-8")
    # maintain a lightweight index
    index_path = out_dir / "index.json"
    index = []
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            index = []
    index = [e for e in index if e.get("experimentId") != experiment_id]
    index.append(
        {
            "experimentId": experiment_id,
            "family": payload["family"],
            "featureCount": payload["featureCount"],
            "val2024LogLoss": payload["headline"]["val2024"]["logLoss"],
            "frozen2025LogLoss": payload["headline"]["frozen2025"]["logLoss"],
            "beatsChampion2024": payload["comparison"]["beatsChampion2024"],
            "createdAt": payload["createdAt"],
        }
    )
    index.sort(key=lambda e: e["val2024LogLoss"])
    index_path.write_text(json.dumps(index), encoding="utf-8")


def run_ablation(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Controlled feature ablation: CONTROL (base) vs CHALLENGER (base + added features)."""
    raise LegacyModelingRetiredError(_LEGACY_RETIRED_MSG)  # Gate 12 — retired; use gen3 feature-family ablation
    base = dict(payload.get("baseConfig") or {})
    add_features = list(payload.get("addFeatures") or [])
    add_engineered = list(payload.get("addEngineered") or [])
    base_features = list(base.get("features") or ALL_FEATURES)
    base_engineered = list(base.get("engineeredFeatures") or [])

    # Engineered features are only exercised by the estimator when their NAMES are selected. Derive the
    # names from the added specs so a caller that passes addEngineered (specs) without also passing
    # addFeatures (names) still gets a real comparison instead of a silent no-op (materialized-but-unused).
    add_eng_names = [s.get("name") for s in add_engineered if isinstance(s, Mapping) and s.get("name")]
    extra: list[str] = []
    for f in list(add_features) + add_eng_names:
        if f not in base_features and f not in extra:
            extra.append(f)
    control_cfg = {**base, "features": base_features, "engineeredFeatures": base_engineered}
    challenger_cfg = {
        **base,
        "features": base_features + extra,
        "engineeredFeatures": base_engineered + add_engineered,
    }
    control = run_experiment(control_cfg, persist=False)
    challenger = run_experiment(challenger_cfg, persist=False)

    def _delta(a, b):
        return {k: challenger["headline"][a][k] - control["headline"][a][k] for k in ("logLoss", "brierScore", "topLabelEce")}

    d24 = _delta("val2024", "val2024")
    d25 = _delta("frozen2025", "frozen2025")
    # feature-family verdict (do not delete on one metric)
    imp24 = d24["logLoss"] < -1e-4
    imp25 = d25["logLoss"] < -1e-4
    worse = d24["logLoss"] > 1e-3
    if imp24 and imp25:
        verdict = "VALUE_CONFIRMED"
    elif imp24 or imp25:
        verdict = "VALUE_MARGINAL"
    elif worse:
        verdict = "NEGATIVE_VALUE"
    else:
        verdict = "NO_MATERIAL_VALUE"
    return {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "addedFeatures": add_features + [s.get("name") for s in add_engineered],
        "control": {"features": len(base_features), "val2024": control["headline"]["val2024"], "frozen2025": control["headline"]["frozen2025"]},
        "challenger": {"features": len(challenger_cfg["features"]), "val2024": challenger["headline"]["val2024"], "frozen2025": challenger["headline"]["frozen2025"]},
        "delta2024": d24,
        "delta2025": d25,
        "verdict": verdict,
    }


def list_experiments() -> list[dict[str, Any]]:
    index_path = COCKPIT_ROOT / "experiments" / "index.json"
    if not index_path.is_file():
        return []
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return []


# Opaque experiment-id allowlist (Phase 7A Gate 11A). Experiment ids are server-generated as
# ``cockpit-exp-<16-64 hex>`` (config-hash) or the autopilot label; anything else is rejected before
# a filesystem path is ever constructed, closing the inherited path-traversal sink where a route
# parameter like ``..%2f..%2fsecret`` could reach arbitrary ``.json`` under the shared runtime root.
_EXPERIMENT_ID_RE = re.compile(r"^cockpit-(exp|autopilot)-[0-9a-f]{8,64}$")


def _validate_experiment_id(experiment_id: str) -> str:
    if not isinstance(experiment_id, str) or not _EXPERIMENT_ID_RE.match(experiment_id):
        raise CockpitError("invalid experiment id")
    return experiment_id


def get_experiment(experiment_id: str) -> dict[str, Any] | None:
    _validate_experiment_id(experiment_id)
    root = (COCKPIT_ROOT / "experiments").resolve()
    path = (root / f"{experiment_id}.json").resolve()
    # Defense in depth: the resolved path must stay strictly within the experiments root and must be a
    # regular file (never a symlink / reparse point escaping the boundary).
    if root not in path.parents or path.is_symlink() or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------------------
# Autopilot: automated bounded benchmark the scientist competes against
# ----------------------------------------------------------------------------------------
def _autopilot_plan(budget: str) -> list[dict[str, Any]]:
    """Bounded candidate plans per budget. Never launches an unbounded search."""
    base = [
        {"family": "logistic", "hyperparameters": {"C": 0.05, "maxIter": 2000}, "label": "Logistic C=0.05"},
        {"family": "logistic", "hyperparameters": {"C": 1.0, "maxIter": 2000}, "label": "Logistic C=1.0"},
    ]
    standard = base + [
        {"family": "hist_gradient_boosting", "hyperparameters": {"maxIter": 200, "learningRate": 0.1}, "label": "HistGradientBoosting"},
        {"family": "random_forest", "hyperparameters": {"nEstimators": 200, "maxDepth": 12, "minSamplesLeaf": 50}, "label": "Random Forest"},
    ]
    deep = standard + [
        {"family": "extra_trees", "hyperparameters": {"nEstimators": 300, "maxDepth": 16, "minSamplesLeaf": 30}, "label": "Extra Trees"},
        {"family": "hist_gradient_boosting", "hyperparameters": {"maxIter": 400, "learningRate": 0.05, "l2": 1.0}, "label": "HGB deep"},
    ]
    if _LGBM is not None:
        deep.append({"family": "lightgbm", "hyperparameters": {"nEstimators": 400, "numLeaves": 63}, "label": "LightGBM"})
    return {"quick": base, "standard": standard, "deep": deep}.get(budget, standard)


def run_autopilot(config: Mapping[str, Any], budget: str = "standard", persist: bool = True) -> dict[str, Any]:
    raise LegacyModelingRetiredError(_LEGACY_RETIRED_MSG)  # Gate 12 — retired; use gen3 run_authorized_suite
    features = list(config.get("features") or ALL_FEATURES)
    outlier_policy = config.get("outlierPolicy") or {"globalMethod": "none"}
    missing_policy = config.get("missingPolicy") or {"globalMethod": "median"}
    plan = _autopilot_plan(budget)
    frame = load_frame()
    champ = champion_baseline()
    candidates = []
    t_start = time.time()
    for spec in plan:
        family = spec["family"]
        if not AVAILABLE_FAMILIES.get(family):
            continue
        t0 = time.time()
        try:
            res = _fit_and_evaluate(frame, features, family, spec["hyperparameters"], outlier_policy, missing_policy)
            candidates.append(
                {
                    "label": spec["label"],
                    "family": family,
                    "hyperparameters": spec["hyperparameters"],
                    "val2024": {k: res["val2024"][k] for k in ("logLoss", "brierScore", "topLabelEce")},
                    "frozen2025": {k: res["frozen2025"][k] for k in ("logLoss", "brierScore", "topLabelEce")},
                    "runtimeSeconds": round(time.time() - t0, 2),
                    "status": "COMPLETED",
                }
            )
        except Exception as exc:  # keep going; report failure honestly
            candidates.append(
                {"label": spec["label"], "family": family, "hyperparameters": spec["hyperparameters"], "status": "FAILED", "error": str(exc)[:200]}
            )
    ok = [c for c in candidates if c.get("status") == "COMPLETED"]
    ok.sort(key=lambda c: c["val2024"]["logLoss"])
    best = ok[0] if ok else None
    runner_up = ok[1] if len(ok) > 1 else None
    payload = {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "budget": budget,
        "featureCount": len(features),
        "candidateCount": len(candidates),
        "candidates": candidates,
        "best": best,
        "runnerUp": runner_up,
        "champion": champ,
        "beatsChampion2024": bool(best and best["val2024"]["logLoss"] < champ["val2024"]["logLoss"]),
        "totalRuntimeSeconds": round(time.time() - t_start, 2),
        "outlierPolicy": outlier_policy,
        "missingPolicy": missing_policy,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "limitations": [
            "Autopilot searches a bounded candidate set per budget; it is a benchmark, not an exhaustive AutoML.",
            "Selection uses 2024 validation only; the 2025 frozen season never participates in selection.",
        ],
    }
    if persist:
        out_dir = COCKPIT_ROOT / "autopilot"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload
