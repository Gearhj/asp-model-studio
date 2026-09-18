"""Render three standalone scientific figures from the completed frozen study.

This reads completed research outputs only. It does not fit, select, resimulate,
acquire evidence, or alter any study or operational artifacts. Run after the
assessment stage has written all five required inputs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd


DEFAULT_OUTPUT = Path(r"C:\Users\james\asp-model-studio\outputs\cfb-opponent-adjusted-strength-v1")
ARMS = ("A", "B", "U_A", "U_B")
COLORS = {"A": "#245B84", "B": "#B97D13", "U_A": "#779BB6", "U_B": "#D3A956"}
LABELS = {"A": "A · opponent adjusted", "B": "B · adjusted + dynamic",
          "U_A": "U_A · unadjusted", "U_B": "U_B · unadjusted + dynamic"}
MARKERS = {"A": "o", "B": "s", "U_A": "o", "U_B": "s"}
INK, GRID = "#26313A", "#DEE3E8"
METRIC = "jointEnergyScore"
METHOD = "PAIRED_CALENDAR_WEEK_BLOCK_BOOTSTRAP_STRATIFIED_BY_SEASON"
CAUTION = "Class A reconstructed history; completion availability is not certified. All 2023–25 evidence is reused."
INPUT_NAMES = ("COMPARISON.csv", "PAIRED_EFFECTS.json", "COMMON_POPULATION_PREDICTIONS.parquet",
               "COMMON_POPULATION_SCORES.parquet", "FROZEN_SELECTION.json")


def binding(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def configure() -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12,
                         "axes.titlesize": 15, "axes.labelsize": 12,
                         "xtick.labelsize": 11, "ytick.labelsize": 12,
                         "text.color": INK, "axes.labelcolor": INK,
                         "xtick.color": INK, "ytick.color": INK,
                         "axes.edgecolor": "#8E99A3", "axes.spines.top": False,
                         "axes.spines.right": False, "figure.facecolor": "white",
                         "axes.facecolor": "white", "savefig.facecolor": "white",
                         "svg.fonttype": "none", "svg.hashsalt": "cfb-strength-study-v1",
                         "axes.formatter.useoffset": False, "lines.linewidth": 1.7})


def load_completed(output: Path):
    missing = [name for name in INPUT_NAMES if not (output / name).is_file()]
    if missing:
        raise ValueError(f"Completed assessment inputs required: {missing}")
    frozen = json.loads((output / "FROZEN_SELECTION.json").read_text(encoding="utf-8"))
    if frozen["maximumOutcomeSeasonRead"] != 2022 or frozen["selectedArm"] not in ("A", "B"):
        raise ValueError("Expected a Development-only frozen selection")
    comparison = pd.read_csv(output / "COMPARISON.csv", dtype={"period": str})
    effects = json.loads((output / "PAIRED_EFFECTS.json").read_text(encoding="utf-8"))
    prediction_columns = ["game_id", "season", "arm", "pred_margin", "pred_total", "low_support",
                          "home_current_support", "away_current_support", "home_prior_weight", "away_prior_weight"]
    predictions = pd.read_parquet(output / "COMMON_POPULATION_PREDICTIONS.parquet", columns=prediction_columns)
    scores = pd.read_parquet(output / "COMMON_POPULATION_SCORES.parquet",
                             columns=["game_id", "season", "arm", "jointEnergyScore", "low_support"])
    for rows in (predictions, scores):
        if rows["season"].gt(2025).any() or rows.duplicated(["game_id", "arm"]).any():
            raise ValueError("Future season or duplicate arm/game identity")
    by_key = {}
    for row in effects:
        key = (str(row["period"]), row["subgroup"], row["reference"], row["arm"])
        if key in by_key:
            raise ValueError("Duplicate paired effect")
        by_key[key] = row
    # Reconcile the plotted annual means and counts with per-game evidence.
    for year in range(2017, 2026):
        year_rows = scores.loc[scores.season.eq(year)]
        reference = year_rows.loc[year_rows.arm.eq("baseline")].set_index("game_id")
        for arm in ARMS:
            candidate = year_rows.loc[year_rows.arm.eq(arm)].set_index("game_id")
            if set(candidate.index) != set(reference.index) or reference.empty:
                raise ValueError(f"Common scored population mismatch: {year} {arm}")
            paired = by_key[(str(year), "overall", "baseline", arm)]
            if paired["method"] != METHOD or paired["games"] != len(reference):
                raise ValueError("Unexpected uncertainty method or paired denominator")
            actual = candidate.loc[reference.index, METRIC].to_numpy() - reference[METRIC].to_numpy()
            if not np.isclose(actual.mean(), paired["metrics"][METRIC]["delta"], rtol=0, atol=1e-10):
                raise ValueError("Paired effect does not reconcile with per-game scores")
            summary = comparison.loc[comparison.period.eq(str(year)) & comparison.subgroup.eq("overall") & comparison.arm.eq(arm)]
            if len(summary) != 1 or int(summary.iloc[0].games) != len(candidate) or not np.isclose(summary.iloc[0][METRIC], candidate[METRIC].mean(), rtol=0, atol=1e-10):
                raise ValueError("Comparison table does not reconcile with per-game scores")
    return frozen, comparison, by_key, predictions, scores


def effect(effects: dict, period: str, subgroup: str, arm: str) -> dict:
    row = effects[(period, subgroup, "baseline", arm)]
    if row["method"] != METHOD or row["direction"] != "CANDIDATE_MINUS_BASELINE":
        raise ValueError("Unrecognized effect direction or uncertainty method")
    value = row["metrics"][METRIC]
    if not np.isfinite([value["delta"], value["low95"], value["high95"]]).all() or value["low95"] > value["high95"]:
        raise ValueError("Invalid energy estimate/interval")
    return row


def energy_limits(rows: list[dict], pad_fraction: float = 0.10) -> tuple[float, float]:
    low = min(0.0, *(row["metrics"][METRIC]["low95"] for row in rows))
    high = max(0.0, *(row["metrics"][METRIC]["high95"] for row in rows))
    padding = max((high - low) * pad_fraction, .01)
    return low - padding, high + padding


def clean_axis(axis, grid_axis="x"):
    axis.grid(axis=grid_axis, color=GRID, linewidth=.65, zorder=0)
    axis.set_axisbelow(True)


def save_figure(fig, directory: Path, stem: str) -> list[dict]:
    files = []
    for extension in ("png", "svg"):
        path = directory / f"{stem}.{extension}"
        metadata = {"Creator": "ASP Model Studio CFB research", "Date": None} if extension == "svg" else {"Software": "ASP Model Studio CFB research"}
        fig.savefig(path, dpi=180, metadata=metadata)
        files.append(binding(path))
    plt.close(fig)
    return files


def forest(effects, frozen, directory):
    periods = [("reused_validation", "Reused validation · 2023–24"), ("reused_2025", "Secondary reused assessment · 2025")]
    groups = [("overall", "Overall"), ("low_support", "Predeclared low support")]
    all_rows = [effect(effects, period, subgroup, arm) for period, _ in periods for subgroup, _ in groups for arm in ARMS]
    limits = energy_limits(all_rows)
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 10.5), sharex=True, sharey=True)
    fig.subplots_adjust(left=.205, right=.975, bottom=.175, top=.815, wspace=.14, hspace=.61)
    fig.suptitle("CFB strength: paired distribution effects", x=.035, ha="left", y=.969, fontsize=23, fontweight="bold")
    fig.text(.035, .923, f"Frozen Development choice: {frozen['selectedArm']}  |  prior precision λ = {frozen['lambdaPrior']:g}", fontsize=13)
    for r, (subgroup, group_label) in enumerate(groups):
        for c, (period, period_label) in enumerate(periods):
            axis = axes[r, c]
            rows = [effect(effects, period, subgroup, arm) for arm in ARMS]
            if len({(row["games"], row["blocks"]) for row in rows}) != 1:
                raise ValueError("Forest panels need common arm denominators")
            for y, (arm, row) in enumerate(zip(ARMS, rows)):
                estimate = row["metrics"][METRIC]
                face = "white" if arm.startswith("U_") else COLORS[arm]
                axis.hlines(y, estimate["low95"], estimate["high95"], color=COLORS[arm], linewidth=2.2, zorder=2)
                axis.plot(estimate["delta"], y, marker=MARKERS[arm], markersize=8, color=COLORS[arm], markerfacecolor=face, markeredgewidth=1.8, zorder=3)
            axis.axvline(0, color=INK, linewidth=1.15)
            axis.set_xlim(limits)
            axis.set_ylim(3.6, -.6)
            axis.set_yticks(range(4), [LABELS[arm] for arm in ARMS])
            axis.set_title(f"{period_label}\n{group_label} · n = {rows[0]['games']:,} games / {rows[0]['blocks']} weeks", loc="left", pad=17, fontsize=13)
            clean_axis(axis)
            if r == 1:
                axis.set_xlabel("Δ joint energy score (candidate − baseline)", labelpad=12)
    fig.text(.035, .10, "Left of zero is better. Bars: 95% paired calendar-week block bootstrap intervals, stratified by season; 2,000 resamples.", fontsize=11.5)
    fig.text(.035, .066, "Low support: scheduled week ≤3 OR either team has <2 eligible current-season games. Intervals are not multiplicity-adjusted.", fontsize=11.5)
    fig.text(.035, .032, CAUTION, fontsize=11, color="#58636D")
    return save_figure(fig, directory, "01-paired-energy-effects")


def season_stability(effects, directory):
    years = list(range(2017, 2026))
    all_rows = [effect(effects, str(year), "overall", arm) for arm in ARMS for year in years]
    limits = energy_limits(all_rows, .14)
    fig, axes = plt.subplots(2, 2, figsize=(16, 11), sharex=True, sharey=True)
    fig.subplots_adjust(left=.08, right=.98, bottom=.17, top=.83, wspace=.13, hspace=.45)
    fig.suptitle("CFB strength: stability across seasons", x=.035, ha="left", y=.963, fontsize=23, fontweight="bold")
    fig.text(.035, .918, "Paired joint energy score change versus the same-origin Gen1 baseline. Negative values favor the challenger.", fontsize=13)
    for axis, arm in zip(axes.flat, ARMS):
        rows = [effect(effects, str(year), "overall", arm) for year in years]
        means = np.array([row["metrics"][METRIC]["delta"] for row in rows])
        lows = np.array([row["metrics"][METRIC]["low95"] for row in rows])
        highs = np.array([row["metrics"][METRIC]["high95"] for row in rows])
        axis.axvspan(2022.5, 2024.5, color="#ECEFF2", alpha=.85, zorder=0)
        axis.axvspan(2024.5, 2025.45, color="#F6F1E6", alpha=.9, zorder=0)
        axis.axhline(0, color=INK, linewidth=1.1)
        axis.vlines(years, lows, highs, color=COLORS[arm], linewidth=1.6)
        axis.plot(years, means, marker=MARKERS[arm], color=COLORS[arm], markerfacecolor="white" if arm.startswith("U_") else COLORS[arm], markersize=6.5, linewidth=1.7)
        axis.set_ylim(limits)
        axis.set_xlim(2016.55, 2025.45)
        axis.set_xticks(years, [f"{year}\nn={row['games']}" for year, row in zip(years, rows)])
        axis.tick_params(axis="x", labelbottom=True, labelsize=10)
        axis.set_title(LABELS[arm], loc="left", pad=13, fontweight="bold")
        clean_axis(axis, "y")
    axes[0, 0].set_ylabel("Δ joint energy score")
    axes[1, 0].set_ylabel("Δ joint energy score")
    fig.text(.035, .105, "2017–22: nested Development choices. Grey: reused 2023–24 validation. Gold tint: secondary reused 2025 assessment.", fontsize=11.5)
    fig.text(.035, .07, "Bars: 95% paired week-block intervals within each season. n counts common games, not 10,000 simulation draws per forecast.", fontsize=11.5)
    fig.text(.035, .035, CAUTION, fontsize=11, color="#58636D")
    return save_figure(fig, directory, "02-season-energy-stability")


def matched_predictions(predictions, scores):
    admitted_ids = set(scores.loc[scores.season.between(2023, 2025) & scores.arm.eq("baseline"), "game_id"])
    selected = predictions.loc[predictions.game_id.isin(admitted_ids) & predictions.season.between(2023, 2025)]
    frames = {arm: selected.loc[selected.arm.eq(arm)].set_index("game_id").sort_index() for arm in ("baseline", "A", "B")}
    if not all(set(frame.index) == admitted_ids for frame in frames.values()):
        raise ValueError("Forecast diagnostics require the common scored game population")
    for arm in ("A", "B"):
        if not np.isfinite(frames[arm][["pred_margin", "pred_total", "home_prior_weight", "away_prior_weight"]].to_numpy()).all():
            raise ValueError("Missing actual A/B prediction or prior-weight diagnostic")
        for key in ("home_current_support", "away_current_support", "low_support", "season"):
            if not frames["A"][key].equals(frames["B"][key]):
                raise ValueError("A/B diagnostic populations or support differ")
    return frames


def forecast_diagnostics(predictions, scores, directory):
    frames = matched_predictions(predictions, scores)
    count = len(frames["baseline"])
    fig, axes = plt.subplots(2, 2, figsize=(16, 11.5))
    fig.subplots_adjust(left=.085, right=.98, bottom=.155, top=.84, hspace=.43, wspace=.22)
    fig.suptitle("CFB strength: support and forecast changes", x=.035, ha="left", y=.968, fontsize=23, fontweight="bold")
    fig.text(.035, .922, f"Reused 2023–25 · {count:,} common games · actual fitted A/B point forecasts and strength diagnostics", fontsize=13)
    axis = axes[0, 0]
    for arm in ("A", "B"):
        frame = frames[arm]
        team_rows = pd.concat([frame[[f"{side}_current_support", f"{side}_prior_weight"]].rename(columns={f"{side}_current_support": "support", f"{side}_prior_weight": "weight"}) for side in ("home", "away")])
        means = team_rows.groupby("support").weight.mean()
        axis.plot(means.index, means.values, color=COLORS[arm], marker=MARKERS[arm], markersize=6, label=LABELS[arm])
    axis.set_title("Prior precision share as evidence accumulates", loc="left", pad=14, fontsize=14)
    axis.set_xlabel("Eligible current-season games for that team")
    axis.set_ylabel("Mean λeffective / (λeffective + support)")
    axis.set_ylim(0, 1.06)
    axis.xaxis.set_major_locator(MaxNLocator(integer=True))
    axis.legend(loc="upper right", frameon=False, fontsize=11)
    clean_axis(axis, "y")
    axis.text(.02, .05, "Two team rows per game; this is a precision diagnostic,\nnot a confidence interval or independent team sample.", transform=axis.transAxes, fontsize=10.5, color="#58636D")
    axis = axes[0, 1]
    support = frames["A"][["home_current_support", "away_current_support"]].min(axis=1)
    bins = pd.cut(support, [-.5, .5, 1.5, 3.5, 6.5, np.inf], labels=["0", "1", "2–3", "4–6", "7+"])
    diagnostics = pd.DataFrame({"support_band": bins,
                                "margin": (frames["B"].pred_margin - frames["A"].pred_margin).abs(),
                                "total": (frames["B"].pred_total - frames["A"].pred_total).abs()})
    summary = diagnostics.groupby("support_band", observed=False).agg(margin=("margin", "mean"), total=("total", "mean"), games=("margin", "size"))
    for key, label, color, marker in (("margin", "Margin", "#245B84", "o"), ("total", "Total", "#C47B38", "s")):
        axis.plot(range(len(summary)), summary[key], color=color, marker=marker, markersize=6, label=label)
    axis.set_xticks(range(len(summary)), [f"{band}\nn={int(row.games):,}" for band, row in summary.iterrows()])
    axis.set_ylim(bottom=0)
    axis.set_title("How much B changes A's forecasts", loc="left", pad=14, fontsize=14)
    axis.set_xlabel("Minimum eligible current games across the two teams")
    axis.set_ylabel("Mean absolute B − A change (points)")
    axis.legend(frameon=False, fontsize=11)
    clean_axis(axis, "y")
    shifts = {arm: pd.DataFrame({"margin": frames[arm].pred_margin - frames["baseline"].pred_margin,
                               "total": frames[arm].pred_total - frames["baseline"].pred_total}) for arm in ("A", "B")}
    xlim = max(float(frame.margin.abs().max()) for frame in shifts.values()) * 1.08
    ylim = max(float(frame.total.abs().max()) for frame in shifts.values()) * 1.08
    xlim, ylim = max(xlim, .1), max(ylim, .1)
    for axis, arm in zip(axes[1], ("A", "B")):
        frame = shifts[arm]
        axis.scatter(frame.margin, frame.total, s=10, alpha=.23, color=COLORS[arm], edgecolors="none", rasterized=True)
        axis.axhline(0, color=INK, linewidth=.9)
        axis.axvline(0, color=INK, linewidth=.9)
        axis.set_xlim(-xlim, xlim)
        axis.set_ylim(-ylim, ylim)
        axis.set_title(f"{arm} forecast changes versus Gen1", loc="left", pad=14, fontsize=14)
        axis.set_xlabel("Home-margin change (points)")
        axis.set_ylabel("Total-score change (points)")
        means = frame.abs().mean()
        axis.text(.025, .96, f"Mean |Δ margin| = {means.margin:.2f}\nMean |Δ total| = {means.total:.2f}\nEach dot is one common game", transform=axis.transAxes, va="top", fontsize=10.5,
                  bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85, "pad": 3})
        clean_axis(axis, "both")
    fig.text(.035, .087, "These panels describe forecast movement, not predictive improvement. The paired energy figures provide the outcome comparison.", fontsize=11.5)
    fig.text(.035, .047, CAUTION, fontsize=11, color="#58636D")
    summary.reset_index().to_csv(directory / "SUPPORT_FORECAST_CHANGE_SUMMARY.csv", index=False)
    return save_figure(fig, directory, "03-support-and-forecast-changes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    configure()
    frozen, comparison, effects, predictions, scores = load_completed(args.output)
    directory = args.output / "figures"
    directory.mkdir(exist_ok=True)
    files = []
    files.extend(forest(effects, frozen, directory))
    files.extend(season_stability(effects, directory))
    files.extend(forecast_diagnostics(predictions, scores, directory))
    receipt = {"schema": "CFB_STRENGTH_SCIENTIFIC_FIGURES_V1", "renderedAtUtc": datetime.now(timezone.utc).isoformat(),
               "sourceClass": "A_RECONSTRUCTED_HISTORICAL", "certifiedHistoricalAvailability": False,
               "laterEvidenceReused": True, "uncertaintyUnit": "PAIRED_CALENDAR_WEEK_BLOCKS_WITH_WHOLE_GAMES",
               "simulationDrawsTreatedAsIndependentObservations": False,
               "sourceFiles": [binding(args.output / name) for name in INPUT_NAMES], "figures": files,
               "sourceReconciliation": "ANNUAL_PAIRED_EFFECTS_AND_COMPARISON_MEANS_COUNTS_MATCH_PER_GAME_SCORES",
               "diagnosticSummary": binding(directory / "SUPPORT_FORECAST_CHANGE_SUMMARY.csv")}
    (directory / "FIGURES.json").write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    print(json.dumps({"figures": files, "receipt": str(directory / "FIGURES.json")}, indent=2))


if __name__ == "__main__":
    main()
