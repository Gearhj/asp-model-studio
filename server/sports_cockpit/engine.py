"""Science engine for the interactive MLB PA modeling cockpit.

All computation runs on the real, materialized D3 feature view
(``mlb-pa-feature-view-v1.parquet``) and is evaluated with the frozen
``server.sports_modeling`` metrics authority. Preprocessing is fold-local: every learned
statistic (outlier threshold, imputation fill, standardization moment) is fitted on the
development season only (2023). The frozen final-evaluation season (2025) never
participates in fitting, tuning, or selection.

Performance discipline (Phase 5G lesson): no ``DataFrame.iterrows`` over the population,
no per-row Python loops over the 549k-row frame, no repeated Parquet reloads. The frame is
loaded once and cached; every transform is vectorized NumPy/pandas.
"""

from __future__ import annotations

import glob
import contextvars
import hashlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.feature_selection import mutual_info_classif
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier

from server.sports_modeling.metrics import (
    PA_CLASS_ORDER,
    encode_labels,
    evaluate_multiclass,
)

COCKPIT_SCHEMA_VERSION = "MLB_PA_COCKPIT_V1"

# Information-Value screening threshold (classic WOE/IV convention: >=0.1 is a notable one-vs-rest
# signal, 0.02-0.1 weak, <0.02 negligible). Screening evidence only — never automatic inclusion.
IV_SCREENING_THRESHOLD = 0.1
IV_WEAK_THRESHOLD = 0.02
# Absolute-correlation threshold used to flag strongly collinear predictor pairs (diagnostic only).
CORRELATION_STRONG_THRESHOLD = 0.8

REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_runtime_root() -> Path:
    """The single mutable runtime data root. Defaults to the fixed in-repo ``.runtime/asp-model-studio`` so
    production containment is unchanged. An operator/test may relocate the ENTIRE runtime tree by setting the
    ``ASP_MODEL_STUDIO_RUNTIME_ROOT`` environment variable to an ABSOLUTE path — used ONLY to run the governed
    subprocess/HTTP acceptance batteries and the isolated-root inventory against a temporary throwaway root so
    the shared development ``.runtime`` is never mutated (Gate 14/15/16). This is a process-level DEPLOYMENT
    control, not a request/caller-supplied path: the per-project + object-root containment checks in
    gen3_authority still apply strictly beneath whatever root this resolves, so it introduces no runtime path
    escape. A relative override is rejected (fail-closed)."""
    default_root = REPO_ROOT / ".runtime" / "asp-model-studio"
    require_isolated = os.environ.get("ASP_REQUIRE_ISOLATED_RUNTIME", "").strip().lower() in ("1", "true", "yes")
    override = os.environ.get("ASP_MODEL_STUDIO_RUNTIME_ROOT")
    if override:
        p = Path(override)
        if not p.is_absolute():
            raise ValueError("ASP_MODEL_STUDIO_RUNTIME_ROOT must be an absolute path")
        resolved = p.resolve()
        if require_isolated and resolved == default_root.resolve():
            # the isolated gate MUST NOT be pointed back at the shared development .runtime
            raise ValueError("ASP_REQUIRE_ISOLATED_RUNTIME=1 forbids resolving to the shared development runtime root")
        return resolved
    if require_isolated:
        # fail-closed: the isolated gate demands an explicit throwaway root, never the shared .runtime default
        raise ValueError("ASP_REQUIRE_ISOLATED_RUNTIME=1 requires an explicit ASP_MODEL_STUDIO_RUNTIME_ROOT override")
    return default_root


RUNTIME_ROOT = _resolve_runtime_root()
COCKPIT_ROOT = RUNTIME_ROOT / "sports-cockpit"
FEATURE_VIEW_GLOB = str(
    RUNTIME_ROOT
    / "sports-modeling"
    / "mlb-pa-v1"
    / "objects"
    / "sha256"
    / "**"
    / "mlb-pa-feature-view-v1.parquet"
)

DEV_SEASON = 2023
VAL_SEASON = 2024
FROZEN_SEASON = 2025  # physically SEALED out-of-time evidence — NEVER an ordinary modeling/scoring season

# Phase 7D.5A.1 — EXPLICIT season-role authority (replaces the ambiguous ``TARGET_SEASONS`` name, which read
# like "all target seasons" but meant only the ordinary modeling window). Ordinary cockpit modeling fits on
# DEVELOPMENT and validates on VALIDATION; the frozen 2025 season is sealed evidence and is never an ordinary
# modeling/scoring/selection season. ALL_GOVERNED_SEASONS is the full physical inventory (INCLUDING sealed 2025)
# and must NEVER be used to authorize an ordinary model path — no fallback may substitute it for a missing
# ordinary-season definition.
DEVELOPMENT_SEASONS = (DEV_SEASON,)
VALIDATION_SEASONS = (VAL_SEASON,)
SEALED_EVIDENCE_SEASONS = (FROZEN_SEASON,)
MODELING_SEASONS = (DEV_SEASON, VAL_SEASON)  # ordinary fit + validate window; EXCLUDES sealed 2025
ALL_GOVERNED_SEASONS = (DEV_SEASON, VAL_SEASON, FROZEN_SEASON)  # full physical inventory (incl. sealed)

