"""Point-in-time, two-sided market tape. All clocks are UTC and fail closed.

The 60-minute quote-age limit is a fixed research measurement convention, not
an AISP selection rule. Scheduled starts are conservative proxies, never claimed
to be verified first-pitch timestamps. Closing targets are unavailable for future
events and do not enter the feature dictionary.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from statistics import mean, pstdev
from typing import Any

CHECKPOINTS = [('24H',1440), ('6H',360), ('2H',120), ('60M',60),
               ('30M',30), ('15M',15), ('5M',5)]
COMPONENTS = ('ticket_concentration','handle_concentration','relief_asymmetry_proxy',
    'reverse_line_movement','late_synchronized_movement','cross_book_dispersion',
    'model_market_disagreement','prediction_market_disagreement','unresolved_availability',
    'abnormal_narrative_concentration')
MAX_AGE = timedelta(minutes=60)


def instant(value):
    if value is None:
        raise ValueError('Missing timestamp')
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Naive timestamp')
    return result.astimezone(timezone.utc)


def iso(value):
    return value.isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        allow_nan=False).encode()).hexdigest()


def decimal_from_american(value):
    value = float(value)
    if abs(value) < 100:
        raise ValueError('Invalid American price')
    return 1 + (value / 100 if value > 0 else 100 / -value)


def no_vig(a, b):
    if not all(math.isfinite(v) and v > 1 for v in (a, b)):
        raise ValueError('Invalid decimal price')
    return (1/a) / (1/a + 1/b)


def sealed(value):
    from zoneinfo import ZoneInfo
    t = instant(value)
    return any('2026-08-14' <= d <= '2026-08-27' for d in (
        t.date().isoformat(), t.astimezone(ZoneInfo('America/New_York')).date().isoformat()))


def pair_quotes(quotes, events):
    """Pair exact provider observation batches; never mix books, times or lines."""
    groups, exclusions = defaultdict(list), []
    for original in quotes:
        q = dict(original)
        reasons = []
        try:
            event = events[q['event_id']]
            if sealed(event['event_start']):
                raise ValueError('FINAL_OOT_SEALED')
            kind = str(q['market_type']).upper()
            kind = {'RUN_LINE':'SPREAD', 'TOTALS':'TOTAL'}.get(kind, kind)
            side = str(q.get('side','')).upper()
            if kind not in ('MONEYLINE','SPREAD','TOTAL') or side not in (
                    ('OVER','UNDER') if kind == 'TOTAL' else ('HOME','AWAY')):
                raise ValueError('UNSUPPORTED_MARKET_OR_SIDE')
            d = float(q['decimal_odds'])
            if not math.isfinite(d) or d <= 1:
                raise ValueError('INVALID_PRICE')
            if q.get('american_odds') is not None and abs(decimal_from_american(q['american_odds'])-d)>0.00011:
                raise ValueError('AMERICAN_DECIMAL_MISMATCH')
            observed, available, created = [instant(q[n]) for n in ('observed_at','available_as_of','created_at')]
            if observed > available:
                raise ValueError('AVAILABILITY_PRECEDES_OBSERVATION')
            if str(q.get('source_mode','')).upper() != 'LIVE':
                raise ValueError('NON_LIVE_SOURCE')
            if str(q.get('status','')).upper() != 'OPEN':
                raise ValueError('NON_OPEN_QUOTE')
            if not q.get('source') or str(q['source']).lower() == 'unknown':
                raise ValueError('UNKNOWN_SOURCE')
            point = None if kind == 'MONEYLINE' else float(q['point'])
            if point is not None and not math.isfinite(point):
                raise ValueError('INVALID_LINE')
            line = -point if kind == 'SPREAD' and side == 'AWAY' else point
            key = (q['event_id'], q['market_id'], kind, q['period'], line,
                   q['bookmaker'], q['source'], iso(observed), iso(available))
            q.update(market_type=kind, side=side, decimal_odds=d,
                     operational_at=iso(max(observed, available, created)), implied_probability_computed=1/d)
            groups[key].append(q)
        except (ValueError, KeyError, TypeError) as exc:
            reasons.append(str(exc))
        if reasons:
            exclusions.append({'quote_id':q.get('quote_id'),'event_id':q.get('event_id'),'reasons':reasons})
    pairs = []
    for key, values in groups.items():
        sides = ('OVER','UNDER') if key[2] == 'TOTAL' else ('HOME','AWAY')
        by_side = {s:[q for q in values if q['side']==s] for s in sides}
        if any(not v for v in by_side.values()) or any(len({q['decimal_odds'] for q in v})>1 for v in by_side.values()):
            exclusions.extend({'quote_id':q['quote_id'],'event_id':q['event_id'],
                'reasons':['UNPAIRED_OR_CONFLICTING_BATCH']} for q in values)
            continue
        # Identical repeated records do not increase source breadth or delay the original pair.
        a,b = [min(by_side[s],key=lambda q:(q['operational_at'],q['quote_id'])) for s in sides]
        pair = dict(event_id=key[0],market_id=key[1],market_type=key[2],period=key[3],line=key[4],
            bookmaker=key[5],source=key[6],observed_at=key[7],available_as_of=key[8],
            operational_at=max(a['operational_at'],b['operational_at']),
            side_a=sides[0],side_b=sides[1],decimal_a=a['decimal_odds'],decimal_b=b['decimal_odds'],
            quote_ids=[a['quote_id'],b['quote_id']],no_vig_a=no_vig(a['decimal_odds'],b['decimal_odds']))
        pair['pair_id'] = digest(pair)
        pair['probability_basis']='CONDITIONAL_ON_NO_PUSH' if key[2] in ('SPREAD','TOTAL') and float(key[4]).is_integer() else 'TWO_SIDED_RESOLVED_CONTRACT'
        pairs.append(pair)
    return sorted(pairs,key=lambda p:(p['operational_at'],p['pair_id'])), exclusions


def consensus_at(pairs, at):
    latest = {}
    for p in pairs:
        if instant(p['operational_at']) <= at:
            old = latest.get(p['bookmaker'])
            if old is None or (p['observed_at'],p['operational_at'],p['pair_id']) > (old['observed_at'],old['operational_at'],old['pair_id']):
                latest[p['bookmaker']] = p
    fresh = {b:p for b,p in latest.items() if timedelta(0)<=at-instant(p['observed_at'])<=MAX_AGE}
    if not fresh:
        return {'status':'STALE_ONLY' if latest else 'NO_PRIOR_PAIR', 'stale_books':len(latest), 'book_count':0}
    probabilities = [p['no_vig_a'] for p in fresh.values()]
    return {'status':'SUPPORTED', 'consensus_probability':mean(probabilities),
        'book_count':len(fresh),'source_count':len({p['source'] for p in fresh.values()}),
        'stale_books':len(latest)-len(fresh), 'cross_book_range':max(probabilities)-min(probabilities),
        'dispersion':pstdev(probabilities),'best_decimal_a':max(p['decimal_a'] for p in fresh.values()),
        'best_decimal_b':max(p['decimal_b'] for p in fresh.values()),
        'oldest_quote_age_seconds':max((at-instant(p['observed_at'])).total_seconds() for p in fresh.values()),
        'newest_quote_age_seconds':min((at-instant(p['observed_at'])).total_seconds() for p in fresh.values()),
        'book_pairs':fresh}


def timely_forecast(forecasts, at, start):
    eligible = []
    for f in forecasts:
        try:
            clocks = [instant(f[k]) for k in ('generated_at','available_as_of','created_at','evidence_cutoff')]
            # PUBLISHED availability only; research DRAFT is not silently substituted for visible Gen1.
            clocks.append(instant(f['published_at']))
            p = float(f['home_probability'])
            if max(clocks)<=at<start and 0<p<1 and str(f['source_mode']).upper()=='LIVE' and str(f['status']).upper()=='PUBLISHED':
                eligible.append(f)
        except (ValueError,KeyError,TypeError):
            continue
    return max(eligible,key=lambda f:(f['published_at'],f['generated_at'],f['forecast_id'])) if eligible else None


def rff_score(values):
    """Equal fixed weights; unknowns widen bounds, never rescale known evidence."""
    known = {k:float(v) for k,v in values.items() if k in COMPONENTS and v is not None}
    if any(not math.isfinite(v) or not 0<=v<=1 for v in known.values()):
        raise ValueError('RFF component outside [0,1]')
    lower = 10*sum(known.values())
    return {'contract':'RFF_COMPONENT_CONTRACT_V1','status':'COMPLETE_RESEARCH_RFF' if len(known)==10 else 'PROVISIONAL_RFF',
        'supported_points':lower, 'score_lower':lower, 'score_upper':lower+10*(10-len(known)),
        'evidence_coverage_pct':10*len(known), 'components':{k:known.get(k) for k in COMPONENTS},
        'essential_handle_available':'handle_concentration' in known,
        'interpretation':'MARKET_IMBALANCE_AND_UNCERTAINTY_NOT_FIXING_OR_WAGERING_EDGE'}


def relief_proxy(handle_a,handle_b,decimal_a,decimal_b):
    if not all(math.isfinite(v) for v in (handle_a,handle_b,decimal_a,decimal_b)) or min(handle_a,handle_b)<0 or abs(handle_a+handle_b-1)>1e-8:
        raise ValueError('Need coherent normalized same-source two-sided handle')
    no_vig(decimal_a,decimal_b)
    return {'net_if_a':1-handle_a*decimal_a,'net_if_b':1-handle_b*decimal_b,
            'label':'NORMALIZED_HANDLE_RELIEF_PROXY_NOT_ACTUAL_LIABILITY'}


def comparable_prediction_market(rows,at):
    eligible = {}
    for p in rows:
        try:
            if p.get('market_type')!='FULL_GAME_MONEYLINE' or p.get('semantics_status')!='SEMANTICS_MATCHED' or p.get('mapping_status') not in ('MATCHED','EXACT'):
                continue
            clocks=[instant(p[k]) for k in ('provider_observed_at','aisp_received_at','created_at','mapping_decided_at')]
            if max(clocks)>at or at-clocks[0]>timedelta(minutes=15) or p.get('in_play') or not p.get('pregame_eligible') or not p.get('quote_fresh') or not p.get('book_complete'):
                continue
            if p.get('selection') not in ('HOME','AWAY') or p.get('midpoint') is None:
                continue
            v=float(p['midpoint'])
            if not 0<v<1: continue
            p_home=v if p['selection']=='HOME' else 1-v
            old=eligible.get(p['provider'])
            if old is None or clocks[0]>old[0]: eligible[p['provider']]=(clocks[0],p_home,p.get('snapshot_id',p.get('id')))
        except (ValueError,TypeError,KeyError):
            continue
    return {'probability':mean(v[1] for v in eligible.values()),'snapshot_ids':[v[2] for v in eligible.values()]} if eligible else None


def schedule_status(states,event,at):
    known=[]
    for s in states:
        try:
            if max(instant(s[k]) for k in ('observed_at','available_as_of','created_at'))<=at:
                known.append(s)
        except (KeyError,ValueError,TypeError):
            continue
    if not known: return 'SCHEDULE_AS_OF_UNAVAILABLE',None
    state=max(known,key=lambda s:(s['available_as_of'],s['observed_at'],s.get('observation_id','')))
    if state.get('is_postponed') or str(state.get('status')).upper() in ('POSTPONED','CANCELED','CANCELLED','IN_PROGRESS','LIVE','FINAL'):
        return 'EVENT_NOT_CONFIRMED_PREGAME',state.get('observation_id')
    if instant(state['scheduled_at'])!=instant(event['event_start']):
        return 'SCHEDULE_REVISION_DIFFERS_AT_CHECKPOINT',state.get('observation_id')
    return 'SUPPORTED',state.get('observation_id')


def build_tape(events,quotes,forecasts,captured_at,prediction_markets=(),game_states=()):
    """Return paired tape, checkpoints, transparent RFF ledger and accounting."""
    event_map={e['event_id']:e for e in events}
    if any(sealed(e['event_start']) for e in events):
        raise ValueError('FINAL_OOT_SEALED: source export must exclude events before payload read')
    pairs,excluded=pair_quotes(quotes,event_map)
    by_series=defaultdict(list)
    by_forecast,by_pm,by_state=defaultdict(list),defaultdict(list),defaultdict(list)
    for f in forecasts: by_forecast[f['event_id']].append(f)
    for p in prediction_markets: by_pm[p['event_id']].append(p)
    for s in game_states: by_state[s['event_id']].append(s)
    for p in pairs:
        by_series[(p['event_id'],p['market_id'],p['market_type'],p['period'],p['line'])].append(p)
    captured=instant(captured_at)
    checkpoints,ledger=[],[]
    for key,series in sorted(by_series.items(),key=str):
        event=event_map[key[0]]
        start=instant(event['event_start'])
        # A recorded actual start can make cutoff earlier, never later than schedule.
        if event.get('actual_start_at'): start=min(start,instant(event['actual_start_at']))
        valid=[p for p in series if instant(p['operational_at'])<start]
        if not valid: continue
        opening=min(instant(p['operational_at']) for p in valid)
        closing_at=max(instant(p['operational_at']) for p in valid) if captured>=start else None
        last=consensus_at(series,closing_at) if closing_at else {}
        closing_ok=bool(closing_at and start-closing_at<=MAX_AGE and last.get('book_count',0)>=2 and
            schedule_status(by_state[key[0]],event,closing_at)[0]=='SUPPORTED')
        times=[('OPENING',opening)]+[(name,start-timedelta(minutes=m)) for name,m in CHECKPOINTS]
        if closing_at: times.append(('LAST_PREGAME',closing_at))
        for name,at in times:
            if at>=start or at>captured: continue
            snap=consensus_at(series,at)
            row={k:v for k,v in snap.items() if k!='book_pairs'}
            row.update(event_id=key[0],event_start=iso(start),market_id=key[1],market_type=key[2],
                period=key[3],line=key[4],checkpoint=name,checkpoint_at=iso(at),
                start_authority='MIN_SCHEDULED_AND_RECORDED_ACTUAL' if event.get('actual_start_at') else 'SCHEDULED_START_PROXY',
                event_status=event.get('event_status'),opening_is_first_local_observation=True,
                quote_pair_ids=[p['pair_id'] for p in snap.get('book_pairs',{}).values()],
                closing_probability=None,closing_at=None,next_probability=None,next_at=None,
                target_home_win=None,target_available_at=None,model_probability=None,
                model_probability_pit_valid=False,signal_available_at={})
            if event.get('event_status','').upper() in ('CANCELED','CANCELLED','POSTPONED'):
                row['status']='EVENT_CANCELED_OR_POSTPONED'
            schedule_gate,schedule_id=schedule_status(by_state[key[0]],event,at)
            row['schedule_as_of_status']=schedule_gate
            row['schedule_observation_id']=schedule_id
            if row['status']=='SUPPORTED' and schedule_gate!='SUPPORTED': row['status']=schedule_gate
            if row['status']!='SUPPORTED':
                checkpoints.append(row); continue
            for field in ('cross_book_range','dispersion'): row['signal_available_at'][field]=iso(at)
            prior=consensus_at(series,at-timedelta(minutes=15))
            earlier=consensus_at(series,at-timedelta(minutes=30))
            common=set(prior.get('book_pairs',{}))&set(snap['book_pairs'])
            if len(common)>=2:
                # Composition changes in available books are not a book's line movement.
                changes=[snap['book_pairs'][b]['no_vig_a']-prior['book_pairs'][b]['no_vig_a'] for b in common]
                row['movement']=mean(changes)
                row['movement_matched_books']=sorted(common)
                row['velocity']=row['movement']*4
                row['signal_available_at'].update(movement=iso(at),velocity=iso(at))
                triple=common&set(earlier.get('book_pairs',{}))
                if len(triple)>=2:
                    row['acceleration']=mean(snap['book_pairs'][b]['no_vig_a']-2*prior['book_pairs'][b]['no_vig_a']+earlier['book_pairs'][b]['no_vig_a'] for b in triple)*16
                    row['signal_available_at']['acceleration']=iso(at)
                if len(common)>=3 and start-at<=timedelta(minutes=120):
                    aligned=max(sum(c>=.01 for c in changes),sum(c<=-.01 for c in changes))
                    row['synchronized_fraction']=aligned/len(common)
                    row['signal_available_at']['synchronized_fraction']=iso(at)
                    row['synchronized_book_count']=aligned
            full_ml=key[2]=='MONEYLINE' and key[3].lower() in ('full_game','fullgame')
            f=timely_forecast(by_forecast[key[0]],at,start) if full_ml else None
            if f:
                row.update(model_probability=f['home_probability'],model_probability_pit_valid=True,
                    model_forecast_id=f['forecast_id'],model_name=f['model_name'],model_version=f['model_version'],
                    model_available_at=f['available_as_of'],model_generated_at=f['generated_at'])
                row['model_disagreement']=float(f['home_probability'])-row['consensus_probability']
                row['signal_available_at']['model_disagreement']=iso(at)
            # Closing and next observations are targets only, never feature inputs.
            if closing_ok and closing_at>at and row['book_count']>=2:
                row.update(closing_probability=last['consensus_probability'],closing_at=iso(closing_at),
                    clv_probability_a=last['consensus_probability']-row['consensus_probability'],
                    clv_best_price_a=last['consensus_probability']*row['best_decimal_a']-1,
                    clv_best_price_b=(1-last['consensus_probability'])*row['best_decimal_b']-1)
            future=sorted({instant(p['operational_at']) for p in valid if instant(p['operational_at'])>at})
            if future and row['book_count']>=2:
                next_at=future[0]; after=consensus_at(series,next_at)
                if after.get('book_count',0)>=2 and schedule_status(by_state[key[0]],event,next_at)[0]=='SUPPORTED':
                    row.update(next_probability=after['consensus_probability'],next_at=iso(next_at))
            if full_ml and event.get('outcome_available_at') and event.get('home_score') is not None and event.get('away_score') is not None and str(event.get('event_status')).upper()=='FINAL':
                outcome_at=instant(event['outcome_available_at'])
                if at<start<outcome_at<=captured and event['home_score']!=event['away_score']:
                    row.update(target_home_win=int(event['home_score']>event['away_score']),target_available_at=iso(outcome_at))
            if full_ml:
                components={}
                if row['book_count']>=2: components['cross_book_dispersion']=min(1,row['cross_book_range']/.10)
                if f: components['model_market_disagreement']=min(1,abs(row['model_disagreement'])/.10)
                if 'synchronized_fraction' in row:
                    components['late_synchronized_movement']=row['synchronized_fraction'] if row['synchronized_book_count']>=3 else 0.
                pm=comparable_prediction_market(by_pm[key[0]],at)
                if pm:
                    row.update(prediction_market_probability=pm['probability'],prediction_market_snapshot_ids=pm['snapshot_ids'])
                    components['prediction_market_disagreement']=min(1,abs(pm['probability']-row['consensus_probability'])/.10)
                score=rff_score(components)
                ledger.append({'event_id':key[0],'event_start':iso(start),'checkpoint':name,'checkpoint_at':iso(at),**score})
                for k,v in components.items():
                    row['rff_'+k]=v; row['signal_available_at']['rff_'+k]=iso(at)
                row['rff_supported']=bool(components)
            checkpoints.append(row)
    summary={'schemaVersion':'POINT_IN_TIME_MARKET_TAPE_V1','eventCount':len(events),'quoteCount':len(quotes),
        'pairedSnapshots':len(pairs),'pairedEvents':len({p['event_id'] for p in pairs}),
        'checkpointRows':len(checkpoints),'statusCounts':dict(Counter(r['status'] for r in checkpoints)),
        'quoteExclusionReasons':dict(Counter(reason for r in excluded for reason in r['reasons'])),
        'primaryCheckpoint':'60M','primaryMarket':'MONEYLINE/full_game','maxQuoteAgeSeconds':MAX_AGE.total_seconds(),
        'eligibleResearchCheckpointRule':'SUPPORTED and >=2 books; operational observed/available/created <= checkpoint < conservative start',
        'closingDefinition':'Last locally recorded supported pre-scheduled-start consensus, >=2 books and <=60min old; not verified official close',
        'missingCheckpointRowsAreRetained':True,'sourceBreadthIsNotIndependentInformation':True,
        'authority':{'status':'RESEARCH_SHADOW','promotion':'NOT_PROMOTED','wageringAuthority':False,'executionAllowedInAISP':False}}
    return {'pairs':pairs,'quote_exclusions':excluded,'checkpoints':checkpoints,'ledger':ledger,'summary':summary}
