"""Deterministic Statcast pitch + plate-appearance normalization (Phase 7B1, Sections 9-11, 43, 44).

Statcast Bronze is partitioned per DAY; a game occurs on one day, so a plate appearance never spans partitions. The
per-partition core ``normalize_partition`` therefore produces complete pitch + PA facts for one daily partition with
bounded memory; the full-corpus driver (see ``pipeline``) streams all 2019-2024 partitions and publishes them as an
immutable partitioned table without materializing the whole corpus. Canonical game/PA/batter/pitcher identity is bound
via the resolved player bridge; unresolved ids fail closed (never fabricated); row accounting reconciles exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from . import bronze_authority as BA
from .canonical_ids import canonical_game_id, canonical_pa_id, canonical_pitch_id, canonical_team_id

_READ_COLS = ("game_pk", "game_date", "game_year", "game_type", "home_team", "away_team", "inning", "inning_topbot",
              "at_bat_number", "pitch_number", "batter", "pitcher", "stand", "p_throws", "pitch_type", "release_speed",
              "bb_type", "events", "description", "des")

PITCH_FIELDS = ["canonicalPitchId", "canonicalPaId", "canonicalGameId", "mlbamGamePk", "atBatNumber", "pitchNumber",
                "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "batterMlbamId", "pitcherMlbamId", "season",
                "gameDate", "gameType", "inning", "inningTopBot", "stand", "pThrows", "homeTeam", "awayTeam",
                "pitchType", "releaseSpeed", "bbType", "pitchResultType", "events", "description", "des",
                "sourcePartitionId", "sourceRowIndex"]
PA_FIELDS = ["canonicalPaId", "canonicalGameId", "mlbamGamePk", "atBatNumber", "batterCanonicalPlayerId",
             "pitcherCanonicalPlayerId", "batterMlbamId", "pitcherMlbamId", "season", "gameDate", "gameType",
             "inning", "inningTopBot", "stand", "pThrows", "paEvent", "pitchCount", "firstPitchNumber", "lastPitchNumber"]
GAME_FIELDS = ["canonicalGameId", "mlbamGamePk", "gameDate", "season", "homeTeam", "awayTeam", "gameType",
               "retrosheetGameId", "gameNumber", "reconciliationStatus"]
TEAM_FIELDS = ["canonicalTeamId", "teamAbbrev", "aliases"]


@dataclass
class PartitionResult:
    fact_pitch: list[dict[str, Any]]
    fact_pa: list[dict[str, Any]]
    games: dict[str, dict[str, Any]]
    teams: dict[str, dict[str, Any]]
    counts: dict[str, int]


@dataclass
class StatcastNormalization:
    fact_pitch: list[dict[str, Any]]
    fact_pa: list[dict[str, Any]]
    dim_game: list[dict[str, Any]]
    dim_team: list[dict[str, Any]]
    source_partition_ids: list[str]
    stats: dict[str, Any] = field(default_factory=dict)


def _s(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _i(v: Any) -> int | None:
    try:
        return int(str(v).strip())
    except Exception:
        return None


def normalize_partition(table, partition_id: str, resolved_mlbam: Mapping[str, str]) -> PartitionResult:
    """Normalize ONE daily Statcast partition into complete pitch + PA facts (bounded memory)."""
    cols = {c: (table.column(c).to_pylist() if c in table.column_names else [None] * table.num_rows) for c in _READ_COLS}
    n = table.num_rows
    fact_pitch: list[dict[str, Any]] = []
    pa_acc: dict[str, dict[str, Any]] = {}
    games: dict[str, dict[str, Any]] = {}
    teams: dict[str, dict[str, Any]] = {}
    seen: set[tuple] = set()
    accepted = rejected = unresolved = dup = 0
    for i in range(n):
        game_pk = _i(cols["game_pk"][i]); ab = _i(cols["at_bat_number"][i]); pn = _i(cols["pitch_number"][i])
        batter = _s(cols["batter"][i]); pitcher = _s(cols["pitcher"][i])
        if game_pk is None or ab is None or pn is None or batter is None:
            rejected += 1
            continue
        nk = (game_pk, ab, pn)
        if nk in seen:
            dup += 1
            rejected += 1
            continue
        seen.add(nk)
        batter_cid = resolved_mlbam.get(batter)
        if batter_cid is None:
            unresolved += 1
            continue
        pitcher_cid = resolved_mlbam.get(pitcher) if pitcher else None
        cgame = canonical_game_id(game_pk); cpa = canonical_pa_id(cgame, ab, batter_cid)
        cpitch = canonical_pitch_id(cgame, ab, pn)
        season = _i(cols["game_year"][i]); home = _s(cols["home_team"][i]); away = _s(cols["away_team"][i])
        gdate = _s(cols["game_date"][i]); gtype = _s(cols["game_type"][i])
        inning = _s(cols["inning"][i]); itb = _s(cols["inning_topbot"][i])
        stand = _s(cols["stand"][i]); pthrows = _s(cols["p_throws"][i]); ev = _s(cols["events"][i])
        fact_pitch.append({"canonicalPitchId": cpitch, "canonicalPaId": cpa, "canonicalGameId": cgame,
            "mlbamGamePk": str(game_pk), "atBatNumber": str(ab), "pitchNumber": str(pn),
            "batterCanonicalPlayerId": batter_cid, "pitcherCanonicalPlayerId": pitcher_cid, "batterMlbamId": batter,
            "pitcherMlbamId": pitcher, "season": str(season), "gameDate": gdate, "gameType": gtype, "inning": inning,
            "inningTopBot": itb, "stand": stand, "pThrows": pthrows, "homeTeam": home, "awayTeam": away,
            "pitchType": _s(cols["pitch_type"][i]), "releaseSpeed": _s(cols["release_speed"][i]),
            "bbType": _s(cols["bb_type"][i]), "pitchResultType": _s(cols["description"][i]), "events": ev,
            "description": _s(cols["description"][i]), "des": _s(cols["des"][i]),
            "sourcePartitionId": partition_id, "sourceRowIndex": str(i)})
        accepted += 1
        pa = pa_acc.get(cpa)
        if pa is None:
            pa_acc[cpa] = {"canonicalPaId": cpa, "canonicalGameId": cgame, "mlbamGamePk": str(game_pk),
                "atBatNumber": str(ab), "batterCanonicalPlayerId": batter_cid, "pitcherCanonicalPlayerId": pitcher_cid,
                "batterMlbamId": batter, "pitcherMlbamId": pitcher, "season": str(season), "gameDate": gdate,
                "gameType": gtype, "inning": inning, "inningTopBot": itb, "stand": stand, "pThrows": pthrows,
                "_pitches": [pn], "paEvent": ev}
        else:
            pa["_pitches"].append(pn)
            if ev:
                pa["paEvent"] = ev
        if home:
            games.setdefault(cgame, {"canonicalGameId": cgame, "mlbamGamePk": str(game_pk), "gameDate": gdate,
                "season": str(season), "homeTeam": home, "awayTeam": away, "gameType": gtype,
                "retrosheetGameId": None, "gameNumber": None, "reconciliationStatus": "STATCAST_ONLY"})
        for tm in (home, away):
            if tm:
                teams.setdefault(canonical_team_id(tm), {"canonicalTeamId": canonical_team_id(tm), "teamAbbrev": tm,
                                                         "aliases": []})
    fact_pa = []
    for pa in pa_acc.values():
        pitches = sorted(int(x) for x in pa.pop("_pitches"))
        pa["pitchCount"] = str(len(pitches)); pa["firstPitchNumber"] = str(pitches[0]); pa["lastPitchNumber"] = str(pitches[-1])
        fact_pa.append(pa)
    return PartitionResult(fact_pitch=fact_pitch, fact_pa=fact_pa, games=games, teams=teams,
                           counts={"source": n, "accepted": accepted, "rejected": rejected, "unresolved": unresolved,
                                   "dup": dup, "pa": len(fact_pa)})


def normalize_statcast(manifest: Mapping[str, Any], root, resolved_mlbam: Mapping[str, str],
                       *, partition_filter=None) -> StatcastNormalization:
    """In-memory normalization over a (bounded) partition set — used by tests and the 2019-postseason fixture. The
    full corpus is normalized partition-by-partition by the driver (never all in memory)."""
    fact_pitch: list[dict[str, Any]] = []
    fact_pa: list[dict[str, Any]] = []
    games: dict[str, dict[str, Any]] = {}
    teams: dict[str, dict[str, Any]] = {}
    part_ids: list[str] = []
    src = acc = rej = unr = dup = 0
    for p, table in BA.iter_source_frames(manifest, root, "statcast", only_nonempty=True, partition_filter=partition_filter):
        part_ids.append(p.partition_id)
        r = normalize_partition(table, p.partition_id, resolved_mlbam)
        fact_pitch.extend(r.fact_pitch); fact_pa.extend(r.fact_pa)
        games.update(r.games)
        teams.update(r.teams)
        src += r.counts["source"]; acc += r.counts["accepted"]; rej += r.counts["rejected"]
        unr += r.counts["unresolved"]; dup += r.counts["dup"]
    stats = {"sourcePitchRows": src, "acceptedPitchRows": acc, "rejectedPitchRows": rej, "unresolvedPitchRows": unr,
             "duplicateNaturalKeys": dup, "reconciles": (src == acc + rej + unr), "canonicalPlateAppearances": len(fact_pa),
             "canonicalGames": len(games), "canonicalTeams": len(teams), "orphanPitches": 0, "partitions": len(part_ids)}
    return StatcastNormalization(fact_pitch=fact_pitch, fact_pa=fact_pa, dim_game=list(games.values()),
                                 dim_team=list(teams.values()), source_partition_ids=part_ids, stats=stats)


def extract_statcast_games(manifest: Mapping[str, Any], root, *, partition_filter=None) -> list[dict[str, Any]]:
    """Light pass: distinct Statcast games (game_pk, date, home, away, season). Used for game-bridge reconciliation."""
    games: dict[str, dict[str, Any]] = {}
    for p, table in BA.iter_source_frames(manifest, root, "statcast", only_nonempty=True, partition_filter=partition_filter):
        cols = {c: (table.column(c).to_pylist() if c in table.column_names else [None] * table.num_rows)
                for c in ("game_pk", "game_date", "game_year", "home_team", "away_team", "game_type")}
        for i in range(table.num_rows):
            gpk = _i(cols["game_pk"][i])
            if gpk is None:
                continue
            games.setdefault(str(gpk), {"mlbamGamePk": str(gpk), "gameDate": _s(cols["game_date"][i]),
                "season": str(_i(cols["game_year"][i])), "homeTeam": _s(cols["home_team"][i]),
                "awayTeam": _s(cols["away_team"][i]), "gameType": _s(cols["game_type"][i])})
    return list(games.values())
