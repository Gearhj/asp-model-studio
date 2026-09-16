"""Publish a bounded rolling NFL M1 research-shadow window."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from server.sports_nfl_m1.current_shadow import publish_current_slate_handoff
from server.sports_nfl_m1.prospective_shadow import (
    ARTIFACT_ROOT,
    DEFAULT_EXCHANGE_ROOT,
    DEFAULT_NFL_STAGING_ROOT,
    DEFAULT_PUBLICATION_ROOT,
    activate_2026_shadow,
)
from server.sports_nfl_m1.rolling_publication import (
    DEFAULT_ROLLING_HANDOFF_ROOT,
    publish_rolling_handoff,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundation-root", type=Path, default=DEFAULT_NFL_STAGING_ROOT / "foundation-v1")
    parser.add_argument("--artifact-root", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument("--publication-root", type=Path, default=DEFAULT_PUBLICATION_ROOT)
    parser.add_argument("--exchange-root", type=Path, default=DEFAULT_EXCHANGE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROLLING_HANDOFF_ROOT)
    parser.add_argument("--as-of", help="Explicit timezone-aware cutoff; defaults to current UTC.")
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--producer-revision")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    as_of = None if args.as_of is None else datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    activation = activate_2026_shadow(
        foundation_root=args.foundation_root,
        artifact_root=args.artifact_root,
        publication_root=args.publication_root,
        exchange_root=args.exchange_root,
        as_of=as_of,
        snapshot_types=("CURRENT",),
        producer_revision=args.producer_revision,
        rolling_window_days=args.window_days,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(json.dumps({"activation": activation}, indent=2, sort_keys=True))
        return 0 if activation.get("status") == "DRY_RUN" else 1
    if activation.get("status") != "ACTIVE":
        print(json.dumps({"activation": activation}, indent=2, sort_keys=True))
        return 1
    slate_handoffs = [
        publish_current_slate_handoff(
            date.fromisoformat(slate_date),
            output_root=args.output_root / "slates",
            exchange_root=args.exchange_root,
            foundation_root=args.foundation_root,
            artifact_root=args.artifact_root,
            publication_root=args.publication_root,
            refresh_evidence=activation,
        )
        for slate_date in activation["selectedSlateDates"]
    ]
    handoff = publish_rolling_handoff(
        activation,
        slate_handoffs,
        output_root=args.output_root,
        staging_root=args.foundation_root.parent,
    )
    print(json.dumps({"activation": activation, "handoff": handoff}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
