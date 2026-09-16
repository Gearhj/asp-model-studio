"""Deterministic, reviewable reporting outputs for NFL M1 research.

The reporting layer accepts already-produced research tables.  It does not
read providers, fit/score models, or infer unavailable evidence.  Missing or
sparse inputs produce an explicit ``NOT_AVAILABLE`` chart rather than a zero.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Mapping

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


CSV_NAMES: Mapping[str, str] = {
    "temporalSplits": "temporal_splits.csv",
    "foldMetrics": "fold_metrics.csv",
    "foldCalibration": "fold_calibration.csv",
    "featureTiers": "feature_tier_leaderboard.csv",
    "recencyStrategies": "recency_strategy_leaderboard.csv",
    "candidateModels": "candidate_model_leaderboard.csv",
    "calibration": "calibration_tables.csv",
    "market": "market_benchmark.csv",
    "slices": "stability_slices.csv",
    "gamePredictions": "game_level_predictions.csv",
    "distributionCoverage": "score_distribution_coverage.csv",
    "featureCoefficients": "feature_coefficients.csv",
    "missingnessSourceEra": "missingness_source_era.csv",
    "missingReasonSummary": "missing_reason_summary.csv",
}

CHART_NAMES: Mapping[str, str] = {
    "oofOotLeaderboard": "oof_oot_model_leaderboard.png",
    "calibration": "calibration.png",
    "homeAwayPointsError": "home_away_points_error.png",
    "spreadTotalError": "spread_total_error.png",
    "cumulativeLogLossDifference": "cumulative_log_loss_difference.png",
    "weeklyStability": "weekly_stability.png",
    "featureTierAblation": "feature_tier_ablation.png",
    "recencyStrategy": "recency_strategy_comparison.png",
    "scoreDistributionCoverage": "score_distribution_coverage.png",
    "modelMarketDisagreement": "model_market_disagreement.png",
}

_MODEL_COLUMNS = ("candidate_id", "candidate", "model_id", "model", "engine")
_SCOPE_COLUMNS = ("scope", "evaluation_scope", "split", "role")
_LOG_LOSS_COLUMNS = ("home_win_log_loss", "homeWinLogLoss", "log_loss", "logLoss")
_COLORS = ("#0f766e", "#2563eb", "#9333ea", "#d97706", "#dc2626", "#475569")


@dataclass(frozen=True)
class ReportingArtifacts:
    output_directory: Path
    csv_paths: Mapping[str, Path]
    chart_paths: Mapping[str, Path]
    chart_status: Mapping[str, str]
    manifest_path: Path


def _first_column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _finite(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty or any(name not in frame.columns for name in columns):
        return frame.iloc[0:0].copy()
    mask = np.ones(len(frame), dtype=bool)
    for name in columns:
        values = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
        mask &= np.isfinite(values)
    return frame.loc[mask].copy()


def _json_cell(value: object) -> object:
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, (list, tuple, set)):
        normalized = sorted(value) if isinstance(value, set) else list(value)
        return json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    return value


def _stable_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame()
    stable = frame.copy(deep=True)
    for name in stable.select_dtypes(include="object").columns:
        stable[name] = stable[name].map(_json_cell)
    sort_priority = (
        "fold_id", "fold", "scope", "evaluation_scope", "split", "season",
        "game_date", "date", "week", "candidate_id", "candidate", "model_id",
        "model", "feature_tier", "tier", "recency_strategy", "strategy",
        "bin", "bin_lower", "slice_family", "slice_value",
    )
    keys = [name for name in sort_priority if name in stable.columns]
    if keys and not stable.empty:
        stable = stable.sort_values(keys, kind="mergesort", na_position="last")
    return stable.reset_index(drop=True)


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    frame.to_csv(
        temporary,
        index=False,
        lineterminator="\n",
        float_format="%.12g",
        na_rep="",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _new_figure(title: str) -> tuple[plt.Figure, plt.Axes]:
    figure, axis = plt.subplots(figsize=(10, 6), dpi=120)
    figure.patch.set_facecolor("white")
    axis.set_title(title, loc="left", fontsize=14, fontweight="bold")
    axis.grid(axis="y", color="#e2e8f0", linewidth=0.8, alpha=0.8)
    axis.set_axisbelow(True)
    return figure, axis


def _not_available(axis: plt.Axes, reason: str) -> str:
    axis.clear()
    axis.axis("off")
    axis.text(
        0.5,
        0.55,
        "NOT AVAILABLE",
        ha="center",
        va="center",
        fontsize=16,
        fontweight="bold",
        color="#475569",
        transform=axis.transAxes,
    )
    axis.text(
        0.5,
        0.43,
        reason,
        ha="center",
        va="center",
        fontsize=10,
        color="#64748b",
        wrap=True,
        transform=axis.transAxes,
    )
    return "NOT_AVAILABLE"


def _save_figure(path: Path, figure: plt.Figure) -> None:
    figure.tight_layout()
    temporary = path.with_name(f".{path.stem}.tmp-{uuid.uuid4().hex}.png")
    figure.savefig(
        temporary,
        format="png",
        dpi=120,
        bbox_inches="tight",
        metadata={"Software": "ASP_MODEL_STUDIO_NFL_M1_REPORTING_V1"},
    )
    plt.close(figure)
    os.replace(temporary, path)


def _label_values(axis: plt.Axes, bars: object) -> None:
    try:
        axis.bar_label(bars, fmt="%.4f", padding=3, fontsize=8)
    except (AttributeError, ValueError):
        return


def _chart_oof_oot(frame: pd.DataFrame, axis: plt.Axes) -> str:
    model = _first_column(frame, _MODEL_COLUMNS)
    scope = _first_column(frame, _SCOPE_COLUMNS)
    metric = _first_column(frame, _LOG_LOSS_COLUMNS)
    if not model or not scope or not metric:
        return _not_available(axis, "Candidate, OOF/OOT scope, or log-loss evidence is absent.")
    data = _finite(frame, [metric])
    if data.empty:
        return _not_available(axis, "No finite OOF/OOT log-loss values were produced.")
    pivot = data.pivot_table(index=model, columns=scope, values=metric, aggfunc="first")
    pivot = pivot.sort_index()
    scopes = [name for name in ("OOF", "FINAL_OOT", "OOT") if name in pivot.columns]
    scopes += [name for name in pivot.columns if name not in scopes]
    if not scopes:
        return _not_available(axis, "No OOF/OOT scopes are available.")
    x = np.arange(len(pivot.index))
    width = 0.8 / len(scopes)
    for index, name in enumerate(scopes):
        values = pd.to_numeric(pivot[name], errors="coerce").to_numpy(dtype=float)
        bars = axis.bar(x + (index - (len(scopes) - 1) / 2) * width, values, width, label=str(name), color=_COLORS[index % len(_COLORS)])
        _label_values(axis, bars)
    axis.set_xticks(x, [str(value) for value in pivot.index], rotation=30, ha="right")
    axis.set_ylabel("Home-win log loss (lower is better)")
    axis.legend(frameon=False)
    return "RENDERED"


def _chart_calibration(frame: pd.DataFrame, axis: plt.Axes) -> str:
    predicted = _first_column(
        frame,
        ("mean_probability", "mean_predicted", "predicted_probability", "meanPrediction", "predicted"),
    )
    observed = _first_column(frame, ("observed_rate", "observed_frequency", "observed", "event_rate"))
    model = _first_column(frame, _MODEL_COLUMNS)
    scope = _first_column(frame, _SCOPE_COLUMNS)
    if not predicted or not observed:
        return _not_available(axis, "Calibration-bin predictions and observed frequencies are absent.")
    data = _finite(frame, [predicted, observed])
    if data.empty:
        return _not_available(axis, "No finite calibration bins were produced.")
    groups = [name for name in (model, scope) if name]
    if groups:
        for index, (key, group) in enumerate(data.groupby(groups, sort=True, dropna=False)):
            label = " / ".join(str(value) for value in (key if isinstance(key, tuple) else (key,)))
            group = group.sort_values(predicted)
            axis.plot(group[predicted], group[observed], marker="o", linewidth=1.5, markersize=4, label=label, color=_COLORS[index % len(_COLORS)])
    else:
        data = data.sort_values(predicted)
        axis.plot(data[predicted], data[observed], marker="o", color=_COLORS[0])
    axis.plot([0, 1], [0, 1], linestyle="--", linewidth=1, color="#64748b", label="Ideal")
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.set_xlabel("Mean predicted home-win probability")
    axis.set_ylabel("Observed home-win frequency")
    axis.legend(frameon=False, fontsize=8)
    return "RENDERED"


def _chart_home_away_error(frame: pd.DataFrame, axis: plt.Axes) -> str:
    model = _first_column(frame, _MODEL_COLUMNS)
    home = _first_column(frame, ("home_points_mae", "homePointsMae", "home_mae"))
    away = _first_column(frame, ("away_points_mae", "awayPointsMae", "away_mae"))
    if not model or not home or not away:
        return _not_available(axis, "Home/away points MAE is absent from the candidate leaderboard.")
    data = _finite(frame, [home, away])
    scope = _first_column(data, _SCOPE_COLUMNS)
    if scope and any(str(value).upper() in {"FINAL_OOT", "OOT"} for value in data[scope]):
        data = data[data[scope].astype(str).str.upper().isin({"FINAL_OOT", "OOT"})]
    if data.empty:
        return _not_available(axis, "No finite home/away points errors were produced.")
    data = data.drop_duplicates(model).sort_values(model)
    x = np.arange(len(data))
    bars_home = axis.bar(x - 0.2, data[home], 0.4, label="Home", color=_COLORS[0])
    bars_away = axis.bar(x + 0.2, data[away], 0.4, label="Away", color=_COLORS[1])
    axis.set_xticks(x, data[model].astype(str), rotation=30, ha="right")
    axis.set_ylabel("Points MAE (lower is better)")
    axis.legend(frameon=False)
    _label_values(axis, bars_home)
    _label_values(axis, bars_away)
    return "RENDERED"


def _aggregate_market_errors(frame: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    model = _first_column(frame, _MODEL_COLUMNS)
    if not model:
        return pd.DataFrame(), None
    if {"spread_mae", "total_mae"}.issubset(frame.columns):
        return _finite(frame, ["spread_mae", "total_mae"]), model
    spread = _first_column(frame, ("spread_projection_error", "spread_error"))
    total = _first_column(frame, ("total_projection_error", "total_error"))
    if not spread or not total:
        return pd.DataFrame(), model
    data = frame.copy()
    data["spread_mae"] = pd.to_numeric(data[spread], errors="coerce").abs()
    data["total_mae"] = pd.to_numeric(data[total], errors="coerce").abs()
    return data.groupby(model, as_index=False, sort=True)[["spread_mae", "total_mae"]].mean(), model


def _chart_spread_total(frame: pd.DataFrame, axis: plt.Axes) -> str:
    data, model = _aggregate_market_errors(frame)
    if not model or data.empty:
        return _not_available(axis, "Complete spread/total projection evidence is unavailable.")
    data = data.drop_duplicates(model).sort_values(model)
    x = np.arange(len(data))
    axis.bar(x - 0.2, data["spread_mae"], 0.4, label="Spread", color=_COLORS[2])
    axis.bar(x + 0.2, data["total_mae"], 0.4, label="Total", color=_COLORS[3])
    axis.set_xticks(x, data[model].astype(str), rotation=30, ha="right")
    axis.set_ylabel("Absolute projection error")
    axis.legend(frameon=False)
    return "RENDERED"


def _chart_cumulative(frame: pd.DataFrame, axis: plt.Axes) -> str:
    model = _first_column(frame, _MODEL_COLUMNS)
    date_name = _first_column(frame, ("game_date", "date"))
    model_loss = _first_column(frame, ("model_log_loss", "home_win_log_loss", "log_loss"))
    baseline_loss = _first_column(frame, ("baseline_log_loss", "reference_log_loss", "market_log_loss"))
    if not model or not date_name or not model_loss or not baseline_loss:
        return _not_available(axis, "Game-level model and reference log losses are absent.")
    data = _finite(frame, [model_loss, baseline_loss])
    if data.empty:
        return _not_available(axis, "No matched finite game-level log-loss differences exist.")
    data[date_name] = pd.to_datetime(data[date_name], errors="coerce")
    data = data[data[date_name].notna()]
    for index, (name, group) in enumerate(data.groupby(model, sort=True)):
        group = group.sort_values([date_name], kind="mergesort")
        difference = pd.to_numeric(group[model_loss]) - pd.to_numeric(group[baseline_loss])
        axis.plot(group[date_name], difference.cumsum(), label=str(name), color=_COLORS[index % len(_COLORS)])
    if not axis.lines:
        return _not_available(axis, "No dated cumulative log-loss series exists.")
    axis.axhline(0, color="#64748b", linewidth=1, linestyle="--")
    axis.set_ylabel("Cumulative model − reference log loss")
    axis.legend(frameon=False, fontsize=8)
    return "RENDERED"


def _chart_weekly(frame: pd.DataFrame, axis: plt.Axes) -> str:
    metric = _first_column(frame, _LOG_LOSS_COLUMNS)
    model = _first_column(frame, _MODEL_COLUMNS)
    week = _first_column(frame, ("week", "slice_value"))
    data = frame.copy()
    if "slice_family" in data.columns:
        data = data[data["slice_family"].astype(str).str.lower().eq("week")]
    if not metric or not week:
        return _not_available(axis, "Week-level stability metrics are absent.")
    data = _finite(data, [metric, week])
    if data.empty:
        return _not_available(axis, "No finite weekly stability values were produced.")
    if model:
        for index, (name, group) in enumerate(data.groupby(model, sort=True)):
            group = group.sort_values(week)
            axis.plot(group[week], group[metric], marker="o", label=str(name), color=_COLORS[index % len(_COLORS)])
        axis.legend(frameon=False, fontsize=8)
    else:
        data = data.sort_values(week)
        axis.plot(data[week], data[metric], marker="o", color=_COLORS[0])
    axis.set_xlabel("NFL week")
    axis.set_ylabel("Home-win log loss")
    return "RENDERED"


def _chart_ranked(frame: pd.DataFrame, axis: plt.Axes, *, names: tuple[str, ...], title: str) -> str:
    category = _first_column(frame, names)
    metric = _first_column(frame, _LOG_LOSS_COLUMNS + ("oof_metric", "metric_value"))
    data = frame.copy()
    if "status" in data.columns:
        data = data[~data["status"].astype(str).str.upper().isin({"NOT_AVAILABLE", "SOURCE_TABLE_ONLY", "NOT_POINT_IN_TIME_MATERIALIZABLE", "DEPENDENCY_NOT_MATERIALIZED"})]
    if not category or not metric:
        return _not_available(axis, f"No comparable {title.lower()} metric is available.")
    data = _finite(data, [metric]).drop_duplicates(category).sort_values(metric)
    if data.empty:
        return _not_available(axis, f"Every {title.lower()} candidate is unavailable or lacks a finite metric.")
    bars = axis.barh(data[category].astype(str), data[metric], color=_COLORS[0])
    axis.invert_yaxis()
    axis.set_xlabel("OOF home-win log loss (lower is better)")
    _label_values(axis, bars)
    return "RENDERED"


def _chart_recency_strategy(frame: pd.DataFrame, axis: plt.Axes) -> str:
    """Compare recency on the common score-family screening candidates.

    Later hyperparameter candidates are evaluated only under their family's
    OOF-selected recency.  Mixing those one-off rows into a recency chart would
    make the six strategies incomparable, so this chart retains only the one
    candidate per score family that was actually screened under every strategy.
    """

    required = {
        "candidate_id",
        "family",
        "recency_strategy",
        "mean_team_points_mae",
    }
    if not required.issubset(frame.columns):
        return _not_available(axis, "Comparable score-family recency evidence is absent.")
    data = _finite(frame, ["mean_team_points_mae"])
    if data.empty:
        return _not_available(axis, "No finite score-family recency metrics were produced.")
    strategy_count = int(data["recency_strategy"].nunique())
    screened = (
        data.groupby(["family", "candidate_id"], as_index=False, sort=True)[
            "recency_strategy"
        ]
        .nunique()
        .rename(columns={"recency_strategy": "strategy_count"})
    )
    screened = screened[screened["strategy_count"] == strategy_count]
    if screened.empty:
        return _not_available(axis, "No score candidate was screened under every recency strategy.")
    # The bounded runner declares exactly one all-strategy screening candidate
    # per score family.  Fail closed to a deterministic first identity if a
    # future grid accidentally adds another, rather than double-weighting it.
    screened = screened.sort_values(["family", "candidate_id"], kind="mergesort").drop_duplicates(
        "family", keep="first"
    )
    comparable = data.merge(
        screened[["family", "candidate_id"]],
        on=["family", "candidate_id"],
        how="inner",
        validate="many_to_one",
    )
    aggregate = (
        comparable.groupby("recency_strategy", as_index=False, sort=True)[
            "mean_team_points_mae"
        ]
        .mean()
        .sort_values(["mean_team_points_mae", "recency_strategy"], kind="mergesort")
    )
    if len(aggregate) != strategy_count:
        return _not_available(axis, "Recency strategies do not share a common score-family screen.")
    bars = axis.barh(
        aggregate["recency_strategy"].astype(str),
        aggregate["mean_team_points_mae"],
        color=_COLORS[0],
    )
    axis.invert_yaxis()
    axis.set_xlabel("Mean OOF team-points MAE across screening score families (lower is better)")
    _label_values(axis, bars)
    return "RENDERED"


def _chart_coverage(frame: pd.DataFrame, axis: plt.Axes) -> str:
    nominal = _first_column(frame, ("nominal_coverage", "nominal", "interval_probability"))
    empirical = _first_column(frame, ("empirical_coverage", "observed_coverage", "coverage"))
    model = _first_column(frame, _MODEL_COLUMNS)
    if not nominal or not empirical:
        return _not_available(axis, "Nominal and empirical score-distribution coverage is absent.")
    data = _finite(frame, [nominal, empirical])
    if data.empty:
        return _not_available(axis, "No finite score-distribution coverage rows were produced.")
    if model:
        for index, (name, group) in enumerate(data.groupby(model, sort=True)):
            group = group.sort_values(nominal)
            axis.plot(group[nominal], group[empirical], marker="o", label=str(name), color=_COLORS[index % len(_COLORS)])
        axis.legend(frameon=False, fontsize=8)
    else:
        data = data.sort_values(nominal)
        axis.plot(data[nominal], data[empirical], marker="o", color=_COLORS[0])
    low = min(0.0, float(data[nominal].min()))
    high = max(1.0, float(data[nominal].max()))
    axis.plot([low, high], [low, high], linestyle="--", color="#64748b")
    axis.set_xlabel("Nominal interval coverage")
    axis.set_ylabel("Empirical interval coverage")
    return "RENDERED"


def _chart_disagreement(frame: pd.DataFrame, axis: plt.Axes) -> str:
    model_probability = _first_column(frame, ("model_probability", "home_win_probability", "model_home_win_probability"))
    market_probability = _first_column(frame, ("no_vig_market_probability", "market_probability", "market_home_win_probability"))
    model = _first_column(frame, _MODEL_COLUMNS)
    if not model_probability or not market_probability:
        return _not_available(axis, "Matched model and no-vig market probabilities are unavailable.")
    data = _finite(frame, [model_probability, market_probability])
    data = data[
        data[model_probability].between(0, 1)
        & data[market_probability].between(0, 1)
    ]
    if data.empty:
        return _not_available(axis, "No valid matched model/market probabilities exist.")
    if model:
        for index, (name, group) in enumerate(data.groupby(model, sort=True)):
            axis.scatter(group[market_probability], group[model_probability], s=16, alpha=0.55, label=str(name), color=_COLORS[index % len(_COLORS)])
        axis.legend(frameon=False, fontsize=8)
    else:
        axis.scatter(data[market_probability], data[model_probability], s=16, alpha=0.55, color=_COLORS[0])
    axis.plot([0, 1], [0, 1], linestyle="--", color="#64748b")
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.set_xlabel("No-vig market home-win probability")
    axis.set_ylabel("Model home-win probability")
    return "RENDERED"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_m1_research_outputs(
    output_directory: Path,
    *,
    temporal_splits: pd.DataFrame,
    feature_tiers: pd.DataFrame,
    candidate_leaderboard: pd.DataFrame,
    calibration: pd.DataFrame,
    market: pd.DataFrame,
    slices: pd.DataFrame,
    fold_metrics: pd.DataFrame | None = None,
    fold_calibration: pd.DataFrame | None = None,
    recency_leaderboard: pd.DataFrame | None = None,
    game_predictions: pd.DataFrame | None = None,
    distribution_coverage: pd.DataFrame | None = None,
    feature_coefficients: pd.DataFrame | None = None,
    missingness_source_era: pd.DataFrame | None = None,
    missing_reason_summary: pd.DataFrame | None = None,
) -> ReportingArtifacts:
    """Write the deterministic NFL M1 tabular and static-chart bundle."""

    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    frames = {
        "temporalSplits": _stable_frame(temporal_splits),
        "foldMetrics": _stable_frame(fold_metrics),
        "foldCalibration": _stable_frame(fold_calibration),
        "featureTiers": _stable_frame(feature_tiers),
        "recencyStrategies": _stable_frame(recency_leaderboard),
        "candidateModels": _stable_frame(candidate_leaderboard),
        "calibration": _stable_frame(calibration),
        "market": _stable_frame(market),
        "slices": _stable_frame(slices),
        "gamePredictions": _stable_frame(game_predictions),
        "distributionCoverage": _stable_frame(distribution_coverage),
        "featureCoefficients": _stable_frame(feature_coefficients),
        "missingnessSourceEra": _stable_frame(missingness_source_era),
        "missingReasonSummary": _stable_frame(missing_reason_summary),
    }
    csv_paths: dict[str, Path] = {}
    for key, filename in CSV_NAMES.items():
        path = output / filename
        _atomic_csv(path, frames[key])
        csv_paths[key] = path

    chart_specs: tuple[tuple[str, str, pd.DataFrame, Callable[[pd.DataFrame, plt.Axes], str]], ...] = (
        ("oofOotLeaderboard", "OOF and final OOT model leaderboard", frames["candidateModels"], _chart_oof_oot),
        ("calibration", "Home-win probability calibration", frames["calibration"], _chart_calibration),
        ("homeAwayPointsError", "Home and away points error", frames["candidateModels"], _chart_home_away_error),
        ("spreadTotalError", "Spread and total projection error", frames["market"], _chart_spread_total),
        ("cumulativeLogLossDifference", "Cumulative log-loss difference", frames["gamePredictions"], _chart_cumulative),
        ("weeklyStability", "Weekly stability", frames["slices"], _chart_weekly),
        (
            "featureTierAblation", "Feature-tier ablation", frames["featureTiers"],
            lambda frame, axis: _chart_ranked(frame, axis, names=("feature_tier", "tier"), title="Feature tier"),
        ),
        (
            "recencyStrategy", "Recency-strategy comparison", frames["recencyStrategies"],
            _chart_recency_strategy,
        ),
        ("scoreDistributionCoverage", "Score-distribution interval coverage", frames["distributionCoverage"], _chart_coverage),
        ("modelMarketDisagreement", "Model versus market disagreement", frames["market"], _chart_disagreement),
    )
    chart_paths: dict[str, Path] = {}
    chart_status: dict[str, str] = {}
    for key, title, frame, renderer in chart_specs:
        path = output / CHART_NAMES[key]
        figure, axis = _new_figure(title)
        try:
            status = renderer(frame, axis)
        except (KeyError, TypeError, ValueError, pd.errors.DataError) as exc:
            status = _not_available(axis, f"Input is sparse or incompatible: {type(exc).__name__}.")
        _save_figure(path, figure)
        chart_paths[key] = path
        chart_status[key] = status

    manifest = {
        "contract": "ASP_NFL_M1_REPORTING_BUNDLE_V1",
        "csv": {
            key: {"file": path.name, "sha256": _sha256(path), "rows": len(frames[key])}
            for key, path in sorted(csv_paths.items())
        },
        "charts": {
            key: {"file": path.name, "sha256": _sha256(path), "status": chart_status[key]}
            for key, path in sorted(chart_paths.items())
        },
        "unavailableMeansZero": False,
        "modelsFittedByReporting": 0,
        "modelsScoredByReporting": 0,
    }
    manifest_path = output / "reporting_manifest.json"
    temporary = manifest_path.with_name(f".{manifest_path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, separators=(",", ": ")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, manifest_path)
    return ReportingArtifacts(
        output_directory=output,
        csv_paths=csv_paths,
        chart_paths=chart_paths,
        chart_status=chart_status,
        manifest_path=manifest_path,
    )


__all__ = [
    "CHART_NAMES",
    "CSV_NAMES",
    "ReportingArtifacts",
    "write_m1_research_outputs",
]
