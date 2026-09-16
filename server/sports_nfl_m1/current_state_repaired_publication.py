"""A separate frozen-repair publisher; the original V2 publisher stays intact."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import joblib
import numpy as np
import pandas as pd

from server.audit_assurance.canonical import canonical_json_bytes
from .current_state_publication import (_checked_ref, _context, _distribution,
    _feature_evidence, _publish_labeled_object, _put)
from .current_state_repaired_model import (CONTRACT as MODEL_CONTRACT, INPUT_NAMES,
    MEAN_INPUT_NAMES, MODEL_IDS, REPAIR_AUTHORITY, SEED, UNCERTAINTY_ONLY_NAMES,
    RepairedCurrentStateSystem, mean_preserving_scores)
from .forward_vintages import DEFAULT_OUTPUT as ARCHIVE_ROOT, schedule_events_from_handoff
from .labs_simulation import AUTHORITY, immutable_json, utc, verify_object

REPAIR_ROOT = Path(__file__).resolve().parents[2] / "outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1"
CONTRACT = "NFL_CURRENT_STATE_JOINT_DISTRIBUTION_HANDOFF_V2"
MODEL_VERSION = "NFL_UNCERTAINTY_MEAN_SEPARATION_REPAIR_V1"
DRAW_COUNT = 5000
FORECAST_TYPE = "HISTORICAL_PRIOR_BASELINE"


def _repair_guard(system):
    if type(system) is not RepairedCurrentStateSystem:
        raise ValueError("ONLY_FROZEN_REPAIRED_MODEL_CLASS_ADMITTED")
    state = system.state()
    if (system.metadata.get("repairAuthority") != REPAIR_AUTHORITY
            or state.get("repairAuthority") != REPAIR_AUTHORITY or state.get("contract") != MODEL_CONTRACT
            or state.get("inputNames") != list(INPUT_NAMES) or state.get("meanInputNames") != list(MEAN_INPUT_NAMES)
            or state.get("uncertaintyOnlyNames") != list(UNCERTAINTY_ONLY_NAMES)
            or state.get("selectedInputCount") != 52 or len(INPUT_NAMES) != 58
            or len(UNCERTAINTY_ONLY_NAMES) != 6 or set(MEAN_INPUT_NAMES) & set(UNCERTAINTY_ONLY_NAMES)
            or state.get("sealed2025Read") is not False or state.get("evidenceClass") != "RETROSPECTIVE_RECONSTRUCTED_AS_OF"
            or state.get("status") != "RESEARCH_SHADOW" or state.get("promotionStatus") != "NOT_PROMOTED"
            or state.get("wageringAuthority") is not False or state.get("executionAllowedInAISP") is not False):
        raise ValueError("REPAIRED_MODEL_AUTHORITY_OR_MEAN_ROLE_CONTRACT_DIFFERS")
    return hashlib.sha256(canonical_json_bytes(state)).hexdigest()


def _population_mean_check(population):
    if population.get("repairAuthority") != REPAIR_AUTHORITY:
        raise ValueError("POPULATION_REPAIR_AUTHORITY_DIFFERS")
    means = np.asarray(population["scoreMeans"], dtype=float)
    home, away = np.asarray(population["homeDraws"]), np.asarray(population["awayDraws"])
    if means.shape != (1, 2) or home.shape != (1, DRAW_COUNT) or away.shape != home.shape:
        raise ValueError("REPAIRED_POPULATION_SHAPE_DIFFERS")
    if not np.isfinite(means).all() or (means < 0).any():
        raise ValueError("REPAIRED_SCORE_MEANS_MUST_BE_FINITE_NONNEGATIVE")
    actual_sums = np.array([home.sum(), away.sum()], dtype=float)
    target_sums = np.rint(means[0] * DRAW_COUNT)
    if not np.array_equal(actual_sums, target_sums):
        raise ValueError("REPAIRED_POPULATION_DOES_NOT_PRESERVE_DECLARED_MEANS")
    return {"targetConditionalScoreMeans": means[0].tolist(),
            "actualPopulationScoreMeans": (actual_sums / DRAW_COUNT).tolist(),
            "expectedIntegerScoreSums": target_sums.astype(int).tolist(),
            "actualIntegerScoreSums": actual_sums.astype(int).tolist(),
            "roundingRule": "NEAREST_EVEN_INTEGER_TOTAL_EXACT_SUM",
            "maximumAbsoluteMeanRoundingErrorPoints": .5 / DRAW_COUNT,
            "isCalibrationClaim": False}


def _ensemble(predicted, weight):
    weight = float(weight)
    if not np.isfinite(weight) or not 0 <= weight <= 1:
        raise ValueError("INVALID_FROZEN_ENSEMBLE_WEIGHT")
    first, second = predicted["HIERARCHICAL"], predicted["RESIDUAL"]
    means = (1-weight) * first["scoreMeans"] + weight * second["scoreMeans"]
    use = np.random.default_rng(SEED + 41).random((1, DRAW_COUNT)) < weight
    home = mean_preserving_scores(np.where(use, second["homeDraws"], first["homeDraws"]), means[:, 0])
    away = mean_preserving_scores(np.where(use, second["awayDraws"], first["awayDraws"]), means[:, 1])
    # Total mixture variance includes the component-mean separation. The actual
    # projected finite population is reported separately, never called calibrated.
    variance = ((1-weight) * (np.square(first["stateUncertainty"]) + np.square(first["scoreMeans"]-means))
                + weight * (np.square(second["stateUncertainty"]) + np.square(second["scoreMeans"]-means)))
    return {**first, "homeDraws": home, "awayDraws": away, "scoreMeans": means,
            "stateUncertainty": np.sqrt(variance), "stateUncertaintyMeaning": "PRE_PROJECTION_MIXTURE_RESIDUAL_SCORE_SD_NOT_PARAMETER_POSTERIOR_SD",
            "fittedLatentResidualVariance": variance,
            "actualPopulationVariance": np.column_stack((home.var(axis=1), away.var(axis=1))),
            "residualAuthoritySha256": None}


def publish_repaired_current_v2(system, team, qb, model_ref, study_ref, output, *, source_receipt,
                                ensemble_weight=None, archive_root=ARCHIVE_ROOT,
                                clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
    """Reload the exact repaired artifact and publish only still-pregame laws."""
    output = Path(output).resolve()
    if not output.is_relative_to(REPAIR_ROOT.resolve()) or output == REPAIR_ROOT.resolve():
        raise ValueError("REPAIRED_PUBLICATION_REQUIRES_NEW_REPAIR_OUTPUT_SUBDIRECTORY")
    for ref in (model_ref, study_ref):
        if not Path(ref["path"]).resolve().is_relative_to(REPAIR_ROOT.resolve()):
            raise ValueError("REPAIRED_MODEL_AND_STUDY_MUST_BELONG_TO_NEW_REPAIR_ROOT")
    model_ref, study_ref = _checked_ref(model_ref), _checked_ref(study_ref)
    supplied_state_sha = _repair_guard(system)
    frozen = joblib.load(model_ref["path"])
    if _repair_guard(frozen) != supplied_state_sha:
        raise ValueError("SUPPLIED_SYSTEM_DIFFERS_FROM_EXACT_FROZEN_REPAIRED_ARTIFACT")
    system = frozen
    study = json.loads(Path(study_ref["path"]).read_bytes())
    if (study.get("contract") != "NFL_CURRENT_STATE_RECONSTRUCTED_STUDY_RESULT_V2"
            or study.get("finalOotAccessed") is not False or study.get("status") != "RESEARCH_SHADOW"
            or study.get("promotionStatus") != "NOT_PROMOTED" or study.get("wageringAuthority") is not False
            or study.get("executionAllowedInAISP") is not False or not study.get("completedAtUtc")
            or study.get("finalModel") != model_ref):
        raise ValueError("REPAIRED_PUBLICATION_REQUIRES_COMPLETED_RESEARCH_STUDY")
    if isinstance(source_receipt, dict) and "path" in source_receipt and "sources" not in source_receipt:
        source_receipt = json.loads(Path(_checked_ref(source_receipt)["path"]).read_bytes())
    sources = source_receipt.get("sources", [])
    if (source_receipt.get("sealedOotRead") is not False or not sources
            or any(int(item["season"]) >= 2025 or not item.get("retrievedAt") for item in sources)):
        raise ValueError("HISTORICAL_SOURCE_RECEIPT_MUST_EXCLUDE_2025_AND_PRESERVE_RETRIEVAL")
    for frame in (team, qb):
        if (frame.season.astype(int) >= 2025).any():
            raise ValueError("CURRENT_CORE_REQUIRES_EXPLICIT_HISTORY_THROUGH_2024")
    trained_seasons = {int(str(value).split("_", 1)[0]) for value in system.league_prior.get("training_ids", [])}
    if not trained_seasons or max(trained_seasons) != 2024 or pd.Timestamp(system.metadata["trainingEnd"]).year > 2025:
        raise ValueError("REPAIRED_MODEL_TRAINING_BOUNDARY_DIFFERS")
    source_cutoff = max(utc(item["retrievedAt"]) for item in sources)
    started = utc(clock())
    if source_cutoff > started:
        raise ValueError("SOURCE_RETRIEVAL_AFTER_ACTUAL_FORECAST_CLOCK")
    selection = schedule_events_from_handoff()
    context = _context(archive_root, started, qb, system)
    context_ref = _put(output / "contexts", "context.json", context)
    source_summary = [{key: source.get(key) for key in ("season", "sha256", "byteCount", "retrievedAt", "assetUpdatedAt", "releasePublishedAt", "license", "evidenceClass")} for source in sources]
    artifacts, forecasts, feature_refs, skips, reused = [], [], [], [], 0
    for event in selection["events"]:
        inference_time = utc(clock())
        if inference_time >= utc(event["kickoffUtc"]):
            skips.append({"eventId": event["eventId"], "evidenceClass": "OBSERVED_AS_OF", "reason": "KICKOFF_REACHED_BEFORE_REPAIRED_INFERENCE"})
            continue
        frame = pd.DataFrame([{"canonical_game_id": event["eventId"], "season": 2026, "week": event["week"], "game_type": "REG",
            "game_date": pd.Timestamp(event["kickoffUtc"]).tz_convert("America/New_York").normalize().tz_localize(None),
            "canonical_home_team_id": event["homeTeamId"], "canonical_away_team_id": event["awayTeamId"],
            "forecast_cutoff_utc": inference_time, "home_points": None, "away_points": None}])
        inference_time = utc(clock())
        if inference_time >= utc(event["kickoffUtc"]):
            skips.append({"eventId": event["eventId"], "evidenceClass": "OBSERVED_AS_OF", "reason": "KICKOFF_REACHED_ADJACENT_TO_REPAIRED_INFERENCE"})
            continue
        frame["forecast_cutoff_utc"] = inference_time
        predicted = system.predict(frame, team, qb, draws=DRAW_COUNT, seed=SEED)
        if utc(clock()) >= utc(event["kickoffUtc"]):
            skips.append({"eventId": event["eventId"], "evidenceClass": "OBSERVED_AS_OF", "reason": "KICKOFF_REACHED_DURING_REPAIRED_INFERENCE"})
            continue
        components = list(MODEL_IDS)
        if ensemble_weight is not None:
            predicted["ENSEMBLE"] = _ensemble(predicted, ensemble_weight)
            components.append("ENSEMBLE")
        feature_evidence = _feature_evidence(predicted["_states"].iloc[0], source_summary)
        for item in feature_evidence["inputs"]:
            item["usedInMeanPredictor"] = item["feature"] in MEAN_INPUT_NAMES
            item["modelRole"] = "UNCERTAINTY_ONLY" if item["feature"] in UNCERTAINTY_ONLY_NAMES else "MEAN_PREDICTOR"
        feature_evidence.update(repairAuthority=REPAIR_AUTHORITY, meanInputCount=52, evidenceInputCount=58,
                                uncertaintyOnlyInputs=list(UNCERTAINTY_ONLY_NAMES))
        feature_ref = _put(output / "features", "feature-state.json", {"schemaVersion": "NFL_CURRENT_STATE_FEATURE_EVIDENCE_V2",
            "evidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF", "eventId": event["eventId"], **feature_evidence})
        feature_refs.append(feature_ref)
        for component in components:
            population = predicted[component]
            mean_receipt = _population_mean_check(population)
            distribution = _distribution(population["homeDraws"][0], population["awayDraws"][0])
            engine_id = f"NFL_CURRENT_STATE_{component}_V2_REPAIRED"
            numerical = {"modelSha256": model_ref["sha256"], "modelStateSha256": supplied_state_sha, "engineId": engine_id,
                "repairAuthority": REPAIR_AUTHORITY, "modelVersion": MODEL_VERSION, "forecastType": FORECAST_TYPE,
                "eventId": event["eventId"], "featureStateSha256": feature_ref["sha256"], "draws": DRAW_COUNT, "seed": SEED,
                "randomStreamScope": "SINGLE_EVENT_FIXED_1_BY_5000_COMMON_RANDOM_NUMBERS",
                "ensembleResidualWeight": ensemble_weight if component == "ENSEMBLE" else None,
                "jointScoreDistribution": distribution["jointScoreDistribution"]}
            numerical_sha = hashlib.sha256(canonical_json_bytes(numerical)).hexdigest()
            identity_path = output / "identities" / numerical_sha / "publication.json"
            publication_time = utc(clock())
            if publication_time >= utc(event["kickoffUtc"]):
                skips.append({"eventId": event["eventId"], "component": component, "evidenceClass": "OBSERVED_AS_OF", "reason": "KICKOFF_REACHED_BEFORE_REPAIRED_PUBLICATION"})
                continue
            if identity_path.is_file():
                previous = json.loads(identity_path.read_bytes())
                old = verify_object(previous["publishedObject"]); _checked_ref(previous["forecast"])
                if old["model"]["engineId"] != engine_id or old.get("repairAuthority") != REPAIR_AUTHORITY:
                    raise ValueError("CACHED_PUBLICATION_REPAIR_IDENTITY_DIFFERS")
                artifacts.append(previous["publishedObject"]); forecasts.append(previous["forecast"]); reused += 1
                continue
            forecast_id = "nfl-current-state-repaired-v2:sha256:" + numerical_sha
            model = {"engineId": engine_id, "modelVersion": MODEL_VERSION, "trainingCutoff": system.metadata["trainingEnd"],
                "trainingSeasonEnd": 2024, "modelArtifact": model_ref, "modelStateSha256": supplied_state_sha,
                "study": study_ref, "repairAuthority": REPAIR_AUTHORITY, "evidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF"}
            common = {**AUTHORITY, "evidenceClass": "OBSERVED_AS_OF", "sport": "NFL", "eventId": event["eventId"],
                "forecastId": forecast_id, "forecastType": FORECAST_TYPE, "publicationClassification": FORECAST_TYPE,
                "repairAuthority": REPAIR_AUTHORITY, "model": model, "homeTeam": {"teamId": event["homeTeamId"], "abbreviation": event["homeTeamId"], "source": "NFLVERSE"},
                "awayTeam": {"teamId": event["awayTeamId"], "abbreviation": event["awayTeamId"], "source": "NFLVERSE"},
                "scheduledStartUtc": event["kickoffUtc"], "forecastCreatedUtc": inference_time.isoformat(),
                "forecastCutoffUtc": inference_time.isoformat(), "publishedAtUtc": publication_time.isoformat(),
                "sourceCutoffUtc": source_cutoff.isoformat(), "sourceCutoffMeaning": "LATEST_REGISTERED_RETRIEVAL_OF_RECONSTRUCTED_HISTORICAL_INPUTS_NOT_CURRENT_TEAM_EVIDENCE",
                "trainingEvidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF", "forecastObservationEvidenceClass": "OBSERVED_AS_OF",
                "featureEvidence": feature_ref, "currentObservedContext": context_ref, "currentContextNumericallyIncorporated": False,
                "currentRosterDepthNumericallyIncorporated": False, "currentTargetStarterKnown": False,
                "historicalEvidenceThroughDate": str(pd.to_datetime(team.game_date).max().date()), "sealed2025Excluded": True,
                "lateHistoricalCorrectionsPossible": True, "noGenericMedianOrModeFallback": True, "scheduleSource": selection["sourceHandoffs"],
                "missingInputs": ["SEALED_2025_INITIALIZATION", "CONFIRMED_CURRENT_STARTER", "CURRENT_INJURY_WEATHER_NUMERICAL_INPUTS"],
                "uncertainty": {"scoreSd": population["stateUncertainty"][0].tolist(), "meaning": population["stateUncertaintyMeaning"],
                    "fittedLatentResidualVariance": population["fittedLatentResidualVariance"][0].tolist(),
                    "actualPopulationVariance": population["actualPopulationVariance"][0].tolist(), "isCalibrated": False,
                    "missingSeasonCount": feature_evidence["missingInterveningSeasons"], "uncertaintyOnlyInputsExcludedFromMean": list(UNCERTAINTY_ONLY_NAMES)},
                "scoreMeanEstimator": {"home": float(population["scoreMeans"][0, 0]), "away": float(population["scoreMeans"][0, 1])},
                "meanPreservation": mean_receipt, "treatmentBranchCounts": population["branchCounts"], "numericalIdentitySha256": numerical_sha,
                "randomStreamScope": "SINGLE_EVENT_FIXED_1_BY_5000_COMMON_RANDOM_NUMBERS", "independentOfM1": True, "explainsM1Forecast": False}
            forecast = _put(output / "forecasts", "forecast.json", {"schemaVersion": "NFL_CURRENT_STATE_GAME_FORECAST_V2", **common,
                **distribution["scoreSummary"], "jointScoreDistribution": distribution["jointScoreDistribution"]})
            artifact = {"schemaVersion": "NFL_LABS_SCORE_DISTRIBUTION_V1", **common, "sourceForecast": {**forecast, "forecastId": forecast_id},
                "drawCount": DRAW_COUNT, "seed": SEED, "scenario": {"scenarioId": "BASE", "modelInputChange": False},
                "generatingLaw": {"id": "NFL_REPAIRED_MEAN_PRESERVING_PAIRED_RESIDUAL_LAW_V1", "calibration": "RAW_DISTRIBUTION_ONLY",
                    "representation": "EXACT_5000_DRAW_EMPIRICAL_JOINT_PMF", "residualAuthoritySha256": population["residualAuthoritySha256"],
                    "pairedResidualSelectionPreservedBeforeNonnegativeProjection": True, "finitePopulationMeanPreserved": True,
                    "ensembleResidualWeight": ensemble_weight if component == "ENSEMBLE" else None},
                **distribution, "simulatedDrives": None, "simulatedGames": None,
                "limitations": ["HISTORICAL_PRIOR_BASELINE only: no 2025 initialization or current starter/injury/weather numerical evidence.",
                    "Current roster/depth context is descriptive, not an incorporated model input or confirmed starter assignment.",
                    "Reconstructed Development is not historical observed source-vintage evidence; late corrections remain possible.",
                    "Dispersion is fitted on chronological inner holdout and dropout evidence, not a calibrated uncertainty claim.",
                    "Final-score laws do not invent drive/play paths or enforce legal scoring sequences.", "No sportsbook or wagering authority is included."]}
            item = _publish_labeled_object(artifact, output / "nfl-labs-score-distributions-repaired-v2")
            verify_object(item)
            immutable_json(identity_path, {"evidenceClass": "OBSERVED_AS_OF", "trainingEvidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF",
                "numericalIdentitySha256": numerical_sha, "publishedObject": item, "forecast": forecast})
            artifacts.append(item); forecasts.append(forecast)
    _checked_ref(model_ref); _checked_ref(study_ref)
    receipt = {"schemaVersion": CONTRACT, "contract": CONTRACT, **AUTHORITY, "evidenceClass": "OBSERVED_AS_OF",
        "publishedAtUtc": utc(clock()).isoformat(), "forecastType": FORECAST_TYPE, "publicationDisposition": "REPAIRED_HISTORICAL_PRIOR_BASELINE",
        "repairAuthority": REPAIR_AUTHORITY, "modelVersion": MODEL_VERSION, "eventCount": len(selection["events"]),
        "forecastEventCount": len({item["eventId"] for item in artifacts}), "forecastCount": len(forecasts), "artifactCount": len(artifacts),
        "unchangedNumericalObjectsReused": reused, "model": model_ref, "study": study_ref, "sourceScheduleProjection": selection,
        "currentObservedContext": context_ref, "artifacts": artifacts, "forecasts": forecasts, "skips": skips, "drawsPerForecast": DRAW_COUNT,
        "trainingEvidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF", "forecastObservationEvidenceClass": "OBSERVED_AS_OF",
        "providerCalls": 0, "modelFits": 0, "sealed2025Read": False, "aispWrites": 0,
        "importInstruction": "Verify checksums/byte counts and import the separate NFL_CURRENT_STATE_*_V2_REPAIRED historical-prior research forecasts and precomputed score distributions. Preserve all prior engines, forecasts and withholding receipts. No model execution, promotion, wagering authority, or current-starter/injury/weather-input claim is permitted."}
    handoff = _put(output / "handoffs", "handoff.json", receipt)
    files = [handoff, context_ref, model_ref, study_ref, *feature_refs, *forecasts]
    files.extend(ref for item in artifacts for ref in (item["artifact"], item["manifest"]))
    manifest = _put(output / "manifests", "manifest.json", {"schemaVersion": "NFL_CURRENT_STATE_PUBLICATION_MANIFEST_V2", **AUTHORITY,
        "evidenceClass": "OBSERVED_AS_OF", "trainingEvidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF", "forecastType": FORECAST_TYPE,
        "files": files, "handoff": handoff, "forecastCount": len(forecasts), "eventCount": receipt["forecastEventCount"],
        "publishedAtUtc": receipt["publishedAtUtc"], "sourceCutoffUtc": source_cutoff.isoformat()})
    return {"handoff": handoff, "manifest": manifest, "forecastCount": len(forecasts), "eventCount": receipt["forecastEventCount"],
            "skipCount": len(skips), "skips": skips, "reused": reused, "context": context_ref}
