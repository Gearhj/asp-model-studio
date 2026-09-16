"""Fit one bounded drive research design and publish independent current simulations."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import joblib
import numpy as np
from sklearn.metrics import log_loss

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_nfl_m1.labs_simulation import (
    AUTHORITY, FAMILY, file_record, immutable_json, publish_object,
    summarize_scores, verify_object, utc,
    pregame_clock, PregameClosed,
    registered_source_availability,
)
from server.sports_nfl_m1.labs_simulation_drives import (
    DRIVE_ENGINE, FEATURES, RULES_URL, enrich_pregame, fit_drive_model,
    load_development_drives, simulate_drive_game, verify_drive_accounting,
)


def pmf(values: np.ndarray, field: str) -> list[dict]:
    observed, counts = np.unique(values, return_counts=True)
    return [{field: int(x), "probability": float(n/len(values))} for x, n in zip(observed, counts, strict=True)]


def run(exchange: Path, output: Path, bronze: Path, *, draws: int = 1000,
        clock: Callable[[], datetime] | None = None) -> dict:
    clock = clock or (lambda: datetime.now(timezone.utc))
    predecessor_handoff = output / "sha256/007b3fca4931f912752f43f59e8fd0e9f012c1e434c2ca3f18a90abb46fa57c0/drive-handoff.json"
    declaration = {"schemaVersion": "NFL_LABS_DRIVE_MATRIX_V1", "engine": DRIVE_ENGINE,
                   "predecessorHandoff": file_record(predecessor_handoff),
                   "correction": "STARTING_KICKOFF_PLAY_ONLY_TOUCHBACK_AUTHORITY_AND_PER_EVENT_RUNTIME_PUBLICATION_CLOCK",
                   "trainingSeasons": list(range(2018, 2024)), "validationSeason": 2024,
                   "finalTrainingSeasons": list(range(2018, 2025)), "features": FEATURES,
                   "algorithm": "STANDARDIZED_MULTINOMIAL_LOGISTIC_C1_MAXITER300_PLUS_CONDITIONAL_EMPIRICAL_PROGRESSION",
                   "statePrior": {"leagueInitializationPointsPerDrive": 2.0, "equivalentPriorDrives": 40, "offseasonExposureRetention": .65},
                   "gridSearch": False, "validationUnit": "observed drive state; not an unbiased pregame forecast test",
                   "populationDrawsPerEvent": draws, "seed": 930731,
                   "scenarios": ["BASE", "PACE_DURATION_0.95"], "sealedOotAccess": False}
    declaration_ref = immutable_json(output / "drive-matrix-v2.json", declaration)
    run_root = output / "drive-research" / declaration_ref["sha256"]
    run_root.mkdir(parents=True, exist_ok=True)
    artifact_path = run_root / "drive-model.joblib"
    receipt_path = run_root / "fit-receipt.json"
    if receipt_path.exists():
        fit_receipt = json.loads(receipt_path.read_bytes())
        if file_record(artifact_path) != fit_receipt["modelArtifact"]: raise ValueError("saved model hash differs")
        model = joblib.load(artifact_path)
        print("reloaded completed drive fit", flush=True)
    else:
        drives, source = load_development_drives(bronze)
        drives = enrich_pregame(drives)
        print(f"loaded {len(drives)} Development drives; sources2018--2024 only", flush=True)
        training = fit_drive_model(drives, end_season=2023)
        valid = drives.loc[drives["season"].eq(2024)]
        probability = training.estimator.predict_proba(valid[FEATURES].to_numpy(float))
        labels = training.estimator[1].classes_
        train_y = drives.loc[drives["season"].le(2023), "outcome"]
        reference = np.array([float((train_y == kind).mean()) for kind in labels])
        baseline = np.tile(reference, (len(valid), 1))
        evaluation = {"validationSeason": 2024, "validationDriveCount": len(valid),
                      "validationGameCount": int(valid["gameId"].nunique()), "trainingDriveCount": training.training_drives,
                      "trainingCutoff": training.training_cutoff, "classOrder": labels.tolist(),
                      "conditionalDriveLogLoss": float(log_loss(valid["outcome"], probability, labels=labels)),
                      "unconditionalDriveLogLoss": float(log_loss(valid["outcome"], baseline, labels=labels)),
                      "multiclassBrierSum": float(np.mean(np.sum((probability-(valid["outcome"].to_numpy()[:,None] == labels))**2, axis=1))),
                      "interpretation": "Chronological held-out drive-state prediction. Not independent evidence of accurate pregame game win probabilities or wagering advantage."}
        print(json.dumps(evaluation), flush=True)
        model = fit_drive_model(drives, end_season=2024)
        with artifact_path.open("xb") as stream: joblib.dump(model, stream)
        reloaded = joblib.load(artifact_path)
        fixture = valid[FEATURES].to_numpy(float)[:16]
        difference = float(np.max(np.abs(model.estimator.predict_proba(fixture)-reloaded.estimator.predict_proba(fixture))))
        if difference != 0: raise ValueError("frozen drive model reload mismatch")
        fit_receipt = {"schemaVersion": "NFL_LABS_DRIVE_FIT_RECEIPT_V1", **AUTHORITY,
                       "declaration": declaration_ref, "modelArtifact": file_record(artifact_path), "sourceEvidence": source,
                       "evaluation": evaluation, "reloadMaximumAbsoluteMismatch": difference,
                       "trainingCutoff": model.training_cutoff, "modelsFit": 2, "predecessorHandoff": file_record(predecessor_handoff),
                       "rules": {"sourceUrl": RULES_URL, "regulation": "two30-minute halves, four15-minute quarters",
                                 "regularOvertime": "10-minute cap since2017; both possession opportunities since2025 subject to clock; defensive first-possession score can end game",
                                 "historicalRegularOvertime": "2018--2024 opening TD wins, opening FG permits response",
                                 "postseason": "15-minute periods with guaranteed response since2022; V1 publication excludes postseason because multi-period continuation is not implemented"}}
        immutable_json(receipt_path, fit_receipt)
        model = reloaded
        print("fitted and persisted independent drive research model; reload exact", flush=True)
    pointer_path = exchange / FAMILY / "current.json"
    pointer = json.loads(pointer_path.read_bytes())
    source_availability = registered_source_availability(bronze, fit_receipt)
    predecessors = {}
    for item in json.loads(predecessor_handoff.read_bytes())["artifacts"]:
        old = verify_object(item)
        predecessors[(old["eventId"], old["scenario"]["scenarioId"])] = item
    artifacts, skips = [], []
    for reference in pointer["artifacts"]:
        if reference["artifactSchemaVersion"] != "NFL_LABS_SCORE_DISTRIBUTION_V1": continue
        original = verify_object(reference)
        home = original["homeTeam"]["abbreviation"]
        away = original["awayTeam"]["abbreviation"]
        # NFL canonical abbreviations are current franchises; PBP history can use LA.
        aliases = {"LAR": "LA", "WSH": "WAS"}
        engine_home, engine_away = aliases.get(home, home), aliases.get(away, away)
        for scenario, pace in (("BASE", 1.0), ("PACE_DURATION_0.95", .95)):
            try:
                inference_started = pregame_clock(original["scheduledStartUtc"], clock=clock, stage="EVENT_INFERENCE")
            except PregameClosed as exc:
                skips.append({"eventId": original["eventId"], "scenarioId": scenario, "reason": str(exc)})
                continue
            case_identity = {"eventId": original["eventId"], "engine": DRIVE_ENGINE,
                             "modelSha256": fit_receipt["modelArtifact"]["sha256"], "scenario": scenario,
                             "draws": draws, "seed": 930731}
            case_sha = hashlib.sha256(canonical_json_bytes(case_identity)).hexdigest()
            saved = run_root / "populations" / f"{case_sha}.json"
            if saved.exists():
                record = json.loads(saved.read_bytes())
                # Prefer an existing immutable metadata correction of this same
                # numerical forecast rather than resurrecting a date-boundary label.
                for current_ref in pointer["artifacts"]:
                    if current_ref["forecastId"] == record["forecastId"]:
                        current_record = verify_object(current_ref)
                        if current_record.get("sourceAvailability") == source_availability:
                            record = current_record
                            break
            else:
                games = [simulate_drive_game(model, home_team=engine_home, away_team=engine_away,
                                             season=2026, postseason=False, seed=930731+i, pace_multiplier=pace)
                         for i in range(draws)]
                home_scores = np.array([g["homeScore"] for g in games]); away_scores = np.array([g["awayScore"] for g in games])
                pairs, counts = np.unique(np.column_stack([home_scores, away_scores]), axis=0, return_counts=True)
                choices = {}
                total = home_scores+away_scores; margin = home_scores-away_scores
                desired = [("Typical", np.argsort(np.abs(total-np.median(total))+np.abs(margin-np.median(margin)))),
                           ("Home win", np.flatnonzero(margin > 0)), ("Away win", np.flatnonzero(margin < 0)),
                           ("High scoring", np.argsort(-total)), ("Low scoring", np.argsort(total)),
                           ("Overtime", np.array([i for i,g in enumerate(games) if g["reachedOvertime"]]))]
                used = set()
                for label, indices in desired:
                    index = next((int(i) for i in indices if int(i) not in used), None)
                    if index is not None: choices[label] = index; used.add(index)
                reps = [{"label": label, "simulationIndex": i, **games[i]} for label, i in choices.items()]
                for rep in reps: verify_drive_accounting(rep)
                try:
                    created_at = pregame_clock(original["scheduledStartUtc"], clock=clock, stage="FORECAST_CREATION")
                except PregameClosed as exc:
                    skips.append({"eventId": original["eventId"], "scenarioId": scenario, "reason": str(exc),
                                  "inferenceStartedUtc": inference_started.isoformat(), "populationNotPublished": True})
                    continue
                record = {"schemaVersion": "NFL_LABS_DRIVE_SIMULATION_V1", **AUTHORITY, "sport": "NFL",
                          "forecastId": f"asp-nfl-drive-research:sha256:{case_sha}", "eventId": original["eventId"],
                          "homeTeam": original["homeTeam"], "awayTeam": original["awayTeam"],
                          "model": {"engineId": DRIVE_ENGINE, "engineVersion": DRIVE_ENGINE, "modelArtifact": fit_receipt["modelArtifact"], "trainingCutoff": model.training_cutoff},
                          "relatedM1ForecastId": original["forecastId"], "explainsM1Forecast": False,
                          "predecessorArtifact": predecessors.get((original["eventId"], scenario)),
                          "scheduledStartUtc": original["scheduledStartUtc"], "forecastCreatedUtc": created_at.isoformat(),
                          "inferenceStartedUtc": inference_started.isoformat(),
                          "sourceCutoffUtc": source_availability["sourceCutoffUtc"], "sourceAvailability": source_availability,
                          "historicalEvidenceThroughDate": model.training_cutoff,
                          "historicalEvidencePrecision": "GAME_DATE_NOT_COMPLETION_OR_RELEASE_TIMESTAMP", "publishedAtUtc": None,
                          "drawCount": draws, "seed": 930731, "scoreSummary": summarize_scores(home_scores, away_scores),
                          "jointScoreDistribution": [{"homeScore": int(pair[0]), "awayScore": int(pair[1]), "probability": float(count/draws)} for pair,count in zip(pairs,counts,strict=True)],
                          "scoreMarginDistribution": pmf(margin, "homeMinusAway"), "totalScoreDistribution": pmf(total, "totalScore"),
                          "populationFinals": [{"simulationIndex": i, "homeScore": g["homeScore"], "awayScore": g["awayScore"], "seed": g["seed"], "driveCount": len(g["drives"]), "reachedOvertime": g["reachedOvertime"], "regulationTie": g["regulationTie"], "finalTie": g["finalTie"]} for i,g in enumerate(games)],
                          "quantiles": {name: {str(q): float(np.quantile(values,q)) for q in (.05,.25,.5,.75,.95)} for name,values in (("marginHomeMinusAway",margin),("total",total))},
                          "simulatedDrives": reps, "representativeFinals": [{"homeScore": g["homeScore"], "awayScore": g["awayScore"], "simulationIndex": g["simulationIndex"]} for g in reps],
                          "regulationTieProbability": float(np.mean([g["regulationTie"] for g in games])),
                          "reachingOvertimeProbability": float(np.mean([g["reachedOvertime"] for g in games])),
                          "finalTieProbability": float(np.mean(home_scores == away_scores)),
                          "scenario": {"scenarioId": scenario, "modelInputChange": scenario != "BASE", "paceDurationMultiplier": pace, "interpretation": "controlled duration sensitivity, not a forecast of a team's tactical choice"},
                          "sourceEvidence": {"fitReceipt": file_record(receipt_path), "evidenceSeason": 2024, "currentTeamState": "DEVELOPMENT_2024_STATE_DISCOUNTED_TWO_OFFSEASONS; 2025 SEALED_NOT_READ", "pregameQbInformation": "NOT_CONSUMED_NO_CURRENT_STARTER_ASSERTED"},
                          "generatingLaw": {"id": DRIVE_ENGINE, "representation": "FITTED_CONDITIONAL_OUTCOME_AND_EMPIRICAL_DRIVE_PROGRESSION", "calibration": "RAW_UNCALIBRATED", "coherentScoreAccounting": True,
                                            "kickoffTouchbackEvidence": "ACTUAL_SINGLE_STARTING_KICKOFF_BEFORE_FIRST_SCRIMMAGE; ABSENT_AMBIGUOUS_OR_MISSING_FLAG_EXCLUDED_FROM_KICKOFF_BANK"},
                          "limitations": ["Research mechanics model; current team evidence stops at2024 season, not current2026 injuries/QB/rosters.", "Regular-season only. Postseason multi-period overtime is not supported.", "No play/player/route/tackle identities. Drive endpoints are sampled; within-drive physical paths are not generated.", "Pace multiplier is a declared model sensitivity, not a fitted strategy or intervention effect.", "Kickoff touchbacks use standard current35-yard spot; landing-zone20-yard exception, onside kicks, detailed timeout/penalty and within-drive decision strategy are not modeled.", "Observed drive-state validation is not full-game prospective calibration evidence; do not rank this engine against M1 without a separate matched pregame evaluation.", "Progression is sampled jointly within outcome and20-yard start band; rare unobserved next-possession field positions use an explicit no-return treatment."]}
            try:
                publication_at = pregame_clock(original["scheduledStartUtc"], clock=clock, stage="PUBLICATION")
            except PregameClosed as exc:
                skips.append({"eventId": original["eventId"], "scenarioId": scenario, "reason": str(exc), "populationNotPublished": True})
                continue
            if not saved.exists():
                record["publishedAtUtc"] = publication_at.isoformat()
                immutable_json(saved, record)
            item = publish_object(record, exchange / FAMILY); verify_object(item); artifacts.append(item)
            print(f"published drive population {original['eventId']} {scenario} {draws}", flush=True)
    completed_at = utc(clock())
    receipt = {"schemaVersion": "NFL_LABS_DRIVE_HANDOFF_V1", **AUTHORITY, "publishedAtUtc": completed_at.isoformat(),
               "engineId": DRIVE_ENGINE, "predecessorHandoff": file_record(predecessor_handoff), "skips": skips,
               "artifactCount": len(artifacts), "artifacts": artifacts, "fitReceipt": file_record(receipt_path),
               "baseEventCount": sum(json.loads(Path(a["artifact"]["path"]).read_bytes())["scenario"]["scenarioId"] == "BASE" for a in artifacts)}
    digest = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
    handoff = immutable_json(output / "sha256" / digest / "drive-handoff.json", receipt)
    # Keep exact-distribution discovery intact; add independent engines only when complete.
    merged = {**pointer, "publishedAtUtc": completed_at.isoformat(), "artifacts": [a for a in pointer["artifacts"] if a["artifactSchemaVersion"] != "NFL_LABS_DRIVE_SIMULATION_V1"]+artifacts,
              "driveResearchHandoff": handoff, "driveResearchArtifactCount": len(artifacts)}
    temporary = pointer_path.with_suffix(f".{os.getpid()}.tmp")
    with temporary.open("xb") as stream: stream.write(canonical_json_bytes(merged))
    os.replace(temporary,pointer_path)
    return {"handoff": handoff, "fitReceipt": fit_receipt, "artifactCount": len(artifacts)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--draws",type=int,default=1000)
    args = parser.parse_args()
    result = run(Path(r"C:\Users\james\asp-model-exchange"), Path("outputs/nfl-labs-simulation-v1"),
                 Path(r"C:\Users\james\asp-data-staging\nfl\bronze-v1"), draws=args.draws)
    print(json.dumps({key:value for key,value in result.items() if key != "fitReceipt"},indent=2))
