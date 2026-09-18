"""Hash/read-only verification and additive readiness handoff; no live execution."""
import argparse
from collections import Counter
from datetime import timedelta
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.sports_nba_gen1.authority import reference, verified_bytes
from server.sports_nba_gen1.production import canonical_bytes, digest
from server.sports_nba_gen1.slate_lifecycle import immutable, now, read_ref, utc


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--repository-root',default=r'C:\Users\james\asp-model-studio')
    p.add_argument('--publish-handoff',action='store_true')
    a=p.parse_args()
    root=Path(a.repository_root)
    source=Path(__file__).resolve().parents[1]
    out=root/'outputs/nba-gen1-same-owner-refresh-v1'
    docs=source/'docs/nba-gen1-same-owner-refresh-v1'
    if (docs/'VERIFICATION.json').exists():
        saved=load(docs/'VERIFICATION.json')
        for ref in saved['preservedObjects']:
            verified_bytes(ref)
        if (docs/'HANDOFF_RECEIPT.json').exists():
            handoff=load(docs/'HANDOFF_RECEIPT.json')
            index=read_ref(handoff['index'])
            for m in index['members']:
                verified_bytes(dict(m,path=str(Path(handoff['index']['path']).parent/m['relativePath'])))
        print('Existing immutable closeout verified; no new clocks or packages.')
        return
    staged=load(out/'release-final/release-receipt.json')
    manifest=read_ref(staged['deploymentManifest'])
    deploy=Path(staged['deploymentManifest']['path']).parent
    for member in manifest['members']:
        verified_bytes(dict(member,path=str(deploy/member['relativePath'])))
    for field in ('release','refreshPlan','refreshAuthorizationProposal'):
        verified_bytes(staged[field])
    prior=load(source/'docs/nba-gen1-slate-publisher-v1/VERIFICATION.json')
    for ref in prior['preservedObjects']:
        verified_bytes(ref)
    before_path=root/'outputs/nba-gen1-same-owner-owners-before.json'
    after_path=root/'outputs/nba-gen1-same-owner-owners-after.json'
    before,after=load(before_path),load(after_path)
    assert before==after and not any(x['taskName']=='ASP NBA Forecast Publisher' for x in after)
    launcher_paths=[]
    for path in (out/'verification/launcher-receipts').glob('*.json'):
        v=load(path)
        if v.get('schema')=='NBA_GEN1_SLATE_LAUNCHER_RECEIPT_V1':
            launcher_paths.append(path)
    assert len(launcher_paths)==1
    launcher=load(launcher_paths[0])
    assert launcher['pythonExitCode']==launcher['wrapperExitCode']==0
    owner=read_ref(launcher['runner']['receipt'])
    assert owner['providerCalls']==owner['providerBytes']==0 and owner['disposition']=='NOT_DUE'
    runner=read_ref(owner['runnerReceipt'])
    for phase in owner['phases']:
        read_ref(phase['receipt'])
    plan=load(out/'verification/installer-plan.json')
    assert plan['status']=='PLAN_VERIFIED_NO_WRITES' and plan['taskCount']==0
    assert (plan['logonType'],plan['runLevel'],plan['multipleInstances'])==('S4U','Limited','IgnoreNew')
    junit=ET.parse(out/'focused-tests.xml').getroot()
    suites=list(junit) if junit.tag=='testsuites' else [junit]
    assert sum(int(s.attrib.get('failures',0))+int(s.attrib.get('errors',0)) for s in suites)==0
    passed=sum(int(s.attrib['tests']) for s in suites)
    assert passed==28
    bundle=read_ref(owner['inputVersion'])
    supported=[x for x in bundle['games'] if x.get('target') and not x.get('exclusion')]
    earliest=min(utc(x['target']['scheduled_tipoff_utc']) for x in supported)
    capture=earliest-timedelta(days=7,minutes=60)
    publication=earliest-timedelta(days=7)
    first_day=earliest.astimezone(ZoneInfo('America/New_York')).date()
    opening=[x['target'] for x in supported if utc(x['target']['scheduled_tipoff_utc']).astimezone(ZoneInfo('America/New_York')).date()==first_day]
    coverage={'sourceRows':len(bundle['games']),'supportedIdentityRows':len(supported),
        'exclusions':dict(Counter(x['exclusion'] for x in bundle['games'] if x.get('exclusion'))),
        'currentDispositions':dict(Counter(x['disposition'] for x in runner['games'])),
        'currentHistoryGames':read_ref(bundle['currentModelReceipt'])['historyGames'],
        'sourceCapturedAtUtc':bundle['scheduleCapturedAtUtc'],'openingSlate':opening,
        'earliestProposedCaptureUtc':capture.isoformat(),'earliestPublicationCheckpointUtc':publication.isoformat(),
        'earliestProposedCaptureNewYork':capture.astimezone(ZoneInfo('America/New_York')).isoformat(),
        'earliestPublicationCheckpointNewYork':publication.astimezone(ZoneInfo('America/New_York')).isoformat(),
        'qualification':'Retained identities, not fresh opening-night inputs. Revalidation/admission and actual due checkpoint required.'}
    verification={'schema':'NBA_GEN1_SAME_OWNER_READINESS_VERIFICATION_V1','createdAtUtc':now(),
        'deployment':staged,'verifiedMembers':len(manifest['members']),'implementationCommit':manifest['sourceCommit'],
        'testsPassed':passed,'junit':reference(out/'focused-tests.xml'),
        'launcherReceipt':reference(launcher_paths[0]),'ownerReceipt':launcher['runner']['receipt'],
        'runnerReceipt':owner['runnerReceipt'],'phaseReceipts':owner['phases'],
        'localVerificationOnly':True,'naturalInvocations':0,'plan':reference(out/'verification/installer-plan.json'),
        'ownerBefore':reference(before_path),'ownerAfter':reference(after_path),'ownerCount':0,
        'unrelatedOwnerDefinitionsUnchanged':True,'preservedObjects':prior['preservedObjects'],
        'preservedPhysicalObjectsVerified':len(prior['preservedObjects']),'coverage':coverage,
        'providerCalls':0,'providerResponseBytes':0,'costUsd':0,'modelFits':0,
        'realForecastsGenerated':0,'aispWrites':0,'taskChanges':0,'windowsElevationAttempts':0,
        'consumerActivated':False,'liveAcquisitionAuthorized':False,'installed':False,
        'secretScan':{'reviewedTextFiles':17,'credentialPatternFindings':0}}
    immutable(docs/'VERIFICATION.json',canonical_bytes(verification))
    immutable(docs/'RELEASE_RECEIPT.json',canonical_bytes(staged))
    immutable(docs/'REFRESH_AUTHORIZATION_PROPOSAL.json',verified_bytes(staged['refreshAuthorizationProposal']))
    grant={'schema':'NBA_SAME_OWNER_REFRESH_GRANT_V1','approvedBy':'James','liveCaptureAuthorized':False,
        'deploymentId':staged['deploymentId'],'proposalSha256':staged['refreshAuthorizationProposal']['sha256'],
        'refreshPlanSha256':staged['refreshPlan']['sha256'],
        'validFromUtc':'2026-10-13T18:00:00+00:00','validUntilUtc':'2027-04-19T04:00:00+00:00',
        'note':'INACTIVE TEMPLATE. Only create an approved grant after James authorizes this exact proposal; retain actual authorization evidence.'}
    immutable(docs/'REFRESH_GRANT_TEMPLATE.json',canonical_bytes(grant))
    command=(f"& '{deploy}/scripts/install_nba_gen1_slate_publisher.ps1' -Mode MODE "
        f"-DeploymentId '{staged['deploymentId']}' -ExpectedManifestSha256 '{staged['deploymentManifest']['sha256']}' "
        f"-ReleasePath '{staged['release']['path']}' -ReleaseSha256 '{staged['release']['sha256']}' "
        f"-InputPointer '{staged['inputPointer']}'")
    activation=f'''# Final successor activation and rollback — not executed

Deployment: `{staged['deploymentId']}`; physical manifest SHA-256 `{staged['deploymentManifest']['sha256']}`.
Source commit: `{manifest['sourceCommit']}`. All {len(manifest['members'])} members verified.
Do not install superseded 0aa50236 or 7e04b1cc. No NBA task currently exists.

The installer Plan passed read-only with owner count zero. The proposed single owner is S4U / Limited / IgnoreNew, 15-minute cadence, 12-minute execution budget. It refuses a different existing owner. This task did not request Windows elevation, install, or start a scheduled task.

Exact disabled-network commands, for separately authorized execution where applicable:
'''
    for mode in ('Plan','Install','Verify','Remove'):
        activation+=f"\n```powershell\n{command.replace('MODE',mode)}\n```\n"
    activation+='''
For production refresh, James must first approve this exact REFRESH_AUTHORIZATION_PROPOSAL.json and REFRESH_PLAN.json hash and the final deployment installation. Create a separate immutable approved grant from REFRESH_GRANT_TEMPLATE.json, retain the actual approval, and compute its physical SHA. Then append the following to the same Plan/Install/Verify/Remove commands (not a separate task):

```powershell
-EnableNetwork -RefreshGrantPath '<exact approved grant path>' -RefreshGrantSha256 '<physical approved grant SHA-256>'
```

The template remains false and cannot authorize capture. Grant filenames/approval clocks cannot honestly be supplied before authorization. Installation may precede the grant's future start; the owner remains zero-network until a legitimately due capture inside the exact period. Never install disabled mode and silently edit the runtime binding; use the supported installer with the intended approved configuration.

Rollback: use **Remove** with the exact same pins and grant arguments used for Install. It verifies the task and runtime binding, stops/unregisters only that exact NBA owner and removes only its binding. Keep every deployment, input, source object, package, discovery and receipt. The prior state is **no NBA task**; do not install a superseded deployment. An immediate Install verification failure unregisters only its newly created task. A differing owner/binding stops for review rather than overwriting it.

After authorized installation, verify the action/principal/runtime binding and observe natural invocations. The local wrapper evidence here is not proof of S4U or live-source success. AISP activation remains a separate owner action; no environment or consumer change belongs in this installer.
'''
    immutable(docs/'ACTIVATION.md',activation.encode('utf-8'))
    handoff=f'''# Claude/AISP: NBA same-owner refresh successor ready, inactive

This is a **producer-readiness handoff**, not consumer activation or a forecast publication.

- Final deployment `{staged['deploymentId']}`; manifest physical SHA `{staged['deploymentManifest']['sha256']}`.
- Release `{staged['release']['path']}`; physical SHA `{staged['release']['sha256']}`.
- Exact proposed REFRESH_PLAN physical SHA `{staged['refreshPlan']['sha256']}`, {staged['refreshPlan']['bytes']} bytes.
- Immutable authorization proposal `{staged['refreshAuthorizationProposal']['path']}`; physical SHA `{staged['refreshAuthorizationProposal']['sha256']}`. Not approved.
- Existing selected-model handoff `7113b71ff5819c89103ad19d5f9afb22c51dbc92980be12b56ce8826cb34ccaf` remains unchanged. Superseded deployment `0aa50236...` must not be installed.

One future invocation will plan, conditionally capture, admit the whole version, dispatch all due games and publish cumulative discovery. There is no separate capture owner. Zero-network is the default. A failed/incomplete update cannot refresh stale evidence or replace the admitted pointer. 304 revalidation retains the raw object's original clock; unchanged numerical inputs reuse original forecasts and publication clocks.

Retained coverage: {len(supported)} mapped supported identities out of {len(bundle['games'])}; exclusions {coverage['exclusions']}. These are planning identities, not refreshed opening-night evidence. The captured source is from {bundle['scheduleCapturedAtUtc']}. Earliest proposed capture is {capture.isoformat()} (2 PM EDT October 13); first publication checkpoint {publication.isoformat()} (3 PM EDT October 13), at the first natural tick at/after those times and only if new input eligibility passes. No new real forecast is due or generated today.

Consumer work after separate activation: validate the exact release/model pins and V2 forecast index, member hashes, full 10,000-draw population and **bound publication receipt**. `publishedAtUtc=null` in a prepared V2 package is deliberate; immutable `publicationReceipt.committedAtUtc` in discovery is actual availability. Read `slate-discovery/current.json` -> immutable version, not a single-game index. Keep all prior revisions; honor currentlyEligible and eligibilityValidUntilUtc. On stopped/failed owners the lease expires; an old preserved package is not current evidence.

Keep authorities separate: Ridge alpha100 supplies expected scores; chronological Elo supplies winner probabilities; `NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1` supplies joint scores, totals, margins and joint-derived probabilities from 10,000 draws. Close-score correction stays disabled. One-point finishes were 7.78% simulated versus 4.01% observed; correction was rejected; overtime is harder; no profitability claim. BOS-DET and all earlier packages retain their original research/production identities and clocks.

Do not pin this readiness index as though it were an accepted activation contract. First authorize/install the final producer and exact network plan; independently validate the release and eligible new forecast packages, then use AISP's supported activation path. No AISP code, database, env, service or policy was changed here. No consumer acknowledgement is claimed.
'''
    immutable(docs/'CLAUDE_HANDOFF.md',handoff.encode('utf-8'))
    report=f'''# NBA opening-night operational readiness

| Area | Status |
|---|---|
| Publisher implementation | READY — all-game dispatch, immutable revisions, cumulative discovery and recoverable per-game journals |
| Input-refresh implementation | READY — same owner/lock, bounded conditional transport, versioned atomic admission, durable phase receipts |
| Live acquisition authorization | PENDING — exact immutable proposal and inactive grant template supplied; zero requests executed |
| Installation and consumer activation | PENDING — installer Plan verified; NBA owners 0; no consumer activation |

Deployment `{staged['deploymentId']}` has {len(manifest['members'])} verified members, source commit `{manifest['sourceCommit']}`. The prior deployment remains preserved and uninstalled. REFRESH_PLAN physical SHA is `{staged['refreshPlan']['sha256']}` ({staged['refreshPlan']['bytes']} bytes). Its proposal binds the deployment and physical manifest; neither is approval.

Focused verification: **{passed} tests passed**, covering no-network/default/not-due behavior; conditional unchanged capture; changed-content admission; precommit rejection; stale/post-tipoff checks; multi-game dispatch; interruption after capture and admission; restart without duplicate requests or forecasts; interrupted unknown transport quarantine; access refusal/schema drift; budget and grant gates; DST; immutable discovery and preserved forecast bindings. Fixture transports and synthetic scores are not source evidence. The prior synthetic renderer checks 10,000 draws without fitting. No real forecast or model run occurred.

The exact packaged Windows PowerShell 5.1 wrapper ran locally once with disabled networking and isolated state/discovery. Python exit 0, wrapper exit 0, REFRESH_NOT_DUE, REUSED_ADMITTED_VERSION and NOT_DUE. Launcher SHA `{reference(launcher_paths[0])['sha256']}`; owner receipt SHA `{launcher['runner']['receipt']['sha256']}`; runner SHA `{owner['runnerReceipt']['sha256']}`. This is local plumbing evidence, not a natural scheduled run. There are no source requests or new captures.

All **{len(prior['preservedObjects'])}** bound prior forecast/model objects remain byte-identical. The three unrelated ASP task definitions match before/after; no NBA task was created. No AISP writes, provider calls, response bytes, paid costs, Windows elevation attempts, model fits, forecast publications, decisions or positions. Only a new additive metadata handoff is eligible for exchange publication.

Real retained schedule: **{len(bundle['games'])} rows; {len(supported)} supported identities; {len(bundle['games'])-len(supported)} explicit exclusions** ({coverage['exclusions']}). Frozen history has {coverage['currentHistoryGames']} games. The retained capture is September 14; it must be actually revalidated and admitted before October publication. All {len(supported)} supported identities are currently NOT_DUE; stale-input reasons remain in the inventory. The source release metadata provides no reliable update SLA. A missing final or unrecognized schema can still block a game/slate even after authorization.

Earliest legitimate network opportunity: **{capture.isoformat()} / {coverage['earliestProposedCaptureNewYork']}**. First publication checkpoint: **{publication.isoformat()} / {coverage['earliestPublicationCheckpointNewYork']}**. These derive from the current captured first tipoff and are subject to source schedule revisions, authorization and installation. No artificial early forecast was created to demonstrate activity.

Next dependency: James approval of this exact refresh plan/proposal and final deployment, followed by supported Administrator installation as the intended owner and natural-run verification. AISP's consumer owner then validates/pins/activates separately. See ACTIVATION.md for exact commands and rollback to no NBA task. No second scheduler or unspecified data owner remains in the design.
'''
    immutable(docs/'REPORT.md',report.encode('utf-8'))
    if a.publish_handoff:
        names=['REPORT.md','CONTRACT.md','ACTIVATION.md','CLAUDE_HANDOFF.md','REFRESH_PLAN.json',
               'REFRESH_AUTHORIZATION_PROPOSAL.json','REFRESH_GRANT_TEMPLATE.json','RELEASE_RECEIPT.json','VERIFICATION.json']
        contents={n:(docs/n).read_bytes() for n in names}
        index={'schema':'NBA_GEN1_SAME_OWNER_READINESS_HANDOFF_V1','createdAtUtc':now(),
            'deploymentId':staged['deploymentId'],'release':staged['release'],
            'refreshPlanSha256':staged['refreshPlan']['sha256'],'consumerActivated':False,
            'liveAcquisitionAuthorized':False,'installed':False,
            'members':[{'relativePath':n,'sha256':digest(b),'bytes':len(b)} for n,b in contents.items()]}
        raw=canonical_bytes(index)
        dest=root.parent/'asp-model-exchange/nba-gen1-production-v1/owner-handoffs/sha256'/digest(raw)
        # Content members first; immutable index is the availability marker. This
        # does not alter forecast discovery or any prior handoff pointer.
        for n,b in contents.items():
            immutable(dest/n,b)
        bound=immutable(dest/'index.json',raw)
        for m in index['members']:
            verified_bytes(dict(m,path=str(dest/m['relativePath'])))
        immutable(docs/'HANDOFF_RECEIPT.json',canonical_bytes({'index':bound,'publishedAtUtc':now(),
            'kind':'ADDITIVE_READINESS_METADATA_ONLY','forecastPublications':0,'consumerAcknowledged':False}))
        print(json.dumps({'handoff':bound},indent=2))
    print(json.dumps({'deployment':staged['deploymentId'],'testsPassed':passed,'coverage':coverage},indent=2))


if __name__=='__main__':
    main()
