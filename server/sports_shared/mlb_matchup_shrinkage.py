"""Separate point-score research; no acquisition, forecast writer or scheduler.

The retained anchor has independent winner probabilities and score means, not a
joint predictive population. Corrections here never alter its probabilities.
Historical reconstruction is not proof of historical publication availability.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
import io
import json
import itertools
from pathlib import Path
import zipfile

import numpy as np
from sklearn.metrics import roc_auc_score
from .show_preview import canonical, digest, immutable, physical

CONFIG = "MLB_MATCHUP_STARTER_SHRINKAGE_CHALLENGER_V1"
DESIGN_SHA = "9a99a40aa627ce9c1b39ca4bee0d3455819b8eba26c33216c8405896e1a0bc4a"
ROOT = Path(__file__).resolve().parents[2]
ANCHOR = ROOT / "outputs/mlb-show-preview-feasibility-v1"


def checked_design(out):
    raw = (Path(out) / "FROZEN_DESIGN.json").read_bytes()
    if digest(raw) != DESIGN_SHA:
        raise ValueError("Frozen design mismatch")
    d = json.loads(raw)
    for ref in d["sourceRefs"]:
        if physical(ref["path"]) != {k: ref[k] for k in ("path", "sha256", "bytes")}:
            raise ValueError("Bound source changed: " + ref["path"])
    return d


def load_anchor(years):
    if not set(years) <= {2022, 2023, 2024}:
        raise ValueError("Only registered historical seasons")
    rows = json.loads((ANCHOR / "population.json").read_bytes())
    # Identity/season gate before selecting any outcomes or opening raw archives.
    if any(r["season"] not in range(2019, 2025) for r in rows):
        raise ValueError("Protected season rejected")
    meta = {r["id"]: r for r in rows}
    pred = json.loads((ANCHOR / "predictions.json").read_bytes())
    if any(p["season"] not in (2022, 2023, 2024) for p in pred):
        raise ValueError("Unexpected prediction population")
    pred = [p for p in pred if p["season"] in years]
    targets = [meta[p["gameId"]] for p in pred]
    forecasts = np.array([[p["candidate"][k] for k in ("pHome", "expectedAway", "expectedHome")] for p in pred])
    for p, r in zip(pred, targets):
        if [p["actual"][s] for s in ("away", "home")] != [r[s + "_score"] for s in ("away", "home")]:
            raise ValueError("Anchor orientation or outcome binding differs")
    # Training identity inspection; no refitting or numerical regeneration.
    import joblib
    for year in years:
        m = joblib.load(ANCHOR / f"model-trained-through-{year-1}.joblib")
        if any(meta[k]["season"] >= year for k in m["trainingTargetIds"]):
            raise ValueError("Anchor is not season-forward")
    return rows, targets, forecasts


def per_game(rows, forecasts):
    y = np.array([[r["away_score"], r["home_score"]] for r in rows], dtype=float)
    mu = forecasts[:, 1:]
    if np.any(mu <= 0) or not np.isfinite(forecasts).all():
        raise ValueError("Invalid forecast means")
    p = forecasts[:, 0]
    if np.any((p <= 0) | (p >= 1)):
        raise ValueError("Non-interior winner probability")
    win = (y[:, 1] > y[:, 0]).astype(float)
    term = np.zeros_like(y)
    nz = y > 0
    term[nz] = y[nz] * np.log(y[nz] / mu[nz])
    dev = 2 * (term - y + mu)
    return np.column_stack((-(win*np.log(p)+(1-win)*np.log1p(-p)), (p-win)**2,
                            np.abs(mu[:, 0]-y[:, 0]), np.abs(mu[:, 1]-y[:, 1]),
                            np.abs(mu.sum(axis=1)-y.sum(axis=1)), dev.mean(axis=1),
                            mu[:, 0]-y[:, 0], mu[:, 1]-y[:, 1], mu.sum(axis=1)-y.sum(axis=1)))


METRICS = ("logLoss", "binaryBrier", "awayMAE", "homeMAE", "totalMAE", "poissonDeviance",
           "awayBias", "homeBias", "totalBias")


def metrics(rows, forecasts):
    if not rows:
        return {"n": 0, "available": False}
    score = per_game(rows, forecasts)
    p = forecasts[:, 0]
    y = np.array([r["home_score"] > r["away_score"] for r in rows])
    rates = []
    for j in range(10):
        take = (p >= j/10) & (p < (j+1)/10)
        if take.any():
            rates.append({"bin": j, "n": int(take.sum()), "pHome": float(p[take].mean()), "homeWinRate": float(y[take].mean())})
    return {"n": len(rows), **dict(zip(METRICS, score.mean(axis=0).tolist())),
            "auc": float(roc_auc_score(y, p)) if len(set(y)) == 2 else None,
            "accuracy": float(((p >= .5) == y).mean()), "winnerCalibration": rates,
            "expectedAway": float(forecasts[:, 1].mean()), "expectedHome": float(forecasts[:, 2].mean()),
            "observedAway": float(np.mean([r["away_score"] for r in rows])),
            "observedHome": float(np.mean([r["home_score"] for r in rows])),
            "predictionCoverage": 1.0, "intervalCoverage50_80_90": None, "intervalWidth50_80_90": None,
            "crps": None, "energyScore": None, "distributionUnavailableReason": "Anchor retains independent point means and Logistic probability, no joint population"}


def regions(forecasts, thresholds):
    means = forecasts[:, 1:]
    total = means.sum(axis=1)
    lo, hi = thresholds["riskBin"]
    return {"all": np.ones(len(forecasts), dtype=bool),
            "teamAbove7": means.max(axis=1) > 7,
            "totalAbove12": total > 12,
            "upperTeamDecile": means.max(axis=1) >= thresholds["team90"],
            "upperTotalDecile": total >= thresholds["total90"],
            "positiveResidualRiskBin": (total >= lo) & (total < (float("inf") if hi is None else hi)),
            "homeFavorite": forecasts[:, 0] >= .5,
            "awayFavorite": forecasts[:, 0] < .5}


def slices(rows, forecasts, thresholds, parks=None, reference_forecasts=None):
    masks = regions(forecasts if reference_forecasts is None else reference_forecasts, thresholds)
    masks.update({"season_"+str(y): np.array([r["season"] == y for r in rows]) for y in sorted({r["season"] for r in rows})})
    masks.update({"month_"+m: np.array([r["date"][:7] == m for r in rows]) for m in sorted({r["date"][:7] for r in rows})})
    if parks:
        masks.update({"park_"+p: np.array([parks[r["id"]] == p for r in rows]) for p in sorted({parks[r["id"]] for r in rows})})
    return {k: {"frequency": float(mask.mean()), **metrics([r for r, t in zip(rows, mask) if t], forecasts[mask])} for k, mask in masks.items()}


def uncertainty(rows, differences, mask=None):
    if mask is not None:
        rows = [r for r, take in zip(rows, mask) if take]
        differences = differences[mask]
    if not rows:
        return {"n": 0, "available": False}
    weeks = [date.fromisoformat(r["date"]).isocalendar()[:2] for r in rows]
    unique = sorted(set(weeks))
    blocks = [differences[[i for i, w in enumerate(weeks) if w == k]] for k in unique]
    rng = np.random.default_rng(20260916)
    sims = np.array([np.concatenate([blocks[j] for j in rng.integers(0, len(blocks), len(blocks))]).mean(axis=0) for _ in range(1000)])
    return {"n": len(rows), "blocks": len(blocks), "unit": "ISO calendar week; games intact", "replicates": 1000,
            "candidateMinusBaseline": {k: {"mean": float(differences[:, i].mean()), "lower95": float(np.quantile(sims[:, i], .025)),
                                          "upper95": float(np.quantile(sims[:, i], .975))} for i, k in enumerate(METRICS)}}


def development_diagnosis(out):
    checked_design(out)
    _, rows, f = load_anchor([2022, 2023])
    total = f[:, 1:].sum(axis=1)
    bins = [(0, 8), (8, 9), (9, 10), (10, 12), (12, None)]
    risk = []
    for lo, hi in bins:
        mask = (total >= lo) & (total < (hi or np.inf))
        r = metrics([r for r, take in zip(rows, mask) if take], f[mask])
        risk.append({"bin": [lo, hi], **r})
    eligible = [r for r in risk if r["n"] >= 100]
    chosen = max(eligible, key=lambda r: r["totalBias"])
    thresholds = {"team90": float(np.quantile(f[:, 1:], .9)), "total90": float(np.quantile(total, .9)),
                  "riskBin": chosen["bin"], "riskBinBias": chosen["totalBias"], "riskPositive": chosen["totalBias"] > 0}
    result = {"designSha256": DESIGN_SHA, "seasons": [2022, 2023], "thresholds": thresholds,
              "maximumTeamMean": float(f[:, 1:].max()), "maximumTotalMean": float(total.max()),
              "frozenTotalBins": risk, "slices": slices(rows, f, thresholds),
              "tailAction": "NO_HARD_CAP_NO_TAIL_STABILIZER; first assess actual calibration, preserve every prediction"}
    immutable(Path(out)/"DEVELOPMENT_DIAGNOSIS.json", canonical(result))
    return result


def park_metadata(history):
    """Only the already admitted 2019-24 archives; select identity/park fields.

