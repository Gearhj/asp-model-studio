"""Synthetic transport/season fixtures. No live acquisition or real forecasts."""
import copy
import io
import json
from pathlib import Path

import pandas as pd
import pytest

from test_nba_slate_publisher import space, env, Renderer, verifier
from server.sports_nba_gen1.authority import reference
from server.sports_nba_gen1.production import digest
from server.sports_nba_gen1.slate_lifecycle import atomic_json, immutable, object_json, read_ref
from server.sports_nba_gen1.slate_owner import invoke
from server.sports_nba_gen1.slate_refresh import capture, refresh_due, schema_description


STAMP = '2030-10-21T02:00:00+00:00'


def fixture(space):
    raw = io.BytesIO()
    pd.DataFrame({'fixture_only':[1], 'meaning':['NOT_PROVIDER_DATA']}).to_parquet(raw,index=False)
    raw = raw.getvalue()
    source = immutable(space/'original.parquet', raw)
    cr = object_json(space/'capture', {'source':source, 'capturedAtUtc':'2030-10-20T00:00:00+00:00',
        'responseHeaders':{'ETag':'"synthetic"'}, 'httpStatus':200})
    rights = object_json(space/'synthetic-rights', {'classification':'SYNTHETIC_TEST_ONLY'})
    plan = {'schema':'SYNTHETIC_PLAN_NOT_LIVE', 'validFromUtc':'2030-10-01T00:00:00+00:00',
        'validUntilUtc':'2030-11-01T00:00:00+00:00', 'expectedPhysicalSchema':schema_description(raw),
        'minimumAttemptSpacingMinutes':60,'maximumCaptureAttemptsPerUtcDay':8,
        'maximumHttpRequestsPerInvocation':4,'maximumResponseBytesPerInvocation':1024**2,
        'maximumResponseBytesPerUtcDay':8*1024**2,'maximumRetainedStorageBytes':100*1024**2,
        'rightsEvidence':[rights],'assets':[{'url':'https://invalid.test/synthetic-never-network'}]}
    pr = object_json(space/'plan', plan)
    proposal = object_json(space/'proposal', {'deploymentId':'SYNTHETIC'})
    grant = object_json(space/'grant', {'schema':'NBA_SAME_OWNER_REFRESH_GRANT_V1', 'approvedBy':'James',
        'liveCaptureAuthorized':True, 'proposalSha256':proposal['sha256'], 'refreshPlanSha256':pr['sha256'],
        'deploymentId':'SYNTHETIC', 'validFromUtc':plan['validFromUtc'],'validUntilUtc':plan['validUntilUtc']})
    b, _, _ = env(space, 2)
    for row in b['games']:
        row['target'].update(season_type='REGULAR',neutral_site=False)
    b['captureReceipt']=cr
    b['predictionInputIdentity']='synthetic-old'
    br = object_json(space/'input',b)
    pointer=space/'registry/current.json'
    atomic_json(pointer, {'inputManifest':br})
    release={'refreshPlan':pr, 'refreshAuthorizationProposal':proposal, 'baseModelReceipt':rights,
        'baseCoverage':rights,'prospectiveEffectiveAtUtc':'2030-01-01T00:00:00+00:00'}
    rr=object_json(space/'release',release)
    return dict(raw=raw,source=source,capture=cr,plan=plan,release=release,release_ref=rr,
                grant=grant,bundle=b,pointer=pointer)


def transport(status=304, body=b''):
    def fetch(headers, plan, meter):
        assert headers == {'If-None-Match':'"synthetic"'}
        meter('request',1)
        meter('bytes',len(body))
        return {'status':status,'body':body,'headers':{'ETag':'"synthetic"'}}
    return fetch


