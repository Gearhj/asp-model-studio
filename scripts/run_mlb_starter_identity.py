"""run-mlb-starter-identity — Phase 5F starter-identity projection + Q0->Q1 simulator ablation.

Builds and validates MLB_STARTER_IDENTITY_PROJECTION_V1 (predict the starting pitcher per
team-game from strictly-prior information), then measures the game-level cost of replacing the
oracle starter identity with the projection inside the whole-game simulator:

  Q0  P3 (Phase 5E projected participation) with STARTER_IDENTITY_ORACLE
  Q1  same, but the starter identity is the model's projection, and starter duration is bound to
      the PROJECTED identity (actual S2 when the projection is correct; the pitcher's own mean
      historical batters-faced otherwise). Bullpen (B1) and lineup (L1) are unchanged.

Only the starter identity (and its natural downstream duration) changes Q0->Q1. Same D3,
transition model, kernel, 500 sims/game, RNG lineage. No component retrained. No sportsbook data,
edge, ROI, or parlays; winner probability is a diagnostic only.
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
from dataclasses import replace as dc_replace
from pathlib import Path
from typing import Any, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from server.sports_phase5 import whole_game_monte_carlo as mc  # noqa: E402
from server.sports_phase5 import starter_identity as si  # noqa: E402
from server.sports_phase5.participation_projection import build_branch_pa_uuids  # noqa: E402
from server.sports_phase5.game_initialization import RngLineage  # noqa: E402
from server.sports_phase4.dynamic_contract import PHASE3_FEATURE_CONTRACT_SHA, dynamic_state_contract_sha  # noqa: E402
from server.sports_phase5.pa_provider import D3_STATE_TABLE_SHA  # noqa: E402

# Reuse Phase 5E CLI (which itself reuses Phase 5D eval helpers).
_spec = importlib.util.spec_from_file_location("p5e_cli", REPOSITORY_ROOT / "scripts" / "run_mlb_projected_participation_ablation.py")
p5e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p5e)
d5 = p5e.d5

RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio"
OUTPUT_ROOT = RUNTIME_ROOT / "sports-phase5" / "starter-identity"
CONTRACT_PATH = REPOSITORY_ROOT / "docs" / "contracts" / "MLB_STARTER_IDENTITY_PROJECTION_V1.md"
DEFAULT_EXCHANGE_ROOT = Path(r"C:/Users/james/asp-model-exchange")
MANIFEST = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
TRANSITION_MODEL_SHA = "4f312af6c61c191b8ca19a71b35d8da12a587f204fb19b257715af9b7a3459e4"
DEV_SEASONS = (2021, 2022, 2023)
SEASONS = (2024, 2025)
MASTER_SEED = 20_260_818
SIMS = 500
BOOTSTRAP_REPLICATES = 500
BOOTSTRAP_SEED = 6_060_606
MONTHS = {"Mar/Apr": (3, 4), "May/Jun": (5, 6), "Jul/Aug": (7, 8), "Sep/Oct": (9, 10)}
_STARTED = time.monotonic()

_PT_COLS = ["game_id", "game_date", "season", "month", "top_bottom", "play_number", "batter_id",
            "pitcher_id", "pa_outcome", "plate_appearance_id", "pbp_quality", "regulation_innings",
            "visiting_team_id", "home_team_id", "visiting_score_after", "home_score_after", "pitching_team_id"]


def _sha(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _hb(stage: str, ev: Mapping[str, Any]) -> None:
    print(f"[p5f] {int(time.monotonic() - _STARTED):>5}s | {stage} | " + " ".join(f"{k}={v}" for k, v in ev.items()), flush=True)


def _starter_rows_and_apps(pt: pd.DataFrame):
    dfp = pt[pt["pitcher_id"].notna() & (pt["pitcher_id"] != "")].copy()
    dfp["game_date"] = dfp["game_date"].astype(str).str[:10]
    firsts = dfp.sort_values("play_number").groupby(["game_id", "pitching_team_id"]).first().reset_index()
    starter_rows = firsts[["game_id", "game_date", "season", "pitching_team_id", "pitcher_id"]].rename(
        columns={"pitching_team_id": "team_id", "pitcher_id": "starter_id"}).to_dict("records")
    app_rows = dfp[["pitching_team_id", "game_date", "pitcher_id"]].drop_duplicates().rename(
        columns={"pitching_team_id": "team_id"}).to_dict("records")
    return starter_rows, app_rows


def _month_of(game_date: str) -> int:
    return int(str(game_date)[5:7])


def _evaluate_starter(model, games_by_season) -> dict[str, Any]:
    out = {"bySeason": {}, "baselines": {}, "earlySeason": {}, "restDay": {}, "openers": {}}
    for season in SEASONS:
        gg = games_by_season[season]
        out["bySeason"][str(season)] = si.rank_metrics(gg, model.probabilities)
        out["baselines"][str(season)] = {
            bk: si.rank_metrics(gg, (lambda g, k=bk: _softmax(si.baseline_scores(g, k))))
            for bk in ("S0_MOST_OVERDUE", "S1_ROTATION_ORDER", "S2_START_FREQUENCY")
        }
        # early season by month band
        band = {}
        for label, months in MONTHS.items():
            sub = [g for g in gg if _month_of(g.game_date) in months]
            if sub:
                band[label] = {k: si.rank_metrics(sub, model.probabilities)[k] for k in ("top1Accuracy", "top2Accuracy", "logLoss", "candidatePoolCoverage")}
        out["earlySeason"][str(season)] = band
        # rest-day segmentation by team-games since last start (proxy for rotation cadence)
        idx = si.FEATURE_NAMES.index("team_games_since_last_start")
        rest = {}
        for lbl, lo, hi in (("<=3", 0, 3), ("4", 4, 4), ("5", 5, 5), ("6", 6, 6), ("7+", 7, 999)):
            sub = [g for g in gg if g.label_index >= 0 and lo <= g.features[g.label_index, idx] <= hi]
            if sub:
                rest[lbl] = {"n": len(sub), "top1": si.rank_metrics(sub, model.probabilities)["top1Accuracy"]}
        out["restDay"][str(season)] = rest
        # openers / irregular: true starter with low season start frequency (< 0.10)
        fidx = si.FEATURE_NAMES.index("start_frequency")
        opener = [g for g in gg if g.label_index >= 0 and g.features[g.label_index, fidx] < 0.10]
        out["openers"][str(season)] = {"n": len(opener), "top1": si.rank_metrics(opener, model.probabilities)["top1Accuracy"] if opener else None}
    return out


def _softmax(s):
    s = s - s.max(); e = np.exp(s); return e / e.sum()


def _projected_starters(model, games_by_season, uuid_p, duration_proxy):
    """Map (game_id, team_id) -> dict(projected canonical uuid, correct, duration, uncertainty)."""
    proj = {}
    for season in SEASONS:
        for g in games_by_season[season]:
            probs = model.probabilities(g)
            top = int(np.argmax(probs))
            proj_ret = g.candidates[top]
            correct = (g.label_index == top)
            canonical = uuid_p.get(proj_ret)
            unc = si.game_uncertainty(g, probs)
            # duration bound to the PROJECTED identity
            if correct:
                dur = None  # signal to use the actual S2 s2_bfp
            else:
                dur = duration_proxy.get(canonical, duration_proxy.get("__median__", 19.0))
            proj[(g.game_id, g.team_id)] = {"canonical": canonical, "correct": correct, "duration": dur,
                                            "topProb": unc["topProb"], "gap": unc["gapTop1Top2"], "entropy": unc["entropy"]}
    return proj


def _simulate_q(preps, projections, proj_starters, folds, tsampler, resolver, branch_q, *, progress_every=500):
    """Q0 = P3 with oracle starter; Q1 = P3 with projected starter identity + projected duration."""
    records = []
    t0 = time.perf_counter()
    for i, p in enumerate(preps):
        away_proj = projections[(p.game_id, p.away_team)]
        home_proj = projections[(p.game_id, p.home_team)]
        n_wrong = 0
        if branch_q == "Q1":
            away_ps = proj_starters.get((p.game_id, p.away_team))
            home_ps = proj_starters.get((p.game_id, p.home_team))
            away_proj, aw = _override_starter(away_proj, away_ps)
            home_proj, hw = _override_starter(home_proj, home_ps)
            n_wrong = aw + hw
        seqs = build_branch_pa_uuids("P3", away_actual=p.away_pa, home_actual=p.home_pa,
                                     away_proj=away_proj, home_proj=home_proj)
        fold = folds[p.season]
        contribs = mc.build_game_contribs(fold=fold, resolver=resolver, game_date=p.game_date, regulation=p.regulation,
                                          away_pa_uuids=seqs["away_pa"], home_pa_uuids=seqs["home_pa"],
                                          away_start_batter_uuids=seqs["away_start"], home_start_batter_uuids=seqs["home_start"])
        result = mc.simulate_game(game_id=p.game_id, contribs=contribs, fold=fold, transition_sampler=tsampler,
                                  rng_lineage=RngLineage(MASTER_SEED, p.game_id), n_sims=SIMS)
        rec = d5._evaluate_game(result, p)
        rec["startersWrong"] = n_wrong
        records.append(rec)
        if progress_every and (i + 1) % progress_every == 0:
            rate = (i + 1) / (time.perf_counter() - t0)
            _hb("SIMULATE", {"branch": branch_q, "games": i + 1, "of": len(preps), "gps": f"{rate:.1f}", "etaMin": f"{(len(preps)-i-1)/rate/60:.1f}"})
    return records


def _override_starter(team_proj, ps):
    """Return a TeamProjection with the projected starter identity + duration; count if wrong."""
    if ps is None or ps["canonical"] is None:
        return team_proj, 0  # no valid projection -> keep (counted as fallback via absence)
    new_s2 = team_proj.s2_bfp if ps["duration"] is None else float(ps["duration"])
    return dc_replace(team_proj, starter_uuid=ps["canonical"], s2_bfp=new_s2), (0 if ps["correct"] else 1)


def _q_eval(records):
    return p5e._branch_season_eval(records)


def _write(payload, run_id) -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    record = {"schemaVersion": "MLB_STARTER_IDENTITY_RECORD_V1", "starterIdentity": payload}
    content = json.dumps(record, indent=2, sort_keys=True).encode()
    named = OUTPUT_ROOT / f"starter-identity-{run_id}.starter.json"
    latest = OUTPUT_ROOT / "latest.starter.json"
    reused = named.is_file() and named.read_bytes() == content
    if not reused:
        named.write_bytes(content)
    latest.write_bytes(content)
    return {"path": str(named), "latest": str(latest), "reused": reused}


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 5F starter identity + Q0/Q1 ablation")
    ap.add_argument("--exchange-root", default=str(DEFAULT_EXCHANGE_ROOT))
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    run_id_core = {"d3": dynamic_state_contract_sha(), "state": D3_STATE_TABLE_SHA, "transition": TRANSITION_MODEL_SHA,
                   "feature": PHASE3_FEATURE_CONTRACT_SHA, "seasons": list(SEASONS), "dev": list(DEV_SEASONS),
                   "sims": SIMS, "masterSeed": MASTER_SEED, "features": list(si.FEATURE_NAMES), "limit": args.limit}
    run_id = "starter-identity-" + _sha(run_id_core)[:16]

    if args.status:
        latest = OUTPUT_ROOT / "latest.starter.json"
        if latest.is_file():
            rec = json.loads(latest.read_text())["starterIdentity"]
            print(json.dumps({"runId": rec.get("runId"), "modelDecision": rec.get("modelDecision"),
                              "simulatorDecision": rec.get("simulatorDecision")}, indent=2))
            return 0
        print("no starter-identity record"); return 1

    existing = OUTPUT_ROOT / f"starter-identity-{run_id}.starter.json"
    if existing.is_file() and not args.force:
        rec = json.loads(existing.read_text())["starterIdentity"]
        (OUTPUT_ROOT / "latest.starter.json").write_bytes(existing.read_bytes())
        _hb("REUSED", {"runId": run_id, "sim": rec.get("simulatorDecision")})
        print(json.dumps({"runId": run_id, "reused": True, "modelDecision": rec.get("modelDecision"),
                          "simulatorDecision": rec.get("simulatorDecision")}, indent=2))
        return 0

    exchange_root = Path(args.exchange_root)
    _hb("LOAD", {})
    dataset_authority = p5e._dataset_authority()
    folds, tsampler, resolver = p5e._load()
    fv = pq.read_table(glob.glob(str(p5e.PA_NS / "objects/sha256/**/mlb-pa-feature-view-v1.parquet"), recursive=True)[0],
                       columns=["plate_appearance_id", "batter_canonical_player_uuid", "pitcher_canonical_player_uuid"]).to_pandas()

    _hb("LOAD_PT", {})
    base = exchange_root / "datasets" / "mlb-fd1" / f"sha256-{MANIFEST}" / "parquet" / "play_transition"
    files = glob.glob(str(base / "**" / "*.parquet"), recursive=True)
    pt_all = pd.concat([pq.read_table(f, columns=_PT_COLS).to_pandas() for f in files], ignore_index=True)
    # identity map (all seasons, for projected starter -> canonical)
    term = pt_all[pt_all["pa_outcome"].notna() & (pt_all["pa_outcome"] != "")]
    m = term[["plate_appearance_id", "batter_id", "pitcher_id"]].merge(fv, on="plate_appearance_id", how="inner")
    uuid_b = dict(zip(m["batter_id"].astype(str), m["batter_canonical_player_uuid"].astype(str)))
    uuid_p = dict(zip(m["pitcher_id"].astype(str), m["pitcher_canonical_player_uuid"].astype(str)))

    _hb("STARTER_MODEL", {})
    starter_rows, app_rows = _starter_rows_and_apps(pt_all)
    games = si.build_starter_games(starter_rows, app_rows)
    games_by_season = {s: [g for g in games if g.season == s] for s in (2021, 2022, 2023, 2024, 2025)}
    dev = [g for s in DEV_SEASONS for g in games_by_season[s]]
    model = si.StarterIdentityModel.fit(dev)
    starter_eval = _evaluate_starter(model, games_by_season)
    # decision: beat the best baseline top-1 in both seasons?
    def beats_baselines():
        for s in SEASONS:
            best_base = max(starter_eval["baselines"][str(s)][bk]["top1Accuracy"] for bk in starter_eval["baselines"][str(s)])
            if starter_eval["bySeason"][str(s)]["top1Accuracy"] <= best_base:
                return False
        return True
    model_decision = "STARTER_IDENTITY_RESEARCH_COMPONENT" if beats_baselines() else "STARTER_IDENTITY_RESEARCH_BASELINE"

    # duration proxy: each pitcher's mean historical BF/start (from S2 parquet target_bfp)
    sta = pd.read_parquet(glob.glob(str(p5e.PART_NS / "objects/sha256/**/starter_duration-fold-2024-predictions.parquet"), recursive=True)[0])
    sta2 = pd.read_parquet(glob.glob(str(p5e.PART_NS / "objects/sha256/**/starter_duration-fold-2025-predictions.parquet"), recursive=True)[0])
    sta_all = pd.concat([sta, sta2], ignore_index=True)
    duration_proxy = sta_all.groupby("canonical_player_uuid")["target_bfp"].mean().to_dict()
    duration_proxy["__median__"] = float(sta_all["target_bfp"].median())
    proj_starters = _projected_starters(model, games_by_season, uuid_p, duration_proxy)
    proj_canon_missing = sum(1 for v in proj_starters.values() if v["canonical"] is None)

    _hb("PREPS", {})
    pt = pt_all[pt_all["season"].isin(SEASONS)]
    preps, skips = p5e._build_preps(pt, uuid_b, uuid_p)
    projections = p5e._load_projections()
    comparable = p5e._comparable(preps, projections)
    if args.limit:
        by = defaultdict(list)
        for p in comparable:
            by[p.season].append(p)
        comparable = [p for s in SEASONS for p in by[s][:args.limit]]
    _hb("COMPARABLE", {"comparable": len(comparable), "skips": skips})

    # Q0 / Q1
    q0 = _simulate_q(comparable, projections, proj_starters, folds, tsampler, resolver, "Q0")
    q1 = _simulate_q(comparable, projections, proj_starters, folds, tsampler, resolver, "Q1")

    by_season = {}
    for s in SEASONS:
        r0 = [r for r in q0 if r["season"] == s]
        r1 = [r for r in q1 if r["season"] == s]
        e0, e1 = _q_eval(r0), _q_eval(r1)
        # correct vs wrong starter segmentation (Q1)
        both_correct = [r for r in r1 if r["startersWrong"] == 0]
        any_wrong = [r for r in r1 if r["startersWrong"] > 0]
        by_season[str(s)] = {
            "Q0": e0, "Q1": e1,
            "delta": p5e._deltas(e0, e1),
            "starterCorrectRate": float(np.mean([1 - r["startersWrong"] / 2.0 for r in r1])),
            "gamesBothCorrect": len(both_correct), "gamesAnyWrong": len(any_wrong),
            "segmentBothCorrect": d5._brier_logloss(both_correct) if both_correct else None,
            "segmentAnyWrong": d5._brier_logloss(any_wrong) if any_wrong else None,
        }

    bootstrap = p5e._bootstrap({"Q0": q0, "Q1": q1}, [("Q0", "Q1")])

    # simulator decision
    def sim_decision():
        mags = []
        for s in SEASONS:
            d = by_season[str(s)]["delta"]
            mags.append(p5e._magnitude(d["winnerBrier"]["relPct"]))
            mags.append(p5e._magnitude(d["totalCrps"]["relPct"]))
        worst = max(mags, key=lambda mm: ["NEGLIGIBLE", "SMALL", "MEANINGFUL", "LARGE", "UNKNOWN"].index(mm) if mm != "UNKNOWN" else -1)
        if worst in ("NEGLIGIBLE", "SMALL"):
            return "STARTER_IDENTITY_PROJECTION_ACCEPTABLE"
        if worst == "MEANINGFUL":
            return "STARTER_IDENTITY_PROJECTION_MATERIAL_DEGRADATION"
        return "STARTER_IDENTITY_PROJECTION_BLOCKING"
    simulator_decision = sim_decision()

    # pregame readiness: all four participation layers projected, still beats generic baseline (P3 did), legal
    q1_beats_generic = all(by_season[str(s)]["Q1"]["winner"]["brier"] < 0.251 for s in SEASONS)
    legal = all(by_season[str(s)]["Q1"]["legality"]["illegal"] == 0 for s in SEASONS)
    pregame_ready = ("PREGAME_RESEARCH_SIMULATOR_READY" if (q1_beats_generic and legal and simulator_decision != "STARTER_IDENTITY_PROJECTION_BLOCKING")
                     else "PREGAME_RESEARCH_SIMULATOR_PARTIAL")

    payload = {
        "schemaVersion": si.STARTER_SCHEMA_VERSION, "runId": run_id, "contractName": si.STARTER_CONTRACT_NAME,
        "researchOnly": True, "datasetAuthority": dataset_authority,
        "d3ModelAuthority": dynamic_state_contract_sha(), "transitionModelSha": TRANSITION_MODEL_SHA,
        "featureContractAuthority": PHASE3_FEATURE_CONTRACT_SHA,
        "devSeasons": list(DEV_SEASONS), "featureNames": list(si.FEATURE_NAMES),
        "starterModel": model.to_dict(), "starterEvaluation": starter_eval,
        "modelDecision": model_decision,
        "simulationsPerGame": SIMS, "comparableGames": {str(s): sum(1 for p in comparable if p.season == s) for s in SEASONS},
        "durationPolicy": "PROJECTED_IDENTITY: actual S2 when starter correct; pitcher mean historical BF/start otherwise (median fallback)",
        "projectedStarterCanonicalMissing": proj_canon_missing,
        "stateFallback": resolver.fallback_summary(),
        "bySeason": by_season, "bootstrap": bootstrap,
        "simulatorDecision": simulator_decision,
        "pregameSimulatorReadiness": pregame_ready,
        "remainingOracleParticipation": {
            "GAME_SCHEDULE_TEAMS_DATE": "MODERATE", "HISTORICAL_SOURCE_POPULATION": "MODERATE",
            "NO_INJURY_SCRATCH_FEED": "MODERATE", "STARTER_IDENTITY": "PROJECTED_NOW",
        },
        "priorities": {
            "bullpen": "BULLPEN_RESEARCH_PRIORITY_HIGH", "prospectiveFeed": "PROSPECTIVE_FEED_READY_FOR_INTEGRATION" if pregame_ready.endswith("READY") else "PROSPECTIVE_FEED_PREMATURE",
            "modelStudioCockpit": "MODEL_STUDIO_COCKPIT_READY_TO_PRIORITIZE",
            "premiumData": "PREMIUM_DATA_MEDIUM", "clustering": "CLUSTERING_LOW", "algorithmTournament": "ALGORITHM_TOURNAMENT_LOW", "e6": "E6_MEDIUM",
        },
        "limitations": [
            "Starter identity predicted from prior-date rotation cadence/rest/workload only; candidate-pool coverage caps top-1 accuracy (~92.5%).",
            "Q1 binds starter duration to the projected identity (actual S2 when correct; pitcher mean historical BF otherwise) — S2 not retrained.",
            "Still uses a historical source population and no injury/scratch or confirmed-lineup feed; not a live pregame forecast.",
            "Winner probability is a diagnostic only; no sportsbook comparison, edge, ROI, or parlays.",
        ],
    }
    written = _write(payload, run_id)
    payload["artifact"] = written
    _hb("DONE", {"runId": run_id, "model": model_decision, "sim": simulator_decision, "ready": pregame_ready, "reused": written["reused"]})
    print(json.dumps({
        "runId": run_id, "modelDecision": model_decision,
        "top1_2024": starter_eval["bySeason"]["2024"]["top1Accuracy"], "top1_2025": starter_eval["bySeason"]["2025"]["top1Accuracy"],
        "Q1_vs_Q0_2024_brierRelPct": by_season["2024"]["delta"]["winnerBrier"]["relPct"],
        "Q1_vs_Q0_2024_crpsRelPct": by_season["2024"]["delta"]["totalCrps"]["relPct"],
        "simulatorDecision": simulator_decision, "pregameReadiness": pregame_ready, "reused": written["reused"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
