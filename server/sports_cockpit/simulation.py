"""Bounded whole-game run Monte Carlo for cockpit simulation impact.

This reuses the governed Phase 5B base-out transition authority. For a bounded sample of
real games it draws, per plate appearance, an outcome class from the candidate model's PA
probability vector, then draws the runs scored from the empirical base-out transition
distribution at that plate appearance's real (outs, base) state, splitting runs by batting
side to produce a home/away score distribution. Champion and challenger are simulated under
the identical kernel, transition authority, game sample, and RNG lineage so the only thing
that varies is the PA model — isolating its whole-game value.

Scope (honest): this is the QUICK actual-sequence variant — it samples outcomes at each
game's real base-out states rather than evolving fully sampled lineups. The full lineup-
rotation whole-game simulator remains the Phase 5 research pipeline
(``scripts/run_mlb_whole_game_monte_carlo.py``); this cockpit mode is a bounded, reproducible
impact probe, not a replacement for it. No betting/odds/sportsbook logic is produced.
"""

from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from server.sports_modeling.metrics import PA_CLASS_ORDER, evaluate_multiclass
from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5 import whole_game_monte_carlo as mc
from server.sports_phase5.game_initialization import RngLineage

from . import engine as E
from . import modeling as M
from . import provider as PROV
from . import game_preps as GP
from .engine import COCKPIT_ROOT, COCKPIT_SCHEMA_VERSION, CockpitError, load_frame

MASTER_SEED = 20260819

_TRANSITION_CACHE: dict[str, Any] = {}
_ACTUALS_CACHE: dict[str, Any] = {}

MANIFEST = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
PLAY_TRANSITION_GLOB = (
    f"C:/Users/james/asp-model-exchange/datasets/mlb-fd1/sha256-{MANIFEST}/parquet/play_transition/**/*.parquet"
)


# ----------------------------------------------------------------------------------------
# Transition authority → per-cell run samplers
# ----------------------------------------------------------------------------------------
def _load_transition_samplers() -> dict[str, Any]:
    if "samplers" in _TRANSITION_CACHE:
        return _TRANSITION_CACHE["samplers"]
    files = sorted(glob.glob(str(E.RUNTIME_ROOT / "sports-phase5" / "base-out-transition" / "*model-sha256-*.json")))
    if not files:
        raise CockpitError("base-out transition model artifact not found")
    # Prefer the model referenced by latest.transition.json when present.
    preferred = None
    latest = E.RUNTIME_ROOT / "sports-phase5" / "base-out-transition" / "latest.transition.json"
    if latest.is_file():
        try:
            sha = json.loads(latest.read_text(encoding="utf-8")).get("transitionSha")
            for f in files:
                if hashlib.sha256(Path(f).read_bytes()).hexdigest() == sha:
                    preferred = f
                    break
        except Exception:
            preferred = None
    model_path = Path(preferred or files[0])
    payload = json.loads(model_path.read_text(encoding="utf-8"))
    model = bt.TransitionModel.from_dict(payload)
    # Per cell = outcome_idx(8) * 24 + outs(3) * 8 + base(8): store (run_values, cum_probs)
    run_values: dict[int, np.ndarray] = {}
    cum_probs: dict[int, np.ndarray] = {}
    expected = np.zeros((8, 3, 8), dtype=np.float64)
    for oi, outcome in enumerate(PA_CLASS_ORDER):
        for outs in range(3):
            for base in range(8):
                dist = model.distribution(outcome, outs, base)
                ts = dist["transitions"]
                runs = np.array([t["runs"] for t in ts], dtype=np.int64)
                probs = np.array([t["probability"] for t in ts], dtype=np.float64)
                # collapse to run-value marginal
                uniq = np.unique(runs)
                marg = np.array([probs[runs == r].sum() for r in uniq], dtype=np.float64)
                marg = marg / marg.sum()
                cell = oi * 24 + outs * 8 + base
                run_values[cell] = uniq
                cum_probs[cell] = np.cumsum(marg)
                expected[oi, outs, base] = float((uniq * marg).sum())
    samplers = {
        "runValues": run_values,
        "cumProbs": cum_probs,
        "expected": expected,
        "modelSha": hashlib.sha256(model_path.read_bytes()).hexdigest(),
    }
    _TRANSITION_CACHE["samplers"] = samplers
    return samplers