def test_not_due_and_default_disabled_have_zero_network_intent(space, monkeypatch):
    f=fixture(space)
    monkeypatch.setattr('server.sports_nba_gen1.slate_refresh.http_fetch', lambda *a:pytest.fail('LIVE HTTP'))
    r=refresh_due(f['bundle'],read_ref(f['capture']),{'attempts':[]},f['plan'],'2030-10-01T01:00:00Z')
    assert r['due'] is False and r['networkIntentRequests']==0
    for enabled,grant in [(False,f['grant']),(True,None)]:
        with pytest.raises(PermissionError):
            capture(release=f['release'], latest_ref=f['capture'], private_root=space/'private',
                    enabled=enabled,grant_ref=grant,clock=lambda:STAMP)
    out,_=invoke(release_ref=f['release_ref'], input_pointer=f['pointer'], state_root=space/'state',
        exchange_root=space/'fixture-exchange',clock=lambda:STAMP,bundle_validator=lambda *a:None,
        renderer=Renderer(),verifier=verifier)
    assert out['disposition']=='LIVE_ACQUISITION_NOT_AUTHORIZED' and out['providerCalls']==0
    assert [p['phase'] for p in out['phases']]==['planning','capture','admission','publication']
    assert not (space/'fixture-exchange').exists()


@pytest.mark.parametrize('status',[304,200])
def test_unchanged_retains_original_bytes_clock_and_conditional_receipt(space,status):
    f=fixture(space)
    bound=capture(release=f['release'],latest_ref=f['capture'],private_root=space/'private',
        enabled=True,grant_ref=f['grant'],clock=lambda:STAMP,
        transport=transport(status,f['raw'] if status==200 else b''))
    saved=read_ref(bound)
    assert saved['source']==f['source'] and saved['capturedAtUtc']==read_ref(f['capture'])['capturedAtUtc']
    assert saved['validatedAtUtc']==STAMP and saved['httpRequests']==1
    assert not list((space/'private/objects').rglob('*.parquet'))
    assert saved['priorObjectReceipt']==f['capture']


def synthetic_admitter(f, clock=STAMP, fail=False):
    def admitter(**kw):
        b=copy.deepcopy(f['bundle'])
        c=read_ref(kw['capture_ref'])
        b.update(captureReceipt=kw['capture_ref'],scheduleValidatedAtUtc=c['validatedAtUtc'],
                 historyCompleteThroughUtc=c['validatedAtUtc'],predictionInputIdentity=c['source']['sha256'])
        kw['precommit'](b)
        if fail:
            raise ValueError('SYNTHETIC_ADMISSION_REJECTION')
        br=object_json(Path(kw['registry_root'])/'versions',b)
        atomic_json(Path(kw['registry_root'])/'current.json',{'inputManifest':br})
        return br
    return admitter


@pytest.mark.parametrize('interruption',[None,'captured','admitted'])
def test_capture_admit_multigame_recovery_no_duplicate_requests_or_forecasts(space,interruption):
    f=fixture(space)
    raw=io.BytesIO()
    pd.DataFrame({'fixture_only':[2], 'meaning':['NOT_PROVIDER_DATA']}).to_parquet(raw,index=False)
    render=Renderer()
    def fault(phase):
        if phase==interruption:
            raise RuntimeError('SYNTHETIC_PROCESS_INTERRUPTION')
    kw=dict(release_ref=f['release_ref'],input_pointer=f['pointer'],state_root=space/'state',
        exchange_root=space/'fixture-exchange',clock=lambda:STAMP,enabled=True,grant_ref=f['grant'],
        renderer=render,verifier=verifier,bundle_validator=lambda *a:None,admitter=synthetic_admitter(f))
    first,_=invoke(**kw,transport=transport(200,raw.getvalue()),fault=fault)
    assert first['providerCalls']==1
    if interruption:
        assert first['disposition']=='FAILED_CLOSED'
        assert render.calls==0
    second,_=invoke(**kw,transport=lambda *a:pytest.fail('No repeated HTTP after retained capture'))
    assert second['providerCalls']==0 and second['exitCode']==0
    assert render.calls==2
    third,_=invoke(**kw,transport=lambda *a:pytest.fail('No HTTP on ordinary tick'))
    assert third['disposition']=='REUSED_IMMUTABLE' and render.calls==2
    discovery=read_ref(read_ref(third['runnerReceipt'])['discovery'])
    assert len(discovery['packages'])==2
    assert {x['phase'] for x in second['phases']} >= {'planning','capture','admission','publication'}


