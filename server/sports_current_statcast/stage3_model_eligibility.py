"""Governed Stage 3 model-feature eligibility for Current Gold.

The accepted contextual publication exposes 254 physical predictor columns, but
physical presence is not execution authority.  This module derives one
content-addressed, project-bound feature universe from the accepted feature
catalog and an explicit eligibility rule.  It never reads target values and it
never rewrites an immutable Gold or feature-set registration.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from ..sports_datasets.consumer import canonical_json_bytes
from . import stage3_feature_engineering as feature_engineering


MODEL_ELIGIBILITY_SCHEMA_VERSION = "SPORTS_STAGE3_MODEL_ELIGIBILITY_V1"
MODEL_ELIGIBILITY_RULE_VERSION = "CURRENT_GOLD_MODEL_ELIGIBILITY_2026_09_01_V2"

# These are not inferred from null counts alone.  The accepted contextual
# review explicitly records that historical game-end timestamp authority and
# venue-altitude authority do not exist for these fields.
SOURCE_UNAVAILABLE_FEATURES: dict[str, str] = {
    "batting_hours_since_previous_game_end": (
        "Historical prior-game end timestamps are not available in the governed source authority."
    ),
    "fielding_hours_since_previous_game_end": (
        "Historical prior-game end timestamps are not available in the governed source authority."
    ),
    "batting_altitude_change_feet": (
        "Versioned venue-altitude evidence is unavailable in the governed source authority."
    ),
    "fielding_altitude_change_feet": (
        "Versioned venue-altitude evidence is unavailable in the governed source authority."
    ),
    "batting_previous_game_duration_minutes": (
        "Prior-game duration is absent from the governed 2025–2026/current-era source contract and is not prospectively available."
    ),
    "fielding_previous_game_duration_minutes": (
        "Prior-game duration is absent from the governed 2025–2026/current-era source contract and is not prospectively available."
    ),
}

ALLOWED_PREDICTOR_ROLES = {
    "PREGAME_FEATURE",
    "MISSINGNESS_INDICATOR",
    "SIMULATION_GENERATED_STATE",
}

SIMULATOR_SUPPLIED_CONTRACT = "SIMULATOR_SUPPLIED_AT_FORECAST_TIME"


def _sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _leakage_contract_rejected(value: str) -> bool:
    normalized = value.strip().upper()
    if not normalized or normalized in {"NONE", "PASS", "POINT_IN_TIME_VALID"}:
        return False
    # Accepted catalog states use explicit negative declarations such as
    # NO_TARGET_OR_FUTURE_EVIDENCE.  Substring matching alone would invert
    # those contracts and exclude every safe predictor.
    if normalized.startswith(("NO_", "NOT_", "WITHOUT_", "LOW_ACCEPTED_")):
        return False
    if "NEVER_ACTUAL_TARGET_GAME_STATE" in normalized:
        return False
    return normalized.startswith(("TARGET_", "POST_EVENT_", "FUTURE_")) or (
        "LEAKAGE" in normalized and "NO_LEAKAGE" not in normalized
    )


def _classification(
    row: Mapping[str, Any],
    *,
    treatment_disposition: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    name = str(row.get("name") or "")
    role = str(row.get("role") or "")
    governance = str(row.get("governanceStatus") or "")
    availability = str(row.get("availabilityStatus") or "")
    missing = float(row.get("missingPercentDevelopment") or 0.0)
    leakage = str(row.get("leakageRisk") or "")
    treatment_status = ""
    governed_prior = False

    base = {
        "name": name,
        "order": int(row.get("order") or 0),
        "role": role,
        "dataType": row.get("dataType"),
        "featureFamily": row.get("featureFamily"),
        "missingPercentDevelopment": missing,
        "coldStartRelevance": row.get("coldStartRelevance"),
        "forecastTimeAvailability": row.get("forecastTimeAvailability"),
        "pointInTimeTreatment": row.get("pointInTimeTreatment"),
        "sourceLineage": row.get("sourceLineage"),
    }

    if treatment_disposition is not None:
        status = str(
            treatment_disposition.get("executable_status")
            or treatment_disposition.get("executableStatus")
            or ""
        )
        treatment_status = status
        governed_prior = (
            status in {"READY_GOVERNED_PRIOR_V1", "READY_GOVERNED_PRIOR_V2"}
            and treatment_disposition.get("preprocessing_executable") is True
            and bool(
                (
                    (treatment_disposition.get("execution_contract") or {})
                    .get("missing", {})
                    .get("priorAuthority")
                )
            )
        )
        if status == "DEFERRED_CONTEXT_AUTHORITY":
            return {
                **base,
                "eligible": False,
                "classification": "OTHER_GOVERNANCE",
                "status": status,
                "reason": "The Core Challenger scientific decision defers this field to a later contextual-authority wave.",
                "overrideAllowed": False,
                "transitivelyReachable": False,
            }
        if treatment_disposition.get("executable_selectable") is False and not governed_prior:
            return {
                **base,
                "eligible": False,
                "classification": "OTHER_GOVERNANCE",
                "status": status or "TREATMENT_NONSELECTABLE",
                "reason": str(
                    treatment_disposition.get("executable_resolution")
                    or treatment_disposition.get("executableResolution")
                    or "The adopted combined treatment authority holds this field nonselectable."
                ),
                "overrideAllowed": False,
            }

    # Explicit inactive governance (currently the unapproved rivalry mapping)
    # takes precedence over the coincident 100% physical-null rate.
    if governance != "ELIGIBLE":
        return {
            **base,
            "eligible": False,
            "classification": "OTHER_GOVERNANCE",
            "status": governance or "INACTIVE_GOVERNANCE",
            "reason": row.get("inactiveReason")
            or "The accepted feature authority does not activate this feature.",
            "overrideAllowed": False,
        }

    if role not in ALLOWED_PREDICTOR_ROLES:
        category = "IDENTITY" if role in {"IDENTIFIER", "GROUPING", "TIME"} else "PIT_LEAKAGE"
        return {
            **base,
            "eligible": False,
            "classification": category,
            "status": "ROLE_NOT_MODEL_ELIGIBLE",
            "reason": f"Feature role {role or 'UNDECLARED'} is not an authorized predictor role.",
            "overrideAllowed": False,
        }

    if "COMPUTATION_FAILURE" in availability or "COMPUTATION_FAILURE" in str(row.get("stateReason") or ""):
        return {
            **base,
            "eligible": False,
            "classification": "COMPUTATION_FAILURE",
            "status": "COMPUTATION_FAILURE_EXCLUDED",
            "reason": "The governed construction failed; ordinary imputation cannot create execution authority.",
            "overrideAllowed": False,
        }

    if name in SOURCE_UNAVAILABLE_FEATURES or "SOURCE_UNAVAILABLE" in availability:
        return {
            **base,
            "eligible": False,
            "classification": "SOURCE_UNAVAILABLE",
            "status": "SOURCE_UNAVAILABLE_EXCLUDED",
            "reason": SOURCE_UNAVAILABLE_FEATURES.get(
                name, "The required governed source authority is unavailable."
            ),
            "overrideAllowed": False,
        }

    # Leakage authority always outranks a missingness override.  A physically
    # sparse field must never become scientist-overridable when its accepted
    # point-in-time contract already says TARGET, POST_EVENT, or FUTURE.
    if _leakage_contract_rejected(leakage):
        return {
            **base,
            "eligible": False,
            "classification": "PIT_LEAKAGE",
            "status": "POINT_IN_TIME_CONTRACT_REJECTED",
            "reason": "The feature's accepted leakage state is incompatible with pregame development.",
            "overrideAllowed": False,
        }

    if governed_prior:
        return {
            **base,
            "eligible": True,
            "classification": "ELIGIBLE",
            "status": f"ELIGIBLE_{treatment_status}_POSTERIOR_MEAN_ONLY",
            "reason": "The raw statistic is a non-model evidence input; the registered fold-local governed posterior mean is the executable predictor.",
            "overrideAllowed": False,
            "requiresGovernedPriorTransformation": True,
        }

    if missing >= 100.0:
        return {
            **base,
            "eligible": False,
            "classification": "MISSINGNESS",
            "status": "ONE_HUNDRED_PERCENT_MISSING_EXCLUDED",
            "reason": "The feature is 100% missing in the development population.",
            "overrideAllowed": False,
        }
    if missing >= 95.0:
        return {
            **base,
            "eligible": False,
            "classification": "MISSINGNESS",
            "status": "REVIEW_REQUIRED_SEMANTIC_SPARSE",
            "reason": (
                "At least 95% of development values are physically missing and no approved semantic-null "
                "contract establishes that absence is a real category."
            ),
            "overrideAllowed": True,
            "overrideRequirements": [
                "writtenScientificRationale",
                "prospectiveSemanticCompatibility",
                "foldLocalTreatment",
            ],
        }
    if missing >= 80.0:
        return {
            **base,
            "eligible": False,
            "classification": "MISSINGNESS",
            "status": "REVIEW_REQUIRED_80_TO_95_PERCENT_MISSING",
            "reason": "The feature is 80%–95% physically missing in development.",
            "overrideAllowed": True,
        }
    if missing >= 50.0:
        return {
            **base,
            "eligible": False,
            "classification": "MISSINGNESS",
            "status": "REVIEW_REQUIRED_50_TO_80_PERCENT_MISSING",
            "reason": "The feature is 50%–80% physically missing and needs explicit scientific acceptance.",
            "overrideAllowed": True,
        }

    if role == "SIMULATION_GENERATED_STATE":
        if row.get("forecastTimeAvailability") != SIMULATOR_SUPPLIED_CONTRACT:
            return {
                **base,
                "eligible": False,
                "classification": "PIT_LEAKAGE",
                "status": "SIMULATOR_SUPPLY_CONTRACT_MISSING",
                "reason": "Simulation state is eligible only under an explicit simulator-supplied forecast contract.",
                "overrideAllowed": False,
            }
        return {
            **base,
            "eligible": True,
            "classification": "ELIGIBLE",
            "status": "ELIGIBLE_SIMULATOR_SUPPLIED_STATE",
            "reason": "The accepted forecast contract requires the simulator—not actual target-game evidence—to supply this state.",
            "overrideAllowed": False,
        }

    return {
        **base,
        "eligible": True,
        "classification": "ELIGIBLE",
        "status": (
            "ELIGIBLE_COLD_START_GOVERNED"
            if str(row.get("coldStartRelevance") or "").startswith("RELEVANT")
            else "ELIGIBLE"
        ),
        "reason": (
            "Cold-start evidence is retained under governed priors/indicators; it is not treated as an ordinary null."
            if str(row.get("coldStartRelevance") or "").startswith("RELEVANT")
            else "The feature is present, point-in-time valid, forecast-compatible, and below the default missingness threshold."
        ),
        "overrideAllowed": False,
    }


def build_model_eligibility(authority: Any) -> dict[str, Any]:
    """Derive the exact content-addressed Full Eligible authority."""

    source_rows, _ = feature_engineering._catalog(authority.eda_authority)
    # Derived model outputs must not mutate a shared physical-catalog snapshot.
    rows = [dict(row) for row in source_rows]
    combined = getattr(authority, "treatment_specification", None) or {}
    manifest = combined.get("manifest") or {}
    corrected_schema = None
    physical_candidate_count = len(rows)
    if manifest.get("semanticTreatmentVersion"):
        from . import stage3_corrected_treatment_spec as corrected

        if (
            manifest.get("semanticTreatmentVersion") != corrected.SEMANTIC_TREATMENT_VERSION
            or _sha(manifest) != combined.get("manifestChecksum")
        ):
            raise RuntimeError("Corrected model eligibility requires an authenticated adopted treatment manifest.")
        corrected_schema = manifest["modelFeatureSchema"]
        if _sha({key: value for key, value in corrected_schema.items() if key != "schemaChecksum"}) != corrected_schema["schemaChecksum"]:
            raise RuntimeError("The adopted corrected model feature schema failed its checksum.")
        by_name = {str(row["name"]): row for row in rows}
        for column in corrected_schema["columns"]:
            if column["feature"] in by_name:
                continue
            parent = by_name.get(column["sourceFeature"])
            if parent is None or column["sourceFeature"] not in corrected_schema["wave1SourceFeatures"]:
                raise RuntimeError("Corrected model output lacks its exact registered prior parent.")
            rows.append({
                **parent,
                "name": column["feature"],
                "order": len(rows) + 1,
                "dataType": column["dataType"],
                "binary": column["binary"],
                "role": "PREGAME_FEATURE",
                "governanceStatus": "ELIGIBLE",
                "availabilityStatus": "REGISTERED_FOLD_LOCAL_PRIOR_OUTPUT",
                "missingPercentDevelopment": None,
                "sourceLineage": {"parentFeature": column["sourceFeature"], "outputRole": column["role"], "modelFeatureSchemaChecksum": corrected_schema["schemaChecksum"]},
            })
    treatment_by_name = {
        str(item.get("feature_name") or item.get("featureName") or ""): item
        for item in manifest.get("features") or []
        if isinstance(item, Mapping)
    }
    for item in (manifest.get("reconciliation") or {}).get(
        "additionalBackendFeatures"
    ) or []:
        if isinstance(item, Mapping):
            treatment_by_name[str(item.get("featureName") or "")] = item
    decisions = [
        _classification(
            row, treatment_disposition=treatment_by_name.get(str(row.get("name") or ""))
        )
        for row in rows
    ]
    if corrected_schema:
        by_decision = {str(item["name"]): item for item in decisions}
        if not all(by_decision[name]["eligible"] for name in corrected_schema["orderedFeatures"]):
            raise RuntimeError("Corrected schema includes a source or output held closed by its governing authority.")
        for name in corrected_schema["wave1SourceFeatures"]:
            by_decision[name].update({
                "status": "ELIGIBLE_CORRECTED_WAVE1_VALID_RAW_PLUS_REGISTERED_OUTPUTS",
                "reason": "The corrected authority preserves valid raw values and separately registers required posterior, exposure, reliability, uncertainty, and state outputs.",
                "requiresGovernedPriorTransformation": False,
            })
        for column in corrected_schema["columns"]:
            if column["feature"] != column["sourceFeature"]:
                by_decision[column["feature"]]["missingPercentDevelopment"] = None
    eligible = [item for item in decisions if item["eligible"]]
    excluded = [item for item in decisions if not item["eligible"]]
    ordered = [str(item["name"]) for item in eligible]
    if corrected_schema:
        if set(ordered) != set(corrected_schema["orderedFeatures"]):
            raise RuntimeError("Corrected eligibility does not match its exact 273-column adopted schema.")
        ordered = list(corrected_schema["orderedFeatures"])
    classifications = Counter(str(item["classification"]) for item in excluded)

    reconciliation = {
        "physicalCandidateCount": physical_candidate_count,
        "eligiblePredictorCount": len(eligible),
        "excludedPredictorCount": len(excluded),
        "sourceUnavailable": classifications["SOURCE_UNAVAILABLE"],
        "missingness": classifications["MISSINGNESS"],
        "pitLeakage": classifications["PIT_LEAKAGE"],
        "identity": classifications["IDENTITY"],
        "computationFailure": classifications["COMPUTATION_FAILURE"],
        "other": classifications["OTHER_GOVERNANCE"],
    }
    if corrected_schema:
        reconciliation["registeredDerivedOutputCount"] = len(rows) - physical_candidate_count
        reconciliation["totalCandidateCount"] = len(decisions)
    if (
        reconciliation["physicalCandidateCount"] + reconciliation.get("registeredDerivedOutputCount", 0)
        != reconciliation["eligiblePredictorCount"] + reconciliation["excludedPredictorCount"]
        or reconciliation["excludedPredictorCount"]
        != sum(
            reconciliation[key]
            for key in (
                "sourceUnavailable",
                "missingness",
                "pitLeakage",
                "identity",
                "computationFailure",
                "other",
            )
        )
    ):
        raise RuntimeError("Model-eligibility counts do not reconcile.")

    payload = {
        "schemaVersion": MODEL_ELIGIBILITY_SCHEMA_VERSION,
        "ruleVersion": MODEL_ELIGIBILITY_RULE_VERSION,
        "authority": {
            "projectId": authority.eda_authority.project_id,
            "authorityKey": authority.authority_key,
            "sourceDatasetId": authority.eda_authority.source_dataset_id,
            "sourceManifestSha": authority.eda_authority.source_manifest_sha,
            "goldManifestSha": authority.eda_authority.gold_manifest_sha,
            "contextualManifestSha": authority.eda_authority.contextual_manifest_sha,
            "reviewDigest": authority.eda_authority.review_digest,
            "splitContractId": authority.split.get("contractId"),
            "splitVersion": int(authority.split.get("contractVersion") or 0),
            "splitChecksum": authority.split.get("checksum"),
            "outlierPolicyId": authority.outlier_policy.get("policyId"),
            "outlierPolicyVersion": int(authority.outlier_policy.get("policyVersion") or 0),
            "outlierPolicyChecksum": authority.outlier_policy.get("checksum"),
            "missingPolicyId": authority.missing_policy.get("policyId"),
            "missingPolicyVersion": int(authority.missing_policy.get("policyVersion") or 0),
            "missingPolicyChecksum": authority.missing_policy.get("checksum"),
            "treatmentSpecificationId": combined.get("specificationId"),
            "treatmentSpecificationVersion": int(
                combined.get("specificationVersion") or 0
            ),
            "treatmentSpecificationChecksum": combined.get("checksum"),
            "treatmentManifestChecksum": combined.get("manifestChecksum"),
        },
        "population": {
            "scope": "DEVELOPMENT_ONLY",
            "rows": 683_662,
            "startDate": "2023-03-30",
            "endDate": "2026-08-13",
            "finalOotRows": 14_067,
            "finalOotStartDate": "2026-08-14",
            "finalOotEndDate": "2026-08-27",
            "finalOotLocked": True,
            "finalOotTargetAccessed": False,
        },
        "orderedFeatures": ordered,
        "exclusions": excluded,
        "reconciliation": reconciliation,
        "rules": {
            "sourceUnavailable": "EXCLUDE_NO_IMPUTATION_OR_ZERO_FABRICATION",
            "computationFailure": "EXCLUDE_UNLESS_SEPARATELY_REVIEWED",
            "oneHundredPercentMissing": "EXCLUDE",
            "atLeastNinetyFivePercentMissing": "EXCLUDE_BY_DEFAULT_REVIEW_OVERRIDE_ONLY",
            "eightyToNinetyFivePercentMissing": "REVIEW_REQUIRED_DEFAULT_EXCLUDED",
            "fiftyToEightyPercentMissing": "EXPLICIT_ACCEPTANCE_REQUIRED_DEFAULT_EXCLUDED",
            "underFiftyPercentMissing": "NORMALLY_ELIGIBLE_FOLD_LOCAL_TREATMENT",
            "coldStart": "RETAIN_GOVERNED_PRIORS_AND_INDICATORS",
            "semanticSparse": "REQUIRE_REGISTERED_SEMANTIC_NULL_AUTHORITY",
            "deferredContextAuthority": "EXCLUDE_NO_TRANSITIVE_REACHABILITY",
            "simulationState": "ALLOW_ONLY_WHEN_SIMULATOR_SUPPLIED_CONTRACT_IS_EXACT",
        },
        "transformationContracts": {
            **feature_engineering._default_transformations(
                ordered, {str(row["name"]): row for row in rows}
            ),
            "ordered": [
                {
                    "feature": name,
                    "steps": (
                        ["GOVERNED_PRIOR_POSTERIOR_MEAN"]
                        if next(
                            item
                            for item in eligible
                            if str(item["name"]) == name
                        ).get("requiresGovernedPriorTransformation")
                        else feature_engineering._default_steps(
                            next(
                                row for row in rows if str(row["name"]) == name
                            )
                        )
                    ),
                }
                for name in ordered
            ],
        },
    }
    if corrected_schema:
        payload["semanticTreatmentVersion"] = manifest["semanticTreatmentVersion"]
        payload["modelFeatureSchemaChecksum"] = corrected_schema["schemaChecksum"]
        payload["transformationContracts"] = corrected.corrected_transformation_contracts({
            **manifest, "manifestChecksum": combined["manifestChecksum"]
        })
    checksum = _sha(payload)
    return {
        **payload,
        "featureSetId": f"stage3-full-eligible-modeling-set-{checksum[:32]}",
        "featureSetKey": "FULL_ELIGIBLE_MODELING_SET",
        "name": "Full Eligible Feature Set",
        "version": 2,
        "status": "GOVERNED_DERIVED_AUTHORITY",
        "authorityType": "CONTENT_ADDRESSED_PROJECT_MODELING_UNIVERSE",
        "checksum": checksum,
        "featureCount": len(ordered),
        "recommended": True,
        "default": True,
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "coldStartRowsDropped": False,
        "simulatorGeneratedStateFeatures": [
            str(item["name"])
            for item in eligible
            if item.get("role") == "SIMULATION_GENERATED_STATE"
        ],
    }


def assess_feature_set(
    feature_set: Mapping[str, Any], eligibility: Mapping[str, Any]
) -> dict[str, Any]:
    """Assess a preserved immutable registration against current execution authority."""

    excluded_by_name = {
        str(item["name"]): item
        for item in eligibility.get("exclusions", [])
    }
    ordered = [str(item) for item in feature_set.get("orderedFeatures") or []]
    eligible_names = set(str(item) for item in eligibility.get("orderedFeatures") or [])
    known_names = eligible_names | set(excluded_by_name)
    incompatible = [excluded_by_name[name] for name in ordered if name in excluded_by_name]
    expected_semantic_contract = eligibility.get("transformationContracts") or {}
    if expected_semantic_contract.get("semanticTreatmentVersion") and (
        dict(feature_set.get("transformationContracts") or {}) != dict(expected_semantic_contract)
        or ordered != list(eligibility.get("orderedFeatures") or [])
    ):
        incompatible.append({
            "name": "<corrected-treatment-contract>",
            "classification": "OTHER_GOVERNANCE",
            "status": "CORRECTED_TREATMENT_CONTRACT_REQUIRED",
            "reason": "Current corrected execution requires the exact adopted expanded feature schema; historical registrations remain preserved but are not silently reinterpreted.",
            "missingPercentDevelopment": None,
            "overrideAllowed": False,
        })
    if not ordered:
        incompatible.append(
            {
                "name": "<empty-feature-set>",
                "classification": "OTHER_GOVERNANCE",
                "status": "FEATURE_SET_EMPTY",
                "reason": "A supervised feature-set registration must contain at least one predictor.",
                "missingPercentDevelopment": 0.0,
                "overrideAllowed": False,
            }
        )
    duplicates = sorted({name for name in ordered if ordered.count(name) > 1})
    for name in duplicates:
        incompatible.append(
            {
                "name": name,
                "classification": "OTHER_GOVERNANCE",
                "status": "DUPLICATE_FEATURE_IDENTITY",
                "reason": "The immutable ordered feature contract contains a duplicate predictor.",
                "missingPercentDevelopment": 0.0,
                "overrideAllowed": False,
            }
        )
    for name in sorted(set(ordered) - known_names):
        incompatible.append(
            {
                "name": name,
                "classification": "OTHER_GOVERNANCE",
                "status": "FEATURE_AUTHORITY_UNKNOWN",
                "reason": "The predictor is absent from the exact current eligibility authority.",
                "missingPercentDevelopment": 0.0,
                "overrideAllowed": False,
            }
        )
    hard = [
        item
        for item in incompatible
        if item.get("classification")
        in {"SOURCE_UNAVAILABLE", "COMPUTATION_FAILURE", "PIT_LEAKAGE", "IDENTITY", "OTHER_GOVERNANCE"}
    ]
    review = [item for item in incompatible if item.get("classification") == "MISSINGNESS"]
    if hard:
        status = "NON_EXECUTABLE_CURRENT_AUTHORITY"
        executable = False
    elif review:
        status = "REVIEW_REQUIRED_DEFAULT_EXCLUDED"
        executable = False
    else:
        status = "EXECUTABLE"
        executable = True
    return {
        "featureSetId": feature_set.get("featureSetId"),
        "executionStatus": status,
        "executable": executable,
        "defaultEligible": bool(ordered) and not incompatible,
        "blockingFeatures": hard,
        "reviewRequiredFeatures": review,
        "overrideEligible": bool(review) and not hard,
        "overrideRequirements": (
            ["writtenScientificRationale", "prospectiveSemanticCompatibility", "foldLocalTreatment"]
            if review and not hard
            else []
        ),
        "historicalRegistrationPreserved": True,
        "immutableRegistrationMutated": False,
    }


def build_feature_set_record(eligibility: Mapping[str, Any]) -> dict[str, Any]:
    """Project the derived authority into the existing evaluator contract."""

    return {
        "featureSetId": eligibility["featureSetId"],
        "featureSetKey": eligibility["featureSetKey"],
        "name": eligibility["name"],
        "version": int(eligibility["version"]),
        "status": eligibility["status"],
        "checksum": eligibility["checksum"],
        "orderedFeatures": list(eligibility["orderedFeatures"]),
        "transformationContracts": dict(eligibility["transformationContracts"]),
        "unavailableExclusions": [
            str(item["name"]) for item in eligibility.get("exclusions", [])
        ],
    }


__all__ = [
    "MODEL_ELIGIBILITY_RULE_VERSION",
    "MODEL_ELIGIBILITY_SCHEMA_VERSION",
    "SOURCE_UNAVAILABLE_FEATURES",
    "assess_feature_set",
    "build_feature_set_record",
    "build_model_eligibility",
]
