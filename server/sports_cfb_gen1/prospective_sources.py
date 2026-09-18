"""Read-only, hash-bound sources for private prospective CFB comparison.

This module neither acquires nor publishes anything. A retained Gen1 package is
used byte-for-byte and its original admitted input snapshot is the common input
for both arms. A fresh canonical discovery lease is separately required. Current
results enter strength state only when the retained source literally declares
completion; kickoff is never a completion/availability surrogate.
"""
from __future__ import annotations

from datetime import timedelta
import io
import json
from pathlib import Path

import pandas as pd

from .lifecycle import read_ref, utc
from .pipeline import FEATURE_COLUMNS
from .publication_io import digest, reference, verified_bytes
from .render import verify_package


def _frame(ref, **kwargs):
    return pd.read_parquet(io.BytesIO(verified_bytes(ref)), **kwargs)


def _single(items, predicate, message):
    chosen = [item for item in items if predicate(item)]
    if len(chosen) != 1:
        raise ValueError(message)
    return chosen[0]


def _not_future(value, clock, label):
    if utc(value) > utc(clock):
        raise ValueError(label + ' is later than observation')


def load_discovery(pointer, *, as_of_utc):
    """Snapshot a live pointer once; do not refresh it or invoke its owner."""
    utc(as_of_utc)
    pointer_ref = reference(pointer)
    pointer_doc = read_ref(pointer_ref)
    if pointer_doc.get('schemaVersion') != 'CFB_GEN1_SLATE_DISCOVERY_POINTER_V1':
        raise ValueError('Wrong discovery pointer schema')
    manifest = pointer_doc['manifest']
    document = read_ref(manifest)
    if document.get('schemaVersion') != 'CFB_GEN1_SLATE_DISCOVERY_V1':
        raise ValueError('Wrong discovery schema')
    _not_future(document['createdAtUtc'], as_of_utc, 'Discovery')
    packages = [item for item in document['packages']
                if item.get('currentlyEligible') is True
                and item.get('eligibilityValidUntilUtc') is not None
                and utc(as_of_utc) < utc(item['eligibilityValidUntilUtc'])]
    if len({str(item['gameId']) for item in packages}) != len(packages):
        raise ValueError('Multiple currently eligible revisions for one game')
    return {'pointer': pointer_ref, 'manifest': manifest, 'document': document,
            'generatedAtUtc': document['createdAtUtc'],
            'observedAtUtc': as_of_utc, 'packages': packages}


def _bundle_target(bundle, game_id):
    return _single(bundle['games'], lambda item: str(item['gameId']) == str(game_id),
                   'Unique admitted target required')


def _feature(bundle, target):
    features = _frame(bundle['features'], filters=[('game_id', '=', int(target['game_id']))])
    if len(features) != 1:
        raise ValueError('Unique admitted feature row required')
    row = features.iloc[0]
    for key in ('home_id', 'away_id', 'season', 'week'):
        if int(row[key]) != int(target[key]):
            raise ValueError('Feature target identity differs')
    if pd.Timestamp(row.scheduled_at) != pd.Timestamp(target['scheduled_at']):
        raise ValueError('Feature target kickoff differs')
    return features


def _feature_values(row):
    return {key: None if pd.isna(row[key]) else float(row[key]) for key in FEATURE_COLUMNS}


