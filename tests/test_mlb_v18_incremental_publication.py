"""Synthetic active-path publication; no model, provider or real exchange."""
from copy import deepcopy
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
import numpy as np

from server.sports_current_statcast import mlb_v18_current_publication as publication
from server.sports_current_statcast import mlb_v18_exchange as exchange
from server.sports_current_statcast import mlb_v18_unattended as unattended
from test_mlb_v18_current_publication import (
    _SyntheticClock, _SyntheticPackagingEngine, _synthetic_complete_inputs,
)


FIRST = '00000000-0000-4000-8000-000000000001'
SECOND = '00000000-0000-4000-8000-000000000002'


class _ImportableSyntheticEngine(_SyntheticPackagingEngine):
    """Two deterministic score pairs, explicitly synthetic and no estimator."""
    def forecast(self, snapshot, composition, feature_snapshot):
        payload = super().forecast(snapshot, composition, feature_snapshot)
        home = np.tile([3, 5], 2500)
        away = 8 - home
        payload['forecast'].update(schemaVersion='MLB_V18_DAILY_GAME_FORECAST_V1',
            snapshotContentSha256=snapshot['contentSha256'],
            distributions={key: [{'value': int(value), 'probability': count / 5000}
                for value, count in sorted(Counter(values).items())] for key, values in (
                ('homeRuns', home), ('awayRuns', away), ('totalRuns', home + away),
                ('homeMinusAwayRuns', home - away))})
        payload['evidence'].update(providerCalls=0, aispRowsModified=0)
        payload['representativePath']['schemaVersion'] = 'MLB_V18_DAILY_REPRESENTATIVE_PATH_V1'
        return payload


def _setup(tmp_path, monkeypatch, engine):
    monkeypatch.setattr(_SyntheticClock, 'current', datetime(2099, 4, 1, 11, tzinfo=timezone.utc))
    source, destination, progress = (tmp_path / name for name in ('source', 'exchange', 'progress'))
    monkeypatch.setattr(publication, 'datetime', _SyntheticClock)
    monkeypatch.setattr(unattended, 'datetime', _SyntheticClock)
    monkeypatch.setattr(exchange, 'datetime', _SyntheticClock)
    monkeypatch.setattr(publication, 'CurrentV18Engine', lambda: engine)
    monkeypatch.setattr(unattended, 'PUBLICATIONS', source)
    real_export = exchange.export_current_handoff
    monkeypatch.setattr(exchange, 'export_current_handoff', lambda handoff, receipt, **kwargs:
        real_export(handoff, receipt, exchange_root=destination, **kwargs))
    snapshots, compositions = zip(*[_synthetic_complete_inputs(gid) for gid in (FIRST, SECOND)])
    report = {'discovery': {'slateDates': ['2099-04-01']}, 'games': [
        {'gameId': row['game']['game_id'], 'gameDate': '2099-04-01',
         'scheduledStartUtc': row['game']['starts_at'], 'status': 'SKIPPED',
         'reason': 'DUE', 'checkpoint': {'due': True}} for row in snapshots]}
    def callback(detail):
        return unattended.publish_completed_game_handoff(report, detail,
            slate_date='2099-04-01', output_root=progress, publish_exchange=True)
    def run():
        return publication.publish_slate({'capturedAt': snapshots[0]['capturedAt'],
            'snapshots': deepcopy(snapshots)}, deepcopy(compositions), output_root=source,
            on_game_published=callback)
    return source, destination, progress, report, run


def _manifests(destination):
    return [json.loads(path.read_text()) for path in sorted((destination / 'sha256').glob('*/exchange-package.json'))]


def _progress(report):
    return [json.loads(Path(ref['path']).read_text()) for ref in report['incrementalPublications']]


