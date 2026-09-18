"""Focused synthetic gates for read-only prospective source admission."""
import json
from pathlib import Path

import pandas as pd
import pytest

from server.sports_cfb_gen1.prospective_sources import (
    _current_history, load_discovery, load_final_evidence, load_pair_source,
)
from server.sports_cfb_gen1.publication_io import canonical_bytes, reference


CAPTURE = '2026-09-17T12:00:00+00:00'
OBSERVED = '2026-09-18T12:00:00+00:00'


def saved(root, name, value):
    path = Path(root) / name
    path.write_bytes(canonical_bytes(value))
    return reference(path)


def source_fixture(tmp_path, *, completed=True):
    raw = [{'id': 11, 'season': 2026, 'seasonType': 'regular', 'week': 3,
            'homeId': 1, 'awayId': 2, 'homeClassification': 'fbs',
            'awayClassification': 'fbs', 'homePoints': 28, 'awayPoints': 14,
            'neutralSite': False, 'startDate': '2026-09-16T20:00:00+00:00',
            'completed': completed}]
    source = saved(tmp_path, 'source.json', raw)
    request = dict(source, endpoint='/games', parameters={'year': 2026},
                   httpStatus=200, acquiredAt=CAPTURE)
    manifest = saved(tmp_path, 'manifest.json', {'requests': [request]})
    frame = pd.DataFrame([{'game_id': 11, 'season': 2026, 'week': 3,
        'home_id': 1, 'away_id': 2, 'home_score': 28, 'away_score': 14,
        'neutral_site': False, 'scheduled_at': pd.Timestamp(raw[0]['startDate']),
        'is_final': completed, 'primary': completed}])
    frame.to_parquet(tmp_path / 'schedule.parquet', index=False)
    bundle = {'sourceManifest': manifest, 'season': 2026,
              'sourceCutoffUtc': CAPTURE, 'schedule': reference(tmp_path / 'schedule.parquet')}
    return raw, request, bundle


def test_source_literal_finals_have_genuine_capture_clock(tmp_path):
    _, _, bundle = source_fixture(tmp_path)
    history, bindings = _current_history(bundle, as_of_utc=OBSERVED)
    assert len(history) == 1
    assert history.iloc[0].sourceCompleted is True or bool(history.iloc[0].sourceCompleted)
    assert history.iloc[0].source_captured_at == pd.Timestamp(CAPTURE)
    assert bindings['capturedAtUtc'] == CAPTURE
    assert 'sourceCompletedAtUtc' not in history


def test_scores_and_earlier_kickoff_do_not_infer_final(tmp_path):
    _, _, bundle = source_fixture(tmp_path, completed=False)
    history, _ = _current_history(bundle, as_of_utc=OBSERVED)
    assert history.empty


def test_304_preserves_original_raw_acquisition(tmp_path):
    _, request, bundle = source_fixture(tmp_path)
    request.update(originalAcquiredAt=CAPTURE, validatedAtUtc='2026-09-18T10:00:00+00:00')
    bundle['sourceCutoffUtc'] = request['validatedAtUtc']
    bundle['sourceManifest'] = saved(tmp_path, 'manifest.json', {'requests': [request]})
    history, bindings = _current_history(bundle, as_of_utc=OBSERVED)
    assert history.iloc[0].capturedAtUtc == CAPTURE
    assert bindings['lastValidatedAtUtc'] != bindings['capturedAtUtc']


def test_rejects_unobserved_future_capture(tmp_path):
    _, _, bundle = source_fixture(tmp_path)
    with pytest.raises(ValueError, match='chronology'):
        _current_history(bundle, as_of_utc='2026-09-17T11:00:00+00:00')


def test_rejects_normalized_outcome_drift(tmp_path):
    _, _, bundle = source_fixture(tmp_path)
    frame = pd.read_parquet(bundle['schedule']['path'])
    frame.loc[0, 'home_score'] = 29
    frame.to_parquet(bundle['schedule']['path'], index=False)
    bundle['schedule'] = reference(bundle['schedule']['path'])
    with pytest.raises(ValueError, match='result/orientation'):
        _current_history(bundle, as_of_utc=OBSERVED)


def test_rejects_physical_source_mutation(tmp_path):
    _, request, bundle = source_fixture(tmp_path)
    Path(request['path']).write_text('[]')
    with pytest.raises(ValueError, match='Physical binding'):
        _current_history(bundle, as_of_utc=OBSERVED)


def test_rejects_tied_final(tmp_path):
    raw, request, bundle = source_fixture(tmp_path)
    raw[0]['awayPoints'] = 28
    ref = saved(tmp_path, 'source.json', raw)
    request.update(ref)
    bundle['sourceManifest'] = saved(tmp_path, 'manifest.json', {'requests': [request]})
    with pytest.raises(ValueError, match='Tied final'):
        _current_history(bundle, as_of_utc=OBSERVED)


