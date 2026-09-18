"""Single authorized CFBD lines validation, sharing the publisher's lock/budget.

This module is deliberately not part of the recurring deployment. It never
publishes forecasts, changes input pointers or grants quote/decision authority.
"""
from datetime import timedelta
import json
from pathlib import Path

from .capture import HttpTransport, entitlement, schema_profile, validate_grant
from .lifecycle import immutable, now, owner_lock, read_ref, utc, atomic_json
from .publication_io import canonical_bytes, digest, reference, verified_bytes
from .refresh import usage_snapshot

ASSET = {
    'endpoint': '/lines',
    'parameters': {'year': 2026, 'week': 4, 'seasonType': 'regular'},
    'url': 'https://api.collegefootballdata.com/lines?year=2026&week=4&seasonType=regular',
}
MAX_BYTES = 5 * 1024 * 1024
ATTEMPT = 'lines-week4-2026-once'


def findings(rows):
    if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
        raise ValueError('LINES_ARRAY_REQUIRED')
    books = [b for g in rows for b in g.get('lines', []) if isinstance(b, dict)]
    fields = sorted({k for row in rows + books for k in row})
    timestamp_fields = [k for k in fields if any(x in k.lower() for x in ('updated', 'observed', 'timestamp'))]
    conventions = [k for k in fields if any(x in k.lower() for x in ('period', 'overtime', 'regulation'))]
    return {
        'gameCount': len(rows), 'bookMarketRecordCount': len(books),
        'uniqueGameIds': len({str(x.get('id')) for x in rows if x.get('id') is not None}),
        'gameIdsComplete': bool(rows) and all(x.get('id') is not None for x in rows),
        'schoolIdsComplete': bool(rows) and all(x.get('homeTeamId') is not None and x.get('awayTeamId') is not None for x in rows),
        'schoolNamesComplete': bool(rows) and all(x.get('homeTeam') and x.get('awayTeam') for x in rows),
        'bookProviders': sorted({str(x.get('provider')) for x in books if x.get('provider')}),
        'recordsWithBothMoneylines': sum(x.get('homeMoneyline') is not None and x.get('awayMoneyline') is not None for x in books),
        'recordsWithSpread': sum(x.get('spread') is not None for x in books),
        'recordsWithTotal': sum(x.get('overUnder') is not None for x in books),
        'quoteTimestampCandidateFields': timestamp_fields,
        'marketPeriodOrOvertimeCandidateFields': conventions,
        'topLevelSchema': schema_profile(rows), 'bookSchema': schema_profile(books),
        'quoteTimestampAuthority': 'NONE_ESTABLISHED_BY_ACQUISITION',
        'consumerAuthority': 'Claude determines reference-only versus actionable prices; acquisition is not quote time.',
    }