Never extract target starting pitchers or batting orders. Retained venue is a
reconstruction, not proof a historical schedule revision was known at cutoff.
"""
    index = json.loads((ANCHOR/"source-index.json").read_bytes())
    admitted = {r["id"] for r in history}
    parks, refs = {}, []
    for ref in index["sourceFiles"]:
        year = ref.get("season")
        if year is None:
            continue
        if year not in range(2019, 2025):
            raise ValueError("Protected archive rejected before open")
        p = Path(ref["path"])
        b = p.read_bytes()
        if len(b) != ref["bytes"] or digest(b) != ref["sha256"]:
            raise ValueError("Retrosheet archive changed")
        refs.append(ref)
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            for f in csv.reader(io.StringIO(z.read(f"gl{year}.txt").decode("latin-1"))):
                if len(f) != 161 or int(f[0][:4]) != year:
                    raise ValueError("Archive identity schema differs")
                gid = f[6]+f[0]+f[1]
                if gid in admitted:
                    parks[gid] = f[16]
    if set(parks) != admitted:
        raise ValueError("Incomplete park identity projection")
    return parks, refs


def donor_pools(history, targets, parks):
    pairs = {}
    for r in history:
        pairs.setdefault(tuple(sorted((r["away"], r["home"]))), []).append(r)
    result = []
    for target in targets:
        today = date.fromisoformat(target["date"])
        boundary = (today-timedelta(days=1)).isoformat()
        pool = [r for r in pairs[tuple(sorted((target["away"], target["home"])))]
                if r["completion_date"] < boundary and (today-date.fromisoformat(r["completion_date"])).days <= 730]
        pool.sort(key=lambda r: (r["completion_date"], r["id"]))
        pool = pool[-12:]
        if any(r["id"] == target["id"] for r in pool):
            raise ValueError("Target included in donor pool")
        result.append({"ids": [r["id"] for r in pool],
                       "completionDates": [r["completion_date"] for r in pool],
                       "ages": np.array([(today-date.fromisoformat(r["completion_date"])).days for r in pool]),
                       "samePark": np.array([parks[r["id"]] == parks[target["id"]] for r in pool]),
                       "runs": np.array([[r["away_score"] if r["away"] == target[side] else r["home_score"] for side in ("away", "home")] for r in pool]).reshape(-1, 2)})
    return result


def h2h_forecast(baseline, pools, config):
    """Pseudo-observation shrinkage, with an overdispersion uncertainty penalty.

