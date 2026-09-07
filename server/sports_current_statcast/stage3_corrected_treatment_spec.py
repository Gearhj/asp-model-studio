"""Pure, opt-in successor schema for the authorized MLB treatment correction.

The immutable V14 manifest is the scientific predecessor. This module neither
loads feature payloads nor fits, registers, adopts, or evaluates anything.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..sports_datasets.consumer import canonical_json_bytes

SEMANTIC_TREATMENT_VERSION = "MLB_SEMANTIC_TREATMENT_V1"
CORRECTED_FEATURE_SET_KEY = "MLB_CORE_CHALLENGER_CORRECTED_V1"
REFERENCE_V14_ID = "stage3-feature-treatment-spec-cd6c877bc9474fa7ab2b716209321d78"
REFERENCE_V14_MANIFEST_SHA = "ba36557bb986f87be40dc18a4a669f4e5d4f979becf2d0e70fda5226f15f544d"
DECISION_PATH = Path(__file__).with_name("mlb_corrected_treatment_decision_v1.json")
WAVE1_OUTPUT_ROLES = (
    "posteriorMean", "effectiveN", "posteriorReliability", "posteriorStd", "historyState"
)


def content_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def correction_decision() -> dict[str, Any]:
    decision = json.loads(DECISION_PATH.read_text(encoding="utf-8"))
    if (
        decision.get("semanticTreatmentVersion") != SEMANTIC_TREATMENT_VERSION
        or decision.get("projectId") != "asp-mtlozhdx"
        or decision.get("predecessor", {}).get("manifestChecksum") != REFERENCE_V14_MANIFEST_SHA
        or decision.get("authorization", {}).get("sha256")
        != "61046f7c1465733f70623bb74533e050fbca8ed93a8c2fb55346e71afa6f1ae9"
    ):
        raise ValueError("The corrected-treatment user decision does not match its frozen authority.")
    diagnostic = decision.get("correctedRowEligibility", {}).get("diagnosticEvidence") or {}
    if diagnostic:
        repository_root = Path(__file__).resolve().parents[2]
        path = (repository_root / diagnostic["relativePath"]).resolve()
        if not path.is_relative_to(repository_root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != diagnostic["sha256"]:
            raise ValueError("The outcome-independent eligibility diagnostic failed its immutable content checksum.")
    return {**decision, "decisionChecksum": content_sha(decision)}


def _included(row: Mapping[str, Any]) -> bool:
    return row.get("executable_selectable") is True or (
        row.get("executable_status") == "READY_GOVERNED_PRIOR_V2"
        and row.get("preprocessing_executable") is True
    )


def build_model_feature_schema(base: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the exact 218-source prefix and append 55 registered V1 outputs."""
    rows = [row for row in base.get("features", []) if _included(row)]
    source_ordered = [str(row["feature_name"]) for row in rows]
    if len(source_ordered) != 218 or len(set(source_ordered)) != 218:
        raise ValueError("Corrected treatment requires the exact 218-source Core feature scope.")
    bindings = {
        str(binding["feature"]): binding
        for binding in base.get("priorAuthority", {}).get("bindings", [])
    }
    v1 = [name for name in source_ordered if bindings.get(name, {}).get("status") == "READY_GOVERNED_PRIOR_V1"]
    v2 = [name for name in source_ordered if bindings.get(name, {}).get("status") == "READY_GOVERNED_PRIOR_V2"]
    if len(v1) != 11 or len(v2) != 10:
        raise ValueError("Corrected treatment must preserve eleven V1 and ten V2 prior estimators.")
    columns: list[dict[str, Any]] = []
    for row in rows:
        name = str(row["feature_name"])
        categorical = row.get("data_type") == "categorical"
        boolean = (
            str(row.get("logical_domain") or "").startswith("{0,1}")
            or row.get("recommended_inclusion") == "INCLUDE_DERIVED_INDICATOR"
            or name == "matchup_platoon_advantage"
        )
        columns.append({
            "feature": name,
            "sourceFeature": name,
            "dataType": "categorical" if categorical else "numeric",
            "binary": boolean,
            "domain": "{0,1}" if name == "matchup_platoon_advantage" else row.get("logical_domain"),
            "role": "WAVE1_VALID_RAW" if name in v1 else "WAVE2_POSTERIOR_MEAN" if name in v2 else "SEMANTIC_SOURCE_FEATURE",
            "steps": ["CATEGORICAL_UNKNOWN", "ONE_HOT"] if categorical else ["SEMANTIC_BOOLEAN_PASSTHROUGH"] if boolean else ["SEMANTIC_NUMERIC_PASSTHROUGH"],
        })
    output_bindings: dict[str, dict[str, str]] = {}
    for name in v1:
        outputs = bindings[name].get("derivedOutputs") or {}
        output_bindings[name] = {}
        for role in WAVE1_OUTPUT_ROLES:
            output = outputs.get(role)
            if not isinstance(output, str) or not output:
                raise ValueError(f"Missing registered {role} output for {name}.")
            output_bindings[name][role] = output
            categorical = role == "historyState"
            columns.append({
                "feature": output,
                "sourceFeature": name,
                "dataType": "categorical" if categorical else "numeric",
                "binary": False,
                "domain": "REGISTERED_PRIOR_HISTORY_STATE" if categorical else "[0,1]" if role in {"posteriorMean", "posteriorReliability"} else ">=0",
                "role": role,
                "steps": ["CATEGORICAL_UNKNOWN", "ONE_HOT"] if categorical else ["SEMANTIC_NUMERIC_PASSTHROUGH"],
            })
    ordered = [column["feature"] for column in columns]
    if len(ordered) != 273 or len(set(ordered)) != 273:
        raise ValueError("The corrected model schema must contain exactly 273 distinct features.")
    schema = {
        "schemaVersion": "MLB_CORRECTED_MODEL_FEATURE_SCHEMA_V1",
        "semanticTreatmentVersion": SEMANTIC_TREATMENT_VERSION,
        "sourceOrderedFeatures": source_ordered,
        "orderedFeatures": ordered,
        "sourceFeatureCount": len(source_ordered),
        "modelFeatureCount": len(ordered),
        "wave1AddedOutputCount": 55,
        "wave1SourceFeatures": v1,
        "wave2SourceFeatures": v2,
        "governedPriorSourceFeatures": [name for name in source_ordered if name in v1 or name in v2],
        "wave1OutputBindings": output_bindings,
        "columns": columns,
    }
    from .stage3_corrected_eligibility import registered_policy
    schema["rowEligibilityPolicy"] = registered_policy()
    return {**schema, "schemaChecksum": content_sha(schema)}


