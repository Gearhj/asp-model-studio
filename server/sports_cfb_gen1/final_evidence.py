"""Export retained source-declared finals, without acquisition or evaluation."""
import json
from pathlib import Path

from .lifecycle import atomic_json, now, object_json, read_ref, utc
from .publication_io import reference, verified_bytes


FINAL_SCHEMA = 'CFB_RETAINED_FINAL_RESULT_EVIDENCE_V1'
INDEX_SCHEMA = 'CFB_ACTIVATION_RETAINED_EVIDENCE_INDEX_V1'
POINTER_SCHEMA = 'CFB_ACTIVATION_RETAINED_EVIDENCE_POINTER_V1'
TIMESTAMP_FIELDS = {
    'sourceCompletedAtUtc': ('completedAtUtc', 'completedAt'),
    'sourceUpdatedAtUtc': ('updatedAtUtc', 'updatedAt', 'lastUpdated'),
    'sourceRevisionAtUtc': ('revisionAtUtc', 'revisionAt'),
}


def _source_times(game):
    result = {'sourceTimestampFields': {}}
    for output, names in TIMESTAMP_FIELDS.items():
        supplied = {name: game[name] for name in names if game.get(name) is not None}
        # Preserve source fields verbatim, and never substitute another clock.
        result['sourceTimestampFields'].update(supplied)
        values = {utc(value).isoformat() for value in supplied.values()}
        if len(values) > 1:
            raise ValueError('Conflicting source timestamp fields: ' + output)
        result[output] = next(iter(values)) if values else None
    return result


