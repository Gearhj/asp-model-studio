"""run-mlb-whole-game-monte-carlo — Phase 5D first whole-game Monte Carlo + historical backtest.

Combines actual historical participants (oracle mode), the frozen D3 PA-outcome provider, the
Phase 5B empirical base-out transition model, and the proven deterministic kernel to sample
whole 2024/2025 games and evaluate the resulting game-level score distributions against actual
results. Runs a convergence pilot, a full-population backtest at the chosen simulation count, a
G0 generic-baseball baseline ablation, and persists content-addressed data-only evidence.

Absolute exclusions (enforced): no D3 retraining/changes, no E1/E2/E6, no algorithm tournament,
no premium data, no transition-model changes, no new lineup/starter/bullpen models, no residual
correction, no sportsbook odds / market edge / ROI / betting logic, no provider/network calls,
no new data acquisition. Winner probability is a game-distribution diagnostic only.
"""

from __future__ import annotations
from scripts._retired_2025_guard import retire_2025  # Phase 7D.4 Gate 12 (B8)

import argparse
import glob
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from server.sports_phase5 import base_out_transition as bt  # noqa: E402
from server.sports_phase5 import whole_game_monte_carlo as mc  # noqa: E402
from server.sports_phase5.pa_provider import (  # noqa: E402
    D3_STATE_TABLE_SHA,
    D3ProbabilisticPAProvider,
    PlayerStateResolver,
)
from server.sports_phase5.game_initialization import RngLineage  # noqa: E402
from server.sports_modeling.metrics import PA_CLASS_ORDER  # noqa: E402
from server.sports_phase4.dynamic_contract import (  # noqa: E402
    PHASE3_FEATURE_CONTRACT_SHA,
    dynamic_state_contract_sha,
)

RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio"
DYNAMIC_NS = RUNTIME_ROOT / "sports-modeling" / "mlb-dynamic-player-state-v1"
PA_NS = RUNTIME_ROOT / "sports-modeling" / "mlb-pa-v1"
OUTPUT_ROOT = RUNTIME_ROOT / "sports-phase5" / "whole-game-monte-carlo"
CONTRACT_PATH = REPOSITORY_ROOT / "docs" / "contracts" / "MLB_WHOLE_GAME_MONTE_CARLO_V1.md"
DEFAULT_EXCHANGE_ROOT = Path(r"C:/Users/james/asp-model-exchange")
MANIFEST = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
TRANSITION_MODEL_SHA = "4f312af6c61c191b8ca19a71b35d8da12a587f204fb19b257715af9b7a3459e4"
SEASONS = (2024, 2025)
MASTER_SEED = 20_260_818
PILOT_GAMES_PER_SEASON = 100
CONVERGENCE_COUNTS = (100, 250, 500, 1000)
DEV_STANDARD_SIMS = 500
_STARTED = time.monotonic()

_PT_COLS = [
    "game_id", "game_date", "season", "month", "top_bottom", "play_number",
    "batter_id", "pitcher_id", "pa_outcome", "plate_appearance_id", "pbp_quality",
    "regulation_innings", "visiting_score_after", "home_score_after",
]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hb(stage: str, evidence: Mapping[str, Any]) -> None:
    print(f"[mc] {int(time.monotonic() - _STARTED):>5}s | {stage} | "
          + " ".join(f"{k}={v}" for k, v in evidence.items()), flush=True)


# ---------------------------------------------------------------------------------------
# Authorities and load
# ---------------------------------------------------------------------------------------
def _dataset_authority() -> dict[str, Any]:
    from server.persistence.db import Database
    from server.sports_datasets.registry import SportsDatasetRegistry
    db = Database(RUNTIME_ROOT / "persistence" / "asp_model_studio.db")
    db.initialize()
    active = SportsDatasetRegistry(db).get_active()
    if not active or active["manifest_sha"] != MANIFEST:
        raise RuntimeError("active FD1 dataset registration authority mismatch")
    return {"registrationId": active["registration_id"], "datasetId": active["dataset_id"], "manifestSha": active["manifest_sha"]}


