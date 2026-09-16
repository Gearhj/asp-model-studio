"""Read frozen September12 exposure evidence; no inference, provider or DB calls."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask, LEDGER
from server.sports_silver.canonical_ids import canonical_game_id

OUT = ROOT / 'outputs/mlb-v18-september12-miss-analysis-v1/exposure'
DECLARATION = ROOT / 'outputs/mlb-v18-position-and-survival-verification-v1/slate-assessment-declaration.json'
CLASSES = ['STRIKEOUT','WALK_HBP_CI','HOME_RUN','SINGLE','DOUBLE','TRIPLE','BIP_OUT','OTHER_REACH']


def ref(path):
    p=Path(path).resolve();data=p.read_bytes()
    return {'path':str(p),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}


def read(descriptor):
    assert ref(descriptor['path'])==descriptor
    return json.loads(Path(descriptor['path']).read_bytes())


def describe(values):
    x=np.asarray(values,dtype=float)
    assert x.ndim==1 and len(x)==5000 and np.isfinite(x).all()
    return {'draws':len(x),'mean':float(x.mean()),'minimum':float(x.min()),'maximum':float(x.max()),
            'p05':float(np.quantile(x,.05,method='inverted_cdf')),'median':float(np.quantile(x,.5,method='inverted_cdf')),
            'p95':float(np.quantile(x,.95,method='inverted_cdf'))}


def trace_metrics(events):
    halves=defaultdict(list); batters=Counter(); role=Counter(); changes=[]
    classes=Counter(); sideclasses=defaultdict(Counter)
    for n,e in enumerate(events,1):
        assert e['pa']==n and e['outcome'] in CLASSES and e['half'] in ('TOP','BOTTOM')
        assert 0<=e['outsBefore']<=2 and e['outsBefore']<=e['outsAfter']<=3
        assert 0<=e['baseMaskBefore']<=7 and 0<=e['baseMaskAfter']<=7 and e['runsScored']>=0
        batting='AWAY' if e['half']=='TOP' else 'HOME';pitching='HOME' if e['half']=='TOP' else 'AWAY'
        batters[batting]+=1;role[pitching+':'+e['pitcherState']]+=1
        classes[e['outcome']]+=1;sideclasses[batting][e['outcome']]+=1
        halves[(e['inning'],e['half'])].append(e)
        if e['pitchingChange']:
            assert e['pitcherState']=='TEAM_BULLPEN'
            changes.append({'pitchingSide':pitching,'globalPaIndex':e['pa'],'inning':e['inning'],'half':e['half'],
                            'opposingTeamPaIndex':batters[batting], 'starterBfBeforeReplacement':role[pitching+':STARTER'],
                            'meaning':'The role switch happens before this sampled PA; anonymous team-bullpen state, not an identified reliever.'})
    hrows=[]
    for (inning,half),rows in sorted(halves.items(),key=lambda x:(x[0][0],x[0][1]=='BOTTOM')):
        hrows.append({'inning':inning,'half':half,'pa':len(rows),'runs':sum(e['runsScored']for e in rows),
                      'endedAtThreeOuts':rows[-1]['outsAfter']==3,
                      'multipleOutPaEvents':sum(e['outsAfter']-e['outsBefore']>=2 for e in rows),
                      'occupiedBasePaOpportunities':sum(e['baseMaskBefore']!=0 for e in rows),
                      'occupiedBaseMaskChangeEvents':sum(e['baseMaskBefore']!=0 and e['baseMaskBefore']!=e['baseMaskAfter'] for e in rows)})
    def side_summary(side):
        half='TOP'if side=='AWAY'else'BOTTOM';sel=[r for r in hrows if r['half']==half]
        scores=sum(r['runs'] for r in sel)
        return {'pa':batters[side],'runs':scores,'outcomeCounts':{k:sideclasses[side][k]for k in CLASSES},
                'hitClassEvents':sum(sideclasses[side][k]for k in ['SINGLE','DOUBLE','TRIPLE','HOME_RUN']),
                'walkHbpCiClassEvents':sideclasses[side]['WALK_HBP_CI'],
                'otherReachClassEvents':sideclasses[side]['OTHER_REACH'],
                'maximumHalfInningRuns':max(r['runs']for r in sel),'halfInningsWithAtLeastThreeRuns':sum(r['runs']>=3 for r in sel),
                'largestHalfInningShareOfTeamRuns':max(r['runs']for r in sel)/scores if scores else None}
    return {'simulationIndex':0,'retainedDrawCount':1,'totalPa':len(events),
            'terminalInningNumber':max(e['inning']for e in events),'halfInningsVisited':len(hrows),
            'halfInningsCompletedAtThreeOuts':sum(r['endedAtThreeOuts']for r in hrows),
            'maximumHalfInningPa':max(r['pa']for r in hrows),
            'multipleOutPaEvents':sum(r['multipleOutPaEvents']for r in hrows),
            'pitcherExposure':{side:{'starterBf':role[side+':STARTER'],'anonymousReliefBf':role[side+':TEAM_BULLPEN']}for side in ['HOME','AWAY']},
            'replacementEvents':changes,'batting':{side:side_summary(side)for side in ['HOME','AWAY']},'halfInnings':hrows,
            'outcomeCounts':{k:classes[k]for k in CLASSES},
            'limitations':['One retained illustrative simulation draw, not an estimate over5000 draws or observed PA outcomes.',
                           'Multiple-out PA count is a state-change proxy; ground-double-play type is not recorded.',
                           'Base-mask changes do not identify individual runner paths or distinguish all advancement from retirements.',
                           'Terminal base masks are cleared; exact stranded-runner counts cannot be reconstructed from these trace fields.',
                           'WALK_HBP_CI is combined; class totals are not an independent observed baserunner ledger.']}


def main():
    declaration=json.loads(DECLARATION.read_text());assert len(declaration['games'])==15
    gate=read(ref(OUT/'identity-before-outcomes.json'))
    assert gate['declaration']==ref(DECLARATION)
    for r in declaration['games']:
        assert all(final_oot_eligible_key_mask([r['gameId'],r['sourceGameId'],canonical_game_id(int(r['sourceGameId']))]))
    finals_path=ROOT/'outputs/mlb-v18-september12-miss-analysis-v1/governed-finals.json'
    finals_ref=ref(finals_path)
    assert finals_ref['sha256']=='9ac89f5f0585d011dca71cd9ef544d8c1bc1e26c79501cab2eefe99ea1528d9f'
    finals=read(finals_ref);finals_by_game={r['gameId']:r for r in finals['records']}
    rows=[]
    for r in declaration['games']:
        # Original attribution is already complete. Verify only the evidence member used here.
        x=read(r['executionInputsAndPairedDraws']);pop=x['population']
        assert pop['gameId']==r['gameId'] and pop['simulationCount']==5000 and len(pop['traces'])==1
        assert x['initialPaClassOrder']==CLASSES
        trace=trace_metrics(pop['traces'][0]);h=np.asarray(pop['homeRuns']);a=np.asarray(pop['awayRuns'])
        assert trace['totalPa']==pop['paCounts'][0] and trace['terminalInningNumber']==pop['innings'][0]
        assert trace['batting']['HOME']['runs']==h[0] and trace['batting']['AWAY']['runs']==a[0]
        assert sum(trace['outcomeCounts'].values())==trace['totalPa']
        assert sum(sum(v.values())for v in trace['pitcherExposure'].values())==trace['totalPa']
        missing=['Observed total PA, half-inning lengths and innings','Observed starter BF/removal time and reliever BF/identities',
                 'Observed hits/walks/other reach events with exact final revision','Observed runner advancement/double plays/stranded runners',
                 'Observed half-inning run sequence','Population-wide simulated starterBF, reliefBF and PA-class counts',
                 'Population-wide simulated half-inning run and runner-transition sequence']
        rows.append({'gameId':r['gameId'],'sourceGameId':r['sourceGameId'],'forecastId':r['forecastId'],
                     'awayTeam':r['teams']['AWAY']['abbreviation'],'homeTeam':r['teams']['HOME']['abbreviation'],
                     'governedFinal':{'receipt':finals_ref, **{k:finals_by_game.get(r['gameId'],{}).get(k)for k in ['status','sourceOutcomeId','sourceRevision','starterEvidence','reason']}},
                     'evidence':{'executionInputsAndPairedDraws':r['executionInputsAndPairedDraws'],'declaration':ref(DECLARATION)},
                     'pregameStarters':{s:{k:r['starters'][s].get(k)for k in ['mlbamId','name','confirmationState','daysRest','workload','pitchesLastStart','pitchesPreviousDay']}for s in ['HOME','AWAY']},
                     'population5000':{'totalPa':describe(pop['paCounts']),'terminalInningNumber':describe(pop['innings']),
                        'extraInningRate':pop['extraInningRate'],'starterEverRemovedRateHome':pop['pitchingChangeRateHome'],
                        'starterEverRemovedRateAway':pop['pitchingChangeRateAway'],
                        'inningMeaning':'Terminal integer inning number; not innings pitched or exact half-innings played.',
                        'illegalStateCount':pop['illegalStateCount'],'nonterminationCount':pop['nonterminationCount']},
                     'singleRetainedTrace':trace,'actualExposureAndConversion':{'status':'UNAVAILABLE_IN_INSPECTED_RETAINED_EXCHANGE',
                        'zeroObservedEventsAsserted':False,'absenceMeaning':'Missing diagnostic records, not evidence of zero PA/BF/hits/runs or absence of a mechanism.'},
                     'missingEvidence':missing,'finding':'INSUFFICIENT_EVIDENCE_TO_LOCATE_EXPOSURE_OR_RUN_CONVERSION_ERROR',
                     'nextAction':'Obtain exact same-final-revision postgame PA/inning and starter/relief exposure labels from an existing authorized retained source, then compare to the already frozen forecasts. Do not diagnose conversion from mean score residual alone.'})
    postgame_root=Path('C:/Users/james/asp-model-exchange/aisp-final-evidence/mlb-position-forecast-final-v1')
    pointer=json.loads((postgame_root/'current.json').read_text());handoff_path=postgame_root/pointer['relativePath']
    post=json.loads(handoff_path.read_text());allowed={r['sourceGameId']for r in declaration['games']}
    assert {str(r['providerGameId'])for r in post['positions']}<=allowed
    evidence={'positionFinalHandoff':ref(handoff_path),'publishedAtUtc':post['publishedAtUtc'],
              'records':len(post['positions']),'scope':'Seven exact funded positions only; five final and two open at the captured handoff.',
              'fieldsPresent':['Explicit final home/away scores','Completion clock/basis','Final revision','Source record ID and checksums'],
              'fieldsAbsent':['Actual PA sequence','Starter BF/removal or relief exposure','Runner advancement/double plays/stranded runners','Half-inning run sequence'],
              'pregameCovariateUse':'NONE; any postgame labels are diagnostic only',
              'otherRetainedSourceGap':'Simulator-evidence current66db25... datedSeptember12 holds2025 appearance labels, not September12 postgame exposure. No2025 appearance payload was loaded.'}
    result={'schemaVersion':'MLB_V18_SEPTEMBER12_FROZEN_EXPOSURE_DIAGNOSTICS_V1','asOfUtc':datetime.now(timezone.utc).isoformat(),
            'identityGate':ref(OUT/'identity-before-outcomes.json'),'quarantineAtUse':ref(LEDGER),'code':ref(Path(__file__)),
            'fixedCohortGames':15,'rows':rows,'postgameEvidenceCoverage':{**evidence,'latestGovernedFinals':finals_ref,
                'latestGovernedFinalCount':9,'awaitingGovernedFinalCount':6,
                'latestReaderStarterEvidence':'All9 final records report ACTUAL_STARTER_BF_UNAVAILABLE, reason OPTIONAL_STARTER_EVIDENCE_UNAVAILABLE:ValueError. The pair-oriented reader lacked its accepted frozen starter input descriptor; this is not proof that the database contains zero pitcher labels.'},
            'supportedModelChanges':[],
            'boundedHypotheses':[{'layer':'Starter-removal and anonymous relief exposure','status':'UNRESOLVED_HYPOTHESIS_NOT_A_DIAGNOSED_FAILURE',
              'support':'Frozen simulation code replaces each starter with an anonymous TEAM_BULLPEN probability mixture. Retained single traces expose this switch, but5000-draw BF/removal distributions and matched actual usage are absent.',
              'missingDiscriminatingEvidence':'Actual starter/relief BF and removal timing bound to the same final revision, plus population-wide frozen exposure counters.',
              'smallestNextExperiment':'For one future supported original baseline-versus-frozen-survival pair, retain per-draw starterBF/reliefBF and inning-run counters before outcome access; compare exact actual pitcher exposure after final. Existing comparison owns fitting and run authority; this analysis starts no replay or candidate.',
              'rejectionCriterion':'If actual pitcher exposure agrees while run misses persist, an exposure correction is not supported as the explanation; inspect event or sequencing evidence separately.'}],
            'conclusion':'Retained diagnostics show exposure mechanics and one event path pergame. They cannot attribute any September12 miss to PA miscalibration, starter duration, sequencing or run conversion. A mean run residual and a single trace are insufficient. No exposure/transition parameter change is selected.',
            'focusedChecks':{'traceIndexZeroMatchesSavedPaAndInningArraysFor15':True,'traceRunsMatchSavedJointDrawZeroFor15':True,
                             'traceEventAndPitcherRoleCountsReconcileFor15':True,'repeatedAttributionAudit':False},
            'activity':{'providerCalls':0,'databaseQueries':0,'newSimulations':0,'modelFits':0,'aispWrites':0}}
    p=OUT/'findings.json'
    if p.exists():
        result['asOfUtc']=json.loads(p.read_text())['asOfUtc']
    raw=json.dumps(result,indent=2,allow_nan=False)+'\n'
    if p.exists():assert p.read_text(encoding='utf-8')==raw,'PRESERVE_IMMUTABLE_FINDINGS'
    else:p.write_text(raw,encoding='utf-8')
    lines=['Frozen September12 exposure evidence','','All15 forecasts retain5000 total-PA and terminal-inning draws, but only one detailed event trace each. Actual exposure/run-conversion labels are unavailable in the inspected exchange; missing is not zero. No model correction is selected.','',
           '| Game | Mean simulated PA | PA5–95% | Extra innings | One trace starterBF away/home | Actual comparison |',
           '|---|---:|---|---:|---|---|']
    for r in rows:
        q=r['population5000'];t=r['singleRetainedTrace'];bf=t['pitcherExposure']
        lines.append(f"| {r['awayTeam']}–{r['homeTeam']} ({r['sourceGameId']}) | {q['totalPa']['mean']:.2f} | {q['totalPa']['p05']:.0f}–{q['totalPa']['p95']:.0f} | {q['extraInningRate']:.2%} | {bf['AWAY']['starterBf']}/{bf['HOME']['starterBf']} | Unavailable |")
    lines+=['','The BF numbers describe one retained simulation draw, not a typical exposure estimate or an actual start. Half-inning PA/runs, sampled hit/walk/other-reach classes, reliefBF and multiple-out PA proxies are saved pergame in findings.json. Runner identity paths, exact stranded runners and ground-double-play types are unobserved. The latest final reader reports starter evidence unavailable because its pair-specific frozen input descriptor is missing; that is not proof of zero actual pitcher labels in the database.','',result['conclusion'],'','One bounded hypothesis remains untested: starter removal and anonymous relief exposure may affect run forecasts. The smallest useful comparison is the already authorized future baseline/survival pair with retained per-draw exposure counters and exact actual usage. This is not evidence that duration explains these losses.','',
              'Run: `.venv/Scripts/python.exe scripts/analyze_mlb_v18_september12_exposure_v1.py`','',f'Findings SHA256: {ref(p)["sha256"]}']
    (OUT/'findings.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(ref(p),indent=2))


if __name__=='__main__':main()
