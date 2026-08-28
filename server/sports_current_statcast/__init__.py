"""Bounded 2023--2026 Statcast evidence extension.

The package is additive.  It does not alter the frozen Phase 7B1 Silver or
Gold V1 authorities and never fits a model.
"""

from .pipeline import (
    CURRENT_DATASET_ID,
    CURRENT_SILVER_CONTRACT,
    CurrentStatcastPipelineError,
    build_current_silver,
    verify_current_silver,
)
from .gold import build_current_gold, verify_current_gold

__all__ = [
    "CURRENT_DATASET_ID",
    "CURRENT_SILVER_CONTRACT",
    "CurrentStatcastPipelineError",
    "build_current_silver",
    "build_current_gold",
    "verify_current_gold",
    "verify_current_silver",
]
