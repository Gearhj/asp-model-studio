"""Run the declared real-data Category-A NBA pilot; cached source only."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.sports_nba_gen1.historical_pilot import run

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',choices=['development-validation','holdout'],required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/nba-gen1-historical-pilot-v1')
    args=parser.parse_args()
    print(json.dumps(run(args.output,args.stage),indent=2))
