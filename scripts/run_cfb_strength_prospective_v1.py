"""Repeatable private research tick; zero acquisition and production writes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from sports_cfb_gen1.prospective_collection import run_tick
from sports_cfb_gen1.strength_study import clean
from threadpoolctl import threadpool_limits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(
        r"C:\Users\james\asp-model-studio\outputs\cfb-strength-prospective-v1"))
    args = parser.parse_args()
    # No --as-of or other backdating override is exposed to operational callers.
    with threadpool_limits(limits=1):
        result = run_tick(args.output)
    # Full evidence resides in immutable local receipts, not this compact log.
    print(json.dumps(clean({k: v for k, v in result.items() if k not in {"newPairs", "excludedAttempts"}}), indent=2))
    if result.get("excludedAttempts"):
        print(json.dumps({"excludedAttempts": len(result["excludedAttempts"]),
                          "firstReason": result["excludedAttempts"][0]["reason"]}))


if __name__ == "__main__":
    main()
