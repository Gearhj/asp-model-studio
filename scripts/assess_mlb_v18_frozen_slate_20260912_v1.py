"""Frozen September 12 full-slate assessment; no inference or source requests.

Declaration is persisted before any final read. Repeat execution reuses its exact
forecast membership and saved database projections; it does not refresh outcomes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from scripts.run_mlb_v18_transition_shrinkage_v1 import load_baseline
from server.sports_current_statcast.mlb_starter_duration_paired_scoring import (
    read_persisted_finals, _marginal, _score_integer, joint_energy_score, WIN_LOGLOSS_FLOOR,
)
from server.sports_current_statcast.mlb_starter_duration_quarantine import (
    final_oot_eligible_key_mask, LEDGER,
)
from server.sports_silver.canonical_ids import canonical_game_id

OUT = ROOT / 'outputs/mlb-v18-position-and-survival-verification-v1'
SOURCE = ROOT / 'outputs/mlb-v18-current-state-pipeline-v1'
DATE = '2026-09-12'


def utc(s):
    v = s if isinstance(s, datetime) else datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    assert v.tzinfo is not None
    return v.astimezone(timezone.utc)


def reference(path):
    p = Path(path).resolve(); b = p.read_bytes()
    return {'path': str(p), 'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)}


def read_ref(r):
    assert reference(r['path']) == r
    return json.loads(Path(r['path']).read_bytes())


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    raw = (json.dumps(value, indent=2, allow_nan=False, default=str) + '\n').encode()
    if p.exists():
        assert p.read_bytes() == raw, 'PRESERVE_EXISTING_RESULT_USE_SAVED_INPUTS'
    else:
        with p.open('xb') as f: f.write(raw)
    return reference(p)


def guard(f):
    keys = [f['gameId'], str(f['sourceGameId']), canonical_game_id(int(f['sourceGameId']))]
    assert all(final_oot_eligible_key_mask(keys)), 'PERMANENT_WHOLE_GAME_QUARANTINE'
    assert utc(f['scheduledStartUtc']).astimezone(ZoneInfo('America/New_York')).date().isoformat() == DATE
    return keys


def declare():
    path = OUT / 'slate-assessment-declaration.json'
    if path.exists():
        d = json.loads(path.read_text()); [guard(r) for r in d['games']]
        return d
    pointer = json.loads((SOURCE / f'slates/{DATE}/latest.json').read_text())
    slate_path = SOURCE / pointer['relativePath'] / 'slate-result.json'
    slate = json.loads(slate_path.read_text())
    assert slate['slateDate'] == DATE and slate['handoffForecasts'] == 15
    # Immutable source handoff history contains forecasts only, not outcomes.
    originals = {}; handoff_count = 0
    for hp in sorted((SOURCE / 'handoffs/sha256').glob('*/aisp-handoff.json')):
        h = json.loads(hp.read_text())
        if h.get('slateDate') != DATE: continue
        handoff_count += 1
        for f in h['forecasts']:
            gid = f['gameId']; item = {'objectSha256': f['objectSha256'], 'generatedAt': h['generatedAt'], 'handoff': reference(hp)}
            if gid in originals:
                assert originals[gid]['objectSha256'] == item['objectSha256'], 'MULTIPLE_ORIGINAL_FORECAST_IDENTITIES_REQUIRE_EXPLICIT_RESOLUTION'
                if utc(item['generatedAt']) >= utc(originals[gid]['generatedAt']): continue
            originals[gid] = item
    assert len(originals) == 15 and set(originals) == {g['gameId'] for g in slate['games']}
    records = []
    for gid, first in originals.items():
        b = load_baseline(first['objectSha256']); f = b['forecast']; x = b['execution']
        r = {'gameId': gid, 'sourceGameId': str(f['sourceGameId']), 'scheduledStartUtc': utc(f['scheduledStart']).isoformat(),
             'forecastId': 'mlb-v18-daily-' + first['objectSha256'], 'objectSha256': first['objectSha256'],
             'forecast': reference(b['directory'] / 'forecast.json'), 'manifest': b['manifest'],
             'executionInputsAndPairedDraws': reference(b['directory'] / 'execution-inputs.json'),
             'pregameEvidence': reference(b['directory'] / 'pregame-evidence.json'),
             'forecastCreatedAt': f['forecastCreatedAt'], 'capturedAt': f['capturedAt'],
             'firstRetainedHandoffGeneratedAt': first['generatedAt'], 'firstRetainedHandoff': first['handoff'],
             'sourceCutoff': f['sourceCutoff'], 'teams': f['teams'], 'parentAuthority': f['parentAuthority'],
             'modelIdentity': x['modelIdentity'], 'probabilities': f['probabilities'], 'expectations': f['expectations'],
             'snapshotContentSha256': f['snapshotContentSha256'], 'lineupAuthorities': f['lineupAuthorities'],
             'starters': f['starters'], 'simulation': f['simulation'],
             'forecastHorizonHours': (utc(f['scheduledStart']) - utc(f['forecastCreatedAt'])).total_seconds()/3600,
             'evidenceHorizonHours': (utc(f['scheduledStart']) - utc(f['sourceCutoff']['evidenceAvailableAt'])).total_seconds()/3600}
        r['quarantineCheckedAliases'] = guard(r)
        assert utc(r['sourceCutoff']['evidenceAvailableAt']) <= utc(r['capturedAt']) <= utc(r['forecastCreatedAt']) <= utc(first['generatedAt']) < utc(r['scheduledStartUtc'])
        h = np.asarray(b['baseline']['homeRuns']); a = np.asarray(b['baseline']['awayRuns'])
        assert len(h) == len(a) == 5000 and not np.any(h == a)
        assert abs(np.mean(h > a) - f['probabilities']['homeWin']) < 1e-12
        for name, values in {'homeRuns': h, 'awayRuns': a, 'totalRuns': h+a, 'homeMinusAwayRuns': h-a}.items():
            assert abs(values.mean() - f['expectations'][name]) < 1e-12
            support, counts = np.unique(values, return_counts=True)
            saved = f['distributions'][name]
            assert np.array_equal(support, [v['value'] for v in saved]) and np.allclose(counts/5000, [v['probability'] for v in saved], rtol=0, atol=1e-12)
        records.append(r)
    records.sort(key=lambda r: (r['scheduledStartUtc'], r['gameId']))
    d = {'schemaVersion': 'MLB_V18_FROZEN_SLATE_ASSESSMENT_DECLARATION_V1', 'declaredAtUtc': datetime.now(timezone.utc).isoformat(),
         'slateDate': DATE, 'branch': subprocess.check_output(['git','branch','--show-current'], cwd=ROOT,text=True).strip(),
         'head': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT,text=True).strip(),
         'slateReceipt': reference(slate_path), 'immutableHandoffsInspected': handoff_count,
         'quarantine': reference(LEDGER), 'games': records, 'outcomesReadBeforeDeclaration': False,
         'selectionRule': 'All 15 original September12 ordinary V18 forecast objects; immutable handoff history confirms one object per game. All eligible latest governed finals are assessed, regardless of selected side or result.',
         'comparatorRule': 'Use latest originally published LIVE CURRENT_DEVELOPMENT Gen1 forecast and latest complete same-book/source/time two-sided LIVE full-game moneyline at or before each original V18 evidenceAvailableAt. All creation/observation/availability/publication clocks must qualify. Exact tied market snapshots ordered by book UUID then source. No post-cutoff substitutions; horizon differences and missingness retained.',
         'metrics': ['winnerLogLoss','winnerBrier','homeRuns/awayRuns/totalRuns/homeMargin CRPS and mean errors','jointEuclideanEnergyScore'],
         'limitations': ['Chronology of fitted V18 training and feature construction remains uncertified.', 'This observed slate cannot establish recurring weakness or authorize tuning/promotion.', 'Retained draw replicates describe simulation uncertainty, not independent games.'],
         'verification': {'retainedDrawsAndAllFourPublishedMarginalsReconciledOnce': True,'forecastProbabilityTotalsVerified': True},
         'activity': {'modelFits':0,'newSimulations':0,'providerCalls':0,'aispWrites':0}}
    save(path.name, d)
    return d


def winner(p, home, away):
    assert np.isfinite(p) and 0 <= p <= 1
    y = int(home > away); q = float(np.clip(p, WIN_LOGLOSS_FLOOR, 1-WIN_LOGLOSS_FLOOR))
    return {'homeWinProbability':p,'observedHomeWin':y,'winnerLogLoss':float(-np.log(q if y else 1-q)), 'winnerBrier':float((p-y)**2)}


def aggregate(rows):
    if not rows: return {'games':0}
    result = {'games':len(rows), **{k:float(np.mean([r[k] for r in rows])) for k in ['winnerLogLoss','winnerBrier']}}
    if all('marginals' in r for r in rows):
        result['marginals'] = {k:{m:float(np.mean([r['marginals'][k][m] for r in rows])) for m in ['signedError','absoluteError','squaredError','crps']} for k in ['homeRuns','awayRuns','totalRuns','homeMargin']}
        result['jointEuclideanEnergyScore'] = float(np.mean([r['jointEuclideanEnergyScore'] for r in rows]))
    return result


def score():
    d = declare(); [guard(r) for r in d['games']]
    # Recheck the current ledger immediately before the outcome boundary; append-only amendments may advance it.
    gate_path = OUT / 'slate-assessment-outcome-gate.json'
    if not gate_path.exists():
        save(gate_path.name, {'checkedAtUtc':datetime.now(timezone.utc).isoformat(), 'declaration':reference(OUT/'slate-assessment-declaration.json'),
                             'quarantine':reference(LEDGER), 'aliases':[guard(r) for r in d['games']], 'outcomesRead':False})
    final_path = OUT / 'slate-assessment-final-read.json'
    if final_path.exists(): finals = json.loads(final_path.read_text())
    else:
        from dotenv import dotenv_values
        url=dotenv_values(Path('C:/Users/james/ai-sports-predictor/.env'))['DATABASE_URL'].replace('postgresql+psycopg://','postgresql+psycopg2://')
        pairs=[{'gameId':r['gameId'],'commonPairId':r['forecastId'],'scheduledStartUtc':r['scheduledStartUtc']} for r in d['games']]
        finals=read_persisted_finals(pairs,database_url=url);save(final_path.name,finals)
    by_game={r['gameId']:r for r in finals['records']}
    positions_path=OUT/'positions/identity-query.json'; positions=json.loads(positions_path.read_text()) if positions_path.exists() else None
    selected_ids={str(r['game_id']) for r in positions['rows']} if positions else set()
    rows=[]
    for r in d['games']:
        f=by_game.get(r['gameId'],{}); row={'gameId':r['gameId'],'sourceGameId':r['sourceGameId'],'forecastId':r['forecastId'],
          'awayTeam':r['teams']['AWAY']['abbreviation'],'homeTeam':r['teams']['HOME']['abbreviation'],
          'selectedIntoFundedPosition':r['gameId'] in selected_ids,'status':'AWAITING_ELIGIBLE_FINAL','final':f,
          'forecastHorizonHours':r['forecastHorizonHours'],'sourceCutoff':r['sourceCutoff'],'expectations':r['expectations'],'probabilities':r['probabilities']}
        if f.get('status')=='FINAL':
            b=load_baseline(r['objectSha256']); h=np.asarray(b['baseline']['homeRuns']);a=np.asarray(b['baseline']['awayRuns'])
            home,away=_score_integer(f['homeScore']),_score_integer(f['awayScore']); assert home != away
            row['status']='SCORED_LATEST_GOVERNED_FINAL';row['scores']=winner(r['probabilities']['homeWin'],home,away)
            row['scores']['marginals']={k:_marginal(values,obs) for k,values,obs in [('homeRuns',h,home),('awayRuns',a,away),('totalRuns',h+a,home+away),('homeMargin',h-a,home-away)]}
            row['scores']['jointEuclideanEnergyScore']=joint_energy_score(h,a,(home,away))
        rows.append(row)
    result={'schemaVersion':'MLB_V18_FROZEN_SLATE_ASSESSMENT_V1','asOfUtc':finals['source']['queryStartedAt'],
      'declaration':reference(OUT/'slate-assessment-declaration.json'),'outcomeGate':reference(gate_path),'finalRead':reference(final_path),
      'selectedPositionIdentity':reference(positions_path) if positions else None,'rows':rows,
      'allEligibleFinalized':aggregate([r['scores'] for r in rows if 'scores' in r]),
      'fundedPositionSubset':aggregate([r['scores'] for r in rows if 'scores' in r and r['selectedIntoFundedPosition']]),
      'pendingGames':sum('scores' not in r for r in rows),'originalForecasts':15,
      'scorers':[reference(ROOT/'server/sports_current_statcast/mlb_starter_duration_paired_scoring.py')],
      'definitions':{'orientation':'AWAY at HOME; home margin=home minus away; signed error=prediction minus final','winnerBrier':'Binary home-win squared error','winnerLogLossFloor':WIN_LOGLOSS_FLOOR,'uncertainty':'No significance threshold or predictive-improvement interval estimated; 5000 retained draws are not 5000 independent games.'},
      'limitations':d['limitations'],'modelFits':0,'newSimulations':0,'providerCalls':0,'aispWrites':0}
    result_ref=save('slate-assessment.json',result)
    lines=['Frozen September 12 V18 slate','',f"{result['allEligibleFinalized']['games']}/15 governed finals scored; {result['pendingGames']} pending. Funded subset: {result['fundedPositionSubset']['games']} scored games.",'',
      '| Game (away–home) | Final away–home | Home p | Winner LL | Brier | CRPS home/away/total/margin | Funded |','|---|---:|---:|---:|---:|---|---|']
    for r in rows:
        f=r['final']; s=r.get('scores'); final=f"{f['awayScore']}–{f['homeScore']}" if s else 'Pending'
        measures=' / '.join(f"{s['marginals'][k]['crps']:.3f}" for k in ['homeRuns','awayRuns','totalRuns','homeMargin']) if s else '—'
        lines.append(f"| {r['awayTeam']}–{r['homeTeam']} ({r['sourceGameId']}) | {final} | {r['probabilities']['homeWin']:.4f} | {s['winnerLogLoss']:.4f} | {s['winnerBrier']:.4f} | {measures} | {r['selectedIntoFundedPosition']} |" if s else f"| {r['awayTeam']}–{r['homeTeam']} ({r['sourceGameId']}) | Pending | {r['probabilities']['homeWin']:.4f} | — | — | — | {r['selectedIntoFundedPosition']} |")
    lines+=['','Run: `.venv/Scripts/python.exe scripts/assess_mlb_v18_frozen_slate_20260912_v1.py --score`','',f"Result SHA256: {result_ref['sha256']}",'','All original clocks and exact IDs are retained in the declaration. Original artifacts remain unchanged. This slate is descriptive evidence; no tuning, promotion or recurring-weakness claim follows.']
    md=OUT/'slate-assessment.md'; raw='\n'.join(lines)+'\n'
    if md.exists(): assert md.read_text(encoding='utf-8')==raw
    else: md.write_text(raw,encoding='utf-8')
    return result_ref


GEN1_QUERY = """
select f.id::text id,f.game_id::text game_id,f.model_version_id::text model_version_id,
 m.name model_name,m.version model_version,m.algorithm,m.artifact_checksum,
 f.version,f.generated_at,f.available_as_of,f.published_at,f.created_at,
 f.status::text status,f.lifecycle::text lifecycle,f.forecast_track::text forecast_track,
 f.home_win_probability,f.away_win_probability,f.expected_home_runs,f.expected_away_runs,
 f.expected_total_runs,f.expected_run_difference,f.source_mode,
 f.feature_snapshot_id::text feature_snapshot_id,s.checksum feature_checksum,
 s.game_id::text feature_game_id,s.generated_at feature_generated_at,s.data_as_of feature_data_as_of,
 s.created_at feature_created_at,s.source_mode feature_source_mode,
 s.stale_features,s.missing_features,s.provisional_features
