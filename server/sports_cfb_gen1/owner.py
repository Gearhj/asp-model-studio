"""One locked CFB capture/admission/publication owner; network opt-in only."""
from pathlib import Path
import uuid
from .publication_io import reference
from .lifecycle import read_ref,now,object_json,owner_lock,tick,atomic_json
from .inputs import admit,validate_bundle
from .render import render,verify_package
from .final_evidence import publish_final_evidence


def invoke(*,release_ref,input_pointer,state_root,exchange_root,capture_pointer=None,
           clock=now,renderer=render,verifier=verify_package,bundle_validator=validate_bundle,
           admitter=admit,fault=None,enable_network=False,grant_ref=None,transport_factory=None,
           capturer=None,final_exporter=publish_final_evidence):
    state=Path(state_root)
    ident=uuid.uuid4().hex
    result={'schema':'CFB_GEN1_OWNER_RECEIPT_V1','invocationId':ident,'startedAtUtc':clock(),
        'providerCalls':0,'providerBytes':0,'costUsd':0,'aispWrites':0,'phases':[]}
    object_json(state/'owner-starts',result)
    def phase(kind,status,**values):
        ref=object_json(state/'phase-receipts',dict(invocationId=ident,createdAtUtc=clock(),phase=kind,disposition=status,**values))
        result['phases'].append(dict(phase=kind,disposition=status,receipt=ref))
    try:
        with owner_lock(state/'publisher.lock'):
            release=read_ref(release_ref)
            current=read_ref(reference(input_pointer))['inputManifest']
            if release.get('refreshPlan'):
                from .capture import capture,validate_grant
                from .refresh import due,statistics_selector,usage_snapshot,budget_reason
                capture_root=state/'capture';plan=read_ref(release['refreshPlan']);bundle=read_ref(current)
                active_path=capture_root/'active.json'
                active=read_ref(reference(active_path)) if active_path.exists() else None
                pending=None
                if active and active['status'] in ('STARTED','CAPTURED'):
                    completion=Path(active['directory'])/'completion.json'
                    if not completion.exists():raise RuntimeError('INTERRUPTED_CAPTURE_REQUIRES_REVIEW_NO_AUTOMATIC_RETRY')
                    pending=read_ref(reference(completion))
                    if pending['disposition']!='CAPTURED':
                        atomic_json(active_path,dict(active,status='FAILED'))
                        raise RuntimeError('CAPTURE_FAILURE_REQUIRES_NEXT_AUTHORIZED_WINDOW')
                    phase('capture','RECOVERED_COMPLETE_CAPTURE_NO_NETWORK',captureReceipt=reference(completion))
                usage=usage_snapshot(capture_root,plan,clock())
                decision=due(bundle,plan,clock(),usage['lastAttemptUtc'])
                if pending is None and decision['due']:
                    if not enable_network:
                        phase('capture','NETWORK_DISABLED',planned=decision,usage=usage)
                    else:
                        validate_grant(release['refreshPlan'],grant_ref,release['deploymentId'],True,clock())
                        retained=plan.get('priorRetainedRawBytesConservative',0)
                        retained+=sum(p.stat().st_size for p in capture_root.rglob('response.json')) if capture_root.exists() else 0
                        reason=budget_reason(usage,plan,retained)
                        if reason:raise RuntimeError(reason)
                        directory=capture_root/'attempts'/ident
                        active={'status':'STARTED','directory':str(directory),'startedAtUtc':clock()}
                        atomic_json(active_path,active)
                        schedule_asset=next(x for x in plan['allowedAssets'] if x['endpoint']=='/games')
                        pending=(capturer or capture)(plan_ref=release['refreshPlan'],grant_ref=grant_ref,
                            deployment=release['deploymentId'],root=directory,enabled=True,
                            transport_factory=transport_factory,clock=clock,
                            selected=[schedule_asset],predecessor=bundle['sourceManifest'],conditional=True,
                            after_schedule=statistics_selector(plan,bundle['sourceManifest'],clock()))
                        result['providerCalls']=pending['providerCalls'];result['providerBytes']=pending['providerBytes']
                        phase('capture',pending['disposition'],captureReceipt=reference(directory/'completion.json'),usageBefore=usage)
                        if pending['disposition']!='CAPTURED':
                            atomic_json(active_path,dict(active,status='FAILED'))
                            raise RuntimeError('CAPTURE_FAILED_CLOSED:'+pending['reason'])
                        atomic_json(active_path,dict(active,status='CAPTURED'))
                        if fault:fault('captured')
                elif pending is None:phase('capture',decision['disposition'],planned=decision,usage=usage)
                if pending is not None:
                    if capture_pointer:
                        atomic_json(capture_pointer,{'schema':'CFB_CAPTURE_POINTER_V1','sourceManifest':pending['sourceManifest'],
                            'captureReceipt':reference(Path(active['directory'])/'completion.json')})
                    if pending['sourceManifest']['sha256']!=read_ref(current)['sourceManifest']['sha256']:
                        try:
                            current=admitter(manifest_ref=pending['sourceManifest'],release=release,registry_root=Path(input_pointer).parent)
                        except Exception:
                            atomic_json(active_path,dict(active,status='ADMISSION_FAILED'))
                            raise
                    phase('admission','ADMITTED_CAPTURE',inputVersion=current)
                    if fault:fault('admitted')
                    atomic_json(active_path,dict(active,status='ADMITTED'))
                elif active and active['status'] in ('FAILED','ADMISSION_FAILED'):
                    raise RuntimeError('PRIOR_CAPTURE_FAILED_PUBLICATION_BLOCKED_UNTIL_SUCCESSOR_CAPTURE')
            else:
                phase('capture','NETWORK_DISABLED_LOCAL_CAPTURE_POINTER_ONLY',authorizationProposal=release.get('refreshAuthorizationProposal'))
            if capture_pointer and Path(capture_pointer).exists():
                capture=read_ref(reference(capture_pointer))['sourceManifest']
                if capture['sha256']!=read_ref(current)['sourceManifest']['sha256']:
                    current=admitter(manifest_ref=capture,release=release,registry_root=Path(input_pointer).parent)
                    phase('admission','ADMITTED',inputVersion=current)
                    if fault:fault('admitted')
                else:phase('admission','REUSED_ADMITTED_VERSION',inputVersion=current)
            else:phase('admission','NO_NEW_CAPTURE',inputVersion=current)
            runner,bound=tick(bundle_ref=current,release_ref=release_ref,state_root=state,
                exchange_root=exchange_root,clock=clock,renderer=renderer,verifier=verifier,
                bundle_validator=bundle_validator,owner_lock_already_held=True)
            phase('publication',runner['disposition'],runnerReceipt=bound)
            result.update(disposition=runner['disposition'],exitCode=runner['exitCode'],runnerReceipt=bound)
            if release.get('finalResultEvidenceEnabled'):
                exported=final_exporter(bundle_ref=current,exchange_root=exchange_root,
                    capture_pointer=capture_pointer,clock=clock)
                phase('final-evidence',exported['disposition'],evidence=exported)
                result['finalResultEvidence']=exported
    except Exception as exc:
        phase('failure','FAILED_CLOSED',reason=str(exc),errorType=type(exc).__name__)
        result.update(disposition='FAILED_CLOSED',exitCode=1,reason=str(exc))
    existing={p['phase'] for p in result['phases']}
    for name in ('capture','admission','publication'):
        if name not in existing:phase(name,'SKIPPED_PRIOR_FAILURE')
    if 'runnerReceipt' not in result:
        result['runnerReceipt']=object_json(state/'runner-receipts',{'schema':'CFB_GEN1_SLATE_RUNNER_RECEIPT_V1',
            'invocationId':ident,'disposition':'PUBLICATION_SKIPPED','reason':result['disposition'],
            'exitCode':result['exitCode'],'createdAtUtc':clock()})
    result['completedAtUtc']=clock()
    return result,object_json(state/'owner-receipts',result)