def probe(*, state_root, plan_ref, grant_ref, deployment, probe_grant_ref,
          entitlement_receipt_ref, env_file, transport_factory=None, clock=now):
    state = Path(state_root)
    capture_root = state / 'capture'
    attempt = capture_root / 'attempts' / ATTEMPT
    with owner_lock(state / 'publisher.lock'):
        # A receipt is reused only after verifying its exact private bytes.
        if (attempt / 'completion.json').exists():
            retained = read_ref(reference(attempt / 'completion.json'))
            if retained.get('disposition') == 'CAPTURED_LINES_PROBE':
                verified_bytes(retained['rawResponse'])
                return dict(retained, invocationDisposition='REUSED_RETAINED_NO_NETWORK')
            raise RuntimeError('ONE_SHOT_PROBE_ALREADY_ATTEMPTED_NO_RETRY')
        if (attempt / 'started.json').exists():
            raise RuntimeError('ONE_SHOT_PROBE_INTERRUPTED_NO_RETRY')
        started = clock()
        plan = validate_grant(plan_ref, grant_ref, deployment, True, started)
        approval = read_ref(probe_grant_ref)
        if (approval.get('approvedBy') != 'James' or approval.get('request') != ASSET
                or approval.get('maxRequests') != 1 or approval.get('maxResponseBytes') != MAX_BYTES
                or approval.get('retryCount') != 0 or approval.get('maxCostUsd') != 0
                or approval.get('planSha256') != plan_ref['sha256']):
            raise PermissionError('EXACT_ONE_SHOT_LINES_AUTHORIZATION_REQUIRED')
        verified_bytes(approval['authorizationEvidence'])
        # Use the natural owner's fresh before/after check. This single-request
        # grant does not silently add separate /info requests.
        previous = read_ref(entitlement_receipt_ref)
        previous_path = Path(entitlement_receipt_ref['path']).resolve()
        if not previous_path.is_relative_to((capture_root / 'attempts').resolve()):
            raise ValueError('ENTITLEMENT_MUST_BIND_CURRENT_OWNER_CAPTURE')
        if previous.get('disposition') != 'CAPTURED':
            raise ValueError('SUCCESSFUL_CURRENT_OWNER_CAPTURE_REQUIRED')
        age = utc(started) - utc(previous['completedAtUtc'])
        if age < timedelta(0) or age > timedelta(minutes=30):
            raise ValueError('FRESH_OWNER_ENTITLEMENT_REQUIRED')
        source = read_ref(previous['sourceManifest'])
        infos = [x for x in source.get('wireRequests', source['requests']) if x['endpoint'] == '/info']
        if not infos:
            raise ValueError('RAW_ENTITLEMENT_EVIDENCE_REQUIRED')
        latest_info = max(infos, key=lambda x: utc(x['acquiredAt']))
        check = entitlement(json.loads(verified_bytes(latest_info)), 1)
        usage = usage_snapshot(capture_root, plan, started)
        # The entitlement capture must be the last account activity known to
        # this owner. Refuse intervening attempts or an unresolved owner batch.
        if utc(usage['lastAttemptUtc']) != utc(previous['startedAtUtc']):
            raise ValueError('ENTITLEMENT_SUPERSEDED_BY_OTHER_ACCOUNT_ACTIVITY')
        active_path = capture_root / 'active.json'
        if active_path.exists():
            active = read_ref(reference(active_path))
            if active.get('status') not in ('ADMITTED', 'ADMISSION_FAILED'):
                raise ValueError('OWNER_CAPTURE_NOT_FINISHED')
        if usage['utcDayRequests'] + 1 > plan['maxRequestsPerUtcDay']:
            raise ValueError('UTC_DAY_REQUEST_BUDGET')
        if usage['periodRequestsIncludingCarryForward'] + 1 > plan['maxRequestsForPeriodIncludingCarryForward']:
            raise ValueError('PERIOD_REQUEST_BUDGET')
        if usage['utcDayBytes'] + MAX_BYTES > plan['maxResponseBytesPerUtcDay']:
            raise ValueError('UTC_DAY_BYTE_BUDGET')
        retained = plan.get('priorRetainedRawBytesConservative', 0)
        retained += sum(p.stat().st_size for p in capture_root.rglob('response.json'))
        if retained + MAX_BYTES > plan['maxRetainedBytes']:
            raise ValueError('RETAINED_STORAGE_BUDGET')
        # Read credentials before reserving. Missing local credentials cause
        # zero HTTP and do not consume this grant.
        transport = transport_factory() if transport_factory else HttpTransport(env_file)
        reservation = dict(schema='CFB_ONE_SHOT_LINES_PROBE_START_V1', startedAtUtc=started,
                           request=ASSET, plannedRequests=1, maximumResponseBytes=MAX_BYTES,
                           plan=plan_ref, grant=probe_grant_ref, recurringGrant=grant_ref,
                           entitlementReceipt=entitlement_receipt_ref, entitlementBefore=check,
                           usageBefore=usage, credentialRetained=False)
        immutable(attempt / 'started.json', canonical_bytes(reservation))
        ledger = {'attemptedRequests': 1, 'responseBytes': 0, 'request': ASSET}
        atomic_json(attempt / 'ledger.json', ledger)
        result = dict(schema='CFB_ONE_SHOT_LINES_PROBE_COMPLETION_V1', startedAtUtc=started,
                      request=ASSET, providerCalls=1, providerBytes=0, retryCount=0, costUsd=0,
                      entitlementBefore=check, grant=probe_grant_ref, credentialRetained=False)
        def meter(size):
            if not isinstance(size, int) or size < 0 or ledger['responseBytes'] + size > MAX_BYTES:
                raise RuntimeError('LINES_BYTE_CEILING')
            ledger['responseBytes'] += size
            atomic_json(attempt / 'ledger.json', ledger)
        try:
            status, headers, raw = transport(ASSET, {}, MAX_BYTES, meter)
            acquired = clock()
            if ledger['responseBytes'] != len(raw) or len(raw) > MAX_BYTES:
                raise ValueError('LINES_RESPONSE_BYTE_ACCOUNTING_FAILURE')
            bound = immutable(attempt / 'raw' / 'sha256' / digest(raw) / 'response.json', raw)
            result.update(httpStatus=status, responseHeaders=headers, rawResponse=bound, acquiredAtUtc=acquired)
            if status != 200:
                raise ValueError('LINES_SOURCE_HTTP_FAILURE')
            result.update(findings=findings(json.loads(raw)), disposition='CAPTURED_LINES_PROBE')
        except Exception as exc:
            # Third-party errors never enter durable output or console.
            result.update(disposition='STOPPED_FAILED_CLOSED', errorType=type(exc).__name__)
        result.update(providerBytes=ledger['responseBytes'], completedAtUtc=clock(),
                      entitlementAfter='NOT_INDEPENDENTLY_QUERIED_UNDER_SINGLE_REQUEST_GRANT',
                      entitlementRemainingConservative=max(0, check['remainingCalls'] - 1))
        immutable(attempt / 'completion.json', canonical_bytes(result))
        return result
