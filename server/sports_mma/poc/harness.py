"""Validation, budgets and append-only state for the no-network MMA POC."""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Iterable
from .models import BoutVersion, EvidenceBundle, EventVersion, MMA_SPORT, ResultRevision, utc

class ValidationError(ValueError): pass
class BudgetError(ValueError): pass

def require_pipeline_sport(record_sport:str,pipeline_sport:str)->None:
    if record_sport!=pipeline_sport: raise ValidationError("CROSS_SPORT_RECORD")

def validate_schema(actual:str,expected:str)->None:
    if actual!=expected: raise ValidationError("SCHEMA_DRIFT")

def validate_latency(kind:str,source_time:str,observed_time:str)->None:
    thresholds={"schedule_change":15,"odds":10,"result":5,"statistics":15}
    if kind not in thresholds: raise ValidationError("UNKNOWN_LATENCY_KIND")
    delta=utc(observed_time)-utc(source_time)
    if delta<timedelta(0) or delta>timedelta(minutes=thresholds[kind]):
        raise ValidationError(f"{kind.upper()}_LATENCY_EXCEEDED")

class BudgetGuard:
    API_SPORTS_MAX_REQUESTS=80; ODDS_API_MAX_CREDITS=80
    def __init__(self)->None: self.api_sports_requests=0; self.odds_api_credits=0
    def reserve_api_sports(self,count:int=1)->None:
        if count<0 or self.api_sports_requests+count>80: raise BudgetError("API_SPORTS_REQUEST_CEILING")
        self.api_sports_requests+=count
    def reserve_odds(self,credits:int,*,region:str,market:str)->None:
        if region!="us" or market!="h2h": raise BudgetError("ODDS_SCOPE_NOT_ONE_REGION_H2H")
        if credits<0 or self.odds_api_credits+credits>80: raise BudgetError("ODDS_API_CREDIT_CEILING")
        self.odds_api_credits+=credits

class AppendOnlyLedger:
    def __init__(self)->None: self.events=[]; self.bouts=[]; self.results=[]
    def add_event(self,value:EventVersion)->None:
        _revision(value.version,value.predecessor_version,value.change_reason,[x for x in self.events if x.canonical_event_id==value.canonical_event_id])
        self.events.append(value)
    def add_bout(self,value:BoutVersion)->None:
        prior=[x for x in self.bouts if x.canonical_bout_id==value.canonical_bout_id]
        _revision(value.version,value.predecessor_version,value.change_reason,prior)
        if prior:
            previous=max(prior,key=lambda x:x.version)
            changed={n for n in ("red_fighter_id","blue_fighter_id","weight_class","scheduled_rounds","status") if getattr(previous,n)!=getattr(value,n)}
            if not changed: raise ValidationError("EMPTY_BOUT_REVISION")
            if value.change_reason not in {"OPPONENT_REPLACEMENT","CANCELLATION","SCHEDULED_ROUNDS_CHANGE","WEIGHT_CLASS_CHANGE","CORRECTION","PARTICIPANT_ORIENTATION_CHANGE"}: raise ValidationError("UNSUPPORTED_BOUT_CHANGE_REASON")
        self.bouts.append(value)
    def add_result(self,value:ResultRevision)->None:
        prior=[x for x in self.results if x.canonical_bout_id==value.canonical_bout_id]
        _revision(value.revision,value.predecessor_revision,value.correction_reason,prior,"revision")
        self.results.append(value)

def _revision(number:int,predecessor:int|None,reason:str|None,prior:Iterable[object],attr:str="version")->None:
    items=list(prior)
    if not items:
        if number!=1 or predecessor is not None: raise ValidationError("FIRST_REVISION_INVALID")
        return
    latest=max(getattr(x,attr) for x in items)
    if number!=latest+1 or predecessor!=latest or not reason: raise ValidationError("APPEND_ONLY_LINEAGE_INVALID")

