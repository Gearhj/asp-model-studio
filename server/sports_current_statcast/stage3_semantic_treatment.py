"""Target-free semantic preprocessing for the immutable MLB treatment successor.

The public seam accepts already authorized training/validation frames. It never
scans data, fits a model, drops rows, changes eligibility, or reads targets. A
reason indicator is source evidence: it is validated before it authorizes zero,
native missingness, or the frozen contextual median.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..sports_datasets.consumer import canonical_json_bytes
from . import stage3_interaction_recomputation_authority as interactions

SCHEMA_VERSION = "MLB_SEMANTIC_TREATMENT_FITTED_V1"
SOURCE_PATH = Path(__file__).with_name("mlb_feature_treatment_spec_v1.json")
DEVELOPMENT_END = "2026-08-13"
_SOURCE_REASONS = frozenset({"SOURCE_UNAVAILABLE", "SOURCE_MISSING", "IDENTITY_FAILURE", "SOURCE_NOT_AVAILABLE_FOR_ERA"})
_INVALID_REASONS = frozenset({"COMPUTATION_FAILURE", "INVALID_VALUE", "DOMAIN_FAILURE"})
_VALID_REASONS = frozenset({"", "NO_PRIOR_HISTORY", "TRUE_COLD_START", "INSUFFICIENT_HISTORY", "SPARSE_HISTORY", "AVAILABLE"})


class SemanticTreatmentError(RuntimeError):
    def __init__(self, code: str, message: str, *, evidence: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.evidence = dict(evidence or {})
        super().__init__(message)


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _rule(kind: str, domain: str, *, indicator: str | None = None, always: Sequence[str] = (), unless_cold: Sequence[str] = ()) -> dict[str, Any]:
    return {"kind": kind, "domain": domain, "noHistoryIndicator": indicator,
            "sourceFailureIndicators": list(always), "sourceFailureIndicatorsUnlessNoHistory": list(unless_cold)}


def _rules() -> dict[str, dict[str, Any]]:
    rules: dict[str, dict[str, Any]] = {}
    for side in ("batting", "fielding"):
        cold = f"{side}_previous_game_missing"
        travel = ((f"{side}_current_venue_coordinates_missing",),
                  (f"{side}_previous_venue_coordinates_missing", f"{side}_travel_path_missing"))
        timezone = ((f"{side}_current_start_missing", f"{side}_current_venue_timezone_missing"),
                    (f"{side}_previous_venue_timezone_missing",))
        previous_start = ((f"{side}_current_start_missing",), (f"{side}_previous_game_start_missing",))
        contextual = {
            "westward_time_zone_change_hours": ("NONNEGATIVE_OFFSET_SHIFT", *timezone),
            "travel_distance_miles": ("NONNEGATIVE", *travel),
            "time_zone_change_hours": ("SIGNED_OFFSET_SHIFT", *timezone),
            "start_hour_in_previous_venue_time_zone": ("HOUR", (f"{side}_current_start_missing",), (f"{side}_previous_venue_timezone_missing",)),
            "previous_game_innings": ("NONNEGATIVE_INTEGER", (), (f"{side}_previous_game_innings_missing",)),
            "hours_since_previous_game_start": ("NONNEGATIVE", *previous_start),
            "eastward_time_zone_change_hours": ("NONNEGATIVE_OFFSET_SHIFT", *timezone),
            "days_since_previous_game": ("NONNEGATIVE_INTEGER", (), ()),
            "circadian_timezone_component": ("NONNEGATIVE_OFFSET_SHIFT", *timezone),
            "circadian_short_recovery_component": ("UNIT_INTERVAL", *previous_start),
            "circadian_disruption_score": ("NONNEGATIVE", (*timezone[0], f"{side}_team_home_timezone_missing"), (*timezone[1], f"{side}_previous_game_start_missing")),
        }
        for suffix, (domain, always, unless) in contextual.items():
            rules[f"{side}_{suffix}"] = _rule("NO_PRIOR_CONTEXT", domain, indicator=cold, always=always, unless_cold=unless)
        structural = {
            "previous_game_extra_innings": ((), (f"{side}_previous_game_innings_missing",)),
            "crossed_time_zone": timezone,
            "crossed_two_or_more_time_zones": timezone,
            "cross_country_travel": travel,
        }
        for suffix, (always, unless) in structural.items():
            rules[f"{side}_{suffix}"] = _rule("STRUCTURAL_ZERO", "BOOLEAN", indicator=cold, always=always, unless_cold=unless)
        for suffix, domain in {
            "travel_distance_last_3_days": "NONNEGATIVE", "travel_distance_last_7_days": "NONNEGATIVE",
            "start_hour_in_team_home_time_zone": "HOUR", "local_body_clock_offset_hours": "CIRCULAR_BODY_CLOCK_DISTANCE",
            "circadian_body_clock_component": "CIRCULAR_BODY_CLOCK_DISTANCE",
        }.items():
            rules[f"{side}_{suffix}"] = _rule("REQUIRED_COMPLETE", domain)
        # contextual_features publishes the number of matching-opponent games;
        # the registered model feature is the Boolean "any in this window".
        # Validate the complete count before repairing its Boolean domain.
        for days in (7, 14):
            rules[f"{side}_repeat_opponent_within_{days}_days"] = _rule("REPEAT_OPPONENT_BOOLEAN", "NONNEGATIVE_INTEGER")
    for feature, indicator in (("batter_log1p_pa", "batter_prior_missing"), ("pitcher_log1p_bfp", "pitcher_prior_missing")):
        rules[feature] = _rule("COLD_EXPOSURE", "LOG1P_INTEGER", indicator=indicator)
    for feature, domain in {"series_game_number": "POSITIVE_INTEGER", "game_day_of_season": "POSITIVE_INTEGER",
                            "local_start_hour": "HOUR", "local_start_hour_sin": "CYCLIC", "local_start_hour_cos": "CYCLIC"}.items():
        rules[feature] = _rule("REQUIRED_COMPLETE", domain)
    rules["matchup_platoon_advantage"] = _rule("MATCHUP_BOOLEAN", "BOOLEAN")
    return rules


RULES = _rules()
TRAVEL_INTERACTIONS = tuple(interactions.INTERACTION_FEATURES)
DETERMINISTIC_INTERACTIONS = tuple(f"{side}_home_x_{suffix}" for side in ("batting", "fielding") for suffix in ("weekend", "friday_night"))
MATCHUP_PARENTS = ("matchup_batter_bats_left", "matchup_batter_bats_switch", "matchup_pitcher_throws_left", "matchup_batter_hand_missing", "matchup_pitcher_hand_missing")


def _selected(features: Sequence[str]) -> tuple[list[str], list[str], list[str]]:
    selected = list(dict.fromkeys(str(value) for value in features))
    travel = [name for name in selected if name in TRAVEL_INTERACTIONS]
    deterministic = [name for name in selected if name in DETERMINISTIC_INTERACTIONS]
    treatment = {name for name in selected if name in RULES}
    for feature in travel:
        for parent in interactions.feature_binding(feature)["parents"]:
            if parent["feature"] in RULES:
                treatment.add(parent["feature"])
    return sorted(treatment), travel, deterministic


def required_input_columns(features: Sequence[str]) -> tuple[str, ...]:
    treatment, travel, deterministic = _selected(features)
    columns = {"game_date"}
    for feature in treatment:
        columns.add(feature)
        rule = RULES[feature]
        if rule["noHistoryIndicator"]:
            columns.add(rule["noHistoryIndicator"])
        columns.update(rule["sourceFailureIndicators"])
        columns.update(rule["sourceFailureIndicatorsUnlessNoHistory"])
    if "matchup_platoon_advantage" in treatment:
        columns.update(MATCHUP_PARENTS)
    if travel:
        columns.update(interactions.required_input_columns(travel))
        columns.update(travel)
    if deterministic:
        columns.add("context_top_bottom")
        columns.update(deterministic)
        if any(name.endswith("weekend") for name in deterministic):
            columns.add("is_weekend")
        if any(name.endswith("friday_night") for name in deterministic):
            columns.update(("is_friday", "is_night_game"))
    return tuple(sorted(columns))


def _dates(frame: pd.DataFrame, *, training_end: str | None = None) -> pd.Series:
    if "game_date" not in frame:
        raise SemanticTreatmentError("SEMANTIC_GAME_DATE_REQUIRED", "game_date is required before feature access.")
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if dates.isna().any() or dates.gt(pd.Timestamp(DEVELOPMENT_END)).any():
        raise SemanticTreatmentError("SEMANTIC_DATE_OUTSIDE_DEVELOPMENT", "Semantic treatment rejects invalid dates or Final OOT before reading feature payload.")
    if training_end is not None and dates.gt(pd.Timestamp(training_end)).any():
        raise SemanticTreatmentError("SEMANTIC_TRAINING_FRAME_CROSSES_FOLD", "Only this fold's training rows may be supplied to fit_semantic_treatment.")
    return dates


def _columns(frame: pd.DataFrame, required: Sequence[str]) -> None:
    absent = sorted(set(required) - set(frame.columns))
    if absent:
        raise SemanticTreatmentError("SEMANTIC_SOURCE_COLUMNS_MISSING", "Required registered source evidence is missing: " + ", ".join(absent), evidence={"missingColumns": absent})


def _numeric(frame: pd.DataFrame, name: str) -> np.ndarray:
    return pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=np.float64)


def _bool(frame: pd.DataFrame, name: str) -> np.ndarray:
    values = _numeric(frame, name)
    invalid = ~np.isfinite(values) | ~np.isin(values, (0.0, 1.0))
    if invalid.any():
        raise SemanticTreatmentError("SEMANTIC_INDICATOR_INVALID", f"{name} must be complete registered Boolean evidence.", evidence={"feature": name, "invalidRows": int(invalid.sum())})
    return values.astype(bool)


def _invalid_domain(values: np.ndarray, domain: str) -> np.ndarray:
    finite = np.isfinite(values)
    if domain == "BOOLEAN": bad = ~np.isin(values, (0.0, 1.0))
    elif domain in {"NONNEGATIVE", "NONNEGATIVE_INTEGER", "POSITIVE_INTEGER"}:
        bad = values < (1.0 if domain == "POSITIVE_INTEGER" else 0.0)
        if domain.endswith("INTEGER"): bad |= np.abs(values - np.rint(values)) > 1e-9
    # Source movement is co-po, not a circular clock distance. The workbook's
    # 'generally [-12,12]' is descriptive, not authority to reject a real
    # trans-Pacific offset difference such as 16 hours.
    elif domain == "SIGNED_OFFSET_SHIFT": bad = np.zeros(values.shape, dtype=bool)
    elif domain == "NONNEGATIVE_OFFSET_SHIFT": bad = values < 0.0
    elif domain == "CIRCULAR_BODY_CLOCK_DISTANCE": bad = (values < 0.0) | (values > 12.0)
    elif domain == "HOUR": bad = (values < 0.0) | (values >= 24.0)
    elif domain == "CYCLIC": bad = np.abs(values) > 1.0 + 1e-12
    elif domain == "UNIT_INTERVAL": bad = (values < 0.0) | (values > 1.0)
    elif domain == "LOG1P_INTEGER":
        with np.errstate(over="ignore", invalid="ignore"):
            exposure = np.expm1(values)
        bad = (values < 0.0) | ~np.isfinite(exposure) | (np.abs(exposure - np.rint(exposure)) > 1e-6)
    else: raise SemanticTreatmentError("SEMANTIC_DOMAIN_UNREGISTERED", domain)
    return finite & bad


def _state(frame: pd.DataFrame, feature: str, rule: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    values = _numeric(frame, feature)
    cold = _bool(frame, rule["noHistoryIndicator"]) if rule["noHistoryIndicator"] else np.zeros(len(frame), dtype=bool)
    source = np.zeros(len(frame), dtype=bool)
    invalid = _invalid_domain(values, str(rule["domain"]))
    invalid |= (~np.isfinite(values)) & frame[feature].notna().to_numpy()
    for indicator in rule["sourceFailureIndicators"]: source |= _bool(frame, indicator)
    for indicator in rule["sourceFailureIndicatorsUnlessNoHistory"]: source |= _bool(frame, indicator) & ~cold
    reason_column = f"{feature}__missing_reason"
    if reason_column in frame:
        reasons = frame[reason_column].fillna("").astype(str).str.upper().str.strip()
        source |= reasons.isin(_SOURCE_REASONS).to_numpy()
        invalid |= reasons.isin(_INVALID_REASONS).to_numpy() | ~reasons.isin(_SOURCE_REASONS | _INVALID_REASONS | _VALID_REASONS).to_numpy()
    if rule["kind"] in {"STRUCTURAL_ZERO", "COLD_EXPOSURE"}:
        invalid |= cold & np.isfinite(values) & (values != 0.0)
    unresolved = ~np.isfinite(values) & ~cold
    source |= unresolved & ~invalid
    return values, cold, source, invalid


def _reject(feature: str, source: np.ndarray, invalid: np.ndarray) -> None:
    if source.any() or invalid.any():
        raise SemanticTreatmentError("SEMANTIC_HELD_REVIEW_REQUIRED", f"{feature} has unavailable or invalid source evidence; no ordinary imputation or eligibility change is authorized.",
            evidence={"feature": feature, "sourceUnavailableRows": int(source.sum()), "invalidRows": int(invalid.sum())})


def _family(model_family: str) -> str:
    name = str(model_family).upper()
    if name in {"TREE", "HISTOGRAM_GRADIENT_BOOSTING", "HGB"}: return "TREE"
    if name in {"LINEAR", "MULTINOMIAL_LOGISTIC", "ELASTIC_NET_LOGISTIC", "SGD_CLASSIFIER"}: return "LINEAR"
    if name in {"NEURAL_OR_DISTANCE", "MLP", "KNN"}: return "NEURAL_OR_DISTANCE"
    raise SemanticTreatmentError("SEMANTIC_MODEL_FAMILY_UNSUPPORTED", f"No registered native/fill resolution for {model_family}.")


def fit_semantic_treatment(train: pd.DataFrame, *, features: Sequence[str], model_family: str, fold: Mapping[str, Any],
                           interaction_authority_manifest: Mapping[str, Any] | None = None,
                           source_identity: Mapping[str, Any] | None = None, seed: int | None = None) -> dict[str, Any]:
    cutoff = str(fold.get("trainEnd") or fold.get("trainingEnd") or "")
    if not cutoff or pd.Timestamp(cutoff) > pd.Timestamp(DEVELOPMENT_END):
        raise SemanticTreatmentError("SEMANTIC_TRAINING_BOUNDARY_INVALID", "An authorized fold trainEnd is required.")
    dates = _dates(train, training_end=cutoff)
    if train.empty: raise SemanticTreatmentError("SEMANTIC_EMPTY_TRAINING", "No training rows supplied.")
    if fold.get("trainStart") and dates.lt(pd.Timestamp(str(fold["trainStart"]))).any():
        raise SemanticTreatmentError("SEMANTIC_TRAINING_FRAME_CROSSES_FOLD", "Training rows precede the registered fold start.")
    if fold.get("trainRows") is not None and len(train) != int(fold["trainRows"]):
        raise SemanticTreatmentError("SEMANTIC_TRAINING_ROW_COUNT_MISMATCH", "Training frame does not match the registered fold row count.")
    selected = list(dict.fromkeys(str(name) for name in features))
    treatment, travel, deterministic = _selected(selected)
    required = required_input_columns(selected)
    _columns(train, required)
    family = _family(model_family)
    medians: dict[str, Any] = {}
    fit_counts: dict[str, Any] = {}
    for feature in treatment:
        rule = RULES[feature]
        values, cold, source, invalid = _state(train, feature, rule)
        if rule["kind"] != "MATCHUP_BOOLEAN": _reject(feature, source, invalid)
        eligible = np.isfinite(values) & ~cold & ~source & ~invalid
        fit_counts[feature] = {"trainingRows": len(train), "validObservedRows": int(eligible.sum()), "verifiedNoHistoryRows": int(cold.sum()), "sourceUnavailableRows": int(source.sum()), "invalidRows": int(invalid.sum())}
        if family != "TREE" and rule["kind"] == "NO_PRIOR_CONTEXT":
            if not eligible.any(): raise SemanticTreatmentError("SEMANTIC_CONTEXT_TRAINING_EVIDENCE_EMPTY", f"No eligible contextual training values for {feature}.")
            medians[feature] = {"method": "TRAINING_FOLD_CONTEXTUAL_MEDIAN", "value": float(np.median(values[eligible])), "fitRows": int(eligible.sum()), "validationRowsFit": 0, "finalOotRowsFit": 0}
    nested = None
    if travel:
        if interaction_authority_manifest is None:
            raise SemanticTreatmentError("SEMANTIC_INTERACTION_AUTHORITY_REQUIRED", "The exact existing project-bound interaction authority is required.")
        nested = interactions.fit_interaction_authority(train, training_end=cutoff, authority_manifest=interaction_authority_manifest,
            fold_id=str(fold.get("foldId") or f"SEMANTIC_FOLD_{fold.get('foldNumber', 0)}"), model_family=family, features=travel)
        # Duration is observational evidence, not learned state or identity.
        nested.pop("fitDurationMs", None)
        for feature, parameter in nested["parentParameters"].items():
            if feature in medians and parameter["value"] != medians[feature]["value"]:
                raise SemanticTreatmentError("SEMANTIC_PARENT_PARAMETER_MISMATCH", f"Shared contextual parent differs from existing interaction authority: {feature}.")
    source_bytes = SOURCE_PATH.read_bytes()
    source = json.loads(source_bytes)
    content = {
        "schemaVersion": SCHEMA_VERSION, "modelFamily": family, "requestedModelFamily": str(model_family),
        "features": selected, "treatmentFeatures": treatment, "rules": {name: copy.deepcopy(RULES[name]) for name in treatment},
        "requiredInputColumns": list(required), "contextualMedians": medians,
        "travelInteractions": travel, "deterministicInteractions": deterministic, "interactionFitted": nested,
        "nativeMissingFeatures": [*[name for name in treatment if RULES[name]["kind"] == "NO_PRIOR_CONTEXT"], *travel] if family == "TREE" else [],
        "trainingStart": dates.min().date().isoformat(), "trainingEnd": cutoff, "trainingRows": len(train),
        "fold": dict(fold), "seed": seed, "sourceIdentity": dict(source_identity or {}),
        "sourceSpecificationKey": source["specification_key"], "sourceSpecificationSha256": hashlib.sha256(source_bytes).hexdigest(),
        "semanticCodeSha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "fitCounts": fit_counts, "validationRowsFit": 0, "finalOotRowsRead": 0, "targetColumnsRead": [],
        "parentOnlyAblationStatus": "DEFERRED_BY_APPROVED_BOUNDED_STUDY", "rowsExcluded": 0,
    }
    checksum = _hash(content)
    fitted = {**content, "fittedChecksum": checksum, "fittedId": f"{SCHEMA_VERSION}:sha256:{checksum}"}
    # Validate the complete training transformation before model fitting.
    transform_semantic_treatment(train, fitted)
    return fitted


def _verify_fitted(fitted: Mapping[str, Any]) -> None:
    content = {key: copy.deepcopy(value) for key, value in fitted.items() if key not in {"fittedChecksum", "fittedId"}}
    checksum = _hash(content)
    if fitted.get("schemaVersion") != SCHEMA_VERSION or fitted.get("fittedChecksum") != checksum or fitted.get("fittedId") != f"{SCHEMA_VERSION}:sha256:{checksum}":
        raise SemanticTreatmentError("SEMANTIC_FITTED_CHECKSUM_MISMATCH", "Persisted semantic fitted state failed its identity check.")
    if fitted.get("rules") != {name: RULES[name] for name in fitted["treatmentFeatures"]}:
        raise SemanticTreatmentError("SEMANTIC_FITTED_RULES_STALE", "Fitted semantic rules differ from the executable registry.")
    current_code = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    if fitted.get("semanticCodeSha256") != current_code:
        raise SemanticTreatmentError("SEMANTIC_FITTED_CODE_STALE", "Reload requires the exact semantic implementation bound by the fitted artifact.")


def _changed(before: np.ndarray, after: np.ndarray) -> int:
    return int((~((before == after) | (np.isnan(before) & np.isnan(after)))).sum())


def transform_semantic_treatment(frame: pd.DataFrame, fitted: Mapping[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    _dates(frame)
    _verify_fitted(fitted)
    _columns(frame, fitted["requiredInputColumns"])
    output = frame.copy()
    branches: dict[str, Any] = {}
    for feature in fitted["treatmentFeatures"]:
        rule = fitted["rules"][feature]
        values, cold, source, invalid = _state(frame, feature, rule)
        kind = rule["kind"]
        if kind == "MATCHUP_BOOLEAN":
            left, switch, pitcher_left, batter_unknown, pitcher_unknown = (_bool(frame, name) for name in MATCHUP_PARENTS)
            _reject(feature, batter_unknown | pitcher_unknown, invalid | (left & switch))
            treated = (switch | (left != pitcher_left)).astype(np.float64)
        else:
            _reject(feature, source, invalid)
            treated = values.copy()
            if kind in {"STRUCTURAL_ZERO", "COLD_EXPOSURE"}: treated[cold] = 0.0
            elif kind == "REPEAT_OPPONENT_BOOLEAN": treated = (values > 0.0).astype(np.float64)
            elif kind == "NO_PRIOR_CONTEXT":
                treated[cold] = np.nan if fitted["modelFamily"] == "TREE" else float(fitted["contextualMedians"][feature]["value"])
        output[feature] = treated
        branches[feature] = {"rows": len(frame), "verifiedNoHistoryRows": int(cold.sum()),
            "semanticZeroRows": int(cold.sum()) if kind in {"STRUCTURAL_ZERO", "COLD_EXPOSURE"} else 0,
            "nativeMissingRows": int((~np.isfinite(treated)).sum()),
            "contextualFillRows": int(cold.sum()) if kind == "NO_PRIOR_CONTEXT" and fitted["modelFamily"] != "TREE" else 0,
            "sourceUnavailableRows": 0, "invalidRows": 0, "futureMissingRejectedRows": 0,
            "deterministicRecomputedRows": len(frame) if kind in {"MATCHUP_BOOLEAN", "REPEAT_OPPONENT_BOOLEAN"} else 0,
            "booleanDomainRepairRows": _changed(values, treated) if kind == "REPEAT_OPPONENT_BOOLEAN" else 0,
            "changedRows": _changed(values, treated)}
    travel = fitted["travelInteractions"]
    if travel:
        semantic = interactions.transform_interactions(output, fitted["interactionFitted"], features=travel)
        for feature in travel:
            state = semantic[f"{feature}__state"].astype(str)
            _reject(feature, state.eq("SOURCE_UNAVAILABLE").to_numpy(), state.eq("COMPUTATION_FAILURE").to_numpy())
            values = semantic[feature].to_numpy(dtype=np.float64)
            binding = interactions.feature_binding(feature)
            parents = [pd.to_numeric(output[name], errors="coerce").to_numpy(dtype=np.float64) for name in binding["orderedParents"]]
            expected = interactions._apply_formula(binding, parents)
            if not np.array_equal(values, expected, equal_nan=True):
                raise SemanticTreatmentError("SEMANTIC_INTERACTION_PARENT_IDENTITY_FAILED", f"{feature} does not equal its prescribed transformed-parent formula.")
            output[feature] = values
            branches[feature] = {"rows": len(frame), "recomputedRows": len(frame), "parentEqualityPassed": True,
                "nativeMissingRows": int((~np.isfinite(values)).sum()), "sourceUnavailableRows": 0, "invalidRows": 0,
                "changedRows": _changed(_numeric(frame, feature), values)}
    if fitted["deterministicInteractions"]:
        batting_home = _bool(output, "context_top_bottom")
        for feature in fitted["deterministicInteractions"]:
            home = batting_home if feature.startswith("batting_") else ~batting_home
            factor = _bool(output, "is_weekend") if feature.endswith("weekend") else (_bool(output, "is_friday") & _bool(output, "is_night_game"))
            values = (home & factor).astype(np.float64)
            output[feature] = values
            branches[feature] = {"rows": len(frame), "recomputedRows": len(frame), "parentEqualityPassed": True,
                "changedRows": _changed(_numeric(frame, feature), values), "sourceUnavailableRows": 0, "invalidRows": 0}
    changed_columns = list(dict.fromkeys([*fitted["treatmentFeatures"], *travel, *fitted["deterministicInteractions"]]))
    digest = hashlib.sha256(canonical_json_bytes({"columns": changed_columns}))
    if changed_columns:
        digest.update(pd.util.hash_pandas_object(output[changed_columns], index=False).to_numpy(dtype=np.uint64).tobytes())
    evidence = {"schemaVersion": "MLB_SEMANTIC_TREATMENT_TRANSFORM_EVIDENCE_V1", "fittedId": fitted["fittedId"],
        "fittedChecksum": fitted["fittedChecksum"], "rows": len(frame), "rowsExcluded": 0, "features": branches,
        "transformedColumnsChecksum": digest.hexdigest(), "targetColumnsRead": [], "finalOotRowsRead": 0,
        "parametersRefit": False, "parentOnlyAblationStatus": fitted["parentOnlyAblationStatus"]}
    evidence["evidenceChecksum"] = _hash(evidence)
    return output, evidence


def validate_model_frame(frame: pd.DataFrame, *, feature_set: Mapping[str, Any],
                         semantic_fitted: Mapping[str, Any], prior_fitted: Mapping[str, Any]) -> dict[str, Any]:
    """Guard every fitted/validation/reloaded matrix before its encoder.

    NaN is an allowed semantic state only in a named native-missing column
    and only on a row whose registered reason proves no history. HGB's ability
    to accept arbitrary NaN must not turn source failures into model inputs.
    """
    _dates(frame)
    _verify_fitted(semantic_fitted)
    features = list(feature_set.get("orderedFeatures") or [])
    if not features or len(features) != len(set(features)) or frame.columns.duplicated().any():
        raise SemanticTreatmentError("SEMANTIC_MODEL_SCHEMA_INVALID", "Model fields must be unique and explicitly ordered.")
    _columns(frame, features)
    contract = feature_set.get("transformationContracts") or {}
    entries = list(contract.get("ordered") or [])
    if [item.get("feature") for item in entries] != features:
        raise SemanticTreatmentError("SEMANTIC_MODEL_TRANSFORM_ORDER_MISMATCH", "Model feature order and registered transformations differ.")
    schema = prior_fitted.get("outputSchema") or {}
    wave1 = set(schema.get("wave1Features") or [])
    bindings = schema.get("bindings") or {}
    additions = {item["name"]: item for item in schema.get("additions") or []}
    native = set(semantic_fitted.get("nativeMissingFeatures") or [])
    branches: dict[str, Any] = {}
    for entry in entries:
        name = str(entry["feature"])
        steps = tuple(entry.get("steps") or [])
        if steps in {("SEMANTIC_BOOLEAN_PASSTHROUGH",), ("BINARY_PASSTHROUGH",)}:
            _bool(frame, name)
            branches[name] = {"kind": "BOOLEAN", "validatedRows": len(frame), "nativeMissingRows": 0}
            continue
        if steps == ("CATEGORICAL_UNKNOWN", "ONE_HOT"):
            addition = additions.get(name)
            if addition and addition.get("role") == "historyState":
                allowed = set(addition.get("domain") or [])
                invalid = frame[name].isna() | ~frame[name].isin(allowed)
                if invalid.any():
                    raise SemanticTreatmentError("SEMANTIC_MODEL_PRIOR_STATE_INVALID", f"{name} contains missing or held-review prior state.", evidence={"feature": name, "invalidRows": int(invalid.sum())})
            branches[name] = {"kind": "CATEGORICAL", "validatedRows": len(frame), "nativeMissingRows": 0}
            continue
        if steps not in {("SEMANTIC_NUMERIC_PASSTHROUGH",), ("RETAIN_RAW",), ("GOVERNED_PRIOR_POSTERIOR_MEAN",)}:
            raise SemanticTreatmentError("SEMANTIC_MODEL_TRANSFORM_UNSUPPORTED", f"Unsupported corrected-model steps for {name}: {steps}.")
        values = _numeric(frame, name)
        invalid_numeric = (~np.isfinite(values)) & frame[name].notna().to_numpy()
        null = np.isnan(values)
        authorized = np.zeros(len(frame), dtype=bool)
        if semantic_fitted["modelFamily"] == "TREE":
            if name in native:
                rule = semantic_fitted["rules"].get(name)
                if rule and rule["kind"] == "NO_PRIOR_CONTEXT":
                    authorized = _bool(frame, rule["noHistoryIndicator"])
                elif name in semantic_fitted["travelInteractions"]:
                    binding = interactions.feature_binding(name)
                    for parent in binding["parents"]:
                        if parent["pairedMissingnessIndicator"]:
                            authorized |= _bool(frame, parent["pairedMissingnessIndicator"])
            if name in wave1:
                state_name = (bindings[name].get("derivedOutputs") or {}).get("historyState")
                if not state_name or state_name not in frame:
                    raise SemanticTreatmentError("SEMANTIC_MODEL_PRIOR_STATE_MISSING", f"{name} lacks its registered cold-start state output.")
                authorized = frame[state_name].eq("TRUE_COLD_START").to_numpy()
        invalid = invalid_numeric | (null & ~authorized)
        if invalid.any():
            raise SemanticTreatmentError("SEMANTIC_MODEL_NUMERIC_STATE_INVALID", f"{name} contains nonfinite values without valid native-missing authority.",
                evidence={"feature": name, "invalidRows": int(invalid.sum()), "unapprovedNullRows": int((null & ~authorized).sum()), "invalidNumericRows": int(invalid_numeric.sum())})
        branches[name] = {"kind": "NUMERIC", "validatedRows": len(frame), "nativeMissingRows": int(null.sum())}
    result = {"status": "PASS", "rows": len(frame), "modelFeatureCount": len(features),
              "features": branches, "ordinaryFallbackRows": 0, "finalOotRowsRead": 0, "targetColumnsRead": []}
    result["evidenceChecksum"] = _hash(result)
    return result
