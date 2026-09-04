"""Point-in-time Gold V1 feature construction.

All historical aggregates use only rows whose ``gameDate`` is strictly less
than the target row's date.  PAs earlier in the same game or day are therefore
excluded together with the current PA.  Raw post-event Silver fields are used
only as historical facts before that cutoff; they are never copied into the
model matrix.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa

from .contracts import (
    ADVANCED_FEATURES,
    BATTER_HISTORY_FEATURES,
    BREAKING_PITCH_TYPES,
    CONTACT_PITCH_RESULTS,
    FASTBALL_PITCH_TYPES,
    GOLD_FEATURES,
    MATCHUP_FEATURES,
    OFFSPEED_PITCH_TYPES,
    PITCHER_HISTORY_FEATURES,
    SWING_PITCH_RESULTS,
    WHIFF_PITCH_RESULTS,
)


class GoldFeatureError(RuntimeError):
    """Gold feature inputs or point-in-time invariants differ."""


_WHIFF = frozenset(WHIFF_PITCH_RESULTS)
_CONTACT = frozenset(CONTACT_PITCH_RESULTS)
_SWING = frozenset(SWING_PITCH_RESULTS)
_FASTBALL = frozenset(FASTBALL_PITCH_TYPES)
_BREAKING = frozenset(BREAKING_PITCH_TYPES)
_OFFSPEED = frozenset(OFFSPEED_PITCH_TYPES)
_STRIKEOUT_EVENTS = frozenset({"strikeout", "strikeout_double_play"})
_WALK_HBP_EVENTS = frozenset({"walk", "intent_walk", "hit_by_pitch"})
_WALK_EVENTS = frozenset({"walk", "intent_walk"})


def _pitch_lazy(
    frame_or_paths: pa.Table | Sequence[Path],
    *,
    maximum_game_date: str | None = None,
) -> pl.LazyFrame:
    required = ["canonicalPaId", "pitchType", "releaseSpeed", "pitchResultType"]
    projection = [*required, "gameDate"] if maximum_game_date is not None else required
    if isinstance(frame_or_paths, pa.Table):
        missing = sorted(set(projection) - set(frame_or_paths.column_names))
        if missing:
            raise GoldFeatureError(f"pitch input columns missing: {missing}")
        lazy = pl.from_arrow(frame_or_paths.select(projection)).lazy()
        if maximum_game_date is not None:
            lazy = lazy.filter(pl.col("gameDate").cast(pl.String) <= maximum_game_date)
        return lazy.select(required)
    paths = [str(Path(path)) for path in frame_or_paths]
    if not paths:
        raise GoldFeatureError("pitch history requires verified child paths")
    # Verified Silver generations can carry additional immutable lineage
    # columns.  Gold consumes only this frozen projection, while still
    # failing closed when any required feature input is absent.
    lazy = pl.scan_parquet(paths, extra_columns="ignore")
    if maximum_game_date is not None:
        lazy = lazy.filter(pl.col("gameDate").cast(pl.String) <= maximum_game_date)
    return lazy.select(required)


def aggregate_pitch_history(
    frame_or_paths: pa.Table | Sequence[Path],
    *,
    maximum_game_date: str | None = None,
) -> pd.DataFrame:
    """Aggregate verified Silver pitches to PA-level history primitives.

    ``maximum_game_date`` is an inclusive source projection boundary used by
    sealed companion publications.  It is applied by the lazy Parquet scan
    before any pitch result, type, or velocity expression is evaluated.
    """

    lazy = _pitch_lazy(
        frame_or_paths, maximum_game_date=maximum_game_date
    ).with_columns(
        pl.col("pitchResultType").cast(pl.String).str.to_lowercase().fill_null("").alias("_result"),
        pl.col("pitchType").cast(pl.String).str.to_uppercase().fill_null("").alias("_type"),
        pl.col("releaseSpeed").cast(pl.Float64, strict=False).alias("_velo"),
    ).with_columns(
        pl.col("_result").is_in(list(_SWING)).cast(pl.Int64).alias("_swing"),
        pl.col("_result").is_in(list(_WHIFF)).cast(pl.Int64).alias("_whiff"),
        pl.col("_result").is_in(list(_CONTACT)).cast(pl.Int64).alias("_contact"),
        pl.col("_type").is_in(list(_FASTBALL)).cast(pl.Int64).alias("_fastball"),
        pl.col("_type").is_in(list(_BREAKING)).cast(pl.Int64).alias("_breaking"),
        pl.col("_type").is_in(list(_OFFSPEED)).cast(pl.Int64).alias("_offspeed"),
    ).with_columns(
        (
            1 - pl.col("_fastball") - pl.col("_breaking") - pl.col("_offspeed")
        ).cast(pl.Int64).alias("_other_or_unclassified"),
        pl.when((pl.col("_fastball") == 1) & pl.col("_velo").is_finite())
        .then(pl.col("_velo"))
        .otherwise(None)
        .alias("_fb_velo"),
    )
    grouped = lazy.group_by("canonicalPaId").agg(
        pl.len().cast(pl.Int64).alias("pitch_count"),
        pl.col("_swing").sum().alias("swing_count"),
        pl.col("_whiff").sum().alias("whiff_count"),
        pl.col("_contact").sum().alias("contact_count"),
        pl.col("_fastball").sum().alias("fastball_count"),
        pl.col("_breaking").sum().alias("breaking_count"),
        pl.col("_offspeed").sum().alias("offspeed_count"),
        pl.col("_other_or_unclassified").sum().alias("other_or_unclassified_pitch_count"),
    )
    try:
        out = grouped.collect(engine="streaming")
    except TypeError:  # Polars < 1.25 compatibility
        out = grouped.collect(streaming=True)

    # Parallel floating-point group reductions can accumulate the same source
    # values in a different order on separate executions. That is numerically
    # negligible but invalid for a content-addressed publication. Sort the
    # original finite float64 values by immutable PA identity and value, then
    # reduce each contiguous group in that fixed order. Source precision is
    # retained: no rounding, truncation, or integer coercion is applied.
    velocity_lazy = (
        lazy.filter(pl.col("_fb_velo").is_not_null())
        .select("canonicalPaId", "_fb_velo")
        .sort(["canonicalPaId", "_fb_velo"])
    )
    try:
        velocity_rows = velocity_lazy.collect(engine="streaming")
    except TypeError:  # Polars < 1.25 compatibility
        velocity_rows = velocity_lazy.collect(streaming=True)
    if velocity_rows.height:
        velocity_ids = velocity_rows.get_column("canonicalPaId").to_numpy()
        velocity_values = velocity_rows.get_column("_fb_velo").to_numpy().astype(
            np.float64, copy=False
        )
        starts = np.concatenate(
            (
                np.array([0], dtype=np.int64),
                np.flatnonzero(velocity_ids[1:] != velocity_ids[:-1]).astype(
                    np.int64, copy=False
                )
                + 1,
            )
        )
        ends = np.concatenate(
            (starts[1:], np.array([len(velocity_values)], dtype=np.int64))
        )
        velocity = pl.DataFrame(
            {
                "canonicalPaId": velocity_ids[starts],
                "fastball_velocity_sum": np.add.reduceat(velocity_values, starts),
                "fastball_velocity_sumsq": np.add.reduceat(
                    velocity_values * velocity_values, starts
                ),
                "fastball_velocity_count": (ends - starts).astype(
                    np.int64, copy=False
                ),
            }
        )
    else:
        velocity = pl.DataFrame(
            schema={
                "canonicalPaId": pl.String,
                "fastball_velocity_sum": pl.Float64,
                "fastball_velocity_sumsq": pl.Float64,
                "fastball_velocity_count": pl.Int64,
            }
        )
    out = (
        out.join(velocity, on="canonicalPaId", how="left")
        .with_columns(
            pl.col("fastball_velocity_sum").fill_null(0.0).cast(pl.Float64),
            pl.col("fastball_velocity_sumsq").fill_null(0.0).cast(pl.Float64),
            pl.col("fastball_velocity_count").fill_null(0).cast(pl.Int64),
        )
        .sort("canonicalPaId")
    )
    return out.to_pandas()


def prepare_pa_history(
    pa_table: pa.Table | pd.DataFrame,
    pitch_aggregates: pd.DataFrame,
    *,
    allowed_seasons: Sequence[int] = (2019, 2020, 2021, 2022, 2023, 2024),
) -> pd.DataFrame:
    """Build deterministic Silver PA history within an explicit season authority.

    The default remains the frozen 2019--2024 Gold V1 authority.  A bounded
    extension must opt in to every additional season at its call site.
    """

    frame = pa_table.to_pandas() if isinstance(pa_table, pa.Table) else pa_table.copy()
    required = {
        "canonicalPaId", "canonicalGameId", "mlbamGamePk", "atBatNumber",
        "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "season", "gameDate",
        "stand", "pThrows", "paEvent",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise GoldFeatureError(f"PA history columns missing: {missing}")
    if frame["canonicalPaId"].isna().any() or frame["canonicalPaId"].duplicated().any():
        raise GoldFeatureError("Silver PA identity is null or duplicated")
    frame["season"] = pd.to_numeric(frame["season"], errors="raise").astype(np.int16)
    governed_seasons = tuple(int(value) for value in allowed_seasons)
    if not governed_seasons or not frame["season"].isin(governed_seasons).all():
        raise GoldFeatureError("PA history includes a prohibited season")
    frame["gameDate"] = pd.to_datetime(frame["gameDate"], format="%Y-%m-%d", errors="raise")
    frame["mlbamGamePk"] = pd.to_numeric(frame["mlbamGamePk"], errors="raise").astype(np.int64)
    frame["atBatNumber"] = pd.to_numeric(frame["atBatNumber"], errors="raise").astype(np.int64)
    pitches = pitch_aggregates.copy()
    if pitches["canonicalPaId"].duplicated().any():
        raise GoldFeatureError("pitch aggregate contains duplicate PA identity")
    frame = frame.merge(pitches, on="canonicalPaId", how="left", validate="one_to_one")
    count_cols = [
        "pitch_count", "swing_count", "whiff_count", "contact_count", "fastball_count", "breaking_count",
        "offspeed_count", "other_or_unclassified_pitch_count", "fastball_velocity_sum",
        "fastball_velocity_sumsq", "fastball_velocity_count",
    ]
    for name in count_cols:
        if name not in frame:
            frame[name] = 0.0
        frame[name] = pd.to_numeric(frame[name], errors="coerce").fillna(0.0).astype(np.float64)
    event = frame["paEvent"].fillna("").astype(str).str.strip().str.lower()
    frame["_pa"] = 1.0
    frame["_strikeout"] = event.isin(_STRIKEOUT_EVENTS).astype(np.float64)
    frame["_walk_hbp"] = event.isin(_WALK_HBP_EVENTS).astype(np.float64)
    frame["_walk"] = event.isin(_WALK_EVENTS).astype(np.float64)
    return frame.sort_values(
        ["gameDate", "mlbamGamePk", "atBatNumber", "canonicalPaId"], kind="mergesort"
    ).reset_index(drop=True)


def _safe_rate(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator > 0.0 else float("nan")


def _prior_window_features(
    history: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    entity_column: str,
    window: int,
    role: str,
    return_sufficient_statistics: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
    metric_columns = [
        "_pa", "_strikeout", "_walk_hbp", "_walk", "swing_count", "whiff_count", "contact_count",
        "pitch_count", "fastball_count", "breaking_count", "offspeed_count",
        "other_or_unclassified_pitch_count", "fastball_velocity_sum",
        "fastball_velocity_sumsq", "fastball_velocity_count",
    ]
    expected = BATTER_HISTORY_FEATURES if role == "batter" else PITCHER_HISTORY_FEATURES
    statistic_columns = (
        ("batter_last100_swing_count", "batter_last100_whiff_count")
        if role == "batter"
        else (
            "pitcher_last250_pitch_count",
            "pitcher_last250_swing_count",
            "pitcher_last250_whiff_count",
            "pitcher_last250_fastball_count",
            "pitcher_last250_breaking_count",
            "pitcher_last250_offspeed_count",
            "pitcher_last250_other_or_unclassified_pitch_count",
            "pitcher_last250_fastball_velocity_count",
            "pitcher_last250_fastball_velocity_sum",
            "pitcher_last250_fastball_velocity_sumsq",
        )
    )
    ordered = history.sort_values(
        [entity_column, "gameDate", "mlbamGamePk", "atBatNumber", "canonicalPaId"], kind="mergesort"
    )
    result = pd.DataFrame(np.nan, index=targets.index, columns=list(expected), dtype=np.float64)
    statistics = pd.DataFrame(
        np.nan, index=targets.index, columns=list(statistic_columns), dtype=np.float64
    )
    history_group_indices = {
        str(key): indices for key, indices in ordered.groupby(entity_column, sort=False, dropna=False).indices.items()
    }
    for raw_entity, positions in targets.groupby(entity_column, sort=False, dropna=False).groups.items():
        entity = str(raw_entity)
        indices = history_group_indices.get(entity)
        if indices is None or raw_entity is None or (isinstance(raw_entity, float) and np.isnan(raw_entity)):
            continue
        group = ordered.iloc[indices]
        dates = group["gameDate"].to_numpy(dtype="datetime64[D]")
        values = group[metric_columns].to_numpy(dtype=np.float64)
        cumulative = np.vstack([np.zeros((1, values.shape[1]), dtype=np.float64), np.cumsum(values, axis=0)])
        target_dates = targets.loc[list(positions), "gameDate"]
        for target_date, day_positions in target_dates.groupby(target_dates).groups.items():
            cutoff = np.datetime64(target_date, "D")
            end = int(np.searchsorted(dates, cutoff, side="left"))
            start = max(0, end - window)
            sums = cumulative[end] - cumulative[start]
            sample = int(end - start)
            prior = int(end)
            m = dict(zip(metric_columns, sums.tolist()))
            if role == "batter":
                payload = {
                    "batter_prior_pa_count": float(prior),
                    "batter_last100_pa_count": float(sample),
                    "batter_last100_strikeout_rate": _safe_rate(m["_strikeout"], m["_pa"]),
                    "batter_last100_walk_hbp_rate": _safe_rate(m["_walk_hbp"], m["_pa"]),
                    "batter_last100_contact_rate": _safe_rate(m["contact_count"], m["swing_count"]),
                    "batter_last100_whiff_rate": _safe_rate(m["whiff_count"], m["swing_count"]),
                    "batter_last100_insufficient": float(sample < window),
                    "batter_last100_whiff_missing": float(m["swing_count"] <= 0.0),
                }
                statistic_payload = {
                    "batter_last100_swing_count": m["swing_count"],
                    "batter_last100_whiff_count": m["whiff_count"],
                }
            else:
                payload = {
                    "pitcher_prior_bf_count": float(prior),
                    "pitcher_last250_bf_count": float(sample),
                    "pitcher_last250_strikeout_rate": _safe_rate(m["_strikeout"], m["_pa"]),
                    "pitcher_last250_walk_rate": _safe_rate(m["_walk"], m["_pa"]),
                    "pitcher_last250_whiff_rate": _safe_rate(m["whiff_count"], m["swing_count"]),
                    "pitcher_last250_avg_fastball_velocity": _safe_rate(
                        m["fastball_velocity_sum"], m["fastball_velocity_count"]
                    ),
                    "pitcher_last250_fastball_usage": _safe_rate(m["fastball_count"], m["pitch_count"]),
                    "pitcher_last250_breaking_usage": _safe_rate(m["breaking_count"], m["pitch_count"]),
                    "pitcher_last250_offspeed_usage": _safe_rate(m["offspeed_count"], m["pitch_count"]),
                    "pitcher_last250_insufficient": float(sample < window),
                    "pitcher_last250_whiff_missing": float(m["swing_count"] <= 0.0),
                    "pitcher_last250_velocity_missing": float(m["fastball_velocity_count"] <= 0.0),
                }
                statistic_payload = {
                    "pitcher_last250_pitch_count": m["pitch_count"],
                    "pitcher_last250_swing_count": m["swing_count"],
                    "pitcher_last250_whiff_count": m["whiff_count"],
                    "pitcher_last250_fastball_count": m["fastball_count"],
                    "pitcher_last250_breaking_count": m["breaking_count"],
                    "pitcher_last250_offspeed_count": m["offspeed_count"],
                    "pitcher_last250_other_or_unclassified_pitch_count": m[
                        "other_or_unclassified_pitch_count"
                    ],
                    "pitcher_last250_fastball_velocity_count": m[
                        "fastball_velocity_count"
                    ],
                    "pitcher_last250_fastball_velocity_sum": m[
                        "fastball_velocity_sum"
                    ],
                    "pitcher_last250_fastball_velocity_sumsq": m[
                        "fastball_velocity_sumsq"
                    ],
                }
            result.loc[list(day_positions), list(payload)] = list(payload.values())
            statistics.loc[
                list(day_positions), list(statistic_payload)
            ] = list(statistic_payload.values())
    rates = result.reindex(columns=list(expected))
    if return_sufficient_statistics:
        return rates, statistics.reindex(columns=list(statistic_columns))
    return rates


def build_advanced_features_with_sufficient_statistics(
    history: pd.DataFrame,
    matched: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate Gold rates and their raw rolling evidence in one window pass."""

    if matched["canonicalPaId"].duplicated().any():
        raise GoldFeatureError("matched bridge contains duplicate canonical PA ids")
    lookup_columns = [
        "canonicalPaId", "gameDate", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "stand", "pThrows",
    ]
    target = matched.drop(columns=[c for c in lookup_columns[1:] if c in matched], errors="ignore").merge(
        history[lookup_columns], on="canonicalPaId", how="left", validate="one_to_one"
    )
    if target[["canonicalPaId", "gameDate", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId"]].isna().any().any():
        raise GoldFeatureError("matched target lacks Silver PA context")
    target.index = matched.index
    batter, batter_statistics = _prior_window_features(
        history,
        target,
        entity_column="batterCanonicalPlayerId",
        window=100,
        role="batter",
        return_sufficient_statistics=True,
    )
    pitcher, pitcher_statistics = _prior_window_features(
        history,
        target,
        entity_column="pitcherCanonicalPlayerId",
        window=250,
        role="pitcher",
        return_sufficient_statistics=True,
    )
    stand = target["stand"].fillna("").astype(str).str.upper()
    throws = target["pThrows"].fillna("").astype(str).str.upper()
    matchup = pd.DataFrame(index=target.index)
    matchup["matchup_batter_bats_left"] = stand.eq("L").astype(np.float64)
    matchup["matchup_batter_bats_switch"] = stand.eq("S").astype(np.float64)
    matchup["matchup_batter_hand_missing"] = (~stand.isin(["L", "R", "S"])).astype(np.float64)
    matchup["matchup_pitcher_throws_left"] = throws.eq("L").astype(np.float64)
    matchup["matchup_pitcher_hand_missing"] = (~throws.isin(["L", "R"])).astype(np.float64)
    matchup["matchup_platoon_advantage"] = (
        ((stand.eq("L") & throws.eq("R")) | (stand.eq("R") & throws.eq("L")) | (stand.eq("S") & throws.isin(["L", "R"])))
        & stand.isin(["L", "R", "S"]) & throws.isin(["L", "R"])
    ).astype(np.float64)
    advanced = pd.concat([batter, pitcher, matchup], axis=1).reindex(columns=list(ADVANCED_FEATURES))
    if advanced.shape[1] != len(ADVANCED_FEATURES):
        raise GoldFeatureError("advanced feature order differs from contract")
    return advanced, pd.concat([batter_statistics, pitcher_statistics], axis=1)


def build_advanced_features(history: pd.DataFrame, matched: pd.DataFrame) -> pd.DataFrame:
    """Calculate all 26 advanced features for matched target rows."""

    advanced, _ = build_advanced_features_with_sufficient_statistics(history, matched)
    return advanced


def assemble_gold_frame(matched: pd.DataFrame, advanced: pd.DataFrame) -> pd.DataFrame:
    """Combine target/base rows and advanced values in deterministic order."""

    missing = sorted(set(GOLD_FEATURES[:22]) - set(matched.columns))
    if missing:
        raise GoldFeatureError(f"matched Gen3 rows lack base features: {missing}")
    if not matched.index.equals(advanced.index):
        raise GoldFeatureError("advanced rows are not aligned to the matched bridge")
    lineage = [
        "canonicalPaId", "plate_appearance_id", "canonicalGameId", "game_id", "game_date", "season", "outcome",
        "batterCanonicalPlayerId", "pitcherCanonicalPlayerId",
    ]
    output = pd.concat([matched[lineage + list(GOLD_FEATURES[:22])], advanced], axis=1)
    if output["canonicalPaId"].duplicated().any() or output["plate_appearance_id"].duplicated().any():
        raise GoldFeatureError("Gold row key is not unique")
    output["datasetRole"] = np.where(output["season"].isin([2021, 2022, 2023]), "DEVELOPMENT", "VALIDATION")
    output = output.sort_values(
        ["season", "game_date", "game_id", "plate_appearance_id"], kind="mergesort"
    ).reset_index(drop=True)
    return output


def feature_quality_report(frame: pd.DataFrame) -> dict[str, Any]:
    rows = len(frame)
    def distribution(column: str) -> dict[str, float | int]:
        values = pd.to_numeric(frame[column], errors="raise").astype(np.float64)
        return {
            "rows": int(len(values)),
            "zeroRows": int(values.eq(0.0).sum()),
            "minimum": float(values.min()),
            "p25": float(values.quantile(0.25)),
            "median": float(values.quantile(0.50)),
            "p75": float(values.quantile(0.75)),
            "p90": float(values.quantile(0.90)),
            "p95": float(values.quantile(0.95)),
            "maximum": float(values.max()),
            "mean": float(values.mean()),
        }

    missingness = {
        name: {"missingRows": int(frame[name].isna().sum()), "missingRate": float(frame[name].isna().mean())}
        for name in ADVANCED_FEATURES
    }
    batter_unseen = frame["batter_prior_pa_count"].eq(0.0)
    pitcher_unseen = frame["pitcher_prior_bf_count"].eq(0.0)
    return {
        "schemaVersion": "MLB_GOLD_V1_FEATURE_QUALITY_V1",
        "rowCount": rows,
        "rowsBySeason": {str(int(k)): int(v) for k, v in frame.groupby("season").size().items()},
        "featureCount": len(GOLD_FEATURES),
        "missingness": missingness,
        "batterHistoryCoverage": float((frame["batter_prior_pa_count"] > 0).mean()),
        "pitcherHistoryCoverage": float((frame["pitcher_prior_bf_count"] > 0).mean()),
        "batterInsufficient100Rate": float(frame["batter_last100_insufficient"].mean()),
        "pitcherInsufficient250Rate": float(frame["pitcher_last250_insufficient"].mean()),
        "unseenPlayerCases": {
            "batterRows": int(batter_unseen.sum()),
            "pitcherRows": int(pitcher_unseen.sum()),
            "bothRows": int((batter_unseen & pitcher_unseen).sum()),
        },
        "sampleSizeDistributions": {
            "batterPriorPa": distribution("batter_prior_pa_count"),
            "batterLast100Pa": distribution("batter_last100_pa_count"),
            "pitcherPriorBf": distribution("pitcher_prior_bf_count"),
            "pitcherLast250Bf": distribution("pitcher_last250_bf_count"),
        },
        "duplicateKeys": {
            "canonicalPaId": int(frame["canonicalPaId"].duplicated().sum()),
            "plateAppearanceId": int(frame["plate_appearance_id"].duplicated().sum()),
        },
    }


__all__ = [
    "GoldFeatureError",
    "aggregate_pitch_history",
    "assemble_gold_frame",
    "build_advanced_features",
    "build_advanced_features_with_sufficient_statistics",
    "feature_quality_report",
    "prepare_pa_history",
]