def _current_history(bundle, *, as_of_utc):
    """Source-literal primary finals, verified against the admitted normalization.

    The returned acquisition clock means only 'known by this capture', not the
    final's completion clock. The caller applies its frozen 48-hour kickoff
    embargo in addition to this genuine source-observation requirement.
    """
    manifest = read_ref(bundle['sourceManifest'])
    source = _single(manifest['requests'], lambda item: item['endpoint'] == '/games',
                     'Exactly one source games response required')
    if source.get('httpStatus') != 200 or source.get('parameters') != {'year': bundle['season']}:
        raise ValueError('Wrong current history source scope/status')
    captured = source.get('originalAcquiredAt', source['acquiredAt'])
    validated = source.get('validatedAtUtc')
    if not utc(captured) <= utc(validated or captured) <= utc(bundle['sourceCutoffUtc']) <= utc(as_of_utc):
        raise ValueError('Current history acquisition/cutoff chronology')
    raw = json.loads(verified_bytes(source))
    if len({str(item['id']) for item in raw}) != len(raw):
        raise ValueError('Duplicate source current game identity')
    normalized = _frame(bundle['schedule'])
    if normalized.game_id.duplicated().any():
        raise ValueError('Duplicate normalized current game identity')
    normalized = normalized.set_index('game_id', drop=False)
    selected = []
    for index, item in enumerate(raw):
        if item.get('completed') is not True:
            continue
        if not (item['season'] == bundle['season'] and item['seasonType'] == 'regular'
                and 1 <= int(item['week']) <= 14
                and item['homeClassification'] == item['awayClassification'] == 'fbs'):
            continue
        for key in ('homePoints', 'awayPoints'):
            if type(item.get(key)) is not int or item[key] < 0:
                raise ValueError('Literal final lacks integer nonnegative score')
        if item['homePoints'] == item['awayPoints']:
            raise ValueError('Tied final cannot update strength state')
        game_id = int(item['id'])
        if game_id not in normalized.index:
            raise ValueError('Source final absent from admitted schedule')
        row = normalized.loc[game_id]
        if not bool(row.is_final) or not bool(row.primary):
            raise ValueError('Source final differs from admitted final classification')
        checks = {'home_id': item['homeId'], 'away_id': item['awayId'],
                  'home_score': item['homePoints'], 'away_score': item['awayPoints'],
                  'season': item['season'], 'week': item['week'],
                  'neutral_site': item['neutralSite']}
        if any(row[key] != value for key, value in checks.items()):
            raise ValueError('Source final differs from admitted result/orientation')
        if pd.Timestamp(row.scheduled_at) != pd.Timestamp(item['startDate']):
            raise ValueError('Source final kickoff differs from admitted schedule')
        if utc(item['startDate']) >= utc(captured):
            raise ValueError('Source final kickoff is not before observed final capture')
        result = row.to_dict()
        result.update(sourceCompleted=True, capturedAtUtc=captured,
                      source_captured_at=pd.Timestamp(captured),
                      lastValidatedAtUtc=validated, sourceRecordLocator=f'$[{index}]',
                      sourceResponseSha256=source.get('sha256', source.get('physicalSha256')))
        selected.append(result)
    frame = pd.DataFrame(selected)
    if frame.empty:
        frame = normalized.iloc[0:0].reset_index(drop=True)
        for key in ('sourceCompleted', 'capturedAtUtc', 'source_captured_at', 'lastValidatedAtUtc',
                    'sourceRecordLocator', 'sourceResponseSha256'):
            frame[key] = pd.Series(dtype='object')
    else:
        frame = frame.sort_values(['scheduled_at', 'game_id']).reset_index(drop=True)
    return frame, {'sourceManifest': bundle['sourceManifest'], 'sourceGames': {
        'path': source['path'], 'sha256': source.get('sha256', source.get('physicalSha256')),
        'bytes': source['bytes']}, 'capturedAtUtc': captured, 'lastValidatedAtUtc': validated,
        'sourceCutoffUtc': bundle['sourceCutoffUtc'],
        'completionCriterion': 'literal completed=true in admitted source; no inferred completion timestamp'}


