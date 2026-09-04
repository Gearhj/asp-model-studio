"""Governed fold-local recomputation of the eight reviewed MLB interactions.

This module is intentionally target-free and model-free.  It registers the
literal formulas already implemented by ``contextual_features.py`` and makes
their use after parent treatment executable and content addressed.  The
registry is explicit: a feature is never admitted because its name happens to
contain ``_x_``.

The caller supplies one project-bound authority manifest and one chronological
training cutoff per fold.  Only the training slice is read while learning
dense-family parent medians or optional downstream scaling.  Transform rejects
rows beyond the development boundary before it reads any feature value.
"""
from __future__ import annotations

import copy
import hashlib
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from ..sports_datasets.consumer import canonical_json_bytes


AUTHORITY_NAME: Final = "MLB_INTERACTION_RECOMPUTATION_AUTHORITY_V1"
SCHEMA_VERSION: Final = "MLB_INTERACTION_RECOMPUTATION_AUTHORITY_SCHEMA_V1"
FITTED_SCHEMA_VERSION: Final = "MLB_INTERACTION_RECOMPUTATION_FITTED_V1"
PREPROCESSOR_SCHEMA_VERSION: Final = "MLB_INTERACTION_PREPROCESSOR_BINDING_V1"
CONTEXT_FEATURE_VERSION: Final = "MLB_TEAM_GAME_CONTEXT_FEATURES_V1"
DEVELOPMENT_START: Final = "2023-03-30"
DEVELOPMENT_END: Final = "2026-08-13"
FINAL_OOT_START: Final = "2026-08-14"
FINAL_OOT_END: Final = "2026-08-27"
DEVELOPMENT_ROWS: Final = 683_662
FINAL_OOT_ROWS: Final = 14_067
HISTORY_CUTOFF: Final = "source.game_date < target.game_date (same-date excluded)"
LONG_TRAVEL_MILES: Final = 1_500.0
INTEGER_TOLERANCE: Final = 1e-9

OPERATION_ORDER: Final = (
    "RESOLVE_SOURCE_IDENTITY_AND_POINT_IN_TIME_ELIGIBILITY",
    "VALIDATE_PARENT_HARD_SEMANTIC_DOMAINS",
    "APPLY_FROZEN_TRAINING_FOLD_PARENT_MISSING_TREATMENT",
    "APPLY_PARENT_PRIOR_OR_STRUCTURAL_ZERO_RULE",
    "RECOMPUTE_REGISTERED_INTERACTION_DETERMINISTICALLY",
    "VALIDATE_DERIVED_INTERACTION_DOMAIN",
    "APPLY_MODEL_FAMILY_ENCODING_OR_TRAINING_ONLY_SCALING",
)

MODEL_FAMILY_RESOLUTION: Final[Mapping[str, Mapping[str, Any]]] = {
    "TREE": {
        "parentMissing": "NATIVE_MISSING_WITH_REGISTERED_REASON_STATE",
        "semanticInteraction": "RAW_RECOMPUTED_VALUE",
        "downstreamScaling": "NONE_TREE_NATIVE",
    },
    "LINEAR": {
        "parentMissing": "TRAINING_FOLD_CONTEXTUAL_MEDIAN_WITH_REASON_STATE",
        "semanticInteraction": "RAW_RECOMPUTED_VALUE",
        "downstreamScaling": "OPTIONAL_STANDARD_SCALING_FIT_ON_TRAINING_ROWS_ONLY",
    },
    "NEURAL_OR_DISTANCE": {
        "parentMissing": "TRAINING_FOLD_CONTEXTUAL_MEDIAN_WITH_REASON_STATE",
        "semanticInteraction": "RAW_RECOMPUTED_VALUE",
        "downstreamScaling": "OPTIONAL_STANDARD_SCALING_FIT_ON_TRAINING_ROWS_ONLY",
    },
}

SOURCE_REASON_VALUES: Final = frozenset(
    {
        "SOURCE_UNAVAILABLE",
        "SOURCE_MISSING",
        "SOURCE_NOT_AVAILABLE_FOR_ERA",
        "IDENTITY_FAILURE",
    }
)
COMPUTATION_REASON_VALUES: Final = frozenset(
    {"COMPUTATION_FAILURE", "DOMAIN_FAILURE", "INVALID_VALUE"}
)


