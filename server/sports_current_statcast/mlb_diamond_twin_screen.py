"""Pure named-position defense functions for the Diamond Twin value screen.

The fitted effect is a retrospective oracle diagnostic.  It consumes no files,
performs no publication, and grants no forecasting authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
from scipy import sparse
from scipy.optimize import minimize

from server.sports_current_statcast.mlb_v19_structural_defense import (
    apply_defense_shift,
)


POSITIONS: tuple[int, ...] = (2, 3, 4, 5, 6, 7, 8, 9)
POSITION_GROUPS: Mapping[str, tuple[int, ...]] = {
    "CATCHER": (2,),
    "INFIELD": (3, 4, 5, 6),
    "OUTFIELD": (7, 8, 9),
    "FULL": POSITIONS,
}


@dataclass(frozen=True)
class IdentityEffectModel:
    coefficients: Mapping[str, float]
    exposures: Mapping[str, int]
    penalty: float
    positions: tuple[int, ...]
    optimizer_success: bool
    iterations: int


def _logit(probabilities: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(probabilities, dtype=np.float64), 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


def _keys(lineups: np.ndarray, positions: Sequence[int]) -> np.ndarray:
    values = np.asarray(lineups, dtype=object)
    if values.ndim != 2 or values.shape[1] != len(positions):
        raise ValueError("lineups must have one participant column per position")
    if any(str(value).strip() == "" for value in values.ravel()):
        raise ValueError("participant identities must be nonempty")
    return np.asarray(
        [[f"P{position}:{player}" for position, player in zip(positions, row)] for row in values],
        dtype=object,
    )


def fit_identity_effects(
    baseline_bip_hit_probability: np.ndarray,
    observed_hit: np.ndarray,
    lineups: np.ndarray,
    *,
    penalty: float,
    positions: Sequence[int] = POSITIONS,
) -> IdentityEffectModel:
    """Fit sum-to-zero position/player log-odds residuals around V18."""
    baseline = np.asarray(baseline_bip_hit_probability, dtype=np.float64)
    target = np.asarray(observed_hit, dtype=np.float64)
    positions = tuple(int(value) for value in positions)
    if baseline.ndim != 1 or target.shape != baseline.shape or len(baseline) == 0:
        raise ValueError("baseline and target must be nonempty aligned vectors")
    if not np.isin(target, [0.0, 1.0]).all():
        raise ValueError("observed_hit must be binary")
    if not np.isfinite(penalty) or penalty <= 0:
        raise ValueError("penalty must be positive and finite")

    keys = _keys(lineups, positions)
    unique = sorted(set(keys.ravel()))
    index = {key: number for number, key in enumerate(unique)}
    columns = np.asarray([[index[key] for key in row] for row in keys], dtype=np.int64)
    row_index = np.repeat(np.arange(len(keys), dtype=np.int64), len(positions))
    design = sparse.csr_matrix(
        (np.ones(row_index.size), (row_index, columns.ravel())),
        shape=(len(keys), len(unique)),
        dtype=np.float64,
    )
    exposures = np.asarray(design.sum(axis=0)).ravel()
    groups = {
        position: np.asarray([number for number, key in enumerate(unique) if key.startswith(f"P{position}:")], dtype=np.int64)
        for position in positions
    }
    weights = {position: exposures[group] / exposures[group].sum() for position, group in groups.items()}

    def center(raw: np.ndarray) -> np.ndarray:
        result = raw.copy()
        for position, group in groups.items():
            result[group] -= float(np.dot(weights[position], raw[group]))
        return result

    offset = _logit(baseline)

    def objective(raw: np.ndarray) -> tuple[float, np.ndarray]:
        coefficients = center(raw)
        eta = offset + design @ coefficients
        probability = 1.0 / (1.0 + np.exp(-np.clip(eta, -35, 35)))
        loss = float(
            np.logaddexp(0.0, eta).sum()
            - np.dot(target, eta)
            + 0.5 * penalty * np.dot(coefficients, coefficients)
        )
        gradient_centered = np.asarray(design.T @ (probability - target)).ravel() + penalty * coefficients
        gradient = gradient_centered.copy()
        for position, group in groups.items():
            gradient[group] -= weights[position] * gradient_centered[group].sum()
        return loss, gradient

    fitted = minimize(
        objective,
        np.zeros(len(unique), dtype=np.float64),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": 300, "ftol": 1e-12, "gtol": 1e-8},
    )
    coefficients = center(np.asarray(fitted.x, dtype=np.float64))
    return IdentityEffectModel(
        coefficients={key: float(coefficients[index[key]]) for key in unique},
        exposures={key: int(exposures[index[key]]) for key in unique},
        penalty=float(penalty),
        positions=positions,
        optimizer_success=bool(fitted.success),
        iterations=int(fitted.nit),
    )


def lineup_shifts(
    model: IdentityEffectModel,
    lineups: np.ndarray,
    *,
    included_positions: Sequence[int] = POSITIONS,
    maximum_absolute_shift: float = 0.35,
) -> np.ndarray:
    if not np.isfinite(maximum_absolute_shift) or maximum_absolute_shift <= 0:
        raise ValueError("maximum_absolute_shift must be positive and finite")
    values = np.asarray(lineups, dtype=object)
    if values.ndim != 2 or values.shape[1] != len(model.positions):
        raise ValueError("lineups do not match the fitted position contract")
    included = {int(value) for value in included_positions}
    if not included.issubset(model.positions):
        raise ValueError("included positions are outside the fitted contract")
    shifts = np.zeros(len(values), dtype=np.float64)
    for column, position in enumerate(model.positions):
        if position not in included:
            continue
        shifts += np.asarray(
            [model.coefficients.get(f"P{position}:{player}", 0.0) for player in values[:, column]],
            dtype=np.float64,
        )
    return np.clip(shifts, -maximum_absolute_shift, maximum_absolute_shift)


def apply_identity_effects(probabilities: np.ndarray, shifts: Sequence[float]) -> np.ndarray:
    """Apply identity shifts under the same V18 BIP-mass preservation contract."""
    return apply_defense_shift(probabilities, shifts)


__all__ = [
    "IdentityEffectModel",
    "POSITIONS",
    "POSITION_GROUPS",
    "apply_identity_effects",
    "fit_identity_effects",
    "lineup_shifts",
]
