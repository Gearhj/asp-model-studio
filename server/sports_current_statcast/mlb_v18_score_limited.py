"""Symmetric whole-game rejection of an immutable V18 simulation population.

This component has no simulator, estimator, source, outcome, or RNG dependency.
The caller must verify the frozen forecast/diagnostic binding and publish the
development-derived rule before examining challenger performance. This module
does not derive, fit, tune, or select limits. Accepted draws retain their exact
original scores, paired identities, innings, and PA counts. Filtering preserves
original draw indices and underlying games without rewriting them. Existing
recorded sequence evidence stays bound; unsaved full sequences are neither
claimed to have been retained nor reconstructed by this component.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import numpy as np


COMPONENT_ID = "MLB_V18_SCORE_LIMITED_V1"
MIN_RETAINED_DRAWS = 1000
BASELINE_ARRAY_NAMES = ("homeRuns", "awayRuns", "innings", "paCounts")
REQUIRED_COUNTER_NAMES = ("runs", "half_innings_started", "terminal_reason")
RULE_FIELDS = ("maxRunsPerPlayedHalfInning", "maxRunsPerTeamGame")
COMPLETE_TERMINAL_REASONS = (1, 2, 3)


class ScoreLimitError(ValueError):
    """The proposed rule or bound population fails an accounting requirement."""


def _integer_array(value: Any, *, name: str, shape: tuple[int, ...] | None = None,
                   positive: bool = False) -> np.ndarray:
    array = np.asarray(value)
    if (array.dtype.kind not in "biuf" or not np.isfinite(array).all()
            or (array < (1 if positive else 0)).any()
            or not np.equal(array, np.floor(array)).all()):
        raise ScoreLimitError(name + " must contain finite nonnegative integers")
    if shape is not None and array.shape != shape:
        raise ScoreLimitError(name + " has a different shape from the frozen population")
    return array


def _mean_mcse(values: np.ndarray) -> float:
    return float(np.std(values, ddof=1) / np.sqrt(len(values))) if len(values) > 1 else 0.0


def _metrics(arrays: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    home = np.asarray(arrays["homeRuns"], dtype=np.float64)
    away = np.asarray(arrays["awayRuns"], dtype=np.float64)
    return {
        "homeWinProbability": (home > away).astype(np.float64),
        "awayWinProbability": (away > home).astype(np.float64),
        "tieProbability": (home == away).astype(np.float64),
        "meanHomeRuns": home, "meanAwayRuns": away,
        "meanTotalRuns": home + away, "meanRunDifferential": home - away,
    }


def _summary(metrics: Mapping[str, np.ndarray]) -> dict[str, float]:
    return {name: float(values.mean()) for name, values in metrics.items()}


def _readonly_copy(values: np.ndarray) -> np.ndarray:
    copied = values.copy()
    copied.flags.writeable = False
    return copied


def apply_score_limits(
    baseline_arrays: Mapping[str, Any],
    diagnostic_arrays: Mapping[str, Any] | None,
    rule: Mapping[str, Any],
) -> dict[str, Any]:
    """Filter complete games with a frozen, common-to-both-teams integer rule.

    ``baseline_arrays`` supplies homeRuns, awayRuns, innings and paCounts in
    original simulation-index order. Diagnostics must use the identical order:
    ``runs`` and ``half_innings_started`` have shape (draw, AWAY/HOME, inning),
    and ``terminal_reason`` has shape (draw,) with passive-observer codes 1/2/3
    for natural completion and 4 for a simulation limit. A played walkoff half
    inning is eligible for the inning limit even if fewer than three outs were
    recorded. Unplayed cells are excluded from the limit and must be zero.

    A draw is rejected only when either team's played half-inning exceeds
    maxRunsPerPlayedHalfInning or final score exceeds maxRunsPerTeamGame.
    Equality is accepted. Limits apply to every inning, including extras.

    Missing counters, incomplete draws and fewer than 1,000 accepted draws
    produce explicit unsupported statuses and no candidate summary. Invalid
    accounting or rules raise ScoreLimitError. No input, array flags, baseline
    summary, score, sequence, or stochastic state is modified. Returned accepted
    arrays are independent read-only copies; indices bind the original sequence.

    Uncertainty describes simulation sampling only. Candidate-minus-baseline
    MCSE uses the shared original draws and a ratio-estimator influence function:
    A_i*(x_i-candidate_mean)/acceptance_rate - (x_i-baseline_mean). It is not an
    independent-arm SE, predictive-error interval, or evidence of future gain.
    """
    limits: dict[str, int] = {}
    for field in RULE_FIELDS:
        value = rule.get(field)
        if (isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer))
                or value < 0):
            raise ScoreLimitError(field + " must be a nonnegative integer published in the frozen rule")
        limits[field] = int(value)
    missing_baseline = [name for name in BASELINE_ARRAY_NAMES if name not in baseline_arrays]
    if missing_baseline:
        raise ScoreLimitError("missing frozen baseline arrays: " + ", ".join(missing_baseline))
    home = np.asarray(baseline_arrays["homeRuns"])
    if home.ndim != 1 or not len(home):
        raise ScoreLimitError("frozen baseline must contain a nonempty one-dimensional draw population")
    count = len(home)
    baseline = {name: _integer_array(baseline_arrays[name], name=name, shape=(count,),
                                     positive=name in ("innings", "paCounts"))
                for name in BASELINE_ARRAY_NAMES}
    metrics = _metrics(baseline)
    baseline_summary = _summary(metrics)
    result: dict[str, Any] = {
        "componentIdentity": COMPONENT_ID,
        "rule": limits,
        "minimumRetainedDraws": MIN_RETAINED_DRAWS,
        "originalDrawCount": count,
        "baselineSummary": baseline_summary,
        "summary": None, "uncertainty": None,
        "acceptMask": None, "acceptedDrawIndices": None, "retainedArrays": None,
        "authority": {"productionEnabled": False, "promotionEligible": False},
        "definitions": {
            "exclusion": "Reject the complete original game if any played half-inning or either team's final score strictly exceeds its common limit; never clip, resample, stop early, or change a sequence.",
            "teamOrder": ["AWAY", "HOME"],
            "winnerProbabilities": "Home win, away win and tie counts divided by actual retained draw count; ties are retained and never split or manufactured.",
            "expectedScores": "Arithmetic means over retained original paired scores.",
            "minimumRetainedDraws": "Fixed at 1,000 before challenger performance; a smaller retained population is reported without a candidate forecast.",
            "uncertainty": "Simulation sampling precision conditional on the frozen simulator and rule; not uncertainty about model, input error or predictive improvement.",
            "pairedDifferenceMCSE": "Sample SD of [A_i*(x_i-candidate_mean)/acceptance_rate - (x_i-baseline_mean)] divided by sqrt(original draw count).",
            "missingCounters": "No reconstruction, partial-population filtering, or unrestricted-baseline relabeling is performed.",
        },
    }
    missing = [name for name in REQUIRED_COUNTER_NAMES
               if diagnostic_arrays is None or name not in diagnostic_arrays]
    if missing:
        result.update(status="UNSUPPORTED_MISSING_COUNTERS", missingCounters=missing)
        return result
    assert diagnostic_arrays is not None
    runs = _integer_array(diagnostic_arrays["runs"], name="runs")
    if runs.ndim != 3 or runs.shape[:2] != (count, 2) or runs.shape[2] < 1:
        raise ScoreLimitError("runs must have shape (frozen draw count, AWAY/HOME, inning)")
    played = _integer_array(diagnostic_arrays["half_innings_started"],
                            name="half_innings_started", shape=runs.shape)
    if (played > 1).any():
        raise ScoreLimitError("half_innings_started must be zero or one")
    terminal = _integer_array(diagnostic_arrays["terminal_reason"],
                              name="terminal_reason", shape=(count,))
    if not np.isin(terminal, COMPLETE_TERMINAL_REASONS + (4,)).all():
        raise ScoreLimitError("terminal_reason contains unknown or unfinalized values")
    if (runs[played == 0] != 0).any():
        raise ScoreLimitError("unplayed half-innings contain nonzero runs")
    if not np.array_equal(runs[:, 0].sum(axis=1), baseline["awayRuns"]):
        raise ScoreLimitError("away inning runs do not reconcile to the immutable baseline")
    if not np.array_equal(runs[:, 1].sum(axis=1), baseline["homeRuns"]):
        raise ScoreLimitError("home inning runs do not reconcile to the immutable baseline")
    for saved, original in (("home_runs", "homeRuns"), ("away_runs", "awayRuns"),
                            ("innings", "innings"), ("pa_counts", "paCounts")):
        if saved in diagnostic_arrays and not np.array_equal(diagnostic_arrays[saved], baseline[original]):
            raise ScoreLimitError("diagnostic saved " + saved + " differs from the frozen baseline")
    incomplete = ~np.isin(terminal, COMPLETE_TERMINAL_REASONS)
    if incomplete.any():
        result.update(status="UNSUPPORTED_INCOMPLETE_GAMES", incompleteDrawCount=int(incomplete.sum()))
        return result
    inning_numbers = np.arange(1, runs.shape[2] + 1, dtype=np.int64)
    last_played = np.where(played.any(axis=1), inning_numbers, 0).max(axis=1)
    if not np.array_equal(last_played, baseline["innings"]):
        raise ScoreLimitError("last played inning does not equal the immutable completed-game inning")
    if not (played[:, 0].sum(axis=1) > 0).all() or not (played[:, 1].sum(axis=1) > 0).all():
        raise ScoreLimitError("a completed game lacks played innings for one team")
    inning_violation = ((runs > limits[RULE_FIELDS[0]]) & (played == 1)).any(axis=(1, 2))
    game_violation = ((baseline["homeRuns"] > limits[RULE_FIELDS[1]])
                      | (baseline["awayRuns"] > limits[RULE_FIELDS[1]]))
    accepted = ~(inning_violation | game_violation)
    retained = int(accepted.sum())
    intersection = int((inning_violation & game_violation).sum())
    exclusions = {
        "inningLimitExceeded": int(inning_violation.sum()),
        "teamGameLimitExceeded": int(game_violation.sum()),
        "bothLimitsExceeded": intersection,
        "inningOnly": int((inning_violation & ~game_violation).sum()),
        "teamGameOnly": int((game_violation & ~inning_violation).sum()),
        "eitherLimitExceeded": count - retained,
    }
    if exclusions["inningLimitExceeded"] + exclusions["teamGameLimitExceeded"] - intersection != count - retained:
        raise ScoreLimitError("exclusion union and intersection do not reconcile")
    result.update(
        acceptMask=_readonly_copy(accepted),
        acceptedDrawIndices=_readonly_copy(np.flatnonzero(accepted)),
        retainedDrawCount=retained, excludedDrawCount=count - retained,
        acceptanceRate=retained / count, exclusionRate=(count - retained) / count,
        exclusions=exclusions,
        accounting={"allPassed": True, "inningScoresEqualFrozenScores": True,
                    "unplayedCellsAreZero": True, "allDrawsNaturallyCompleted": True,
                    "inningCountMatchesFrozenPopulation": True,
                    "exclusionUnionIntersectionReconciled": True},
    )
    if retained < MIN_RETAINED_DRAWS:
        result.update(status="INSUFFICIENT_RETAINED_DRAWS")
        return result
    candidate_metrics = {name: values[accepted] for name, values in metrics.items()}
    candidate_summary = _summary(candidate_metrics)
    probability_sum = sum(candidate_summary[name] for name in
                          ("homeWinProbability", "awayWinProbability", "tieProbability"))
    if not np.isclose(probability_sum, 1.0, rtol=0, atol=1e-15):
        raise ScoreLimitError("retained winner probabilities do not sum to one")
    acceptance_rate = retained / count
    uncertainty: dict[str, Any] = {
        "baselineMCSE": {}, "candidateMCSE": {},
        "candidateMinusBaseline": {}, "pairedDifferenceMCSE": {},
        "acceptanceRateMCSE": float(np.sqrt(acceptance_rate * (1 - acceptance_rate) / count)),
        "method": "Analytic mean/indicator MCSE and shared-population ratio influence function; no bootstrap, independent-arm assumption, or added random draws.",
    }
    for name, values in metrics.items():
        base_mean, candidate_mean = baseline_summary[name], candidate_summary[name]
        if name.endswith("Probability"):
            uncertainty["baselineMCSE"][name] = float(np.sqrt(base_mean * (1 - base_mean) / count))
            uncertainty["candidateMCSE"][name] = float(np.sqrt(candidate_mean * (1 - candidate_mean) / retained))
        else:
            uncertainty["baselineMCSE"][name] = _mean_mcse(values)
            uncertainty["candidateMCSE"][name] = _mean_mcse(candidate_metrics[name])
        influence = accepted * (values - candidate_mean) / acceptance_rate - (values - base_mean)
        uncertainty["candidateMinusBaseline"][name] = candidate_mean - base_mean
        uncertainty["pairedDifferenceMCSE"][name] = _mean_mcse(influence)
    result.update(
        status="SUPPORTED", summary=candidate_summary, uncertainty=uncertainty,
        retainedArrays={name: _readonly_copy(values[accepted]) for name, values in baseline.items()},
    )
    result["accounting"]["winnerProbabilitySum"] = probability_sum
    result["accounting"]["retainedArraysEqualOriginalIndexedDraws"] = all(
        np.array_equal(result["retainedArrays"][name], values[result["acceptedDrawIndices"]])
        for name, values in baseline.items()
    )
    return result


def run_focused_checks() -> dict[str, Any]:
    """Synthetic checks only; does not inspect real limits, outcomes or forecasts."""
    # Six synthetic paired score patterns: at boundary, game-only violation,
    # inning-only violation, both violations, mirrored boundary, and a retained
    # tie. Repetition supplies enough draws for the fixed 1,000-draw requirement.
    patterns = np.asarray([[[2, 1], [1, 0]], [[2, 2], [1, 0]],
                           [[3, 0], [1, 0]], [[4, 0], [1, 0]],
                           [[1, 0], [2, 1]], [[2, 0], [2, 0]]], dtype=np.int32)
    runs = np.tile(patterns, (1000, 1, 1))
    baseline = {"homeRuns": runs[:, 1].sum(axis=1), "awayRuns": runs[:, 0].sum(axis=1),
                "innings": np.full(len(runs), 2, dtype=np.int64),
                "paCounts": np.full(len(runs), 20, dtype=np.int64)}
    diagnostics = {"runs": runs, "half_innings_started": np.ones_like(runs),
                   "terminal_reason": np.full(len(runs), 2, dtype=np.int8)}
    originals = {"baseline/" + name: (value.copy(), value.flags.writeable)
                 for name, value in baseline.items()}
    originals.update({"diagnostics/" + name: (value.copy(), value.flags.writeable)
                      for name, value in diagnostics.items()})
    rule = {"maxRunsPerPlayedHalfInning": 2, "maxRunsPerTeamGame": 3}
    filtered = apply_score_limits(baseline, diagnostics, rule)
    expected_mask = np.tile([True, False, False, False, True, True], 1000)
    checks: dict[str, bool] = {
        "strictBoundariesAndUnion": bool(np.array_equal(filtered["acceptMask"], expected_mask)),
        "actualAcceptedDenominator": filtered["retainedDrawCount"] == 3000,
        "pairedScoresAndIndicesPreserved": filtered["accounting"]["retainedArraysEqualOriginalIndexedDraws"],
        "tiesNotSplitOrManufactured": all(np.isclose(filtered["summary"][name], 1 / 3)
                                          for name in ("homeWinProbability", "awayWinProbability", "tieProbability")),
        "exclusionUnionIntersection": filtered["exclusions"] == {
            "inningLimitExceeded": 2000, "teamGameLimitExceeded": 2000,
            "bothLimitsExceeded": 1000, "inningOnly": 1000, "teamGameOnly": 1000,
            "eitherLimitExceeded": 3000},
        "retainedCopiesReadOnly": all(not value.flags.writeable for value in filtered["retainedArrays"].values()),
    }
    swapped_baseline = dict(baseline, homeRuns=baseline["awayRuns"], awayRuns=baseline["homeRuns"])
    swapped_diagnostics = dict(diagnostics, runs=runs[:, ::-1],
                               half_innings_started=diagnostics["half_innings_started"][:, ::-1])
    mirrored = apply_score_limits(swapped_baseline, swapped_diagnostics, rule)
    checks["teamSymmetry"] = bool(np.array_equal(mirrored["acceptMask"], expected_mask))
    checks["winnerSymmetry"] = (mirrored["summary"]["homeWinProbability"] == filtered["summary"]["awayWinProbability"])
    unrestricted = apply_score_limits(baseline, diagnostics,
                                      {"maxRunsPerPlayedHalfInning": 99, "maxRunsPerTeamGame": 99})
    checks["noExclusionsExactlyReproducesBaseline"] = unrestricted["summary"] == unrestricted["baselineSummary"]
    checks["pairedDifferenceNoiseZeroForIdentity"] = all(value == 0.0 for value in unrestricted["uncertainty"]["pairedDifferenceMCSE"].values())
    base_indicator = (baseline["homeRuns"] > baseline["awayRuns"]).astype(float)
    manual_influence = expected_mask * (base_indicator - 1 / 3) / .5 - (base_indicator - 1 / 6)
    checks["pairedRatioInfluenceFormula"] = bool(np.isclose(
        filtered["uncertainty"]["pairedDifferenceMCSE"]["homeWinProbability"],
        np.std(manual_influence, ddof=1) / np.sqrt(len(runs)), rtol=0, atol=1e-15))
    checks["candidateProbabilityMCSEUsesAcceptedN"] = bool(np.isclose(
        filtered["uncertainty"]["candidateMCSE"]["homeWinProbability"], np.sqrt((1 / 3) * (2 / 3) / 3000)))
    tiny = apply_score_limits({key: value[:6] for key, value in baseline.items()},
                              {key: value[:6] for key, value in diagnostics.items()}, rule)
    checks["tooFewDrawsProducesNoForecast"] = tiny["status"] == "INSUFFICIENT_RETAINED_DRAWS" and tiny["summary"] is None
    missing = apply_score_limits(baseline, None, rule)
    checks["missingCountersExplicit"] = missing["status"] == "UNSUPPORTED_MISSING_COUNTERS" and missing["summary"] is None
    nonterminal = dict(diagnostics, terminal_reason=diagnostics["terminal_reason"].copy())
    nonterminal["terminal_reason"][0] = 4
    incomplete = apply_score_limits(baseline, nonterminal, rule)
    checks["incompleteGamesNotSilentlyFiltered"] = incomplete["status"] == "UNSUPPORTED_INCOMPLETE_GAMES" and incomplete["summary"] is None
    bad = dict(diagnostics, half_innings_started=diagnostics["half_innings_started"].copy())
    bad["half_innings_started"][0, 0, 0] = 0
    try:
        apply_score_limits(baseline, bad, rule)
    except ScoreLimitError:
        checks["unplayedNonzeroRunsRejected"] = True
    else:
        checks["unplayedNonzeroRunsRejected"] = False
    bad_scores = dict(baseline, homeRuns=baseline["homeRuns"].copy())
    bad_scores["homeRuns"][0] += 1
    try:
        apply_score_limits(bad_scores, diagnostics, rule)
    except ScoreLimitError:
        checks["mismatchedFrozenScoresRejected"] = True
    else:
        checks["mismatchedFrozenScoresRejected"] = False
    checks["allOriginalValuesAndFlagsUnchanged"] = all(
        np.array_equal((baseline if name.startswith("baseline/") else diagnostics)[name.split("/", 1)[1]], saved)
        and (baseline if name.startswith("baseline/") else diagnostics)[name.split("/", 1)[1]].flags.writeable == writeable
        for name, (saved, writeable) in originals.items()
    )
    if not all(checks.values()):
        raise AssertionError("score-limit checks failed: " + ", ".join(name for name, value in checks.items() if not value))
    return {"componentIdentity": COMPONENT_ID, "data": "SYNTHETIC_ONLY",
            "checks": checks, "allPassed": True, "checkCount": len(checks),
            "randomDraws": 0, "minimumRetainedDraws": MIN_RETAINED_DRAWS}


if __name__ == "__main__":
    print(json.dumps(run_focused_checks(), indent=2, sort_keys=True))


__all__ = ["COMPONENT_ID", "MIN_RETAINED_DRAWS", "ScoreLimitError",
           "apply_score_limits", "run_focused_checks"]