from forecasts f join model_versions m on m.id=f.model_version_id
left join game_feature_snapshots s on s.id=f.feature_snapshot_id
where f.game_id::text=:game_id and f.forecast_track::text='CURRENT_DEVELOPMENT'
 and f.source_mode='LIVE' and upper(f.status::text) in ('PUBLISHED','SUPERSEDED')
 and f.generated_at<=:cutoff and f.available_as_of<=:cutoff
 and f.published_at<=:cutoff and f.created_at<=:cutoff
order by f.published_at desc,f.generated_at desc,f.id
"""
MARKET_QUERY = """
select o.id::text quote_id,o.market_outcome_id::text market_outcome_id,
 mo.participant_team_id::text participant_team_id,mo.outcome_key,
 o.sportsbook_id::text sportsbook_id,b.name sportsbook_name,o.observed_at,o.available_as_of,
 o.created_at,o.american_odds,o.decimal_odds,o.payload_checksum,
 o.source,o.source_event_id,o.source_mode,o.status::text status
from odds_snapshots o join market_outcomes mo on mo.id=o.market_outcome_id
join markets m on m.id=mo.market_id join sportsbooks b on b.id=o.sportsbook_id
where m.game_id::text=:game_id and m.market_type::text='MONEYLINE' and m.period='full_game'
 and o.source_mode='LIVE' and upper(o.status::text)='OPEN' and o.point is null
 and o.observed_at<=:cutoff and o.available_as_of<=:cutoff and o.created_at<=:cutoff
 and o.decimal_odds>1