# Phase 6E.1 — full registered source-evidence authority. Counts and season roles are read from the
# governed FD1 dataset manifest `seasons` block (2021-2022 = PRIOR_ONLY_HISTORY, 2023-2025 =
# PRIMARY_GEN2_MODELING); the modeling-season counts mirror feature_contract.EXPECTED_SEASON_ROWS. The
# feature view materializes only 2023-2025, so 2021-2022 counts are sourced from this frozen authority.
SOURCE_EVIDENCE_SEASONS: tuple[dict[str, Any], ...] = (
    # games / batters / pitchers are DERIVED from the registered source PA partitions (distinct
    # game_id / batter_id / pitcher_id). 2021 has more distinct batters because NL pitchers batted
    # before the 2022 universal DH. These are real counts — never "—" — for the source-history display.
    {"season": 2021, "rows": 181_818, "games": 2_429, "batters": 1_049, "pitchers": 909, "role": "PRIOR_HISTORY"},
    {"season": 2022, "rows": 182_052, "games": 2_430, "batters": 693, "pitchers": 871, "role": "PRIOR_HISTORY"},
    {"season": 2023, "rows": 184_104, "games": 2_430, "batters": 656, "pitchers": 863, "role": "DEVELOPMENT"},
    {"season": 2024, "rows": 182_449, "games": 2_429, "batters": 651, "pitchers": 855, "role": "VALIDATION"},
    {"season": 2025, "rows": 182_926, "games": 2_430, "batters": 673, "pitchers": 873, "role": "FROZEN_FINAL"},
)
REGISTERED_TOTAL_ROWS = 913_349          # 2021-2025 registered PA evidence
PRIOR_HISTORY_TOTAL_ROWS = 363_870       # 2021-2022 prior-only history (181,818 + 182,052)
MODELING_TOTAL_ROWS = 549_479            # 2023-2025 Gen-2 modeling / evaluation matrix

# One-hot categorical context features (mirrors the D3 fold preprocessor authority).
CATEGORICAL_VALUES: Mapping[str, tuple[int, ...]] = {
    "context_top_bottom": (0, 1),
    "context_outs_before": (0, 1, 2),
    "context_base_mask_before": tuple(range(8)),
}

CONTEXT_FEATURES = (
    "context_inning",
    "context_top_bottom",
    "context_outs_before",
    "context_base_mask_before",
    "context_batting_score_diff_before",
)
BATTER_FEATURES = (
    "batter_log1p_pa",
    "batter_avg",
    "batter_obp",
    "batter_slg",
    "batter_so_per_pa",
    "batter_bb_hbp_per_pa",
    "batter_hr_per_pa",
    "batter_prior_missing",
)
PITCHER_FEATURES = (
    "pitcher_log1p_bfp",
    "pitcher_era9",
    "pitcher_whip",
    "pitcher_so_per_bfp",
    "pitcher_bb_per_bfp",
    "pitcher_hr_per_bfp",
    "pitcher_hbp_per_bfp",
    "pitcher_gs_per_g",
    "pitcher_prior_missing",
)
ALL_FEATURES = CONTEXT_FEATURES + BATTER_FEATURES + PITCHER_FEATURES

# Binary indicator features (0/1) — never outlier-treated, no imputation needed.
BINARY_FEATURES = frozenset({"batter_prior_missing", "pitcher_prior_missing"})
# Features eligible for outlier treatment: continuous numerics only.
CONTINUOUS_FEATURES = tuple(
    f for f in ALL_FEATURES if f not in CATEGORICAL_VALUES and f not in BINARY_FEATURES
)

FAMILY_LABELS = {
    "logistic": "Logistic Regression (multinomial)",
    "random_forest": "Random Forest",
    "extra_trees": "Extra Trees",
    "hist_gradient_boosting": "Histogram Gradient Boosting",
    "mlp": "Neural Network (MLP)",
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
}

# Registered D3 champion (candidate C4) frozen evidence, read from the experiment-metrics
# artifact at import so the cockpit displays the governed champion of record. The in-pipeline
# reproduction (``champion_baseline``) is what challengers are compared against numerically.
# Phase 7D.2 Gate 12 — no sealed-2025 metric constant is loaded into an ordinary reference. Only the 2024
# validation reference is carried; the sealed-2025 evidence is restricted archival, never a scientist DTO.
CHAMPION_REFERENCE_FALLBACK = {
    "candidateId": "C4",
    "val2024": {"logLoss": 1.4842548490122627, "brierScore": 0.7067859079863168, "topLabelEce": 0.0117306649436536},
}


class CockpitError(RuntimeError):
    """Fail-closed cockpit error."""


# ----------------------------------------------------------------------------------------
# Frame loading (loaded once, cached)
# ----------------------------------------------------------------------------------------
_FRAME_LOCK = threading.Lock()
_FRAME_CACHE: dict[str, Any] = {}
RESEARCH_REQUEST_SCOPE: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "cockpit_research_request_scope", default=None
)


def _research_cache_scope() -> str:
    scope = RESEARCH_REQUEST_SCOPE.get()
    if scope is None:
        return "internal"  # Offline governed tools have no HTTP response cache.
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()


def _frame_cache_key(key: str) -> str:
    return f"{_research_cache_scope()}:{key}"



# Phase 7C Gate 7/23 — the legacy in-process engine reads the PHYSICALLY SEPARATED Gen-2 RESEARCH object
# (2023 development + 2024 validation only). The combined 2023-2025 object is never opened by any ordinary
# scientist route; the sealed 2025 season is not resident in this frame. The old combined object remains as
# immutable lineage but is retired from the ordinary resolver.
GEN2_RESEARCH_REGISTRATION = (
    RUNTIME_ROOT / "sports-modeling" / "mlb-pa-gen2-v1" / "registration.json"
)


