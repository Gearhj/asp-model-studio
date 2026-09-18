"""Synthetic-only tests for retained paper-window authority; no network/model fits."""
import copy
import json
from pathlib import Path
import uuid

import pytest

from server.sports_cfb_gen1.lifecycle import (
    POLICY, canonical_bytes, immutable, object_json, read_ref, revision_key, tick,
)


@pytest.fixture
def setup():
    root = Path(__file__).resolve().parents[1] / 'outputs/cfb-retained-eligibility-fixtures' / uuid.uuid4().hex
    root.mkdir(parents=True)
    plan = object_json(root / 'plan', {'validFromUtc': '2030-10-01T00:00:00Z', 'validUntilUtc': '2030-11-01T00:00:00Z'})
    grant = {
        'schema': 'CFB_VIRTUAL_POLICY_EXTENSION_AUTHORIZATION_V1', 'approvedBy': 'James',
        'consumerVirtualExperimentAuthorized': True, 'realMoneyAuthorized': False,
        'modelPromotionAuthorized': False, 'modelConfiguration': 'CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1',
        'planSha256': plan['sha256'], 'retainedAtUtc': '2030-10-01T00:00:00Z',
        'validUntilUtc': '2030-11-01T00:00:00Z',
        'policyAuthorization': {'mode': 'VIRTUAL_RESEARCH_ONLY', 'realMoneyExecutionAllowed': False},
    }
    release = {'prospectiveEffectiveAtUtc': '2030-10-01T00:00:00Z', 'refreshPlan': plan,
               'predictionReleaseIdentity': 'unchanged-synthetic-numerical-release',
               'paperEligibilityAuthorization': object_json(root / 'grant', grant)}
    bundle = {'schema': 'CFB_GEN1_SLATE_INPUT_V1', 'classification': 'SYNTHETIC_TEST_ONLY',
              'scheduleCapturedAtUtc': '2030-10-21T23:00:00Z', 'historyCompleteThroughUtc': '2030-10-21T23:00:00Z',
              'historyMissingGameIds': [], 'games': [{'gameId': '1', 'predictionInputIdentity': 'unchanged-inputs',
              'target': {'game_id': 1, 'scheduled_at': '2030-10-22T00:00:00Z', 'status': 'SCHEDULED'}}]}
    calls = {'render': 0, 'verify': 0}
    def render(row, br, rr, key, path):
        calls['render'] += 1
        immutable(path / 'index.json', canonical_bytes({'schema': 'SYNTHETIC_ONLY', 'revisionKey': key,
                  'forecastId': 'synthetic:' + key, 'gameId': 1}))
        return path
    def verify(path):
        calls['verify'] += 1
        value = json.loads((path / 'index.json').read_bytes())
        assert value['schema'] == 'SYNTHETIC_ONLY'
        return value
    def run(stamp, b=None, r=None, renderer=render, clock=None, fault=None):
        return tick(bundle_ref=object_json(root / 'input', b or bundle), release_ref=object_json(root / 'release', r or release),
                    state_root=root / 'state', exchange_root=root / 'exchange', renderer=renderer, verifier=verify,
                    clock=clock or (lambda: stamp), fault=fault)[0]
    return root, bundle, release, grant, calls, run


@pytest.mark.parametrize('minute,eligible', [('29', True), ('30', True), ('31', True), ('44', True), ('45', False)])
def test_T31_T30_T29_T16_T15_preserves_original_publication(setup, minute, eligible):
    root, _, release, _, calls, run = setup
    original = run('2030-10-21T23:29:00Z')
    saved = original['games'][0]['package']
    committed = (root / 'state/committed' / (saved['revisionKey'] + '.json'))
    before = committed.read_bytes()
    result = run('2030-10-21T23:' + minute + ':00Z')
    assert result['games'][0]['currentlyEligible'] is eligible
    assert calls['render'] == 1 and committed.read_bytes() == before
    package = read_ref(result['discovery'])['packages'][0]
    assert package['currentlyEligible'] is eligible
    assert package['committedAtUtc'] == '2030-10-21T23:29:00Z'
    if eligible:
        assert package['eligibilityAuthority'] == 'VIRTUAL_RESEARCH_ONLY'
        assert package['paperEligibilityAuthorization'] == release['paperEligibilityAuthorization']
        assert package['eligibilityValidUntilUtc'] <= '2030-10-21T23:45:00+00:00'
    if minute == '29':
        assert package['eligibilityValidUntilUtc'] == '2030-10-21T23:44:00+00:00'


@pytest.mark.parametrize('stamp,status', [('2030-10-22T00:00:00Z', 'SCHEDULED'),
                                        ('2030-10-21T23:31:00Z', 'FINAL')])
def test_started_or_completed_never_get_authority(setup, stamp, status):
    _, bundle, _, _, calls, run = setup
    run('2030-10-21T23:29:00Z')
    changed = copy.deepcopy(bundle); changed['games'][0]['target']['status'] = status
    before = calls['verify']
    result = run(stamp, b=changed)
    assert not result['games'][0]['currentlyEligible']
    assert calls['verify'] == before and calls['render'] == 1