def test_discovery_excludes_expired_and_historical_packages(tmp_path):
    doc = {'schemaVersion': 'CFB_GEN1_SLATE_DISCOVERY_V1', 'createdAtUtc': CAPTURE,
           'packages': [dict(gameId='1', currentlyEligible=True, eligibilityValidUntilUtc='2026-09-18T13:00:00Z'),
                        dict(gameId='2', currentlyEligible=True, eligibilityValidUntilUtc=CAPTURE),
                        dict(gameId='3', currentlyEligible=False, eligibilityValidUntilUtc='2026-09-18T13:00:00Z')]}
    ref = saved(tmp_path, 'discovery.json', doc)
    saved(tmp_path, 'pointer.json', {'schemaVersion': 'CFB_GEN1_SLATE_DISCOVERY_POINTER_V1', 'manifest': ref})
    result = load_discovery(tmp_path / 'pointer.json', as_of_utc=OBSERVED)
    assert [row['gameId'] for row in result['packages']] == ['1']
    assert result['generatedAtUtc'] == CAPTURE


def test_discovery_rejects_duplicate_eligible_revisions(tmp_path):
    package = dict(gameId='1', currentlyEligible=True, eligibilityValidUntilUtc='2026-09-18T13:00:00Z')
    doc = {'schemaVersion': 'CFB_GEN1_SLATE_DISCOVERY_V1', 'createdAtUtc': CAPTURE, 'packages': [package, package]}
    ref = saved(tmp_path, 'discovery.json', doc)
    saved(tmp_path, 'pointer.json', {'schemaVersion': 'CFB_GEN1_SLATE_DISCOVERY_POINTER_V1', 'manifest': ref})
    with pytest.raises(ValueError, match='Multiple currently eligible'):
        load_discovery(tmp_path / 'pointer.json', as_of_utc=OBSERVED)


def test_pair_rejects_less_than_thirty_minutes_lead():
    with pytest.raises(ValueError, match='T-30'):
        load_pair_source({}, {}, as_of_utc=OBSERVED, minimum_lead_minutes=29)


def test_pair_rejects_expired_lease_before_loading_payloads():
    package = {'index': {'sha256': 'opaque'}, 'currentlyEligible': True,
               'eligibilityValidUntilUtc': CAPTURE}
    snapshot = {'document': {'createdAtUtc': CAPTURE, 'packages': [package]}}
    with pytest.raises(ValueError, match='eligibility lease'):
        load_pair_source(snapshot, package, as_of_utc=OBSERVED)


def test_pair_rejects_mutated_discovery_member_before_loading_payloads():
    package = {'index': {'sha256': 'opaque'}, 'currentlyEligible': False}
    snapshot = {'document': {'createdAtUtc': CAPTURE, 'packages': [package]}}
    changed = dict(package, currentlyEligible=True)
    with pytest.raises(ValueError, match='differs from discovery'):
        load_pair_source(snapshot, changed, as_of_utc=OBSERVED)


def test_final_evidence_is_same_admitted_revision(tmp_path):
    raw, request, bundle = source_fixture(tmp_path)
    bundle_ref = saved(tmp_path, 'input.json', bundle)
    row = {'sourceGameId': 11, 'homeTeamId': 1, 'awayTeamId': 2,
           'homeFinalPoints': 28, 'awayFinalPoints': 14, 'season': 2026, 'week': 3,
           'scheduledKickoffUtc': raw[0]['startDate'], 'completed': True, 'sourceCompleted': True,
           'sourceArrayIndex': 0, 'sourceResponseSha256': request['sha256'], 'capturedAtUtc': CAPTURE}
    final = {'schemaVersion': 'CFB_RETAINED_FINAL_RESULT_EVIDENCE_V1', 'generatedAtUtc': CAPTURE,
             'inputVersion': bundle_ref, 'sourceManifest': bundle['sourceManifest'],
             'source': {key: request[key] for key in ('path', 'sha256', 'bytes')}, 'rows': [row]}
    final_ref = saved(tmp_path, 'finals.json', final)
    index = {'schemaVersion': 'CFB_ACTIVATION_RETAINED_EVIDENCE_INDEX_V1', 'generatedAtUtc': CAPTURE,
             'inputVersion': bundle_ref, 'sourceManifest': bundle['sourceManifest'],
             'artifacts': {'finalResultEvidenceJson': final_ref}}
    index_ref = saved(tmp_path, 'index.json', index)
    saved(tmp_path, 'pointer.json', {'schemaVersion': 'CFB_ACTIVATION_RETAINED_EVIDENCE_POINTER_V1', 'index': index_ref})
    result = load_final_evidence(tmp_path / 'pointer.json', as_of_utc=OBSERVED)
    assert result['rows'] == [row]
    assert 'no AISP' in result['admissionMeaning']
