"""Publish one exact-object eligibility batch for all 16 NFL Week 2 games."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_nfl_m1.week2_paper_eligibility import publish_week2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange-root", type=Path, default=Path(r"C:\Users\james\asp-model-exchange"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs/nfl-week2-paper-eligibility-20260915-v1"))
    parser.add_argument("--readiness", type=Path, default=Path("outputs/four-sport-operational-handoff-20260915-v1/nfl-week-2-readiness.json"))
    parser.add_argument("--authorization-source", type=Path, required=True)
    parser.add_argument("--published-utc")
    args = parser.parse_args()
    result = publish_week2(
        exchange_root=args.exchange_root,
        output_root=args.output_root,
        readiness_path=args.readiness,
        authorization_source_path=args.authorization_source,
        published_utc=args.published_utc,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
