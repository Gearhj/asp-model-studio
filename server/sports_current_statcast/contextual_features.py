"""Pure, provider-free MLB contextual features with prior-date-only history."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from types import MappingProxyType
from typing import Final, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..sports_gold.contracts import GOLD_FEATURES

CONTEXT_AUTHORITY_VERSION: Final = "MLB_CONTEXT_STATIC_AUTHORITY_V1"
CONTEXT_FEATURE_VERSION: Final = "MLB_TEAM_GAME_CONTEXT_FEATURES_V1"
HOLIDAY_RULES_VERSION: Final = "US_CA_ON_BASEBALL_CALENDAR_V1"
RIVALRY_AUTHORITY_STATUS: Final = "PROPOSED_NOT_APPROVED"
EXCLUDED_INTERACTIONS: Final[Mapping[str, str]] = MappingProxyType({
    "travel_x_recent_bullpen_workload": "RECENT_BULLPEN_WORKLOAD_AUTHORITY_UNAVAILABLE",
    "month_x_temperature": "PREGAME_TEMPERATURE_AUTHORITY_UNAVAILABLE",
})


@dataclass(frozen=True)
class VenueAuthority:
    venue_id: str
    latitude: float | None
    longitude: float | None
    timezone_name: str | None
    altitude_feet: float | None = None
    country: str = "US"
    region: str | None = None
    authority_version: str = CONTEXT_AUTHORITY_VERSION


@dataclass(frozen=True)
class TeamAuthority:
    team_id: str
    league: str
    division: str
    home_timezone_name: str | None


def _team(team_id: str, league: str, division: str, tz: str) -> TeamAuthority:
    return TeamAuthority(team_id, league, division, tz)


# Canonical Silver abbreviations. Venue is never inferred from home team.
MLB_TEAM_AUTHORITIES: Final[Mapping[str, TeamAuthority]] = MappingProxyType({t.team_id: t for t in (
    _team("BAL","AL","E","America/New_York"),_team("BOS","AL","E","America/New_York"),_team("NYY","AL","E","America/New_York"),_team("TB","AL","E","America/New_York"),_team("TOR","AL","E","America/Toronto"),
    _team("CWS","AL","C","America/Chicago"),_team("CLE","AL","C","America/New_York"),_team("DET","AL","C","America/Detroit"),_team("KC","AL","C","America/Chicago"),_team("MIN","AL","C","America/Chicago"),
    _team("HOU","AL","W","America/Chicago"),_team("LAA","AL","W","America/Los_Angeles"),_team("ATH","AL","W","America/Los_Angeles"),_team("SEA","AL","W","America/Los_Angeles"),_team("TEX","AL","W","America/Chicago"),
    _team("ATL","NL","E","America/New_York"),_team("MIA","NL","E","America/New_York"),_team("NYM","NL","E","America/New_York"),_team("PHI","NL","E","America/New_York"),_team("WSH","NL","E","America/New_York"),
    _team("CHC","NL","C","America/Chicago"),_team("CIN","NL","C","America/New_York"),_team("MIL","NL","C","America/Chicago"),_team("PIT","NL","C","America/New_York"),_team("STL","NL","C","America/Chicago"),
    _team("AZ","NL","W","America/Phoenix"),_team("COL","NL","W","America/Denver"),_team("LAD","NL","W","America/Los_Angeles"),_team("SD","NL","W","America/Los_Angeles"),_team("SF","NL","W","America/Los_Angeles"),
)})


@dataclass(frozen=True)
class GameContextInput:
    canonical_game_id: str
    game_date: date
    home_team_id: str
    away_team_id: str
    venue_id: str
    scheduled_start_utc: datetime | None = None
    actual_end_utc: datetime | None = None
    duration_minutes: float | None = None
    innings_played: int | None = None
    series_game_number: int | None = None
    games_in_series: int | None = None
    doubleheader_game_number: int | None = None
    is_home_opener: bool = False
    season_start_date: date | None = None
    recent_bullpen_workload: float | None = None
    pregame_temperature: float | None = None

    def __post_init__(self) -> None:
        for field in ("scheduled_start_utc", "actual_end_utc"):
            value = getattr(self, field)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{field} must be timezone-aware")


GameInput = GameContextInput

GAME_CONTEXT_FEATURES: Final = (
    "game_day_of_week","game_month","game_day_of_season","season_phase","local_start_hour",
    "is_day_game","is_night_game","is_friday","is_saturday","is_sunday","is_weekend",
    "is_holiday","holiday_name","holiday_region","is_holiday_eve","is_home_opener",
    "series_game_number","is_series_opener","is_series_finale","is_getaway_day","is_doubleheader",
    "doubleheader_game_number","month_sin","month_cos","day_of_week_sin","day_of_week_cos",
    "local_start_hour_sin","local_start_hour_cos",
)
TEAM_CONTEXT_FEATURES: Final = (
    "days_since_previous_game","hours_since_previous_game_start","hours_since_previous_game_end",
    "previous_game_duration_minutes","previous_game_extra_innings","previous_game_innings",
    "played_yesterday","played_two_days_ago","games_last_3_days","games_last_7_days",
    "consecutive_game_days","doubleheader_yesterday","doubleheader_today","short_rest_indicator","long_rest_indicator",
    "travel_distance_miles","travel_distance_last_3_days","travel_distance_last_7_days",
    "time_zone_change_hours","crossed_time_zone","eastward_time_zone_change_hours",
    "westward_time_zone_change_hours","crossed_two_or_more_time_zones","cross_country_travel",
    "altitude_change_feet","consecutive_road_games","road_trip_game_number","home_stand_game_number",
    "previous_game_was_away","previous_game_was_home","returned_home_after_road_trip",
    "first_game_of_road_trip","overnight_travel_proxy","start_hour_in_team_home_time_zone",
    "start_hour_in_previous_venue_time_zone","local_body_clock_offset_hours",
    "early_start_after_eastward_travel","late_start_after_westward_travel","morning_body_clock_game",
    "circadian_timezone_component","circadian_body_clock_component","circadian_early_east_component",
    "circadian_late_west_component","circadian_morning_component","circadian_short_recovery_component",
    "circadian_disruption_score",
    "same_league_game","interleague_game","division_game","same_division",
    "repeat_opponent_within_7_days","repeat_opponent_within_14_days","series_rematch_indicator",
    "rivalry_pair","rivalry_game","home_rivalry_game","friday_night_home_rivalry","weekend_home_rivalry",
)
INTERACTION_FEATURES: Final = (
    "home_x_friday_night","home_x_weekend","home_x_holiday","home_x_rivalry",
    "eastward_travel_x_early_start","long_travel_x_short_rest","prior_extra_innings_x_travel",
    "doubleheader_x_short_rest","road_trip_length_x_travel",
)
MISSING_FLAG_FEATURES: Final = (
    "previous_game_missing","previous_game_start_missing","previous_game_end_missing",
    "previous_game_duration_missing","previous_game_innings_missing","current_start_missing",
    "current_venue_coordinates_missing","current_venue_timezone_missing","current_venue_altitude_missing",
    "previous_venue_coordinates_missing","previous_venue_timezone_missing","previous_venue_altitude_missing",
    "team_home_timezone_missing","team_alignment_missing","rivalry_mapping_missing",
    "recent_bullpen_workload_missing","pregame_temperature_missing",
    "previous_game_end_time_missing","travel_path_missing","venue_coordinate_missing",
    "time_zone_missing","holiday_calendar_missing",
)
CONTEXT_FEATURES: Final = (
    *GAME_CONTEXT_FEATURES,
    *(f"batting_{x}" for x in (*TEAM_CONTEXT_FEATURES,*INTERACTION_FEATURES,*MISSING_FLAG_FEATURES)),
    *(f"fielding_{x}" for x in (*TEAM_CONTEXT_FEATURES,*INTERACTION_FEATURES,*MISSING_FLAG_FEATURES)),
)
ORDERED_GOLD_PLUS_CONTEXT_FEATURES: Final = (*tuple(GOLD_FEATURES),*CONTEXT_FEATURES)

_REST = TEAM_CONTEXT_FEATURES[:TEAM_CONTEXT_FEATURES.index("travel_distance_miles")]
_TRAVEL = TEAM_CONTEXT_FEATURES[
    TEAM_CONTEXT_FEATURES.index("travel_distance_miles"):
    TEAM_CONTEXT_FEATURES.index("start_hour_in_team_home_time_zone")
]
_CIRCADIAN = TEAM_CONTEXT_FEATURES[
    TEAM_CONTEXT_FEATURES.index("start_hour_in_team_home_time_zone"):
    TEAM_CONTEXT_FEATURES.index("same_league_game")
]
_OPPONENT = TEAM_CONTEXT_FEATURES[TEAM_CONTEXT_FEATURES.index("same_league_game"):]
FEATURE_FAMILIES: Final[Mapping[str, tuple[str,...]]] = MappingProxyType({
    "A_GOLD_48":tuple(GOLD_FEATURES),"B_CALENDAR_SERIES":GAME_CONTEXT_FEATURES,
    "C_REST_DENSITY":_REST,"D_TRAVEL_TRIP":_TRAVEL,"E_CIRCADIAN":_CIRCADIAN,
    "F_OPPONENT_RIVALRY":_OPPONENT,"G_BOUNDED_INTERACTIONS":INTERACTION_FEATURES,
})
def _perspectives(names: Sequence[str]) -> tuple[str, ...]:
    return (*(f"batting_{name}" for name in names), *(f"fielding_{name}" for name in names))


_OBJECTIVE_OPPONENT = tuple(name for name in _OPPONENT if "rivalry" not in name)
_ACTIVE_INTERACTIONS = tuple(name for name in INTERACTION_FEATURES if name != "home_x_rivalry")
_FULL_TEAM = tuple(name for name in TEAM_CONTEXT_FEATURES if "rivalry" not in name)
FUTURE_ABLATION_FAMILIES: Final[Mapping[str,tuple[str,...]]] = MappingProxyType({
    "A CORE_GOLD_48": tuple(GOLD_FEATURES),
    "B CORE_PLUS_CALENDAR": (*tuple(GOLD_FEATURES), *GAME_CONTEXT_FEATURES),
    "C CORE_PLUS_REST_TRAVEL": (*tuple(GOLD_FEATURES), *_perspectives((*_REST, *_TRAVEL))),
    "D CORE_PLUS_CIRCADIAN": (*tuple(GOLD_FEATURES), *_perspectives(_CIRCADIAN)),
    "E CORE_PLUS_DIVISION_RIVALRY": (*tuple(GOLD_FEATURES), *_perspectives(_OBJECTIVE_OPPONENT)),
    "F CORE_PLUS_CALENDAR_TRAVEL": (*tuple(GOLD_FEATURES), *GAME_CONTEXT_FEATURES, *_perspectives((*_REST, *_TRAVEL))),
    "G FULL_CONTEXTUAL_CHALLENGER": (*tuple(GOLD_FEATURES), *GAME_CONTEXT_FEATURES, *_perspectives((*_FULL_TEAM, *_ACTIVE_INTERACTIONS, *MISSING_FLAG_FEATURES))),
})
FEATURE_SPECS: Final[Mapping[str,Mapping[str,str]]] = MappingProxyType({name:MappingProxyType({
    "featureVersion":CONTEXT_FEATURE_VERSION,"knowledgeCutoff":"source.game_date < target.game_date",
    "availability":"PREGAME_OR_PRIOR_DATE_ONLY",
}) for name in CONTEXT_FEATURES})
PROPOSED_RIVALRY_PAIRS: Final[frozenset[frozenset[str]]] = frozenset()


def haversine_miles(a: VenueAuthority, b: VenueAuthority) -> float | None:
    if None in (a.latitude,a.longitude,b.latitude,b.longitude): return None
    lat1,lon1,lat2,lon2=map(math.radians,(a.latitude,a.longitude,b.latitude,b.longitude))
    h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 2*3958.7613*math.asin(math.sqrt(h))


def _nth_weekday(year:int,month:int,weekday:int,n:int)->date:
    first=date(year,month,1); return first+timedelta(days=(weekday-first.weekday())%7+7*(n-1))


def _last_weekday(year:int,month:int,weekday:int)->date:
    nxt=date(year+(month==12),month%12+1,1); end=nxt-timedelta(days=1); return end-timedelta(days=(end.weekday()-weekday)%7)


def _observed_us(day:date)->date:
    return day-timedelta(days=1) if day.weekday()==5 else day+timedelta(days=1) if day.weekday()==6 else day


def _observed_ca(day:date)->date:
    return day+timedelta(days=7-day.weekday()) if day.weekday()>=5 else day


def venue_holiday_map(year:int,venue:VenueAuthority)->Mapping[date,str]:
    if venue.country=="CA" and venue.region=="ON": items=((_last_weekday(year,5,0)-timedelta(days=7),"VICTORIA_DAY"),(_observed_ca(date(year,7,1)),"CANADA_DAY"),(_nth_weekday(year,8,0,1),"CIVIC_HOLIDAY"),(_nth_weekday(year,9,0,1),"LABOUR_DAY"),(_nth_weekday(year,10,0,2),"THANKSGIVING_CA"))
    else: items=((_last_weekday(year,5,0),"MEMORIAL_DAY"),(_observed_us(date(year,6,19)),"JUNETEENTH"),(_observed_us(date(year,7,4)),"INDEPENDENCE_DAY"),(_nth_weekday(year,9,0,1),"LABOR_DAY"))
    return MappingProxyType(dict(items))


def venue_holidays(year:int,venue:VenueAuthority)->frozenset[date]: return frozenset(venue_holiday_map(year,venue))


def _local(game:GameContextInput,venue:VenueAuthority|None,tz:str|None=None)->datetime|None:
    name=tz or (venue.timezone_name if venue else None)
    return game.scheduled_start_utc.astimezone(ZoneInfo(name)) if game.scheduled_start_utc and name else None


def _offset(game:GameContextInput|None,venue:VenueAuthority|None)->float|None:
    value=_local(game,venue) if game else None; return value.utcoffset().total_seconds()/3600 if value else None


def _history(rows:Sequence[GameContextInput],team:str,before:date)->list[GameContextInput]:
    return sorted(
        (g for g in rows if g.game_date < before and team in (g.home_team_id, g.away_team_id)),
        key=lambda g: (
            g.game_date,
            g.doubleheader_game_number or 0,
            g.scheduled_start_utc.isoformat() if g.scheduled_start_utc else "",
            g.canonical_game_id,
        ),
    )


def _trip(priors:Sequence[GameContextInput],team:str,home:bool)->int:
    n=1
    for g in reversed(priors):
        if (g.home_team_id==team)!=home: break
        n+=1
    return n


def _consecutive(priors:Sequence[GameContextInput],target:date)->int:
    dates={g.game_date for g in priors}; n=0; cursor=target-timedelta(days=1)
    while cursor in dates: n+=1; cursor-=timedelta(days=1)
    return n


def build_team_game_context(game:GameContextInput,team_id:str,*,history:Sequence[GameContextInput],venues:Mapping[str,VenueAuthority],teams:Mapping[str,TeamAuthority]=MLB_TEAM_AUTHORITIES)->dict[str,object]:
    if team_id not in (game.home_team_id,game.away_team_id): raise ValueError("team_id is not a participant")
    opponent=game.away_team_id if team_id==game.home_team_id else game.home_team_id
    priors=_history(history,team_id,game.game_date); prior=priors[-1] if priors else None
    venue=venues.get(game.venue_id); pvenue=venues.get(prior.venue_id) if prior else None; local=_local(game,venue)
    team_auth,opp_auth=teams.get(team_id),teams.get(opponent); home=game.home_team_id==team_id
    days=(game.game_date-prior.game_date).days if prior else None
    hstart=(game.scheduled_start_utc-prior.scheduled_start_utc).total_seconds()/3600 if game.scheduled_start_utc and prior and prior.scheduled_start_utc else None
    hend=(game.scheduled_start_utc-prior.actual_end_utc).total_seconds()/3600 if game.scheduled_start_utc and prior and prior.actual_end_utc else None
    r3=[g for g in priors if g.game_date>=game.game_date-timedelta(days=3)]; r7=[g for g in priors if g.game_date>=game.game_date-timedelta(days=7)]; r14=[g for g in priors if g.game_date>=game.game_date-timedelta(days=14)]
    distance=haversine_miles(pvenue,venue) if pvenue and venue else None
    def miles(window:Sequence[GameContextInput])->float|None:
        if window:
            first_index=priors.index(window[0]); predecessor=priors[first_index-1] if first_index else None
        else:
            predecessor=prior
        chain=[*([predecessor] if predecessor else []),*window,game]
        total=0.0
        for a,b in zip(chain,chain[1:]):
            va,vb=venues.get(a.venue_id),venues.get(b.venue_id); d=haversine_miles(va,vb) if va and vb else None
            if d is None:return None
            total+=d
        return total
    # Compare both venue offsets at the target first pitch. This measures
    # geographic time-zone movement without inventing a one-hour trip when a
    # club simply spans a daylight-saving transition in the same venue.
    po,co=_offset(game,pvenue),_offset(game,venue); tz=co-po if co is not None and po is not None else None
    home_clock=_local(game,venue,team_auth.home_timezone_name if team_auth else None); previous_clock=_local(game,pvenue,pvenue.timezone_name if pvenue else None)
    body=abs((local.hour+local.minute/60)-(home_clock.hour+home_clock.minute/60)) if local and home_clock else None
    if body is not None: body=min(body,24-body)
    road,stand=(0,_trip(priors,team_id,True)) if home else (_trip(priors,team_id,False),0)
    repeat7=sum(opponent in (g.home_team_id,g.away_team_id) for g in r7); repeat14=sum(opponent in (g.home_team_id,g.away_team_id) for g in r14)
    same_league=int(team_auth.league==opp_auth.league) if team_auth and opp_auth else None; same_div=int(bool(same_league) and team_auth.division==opp_auth.division) if team_auth and opp_auth else None
    current_series_prior=max((game.series_game_number or 1)-1,0)
    pre_series_priors=priors[:-current_series_prior] if current_series_prior else priors
    series_rematch=int(any(opponent in (g.home_team_id,g.away_team_id) for g in pre_series_priors))
    holiday_map=venue_holiday_map(game.game_date.year,venue) if venue else {}; holiday=holiday_map.get(local.date()) if local else None
    finale=int(game.series_game_number==game.games_in_series) if game.series_game_number and game.games_in_series else None
    short=int((hend is not None and hend<18) or (hend is None and days is not None and days<=1)); long=int(days is not None and days>=3)
    east=max(tz,0.0) if tz is not None else None; west=max(-tz,0.0) if tz is not None else None
    early=int(bool(east) and local is not None and local.hour<14); late=int(bool(west) and local is not None and local.hour>=19); morning=int(home_clock is not None and home_clock.hour<12)
    circ_tz=abs(tz) if tz is not None else None
    short_recovery=max(0.0,24.0-hstart)/24.0 if hstart is not None else None
    circ_score=sum((circ_tz,body,float(early),float(late),float(morning),short_recovery)) if circ_tz is not None and body is not None and short_recovery is not None else None
    dow=game.game_date.weekday(); month=game.game_date.month; hour=local.hour+local.minute/60 if local else None
    rivalry_missing=int(RIVALRY_AUTHORITY_STATUS!="APPROVED"); rivalry=None if rivalry_missing else int(frozenset((team_id,opponent)) in PROPOSED_RIVALRY_PAIRS)
    flags={"previous_game_missing":int(prior is None),"previous_game_start_missing":int(prior is None or prior.scheduled_start_utc is None),"previous_game_end_missing":int(prior is None or prior.actual_end_utc is None),"previous_game_duration_missing":int(prior is None or prior.duration_minutes is None),"previous_game_innings_missing":int(prior is None or prior.innings_played is None),"current_start_missing":int(game.scheduled_start_utc is None),"current_venue_coordinates_missing":int(venue is None or None in (venue.latitude,venue.longitude)),"current_venue_timezone_missing":int(venue is None or not venue.timezone_name),"current_venue_altitude_missing":int(venue is None or venue.altitude_feet is None),"previous_venue_coordinates_missing":int(pvenue is None or None in (pvenue.latitude,pvenue.longitude)),"previous_venue_timezone_missing":int(pvenue is None or not pvenue.timezone_name),"previous_venue_altitude_missing":int(pvenue is None or pvenue.altitude_feet is None),"team_home_timezone_missing":int(team_auth is None or not team_auth.home_timezone_name),"team_alignment_missing":int(team_auth is None or opp_auth is None),"rivalry_mapping_missing":rivalry_missing,"recent_bullpen_workload_missing":int(game.recent_bullpen_workload is None),"pregame_temperature_missing":int(game.pregame_temperature is None)}
    flags.update({"previous_game_end_time_missing":flags["previous_game_end_missing"],"travel_path_missing":int(prior is None or distance is None),"venue_coordinate_missing":int(bool(flags["current_venue_coordinates_missing"] or flags["previous_venue_coordinates_missing"])),"time_zone_missing":int(bool(flags["current_venue_timezone_missing"] or flags["previous_venue_timezone_missing"] or flags["team_home_timezone_missing"])),"holiday_calendar_missing":int(venue is None or not (venue.country=="US" or (venue.country=="CA" and venue.region=="ON")))})
    row:dict[str,object]={"canonical_game_id":game.canonical_game_id,"team_id":team_id,"opponent_team_id":opponent,"prior_game_id":prior.canonical_game_id if prior else None,"context_feature_version":CONTEXT_FEATURE_VERSION,"history_cutoff_rule":"source.game_date < target.game_date","rivalry_authority_status":RIVALRY_AUTHORITY_STATUS,"actual_end_utc":game.actual_end_utc.isoformat() if game.actual_end_utc else None,"excluded_interactions":dict(EXCLUDED_INTERACTIONS),
        "game_day_of_week":game.game_date.strftime("%A").upper(),"game_month":month,"game_day_of_season":(game.game_date-game.season_start_date).days+1 if game.season_start_date else None,"season_phase":"EARLY" if month<=5 else "MIDDLE" if month<=7 else "LATE","local_start_hour":hour,"is_day_game":int(hour<18) if hour is not None else None,"is_night_game":int(hour>=18) if hour is not None else None,"is_friday":int(dow==4),"is_saturday":int(dow==5),"is_sunday":int(dow==6),"is_weekend":int(dow>=5),"is_holiday":int(holiday is not None) if local else None,"holiday_name":holiday,"holiday_region":f"{venue.country}-{venue.region}" if venue and venue.region else venue.country if venue else None,"is_holiday_eve":int(local.date()+timedelta(days=1) in holiday_map) if local else None,"is_home_opener":int(game.is_home_opener),"series_game_number":game.series_game_number,"is_series_opener":int(game.series_game_number==1) if game.series_game_number else None,"is_series_finale":finale,"is_getaway_day":finale,"is_doubleheader":int(game.doubleheader_game_number is not None),"doubleheader_game_number":game.doubleheader_game_number,"month_sin":math.sin(2*math.pi*(month-1)/12),"month_cos":math.cos(2*math.pi*(month-1)/12),"day_of_week_sin":math.sin(2*math.pi*dow/7),"day_of_week_cos":math.cos(2*math.pi*dow/7),"local_start_hour_sin":math.sin(2*math.pi*hour/24) if hour is not None else None,"local_start_hour_cos":math.cos(2*math.pi*hour/24) if hour is not None else None,
        "days_since_previous_game":days,"hours_since_previous_game_start":hstart,"hours_since_previous_game_end":hend,"previous_game_duration_minutes":prior.duration_minutes if prior else None,"previous_game_extra_innings":int(prior.innings_played>9) if prior and prior.innings_played is not None else None,"previous_game_innings":prior.innings_played if prior else None,"played_yesterday":int(days==1),"played_two_days_ago":int(days==2),"games_last_3_days":len(r3),"games_last_7_days":len(r7),"consecutive_game_days":_consecutive(priors,game.game_date),"doubleheader_yesterday":int(sum(g.game_date==game.game_date-timedelta(days=1) for g in priors)>=2),"doubleheader_today":int(game.doubleheader_game_number is not None),"short_rest_indicator":short,"long_rest_indicator":long,
        "travel_distance_miles":distance,"travel_distance_last_3_days":miles(r3),"travel_distance_last_7_days":miles(r7),"time_zone_change_hours":tz,"crossed_time_zone":int(bool(tz)) if tz is not None else None,"eastward_time_zone_change_hours":east,"westward_time_zone_change_hours":west,"crossed_two_or_more_time_zones":int(abs(tz)>=2) if tz is not None else None,"cross_country_travel":int(distance>=1500) if distance is not None else None,"altitude_change_feet":venue.altitude_feet-pvenue.altitude_feet if venue and pvenue and venue.altitude_feet is not None and pvenue.altitude_feet is not None else None,"consecutive_road_games":road if not home else 0,"road_trip_game_number":road,"home_stand_game_number":stand,"previous_game_was_away":int(prior is not None and prior.away_team_id==team_id),"previous_game_was_home":int(prior is not None and prior.home_team_id==team_id),"returned_home_after_road_trip":int(home and prior is not None and prior.away_team_id==team_id),"first_game_of_road_trip":int(not home and (prior is None or prior.home_team_id==team_id)),"overnight_travel_proxy":int(distance is not None and distance>0 and days==1),
        "start_hour_in_team_home_time_zone":home_clock.hour+home_clock.minute/60 if home_clock else None,"start_hour_in_previous_venue_time_zone":previous_clock.hour+previous_clock.minute/60 if previous_clock else None,"local_body_clock_offset_hours":body,"early_start_after_eastward_travel":early,"late_start_after_westward_travel":late,"morning_body_clock_game":morning,"circadian_timezone_component":circ_tz,"circadian_body_clock_component":body,"circadian_early_east_component":early,"circadian_late_west_component":late,"circadian_morning_component":morning,"circadian_short_recovery_component":short_recovery,"circadian_disruption_score":circ_score,
        "same_league_game":same_league,"interleague_game":1-same_league if same_league is not None else None,"division_game":same_div,"same_division":same_div,"repeat_opponent_within_7_days":repeat7,"repeat_opponent_within_14_days":repeat14,"series_rematch_indicator":series_rematch,"rivalry_pair":rivalry,"rivalry_game":rivalry,"home_rivalry_game":None if rivalry is None else rivalry*int(home),"friday_night_home_rivalry":None if rivalry is None else rivalry*int(home)*int(dow==4)*int(hour is not None and hour>=18),"weekend_home_rivalry":None if rivalry is None else rivalry*int(home)*int(dow>=5),
        "home_x_friday_night":int(home and dow==4 and hour is not None and hour>=18),"home_x_weekend":int(home and dow>=5),"home_x_holiday":int(home and holiday is not None),"home_x_rivalry":None if rivalry is None else int(home)*rivalry,"eastward_travel_x_early_start":east*early if east is not None else None,"long_travel_x_short_rest":int(distance>=1500)*short if distance is not None else None,"prior_extra_innings_x_travel":int(prior.innings_played>9)*distance if prior and prior.innings_played is not None and distance is not None else None,"doubleheader_x_short_rest":int(game.doubleheader_game_number is not None)*short,"road_trip_length_x_travel":road*distance if distance is not None else None,**flags}
    if flags["previous_game_missing"]:
        missing_category = "NO_PRIOR_HISTORY"
    elif flags["team_alignment_missing"]:
        missing_category = "IDENTITY_FAILURE"
    elif any(flags.values()):
        missing_category = "SOURCE_MISSING"
    else:
        missing_category = None
    row["missing_reason_category"] = missing_category
    row["missing_reasons"]=tuple(sorted(name.upper() for name,value in flags.items() if value))
    return row


def build_game_context_rows(game:GameContextInput,*,history:Sequence[GameContextInput],venues:Mapping[str,VenueAuthority],teams:Mapping[str,TeamAuthority]=MLB_TEAM_AUTHORITIES)->tuple[dict[str,object],dict[str,object]]:
    return build_team_game_context(game,game.away_team_id,history=history,venues=venues,teams=teams),build_team_game_context(game,game.home_team_id,history=history,venues=venues,teams=teams)
