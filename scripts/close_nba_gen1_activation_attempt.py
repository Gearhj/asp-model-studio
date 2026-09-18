"""Retain the failed authorized activation and publish an additive handoff.

No installation, task execution, network, model, provider, or AISP operation.
The receipt records observed failure; it never certifies an unobserved run.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import os
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=Path(r'C:\Users\james\asp-model-studio\outputs\nba-gen1-producer-activation-v1')
DOCS=ROOT/'docs/nba-gen1-producer-activation-v1'
EXCHANGE=Path(r'C:\Users\james\asp-model-exchange\nba-gen1-production-v1\activation-receipts\sha256')
DEPLOYMENT='7e04b1cc6f68ad4a4c0a3833f28751fdbfc54957e019e2cb5743946eeae25716'
HANDOFF='7113b71ff5819c89103ad19d5f9afb22c51dbc92980be12b56ce8826cb34ccaf'
HANDOFF_PATH=rf'C:\Users\james\asp-model-exchange\nba-gen1-production-v1\handoffs\sha256\{HANDOFF}\index.json'

def raw(value):
    return (json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,indent=2)+'\n').encode('utf-8')

def ref(path):
    p=Path(path); b=p.read_bytes()
    return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}

def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def immutable(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=data: raise ValueError('Immutable receipt conflict: '+str(path))
    else:
        with path.open('xb') as handle: handle.write(data)

def main():
    audit_path=EVIDENCE/'independent-audit-after.json'
    audit=read(audit_path)
    before=read(EVIDENCE/'independent-audit-before.json')
    owner=read(EVIDENCE/'final-owner-state.json')
    assert owner['nbaOwnerCount']==0 and not owner['runtimeManifestExists']
    assert owner['otherOwnerDefinitionsUnchanged'] is True
    for key in ['deploymentMembers','packageMembers','preservedResearchArtifacts']:
        assert audit[key]==before[key]
    junit=Path(r'C:\Users\james\asp-model-studio\.tmp\nba-activation-tests-20260918T0251\six-point-tests.xml')
    suite=ET.parse(junit).getroot().find('testsuite')
    assert suite is not None and suite.attrib['tests']=='6'
    assert suite.attrib['errors']=='0' and suite.attrib['failures']=='0'
    timestamp=datetime.now(timezone.utc).isoformat()
    receipt={
        'schema':'NBA_GEN1_PRODUCER_ACTIVATION_RECEIPT_V1','createdAtUtc':timestamp,
        'disposition':'NBA_GEN1_PRODUCTION_BLOCKED','producerStatus':'BLOCKED_NOT_INSTALLED',
        'authorization':'James explicitly authorized only the exact 7e04b1 deployment, S4U/Limited/IgnoreNew, 15 minutes',
        'authorizedDeploymentId':DEPLOYMENT,'deploymentManifest':audit['deployment'],
        'verifiedDeploymentMembers':26,'productionHandoff':audit['handoff'],
        'installedDeploymentId':None,'canonicalTaskName':'ASP NBA Forecast Publisher',
        'canonicalOwnerCount':0,'runtimeBinding':None,
        'installAttempts':[
            {'result':'FAILED_USER_ID_PARAMETER','exitCode':1,'windowsHresult':'0x80070057',
             'evidence':ref(EVIDENCE/'installer-attempt.txt')},
            {'result':'FAILED_ADMINISTRATOR_TOKEN_REQUIRED','exitCode':1,'windowsHresult':'0x80070005',
             'evidence':ref(EVIDENCE/'installer-attempt-2.txt')},
            {'result':'WINDOWS_ELEVATION_CANCELED','administratorProcessStarted':False,
             'observedAtUtc':'2026-09-18T02:56:10.6883966+00:00',
             'message':'Start-Process -Verb RunAs returned: The operation was canceled by the user.',
             'furtherElevationAttempted':False}],
        'naturalInvocations':[],'naturalLauncherExitCodes':[], 'naturalRunnerExitCodes':[],
        'naturalDispositions':[],'twoConsecutiveInvocationsVerified':False,
        'verificationUnavailableReason':'No task was registered; no natural execution can occur',
        'rollback':{'required':False,'performed':False,'reason':'Task and runtime binding were never created'},
        'tests':{'passed':6,'failed':0,'deselected':7,'fixturePopulation':'SYNTHETIC_ONLY',
                 'junit':ref(junit),'temporaryDirectory':'fresh default inherited permissions',
                 'elevationUsed':False,'aclChanged':False},
        'installer':ref(ROOT/'scripts/install_nba_gen1_publisher.ps1'),
        'installerPlan':ref(EVIDENCE/'installer-plan-final.json'),
        'independentAudit':ref(audit_path),'independentForecastAndPopulationChecksPassed':True,
        'fullSlateReadiness':audit['fullSlateReadiness'],
        'consumerStatus':'NOT_ACTIVATED_BY_THIS_TASK','consumerAcknowledgement':False,
        'preservation':{'all26DeploymentMembersByteIdentical':True,
            'phiNykPackageAndPopulationByteIdentical':True,'bosDetIndexedResearchArtifactsByteIdentical':True,
            'otherOwnerDefinitionsUnchanged':True,'otherOwnerDefinitions':ref(EVIDENCE/'owners-after.json'),
            'gen2PopulationTouched':False},
        'activity':{'providerCalls':0,'providerResponseBytes':0,'costUsd':0,'aispWrites':0,
            'forecastPublications':0,'forecastOrSimulationRuns':0,'realModelFits':0,
            'exchangeForecastWrites':0,'exchangeActivationCloseoutPackages':1},
        'implementationCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'priorReadinessCorrection':'Prior statement that the owner fails closed when current history becomes stale was unsupported: the pinned reuse branch precedes freshness and deadline checks.',
    }
    args=(f"-DeploymentId '{DEPLOYMENT}' -HandoffPath '{HANDOFF_PATH}' "
          f"-HandoffSha256 '{HANDOFF}' -EffectiveAtUtc '2026-09-18T01:16:08.176807+00:00'")
    command=f"& '{ROOT / 'scripts/install_nba_gen1_publisher.ps1'}' -Mode Install {args}"
    verify=command.replace('-Mode Install','-Mode Verify')
    rollback=command.replace('-Mode Install','-Mode Remove')
    report=f"""# NBA producer activation closeout

