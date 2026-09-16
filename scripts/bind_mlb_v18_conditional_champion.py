"""Reference-only frozen V18 binding plus one 32-row Development reload fixture.

No model fitting, current game inference, provider, database or simulation calls.
Only existing isolated Development fixture bytes and accepted artifact stores
are read. Existing evidence and executable bytes are never rewritten or copied.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "4"

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import sklearn
from threadpoolctl import threadpool_limits

from server.sports_current_statcast import mlb_v18_daily_slate as daily
from server.sports_current_statcast.mlb_v18_forecast_clock import resolve_forecast_created_at_v1
from server.sports_current_statcast.mlb_v18_current_slate import load_contract, reference
from server.sports_current_statcast.stage3_model_laboratory import _aligned_probabilities
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_silver.current_statcast_pa import EVENT_TO_OUTCOME

RUNTIME = ROOT / ".runtime/asp-model-studio/stage3-model-laboratory"
BUNDLE = ROOT / "outputs/mlb-v18-whole-game-challenger/sha256" / daily.PARENT_BUNDLE_SHA256
FITTED_SHA = "21f13e822fcfc204bcbc769f171e4e57379b56c58d7bf330ceb3cc9a0f877df5"
BASE_SHA = "0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9"
OPERATIONAL_SHA = "2bcf37de2fd76316ec850ebec2f06c7383fcd7c5afa275071ea21f8aafc95e29"
COMPARISON_SHA = "12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d"
COMPARISON_FILE_SHA = "d1911a217560895b508cc5ed61a19baf49aab18ff897639fe0b5b52c435bd0e4"
OUTPUT = ROOT / "outputs/mlb-v18-conditional-champion-v1/frozen-model"


def authenticated(path, expected=None):
    ref = reference(path)
    if expected is not None and ref["sha256"] != expected:
        raise ValueError(f"Artifact digest mismatch: {path}")
    return ref


def read_json(path, expected=None):
    ref = authenticated(path, expected)
    return json.loads(Path(path).read_text(encoding="utf-8")), ref


def checked_ref(ref):
    actual = authenticated(ref["path"], ref["sha256"])
    if actual["bytes"] != ref["bytes"]:
        raise ValueError("Artifact byte count mismatch")
    return actual


def immutable_json(name, body):
    payload = canonical_json_bytes(daily.json_safe(body))
    digest = hashlib.sha256(payload).hexdigest()
    path = OUTPUT / "sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("Immutable champion binding differs")
    else:
        with path.open("xb") as stream:
            stream.write(payload)
    return reference(path)


def type_name(value):
    return type(value).__module__ + "." + type(value).__name__


def encoder_binding(encoder):
    branches = []
    for name, transformer, columns in encoder.transformers_:
        branch = {"name": name, "inputColumns": list(columns), "class": type_name(transformer)}
        if hasattr(transformer, "steps"):
            branch["steps"] = [{"name": key, "class": type_name(step),
                "parameters": {k: value for k, value in step.get_params(deep=False).items()
                    if value is None or isinstance(value, (bool, int, float, str))},
                **({"fittedCategories": [list(a) for a in step.categories_]}
                   if hasattr(step, "categories_") else {})} for key, step in transformer.steps]
        branches.append(branch)
    return {"class": type_name(encoder), "branches": branches,
        "orderedEncodedFeatures": list(encoder.get_feature_names_out()),
        "fittedStateLocation": "paArtifact.preprocessor.encoder",
        "sparseOutput": bool(encoder.sparse_output_)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-verified-fixture", type=Path,
        help="Finish/check reference packaging using an already completed immutable reload; no extra inference")
    args = parser.parse_args()
    parent, parent_ref = read_json(BUNDLE / "manifest.json")
    body = {k: v for k, v in parent.items() if k not in {"bundleId", "bundleSha256"}}
    if parent["bundleSha256"] != daily.PARENT_BUNDLE_SHA256 or daily.sha_json(body) != daily.PARENT_BUNDLE_SHA256:
        raise ValueError("Parent logical bundle identity differs")
    artifacts = []
    for child in parent["artifacts"]:
        ref = authenticated(BUNDLE / child["relativePath"], child["sha256"])
        if ref["bytes"] != child["bytes"]:
            raise ValueError("Parent child byte count differs")
        artifacts.append({**ref, "parentRelativePath": child["relativePath"]})
    model_ref = authenticated(BUNDLE / "executable/v18-pa-fold5.joblib", daily.PA_MODEL_SHA256)
    model_store_ref = {key: parent["paModels"][-1][key] for key in ("relativePath", "sha256", "bytes")}
    if authenticated(RUNTIME / model_store_ref["relativePath"], daily.PA_MODEL_SHA256)["bytes"] != model_store_ref["bytes"]:
        raise ValueError("Original model-store artifact differs")
    model = joblib.load(model_ref["path"])
    state, state_ref = read_json(RUNTIME / f"objects/corrected-preprocessing/sha256/{FITTED_SHA}.json", FITTED_SHA)
    implementation = state["implementationSnapshot"]
    implementation_ref = authenticated(RUNTIME / implementation["relativePath"], implementation["sha256"])
    if implementation_ref["bytes"] != implementation["bytes"]:
        raise ValueError("Fitted implementation snapshot byte count differs")
    if (canonical_json_bytes(model.preprocessor.prior) != canonical_json_bytes(state["prior"])
            or canonical_json_bytes(model.preprocessor.semantic) != canonical_json_bytes(state["semantic"])):
        raise ValueError("Embedded fold-5 prior/semantic state differs from fitted metadata")
    contract = load_contract()
    if not (list(model.ordered_features) == state["sourceColumns"] == contract["rawFeatureColumns"]
            and list(model.preprocessor.ordered_features) == state["orderedFeatures"] == contract["treatedFeatureColumns"]):
        raise ValueError("Ordered raw/treated contracts differ")
    if list(model.target_order) != list(PA_CLASS_ORDER) or len(PA_CLASS_ORDER) != 8:
        raise ValueError("Accepted target order differs")
    base_ref = authenticated(ROOT / f"outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache/baseline-reproduction-{BASE_SHA}.json", BASE_SHA)
    raw_ref = checked_ref(contract["artifacts"]["rawDevelopment"])
    oof_ref = checked_ref(contract["artifacts"]["matchedOof"])
    treated_ref = checked_ref(contract["artifacts"]["validationFold5"])
    if args.reuse_verified_fixture:
        fixture, fixture_ref = read_json(args.reuse_verified_fixture, args.reuse_verified_fixture.parent.name)
        if (fixture["model"] != model_ref or fixture["rawDevelopment"] != raw_ref
                or fixture["savedTreatedFold5"] != treated_ref or fixture["savedPredictions"] != oof_ref
                or fixture["comparedRows"] != 32 or fixture["predictionMismatches"] != 0
                or fixture["bitwiseEqual"] is not True or fixture["treatedFrameExactMatch"] is not True):
            raise ValueError("Reused fixture does not bind these exact artifacts")
        inferred_this_invocation = 0
    else:
        fixture_ref, fixture = run_fixture(model, model_ref, base_ref, raw_ref, oof_ref, treated_ref, state)
        inferred_this_invocation = 1
    finish_bindings(model, model_ref, model_store_ref, state, state_ref, implementation_ref,
        parent, parent_ref, artifacts, raw_ref, treated_ref, fixture_ref, fixture, inferred_this_invocation)


def run_fixture(model, model_ref, base_ref, raw_ref, oof_ref, treated_ref, state):
    probabilities = ["probability_" + name for name in PA_CLASS_ORDER]
    expected = pd.read_parquet(oof_ref["path"], filters=[("foldNumber", "=", 5)],
        columns=["canonicalPaId", "canonicalGameId", "game_date", *probabilities]).head(32)
    ids = expected.canonicalPaId.tolist()
    raw = pd.read_parquet(raw_ref["path"], filters=[("canonicalPaId", "in", ids)],
        columns=list(model.ordered_features)).set_index("canonicalPaId", drop=False).loc[ids]
    saved_treated = pd.read_parquet(treated_ref["path"], filters=[("canonicalPaId", "in", ids)],
        columns=["canonicalPaId", *state["orderedFeatures"]]).set_index("canonicalPaId").loc[ids]
    if len(raw) != 32 or raw.game_date.max() > "2026-08-06" or not np.array_equal(raw.canonicalGameId, expected.canonicalGameId):
        raise ValueError("Fixture identity or physical Development boundary differs")
    with threadpool_limits(limits=4):
        treated = model.preprocessor.transform_frame(raw)
        pd.testing.assert_frame_equal(treated.reset_index(drop=True), saved_treated.reset_index(drop=True),
            check_dtype=False, check_exact=True)
        encoded = model.preprocessor.encoder.transform(treated)
        # Exactly one estimator predict_proba call, through the accepted class aligner.
        actual = _aligned_probabilities(model.estimator, encoded)
    original = expected[probabilities].to_numpy()
    mismatches = int(np.count_nonzero(actual != original))
    if actual.tobytes() != original.tobytes():
        raise ValueError(f"Frozen prediction fixture differs: {mismatches} values")
    fixture = {"schemaVersion": "MLB_V18_CHAMPION_FROZEN_RELOAD_V1", "model": model_ref,
        "sourceAuthority": base_ref, "rawDevelopment": raw_ref, "savedTreatedFold5": treated_ref,
        "savedPredictions": oof_ref, "fixtureSelection": "FIRST_32_SAVED_MATCHED_FOLD5_PA_IDS_UNCHANGED_ORDER",
        "canonicalPaIds": ids, "gameDates": sorted(set(raw.game_date)), "comparedRows": 32,
        "comparedProbabilityValues": int(original.size), "predictionMismatches": mismatches,
        "maximumAbsoluteDifference": float(np.abs(actual-original).max()), "bitwiseEqual": True,
        "treatedFrameExactMatch": True, "treatedValueCellsCompared": int(treated.size),
        "encodedShape": list(encoded.shape), "encodedPhysicalDtype": str(encoded.dtype),
        "actualEstimatorInferenceCalls": 1, "preprocessorTransformCalls": 1,
        "newGameForecasts": 0, "simulationRuns": 0, "fits": 0, "providerCalls": 0,
        "finalOotPayloadRowsRead": 0, "targetsRead": 0,
        "scope": "NUMERICAL_REPRODUCTION_NOT_CLEAN_HISTORICAL_PIT_VALIDATION",
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__,
                    "pandas": pd.__version__, "scikitLearn": sklearn.__version__}}
    fixture_ref = immutable_json("reload-verification.json", fixture)
    return fixture_ref, fixture


def finish_bindings(model, model_ref, model_store_ref, state, state_ref, implementation_ref,
        parent, parent_ref, artifacts, raw_ref, treated_ref, fixture_ref, fixture, inferred_this_invocation):
    study, study_ref = read_json(RUNTIME / "corrected-hgb-recovery-1/study.json")
    comparison, comparison_ref = read_json(ROOT / f"outputs/mlb-corrected-treatment/corrected-hgb-recovery-1-comparison-{COMPARISON_SHA}.json", COMPARISON_FILE_SHA)
    if comparison["resultChecksum"] != COMPARISON_SHA:
        raise ValueError("Original comparison logical identity differs")
    training_run, training_run_ref = read_json(RUNTIME / "objects/sha256/95d4f0199aff4698f187311266c30670c4a95a66802cfd87ab96f1e120fd66bb.json",
        "95d4f0199aff4698f187311266c30670c4a95a66802cfd87ab96f1e120fd66bb")
    eligibility = study["rowEligibilityReceipt"]
    eligibility_ref = authenticated(eligibility["path"], eligibility["fileSha256"])
    calibration, calibration_ref = read_json(BUNDLE / "calibration.json")
    if calibration["decision"] != "RETAIN_RAW_V18" or calibration["selected"] is not False:
        raise ValueError("Accepted calibration disposition differs")
    operational, operational_ref = read_json(ROOT / f"outputs/mlb-v18-unattended-v1/evidence/sha256/{OPERATIONAL_SHA}/sept10-operational-evidence.json", OPERATIONAL_SHA)
    if operational["modelRegistration"]["paArtifact"] != model_ref:
        raise ValueError("Legitimate current-slate model identity differs")
    raw_schema, treated_schema = pq.read_schema(raw_ref["path"]), pq.read_schema(treated_ref["path"])
    code_names = ["server/sports_current_statcast/stage3_corrected_preprocessing_artifacts.py",
        "server/sports_current_statcast/stage3_corrected_prior_treatment.py",
        "server/sports_current_statcast/stage3_semantic_treatment.py",
        "server/sports_current_statcast/stage3_model_laboratory.py",
        "server/sports_current_statcast/mlb_v18_prospective_transform.py",
        "server/sports_current_statcast/mlb_v18_current_publication.py",
        "server/sports_current_statcast/mlb_v18_whole_game_challenger.py",
        "server/sports_phase5/base_out_transition.py", "server/sports_phase5/whole_game_monte_carlo.py",
        "server/sports_silver/current_statcast_pa.py", "server/sports_modeling/metrics.py"]
    encoder = encoder_binding(model.preprocessor.encoder)
    result = {"schemaVersion": "MLB_V18_CONDITIONAL_CHAMPION_FROZEN_MODEL_BINDINGS_V1",
        "modelIdentity": {"name": "MLB_V18_HGB_PA", "version": "V18", "paFold": 5,
            "candidateId": "stage3-candidate-83f50e93af5946198c8df4602e08d7b8",
            "trainingRunId": training_run["runId"], "trainingRunReceipt": training_run_ref,
            "artifactSha256": model_ref["sha256"], "parentBundleId": parent["bundleId"],
            "parentLogicalBundleSha256": parent["bundleSha256"]},
        "disposition": "FROZEN_ARTIFACT_BINDING_FOR_CONDITIONAL_OPERATIONAL_CHAMPION",
        "registrationAuthority": "SEPARATE_CHAMPION_MANIFEST_REQUIRED_NO_DATABASE_WRITE_BY_THIS_BUILDER",
        "paArtifact": model_ref, "modelStore": {"root": str(RUNTIME), "reference": model_store_ref},
        "parentManifest": parent_ref, "parentArtifactBindings": artifacts,
        "targetContract": {"classOrder": list(PA_CLASS_ORDER), "targetColumn": "outcome",
            "terminalEventMapping": dict(EVENT_TO_OUTCOME),
            "walkHbpCatcherInterferenceCombined": True, "otherReachSeparate": True,
            "estimatorInternalClassOrder": list(model.estimator.classes_),
            "exportClassAlignment": "stage3_model_laboratory._aligned_probabilities"},
        "featureContract": {"rawCount": 246, "treatedPreEncodingCount": 273,
            "encodedEstimatorCount": int(fixture["encodedShape"][1]), "rawOrderedFields": [
                {"name": name, "physicalArrowType": str(raw_schema.field(name).type)} for name in model.ordered_features],
            "treatedOrderedFields": [{"name": name, "physicalArrowType": str(treated_schema.field(name).type)}
                for name in state["orderedFeatures"]], "physicalDtypesSource": "AUTHENTICATED_ACCEPTED_DEVELOPMENT_CACHE_SCHEMAS",
            "treatmentSpecificationId": daily.TREATMENT_SPECIFICATION_ID,
            "treatmentVersion": 18, "manifestSha256": daily.TREATMENT_MANIFEST_SHA256,
            "modelFeatureSchemaChecksum": study["authority"]["modelFeatureSchemaChecksum"],
            "featureSetId": study["authority"]["featureSetId"],
            "featureSetChecksum": study["authority"]["featureSetChecksum"]},
        "fittedPreprocessor": {"artifact": state_ref, "embeddedInPaArtifact": True,
            "class": type_name(model.preprocessor), "foldNumber": 5,
            "priorChecksum": model.preprocessor.prior["fittedTreatmentChecksum"],
            "semanticChecksum": model.preprocessor.semantic["fittedChecksum"],
            "stateLocations": {"prior": "/prior", "semanticMissingRules": "/semantic/rules",
                "treatmentFeatureRules": "/semantic/treatmentFeatures", "interactionState": "/semantic/interactionFitted",
                "transformationOrder": "/transformationContracts/ordered",
                "categoricalLevels": "/categoricalLevelsIncludingUnknown"},
            "globalImputation": state["transformationContracts"]["globalImputation"],
            "contextualMedianCount": len(state["semantic"]["contextualMedians"]),
            "nativeMissingFeatures": state["semantic"]["nativeMissingFeatures"],
            "historicalImplementationSnapshot": implementation_ref,
            "posteriorStdRole": "ACCEPTED_V18_POSTERIOR_STD_AND_RELIABILITY_FEATURES_ENTER_PA_MEAN_PREDICTION_UNCHANGED",
            "encoder": encoder},
        "estimator": {"class": type_name(model.estimator), "parameters": model.estimator.get_params(),
            "nFeaturesIn": int(model.estimator.n_features_in_), "nIterations": int(model.estimator.n_iter_),
            "fittedEnvironment": state["environment"]},
        "calibration": {"decisionArtifact": calibration_ref, "status": "IDENTITY_NO_CALIBRATOR_APPLIED",
            "temperature": 1.0, "currentProviderArgument": "temperature=None",
            "unselectedCandidateTemperature": calibration["deploymentFit"]["temperature"],
            "candidateRetainedButNotApplied": True,
            "probabilityPostprocessing": "CLASS_ALIGNMENT_AND_ROW_SUM_NORMALIZATION_NOT_FITTED_CALIBRATION"},
        "trainingPopulation": {"studyArtifact": study_ref, "trainingRun": training_run_ref,
            "originalComparison": comparison_ref, "originalComparisonLogicalChecksum": COMPARISON_SHA,
            "registeredDevelopment": study["development"], "developmentSeasons": [2023, 2024, 2025, 2026],
            "operationalFold": next(p for p in study["modelFoldPopulations"] if p["foldNumber"] == 5),
            "fullDevelopmentRefit": False, "nominalTrainingCutoff": "2026-05-01",
            "nominalDateNotAvailabilityCertificate": True,
            "eligibleDevelopmentRows": comparison["rowEligibility"]["eligibleRows"],
            "heldDevelopmentObservations": comparison["rowEligibility"]["heldRows"],
            "eligibilityReceipt": eligibility_ref,
            "eligibilityChecksum": eligibility["eligibilityChecksum"],
            "priorNominalFitRows": state["prior"]["fitRows"],
            "priorModelEligibleTrainRows": state["prior"]["modelEligibleTrainRows"],
            "finalOot": {**study["finalOot"], "payloadRowsReadByThisBuilder": 0}},
        "simulator": {"transitionFold": 4, "transitionArtifact": authenticated(BUNDLE / "executable/transition-fold4.json", daily.TRANSITION_MODEL_SHA256),
            "acceptedSimulationSettings": parent["simulation"], "runtimeCodeBindings": [reference(ROOT / p) for p in code_names],
            "currentTemplateSemantics": "REAL_CURRENT_SOURCE_ROWS_PLUS_HYPOTHETICAL_SIMULATED_PA_STATE",
            "currentProviderCacheSemantics": "ONE_ROW_TRANSFORM_PER_TEMPLATE_V1",
            "originalParentForecastLimitationsAreHistorical": parent["limitations"],
            "currentSourceEvidenceSupersedesCarriedForwardTemplatesNotTheFrozenEstimator": True,
            "simulationRunsByThisBuilder": 0},
        "legitimateCurrentInferenceEvidence": {"receipt": operational_ref,
            "games": [{**{k: game[k] for k in ("gameId", "teams", "forecastObject", "evidenceCutoff",
                "scheduledFirstPitch", "pregameProof", "actualExecutionFeatureSnapshot", "simulation")},
                "forecastCreatedAt": resolve_forecast_created_at_v1(game)["forecastCreatedAt"]}
                for game in operational["publishedGames"]],
            "originalHandoff": checked_ref(operational["handoff"]),
            "historicalSeptember10EvidenceNotNewSeptember11Forecasts": True},
        "exactReload": fixture_ref,
        "historicalIntegrity": {"status": "HISTORICAL_VALIDATION_UNDER_REVIEW",
            "notice": reference(ROOT / "docs/MLB_V19_TEMPORAL_INTEGRITY_HOLD_V1.md"),
            "numericalReproductionDoesNotProvePointInTimeValidation": True},
        "boundaries": {"modelFits": 0, "actualEstimatorInferenceCalls": 1, "inferredFixtureRows": 32,
            "newGameForecasts": 0, "simulationRuns": 0, "providerCalls": 0, "costUsd": 0,
            "aispWrites": 0, "historicalArtifactWrites": 0, "finalOotPayloadAccessCount": 0,
            "wageringAuthority": False, "realMoneyExecutionAllowed": False, "executionAllowedInAISP": False}}
    if result["trainingPopulation"]["heldDevelopmentObservations"] != 56 or result["trainingPopulation"]["eligibleDevelopmentRows"] != 683606:
        raise ValueError("Frozen eligibility population differs")
    result["assets"] = [{**ref, "sizeBytes": ref["bytes"]} for ref in [model_ref,
        parent_ref, state_ref, implementation_ref, fixture_ref, study_ref, comparison_ref, eligibility_ref, training_run_ref,
        *artifacts, *result["simulator"]["runtimeCodeBindings"]]]
    binding_ref = immutable_json("model-bindings.json", result)
    print(json.dumps({"modelBindings": binding_ref, "reloadVerification": fixture_ref,
        "model": result["modelIdentity"], "encodedEstimatorInputs": fixture["encodedShape"][1],
        "fits": 0, "estimatorInferenceCallsThisInvocation": inferred_this_invocation,
        "completedFixtureInferenceCalls": 1, "comparedRows": 32, "mismatches": fixture["predictionMismatches"]}), flush=True)


if __name__ == "__main__":
    main()
