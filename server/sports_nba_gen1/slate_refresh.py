"""Conditional source capture and checkpoint-aware planning for ONE NBA owner.

No call can reach the HTTP transport without an exact live grant and explicit
enable flag. Tests inject a transport; fixtures never authorize the real client.
"""
from __future__ import annotations

from datetime import timedelta
import io
import json
from pathlib import Path
from urllib.parse import urlparse
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from .authority import reference, verified_bytes
from .production import canonical_bytes, digest
from .slate_lifecycle import atomic_json, immutable, now, object_json, read_ref, utc

URL = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_schedules/nba_schedule_2027.parquet'


def schema_description(raw):
    return [{'name': f.name, 'type': str(f.type), 'nullable': f.nullable}
            for f in pq.read_schema(io.BytesIO(raw))]


def refresh_due(bundle, latest_capture, usage, plan, clock):
    """Timing uses observed published metadata, never fabricated final status."""
    t = utc(clock)
    targets = [x['target'] for x in bundle['games'] if x.get('target')]
    ordinary = [x for x in targets if not x['neutral_site'] and x['season_type'] == 'REGULAR']
    starts = [utc(x['scheduled_tipoff_utc']) for x in ordinary]
    if not starts:
        return {'disposition': 'NO_ADMITTED_SCHEDULE', 'due': False, 'networkIntentRequests': 0}
    first, last = min(starts), max(starts)
    earliest = first - timedelta(days=7, minutes=60)
    if t < earliest or t < utc(plan['validFromUtc']):
        return {'disposition': 'REFRESH_NOT_DUE', 'due': False, 'networkIntentRequests': 0,
                'nextEligibleAtUtc': max(earliest, utc(plan['validFromUtc'])).isoformat()}
    if t >= utc(plan['validUntilUtc']) or t > last + timedelta(days=2):
        return {'disposition': 'REFRESH_PERIOD_CLOSED', 'due': False, 'networkIntentRequests': 0}
    checked = utc(latest_capture.get('validatedAtUtc', latest_capture['capturedAtUtc']))
    last_attempt = utc(usage['attempts'][-1]['startedAtUtc']) if usage.get('attempts') else None
    if last_attempt and t - last_attempt < timedelta(minutes=plan['minimumAttemptSpacingMinutes']):
        return {'disposition': 'REFRESH_NOT_DUE', 'due': False, 'networkIntentRequests': 0,
                'nextEligibleAtUtc': (last_attempt + timedelta(minutes=plan['minimumAttemptSpacingMinutes'])).isoformat()}
    reasons = []
    if checked < earliest:
        reasons.append('PRESEASON_OPENING_BOOTSTRAP')
    local = t.astimezone(ZoneInfo('America/New_York'))
    daily = local.replace(hour=10, minute=0, second=0, microsecond=0)
    if local >= daily and checked < daily.astimezone(ZoneInfo('UTC')):
        reasons.append('DAILY_SCHEDULE_STATUS_AND_CORRECTIONS')
    for target in ordinary:
        tip = utc(target['scheduled_tipoff_utc'])
        if target['status'] == 'SCHEDULED' and t < tip - timedelta(minutes=30):
            for minutes in (10080, 1440, 360, 60):
                checkpoint = tip - timedelta(minutes=minutes)
                lead = checkpoint - timedelta(minutes=60)
                if lead <= t <= checkpoint and checked < lead:
                    reasons.append('CHECKPOINT_LEAD_REVALIDATION')
            if tip - timedelta(days=7) <= t and t-checked >= timedelta(hours=23):
                reasons.append('FRESHNESS_EXPIRY_APPROACHING')
            if tip-t <= timedelta(hours=1) and t-checked >= timedelta(minutes=90):
                reasons.append('FINAL_CHECKPOINT_FRESHNESS')
        # Four hours is only a bounded opportunity to CHECK, never an assumed final.
        opportunity = tip + timedelta(hours=4)
        unresolved = target['status'] not in ('STATUS_FINAL','STATUS_POSTPONED','STATUS_CANCELED','STATUS_CANCELLED')
        if opportunity <= t <= opportunity + timedelta(days=2) and (checked < opportunity or
                (unresolved and t-checked >= timedelta(hours=2))):
            reasons.append('POSTGAME_FINAL_AVAILABILITY_CHECK')
    return {'disposition': 'REFRESH_DUE' if reasons else 'REFRESH_NOT_DUE', 'due': bool(reasons),
            'networkIntentRequests': 1 if reasons else 0, 'reasons': sorted(set(reasons))}