No winner conversion from means, no score clipping, no hidden default history.
Each unsupported game is copied bit-for-bit at the numpy-value level.
"""
    forecast = baseline.copy()
    audits = []
    for i, (b, pool) in enumerate(zip(baseline, pools)):
        idx = np.flatnonzero(pool["ages"] <= min(730, 2*config["halfLifeDays"]))[-config["window"]:]
        n = len(idx)
        detail = {"count": n, "availableMeetingsCapped12": len(pool["ids"]), "supported": False,
                  "weights": [0.0, 0.0], "donorIds": [pool["ids"][j] for j in idx],
                  "donorCompletionDates": [pool["completionDates"][j] for j in idx]}
        if n >= config["minimumCount"]:
            raw = np.exp2(-pool["ages"][idx]/config["halfLifeDays"])
            raw *= np.where(pool["samePark"][idx], 1.0, config["sameParkOnlyWeight"])
            runs = pool["runs"][idx]
            rate = np.average(runs, weights=raw, axis=0)
            variance = np.average((runs-rate)**2, weights=raw, axis=0)
            dispersion = np.maximum(1., variance/np.maximum(rate, 1e-12))
            weight = raw.sum()/(raw.sum()+config["priorStrength"]*dispersion)
            forecast[i, 1:] = b[1:] + weight*(rate-b[1:])
            detail.update(supported=True, weights=weight.tolist(), historicalMeans=rate.tolist(),
                          uncertaintyPenalty=dispersion.tolist(), decayedSupport=float(raw.sum()))
        audits.append(detail)
    if not np.array_equal(forecast[:, 0], baseline[:, 0]):
        raise ValueError("Winner probabilities changed")
    unsupported = np.array([not a["supported"] for a in audits])
    if not np.array_equal(forecast[unsupported], baseline[unsupported]):
        raise ValueError("Fallback is not exact")
    return forecast, audits


def starter_forecast(baseline, targets, bindings=None):
    """Fail closed until a chronologically trained starter component exists.