def load_pair_source(snapshot, package, *, as_of_utc, minimum_lead_minutes=30):
    """Return exact canonical arm and its original cutoff-eligible common input."""
    if minimum_lead_minutes < 30:
        raise ValueError('Private capture must preserve at least the T-30 cutoff')
    _not_future(snapshot['document']['createdAtUtc'], as_of_utc, 'Discovery')
    member = _single(snapshot['document']['packages'],
                     lambda item: item['index'] == package['index'],
                     'Package not uniquely bound by discovery')
    if member != package:
        raise ValueError('Package differs from discovery member')
    if (member.get('currentlyEligible') is not True
            or not member.get('eligibilityValidUntilUtc')
            or utc(as_of_utc) >= utc(member['eligibilityValidUntilUtc'])):
        raise ValueError('Canonical forecast does not have a current eligibility lease')
    receipt = read_ref(member['publicationReceipt'])
    for key in ('gameId', 'forecastId', 'revisionKey', 'index', 'packageAddress',
                'packageDirectory', 'committedAtUtc'):
        if receipt[key] != member[key]:
            raise ValueError('Original publication receipt differs from discovery')
    package_dir = Path(member['packageDirectory'])
    index = read_ref(member['index'])
    if reference(package_dir / 'index.json') != member['index']:
        raise ValueError('Package index path/address differs')
    verify_package(package_dir)
    forecast = json.loads((package_dir / 'forecast.json').read_bytes())
    target = forecast['game']
    if (forecast['forecastId'] != member['forecastId']
            or forecast['revisionKey'] != member['revisionKey']
            or str(target['game_id']) != str(member['gameId'])
            or index['forecastId'] != forecast['forecastId']):
        raise ValueError('Canonical forecast identity differs')
    deadline = utc(target['scheduled_at']) - timedelta(minutes=minimum_lead_minutes)
    if not utc(forecast['sourceCutoff']) <= utc(forecast['createdAt']) <= utc(receipt['committedAtUtc']) <= utc(as_of_utc) < deadline:
        raise ValueError('Canonical publication or prospective capture cutoff chronology')
    original_ref = forecast['sourceBindings']['inputVersion']
    original = read_ref(original_ref)
    current_ref = snapshot['document']['inputVersion']
    current = read_ref(current_ref)
    for bundle in (original, current):
        if bundle.get('schema') != 'CFB_GEN1_SLATE_INPUT_V1' or bundle.get('classification') != 'REAL_GOVERNED_CFBD_INPUTS':
            raise ValueError('Non-governed input snapshot')
        if bundle['modelBindings'] != forecast['modelBindings']:
            raise ValueError('Canonical frozen model bindings differ')
        _not_future(bundle['admittedAtUtc'], as_of_utc, 'Input admission')
        _not_future(bundle['sourceCutoffUtc'], as_of_utc, 'Input cutoff')
        row = _bundle_target(bundle, target['game_id'])
        if row.get('exclusion') or row.get('inputBlockers') or row['target']['status'] != 'SCHEDULED':
            raise ValueError('Target is excluded, blocked, or no longer scheduled')
        for key in ('home_id', 'away_id', 'season', 'week', 'neutral_site', 'conference_competition'):
            if row['target'][key] != target[key]:
                raise ValueError('Current/original target identity or venue differs')
        if utc(row['target']['scheduled_at']) != utc(target['scheduled_at']):
            raise ValueError('Current/original target kickoff differs')
    if original['sourceCutoffUtc'] != forecast['sourceCutoff'] or original['sourceManifest'] != forecast['sourceBindings']['cfbdManifest']:
        raise ValueError('Original input/forecast source binding differs')
    feature = _feature(original, target)
    latest_feature = _feature(current, target)
    values = _feature_values(feature.iloc[0])
    if values != forecast['featureValues'] or values != _feature_values(latest_feature.iloc[0]):
        raise ValueError('Canonical original/current feature values differ')
    for ref in forecast['modelBindings'].values():
        verified_bytes(ref)
    current_history, history_bindings = _current_history(original, as_of_utc=as_of_utc)
    metadata = _frame(original['historicalGames'], columns=['season', 'scheduled_at'])
    if not metadata.season.le(2025).all() or not metadata.scheduled_at.lt(pd.Timestamp(original['sourceCutoffUtc'])).all():
        raise ValueError('Historical input contains unpermitted season or future timestamp')
    historical_history = _frame(original['historicalGames'])
    draws_ref = reference(package_dir / 'baseline-joint-draws.parquet')
    draws = _frame(draws_ref)
    declared_draws = forecast['population']['drawArtifact']
    if (draws_ref['sha256'] != declared_draws['sha256']
            or draws_ref['bytes'] != declared_draws['bytes']):
        raise ValueError('Canonical package draw bytes differ from original forecast')
    baseline = forecast['baseline']
    points = {key: float(baseline[source]) for key, source in {
        'pred_home': 'expectedHomePoints', 'pred_away': 'expectedAwayPoints',
        'pred_margin': 'expectedHomeMargin', 'pred_total': 'expectedTotal'}.items()}
    normalized_target = dict(target)
    normalized_target['scheduled_at'] = pd.Timestamp(target['scheduled_at']).tz_convert('UTC')
    return {'target': normalized_target, 'featureRow': feature, 'baselinePoints': points,
            'baselineDraws': draws, 'currentHistory': current_history,
            'historicalHistory': historical_history, 'forecast': forecast,
            'packageReceipt': receipt, 'observedAtUtc': as_of_utc,
            'inputCutoffUtc': original['sourceCutoffUtc'],
            'currentEligibilityEvaluatedAtUtc': snapshot['document']['createdAtUtc'],
            'bindings': {'discoveryPointer': snapshot['pointer'], 'discovery': snapshot['manifest'],
                'canonicalIndex': member['index'], 'publicationReceipt': member['publicationReceipt'],
                'originalInputVersion': original_ref, 'currentInputVersion': current_ref,
                'originalFeatures': original['features'], 'historicalGames': original['historicalGames'],
                'canonicalDraws': draws_ref, 'featureValuesSha256': digest(values),
                'modelBindings': forecast['modelBindings'], 'currentHistory': history_bindings,
                'currentEligibilityValidUntilUtc': member['eligibilityValidUntilUtc'],
                'privateCaptureDeadlineUtc': deadline.isoformat(),
                'identityPolicy': 'Existing Gen1 direct integer CFBD/historical team identities; no fuzzy remapping'}}


