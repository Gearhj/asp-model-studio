"""Canonical project-bound MLB feature-treatment specification service.

The checked-in JSON is the deterministic compilation of the reviewed source
workbook.  It is deliberately not another feature registry: every request
reconciles those recommendations by exact natural key against the same live
Stage 3 feature catalog used by Data Profile, Outliers, Missing Values,
Feature Engineering, and Model Laboratory.

This module is configuration-only.  It does not scan final-OOT rows, fit a
preprocessor or outcome model, call a provider, score, calibrate, promote, or
mutate Source/Gold data.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..persistence.db import Database
from ..persistence.repositories.stage3_treatment_repository import (
    Stage3TreatmentPersistenceError,
    Stage3TreatmentRepository,
)
from ..sports_datasets.consumer import canonical_json_bytes
from . import stage3_eda as eda
from . import stage3_interaction_recomputation_authority as interaction_authority
from . import stage3_player_prior_authority as player_prior
from . import stage3_player_prior_authority_v2 as player_prior_v2
from . import stage3_player_prior_resolution_v2 as player_prior_resolution_v2
from . import stage3_treatments as treatments
from . import sufficient_stats


SCHEMA_VERSION = "ASP_MLB_FEATURE_TREATMENT_SPECIFICATION_V1"
SPECIFICATION_KEY = "MLB_FEATURE_TREATMENT_SPEC_V1"
SOURCE_PATH = Path(__file__).with_name("mlb_feature_treatment_spec_v1.json")

EXPECTED_DISPOSITION_COUNTS: Mapping[str, int] = {
    "EXCLUDE_UNTIL_SOURCE_REPAIRED": 4,
    "EXCLUDE_UNTIL_COVERAGE_REPAIRED": 2,
    "RECODE_AFTER_SEMANTIC_VALIDATION": 1,
    "RECODE_AFTER_CALENDAR_VALIDATION": 1,
    "HIERARCHICAL_PRIOR_PLUS_INDICATOR": 23,
    "COLD_START_EXPOSURE_ENCODING": 2,
    "ROLE_OR_LEAGUE_PRIOR_PLUS_INDICATOR": 1,
    "NO_PRIOR_GAME_STATE_PLUS_FOLD_LOCAL_FILL": 22,
    "RECOMPUTE_AFTER_PARENT_TREATMENT": 8,
    "STRUCTURAL_ZERO_PLUS_INDICATOR": 8,
    "INCLUDE_DERIVED_INDICATOR": 42,
    "SIMULATOR_REQUIRED": 5,
    "NO_MISSING_TREATMENT": 121,
}

# These records are present in the accepted 254-field contextual publication
# but absent from the reviewed 240-row workbook.  Their absence is explained
# by the unapproved rivalry-mapping authority.  They are reconciled explicitly
# and held closed; no treatment is inferred by analogy.
EXPECTED_ADDITIONAL_FEATURES = (
    "batting_rivalry_pair",
    "batting_rivalry_game",
    "batting_home_rivalry_game",
    "batting_friday_night_home_rivalry",
    "batting_weekend_home_rivalry",
    "batting_home_x_rivalry",
    "batting_rivalry_mapping_missing",
    "fielding_rivalry_pair",
    "fielding_rivalry_game",
    "fielding_home_rivalry_game",
    "fielding_friday_night_home_rivalry",
    "fielding_weekend_home_rivalry",
    "fielding_home_x_rivalry",
    "fielding_rivalry_mapping_missing",
)

# These are negative, read-only authority findings for the two reviewed
# semantic rows.  Neither record is made executable: the landed schedule is
# deterministic, but its historical snapshots do not preserve original
# pregame knowledge timestamps, while the embedded holiday rules are not a
# separately registered/effective-dated calendar authority.  Keeping the
# exact finding beside the compiler prevents a generic missing-value default
# from being mistaken for scientific resolution.
_SEMANTIC_AUTHORITY_DECISIONS: Mapping[str, Mapping[str, Any]] = {
    "doubleheader_game_number": {
        "status": "BLOCKED_POINT_IN_TIME_UNPROVEN",
        "resolution": "HOLD_UNTIL_PREGAME_SCHEDULE_SEQUENCE_AUTHORITY_IS_REGISTERED",
        "blockedReason": (
            "Schedule authority MLB_CURRENT_STATCAST_SCHEDULE_AUTHORITY_V1 does not "
            "preserve original pregame knowledge timestamps or an independent "
            "{0,1,2} doubleheader-sequence invariant tied to scheduled start order."
        ),
        "sourceAuthority": "MLB_CURRENT_STATCAST_SCHEDULE_AUTHORITY_V1",
        "sourceAuthoritySha256": "44c43a48dda5895dcc19417a1c51b18ccdaed9dd83b3c1b8d50826e42be69c4d",
        "requiredSemantics": {
            "0": "VERIFIED_NOT_A_DOUBLEHEADER",
            "1": "VERIFIED_FIRST_DOUBLEHEADER_GAME",
            "2": "VERIFIED_SECOND_DOUBLEHEADER_GAME",
            "unknown": "HELD_NONEXECUTABLE",
        },
        "forbiddenTreatment": "MEDIAN_IMPUTATION",
    },
    "holiday_name": {
        "status": "BLOCKED_CALENDAR_AUTHORITY_UNAVAILABLE",
        "resolution": "HOLD_UNTIL_EFFECTIVE_DATED_VENUE_REGION_CALENDAR_AUTHORITY_IS_REGISTERED",
        "blockedReason": (
            "US_CA_ON_BASEBALL_CALENDAR_V1 is embedded code rather than a separately "
            "registered, sourced, effective-dated holiday calendar; null currently "
            "cannot prove NONE rather than UNKNOWN_HOLIDAY for every venue region."
        ),
        "sourceAuthority": "MLB_CONTEXT_STATIC_AUTHORITY_V1",
        "sourceAuthoritySha256": "da9740dd90a161202d42ba18d3c89f2569e3711e33b48f86bf3bd0a8a6f2d56d",
        "embeddedRulesVersion": "US_CA_ON_BASEBALL_CALENDAR_V1",
        "requiredSemantics": {
            "holiday": "EXACT_REGISTERED_HOLIDAY_NAME",
            "none": "VERIFIED_NON_HOLIDAY",
            "unknown": "UNKNOWN_HOLIDAY_HELD_NONEXECUTABLE",
        },
        "forbiddenTreatment": "MODE_IMPUTATION",
    },
}

_RIVALRY_PROPOSAL_PATH = Path(__file__).parents[2] / "docs" / "MLB_RIVALRY_MAPPING_PROPOSAL_V1.json"
_RIVALRY_FORMULAS: Mapping[str, str] = {
    "rivalry_pair": "None if mapping_missing else int({team_id, opponent_team_id} in approved_pairs)",
    "rivalry_game": "rivalry_pair",
    "home_rivalry_game": "None if rivalry_pair is None else rivalry_pair * int(is_home)",
    "friday_night_home_rivalry": (
        "None if rivalry_pair is None else rivalry_pair * int(is_home) * "
        "int(local_day_of_week == FRIDAY) * int(local_start_hour >= 18)"
    ),
    "weekend_home_rivalry": (
        "None if rivalry_pair is None else rivalry_pair * int(is_home) * "
        "int(local_day_of_week in {SATURDAY, SUNDAY})"
    ),
    "home_x_rivalry": "None if rivalry_pair is None else int(is_home) * rivalry_pair",
    "rivalry_mapping_missing": "int(rivalry_mapping_authority_status != APPROVED)",
}

_BLOCKED_DISPOSITIONS = frozenset(
    {
        "RECODE_AFTER_SEMANTIC_VALIDATION",
        "RECODE_AFTER_CALENDAR_VALIDATION",
        "HIERARCHICAL_PRIOR_PLUS_INDICATOR",
        "ROLE_OR_LEAGUE_PRIOR_PLUS_INDICATOR",
        "RECOMPUTE_AFTER_PARENT_TREATMENT",
        "REVIEW_REQUIRED",
    }
)
_EXCLUDED_DISPOSITIONS = frozenset(
    {
        "EXCLUDE_UNTIL_SOURCE_REPAIRED",
        "EXCLUDE_UNTIL_COVERAGE_REPAIRED",
        "EXCLUDE_BY_DEFAULT",
    }
)
_FALLBACK_DISPOSITIONS = frozenset({"NO_PRIOR_GAME_STATE_PLUS_FOLD_LOCAL_FILL"})
_ZERO_WITH_INDICATOR_DISPOSITIONS = frozenset(
    {"COLD_START_EXPOSURE_ENCODING", "STRUCTURAL_ZERO_PLUS_INDICATOR"}
)


class Stage3FeatureTreatmentSpecError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)

    def public_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _normalized_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _source_without_identity(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in source.items()
        if key not in {"source_content_sha256", "source_artifact_id"}
    }


def load_source_specification(path: Path = SOURCE_PATH) -> dict[str, Any]:
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_SOURCE_UNAVAILABLE",
            "The canonical MLB feature-treatment source artifact cannot be read.",
            status_code=503,
        ) from exc
    if not isinstance(source, dict):
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_SOURCE_INVALID", "The canonical source artifact must be an object."
        )
    expected = str(source.get("source_content_sha256") or "")
    actual = _sha256(_source_without_identity(source))
    if expected != actual:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_SOURCE_CHECKSUM_MISMATCH",
            "The canonical feature-treatment source artifact failed its content-address check.",
        )
    if source.get("specification_key") != SPECIFICATION_KEY:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_SOURCE_INVALID", "The canonical source artifact has the wrong specification key."
        )
    rows = source.get("features")
    if not isinstance(rows, list) or len(rows) != 240:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_SOURCE_ROW_COUNT_INVALID",
            "The canonical source artifact must contain exactly 240 feature recommendations.",
        )
    names = [str(row.get("feature_name") or "") for row in rows if isinstance(row, Mapping)]
    duplicates = sorted(name for name, count in Counter(names).items() if name and count > 1)
    if len(names) != 240 or any(not name for name in names) or duplicates:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_SOURCE_KEY_INVALID",
            "The canonical source contains blank, duplicate, or malformed feature natural keys.",
        )
    counts = Counter(str(row.get("recommended_inclusion") or "") for row in rows)
    if dict(counts) != dict(EXPECTED_DISPOSITION_COUNTS):
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_DISPOSITION_COUNTS_INVALID",
            "The canonical source disposition counts do not reconcile to the reviewed workbook.",
        )
    if any(row.get("reviewer_decision") or row.get("reviewer_notes") for row in rows):
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_SOURCE_REVIEW_FIELDS_INVALID",
            "Reviewer fields are draft overlays and must be blank in the scientific source artifact.",
        )
    return source


def _execution_contract(
    feature_name: str,
    disposition: str,
    *,
    prior_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if disposition in _EXCLUDED_DISPOSITIONS:
        return {
            "executableStatus": "READY",
            "executable": True,
            "selectable": False,
            "resolution": "EXCLUDE_FEATURE_WITHOUT_VALUE_REWRITE_OR_OUTLIER_FIT",
            "blockedReason": None,
            "treeModel": "EXCLUDED",
            "denseModel": "EXCLUDED",
            "fallbackLabel": None,
        }
    if disposition in {
        "RECODE_AFTER_SEMANTIC_VALIDATION",
        "RECODE_AFTER_CALENDAR_VALIDATION",
    }:
        semantic = _SEMANTIC_AUTHORITY_DECISIONS.get(feature_name)
        return {
            "executableStatus": "BLOCKED",
            "executable": False,
            "selectable": False,
            "resolution": (
                str(semantic["resolution"])
                if semantic
                else "HOLD_NONEXECUTABLE_UNTIL_REGISTERED_SEMANTIC_VALIDATION"
            ),
            "blockedReason": (
                str(semantic["blockedReason"])
                if semantic
                else "The required semantic/calendar validation authority is not registered."
            ),
            "treeModel": "EXCLUDED_PENDING_SEMANTIC_AUTHORITY",
            "denseModel": "EXCLUDED_PENDING_SEMANTIC_AUTHORITY",
            "fallbackLabel": None,
        }
    if disposition in {
        "HIERARCHICAL_PRIOR_PLUS_INDICATOR",
        "ROLE_OR_LEAGUE_PRIOR_PLUS_INDICATOR",
    }:
        binding = (
            dict(prior_binding)
            if prior_binding is not None
            else player_prior.feature_binding(feature_name)
        )
        if binding and binding["executable"]:
            binding_status = str(binding.get("status") or "")
            output_contract = binding.get("outputContract") or {}
            raw_selectable = bool(
                output_contract.get("rawFeatureSelectable", binding.get("selectable", True))
            )
            is_wave2 = binding_status == player_prior_v2.READY_GOVERNED_PRIOR_V2
            return {
                "executableStatus": binding_status,
                "executable": True,
                "preprocessingExecutable": True,
                "selectable": raw_selectable,
                "resolution": (
                    "EXECUTE_GOVERNED_SHARED_WAVE2_EMPIRICAL_BAYES_PRIOR_OUTPUT_FAMILY"
                    if is_wave2
                    else "EXECUTE_GOVERNED_PLAYER_TO_MLB_LEAGUE_EMPIRICAL_BAYES_PRIOR"
                ),
                "blockedReason": None,
                "treeModel": (
                    "WAVE2_DERIVED_OUTPUTS_REQUIRE_LATER_REGISTERED_FEATURE_SET_ABLATION"
                    if is_wave2
                    else "RETAIN_RAW_PLUS_GOVERNED_POSTERIOR_EFFECTIVE_N_RELIABILITY_AND_STATE"
                ),
                "denseModel": (
                    "WAVE2_DERIVED_OUTPUTS_REQUIRE_LATER_REGISTERED_FEATURE_SET_ABLATION"
                    if is_wave2
                    else "GOVERNED_POSTERIOR_EFFECTIVE_N_RELIABILITY_AND_STATE_WITH_TRAINING_ONLY_SCALING"
                ),
                "fallbackLabel": None,
            }
        binding_status = str((binding or {}).get("status") or "")
        if binding_status == "BINDING_READY_REQUIRES_WAVE2_ENGINE":
            return {
                "executableStatus": binding_status,
                "executable": False,
                "selectable": False,
                "resolution": "VALIDATED_SUFFICIENT_STATISTIC_BINDING_AWAITS_WAVE2_ESTIMATOR",
                "blockedReason": None,
                "treeModel": "EXCLUDED_PENDING_WAVE2_PRIOR_ENGINE",
                "denseModel": "EXCLUDED_PENDING_WAVE2_PRIOR_ENGINE",
                "fallbackLabel": None,
            }
        if binding_status == "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION":
            return {
                "executableStatus": binding_status,
                "executable": False,
                "selectable": False,
                "resolution": "SCIENTIFICALLY_RETIRED_PRESERVE_DEFINITION_AND_AUDIT_EVIDENCE",
                "blockedReason": None,
                "treeModel": "RETIRED_NONSELECTABLE",
                "denseModel": "RETIRED_NONSELECTABLE",
                "fallbackLabel": None,
            }
        return {
            "executableStatus": "BLOCKED",
            "executable": False,
            "selectable": False,
            "resolution": "HOLD_NONEXECUTABLE_UNTIL_GOVERNED_PRIOR_AUTHORITY_EXISTS",
            "blockedReason": (
                str(binding["blockedReason"])
                if binding
                else "No exact governed feature binding exists in the player-prior authority."
            ),
            "treeModel": "NO_NATIVE_MISSING_SUBSTITUTION_IS_CLAIMED_AS_A_PRIOR",
            "denseModel": "NO_MEDIAN_SUBSTITUTION_IS_CLAIMED_AS_A_PRIOR",
            "fallbackLabel": None,
        }
    if disposition == "RECOMPUTE_AFTER_PARENT_TREATMENT":
        binding = interaction_authority.feature_binding(feature_name)
        if binding and binding.get("executableStatus") == "READY_GOVERNED_INTERACTION_V1":
            return {
                "executableStatus": "READY_GOVERNED_INTERACTION_V1",
                "executable": True,
                "selectable": True,
                "resolution": "EXECUTE_PARENT_FIRST_FOLD_LOCAL_INTERACTION_RECOMPUTATION_V1",
                "blockedReason": None,
                "treeModel": "TREAT_PARENTS_WITH_NATIVE_MISSING_THEN_RECOMPUTE_NO_SCALING",
                "denseModel": "TREAT_PARENTS_WITH_FROZEN_FOLD_PARAMETERS_THEN_RECOMPUTE_THEN_OPTIONAL_SCALE",
                "fallbackLabel": None,
            }
        return {
            "executableStatus": "BLOCKED",
            "executable": False,
            "selectable": False,
            "resolution": "HOLD_UNTIL_PARENT_FIRST_FOLD_LOCAL_RECOMPUTATION_IS_REGISTERED",
            "blockedReason": (
                "No exact formula and ordered-parent binding exists in "
                "MLB_INTERACTION_RECOMPUTATION_AUTHORITY_V1."
            ),
            "treeModel": "EXCLUDED_PENDING_PARENT_LINEAGE_EXECUTOR",
            "denseModel": "EXCLUDED_PENDING_PARENT_LINEAGE_EXECUTOR",
            "fallbackLabel": None,
        }
    if disposition in _FALLBACK_DISPOSITIONS:
        return {
            "executableStatus": "READY_WITH_EXPLICIT_FALLBACK",
            "executable": True,
            "selectable": True,
            "resolution": "MODEL_FAMILY_SPECIFIC_NO_PRIOR_GAME_FALLBACK_WITH_INDICATOR",
            "blockedReason": None,
            "treeModel": "RETAIN_NAN_FOR_NATIVE_MISSING_ROUTING_WITH_REASON_INDICATOR",
            "denseModel": "TRAINING_FOLD_LOCAL_CONTEXTUAL_FILL_WITH_REASON_INDICATOR",
            "fallbackLabel": "INTERIM_TECHNICAL_FALLBACK",
        }
    if disposition in _ZERO_WITH_INDICATOR_DISPOSITIONS:
        return {
            "executableStatus": "READY",
            "executable": True,
            "selectable": True,
            "resolution": "SEMANTIC_ZERO_FOR_TRUE_NO_HISTORY_ONLY_WITH_INDICATOR",
            "blockedReason": None,
            "treeModel": "SEMANTIC_ZERO_PLUS_REASON_INDICATOR",
            "denseModel": "SEMANTIC_ZERO_PLUS_REASON_INDICATOR",
            "fallbackLabel": None,
        }
    if disposition == "INCLUDE_DERIVED_INDICATOR":
        return {
            "executableStatus": "READY",
            "executable": True,
            "selectable": True,
            "resolution": "DETERMINISTIC_BOOLEAN_RECOMPUTATION_NO_STATISTICAL_IMPUTATION",
            "blockedReason": None,
            "treeModel": "BOOLEAN_PASSTHROUGH_WITH_SOURCE_ERA_MONITORING",
            "denseModel": "BOOLEAN_PASSTHROUGH_WITH_SOURCE_ERA_MONITORING",
            "fallbackLabel": None,
        }
    if disposition == "SIMULATOR_REQUIRED":
        return {
            "executableStatus": "READY",
            "executable": True,
            "selectable": True,
            "resolution": "REQUIRE_VALID_SIMULATOR_STATE_NO_IMPUTATION",
            "blockedReason": None,
            "treeModel": "SIMULATOR_SUPPLIED_STATE_ONLY",
            "denseModel": "SIMULATOR_SUPPLIED_STATE_ONLY",
            "fallbackLabel": None,
        }
    if disposition == "NO_MISSING_TREATMENT":
        return {
            "executableStatus": "READY",
            "executable": True,
            "selectable": True,
            "resolution": "RETAIN_WITH_SEMANTIC_DOMAIN_VALIDATION_NO_UNNECESSARY_FILL",
            "blockedReason": None,
            "treeModel": "RETAIN_RAW_VALID_STATE",
            "denseModel": "RETAIN_RAW_VALID_STATE_WITH_FOLD_LOCAL_SCALING_WHEN_REQUESTED",
            "fallbackLabel": None,
        }
    return {
        "executableStatus": "BLOCKED",
        "executable": False,
        "selectable": False,
        "resolution": "HOLD_FOR_EXPLICIT_SCIENTIFIC_REVIEW",
        "blockedReason": f"Disposition {disposition or '<blank>'} has no registered executable mapping.",
        "treeModel": "EXCLUDED",
        "denseModel": "EXCLUDED",
        "fallbackLabel": None,
    }


def _inventory_identity(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": "STAGE3_FEATURE_INVENTORY_IDENTITY_V1",
        "features": [
            {
                "order": int(row["order"]),
                "name": str(row["name"]),
                "featureFamily": str(row.get("featureFamily") or ""),
                "dataType": str(row.get("dataType") or ""),
                "role": str(row.get("role") or ""),
                "core": bool(row.get("core")),
                "contextual": bool(row.get("contextual")),
                "governanceStatus": str(row.get("governanceStatus") or ""),
                "eligible": bool(row.get("eligible")),
                "availabilityStatus": str(row.get("availabilityStatus") or ""),
                "sourceLineage": str(row.get("sourceLineage") or ""),
                "coverageDevelopment": float(row.get("coverageDevelopment") or 0.0),
            }
            for row in rows
        ],
    }


def _interaction_parents(feature_name: str) -> list[str]:
    binding = interaction_authority.feature_binding(feature_name)
    return list(binding["orderedParents"]) if binding else []


def _paired_indicators(feature_name: str, disposition: str) -> list[str]:
    if feature_name.startswith("batter_last100_"):
        indicators = ["batter_last100_insufficient"]
        if feature_name.endswith(("whiff_rate", "contact_rate")):
            indicators.append("batter_last100_whiff_missing")
        return indicators
    if feature_name.startswith("pitcher_last250_"):
        indicators = ["pitcher_last250_insufficient"]
        if feature_name.endswith("whiff_rate"):
            indicators.append("pitcher_last250_whiff_missing")
        if feature_name.endswith("avg_fastball_velocity"):
            indicators.append("pitcher_last250_velocity_missing")
        return indicators
    if feature_name.startswith("batter_") and disposition in {
        "HIERARCHICAL_PRIOR_PLUS_INDICATOR",
        "ROLE_OR_LEAGUE_PRIOR_PLUS_INDICATOR",
        "COLD_START_EXPOSURE_ENCODING",
    }:
        return ["batter_prior_missing"]
    if feature_name.startswith("pitcher_") and disposition in {
        "HIERARCHICAL_PRIOR_PLUS_INDICATOR",
        "ROLE_OR_LEAGUE_PRIOR_PLUS_INDICATOR",
        "COLD_START_EXPOSURE_ENCODING",
    }:
        return ["pitcher_prior_missing"]
    if feature_name.startswith("batting_") and disposition in (
        _FALLBACK_DISPOSITIONS | _ZERO_WITH_INDICATOR_DISPOSITIONS
    ):
        return ["batting_previous_game_missing"]
    if feature_name.startswith("fielding_") and disposition in (
        _FALLBACK_DISPOSITIONS | _ZERO_WITH_INDICATOR_DISPOSITIONS
    ):
        return ["fielding_previous_game_missing"]
    return []


def _outlier_detector(source_row: Mapping[str, Any], backend: Mapping[str, Any]) -> str:
    name = str(source_row["feature_name"])
    disposition = str(source_row["recommended_inclusion"])
    if disposition in _EXCLUDED_DISPOSITIONS:
        return "NOT_APPLICABLE_EXCLUDED"
    if disposition == "RECOMPUTE_AFTER_PARENT_TREATMENT":
        return "VALIDATE_PARENTS_THEN_RECOMPUTE"
    if backend.get("simulationGeneratedState"):
        return "STATE_MACHINE_VALIDATION"
    if "RATE" in str(source_row.get("semantic_class") or "").upper():
        return "PHYSICAL_BOUNDS_AND_DENOMINATOR_VALIDATION"
    if backend.get("binary"):
        return "REGISTERED_BOOLEAN_DOMAIN_VALIDATION"
    if str(backend.get("dataType")) == "categorical":
        return "ALLOWED_CATEGORY_SEMANTIC_VALIDATION"
    if name.endswith(("_sin", "_cos")):
        return "HARD_BOUNDS_MINUS_ONE_TO_ONE"
    if any(token in name for token in ("_rate", "_usage", "_avg", "_obp", "_slg")):
        return "PHYSICAL_BOUNDS_AND_DENOMINATOR_VALIDATION"
    return "REGISTERED_SEMANTIC_DOMAIN_VALIDATION"


def _structured_execution_contract(
    source_row: Mapping[str, Any],
    backend: Mapping[str, Any],
    execution: Mapping[str, Any],
    *,
    prior_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    name = str(source_row["feature_name"])
    disposition = str(source_row["recommended_inclusion"])
    parents = _interaction_parents(name) if disposition == "RECOMPUTE_AFTER_PARENT_TREATMENT" else []
    indicators = _paired_indicators(name, disposition)
    prior_binding = (
        dict(prior_binding)
        if prior_binding is not None
        else player_prior.feature_binding(name)
    )
    prior_status = str((prior_binding or {}).get("status") or "")
    prior_executable = bool((prior_binding or {}).get("executable"))
    executable_prior_outputs = (
        dict(prior_binding.get("derivedOutputs") or {})
        if prior_binding and prior_executable
        else {}
    )
    interaction_binding = (
        interaction_authority.feature_binding(name)
        if disposition == "RECOMPUTE_AFTER_PARENT_TREATMENT"
        else None
    )
    if disposition in _EXCLUDED_DISPOSITIONS:
        missing_strategy = "DROP_VARIABLE_NO_VALUE_REWRITE"
    elif disposition in {
        "HIERARCHICAL_PRIOR_PLUS_INDICATOR",
        "ROLE_OR_LEAGUE_PRIOR_PLUS_INDICATOR",
    }:
        if execution["executable"]:
            missing_strategy = (
                "GOVERNED_SHARED_EMPIRICAL_BAYES_PRIOR_V2"
                if prior_status == player_prior_v2.READY_GOVERNED_PRIOR_V2
                else "GOVERNED_PLAYER_TO_MLB_LEAGUE_BETA_BINOMIAL_PRIOR_V1"
            )
        elif execution["executableStatus"] == "BLOCKED":
            missing_strategy = "GOVERNED_PRIOR_REQUIRED_EXACT_SUFFICIENT_STATISTIC_UNAVAILABLE"
        elif prior_status == "BINDING_READY_REQUIRES_WAVE2_ENGINE":
            missing_strategy = "HOLD_FOR_WAVE2_ENGINE_NO_VALUE_SUBSTITUTION"
        elif prior_status == "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION":
            missing_strategy = "DROP_RETIRED_VARIABLE_NO_VALUE_REWRITE"
        else:
            missing_strategy = "HOLD_NONEXECUTABLE_WITHOUT_VALUE_SUBSTITUTION"
    elif not execution["selectable"]:
        missing_strategy = "HOLD_NONEXECUTABLE_WITHOUT_VALUE_SUBSTITUTION"
    elif disposition in _ZERO_WITH_INDICATOR_DISPOSITIONS:
        missing_strategy = "SEMANTIC_ZERO_FOR_TRUE_NO_HISTORY_PLUS_INDICATOR"
    elif disposition in _FALLBACK_DISPOSITIONS:
        missing_strategy = "TREE_NATIVE_MISSING_OR_DENSE_FOLD_LOCAL_CONTEXTUAL_FILL"
    elif disposition == "INCLUDE_DERIVED_INDICATOR":
        missing_strategy = "DETERMINISTIC_RECOMPUTATION_NO_STATISTICAL_IMPUTATION"
    elif disposition == "SIMULATOR_REQUIRED":
        missing_strategy = "SIMULATOR_SUPPLIED_NO_IMPUTATION"
    else:
        missing_strategy = "NO_MISSING_TREATMENT"
    return {
        "selectable": bool(execution["selectable"]),
        "executable": bool(execution["executable"]),
        "preprocessingExecutable": bool(
            execution.get("preprocessingExecutable", execution["selectable"])
        ),
        "rawFeatureSelectable": bool(
            (prior_binding or {}).get("outputContract", {}).get(
                "rawFeatureSelectable", execution["selectable"]
            )
        ),
        "exclusionReason": (
            None
            if execution["selectable"]
            else execution["blockedReason"]
            or (
                prior_binding.get("retirementReason")
                if prior_status == "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
                and prior_binding
                else None
            )
            or execution["resolution"]
        ),
        "outlier": {
            "detector": _outlier_detector(source_row, backend),
            "treatment": str(source_row.get("outlier_treatment") or ""),
            "logicalDomain": str(source_row.get("logical_domain") or ""),
            "statisticalFit": False,
            "exactObservedCountImported": False,
        },
        "missing": {
            "strategy": missing_strategy,
            "scientificRule": str(source_row.get("missing_treatment") or ""),
            "fitScope": "TRAINING_ROWS_OF_EACH_CHRONOLOGICAL_FOLD_ONLY",
            "validationRowsFitParameters": False,
            "finalOotRowsFitParameters": False,
            "indicatorFeatures": indicators,
            "fallbackLabel": execution["fallbackLabel"],
            "priorAuthority": (
                {
                    "authorityName": prior_binding.get(
                        "authorityName", player_prior.AUTHORITY_NAME
                    ),
                    "authorityId": prior_binding.get("authorityId"),
                    "authorityChecksum": prior_binding.get("authorityChecksum"),
                    "familyId": prior_binding.get("familyId"),
                    "method": prior_binding["method"],
                    "hierarchy": prior_binding["hierarchy"],
                    "roleAuthority": prior_binding["roleAuthority"],
                    "exposureFeature": prior_binding["exposureFeature"],
                    "exposureDefinition": prior_binding["exposureDefinition"],
                    "historyWindow": prior_binding["historyWindow"],
                    "historyCutoff": prior_binding["historyCutoff"],
                    "decayAuthority": prior_binding["decayAuthority"],
                    "reliability": "observed_effective_n / (prior_strength + observed_effective_n)",
                    "foldLocal": "PASS",
                    "pointInTime": "PASS",
                    "status": prior_binding["status"],
                    "executable": bool(prior_binding["executable"]),
                    "selectable": bool(prior_binding.get("selectable", prior_binding["executable"])),
                    "blockedReason": prior_binding["blockedReason"],
                    "requiredSufficientStatistics": list(
                        prior_binding.get("requiredSufficientStatistics") or ()
                    ),
                    "numeratorComponents": list(
                        prior_binding.get("numeratorComponents") or ()
                    ),
                    "compositionComponents": list(
                        prior_binding.get("compositionComponents") or ()
                    ),
                    "derivedComponents": prior_binding.get("derivedComponents"),
                    "componentFields": prior_binding.get("componentFields"),
                    "bindingEvidence": prior_binding.get("bindingEvidence"),
                    "registeredDefinition": prior_binding.get("registeredDefinition"),
                    "componentDefinition": prior_binding.get("componentDefinition"),
                    "retirementReason": prior_binding.get("retirementReason"),
                    "scientificDecisionResolved": prior_binding.get(
                        "scientificDecisionResolved"
                    ),
                    "derivedOutputs": list(executable_prior_outputs.values()),
                    "derivedOutputMap": executable_prior_outputs,
                    "outputContract": prior_binding.get("outputContract"),
                    "modelCandidateOutputs": list(
                        (prior_binding.get("outputContract") or {}).get(
                            "modelCandidateOutputs", ()
                        )
                    ),
                    "auditOnlyOutputs": list(
                        (prior_binding.get("outputContract") or {}).get(
                            "auditOnlyOutputs", ()
                        )
                    ),
                    "recommendedAblationBundle": list(
                        (prior_binding.get("outputContract") or {}).get(
                            "recommendedAblationBundle", ()
                        )
                    ),
                    "fittedFoldStatus": prior_binding.get("fittedFoldStatus"),
                    "foldContract": prior_binding.get("foldContract"),
                    "fittedFoldAuthorities": prior_binding.get("fittedFoldAuthorities"),
                    "finalDevelopmentAuthority": prior_binding.get("finalDevelopmentAuthority"),
                    "companionBindingIdentity": prior_binding.get("companionBindingIdentity"),
                    "effectiveSampleSizeSupport": prior_binding.get("effectiveSampleSizeSupport"),
                    "reliabilitySupport": prior_binding.get("reliabilitySupport"),
                    "uncertaintySupport": prior_binding.get("uncertaintySupport"),
                    "rawFeatureDecision": prior_binding["rawFeatureDecision"],
                }
                if prior_binding
                else None
            ),
        },
        "lineage": {
            "sourceIdentity": backend.get("sourceLineage"),
            "parentFeatures": parents,
            "pairedIndicators": indicators,
            "exposureFeature": prior_binding["exposureFeature"] if prior_binding else None,
            "derivedPriorOutputs": executable_prior_outputs or None,
            "transformationOrder": (
                ["TREAT_PARENTS_INSIDE_TRAINING_FOLD", "RECOMPUTE_INTERACTION", "APPLY_FROZEN_PIPELINE"]
                if parents
                else ["VALIDATE_DOMAIN", "APPLY_APPROVED_FOLD_LOCAL_TREATMENT"]
            ),
        },
        "modelFamilyResolution": {
            "treeNativeMissing": execution["treeModel"],
            "denseMatrix": execution["denseModel"],
        },
        "interactionAuthority": (
            {
                "authorityName": interaction_authority.AUTHORITY_NAME,
                "formula": interaction_binding["formula"],
                "sourceFormulaLiteral": interaction_binding["sourceFormulaLiteral"],
                "formulaVersion": interaction_binding["formulaVersion"],
                "orderedParents": interaction_binding["orderedParents"],
                "parentIdentities": [
                    parent["backendFeatureIdentity"]
                    for parent in interaction_binding["parents"]
                ],
                "parentTreatmentAuthorities": [
                    parent["parentTreatmentAuthority"]
                    for parent in interaction_binding["parents"]
                ],
                "parents": interaction_binding["parents"],
                "missingStatePropagation": interaction_binding[
                    "missingStatePropagation"
                ],
                "sourceFailurePropagation": interaction_binding[
                    "sourceFailurePropagation"
                ],
                "computationFailurePropagation": interaction_binding[
                    "computationFailurePropagation"
                ],
                "outputDataType": interaction_binding["outputDataType"],
                "outputDomain": interaction_binding["outputDomain"],
                "operationOrder": interaction_binding["operationOrder"],
                "modelFamilyResolution": interaction_binding[
                    "modelFamilyResolution"
                ],
                "pointInTime": interaction_binding["pointInTimeStatus"],
                "foldLocal": interaction_binding["foldLocalStatus"],
                "status": interaction_binding["executableStatus"],
                "blockedReason": interaction_binding["blockedReason"],
                "independentImputation": interaction_binding[
                    "independentImputation"
                ],
                "independentCapping": interaction_binding["independentCapping"],
            }
            if interaction_binding
            else None
        ),
        "semanticAuthorityDecision": (
            dict(_SEMANTIC_AUTHORITY_DECISIONS[name])
            if name in _SEMANTIC_AUTHORITY_DECISIONS
            else None
        ),
    }


def _rivalry_authority_audit(feature_name: str) -> dict[str, Any]:
    """Return a negative-only audit record for one exact backend extra.

    Formula text is copied from the canonical contextual materializer for
    traceability; it is not an activation or treatment rule.  The referenced
    mapping is explicitly proposed/inactive and lacks effective dates and an
    operational-use rights grant, so every record remains held closed.
    """

    side = "BATTING" if feature_name.startswith("batting_") else "FIELDING"
    raw_name = feature_name.removeprefix("batting_").removeprefix("fielding_")
    mapping_bytes = _RIVALRY_PROPOSAL_PATH.read_bytes()
    substantive = raw_name != "rivalry_mapping_missing"
    exact_duplicate = (
        f"{side.lower()}_rivalry_game"
        if raw_name == "rivalry_pair"
        else f"{side.lower()}_rivalry_pair"
        if raw_name == "rivalry_game"
        else f"{side.lower()}_home_x_rivalry"
        if raw_name == "home_rivalry_game"
        else f"{side.lower()}_home_rivalry_game"
        if raw_name == "home_x_rivalry"
        else None
    )
    indicator = f"{side.lower()}_rivalry_mapping_missing" if substantive else None
    return {
        "recommendation": "KEEP_HELD_CLOSED",
        "side": side,
        "source": "MLB_TEAM_GAME_CONTEXT_FEATURES_V1_RESEARCH_ONLY_EVIDENCE",
        "formula": _RIVALRY_FORMULAS[raw_name],
        "formulaEvidenceOnly": True,
        "mappingSource": "docs/MLB_RIVALRY_MAPPING_PROPOSAL_V1.json",
        "mappingSourceSha256": hashlib.sha256(mapping_bytes).hexdigest(),
        "mappingStatus": "PROPOSED_NOT_APPROVED",
        "mappingActive": False,
        "constructObjectivity": (
            "OBJECTIVE_GOVERNANCE_STATE_INDICATOR"
            if not substantive
            else "SUBJECTIVE_RIVALRY_MEMBERSHIP"
        ),
        "pointInTimeAvailability": "BLOCKED_NO_APPROVED_EFFECTIVE_DATED_MAPPING",
        "physicalMissingPercentDevelopment": 100.0 if substantive else 0.0,
        "coveragePercentDevelopment": 0.0 if substantive else 100.0,
        "coveragePercentBySeason": {
            season: 0.0 if substantive else 100.0
            for season in ("2023", "2024", "2025", "2026")
        },
        "pairedMissingnessIndicator": indicator,
        "exactDuplicateFeature": exact_duplicate,
        "overlapsObjectiveOpponentContext": substantive,
        "requiresCuratedRivalryTable": substantive,
        "sourceRights": "OPERATIONAL_USE_NOT_ESTABLISHED",
        "currentlyActive": False,
        "selectable": False,
    }


def _reconcile(
    authority: eda._Authority,
    source: Mapping[str, Any],
    *,
    prior_bindings: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    # Imported lazily to keep this combined view from becoming a second feature
    # authority and to avoid an import cycle when Feature Engineering asks for
    # the adopted combined binding later.
    from .stage3_feature_engineering import _catalog as feature_catalog

    backend_rows, backend_catalog = feature_catalog(authority)
    source_rows = [dict(row) for row in source["features"]]
    source_names = {str(row["feature_name"]) for row in source_rows}
    backend_names = {str(row["name"]) for row in backend_rows}
    unmatched_workbook = sorted(source_names - backend_names)
    additional_names = [str(row["name"]) for row in backend_rows if row["name"] not in source_names]
    additional_set_matches = tuple(additional_names) == EXPECTED_ADDITIONAL_FEATURES
    reconciled_features: list[dict[str, Any]] = []
    discrepancies: list[dict[str, Any]] = []
    for source_row in source_rows:
        name = str(source_row["feature_name"])
        backend = backend_catalog.get(name)
        row_discrepancies: list[str] = []
        if backend is None:
            row_discrepancies.append("UNMATCHED_WORKBOOK_FEATURE")
        else:
            if str(source_row["feature_family"]) != str(backend.get("featureFamily") or ""):
                row_discrepancies.append("FEATURE_FAMILY_CONFLICT")
            if str(source_row["data_type"]).lower() != str(backend.get("dataType") or "").lower():
                row_discrepancies.append("DATA_TYPE_CONFLICT")
            source_core = str(source_row["core_status"]).strip().lower() == "yes"
            if source_core is not bool(backend.get("core")):
                row_discrepancies.append("CORE_STATUS_CONFLICT")
            backend_missing = float(backend.get("missingPercentDevelopment") or 0.0)
            workbook_missing = float(source_row.get("missing_percent") or 0.0)
            if abs(backend_missing - workbook_missing) > 1e-8:
                row_discrepancies.append("DEVELOPMENT_MISSINGNESS_CONFLICT")
        prior_binding = (prior_bindings or {}).get(name)
        execution = _execution_contract(
            name,
            str(source_row.get("recommended_inclusion") or ""),
            prior_binding=prior_binding,
        )
        structured_execution = _structured_execution_contract(
            source_row,
            backend or {},
            execution,
            prior_binding=prior_binding,
        )
        reconciled = {
            **source_row,
            "source_workbook_sha256": source["source_workbook"]["sha256"],
            "backend_feature_identity": name if backend is not None else None,
            "exact_name_match": backend is not None,
            "backend_feature_family": backend.get("featureFamily") if backend else None,
            "backend_data_type": backend.get("dataType") if backend else None,
            "backend_core_status": bool(backend.get("core")) if backend else None,
            "backend_eligibility": bool(backend.get("eligible")) if backend else False,
            "source_status": backend.get("availabilityStatus") if backend else "UNMATCHED",
            "source_or_lineage_identity": backend.get("sourceLineage") if backend else None,
            "point_in_time_status": backend.get("pointInTimeTreatment") if backend else None,
            "interaction_parent_lineage": (
                {
                    "sourceLineage": backend.get("sourceLineage"),
                    "orderedParents": _interaction_parents(name),
                    "formulaVersion": (
                        interaction_authority.feature_binding(name) or {}
                    ).get("formulaVersion"),
                }
                if backend
                and source_row.get("recommended_inclusion")
                == "RECOMPUTE_AFTER_PARENT_TREATMENT"
                else None
            ),
            "discrepancy": row_discrepancies,
            "scientific_recommendation": str(source_row.get("recommended_inclusion") or ""),
            "executable_status": execution["executableStatus"],
            "executable_resolution": execution["resolution"],
            "executable_selectable": execution["selectable"],
            "preprocessing_executable": bool(
                execution.get("preprocessingExecutable", execution["selectable"])
            ),
            "raw_feature_selectable": bool(execution["selectable"]),
            "blocked_reason": execution["blockedReason"],
            "model_family_resolution": {
                "tree_native_missing": execution["treeModel"],
                "dense_matrix": execution["denseModel"],
                "fallback_label": execution["fallbackLabel"],
            },
            "execution_contract": structured_execution,
        }
        reconciled_features.append(reconciled)
        if row_discrepancies:
            discrepancies.append(
                {"featureName": name, "codes": row_discrepancies, "sourceRow": source_row["source_row"]}
            )
    additional: list[dict[str, Any]] = []
    for name in additional_names:
        backend = backend_catalog[name]
        is_expected_rivalry = name in EXPECTED_ADDITIONAL_FEATURES
        record = {
                "featureName": name,
                "backendFeatureIdentity": name,
                "workbookFeature": None,
                "exactNameMatch": False,
                "featureFamily": backend.get("featureFamily"),
                "dataType": backend.get("dataType"),
                "backendEligibility": bool(backend.get("eligible")),
                "backendGovernanceStatus": backend.get("governanceStatus"),
                "sourceStatus": backend.get("availabilityStatus"),
                "sourceOrLineageIdentity": backend.get("sourceLineage"),
                "classification": (
                    "ABSENT_UNAPPROVED_RIVALRY_AUTHORITY"
                    if is_expected_rivalry
                    else "UNMATCHED_BACKEND_FEATURE"
                ),
                "proposedDisposition": "REVIEW_REQUIRED",
                "executableStatus": "BLOCKED",
                "executableResolution": "HELD_CLOSED_NO_TREATMENT_INFERRED",
                "executableSelectable": False,
                "blockedReason": (
                    "The accepted contextual inventory contains this rivalry-authority field, "
                    "but the reviewed workbook contains no recommendation for it."
                ),
            }
        if is_expected_rivalry:
            record["authorityAudit"] = _rivalry_authority_audit(name)
        additional.append(record)
    fatal = bool(unmatched_workbook or discrepancies or not additional_set_matches)
    inventory_identity = _inventory_identity(backend_rows)
    return {
        "status": "BLOCKED" if fatal else "RECONCILED_WITH_EXPLICIT_HOLDS",
        "workbookFeatureCount": len(source_rows),
        "backendFeatureCount": len(backend_rows),
        "exactMatchCount": sum(row["exact_name_match"] for row in reconciled_features),
        "unmatchedWorkbookFeatures": unmatched_workbook,
        "additionalBackendFeatures": additional,
        "additionalBackendFeatureCount": len(additional),
        "familyConflictCount": sum(
            "FEATURE_FAMILY_CONFLICT" in row["discrepancy"] for row in reconciled_features
        ),
        "dataTypeConflictCount": sum(
            "DATA_TYPE_CONFLICT" in row["discrepancy"] for row in reconciled_features
        ),
        "coreStatusConflictCount": sum(
            "CORE_STATUS_CONFLICT" in row["discrepancy"] for row in reconciled_features
        ),
        "missingnessConflictCount": sum(
            "DEVELOPMENT_MISSINGNESS_CONFLICT" in row["discrepancy"]
            for row in reconciled_features
        ),
        "fuzzyMatchesUsed": 0,
        "discrepancies": discrepancies,
        "inventoryIdentity": inventory_identity,
        "featureInventorySha256": _sha256(inventory_identity),
        "features": reconciled_features,
        "fatal": fatal,
    }


def _exception_rows(
    features: Sequence[Mapping[str, Any]], additional: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in features:
        status = str(row["executable_status"])
        disposition = str(row["recommended_inclusion"])
        if status in {
            "READY",
            "READY_GOVERNED_PRIOR_V1",
            "READY_GOVERNED_PRIOR_V2",
            "READY_GOVERNED_INTERACTION_V1",
        } and disposition not in _EXCLUDED_DISPOSITIONS:
            continue
        output.append(
            {
                "featureName": row["feature_name"],
                "sourceSheet": row["source_sheet"],
                "sourceRow": row["source_row"],
                "priority": row["priority"],
                "scientificRecommendation": disposition,
                "executableStatus": status,
                "disposition": (
                    "EXCLUDED"
                    if disposition in _EXCLUDED_DISPOSITIONS
                    else "BLOCKING"
                    if status == "BLOCKED"
                    else "BINDING_READY_REQUIRES_WAVE2_ENGINE"
                    if status == "BINDING_READY_REQUIRES_WAVE2_ENGINE"
                    else "RETIRED"
                    if status == "RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"
                    else "FALLBACK"
                ),
                "detail": row["blocked_reason"] or row["executable_resolution"],
            }
        )
    output.extend(
        {
            "featureName": row["featureName"],
            "sourceSheet": None,
            "sourceRow": None,
            "priority": "BLOCKER",
            "scientificRecommendation": "NO_WORKBOOK_RECOMMENDATION",
            "executableStatus": "BLOCKED",
            "disposition": "BLOCKING",
            "detail": row["blockedReason"],
        }
        for row in additional
    )
    return output


def compile_project_specification(database: Database, project_id: str) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    source = load_source_specification()
    sufficient_statistics_authority = (
        sufficient_stats.registered_sufficient_statistics_authority(
            database,
            expected_gold_manifest_sha256=authority.gold_manifest_sha,
            output_root=eda._gold_root(),
        )
    )
    v1_prior_authority = player_prior.project_authority_manifest(
        authority,
        treatment_specification_key=SPECIFICATION_KEY,
        treatment_source_sha256=str(source["source_content_sha256"]),
        sufficient_statistics_authority=sufficient_statistics_authority,
    )
    exact_wave2_source = (
        v1_prior_authority.get("goldManifestSha")
        == player_prior_v2.EXPECTED_GOLD_MANIFEST_SHA256
        and (sufficient_statistics_authority or {}).get("manifestSha256")
        == player_prior_v2.EXPECTED_COMPANION_MANIFEST_SHA256
    )
    resolved_wave2 = (
        player_prior_resolution_v2.resolve_project_fit_bundle(
            project_authority=authority,
            v1_authority_manifest=v1_prior_authority,
            sufficient_statistics_authority=sufficient_statistics_authority,
            treatment_specification_key=SPECIFICATION_KEY,
            treatment_source_sha256=str(source["source_content_sha256"]),
            compiler_version=str(source["compiler_version"]),
            compiler_sha256=_normalized_file_sha256(Path(__file__)),
        )
        if exact_wave2_source
        else None
    )
    wave2_bundle = resolved_wave2[0] if resolved_wave2 is not None else None
    prior_authority = (
        player_prior_v2.combined_project_authority_manifest(
            v1_prior_authority, wave2_bundle
        )
        if wave2_bundle is not None
        else v1_prior_authority
    )
    prior_bindings = {
        str(binding["feature"]): binding
        for binding in prior_authority["bindings"]
        if isinstance(binding, Mapping) and binding.get("feature")
    }
    reconciliation = _reconcile(
        authority,
        source,
        prior_bindings=prior_bindings,
    )
    features = reconciliation.pop("features")
    inventory_identity = reconciliation.pop("inventoryIdentity")
    additional = list(reconciliation["additionalBackendFeatures"])
    interaction_manifest = interaction_authority.project_authority_manifest(
        authority,
        treatment_specification_key=SPECIFICATION_KEY,
        treatment_specification_sha256=str(source["source_content_sha256"]),
        feature_inventory_sha256=str(reconciliation["featureInventorySha256"]),
        compiler_version=str(source["compiler_version"]),
        compiler_sha256=_normalized_file_sha256(Path(__file__)),
        contextual_formula_source_sha256=_normalized_file_sha256(
            Path(__file__).with_name("contextual_features.py")
        ),
        development_identity={
            "rows": eda.DEVELOPMENT_ROWS,
            "start": eda.DEVELOPMENT_START,
            "end": eda.DEVELOPMENT_END,
        },
        final_oot_identity={
            "rows": eda.FINAL_OOT_ROWS,
            "start": eda.EXPECTED_FINAL_OOT[0],
            "end": eda.EXPECTED_FINAL_OOT[1],
            "status": "LOCKED_UNOPENED",
            "accessCount": 0,
        },
    )
    rivalry_rows = [
        row
        for row in additional
        if row.get("featureName") in EXPECTED_ADDITIONAL_FEATURES
        and isinstance(row.get("authorityAudit"), Mapping)
    ]
    for row in features:
        feature_prior = (
            (row.get("execution_contract") or {}).get("missing") or {}
        ).get("priorAuthority")
        if isinstance(feature_prior, dict):
            feature_prior["authorityId"] = prior_authority["authorityId"]
            feature_prior["authorityChecksum"] = prior_authority["authorityChecksum"]
        feature_interaction = (row.get("execution_contract") or {}).get(
            "interactionAuthority"
        )
        if isinstance(feature_interaction, dict):
            feature_interaction["authorityId"] = interaction_manifest["authorityId"]
            feature_interaction["authorityChecksum"] = interaction_manifest[
                "authorityChecksum"
            ]
    exceptions = _exception_rows(features, additional)
    disposition_counts = Counter(str(row["recommended_inclusion"]) for row in features)
    status_counts = Counter(str(row["executable_status"]) for row in features)
    status_counts["BLOCKED"] += len(additional)
    manifest_content = {
        "schemaVersion": SCHEMA_VERSION,
        "specificationKey": SPECIFICATION_KEY,
        "compilerVersion": source["compiler_version"],
        "sourceArtifactId": source["source_artifact_id"],
        "sourceContentSha256": source["source_content_sha256"],
        "sourceWorkbook": source["source_workbook"],
        "projectAuthority": treatments._authority_payload(authority),
        "priorAuthority": prior_authority,
        "wave2PriorFitBundle": (
            {
                "authorityId": wave2_bundle["authorityId"],
                "authorityChecksum": wave2_bundle["authorityChecksum"],
                "foldContract": wave2_bundle["foldContract"],
                "foldAuthorities": wave2_bundle["foldAuthorities"],
                "finalDevelopmentAuthority": wave2_bundle["finalDevelopmentAuthority"],
                "companionBindingAuthorityId": wave2_bundle["companionBindingAuthorityId"],
                "status": player_prior_v2.READY_GOVERNED_PRIOR_V2,
            }
            if wave2_bundle is not None
            else None
        ),
        "interactionAuthority": interaction_manifest,
        "semanticAuthorityAudit": {
            "status": "HELD_CLOSED",
            "cleared": 0,
            "remaining": len(_SEMANTIC_AUTHORITY_DECISIONS),
            "decisions": {
                name: dict(decision)
                for name, decision in _SEMANTIC_AUTHORITY_DECISIONS.items()
            },
        },
        "rivalryAuthorityAudit": {
            "status": "READ_ONLY_HELD_CLOSED",
            "recommendation": "KEEP_HELD_CLOSED",
            "fieldCount": len(rivalry_rows),
            "activeFieldCount": 0,
            "mappingStatus": "PROPOSED_NOT_APPROVED",
            "fields": {
                str(row["featureName"]): dict(row["authorityAudit"])
                for row in rivalry_rows
            },
        },
        "developmentBoundary": {
            "startDate": eda.DEVELOPMENT_START,
            "endDate": eda.DEVELOPMENT_END,
            "rows": eda.DEVELOPMENT_ROWS,
        },
        "finalOotIdentity": {
            "startDate": eda.EXPECTED_FINAL_OOT[0],
            "endDate": eda.EXPECTED_FINAL_OOT[1],
            "rows": eda.FINAL_OOT_ROWS,
            "locked": True,
            "targetsAccessed": False,
        },
        "featureInventoryIdentity": inventory_identity,
        "featureInventorySha256": reconciliation["featureInventorySha256"],
        "reconciliation": reconciliation,
        "dispositionCounts": dict(sorted(disposition_counts.items())),
        "executionSummary": {
            "workbookFeatures": len(features),
            "additionalHeldClosed": len(additional),
            "ready": int(status_counts["READY"]),
            "readyGovernedPrior": int(
                status_counts["READY_GOVERNED_PRIOR_V1"]
                + status_counts["READY_GOVERNED_PRIOR_V2"]
            ),
            "readyGovernedPriorV1": int(status_counts["READY_GOVERNED_PRIOR_V1"]),
            "readyGovernedPriorV2": int(status_counts["READY_GOVERNED_PRIOR_V2"]),
            "bindingReadyRequiresWave2": int(
                status_counts["BINDING_READY_REQUIRES_WAVE2_ENGINE"]
            ),
            "retiredByScientificDecision": int(
                status_counts["RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"]
            ),
            "readyGovernedInteraction": int(
                status_counts["READY_GOVERNED_INTERACTION_V1"]
            ),
            "totalReady": sum(bool(row["executable_selectable"]) for row in features),
            "readyWithExplicitFallback": int(status_counts["READY_WITH_EXPLICIT_FALLBACK"]),
            "blocked": int(status_counts["BLOCKED"]),
            "currentTotalBlockers": int(status_counts["BLOCKED"]),
            "automaticRetain": int(disposition_counts["NO_MISSING_TREATMENT"]),
            "automaticExclude": int(
                disposition_counts["EXCLUDE_UNTIL_SOURCE_REPAIRED"]
                + disposition_counts["EXCLUDE_UNTIL_COVERAGE_REPAIRED"]
            ),
            "semanticReview": int(
                disposition_counts["RECODE_AFTER_SEMANTIC_VALIDATION"]
                + disposition_counts["RECODE_AFTER_CALENDAR_VALIDATION"]
            ),
            "semanticFieldsCleared": 0,
            "semanticFieldsRemaining": len(_SEMANTIC_AUTHORITY_DECISIONS),
            "rivalryFieldsHeldClosed": len(rivalry_rows),
            "interactionBlockersBefore": int(
                disposition_counts["RECOMPUTE_AFTER_PARENT_TREATMENT"]
            ),
            "interactionBlockersCleared": int(
                status_counts["READY_GOVERNED_INTERACTION_V1"]
            ),
            "interactionBlockersRemaining": int(
                disposition_counts["RECOMPUTE_AFTER_PARENT_TREATMENT"]
                - status_counts["READY_GOVERNED_INTERACTION_V1"]
            ),
            "hierarchicalPriorRequired": int(
                disposition_counts["HIERARCHICAL_PRIOR_PLUS_INDICATOR"]
                + disposition_counts["ROLE_OR_LEAGUE_PRIOR_PLUS_INDICATOR"]
            ),
            "hierarchicalPriorReady": int(
                status_counts["READY_GOVERNED_PRIOR_V1"]
                + status_counts["READY_GOVERNED_PRIOR_V2"]
            ),
            "hierarchicalPriorReadyV1": int(status_counts["READY_GOVERNED_PRIOR_V1"]),
            "hierarchicalPriorReadyV2": int(status_counts["READY_GOVERNED_PRIOR_V2"]),
            "hierarchicalPriorBindingReady": int(
                status_counts["BINDING_READY_REQUIRES_WAVE2_ENGINE"]
            ),
            "hierarchicalPriorRetired": int(
                status_counts["RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION"]
            ),
            "hierarchicalPriorBlocked": sum(
                row["executable_status"] == "BLOCKED"
                and row["recommended_inclusion"]
                in {
                    "HIERARCHICAL_PRIOR_PLUS_INDICATOR",
                    "ROLE_OR_LEAGUE_PRIOR_PLUS_INDICATOR",
                }
                for row in features
            ),
            "nativeMissingEligible": int(disposition_counts["NO_PRIOR_GAME_STATE_PLUS_FOLD_LOCAL_FILL"]),
            "foldLocalTechnicalFallback": int(status_counts["READY_WITH_EXPLICIT_FALLBACK"]),
            "userReviewRequired": sum(item["disposition"] == "BLOCKING" for item in exceptions),
        },
        "exceptions": exceptions,
        "features": features,
        "audit": {
            "sourceRowsMutated": 0,
            "goldRowsMutated": 0,
            "finalOotRowsOpened": 0,
            "finalOotTargetsAccessed": False,
            "preprocessingFits": 0,
            "modelFits": 0,
            "scores": 0,
            "calibrations": 0,
            "promotions": 0,
            "featureSetsRegistered": 0,
            "gameScoringJobs": 0,
            "historicalArtifactMutations": 0,
            "providerCalls": 0,
        },
    }
    manifest_checksum = _sha256(manifest_content)
    return {
        **manifest_content,
        "manifestChecksum": manifest_checksum,
        "specificationId": f"{SPECIFICATION_KEY}:sha256:{manifest_checksum}",
        "canCreateDraft": not bool(reconciliation["fatal"]),
        "canAdopt": not bool(reconciliation["fatal"]) and int(status_counts["BLOCKED"]) == 0,
        "blockers": list(
            dict.fromkeys(
                item["detail"]
                for item in exceptions
                if item["disposition"] == "BLOCKING"
            )
        ),
    }


def _policy_inputs(compiled: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    authority_key = str(compiled["projectAuthority"]["authorityKey"])
    numeric_exclusions: dict[str, dict[str, Any]] = {}
    missing_overrides: dict[str, dict[str, Any]] = {}
    for row in compiled["features"]:
        disposition = str(row["recommended_inclusion"])
        name = str(row["feature_name"])
        selectable = bool(row["executable_selectable"])
        preprocessing_executable = bool(
            row.get("preprocessing_executable", row.get("executable_selectable"))
        )
        if row["data_type"] == "numeric" and not selectable and row["backend_eligibility"]:
            numeric_exclusions[name] = {
                "detectionMethod": "NO_STATISTICAL_DETECTION",
                "treatment": "RETAIN",
                "included": False,
            }
        elif (
            disposition == "RECOMPUTE_AFTER_PARENT_TREATMENT"
            and selectable
            and row["data_type"] == "numeric"
        ):
            numeric_exclusions[name] = {
                "detectionMethod": "NO_STATISTICAL_DETECTION",
                "treatment": "RETAIN",
                "included": True,
                "interactionAuthorityId": compiled["interactionAuthority"][
                    "authorityId"
                ],
                "parentValidationBeforeRecomputation": True,
                "independentInteractionCapping": False,
            }
        if not row["backend_eligibility"]:
            continue
        if not selectable and not preprocessing_executable:
            missing_overrides[name] = {
                "method": "DROP_VARIABLE",
                "coldStartMethod": "REVIEW_REQUIRED",
                "sourceFailureMethod": (
                    "DROP_VARIABLE" if disposition in _EXCLUDED_DISPOSITIONS else "REVIEW_REQUIRED"
                ),
                "retainIndicator": False,
            }
        elif disposition in _ZERO_WITH_INDICATOR_DISPOSITIONS:
            missing_overrides[name] = {
                "method": "CONSTANT",
                "constantValue": 0,
                "coldStartMethod": "RETAIN_WITH_INDICATOR",
                "sourceFailureMethod": "REVIEW_REQUIRED",
                "retainIndicator": True,
            }
        elif disposition in _FALLBACK_DISPOSITIONS:
            missing_overrides[name] = {
                "method": "RETAIN_WITH_INDICATOR",
                "coldStartMethod": "RETAIN_WITH_INDICATOR",
                "sourceFailureMethod": "REVIEW_REQUIRED",
                "retainIndicator": True,
                "resolutionLabel": "INTERIM_TECHNICAL_FALLBACK",
            }
        elif disposition == "RECOMPUTE_AFTER_PARENT_TREATMENT":
            missing_overrides[name] = {
                "method": "RETAIN_WITH_INDICATOR",
                "coldStartMethod": "RETAIN_WITH_INDICATOR",
                "sourceFailureMethod": "REVIEW_REQUIRED",
                "retainIndicator": True,
                "interactionAuthorityId": compiled["interactionAuthority"][
                    "authorityId"
                ],
                "parentFirstRecomputationRequired": True,
                "independentInteractionImputation": False,
                "resolutionLabel": "GOVERNED_PARENT_FIRST_INTERACTION_RECOMPUTATION_V1",
            }
        elif disposition in {
            "HIERARCHICAL_PRIOR_PLUS_INDICATOR",
            "ROLE_OR_LEAGUE_PRIOR_PLUS_INDICATOR",
        }:
            missing_overrides[name] = {
                "method": "GOVERNED_PRIOR",
                "coldStartMethod": "GOVERNED_PRIOR_WITH_INDICATOR",
                "sourceFailureMethod": "REVIEW_REQUIRED",
                "retainIndicator": True,
                "priorAuthorityId": compiled["priorAuthority"]["authorityId"],
                "resolutionLabel": "GOVERNED_EXECUTABLE_PRIOR_AUTHORITY",
            }
        elif disposition in {"INCLUDE_DERIVED_INDICATOR", "SIMULATOR_REQUIRED"}:
            missing_overrides[name] = {
                "method": "RETAIN_WITH_INDICATOR",
                "coldStartMethod": "RETAIN_WITH_INDICATOR",
                "sourceFailureMethod": "REVIEW_REQUIRED",
                "retainIndicator": True,
            }
    # No additional 254-library record receives an inferred treatment.  Those
    # fourteen rivalry-authority fields are held closed by the combined
    # receipt's negative Feature Engineering gate, not written into a child
    # policy that lacks a workbook recommendation.
    lineage_note = (
        f"Combined {compiled['specificationId']} · manifest {compiled['manifestChecksum']} · "
        "DRAFT ONLY; no adoption, fit, score, Gold mutation, or final-OOT access."
    )
    return (
        {
            "authorityKey": authority_key,
            "globalMethod": "NO_STATISTICAL_DETECTION",
            "globalTreatment": "RETAIN",
            "overrides": numeric_exclusions,
            "notes": lineage_note,
        },
        {
            "authorityKey": authority_key,
            "globalMethod": "RETAIN_WITH_INDICATOR",
            "coldStartDefault": "RETAIN_WITH_INDICATOR",
            "sourceFailureDefault": "REVIEW_REQUIRED",
            "indicatorDefault": "RETAIN",
            "overrides": missing_overrides,
            "notes": lineage_note,
        },
    )


def current_draft_execution_overlay(
    database: Database, authority: eda._Authority
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    """Return negative-only draft gates for Feature Engineering.

    A DRAFT never authorizes a feature or preprocessing step.  It may only
    hold a feature closed so an unresolved/source-unavailable record cannot
    slip into a new executable feature-set draft while review is pending.
    Positive transformation authority continues to come exclusively from
    adopted treatment policies.
    """

    try:
        draft = Stage3TreatmentRepository(database).combined_spec_state(
            authority.project_id, authority.review_digest
        ).get("latestDraft")
    except Exception as exc:
        if "no such table" in str(exc).lower():
            return {}, None
        raise
    if not draft:
        return {}, None
    manifest = draft.get("manifest")
    if not isinstance(manifest, Mapping):
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_DRAFT_MANIFEST_INVALID",
            "The current combined treatment draft has no immutable manifest payload.",
        )
    if _sha256(manifest) != str(draft.get("manifestChecksum") or ""):
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_DRAFT_MANIFEST_CHECKSUM_MISMATCH",
            "The current combined treatment draft failed its content-address check.",
        )
    current_manifest_checksum = compile_project_specification(
        database, authority.project_id
    )["manifestChecksum"]
    if str(draft.get("manifestChecksum") or "") != current_manifest_checksum:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_DRAFT_STALE",
            "The current combined treatment draft no longer matches the current project-bound feature authority.",
        )
    overlay: dict[str, dict[str, Any]] = {}
    for row in manifest.get("features") or []:
        if isinstance(row, Mapping) and str(row.get("feature_name") or ""):
            execution_contract = row.get("execution_contract")
            execution_contract = (
                execution_contract if isinstance(execution_contract, Mapping) else {}
            )
            missing_contract = execution_contract.get("missing")
            missing_contract = (
                missing_contract if isinstance(missing_contract, Mapping) else {}
            )
            lineage_contract = execution_contract.get("lineage")
            lineage_contract = (
                lineage_contract if isinstance(lineage_contract, Mapping) else {}
            )
            interaction_contract = execution_contract.get("interactionAuthority")
            interaction_contract = (
                interaction_contract
                if isinstance(interaction_contract, Mapping)
                else None
            )
            overlay[str(row["feature_name"])] = {
                "executableStatus": row.get("executable_status"),
                "executable": bool(execution_contract.get("executable")),
                "preprocessingExecutable": bool(
                    execution_contract.get(
                        "preprocessingExecutable", execution_contract.get("selectable")
                    )
                ),
                "rawFeatureSelectable": bool(
                    execution_contract.get(
                        "rawFeatureSelectable", row.get("executable_selectable")
                    )
                ),
                "executableSelectable": bool(row.get("executable_selectable")),
                "blockedReason": row.get("blocked_reason"),
                "resolution": row.get("executable_resolution"),
                "scientificRecommendation": row.get("recommended_inclusion"),
                # Display-only scientific lineage. A DRAFT still cannot
                # authorize this preprocessing output or a feature-set entry.
                "priorAuthority": missing_contract.get("priorAuthority"),
                "derivedPriorOutputs": lineage_contract.get("derivedPriorOutputs"),
                "interactionAuthority": interaction_contract,
            }
    for row in (manifest.get("reconciliation") or {}).get("additionalBackendFeatures") or []:
        if isinstance(row, Mapping) and str(row.get("featureName") or ""):
            overlay[str(row["featureName"])] = {
                "executableStatus": row.get("executableStatus"),
                "executable": False,
                "executableSelectable": bool(row.get("executableSelectable")),
                "blockedReason": row.get("blockedReason"),
                "resolution": row.get("executableResolution"),
                "scientificRecommendation": row.get("proposedDisposition"),
            }
    reference = {
        "specificationDraftId": draft.get("specificationId"),
        "specificationVersion": draft.get("specificationVersion"),
        "manifestChecksum": draft.get("manifestChecksum"),
        "status": "DRAFT_NEGATIVE_GATES_ONLY",
        "priorAuthority": manifest.get("priorAuthority"),
        "wave2PriorFitBundle": manifest.get("wave2PriorFitBundle"),
        "interactionAuthority": manifest.get("interactionAuthority"),
        "semanticAuthorityAudit": manifest.get("semanticAuthorityAudit"),
        "rivalryAuthorityAudit": manifest.get("rivalryAuthorityAudit"),
        "executionSummary": manifest.get("executionSummary"),
    }
    return overlay, reference


def _state_data(
    database: Database, authority: eda._Authority, compiled: Mapping[str, Any]
) -> dict[str, Any]:
    repository = Stage3TreatmentRepository(database)
    try:
        binding_state = repository.combined_spec_state(
            authority.project_id, authority.review_digest
        )
    except Exception as exc:
        if "no such table" not in str(exc).lower():
            raise
        binding_state = {
            "latestDraft": None,
            "adopted": None,
            "history": [],
            "persistenceStatus": "MIGRATION_REQUIRED",
        }
    prior_policies: dict[str, Any] = {}
    for key, kind in (("outlier", "OUTLIER"), ("missing", "IMPUTATION")):
        policy = repository.policy_state(
            authority.project_id, kind, authority.review_digest
        ).get("adopted")
        prior_policies[key] = policy
    current = binding_state.get("latestDraft")
    draft_matches = bool(
        current and str(current.get("manifestChecksum") or "") == compiled["manifestChecksum"]
    )
    return {
        "schemaVersion": compiled["schemaVersion"],
        "specification": {
            "specificationId": compiled["specificationId"],
            "sourceWorkbookFilename": compiled["sourceWorkbook"]["filename"],
            "sourceWorkbookSha256": compiled["sourceWorkbook"]["sha256"],
            "manifestChecksum": compiled["manifestChecksum"],
            "featureInventorySha256": compiled["featureInventorySha256"],
            "compilerVersion": compiled["compilerVersion"],
        },
        "reconciliation": compiled["reconciliation"],
        "dispositionCounts": compiled["dispositionCounts"],
        "executionSummary": compiled["executionSummary"],
        "priorAuthority": compiled["priorAuthority"],
        "interactionAuthority": compiled["interactionAuthority"],
        "semanticAuthorityAudit": compiled["semanticAuthorityAudit"],
        "rivalryAuthorityAudit": compiled["rivalryAuthorityAudit"],
        "exceptions": compiled["exceptions"],
        "features": [
            {
                **row,
                "featureName": row["feature_name"],
                "canonicalDisposition": row["recommended_inclusion"],
                "executionStatus": row["executable_status"],
            }
            for row in compiled["features"]
        ],
        "audit": compiled["audit"],
        "canCreateDraft": compiled["canCreateDraft"],
        "canAdopt": compiled["canAdopt"],
        "blockers": compiled["blockers"],
        "status": (
            "DRAFT_CURRENT"
            if draft_matches
            else "DRAFT_STALE"
            if current
            else "AVAILABLE"
            if compiled["canCreateDraft"]
            else "BLOCKED"
        ),
        "draft": (
            {
                "specificationDraftId": current.get("specificationId"),
                "version": current.get("specificationVersion"),
                "status": current.get("status"),
                "manifestChecksum": current.get("manifestChecksum"),
                "outlierPolicyRef": (current.get("linkedPolicies") or {}).get("outlier"),
                "missingPolicyRef": (current.get("linkedPolicies") or {}).get("missing"),
                "sourceWorkbookSha256": current.get("sourceWorkbookSha256"),
                "featureInventorySha256": current.get("featureInventorySha256"),
                "checksum": current.get("checksum"),
            }
            if current
            else None
        ),
        "adoptedSpecification": binding_state.get("adopted"),
        "history": binding_state.get("history") or [],
        "priorPolicies": prior_policies,
        "persistenceStatus": binding_state.get("persistenceStatus", "READY"),
        "draftOnly": True,
        "adoptionPerformed": False,
    }


def treatment_specification(
    database: Database, project_id: str, *, authority_key: str
) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    treatments._assert_get_authority(authority, authority_key)
    compiled = compile_project_specification(database, project_id)
    return treatments._envelope(
        authority,
        filters={},
        rows=eda.DEVELOPMENT_ROWS,
        aggregation="CANONICAL_FEATURE_TREATMENT_SPECIFICATION",
        data=_state_data(database, authority, compiled),
    )


def save_treatment_specification_draft(
    database: Database,
    project_id: str,
    payload: Any,
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    payload, filters = treatments._normalize_request(authority, payload)
    if filters:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_FILTER_SCOPE_PROHIBITED",
            "The canonical specification must bind the complete development population.",
        )
    compiled = compile_project_specification(database, project_id)
    expected_checksum = str(payload.get("expectedManifestChecksum") or "")
    if expected_checksum != compiled["manifestChecksum"]:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_CHECKSUM_MISMATCH",
            "The requested manifest checksum is absent or does not match the current project-bound compilation.",
        )
    if not compiled["canCreateDraft"]:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_RECONCILIATION_BLOCKED",
            "The source workbook and current feature authority do not reconcile exactly.",
        )
    outlier_input, missing_input = _policy_inputs(compiled)
    outlier_global, outlier_policy, outlier_fitting, outlier_notes = treatments._validate_policy_payload(
        database, authority, "OUTLIER", outlier_input
    )
    missing_global, missing_policy, missing_fitting, missing_notes = treatments._validate_policy_payload(
        database, authority, "IMPUTATION", missing_input
    )
    try:
        persisted_manifest = {
            key: value
            for key, value in compiled.items()
            if key
            not in {
                "manifestChecksum",
                "specificationId",
                "canCreateDraft",
                "canAdopt",
                "blockers",
            }
        }
        if _sha256(persisted_manifest) != compiled["manifestChecksum"]:
            raise Stage3FeatureTreatmentSpecError(
                "TREATMENT_SPEC_INTERNAL_CHECKSUM_MISMATCH",
                "The persisted manifest content does not match its deterministic compilation checksum.",
            )
        Stage3TreatmentRepository(database).save_combined_spec_draft(
            authority=treatments._persistence_authority(authority),
            source_workbook_filename=str(compiled["sourceWorkbook"]["filename"]),
            source_workbook_sha256=str(compiled["sourceWorkbook"]["sha256"]),
            feature_inventory_sha256=str(compiled["featureInventorySha256"]),
            manifest_checksum=str(compiled["manifestChecksum"]),
            manifest=persisted_manifest,
            outlier_draft={
                "globalMethod": outlier_global,
                "policy": outlier_policy,
                "fittingRule": outlier_fitting,
                "notes": outlier_notes,
            },
            missing_draft={
                "globalMethod": missing_global,
                "policy": missing_policy,
                "fittingRule": missing_fitting,
                "notes": missing_notes,
            },
            notes=(
                f"{compiled['specificationId']} · DRAFT ONLY · "
                f"{len(compiled['blockers'])} blocker class(es) remain unresolved."
            ),
            actor_user_id=actor_user_id,
        )
    except Stage3TreatmentPersistenceError as exc:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_DRAFT_PERSISTENCE_FAILED", str(exc)
        ) from exc
    return treatments._envelope(
        authority,
        filters={},
        rows=eda.DEVELOPMENT_ROWS,
        aggregation="CANONICAL_FEATURE_TREATMENT_SPECIFICATION_DRAFT",
        data=_state_data(database, authority, compiled),
    )


def adopt_treatment_specification(
    database: Database,
    project_id: str,
    payload: Any,
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    authority = eda._resolve_authority(database, project_id)
    payload, filters = treatments._normalize_request(authority, payload)
    if filters:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_FILTER_SCOPE_PROHIBITED",
            "Specification adoption must bind the complete development population.",
        )
    compiled = compile_project_specification(database, project_id)
    specification_draft_id = str(payload.get("specificationDraftId") or "").strip()
    expected_manifest_checksum = str(
        payload.get("expectedManifestChecksum") or ""
    ).strip()
    if not specification_draft_id or not expected_manifest_checksum:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_DRAFT_REQUIRED",
            "The exact immutable specificationDraftId and expectedManifestChecksum are required for adoption.",
        )
    current_draft = Stage3TreatmentRepository(database).combined_spec_state(
        authority.project_id, authority.review_digest
    ).get("latestDraft")
    if (
        not current_draft
        or str(current_draft.get("specificationId") or "")
        != specification_draft_id
    ):
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_DRAFT_NOT_CURRENT",
            "The requested combined specification draft is not the current authority-bound draft.",
        )
    if (
        str(current_draft.get("manifestChecksum") or "")
        != expected_manifest_checksum
    ):
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_DRAFT_CHECKSUM_MISMATCH",
            "The requested manifest checksum does not match the immutable combined specification draft.",
        )
    if expected_manifest_checksum != str(compiled["manifestChecksum"]):
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_DRAFT_STALE",
            "The combined specification draft no longer matches the current project-bound feature authority.",
        )
    if not compiled["canAdopt"]:
        raise Stage3FeatureTreatmentSpecError(
            "TREATMENT_SPEC_ADOPTION_BLOCKED",
            "The combined specification has unresolved semantic or executable blockers and cannot be adopted.",
        )
    raise Stage3FeatureTreatmentSpecError(
        "TREATMENT_SPEC_ADOPTION_NOT_IMPLEMENTED",
        "Atomic combined adoption remains held closed until all executable blockers are resolved.",
    )


__all__ = [
    "EXPECTED_ADDITIONAL_FEATURES",
    "EXPECTED_DISPOSITION_COUNTS",
    "SCHEMA_VERSION",
    "SPECIFICATION_KEY",
    "Stage3FeatureTreatmentSpecError",
    "adopt_treatment_specification",
    "compile_project_specification",
    "current_draft_execution_overlay",
    "load_source_specification",
    "save_treatment_specification_draft",
    "treatment_specification",
]
