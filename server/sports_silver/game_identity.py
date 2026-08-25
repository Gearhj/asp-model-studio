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

# Evidence-based reasons for why a Statcast game has no 1:1 Retrosheet counterpart (all fail-closed — never force-matched)
RETROSHEET_SOURCE_ABSENT = "RETROSHEET_SOURCE_ABSENT"   # the Retrosheet source has no game for this date/matchup at all
UNRESOLVED_SOURCE_GAP = "UNRESOLVED_SOURCE_GAP"         # the teams meet in Retrosheet but this game is not resolvable


def _normdate(v) -> str:
    return "".join(ch for ch in str(v) if ch.isdigit())


def classify_statcast_only(statcast_only_games, retro_games, team_map) -> dict[str, Any]:
    """Assign each STATCAST_ONLY game an EXACT, evidence-based reason from the landed Retrosheet source (no guessing,
    no forced match):
      * SOURCE_CONFLICT          — a Retrosheet game exists for the SAME date + teams but with home/away REVERSED
                                   (the sources disagree on the home/away fact; e.g. 2020 relocated 'home' games);
      * RETROSHEET_SOURCE_ABSENT — the Retrosheet source has no game on that date (postseason not in the landed
                                   regular-season corpus) or never records those two teams meeting that season;
      * UNRESOLVED_SOURCE_GAP    — the teams meet in Retrosheet that season but this specific game is not resolvable.
    ``team_map`` maps Statcast code -> Retrosheet code. Returns per-game reasons + a tally. Pure/deterministic."""
    from collections import Counter
    retro_games = list(retro_games)
    ordered = Counter()      # (date, retroHome, retroVis)
    on_date = Counter()      # date -> count
    pair_season = Counter()  # (season, frozenset(teams))
    for r in retro_games:
        d = _normdate(r.get("gameDate"))
        ordered[(d, r.get("retroHomeTeam"), r.get("retroVisTeam"))] += 1
        on_date[d] += 1
        pair_season[(d[:4], frozenset((r.get("retroHomeTeam"), r.get("retroVisTeam"))))] += 1

    per_game: list[dict[str, Any]] = []
    tally: Counter = Counter()
    for g in statcast_only_games:
        d = _normdate(g.get("gameDate"))
        H = team_map.get(g.get("homeTeam"))
        A = team_map.get(g.get("awayTeam"))
        if H is None or A is None:
            reason = UNRESOLVED_SOURCE_GAP
        elif ordered[(d, A, H)] > 0:
            reason = SOURCE_CONFLICT                    # same date+teams, home/away reversed in Retrosheet
        elif on_date[d] == 0 or pair_season[(d[:4], frozenset((H, A)))] == 0:
            reason = RETROSHEET_SOURCE_ABSENT           # Retrosheet source does not cover this date/matchup
        else:
            reason = UNRESOLVED_SOURCE_GAP
        tally[reason] += 1
        per_game.append({"mlbamGamePk": g.get("mlbamGamePk"), "gameDate": g.get("gameDate"),
                         "season": g.get("season"), "gameType": g.get("gameType"),
                         "homeTeam": g.get("homeTeam"), "awayTeam": g.get("awayTeam"),
                         "mappedRetroHome": H, "mappedRetroAway": A, "sourceReason": reason,
                         "retroGameSameDateReversed": int(ordered[(d, A, H)]) if H and A else 0})
    return {"perGame": per_game, "tally": dict(tally),
            "postseasonCount": sum(1 for g in statcast_only_games if g.get("gameType") not in (None, "R")),
            "regularSeasonCount": sum(1 for g in statcast_only_games if g.get("gameType") == "R")}


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
