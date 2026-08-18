"""Materialize E1 leakage-safe batter/pitcher pitch-sequence process features.

Reads the governed ``pitch_sequence`` family, parses each PA with the deterministic
parser, then builds strictly prior-date cumulative and trailing-30-day process rates
for the batter and the pitcher. It fits **no model** and estimates nothing.

Leakage policy (identical strictness to D3 / Milestone B): a target PA's own pitches,
and any PA on the same calendar date (doubleheaders included), are excluded from its
own predictors -- prior evidence is strictly earlier than the target date.
Vectorized via per-(entity, day) cumulative sums and ``merge_asof`` (no per-row
Python loop over the aggregation).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from . import pitch_sequence_features as psf

PRIMARY_SEASONS: tuple[int, ...] = (2023, 2024, 2025)
TRAILING_WINDOW_DAYS = 30
LOW_SAMPLE_PA_THRESHOLD = 25

# Per-pitch counters summed cumulatively; rates are ratios of these.
_COUNT_COLS = ("pitches", "balls", "called_strikes", "swinging_strikes", "fouls", "in_play", "pas", "reached_two", "first_pitch_strike")

_RATE_DEFS = {
    "ball_rate": ("balls", "pitches"),
    "called_strike_rate": ("called_strikes", "pitches"),
    "swinging_strike_rate": ("swinging_strikes", "pitches"),
    "foul_rate": ("fouls", "pitches"),
    "in_play_rate": ("in_play", "pitches"),
    "two_strike_pa_rate": ("reached_two", "pas"),
    "first_pitch_strike_rate": ("first_pitch_strike", "pas"),
}


def _ordinal(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").map(
        lambda ts: date(ts.year, ts.month, ts.day).toordinal() if pd.notna(ts) else -1
    ).astype("int64")


def parse_pa_counts(seq_df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized-enough per-PA parse into a count frame (one row per PA)."""

    records = {c: np.zeros(len(seq_df), dtype="int64") for c in _COUNT_COLS}
    sequences = seq_df["source_pitch_sequence"].to_numpy()
    for i, raw in enumerate(sequences):
        parsed = psf.parse_sequence(raw)
        records["pitches"][i] = parsed.pitches
        records["balls"][i] = parsed.balls
        records["called_strikes"][i] = parsed.called_strikes
        records["swinging_strikes"][i] = parsed.swinging_strikes
        records["fouls"][i] = parsed.fouls
        records["in_play"][i] = parsed.in_play
        records["pas"][i] = 1 if parsed.pitches else 0  # a PA with >=1 parsed pitch
        records["reached_two"][i] = int(parsed.reached_two_strikes)
        records["first_pitch_strike"][i] = int(parsed.first_pitch_strike)
    out = pd.DataFrame(records)
    out["batter_id"] = seq_df["batter_id"].to_numpy()
    out["pitcher_id"] = seq_df["pitcher_id"].to_numpy()
    out["season"] = seq_df["season"].to_numpy()
    out["_ord"] = _ordinal(seq_df["game_date"]).to_numpy()
    return out


def _cumulative_before(counts: pd.DataFrame, entity: str) -> pd.DataFrame:
    """Per-(entity, day) cumulative-inclusive counts, sorted for as-of joins."""

    day = counts.groupby([entity, "_ord"], sort=True)[list(_COUNT_COLS)].sum().reset_index()
    day = day.sort_values([entity, "_ord"])
    cum = day.groupby(entity, sort=False)[list(_COUNT_COLS)].cumsum()
    for c in _COUNT_COLS:
        day[f"cum_{c}"] = cum[c].to_numpy()
    return day[[entity, "_ord"] + [f"cum_{c}" for c in _COUNT_COLS]]


def _asof_prior(targets: pd.DataFrame, day_cum: pd.DataFrame, entity: str, key_ord: str) -> pd.DataFrame:
    """Cumulative counts strictly before `key_ord` for each target row (as-of, exclusive)."""

    left = targets[[entity, key_ord]].reset_index().sort_values([key_ord, "index"])
    right = day_cum.rename(columns={"_ord": key_ord}).sort_values([key_ord, entity])
    merged = pd.merge_asof(
        left.sort_values(key_ord), right.sort_values(key_ord),
        on=key_ord, by=entity, direction="backward", allow_exact_matches=False,
    )
    merged = merged.set_index("index").sort_index()
    cols = [f"cum_{c}" for c in _COUNT_COLS]
    return merged[cols].fillna(0.0)


