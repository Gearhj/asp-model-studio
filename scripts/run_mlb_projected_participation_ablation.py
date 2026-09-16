"""run-mlb-projected-participation-ablation — Phase 5E P0→P3 participation ablation.

Measures how much whole-game predictive value survives as historical oracle participants are
progressively replaced by ASP's own frozen Milestone B research components:

  P0  historical oracle participants (reproduces Phase 5D on the comparable population)
  P1  projected lineup (L1) + oracle pitching
  P2  P1 + projected starter duration (S2), starter IDENTITY oracle, oracle bullpen after
  P3  P2 + projected bullpen usage (B1)   [PROJECTED_PARTICIPATION_RESEARCH_MODE]

Same D3 PA model, base-out transition model, kernel, 500 simulations/game, and RNG lineage
across all branches; only participation realism changes. No component is retrained or modified.
No sportsbook data, betting edge, ROI, or parlays. Winner probability is a diagnostic only.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.util
import json
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
from server.sports_phase5.pa_provider import D3_STATE_TABLE_SHA, D3ProbabilisticPAProvider, PlayerStateResolver  # noqa: E402
from server.sports_phase5.game_initialization import RngLineage  # noqa: E402
from server.sports_phase5.participation_projection import (  # noqa: E402
    BRANCHES, BRANCH_LABELS, TemporalStateResolver, build_team_projections, build_branch_pa_uuids,
)
from server.sports_phase4.dynamic_contract import PHASE3_FEATURE_CONTRACT_SHA, dynamic_state_contract_sha  # noqa: E402
from scripts._retired_2025_guard import retire_2025  # Phase 7D.4 Gate 12 (B8)

# Reuse the Phase 5D evaluation helpers.
_spec = importlib.util.spec_from_file_location("wg_mc_cli", REPOSITORY_ROOT / "scripts" / "run_mlb_whole_game_monte_carlo.py")
d5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(d5)

RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio"
DYNAMIC_NS = RUNTIME_ROOT / "sports-modeling" / "mlb-dynamic-player-state-v1"
PA_NS = RUNTIME_ROOT / "sports-modeling" / "mlb-pa-v1"
PART_NS = RUNTIME_ROOT / "sports-phase4" / "mlb-participation-usage-v1"
OUTPUT_ROOT = RUNTIME_ROOT / "sports-phase5" / "projected-participation-ablation"
CONTRACT_PATH = REPOSITORY_ROOT / "docs" / "contracts" / "MLB_PROJECTED_PARTICIPATION_ABLATION_V1.md"
DEFAULT_EXCHANGE_ROOT = Path(r"C:/Users/james/asp-model-exchange")
MANIFEST = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
TRANSITION_MODEL_SHA = "4f312af6c61c191b8ca19a71b35d8da12a587f204fb19b257715af9b7a3459e4"
SEASONS = (2024, 2025)
MASTER_SEED = 20_260_818
SIMS = 500
PILOT_PER_SEASON = 100
BOOTSTRAP_REPLICATES = 500
BOOTSTRAP_SEED = 5_050_505
_STARTED = time.monotonic()

_PT_COLS = ["game_id", "game_date", "season", "month", "top_bottom", "play_number", "batter_id",
            "pitcher_id", "pa_outcome", "plate_appearance_id", "pbp_quality", "regulation_innings",
            "visiting_team_id", "home_team_id", "visiting_score_after", "home_score_after"]


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _hb(stage: str, ev: Mapping[str, Any]) -> None:
    print(f"[p5e] {int(time.monotonic() - _STARTED):>5}s | {stage} | " + " ".join(f"{k}={v}" for k, v in ev.items()), flush=True)


def _part(name: str) -> str:
    fp = glob.glob(str(PART_NS / "objects/sha256/**" / f"{name}.parquet"), recursive=True)
    if not fp:
        raise RuntimeError(f"participation artifact missing: {name}")
    return fp[0]


class Prep:
    __slots__ = ("game_id", "season", "month", "game_date", "regulation", "away_team", "home_team",
                 "away_pa", "home_pa", "actual_away", "actual_home")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _dataset_authority() -> dict[str, Any]:
    from server.persistence.db import Database
    from server.sports_datasets.registry import SportsDatasetRegistry
    db = Database(RUNTIME_ROOT / "persistence" / "asp_model_studio.db")
    db.initialize()
    active = SportsDatasetRegistry(db).get_active()
    if not active or active["manifest_sha"] != MANIFEST:
        raise RuntimeError("dataset authority mismatch")
    return {"registrationId": active["registration_id"], "datasetId": active["dataset_id"], "manifestSha": active["manifest_sha"]}


def _load():
    state = pq.read_table(str(DYNAMIC_NS / "objects/sha256" / D3_STATE_TABLE_SHA[:2] / D3_STATE_TABLE_SHA / "mlb-dynamic-player-state-v1.parquet")).to_pandas()
    exact_resolver = PlayerStateResolver.from_records(state.to_dict("records"), state_table_sha=D3_STATE_TABLE_SHA)
    provider = D3ProbabilisticPAProvider.from_runtime(dynamic_namespace_root=DYNAMIC_NS, resolver=exact_resolver)
    temporal = TemporalStateResolver(state.to_dict("records"), state_table_sha=D3_STATE_TABLE_SHA)
    folds = {2024: mc.FastD3Fold.from_model(provider._models[2024]), 2025: mc.FastD3Fold.from_model(provider._models[2025])}
    tm = glob.glob(str(RUNTIME_ROOT / "sports-phase5" / "base-out-transition" / f"*model-sha256-{TRANSITION_MODEL_SHA[:16]}.json"))[0]
    content = Path(tm).read_bytes()
    if hashlib.sha256(content).hexdigest() != TRANSITION_MODEL_SHA:
        raise RuntimeError("transition model SHA mismatch")
    tsampler = mc.FastTransitionSampler(bt.TransitionModel.from_dict(json.loads(content.decode())))
    return folds, tsampler, temporal


def _projection_authorities() -> dict[str, Any]:
    def cid(name):
        f = pq.ParquetFile(_part(name))
        md = f.schema_arrow.metadata or {}
        return md.get(b"componentId", b"").decode()
    return {
        "lineup": cid("lineup_projection-fold-2024-predictions"),
        "starter": cid("starter_duration-fold-2024-predictions"),
        "bullpen": cid("bullpen_usage-fold-2024-predictions"),
    }


def _load_projections() -> dict[tuple[str, str], Any]:
    projections: dict[tuple[str, str], Any] = {}
    lin_by: dict[tuple[str, str], list] = defaultdict(list)
    sta_by: dict[tuple[str, str], list] = defaultdict(list)
    bul_by: dict[tuple[str, str], list] = defaultdict(list)
    for season in SEASONS:
        lin = pq.read_table(_part(f"lineup_projection-fold-{season}-predictions")).to_pandas()
        sta = pq.read_table(_part(f"starter_duration-fold-{season}-predictions")).to_pandas()
        bul = pq.read_table(_part(f"bullpen_usage-fold-{season}-predictions")).to_pandas()
        for (g, t), grp in lin.groupby(["game_id", "team_id"]):
            lin_by[(str(g), str(t))] = grp.to_dict("records")
        for (g, t), grp in sta.groupby(["game_id", "team_id"]):
            sta_by[(str(g), str(t))] = grp.to_dict("records")
        for (g, t), grp in bul.groupby(["game_id", "team_id"]):
            bul_by[(str(g), str(t))] = grp.to_dict("records")
    keys = set(lin_by) | set(sta_by) | set(bul_by)
    for key in keys:
        projections[key] = build_team_projections(lin_by.get(key, []), sta_by.get(key, []), bul_by.get(key, []))
    return projections


def _build_preps(pt: pd.DataFrame, uuid_b, uuid_p) -> tuple[list[Prep], dict[str, int]]:
    preps: list[Prep] = []
    skips: dict[str, int] = defaultdict(int)
    pt = pt.sort_values(["game_id", "play_number"])
    for gid, g in pt.groupby("game_id", sort=False):
        season = int(g["season"].iloc[0])
        regulation = int(g["regulation_innings"].iloc[0]) if pd.notna(g["regulation_innings"].iloc[0]) else 9
        last = g.iloc[-1]
        if (g["pbp_quality"] != "FULL").any():
            skips["PBP_NOT_FULL"] += 1
            continue
        term = g[g["pa_outcome"].notna() & (g["pa_outcome"] != "")]
        def seq(rows):
            out = []
            for bid, pid in zip(rows["batter_id"].astype(str), rows["pitcher_id"].astype(str)):
                bu, pu = uuid_b.get(bid), uuid_p.get(pid)
                if bu is None or pu is None:
                    return None
                out.append((bu, pu))
            return out
        away_pa = seq(term[term["top_bottom"] == 0])
        home_pa = seq(term[term["top_bottom"] == 1])
        if away_pa is None or home_pa is None or len(away_pa) < 9 or len(home_pa) < 9:
            skips["INSUFFICIENT_OR_UNRESOLVED"] += 1
            continue
        preps.append(Prep(game_id=str(gid), season=season, month=int(g["month"].iloc[0]),
                          game_date=str(g["game_date"].iloc[0]), regulation=regulation,
                          away_team=str(g["visiting_team_id"].iloc[0]), home_team=str(g["home_team_id"].iloc[0]),
                          away_pa=away_pa, home_pa=home_pa,
                          actual_away=int(last["visiting_score_after"]), actual_home=int(last["home_score_after"])))
    return preps, dict(skips)


def _comparable(preps, projections):
    out = []
    for p in preps:
        ap = projections.get((p.game_id, p.away_team))
        hp = projections.get((p.game_id, p.home_team))
        if ap is None or hp is None:
            continue
        if len(ap.lineup) == 9 and len(hp.lineup) == 9 and ap.starter_uuid and hp.starter_uuid:
            out.append(p)
    return out


def _simulate_branch(preps, projections, folds, tsampler, resolver, branch, *, progress_every=500):
    records = []
    t0 = time.perf_counter()
    for i, p in enumerate(preps):
        away_proj = projections[(p.game_id, p.away_team)]
        home_proj = projections[(p.game_id, p.home_team)]
        seqs = build_branch_pa_uuids(branch, away_actual=p.away_pa, home_actual=p.home_pa,
                                     away_proj=away_proj, home_proj=home_proj)
        fold = folds[p.season]
        contribs = mc.build_game_contribs(fold=fold, resolver=resolver, game_date=p.game_date, regulation=p.regulation,
                                          away_pa_uuids=seqs["away_pa"], home_pa_uuids=seqs["home_pa"],
                                          away_start_batter_uuids=seqs["away_start"], home_start_batter_uuids=seqs["home_start"])
        result = mc.simulate_game(game_id=p.game_id, contribs=contribs, fold=fold, transition_sampler=tsampler,
                                  rng_lineage=RngLineage(MASTER_SEED, p.game_id), n_sims=SIMS)
        rec = d5._evaluate_game(result, p)
        rec["lineupRecall"] = away_proj.lineup_recall
        records.append(rec)
        if progress_every and (i + 1) % progress_every == 0:
            rate = (i + 1) / (time.perf_counter() - t0)
            _hb("SIMULATE", {"branch": branch, "games": i + 1, "of": len(preps), "gps": f"{rate:.1f}", "etaMin": f"{(len(preps)-i-1)/rate/60:.1f}"})
    return records


def _branch_season_eval(records) -> dict[str, Any]:
    return {
        "games": len(records),
        "scoreMetrics": d5._score_metrics(records),
        "coverage": d5._coverage(records),
        "winner": d5._brier_logloss(records),
        "calibrationEce": d5._calibration_bins(records)["ece"],
        "actualHomeWinRate": float(np.mean([r["homeWon"] for r in records])),
        "meanSimulatedHomeWinProb": float(np.mean([r["pHome"] for r in records])),
        "simulatedMeanTotal": float(np.mean([r["meanTotal"] for r in records])),
        "actualMeanTotal": float(np.mean([r["actualTotal"] for r in records])),
        "legality": {"illegal": int(sum(r["illegal"] for r in records)), "nonterminated": int(sum(r["nonterminated"] for r in records))},
    }


def _deltas(a_eval, b_eval) -> dict[str, Any]:
    def d(metric_path):
        av = _dig(a_eval, metric_path); bv = _dig(b_eval, metric_path)
        return {"abs": bv - av, "relPct": (100.0 * (bv - av) / abs(av)) if av else None}
    return {
        "winnerBrier": d(["winner", "brier"]), "winnerLogLoss": d(["winner", "logLoss"]),
        "totalCrps": d(["scoreMetrics", "crpsTotal"]), "totalMae": d(["scoreMetrics", "total", "mae"]),
        "totalBiasAbsChange": {"abs": abs(_dig(b_eval, ["scoreMetrics", "total", "bias"])) - abs(_dig(a_eval, ["scoreMetrics", "total", "bias"]))},
        "runDiffMae": d(["scoreMetrics", "diff", "mae"]),
        "cov90": {"abs": _dig(b_eval, ["coverage", "intTotal", "90"]) - _dig(a_eval, ["coverage", "intTotal", "90"])},
    }


def _dig(d, path):
    for k in path:
        d = d[k]
    return d


def _bootstrap(recs_by_branch, pairs) -> dict[str, Any]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    n = len(next(iter(recs_by_branch.values())))
    idx_all = np.arange(n)
    # align records by game order (same preps order) so a resample compares same games
    out = {}
    for a, b in pairs:
        ra = recs_by_branch[a]; rb = recs_by_branch[b]
        pa = np.clip(np.array([r["pHome"] for r in ra]), 1e-6, 1 - 1e-6)
        pb = np.clip(np.array([r["pHome"] for r in rb]), 1e-6, 1 - 1e-6)
        y = np.array([r["homeWon"] for r in ra], dtype=float)
        brier_a = (pa - y) ** 2; brier_b = (pb - y) ** 2
        ll_a = -(y * np.log(pa) + (1 - y) * np.log(1 - pa)); ll_b = -(y * np.log(pb) + (1 - y) * np.log(1 - pb))
        crps_a = np.array([r["crpsTotal"] for r in ra]); crps_b = np.array([r["crpsTotal"] for r in rb])
        db, dl, dc = [], [], []
        for _ in range(BOOTSTRAP_REPLICATES):
            s = rng.integers(0, n, n)
            db.append(brier_b[s].mean() - brier_a[s].mean())
            dl.append(ll_b[s].mean() - ll_a[s].mean())
            dc.append(crps_b[s].mean() - crps_a[s].mean())
        def summ(arr):
            arr = np.array(arr)
            return {"meanDelta": float(arr.mean()), "ci95": [float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))],
                    "probWorse": float((arr > 0).mean()), "probBetter": float((arr < 0).mean())}
        out[f"{b}_vs_{a}"] = {"winnerBrier": summ(db), "winnerLogLoss": summ(dl), "totalCrps": summ(dc)}
    return out


def _magnitude(rel_pct: float | None) -> str:
    if rel_pct is None:
        return "UNKNOWN"
    a = abs(rel_pct)
    if a < 1.0:
        return "NEGLIGIBLE"
    if a < 3.0:
        return "SMALL"
    if a < 8.0:
        return "MEANINGFUL"
    return "LARGE"


def _write(payload, run_id) -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    record = {"schemaVersion": "MLB_PROJECTED_PARTICIPATION_ABLATION_RECORD_V1", "ablation": payload}
    content = json.dumps(record, indent=2, sort_keys=True).encode()
    named = OUTPUT_ROOT / f"projected-participation-{run_id}.ablation.json"
    latest = OUTPUT_ROOT / "latest.ablation.json"
    reused = named.is_file() and named.read_bytes() == content
    if not reused:
        named.write_bytes(content)
    latest.write_bytes(content)
    return {"path": str(named), "latest": str(latest), "reused": reused}


def main() -> int:
    retire_2025("server.sports_cockpit.gen3_authority.run_feature_family_ablation (canonical 2024-only research)")
    parser = argparse.ArgumentParser(description="Phase 5E projected participation ablation")
    parser.add_argument("--exchange-root", default=str(DEFAULT_EXCHANGE_ROOT))
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--pilot-only", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    run_id_core = {"d3": dynamic_state_contract_sha(), "state": D3_STATE_TABLE_SHA, "transition": TRANSITION_MODEL_SHA,
                   "feature": PHASE3_FEATURE_CONTRACT_SHA, "seasons": list(SEASONS), "sims": SIMS, "masterSeed": MASTER_SEED,
                   "pilotOnly": bool(args.pilot_only), "limit": args.limit}
    run_id = "projected-participation-" + _sha(run_id_core)[:16]

    if args.status:
        latest = OUTPUT_ROOT / "latest.ablation.json"
        if latest.is_file():
            rec = json.loads(latest.read_text())["ablation"]
            print(json.dumps({"runId": rec.get("runId"), "decision": rec.get("overallDecision")}, indent=2))
            return 0
        print("no ablation record")
        return 1

    existing = OUTPUT_ROOT / f"projected-participation-{run_id}.ablation.json"
    if existing.is_file() and not args.force:
        rec = json.loads(existing.read_text())["ablation"]
        (OUTPUT_ROOT / "latest.ablation.json").write_bytes(existing.read_bytes())
        _hb("REUSED", {"runId": run_id, "decision": rec.get("overallDecision")})
        print(json.dumps({"runId": run_id, "reused": True, "overallDecision": rec.get("overallDecision")}, indent=2))
        return 0

    exchange_root = Path(args.exchange_root)
    _hb("LOAD", {})
    dataset_authority = _dataset_authority()
    folds, tsampler, resolver = _load()
    proj_auth = _projection_authorities()
    fv = pq.read_table(glob.glob(str(PA_NS / "objects/sha256/**/mlb-pa-feature-view-v1.parquet"), recursive=True)[0],
                       columns=["plate_appearance_id", "batter_canonical_player_uuid", "pitcher_canonical_player_uuid"]).to_pandas()

    _hb("LOAD_PT", {})
    base = exchange_root / "datasets" / "mlb-fd1" / f"sha256-{MANIFEST}" / "parquet" / "play_transition"
    files = glob.glob(str(base / "**" / "*.parquet"), recursive=True)
    pt = pd.concat([pq.read_table(f, columns=_PT_COLS).to_pandas().pipe(lambda d: d[d["season"].isin(SEASONS)]) for f in files], ignore_index=True)
    term = pt[pt["pa_outcome"].notna() & (pt["pa_outcome"] != "")]
    m = term[["plate_appearance_id", "batter_id", "pitcher_id"]].merge(fv, on="plate_appearance_id", how="inner")
    uuid_b = dict(zip(m["batter_id"].astype(str), m["batter_canonical_player_uuid"].astype(str)))
    uuid_p = dict(zip(m["pitcher_id"].astype(str), m["pitcher_canonical_player_uuid"].astype(str)))

    _hb("PROJECTIONS", {})
    projections = _load_projections()
    preps, skips = _build_preps(pt, uuid_b, uuid_p)
    comparable = _comparable(preps, projections)
    if args.limit:
        by = defaultdict(list)
        for p in comparable:
            by[p.season].append(p)
        comparable = [p for s in SEASONS for p in by[s][:args.limit]]
    _hb("COMPARABLE", {"eligiblePreps": len(preps), "comparable": len(comparable), "skips": skips})

    run_preps = comparable
    if args.pilot_only:
        pilot = []
        for s in SEASONS:
            ss = sorted([p for p in comparable if p.season == s], key=lambda p: (p.month, p.actual_away + p.actual_home, p.game_id))
            idx = np.linspace(0, len(ss) - 1, min(PILOT_PER_SEASON, len(ss))).round().astype(int)
            pilot.extend([ss[i] for i in idx])
        run_preps = pilot
        _hb("PILOT_ONLY", {"games": len(run_preps)})

    recs_by_branch: dict[str, list] = {}
    for branch in BRANCHES:
        _hb("BRANCH_START", {"branch": branch, "label": BRANCH_LABELS[branch][:30]})
        recs_by_branch[branch] = _simulate_branch(run_preps, projections, folds, tsampler, resolver, branch)

    by_season = {}
    for s in SEASONS:
        season_recs = {b: [r for r in recs_by_branch[b] if r["season"] == s] for b in BRANCHES}
        evals = {b: _branch_season_eval(season_recs[b]) for b in BRANCHES}
        deltas = {"P1_vs_P0": _deltas(evals["P0"], evals["P1"]), "P2_vs_P1": _deltas(evals["P1"], evals["P2"]),
                  "P3_vs_P2": _deltas(evals["P2"], evals["P3"]), "P3_vs_P0": _deltas(evals["P0"], evals["P3"])}
        by_season[str(s)] = {"branches": evals, "deltas": deltas}

    bootstrap = _bootstrap(recs_by_branch, [("P0", "P1"), ("P1", "P2"), ("P2", "P3"), ("P0", "P3")])

    # decisions
    def overall():
        mags = []
        for s in SEASONS:
            d = by_season[str(s)]["deltas"]["P3_vs_P0"]
            mags.append(_magnitude(d["winnerBrier"]["relPct"]))
            mags.append(_magnitude(d["totalCrps"]["relPct"]))
        worst = max(mags, key=lambda m: ["NEGLIGIBLE", "SMALL", "MEANINGFUL", "LARGE", "UNKNOWN"].index(m) if m != "UNKNOWN" else -1)
        # significance: does bootstrap say P3 worse than P0 on Brier in both seasons with prob>0.9?
        sig = bootstrap["P3_vs_P0"]["winnerBrier"]["probWorse"] > 0.9
        if worst in ("NEGLIGIBLE", "SMALL"):
            return "PROJECTED_PARTICIPATION_VALUE_PRESERVED" if worst == "NEGLIGIBLE" else "PROJECTED_PARTICIPATION_ACCEPTABLE_DEGRADATION"
        if worst == "MEANINGFUL":
            return "PROJECTED_PARTICIPATION_MATERIAL_DEGRADATION"
        return "PROJECTED_PARTICIPATION_BLOCKING"

    def component_decision(delta_key):
        mags = [_magnitude(by_season[str(s)]["deltas"][delta_key]["winnerBrier"]["relPct"]) for s in SEASONS]
        mags += [_magnitude(by_season[str(s)]["deltas"][delta_key]["totalCrps"]["relPct"]) for s in SEASONS]
        worst = max(mags, key=lambda m: ["NEGLIGIBLE", "SMALL", "MEANINGFUL", "LARGE", "UNKNOWN"].index(m) if m != "UNKNOWN" else -1)
        if worst in ("NEGLIGIBLE", "SMALL"):
            return "ACCEPTABLE"
        if worst == "MEANINGFUL":
            return "MATERIAL"
        return "BLOCKING"

    overall_decision = overall()
    lineup_dec = f"LINEUP_GAME_IMPACT_{component_decision('P1_vs_P0')}"
    starter_dec = f"STARTER_DURATION_GAME_IMPACT_{component_decision('P2_vs_P1')}"
    bullpen_dec = f"BULLPEN_GAME_IMPACT_{component_decision('P3_vs_P2')}"

    fb = resolver.fallback_summary()
    payload = {
        "schemaVersion": "MLB_PROJECTED_PARTICIPATION_ABLATION_V1",
        "runId": run_id, "contractName": "MLB_PROJECTED_PARTICIPATION_ABLATION_V1", "researchOnly": True,
        "pilotOnly": bool(args.pilot_only),
        "datasetAuthority": dataset_authority,
        "d3ModelAuthority": dynamic_state_contract_sha(), "transitionModelSha": TRANSITION_MODEL_SHA,
        "featureContractAuthority": PHASE3_FEATURE_CONTRACT_SHA,
        "projectionAuthorities": proj_auth,
        "branchLabels": BRANCH_LABELS,
        "simulationsPerGame": SIMS, "rngMasterSeed": MASTER_SEED,
        "comparableGames": {str(s): sum(1 for p in run_preps if p.season == s) for s in SEASONS},
        "skips": skips,
        "bySeason": by_season,
        "bootstrap": bootstrap,
        "stateFallback": fb,
        "meanLineupRecall": {str(s): float(np.mean([r["lineupRecall"] for r in recs_by_branch["P1"] if r["season"] == s and r["lineupRecall"] is not None])) for s in SEASONS},
        "overallDecision": overall_decision,
        "lineupGameImpact": lineup_dec, "starterDurationGameImpact": starter_dec, "bullpenGameImpact": bullpen_dec,
        "remainingOracleDependencies": {
            "STARTER_IDENTITY": "CRITICAL", "GAME_SCHEDULE_TEAMS_DATE": "MODERATE",
            "HISTORICAL_SOURCE_POPULATION": "MODERATE", "NO_INJURY_SCRATCH_FEED": "MODERATE",
        },
        "limitations": [
            "PROJECTED_PARTICIPATION_RESEARCH_MODE: P3 still uses actual STARTER IDENTITY (S2 is CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY) and a historical source population; not a live pregame forecast.",
            "Projected lineup batting order is proxied by L1 start-probability order (L1 does not predict order); D3 has no batting-order feature so the effect is second-order.",
            "Projected participation is deterministic per game (point projections); PA/transition sampling supplies game-outcome uncertainty.",
            "Projected players absent from the game date resolve to their most-recent prior cumulative B-state (counted); no component retrained.",
            "Winner probability is a diagnostic only; no sportsbook comparison, edge, ROI, or parlays.",
        ],
    }
    written = _write(payload, run_id)
    payload["artifact"] = written
    _hb("DONE", {"runId": run_id, "decision": overall_decision, "reused": written["reused"]})
    print(json.dumps({
        "runId": run_id, "comparable": payload["comparableGames"],
        "overallDecision": overall_decision, "lineup": lineup_dec, "starter": starter_dec, "bullpen": bullpen_dec,
        "P3_vs_P0_2024_brierRelPct": by_season["2024"]["deltas"]["P3_vs_P0"]["winnerBrier"]["relPct"],
        "P3_vs_P0_2024_crpsRelPct": by_season["2024"]["deltas"]["P3_vs_P0"]["totalCrps"]["relPct"],
        "stateFallback": fb, "reused": written["reused"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
