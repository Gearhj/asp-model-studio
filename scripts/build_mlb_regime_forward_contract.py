"""Package already-inspected current-evidence limitations and safe-cache flags.

No source acquisition, model execution, AISP access or raw-source reads occur.
The historical flags are descriptive PA exposure, never current readiness.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import pyarrow.parquet as pq
from server.sports_datasets.consumer import canonical_json_bytes


CACHE = ROOT / 'outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache'
REPRODUCTION_SHA = '0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9'
FLAGS = (
    'batting_recent_bullpen_workload_missing', 'fielding_recent_bullpen_workload_missing',
    'batting_pregame_temperature_missing', 'fielding_pregame_temperature_missing',
    'batting_current_start_missing', 'fielding_current_start_missing',
    'batting_previous_game_missing', 'fielding_previous_game_missing',
    'pitcher_last250_velocity_missing', 'pitcher_last250_whiff_missing',
    'batter_last100_whiff_missing', 'matchup_batter_hand_missing', 'matchup_pitcher_hand_missing',
    'batter_prior_missing', 'pitcher_prior_missing',
)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_flags(frame: pd.DataFrame) -> dict:
    records = []
    for name in FLAGS:
        values = pd.to_numeric(frame[name], errors='coerce')
        records.append({
            'feature': name, 'rows': len(frame), 'flagOneRows': int((values == 1).sum()),
            'flagZeroRows': int((values == 0).sum()), 'nullOrNonNumericRows': int(values.isna().sum()),
            'otherValueRows': int((values.notna() & ~values.isin([0, 1])).sum()),
            'flagOneFraction': float((values == 1).mean()),
            'gamesWithAtLeastOneFlaggedPa': int(frame.loc[values == 1, 'canonicalGameId'].nunique()),
        })
    return {'rows': len(frame), 'games': int(frame.canonicalGameId.nunique()),
            'firstDate': str(frame.game_date.min()), 'lastDate': str(frame.game_date.max()), 'features': records}


def build() -> dict:
    reproduction_path = CACHE / f'baseline-reproduction-{REPRODUCTION_SHA}.json'
    if file_sha(reproduction_path) != REPRODUCTION_SHA:
        raise ValueError('Baseline reproduction receipt differs')
    reproduction = json.loads(reproduction_path.read_bytes())
    frames, input_records = [], []
    for fold in range(1, 6):
        reference = reproduction['artifacts'][f'validationFold{fold}']
        path = Path(reference['path'])
        if not path.resolve().is_relative_to(CACHE.resolve()) or file_sha(path) != reference['sha256']:
            raise ValueError('Safe validation feature cache differs')
        frame = pq.read_table(path, columns=['canonicalGameId', 'game_date', 'foldNumber', *FLAGS]).to_pandas()
        if not frame.game_date.astype(str).between('2024-03-20', '2026-08-06').all():
            raise ValueError('Unexpected date in physically safe validation cache')
        frames.append(frame)
        input_records.append({'fold': fold, **reference})
    all_oof = pd.concat(frames, ignore_index=True)
    if len(all_oof) != 494432 or int((all_oof.foldNumber == 5).sum()) != 94157:
        raise ValueError('Physically safe common OOF population differs')
    payload = {
        'schemaVersion': 'MLB_REGIME_FORWARD_SOURCE_EVIDENCE_V1',
        'purpose': 'DESCRIPTIVE_SOURCE_LIMITATIONS_AND_FUTURE_PRECOMPUTED_RESEARCH_IMPORT_CONTRACT',
        'inspectionTime': '2026-09-10T09:04:08.2976997-04:00',
        'currentShadowReadiness': {
            'status': 'NO_FUTURE_PREGAME_TEMPLATE_BUNDLE_AVAILABLE_IN_INSPECTED_PUBLICATIONS',
            'latestPublishedSlate': '2026-09-08', 'publishedForecasts': 13, 'originalSkips': 2,
            'handoffSha256': '3bbada26170778ca0d26ace39dc86fffbccfb3a82924872fd6dc1a1adef6014a',
            'handoffGeneratedAt': '2026-09-08T19:28:32.828388+00:00',
            'earliestForecastTimestamp': '2026-09-08T11:13:32.962515-04:00',
            'latestForecastTimestamp': '2026-09-08T12:01:09.67818-04:00',
            'earliestFirstPitch': '2026-09-08T18:35:00-04:00',
            'latestFirstPitch': '2026-09-08T22:10:00-04:00',
            'savedRawTemplatesExist': True, 'savedTreatedTemplatesExistInParentBundle': True,
            'templatesApplyToFutureGames': False,
            'sourceEvidenceWindow': ['2026-04-01', '2026-08-13'],
            'bullpenTemplateWindow': ['2026-07-15', '2026-08-13'],
            'nextSlateIdentity': 'NOT_ESTABLISHED_BY_EXISTING_PUBLICATION_METADATA',
            'newForecastsProduced': 0, 'action': 'FORWARD_CONTRACT_ONLY_NO_RETROSPECTIVE_FORECAST_PUBLICATION',
            'scope': 'EXISTING_MODEL_STUDIO_PUBLICATION_METADATA_NOT_AISP_OR_PROVIDER_INVENTORY',
        },
        'limitations': [
            {'family': 'BULLPEN', 'available': ['Historical team-staff templates', 'batting_recent_bullpen_workload_missing', 'fielding_recent_bullpen_workload_missing'],
             'unavailable': ['Current reliever workload and availability', 'Same-day fatigue authority'],
             'interpretation': 'Rest/travel clusters and historical staff distributions are not bullpen availability.'},
            {'family': 'CURRENT_STATCAST', 'available': ['Governed historical K/BB/whiff/velocity/pitch-composition channels', 'Exposure, missingness and posterior uncertainty'],
             'unavailable': ['Refreshed next-slate source evidence in inspected publication artifacts'], 'sourceThrough': '2026-08-13',
             'interpretation': 'Later publication timestamps do not refresh numerical source inputs.'},
            {'family': 'STARTER_WORKLOAD', 'available': ['Timestamped September 8 starter identity', 'Historical BF exposure', 'pitcher_gs_per_g role proxy', 'Transparent simulated starter-removal hook'],
             'unavailable': ['Current pitch restriction', 'Current pitcher rest/workload authority', 'Fitted current starter-duration model'],
             'interpretation': 'The simulator hook is a policy, not a fitted workload forecast.'},
            {'family': 'LINEUPS', 'available': ['Ordered nine-player snapshot contract', 'Confirmed/projected status and original timestamps', 'Historical-template participant mapping'],
             'unavailable': ['Next-slate participant snapshots', 'Bench/substitution model', 'General historical announced-at lineup archive'],
             'interpretation': 'Absent current confirmation, the prior complete lineup is projected and its order remains fixed.'},
            {'family': 'WEATHER_ROOF_PARK', 'available': ['Static venue/team authority', 'Schedule/calendar and travel geography', 'Pregame-temperature missingness flags', 'Optional timestamped weather capture contract'],
             'unavailable': ['Verified next-slate weather forecast vintage', 'Roof-state authority', 'Numerical weather-response treatment in frozen PA template path'],
             'interpretation': 'Captured weather metadata does not establish numerical forecast use; travel geography is not a park/weather response model.'},
            {'family': 'DEFENSE_BASERUNNING', 'available': ['Empirical base/out transitions', 'Anonymous renderer runner movement'],
             'unavailable': ['Player-specific defensive skill', 'Sprint speed or runner-skill inputs', 'Current defensive alignment strength'],
             'interpretation': 'Simulation geometry is not measured player physical ability.'},
            {'family': 'ABS_2026', 'available': ['Calendar/season context only'],
             'unavailable': ['Explicit governed ABS adoption/challenge behavior', 'Timestamped team/player ABS behavior', 'Identified ABS effect'],
             'interpretation': 'Calendar controls do not identify an ABS mechanism or causal adjustment.'},
        ],
        'historicalFlagCoverage': {
            'scope': 'V18_FOLD_LOCAL_SEMANTIC_TREATMENT_ON_PHYSICALLY_SAFE_ELIGIBLE_DEVELOPMENT_OOF',
            'notCurrentReadiness': True, 'awardedReadinessPoints': 0,
            'interpretation': 'Counts are PA exposures, not independent games or current-source availability. Flag one marks the named missingness state; flag zero is not evidence that a current feed exists.',
            'baselineReproductionSha256': REPRODUCTION_SHA,
            'registeredEligibleOofRows': 501539, 'safeCommonOofRows': 494432,
            'excludedOofRows': 7107, 'exclusionReason': 'MIXED_SEALED_ROW_GROUP_OR_INCOMPLETE_BOUNDARY_DATE',
            'allSafeOof': summarize_flags(all_oof),
            'foldFive': summarize_flags(all_oof[all_oof.foldNumber == 5]),
            'inputs': input_records,
        },
        'minimalForwardContract': {
            'status': 'PROPOSED_CONSUMER_CONTRACT_NOT_A_REGISTERED_OR_EXECUTABLE_MODEL',
            'event': ['canonicalEventId', 'sourceEventId', 'canonicalHomeTeamId', 'canonicalAwayTeamId', 'scheduledStartUtc', 'eventStatus'],
            'sourceEvidence': ['capturedAtUtc', 'evidenceCutoffUtc', 'sourceRegistrationId', 'sourceVersion', 'originalObservedAtUtc', 'originalAvailableAsOfUtc', 'sourceSha256', 'sourceRestrictions'],
            'participants': ['starterCanonicalPlayerIds', 'starterAvailableAsOfUtc', 'orderedLineupPlayerIds', 'lineupStatus', 'lineupAvailableAsOfUtc'],
            'features': ['raw246ArtifactRef', 'treated273ArtifactRef', 'orderedSchemaSha256', 'V18TreatmentManifestSha256', 'perDomainAvailability', 'perDomainSourceAsOf', 'missingReasons'],
            'forecast': ['forecastCreatedAtUtc', 'V18GlobalModelSha256', 'hybridModelSha256', 'clusterSystemSha256', 'calibratorSha256', 'exactEightClassOrder', 'globalProbabilities', 'hybridProbabilities', 'clusterMemberships', 'supportWeights', 'specialistInfluence'],
            'simulation': ['initializationAuthority', 'simulatedStateNotRealizedFutureState', 'transitionModelSha256', 'simulationSeed', 'simulationCount', 'jointScoreDistribution'],
            'consumerRules': [
                'All used evidence must be available by forecast creation; forecast creation must precede first pitch.',
                'AISP imports precomputed immutable evidence only; it does not execute or fit models.',
                'Preserve V18 global and hybrid as separate research tracks; this contract does not register either.',
                'Do not mutate Gen1, V2.1, positions, stakes, promotion status or existing forecasts.',
                'Preserve intersected source rights, attribution, local-research restrictions and commercial-rights review obligations.',
            ],
            'marketJoin': {
                'required': False, 'scope': 'OPTIONAL_FUTURE_DESCRIPTIVE_BENCHMARK_NO_POLICY_OR_WAGERING_AUTHORITY',
                'exactJoinKeys': ['canonicalEventId', 'canonicalHomeTeamId', 'canonicalAwayTeamId', 'bookmakerId', 'marketType', 'marketPeriod', 'line'],
                'quoteFields': ['quoteId', 'side', 'opposingSide', 'price', 'priceFormat', 'opposingPrice', 'quoteObservedAtUtc', 'opposingQuoteObservedAtUtc', 'quoteAvailableAsOfUtc', 'pairedSnapshotId'],
                'timingRule': 'both quote-observed timestamps and available-as-of <= forecastCutoffUtc < scheduledStartUtc',
                'horizonFields': ['forecastCutoffUtc', 'forecastAgeSeconds', 'quoteAgeSeconds', 'opposingQuoteAgeSeconds', 'decisionHorizonSecondsBeforeStart', 'predeclaredMaximumQuoteAgeSeconds'],
                'pairingRule': 'Both market sides must share bookmaker, event, market period, line and a legitimate paired contemporaneous snapshot. Never pair across books or substitute later closing prices.',
                'orientationRule': 'Resolve each side to canonical home/away team or the explicit over/under outcome before comparing probabilities.',
                'missingOrStalePolicy': 'Retain explicit missing/stale/unpaired flags; exclude from market comparison without excluding valid model-only evidence.',
                'outcomeFields': ['outcomeAvailableAtUtc', 'outcomeSourceId', 'outcomeSourceSha256', 'homeScore', 'awayScore', 'marketSettlementStatus', 'voidPushCanceledRules'],
                'prohibitedInference': 'No rejected-opportunity profitability claim without legitimate contemporaneous prices and outcome/settlement evidence.',
                'authorityGranted': False,
            },
            'researchStatus': 'RESEARCH_SHADOW', 'promotionStatus': 'NOT_PROMOTED',
            'wageringAuthority': False, 'executionAllowedInAISP': False,
        },
        'evidenceReferences': [
            'outputs/mlb-v18-daily-slate/slates/2026-09-08/sha256/63eee512e1e7816cdee92c9cf1f0c22801f6171d702bfa69e783f11c6b9966a2/slate-result.json',
            'outputs/mlb-v18-daily-slate/handoffs/sha256/3bbada26170778ca0d26ace39dc86fffbccfb3a82924872fd6dc1a1adef6014a/aisp-handoff.json',
            'outputs/mlb-v18-whole-game-challenger/sha256/a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27/manifest.json',
            'server/sports_current_statcast/mlb_v18_daily_slate.py:61',
            'server/sports_current_statcast/mlb_v18_daily_slate.py:640',
            'server/sports_current_statcast/mlb_v18_daily_slate.py:708',
            'server/sports_current_statcast/mlb_v18_whole_game_challenger.py:254',
            'docs/corrected-treatment-report/MLB_Corrected_240_Feature_Implementation_Report.json',
        ],
        'activity': {'providerCalls': 0, 'aispReads': 0, 'aispWrites': 0, 'modelFits': 0, 'newForecasts': 0,
                     'rawSourcePayloadReads': 0, 'finalOotPayloadBytesRead': 0, 'sealedHistoricalArtifactsRead': 0},
    }
    data = canonical_json_bytes(payload)
    digest = hashlib.sha256(data).hexdigest()
    output = ROOT / 'outputs/mlb-regime-hybrid-ensemble-v1/forward-contract/sha256' / digest
    output.mkdir(parents=True, exist_ok=True)
    text = f'''# MLB regime research: forward evidence contract

Evidence identity: `{digest}`. This supplement is a proposed import contract, not a model registration, forecast publication, promotion, policy or wagering authorization.

## Current result

Only the September 8 slate is present in the inspected daily publications: 13 forecasts and two preserved skips. Their original forecast timestamps span September 8, 11:13–12:01 EDT; all scheduled starts were that evening. The handoff was assembled at 19:28 UTC. Existing numerical templates carry evidence through August 13 (bullpen staff window July 15–August 13). No future-game bundle was found. Do not republish these past games as new pregame forecasts.

## Minimal precomputed research import

Require exact event/home/away identities, UTC first pitch and status, original evidence availability/cutoff timestamps, source versions/restrictions and content hashes; ordered participant identities with confirmed/projected status; raw-246 and treated-273 template references and schema/treatment identities; global/hybrid/cluster/calibrator identities; eight-class probabilities, memberships/support and influence; and simulation initialization, transition version, seeds and distributions. Every source used must be available by forecast creation, strictly before first pitch. AISP imports evidence only, never executes or fits the model. Preserve global V18 and any later authorized hybrid as distinct research tracks.

## Optional market evidence

Join only the same canonical event and teams, bookmaker, market type, market period and line. Both sides need legitimate contemporaneous paired prices, observation and availability timestamps satisfying `quote time <= forecast cutoff < first pitch`. Preserve quote age, forecast age, horizon before start and the predeclared freshness limit. Never pair opposing prices across books or replace them with later closing prices. Preserve missing, stale, unpaired, started, canceled, void and push states. Outcomes require their source identity, checksum, availability timestamp and settlement rules. Without a valid pair, retain model-only analysis and do not infer rejected-bet profitability.

## Evidence limitations

Historical rest/travel is not current bullpen availability. Historical Statcast features are not a refreshed current feed. Starter exposure/role and the transparent removal hook do not provide current pitch restrictions or a fitted workload forecast. Previous confirmed lineups may be projected; there is no bench/substitution model. Static geography and captured weather metadata do not establish numerical weather, roof or park-response treatment. Anonymous simulator movement is not player-specific defense or speed. Calendar fields do not identify an ABS effect.

The accompanying JSON quantifies 15 missingness flags across **494,432 safe OOF PAs / 6,570 games**, including **94,157 fold-five PAs / 1,248 games**. These are historical PA exposures, not current readiness scores. The 7,107 excluded OOF PAs remain excluded to protect the mixed sealed row group and complete-date boundary. No points or formula changes are authorized.

Keep `RESEARCH_SHADOW`, `NOT_PROMOTED`, `wageringAuthority=false` and `executionAllowedInAISP=false`. No Gen1/V2.1, position, stake, policy or historical forecast changes. Preserve source-rights intersection, attribution, local-research restrictions and commercial-rights review obligations.
'''
    files = {'source-evidence.json': data, 'forward-contract.md': text.encode('utf-8')}
    references = []
    for name, raw in files.items():
        path = output / name
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('Immutable forward-contract conflict')
        else:
            with path.open('xb') as stream:
                stream.write(raw)
        references.append({'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
    return {'contentSha256': digest, 'artifacts': references,
            'historicalFlagCoverage': {key: payload['historicalFlagCoverage'][key] for key in ('allSafeOof', 'foldFive')}}


if __name__ == '__main__':
    print(json.dumps(build(), indent=2))
