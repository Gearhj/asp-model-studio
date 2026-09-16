"""Hierarchically smoothed MLB PA-to-game transition provider.

This is a research-only drop-in replacement for ``TransitionModel``.  It keeps
the accepted eight PA classes and legality contract.  The only intervention is
the prior used inside each outcome/outs/base cell: every observed exact-cell
count is retained and shrunk toward the broader outcome/outs distribution,
then the outcome distribution.  A very small uniform legal floor preserves
finite loss for an unseen but mechanically legal transition.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from server.sports_phase5 import base_out_transition as bt


SCHEMA_VERSION = "MLB_BASE_OUT_TRANSITION_HIERARCHICAL_SHRINKAGE_V1"
DEFAULT_PRIOR_STRENGTH = 20.0
DEFAULT_LEGAL_FLOOR = 1e-6


def _key(outcome: str, outs: int, base: int) -> str:
    return f"{outcome}|{outs}|{base}"


def _decode(table: Mapping[str, Mapping[str, int]]) -> dict[str, dict[tuple[int, int, int], int]]:
    return {
        key: {tuple(int(part) for part in transition.split(",")): int(count)
              for transition, count in counts.items()}
        for key, counts in table.items()
    }


def _encode(table: Mapping[str, Mapping[tuple[int, int, int], int]]) -> dict[str, dict[str, int]]:
    return {
        key: {",".join(str(part) for part in transition): int(count)
              for transition, count in counts.items()}
        for key, counts in table.items()
    }


@dataclass(frozen=True)
class HierarchicalTransitionModel:
    cells: dict[str, dict[tuple[int, int, int], int]]
    by_outcome_outs: dict[str, dict[tuple[int, int, int], int]]
    by_outcome: dict[str, dict[tuple[int, int, int], int]]
    seasons: tuple[int, ...]
    prior_strength: float = DEFAULT_PRIOR_STRENGTH
    legal_floor: float = DEFAULT_LEGAL_FLOOR

    @classmethod
    def from_baseline(cls, model: bt.TransitionModel, *, prior_strength: float = DEFAULT_PRIOR_STRENGTH,
                      legal_floor: float = DEFAULT_LEGAL_FLOOR) -> "HierarchicalTransitionModel":
        if prior_strength <= 0 or legal_floor <= 0:
            raise ValueError("Positive shrinkage strength and legal floor are required")
        return cls(cells=model.cells, by_outcome_outs=model.by_outcome_outs,
                   by_outcome=model.by_outcome, seasons=model.seasons,
                   prior_strength=float(prior_strength), legal_floor=float(legal_floor))

    def _prior(self, outcome: str, outs_before: int,
               legal: list[tuple[int, int, int]]) -> tuple[dict[tuple[int, int, int], float], str]:
        legal_set = set(legal)
        for level, counts in (
            ("OUTCOME_OUTS", self.by_outcome_outs.get(f"{outcome}|{outs_before}", {})),
            ("OUTCOME", self.by_outcome.get(outcome, {})),
        ):
            supported = {transition: count for transition, count in counts.items()
                         if transition in legal_set and count > 0}
            total = float(sum(supported.values()))
            if total:
                return ({transition: supported.get(transition, 0) / total for transition in legal}, level)
        uniform = 1.0 / len(legal)
        return ({transition: uniform for transition in legal}, "LEGAL_UNIFORM")

    def distribution(self, outcome: str, outs_before: int, base_before: int) -> dict[str, Any]:
        if outcome not in bt.PA_CLASSES:
            raise bt.TransitionModelError(f"unknown PA outcome: {outcome}")
        legal = bt.enumerate_legal_transitions(outs_before, base_before)
        if outcome == "HOME_RUN":
            deterministic = bt.home_run_transition(outs_before, base_before)
            probabilities = {transition: float(transition == deterministic) for transition in legal}
            return self._finalize(probabilities, legal, "DETERMINISTIC_HOME_RUN", 0,
                                  "MECHANICAL", outs_before, base_before)
        exact = self.cells.get(_key(outcome, outs_before, base_before), {})
        exact = {transition: count for transition, count in exact.items() if transition in set(legal)}
        prior, prior_level = self._prior(outcome, outs_before, legal)
        weights = {
            transition: float(exact.get(transition, 0))
            + self.prior_strength * prior[transition]
            + self.legal_floor
            for transition in legal
        }
        total = sum(weights.values())
        probabilities = {transition: weight / total for transition, weight in weights.items()}
        return self._finalize(probabilities, legal, "HIERARCHICAL_EXACT", sum(exact.values()),
                              prior_level, outs_before, base_before)

    @staticmethod
    def _finalize(probabilities: Mapping[tuple[int, int, int], float],
                  legal: list[tuple[int, int, int]], level: str, support: int,
                  prior_level: str, outs_before: int, base_before: int) -> dict[str, Any]:
        ordered = sorted(probabilities.items(), key=lambda item: (-item[1], item[0]))
        result = {
            "fallbackLevel": level,
            "priorLevel": prior_level,
            "support": int(support),
            "legalTransitionCount": len(legal),
            "entropy": float(-sum(p * math.log(p) for _, p in ordered if p > 0)),
            "maxProbability": float(ordered[0][1]),
            "transitions": [
                {"outsAdded": transition[0], "baseMaskAfter": transition[1],
                 "runs": transition[2], "probability": float(probability)}
                for transition, probability in ordered
            ],
        }
        bt.validate_distribution(result, outs_before, base_before)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "priorStrength": self.prior_strength,
            "legalFloor": self.legal_floor,
            "seasons": list(self.seasons),
            "cells": _encode(self.cells),
            "byOutcomeOuts": _encode(self.by_outcome_outs),
            "byOutcome": _encode(self.by_outcome),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HierarchicalTransitionModel":
        if payload.get("schemaVersion") != SCHEMA_VERSION:
            raise ValueError("Hierarchical transition schema differs")
        return cls(cells=_decode(payload["cells"]), by_outcome_outs=_decode(payload["byOutcomeOuts"]),
                   by_outcome=_decode(payload["byOutcome"]), seasons=tuple(payload["seasons"]),
                   prior_strength=float(payload["priorStrength"]), legal_floor=float(payload["legalFloor"]))
__all__ = [
    "SCHEMA_VERSION", "DEFAULT_PRIOR_STRENGTH", "DEFAULT_LEGAL_FLOOR",
    "HierarchicalTransitionModel",
]
