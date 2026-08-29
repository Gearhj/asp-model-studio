"""Incrementally sync completed current-season MLB Statcast evidence.

Usage:
    python -m scripts.sync_mlb_current_statcast --through latest-completed
    python -m scripts.sync_mlb_current_statcast --through 2026-08-28

This command acquires and publishes evidence only.  It has no model-fit,
scoring, selection, calibration, or promotion path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from server.sports_cockpit.interprocess_lock import LockBusy
from server.sports_current_statcast.incremental import (
    LOCK_BUSY_EXIT,
    CurrentStatcastSyncConfig,
    sync_current_statcast,
)


DEFAULT_STAGING = Path(r"C:\Users\james\asp-data-staging")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", default="latest-completed")
    parser.add_argument("--correction-lookback", type=int, default=3)
    parser.add_argument("--legacy-bronze-root", type=Path, default=DEFAULT_STAGING / "mlb-advanced-bronze-v1")
    parser.add_argument("--current-bronze-root", type=Path, default=DEFAULT_STAGING / "mlb-current-statcast-bronze-v1")
    parser.add_argument("--existing-silver-root", type=Path, default=DEFAULT_STAGING / "mlb-silver-v1")
    parser.add_argument("--current-silver-root", type=Path, default=DEFAULT_STAGING / "mlb-current-statcast-silver-v1")
    parser.add_argument("--existing-gold-root", type=Path, default=DEFAULT_STAGING / "mlb-gold-v1")
    parser.add_argument("--current-gold-root", type=Path, default=DEFAULT_STAGING / "mlb-current-statcast-gold-v1")
    parser.add_argument("--contextual-gold-root", type=Path, default=DEFAULT_STAGING / "mlb-current-statcast-context-gold-v2")
    parser.add_argument("--exchange-root", type=Path, default=Path(r"C:\Users\james\asp-model-exchange"))
    parser.add_argument("--package-root", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--database", type=Path, default=Path(".runtime/asp-model-studio/persistence/asp_model_studio.db"))
    parser.add_argument("--report-root", type=Path, default=Path(".runtime/asp-model-studio/current-statcast-sync"))
    parser.add_argument("--lock-path", type=Path, default=Path(".runtime/asp-model-studio/locks/current-statcast-sync.lock"))
    parser.add_argument("--registered-by", default="nightly-current-statcast-sync")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = CurrentStatcastSyncConfig(
        through=args.through,
        correction_lookback=args.correction_lookback,
        legacy_bronze_root=args.legacy_bronze_root,
        current_bronze_root=args.current_bronze_root,
        existing_silver_root=args.existing_silver_root,
        current_silver_root=args.current_silver_root,
        existing_gold_root=args.existing_gold_root,
        current_gold_root=args.current_gold_root,
        contextual_gold_root=args.contextual_gold_root,
        exchange_root=args.exchange_root,
        package_root=args.package_root,
        database_path=args.database,
        report_root=args.report_root,
        lock_path=args.lock_path,
        registered_by=args.registered_by,
    )
    try:
        report = sync_current_statcast(config)
    except LockBusy as exc:
        print(json.dumps({"status": "LOCK_BUSY", "error": str(exc)}, sort_keys=True))
        return LOCK_BUSY_EXIT
    except Exception as exc:
        # Provider URLs carry no credential.  Do not emit environment state or a
        # traceback from an unattended job; the bounded error type/message is
        # sufficient for the retry log.
        print(
            json.dumps(
                {"status": "FAILED", "errorType": type(exc).__name__, "error": str(exc)[:500]},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") in {"COMPLETE", "NO_OP"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