def load_final_evidence(pointer, *, as_of_utc):
    """Read admitted source finals for private research, not AISP admission.

    Each row retains its exact immutable revision. Both study arms must bind the
    same row/revision downstream; this adapter does not select or score outcomes.
    """
    pointer_ref = reference(pointer)
    pointer_doc = read_ref(pointer_ref)
    if pointer_doc.get('schemaVersion') != 'CFB_ACTIVATION_RETAINED_EVIDENCE_POINTER_V1':
        raise ValueError('Wrong final evidence pointer schema')
    index_ref = pointer_doc['index']
    index = read_ref(index_ref)
    if index.get('schemaVersion') != 'CFB_ACTIVATION_RETAINED_EVIDENCE_INDEX_V1':
        raise ValueError('Wrong final evidence index schema')
    final_ref = index['artifacts']['finalResultEvidenceJson']
    final = read_ref(final_ref)
    if final.get('schemaVersion') != 'CFB_RETAINED_FINAL_RESULT_EVIDENCE_V1':
        raise ValueError('Wrong final evidence schema')
    _not_future(index['generatedAtUtc'], as_of_utc, 'Final index')
    _not_future(final['generatedAtUtc'], as_of_utc, 'Final evidence')
    if index['inputVersion'] != final['inputVersion'] or index['sourceManifest'] != final['sourceManifest']:
        raise ValueError('Final evidence index source binding differs')
    bundle = read_ref(final['inputVersion'])
    if bundle['sourceManifest'] != final['sourceManifest']:
        raise ValueError('Final evidence does not bind admitted source')
    normalized, history_bindings = _current_history(bundle, as_of_utc=as_of_utc)
    raw = json.loads(verified_bytes(final['source']))
    expected_source = history_bindings['sourceGames']
    if final['source'] != expected_source:
        raise ValueError('Final evidence raw source differs from admitted capture')
    if len({row['sourceGameId'] for row in final['rows']}) != len(final['rows']):
        raise ValueError('Duplicate final evidence game')
    if set(normalized.game_id.astype(int)) != {int(row['sourceGameId']) for row in final['rows']}:
        raise ValueError('Final evidence population differs from admitted source')
    for row in final['rows']:
        source = raw[row['sourceArrayIndex']]
        pairs = {'sourceGameId': 'id', 'homeTeamId': 'homeId', 'awayTeamId': 'awayId',
                 'homeFinalPoints': 'homePoints', 'awayFinalPoints': 'awayPoints',
                 'season': 'season', 'week': 'week', 'scheduledKickoffUtc': 'startDate'}
        if (row.get('completed') is not True or row.get('sourceCompleted') is not True
                or source.get('completed') is not True
                or any(row[key] != source[other] for key, other in pairs.items())
                or row['sourceResponseSha256'] != expected_source['sha256']
                or row['capturedAtUtc'] != history_bindings['capturedAtUtc']):
            raise ValueError('Final row differs from literal admitted source revision')
    return {'rows': final['rows'], 'document': final, 'observedAtUtc': as_of_utc,
            'bindings': {'pointer': pointer_ref, 'index': index_ref, 'finalEvidence': final_ref,
                         'inputVersion': final['inputVersion'], 'source': final['source'],
                         'sourceManifest': final['sourceManifest']},
            'admissionMeaning': 'Private research source-final verification only; no AISP canonical admission asserted'}