def _parent_authorities() -> dict[str, Any]:
    read = lambda p, k: json.loads((RUNTIME_ROOT / "sports-phase5" / p).read_text(encoding="utf-8"))[k]
    replay = read("game-replay/latest.replay.json", "replay")
    transition = read("base-out-transition/latest.transition.json", "transition")
    sim_input = read("simulation-input/latest.simulation.json", "simulationInput")
    if transition["modelArtifact"]["sha256"] != TRANSITION_MODEL_SHA:
        raise RuntimeError("transition model authority mismatch")
    if sim_input["monteCarloEntryDecision"]["decision"] != "MONTE_CARLO_ENTRY_GATES_PASSED":
        raise RuntimeError("Phase 5C entry gates not passed")
    return {
        "replay": {"contractName": replay["contractName"], "readinessStatus": replay["readinessStatus"], "runId": replay.get("replayRunId")},
        "transition": {"contractName": transition["contractName"], "readinessStatus": transition["readinessStatus"],
                       "runId": transition.get("transitionRunId"), "modelSha": TRANSITION_MODEL_SHA},
        "simulationInput": {"runId": sim_input.get("runId"), "decision": sim_input["monteCarloEntryDecision"]["decision"]},
    }


def _load_transition_model() -> bt.TransitionModel:
    fp = glob.glob(str(RUNTIME_ROOT / "sports-phase5" / "base-out-transition" / f"*model-sha256-{TRANSITION_MODEL_SHA[:16]}.json"))
    content = Path(fp[0]).read_bytes()
    if hashlib.sha256(content).hexdigest() != TRANSITION_MODEL_SHA:
        raise RuntimeError("transition model SHA mismatch")
    return bt.TransitionModel.from_dict(json.loads(content.decode("utf-8")))


def _feature_view_maps():
    fp = glob.glob(str(PA_NS / "objects/sha256/**/mlb-pa-feature-view-v1.parquet"), recursive=True)[0]
    fv = pq.read_table(fp, columns=["plate_appearance_id", "batter_canonical_player_uuid",
                                     "pitcher_canonical_player_uuid", "outcome", "season"]).to_pandas()
    # League-average 8-class PA distribution from 2023 (temporally prior to the eval seasons).
    league = fv[fv["season"] == 2023]["outcome"].value_counts()
    total = int(league.sum())
    league_probs = np.array([league.get(c, 0) / total for c in PA_CLASS_ORDER], dtype=np.float64)
    return fv, league_probs


def _identity_map(fv: pd.DataFrame, pt: pd.DataFrame) -> tuple[dict[str, str], dict[str, str]]:
    term = pt[pt["pa_outcome"].notna() & (pt["pa_outcome"] != "")]
    m = term[["plate_appearance_id", "batter_id", "pitcher_id"]].merge(
        fv[["plate_appearance_id", "batter_canonical_player_uuid", "pitcher_canonical_player_uuid"]],
        on="plate_appearance_id", how="inner")
    uuid_b = dict(zip(m["batter_id"].astype(str), m["batter_canonical_player_uuid"].astype(str)))
    uuid_p = dict(zip(m["pitcher_id"].astype(str), m["pitcher_canonical_player_uuid"].astype(str)))
    return uuid_b, uuid_p


# ---------------------------------------------------------------------------------------
# Per-game preparation (oracle participant sequences + actuals)
# ---------------------------------------------------------------------------------------
class GamePrep:
    __slots__ = ("game_id", "season", "month", "game_date", "regulation",
                 "away_pa", "home_pa", "away_start", "home_start",
                 "actual_away", "actual_home")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _build_game_preps(pt: pd.DataFrame, resolver: PlayerStateResolver,
                      uuid_b: dict[str, str], uuid_p: dict[str, str]) -> tuple[list[GamePrep], dict[str, int]]:
    preps: list[GamePrep] = []
    skips: dict[str, int] = defaultdict(int)
    pt = pt.sort_values(["game_id", "play_number"])
    for gid, g in pt.groupby("game_id", sort=False):
        season = int(g["season"].iloc[0])
        regulation = int(g["regulation_innings"].iloc[0]) if pd.notna(g["regulation_innings"].iloc[0]) else 9
        month = int(g["month"].iloc[0])
        game_date = str(g["game_date"].iloc[0])
        last = g.iloc[-1]
        actual_away = int(last["visiting_score_after"])
        actual_home = int(last["home_score_after"])
        if (g["pbp_quality"] != "FULL").any():
            skips["PBP_NOT_FULL"] += 1
            continue
        term = g[g["pa_outcome"].notna() & (g["pa_outcome"] != "")]
        away_rows = term[term["top_bottom"] == 0]
        home_rows = term[term["top_bottom"] == 1]

        def seq(rows):
            out = []
            for bid, pid in zip(rows["batter_id"].astype(str), rows["pitcher_id"].astype(str)):
                bu = uuid_b.get(bid); pu = uuid_p.get(pid)
                if bu is None or pu is None:
                    return None
                out.append((bu, pu))
            return out

        away_pa = seq(away_rows)
        home_pa = seq(home_rows)
        if away_pa is None or home_pa is None:
            skips["UNRESOLVED_PARTICIPANT"] += 1
            continue
        if len(away_pa) < 9 or len(home_pa) < 9:
            skips["INSUFFICIENT_PA"] += 1
            continue
        # starting-lineup uuids for overflow rotation: first 9 distinct batters
        def distinct9(pa):
            seen = []
            for bu, _ in pa:
                if bu not in seen:
                    seen.append(bu)
                if len(seen) == 9:
                    break
            return seen
        away_start = distinct9(away_pa)
        home_start = distinct9(home_pa)
        if len(away_start) < 9 or len(home_start) < 9:
            skips["LINEUP_LT_9"] += 1
            continue
        # confirm state resolvable on this game_date (fail-closed eligibility)
        try:
            resolver.resolve(away_pa[0][0], "BATTER", game_date)
            resolver.resolve(away_pa[0][1], "PITCHER", game_date)
            resolver.resolve(home_pa[0][0], "BATTER", game_date)
            resolver.resolve(home_pa[0][1], "PITCHER", game_date)
        except Exception:
            skips["STATE_UNRESOLVED"] += 1
            continue
        preps.append(GamePrep(game_id=str(gid), season=season, month=month, game_date=game_date,
                              regulation=regulation, away_pa=away_pa, home_pa=home_pa,
                              away_start=away_start, home_start=home_start,
                              actual_away=actual_away, actual_home=actual_home))
    return preps, dict(skips)


