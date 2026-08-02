"""Model-governance contracts shared across training, evaluation, and registry."""

from .selection_integrity import (
    ALLOWED_SELECTION_SOURCES,
    INVALID_FINAL_HOLDOUT_RANKING,
    LEGACY_UNRESOLVED,
    VERIFIED_SELECTION,
    SelectionIntegrityError,
    assert_evaluation_package_integrity,
    assert_locked_candidate_decision,
    assert_selection_integrity,
    classify_selection_integrity,
)

__all__ = [
    "ALLOWED_SELECTION_SOURCES",
    "INVALID_FINAL_HOLDOUT_RANKING",
    "LEGACY_UNRESOLVED",
    "VERIFIED_SELECTION",
    "SelectionIntegrityError",
    "assert_evaluation_package_integrity",
    "assert_locked_candidate_decision",
    "assert_selection_integrity",
    "classify_selection_integrity",
]
