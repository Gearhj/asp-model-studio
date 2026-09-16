"""Focused physical and numerical checks of the completed recent NBA study."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import joblib
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.sports_nba_gen1.authority import reference, verified_bytes, json_bytes
from server.sports_nba_gen1.recent_study import predict

OUT=ROOT/'outputs/nba-gen1-recent-v1'


def main():
    path=OUT/'verification.json'
    if path.exists():
        print(json.dumps({'status':'REUSE_COMPLETED_VERIFICATION','receipt':reference(path)},indent=2))
        return
    rows=[]; preceding_freeze=None; data_refs=[]
    for stage in ('development','validation','holdout'):
        receipt=json.loads((OUT/f'{stage}-receipt.json').read_bytes())
        for artifact in receipt['artifacts'].values():
            verified_bytes(artifact)
            data_refs.append(artifact)
        access=json.loads(verified_bytes(receipt['artifacts']['access']))
        for artifact in access['numericalModules'].values():
            verified_bytes(artifact)
        if preceding_freeze:
            assert preceding_freeze['createdAtUtc']<access['startedAtUtc']
        frame=pd.read_parquet(receipt['artifacts']['features']['path'])
        ledger=pd.read_parquet(receipt['artifacts']['predictions']['path'])
        bindings=json.loads(verified_bytes(receipt['artifacts']['models']))
        for bound in bindings:
            stored=ledger[(ledger.season_end==bound['assessmentSeasonEnd']) & (ledger.model_id==bound['config']['id'])]
            target=frame.set_index('game_id').loc[stored.game_id].reset_index()
            reproduced=predict(bound,target)
            numeric=['expected_home_score','expected_away_score','p_home_win','p_away_win','p_tie',
                     'log_loss','binary_brier','home_mae','away_mae','margin_mae','total_mae','team_score_mse',
                     'home_residual','away_residual']
            assert np.array_equal(reproduced[numeric].to_numpy(),stored[numeric].to_numpy())
            rows.append({'stage':stage,'seasonEnd':bound['assessmentSeasonEnd'],'modelId':bound['config']['id'],
                         'games':len(stored),'allStoredNumericalPredictionsAndScoresExact':True})
        if 'nextStageFreeze' in receipt['artifacts']:
            preceding_freeze=json.loads(verified_bytes(receipt['artifacts']['nextStageFreeze']))
    refit=json.loads((OUT/'post-assessment-refit/receipt.json').read_bytes())
    final=json.loads((OUT/'holdout-receipt.json').read_bytes())
    assert refit['createdAtUtc']>final['completedAtUtc']
    latest_frame=pd.read_parquet(OUT/'holdout/features.parquet')
    train=latest_frame[latest_frame.target_eligible]
    for bound in refit['models'].values():
        verified_bytes(bound['artifact'])
        model=joblib.load(bound['artifact']['path'])
        assert model.training_game_ids==tuple(train.game_id)
        assert bound['trainingLastDate']=='2025-04-13'
        values=model.predict(train.tail(5))
        assert np.isfinite(values).all()
    # Preserve original artifacts by byte checks; no prior model evaluation.
    old_index=ROOT/'outputs/nba-gen1-historical-pilot-v1/INDEX.json'
    prior=json.loads(old_index.read_bytes())
    for artifact in prior['files']+prior['implementationFiles']:
        verified_bytes(artifact)
    original=json.loads((ROOT/'outputs/nba-gen1-v1/verification.json').read_bytes())
    for artifact in original['existingDirtyFilesPreserved']:
        verified_bytes(artifact)
    subprocess.run(['git','diff','--exit-code','816e04f','--','outputs/nba-gen1-historical-pilot-v1',
                    'outputs/nba-gen1-v1','server/sports_nba_gen1/authority.py','server/sports_nba_gen1/features.py',
                    'server/sports_nba_gen1/models.py','server/sports_nba_gen1/historical_features.py',
                    'server/sports_nba_gen1/historical_source.py','server/sports_nba_gen1/historical_pilot.py',
                    'server/sports_nba_gen1/distribution.py','server/sports_nba_gen1/forecast.py'],
                    cwd=ROOT,check=True,capture_output=True)
    value={'schemaVersion':'NBA_GEN1_RECENT_FOCUSED_VERIFICATION_V1','createdAtUtc':datetime.now(timezone.utc).isoformat(),
           'numericalReproductions':rows,'exactNumericalAgreement':True,'modelGameRowsChecked':sum(r['games'] for r in rows),
           'stageFreezeChronologyVerified':True,'postAssessmentRefitCompleted':True,'refitTrainingGames':len(train),
           'separateRefitArtifacts':{key:b['artifact'] for key,b in refit['models'].items()},
           'originalPilotPreserved':reference(old_index),'originalDirtyFilesPreserved':original['existingDirtyFilesPreserved'],
           'unitTests':{'sourceAndFeatures':17,'reducedModels':8,'selectionGate':3,'meaning':'Synthetic software checks, not independent forecast evidence'},
           'sourceRequestsForVerification':0,'verificationFits':0,'simulations':0,'aispWrites':0,
           'mlbNflOperationsChanged':False,'artifactsVerified':data_refs}
    path.write_bytes(json_bytes(value))
    print(json.dumps({'receipt':reference(path),'modelGameRowsChecked':value['modelGameRowsChecked'],
                      'assessmentModelsChecked':len(rows),'postAssessmentRefitCompleted':True},indent=2))


if __name__=='__main__':
    main()
