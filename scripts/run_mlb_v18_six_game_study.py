"""Exploratory, fixed V18/last-six point-score analysis from retained evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from mlb_v18_six_game_inventory import load_inventory
from mlb_v18_six_game_history import load_history, reference_for
from mlb_v18_six_game_statistics import add_losses, comparisons, outlier_tables, charts

DESIGN_SHA = 'fb3325e25ae184363fb346a8096e7dda32b8b499d98ef1be02009b664c262fd2'


def clean(value):
    if isinstance(value, dict):
        return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [clean(x) for x in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_json(path, obj):
    path.write_text(json.dumps(clean(obj),indent=2,allow_nan=False)+'\n',encoding='utf-8')


def file_ref(path):
    b=path.read_bytes()
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runtime',type=Path,default=Path(r'C:\Users\james\asp-model-studio'))
    ap.add_argument('--authority',type=Path,default=Path(r'C:\Users\james\aisp-analysis\wagering-record-20260918'))
    ap.add_argument('--output',type=Path,default=Path(r'C:\Users\james\asp-model-studio\outputs\mlb-v18-score-outlier-six-game-20260919-v1'))
    args=ap.parse_args();out=args.output
    started=dt.datetime.now(dt.timezone.utc).isoformat()
    assert file_ref(out/'DESIGN.md')['sha256']==DESIGN_SHA,'PREDECLARED_DESIGN_CHANGED'
    rows,exclusions,inventory_refs=load_inventory(args.runtime,args.authority)
    history,history_coverage,history_refs=load_history(args.runtime)
    assert len({r['game_id'] for r in rows})==len(rows),'PREDICTIVE_GRAIN_NOT_ONE_GAME'
    reference_details=[];donors=[]
    # Construct all reference means, deviations and groups before target outcome join.
    for r in rows:
        r['game_date']=r['local_game_date']
        meta={'homeTeamMlbamId':r['home_team_id'],'awayTeamMlbamId':r['away_team_id'],
              'scheduledStartUtc':r['scheduled_start'],'cutoffUtc':r['cutoff_utc'],
              'mlbamGamePk':r['source_game_id']}
        refs=reference_for(meta,history,history_coverage['identityInventory'])
        reference_details.append({'game_id':r['game_id'],'forecast_identity':r['forecast_identity'],'references':refs})
        for key,prefix in [('TEAM_LAST6','team6'),('H2H_LAST6','h2h6')]:
            ref=refs[key]
            for source,dest in [('homeMean','home'),('awayMean','away'),('homeSupport','home_support'),('awaySupport','away_support'),('completeSix','complete_six'),('availabilityClass','availability'),('supportClass','support_class'),('historyCompleteness','identity_completeness')]:
                r[prefix+'_'+dest]=ref[source]
            r[prefix+'_missing_game_ids']=ref['missingGameIds']
            r[prefix+'_identity_ordering_availability']='RECONSTRUCTED_FROM_LATEST_RETAINED_SCORE_FREE_SEASON_INVENTORY'
            for d in ref['donors']:
                donors.append({'target_game_id':r['game_id'],'target_mlbam_game_pk':r['source_game_id'],
                               'forecast_identity':r['forecast_identity'],'reference':key,
                               'target_cutoff_utc':r['cutoff_utc'],**d})
            h,a=ref['homeMean'],ref['awayMean']
            if h is None or a is None:
                for field in ['home_deviation','away_deviation','total_deviation','margin_deviation','max_abs_team_deviation','total_abs_deviation','margin_abs_deviation','blend_home','blend_away']:
                    r[prefix+'_'+field]=None
                r[prefix+'_outlier']='UNSUPPORTED'
            else:
                dh,da=r['v18_home']-h,r['v18_away']-a
                r.update({prefix+'_home_deviation':dh,prefix+'_away_deviation':da,
                          prefix+'_total_deviation':dh+da,prefix+'_margin_deviation':dh-da,
                          prefix+'_total_abs_deviation':abs(dh+da),prefix+'_margin_abs_deviation':abs(dh-da),
                          prefix+'_max_abs_team_deviation':max(abs(dh),abs(da)),
                          prefix+'_outlier':'UNUSUAL' if max(abs(dh),abs(da))>=2.0 else 'ORDINARY',
                          prefix+'_blend_home':.5*(r['v18_home']+h),prefix+'_blend_away':.5*(r['v18_away']+a)})
    pregame=[{k:v for k,v in r.items() if not k.startswith('wager_') and k not in ['profit_actual','expected_profit_raw','expected_profit_controlling']} for r in rows]
    write_json(out/'PREGAME_REFERENCES_AND_GROUPS.json',pregame)
    write_json(out/'REFERENCE_DETAILS.json',reference_details)
    donor_frame=pd.DataFrame(donors)
    donor_frame.to_csv(out/'reference_contributors.csv',index=False)
    feature_binding=file_ref(out/'PREGAME_REFERENCES_AND_GROUPS.json')
    feature_clock=dt.datetime.now(dt.timezone.utc).isoformat()
    # Same original target outcome is used for every point arm.
    by_pk={r['mlbamGamePk']:r for r in history}
    conflicts=[]
    for r in rows:
        r['actual_home']=None;r['actual_away']=None
        target=by_pk.get(int(r['source_game_id']))
        if target and (target['homeTeamMlbamId']!=r['home_team_id'] or target['awayTeamMlbamId']!=r['away_team_id']):
            raise ValueError('TARGET_FINAL_ORIENTATION_CONFLICT')
        if r['selected']:
            h=float(r['wager_final_home_score']);a=float(r['wager_final_away_score'])
            if target and (h!=target['homeScore'] or a!=target['awayScore']):
                conflicts.append({'game_id':r['game_id'],'consumer':[h,a],'retained_schedule':[target['homeScore'],target['awayScore']]})
                raise ValueError('SELECTED_AUTHORITY_FINAL_CONFLICT')
            r['actual_home'],r['actual_away']=h,a
            r['outcome_authority']='CLAUDE_RECONCILED_HISTORICAL_POSITION_EXPORT'
            r['outcome_source_revision']=r.get('wager_settlement_revisions')
            r['outcome_source_sha256']=inventory_refs['sources'][0]['sha256']
            r['outcome_status']='SUPPORTED_COMPLETED'
        elif target:
            r['actual_home'],r['actual_away']=target['homeScore'],target['awayScore']
            r['outcome_authority']='RETAINED_PERMITTED_OFFICIAL_DAILY_SCHEDULE_FINAL_RESEARCH_ONLY'
            r['outcome_source_revision']=target['sourceRevisionIdentity']
            r['outcome_source_sha256']=target['sourceSha256']
            r['outcome_capture_utc']=target['captureAvailableAtUtc']
            r['outcome_status']='SUPPORTED_COMPLETED'
        else:
            r['outcome_status']='NO_SUPPORTED_RETAINED_FINAL'
            exclusions.append({'game_id':r['game_id'],'source_game_id':r['source_game_id'],'forecast_identity':r['forecast_identity'],'reason':'NO_SUPPORTED_RETAINED_FINAL'})
    f=pd.DataFrame(rows)
    for c in ['actual_home','actual_away','odds_american','odds_decimal','stake','profit_actual','expected_profit_raw','expected_profit_controlling']:
        if c not in f:f[c]=np.nan
        f[c]=pd.to_numeric(f[c],errors='coerce')
    f=add_losses(f)
    comparison=comparisons(f)
    groups,diffs,wagers=outlier_tables(f)
    scored=f[f.outcome_status.eq('SUPPORTED_COMPLETED')]
    reference_counts={}
    for prefix in ['team6','h2h6']:
        valid=scored[scored[prefix+'_home'].notna() & scored[prefix+'_away'].notna()]
        reference_counts[prefix]={
            'available_both_teams':len(valid),'complete_six':int(valid[prefix+'_complete_six'].sum()),
            'unsupported':len(scored)-len(valid),
            'support_home_counts':valid[prefix+'_home_support'].value_counts().sort_index().to_dict(),
            'support_away_counts':valid[prefix+'_away_support'].value_counts().sort_index().to_dict(),
            'outlier_counts':valid[prefix+'_outlier'].value_counts().to_dict(),
            'availability_counts':valid[prefix+'_availability'].value_counts().to_dict(),
            'selected_unusual':int((valid.selected & valid[prefix+'_outlier'].eq('UNUSUAL')).sum()),
            'nonselected_unusual':int((~valid.selected & valid[prefix+'_outlier'].eq('UNUSUAL')).sum())}
    summary={'schema':'MLB_V18_FIXED_SIX_GAME_EXPLORATORY_RESULTS_V1','startedAtUtc':started,
             'featureGroupsWrittenBeforeOutcomeJoinAtUtc':feature_clock,'pregameFeatureBinding':feature_binding,
             'completedAtUtc':dt.datetime.now(dt.timezone.utc).isoformat(),
             'designSha256':DESIGN_SHA,'originalInventory':inventory_refs['counts'],
             'eligibleOriginalGames':len(f),'scoredGames':len(scored),'scoredSelected':int(scored.selected.sum()),
             'scoredNonselected':int((~scored.selected).sum()),'unscored':len(f)-len(scored),
             'gameDates':sorted(scored.game_date.unique()),'dateBlocks':scored.game_date.nunique(),
             'references':reference_counts,'outcomeConflicts':conflicts,
             'selectedActualProfit':f.loc[f.selected,'profit_actual'].sum(),'selectedStake':f.loc[f.selected,'stake'].sum(),
             'selectedWins':int((f.selected & f.wager_result.eq('WIN')).sum()),'selectedLosses':int((f.selected & f.wager_result.eq('LOSS')).sum()),
             'uncertaintyDefectSelections':int(f.uncertainty_defect_selection.sum()),
             'pairedUncertainty':'2000 game-date block resamples, seed20260919; descriptive intervals with few dates and overlapping team histories',
             'newProbabilityDistributions':0,'productionChanges':False,'providerCalls':0,'protectedPayloadsRead':0}
    serial=f.copy()
    for c in serial:
        if serial[c].map(lambda x:isinstance(x,(dict,list))).any():
            serial[c]=serial[c].map(lambda x:json.dumps(clean(x),sort_keys=True) if isinstance(x,(dict,list)) else x)
    serial.to_csv(out/'game_results.csv',index=False)
    serial[serial.selected].to_csv(out/'selected_wager_results.csv',index=False)
    for name,table in [('score_comparison',comparison),('outlier_performance',groups),('paired_group_differences',diffs),('wager_groups',wagers)]:
        table.to_csv(out/(name+'.csv'),index=False)
    pd.DataFrame(exclusions).to_csv(out/'exclusions.csv',index=False)
    write_json(out/'SUMMARY.json',summary)
    write_json(out/'HISTORY_COVERAGE.json',{k:v for k,v in history_coverage.items() if k!='identityInventory'})
    write_json(out/'SEPARATE_LEGACY_POSITIONS.json',inventory_refs['legacy_positions'])
    source_refs=inventory_refs['sources']+history_refs
    write_json(out/'SOURCE_INDEX.json',list({r['path']:r for r in source_refs}.values()))
    write_json(out/'IDENTITY_GATE.json',inventory_refs['identity_gate'])
    charts(f,comparison,out)
    write_json(out/'ARTIFACT_RECEIPT.json',{'generatedAtUtc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'sourceCode':[file_ref(p) for p in Path(__file__).parent.glob('*six_game*.py')],
        'outputs':[file_ref(p) for p in out.iterdir() if p.is_file() and p.name!='ARTIFACT_RECEIPT.json']})
    print(json.dumps(clean(summary),indent=2,allow_nan=False))


if __name__=='__main__':
    main()