**NBA_GEN1_PRODUCTION_BLOCKED — owner not installed.** Windows rejected registration with `0x80070005` (Administrator token required); the subsequent standard Windows elevation was cancelled. No owner or runtime binding was created. There were zero natural invocations, so no launcher/runner exit or disposition is claimed. A rollback was unnecessary. Consumer activation was not performed.

All 26 deployment members and the exact manifest/handoff hashes pass. The six previously blocked point tests pass in fresh, permitted directories with default inherited permissions: 6 passed, 7 deselected, no ACL changes or elevation. These are synthetic mechanics tests, not fitted production models or performance evidence.

The supported installer now provides a read-only Plan, a read-only Verify, exact action/principal/cadence checks, refusal to overwrite another owner, and manifest writing only after successful registration. Explicit SID task XML fixes the observed UserId rejection; registration still needs Administrator elevation. The pinned deployment and its launcher are unchanged.

## Forecast verification

PHI at NYK, ESPN 401909089: package `8a725a439af9f9ad4828281ff9bcdec5511c2af292c3feac4826b975dfa0d4c2`, physical forecast `8c69bc25e64c969b0dfd2f0cfe3b3ec7af0f8699358368a44ab4289ba3f46282`, population `62b48824b2746656d2ec9e93c5ebcd6b3768e8662b37b0e0703a3a463e1eb17c`, logical HOME/AWAY int64 SHA `6d7b75fbe79f3803269643f88bf29b117e182730d38b2ba5477d0bb70e2c0bb7`. Independent checks reconstructed all four PMFs, intervals, totals queries, means, orientation and probability mass directly from 10,000 untied paired draws. Source cutoff September 14 13:04:43 UTC and publication September 18 01:16:32 UTC both precede October 20 23:00 UTC tipoff.

Ridge expected PHI/NYK scores are 111.1184/117.0613; Elo PHI/NYK win probabilities are 0.322743/0.677257; joint means are 111.1279/117.2234 and joint probabilities are 0.3181/0.6819. Those remain distinct channels. Close-score is disabled. No profitability authority follows.

## Full-slate readiness correction

The snapshot contains 1,205 regular entries, of which 1,197 have mapped teams and unstarted, nonneutral status. Five have unresolved placeholder team IDs and three further rows are excluded by status/neutral conditions. The recurring wrapper passes no game ID and therefore only reaches PHI–NYK 401909089.

