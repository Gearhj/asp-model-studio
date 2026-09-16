"""Run independent source steps without hidden retries or stale substitution.

This is the producer-side reference contract for the AISP MLB refresh repair.
Each supplied operation is attempted exactly once.  A failure is recorded for
that operation and does not prevent later independent operations from running.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable


@dataclass(frozen=True)
class SourceStep:
    name: str
    operation: Callable[[], Awaitable[Any]]


async def run_independent_source_steps(
    steps: Iterable[SourceStep], *, expected_error: type[BaseException] | tuple[type[BaseException], ...]
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    values: dict[str, Any] = {}
    for step in steps:
        record = {"family": step.name, "attemptCount": 1, "automaticRetriesAdded": 0}
        try:
            values[step.name] = await step.operation()
            record.update({"status": "COMPLETED", "errorType": None, "error": None})
        except expected_error as exc:
            record.update({
                "status": "FAILED",
                "errorType": type(exc).__name__,
                "error": str(exc),
            })
        attempts.append(record)
    return {
        "attempts": attempts,
        "values": values,
        "attemptCount": len(attempts),
        "completedCount": sum(item["status"] == "COMPLETED" for item in attempts),
        "failedCount": sum(item["status"] == "FAILED" for item in attempts),
        "automaticRetriesAdded": 0,
        "staleEvidenceSubstituted": False,
    }
