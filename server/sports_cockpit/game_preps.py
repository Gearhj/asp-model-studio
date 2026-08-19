"""Per-game participant orderings for the full lineup-rotation whole-game simulator.

Builds, for a bounded set of real games, the away/home plate-appearance sequences
(batter_uuid, pitcher_uuid) and the 9 starting batters needed by the Phase 5
``build_game_contribs`` kernel — mapping retrosheet ids to canonical uuids via the
plate_appearance_id join with the feature view. The governed play_transition columns are read
once and cached in-process; prep construction for a requested game sample is vectorized per game
(groupby, no row-by-row work over the full population).
"""

from __future__ import annotations

import glob
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from . import engine as E
from .engine import CockpitError, load_frame

MANIFEST = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
PLAY_TRANSITION_GLOB = (
    f"C:/Users/james/asp-model-exchange/datasets/mlb-fd1/sha256-{MANIFEST}/parquet/play_transition/**/*.parquet"
)

_PT_CACHE: dict[str, Any] = {}


@dataclass(frozen=True)
class GamePrep:
    game_id: str
    season: int
    game_date: str
    regulation: int
    away_pa: tuple[tuple[str, str], ...]
    home_pa: tuple[tuple[str, str], ...]
    away_start: tuple[str, ...]
    home_start: tuple[str, ...]
    actual_away: int
    actual_home: int


def _load_pt() -> tuple[pd.DataFrame, dict[str, str], dict[str, str]]:
    """Load needed play_transition columns once; build retrosheet→canonical uuid maps."""
    if "pt" in _PT_CACHE:
        return _PT_CACHE["pt"], _PT_CACHE["uuid_b"], _PT_CACHE["uuid_p"]
    import pyarrow.parquet as pq

    files = sorted(glob.glob(PLAY_TRANSITION_GLOB, recursive=True))
    if not files:
        raise CockpitError("governed play_transition dataset is not available")
    cols = [
        "game_id", "season", "play_number", "top_bottom", "batter_id", "pitcher_id",
        "pa_outcome", "plate_appearance_id", "regulation_innings", "pbp_quality",
        "game_date", "visiting_score_after", "home_score_after",
    ]
    pt = pd.concat([pq.read_table(f, columns=cols).to_pandas() for f in files], ignore_index=True)
    pt = pt[pt["pa_outcome"].notna() & (pt["pa_outcome"] != "")].copy()
    pt["game_id"] = pt["game_id"].astype(str)
    # retrosheet id -> canonical uuid via plate_appearance_id join with the feature view
    fv = load_frame()[["plate_appearance_id", "batter_canonical_player_uuid", "pitcher_canonical_player_uuid"]]
    merged = pt[["plate_appearance_id", "batter_id", "pitcher_id"]].merge(fv, on="plate_appearance_id", how="inner")
    uuid_b = dict(zip(merged["batter_id"].astype(str), merged["batter_canonical_player_uuid"].astype(str)))
    uuid_p = dict(zip(merged["pitcher_id"].astype(str), merged["pitcher_canonical_player_uuid"].astype(str)))
    _PT_CACHE["pt"] = pt
    _PT_CACHE["uuid_b"] = uuid_b
    _PT_CACHE["uuid_p"] = uuid_p
    return pt, uuid_b, uuid_p


def build_preps(season: int, game_ids: list[str]) -> list[GamePrep]:
    """Build participant-ordering preps for the requested games (canonical-uuid resolvable)."""
    pt, uuid_b, uuid_p = _load_pt()
    want = set(str(g) for g in game_ids)
    sub = pt[(pt["season"] == season) & (pt["game_id"].isin(want))].sort_values(["game_id", "play_number"])
    preps: list[GamePrep] = []
    fv_uuids_b = _season_uuids("batter_canonical_player_uuid", season)
    fv_uuids_p = _season_uuids("pitcher_canonical_player_uuid", season)
    for gid, g in sub.groupby("game_id", sort=False):
        if (g["pbp_quality"] != "FULL").any():
            continue
        reg = int(g["regulation_innings"].iloc[0]) if pd.notna(g["regulation_innings"].iloc[0]) else 9
        game_date = str(g["game_date"].iloc[0])
        last = g.iloc[-1]
        away_rows = g[g["top_bottom"] == 0]
        home_rows = g[g["top_bottom"] == 1]

        def seq(rows):
            out = []
            for bid, pid in zip(rows["batter_id"].astype(str), rows["pitcher_id"].astype(str)):
                bu = uuid_b.get(bid); pu = uuid_p.get(pid)
                if bu is None or pu is None or bu not in fv_uuids_b or pu not in fv_uuids_p:
                    return None
                out.append((bu, pu))
            return out

        away_pa = seq(away_rows); home_pa = seq(home_rows)
        if away_pa is None or home_pa is None or len(away_pa) < 9 or len(home_pa) < 9:
            continue

        def distinct9(pa):
            seen: list[str] = []
            for bu, _ in pa:
                if bu not in seen:
                    seen.append(bu)
                if len(seen) == 9:
                    break
            return seen

        aw, hm = distinct9(away_pa), distinct9(home_pa)
        if len(aw) < 9 or len(hm) < 9:
            continue
        preps.append(GamePrep(
            game_id=str(gid), season=season, game_date=game_date, regulation=reg,
            away_pa=tuple(away_pa), home_pa=tuple(home_pa), away_start=tuple(aw), home_start=tuple(hm),
            actual_away=int(last["visiting_score_after"]), actual_home=int(last["home_score_after"]),
        ))
    return preps


def _season_uuids(col: str, season: int) -> set[str]:
    key = f"{col}-{season}"
    if key not in _PT_CACHE:
        frame = load_frame()
        m = frame["season"].to_numpy() == season
        _PT_CACHE[key] = set(frame.loc[m, col].astype(str).unique())
    return _PT_CACHE[key]
