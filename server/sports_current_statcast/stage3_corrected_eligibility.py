"""Explicit, outcome-independent eligibility for the corrected comparison.

The source population is never changed. This helper returns a model-row mask
and immutable evidence only; it does not transform priors or invent values.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from numbers import Real
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

from ..sports_datasets.consumer import canonical_json_bytes

POLICY_VERSION = "MLB_CORRECTED_ROW_ELIGIBILITY_V1"
REASON = "V1_KNOWN_ZERO_PRIOR_PA_UNSUPPORTED_HISTORY_STATE"
RAW_FEATURES = ("batter_so_per_pa", "batter_bb_hbp_per_pa", "batter_hr_per_pa")


def _sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def registered_policy() -> dict[str, Any]:
    # Import locally: the specification itself binds this policy into its
    # schema; this accessor performs no dataset or persistence operation.
    from .stage3_corrected_treatment_spec import correction_decision

    policy = copy.deepcopy(correction_decision()["correctedRowEligibility"])
    return {**policy, "policyChecksum": _sha(policy)}


def required_input_columns(feature_set: Mapping[str, Any]) -> tuple[str, ...]:
    policy = (feature_set.get("transformationContracts") or {}).get("rowEligibilityPolicy")
    if not policy:
        return ()
    return ("game_date", "canonicalPaId", "canonicalGameId", "batter_log1p_pa", "batter_prior_missing", *RAW_FEATURES)


def eligibility_mask(frame: pd.DataFrame, feature_set: Mapping[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    contract = feature_set.get("transformationContracts") or {}
    policy = contract.get("rowEligibilityPolicy")
    if not policy:
        evidence = {"schemaVersion": POLICY_VERSION, "status": "NOT_REGISTERED_NOT_APPLIED", "sourceRows": len(frame), "eligibleRows": len(frame), "heldRows": 0}
        return np.ones(len(frame), dtype=bool), {**evidence, "eligibilityChecksum": _sha(evidence)}
    if contract.get("semanticTreatmentVersion") != "MLB_SEMANTIC_TREATMENT_V1" or dict(policy) != registered_policy():
        raise ValueError("Corrected row eligibility requires the exact registered outcome-independent policy.")
    # Check the date-only seal before touching any feature payload.
    if "game_date" not in frame:
        raise ValueError("Corrected row eligibility requires valid Development dates.")
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if dates.isna().any() or ((dates < pd.Timestamp("2023-03-30")) | (dates > pd.Timestamp("2026-08-13"))).any():
        raise ValueError("FINAL_OOT_SEALED: corrected eligibility accepts registered Development dates only.")
    missing = sorted(set(required_input_columns(feature_set)) - set(frame.columns))
    if missing:
        raise ValueError("Corrected row-eligibility inputs are absent: " + ", ".join(missing))
    identities = frame.loc[:, ["canonicalPaId", "canonicalGameId"]]
    if identities.isna().any(axis=None) or frame["canonicalPaId"].duplicated().any():
        raise ValueError("Corrected eligibility requires non-null, unique immutable PA identity.")
    exposure = frame["batter_log1p_pa"]
    flag = frame["batter_prior_missing"]
    # Strings, null flags, nonbinary values and malformed exposure cannot
    # qualify for this narrow exception. They remain subject to normal guards.
    zero = np.zeros(len(frame), dtype=bool)
    if is_numeric_dtype(exposure.dtype) and not is_bool_dtype(exposure.dtype):
        numeric = exposure.to_numpy(dtype=np.float64, na_value=np.nan)
        zero = np.isfinite(numeric) & (numeric == 0.0)
    else:
        zero = exposure.map(lambda value: isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) and np.isfinite(value) and value == 0.0).to_numpy(dtype=bool)
    false_flag = np.zeros(len(frame), dtype=bool)
    if is_bool_dtype(flag.dtype) or is_numeric_dtype(flag.dtype):
        numeric_flag = flag.to_numpy(dtype=np.float64, na_value=np.nan)
        false_flag = np.isfinite(numeric_flag) & (numeric_flag == 0.0)
    else:
        false_flag = flag.map(lambda value: (isinstance(value, (bool, np.bool_)) or isinstance(value, Real)) and pd.notna(value) and value == 0).to_numpy(dtype=bool)
    all_raw_null = frame.loc[:, list(RAW_FEATURES)].isna().all(axis=1).to_numpy(dtype=bool)
    held = zero & false_flag & all_raw_null
    held_rows = [
        {"canonicalPaId": str(pa_id), "canonicalGameId": str(game_id), "gameDate": pd.Timestamp(date).date().isoformat(), "reason": REASON}
        for pa_id, game_id, date in frame.loc[held, ["canonicalPaId", "canonicalGameId", "game_date"]].itertuples(index=False, name=None)
    ]
    source_keys = frame["canonicalPaId"].astype(str).tolist()
    evidence = {
        "schemaVersion": POLICY_VERSION, "status": "APPLIED_EXPLICIT_OUTCOME_INDEPENDENT_QUARANTINE",
        "policyChecksum": policy["policyChecksum"], "featureSetId": feature_set.get("featureSetId"),
        "featureSetChecksum": feature_set.get("checksum"), "treatmentManifestChecksum": contract.get("treatmentManifestChecksum"),
        "modelFeatureSchemaChecksum": contract.get("modelFeatureSchemaChecksum"),
        "sourceRows": len(frame), "eligibleRows": int((~held).sum()), "heldRows": int(held.sum()),
        "coveragePercent": 100.0 * float((~held).sum()) / len(frame) if len(frame) else 100.0,
        "sourceRowIdentityChecksum": hashlib.sha256(("\n".join(source_keys) + "\n").encode("utf-8")).hexdigest(),
        "heldRowsByReason": {REASON: int(held.sum())},
        "heldRowsByYear": {str(year): int(count) for year, count in dates.loc[held].dt.year.value_counts().sort_index().items()},
        "heldObservations": held_rows,
        "sourceRowsDeleted": 0, "valuesImputed": 0, "statesRelabeledAsColdStart": 0,
        "whipGovernedFallbackExcludedByThisPolicy": False,
        "targetValuesRead": 0, "finalOotPayloadRowsRead": 0,
        "unknownInvalidStates": "REMAIN_SUBJECT_TO_EXISTING_FAIL_CLOSED_TREATMENT_GUARDS",
    }
    return ~held, {**evidence, "eligibilityChecksum": _sha(evidence)}