class InteractionAuthorityError(RuntimeError):
    """An authority, fit, or transform contract failed closed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _parent(
    feature: str,
    *,
    data_type: str,
    semantic_domain: str,
    domain_kind: str,
    missing_disposition: str,
    missing_policy: str,
    outlier_policy: str,
    paired_indicator: str | None,
    source_failure_indicators: Sequence[str] = (),
    source_failure_indicators_unless_no_history: Sequence[str] = (),
) -> dict[str, Any]:
    content = {
        "feature": feature,
        "backendFeatureIdentity": feature,
        "dataType": data_type,
        "semanticDomain": semantic_domain,
        "domainKind": domain_kind,
        "missingDisposition": missing_disposition,
        "missingPolicy": missing_policy,
        "outlierPolicy": outlier_policy,
        "pairedMissingnessIndicator": paired_indicator,
        "sourceFailureIndicators": list(source_failure_indicators),
        "sourceFailureIndicatorsUnlessNoHistory": list(
            source_failure_indicators_unless_no_history
        ),
        "sourceStatus": "AVAILABLE_IN_EXACT_CONTEXTUAL_GOLD",
        "sourceLineage": (
            "exact team-game schedule/venue authority plus strictly prior-date "
            "completed-game context"
        ),
        "pointInTimeStatus": "PASS",
        "historyCutoff": HISTORY_CUTOFF,
        "forecastTimeAvailability": "PREGAME_OR_STRICTLY_PRIOR_DATE_EVIDENCE",
    }
    checksum = _sha256(content)
    return {
        **content,
        "parentTreatmentAuthority": (
            f"MLB_FEATURE_TREATMENT_PARENT_V1:{feature}:sha256:{checksum}"
        ),
        "parentTreatmentChecksum": checksum,
    }


def _parent_set(side: str) -> dict[str, dict[str, Any]]:
    previous_missing = f"{side}_previous_game_missing"
    return {
        "road": _parent(
            f"{side}_road_trip_game_number",
            data_type="numeric",
            semantic_domain="nonnegative integer",
            domain_kind="NONNEGATIVE_INTEGER",
            missing_disposition="NO_MISSING_TREATMENT",
            missing_policy="REQUIRED_VALUE_FAIL_CLOSED_IF_ABSENT",
            outlier_policy="DISCRETE_SCHEDULE_DOMAIN_VALIDATION_NO_IQR_CAPPING",
            paired_indicator=None,
        ),
        "travel": _parent(
            f"{side}_travel_distance_miles",
            data_type="numeric",
            semantic_domain=">=0 miles reconciled to registered venue coordinates",
            domain_kind="NONNEGATIVE_FINITE",
            missing_disposition="NO_PRIOR_GAME_STATE_PLUS_FOLD_LOCAL_FILL",
            missing_policy=(
                "TREE_NATIVE_MISSING_OR_DENSE_TRAINING_FOLD_CONTEXTUAL_MEDIAN; "
                "NEVER_ZERO_FOR_UNKNOWN_DISTANCE"
            ),
            outlier_policy="RETAIN_LEGITIMATE_EXTREMES_NO_GENERIC_IQR_CAPPING",
            paired_indicator=previous_missing,
            source_failure_indicators=(
                f"{side}_current_venue_coordinates_missing",
            ),
            source_failure_indicators_unless_no_history=(
                f"{side}_previous_venue_coordinates_missing",
                f"{side}_travel_path_missing",
            ),
        ),
        "extra": _parent(
            f"{side}_previous_game_extra_innings",
            data_type="numeric",
            semantic_domain="{0,1} registered Boolean encoding",
            domain_kind="BOOLEAN",
            missing_disposition="STRUCTURAL_ZERO_PLUS_INDICATOR",
            missing_policy=(
                "ZERO_ONLY_FOR_TRUE_NO_PRIOR_HISTORY_WITH_PAIRED_INDICATOR; "
                "UNKNOWN_FAILS_CLOSED"
            ),
            outlier_policy="HARD_BOOLEAN_DOMAIN_VALIDATION_NO_CAPPING",
            paired_indicator=previous_missing,
            source_failure_indicators_unless_no_history=(
                f"{side}_previous_game_innings_missing",
            ),
        ),
        "short": _parent(
            f"{side}_short_rest_indicator",
            data_type="categorical",
            semantic_domain="{0,1} registered Boolean encoding",
            domain_kind="BOOLEAN",
            missing_disposition="NO_MISSING_TREATMENT",
            missing_policy="REQUIRED_BOOLEAN_UNKNOWN_MUST_NOT_BECOME_FALSE",
            outlier_policy="HARD_BOOLEAN_DOMAIN_VALIDATION_NO_CAPPING",
            paired_indicator=previous_missing,
        ),
        "east": _parent(
            f"{side}_eastward_time_zone_change_hours",
            data_type="numeric",
            semantic_domain="[0,12] eastward registered venue-time-zone hours",
            domain_kind="EASTWARD_HOURS",
            missing_disposition="NO_PRIOR_GAME_STATE_PLUS_FOLD_LOCAL_FILL",
            missing_policy=(
                "TREE_NATIVE_MISSING_OR_DENSE_TRAINING_FOLD_CONTEXTUAL_MEDIAN; "
                "NEVER_ZERO_FOR_UNKNOWN_TIME_ZONE"
            ),
            outlier_policy="REGISTERED_TIME_ZONE_DOMAIN_VALIDATION_NO_IQR_CAPPING",
            paired_indicator=previous_missing,
            source_failure_indicators=(
                f"{side}_current_start_missing",
                f"{side}_current_venue_timezone_missing",
            ),
            source_failure_indicators_unless_no_history=(
                f"{side}_previous_venue_timezone_missing",
            ),
        ),
        "early": _parent(
            f"{side}_early_start_after_eastward_travel",
            data_type="numeric",
            semantic_domain="{0,1} registered Boolean encoding",
            domain_kind="BOOLEAN",
            missing_disposition="NO_MISSING_TREATMENT",
            missing_policy="REQUIRED_BOOLEAN_UNKNOWN_MUST_NOT_BECOME_FALSE",
            outlier_policy="HARD_BOOLEAN_DOMAIN_VALIDATION_NO_CAPPING",
            paired_indicator=previous_missing,
            source_failure_indicators=(
                f"{side}_current_start_missing",
                f"{side}_current_venue_timezone_missing",
            ),
            source_failure_indicators_unless_no_history=(
                f"{side}_previous_venue_timezone_missing",
            ),
        ),
    }


def _interaction(
    feature: str,
    *,
    formula: str,
    source_formula: str,
    formula_operator: str,
    parents: Sequence[Mapping[str, Any]],
    output_domain: str,
    output_domain_kind: str,
    boolean_parent_position: int | None,
) -> dict[str, Any]:
    return {
        "featureName": feature,
        "interactionFeature": feature,
        "backendFeatureIdentity": feature,
        "featureFamily": "INTERACTION",
        "formula": formula,
        "sourceFormulaLiteral": source_formula,
        "formulaVersion": f"{CONTEXT_FEATURE_VERSION}::{feature}::V1",
        "formulaOperator": formula_operator,
        "formulaSource": (
            "server/sports_current_statcast/contextual_features.py::"
            "build_team_game_context"
        ),
        "orderedParents": [str(parent["feature"]) for parent in parents],
        "parents": [copy.deepcopy(dict(parent)) for parent in parents],
        "booleanParentPosition": boolean_parent_position,
        "missingStatePropagation": (
            "PARENT_FIRST; TRUE_NO_HISTORY_USES_ONLY_REGISTERED_PARENT_POLICY; "
            "NO_INDEPENDENT_INTERACTION_IMPUTATION"
        ),
        "sourceFailurePropagation": "ANY_PARENT_SOURCE_UNAVAILABLE=>SOURCE_UNAVAILABLE",
        "computationFailurePropagation": (
            "ANY_PARENT_COMPUTATION_FAILURE=>COMPUTATION_FAILURE"
        ),
        "structuralZeroRule": (
            "BOOLEAN_FALSE_MAY_YIELD_ZERO_ONLY_AFTER_BOOLEAN_DOMAIN_AND_SOURCE_VALIDATION"
            if boolean_parent_position is not None
            else "NONE"
        ),
        "outputDataType": "numeric",
        "outputDomain": output_domain,
        "outputDomainKind": output_domain_kind,
        "operationOrder": list(OPERATION_ORDER),
        "modelFamilyResolution": copy.deepcopy(dict(MODEL_FAMILY_RESOLUTION)),
        "pointInTimeStatus": "PASS",
        "foldLocalStatus": "PASS",
        "executableStatus": "READY_GOVERNED_INTERACTION_V1",
        "selectable": True,
        "blockedReason": None,
        "independentImputation": "PROHIBITED",
        "independentCapping": "PROHIBITED",
    }


_FIELDING = _parent_set("fielding")
_BATTING = _parent_set("batting")

# Deliberately explicit registry in the exact reviewed blocker order.  No code
# derives membership from a naming convention.
_BINDINGS: Final[tuple[dict[str, Any], ...]] = (
    _interaction(
        "fielding_road_trip_length_x_travel",
        formula=(
            "fielding_road_trip_game_number * fielding_travel_distance_miles"
        ),
        source_formula="road_trip_game_number * travel_distance_miles",
        formula_operator="PRODUCT",
        parents=(_FIELDING["road"], _FIELDING["travel"]),
        output_domain="nonnegative finite miles-games or governed missing state",
        output_domain_kind="NONNEGATIVE_FINITE",
        boolean_parent_position=None,
    ),
    _interaction(
        "fielding_prior_extra_innings_x_travel",
        formula=(
            "fielding_previous_game_extra_innings * "
            "fielding_travel_distance_miles"
        ),
        source_formula="previous_game_extra_innings * travel_distance_miles",
        formula_operator="BOOLEAN_TIMES_CONTINUOUS",
        parents=(_FIELDING["extra"], _FIELDING["travel"]),
        output_domain="nonnegative finite miles or governed missing state",
        output_domain_kind="NONNEGATIVE_FINITE",
        boolean_parent_position=0,
    ),
    _interaction(
        "fielding_long_travel_x_short_rest",
        formula=(
            "int(fielding_travel_distance_miles >= 1500) * "
            "fielding_short_rest_indicator"
        ),
        source_formula="int(travel_distance_miles >= 1500) * short_rest_indicator",
        formula_operator="LONG_TRAVEL_BOOLEAN_INTERSECTION",
        parents=(_FIELDING["travel"], _FIELDING["short"]),
        output_domain="{0,1} registered Boolean encoding or governed missing state",
        output_domain_kind="BOOLEAN",
        boolean_parent_position=1,
    ),
    _interaction(
        "fielding_eastward_travel_x_early_start",
        formula=(
            "fielding_eastward_time_zone_change_hours * "
            "fielding_early_start_after_eastward_travel"
        ),
        source_formula=(
            "eastward_time_zone_change_hours * early_start_after_eastward_travel"
        ),
        formula_operator="CONTINUOUS_TIMES_BOOLEAN",
        parents=(_FIELDING["east"], _FIELDING["early"]),
        output_domain="[0,12] eastward hours or governed missing state",
        output_domain_kind="EASTWARD_HOURS",
        boolean_parent_position=1,
    ),
    _interaction(
        "batting_road_trip_length_x_travel",
        formula="batting_road_trip_game_number * batting_travel_distance_miles",
        source_formula="road_trip_game_number * travel_distance_miles",
        formula_operator="PRODUCT",
        parents=(_BATTING["road"], _BATTING["travel"]),
        output_domain="nonnegative finite miles-games or governed missing state",
        output_domain_kind="NONNEGATIVE_FINITE",
        boolean_parent_position=None,
    ),
    _interaction(
        "batting_prior_extra_innings_x_travel",
        formula=(
            "batting_previous_game_extra_innings * batting_travel_distance_miles"
        ),
        source_formula="previous_game_extra_innings * travel_distance_miles",
        formula_operator="BOOLEAN_TIMES_CONTINUOUS",
        parents=(_BATTING["extra"], _BATTING["travel"]),
        output_domain="nonnegative finite miles or governed missing state",
        output_domain_kind="NONNEGATIVE_FINITE",
        boolean_parent_position=0,
    ),
    _interaction(
        "batting_long_travel_x_short_rest",
        formula=(
            "int(batting_travel_distance_miles >= 1500) * "
            "batting_short_rest_indicator"
        ),
        source_formula="int(travel_distance_miles >= 1500) * short_rest_indicator",
        formula_operator="LONG_TRAVEL_BOOLEAN_INTERSECTION",
        parents=(_BATTING["travel"], _BATTING["short"]),
        output_domain="{0,1} registered Boolean encoding or governed missing state",
        output_domain_kind="BOOLEAN",
        boolean_parent_position=1,
    ),
    _interaction(
        "batting_eastward_travel_x_early_start",
        formula=(
            "batting_eastward_time_zone_change_hours * "
            "batting_early_start_after_eastward_travel"
        ),
        source_formula=(
            "eastward_time_zone_change_hours * early_start_after_eastward_travel"
        ),
        formula_operator="CONTINUOUS_TIMES_BOOLEAN",
        parents=(_BATTING["east"], _BATTING["early"]),
        output_domain="[0,12] eastward hours or governed missing state",
        output_domain_kind="EASTWARD_HOURS",
        boolean_parent_position=1,
    ),
)

_BY_FEATURE: Final = {
    str(binding["interactionFeature"]): binding for binding in _BINDINGS
}
INTERACTION_FEATURES: Final = tuple(_BY_FEATURE)


def feature_binding(feature: str) -> dict[str, Any] | None:
    """Return a defensive copy only for an explicitly registered interaction."""

    binding = _BY_FEATURE.get(feature)
    return copy.deepcopy(binding) if binding is not None else None


def authority_configuration(
    *, overrides: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Return the immutable scientific configuration used by the authority."""

    configuration: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "authorityName": AUTHORITY_NAME,
        "implementationSha256": hashlib.sha256(
            Path(__file__).read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        "contextFeatureVersion": CONTEXT_FEATURE_VERSION,
        "formulaAuthority": (
            "LITERAL_EXPRESSIONS_REGISTERED_IN_CONTEXTUAL_FEATURE_MATERIALIZER"
        ),
        "historyCutoff": HISTORY_CUTOFF,
        "operationOrder": list(OPERATION_ORDER),
        "modelFamilyResolution": copy.deepcopy(dict(MODEL_FAMILY_RESOLUTION)),
        "foldLocalFit": {
            "learnedParentParameters": (
                "DENSE_FAMILY_CONTEXTUAL_MEDIANS_FROM_TRAINING_ROWS_ONLY"
            ),
            "optionalOutputScaling": "TRAINING_ROWS_ONLY_AFTER_SEMANTIC_RECOMPUTATION",
            "validationRowsFitParameters": False,
            "finalOotRowsFitParameters": False,
        },
        "leakageControls": {
            "targetColumnsRead": False,
            "laterRowsAffectEarlierRows": False,
            "finalOotRejectedBeforeFeatureRead": True,
            "predictiveModelFit": False,
            "scoreOrCalibration": False,
        },
        "thresholds": {"longTravelMiles": LONG_TRAVEL_MILES},
        "bindings": [copy.deepcopy(binding) for binding in _BINDINGS],
    }
    if overrides:
        for key, value in overrides.items():
            configuration[str(key)] = copy.deepcopy(value)
    return configuration


