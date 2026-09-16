"""Append-only admission correction from saved forecasts; never fit or predict."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

from .current_state_model import INPUT_NAMES
from .current_state_publication import (
    CONTRACT, OUTPUTS_ROOT, MISSING_SEASON_ADMISSION_REASON, _checked_ref, _put,
)
from .labs_simulation import AUTHORITY, file_record, verify_object

ALLOWED = "NFL_CURRENT_STATE_DYNAMIC_V2"
BLOCKED = [f"NFL_CURRENT_STATE_{name}_V2" for name in ("HIERARCHICAL", "RESIDUAL", "ENSEMBLE")]
LABELS = {**AUTHORITY, "evidenceClass": "OBSERVED_AS_OF",
          "trainingEvidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF"}


def _read(ref):
    _checked_ref(ref)
    return json.loads(Path(ref["path"]).read_bytes())


def issue_current_admission(original_handoff_ref, original_manifest_ref, publisher_snapshot_ref, output):
    """Diagnose frozen linear terms, then filter original immutable objects only.

    Matrix multiplication below decomposes already saved score means. No model
    prediction, feature construction, residual draws, outcomes or source reads.
    """
    output = Path(output).resolve()
    if not output.is_relative_to(OUTPUTS_ROOT.resolve()) or output == OUTPUTS_ROOT.resolve():
        raise ValueError("ADMISSION_REQUIRES_DEDICATED_MODEL_STUDIO_OUTPUT")
    original_handoff_ref, original_manifest_ref, publisher_snapshot_ref = [
        _checked_ref(ref) for ref in (original_handoff_ref, original_manifest_ref, publisher_snapshot_ref)]
    handoff, old_manifest, snapshot = map(_read, (original_handoff_ref, original_manifest_ref, publisher_snapshot_ref))
    if handoff.get("contract") != CONTRACT or old_manifest["handoff"] != original_handoff_ref:
        raise ValueError("ORIGINAL_PUBLICATION_CONTRACT_OR_MANIFEST_DIFFERS")
    if any(handoff.get(key) != value for key, value in AUTHORITY.items()):
        raise ValueError("ORIGINAL_AUTHORITY_DIFFERS")
    raw_source = base64.b64decode(snapshot["bytesBase64"], validate=True)
    if (hashlib.sha256(raw_source).hexdigest() != snapshot["originalSource"]["sha256"]
            or len(raw_source) != snapshot["originalSource"]["byteCount"]):
        raise ValueError("ORIGINAL_PUBLISHER_SOURCE_SNAPSHOT_DIFFERS")
    protected = {ref["path"]: _checked_ref(ref) for ref in [
        original_handoff_ref, original_manifest_ref, publisher_snapshot_ref, *old_manifest["files"]]}
    records = [(item, verify_object(item)) for item in handoff["artifacts"]]
    if len(records) != 64 or len({item["eventId"] for item, _ in records}) != 16:
        raise ValueError("EXPECTED_ORIGINAL_16_EVENTS_64_FORECASTS")
    model = joblib.load(handoff["model"]["path"])
    core = model.core
    supported = np.flatnonzero(core.supported_columns)
    terms_by_event, by_event = [], {}
    for item, record in records:
        by_event.setdefault(item["eventId"], {})[item["modelId"]] = (item, record)
    training_n = int(model.metadata["trainingRows"])
    training_terms = []
    for feature in ("home_missing_season_uncertainty", "away_missing_season_uncertainty",
                    "home_prior_season_gap", "away_prior_season_gap"):
        index = INPUT_NAMES.index(feature)
        position = list(supported).index(index)
        mean, scale = float(core.centers[index]), float(core.scales[index])
        training_terms.append({"feature": feature, "trainingMean": mean, "trainingScale": scale,
            "trainingRows": training_n, "sumFromSavedMoments": mean * training_n,
            "sumSquaresFromSavedScaleAndCenter": (scale ** 2 + mean ** 2) * training_n,
            "scaleFloorCaveat": "Saved scale has a 1e-6 floor; its implied second moment is not exact when the raw variance was zero.",
            "homeCoefficient": float(core.ridge.coef_[0, position]),
            "awayCoefficient": float(core.ridge.coef_[1, position])})
    for event_id, engines in by_event.items():
        if set(engines) != {ALLOWED, *BLOCKED}:
            raise ValueError("ORIGINAL_EVENT_COMPONENT_SET_DIFFERS")
        dynamic = engines[ALLOWED][1]
        features = _read(dynamic["featureEvidence"])
        if not any(value > 0 for value in features["missingInterveningSeasons"].values()):
            raise ValueError("CORRECTIVE_COHORT_HAS_NO_MISSING_SEASON")
        source_values = {row["feature"]: row["value"] for row in features["inputs"]}
        x = np.array([[np.nan if source_values[name] is None else source_values[name] for name in INPUT_NAMES]], dtype=float)
        design = core._linear(x)[0]
        terms = []
        for position, index in enumerate(supported):
            effects = design[position] * core.ridge.coef_[:, position]
            missing_effects = design[position + len(supported)] * core.ridge.coef_[:, position + len(supported)]
            terms.append({"feature": INPUT_NAMES[index], "value": source_values[INPUT_NAMES[index]],
                "standardizedValue": float(design[position]),
                "homeMeanContribution": float(effects[0]), "awayMeanContribution": float(effects[1]),
                "marginContribution": float(effects[0] - effects[1]),
                "homeMissingIndicatorContribution": float(missing_effects[0]),
                "awayMissingIndicatorContribution": float(missing_effects[1])})
        dynamic_mean = np.array([dynamic["scoreMeanEstimator"][key] for key in ("home", "away")])
        reconstructed = np.maximum(dynamic_mean + design @ core.ridge.coef_.T + core.ridge.intercept_, 0.0)
        saved = np.array([engines["NFL_CURRENT_STATE_HIERARCHICAL_V2"][1]["scoreMeanEstimator"][key]
                          for key in ("home", "away")])
        mismatch = float(np.max(np.abs(reconstructed - saved)))
        if mismatch > 1e-10:
            raise ValueError("SAVED_HIERARCHICAL_MEAN_TERM_RECONSTRUCTION_DIFFERS")
        terms_by_event.append({"eventId": event_id, "featureEvidence": dynamic["featureEvidence"],
            "missingInterveningSeasons": features["missingInterveningSeasons"], "terms": terms,
            "ridgeIntercept": core.ridge.intercept_.tolist(), "dynamicMeans": dynamic_mean.tolist(),
            "reconstructedHierarchicalMeans": reconstructed.tolist(), "savedHierarchicalMeans": saved.tolist(),
            "maxAbsoluteReconstructionMismatch": mismatch,
            "savedComponents": {engine: {"scoreMeanEstimator": record["scoreMeanEstimator"],
                "scoreSummary": record["scoreSummary"], "artifact": item["artifact"]}
                for engine, (item, record) in engines.items()}})
    created = datetime.now(timezone.utc).isoformat()
    key_terms = [next(term for term in row["terms"] if term["feature"] == "home_missing_season_uncertainty")
                 for row in terms_by_event]
    diagnostic = _put(output / "diagnostics", "diagnostic.json", {
        "contract": "NFL_CURRENT_STATE_MISSING_SEASON_DIAGNOSIS_V1", **LABELS,
        "createdAtUtc": created, "originalHandoff": original_handoff_ref, "originalManifest": original_manifest_ref,
        "publisherSourceBeforeCorrection": publisher_snapshot_ref,
        "publisherSourceAfterCorrection": file_record(Path(__file__).with_name("current_state_publication.py")),
        "diagnosisSource": file_record(Path(__file__)), "model": handoff["model"], "study": handoff["study"],
        "reason": MISSING_SEASON_ADMISSION_REASON, "trainingRows": training_n,
        "trainingTerms": training_terms, "events": terms_by_event,
        "summary": {"homeMissingSeasonCurrentValue": 1,
            "homeMeanContributionRange": [min(term["homeMeanContribution"] for term in key_terms), max(term["homeMeanContribution"] for term in key_terms)],
            "awayMeanContributionRange": [min(term["awayMeanContribution"] for term in key_terms), max(term["awayMeanContribution"] for term in key_terms)],
            "marginContributionRange": [min(term["marginContribution"] for term in key_terms), max(term["marginContribution"] for term in key_terms)],
            "maxAbsoluteReconstructionMismatch": max(row["maxAbsoluteReconstructionMismatch"] for row in terms_by_event)},
        "interpretation": "A sparsely observed training missing-season count entered the learned score mean, not only uncertainty. The current symmetric one-season gap creates an asymmetric +14.130862247907825 home-margin term. Saved moments of the nonnegative integer home flag imply one training value 2 and 6729 zeros; the away flag was constant zero with zero coefficients. This regime is unvalidated. DYNAMIC does not consume the flag in its scoring-only mean. Historical Development results remain unchanged; HIERARCHICAL/RESIDUAL/ENSEMBLE are not usable current challengers under this gap.",
        "operation": "READ_ONLY_SAVED_LINEAR_TERM_DECOMPOSITION_NOT_NEW_FORECAST_INFERENCE",
        "modelFits": 0, "newForecastInference": 0, "sealed2025Read": False, "providerCalls": 0, "aispWrites": 0})
    admitted, admitted_forecasts, withheld = [], [], []
    features_kept = []
    for item, record in records:
        if item["modelId"] == ALLOWED:
            admitted.append(item)
            admitted_forecasts.append(_checked_ref(record["sourceForecast"]))
            features_kept.append(_checked_ref(record["featureEvidence"]))
        else:
            withheld.append({"eventId": item["eventId"], "forecastId": item["forecastId"],
                "modelId": item["modelId"], "artifact": item["artifact"],
                "reason": MISSING_SEASON_ADMISSION_REASON,
                "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED"})
    if len(admitted) != 16 or len(withheld) != 48:
        raise ValueError("CORRECTIVE_ADMISSION_ACCOUNTING_DIFFERS")
    instruction = ("Import ONLY this corrective handoff's 16 NFL_CURRENT_STATE_DYNAMIC_V2 precomputed research-baseline forecasts and score-distribution artifacts. "
        "Verify checksums and byte counts. Do not import or admit the 48 HIERARCHICAL, RESIDUAL or ENSEMBLE forecasts from the predecessor: "
        "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED. Preserve original forecast timestamps and all prior evidence. "
        "No current hierarchical/residual challenger is admitted; no model execution, promotion or wagering authority.")
    corrected = {**handoff, "publishedAtUtc": created, "predecessor": original_handoff_ref,
        "originalHandoff": original_handoff_ref, "qualityNotice": diagnostic,
        "admissionOnly": True, "newForecastInference": 0, "forecastCount": 16, "artifactCount": 16,
        "forecastEventCount": 16, "unchangedNumericalObjectsReused": 16,
        "withheldForecastCount": 48, "artifacts": admitted, "forecasts": admitted_forecasts,
        "skips": [*handoff["skips"], *withheld], "importInstruction": instruction,
        "admissionDisposition": "DYNAMIC_RESEARCH_BASELINE_ONLY_NO_CURRENT_CHALLENGER",
        "originalForecastTimestampsPreserved": True}
    admitted_handoff = _put(output / "handoffs", "handoff.json", corrected)
    files = [admitted_handoff, diagnostic, publisher_snapshot_ref, original_handoff_ref, original_manifest_ref,
        handoff["model"], handoff["study"], handoff["currentObservedContext"], *features_kept, *admitted_forecasts]
    files += [ref for item in admitted for ref in (item["artifact"], item["manifest"])]
    files = list({ref["path"]: _checked_ref(ref) for ref in files}.values())
    manifest = _put(output / "manifests", "manifest.json", {
        "schemaVersion": "NFL_CURRENT_STATE_PUBLICATION_MANIFEST_V2", **LABELS,
        "publishedAtUtc": created, "handoff": admitted_handoff, "predecessor": original_manifest_ref,
        "qualityNotice": diagnostic, "files": files, "forecastCount": 16, "eventCount": 16,
        "withheldForecastCount": 48, "sourceCutoffUtc": old_manifest["sourceCutoffUtc"], "admissionOnly": True})
    for ref in protected.values():
        _checked_ref(ref)
    publication = {"handoff": admitted_handoff, "manifest": manifest, "forecastCount": 16,
        "eventCount": 16, "withheldForecastCount": 48}
    admission = _put(output / "supplements", "admission.json", {
        "contract": "NFL_CURRENT_STATE_V2_ADMISSION_SUPPLEMENT_V1", **LABELS,
        "createdAtUtc": created, "originalHandoff": original_handoff_ref, "diagnostic": diagnostic,
        "admittedHandoff": admitted_handoff, "manifest": manifest, "publication": publication,
        "admittedForecastCount": 16, "withheldForecastCount": 48,
        "admittedForecasts": admitted, "withheldForecasts": withheld,
        "allowedModels": [ALLOWED], "blockedModels": BLOCKED, "importInstruction": instruction,
        "disposition": "DYNAMIC_RESEARCH_BASELINE_ONLY_NO_CURRENT_CHALLENGER",
        "verification": {"originalFilesVerifiedUnchanged": len(protected),
            "originalNumericalObjectsUnchanged": 64, "admittedOriginalObjectsReused": 16,
            "newForecastInference": 0, "modelFits": 0, "sealed2025Read": False,
            "providerCalls": 0, "aispWrites": 0, "historicalOrPublicationPointersChanged": False}})
    return {"admission": admission, "diagnostic": diagnostic, "publication": publication,
        "originalHandoff": original_handoff_ref, "admittedForecastCount": 16, "withheldForecastCount": 48}
