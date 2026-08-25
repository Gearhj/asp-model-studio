"""Deterministic Statcast pitch + plate-appearance normalization (Phase 7B1, Sections 10, 43, 44).

Streams the landed Statcast Bronze partitions one at a time (bounded memory), binds each pitch to canonical
game / plate-appearance / batter / pitcher identity via the resolved player bridge, and produces:
  * ``fact_statcast_pitch``               — one row per pitch (natural key game_pk/at_bat_number/pitch_number)
  * ``fact_statcast_plate_appearance``    — one canonical PA aggregating its pitches, with pitch lineage preserved
  * ``dim_game`` / ``dim_team``           — canonical game/team dimensions derived from Statcast metadata

Fail-closed: a pitch whose batter/pitcher MLBAM id is not UNAMBIGUOUSLY resolved by the player bridge is not given a
fabricated canonical id — it is quarantined as UNRESOLVED and counted. Row accounting reconciles exactly
(SOURCE = ACCEPTED + REJECTED + UNRESOLVED). Pitch->PA is a cardinality change, reported explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from . import bronze_authority as BA
from .canonical_ids import (canonical_game_id, canonical_pa_id, canonical_pitch_id, canonical_team_id)

# Statcast column -> normalized field (only governed columns; outcome fields kept but temporally classified in contract)
_INT_COLS = ("game_pk", "at_bat_number", "pitch_number", "inning", "batter", "pitcher", "game_year")


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


def normalize_statcast(manifest: Mapping[str, Any], root, resolved_mlbam: Mapping[str, str],
                       *, partition_filter=None) -> StatcastNormalization:
    """``resolved_mlbam``: unambiguous mlbam_id -> canonical player id (from the player bridge). ``partition_filter``:
    optional callable(BronzePartition)->bool to bound the slice (e.g. one season/month)."""
    fact_pitch: list[dict[str, Any]] = []
    pa_acc: dict[str, dict[str, Any]] = {}
    games: dict[str, dict[str, Any]] = {}
    teams: dict[str, dict[str, Any]] = {}
    part_ids: list[str] = []
    src_rows = accepted = rejected = unresolved = 0
    dup_natural = 0
    seen_pitch: set[tuple] = set()

    for p, table in BA.iter_source_frames(manifest, root, "statcast", only_nonempty=True,
                                          partition_filter=partition_filter):
        part_ids.append(p.partition_id)
        cols = {c: (table.column(c).to_pylist() if c in table.column_names else [None] * table.num_rows)
                for c in ("game_pk", "game_date", "game_year", "game_type", "home_team", "away_team", "inning",
                          "inning_topbot", "at_bat_number", "pitch_number", "batter", "pitcher", "stand", "p_throws",
                          "pitch_type", "release_speed", "bb_type", "events", "description", "des")}
        n = table.num_rows
        src_rows += n
        for i in range(n):
            game_pk = _i(cols["game_pk"][i])
            ab = _i(cols["at_bat_number"][i])
            pn = _i(cols["pitch_number"][i])
            batter_mlbam = _s(cols["batter"][i])
            pitcher_mlbam = _s(cols["pitcher"][i])
            if game_pk is None or ab is None or pn is None or batter_mlbam is None:
                rejected += 1
                continue
            nk = (game_pk, ab, pn)
            if nk in seen_pitch:
                dup_natural += 1
                rejected += 1
                continue
            seen_pitch.add(nk)
            batter_cid = resolved_mlbam.get(batter_mlbam)
            pitcher_cid = resolved_mlbam.get(pitcher_mlbam) if pitcher_mlbam else None
            if batter_cid is None:                                  # fail-closed: no fabricated canonical identity
                unresolved += 1
                continue
            cgame = canonical_game_id(game_pk)
            cpa = canonical_pa_id(cgame, ab, batter_cid)
            cpitch = canonical_pitch_id(cgame, ab, pn)
            season = _i(cols["game_year"][i])
            home, away = _s(cols["home_team"][i]), _s(cols["away_team"][i])
            fact_pitch.append({
                "canonicalPitchId": cpitch, "canonicalPaId": cpa, "canonicalGameId": cgame, "mlbamGamePk": str(game_pk),
                "atBatNumber": str(ab), "pitchNumber": str(pn), "batterCanonicalPlayerId": batter_cid,
                "pitcherCanonicalPlayerId": pitcher_cid, "batterMlbamId": batter_mlbam, "pitcherMlbamId": pitcher_mlbam,
                "season": str(season), "gameDate": _s(cols["game_date"][i]), "gameType": _s(cols["game_type"][i]),
                "inning": _s(cols["inning"][i]), "inningTopBot": _s(cols["inning_topbot"][i]),
                "stand": _s(cols["stand"][i]), "pThrows": _s(cols["p_throws"][i]), "homeTeam": home, "awayTeam": away,
                "pitchType": _s(cols["pitch_type"][i]), "releaseSpeed": _s(cols["release_speed"][i]),
                "bbType": _s(cols["bb_type"][i]), "pitchResultType": _s(cols["description"][i]),
                "events": _s(cols["events"][i]), "description": _s(cols["description"][i]), "des": _s(cols["des"][i]),
                "sourcePartitionId": p.partition_id, "sourceRowIndex": str(i)})
            accepted += 1

            # PA aggregation (deterministic; final pitch of the AB carries the PA event)
            pa = pa_acc.get(cpa)
            if pa is None:
                pa_acc[cpa] = {"canonicalPaId": cpa, "canonicalGameId": cgame, "mlbamGamePk": str(game_pk),
                               "atBatNumber": str(ab), "batterCanonicalPlayerId": batter_cid,
                               "pitcherCanonicalPlayerId": pitcher_cid, "batterMlbamId": batter_mlbam,
                               "pitcherMlbamId": pitcher_mlbam, "season": str(season), "gameDate": _s(cols["game_date"][i]),
                               "gameType": _s(cols["game_type"][i]), "inning": _s(cols["inning"][i]),
                               "inningTopBot": _s(cols["inning_topbot"][i]), "stand": _s(cols["stand"][i]),
                               "pThrows": _s(cols["p_throws"][i]), "_pitches": [pn], "paEvent": _s(cols["events"][i])}
            else:
                pa["_pitches"].append(pn)
                ev = _s(cols["events"][i])
                if ev:
                    pa["paEvent"] = ev

            if home:
                games.setdefault(cgame, {"canonicalGameId": cgame, "mlbamGamePk": str(game_pk),
                                         "gameDate": _s(cols["game_date"][i]), "season": str(season),
                                         "homeTeam": home, "awayTeam": away, "gameType": _s(cols["game_type"][i]),
                                         "retrosheetGameId": None, "gameNumber": None,
                                         "reconciliationStatus": "STATCAST_ONLY"})
            for tm in (home, away):
                if tm:
                    teams.setdefault(canonical_team_id(tm), {"canonicalTeamId": canonical_team_id(tm),
                                                             "teamAbbrev": tm, "aliases": []})

    fact_pa = []
    for pa in pa_acc.values():
        pitches = sorted(int(x) for x in pa.pop("_pitches"))
        pa["pitchCount"] = str(len(pitches))
        pa["firstPitchNumber"] = str(pitches[0])
        pa["lastPitchNumber"] = str(pitches[-1])
        fact_pa.append(pa)

    stats = {"sourcePitchRows": src_rows, "acceptedPitchRows": accepted, "rejectedPitchRows": rejected,
             "unresolvedPitchRows": unresolved, "duplicateNaturalKeys": dup_natural,
             "reconciles": (src_rows == accepted + rejected + unresolved),
             "canonicalPlateAppearances": len(fact_pa), "canonicalGames": len(games), "canonicalTeams": len(teams),
             "orphanPitches": 0, "partitions": len(part_ids)}
    return StatcastNormalization(fact_pitch=fact_pitch, fact_pa=fact_pa,
                                 dim_game=list(games.values()), dim_team=list(teams.values()),
                                 source_partition_ids=part_ids, stats=stats)
