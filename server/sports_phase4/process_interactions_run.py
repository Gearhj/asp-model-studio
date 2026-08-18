"""MLB_BATTER_PITCHER_PROCESS_INTERACTIONS_V1 — E2 matchup interaction features.

A bounded, baseball-motivated, leakage-safe transformation of the already governed
E1 pitch-sequence process features (batter state × pitcher state). It fits **no
model**, uses **no target**, and performs **no learned transform** (no PCA, no
target encoding, no clustering, no fold-local normalization). Every E2 row is a pure
row-local function of the parent E1 row, so the target population and row count are
preserved exactly (no merge, no fan-out) and E1's strict prior-date leakage safety is
inherited unchanged.

Deferred to future model folds (marked MODEL_FOLD_DERIVED in the contract, not
materialized here): league-relative contrasts and any transform requiring fitting.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

INTERACTION_CONTRACT_NAME = "MLB_BATTER_PITCHER_PROCESS_INTERACTIONS_V1"
INTERACTION_SCHEMA_VERSION = "MLB_BATTER_PITCHER_PROCESS_INTERACTIONS_V1"
PRIMARY_SEASONS: tuple[int, ...] = (2023, 2024, 2025)
FEATURE_HARD_MAX = 60
HIGH_CORRELATION_FLAG = 0.95

ID_COLUMNS: tuple[str, ...] = ("batter_id", "pitcher_id", "season", "_ord")


def _prod(a: str, b: str) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda df: df[a] * df[b]


def _absdiff(a: str, b: str) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda df: (df[a] - df[b]).abs()


def _both_and(a: str, b: str) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda df: (df[a].fillna(0).astype("int64") & df[b].fillna(0).astype("int64")).astype("int64")


def _both_present(a: str, b: str) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda df: ((1 - df[a].fillna(0).astype("int64")) & (1 - df[b].fillna(0).astype("int64"))).astype("int64")


def _log_sample_product(a: str, b: str) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda df: np.log1p(df[a].clip(lower=0)) * np.log1p(df[b].clip(lower=0))


def _min_log_sample(a: str, b: str) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda df: np.minimum(np.log1p(df[a].clip(lower=0)), np.log1p(df[b].clip(lower=0)))


def _passthrough(a: str) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda df: df[a].fillna(0).astype("int64")


# Declarative, bounded feature spec: (name, family, callable). Cumulative window is
# the primary matchup signal; a few trailing-30d recent-form products are included.
INTERACTION_SPECS: tuple[tuple[str, str, Callable[[pd.DataFrame], pd.Series]], ...] = (
    # --- STRIKEOUT / SWING-MISS process ---
    ("bp_swinging_strike_product", "strikeout", _prod("batter_cum_swinging_strike_rate", "pitcher_cum_swinging_strike_rate")),
    ("bp_swinging_strike_absdiff", "strikeout", _absdiff("batter_cum_swinging_strike_rate", "pitcher_cum_swinging_strike_rate")),
    ("bp_called_strike_product", "strikeout", _prod("batter_cum_called_strike_rate", "pitcher_cum_called_strike_rate")),
    ("bp_two_strike_product", "strikeout", _prod("batter_cum_two_strike_pa_rate", "pitcher_cum_two_strike_pa_rate")),
    # --- WALK / COMMAND process ---
    ("bp_ball_rate_product", "walk", _prod("batter_cum_ball_rate", "pitcher_cum_ball_rate")),
    ("bp_ball_rate_absdiff", "walk", _absdiff("batter_cum_ball_rate", "pitcher_cum_ball_rate")),
    ("bp_pitches_per_pa_product", "walk", _prod("batter_cum_pitches_per_pa", "pitcher_cum_pitches_per_pa")),
    ("bp_pitches_per_pa_absdiff", "walk", _absdiff("batter_cum_pitches_per_pa", "pitcher_cum_pitches_per_pa")),
    ("batter_patience_x_pitcher_command", "walk", _prod("batter_cum_called_strike_rate", "pitcher_cum_ball_rate")),
    # --- FIRST-PITCH process ---
    ("bp_first_pitch_strike_product", "first_pitch", _prod("batter_cum_first_pitch_strike_rate", "pitcher_cum_first_pitch_strike_rate")),
    ("bp_first_pitch_strike_absdiff", "first_pitch", _absdiff("batter_cum_first_pitch_strike_rate", "pitcher_cum_first_pitch_strike_rate")),
    # --- CONTACT process ---
    ("bp_in_play_product", "contact", _prod("batter_cum_in_play_rate", "pitcher_cum_in_play_rate")),
    ("bp_in_play_absdiff", "contact", _absdiff("batter_cum_in_play_rate", "pitcher_cum_in_play_rate")),
    ("bp_foul_product", "contact", _prod("batter_cum_foul_rate", "pitcher_cum_foul_rate")),
    # --- SAMPLE / RELIABILITY interactions (log-safe) ---
    ("bp_log_sample_product", "sample", _log_sample_product("batter_cum_prior_pas", "pitcher_cum_prior_pas")),
    ("bp_min_log_sample", "sample", _min_log_sample("batter_cum_prior_pas", "pitcher_cum_prior_pas")),
    ("both_process_low_sample", "sample", _both_and("batter_cum_low_sample", "pitcher_cum_low_sample")),
    ("both_process_missing", "sample", _both_and("batter_cum_missing_history", "pitcher_cum_missing_history")),
    ("both_process_history_present", "sample", _both_present("batter_cum_missing_history", "pitcher_cum_missing_history")),
    ("batter_process_missing", "sample", _passthrough("batter_cum_missing_history")),
    ("pitcher_process_missing", "sample", _passthrough("pitcher_cum_missing_history")),
    # --- TRAILING-30d recent-form matchup products ---
    ("bp_swinging_strike_product_trail30", "recent_form", _prod("batter_trail30_swinging_strike_rate", "pitcher_trail30_swinging_strike_rate")),
    ("bp_ball_rate_product_trail30", "recent_form", _prod("batter_trail30_ball_rate", "pitcher_trail30_ball_rate")),
    ("bp_first_pitch_strike_product_trail30", "recent_form", _prod("batter_trail30_first_pitch_strike_rate", "pitcher_trail30_first_pitch_strike_rate")),
    ("bp_two_strike_product_trail30", "recent_form", _prod("batter_trail30_two_strike_pa_rate", "pitcher_trail30_two_strike_pa_rate")),
)

FEATURE_NAMES: tuple[str, ...] = tuple(name for name, _f, _c in INTERACTION_SPECS)
INTERACTION_FAMILIES: tuple[str, ...] = ("strikeout", "walk", "first_pitch", "contact", "sample", "recent_form")


class ProcessInteractionError(RuntimeError):
    pass


def required_e1_columns() -> set[str]:
    """The exact E1 columns this contract reads (for authority verification)."""

    cols: set[str] = set(ID_COLUMNS)
    # Re-derive from the closures' source is not possible; enumerate explicitly.
    for a, b in (
        ("batter_cum_swinging_strike_rate", "pitcher_cum_swinging_strike_rate"),
        ("batter_cum_called_strike_rate", "pitcher_cum_called_strike_rate"),
        ("batter_cum_two_strike_pa_rate", "pitcher_cum_two_strike_pa_rate"),
        ("batter_cum_ball_rate", "pitcher_cum_ball_rate"),
        ("batter_cum_pitches_per_pa", "pitcher_cum_pitches_per_pa"),
        ("batter_cum_first_pitch_strike_rate", "pitcher_cum_first_pitch_strike_rate"),
        ("batter_cum_in_play_rate", "pitcher_cum_in_play_rate"),
        ("batter_cum_foul_rate", "pitcher_cum_foul_rate"),
        ("batter_cum_prior_pas", "pitcher_cum_prior_pas"),
        ("batter_cum_low_sample", "pitcher_cum_low_sample"),
        ("batter_cum_missing_history", "pitcher_cum_missing_history"),
        ("batter_trail30_swinging_strike_rate", "pitcher_trail30_swinging_strike_rate"),
        ("batter_trail30_ball_rate", "pitcher_trail30_ball_rate"),
        ("batter_trail30_first_pitch_strike_rate", "pitcher_trail30_first_pitch_strike_rate"),
        ("batter_trail30_two_strike_pa_rate", "pitcher_trail30_two_strike_pa_rate"),
    ):
        cols.add(a)
        cols.add(b)
    return cols


def build_interactions(e1: pd.DataFrame) -> pd.DataFrame:
    """Row-local E2 transform of E1. Output row count == input row count (no merge)."""

    if len(FEATURE_NAMES) > FEATURE_HARD_MAX:
        raise ProcessInteractionError(f"E2 feature count {len(FEATURE_NAMES)} exceeds hard max {FEATURE_HARD_MAX}")
    missing = required_e1_columns() - set(e1.columns)
    if missing:
        raise ProcessInteractionError(f"parent E1 schema is missing required columns: {sorted(missing)}")
    out = e1[list(ID_COLUMNS)].copy()
    for name, _family, fn in INTERACTION_SPECS:
        out[name] = fn(e1).to_numpy()
    if len(out) != len(e1):
        raise ProcessInteractionError("E2 row count diverged from E1 (fan-out or row loss)")
    return out


def feature_distribution_audit(e2: pd.DataFrame) -> dict[str, Any]:
    seasons: dict[str, Any] = {}
    for season in PRIMARY_SEASONS:
        block = e2[e2["season"] == season]
        total = int(len(block))
        rows = []
        for name in FEATURE_NAMES:
            s = block[name]
            nn = int(s.notna().sum())
            q = s.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]) if nn else None
            rows.append({
                "feature": name,
                "nonNull": nn,
                "nullCount": total - nn,
                "coverageRate": (nn / total) if total else None,
                "mean": float(s.mean()) if nn else None,
                "std": float(s.std()) if nn else None,
                "min": float(s.min()) if nn else None,
                "p01": float(q.loc[0.01]) if nn else None,
                "p05": float(q.loc[0.05]) if nn else None,
                "p25": float(q.loc[0.25]) if nn else None,
                "median": float(q.loc[0.5]) if nn else None,
                "p75": float(q.loc[0.75]) if nn else None,
                "p95": float(q.loc[0.95]) if nn else None,
                "p99": float(q.loc[0.99]) if nn else None,
                "max": float(s.max()) if nn else None,
            })
        seasons[str(season)] = {"rows": total, "features": rows}
    return seasons


def redundancy_audit(e2: pd.DataFrame) -> dict[str, Any]:
    """Descriptive predictor-only redundancy. No target, no supervised selection."""

    numeric = e2[list(FEATURE_NAMES)].astype("float64")
    # Near-constant features (structurally useless).
    near_constant = [name for name in FEATURE_NAMES if float(numeric[name].std(ddof=0) or 0.0) < 1e-12]
    # Exact duplicate columns (identical values ignoring NaN alignment).
    exact_duplicates: list[list[str]] = []
    seen: dict[bytes, str] = {}
    for name in FEATURE_NAMES:
        key = np.nan_to_num(numeric[name].to_numpy(), nan=-9.99e17).tobytes()
        if key in seen:
            exact_duplicates.append([seen[key], name])
        else:
            seen[key] = name
    # High |Pearson| pairs (sampled for speed; predictor-only).
    sample = numeric.sample(n=min(50000, len(numeric)), random_state=20260818) if len(numeric) else numeric
    corr = sample.corr(method="pearson")
    high_pairs = []
    cols = list(FEATURE_NAMES)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c = corr.iloc[i, j]
            if pd.notna(c) and abs(c) >= HIGH_CORRELATION_FLAG:
                high_pairs.append({"a": cols[i], "b": cols[j], "pearson": round(float(c), 4)})
    return {
        "nearConstantFeatures": near_constant,
        "exactDuplicateGroups": exact_duplicates,
        "highCorrelationPairs": sorted(high_pairs, key=lambda r: -abs(r["pearson"]))[:25],
        "highCorrelationThreshold": HIGH_CORRELATION_FLAG,
    }


def _coverage(e2: pd.DataFrame) -> dict[str, Any]:
    cov: dict[str, Any] = {}
    for season in PRIMARY_SEASONS:
        block = e2[e2["season"] == season]
        total = int(len(block))
        both_present = int((block["both_process_history_present"] == 1).sum())
        cov[str(season)] = {
            "rows": total,
            "bothProcessHistoryPresent": both_present,
            "bothPresentRate": (both_present / total) if total else None,
            "batterProcessMissing": int((block["batter_process_missing"] == 1).sum()),
            "pitcherProcessMissing": int((block["pitcher_process_missing"] == 1).sum()),
            "bothProcessLowSample": int((block["both_process_low_sample"] == 1).sum()),
        }
    return cov


def _strikeout_walk_readiness() -> dict[str, Any]:
    return {
        "strikeout": {
            "swing_miss_vulnerability_x_dominance": "AVAILABLE",
            "called_strike_exposure_x_tendency": "AVAILABLE",
            "two_strike_vulnerability_x_dominance": "AVAILABLE",
            "first_pitch_strike_interaction": "AVAILABLE",
            "sample_reliability_interaction": "AVAILABLE",
        },
        "walk": {
            "ball_tendency_x_ball_tendency": "AVAILABLE",
            "patience_x_command": "AVAILABLE",
            "pitches_per_pa_x_pitches_per_bf": "AVAILABLE",
            "full_count_interaction": "PARTIAL",
            "called_strike_x_command_contrast": "AVAILABLE",
        },
    }


def _limitations() -> tuple[str, ...]:
    return (
        "E2 is a bounded, model-agnostic interaction feature family; NO model is "
        "trained or evaluated and no predictive improvement is claimed.",
        "E2 inherits E1's strict prior-date leakage safety and is a pure row-local "
        "transform of E1 rows (row count preserved; no merge, no fan-out).",
        "E2 still lacks handedness/platoon, velocity, pitch type, movement, location, "
        "contact quality, catcher framing, and the actual pitch caller; none are "
        "inferred. Rare batted-ball outcomes (HOME_RUN/DOUBLE/TRIPLE/OTHER_REACH) "
        "remain limited by missing contact-quality/tracking evidence.",
        "League-relative and any fitting-dependent contrasts are deferred to future "
        "model folds (MODEL_FOLD_DERIVED), not materialized globally here.",
    )


def compute_readiness_payload(
    e2: pd.DataFrame,
    distribution: Mapping[str, Any],
    redundancy: Mapping[str, Any],
    *,
    dataset_authority: Mapping[str, Any],
    identity_bridge_authority: Mapping[str, Any],
    parent_e1: Mapping[str, Any],
    rows_read: int,
) -> dict[str, Any]:
    integrity_ok = (
        int(len(e2)) == int(rows_read)
        and not redundancy.get("exactDuplicateGroups")
        and not redundancy.get("nearConstantFeatures")
    )
    status = "PROCESS_INTERACTIONS_READY" if integrity_ok else "PROCESS_INTERACTIONS_PARTIALLY_READY"
    families: dict[str, list[str]] = {fam: [] for fam in INTERACTION_FAMILIES}
    for name, family, _fn in INTERACTION_SPECS:
        families[family].append(name)
    return {
        "schemaVersion": INTERACTION_SCHEMA_VERSION,
        "contractName": INTERACTION_CONTRACT_NAME,
        "datasetAuthority": dict(dataset_authority),
        "identityBridgeAuthority": dict(identity_bridge_authority),
        "parentE1": dict(parent_e1),
        "seasons": sorted(int(s) for s in pd.unique(e2["season"])),
        "primaryModelingSeasons": list(PRIMARY_SEASONS),
        "featureCount": len(FEATURE_NAMES),
        "featureHardMax": FEATURE_HARD_MAX,
        "interactionFamilies": families,
        "features": list(FEATURE_NAMES),
        "coverage": _coverage(e2),
        "featureDistribution": distribution,
        "redundancy": redundancy,
        "strikeoutWalkReadiness": _strikeout_walk_readiness(),
        "e6HandoffNote": {
            "status": "DESIGN_ONLY",
            "note": "A future governed E6 companion (bats L/R/S, throws L/R, primary "
                    "position, optional age/debut) would segment these interactions by "
                    "platoon quadrant: LHB-vs-LHP, LHB-vs-RHP, RHB-vs-LHP, RHB-vs-RHP, "
                    "and switch-hitter effective side. Not acquired here.",
        },
        "archetypeHandoffNote": {
            "status": "DESIGN_ONLY",
            "note": "A future archetype study should represent players with E1 process "
                    "states + E2 matchup structure + E6 handedness/platoon rather than "
                    "static annual features alone. No clustering is performed here.",
        },
        "rowsRead": int(rows_read),
        "rowsMaterialized": int(len(e2)),
        "terminalStatus": status,
        "limitations": _limitations(),
    }


__all__ = [
    "FEATURE_HARD_MAX",
    "FEATURE_NAMES",
    "ID_COLUMNS",
    "INTERACTION_CONTRACT_NAME",
    "INTERACTION_FAMILIES",
    "INTERACTION_SCHEMA_VERSION",
    "PRIMARY_SEASONS",
    "ProcessInteractionError",
    "build_interactions",
    "compute_readiness_payload",
    "feature_distribution_audit",
    "redundancy_audit",
    "required_e1_columns",
]