def test_first_game_is_atomically_importable_before_second_inference(tmp_path, monkeypatch):
    engine = _ImportableSyntheticEngine()
    source, destination, progress, report, run = _setup(tmp_path, monkeypatch, engine)
    original = engine.forecast
    first_package = []
    def forecast(snapshot, *args):
        if snapshot['game']['game_id'] == SECOND:
            manifests = _manifests(destination)
            assert len(manifests) == 1 and manifests[0]['forecastCount'] == 1
            first_package.append(deepcopy(manifests[0]))
            handoff = json.loads(Path(manifests[0]['handoff']['path']).read_text())
            assert [row['gameId'] for row in handoff['forecasts']] == [FIRST]
            assert {row['gameId']: row['reason'] for row in handoff['gameAccounting']
                    if row['status'] != 'PUBLISHED'} == {SECOND: 'SEQUENTIAL_FORECAST_NOT_COMPLETED'}
            assert len(list((destination / 'handoff-keys').glob('*/*.json'))) == 1
            assert len(report['incrementalPublications']) == 1
            assert report['games'][1]['reason'] == 'DUE'  # copy-only intermediate accounting
            (tmp_path / 'first-visible-before-second-inference.json').write_text(json.dumps({
                'syntheticTestOnly': True, 'firstExchangeManifest': manifests[0],
                'completedInferenceGameIds': list(engine.calls), 'nextGameId': SECOND,
                'nextInferenceHasStarted': False,
                'incrementalPublications': report['incrementalPublications']}, sort_keys=True))
        return original(snapshot, *args)
    engine.forecast = forecast
    result = run()
    assert engine.calls == [FIRST, SECOND]
    assert result['newForecastCount'] == 2
    assert sorted(item['forecastCount'] for item in _manifests(destination)) == [1, 2]
    later = next(item for item in _manifests(destination) if item['forecastCount'] == 2)
    handoff = json.loads(Path(later['handoff']['path']).read_text())
    assert {row['gameId'] for row in handoff['forecasts']} == {FIRST, SECOND}
    assert first_package[0] in _manifests(destination)
    events = _progress(report)
    assert [event['gameId'] for event in events] == [FIRST, SECOND]
    for event in events:
        assert event['completedObjectIncluded'] is True
        assert event['selectedObjectSha256'] == event['objectSha256']
        assert event['publicationCompletedAtUtc'] <= event['packageExposedAtUtc'] <= event['callbackConfirmedAtUtc']
        assert event['completedToExposureSeconds'] == event['completedToConfirmationSeconds'] == 0
        assert event['slate']['exchange']['providerCalls'] == event['modelFits'] == event['aispWrites'] == 0
        forecast = json.loads((source / 'objects/sha256' / event['objectSha256'] / 'forecast.json').read_text())
        assert forecast['forecastCreatedAt'] == _SyntheticClock.current.isoformat()


def test_active_tick_supplies_callback_before_later_synthetic_inference(tmp_path, monkeypatch):
    from scripts import run_mlb_v18_current_state as runner
    engine = _ImportableSyntheticEngine()
    source, destination, progress, _, _ = _setup(tmp_path, monkeypatch, engine)
    snapshots, compositions = zip(*[_synthetic_complete_inputs(gid) for gid in (FIRST, SECOND)])
    discovery = {'providerCalls': 0, 'slateDates': ['2099-04-01'], 'games': [
        {'gameId': item['game']['game_id'], 'gameDate': '2099-04-01',
         'scheduledStartUtc': item['game']['starts_at'], 'canonicalIdentityResolved': True,
         'status': 'Scheduled'} for item in snapshots]}
    monkeypatch.setattr(unattended, 'discover', lambda *args, **kwargs: deepcopy(discovery))
    monkeypatch.setattr(unattended, 'preflight_participants', lambda due, *args, **kwargs: due)
    monkeypatch.setattr(unattended, 'refresh_history', lambda *args, **kwargs: ('SYNTHETIC', {}))
    monkeypatch.setenv('MLB_V18_DEPLOYED_COMMIT', 'synthetic-commit')
    monkeypatch.setenv('MLB_V18_DEPLOYMENT_MANIFEST_SHA256', 'd' * 64)
    def synthetic_runner(args):
        assert callable(args.on_game_published)
        return publication.publish_slate({'capturedAt': snapshots[0]['capturedAt'],
            'snapshots': deepcopy(snapshots)}, deepcopy(compositions),
            output_root=args.output_root, on_game_published=args.on_game_published)
    monkeypatch.setattr(runner, 'run', synthetic_runner)
    original = engine.forecast
    def forecast(snapshot, *args):
        if snapshot['game']['game_id'] == SECOND:
            assert [item['forecastCount'] for item in _manifests(destination)] == [1]
            assert len(list((progress / 'objects').rglob('incremental-publication.json'))) == 1
        return original(snapshot, *args)
    engine.forecast = forecast
    result = unattended.execute_tick(now=_SyntheticClock.current, state_root=tmp_path / 'state',
        output_root=progress, publish_exchange=True)
    assert result['status'] == 'BOUNDED_TICK_COMPLETED'
    assert engine.calls == [FIRST, SECOND]
    assert len(result['incrementalPublications']) == 2
    assert result['slates'][0]['publishedGames'] == 2
    assert _progress(result)[0]['deploymentIdentity'] == {
        'commit': 'synthetic-commit', 'manifestSha256': 'd' * 64}


