"""Review actual captured membership for the one selected future NBA target.

Only history identity/date columns are read. This does not fit or predict.
"""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.sports_nba_gen1.authority import reference,verified_bytes,json_bytes

OUT=ROOT/'outputs/nba-gen1-long-gap-v1'


def main():
    destination=OUT/'current-history-coverage.json'
    if destination.exists():
        print(json.dumps({'status':'EXISTING_COVERAGE_PRESERVED','coverage':reference(destination)},indent=2));return
    current_path=OUT/'current-research/receipt.json'
    current_ref=reference(current_path);current=json.loads(verified_bytes(current_ref))
    schedule_path=OUT/'future-schedule-evidence-qualified.json'
    schedule=json.loads(schedule_path.read_bytes())
    capture_path=OUT/'future-schedule-capture.json'
    capture=json.loads(capture_path.read_bytes())
    target=schedule['target'];cutoff=capture['capturedAtUtc']
    assert schedule['capturedAtUtc']==cutoff and schedule['sourceObject']==capture['source']
    verified_bytes(schedule['sourceObject']);verified_bytes(schedule['clockValidation'])
    clock=json.loads(verified_bytes(schedule['clockValidation']))
    assert clock['timeValid'] is True and clock['source_game_id']==target['source_game_id']
    assert clock['date']==clock['startDate']
    historical_source=json.loads((ROOT/'outputs/nba-gen1-recent-v1/acquisition.json').read_bytes())
    current_source=json.loads((OUT/'acquisition-2026.json').read_bytes())
    old_decl_pointer=json.loads((ROOT/'outputs/nba-gen1-recent-v1/declaration.json').read_bytes())['declaration']
    old_decl=json.loads(verified_bytes(old_decl_pointer))
    cohort_path=OUT/'cohort-2026.json';cohort=json.loads(cohort_path.read_bytes())
    old_ids=set().union(*(set(old_decl['admittedSourceKeysBySeason'][str(year)]) for year in range(2020,2026)))
    new_ids={g['game_id'] for g in cohort['admittedGames']}
    assert len(old_ids)==7059 and len(new_ids)==1230 and old_ids.isdisjoint(new_ids)
    history_ref=current['history']['games'];verified_bytes(history_ref)
    history=pd.read_parquet(history_ref['path'],columns=['game_id','season_end','game_date','home_team_id','away_team_id'])
    assert not history.game_id.duplicated().any() and set(history.game_id)==old_ids|new_ids
    assert len(history)==8289 and history.game_date.max()=='2026-04-12'
    assert current['trainingThroughSeasonEnd']==2026
    assert set(cohort['gamesPerTeam'].values())=={82} and len(cohort['gamesPerTeam'])==30
    assert all(cohort['gamesPerTeam'][target[f'{side}_team_code']]==82 for side in ['home','away'])
    future=pd.read_parquet(capture['metadata']['path'])
    assert set(future.season)=={2027}
    regular=future[(future.season_type==2)&(future.type_id==1)]
    stamps=pd.to_datetime(regular['date'],utc=True)
    assert (stamps>pd.Timestamp(cutoff)).all(),'An intervening regular-season opportunity requires explicit reconciliation'
    assert not regular.status_type_completed.any() and set(regular.status_type_state)=={'pre'}
    assert target['game_id'] not in set(history.game_id)
    source_captures=[]
    for name,source,ids,rights in [
        ('Neil Paine2020-2025',historical_source,old_ids,[historical_source['sourceReview'],reference(ROOT/'outputs/nba-gen1-recent-v1/source-review/neil-paine-LICENSE.txt')]),
        ('SportsDataverse2026',current_source,new_ids,[reference(OUT/'source-review/admission.json'),reference(OUT/'source-review/hoopr-LICENSE.md')]),
    ]:
        assert pd.Timestamp(source['acquiredAtUtc'])<=pd.Timestamp(cutoff)
        verified_bytes(source['original'])
        for ref in rights:verified_bytes(ref)
        source_captures.append({'source':name,'capturedAtUtc':source['acquiredAtUtc'],'sourceObject':source['original'],
            'rightsEvidence':rights,'coveredHistoryGames':len(ids),
            'coveredHistoryIdentitySha256':hashlib.sha256(json_bytes(sorted(ids))).hexdigest()})
    result={'schema':'NBA_GEN1_REDUCED_CURRENT_HISTORY_V1','createdAtUtc':datetime.now(timezone.utc).isoformat(),
        'reviewedBy':'Codex NBA source review (/root/nba_recent_source)',
        'currentResearchReceiptSha256':current_ref['sha256'],'targetGameId':target['game_id'],
        'teamIds':[target['home_team_id'],target['away_team_id']],
        'sourceCutoffUtc':cutoff,'completeThroughUtc':cutoff,
        'regularSeasonMembershipComplete':True,'missingGameIds':[],'identityReconciled':True,
        'historyPopulation':history_ref,'contextMetadata':current['history']['contextMetadata'],
        'evidence':[reference(cohort_path),reference(OUT/'reconciliation-2026.json'),old_decl_pointer,
            reference(OUT/'acquisition-2026.json'),reference(capture_path),reference(schedule_path),schedule['clockValidation']],
        'allHistoryRowsCoveredBySourceCaptures':True,'sourceCaptures':source_captures,
        'membershipReview':{'historyGames':len(history),'priorHistoryGames':len(old_ids),'currentSeasonGames':len(new_ids),
            'completed2026GamesPerTargetTeam':{target[f'{side}_team_code']:82 for side in ['home','away']},
            'historyLastDate':history.game_date.max(),'captured2027RegularRows':len(regular),
            'captured2027RegularRowsAtOrBeforeCutoff':0,
            'earliestCaptured2027RegularTipoffUtc':stamps.min().isoformat(),
            'futureCupTBDMatchupsDoNotRepresentMissingElapsedGames':True,
            'postponedOriginalIdsExcludedAndMakeupFinalIdsRetained':4},
        'chronologyQualification':'Future inputs were captured before cutoff. Historical sources remain finalized-record reconstructions with unknown original revision vintages.',
        'calendarScope':'NBA regular-season dates plus declared Cup-final date-only context; not all-competition physical rest.',
        'outcomeColumnsReadForCoverage':[],'networkRequests':0,'forecastGenerated':False}
    destination.write_bytes(json_bytes(result))
    print(json.dumps({'coverage':reference(destination),'target':target,'sourceCutoffUtc':cutoff,
        'membershipReview':result['membershipReview']},indent=2))


if __name__=='__main__':main()