def _feature_view_path() -> Path:
    """Resolve the immutable Gen-2 RESEARCH object (2023-2024) through the ONE verified read boundary
    (Gate 3/4): verified_research_object() resolves the selectable research entry from the canonical registry
    and runs the COMPLETE object verification (containment, physical/logical/schema SHAs, publication
    manifest, embedded identities, contracts, counts, no sealed leak) BEFORE any modeling read. Never the
    combined 2023-2025 object, a sidecar, or a glob."""
    from . import gen3_authority as _G3A  # lazy import avoids the engine<->authority import cycle

    try:
        verified = _G3A.verified_research_object("GEN2")
        scope = RESEARCH_REQUEST_SCOPE.get()
        if scope is not None and any(
            verified.get(field) != scope.get(scope_field)
            for field, scope_field in (
                ("datasetVersionId", "datasetVersionId"),
                ("logicalContentSha256", "datasetContentSha256"),
                ("physicalParquetSha256", "physicalParquetSha256"),
                ("contractBundleSha256", "contractBundleSha256"),
            )
        ):
            raise CockpitError("Project research authority changed before the data read.")
        return verified["path"]
    except _G3A.AuthorityError as exc:
        raise CockpitError(
            f"Gen-2 research object is not resolvable/verifiable through the canonical registry: {exc}. "
            "Run scripts/phase7c_publish_gen2.py and the registry migration."
        )


def load_frame() -> pd.DataFrame:
    """Load the materialized D3 feature view once and cache it (numeric-coerced features)."""
    with _FRAME_LOCK:
        cached = _FRAME_CACHE.get(_frame_cache_key("frame"))
        if cached is not None:
            return cached
        import pyarrow.parquet as pq

        path = _feature_view_path()
        columns = [
            "plate_appearance_id",
            "game_id",
            "game_date",
            "season",
            "outcome",
            "batter_canonical_player_uuid",
            "pitcher_canonical_player_uuid",
            *ALL_FEATURES,
        ]
        table = pq.read_table(path, columns=columns)
        frame = table.to_pandas()
        for col in ALL_FEATURES:
            frame[col] = pd.to_numeric(frame[col], errors="coerce").astype(np.float64)
        frame["season"] = pd.to_numeric(frame["season"], errors="coerce").astype(np.int64)
        # Cache the source content sha for content-addressed profile caching.
        content_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        _FRAME_CACHE[_frame_cache_key("frame")] = frame
        _FRAME_CACHE[_frame_cache_key("path")] = str(path)
        _FRAME_CACHE[_frame_cache_key("content_sha")] = content_sha
        return frame


def data_content_sha() -> str:
    load_frame()
    return _FRAME_CACHE[_frame_cache_key("content_sha")]


def _season_mask(frame: pd.DataFrame, season: int) -> np.ndarray:
    return (frame["season"].to_numpy() == season)


# ----------------------------------------------------------------------------------------
# Feature metadata / kinds
# ----------------------------------------------------------------------------------------
def feature_kind(name: str) -> str:
    if name in CATEGORICAL_VALUES:
        return "categorical"
    if name in BINARY_FEATURES:
        return "binary"
    return "continuous"


def feature_role(name: str) -> str:
    if name in CONTEXT_FEATURES:
        return "context"
    if name in BATTER_FEATURES:
        return "batter"
    return "pitcher"


# ----------------------------------------------------------------------------------------
# Objective + population
# ----------------------------------------------------------------------------------------
CHAMPION_2024_REFERENCE_GLOB = str(
    RUNTIME_ROOT / "sports-modeling" / "champion-2024-reference" / "reference-sha256-*.json")


def _champion_reference() -> dict[str, Any]:
    """Return the C4 champion's 2024-VALIDATION-ONLY reference.

    Phase 7D.5A (Workstream H): the ordinary path NEVER opens the combined legacy metrics artifact (which carries
    a sealed out-of-time section). It reads a 2024-only, content-addressed reference artifact produced by the
    explicit ``scripts/migrate_champion_2024_reference`` migration; if that artifact is absent, it uses the
    documented 2024-only fallback constant. No sealed out-of-time metric is ever opened, read, or exposed."""
    try:
        matches = sorted(glob.glob(CHAMPION_2024_REFERENCE_GLOB))
        if matches:
            payload = json.loads(Path(matches[-1]).read_text(encoding="utf-8"))
            val = payload.get("val2024") or {}
            if val.get("logLoss") is not None:
                return {
                    "candidateId": "C4",
                    "val2024": {"logLoss": val.get("logLoss"), "brierScore": val.get("brierScore"),
                                "topLabelEce": val.get("topLabelEce")},
                    "sealed2025": "RESTRICTED_ARCHIVAL_AUDIT_EVIDENCE",
                }
    except Exception:
        pass
    ref = dict(CHAMPION_REFERENCE_FALLBACK)
    ref.pop("frozen2025", None)
    ref["sealed2025"] = "RESTRICTED_ARCHIVAL_AUDIT_EVIDENCE"
    return ref


def objective_payload() -> dict[str, Any]:
    frame = load_frame()
    total = int(len(frame))
    counts = frame["outcome"].value_counts()
    distribution = [
        {"class": cls, "count": int(counts.get(cls, 0)), "share": float(counts.get(cls, 0) / total)}
        for cls in PA_CLASS_ORDER
    ]
    return {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "objective": "Plate Appearance Outcome",
        "predictionUnit": "PLATE_APPEARANCE",
        "downstreamUse": "WHOLE_GAME_SIMULATOR",
        "classOrder": list(PA_CLASS_ORDER),
        "targetColumn": "outcome",
        "targetDistribution": distribution,
        "totalRows": total,
        "seasons": list(MODELING_SEASONS),
        "champion": {
            "modelId": "D3 (candidate C4)",
            "family": "Logistic Regression (multinomial)",
            "featureCount": len(ALL_FEATURES),
            "reference": _champion_reference(),
            "status": "RESEARCH_CHAMPION",
        },
        "datasetAuthority": {
            "featureView": "MLB_PA_FEATURE_VIEW_V1",
            "manifestSha": "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49",
            "registration": "sports-dataset-1b58d5d1def2c9b7",
        },
        "maturity": "D3_GAME_LEVEL_VALUE_CONFIRMED",
    }