def test_without_authorization_retains_T30_cutoff(setup):
    _, _, release, _, calls, run = setup
    legacy = dict(release); legacy.pop('paperEligibilityAuthorization')
    original = run('2030-10-21T23:29:00Z', r=legacy)
    assert original['games'][0]['eligibilityValidUntilUtc'] == '2030-10-21T23:30:00+00:00'
    result = run('2030-10-21T23:30:00Z', r=legacy)
    assert result['games'][0]['disposition'] == 'PUBLICATION_CUTOFF_PASSED'
    assert calls['render'] == 1


def test_grant_expiry_caps_lease_and_refuses_later_reuse(setup):
    root, _, release, grant, calls, run = setup
    grant['validUntilUtc'] = '2030-10-21T23:40:00Z'
    release = dict(release, paperEligibilityAuthorization=object_json(root / 'grant', grant))
    run('2030-10-21T23:29:00Z', r=release)
    active = run('2030-10-21T23:30:00Z', r=release)
    assert active['games'][0]['eligibilityValidUntilUtc'] == '2030-10-21T23:40:00+00:00'
    expired = run('2030-10-21T23:40:00Z', r=release)
    assert not expired['games'][0]['currentlyEligible'] and calls['render'] == 1


@pytest.mark.parametrize('change,expected', [('stale', 'STALE_INPUT_REJECTED'),
                                          ('identity', 'INPUTS_PENDING'), ('missing', 'HISTORY_INCOMPLETE')])
def test_freshness_identity_history_checked_before_any_reuse(setup, change, expected):
    _, bundle, _, _, calls, run = setup
    run('2030-10-21T23:29:00Z')
    changed = copy.deepcopy(bundle)
    if change == 'stale': changed['scheduleCapturedAtUtc'] = '2030-10-21T21:00:00Z'
    if change == 'identity': changed['games'][0]['inputBlockers'] = ['UNKNOWN_SCHOOL_ID']
    if change == 'missing': changed['historyMissingGameIds'] = ['2']
    before = calls['verify']
    result = run('2030-10-21T23:31:00Z', b=changed)
    assert result['games'][0]['disposition'] == expected
    assert calls['verify'] == before and calls['render'] == 1


def test_changed_input_revision_cannot_render_after_cutoff(setup):
    _, bundle, _, _, calls, run = setup
    run('2030-10-21T23:29:00Z')
    changed = copy.deepcopy(bundle); changed['games'][0]['predictionInputIdentity'] = 'different-features'
    result = run('2030-10-21T23:31:00Z', b=changed)
    assert result['games'][0]['disposition'] == 'RETAINED_FORECAST_UNAVAILABLE'
    assert not read_ref(result['discovery'])['packages'][0]['currentlyEligible']
    assert calls['render'] == 1


@pytest.mark.parametrize('stamp', ['2030-10-21T23:30:00Z', '2030-10-21T23:31:00Z'])
def test_no_committed_revision_cannot_create_one_after_cutoff(setup, stamp):
    _, _, _, _, calls, run = setup
    result = run(stamp)
    assert result['games'][0]['disposition'] == 'RETAINED_FORECAST_UNAVAILABLE'
    assert read_ref(result['discovery'])['packages'] == [] and calls['render'] == 0


def test_publication_at_exact_cutoff_is_not_eligible_proof(setup):
    root, _, _, _, calls, run = setup
    first = run('2030-10-21T23:29:00Z')
    package = first['games'][0]['package']
    package['committedAtUtc'] = '2030-10-21T23:30:00Z'
    (root / 'state/committed' / (package['revisionKey'] + '.json')).write_bytes(canonical_bytes(package))
    result = run('2030-10-21T23:31:00Z')
    assert result['games'][0]['disposition'] == 'GAME_FAILED'
    assert not result['games'][0]['currentlyEligible'] and calls['render'] == 1


def test_authorized_render_crossing_cutoff_cannot_publish(setup):
    _, _, _, _, calls, run = setup
    stamp = ['2030-10-21T23:29:00Z']
    def render(row, br, rr, key, path):
        calls['render'] += 1
        immutable(path / 'index.json', canonical_bytes({'schema': 'SYNTHETIC_ONLY', 'revisionKey': key,
                  'forecastId': 'synthetic:' + key, 'gameId': 1}))
        stamp[0] = '2030-10-21T23:31:00Z'
        return path
    result = run(None, renderer=render, clock=lambda: stamp[0])
    assert result['games'][0]['disposition'] == 'PUBLICATION_CUTOFF_PASSED'
    assert read_ref(result['discovery'])['packages'] == []


def test_operational_authorization_does_not_change_POLICY_or_revision_key(setup):
    root, bundle, release, _, _, _ = setup
    original = dict(release); original.pop('paperEligibilityAuthorization')
    br = object_json(root / 'input', bundle)
    assert revision_key(bundle['games'][0], br, object_json(root / 'release', original)) == revision_key(
        bundle['games'][0], br, object_json(root / 'release', release))
    assert POLICY['lastPublicationMinutesBeforeKickoff'] == 30
    assert POLICY['cadenceMinutes'] == 15
