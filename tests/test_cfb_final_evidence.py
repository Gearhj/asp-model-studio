"""Synthetic retained-final exports; no provider access or model evaluation."""
import copy
import json
from pathlib import Path
import uuid

import pytest

from server.sports_cfb_gen1.final_evidence import publish_final_evidence
from server.sports_cfb_gen1.lifecycle import atomic_json, object_json, owner_lock, read_ref


@pytest.fixture
def space():
    path = Path(__file__).resolve().parents[1] / 'outputs/cfb-final-evidence-fixtures' / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


def game(gid=1, completed=True, **kwargs):
    return dict(id=gid, season=2030, week=1, seasonType='regular',
                startDate='2030-09-01T00:00:00Z', startTimeTBD=False,
                completed=completed, homeId=11, awayId=22, homeTeam='Home', awayTeam='Away',
                homeClassification='fbs', awayClassification='fbs',
                homePoints=21, awayPoints=17, neutralSite=False, **kwargs)


def admitted(space, games, validated=None, target_change=None):
    raw = object_json(space / 'private-raw', games, 'response.json')
    request = dict(endpoint='/games', parameters={'year': 2030}, httpStatus=200,
                   acquiredAt='2030-09-02T01:00:00Z', path=raw['path'],
                   physicalSha256=raw['sha256'], bytes=raw['bytes'], responseHeaders={'etag': 'synthetic'})
    if validated:
        request.update(transportHttpStatus=304, validatedAtUtc=validated,
                       originalAcquiredAt=request['acquiredAt'], responseBytes=0)
    manifest = object_json(space / 'source', {'requests': [request]})
    targets = [{'gameId': str(g['id']), 'target': {'game_id': g['id'],
                'home_id': g['homeId'], 'away_id': g['awayId'],
                'status': 'STATUS_FINAL' if g['completed'] is True else 'SCHEDULED'}} for g in games]
    if target_change:
        targets[0]['target'].update(target_change)
    bundle = object_json(space / 'inputs', {'schema': 'CFB_GEN1_SLATE_INPUT_V1',
        'classification': 'REAL_GOVERNED_CFBD_INPUTS', 'season': 2030,
        'sourceManifest': manifest, 'games': targets})
    return bundle, raw


def run(space, bundle, stamp='2030-09-02T03:00:00Z'):
    return publish_final_evidence(bundle_ref=bundle, exchange_root=space / 'exchange', clock=lambda: stamp)


def final(result):
    return read_ref(read_ref(result['index'])['artifacts']['finalResultEvidenceJson'])


def test_literal_completed_exact_orientation_absent_clocks_and_idempotence(space):
    other = game(3)
    other['homeClassification'] = 'fcs'
    bundle, raw = admitted(space, [game(), game(2, False), other])
    result = run(space, bundle)
    data = final(result)
    assert len(data['rows']) == 1 and data['sourceDeclaredCompletedRows'] == 2
    row = data['rows'][0]
    assert (row['sourceGameId'], row['homeTeamId'], row['awayTeamId']) == (1, 11, 22)
    assert (row['homeFinalPoints'], row['awayFinalPoints']) == (21, 17)
    assert row['completed'] is True and row['sourceResponseSha256'] == raw['sha256']
    assert all(row[k] is None for k in ('sourceCompletedAtUtc', 'sourceUpdatedAtUtc', 'sourceRevisionAtUtc'))
    pointer = Path(result['pointer']); before = pointer.read_bytes(); modified = pointer.stat().st_mtime_ns
    again = run(space, bundle, '2030-09-03T03:00:00Z')
    assert again['disposition'] == 'REUSED_FINAL_EVIDENCE' and again['index'] == result['index']
    assert pointer.read_bytes() == before and pointer.stat().st_mtime_ns == modified


def test_conditional_validation_keeps_original_capture_and_source_clocks(space):
    first, raw = admitted(space, [game()])
    prior = run(space, first)
    second, reused = admitted(space, [game()], validated='2030-09-02T02:00:00Z')
    result = run(space, second)
    row = final(result)['rows'][0]
    assert raw == reused
    assert row['capturedAtUtc'] == '2030-09-02T01:00:00Z'
    assert row['lastValidatedAtUtc'] == '2030-09-02T02:00:00Z'
    assert row['sourceCompletedAtUtc'] is None and row['sourceRevisionAtUtc'] is None
    assert read_ref(result['index'])['predecessor'] == prior['index']


