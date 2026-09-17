"""Leakage-bounded team-defense adjustment for V18 ball-in-play classes.

The component changes only the conditional split between BIP hits and BIP
outs, preserves total BIP mass, and preserves the baseline relative
SINGLE/DOUBLE/TRIPLE mix. Strikeouts, walks/HBP, home runs, and OTHER_REACH
are never changed. It uses team defense because the retained Development
population does not bind named pregame fielders or positions.

This module performs no I/O, provider access, publication, or promotion.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np

from server.sports_modeling.metrics import PA_CLASS_ORDER


HIT_CLASSES = ("SINGLE", "DOUBLE", "TRIPLE")
OUT_CLASS = "BIP_OUT"
BIP_CLASSES = (*HIT_CLASSES, OUT_CLASS)
HIT_INDICES = tuple(PA_CLASS_ORDER.index(name) for name in HIT_CLASSES)
OUT_INDEX = PA_CLASS_ORDER.index(OUT_CLASS)
BIP_INDICES = (*HIT_INDICES, OUT_INDEX)
UNCHANGED_INDICES = tuple(index for index in range(len(PA_CLASS_ORDER)) if index not in BIP_INDICES)


def _logit(value: float) -> float:
    value = float(np.clip(value, 1e-9, 1.0 - 1e-9))
    return float(np.log(value / (1.0 - value)))


def _expit(value: np.ndarray | float) -> np.ndarray:
    value = np.asarray(value, dtype=np.float64)
    return 1.0 / (1.0 + np.exp(-value))


@dataclass(frozen=True)
class DefenseConfig:
    prior_strength: float
    maximum_absolute_log_odds_shift: float = 0.35

    def __post_init__(self) -> None:
        if not np.isfinite(self.prior_strength) or self.prior_strength <= 0:
            raise ValueError("prior_strength must be positive and finite")
        if not np.isfinite(self.maximum_absolute_log_odds_shift) or self.maximum_absolute_log_odds_shift <= 0:
            raise ValueError("maximum_absolute_log_odds_shift must be positive and finite")


@dataclass(frozen=True)
class DefenseState:
    league_hits: int
    league_outs: int
    team_hits: Mapping[str, int]
    team_outs: Mapping[str, int]

    @property
    def league_bip(self) -> int:
        return int(self.league_hits + self.league_outs)


def fit_state(rows: Iterable[tuple[str, int]]) -> DefenseState:
    """Fit counts from ``(fielding_team, observed_class_index)`` rows."""
    team_hits: dict[str, int] = {}
    team_outs: dict[str, int] = {}
    league_hits = league_outs = 0
    for team, observed in rows:
        team = str(team)
        observed = int(observed)
        if observed in HIT_INDICES:
            league_hits += 1
            team_hits[team] = team_hits.get(team, 0) + 1
        elif observed == OUT_INDEX:
            league_outs += 1
            team_outs[team] = team_outs.get(team, 0) + 1
    if league_hits + league_outs == 0:
        raise ValueError("at least one eligible ball in play is required")
    return DefenseState(league_hits, league_outs, team_hits, team_outs)


def defense_log_odds_shift(state: DefenseState, team: str, config: DefenseConfig) -> float:
    """Return a shrunk team-vs-league conditional BIP hit log-odds shift."""
    league_rate = state.league_hits / state.league_bip
    hits = int(state.team_hits.get(str(team), 0))
    outs = int(state.team_outs.get(str(team), 0))
    posterior = (hits + config.prior_strength * league_rate) / (hits + outs + config.prior_strength)
    shift = _logit(posterior) - _logit(league_rate)
    return float(np.clip(shift, -config.maximum_absolute_log_odds_shift,
                         config.maximum_absolute_log_odds_shift))


def apply_defense_shift(probabilities: np.ndarray, shifts: Sequence[float]) -> np.ndarray:
    """Apply conditional BIP shifts while preserving mass and untouched classes."""
    baseline = np.asarray(probabilities, dtype=np.float64)
    if baseline.ndim != 2 or baseline.shape[1] != len(PA_CLASS_ORDER):
        raise ValueError("probabilities must have shape (rows, 8)")
    shifts_array = np.asarray(shifts, dtype=np.float64)
    if shifts_array.shape != (len(baseline),) or not np.isfinite(shifts_array).all():
        raise ValueError("one finite shift is required per probability row")
    if not np.isfinite(baseline).all() or np.any(baseline < 0):
        raise ValueError("baseline probabilities must be finite and nonnegative")
    if not np.allclose(baseline.sum(axis=1), 1.0, rtol=0.0, atol=1e-12):
        raise ValueError("baseline probability rows must sum to one")

    result = baseline.copy()
    hit_mass = baseline[:, HIT_INDICES].sum(axis=1)
    out_mass = baseline[:, OUT_INDEX]
    bip_mass = hit_mass + out_mass
    supported = (hit_mass > 0.0) & (out_mass > 0.0) & (bip_mass > 0.0)
    conditional_hit = np.zeros(len(baseline), dtype=np.float64)
    conditional_hit[supported] = hit_mass[supported] / bip_mass[supported]
    adjusted_hit = conditional_hit.copy()
    adjusted_hit[supported] = _expit(
        np.log(conditional_hit[supported] / (1.0 - conditional_hit[supported])) + shifts_array[supported]
    )
    scale = np.ones(len(baseline), dtype=np.float64)
    scale[supported] = bip_mass[supported] * adjusted_hit[supported] / hit_mass[supported]
    result[:, HIT_INDICES] = baseline[:, HIT_INDICES] * scale[:, None]
    result[supported, OUT_INDEX] = bip_mass[supported] * (1.0 - adjusted_hit[supported])
    # A neutral profile is an exact no-op, including at the physical float level.
    # This avoids presenting harmless roundoff as a changed V18 probability.
    result[shifts_array == 0.0] = baseline[shifts_array == 0.0]

    if not np.array_equal(result[:, UNCHANGED_INDICES], baseline[:, UNCHANGED_INDICES]):
        raise RuntimeError("non-BIP probabilities changed")
    if not np.allclose(result[:, BIP_INDICES].sum(axis=1), bip_mass, rtol=0.0, atol=1e-12):
        raise RuntimeError("conditional BIP mass changed")
    if not np.allclose(result.sum(axis=1), 1.0, rtol=0.0, atol=1e-12):
        raise RuntimeError("probability mass changed")
    return result


def conditional_bip_hit_probability(probabilities: np.ndarray) -> np.ndarray:
    values = np.asarray(probabilities, dtype=np.float64)
    hit = values[:, HIT_INDICES].sum(axis=1)
    mass = hit + values[:, OUT_INDEX]
    result = np.full(len(values), np.nan)
    np.divide(hit, mass, out=result, where=mass > 0)
    return result


__all__ = [
    "BIP_CLASSES", "BIP_INDICES", "DefenseConfig", "DefenseState", "HIT_CLASSES",
    "HIT_INDICES", "OUT_CLASS", "OUT_INDEX", "UNCHANGED_INDICES", "apply_defense_shift",
    "conditional_bip_hit_probability", "defense_log_odds_shift", "fit_state",
]