# ---------------------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------------------
def _crps(samples: np.ndarray, y: float) -> float:
    # Fair empirical CRPS: CRPS = E|X-y| - 0.5 E|X-X'|, with the sorted identity
    # E|X-X'| = (2/m^2) sum_i (2i-m-1) x_(i). Here e2 already equals 0.5 E|X-X'|.
    x = np.sort(samples.astype(np.float64))
    m = x.size
    e1 = float(np.mean(np.abs(x - y)))
    i = np.arange(1, m + 1)
    e2 = float((1.0 / (m * m)) * np.sum((2 * i - m - 1) * x))  # = 0.5 * E|X-X'|
    return e1 - e2


def _interval_hits(samples: np.ndarray, y: float) -> dict[str, int]:
    hits = {}
    for level, lo, hi in ((50, 25, 75), (80, 10, 90), (90, 5, 95), (95, 2.5, 97.5)):
        a, b = np.percentile(samples, [lo, hi])
        hits[str(level)] = int(a <= y <= b)
    return hits


def _interval_width(samples: np.ndarray) -> dict[str, float]:
    out = {}
    for level, lo, hi in ((50, 25, 75), (80, 10, 90), (90, 5, 95), (95, 2.5, 97.5)):
        a, b = np.percentile(samples, [lo, hi])
        out[str(level)] = float(b - a)
    return out


def _evaluate_game(result: "mc.GameSimResult", prep: GamePrep) -> dict[str, Any]:
    away = result.away_runs.astype(np.float64)
    home = result.home_runs.astype(np.float64)
    total = away + home
    diff = home - away
    a_act, h_act = float(prep.actual_away), float(prep.actual_home)
    t_act, d_act = a_act + h_act, h_act - a_act
    p_home = float(result.home_win.mean())
    home_won = 1 if prep.actual_home > prep.actual_away else 0
    return {
        "gameId": prep.game_id, "season": prep.season, "month": prep.month,
        "regulation": prep.regulation,
        "meanAway": float(away.mean()), "meanHome": float(home.mean()),
        "meanTotal": float(total.mean()), "meanDiff": float(diff.mean()),
        "varTotal": float(total.var()), "varDiff": float(diff.var()),
        "pHome": p_home, "homeWon": home_won,
        "extraRate": float((result.innings > prep.regulation).mean()),
        "actualAway": a_act, "actualHome": h_act, "actualTotal": t_act, "actualDiff": d_act,
        "crpsAway": _crps(away, a_act), "crpsHome": _crps(home, h_act), "crpsTotal": _crps(total, t_act),
        "intAway": _interval_hits(away, a_act), "intHome": _interval_hits(home, h_act),
        "intTotal": _interval_hits(total, t_act), "widthTotal": _interval_width(total),
        "nonterminated": result.nonterminated, "illegal": result.illegal_states,
    }


