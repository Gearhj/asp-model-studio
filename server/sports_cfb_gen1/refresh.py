"""Checkpoint-aware bounded recurring refresh planning, no implicit authority."""
from datetime import timedelta
from pathlib import Path
import json
from zoneinfo import ZoneInfo
from .lifecycle import utc,read_ref
from .publication_io import verified_bytes
from .inputs import observed_at


def due(bundle,plan,clock,last_attempt=None):
    t=utc(clock)
    if not utc(plan['validFromUtc'])<=t<utc(plan['validUntilUtc']):
        return {'due':False,'disposition':'REFRESH_PERIOD_CLOSED','networkIntentRequests':0}
    targets=[x['target'] for x in bundle['games'] if x.get('exclusion')!='OUTSIDE_FBS_FBS_REGULAR_WEEKS_1_14']
    starts=[utc(x['scheduled_at']) for x in targets if x['status']=='SCHEDULED']
    if not any(t-timedelta(days=2)<=s<=t+timedelta(days=7) for s in starts):
        return {'due':False,'disposition':'NO_NEAR_SUPPORTED_SLATE','networkIntentRequests':0}
    if last_attempt and t-utc(last_attempt)<timedelta(minutes=plan['minimumCaptureSpacingMinutes']):
        return {'due':False,'disposition':'REFRESH_COALESCED','networkIntentRequests':0,
                'nextEligibleAtUtc':(utc(last_attempt)+timedelta(minutes=plan['minimumCaptureSpacingMinutes'])).isoformat()}
    checked=utc(bundle['scheduleCapturedAtUtc']);local=t.astimezone(ZoneInfo('America/New_York'))
    daily=local.replace(hour=plan['dailyCheckHourNewYork'],minute=0,second=0,microsecond=0)
    reasons=[]
    if t-checked>=timedelta(hours=23):reasons.append('FRESHNESS_EXPIRY_APPROACHING')
    if local>=daily and checked<daily:reasons.append('DAILY_SCHEDULE_CORRECTION_CHECK')
    for target in targets:
        s=utc(target['scheduled_at'])
        if target['status']=='SCHEDULED' and t<s-timedelta(minutes=30):
            for minutes in (10080,1440,360,60):
                checkpoint=s-timedelta(minutes=minutes);lead=checkpoint-timedelta(minutes=plan['checkpointCaptureLeadMinutes'])
                if lead<=t<=checkpoint and checked<lead:reasons.append('CHECKPOINT_REVALIDATION')
            if s-t<=timedelta(minutes=90) and t-checked>=timedelta(minutes=90):reasons.append('FINAL_CHECKPOINT_FRESHNESS')
        # An availability check is not an inferred final result.
        opportunity=s+timedelta(hours=5)
        if opportunity<=t<=opportunity+timedelta(days=2) and (checked<opportunity or
            (target['status']=='SCHEDULED' and t-checked>=timedelta(hours=4))):reasons.append('POSTGAME_AVAILABILITY_CHECK')
    return {'due':bool(reasons),'disposition':'REFRESH_DUE' if reasons else 'REFRESH_NOT_DUE',
            'networkIntentRequests':plan['maxRequests'] if reasons else 0,'reasons':sorted(set(reasons))}


