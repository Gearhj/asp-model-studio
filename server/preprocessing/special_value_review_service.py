from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable, Mapping

from .bureau_detection_types import SpecialValueVariableDecisionInput


RATIONALE_REQUIRED_POLICIES = {
    "convert_to_missing",
    "documented_domain_mapping",
    "exclude_variable",
    "custom",
}


class SpecialValueReviewValidationError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        open_items: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.open_items = list(open_items or [])


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_scalar(value: Any) -> str:
    item = getattr(value, "item", None)
    if callable(item):
        try:
            value = item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, bool):
        return f"bool:{str(value).lower()}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        return f"number:{format(numeric, '.15g')}"
    return "text:" + str(value)


def _detection_contract(detection: Mapping[str, Any]) -> dict[str, Any]:
    target_evidence = detection.get("target_evidence")
    target_evidence = (
        target_evidence if isinstance(target_evidence, Mapping) else {}
    )
    variables: list[dict[str, Any]] = []
    for raw in detection.get("variables", []) or []:
        if not isinstance(raw, Mapping):
            continue
        special_values = []
        for special in raw.get("special_values", []) or []:
            if not isinstance(special, Mapping):
                continue
            special_values.append(
                {
                    "value": special.get("value"),
                    "count": int(special.get("count") or 0),
                    "definition": _text(special.get("definition")),
                }
            )
        variables.append(
            {
                "variable": _text(raw.get("variable")),
                "datatype": _text(raw.get("datatype")),
                "likely_bureau": bool(raw.get("likely_bureau")),
                "special_value_count": int(raw.get("special_value_count") or 0),
                "special_values": special_values,
            }
        )
    return {
        "project_id": _text(detection.get("project_id")),
        "dataset_id": _text(detection.get("dataset_id")),
        "dataset_version_id": _text(detection.get("dataset_version_id")),
        "predictor_authorization_id": _text(
            detection.get("predictor_authorization_id")
        ),
        "target_contract_id": _text(detection.get("target_contract_id")),
        "analysis_partition_id": _text(
            detection.get("analysis_partition_id")
        ),
        "analysis_partition_revision": int(
            detection.get("analysis_partition_revision") or 0
        ),
        "development_partition_id": _text(
            detection.get("development_partition_id")
        ),
        "analysis_partition_assignment_hash": _text(
            detection.get("analysis_partition_assignment_hash")
        ),
        "analysis_partition_artifact_hash": _text(
            detection.get("analysis_partition_artifact_hash")
        ),
        "development_target_checksum": _text(
            detection.get("development_target_checksum")
        ),
        "source_checksum": _text(detection.get("source_checksum")),
        "structural_scope": _text(detection.get("structural_scope")),
        "target_analysis_scope": _text(
            detection.get("target_analysis_scope")
        ),
        "target_evidence_available": bool(
            target_evidence.get("available")
        ),
        "target_evidence_status": _text(
            target_evidence.get("status")
            or detection.get("target_evidence_status")
        ),
        "target_evidence_unavailable_reason": _text(
            detection.get("target_evidence_unavailable_reason")
        ),
        "full_governed_population_rows": int(
            detection.get("full_governed_population_rows")
            or detection.get("row_count")
            or 0
        ),
        "development_rows": int(detection.get("development_rows") or 0),
        "target": _text(detection.get("target")),
        "manual_declaration": _text(detection.get("manual_declaration")),
        "detected": bool(detection.get("detected")),
        "variables": sorted(variables, key=lambda value: value["variable"]),
    }