def check_grant(release, grant_ref, enabled, clock):
    if not enabled or not grant_ref:
        raise PermissionError('LIVE_ACQUISITION_NOT_AUTHORIZED')
    proposal = read_ref(release['refreshAuthorizationProposal'])
    plan_ref = release['refreshPlan']
    plan = read_ref(plan_ref)
    grant = read_ref(grant_ref)
    if (grant.get('schema') != 'NBA_SAME_OWNER_REFRESH_GRANT_V1' or grant.get('approvedBy') != 'James'
            or grant.get('liveCaptureAuthorized') is not True
            or grant.get('proposalSha256') != release['refreshAuthorizationProposal']['sha256']
            or grant.get('refreshPlanSha256') != plan_ref['sha256']
            or grant.get('deploymentId') != proposal['deploymentId']
            or grant.get('validFromUtc') != plan['validFromUtc'] or grant.get('validUntilUtc') != plan['validUntilUtc']
            or not utc(plan['validFromUtc']) <= utc(clock) < utc(plan['validUntilUtc'])):
        raise PermissionError('EXACT_REFRESH_GRANT_REQUIRED')
    for bound in plan['rightsEvidence']:
        verified_bytes(bound)
    return plan


def permitted_redirect(url, plan):
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.port in (None,443) and not parsed.username and not parsed.password
            and any(parsed.hostname == r['host'] and parsed.path.startswith(r['pathPrefix'])
                    for r in plan['permittedTransportRedirects']))


