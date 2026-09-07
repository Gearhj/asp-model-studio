"""Project-bound Stage 3 feature inventory and immutable candidate-set service.

This module is intentionally a contract/configuration surface.  It resolves the
same accepted Current-Gold authority used by Stage 3 EDA, reads development
evidence only, and persists feature-set definitions.  It has no provider,
materialization, preprocessing-fit, model-fit, scoring, or promotion entry
point.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from ..persistence.db import Database
from ..persistence.repositories.stage3_feature_set_repository import (
    NO_CURRENT_FEATURE_SET,
    Stage3FeatureSetPersistenceError,
    Stage3FeatureSetRepository,
)
from ..persistence.repositories.stage3_treatment_repository import Stage3TreatmentRepository
from ..sports_gold.contracts import GOLD_FEATURES
from . import stage3_eda as eda
from . import stage3_treatments as treatments
from .contextual_features import (
    CONTEXT_FEATURES,
    EXCLUDED_INTERACTIONS,
    FUTURE_ABLATION_FAMILIES,
    INTERACTION_FEATURES,
    ORDERED_GOLD_PLUS_CONTEXT_FEATURES,
    RIVALRY_AUTHORITY_STATUS,
)


FEATURE_STUDIO_SCHEMA_VERSION = "SPORTS_STAGE3_FEATURE_ENGINEERING_V1"
MAX_PAGE_SIZE = 254
DEFAULT_PAGE_SIZE = 50
FOLD_LOCAL_RULE = (
    "Fit every learned transformation parameter on the training rows of each "
    "chronological fold only; apply the frozen fold parameter to validation."
)
FINAL_FIT_RULE = (
    "After development-only selection is frozen, refit preprocessing on all "
    "authorized pre-final-OOT development rows and apply once to locked final OOT."
)

_SUBJECTIVE_RIVALRY_FEATURES = frozenset(
    {
        "rivalry_pair",
        "rivalry_game",
        "home_rivalry_game",
        "friday_night_home_rivalry",
        "weekend_home_rivalry",
        "home_x_rivalry",
    }
)
_SUPPORTED_TRANSFORMATIONS = frozenset(
    {
        "NONE",
        "RETAIN_RAW",
        "LOG1P",
        "STANDARDIZE",
        "ROBUST_SCALE",
        "QUANTILE_TRANSFORM",
        "BOUNDED_TRANSFORM",
        "GOVERNED_PRIOR_POSTERIOR_MEAN",
        "CATEGORICAL_UNKNOWN",
        "ONE_HOT",
        "BINARY_PASSTHROUGH",
        "BINARY_MODE_IMPUTE",
        "MISSING_INDICATOR",
        "ADOPTED_OUTLIER_POLICY",
        "ADOPTED_MISSING_POLICY",
    }
)
_TRANSFORM_ALIASES = {
    "ROBUST_SCALING": "ROBUST_SCALE",
    "QUANTILE": "QUANTILE_TRANSFORM",
    "FOLD_LOCAL_QUANTILE": "QUANTILE_TRANSFORM",
    "BOUNDED": "BOUNDED_TRANSFORM",
    "KEEP_RAW": "RETAIN_RAW",
    "NO_TRANSFORMATION": "NONE",
}
_NUMERIC_ONLY = frozenset(
    {
        "LOG1P",
        "STANDARDIZE",
        "ROBUST_SCALE",
        "QUANTILE_TRANSFORM",
        "BOUNDED_TRANSFORM",
        "GOVERNED_PRIOR_POSTERIOR_MEAN",
    }
)
_CATEGORICAL_ONLY = frozenset({"CATEGORICAL_UNKNOWN", "ONE_HOT"})
_INVENTORY_SORT_FIELDS = frozenset(
    {
        "order",
        "name",
        "featureFamily",
        "dataType",
        "governanceStatus",
        "missingPercentDevelopment",
        "missingPercentFinalOot",
        "coverageDevelopment",
        "coverageFinalOot",
        "adoptedOutlierTreatment",
        "adoptedMissingTreatment",
    }
)


class Stage3FeatureEngineeringError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)

    def public_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


def _raw_name(name: str) -> str:
    return name.removeprefix("batting_").removeprefix("fielding_")


def _is_binary(name: str, meta: Mapping[str, Any]) -> bool:
    raw = _raw_name(name)
    return bool(
        meta.get("role") == "MISSINGNESS_INDICATOR"
        or raw.startswith("is_")
        or raw.endswith(("_indicator", "_missing", "_insufficient"))
        or raw.startswith(("played_", "crossed_", "returned_", "first_game_"))
        or raw
        in {
            "same_league_game",
            "interleague_game",
            "division_game",
            "same_division",
            "doubleheader_today",
            "doubleheader_yesterday",
            "previous_game_was_away",
            "previous_game_was_home",
            "repeat_opponent_within_7_days",
            "repeat_opponent_within_14_days",
            "series_rematch_indicator",
        }
    )


def _governance_status(name: str) -> tuple[str, str | None]:
    if _raw_name(name) in _SUBJECTIVE_RIVALRY_FEATURES:
        return (
            "INACTIVE_PENDING_RIVALRY_APPROVAL",
            "The explicit rivalry mapping is proposed but not approved; the field cannot enter a candidate set.",
        )
    return "ELIGIBLE", None


def _authority_payload(authority: eda._Authority) -> dict[str, Any]:
    return treatments._authority_payload(authority)


def _persistence_authority(authority: eda._Authority) -> dict[str, Any]:
    return treatments._persistence_authority(authority)


def _audit() -> dict[str, Any]:
    return {
        **treatments._audit(),
        "featureEngineeringActivity": {
            "sourceRowsMutated": 0,
            "goldRowsMutated": 0,
            "preprocessingFits": 0,
            "modelFits": 0,
            "scores": 0,
            "candidateRegistrations": 0,
            "promotions": 0,
        },
        "finalOotTargetsAccessed": False,
    }


def _population(*, rows: int = eda.DEVELOPMENT_ROWS, aggregation: str) -> dict[str, Any]:
    return eda._population(filters={}, rows=rows, aggregation=aggregation)


def _envelope(
    authority: eda._Authority,
    *,
    data: Mapping[str, Any],
    aggregation: str,
    rows: int = eda.DEVELOPMENT_ROWS,
) -> dict[str, Any]:
    return {
        "ok": True,
        "schemaVersion": FEATURE_STUDIO_SCHEMA_VERSION,
        "authority": _authority_payload(authority),
        "population": _population(rows=rows, aggregation=aggregation),
        "audit": _audit(),
        "data": dict(data),
    }


def _reject_oot_request(payload: Mapping[str, Any] | None) -> None:
    if not payload:
        return
    serialized = str(dict(payload)).upper()
    forbidden = (
        "FINAL_OOT_TARGET",
        "INCLUDEOOTOUTCOME",
        "INCLUDE_FINAL_OOT_OUTCOME",
        "OOT_TARGET_DISTRIBUTION",
        "OOT_TARGET_COUNTS",
    )
    population = str(payload.get("population") or payload.get("datasetRole") or "").upper()
    if population in {"FINAL_OOT", "OOT", "ALL_WITH_TARGETS"} or any(token in serialized for token in forbidden):
        raise Stage3FeatureEngineeringError(
            "FINAL_OOT_TARGET_ACCESS_PROHIBITED",
            "Feature Engineering may review predictor coverage but may not access final-OOT target counts, distributions, or outcomes.",
            status_code=409,
        )
    filters = payload.get("filters")
    if isinstance(filters, Mapping):
        if filters.get("outcomes"):
            raise Stage3FeatureEngineeringError(
                "TARGET_DERIVED_FEATURE_SELECTION_PROHIBITED",
                "Feature inventory and candidate-set selection cannot be conditioned on the governed outcome target.",
            )
        end = str(filters.get("endDate") or eda.DEVELOPMENT_END)
        if end > eda.DEVELOPMENT_END:
            raise Stage3FeatureEngineeringError(
                "FINAL_OOT_FILTER_PROHIBITED",
                f"Feature Engineering analytical dates must end by {eda.DEVELOPMENT_END}; final OOT is locked.",
                status_code=409,
            )


def _catalog(authority: eda._Authority) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    eda_meta = {str(item["name"]): dict(item) for item in eda._variables(authority)}
    review_meta = {
        str(item["name"]): dict(item)
        for item in authority.contextual_review.get("features") or []
    }
    rows: list[dict[str, Any]] = []
    for index, name in enumerate(ORDERED_GOLD_PLUS_CONTEXT_FEATURES, start=1):
        meta = eda_meta.get(name)
        review = review_meta.get(name)
        if not meta or not review:
            raise Stage3FeatureEngineeringError(
                "FEATURE_CONTRACT_INCOMPLETE",
                f"The exact accepted contextual publication does not expose required predictor {name}.",
                status_code=409,
            )
        status, reason = _governance_status(name)
        development_coverage = float(review.get("coverageDevelopment") or 0.0)
        oot_coverage = float(review.get("coverageFinalOot") or 0.0)
        rows.append(
            {
                "order": index,
                "name": name,
                "label": meta.get("label"),
                "definition": review.get("definition") or meta.get("definition"),
                "dataType": meta.get("dataType"),
                "role": meta.get("role"),
                "featureFamily": review.get("family") or meta.get("featureFamily"),
                "category": review.get("category"),
                "core": name in GOLD_FEATURES,
                "contextual": name in CONTEXT_FEATURES,
                "binary": _is_binary(name, meta),
                "sourceLineage": review.get("sourceLineage"),
                "pointInTimeTreatment": review.get("pointInTimeTreatment"),
                "proxyWarning": review.get("proxyWarning"),
                "availabilityEra": meta.get("availabilityEra"),
                "coverageOverall": float(review.get("coverageOverall") or 0.0),
                "coverageDevelopment": development_coverage,
                "coverageFinalOot": oot_coverage,
                "missingPercentDevelopment": 100.0 * (1.0 - development_coverage),
                "missingPercentFinalOot": 100.0 * (1.0 - oot_coverage),
                "physicalMissingnessPercent": 100.0 * (1.0 - development_coverage),
                "earliestDevelopmentDate": eda.DEVELOPMENT_START,
                "latestDevelopmentDate": eda.DEVELOPMENT_END,
                "declaredUniqueCount": meta.get("uniqueCount"),
                "cardinalityRangeStatus": "DETAIL_ON_DEMAND_DEVELOPMENT_ONLY",
                "cardinality": meta.get("uniqueCount"),
                "minimum": None,
                "maximum": None,
                "availabilityStatus": "AVAILABLE_IN_EXACT_CONTEXTUAL_GOLD",
                "forecastTimeAvailability": (
                    "SIMULATOR_SUPPLIED_AT_FORECAST_TIME"
                    if meta.get("role") == "SIMULATION_GENERATED_STATE"
                    else "PREGAME_OR_STRICTLY_PRIOR_DATE_EVIDENCE"
                ),
                "simulationGeneratedState": meta.get("role") == "SIMULATION_GENERATED_STATE",
                "leakageRisk": (
                    "SIMULATOR_VALUE_REQUIRED_NEVER_ACTUAL_TARGET_GAME_STATE"
                    if meta.get("role") == "SIMULATION_GENERATED_STATE"
                    else "LOW_ACCEPTED_POINT_IN_TIME_CONTRACT"
                ),
                "coldStartRelevance": (
                    "RELEVANT_EXPLICIT_MISSINGNESS_RETAINED"
                    if any(
                        token in _raw_name(name)
                        for token in (
                            "last",
                            "prior",
                            "previous",
                            "recent",
                            "rolling",
                            "career",
                            "season_to_date",
                            "days_since",
                            "games_last",
                        )
                    )
                    else "NOT_PRIMARY_COLD_START_FEATURE"
                ),
                "interactionMembership": (
                    [_raw_name(name)] if _raw_name(name) in INTERACTION_FEATURES else []
                ),
                "governanceStatus": status,
                "featureState": "ACTIVE" if status == "ELIGIBLE" else "INACTIVE",
                "eligible": status == "ELIGIBLE",
                "inactiveReason": reason,
                "unavailableReason": None,
                "stateReason": reason or "Exact feature exists in the accepted contextual Gold authority.",
                "selectedFeatureSetIds": [],
                "compatibleTransformations": [],
                "finalOotTargetEvidenceUsed": False,
            }
        )
    if len(rows) != 254 or tuple(row["name"] for row in rows[:48]) != tuple(GOLD_FEATURES):
        raise Stage3FeatureEngineeringError(
            "FEATURE_CONTRACT_RECONCILIATION_FAILED",
            "The accepted candidate inventory must reconcile as the immutable Gold-48 prefix plus 206 contextual predictors.",
            status_code=409,
        )
    return rows, {str(row["name"]): row for row in rows}


def _apply_treatment_spec_draft_gates(
    rows: Sequence[dict[str, Any]], database: Database, authority: eda._Authority
) -> dict[str, Any] | None:
    """Apply only fail-closed gates from a combined DRAFT.

    A draft cannot positively authorize a feature or transformation.  Adopted
    Outlier/Missing policies remain the only executable preprocessing refs.
    """

    from .stage3_feature_treatment_spec import (
        Stage3FeatureTreatmentSpecError,
        compile_project_specification,
        current_draft_execution_overlay,
    )

    try:
        # Prior executability is current project authority, not a property that
        # springs into existence only after somebody persists the combined
        # treatment DRAFT.  Resolve it independently first so a missing (or
        # subsequently stale) DRAFT can never leave Wave-2-only or retired raw
        # fields selectable in Feature Engineering.
        compiled = compile_project_specification(database, authority.project_id)
        _apply_current_prior_authority_gates(
            rows,
            compiled.get("priorAuthority"),
        )
        overlay, reference = current_draft_execution_overlay(database, authority)
    except Stage3FeatureTreatmentSpecError as exc:
        raise Stage3FeatureEngineeringError(exc.code, str(exc), status_code=exc.status_code) from exc
    for row in rows:
        resolution = overlay.get(str(row["name"]))
        row["treatmentSpecificationDraft"] = reference
        row["treatmentSpecificationResolution"] = resolution
        if resolution and not resolution["executableSelectable"]:
            row["eligible"] = False
            row["featureState"] = "INACTIVE"
            row["governanceStatus"] = "HELD_CLOSED_BY_TREATMENT_SPEC_DRAFT"
            row["inactiveReason"] = (
                resolution.get("blockedReason")
                or resolution.get("resolution")
                or "The current combined treatment specification draft holds this feature closed."
            )
            row["stateReason"] = row["inactiveReason"]
    return reference


def _prior_gate_reason(binding: Mapping[str, Any]) -> str:
    status = str(binding.get("status") or "")
    if (
        status == "READY_GOVERNED_PRIOR_V2"
        and binding.get("executable") is True
        and binding.get("selectable") is False
    ):
        return "RAW_FEATURE_NONSELECTABLE_WAVE2_DERIVED_OUTPUT_FAMILY_INSPECTABLE_FOR_LATER_ABLATION"
    if status == "BINDING_READY_REQUIRES_WAVE2_ENGINE":
        return "VALIDATED_SUFFICIENT_STATISTIC_BINDING_AWAITS_WAVE2_ESTIMATOR"
    if status == "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION":
        return str(
            binding.get("retirementReason")
            or "SCIENTIFICALLY_RETIRED_PRESERVE_DEFINITION_AND_AUDIT_EVIDENCE"
        )
    return str(
        binding.get("blockedReason")
        or "CURRENT_GOVERNED_PRIOR_AUTHORITY_DOES_NOT_AUTHORIZE_EXECUTION"
    )


def _apply_current_prior_authority_gates(
    rows: Sequence[dict[str, Any]],
    prior_authority: Any,
) -> None:
    """Apply fail-closed prior status directly from the current compiler.

    V1 raw statistics may pass only when the binding remains raw-selectable.
    Wave 2 raw statistics are never themselves selectable, but their registered
    posterior-mean output may pass through the explicit
    GOVERNED_PRIOR_POSTERIOR_MEAN transformation.  The gate is deliberately
    negative-only for every other authority state.
    """

    authority = prior_authority if isinstance(prior_authority, Mapping) else {}
    raw_bindings = authority.get("bindings")
    bindings = raw_bindings if isinstance(raw_bindings, Sequence) else ()
    by_feature = {
        str(binding.get("feature") or ""): binding
        for binding in bindings
        if isinstance(binding, Mapping) and str(binding.get("feature") or "")
    }
    for row in rows:
        binding = by_feature.get(str(row.get("name") or ""))
        if binding is None:
            continue
        status = str(binding.get("status") or "")
        exact_executable = (
            status == "READY_GOVERNED_PRIOR_V1"
            and binding.get("executable") is True
            and binding.get("selectable") is True
        ) or (
            status == "READY_GOVERNED_PRIOR_V2"
            and binding.get("executable") is True
            and binding.get("selectable") is False
            and bool((binding.get("derivedOutputs") or {}).get("posteriorMean"))
        )
        if exact_executable:
            if status == "READY_GOVERNED_PRIOR_V2":
                row["requiresGovernedPriorTransformation"] = True
            continue
        reason = _prior_gate_reason(binding)
        row["eligible"] = False
        row["featureState"] = "INACTIVE"
        row["governanceStatus"] = "HELD_CLOSED_BY_CURRENT_PRIOR_AUTHORITY"
        row["inactiveReason"] = reason
        row["stateReason"] = reason


def _interaction_contracts(selected_features: Sequence[str] = ()) -> list[dict[str, Any]]:
    selected = set(selected_features)
    output: list[dict[str, Any]] = []
    for name in INTERACTION_FEATURES:
        selected_physical = [
            physical
            for physical in (f"batting_{name}", f"fielding_{name}")
            if physical in selected
        ]
        if name == "home_x_rivalry":
            status = "INACTIVE_PENDING_RIVALRY_APPROVAL"
        elif selected_features and not selected_physical:
            status = "EXCLUDED_FROM_FEATURE_SET"
        else:
            status = "MATERIALIZED"
        output.append(
            {
                "name": name,
                "status": status,
                "reason": (
                    "Explicit approved-source interaction, retained as a future chronological-ablation candidate."
                    if status == "MATERIALIZED"
                    else "No physical binding is selected in this immutable feature set."
                    if status == "EXCLUDED_FROM_FEATURE_SET"
                    else "Rivalry-map authority is proposed and not approved."
                ),
                "selectedPhysicalFeatures": selected_physical,
                "mayActivate": status == "MATERIALIZED",
            }
        )
    output.extend(
        {
            "name": name,
            "status": "EXCLUDED_SOURCE_UNAVAILABLE",
            "reason": reason,
            "selectedPhysicalFeatures": [],
            "mayActivate": False,
        }
        for name, reason in EXCLUDED_INTERACTIONS.items()
    )
    if len(output) != 11:
        raise Stage3FeatureEngineeringError(
            "INTERACTION_CONTRACT_RECONCILIATION_FAILED",
            "The contextual authority must expose exactly eleven bounded interaction decisions.",
            status_code=409,
        )
    return output


def _family_summaries(catalog: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for name, features in FUTURE_ABLATION_FAMILIES.items():
        ordered = list(features)
        missingness = [float(catalog[feature]["missingPercentDevelopment"]) for feature in ordered]
        inactive = [feature for feature in ordered if not catalog[feature]["eligible"]]
        interaction_names = sorted(
            {
                interaction
                for feature in ordered
                for interaction in catalog[feature]["interactionMembership"]
            }
        )
        excluded_reasons = [
            {
                "feature": feature,
                "status": catalog[feature]["governanceStatus"],
                "reason": catalog[feature]["inactiveReason"],
            }
            for feature in inactive
        ]
        if name == "G FULL_CONTEXTUAL_CHALLENGER":
            excluded_reasons.extend(
                {
                    "feature": interaction,
                    "status": "EXCLUDED_SOURCE_UNAVAILABLE",
                    "reason": reason,
                }
                for interaction, reason in EXCLUDED_INTERACTIONS.items()
            )
        output.append(
            {
                "name": name,
                "friendlyName": name.split(" ", 1)[1].replace("_", " ").title(),
                "featureCount": len(ordered),
                "coreFeatureCount": sum(1 for feature in ordered if feature in GOLD_FEATURES),
                "contextualFeatureCount": sum(1 for feature in ordered if feature in CONTEXT_FEATURES),
                "eligibleFeatureCount": sum(1 for feature in ordered if catalog[feature]["eligible"]),
                "inactiveFeatureCount": sum(1 for feature in ordered if not catalog[feature]["eligible"]),
                "sourceUnavailableCount": len(EXCLUDED_INTERACTIONS) if name == "G FULL_CONTEXTUAL_CHALLENGER" else 0,
                "physicalMissingness": {
                    "meanDevelopmentPercent": float(np.mean(missingness)) if missingness else None,
                    "status": "EXACT_ACCEPTED_PUBLICATION_COVERAGE",
                },
                "coldStartExposure": {
                    "relevantFeatureCount": sum(
                        catalog[feature]["coldStartRelevance"].startswith("RELEVANT")
                        for feature in ordered
                    ),
                    "rowsDropped": False,
                },
                "pointInTimeStatus": "ACCEPTED_PROJECT_BOUND_POINT_IN_TIME_CONTRACT",
                "forecastTimeStatus": "PREGAME_OR_SIMULATOR_SUPPLIED_AS_DECLARED",
                "interactionCount": len(interaction_names),
                "interactions": interaction_names,
                "transformationCompatibility": "PER_FEATURE_COMPATIBILITY_ENFORCED_FOLD_LOCAL",
                "warnings": [
                    "Feature-family effects are hypotheses for chronological ablation, not selected winners."
                ]
                + (
                    ["Subjective rivalry features remain inactive pending explicit mapping approval."]
                    if "RIVALRY" in name
                    else []
                ),
                "excludedReasons": excluded_reasons,
                "orderedFeatures": ordered,
                "hypothesisOnly": name != "A CORE_GOLD_48",
                "selectionStatus": "FUTURE_CHRONOLOGICAL_ABLATION_CANDIDATE",
                "finalOotUsedForSelection": False,
            }
        )
    if len(output) != 7:
        raise Stage3FeatureEngineeringError(
            "FEATURE_FAMILY_CONTRACT_INCOMPLETE",
            "The accepted contextual authority must expose exactly seven feature-family candidates.",
            status_code=409,
        )
    return output


def _default_steps(meta: Mapping[str, Any]) -> list[str]:
    if meta.get("binary"):
        # The adopted DATA_TYPE_AWARE Missing Policy v2 requires MODE for a
        # physically-missing binary predictor.  Passthrough remains the exact
        # contract for complete binary columns.  This distinction is part of
        # the immutable/content-addressed transformation authority; the model
        # worker must never infer it later from a pandas dtype.
        if float(meta.get("missingPercentDevelopment") or 0.0) > 0.0:
            return ["BINARY_MODE_IMPUTE"]
        return ["BINARY_PASSTHROUGH"]
    if str(meta.get("dataType")) == "categorical":
        return ["CATEGORICAL_UNKNOWN", "ONE_HOT"]
    return ["RETAIN_RAW"]


def _default_transformations(
    ordered_features: Sequence[str], catalog: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "fittingScope": "CHRONOLOGICAL_TRAINING_FOLD_ONLY",
        "fittingRule": FOLD_LOCAL_RULE,
        "finalFitRule": FINAL_FIT_RULE,
        "targetEncoding": "PROHIBITED",
        "globalImputation": "PROHIBITED",
        "ordered": [
            {"feature": name, "steps": _default_steps(catalog[name])}
            for name in ordered_features
        ],
    }


def _recommended_sets(
    catalog: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    descriptions = {
        "A CORE_GOLD_48": "Immutable Gold-48 baseline contract.",
        "B CORE_PLUS_CALENDAR": "Gold-48 plus venue-local calendar and series context.",
        "C CORE_PLUS_REST_TRAVEL": "Gold-48 plus prior-date team rest, density, travel, and trip context.",
        "D CORE_PLUS_CIRCADIAN": "Gold-48 plus transparent body-clock and time-zone proxies.",
        "E CORE_PLUS_DIVISION_RIVALRY": "Gold-48 plus objective league/division/repeat-opponent context; subjective rivalry remains inactive.",
        "F CORE_PLUS_CALENDAR_TRAVEL": "Combined calendar, rest, and travel challenger.",
        "G FULL_CONTEXTUAL_CHALLENGER": "All currently eligible contextual hypotheses; inactive rivalry and unavailable-source interactions remain excluded.",
    }
    stable_ids = {
        "A CORE_GOLD_48": "BASELINE_CORE_48",
        "B CORE_PLUS_CALENDAR": "CORE_PLUS_CALENDAR",
        "C CORE_PLUS_REST_TRAVEL": "CORE_PLUS_REST_TRAVEL",
        "D CORE_PLUS_CIRCADIAN": "CORE_PLUS_CIRCADIAN",
        "E CORE_PLUS_DIVISION_RIVALRY": "CORE_PLUS_DIVISION",
        "F CORE_PLUS_CALENDAR_TRAVEL": "CORE_PLUS_CALENDAR_TRAVEL",
        "G FULL_CONTEXTUAL_CHALLENGER": "FULL_ELIGIBLE_CONTEXTUAL",
    }
    output: list[dict[str, Any]] = []
    for name, values in FUTURE_ABLATION_FAMILIES.items():
        ordered = [feature for feature in values if catalog[feature]["eligible"]]
        excluded = [
            {
                "feature": feature,
                "status": catalog[feature]["governanceStatus"],
                "reason": catalog[feature]["inactiveReason"],
            }
            for feature in values
            if not catalog[feature]["eligible"]
        ]
        output.append(
            {
                "setId": stable_ids[name],
                "name": name,
                "description": descriptions[name],
                "orderedFeatures": ordered,
                "counts": {
                    "total": len(ordered),
                    "core": sum(feature in GOLD_FEATURES for feature in ordered),
                    "contextual": sum(feature in CONTEXT_FEATURES for feature in ordered),
                    "excluded": len(excluded),
                },
                "exclusions": excluded,
                "defaultTransformationContracts": _default_transformations(ordered, catalog),
                "interactionContracts": _interaction_contracts(ordered),
                "selectionAuthority": "DEVELOPMENT_ONLY_FUTURE_ABLATION_CANDIDATE",
                "finalOotUsedForSelection": False,
            }
        )
    baseline = output[0]
    output.append(
        {
            **baseline,
            "setId": "CUSTOM",
            "name": "CUSTOM",
            "description": (
                "User-defined ordered candidate set initialized from the immutable Core Gold 48; "
                "inactive and unavailable fields remain ineligible."
            ),
            "selectionAuthority": "DEVELOPMENT_ONLY_USER_DEFINED_CANDIDATE",
        }
    )
    return output


def _treatment_policy_refs(database: Database, authority: eda._Authority) -> dict[str, Any]:
    repository = Stage3TreatmentRepository(database)
    refs: dict[str, Any] = {}
    for key, kind in (("outlier", "OUTLIER"), ("missing", "IMPUTATION")):
        try:
            state = repository.policy_state(authority.project_id, kind, authority.review_digest)
        except Exception as exc:
            if "no such table" in str(exc).lower():
                refs[key] = None
                continue
            raise
        adopted = state.get("adopted")
        refs[key] = (
            {
                "policyId": adopted.get("policyId"),
                "policyVersion": adopted.get("policyVersion"),
                "checksum": adopted.get("checksum"),
                "status": "ADOPTED",
            }
            if adopted
            else None
        )
    return refs


def _adopted_treatment_rows(database: Database, authority: eda._Authority) -> dict[str, Any]:
    repository = Stage3TreatmentRepository(database)
    rows: dict[str, Any] = {"outlier": None, "missing": None}
    for key, kind in (("outlier", "OUTLIER"), ("missing", "IMPUTATION")):
        try:
            rows[key] = repository.policy_state(
                authority.project_id, kind, authority.review_digest
            ).get("adopted")
        except Exception as exc:
            if "no such table" not in str(exc).lower():
                raise
    return rows


def _enrich_adopted_treatments(
    rows: Sequence[dict[str, Any]], database: Database, authority: eda._Authority
) -> None:
    adopted = _adopted_treatment_rows(database, authority)
    outlier = adopted.get("outlier") or {}
    missing = adopted.get("missing") or {}
    outlier_policy = dict(outlier.get("policy") or {})
    missing_policy = dict(missing.get("policy") or {})
    outlier_overrides = dict(outlier_policy.get("overrides") or {})
    missing_overrides = dict(missing_policy.get("overrides") or {})
    outlier_ref = (
        {
            "policyId": outlier.get("policyId"),
            "policyVersion": outlier.get("policyVersion"),
            "checksum": outlier.get("checksum"),
        }
        if outlier
        else None
    )
    missing_ref = (
        {
            "policyId": missing.get("policyId"),
            "policyVersion": missing.get("policyVersion"),
            "checksum": missing.get("checksum"),
        }
        if missing
        else None
    )
    for row in rows:
        name = str(row["name"])
        outlier_override = dict(outlier_overrides.get(name) or {})
        missing_override = dict(missing_overrides.get(name) or {})
        row["adoptedOutlierTreatment"] = (
            outlier_override.get("treatment")
            or outlier_policy.get("globalTreatment")
            or "NO_TREATMENT_ADOPTED"
        )
        row["adoptedOutlierDetectionMethod"] = (
            outlier_override.get("detectionMethod")
            or outlier.get("globalMethod")
            or "NO_TREATMENT_ADOPTED"
        )
        row["adoptedMissingTreatment"] = (
            missing_override.get("method")
            or missing_override.get("imputationMethod")
            or missing.get("globalMethod")
            or "NO_TREATMENT_ADOPTED"
        )
        row["adoptedOutlierPolicyRef"] = outlier_ref
        row["adoptedMissingPolicyRef"] = missing_ref
        row["adoptedOutlierRule"] = {
            "detectionMethod": row["adoptedOutlierDetectionMethod"],
            "treatment": row["adoptedOutlierTreatment"],
            "override": bool(outlier_override),
        }
        row["adoptedOutlierPrevalencePercent"] = None
        row["adoptedOutlierPrevalenceStatus"] = "NOT_EVALUATED_IN_INVENTORY"
        row["adoptedMissingRule"] = {
            "method": row["adoptedMissingTreatment"],
            "override": bool(missing_override),
        }


def _feature_set_state_data(database: Database, authority: eda._Authority) -> dict[str, Any]:
    try:
        state = Stage3FeatureSetRepository(database).feature_set_state(
            authority.project_id, authority.review_digest
        )
    except Exception as exc:
        if "no such table" in str(exc).lower():
            return {
                "draft": None,
                "registered": None,
                "drafts": [],
                "registeredSets": [],
                "history": [],
                "expectedChecksum": NO_CURRENT_FEATURE_SET,
                "persistenceStatus": "MIGRATION_REQUIRED",
            }
        raise
    return {**state, "persistenceStatus": "READY"}


def feature_studio_summary(project_id: str, database: Database) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    rows, catalog = _catalog(authority)
    treatment_specification_draft = _apply_treatment_spec_draft_gates(
        rows, database, authority
    )
    interaction_authority = (
        treatment_specification_draft.get("interactionAuthority")
        if isinstance(treatment_specification_draft, Mapping)
        else None
    )
    families = _family_summaries(catalog)
    interactions = _interaction_contracts()
    state = _feature_set_state_data(database, authority)
    eligible_contextual = sum(
        row["contextual"] and row["eligible"] for row in rows
    )
    inactive = sum(not row["eligible"] for row in rows)
    interaction_counts = {
        "total": len(interactions),
        "materialized": sum(item["status"] == "MATERIALIZED" for item in interactions),
        "inactivePendingRivalry": sum(
            item["status"] == "INACTIVE_PENDING_RIVALRY_APPROVAL" for item in interactions
        ),
        "sourceUnavailable": sum(
            item["status"] == "EXCLUDED_SOURCE_UNAVAILABLE" for item in interactions
        ),
    }
    summary = {
        "coreFeatureCount": len(GOLD_FEATURES),
        "contextualFeatureCount": len(CONTEXT_FEATURES),
        "totalCandidateCount": len(rows),
        "eligibleContextualCount": eligible_contextual,
        "inactiveFeatureCount": inactive,
        "unavailableFeatureCount": len(EXCLUDED_INTERACTIONS),
        "familyCount": len(families),
        "interactionCounts": interaction_counts,
        "developmentRows": eda.DEVELOPMENT_ROWS,
        "developmentStartDate": eda.DEVELOPMENT_START,
        "developmentEndDate": eda.DEVELOPMENT_END,
        "finalOotRows": eda.FINAL_OOT_ROWS,
        "finalOotStartDate": eda.EXPECTED_FINAL_OOT[0],
        "finalOotEndDate": eda.EXPECTED_FINAL_OOT[1],
        "finalOotLocked": True,
        "selectedCandidateSetCount": len(state.get("registeredSets") or []),
        "rivalryMappingStatus": RIVALRY_AUTHORITY_STATUS,
        "sourceOrGoldMutated": False,
        "modelActivity": {"fits": 0, "scores": 0, "promotions": 0},
    }
    visualizations = [
        {
            "visualizationId": "FEATURE_FAMILY_SIZE_COMPARISON",
            "type": "BAR",
            "developmentOnly": True,
            "rows": [
                {"family": item["name"], "featureCount": item["featureCount"]}
                for item in families
            ],
        },
        {
            "visualizationId": "DEVELOPMENT_VS_OOT_PREDICTOR_COVERAGE",
            "type": "COVERAGE_COMPARISON",
            "predictorMissingnessOnly": True,
            "ootTargetsAccessed": False,
        },
        {
            "visualizationId": "PROJECT_GOLD_FEATURE_LINEAGE",
            "type": "LINEAGE_DIAGRAM",
            "nodes": [
                authority.source_dataset_id,
                authority.dataset_version_id,
                authority.gold_manifest_sha,
                authority.contextual_manifest_sha,
                authority.review_digest,
            ],
        },
        {
            "visualizationId": "FOLD_LOCAL_TRANSFORMATION_FLOW",
            "type": "PROCESS_DIAGRAM",
            "steps": [
                "TRAINING_ROWS_ONLY",
                "FIT_TRANSFORMATION_PARAMETERS",
                "FREEZE_FOLD_PARAMETERS",
                "APPLY_TO_VALIDATION",
            ],
        },
    ]
    return _envelope(
        authority,
        aggregation="FEATURE_STUDIO_AUTHORITY_SUMMARY",
        data={
            "summary": summary,
            "families": families,
            "interactions": interactions,
            "recommendedSets": _recommended_sets(catalog),
            "visualizations": visualizations,
            "treatmentPolicies": _treatment_policy_refs(database, authority),
            "featureSetState": state,
            "treatmentSpecificationDraft": treatment_specification_draft,
            "interactionAuthority": interaction_authority,
        },
    )


def _sequence(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def feature_inventory(
    project_id: str, database: Database, query: Mapping[str, Any] | None
) -> dict[str, Any]:
    payload = dict(query or {})
    _reject_oot_request(payload)
    authority = eda._resolve_authority(database, project_id)
    rows, _ = _catalog(authority)
    _apply_treatment_spec_draft_gates(rows, database, authority)
    _enrich_adopted_treatments(rows, database, authority)
    state = _feature_set_state_data(database, authority)
    for row in rows:
        row["compatibleTransformations"] = _compatible_transformations(row)
        row["selectedFeatureSetIds"] = [
            str(feature_set["featureSetId"])
            for feature_set in state.get("registeredSets") or []
            if row["name"] in (feature_set.get("orderedFeatures") or [])
        ]
    search = str(payload.get("search") or "").strip().lower()
    families = set(_sequence(payload.get("families") or payload.get("featureFamilies")))
    statuses = {item.upper() for item in _sequence(payload.get("statuses"))}
    data_types = {item.lower() for item in _sequence(payload.get("dataTypes"))}
    outlier_treatments = {item.upper() for item in _sequence(payload.get("outlierTreatments"))}
    missing_treatments = {item.upper() for item in _sequence(payload.get("missingTreatments"))}
    if search:
        rows = [
            row
            for row in rows
            if search
            in " ".join(
                str(row.get(key) or "")
                for key in ("name", "label", "definition", "featureFamily", "sourceLineage")
            ).lower()
        ]
    if families:
        logical_families = {
            name.split(" ", 1)[1]: set(features)
            for name, features in FUTURE_ABLATION_FAMILIES.items()
        }
        requested_features: set[str] = set()
        physical_families: set[str] = set()
        for family in families:
            normalized = re.sub(r"^[A-G]\s+", "", family)
            if normalized in logical_families:
                requested_features.update(logical_families[normalized])
            else:
                physical_families.add(family)
        rows = [
            row
            for row in rows
            if str(row["name"]) in requested_features
            or str(row["featureFamily"]) in physical_families
        ]
    if statuses:
        rows = [row for row in rows if str(row["governanceStatus"]).upper() in statuses]
    if data_types:
        rows = [row for row in rows if str(row["dataType"]).lower() in data_types]
    if payload.get("binaryOnly") is True:
        rows = [row for row in rows if row["binary"] is True]
    scope = str(payload.get("scope") or "").upper()
    if scope in {"CORE", "CONTEXTUAL"}:
        rows = [row for row in rows if bool(row[scope.lower()])]
    feature_states = {item.upper() for item in _sequence(payload.get("featureStates"))}
    if feature_states:
        rows = [row for row in rows if str(row["featureState"]).upper() in feature_states]
    forecast_statuses = {
        item.upper() for item in _sequence(payload.get("forecastAvailability"))
    }
    if forecast_statuses:
        rows = [
            row
            for row in rows
            if any(
                token in str(row["forecastTimeAvailability"]).upper()
                for token in forecast_statuses
            )
        ]
    simulation_state = str(payload.get("simulationState") or "").upper()
    if simulation_state in {"YES", "NO"}:
        rows = [
            row
            for row in rows
            if bool(row["simulationGeneratedState"]) is (simulation_state == "YES")
        ]
    point_in_time_state = str(payload.get("pointInTimeState") or "").upper()
    if point_in_time_state in {"SIMULATOR", "PREGAME"}:
        rows = [
            row
            for row in rows
            if bool(row["simulationGeneratedState"])
            is (point_in_time_state == "SIMULATOR")
        ]
    interaction_state = str(payload.get("interaction") or "").upper()
    if interaction_state in {"MEMBER", "NONE"}:
        rows = [
            row
            for row in rows
            if bool(row["interactionMembership"]) is (interaction_state == "MEMBER")
        ]
    source_state = str(payload.get("sourceAvailability") or "").upper()
    if source_state in {"AVAILABLE", "UNAVAILABLE"}:
        rows = [
            row
            for row in rows
            if (row["availabilityStatus"] == "AVAILABLE_IN_EXACT_CONTEXTUAL_GOLD")
            is (source_state == "AVAILABLE")
        ]
    missingness = str(payload.get("missingness") or "").upper()
    if missingness == "COMPLETE":
        rows = [row for row in rows if float(row["missingPercentDevelopment"]) == 0.0]
    elif missingness == "PRESENT":
        rows = [row for row in rows if float(row["missingPercentDevelopment"]) > 0.0]
    elif missingness == "HIGH":
        rows = [row for row in rows if float(row["missingPercentDevelopment"]) >= 20.0]
    outlier_prevalence = str(payload.get("outlierPrevalence") or "").upper()
    if outlier_prevalence == "NOT_EVALUATED":
        rows = [row for row in rows if row["adoptedOutlierPrevalencePercent"] is None]
    governance = {item.upper() for item in _sequence(payload.get("governanceStatuses"))}
    if governance:
        rows = [row for row in rows if str(row["governanceStatus"]).upper() in governance]
    if outlier_treatments:
        rows = [
            row
            for row in rows
            if str(row["adoptedOutlierTreatment"]).upper() in outlier_treatments
        ]
    if missing_treatments:
        rows = [
            row
            for row in rows
            if str(row["adoptedMissingTreatment"]).upper() in missing_treatments
        ]
    eligible = payload.get("eligible")
    if eligible is not None:
        if not isinstance(eligible, bool):
            raise Stage3FeatureEngineeringError(
                "FEATURE_INVENTORY_FILTER_INVALID", "eligible must be boolean."
            )
        rows = [row for row in rows if bool(row["eligible"]) is eligible]
    sort_by = str(payload.get("sortBy") or "order")
    if sort_by not in _INVENTORY_SORT_FIELDS:
        raise Stage3FeatureEngineeringError(
            "FEATURE_INVENTORY_SORT_INVALID", f"Unsupported feature-inventory sort field: {sort_by}."
        )
    direction = str(payload.get("sortDirection") or "asc").lower()
    if direction not in {"asc", "desc"}:
        raise Stage3FeatureEngineeringError(
            "FEATURE_INVENTORY_SORT_INVALID", "sortDirection must be asc or desc."
        )
    rows.sort(
        key=lambda row: (
            row.get(sort_by) is None,
            str(row.get(sort_by)).lower()
            if not isinstance(row.get(sort_by), (int, float))
            else row.get(sort_by),
            int(row["order"]),
        ),
        reverse=direction == "desc",
    )
    try:
        page = int(payload.get("page") or 1)
        page_size = int(payload.get("pageSize") or DEFAULT_PAGE_SIZE)
    except (TypeError, ValueError) as exc:
        raise Stage3FeatureEngineeringError(
            "FEATURE_INVENTORY_PAGE_INVALID", "page and pageSize must be integers."
        ) from exc
    if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise Stage3FeatureEngineeringError(
            "FEATURE_INVENTORY_PAGE_INVALID",
            f"page must be positive and pageSize must be from 1 through {MAX_PAGE_SIZE}.",
        )
    total = len(rows)
    start = (page - 1) * page_size
    data = {
        "rows": rows[start : start + page_size],
        "total": total,
        "page": page,
        "pageSize": page_size,
        "filters": {
            "search": search,
            "families": sorted(families),
            "statuses": sorted(statuses),
            "dataTypes": sorted(data_types),
            "outlierTreatments": sorted(outlier_treatments),
            "missingTreatments": sorted(missing_treatments),
            "eligible": eligible,
            "sortBy": sort_by,
            "sortDirection": direction,
        },
    }
    return _envelope(
        authority,
        aggregation="PAGINATED_FEATURE_CONTRACT_INVENTORY",
        data=data,
    )


def _finite(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _development_summary(frame: pd.DataFrame, feature: Mapping[str, Any]) -> dict[str, Any]:
    name = str(feature["name"])
    series = frame[name]
    missing = int(series.isna().sum())
    total = int(len(series))
    base = {
        "developmentRows": total,
        "observedRows": total - missing,
        "missingRows": missing,
        "missingPercent": float(100.0 * missing / total) if total else 0.0,
        "uniqueObserved": int(series.nunique(dropna=True)),
        "finalOotTargetsAccessed": False,
    }
    if str(feature.get("dataType")) == "numeric":
        numeric = pd.to_numeric(series, errors="coerce").astype(float)
        numeric = numeric.where(np.isfinite(numeric), np.nan).dropna()
        if numeric.empty:
            return {**base, "distributionType": "NUMERIC", "statistics": {}}
        return {
            **base,
            "distributionType": "NUMERIC",
            "statistics": {
                "min": _finite(numeric.min()),
                "q1": _finite(numeric.quantile(0.25)),
                "median": _finite(numeric.median()),
                "q3": _finite(numeric.quantile(0.75)),
                "max": _finite(numeric.max()),
                "mean": _finite(numeric.mean()),
                "standardDeviation": _finite(numeric.std(ddof=0)),
            },
        }
    counts = series.fillna("MISSING").astype(str).value_counts(dropna=False).head(50)
    return {
        **base,
        "distributionType": "CATEGORICAL",
        "topValues": [
            {
                "value": str(value),
                "count": int(count),
                "percent": float(100.0 * count / total) if total else 0.0,
            }
            for value, count in counts.items()
        ],
        "topValuesBounded": True,
    }


def feature_detail(project_id: str, database: Database, feature_name: str) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    rows, catalog = _catalog(authority)
    _apply_treatment_spec_draft_gates(rows, database, authority)
    feature = catalog.get(feature_name)
    if not feature:
        raise Stage3FeatureEngineeringError(
            "FEATURE_UNKNOWN", f"Unknown candidate feature: {feature_name}.", status_code=404
        )
    _enrich_adopted_treatments([feature], database, authority)
    try:
        frame = eda._scan(authority, [feature_name, "season", "game_date"], {})
    except eda.Stage3EdaError as exc:
        raise Stage3FeatureEngineeringError(exc.code, str(exc), status_code=exc.status_code) from exc
    by_season = []
    if "season" in frame:
        for season, group in frame.groupby("season", dropna=False, sort=True):
            missing = int(group[feature_name].isna().sum())
            by_season.append(
                {
                    "season": int(season) if pd.notna(season) else None,
                    "rows": int(len(group)),
                    "missingRows": missing,
                    "missingPercent": float(100.0 * missing / len(group)) if len(group) else 0.0,
                }
            )
    linked_indicators = [
        name
        for name in catalog
        if name.endswith(("_missing", "_insufficient"))
        and (
            _raw_name(feature_name).split("_")[0] in _raw_name(name)
            or _raw_name(feature_name) in _raw_name(name)
        )
    ][:12]
    by_month = []
    if "game_date" in frame:
        dates = pd.to_datetime(frame["game_date"], errors="coerce")
        month_frame = pd.DataFrame(
            {"month": dates.dt.strftime("%Y-%m"), "value": frame[feature_name]}
        ).dropna(subset=["month"])
        for month, group in month_frame.groupby("month", sort=True):
            missing = int(group["value"].isna().sum())
            by_month.append(
                {
                    "month": str(month),
                    "rows": int(len(group)),
                    "missingRows": missing,
                    "missingPercent": float(100.0 * missing / len(group)) if len(group) else 0.0,
                }
            )
    refs = _treatment_policy_refs(database, authority)
    outlier_overrides: Mapping[str, Any] = {}
    missing_overrides: Mapping[str, Any] = {}
    try:
        repository = Stage3TreatmentRepository(database)
        outlier_state = repository.policy_state(authority.project_id, "OUTLIER", authority.review_digest)
        missing_state = repository.policy_state(authority.project_id, "IMPUTATION", authority.review_digest)
        outlier_overrides = dict(((outlier_state.get("adopted") or {}).get("policy") or {}).get("overrides") or {})
        missing_overrides = dict(((missing_state.get("adopted") or {}).get("policy") or {}).get("overrides") or {})
    except Exception as exc:
        if "no such table" not in str(exc).lower():
            raise
    data = {
        "feature": feature,
        "developmentSummary": _development_summary(frame, feature),
        "missingnessBySeason": by_season,
        "missingnessByMonth": by_month,
        "linkedMissingnessIndicators": linked_indicators,
        "treatmentPolicies": refs,
        "featureTreatmentOverrides": {
            "outlier": outlier_overrides.get(feature_name),
            "missing": missing_overrides.get(feature_name),
        },
        "compatibleTransformations": _compatible_transformations(feature),
        "developmentOnlyTargetComparison": {
            "status": "NOT_EVALUATED",
            "reason": "No target column is materialized by this feature-detail endpoint; use the existing bounded development-only EDA relationship queries when requested.",
            "finalOotTargetsAccessed": False,
        },
        "temporalStability": {
            "status": "DESCRIPTIVE_MISSINGNESS_ONLY",
            "bySeason": by_season,
            "byMonth": by_month,
            "outcomeEvidenceUsed": False,
        },
        "redundancyAssessment": {
            "status": "NOT_EVALUATED",
            "reason": "Pairwise redundancy requires an explicit bounded development-only relationship query.",
            "finalOotTargetsAccessed": False,
        },
        "foldLocalRule": FOLD_LOCAL_RULE,
        "finalFitRule": FINAL_FIT_RULE,
        "finalOotPredictorCoverage": {
            "coverage": feature["coverageFinalOot"],
            "missingPercent": feature["missingPercentFinalOot"],
            "predictorOnly": True,
            "targetCountsAvailable": False,
            "targetDistributionAvailable": False,
        },
    }
    return _envelope(
        authority,
        aggregation="DEVELOPMENT_ONLY_FEATURE_DETAIL",
        rows=len(frame),
        data=data,
    )


def _compatible_transformations(feature: Mapping[str, Any]) -> list[str]:
    common = [
        "NONE",
        "RETAIN_RAW",
        "MISSING_INDICATOR",
        "ADOPTED_OUTLIER_POLICY",
        "ADOPTED_MISSING_POLICY",
    ]
    if feature.get("binary"):
        return ["NONE", "BINARY_PASSTHROUGH", "MISSING_INDICATOR", "ADOPTED_MISSING_POLICY"]
    if str(feature.get("dataType")) == "categorical":
        return ["NONE", "CATEGORICAL_UNKNOWN", "ONE_HOT", "MISSING_INDICATOR", "ADOPTED_MISSING_POLICY"]
    return [*common, "LOG1P", "STANDARDIZE", "ROBUST_SCALE", "QUANTILE_TRANSFORM", "BOUNDED_TRANSFORM"]


def feature_set_state(project_id: str, database: Database) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    return _envelope(
        authority,
        aggregation="IMMUTABLE_FEATURE_SET_HISTORY",
        data=_feature_set_state_data(database, authority),
    )


def _assert_authority(authority: eda._Authority, payload: Mapping[str, Any]) -> None:
    try:
        treatments._assert_authority_key(authority, payload)
    except treatments.Stage3TreatmentError as exc:
        raise Stage3FeatureEngineeringError(exc.code, str(exc), status_code=exc.status_code) from exc


def _normalize_transformations(
    payload: Any,
    ordered_features: Sequence[str],
    catalog: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    requested: dict[str, Any] = {}
    default_numeric = "RETAIN_RAW"
    if payload is None:
        requested = {}
    elif not isinstance(payload, Mapping):
        raise Stage3FeatureEngineeringError(
            "TRANSFORMATION_CONTRACT_INVALID", "transformationContracts must be an object."
        )
    elif isinstance(payload.get("ordered"), list):
        for item in payload["ordered"]:
            if not isinstance(item, Mapping) or not str(item.get("feature") or ""):
                raise Stage3FeatureEngineeringError(
                    "TRANSFORMATION_CONTRACT_INVALID", "Every ordered transformation contract requires a feature."
                )
            requested[str(item["feature"])] = item.get("steps")
    else:
        default_numeric = _TRANSFORM_ALIASES.get(
            str(payload.get("defaultNumeric") or "RETAIN_RAW").strip().upper(),
            str(payload.get("defaultNumeric") or "RETAIN_RAW").strip().upper(),
        )
        if default_numeric not in ({"NONE", "RETAIN_RAW"} | _NUMERIC_ONLY):
            raise Stage3FeatureEngineeringError(
                "TRANSFORMATION_DEFAULT_INVALID",
                "defaultNumeric must be a compatible numeric transformation rule.",
            )
        requested = {
            str(name): value
            for name, value in payload.items()
            if name not in {
                "defaultNumeric",
                "fittingScope",
                "fittingRule",
                "finalFitRule",
                "targetEncoding",
                "globalImputation",
            }
        }
    selected = set(ordered_features)
    unknown = sorted(set(requested) - selected)
    if unknown:
        raise Stage3FeatureEngineeringError(
            "TRANSFORMATION_FEATURE_NOT_SELECTED",
            f"Transformation contracts reference unselected features: {', '.join(unknown)}.",
        )
    output: list[dict[str, Any]] = []
    for name in ordered_features:
        meta = catalog[name]
        default_steps = (
            [default_numeric]
            if str(meta.get("dataType")) == "numeric" and not meta.get("binary")
            else _default_steps(meta)
        )
        raw_steps = requested.get(name, default_steps)
        if isinstance(raw_steps, Mapping):
            raw_steps = raw_steps.get("steps") or raw_steps.get("method")
        values = raw_steps if isinstance(raw_steps, list) else [raw_steps]
        steps = [
            _TRANSFORM_ALIASES.get(str(value or "").strip().upper(), str(value or "").strip().upper())
            for value in values
            if str(value or "").strip()
        ]
        if not steps:
            steps = ["NONE"]
        unsupported = sorted(set(steps) - _SUPPORTED_TRANSFORMATIONS)
        if unsupported:
            raise Stage3FeatureEngineeringError(
                "TRANSFORMATION_METHOD_UNSUPPORTED",
                f"Unsupported transformation methods for {name}: {', '.join(unsupported)}.",
            )
        if set(steps) & _NUMERIC_ONLY and str(meta.get("dataType")) != "numeric":
            raise Stage3FeatureEngineeringError(
                "TRANSFORMATION_TYPE_INCOMPATIBLE",
                f"Numeric transformations are not compatible with categorical feature {name}.",
            )
        if set(steps) & _CATEGORICAL_ONLY and str(meta.get("dataType")) != "categorical":
            raise Stage3FeatureEngineeringError(
                "TRANSFORMATION_TYPE_INCOMPATIBLE",
                f"Categorical transformations are not compatible with numeric feature {name}.",
            )
        if (
            {"BINARY_PASSTHROUGH", "BINARY_MODE_IMPUTE"} & set(steps)
            and not meta.get("binary")
        ):
            raise Stage3FeatureEngineeringError(
                "TRANSFORMATION_TYPE_INCOMPATIBLE",
                f"Binary treatment is not compatible with nonbinary feature {name}.",
            )
        if "ONE_HOT" in steps and "CATEGORICAL_UNKNOWN" not in steps:
            raise Stage3FeatureEngineeringError(
                "CATEGORICAL_UNKNOWN_REQUIRED",
                f"ONE_HOT for {name} must preserve an explicit unknown-category treatment.",
            )
        output.append({"feature": name, "steps": steps})
    return {
        "fittingScope": "CHRONOLOGICAL_TRAINING_FOLD_ONLY",
        "fittingRule": FOLD_LOCAL_RULE,
        "finalFitRule": FINAL_FIT_RULE,
        "targetEncoding": "PROHIBITED",
        "globalImputation": "PROHIBITED",
        "ordered": output,
    }


def _corrected_registration_contract(
    database: Database,
    authority: eda._Authority,
    payload: Any,
    ordered_features: Sequence[str],
    catalog: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Authorize expanded outputs only from the exact adopted successor.

    The legacy catalog remains the immutable physical source inventory.
    Virtual prior outputs enter a corrected set only through this complete,
    content-addressed model schema; arbitrary extra columns are never allowed.
    """
    if not isinstance(payload, Mapping) or not payload.get("semanticTreatmentVersion"):
        return None
    from . import stage3_corrected_treatment_spec as corrected

    if payload.get("semanticTreatmentVersion") != corrected.SEMANTIC_TREATMENT_VERSION:
        raise Stage3FeatureEngineeringError("SEMANTIC_TREATMENT_VERSION_UNSUPPORTED", "Unknown corrected treatment marker.")
    adopted = Stage3TreatmentRepository(database).combined_spec_state(
        authority.project_id, authority.review_digest
    ).get("adopted")
    manifest = (adopted or {}).get("manifest") or {}
    if (
        manifest.get("semanticTreatmentVersion") != corrected.SEMANTIC_TREATMENT_VERSION
        or corrected.content_sha(manifest) != (adopted or {}).get("manifestChecksum")
    ):
        raise Stage3FeatureEngineeringError(
            "CORRECTED_TREATMENT_ADOPTION_REQUIRED", "The exact corrected treatment must be adopted before its feature schema is registered.", status_code=409
        )
    schema = manifest["modelFeatureSchema"]
    expected = corrected.corrected_transformation_contracts({
        **manifest, "manifestChecksum": adopted["manifestChecksum"]
    })
    if list(ordered_features) != schema["orderedFeatures"] or dict(payload) != expected:
        raise Stage3FeatureEngineeringError(
            "CORRECTED_FEATURE_SCHEMA_MISMATCH", "The corrected set must bind the exact adopted 273-column schema and transformation contract.", status_code=409
        )
    for column in schema["columns"]:
        name = str(column["feature"])
        if name in catalog:
            if name not in schema["sourceOrderedFeatures"]:
                raise Stage3FeatureEngineeringError("CORRECTED_SOURCE_PREFIX_INVALID", "A corrected source column is not authorized.")
            continue
        parent = catalog.get(str(column["sourceFeature"]))
        if parent is None or column["sourceFeature"] not in schema["wave1SourceFeatures"]:
            raise Stage3FeatureEngineeringError("CORRECTED_DERIVED_PARENT_INVALID", "A derived output lacks its exact eligible Wave 1 parent.")
        catalog[name] = {
            **parent,
            "name": name,
            "label": name,
            "dataType": column["dataType"],
            "binary": bool(column["binary"]),
            "eligible": True,
            "governanceStatus": "ELIGIBLE_ADOPTED_CORRECTED_OUTPUT",
            "featureState": "ACTIVE",
            "derivedFromFeature": column["sourceFeature"],
            "derivedRole": column["role"],
            "requiresGovernedPriorTransformation": False,
        }
    return expected


