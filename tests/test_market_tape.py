from datetime import timedelta

import pytest

from server.market_intelligence.market_tape import (
    build_tape, consensus_at, decimal_from_american, instant, no_vig, pair_quotes, relief_proxy, rff_score,
)


def fixture():
    event={'event_id':'e','event_start':'2026-09-09T23:00:00+00:00','event_status':'FINAL',
        'home_score':5,'away_score':2,'outcome_available_at':'2026-09-10T03:00:00+00:00'}
    quotes=[]
    for hour,p in [(21,2.),(22,1.8)]:
        for book in ('a','b','c'):
            for side in ('HOME','AWAY'):
                t=f'2026-09-09T{hour}:00:00+00:00'
                quotes.append(dict(quote_id=f'{hour}{book}{side}',event_id='e',market_id='m',
                    market_type='MONEYLINE',period='full_game',side=side,point=None,bookmaker=book,
                    source='test_authority',source_mode='LIVE',observed_at=t,available_as_of=t,created_at=t,
                    decimal_odds=p if side=='HOME' else 2.2,american_odds=None,status='OPEN'))
    return event,quotes


def test_pairing_no_vig_and_no_cross_line_or_batch():
    event,quotes=fixture()
    pairs,excluded=pair_quotes(quotes,{'e':event})
    assert len(pairs)==6 and not excluded
    assert decimal_from_american(-125)==1.8
    assert no_vig(2.,2.)==.5
    assert all(0<p['no_vig_a']<1 for p in pairs)
    quotes[1]['available_as_of']='2026-09-09T21:00:01+00:00'
    pairs,excluded=pair_quotes(quotes,{'e':event})
    assert len(pairs)==5 and len(excluded)==2
    quotes=quotes[:2]
    for q in quotes: q.update(market_type='SPREAD',available_as_of=q['observed_at'])
    quotes[0]['point']=-1.5;quotes[1]['point']=2.5
    assert not pair_quotes(quotes,{'e':event})[0]


def test_checkpoint_targets_and_late_receipt_are_not_pregame_features():
    event,quotes=fixture()
    # Late local receipt cannot become an earlier valid quote by its observed clock.
    for q in quotes[6:]: q['created_at']='2026-09-09T23:01:00+00:00'
    pairs,_=pair_quotes(quotes,{'e':event})
    at=instant('2026-09-09T22:00:00+00:00')
    snap=consensus_at(pairs,at)
    assert snap['consensus_probability']==no_vig(2.,2.2)
    state=dict(event_id='e',scheduled_at=event['event_start'],status='SCHEDULED',is_postponed=False,
        observed_at='2026-09-09T01:00:00+00:00',available_as_of='2026-09-09T01:00:00+00:00',created_at='2026-09-09T01:00:00+00:00')
    tape=build_tape([event],quotes,[], '2026-09-10T04:00:00+00:00',game_states=[state])
    cp=next(r for r in tape['checkpoints'] if r['checkpoint']=='60M')
    assert cp['target_home_win']==1
    assert cp['closing_probability'] is None  # archived close is too stale, not manufactured
    assert cp['next_probability'] is None
    assert cp['model_probability'] is None
    _,fresh_quotes=fixture()
    postponed={**state,'status':'POSTPONED','is_postponed':True,
        'observed_at':'2026-09-09T21:50:00+00:00','available_as_of':'2026-09-09T21:50:00+00:00',
        'created_at':'2026-09-09T21:50:00+00:00'}
    changed=build_tape([event],fresh_quotes,[], '2026-09-10T04:00:00+00:00',game_states=[state,postponed])
    opening=next(r for r in changed['checkpoints'] if r['checkpoint']=='2H')
    assert opening['next_probability'] is None and opening['closing_probability'] is None
    event['event_start']='2026-08-20T23:00:00+00:00'
    with pytest.raises(ValueError,match='FINAL_OOT_SEALED'):
        build_tape([event],quotes,[], '2026-09-10T04:00:00+00:00')


def test_rff_missingness_is_an_interval_not_renormalization():
    value=rff_score({'cross_book_dispersion':.5})
    assert value['score_lower']==5 and value['score_upper']==95
    assert value['evidence_coverage_pct']==10 and value['status']=='PROVISIONAL_RFF'
    assert value['components']['handle_concentration'] is None
    relief=relief_proxy(.75,.25,2.,2.)
    assert relief['net_if_a']==-.5 and relief['net_if_b']==.5
    with pytest.raises(ValueError): relief_proxy(.8,.8,2.,2.)