def http_fetch(headers, plan, meter):
    """No credential loading. At most four explicitly metered HTTP requests."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    url = plan['assets'][0]['url']
    for hop in range(plan['maximumHttpRequestsPerInvocation']):
        meter('request', 1)
        request = urllib.request.Request(url, headers={'User-Agent': 'ASP-NBA-governed-refresh/1', **headers})
        try:
            response = opener.open(request, timeout=45)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status = response.code
            allowed = {k: response.headers[k] for k in ('Date','ETag','Last-Modified','Content-Type','Content-Length') if k in response.headers}
            if status in (301,302,303,307,308):
                location = response.headers.get('Location', '')
                if not permitted_redirect(location, plan):
                    raise ValueError('Unapproved source redirect')
                # Read/count even redirect response bodies. Signed query strings
                # remain transport-only and are never retained or printed.
                while True:
                    part = response.read(65536)
                    if not part:
                        break
                    meter('bytes', len(part))
                url = location
                continue
            if status == 304:
                return {'status':304, 'body':b'', 'headers':allowed}
            if status != 200:
                raise ValueError('SOURCE_ACCESS_REFUSED_OR_HTTP_' + str(status))
            body = bytearray()
            while True:
                part = response.read(65536)
                if not part:
                    break
                meter('bytes', len(part))
                body.extend(part)
            return {'status':200, 'body':bytes(body), 'headers':allowed}
    raise ValueError('Redirect/request ceiling reached')


def capture(*, release, latest_ref, private_root, grant_ref=None, enabled=False,
            clock=now, transport=None, admission_root=None):
    """Must be called while the canonical invocation lock is held.

    Admission and pointer updates are deliberately outside this phase. A fully
    retained capture can be replayed after a crash without another source call.
    """
    started = clock()
    plan = check_grant(release, grant_ref, enabled, started)
    root = Path(private_root)
    ledger = root/'usage.json'
    usage = json.loads(ledger.read_bytes()) if ledger.exists() else {'attempts': []}
    if (root/'HALTED.json').exists():
        raise RuntimeError('SOURCE_CAPTURE_HALTED_REVIEW_REQUIRED')
    daily = [x for x in usage['attempts'] if x['startedAtUtc'][:10] == started[:10]]
    if len(daily) >= plan['maximumCaptureAttemptsPerUtcDay']:
        raise RuntimeError('UTC_DAY_REQUEST_CEILING')
    if usage['attempts'] and utc(started)-utc(usage['attempts'][-1]['startedAtUtc']) < timedelta(minutes=plan['minimumAttemptSpacingMinutes']):
        raise RuntimeError('CAPTURE_SPACING_CEILING')
    if sum(x['reservedResponseBytes'] for x in daily) + plan['maximumResponseBytesPerInvocation'] > plan['maximumResponseBytesPerUtcDay']:
        raise RuntimeError('UTC_DAY_BYTE_CEILING')
    storage_roots = [root] + ([Path(admission_root)] if admission_root else [])
    used_storage = sum(p.stat().st_size for folder in storage_roots for p in folder.rglob('*') if p.is_file())
    if used_storage + plan['maximumResponseBytesPerInvocation'] + 32*1024**2 > plan['maximumRetainedStorageBytes']:
        raise RuntimeError('RETAINED_STORAGE_CEILING')
    latest = read_ref(latest_ref)
    verified_bytes(latest['source'])
    conditional = {}
    previous_headers = latest.get('responseHeaders', {})
    if previous_headers.get('ETag'):
        conditional['If-None-Match'] = previous_headers['ETag']
    if previous_headers.get('Last-Modified'):
        conditional['If-Modified-Since'] = previous_headers['Last-Modified']
    attempt = {'startedAtUtc':started, 'disposition':'RESERVED', 'httpRequests':0, 'responseBodyBytes':0,
               'reservedResponseBytes':plan['maximumResponseBytesPerInvocation']}
    usage['attempts'].append(attempt)
    atomic_json(ledger, usage)  # Crash reservations persist; zero retries.
    source = None
    def meter(kind, count):
        key = 'httpRequests' if kind == 'request' else 'responseBodyBytes'
        attempt[key] += count
        atomic_json(ledger, usage)
        if attempt['httpRequests'] > plan['maximumHttpRequestsPerInvocation'] or attempt['responseBodyBytes'] > plan['maximumResponseBytesPerInvocation']:
            raise RuntimeError('CAPTURE_REQUEST_OR_BYTE_CEILING')
    try:
        response = (transport or http_fetch)(conditional, plan, meter)
        stamp = clock()
        headers = dict(previous_headers)
        headers.update(response['headers'])
        if response['status'] == 304:
            if not conditional or response['body']:
                raise ValueError('INVALID_304_WITHOUT_CONDITIONAL_PRIOR')
            source = latest['source']
            first_capture = latest['capturedAtUtc']
            disposition = 'CONDITIONAL_UNCHANGED'
            schema = schema_description(verified_bytes(source))
        elif response['status'] == 200:
            payload = response['body']
            same = digest(payload) == latest['source']['sha256']
            source = latest['source'] if same else immutable(
                root/'objects/sha256'/digest(payload)/'nba_schedule_2027.parquet', payload)
            schema = schema_description(payload)
            first_capture = latest['capturedAtUtc'] if same else stamp
            disposition = 'UNCHANGED_200' if same else 'CHANGED_CAPTURE'
        else:
            raise ValueError('Unsupported capture response')
        if schema != plan['expectedPhysicalSchema']:
            raise ValueError('SOURCE_SCHEMA_DRIFT_QUARANTINED')
        receipt = {'schema':'NBA_CONDITIONAL_SCHEDULE_CAPTURE_V1', 'source':source,
            'endpoint':plan['assets'][0]['url'], 'parameters':{}, 'seasonEnd':2027,
            'capturedAtUtc':first_capture, 'validatedAtUtc':stamp, 'sourcePublicationClock':headers.get('Last-Modified'),
            'httpStatus':response['status'], 'responseHeaders':headers, 'conditionalHeadersSent':conditional,
            'priorObjectReceipt':latest_ref, 'disposition':disposition, 'schemaFingerprint':digest(schema),
            'rightsEvidence':plan['rightsEvidence'], 'plan':release['refreshPlan'], 'authorization':grant_ref,
            'httpRequests':attempt['httpRequests'], 'responseBodyBytes':attempt['responseBodyBytes'],
            'rawBytesDuplicated':False, 'costUsd':0,
            'freshnessMeaning':'Actual server revalidation; not a claim that the publisher has supplied missing finals'}
        bound = object_json(root/'captures', receipt)
        attempt.update(disposition=disposition, captureReceipt=bound)
        atomic_json(ledger, usage)
        # Capture transaction persisted before return. Recovery uses this object.
        atomic_json(root/'latest-capture.json', {'receipt':bound})
        return bound
    except Exception as exc:
        failure = {'schema':'NBA_REFRESH_CAPTURE_FAILURE_V1', 'createdAtUtc':clock(),
            'attempt':attempt, 'errorType':type(exc).__name__, 'reason':str(exc),
            'priorObjectReceipt':latest_ref, 'quarantinedObject':source,
            'plan':release['refreshPlan'], 'retryCount':0}
        failure_ref = object_json(root/'failures', failure)
        attempt.update(disposition='FAILED_STOP_NO_RETRY', failureReceipt=failure_ref)
        immutable(root/'HALTED.json', canonical_bytes({'failure':failure_ref}))
        raise
    finally:
        atomic_json(ledger, usage)