def _validate_draft(
    authority: eda._Authority,
    database: Database,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    _reject_oot_request(payload)
    _assert_authority(authority, payload)
    rows, catalog = _catalog(authority)
    _apply_treatment_spec_draft_gates(rows, database, authority)
    recommended = {item["setId"]: item for item in _recommended_sets(catalog)}
    recommended_id = str(payload.get("recommendedSetId") or "").strip()
    selected_template = recommended.get(recommended_id)
    ordered = payload.get("orderedFeatures")
    if ordered is None and selected_template:
        ordered = selected_template["orderedFeatures"]
    if not isinstance(ordered, list) or not ordered:
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_EMPTY", "A candidate feature set requires an orderedFeatures list."
        )
    ordered_features = [str(name).strip() for name in ordered if str(name).strip()]
    if len(ordered_features) != len(ordered) or len(set(ordered_features)) != len(ordered_features):
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_ORDER_INVALID", "orderedFeatures must be nonempty and contain no duplicates."
        )
    corrected_contract = _corrected_registration_contract(
        database, authority, payload.get("transformationContracts"), ordered_features, catalog
    )
    unknown = [name for name in ordered_features if name not in catalog]
    if unknown:
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_UNKNOWN_FEATURE", f"Unknown candidate features: {', '.join(sorted(unknown))}."
        )
    ineligible = [name for name in ordered_features if not catalog[name]["eligible"]]
    if ineligible:
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_INACTIVE_FEATURE",
            "Ineligible features cannot enter a feature set without explicit governed approval: "
            + ", ".join(sorted(ineligible)),
            status_code=409,
        )
    key = str(payload.get("featureSetKey") or "PROJECT_CANDIDATE_FEATURE_SET").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", key):
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_KEY_INVALID", "featureSetKey must be a stable 1-128 character identifier."
        )
    name = str(payload.get("name") or (selected_template or {}).get("name") or key).strip()
    if not name or len(name) > 200:
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_NAME_INVALID", "Feature-set name must contain 1 through 200 characters."
        )
    transformations = corrected_contract or _normalize_transformations(
        payload.get("transformationContracts"), ordered_features, catalog
    )
    steps_by_feature = {
        str(item["feature"]): tuple(item.get("steps") or ())
        for item in transformations["ordered"]
    }
    missing_governed_transform = sorted(
        name
        for name in ordered_features
        if catalog[name].get("requiresGovernedPriorTransformation") is True
        and steps_by_feature.get(name) != ("GOVERNED_PRIOR_POSTERIOR_MEAN",)
    )
    if missing_governed_transform and corrected_contract is None:
        raise Stage3FeatureEngineeringError(
            "GOVERNED_PRIOR_TRANSFORMATION_REQUIRED",
            "Wave 2 raw statistics are nonselectable; their registered posterior-mean transformation is required for: "
            + ", ".join(missing_governed_transform),
            status_code=409,
        )
    family_memberships = [
        family_name
        for family_name, family_features in FUTURE_ABLATION_FAMILIES.items()
        if tuple(ordered_features) == tuple(
            feature for feature in family_features if catalog[feature]["eligible"]
        )
    ]
    return {
        "featureSetKey": key,
        "name": name,
        "description": str(payload.get("description") or (selected_template or {}).get("description") or "").strip(),
        "notes": str(payload.get("notes") or "").strip(),
        "orderedFeatures": ordered_features,
        "familyMemberships": family_memberships,
        "transformationContracts": transformations,
        "interactionContracts": _interaction_contracts(ordered_features),
        "unavailableExclusions": list((selected_template or {}).get("exclusions") or []),
        "treatmentPolicies": _treatment_policy_refs(database, authority),
        "expectedChecksum": str(payload.get("expectedChecksum") or ""),
    }


