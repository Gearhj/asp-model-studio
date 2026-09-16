"""Package an explicitly selected evaluated V19 branch; never publish forecasts."""
from __future__ import annotations

import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "4"

import argparse
import hashlib
import json
import joblib
import numpy as np
import sklearn
from threadpoolctl import threadpool_limits

from server.sports_current_statcast.mlb_regime_baseline import RUNTIME
from server.sports_current_statcast.stage3_corrected_preprocessing_artifacts import load_research_pipeline
from server.sports_current_statcast.mlb_v19_meta import GLOBAL_ORDER, ENSEMBLE_NAMES
from server.sports_current_statcast.mlb_v19_executable import V19Executable
from server.sports_current_statcast.mlb_v19_launch_guard import require_v19_launch_authority
from reproduce_mlb_v19_baseline import load_safe_cache, BASE_SHA
from run_mlb_v19_study import OUT, GAME_PATH, join_teams, ref, write_json
from evaluate_mlb_v19_study import checked_artifact
from server.sports_datasets.consumer import canonical_json_bytes


def checked_completion(path):
    if not path.exists():
        raise ValueError("Required completed study artifact absent: " + str(path))
    value = json.loads(path.read_text())
    for entry in value.get("artifacts", []):
        checked_artifact(entry)
    return value


