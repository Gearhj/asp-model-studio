"""Retrosheet team-code authority (Phase 7B1, Section 7).

The Retrosheet team codes (e.g. ANA/NYA/CHA/SLN/LAN) differ from the Statcast/MLBAM abbreviations (LAA/NYY/CWS/STL/LAD)
for a handful of clubs. The mapping is NOT hand-coded: it is DERIVED and VALIDATED from the landed source authority by
aligning the shared 2019-2024 schedule — for each date, matching a Statcast game to a Retrosheet game requires the two
team codes to be consistent under the (growing) map allowing at most one unknown, and a unique such match derives the
unknown code. The result is cross-checked to be a bijection; the TEAM{year} file supplies alias/nickname evidence.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .canonical_ids import canonical_team_id

MATCHED_EXACT = "MATCHED_EXACT"
UNMATCHED = "UNMATCHED"
AMBIGUOUS = "AMBIGUOUS"
SOURCE_CONFLICT = "SOURCE_CONFLICT"


def _normdate(v) -> str:
    return "".join(ch for ch in str(v) if ch.isdigit())


def derive_team_map(statcast_games: Iterable[dict[str, Any]], retro_games: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return ``{"map": {statcast_code: retro_code}, "reverse": {...}, "status": ..., "unresolved": [...]}`` derived by
    schedule alignment. ``statcast_games``: dicts with gameDate/homeTeam/awayTeam. ``retro_games``: dicts with
    gameDate/retroHomeTeam/retroVisTeam."""
    rs_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in retro_games:
        rs_by_date[_normdate(r.get("gameDate"))].append(r)
    sc_games = [g for g in statcast_games if g.get("homeTeam") and g.get("awayTeam") and g.get("gameDate")]

    tmap: dict[str, str] = {}

    def consistent(sc_code, rs_code):
        m = tmap.get(sc_code)
        if m is None:
            return "unknown" if sc_code != rs_code else "ok"
        return "ok" if m == rs_code else "bad"

    for _ in range(12):
        changed = False
        for g in sc_games:
            date = _normdate(g["gameDate"])
            cands = []
            for r in rs_by_date.get(date, []):
                pairs = [(g["homeTeam"], r.get("retroHomeTeam")), (g["awayTeam"], r.get("retroVisTeam"))]
                unknowns = []
                ok = True
                for sc, rs in pairs:
                    if rs is None:
                        ok = False
                        break
                    st = consistent(sc, rs)
                    if st == "bad":
                        ok = False
                        break
                    if st == "unknown":
                        unknowns.append((sc, rs))
                if ok and len(unknowns) <= 1:
                    cands.append(unknowns)
            # a unique candidate that forces exactly one new mapping derives it
            forcing = [u for u in cands if len(u) == 1]
            if len(cands) == 1 and forcing:
                sc, rs = forcing[0][0]
                if tmap.get(sc) != rs:
                    tmap[sc] = rs
                    changed = True
        if not changed:
            break

    # identity for codes that never needed derivation but appear identically in both systems
    sc_codes = {g["homeTeam"] for g in sc_games} | {g["awayTeam"] for g in sc_games}
    rs_codes = {r.get("retroHomeTeam") for r in retro_games} | {r.get("retroVisTeam") for r in retro_games}
    for c in sc_codes:
        if c not in tmap and c in rs_codes:
            tmap[c] = c

    reverse: dict[str, list[str]] = defaultdict(list)
    for sc, rs in tmap.items():
        reverse[rs].append(sc)
    conflicts = {rs: scs for rs, scs in reverse.items() if len(scs) > 1}
    unresolved = sorted(sc_codes - set(tmap))
    status = SOURCE_CONFLICT if conflicts else (UNMATCHED if unresolved else MATCHED_EXACT)
    return {"map": dict(sorted(tmap.items())), "reverse": {k: sorted(v) for k, v in reverse.items()},
            "status": status, "conflicts": conflicts, "unresolvedStatcastCodes": unresolved,
            "statcastCodeCount": len(sc_codes), "mappedCount": len(tmap)}


def dim_team_rows(statcast_teams: Iterable[str], team_map: dict[str, str],
                  team_files: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    """Canonical dim_team keyed by the Statcast abbreviation (window-stable), carrying the Retrosheet code + nickname
    evidence as aliases."""
    nick_by_retro = {t["retroTeamCode"]: t for t in team_files}
    rows = []
    for sc in sorted(set(statcast_teams)):
        rs = team_map.get(sc)
        info = nick_by_retro.get(rs, {})
        aliases = sorted({x for x in [rs, info.get("nickname"), info.get("city")] if x and x != sc})
        rows.append({"canonicalTeamId": canonical_team_id(sc), "teamAbbrev": sc, "aliases": aliases,
                     "retroTeamCode": rs, "nickname": info.get("nickname"), "city": info.get("city")})
    return rows