def corrected_transformation_contracts(compiled: Mapping[str, Any]) -> dict[str, Any]:
    schema = compiled["modelFeatureSchema"]
    return {
        "semanticTreatmentVersion": SEMANTIC_TREATMENT_VERSION,
        "treatmentManifestChecksum": compiled["manifestChecksum"],
        "modelFeatureSchemaChecksum": schema["schemaChecksum"],
        "rowEligibilityPolicy": copy.deepcopy(schema["rowEligibilityPolicy"]),
        "fittingScope": "CHRONOLOGICAL_TRAINING_FOLD_ONLY",
        "fittingRule": "Fit semantic fallback, priors, and encoders on training rows only; freeze and transform validation without refitting.",
        "finalFitRule": "NOT_AUTHORIZED_BY_THIS_FIVE_FOLD_COMPARISON",
        "targetEncoding": "PROHIBITED",
        "globalImputation": "PROHIBITED",
        "sourceOrderedFeatures": list(schema["sourceOrderedFeatures"]),
        "governedPriorSourceFeatures": list(schema["governedPriorSourceFeatures"]),
        "wave1SourceFeatures": list(schema["wave1SourceFeatures"]),
        "wave2SourceFeatures": list(schema["wave2SourceFeatures"]),
        "wave1OutputBindings": copy.deepcopy(schema["wave1OutputBindings"]),
        "modelFeatureColumns": copy.deepcopy(schema["columns"]),
        "ordered": [{"feature": column["feature"], "steps": list(column["steps"])} for column in schema["columns"]],
        "parentOnlyAblationStatus": "DEFERRED_BY_EXPLICIT_USER_DECISION",
    }


