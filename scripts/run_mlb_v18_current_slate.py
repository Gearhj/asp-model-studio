"""Capture the actual next local MLB slate and prepare a safe incremental V18 source bridge."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.inventory_mlb_current_slate import capture_current_slate
from server.sports_current_statcast.mlb_v18_current_slate import (
    OUTPUT, build_evidence_bridge, load_contract, reference, verify_accepted_reload, write_object,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, help='Use an existing local captured inventory without any database call')
    parser.add_argument('--output-root', type=Path, default=OUTPUT)
    parser.add_argument('--verify-artifact', action='store_true')
    args = parser.parse_args()
    if args.inventory:
        path = args.inventory.resolve()
        if not path.is_relative_to((args.output_root / 'inventory/sha256').resolve()) or path.name != 'current-slate-input-inventory.json':
            raise ValueError('Replay accepts only this workflow\'s immutable current-slate inventory objects')
        capture = reference(path)
        if capture['sha256'] != path.parent.name:
            raise ValueError('Captured inventory content address differs')
        inventory = json.loads(path.read_text(encoding='utf-8'))
        if inventory.get('schemaVersion') != 'MLB_V18_CURRENT_SLATE_INPUT_INVENTORY_V1':
            raise ValueError('Not a current-slate source inventory')
        capture = reference(args.inventory)
    else:
        inventory, capture = capture_current_slate(output_root=args.output_root / 'inventory')
    receipt, result = build_evidence_bridge(inventory, output_root=args.output_root)
    reload_result = verify_accepted_reload(load_contract()) if args.verify_artifact else None
    run = {'schemaVersion': 'MLB_CURRENT_SLATE_RUN_V1', 'capture': capture, 'bridge': result,
           'artifactReload': reload_result, 'newForecasts': 0, 'aispImportAction': 'NONE_SOURCE_EVIDENCE_NOT_A_FORECAST_HANDOFF'}
    run['implementation'] = [reference(ROOT / name) for name in (
        'scripts/run_mlb_v18_current_slate.py', 'scripts/inventory_mlb_current_slate.py',
        'server/sports_current_statcast/mlb_v18_current_slate.py',
        'server/sports_current_statcast/mlb_v18_current_inputs.py')]
    run_ref, _ = write_object(args.output_root, 'run-receipt.json', run)
    print(json.dumps({'run': run_ref, 'bridge': result, 'slateDate': receipt['slateDateEastern'],
                     'games': receipt['gamesDiscovered'], 'gamesSkipped': receipt['gamesSkipped'],
                     'sourceObjectsReused': receipt['sourceObjectsReused'],
                     'status': receipt['status'], 'artifactReload': reload_result}, indent=2))


if __name__ == '__main__':
    main()
