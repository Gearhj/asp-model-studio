"""Score exactly three existing frozen studies; no inference, provider or AISP write.

Uses the existing metadata-first, latest-final-revision reader and saved-draw
scorers. Original NYM-NYY candidate distributions were not retained: only its
saved probability and mean-score measurements are eligible for scoring.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_mlb_v18_transition_shrinkage_v1 import load_baseline, compact
from server.sports_current_statcast.mlb_starter_duration_paired_publication import (
    OUTPUT as DURATION, read, reference, save, verified, verify_published_pointer, utc,
)
from server.sports_current_statcast.mlb_starter_duration_paired_scoring import (
    read_persisted_finals, score_pair, _final_identity, _digest, _marginal,
    _score_integer, joint_energy_score, WIN_LOGLOSS_FLOOR,
)
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask
from server.sports_current_statcast.mlb_v18_unattended import atomic_state, single_owner
from server.sports_silver.canonical_ids import canonical_game_id

OUT = ROOT / "outputs/mlb-v18-three-arm-pregame-comparison-v1/scoring"
TRANSITION = ROOT / "outputs/mlb-v18-transition-shrinkage-v1"
COMPONENT = "8c91d687c95ff81ad11efa7a5e718aa5bbfeb0aa97cc05795bd26e3954939640"
PAIR_SHAS = ("4c81080510a37eb4fd238623c3c590c3aed9477f8b155cd78945e5bb5f080fca",
             "b3aded9cebff04d91206e45d90339ea7df02fa5605b9578979f22f6e87c57f9e")
KC_ADAPTER_FORECAST = {
    "path": str(TRANSITION / "adapter-v2/packages/sha256/11483c854b0e541a528dd67b2c772a35dffd380fde14ccb09726e647a96d4466/objects/sha256/06512721fb99d011d09732e597e9478b794d92d15ef0ba786af5a77a7bfd7105/forecast.json"),
    "sha256": "b1f43259dc7cf56d8db9f08b62e9383ffd02dfd7dedd8555bab341db024a2ddb", "bytes": 4349,
}


def consumer_identities(pair, pair_reference):
    """Saved consumer IDs and explicitly separate internal arm coordinates."""
    labels = {"referenceArmIdentity": pair["commonPairId"] + ":reference",
              "candidateArmIdentity": pair["commonPairId"] + ":challenger",
              "armIdentityMeaning": "Internal pair/arm coordinates, not consumer forecast IDs."}
    if pair["sourceGameId"] == "824227":
        inputs = read(pair["inputs"])
        return {**labels, "baselineSourceForecastId": "mlb-v18-daily-" + inputs["v18SourceObject"]["objectSha256"],
                "baselineForecastId": None, "candidateForecastId": None,
                "consumerForecastIdentityEvidence": None,
                "consumerIdentityGap": "Original duration exchange saves commonPairId and reference/challenger arms; no separate consumer forecast IDs are present. Source ordinary V18 forecast ID is reported separately."}
    baseline_id = "mlb-v18-daily-" + pair["sourceForecastObjectSha256"]
    if pair["sourceGameId"] == "824712":
        forecast = read(KC_ADAPTER_FORECAST)
        assert forecast["sourcePairSha256"] == pair_reference["sha256"]
        assert forecast["sourceGameId"] == pair["sourceGameId"] and forecast["baselineForecastId"] == baseline_id
        return {**labels, "baselineSourceForecastId": baseline_id, "baselineForecastId": forecast["baselineForecastId"],
                "candidateForecastId": forecast["forecastId"], "consumerForecastIdentityEvidence": KC_ADAPTER_FORECAST,
                "consumerIdentityGap": None}
    return {**labels, "baselineSourceForecastId": baseline_id, "baselineForecastId": baseline_id,
            "candidateForecastId": None, "consumerForecastIdentityEvidence": None,
            "consumerIdentityGap": "Original NYM-NYY V1 pair has no saved candidate consumer forecast ID or candidate distribution package."}


def guard(pair):
    ids = [pair["gameId"], pair["sourceGameId"], canonical_game_id(int(pair["sourceGameId"]))]
    assert all(final_oot_eligible_key_mask(ids)), "PERMANENT_WHOLE_GAME_QUARANTINE"
    assert utc(pair["scheduledStartUtc"]) >= datetime(2026, 9, 11, tzinfo=timezone.utc), "SEALED_OR_OUT_OF_SCOPE_GAME"


def preflight():
    pointer = json.loads((DURATION / "published/7323d8f3-9b24-464d-903e-fe290913d73b.json").read_text())
    pair, publication = verify_published_pointer(pointer)
    assert pair["sourceGameId"] == "824227"
    guard(pair)
    for descriptor in (pair["durationModel"]["artifact"], pair["modelIdentity"]["paArtifact"], pair["modelIdentity"]["transitionArtifact"]):
        verified(descriptor)
    assert pair["modelIdentity"]["paArtifact"]["sha256"] == "44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b"
    assert pair["durationModel"]["artifact"]["sha256"] == "f64f82b4fadf35acd3418bc298548c48bb73cf624fe8c70ba01a87c33e8d2370"
    assert utc(pair["sourceCutoff"]["evidenceAvailableAt"]) <= utc(pair["forecastCreatedAt"]) < utc(pair["deadlineUtc"])
    studies = [{"name": "2026-09-11 COL-DET duration", "pair": pair, "pairReference": pointer["pair"],
                "publicationReceipt": pointer["publicationReceipt"], "population": read(pair["population"]),
                "component": pair["durationModel"]["artifact"], "summaryOnly": False,
                **consumer_identities(pair, pointer["pair"])}]
    component_path = TRANSITION / f"components/sha256/{COMPONENT}/transition.json"
    assert reference(component_path)["sha256"] == COMPONENT
    component = json.loads(component_path.read_text())
    assert component["priorStrength"] == 20 and component["legalFloor"] == 1e-6
    for digest in PAIR_SHAS:
        pair_path = TRANSITION / f"prospective-pairs/sha256/{digest}/pair.json"
        pair_ref = reference(pair_path)
        assert pair_ref["sha256"] == digest
        p = read(pair_ref)
        guard(p)
        assert p["sourceGameId"] in {"823496", "824712"}
        assert p["componentSha256"] == COMPONENT and p["simulationCountPerConfiguration"] == 5000 and p["masterSeed"] == 20260907
        assert p["outcomeRead"] is False and p["candidateAuthority"] is False
        assert p["identicalPregameInputs"] and not p["paModelChanged"] and not p["starterUsageChanged"]
        assert utc(p["baselineForecastCreatedAtUtc"]) <= utc(p["changeSimulationStartedAtUtc"]) <= utc(p["pairFrozenAtUtc"]) < utc(p["policyCutoffUtc"]) < utc(p["scheduledStartUtc"])
        bundle = load_baseline(p["sourceForecastObjectSha256"])
        forecast = bundle["forecast"]
        assert p["gameId"] == forecast["gameId"] and p["sourceGameId"] == forecast["sourceGameId"]
        assert p["teams"] == forecast["teams"] and utc(p["scheduledStartUtc"]) == utc(forecast["scheduledStart"])
        cutoff = bundle["execution"]["sourceCutoff"]
        assert cutoff == forecast["sourceCutoff"]
        assert utc(cutoff["evidenceAvailableAt"]) <= utc(forecast["capturedAt"]) <= utc(forecast["forecastCreatedAt"])
        for k, value in compact(bundle["baseline"]).items():
            if k == "meanRunDifferential" and "meanMargin" in p["baseline"]:
                k = "meanMargin"
            if k in p["baseline"]:
                assert np.isclose(value, p["baseline"][k], rtol=0, atol=1e-12)
        pop = {"reference": bundle["baseline"]}
        if "population" in p:
            execution = read(p["executionReceipt"])
            assert execution["population"] == p["population"] and execution["sourceCutoff"] == cutoff
            assert execution["execution"]["component"]["sha256"] == COMPONENT
            assert execution["gameId"] == p["gameId"] and execution["forecastObjectSha256"] == p["sourceForecastObjectSha256"]
            assert execution["pairedMonteCarloCoupling"] is True
            with np.load(verified(p["population"]), allow_pickle=False) as arrays:
                for k in ("homeRuns", "awayRuns", "innings", "paCounts"):
                    assert np.array_equal(arrays["baseline_" + k], bundle["baseline"][k])
                pop["challenger"] = {k: arrays["change_" + k].tolist() for k in ("homeRuns", "awayRuns", "innings", "paCounts")}
            for k, v in compact({**pop["challenger"], "illegalStateCount": 0, "nonterminationCount": 0}).items():
                assert np.isclose(v, p["change"][k], rtol=0, atol=1e-12)
        p = {**p, "commonPairId": "mlb-transition-pair-" + digest, "resolvedSourceCutoff": cutoff}
        studies.append({"name": "2026-09-12 " + p["teams"]["AWAY"]["abbreviation"] + "-" + p["teams"]["HOME"]["abbreviation"] + " transition",
                        "pair": p, "pairReference": pair_ref, "population": pop, "component": reference(component_path),
                        "summaryOnly": "challenger" not in pop, "baselineManifest": bundle["manifest"],
                        **consumer_identities(p, pair_ref),
                        "baselineInputs": reference(bundle["directory"] / "execution-inputs.json")})
    return studies


def summary_score(study, final):
    """Use saved candidate scalars; never manufacture a candidate distribution."""
    pair, pop = study["pair"], study["population"]
    home, away = _score_integer(final["homeScore"]), _score_integer(final["awayScore"])
    assert final["status"] == "FINAL" and final["gameId"] == pair["gameId"] and home != away
    observed = {"homeRuns": home, "awayRuns": away, "totalRuns": home + away, "homeMargin": home - away}
    arms = {}
    for key, summary in (("reference", pair["baseline"]), ("challenger", pair["change"])):
        p = summary["homeWinProbability"]
        prob = np.clip(p, WIN_LOGLOSS_FLOOR, 1 - WIN_LOGLOSS_FLOOR)
        means = {"homeRuns": summary["meanHomeRuns"], "awayRuns": summary["meanAwayRuns"], "totalRuns": summary["meanTotalRuns"], "homeMargin": summary["meanMargin"]}
        assert np.isclose(means["homeRuns"] + means["awayRuns"], means["totalRuns"], atol=1e-12, rtol=0)
        assert np.isclose(means["homeRuns"] - means["awayRuns"], means["homeMargin"], atol=1e-12, rtol=0)
        arms[key] = {"arm": "V18_BASE" if key == "reference" else "V18_TRANSITION_ONLY", "simulations": 5000,
                     "homeWinProbability": p, "observedHomeWin": int(home > away),
                     "winnerLogLoss": float(-np.log(prob if home > away else 1 - prob)), "winnerBrier": (p - int(home > away))**2,
                     "marginals": {name: {"observed": value, "predictedMean": means[name], "signedError": means[name] - value,
                                           "absoluteError": abs(means[name] - value), "squaredError": (means[name] - value)**2,
                                           "crps": None, "centralPredictionIntervals": None} for name, value in observed.items()},
                     "jointEuclideanEnergyScore": None}
    h, a = np.asarray(pop["reference"]["homeRuns"]), np.asarray(pop["reference"]["awayRuns"])
    draws = {"homeRuns": h, "awayRuns": a, "totalRuns": h + a, "homeMargin": h - a}
    arms["reference"]["marginals"] = {name: _marginal(draws[name], value) for name, value in observed.items()}
    arms["reference"]["jointEuclideanEnergyScore"] = joint_energy_score(h, a, (home, away))
    delta = {name: arms["challenger"][name] - arms["reference"][name] for name in ("winnerLogLoss", "winnerBrier")}
    delta["marginals"] = {name: {metric: arms["challenger"]["marginals"][name][metric] - arms["reference"]["marginals"][name][metric]
                                         for metric in ("predictedMean", "signedError", "absoluteError", "squaredError")} for name in observed}
    return {"schemaVersion": "MLB_FROZEN_SUMMARY_PAIR_SCORING_V1", "commonPairId": pair["commonPairId"], "gameId": pair["gameId"],
            "status": "SCORED_ONE_MATCHED_GAME_SUMMARY_MEASURES_ONLY", "final": final,
            "scoreIdentity": _digest({"schema": "MLB_FROZEN_SUMMARY_PAIR_SCORING_V1", "pairSha256": study["pairReference"]["sha256"], "final": _final_identity(final)}),
            "arms": arms, "challengerMinusReference": delta,
            "unavailable": ["Candidate CRPS, joint energy, intervals and paired Monte Carlo uncertainty: original candidate draws/distributions were not retained."],
            "accounting": {"matchedGames": 1, "simulationDrawsPerArm": 5000, "candidateDrawsRetained": 0},
            "definitions": {"delta": "candidate minus baseline; negative loss/absolute-error/CRPS differences favor candidate", "signedError": "predicted minus observed", "acrossGameConfidenceInterval": None}}


def run(root):
    root.mkdir(parents=True, exist_ok=True)
    with single_owner(root / "scoring.lock") as owns:
        if not owns:
            return {"status": "DEFERRED_EXISTING_SCORING_OWNER"}
        studies = preflight()
        audit = [{k: v for k, v in s.items() if k != "population"} for s in studies]
        preflight_ref = save("identity-before-outcomes.json", {"verifiedAtUtc": datetime.now(timezone.utc).isoformat(), "studies": audit,
            "wholeGameQuarantineApplied": True, "sealedFinalOotExcluded": True, "outcomesRead": False}, root)
        from dotenv import dotenv_values
        database_url = dotenv_values(Path("C:/Users/james/ai-sports-predictor/.env"))["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql+psycopg2://")
        finals = read_persisted_finals([s["pair"] for s in studies], database_url=database_url)
        final_ref = save("persisted-final-read.json", finals, root)
        by_game = {row["gameId"]: row for row in finals["records"]}
        rows = []
        for s in studies:
            p = s["pair"]
            final = by_game.get(p["gameId"])
            row = {"study": s["name"], "gameId": p["gameId"], "sourceGameId": p["sourceGameId"], "pair": s["pairReference"],
                   "summaryOnly": s["summaryOnly"], **consumer_identities(p, s["pairReference"])}
            if not final or final["status"] != "FINAL":
                row.update(status="AWAITING_ELIGIBLE_FINAL", prerequisite=(final or {}).get("reason", (final or {}).get("status", "PERSISTED_FINAL_NOT_AVAILABLE")), finalMetadata=final)
            else:
                value = summary_score(s, final) if s["summaryOnly"] else score_pair(p, s["population"], final)
                if s["name"].endswith("transition"):
                    value["arms"]["reference"]["arm"] = "V18_BASE"
                    value["arms"]["challenger"]["arm"] = "V18_TRANSITION_ONLY"
                key = root / "score-keys" / (value["scoreIdentity"] + ".json")
                if key.exists():
                    score_ref = json.loads(key.read_text()); read(score_ref)
                else:
                    score_ref = save("paired-game-score.json", {**value, "pairReference": s["pairReference"], "component": s["component"], "finalRead": final_ref}, root)
                    atomic_state(key, score_ref)
                atomic_state(root / "scores-by-pair" / (p["commonPairId"] + ".json"), score_ref)
                row.update(status=value["status"], score=score_ref, finalRevision=final["sourceRevision"], finalOutcomeId=final["sourceOutcomeId"],
                           observed={"home": final["homeScore"], "away": final["awayScore"]}, arms=value["arms"], candidateMinusBaseline=value["challengerMinusReference"])
                row["componentEvidence"] = final.get("starterEvidence") if "duration" in s["name"] else {"status": "TRANSITION_SEQUENCE_UNAVAILABLE", "reason": "No governed postgame transition sequence bound to this final revision is present in the frozen pair; protocol transition metrics remain unassessed."}
            rows.append(row)
        report = {"schemaVersion": "MLB_THREE_EXISTING_FROZEN_PAIR_SCORING_V1", "asOfUtc": datetime.now(timezone.utc).isoformat(),
                  "identityAudit": preflight_ref, "finalRead": final_ref, "studies": rows,
                  "requiredOwnerAction": "Claude: through the existing governed outcome ingest, persist revisioned game_final_outcomes for these exact canonical UUIDs/source IDs and original starts. Required fields are id, game_id, outcome_status=FINAL, revision, created_at, final_at after scheduled start and no later than query time, plus non-null nonnegative integer home_score and away_score in original home/away orientation. The newest revision must itself be eligible FINAL; never revive an older final or substitute canonical games score columns. KC-BOS must first reach a genuine final. Optional starter BF/transition evidence may follow separately.",
                  "scoredGames": sum("score" in r for r in rows), "pendingGames": sum("score" not in r for r in rows),
                  "deltaConvention": "Candidate minus baseline. Negative log loss/Brier/absolute-error/CRPS/energy differences favor candidate. Signed run error is predicted minus observed.",
                  "aggregation": "Studies remain separate: baseline/source horizons and duration/transition interventions differ. No pooled ensemble comparison.",
                  "verdict": "INSUFFICIENT_EVIDENCE", "modelFits": 0, "newSimulations": 0, "providerCalls": 0, "aispWrites": 0}
        result = save("scoring-findings.json", report, root)
        atomic_state(root / "current.json", result)
        lines = ["Existing frozen MLB pairs", "", report["deltaConvention"], "", "| Study | Status | Final H-A | Δ log loss | Δ Brier |", "|---|---|---:|---:|---:|"]
        for row in rows:
            d = row.get("candidateMinusBaseline", {})
            lines.append("| " + row["study"] + " | " + row["status"] + " | " + (f"{row['observed']['home']}-{row['observed']['away']}" if "observed" in row else "Pending") + " | " + (f"{d['winnerLogLoss']:+.6f}" if d else "—") + " | " + (f"{d['winnerBrier']:+.6f}" if d else "—") + " |")
        lines += ["", "NYM–NYY candidate distributions were not retained; its eligible measurements are winner and mean-score errors. Missing optional component truth does not block whole-game scoring.", "", report["aggregation"], "", "One pair is one observed game; 5,000 draws measure simulation precision, not 5,000 independent assessment observations.", "", "Run: `.venv/Scripts/python.exe scripts/score_mlb_frozen_component_pairs_v1.py`", "", "Immutable result: " + result["path"] + " (SHA256 " + result["sha256"] + ")"]
        (root / "scoring-findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"result": result, "scoredGames": report["scoredGames"], "pendingGames": report["pendingGames"], "states": [{k: r[k] for k in ("study", "status", "prerequisite") if k in r} for r in rows]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output_root.resolve()), indent=2))