def test_older_reused_object_does_not_claim_newer_selected_object_exposure(tmp_path, monkeypatch):
    engine = _ImportableSyntheticEngine()
    source, destination, progress, report, _ = _setup(tmp_path, monkeypatch, engine)
    snapshot, composition = _synthetic_complete_inputs(FIRST)
    first = publication.publish_composed_game(snapshot, composition, output_root=source, engine=engine)
    _SyntheticClock.current += timedelta(minutes=1)
    changed = deepcopy(composition)
    changed['rows'][0][publication.load_contract()['rawFeatureColumns'][-1]] += 1
    refreshed_snapshot = deepcopy(snapshot)
    refreshed_snapshot['capturedAt'] = '2099-04-01T10:01:00+00:00'
    changed['sourceCutoff'] = refreshed_snapshot['capturedAt']
    second = publication.publish_composed_game(refreshed_snapshot, changed, output_root=source, engine=engine)
    assert second['objectSha256'] != first['objectSha256']
    reused = publication.publish_composed_game(snapshot, composition, output_root=source, engine=engine)
    assert reused['objectSha256'] == first['objectSha256']
    reused['publicationCompletedAtUtc'] = _SyntheticClock.current.isoformat()
    unattended.publish_completed_game_handoff(report, reused, slate_date='2099-04-01',
        output_root=progress, publish_exchange=True)
    event = _progress(report)[0]
    assert event['completedObjectIncluded'] is False
    assert event['selectedObjectSha256'] == second['objectSha256']
    assert event['packageExposedAtUtc'] is not None
    assert event['completedToExposureSeconds'] is event['createdToExposureSeconds'] is None


def test_interruption_leaves_first_prefix_and_restart_reuses_original_bytes(tmp_path, monkeypatch):
    engine = _ImportableSyntheticEngine()
    source, destination, progress, report, run = _setup(tmp_path, monkeypatch, engine)
    original = engine.forecast
    def interrupted(snapshot, *args):
        if snapshot['game']['game_id'] == SECOND:
            raise KeyboardInterrupt('synthetic process interruption')
        return original(snapshot, *args)
    engine.forecast = interrupted
    with pytest.raises(KeyboardInterrupt):
        run()
    first_event = _progress(report)[0]
    first_path = source / 'objects/sha256' / first_event['objectSha256'] / 'forecast.json'
    original_bytes = first_path.read_bytes()
    original_package = _manifests(destination)[0]
    assert original_package['forecastCount'] == 1
    assert len(list((progress / 'objects').rglob('*incremental-publication.json'))) == 1
    engine.forecast = original
    result = run()
    assert engine.calls == [FIRST, SECOND]  # FIRST never reruns inference
    assert result['games'][0]['status'] == 'UNCHANGED_NUMERICAL_FORECAST_REUSED'
    assert first_path.read_bytes() == original_bytes
    assert original_package in _manifests(destination)
    assert _progress(report)[1]['packageExposedAtUtc'] is None
    assert _progress(report)[1]['slate']['exchange']['reused'] is True


def test_copy_interruption_keeps_incomplete_second_package_hidden(tmp_path, monkeypatch):
    engine = _ImportableSyntheticEngine()
    source, destination, progress, report, run = _setup(tmp_path, monkeypatch, engine)
    real_copy = exchange.shutil.copyfile
    def fail_second_export(src, dest):
        if any(row['gameId'] == SECOND for row in publication.daily.collect_slate_forecasts(source, date(2099, 4, 1))):
            Path(dest).write_bytes(b'partial synthetic copy')
            raise OSError('synthetic interrupted dependency copy')
        return real_copy(src, dest)
    monkeypatch.setattr(exchange.shutil, 'copyfile', fail_second_export)
    with pytest.raises(OSError, match='interrupted dependency'):
        run()
    assert [item['forecastCount'] for item in _manifests(destination)] == [1]
    assert len(list((destination / 'handoff-keys').glob('*/*.json'))) == 1
    assert not list((destination / '.staging').iterdir())
    assert [event['gameId'] for event in _progress(report)] == [FIRST]
    assert len(publication.daily.collect_slate_forecasts(source, date(2099, 4, 1))) == 2


def test_callback_failure_is_not_relabelled_or_swallowed_before_later_inference(tmp_path, monkeypatch):
    engine = _ImportableSyntheticEngine()
    source, _, _, _, _ = _setup(tmp_path, monkeypatch, engine)
    inputs = [_synthetic_complete_inputs(gid) for gid in (FIRST, SECOND)]
    def fail(_detail):
        raise RuntimeError('synthetic exchange rejection')
    with pytest.raises(RuntimeError, match='exchange rejection'):
        publication.publish_slate({'capturedAt': inputs[0][0]['capturedAt'],
            'snapshots': [item[0] for item in inputs]}, [item[1] for item in inputs],
            output_root=source, on_game_published=fail)
    assert engine.calls == [FIRST]
    assert [row['gameId'] for row in publication.daily.collect_slate_forecasts(source, date(2099, 4, 1))] == [FIRST]


def test_unsupported_game_never_enters_publication_callback(tmp_path, monkeypatch):
    snapshot, composition = _synthetic_complete_inputs('BLOCKED')
    composition.update(canSimulate=False, blockers=[{'reason': 'MISSING_SOURCE'}])
    def forbidden(*args):
        raise AssertionError('unsupported game invoked inference/publication callback')
    monkeypatch.setattr(publication, 'CurrentV18Engine', forbidden)
    result = publication.publish_slate({'capturedAt': snapshot['capturedAt'], 'snapshots': [snapshot]},
        [composition], output_root=tmp_path, on_game_published=forbidden)
    assert result['games'][0]['status'] == 'SKIPPED'
