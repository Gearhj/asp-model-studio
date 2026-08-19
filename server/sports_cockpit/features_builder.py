"""Real user-created experiment features: arithmetic, ratio, interaction, log, power, bin,
indicator, and temporally-safe sports calendar features.

Feature specs serialize into the experiment configuration. Every engineered column is derived
only from information known before the plate appearance (prior-player-state inputs or the game
date), so no target/future leakage is introduced. Materialization is vectorized on the cached
frame — no per-row Python loops.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from . import engine as E
from .engine import ALL_FEATURES, CockpitError, load_frame

FEATURE_KINDS = ("arithmetic", "ratio", "interaction", "log", "power", "bin", "indicator", "calendar")
CALENDAR_SUBKINDS = ("month", "day_of_week", "week_of_year", "days_since_season_start")
# Honestly unavailable in the governed free data (no schedule/All-Star authority in the feature view).
CALENDAR_UNAVAILABLE = ("pre_all_star_break", "post_all_star_break", "postseason", "postseason_round", "series_game_number", "doubleheader")


def _safe_div(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    out = np.full_like(a, np.nan, dtype=np.float64)
    ok = np.isfinite(a) & np.isfinite(b) & (b != 0)
    out[ok] = a[ok] / b[ok]
    return out


def _calendar_column(frame: pd.DataFrame, sub: str) -> np.ndarray:
    dates = pd.to_datetime(frame["game_date"], errors="coerce")
    if sub == "month":
        return dates.dt.month.to_numpy(dtype=np.float64)
    if sub == "day_of_week":
        return dates.dt.dayofweek.to_numpy(dtype=np.float64)
    if sub == "week_of_year":
        return dates.dt.isocalendar().week.to_numpy(dtype=np.float64)
    if sub == "days_since_season_start":
        season_start = frame.assign(_d=dates).groupby("season")["_d"].transform("min")
        return (dates - season_start).dt.days.to_numpy(dtype=np.float64)
    raise CockpitError(f"unknown calendar subkind: {sub}")


def materialize(frame: pd.DataFrame, spec: Mapping[str, Any], dev_mask: np.ndarray | None = None) -> np.ndarray:
    kind = spec.get("kind")
    inputs = spec.get("inputs", [])
    params = spec.get("params", {})

    def col(name: str) -> np.ndarray:
        if name not in frame.columns:
            raise CockpitError(f"input feature not available: {name}")
        return frame[name].to_numpy(dtype=np.float64)

    if kind == "calendar":
        return _calendar_column(frame, params.get("subkind", "month"))
    if kind in ("arithmetic", "ratio", "interaction"):
        if len(inputs) != 2:
            raise CockpitError(f"{kind} requires exactly two inputs")
        a, b = col(inputs[0]), col(inputs[1])
        if kind == "ratio":
            return _safe_div(a, b)
        if kind == "interaction":
            return a * b
        op = params.get("op", "add")
        if op == "add":
            return a + b
        if op in ("sub", "subtract"):
            return a - b
        if op in ("mul", "multiply"):
            return a * b
        if op in ("div", "divide"):
            return _safe_div(a, b)
        raise CockpitError(f"unknown arithmetic op: {op}")
    if kind in ("log", "power", "bin", "indicator"):
        if len(inputs) != 1:
            raise CockpitError(f"{kind} requires exactly one input")
        a = col(inputs[0])
        if kind == "log":
            return np.log1p(np.clip(a, 0, None))
        if kind == "power":
            return np.power(a, float(params.get("exponent", 2.0)))
        if kind == "indicator":
            return (a > float(params.get("threshold", 0.0))).astype(np.float64)
        if kind == "bin":
            k = int(params.get("bins", 5))
            fit = a if dev_mask is None else a[dev_mask]
            finite = fit[np.isfinite(fit)]
            if finite.size <= k:
                return np.zeros_like(a)
            edges = np.quantile(finite, np.linspace(0, 1, k + 1)[1:-1])
            return np.digitize(a, edges).astype(np.float64)
    raise CockpitError(f"unknown feature kind: {kind}")


def apply_engineered(frame: pd.DataFrame, specs: Sequence[Mapping[str, Any]]) -> tuple[pd.DataFrame, list[str]]:
    """Return a frame copy with engineered columns added (fit-independent columns) + their names."""
    if not specs:
        return frame, []
    out = frame.copy()
    dev_mask = frame["season"].to_numpy() == E.DEV_SEASON
    names: list[str] = []
    for spec in specs:
        name = spec.get("name")
        if not name:
            raise CockpitError("engineered feature requires a name")
        if name in ALL_FEATURES:
            raise CockpitError(f"engineered feature name collides with a base feature: {name}")
        out[name] = materialize(frame, spec, dev_mask)
        names.append(name)
    return out, names


def profile_engineered(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Profile a candidate engineered feature: distribution, missing, IV, MI, drift, sim-availability."""
    from server.sports_modeling.metrics import encode_labels
    from sklearn.feature_selection import mutual_info_classif

    frame = load_frame()
    col = materialize(frame, spec, frame["season"].to_numpy() == E.DEV_SEASON)
    dev_mask = frame["season"].to_numpy() == E.DEV_SEASON
    dev_labels = encode_labels(frame.loc[dev_mask, "outcome"].to_numpy())
    finite = np.isfinite(col)
    vals = col[finite]
    kind = "continuous" if spec.get("kind") not in ("bin", "indicator") and spec.get("params", {}).get("subkind") not in ("month", "day_of_week") else "categorical"
    iv = E._feature_iv(col[dev_mask], dev_labels, kind)
    # bounded MI
    rng = np.random.default_rng(20260819)
    dev_idx = np.flatnonzero(dev_mask)
    samp = dev_idx if len(dev_idx) <= 20000 else rng.choice(dev_idx, 20000, replace=False)
    x = np.nan_to_num(col[samp], nan=float(np.nanmedian(vals)) if vals.size else 0.0)
    mi = float(mutual_info_classif(x.reshape(-1, 1), encode_labels(frame["outcome"].to_numpy()[samp]),
                                   discrete_features=[kind == "categorical"], random_state=20260819)[0])
    season_means = {}
    for s in E.TARGET_SEASONS:
        sc = col[frame["season"].to_numpy() == s]
        scf = sc[np.isfinite(sc)]
        season_means[str(s)] = float(scf.mean()) if scf.size else None
    present = [v for v in season_means.values() if v is not None]
    drift = float((max(present) - min(present)) / (np.std(vals) or 1.0)) if len(present) >= 2 and vals.size else None
    return {
        "name": spec.get("name"),
        "kind": spec.get("kind"),
        "simulatorAvailability": _sim_availability(spec),
        "missing": int((~finite).sum()),
        "missingPct": float((~finite).sum() / len(col)),
        "mean": float(vals.mean()) if vals.size else None,
        "std": float(vals.std()) if vals.size else None,
        "min": float(vals.min()) if vals.size else None,
        "max": float(vals.max()) if vals.size else None,
        "iv": iv,
        "mi": mi,
        "seasonMeans": season_means,
        "drift": drift,
        "sampleValues": [float(v) for v in vals[:8]],
    }


def _sim_availability(spec: Mapping[str, Any]) -> str:
    """Engineered features are known pre-game but break the linear additive-logit decomposition
    (interactions) or are not wired into the whole-game fold context (calendar), so they are
    honestly marked QUICK-only for the full simulator."""
    kind = spec.get("kind")
    if kind == "calendar":
        return "STATIC_PRE_GAME (quick-sim only; not yet in full-sim game context)"
    if kind == "interaction" or (kind == "arithmetic" and spec.get("params", {}).get("op") in ("mul", "multiply", "div", "divide")):
        return "PRIOR_PLAYER_STATE (breaks linear decomposition; quick-sim only)"
    return "DERIVED (quick-sim only)"
