"""Fit one frozen lagged-QB residual configuration, then assess it chronologically.

Production M1 models, sources, features, and publishers are never mutated.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_nfl_m1.distributions import PairedResidualAuthority
from server.sports_nfl_m1.metrics import empirical_crps
from server.sports_nfl_m1.overnight_lab import _loss_vector, _probabilities
from server.sports_nfl_m1.research_benchmarks import block_interval
from server.sports_current_statcast.mlb_starter_duration_paired_scoring import joint_energy_score
from server.sports_nfl_m1.qb_context_residual_sampler import fit_conditioning, authority_from_config, simulate_comparison

OUT = ROOT / "outputs/nfl-m1-qb-context-residual-v1"
DECLARATION_SHA = "a39117694917024692a7a31f4c643a6f267da25245a5157f962f7729b8a6c72d"
LOSS_KEYS = ("energy", "logLoss", "brierSum", "homeCRPS", "awayCRPS", "totalCRPS", "marginCRPS")


def utc():
    return datetime.now(timezone.utc).isoformat()


def ref(path):
    path = Path(path)
    b = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}


def verify(r):
    b = Path(r["path"]).read_bytes()
    assert hashlib.sha256(b).hexdigest() == r["sha256"] and len(b) == r["bytes"]
    return b


def put(name, data):
    raw = data if isinstance(data, bytes) else (json.dumps(data, indent=2, sort_keys=True, allow_nan=False)+"\n").encode()
    path = OUT/"objects/sha256"/hashlib.sha256(raw).hexdigest()/name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw
    else:
        path.write_bytes(raw)
    return ref(path)


def pointer(name, descriptor):
    (OUT/name).write_bytes((json.dumps(descriptor, indent=2)+"\n").encode())


def joined(data_path, contexts_path, seasons):
    frame = pd.read_parquet(data_path)
    contexts = pd.read_parquet(contexts_path)
    assert set(frame.season.unique()) == set(seasons)
    assert not frame.canonical_game_id.duplicated().any() and not contexts.canonical_game_id.duplicated().any()
    columns = ["canonical_game_id", "qb_context_group"]
    result = frame.merge(contexts[columns], on="canonical_game_id", how="left", validate="one_to_one")
    assert len(result) == len(frame) and result.qb_context_group.notna().all()
    return result.sort_values(["season", "game_date", "canonical_game_id"], kind="stable").reset_index(drop=True)


def fit(args):
    declaration = ref(OUT/"declaration.json")
    assert declaration["sha256"] == DECLARATION_SHA
    source = json.loads(Path(args.source_receipt).read_bytes())
    context_source = json.loads(Path(args.context_receipt).read_bytes())
    assert ref(args.data)["sha256"] == source["data"]["sha256"]
    assert ref(args.contexts)["sha256"] == context_source["artifacts"]["contexts.parquet"]["sha256"]
    assert source["declaration"]["sha256"] == context_source["declaration"]["sha256"] == DECLARATION_SHA
    frame = joined(args.data, args.contexts, (2020, 2021, 2022))
    assert (frame.training_end_season < frame.season).all() and len(frame) == 838
    bank = PairedResidualAuthority.fit(actual_home=frame.actual_home_points, actual_away=frame.actual_away_points,
        predicted_home=frame.predicted_home_points, predicted_away=frame.predicted_away_points,
        row_ids=frame.canonical_game_id.tolist(), row_dates=frame.game_date.tolist(), training_end=str(pd.to_datetime(frame.game_date).max().date()))
    config = fit_conditioning(residual_authority=bank, donor_contexts=frame.qb_context_group.tolist(), declaration_sha256=DECLARATION_SHA)
    result = put("fitted-config.json", config)
    pointer("fitted-config.json", result)
    receipt = {"fittedConfig": result, "frozenAtUtc": config["frozenAtUtc"], "declaration": declaration,
        "chronologicalDonors": ref(args.data), "laggedContexts": ref(args.contexts), "sourceReceipt": ref(args.source_receipt),
        "contextReceipt": ref(args.context_receipt), "fitCode": ref(Path(__file__)),
        "samplerCode": ref(ROOT/"server/sports_nfl_m1/qb_context_residual_sampler.py"),
        "contextCode": ref(ROOT/"server/sports_nfl_m1/qb_usage_context.py"),
        "assessmentOutcomesOpened": False, "productionModelsChanged": False,
        "historicalQualification": "Reused Development; prior model selection and reconstructed historical source vintages remain qualified.",
        "randomNumberClarification": "Existing class is CommonRandomNumbers. Its unchanged matrix maker is called per game with documented SHA256-derived game seed; same variates A/B. No class named SimulationRandoms is used."}
    pointer("fit-receipt.json", put("fit-receipt.json", receipt))
    print(json.dumps({"fittedConfig": result, "donors": len(frame), "assessmentOutcomesOpened": False}, indent=2), flush=True)


def score_game(h, a, probabilities, actual_home, actual_away):
    h, a = np.asarray(h, float), np.asarray(a, float)
    actuals = {"home": actual_home, "away": actual_away, "total": actual_home+actual_away, "margin": actual_home-actual_away}
    samples = {"home": h, "away": a, "total": h+a, "margin": h-a}
    truth = 2 if actual_home > actual_away else 0 if actual_home < actual_away else 1
    result = {"energy": joint_energy_score(h, a, (actual_home, actual_away)),
        "logLoss": float(_loss_vector(np.asarray([probabilities]), np.asarray([truth]))[0]),
        "brierSum": float(np.sum((probabilities-np.eye(3)[truth])**2)),
        "rawHomeProbability": float(np.mean(h>a)), "rawAwayProbability": float(np.mean(a>h)), "rawTieProbability": float(np.mean(a==h)),
        "homeAwayCovariance": float(np.cov(h, a, ddof=0)[0, 1]), "homeAwayCorrelation": float(np.corrcoef(h, a)[0, 1]),
        "totalAtLeast60": float(np.mean(h+a >= 60)), "homeAtMost10": float(np.mean(h <= 10)),
        "awayAtMost10": float(np.mean(a <= 10)), "absoluteMarginAtLeast21": float(np.mean(abs(h-a) >= 21))}
    for name, values in samples.items():
        result[name+"CRPS"] = empirical_crps(values, actuals[name])
        result[name+"Mean"] = float(values.mean())
        result[name+"Variance"] = float(values.var())
        result[name+"AbsoluteError"] = abs(float(values.mean())-actuals[name])
        for level in (80, 90):
            tail = (1-level/100)/2
            lo, hi = np.quantile(values, [tail, 1-tail])
            result[f"{name}Coverage{level}"] = int(lo <= actuals[name] <= hi)
            result[f"{name}Width{level}"] = float(hi-lo)
    return result


def describe(frame):
    result = {"games": len(frame), "supportedGames": int(frame.supported.sum()), "fallbackGames": int((~frame.supported).sum()),
        "meanESS": float(frame.effectiveSampleSize.mean()), "meanDonorSupport": float(frame.localDonors.mean()),
        "baseline": {}, "candidate": {}, "candidateMinusBaseline": {}}
    metric_names = [k[2:] for k in frame.columns if k.startswith("A_")]
    for key in metric_names:
        result["baseline"][key] = float(frame["A_"+key].mean())
        result["candidate"][key] = float(frame["B_"+key].mean())
        result["candidateMinusBaseline"][key] = float((frame["B_"+key]-frame["A_"+key]).mean())
    result["pairedBlockIntervals"] = {k: block_interval((frame["B_"+k]-frame["A_"+k]).to_numpy(), frame) for k in LOSS_KEYS}
    return result


def assess(args):
    cfg_ref = json.loads((OUT/"fitted-config.json").read_bytes())
    cfg = json.loads(verify(cfg_ref))
    fit_receipt_ref = json.loads((OUT/"fit-receipt.json").read_bytes())
    fit_receipt = json.loads(verify(fit_receipt_ref))
    assert fit_receipt["fittedConfig"] == cfg_ref
    assert cfg["declarationSha256"] == DECLARATION_SHA and ref(OUT/"declaration.json")["sha256"] == DECLARATION_SHA
    for key in ("chronologicalDonors", "laggedContexts", "sourceReceipt", "contextReceipt", "samplerCode", "contextCode"):
        verify(fit_receipt[key])
    # The phase-specific builder has admitted assessment columns only after this frozen configuration.
    source = json.loads(Path(args.source_receipt).read_bytes())
    assert args.contexts.resolve() == Path(fit_receipt["laggedContexts"]["path"]).resolve()
    assert source["fittedSamplerConfiguration"]["sha256"] == cfg_ref["sha256"]
    assert source["data"]["sha256"] == ref(args.data)["sha256"]
    assert datetime.fromisoformat(source["outcomeColumnsOpenedAtUtc"].replace("Z", "+00:00")) >= datetime.fromisoformat(cfg["frozenAtUtc"])
    opened_at = utc()
    frame = joined(args.data, args.contexts, (2023, 2024))
    assert (frame.training_end_season < frame.season).all() and len(frame) == 570
    bank = authority_from_config(cfg)
    run = simulate_comparison(predicted_home_mean=frame.predicted_home_points.to_numpy(), predicted_away_mean=frame.predicted_away_points.to_numpy(),
        target_contexts=frame.qb_context_group.tolist(), target_game_ids=frame.canonical_game_id.tolist(), target_game_dates=frame.game_date.tolist(),
        residual_authority=bank, fitted_config=cfg, draws=10000, seed=731001)
    pa, pb = _probabilities(run.baseline), _probabilities(run.candidate)
    rows = []
    for i, r in enumerate(frame.itertuples(index=False)):
        d = run.diagnostics[i]
        row = {"canonical_game_id": r.canonical_game_id, "season": int(r.season), "week": int(r.week), "game_date": str(r.game_date),
            "context": r.qb_context_group, "actualHome": float(r.actual_home_points), "actualAway": float(r.actual_away_points),
            "pointModelHome": float(r.predicted_home_points), "pointModelAway": float(r.predicted_away_points),
            "supported": d["supportedConditioning"], "localDonors": d["localDonorCount"], "effectiveSampleSize": d["effectiveSampleSize"], "status": d["status"]}
        for prefix, sim, probabilities in (("A", run.baseline, pa), ("B", run.candidate, pb)):
            metrics = score_game(sim.home[i], sim.away[i], probabilities[i], r.actual_home_points, r.actual_away_points)
            row.update({prefix+"_"+k: v for k, v in metrics.items()})
        if not row["supported"]:
            assert np.array_equal(run.baseline.home[i], run.candidate.home[i]) and np.array_equal(run.baseline.away[i], run.candidate.away[i])
        rows.append(row)
        if (i+1) % 25 == 0:
            print(json.dumps({"scoredGames": i+1, "of": len(frame), "atUtc": utc()}), flush=True)
    ledger = pd.DataFrame(rows)
    overall = describe(ledger)
    periods = {str(y): describe(g) for y, g in ledger.groupby("season")}
    groups = {str(k): describe(g) for k, g in ledger.groupby("context")}
    coverage_ok = all(max(0, level/100-overall["candidate"][f"{name}Coverage{level}"])-max(0, level/100-overall["baseline"][f"{name}Coverage{level}"]) <= .02
        for name in ("home", "away", "total", "margin") for level in (80, 90))
    width_ok = all(overall["candidate"][f"{name}Width{level}"]/overall["baseline"][f"{name}Width{level}"] >= .9
        for name in ("home", "away", "total", "margin") for level in (80, 90))
    delta = overall["candidateMinusBaseline"]
    checks = {"energyImproved": delta["energy"] < 0, "energyUpper95BelowZero": overall["pairedBlockIntervals"]["energy"]["interval95"][1] < 0,
        "bothPeriodsNonpositiveEnergy": all(p["candidateMinusBaseline"]["energy"] <= 0 for p in periods.values()),
        "winnerGuardrails": delta["logLoss"] <= 0 and delta["brierSum"] <= 0,
        "allMarginalCrpsNonpositive": all(delta[k] <= 0 for k in ("homeCRPS", "awayCRPS", "totalCRPS", "marginCRPS")),
        "minimumSupportedGames": overall["supportedGames"] >= 100 and all(p["supportedGames"] >= 30 for p in periods.values()),
        "coverage": coverage_ok, "intervalWidth": width_ok, "ess": bool((ledger.loc[ledger.supported, "effectiveSampleSize"] >= 100).all())}
    verdict = "ADVANCE_TO_PROSPECTIVE_RESEARCH_COMPARISON" if all(checks.values()) else "REJECT" if delta["energy"] >= 0 or not checks["winnerGuardrails"] else "RETAIN_AS_EXPLORATORY"
    ledger_buffer = io.BytesIO()
    ledger.to_parquet(ledger_buffer, index=False)
    ledger_ref = put("assessment-ledger.parquet", ledger_buffer.getvalue())
    population_refs = []
    for season in (2023, 2024):
        mask = frame.season.eq(season).to_numpy()
        buf = io.BytesIO()
        np.savez_compressed(buf, gameIds=frame.loc[mask, "canonical_game_id"].to_numpy(dtype=str),
            A_home=run.baseline.home[mask], A_away=run.baseline.away[mask], B_home=run.candidate.home[mask], B_away=run.candidate.away[mask])
        population_refs.append(put(f"paired-populations-{season}.npz", buf.getvalue()))
    diag_ref = put("simulation-diagnostics.json", list(run.diagnostics))
    result = {"schemaVersion": "NFL_M1_LAGGED_QB_USAGE_RESIDUAL_ASSESSMENT_V1", "createdAtUtc": utc(), "assessmentInputOpenedAtUtc": opened_at,
        "fittedConfig": cfg_ref, "assessmentData": ref(args.data), "assessmentSourceReceipt": ref(args.source_receipt),
        "ledger": ledger_ref, "populations": population_refs, "simulationDiagnostics": diag_ref,
        "overall": overall, "bySeason": periods, "byContext": groups, "decisionChecks": checks, "verdict": verdict,
        "definition": "Candidate minus control. Lower energy/logloss/summed3-class Brier/CRPS is better. A and B use the same chronological point prediction and complete oriented donor pairs. No weighted recentering.",
        "brierConvention": "Sum over AWAY,TIE,HOME of squared error; existing floor1e-12 then renormalized probability convention. Raw count probabilities separately retained; genuine ties are not converted to MLB binary Brier.",
        "scope": "Fixed2020–22 chronological donors; all570 eligible2023–24 chronological games, reused Development. Contexts reconstructed from prior-game usage, not target QB availability.",
        "uncertainty": "Paired season/week block intervals measure across-game variation; conditional simulation MCSE remains separate in diagnostics. Draws are not independent observed games.",
        "productionModelFits": 0, "newPointModelFits": 0, "conditioningConfigurations": 1, "providerCalls": 0, "sealed2025Opened": False,
        "opening2026GamesUsed": False, "promotionAllowed": False, "wageringAuthority": False, "ordinaryPublisherChanged": False}
    result_ref = put("assessment.json", result)
    pointer("assessment.json", result_ref)
    lines = ["NFL M1 lagged QB-usage-conditioned paired residual challenger", "", "Verdict: "+verdict, "", result["scope"], "", result["definition"], "",
        "| Context (home / away) | Games applied / fallback | Donors | ESS | Δ expected H/A | Δ energy | Δ log loss | Δ Brier sum |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for group, g in groups.items():
        d = g["candidateMinusBaseline"]
        lines.append(f"| {group} | {g['supportedGames']} / {g['fallbackGames']} | {g['meanDonorSupport']:.0f} | {g['meanESS']:.1f} | {d['homeMean']:+.3f}/{d['awayMean']:+.3f} | {d['energy']:+.5f} | {d['logLoss']:+.5f} | {d['brierSum']:+.5f} |")
    lines += ["", "| Metric | A pooled | B conditioned | B−A | Paired 95% season/week block interval |", "|---|---:|---:|---:|---|"]
    for key in LOSS_KEYS:
        lines.append(f"| {key} | {overall['baseline'][key]:.6f} | {overall['candidate'][key]:.6f} | {delta[key]:+.6f} | {overall['pairedBlockIntervals'][key]['interval95']} |")
    lines += ["", "Season primary differences: "+", ".join(f"{year}: {g['candidateMinusBaseline']['energy']:+.6f}" for year, g in periods.items()), "", "Expected scores can move because weighting changes residual means. Both arms keep the same pooled centering and score transformation. Variance/dependence/tail changes, interval coverage/width and every game are retained in the linked JSON/Parquet evidence.", "", result["uncertainty"], "", "This assessment has historical publication-vintage and inherited model-selection limitations. No current starter, in-game injury or target-game QB participation was used. No sealed2025 or opening2026 results were used.", "", "Immutable assessment: "+result_ref["path"]+"; SHA256 "+result_ref["sha256"]]
    (OUT/"RESULTS.md").write_bytes(("\n".join(lines)+"\n").encode())
    print(json.dumps({"assessment": result_ref, "verdict": verdict, "games": len(ledger), "supported": overall["supportedGames"], "checks": checks}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("fit", "assess"), required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--contexts", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--context-receipt", type=Path)
    args = parser.parse_args()
    fit(args) if args.phase == "fit" else assess(args)
