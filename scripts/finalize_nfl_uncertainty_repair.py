"""Publish the completed bounded repair; never fit or touch AISP/MLB."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from server.sports_nfl_m1.current_state_repair_study import OUTPUT, checked
from server.sports_nfl_m1.current_state_repaired_model import UNCERTAINTY_ONLY_NAMES, MODEL_IDS
from server.sports_nfl_m1.current_state_repaired_publication import publish_repaired_current_v2
from server.sports_nfl_m1.current_state_registration import register_study
from server.sports_nfl_m1.current_state_study import EVIDENCE, publish_json
from server.sports_nfl_m1.forward_vintages import _pointer
from server.sports_nfl_m1.labs_simulation import file_record, verify_object, utc


def finalize(result_path, tests_path):
    result_path = Path(result_path).resolve()
    if not result_path.is_relative_to((OUTPUT / "runs").resolve()):
        raise ValueError("COMPLETED_DEDICATED_REPAIR_PATH_REQUIRED")
    result_ref = file_record(result_path)
    result = json.loads(result_path.read_bytes())
    if (result.get("repairContract") != "NFL_UNCERTAINTY_MEAN_SEPARATION_REPAIR_RESULT_V1"
            or not result.get("completedAtUtc") or result.get("finalOotAccessed") is not False):
        raise ValueError("COMPLETED_REPAIR_DEVELOPMENT_EVIDENCE_REQUIRED")
    for ref in result["artifacts"]:
        checked(ref)
    predecessor = json.loads(checked(result["predecessor"]).read_bytes())
    for ref in predecessor["artifacts"]:
        checked(ref)
    admission_path = OUTPUT.parent / "reconstructed-study-v1/corrective-admission/supplements/sha256/1cff387543e7401da00cc6f1512444b0c70884948d1f6878f51d8bcdc6843586/admission.json"
    admission_ref = file_record(admission_path)
    if admission_ref["sha256"] != "1cff387543e7401da00cc6f1512444b0c70884948d1f6878f51d8bcdc6843586":
        raise ValueError("PREDECESSOR_WITHHOLDING_RECEIPT_CHANGED")
    admission = json.loads(admission_path.read_bytes())
    original_handoff = json.loads(checked(admission["originalHandoff"]).read_bytes())
    for ref in original_handoff["forecasts"]:
        checked(ref)
    for ref in original_handoff["artifacts"]:
        verify_object(ref)
    current_path = OUTPUT.parent / "reconstructed-study-v1/CURRENT.json"
    previous_pointer_identity = file_record(current_path)
    previous = json.loads(current_path.read_bytes())
    declaration = json.loads(checked(result["declaration"]).read_bytes())
    team = pd.read_parquet(checked(result["sourceRefs"]["sufficient-statistics-team.parquet"]))
    qb = pd.read_parquet(checked(result["sourceRefs"]["sufficient-statistics-qb.parquet"]))
    system = joblib.load(checked(result["finalModel"]))
    # An actual saved-state fixture proves final fitted means and finite-population
    # means are invariant too. This is implementation evidence, not an additional
    # validation observation or a forecast issued at this historical timestamp.
    last_fold = next(ref for ref in result["fittedModels"]
                     if ref["lagHours"] == 48 and ref["validationSeason"] == 2024)
    fold_check = json.loads(Path(last_fold["path"]).with_name("verification.json").read_bytes())
    fixture = pd.read_parquet(checked(fold_check["stateSource"])).head(1)
    changed = fixture.copy()
    for name in (*UNCERTAINTY_ONLY_NAMES, *[name for name in changed if name.endswith("__posterior_sd")]):
        changed[name] = 123.
    baseline = system.predict_states(fixture, draws=5000)
    perturbed = system.predict_states(changed, draws=5000)
    final_invariance = sum(int(np.count_nonzero(baseline[name][field] != perturbed[name][field]))
        for name in MODEL_IDS for field in ("scoreMeans", "distributionScoreMeans"))
    if final_invariance:
        raise ValueError("FINAL_ARTIFACT_UNCERTAINTY_MEAN_INVARIANCE_FAILED")
    publication_args = dict(source_receipt=declaration["sourceEvidence"],
                            ensemble_weight=result["finalEnsembleResidualWeight"])
    publication = publish_repaired_current_v2(system, team, qb, result["finalModel"], result_ref,
        OUTPUT / "current-publication", **publication_args)
    handoff = json.loads(checked(publication["handoff"]).read_bytes())
    manifest = json.loads(checked(publication["manifest"]).read_bytes())
    for ref in manifest["files"]:
        checked(ref)
    for ref in handoff["artifacts"]:
        verify_object(ref)
    orientations, mean_error = 0, 0.
    for ref in handoff["forecasts"]:
        forecast = json.loads(checked(ref).read_bytes())
        if not (utc(forecast["forecastCutoffUtc"]) <= utc(forecast["forecastCreatedUtc"])
                <= utc(forecast["publishedAtUtc"]) < utc(forecast["scheduledStartUtc"])):
            raise ValueError("FORECAST_NOT_ACTUALLY_PREGAME")
        joint = forecast["jointScoreDistribution"]
        home = sum(item["homeScore"]*item["count"] for item in joint)/5000
        away = sum(item["awayScore"]*item["count"] for item in joint)/5000
        if (sum(item["count"] for item in joint) != 5000
                or home != forecast["expectedHomeScore"] or away != forecast["expectedAwayScore"]
                or not np.isclose(home-away, forecast["expectedMarginHomeMinusAway"], rtol=0, atol=1e-12)):
            raise ValueError("HOME_AWAY_POPULATION_ORIENTATION_DIFFERS")
        mean_error = max(mean_error, abs(home-forecast["scoreMeanEstimator"]["home"]),
                         abs(away-forecast["scoreMeanEstimator"]["away"]))
        orientations += 1
    if mean_error > .5/5000+1e-12:
        raise ValueError("PUBLISHED_SCORE_MEAN_QUANTIZATION_EXCEEDED")
    # A fresh actual clock is used again: no backdated idempotency replay.
    repeated = publish_repaired_current_v2(system, team, qb, result["finalModel"], result_ref,
        OUTPUT / "current-publication", **publication_args)
    second = json.loads(checked(repeated["handoff"]).read_bytes())
    first_objects = {ref["forecastId"]: ref for ref in handoff["artifacts"]}
    repeat_objects = {ref["forecastId"]: ref for ref in second["artifacts"]}
    common = first_objects.keys() & repeat_objects.keys()
    mismatch = sum(first_objects[key] != repeat_objects[key] for key in common)
    if mismatch or repeat_objects.keys()-first_objects.keys() or repeated["reused"] != len(repeat_objects):
        raise ValueError("FROZEN_PUBLICATION_REPRODUCTION_OR_IDEMPOTENCY_FAILED")
    registration = register_study(result_ref, publication["handoff"])
    registration_repeat = register_study(result_ref, publication["handoff"])
    if registration_repeat["status"] != "NO_OP":
        raise ValueError("RESEARCH_REGISTRATION_NOT_IDEMPOTENT")
    tests_ref = file_record(Path(tests_path).resolve())
    tests = json.loads(checked(tests_ref).read_bytes())
    diagnostic = file_record(OUTPUT / "diagnostics/sha256/f140d1e4328593e758197a378acfb133091b0502585d6897b63fdbdcdb46c1ae/diagnostic.json")
    archive = file_record(OUTPUT / "archive-automation-operating-requirements.json")
    checked(previous_pointer_identity)
    previous_ref = publish_json(OUTPUT / "preserved-pointers", "previous-current.json", previous)
    delivery = {"contract": "NFL_UNCERTAINTY_REPAIR_DELIVERY_RECEIPT_V1", "evidenceClass": EVIDENCE,
        "study": result_ref, "publication": publication, "registration": registration,
        "registrationRerun": registration_repeat, "previousCurrentPointer": previous_ref,
        "diagnostic": diagnostic, "archiveOperatingRequirements": archive,
        "marketComparison": {"status": "NOT_RUN_IN_BOUNDED_UNCERTAINTY_REPAIR",
            "reason": "No new quote evidence or decision study authorized."},
        "tests": {"receipt": tests_ref, **tests},
        "verification": {"allStudyAndPublicationChecksumsValid": True,
            "finalModelUncertaintyMeanMismatchCount": final_invariance,
            "finalModelInvariantFixtureEventId": str(fixture.canonical_game_id.iloc[0]),
            "invariantFixtureIsNewForecastOrPerformanceEvidence": False,
            "allScoreDistributionObjectsValid": True, "pregameAndOrientationCheckedForecasts": orientations,
            "maximumPublishedMeanQuantizationError": mean_error,
            "publicationRerun": repeated, "commonRerunForecasts": len(common), "reproductionMismatchCount": mismatch,
            "modelFitsDuringFinalization": 0, "providerCalls": 0, "aispWrites": 0,
            "finalOotRead": False, "mlbChanges": False, "m1Retained": True,
            "predecessorStudyFilesReverified": len(predecessor["artifacts"]),
            "originalForecastsReverified": len(original_handoff["forecasts"]),
            "preservedOriginalWithheldForecastCount": admission["withheldForecastCount"],
            "originalWithholdingReceipt": admission_ref,
            "originalArtifactsAndWithheldOutputsPreserved": True},
        "completionBoundary": "STOP_NFL_EXPANSION_RETURN_TO_MLB; NO_PROMOTION_OR_WAGERING_AUTHORITY"}
    delivery_ref = publish_json(OUTPUT / "deliveries", "delivery.json", delivery)
    # Only the explicitly mutable research pointer moves; immutable predecessors
    # and their prior withheld-object admission receipts are preserved above.
    _pointer(current_path, {"status": "COMPLETED", "evidenceClass": EVIDENCE,
        "runId": result["runId"], "result": result_ref, "publication": publication["handoff"],
        "publicationDisposition": "REPAIRED_HISTORICAL_PRIOR_BASELINE", "qualityNotice": delivery_ref,
        "previousCurrentPointer": previous_ref,
        "marketComparisonDisposition": "NO_NEW_MARKET_STUDY_IN_REPAIR_SCOPE"})
    print(json.dumps({"delivery": delivery_ref, "publication": publication,
        "verification": delivery["verification"]}, indent=2), flush=True)
    return delivery_ref


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--tests", required=True, type=Path)
    args = parser.parse_args()
    finalize(args.result, args.tests)