def test_failed_admission_preserves_pointer_and_prior_discovery(space):
    f=fixture(space)
    before=f['pointer'].read_bytes()
    discovery=space/'fixture-exchange/slate-discovery/current.json'
    atomic_json(discovery,{'synthetic':'prior-immutable-reference'})
    prior=discovery.read_bytes()
    result,_=invoke(release_ref=f['release_ref'],input_pointer=f['pointer'],state_root=space/'state',
        exchange_root=space/'fixture-exchange',clock=lambda:STAMP,enabled=True,grant_ref=f['grant'],
        transport=transport(),renderer=Renderer(),verifier=verifier,bundle_validator=lambda *a:None,
        admitter=synthetic_admitter(f,fail=True))
    assert result['exitCode']==1 and f['pointer'].read_bytes()==before and discovery.read_bytes()==prior
    assert any(x['disposition']=='REJECTED_POINTER_UNCHANGED' for x in result['phases'])
    assert list((space/'state/runner-receipts').rglob('receipt.json'))


def test_schema_drift_quarantine_no_retry(space):
    f=fixture(space)
    body=io.BytesIO()
    pd.DataFrame({'wrong_field':[1]}).to_parquet(body,index=False)
    kw=dict(release=f['release'],latest_ref=f['capture'],private_root=space/'private',
            enabled=True,grant_ref=f['grant'],clock=lambda:STAMP)
    with pytest.raises(ValueError,match='SCHEMA_DRIFT'):
        capture(**kw,transport=transport(200,body.getvalue()))
    assert (space/'private/HALTED.json').exists()
    assert len(list((space/'private/objects').rglob('*.parquet')))==1
    with pytest.raises(RuntimeError,match='HALTED'):
        capture(**kw,transport=lambda *a:pytest.fail('No retry'))


def test_budget_and_exact_grant_gates(space):
    f=fixture(space)
    grant=read_ref(f['grant']); grant['deploymentId']='WRONG'
    with pytest.raises(PermissionError,match='EXACT_REFRESH_GRANT'):
        capture(release=f['release'],latest_ref=f['capture'],private_root=space/'private',
            enabled=True,grant_ref=object_json(space/'bad',grant),clock=lambda:STAMP,
            transport=lambda *a:pytest.fail('No HTTP'))
    attempts=[dict(startedAtUtc='2030-10-21T00:00:00Z',reservedResponseBytes=1024**2,
                   httpRequests=1,responseBodyBytes=0,disposition='CONDITIONAL_UNCHANGED') for _ in range(8)]
    atomic_json(space/'private/usage.json',{'attempts':attempts})
    with pytest.raises(RuntimeError,match='UTC_DAY_REQUEST'):
        capture(release=f['release'],latest_ref=f['capture'],private_root=space/'private',
            enabled=True,grant_ref=f['grant'],clock=lambda:STAMP,transport=lambda *a:pytest.fail('No HTTP'))


def test_preseason_daily_postgame_and_dst_policy(space):
    f=fixture(space)
    b=f['bundle']; c=read_ref(f['capture'])
    c['validatedAtUtc']='2030-10-21T13:59:00+00:00'
    assert 'DAILY_SCHEDULE_STATUS_AND_CORRECTIONS' in refresh_due(b,c,{},f['plan'],'2030-10-21T14:00:00Z')['reasons']
    c['validatedAtUtc']='2030-10-22T03:00:00+00:00'
    assert 'POSTGAME_FINAL_AVAILABILITY_CHECK' in refresh_due(b,c,{},f['plan'],'2030-10-22T04:00:00Z')['reasons']
    for r in b['games']:
        r['target']['scheduled_tipoff_utc']='2030-11-10T00:00:00Z'
    f['plan']['validUntilUtc']='2030-12-01T00:00:00Z'
    c['validatedAtUtc']='2030-11-09T14:59:00+00:00'
    assert 'DAILY_SCHEDULE_STATUS_AND_CORRECTIONS' in refresh_due(b,c,{},f['plan'],'2030-11-09T15:00:00Z')['reasons']


