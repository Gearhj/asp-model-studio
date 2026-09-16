"""Run the one frozen ordinary-rest remedy on existing historical evidence."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_nba_gen1.rest_study import run

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['development', 'reused-diagnostics'], required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/nba-gen1-long-gap-v1')
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.stage), indent=2))
