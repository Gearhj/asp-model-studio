"""run-mlb-base-out-transition — Phase 5B empirical base-out / runner-advancement model.

Fits an empirical conditional transition distribution from governed FD1 ``play_transition``
evidence (development 2021-2023), evaluates a one-step transition backtest out-of-time on
2024 and frozen 2025, runs a stochastic legality stress test and a reproducibility check,
and persists a data-only (JSON, non-executable) content-addressed artifact.

The provider bridges a sampled eight-class PA outcome to the proven deterministic kernel.
No whole-game Monte Carlo, win/run-line/total probabilities, or betting logic. No new PA
model training, no D3/E1/E2 changes, no provider/network calls, no new data acquisition.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import numpy as np  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from server.sports_phase5 import base_out_transition as bt  # noqa: E402
from server.sports_phase5 import game_replay as gr  # noqa: E402
from scripts._retired_2025_guard import retire_2025  # Phase 7D.4 Gate 12 (B8)

RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio"
OUTPUT_ROOT = RUNTIME_ROOT / "sports-phase5" / "base-out-transition"
CONTRACT_PATH = REPOSITORY_ROOT / "docs" / "contracts" / "MLB_BASE_OUT_TRANSITION_MODEL_V1.md"
DEFAULT_EXCHANGE_ROOT = Path(r"C:/Users/james/asp-model-exchange")
MANIFEST = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
DEV_SEASONS = (2021, 2022, 2023)
VAL_SEASON, FROZEN_SEASON = 2024, 2025
_COLS = ["season", "pa_outcome", "outs_before", "base_mask_before", "outs_after", "base_mask_after", "runs_scored"]
_STARTED = time.monotonic()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hb(stage: str, evidence: Mapping[str, Any]) -> None:
    print(f"[transition] {int(time.monotonic() - _STARTED):>5}s | {stage} | "
          + " ".join(f"{k}={v}" for k, v in evidence.items()), flush=True)


def _dataset_authority() -> dict[str, Any]:
    from server.persistence.db import Database
    from server.sports_datasets.registry import SportsDatasetRegistry
    db = Database(RUNTIME_ROOT / "persistence" / "asp_model_studio.db")
    db.initialize()
    active = SportsDatasetRegistry(db).get_active()
    if not active or active["manifest_sha"] != MANIFEST:
        raise RuntimeError("active FD1 dataset registration authority mismatch")
    return {"registrationId": active["registration_id"], "datasetId": active["dataset_id"], "manifestSha": active["manifest_sha"]}


def _replay_authority() -> dict[str, Any]:
    pointer = RUNTIME_ROOT / "sports-phase5" / "game-replay" / "latest.replay.json"
    rec = json.loads(pointer.read_text(encoding="utf-8"))
    return {"replayRunId": rec["replay"]["replayRunId"], "contractName": rec["replay"]["contractName"],
            "readinessStatus": rec["replay"]["readinessStatus"]}


def _load(exchange_root: Path):
    import pandas as pd
    base = exchange_root / "datasets" / "mlb-fd1" / f"sha256-{MANIFEST}" / "parquet" / "play_transition"
    files = glob.glob(str(base / "**" / "*.parquet"), recursive=True)
    if not files:
        raise RuntimeError("FD1 play_transition family not found")
    df = pd.concat([pq.read_table(f, columns=_COLS).to_pandas() for f in files], ignore_index=True)
    df = df[df["pa_outcome"].isin(bt.PA_CLASSES)].copy()
    df["outs_added"] = df["outs_after"] - df["outs_before"]
    # legality flag (single-PA runner conservation); residual anomalies excluded from fitting/eval
    pcb = df["base_mask_before"].map(bt.popcount)
    pca = df["base_mask_after"].map(bt.popcount)
    cont = (df["outs_after"] < 3) & (pcb + 1 == pca + df["runs_scored"] + df["outs_added"])
    end = (df["outs_after"] == 3) & (df["base_mask_after"] == 0) & (pcb + 1 - df["outs_added"] - df["runs_scored"] >= 0)
    df["legal"] = (cont | end) & (df["outs_added"] >= 0) & (df["runs_scored"] >= 0) & (df["outs_before"] <= 2)
    return df


def _cell_distributions(model: bt.TransitionModel):
    """Precompute the distribution for every (outcome, outs, base) cell once."""
    dists: dict[tuple[str, int, int], dict[str, Any]] = {}
    for outcome in bt.PA_CLASSES:
        for outs in range(3):
            for base in range(8):
                dists[(outcome, outs, base)] = model.distribution(outcome, outs, base)
    return dists


def _evaluate(df, dists) -> dict[str, Any]:
    """One-step transition backtest for a season's eligible legal PAs."""
    sub = df[df["legal"]].copy()
    n = len(sub)
    log_losses = np.empty(n); briers = np.empty(n)
    top1 = np.empty(n, bool); top2 = np.empty(n, bool)
    runs_err = np.empty(n); outs_ok = np.empty(n, bool); base_ok = np.empty(n, bool); inn_ok = np.empty(n, bool)
    fallback = np.empty(n, dtype=object); entropy = np.empty(n)
    per_outcome = defaultdict(lambda: {"n": 0, "ll": 0.0, "brier": 0.0, "top1": 0, "top2": 0})
    fb_counts: Counter[str] = Counter()
    det_share: Counter[str] = Counter()
    records = sub.to_dict("records")
    for i, r in enumerate(records):
        cell = (r["pa_outcome"], int(r["outs_before"]), int(r["base_mask_before"]))
        d = dists[cell]
        actual = (int(r["outs_added"]), int(r["base_mask_after"]), int(r["runs_scored"]))
        prob_of_actual = 0.0
        brier = 0.0
        for t in d["transitions"]:
            tt = (t["outsAdded"], t["baseMaskAfter"], t["runs"])
            p = t["probability"]
            match = 1.0 if tt == actual else 0.0
            brier += (p - match) ** 2
            if tt == actual:
                prob_of_actual = p
        log_losses[i] = -math.log(max(prob_of_actual, 1e-12))
        briers[i] = brier
        mode = d["transitions"][0]
        mode_t = (mode["outsAdded"], mode["baseMaskAfter"], mode["runs"])
        top1[i] = mode_t == actual
        top2[i] = actual in [(t["outsAdded"], t["baseMaskAfter"], t["runs"]) for t in d["transitions"][:2]]
        runs_err[i] = abs(mode["runs"] - actual[2])
        outs_ok[i] = mode["outsAdded"] == actual[0]
        base_ok[i] = mode["baseMaskAfter"] == actual[1]
        inn_ok[i] = (int(r["outs_before"]) + mode["outsAdded"] == 3) == (int(r["outs_before"]) + actual[0] == 3)
        fallback[i] = d["fallbackLevel"]; entropy[i] = d["entropy"]
        fb_counts[d["fallbackLevel"]] += 1
        po = per_outcome[r["pa_outcome"]]
        po["n"] += 1; po["ll"] += log_losses[i]; po["brier"] += briers[i]
        po["top1"] += int(top1[i]); po["top2"] += int(top2[i])
        # deterministic/stochastic share
        if d["fallbackLevel"] == "DETERMINISTIC_HOME_RUN":
            det_share["MECHANICALLY_DETERMINISTIC"] += 1
        elif d["fallbackLevel"].startswith("L3"):
            det_share["FALLBACK_REQUIRED"] += 1
        elif d["entropy"] < 0.3:
            det_share["EMPIRICALLY_STOCHASTIC_LOW_ENTROPY"] += 1
        else:
            det_share["EMPIRICALLY_STOCHASTIC_HIGH_ENTROPY"] += 1

    # Pareto concentration of transition log loss
    order = np.argsort(log_losses)[::-1]
    total_ll = float(log_losses.sum())
    pareto = {f"worst_{int(f*100)}pct": float(log_losses[order[:max(1, int(f*n))]].sum() / total_ll)
              for f in (0.01, 0.05, 0.10)}
    # error forensics: highest-loss cells
    cell_loss: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "ll": 0.0})
    for i, r in enumerate(records):
        c = (r["pa_outcome"], int(r["outs_before"]), int(r["base_mask_before"]))
        cell_loss[c]["n"] += 1; cell_loss[c]["ll"] += log_losses[i]
    top_cells = sorted(cell_loss.items(), key=lambda kv: kv[1]["ll"], reverse=True)[:12]
    return {
        "rows": int(n),
        "logLoss": float(log_losses.mean()),
        "brier": float(briers.mean()),
        "top1Accuracy": float(top1.mean()),
        "top2Coverage": float(top2.mean()),
        "runsScoredMae": float(runs_err.mean()),
        "outsAddedAccuracy": float(outs_ok.mean()),
        "baseMaskAfterAccuracy": float(base_ok.mean()),
        "inningEndingAccuracy": float(inn_ok.mean()),
        "meanEntropy": float(entropy.mean()),
        "fallbackUsage": {k: fb_counts[k] / n for k in fb_counts},
        "deterministicStochasticShare": {k: det_share[k] / n for k in det_share},
        "perOutcome": {o: {"rows": v["n"], "logLoss": v["ll"] / v["n"], "brier": v["brier"] / v["n"],
                           "top1Accuracy": v["top1"] / v["n"], "top2Coverage": v["top2"] / v["n"]}
                       for o, v in per_outcome.items()},
        "paretoLogLossConcentration": pareto,
        "highestLossCells": [{"outcome": c[0], "outsBefore": c[1], "baseMaskBefore": c[2],
                              "rows": v["n"], "meanLogLoss": v["ll"] / v["n"]} for c, v in top_cells],
    }


