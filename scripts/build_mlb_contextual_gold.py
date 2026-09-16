"""Build or independently verify the immutable MLB contextual Gold extension.

This command performs feature engineering only. It has no model fitting,
scoring, calibration, selection, or promotion path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.sports_current_statcast.contextual_gold import (
    DEFAULT_CONTEXT_GOLD_ROOT,
    DEFAULT_CURRENT_GOLD_ROOT,
    build_contextual_gold,
    issue_contextual_verification_receipt,
    verify_contextual_gold,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-gold-root", type=Path, default=DEFAULT_CURRENT_GOLD_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_CONTEXT_GOLD_ROOT)
    parser.add_argument("--current-gold-manifest-sha256")
    parser.add_argument("--context-manifest-sha256")
    parser.add_argument("--recompute-date", action="append", default=[])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument(
        "--issue-verification-receipt",
        action="store_true",
        help="Deep-verify the existing current/named manifest and bind a metadata-only receipt; rebuilds no objects.",
    )
    parser.add_argument("--no-publish-current", action="store_true")
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.issue_verification_receipt:
        if args.recompute_date or args.no_publish_current or args.current_gold_manifest_sha256:
            raise SystemExit(
                "--issue-verification-receipt cannot be combined with build-only options"
            )
        result = issue_contextual_verification_receipt(
            args.output_root,
            args.context_manifest_sha256,
            current_gold_root=args.current_gold_root,
        )
    elif args.verify_only:
        result = verify_contextual_gold(
            args.output_root,
            args.context_manifest_sha256,
            current_gold_root=args.current_gold_root,
        )
    else:
        result = build_contextual_gold(
            current_gold_root=args.current_gold_root,
            output_root=args.output_root,
            current_gold_manifest_sha256=args.current_gold_manifest_sha256,
            recompute_dates=args.recompute_date,
            publish_current=not args.no_publish_current,
        )
    if args.summary:
        result = {
            key: result.get(key)
            for key in (
                "datasetId", "manifestSha256", "sourceGoldManifestSha256",
                "rowCount", "teamGameRowCount", "coreFeatureCount",
                "addedFeatureCount", "totalFeatureCount", "modelsFitted",
                "modelsScored", "modelsCalibrated", "modelPromoted", "verified",
                "verificationReceiptSha256", "verificationReceiptPath",
            )
            if key in result
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
