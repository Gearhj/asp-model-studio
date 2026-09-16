"""Run only admitted real-data NBA Gen 1 phases; no provider or scheduler actions."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_nba_gen1.authority import NbaAdmissionError, register_plan
from server.sports_nba_gen1.runner import development, load_pointer, refit, season_assessment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['register', 'development', 'validation', 'oot', 'refit'], required=True)
    parser.add_argument('--source-index', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/nba-gen1-v1/real-study')
    args = parser.parse_args()
    if args.phase == 'register':
        if args.source_index is None:
            parser.error('--source-index is required to admit genuine licensed game evidence')
        result = register_plan(args.source_index, args.output)
    elif (args.output/(args.phase+'.json')).exists():
        _, result = load_pointer(args.output, args.phase)
    elif args.phase == 'development':
        result = development(args.output)
    elif args.phase in ('validation', 'oot'):
        result = season_assessment(args.output, args.phase)
    else:
        result = refit(args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except NbaAdmissionError as exc:
        print(json.dumps({'status': 'UNSUPPORTED_REAL_DATA_PREREQUISITE', 'reason': str(exc),
            'fixturePerformanceIsNotNbaGen1': True}, indent=2))
        raise SystemExit(2)