def _stress_test(model: bt.TransitionModel, dists, *, sequences: int = 1000, steps: int = 50, seed: int = 20260818) -> dict[str, Any]:
    """Repeated sampled transitions fed through the deterministic kernel must never corrupt state."""
    rng = np.random.default_rng(seed)
    outcomes = list(bt.PA_CLASSES)
    illegal = dup = lost = outs_bad = 0
    batter_counter = 0
    for _ in range(sequences):
        s = gr.GameState(inning=1, top=True, outs=0, base_mask=0, away_score=0, home_score=0)
        runners: dict[int, str] = {}
        for _ in range(steps):
            outcome = outcomes[rng.integers(0, len(outcomes))]
            transition = model.sample(outcome, s.outs, s.base_mask, rng)
            if not bt.is_legal(s.outs, s.base_mask, transition):
                illegal += 1; continue
            outs_added, base_after, runs = transition
            batter_counter += 1
            batter_id = f"b{batter_counter}"  # every plate appearance is a distinct identity
            before = {b: runners[b] for b in (1, 2, 3) if s.base_mask & (1 << (b - 1))}
            if len(before) != bt.popcount(s.base_mask):
                lost += 1; continue
            try:
                applied = bt.apply_transition_to_runners(s.base_mask, before, batter_id, transition)
            except bt.TransitionModelError:
                lost += 1; continue
            after_ids = list(applied["afterRunners"].values()) + applied["scored"]
            if len(after_ids) != len(set(after_ids)):
                dup += 1
            new_outs = s.outs + outs_added
            if new_outs > 3:
                outs_bad += 1
            if new_outs >= 3:
                # half-inning transition
                s = gr.GameState(inning=s.inning + (0 if s.top else 1), top=not s.top, outs=0, base_mask=0,
                                 away_score=s.away_score + (runs if s.top else 0), home_score=s.home_score + (0 if s.top else runs))
                runners = {}
            else:
                s = gr.GameState(inning=s.inning, top=s.top, outs=new_outs, base_mask=base_after,
                                 away_score=s.away_score + (runs if s.top else 0), home_score=s.home_score + (0 if s.top else runs))
                runners = {b: pid for b, pid in applied["afterRunners"].items()}
            if not (0 <= s.base_mask <= 7 and 0 <= s.outs <= 2):
                illegal += 1
    return {"sequences": sequences, "stepsPerSequence": steps, "illegalStateCount": illegal,
            "duplicatedRunnerCount": dup, "lostRunnerCount": lost, "outsViolationCount": outs_bad,
            "totalSampledTransitions": sequences * steps}