def _rates(prior: pd.DataFrame, prefix: str) -> pd.DataFrame:
    out = pd.DataFrame(index=prior.index)
    pitches = prior["cum_pitches"]
    pas = prior["cum_pas"]
    out[f"{prefix}_prior_pas"] = pas.astype("int64")
    out[f"{prefix}_prior_pitches"] = pitches.astype("int64")
    for name, (num, den) in _RATE_DEFS.items():
        denom = prior[f"cum_{den}"]
        rate = np.where(denom > 0, prior[f"cum_{num}"] / denom.replace(0, np.nan), np.nan)
        out[f"{prefix}_{name}"] = rate
    out[f"{prefix}_pitches_per_pa"] = np.where(pas > 0, pitches / pas.replace(0, np.nan), np.nan)
    out[f"{prefix}_missing_history"] = (pas <= 0).astype("int64")
    out[f"{prefix}_low_sample"] = (pas < LOW_SAMPLE_PA_THRESHOLD).astype("int64")
    return out


def build_features(counts: pd.DataFrame) -> pd.DataFrame:
    """Assemble the per-PA E1 feature matrix for the primary target seasons."""

    features = counts[["batter_id", "pitcher_id", "season", "_ord"]].copy()
    for entity, label in (("batter_id", "batter"), ("pitcher_id", "pitcher")):
        day_cum = _cumulative_before(counts, entity)
        # cumulative-to-date = strictly before this PA's day.
        cum_prior = _asof_prior(counts, day_cum, entity, "_ord")
        features = features.join(_rates(cum_prior, f"{label}_cum"))
        # trailing 30d = C(d) - C(d-30).
        window = counts[[entity]].copy()
        window["_ord_lag"] = counts["_ord"] - TRAILING_WINDOW_DAYS
        prior_lag = _asof_prior(window.assign(_ord=counts["_ord"]), day_cum, entity, "_ord_lag")
        trailing = pd.DataFrame(index=counts.index)
        for c in _COUNT_COLS:
            trailing[f"cum_{c}"] = (cum_prior[f"cum_{c}"].to_numpy() - prior_lag[f"cum_{c}"].to_numpy()).clip(min=0)
        features = features.join(_rates(trailing, f"{label}_trail30"))
    return features[features["season"].isin(PRIMARY_SEASONS)].reset_index(drop=True)


def _coverage(features: pd.DataFrame) -> dict[str, Any]:
    cov: dict[str, Any] = {}
    for season in PRIMARY_SEASONS:
        block = features[features["season"] == season]
        total = int(len(block))
        both_present = int(((block["batter_cum_prior_pas"] > 0) & (block["pitcher_cum_prior_pas"] > 0)).sum())
        batter_missing = int((block["batter_cum_prior_pas"] <= 0).sum())
        pitcher_missing = int((block["pitcher_cum_prior_pas"] <= 0).sum())
        cov[str(season)] = {
            "targetPlateAppearances": total,
            "bothHistoryPresent": both_present,
            "bothPresentRate": (both_present / total) if total else None,
            "batterMissingHistory": batter_missing,
            "pitcherMissingHistory": pitcher_missing,
            "batterLowSample": int((block["batter_cum_low_sample"] == 1).sum()),
            "pitcherLowSample": int((block["pitcher_cum_low_sample"] == 1).sum()),
        }
    return cov


def _early_season_missing(features: pd.DataFrame) -> dict[str, Any]:
    """Batter missing-history rate by month (proxy for early-season cold start)."""

    tmp = features.copy()
    tmp["_month"] = (pd.to_datetime(tmp["_ord"].map(date.fromordinal))).dt.month
    rows = []
    for month, block in tmp.groupby("_month"):
        rows.append({
            "month": int(month),
            "batterMissingRate": float((block["batter_cum_prior_pas"] <= 0).mean()),
            "pitcherMissingRate": float((block["pitcher_cum_prior_pas"] <= 0).mean()),
        })
    return {"byMonth": sorted(rows, key=lambda r: r["month"])}


def _feature_summary(features: pd.DataFrame) -> list[dict[str, Any]]:
    summary = []
    rate_cols = [c for c in features.columns if c.endswith("_rate") or c.endswith("pitches_per_pa")]
    for col in rate_cols:
        s = features[col]
        nn = int(s.notna().sum())
        summary.append({
            "feature": col,
            "nonNull": nn,
            "coverageRate": (nn / len(features)) if len(features) else None,
            "mean": float(s.mean()) if nn else None,
            "std": float(s.std()) if nn else None,
            "p10": float(s.quantile(0.10)) if nn else None,
            "p50": float(s.quantile(0.50)) if nn else None,
            "p90": float(s.quantile(0.90)) if nn else None,
        })
    return summary