| Opening-night captured game | UTC start | Exact recurring-path coverage |
|---|---|---|
| BOS at DET 401909088 | October 20 19:00 | Explicitly excluded; preserve original research forecast |
| PHI at NYK 401909089 | October 20 23:00 | Existing immutable package reuse only |
| OKC at SAS 401909090 | October 21 01:30 | Mapped source identity exists, but recurring wrapper does not dispatch it |

No automatic source-refresh owner exists. Model Studio owns future governed schedule/history capture, but this authorization grants no new acquisitions. Before opening night, refresh identity/status/tipoff evidence; after governed finals, refresh result membership and chronological features. The exact publisher is pinned to the September 14 schedule digest and cannot ingest a changed schedule without a successor. It has no multi-game dispatcher or publication checkpoint; its discovery writer replaces the index with one game. Its reuse branch returns before freshness and deadline checks, and it retains no per-invocation launcher or runner receipt (stdout only). The host Task Scheduler event log is disabled and was not changed.

**Full-slate readiness: false. Next genuinely due new publication: not defined by this deployment.** Installing it enables repeated PHI–NYK reuse and does not establish opening-night operational readiness. The preceding report's claim of stale-history fail-closed behavior is corrected by this closeout. A successor needs explicit approval before installation; none was built or installed here.

## Remaining activation actions

The authorization remains for this exact limited publisher. Run as James in an Administrator PowerShell:

```powershell
{command}
```

Read-only verification:

```powershell
{verify}
```

Then observe two natural runs; do not manually start the publisher. The pinned launcher has no durable invocation log, so runner disposition must not be inferred from the old publication receipt and called observed stdout. Supported rollback of only this task and binding, preserving artifacts:

```powershell
{rollback}
```

Claude must independently validate the model handoff and forecast package, confirm or implement the NBA consumer schema and pin handling, then obtain separate consumer activation authority before applying the two pins below. Their existence in this producer handoff does not prove AISP currently implements them. Preserve all earlier research labels and the prospective effective boundary; import idempotently and retain a consumer receipt.

```text
NBA_PRODUCTION_HANDOFF_PATH={HANDOFF_PATH}
NBA_PRODUCTION_HANDOFF_SHA256={HANDOFF}
```

There were zero provider calls/bytes, cost, AISP writes, model fits, simulation runs and forecast publications. Only this additive closeout package is published to the exchange. All three unrelated ASP task definitions and indexed BOS–DET research artifacts remain unchanged.
"""
    DOCS.mkdir(parents=True,exist_ok=True)
    receipt_raw=raw(receipt)
    immutable(EVIDENCE/'activation-receipt.json',receipt_raw)
    immutable(DOCS/'ACTIVATION_RECEIPT.json',receipt_raw)
    immutable(DOCS/'CLAUDE_HANDOFF.md',report.encode('utf-8'))
    immutable(DOCS/'INDEPENDENT_AUDIT.json',audit_path.read_bytes())
    package_files={'ACTIVATION_RECEIPT.json':receipt_raw,'CLAUDE_HANDOFF.md':report.encode('utf-8'),
                   'INDEPENDENT_AUDIT.json':audit_path.read_bytes()}
    index={'schema':'NBA_GEN1_ACTIVATION_CLOSEOUT_INDEX_V1','createdAtUtc':timestamp,
           'disposition':receipt['disposition'],'predecessorProductionHandoffSha256':HANDOFF,
           'files':[{'relativePath':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
                    for name,data in sorted(package_files.items())]}
    index_raw=raw(index); address=hashlib.sha256(index_raw).hexdigest()
    EXCHANGE.mkdir(parents=True,exist_ok=True)
    stage=EXCHANGE/('.stage-'+uuid.uuid4().hex)
    stage.mkdir()
    for name,data in package_files.items(): immutable(stage/name,data)
    immutable(stage/'index.json',index_raw)
    for item in index['files']: assert ref(stage/item['relativePath'])['sha256']==item['sha256']
    destination=EXCHANGE/address
    os.rename(stage,destination)
    publication={'publishedAtUtc':datetime.now(timezone.utc).isoformat(),'index':ref(destination/'index.json'),
        'receipt':ref(destination/'ACTIVATION_RECEIPT.json'),'handoff':ref(destination/'CLAUDE_HANDOFF.md'),
        'consumerAcknowledged':False,'discoveryChanged':False}
    immutable(EVIDENCE/'closeout-publication.json',raw(publication))
    immutable(DOCS/'PUBLICATION.json',raw(publication))
    print(json.dumps(publication,indent=2))

if __name__=='__main__':main()
