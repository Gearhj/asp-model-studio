"""One offline CFB admission/publication owner. No credential or HTTP capability."""
from pathlib import Path
import uuid
from .publication_io import reference
from .lifecycle import read_ref,now,object_json,owner_lock,tick
from .inputs import admit,validate_bundle
from .render import render,verify_package


def invoke(*,release_ref,input_pointer,state_root,exchange_root,capture_pointer=None,
           clock=now,renderer=render,verifier=verify_package,bundle_validator=validate_bundle,
           admitter=admit,fault=None):
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
            phase('capture','NETWORK_DISABLED_LOCAL_CAPTURE_POINTER_ONLY',authorizationProposal=release.get('refreshAuthorizationProposal'))
            current=read_ref(reference(input_pointer))['inputManifest']
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
