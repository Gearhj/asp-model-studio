"""Execute MLB_CATCHER_INFLUENCE_READINESS_V1 against governed FD1 evidence.

This wires the pure audit engine (``catcher_readiness.py``) to the already
registered FD1 dataset. It reads only the registered partitions (through the same
governed ``_read_family`` helper Milestone B uses), reconstructs catcher identity
from ``player_game_fielding`` (``fielding_position == 2``), and computes strict
prior-history battery / catcher-batter sample distributions **vectorized** so the
audit stays a data audit (target < 45 min), never a per-row Python loop over
millions of rows. It fits no model and estimates nothing.

Honest structural limits established from the resolved v5 schema:
- ``player_game_fielding`` is a per-player-per-game defensive aggregate with
  ``fielding_position``, ``stat_d_gs`` (started), ``appearance_sequence``, and
  ``stat_d_ifouts`` (defensive outs = innings*3), but **no in-game substitution
  event / PA index**. There is no governed substitution-event family. Therefore
  PA-level catcher assignment is DETERMINISTIC only for single-catcher team-games;
  multi-catcher team-games are reported AMBIGUOUS at the PA level rather than
  forward-filled.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from . import catcher_readiness as cr

CATCHER_POSITION = 2

_FIELDING_COLUMNS = (
    "game_id", "team_id", "player_id", "season", "game_date",
    "fielding_position", "stat_d_gs", "appearance_sequence", "stat_d_ifouts",
    "canonical_identity_resolved",
)
_PA_COLUMNS = (
    "game_id", "pitching_team_id", "batter_id", "pitcher_id", "season", "game_date",
    "half_play_number", "canonical_identity_resolved",
)
_ROLE_COLUMNS = ("game_id", "player_id", "team_id", "pitcher_role")


def _ordinal(series: pd.Series) -> pd.Series:
    """ISO game_date -> integer day ordinal (same-date rows share an ordinal)."""

    return pd.to_datetime(series, errors="coerce").map(
        lambda ts: date(ts.year, ts.month, ts.day).toordinal() if pd.notna(ts) else -1
    ).astype("int64")


def _vectorized_prior_counts(frame: pd.DataFrame, pair_col: str, ordinal_col: str) -> pd.Series:
    """Strictly-prior same-pair sample count for every row (bisect_left semantics).

    A row's prior count is the number of same-pair rows with an ordinal STRICTLY
    LESS than this row's ordinal. Same-ordinal ties (e.g. a doubleheader on the
    same day) are excluded from each other, exactly like ``bisect_left``. Vectorized
    via a per-(pair,ordinal) count and a shifted cumulative sum.
    """

    if frame.empty:
        return pd.Series([], dtype="int64")
    grouped = (
        frame.groupby([pair_col, ordinal_col], sort=True)
        .size()
        .reset_index(name="_n")
        .sort_values([pair_col, ordinal_col])
    )
    grouped["_prior"] = grouped.groupby(pair_col, sort=False)["_n"].cumsum() - grouped["_n"]
    merged = frame.merge(grouped[[pair_col, ordinal_col, "_prior"]], on=[pair_col, ordinal_col], how="left")
    return merged["_prior"].astype("int64").to_numpy()


def _band_series(prior: np.ndarray) -> dict[str, Any]:
    edges = np.array([0, 1, 10, 25, 50, 100, 250])
    labels = list(cr.SAMPLE_SIZE_BANDS)
    # band index: 0 -> "0"; 1-9 -> "1-9"; etc.
    idx = np.searchsorted(edges, prior, side="right") - 1
    idx = np.clip(idx, 0, len(labels) - 1)
    counts = {label: int((idx == i).sum()) for i, label in enumerate(labels)}
    population = int(prior.size)
    sorted_prior = np.sort(prior)

    def pct(p: float) -> float | None:
        return float(np.quantile(sorted_prior, p)) if population else None

    at_least = {
        f">={t}": {
            "count": int((prior >= t).sum()),
            "percentOfPopulation": float((prior >= t).mean()) if population else None,
        }
        for t in cr.SAMPLE_SIZE_AT_LEAST_THRESHOLDS
    }
    return {
        "population": population,
        "bands": {
            label: {
                "count": counts[label],
                "percentOfPopulation": (counts[label] / population) if population else None,
            }
            for label in labels
        },
        "medianPriorSamples": pct(0.50),
        "p75PriorSamples": pct(0.75),
        "p90PriorSamples": pct(0.90),
        "p95PriorSamples": pct(0.95),
        "maxPriorSamples": int(sorted_prior[-1]) if population else None,
        "atLeast": at_least,
    }


def reconstruct_team_game_catchers(fielding_df: pd.DataFrame) -> pd.DataFrame:
    """Per (game_id, team_id): catcher set, starter, status (single/multi/none)."""

    catchers = fielding_df[fielding_df["fielding_position"] == CATCHER_POSITION].copy()
    if catchers.empty:
        return pd.DataFrame(columns=["game_id", "team_id", "season", "status", "catcher_uuid", "num_catchers"])
    grouped = catchers.groupby(["game_id", "team_id"], sort=False)
    rows: list[dict[str, Any]] = []
    for (game_id, team_id), block in grouped:
        distinct = block["player_id"].dropna().unique().tolist()
        season = int(block["season"].iloc[0])
        started = block[block.get("stat_d_gs", 0) == 1]["player_id"].dropna().unique().tolist()
        if not started:
            # Fall back to the earliest appearance_sequence as the starter signal.
            ordered = block.sort_values("appearance_sequence")
            started = ordered["player_id"].dropna().head(1).tolist()
        if len(distinct) == 1:
            status, catcher = "DETERMINISTIC", distinct[0]
        elif len(distinct) == 0:
            status, catcher = "MISSING", None
        else:
            # More than one catcher in the team-game: starter is known, but PA-level
            # assignment across the substitution is not (no sub-timing family).
            status = "MULTI_CATCHER"
            catcher = started[0] if len(started) == 1 else None
        rows.append({
            "game_id": game_id, "team_id": team_id, "season": season,
            "status": status, "catcher_uuid": catcher, "num_catchers": len(distinct),
        })
    return pd.DataFrame(rows)


def compute_catcher_readiness(
    fielding_df: pd.DataFrame,
    pa_df: pd.DataFrame,
    role_map: Mapping[tuple[str, str], str],
    *,
    dataset_authority: Mapping[str, Any],
    identity_bridge_authority: Mapping[str, Any],
    available_field_names: Mapping[str, set[str]] | None = None,
) -> tuple["cr.CatcherReadinessAudit", dict[str, Any]]:
    """Pure over already-read frames (hermetically testable). Returns (audit, decision)."""

    team_games = reconstruct_team_game_catchers(fielding_df)
    seasons = sorted(int(s) for s in pd.unique(pa_df["season"])) if not pa_df.empty else []

    # ---- starting-catcher coverage by season -------------------------------
    starting_cov: dict[str, Any] = {}
    for season in seasons:
        tg = team_games[team_games["season"] == season]
        total = int(len(tg))
        deterministic = int((tg["status"] == "DETERMINISTIC").sum())
        multi = int((tg["status"] == "MULTI_CATCHER").sum())
        missing = int((tg["status"] == "MISSING").sum())
        # A team-game has a determinable *starting* catcher when it is single-catcher
        # or multi-catcher with exactly one identified starter.
        start_known = int(((tg["status"] == "DETERMINISTIC") | ((tg["status"] == "MULTI_CATCHER") & tg["catcher_uuid"].notna())).sum())
        starting_cov[str(season)] = {
            "teamGames": total,
            "singleCatcherTeamGames": deterministic,
            "multiCatcherTeamGames": multi,
            "missingCatcherTeamGames": missing,
            "startingCatcherDeterminable": start_known,
            "startingCatcherCoverageRate": (start_known / total) if total else None,
        }

    # ---- PA-level catcher assignment ---------------------------------------
    tg_index = team_games.set_index(["game_id", "team_id"])[["status", "catcher_uuid"]]
    pa = pa_df.merge(
        tg_index, left_on=["game_id", "pitching_team_id"], right_index=True, how="left"
    )
    pa["assign_status"] = np.where(
        pa["status"] == "DETERMINISTIC", "DETERMINISTIC",
        np.where(pa["status"] == "MULTI_CATCHER", "AMBIGUOUS", "MISSING"),
    )
    pa["catcher_uuid"] = np.where(pa["assign_status"] == "DETERMINISTIC", pa["catcher_uuid"], None)

    pa_cov: dict[str, Any] = {}
    for season in seasons:
        block = pa[pa["season"] == season]
        total = int(len(block))
        det = int((block["assign_status"] == "DETERMINISTIC").sum())
        amb = int((block["assign_status"] == "AMBIGUOUS").sum())
        miss = int((block["assign_status"] == "MISSING").sum())
        uniq = int(block.loc[block["catcher_uuid"].notna(), "catcher_uuid"].nunique())
        pa_cov[str(season)] = {
            "plateAppearances": total,
            "deterministicCatcherAssignment": det,
            "ambiguous": amb,
            "missing": miss,
            "paCatcherAssignmentCoverageRate": (det / total) if total else None,
            "uniqueCatchers": uniq,
        }

    # ---- prior-history distributions over the primary modeling population ---
    # History uses ALL determinable-catcher PAs (2021-2025) so a 2023 target sees
    # genuine prior seasons. Prior counts are computed ONCE per pair over the full
    # determinable frame (strictly-earlier ordinals only), then subset by season --
    # no second merge (which previously fanned out on a non-unique PA key).
    determinable = pa[(pa["assign_status"] == "DETERMINISTIC") & pa["catcher_uuid"].notna()].copy()
    determinable["_ord"] = _ordinal(determinable["game_date"])
    determinable["_battery"] = determinable["pitcher_id"].astype(str) + "|" + determinable["catcher_uuid"].astype(str)
    determinable["_cb"] = determinable["catcher_uuid"].astype(str) + "|" + determinable["batter_id"].astype(str)
    determinable["_battery_prior"] = _vectorized_prior_counts(determinable, "_battery", "_ord")
    determinable["_cb_prior"] = _vectorized_prior_counts(determinable, "_cb", "_ord")

    battery_by_season: dict[str, Any] = {}
    catcher_batter_by_season: dict[str, Any] = {}
    for season in cr.PRIMARY_MODELING_SEASONS:
        sub = determinable[determinable["season"] == season]
        battery = _band_series(sub["_battery_prior"].to_numpy())
        battery["uniquePairs"] = int(sub["_battery"].nunique())
        battery_by_season[str(season)] = battery
        cb = _band_series(sub["_cb_prior"].to_numpy())
        cb["uniquePairs"] = int(sub["_cb"].nunique())
        catcher_batter_by_season[str(season)] = cb

    # Role segmentation. starter_usage lists starters only, so a non-starter
    # deterministic PA is relievers-or-unknown (honestly labeled).
    primary = determinable[determinable["season"].isin(cr.PRIMARY_MODELING_SEASONS)]
    starter_keys = {k for k, v in role_map.items() if v == "STARTER"}
    is_starter = primary.apply(lambda r: (str(r["game_id"]), str(r["pitcher_id"])) in starter_keys, axis=1) if not primary.empty else pd.Series([], dtype=bool)
    role_segmented = {
        "starterPlateAppearances": int(is_starter.sum()) if len(is_starter) else 0,
        "relieverOrUnknownPlateAppearances": int((~is_starter).sum()) if len(is_starter) else 0,
        "note": "starter_usage governs only starters; non-starter PAs are reliever-or-unknown.",
    }

    battery_fallback = cr.battery_fallback_distribution(
        primary["_battery_prior"].to_numpy().tolist()
    )

    # ---- feature availability (confirmed against resolved schema) -----------
    available = available_field_names or {}
    feature_inventory = _confirm_feature_inventory(available)

    # ---- decision from measured coverage -----------------------------------
    primary_start = _weighted_rate(starting_cov, "startingCatcherDeterminable", "teamGames")
    primary_pa = _weighted_rate(pa_cov, "deterministicCatcherAssignment", "plateAppearances")
    # Identity linkage reliability: within-package catcher reconstruction joins EXACT
    # Retrosheet IDs (fielding.player_id <-> plate_appearance pitcher/batter). The raw
    # `canonical_identity_resolved` flag is False by design (the governed bridge
    # canonicalizes CROSS-family identities at join time), so reliability is assessed
    # on exact non-null ID presence, not that in-family flag.
    catcher_rows = fielding_df[fielding_df["fielding_position"] == CATCHER_POSITION]
    identity_linkage_reliable = bool(
        not pa_df.empty
        and pa_df["pitcher_id"].notna().mean() >= 0.99
        and pa_df["batter_id"].notna().mean() >= 0.99
        and not catcher_rows.empty
        and catcher_rows["player_id"].notna().mean() >= 0.99
    )
    decision = cr.decide_readiness(
        starting_catcher_coverage_rate=primary_start,
        pa_assignment_coverage_rate=primary_pa,
        identity_linkage_reliable=identity_linkage_reliable,
        battery_distribution_present=any(v.get("population", 0) for v in battery_by_season.values()),
        feature_inventory_present=bool(feature_inventory),
    )

    audit = cr.CatcherReadinessAudit(
        dataset_authority=dataset_authority,
        identity_bridge_authority=identity_bridge_authority,
        seasons=seasons,
        starting_catcher_coverage=starting_cov,
        pa_assignment_coverage=pa_cov,
        battery_distribution={"bySeason": battery_by_season, "roleSegmentation": role_segmented},
        battery_fallback=battery_fallback,
        catcher_batter_distribution={"bySeason": catcher_batter_by_season},
        feature_inventory=feature_inventory,
        premium_gaps=cr.premium_gap_inventory(),
        decision=decision,
        limitations=(
            *cr.DEFAULT_LIMITATIONS,
            "No governed substitution-event family exists; PA-level catcher assignment "
            "is deterministic only for single-catcher team-games and reported AMBIGUOUS "
            "for multi-catcher team-games.",
        ),
    )
    return audit, decision


def _weighted_rate(coverage: Mapping[str, Any], numerator: str, denominator: str) -> float | None:
    num = sum(v.get(numerator, 0) for k, v in coverage.items() if int(k) in cr.PRIMARY_MODELING_SEASONS)
    den = sum(v.get(denominator, 0) for k, v in coverage.items() if int(k) in cr.PRIMARY_MODELING_SEASONS)
    return (num / den) if den else None


def _confirm_feature_inventory(available: Mapping[str, set[str]]) -> list[dict[str, str]]:
    """Downgrade any inventory entry whose backing family/field is absent."""

    inventory = cr.free_feature_inventory()
    fielding_fields = available.get("player_game_fielding", set())
    backing = {
        "innings_caught": "stat_d_ifouts",
        "passed_balls": "stat_d_pb",
        "putouts": "stat_d_po",
        "assists": "stat_d_a",
        "errors": "stat_d_e",
        "double_plays": "stat_d_dp",
    }
    for item in inventory:
        needed = backing.get(item["field"])
        if needed and fielding_fields and needed not in fielding_fields:
            item["label"] = "UNAVAILABLE"
    return inventory


__all__ = [
    "CATCHER_POSITION",
    "compute_catcher_readiness",
    "reconstruct_team_game_catchers",
    "_vectorized_prior_counts",
    "_band_series",
]
