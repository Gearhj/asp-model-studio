"""Activate the frozen NFL M1 2026 research-shadow forecast exchange."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from server.sports_nfl_m1.prospective_shadow import (
    ARTIFACT_ROOT,
    DEFAULT_EXCHANGE_ROOT,
    DEFAULT_PUBLICATION_ROOT,
    DEFAULT_NFL_STAGING_ROOT,
    activate_2026_shadow,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundation-root", type=Path, default=DEFAULT_NFL_STAGING_ROOT / "foundation-v1")
    parser.add_argument("--artifact-root", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument("--publication-root", type=Path, default=DEFAULT_PUBLICATION_ROOT)
    parser.add_argument("--exchange-root", type=Path, default=DEFAULT_EXCHANGE_ROOT)
    parser.add_argument("--as-of", help="Explicit timezone-aware cutoff; defaults to current UTC.")
    parser.add_argument("--producer-revision")
    parser.add_argument(
        "--snapshot-type",
        action="append",
        choices=("EARLY", "CURRENT", "FINAL_PREGAME"),
        dest="snapshot_types",
        help="Repeat to select snapshot types; default is EARLY plus CURRENT.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    as_of = None if args.as_of is None else datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    result = activate_2026_shadow(
        foundation_root=args.foundation_root,
        artifact_root=args.artifact_root,
        publication_root=args.publication_root,
        exchange_root=args.exchange_root,
        as_of=as_of,
        snapshot_types=tuple(args.snapshot_types or ("EARLY", "CURRENT")),
        producer_revision=args.producer_revision,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"ACTIVE", "NO_ELIGIBLE_UPCOMING_GAMES"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
