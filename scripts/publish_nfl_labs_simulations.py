"""Publish current saved M1 distributions without fitting or changing forecasts."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from server.sports_nfl_m1.labs_simulation import publish_current_score_distributions

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange-root", type=Path, default=Path(r"C:\Users\james\asp-model-exchange"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs/nfl-labs-simulation-v1"))
    args = parser.parse_args()
    print(json.dumps(publish_current_score_distributions(args.exchange_root, args.output_root), indent=2))