def _mutation_envelope(
    authority: eda._Authority,
    *,
    feature_set: Mapping[str, Any],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "ok": True,
        "schemaVersion": FEATURE_STUDIO_SCHEMA_VERSION,
        "authority": _authority_payload(authority),
        "population": _population(aggregation="IMMUTABLE_FEATURE_SET_MUTATION"),
        "audit": _audit(),
        "data": {"featureSet": dict(feature_set), "state": dict(state)},
    }


def save_feature_set_draft(
    project_id: str,
    database: Database,
    payload: Mapping[str, Any],
    actor_user_id: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_REQUEST_INVALID", "The request body must be an object."
        )
    authority = eda._resolve_authority(database, project_id)
    normalized = _validate_draft(authority, database, payload)
    try:
        feature_set = Stage3FeatureSetRepository(database).save_draft(
            authority=_persistence_authority(authority),
            feature_set_key=normalized["featureSetKey"],
            feature_set_name=normalized["name"],
            ordered_features=normalized["orderedFeatures"],
            family_memberships=normalized["familyMemberships"],
            transformation_contracts=normalized["transformationContracts"],
            interaction_contracts=normalized["interactionContracts"],
            unavailable_exclusions=normalized["unavailableExclusions"],
            treatment_policies=normalized["treatmentPolicies"],
            description=normalized["description"],
            notes=normalized["notes"],
            expected_checksum=normalized["expectedChecksum"],
            actor_user_id=actor_user_id,
        )
    except Stage3FeatureSetPersistenceError as exc:
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_CONCURRENT_MODIFICATION", str(exc), status_code=409
        ) from exc
    return _mutation_envelope(
        authority,
        feature_set=feature_set,
        state=_feature_set_state_data(database, authority),
    )