def main(selected):
    require_v19_launch_authority("EXECUTABLE_CANDIDATE_PACKAGING")
    # Selection is an explicit root-agent choice after the fixed evaluation,
    # never hidden here in a new model search or prospective source gate.
    decision_path = OUT / "evaluation/development-decision.json"
    study_path = OUT / "evaluation/meta-study-package.json"
    if not decision_path.exists() or not study_path.exists():
        raise ValueError("Complete the declared matched evaluation before packaging")
    decision = json.loads(decision_path.read_text())
    record = next((row for row in decision["candidates"] if row["model"] == selected), None)
    if record is None:
        raise ValueError("Selected branch is not one of the evaluated candidates")
    study = json.loads(study_path.read_text())
    for entry in study["evaluationArtifacts"].values():
        checked_artifact(entry)
    global_directory = OUT / "folds/fold-5"
    meta_directory = OUT / "meta/fold-5"
    global_complete = checked_completion(global_directory / "complete.json")
    meta_complete = checked_completion(meta_directory / "complete.json")
    base_metadata, raw, _ = load_safe_cache()
    history = join_teams(raw).reset_index(drop=True)
    frozen_descriptor = base_metadata["folds"][4]["model"]
    baseline = load_research_pipeline(frozen_descriptor, root=RUNTIME)
    model_assets = {name: ref(global_directory / (name + ".joblib")) for name in GLOBAL_ORDER[1:]}
    fitted_globals = {name: joblib.load(checked_artifact(entry)) for name, entry in model_assets.items()}
    fitted_meta = joblib.load(meta_directory / "meta-system.joblib")
    fixture_ref = ref(meta_directory / "reload-fixture.joblib")
    fixture = joblib.load(checked_artifact(fixture_ref))
    rows = fixture["rows"].reset_index(drop=True)
    if len(rows) != 32 or not rows.foldNumber.eq(5).all() or rows.game_date.astype(str).max() > "2026-08-06":
        raise ValueError("Expected the exact fold-5 physically Development-only 32-row fixture")
    lineage = {"schemaVersion": "MLB_V19_EXECUTABLE_ASSET_AUTHORITY_V1", "selectedBranch": selected,
        "probabilityScale": "CHRONOLOGICALLY_CALIBRATED", "selectionDecision": ref(decision_path),
        "selectedCandidateDecision": record, "studyPackage": ref(study_path),
        "baselineReceiptSha256": BASE_SHA, "frozenV18Model": {**frozen_descriptor, "root": str(RUNTIME)},
        "globalModels": model_assets, "fold5Meta": ref(meta_directory / "meta-system.joblib"),
        "rawDevelopmentHistory": base_metadata["artifacts"]["rawDevelopment"], "historyTeamIdentityMap": ref(GAME_PATH),
        "originalMatchedFixture": fixture_ref,
        "rawFeatureOrder": base_metadata["rawFeatureColumns"], "targetOrder": base_metadata["targetOrder"],
        "executableCode": [ref(ROOT / "server/sports_current_statcast/mlb_v19_executable.py"), ref(Path(__file__))],
        "modelCode": [ref(ROOT / ("server/sports_current_statcast/" + name)) for name in
            ("mlb_v19_models.py", "mlb_v19_meta.py", "mlb_v19_evaluation.py")],
        "researchDisposition": "PASSED_DECLARED_DEVELOPMENT_RULE_NOT_PROMOTED" if record["passesDevelopmentResearchRule"]
            else "REJECTED_BY_DECLARED_DEVELOPMENT_RULE_PRESERVED_EXECUTABLE_RESEARCH_EVIDENCE",
        "retainedModel": "V18", "wageringAuthority": False, "executionAllowedInAISP": False}
    lineage["runtime"] = {"python": sys.version, "numpy": np.__version__, "scikitLearn": sklearn.__version__,
                          "joblib": joblib.__version__, "nativeWorkers": 4}
    key = hashlib.sha256(canonical_json_bytes(lineage)).hexdigest()
    directory = OUT / "executables/sha256" / key
    directory.mkdir(parents=True, exist_ok=True)
    complete_path = directory / "package-complete.json"
    if complete_path.exists():
        complete = checked_completion(complete_path)
        if complete["inputAuthority"] != lineage:
            raise ValueError("Existing aggregate package authority differs")
        print(json.dumps(ref(complete_path), indent=2))
        return
    aggregate_path = directory / "aggregate-candidate.joblib"
    if aggregate_path.exists():
        raise ValueError("Incomplete package attempt retained; review before explicit recovery")
    aggregate = V19Executable(baseline, fitted_globals, fitted_meta, selected,
                              tuple(base_metadata["rawFeatureColumns"]), lineage)
    joblib.dump(aggregate, aggregate_path, compress=3)
    reloaded = joblib.load(aggregate_path)
    replay_records = []
    with threadpool_limits(limits=4):
        for calibrated, name in ((False, "rawProbabilities"), (True, "calibratedProbabilities")):
            probabilities = aggregate.predict_development_fixture(rows, history, calibrated=calibrated)
            replay = reloaded.predict_development_fixture(rows, history, calibrated=calibrated)
            if set(probabilities) != set(fixture[name]):
                raise ValueError("Compound fixture branch identities differ")
            for branch in probabilities:
                expected = fixture[name][branch]
                if not np.array_equal(probabilities[branch], expected) or not np.array_equal(replay[branch], expected):
                    raise ValueError("Compound full-stack fixture differs: " + branch + "/" + name)
                replay_records.append({"branch": branch, "scale": "calibrated" if calibrated else "raw",
                    "observations": len(rows), "mismatchCount": 0, "maximumAbsoluteDifference": 0.0})
    fixture_path = directory / "aggregate-reload-fixture.joblib"
    joblib.dump({"rows": rows, "semanticHistoryReference": base_metadata["artifacts"]["rawDevelopment"],
        "teamIdentityMapReference": ref(GAME_PATH), "expectedRaw": fixture["rawProbabilities"],
        "expectedCalibrated": fixture["calibratedProbabilities"],
        "selectedCalibratedProbabilities": fixture["calibratedProbabilities"][selected]}, fixture_path, compress=3)
    schema = {"schemaVersion": "MLB_V19_COMPOUND_INFERENCE_SCHEMA_V1", "fold": 5,
        "rawFeatureOrder": list(aggregate.raw_feature_order), "classOrder": base_metadata["targetOrder"],
        "frozenV18TreatedFeatureOrder": list(baseline.preprocessor.ordered_features),
        "globalBranches": {name: {"orderedEncodedMeanFeatures": model.ordered_features,
            "semanticMeanFeatures": model.semantic.feature_names, "uncertaintyOnlyFeatures": model.semantic.uncertainty_names,
            "semanticTrainingEnd": model.semantic.fitted_end, "clusterTrainingEnd": model.clusters.fitted_end,
            "clusterDomains": sorted(row["domain"] for row in model.clusters.reports), "regimeIndicatorOrder": model.regime_order,
            "nativeMissingTreatment": "EXACT_FROZEN_V18_TREATMENT_NO_GENERIC_FILL"}
            for name, model in fitted_globals.items()},
        "metaGlobalBranchOrder": list(fitted_meta.global_gate.branch_order),
        "metaGlobalWeights": fitted_meta.global_gate.weights.tolist(),
        "metaSpecialistBranchOrder": list(fitted_meta.specialist_gate.branch_order),
        "metaSpecialistWeights": fitted_meta.specialist_gate.weights.tolist(),
        "scalarTemperatures": fitted_meta.temperatures, "metaTrainingAuthority": fitted_meta.receipt,
        "trainingOrCurrentModeFallback": "PROHIBITED"}
    schema_ref = write_json(directory / "ordered-inference-schema.json", schema)
    operational = {"schemaVersion": "MLB_V19_COMPOUND_OPERATIONAL_READINESS_V1",
        "selectedBranch": selected, "passesDevelopmentRule": bool(record["passesDevelopmentResearchRule"]),
        "prospectiveReady": False, "verifiedSupportedCurrentGames": 0,
        "executableDevelopmentFixture": "VERIFIED_ZERO_MISMATCH", "fixtureRows": len(rows),
        "predictionScope": "EXACT_PA_PROBABILITIES_DEVELOPMENT_RELOAD_ONLY",
        "currentInputVectorsVerified": False, "currentPregameCutoffVerified": False,
        "currentWholeGameSimulationVerified": False,
        "currentSourceReadiness": "NOT_ESTABLISHED_CURRENT_V19_SOURCE_PACKAGE_REQUIRED",
        "verifiedSupportedProspectiveGames": 0, "currentScheduleInspectedByThisScript": False,
        "currentSourceInferencePerformed": False, "newForecastsPublished": 0,
        "availableSemanticHistoryMaximumDate": str(history.game_date.max()),
        "blockers": ["Current full 246-field vectors with original per-field observation/availability/retrieval provenance have not been validated for this aggregate.",
            "Semantic player/team class-history authority is the frozen Development cache through 2026-08-06, not current-slate evidence.",
            "Complete multiseason semantic history through the prior local game date, with explicit coverage/source failures, needs a current source composition bridge.",
            "Forward workload/roster additions are separately timestamped evidence and do not supply or relabel missing historical/current semantic team strength."],
        "simulationReadiness": "PA_PROBABILITY_EXECUTABLE_NOT_AN_END_TO_END_CURRENT_GAME_SIMULATION_PUBLICATION",
        "sourceAcquisitionCalls": 0, "modelFits": 0, "finalOotPayloadBytesRead": 0,
        "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED", "retainedModel": "V18",
        "executionAllowedInAISP": False, "wageringAuthority": False,
        "nextAction": "Preserve this research package; do not import or run it in AISP. Any subsequent prospective source bridge is a separate bounded assignment."}
    operational_ref = write_json(directory / "operational-readiness.json", operational)
    complete = {"schemaVersion": "MLB_V19_EXECUTABLE_RESEARCH_PACKAGE_V1", "inputAuthority": lineage,
        "artifacts": [ref(aggregate_path), ref(fixture_path), schema_ref, operational_ref],
        "fullStackReproduction": replay_records, "retainedOriginalForecastsModified": 0,
        "packageAuthority": "EXECUTABLE_RESEARCH_ONLY_NOT_OPERATIONAL_OR_PROMOTED",
        "modelFits": 0, "providerCalls": 0, "finalOotPayloadBytesRead": 0}
    write_json(complete_path, complete)
    print(json.dumps(ref(complete_path), indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", required=True, choices=[*GLOBAL_ORDER[1:], *ENSEMBLE_NAMES])
    args = parser.parse_args()
    main(args.branch)