@pytest.mark.parametrize('failure', ['raw-tamper', 'orientation', 'missing-score', 'duplicate'])
def test_invalid_source_fails_without_advancing_current_pointer(space, failure):
    first, _ = admitted(space, [game()]); old = run(space, first)
    pointer = Path(old['pointer']); before = pointer.read_bytes()
    values = [game()]
    if failure == 'missing-score': values[0]['homePoints'] = None
    if failure == 'duplicate': values.append(copy.deepcopy(values[0]))
    bundle, raw = admitted(space, values, validated='2030-09-02T02:00:00Z',
                           target_change={'home_id': 999} if failure == 'orientation' else None)
    if failure == 'raw-tamper': Path(raw['path']).write_bytes(b'tampered synthetic response')
    with pytest.raises(ValueError): run(space, bundle)
    assert pointer.read_bytes() == before


def test_source_correction_genuine_timestamp_and_revoked_final_are_explicit(space):
    bundle, _ = admitted(space, [game()]); first = run(space, bundle)
    corrected = game(completedAt='2030-09-01T03:12:00Z', updatedAt='2030-09-02T01:00:00Z')
    corrected['homePoints'] = 24
    bundle, _ = admitted(space, [corrected]); second = run(space, bundle)
    row = final(second)['rows'][0]
    assert row['sourceCompletedAtUtc'] == '2030-09-01T03:12:00+00:00'
    assert row['sourceTimestampFields']['completedAt'] == corrected['completedAt']
    assert row['homeFinalPoints'] == 24 and final(first)['rows'][0]['homeFinalPoints'] == 21
    bundle, _ = admitted(space, [game(completed=False)]); third = run(space, bundle)
    assert final(third)['rows'] == []
    assert read_ref(third['index'])['summary']['previouslyExportedFinalGameIdsNotPresent'] == [1]


def test_capture_receipt_requires_matching_completed_source(space):
    bundle, _ = admitted(space, [game()])
    source = read_ref(bundle)['sourceManifest']
    bad = object_json(space / 'capture', {'disposition': 'CAPTURED', 'sourceManifest': {'sha256': 'different'}})
    pointer = space / 'capture-current.json'
    atomic_json(pointer, {'sourceManifest': source, 'captureReceipt': bad})
    with pytest.raises(ValueError, match='receipt does not bind'):
        publish_final_evidence(bundle_ref=bundle, exchange_root=space/'exchange', capture_pointer=pointer)
    assert not (space/'exchange/final-result-evidence/current.json').exists()


def test_owner_exports_under_same_lock_after_publication_and_retains_runner_on_failure(space, monkeypatch):
    from server.sports_cfb_gen1 import owner
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('Network forbidden'))
    bundle, _ = admitted(space, [game()]); pointer = space / 'input-current.json'
    atomic_json(pointer, {'inputManifest': bundle})
    release = object_json(space / 'release', {'finalResultEvidenceEnabled': True})
    calls = []
    def tick(**kwargs):
        calls.append('publication')
        value = {'disposition': 'REUSED_IMMUTABLE', 'exitCode': 0}
        return value, object_json(space / 'runners', value)
    monkeypatch.setattr(owner, 'tick', tick)
    def exporter(**kwargs):
        assert calls[-1] == 'publication'
        with pytest.raises(RuntimeError, match='OWNER_BUSY'):
            with owner_lock(space / 'state/publisher.lock'): pass
        return publish_final_evidence(**kwargs)
    args = dict(release_ref=release, input_pointer=pointer, state_root=space / 'state',
                exchange_root=space / 'exchange', clock=lambda: '2030-09-02T03:00:00Z')
    successful, _ = owner.invoke(**args, final_exporter=exporter)
    assert successful['exitCode'] == 0 and successful['providerCalls'] == 0
    assert successful['finalResultEvidence']['finalResultCount'] == 1
    def fail(**kwargs): raise ValueError('Synthetic export failure')
    failed, _ = owner.invoke(**args, final_exporter=fail)
    assert failed['exitCode'] == 1 and failed['disposition'] == 'FAILED_CLOSED'
    assert read_ref(failed['runnerReceipt'])['disposition'] == 'REUSED_IMMUTABLE'
    assert Path(successful['finalResultEvidence']['pointer']).exists()
