"""Persistable chronological V19 gates, specialists and scalar calibrators.

This module loads no data. Callers provide earlier OOF predictions explicitly;
the fold boundary is checked before labels are used. No global classifier is
trained here. The only fits are the predeclared bounded meta/calibration systems.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix
from .mlb_regime_models import OffsetCorrection, fit_temperature, temperature_transform
from .mlb_v19_evaluation import regime_masks


GLOBAL_ORDER = ("V18", "SEMANTIC_HGB", "SEMANTIC_EXTRA_TREES", "REGIME_HGB", "REGIME_CLUSTER_HGB")
ENSEMBLE_NAMES = ("GLOBAL_ENSEMBLE", "SPECIALIST_MIXTURE")
PENALTY = .01


@dataclass
class ConvexSimplex:
    """Variable-width convex probability mixture with a frozen V18 anchor prior."""
    branch_order: tuple[str, ...]
    weights: np.ndarray
    fit_receipt: dict

    @classmethod
    def identity(cls, names: Sequence[str], reason: str) -> "ConvexSimplex":
        if not names or names[0] != "V18":
            raise ValueError("Convex branch zero must be the V18 anchor")
        weights = np.zeros(len(names))
        weights[0] = 1.
        return cls(tuple(names), weights, {"status": reason, "rows": 0, "fitted": False})

    @classmethod
    def fit(cls, branches: Mapping[str, np.ndarray], y: np.ndarray, *, penalty=PENALTY) -> "ConvexSimplex":
        names = tuple(branches)
        if not names or names[0] != "V18" or not len(y):
            raise ValueError("A nonempty matched OOF gate with the V18 anchor is required")
        matrices = [validate_probability_matrix(branches[name]) for name in names]
        if any(len(matrix) != len(y) for matrix in matrices):
            raise ValueError("Meta gate labels and branch rows differ")
        truth = np.asarray(y, dtype=int)
        if not np.array_equal(truth, y) or np.any(truth < 0) or np.any(truth >= len(PA_CLASS_ORDER)):
            raise ValueError("Invalid frozen eight-class target index")
        true_class = np.column_stack([matrix[np.arange(len(y)), truth] for matrix in matrices])
        anchor = np.zeros(len(names)); anchor[0] = 1.

        def objective(weights):
            p = np.maximum(true_class @ weights, 1e-15)
            delta = weights - anchor
            return float(-np.log(p).mean() + .5 * penalty * np.square(delta).sum()), (
                -np.mean(true_class / p[:, None], axis=0) + penalty * delta)

        result = minimize(objective, anchor, jac=True, method="SLSQP", bounds=[(0., 1.)] * len(names),
            constraints=[{"type": "eq", "fun": lambda weights: weights.sum() - 1.,
                          "jac": lambda weights: np.ones(len(names))}],
            options={"maxiter": 150, "ftol": 1e-11})
        if not result.success or not np.isfinite(result.x).all() or abs(result.x.sum() - 1.) > 1e-8:
            raise RuntimeError(f"Convex gate failed convergence: {result.message}")
        weights = np.clip(result.x, 0., 1.)
        weights /= weights.sum()
        return cls(names, weights, {"status": "FITTED", "fitted": True, "rows": len(y),
            "iterations": int(result.nit), "objective": float(result.fun), "l2Penalty": penalty,
            "regularizationTarget": "ALL_WEIGHT_ON_V18", "coefficientConstraint": "NONNEGATIVE_SUM_ONE",
            "objectiveDistribution": "EXACT_DEPLOYED_CONVEX_PROBABILITY_MIXTURE"})

    def predict(self, branches: Mapping[str, np.ndarray]) -> np.ndarray:
        if set(branches) != set(self.branch_order):
            raise ValueError("Frozen convex branch contract differs")
        matrices = [validate_probability_matrix(branches[name]) for name in self.branch_order]
        if any(matrix.shape != matrices[0].shape for matrix in matrices):
            raise ValueError("Prediction branches are not aligned")
        if self.weights[0] == 1. and not self.weights[1:].any():
            return matrices[0].copy()
        result = np.zeros_like(matrices[0])
        for weight, matrix in zip(self.weights, matrices):
            result += weight * matrix
        # Masked specialists return the exact V18 vector outside their support;
        # keep that identity bitwise instead of re-summing identical branches.
        identical = np.ones(len(result), dtype=bool)
        for matrix in matrices[1:]:
            identical &= np.all(matrix == matrices[0], axis=1)
        result[identical] = matrices[0][identical]
        return validate_probability_matrix(result)


def chronological_segments(frame: pd.DataFrame, before_fold: int) -> tuple[dict[str, np.ndarray], dict]:
    """Split by complete date groups; never split a game or a shared game date."""
    if before_fold not in range(1, 6):
        raise ValueError("Only the five registered outer folds are allowed")
    if not frame.empty:
        if frame.foldNumber.ge(before_fold).any():
            raise ValueError("Meta fitting may see earlier OOF folds only")
        if frame.canonicalPaId.duplicated().any():
            raise ValueError("Duplicate earlier OOF observation identity")
        if frame.groupby("canonicalGameId").game_date.nunique().max() != 1:
            raise ValueError("Game crossed meta date groups")
        if not frame.game_date.astype(str).between("2023-03-30", "2026-08-06").all():
            raise ValueError("Meta frame escaped the physically Development-only interval")
    dates = np.array(sorted(frame.game_date.astype(str).unique()))
    first, second = int(np.floor(.70 * len(dates))), int(np.floor(.85 * len(dates)))
    segments = {"specialistFit": dates[:first], "gateFit": dates[first:second], "temperatureFit": dates[second:]}
    masks = {name: frame.game_date.astype(str).isin(values).to_numpy() for name, values in segments.items()}
    records = {name: {"dateCount": len(values), "rows": int(masks[name].sum()),
        "games": int(frame.loc[masks[name], "canonicalGameId"].nunique()),
        "startDate": str(values[0]) if len(values) else None, "endDate": str(values[-1]) if len(values) else None}
        for name, values in segments.items()}
    if len(frame) and not np.all(sum(mask.astype(int) for mask in masks.values()) == 1):
        raise ValueError("Chronological meta segments overlap or leave observations unassigned")
    return masks, {"beforeFold": before_fold, "splitUnit": "COMPLETE_OFFICIAL_GAME_DATE",
        "fractionRule": "EARLIEST_70_PERCENT_SPECIALISTS_NEXT_15_PERCENT_BOTH_GATES_FINAL_15_PERCENT_TEMPERATURES",
        "segments": records, "evaluationRowsInspected": 0,
        "historicalPublicationVintagesClaimed": False}


@dataclass
class MetaSystem:
    before_fold: int
    global_gate: ConvexSimplex
    specialist_gate: ConvexSimplex
    specialists: dict[str, OffsetCorrection] = field(default_factory=dict)
    temperatures: dict[str, float] = field(default_factory=dict)
    receipt: dict = field(default_factory=dict)

    def specialist_predictions(self, frame: pd.DataFrame, base: np.ndarray) -> dict[str, np.ndarray]:
        base = validate_probability_matrix(base)
        if len(frame) != len(base):
            raise ValueError("Specialist input/forecast population mismatch")
        masks, _ = regime_masks(frame)
        predictions = {"V18": base.copy()}
        for name, expert in self.specialists.items():
            mask = masks[name]
            result = base.copy()
            if mask.any():
                result[mask] = expert.predict(np.ones((int(mask.sum()), 1)), base[mask])
            if not np.array_equal(result[~mask], base[~mask]):
                raise ValueError("Specialist changed its unsupported complement")
            predictions["SPECIALIST:" + name] = result
        return predictions

    def predict(self, frame: pd.DataFrame, global_probabilities: Mapping[str, np.ndarray], *, calibrated=False) -> dict[str, np.ndarray]:
        if set(global_probabilities) != set(GLOBAL_ORDER):
            raise ValueError("Expected the exact V18 plus four-global prediction contract")
        result = {name: validate_probability_matrix(global_probabilities[name]).copy() for name in GLOBAL_ORDER}
        if any(len(matrix) != len(frame) for matrix in result.values()):
            raise ValueError("Global input and prediction populations differ")
        branches = self.specialist_predictions(frame, result["V18"])
        result.update({name: matrix for name, matrix in branches.items() if name != "V18"})
        result["GLOBAL_ENSEMBLE"] = self.global_gate.predict({name: result[name] for name in GLOBAL_ORDER})
        result["SPECIALIST_MIXTURE"] = self.specialist_gate.predict(branches)
        if calibrated:
            for name in result:
                if name not in self.temperatures:
                    raise ValueError("Frozen branch temperature is missing: " + name)
                temperature = self.temperatures[name]
                if temperature != 1.:
                    result[name] = temperature_transform(result[name], temperature)
        return result


def fit_meta_system(frame: pd.DataFrame, earlier_predictions: Mapping[str, np.ndarray], *,
                    before_fold: int, selected_regimes: Sequence[str],
                    run_fit: Callable | None = None) -> MetaSystem:
    """Fit only when explicitly invoked with a completed prior-OOF population.

    `run_fit(name, function, fold)` may provide the study's actual fit ledger.
    Missing earlier meta support has an explicit identity, never an auto retry.
    """
    if len(selected_regimes) > 2 or len(set(selected_regimes)) != len(selected_regimes):
        raise ValueError("At most two distinct predeclared eligible specialists")
    if set(earlier_predictions) != set(GLOBAL_ORDER):
        raise ValueError("Prior OOF global branch identities differ")
    masks, receipt = chronological_segments(frame, before_fold)
    ordered = {name: np.asarray(earlier_predictions[name], dtype=float) for name in GLOBAL_ORDER}
    if any(matrix.shape != (len(frame), len(PA_CLASS_ORDER)) for matrix in ordered.values()):
        raise ValueError("Prior OOF prediction shape differs from exact target contract")
    registry, _ = regime_masks(frame)
    if set(selected_regimes) - set(registry):
        raise ValueError("Specialist outside frozen outcome-independent registry")
    if before_fold <= 2 and selected_regimes:
        raise ValueError("First two folds cannot qualify persistent specialists")
    model = MetaSystem(before_fold, ConvexSimplex.identity(GLOBAL_ORDER, "NO_EARLIER_OOF_SUPPORT"),
        ConvexSimplex.identity(("V18",), "NO_QUALIFIED_SPECIALISTS"), receipt=receipt)
    runner = run_fit or (lambda name, function, fold: function())
    receipt["selectedRegimes"] = list(selected_regimes)
    receipt["specialists"] = {}
    receipt["targetOrder"] = list(PA_CLASS_ORDER)
    if any(not mask.any() for mask in masks.values()):
        names = (*GLOBAL_ORDER, *ENSEMBLE_NAMES)
        model.temperatures = {name: 1. for name in names}
        receipt.update(status="IDENTITY_INSUFFICIENT_PRIOR_META_SEGMENTS", actualMetaFits=0)
        return model
    y = frame.observedClassIndex.to_numpy(dtype=int)
    fits = 0
    for name in selected_regimes:
        selected = registry[name] & masks["specialistFit"]
        if not selected.any():
            receipt["specialists"][name] = {"status": "NO_SELECTED_REGIME_ROWS_IN_SPECIALIST_SEGMENT", "fitted": False}
            continue
        expert = runner("CLASS_OFFSET:" + name, lambda selected=selected: OffsetCorrection.fit(
            np.ones((int(selected.sum()), 1)), y[selected], ordered["V18"][selected], penalty=PENALTY), before_fold)
        model.specialists[name] = expert
        receipt["specialists"][name] = {**expert.fit_receipt,
            "coefficientClassOrder": list(PA_CLASS_ORDER), "maximumClassProbabilityAdjustment": .03,
            "complementPolicy": "RAW_BRANCH_EXACT_V18_OUTSIDE_PREGAME_REGIME",
            "calibratedComplementPolicy": "SEPARATE_EARLIER_OOF_TEMPERATURE_MAY_CHANGE_COMPLEMENT; EVALUATE_AGAINST_EQUALLY_CALIBRATED_V18",
            "meanPredictionFeature": "REGIME_MEMBERSHIP_ONLY"}
        fits += 1
    gate = masks["gateFit"]
    model.global_gate = runner("GLOBAL_CONVEX_GATE", lambda: ConvexSimplex.fit(
        {name: matrix[gate] for name, matrix in ordered.items()}, y[gate]), before_fold)
    fits += 1
    specialists = model.specialist_predictions(frame.loc[gate], ordered["V18"][gate])
    if model.specialists:
        model.specialist_gate = runner("SPECIALIST_CONVEX_GATE", lambda: ConvexSimplex.fit(specialists, y[gate]), before_fold)
        fits += 1
    temperature = masks["temperatureFit"]
    raw_calibration = model.predict(frame.loc[temperature], {name: matrix[temperature] for name, matrix in ordered.items()})
    receipt["temperatureFits"] = {}
    for name, matrix in raw_calibration.items():
        t, detail = runner("TEMPERATURE:" + name, lambda matrix=matrix: fit_temperature(y[temperature], matrix), before_fold)
        model.temperatures[name] = t
        receipt["temperatureFits"][name] = {**detail, "temperature": t, "classOrder": list(PA_CLASS_ORDER),
            "trainingSegment": "DISJOINT_LAST_15_PERCENT_OF_PRIOR_OOF_DATES"}
        fits += 1
    receipt.update(status="FITTED_FROM_STRICTLY_EARLIER_OOF", actualMetaFits=fits,
        globalGate={**model.global_gate.fit_receipt, "branchOrder": list(model.global_gate.branch_order),
                    "weights": model.global_gate.weights.tolist()},
        specialistGate={**model.specialist_gate.fit_receipt, "branchOrder": list(model.specialist_gate.branch_order),
                        "weights": model.specialist_gate.weights.tolist()},
        trainingEnd=str(frame.game_date.max()), targetOrder=list(PA_CLASS_ORDER),
        finalOotPayloadBytesRead=0, automaticRetries=0)
    return model
