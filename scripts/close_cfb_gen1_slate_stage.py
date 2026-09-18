"""Retain staged CFB evidence and handoff metadata; no acquisition or activation."""
import argparse
from collections import Counter
from datetime import timedelta
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.sports_cfb_gen1.publication_io import reference,verified_bytes,canonical_bytes,digest
from server.sports_cfb_gen1.lifecycle import read_ref,immutable,now,utc


def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence-root',required=True);p.add_argument('--handoff-root',required=True)
    a=p.parse_args();root=Path(a.evidence_root);docs=Path(__file__).resolve().parents[1]/'docs/cfb-gen1-slate-publisher-v1'
    if (docs/'CLOSEOUT.json').exists():
        old=read_ref(reference(docs/'CLOSEOUT.json'))
        verified_bytes(old['handoffIndex']);print(json.dumps(old,indent=2));return
    stage=read_ref(reference(root/'final/release-receipt.json'));release=read_ref(stage['release'])
    prep=read_ref(stage['preparation']);bundle=read_ref(stage['inputVersion']);inventory=read_ref(stage['inventory'])
    for ref in prep['preservedObjects']:verified_bytes(ref)
    plan=json.loads((root/'final-installer-plan.json').read_text(encoding='utf-8-sig'))
    assert plan['status']=='PLAN_VERIFIED_NO_WRITES' and plan['taskCount']==0
    assert (root/'owner-bindings-before.json').read_bytes()==(root/'owner-bindings-after.json').read_bytes()
    launcher_paths=[p for p in (root/'final-verification-launcher').glob('*.json') if not p.name.endswith(('.started.json','.runner-result.json'))]
    assert len(launcher_paths)==1
    launcher_ref=reference(launcher_paths[0]);launcher=read_ref(launcher_ref)
    assert launcher['pythonExitCode']==launcher['wrapperExitCode']==0 and launcher['disposition']=='STALE_INPUT_REJECTED'
    owner=read_ref(launcher['runner']['receipt']);runner=read_ref(owner['runnerReceipt'])
    discovery=read_ref(runner['discovery']);assert discovery['packages']==[]
    counts=dict(Counter(x['disposition'] for x in inventory['games']))
    exclusions=dict(Counter(x.get('exclusion') for x in bundle['games'] if x.get('exclusion')))
    due=[x for x in inventory['games'] if x['disposition']=='STALE_INPUT_REJECTED']
    first=due[0]['target'];start=utc(first['scheduled_at']);edt=ZoneInfo('America/New_York')
    by_date=dict(Counter(utc(x['target']['scheduled_at']).astimezone(edt).date().isoformat() for x in due))
    aliases=read_ref(bundle['aliases'])
    summary={'schema':'CFB_GEN1_SLATE_READINESS_V1','createdAtUtc':now(),
        'status':'CFB_GEN1_PUBLISHER_STAGED_AWAITING_FRESH_INPUTS_AND_ACTIVATION',
        'modelReadiness':'EXACT_RETAINED_BASELINE_REPRODUCED_NO_REFIT',
        'publisherReadiness':'IMPLEMENTED_FOCUSED_VERIFICATION_PASSED_NOT_INSTALLED',
        'refreshReadiness':'OFFLINE_ADMISSION_IMPLEMENTED_BOUNDED_LIVE_CAPTURE_REQUIRES_AUTHORIZATION',
        'consumerActivation':'NOT_AUTHORIZED_NOT_PERFORMED_EXISTING_RESEARCH_SCHEMA_ONLY',
        'stage':stage,'modelBindings':release['modelBindings'],'featureCount':len(release['featureColumns']),
        'residualDonors':prep['baselineReproductions'][0]['transformationAccounting']['donorCount'],
        'reproductions':prep['baselineReproductions'],'featureRowsExactlyReproduced':prep['allRetainedFeatureRowsExactlyReproduced'],
        'inventoryAsOfUtc':inventory['createdAtUtc'],'scheduleCapturedAtUtc':bundle['scheduleCapturedAtUtc'],
        'sourceCutoffUtc':bundle['sourceCutoffUtc'],'inventoryCounts':counts,'exclusionCounts':exclusions,
        'dueByNewYorkDate':by_date,'dueButStale':len(due),'freshEligibleForecasts':0,
        'priorIdentityOrFeatureBlockersWithinDue':sum(bool(x['underlyingInputBlockers']) for x in due),
        'sourceSchoolIds':len({x['sourceTeamId'] for x in aliases['aliases']}),'effectiveAliasRows':len(aliases['aliases']),
        'earliestRetainedGame':first,'earliestLegitimatePublication':'After approved fresh capture/admission and authorized producer execution, while an original checkpoint is open; none issued in this task',
        'firstGamePublicationCloseUtc':(start-timedelta(minutes=30)).isoformat(),
        'nextFirstGameCheckpointUtc':(start-timedelta(hours=6)).isoformat(),
        'installerPlan':reference(root/'final-installer-plan.json'),'launcher':launcher_ref,'ownerReceipt':launcher['runner']['receipt'],
        'runnerReceipt':owner['runnerReceipt'],'isolatedDiscovery':runner['discovery'],
        'canonicalTaskCount':0,'otherOwnerDefinitionHashesUnchanged':True,
        'ownerBefore':reference(root/'owner-bindings-before.json'),'ownerAfter':reference(root/'owner-bindings-after.json'),
        'verification':{'focusedTests':16,'fullFocusedRun':'16 passed in 13.31s',
            'subsequentRequiredSchemaGuard':'Affected admission test passed in 6.22s',
            'consumerPureVerifierAndPmfs':'Actual retained AISP function bodies exercised without database/session imports or writes',
            'consumerCodeEvidence':release['consumerCodeEvidence'],'preservedObjects':len(prep['preservedObjects']),
            'deployedMembers':14,'powershellVersion':'Windows PowerShell 5.1',
            'launcherDurationSeconds':(utc(launcher['completedAtUtc'])-utc(launcher['startedAtUtc'])).total_seconds()},
        'activity':{'providerCalls':0,'providerBytes':0,'costUsd':0,'modelFits':0,'reproducedDrawsTotal':30000,
            'reproductionNote':'Initial Coastal verification 10000, then two independent baseline cases 20000; no new study or forecasts',
            'newForecasts':0,'forecastExchangePublications':0,'aispWrites':0,'taskChanges':0,
            'liveDiscoveryWrites':0,'stagedMetadataHandoffOnly':True,'consumerAcknowledged':False}}
    immutable(docs/'READINESS.json',canonical_bytes(summary))
    table='\n'.join(f'| {d} | {n} |' for d,n in by_date.items())
    report=f'''# CFB Gen1 prospective slate publisher

**CFB_GEN1_PUBLISHER_STAGED_AWAITING_FRESH_INPUTS_AND_ACTIVATION.** The exact numerical baseline is reproduced and a multi-game publisher is staged. It is not installed, AISP is not activated, and no new real forecast was issued from stale evidence.

## Model and independent reproduction

`{release['configurationIdentity']}` remains selected. Model physical SHA `{release['modelBindings']['selectedModel']['physicalSha256']}`; training through 2025; 35 frozen features and fitted preprocessing; 7,067 earlier season-forward paired residual donors. Ridge alpha100 points, frozen Development-calibrated margin probabilities, Elo diagnostic probabilities and joint probabilities remain separate. No challenger, recalibration or new family is enabled.

Both retained 10,000-draw populations reproduced in their exact original order. All 888 retained current feature rows also matched exactly. This is numerical reproduction, not a new accuracy study.

| Preserved research game | Ridge away / home | Calibrated home win | Joint home win | Ordered draws |
|---|---:|---:|---:|---:|
| Syracuse–Pittsburgh 401858225 | 20.5091 / 32.0708 | 0.747756 | 0.7692 | 10,000 exact |
| Coastal Carolina–Delaware 401869940 | 22.7750 / 32.9494 | 0.724035 | 0.7315 | 10,000 exact |

Original index digests remain `72a91840c7f0a88a7248d3a36c9723e4011dd75969859e05d65b7be971ae298f` and `223bbc35becc894560cc255dd7b786d2921c3201d63875c0af4a1af4e0b3ff76`. All 24 bound model/research objects are unchanged. A later authorized forecast for the same legitimate game would get a separate identity, without relabelling either research artifact.

Retained historical model-card results: Validation margin/total MAE 13.272/12.913; reused 2025 holdout 13.032/12.531. Historical source vintages are reconstructed, not certified prospective evidence. Early-season uncertainty, missing personnel/weather inputs, and the simplistic residual score law remain limitations. No new performance or profitability claim is made.

## Real input coverage

Inventory clock: **{inventory['createdAtUtc']}** ({utc(inventory['createdAtUtc']).astimezone(edt).isoformat()}). Latest retained CFBD schedule: **{bundle['scheduleCapturedAtUtc']}**; latest model-input capture: **{bundle['sourceCutoffUtc']}**. This is a September 14 capture, not current refreshed data.

Of 3,679 source schedule records, 2,919 are outside the original target scope; 399 in-scope starts are explicitly TBD. The remaining 361 comprise 100 source-declared finals, one elapsed nonfinal start, 57 currently due but stale games, and 203 not-yet-due games. Thus 760 are in the frozen FBS/FBS target scope; 660 were future at the original capture. The earlier aggregate FBS/FBS count should not be mistaken for the narrower published scope.

| Due slate date (New York) | Games blocked by stale capture |
|---|---:|
{table}

No additional retained alias/prior-feature blockers occur among those 57. There are 138 source school IDs and 320 effective-season alias records. This does **not** certify current availability: new final scores/statuses/boxes since September 14 have not been acquired. Missing newly completed-game statistics will block successor admission. No current result was acquired or examined for model selection.

First retained target is {first['away_team']} at {first['home_team']}, CFBD {first['game_id']}, kickoff {first['scheduled_at']} ({start.astimezone(edt).isoformat()}). T-6h is {(start-timedelta(hours=6)).isoformat()} ({(start-timedelta(hours=6)).astimezone(edt).isoformat()}); producer close is strictly before {(start-timedelta(minutes=30)).isoformat()} ({(start-timedelta(minutes=30)).astimezone(edt).isoformat()}). A legitimate first issue is possible only after fresh admission and authorized execution; an elapsed checkpoint cannot be backdated.

## Publisher and verification

Checkpoints T-7d/T-24h/T-6h/T-60m; proposed single owner every 15 minutes; close T-30m. Current AISP code exposes T-15m in House Divided but no official CFB decision pipeline. Consumer cadence and authority require Claude's separate implementation/approval. The producer does not pretend that interface is already active.

Versioned inputs, per-target unchanged-content reuse, per-game failure isolation, prepared/committed recovery, cumulative discovery with expiring eligibility and durable launcher/phase/runner receipts are implemented. 16 focused tests passed; the subsequent required-schema guard passed its affected admission test. Tests cover multi-game dispatch, chronological target exclusion, corrections, atomic pointers, alias ambiguity, cutoff/DST, orientation, 10,000-draw mass, actual consumer verifier/PMFs, tamper rejection, failure recovery and zero-network owner behavior. No unrelated suite ran.

Final 14-member deployment: `{stage['deploymentId']}`. Manifest physical SHA `{stage['deploymentManifest']['sha256']}`. Release SHA `{stage['release']['sha256']}`. Read-only Plan passed with zero CFB tasks. Final PowerShell 5.1 wrapper and Python exits were both 0, disposition `STALE_INPUT_REJECTED`, in {summary['verification']['launcherDurationSeconds']:.2f}s. This validates the real retained-input failure path, not a fresh full-slate production run. Full-slate numerical execution runtime remains unmeasured; per-game durable recovery supports continuation under the 12-minute task bound.

The draft deployment `46a72e998a729fa28a64eb43496d80d9ddfcec89125219f47fc913a913f95363` remains uninstalled audit evidence. Only the final identity above is proposed for activation. No owner was created; all three existing ASP owner definitions are byte-identical before/after.

## Remaining authorization and integration

`REFRESH_REQUIREMENTS.json` physical SHA `{stage['refreshRequirements']['sha256']}` proposes **one bounded CFBD capture: at most 7 requests, 25 MiB response bytes, zero retries, $0**, valid September 18 through September 21 00:00 UTC. Exact endpoints and fields are enumerated: account info before/after, 2026 schedule, FBS school master and regular-season team statistics for weeks 1–3. Stop on insufficient free entitlement, schema/rights failure or incomplete joins. Preserve the previous eight-request / 3,890,306-byte ledger; proposed upper cumulative totals are 15 requests and 30,104,706 bytes within the previous 25-request / 50-MiB bound. This task authorizes none of those calls. No secret was read.

The publisher consumes governed local capture versions; live HTTP capture is deliberately absent. Recurring season-long capture needs a separate bounded same-owner implementation/authorization. Installing the offline publisher alone cannot refresh stale data. Raw CFBD payloads remain private and are not redistributed. Attribution: Data provided by CollegeFootballData.com.

Approve exact deployment installation separately, then observe natural invocations; no manual competing owner. Consumer production acceptance, discovery, publication receipt handling and pins must be implemented/authorized by Claude. There is no CFB production environment pin contract in the inspected research importer to claim was activated.

See `ACTIVATION.md`, `PRODUCER_CONTRACT.md`, `READINESS.json` and `CLAUDE_HANDOFF.md`. Provider calls/bytes/cost, AISP writes, task changes and real forecast publications this assignment: **0 / 0 / $0 / 0 / 0 / 0**. Only synthetic tests and isolated stale-state discovery were written before the staged metadata handoff. No current-season model selection occurred. NBA, NFL and MLB work remains unchanged.
'''
    immutable(docs/'REPORT.md',report.encode())
    command=f'''$receipt = Get-Content '{root / 'final/release-receipt.json'}' -Raw | ConvertFrom-Json
$installer = Join-Path (Split-Path $receipt.deploymentManifest.path) 'scripts\\install_cfb_gen1_slate_publisher.ps1'
& $installer -Mode Plan -DeploymentId $receipt.deploymentId -ExpectedManifestSha256 $receipt.deploymentManifest.sha256 -ReleasePath $receipt.release.path -ReleaseSha256 $receipt.release.sha256 -InputPointer $receipt.inputPointer'''
    activation=f'''# CFB activation requirements — not executed

Final deployment `{stage['deploymentId']}`; manifest physical SHA `{stage['deploymentManifest']['sha256']}`; release physical SHA `{stage['release']['sha256']}`. Plan verifies all 14 immutable members, exact runtime binding and absence of a conflicting task.

```powershell
{command}
```

After explicit installation authorization, use the same supported command with `-Mode Install`, then `-Mode Verify`. It installs only **ASP CFB Forecast Publisher**, S4U/Limited/IgnoreNew, at 15-minute cadence. Do not install the draft deployment. Administrator execution may be necessary; this assignment made no elevation attempt. No task is currently installed. An existing different owner must stop installation; never force an overwrite.

Rollback uses the identical command with `-Mode Remove` for this exact owner/binding only. It preserves all input, forecast, discovery, release, evidence and launcher artifacts. There is no previous installed CFB deployment to restore. Other owners are outside this procedure.

Installation does not authorize acquisition or consumer activation. Authorize the exact `{stage['refreshRequirements']['sha256']}` requirement packet separately. Retain new raw objects privately; do not invoke old acquisition defaults that overwrite retained paths. Publish the new local capture pointer (`sourceManifest` with path/sha256/bytes) to `{Path(stage['inputPointer']).parent / 'capture-current.json'}`. Under its existing lock the owner validates and admits it before dispatch. Live capture transport is not bundled; use a separately reviewed bounded intake execution after approval. Recurring live capture requires a later explicit same-owner extension, not a second task.

Consumer action: Claude verifies and pins the exact release/model/feature identities through a separately approved CFB authority contract, connects cumulative discovery, and records the bound immutable publication receipt clock. Existing research import accepts package bytes but does not itself provide production activation. Do not invent environment pin names or copy NBA/NFL pins. No decisions or wagering authority are conveyed.

Offline deterministic checks:

```powershell
Set-Location '{Path(__file__).resolve().parents[1]}'
& 'C:\\Users\\james\\asp-model-studio\\.venv\\Scripts\\python.exe' scripts/verify_cfb_gen1_slate_stage.py --receipt '{root / 'final/release-receipt.json'}'
& 'C:\\Users\\james\\asp-model-studio\\.venv\\Scripts\\python.exe' -m pytest tests/test_cfb_slate_publisher.py -q -p no:cacheprovider
```

Independent baseline reproduction (reuses completed evidence if this output already exists; use a new private output directory only for a deliberate numerical rerun):

```powershell
& 'C:\\Users\\james\\asp-model-studio\\.venv\\Scripts\\python.exe' scripts/prepare_cfb_gen1_publisher.py --output '{root}'
```

The forecast runner has no clock-override CLI and must not be used to manufacture earlier prospective issues. Synthetic test clocks remain separate. Observe the natural task after approved installation, preserving truthful NOT_DUE, STALE_INPUT_REJECTED and REUSED_IMMUTABLE dispositions.
'''
    immutable(docs/'ACTIVATION.md',activation.encode())
    handoff=f'''# Claude handoff: staged CFB Gen1 multi-game publisher

**Staged producer readiness; no consumer activation requested or implied.** No new real forecast is ready to import from this task. The 57 due retained games are blocked by stale September 14 evidence. Fresh source capture and producer installation need separate authorization. You need not wait for final outcomes to integrate this producer contract.

Baseline `{release['configurationIdentity']}` remains unchanged. Point scores: frozen Ridge alpha100. `ridgeHomeWinProbability`: frozen Development logistic mapping of Ridge margin. Elo is a separate diagnostic. Joint 10,000-draw probabilities, score/total/margin PMFs and intervals are a separate channel; do not label the calibrated probability as a simulation count, or force agreement. All probabilities are fractions; ties are zero under the existing tied-pair rejection law. Missing injuries/personnel/weather and early-season limitations remain visible; no profitability claim.

Release: `{stage['release']['path']}`; physical SHA `{stage['release']['sha256']}`. Final deployment `{stage['deploymentId']}`; manifest `{stage['deploymentManifest']['sha256']}`. Effective creation boundary `{release['prospectiveEffectiveAtUtc']}` concerns new prospective artifacts only, not retrospective production relabelling or active consumer authority.

Your existing `research_import.py` pure verifier and PMF reader passed a synthetic package from the new renderer. Schemas remain `CFB_GEN1_PRIVATE_RESEARCH_PACKAGE_INDEX_V1` and `CFB_GEN1_PROSPECTIVE_RESEARCH_FORECAST_V1`; research-only true, AISP/wagering authority false. The publisher produces all eligible games under a separate release; existing Syracuse-Pittsburgh and Coastal-Delaware research packages remain unchanged.

When activated, discover `{Path(r'C:\Users\james\asp-model-exchange\cfb-gen1-production-v1\slate-discovery\current.json')}`. It is not created by this task. Verify the versioned manifest reference, package-index physical digest/address and all members, then exact CFBD game/school IDs and home/away orientation. Never match by school name alone. Only currentlyEligible entries with unexpired leases are current; every predecessor remains available. Revisions must retain original IDs/clocks and decision bindings. Schedule changes/newly stale or absent inputs can make older packages historical even though their bytes are preserved.

Publication time is the discovery-bound immutable `publicationReceipt.committedAtUtc`, distinct from forecast creation; it is not the null prepared-index timestamp. Your existing importer reads a package-local receipt, so cumulative discovery and this clock mapping need a small explicit consumer integration before claiming automatic current ingestion. No production pin/interface is activated by this handoff. CFB's inspected House Divided T-15 cutoff is qualified by absence of an official CFB decision pipeline; producer T-30 close leaves 15 minutes but does not establish a consumer cadence guarantee.

Needed decisions: approve exact bounded source-refresh packet `{stage['refreshRequirements']['sha256']}` (7 requests / 25 MiB / zero retries / $0); approve exact single-owner installation; then separately implement/authorize consumer production acceptance. First retained open opportunity is {first['away_team']}–{first['home_team']} {first['game_id']} on {first['scheduled_at']}, with publication strictly before {(start-timedelta(minutes=30)).isoformat()}. No guarantee of timely input availability is made.

Detailed source identities, 24 preservation hashes, current coverage, test evidence, required activation commands and rollback are in the accompanying metadata. Raw data/models remain outside this package under their original permissions. No AISP, sportsbook, task or bankroll changes occurred. Consumer acknowledgement: not received.
'''
    immutable(docs/'CLAUDE_HANDOFF.md',handoff.encode())
    members=[docs/n for n in ('READINESS.json','REPORT.md','ACTIVATION.md','CLAUDE_HANDOFF.md','PRODUCER_CONTRACT.md','REFRESH_REQUIREMENTS.json')]
    index={'schema':'CFB_GEN1_STAGED_PRODUCER_HANDOFF_INDEX_V1','createdAtUtc':now(),'deploymentId':stage['deploymentId'],
        'release':stage['release'],'forecastPackagesIncluded':0,'consumerActivated':False,
        'members':[dict(relativePath=x.name,sha256=reference(x)['sha256'],bytes=x.stat().st_size) for x in members]}
    raw=canonical_bytes(index);address=digest(raw);destination=Path(a.handoff_root)/'sha256'/address
    for file in members:immutable(destination/file.name,file.read_bytes())
    index_ref=immutable(destination/'index.json',raw)
    for m in index['members']:verified_bytes(dict(m,path=str(destination/m['relativePath'])))
    closeout={'schema':'CFB_GEN1_STAGED_CLOSEOUT_V1','createdAtUtc':now(),'handoffIndex':index_ref,
        'deploymentId':stage['deploymentId'],'deploymentManifest':stage['deploymentManifest'],'release':stage['release'],
        'readiness':reference(docs/'READINESS.json'),'providerCalls':0,'providerBytes':0,'costUsd':0,'aispWrites':0,
        'taskChanges':0,'consumerAcknowledged':False,'liveForecastOrDiscoveryWrites':0,'metadataHandoffFilesWritten':len(members)+1}
    immutable(docs/'CLOSEOUT.json',canonical_bytes(closeout));print(json.dumps(closeout,indent=2))


if __name__=='__main__':main()
