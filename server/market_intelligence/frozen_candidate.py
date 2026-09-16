"""Append-only registration and guarded inference for the exact frozen market HGB.

No fitting, providers, database access, V18 mutation, or fold averaging. Execute
``python -m server.market_intelligence.frozen_candidate`` to register locally.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .research_models import ALL_SIGNALS, EPSILON, FittedResearchArtifact, _bytes, _time
from .market_tape import sealed


CANDIDATE = "MLB_MARKET_COMPOSITE_HGB_V1"
SOURCE_COMMIT = "d68ac6b1eea3f1174d929c74984312d9dd51436d"
SOURCE_MANIFEST = "outputs/market-intelligence-rff-v1/completed/sha256/c0f759a2854e8c620b7936e49c7db930f652b2371f8dba01a904317a1db4402b/manifest.json"
SOURCE_SHA = "6f431412f809c08ba00661a8bd0b45fd0465d9f48d58619aae3166c93acf727c"
REGISTRY = "outputs/market-intelligence-rff-v1/candidate-registration"
FEATURES = ("market_logit", *ALL_SIGNALS)
GEN1_NAME = "asp_mlb_ensemble"
GEN1_VERSION = "2.0.0-gate2-08cca634c81b"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_ref(root: Path, reference: dict) -> bytes:
    path = Path(reference["path"])
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Artifact reference outside Model Studio")
    raw = path.read_bytes()
    if _hash(raw) != reference["sha256"] or len(raw) != reference.get("bytes", reference.get("byteCount", len(raw))):
        raise ValueError("Frozen artifact checksum/byte count mismatch")
    return raw


def _append(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError("Immutable registration conflict")


def _copy_object(root: Path, raw: bytes, suffix: str) -> dict:
    path = root / REGISTRY / "objects" / (_hash(raw) + suffix)
    _append(path, raw)
    return {"path": path.relative_to(root).as_posix(), "sha256": _hash(raw), "bytes": len(raw)}


def _fixture_check(artifact: FittedResearchArtifact, fixture: dict) -> dict:
    if tuple(fixture["orderedFeatures"]) != artifact.features or artifact.features != FEATURES:
        raise ValueError("Frozen feature order mismatch")
    if fixture["foldContract"] != artifact.fold_contract:
        raise ValueError("Frozen fold authority mismatch")
    predicted = artifact.predict(pd.DataFrame(fixture["rows"]))
    expected = np.asarray(fixture["expectedPredictions"], dtype=float)
    if predicted.shape != expected.shape or not np.array_equal(predicted, expected):
        raise ValueError("Exact HGB reload fixture mismatch")
    return {"rows": len(expected), "bitwiseEqual": True, "maximumAbsoluteDifference": 0.0}


def register_candidate(repository: str | Path) -> dict:
    """Copy all three trusted fitted authorities; reruns retain one registration."""
    root = Path(repository).resolve()
    source_raw = _read_ref(root, {"path": SOURCE_MANIFEST, "sha256": SOURCE_SHA})
    source = json.loads(source_raw)
    comparison_raw = _read_ref(root, source["currentComparison"])
    comparison = json.loads(comparison_raw)
    refs = sorted((a for a in comparison["artifacts"] if a["model"] == "HGB_RESEARCH_CHALLENGER"), key=lambda a: a["fold"])
    if [a["fold"] for a in refs] != [1, 2, 3]:
        raise ValueError("Exactly three original composite folds required")
    result = next(m for m in comparison["models"] if m["model"] == "HGB_RESEARCH_CHALLENGER")
    metrics = result["metrics"]
    if metrics["observations"] != 40 or metrics["logLoss"] != 0.650730337731732 or metrics["brier"] != 0.2281957487589441:
        raise ValueError("Original composite evaluation authority changed")
    folds = []
    for reference in refs:
        raw = _read_ref(root, reference)
        fixture_raw = _read_ref(root, reference["reloadFixture"])
        fixture = json.loads(fixture_raw)
        if fixture["modelSha256"] != reference["sha256"]:
            raise ValueError("Fixture points to a different estimator")
        # Only checksum-pinned, local, original repository artifacts are unpickled.
        fitted = joblib.load(io.BytesIO(raw))
        if not isinstance(fitted, FittedResearchArtifact) or fitted.model != "HGB_RESEARCH_CHALLENGER" or fitted.target != "home_win":
            raise ValueError("Unexpected frozen estimator authority")
        check = _fixture_check(fitted, fixture)
        if list(fitted.estimator.classes_) != [0, 1] or fitted.offset_recipe != "NONE":
            raise ValueError("Unexpected class orientation or model recipe")
        contract = fitted.fold_contract
        if _time(contract["maximumTrainingTargetAvailableAt"]) > _time(contract["trainingCutoff"]):
            raise ValueError("Training outcome knowledge exceeds fitted cutoff")
        folds.append({
            "fold": reference["fold"], "estimatorAndPreprocessor": _copy_object(root, raw, ".joblib"),
            "reloadFixture": _copy_object(root, fixture_raw, ".json"), "reloadVerification": check,
            "foldContract": contract, "orderedFeatures": list(fitted.features),
            "modelClass": type(fitted.estimator).__name__, "classes": [0, 1], "offsetRecipe": fitted.offset_recipe,
            "fixedHyperparameters": fitted.fixed_hyperparameters,
            "preprocessing": {"class": type(fitted.preprocessor).__name__,
                "steps": [{"name": name, "class": type(step).__name__,
                           "parameters": step.get_params(deep=False)} for name, step in fitted.preprocessor.steps],
                "fittedStatePreservedInsideArtifact": True,
                "scope": "Original market-research fold-local median/missing-indicator/scaler state; NOT V18 preprocessing."},
            "originalArtifact": reference,
        })
    authority = {
        "schemaVersion": "MLB_MARKET_COMPOSITE_FROZEN_REGISTRATION_V1", "candidateId": CANDIDATE,
        "sourceCommit": SOURCE_COMMIT, "status": "RESEARCH_CANDIDATE",
        "validationStatus": "PROSPECTIVE_VALIDATION_REQUIRED", "promotionStatus": "NOT_PROMOTED",
        "wageringAuthority": False, "authorityLabel": "NO_WAGERING_AUTHORITY", "executionAllowedInAISP": False,
        "sourceManifest": _copy_object(root, source_raw, ".json"),
        "originalComparison": _copy_object(root, comparison_raw, ".json"),
        "evaluation": {"scope": "Three chronological fold models, 40 combined OOF games; NOT one final-fit performance estimate.",
                       "metrics": metrics, "events": result["eventIds"], "folds": result["folds"],
                       "formalInference": False, "uncertainty": result["uncertainty"]},
        "foldArtifacts": folds,
        "prospectiveArtifact": {"fold": 3, "artifact": folds[-1]["estimatorAndPreprocessor"],
            "selectionRule": "LATEST_FROZEN_FOLD_FOR_PROSPECTIVE_RESEARCH",
            "relationship": "Exact last chronological fitted fold, no new fit and no averaging. The aggregate 40-game OOF metric does not belong to this single estimator.",
            "fullDataFinalFitExists": False, "isFoldEnsemble": False,
            "readiness": "EXECUTABLE_FROZEN_ARTIFACT_REQUIRES_VALID_CURRENT_T60_INPUTS"},
        "futureScoringContract": {
            "market": "MLB FULL_GAME MONEYLINE", "canonicalOrientation": "HOME_WIN=1; AWAY_WIN=0",
            "checkpointMinutesBeforeStart": 60, "minimumDistinctBookmakers": 2, "maximumQuoteAgeSeconds": 3600,
            "recipe": "Same market_tape feature recipes as source commit; market_logit from clipped no-vig consensus, no numerical substitution by a different model.",
            "orderedFeatures": list(FEATURES),
            "requiredMetadata": ["event_id", "home_team_id", "away_team_id", "event_start", "event_status", "checkpoint_at", "source_manifest_sha256", "evidence_available_at", "quote_max_age_seconds", "book_count", "signal_available_at"],
            "modelDisagreementAuthority": {"name": GEN1_NAME, "version": GEN1_VERSION,
                "rule": "Only original precheckpoint PUBLISHED Gen1 forecasts. V18 must not replace the trained Gen1 disagreement input without a separate study."},
            "pointInTime": "All source observed/available/created clocks must be <= checkpoint; no target-game result, closing target, future quote or sealed OOT input; score is available only at its actual creation time.",
            "publicationWindow": "At/after T60 but strictly before known event start. Late creation is explicitly recorded, never backdated as available at T60.",
            "missingTreatment": "Preserve original fitted market preprocessing only. Required market and identity evidence must be valid; unsupported optional signals remain missing with explicit reasons. No new median fit.",
            "untrainedPredictionMarketInput": "rff_prediction_market_disagreement was wholly missing in fitting and remains null; new numeric support needs separate authority."},
        "hierarchy": ["V18 is primary plate-appearance model", "V18 simulation is primary game forecast",
                      "Market composite is separate game-level research layer; original fit used Gen1 disagreement, not a fitted V18 calibration",
                      "Future persistent-regime specialists require separate study, soft gates and shrinkage; none trained here"],
        "currentScoring": {"status": "NOT_SCORED_NO_CURRENT_VALIDATED_T60_INPUT_SUPPLIED", "forecastRows": 0},
        "rights": "LOCAL_PRIVATE_RESEARCH_ONLY; source restrictions retained, no redistribution/commercial rights granted",
        "activity": {"fits": 0, "providerCalls": 0, "aispWrites": 0, "ootPayloadReads": 0},
        "registrationImplementationSha256": _hash(Path(__file__).read_bytes()),
    }
    raw = _bytes(authority)
    path = root / REGISTRY / "sha256" / _hash(raw) / "manifest.json"
    _append(path, raw)
    return {"path": path.relative_to(root).as_posix(), "sha256": _hash(raw), "bytes": len(raw)}


def prospective_record(repository: str | Path, registration: dict, checkpoint: dict,
                       *, now: datetime | None = None) -> dict:
    """Pure record builder. Does not persist, refresh inputs, or manufacture a quote."""
    root = Path(repository).resolve()
    authority = json.loads(_read_ref(root, registration))
    if authority.get("candidateId") != CANDIDATE:
        raise ValueError("Unexpected candidate registration")
    created = _time(now or datetime.now(timezone.utc))
    start, cut = _time(checkpoint.get("event_start")), _time(checkpoint.get("checkpoint_at"))
    evidence = _time(checkpoint.get("evidence_available_at"))
    reasons = []
    if start is None or cut is None or start-cut != timedelta(hours=1):
        reasons.append("INVALID_EXACT_T60_CHECKPOINT")
    elif sealed(start) or checkpoint.get("final_oot") is True:
        reasons.append("SEALED_FINAL_OOT")
    elif created is None or created < cut or created >= start:
        reasons.append("NOT_CURRENT_PREGAME_PUBLICATION_WINDOW")
    if any(not checkpoint.get(k) for k in ("event_id", "home_team_id", "away_team_id", "source_manifest_sha256")) or checkpoint.get("home_team_id") == checkpoint.get("away_team_id"):
        reasons.append("MISSING_OR_INVALID_CANONICAL_IDENTITY_OR_SOURCE_MANIFEST")
    if checkpoint.get("event_status") not in {"SCHEDULED", "PRE_GAME"}:
        reasons.append("EVENT_NOT_SUPPORTABLY_SCHEDULED")
    if checkpoint.get("market_type") != "MONEYLINE" or checkpoint.get("period") != "full_game" or checkpoint.get("status") != "SUPPORTED":
        reasons.append("UNSUPPORTED_MARKET_CHECKPOINT")
    if evidence is None or cut is None or evidence > cut:
        reasons.append("EVIDENCE_UNAVAILABLE_AT_CHECKPOINT")
    try:
        p = float(checkpoint["consensus_probability"])
        age, count = float(checkpoint["quote_max_age_seconds"]), int(checkpoint["book_count"])
        if not np.isfinite(p) or not 0 < p < 1 or not np.isfinite(age) or not 0 <= age <= 3600 or count < 2:
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        p = float("nan")
        reasons.append("MISSING_FRESH_TWO_BOOK_CONSENSUS")
    metadata = {"schemaVersion": "MLB_MARKET_COMPOSITE_PROSPECTIVE_RECORD_V1", "candidateId": CANDIDATE,
                "registration": registration, "eventId": checkpoint.get("event_id"),
                "createdAtUtc": created.isoformat() if created is not None else None,
                "checkpointAtUtc": cut.isoformat() if cut is not None else None,
                "sourceManifestSha256": checkpoint.get("source_manifest_sha256"),
                "inputSha256": _hash(_bytes(checkpoint)), "status": "SKIPPED", "skipReasons": reasons,
                "promotionStatus": "NOT_PROMOTED", "wageringAuthority": False, "executionAllowedInAISP": False,
                "replacesV18": False, "fold": 3}
    fitted_cutoff = _time(authority["foldArtifacts"][-1]["foldContract"]["trainingCutoff"])
    if cut is not None and (fitted_cutoff is None or cut <= fitted_cutoff):
        reasons.append("CHECKPOINT_NOT_AFTER_FROZEN_TRAINING_CUTOFF")
    if reasons:
        return metadata
    values = {"market_logit": float(np.log(np.clip(p, EPSILON, 1-EPSILON)/(1-np.clip(p, EPSILON, 1-EPSILON))))}
    missing = {}
    available = checkpoint.get("signal_available_at") or {}
    model = checkpoint.get("model") or {}
    needs_model = any(checkpoint.get(key) is not None for key in ("model_disagreement", "rff_model_market_disagreement"))
    model_time = _time(model.get("available_at"))
    if needs_model:
        try:
            model_probability = float(model["home_win_probability"])
            if not np.isfinite(model_probability) or not 0 <= model_probability <= 1:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return {**metadata, "skipReasons": ["MODEL_DISAGREEMENT_PROBABILITY_UNAVAILABLE"]}
        if model.get("name") != GEN1_NAME or model.get("version") != GEN1_VERSION or model.get("status") != "PUBLISHED" or model_time is None or model_time > cut:
            return {**metadata, "skipReasons": ["MODEL_DISAGREEMENT_RECIPE_CHANGED_OR_NOT_PUBLISHED"]}
    for name in ALL_SIGNALS:
        value, when = checkpoint.get(name), _time(available.get(name))
        if name == "rff_prediction_market_disagreement" and value is not None:
            return {**metadata, "skipReasons": ["NEW_NUMERIC_FEATURE_SUPPORT_REQUIRES_AUTHORITY"]}
        try:
            number = float(value)
            if not np.isfinite(number) or when is None or when > cut:
                raise ValueError
            if name in {"model_disagreement", "rff_model_market_disagreement"}:
                expected = model_probability-p
                if name.startswith("rff_"):
                    expected = min(1.0, abs(expected)/.1)
                if not np.isclose(number, expected, atol=1e-12, rtol=0):
                    return {**metadata, "skipReasons": ["MODEL_DISAGREEMENT_VALUE_DOES_NOT_MATCH_ORIGINAL_RECIPE"]}
            values[name] = number
        except (TypeError, ValueError):
            values[name] = float("nan")
            missing[name] = "UNAVAILABLE_OR_NOT_AVAILABLE_AT_CHECKPOINT"
    if not any(np.isfinite(values[name]) for name in ALL_SIGNALS):
        return {**metadata, "skipReasons": ["NO_SUPPORTED_COMPOSITE_SIGNAL"]}
    fitted = joblib.load(io.BytesIO(_read_ref(root, authority["prospectiveArtifact"]["artifact"])))
    prediction = float(fitted.predict(pd.DataFrame([values]))[0])
    if not np.isfinite(prediction) or not 0 <= prediction <= 1:
        raise ValueError("Invalid frozen prediction")
    return {**metadata, "status": "RESEARCH_SHADOW", "skipReasons": [], "homeWinProbability": prediction,
            "awayWinProbability": 1-prediction, "missingOptionalSignals": missing,
            "sourceRole": "LATEST_ORIGINAL_FOLD_NOT_FULL_DATA_FINAL_FIT", "validationStatus": "PROSPECTIVE_VALIDATION_REQUIRED"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(register_candidate(args.repository), indent=2))
