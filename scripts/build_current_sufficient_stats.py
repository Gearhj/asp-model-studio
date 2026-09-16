"""Build, verify, or register the sealed MLB sufficient-statistics companion.

This command has no model fitting, scoring, calibration, policy-adoption,
feature-set, project-activation, final-OOT transformation, or promotion path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.persistence.db import Database
from server.sports_current_statcast.sufficient_stats import (
    DEFAULT_CURRENT_GOLD_ROOT,
    DEFAULT_CURRENT_SILVER_ROOT,
    DEFAULT_EXCHANGE_ROOT,
    DEFAULT_EXISTING_SILVER_ROOT,
    build_current_sufficient_stats,
    register_current_sufficient_stats,
    verify_current_sufficient_stats,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-silver-root", type=Path, default=DEFAULT_CURRENT_SILVER_ROOT)
    parser.add_argument("--existing-silver-root", type=Path, default=DEFAULT_EXISTING_SILVER_ROOT)
    parser.add_argument("--current-gold-root", type=Path, default=DEFAULT_CURRENT_GOLD_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_CURRENT_GOLD_ROOT)
    parser.add_argument("--exchange-root", type=Path, default=DEFAULT_EXCHANGE_ROOT)
    parser.add_argument("--current-silver-manifest-sha256")
    parser.add_argument("--current-gold-manifest-sha256")
    parser.add_argument("--companion-manifest-sha256")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--register-only", action="store_true")
    parser.add_argument("--no-publish-current", action="store_true")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--registered-by", default="wave1-sufficient-stats-local-operator")
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.register_only:
        if args.database is None:
            raise SystemExit("--register-only requires an explicit --database path")
        result = register_current_sufficient_stats(
            Database(args.database),
            output_root=args.output_root,
            manifest_sha256=args.companion_manifest_sha256,
            current_gold_root=args.current_gold_root,
            registered_by=args.registered_by,
        )
    elif args.verify_only:
        if args.no_publish_current or args.database is not None:
            raise SystemExit("--verify-only cannot be combined with build/register options")
        result = verify_current_sufficient_stats(
            args.output_root,
            args.companion_manifest_sha256,
            current_gold_root=args.current_gold_root,
        )
    else:
        if args.database is not None or args.companion_manifest_sha256 is not None:
            raise SystemExit("build mode does not accept registration/companion identity options")
        result = build_current_sufficient_stats(
            current_silver_root=args.current_silver_root,
            existing_silver_root=args.existing_silver_root,
            current_gold_root=args.current_gold_root,
            exchange_root=args.exchange_root,
            output_root=args.output_root,
            current_silver_manifest_sha256=args.current_silver_manifest_sha256,
            current_gold_manifest_sha256=args.current_gold_manifest_sha256,
            publish_current=not args.no_publish_current,
        )
    if args.summary:
        result = {
            key: result.get(key)
            for key in (
                "datasetId",
                "manifestSha256",
                "objectSha256",
                "rowCount",
                "developmentRowCount",
                "finalOotKeyRowCount",
                "registrationId",
                "registrationDisposition",
                "rightsRowCount",
                "verified",
            )
            if key in result
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
