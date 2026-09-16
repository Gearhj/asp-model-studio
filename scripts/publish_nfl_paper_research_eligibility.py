"""Publish authorized DEN-KC paper eligibility evidence, never a wager or forecast."""
import argparse
import json
from pathlib import Path

from server.sports_nfl_m1.paper_research_eligibility import publish

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange-root", type=Path, default=Path(r"C:\Users\james\asp-model-exchange"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs/nfl-paper-research-eligibility-20260914-v1"))
    parser.add_argument("--authorization", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish(exchange_root=args.exchange_root, output_root=args.output_root, authorization_path=args.authorization), indent=2))
