"""Single-lock NBA refresh -> admission -> publication transaction owner.

Transport injection exists for tests only. CLI network access requires both an
explicit switch and a grant bound to the exact staged proposal/deployment.
"""
import json
from pathlib import Path
import uuid

from .authority import reference
from .slate_inputs import admit, validate_bundle
from .slate_lifecycle import atomic_json, now, object_json, owner_lock, read_ref, tick
from .slate_refresh import capture, refresh_due
from .slate_render import render, verify_package


def usage_totals(root):
    p = Path(root)/'usage.json'
    usage = json.loads(p.read_bytes()) if p.exists() else {'attempts': []}
    return usage, sum(x['httpRequests'] for x in usage['attempts']), sum(x['responseBodyBytes'] for x in usage['attempts'])


def invoke(*, release_ref, input_pointer, state_root, exchange_root, enabled=False,
           grant_ref=None, clock=now, transport=None, renderer=render,
           verifier=verify_package, bundle_validator=validate_bundle, admitter=admit, fault=None):
    state = Path(state_root)
    private = state/'refresh'
    invocation = uuid.uuid4().hex
    phases = []
    receipt = {'schema':'NBA_GEN1_SAME_OWNER_RECEIPT_V1', 'invocationId':invocation,
               'startedAtUtc':clock(), 'phases':phases, 'release':release_ref,
               'networkEnabled':enabled, 'costUsd':0, 'aispWrites':0}
    object_json(state/'owner-starts', receipt)
    _, before_calls, before_bytes = usage_totals(private)
    def phase(name, disposition, **details):
        value = dict(schema='NBA_OWNER_PHASE_RECEIPT_V1', invocationId=invocation,
                     phase=name, disposition=disposition, createdAtUtc=clock(), **details)
        bound = object_json(state/'phase-receipts', value)
        phases.append({'phase':name, 'disposition':disposition, 'receipt':bound})
        return bound
    try:
        with owner_lock(state/'publisher.lock'):
            release = read_ref(release_ref)
            plan = read_ref(release['refreshPlan'])
            bundle_ref = read_ref(reference(input_pointer))['inputManifest']
            bundle = read_ref(bundle_ref)
            bundle_validator(bundle, release)
            latest_ref = bundle['captureReceipt']
            usage, _, _ = usage_totals(private)
            # Ledger is committed before latest-capture pointer. Recover either.
            completed = [a['captureReceipt'] for a in usage['attempts'] if a.get('captureReceipt')]
            if completed:
                latest_ref = completed[-1]
            elif (private/'latest-capture.json').exists():
                latest_ref = read_ref(reference(private/'latest-capture.json'))['receipt']
            latest = read_ref(latest_ref)
            pending = latest_ref['sha256'] != bundle['captureReceipt']['sha256']
            timing = refresh_due(bundle, latest, usage, plan, clock())
            phase('planning', timing['disposition'], timing=timing, inputVersion=bundle_ref)
            rejection_path = private/'admission-rejection.json'
            rejection = json.loads(rejection_path.read_bytes()) if rejection_path.exists() else None
            transient_pending = bool(rejection and rejection['captureSha256'] == latest_ref['sha256']
                and rejection['reason'].startswith('SOURCE_FINAL_PENDING:'))
            if rejection and rejection['captureSha256'] == latest_ref['sha256'] and not transient_pending:
                raise RuntimeError('ADMISSION_QUARANTINE_REVIEW_REQUIRED')
            # A completed but unadmitted capture is recovered locally first.
            # Failed incomplete transport reservations are never automatically retried.
            if any(a['disposition'] == 'RESERVED' for a in usage['attempts']):
                raise RuntimeError('INTERRUPTED_CAPTURE_REVIEW_REQUIRED_NO_RETRY')
            if (private/'HALTED.json').exists():
                raise RuntimeError('SOURCE_CAPTURE_HALTED_REVIEW_REQUIRED')
            if (not pending or transient_pending) and timing['due']:
                if not enabled or not grant_ref:
                    phase('capture', 'LIVE_ACQUISITION_NOT_AUTHORIZED', networkIntentRequests=0,
                          potentialLogicalRequests=1)
                    phase('admission', 'SKIPPED_NO_NEW_CAPTURE')
                    phase('publication', 'SKIPPED_REQUIRED_REFRESH_UNAVAILABLE')
                    receipt.update(disposition='LIVE_ACQUISITION_NOT_AUTHORIZED', exitCode=0)
                else:
                    try:
                        latest_ref = capture(release=release, latest_ref=latest_ref, private_root=private,
                            grant_ref=grant_ref, enabled=enabled, clock=clock, transport=transport,
                            admission_root=Path(input_pointer).parent)
                    except Exception as exc:
                        ledger, _, _ = usage_totals(private)
                        phase('capture', 'CAPTURE_FAILED_CLOSED', reason=str(exc),
                              lastAttempt=ledger['attempts'][-1] if ledger['attempts'] else None)
                        raise
                    latest = read_ref(latest_ref)
                    pending = True
                    phase('capture', latest['disposition'], captureReceipt=latest_ref,
                          httpRequests=latest['httpRequests'], responseBodyBytes=latest['responseBodyBytes'])
                    if fault:
                        fault('captured')
            else:
                phase('capture', 'RECOVERED_RETAINED_CAPTURE' if pending else 'REFRESH_NOT_DUE',
                      captureReceipt=latest_ref, networkIntentRequests=0)
            if 'exitCode' not in receipt:
                if pending:
                    # Full validation occurs before admit atomically advances current.json.
                    try:
                        bundle_ref = admitter(capture_ref=latest_ref, base_model_ref=release['baseModelReceipt'],
                            base_coverage_ref=release['baseCoverage'], rights_refs=plan['rightsEvidence'],
                            registry_root=Path(input_pointer).parent, season_end=2027,
                            reviewed_by='NBA_GEN1_SAME_OWNER_FROZEN_ADMISSION_V1',
                            precommit=lambda b: bundle_validator(b, release))
                    except Exception as exc:
                        failure = dict(captureSha256=latest_ref['sha256'], reason=str(exc),
                            createdAtUtc=clock(), inputPointerBefore=bundle_ref)
                        failure_ref = object_json(private/'admission-failures', failure)
                        atomic_json(rejection_path, dict(failure, receipt=failure_ref))
                        phase('admission', 'REJECTED_POINTER_UNCHANGED', failure=failure_ref)
                        raise
                    phase('admission', 'ADMITTED_ATOMIC_INPUT_VERSION', inputVersion=bundle_ref)
                    if fault:
                        fault('admitted')
                else:
                    phase('admission', 'REUSED_ADMITTED_VERSION', inputVersion=bundle_ref)
                result, bound = tick(bundle_ref=bundle_ref, release_ref=release_ref,
                    state_root=state, exchange_root=exchange_root, renderer=renderer,
                    verifier=verifier, bundle_validator=bundle_validator, clock=clock,
                    owner_lock_already_held=True)
                phase('publication', result['disposition'], runnerReceipt=bound)
                receipt.update(disposition=result['disposition'], exitCode=result['exitCode'],
                               runnerReceipt=bound, inputVersion=bundle_ref)
    except Exception as exc:
        phase('failure', 'FAILED_CLOSED', errorType=type(exc).__name__, reason=str(exc),
              priorArtifactsPreserved=True, inputPointerPolicy='Last completely admitted version only')
        receipt.update(disposition='FAILED_CLOSED', exitCode=1,
                       errorType=type(exc).__name__, reason=str(exc))
    finally:
        # Every invocation has all phase dispositions, even if an earlier phase failed.
        existing = {p['phase'] for p in phases}
        for name in ('planning','capture','admission','publication'):
            if name not in existing:
                phase(name, 'SKIPPED_PRIOR_PHASE_FAILURE')
        _, after_calls, after_bytes = usage_totals(private)
        receipt.update(completedAtUtc=clock(), providerCalls=after_calls-before_calls,
                       providerBytes=after_bytes-before_bytes)
        if not receipt.get('runnerReceipt'):
            receipt['runnerReceipt'] = object_json(state/'runner-receipts', {
                'schema':'NBA_GEN1_SLATE_RUNNER_RECEIPT_V1', 'createdAtUtc':clock(),
                'invocationId':invocation, 'disposition':'PUBLICATION_SKIPPED',
                'reason':receipt['disposition'], 'exitCode':receipt['exitCode'], 'games':[],
                'priorArtifactsPreserved':True})
        bound = object_json(state/'owner-receipts', receipt)
    return receipt, bound
