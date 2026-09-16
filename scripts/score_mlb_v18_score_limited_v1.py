"""Score the three permitted observed score-limited executions, without reruns.

Future executions are inventoried but excluded before observed evidence opens.
The scorer accepts different original/retained N and uses existing winner and
empirical marginal scoring functions. It never invokes paired equal-N scoring.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.assess_mlb_v18_frozen_slate_20260912_v1 import winner
from scripts.run_mlb_v18_transition_shrinkage_v1 import load_baseline
from server.sports_current_statcast.mlb_starter_duration_paired_scoring import _marginal
from server.sports_current_statcast.mlb_starter_duration_quarantine import LEDGER, final_oot_eligible_key_mask
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_silver.canonical_ids import canonical_game_id

OUT = ROOT / "outputs/mlb-v18-score-limited-v1/results"
OBSERVED = ROOT / "outputs/mlb-v18-population-diagnostics-v1/observed-v2/observed.json"
OBSERVED_SHA = "873027ff0eea7c5306ee7a54d394986359bce929aa6ab64d0f4c02d3db0d3363"
BASELINES = {
    "823496": "d8bc8570b0e62c98150a4629dc075941d6feb0c9ba23611980f4c309c80ce8cb",
    "824870": "5af32a236f9ee77727237540f4b89a9184ba7dbc8ce632e3e535e2104e5c81c0",
    "824630": "707bc71848abc82180423a22e840a0bebc9f6fd5640c0f3356f1fa048a9d7564",
}
FIELDS = ("homeRuns", "awayRuns", "innings", "paCounts")


def require(value, message):
    if not value:
        raise ValueError(message)


def ref(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def verified_bytes(bound):
    raw = Path(bound["path"]).read_bytes()
    require(len(raw) == bound["bytes"] and hashlib.sha256(raw).hexdigest() == bound["sha256"],
            "Physical binding mismatch: " + str(bound["path"]))
    return raw


def verified_json(bound):
    return json.loads(verified_bytes(bound))


def save(value, name):
    raw = canonical_json_bytes(value)
    sha = hashlib.sha256(raw).hexdigest()
    path = OUT / "objects/sha256" / sha / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == raw, "Immutable scoring artifact conflict")
    else:
        path.write_bytes(raw)
    return ref(path)


def pick(probability):
    return "HOME" if probability > .5 else "AWAY" if probability < .5 else "NO_PICK"


def score_arm(home, away, actual_home, actual_away, saved_summary):
    require(home.ndim == away.ndim == 1 and len(home) == len(away) and len(home) >= 1000,
            "Unsupported retained score population")
    require(not np.equal(home, away).any(), "Binary MLB scoring requires zero tie probability")
    p = float(np.mean(home > away))
    computed = {"homeWinProbability": p, "awayWinProbability": float(np.mean(away > home)),
                "tieProbability": 0., "meanHomeRuns": float(home.mean()), "meanAwayRuns": float(away.mean()),
                "meanTotalRuns": float((home + away).mean()), "meanRunDifferential": float((home-away).mean())}
    require(all(computed[k] == saved_summary[k] for k in computed), "Saved forecast summary changed or wrong denominator")
    outcomes = {"homeRuns": actual_home, "awayRuns": actual_away,
                "totalRuns": actual_home + actual_away, "homeMargin": actual_home - actual_away}
    draws = {"homeRuns": home, "awayRuns": away, "totalRuns": home+away, "homeMargin": home-away}
    metrics = winner(p, actual_home, actual_away)
    chosen = pick(p)
    actual_winner = "HOME" if actual_home > actual_away else "AWAY"
    marginals = {name: _marginal(values, outcomes[name]) for name, values in draws.items()}
    return {**computed, **metrics, "drawCount": len(home), "pick": chosen,
            "correctPick": chosen != "NO_PICK" and chosen == actual_winner, "marginals": marginals,
            "meanTeamScoreAbsoluteError": (marginals["homeRuns"]["absoluteError"] + marginals["awayRuns"]["absoluteError"])/2,
            "totalRunsAbsoluteError": marginals["totalRuns"]["absoluteError"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executions", type=Path, default=ROOT / "outputs/mlb-v18-score-limited-v1/executions/current.json")
    parser.add_argument("--inventory", type=Path, default=ROOT / "outputs/mlb-v18-score-limited-v1/inventory/coverage.json")
    args = parser.parse_args()
    if (OUT / "current.json").exists():
        current = json.loads((OUT / "current.json").read_text())
        verified_json(current["result"])
        verified_bytes(current["table"])
        print(json.dumps(current, indent=2))
        return
    input_ref = ref(args.executions)
    index = verified_json(input_ref)
    executions = [(bound, verified_json(bound)) for bound in index["executions"]]
    selected, not_scored = [], []
    for bound, execution in executions:
        pk = str(execution["sourceGameId"])
        if pk not in BASELINES:
            not_scored.append({"sourceGameId": pk, "execution": bound,
                               "reason": "OUTSIDE_FIXED_OBSERVED_THREE_GAME_COHORT_NO_OUTCOME_ACCESS"})
            continue
        require(execution["status"] == "SUPPORTED", "Fixed observed game lacks supported execution")
        aliases = [pk, execution["gameId"], canonical_game_id(int(pk))]
        require(all(final_oot_eligible_key_mask(aliases)), "Whole-game quarantine gate failed")
        require(execution.get("rulePublication") is not None, "Published rule receipt required before outcome access")
        publication = verified_json(execution["rulePublication"])
        require(publication["status"] == "PUBLISHED_RULE" and publication["forecastPerformanceExamined"] is False,
                "Initial rule was not published before performance examination")
        require(verified_bytes(publication["rule"]) == verified_bytes(publication["deliveredRule"]),
                "Delivered rule differs from frozen rule")
        require(datetime.fromisoformat(publication["publishedAtUtc"].replace("Z", "+00:00"))
                < datetime.fromisoformat(execution["frozenAtUtc"].replace("Z", "+00:00")),
                "Challenger execution preceded rule publication")
        bundle = load_baseline(BASELINES[pk])
        require(execution["baselineObjectSha256"] == bundle["objectSha256"], "Execution uses another baseline object")
        require(bundle["forecast"]["gameId"] == execution["gameId"], "Original frozen baseline identity mismatch")
        require(str(bundle["forecast"]["scheduledStart"])[:10] == "2026-09-12", "Wrong retrospective forecast date")
        selected.append((bound, execution, bundle))
    require({str(x[1]["sourceGameId"]) for x in selected} == set(BASELINES) and len(selected) == len(BASELINES),
            "Each of the three fixed observed games must occur exactly once")
    gate = save({"schemaVersion": "MLB_V18_SCORE_LIMIT_SCORING_OUTCOME_GATE_V1",
                 "checkedAtUtc": datetime.now(timezone.utc).isoformat(), "quarantine": ref(LEDGER),
                 "executions": input_ref, "selected": [{"sourceGameId": x[1]["sourceGameId"], "gameId": x[1]["gameId"],
                     "execution": x[0], "originalBaselineObjectSha256": x[2]["objectSha256"]} for x in selected],
                 "outcomesAccessedBeforeGate": False, "futureGamesExcluded": not_scored}, "outcome-gate.json")
    observed_ref = ref(OBSERVED)
    require(observed_ref["sha256"] == OBSERVED_SHA, "Corrected observed V2 identity changed")
    observed = verified_json(observed_ref)
    require(set(map(str, observed["fixedSourceGameIds"])) == set(BASELINES), "Observed payload contains an unexpected cohort")
    by_pk = {str(row["sourceGameId"]): row for row in observed["rows"]}
    results = []
    for bound, execution, bundle in sorted(selected, key=lambda x: list(BASELINES).index(str(x[1]["sourceGameId"]))):
        pk = str(execution["sourceGameId"])
        actual = by_pk[pk]
        require(actual["gameId"] == execution["gameId"], "Final and forecast game identity differ")
        actual_home = int(actual["perTeam"]["HOME"]["runs"] + actual["perTeam"]["HOME"]["non_pa_runs"])
        actual_away = int(actual["perTeam"]["AWAY"]["runs"] + actual["perTeam"]["AWAY"]["non_pa_runs"])
        require(actual_home != actual_away, "Untied final required")
        raw = verified_bytes(execution["acceptedPopulation"])
        with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
            arrays = {name: archive[name].copy() for name in archive.files}
        indices = arrays["accepted_indices"]
        require(indices.ndim == 1 and np.issubdtype(indices.dtype, np.integer) and np.all(np.diff(indices) > 0),
                "Accepted draw identities must be strictly increasing integers")
        require(len(indices) == execution["retainedDrawCount"] and execution["originalDrawCount"] == 5000,
                "Execution denominator mismatch")
        for field in FIELDS:
            base = arrays["baseline_"+field]
            accepted = arrays["accepted_"+field]
            require(np.array_equal(base, np.asarray(bundle["baseline"][field])), "Unrestricted original array changed: " + field)
            require(np.array_equal(accepted, base[indices]), "Accepted draw changed: " + field)
        baseline = score_arm(arrays["baseline_homeRuns"], arrays["baseline_awayRuns"], actual_home, actual_away, execution["baselineSummary"])
        candidate = score_arm(arrays["accepted_homeRuns"], arrays["accepted_awayRuns"], actual_home, actual_away, execution["summary"])
        differences = {key: candidate[key]-baseline[key] for key in
                       ("winnerLogLoss", "winnerBrier", "meanTeamScoreAbsoluteError", "totalRunsAbsoluteError",
                        "homeWinProbability", "meanHomeRuns", "meanAwayRuns", "meanTotalRuns")}
        differences["marginals"] = {name: {metric: candidate["marginals"][name][metric]-baseline["marginals"][name][metric]
            for metric in ("signedError", "absoluteError", "squaredError", "crps")}
            for name in ("homeRuns", "awayRuns", "totalRuns", "homeMargin")}
        results.append({"sourceGameId": pk, "gameId": actual["gameId"], "gameDate": "2026-09-12",
                        "awayTeam": actual["awayTeam"], "homeTeam": actual["homeTeam"],
                        "actual": {"awayRuns": actual_away, "homeRuns": actual_home},
                        "classification": "EXPLORATORY_RETROSPECTIVE_POST_OUTCOME_SELECTED_CASES",
                        "source": actual["source"], "execution": bound, "acceptedPopulation": execution["acceptedPopulation"],
                        "baselineObjectSha256": bundle["objectSha256"], "originalForecast": ref(bundle["directory"] / "forecast.json"),
                        "rulePublication": execution["rulePublication"], "baseline": baseline, "candidate": candidate,
                        "candidateMinusBaseline": differences,
                        "pickChanged": baseline["pick"] != candidate["pick"],
                        "wrongToRight": not baseline["correctPick"] and baseline["pick"] != "NO_PICK" and candidate["correctPick"],
                        "rightToWrong": baseline["correctPick"] and candidate["pick"] != "NO_PICK" and not candidate["correctPick"],
                        "exclusions": execution["exclusions"], "exclusionRate": execution["exclusionRate"],
                        "retainedDrawCount": execution["retainedDrawCount"], "originalDrawCount": execution["originalDrawCount"],
                        "simulationUncertainty": execution["uncertainty"],
                        "verification": {"fourOriginalArraysExact": True, "fourAcceptedArraysExactIndexedSubset": True,
                                         "allSummaryValuesReconcileWithActualN": True, "binaryBrierZeroTieCondition": True}})
    metrics = ("winnerLogLoss", "winnerBrier", "meanTeamScoreAbsoluteError", "totalRunsAbsoluteError")
    aggregate = {arm: {"correctWinnerPicks": sum(row[arm]["correctPick"] for row in results),
                      "noPicks": sum(row[arm]["pick"] == "NO_PICK" for row in results),
                      **{key: float(np.mean([row[arm][key] for row in results])) for key in metrics}}
                 for arm in ("baseline", "candidate")}
    aggregate.update(games=len(results), wrongToRight=sum(row["wrongToRight"] for row in results),
                     rightToWrong=sum(row["rightToWrong"] for row in results),
                     picksChanged=sum(row["pickChanged"] for row in results))
    aggregate["candidateMinusBaseline"] = {key: aggregate["candidate"][key]-aggregate["baseline"][key] for key in metrics}
    inventory_ref = ref(args.inventory)
    inventory = verified_json(inventory_ref)
    missing = [{key: row[key] for key in ("sourceGameId", "gameId", "gameDate", "objectSha256", "counterCoverage")}
               for row in inventory["ordinaryForecasts"] if row.get("counterCoverage") == "MISSING_PER_DRAW_INNING_RUNS"]
    result = {"schemaVersion": "MLB_V18_SCORE_LIMIT_EXPLORATORY_RESULTS_V1",
              "createdAtUtc": datetime.now(timezone.utc).isoformat(), "outcomeGate": gate,
              "executionsIndex": input_ref, "observedEvidence": observed_ref, "rows": results,
              "aggregate": aggregate, "notScoredExecutions": not_scored,
              "coverageInventory": inventory_ref, "coverageSummary": inventory["summary"], "missingCounterGames": missing,
              "missingCounterStatusSource": "Use the bound complete inventory; missing counters do not become zero exclusions or successful executions.",
              "definitions": {"winnerPick": "HOME iff pHome>0.5, AWAY iff pHome<0.5, exact0.5 NO_PICK",
                              "differenceDirection": "Candidate minus baseline; negative log loss, binary Brier, absolute error, squared error and CRPS differences are better.",
                              "binaryBrier": "(pHome-observedHomeWin)^2; computed only after zero simulated ties and an untied final are verified.",
                              "meanTeamScoreAbsoluteError": "Mean of absolute expected-home-score error and absolute expected-away-score error, then equally weighted over games.",
                              "economics": "Argmax winner-pick accuracy is separate from selecting a team at offered odds. No offered-price/stake economics is recomputed or implied by this table.",
                              "simulationUncertainty": "Retained-N MCSE and paired subset-minus-original ratio-estimator MCSE are simulation sampling precision, not predictive-improvement uncertainty."},
              "limitations": ["These three games were selected after their outcomes for explanation; results are exploratory and not an independent validation cohort.",
                              "No prospective outcome is accessed by this scorer.", "Lower mean runs alone do not demonstrate better winner forecasting.",
                              "The initial Development thresholds are fixed, not selected for these games; inherited model chronology remains uncertified."],
              "activity": {"modelFits": 0, "simulations": 0, "providerRequests": 0, "newThresholdSearches": 0},
              "code": ref(Path(__file__))}
    result_ref = save(result, "results.json")
    lines = ["# Score-limited V18: exploratory comparison", "",
             f"Correct winner picks: **{aggregate['baseline']['correctWinnerPicks']}/{len(results)} → {aggregate['candidate']['correctWinnerPicks']}/{len(results)}**. "
             f"Wrong → right: **{aggregate['wrongToRight']}**; right → wrong: **{aggregate['rightToWrong']}**.", "",
             "Unrestricted → score-limited. Mean errors are lower-is-better. The limited forecasts condition on the actually retained draws; neither scores nor sequences are clipped.", "",
             "| September 12 game; actual A–H | Retained / 5,000; excluded | Pick A → S | p(Home) A → S | Expected A/H: A → S | Log loss A → S (Δ) | Brier A → S (Δ) | Team-score MAE A → S | Total error A → S |",
             "|---|---:|---|---:|---|---:|---:|---:|---:|"]
    for row in results:
        b,c,d = row["baseline"],row["candidate"],row["candidateMinusBaseline"]
        def team(side):
            return row["homeTeam"] if side == "HOME" else row["awayTeam"] if side == "AWAY" else "no pick"
        lines.append(f"| {row['awayTeam']}–{row['homeTeam']} {row['sourceGameId']}; {row['actual']['awayRuns']}–{row['actual']['homeRuns']} "
            f"| {row['retainedDrawCount']:,}; {row['exclusionRate']:.2%} | {team(b['pick'])} → {team(c['pick'])} "
            f"| {b['homeWinProbability']:.4f} → {c['homeWinProbability']:.4f} "
            f"| {b['meanAwayRuns']:.3f}/{b['meanHomeRuns']:.3f} → {c['meanAwayRuns']:.3f}/{c['meanHomeRuns']:.3f} "
            f"| {b['winnerLogLoss']:.4f} → {c['winnerLogLoss']:.4f} ({d['winnerLogLoss']:+.4f}) "
            f"| {b['winnerBrier']:.4f} → {c['winnerBrier']:.4f} ({d['winnerBrier']:+.4f}) "
            f"| {b['meanTeamScoreAbsoluteError']:.3f} → {c['meanTeamScoreAbsoluteError']:.3f} "
            f"| {b['totalRunsAbsoluteError']:.3f} → {c['totalRunsAbsoluteError']:.3f} |")
    lines += ["", "Aggregate mean metrics (unrestricted → score-limited): " + "; ".join(
        f"{key} {aggregate['baseline'][key]:.5f} → {aggregate['candidate'][key]:.5f} (Δ {aggregate['candidateMinusBaseline'][key]:+.5f})" for key in metrics) + ".", "",
        "p(Home) simulation MCSE, baseline / candidate / paired candidate-minus-baseline: " + "; ".join(
            f"{row['awayTeam']}–{row['homeTeam']} " + "/".join(f"{row['simulationUncertainty'][key]['homeWinProbability']:.5f}"
                for key in ("baselineMCSE", "candidateMCSE", "pairedDifferenceMCSE")) for row in results) + ".", "",
        "The saved JSON includes each arm's home, away, total and margin distribution scores, exact final-revision identities, exclusion categories, retained populations, and original forecast bindings.", "",
        "These post-outcome selected games are exploratory. Winner-pick accuracy is not offered-price betting economics. MCSE measures simulation sampling only; it does not bound model/input error or establish recurring improvement. Future executions are not scored here.", "",
        "Missing population counters remain separately reported in the bound coverage inventory. No missing game is counted as zero exclusions or a supported challenger.", "",
        "```powershell", ".venv/Scripts/python.exe -B scripts/score_mlb_v18_score_limited_v1.py", "```", ""]
    table_path = OUT / "comparison.md"
    table_path.write_bytes("\n".join(lines).encode("utf-8"))
    current = {"result": result_ref, "table": ref(table_path)}
    (OUT / "current.json").write_bytes(canonical_json_bytes(current))
    print(json.dumps({"aggregate": aggregate, "artifacts": current}, indent=2))


if __name__ == "__main__":
    main()
