"""Reproducible, bounded NFL/CFB/NBA readiness and feature-block audit.

Reads only the hash-bound, pre-2026 permitted projections declared in
docs/nfl-cfb-nba-feature-readiness-v1/STUDY_DESIGN.json. Outputs contain only
aggregate summaries, model metrics, and static figures; no row-level evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import warnings
from pathlib import Path
import sys
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.impute import SimpleImputer
from sklearn.base import clone
from sklearn.linear_model import Ridge
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_cfb_gen1.pipeline import FEATURE_COLUMNS as CFB_FEATURES
from server.sports_nba_gen1.rest_support import feature_contract
from server.sports_nfl.gold import GAME_FEATURES as NFL_FEATURES
from server.sports_nfl_m1.contracts import XGBOOST_SCORE_CONFIG
from server.sports_nfl_m1.models import IndependentHomeAwayScoreModel


DOC = ROOT / "docs" / "nfl-cfb-nba-feature-readiness-v1"
DESIGN_PATH = DOC / "STUDY_DESIGN.json"
DEFAULT_INPUT = Path(r"C:\Users\james\asp-model-studio\outputs\multisport-feature-engineering-audit-v1\permitted-input-projections")
SEED = 9172601
META = {
    "NFL": {"game_id", "game_date", "home_team", "away_team", "home_score", "away_score", "game_state", "governed_population", "audit_season"},
    "CFB": {"game_id", "game_date", "home_team", "away_team", "home_margin", "total_points", "home_score", "away_score", "primary", "is_final", "feature_max_source_game_date", "audit_season"},
    "NBA": {"game_id", "game_date", "home_team", "away_team", "home_score", "away_score", "history_latest_game_date", "target_eligible", "neutral_site", "audit_season"},
}
FEATURES = {"NFL": list(NFL_FEATURES), "CFB": list(CFB_FEATURES), "NBA": list(feature_contract()["numericFeatures"])}


def canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, np.ndarray):
        return canonical(value.tolist())
    if isinstance(value, np.generic):
        return canonical(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(canonical(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_bound(input_dir: Path) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    frames: dict[str, pd.DataFrame] = {}
    receipt: dict[str, Any] = {"identity": "NFL_CFB_NBA_BOUND_INPUT_RECEIPT_V1", "files": {}}
    for sport in ("NFL", "CFB", "NBA"):
        path = input_dir / f"{sport}.parquet"
        expected = design["inputs"][sport]
        actual = sha256(path)
        if actual != expected["sha256"]:
            raise ValueError(f"{sport} input digest mismatch: {actual}")
        schema = pq.read_schema(path).names
        forbidden = [c for c in schema if "2026" in c.lower() or "sealed" in c.lower() or "final_oot" in c.lower()]
        if forbidden:
            raise ValueError(f"{sport} forbidden columns: {forbidden}")
        frame = pq.read_table(path).to_pandas()
        if len(frame) != expected["rows"]:
            raise ValueError(f"{sport} row-count mismatch")
        if frame["audit_season"].max() > expected["maxAuditSeason"]:
            raise ValueError(f"{sport} season exceeds design")
        date = pd.to_datetime(frame["game_date"], utc=True, errors="raise")
        if not date.lt(pd.Timestamp(design["calendarCutoffExclusiveUtc"])).all():
            raise ValueError(f"{sport} has ineligible calendar-2026 row")
        if frame["game_id"].astype(str).duplicated().any():
            raise ValueError(f"{sport} duplicate game identity")
        missing_cols = sorted(set(FEATURES[sport]) - set(frame.columns))
        if missing_cols:
            raise ValueError(f"{sport} missing contract features: {missing_cols}")
        if sport == "CFB":
            src = pd.to_datetime(frame["feature_max_source_game_date"], utc=True, errors="coerce")
            if not (src.isna() | src.lt(date)).all():
                raise ValueError("CFB post-cutoff source evidence")
        if sport == "NBA":
            src = pd.to_datetime(frame["history_latest_game_date"], utc=True, errors="coerce")
            if not (src.isna() | src.lt(date)).all():
                raise ValueError("NBA post-cutoff source evidence")
        frames[sport] = frame.sort_values(["game_date", "game_id"]).reset_index(drop=True)
        receipt["files"][sport] = {
            "path": str(path), "sha256": actual, "bytes": path.stat().st_size,
            "rows": len(frame), "columns": len(frame.columns), "minDate": str(date.min()), "maxDate": str(date.max()),
            "minSeason": int(frame.audit_season.min()), "maxSeason": int(frame.audit_season.max()),
        }
    return frames, receipt


def feature_family(sport: str, name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("rest", "short_week", "bye", "back_to_back", "games_last_", "long_gap")):
        return "REST_SCHEDULE"
    if "elo" in n:
        return "TEAM_STRENGTH_ELO"
    if "epa" in n:
        return "EPA"
    if "explosive" in n:
        return "EXPLOSIVENESS"
    if any(k in n for k in ("success", "conversion", "red_zone")):
        return "SUCCESS_DOWN_DISTANCE"
    if any(k in n for k in ("yards", "rebound", "turnover", "takeaway", "sack", "penalty")):
        return "EFFICIENCY_EVENT"
    if any(k in n for k in ("std", "variability")):
        return "VARIABILITY"
    if any(k in n for k in ("prior", "fallback")):
        return "PRIOR_COLD_START"
    if any(k in n for k in ("supported", "games", "weight", "missing", "early_season")):
        return "SUPPORT_MISSINGNESS"
    if any(k in n for k in ("points", "margin", "total")):
        return "SCORING"
    return "CONTEXT"


def missingness_type(name: str) -> str:
    n = name.lower()
    if "source_era_missing" in n:
        return "SOURCE_ERA"
    if any(k in n for k in ("rest_known", "supported", "fallback_available", "history_supported")):
        return "STRUCTURAL_SUPPORT_SIGNAL"
    if any(k in n for k in ("prior_", "season_games", "prior_games", "rolling_games", "current_season_games")):
        return "NOT_YET_OBSERVED_OR_COLD_START"
    return "SOURCE_OR_IDENTITY_UNRESOLVED"


def role_for(sport: str, season: int, design: dict[str, Any]) -> str:
    if season in design["roles"]["Development"][sport]:
        return "Development"
    if season in design["roles"]["ReusedLaterDiagnostic"][sport]:
        return "ReusedLaterDiagnostic"
    return "EarlierTrainingHistory"


def psi(a: pd.Series, b: pd.Series, bins: int = 10) -> float | None:
    av = pd.to_numeric(a, errors="coerce").dropna().to_numpy(float)
    bv = pd.to_numeric(b, errors="coerce").dropna().to_numpy(float)
    if len(av) < 20 or len(bv) < 20 or np.nanstd(av) == 0:
        return None
    edges = np.unique(np.quantile(av, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return None
    edges[0], edges[-1] = -np.inf, np.inf
    pa = np.histogram(av, bins=edges)[0] / len(av)
    pb = np.histogram(bv, bins=edges)[0] / len(bv)
    pa, pb = np.clip(pa, 1e-6, None), np.clip(pb, 1e-6, None)
    return float(np.sum((pb - pa) * np.log(pb / pa)))


def quality_and_registry(frames: dict[str, pd.DataFrame], design: dict[str, Any]) -> tuple[dict, dict, dict]:
    quality: dict[str, Any] = {}
    registry: dict[str, Any] = {}
    missing_plan: dict[str, Any] = {}
    for sport, f in frames.items():
        seasons = sorted(int(x) for x in f.audit_season.unique())
        features = FEATURES[sport]
        per_season = []
        for season in seasons:
            z = f[f.audit_season == season]
            if sport == "NFL": support = np.minimum(pd.to_numeric(z.home_prior_games), pd.to_numeric(z.away_prior_games))
            elif sport == "CFB": support = np.minimum(pd.to_numeric(z.home_current_season_games), pd.to_numeric(z.away_current_season_games))
            else: support = np.minimum(pd.to_numeric(z.home_season_games_played), pd.to_numeric(z.away_season_games_played))
            per_season.append({
                "season": season, "role": role_for(sport, season, design), "games": len(z),
                "dates": [str(pd.to_datetime(z.game_date, utc=True).min()), str(pd.to_datetime(z.game_date, utc=True).max())],
                "teams": int(pd.concat([z.home_team.astype(str), z.away_team.astype(str)]).nunique()),
                "featureMissingCells": int(z[features].isna().sum().sum()),
                "featureMissingRate": float(z[features].isna().to_numpy().mean()),
                "lowSupportGamesLt5": int((support < 5).sum()), "lowSupportRateLt5": float((support < 5).mean()),
            })
        dev_seasons = design["roles"]["Development"][sport]
        later_seasons = design["roles"]["ReusedLaterDiagnostic"][sport]
        dev, later = f[f.audit_season.isin(dev_seasons)], f[f.audit_season.isin(later_seasons)]
        feature_rows = []
        for name in features:
            x = pd.to_numeric(f[name], errors="coerce")
            miss = int(x.isna().sum())
            drift = psi(dev[name], later[name]) if len(dev) and len(later) else None
            rate_like = any(k in name.lower() for k in ("rate", "probability", "weight"))
            nonnegative_count = not name.lower().startswith("difference_") and any(k in name.lower() for k in ("games", "days", "week"))
            impossible = int(((x < 0) | (x > 1)).sum()) if rate_like else int((x < 0).sum()) if nonnegative_count else 0
            margin = pd.to_numeric(f.home_score, errors="coerce") - pd.to_numeric(f.away_score, errors="coerce")
            total = pd.to_numeric(f.home_score, errors="coerce") + pd.to_numeric(f.away_score, errors="coerce")
            corr_margin = float(x.corr(margin)) if x.notna().sum() > 2 and x.nunique(dropna=True) > 1 else None
            corr_total = float(x.corr(total)) if x.notna().sum() > 2 and x.nunique(dropna=True) > 1 else None
            feature_rows.append({
                "name": name, "family": feature_family(sport, name), "dtype": str(f[name].dtype),
                "missing": miss, "missingRate": float(miss / len(f)), "distinct": int(f[name].nunique(dropna=True)),
                "min": float(x.min()) if x.notna().any() else None, "median": float(x.median()) if x.notna().any() else None,
                "max": float(x.max()) if x.notna().any() else None, "developmentToLaterPsi": drift,
                "impossibleValueCount": impossible,
                "correlationHomeMargin": corr_margin, "correlationTotal": corr_total,
                "maxAbsTargetCorrelation": max(abs(corr_margin or 0), abs(corr_total or 0)),
            })
        home = pd.to_numeric(f.home_score, errors="coerce")
        away = pd.to_numeric(f.away_score, errors="coerce")
        team_missing = []
        for team in sorted(set(f.home_team.astype(str)) | set(f.away_team.astype(str))):
            h = f.home_team.astype(str).eq(team)
            a = f.away_team.astype(str).eq(team)
            values = pd.concat([f.loc[h, [x for x in features if x.startswith("home_")]].rename(columns=lambda x: x.replace("home_", "", 1)),
                                f.loc[a, [x for x in features if x.startswith("away_")]].rename(columns=lambda x: x.replace("away_", "", 1))], ignore_index=True)
            team_missing.append({"team": team, "games": int(h.sum() + a.sum()), "missingRate": float(values.isna().to_numpy().mean()) if values.size else None})
        entrant_counts = []
        prior: set[str] = set()
        for season in seasons:
            z = f[f.audit_season == season]
            current = set(z.home_team.astype(str)) | set(z.away_team.astype(str))
            entrant_counts.append({"season": season, "teams": len(current), "newVsPriorObservedSeason": len(current-prior) if prior else None, "departedVsPriorObservedSeason": len(prior-current) if prior else None})
            prior = current
        quality[sport] = {
            "games": len(f), "seasons": per_season, "features": len(features), "duplicateGameIds": int(f.game_id.duplicated().sum()),
            "missingTargetRows": int(f[["home_score", "away_score"]].isna().any(axis=1).sum()),
            "featureMissingCells": int(f[features].isna().sum().sum()),
            "topMissingFeatures": sorted(feature_rows, key=lambda r: (-r["missingRate"], r["name"]))[:15],
            "topDriftFeatures": sorted([r for r in feature_rows if r["developmentToLaterPsi"] is not None], key=lambda r: -r["developmentToLaterPsi"])[:15],
            "topTargetAssociations": sorted(feature_rows, key=lambda r: -r["maxAbsTargetCorrelation"])[:15],
            "impossibleValueCount": int(sum(r["impossibleValueCount"] for r in feature_rows)),
            "targets": {
                "homeMean": float(home.mean()), "awayMean": float(away.mean()), "marginMean": float((home-away).mean()), "totalMean": float((home+away).mean()),
                "homeWinRate": float((home>away).mean()), "awayWinRate": float((away>home).mean()), "tieRate": float((home==away).mean()), "ties": int((home==away).sum()),
                "scoreQuantiles": {str(q): [float(home.quantile(q)), float(away.quantile(q))] for q in (.01,.5,.99)},
                "overtimeIdentification": "UNAVAILABLE_IN_BOUND_PROJECTION",
            },
            "topTeamMissingness": sorted(team_missing, key=lambda x: (-(x["missingRate"] or 0), x["team"]))[:15],
            "teamIdentityBySeason": entrant_counts,
        }
        registry[sport] = [{
            **r,
            "availability": "pregame reconstructed from earlier finalized games; original source vintage uncertified",
            "lineage": "hash-bound permitted-input projection from multisport-feature-engineering-audit-v1",
            "leakageRisk": "MEDIUM" if any(k in r["name"].lower() for k in ("current", "rolling", "season")) else "LOW",
            "missingnessType": missingness_type(r["name"]) if r["missing"] else "NONE_OBSERVED",
            "imputation": "fold-local training median with explicit indicator when missing",
            "coldStart": "explicit support-aware block" if r["family"] in ("PRIOR_COLD_START", "SUPPORT_MISSINGNESS", "SCORING") else "unchanged",
            "productionReadiness": "HISTORICAL_RESEARCH_ONLY",
        } for r in feature_rows]
        missing_plan[sport] = {
            "taxonomy": ["STRUCTURAL", "SOURCE_ERA", "NOT_YET_OBSERVED", "IDENTITY_UNMATCHED", "ANOMALOUS"],
            "hierarchy": ["team-season earlier evidence", "prior-season team evidence", "training-league median"],
            "genericZeroFill": False,
            "indicatorRequired": True,
            "coldStart": {"thresholdGames": 5, "priorStrengthGames": 5, "weight": "n/(n+5)"},
            "observedMissingFeatures": [r["name"] for r in feature_rows if r["missing"]],
        }
    return quality, registry, missing_plan


def missing_indicators(train: pd.DataFrame, test: pd.DataFrame, base: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    names = [n for n in base if train[n].isna().any() or test[n].isna().any()]
    out = [f"audit_missing__{n}" for n in names]
    a = pd.concat([train.copy(), pd.DataFrame({f"audit_missing__{n}": train[n].isna().astype(float) for n in names}, index=train.index)], axis=1)
    b = pd.concat([test.copy(), pd.DataFrame({f"audit_missing__{n}": test[n].isna().astype(float) for n in names}, index=test.index)], axis=1)
    return a, b, out


def cold_start_features(sport: str, train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    a, b = train.copy(), test.copy()
    if sport == "NFL":
        hs, aws = "home_prior_games", "away_prior_games"
        pairs = [
            ("points_for_season_to_date", "points_for_last_16"),
            ("points_against_season_to_date", "points_against_last_16"),
            ("offensive_epa_per_play_season_to_date", "offensive_epa_per_play_last_16"),
            ("defensive_epa_per_play_season_to_date", "defensive_epa_per_play_last_16"),
        ]
    elif sport == "CFB":
        hs, aws = "home_current_season_games", "away_current_season_games"
        pairs = []
    else:
        hs, aws = "home_season_games_played", "away_season_games_played"
        pairs = [("points_for", "prior_points_for"), ("points_allowed", "prior_points_allowed"), ("rolling_points_for", "prior_points_for"), ("rolling_points_allowed", "prior_points_allowed")]
    out = ["audit_min_support", "audit_low_support"]
    for z in (a, b):
        z["audit_min_support"] = np.minimum(pd.to_numeric(z[hs], errors="coerce"), pd.to_numeric(z[aws], errors="coerce"))
        z["audit_low_support"] = (z["audit_min_support"] < 5).astype(float)
        for side, support in (("home", hs), ("away", aws)):
            w = pd.to_numeric(z[support], errors="coerce").fillna(0).clip(lower=0) / (pd.to_numeric(z[support], errors="coerce").fillna(0).clip(lower=0) + 5.0)
            if sport == "CFB":
                prior_margin = pd.to_numeric(z[f"{side}_prior_margin_shrunk"], errors="coerce")
                prior_total = pd.to_numeric(z[f"{side}_prior_total_shrunk"], errors="coerce")
                for current, prior in (
                    ("points_for_season", (prior_total + prior_margin) / 2),
                    ("points_allowed_season", (prior_total - prior_margin) / 2),
                ):
                    name = f"audit_shrunk__{side}_{current}"
                    z[name] = w * pd.to_numeric(z[f"{side}_{current}"], errors="coerce") + (1 - w) * prior
                    if name not in out:
                        out.append(name)
            for current, prior in pairs:
                c, p = f"{side}_{current}", f"{side}_{prior}"
                if c in z and p in z:
                    name = f"audit_shrunk__{side}_{current}"
                    z[name] = w * pd.to_numeric(z[c], errors="coerce") + (1 - w) * pd.to_numeric(z[p], errors="coerce")
                    if name not in out:
                        out.append(name)
    return a, b, out


def context_features(sport: str, train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    a, b = train.copy(), test.copy()
    mapping: list[tuple[str, str, str]] = []
    if sport == "NFL":
        for window in ("season_to_date", "last_4", "last_8", "last_16"):
            mapping += [
                (f"audit_matchup_home_pass_{window}", f"home_pass_epa_per_play_{window}", f"away_defensive_pass_epa_per_play_{window}"),
                (f"audit_matchup_away_pass_{window}", f"away_pass_epa_per_play_{window}", f"home_defensive_pass_epa_per_play_{window}"),
                (f"audit_matchup_home_rush_{window}", f"home_rush_epa_per_play_{window}", f"away_defensive_rush_epa_per_play_{window}"),
                (f"audit_matchup_away_rush_{window}", f"away_rush_epa_per_play_{window}", f"home_defensive_rush_epa_per_play_{window}"),
            ]
    elif sport == "CFB":
        mapping = [
            ("audit_home_scoring_matchup", "home_points_for_season", "away_points_allowed_season"),
            ("audit_away_scoring_matchup", "away_points_for_season", "home_points_allowed_season"),
            ("audit_home_yardage_matchup", "home_total_yards_season", "away_yards_allowed_season"),
            ("audit_away_yardage_matchup", "away_total_yards_season", "home_yards_allowed_season"),
        ]
    else:
        mapping = [
            ("audit_rest_support_interaction", "difference_rest_days", "difference_games_last_7_days"),
            ("audit_home_density_b2b", "home_games_last_7_days", "home_back_to_back"),
            ("audit_away_density_b2b", "away_games_last_7_days", "away_back_to_back"),
            ("audit_elo_density_interaction", "difference_elo", "difference_games_last_7_days"),
        ]
    out = []
    for z in (a, b):
        for name, left, right in mapping:
            if left in z and right in z:
                lv, rv = pd.to_numeric(z[left], errors="coerce"), pd.to_numeric(z[right], errors="coerce")
                if sport == "NBA":
                    z[name] = lv * rv
                else:
                    z[name] = lv - rv
                if name not in out:
                    out.append(name)
    return a, b, out


def candidate_frames(sport: str, candidate: str, train: pd.DataFrame, test: pd.DataFrame, base: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    a, b, cols = train.copy(), test.copy(), list(base)
    if candidate in ("MISSINGNESS", "COMBINED"):
        a, b, add = missing_indicators(a, b, base); cols += add
    if candidate in ("COLD_START", "COMBINED"):
        a, b, add = cold_start_features(sport, a, b); cols += [x for x in add if x not in cols]
    context_name = {"NFL": "OPPONENT_ADJUSTED_EPA", "CFB": "OPPONENT_SCHEDULE_ADJUSTED", "NBA": "REST_DENSITY_INTERACTIONS"}[sport]
    if candidate in (context_name, "COMBINED"):
        a, b, add = context_features(sport, a, b); cols += [x for x in add if x not in cols]
    return a, b, cols


def fit_predict(sport: str, train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> tuple[np.ndarray, np.ndarray | None]:
    if sport == "NFL":
        model = IndependentHomeAwayScoreModel(XGBOOST_SCORE_CONFIG, tuple(cols), seed=731001).fit(
            train[cols], train.home_score, train.away_score, training_row_ids=train.game_id
        )
        pred = model.predict(test[cols])
        return np.column_stack((pred.expected_home_points, pred.expected_away_points)), np.asarray(pred.home_win_probability)
    pipe = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("ridge", Ridge(alpha=100.0))])
    margin = (train.home_score - train.away_score).to_numpy(float)
    total = (train.home_score + train.away_score).to_numpy(float)
    mm = clone(pipe).fit(train[cols], margin)
    tm = clone(pipe).fit(train[cols], total)
    mg, tt = mm.predict(test[cols]), tm.predict(test[cols])
    scores = np.column_stack(((tt + mg) / 2, (tt - mg) / 2))
    return scores, test["elo_home_win_probability"].to_numpy(float) if sport == "NBA" else None


def row_errors(actual: np.ndarray, pred: np.ndarray) -> dict[str, np.ndarray]:
    ah, aa = actual[:, 0], actual[:, 1]
    ph, pa = pred[:, 0], pred[:, 1]
    return {
        "homeMAE": np.abs(ph - ah), "awayMAE": np.abs(pa - aa),
        "scoreMAE": (np.abs(ph - ah) + np.abs(pa - aa)) / 2,
        "marginMAE": np.abs((ph - pa) - (ah - aa)), "totalMAE": np.abs((ph + pa) - (ah + aa)),
    }


def probability_metrics(actual: np.ndarray, p: np.ndarray | None) -> dict[str, Any] | None:
    if p is None:
        return None
    mask = actual[:, 0] != actual[:, 1]
    y = (actual[mask, 0] > actual[mask, 1]).astype(int)
    q = np.clip(np.asarray(p)[mask], 1e-9, 1 - 1e-9)
    bins = np.minimum((q * 10).astype(int), 9)
    rel = []
    for i in range(10):
        ix = bins == i
        if ix.any():
            rel.append({"bin": i, "n": int(ix.sum()), "meanPrediction": float(q[ix].mean()), "observed": float(y[ix].mean())})
    return {
        "n": int(mask.sum()), "excludedTies": int((~mask).sum()), "logLoss": float(log_loss(y, q, labels=[0, 1])),
        "binaryBrier": float(np.mean((q - y) ** 2)), "AUC": float(roc_auc_score(y, q)),
        "accuracy": float(np.mean((q >= 0.5) == y)), "calibrationBias": float(np.mean(q - y)), "reliability": rel,
    }


def baseline_diagnostics(sport: str, test: pd.DataFrame, actual: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    residual_margin = (actual[:, 0]-actual[:, 1]) - (pred[:, 0]-pred[:, 1])
    residual_total = (actual[:, 0]+actual[:, 1]) - (pred[:, 0]+pred[:, 1])
    predicted_margin = pred[:, 0]-pred[:, 1]
    predicted_total = pred[:, 0]+pred[:, 1]
    quantile = pd.qcut(pd.Series(predicted_margin), q=5, duplicates="drop")
    residual_bins = []
    for level in quantile.cat.categories:
        ix = quantile.eq(level).to_numpy()
        residual_bins.append({"bin": str(level), "n": int(ix.sum()), "meanPredictedMargin": float(predicted_margin[ix].mean()), "meanMarginResidual": float(residual_margin[ix].mean()), "meanTotalResidual": float(residual_total[ix].mean())})
    if sport == "NFL":
        support = np.minimum(pd.to_numeric(test.home_prior_games), pd.to_numeric(test.away_prior_games))
        rest = test.home_short_week.astype(bool) | test.away_short_week.astype(bool)
    elif sport == "CFB":
        support = np.minimum(pd.to_numeric(test.home_current_season_games), pd.to_numeric(test.away_current_season_games))
        rest = test.home_long_gap.astype(bool) | test.away_long_gap.astype(bool)
    else:
        support = np.minimum(pd.to_numeric(test.home_season_games_played), pd.to_numeric(test.away_season_games_played))
        rest = test.home_back_to_back.astype(bool) | test.away_back_to_back.astype(bool)
    segments = {}
    masks = {
        "LOW_SUPPORT_LT5": np.asarray(support < 5), "ESTABLISHED_SUPPORT_GE5": np.asarray(support >= 5),
        "HOME_EXPECTED_FAVORITE": predicted_margin >= 0, "AWAY_EXPECTED_FAVORITE": predicted_margin < 0,
        "REST_STRESS_OR_LONG_GAP": np.asarray(rest), "ORDINARY_REST": ~np.asarray(rest),
        "HIGH_PREDICTED_TOTAL_TOP_THIRD": predicted_total >= np.quantile(predicted_total, 2/3),
        "LOW_PREDICTED_TOTAL_BOTTOM_THIRD": predicted_total <= np.quantile(predicted_total, 1/3),
    }
    for name, ix in masks.items():
        if ix.sum():
            err = row_errors(actual[ix], pred[ix])
            segments[name] = {"n": int(ix.sum()), **{k: float(v.mean()) for k,v in err.items() if k in ("scoreMAE","marginMAE","totalMAE")}}
    return {"residualBins": residual_bins, "segments": segments}


def bootstrap(delta: np.ndarray, dates: pd.Series, reps: int = 2000) -> list[float]:
    weeks = pd.to_datetime(dates, utc=True).dt.strftime("%G-%V").to_numpy()
    ids = np.array(sorted(set(weeks)))
    sums = np.array([delta[weeks == x].sum() for x in ids])
    counts = np.array([(weeks == x).sum() for x in ids])
    rng = np.random.default_rng(SEED)
    take = rng.integers(0, len(ids), size=(reps, len(ids)))
    values = sums[take].sum(axis=1) / counts[take].sum(axis=1)
    return [float(x) for x in np.quantile(values, [0.025, 0.975])]


def experiment(frames: dict[str, pd.DataFrame], design: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    with threadpool_limits(limits=1):
        for sport, f in frames.items():
            candidates = design["candidates"][sport]
            all_rows = []
            seasonal = []
            for season in design["roles"]["Development"][sport] + design["roles"]["ReusedLaterDiagnostic"][sport]:
                train = f[f.audit_season < season].copy()
                test = f[f.audit_season == season].copy().reset_index(drop=True)
                if sport == "NFL":
                    train = train[train.audit_season >= 2000].copy()
                if not len(train) or not len(test):
                    continue
                if pd.to_datetime(train.game_date, utc=True).max() >= pd.to_datetime(test.game_date, utc=True).min():
                    raise ValueError(f"{sport} chronology failure {season}")
                actual = test[["home_score", "away_score"]].to_numpy(float)
                season_predictions = {}
                for candidate in candidates:
                    tr, te, cols = candidate_frames(sport, candidate, train, test, FEATURES[sport])
                    pred, prob = fit_predict(sport, tr, te, cols)
                    err = row_errors(actual, pred)
                    summary = {k: float(v.mean()) for k, v in err.items()}
                    summary.update({
                        "sport": sport, "season": int(season), "role": role_for(sport, season, design), "candidate": candidate,
                        "trainGames": len(train), "assessmentGames": len(test), "features": len(cols),
                        "winnerAccuracyFromExpectedScores": float(np.mean(np.sign(pred[:, 0] - pred[:, 1]) == np.sign(actual[:, 0] - actual[:, 1]))),
                        "probability": probability_metrics(actual, prob),
                    })
                    if candidate == "BASELINE":
                        summary["diagnostics"] = baseline_diagnostics(sport, test, actual, pred)
                    seasonal.append(summary)
                    season_predictions[candidate] = (err, pred, prob)
                base = season_predictions["BASELINE"][0]
                for candidate in candidates:
                    err = season_predictions[candidate][0]
                    for i, row in test.iterrows():
                        all_rows.append({
                            "candidate": candidate, "season": int(season), "role": role_for(sport, season, design),
                            "date": str(row.game_date),
                            **{f"delta_{k}": float(err[k][i] - base[k][i]) for k in ("scoreMAE", "marginMAE", "totalMAE")},
                        })
            rows = pd.DataFrame(all_rows)
            pooled = []
            later = rows[rows.role == "ReusedLaterDiagnostic"]
            for candidate in candidates:
                z = later[later.candidate == candidate]
                item = {"candidate": candidate, "games": len(z)}
                for metric in ("scoreMAE", "marginMAE", "totalMAE"):
                    values = z[f"delta_{metric}"].to_numpy(float)
                    item[f"delta_{metric}"] = float(values.mean())
                    item[f"interval95_{metric}"] = bootstrap(values, z.date) if len(values) else None
                per = [s for s in seasonal if s["candidate"] == candidate and s["role"] == "ReusedLaterDiagnostic"]
                item["seasonDeltas"] = []
                for s in per:
                    b = next(x for x in seasonal if x["season"] == s["season"] and x["candidate"] == "BASELINE")
                    item["seasonDeltas"].append({"season": s["season"], **{f"delta_{m}": s[m] - b[m] for m in ("scoreMAE", "marginMAE", "totalMAE")}})
                passes = candidate != "BASELINE" and any(item[f"interval95_{m}"][1] < 0 for m in ("scoreMAE", "marginMAE", "totalMAE"))
                passes = passes and all(item[f"delta_{m}"] <= design["materialDegradationPoints"] for m in ("scoreMAE", "marginMAE", "totalMAE"))
                passes = passes and all(all(x[f"delta_{m}"] <= design["materialDegradationPoints"] for m in ("scoreMAE", "marginMAE", "totalMAE")) for x in item["seasonDeltas"])
                item["passesFrozenGate"] = bool(passes)
                pooled.append(item)
            results[sport] = {"seasonal": seasonal, "pooledReusedLater": pooled}
    return results


def injury_matrix() -> dict[str, Any]:
    common = {
        "retainedPointInTimeAvailability": False,
        "permittedUse": "readiness design only; no model feature in this study",
        "prohibitedSubstitutes": ["postgame participation", "current roster projected backward", "final lineup or inactive list after cutoff"],
        "requiredContract": ["canonical player and team identity", "status and status vocabulary", "source publication time", "retrieval time", "effective game", "revision/correction lineage", "source payload digest"],
    }
    return {
        "NFL": {**common, "highestValueFields": ["QB starter/status", "offensive-line availability", "skill-player availability", "defensive starter availability"], "earliestCredibleTiming": "official practice participation and game-status reports; exact historical revisions not retained"},
        "CFB": {**common, "highestValueFields": ["QB availability", "starter depth-chart change", "transfer/eligibility status"], "earliestCredibleTiming": "team/conference reports vary; no governed uniform retained feed"},
        "NBA": {**common, "highestValueFields": ["official injury status", "confirmed active/inactive", "expected minutes restriction", "starter availability"], "earliestCredibleTiming": "league/team injury reports; revision history and cutoff binding required"},
    }


def plot_outputs(quality: dict, experiments: dict, out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    colors = {"NFL": "#1f77b4", "CFB": "#ff7f0e", "NBA": "#2ca02c"}
    for sport in ("NFL", "CFB", "NBA"):
        seasons = quality[sport]["seasons"]
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.bar([str(x["season"]) for x in seasons], [x["games"] for x in seasons], color=colors[sport])
        ax.set(title=f"{sport}: admitted games by season", xlabel="Audit season", ylabel="Games")
        ax.tick_params(axis="x", rotation=45); fig.tight_layout()
        p = out / f"{sport.lower()}_coverage.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(str(p.relative_to(ROOT)))

        miss = quality[sport]["topMissingFeatures"][:10]
        fig, ax = plt.subplots(figsize=(9, 4.8))
        if miss:
            ax.barh([x["name"] for x in reversed(miss)], [100*x["missingRate"] for x in reversed(miss)], color=colors[sport])
        ax.set(title=f"{sport}: highest retained feature missingness", xlabel="Missing cells (%)")
        fig.tight_layout(); p = out / f"{sport.lower()}_missingness.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(str(p.relative_to(ROOT)))

        pooled = [x for x in experiments[sport]["pooledReusedLater"] if x["candidate"] != "BASELINE"]
        fig, ax = plt.subplots(figsize=(9, 4.8))
        xpos = np.arange(len(pooled)); width = .25
        for j, metric in enumerate(("scoreMAE", "marginMAE", "totalMAE")):
            ax.bar(xpos + (j-1)*width, [x[f"delta_{metric}"] for x in pooled], width, label=metric)
        ax.axhline(0, color="black", lw=.8); ax.set_xticks(xpos, [x["candidate"] for x in pooled], rotation=20, ha="right")
        ax.set(title=f"{sport}: candidate minus baseline error on reused evidence", ylabel="MAE delta (lower is better)")
        ax.legend(); fig.tight_layout(); p = out / f"{sport.lower()}_experiment_deltas.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(str(p.relative_to(ROOT)))

        target = quality[sport]["targets"]
        season_rows = quality[sport]["seasons"]
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.plot([x["season"] for x in season_rows], [100*x["featureMissingRate"] for x in season_rows], marker="o", label="missing feature cells")
        ax.set(title=f"{sport}: feature availability over time", xlabel="Audit season", ylabel="Missing cells (%)")
        ax.legend(); fig.tight_layout(); p = out / f"{sport.lower()}_availability_timeline.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(str(p.relative_to(ROOT)))

        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.bar([str(x["season"]) for x in season_rows], [100*x["lowSupportRateLt5"] for x in season_rows], color=colors[sport])
        ax.set(title=f"{sport}: cold-start exposure coverage", xlabel="Audit season", ylabel="Games with either team below 5 games (%)")
        ax.tick_params(axis="x", rotation=45); fig.tight_layout(); p = out / f"{sport.lower()}_cold_start_coverage.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(str(p.relative_to(ROOT)))

        drift = quality[sport]["topDriftFeatures"][:10]
        fig, ax = plt.subplots(figsize=(9, 4.8))
        ax.barh([x["name"] for x in reversed(drift)], [x["developmentToLaterPsi"] for x in reversed(drift)], color=colors[sport])
        ax.axvline(.25, color="firebrick", linestyle="--", label="PSI 0.25 reference")
        ax.set(title=f"{sport}: Development to reused-later feature drift", xlabel="Population stability index")
        ax.legend(); fig.tight_layout(); p = out / f"{sport.lower()}_temporal_drift.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(str(p.relative_to(ROOT)))

        assoc = quality[sport]["topTargetAssociations"][:12]
        fig, ax = plt.subplots(figsize=(9, 5.2))
        ypos = np.arange(len(assoc)); width = .36
        ax.barh(ypos-width/2, [x["correlationHomeMargin"] or 0 for x in assoc], width, label="home margin")
        ax.barh(ypos+width/2, [x["correlationTotal"] or 0 for x in assoc], width, label="total")
        ax.set_yticks(ypos, [x["name"] for x in assoc]); ax.invert_yaxis(); ax.axvline(0,color="black",lw=.8)
        ax.set(title=f"{sport}: strongest univariate target associations", xlabel="Pearson correlation (associational)")
        ax.legend(); fig.tight_layout(); p = out / f"{sport.lower()}_target_associations.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(str(p.relative_to(ROOT)))

        base = [x for x in experiments[sport]["seasonal"] if x["candidate"] == "BASELINE" and x["role"] == "ReusedLaterDiagnostic"]
        fig, ax = plt.subplots(figsize=(8, 4.5))
        for row in base:
            bins = row["diagnostics"]["residualBins"]
            ax.plot([x["meanPredictedMargin"] for x in bins], [x["meanMarginResidual"] for x in bins], marker="o", label=str(row["season"]))
        ax.axhline(0, color="black", lw=.8); ax.set(title=f"{sport}: baseline margin residuals", xlabel="Predicted margin bin mean", ylabel="Observed minus predicted margin")
        ax.legend(); fig.tight_layout(); p = out / f"{sport.lower()}_margin_residuals.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(str(p.relative_to(ROOT)))

        probs = [x for x in base if x["probability"]]
        fig, ax = plt.subplots(figsize=(6, 5))
        for row in probs:
            rel = row["probability"]["reliability"]
            ax.plot([x["meanPrediction"] for x in rel], [x["observed"] for x in rel], marker="o", label=str(row["season"]))
        ax.plot([0,1],[0,1], color="black", linestyle="--")
        ax.set(title=f"{sport}: retained baseline reliability", xlabel="Mean home-win probability", ylabel="Observed home-win rate", xlim=(0,1), ylim=(0,1))
        if probs: ax.legend()
        else: ax.text(.5,.5,"No supported probability channel\nfor this bounded point-model run",ha="center",va="center")
        fig.tight_layout(); p = out / f"{sport.lower()}_reliability.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(str(p.relative_to(ROOT)))

        # Target distribution uses aggregate quantiles to avoid retaining row-level evidence.
        qs = target["scoreQuantiles"]
        fig, ax = plt.subplots(figsize=(7, 4.5))
        xpos = np.arange(3)
        ax.plot(xpos, [qs[k][0] for k in ("0.01","0.5","0.99")], marker="o", label="home score")
        ax.plot(xpos, [qs[k][1] for k in ("0.01","0.5","0.99")], marker="o", label="away score")
        ax.set_xticks(xpos, ["1st percentile","median","99th percentile"]); ax.set(title=f"{sport}: score distribution landmarks", ylabel="Final points")
        ax.legend(); fig.tight_layout(); p = out / f"{sport.lower()}_target_distribution.png"; fig.savefig(p, dpi=160); plt.close(fig); paths.append(str(p.relative_to(ROOT)))
    return paths


def artifact_index(doc: Path) -> dict[str, Any]:
    files = []
    for path in sorted(doc.rglob("*")):
        if path.is_file() and path.name != "artifact-index.json":
            files.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path), "bytes": path.stat().st_size})
    return {"identity": "NFL_CFB_NBA_FEATURE_READINESS_ARTIFACT_INDEX_V1", "files": files}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--output-dir", type=Path, default=DOC)
    args = ap.parse_args()
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    frames, receipt = load_bound(args.input_dir)
    quality, registry, missing = quality_and_registry(frames, design)
    experiments = experiment(frames, design)
    figures = plot_outputs(quality, experiments, args.output_dir / "figures")
    write_json(args.output_dir / "BOUND_INPUT_RECEIPT.json", receipt)
    write_json(args.output_dir / "DATA_QUALITY_SCORECARDS.json", quality)
    write_json(args.output_dir / "FEATURE_REGISTRIES.json", registry)
    write_json(args.output_dir / "MISSINGNESS_AND_IMPUTATION.json", missing)
    write_json(args.output_dir / "COLD_START_SPECIFICATIONS.json", {s: missing[s]["coldStart"] for s in missing})
    write_json(args.output_dir / "INJURY_AVAILABILITY_MATRIX.json", injury_matrix())
    write_json(args.output_dir / "EXPERIMENT_RESULTS.json", experiments)
    write_json(args.output_dir / "FIGURE_INDEX.json", {"figures": figures})
    write_json(args.output_dir / "artifact-index.json", artifact_index(args.output_dir))
    print(json.dumps({
        "status": "complete", "inputs": {s: len(f) for s, f in frames.items()},
        "passingBlocks": {s: [x["candidate"] for x in experiments[s]["pooledReusedLater"] if x["passesFrozenGate"]] for s in experiments},
        "figures": len(figures),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
