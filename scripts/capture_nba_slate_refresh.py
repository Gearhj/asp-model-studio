"""Compatibility plan display only. Capture is exclusively inside the NBA owner."""
import argparse
import json
import urllib.request  # Kept for the existing no-network interception check.
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sports_nba_gen1.slate_lifecycle import read_ref
from server.sports_nba_gen1.authority import reference


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--plan')
    p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    if a.execute:
        raise PermissionError('Standalone capture disabled. Use exact authorized same-owner invocation.')
    value = read_ref(reference(a.plan)) if a.plan else {}
    print(json.dumps({'authority':'AWAITING_EXPLICIT_REFRESH_AUTHORIZATION',
        'standaloneCaptureEnabled':False, 'plan':value, 'providerCalls':0}, indent=2))


if __name__ == '__main__':
    main()