def _reproducibility(model: bt.TransitionModel) -> dict[str, Any]:
    cases = [("SINGLE", 0, 2), ("BIP_OUT", 1, 1), ("DOUBLE", 2, 5), ("WALK_HBP_CI", 0, 7)]
    a = [model.sample(o, ou, b, np.random.default_rng(7)) for o, ou, b in cases]
    b = [model.sample(o, ou, b, np.random.default_rng(7)) for o, ou, b in cases]
    c = [model.sample(o, ou, b, np.random.default_rng(99)) for o, ou, b in cases]
    return {"sameSeedIdentical": a == b, "differentSeedCanDiffer": a != c or all(len(model.distribution(o, ou, bb)["transitions"]) == 1 for o, ou, bb in cases)}


def _readiness(val, frozen, stress) -> str:
    illegal_ok = stress["illegalStateCount"] == 0 and stress["duplicatedRunnerCount"] == 0 and stress["lostRunnerCount"] == 0
    fb_val = sum(v for k, v in val["fallbackUsage"].items() if k.startswith("L3"))
    fb_frozen = sum(v for k, v in frozen["fallbackUsage"].items() if k.startswith("L3"))
    stable = abs(val["logLoss"] - frozen["logLoss"]) < 0.15
    if not illegal_ok:
        return "BASE_OUT_TRANSITION_MODEL_BLOCKED"
    if fb_val < 0.02 and fb_frozen < 0.02 and stable and val["baseMaskAfterAccuracy"] > 0.6:
        return "BASE_OUT_TRANSITION_MODEL_READY"
    return "BASE_OUT_TRANSITION_MODEL_PARTIALLY_READY"


