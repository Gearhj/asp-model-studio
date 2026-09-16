"""Incremental local evidence bridge for V18, never a Gen1-to-V18 prediction alias.

This step captures and composes actual current inputs. Incomplete evidence cannot
invoke the historical-template simulator. No provider or AISP write path exists.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from server.sports_datasets.consumer import canonical_json_bytes
from .mlb_regime_baseline import sha_file, verified_json
from .mlb_v18_daily_slate import PA_MODEL_SHA256, PARENT_BUNDLE_SHA256, TREATMENT_MANIFEST_SHA256

ROOT = Path(__file__).resolve().parents[2]
BASELINE_SHA = '0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9'
OUTPUT = ROOT / 'outputs/mlb-v18-current-slate-v1'


def utc(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Source timestamps must specify a timezone')
    return parsed.astimezone(timezone.utc)


def reference(path):
    path = Path(path)
    return {'path': str(path.resolve()), 'sha256': sha_file(path), 'bytes': path.stat().st_size}


def write_object(root: Path, name: str, payload: dict) -> tuple[dict, bool]:
    raw = canonical_json_bytes(payload)
    digest = hashlib.sha256(raw).hexdigest()
    path = root / 'objects/sha256' / digest / name
    reused = path.exists()
    if reused:
        if path.read_bytes() != raw:
            raise ValueError('Immutable current-slate evidence conflict')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
    return reference(path), reused


def numerical_identity(*, game_id: str, model_sha: str, ordered_inputs: list, seed: int) -> str:
    """Publication clocks/source capture clocks cannot create new numerical versions."""
    return hashlib.sha256(canonical_json_bytes({'gameId': game_id, 'modelSha256': model_sha,
        'treatmentSha256': TREATMENT_MANIFEST_SHA256, 'orderedInputs': ordered_inputs, 'seed': seed})).hexdigest()


def source_body(game: dict) -> dict:
    # Capture/query clocks and summary-of-capture hashes are operational receipts,
    # not source refresh. Original observation, availability and version times stay.
    return {key: value for key, value in game.items() if key not in ('snapshotContentSha256', 'existingForecastMetadata')}


def load_contract():
    baseline = verified_json(ROOT / f'outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache/baseline-reproduction-{BASELINE_SHA}.json', BASELINE_SHA)
    if len(baseline['rawFeatureColumns']) != 246 or len(baseline['treatedFeatureColumns']) != 273:
        raise ValueError('Accepted V18 source/model schema differs')
    preprocessing_sha = '4171306af87bee46e74d2b5141189a5916382967322592243bf71e9eed9cf684'
    metadata = verified_json(ROOT / f'.runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/{preprocessing_sha}.json', preprocessing_sha)
    if metadata['sourceColumns'] != baseline['rawFeatureColumns'] or metadata['orderedFeatures'] != baseline['treatedFeatureColumns']:
        raise ValueError('Saved treatment dependency schema differs')
    baseline['priorOutputSchema'] = metadata['prior']['outputSchema']
    return baseline


def current_player_crosswalk(games):
    """Read identity-only Chadwick columns, not game or sealed feature payloads."""
    path = Path('C:/Users/james/asp-data-staging/mlb-silver-v1/objects/sha256/ab06c88e7d4fa6e78b397c8a4dfbbc2c8a21a51c03f50fd78ee49de232fb0aaf/object.parquet')
    expected = '5265b8d98a0b8d991f7285259a21d7e49ecf45f1ee1022d7902753ffb862fc2f'
    if sha_file(path) != expected:
        raise ValueError('Accepted identity-only crosswalk checksum differs')
    identifiers = set()
    for game in games:
        for side in game['sides']:
            if side['starter'].get('mlbamId'):
                identifiers.add(str(side['starter']['mlbamId']))
            identifiers.update(str(row['mlbam']) for row in side['lineup'] if row.get('mlbam'))
    frame = pq.read_table(path, columns=['canonicalPlayerId', 'mlbamId', 'resolutionStatus'],
                          filters=[('mlbamId', 'in', sorted(identifiers))]).to_pandas().drop_duplicates()
    frame = frame[frame.resolutionStatus.eq('MATCHED_EXACT')]
    mapping = {}
    for mlbam, group in frame.groupby('mlbamId'):
        values = group.canonicalPlayerId.dropna().unique()
        if len(values) == 1:
            mapping[str(mlbam)] = str(values[0])
    return mapping, {'path': str(path), 'sha256': expected, 'scope': 'IDENTITY_ONLY_NOT_MODEL_FEATURES',
                     'requestedPlayers': len(identifiers), 'exactlyMapped': len(mapping),
                     'unresolvedMlbamIds': sorted(identifiers - set(mapping))}


def compose_game_evidence(game, *, contract, crosswalk, as_of_utc):
    from .mlb_v18_current_inputs import compose_current_input
    info = game['game']
    game_id = info['game_id']
    states = game.get('gameState') or []
    current_state = states[0] if states else {}
    source = {'sourceIdentity': str(current_state.get('source') or 'AISP_PERSISTED_SCHEDULE'),
              'observedAt': current_state.get('observed_at'), 'availableAsOf': current_state.get('available_as_of'),
              'eventId': game_id}
    sides = {row['side']: row for row in game['sides']}
    venue_path = ROOT / 'server/sports_current_statcast/mlb_context_authorities_v1.json'
    venue_authorities = verified_json(venue_path)
    matches = [venue for venue in venue_authorities['venues'] if
               str(info.get('source_venue_id') or '') in venue['mlbVenueIds']]
    timezone_name = info.get('timezone')
    venue_resolution = {'status': 'PERSISTED_AISP_VENUE_TIMEZONE', 'sourceVenueId': info.get('source_venue_id')}
    if not timezone_name and len(matches) == 1:
        timezone_name = matches[0]['timeZone']
        venue_resolution = {'status': 'EXACT_MLB_VENUE_ID_STATIC_AUTHORITY', 'sourceVenueId': info['source_venue_id'],
                            'authority': reference(venue_path), 'venueKey': matches[0]['venueKey']}
    if not timezone_name:
        return {'event': {'canonicalGameId': game_id, 'startsAtUtc': info['starts_at']}, 'rows': [],
                'rowsComposed': 0, 'expectedStartingLineupRows': 18, 'coversAllSimulatedMatchups': False,
                'blockingReason': 'EXACT_VENUE_TIMEZONE_AUTHORITY_UNAVAILABLE', 'venueResolution': venue_resolution}
    event = {'canonicalGameId': game_id, 'gameDate': utc(info['starts_at']).astimezone(ZoneInfo(timezone_name)).date().isoformat(),
             'startsAtUtc': info['starts_at'], 'venueTimezone': timezone_name, 'venueId': info.get('venue_id'),
             'homeTeamId': sides.get('HOME', {}).get('team', {}).get('abbreviation'),
             'awayTeamId': sides.get('AWAY', {}).get('team', {}).get('abbreviation'), 'source': source}
    reports = []
    for batting_side, defending_side in [('AWAY', 'HOME'), ('HOME', 'AWAY')]:
        batting = sides.get(batting_side) or {}
        defending = sides.get(defending_side) or {}
        starter = defending.get('starter') or {}
        for entry in batting.get('lineup') or []:
            fields = {}
            lineup = batting['lineupAuthority']
            def add(name, value, evidence):
                if value is not None:
                    fields[name] = {'value': value, 'sourceIdentity': evidence.get('source'),
                        'observedAt': evidence.get('observedAt'), 'availableAsOf': evidence.get('availableAsOf'), 'eventId': game_id}
            add('batterCanonicalPlayerId', crosswalk.get(str(entry.get('mlbam'))), lineup)
            add('pitcherCanonicalPlayerId', crosswalk.get(str(starter.get('mlbamId'))), starter)
            add('batterBats', entry.get('bats'), lineup)
            add('pitcherThrows', starter.get('throws'), starter)
            for hand, participant in [('batterBats', 'batterCanonicalPlayerId'), ('pitcherThrows', 'pitcherCanonicalPlayerId')]:
                if hand in fields:
                    fields[hand]['playerId'] = fields.get(participant, {}).get('value')
            fields['canonicalPaId'] = {**source, 'value': f'SIMULATION_INPUT:{game_id}:{batting_side}:{entry["batting_order"]}',
                                       'identityKind': 'HYPOTHETICAL_PA'}
            _, coverage = compose_current_input(source_order=contract['rawFeatureColumns'], event=event,
                batting_side=batting_side, as_of_utc=as_of_utc, field_evidence=fields,
                treated_order=contract['treatedFeatureColumns'], prior_output_schema=contract['priorOutputSchema'])
            reports.append({'battingSide': batting_side, 'battingOrder': entry['batting_order'],
                'batterMlbamId': entry.get('mlbam'), 'opposingStarterMlbamId': starter.get('mlbamId'), 'coverage': coverage})
    return {'event': event, 'rows': reports, 'rowsComposed': len(reports), 'venueResolution': venue_resolution,
            'expectedStartingLineupRows': 18, 'coversAllSimulatedMatchups': False,
            'bullpenModelInputs': 'UNAVAILABLE_NO_BORROWED_HISTORICAL_ROSTER',
            'note': 'Starting-lineup diagnostic input rows only. No values from another player or prior game copied; no fabricated median or cold start.'}


def verify_accepted_reload(contract):
    """A small physically Development-only fixture verifies the unmodified artifact."""
    from .stage3_model_laboratory import _aligned_probabilities
    from .mlb_regime_baseline import PROBABILITY_COLUMNS
    from threadpoolctl import threadpool_limits
    path = ROOT / f'outputs/mlb-v18-whole-game-challenger/sha256/{PARENT_BUNDLE_SHA256}/executable/v18-pa-fold5.joblib'
    if sha_file(path) != PA_MODEL_SHA256:
        raise ValueError('Accepted V18 executable hash differs')
    model = joblib.load(path)
    if list(model.ordered_features) != contract['rawFeatureColumns'] or list(model.preprocessor.ordered_features) != contract['treatedFeatureColumns']:
        raise ValueError('Accepted raw/semantic feature order mismatch')
    for name in ['matchedOof', 'rawDevelopment']:
        artifact = contract['artifacts'][name]
        if sha_file(Path(artifact['path'])) != artifact['sha256']:
            raise ValueError('Development-only fixture cache hash differs')
    original = pd.read_parquet(contract['artifacts']['matchedOof']['path'], filters=[('foldNumber', '=', 5)]).head(32)
    raw = pd.read_parquet(contract['artifacts']['rawDevelopment']['path'],
        filters=[('canonicalPaId', 'in', original.canonicalPaId.tolist())], columns=contract['rawFeatureColumns'])
    raw = raw.set_index('canonicalPaId', drop=False).loc[original.canonicalPaId, contract['rawFeatureColumns']]
    if len(raw) != 32 or raw.game_date.max() > '2026-08-06':
        raise ValueError('Development fixture scope differs')
    with threadpool_limits(limits=4):
        actual = _aligned_probabilities(model.estimator, model.preprocessor.transform(raw))
    expected = original[PROBABILITY_COLUMNS].to_numpy()
    if actual.tobytes() != expected.tobytes():
        raise ValueError('Accepted V18 fixture reproduction mismatch')
    return {'model': reference(path), 'rawInputs': 246, 'semanticInputs': 273, 'fixtureRows': 32,
            'scope': 'EXISTING_PHYSICALLY_DEVELOPMENT_ONLY_CACHE', 'bitwiseEqual': True,
            'maximumAbsoluteDifference': 0., 'refits': 0, 'currentForecastsExecuted': 0}


def build_evidence_bridge(inventory, *, output_root=OUTPUT, checked_at_utc=None, crosswalk=None):
    now = checked_at_utc or datetime.now(timezone.utc).isoformat()
    contract = load_contract()
    if crosswalk is None:
        crosswalk, crosswalk_ref = current_player_crosswalk(inventory['games'])
    else:
        crosswalk_ref = {'scope': 'CALLER_VERIFIED_IDENTITY_MAP'}
    games, reuse_count = [], 0
    for record in inventory['games']:
        evidence, reused = write_object(output_root, 'source-evidence.json', source_body(record))
        reuse_count += reused
        try:
            composed = compose_game_evidence(record, contract=contract, crosswalk=crosswalk, as_of_utc=now)
        except ValueError as exc:
            composed = {'event': {'canonicalGameId': record['game']['game_id']}, 'rows': [], 'rowsComposed': 0,
                        'blockingReason': 'SOURCE_COMPOSITION_POINT_IN_TIME_OR_IDENTITY_INVALID', 'detail': str(exc)}
        # Revalidation clocks live in the run receipt. Unchanged source-backed
        # values/dependencies retain the same immutable composition object.
        for row in composed['rows']:
            row['coverage'].pop('asOfUtc', None)
        composed_ref, _ = write_object(output_root, 'input-coverage.json', composed)
        reasons = list(record['currentParticipantGateReasons'])
        if composed.get('blockingReason'):
            reasons.append(composed['blockingReason'])
        start = utc(record['game']['starts_at'])
        if utc(now) >= start:
            reasons.append('ACTUAL_EXECUTION_AT_OR_AFTER_FIRST_PITCH')
        if str(record['game']['status']).upper() not in ('SCHEDULED', 'PREGAME', 'PRE_GAME'):
            reasons.append('GAME_NOT_ELIGIBLE_PREGAME')
        # Current Gen1 aggregates do not implement V18 player-level exposures or
        # lag windows. Never translate its readiness score into feature authority.
        reasons += ['CURRENT_PLAYER_LEVEL_V18_SUFFICIENT_STATISTICS_UNAVAILABLE',
                    'CURRENT_LAST100_BATTER_LAST250_PITCHER_STATE_UNAVAILABLE',
                    'COMPLETE_TEAM_REST_TRAVEL_CONTEXT_EVIDENCE_UNAVAILABLE',
                    'CURRENT_BULLPEN_MEMBERSHIP_AND_WORKLOAD_EVIDENCE_UNAVAILABLE']
        games.append({'gameId': record['game']['game_id'], 'scheduledStartUtc': start.isoformat(),
            'teams': [{'side': side['side'], **side['team']} for side in record['sides']],
            'status': 'SKIPPED_MISSING_SOURCE_EVIDENCE', 'skipReasons': reasons,
            'sourceEvidence': evidence, 'sourceObjectReused': reused, 'inputCoverage': composed_ref,
            'startingLineupRowsComposed': composed['rowsComposed'], 'forecastPublished': False})
    receipt = {'schemaVersion': 'MLB_V18_CURRENT_SLATE_BRIDGE_RECEIPT_V1', 'checkedAtUtc': now,
        'sourceCapturedAtUtc': inventory['capturedAtUtc'], 'slateDateEastern': inventory['slateDateEastern'],
        'gamesDiscovered': len(games), 'games': games, 'gamesWithCurrentParticipants': inventory['currentParticipantCompleteGameCount'],
        'supportedForecastGames': 0, 'newForecasts': 0, 'gamesSkipped': len(games), 'sourceObjectsReused': reuse_count,
        'currentPlayerIdentity': crosswalk_ref, 'parentBundleSha256': PARENT_BUNDLE_SHA256,
        'paModelSha256': PA_MODEL_SHA256, 'treatmentManifestSha256': TREATMENT_MANIFEST_SHA256,
        'status': 'SOURCE_BRIDGE_OPERATIONAL_FORECAST_PUBLICATION_BLOCKED',
        'isForecastHandoff': False, 'aispForecastHandoff': None,
        'nightlyForecastPublicationOperational': False, 'scheduledTaskInstalled': False,
        'implementationScope': 'Incremental live local source capture and exact-contract missing-input composition; no historical-template simulator fallback.',
        'nextIntegrationAfterSourcesExist': 'Verify source-backed prospective transform authority with truthful current game dates. Existing Development-only date guards are not bypassed.',
        'authority': {'status': 'RESEARCH_SHADOW', 'promotionStatus': 'NOT_PROMOTED', 'wageringAuthority': False, 'executionAllowedInAISP': False},
        'safety': {'modelFits': 0, 'providerCalls': 0, 'aispRowsModified': 0, 'officialForecastsModified': 0,
                   'policyChanges': 0, 'positionsChanged': 0, 'settlementsChanged': 0, 'finalOotPayloadBytesRead': 0}}
    result, _ = write_object(output_root, 'bridge-receipt.json', receipt)
    return receipt, result