def _strikeout_walk_readiness() -> dict[str, Any]:
    """Descriptive availability for D3's known STRIKEOUT / WALK weaknesses. No model."""

    strikeout = {
        "batter_swinging_strike_tendency": "AVAILABLE",
        "batter_called_strike_tendency": "AVAILABLE",
        "batter_two_strike_frequency": "AVAILABLE",
        "batter_two_strike_swing_miss_tendency": "PARTIAL",
        "pitcher_swinging_strike_tendency": "AVAILABLE",
        "pitcher_called_strike_tendency": "AVAILABLE",
        "pitcher_two_strike_frequency": "AVAILABLE",
        "pitcher_two_strike_swing_miss_tendency": "PARTIAL",
        "first_pitch_strike_tendency": "AVAILABLE",
        "sequence_length_discipline": "AVAILABLE",
    }
    walk = {
        "batter_ball_rate_tendency": "AVAILABLE",
        "pitcher_ball_rate_tendency": "AVAILABLE",
        "full_count_frequency": "PARTIAL",
        "pitches_per_pa": "AVAILABLE",
        "called_strike_tendency": "AVAILABLE",
        "intentional_ball_pitchout_distinction": "PARTIAL",
    }
    return {"strikeout": strikeout, "walk": walk}


def _rare_outcome_limitations() -> list[str]:
    return [
        "Pitch-sequence process features alone may not resolve HOME_RUN / DOUBLE / "
        "TRIPLE / OTHER_REACH: the free encoding lacks exit velocity, launch angle, "
        "barrel / hard-hit, pitch location, velocity, and movement.",
        "E1 measures plate-discipline process, not contact quality; it is expected to "
        "be most relevant to STRIKEOUT and WALK_HBP_CI, least to rare batted-ball events.",
    ]


def compute_pitch_sequence_readiness(
    counts: pd.DataFrame,
    features: pd.DataFrame,
    parse_quality: Mapping[str, Any],
    per_season_quality: Mapping[str, Any],
    *,
    dataset_authority: Mapping[str, Any],
    identity_bridge_authority: Mapping[str, Any],
    feature_columns: list[str],
) -> dict[str, Any]:
    batter_feats = [c for c in feature_columns if c.startswith("batter_")]
    pitcher_feats = [c for c in feature_columns if c.startswith("pitcher_")]
    readiness = psf.readiness_from_quality(parse_quality)
    status = {
        "PITCH_SEQUENCE_READY": "PITCH_SEQUENCE_FEATURES_READY",
        "PITCH_SEQUENCE_PARTIALLY_READY": "PITCH_SEQUENCE_FEATURES_PARTIALLY_READY",
        "PITCH_SEQUENCE_BLOCKED": "PITCH_SEQUENCE_FEATURES_BLOCKED",
    }[readiness]
    return {
        "schemaVersion": psf.FEATURE_SCHEMA_VERSION,
        "contractName": psf.FEATURE_CONTRACT_NAME,
        "parserVersion": psf.PARSER_VERSION,
        "datasetAuthority": dict(dataset_authority),
        "identityBridgeAuthority": dict(identity_bridge_authority),
        "seasons": sorted(int(s) for s in pd.unique(counts["season"])),
        "primaryModelingSeasons": list(PRIMARY_SEASONS),
        "parserCategories": psf.parser_category_table(),
        "parseQuality": dict(parse_quality),
        "parseQualityBySeason": dict(per_season_quality),
        "trailingWindowDays": TRAILING_WINDOW_DAYS,
        "batterFeatureCount": len(batter_feats),
        "pitcherFeatureCount": len(pitcher_feats),
        "totalFeatureCount": len(feature_columns),
        "batterFeatures": batter_feats,
        "pitcherFeatures": pitcher_feats,
        "coverage": _coverage(features),
        "earlySeasonMissing": _early_season_missing(features),
        "featureSummary": _feature_summary(features),
        "strikeoutWalkReadiness": _strikeout_walk_readiness(),
        "rareOutcomeLimitations": _rare_outcome_limitations(),
        "e2InputContract": {
            "status": "DESIGN_ONLY_NOT_MATERIALIZED",
            "note": "Future E2 combines batter process state x pitcher process state.",
            "examples": [
                "batter_cum_swinging_strike_rate x pitcher_cum_swinging_strike_rate",
                "batter_cum_ball_rate x pitcher_cum_ball_rate",
                "batter_cum_first_pitch_strike_rate x pitcher_cum_first_pitch_strike_rate",
                "batter_cum_two_strike_pa_rate x pitcher_cum_two_strike_pa_rate",
            ],
        },
        "terminalStatus": status,
        "limitations": (
            "This is a feature-materialization readiness audit; NO model is trained or "
            "evaluated and no predictive improvement is claimed.",
            "Features use only strictly-prior-date evidence (target PA and same-date PAs "
            "excluded); players with no prior history carry explicit missing/low-sample "
            "indicators, never future or full-season fill.",
            "The free encoding contains no velocity, pitch type, location, movement, "
            "target, catcher call, or contact-quality facts; none are inferred.",
            *(_rare_outcome_limitations()),
        ),
    }


__all__ = [
    "LOW_SAMPLE_PA_THRESHOLD",
    "PRIMARY_SEASONS",
    "TRAILING_WINDOW_DAYS",
    "build_features",
    "compute_pitch_sequence_readiness",
    "parse_pa_counts",
]