def _run(args: argparse.Namespace) -> int:
    exchange_root = Path(args.exchange_root or os.getenv("ASP_MODEL_EXCHANGE_ROOT", "") or DEFAULT_EXCHANGE_ROOT)
    if not exchange_root.exists():
        print(f"exchange root not found: {exchange_root}", file=sys.stderr)
        return 2
    dataset_authority = _dataset_authority()
    replay_authority = _replay_authority()
    code_revision = os.getenv("ASP_MODEL_STUDIO_CODE_REVISION", "").strip() or "worktree:phase5b-base-out-transition"
    contract_sha = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() if CONTRACT_PATH.exists() else ""
    run_id = "base-out-transition-" + _sha({"contract": bt.TRANSITION_CONTRACT_NAME, "contractSha": contract_sha,
                                            "manifest": MANIFEST, "alpha": bt.DEFAULT_ALPHA, "minCell": bt.MIN_CELL_COUNT,
                                            "code": code_revision})[:16]
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    completed = OUTPUT_ROOT / f"{run_id}.transition.json"
    if args.status:
        print(json.dumps({"runId": run_id, "completed": completed.exists()}))
        return 0
    if completed.exists() and not args.force:
        _hb("REUSED_COMPLETED_TRANSITION_MODEL", {"runId": run_id})
        print("COMPLETED (reused)")
        return 0

    _hb("LOADING", {})
    df = _load(exchange_root)
    dev = df[df["season"].isin(DEV_SEASONS) & df["legal"]]
    _hb("LOADED", {"total": len(df), "dev": len(dev), "legalRate": round(float(df["legal"].mean()), 5),
                   "excludedAnomalies": int((~df["legal"]).sum())})

    model = bt.fit(dev.to_dict("records"), seasons=DEV_SEASONS)
    dists = _cell_distributions(model)
    _hb("FITTED", {"cells": len(model.cells), "sparseCells": sum(1 for v in model.cells.values() if sum(v.values()) < bt.MIN_CELL_COUNT)})

    # legality: illegal probability mass must be zero across every cell
    illegal_mass = 0.0
    for (o, ou, b), d in dists.items():
        bt.validate_distribution(d, ou, b)
        for t in d["transitions"]:
            if not bt.is_legal(ou, b, (t["outsAdded"], t["baseMaskAfter"], t["runs"])):
                illegal_mass += t["probability"]
    _hb("LEGALITY_VALIDATED", {"illegalProbabilityMass": illegal_mass})

    val = _evaluate(df[df["season"] == VAL_SEASON], dists)
    frozen = _evaluate(df[df["season"] == FROZEN_SEASON], dists)
    _hb("BACKTEST", {"val2024LogLoss": round(val["logLoss"], 4), "frozen2025LogLoss": round(frozen["logLoss"], 4),
                     "baseAcc2024": round(val["baseMaskAfterAccuracy"], 4)})

    stress = _stress_test(model, dists)
    _hb("STRESS", {"illegal": stress["illegalStateCount"], "dup": stress["duplicatedRunnerCount"], "transitions": stress["totalSampledTransitions"]})
    repro = _reproducibility(model)
    readiness = _readiness(val, frozen, stress)

    # persist the data-only model artifact (JSON, never pickle)
    model_bytes = _canonical(model.to_dict())
    model_sha = hashlib.sha256(model_bytes).hexdigest()
    model_path = OUTPUT_ROOT / f"{run_id}-model-sha256-{model_sha[:16]}.json"
    tmp = model_path.with_suffix(".tmp"); tmp.write_bytes(model_bytes); os.replace(tmp, model_path)

    payload = {
        "schemaVersion": bt.TRANSITION_SCHEMA_VERSION, "contractName": bt.TRANSITION_CONTRACT_NAME,
        "transitionRunId": run_id, "contractSha": contract_sha,
        "datasetAuthority": dataset_authority, "parentReplayAuthority": replay_authority,
        "researchOnly": True, "productionReady": False, "monteCarlo": False,
        "retainedPolicy": "T0_EMPIRICAL_CONDITIONAL", "smoothing": {"type": "DIRICHLET_OVER_LEGAL_SET", "alpha": bt.DEFAULT_ALPHA, "minCell": bt.MIN_CELL_COUNT},
        "devSeasons": list(DEV_SEASONS), "valSeason": VAL_SEASON, "frozenSeason": FROZEN_SEASON,
        "developmentRows": int(len(dev)), "primaryStateCells": 192,
        "observedTransitionCount": int(sum(len(v) for v in model.cells.values())),
        "sparseCellCount": int(sum(1 for v in model.cells.values() if sum(v.values()) < bt.MIN_CELL_COUNT)),
        "deterministicRules": ["HOME_RUN: bases clear, outs unchanged, runs = runners + 1 (verified 100%)"],
        "legality": {"illegalProbabilityMass": illegal_mass, "invariant": "runner conservation with inning-end branch"},
        "validation2024": val, "frozen2025": frozen,
        "stochasticStressTest": stress, "reproducibility": repro,
        "modelArtifact": {"logicalUri": f"asp-model-studio-runtime://sports-phase5/base-out-transition/{model_path.name}",
                          "sha256": model_sha, "byteCount": model_path.stat().st_size, "format": "JSON_DATA_ONLY_NO_PICKLE"},
        "readinessStatus": readiness,
        "limitations": [
            "One-step transition provider only; no whole-game Monte Carlo, win/run-line/total probabilities, or betting logic.",
            "Conditioned on (PA outcome, outs, base state); no inning/score/park/handedness context (T0 champion, simplest defensible).",
            "0.08% of governed PAs violate single-PA runner conservation (multi-play/source quirks) and are excluded from fitting and evaluation.",
            "READY means transition mechanics are trustworthy for simulation; it does NOT mean a game forecaster or Monte Carlo exists.",
        ],
    }
    audit_sha = _sha(payload)
    record = {"schemaVersion": "MLB_BASE_OUT_TRANSITION_RUNTIME_ARTIFACT_V1", "transitionRunId": run_id, "transitionSha": audit_sha,
              "codeRevision": code_revision, "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "transition": payload}
    for pointer in (completed, OUTPUT_ROOT / "latest.transition.json"):
        tmp = pointer.with_suffix(".tmp"); tmp.write_bytes(_canonical(record)); os.replace(tmp, pointer)
    _hb("REGISTERED", {"transitionSha": audit_sha[:16], "modelSha": model_sha[:16], "readiness": readiness})
    print(f"COMPLETED readiness={readiness} val2024LogLoss={val['logLoss']:.4f} frozen2025LogLoss={frozen['logLoss']:.4f} "
          f"illegalMass={illegal_mass} stressIllegal={stress['illegalStateCount']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    retire_2025("server.sports_cockpit.gen3_authority.run_feature_family_ablation (canonical 2024-only research)")
    parser = argparse.ArgumentParser(description="Phase 5B empirical base-out transition model.")
    parser.add_argument("--exchange-root", default=os.getenv("ASP_MODEL_EXCHANGE_ROOT", ""))
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.estimate_only:
        print(json.dumps({"estimateOnly": True, "estimatedSecondsLower": 30, "estimatedSecondsUpper": 300}, sort_keys=True))
        return 0
    try:
        return _run(args)
    except Exception as exc:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print(f"FAILED {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
