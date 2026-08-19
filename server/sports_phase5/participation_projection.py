"""Projected-participation adapters for the P0→P3 ablation (MLB_PROJECTED_PARTICIPATION_ABLATION_V1).

Builds, from the frozen Milestone B research components, the per-team batter/pitcher identity
sequences the whole-game Monte Carlo consumes — WITHOUT retraining or modifying any component:

  - L1 lineup projection  → projected starting nine (top-9 by start probability).
  - S2 starter duration   → projected batters-faced before the starter is removed
                            (starter IDENTITY remains the actual one — STARTER_IDENTITY_ORACLE).
  - B1 bullpen usage       → projected reliever sequence after the starter.

Only the participation dimension changes across branches; the D3 PA model, the base-out
transition model, the kernel, and the RNG lineage are identical to Phase 5D.

The D3 cumulative B-state is materialized only for (player, date) pairs that actually appeared.
A projected player who did not appear on the game date resolves to their most-recent prior
materialized cumulative state (B-state is cumulative and slowly varying) — a principled, low-
distortion fallback that is counted; a player with no prior materialized state falls back to the
role-league mean (also counted). No actual target-game lineup/relievers are used to CHOOSE
projected participants; historical participants are used only as the P0 oracle control and for
evaluation.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from server.sports_phase4.dynamic_contract import STATE_VALUE_COLUMNS
from server.sports_phase5.pa_provider import D3_STATE_TABLE_SHA

BRANCHES = ("P0", "P1", "P2", "P3")
BRANCH_LABELS = {
    "P0": "HISTORICAL_PARTICIPANTS_ORACLE_MODE",
    "P1": "PROJECTED_LINEUP + ORACLE_PITCHING",
    "P2": "PROJECTED_LINEUP + STARTER_IDENTITY_ORACLE + PROJECTED_STARTER_DURATION + ORACLE_BULLPEN",
    "P3": "PROJECTED_PARTICIPATION_RESEARCH_MODE (PROJECTED_LINEUP + STARTER_IDENTITY_ORACLE + PROJECTED_STARTER_DURATION + PROJECTED_BULLPEN)",
}


class ProjectionError(RuntimeError):
    """Structural fault building projected participation (never used to hide fallback usage)."""


# --------------------------------------------------------------------------------------
# Temporal B-state resolver (exact, else most-recent prior, else role-league mean)
# --------------------------------------------------------------------------------------
class TemporalStateResolver:
    """Resolve a player's cumulative B-state as of a game date, with counted fallback.

    Presents the same ``resolve(uuid, role, game_date) -> tuple[float, ...]`` interface as the
    exact ``PlayerStateResolver`` so the Monte Carlo contribution builder is unchanged.
    """

    def __init__(self, records: Sequence[Mapping[str, Any]], *, state_table_sha: str) -> None:
        self.state_table_sha = state_table_sha
        self._by_player: dict[tuple[str, str], list[tuple[str, tuple[float, ...]]]] = defaultdict(list)
        role_sum = {"BATTER": np.zeros(len(STATE_VALUE_COLUMNS)), "PITCHER": np.zeros(len(STATE_VALUE_COLUMNS))}
        role_n = {"BATTER": 0, "PITCHER": 0}
        for row in records:
            if row.get("state_kind") != "B_CUMULATIVE":
                continue
            role = str(row["role"])
            values = tuple(
                float(row[name]) if row[name] is not None and not _is_nan(row[name]) else float("nan")
                for name in STATE_VALUE_COLUMNS
            )
            self._by_player[(role, str(row["canonical_player_uuid"]))].append((str(row["game_date"]), values))
            if role in role_sum:
                finite = np.array([v if v == v else 0.0 for v in values])
                role_sum[role] += finite
                role_n[role] += 1
        for key in self._by_player:
            self._by_player[key].sort(key=lambda item: item[0])
        self._role_mean = {
            role: tuple((role_sum[role] / max(role_n[role], 1)).tolist()) for role in role_sum
        }
        self.exact = 0
        self.stale = 0
        self.league = 0

    def resolve(self, uuid: str, role: str, game_date: str) -> tuple[float, ...]:
        seq = self._by_player.get((role, str(uuid)))
        if seq:
            dates = [d for d, _ in seq]
            i = bisect.bisect_right(dates, str(game_date))
            if i > 0:
                if dates[i - 1] == str(game_date):
                    self.exact += 1
                else:
                    self.stale += 1
                return seq[i - 1][1]
        self.league += 1
        return self._role_mean.get(role, tuple([0.0] * len(STATE_VALUE_COLUMNS)))

    def has(self, uuid: str, role: str, game_date: str) -> bool:
        return (role, str(uuid)) in self._by_player

    def fallback_summary(self) -> dict[str, Any]:
        total = self.exact + self.stale + self.league
        return {
            "resolvedExact": self.exact, "resolvedPriorState": self.stale, "roleLeagueFallback": self.league,
            "total": total,
            "priorStateRate": round(self.stale / total, 6) if total else 0.0,
            "leagueFallbackRate": round(self.league / total, 6) if total else 0.0,
        }


def _is_nan(value: Any) -> bool:
    try:
        return isinstance(value, float) and value != value
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------------------
# Per-game projected participation (from L1/S2/B1 predictions)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TeamProjection:
    lineup: tuple[str, ...]           # projected 9 batter uuids (l1-probability order)
    starter_uuid: str | None          # actual starter identity (oracle)
    s2_bfp: float                     # projected batters faced before removal
    reliever_uuids: tuple[str, ...]   # projected relievers, b1-probability order
    reliever_bfp: tuple[float, ...]   # projected batters-faced per reliever
    lineup_recall: float | None       # retrospective top-9 recall vs actual (diagnostic)


def build_team_projections(
    lineup_rows: Sequence[Mapping[str, Any]],
    starter_rows: Sequence[Mapping[str, Any]],
    bullpen_rows: Sequence[Mapping[str, Any]],
) -> TeamProjection:
    # lineup: top-9 by l1_probability
    lin = sorted(lineup_rows, key=lambda r: -float(r["l1_probability"]))
    lineup = tuple(str(r["canonical_player_uuid"]) for r in lin[:9])
    actual_starters = {str(r["canonical_player_uuid"]) for r in lineup_rows if int(r.get("target_start", 0)) == 1}
    recall = (sum(1 for u in lineup if u in actual_starters) / len(actual_starters)) if actual_starters else None
    # starter
    starter_uuid = None
    s2 = 18.0
    if starter_rows:
        sr = starter_rows[0]
        starter_uuid = str(sr["canonical_player_uuid"])
        s2 = float(sr["s2_bfp"])
    # relievers: b1-probability order
    bul = sorted(bullpen_rows, key=lambda r: -float(r["b1_probability"]))
    reliever_uuids = tuple(str(r["canonical_player_uuid"]) for r in bul)
    reliever_bfp = tuple(max(1.0, float(r["b1_bfp"])) for r in bul)
    return TeamProjection(lineup=lineup, starter_uuid=starter_uuid, s2_bfp=s2,
                          reliever_uuids=reliever_uuids, reliever_bfp=reliever_bfp, lineup_recall=recall)


# --------------------------------------------------------------------------------------
# Branch sequence construction
# --------------------------------------------------------------------------------------
def _projected_pitch_sequence(
    starter_uuid: str, s2_bfp: float, actual_pitchers: Sequence[str],
    reliever_uuids: Sequence[str], reliever_bfp: Sequence[float],
    length: int, *, projected_bullpen: bool,
) -> list[str]:
    """Build a pitcher-by-opponent-PA-ordinal sequence: starter for round(s2_bfp) batters, then bullpen."""
    k = max(1, int(round(s2_bfp)))
    seq = [starter_uuid] * min(k, length)
    if len(seq) >= length:
        return seq[:length]
    if projected_bullpen:
        # projected relievers, each for round(b1_bfp) batters, chained
        qi = 0
        while len(seq) < length and qi < len(reliever_uuids):
            dur = max(1, int(round(reliever_bfp[qi])))
            seq.extend([reliever_uuids[qi]] * dur)
            qi += 1
        while len(seq) < length:  # overflow: repeat last projected reliever (fallback)
            seq.append(reliever_uuids[-1] if reliever_uuids else starter_uuid)
    else:
        # oracle bullpen: the actual relievers after the actual starter stint
        actual_starter_stint = 0
        for p in actual_pitchers:
            if p == actual_pitchers[0]:
                actual_starter_stint += 1
            else:
                break
        tail = list(actual_pitchers[actual_starter_stint:])
        i = 0
        while len(seq) < length:
            seq.append(tail[i] if i < len(tail) else (tail[-1] if tail else starter_uuid))
            i += 1
    return seq[:length]


def build_branch_pa_uuids(
    branch: str,
    *,
    away_actual: Sequence[tuple[str, str]],   # [(batter_uuid, pitcher_uuid)] per away PA (P0)
    home_actual: Sequence[tuple[str, str]],
    away_proj: TeamProjection,                # away team batting projection + (as pitching) starter/relievers
    home_proj: TeamProjection,
) -> dict[str, Any]:
    """Return away_pa_uuids, home_pa_uuids, away_start, home_start for a branch."""

    if branch == "P0":
        return {
            "away_pa": list(away_actual), "home_pa": list(home_actual),
            "away_start": _distinct9([b for b, _ in away_actual]),
            "home_start": _distinct9([b for b, _ in home_actual]),
        }

    la = len(away_actual)
    lh = len(home_actual)
    away_pitchers_actual = [p for _, p in away_actual]  # home team's pitchers faced by away
    home_pitchers_actual = [p for _, p in home_actual]  # away team's pitchers faced by home

    # Batters: projected lineup rotating.
    away_bat = [away_proj.lineup[k % 9] for k in range(la)] if away_proj.lineup else [b for b, _ in away_actual]
    home_bat = [home_proj.lineup[k % 9] for k in range(lh)] if home_proj.lineup else [b for b, _ in home_actual]

    # Pitchers.
    if branch == "P1":
        away_pit = list(away_pitchers_actual)  # oracle pitching
        home_pit = list(home_pitchers_actual)
    else:
        projected_bullpen = branch == "P3"
        # away batters faced by home team's pitching (home starter/s2/relievers)
        away_pit = _projected_pitch_sequence(
            home_proj.starter_uuid or away_pitchers_actual[0], home_proj.s2_bfp, away_pitchers_actual,
            home_proj.reliever_uuids, home_proj.reliever_bfp, la, projected_bullpen=projected_bullpen)
        # home batters faced by away team's pitching
        home_pit = _projected_pitch_sequence(
            away_proj.starter_uuid or home_pitchers_actual[0], away_proj.s2_bfp, home_pitchers_actual,
            away_proj.reliever_uuids, away_proj.reliever_bfp, lh, projected_bullpen=projected_bullpen)

    away_pa = list(zip(away_bat, away_pit))
    home_pa = list(zip(home_bat, home_pit))
    away_start = list(away_proj.lineup) if away_proj.lineup else _distinct9([b for b, _ in away_actual])
    home_start = list(home_proj.lineup) if home_proj.lineup else _distinct9([b for b, _ in home_actual])
    return {"away_pa": away_pa, "home_pa": home_pa, "away_start": away_start, "home_start": home_start}


def _distinct9(uuids: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for u in uuids:
        if u not in seen:
            seen.append(u)
        if len(seen) == 9:
            break
    return seen


__all__ = [
    "BRANCHES", "BRANCH_LABELS",
    "ProjectionError", "TemporalStateResolver",
    "TeamProjection", "build_team_projections", "build_branch_pa_uuids",
]
