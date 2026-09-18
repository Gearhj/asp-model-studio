"""Offline admission of retained source captures; no external acquisition."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sports_nba_gen1.authority import reference
from server.sports_nba_gen1.slate_inputs import admit


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--capture', required=True)
    p.add_argument('--base-model-receipt', required=True)
    p.add_argument('--base-coverage', required=True)
    p.add_argument('--rights', action='append', required=True)
    p.add_argument('--registry-root', required=True)
    p.add_argument('--season-end', type=int, default=2027)
    p.add_argument('--reviewed-by', required=True)
    a = p.parse_args()
    result = admit(capture_ref=reference(a.capture), base_model_ref=reference(a.base_model_receipt),
        base_coverage_ref=reference(a.base_coverage), rights_refs=[reference(x) for x in a.rights],
        registry_root=a.registry_root, season_end=a.season_end, reviewed_by=a.reviewed_by)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
