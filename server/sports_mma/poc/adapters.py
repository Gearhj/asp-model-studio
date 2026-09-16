"""Provider planning interfaces. Network access is gated and never implicit."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol
from .harness import BudgetGuard, ValidationError
from .models import (BoutVersion, Capture, EventVersion, Fighter, OddsSnapshot,
                     canonical_bytes, digest, schema_fingerprint)

API_SPORTS_ENV="MMA_API_SPORTS_KEY"; ODDS_API_ENV="MMA_THE_ODDS_API_KEY"; RIGHTS_ENV="MMA_POC_RIGHTS_APPROVED"

@dataclass(frozen=True)
class PlannedRequest:
    provider:str; method:str; endpoint:str; parameters:dict[str,str]; requests:int; credits:int; retention:str; output:str

class Transport(Protocol):
    def get(self,endpoint:str,*,headers:Mapping[str,str],params:Mapping[str,str])->bytes: ...

class LiveGate:
    @staticmethod
    def credentials(env:Mapping[str,str],*,execute_live:bool)->tuple[str,str]:
        if not execute_live: raise ValidationError("LIVE_EXECUTION_FLAG_REQUIRED")
        if env.get(RIGHTS_ENV)!="YES": raise ValidationError("RIGHTS_APPROVAL_MARKER_REQUIRED")
        api_key,odds_key=env.get(API_SPORTS_ENV,""),env.get(ODDS_API_ENV,"")
        if not api_key or not odds_key: raise ValidationError("LOCAL_PROVIDER_CREDENTIALS_REQUIRED")
        return api_key,odds_key

class ApiSportsMmaAdapter:
    base_url="https://v1.mma.api-sports.io"
    def plan(self)->list[PlannedRequest]:
        rows=[("/categories",{},1,"category capture"),("/fighters",{"search":"<fixture-fighter>"},4,"fighter identities"),("/fights",{"date":"<card-date>"},40,"two-card schedules"),("/fights/results",{"date":"<card-date>"},20,"result revisions"),("/fights/statistics/fighters",{"fight":"<fight-id>"},15,"round/fight statistics")]
        return [PlannedRequest("API_SPORTS_MMA","GET",p,q,n,0,"quarantine raw bytes pending rights approval",o) for p,q,n,o in rows]

class TheOddsApiMmaAdapter:
    base_url="https://api.the-odds-api.com"
    def plan(self)->list[PlannedRequest]:
        return [PlannedRequest("THE_ODDS_API","GET","/v4/sports",{},1,0,"retain metadata receipt","entitlement metadata"),PlannedRequest("THE_ODDS_API","GET","/v4/sports/mma_mixed_martial_arts/odds",{"regions":"us","markets":"h2h","oddsFormat":"decimal"},80,80,"retain timestamped h2h snapshots","odds snapshots")]

def synthetic_capture(provider:str,endpoint:str,payload:dict,retrieved_at:str)->Capture:
    _require_synthetic(payload); raw=canonical_bytes(payload); capture_id=f"capture:{digest([provider,endpoint,retrieved_at,digest(payload)])}"
    return Capture(capture_id,"MMA",provider,endpoint,retrieved_at,digest(payload),len(raw),schema_fingerprint(payload),payload.get("sourcePublishedAt"),payload.get("sourceUpdatedAt"))

def normalize_api_sports_synthetic(payload:dict,capture:Capture)->tuple[list[Fighter],EventVersion,list[BoutVersion]]:
    _require_synthetic(payload); event=payload["event"]
    fighters={}
    bouts=[]
    for row in payload["fights"]:
        ids=[]
        for side in ("red","blue"):
            item=row[side]; canonical=f"fighter:{digest(['synthetic',item['id']])[:16]}"; ids.append(canonical)
            fighters[canonical]=Fighter(canonical,"MMA",item["name"],{"api_sports_synthetic":str(item["id"])})
        bouts.append(BoutVersion(f"bout:{digest(['synthetic',row['id']])[:16]}",f"event:{event['id']}","MMA",1,ids[0],ids[1],row["weightClass"],row["scheduledRounds"],capture.retrieved_at,{"api_sports_synthetic":str(row["id"])}))
    canonical_event=EventVersion(f"event:{event['id']}","MMA",1,"SYNTHETIC UFC",event["scheduled"],capture.retrieved_at,{"api_sports_synthetic":str(event["id"])},"SCHEDULED")
    return list(fighters.values()),canonical_event,bouts

def normalize_odds_synthetic(payload:dict,bout_id:str,capture:Capture)->OddsSnapshot:
    _require_synthetic(payload); event=payload["event"]
    raw={str(x["fighterId"]):float(x["probability"]) for x in event["outcomes"]}; total=sum(raw.values())
    if total<=0: raise ValidationError("ODDS_MASS_INVALID")
    return OddsSnapshot(bout_id,"MMA","THE_ODDS_API_SYNTHETIC",event["bookmaker"],"h2h","us",capture.retrieved_at,event["lastUpdate"],{key:value/total for key,value in raw.items()},capture.capture_id)

def _require_synthetic(payload:dict)->None:
    if payload.get("_fixture")!="SYNTHETIC_NON_PROVIDER": raise ValidationError("NON_SYNTHETIC_PAYLOAD_REJECTED")

def build_plan()->dict:
    budget=BudgetGuard(); api=ApiSportsMmaAdapter().plan(); odds=TheOddsApiMmaAdapter().plan()
    for x in api: budget.reserve_api_sports(x.requests)
    for x in odds:
        if x.credits: budget.reserve_odds(x.credits,region=x.parameters["regions"],market=x.parameters["markets"])
    return {"liveExecution":False,"networkCalls":0,"environmentVariables":[API_SPORTS_ENV,ODDS_API_ENV,RIGHTS_ENV],"apiSports":{"requests":budget.api_sports_requests,"ceiling":80,"items":[asdict(x) for x in api]},"theOddsApi":{"credits":budget.odds_api_credits,"ceiling":80,"region":"us","market":"h2h","items":[asdict(x) for x in odds]},"expectedOutputs":["immutable captures","canonical identities","card revisions","odds snapshots","result/stat revisions","validation receipt"]}