def register_feature_set(
    project_id: str,
    database: Database,
    payload: Mapping[str, Any],
    actor_user_id: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_REQUEST_INVALID", "The request body must be an object."
        )
    authority = eda._resolve_authority(database, project_id)
    _reject_oot_request(payload)
    _assert_authority(authority, payload)
    combined_state = Stage3TreatmentRepository(database).combined_spec_state(
        authority.project_id, authority.review_digest
    )
    combined_history = list(combined_state.get("history") or [])
    if combined_history and combined_history[0].get("status") == "DRAFT":
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_TREATMENT_SPEC_DRAFT_PENDING",
            "Adopt or explicitly resolve the newest combined treatment specification before feature-set registration.",
            status_code=409,
        )
    draft_id = str(payload.get("draftFeatureSetId") or payload.get("featureSetId") or "").strip()
    checksum = str(payload.get("expectedChecksum") or "").strip()
    if not draft_id:
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_DRAFT_REQUIRED", "The exact immutable draftFeatureSetId is required."
        )
    repository = Stage3FeatureSetRepository(database)
    state = repository.feature_set_state(authority.project_id, authority.review_digest)
    draft = next(
        (row for row in state.get("drafts") or [] if row.get("featureSetId") == draft_id),
        None,
    )
    if not draft:
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_DRAFT_NOT_CURRENT", "The requested draft is not a current authority-bound draft.", status_code=409
        )
    # Re-resolve current prior authority against the stored immutable contents.
    # A draft may predate Wave 1 (or any later authority change), so validating
    # only when it was first saved would allow an obsolete selectable state to
    # cross the registration boundary.
    rows, catalog = _catalog(authority)
    try:
        from .stage3_feature_treatment_spec import (
            Stage3FeatureTreatmentSpecError,
            compile_project_specification,
        )

        compiled = compile_project_specification(database, authority.project_id)
        _apply_current_prior_authority_gates(
            rows,
            compiled.get("priorAuthority"),
        )
    except Stage3FeatureTreatmentSpecError as exc:
        raise Stage3FeatureEngineeringError(
            exc.code, str(exc), status_code=exc.status_code
        ) from exc
    stored_features = [str(name) for name in draft.get("orderedFeatures") or []]
    corrected_contract = _corrected_registration_contract(
        database, authority, draft.get("transformationContracts"), stored_features, catalog
    )
    unknown = [name for name in stored_features if name not in catalog]
    if unknown:
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_UNKNOWN_FEATURE",
            "The stored draft contains features absent from the current authority: "
            + ", ".join(sorted(unknown)),
            status_code=409,
        )
    ineligible = [name for name in stored_features if not catalog[name]["eligible"]]
    if ineligible:
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_INACTIVE_FEATURE",
            "The stored draft contains features that current governed authority "
            "holds nonselectable: "
            + ", ".join(sorted(ineligible)),
            status_code=409,
        )
    stored_steps = {
        str(item.get("feature") or ""): tuple(item.get("steps") or ())
        for item in (draft.get("transformationContracts") or {}).get("ordered") or []
        if isinstance(item, Mapping)
    }
    invalid_wave2 = sorted(
        name
        for name in stored_features
        if catalog[name].get("requiresGovernedPriorTransformation") is True
        and stored_steps.get(name) != ("GOVERNED_PRIOR_POSTERIOR_MEAN",)
    )
    if invalid_wave2 and corrected_contract is None:
        raise Stage3FeatureEngineeringError(
            "GOVERNED_PRIOR_TRANSFORMATION_REQUIRED",
            "The immutable draft does not bind the required Wave 2 posterior-mean transformation for: "
            + ", ".join(invalid_wave2),
            status_code=409,
        )
    current_refs = _treatment_policy_refs(database, authority)
    stored_refs = draft.get("treatmentPolicies") or {}
    if not current_refs.get("outlier") or not current_refs.get("missing"):
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_TREATMENT_AUTHORITY_REQUIRED",
            "Both Outlier and Missing Value policies must be adopted before feature-set registration.",
            status_code=409,
        )
    if stored_refs != current_refs:
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_TREATMENT_AUTHORITY_STALE",
            "An adopted treatment policy changed after this draft was saved; review and save a new draft.",
            status_code=409,
        )
    try:
        feature_set = repository.register(
            project_id=authority.project_id,
            authority_review_digest=authority.review_digest,
            draft_feature_set_id=draft_id,
            expected_checksum=checksum,
            actor_user_id=actor_user_id,
        )
    except Stage3FeatureSetPersistenceError as exc:
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_REGISTRATION_CONFLICT", str(exc), status_code=409
        ) from exc
    return _mutation_envelope(
        authority,
        feature_set=feature_set,
        state=_feature_set_state_data(database, authority),
    )


