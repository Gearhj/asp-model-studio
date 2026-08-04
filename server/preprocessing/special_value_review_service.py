from __future__ import annotations

import hashlib
import json
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
            overrides.append(override.model_dump(mode="json"))
        normalized.append(
            {
                "variable": variable,
                "policy": decision.policy,
                "rationale": decision.rationale,
                "overrides": overrides,
            }
        )

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
