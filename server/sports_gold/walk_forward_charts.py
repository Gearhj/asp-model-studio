"""Deterministic review charts for the recent-data walk-forward study.

The chart layer consumes only compact aggregate records produced by the study.
It never opens governed row data, fits a model, or participates in candidate
selection.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


SCHEMA_VERSION = "MLB_GOLD_RECENT_DATA_WALK_FORWARD_CHARTS_V1"
DIRECT = "DIRECT_GOLD"
NULL = "CLASS_FREQUENCY_NULL"
BASE = "MATCHED_BASE"

_COLORS = {
    "direct": "#264653",
    "selected": "#e76f51",
    "null": "#8d99ae",
    "base": "#2a9d8f",
    "positive": "#2a9d8f",
    "negative": "#e76f51",
}


class WalkForwardChartError(RuntimeError):
    """Raised when compact chart inputs are missing or malformed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value: Any, *, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise WalkForwardChartError(f"{label} must be numeric") from exc
    if not math.isfinite(parsed):
        raise WalkForwardChartError(f"{label} must be finite")
    return parsed


def _rows(result: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    tables = result.get("tables")
    if not isinstance(tables, Mapping):
        raise WalkForwardChartError("results tables are missing")
    raw = tables.get(key)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise WalkForwardChartError(f"table {key!r} is missing or empty")
    output = list(raw)
    if not all(isinstance(item, Mapping) for item in output):
        raise WalkForwardChartError(f"table {key!r} contains a non-record")
    return output


def _display(name: str) -> str:
    return name.replace("_", " ").title()


def _save(fig: Any, output_dir: Path, chart_id: str, title: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    metadata = {"Creator": "ASP Model Studio", "Date": None}
    for extension in ("png", "svg"):
        path = output_dir / f"{chart_id}.{extension}"
        fig.savefig(
            path,
            format=extension,
            dpi=170,
            bbox_inches="tight",
            metadata=metadata,
        )
        files.append(
            {
                "format": extension.upper(),
                "path": str(path.resolve()),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    plt.close(fig)
    return {"chartId": chart_id, "title": title, "files": files}


def plot_sorted_improvement(
    result: Mapping[str, Any], output_dir: Path
) -> dict[str, Any]:
    rows = sorted(
        _rows(result, "candidate-performance"),
        key=lambda item: _finite(
            item.get("logLossImprovementVsDirect"), label="candidate improvement"
        ),
    )
    labels = [str(item.get("candidateId", "")) for item in rows]
    if any(not label for label in labels) or len(set(labels)) != len(labels):
        raise WalkForwardChartError("candidate identities are missing or duplicated")
    values = np.asarray(
        [
            _finite(item.get("logLossImprovementVsDirect"), label=label)
            for item, label in zip(rows, labels, strict=True)
        ],
        dtype=np.float64,
    )
    height = max(5.0, 0.30 * len(rows) + 1.8)
    fig, ax = plt.subplots(figsize=(10.5, height), constrained_layout=True)
    colors = [
        _COLORS["positive"] if value >= 0.0 else _COLORS["negative"] for value in values
    ]
    positions = np.arange(len(values))
    ax.barh(positions, values, color=colors, alpha=0.88)
    ax.axvline(0.0, color="#343a40", linewidth=0.9)
    ax.set_yticks(positions, [_display(value) for value in labels])
    ax.set_xlabel("2024 holdout log-loss improvement vs Direct Gold")
    ax.set_title("Walk-forward candidate improvement on the final two weeks")
    ax.grid(axis="x", color="#ced4da", linewidth=0.55, alpha=0.65)
    span = max(float(np.max(np.abs(values))), 1e-5)
    for position, value in zip(positions, values, strict=True):
        ax.text(
            value + (0.018 * span if value >= 0 else -0.018 * span),
            position,
            f"{value:+.6f}",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=8,
        )
    return _save(fig, output_dir, "sorted-improvement-vs-direct", ax.get_title())


def plot_daily_performance(
    result: Mapping[str, Any], output_dir: Path
) -> dict[str, Any]:
    selected = str(result.get("selectedOofEnsemble", ""))
    if not selected:
        raise WalkForwardChartError("selected OOF ensemble is missing")
    wanted = (NULL, BASE, DIRECT, selected)
    rows = _rows(result, "daily-performance")
    fig, ax = plt.subplots(figsize=(11.5, 5.4), constrained_layout=True)
    palette = {
        NULL: _COLORS["null"],
        BASE: _COLORS["base"],
        DIRECT: _COLORS["direct"],
        selected: _COLORS["selected"],
    }
    for candidate in wanted:
        selected_rows = sorted(
            (item for item in rows if item.get("candidateId") == candidate),
            key=lambda item: str(item.get("scoreDate", "")),
        )
        if not selected_rows:
            raise WalkForwardChartError(f"daily series missing for {candidate}")
        dates = [str(item["scoreDate"])[5:] for item in selected_rows]
        values = [
            _finite(item.get("logLoss"), label=f"{candidate} daily log loss")
            for item in selected_rows
        ]
        ax.plot(
            dates,
            values,
            marker="o",
            markersize=3.2,
            linewidth=1.7 if candidate in {DIRECT, selected} else 1.1,
            color=palette[candidate],
            label=_display(candidate),
        )
    ax.set_xlabel("2024 score date (MM-DD)")
    ax.set_ylabel("Multiclass log loss")
    ax.set_title("Daily final-holdout performance")
    ax.grid(color="#dee2e6", linewidth=0.55, alpha=0.7)
    ax.legend(frameon=False, ncol=2)
    ax.tick_params(axis="x", rotation=45)
    return _save(fig, output_dir, "daily-holdout-performance", ax.get_title())


def plot_coverage_by_date(
    result: Mapping[str, Any], output_dir: Path
) -> dict[str, Any]:
    rows = _rows(result, "coverage-by-date")
    component_order = result.get("request", {}).get("components")
    if not isinstance(component_order, Sequence) or isinstance(
        component_order, (str, bytes)
    ):
        raise WalkForwardChartError("component order is missing")
    components = [str(item) for item in component_order if str(item) != DIRECT]
    fig, (coverage_ax, ess_ax) = plt.subplots(
        2, 1, figsize=(12.0, 8.0), sharex=True, constrained_layout=True
    )
    cmap = plt.get_cmap("tab10")
    for index, component in enumerate(components):
        selected_rows = sorted(
            (item for item in rows if item.get("componentId") == component),
            key=lambda item: str(item.get("scoreDate", "")),
        )
        if not selected_rows:
            raise WalkForwardChartError(f"coverage series missing for {component}")
        dates = [str(item["scoreDate"])[5:] for item in selected_rows]
        coverage = [
            _finite(item.get("coverage"), label=f"{component} coverage")
            for item in selected_rows
        ]
        ess = [
            _finite(item.get("effectiveSampleSizeMean"), label=f"{component} ESS")
            for item in selected_rows
        ]
        color = cmap(index % 10)
        coverage_ax.plot(
            dates, coverage, color=color, linewidth=1.4, label=_display(component)
        )
        ess_ax.plot(dates, ess, color=color, linewidth=1.4)
    coverage_ax.set_ylabel("Coverage share")
    coverage_ax.set_ylim(-0.02, 1.02)
    coverage_ax.set_title("Empirical-component coverage by holdout date")
    coverage_ax.grid(color="#dee2e6", linewidth=0.5, alpha=0.7)
    coverage_ax.legend(frameon=False, ncol=3, fontsize=7)
    ess_ax.set_xlabel("2024 score date (MM-DD)")
    ess_ax.set_ylabel("Mean effective sample size")
    ess_ax.grid(color="#dee2e6", linewidth=0.5, alpha=0.7)
    ess_ax.tick_params(axis="x", rotation=45)
    return _save(fig, output_dir, "component-coverage-by-date", coverage_ax.get_title())


def plot_ensemble_summary(
    result: Mapping[str, Any], output_dir: Path
) -> dict[str, Any]:
    rows = _rows(result, "ensemble-weights-gating")
    components = [str(item.get("componentId", "")) for item in rows]
    if any(not item for item in components) or len(set(components)) != len(components):
        raise WalkForwardChartError("ensemble weight component identities are invalid")
    static = np.asarray(
        [_finite(item.get("e9Weight"), label="E9 weight") for item in rows]
    )
    gated = np.asarray(
        [
            _finite(item.get("e10CoefficientImportance"), label="E10 importance")
            for item in rows
        ]
    )
    positions = np.arange(len(components))
    fig, axes = plt.subplots(
        1, 2, figsize=(13.0, 5.5), sharey=True, constrained_layout=True
    )
    axes[0].barh(positions, static, color=_COLORS["base"], alpha=0.9)
    axes[1].barh(positions, gated, color=_COLORS["selected"], alpha=0.9)
    axes[0].set_yticks(positions, [_display(item) for item in components])
    axes[0].set_xlabel("Convex probability weight")
    axes[0].set_title("E9 development-optimized static blend")
    axes[1].set_xlabel("Normalized coefficient magnitude")
    axes[1].set_title("E10 reliability-gating importance")
    for ax in axes:
        ax.grid(axis="x", color="#dee2e6", linewidth=0.55, alpha=0.7)
    fig.suptitle("Frozen ensemble weight and gating summary")
    return _save(
        fig, output_dir, "ensemble-weight-gating-summary", fig._suptitle.get_text()
    )


def generate_walk_forward_charts(
    result: Mapping[str, Any], output_dir: Path
) -> list[dict[str, Any]]:
    """Generate the four fixed Phase 7B5 review charts as PNG and SVG."""

    if not isinstance(result, Mapping):
        raise TypeError("results must be a mapping")
    output = Path(output_dir)
    matplotlib.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 12,
            "axes.labelsize": 9,
            "svg.hashsalt": "phase7b5-walk-forward",
        }
    )
    return [
        plot_sorted_improvement(result, output),
        plot_daily_performance(result, output),
        plot_coverage_by_date(result, output),
        plot_ensemble_summary(result, output),
    ]


__all__ = [
    "SCHEMA_VERSION",
    "WalkForwardChartError",
    "generate_walk_forward_charts",
    "plot_coverage_by_date",
    "plot_daily_performance",
    "plot_ensemble_summary",
    "plot_sorted_improvement",
]