def retire_feature_set(
    project_id: str,
    database: Database,
    payload: Mapping[str, Any],
    actor_user_id: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_REQUEST_INVALID", "The request body must be an object."
        )
    authority = eda._resolve_authority(database, project_id)
    _assert_authority(authority, payload)
    feature_set_id = str(payload.get("registeredFeatureSetId") or payload.get("featureSetId") or "").strip()
    checksum = str(payload.get("expectedChecksum") or "").strip()
    if not feature_set_id:
        raise Stage3FeatureEngineeringError(
            "REGISTERED_FEATURE_SET_REQUIRED", "The exact registeredFeatureSetId is required."
        )
    try:
        feature_set = Stage3FeatureSetRepository(database).retire(
            project_id=authority.project_id,
            authority_review_digest=authority.review_digest,
            registered_feature_set_id=feature_set_id,
            expected_checksum=checksum,
            actor_user_id=actor_user_id,
        )
    except Stage3FeatureSetPersistenceError as exc:
        raise Stage3FeatureEngineeringError(
            "FEATURE_SET_RETIREMENT_CONFLICT", str(exc), status_code=409
        ) from exc
    return _mutation_envelope(
        authority,
        feature_set=feature_set,
        state=_feature_set_state_data(database, authority),
    )


__all__ = [
    "FEATURE_STUDIO_SCHEMA_VERSION",
    "Stage3FeatureEngineeringError",
    "feature_studio_summary",
    "feature_inventory",
    "feature_detail",
    "feature_set_state",
    "save_feature_set_draft",
    "register_feature_set",
    "retire_feature_set",
]