# ----------------------------------------------------------------------------------------
# Actual per-game outcomes (from governed play_transition, cached)
# ----------------------------------------------------------------------------------------
def _load_actuals() -> dict[str, Any]:
    if "actuals" in _ACTUALS_CACHE:
        return _ACTUALS_CACHE["actuals"]
    cache_path = COCKPIT_ROOT / "sim" / "game-actuals.json"
    if cache_path.is_file():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        _ACTUALS_CACHE["actuals"] = payload
        return payload
    import pyarrow.parquet as pq

    files = sorted(glob.glob(PLAY_TRANSITION_GLOB, recursive=True))
    if not files:
        raise CockpitError("governed play_transition dataset is not available")
    cols = [
        "game_id", "season", "top_bottom", "batting_team_id", "home_team_id",
        "visiting_score_after", "home_score_after",
    ]
    frames = [pq.read_table(f, columns=cols).to_pandas() for f in files]
    pt = pd.concat(frames, ignore_index=True)
    # Determine which top_bottom value corresponds to the home team batting.
    home_bat = pt[pt["batting_team_id"] == pt["home_team_id"]]
    home_tb = int(home_bat["top_bottom"].mode().iloc[0]) if len(home_bat) else 1
    # Final scores per game = max score_after.
    grp = pt.groupby("game_id").agg(
        season=("season", "first"),
        homeRuns=("home_score_after", "max"),
        awayRuns=("visiting_score_after", "max"),
    ).reset_index()
    games = {}
    for _, r in grp.iterrows():
        hr, ar = int(r["homeRuns"]), int(r["awayRuns"])
        games[str(r["game_id"])] = {
            "season": int(r["season"]),
            "homeRuns": hr,
            "awayRuns": ar,
            "totalRuns": hr + ar,
            "homeWin": 1 if hr > ar else 0,
        }
    payload = {"homeTopBottom": home_tb, "games": games}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    _ACTUALS_CACHE["actuals"] = payload
    return payload


