"""Synthetic lifecycle cases only; never provider data or forecasting evidence."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

import pytest

from server.sports_nba_gen1.authority import reference
from server.sports_nba_gen1.production import canonical_bytes, digest
from server.sports_nba_gen1.slate_inputs import classify
from server.sports_nba_gen1.slate_lifecycle import (
    POLICY, eligibility, immutable, object_json, owner_lock, read_ref, tick,
)


@pytest.fixture
def space():
    # No pytest tmp_path/0700 Windows ACL mutation.
    p = Path(__file__).resolve().parents[1] / 'outputs/nba-slate-fixture-tests' / uuid.uuid4().hex
    p.mkdir(parents=True)
    return p


def row(gid=1):
    return {'gameId': f'synthetic:{gid}', 'target': {'game_id': f'synthetic:{gid}',
        'scheduled_tipoff_utc': '2030-10-22T00:00:00+00:00', 'status': 'SCHEDULED'}}


def env(space, count=3):
    b = {'schema': 'NBA_GEN1_SLATE_INPUT_V1', 'classification': 'SYNTHETIC_TEST_ONLY',
         'scheduleCapturedAtUtc': '2030-10-21T00:00:00+00:00',
         'historyCompleteThroughUtc': '2030-10-21T00:00:00+00:00',
         'games': [row(i) for i in range(count)], 'historyMissingGameIds': []}
    r = {'prospectiveEffectiveAtUtc': '2030-01-01T00:00:00+00:00'}
    return b, object_json(space / 'input', b), object_json(space / 'release', r)


class Renderer:
    def __init__(self):
        self.calls = 0
        self.fail = set()

    def __call__(self, row, bundle, release, key, path):
        self.calls += 1
        if row['gameId'] in self.fail:
            raise ValueError('Synthetic isolated game failure')
        folder = path / 'complete'
        index = {'schemaVersion': 'SYNTHETIC_PACKAGE_ONLY', 'forecastId': key,
                 'publishedAtUtc': None, 'revisionKey': key, 'game': row['target']}
        immutable(folder / 'index.json', canonical_bytes(index))
        return folder


def verifier(path):
    index = json.loads((path / 'index.json').read_bytes())
    assert index['schemaVersion'] == 'SYNTHETIC_PACKAGE_ONLY'
    return index


def run(space, bundle, release, renderer, stamp='2030-10-21T02:00:00+00:00', fault=None):
    return tick(bundle_ref=bundle, release_ref=release, state_root=space / 'state',
        exchange_root=space / 'fixture-exchange', renderer=renderer, verifier=verifier,
        clock=lambda: stamp, fault=fault)[0]


def test_multi_game_idempotency_and_discovery_preserves_every_revision(space):
    b, br, rr = env(space)
    render = Renderer()
    first = run(space, br, rr, render)
    assert first['disposition'] == 'PUBLISHED'
    assert render.calls == 3
    indexes = [g['package']['index'] for g in first['games']]
    again = run(space, br, rr, render)
    assert again['disposition'] == 'REUSED_IMMUTABLE' and render.calls == 3
    assert [g['package']['index'] for g in again['games']] == indexes
    b['scheduleCapturedAtUtc'] = '2030-10-21T01:00:00+00:00'
    b2 = object_json(space / 'input', b)
    changed = run(space, b2, rr, render)
    assert render.calls == 6
    discovery = read_ref(changed['discovery'])
    assert len(discovery['packages']) == 6
    assert sum(p['currentlyEligible'] for p in discovery['packages']) == 3
    assert discovery['predecessor'] == again['discovery']


def test_freshness_and_post_tipoff_are_checked_before_reuse(space):
    _, br, rr = env(space, 1)
    render = Renderer()
    run(space, br, rr, render)
    stale = run(space, br, rr, render, '2030-10-21T23:00:00+00:00')
    assert stale['games'][0]['disposition'] == 'STALE_INPUT_REJECTED'
    assert not read_ref(stale['discovery'])['packages'][0]['currentlyEligible']
    late = run(space, br, rr, render, '2030-10-22T00:01:00+00:00')
    assert late['games'][0]['disposition'] == 'POST_TIPOFF_REJECTED'
    assert render.calls == 1


@pytest.mark.parametrize('phase', ['prepared', 'published'])
def test_interruption_recovery_does_not_resimulate_or_erase_success(space, phase):
    _, br, rr = env(space)
    render = Renderer()
    def fault(stage, gid):
        if stage == phase and gid == 'synthetic:1':
            raise RuntimeError('Synthetic interruption')
    failed = run(space, br, rr, render, fault=fault)
    assert failed['exitCode'] == 1
    assert len(read_ref(failed['discovery'])['packages']) == 2
    recovered = run(space, br, rr, render)
    assert recovered['exitCode'] == 0 and render.calls == 3
    assert len(read_ref(recovered['discovery'])['packages']) == 3


def test_isolated_failure_does_not_hide_game_or_erase_other_packages(space):
    _, br, rr = env(space)
    render = Renderer()
    render.fail.add('synthetic:1')
    result = run(space, br, rr, render)
    assert [g['disposition'] for g in result['games']] == ['PUBLISHED_NEW_PROSPECTIVE', 'GAME_FAILED', 'PUBLISHED_NEW_PROSPECTIVE']
    assert len(read_ref(result['discovery'])['packages']) == 2
    assert list((space / 'state/runner-receipts/sha256').glob('*/receipt.json'))


def test_not_due_status_changed_and_cutoff_semantics(space):
    b, br, rr = env(space, 1)
    render = Renderer()
    assert run(space, br, rr, render, '2030-10-10T02:00:00+00:00')['disposition'] == 'NOT_DUE'
    b['games'][0]['target']['status'] = 'STATUS_POSTPONED'
    br2 = object_json(space / 'input', b)
    assert run(space, br2, rr, render)['games'][0]['disposition'] == 'GAME_NOT_SCHEDULED'
    assert run(space, br, rr, render, '2030-10-21T23:30:00+00:00')['games'][0]['disposition'] == 'PUBLICATION_CUTOFF_PASSED'
    assert render.calls == 0


def test_due_crosses_deadline_during_render_is_not_published(space):
    b, br, rr = env(space, 1)
    b['scheduleCapturedAtUtc'] = b['historyCompleteThroughUtc'] = '2030-10-21T23:00:00+00:00'
    br = object_json(space / 'input', b)
    calls = [0]
    def clock():
        calls[0] += 1
        return '2030-10-21T23:29:00+00:00' if calls[0] <= 2 else '2030-10-21T23:31:00+00:00'
    result, _ = tick(bundle_ref=br, release_ref=rr, state_root=space / 'state', exchange_root=space / 'fixture-exchange',
        renderer=Renderer(), verifier=verifier, clock=clock)
    assert result['games'][0]['disposition'] == 'PUBLICATION_CUTOFF_PASSED'
    assert read_ref(result['discovery'])['packages'] == []


def test_no_concurrent_owner_and_tamper_rejected(space):
    _, br, rr = env(space, 1)
    with owner_lock(space / 'state/publisher.lock'):
        result = run(space, br, rr, Renderer())
    assert result['disposition'] == 'FAILED' and result['reason'] == 'OWNER_BUSY'
    Path(br['path']).write_bytes(b'{}')
    assert run(space, br, rr, Renderer())['disposition'] == 'FAILED'


def test_identity_orientation_and_dst_metadata():
    import pandas as pd
    from server.sports_nba_gen1.current_history_source import TEAM_IDENTITIES
    h, a = TEAM_IDENTITIES[8], TEAM_IDENTITIES[2]
    r = dict(id=401909088, game_id=401909088, date='2026-11-02T01:00:00Z', game_date='2026-11-01', season=2027,
        season_type=2, type_id=1, type_abbreviation='STD', neutral_site=False, status_type_name='STATUS_SCHEDULED',
        status_type_state='pre', status_type_completed=False, home_id=8, away_id=2,
        home_abbreviation=h[0], home_display_name=h[2], away_abbreviation=a[0], away_display_name=a[2])
    rows, _, _, _ = classify(pd.DataFrame([r]), 'a'*64)
    assert rows[0]['target']['home_team_code'] == 'DET'
    assert rows[0]['target']['away_team_code'] == 'BOS'  # Not excluded for owning an old research artifact.
    with pytest.raises(ValueError):
        classify(pd.DataFrame([r, r]), 'a'*64)
    r['game_date'] = '2026-11-02'
    with pytest.raises(ValueError):
        classify(pd.DataFrame([r]), 'a'*64)


def test_no_network_refresh_default(monkeypatch, capsys):
    import importlib.util
    p = Path(__file__).resolve().parents[1] / 'scripts/capture_nba_slate_refresh.py'
    spec = importlib.util.spec_from_file_location('refresh', p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr('sys.argv', ['refresh'])
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *a: pytest.fail('network forbidden'))
    module.main()
    assert json.loads(capsys.readouterr().out)['authority'] == 'AWAITING_EXPLICIT_REFRESH_AUTHORIZATION'


def test_real_renderer_with_synthetic_point_and_residuals(space, monkeypatch):
    import numpy as np
    import pandas as pd
    from server.sports_nba_gen1 import slate_render as sr
    from server.sports_nba_gen1.joint_residual import ENGINE, MASTER_SEED
    from server.sports_nba_gen1.production import CONFIGURATION
    target = {'game_id': 'synthetic:only', 'source_game_id': 'synthetic', 'status': 'SCHEDULED',
        'game_date': '2099-01-01', 'scheduled_tipoff_utc': '2099-01-01T23:00:00+00:00',
        'home_team_id': 'synthetic:home', 'away_team_id': 'synthetic:away', 'home_team_code': 'SYN_H', 'away_team_code': 'SYN_A'}
    bank = pd.DataFrame({'residual_home': np.arange(500)%15-7, 'residual_away': np.arange(500)%19-9})
    bank.to_parquet(space/'synthetic-residuals.parquet', index=False)
    method = object_json(space/'method', {'engine': ENGINE, 'masterSeed': MASTER_SEED, 'drawCountPerGamePerArm': 10000,
                                        'residuals': reference(space/'synthetic-residuals.parquet')})
    fake = object_json(space/'fake', {'only': 'SYNTHETIC_TEST'})
    current = object_json(space/'model', {'models': {'ridge_a100_rest': {'artifact': fake}, 'elo': {'artifact': fake}}})
    coverage = object_json(space/'coverage', {})
    br = object_json(space/'bundle', {'reviewedBy': 'SYNTHETIC_TEST', 'source': fake, 'rightsEvidence': [fake],
        'scheduleCapturedAtUtc': '2026-09-01T00:00:00Z', 'sourceCutoffUtc': '2026-09-01T00:00:00Z',
        'coverageTemplate': coverage, 'currentModelReceipt': current})
    rr = object_json(space/'release', {'jointMethod': method, 'deploymentManifest': fake, 'modelHandoff': fake,
                                      'prospectiveEffectiveAtUtc': '2026-09-01T00:00:00Z'})
    monkeypatch.setattr(sr, 'eligible_bank', lambda *a: bank)
    monkeypatch.setattr(sr, 'build_point_forecast', lambda *a: {'configurationIdentity': CONFIGURATION,
        'sourceCutoffUtc': '2026-09-01T00:00:00Z', 'game': target,
        'pointExpectations': {'home': 112., 'away': 108., 'total': 220., 'homeMargin': 4.},
        'winnerProbabilities': {'home': .6, 'away': .4, 'tie': 0.},
        'bindings': {'featureContractSha256': 'synthetic', 'pointTrainingIdentitySha256': 'synthetic'}})
    directory = sr.render({'target': target}, br, rr, 'test-key', space/'build')
    result = sr.verify_package(directory)
    assert result['drawCount'] == 10000 and result['publishedAtUtc'] is None
    forecast = json.loads((directory/'forecast.json').read_bytes())
    assert forecast['eloWinnerProbabilities']['home'] == .6
    assert forecast['jointSimulation']['drawCount'] == 10000
    assert not forecast['closeScoreChallenger']['enabled']


def test_offline_input_update_preserves_models_and_applies_final_corrections(space):
    import pandas as pd
    from server.sports_nba_gen1.slate_inputs import admit
    from server.sports_nba_gen1.production import CONFIGURATION
    from server.sports_nba_gen1.current_history_source import TEAM_IDENTITIES
    fake = object_json(space/'fixture-only', {'classification': 'SYNTHETIC_ONLY_NOT_SOURCE_AUTHORITY'})
    history = pd.DataFrame([{'game_id': 'synthetic-prior', 'game_date': '2026-04-01', 'season_end': 2026,
        'home_team_id': 'nba-neil:franchise:DET', 'away_team_id': 'nba-neil:franchise:BOS',
        'home_score': 100, 'away_score': 99}])
    history.to_parquet(space/'history.parquet', index=False)
    context = object_json(space/'context', {'contextOnlyEvents': []})
    models = {'unchanged': 'SYNTHETIC_MODEL_TOKEN'}
    base = object_json(space/'base', {'configurationIdentity': CONFIGURATION, 'models': models,
        'history': {'games': reference(space/'history.parquet'), 'contextMetadata': context, 'acquisition': fake}})
    coverage = object_json(space/'coverage', {'currentResearchReceiptSha256': base['sha256'],
        'regularSeasonMembershipComplete': True, 'missingGameIds': [], 'completeThroughUtc': '2026-09-01T00:00:00Z',
        'evidence': [fake], 'sourceCaptures': []})
    h, a = TEAM_IDENTITIES[8], TEAM_IDENTITIES[2]
    def capture(score, stamp):
        path = space / ('source-' + str(score) + '.parquet')
        pd.DataFrame([dict(id=99, game_id=99, date='2026-09-16T23:00:00Z', game_date='2026-09-16', season=2027,
            season_type=2, type_id=1, type_abbreviation='STD', neutral_site=False,
            status_type_name='STATUS_FINAL', status_type_state='post', status_type_completed=True,
            home_id=8, away_id=2, home_abbreviation=h[0], home_display_name=h[2], away_abbreviation=a[0], away_display_name=a[2],
            home_score=score, away_score=100)]).to_parquet(path,index=False)
        return object_json(space/'capture', {'schema': 'NBA_GOVERNED_SCHEDULE_CAPTURE_V1',
            'source': reference(path), 'capturedAtUtc': stamp, 'httpStatus': 200})
    first = capture(110, '2026-09-17T01:00:00Z')
    kw = dict(base_model_ref=base, base_coverage_ref=coverage, rights_refs=[fake],
              registry_root=space/'registry', season_end=2027, reviewed_by='SYNTHETIC_TEST_ONLY')
    one = admit(capture_ref=first, **kw)
    assert admit(capture_ref=first, **kw) == one
    two = admit(capture_ref=capture(111, '2026-09-17T02:00:00Z'), **kw)
    assert read_ref(two)['predecessor'] == one
    current = read_ref(read_ref(two)['currentModelReceipt'])
    assert current['models'] == models
    updated = pd.read_parquet(current['history']['games']['path'])
    assert len(updated) == 2 and updated.loc[updated.game_id.eq('nba-espn:game:99'), 'home_score'].iloc[0] == 111
    assert pd.read_parquet(read_ref(read_ref(one)['currentModelReceipt'])['history']['games']['path']).home_score.iloc[-1] == 110
    with pytest.raises(ValueError, match='regression'):
        admit(capture_ref=first, **kw)
    pointer_before=(space/'registry/current.json').read_bytes()
    with pytest.raises(ValueError, match='Precommit rejection'):
        admit(capture_ref=capture(112, '2026-09-17T03:00:00Z'), **kw,
              precommit=lambda b: (_ for _ in ()).throw(ValueError('Precommit rejection')))
    assert (space/'registry/current.json').read_bytes()==pointer_before