def publish_final_evidence(*, bundle_ref, exchange_root, capture_pointer=None, clock=now):
    """Called by the existing owner while its publication lock is held.

    Only admitted /games bytes are read. An unchanged admitted version reuses
    its exact index and publication clock; 304 validation does not restamp raw
    acquisition. The pointer advances only after every immutable member exists.
    """
    bundle = read_ref(bundle_ref)
    if (bundle.get('schema') != 'CFB_GEN1_SLATE_INPUT_V1' or
            bundle.get('classification') != 'REAL_GOVERNED_CFBD_INPUTS'):
        raise ValueError('Final export requires admitted governed CFB input')
    manifest_ref = bundle['sourceManifest']
    manifest = read_ref(manifest_ref)
    requests = [item for item in manifest['requests'] if item['endpoint'] == '/games']
    if len(requests) != 1:
        raise ValueError('Exactly one admitted games response required')
    request = requests[0]
    if request.get('httpStatus') != 200 or request['parameters'] != {'year': bundle['season']}:
        raise ValueError('Wrong games source scope or response status')
    raw = verified_bytes(request)
    games = json.loads(raw)
    if not isinstance(games, list):
        raise ValueError('Games response must be a list')
    captured = request.get('originalAcquiredAt', request['acquiredAt'])
    utc(captured)
    validated = request.get('validatedAtUtc')
    if validated is not None and utc(validated) < utc(captured):
        raise ValueError('Validation precedes raw acquisition')
    raw_ref = {'path': request['path'], 'sha256': request['physicalSha256'], 'bytes': request['bytes']}
    capture_ref = None
    if capture_pointer and Path(capture_pointer).exists():
        capture = read_ref(reference(capture_pointer))
        if capture['sourceManifest']['sha256'] != manifest_ref['sha256']:
            raise ValueError('Capture pointer differs from admitted source')
        capture_ref = capture.get('captureReceipt')
        if capture_ref is not None:
            receipt = read_ref(capture_ref)
            if receipt.get('disposition') != 'CAPTURED' or receipt.get('sourceManifest') != manifest_ref:
                raise ValueError('Capture receipt does not bind admitted source')
    root = Path(exchange_root) / 'final-result-evidence'
    pointer = root / 'current.json'
    prior = read_ref(reference(pointer)) if pointer.exists() else None
    previous = read_ref(prior['index']) if prior else None
    previous_finals = read_ref(previous['artifacts']['finalResultEvidenceJson']) if previous else None
    if previous and previous['inputVersion'] == bundle_ref:
        if previous['sourceManifest'] != manifest_ref or previous_finals['source'] != raw_ref:
            raise ValueError('Retained final evidence binding differs')
        return {'disposition': 'REUSED_FINAL_EVIDENCE', 'index': prior['index'],
                'pointer': str(pointer), 'finalResultCount': len(previous_finals['rows']),
                'providerCalls': 0, 'providerBytes': 0}

    targets = {str(item['gameId']): item['target'] for item in bundle['games']}
    if len(targets) != len(bundle['games']):
        raise ValueError('Duplicate admitted game identities')
    ids = [str(game['id']) for game in games]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate source game identities')
    rows = []
    all_completed = 0
    for index, game in enumerate(games):
        if game.get('completed') is not True:
            continue
        all_completed += 1
        if not (game['season'] == bundle['season'] and game['seasonType'] == 'regular' and
                1 <= game['week'] <= 14 and game['homeClassification'] == game['awayClassification'] == 'fbs'):
            continue
        target = targets.get(str(game['id']))
        if (target is None or target['status'] != 'STATUS_FINAL' or
                target['home_id'] != game['homeId'] or target['away_id'] != game['awayId']):
            raise ValueError('Source final differs from admitted identity/status')
        if any(type(game[name]) is not int or game[name] < 0 for name in ('homePoints', 'awayPoints')):
            raise ValueError('Source-completed game lacks valid final points')
        rows.append({
            'provider': 'CFBD', 'sourceGameId': game['id'], 'season': game['season'],
            'week': game['week'], 'seasonType': game['seasonType'],
            'homeTeamId': game['homeId'], 'homeTeam': game['homeTeam'],
            'awayTeamId': game['awayId'], 'awayTeam': game['awayTeam'],
            'homeClassification': game['homeClassification'], 'awayClassification': game['awayClassification'],
            'neutralSite': game['neutralSite'], 'scheduledKickoffUtc': game['startDate'],
            'startTimeTBD': game['startTimeTBD'], 'completed': True, 'sourceCompleted': True,
            'sourceStatusField': 'completed', 'sourceStatusValue': True,
            'homeFinalPoints': game['homePoints'], 'awayFinalPoints': game['awayPoints'],
            'capturedAtUtc': captured, 'lastValidatedAtUtc': validated,
            **_source_times(game),
            'sourceCompletionTimestampStatus': 'PRESENT' if any(game.get(k) is not None for k in TIMESTAMP_FIELDS['sourceCompletedAtUtc']) else 'ABSENT_FROM_RETAINED_SOURCE',
            'sourceUpdateTimestampStatus': 'PRESENT' if any(game.get(k) is not None for k in TIMESTAMP_FIELDS['sourceUpdatedAtUtc']) else 'ABSENT_FROM_RETAINED_SOURCE',
            'sourceRevisionTimestampStatus': 'PRESENT' if any(game.get(k) is not None for k in TIMESTAMP_FIELDS['sourceRevisionAtUtc']) else 'ABSENT_FROM_RETAINED_SOURCE',
            'sourceResponseSha256': raw_ref['sha256'], 'sourceArrayIndex': index,
            'sourceRecordLocator': '$[' + str(index) + ']',
            'canonicalFinalAdmission': 'CONSUMER_OWNED_NOT_ASSERTED',
        })
    created = clock()
    if utc(created) < utc(validated or captured):
        raise ValueError('Evidence publication precedes source observation')
    final = {
        'schemaVersion': FINAL_SCHEMA, 'generatedAtUtc': created,
        'purpose': 'Private retained source evidence for AISP canonical final admission; no settlement or performance evaluation.',
        'attribution': 'Data provided by CollegeFootballData.com', 'privateEvidenceOnly': True,
        'source': raw_ref, 'sourceManifest': manifest_ref, 'captureReceipt': capture_ref,
        'inputVersion': bundle_ref, 'endpoint': '/games', 'parameters': request['parameters'],
        'captureTimeMeaning': 'Raw acquisition, never completion or revision time; 304 validation is separate.',
        'sourceCompletionCriterion': 'Literal completed=true; never inferred from kickoff or scores.',
        'sourceResponseHeaders': request.get('responseHeaders', {}),
        'sourceRecordKeys': sorted(set().union(*(game.keys() for game in games))),
        'selection': 'Admitted season, FBS/FBS regular weeks 1-14, completed=true',
        'sourceScheduleRows': len(games), 'sourceDeclaredCompletedRows': all_completed,
        'inProducerScopeFinalRows': len(rows), 'outsideProducerScopeCompletedRows': all_completed-len(rows),
        'rows': rows,
    }
    final_ref = object_json(root / 'objects', final, 'FINAL_RESULT_EVIDENCE.json')
    old_ids = {row['sourceGameId'] for row in previous_finals['rows']} if previous_finals else set()
    current_ids = {row['sourceGameId'] for row in rows}
    evidence = {
        'schemaVersion': INDEX_SCHEMA, 'generatedAtUtc': created,
        'predecessor': prior['index'] if prior else None,
        'producerOwnedEvidenceOnly': True, 'attribution': final['attribution'],
        'inputVersion': bundle_ref, 'sourceManifest': manifest_ref,
        'artifacts': {'finalResultEvidenceJson': final_ref},
        'sourceReferences': [bundle_ref, manifest_ref, raw_ref] + ([capture_ref] if capture_ref else []),
        'summary': {'inProducerScopeFinalResults': len(rows),
                    'sourceDeclaredCompletedAllClasses': all_completed,
                    'completedRowsOutsideProducerForecastScope': all_completed-len(rows),
                    'sourceAcquiredAtUtc': captured, 'lastValidatedAtUtc': validated,
                    'previouslyExportedFinalGameIdsNotPresent': sorted(old_ids-current_ids),
                    'newHttpRequests': 0, 'newSourceBytes': 0,
                    'canonicalFinalAdmission': 'CONSUMER_OWNED_NOT_ASSERTED'},
    }
    index_ref = object_json(root / 'versions', evidence, 'EVIDENCE_INDEX.json')
    read_ref(index_ref)
    read_ref(final_ref)
    atomic_json(pointer, {'schemaVersion': POINTER_SCHEMA, 'index': index_ref})
    return {'disposition': 'PUBLISHED_FINAL_EVIDENCE', 'index': index_ref,
            'pointer': str(pointer), 'finalResultCount': len(rows),
            'providerCalls': 0, 'providerBytes': 0}
