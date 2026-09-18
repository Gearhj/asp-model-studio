"""Consumer evidence shares the one publisher lock and preserves failure status."""
from pathlib import Path
import uuid
import pytest
from server.sports_cfb_gen1 import owner
from server.sports_cfb_gen1.lifecycle import atomic_json, object_json, owner_lock, read_ref


@pytest.mark.parametrize('paper_exit', [0, 1])
def test_paper_phase_uses_current_discovery_under_owner_lock_and_propagates_failure(paper_exit, monkeypatch):
    root=Path(__file__).resolve().parents[1]/'outputs/cfb-consumer-owner-fixtures'/uuid.uuid4().hex
    root.mkdir(parents=True)
    bundle=object_json(root/'bundle',{'sourceManifest':{'sha256':'synthetic'}})
    pointer=root/'inputs/current.json';atomic_json(pointer,{'inputManifest':bundle})
    grant=object_json(root/'grant',{'synthetic':True})
    release=object_json(root/'release',{'paperEligibilityAuthorization':grant})
    discovery=object_json(root/'discovery',{'synthetic':True})
    def tick(**kwargs):
        result={'disposition':'REUSED_IMMUTABLE','exitCode':0,'discovery':discovery}
        return result,object_json(root/'runner',result)
    monkeypatch.setattr(owner,'tick',tick)
    calls=[]
    def paper(**kwargs):
        assert kwargs['discovery_ref']==discovery and kwargs['grant_ref']==grant
        assert kwargs['exchange_family_root']==root/'exchange/cfb-gen1-research-v1'
        with pytest.raises(RuntimeError,match='OWNER_BUSY'):
            with owner_lock(root/'state/publisher.lock'): pass
        calls.append('paper')
        result={'exitCode':paper_exit,'publishedCount':0,'reusedCount':2}
        return dict(result,receipt=object_json(root/'paper',result))
    result,_=owner.invoke(release_ref=release,input_pointer=pointer,state_root=root/'state',
        exchange_root=root/'exchange/cfb-gen1-production-v1',paper_publisher=paper,
        clock=lambda:'2030-09-01T00:00:00Z')
    assert calls==['paper'] and result['providerCalls']==0
    assert result['exitCode']==paper_exit
    assert result['disposition']==('PARTIAL_FAILURE' if paper_exit else 'REUSED_IMMUTABLE')
    assert read_ref(result['runnerReceipt'])['disposition']=='REUSED_IMMUTABLE'