def build_corrected_manifest(base: Mapping[str, Any], *, predecessor_id: str = REFERENCE_V14_ID) -> dict[str, Any]:
    """Build a deterministic descendant without modifying any predecessor object."""
    if predecessor_id != REFERENCE_V14_ID or content_sha(base) != REFERENCE_V14_MANIFEST_SHA:
        raise ValueError("The correction must descend from the exact authenticated V14 manifest.")
    result = copy.deepcopy(dict(base))
    decision = correction_decision()
    schema = build_model_feature_schema(base)
    excluded = [str(row["feature_name"]) for row in base["features"] if not _included(row)]
    if len(excluded) != 22:
        raise ValueError("The corrected treatment must preserve all 22 workbook exclusions.")
    result["semanticTreatmentVersion"] = SEMANTIC_TREATMENT_VERSION
    result["treatmentName"] = "MLB Core Challenger — Corrected Semantic Treatment"
    result["compilerVersion"] = "MLB_FEATURE_TREATMENT_COMPILER_CORRECTED_V1"
    result["correctedTreatmentDecision"] = decision
    result["modelFeatureSchema"] = schema
    result["sourceFeatureInventorySha256"] = base["featureInventorySha256"]
    result["featureInventorySha256"] = content_sha({
        "sourceFeatureInventorySha256": base["featureInventorySha256"],
        "modelFeatureSchemaChecksum": schema["schemaChecksum"],
    })
    result["correctedTreatment"] = {
        "predecessorSpecificationId": predecessor_id,
        "predecessorManifestChecksum": REFERENCE_V14_MANIFEST_SHA,
        "authorizationChecksum": decision["authorization"]["sha256"],
        "preservedExcludedWorkbookFeatures": excluded,
        "requiredExecutionOrder": ["VALIDATE_SOURCE_AND_POINT_IN_TIME", "RESOLVE_HISTORY_REASONS", "FIT_TRAINING_ONLY_PRIORS_AND_CONTEXT", "TRANSFORM_PARENTS", "RECOMPUTE_INTERACTIONS", "VALIDATE_OUTPUT_DOMAINS", "FIT_TRAINING_ONLY_ENCODING", "PERSIST_AND_VERIFY_RELOAD"],
        "parentOnlyAblations": "DEFERRED_BY_EXPLICIT_USER_DECISION",
        "invalidPriorFallback": "ERROR_OR_EXPLICIT_REVIEW_NEVER_ORDINARY_IMPUTATION",
        "modelSchemaCountBeforeOneHot": 273,
        "oneHotExpandedCount": "RECORDED_PER_FOLD_AFTER_TRAINING_ONLY_CATEGORY_FIT",
    }
    for row in result["features"]:
        if not _included(row):
            continue
        row["semantic_treatment_version"] = SEMANTIC_TREATMENT_VERSION
        contract = row["execution_contract"]
        contract["semanticTreatmentVersion"] = SEMANTIC_TREATMENT_VERSION
        contract["invalidSourceOrComputation"] = "ERROR_OR_EXPLICIT_REVIEW_NO_ORDINARY_IMPUTATION"
        if row["feature_name"] == "matchup_platoon_advantage":
            row["source_model_handling"] = row["model_handling"]
            row["model_handling"] = "Deterministic matchup Boolean; validate parents and 0/1 domain; no Bayesian prior, scaling, or statistical imputation."
            row["approved_deviation"] = {
                "decisionId": decision["decisionId"],
                "authorizationChecksum": decision["authorization"]["sha256"],
                "resolution": "CORRECT_INCONSISTENT_PLAYER_RATE_WORDING_TO_DETERMINISTIC_MATCHUP_BOOLEAN",
            }
            contract["modelFamilyResolution"] = {"treeNativeMissing": "VALIDATED_MATCHUP_BOOLEAN", "denseMatrix": "VALIDATED_MATCHUP_BOOLEAN"}
        if "interaction" in str(row.get("semantic_class") or "").lower() or row.get("recommended_inclusion") == "RECOMPUTE_AFTER_PARENT_TREATMENT":
            contract["parentOnlyAblationStatus"] = "DEFERRED_BY_EXPLICIT_USER_DECISION"
    result["executionSummary"].update({
        "selectedSourceFeatures": 218,
        "selectedModelFeatures": 273,
        "wave1AddedModelOutputs": 55,
        "preservedWorkbookExclusions": 22,
        "parentOnlyAblationsDeferred": True,
    })
    return result


__all__ = ["SEMANTIC_TREATMENT_VERSION", "CORRECTED_FEATURE_SET_KEY", "REFERENCE_V14_ID", "REFERENCE_V14_MANIFEST_SHA", "build_corrected_manifest", "build_model_feature_schema", "corrected_transformation_contracts", "correction_decision", "content_sha"]
