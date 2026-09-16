"""Research-only discrete PA-boundary hazards; never imported by production V18.

Game termination competes with removal. Unknown observation is not an event.
The BF-only forecast integrates this reduced state; it is not a full-game model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler

ENDPOINTS = ("CONTINUE", "REMOVAL", "GAME_END")
PREGAME_FIELDS = ("homePitcher", "calendarMonth", "priorStartCount", "priorStartBfMean", "daysRest", "historyMissing", "bf")
CONDITIONAL_FIELDS = ("inning", "outsInInning", "pitchingOuts", "runsAllowedSoFar", "pitchingTeamScoreMargin", "baseState")
FLOOR = 1e-12


def target_codes(values):
    lookup = {name: i for i, name in enumerate(ENDPOINTS)}
    if not set(values).issubset(lookup):
        raise ValueError("Unknown/censored observation cannot become a removal event")
    return np.array([lookup[v] for v in values], dtype=np.int64)


def losses(probabilities, y):
    p = np.asarray(probabilities, float)
    if p.shape != (len(y), 3) or not np.isfinite(p).all() or (p < 0).any() or not np.allclose(p.sum(1), 1, atol=1e-10):
        raise ValueError("Incoherent competing endpoint probabilities")
    return -np.log(np.clip(p[np.arange(len(y)), y], FLOOR, 1)), ((p - np.eye(3)[y]) ** 2).sum(1)


def temperature_probabilities(p, temperature):
    logp = np.log(np.clip(p, FLOOR, 1)) / float(temperature)
    logp -= logp.max(axis=1, keepdims=True)
    p = np.exp(logp)
    return p / p.sum(axis=1, keepdims=True)


def history_strata(frame):
    count = frame.get("priorStartCount", pd.Series(0, index=frame.index)).fillna(0).to_numpy()
    mean = frame.get("priorStartBfMean", pd.Series(np.nan, index=frame.index)).to_numpy()
    return np.where(count < 3, "SPARSE_HISTORY", np.where(mean <= 12, "PRIOR_SHORT_USAGE_PROXY", "PRIOR_CONVENTIONAL_USAGE_PROXY"))


@dataclass
class EmpiricalHazard:
    feature_order: tuple = PREGAME_FIELDS
    temperature: float = 1.0
    model_id: str = "EMPIRICAL_POOLED"
    metadata: dict = field(default_factory=dict)

    def fit(self, frame, endpoints):
        y = target_codes(endpoints)
        counts = np.bincount(y, minlength=3).astype(float) + 0.5
        self.pooled = counts / counts.sum()
        self.by_bf, self.by_group = {}, {}
        bf = np.minimum(frame.bf.to_numpy(dtype=int), 50)
        group = history_strata(frame)
        for value in np.unique(bf):
            cnt = np.bincount(y[bf == value], minlength=3)
            self.by_bf[int(value)] = (cnt + 30 * self.pooled) / (cnt.sum() + 30)
        for value, label in sorted(set(zip(bf, group))):
            cnt = np.bincount(y[(bf == value) & (group == label)], minlength=3)
            prior = self.by_bf[int(value)]
            self.by_group[(int(value), str(label))] = (cnt + 30 * prior) / (cnt.sum() + 30)
        return self

    def predict_proba(self, frame, *, calibrated=True):
        bf = np.minimum(frame.bf.to_numpy(dtype=int), 50)
        return np.array([self.by_group.get((int(b), str(g)), self.by_bf.get(int(b), self.pooled))
                         for b, g in zip(bf, history_strata(frame))])


@dataclass
class LearnedHazard:
    model_id: str
    feature_order: tuple
    temperature: float = 1.0
    metadata: dict = field(default_factory=dict)

    def fit(self, frame, endpoints):
        if "bf" not in self.feature_order or not set(self.feature_order).issubset(PREGAME_FIELDS + CONDITIONAL_FIELDS):
            raise ValueError("Unregistered/future feature requested")
        if self.model_id.endswith("PREGAME") and set(self.feature_order) - set(PREGAME_FIELDS):
            raise ValueError("Observed future in-game state is forbidden in pregame hazard")
        x, y = frame[list(self.feature_order)], target_codes(endpoints)
        if set(y) != {0, 1, 2}:
            raise ValueError("Training must observe all three endpoints; no fabricated class")
        if self.model_id == "HGB_PREGAME":
            self.pipeline = Pipeline([
                ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
                ("estimator", HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=15,
                    learning_rate=0.06, min_samples_leaf=200, l2_regularization=10.0,
                    early_stopping=False, random_state=20260911))])
        else:
            other = [name for name in self.feature_order if name != "bf"]
            transformer = ColumnTransformer([
                ("bf_spline", SplineTransformer(n_knots=5, degree=3, extrapolation="linear"), ["bf"]),
                ("other", Pipeline([("imputer", SimpleImputer(strategy="median", add_indicator=True)),
                                    ("scale", StandardScaler())]), other)], remainder="drop")
            self.pipeline = Pipeline([("features", transformer),
                ("estimator", LogisticRegression(C=1.0, max_iter=500, solver="lbfgs", random_state=20260911))])
        self.pipeline.fit(x, y)
        return self

    def predict_proba(self, frame, *, calibrated=True):
        raw = self.pipeline.predict_proba(frame[list(self.feature_order)])
        p = np.zeros((len(frame), 3))
        for j, cls in enumerate(self.pipeline.classes_):
            p[:, int(cls)] = raw[:, j]
        return temperature_probabilities(p, self.temperature) if calibrated else p

    def fit_temperature(self, calibration, endpoints):
        p = self.predict_proba(calibration, calibrated=False)
        y = target_codes(endpoints)
        result = minimize_scalar(lambda t: losses(temperature_probabilities(p, t), y)[0].mean(),
                                 bounds=(0.5, 2.0), method="bounded", options={"xatol": 1e-5})
        if not result.success:
            raise ValueError("Bounded calibration optimization failed")
        self.temperature = float(result.x)
        return {"temperature": self.temperature, "method": "DISJOINT_EARLIER_TEMPERATURE_ONLY",
                "iterations": int(result.nfev), "rawNll": float(losses(p, y)[0].mean()),
                "calibratedNll": float(result.fun)}


def pregame_bf_distribution(model, starts, *, maximum_bf=100, calibrated=True):
    """Exact integration over the reduced BF state, conditional on facing >=1 BF.

    No observed future state enters this calculation. A surviving tail is not
    forced into a fictional hook. Full-game termination/outs need game simulation.
    """
    if set(model.feature_order) - set(PREGAME_FIELDS):
        raise ValueError("Conditional observed state cannot generate a pregame BF distribution")
    n = len(starts)
    expanded = starts.loc[starts.index.repeat(maximum_bf)].reset_index(drop=True).copy()
    expanded["bf"] = np.tile(np.arange(1, maximum_bf + 1), n)
    p = model.predict_proba(expanded, calibrated=calibrated).reshape(n, maximum_bf, 3)
    if not np.allclose(p.sum(2), 1, atol=1e-10):
        raise ValueError("Invalid integrated probabilities")
    survival_before = np.concatenate([np.ones((n, 1)), np.cumprod(p[:, :-1, 0], axis=1)], axis=1)
    cause_mass = survival_before[:, :, None] * p[:, :, 1:]
    remaining = np.prod(p[:, :, 0], axis=1)
    if not np.allclose(cause_mass.sum((1, 2)) + remaining, 1, atol=1e-10):
        raise ValueError("Competing duration mass not conserved")
    return {"pmf": cause_mass.sum(2), "causeMass": cause_mass, "tail": remaining}


def duration_metrics(distribution, observed_bf):
    pmf, tail = distribution["pmf"], distribution["tail"]
    observed = np.asarray(observed_bf, dtype=int)
    if (observed < 1).any() or (observed > pmf.shape[1]).any():
        raise ValueError("Observed BF is outside declared support; do not silently clip")
    cdf = pmf.cumsum(1)
    grid = np.arange(1, pmf.shape[1] + 1)
    # Tail is reported; mean below is a lower bound when nonnegligible.
    expectation = pmf @ grid + tail * (grid[-1] + 1)
    def quantile(q):
        hit = cdf >= q
        return np.where(hit.any(1), hit.argmax(1) + 1, grid[-1] + 1)
    observed_cdf = observed[:, None] <= grid[None, :]
    lo80, hi80, lo90, hi90 = quantile(0.10), quantile(0.90), quantile(0.05), quantile(0.95)
    return {
        "expectedBfCapped101": expectation, "bfCappedMeanBias": expectation - observed,
        "bfCappedMeanAbsoluteError": np.abs(expectation - observed),
        "bfNll": -np.log(np.clip(pmf[np.arange(len(observed)), observed - 1], FLOOR, 1)),
        "bfCrpsThrough100": ((cdf - observed_cdf) ** 2).sum(1),
        "coverage80": (lo80 <= observed) & (observed <= hi80),
        "coverage90": (lo90 <= observed) & (observed <= hi90),
        "interval80WidthLowerBound": hi80 - lo80, "interval90WidthLowerBound": hi90 - lo90,
        "earlyExitProbability": cdf[:, 8], "longStartProbability": 1 - cdf[:, 25],
        "earlyExitBrier": (cdf[:, 8] - (observed <= 9)) ** 2,
        "longStartBrier": (1 - cdf[:, 25] - (observed >= 27)) ** 2,
        "gameEndProbability": distribution["causeMass"][:, :, 1].sum(1), "unresolvedTail": tail,
    }
