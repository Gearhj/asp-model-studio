"""Publish or inspect one prospective MLB V18 research-shadow slate."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_current_statcast.mlb_v18_daily_slate import (
    AispReadOnlySlateSource,
    PublishConfig,
    publish_daily_slate,
    read_status,
    rebuild_slate_handoff,
)
from server.sports_current_statcast.mlb_v18_daily_views import backfill_slate_views


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--date", type=date.fromisoformat,
                       default=datetime.now(ZoneInfo("America/New_York")).date(), dest="slate_date")
    value.add_argument("--horizon-hours", type=int, default=24)
    value.add_argument("--game", action="append", default=[], dest="game_ids")
    value.add_argument("--limit", type=int)
    value.add_argument("--dry-run", action="store_true")
    value.add_argument("--status", action="store_true")
    value.add_argument("--rebuild-handoff", action="store_true")
    value.add_argument("--backfill-views", action="store_true")
    value.add_argument("--output-root", type=Path, default=ROOT / "outputs/mlb-v18-daily-slate")
    value.add_argument("--workers", type=int, default=1)
    value.add_argument("--aisp-root", type=Path, default=Path(r"C:\Users\james\ai-sports-predictor"))
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.status:
        print(json.dumps(read_status(args.output_root, args.slate_date), sort_keys=True))
        return 0
    if args.backfill_views:
        result = backfill_slate_views(
            args.output_root,
            args.slate_date,
            repo_root=ROOT,
            workers=args.workers,
            game_ids=args.game_ids,
            progress=lambda row: print(json.dumps({"stage": "VIEW_BACKFILL", **row}, sort_keys=True), flush=True),
        )
        if result["gamesFailed"] == 0:
            result["handoff"] = rebuild_slate_handoff(args.output_root, args.slate_date)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["gamesFailed"] == 0 else 2
    if args.rebuild_handoff:
        print(json.dumps(rebuild_slate_handoff(args.output_root, args.slate_date), sort_keys=True))
        return 0
    config = PublishConfig(
        slate_date=args.slate_date,
        horizon_hours=args.horizon_hours,
        game_ids=tuple(args.game_ids),
        limit=args.limit,
        workers=args.workers,
        dry_run=args.dry_run,
        output_root=args.output_root,
    )
    source = AispReadOnlySlateSource(args.aisp_root)
    try:
        result = publish_daily_slate(config, source, repo_root=ROOT)
    finally:
        source.close()
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("gamesFailed", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
