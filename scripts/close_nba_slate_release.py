"""Publish metadata-only successor handoff after focused local verification."""
from collections import Counter
import json
from pathlib import Path
import os
import sys
import uuid
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sports_nba_gen1.authority import reference, verified_bytes
from server.sports_nba_gen1.production import canonical_bytes, digest
from server.sports_nba_gen1.slate_lifecycle import immutable, now, read_ref
from server.sports_nba_gen1.slate_inputs import validate_bundle
from capture_nba_slate_refresh import PLAN

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(r'C:\Users\james\asp-model-studio\outputs\nba-gen1-slate-publisher-v1')
DOCS = ROOT/'docs/nba-gen1-slate-publisher-v1'
EXCHANGE = Path(r'C:\Users\james\asp-model-exchange\nba-gen1-production-v1\slate-handoffs\sha256')


def main():
    staging = json.loads((OUT/'release-final/release-receipt.json').read_bytes())
    release = read_ref(staging['release'])
    manifest = read_ref(staging['deploymentManifest'])
    for m in manifest['members']:
        verified_bytes(dict(m, path=str(Path(staging['deploymentManifest']['path']).parent/m['relativePath'])))
    bundle_ref = read_ref(reference(staging['inputPointer']))['inputManifest']
    bundle = read_ref(bundle_ref)
    validate_bundle(bundle, release)
    before = json.loads((OUT/'owners-before.json').read_bytes())
    after = json.loads((OUT/'owners-after.json').read_bytes())
    assert before['owners'] == after['owners'] and after['nbaOwnerCount'] == 0
    assert not (Path(r'C:\Users\james\asp-model-studio\.runtime\nba-gen1-slate-publisher\deployment.json')).exists()
    prior = json.loads(Path(r'C:\Users\james\asp-model-studio\outputs\nba-gen1-producer-activation-v1\independent-audit-after.json').read_bytes())
    preserved = [prior['deployment'], prior['package'], prior['handoff']]
    for field in ['deploymentMembers','packageMembers','preservedResearchArtifacts','handoffMembers','fittedAndResidualBindings']:
        preserved.extend(prior[field])
    for ref in preserved:
        verified_bytes(ref)
    launcher_paths = sorted((OUT/'final-local-verification/launcher-receipts').glob('*.json'))
    launchers = [(p,json.loads(p.read_bytes())) for p in launcher_paths]
    launchers = [(p,v) for p,v in launchers if v.get('schema') == 'NBA_GEN1_SLATE_LAUNCHER_RECEIPT_V1']
    assert len(launchers) == 2
    runs = []
    for path, item in launchers:
        assert item['pythonExitCode'] == item['wrapperExitCode'] == 0 and item['disposition'] == 'NOT_DUE'
        run = read_ref(item['runner']['receipt'])
        assert len(run['games']) == len(bundle['games'])
        runs.append({'launcher': reference(path), 'runner': item['runner']['receipt'], 'disposition': item['disposition'],
                     'pythonExitCode': item['pythonExitCode'], 'wrapperExitCode': item['wrapperExitCode']})
    failure_paths = list((OUT/'final-local-verification/failure-fixture-launcher-receipts').glob('*.json'))
    failed = [(p,json.loads(p.read_bytes())) for p in failure_paths]
    failed = [(p,v) for p,v in failed if v.get('schema') == 'NBA_GEN1_SLATE_LAUNCHER_RECEIPT_V1']
    assert len(failed) == 1 and failed[0][1]['pythonExitCode'] == failed[0][1]['wrapperExitCode'] == 1
    junit = ROOT/'outputs/nba-gen1-slate-publisher-v1/focused-tests.xml'
    suite = ET.parse(junit).getroot().find('testsuite')
    assert suite.attrib['tests'] == '14' and suite.attrib['failures'] == suite.attrib['errors'] == '0'
    dispositions = dict(Counter(g['disposition'] for g in run['games']))
    exclusions = dict(Counter(g.get('reason') for g in run['games'] if g['disposition'] == 'EXCLUDED'))
    next_checkpoint = min(g['nextCheckpointUtc'] for g in run['games'] if 'nextCheckpointUtc' in g)
    full = {'schema': 'NBA_GEN1_SLATE_COVERAGE_V1', 'asOfUtc': run['completedAtUtc'],
        'inputVersion': bundle_ref, 'scheduleCaptureUtc': bundle['scheduleCapturedAtUtc'],
        'sourceRows': len(bundle['games']), 'dispositions': dispositions, 'exclusions': exclusions,
        'unmappedGameIds': [g['gameId'] for g in bundle['games'] if g.get('exclusion') == 'UNMAPPED_TEAM'],
        'teamSupportCounts': bundle['teamSupportCounts'], 'nextCheckpointUtc': next_checkpoint,
        'currentlyEligibleGames': sum(g['currentlyEligible'] for g in run['games']),
        'newRealForecasts': 0, 'completeGameInventoryReceipt': runs[-1]['runner'],
        'currentInputRefreshRequired': True, 'fullSlateLiveReady': False,
        'qualification': 'Retained 2026-09-14 identity snapshot, not a claim of latest schedule status. All supported targets outside T-7d; inputs already fail freshness for a due publication.'}
    verification = {'schema': 'NBA_GEN1_SLATE_RELEASE_VERIFICATION_V1', 'createdAtUtc': now(),
        'implementationReadiness': 'IMPLEMENTED_VERIFIED_STAGED', 'installed': False, 'consumerActivated': False,
        'deployment': staging, 'verifiedMembers': len(manifest['members']), 'testsPassed': 14,
        'junit': reference(junit), 'plan': reference(OUT/'installer-plan-final.json'),
        'localWrapperRuns': runs, 'deliberateFailureFixture': reference(failed[0][0]),
        'naturalInvocations': 0, 'ownerCount': 0, 'otherOwnerDefinitionsUnchanged': True,
        'ownerBefore': reference(OUT/'owners-before.json'), 'ownerAfter': reference(OUT/'owners-after.json'),
        'preservedPhysicalObjectsVerified': len(preserved), 'preservedObjects': preserved,
        'coverage': full, 'providerRequests': 0, 'providerBytes': 0, 'costUsd': 0,
        'aispWrites': 0, 'modelFits': 0, 'realForecastOrSimulationRuns': 0,
        'syntheticVerification': 'Lifecycle fixture packages and one synthetic 10,000-draw renderer check; isolated from exchange',
        'supersededLocalStagingCandidate': '70441cb653b249c2fc8e76a9e8af6b34c0edbbadf16b49ac8d65b0a03d606792',
        'candidateNote': 'Preserved local verification candidate before receipt-volume fix; never installed or advertised for activation'}
    for name, value in [('VERIFICATION.json',verification),('COVERAGE.json',full),('REFRESH_PLAN.json',PLAN),('RELEASE_RECEIPT.json',staging)]:
        immutable(DOCS/name,canonical_bytes(value))
    dep = staging['deploymentId']
    installer = Path(staging['deploymentManifest']['path']).parent/'scripts/install_nba_gen1_slate_publisher.ps1'
    args = f"-DeploymentId '{dep}' -ExpectedManifestSha256 '{staging['deploymentManifest']['sha256']}' -ReleasePath '{staging['release']['path']}' -ReleaseSha256 '{staging['release']['sha256']}' -InputPointer '{staging['inputPointer']}'"
    commands = '\n\n'.join(f"```powershell\n& '{installer}' -Mode {mode} {args}\n```" for mode in ('Plan','Install','Verify','Remove'))
    activation = f'''# Supported activation and rollback

STAGED ONLY. No installation, elevation retry or task mutation was performed.
Only deployment `{dep}` is the proposed successor. Do not install 7e04b1 or the
intermediate local verification candidate. Plan is read-only. Install requires
separate James authorization for this exact successor and Administrator execution
as James; it creates at most one S4U/Limited/IgnoreNew owner at 15 minutes and
refuses a different existing owner. Verify is read-only. Remove is the supported
rollback of this exact task and runtime binding only, retaining every artifact.
The command sequence below is documentation, not activation authorization.

{commands}

After separately authorized installation, observe natural invocations; never
substitute local verification for Task Scheduler/S4U success. Compare the task
action and runtime binding, launcher/runner receipts and owner count. Runtime:
`C:\\Users\\james\\asp-model-studio\\.runtime\\nba-gen1-slate-publisher`.
The installer unregisters its newly created task if its immediate verification
fails; it never overwrites another owner. No other sport owner is altered.

Input refresh is independently inactive. Inspect its no-network plan:

```powershell
& 'C:\\Users\\james\\asp-model-studio\\.venv\\Scripts\\python.exe' '{Path(staging['deploymentManifest']['path']).parent/'scripts/capture_nba_slate_refresh.py'}'
```

Later live capture requires `--execute --authorization <James-approved-receipt>
--authorization-sha256 <physical-sha> --private-root <private-store>`. The receipt
schema is `NBA_SLATE_REFRESH_AUTHORIZATION_V1`, with authorizedBy=James,
executeApproved=true, validFromUtc/validUntilUtc, the exact REFRESH_PLAN.json
object and rightsEvidence physical references. No such authorization is issued here.
The existing NBA forecast task does NOT call this network client. A future
authorized same-owner capture phase may call it, then admit its returned receipt:

```powershell
& 'C:\\Users\\james\\asp-model-studio\\.venv\\Scripts\\python.exe' '{Path(staging['deploymentManifest']['path']).parent/'scripts/admit_nba_gen1_slate_inputs.py'}' --capture '<CAPTURE_RECEIPT>' --base-model-receipt '{release['baseModelReceipt']['path']}' --base-coverage '{release['baseCoverage']['path']}' --rights 'C:\\Users\\james\\asp-model-studio\\outputs\\nba-gen1-long-gap-v1\\source-review\\admission.json' --rights 'C:\\Users\\james\\asp-model-studio\\outputs\\nba-gen1-long-gap-v1\\source-review\\hoopr-LICENSE.md' --registry-root 'C:\\Users\\james\\asp-model-studio\\outputs\\nba-gen1-slate-publisher-v1\\inputs' --season-end 2027 --reviewed-by '<responsible Model Studio owner>'
```

Do not copy the old capture and restamp it. Changes produce append-only input
versions and an atomic pointer; the executable, model and preprocessing remain fixed.
Current acquisition age and the checkpoint must pass before new forecasts or reuse.
'''
    immutable(DOCS/'ACTIVATION.md',activation.encode())
    report = f'''# NBA Gen1 slate publisher successor

**IMPLEMENTED_VERIFIED_STAGED — activation, fresh inputs and consumer adoption pending.**

The frozen Ridge/Elo/lattice numerical baseline is unchanged. This release adds
multi-game dispatch, eligibility-before-reuse, versioned input admission, atomic
discovery retaining revisions, recovery journals, and durable runner/PowerShell
receipts. BOS–DET may receive a newly identified prospective package when eligible;
its existing research forecast is preserved. Source commit: `{manifest['sourceCommit']}`.

Deployment: `{dep}`. Manifest physical SHA: `{staging['deploymentManifest']['sha256']}`.
Release physical SHA: `{staging['release']['sha256']}`. All {len(manifest['members'])} members verified.

| Readiness dimension | Result |
|---|---|
| Publisher implementation | 14 focused tests passed; read-only installer Plan passed |
| Local PowerShell 5.1 wrapper | Two real-input runs: Python=0, wrapper=0, NOT_DUE; approximately 7 seconds each |
| Failure receipts | Deliberately missing fixture input produced Python=1, wrapper=1 and durable runner/launcher receipts |
| Real slate | {len(bundle['games'])} retained rows; {dispositions.get('NOT_DUE',0)} mapped supported future targets, all not due |
| Exclusions | {json.dumps(exclusions,sort_keys=True)} |
| New real forecasts/publications | 0; no freshness bypass, restamping or artificial demonstration |
| Fresh inputs | September 14 snapshot; not current enough for a due publication; 30 teams retain prior-season support |
| Next legitimate checkpoint | {next_checkpoint}, October 13 at 3:00 PM America/New_York, conditional on fresh admitted evidence |
| Acquisition | Staged no-network default; separate exact bounded authorization required |
| Administrator installation | Awaiting authorization/execution; zero NBA tasks |
| Consumer | Not activated; additive V2 publication-clock/discovery support required |

Coverage is identity/feature support, not proof every future row is already
forecast-ready. The entire retained inventory and per-game blockers are bound by
COVERAGE.json. Five unresolved placeholder games remain blocked. The source must
refresh schedule changes and final membership before opening night and after
completed games. Model Studio owns the documented capture/admission path.

The previous one-game discovery, all 26 superseded deployment members, PHI–NYK
and BOS–DET packages and fitted/residual bindings were physically reverified.
All three unrelated ASP task definitions are unchanged. There were zero provider
requests/bytes, $0 cost, AISP writes, model fits or real simulation runs.
Lifecycle cases and renderer mechanics used isolated synthetic fixtures.

No performance or promotion claim follows these software tests. The selected
model limitations and 50/100-game monitoring gates remain intact. See CONTRACT.md
for channels, deadlines, source limits, revision semantics and consumer safeguards.
'''
    immutable(DOCS/'REPORT.md',report.encode())
    handoff = f'''# Claude/AISP — NBA slate publisher successor

Producer implementation is staged, NOT installed. NBA consumer is NOT activated.
This handoff grants no decision, position, wagering or model-promotion authority.
Deployment `{dep}`; physical manifest SHA `{staging['deploymentManifest']['sha256']}`.
Release `{staging['release']['path']}` with SHA `{staging['release']['sha256']}`.
Prospective effective boundary: `{release['prospectiveEffectiveAtUtc']}`.

Validate index bytes and every bound member. Retain the selected underlying
model handoff `7113b71ff5819c89103ad19d5f9afb22c51dbc92980be12b56ce8826cb34ccaf`.
Do not replace or relabel its original PHI–NYK or the earlier BOS–DET research
forecasts. A future new BOS–DET package has its own forecast/revision identity.

The V2 package retains explicit Ridge point expectations, Elo winner probabilities,
and 10,000 paired joint score draws. Elo is the controlling winner channel; joint
winner probabilities are a separate summary, while totals/intervals use the full
joint population. Close-score correction is disabled. Probability units are 0–1.

Required additive import changes, pending your own implementation/verification:

1. Follow `nba-gen1-production-v1/slate-discovery/current.json` to its physically
   hashed immutable version. Preserve all packages/revisions. Do not scan unrelated
   research artifacts or treat preserved historical entries as current.
2. Support `NBA_GEN1_PRODUCTION_FORECAST_PACKAGE_INDEX_V2`. Package/forecast
   publishedAtUtc remains null in prepared bytes. Actual confirmed publication is
   the bound exchange publicationReceipt's committedAtUtc. Verify its hash and
   exact package, forecast and revision binding. Never substitute creation time.
3. Require current eligibility and an unexpired eligibilityValidUntilUtc (maximum
   one 15-minute tick), source/model bindings, pre-tipoff creation/publication, and
   your independently governed decision cutoff. A producer cutoff is not a wager
   deadline. Verify the forecast population and point/Elo/joint channel orientation.
4. Import idempotently by forecast ID plus physical package digest, retain old
   revisions, and keep research history before the effective boundary unchanged.
5. Obtain separate AISP activation authority and supply an actual consumer receipt.
   Do not assume that existing AISP pin handling implements these additive fields.

No real packages were issued this task: all {dispositions.get('NOT_DUE',0)} supported
retained games are outside T−7 days and the inputs need refresh. Earliest checkpoint
is {next_checkpoint}, subject to fresh evidence. The only discovered predecessor
PHI–NYK package is preserved as historical, not recertified as currently eligible.
There is no consumer acknowledgement. ACTIVATE.md is not required: use the exact
supported commands in ACTIVATION.md after authorization. No second scheduler.
'''
    immutable(DOCS/'CLAUDE_HANDOFF.md',handoff.encode())
    # Consumer-ready metadata only; no raw histories, weights or test packages.
    members = {name:(DOCS/name).read_bytes() for name in ('REPORT.md','CONTRACT.md','ACTIVATION.md','CLAUDE_HANDOFF.md',
        'VERIFICATION.json','COVERAGE.json','REFRESH_PLAN.json','RELEASE_RECEIPT.json')}
    members['release.json'] = verified_bytes(staging['release'])
    members['deployment-manifest.json'] = verified_bytes(staging['deploymentManifest'])
    index = {'schemaVersion':'NBA_GEN1_SLATE_SUCCESSOR_HANDOFF_INDEX_V1','createdAtUtc':now(),
        'deploymentId':dep,'producerInstalled':False,'consumerActivated':False,
        'members':[{'relativePath':name,'sha256':digest(raw),'bytes':len(raw)} for name,raw in sorted(members.items())]}
    data=canonical_bytes(index)
    address=digest(data)
    EXCHANGE.mkdir(parents=True,exist_ok=True)
    temporary=EXCHANGE/('.stage-'+uuid.uuid4().hex)
    for name,raw in members.items():
        immutable(temporary/name,raw)
    immutable(temporary/'index.json',data)
    for member in index['members']:
        verified_bytes(dict(member,path=str(temporary/member['relativePath'])))
    destination=EXCHANGE/address
    os.rename(temporary,destination)
    publication={'schema':'NBA_GEN1_SLATE_HANDOFF_PUBLICATION_V1','publishedAtUtc':now(),
        'index':reference(destination/'index.json'),'handoff':reference(destination/'CLAUDE_HANDOFF.md'),
        'forecastPublications':0,'discoveryPointerChanged':False,'consumerAcknowledged':False}
    immutable(DOCS/'PUBLICATION.json',canonical_bytes(publication))
    print(json.dumps(publication,indent=2))


if __name__=='__main__':
    main()