def population_payload() -> dict[str, Any]:
    frame = load_frame()
    per_season = []
    for season in MODELING_SEASONS:
        mask = _season_mask(frame, season)
        sub = frame.loc[mask]
        per_season.append(
            {
                "season": int(season),
                "rows": int(mask.sum()),
                "games": int(sub["game_id"].nunique()),
                "batters": int(sub["batter_canonical_player_uuid"].nunique()) if "batter_canonical_player_uuid" in sub else None,
                "role": "development" if season == DEV_SEASON else "validation" if season == VAL_SEASON else "frozen_final",
            }
        )
    # Population lineage: registered evidence (2021-2025) splits into prior-history (2021-2022, a
    # parallel role — NOT dropped) and the Gen-2 modeling matrix (2023-2025), which narrows to the
    # 2023 development target population. No rows are discarded for quality.
    total = int(len(frame))
    dev_rows = int(_season_mask(frame, DEV_SEASON).sum())
    waterfall = [
        {"stage": "Registered PA evidence (2021-2025)", "rows": REGISTERED_TOTAL_ROWS, "kind": "source"},
        {"stage": "Prior-history evidence (2021-2022)", "rows": PRIOR_HISTORY_TOTAL_ROWS, "kind": "prior"},
        {"stage": "Gen-2 modeling / evaluation matrix (2023-2025)", "rows": MODELING_TOTAL_ROWS, "kind": "retained"},
        {"stage": "Development target population (2023)", "rows": dev_rows, "kind": "final"},
    ]
    return {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "perSeason": per_season,
        "totalRows": total,
        "waterfall": waterfall,
        "candidatePredictors": len(ALL_FEATURES),
        "temporalPolicy": {
            "development": [DEV_SEASON],
            "validation": VAL_SEASON,
            "frozenFinal": FROZEN_SEASON,
        },
        # Phase 6E — explicit source-evidence vs. modeling-development authority. The registered FD1
        # dataset spans 2021-2025, but the manifest temporal contract classifies 2021-2022 as
        # PRIOR_ONLY_HISTORY (Y-1 prior construction only; the prior_only population is contractually
        # prohibited from PRIMARY_2023_2025_TARGET_TRAINING). The PA modeling matrix is 2023-2025.
        "sourceEvidence": {
            "registeredSeasons": [2021, 2022, 2023, 2024, 2025],
            "priorOnlyHistory": [2021, 2022],
            "modelingDevelopment": [DEV_SEASON],
            "validation": VAL_SEASON,
            "frozenFinal": FROZEN_SEASON,
            "registeredTotalRows": REGISTERED_TOTAL_ROWS,
            "priorHistoryTotalRows": PRIOR_HISTORY_TOTAL_ROWS,
            "modelingTotalRows": MODELING_TOTAL_ROWS,
            "perSeason": [dict(row) for row in SOURCE_EVIDENCE_SEASONS],
            "note": (
                "Registered evidence spans 2021-2025. 2021-2022 are PRIOR_ONLY_HISTORY: retained only "
                "to build Y-1 player priors for the 2023-2025 primary modeling seasons and prohibited "
                "from primary target training. 2021 additionally has no eligible <=2020 prior (earliest "
                "registered player_prior source season is 2021), so every 2021 PA would be prior-missing."
            ),
        },
        "knownLimitations": [
            "Source evidence spans 2021-2025, but 2021-2022 are governed PRIOR_ONLY_HISTORY (Y-1 prior "
            "construction only); modeling development is 2023, validation 2024, frozen final 2025.",
            "Prior-season player state is unavailable for debut players (batter 7.7% / pitcher 11.7% missing).",
            "No premium contact-quality, umpire, weather, or park features in the governed free data.",
        ],
    }


# ----------------------------------------------------------------------------------------
# Profiling: stats, IV (one-vs-rest), MI, outliers, drift
# ----------------------------------------------------------------------------------------
def _woe_iv(feature_bins: np.ndarray, event: np.ndarray) -> float:
    """Weight-of-evidence Information Value over integer bin ids for a binary event."""
    total_event = float(event.sum())
    total_nonevent = float(len(event) - total_event)
    if total_event <= 0 or total_nonevent <= 0:
        return 0.0
    iv = 0.0
    for b in np.unique(feature_bins):
        sel = feature_bins == b
        ev = float(event[sel].sum())
        nev = float(sel.sum() - ev)
        p_ev = max(ev / total_event, 1e-6)
        p_nev = max(nev / total_nonevent, 1e-6)
        iv += (p_ev - p_nev) * math.log(p_ev / p_nev)
    return float(iv)


def _dev_bins(values: np.ndarray, kind: str, n_bins: int = 10) -> np.ndarray:
    """Assign development-fitted bin ids (categorical → own categories, continuous → deciles)."""
    if kind in ("categorical", "binary"):
        # each distinct integer value is its own bin; NaN → -1
        out = np.where(np.isfinite(values), values, -1.0)
        return out.astype(np.int64)
    # continuous: qcut on finite dev values; missing → own bin -1
    finite = np.isfinite(values)
    out = np.full(values.shape, -1, dtype=np.int64)
    if finite.sum() > n_bins:
        ranks = pd.Series(values[finite]).rank(method="first")
        try:
            binned = pd.qcut(ranks, min(n_bins, finite.sum()), labels=False, duplicates="drop")
            out[finite] = binned.to_numpy().astype(np.int64)
        except Exception:
            out[finite] = 0
    else:
        out[finite] = 0
    return out