def authority_checksum(*, configuration: Mapping[str, Any] | None = None) -> str:
    return _sha256(configuration or authority_configuration())


def _public_project_authority(project_authority: Any) -> dict[str, Any]:
    if callable(getattr(project_authority, "public", None)):
        return dict(project_authority.public())
    if isinstance(project_authority, Mapping):
        return dict(project_authority)
    return {}


def project_authority_manifest(
    project_authority: Any,
    *,
    treatment_specification_key: str,
    treatment_specification_sha256: str,
    feature_inventory_sha256: str,
    compiler_version: str,
    compiler_sha256: str,
    contextual_formula_source_sha256: str,
    development_identity: Mapping[str, Any] | None = None,
    final_oot_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind the scientific registry to exact project, data, and compiler inputs."""

    public = _public_project_authority(project_authority)
    development = dict(
        development_identity
        or {
            "rows": DEVELOPMENT_ROWS,
            "start": DEVELOPMENT_START,
            "end": DEVELOPMENT_END,
        }
    )
    final_oot = dict(
        final_oot_identity
        or {
            "rows": FINAL_OOT_ROWS,
            "start": FINAL_OOT_START,
            "end": FINAL_OOT_END,
            "status": "LOCKED_UNOPENED",
            "accessCount": 0,
        }
    )
    config = authority_configuration()
    content: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "authorityName": AUTHORITY_NAME,
        "configurationChecksum": authority_checksum(configuration=config),
        "projectId": public.get("projectId"),
        "goldDatasetId": public.get("goldDatasetId"),
        "goldManifestSha": public.get("goldManifestSha"),
        "contextualDatasetId": public.get("contextualDatasetId"),
        "contextualManifestSha": public.get("contextualManifestSha"),
        "reviewDigest": public.get("reviewDigest"),
        "featureInventorySha256": feature_inventory_sha256,
        "treatmentSpecificationSource": {
            "key": treatment_specification_key,
            "sourceContentSha256": treatment_specification_sha256,
        },
        "compiler": {
            "version": compiler_version,
            "sha256": compiler_sha256,
        },
        "contextualFormulaSource": {
            "version": CONTEXT_FEATURE_VERSION,
            "sha256": contextual_formula_source_sha256,
            "historyCutoff": HISTORY_CUTOFF,
        },
        "development": development,
        "finalOot": final_oot,
        "pointInTime": "PASS",
        "foldLocal": "PASS",
        "finalOotPolicy": "LOCKED_NOT_OPENED_NOT_FIT_NOT_TRANSFORMED",
        "featureCount": len(INTERACTION_FEATURES),
        "readyFeatureCount": len(INTERACTION_FEATURES),
        "blockedFeatureCount": 0,
        "bindings": config["bindings"],
        "modelActivity": {
            "fits": 0,
            "scores": 0,
            "calibrations": 0,
            "promotions": 0,
            "gameScoringJobs": 0,
            "featureSetsRegistered": 0,
            "goldMutations": 0,
        },
    }
    checksum = _sha256(content)
    return {
        **content,
        "authorityChecksum": checksum,
        "authorityId": f"{AUTHORITY_NAME}:sha256:{checksum}",
    }


def _validated_authority_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    content = {
        key: copy.deepcopy(value)
        for key, value in manifest.items()
        if key not in {"authorityChecksum", "authorityId"}
    }
    checksum = _sha256(content)
    expected_id = f"{AUTHORITY_NAME}:sha256:{checksum}"
    if str(manifest.get("authorityChecksum") or "") != checksum:
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_CHECKSUM_MISMATCH",
            "Project-bound interaction authority failed its content-address check.",
        )
    if str(manifest.get("authorityId") or "") != expected_id:
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_ID_MISMATCH",
            "Project-bound interaction authority ID does not match its content.",
        )
    if manifest.get("authorityName") != AUTHORITY_NAME:
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_NAME_MISMATCH", "Unsupported authority name."
        )
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_SCHEMA_MISMATCH", "Unsupported authority schema."
        )
    if manifest.get("configurationChecksum") != authority_checksum():
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_CONFIGURATION_STALE",
            "The project manifest does not bind the current interaction configuration.",
        )
    configuration = authority_configuration()
    if manifest.get("bindings") != configuration["bindings"]:
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_BINDINGS_STALE",
            "The project manifest does not contain the exact registered interaction bindings.",
        )
    if (
        int(manifest.get("featureCount", -1)) != len(INTERACTION_FEATURES)
        or int(manifest.get("readyFeatureCount", -1)) != len(INTERACTION_FEATURES)
        or int(manifest.get("blockedFeatureCount", -1)) != 0
    ):
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_COUNTS_INVALID",
            "The project manifest does not reconcile to the exact eight ready interactions.",
        )
    required_paths = {
        "projectId": manifest.get("projectId"),
        "goldDatasetId": manifest.get("goldDatasetId"),
        "goldManifestSha": manifest.get("goldManifestSha"),
        "contextualDatasetId": manifest.get("contextualDatasetId"),
        "contextualManifestSha": manifest.get("contextualManifestSha"),
        "reviewDigest": manifest.get("reviewDigest"),
        "featureInventorySha256": manifest.get("featureInventorySha256"),
        "treatmentSpecificationSource": manifest.get("treatmentSpecificationSource"),
        "compiler": manifest.get("compiler"),
        "contextualFormulaSource": manifest.get("contextualFormulaSource"),
        "development": manifest.get("development"),
        "finalOot": manifest.get("finalOot"),
    }
    missing = sorted(key for key, value in required_paths.items() if not value)
    if missing:
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_PROJECT_BINDING_MISSING",
            f"Project-bound interaction authority is missing: {', '.join(missing)}.",
        )
    invalid_sha_fields = sorted(
        key
        for key in (
            "goldManifestSha",
            "contextualManifestSha",
            "reviewDigest",
            "featureInventorySha256",
        )
        if not _is_sha256(manifest.get(key))
    )
    if invalid_sha_fields:
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_PROJECT_BINDING_INVALID",
            "Project-bound SHA-256 bindings are invalid: "
            + ", ".join(invalid_sha_fields)
            + ".",
        )
    treatment_source = manifest.get("treatmentSpecificationSource")
    compiler = manifest.get("compiler")
    formula_source = manifest.get("contextualFormulaSource")
    if not all(
        isinstance(value, Mapping)
        for value in (treatment_source, compiler, formula_source)
    ):
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_NESTED_BINDING_INVALID",
            "Treatment, compiler, and contextual-formula bindings must be mappings.",
        )
    treatment_source = dict(treatment_source)
    compiler = dict(compiler)
    formula_source = dict(formula_source)
    if not str(treatment_source.get("key") or "") or not _is_sha256(
        treatment_source.get("sourceContentSha256")
    ):
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_TREATMENT_BINDING_INVALID",
            "Treatment authority requires a key and exact source SHA-256.",
        )
    if not str(compiler.get("version") or "") or not _is_sha256(
        compiler.get("sha256")
    ):
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_COMPILER_BINDING_INVALID",
            "Compiler authority requires a version and exact SHA-256.",
        )
    if (
        formula_source.get("version") != CONTEXT_FEATURE_VERSION
        or not _is_sha256(formula_source.get("sha256"))
        or formula_source.get("historyCutoff") != HISTORY_CUTOFF
    ):
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_FORMULA_BINDING_INVALID",
            "Contextual formula authority requires the exact version, SHA-256, and history cutoff.",
        )
    if manifest.get("pointInTime") != "PASS" or manifest.get("foldLocal") != "PASS":
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_SAFETY_GATE_INVALID",
            "Point-in-time and fold-local authority gates must both pass.",
        )
    if manifest.get("finalOotPolicy") != "LOCKED_NOT_OPENED_NOT_FIT_NOT_TRANSFORMED":
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_FINAL_OOT_POLICY_INVALID",
            "Final OOT must remain locked, unopened, unfit, and untransformed.",
        )
    if not isinstance(manifest["development"], Mapping) or not isinstance(
        manifest["finalOot"], Mapping
    ):
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_POPULATION_BINDING_INVALID",
            "Development and final-OOT identities must be mappings.",
        )
    development = dict(manifest["development"])
    if any(
        (
            development.get("rows") != DEVELOPMENT_ROWS,
            development.get("start") != DEVELOPMENT_START,
            development.get("end") != DEVELOPMENT_END,
        )
    ):
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_DEVELOPMENT_BOUNDARY_INVALID",
            "Development identity must match the exact registered rows and date boundaries.",
        )
    final_oot = dict(manifest["finalOot"])
    if (
        final_oot.get("rows") != FINAL_OOT_ROWS
        or final_oot.get("start") != FINAL_OOT_START
        or final_oot.get("end") != FINAL_OOT_END
        or final_oot.get("status") != "LOCKED_UNOPENED"
        or final_oot.get("accessCount") != 0
    ):
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_FINAL_OOT_OPENED",
            "Final OOT identity must prove locked/unopened status and zero access.",
        )
    model_activity = manifest.get("modelActivity")
    expected_activity = {
        "fits",
        "scores",
        "calibrations",
        "promotions",
        "gameScoringJobs",
        "featureSetsRegistered",
        "goldMutations",
    }
    if not isinstance(model_activity, Mapping) or any(
        model_activity.get(key) != 0 for key in expected_activity
    ):
        raise InteractionAuthorityError(
            "INTERACTION_AUTHORITY_ACTIVITY_INVALID",
            "The interaction authority cannot carry model, scoring, registration, or Gold activity.",
        )
    return {**content, "authorityChecksum": checksum, "authorityId": expected_id}


def required_input_columns(features: Sequence[str] | None = None) -> tuple[str, ...]:
    selected = tuple(features or INTERACTION_FEATURES)
    columns = {"game_date"}
    for feature in selected:
        binding = _BY_FEATURE.get(feature)
        if binding is None:
            raise InteractionAuthorityError(
                "INTERACTION_FEATURE_NOT_REGISTERED",
                f"{feature} is not one of the eight explicitly registered interactions.",
            )
        for parent in binding["parents"]:
            columns.add(str(parent["feature"]))
            indicator = parent.get("pairedMissingnessIndicator")
            if indicator:
                columns.add(str(indicator))
            columns.update(str(value) for value in parent["sourceFailureIndicators"])
            columns.update(
                str(value)
                for value in parent["sourceFailureIndicatorsUnlessNoHistory"]
            )
    return tuple(sorted(columns))


def _available_input_columns(
    frame: pd.DataFrame,
    required: Sequence[str],
    features: Sequence[str],
) -> list[str]:
    """Preserve optional explicit failure states without making them mandatory."""

    columns = set(required)
    for feature in features:
        for parent in _BY_FEATURE[feature]["parents"]:
            reason_column = f"{parent['feature']}__missing_reason"
            if reason_column in frame:
                columns.add(reason_column)
    return sorted(columns)


def _normalize_model_family(model_family: str) -> str:
    family = str(model_family).strip().upper()
    if family not in MODEL_FAMILY_RESOLUTION:
        raise InteractionAuthorityError(
            "INTERACTION_MODEL_FAMILY_UNSUPPORTED",
            f"Unsupported model family {model_family}.",
        )
    return family


def _date_boundary(
    frame: pd.DataFrame, *, operation: str
) -> tuple[pd.Series, np.ndarray]:
    # This helper must run before required parent-column checks.  It reads only
    # the date column, so forbidden OOT feature values remain untouched.
    if "game_date" not in frame:
        raise InteractionAuthorityError(
            f"INTERACTION_{operation}_GAME_DATE_MISSING", "game_date is required."
        )
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if bool(dates.isna().any()):
        raise InteractionAuthorityError(
            f"INTERACTION_{operation}_GAME_DATE_INVALID",
            "Every interaction row requires a valid game_date.",
        )
    crosses_oot = dates.gt(pd.Timestamp(DEVELOPMENT_END)).to_numpy()
    if bool(crosses_oot.any()):
        raise InteractionAuthorityError(
            f"INTERACTION_{operation}_CROSSES_FINAL_OOT",
            f"Interaction {operation.lower()} cannot read rows after {DEVELOPMENT_END}.",
        )
    return dates, crosses_oot


def _numeric(frame: pd.DataFrame, column: str) -> np.ndarray:
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=np.float64)


def _boolean_indicator(
    frame: pd.DataFrame, column: str
) -> tuple[np.ndarray, np.ndarray]:
    values = _numeric(frame, column)
    valid = np.isfinite(values) & np.isin(values, (0.0, 1.0))
    # Governance indicators are evidence, not conveniences. Missing or
    # non-Boolean values cannot authorize a fill, structural zero, or an
    # available state; callers propagate the second mask as a computation
    # failure.
    return valid & (values == 1.0), ~valid


def _explicit_reason_masks(frame: pd.DataFrame, parent: str) -> tuple[np.ndarray, np.ndarray]:
    column = f"{parent}__missing_reason"
    if column not in frame:
        empty = np.zeros(len(frame), dtype=bool)
        return empty, empty.copy()
    reasons = frame[column].fillna("").astype(str).str.upper().str.strip()
    source = reasons.isin(SOURCE_REASON_VALUES).to_numpy()
    computation = reasons.isin(COMPUTATION_REASON_VALUES).to_numpy()
    unregistered = ~(reasons.eq("") | reasons.isin(SOURCE_REASON_VALUES | COMPUTATION_REASON_VALUES))
    return source, computation | unregistered.to_numpy()


def _domain_failure(values: np.ndarray, kind: str) -> np.ndarray:
    finite = np.isfinite(values)
    if kind == "BOOLEAN":
        return finite & ~np.isin(values, (0.0, 1.0))
    if kind == "NONNEGATIVE_INTEGER":
        return finite & (
            (values < 0.0) | (np.abs(values - np.rint(values)) > INTEGER_TOLERANCE)
        )
    if kind == "NONNEGATIVE_FINITE":
        return finite & (values < 0.0)
    if kind == "EASTWARD_HOURS":
        return finite & ((values < 0.0) | (values > 12.0))
    raise InteractionAuthorityError(
        "INTERACTION_PARENT_DOMAIN_UNREGISTERED", f"Unknown parent domain {kind}."
    )


def _parent_state(
    frame: pd.DataFrame,
    parent: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    name = str(parent["feature"])
    raw_values = frame[name]
    raw_missing = raw_values.isna().to_numpy()
    values = pd.to_numeric(raw_values, errors="coerce").to_numpy(dtype=np.float64)
    finite = np.isfinite(values)
    present_nonfinite = ~raw_missing & ~finite
    domain_failure = _domain_failure(values, str(parent["domainKind"]))
    explicit_source, explicit_computation = _explicit_reason_masks(frame, name)
    paired = parent.get("pairedMissingnessIndicator")
    indicator_computation = np.zeros(len(frame), dtype=bool)
    if paired:
        cold, invalid = _boolean_indicator(frame, str(paired))
        indicator_computation |= invalid
    else:
        cold = np.zeros(len(frame), dtype=bool)
    source_indicator = np.zeros(len(frame), dtype=bool)
    for indicator in parent["sourceFailureIndicators"]:
        indicated, invalid = _boolean_indicator(frame, str(indicator))
        source_indicator |= indicated
        indicator_computation |= invalid
    conditional_source_indicator = np.zeros(len(frame), dtype=bool)
    for indicator in parent["sourceFailureIndicatorsUnlessNoHistory"]:
        indicated, invalid = _boolean_indicator(frame, str(indicator))
        conditional_source_indicator |= indicated
        indicator_computation |= invalid
    # Prior-source indicators also fire on a true no-history row; the paired
    # no-history authority may override only those prior-side flags. Current
    # game source failures retain precedence even on a cold-start row.
    source_failure = (
        explicit_source
        | source_indicator
        | (conditional_source_indicator & ~cold)
    )
    missing_without_registered_cold = raw_missing & ~cold
    source_failure |= missing_without_registered_cold & ~explicit_computation
    contradictory_no_history_boolean = (
        cold
        & finite
        & (values == 1.0)
        & bool(paired)
        & (str(parent["domainKind"]) == "BOOLEAN")
    )
    computation_failure = (
        explicit_computation
        | domain_failure
        | indicator_computation
        | present_nonfinite
        | contradictory_no_history_boolean
    ) & ~source_failure
    # A value alongside a source-unavailable marker remains unavailable even
    # when numerically finite; source flags describe evidence authority.
    valid = finite & ~source_failure & ~computation_failure
    return values, cold & ~source_failure & ~computation_failure, source_failure, computation_failure | (~valid & ~cold & ~source_failure)


def _dense_fill_parent_names(
    features: Sequence[str],
) -> tuple[str, ...]:
    names: set[str] = set()
    for feature in features:
        for parent in _BY_FEATURE[feature]["parents"]:
            if parent["missingDisposition"] == "NO_PRIOR_GAME_STATE_PLUS_FOLD_LOCAL_FILL":
                names.add(str(parent["feature"]))
    return tuple(sorted(names))


def _fit_parent_medians(
    training: pd.DataFrame, features: Sequence[str]
) -> dict[str, dict[str, Any]]:
    parameters: dict[str, dict[str, Any]] = {}
    parent_by_name = {
        str(parent["feature"]): parent
        for feature in features
        for parent in _BY_FEATURE[feature]["parents"]
    }
    for name in _dense_fill_parent_names(features):
        values, cold, source, computation = _parent_state(
            training, parent_by_name[name]
        )
        eligible = np.isfinite(values) & ~cold & ~source & ~computation
        if not bool(eligible.any()):
            raise InteractionAuthorityError(
                "INTERACTION_PARENT_TRAINING_EVIDENCE_EMPTY",
                f"No valid training-fold evidence exists for dense parent {name}.",
            )
        parameters[name] = {
            "method": "TRAINING_FOLD_CONTEXTUAL_MEDIAN",
            "value": float(np.median(values[eligible])),
            "fitRows": int(eligible.sum()),
            "validationRowsFit": 0,
            "finalOotRowsFit": 0,
        }
    return parameters


def _treat_parent(
    frame: pd.DataFrame,
    parent: Mapping[str, Any],
    *,
    family: str,
    parent_parameters: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    values, cold, source, computation = _parent_state(frame, parent)
    treated = values.copy()
    disposition = str(parent["missingDisposition"])
    if disposition == "STRUCTURAL_ZERO_PLUS_INDICATOR":
        # The paired no-history indicator is the governing evidence.  A
        # missing/false prior-event Boolean therefore canonicalizes to zero;
        # a contradictory true value was already marked as computation
        # failure by _parent_state and is never consumed.
        treated[cold] = 0.0
    elif disposition == "NO_PRIOR_GAME_STATE_PLUS_FOLD_LOCAL_FILL" and family == "TREE":
        # Never consume a prefilled or corrupt cold-start value.  Tree models
        # retain the registered native-missing state regardless of the raw
        # payload whenever the paired no-history authority is true.
        treated[cold] = np.nan
    elif disposition == "NO_PRIOR_GAME_STATE_PLUS_FOLD_LOCAL_FILL":
        parameter = parent_parameters.get(str(parent["feature"]))
        if not isinstance(parameter, Mapping) or not np.isfinite(parameter.get("value")):
            raise InteractionAuthorityError(
                "INTERACTION_PARENT_FROZEN_MEDIAN_MISSING",
                f"Dense transform lacks a frozen median for {parent['feature']}.",
            )
        # Dense families likewise ignore any raw cold-start payload and use
        # only the frozen training-fold parameter registered for this parent.
        treated[cold] = float(parameter["value"])
    state = np.full(len(frame), "AVAILABLE", dtype=object)
    state[cold] = (
        "TRUE_NO_HISTORY_NATIVE_MISSING"
        if family == "TREE" and ~np.isfinite(treated[cold]).all()
        else "TRUE_NO_HISTORY_PARENT_TREATMENT"
    )
    state[source] = "SOURCE_UNAVAILABLE"
    state[computation] = "COMPUTATION_FAILURE"
    treated[source | computation] = np.nan
    return treated, state


def _apply_formula(
    binding: Mapping[str, Any], parent_values: Sequence[np.ndarray]
) -> np.ndarray:
    first, second = parent_values
    operator = str(binding["formulaOperator"])
    if operator == "PRODUCT":
        return first * second
    if operator == "BOOLEAN_TIMES_CONTINUOUS":
        return first * second
    if operator == "CONTINUOUS_TIMES_BOOLEAN":
        return first * second
    if operator == "LONG_TRAVEL_BOOLEAN_INTERSECTION":
        result = (first >= LONG_TRAVEL_MILES).astype(np.float64) * second
        # The canonical materializer guards on distance availability before
        # thresholding.  NaN must therefore remain missing even when the other
        # Boolean parent happens to be false.
        result[~np.isfinite(first)] = np.nan
        return result
    raise InteractionAuthorityError(
        "INTERACTION_FORMULA_OPERATOR_UNREGISTERED",
        f"No executable formula operator is registered for {binding['interactionFeature']}.",
    )


def _output_domain_failure(values: np.ndarray, kind: str) -> np.ndarray:
    return _domain_failure(values, kind)


def _transform_semantic(
    frame: pd.DataFrame,
    *,
    family: str,
    parent_parameters: Mapping[str, Any],
    features: Sequence[str],
) -> pd.DataFrame:
    outputs: dict[str, Any] = {}
    for feature in features:
        binding = _BY_FEATURE[feature]
        treated: list[np.ndarray] = []
        parent_states: list[np.ndarray] = []
        for parent in binding["parents"]:
            values, state = _treat_parent(
                frame,
                parent,
                family=family,
                parent_parameters=parent_parameters,
            )
            treated.append(values)
            parent_states.append(state)
        source = np.logical_or.reduce(
            [state == "SOURCE_UNAVAILABLE" for state in parent_states]
        )
        computation = np.logical_or.reduce(
            [state == "COMPUTATION_FAILURE" for state in parent_states]
        ) & ~source
        has_no_history = np.logical_or.reduce(
            [np.char.startswith(state.astype(str), "TRUE_NO_HISTORY") for state in parent_states]
        )
        values = _apply_formula(binding, treated)
        values[source | computation] = np.nan
        output_failure = _output_domain_failure(values, str(binding["outputDomainKind"]))
        computation |= output_failure & ~source
        values[output_failure] = np.nan
        state = np.full(len(frame), "AVAILABLE", dtype=object)
        state[has_no_history & np.isfinite(values)] = "TRUE_NO_HISTORY_GOVERNED_RESULT"
        state[has_no_history & ~np.isfinite(values)] = "TRUE_NO_HISTORY_NATIVE_MISSING"
        state[source] = "SOURCE_UNAVAILABLE"
        state[computation] = "COMPUTATION_FAILURE"
        # Any unresolved NaN that is not a registered no-history result fails
        # closed as a computation state.
        unresolved = ~np.isfinite(values) & ~source & ~computation & ~has_no_history
        state[unresolved] = "COMPUTATION_FAILURE"
        outputs[feature] = values
        outputs[f"{feature}__state"] = state
        outputs[f"{feature}__missing_reason"] = np.where(
            state == "SOURCE_UNAVAILABLE",
            "SOURCE_UNAVAILABLE",
            np.where(
                state == "COMPUTATION_FAILURE",
                "COMPUTATION_FAILURE",
                np.where(
                    state == "TRUE_NO_HISTORY_NATIVE_MISSING",
                    "NO_PRIOR_HISTORY",
                    "",
                ),
            ),
        )
    return pd.DataFrame(outputs, index=frame.index)


def fit_interaction_authority(
    frame: pd.DataFrame,
    *,
    training_end: str,
    authority_manifest: Mapping[str, Any],
    fold_id: str,
    model_family: str,
    features: Sequence[str] | None = None,
    scale_interactions: bool = False,
) -> dict[str, Any]:
    """Fit only fold-local parent medians and optional downstream scalers."""

    started = time.perf_counter()
    verified = _validated_authority_manifest(authority_manifest)
    family = _normalize_model_family(model_family)
    selected = tuple(features or INTERACTION_FEATURES)
    # Validate exact membership without any name-pattern shortcut.
    required = required_input_columns(selected)
    dates, _ = _date_boundary(frame, operation="FIT")
    cutoff = pd.Timestamp(training_end)
    if cutoff > pd.Timestamp(DEVELOPMENT_END):
        raise InteractionAuthorityError(
            "INTERACTION_FIT_CUTOFF_CROSSES_FINAL_OOT",
            f"Training cutoff {training_end} exceeds {DEVELOPMENT_END}.",
        )
    training_mask = dates.le(cutoff).to_numpy()
    if not bool(training_mask.any()):
        raise InteractionAuthorityError(
            "INTERACTION_TRAINING_WINDOW_EMPTY",
            "No rows are at or before the training cutoff.",
        )
    # Required feature columns are checked only after the OOT boundary. Slice
    # columns and rows together so validation feature values are never read.
    missing = [column for column in required if column not in frame]
    if missing:
        raise InteractionAuthorityError(
            "INTERACTION_FIT_INPUT_COLUMNS_MISSING",
            f"Interaction fitting input is missing: {', '.join(missing)}.",
        )
    training = frame.loc[
        training_mask, _available_input_columns(frame, required, selected)
    ]
    parent_parameters = (
        {} if family == "TREE" else _fit_parent_medians(training, selected)
    )
    scaler_parameters: dict[str, dict[str, Any]] = {}
    if scale_interactions:
        if family == "TREE":
            raise InteractionAuthorityError(
                "INTERACTION_TREE_SCALING_PROHIBITED",
                "Tree-family interaction authority does not fit downstream scaling.",
            )
        semantic = _transform_semantic(
            training,
            family=family,
            parent_parameters=parent_parameters,
            features=selected,
        )
        for feature in selected:
            state = semantic[f"{feature}__state"].astype(str)
            values = semantic[feature].to_numpy(dtype=np.float64)
            eligible = np.isfinite(values) & ~state.isin(
                {"SOURCE_UNAVAILABLE", "COMPUTATION_FAILURE"}
            ).to_numpy()
            if not bool(eligible.any()):
                raise InteractionAuthorityError(
                    "INTERACTION_SCALER_TRAINING_EVIDENCE_EMPTY",
                    f"No valid training values exist for scaler {feature}.",
                )
            mean = float(np.mean(values[eligible]))
            scale = float(np.std(values[eligible], ddof=0))
            scaler_parameters[feature] = {
                "method": "STANDARD_SCALER_AFTER_SEMANTIC_RECOMPUTATION",
                "mean": mean,
                "scale": scale if scale > 0.0 else 1.0,
                "zeroVariance": scale <= 0.0,
                "fitRows": int(eligible.sum()),
                "validationRowsFit": 0,
                "finalOotRowsFit": 0,
            }
    training_dates = dates[training_mask]
    content: dict[str, Any] = {
        "schemaVersion": FITTED_SCHEMA_VERSION,
        "authorityId": verified["authorityId"],
        "authorityChecksum": verified["authorityChecksum"],
        "authorityConfigurationChecksum": verified["configurationChecksum"],
        "projectId": verified["projectId"],
        "goldDatasetId": verified["goldDatasetId"],
        "goldManifestSha": verified["goldManifestSha"],
        "contextualDatasetId": verified["contextualDatasetId"],
        "contextualManifestSha": verified["contextualManifestSha"],
        "featureInventorySha256": verified["featureInventorySha256"],
        "treatmentSpecificationSource": verified["treatmentSpecificationSource"],
        "compiler": verified["compiler"],
        "contextualFormulaSource": verified["contextualFormulaSource"],
        "development": verified["development"],
        "finalOot": verified["finalOot"],
        "foldId": str(fold_id),
        "modelFamily": family,
        "trainingStart": training_dates.min().date().isoformat(),
        "trainingEnd": cutoff.date().isoformat(),
        "trainingRows": int(training_mask.sum()),
        "rowsAfterTrainingCutoffExcluded": int((~training_mask).sum()),
        "features": list(selected),
        "parentParameters": parent_parameters,
        "scaleInteractions": bool(scale_interactions),
        "scalerParameters": scaler_parameters,
        "fitEvidence": {
            "validationFeatureValuesRead": False,
            "targetColumnRead": False,
            "finalOotRowsRead": 0,
            "finalOotRowsFit": 0,
            "modelFits": 0,
            "scores": 0,
            "calibrations": 0,
        },
    }
    checksum = _sha256(content)
    return {
        **content,
        "fittedChecksum": checksum,
        "fittedId": f"{FITTED_SCHEMA_VERSION}:{fold_id}:sha256:{checksum}",
        "fitDurationMs": round((time.perf_counter() - started) * 1000.0, 3),
    }


def _validate_fitted(fitted: Mapping[str, Any]) -> None:
    content = {
        key: copy.deepcopy(value)
        for key, value in fitted.items()
        if key not in {"fittedChecksum", "fittedId", "fitDurationMs"}
    }
    checksum = _sha256(content)
    if checksum != str(fitted.get("fittedChecksum") or ""):
        raise InteractionAuthorityError(
            "INTERACTION_FITTED_CHECKSUM_MISMATCH",
            "Fitted interaction preprocessing evidence failed its checksum.",
        )
    expected_id = (
        f"{FITTED_SCHEMA_VERSION}:{fitted.get('foldId')}:sha256:{checksum}"
    )
    if str(fitted.get("fittedId") or "") != expected_id:
        raise InteractionAuthorityError(
            "INTERACTION_FITTED_ID_MISMATCH",
            "Fitted interaction evidence ID does not match its content.",
        )
    if fitted.get("authorityConfigurationChecksum") != authority_checksum():
        raise InteractionAuthorityError(
            "INTERACTION_FITTED_CONFIGURATION_STALE",
            "Fitted evidence does not bind the current interaction configuration.",
        )


def transform_interactions(
    frame: pd.DataFrame,
    fitted: Mapping[str, Any],
    *,
    features: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Transform parents, recompute semantics, then optionally scale outputs."""

    _validate_fitted(fitted)
    selected = tuple(features or fitted.get("features") or ())
    if any(feature not in set(fitted.get("features") or ()) for feature in selected):
        raise InteractionAuthorityError(
            "INTERACTION_FEATURE_NOT_FITTED",
            "Every requested interaction must be present in the frozen fold authority.",
        )
    required = required_input_columns(selected)
    _date_boundary(frame, operation="TRANSFORM")
    missing = [column for column in required if column not in frame]
    if missing:
        raise InteractionAuthorityError(
            "INTERACTION_TRANSFORM_INPUT_COLUMNS_MISSING",
            f"Interaction transform input is missing: {', '.join(missing)}.",
        )
    family = _normalize_model_family(str(fitted["modelFamily"]))
    semantic = _transform_semantic(
        frame.loc[:, _available_input_columns(frame, required, selected)],
        family=family,
        parent_parameters=dict(fitted.get("parentParameters") or {}),
        features=selected,
    )
    if bool(fitted.get("scaleInteractions")):
        for feature in selected:
            parameter = (fitted.get("scalerParameters") or {}).get(feature)
            if not isinstance(parameter, Mapping):
                raise InteractionAuthorityError(
                    "INTERACTION_FROZEN_SCALER_MISSING",
                    f"Frozen scaler evidence is missing for {feature}.",
                )
            semantic[f"{feature}__scaled"] = (
                semantic[feature].to_numpy(dtype=np.float64) - float(parameter["mean"])
            ) / float(parameter["scale"])
    return semantic


def transform_interaction(
    frame: pd.DataFrame, fitted: Mapping[str, Any], feature: str
) -> pd.DataFrame:
    return transform_interactions(frame, fitted, features=[feature])


def preprocessing_identity(fitted: Mapping[str, Any]) -> dict[str, Any]:
    """Return a content-addressed downstream binding without fitting a model."""

    _validate_fitted(fitted)
    family = _normalize_model_family(str(fitted["modelFamily"]))
    content = {
        "schemaVersion": PREPROCESSOR_SCHEMA_VERSION,
        "authorityId": fitted["authorityId"],
        "fittedInteractionId": fitted["fittedId"],
        "fittedInteractionChecksum": fitted["fittedChecksum"],
        "modelFamily": family,
        "parentTreatment": MODEL_FAMILY_RESOLUTION[family]["parentMissing"],
        "semanticRecomputation": "BEFORE_DOWNSTREAM_ENCODING_OR_SCALING",
        "downstreamScaling": MODEL_FAMILY_RESOLUTION[family]["downstreamScaling"],
        "scalingEnabled": bool(fitted["scaleInteractions"]),
        "targetRead": False,
        "modelFitCreated": False,
    }
    checksum = _sha256(content)
    return {
        **content,
        "checksum": checksum,
        "id": f"{PREPROCESSOR_SCHEMA_VERSION}:sha256:{checksum}",
    }


__all__ = [
    "AUTHORITY_NAME",
    "CONTEXT_FEATURE_VERSION",
    "DEVELOPMENT_END",
    "INTERACTION_FEATURES",
    "InteractionAuthorityError",
    "OPERATION_ORDER",
    "authority_checksum",
    "authority_configuration",
    "feature_binding",
    "fit_interaction_authority",
    "preprocessing_identity",
    "project_authority_manifest",
    "required_input_columns",
    "transform_interaction",
    "transform_interactions",
]