# ----------------------------------------------------------------------------------------
# Per-game Monte Carlo (vectorized over sims)
# ----------------------------------------------------------------------------------------
def _simulate_game_runs(
    probs: np.ndarray,          # (K, 8) PA outcome probabilities
    outs: np.ndarray,           # (K,) outs_before 0-2
    base: np.ndarray,           # (K,) base_mask_before 0-7
    is_home: np.ndarray,        # (K,) bool — home team batting
    samplers: Mapping[str, Any],
    n_sims: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (home_runs[n_sims], away_runs[n_sims]) simulated totals for one game."""
    K = probs.shape[0]
    cumprob = np.cumsum(probs, axis=1)  # (K,8)
    # Sample outcomes for all PAs and sims: (K, n_sims)
    u = rng.random((K, n_sims))
    outcomes = (u[:, :, None] > cumprob[:, None, :]).sum(axis=2)  # inverse CDF -> 0..7
    np.clip(outcomes, 0, 7, out=outcomes)
    cell_base = (outs * 8 + base).astype(np.int64)  # (K,)
    home_runs = np.zeros(n_sims, dtype=np.float64)
    away_runs = np.zeros(n_sims, dtype=np.float64)
    run_values = samplers["runValues"]
    cum_probs = samplers["cumProbs"]
    for k in range(K):
        cells = outcomes[k] * 24 + cell_base[k]  # (n_sims,)
        runs_k = np.empty(n_sims, dtype=np.float64)
        # group by unique cell to sample runs vectorized
        for cell in np.unique(cells):
            m = cells == cell
            cp = cum_probs[int(cell)]
            rv = run_values[int(cell)]
            idx = np.searchsorted(cp, rng.random(int(m.sum())), side="right")
            np.clip(idx, 0, len(rv) - 1, out=idx)
            runs_k[m] = rv[idx]
        if is_home[k]:
            home_runs += runs_k
        else:
            away_runs += runs_k
    return home_runs, away_runs


def _crps(samples: np.ndarray, actual: float) -> float:
    """CRPS via the empirical-sample estimator E|X-y| - 0.5 E|X-X'|."""
    s = np.sort(samples)
    n = len(s)
    term1 = np.mean(np.abs(s - actual))
    # E|X-X'| via sorted-sample formula
    i = np.arange(1, n + 1)
    term2 = (2.0 / (n * n)) * np.sum((2 * i - n - 1) * s)
    return float(term1 - 0.5 * term2)


def _model_probs_on_rows(config: Mapping[str, Any], rows_mask: np.ndarray, family_override: str | None = None) -> np.ndarray:
    """Fit the given config on 2023 and predict PA probabilities for the masked rows.

    Supports engineered features via the working frame."""
    frame, _ = M.working_frame(config)
    features = list(config.get("features") or E.ALL_FEATURES)
    family = family_override or config.get("family", "logistic")
    hyper = dict(config.get("hyperparameters") or {})
    outlier_policy = config.get("outlierPolicy") or {"globalMethod": "none"}
    missing_policy = config.get("missingPolicy") or {"globalMethod": "median"}
    pre = M.Preprocessor.fit(frame, features, outlier_policy, missing_policy)
    dev_mask = frame["season"].to_numpy() == E.DEV_SEASON
    from server.sports_modeling.metrics import encode_labels

    X_dev = pre.transform(frame, dev_mask)
    y_dev = encode_labels(frame.loc[dev_mask, "outcome"].to_numpy())
    est = M._build_estimator(family, hyper)
    est.fit(X_dev, y_dev)
    X = pre.transform(frame, rows_mask)
    return M._predict_proba_aligned(est, X)


def simulate_impact(
    config: Mapping[str, Any],
    *,
    season: int = E.VAL_SEASON,
    n_games: int = 60,
    n_sims: int = 200,
    seed: int = 20260819,
) -> dict[str, Any]:
    """Bounded whole-game run Monte Carlo comparing the challenger to the D3 champion."""
    if season not in (E.VAL_SEASON, E.FROZEN_SEASON):
        raise CockpitError("simulation season must be validation (2024) or frozen (2025)")
    n_games = int(max(5, min(n_games, 200)))
    n_sims = int(max(50, min(n_sims, 500)))
    samplers = _load_transition_samplers()
    actuals = _load_actuals()
    home_tb = actuals["homeTopBottom"]

    frame = load_frame()
    season_mask = frame["season"].to_numpy() == season
    game_ids = frame.loc[season_mask, "game_id"].to_numpy()
    known = set(actuals["games"].keys())
    unique_games = [g for g in pd.unique(game_ids) if str(g) in known]
    if not unique_games:
        raise CockpitError("no sampled games have known actual scores")
    rng = np.random.default_rng(seed)
    chosen = sorted(unique_games)
    if len(chosen) > n_games:
        idx = rng.choice(len(chosen), n_games, replace=False)
        chosen = [chosen[i] for i in sorted(idx)]
    chosen_set = set(chosen)
    rows_mask = season_mask & frame["game_id"].isin(chosen_set).to_numpy()

    # Champion (reproduced logistic C4) and challenger probabilities on the sampled rows.
    champ_config = {"features": list(E.ALL_FEATURES), "family": "logistic", "hyperparameters": {"C": M.champion_baseline().get("C", 0.05)}, "outlierPolicy": {"globalMethod": "none"}, "missingPolicy": {"globalMethod": "mean"}}
    champ_probs = _model_probs_on_rows(champ_config, rows_mask)
    chal_probs = _model_probs_on_rows(config, rows_mask)

    sub = frame.loc[rows_mask, ["game_id", "outcome", "context_outs_before", "context_base_mask_before", "context_top_bottom"]].reset_index(drop=True)
    outs_all = sub["context_outs_before"].to_numpy().astype(np.int64)
    base_all = sub["context_base_mask_before"].to_numpy().astype(np.int64)
    is_home_all = (sub["context_top_bottom"].to_numpy().astype(int) == home_tb)
    game_col = sub["game_id"].to_numpy()

    def _evaluate(probs: np.ndarray, label: str) -> dict[str, Any]:
        rng_local = np.random.default_rng(seed)  # identical RNG lineage per model
        tot_bias = []
        tot_abs = []
        crps_list = []
        hw_actual = []
        hw_prob = []
        diff_err = []
        covered = 0
        for g in chosen:
            gmask = game_col == g
            if not gmask.any():
                continue
            p = probs[gmask]
            hr, ar = _simulate_game_runs(
                p, outs_all[gmask], base_all[gmask], is_home_all[gmask], samplers, n_sims, rng_local
            )
            total = hr + ar
            act = actuals["games"][str(g)]
            actual_total = act["totalRuns"]
            tot_bias.append(float(total.mean() - actual_total))
            tot_abs.append(abs(float(total.mean() - actual_total)))
            crps_list.append(_crps(total, actual_total))
            hw_actual.append(act["homeWin"])
            hw_prob.append(float((hr > ar).mean()))
            diff_err.append(abs(float((hr - ar).mean() - (act["homeRuns"] - act["awayRuns"]))))
            lo, hi = np.percentile(total, [5, 95])
            covered += int(lo <= actual_total <= hi)
        hw_actual = np.array(hw_actual, dtype=np.float64)
        hw_prob = np.array(hw_prob, dtype=np.float64)
        # PA-level metrics on the sample (real, exact)
        pa_eval = evaluate_multiclass(sub["outcome"].to_numpy(), probs)
        return {
            "label": label,
            "games": len(chosen),
            "paLogLoss": pa_eval["logLoss"],
            "paBrier": pa_eval["brierScore"],
            "totalRunBias": float(np.mean(tot_bias)),
            "totalRunMae": float(np.mean(tot_abs)),
            "totalRunCrps": float(np.mean(crps_list)),
            "runDiffMae": float(np.mean(diff_err)),
            "homeWinBrier": float(np.mean((hw_prob - hw_actual) ** 2)),
            "homeWinLogLoss": float(np.mean(-(hw_actual * np.log(np.clip(hw_prob, 1e-6, 1)) + (1 - hw_actual) * np.log(np.clip(1 - hw_prob, 1e-6, 1))))),
            "intervalCoverage90": float(covered / len(chosen)),
        }

    champ_eval = _evaluate(champ_probs, "CHAMPION (D3 C4)")
    chal_eval = _evaluate(chal_probs, "CHALLENGER")

    # Verdict framework
    pa_better = chal_eval["paLogLoss"] < champ_eval["paLogLoss"] - 1e-6
    game_better = (chal_eval["totalRunCrps"] < champ_eval["totalRunCrps"] - 1e-4) and (
        chal_eval["homeWinBrier"] <= champ_eval["homeWinBrier"] + 1e-6
    )
    game_worse = chal_eval["totalRunCrps"] > champ_eval["totalRunCrps"] + 1e-3
    if game_better:
        verdict = "GAME_LEVEL_IMPROVEMENT"
    elif game_worse:
        verdict = "GAME_LEVEL_DEGRADATION"
    elif pa_better:
        verdict = "PA_ONLY_IMPROVEMENT"
    else:
        verdict = "NO_MATERIAL_CHANGE"

    return {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "mode": "QUICK_ACTUAL_SEQUENCE_MARGINAL_STATE",
        "season": season,
        "games": len(chosen),
        "simsPerGame": n_sims,
        "transitionAuthority": samplers["modelSha"],
        "kernel": "PHASE_5B_BASE_OUT_TRANSITION",
        "champion": champ_eval,
        "challenger": chal_eval,
        "deltas": {
            "paLogLoss": chal_eval["paLogLoss"] - champ_eval["paLogLoss"],
            "totalRunCrps": chal_eval["totalRunCrps"] - champ_eval["totalRunCrps"],
            "homeWinBrier": chal_eval["homeWinBrier"] - champ_eval["homeWinBrier"],
            "totalRunBias": chal_eval["totalRunBias"] - champ_eval["totalRunBias"],
        },
        "verdict": verdict,
        "notes": [
            "Bounded QUICK mode: outcomes sampled at each game's real base-out states via the Phase 5B transition authority.",
            "Champion and challenger share the identical game sample, transition kernel, sim count, and RNG lineage.",
            "Full lineup-rotation whole-game Monte Carlo is available via mode=FULL for simulator-eligible logistic models.",
        ],
    }


# ----------------------------------------------------------------------------------------
# FULL lineup-rotation whole-game simulation (generic-provider path, Phase 5 kernel)
# ----------------------------------------------------------------------------------------
def _load_transition_model() -> bt.TransitionModel:
    if "model" in _TRANSITION_CACHE:
        return _TRANSITION_CACHE["model"]
    files = sorted(glob.glob(str(E.RUNTIME_ROOT / "sports-phase5" / "base-out-transition" / "*model-sha256-*.json")))
    if not files:
        raise CockpitError("base-out transition model artifact not found")
    preferred = None
    latest = E.RUNTIME_ROOT / "sports-phase5" / "base-out-transition" / "latest.transition.json"
    if latest.is_file():
        try:
            sha = json.loads(latest.read_text(encoding="utf-8")).get("transitionSha")
            for f in files:
                if hashlib.sha256(Path(f).read_bytes()).hexdigest() == sha:
                    preferred = f
                    break
        except Exception:
            preferred = None
    model = bt.TransitionModel.from_dict(json.loads(Path(preferred or files[0]).read_text(encoding="utf-8")))
    _TRANSITION_CACHE["model"] = model
    return model


def _coverage(samples: np.ndarray, actual: float, bands=((5, 95, "90"), (10, 90, "80"), (25, 75, "50"), (2.5, 97.5, "95"))) -> dict[str, int]:
    hits = {}
    for lo, hi, name in bands:
        lo_v, hi_v = np.percentile(samples, [lo, hi])
        hits[name] = int(lo_v <= actual <= hi_v)
    return hits


def simulate_full_impact(config: Mapping[str, Any], *, season: int = E.VAL_SEASON, n_games: int = 40, n_sims: int = 120, seed: int = MASTER_SEED) -> dict[str, Any]:
    """Full lineup-rotation whole-game Monte Carlo: champion vs challenger through the Phase 5 kernel."""
    if season not in (E.VAL_SEASON, E.FROZEN_SEASON):
        raise CockpitError("simulation season must be validation (2024) or frozen (2025)")
    elig = PROV.simulator_eligibility(config)
    if not elig["eligible"]:
        raise CockpitError("model is not full-simulator-eligible: " + "; ".join(elig["reasons"]))
    n_games = int(max(5, min(n_games, 160)))
    n_sims = int(max(50, min(n_sims, 400)))

    # champion config: reproduced D3 C4 (all 22 features, tuned C, mean impute)
    champ_config = {"features": list(E.ALL_FEATURES), "family": "logistic",
                    "hyperparameters": {"C": M.champion_baseline().get("C", 0.05)},
                    "outlierPolicy": {"globalMethod": "none"}, "missingPolicy": {"globalMethod": "mean"}}
    champ_fold, champ_resolver, _, _, _ = PROV.build_cockpit_fold_and_resolver(champ_config)
    chal_fold, chal_resolver, _, chal_est, chal_pre = PROV.build_cockpit_fold_and_resolver(config)
    tsampler = mc.FastTransitionSampler(_load_transition_model())

    # pick games with resolvable participant orderings
    frame = load_frame()
    season_mask = frame["season"].to_numpy() == season
    rng = np.random.default_rng(seed)
    candidate_games = sorted(pd.unique(frame.loc[season_mask, "game_id"].to_numpy()))
    if len(candidate_games) > n_games * 3:
        idx = rng.choice(len(candidate_games), n_games * 3, replace=False)
        candidate_games = [candidate_games[i] for i in sorted(idx)]
    preps = GP.build_preps(season, candidate_games)[:n_games]
    if not preps:
        raise CockpitError("no games with resolvable participant orderings in the sample")
    chosen = [p.game_id for p in preps]

    def _run(fold, resolver, label: str) -> dict[str, Any]:
        tot_bias, tot_abs, crps_list, hw_actual, hw_prob, diff_err = [], [], [], [], [], []
        cover = {"50": 0, "80": 0, "90": 0, "95": 0}
        for prep in preps:
            contribs = mc.build_game_contribs(
                fold=fold, resolver=resolver, game_date=prep.game_date, regulation=prep.regulation,
                away_pa_uuids=prep.away_pa, home_pa_uuids=prep.home_pa,
                away_start_batter_uuids=prep.away_start, home_start_batter_uuids=prep.home_start)
            res = mc.simulate_game(game_id=prep.game_id, contribs=contribs, fold=fold, transition_sampler=tsampler,
                                   rng_lineage=RngLineage(master_seed=seed, game_key=prep.game_id), n_sims=n_sims)
            total = (res.away_runs + res.home_runs).astype(np.float64)
            actual_total = prep.actual_away + prep.actual_home
            tot_bias.append(float(total.mean() - actual_total)); tot_abs.append(abs(float(total.mean() - actual_total)))
            crps_list.append(_crps(total, actual_total))
            hw_actual.append(1 if prep.actual_home > prep.actual_away else 0)
            hw_prob.append(float(res.home_win.mean()))
            diff_err.append(abs(float((res.home_runs - res.away_runs).mean() - (prep.actual_home - prep.actual_away))))
            for k, v in _coverage(total, actual_total).items():
                cover[k] += v
        hw_actual = np.array(hw_actual, dtype=np.float64); hw_prob = np.array(hw_prob, dtype=np.float64)
        n = len(preps)
        return {
            "label": label, "games": n,
            "totalRunBias": float(np.mean(tot_bias)), "totalRunMae": float(np.mean(tot_abs)),
            "totalRunCrps": float(np.mean(crps_list)), "runDiffMae": float(np.mean(diff_err)),
            "homeWinBrier": float(np.mean((hw_prob - hw_actual) ** 2)),
            "homeWinLogLoss": float(np.mean(-(hw_actual * np.log(np.clip(hw_prob, 1e-6, 1)) + (1 - hw_actual) * np.log(np.clip(1 - hw_prob, 1e-6, 1))))),
            "coverage50": cover["50"] / n, "coverage80": cover["80"] / n, "coverage90": cover["90"] / n, "coverage95": cover["95"] / n,
        }

    champ_eval = _run(champ_fold, champ_resolver, "CHAMPION (D3 C4)")
    chal_eval = _run(chal_fold, chal_resolver, "CHALLENGER")

    # PA-level metrics on the sampled games (exact, from the models directly)
    rows_mask = season_mask & frame["game_id"].isin(set(chosen)).to_numpy()
    labels = frame.loc[rows_mask, "outcome"].to_numpy()
    champ_pa = evaluate_multiclass(labels, _probs_via_model(champ_config, rows_mask))
    chal_pa = evaluate_multiclass(labels, _probs_via_model(config, rows_mask))
    champ_eval["paLogLoss"], champ_eval["paBrier"] = champ_pa["logLoss"], champ_pa["brierScore"]
    chal_eval["paLogLoss"], chal_eval["paBrier"] = chal_pa["logLoss"], chal_pa["brierScore"]

    pa_better = chal_eval["paLogLoss"] < champ_eval["paLogLoss"] - 1e-6
    game_better = (chal_eval["totalRunCrps"] < champ_eval["totalRunCrps"] - 1e-4) and (chal_eval["homeWinBrier"] <= champ_eval["homeWinBrier"] + 1e-6)
    game_worse = chal_eval["totalRunCrps"] > champ_eval["totalRunCrps"] + 1e-3
    verdict = "GAME_LEVEL_IMPROVEMENT" if game_better else "GAME_LEVEL_DEGRADATION" if game_worse else "PA_ONLY_IMPROVEMENT" if pa_better else "NO_MATERIAL_CHANGE"

    return {
        "schemaVersion": COCKPIT_SCHEMA_VERSION, "mode": "FULL_LINEUP_ROTATION",
        "provider": PROV.PROBABILISTIC_PA_PROVIDER_V1, "season": season, "games": len(preps), "simsPerGame": n_sims,
        "kernel": "PHASE_5_WHOLE_GAME_MONTE_CARLO", "eligibility": elig,
        "champion": champ_eval, "challenger": chal_eval,
        "deltas": {"paLogLoss": chal_eval["paLogLoss"] - champ_eval["paLogLoss"],
                   "totalRunCrps": chal_eval["totalRunCrps"] - champ_eval["totalRunCrps"],
                   "homeWinBrier": chal_eval["homeWinBrier"] - champ_eval["homeWinBrier"]},
        "verdict": verdict,
        "notes": [
            "FULL lineup-rotation whole-game Monte Carlo through the unchanged Phase 5 kernel.",
            "Champion and challenger share the identical games, participant orderings, transition kernel, RNG lineage, and sim count; only the PA provider differs.",
            "PA provider decomposed from the cockpit logistic model (reproduces predict_proba to floating tolerance).",
        ],
    }


def _probs_via_model(config: Mapping[str, Any], rows_mask: np.ndarray) -> np.ndarray:
    est, pre = M.fit_cockpit_model(config)
    frame = load_frame()
    X = pre.transform(frame, rows_mask)
    return M._predict_proba_aligned(est, X)