def validate_bundle(b:EvidenceBundle,*,now:str)->list[str]:
    e=[]; cutoff,current=utc(b.forecast_cutoff),utc(now)
    records=[*b.captures,*b.fighters,*b.events,*b.bouts,*b.odds,*b.results]
    if any(getattr(x,"sport",None)!=MMA_SPORT for x in records): e.append("CROSS_SPORT_RECORD")
    captures={x.capture_id for x in b.captures}; fighters={x.canonical_fighter_id for x in b.fighters}; events={x.canonical_event_id for x in b.events}; bouts={x.canonical_bout_id for x in b.bouts}
    if len(fighters)!=len(b.fighters): e.append("DUPLICATE_FIGHTER_ID")
    if len({(x.canonical_event_id,x.version) for x in b.events})!=len(b.events): e.append("DUPLICATE_EVENT_VERSION")
    if len({(x.canonical_bout_id,x.version) for x in b.bouts})!=len(b.bouts): e.append("DUPLICATE_BOUT_VERSION")
    aliases=defaultdict(set)
    for x in b.fighters:
        if not x.source_ids or not x.display_name: e.append("FIGHTER_REQUIRED_FIELD")
        for alias in (x.display_name,*x.aliases): aliases[alias.casefold()].add(x.canonical_fighter_id)
    if any(len(v)>1 for v in aliases.values()): e.append("FIGHTER_ALIAS_AMBIGUITY")
    for x in b.captures:
        if not x.provider or not x.endpoint or x.payload_bytes<0:e.append("CAPTURE_REQUIRED_FIELD")
        if utc(x.retrieved_at)>current: e.append("FUTURE_DATED_CAPTURE")
        if len(x.payload_sha256)!=64 or len(x.schema_fingerprint)!=64: e.append("CAPTURE_INTEGRITY_FIELD")
    for x in b.events:
        if not x.source_event_ids or not x.promotion: e.append("EVENT_REQUIRED_FIELD")
        if utc(x.observed_at)>cutoff: e.append("POST_CUTOFF_EVENT_EVIDENCE")
    for x in b.bouts:
        if not x.source_bout_ids or not x.weight_class:e.append("BOUT_REQUIRED_FIELD")
        if x.canonical_event_id not in events:e.append("ORPHAN_BOUT_EVENT")
        if x.red_fighter_id not in fighters or x.blue_fighter_id not in fighters:e.append("ORPHAN_BOUT_FIGHTER")
        if x.red_fighter_id==x.blue_fighter_id:e.append("PARTICIPANT_ORIENTATION_INVALID")
        if x.scheduled_rounds not in (3,5):e.append("SCHEDULED_ROUNDS_INVALID")
        if utc(x.observed_at)>cutoff:e.append("POST_CUTOFF_BOUT_EVIDENCE")
    for x in b.odds:
        if x.canonical_bout_id not in bouts or x.capture_id not in captures:e.append("ORPHAN_ODDS")
        if x.market!="h2h" or x.region!="us":e.append("ODDS_SCOPE_INVALID")
        if abs(sum(x.outcomes.values())-1)>1e-9:e.append("ODDS_MASS_INVALID")
        if utc(x.observed_at)>cutoff:e.append("POST_CUTOFF_ODDS")
        if utc(x.observed_at)-utc(x.source_last_update)>timedelta(minutes=10):e.append("ODDS_LATENCY_EXCEEDED")
    for x in b.results:
        if x.canonical_bout_id not in bouts or x.capture_id not in captures:e.append("ORPHAN_RESULT")
        if x.status=="FINAL" and (x.method is None or x.round is None or x.finish_time is None):e.append("RESULT_INCOMPLETE")
        if x.status=="FINAL" and (not x.round_stats_complete or x.round is None or x.round_stats_rounds!=tuple(range(1,x.round+1))):e.append("ROUND_STATS_INCOMPLETE")
    source_ids=[]
    for x in b.fighters: source_ids += list(x.source_ids.items())
    if any(n>1 for n in Counter(source_ids).values()):e.append("CONFLICTING_SOURCE_FIGHTER_ID")
    return sorted(set(e))

def require_valid(bundle:EvidenceBundle,*,now:str)->None:
    errors=validate_bundle(bundle,now=now)
    if errors: raise ValidationError(";".join(errors))
