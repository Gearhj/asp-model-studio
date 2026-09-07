"""Successor-only prior representation and replay for the controlled HGB study.

This module does not load datasets, persist state, or fit predictive models. Its
only fit is the already registered V1 empirical-Bayes preprocessing authority,
using an explicitly sliced training frame. Existing fitted V2 authorities are
consumed without fitting. Invalid/source-held outputs never reach an imputer.
"""
from __future__ import annotations

import copy
import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from ..sports_datasets.consumer import canonical_json_bytes
from . import stage3_player_prior_authority as prior_v1
from . import stage3_player_prior_authority_v2 as prior_v2


SCHEMA_VERSION = "MLB_CORRECTED_PRIOR_REPRESENTATION_V1"
FITTED_SCHEMA_VERSION = "MLB_CORRECTED_PRIOR_FITTED_V1"
# The workbook requires posterior uncertainty in addition to effective N,
# reliability and history state. Std is the minimal existing uncertainty output.
V1_MODEL_OUTPUT_ROLES = (
    "posteriorMean", "effectiveN", "posteriorReliability", "posteriorStd", "historyState",
)
_VALID_STATES = frozenset({
    "TRUE_COLD_START", "TRUE_NO_OPPORTUNITY", "SPARSE_HISTORY",
    "ESTABLISHED_HISTORY", "PRIOR_SEASON_ONLY",
})
_TARGET_NAMES = frozenset({"outcome", "target", "observedClassIndex", "label", "y"})


