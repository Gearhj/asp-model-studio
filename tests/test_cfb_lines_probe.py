import json
from pathlib import Path

import pytest

from server.sports_cfb_gen1 import lines_probe as module
from server.sports_cfb_gen1.lifecycle import immutable
from server.sports_cfb_gen1.publication_io import canonical_bytes, reference
from server.sports_cfb_gen1.refresh import usage_snapshot


def write(path, value):
    return immutable(path, canonical_bytes(value))


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    capture = state / 'capture'
    prior = capture / 'attempts' / 'natural'
    info = write(prior / 'raw' / 'info' / 'response.json',
                 {'remainingCalls': 900, 'monthlyLimit': 1000, 'sharedPool': True})
    manifest = write(prior / 'manifest.json', {'requests': [dict(info, endpoint='/info', acquiredAt='2026-09-18T18:00:10Z')]})
    before = write(prior / 'completion.json', dict(disposition='CAPTURED', sourceManifest=manifest,
                   startedAtUtc='2026-09-18T18:00:00Z', completedAtUtc='2026-09-18T18:00:10Z',
                   providerCalls=4, providerBytes=1000))
    write(prior / 'started.json', {'startedAtUtc': '2026-09-18T18:00:00Z'})
    write(capture / 'active.json', {'status': 'ADMITTED'})
    carry = write(tmp_path / 'carried.json', dict(startedAtUtc='2026-09-18T15:55:00Z',
                  completedAtUtc='2026-09-18T15:56:00Z', providerCalls=7, providerBytes=3892030))
    plan = dict(maxRequests=7, maxResponseBytes=25 * 1024**2, maxRequestsPerUtcDay=28,
                maxRequestsForPeriodIncludingCarryForward=200, maxResponseBytesPerUtcDay=100 * 1024**2,
                maxRetainedBytes=2 * 1024**3, carryForwardCaptureReceipts=[carry])
    plan_ref = write(tmp_path / 'plan.json', plan)
    approval = write(tmp_path / 'approval.txt', {'text': 'Synthetic test authorization'})
    grant = write(tmp_path / 'probe-grant.json', dict(approvedBy='James', request=module.ASSET,
                  maxRequests=1, maxResponseBytes=module.MAX_BYTES, retryCount=0, maxCostUsd=0,
                  planSha256=plan_ref['sha256'], authorizationEvidence=approval))
    monkeypatch.setattr(module, 'validate_grant', lambda *args: plan)
    args = dict(state_root=state, plan_ref=plan_ref, grant_ref={}, deployment='synthetic',
                probe_grant_ref=grant, entitlement_receipt_ref=before, env_file='unused',
                clock=lambda: '2026-09-18T18:01:00Z')
    return args, plan


def success(counter):
    def transport(asset, headers, limit, meter):
        counter.append(asset)
        assert asset == module.ASSET and headers == {} and limit == module.MAX_BYTES
        raw = canonical_bytes([{'id': 1, 'homeTeamId': 2, 'awayTeamId': 3,
               'homeTeam': 'Home', 'awayTeam': 'Away', 'startDate': '2026-09-19T18:00:00Z',
               'lines': [{'provider': 'Book', 'homeMoneyline': -120, 'awayMoneyline': 100,
                          'spread': -1.5, 'overUnder': 50.5}]}])
        meter(len(raw))
        return 200, {'content-type': 'application/json'}, raw
    return transport


def test_one_request_receipt_reuse_and_shared_accounting(fixture):
    args, plan = fixture
    calls = []
    args['transport_factory'] = lambda: success(calls)
    result = module.probe(**args)
    assert result['disposition'] == 'CAPTURED_LINES_PROBE'
    assert result['findings']['quoteTimestampCandidateFields'] == []
    assert result['findings']['marketPeriodOrOvertimeCandidateFields'] == []
    assert result['findings']['schoolIdsComplete']
    assert module.probe(**args)['invocationDisposition'] == 'REUSED_RETAINED_NO_NETWORK'
    assert len(calls) == 1
    usage = usage_snapshot(args['state_root'] / 'capture', plan, args['clock']())
    assert usage['periodRequestsIncludingCarryForward'] == usage['utcDayRequests'] == 12
    assert usage['periodBytesIncludingCarryForward'] == 3893030 + result['providerBytes']


def test_transport_failure_is_counted_and_not_retried(fixture):
    args, plan = fixture
    def fail(*_):
        raise RuntimeError('Untrusted error with potentially sensitive transport text')
    args['transport_factory'] = lambda: fail
    result = module.probe(**args)
    assert result['providerCalls'] == 1 and result['disposition'] == 'STOPPED_FAILED_CLOSED'
    assert 'Untrusted' not in json.dumps(result)
    with pytest.raises(RuntimeError, match='NO_RETRY'):
        module.probe(**args)
    assert usage_snapshot(args['state_root'] / 'capture', plan, args['clock']())['utcDayRequests'] == 12


def test_interrupted_probe_is_never_repeated_and_counts_conservatively(fixture):
    args, plan = fixture
    write(args['state_root'] / 'capture' / 'attempts' / module.ATTEMPT / 'started.json',
          {'startedAtUtc': '2026-09-18T18:00:30Z'})
    with pytest.raises(RuntimeError, match='INTERRUPTED_NO_RETRY'):
        module.probe(**args)
    usage = usage_snapshot(args['state_root'] / 'capture', plan, args['clock']())
    assert usage['utcDayRequests'] == 18
    assert usage['utcDayBytes'] == 3893030 + plan['maxResponseBytes']


@pytest.mark.parametrize('field,value,reason', [
    ('maxRequestsPerUtcDay', 11, 'UTC_DAY_REQUEST_BUDGET'),
    ('maxRequestsForPeriodIncludingCarryForward', 11, 'PERIOD_REQUEST_BUDGET'),
    ('maxResponseBytesPerUtcDay', 3893030, 'UTC_DAY_BYTE_BUDGET'),
    ('maxRetainedBytes', 1, 'RETAINED_STORAGE_BUDGET'),
])
def test_budget_stops_before_transport(fixture, field, value, reason):
    args, plan = fixture
    plan[field] = value
    with pytest.raises(ValueError, match=reason):
        module.probe(**args)
    assert not (args['state_root'] / 'capture' / 'attempts' / module.ATTEMPT).exists()


def test_old_entitlement_requires_fresh_natural_owner_capture(fixture):
    args, _ = fixture
    args['clock'] = lambda: '2026-09-18T19:01:00Z'
    with pytest.raises(ValueError, match='FRESH_OWNER_ENTITLEMENT_REQUIRED'):
        module.probe(**args)


def test_byte_limit_failure_is_metered_and_never_retried(fixture):
    args, _ = fixture
    def exceed(asset, headers, limit, meter):
        meter(limit)
        meter(1)
    args['transport_factory'] = lambda: exceed
    result = module.probe(**args)
    assert result['providerBytes'] == module.MAX_BYTES
    assert result['disposition'] == 'STOPPED_FAILED_CLOSED'
    with pytest.raises(RuntimeError, match='NO_RETRY'):
        module.probe(**args)
