"""Isolated two-arm rollout: frozen V18 mechanics, only the starter hook differs.

The source loop has no hook callback. Its score/inning/transition/RNG mechanics
are reproduced here with an exact source binding and a reference-equivalence
test. Neither the production module nor its global hook is patched at runtime.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5.whole_game_monte_carlo import FastTransitionSampler
from . import mlb_v18_whole_game_challenger as frozen
from .mlb_duration_research_adapter import removal_probability
from .mlb_starter_survival_models import PREGAME_FIELDS

SCHEMA = "MLB_STARTER_DURATION_PAIRED_SIMULATION_V1"
REFERENCE = "REFERENCE_EXISTING_HOOK"
CHALLENGER = "CHALLENGER_HGB_DURATION"
FROZEN_SOURCE_SHA256 = "d9e5151141c697d6d8080e47c3c50ebfc5297764155a7f16de455152939bcac7"
MAX_PA = 200
POPULATION_ARRAYS = ("homeRuns", "awayRuns", "innings", "paCounts", "homeStarterBf", "awayStarterBf",
    "homeStarterOuts", "awayStarterOuts", "homeRelieverBf", "awayRelieverBf",
    "homeRelieverOuts", "awayRelieverOuts", "homeStarterRemoved", "awayStarterRemoved")


class PairedSimulationError(RuntimeError):
    pass


def verify_frozen_mechanics() -> dict:
    path = Path(frozen.__file__).resolve()
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != FROZEN_SOURCE_SHA256:
        raise PairedSimulationError("FROZEN_SIMULATOR_SOURCE_BINDING_CHANGED")
    return {"path": str(path), "sha256": digest, "bytes": len(data),
        "entryPoint": "simulate_prospective_game", "productionCodeModified": False}


def _deadline(value):
    if value is None:
        return
    limit = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if limit.tzinfo is None:
        raise PairedSimulationError("AWARE_PREGAME_DEADLINE_REQUIRED")
    if datetime.now(timezone.utc) >= limit:
        raise PairedSimulationError("PAIRED_PREGAME_DEADLINE_EXPIRED")


def _duration_lookup(model, home: Mapping, away: Mapping) -> tuple[np.ndarray, dict]:
    if model.model_id != "HGB_PREGAME" or tuple(model.feature_order) != tuple(PREGAME_FIELDS):
        raise PairedSimulationError("FROZEN_HGB_PREGAME_FEATURE_CONTRACT_REQUIRED")
    fields = tuple(name for name in PREGAME_FIELDS if name != "bf")
    rows = []
    for orientation, values in ((0, away), (1, home)):
        if set(fields) - set(values):
            raise PairedSimulationError("MISSING_DURATION_PREGAME_INPUT:" + ",".join(sorted(set(fields)-set(values))))
        if values["homePitcher"] != orientation:
            raise PairedSimulationError("DURATION_HOME_AWAY_ORIENTATION_MISMATCH")
        for name in ("homePitcher", "calendarMonth", "priorStartCount", "historyMissing"):
            if not np.isfinite(float(values[name])):
                raise PairedSimulationError("UNSUPPORTED_MISSING_DURATION_INPUT:" + name)
        if (values["calendarMonth"] not in range(1, 13) or values["priorStartCount"] < 0
                or values["historyMissing"] not in (0, 1)):
            raise PairedSimulationError("INVALID_DURATION_PREGAME_INPUT")
        rows.extend({**{name: values[name] for name in fields}, "bf": bf} for bf in range(1, MAX_PA + 1))
    frame = pd.DataFrame(rows, columns=PREGAME_FIELDS)
    probabilities = removal_probability(model, frame,
        game_active=np.ones(len(frame), bool), starter_active=np.ones(len(frame), bool))
    if (not np.isfinite(probabilities).all() or (probabilities < 0).any() or (probabilities > 1).any()):
        raise PairedSimulationError("INVALID_CONDITIONAL_REMOVAL_PROBABILITIES")
    lookup = np.zeros((2, MAX_PA + 1))
    lookup[:, 1:] = probabilities.reshape(2, MAX_PA)
    return lookup, {"actualDurationPredictCalls": 1, "rowsScored": len(frame),
        "calibrated": True, "fittedTemperature": float(model.temperature),
        "BFZeroScored": False, "bfGrid": [1, MAX_PA],
        "meaning": "Frozen conditional next-opportunity hazard; grid extends to shared simulator watchdog, not a forced removal or second GAME_END draw"}


def _distribution(values):
    return [{"value": int(v), "count": int(n), "probability": n/len(values)}
            for v, n in sorted(Counter(map(int, values)).items())]


def _summary(values):
    values = np.asarray(values)
    return {"mean": float(values.mean()), "minimum": int(values.min()), "maximum": int(values.max()),
        "quantiles": {str(q): float(np.quantile(values, q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
        "distribution": _distribution(values)}


def simulate_research_arm(*, game_id: str, provider: Any, transition_model: bt.TransitionModel,
        n_sims: int, master_seed: int, arm: str, duration_lookup=None,
        regulation: int = 9, trace_count: int = 1, deadline_utc=None) -> dict:
    """Run the existing game loop; intervention is exactly the hook probability.

    The pending defensive opportunity follows the starter's completed BF count.
    A half-inning break does not create an extra draw: the next draw occurs only
    when the pitcher next has an actual simulated opportunity. BF0 never hooks.
    """
    verify_frozen_mechanics()
    _deadline(deadline_utc)
    if arm not in (REFERENCE, CHALLENGER) or n_sims <= 0 or not 0 <= trace_count <= min(6, n_sims):
        raise PairedSimulationError("INVALID_RESEARCH_ARM_OR_BUDGET")
    if regulation <= 0:
        raise PairedSimulationError("INVALID_REGULATION_LENGTH")
    if arm == CHALLENGER and (duration_lookup is None or np.asarray(duration_lookup).shape != (2, MAX_PA+1)):
        raise PairedSimulationError("AUTHENTICATED_DURATION_LOOKUP_REQUIRED")
    game_entropy = int.from_bytes(hashlib.sha256(game_id.encode("utf-8")).digest()[:8], "big")
    pa_seed, transition_seed, hook_seed = np.random.SeedSequence([master_seed, game_entropy]).spawn(3)
    pa_rng, transition_rng, hook_rng = (np.random.default_rng(seed) for seed in (pa_seed, transition_seed, hook_seed))
    sampler = FastTransitionSampler(transition_model)
    inning, top = np.ones(n_sims, dtype=np.int64), np.ones(n_sims, dtype=bool)
    outs, base = np.zeros(n_sims, dtype=np.int64), np.zeros(n_sims, dtype=np.int64)
    away_score, home_score = np.zeros(n_sims, dtype=np.int64), np.zeros(n_sims, dtype=np.int64)
    away_pa, home_pa = np.zeros(n_sims, dtype=np.int64), np.zeros(n_sims, dtype=np.int64)
    pa_count = np.zeros(n_sims, dtype=np.int64)
    away_starter_active, home_starter_active = np.ones(n_sims, dtype=bool), np.ones(n_sims, dtype=bool)
    away_bf, home_bf = np.zeros(n_sims, dtype=np.int64), np.zeros(n_sims, dtype=np.int64)
    away_starter_runs, home_starter_runs = np.zeros(n_sims, dtype=np.int64), np.zeros(n_sims, dtype=np.int64)
    away_starter_outs, home_starter_outs = np.zeros(n_sims, dtype=np.int64), np.zeros(n_sims, dtype=np.int64)
    away_relief_outs, home_relief_outs = np.zeros(n_sims, dtype=np.int64), np.zeros(n_sims, dtype=np.int64)
    terminal = np.zeros(n_sims, dtype=bool)
    illegal, unsupported_bf_zero_hooks = 0, 0
    traces = [[] for _ in range(trace_count)]

    for step in range(MAX_PA):
        _deadline(deadline_utc)
        if terminal.all():
            break
        active = ~terminal
        pitching_home = top
        active_starter = np.where(pitching_home, home_starter_active, away_starter_active)
        bf = np.where(pitching_home, home_bf, away_bf)
        starter_runs = np.where(pitching_home, home_starter_runs, away_starter_runs)
        batting_pa = np.where(top, away_pa, home_pa)
        if arm == REFERENCE:
            hook_p = frozen.starter_removal_probability(inning, bf, starter_runs, bf // 9 + 1)
        else:
            hook_p = duration_lookup[pitching_home.astype(int), bf]
        change = active & active_starter & (hook_rng.random(n_sims) < hook_p)
        unsupported_bf_zero_hooks += int((change & (bf == 0)).sum())
        if unsupported_bf_zero_hooks:
            raise PairedSimulationError("UNSUPPORTED_BF_ZERO_HOOK")
        home_starter_active &= ~(change & pitching_home)
        away_starter_active &= ~(change & ~pitching_home)
        bullpen = np.where(pitching_home, ~home_starter_active, ~away_starter_active)
        diff = np.where(top, away_score-home_score, home_score-away_score)
        probabilities = provider.probabilities(top=top, batting_pa=batting_pa, inning=inning, outs=outs,
            base=base, score_diff=diff, bullpen=bullpen)
        if (probabilities.shape != (n_sims, 8) or not np.isfinite(probabilities).all()
                or (probabilities < 0).any() or not np.allclose(probabilities.sum(1), 1.0, atol=1e-12)):
            raise PairedSimulationError("INVALID_FROZEN_PA_PROBABILITIES")
        u = pa_rng.random(n_sims)
        outcome_index = (np.cumsum(probabilities, axis=1) < u[:, None]).sum(axis=1)
        np.clip(outcome_index, 0, 7, out=outcome_index)
        transition = sampler.sample(outcome_index*24+outs*8+base, transition_rng.random(n_sims))
        outs_added, base_after, runs = transition[:, 0], transition[:, 1], transition[:, 2]
        for simulation in np.nonzero(active)[0]:
            item = (int(outs_added[simulation]), int(base_after[simulation]), int(runs[simulation]))
            if not bt.is_legal(int(outs[simulation]), int(base[simulation]), item):
                illegal += 1
        outs_after = outs+outs_added
        for simulation in range(trace_count):
            if not active[simulation]:
                continue
            traces[simulation].append({"pa": step+1, "inning": int(inning[simulation]),
                "half": "TOP" if top[simulation] else "BOTTOM",
                "battingOrderPosition": int(batting_pa[simulation] % 9+1),
                "pitcherState": "TEAM_BULLPEN" if bullpen[simulation] else "STARTER",
                "pitchingChange": bool(change[simulation]), "outcome": PA_CLASS_ORDER[int(outcome_index[simulation])],
                "outsBefore": int(outs[simulation]), "outsAfter": int(outs_after[simulation]),
                "baseMaskBefore": int(base[simulation]), "baseMaskAfter": int(base_after[simulation]),
                "runsScored": int(runs[simulation]),
                "awayScoreAfter": int(away_score[simulation]+(runs[simulation] if top[simulation] else 0)),
                "homeScoreAfter": int(home_score[simulation]+(runs[simulation] if not top[simulation] else 0))})
        away_score += np.where(active & top, runs, 0)
        home_score += np.where(active & ~top, runs, 0)
        starter_run_credit = active & ~bullpen
        home_starter_runs += np.where(starter_run_credit & top, runs, 0)
        away_starter_runs += np.where(starter_run_credit & ~top, runs, 0)
        home_bf += (active & top & ~bullpen).astype(np.int64)
        away_bf += (active & ~top & ~bullpen).astype(np.int64)
        home_starter_outs += np.where(active & top & ~bullpen, outs_added, 0)
        away_starter_outs += np.where(active & ~top & ~bullpen, outs_added, 0)
        home_relief_outs += np.where(active & top & bullpen, outs_added, 0)
        away_relief_outs += np.where(active & ~top & bullpen, outs_added, 0)
        away_pa += (active & top).astype(np.int64)
        home_pa += (active & ~top).astype(np.int64)
        pa_count += active.astype(np.int64)
        walkoff = active & ~top & (inning >= regulation) & (home_score > away_score)
        ends = active & ~walkoff & (outs_after >= 3)
        cont = active & ~walkoff & (outs_after < 3)
        base, outs = np.where(cont, base_after, base), np.where(cont, outs_after, outs)
        end_bottom = ends & ~top & (inning >= regulation) & (away_score != home_score)
        end_top = ends & top & (inning >= regulation) & (home_score > away_score)
        become_terminal = walkoff | end_bottom | end_top
        switch = ends & ~become_terminal
        was_top, was_bottom = switch & top, switch & ~top
        inning = np.where(was_bottom, inning+1, inning)
        top = np.where(was_top, False, top)
        top = np.where(was_bottom, True, top)
        outs, base = np.where(switch, 0, outs), np.where(switch, 0, base)
        base = np.where(switch & (inning > regulation), 2, base)
        terminal |= become_terminal

    _deadline(deadline_utc)
    if illegal or (~terminal).any():
        raise PairedSimulationError(f"INCOMPLETE_OR_ILLEGAL_POPULATION:illegal={illegal};unfinished={int((~terminal).sum())}")
    total, margin = away_score+home_score, home_score-away_score
    joint = Counter(zip(map(int, away_score), map(int, home_score)))
    result = {"schemaVersion": SCHEMA, "arm": arm, "gameId": game_id, "simulationCount": n_sims,
        "masterSeed": master_seed, "homeWinProbability": float((home_score > away_score).mean()),
        "awayWinProbability": float((away_score > home_score).mean()), "tieProbability": float((home_score == away_score).mean()),
        "meanAwayRuns": float(away_score.mean()), "meanHomeRuns": float(home_score.mean()),
        "meanTotalRuns": float(total.mean()), "meanRunDifferential": float(margin.mean()),
        "oneRunRate": float((np.abs(margin) == 1).mean()), "extraInningRate": float((inning > regulation).mean()),
        "pitchingChangeRateAway": float((~away_starter_active).mean()),
        "pitchingChangeRateHome": float((~home_starter_active).mean()),
        "nonterminationCount": 0, "illegalStateCount": 0, "bfZeroHookCount": 0,
        "awayRuns": away_score, "homeRuns": home_score, "innings": inning, "paCounts": pa_count,
        "awayStarterBf": away_bf, "homeStarterBf": home_bf,
        "awayStarterOuts": away_starter_outs, "homeStarterOuts": home_starter_outs,
        "awayRelieverBf": home_pa-away_bf, "homeRelieverBf": away_pa-home_bf,
        "awayRelieverOuts": away_relief_outs, "homeRelieverOuts": home_relief_outs,
        "awayStarterRemoved": ~away_starter_active, "homeStarterRemoved": ~home_starter_active,
        "jointScores": [{"awayRuns": a, "homeRuns": h, "count": count, "probability": count/n_sims}
                        for (a, h), count in sorted(joint.items())],
        "marginDistribution": _distribution(margin), "totalDistribution": _distribution(total),
        "traces": traces}
    result["starterDuration"] = {side: {"bf": _summary(result[side+"StarterBf"]),
        "pitchingOuts": _summary(result[side+"StarterOuts"]),
        "relieverBf": _summary(result[side+"RelieverBf"]),
        "relieverPitchingOuts": _summary(result[side+"RelieverOuts"]),
        "removedBeforeFinalGameEndProbability": float(result[side+"StarterRemoved"].mean())}
        for side in ("home", "away")}
    return result


def simulate_paired_game(*, game_id: str, provider: Any, transition_model: bt.TransitionModel,
        duration_model: Any, home_duration_inputs: Mapping, away_duration_inputs: Mapping,
        n_sims: int, master_seed: int, regulation: int = 9, trace_count: int = 1, deadline_utc=None) -> dict:
    _deadline(deadline_utc)
    mechanics = verify_frozen_mechanics()
    lookup, inference = _duration_lookup(duration_model, home_duration_inputs, away_duration_inputs)
    args = dict(game_id=game_id, provider=provider, transition_model=transition_model,
        n_sims=n_sims, master_seed=master_seed, regulation=regulation, trace_count=trace_count,
        deadline_utc=deadline_utc)
    reference = simulate_research_arm(**args, arm=REFERENCE)
    challenger = simulate_research_arm(**args, arm=CHALLENGER, duration_lookup=lookup)
    deltas = {}
    for label, r, c in (
        ("homeWinProbability", reference["homeRuns"] > reference["awayRuns"], challenger["homeRuns"] > challenger["awayRuns"]),
        ("homeRuns", reference["homeRuns"], challenger["homeRuns"]),
        ("awayRuns", reference["awayRuns"], challenger["awayRuns"]),
        ("homeMargin", reference["homeRuns"]-reference["awayRuns"], challenger["homeRuns"]-challenger["awayRuns"]),
        ("totalRuns", reference["homeRuns"]+reference["awayRuns"], challenger["homeRuns"]+challenger["awayRuns"])):
        difference = c.astype(float)-r.astype(float)
        deltas[label] = {"challengerMinusReference": float(difference.mean()),
            "pairedMonteCarloStandardError": float(difference.std(ddof=1)/np.sqrt(n_sims)) if n_sims > 1 else None}
    _deadline(deadline_utc)
    return {"schemaVersion": SCHEMA, "gameId": game_id, "reference": reference, "challenger": challenger,
        "pairedDifferences": deltas, "durationInference": inference, "frozenMechanics": mechanics,
        "rng": {"masterSeed": master_seed, "streams": ["PA", "TRANSITION", "HOOK"],
            "sameEntropyAndStreamAssignmentBothArms": True,
            "drawIndex": "Fixed n_sims-sized vectors by global simulated PA step; inactive rows consume matching draws",
            "scope": "Paired Monte Carlo noise, not across-game predictive uncertainty"},
        "limitation": "Anonymous frozen team-staff mixture is shared, not individual reliever availability; no mid-PA replacement model. BF-zero starts remain for their first PA without extrapolated hook.",
        "authority": {"researchOnly": True, "promoted": False, "wageringAuthority": False,
            "executionAllowedInAISP": False, "fits": 0, "providerCalls": 0}}