class CorrectedPriorTreatmentError(ValueError):
    def __init__(self, code: str, message: str, *, evidence: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.evidence = dict(evidence or {})


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _binding(feature: str, runtime: Mapping[str, Any] | None) -> dict[str, Any]:
    provided = ((runtime or {}).get("bindings") or {}).get(feature)
    if feature in prior_v1.SUPPORTED_PRIOR_FEATURES:
        canonical = prior_v1.feature_binding(feature)
    elif feature in prior_v2.WAVE2_FEATURES:
        canonical = prior_v2.feature_binding(feature)
    else:
        return {}
    if not canonical:
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_BINDING_MISSING", feature)
    if provided and provided.get("derivedOutputs") != canonical.get("derivedOutputs"):
        raise CorrectedPriorTreatmentError(
            "CORRECTED_PRIOR_OUTPUT_BINDING_MISMATCH", f"Output names differ from registered authority for {feature}."
        )
    return copy.deepcopy(dict(provided or canonical))


def build_prior_output_schema(
    ordered_features: Sequence[str], runtime: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind source slots and five explicit V1 additions in stable source order.

The source list must contain original feature names only. V2 retains its
approved posterior-only slot. Categorical state encoding belongs to the shared
model preprocessor, so this count is before one-hot category expansion.
"""
    source = list(ordered_features)
    if len(source) != len(set(source)) or any("__prior_v1__" in item for item in source):
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_SOURCE_SCHEMA_INVALID", "Source features must be unique raw names.")
    v1 = [name for name in source if name in prior_v1.SUPPORTED_PRIOR_FEATURES]
    v2 = [name for name in source if name in prior_v2.WAVE2_FEATURES]
    bindings = {feature: _binding(feature, runtime) for feature in [*v1, *v2]}
    additions: list[dict[str, Any]] = []
    for feature in v1:
        for role in V1_MODEL_OUTPUT_ROLES:
            categorical = role == "historyState"
            additions.append({
                "name": bindings[feature]["derivedOutputs"][role],
                "sourceFeature": feature, "role": role,
                "dtype": "string" if categorical else "float64",
                "domain": sorted(_VALID_STATES - {"TRUE_NO_OPPORTUNITY"}) if categorical else "[0,1]" if role in {"posteriorMean", "posteriorReliability"} else "[0,infinity)",
                "missingTreatment": "REJECT_INVALID_OR_SOURCE_UNAVAILABLE",
            })
    content = {
        "schemaVersion": SCHEMA_VERSION, "sourceOrderedFeatures": source,
        "orderedFeatures": source + [row["name"] for row in additions],
        "featureCount": len(source) + len(additions),
        "wave1Features": v1, "wave2Features": v2, "additions": additions,
        "bindings": bindings,
        "wave1RawMissingTreatment": "HGB_NATIVE_NAN_ONLY_FOR_VERIFIED_TRUE_COLD_START",
        "wave1Representation": "VALID_RAW_PLUS_POSTERIOR_EFFECTIVE_N_RELIABILITY_HISTORY_STATE_UNCERTAINTY_STD",
        "wave2Representation": "APPROVED_POSTERIOR_ONLY_EXISTING_SOURCE_SLOT",
        "optionalWave2OutputsAdded": [],
    }
    return {**content, "schemaChecksum": _sha(content)}


def _check_dates(frame: pd.DataFrame) -> pd.Series:
    if "game_date" not in frame:
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_DATE_MISSING", "game_date is required before prior inputs may be read.")
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if dates.isna().any() or (len(dates) and dates.max() > pd.Timestamp(prior_v1.DEVELOPMENT_END)):
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_FINAL_OOT_SEALED", "Only valid registered Development dates may enter corrected prior treatment.")
    return dates


def _input_frame(frame: pd.DataFrame, selected: Sequence[str], *, wave: int, schema: Mapping[str, Any]) -> pd.DataFrame:
    required = list((prior_v1 if wave == 1 else prior_v2).required_input_columns(selected))
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_INPUT_MISSING", ", ".join(missing))
    reasons = [schema["bindings"][feature].get("missingReasonFeature") for feature in selected]
    columns = list(dict.fromkeys(required + [name for name in reasons if name and name in frame]))
    if set(columns) & _TARGET_NAMES:
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_TARGET_INPUT_PROHIBITED", "Targets cannot be supplied to prior engines.")
    return frame.loc[:, columns].copy()


def _fitted_payload_check(payload: Mapping[str, Any]) -> None:
    content = {key: value for key, value in payload.items() if key != "fittedTreatmentChecksum"}
    if payload.get("schemaVersion") != FITTED_SCHEMA_VERSION or payload.get("fittedTreatmentChecksum") != _sha(content):
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_FITTED_CHECKSUM_MISMATCH", "Saved prior treatment is not authenticated.")
    schema = payload["outputSchema"]
    schema_content = {key: value for key, value in schema.items() if key != "schemaChecksum"}
    if schema.get("schemaChecksum") != _sha(schema_content):
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_SCHEMA_CHECKSUM_MISMATCH", "Saved output schema is not authenticated.")


def _validated_outputs(
    original: pd.DataFrame, derived: pd.DataFrame, *, feature: str,
    binding: Mapping[str, Any], wave: int,
) -> tuple[dict[str, Any], np.ndarray]:
    names = binding["derivedOutputs"]
    needed = [names[role] for role in (V1_MODEL_OUTPUT_ROLES if wave == 1 else ("posteriorMean", "historyState", "priorLevel"))]
    missing = [name for name in needed if name not in derived]
    if missing:
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_OUTPUT_MISSING", ", ".join(missing))
    states = derived[names["historyState"]].astype(str)
    levels = derived[names["priorLevel"]].astype(str)
    posterior = pd.to_numeric(derived[names["posteriorMean"]], errors="coerce").to_numpy(dtype=np.float64)
    # Existing WHIP scientific authority explicitly governs this zero-outs
    # case. It is counted separately; no generic imputation is used.
    governed_fallback = (
        (wave == 2) & (feature == "pitcher_whip")
        & states.eq("COMPUTATION_FAILURE").to_numpy()
        & levels.eq("MLB_LEAGUE_POPULATION_GOVERNED_FALLBACK").to_numpy()
    )
    invalid = (~states.isin(_VALID_STATES).to_numpy() & ~governed_fallback) | ~np.isfinite(posterior)
    if wave == 1:
        for role in ("effectiveN", "posteriorReliability", "posteriorStd"):
            values = pd.to_numeric(derived[names[role]], errors="coerce").to_numpy(dtype=np.float64)
            invalid |= ~np.isfinite(values) | (values < 0.0)
            if role == "posteriorReliability":
                invalid |= values > 1.0
        raw = pd.to_numeric(original[feature], errors="coerce").to_numpy(dtype=np.float64)
        cold = states.eq("TRUE_COLD_START").to_numpy()
        invalid |= (~np.isfinite(raw) & ~cold) | (np.isfinite(raw) & ((raw < 0.0) | (raw > 1.0)))
        invalid |= (posterior < 0.0) | (posterior > 1.0)
    else:
        invalid |= posterior < 0.0
        if feature not in {"pitcher_whip", "pitcher_last250_avg_fastball_velocity", "batter_slg"}:
            invalid |= posterior > 1.0
        elif feature == "batter_slg":
            invalid |= posterior > 4.0
    evidence = {
        "feature": feature, "wave": wave, "rows": len(original),
        "historyStateCounts": dict(sorted(Counter(states).items())),
        "priorLevelCounts": dict(sorted(Counter(levels).items())),
        "governedWhipFallbackRows": int(np.sum(governed_fallback)),
        "invalidOrHeldReviewRows": int(np.sum(invalid)),
        "ordinaryMedianOrModeFallbackRows": 0,
    }
    if wave == 1:
        finite_raw = np.isfinite(raw)
        evidence.update({
            "preservedRawRows": int(np.sum(finite_raw)),
            "rawValueDifferentFromPosteriorRows": int(np.sum(finite_raw & (raw != posterior))),
            "trueColdRawMissingRetainedRows": int(np.sum(cold & np.isnan(raw))),
            "requiredDerivedOutputColumnsAdded": 5,
        })
    if invalid.any():
        raise CorrectedPriorTreatmentError(
            "CORRECTED_PRIOR_OUTPUT_REQUIRES_REVIEW",
            f"{feature}: {int(invalid.sum())} invalid/source-unavailable prior outputs require review; no ordinary imputation is authorized.", evidence=evidence,
        )
    return evidence, posterior


def transform_prior_frame(
    frame: pd.DataFrame, fitted_payload: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Reload the complete frozen representation and transform without fitting."""
    _check_dates(frame)
    _fitted_payload_check(fitted_payload)
    schema = fitted_payload["outputSchema"]
    out = frame.copy()
    evidence_rows: list[dict[str, Any]] = []
    additions: dict[str, Any] = {}
    for wave, key in ((1, "wave1Features"), (2, "wave2Features")):
        features = list(schema[key])
        if not features:
            continue
        engine = prior_v1 if wave == 1 else prior_v2
        fitted = fitted_payload[f"wave{wave}FittedAuthority"]
        inputs = _input_frame(frame, features, wave=wave, schema=schema)
        derived = engine.transform_prior_features(inputs, fitted, features=features)
        for feature in features:
            binding = schema["bindings"][feature]
            row, posterior = _validated_outputs(frame, derived, feature=feature, binding=binding, wave=wave)
            if wave == 1:
                for role in V1_MODEL_OUTPUT_ROLES:
                    name = binding["derivedOutputs"][role]
                    if name in frame:
                        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_DERIVED_INPUT_COLLISION", f"{name} already exists before prior treatment.")
                    additions[name] = derived[name].to_numpy(copy=True)
                row["validRawValuesPreserved"] = int(np.isfinite(pd.to_numeric(frame[feature], errors="coerce")).sum())
                row["nativeMissingRawColdStartRows"] = int(derived[binding["derivedOutputs"]["historyState"]].eq("TRUE_COLD_START").sum())
                row["posteriorReplacedRawRows"] = 0
            else:
                raw = pd.to_numeric(frame[feature], errors="coerce").to_numpy(dtype=np.float64)
                row["posteriorReplacedRawRows"] = int(np.sum(~np.isclose(raw, posterior, equal_nan=True, rtol=0.0, atol=0.0)))
                out[feature] = posterior
            evidence_rows.append(row)
    if additions:
        out = pd.concat([out, pd.DataFrame(additions, index=frame.index)], axis=1)
    evidence = {
        "schemaVersion": SCHEMA_VERSION, "status": "APPLIED", "rows": len(frame),
        "outputSchemaChecksum": schema["schemaChecksum"],
        "fittedTreatmentChecksum": fitted_payload["fittedTreatmentChecksum"],
        "features": evidence_rows, "fittingPerformed": False,
        "targetColumnsRead": [], "finalOotRowsRead": 0,
    }
    return out, {**evidence, "evidenceChecksum": _sha(evidence)}


def fit_transform_prior_pair(
    frame: pd.DataFrame, *, train_mask: np.ndarray, validation_mask: np.ndarray,
    fold: Mapping[str, Any], feature_set: Mapping[str, Any],
    eligibility_mask: np.ndarray | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """Fit only V1 training priors, bind existing V2 child, then transform pair."""
    dates = _check_dates(frame)
    train_mask = np.asarray(train_mask)
    validation_mask = np.asarray(validation_mask)
    if (train_mask.dtype != bool or validation_mask.dtype != bool
            or train_mask.shape != (len(frame),) or validation_mask.shape != (len(frame),)
            or np.any(train_mask & validation_mask) or not np.any(train_mask) or not np.any(validation_mask)):
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_FOLD_MASK_INVALID", "Disjoint nonempty boolean training/validation masks are required.")
    train_dates, validation_dates = dates[train_mask], dates[validation_mask]
    if (not train_dates.between(pd.Timestamp(fold["trainStart"]), pd.Timestamp(fold["trainEnd"])).all()
            or not validation_dates.between(pd.Timestamp(fold["validationStart"]), pd.Timestamp(fold["validationEnd"])).all()
            or train_dates.max() >= validation_dates.min()
            or not np.array_equal(train_mask, dates.between(pd.Timestamp(fold["trainStart"]), pd.Timestamp(fold["trainEnd"])).to_numpy())
            or not np.array_equal(validation_mask, dates.between(pd.Timestamp(fold["validationStart"]), pd.Timestamp(fold["validationEnd"])).to_numpy())):
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_FOLD_BOUNDARY_MISMATCH", "Masks do not respect registered chronological boundaries.")
    runtime = frame.attrs.get("governedPriorRuntime") or {}
    contract = feature_set.get("transformationContracts") or {}
    source = contract.get("sourceOrderedFeatures") or feature_set.get("sourceOrderedFeatures") or feature_set.get("orderedFeatures") or []
    schema = build_prior_output_schema(source, runtime)
    actual = list(feature_set.get("orderedFeatures") or [])
    if actual != schema["orderedFeatures"]:
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_REGISTERED_SCHEMA_MISMATCH", "The registered feature list must include the exact corrected prior output schema.")
    train_raw, validation_raw = frame.loc[train_mask].copy(), frame.loc[validation_mask].copy()
    eligible = np.ones(len(frame), dtype=bool) if eligibility_mask is None else np.asarray(eligibility_mask)
    if eligible.dtype != bool or eligible.shape != (len(frame),) or not (eligible & train_mask).any() or not (eligible & validation_mask).any():
        raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_ELIGIBILITY_MASK_INVALID", "A full-length Boolean eligibility mask must retain training and validation observations.")
    v1_fit = None
    v2_fit = None
    if schema["wave1Features"]:
        if not runtime.get("v1Authority"):
            raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_AUTHORITY_MISSING", "The exact V1 authority is required.")
        inputs = _input_frame(train_raw, schema["wave1Features"], wave=1, schema=schema)
        v1_fit = prior_v1.fit_prior_authority(inputs, training_end=str(fold["trainEnd"]), authority_manifest=runtime["v1Authority"], fold_id=f"CORRECTED_HGB_FOLD_{int(fold['foldNumber'])}", features=schema["wave1Features"])
    if schema["wave2Features"]:
        v2_fit = copy.deepcopy((runtime.get("v2FittedByFold") or {}).get(int(fold["foldNumber"])))
        if not v2_fit or v2_fit.get("trainingEnd") != fold["trainEnd"] or int(v2_fit.get("trainingRows") or 0) != int(train_mask.sum()):
            raise CorrectedPriorTreatmentError("CORRECTED_PRIOR_V2_FOLD_MISMATCH", "Existing fitted V2 authority does not match the exact training fold.")
        prior_v2._validate_fitted(v2_fit)
    content = {
        "schemaVersion": FITTED_SCHEMA_VERSION, "outputSchema": schema,
        "fold": dict(fold), "fitRows": int(train_mask.sum()),
        "trainingStart": str(fold["trainStart"]), "trainingEnd": str(fold["trainEnd"]),
        "wave1FittedAuthority": v1_fit, "wave2FittedAuthority": v2_fit,
        "wave1ParameterProvenance": "NEW_SUCCESSOR_TRAINING_FOLD_FIT_NOT_HISTORICAL_RECOVERY",
        "wave2ParameterProvenance": "EXISTING_EXACT_FOLD_CONTENT_ADDRESSED_AUTHORITY_NO_REFIT",
        "companionAuthenticationChecksum": runtime.get("companionAuthenticationChecksum"),
        "modelEligibleTrainRows": int((eligible & train_mask).sum()),
        "modelEligibleValidationRows": int((eligible & validation_mask).sum()),
        "populationRule": "PRIOR_PARAMETERS_FROM_ORIGINAL_TRAINING_FOLD_VALID_COMPONENTS_MODEL_QUARANTINE_APPLIED_AFTER_FIT",
        "validationRowsUsedForFit": 0, "targetColumnsRead": [], "finalOotRowsRead": 0,
    }
    payload = {**content, "fittedTreatmentChecksum": _sha(content)}
    train, train_evidence = transform_prior_frame(frame.loc[train_mask & eligible].copy(), payload)
    validation, validation_evidence = transform_prior_frame(frame.loc[validation_mask & eligible].copy(), payload)
    evidence = {
        "status": "APPLIED", "kind": SCHEMA_VERSION, "features": schema["wave1Features"] + schema["wave2Features"],
        "wave1Features": schema["wave1Features"], "wave2Features": schema["wave2Features"],
        "fitRows": int(train_mask.sum()), "validationRowsUsedForFit": 0,
        "finalOotRowsRead": 0, "targetColumnsRead": [],
        "featureCount": schema["featureCount"], "outputSchemaChecksum": schema["schemaChecksum"],
        "fittedTreatmentChecksum": payload["fittedTreatmentChecksum"],
        "train": train_evidence, "validation": validation_evidence,
        "wave1FittedChecksum": (v1_fit or {}).get("fittedChecksum"),
        "wave2FittedChecksum": (v2_fit or {}).get("fittedChecksum"),
    }
    return train, validation, {**evidence, "evidenceChecksum": _sha(evidence)}, payload