def _feature_iv(dev_values: np.ndarray, dev_labels: np.ndarray, kind: str) -> dict[str, Any]:
    """One-vs-rest IV for each of the 8 classes using development bins."""
    bins = _dev_bins(dev_values, kind)
    per_class = {}
    for idx, cls in enumerate(PA_CLASS_ORDER):
        event = (dev_labels == idx).astype(np.float64)
        per_class[cls] = _woe_iv(bins, event)
    values = list(per_class.values())
    return {
        "perClass": per_class,
        "maxIv": float(max(values)) if values else 0.0,
        "meanIv": float(np.mean(values)) if values else 0.0,
        "maxIvClass": max(per_class, key=per_class.get) if per_class else None,
    }


_PROFILE_CACHE: dict[str, Any] = {}


PROFILE_CACHE_VERSION = "v2"  # bump when the profile payload schema changes (adds/removes fields)


def feature_profile(force: bool = False) -> dict[str, Any]:
    """Profile every candidate predictor. Cached content-addressed to disk + memory."""
    sha = data_content_sha()
    cache_key = f"profile-{_research_cache_scope()}-{PROFILE_CACHE_VERSION}-{sha}"
    if not force and cache_key in _PROFILE_CACHE:
        return _PROFILE_CACHE[cache_key]
    cache_path = COCKPIT_ROOT / "profiles" / _research_cache_scope() / f"{sha}-{PROFILE_CACHE_VERSION}.json"
    if not force and cache_path.is_file():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        _PROFILE_CACHE[cache_key] = payload
        return payload

    frame = load_frame()
    dev_mask = _season_mask(frame, DEV_SEASON)
    dev_labels = encode_labels(frame.loc[dev_mask, "outcome"].to_numpy())
    total = int(len(frame))

    # Bounded MI sample (development evidence only) — KNN MI is O(n log n); cap to keep it fast.
    rng = np.random.default_rng(20260819)
    dev_idx = np.flatnonzero(dev_mask)
    mi_sample = dev_idx if len(dev_idx) <= 30000 else rng.choice(dev_idx, 30000, replace=False)
    mi_matrix = np.column_stack(
        [np.nan_to_num(frame[f].to_numpy()[mi_sample], nan=np.nanmedian(frame[f].to_numpy()[mi_sample])) for f in ALL_FEATURES]
    )
    discrete_mask = [feature_kind(f) != "continuous" for f in ALL_FEATURES]
    mi_labels = encode_labels(frame["outcome"].to_numpy()[mi_sample])
    mi_values = mutual_info_classif(
        mi_matrix,
        mi_labels,
        discrete_features=discrete_mask,
        random_state=20260819,
    )

    features = []
    for pos, name in enumerate(ALL_FEATURES):
        col = frame[name].to_numpy()
        dev_col = col[dev_mask]
        kind = feature_kind(name)
        finite = np.isfinite(col)
        finite_vals = col[finite]
        missing = int((~finite).sum())
        pcts = {}
        if finite_vals.size:
            for p in (1, 5, 25, 50, 75, 95, 99):
                pcts[f"p{p}"] = float(np.percentile(finite_vals, p))
        # IQR outliers on development finite values
        outlier_count = 0
        iqr_bounds = None
        if kind == "continuous" and finite_vals.size:
            q1, q3 = np.percentile(dev_col[np.isfinite(dev_col)], [25, 75]) if np.isfinite(dev_col).any() else (0.0, 0.0)
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            iqr_bounds = {"lower": float(lo), "upper": float(hi)}
            outlier_count = int(((finite_vals < lo) | (finite_vals > hi)).sum())
        # Drift: mean per season
        season_means = {}
        for season in MODELING_SEASONS:
            sc = col[_season_mask(frame, season)]
            scf = sc[np.isfinite(sc)]
            season_means[str(season)] = float(scf.mean()) if scf.size else None
        drift = None
        vals_present = [v for v in season_means.values() if v is not None]
        if len(vals_present) >= 2 and finite_vals.size:
            spread = max(vals_present) - min(vals_present)
            scale = float(np.std(finite_vals)) or 1.0
            drift = float(spread / scale)
        iv = _feature_iv(dev_col, dev_labels, kind)
        features.append(
            {
                "name": name,
                "role": feature_role(name),
                "kind": kind,
                "nonNull": total - missing,
                "missing": missing,
                "missingPct": float(missing / total),
                "unique": int(pd.Series(finite_vals).nunique()) if finite_vals.size else 0,
                "min": float(finite_vals.min()) if finite_vals.size else None,
                "max": float(finite_vals.max()) if finite_vals.size else None,
                "mean": float(finite_vals.mean()) if finite_vals.size else None,
                "median": float(np.median(finite_vals)) if finite_vals.size else None,
                "std": float(finite_vals.std()) if finite_vals.size else None,
                "skew": float(pd.Series(finite_vals).skew()) if finite_vals.size > 2 else None,
                "percentiles": pcts,
                "outlierCount": outlier_count,
                "outlierPct": float(outlier_count / total) if total else 0.0,
                "iqrBounds": iqr_bounds,
                "seasonMeans": season_means,
                "drift": drift,
                "iv": iv,
                "mi": float(mi_values[pos]),
                "outlierTreatable": kind == "continuous",
            }
        )

    payload = {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "dataContentSha": sha,
        "developmentSeason": DEV_SEASON,
        "miSampleRows": int(len(mi_sample)),
        "miEstimator": "sklearn.mutual_info_classif (development-only, bounded sample)",
        "ivMethod": "one-vs-rest WOE over development deciles / categories",
        "ivScreeningThreshold": IV_SCREENING_THRESHOLD,
        "ivWeakThreshold": IV_WEAK_THRESHOLD,
        "totalRows": total,
        "features": features,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    _PROFILE_CACHE[cache_key] = payload
    return payload


def _column_role(name: str) -> str:
    if name == "outcome":
        return "TARGET"
    if name in ("game_date", "season"):
        return "TIME"
    if name == "game_id":
        return "GROUPING"
    if name in ("plate_appearance_id", "batter_canonical_player_uuid", "pitcher_canonical_player_uuid"):
        return "IDENTIFIER"
    if name in ALL_FEATURES:
        return "FEATURE"
    return "EXCLUDED"


# Curated, readable column order for the row preview (identifiers truncated in the UI).
_PREVIEW_COLUMNS = (
    "game_date", "season", "game_id", "batter_canonical_player_uuid", "pitcher_canonical_player_uuid",
    "outcome", "context_inning", "context_outs_before", "context_base_mask_before",
    "batter_avg", "batter_obp", "batter_so_per_pa", "batter_hr_per_pa",
    "pitcher_era9", "pitcher_whip", "pitcher_so_per_bfp",
)


def data_preview(*, season: int | None = None, limit: int = 25, sample: str = "head", seed: int = 20260819) -> dict[str, Any]:
    """Bounded, governed preview of the PA modeling matrix (feature view): schema + real rows +
    target distribution + development/validation/frozen counts. No file paths, no client file access."""
    frame = load_frame()
    limit = int(max(1, min(limit, 50)))
    view = frame if season is None else frame[frame["season"] == int(season)]
    total = int(len(view))

    if sample == "random" and total > limit:
        rows_df = view.sample(limit, random_state=seed)
    else:
        rows_df = view.head(limit)

    def _cell(name: str, v: Any) -> Any:
        if v is None or (isinstance(v, float) and (math.isnan(v))):
            return None
        if name in ("game_id", "plate_appearance_id", "batter_canonical_player_uuid", "pitcher_canonical_player_uuid"):
            return str(v)
        if isinstance(v, float):
            return round(float(v), 4)
        try:
            return int(v) if name in ("season", "context_inning", "context_outs_before", "context_base_mask_before") else (str(v) if not isinstance(v, (int, float)) else v)
        except Exception:
            return str(v)

    preview_cols = [c for c in _PREVIEW_COLUMNS if c in view.columns]
    rows = [{c: _cell(c, r[c]) for c in preview_cols} for _, r in rows_df[preview_cols].iterrows()]

    # schema over the meaningful columns
    schema_cols = ["plate_appearance_id", "game_id", "game_date", "season", "outcome",
                   "batter_canonical_player_uuid", "pitcher_canonical_player_uuid", *ALL_FEATURES]
    schema = []
    numeric = 0
    categorical = 0
    for c in schema_cols:
        if c not in view.columns:
            continue
        col = view[c]
        miss = float(col.isna().mean()) if len(col) else 0.0
        kind = feature_kind(c) if c in ALL_FEATURES else ("string" if col.dtype == object else str(col.dtype))
        role = _column_role(c)
        if role == "FEATURE":
            if feature_kind(c) == "continuous":
                numeric += 1
            else:
                categorical += 1
        nonnull = col.dropna()
        example = _cell(c, nonnull.iloc[0]) if len(nonnull) else None
        schema.append({"name": c, "type": kind, "role": role, "missingPct": miss, "example": example})

    counts = view["outcome"].value_counts()
    target_dist = [{"class": cls, "count": int(counts.get(cls, 0)), "share": float(counts.get(cls, 0) / total) if total else 0.0} for cls in PA_CLASS_ORDER]

    split_counts = []
    for s, role in ((DEV_SEASON, "development"), (VAL_SEASON, "validation"), (FROZEN_SEASON, "frozen_final")):
        split_counts.append({"season": int(s), "role": role, "rows": int((frame["season"] == s).sum())})

    overall_missing = float(view[list(ALL_FEATURES)].isna().to_numpy().mean()) if total else 0.0
    return {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "matrix": "MLB_PA_FEATURE_VIEW_V1",
        "grain": "PLATE_APPEARANCE",
        "totalRows": int(len(frame)),
        "filteredRows": total,
        "columns": len(schema),
        "seasons": sorted(int(x) for x in frame["season"].dropna().unique().tolist()),
        "target": "outcome",
        "targetClassOrder": list(PA_CLASS_ORDER),
        "targetDistribution": target_dist,
        "splitCounts": split_counts,
        "numericFeatureColumns": numeric,
        "categoricalFeatureColumns": categorical,
        "featureMissingPct": overall_missing,
        "sample": "random" if (sample == "random" and total > limit) else "head",
        "limit": limit,
        "season": season,
        "previewColumns": preview_cols,
        "rows": rows,
        "schema": schema,
        "note": "This is the governed plate-appearance modeling matrix (feature view, 2023–2025). Registered source evidence spans 2021–2025, but 2021–2022 are PRIOR_ONLY_HISTORY (used only to build Y−1 priors, not as modeling targets); development is 2023, validation 2024, frozen final 2025.",
    }


def target_analysis() -> dict[str, Any]:
    """Target-variable analysis for the Data Profile EDA: overall + per-modeling-season class
    distribution, imbalance, and summary. Modeling seasons only (2023-2025); 2021-2022 are prior-only
    history and not target rows. Bounded value-counts."""
    frame = load_frame()
    total = int(len(frame))
    counts = frame["outcome"].value_counts()
    overall = [{"class": c, "count": int(counts.get(c, 0)), "share": float(counts.get(c, 0) / total)} for c in PA_CLASS_ORDER]
    per_season = []
    for s in MODELING_SEASONS:
        sub = frame.loc[_season_mask(frame, s), "outcome"]
        n = int(len(sub))
        vc = sub.value_counts()
        per_season.append({
            "season": int(s),
            "rows": n,
            "distribution": [{"class": c, "count": int(vc.get(c, 0)), "share": float(vc.get(c, 0) / n) if n else 0.0} for c in PA_CLASS_ORDER],
        })
    ranked = sorted(overall, key=lambda d: -d["share"])
    dominant = ranked[0]
    rarest = ranked[-1]
    return {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "target": "outcome",
        "problemType": "MULTICLASS_CLASSIFICATION",
        "classCount": len(PA_CLASS_ORDER),
        "classOrder": list(PA_CLASS_ORDER),
        "missing": int(frame["outcome"].isna().sum()),
        "totalRows": total,
        "overall": overall,
        "perSeason": per_season,
        "dominantClass": {"class": dominant["class"], "share": dominant["share"]},
        "rarestClass": {"class": rarest["class"], "share": rarest["share"]},
        "imbalanceRatio": float(dominant["share"] / rarest["share"]) if rarest["share"] > 0 else None,
        "modelingSeasons": list(MODELING_SEASONS),
        "note": "Class distribution over the ordinary modeling target rows (2023 development + 2024 validation). 2025 is sealed out-of-time evidence and is not an ordinary modeling season; 2021-2022 are prior-only history and are not target rows; their raw outcomes live in the Data Warehouse, not the modeling matrix.",
    }


def temporal_split_preview(policy: str = "SEASON_HOLDOUT", boundary_date: str | None = None) -> dict[str, Any]:
    """Concrete fold preview for a chosen temporal policy, with REAL development-fold row counts. Frozen
    2025 is never presented as a tuning/selection fold. Bounded (season/date aggregation only)."""
    frame = load_frame()
    season = frame["season"].to_numpy()
    dates_dev = frame.loc[season == DEV_SEASON, "game_date"]
    dmin, dmax = str(dates_dev.min()), str(dates_dev.max())
    n23 = int((season == DEV_SEASON).sum())
    n24 = int((season == VAL_SEASON).sum())
    n25 = int((season == FROZEN_SEASON).sum())
    pol = (policy or "SEASON_HOLDOUT").upper()
    recommended = {"SEASON_HOLDOUT", "ROLLING_ORIGIN", "EXPANDING_WINDOW"}
    frozen_note = "2025 is the frozen final season — never used for tuning, parameter selection, or model selection."

    if pol == "SEASON_HOLDOUT":
        folds = [{"foldId": "season-holdout", "training": {"seasons": [DEV_SEASON], "rows": n23},
                  "validation": {"season": VAL_SEASON, "rows": n24},
                  "frozen": {"season": FROZEN_SEASON, "rows": n25}}]
    elif pol in ("ROLLING_ORIGIN", "EXPANDING_WINDOW"):
        folds = [
            {"foldId": "fold-1", "training": {"seasons": [DEV_SEASON], "rows": n23}, "validation": {"season": VAL_SEASON, "rows": n24}},
            {"foldId": "frozen-refit", "training": {"seasons": [DEV_SEASON, VAL_SEASON], "rows": n23 + n24},
             "validation": {"season": FROZEN_SEASON, "rows": n25, "role": "FROZEN_EVAL_ONLY"}},
        ]
    elif pol == "DATE_HOLDOUT":
        if boundary_date:
            parsed = pd.to_datetime(boundary_date, errors="coerce")
            if pd.isna(parsed):
                raise CockpitError(f"invalid boundary date: {boundary_date!r} (expected YYYY-MM-DD)")
            lo, hi = pd.to_datetime(dmin), pd.to_datetime(dmax)
            if parsed <= lo or parsed >= hi:
                raise CockpitError(
                    f"boundary date {boundary_date} must fall within the {DEV_SEASON} development window "
                    f"({str(lo)[:10]}..{str(hi)[:10]}) so both sides are non-empty"
                )
            bd = str(parsed.date())
        else:
            bd = str(np.sort(dates_dev.to_numpy())[len(dates_dev) // 2])
        dev_dates = frame["game_date"].to_numpy()
        before = int(((season == DEV_SEASON) & (dev_dates < bd)).sum())
        after = int(((season == DEV_SEASON) & (dev_dates >= bd)).sum())
        folds = [{"foldId": "date-holdout", "boundaryDate": bd,
                  "training": {"season": DEV_SEASON, "dateRange": [dmin, bd], "rows": before},
                  "validation": {"season": DEV_SEASON, "dateRange": [bd, dmax], "rows": after},
                  "frozen": {"season": FROZEN_SEASON, "rows": n25}}]
    elif pol == "RANDOM":
        tr = int(round(n23 * 0.8))
        folds = [{"foldId": "random-80-20", "training": {"season": DEV_SEASON, "rows": tr},
                  "validation": {"season": DEV_SEASON, "rows": n23 - tr}, "researchOnly": True}]
    else:
        raise CockpitError(f"unknown temporal policy: {policy}")

    return {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "policy": pol,
        "recommended": pol in recommended,
        "researchOnly": pol == "RANDOM",
        "eligible": True,
        "devDateRange": [dmin, dmax],
        "folds": folds,
        "frozenNote": frozen_note,
        "matchesGovernedContract": pol == "SEASON_HOLDOUT",
        "leakageStatus": "FROZEN_2025_PROTECTED" if pol != "RANDOM" else "TEMPORAL_ORDER_NOT_PRESERVED",
    }


_CORR_CACHE: dict[str, Any] = {}


def correlation_summary(threshold: float | None = None) -> dict[str, Any]:
    """Development-2023 pairwise |Pearson correlation| across the continuous predictors. Bounded
    (17x17) and cached content-addressed; a diagnostic screen for redundancy, never auto-exclusion.
    Validation (2024) and frozen (2025) rows are not used — this is a development-fold screen."""
    thr = float(CORRELATION_STRONG_THRESHOLD if threshold is None else threshold)
    sha = data_content_sha()
    key = f"corr-{_research_cache_scope()}-{sha}-{thr}"
    if key in _CORR_CACHE:
        return _CORR_CACHE[key]
    frame = load_frame()
    feats = list(CONTINUOUS_FEATURES)
    dev = frame.loc[_season_mask(frame, DEV_SEASON), feats]
    corr = dev.corr()  # pandas handles NaN pairwise; development rows only
    n = len(feats)
    matrix: list[list[float | None]] = []
    for i in range(n):
        row: list[float | None] = []
        for j in range(n):
            v = corr.iat[i, j]
            row.append(None if not (isinstance(v, (int, float)) and math.isfinite(v)) else round(float(v), 4))
        matrix.append(row)
    strongest: dict[str, dict[str, Any]] = {}
    pairs: list[dict[str, Any]] = []
    for i in range(n):
        best_feat, best_r = None, 0.0
        for j in range(n):
            if i == j:
                continue
            v = matrix[i][j]
            if v is None:
                continue
            if abs(v) > abs(best_r):
                best_feat, best_r = feats[j], v
            if j > i and abs(v) >= thr:
                pairs.append({"a": feats[i], "b": feats[j], "r": v})
        strongest[feats[i]] = {"feature": best_feat, "r": round(float(best_r), 4)}
    pairs.sort(key=lambda p: -abs(p["r"]))
    payload = {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "scope": "FOLD_LOCAL_DEVELOPMENT_2023",
        "features": feats,
        "matrix": matrix,
        "threshold": thr,
        "strongPairs": pairs,
        "strongPairCount": len(pairs),
        "strongest": strongest,
    }
    _CORR_CACHE[key] = payload
    return payload


def feature_detail(name: str) -> dict[str, Any]:
    if name not in ALL_FEATURES:
        raise CockpitError(f"unknown feature: {name}")
    frame = load_frame()
    kind = feature_kind(name)
    col = frame[name].to_numpy()
    dev_mask = _season_mask(frame, DEV_SEASON)
    dev_labels = encode_labels(frame.loc[dev_mask, "outcome"].to_numpy())
    finite = np.isfinite(col)
    vals = col[finite]

    # Histogram (bounded to 30 bins), plus per-season histogram for YoY drift
    hist = []
    yoy = {}
    if vals.size:
        lo, hi = float(np.percentile(vals, 0.5)), float(np.percentile(vals, 99.5))
        if hi <= lo:
            hi = lo + 1.0
        edges = np.linspace(lo, hi, 31)
        counts, _ = np.histogram(np.clip(vals, lo, hi), bins=edges)
        hist = [
            {"lo": float(edges[i]), "hi": float(edges[i + 1]), "count": int(counts[i])}
            for i in range(len(counts))
        ]
        for season in MODELING_SEASONS:
            sc = col[_season_mask(frame, season)]
            scf = sc[np.isfinite(sc)]
            c, _ = np.histogram(np.clip(scf, lo, hi), bins=edges) if scf.size else (np.zeros(30), None)
            yoy[str(season)] = c.astype(int).tolist()

    # Box stats
    box = None
    if vals.size:
        q1, med, q3 = np.percentile(vals, [25, 50, 75])
        iqr = q3 - q1
        box = {
            "min": float(vals.min()),
            "q1": float(q1),
            "median": float(med),
            "q3": float(q3),
            "max": float(vals.max()),
            "whiskerLo": float(max(vals.min(), q1 - 1.5 * iqr)),
            "whiskerHi": float(min(vals.max(), q3 + 1.5 * iqr)),
        }

    # Target-conditioned means: mean feature value within each outcome class (dev)
    conditioned = []
    dev_col = col[dev_mask]
    for idx, cls in enumerate(PA_CLASS_ORDER):
        sel = (dev_labels == idx) & np.isfinite(dev_col)
        conditioned.append(
            {"class": cls, "mean": float(dev_col[sel].mean()) if sel.any() else None, "count": int(sel.sum())}
        )

    # IV bins with event rate for the max-IV class
    iv = _feature_iv(dev_col, dev_labels, kind)
    max_class = iv["maxIvClass"]
    iv_bins = []
    if max_class is not None:
        cls_idx = PA_CLASS_ORDER.index(max_class)
        bins = _dev_bins(dev_col, kind)
        event = (dev_labels == cls_idx).astype(np.float64)
        for b in np.unique(bins):
            sel = bins == b
            iv_bins.append(
                {
                    "bin": int(b),
                    "count": int(sel.sum()),
                    "eventRate": float(event[sel].mean()) if sel.any() else 0.0,
                }
            )

    return {
        "schemaVersion": COCKPIT_SCHEMA_VERSION,
        "name": name,
        "kind": kind,
        "role": feature_role(name),
        "histogram": hist,
        "yoyHistogram": yoy,
        "box": box,
        "targetConditioned": conditioned,
        "iv": iv,
        "ivBinsMaxClass": max_class,
        "ivBins": iv_bins,
        "missing": int((~finite).sum()),
        "missingPct": float((~finite).sum() / len(col)),
    }
