"""Reproduce frozen accepted V18 baseline without fitting or sealed payload IO."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_current_statcast.mlb_regime_baseline import reproduce_and_cache


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache')
    args = parser.parse_args()
    def emit(event, **payload):
        print(json.dumps({'event': event, **payload}, default=str), flush=True)
    result = reproduce_and_cache(args.output, emit=emit)
    emit('BASELINE_REPRODUCTION_COMPLETE', path=result['path'], sha256=result['sha256'],
         usableOofRows=result['usableOofRows'], usableOofGames=result['usableOofGames'],
         unavailableOofRows=result['unavailableOofRows'], estimatorFits=0, finalOotPayloadBytesRead=0)
