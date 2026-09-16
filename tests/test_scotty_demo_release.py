"""Focused release failures; synthetic examples are not forecasting evidence."""
from copy import deepcopy
import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

from scripts.scotty_demo_release import (
    SCHEMA, DECLARATION, canonical, clock, chronology, joint_summary, agree,
    probabilities, publish, validate_release, verify_package_directory, write,
)


@pytest.fixture
def tmp_path():
    # Inherit the authorized workspace ACL. pytest's mode-0700 directories are
    # unreadable under this Windows sandbox; never change an existing ACL.
    root=Path(os.environ.get('ASP_DEMO_TEST_ROOT',tempfile.gettempdir()))
    result=root/('demo-release-test-'+uuid.uuid4().hex)
    result.mkdir(parents=True)
    return result


def fixture_release():
    return {'schemaVersion':SCHEMA,'champions':[
        {'schemaVersion':DECLARATION,'sport':s,'modelIdentity':{},'channels':{},
         'training':{},'featureContract':{},'limitations':[],'historicalMetrics':{},'authority':{}}
        for s in ['MLB','NFL','NBA','CFB']], 'forecasts':[],
        'authority':dict.fromkeys(['modelPromotion','wagering','positions','schedulerActivation','aispWrites'],False)}


def test_unicode_and_nonfinite():
    assert b'\xe2\x80\x94' in canonical({'name':'research — demo'})
    assert canonical({'name':'research — demo'}) == json.dumps({'name':'research — demo'},ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    with pytest.raises(ValueError):canonical({'x':float('nan')})


def test_clock_dst_and_midnight():
    x=chronology('2026-09-16T14:00:00Z','2026-09-16T14:01:00Z','2026-09-16T14:02:00Z','2026-09-21T00:20:00Z')
    assert x['scheduledStartEastern']=='2026-09-20T20:20:00-04:00'
    x=chronology('2026-11-01T01:00:00Z','2026-11-01T01:01:00Z','2026-11-01T01:02:00Z','2026-11-01T07:00:00Z')
    assert x['scheduledStartEastern']=='2026-11-01T02:00:00-05:00'
    with pytest.raises(ValueError):clock('2026-09-16T14:00:00')


@pytest.mark.parametrize('clocks',[
    ('14:02','14:01','14:03','15:00'),('14:00','14:01','15:00','15:00'),('14:00','14:03','14:02','15:00')])
def test_chronology_fails_closed(clocks):
    with pytest.raises(ValueError):chronology(*['2026-09-16T'+x+':00Z' for x in clocks])


def test_probability_and_joint_accounting():
    probabilities(.4,.55,.05)
    with pytest.raises(ValueError):probabilities(40,55,5)
    with pytest.raises(ValueError):probabilities(.4,.6,.05)
    s=joint_summary([21,7,10],[10,14,10],[2,1,1])
    assert s['drawCount']==4 and s['homeWin']==.5 and s['tie']==.25
    assert s['expectedHome']==14.75 and s['expectedAway']==11
    with pytest.raises(ValueError):agree(s['expectedHome'],s['expectedAway'])
    with pytest.raises(ValueError):joint_summary([1],[2],[.5])


def test_authority_and_horizon():
    d=fixture_release();validate_release(d)
    bad=deepcopy(d);bad['authority']['modelPromotion']=True
    with pytest.raises(ValueError):validate_release(bad)
    bad=deepcopy(d);bad['forecasts']=[{'horizon':'SHOW_PREVIEW','consumerUse':'FINAL_PREGAME','marketAuthorityGrantedByRelease':False}]
    with pytest.raises(ValueError):validate_release(bad)
    bad=deepcopy(d);bad['champions']=bad['champions'][:-1]
    with pytest.raises(ValueError):validate_release(bad)


def test_atomic_publish_replay_and_tamper(tmp_path):
    stage=tmp_path/'stage';stage.mkdir();write(stage/'release.json',fixture_release())
    exchange=tmp_path/'exchange'
    a=publish(stage,exchange)
    b=publish(stage,exchange)
    assert a==b
    assert len(json.loads(Path(a['discovery']['path']).read_bytes())['releases'])==1
    dest=Path(a['package'])
    assert verify_package_directory(dest)['packageContentSha256']==dest.name
    (dest/'release.json').write_bytes(b'{}')
    with pytest.raises(ValueError):verify_package_directory(dest)
    with pytest.raises(ValueError):publish(stage,exchange)
    assert not (exchange/'demo-releases-v1/publication.lock').exists()


def test_invalid_release_not_discovered(tmp_path):
    stage=tmp_path/'stage';stage.mkdir();bad=fixture_release();bad['authority']['wagering']=True
    write(stage/'release.json',bad)
    with pytest.raises(ValueError):publish(stage,tmp_path/'exchange')
    assert not (tmp_path/'exchange/demo-releases-v1/discovery.json').exists()
