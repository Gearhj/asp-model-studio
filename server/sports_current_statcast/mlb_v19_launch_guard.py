"""Code-pinned integrity hold for the original date-only V19 study attempt.

This is deliberately not a settings switch or a receipt-controlled gate. The
original attempt cannot resume, evaluate, or become an executable candidate
while suspended-game PA availability is unresolved. Lifting the hold requires
an explicitly reviewed implementation/authority successor; existing partial
artifacts remain preserved and do not supply that authority.
"""
from __future__ import annotations


HOLD_ID = "MLB_V19_SUSPENDED_GAME_AVAILABILITY_HOLD_V1"


class V19StudyIntegrityHold(RuntimeError):
    """The original V19 attempt is scientifically ineligible to advance."""


def require_v19_launch_authority(stage: str) -> None:
    """Fail before data loading or fitting; no CLI, environment or JSON bypass."""
    raise V19StudyIntegrityHold(
        f"{HOLD_ID}: {stage} is blocked. The original V19 date-only history "
        "does not establish suspended/resumed plate-appearance availability "
        "at historical cutoffs. Preserve all partial results as held evidence. "
        "A reviewed completion-time-safe implementation and explicit successor "
        "study authority are required; a Boolean receipt, CLI option, or "
        "environment variable cannot release this hold. No data load, fit, "
        "evaluation, or candidate packaging is authorized by this entry point."
    )
