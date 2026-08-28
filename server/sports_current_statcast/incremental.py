"""Idempotent nightly orchestration for the current-season Statcast evidence.

The orchestration layer is deliberately model-free.  It coordinates the
existing Bronze acquisition, current Silver normalization, Gold-48 feature
publication, and Data Warehouse registry without importing an estimator or a
scoring path.  Component functions are injectable so the incremental state
machine can be proved without provider calls or large data fixtures.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from server.sports_cockpit.interprocess_lock import LockBusy, interprocess_lock


LATEST_COMPLETED = "latest-completed"
LOCK_BUSY_EXIT = 75


@dataclass(frozen=True)
class CurrentStatcastSyncConfig:
    """All filesystem and policy inputs for one bounded sync attempt."""

    through: str = LATEST_COMPLETED
    correction_lookback: int = 3
    legacy_bronze_root: Path = Path(r"C:\Users\james\asp-data-staging\mlb-advanced-bronze-v1")
    current_bronze_root: Path = Path(r"C:\Users\james\asp-data-staging\mlb-current-statcast-bronze-v1")
    existing_silver_root: Path = Path(r"C:\Users\james\asp-data-staging\mlb-silver-v1")
    current_silver_root: Path = Path(r"C:\Users\james\asp-data-staging\mlb-current-statcast-silver-v1")
    existing_gold_root: Path = Path(r"C:\Users\james\asp-data-staging\mlb-gold-v1")
    current_gold_root: Path = Path(r"C:\Users\james\asp-data-staging\mlb-current-statcast-gold-v1")
    exchange_root: Path = Path(r"C:\Users\james\asp-model-exchange")
    package_root: Path = Path(r"C:\Users\james\asp-data-staging")
    database_path: Path = Path(r".runtime\asp-model-studio\persistence\asp_model_studio.db")
    report_root: Path = Path(r".runtime\asp-model-studio\current-statcast-sync")
    lock_path: Path = Path(r".runtime\asp-model-studio\locks\current-statcast-sync.lock")
    registered_by: str = "nightly-current-statcast-sync"

    def __post_init__(self) -> None:
        if not isinstance(self.correction_lookback, int) or self.correction_lookback < 0:
            raise ValueError("correction_lookback must be a nonnegative integer")
        if not str(self.through).strip():
            raise ValueError("through must be latest-completed or YYYY-MM-DD")


DiscoverCompleted = Callable[[CurrentStatcastSyncConfig], dict[str, Any]]
SyncBronze = Callable[[CurrentStatcastSyncConfig, dict[str, Any], list[str]], dict[str, Any]]
SyncSilver = Callable[[CurrentStatcastSyncConfig, dict[str, Any], dict[str, Any]], dict[str, Any]]
SyncGold = Callable[[CurrentStatcastSyncConfig, dict[str, Any], list[str]], dict[str, Any]]
SyncWarehouse = Callable[
    [CurrentStatcastSyncConfig, dict[str, Any], dict[str, Any], dict[str, Any]],
    dict[str, Any],
]


@dataclass(frozen=True)
class CurrentStatcastSyncDependencies:
    discover_completed: DiscoverCompleted
    sync_bronze: SyncBronze
    sync_silver: SyncSilver
    sync_gold: SyncGold
    sync_warehouse: SyncWarehouse
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(body)
    os.replace(temporary, path)


def _identity_fields(bronze: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "silverPublicationIdentity": bronze.get("currentSilverPublicationIdentity"),
        "goldPublicationIdentity": bronze.get("currentGoldPublicationIdentity"),
        "warehouseRegistrationIdentity": bronze.get("currentWarehouseRegistrationIdentity"),
        "resultingCoverage": dict(bronze.get("currentCoverage") or {}),
    }


def _base_report(
    *,
    attempt: str,
    probe: Mapping[str, Any],
    bronze: Mapping[str, Any],
    inspect_dates: list[str],
) -> dict[str, Any]:
    return {
        "attemptedAtUtc": attempt,
        "requestedThroughDate": probe.get("requestedThroughDate"),
        "priorRegisteredThroughDate": probe.get("priorRegisteredThroughDate"),
        "latestMlbFinalDate": probe.get("latestMlbFinalDate"),
        "datesInspected": inspect_dates,
        "datesAdded": list(bronze.get("datesAdded") or []),
        "datesCorrected": list(bronze.get("datesCorrected") or []),
        "datesUnchanged": list(bronze.get("datesUnchanged") or []),
        "completeEmptyDates": list(bronze.get("completeEmptyDates") or []),
        "failedDates": list(bronze.get("failedDates") or []),
        "expectedFinalGames": int(bronze.get("expectedFinalGames") or 0),
        "representedGames": int(bronze.get("representedGames") or 0),
        "missingGames": int(bronze.get("missingGames") or 0),
        "sourcePitches": int(bronze.get("sourcePitches") or 0),
        "acceptedPitches": int(bronze.get("acceptedPitches") or 0),
        "acceptedPlateAppearances": int(bronze.get("acceptedPlateAppearances") or 0),
        "rejectedPlateAppearances": int(bronze.get("rejectedPlateAppearances") or 0),
        "rejectReasons": dict(bronze.get("rejectReasons") or {}),
        "duplicateCount": int(bronze.get("duplicateCount") or 0),
        "unresolvedCount": int(bronze.get("unresolvedCount") or 0),
        "modelFits": 0,
        **_identity_fields(bronze),
    }


def _inspection_dates(config: CurrentStatcastSyncConfig, probe: Mapping[str, Any]) -> list[str]:
    completed = sorted(str(day) for day in (probe.get("completedGamesByDate") or {}))
    through = str(probe.get("requestedThroughDate") or "")
    prior = str(probe.get("priorRegisteredThroughDate") or "")
    eligible = [day for day in completed if (not through or day <= through)]
    correction_candidates = sorted(
        str(day) for day in (probe.get("correctionEligibleDates") or completed)
    )
    correction_dates = [
        day
        for day in correction_candidates
        if not through or day <= through
    ]
    # ``correction_lookback`` is the number of completed dates preceding the
    # requested through-date.  The requested completed date itself is always
    # included, so the default window contains four completed dates total.
    lookback = correction_dates[-(config.correction_lookback + 1) :]
    new_dates = [day for day in eligible if prior and day > prior]
    if not prior:
        new_dates = eligible
    # A prior attempt may have durably acquired Bronze before a downstream
    # publication failed.  Keep that exact mismatch eligible even after it has
    # aged out of the ordinary rolling correction lookback so the next attempt
    # can finish Silver/Gold/warehouse publication instead of reporting NO_OP.
    pending = [
        str(day)
        for day in (probe.get("pendingBronzeDates") or [])
        if (not through or str(day) <= through)
    ]
    return sorted(set(lookback + new_dates + pending))


def _affected_target_dates(
    probe: Mapping[str, Any], bronze: Mapping[str, Any]
) -> list[str]:
    changed = sorted(
        set(str(day) for day in (bronze.get("datesAdded") or []))
        | set(str(day) for day in (bronze.get("datesCorrected") or []))
    )
    if not changed:
        return []
    first = changed[0]
    through = str(probe.get("requestedThroughDate") or "")
    return sorted(
        str(day)
        for day in (probe.get("completedGamesByDate") or {})
        if str(day) >= first and (not through or str(day) <= through)
    )


def _record_attempt(config: CurrentStatcastSyncConfig, report: Mapping[str, Any]) -> None:
    """Write only ignored operational health; never mutate evidence authority."""

    root = Path(config.report_root)
    _atomic_json(root / "latest-attempt.json", report)
    if report.get("status") in {"COMPLETE", "NO_OP"}:
        _atomic_json(root / "latest-success.json", report)


def _sync_current_statcast_impl(
    config: CurrentStatcastSyncConfig,
    *,
    dependencies: CurrentStatcastSyncDependencies | None = None,
) -> dict[str, Any]:
    """Run one locked, chronological, all-or-nothing incremental attempt."""

    deps = dependencies or default_dependencies()
    with interprocess_lock(config.lock_path, blocking=False, stale_after=12 * 60 * 60):
        attempted = deps.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        probe = deps.discover_completed(config)
        inspect_dates = _inspection_dates(config, probe)
        bronze = deps.sync_bronze(config, probe, inspect_dates)
        report = _base_report(
            attempt=attempted,
            probe=probe,
            bronze=bronze,
            inspect_dates=inspect_dates,
        )

        if bronze.get("status") != "COMPLETE" or report["failedDates"] or report["missingGames"]:
            report["status"] = "FAILED"
            _record_attempt(config, report)
            return report

        changed = bool(report["datesAdded"] or report["datesCorrected"])
        if not changed:
            report["status"] = "NO_OP"
            _record_attempt(config, report)
            return report

        affected = _affected_target_dates(probe, bronze)
        silver = deps.sync_silver(config, bronze, probe)
        if silver.get("status") != "COMPLETE":
            report.update({"status": "FAILED", "failedStage": "SILVER"})
            _record_attempt(config, report)
            return report
        gold = deps.sync_gold(config, silver, affected)
        if gold.get("status") != "COMPLETE" or int(gold.get("modelsFitted") or 0) != 0:
            report.update({"status": "FAILED", "failedStage": "GOLD"})
            _record_attempt(config, report)
            return report

        warehouse = deps.sync_warehouse(config, silver, gold, report)
        if warehouse.get("status") != "COMPLETE":
            report.update({"status": "FAILED", "failedStage": "WAREHOUSE"})
            _record_attempt(config, report)
            return report

        resulting_coverage = dict(warehouse.get("coverage") or {})
        report.update(
            {
                "status": "COMPLETE",
                "affectedGoldTargetDates": affected,
                "silverPublicationIdentity": silver.get("publicationIdentity"),
                "goldPublicationIdentity": gold.get("publicationIdentity"),
                "warehouseRegistrationIdentity": warehouse.get("registrationIdentity"),
                "priorSilverPublicationIdentity": silver.get("priorPublicationIdentity"),
                "priorGoldPublicationIdentity": gold.get("priorPublicationIdentity"),
                "priorWarehouseRegistrationIdentity": warehouse.get("priorRegistrationIdentity"),
                "historicalWarehouseRegistrationIdentities": list(
                    warehouse.get("historicalRegistrationIdentities") or []
                ),
                "resultingCoverage": resulting_coverage,
                "sourcePitches": int(resulting_coverage.get("sourcePitchRows") or report["sourcePitches"]),
                "acceptedPitches": int(resulting_coverage.get("acceptedPitchRows") or 0),
                "acceptedPlateAppearances": int(
                    resulting_coverage.get("acceptedPlateAppearances") or 0
                ),
                "rejectedPlateAppearances": int(
                    resulting_coverage.get("rejectedPlateAppearances") or 0
                ),
                "rejectReasons": dict(resulting_coverage.get("rejectReasons") or {}),
                "modelFits": 0,
            }
        )
        _record_attempt(config, report)
        return report


def sync_current_statcast(
    config: CurrentStatcastSyncConfig,
    *,
    dependencies: CurrentStatcastSyncDependencies | None = None,
) -> dict[str, Any]:
    """Run one attempt and preserve a bounded failed-attempt health record."""

    deps = dependencies or default_dependencies()
    try:
        return _sync_current_statcast_impl(config, dependencies=deps)
    except LockBusy:
        raise
    except Exception as exc:
        attempted = deps.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        report = {
            "status": "FAILED",
            "attemptedAtUtc": attempted,
            "requestedThroughDate": str(config.through),
            "failedStage": "UNEXPECTED",
            "errorType": type(exc).__name__,
            "error": str(exc)[:500],
            "modelFits": 0,
        }
        _record_attempt(config, report)
        return report


def default_dependencies() -> CurrentStatcastSyncDependencies:
    """Load concrete dependencies lazily to keep this module model-free."""

    from .incremental_runtime import concrete_dependencies

    return concrete_dependencies()


__all__ = [
    "CurrentStatcastSyncConfig",
    "CurrentStatcastSyncDependencies",
    "LATEST_COMPLETED",
    "LOCK_BUSY_EXIT",
    "sync_current_statcast",
]