def test_validation_only_304_reuses_original_forecast_binding(space):
    f=fixture(space)
    render=Renderer()
    kw=dict(release_ref=f['release_ref'],input_pointer=f['pointer'],state_root=space/'state',
        exchange_root=space/'fixture-exchange',enabled=True,grant_ref=f['grant'],
        renderer=render,verifier=verifier,bundle_validator=lambda *a:None,admitter=synthetic_admitter(f))
    one,_=invoke(**kw,clock=lambda:STAMP,transport=transport())
    first=read_ref(one['runnerReceipt'])
    assert render.calls==2
    # Daily revalidation at 10 EDT, original raw bytes and forecast input binding unchanged.
    two,_=invoke(**kw,clock=lambda:'2030-10-21T14:00:00+00:00',transport=transport())
    assert two['providerCalls']==1 and two['disposition']=='REUSED_IMMUTABLE' and render.calls==2
    second=read_ref(two['runnerReceipt'])
    assert second['input'] != first['input']
    assert [x['package'] for x in first['games']]==[x['package'] for x in second['games']]


def test_pending_final_recovers_on_next_bounded_capture(space):
    f=fixture(space)
    def pending(**kw):
        raise ValueError('SOURCE_FINAL_PENDING:synthetic:1')
    kw=dict(release_ref=f['release_ref'],input_pointer=f['pointer'],state_root=space/'state',
        exchange_root=space/'fixture-exchange',enabled=True,grant_ref=f['grant'],
        renderer=Renderer(),verifier=verifier,bundle_validator=lambda *a:None)
    first,_=invoke(**kw,clock=lambda:STAMP,transport=transport(),admitter=pending)
    assert first['exitCode']==1 and first['providerCalls']==1
    again,_=invoke(**kw,clock=lambda:STAMP,transport=lambda *a:pytest.fail('No retries'),admitter=pending)
    assert again['providerCalls']==0
    fixed,_=invoke(**kw,clock=lambda:'2030-10-21T14:00:00+00:00',transport=transport(),admitter=synthetic_admitter(f))
    assert fixed['exitCode']==0 and fixed['providerCalls']==1


def test_interrupted_unknown_transport_reservation_never_retries(space):
    f=fixture(space)
    atomic_json(space/'state/refresh/usage.json',{'attempts':[dict(startedAtUtc=STAMP,
        disposition='RESERVED',httpRequests=1,responseBodyBytes=0,reservedResponseBytes=1024**2)]})
    result,_=invoke(release_ref=f['release_ref'],input_pointer=f['pointer'],state_root=space/'state',
        exchange_root=space/'fixture-exchange',enabled=True,grant_ref=f['grant'],clock=lambda:STAMP,
        bundle_validator=lambda *a:None,transport=lambda *a:pytest.fail('No retry'))
    assert result['reason']=='INTERRUPTED_CAPTURE_REVIEW_REQUIRED_NO_RETRY'
    assert result['providerCalls']==0


def test_capture_failure_has_durable_phase_and_prevents_publication(space):
    f=fixture(space)
    def refusal(*args):
        args[2]('request',1)
        raise ValueError('SYNTHETIC_ACCESS_REFUSAL')
    result,_=invoke(release_ref=f['release_ref'],input_pointer=f['pointer'],state_root=space/'state',
        exchange_root=space/'fixture-exchange',enabled=True,grant_ref=f['grant'],clock=lambda:STAMP,
        bundle_validator=lambda *a:None,transport=refusal)
    assert result['providerCalls']==1 and result['exitCode']==1
    assert any(p['disposition']=='CAPTURE_FAILED_CLOSED' for p in result['phases'])
    assert not (space/'fixture-exchange').exists()