def detection_fingerprint(detection: Mapping[str, Any]) -> str:
    payload = json.dumps(
        _detection_contract(detection),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def detected_variables(detection: Mapping[str, Any]) -> dict[str, set[str]]:
    output: dict[str, set[str]] = {}
    for raw in detection.get("variables", []) or []:
        if not isinstance(raw, Mapping):
            continue
        variable = _text(raw.get("variable"))
        if (
            not variable
            or not bool(raw.get("likely_bureau"))
            or int(raw.get("special_value_count") or 0) <= 0
        ):
            continue
        output[variable] = {
            _canonical_scalar(value.get("value"))
            for value in raw.get("special_values", []) or []
            if isinstance(value, Mapping) and value.get("value") is not None
        }
    return output


def _detected_variable_rows(
    detection: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    return {
        _text(raw.get("variable")): raw
        for raw in detection.get("variables", []) or []
        if isinstance(raw, Mapping) and _text(raw.get("variable"))
    }


def _validated_replacement(
    value: Any,
    *,
    variable: str,
    detected_values: set[str],
    variable_row: Mapping[str, Any],
) -> Any:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        raise SpecialValueReviewValidationError(
            "governed_replacement_value_required",
            f"{variable} requires one valid governed replacement value.",
            open_items=[variable],
        )
    if isinstance(value, str) and not value.strip():
        raise SpecialValueReviewValidationError(
            "governed_replacement_value_required",
            f"{variable} requires one valid governed replacement value.",
            open_items=[variable],
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise SpecialValueReviewValidationError(
            "governed_replacement_value_invalid",
            f"{variable} has a non-finite governed replacement value.",
            open_items=[variable],
        )

    datatype = _text(variable_row.get("datatype")).casefold()
    numeric_datatype = any(
        token in datatype
        for token in ("int", "float", "double", "decimal", "number")
    )
    native_value = value
    if numeric_datatype:
        if isinstance(native_value, bool):
            native_value = None
        elif isinstance(native_value, str):
            try:
                native_value = float(native_value.strip())
            except ValueError:
                native_value = None
        if not isinstance(native_value, (int, float)) or not math.isfinite(
            float(native_value)
        ):
            raise SpecialValueReviewValidationError(
                "governed_replacement_value_invalid",
                f"{variable} requires a finite numeric governed replacement value.",
                open_items=[variable],
            )
        if "int" in datatype:
            if not float(native_value).is_integer():
                raise SpecialValueReviewValidationError(
                    "governed_replacement_value_invalid",
                    f"{variable} requires an integer governed replacement value.",
                    open_items=[variable],
                )
            native_value = int(native_value)
    item = getattr(native_value, "item", None)
    if callable(item):
        try:
            native_value = item()
        except (TypeError, ValueError):
            pass
    if _canonical_scalar(native_value) in detected_values:
        raise SpecialValueReviewValidationError(
            "governed_replacement_value_invalid",
            (
                f"{variable} cannot use another detected special code as its "
                "governed replacement value."
            ),
            open_items=[variable],
        )
    return native_value


def _normalized_replacement(
    *,
    policy: str,
    supplied: Any,
    variable: str,
    detected_values: set[str],
    variable_row: Mapping[str, Any],
) -> tuple[bool, Any]:
    if policy == "documented_domain_mapping":
        return True, _validated_replacement(
            supplied,
            variable=variable,
            detected_values=detected_values,
            variable_row=variable_row,
        )
    if supplied is not None:
        raise SpecialValueReviewValidationError(
            "governed_replacement_value_not_applicable",
            (
                f"{variable} supplies a governed replacement value for a "
                "non-imputation policy."
            ),
            open_items=[variable],
        )
    return False, None


def initial_review_state(detection: Mapping[str, Any]) -> dict[str, Any]:
    count = len(detected_variables(detection))
    return {
        "status": "not_required" if count == 0 else "not_started",
        "detected_count": count,
        "reviewed_count": 0,
        "open_count": count,
        "blocks_confirmation": count > 0,
        "blocks_continuation": count > 0,
    }


def evaluate_review(
    detection: Mapping[str, Any],
    decisions: Iterable[SpecialValueVariableDecisionInput],
    *,
    intent: str,
) -> dict[str, Any]:
    detected = detected_variables(detection)
    variable_rows = _detected_variable_rows(detection)
    normalized: list[dict[str, Any]] = []
    seen_variables: set[str] = set()
    for decision in decisions:
        variable = decision.variable.strip()
        if variable in seen_variables:
            raise SpecialValueReviewValidationError(
                "duplicate_special_value_decision",
                f"The review contains more than one decision for {variable}.",
            )
        seen_variables.add(variable)
        if variable not in detected:
            raise SpecialValueReviewValidationError(
                "unknown_special_value_variable",
                "A review decision references a variable outside the exact backend detection.",
            )
        if decision.policy in RATIONALE_REQUIRED_POLICIES and not decision.rationale:
            raise SpecialValueReviewValidationError(
                "special_value_rationale_required",
                f"{variable} requires a rationale for the selected policy.",
                open_items=[variable],
            )
        has_replacement, replacement_value = _normalized_replacement(
            policy=decision.policy,
            supplied=decision.replacement_value,
            variable=variable,
            detected_values=detected[variable],
            variable_row=variable_rows.get(variable, {}),
        )
        seen_values: set[str] = set()
        overrides: list[dict[str, Any]] = []
        for override in decision.overrides:
            canonical = _canonical_scalar(override.value)
            if canonical in seen_values:
                raise SpecialValueReviewValidationError(
                    "duplicate_special_value_override",
                    f"{variable} contains a duplicate value override.",
                )
            seen_values.add(canonical)
            if canonical not in detected[variable]:
                raise SpecialValueReviewValidationError(
                    "unknown_special_value_override",
                    "A value override is not present in the exact backend detection.",
                )
            if not override.rationale:
                raise SpecialValueReviewValidationError(
                    "special_value_override_rationale_required",
                    f"The {variable} value override requires a rationale.",
                    open_items=[variable],
                )
            has_override_replacement, override_replacement = (
                _normalized_replacement(
                    policy=override.policy,
                    supplied=override.replacement_value,
                    variable=variable,
                    detected_values=detected[variable],
                    variable_row=variable_rows.get(variable, {}),
                )
            )
            normalized_override = override.model_dump(
                mode="json",
                exclude={"replacement_value"},
            )
            if has_override_replacement:
                normalized_override["replacement_value"] = (
                    override_replacement
                )
            overrides.append(normalized_override)
        normalized_decision = {
            "variable": variable,
            "policy": decision.policy,
            "rationale": decision.rationale,
            "overrides": overrides,
        }
        if has_replacement:
            normalized_decision["replacement_value"] = (
                replacement_value
            )
        normalized.append(normalized_decision)

    detected_count = len(detected)
    reviewed_count = len(seen_variables)
    open_items = sorted(set(detected) - seen_variables)
    open_count = len(open_items)
    if intent == "confirm" and open_count:
        raise SpecialValueReviewValidationError(
            "special_value_review_incomplete",
            "All backend-detected special-value variables must be reviewed before confirmation.",
            open_items=open_items,
        )
    if detected_count == 0:
        status = "not_required"
    elif intent == "confirm":
        status = "confirmed"
    elif open_count == 0:
        status = "ready_for_confirmation"
    elif reviewed_count:
        status = "in_review"
    else:
        status = "not_started"
    return {
        "decisions": sorted(normalized, key=lambda value: value["variable"]),
        "status": status,
        "detected_count": detected_count,
        "reviewed_count": reviewed_count,
        "open_count": open_count,
        "open_items": open_items,
        "blocks_confirmation": open_count > 0,
        "blocks_continuation": detected_count > 0 and status != "confirmed",
    }


def public_review_contract(row: Mapping[str, Any]) -> dict[str, Any]:
    status = _text(row.get("status")) or "not_started"
    detection = row.get("detection_json")
    decisions = row.get("decisions_json")
    detected = detected_variables(detection if isinstance(detection, Mapping) else {})
    detection_contract = (
        detection if isinstance(detection, Mapping) else {}
    )
    target_evidence = detection_contract.get("target_evidence")
    target_evidence = (
        target_evidence if isinstance(target_evidence, Mapping) else {}
    )
    reviewed = {
        _text(decision.get("variable"))
        for decision in decisions or []
        if isinstance(decision, Mapping) and _text(decision.get("variable"))
    }
    open_items = sorted(set(detected) - reviewed)
    return {
        "special_value_review_id": _text(row.get("special_value_review_id")),
        "project_id": _text(row.get("project_id")),
        "dataset_id": _text(row.get("dataset_id")),
        "dataset_version_id": _text(row.get("dataset_version_id")),
        "activation_revision": int(row.get("activation_revision") or 0),
        "predictor_authorization_id": _text(
            row.get("predictor_authorization_id")
        ),
        "target_contract_id": _text(row.get("target_contract_id")),
        "analysis_partition_id": _text(
            detection_contract.get("analysis_partition_id")
        ) or None,
        "analysis_partition_revision": (
            int(detection_contract.get("analysis_partition_revision") or 0)
            or None
        ),
        "development_partition_id": _text(
            detection_contract.get("development_partition_id")
        ) or None,
        "analysis_partition_assignment_hash": _text(
            detection_contract.get("analysis_partition_assignment_hash")
        ) or None,
        "analysis_partition_artifact_hash": _text(
            detection_contract.get("analysis_partition_artifact_hash")
        ) or None,
        "development_target_checksum": _text(
            detection_contract.get("development_target_checksum")
        ) or None,
        "source_checksum": _text(
            detection_contract.get("source_checksum")
        ) or None,
        "structural_scope": _text(
            detection_contract.get("structural_scope")
        ),
        "target_analysis_scope": _text(
            detection_contract.get("target_analysis_scope")
        ),
        "target_evidence_available": bool(
            target_evidence.get("available")
        ),
        "target_evidence_status": _text(
            target_evidence.get("status")
            or detection_contract.get("target_evidence_status")
        )
        or "unavailable",
        "target_evidence_unavailable_reason": _text(
            detection_contract.get("target_evidence_unavailable_reason")
        ),
        "full_governed_population_rows": int(
            detection_contract.get("full_governed_population_rows")
            or detection_contract.get("row_count")
            or 0
        ),
        "development_rows": int(
            detection_contract.get("development_rows") or 0
        ),
        "detection_fingerprint": _text(row.get("detection_fingerprint")),
        "status": status,
        "detected_count": int(row.get("detected_count") or 0),
        "reviewed_count": int(row.get("reviewed_count") or 0),
        "open_count": int(row.get("open_count") or 0),
        "open_items": open_items,
        "blocks_confirmation": bool(row.get("blocks_confirmation")),
        "blocks_continuation": bool(row.get("blocks_continuation")),
        "confirmation_allowed": int(row.get("open_count") or 0) == 0,
        "revision": int(row.get("revision") or 0),
        "variable_decisions": list(row.get("decisions_json") or []),
        "reviewer_rationale": _text(row.get("reviewer_rationale")),
        "confirmed_at": row.get("confirmed_at"),
        "updated_at": row.get("updated_at"),
        "authority": "backend_durable_exact_version",
        "browser_cache_authority": False,
    }
