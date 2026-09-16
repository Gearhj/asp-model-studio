"""Synchronize the governed NFL current-season data foundation.

Examples:
    python -m scripts.sync_nfl_current_season --through latest-completed
    python -m scripts.sync_nfl_current_season --mode thursday-correction
    python -m scripts.sync_nfl_current_season --mode schedule-refresh
    python -m scripts.sync_nfl_current_season --mode catch-up

This command only acquires and republishes governed data evidence.  It has no
model-fit, scoring, calibration, selection, or promotion path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.sports_cockpit.interprocess_lock import LockBusy
from server.sports_nfl.current_season_sync import (
    LATEST_COMPLETED,
    LOCK_BUSY_EXIT,
    NIGHTLY,
    SYNC_MODES,
    NflCurrentSeasonSyncConfig,
    sync_nfl_current_season,
)
from server.sports_nfl.pipeline import (
    ALL_SEASONS,
    DEFAULT_STAGING_ROOT,
    NflFoundationConfig,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", default=LATEST_COMPLETED)
    parser.add_argument("--mode", choices=SYNC_MODES, default=NIGHTLY)
    parser.add_argument("--staging-root", type=Path, default=DEFAULT_STAGING_ROOT)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(r".runtime\asp-model-studio\persistence\asp_model_studio.db"),
    )
    parser.add_argument(
        "--report-root",
        type=Path,
        default=Path(r".runtime\asp-model-studio\nfl-current-season-sync"),
    )
    parser.add_argument(
        "--lock-path",
        type=Path,
        default=Path(r".runtime\asp-model-studio\locks\nfl-current-season-sync.lock"),
    )
    parser.add_argument("--registered-by", default="nfl-current-season-sync")
    parser.add_argument(
        "--mandatory-only",
        action="store_true",
        help="Exclude optional enrichment families while preserving the mandatory foundation.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    foundation = NflFoundationConfig(
        staging_root=args.staging_root,
        database_path=args.database,
        registered_by=args.registered_by,
        seasons=ALL_SEASONS,
        include_optional=not args.mandatory_only,
    )
    config = NflCurrentSeasonSyncConfig(
        foundation=foundation,
        through=args.through,
        mode=args.mode,
        report_root=args.report_root,
        lock_path=args.lock_path,
    )
    try:
        report = sync_nfl_current_season(config)
    except LockBusy as exc:
        print(json.dumps({"status": "LOCK_BUSY", "error": str(exc)}, sort_keys=True))
        return LOCK_BUSY_EXIT
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "errorType": type(exc).__name__,
                    "error": str(exc)[:500],
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") in {"COMPLETE", "NO_OP"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
