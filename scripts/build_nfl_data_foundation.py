"""Acquire, normalize, publish, and register the NFL data foundation.

This command is data-only.  It has no model fit, score, calibration,
comparison, or promotion path.  All source and generated Parquet files remain
under the external NFL staging root.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.sports_nfl.pipeline import ALL_SEASONS, DEFAULT_STAGING_ROOT, NflFoundationConfig, build_nfl_foundation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, default=DEFAULT_STAGING_ROOT)
    parser.add_argument(
        "--database", type=Path,
        default=Path(r".runtime\asp-model-studio\persistence\asp_model_studio.db"),
    )
    parser.add_argument("--registered-by", default="nfl-foundation-builder")
    parser.add_argument("--mandatory-only", action="store_true")
    parser.add_argument(
        "--reuse-verified-bronze",
        action="store_true",
        help="Rebuild canonical/Foundation outputs from the current deeply verified Bronze manifest without provider discovery or downloads.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = build_nfl_foundation(
            NflFoundationConfig(
                staging_root=args.staging_root,
                database_path=args.database,
                registered_by=args.registered_by,
                seasons=ALL_SEASONS,
                include_optional=not args.mandatory_only,
                acquire_sources=not args.reuse_verified_bronze,
            )
        )
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "errorType": type(exc).__name__, "error": str(exc)[:1000]}, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
