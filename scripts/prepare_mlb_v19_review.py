"""Prepare compact review tables; preserve source values beside derived metrics."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT/'outputs/mlb-v19-current-state-specialists-v1'


def load(path): return json.loads(path.read_text())
def col(label,width=20,format=None,wrap=False,editable=False,date=False):
    return dict(label=label,width=width,format=format,wrap=wrap,editable=editable,date=date)
def sheet(name,title,columns,rows,**kwargs): return dict(name=name,title=title,columns=columns,rows=rows,**kwargs)


def main(integrity_hold=None):
    qualityroot=OUT/'feature-quality/sha256'
    audit=load(qualityroot/'18171d5414989a12ebfba8ed1916112ac047ef78f62c7a793b65d1d4923aabc0/feature-quality.json')
    cold=load(qualityroot/'8e88e564a2e12e754f8c723d39a1864ef9bb4589b57c14134fe55063d2a98f25/cold-start-specification.json')
    gaps=load(qualityroot/'2c75cb8a47d1f4d39b5495987cbc65232207294dbd8a811f424b6e6158a0321a/ranked-source-gaps.json')
    hold=load(integrity_hold) if integrity_hold else None
    if hold:
        if hold['status']!='BLOCKED_TEMPORAL_INTEGRITY':
            raise ValueError('An explicit temporal-integrity receipt is required')
        atlas=load(OUT/'baseline-atlas/sha256/d1b27325f5c2d0ac2ef048e282578cca12b5e09cb95827145a428fc594312b73/baseline-failure-atlas.json')
        evaluation=raw_evaluation=atlas['evaluation']
        decision={'candidates':[]}
    else:
        evaluation=load(OUT/'evaluation/calibrated-evaluation.json')
        raw_evaluation=load(OUT/'evaluation/raw-evaluation.json')
        decision=load(OUT/'evaluation/development-decision.json')
    summary=[]
    decisions={r['model']:r for r in decision['candidates']}
    for r in evaluation['metrics']:
        if r['dimension']!='overall': continue
        ci=evaluation['pairedIntervals'].get(r['model'],{})
        def bound(method,key):return ci.get(method,{}).get('intervals',{}).get('logLoss',{}).get(key)
        summary.append([r['model'],r['observations'],r['games'],r['logLoss'],r['brier'],None,
            bound('gameClusterBootstrap','lower'),bound('gameClusterBootstrap','upper'),
            bound('calendarWeekBlockBootstrap','lower'),bound('calendarWeekBlockBootstrap','upper'),
            decisions.get(r['model'],{}).get('improvingFolds'),
            'Retained baseline' if r['model']=='V18' else ('Meets Development rule' if decisions[r['model']]['passesDevelopmentResearchRule'] else 'Does not meet rule'), ''])
    base_row=6+next(i for i,row in enumerate(summary) if row[0]=='V18')
    sheets=[sheet('Results','V19 matched Development results',
        [col('Model',28),col('PAs',13,'#,##0'),col('Games',12,'#,##0'),col('Log loss',15,'0.000000'),col('Brier score',15,'0.000000'),
         col('Log-loss delta',17,'+0.000000;-0.000000;0.000000'),col('Game CI lower',16,'0.000000'),col('Game CI upper',16,'0.000000'),
         col('4-week CI lower',18,'0.000000'),col('4-week CI upper',18,'0.000000'),col('Improving folds',18,'0'),col('Research rule',27),col('Review notes',45,editable=True)],summary,
        subtitle='Chronologically calibrated. Reused Development evidence, not independent confirmation. V18 remains retained; Final OOT sealed.',
        formulas=[{'cell':f'F{i+6}','formula':f'=D{i+6}-$D${base_row}'} for i in range(len(summary))],previewRange='A1:F14')]
    if hold:
        sheets=[sheet('Results','V19 comparison blocked by outcome timing',
            [col('Item',34),col('Disposition',77,wrap=True),col('Review notes',50,editable=True)],
            [[item['name'],item['disposition'],''] for item in hold['deliverableStatus']],
            subtitle='V18 retained. No challenger comparison, interval or selection is valid from this stopped attempt.',
            rowHeight=58,previewRange='A1:C12')]
        sheets.append(sheet('Fit accounting','Actual fits and preserved artifacts',
            [col('Fold',10,'0'),col('Model',30),col('Fit completed',18),col('Fit seconds',18,'0.000'),
             col('Reload verified',20),col('Scientific disposition',62,wrap=True)],
            [[r['fold'],r['model'],r['fitCompleted'],r['seconds'],r['reloadVerified'],r['disposition']] for r in hold['globalFits']],
            subtitle='20 scheduled slots; 5 actual global fit starts and completions. Four reload-verified pipelines. All on integrity hold.',
            rowHeight=52,previewRange='A1:F12'))
    metrics=[]
    scales=[('Raw cached V18; timing invalid',raw_evaluation)] if hold else [('Raw',raw_evaluation),('Chronologically calibrated',evaluation)]
    for scale,result in scales:
        for r in result['metrics']:
            metrics.append([scale,r['model'],r['dimension'],r['group'],r['observations'],r['games'],r['logLoss'],r['brier'],r['deltaLogLossVsV18'],r['deltaBrierVsV18']])
    sheets.append(sheet('PA metrics','Matched PA performance by scope',
        [col('Scale',29),col('Model',28),col('Dimension',19),col('Group',38),col('PAs',12,'#,##0'),col('Games',12,'#,##0'),
         col('Log loss',15,'0.000000'),col('Brier',15,'0.000000'),col('Log-loss delta',18,'0.000000'),col('Brier delta',17,'0.000000')],metrics,
        subtitle='Negative deltas mean lower error. Empty scopes are not reported as zero error.',previewRange='A1:H14'))
    calibration=[]
    for r in evaluation['metrics']:
        if r['dimension']!='overall': continue
        for c in r['perClass']:
            calibration.append([r['model'],c['className'],c['observedCount'],c['observedRate'],c['predictedRate'],None,c['oneVsRestBrier'],c['expectedCalibrationError'],c['meanTrueClassLogLoss']])
    sheets.append(sheet('Calibration','Eight-class calibration',
        [col('Model',28),col('Class',21),col('Observed PAs',17,'#,##0'),col('Observed rate',17,'0.00%'),col('Predicted rate',17,'0.00%'),
         col('Rate bias',15,'+0.00%;-0.00%;0.00%'),col('Class Brier',16,'0.000000'),col('10-bin ECE',17,'0.000000'),col('True-class loss',18,'0.000000')],calibration,
        formulas=[{'cell':f'F{i+6}','formula':f'=E{i+6}-D{i+6}'} for i in range(len(calibration))],previewRange='A1:F14'))
    game_labels={'147789ea-5c5e-4485-991b-289eb12a6f4a':'COL–NYY','1a36f34b-466f-4980-967f-fb9ba2778834':'PIT–CWS'}
    fields,values=[],[]
    for f in audit['fields']:
        for gid,g in f['perGame'].items():
            fields.append([game_labels[gid],f['field'],f['featureFamily'],g['fieldQualityCategory'],g['templateCount'],g['rawNullCount'],f['definition'],
                f['entityGrain'],f['frozenMissingTreatment'].get('priorMethod') or f['frozenMissingTreatment'].get('semanticRule'),
                f['numericalRole']['affectsProbabilityMeansThroughEstimatorInputs'],f['betterFreeSource']['gapId'],''])
            for cell in g['cells']:
                value=cell['actualRawValue']
                values.append([game_labels[gid],cell['templateId'].split(gid+':')[-1],f['field'],
                    value if isinstance(value,(int,float)) and not isinstance(value,bool) else None,
                    value if isinstance(value,str) else str(value) if isinstance(value,bool) else None,
                    value is None,json.dumps(value,separators=(',',':'),ensure_ascii=False),cell['qualityCategory'],cell['semanticState'],','.join(cell['sourceEvidenceRefs'])])
    sheets.append(sheet('Feature quality','Original September 10 V18 input quality',
        [col('Game',15),col('Raw field',48),col('Family',32),col('Field classification',45),col('Templates',13,'0'),col('Null values',14,'0'),
         col('Definition',65,wrap=True),col('Grain',23),col('Frozen method',45),col('Mean predictor',18),col('Source gap',31),col('Review notes',45,editable=True)],fields,
        subtitle='Field classification and individual-cell semantic absence are distinct. The original forecasts remain unchanged.',rowHeight=62,previewRange='A1:F13'))
    sheets.append(sheet('Original values','',
        [col('Game',15),col('Template',27),col('Raw field',48),col('Numeric value',24,'0.000000000000'),col('Text value',52),col('Missing',12),
         col('Original JSON value',58),col('Cell classification',43),col('Semantic state',55),col('Source clock IDs',72)],values,raw=True,previewRange='A1:F12'))
    counts=[]
    for game in game_labels.values():
        for category in audit['categoryDefinitions']:
            counts.append([game,category,None,246,None])
    sheets.append(sheet('Coverage','Input-family coverage accounting',
        [col('Game',16),col('Field classification',47),col('Fields',14,'0'),col('Contract fields',18,'0'),col('Share',14,'0.0%')],counts,
        subtitle='A populated missing-source indicator is a source gap, not a measurement. Per-cell details are retained in Original values.',
        formulas=[f for i in range(len(counts)) for f in [
          {'cell':f'C{i+6}','formula':f'=COUNTIFS(\'Feature quality\'!$A$6:$A${5+len(fields)},A{i+6},\'Feature quality\'!$D$6:$D${5+len(fields)},B{i+6})'},
          {'cell':f'E{i+6}','formula':f'=C{i+6}/D{i+6}'}]],previewRange='A1:E17'))
    coldrows=[]
    for f in cold['fields']:
        coldrows.append([f['field'],f['featureFamily'],f['exposureAuthority'],f['knownZeroRule'],f['states']['NO_OBSERVATION'],f['states']['SOURCE_FAILURE'],
            f.get('hierarchyFallback','Not applicable: deterministic context; preserve explicit unknown state'),', '.join(f['candidateTreatmentFamilies']),f['baselineAbsentTreatment'],
            f['states']['NO_OPPORTUNITY'],f['states']['LOW_EXPOSURE'],f['states']['INAPPLICABLE'],f['states']['NEW_PLAYER_OR_CHANGED_ROLE'],''])
    sheets.append(sheet('Cold-start rules','Per-feature semantic cold-start specification',
        [col('Field',47),col('Family',30),col('Exposure authority',58,wrap=True),col('Known zero',62,wrap=True),col('No observation',66,wrap=True),
         col('Source failure',66,wrap=True),col('Hierarchy',72,wrap=True),col('Candidate families',65,wrap=True),col('Frozen V18 behavior',70,wrap=True),
         col('No opportunity',68,wrap=True),col('Low exposure',68,wrap=True),col('Inapplicable',68,wrap=True),col('New player or changed role',68,wrap=True),col('Review notes',45,editable=True)],coldrows,
        subtitle='Proposed families are not automatically fitted methods. Fitted class-composition priors are recorded separately.',rowHeight=86,previewRange='A1:D10'))
    gaprows=[[r['priority'],r['family'],r['likelyPredictiveValue'],r['frequency'],r['pointInTimeReliability'],r['historicalReconstructability'],
              r['currentAvailability'],r['implementationCost'],r['researchAdmission'],r['smallestAction'],''] for r in gaps['ranking']]
    sheets.append(sheet('Source gaps','Ranked source gaps',
        [col('Rank',10,'0'),col('Family',39),col('Plausible value',38),col('Frequency',35,wrap=True),col('Timing reliability',38,wrap=True),col('Historical support',62,wrap=True),
         col('Current availability',58),col('Cost',24),col('Research admission',67),col('Smallest action',75,wrap=True),col('Review notes',45,editable=True)],gaprows,
        subtitle='Qualitative pre-result ranking, not measured lift. Existing captures were reused; provider data calls and cost were zero.',rowHeight=64,previewRange='A1:D15'))
    clocks=[]
    for key,c in audit['sourceClockCatalog'].items():
        original=c.get('originalEvidence',{})
        clocks.append([key,original.get('sourceIdentity') or original.get('source'),c.get('observedAt'),c.get('availableAsOf'),c.get('ingestedAt'),c.get('retrievedAt'),c.get('providerPublishedAt'),json.dumps(original,separators=(',',':'))])
    sheets.append(sheet('Source clocks','',
        [col('Clock ID',68),col('Source identity',60),col('Observed UTC',29,'yyyy-mm-dd hh:mm:ss',date=True),col('Available UTC',29,'yyyy-mm-dd hh:mm:ss',date=True),
         col('Ingested UTC',29,'yyyy-mm-dd hh:mm:ss',date=True),col('Retrieved UTC',29,'yyyy-mm-dd hh:mm:ss',date=True),
         col('Provider publication UTC',29,'yyyy-mm-dd hh:mm:ss',date=True),col('Original source receipt (original timezone and precision retained)',90)],clocks,raw=True,previewRange='A1:C12'))
    clusterrows=[]
    priorrows=[]
    for fold in range(1,6):
        d=OUT/f'folds/fold-{fold}'
        if hold and not (d/'clusters.json').exists(): continue
        for r in load(d/'clusters.json')['domains']:
            for k,center in enumerate(r.get('centersOriginalUnits',[])):
                for feature,value in zip(r['featureOrder'],center,strict=True):
                    clusterrows.append([fold,r['domain'],k,feature,value,r['fittedEnd'],r['fitRows'],r['subprefixStabilityARI']])
        p=load(d/'semantic-priors.json')
        for domain,r in p['parameters'].items():
            priorrows.append([fold,domain,p['fittedEnd'],r['trainingRows'],r['alpha'],r['decay'],r['decayStatus'],r['objective']])
    sheets.append(sheet('Clusters','Fold-local cluster diagnostics',
        [col('Fold',10,'0'),col('Domain',29),col('Local cluster',17,'0'),col('Coordinate',54),col('Center value',19,'0.000000'),
         col('Training end',18,'yyyy-mm-dd',date=True),col('Sampled fit PAs',20,'#,##0'),col('Subprefix ARI',19,'0.0000')],clusterrows,
        subtitle='Fixed three-cluster architecture. Labels are fold-local; stability alone does not prove predictive value.',previewRange='A1:F14'))
    sheets.append(sheet('Fitted priors','Training-fitted semantic priors',
        [col('Fold',10,'0'),col('Entity',24),col('Training cutoff',20,'yyyy-mm-dd',date=True),col('Training PAs',20,'#,##0'),col('Concentration',20,'0.0000'),
         col('Season decay',18,'0.0000'),col('Decay status',72),col('Training objective',23,'0.000000')],priorrows,
        subtitle='League/hand hierarchy uses training-prefix evidence. Same-date and future entity outcomes do not enter features.',previewRange='A1:F14'))
    if hold:
        for s in sheets:
            if s['name'] in ('PA metrics','Calibration','Clusters','Fitted priors'):
                s['title']='Superseded '+s['title'].lower()
                s['subtitle']='Preserved numerical evidence only. Official-date chronology is invalid; do not use for model selection or pregame claims.'
        # Do not present a baseline's identity delta as a comparative study result.
        for row in next(s for s in sheets if s['name']=='PA metrics')['rows']:
            row[8]=row[9]=None
    for s in sheets:
        s['rows']=[[json.dumps(v,separators=(',',':'),ensure_ascii=False) if isinstance(v,(dict,list)) else v for v in row] for row in s['rows']]
    payload={'sheets':sheets,'matchedPAs':evaluation['observations'],'matchedGames':evaluation['games'],
             'originalValueCells':len(values),'featureGameRows':len(fields),
             'status':'BLOCKED_TEMPORAL_INTEGRITY' if hold else 'COMPLETED',
             'integrityReceipt':str(integrity_hold) if hold else None}
    if (OUT/'review/MLB_V19_Research_Review.xlsx').exists():
        payload['renderOnly']=['PA metrics','Cold-start rules','Source gaps','Source clocks']
    path=OUT/'review/workbook-data.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf8')
    print(path)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--integrity-hold',type=Path)
    main(parser.parse_args().integrity_hold)
