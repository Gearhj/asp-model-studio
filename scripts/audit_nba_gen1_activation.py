"""Independent read-only numerical/integrity audit; no forecast or model run.

Writes only its requested local evidence report. Reads the retained future
schedule through explicit identity/status columns, never outcome columns.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

DEPLOYMENT = '7e04b1cc6f68ad4a4c0a3833f28751fdbfc54957e019e2cb5743946eeae25716'
MANIFEST_SHA = '5d34687595d35837528be0655080b00d006c38b5414e33ffb7448c9e19cb360e'
HANDOFF_SHA = '7113b71ff5819c89103ad19d5f9afb22c51dbc92980be12b56ce8826cb34ccaf'
PACKAGE_SHA = '8a725a439af9f9ad4828281ff9bcdec5511c2af292c3feac4826b975dfa0d4c2'
FORECAST_SHA = '8c69bc25e64c969b0dfd2f0cfe3b3ec7af0f8699358368a44ab4289ba3f46282'
POPULATION_SHA = '62b48824b2746656d2ec9e93c5ebcd6b3768e8662b37b0e0703a3a463e1eb17c'
LOGICAL_SHA = '6d7b75fbe79f3803269643f88bf29b117e182730d38b2ba5477d0bb70e2c0bb7'

def ref(path):
    p = Path(path); b = p.read_bytes()
    return {'path':str(p), 'bytes':len(b), 'sha256':hashlib.sha256(b).hexdigest()}

def checked(path, expected, size=None):
    r=ref(path)
    if r['sha256'] != expected or (size is not None and r['bytes'] != size):
        raise ValueError('Physical artifact mismatch: '+str(path))
    return r

def members(root, index):
    result=[]
    for item in index.get('members', index.get('files', [])):
        path=(root/item['relativePath']).resolve()
        if not path.is_relative_to(root.resolve()): raise ValueError('Escaping member path')
        result.append(checked(path,item['sha256'],item['bytes']))
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',required=True)
    ap.add_argument('--repository',default=r'C:\Users\james\asp-model-studio')
    ap.add_argument('--exchange',default=r'C:\Users\james\asp-model-exchange')
    args=ap.parse_args()
    repo,exchange=Path(args.repository),Path(args.exchange)
    d=repo/'.deployments/nba-gen1-publisher'/DEPLOYMENT
    manifest_ref=checked(d/'deployment-manifest.json',MANIFEST_SHA)
    manifest=json.loads((d/'deployment-manifest.json').read_bytes())
    deployment_members=members(d,manifest)
    assert len(deployment_members)==26 and manifest['deploymentId']==DEPLOYMENT
    handoff=exchange/'nba-gen1-production-v1/handoffs/sha256'/HANDOFF_SHA
    handoff_ref=checked(handoff/'index.json',HANDOFF_SHA)
    handoff_members=members(handoff,json.loads((handoff/'index.json').read_bytes()))
    package=exchange/'nba-gen1-production-v1/forecasts/sha256'/PACKAGE_SHA
    package_ref=checked(package/'index.json',PACKAGE_SHA)
    index=json.loads((package/'index.json').read_bytes())
    package_members=members(package,index)
    checked(package/'forecast.json',FORECAST_SHA)
    f=json.loads((package/'forecast.json').read_bytes())
    fitted_bindings=[]
    for name in ['pointModel','eloModel','currentModelReceipt','jointMethod','residualPopulation']:
        bound=f['bindings'][name]
        fitted_bindings.append(checked(bound['path'],bound['sha256'],bound['bytes']))
    population=package/f['population']['artifact']['relativePath']
    checked(population,POPULATION_SHA)
    frame=pd.read_parquet(population)
    assert len(frame)==10000 and np.array_equal(frame.drawIndex,np.arange(10000))
    assert set(frame.homeTeamCode)=={'NYK'} and set(frame.awayTeamCode)=={'PHI'}
    x=frame[['homeScore','awayScore']].to_numpy(dtype=np.int64)
    assert hashlib.sha256(x.astype('<i8').tobytes()).hexdigest()==LOGICAL_SHA
    assert (x>=0).all() and (x[:,0]!=x[:,1]).all()
    h,a=x.T
    vectors={'home':h,'away':a,'total':h+a,'margin':h-a}
    joint=f['jointSimulation']
    for name,v in vectors.items():
        expected=Counter(v.tolist()); cells=joint['pmfs'][name]
        assert len(cells)==len(expected) and sum(c['count'] for c in cells)==10000
        assert abs(sum(c['probability'] for c in cells)-1)<1e-12
        for c in cells:
            assert expected[c['value']]==c['count'] and c['probability']==c['count']/10000
        mean_key='homeMargin' if name=='margin' else name
        assert abs(float(v.mean())-joint['expectedScores'][mean_key])<1e-10
        for interval in joint['intervals'][name]:
            alpha=(1-interval['level'])/2
            actual=np.quantile(v,[alpha,1-alpha],method='inverted_cdf')
            assert np.array_equal(actual,[interval['lower'],interval['upper']])
    assert joint['winnerProbabilities']['home']==float((h>a).mean())
    for p in [f['eloWinnerProbabilities'],joint['winnerProbabilities']]:
        assert all(0<=p[k]<=1 for k in ['home','away','tie'])
        assert abs(sum(p[k] for k in ['home','away','tie'])-1)<1e-12 and p['tie']==0
    points=f['ridgePointExpectations']
    assert abs(points['home']+points['away']-points['total'])<1e-10
    assert abs(points['home']-points['away']-points['homeMargin'])<1e-10
    for q in joint['illustrativeTotals']:
        over=float(((h+a)>q['line']).mean()); push=float(((h+a)==q['line']).mean())
        under=float(((h+a)<q['line']).mean())
        assert q['over']=={'win':over,'push':push,'loss':under}
        assert q['under']=={'win':under,'push':push,'loss':over}
    clocks={key:pd.Timestamp(f[key]) for key in ['sourceCutoffUtc','createdAtUtc','publishedAtUtc','prospectiveEffectiveAtUtc']}
    assert all(t.tzinfo for t in clocks.values())
    tip=pd.Timestamp(f['game']['scheduled_tipoff_utc'])
    assert clocks['sourceCutoffUtc']<=clocks['createdAtUtc']<=clocks['publishedAtUtc']<tip
    assert clocks['prospectiveEffectiveAtUtc']<=clocks['createdAtUtc']
    assert f['game']['source_game_id']==401909089
    assert f['game']['home_team_id']=='nba-neil:franchise:NYK' and f['game']['away_team_id']=='nba-neil:franchise:PHI'
    assert f['closeScoreChallenger']['enabled'] is False
    assert f['authority']['requiresConsumerPin'] is True
    assert not any(f['authority'][k] for k in ['wageringAuthority','decisionAuthority','positionAuthority'])
    preserved=[]
    for rel in ['point-elo-v1/packages/sha256/85e3d7414ccaac4b79c524096af3f7fa894169041e143ee3dc5894002f53e2e0',
                'joint-comparison-v1/packages/sha256/00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d']:
        root=exchange/'nba-gen1-research-v1'/rel
        preserved.append(checked(root/'index.json',root.name))
        preserved.extend(members(root,json.loads((root/'index.json').read_bytes())))
    base=repo/'outputs/nba-gen1-long-gap-v1'
    capture=json.loads((base/'future-schedule-capture.json').read_bytes())
    schedule_ref=checked(capture['source']['path'],capture['source']['sha256'],capture['source']['bytes'])
    cols=['id','game_id','date','game_date','season','season_type','type_id','type_abbreviation','neutral_site',
          'status_type_state','status_type_completed','home_id','away_id','home_abbreviation','away_abbreviation']
    schedule=pd.read_parquet(schedule_ref['path'],columns=cols)
    from server.sports_nba_gen1.current_history_source import TEAM_IDENTITIES
    regular=schedule[(schedule.season==2027)&(schedule.season_type==2)&(schedule.type_id==1)&(schedule.type_abbreviation=='STD')]
    mapped=regular.home_id.isin(TEAM_IDENTITIES)&regular.away_id.isin(TEAM_IDENTITIES)
    eligible=regular[mapped&~regular.neutral_site.fillna(True)&~regular.status_type_completed.fillna(True)&regular.status_type_state.eq('pre')].copy()
    eligible['utc']=pd.to_datetime(eligible.date,utc=True)
    eligible=eligible.sort_values(['utc','id'])
    opener=eligible[eligible.game_date.astype(str).eq('2026-10-20')]
    readiness={'capturedAtUtc':capture['capturedAtUtc'],'source':schedule_ref,'identityColumnsRead':cols,
        'outcomeColumnsRead':[], 'regularRows':len(regular),'mappedUnstartedNonneutralGames':len(eligible),
        'unmappedRegularGames':regular.loc[~mapped,['id','home_id','away_id']].to_dict('records'),
        'openingSlate':opener[['id','date','home_abbreviation','away_abbreviation']].to_dict('records'),
        'recurringOwnerReachableGameIds':[401909089],
        'fullSlateReady':False,'automaticInputRefreshOwner':None,
        'blockers':['No slate dispatcher: wrapper omits --game-id so default is always PHI-NYK 401909089',
          'Schedule hash and source cutoff fixed to September 14 snapshot; different source bytes are rejected',
          'No recurring result/history/coverage refresh; manual governed source admission belongs to Model Studio',
          'Reuse branch precedes schedule/history/deadline checks and returns old receipt without checking current input freshness',
          'Discovery writer replaces packages with one entry; not a full-slate append/preserve implementation',
          'No durable per-invocation launcher/runner receipt in pinned deployment; stdout only'],
        'nextGenuinelyDuePublication':'Not defined by this deployment; next 15-minute invocation reuses PHI-NYK. A governed refreshed schedule/history bundle and dispatcher successor are needed for new slate publications.',
        'requiredBeforeOpeningNight':['Governed schedule identity/status/tipoff refresh',
          'Retained result/history membership update following each completed regular game; feature snapshot excludes target/later evidence',
          'Explicit publication checkpoints, multi-game discovery preservation and revision-aware reuse',
          'Player/lineup/injury inputs remain unsupported rather than fabricated']}
    report={'schema':'NBA_GEN1_ACTIVATION_INDEPENDENT_AUDIT_V1','createdAtUtc':datetime.now(timezone.utc).isoformat(),
        'deployment':manifest_ref,'deploymentMemberCount':26,'deploymentMembers':deployment_members,
        'handoff':handoff_ref,'handoffMembers':handoff_members,'package':package_ref,'packageMembers':package_members,
        'fittedAndResidualBindings':fitted_bindings,
        'drawCount':10000,'logicalPopulationSha256':LOGICAL_SHA,'allIndependentAccountingChecksPassed':True,
        'ridgePointExpectations':points,'eloWinnerProbabilities':f['eloWinnerProbabilities'],
        'jointExpectedScores':joint['expectedScores'],'jointWinnerProbabilities':joint['winnerProbabilities'],
        'distinctChannelsVerified':True,'sourceCutoffUtc':f['sourceCutoffUtc'],'createdAt':f['createdAtUtc'],
        'publishedAt':f['publishedAtUtc'],'tipoffUtc':tip.isoformat(),
        'preservedResearchArtifacts':preserved,'fullSlateReadiness':readiness,
        'providerCalls':0,'providerBytes':0,'costUsd':0,'aispWrites':0,'exchangeWrites':0,
        'modelExecutions':0,'outcomeAccess':False}
    output=Path(args.output)
    if output.exists(): raise ValueError('Audit output must be append-only')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,allow_nan=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'audit':ref(output),'checksPassed':True,'fullSlateReadiness':readiness},indent=2))

if __name__=='__main__':main()