def statistics_selector(plan,previous_manifest,clock):
    """Choose complete required weeks after observing the newly captured schedule.

    Older weeks remain cached with original provenance; one older week rotates
    through correction checks daily. Missing/new/corrected final weeks are mandatory.
    """
    previous=read_ref(previous_manifest);t=utc(clock)
    data=[x for x in previous['requests'] if x['endpoint']!='/info']
    schedules=[x for x in data if x['endpoint']=='/games'];schools=[x for x in data if x['endpoint']=='/teams/fbs']
    old_games={int(g['id']):g for g in json.loads(verified_bytes(schedules[0]))}
    old_weeks={int(x['parameters']['week']):x for x in data if x['endpoint']=='/games/teams'}
    assets=plan['allowedAssets'];stat_assets={int(x['parameters']['week']):x for x in assets if x['endpoint']=='/games/teams'}
    school_asset=next(x for x in assets if x['endpoint']=='/teams/fbs')
    def choose(schedule):
        relevant=[x for x in schedule if x.get('seasonType')=='regular' and
                  (x.get('homeClassification')=='fbs' or x.get('awayClassification')=='fbs')]
        completed=[x for x in relevant if x.get('completed')]
        final_weeks={int(x['week']) for x in completed};required=final_weeks-set(old_weeks)
        for game in completed:
            before=old_games.get(int(game['id']))
            if before is None or any(before.get(k)!=game.get(k) for k in ('completed','homePoints','awayPoints','homeId','awayId','startDate')):
                required.add(int(game['week']))
        if final_weeks:required.add(max(final_weeks))
        # The imminent week can acquire a newly completed game between schedule
        # captures; request it only when a governed completed row exists.
        if any(w not in stat_assets for w in required):raise ValueError('REQUIRED_WEEK_OUTSIDE_AUTHORIZATION')
        selected=[]
        if not schools or t-utc(observed_at(schools[0]))>=timedelta(days=7):selected.append(school_asset)
        capacity=plan['maxRequests']-3-len(selected)  # before-info, games, after-info
        if len(required)>capacity:raise ValueError('REQUIRED_CORRECTION_WEEKS_EXCEED_CAPTURE_BUDGET')
        optional=sorted(final_weeks-required,key=lambda w:utc(observed_at(old_weeks[w])))
        for w in optional:
            if len(required)>=capacity:break
            if t-utc(observed_at(old_weeks[w]))>=timedelta(hours=24):required.add(w);break
        selected += [stat_assets[w] for w in sorted(required)]
        return selected
    return choose


def usage_snapshot(root,plan,clock):
    """Count all starts conservatively, including interrupted captures and seed usage."""
    root=Path(root);day=utc(clock).date();requests=byte_count=day_requests=day_bytes=0;last=None
    receipts=[read_ref(x) for x in plan.get('carryForwardCaptureReceipts',[])]
    for folder in sorted((root/'attempts').glob('*')) if (root/'attempts').exists() else []:
        if not (folder/'started.json').exists():continue
        start=json.loads((folder/'started.json').read_bytes())
        if (folder/'completion.json').exists():receipts.append(json.loads((folder/'completion.json').read_bytes()))
        else:receipts.append({'startedAtUtc':start['startedAtUtc'],'providerCalls':plan['maxRequests'],
                             'providerBytes':plan['maxResponseBytes'],'uncertain':True})
    for receipt in receipts:
        stamp=utc(receipt['startedAtUtc']);n=receipt['providerCalls'];size=receipt['providerBytes']
        requests+=n;byte_count+=size
        # Conservatively charge a midnight-spanning batch to both dates; never
        # undercount the next day's requests by assigning them all to its start.
        end=utc(receipt.get('completedAtUtc',clock))
        if stamp.date()<=day<=end.date():day_requests+=n;day_bytes+=size
        last=max(stamp,last) if last else stamp
    return {'periodRequestsIncludingCarryForward':requests,'periodBytesIncludingCarryForward':byte_count,
            'utcDayRequests':day_requests,'utcDayBytes':day_bytes,'lastAttemptUtc':last.isoformat() if last else None}


def budget_reason(usage,plan,retained_bytes):
    if usage['utcDayRequests']+plan['maxRequests']>plan['maxRequestsPerUtcDay']:return 'UTC_DAY_REQUEST_BUDGET'
    if usage['periodRequestsIncludingCarryForward']+plan['maxRequests']>plan['maxRequestsForPeriodIncludingCarryForward']:return 'PERIOD_REQUEST_BUDGET'
    if usage['utcDayBytes']+plan['maxResponseBytes']>plan['maxResponseBytesPerUtcDay']:return 'UTC_DAY_BYTE_BUDGET'
    if retained_bytes+plan['maxResponseBytes']>plan['maxRetainedBytes']:return 'RETAINED_STORAGE_BUDGET'
    return None
