"""Preserve a blocked attempt without completing or registering a candidate.

Reads existing isolated V19 receipts only. No model loading, data fitting,
provider access, source resolution or database connections.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast.mlb_v19_launch_guard import HOLD_ID

OUT=ROOT/'outputs/mlb-v19-current-state-specialists-v1'
VARIANTS=('SEMANTIC_HGB','SEMANTIC_EXTRA_TREES','REGIME_HGB','REGIME_CLUSTER_HGB')
TIMING=OUT/'timing-blocker/sha256/5bbcdf6c7cae0332b903db18b410a6bae2da05da6871e2125688c6e8394b0e6b/timing-evidence.json'
BASELINE=OUT/'baseline/sha256/625bc8707461982082a159f9539acf89aedb4ceb8c289b6d1b891ab14e6eb121/reproduction.json'


def load(p): return json.loads(p.read_bytes())


def ref(p):
    digest=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''): digest.update(block)
    return {'path':str(p.resolve()),'sha256':digest.hexdigest(),'bytes':p.stat().st_size}


def store(name,value):
    data=canonical_json_bytes(value)
    digest=hashlib.sha256(data).hexdigest()
    p=OUT/'integrity-hold/sha256'/digest/name
    p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():
        if p.read_bytes()!=data: raise ValueError('Immutable hold receipt conflict')
    else:
        with p.open('xb') as stream: stream.write(data)
    return ref(p)


def prepare():
    events=[json.loads(line) for line in (OUT/'fit-events.jsonl').read_text().splitlines()]
    starts=[e for e in events if e['event']=='FIT_STARTED' and e['fit'] in VARIANTS]
    completed=[e for e in events if e['event']=='FIT_COMPLETED' and e['fit'] in VARIANTS]
    failed=[e for e in events if e['event']=='FIT_FAILED' and e['fit'] in VARIANTS]
    if len(starts)!=5 or len(completed)!=5 or failed:
        raise ValueError('Unexpected stopped-attempt fit accounting; inspect instead of relabeling')
    rows=[]
    for e in completed:
        d=OUT/f"folds/fold-{e['fold']}"
        verified=d/(e['fit']+'-verified.json')
        r={'fold':e['fold'],'model':e['fit'],'fitCompleted':True,'seconds':e['seconds'],
           'reloadVerified':verified.exists(),'disposition':'SUPERSEDED_FOR_SCIENTIFIC_COMPARISON_TEMPORAL_INTEGRITY',
           'estimator':ref(d/(e['fit']+'.joblib')),'predictions':ref(d/(e['fit']+'-probabilities.npy'))}
        if verified.exists():
            v=load(verified)
            if v['model']['sha256']!=r['estimator']['sha256'] or v['predictions']['sha256']!=r['predictions']['sha256']:
                raise ValueError('Preserved artifact differs from original verification')
            r['originalVerification']=ref(verified)
        rows.append(r)
    if sum(r['reloadVerified'] for r in rows)!=4: raise ValueError('Expected four full reload receipts')
    status=[
        ('V18 current-feature audit','COMPLETE: 246 fields, 2 games, 16,728 original values and source clocks'),
        ('Ranked source gaps','COMPLETE: ranked evidence gaps; no claimed predictive lift'),
        ('Semantic cold-start specification','COMPLETE DESIGN: 246 rows; fitted V19 treatments on integrity hold'),
        ('V18 failure atlas','PRESERVED NUMERICAL DESCRIPTION: original-date chronology invalid for selection'),
        ('Cluster analysis','PARTIAL / SUPERSEDED: two fitted fold-local systems; no validated incremental value'),
        ('Candidate and specialist matrix','PREDECLARED: 20 global slots; five completed fits; specialists not fitted'),
        ('Matched-population evaluation','BLOCKED: no scientifically valid candidate comparison'),
        ('Calibration and uncertainty','BLOCKED: no comparative intervals or new calibration fit'),
        ('Executable candidate package','NOT PRODUCED: incomplete timing-invalid attempt must not be packaged'),
        ('Game-simulation comparison','NOT RUN: no valid candidate selection; oracle diagnostics are not pregame skill'),
        ('Operational readiness','NOT READY: zero verified V19 current games; no V19 forecast publication'),
        ('Editable review workbook','DELIVERED WITH HOLD: valid source audit and explicitly superseded numerical evidence'),
        ('Manifest and checksums','DELIVERED: blocked evidence archive, not a completed-study certificate'),
        ('Recommendation','RETAIN V18 authority unchanged; keep Final OOT sealed; repair source chronology before resuming'),
    ]
    receipt={'schemaVersion':'MLB_V19_INTEGRITY_HOLD_RECEIPT_V1','holdId':HOLD_ID,
        'status':'BLOCKED_TEMPORAL_INTEGRITY','verdict':'MLB_V19_STUDY_BLOCKED_ON_EVIDENCE',
        'originalDeclaration':ref(ROOT/'docs/MLB_V19_STUDY_DECLARATION_V1.md'),
        'successorSupplement':ref(ROOT/'docs/MLB_V19_TEMPORAL_INTEGRITY_HOLD_V1.md'),
        'timingEvidence':ref(TIMING),'baselineNumericalReproduction':ref(BASELINE),
        'worker':{'pid':75200,'startedAtUtc':'2026-09-11T00:33:41.0064481Z',
                  'absenceVerifiedAtUtc':'2026-09-11T02:06:14Z','status':'STOPPED_BY_INTEGRITY_HOLD',
                  'stoppedDuring':'FOLD_2_POSTFIT_VERIFICATION','terminalExitCode':1},
        'scheduledGlobalFitSlots':20,'actualGlobalFitStarts':len(starts),'actualGlobalFitCompletions':len(completed),
        'globalFitFailures':len(failed),'fullyReloadVerifiedGlobalArtifacts':4,'foldCompletionReceipts':1,
        'semanticPriorFitGroups':2,'clusterFitGroups':2,
        'fitGroupQualification':'Groups contain multiple component optimizations; not a claim of four individual estimator fits.',
        'syntheticNativeNanCompatibilityFits':2,'globalFits':rows,
        'preflightFailure':ref(OUT/'preflight-recovery.json'),
        'candidatePerformanceComparisonsReviewed':0,'newCalibrationFits':0,'specialistFits':0,
        'gameSimulations':0,'v19ForecastsPublished':0,'verifiedSupportedCurrentGames':0,
        'prospectiveReady':False,'providerDataRequests':0,'providerCostUsd':0,'sealedPayloadReads':0,
        'sealedReadQualification':'No sealed evaluation artifact or mixed 2026 raw schedule opened; safe cached Development chronology is separately invalidated.',
        'aispWrites':0,'pinnedDeploymentActions':0,'promotion':'NOT_PROMOTED','wageringAuthority':False,
        'deliverableStatus':[{'name':n,'disposition':s} for n,s in status],
        'notAnExternalProviderAbsence':True,'nextAction':'Establish completion-aware source ordering and admissibility authority for baseline and challenger inputs. Declare any reduced common population separately before resuming the fixed matrix; do not relabel the original fold cutoff.'}
    result=store('integrity-hold.json',receipt)
    if not any(e.get('holdId')==HOLD_ID and e['event']=='INTEGRITY_HOLD' for e in events):
        event={'event':'INTEGRITY_HOLD','holdId':HOLD_ID,'atUtc':'2026-09-11T02:06:14Z',
               'timestampMeaning':'WORKER_ABSENCE_VERIFIED_NOT_EXACT_TERMINATION_TIME','receipt':result,
               'actualGlobalFitStarts':5,'actualGlobalFitCompletions':5,'fullyReloadVerifiedGlobalArtifacts':4}
        with (OUT/'fit-events.jsonl').open('a',encoding='utf8') as stream: stream.write(json.dumps(event,sort_keys=True)+'\n')
    print(json.dumps(result))
    return result


def finalize(incident):
    incident=incident.resolve()
    if not incident.is_relative_to(OUT.resolve()): raise ValueError('Only isolated hold receipts may be archived')
    held=load(incident)
    if held['status']!='BLOCKED_TEMPORAL_INTEGRITY': raise ValueError('Not a blocked attempt')
    workbook=OUT/'review/MLB_V19_Research_Review.xlsx'
    verification=load(OUT/'review/workbook-verification.json')
    if not workbook.is_file() or len(verification['sheets'])<8: raise ValueError('Review workbook incomplete')
    files=[ref(p) for p in sorted(OUT.rglob('*')) if p.is_file() and 'final-archive' not in p.parts]
    report={
        'schemaVersion':'MLB_V19_BLOCKED_RESEARCH_ARCHIVE_V1','status':'BLOCKED_TEMPORAL_INTEGRITY',
        'verdict':held['verdict'],'studyId':'mlb-v19-current-state-specialists-v1',
        'projectId':'asp-mtlozhdx','hold':ref(incident),'reviewWorkbook':ref(workbook),'files':files,
        'fileCount':len(files),'totalBytes':sum(r['bytes'] for r in files),
        'authority':{'status':'RESEARCH_SHADOW','promotionStatus':'NOT_PROMOTED','wageringAuthority':False,
                     'executionAllowedInAISP':False,'finalOotAccessed':False},
        'deliverables':held['deliverableStatus'],'candidateSelected':None,'comparisonMetrics':None,
        'confidenceIntervals':None,'prospectiveReady':False,'verifiedSupportedCurrentGames':0,
        'registration':'NOT_REGISTERED_AS_COMPLETED: completed-run registrar requires all 20 valid fits and matched evaluation',
        'preservation':'Original protocol, numerical baseline, source receipts, partial models and predictions remain unchanged. This supplement supersedes their scientific-comparison admissibility, not their bytes.'}
    data=canonical_json_bytes(report); sha=hashlib.sha256(data).hexdigest()
    path=OUT/'final-archive/sha256'/sha/'manifest.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=data: raise ValueError('Immutable archive conflict')
    else:
        with path.open('xb') as stream:stream.write(data)
    # Verify listed bytes after packaging; no estimator loads or source reads.
    for r in files:
        if ref(Path(r['path']))!=r: raise ValueError('Archive reference changed')
    print(json.dumps(ref(path)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--finalize',type=Path)
    args=parser.parse_args()
    finalize(args.finalize) if args.finalize else prepare()