order by o.observed_at desc,o.sportsbook_id,o.source,o.id
"""


def comparators():
    """Read no outcomes: use only the existing frozen final projection."""
    d=declare();[guard(r) for r in d['games']]
    base_path=OUT/'slate-assessment.json'; base=json.loads(base_path.read_text())
    capture_path=OUT/'slate-assessment-comparator-inputs.json'
    if capture_path.exists(): capture=json.loads(capture_path.read_text())
    else:
        from dotenv import dotenv_values
        from sqlalchemy import create_engine,text
        from sqlalchemy.engine import make_url
        url=make_url(dotenv_values('C:/Users/james/ai-sports-predictor/.env')['DATABASE_URL'].replace('postgresql+psycopg://','postgresql+psycopg2://'))
        assert url.host in ('127.0.0.1','localhost','::1')
        engine=create_engine(url);items=[]
        try:
            with engine.connect() as c:
                transaction=c.begin()
                try:
                    c.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                    assert c.exec_driver_sql('SHOW transaction_read_only').scalar()=='on'
                    for r in d['games']:
                        params={'game_id':r['gameId'],'cutoff':utc(r['sourceCutoff']['evidenceAvailableAt'])}
                        gen=[dict(v) for v in c.execute(text(GEN1_QUERY),params).mappings()]
                        quotes=[dict(v) for v in c.execute(text(MARKET_QUERY),params).mappings()]
                        items.append({'gameId':r['gameId'],'params':params,'gen1':gen,'quotes':quotes})
                finally: transaction.rollback()
        finally: engine.dispose()
        capture={'asOfUtc':datetime.now(timezone.utc).isoformat(),'declaration':reference(OUT/'slate-assessment-declaration.json'),
                 'queries':{'gen1':GEN1_QUERY,'market':MARKET_QUERY},'rows':items,'readOnlyTransactionVerified':True,
                 'outcomeQueries':0,'providerRequests':0,'aispWrites':0}
        save(capture_path.name,capture)
        capture=json.loads(capture_path.read_text())
    source={r['gameId']:r for r in capture['rows']};baseline={r['gameId']:r for r in base['rows']};rows=[]
    for r in d['games']:
        inp=source[r['gameId']];cutoff=utc(r['sourceCutoff']['evidenceAvailableAt']);b=baseline[r['gameId']]
        out={'gameId':r['gameId'],'sourceGameId':r['sourceGameId'],'sourceCutoff':r['sourceCutoff'],
             'forecastHorizonHoursV18':r['forecastHorizonHours'],'gen1Status':'NO_ELIGIBLE_PRE_CUTOFF_FORECAST',
             'marketStatus':'NO_ELIGIBLE_COMPLETE_PRE_CUTOFF_TWO_SIDED_SNAPSHOT',
             'eligibleGen1Rows':len(inp['gen1']),'eligibleQuoteRows':len(inp['quotes'])}
        gen=next((g for g in inp['gen1'] if g['feature_game_id']==r['gameId'] and g['feature_source_mode']=='LIVE'
                  and all(g.get(k) and utc(g[k])<=cutoff for k in ['feature_generated_at','feature_data_as_of','feature_created_at'])
                  and utc(g['feature_data_as_of'])<=utc(g['feature_generated_at'])<=utc(g['generated_at'])),None)
        if gen:
            assert gen['model_name']=='asp_mlb_ensemble' and abs(gen['home_win_probability']+gen['away_win_probability']-1)<1e-9
            out.update(gen1Status='MATCHED_ELIGIBLE_PRE_CUTOFF',gen1=gen,
                       forecastHorizonHoursGen1=(utc(r['scheduledStartUtc'])-utc(gen['generated_at'])).total_seconds()/3600,
                       gen1OlderThanV18Hours=(utc(r['forecastCreatedAt'])-utc(gen['generated_at'])).total_seconds()/3600)
        groups={}
        for q in inp['quotes']:
            assert all(utc(q[k])<=cutoff for k in ['observed_at','available_as_of','created_at'])
            key=(q['sportsbook_id'],q['source'],q['source_event_id'],q['observed_at'])
            groups.setdefault(key,[]).append(q)
        complete=[]
        for key,quotes in groups.items():
            sides={side:[q for q in quotes if q['participant_team_id']==r['teams'][side]['uuid']] for side in ['HOME','AWAY']}
            if not all(len(v)==1 for v in sides.values()): continue
            home=sides['HOME'][0];away=sides['AWAY'][0]
            ph,pa=1/float(home['decimal_odds']),1/float(away['decimal_odds'])
            complete.append({'homeQuote':home,'awayQuote':away,'homeNoVigProbability':ph/(ph+pa),'awayNoVigProbability':pa/(ph+pa),
                             'overround':ph+pa-1,'observedAt':home['observed_at'],'sportsbookId':key[0],'source':key[1]})
        complete.sort(key=lambda m:(-utc(m['observedAt']).timestamp(),m['sportsbookId'],m['source']))
        if complete:
            out.update(marketStatus='MATCHED_ELIGIBLE_PRE_CUTOFF',market=complete[0],
                       marketHorizonHours=(utc(r['scheduledStartUtc'])-utc(complete[0]['observedAt'])).total_seconds()/3600)
        if 'scores' in b:
            home,away=b['final']['homeScore'],b['final']['awayScore']
            if gen: out['gen1Scores']=winner(gen['home_win_probability'],home,away)
            if complete: out['marketScores']=winner(complete[0]['homeNoVigProbability'],home,away)
        rows.append(out)
    aggregates={}
    for kind in ['gen1','market']:
        matched=[r for r in rows if kind+'Scores' in r]
        aggregates[kind]={'matchedFinalizedGames':len(matched),'matchedGameIds':[r['gameId'] for r in matched],
                          'v18':aggregate([baseline[r['gameId']]['scores'] for r in matched]),
                          'comparator':aggregate([r[kind+'Scores'] for r in matched]),
                          'preCutoffCoverageAll15':sum(r[kind+'Status']=='MATCHED_ELIGIBLE_PRE_CUTOFF' for r in rows)}
    result={'schemaVersion':'MLB_V18_FROZEN_SLATE_MATCHED_COMPARATORS_V1','asOfUtc':capture['asOfUtc'],
            'declaration':reference(OUT/'slate-assessment-declaration.json'),'originalAssessment':reference(base_path),
            'comparatorInputs':reference(capture_path),'rows':rows,'matchedComparisons':aggregates,
            'interpretation':'Descriptive same-game comparisons at earlier eligible source horizons. No causal or superiority claim; no post-cutoff quotes or later forecasts substituted. Selected-position policy quotes have a different horizon and are reported separately by the position verification.',
            'missingRunDistributionComparison':'Gen1/market full joint or four marginal distributions are not authenticated by this bounded scalar snapshot query; no distributions reconstructed.',
            'outcomeQueries':0,'newSimulations':0,'providerCalls':0,'aispWrites':0}
    ref=save('slate-assessment-comparators.json',result)
    lines=['Matched frozen-slate comparator assessment','','| Eligible finalized cohort | Games | V18 log loss | Comparator log loss | V18 Brier | Comparator Brier |','|---|---:|---:|---:|---:|---:|']
    for k,a in aggregates.items():
        if a['matchedFinalizedGames']:
            x,y=a['v18'],a['comparator'];lines.append(f"| {k} | {a['matchedFinalizedGames']} | {x['winnerLogLoss']:.6f} | {y['winnerLogLoss']:.6f} | {x['winnerBrier']:.6f} | {y['winnerBrier']:.6f} |")
        else:lines.append(f'| {k} | 0 | — | — | — | — |')
    lines+=['',result['interpretation'],'',f"SHA256: {ref['sha256']}",'','Run: `.venv/Scripts/python.exe scripts/assess_mlb_v18_frozen_slate_20260912_v1.py --comparators`']
    p=OUT/'slate-assessment-comparators.md';raw='\n'.join(lines)+'\n'
    if p.exists():assert p.read_text(encoding='utf-8')==raw
    else:p.write_text(raw,encoding='utf-8')
    return ref


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--score',action='store_true');p.add_argument('--comparators',action='store_true');args=p.parse_args()
    print(json.dumps(comparators() if args.comparators else score() if args.score else {'declaration':reference(OUT/'slate-assessment-declaration.json')} if (OUT/'slate-assessment-declaration.json').exists() else (declare() and {'declaration':reference(OUT/'slate-assessment-declaration.json')}),indent=2))
