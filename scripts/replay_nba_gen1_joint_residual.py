"""Read-only deterministic replay and totals query of one retained research game."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from server.sports_nba_gen1.authority import verified_bytes
from server.sports_nba_gen1.joint_residual import eligible_bank,simulate_pair,totals_query


def replay(root,game_id,line):
    method=json.loads((root/'method-freeze.json').read_bytes())
    verified_bytes(method['residuals'])
    # Verify the numerical sampler and scorer bound at method freeze. The
    # separately documented storage-guard fix changed only the assessment CLI.
    for bound in method['code'][1:]:
        verified_bytes(bound)
    residuals=pd.read_parquet(root/'residuals.parquet')
    selected=residuals[residuals.game_id==game_id]
    if len(selected)!=1:
        raise ValueError('One retained historical game identity required')
    game=selected.iloc[0]
    bank=eligible_bank(residuals,game.game_date,game_id)
    folder=root/'assessment'/str(game.season_end)
    receipt=json.loads((folder/'receipt.json').read_bytes())
    for bound in receipt['artifacts']:
        verified_bytes(bound)
    saved=pd.read_parquet(folder/'populations.parquet')
    populations,_=simulate_pair([game.expected_home_score,game.expected_away_score],bank[['residual_home','residual_away']].to_numpy(),game_id)
    outputs={}
    for arm,population in populations.items():
        binding=saved[(saved.game_id==game_id)&(saved.configuration==arm)].iloc[0]
        draws=population['draws']
        actual=hashlib.sha256(draws.astype('<i8').tobytes()).hexdigest()
        if actual!=binding.ordered_draws_int64_le_sha256:
            raise AssertionError('Original deterministic draw sequence changed')
        outputs[arm]={'orderedDrawsReproducedExactly':True,'orderedDrawsSha256':actual,
            'homeMean':float(draws[:,0].mean()),'awayMean':float(draws[:,1].mean()),
            'jointHomeWinProbability':float((draws[:,0]>draws[:,1]).mean()),'totals':totals_query(draws,line)}
    return {'gameId':game_id,'gameDate':game.game_date,'evidence':'REUSED_HISTORICAL_RESEARCH',
        'separateEloHomeWinProbability':float(game.p_home_win_elo),'outputs':outputs,'filesWritten':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=ROOT/'outputs/nba-gen1-joint-residual-v1')
    parser.add_argument('--game-id',default='nba-espn:game:401809243')
    parser.add_argument('--line',type=float,default=225.5)
    args=parser.parse_args()
    print(json.dumps(replay(args.root,args.game_id,args.line),indent=2,allow_nan=False))