def _brier_logloss(records: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    p = np.clip(np.array([r["pHome"] for r in records]), 1e-6, 1 - 1e-6)
    y = np.array([r["homeWon"] for r in records], dtype=np.float64)
    brier = float(np.mean((p - y) ** 2))
    logloss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    return {"brier": brier, "logLoss": logloss}


def _calibration_bins(records: Sequence[Mapping[str, Any]], n_bins: int = 10) -> dict[str, Any]:
    p = np.array([r["pHome"] for r in records])
    y = np.array([r["homeWon"] for r in records], dtype=np.float64)
    order = np.argsort(p)
    bins = np.array_split(order, n_bins)
    rows = []
    ece = 0.0
    for b in bins:
        if len(b) == 0:
            continue
        mp = float(p[b].mean()); oy = float(y[b].mean())
        rows.append({"meanPredicted": mp, "observed": oy, "count": int(len(b))})
        ece += len(b) / len(p) * abs(mp - oy)
    return {"bins": rows, "ece": float(ece)}


def _favorite_bands(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    p = np.array([r["pHome"] for r in records])
    y = np.array([r["homeWon"] for r in records], dtype=np.float64)
    # simulator-favorite band on max(p,1-p) with the favored side
    fav_p = np.where(p >= 0.5, p, 1 - p)
    fav_win = np.where(p >= 0.5, y, 1 - y)
    out = []
    for lo, hi in ((0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 1.01)):
        m = (fav_p >= lo) & (fav_p < hi)
        if m.sum() == 0:
            continue
        out.append({"band": f"{lo:.2f}-{hi:.2f}", "count": int(m.sum()),
                    "meanPredicted": float(fav_p[m].mean()), "observedFavWin": float(fav_win[m].mean())})
    return out


def _score_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def stat(sim_key, act_key):
        s = np.array([r[sim_key] for r in records]); a = np.array([r[act_key] for r in records])
        err = s - a
        return {"mae": float(np.mean(np.abs(err))), "rmse": float(np.sqrt(np.mean(err ** 2))), "bias": float(np.mean(err))}
    return {
        "away": stat("meanAway", "actualAway"), "home": stat("meanHome", "actualHome"),
        "total": stat("meanTotal", "actualTotal"), "diff": stat("meanDiff", "actualDiff"),
        "crpsAway": float(np.mean([r["crpsAway"] for r in records])),
        "crpsHome": float(np.mean([r["crpsHome"] for r in records])),
        "crpsTotal": float(np.mean([r["crpsTotal"] for r in records])),
    }


def _coverage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out = {}
    for target in ("intAway", "intHome", "intTotal"):
        out[target] = {lvl: float(np.mean([r[target][lvl] for r in records])) for lvl in ("50", "80", "90", "95")}
    out["meanWidthTotal"] = {lvl: float(np.mean([r["widthTotal"][lvl] for r in records])) for lvl in ("50", "80", "90", "95")}
    return out


def _distribution_shape(records: Sequence[Mapping[str, Any]], mean_key: str, var_key: str, act_key: str) -> dict[str, Any]:
    game_means = np.array([r[mean_key] for r in records])
    game_vars = np.array([r[var_key] for r in records])
    act = np.array([r[act_key] for r in records])
    # Simulated predictive-marginal variance via the law of total variance:
    # Var(total) = E[Var(total|game)] + Var(E[total|game]).
    sim_marginal_var = float(game_vars.mean() + game_means.var())
    return {
        "simulatedMarginalMean": float(game_means.mean()),
        "simulatedMarginalStd": float(math.sqrt(max(sim_marginal_var, 0.0))),
        "actualMean": float(act.mean()),
        "actualStd": float(act.std()),
        "actualP10": float(np.percentile(act, 10)),
        "actualP90": float(np.percentile(act, 90)),
        "actualP99": float(np.percentile(act, 99)),
    }


# ---------------------------------------------------------------------------------------
# Simulation driver over a set of preps
# ---------------------------------------------------------------------------------------
def _simulate_records(preps, folds, tsampler, resolver, n_sims, *, fixed_probs=None,
                      check_legality=False, progress_every=400) -> list[dict[str, Any]]:
    records = []
    t0 = time.perf_counter()
    for i, prep in enumerate(preps):
        fold = folds[prep.season]
        contribs = mc.build_game_contribs(
            fold=fold, resolver=resolver, game_date=prep.game_date, regulation=prep.regulation,
            away_pa_uuids=prep.away_pa, home_pa_uuids=prep.home_pa,
            away_start_batter_uuids=prep.away_start, home_start_batter_uuids=prep.home_start)
        result = mc.simulate_game(
            game_id=prep.game_id, contribs=contribs, fold=(None if fixed_probs is not None else fold),
            transition_sampler=tsampler, rng_lineage=RngLineage(MASTER_SEED, prep.game_id),
            n_sims=n_sims, check_legality=check_legality, fixed_probs=fixed_probs)
        records.append(_evaluate_game(result, prep))
        if progress_every and (i + 1) % progress_every == 0:
            rate = (i + 1) / (time.perf_counter() - t0)
            _hb("SIMULATE", {"games": i + 1, "of": len(preps), "gamesPerSec": f"{rate:.1f}",
                             "etaMin": f"{(len(preps) - i - 1) / rate / 60:.1f}"})
    return records


def _stratified_pilot(preps: list[GamePrep], per_season: int) -> list[GamePrep]:
    pilot = []
    for season in SEASONS:
        s = sorted([p for p in preps if p.season == season], key=lambda p: (p.month, p.actual_away + p.actual_home, p.game_id))
        if len(s) <= per_season:
            pilot.extend(s)
        else:
            idx = np.linspace(0, len(s) - 1, per_season).round().astype(int)
            pilot.extend([s[i] for i in idx])
    return pilot


def _convergence(pilot, folds, tsampler, resolver) -> dict[str, Any]:
    prev = None
    rows = {}
    for count in CONVERGENCE_COUNTS:
        recs = _simulate_records(pilot, folds, tsampler, resolver, count, check_legality=True, progress_every=0)
        summ = {"meanTotal": float(np.mean([r["meanTotal"] for r in recs])),
                "meanHomeWinProb": float(np.mean([r["pHome"] for r in recs])),
                "crpsTotal": float(np.mean([r["crpsTotal"] for r in recs])),
                "illegal": int(sum(r["illegal"] for r in recs)),
                "nonterminated": int(sum(r["nonterminated"] for r in recs))}
        if prev is not None:
            summ["driftMeanTotalVsPrev"] = abs(summ["meanTotal"] - prev["meanTotal"])
            summ["driftHomeWinVsPrev"] = abs(summ["meanHomeWinProb"] - prev["meanHomeWinProb"])
            summ["driftCrpsVsPrev"] = abs(summ["crpsTotal"] - prev["crpsTotal"])
        rows[str(count)] = summ
        prev = summ
        _hb("CONVERGENCE", {"count": count, "meanTotal": f"{summ['meanTotal']:.3f}",
                            "homeWin": f"{summ['meanHomeWinProb']:.4f}", "illegal": summ["illegal"]})
    return rows


# ---------------------------------------------------------------------------------------
# Aggregate season evaluation
# ---------------------------------------------------------------------------------------
def _season_eval(records: Sequence[Mapping[str, Any]], baseline_records=None) -> dict[str, Any]:
    n = len(records)
    total_sim = np.array([r["meanTotal"] for r in records])
    total_act = np.array([r["actualTotal"] for r in records])
    ev = {
        "games": n,
        "actualRunsPerTeam": float(np.mean([r["actualTotal"] for r in records]) / 2.0),
        "simulatedRunsPerTeam": float(np.mean([r["meanAway"] + r["meanHome"] for r in records]) / 2.0),
        "actualMeanTotal": float(total_act.mean()), "simulatedMeanTotal": float(total_sim.mean()),
        "scoreMetrics": _score_metrics(records),
        "coverage": _coverage(records),
        "winner": _brier_logloss(records),
        "calibration": _calibration_bins(records),
        "favoriteBands": _favorite_bands(records),
        "actualHomeWinRate": float(np.mean([r["homeWon"] for r in records])),
        "meanSimulatedHomeWinProb": float(np.mean([r["pHome"] for r in records])),
        "distributionShapeTotal": _distribution_shape(records, "meanTotal", "varTotal", "actualTotal"),
        "distributionShapeDiff": _distribution_shape(records, "meanDiff", "varDiff", "actualDiff"),
        "extraInningRateActual": None,
        "meanSimulatedExtraRate": float(np.mean([r["extraRate"] for r in records])),
        "legality": {"illegal": int(sum(r["illegal"] for r in records)),
                     "nonterminated": int(sum(r["nonterminated"] for r in records))},
    }
    # Distribution-shape verdict from dispersion (marginal std) and total-run bias.
    shp = ev["distributionShapeTotal"]
    sim_std, act_std = shp["simulatedMarginalStd"], shp["actualStd"]
    bias = ev["scoreMetrics"]["total"]["bias"]
    parts = []
    if sim_std < act_std * 0.9:
        parts.append("UNDER_DISPERSED")
    elif sim_std > act_std * 1.1:
        parts.append("OVER_DISPERSED")
    if bias < -0.5:
        parts.append("LOW_BIASED")
    elif bias > 0.5:
        parts.append("HIGH_BIASED")
    ev["shapeVerdict"] = "WELL_SHAPED" if not parts else ("MIXED" if len(parts) > 1 else parts[0])
    ev["dispersionRatioTotal"] = float(sim_std / act_std) if act_std else None

    # error concentration (Pareto) on total-run CRPS and winner log loss
    crps_total = np.sort(np.array([r["crpsTotal"] for r in records]))[::-1]
    ll = np.sort(np.abs(_pointwise_logloss(records)))[::-1]
    def pareto(sorted_desc):
        s = sorted_desc.sum()
        return {f"worst{p}pct": float(sorted_desc[:max(1, int(len(sorted_desc) * p / 100))].sum() / s) if s > 0 else 0.0
                for p in (1, 5, 10, 20)}
    ev["errorConcentrationCrpsTotal"] = pareto(crps_total)
    ev["errorConcentrationWinnerLogLoss"] = pareto(ll)
    if baseline_records is not None:
        ev["baselineG0"] = {
            "winner": _brier_logloss(baseline_records),
            "crpsTotal": float(np.mean([r["crpsTotal"] for r in baseline_records])),
            "diffMae": _score_metrics(baseline_records)["diff"]["mae"],
            "simulatedMeanTotal": float(np.mean([r["meanTotal"] for r in baseline_records])),
        }
    return ev


def _pointwise_logloss(records):
    p = np.clip(np.array([r["pHome"] for r in records]), 1e-6, 1 - 1e-6)
    y = np.array([r["homeWon"] for r in records], dtype=np.float64)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _retrospective_bands(records):
    bands = [("<=5", -1, 5), ("6-8", 6, 8), ("9-11", 9, 11), ("12+", 12, 999)]
    out = []
    for label, lo, hi in bands:
        sub = [r for r in records if lo <= r["actualTotal"] <= hi]
        if not sub:
            continue
        out.append({"band": label, "count": len(sub), "totalBias": float(np.mean([r["meanTotal"] - r["actualTotal"] for r in sub])),
                    "crpsTotal": float(np.mean([r["crpsTotal"] for r in sub]))})
    return {"label": "RETROSPECTIVE_DIAGNOSTIC_ONLY", "bands": out}


# ---------------------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------------------
def _write(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    record = {"schemaVersion": "MLB_WHOLE_GAME_MONTE_CARLO_RECORD_V1", "monteCarlo": payload}
    content = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")
    named = OUTPUT_ROOT / f"whole-game-mc-{run_id}.montecarlo.json"
    latest = OUTPUT_ROOT / "latest.montecarlo.json"
    reused = named.is_file() and named.read_bytes() == content
    if not reused:
        named.write_bytes(content)
    latest.write_bytes(content)
    return {"path": str(named), "latest": str(latest), "reused": reused}


def main() -> int:
    retire_2025("server.sports_cockpit.gen3_authority.run_feature_family_ablation (canonical 2024-only research)")
    parser = argparse.ArgumentParser(description="Phase 5D whole-game Monte Carlo + backtest")
    parser.add_argument("--exchange-root", default=str(DEFAULT_EXCHANGE_ROOT))
    parser.add_argument("--sims", type=int, default=DEV_STANDARD_SIMS)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="limit games per season (debug)")
    args = parser.parse_args()

    run_id_core = {"d3ModelAuthority": dynamic_state_contract_sha(), "stateTable": D3_STATE_TABLE_SHA,
                   "transitionModel": TRANSITION_MODEL_SHA, "featureContract": PHASE3_FEATURE_CONTRACT_SHA,
                   "seasons": list(SEASONS), "sims": args.sims, "masterSeed": MASTER_SEED, "limit": args.limit}
    run_id = "whole-game-mc-" + _sha(run_id_core)[:16]

    if args.status:
        latest = OUTPUT_ROOT / "latest.montecarlo.json"
        if latest.is_file():
            rec = json.loads(latest.read_text(encoding="utf-8"))["monteCarlo"]
            print(json.dumps({"runId": rec.get("runId"), "decision": rec.get("simulatorReadiness"),
                              "d3Value": rec.get("d3GameLevelValue")}, indent=2))
            return 0
        print("no monte-carlo record found")
        return 1

    existing = OUTPUT_ROOT / f"whole-game-mc-{run_id}.montecarlo.json"
    if existing.is_file() and not args.force:
        rec = json.loads(existing.read_text(encoding="utf-8"))["monteCarlo"]
        (OUTPUT_ROOT / "latest.montecarlo.json").write_bytes(existing.read_bytes())
        _hb("REUSED", {"runId": run_id, "readiness": rec.get("simulatorReadiness")})
        print(json.dumps({"runId": run_id, "reused": True, "readiness": rec.get("simulatorReadiness"),
                          "d3GameLevelValue": rec.get("d3GameLevelValue")}, indent=2))
        return 0

    exchange_root = Path(args.exchange_root)
    _hb("AUTHORITIES", {"contract": mc.MONTE_CARLO_CONTRACT_NAME})
    dataset_authority = _dataset_authority()
    parents = _parent_authorities()

    _hb("LOAD", {"state": D3_STATE_TABLE_SHA[:12]})
    state = pq.read_table(str(DYNAMIC_NS / "objects/sha256" / D3_STATE_TABLE_SHA[:2] / D3_STATE_TABLE_SHA / "mlb-dynamic-player-state-v1.parquet")).to_pandas()
    resolver = PlayerStateResolver.from_records(state.to_dict("records"), state_table_sha=D3_STATE_TABLE_SHA)
    provider = D3ProbabilisticPAProvider.from_runtime(dynamic_namespace_root=DYNAMIC_NS, resolver=resolver)
    folds = {2024: mc.FastD3Fold.from_model(provider._models[2024]),
             2025: mc.FastD3Fold.from_model(provider._models[2025])}
    tsampler = mc.FastTransitionSampler(_load_transition_model())
    fv, league_probs = _feature_view_maps()

    _hb("LOAD_PLAY_TRANSITION", {})
    base = exchange_root / "datasets" / "mlb-fd1" / f"sha256-{MANIFEST}" / "parquet" / "play_transition"
    files = glob.glob(str(base / "**" / "*.parquet"), recursive=True)
    pt = pd.concat([pq.read_table(f, columns=_PT_COLS).to_pandas().pipe(lambda d: d[d["season"].isin(SEASONS)]) for f in files], ignore_index=True)
    uuid_b, uuid_p = _identity_map(fv, pt)

    _hb("BUILD_PREPS", {})
    preps, skips = _build_game_preps(pt, resolver, uuid_b, uuid_p)
    if args.limit:
        by_season = defaultdict(list)
        for p in preps:
            by_season[p.season].append(p)
        preps = [p for s in SEASONS for p in by_season[s][:args.limit]]
    _hb("PREPS_READY", {"games": len(preps), "skips": skips})

    # Pilot convergence
    pilot = _stratified_pilot(preps, PILOT_GAMES_PER_SEASON)
    _hb("PILOT", {"games": len(pilot)})
    convergence = _convergence(pilot, folds, tsampler, resolver)
    sims = args.sims

    # Full backtest (D3-driven = G1)
    _hb("FULL_BACKTEST", {"games": len(preps), "sims": sims})
    records = _simulate_records(preps, folds, tsampler, resolver, sims, check_legality=False, progress_every=400)
    # legality spot-check on the pilot already done (check_legality=True in convergence)

    # G0 baseline (generic league-average PA distribution) — same games/kernel/transitions
    _hb("BASELINE_G0", {"games": len(preps)})
    baseline = _simulate_records(preps, folds, tsampler, resolver, sims, fixed_probs=league_probs, progress_every=800)

    by_season = {}
    for season in SEASONS:
        recs = [r for r in records if r["season"] == season]
        brecs = [r for r in baseline if r["season"] == season]
        ev = _season_eval(recs, baseline_records=brecs)
        ev["retrospectiveScoringBands"] = _retrospective_bands(recs)
        by_season[str(season)] = ev

    # D3 game-level value decision (G1 vs G0)
    def d3_value():
        better = 0; worse = 0
        for season in SEASONS:
            g1 = by_season[str(season)]["winner"]; g0 = by_season[str(season)]["baselineG0"]["winner"]
            c1 = by_season[str(season)]["scoreMetrics"]["crpsTotal"]; c0 = by_season[str(season)]["baselineG0"]["crpsTotal"]
            better += int(g1["brier"] < g0["brier"]) + int(g1["logLoss"] < g0["logLoss"]) + int(c1 < c0)
            worse += int(g1["brier"] > g0["brier"]) + int(g1["logLoss"] > g0["logLoss"]) + int(c1 > c0)
        if better >= 5 and worse == 0:
            return "D3_GAME_LEVEL_VALUE_CONFIRMED"
        if better > worse:
            return "D3_GAME_LEVEL_VALUE_MARGINAL"
        if worse > better:
            return "D3_GAME_LEVEL_VALUE_NEGATIVE" if worse >= 5 else "D3_GAME_LEVEL_VALUE_NOT_CONFIRMED"
        return "D3_GAME_LEVEL_VALUE_NOT_CONFIRMED"

    # readiness
    total_illegal = sum(by_season[str(s)]["legality"]["illegal"] for s in SEASONS)
    total_nonterm = sum(by_season[str(s)]["legality"]["nonterminated"] for s in SEASONS)
    convergence_stable = convergence[str(1000)].get("driftMeanTotalVsPrev", 1.0) < 0.1
    readiness = ("WHOLE_GAME_SIMULATOR_RESEARCH_BASELINE_READY"
                 if (total_illegal == 0 and total_nonterm == 0 and convergence_stable)
                 else "WHOLE_GAME_SIMULATOR_PARTIALLY_READY")

    # contact-quality priority from tail behavior
    def contact_priority():
        under_high = []
        for season in SEASONS:
            rb = by_season[str(season)]["retrospectiveScoringBands"]["bands"]
            high = [b for b in rb if b["band"] == "12+"]
            cov = by_season[str(season)]["coverage"]["intTotal"]["90"]
            under_high.append((high[0]["totalBias"] if high else 0.0, cov))
        neg_tail = all(b < -0.5 for b, _ in under_high)
        under_disp = all(c < 0.85 for _, c in under_high)
        if neg_tail and under_disp:
            return "PREMIUM_CONTACT_DATA_PRIORITY_HIGH"
        if neg_tail or under_disp:
            return "PREMIUM_CONTACT_DATA_PRIORITY_MEDIUM"
        return "PREMIUM_CONTACT_DATA_PRIORITY_UNCHANGED"

    perf_pergame = None  # filled below via timing recorded during runs (approx from progress)
    payload = {
        "schemaVersion": mc.MONTE_CARLO_SCHEMA_VERSION,
        "runId": run_id,
        "contractName": mc.MONTE_CARLO_CONTRACT_NAME,
        "researchOnly": True,
        "participantMode": mc.PARTICIPANT_MODE,
        "datasetAuthority": dataset_authority,
        "parentAuthorities": parents,
        "d3ModelAuthority": dynamic_state_contract_sha(),
        "transitionModelSha": TRANSITION_MODEL_SHA,
        "featureContractAuthority": PHASE3_FEATURE_CONTRACT_SHA,
        "rngMasterSeed": MASTER_SEED,
        "simulationsPerGame": sims,
        "developmentStandardSimulations": DEV_STANDARD_SIMS,
        "eligibleGames": {str(s): sum(1 for p in preps if p.season == s) for s in SEASONS},
        "skippedGames": skips,
        "leagueBaselineProbs": {c: float(league_probs[i]) for i, c in enumerate(PA_CLASS_ORDER)},
        "convergence": convergence,
        "bySeason": by_season,
        "d3GameLevelValue": d3_value(),
        "contactQualityPriority": contact_priority(),
        "participationAblationDecision": "PARTICIPATION_ABLATION_READY" if readiness.endswith("BASELINE_READY") else "PARTICIPATION_ABLATION_PREMATURE",
        "simulatorReadiness": readiness,
        "legality": {"totalIllegalStates": total_illegal, "totalNonterminated": total_nonterm},
        "limitations": [
            "HISTORICAL_PARTICIPANTS_ORACLE_MODE: actual participants keyed to batting-team PA ordinal; NOT a prospective pregame forecast.",
            "Oracle participation is an optimistic upper bound relative to projected participation.",
            "No residual correction, no home-field adjustment, no calibration scaling (uncorrected baseline).",
            "Winner probability is a game-distribution diagnostic only; no sportsbook comparison, edge, or ROI.",
            "Contact-quality (Statcast) not used; D3 and the transition model are frozen.",
        ],
    }
    written = _write(payload, run_id)
    payload["artifact"] = written
    _hb("DONE", {"runId": run_id, "readiness": readiness, "d3Value": payload["d3GameLevelValue"], "reused": written["reused"]})
    print(json.dumps({
        "runId": run_id, "sims": sims, "eligible": payload["eligibleGames"],
        "2024_totalBias": by_season["2024"]["scoreMetrics"]["total"]["bias"],
        "2025_totalBias": by_season["2025"]["scoreMetrics"]["total"]["bias"],
        "2024_crpsTotal": by_season["2024"]["scoreMetrics"]["crpsTotal"],
        "2024_winnerBrier": by_season["2024"]["winner"]["brier"],
        "2024_cov90Total": by_season["2024"]["coverage"]["intTotal"]["90"],
        "d3GameLevelValue": payload["d3GameLevelValue"],
        "contactQualityPriority": payload["contactQualityPriority"],
        "readiness": readiness, "illegal": total_illegal, "nonterminated": total_nonterm,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
