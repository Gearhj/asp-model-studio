from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any


VERIFIED_SELECTION = "verified"
LEGACY_UNRESOLVED = "legacy_unresolved"
INVALID_FINAL_HOLDOUT_RANKING = "invalid_final_holdout_ranking"

ALLOWED_SELECTION_SOURCES = frozenset(
    {
        "cross_validation_mean",
        "out_of_fold",
        "training_validation_partition",
    }
)

# This record was directly observed during Phase 2B1 acceptance.  Its final
# holdout PR-AUC was also the value displayed as selection evidence.  The
# evidence remains preserved, but it can never unlock Evaluation or promotion.
KNOWN_CONTAMINATED_IDENTIFIERS = {
    "training_job_id": "train-job-b59a7bf338784dac882cfe17ade06af0",
    "training_run_id": "train-run-f1af457df46e492483054ecbf95061f4",
    "candidate_id": "candidate-7925f986465de3fc97d9b727",
    "candidate_decision_id": "model-decision-3fb7f4ab032fc551",
    "evaluation_package_id": "evalpkg-41bad836447384a03547ff3e",
}


class SelectionIntegrityError(ValueError):
    """Raised when selection/holdout governance cannot be proven."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _selection_metric(record: Mapping[str, Any]) -> Mapping[str, Any]:
    metric = record.get("selection_metric")
    if isinstance(metric, Mapping):
        return metric
    evidence = record.get("selection_evidence")
    if isinstance(evidence, Mapping):
        nested = evidence.get("selection_metric")
        return nested if isinstance(nested, Mapping) else evidence
    return {}


def _metric_value(metric: Mapping[str, Any]) -> Any:
    for key in ("value", "selection_metric_value", "mean"):
        if metric.get(key) is not None:
            return metric.get(key)
    return None


def _metric_name(metric: Mapping[str, Any]) -> str:
    return _text(metric.get("name") or metric.get("selection_metric_name"))


def _metric_source(metric: Mapping[str, Any]) -> str:
    return _text(metric.get("source") or metric.get("selection_metric_source")).casefold()


def _matches_known_contamination(record: Mapping[str, Any]) -> bool:
    return any(
        _text(record.get(key)) == expected
        for key, expected in KNOWN_CONTAMINATED_IDENTIFIERS.items()
    )


def classify_selection_integrity(
    record: Mapping[str, Any] | None,
) -> tuple[str, str]:
    """Classify without guessing.

    Only explicit, internally consistent non-holdout provenance is verified.
    Evidence-proven Phase 2B1 contamination is invalid.  Older records with no
    provenance stay visible as legacy-unresolved rather than being rewritten.
    """

    if not isinstance(record, Mapping):
        return LEGACY_UNRESOLVED, "Selection provenance is unavailable."
    if _matches_known_contamination(record):
        return (
            INVALID_FINAL_HOLDOUT_RANKING,
            "Acceptance evidence proves that final-holdout performance ranked this candidate.",
        )
    metric = _selection_metric(record)
    if not metric:
        return LEGACY_UNRESOLVED, "The record predates explicit selection-metric provenance."
    source = _metric_source(metric)
    if source == "final_holdout" or bool(metric.get("holdout_used")):
        return (
            INVALID_FINAL_HOLDOUT_RANKING,
            "The selection metric consumed the final holdout.",
        )
    declared = _text(
        record.get("selection_integrity_status")
        or metric.get("selection_integrity_status")
    ).casefold()
    isolation = _text(
        record.get("holdout_isolation_status")
        or metric.get("holdout_isolation_status")
    ).casefold()
    required_text = {
        "selection metric name": _metric_name(metric),
        "selection metric source": source,
        "selection partition": _text(
            metric.get("partition_id") or metric.get("selection_partition_id")
        ),
        "fold definition": _text(metric.get("fold_definition_id")),
        "threshold source": _text(metric.get("threshold_source")),
        "calibration source": _text(metric.get("calibration_source")),
        "created_at": _text(metric.get("created_at")),
    }
    missing = [label for label, value in required_text.items() if not value]
    fold_values = metric.get("fold_values")
    try:
        fold_count = int(metric.get("fold_count") or 0)
    except (TypeError, ValueError):
        fold_count = 0
    if source not in ALLOWED_SELECTION_SOURCES:
        return LEGACY_UNRESOLVED, f"Unsupported selection metric source: {source or 'missing'}."
    if missing:
        return LEGACY_UNRESOLVED, "Selection provenance is incomplete: " + ", ".join(missing) + "."
    if not _finite_number(_metric_value(metric)):
        return LEGACY_UNRESOLVED, "The selection metric value is missing or non-finite."
    if fold_count < 1 or not isinstance(fold_values, list) or len(fold_values) != fold_count:
        return LEGACY_UNRESOLVED, "The governed fold evidence is incomplete."
    if not all(_finite_number(value) for value in fold_values):
        return LEGACY_UNRESOLVED, "The governed fold evidence contains a non-finite value."
    if declared != VERIFIED_SELECTION:
        return LEGACY_UNRESOLVED, "Selection integrity has not been explicitly verified."
    if isolation != VERIFIED_SELECTION:
        return LEGACY_UNRESOLVED, "Final-holdout isolation has not been explicitly verified."
    return VERIFIED_SELECTION, "Selection used governed training-only validation evidence."


def assert_selection_integrity(record: Mapping[str, Any] | None) -> Mapping[str, Any]:
    status, reason = classify_selection_integrity(record)
    if status != VERIFIED_SELECTION:
        raise SelectionIntegrityError(f"Selection integrity is {status}: {reason}")
    assert isinstance(record, Mapping)
    return _selection_metric(record)


def assert_locked_candidate_decision(
    decision: Mapping[str, Any] | None,
    candidate: Mapping[str, Any],
) -> Mapping[str, Any]:
    if not isinstance(decision, Mapping):
        raise SelectionIntegrityError(
            "The final holdout is sealed until an exact candidate decision is locked."
        )
    if _matches_known_contamination(decision):
        raise SelectionIntegrityError(
            "The candidate decision is non-promotable because final-holdout performance ranked it."
        )
    required = (
        "decision_id",
        "selected_candidate_id",
        "training_run_id",
        "selection_ranking_snapshot_hash",
        "selection_locked_at",
    )
    missing = [key for key in required if not _text(decision.get(key))]
    if missing:
        raise SelectionIntegrityError(
            "The candidate decision is not an immutable lock: " + ", ".join(missing) + "."
        )
    if _text(decision.get("status")).casefold() != "locked":
        raise SelectionIntegrityError("The candidate decision is not locked.")
    exact_pairs = (
        ("selected_candidate_id", "candidate_id"),
        ("training_run_id", "training_run_id"),
        ("training_job_id", "training_job_id"),
        ("project_id", "project_id"),
        ("dataset_id", "dataset_id"),
        ("dataset_version_id", "dataset_version_id"),
        ("feature_manifest_version", "feature_manifest_version"),
        ("validation_design_id", "validation_design_id"),
        ("validation_design_version", "validation_design_version"),
        ("split_id", "split_id"),
    )
    for decision_key, candidate_key in exact_pairs:
        decision_value = _text(decision.get(decision_key))
        candidate_value = _text(candidate.get(candidate_key))
        if not decision_value or not candidate_value or decision_value != candidate_value:
            raise SelectionIntegrityError(
                f"The locked candidate decision conflicts with {candidate_key}."
            )
    candidate_metric = assert_selection_integrity(candidate)
    decision_metric = assert_selection_integrity(decision)
    for label, candidate_value, decision_value in (
        ("name", _metric_name(candidate_metric), _metric_name(decision_metric)),
        ("source", _metric_source(candidate_metric), _metric_source(decision_metric)),
        ("value", _metric_value(candidate_metric), _metric_value(decision_metric)),
        (
            "fold definition",
            _text(candidate_metric.get("fold_definition_id")),
            _text(decision_metric.get("fold_definition_id")),
        ),
    ):
        if candidate_value != decision_value:
            raise SelectionIntegrityError(
                f"The locked decision selection metric conflicts with the candidate {label}."
            )
    return decision


def assert_evaluation_package_integrity(
    package: Mapping[str, Any] | None,
    *,
    decision: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> Mapping[str, Any]:
    if not isinstance(package, Mapping):
        raise SelectionIntegrityError("A complete governed Evaluation package is required.")
    if _matches_known_contamination(package):
        raise SelectionIntegrityError(
            "The Evaluation package is non-promotable because final-holdout performance ranked its candidate."
        )
    assert_locked_candidate_decision(decision, candidate)
    if _text(package.get("status")).casefold() != "complete":
        raise SelectionIntegrityError("The Evaluation package is incomplete.")
    if _text(package.get("candidate_decision_id")) != _text(decision.get("decision_id")):
        raise SelectionIntegrityError("The Evaluation package does not bind the locked candidate decision.")
    if _text(package.get("candidate_id")) != _text(candidate.get("candidate_id")):
        raise SelectionIntegrityError("The Evaluation package does not bind the exact candidate.")
    assert_selection_integrity(package)
    if _text(package.get("isolation_status")).casefold() != VERIFIED_SELECTION:
        raise SelectionIntegrityError("The Evaluation package does not prove final-holdout isolation.")
    exposure = package.get("holdout_exposure")
    if not isinstance(exposure, Mapping) or _text(exposure.get("status")).casefold() != "evaluated":
        raise SelectionIntegrityError("The Evaluation package has no evaluated holdout exposure record.")
    if not _text(exposure.get("first_opened_at")):
        raise SelectionIntegrityError("The Evaluation package has no first holdout exposure timestamp.")
    if bool(package.get("recommendations_derived_from_final_holdout")):
        raise SelectionIntegrityError("The Evaluation package derived recommendations from the final holdout.")
    if not isinstance(package.get("selection_evidence"), Mapping):
        raise SelectionIntegrityError("The Evaluation package is missing selection evidence.")
    if not isinstance(package.get("final_holdout_evidence"), Mapping):
        raise SelectionIntegrityError("The Evaluation package is missing final-holdout evidence.")
    return package
