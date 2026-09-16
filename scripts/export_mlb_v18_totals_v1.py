"""Reuse complete original V18 total PMFs in a checksummed derivative handoff.

No forecast is regenerated or newly claimed prospective. Existing forecast
bytes are copied exactly; export creation/delivery clocks are separate.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from scripts.package_mlb_v18_transition_adapter_v2 import canonical, reference, verify_ref, immutable, aware
from server.sports_current_statcast import mlb_v18_daily_slate as daily
from server.sports_current_statcast.mlb_v18_exchange import _child
from server.sports_current_statcast.mlb_v18_unattended import single_owner
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask
from server.sports_current_statcast.mlb_v18_totals_probabilities import validated_pmf, line_probabilities, focused_checks, UNITS

OUT = ROOT/'outputs/mlb-v18-totals-distribution-v1'
SOURCE = ROOT/'outputs/mlb-v18-current-state-pipeline-v1'
EXCHANGE = ROOT.parent/'asp-model-exchange/mlb-v18-current/totals-v1'
HELPER = ROOT/'server/sports_current_statcast/mlb_v18_totals_probabilities.py'
CORE = ROOT/'server/sports_current_statcast/mlb_v18_whole_game_challenger.py'

CONTRACT = '''# Original V18 totals distribution contract V1

The existing `MLB_V18_DAILY_GAME_FORECAST_V1` field
`distributions.totalRuns` is already the complete empirical mass function.
This export copies those original forecast bytes unchanged and indexes the
existing field; it does not replace the forecast, simulate, or create a new PMF.
The file's other numerical fields and original clocks remain unchanged.

Each row is `{value: integer total runs, probability: fraction from 0 to 1}`.
Absent integer bins have zero probability. All retained integer tail bins count;
never collapse them into an open-ended `>20` bin or infer probabilities from a
middle-80% range, a rounded mean, or independently combined team marginals.
The exact original paired population has `total[i]=awayRuns[i]+homeRuns[i]`.
Every valid original draw is used, with denominator `originalSimulationCount`.
No inning counter or score-limit mask is required. The original CIN-MIL 823734
baseline is 5,000 draws; its separate 4,722-draw score-limited study is unrelated.

For integer and half-run line L:
Over pWin=P(T>L), pPush=P(T=L), pLoss=P(T<L).
Under pWin=P(T<L), pPush=P(T=L), pLoss=P(T>L).
Each triplet sums to one. Half-run pushes are zero because totals are integers.
All probability fields in this contract use FRACTION_0_TO_1, never percent.
Display percentages multiply a fraction by 100 exactly once.

With supplied decimal odds D, expected net return per unit stake is
`pWin*(D-1)-pLoss`; a push refunds the stake. When pWin>0, fair decimal odds
are `1+pLoss/pWin`; otherwise the exported helper returns null with a reason.
Conditional non-push probability pWin/(pWin+pLoss), if used for a no-vig
comparison, is a separate quantity and must not replace raw pWin in EV.
Claude owns market lines, quotes, compatibility, pricing and selections.
Example lines 8 and 8.5 are illustrative, not recorded sportsbook quotes.

Settlement is full-game scoring INCLUDING simulated extra innings, natural
walk-offs, and an automatic runner on second beyond scheduled regulation.
The original simulator's zero-nontermination requirement is enforced.
Match only compatible full-game market rules. This final-total PMF cannot
provide regulation-only/F5 totals or independently establish a parlay's joint
probability. No parlay or selection engine is added here.

Bind by both canonical game ID and MLBAM gamePk, exact baseline forecast ID
`mlb-v18-daily-{FULL_OBJECT_SHA}`, engine MLB_V18_WHOLE_GAME, simulator
V18_WHOLE_GAME_MONTE_CARLO, original population schema and version, N/seed,
source cutoff and immutable source checksums. Never bind by teams/date alone.
Both versions of a game remain distinct; latest-at-inventory is a discovery
hint, not authorization to overwrite an already bound forecast or selection.

The existing AISP daily importer maps this field unchanged to
ShadowForecast.distributions.totalRunDistribution. Its Theater reader exposes
population.total_run_distribution; that PMF remains fractions even though
Theater's winner display uses percentages. Reuse the exact already imported
baseline when present. If absent, import its ordinary baseline through the
existing authorized daily adapter before attaching totals. This derivative
index is NOT itself an ordinary daily-forecast importer input.

For Over/Under, Overs Only and Parlay Watch, add only the narrow V18 mapping
from totalRunDistribution to the existing total-market pricing functions.
The generic board's distributions.full_game/first_five schema and old coarse
tail reader are different contracts; do not manufacture those payloads.
All original authority settings remain unchanged; this package grants none.

Index exportCreatedAtUtc and publication receipt publishedAtUtc are actual
new derivative clocks. originalCapturedAt/originalForecastCreatedAt and any
bound prior slate receipt keep their original meanings. A later slate receipt
is not represented as the first publication clock. A historical derivative
does not establish pregame availability or repair a missed deadline.

Verify package manifest file SHA-256/byte counts on delivered bytes without
newline normalization. Then verify the forecast file bound by each index row,
PMF mass and N, and exact baseline identity. The producer verification also
compares every bin against all paired totals and their full-precision mean.
Rounding for UI display must happen only after this calculation.
Return a consumer acknowledgement with index SHA, exact accepted forecast IDs,
actual import/attachment time, distinct games and precise rejected dependencies.
Publication alone is not import or end-to-end UI confirmation.
'''

def now():
    return datetime.now(timezone.utc).isoformat()

def read_ref(item):
    return json.loads(verify_ref(item).read_bytes())

def save_object(name, value):
    raw = canonical(value)
    return immutable(OUT/'objects/sha256'/hashlib.sha256(raw).hexdigest()/name, raw)

def build():
    current_path = OUT/'package.json'
    if current_path.exists():
        saved = read_ref(json.loads(current_path.read_bytes()))
        for item in saved['files']:
            verify_ref(item)
        return reference(Path(json.loads(current_path.read_bytes())['path']))
    inventory_ref = json.loads((OUT/'inventory/current.json').read_bytes())
    inventory = read_ref(inventory_ref)
    started = now()
    source_hashes = []
    copies, rows, checks, unsupported = {}, [], [], []
    # Identity guards precede numerical payload reads; no outcomes are used.
    for item in inventory['ordinaryForecasts']:
        pk, game = str(item['sourceGameId']), item['gameId']
        if (not all(final_oot_eligible_key_mask([game,pk]))
                or '2026-08-14' <= item['gameDate'] <= '2026-08-27'):
            unsupported.append({'gameId':game,'gamePk':pk,'reason':'GOVERNANCE_IDENTITY_EXCLUSION'})
            continue
        try:
            directory = daily._verify_existing_object(SOURCE, {'relativePath':'objects/sha256/'+item['objectSha256'],
                                                               'objectSha256':item['objectSha256']})
            for field in ('forecast','manifest','executionInputs','pregameEvidence'):
                verify_ref(item[field]); source_hashes.append(item[field])
            f, execution = read_ref(item['forecast']), read_ref(item['executionInputs'])
            snapshot = read_ref(item['pregameEvidence'])
            if (f['gameId'] != game or str(f['sourceGameId']) != pk
                    or f['parentAuthority']['bundleSha256'] != daily.PARENT_BUNDLE_SHA256
                    or f['parentAuthority']['paModelSha256'] != daily.PA_MODEL_SHA256
                    or f['parentAuthority']['transitionModelSha256'] != daily.TRANSITION_MODEL_SHA256
                    or f['executionInputDigest'] != daily.sha_json(daily.json_safe(execution))
                    or f['sourceCutoff'] != execution['sourceCutoff']):
                raise ValueError('EXACT_ORIGINAL_BASELINE_BINDING_MISMATCH')
            original = execution['population']
            n = f['simulation']['count']
            if n != 5000 or original['simulationCount'] != n:
                raise ValueError('ORIGINAL_V18_5000_DRAW_POPULATION_REQUIRED')
            if original['nonterminationCount'] or original['illegalStateCount']:
                raise ValueError('ORIGINAL_POPULATION_HAS_INVALID_OR_INCOMPLETE_DRAWS')
            away, home = np.asarray(original['awayRuns']), np.asarray(original['homeRuns'])
            for values in (away,home):
                if values.shape != (n,) or not np.isfinite(values).all() or (values<0).any() or not np.equal(values,np.floor(values)).all():
                    raise ValueError('INVALID_ORIGINAL_PAIRED_SCORE_ARRAY')
            # Never zip, sort, combine marginals, or select a research subset.
            totals = away.astype(np.int64) + home.astype(np.int64)
            counts = Counter(map(int,totals))
            pmf = f['distributions']['totalRuns']
            bins = validated_pmf(pmf,n)
            if {v:c for v,c,p in bins if c} != dict(counts):
                raise ValueError('EXISTING_PMF_DIFFERS_FROM_COMPLETE_PAIRED_POPULATION')
            paired_mean = int(totals.sum())/n
            pmf_mean = sum(v*c for v,c,p in bins)/n
            if paired_mean != pmf_mean or abs(paired_mean-f['expectations']['totalRuns']) > 1e-12:
                raise ValueError('ORIGINAL_PMF_EXPECTATION_MISMATCH')
            if abs(float(home.mean())-f['expectations']['homeRuns'])>1e-12 or abs(float(away.mean())-f['expectations']['awayRuns'])>1e-12:
                raise ValueError('ORIGINAL_TEAM_EXPECTATION_MISMATCH')
            probes = []
            for line in (8,8.5):
                query = line_probabilities(pmf,n,line)
                assert query['over']['winCount'] == int((totals>line).sum())
                assert query['over']['pushCount'] == int((totals==line).sum())
                assert query['over']['lossCount'] == int((totals<line).sum())
                probes.append(query)
            relative = 'forecasts/'+item['objectSha256']+'/forecast.json'
            copies[relative] = verify_ref(item['forecast']).read_bytes()
            population_hash = hashlib.sha256(canonical({'awayRuns':original['awayRuns'],'homeRuns':original['homeRuns']})).hexdigest()
            regulation = int(snapshot['game'].get('scheduled_innings') or 9)
            row = {'canonicalGameId':game,'mlbamGamePk':int(pk),'gameDate':item['gameDate'],
                'awayTeam':item['away'],'homeTeam':item['home'],'baselineForecastId':item['baselineForecastId'],
                'baselineObjectSha256':item['objectSha256'],'engineId':'MLB_V18_WHOLE_GAME',
                'engineVersion':f['parentAuthority']['bundleId'],'engineArtifactSha256':f['parentAuthority']['bundleSha256'],
                'simulatorId':'V18_WHOLE_GAME_MONTE_CARLO','forecastSchemaVersion':f['schemaVersion'],
                'populationSchemaVersion':original['schemaVersion'],'originalSimulationCount':n,'validOriginalDrawsUsed':n,
                'excludedDrawCount':0,'scoreLimited':False,'seed':f['simulation']['seed'],
                'sourceCutoff':f['sourceCutoff'],'originalCapturedAt':f['capturedAt'],
                'originalForecastCreatedAt':f['forecastCreatedAt'],'scheduledStart':f['scheduledStart'],
                'originalPublicationEvidence':item.get('currentPublishedSlateReceipt'),
                'originalPublicationEvidenceMeaning':'Bound retained slate receipt; not a newly inferred first-publication time',
                'latestAvailableVersionForGameAtInventory':item['latestAvailableVersionForGame'],
                'versionCountForGameAtInventory':item['versionCountForGame'],
                'sourceForecast':item['forecast'],'sourceManifest':item['manifest'],
                'originalPopulation':{'executionInputs':item['executionInputs'],'awayJsonPointer':'/population/awayRuns',
                    'homeJsonPointer':'/population/homeRuns','orderedPairedArraysSha256':population_hash,
                    'digestEncoding':'SHA256 of sorted-key compact JSON object {awayRuns: original array, homeRuns: original array}'},
                'distribution':{'relativePath':relative,'sha256':item['forecast']['sha256'],'bytes':item['forecast']['bytes'],
                    'jsonPointer':'/distributions/totalRuns','probabilityUnits':UNITS,'totalRunValues':'INTEGER_RUNS',
                    'denominator':n,'completeOriginalPopulation':True,'tailTruncated':False},
                'expectations':f['expectations'],'extraInningsIncluded':True,'scheduledRegulationInnings':regulation,
                'extraInningDrawCount':int((np.asarray(original['innings'])>regulation).sum()),
                'exportCreatedAtUtc':started,'originalAuthority':{k:f.get(k) for k in daily.RESEARCH_FLAGS},
                'newForecastGenerated':False,'newAuthorityGranted':False}
            rows.append(row)
            checks.append({'baselineForecastId':item['baselineForecastId'],'canonicalGameId':game,'mlbamGamePk':int(pk),
                'pairedDrawCount':n,'pmfCount':sum(c for v,c,p in bins),'probabilityMass':sum(c for v,c,p in bins)/n,
                'populationMean':paired_mean,'pmfMean':pmf_mean,'originalExpectedTotal':f['expectations']['totalRuns'],
                'meanDifference':paired_mean-f['expectations']['totalRuns'],'minimumTotal':int(totals.min()),'maximumTotal':int(totals.max()),
                'allOriginalDrawsUsed':True,'lineChecks':probes,'exactOriginalPmf':True})
        except (ValueError,KeyError,OSError,AssertionError) as exc:
            unsupported.append({'canonicalGameId':game,'mlbamGamePk':pk,'baselineForecastId':item['baselineForecastId'],
                                'reason':type(exc).__name__+': '+str(exc)})
    if not rows:
        raise ValueError('No supported original baseline PMF; '+str(unsupported[:2]))
    # Validate unchanged original files once after the complete derivative calculation.
    for descriptor in source_hashes:
        verify_ref(descriptor)
    synthetic = {**focused_checks(),'createdAtUtc':now(),'componentSource':reference(HELPER)}
    synthetic_ref = save_object('line-probabilities.json', synthetic)
    immutable(OUT/'verification/line-probabilities.json',canonical(synthetic_ref))
    verification = {'schemaVersion':'MLB_V18_TOTALS_POPULATION_VERIFICATION_V1','createdAtUtc':now(),
        'inventory':inventory_ref,'games':checks,'sourceFilesUnchanged':len(source_hashes),
        'allSupportedChecksPassed':True,'syntheticChecks':synthetic_ref,'newRandomDraws':0,'newSimulations':0,
        'fittedComponentsChanged':False,'inningCountersRequired':False,'scoreLimitedInputsUsed':False,
        'unroundedPmfMeanDifferenceMaximum':max(abs(x['meanDifference']) for x in checks)}
    verification_ref = save_object('verification.json', verification)
    missing = [{'slateDate':s['slateDate'],'receipt':s['receipt'],'dispositions':s['missingForecastDispositions']}
               for s in inventory['latestSlates'] if s.get('missingForecastDispositions')]
    index = {'schemaVersion':'MLB_V18_TOTALS_DISTRIBUTION_INDEX_V1','artifactType':'DERIVATIVE_OF_EXISTING_FROZEN_BASELINE',
        'exportCreatedAtUtc':started,'exportCompletedAtUtc':now(),'publicationTimeLocation':'publication-receipt.json.publishedAtUtc',
        'probabilityUnits':UNITS,'sourceInventory':inventory_ref,'sourceInventoryAtUtc':inventory['completedAtUtc'],
        'forecasts':rows,'forecastVersionCount':len(rows),'distinctGameCount':len({r['canonicalGameId'] for r in rows}),
        'coverageByDate':dict(Counter(r['gameDate'] for r in rows if r['latestAvailableVersionForGameAtInventory'])),
        'missingForecasts':missing,'unsupportedObjects':unsupported,
        'legacyNotCurrentSourcePipeline':inventory['legacyDailyForecasts'],
        'semantics':{'total':'original awayRuns[i] + original homeRuns[i]','fullScoringTail':True,'extraInningsIncluded':True,
            'noScoreLimit':True,'noInningCounterDependency':True,'existingCompletePmfReused':True},
        'contractFile':'CONTRACT.md','lineQueryHelper':'mlb_v18_totals_probabilities.py',
        'verification':verification_ref,'consumerAcknowledgement':None,'newAuthorityGranted':False,
        'newForecastGenerated':False,'providerRequests':0,'outcomeDataUsed':False,
        'code':reference(__file__),'simulatorSource':reference(CORE)}
    index_bytes = canonical(index)
    index_sha = hashlib.sha256(index_bytes).hexdigest()
    package = OUT/'packages/sha256'/index_sha
    files = {**copies,'index.json':index_bytes,'CONTRACT.md':CONTRACT.encode(),
        'mlb_v18_totals_probabilities.py':HELPER.read_bytes(),'verification.json':verify_ref(verification_ref).read_bytes()}
    for relative, data in files.items():
        immutable(_child(package,relative),data)
    manifest = {'schemaVersion':'MLB_V18_TOTALS_PACKAGE_MANIFEST_V1','indexSha256':index_sha,
        'createdAtUtc':now(),'files':[{'relativePath':k,'sha256':hashlib.sha256(v).hexdigest(),'bytes':len(v)} for k,v in sorted(files.items())]}
    immutable(package/'manifest.json',canonical(manifest))
    receipt = {'schemaVersion':'MLB_V18_TOTALS_EXPORT_BUILD_V1','createdAtUtc':now(),'packageRoot':str(package),
        'index':reference(package/'index.json'),'manifest':reference(package/'manifest.json'),
        'supportedForecastVersions':len(rows),'supportedDistinctGames':len({r['canonicalGameId'] for r in rows}),
        'files':[reference(p) for p in sorted(package.rglob('*')) if p.is_file()],
        'verification':verification_ref,'unsupportedObjects':unsupported,'published':False,'consumerAcknowledged':False}
    receipt_ref = save_object('build-receipt.json',receipt)
    immutable(current_path,canonical(receipt_ref))
    return receipt_ref

def publish(build_ref):
    receipt = read_ref(build_ref)
    original_root = Path(receipt['packageRoot'])
    index = read_ref(receipt['index'])
    destination = EXCHANGE/'sha256'/receipt['index']['sha256']
    local_publication = OUT/'publication.json'
    if local_publication.exists():
        old_ref = json.loads(local_publication.read_bytes())
        old = read_ref(old_ref)
        assert old['buildReceipt'] == build_ref
        for ref in old['deliveredFiles']:
            verify_ref(ref)
        return old_ref
    started = now()
    delivered = []
    with single_owner(EXCHANGE/'export.lock') as owned:
        if not owned:
            raise RuntimeError('Existing export lock is held; no ownership takeover')
        ordered = sorted(receipt['files'], key=lambda r: Path(r['path']).name == 'index.json')
        for descriptor in ordered:
            source = verify_ref(descriptor)
            target = _child(destination,source.relative_to(original_root).as_posix())
            immutable(target,source.read_bytes())
            copied = reference(target)
            assert (copied['sha256'],copied['bytes']) == (descriptor['sha256'],descriptor['bytes'])
            delivered.append(copied)
        clock = now()
        pub_index = reference(destination/'index.json')
        publication = {'schemaVersion':'MLB_V18_TOTALS_PUBLICATION_RECEIPT_V1','startedAtUtc':started,'publishedAtUtc':clock,
            'exportCreatedAtUtc':index['exportCreatedAtUtc'],'index':pub_index,'buildReceipt':build_ref,
            'status':'PUBLISHED_DERIVATIVE_NOT_A_NEW_FORECAST','exportedForecastVersions':index['forecastVersionCount'],
            'exportedDistinctGames':index['distinctGameCount'],'deliveredFiles':delivered,
            'perForecastExportTiming':[{'baselineForecastId':r['baselineForecastId'],
                 'availableBeforeScheduledStart':aware(clock)<aware(r['scheduledStart'])} for r in index['forecasts']],
            'originalClocksChanged':False,'consumerAcknowledged':False,'newAuthorityGranted':False}
        publication_bytes = canonical(publication)
        immutable(destination/'publication-receipt.json',publication_bytes)
        cin = next(r for r in index['forecasts'] if r['mlbamGamePk']==823734 and r['latestAvailableVersionForGameAtInventory'])
        forecast = read_ref(cin['sourceForecast'])
        examples = [line_probabilities(forecast['distributions']['totalRuns'],cin['originalSimulationCount'],l) for l in (8,8.5)]
        table = '\n'.join('| '+str(e['line'])+' | '+side+' | '+ ' | '.join(f"{e[side][p]:.6f}" for p in ('pWin','pPush','pLoss'))+' |' for e in examples for side in ('over','under'))
        day = max(index['coverageByDate'])
        note = f'''# CLAUDE_HANDOFF — original V18 totals V1

Package/index: `{pub_index['path']}`
Physical SHA-256: `{pub_index['sha256']}`; **{pub_index['bytes']:,} bytes**.
Sibling `manifest.json` binds every copied file by physical SHA-256 and bytes.
Actual derivative publication: **{clock}**. Original forecast clocks are unchanged.

Schema `MLB_V18_TOTALS_DISTRIBUTION_INDEX_V1`; all probabilities **FRACTION_0_TO_1**.
The existing complete `distributions.totalRuns` PMF is reused byte-for-byte,
including the full scoring tail and extra innings. Read `CONTRACT.md`.
Coverage: **{index['distinctGameCount']} distinct games / {index['forecastVersionCount']} exact forecast versions**;
latest slate {day}: **{index['coverageByDate'][day]} distinct supported games**.
Missing slate forecasts and historical/legacy dependencies are explicit in index.
All 5,000 original draws per supported version are used; no inning counters are required.

Use the exact `baselineForecastId`, object hash, canonical identity and gamePk.
Match an already imported ordinary MLB_V18_WHOLE_GAME baseline; never substitute
another version or a SCORE_LIMIT, SURVIVAL or TRANSITION candidate. Reuse
ShadowForecast.distributions.totalRunDistribution. If the baseline is missing,
the dependency is its ordinary daily import; this index does not manufacture it.
For the board, map only the V18 total PMF into existing total-market pricing;
do not fabricate full_game/first_five or coarse >20-tail payloads.

Example: **CIN–MIL {cin['mlbamGamePk']}**, canonical `{cin['canonicalGameId']}`,
forecast `{cin['baselineForecastId']}`, original **5,000** draws, mean **{cin['expectations']['totalRuns']:.4f}**.
Lines below are **illustrative**, not actual recorded sportsbook lines. Fractions:

| Line | Side | pWin | pPush | pLoss |
|---:|---|---:|---:|---:|
{table}

Over wins T>L, pushes T=L, loses T<L; Under reverses win/loss.
At supplied decimal odds D: expected net return per unit stake = pWin*(D-1)-pLoss.
Push-aware fair decimal odds = 1+pLoss/pWin when pWin>0; otherwise unavailable.
Do not substitute conditional non-push probabilities in expected net return.
Claude owns quotes, compatible settlement, pricing, filters and parlay decisions.
The modeled total includes extras and automatic second-base runners; not F5 or regulation-only.

Verify the manifest and exact baseline bindings, then use the existing PMF or the
included pure `line_probabilities(rows, sample_count, line, decimal_odds=None)` helper.
Return an acknowledgement naming the exact index SHA, accepted forecast IDs,
distinct games, actual attachment/import time and missing baselines.
Publication is complete; **no consumer acknowledgement or UI integration is claimed**.
'''
        immutable(destination/'CLAUDE_HANDOFF.md',note.encode())
        immutable(OUT/'CLAUDE_HANDOFF.md',note.encode())
        ref = save_object('publication-receipt.json',{**publication,
            'exchangePublicationReceipt':reference(destination/'publication-receipt.json'),
            'claudeHandoff':reference(destination/'CLAUDE_HANDOFF.md')})
        immutable(local_publication,canonical(ref))
    return ref

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--game-pk',type=int)
    parser.add_argument('--line',type=str)
    args=parser.parse_args()
    built=build()
    if args.game_pk is not None or args.line is not None:
        if args.game_pk is None or args.line is None:
            parser.error('--game-pk and --line must be supplied together')
        package=read_ref(built);index=read_ref(package['index'])
        row=next(r for r in index['forecasts'] if r['mlbamGamePk']==args.game_pk and r['latestAvailableVersionForGameAtInventory'])
        forecast=read_ref(row['sourceForecast'])
        print(json.dumps(line_probabilities(forecast['distributions']['totalRuns'],row['originalSimulationCount'],args.line)))
    else:
        print(json.dumps(publish(built) if args.publish else built))
