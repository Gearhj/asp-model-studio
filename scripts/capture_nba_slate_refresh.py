"""Staged bounded free source capture. Default is a no-network plan.

Not invoked by the publisher wrapper. A future explicit, hash-pinned owner
authorization is required for --execute. This task runs only --plan.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sports_nba_gen1.authority import reference, verified_bytes
from server.sports_nba_gen1.slate_lifecycle import atomic_json, immutable, now, object_json, owner_lock, read_ref, utc

URL = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_schedules/nba_schedule_2027.parquet'
PLAN = {'schema': 'NBA_SLATE_REFRESH_ACQUISITION_PLAN_V1', 'source': 'SportsDataverse ESPN-derived schedule/finals',
    'endpoint': URL, 'seasonEnd': 2027, 'successfulGetsPerCapture': 1, 'maximumHttpAttemptsPerCapture': 4,
    'redirectsMaximum': 3, 'retryCount': 0, 'maxBodyBytesPerCapture': 16*1024*1024,
    'capturesMaximumPerUtcDay': 24, 'minimumMinutesBetweenAttempts': 60,
    'maxBodyBytesPerUtcDay': 384*1024*1024, 'maxPrivateStorageBytes': 5*1024**3,
    'expectedBodyBytes': 'Latest retained schedule 86,466 bytes; completed 2026 season 525,802 bytes; future size unknown',
    'costUsd': 0, 'credentials': False, 'license': 'Retained SportsDataverse/hoopR CC BY 4.0; preserve attribution and changes disclosure',
    'period': 'Proposed hourly only when a slate game is within seven days, plus post-final updates at next allowed hour',
    'owner': 'Model Studio NBA input admission; no recurring capture is installed or connected',
    'authority': 'AWAITING_EXPLICIT_REFRESH_AUTHORIZATION', 'nbaComCalls': 0,
    'output': 'Private raw physical object + receipt, then offline admit_nba_gen1_slate_inputs.py',
    'stopConditions': ['refusal/non-200', 'changed rights', 'schema/identity failure', 'limits', 'no retries'],
    'retention': 'Append-only private objects; no automatic deletion; stop at 5 GiB; no Git/raw exchange'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--execute', action='store_true')
    p.add_argument('--authorization')
    p.add_argument('--authorization-sha256')
    p.add_argument('--private-root')
    a = p.parse_args()
    if not a.execute:
        print(json.dumps(PLAN, indent=2))
        return
    if not all([a.authorization, a.authorization_sha256, a.private_root]):
        raise ValueError('Explicit owner authorization, physical hash and private root required')
    ref = reference(a.authorization)
    if ref['sha256'] != a.authorization_sha256:
        raise ValueError('Authorization hash mismatch')
    grant = read_ref(ref)
    if grant.get('schema') != 'NBA_SLATE_REFRESH_AUTHORIZATION_V1' or grant.get('authorizedBy') != 'James' or grant.get('plan') != PLAN or grant.get('executeApproved') is not True:
        raise ValueError('This exact bounded source plan needs separate authorization')
    if not utc(grant['validFromUtc']) <= utc(now()) < utc(grant['validUntilUtc']):
        raise ValueError('Authorization not current')
    if not grant.get('rightsEvidence'):
        raise ValueError('Source rights review missing')
    for bound in grant['rightsEvidence']:
        verified_bytes(bound)
    root = Path(a.private_root)
    with owner_lock(root / 'capture.lock'):
        ledger = root / 'usage.json'
        usage = json.loads(ledger.read_bytes()) if ledger.exists() else {'attempts': [], 'acceptedBytes': 0}
        start = now()
        today = start[:10]
        daily = [x for x in usage['attempts'] if x['startedAtUtc'][:10] == today]
        if len(daily) >= PLAN['capturesMaximumPerUtcDay'] or (usage['attempts'] and (utc(start)-utc(usage['attempts'][-1]['startedAtUtc'])).total_seconds() < 3600):
            raise ValueError('Daily/cadence ceiling')
        if sum(x.get('bytes', 0) for x in daily) + PLAN['maxBodyBytesPerCapture'] > PLAN['maxBodyBytesPerUtcDay']:
            raise ValueError('Daily byte ceiling')
        if sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) + PLAN['maxBodyBytesPerCapture'] > PLAN['maxPrivateStorageBytes']:
            raise ValueError('Private retained storage ceiling')
        attempt = {'startedAtUtc': start, 'disposition': 'RESERVED', 'bytes': 0, 'httpAttempts': 0}
        usage['attempts'].append(attempt)
        atomic_json(ledger, usage)  # Reserve before network; crash does not reset allowance.
        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                from urllib.parse import urlparse
                u = urlparse(newurl)
                if u.scheme != 'https' or u.hostname not in ('release-assets.githubusercontent.com', 'objects.githubusercontent.com', 'github.com'):
                    raise ValueError('Unapproved redirect')
                attempt['httpAttempts'] += 1
                atomic_json(ledger, usage)
                if attempt['httpAttempts'] > PLAN['maximumHttpAttemptsPerCapture']:
                    raise ValueError('Redirect ceiling')
                return super().redirect_request(req, fp, code, msg, headers, newurl)
        try:
            attempt['httpAttempts'] = 1
            atomic_json(ledger, usage)
            opener = urllib.request.build_opener(Redirect())
            with opener.open(urllib.request.Request(URL, headers={'User-Agent': 'ASP-Model-Studio-bounded-source-capture/1'}), timeout=45) as response:
                if response.status != 200:
                    raise ValueError('Source refusal/status')
                data = bytearray()
                while True:
                    chunk = response.read(min(65536, PLAN['maxBodyBytesPerCapture'] + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    attempt['bytes'] = len(data)
                    atomic_json(ledger, usage)
                    if len(data) > PLAN['maxBodyBytesPerCapture']:
                        raise ValueError('Response byte ceiling')
                headers = {k: response.headers[k] for k in ('Date', 'ETag', 'Last-Modified', 'Content-Type', 'Content-Length') if k in response.headers}
            payload = bytes(data)
            # Rights already bound before raw retention. Schema drift is quarantined
            # here; no pointer admission occurs until the offline validator passes.
            bound = immutable(root / 'raw/sha256' / hashlib.sha256(payload).hexdigest() / 'schedule.parquet', payload)
            import pyarrow.parquet as pq
            schema = pq.read_schema(bound['path'])
            fingerprint = hashlib.sha256(str(schema).encode()).hexdigest()
            predecessor = usage.get('latestSuccessfulReceipt')
            if predecessor and read_ref(predecessor)['schemaFingerprint'] != fingerprint:
                raise ValueError('Schema drift: raw object retained in quarantine, not admitted')
            receipt = {'schema': 'NBA_GOVERNED_SCHEDULE_CAPTURE_V1', 'endpoint': URL, 'parameters': {},
                'seasonEnd': 2027, 'capturedAtUtc': now(), 'httpStatus': 200, 'responseHeaders': headers,
                'source': bound, 'schemaFingerprint': fingerprint, 'predecessor': predecessor,
                'authorization': ref, 'rightsEvidence': grant['rightsEvidence'], 'costUsd': 0}
            result = object_json(root / 'captures', receipt)
            usage['latestSuccessfulReceipt'] = result
            usage['acceptedBytes'] += len(payload)
            attempt['disposition'] = 'CAPTURED_NOT_ADMITTED'
            print(json.dumps(result, indent=2))
        except Exception as exc:
            attempt.update(disposition='FAILED_STOP_NO_RETRY', errorType=type(exc).__name__)
            raise
        finally:
            atomic_json(ledger, usage)


if __name__ == '__main__':
    main()
