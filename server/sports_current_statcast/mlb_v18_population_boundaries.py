"""Add aggregate inning-boundary accounting to retained passive V18 arrays.

This postprocessor reads only its arguments. It does not invoke the simulator,
provider, RNG, model, or any source. It leaves the supplied arrays and metadata
unchanged and adds separately labeled counters to shallow/deep copies respectively.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

import numpy as np


SCHEMA_VERSION = "MLB_V18_PASSIVE_POPULATION_BOUNDARIES_V1"
ADDED_ARRAYS = (
    "automatic_runner_placements", "runners_after_last_transition",
    "walkoff_runner_remnants", "censored_runner_remnants",
)


def enrich_boundaries(
    arrays: Mapping[str, np.ndarray], metadata: Mapping[str, Any],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Derive automatic placements and aggregate end-of-transition remnants.

    ``automatic_runner_placements`` and ``runners_after_last_transition`` use
    [draw, batting team AWAY/HOME, inning]. Walkoff and censored remnants use
    [draw, batting team]. Their zeros outside the applicable terminal-reason
    mask mean the category does not apply, not that censoring was observed away.

    Automatic placements cover halves with at least one observed PA. A censored
    run may have switched into a new half with no PA; that boundary is explicitly
    counted in metadata and excluded from these observed-transition quantities.
    """
    if any(name in arrays for name in ADDED_ARRAYS) or "boundaryDerivation" in metadata:
        raise ValueError("boundary derivation already present; preserve its original receipt")
    completed = np.asarray(arrays["completed_pa"])
    if completed.ndim != 3 or completed.shape[1] != 2 or completed.shape[2] < 1:
        raise ValueError("completed_pa must have draw, AWAY/HOME, inning axes")
    shape = completed.shape
    n_sims = shape[0]
    if n_sims < 1 or int(metadata["simulationCount"]) != n_sims:
        raise ValueError("simulation count differs from retained arrays")
    regulation = int(metadata["regulationInnings"])
    if regulation < 1 or regulation != metadata["regulationInnings"]:
        raise ValueError("regulationInnings must be a positive integer")

    def counts(name: str, expected_shape: tuple[int, ...] = shape) -> np.ndarray:
        value = np.asarray(arrays[name])
        if value.shape != expected_shape or value.dtype.kind not in "biuf":
            raise ValueError("invalid retained count array: " + name)
        if not np.isfinite(value).all() or (value < 0).any() or (value != np.floor(value)).any():
            raise ValueError("nonintegral or negative retained count: " + name)
        return value.astype(np.int64, copy=False)

    completed = counts("completed_pa")
    started = counts("half_innings_started")
    ended = counts("half_innings_completed")
    outs = counts("outs_recorded")
    runs = counts("runs")
    lob = counts("runners_lob_third_out")
    terminal = counts("terminal_reason", (n_sims,))
    if not np.isin(terminal, (1, 2, 3, 4)).all():
        raise ValueError("terminal reasons must be finalized collector codes 1 through 4")

    automatic = started * (np.arange(shape[2])[None, None, :] >= regulation)
    residual = automatic + completed - outs - runs - lob
    team_residual = residual.sum(axis=2)
    walkoff = terminal == 1
    censored = terminal == 4
    other_terminal = (terminal == 2) | (terminal == 3)
    checks = {
        "halfStartedIsBinaryAndMatchesPA": bool(np.array_equal(started, completed > 0)),
        "halfCompletedIsBinary": bool(np.isin(ended, (0, 1)).all()),
        "completedHalvesWereStarted": bool((ended <= started).all()),
        "outsAgreeWithHalfCompletion": bool(((outs >= 0) & (outs <= 3)).all() and np.array_equal(ended, outs == 3)),
        "thirdOutLOBOnlyOnCompletedHalves": bool((lob[ended == 0] == 0).all()),
        "residualWithinBaseCapacity": bool(((residual >= 0) & (residual <= 3)).all()),
        "completedHalvesHaveZeroResidual": bool((residual[ended == 1] == 0).all()),
        "unstartedHalvesHaveZeroResidual": bool((residual[started == 0] == 0).all()),
        "eachDrawHasAnObservedPA": bool((started.sum(axis=(1, 2)) > 0).all()),
        "nonWalkoffFinishedGamesHaveZeroResidual": bool((team_residual[other_terminal] == 0).all()),
        "walkoffAwayResidualIsZero": bool((team_residual[walkoff, 0] == 0).all()),
        "perTeamResidualWithinBaseCapacity": bool(((team_residual >= 0) & (team_residual <= 3)).all()),
    }
    if not all(checks.values()):
        raise ValueError("boundary accounting failed: " + ", ".join(k for k, v in checks.items() if not v))

    # The frozen loop can switch half innings after its final permitted PA.
    # Such a new half has no event, so its automatic runner is not part of A/R.
    ordered_started = started.transpose(0, 2, 1).reshape(n_sims, -1)
    ordered_ended = ended.transpose(0, 2, 1).reshape(n_sims, -1)
    last_half = np.where(ordered_started > 0, np.arange(ordered_started.shape[1]), -1).max(axis=1)
    pending_half = censored & (ordered_ended[np.arange(n_sims), last_half] == 1)
    next_inning = (last_half + 1) // 2 + 1
    pending_automatic = pending_half & (next_inning > regulation)

    result_arrays = dict(arrays)
    result_arrays.update({
        "automatic_runner_placements": automatic.astype(np.int32),
        "runners_after_last_transition": residual.astype(np.int32),
        "walkoff_runner_remnants": np.where(walkoff[:, None], team_residual, 0).astype(np.int32),
        "censored_runner_remnants": np.where(censored[:, None], team_residual, 0).astype(np.int32),
    })
    definitions = {
        "axes": "Team axis is batting team [AWAY, HOME]; inning index 0 means inning 1.",
        "automatic_runner_placements": {
            "formula": "A = half_innings_started * (one_based_inning > regulationInnings)",
            "meaning": "One modeled runner placed at second base at the start of each observed extra-inning half. A placement is a deterministic non-PA boundary event, separate from sampled/nonmodeled non-PA events.",
            "coverage": "Halves with at least one observed completed PA only; exact for every terminated draw. Censored unobserved-next-half placements are excluded and counted separately below.",
        },
        "runners_after_last_transition": {
            "formula": "R = A + completed_pa - outs_recorded - runs - runners_lob_third_out",
            "meaning": "Exact aggregate occupied-runner count after the last observed transition in each half, by runner conservation. Completed halves have zero residual. Not exact runner identities or the simulator's stale terminal base-array cache.",
        },
        "walkoff_runner_remnants": {
            "formula": "sum_innings(R) where terminal_reason == 1 (WALKOFF); otherwise zero",
            "meaning": "Aggregate post-transition runners remaining on a walkoff. Away must be zero. Not official box-score LOB. Zero on other draw categories means not applicable; condition walkoff summaries on terminal_reason==1.",
        },
        "censored_runner_remnants": {
            "formula": "sum_innings(R) where terminal_reason == 4 (SIMULATION_LIMIT); otherwise zero",
            "meaning": "Aggregate runners after the last observed PA on a truncated draw, not a completed-game or walkoff statistic. Excludes any automatic runner already placed into an unobserved next half after that PA; never combine this with walkoff remnants.",
        },
        "nonPASeparation": "The original non_pa_event_count remains unchanged: structural NOT_MODELED zero for sampled non-PA events. Deterministic automatic runner placements are separately represented here and must not be described as absent.",
        "limitations": [
            "No runner identities, exact advancement paths, or official player/team LOB reconstruction.",
            "If censoredDrawsWithUnobservedNextHalf is nonzero, the last observed transition does not necessarily equal the loop's final post-switch state. Do not claim complete non-PA placement coverage for those draws.",
        ],
    }
    result_metadata = deepcopy(dict(metadata))
    result_metadata.setdefault("arrays", {}).update({
        name: {"shape": list(result_arrays[name].shape), "dtype": str(result_arrays[name].dtype)}
        for name in ADDED_ARRAYS
    })
    result_metadata.setdefault("definitions", {})["boundaries"] = definitions
    result_metadata["boundaryDerivation"] = {
        "schemaVersion": SCHEMA_VERSION, "extraRandomDraws": 0, "simulationReruns": 0,
        "checks": checks, "allPassed": True,
        "walkoffDraws": int(walkoff.sum()), "censoredDraws": int(censored.sum()),
        "censoredDrawsWithUnobservedNextHalf": int(pending_half.sum()),
        "censoredAutomaticPlacementsOutsideObservedHalves": int(pending_automatic.sum()),
        "completeAutomaticPlacementCoverageForAllDraws": not bool(pending_automatic.any()),
        "automaticRunnerPlacementsByBattingTeam": automatic.sum(axis=(0, 2)).tolist(),
        "walkoffRunnerRemnantsByBattingTeam": result_arrays["walkoff_runner_remnants"].sum(axis=0).tolist(),
        "censoredRunnerRemnantsByBattingTeam": result_arrays["censored_runner_remnants"].sum(axis=0).tolist(),
    }
    return result_arrays, result_metadata


__all__ = ["enrich_boundaries", "SCHEMA_VERSION", "ADDED_ARRAYS"]
