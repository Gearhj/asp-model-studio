"""Close the bounded September 13 inventory; no forecasting or outcome ingestion.

Consumer evaluations remain explicitly distinct from governed revision scoring.
Uses only frozen artifacts and a retained SELECT-only observation receipt.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_mlb_v18_transition_shrinkage_v1 import load_baseline
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask

OUT = ROOT / "outputs/mlb-prospective-closeout-and-explanations-v1"
SURVIVAL = ROOT / "outputs/mlb-v18-survival-starter-coverage-v1/comparisons/objects/sha256/e2be2661fa1f72156096dd3b16087e5cc98ccd329bf299a89653de06851edac1/three-arm-result.json"
LIMITED = ROOT / "outputs/mlb-v18-score-limited-v1/objects/sha256/8ac962b90c3da1bbdcefd84de01ebd403f5c44459ca4e4d68d1eb4d8350996bb/execution.json"
ARMS = ("V18_BASE", "V18_SURVIVAL_ONLY", "V18_TRANSITION_ONLY")
FIELDS = ("homeRuns", "awayRuns", "innings", "paCounts")
TARGETS = {"824225": "8b923997-fc79-483d-9444-78f088e65c52", "823734": "3c7a6820-7c95-4e91-87fa-6acb89c013d7"}


def ref(path):
    raw = Path(path).read_bytes()
    return {"path": str(Path(path).resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def verify(descriptor):
    raw = Path(descriptor["path"]).read_bytes()
    assert len(raw) == descriptor["bytes"] and hashlib.sha256(raw).hexdigest() == descriptor["sha256"], "PHYSICAL_BYTES_CHANGED"
    return raw


def put(name, data):
    raw = (json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    path = OUT / "objects/sha256" / hashlib.sha256(raw).hexdigest() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw
    else:
        path.write_bytes(raw)
    return ref(path)


def summary(pop):
    h, a = (np.asarray(pop[k]) for k in ("homeRuns", "awayRuns"))
    assert h.ndim == a.ndim == 1 and len(h) == len(a) and len(h) >= 1000
    assert np.isfinite(h).all() and np.isfinite(a).all()
    assert (h >= 0).all() and (a >= 0).all() and np.equal(h, np.floor(h)).all() and np.equal(a, np.floor(a)).all()
    return {"drawCount": len(h), "homeWinProbability": float(np.mean(h > a)), "awayWinProbability": float(np.mean(a > h)),
            "tieProbability": float(np.mean(h == a)), "meanHomeRuns": float(h.mean()), "meanAwayRuns": float(a.mean()),
            "meanTotalRuns": float((h+a).mean()), "meanRunDifferential": float((h-a).mean())}


def require_summary(actual, saved):
    for k, v in actual.items():
        if k in saved:
            assert np.isclose(v, saved[k], rtol=0, atol=1e-12), (k, v, saved[k])
    assert np.isclose(sum(actual[k] for k in ("homeWinProbability", "awayWinProbability", "tieProbability")), 1, atol=1e-15)


def main():
    assert all(final_oot_eligible_key_mask(list(TARGETS) + list(TARGETS.values())))
    # The original fixed identities are admitted before reading the retained outcome receipt.
    for p in (SURVIVAL, LIMITED):
        assert ref(p)["sha256"] == p.parent.name
    s, c = (json.loads(p.read_bytes()) for p in (SURVIVAL, LIMITED))
    assert s["sourceGameId"] == "824225" and s["gameId"] == TARGETS["824225"]
    assert c["sourceGameId"] == "823734" and c["gameId"] == TARGETS["823734"]
    original_refs = [ref(SURVIVAL), ref(LIMITED), s["population"], c["acceptedPopulation"], s["baselineForecast"], c["baselineForecast"]]
    baseline_s, baseline_c = (load_baseline(obj) for obj in (s["sourceForecastObjectSha256"], c["baselineObjectSha256"]))
    summaries, exposure = {}, {}
    with np.load(io.BytesIO(verify(s["population"])), allow_pickle=False) as z:
        for arm in ARMS:
            pop = {k: z[arm+"_"+k] for k in FIELDS}
            assert all(v.shape == (5000,) for v in pop.values())
            if arm == "V18_BASE":
                for k in FIELDS:
                    assert np.array_equal(pop[k], baseline_s["baseline"][k])
            summaries[arm] = summary(pop)
            require_summary(summaries[arm], s["arms"][arm]["summary"])
            exposure[arm] = {}
            for name in ("homeStarterBf", "awayStarterBf", "homeStarterOuts", "awayStarterOuts", "homeRelieverBf", "awayRelieverBf"):
                key = arm+"_"+name
                if key in z:
                    a = z[key]
                    assert a.shape == (5000,)
                    exposure[arm][name] = {"mean": float(a.mean()), "q05": float(np.quantile(a, .05)), "median": float(np.median(a)), "q95": float(np.quantile(a, .95)), "drawCount": len(a)}
            if exposure[arm]:
                bf = sum(z[arm+"_"+k] for k in ("homeStarterBf", "awayStarterBf", "homeRelieverBf", "awayRelieverBf"))
                assert np.array_equal(bf, pop["paCounts"]), "PITCHER_EXPOSURE_ACCOUNTING"
    with np.load(io.BytesIO(verify(c["acceptedPopulation"])), allow_pickle=False) as z:
        ix = z["accepted_indices"]
        assert ix.dtype.kind in "iu" and len(ix) == c["retainedDrawCount"] == 4722 and np.all(np.diff(ix) > 0)
        assert np.array_equal(np.flatnonzero(z["acceptance_mask"]), ix)
        for k in FIELDS:
            assert np.array_equal(z["baseline_"+k], baseline_c["baseline"][k])
            assert np.array_equal(z["accepted_"+k], z["baseline_"+k][ix])
        limited_summaries = {arm: summary({k: z[arm+"_"+k] for k in FIELDS}) for arm in ("baseline", "accepted")}
        require_summary(limited_summaries["baseline"], c["baselineSummary"])
        require_summary(limited_summaries["accepted"], c["summary"])
    inventory_path = OUT / "final-inventory.json"
    assert ref(inventory_path)["sha256"] == "5742ac585cf8ba7b061e9c25f1a808b197ce33dd195d5e518f511f6e70674dfd", "FROZEN_CONSUMER_SNAPSHOT_CHANGED"
    inventory_ref = put("consumer-final-inventory.json", json.loads(inventory_path.read_bytes()))
    inv = json.loads(verify(inventory_ref))
    assert set(inv["declaredGamePks"]) == set(TARGETS)
    assert inv["transactionReadOnly"] is True and inv["quarantineCheckedBeforeOutcomeAccess"] is True
    # This snapshot has no eligible revision. Do not silently substitute the consumer result source.
    assert not inv["governedFinals"], "NEW_GOVERNED_FINAL_REQUIRES_EXISTING_SCORER"
    by_id = {r["forecast_identity"]: r for r in inv["consumerEvaluations"]}
    forecasts = {r["forecast_id"]: r for r in inv["consumerForecasts"]}
    ids = {"V18_BASE": s["baselineForecastId"], "V18_SURVIVAL_ONLY": "mlb-v18-survival-"+SURVIVAL.parent.name, "V18_TRANSITION_ONLY": "mlb-v18-transition-"+SURVIVAL.parent.name}
    consumer_rows = {}
    for arm, fid in ids.items():
        e = by_id[fid]
        p = e["detail"]["published_probabilities"]
        assert p["tie"] == summaries[arm]["tieProbability"] == 0
        # Consumer computes away as 1-home; count/N differs by one float ULP.
        assert p["home"] == summaries[arm]["homeWinProbability"] and np.isclose(p["away"], summaries[arm]["awayWinProbability"], rtol=0, atol=1e-15)
        assert e["canonical_game_id"] == s["gameId"] and e["distribution_draws"] == summaries[arm]["drawCount"]
        assert e["predicted_home_score"] == summaries[arm]["meanHomeRuns"] and e["predicted_away_score"] == summaries[arm]["meanAwayRuns"]
        binary = (p["home"]-int(e["actual_outcome"] == "HOME"))**2
        assert np.isclose(e["brier_score"], 2*binary, atol=1e-14, rtol=0)
        metrics = {"winnerLogLoss": e["log_loss"], "winnerBinaryBrier": binary, "consumerThreeClassBrier": e["brier_score"],
                   "homeCRPS": e["crps_home"], "awayCRPS": e["crps_away"], "totalCRPS": e["crps_total"], "marginCRPS": e["crps_margin"],
                   "meanTeamScoreAbsoluteError": e["team_score_mae"], "totalAbsoluteError": abs(e["total_error"]), "marginAbsoluteError": abs(e["margin_error"])}
        consumer_rows[arm] = {"forecastId": fid, "evaluationId": e["id"], "resultIdentity": e["result_identity"], "resultObservedAt": e["result_observed_utc"],
                              "evaluatedAt": e["evaluated_at"], "consumerSnapshotVersion": e["snapshot_version"], "governedFinalRevision": None,
                              "status": "EXISTING_CONSUMER_EVALUATION_ONLY", "actualAwayHome": [e["away_score"], e["home_score"]],
                              "winnerPick": e["predicted_outcome"], "correctPick": e["winner_correct"], "metrics": metrics,
                              "forecastSummary": summaries[arm], "receipt": inventory_ref}
    assert len({r["resultIdentity"] for r in consumer_rows.values()}) == 1
    for arm in ARMS[1:]:
        consumer_rows[arm]["candidateMinusBaseline"] = {k: v-consumer_rows[ARMS[0]]["metrics"][k] for k, v in consumer_rows[arm]["metrics"].items()}
        imp = forecasts[ids[arm]]
        assert datetime.fromisoformat(imp["imported_at"]) < datetime.fromisoformat(s["deadlineUtc"])
    limited_id = next(k for k in forecasts if "score-limited" in k)
    assert datetime.fromisoformat(forecasts[limited_id]["imported_at"]) < datetime.fromisoformat(c["deadlineUtc"])
    assert not any(e["canonical_game_id"] == c["gameId"] for e in inv["consumerEvaluations"])
    report = {
        "schemaVersion": "MLB_EXISTING_PROSPECTIVE_COMPARISONS_CLOSEOUT_V1", "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "snapshotAsOfUtc": inv["observedAtUtc"], "finalInventory": inventory_ref,
        "governedAssessmentStatus": "PENDING_EXACT_REVISIONED_FINALS", "governedScoredGames": 0,
        "distinctPublishedGames": 2, "researchInterventionsPublishedAndImported": 3, "supportedExecutions": 3, "fallbacks": 0,
        "consumerEvaluationGames": 1, "consumerEvaluations": consumer_rows,
        "survivalAndTransition": {"result": ref(SURVIVAL), "population": s["population"], "baselineForecast": s["baselineForecast"],
            "baselineForecastId": s["baselineForecastId"], "sourceCutoff": s["sourceCutoff"], "frozenAtUtc": s["frozenAtUtc"], "deadlineUtc": s["deadlineUtc"],
            "coupling": s["pairedMonteCarloCoupling"], "pitchingExposure": exposure,
            "allocationAssessment": "UNAVAILABLE: original baseline has no starter/relief counters; no final-bound actual pitcher history for this game. Candidate summaries alone cannot establish allocation improvement.",
            "decision": {"survival": "Mixed existing consumer single-game scores; do not advance or promote.", "transition": "Mixed existing consumer single-game scores; do not advance or promote."}},
        "scoreLimited": {"execution": ref(LIMITED), "population": c["acceptedPopulation"], "forecastId": limited_id, "baselineForecastId": c["baselineForecastId"],
            "baselineForecast": c["baselineForecast"], "summaries": limited_summaries, "exclusions": c["exclusions"], "retainedDrawCount": 4722,
            "originalDrawCount": 5000, "exclusionRate": c["exclusionRate"], "uncertainty": c["uncertainty"], "frozenAtUtc": c["frozenAtUtc"],
            "frozenLimits": {"maxRunsPerPlayedHalfInning": 5, "maxRunsPerTeamGame": 14}, "rule": c["rule"], "rulePublication": c["rulePublication"],
            "sourceCutoff": c["sourceCutoff"], "deadlineUtc": c["deadlineUtc"], "importedAt": forecasts[limited_id]["imported_at"],
            "winnerPicks": {"baseline": "CIN", "candidate": "CIN", "changed": False}, "metrics": None,
            "status": "AWAITING_GENUINE_FINAL_AND_GOVERNED_REVISION", "decision": "Insufficient evidence; keep frozen, no advancement or backfill."},
        "remainingPrerequisites": inv["governedFinalRevisionStatus"],
        "requiredOwnerAction": "Claude: use the existing governed final ingest to persist latest eligible FINAL game_final_outcomes for exact game UUIDs 8b923997-fc79-483d-9444-78f088e65c52 (824225) and 3c7a6820-7c95-4e91-87fa-6acb89c013d7 (823734, only once genuinely final). Required id, game_id, revision, created_at, final_at after original start, nonnegative integer away_score/home_score. Reuse identical revision for all arms. Official game-state evaluations are separately recorded evidence and do not substitute for this study prerequisite. Optional actual starter/relief evidence must bind the same final; lack of it must not block whole-game scoring. Existing evaluation owner remains unchanged.",
        "definitions": {"difference": "candidate minus exact baseline; negative loss/error/CRPS favors candidate", "brier": "MLB binary (pHome-yHome)^2; conversion from the retained consumer sum-of-three-class Brier is valid here only after exact zero-tie verification", "uncertainty": "MCSE is conditional simulation sampling precision; one game is one assessment observation, not 5000.", "consumerSource": "Existing AISP official-wire evaluation; sourceIdentity is not a governed outcome revision. Not a formal study completion.", "jointScore": "Not recomputed from an ineligible final. Original paired draws remain retained for the existing scorer once a governed final is admitted."},
        "archetypeDecision": "B and C did not demonstrate improvement; preserve completed study, do not advance.",
        "verification": {"frozenPopulationCountsAndMeans": True, "baselineFourArraysExact": True, "acceptedSubsetExact": True, "candidateBfReconcilesToPa": True,
                         "sameConsumerResultIdentity": True, "zeroTieBrierConventionChecked": True, "originalPhysicalArtifactsUnchanged": True},
        "newFits": 0, "newSimulations": 0, "providerRequests": 0, "aispWrites": 0, "productionAuthority": False}
    for original in original_refs:
        verify(original)
    result = put("prospective-closeout.json", report)
    (OUT / "prospective-closeout.json").write_bytes((json.dumps(result, indent=2)+"\n").encode())
    lines = ["September 13 frozen comparisons", "", "COL–DET's existing AISP official-wire evaluation reports COL 1–DET 8. No game_final_outcomes revision exists at the retained read; these are qualified consumer results, not completed governed study assessments. CIN–MIL was live and had no evaluation.", "", "| Game / arm | Draws | P(home) | Expected away/home | Log loss | Binary Brier | CRPS away/home/total/margin |", "|---|---:|---:|---|---:|---:|---|"]
    for arm, r in consumer_rows.items():
        q, m = r["forecastSummary"], r["metrics"]
        lines.append(f"| COL–DET / {arm} | {q['drawCount']} | {q['homeWinProbability']:.4f} | {q['meanAwayRuns']:.4f}/{q['meanHomeRuns']:.4f} | {m['winnerLogLoss']:.6f} | {m['winnerBinaryBrier']:.6f} | "+"/".join(f"{m[k]:.6f}" for k in ('awayCRPS','homeCRPS','totalCRPS','marginCRPS'))+" |")
    for arm, q in limited_summaries.items():
        lines.append(f"| CIN–MIL / {arm} | {q['drawCount']} | {q['homeWinProbability']:.6f} | {q['meanAwayRuns']:.4f}/{q['meanHomeRuns']:.4f} | Pending | Pending | Pending |")
    lines += ["", "All COL–DET picks were correctly Detroit. Survival: slightly better winner, home and margin scores; worse away and total CRPS. Transition: slightly worse winner scores; better away/home/margin CRPS, worse total CRPS. No recurring gain established. CIN–MIL retains the CIN pick: 278/5000 excluded (5.56%), 4722 retained. Its result is pending.", "", report["survivalAndTransition"]["allocationAssessment"], "", "No research arm advances. Archetype B/C remain closed without advancement.", "", "Run: `.venv/Scripts/python.exe -B scripts/close_mlb_existing_prospective_comparisons_v1.py`", "", "Immutable result: "+result["path"]+"; SHA256 "+result["sha256"]]
    (OUT / "RESULTS.md").write_bytes(("\n".join(lines)+"\n").encode())
    print(json.dumps({"result": result, "governedScoredGames": 0, "consumerEvaluatedGames": 1, "distinctPublishedGames": 2}, indent=2))


if __name__ == "__main__":
    main()