FD1 actual starter targets explicitly cannot certify pregame announcements.
Do not smuggle those target identities into a day-before model. Retain a real
fallback arm, not a synthetic success. Prior charged runs/outs/BF are available
in the source schema but neither active-pitcher runs nor a certified target
assignment can be inferred from that fact.
"""
    if bindings:
        raise ValueError("NO_DEVELOPMENT_SELECTED_STARTER_PARAMETERS_OR_CERTIFIED_TARGET_COHORT")
    return baseline.copy(), [{"gameId": r["id"], "supported": False, "weight": 0.0,
                             "reason": "NO_PRE_CUTOFF_TARGET_STARTER_IDENTITY"} for r in targets]


def support_summary(audits):
    values = [a["availableMeetingsCapped12"] for a in audits]
    return {"n": len(values), "zero": sum(v == 0 for v in values), "oneToThree": sum(1 <= v <= 3 for v in values),
            "fourToSeven": sum(4 <= v <= 7 for v in values), "eightToTwelve": sum(8 <= v <= 12 for v in values),
            "definition": "up to 12 prior completed meetings in 730 days, before D-1; counts before selected shorter age/window rule",
            "h2hActuallyApplied": sum(a["supported"] for a in audits), "adequateCertifiedExactStarterHistory": 0,
            "starterHistoryQualification": "Zero eligible target-starter bindings, not a claim that no historical pitcher records exist"}


def select_development(out):
    out = Path(out)
    design = checked_design(out)
    diagnosis = json.loads((out/"DEVELOPMENT_DIAGNOSIS.json").read_bytes())
    history, rows, baseline = load_anchor([2022, 2023])
    parks, refs = park_metadata(history)
    pools = donor_pools(history, rows, parks)
    grid = design["candidateGrid"]
    keys = sorted(grid)
    results = []
    for values in itertools.product(*(grid[k] for k in keys)):
        config = dict(zip(keys, values))
        f, audits = h2h_forecast(baseline, pools, config)
        results.append({"config": config, "metrics": metrics(rows, f),
                        "seasons": {str(y): metrics([r for r in rows if r["season"] == y], f[[r["season"] == y for r in rows]]) for y in (2022, 2023)},
                        "support": support_summary(audits)})
    results.sort(key=lambda r: (r["metrics"]["poissonDeviance"], canonical(r["config"])))
    selected = results[0]
    f, audits = h2h_forecast(baseline, pools, selected["config"])
    selection = {"schema": "MLB_MATCHUP_STARTER_SHRINKAGE_SELECTION_V1", "designSha256": DESIGN_SHA,
                 "diagnosis": physical(out/"DEVELOPMENT_DIAGNOSIS.json"), "trainingSeasons": [2022, 2023],
                 "selectedH2h": selected, "allCandidatesIncludingNegative": results,
                 "zeroCorrectionBaseline": metrics(rows, baseline),
                 "starterSelection": "UNAVAILABLE: no certified historical target assignment; parameters not invented",
                 "tailStabilizer": "NOT_TESTED: no runaway means; no cosmetic cap",
                 "thresholds": diagnosis["thresholds"], "sourceRefs": refs,
                 "selectedArmSlices": slices(rows, f, diagnosis["thresholds"], parks),
                 "baselineSlices": slices(rows, baseline, diagnosis["thresholds"], parks),
                 "assessmentNotYetRun": True}
    immutable(out/"CANDIDATE_SELECTION.json", canonical(selection))
    return selection


def assess(out):
    out = Path(out)
    checked_design(out)
    selection_path = out/"CANDIDATE_SELECTION.json"
    if not selection_path.exists():
        raise ValueError("Selection must be frozen before later assessment")
    selection = json.loads(selection_path.read_bytes())
    history, rows, baseline = load_anchor([2024])
    parks, _ = park_metadata(history)
    pools = donor_pools(history, rows, parks)
    h2h, audits = h2h_forecast(baseline, pools, selection["selectedH2h"]["config"])
    starter, sa = starter_forecast(baseline, rows)
    # Only one supported signal: combined is exactly H2H, not double counted.
    arms = {"baseline": baseline, "h2h_only": h2h, "starter_opponent_only": starter, "combined": h2h.copy()}
    comparisons = {}
    baseline_scores = per_game(rows, baseline)
    masks = regions(baseline, selection["thresholds"])
    for name, f in arms.items():
        comparisons[name] = {"metrics": metrics(rows, f), "slices": slices(rows, f, selection["thresholds"], parks, baseline)}
        if name != "baseline":
            comparisons[name]["pairedWeekUncertainty"] = uncertainty(rows, per_game(rows, f)-baseline_scores)
            comparisons[name]["tailUncertainty"] = {k: uncertainty(rows, per_game(rows, f)-baseline_scores, masks[k]) for k in ("upperTeamDecile", "upperTotalDecile", "positiveResidualRiskBin")}
            # Assessment regions are anchored on original predictions, never moved
            # to change membership after the intervention.
            comparisons[name]["fixedAnchorTailMetrics"] = {k: metrics([r for r, take in zip(rows, mask) if take], f[mask]) for k, mask in masks.items()}
    delta = comparisons["h2h_only"]["pairedWeekUncertainty"]["candidateMinusBaseline"]
    dev = selection["selectedH2h"]["seasons"]
    devbase = selection["baselineSlices"]
    tail_guard = all(comparisons["h2h_only"]["fixedAnchorTailMetrics"][k]["poissonDeviance"] - comparisons["baseline"]["slices"][k]["poissonDeviance"] <= .05
                     for k in ("upperTeamDecile", "upperTotalDecile", "positiveResidualRiskBin") if comparisons["baseline"]["slices"][k]["n"] >= 100)
    gate = {"atLeast2000Games": len(rows) >= 2000, "devianceImprovementAtLeastPoint01": delta["poissonDeviance"]["mean"] <= -.01,
            "pairedWeek95UpperBelowZero": delta["poissonDeviance"]["upper95"] < 0,
            "bothDevelopmentSeasonsImprove": all(dev[str(y)]["poissonDeviance"] < devbase["season_"+str(y)]["poissonDeviance"] for y in (2022, 2023)),
            "totalMAEHarmAtMostPoint02": delta["totalMAE"]["mean"] <= .02,
            "teamMAEHarmAtMostPoint01": max(delta["awayMAE"]["mean"], delta["homeMAE"]["mean"]) <= .01,
            "noMaterialTailHarm": tail_guard}
    decision = "RESEARCH_ONLY_PROMISING" if all(gate.values()) else "RETAIN_BASELINE"
    forecasts = [{"gameId": r["id"], "season": r["season"], "date": r["date"], "actual": [r["away_score"], r["home_score"]],
                  "arms": {name: f[i].tolist() for name, f in arms.items()}, "h2h": audits[i], "starter": sa[i]}
                 for i, r in enumerate(rows)]
    immutable(out/"assessment-predictions.json", canonical(forecasts))
    report = {"schema": "MLB_MATCHUP_STARTER_SHRINKAGE_ASSESSMENT_V1", "configuration": CONFIG,
              "designSha256": DESIGN_SHA, "selection": physical(selection_path),
              "role": "Reused 2024 historical Validation; not untouched confirmation or certified historical forecast timing",
              "population": {"historySeasons": list(range(2019, 2025)), "historyGames": len(history), "developmentGames": selection["zeroCorrectionBaseline"]["n"],
                             "assessmentGames": len(rows), "assessmentIdsSha256": digest(canonical([r["id"] for r in rows])), "protectedSeasons": []},
              "comparisons": comparisons, "support": support_summary(audits), "gate": gate, "decision": decision,
              "starterResearchStatus": "NOT_ESTIMABLE_ON_ELIGIBLE_TARGET_BINDINGS; fallback is not starter execution",
              "winnerProbabilityChanges": 0, "winnerPickChanges": 0,
              "metricDefinitions": {"brier": "mean((pHome - homeWin)^2), range 0..1", "bias": "predicted minus actual runs",
                                    "deviance": "mean across away/home team observations of 2*(y*log(y/mu)-y+mu), 0log0=0; proper mean count score, no Poisson distribution asserted",
                                    "unavailable": "No retained joint population: CRPS/energy and 50/80/90 interval coverage/width null"},
              "predictions": physical(out/"assessment-predictions.json"), "newForecastsPublished": 0, "promotion": False,
              "providerCalls": 0, "providerBytes": 0, "costUsd": 0, "aispWrites": 0}
    immutable(out/"ASSESSMENT.json", canonical(report))
    return report
