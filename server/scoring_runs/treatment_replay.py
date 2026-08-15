from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ..preprocessing.predictor_authorization import bureau_special_mask
from ..training.candidate_contract import canonical_contract_hash


MISSING_STRINGS = {"", "na", "n/a", "null", "none", "nan", "missing"}
_SPECIAL_STEP_TYPES = {"special_value", "special_value_treatment"}
_SPECIAL_NOOP_POLICIES = {"preserve_informative", "leave_unchanged"}
_SPECIAL_MUTATING_POLICIES = {
    "convert_to_missing",
    "convert_to_category",
    "documented_domain_mapping",
    "exclude_variable",
    "custom",
}


@dataclass(frozen=True)
class GovernedTreatmentReplayError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _fail(code: str, message: str) -> None:
    raise GovernedTreatmentReplayError(code, message)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _identity_from_contract(candidate_contract: Mapping[str, Any]) -> dict[str, str]:
    return {
        "project_id": _text(candidate_contract.get("project_id")),
        "dataset_id": _text(candidate_contract.get("dataset_id")),
        "dataset_version_id": _text(candidate_contract.get("dataset_version_id")),
    }


def treatment_manifest_payload(
    datastore_meta: Mapping[str, Any],
    candidate_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Rebuild the exact payload used by ``complete_training_contract``.

    Keep this shape synchronized with ``candidate_contract.py``. Adding fields
    here would make existing frozen hashes unverifiable, so special-value replay
    is sourced only from hash-bound executable pipeline steps.
    """

    identity = _identity_from_contract(candidate_contract)
    return {
        **identity,
        "outlier_application": deepcopy(datastore_meta.get("outlier_application")),
        "missing_application": deepcopy(datastore_meta.get("missing_application")),
        "missing_validation": deepcopy(datastore_meta.get("missing_validation")),
        "preprocessing_pipeline": deepcopy(
            candidate_contract.get("preprocessing_pipeline") or []
        ),
    }


def _assert_exact_identity(
    candidate_contract: Mapping[str, Any],
    *,
    expected_project_id: str,
    expected_dataset_id: str,
    expected_dataset_version_id: str,
) -> dict[str, str]:
    expected = {
        "project_id": _text(expected_project_id),
        "dataset_id": _text(expected_dataset_id),
        "dataset_version_id": _text(expected_dataset_version_id),
    }
    if any(not value for value in expected.values()):
        _fail(
            "treatment_identity_required",
            "Exact project, dataset, and dataset-version identity is required for treatment replay.",
        )
    actual = _identity_from_contract(candidate_contract)
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            _fail(
                "treatment_identity_mismatch",
                f"The frozen treatment contract does not match the expected {key}.",
            )
    return expected


def _assert_record_identity(
    record: Any,
    *,
    label: str,
    expected: Mapping[str, str],
    candidate_contract: Mapping[str, Any],
) -> None:
    if record is None:
        return
    if not isinstance(record, Mapping):
        _fail(
            "treatment_metadata_invalid",
            f"The current {label} metadata is not a governed mapping.",
        )
    for key, expected_value in expected.items():
        actual = _text(record.get(key))
        if actual != expected_value:
            _fail(
                "treatment_identity_mismatch",
                f"The current {label} does not match the exact {key}.",
            )
    legacy_version = _text(record.get("dataset_version"))
    if legacy_version and legacy_version != expected["dataset_version_id"]:
        _fail(
            "treatment_identity_mismatch",
            f"The current {label} has a contradictory legacy dataset version.",
        )

    expected_partition_id = _text(candidate_contract.get("analysis_partition_id"))
    expected_partition_revision = int(
        candidate_contract.get("analysis_partition_revision") or 0
    )
    if expected_partition_id:
        if _text(record.get("analysis_partition_id")) != expected_partition_id:
            _fail(
                "treatment_partition_mismatch",
                f"The current {label} does not match the frozen Analysis Partition.",
            )
        if int(record.get("analysis_partition_revision") or 0) != expected_partition_revision:
            _fail(
                "treatment_partition_mismatch",
                f"The current {label} does not match the frozen Analysis Partition revision.",
            )


def _verified_manifest(
    datastore_meta: Mapping[str, Any],
    candidate_contract: Mapping[str, Any],
    *,
    expected_project_id: str,
    expected_dataset_id: str,
    expected_dataset_version_id: str,
) -> tuple[dict[str, Any], str]:
    if not isinstance(datastore_meta, Mapping):
        _fail(
            "treatment_manifest_missing",
            "Current exact treatment metadata is unavailable; external scoring is blocked.",
        )
    if not isinstance(candidate_contract, Mapping):
        _fail(
            "treatment_manifest_missing",
            "The frozen candidate treatment contract is unavailable; external scoring is blocked.",
        )
    expected = _assert_exact_identity(
        candidate_contract,
        expected_project_id=expected_project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
    )
    expected_hash = _text(candidate_contract.get("treatment_manifest_hash"))
    if not expected_hash:
        _fail(
            "treatment_manifest_missing",
            "The frozen candidate has no treatment_manifest_hash; external scoring is blocked.",
        )

    for key, label in (
        ("outlier_application", "outlier application"),
        ("missing_application", "missing-value application"),
        ("missing_validation", "missing-value validation"),
    ):
        _assert_record_identity(
            datastore_meta.get(key),
            label=label,
            expected=expected,
            candidate_contract=candidate_contract,
        )

    payload = treatment_manifest_payload(datastore_meta, candidate_contract)
    actual_hash = canonical_contract_hash(payload)
    if actual_hash != expected_hash:
        _fail(
            "treatment_manifest_hash_mismatch",
            "Current treatment metadata does not match the frozen candidate treatment manifest.",
        )
    expected_id = _text(candidate_contract.get("treatment_manifest_id"))
    canonical_id = f"tm-{actual_hash[:20]}"
    if expected_id and expected_id != canonical_id:
        _fail(
            "treatment_manifest_id_mismatch",
            "The frozen treatment_manifest_id does not match its canonical hash.",
        )
    return payload, actual_hash


def _pipeline_special_treatments(
    pipeline: Sequence[Any],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for step in pipeline:
        if not isinstance(step, Mapping) or step.get("enabled") is False:
            continue
        step_type = _text(
            step.get("transformation_type") or step.get("type")
        ).casefold()
        if step_type not in _SPECIAL_STEP_TYPES:
            continue
        config = step.get("config")
        if not isinstance(config, Mapping):
            _fail(
                "special_value_treatment_not_executable",
                "A frozen special-value pipeline step has no executable configuration.",
            )
        treatments = config.get("treatments")
        if not isinstance(treatments, list) or not treatments:
            _fail(
                "special_value_treatment_not_executable",
                "A frozen special-value pipeline step has no executable treatments.",
            )
        for treatment in treatments:
            if not isinstance(treatment, Mapping):
                _fail(
                    "special_value_treatment_not_executable",
                    "A frozen special-value treatment is not a governed mapping.",
                )
            output.append(dict(treatment))
    return output


def _assert_no_unexecutable_special_review(
    datastore_meta: Mapping[str, Any],
    executable: Sequence[Mapping[str, Any]],
) -> None:
    review = datastore_meta.get("special_value_review")
    if not isinstance(review, Mapping):
        return
    decisions = review.get("variable_decisions")
    decisions = decisions if isinstance(decisions, list) else []
    mutating = [
        decision
        for decision in decisions
        if isinstance(decision, Mapping)
        and _text(decision.get("policy")).casefold() in _SPECIAL_MUTATING_POLICIES
    ]
    if mutating and not executable:
        _fail(
            "special_value_treatment_not_executable",
            "The confirmed special-value review contains mutating choices, but the frozen treatment manifest has no executable value-level treatment metadata.",
        )


def _numeric_like(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        return True
    nonmissing = series.dropna()
    return bool(
        len(nonmissing)
        and pd.to_numeric(nonmissing, errors="coerce").notna().mean() >= 0.8
    )


def _value_mask(series: pd.Series, value: Any) -> pd.Series:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            _fail(
                "special_value_treatment_not_executable",
                "A frozen special-value treatment contains a non-finite value.",
            )
        if _numeric_like(series):
            return pd.to_numeric(series, errors="coerce").eq(float(value))
    return series.eq(value).fillna(False)


def _apply_special_values(
    frame: pd.DataFrame,
    treatments: Sequence[Mapping[str, Any]],
    *,
    target: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    work = frame.copy(deep=True)
    applied: list[dict[str, Any]] = []
    for treatment in treatments:
        feature = _text(treatment.get("feature") or treatment.get("variable"))
        policy = _text(treatment.get("policy")).casefold()
        if not feature or not policy:
            _fail(
                "special_value_treatment_not_executable",
                "A frozen special-value treatment is missing its feature or policy.",
            )
        if feature == target:
            _fail(
                "special_value_target_forbidden",
                "A special-value treatment cannot modify the governed target column.",
            )
        if feature not in work.columns:
            _fail(
                "treatment_source_missing",
                f"External scoring is missing special-value source feature '{feature}'.",
            )
        if policy in _SPECIAL_NOOP_POLICIES:
            applied.append({"feature": feature, "policy": policy, "changed": 0})
            continue
        if policy == "custom":
            _fail(
                "special_value_treatment_not_executable",
                f"The custom special-value policy for '{feature}' has no deterministic executable contract.",
            )
        if policy == "exclude_variable":
            work = work.drop(columns=[feature])
            applied.append({"feature": feature, "policy": policy, "changed": int(len(work))})
            continue

        values = treatment.get("values")
        if not isinstance(values, list) or not values:
            _fail(
                "special_value_treatment_not_executable",
                f"The special-value policy for '{feature}' does not record the exact values it applies to.",
            )
        mask = pd.Series(False, index=work.index, dtype=bool)
        for value in values:
            mask = mask | _value_mask(work[feature], value)
        changed = int(mask.sum())
        if policy == "convert_to_missing":
            work.loc[mask, feature] = np.nan
        elif policy in {"convert_to_category", "documented_domain_mapping"}:
            if "replacement_value" not in treatment:
                _fail(
                    "special_value_treatment_not_executable",
                    f"The special-value mapping for '{feature}' has no frozen replacement value.",
                )
            work.loc[mask, feature] = treatment.get("replacement_value")
        else:
            _fail(
                "special_value_treatment_not_executable",
                f"Unsupported frozen special-value policy '{policy}' for '{feature}'.",
            )
        applied.append({"feature": feature, "policy": policy, "changed": changed})
    return work, applied


def _apply_outliers(
    frame: pd.DataFrame,
    application: Any,
    *,
    target: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    work = frame.copy(deep=True)
    if application is None:
        return work, []
    treatments = application.get("treatments")
    if not isinstance(treatments, list):
        _fail(
            "outlier_treatment_not_executable",
            "The frozen outlier application does not contain executable treatments.",
        )
    applied: list[dict[str, Any]] = []
    for treatment in treatments:
        if not isinstance(treatment, Mapping):
            _fail(
                "outlier_treatment_not_executable",
                "A frozen outlier treatment is not a governed mapping.",
            )
        feature = _text(treatment.get("feature"))
        method = _text(treatment.get("applied_method")).upper()
        if not feature or not method:
            _fail(
                "outlier_treatment_not_executable",
                "A frozen outlier treatment is missing its feature or applied method.",
            )
        if feature == target:
            _fail(
                "outlier_target_forbidden",
                "An outlier treatment cannot modify the governed target column.",
            )
        if feature not in work.columns:
            _fail(
                "treatment_source_missing",
                f"External scoring is missing outlier source feature '{feature}'.",
            )
        if method == "NONE":
            applied.append({"feature": feature, "method": method, "changed": 0})
            continue
        try:
            lower = float(treatment["lower_threshold"])
            upper = float(treatment["upper_threshold"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GovernedTreatmentReplayError(
                "outlier_treatment_not_executable",
                f"The frozen outlier treatment for '{feature}' has no valid cutoffs.",
            ) from exc
        if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
            _fail(
                "outlier_treatment_not_executable",
                f"The frozen outlier treatment for '{feature}' has invalid cutoffs.",
            )
        numeric = pd.to_numeric(work[feature], errors="coerce")
        special = bureau_special_mask(numeric)
        clipped = numeric.clip(lower, upper).where(~special, numeric)
        changed = int((numeric.notna() & clipped.ne(numeric)).sum())
        work[feature] = clipped
        applied.append({"feature": feature, "method": method, "changed": changed})
    return work, applied


def _normalize_missing(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy(deep=True)
    for column in work.columns:
        if pd.api.types.is_object_dtype(work[column]) or pd.api.types.is_string_dtype(
            work[column]
        ):
            text = work[column].astype("string")
            work.loc[
                text.str.strip().str.lower().isin(MISSING_STRINGS), column
            ] = np.nan
    return work


def _apply_missing(
    frame: pd.DataFrame,
    application: Any,
    *,
    target: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    work = _normalize_missing(frame)
    if application is None:
        return work, []
    treatments = application.get("treatments")
    if not isinstance(treatments, list):
        _fail(
            "missing_treatment_not_executable",
            "The frozen missing-value application does not contain executable treatments.",
        )
    applied: list[dict[str, Any]] = []
    for treatment in treatments:
        if not isinstance(treatment, Mapping):
            _fail(
                "missing_treatment_not_executable",
                "A frozen missing-value treatment is not a governed mapping.",
            )
        feature = _text(treatment.get("feature"))
        strategy = _text(treatment.get("strategy")).casefold()
        if not feature or not strategy:
            _fail(
                "missing_treatment_not_executable",
                "A frozen missing-value treatment is missing its feature or strategy.",
            )
        if feature == target:
            _fail(
                "missing_target_forbidden",
                "A missing-value treatment cannot modify the governed target column.",
            )
        if feature not in work.columns:
            _fail(
                "treatment_source_missing",
                f"External scoring is missing missing-value source feature '{feature}'.",
            )
        if strategy == "drop row":
            _fail(
                "missing_treatment_not_executable",
                "Row deletion cannot be replayed against an external scoring population.",
            )
        if "value" not in treatment:
            _fail(
                "missing_treatment_not_executable",
                f"The frozen missing-value treatment for '{feature}' has no realized fill value.",
            )
        series = work[feature]
        missing = series.isna()
        if not missing.any():
            applied.append({"feature": feature, "strategy": strategy, "filled": 0})
            continue
        nonmissing = series.dropna()
        if nonmissing.empty:
            _fail(
                "missing_treatment_type_ambiguous",
                f"The external feature '{feature}' is entirely missing and the frozen treatment does not record its fitted datatype.",
            )
        fill_value: Any = treatment.get("value")
        if _numeric_like(series):
            converted = pd.to_numeric(series, errors="coerce")
            try:
                fill_value = float(fill_value)
            except (TypeError, ValueError) as exc:
                raise GovernedTreatmentReplayError(
                    "missing_treatment_not_executable",
                    f"The frozen numeric fill value for '{feature}' is invalid.",
                ) from exc
            if not math.isfinite(fill_value):
                _fail(
                    "missing_treatment_not_executable",
                    f"The frozen numeric fill value for '{feature}' is not finite.",
                )
            series = converted
        work[feature] = series.fillna(fill_value)
        applied.append(
            {"feature": feature, "strategy": strategy, "filled": int(missing.sum())}
        )
    return work, applied


def replay_external_scoring_treatments(
    frame: pd.DataFrame,
    *,
    datastore_meta: Mapping[str, Any],
    candidate_contract: Mapping[str, Any],
    expected_project_id: str,
    expected_dataset_id: str,
    expected_dataset_version_id: str,
) -> dict[str, Any]:
    """Verify and replay the frozen treatment contract without global state.

    The input frame and metadata are copied, row order/index are preserved, and
    no DatasetStore or holdout API is imported or consulted.
    """

    if not isinstance(frame, pd.DataFrame):
        _fail(
            "treatment_input_invalid",
            "External scoring treatment replay requires a pandas DataFrame.",
        )
    payload, manifest_hash = _verified_manifest(
        datastore_meta,
        candidate_contract,
        expected_project_id=expected_project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
    )
    target_definition = candidate_contract.get("target_definition")
    target_definition = (
        target_definition if isinstance(target_definition, Mapping) else {}
    )
    target = _text(
        candidate_contract.get("target_name")
        or target_definition.get("target_name")
    )
    special_treatments = _pipeline_special_treatments(
        payload.get("preprocessing_pipeline") or []
    )
    _assert_no_unexecutable_special_review(datastore_meta, special_treatments)

    work, special_applied = _apply_special_values(
        frame, special_treatments, target=target
    )
    work, outlier_applied = _apply_outliers(
        work, payload.get("outlier_application"), target=target
    )
    work, missing_applied = _apply_missing(
        work, payload.get("missing_application"), target=target
    )

    return {
        "frame": work,
        "treatment_manifest_hash": manifest_hash,
        "treatment_manifest_id": _text(
            candidate_contract.get("treatment_manifest_id")
        )
        or f"tm-{manifest_hash[:20]}",
        "applied_special_value_treatments": special_applied,
        "applied_outlier_treatments": outlier_applied,
        "applied_missing_treatments": missing_applied,
        "row_count": int(len(work)),
        "holdout_accessed": False,
        "state_mutated": False,
    }
