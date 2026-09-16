"""Freeze a 2026 metadata cohort, then separately admit its guarded outcomes."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.sports_nba_gen1.authority import json_bytes,reference,verified_bytes
from server.sports_nba_gen1.current_history_source import classify_current_metadata,normalize_current_history

OUT=ROOT/'outputs/nba-gen1-long-gap-v1'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',choices=['scope','scores'],required=True)
    parser.add_argument('--model-freeze',type=Path)
    args=parser.parse_args()
    cohort_path=OUT/'cohort-2026.json'
    if args.stage=='scope':
        if cohort_path.exists():
            print(json.dumps({'status':'EXISTING_COHORT_PRESERVED','cohort':reference(cohort_path)},indent=2));return
        acquisition=json.loads((OUT/'acquisition-2026.json').read_bytes())
        verified_bytes(acquisition['original']);verified_bytes(acquisition['metadata']);verified_bytes(acquisition['declaration'])
        scope=classify_current_metadata(pd.read_parquet(acquisition['metadata']['path']))
        scope.update({'createdAtUtc':datetime.now(timezone.utc).isoformat(),'source':acquisition['original'],
            'metadata':acquisition['metadata'],'declaration':acquisition['declaration'],
            'adapter':reference(ROOT/'server/sports_nba_gen1/current_history_source.py')})
        cohort_path.write_bytes(json_bytes(scope))
        print(json.dumps({'cohort':reference(cohort_path),'regularGames':len(scope['admittedGames']),
            'oriented':scope['orientedTargetGames'],'neutral':scope['neutralHistoryOnlyGames'],
            'exclusions':scope['exclusionCounts'],'contextEvents':scope['contextOnlyEvents']},indent=2));return
    if args.model_freeze is None:
        raise ValueError('--model-freeze is required before score access')
    target=OUT/'games-2026.parquet'
    if target.exists():
        print(json.dumps({'status':'EXISTING_NORMALIZED_GAMES_PRESERVED','games':reference(target)},indent=2));return
    games,report=normalize_current_history(cohort_path,args.model_freeze)
    games.to_parquet(target,index=False)
    report.update({'createdAtUtc':datetime.now(timezone.utc).isoformat(),'normalized':reference(target),
        'gamesArtifact':reference(target),'modelFreeze':reference(args.model_freeze),
        'acquisition':reference(OUT/'acquisition-2026.json')})
    receipt=OUT/'reconciliation-2026.json'
    receipt.write_bytes(json_bytes(report))
    print(json.dumps({'receipt':reference(receipt),'games':reference(target),
        'regularGames':len(games),'oriented':report['orientedTargetGames'],'neutral':report['neutralHistoryOnlyGames']},indent=2))

if __name__=='__main__':main()
