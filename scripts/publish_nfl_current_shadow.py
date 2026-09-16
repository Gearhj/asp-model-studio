"""Publish one current NFL M1 research-shadow slate and its AISP handoff."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from server.sports_nfl_m1.current_shadow import DEFAULT_HANDOFF_ROOT, publish_current_slate_handoff
from server.sports_nfl_m1.prospective_shadow import (
    ARTIFACT_ROOT,
    DEFAULT_EXCHANGE_ROOT,
    DEFAULT_NFL_STAGING_ROOT,
    DEFAULT_PUBLICATION_ROOT,
    activate_2026_shadow,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundation-root", type=Path, default=DEFAULT_NFL_STAGING_ROOT / "foundation-v1")
    parser.add_argument("--artifact-root", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument("--publication-root", type=Path, default=DEFAULT_PUBLICATION_ROOT)
    parser.add_argument("--exchange-root", type=Path, default=DEFAULT_EXCHANGE_ROOT)
    parser.add_argument("--handoff-root", type=Path, default=DEFAULT_HANDOFF_ROOT)
    parser.add_argument("--as-of", help="Explicit timezone-aware cutoff; defaults to current UTC.")
    parser.add_argument("--slate-date", type=date.fromisoformat, help="Exact slate date; default is the next scheduled slate.")
    parser.add_argument("--producer-revision")
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
        slate_date=args.slate_date,
        next_slate_only=args.slate_date is None,
    )
    if activation.get("status") != "ACTIVE":
        print(json.dumps({"activation": activation}, indent=2, sort_keys=True))
        return 1
    selected_dates = activation.get("selectedSlateDates") or []
    if len(selected_dates) != 1:
        raise RuntimeError("bounded current-slate activation did not select exactly one slate")
    handoff = publish_current_slate_handoff(
        date.fromisoformat(selected_dates[0]),
        output_root=args.handoff_root,
        exchange_root=args.exchange_root,
        foundation_root=args.foundation_root,
        artifact_root=args.artifact_root,
        publication_root=args.publication_root,
        refresh_evidence=activation,
    )
    print(json.dumps({"activation": activation, "handoff": handoff}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
