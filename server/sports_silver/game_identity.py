"""Full canonical game-identity reconciliation (Phase 7B1, Section 8).

Reconciles ``Statcast game_pk <-> canonical_game_id <-> Retrosheet game id`` using non-outcome identity material only
(date, home/away team under the derived team map, doubleheader/game number). Final score/innings are never a matching
key. Doubleheaders (same teams + date) are matched by game-number order (Statcast game_pk order <-> Retrosheet game
number). Ambiguous or conflicting mappings never silently feed downstream facts.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from .canonical_ids import canonical_game_id

MATCHED_EXACT = "MATCHED_EXACT"
STATCAST_ONLY = "STATCAST_ONLY"
RETROSHEET_ONLY = "RETROSHEET_ONLY"
AMBIGUOUS = "AMBIGUOUS"
SOURCE_CONFLICT = "SOURCE_CONFLICT"


def _normdate(v) -> str:
    return "".join(ch for ch in str(v) if ch.isdigit())


@dataclass
class GameReconciliation:
    dim_game: list[dict[str, Any]]                 # canonical games (Statcast-authoritative) enriched with retro id
    bridge_game_identity: list[dict[str, Any]]     # one row per canonical game with reconciliation state
    retro_only: list[dict[str, Any]]               # Retrosheet games with no Statcast match
    retro_to_canonical: dict[str, str] = field(default_factory=dict)   # retro_game_id -> canonical_game_id (matched)
    stats: dict[str, Any] = field(default_factory=dict)


def reconcile_games(statcast_games: Iterable[dict[str, Any]], retro_games: Iterable[dict[str, Any]],
                    team_map: dict[str, str]) -> GameReconciliation:
    retro_games = list(retro_games)
    statcast_games = list(statcast_games)
    # index retro games by (date, retroHome, retroVis) with game numbers
    rs_by_key: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in retro_games:
        rs_by_key[(_normdate(r.get("gameDate")), r.get("retroHomeTeam"), r.get("retroVisTeam"))].append(r)
    for lst in rs_by_key.values():
        lst.sort(key=lambda r: str(r.get("gameNumber") or "0"))
    matched_retro: set[str] = set()

    # group statcast games by (date, mapped home, mapped away); order by game_pk for doubleheaders
    sc_by_key: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for g in statcast_games:
        home_rs = team_map.get(g.get("homeTeam"))
        away_rs = team_map.get(g.get("awayTeam"))
        sc_by_key[(_normdate(g.get("gameDate")), home_rs, away_rs)].append(g)
    for lst in sc_by_key.values():
        lst.sort(key=lambda g: int(g["mlbamGamePk"]))

    dim_game: list[dict[str, Any]] = []
    bridge: list[dict[str, Any]] = []
    retro_to_canonical: dict[str, str] = {}
    counts = {MATCHED_EXACT: 0, STATCAST_ONLY: 0, AMBIGUOUS: 0, SOURCE_CONFLICT: 0}
    doubleheaders = 0

    for key, sc_list in sc_by_key.items():
        date, home_rs, away_rs = key
        rs_list = rs_by_key.get(key, []) if home_rs and away_rs else []
        if len(sc_list) > 1 or len(rs_list) > 1:
            doubleheaders += 1
        for idx, g in enumerate(sc_list):
            cgame = canonical_game_id(g["mlbamGamePk"])
            status = STATCAST_ONLY
            retro_id = None
            if home_rs is None or away_rs is None:
                status = STATCAST_ONLY                       # unmapped team -> cannot reconcile (fail closed)
            elif len(rs_list) == len(sc_list) and idx < len(rs_list):
                # equal cardinality (incl. doubleheaders) -> position-matched by game number order
                retro_id = rs_list[idx].get("retroGameId")
                status = MATCHED_EXACT
            elif len(rs_list) == 0:
                status = STATCAST_ONLY
            else:
                status = AMBIGUOUS                           # cardinality mismatch -> ambiguous, never guessed
            if retro_id:
                matched_retro.add(retro_id)
                retro_to_canonical[retro_id] = cgame
            counts[status] = counts.get(status, 0) + 1
            dim_game.append({"canonicalGameId": cgame, "mlbamGamePk": g["mlbamGamePk"], "gameDate": g.get("gameDate"),
                "season": g.get("season"), "homeTeam": g.get("homeTeam"), "awayTeam": g.get("awayTeam"),
                "gameType": g.get("gameType"), "retrosheetGameId": retro_id,
                "gameNumber": (str(idx + 1) if len(sc_list) > 1 else "0"), "reconciliationStatus": status})
            bridge.append({"canonicalGameId": cgame, "mlbamGamePk": g["mlbamGamePk"], "retrosheetGameId": retro_id,
                "gameDate": g.get("gameDate"), "homeTeam": g.get("homeTeam"), "awayTeam": g.get("awayTeam"),
                "resolutionStatus": status, "resolutionMethod": "date_team_gamenumber"})

    retro_only = [{"retroGameId": r.get("retroGameId"), "gameDate": r.get("gameDate"),
                   "retroHomeTeam": r.get("retroHomeTeam"), "retroVisTeam": r.get("retroVisTeam"),
                   "resolutionStatus": RETROSHEET_ONLY}
                  for r in retro_games if r.get("retroGameId") not in matched_retro]

    stats = {"statcastGames": len(dim_game), "retrosheetGames": len(retro_games),
             "matchedExact": counts.get(MATCHED_EXACT, 0), "statcastOnly": counts.get(STATCAST_ONLY, 0),
             "ambiguous": counts.get(AMBIGUOUS, 0), "retrosheetOnly": len(retro_only),
             "doubleheaderBuckets": doubleheaders}
    return GameReconciliation(dim_game=dim_game, bridge_game_identity=bridge, retro_only=retro_only,
                              retro_to_canonical=retro_to_canonical, stats=stats)
