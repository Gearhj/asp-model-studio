"""Deliver one existing NBA research forecast; no model execution or source intake.

Uses the established research exchange packages/sha256/<physical-index-hash>
convention. Original payload clocks remain intact; publication is a receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'outputs/nba-gen1-exchange-delivery-v1'
PRIOR = ROOT/'outputs/nba-gen1-long-gap-v1'
EXCHANGE = Path('C:/Users/james/asp-model-exchange/nba-gen1-research-v1/point-elo-v1/packages/sha256')
FORECAST_SHA = '27f766e341cc211317d61e7ed842d7bbff7521664da5b27a0776bfc5394a8767'
LOCAL_INDEX_SHA = '22a6748510653c50820aea4391a79040058d55230a793a3ee059597bc82d4a7a'
FORECAST_ID = 'nba-point:1b0f9b6fa8d5ce8adc2532664afd941eaf889b6bdf6d6a8013295c43ba1e554f'
SCHEMA = 'NBA_GEN1_REDUCED_POINT_ELO_FORECAST_V1'


def now():
    return datetime.now(timezone.utc).isoformat()


def blob(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()


def ref(path):
    path=Path(path).resolve(); raw=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def verified(bound):
    raw=Path(bound['path']).read_bytes()
    if len(raw)!=bound['bytes'] or hashlib.sha256(raw).hexdigest()!=bound['sha256']:
        raise ValueError('Physical artifact changed: '+bound['path'])
    return raw


def immutable(path, raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError('Refusing to replace existing artifact: '+str(path))
    else:
        with path.open('xb') as stream:stream.write(raw)
    return ref(path)


def read(path):
    return json.loads(Path(path).read_bytes())


def verify_package(directory):
    directory=Path(directory).resolve()
    index_ref=ref(directory/'index.json')
    if directory.name!=index_ref['sha256']:
        raise ValueError('Package directory must equal physical DELIVERY INDEX digest')
    index=read(directory/'index.json')
    for entry in index['files']:
        path=(directory/entry['relativePath']).resolve()
        if not path.is_relative_to(directory):raise ValueError('Package path escapes root')
        verified({'path':str(path),'sha256':entry['sha256'],'bytes':entry['bytes']})
    if ref(directory/'forecast.json')['sha256']!=FORECAST_SHA:
        raise ValueError('Original forecast bytes changed')
    if ref(directory/'original-local-index.json')['sha256']!=LOCAL_INDEX_SHA:
        raise ValueError('Original local index bytes changed')
    return index_ref


def stage():
    staged_path=OUT/'staged-publication.json'
    if staged_path.exists():
        staged=read(staged_path)
        verify_package(staged['stageDirectory'])
        for bound in staged['files']:verified(bound)
        return staged
    original_dir=PRIOR/'future-point-export/sha256'/FORECAST_SHA
    original_forecast=ref(original_dir/'forecast.json')
    original_index=ref(original_dir/'index.json')
    if original_forecast['sha256']!=FORECAST_SHA or original_index['sha256']!=LOCAL_INDEX_SHA:
        raise ValueError('User-specified original objects do not match physical bytes')
    forecast=read(original_forecast['path']);local_index=read(original_index['path'])
    if forecast['forecastId']!=FORECAST_ID or forecast['schema']!=SCHEMA or local_index['forecast']!=original_forecast:
        raise ValueError('Exact original forecast/index identity required')
    if forecast['game']['game_id']!='nba-espn:game:401909088':raise ValueError('Game identity changed')
    if forecast['distributions']!={'away':None,'drawCount':0,'home':None,'intervals':None,'margin':None,'status':'UNAVAILABLE','total':None}:
        raise ValueError('Original unavailable distribution semantics changed')
    if forecast['authority']!={'accountCreationAuthority':False,'productionAuthority':False,'researchOnly':True,'schedulerAuthority':False,'wageringAuthority':False}:
        raise ValueError('Research authority changed')
    for bound in forecast['bindings'].values():
        if isinstance(bound,dict) and {'path','sha256','bytes'}<=set(bound):verified(bound)
    sources={'forecast.json':Path(original_forecast['path']),
             'original-local-index.json':Path(original_index['path']),
             'POINT_FORECAST_CONTRACT.md':ROOT/'docs/nba-gen1-long-gap-v1/POINT_FORECAST_CONTRACT.md',
             'evidence/schedule.json':Path(forecast['bindings']['schedule']['path']),
             'evidence/history-coverage.json':Path(forecast['bindings']['historyCoverage']['path']),
             'evidence/schedule-clock-validation.json':PRIOR/'future-schedule-clock-validation.json',
             'evidence/original-export-verification.json':PRIOR/'future-point-export-verification.json'}
    index={'schemaVersion':'NBA_GEN1_POINT_ELO_EXCHANGE_INDEX_V1','createdAtUtc':now(),
           'artifactKind':'DELIVERY_OF_EXISTING_EARLY_RESEARCH_FORECAST','forecastSchema':SCHEMA,
           'forecastId':FORECAST_ID,'forecastSha256':FORECAST_SHA,'game':forecast['game'],
           'engine':forecast['engine'],'configurationIdentity':forecast['configurationIdentity'],
           'pointConfigurationIdentity':forecast['pointConfigurationIdentity'],
           'originalClocks':{key:forecast[key] for key in ('sourceCutoffUtc','createdAtUtc','exportedAtUtc','publishedAtUtc')},
           'publicationClock':'Separate publication-receipt.json beside this index; original payload publishedAtUtc=null remains unchanged.',
           'files':[{'relativePath':name,**{k:v for k,v in ref(path).items() if k!='path'},'originalSource':ref(path)} for name,path in sources.items()],
           'originalModelInputBindings':forecast['bindings'],
           'bindingResolution':'Original absolute provenance references remain unchanged and were physically verified. Import forecast fields directly; do not execute model artifacts. Included evidence copies are mapped by file digest, not rewritten into the forecast.',
           'consumer':{'label':'Early research forecast','originalForecastDate':'2026-09-14',
                       'fixture':'Boston Celtics at Detroit Pistons','capturedTipoffUtc':forecast['game']['scheduled_tipoff_utc'],
                       'expectedPointsField':'pointExpectations','expectedPointsMethod':'Ridge alpha100, ordinary-rest treatment',
                       'winnerProbabilityField':'winnerProbabilities','winnerProbabilityMethod':'Separate chronological Elo',
                       'probabilityUnits':'FRACTIONS_0_TO_1','scoreUnits':'POINTS_INCLUDING_OVERTIME',
                       'collapsedDetails':['restSupportAudit','limitations','bindings','sourceCutoffUtc','game.source_revision'],
                       'missingPregameInputs':['player strength/availability','projected starters','lineups','injuries'],
                       'sharedSimulationPopulation':False,'drawCount':0,'totalLineProbabilities':None,
                       'wagerEligibility':False,'automaticForecastRefresh':False},
           'revisionContract':{'importKey':['forecastId','forecastSha256'],
                               'sameIdDifferentBytes':'REJECT','sameIdSameBytes':'IDEMPOTENT_NO_DUPLICATE',
                               'futureSupersession':'Only a later authorized new forecast with new ID/digest and its own input/schedule/cutoff/creation/publication clocks may supersede this display snapshot. Its delivery envelope must name supersedesForecastId and supersedesForecastSha256; retain both objects.',
                               'scheduleCorrection':'Append a new schedule revision or authorized forecast. Preserve this captured schedule and clocks; display a current schedule separately if needed. No date/name-only game joins or silent ID merges.',
                               'publicationOnly':'This delivery is not a model/input revision and must not advance original forecast date.'},
           'authority':{**forecast['authority'],'funded':False,'wageringEligibility':False},
           'newForecastsCreated':0,'providerRequests':0,'simulations':0,'consumerAcknowledged':False}
    raw=blob(index);digest=hashlib.sha256(raw).hexdigest()
    package=OUT/'package/sha256'/digest;destination=EXCHANGE/digest
    for name,path in sources.items():immutable(package/name,path.read_bytes())
    immutable(package/'index.json',raw)
    text=f'''# CLAUDE_HANDOFF — NBA early point/Elo research forecast

Import delivery index: `{destination/'index.json'}`

**Package / physical index SHA-256:** `{digest}` ({len(raw):,} bytes). The delivery directory uses this INDEX digest. The original local directory used the FORECAST digest; do not interchange them.

Forecast schema: `{SCHEMA}`. Delivery envelope: `NBA_GEN1_POINT_ELO_EXCHANGE_INDEX_V1`.
Original forecast ID: `{FORECAST_ID}`.
Original forecast SHA-256: `{FORECAST_SHA}` (21,524 bytes).
Original local index SHA-256: `{LOCAL_INDEX_SHA}` (679 bytes), retained as `original-local-index.json`.

Verify raw physical bytes without newline normalization. Verify index hash equals package directory, then every `files` entry. Import `forecast.json` once by `(forecastId, forecastSha256)`; reject conflicting bytes for an existing ID. Original model/input bindings stay intact. The consumer reads retained values, not executable/pickle model files.

**Boston Celtics at Detroit Pistons** — canonical `nba-espn:game:401909088`, ESPN game ID `401909088`, Boston franchise `nba-neil:franchise:BOS`, Detroit franchise `nba-neil:franchise:DET`. Reconcile those source identities to AISP's NBA identities; do not join on date/team names alone. Captured schedule: **October 20, 2026, 19:00 UTC / 3:00 PM EDT**. The retained source explicitly marks the time valid. Preserve `game.source_revision` (`github-asset:552084615:sha256:d4ffe0d974dbec227af1ea5d731e0f36426839a170bfd0bbffc39b65f933a090`).

| Consumer value | Retained value | Meaning |
|---|---:|---|
| Boston expected points | 111.93456692347031 | Ridge alpha100 |
| Detroit expected points | 113.78511290268382 | Ridge alpha100 |
| Expected total / Detroit margin | 225.71967982615413 / +1.850545979213507 | Point expectations only |
| Boston win probability | 0.41887505293332616 | Separate Elo output |
| Detroit win probability | 0.5811249470666738 | Separate Elo output |
| Tie probability | 0 | Final NBA outcomes |

Probabilities are **fractions 0–1**; percentage display multiplies once. Points include overtime. Label the card **“Early research forecast — September 14, 2026”**. Label score means “Ridge expected points” and winner probabilities “Elo win probability — separate model output.” Do not imply a shared joint simulation or force their favored sides to agree.

Collapsed details should show `restSupportAudit`: both raw 190-day regular-season gaps were marked `SEASON_OPENER_NO_ORDINARY_REST`; treated rest/difference are null, rest-known and back-to-back indicators zero. They are not claims of 190 days of physical rest. Show missing player availability/strength, starters, lineups and injury inputs, plus historical-training revision limitations and original source/model bindings.

Keep `distributions.drawCount=0`; home, away, total, margin and interval distributions remain **null**. Over/Under probabilities, market fair prices, simulation intervals and MCSE are unavailable. Do not derive them from expected total or attach a simulation count. NBA stays research-only and unfunded: no account, wagers, decisions, bankroll, staking or scheduler authority is granted.

Original source cutoff: **2026-09-14T13:04:43.697362Z**.
Original forecast creation: **2026-09-14T13:09:39.891972Z**.
Original local export: **2026-09-14T13:09:39.901986Z**.
Actual exchange publication: read **`publication-receipt.json` beside this index**. Its `publishedAtUtc` is the delivery-completion clock. The unchanged original forecast retains `publishedAtUtc=null`; the original local index's `published=false` describes its earlier local-export state. Neither is rewritten or used to backdate exchange publication.

A later authorized forecast must be a new immutable ID/digest with its own captures and clocks. Name this forecast ID/hash in `supersedesForecastId` / `supersedesForecastSha256` in the new delivery envelope, and retain both versions. A schedule correction is an appended schedule revision or authorized new forecast, never an overwrite of this early snapshot. Publication of the same bytes is idempotent and is not a newer forecast.

Minimal AISP work: add this schema to the research importer; verify/deduplicate and reconcile ESPN identities; store original clocks and delivery clock separately; display the two labeled outputs and collapsed details; leave unsupported distribution/market fields unavailable. After actual import/display, return a consumer receipt under `{EXCHANGE.parents[1]/'consumer-receipts'}` naming package index SHA, forecast ID/SHA, canonical/source game identity, import time, imported count and display checks. Publication alone is not integration confirmation.

No forecast was regenerated, fitted or simulated for this delivery. Existing NBA assessments and MLB/NFL operations remain untouched. Reproduce delivery verification using `.venv/Scripts/python.exe -B scripts/publish_nba_gen1_point_exchange.py --verify`.
'''
    immutable(package/'CLAUDE_HANDOFF.md',text.encode())
    verify_package(package)
    files=[ref(package/name) for name in sources]+[ref(package/'index.json'),ref(package/'CLAUDE_HANDOFF.md')]
    staged={'schemaVersion':'NBA_POINT_ELO_DELIVERY_STAGING_V1','createdAtUtc':now(),
            'stageDirectory':str(package),'destinationDirectory':str(destination),
            'index':ref(package/'index.json'),'files':files,'publisherExecutable':ref(__file__),
            'originalForecast':original_forecast,'originalLocalIndex':original_index}
    immutable(staged_path,blob(staged))
    return staged


def verify_publication():
    receipt=read(OUT/'publication-receipt.json')
    for bound in receipt['files']:verified(bound)
    verify_package(Path(receipt['index']['path']).parent)
    destination=Path(receipt['index']['path']).parent/'publication-receipt.json'
    if destination.read_bytes()!=(OUT/'publication-receipt.json').read_bytes():
        raise ValueError('Local and delivered publication receipt differ')
    return {'status':'PUBLISHED_PHYSICAL_BYTES_VERIFIED','index':receipt['index'],
            'receipt':ref(destination),'handoff':receipt['handoff'],
            'publishedAtUtc':receipt['publishedAtUtc'],'consumerAcknowledged':False}


def publish():
    staged=stage()
    if (OUT/'publication-receipt.json').exists():return verify_publication()
    verified(staged['publisherExecutable'])
    target=Path(staged['destinationDirectory']).resolve()
    if target.parent!=EXCHANGE.resolve() or target.name!=staged['index']['sha256']:
        raise ValueError('Unexpected exchange destination')
    forecast=read(staged['originalForecast']['path'])
    if datetime.now(timezone.utc)>=datetime.fromisoformat(forecast['game']['scheduled_tipoff_utc']):
        raise ValueError('Original captured forecast deadline has passed')
    started=now();delivered=[];stage_root=Path(staged['stageDirectory'])
    # Publish the index last, after every indexed payload and handoff is intact.
    ordered=sorted(staged['files'],key=lambda b:Path(b['path']).name=='index.json')
    for bound in ordered:
        relative=Path(bound['path']).relative_to(stage_root)
        delivered.append(immutable(target/relative,verified(bound)))
    verify_package(target)
    receipt={'schemaVersion':'NBA_POINT_ELO_EXCHANGE_PUBLICATION_V1','status':'PUBLISHED',
             'publicationStartedAtUtc':started,'publishedAtUtc':now(),
             'index':ref(target/'index.json'),'handoff':ref(target/'CLAUDE_HANDOFF.md'),
             'files':delivered,'fileCount':len(delivered),'bytes':sum(b['bytes'] for b in delivered),
             'sourceStaging':ref(OUT/'staged-publication.json'),'originalForecastId':FORECAST_ID,
             'originalForecastSha256':FORECAST_SHA,'originalLocalIndexSha256':LOCAL_INDEX_SHA,
             'originalForecastClocksChanged':False,'newForecastsCreated':0,'providerRequests':0,
             'simulations':0,'consumerAcknowledged':False,'researchOnly':True,'funded':False,
             'wageringAuthority':False,'schedulerAuthority':False,'productionAuthority':False}
    raw=blob(receipt)
    immutable(target/'publication-receipt.json',raw)
    immutable(OUT/'publication-receipt.json',raw)
    return verify_publication()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--publish',action='store_true')
    modes.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    print(json.dumps(verify_publication() if args.verify else publish() if args.publish else stage(),indent=2))
