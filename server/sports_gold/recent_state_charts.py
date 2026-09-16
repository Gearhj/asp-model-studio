"""Deterministic review charts for the Phase 7B4 PA ensemble study.

The plotting layer consumes only machine-result dictionaries.  It does not read
Gold/Silver data, fit models, or reinterpret experiment results.  The canonical
input contract used by :func:`generate_review_charts` is::

    {
        "direct2024LogLoss": 1.4778,
        "candidate2024": [
            {
                "candidate": "DIRECT_MODEL",
                "logLoss": 1.4778,
                "components": ["DIRECT_MODEL"],
            },
            ...
        ],
        "monthly2024": [
            {"month": "2024-03", "candidate": "DIRECT_MODEL", "logLoss": 1.48},
            ...
        ],
        "calibration2024": {
            "directCandidate": "DIRECT_MODEL",
            "bestCandidate": "E10_RELIABILITY_GATED_RESIDUAL_STACKER",
            "curves": {
                "DIRECT_MODEL": [
                    {
                        "meanConfidence": 0.31,
                        "observedAccuracy": 0.29,
                        "count": 1000,
                    },
                    ...
                ],
                ...
            },
        },
        "ensembleWeights": {
            "optimizedStatic": {"DIRECT_MODEL": 0.8, ...},
            "averageGated": {"DIRECT_MODEL": 0.7, ...},
        },
        "disagreement2024": [
            {
                "bin": "Q1 (lowest)",
                "directLogLoss": 1.45,
                "bestLogLoss": 1.44,
                "count": 36000,
            },
            ...
        ],
        "topFourCandidates": ["E1", "E3", "E9", "E10"],  # optional
        "bestCandidate": "E10",                             # optional
    }

Snake-case spellings are accepted for the public fields.  The explicit schema
keeps chart generation separate from statistical selection: if a required
series is absent or malformed, charting fails with :class:`ChartInputError`
instead of silently inventing or dropping evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import math
import os
from pathlib import Path
import tempfile
from typing import Any

import matplotlib

# This module is also used by non-interactive PowerShell research runners.
# Select the backend before importing pyplot so it never requires a desktop.
matplotlib.use("Agg", force=True)
matplotlib.rcParams["svg.hashsalt"] = "asp-model-studio-phase7b4"

from matplotlib import pyplot as plt  # noqa: E402  (backend selected above)
from matplotlib.colors import ListedColormap  # noqa: E402
import numpy as np  # noqa: E402


DIRECT_MODEL = "DIRECT_MODEL"

SIGNAL_COMPONENT_ORDER: tuple[str, ...] = (
    "DIRECT_MODEL",
    "LONG_TERM_STATE",
    "RECENT_14_DAY_STATE",
    "RECENT_42_DAY_STATE",
    "DECAY_180_DAY_STATE",
    "DECAY_365_DAY_STATE",
    "CLUSTER_MATCHUP",
    "SHRUNK_EXACT_BVP",
    "RECENT_RESIDUAL_FORM",
)

_MISSING = object()
_NO_DEFAULT = object()


class ChartInputError(ValueError):
    """Raised when a required machine-result chart input is missing or invalid."""


def _field(
    value: Mapping[str, Any],
    *names: str,
    default: Any = _NO_DEFAULT,
    context: str = "result",
) -> Any:
    for name in names:
        if name in value:
            return value[name]
    if default is not _NO_DEFAULT:
        return default
    joined = " or ".join(repr(name) for name in names)
    raise ChartInputError(f"{context} is missing required field {joined}")


def _mapping(value: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ChartInputError(f"{context} must be an object/mapping")
    return value


def _rows(value: Any, *, context: str) -> list[Mapping[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ChartInputError(f"{context} must be a non-empty list of row objects")
    if not value:
        raise ChartInputError(f"{context} must not be empty")
    output: list[Mapping[str, Any]] = []
    for index, row in enumerate(value):
        output.append(_mapping(row, context=f"{context}[{index}]"))
    return output


def _name(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ChartInputError(f"{context} must be a non-empty string")
    return value.strip()


def _finite(value: Any, *, context: str, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ChartInputError(f"{context} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ChartInputError(f"{context} must be a finite number") from exc
    if not math.isfinite(number):
        raise ChartInputError(f"{context} must be finite")
    if minimum is not None and number < minimum:
        raise ChartInputError(f"{context} must be >= {minimum}")
    return number


def _probability(value: Any, *, context: str) -> float:
    number = _finite(value, context=context)
    if not 0.0 <= number <= 1.0:
        raise ChartInputError(f"{context} must be in [0, 1]")
    return number


def _nested_metric(row: Mapping[str, Any], *names: str, context: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    for container_name in (
        "metrics2024",
        "metrics_2024",
        "validation2024",
        "validation_2024",
        "metrics",
    ):
        nested = row.get(container_name)
        if isinstance(nested, Mapping):
            for name in names:
                if name in nested:
                    return nested[name]
    joined = " or ".join(repr(name) for name in names)
    raise ChartInputError(f"{context} is missing required metric {joined}")


def _candidate_source(results: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in (
        "candidate2024",
        "candidate_2024",
        "candidates2024",
        "candidates_2024",
    ):
        if key in results:
            return _rows(results[key], context=key)

    combined: list[Mapping[str, Any]] = []
    for key in (
        "standaloneLeaderboard",
        "standalone_leaderboard",
        "ensembleLeaderboard",
        "ensemble_leaderboard",
    ):
        if key in results:
            combined.extend(_rows(results[key], context=key))
    if not combined:
        tables = results.get("tables")
        if isinstance(tables, Mapping):
            for key in (
                "standaloneLeaderboard",
                "standalone_leaderboard",
                "ensembleLeaderboard",
                "ensemble_leaderboard",
            ):
                if key in tables:
                    combined.extend(_rows(tables[key], context=f"tables.{key}"))
    if not combined:
        raise ChartInputError(
            "result must contain candidate2024 or standalone/ensemble leaderboard rows"
        )
    return combined


def _candidate_records(results: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(_candidate_source(results)):
        context = f"candidate row {index}"
        candidate = _name(
            _field(row, "candidate", "candidateName", "candidate_name", "name", context=context),
            context=f"{context}.candidate",
        )
        if candidate in seen:
            raise ChartInputError(f"candidate2024 contains duplicate candidate {candidate!r}")
        seen.add(candidate)
        log_loss = _finite(
            _nested_metric(
                row,
                "logLoss",
                "log_loss",
                "multiclassLogLoss",
                "multiclass_log_loss",
                context=context,
            ),
            context=f"{context}.logLoss",
            minimum=0.0,
        )
        component_value = _field(
            row,
            "components",
            "includedComponents",
            "included_components",
            default=[DIRECT_MODEL] if candidate == DIRECT_MODEL else _MISSING,
            context=context,
        )
        if component_value is _MISSING:
            raise ChartInputError(
                f"{context} must declare components; charting will not infer ensemble composition"
            )
        if isinstance(component_value, (str, bytes)) or not isinstance(
            component_value, Sequence
        ):
            raise ChartInputError(f"{context}.components must be a non-empty string list")
        components = [
            _name(item, context=f"{context}.components[{component_index}]")
            for component_index, item in enumerate(component_value)
        ]
        if not components:
            raise ChartInputError(f"{context}.components must not be empty")
        if len(components) != len(set(components)):
            raise ChartInputError(f"{context}.components contains duplicates")
        records.append(
            {"candidate": candidate, "logLoss": log_loss, "components": components}
        )
    if DIRECT_MODEL not in seen:
        raise ChartInputError("candidate2024 must include DIRECT_MODEL")
    if len(records) < 2:
        raise ChartInputError("candidate2024 must include at least one alternative")
    return records


def _direct_log_loss(
    results: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
) -> float:
    explicit = _field(
        results,
        "direct2024LogLoss",
        "direct_2024_log_loss",
        default=_MISSING,
    )
    row_value = next(
        float(row["logLoss"]) for row in records if row["candidate"] == DIRECT_MODEL
    )
    if explicit is _MISSING:
        return row_value
    explicit_value = _finite(
        explicit, context="direct2024LogLoss", minimum=0.0
    )
    if not math.isclose(explicit_value, row_value, rel_tol=0.0, abs_tol=1e-12):
        raise ChartInputError(
            "direct2024LogLoss disagrees with the DIRECT_MODEL candidate row"
        )
    return explicit_value


def _best_candidate(
    results: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
) -> str:
    explicit = _field(
        results,
        "bestCandidate",
        "best_candidate",
        "bestEnsemble",
        "best_ensemble",
        default=_MISSING,
    )
    candidates = {str(row["candidate"]) for row in records}
    if explicit is not _MISSING:
        name = _name(explicit, context="bestCandidate")
        if name not in candidates:
            raise ChartInputError(f"bestCandidate {name!r} is absent from candidate2024")
        if name == DIRECT_MODEL:
            raise ChartInputError("bestCandidate must name an alternative, not DIRECT_MODEL")
        return name
    alternatives = [row for row in records if row["candidate"] != DIRECT_MODEL]
    return str(min(alternatives, key=lambda row: (row["logLoss"], row["candidate"]))["candidate"])


def _ordered_components(records: Sequence[Mapping[str, Any]]) -> list[str]:
    present = {component for row in records for component in row["components"]}
    known = [component for component in SIGNAL_COMPONENT_ORDER if component in present]
    extras = sorted(present.difference(SIGNAL_COMPONENT_ORDER))
    return known + extras


def _section(results: Mapping[str, Any], *names: str, context: str) -> Any:
    direct = _field(results, *names, default=_MISSING)
    if direct is not _MISSING:
        return direct
    tables = results.get("tables")
    if isinstance(tables, Mapping):
        nested = _field(tables, *names, default=_MISSING)
        if nested is not _MISSING:
            return nested
    raise ChartInputError(
        f"result is missing required {context} section ({' or '.join(names)})"
    )


def _monthly_records(results: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = _section(
        results,
        "monthly2024",
        "monthly_2024",
        "monthlyStability",
        "monthly_stability",
        context="monthly stability",
    )
    output: list[dict[str, Any]] = []
    if isinstance(raw, Mapping):
        for candidate, series in raw.items():
            candidate_name = _name(candidate, context="monthly candidate")
            series_map = _mapping(series, context=f"monthly2024.{candidate_name}")
            for month, value in series_map.items():
                metric = value
                if isinstance(value, Mapping):
                    metric = _nested_metric(
                        value, "logLoss", "log_loss", context=f"monthly {candidate_name}/{month}"
                    )
                output.append(
                    {
                        "month": _name(str(month), context="monthly month"),
                        "candidate": candidate_name,
                        "logLoss": _finite(
                            metric,
                            context=f"monthly {candidate_name}/{month}.logLoss",
                            minimum=0.0,
                        ),
                    }
                )
    else:
        for index, row in enumerate(_rows(raw, context="monthly2024")):
            context = f"monthly2024[{index}]"
            output.append(
                {
                    "month": _name(
                        _field(row, "month", "monthLabel", "month_label", context=context),
                        context=f"{context}.month",
                    ),
                    "candidate": _name(
                        _field(
                            row,
                            "candidate",
                            "candidateName",
                            "candidate_name",
                            "name",
                            context=context,
                        ),
                        context=f"{context}.candidate",
                    ),
                    "logLoss": _finite(
                        _nested_metric(row, "logLoss", "log_loss", context=context),
                        context=f"{context}.logLoss",
                        minimum=0.0,
                    ),
                }
            )
    if not output:
        raise ChartInputError("monthly2024 must not be empty")
    pairs = [(row["candidate"], row["month"]) for row in output]
    if len(pairs) != len(set(pairs)):
        raise ChartInputError("monthly2024 contains duplicate candidate/month rows")
    return output


def _top_four_candidates(
    results: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
) -> list[str]:
    explicit = _field(
        results,
        "topFourCandidates",
        "top_four_candidates",
        default=_MISSING,
    )
    known = {str(row["candidate"]) for row in records}
    if explicit is not _MISSING:
        if isinstance(explicit, (str, bytes)) or not isinstance(explicit, Sequence):
            raise ChartInputError("topFourCandidates must be a list of four candidate names")
        selected = [
            _name(item, context=f"topFourCandidates[{index}]")
            for index, item in enumerate(explicit)
        ]
        if len(selected) != 4 or len(set(selected)) != 4:
            raise ChartInputError("topFourCandidates must contain exactly four unique names")
        if DIRECT_MODEL in selected:
            raise ChartInputError("topFourCandidates must not contain DIRECT_MODEL")
        missing = set(selected).difference(known)
        if missing:
            raise ChartInputError(
                f"topFourCandidates contains unknown candidates: {sorted(missing)}"
            )
        return selected
    alternatives = sorted(
        (row for row in records if row["candidate"] != DIRECT_MODEL),
        key=lambda row: (row["logLoss"], row["candidate"]),
    )
    if len(alternatives) < 4:
        raise ChartInputError(
            "monthly chart requires at least four alternatives in candidate2024"
        )
    return [str(row["candidate"]) for row in alternatives[:4]]


def _calibration_curves(
    results: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> tuple[str, str, dict[str, list[dict[str, float]]]]:
    raw = _mapping(
        _section(
            results,
            "calibration2024",
            "calibration_2024",
            "reliability2024",
            "reliability_2024",
            context="calibration/reliability",
        ),
        context="calibration2024",
    )
    direct_name = _name(
        _field(
            raw,
            "directCandidate",
            "direct_candidate",
            default=DIRECT_MODEL,
        ),
        context="calibration2024.directCandidate",
    )
    best_name = _name(
        _field(
            raw,
            "bestCandidate",
            "best_candidate",
            default=_best_candidate(results, records),
        ),
        context="calibration2024.bestCandidate",
    )
    curve_value = _field(raw, "curves", "series", context="calibration2024")
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    if isinstance(curve_value, Mapping):
        for candidate, rows in curve_value.items():
            grouped[_name(candidate, context="calibration curve candidate")] = _rows(
                rows, context=f"calibration curve {candidate}"
            )
    else:
        for index, row in enumerate(_rows(curve_value, context="calibration curves")):
            candidate = _name(
                _field(
                    row,
                    "candidate",
                    "candidateName",
                    "candidate_name",
                    context=f"calibration curves[{index}]",
                ),
                context=f"calibration curves[{index}].candidate",
            )
            grouped.setdefault(candidate, []).append(row)
    for required in (direct_name, best_name):
        if required not in grouped:
            raise ChartInputError(
                f"calibration2024.curves is missing required candidate {required!r}"
            )
    normalized: dict[str, list[dict[str, float]]] = {}
    for candidate in (direct_name, best_name):
        points: list[dict[str, float]] = []
        for index, row in enumerate(grouped[candidate]):
            context = f"calibration {candidate}[{index}]"
            confidence = _probability(
                _field(
                    row,
                    "meanConfidence",
                    "mean_confidence",
                    "confidence",
                    "meanPredicted",
                    "mean_predicted",
                    context=context,
                ),
                context=f"{context}.meanConfidence",
            )
            observed = _probability(
                _field(
                    row,
                    "observedAccuracy",
                    "observed_accuracy",
                    "empiricalAccuracy",
                    "empirical_accuracy",
                    "accuracy",
                    "fractionPositive",
                    "fraction_positive",
                    context=context,
                ),
                context=f"{context}.observedAccuracy",
            )
            count = _finite(
                _field(row, "count", "rowCount", "row_count", default=1),
                context=f"{context}.count",
                minimum=0.0,
            )
            points.append(
                {
                    "meanConfidence": confidence,
                    "observedAccuracy": observed,
                    "count": count,
                }
            )
        if len(points) < 2:
            raise ChartInputError(
                f"calibration curve {candidate!r} requires at least two populated bins"
            )
        normalized[candidate] = sorted(points, key=lambda point: point["meanConfidence"])
    return direct_name, best_name, normalized


def _weight_mapping(value: Any, *, context: str) -> dict[str, float]:
    output: dict[str, float] = {}
    if isinstance(value, Mapping):
        items = value.items()
    else:
        rows = _rows(value, context=context)
        items = (
            (
                _field(row, "component", "signal", "name", context=f"{context}[{index}]"),
                _field(row, "weight", "value", context=f"{context}[{index}]"),
            )
            for index, row in enumerate(rows)
        )
    for raw_name, raw_weight in items:
        name = _name(raw_name, context=f"{context} component")
        if name in output:
            raise ChartInputError(f"{context} contains duplicate component {name!r}")
        output[name] = _finite(
            raw_weight, context=f"{context}.{name}", minimum=0.0
        )
    if not output:
        raise ChartInputError(f"{context} must not be empty")
    total = sum(output.values())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise ChartInputError(f"{context} weights must sum to 1; observed {total:.12g}")
    return output


def _weights(results: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    raw = _mapping(
        _section(
            results,
            "ensembleWeights",
            "ensemble_weights",
            "finalEnsembleWeights",
            "final_ensemble_weights",
            context="ensemble weights",
        ),
        context="ensembleWeights",
    )
    # Also accept the convenient row-wise table form:
    # [{component, optimizedStatic, averageGated}, ...].
    if "rows" in raw:
        rows = _rows(raw["rows"], context="ensembleWeights.rows")
        static_value = {
            _field(row, "component", "signal", "name", context="weight row"):
            _field(row, "optimizedStatic", "optimized_static", context="weight row")
            for row in rows
        }
        gated_value = {
            _field(row, "component", "signal", "name", context="weight row"):
            _field(row, "averageGated", "average_gated", context="weight row")
            for row in rows
        }
    else:
        static_value = _field(
            raw,
            "optimizedStatic",
            "optimized_static",
            "static",
            context="ensembleWeights",
        )
        gated_value = _field(
            raw,
            "averageGated",
            "average_gated",
            "gatedAverage",
            "gated_average",
            context="ensembleWeights",
        )
    return (
        _weight_mapping(static_value, context="optimized static weights"),
        _weight_mapping(gated_value, context="average gated weights"),
    )


def _disagreement_records(results: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = _section(
        results,
        "disagreement2024",
        "disagreement_2024",
        "disagreementPerformance",
        "disagreement_performance",
        context="disagreement performance",
    )
    output: list[dict[str, Any]] = []
    for index, row in enumerate(_rows(raw, context="disagreement2024")):
        context = f"disagreement2024[{index}]"
        direct = _finite(
            _field(row, "directLogLoss", "direct_log_loss", context=context),
            context=f"{context}.directLogLoss",
            minimum=0.0,
        )
        best_raw = _field(
            row,
            "bestLogLoss",
            "best_log_loss",
            "candidateLogLoss",
            "candidate_log_loss",
            default=_MISSING,
        )
        if best_raw is _MISSING:
            improvement = _finite(
                _field(
                    row,
                    "improvement",
                    "logLossImprovement",
                    "log_loss_improvement",
                    context=context,
                ),
                context=f"{context}.improvement",
            )
            best = direct - improvement
            if best < 0.0:
                raise ChartInputError(f"{context} implies a negative best log loss")
        else:
            best = _finite(
                best_raw, context=f"{context}.bestLogLoss", minimum=0.0
            )
        output.append(
            {
                "bin": _name(
                    _field(row, "bin", "binLabel", "bin_label", context=context),
                    context=f"{context}.bin",
                ),
                "directLogLoss": direct,
                "bestLogLoss": best,
                "count": _finite(
                    _field(row, "count", "rowCount", "row_count", context=context),
                    context=f"{context}.count",
                    minimum=0.0,
                ),
            }
        )
    if len(output) < 2:
        raise ChartInputError("disagreement2024 requires at least two populated bins")
    bins = [str(row["bin"]) for row in output]
    if len(bins) != len(set(bins)):
        raise ChartInputError("disagreement2024 contains duplicate bin labels")
    if sum(float(row["count"]) for row in output) <= 0.0:
        raise ChartInputError("disagreement2024 counts must include at least one row")
    return output


def _display(value: str) -> str:
    return value.replace("_", " ")


def _figure(width: float, height: float) -> tuple[Any, Any]:
    fig, axis = plt.subplots(figsize=(width, height), constrained_layout=True)
    fig.patch.set_facecolor("white")
    return fig, axis


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _save_figure(
    figure: Any,
    output_dir: str | os.PathLike[str],
    *,
    chart_id: str,
    title: str,
    include_svg: bool,
    dpi: int,
) -> dict[str, Any]:
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi < 72:
        raise ChartInputError("dpi must be an integer >= 72")
    directory = Path(output_dir).expanduser().resolve()
    if directory.exists() and not directory.is_dir():
        raise ChartInputError(f"output directory is not a directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)

    formats = ["png"] + (["svg"] if include_svg else [])
    pending: list[tuple[Path, Path, str]] = []
    try:
        for file_format in formats:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{chart_id}-",
                suffix=f".{file_format}.tmp",
                dir=directory,
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            destination = directory / f"{chart_id}.{file_format}"
            metadata: dict[str, Any]
            if file_format == "svg":
                metadata = {
                    "Creator": "ASP Model Studio Phase 7B4",
                    "Date": None,
                }
            else:
                metadata = {"Software": "ASP Model Studio Phase 7B4"}
            pending.append((temporary, destination, file_format))
            figure.savefig(
                temporary,
                format=file_format,
                dpi=dpi,
                bbox_inches="tight",
                facecolor="white",
                metadata=metadata,
            )
        for temporary, destination, _ in pending:
            os.replace(temporary, destination)
    except Exception:
        for temporary, _, _ in pending:
            temporary.unlink(missing_ok=True)
        raise

    files: list[dict[str, Any]] = []
    for _, destination, file_format in pending:
        files.append(
            {
                "format": file_format,
                "path": str(destination),
                "sha256": _sha256(destination),
                "bytes": int(destination.stat().st_size),
            }
        )
    return {"chartId": chart_id, "title": title, "files": files}


def plot_log_loss_improvement(
    results: Mapping[str, Any],
    output_dir: str | os.PathLike[str],
    *,
    include_svg: bool = True,
    dpi: int = 160,
) -> dict[str, Any]:
    """Plot candidates sorted by 2024 log-loss improvement over Direct Gold."""

    results = _mapping(results, context="results")
    records = _candidate_records(results)
    direct = _direct_log_loss(results, records)
    ordered = sorted(
        records,
        key=lambda row: (direct - float(row["logLoss"]), row["candidate"]),
    )
    names = [_display(str(row["candidate"])) for row in ordered]
    improvements = [direct - float(row["logLoss"]) for row in ordered]

    fig, axis = _figure(11.5, max(5.2, 0.38 * len(ordered) + 1.8))
    try:
        colors = ["#4c78a8" if value >= 0.0 else "#f58518" for value in improvements]
        positions = np.arange(len(ordered))
        bars = axis.barh(positions, improvements, color=colors, alpha=0.9)
        axis.set_yticks(positions, names)
        axis.axvline(0.0, color="black", linewidth=0.9)
        axis.set_xlabel("2024 log-loss improvement vs Direct Gold (positive is better)")
        axis.set_title("2024 Out-of-Time Log-Loss Improvement")
        axis.grid(axis="x", alpha=0.25)
        max_abs = max(max(abs(value) for value in improvements), 1e-6)
        offset = max_abs * 0.018
        for bar, value in zip(bars, improvements, strict=True):
            axis.text(
                value + (offset if value >= 0.0 else -offset),
                bar.get_y() + bar.get_height() / 2.0,
                f"{value:+.6f}",
                va="center",
                ha="left" if value >= 0.0 else "right",
                fontsize=8,
            )
        axis.margins(x=0.14)
        inventory = _save_figure(
            fig,
            output_dir,
            chart_id="01_2024_log_loss_improvement",
            title="2024 Out-of-Time Log-Loss Improvement",
            include_svg=include_svg,
            dpi=dpi,
        )
    finally:
        plt.close(fig)
    inventory["candidateCount"] = len(ordered)
    inventory["direct2024LogLoss"] = direct
    return inventory


def plot_component_inclusion_heatmap(
    results: Mapping[str, Any],
    output_dir: str | os.PathLike[str],
    *,
    include_svg: bool = True,
    dpi: int = 160,
) -> dict[str, Any]:
    """Plot candidate/component inclusion, annotating included cells with 2024 LL."""

    results = _mapping(results, context="results")
    records = sorted(
        _candidate_records(results),
        key=lambda row: (float(row["logLoss"]), str(row["candidate"])),
    )
    components = _ordered_components(records)
    matrix = np.asarray(
        [
            [1.0 if component in row["components"] else 0.0 for component in components]
            for row in records
        ],
        dtype=float,
    )
    fig, axis = _figure(
        max(11.0, 1.15 * len(components) + 3.5),
        max(5.5, 0.52 * len(records) + 1.8),
    )
    try:
        axis.imshow(
            matrix,
            aspect="auto",
            interpolation="nearest",
            cmap=ListedColormap(["#f2f2f2", "#4c78a8"]),
            vmin=0.0,
            vmax=1.0,
        )
        axis.set_xticks(np.arange(len(components)), [_display(item) for item in components])
        axis.set_yticks(
            np.arange(len(records)),
            [_display(str(row["candidate"])) for row in records],
        )
        axis.tick_params(axis="x", rotation=35)
        for label in axis.get_xticklabels():
            label.set_horizontalalignment("right")
        for row_index, row in enumerate(records):
            for component_index, component in enumerate(components):
                if component in row["components"]:
                    axis.text(
                        component_index,
                        row_index,
                        f"{float(row['logLoss']):.4f}",
                        ha="center",
                        va="center",
                        color="white",
                        fontsize=7,
                    )
        axis.set_xlabel("Included signal component (cell text = 2024 log loss)")
        axis.set_ylabel("Candidate")
        axis.set_title("Candidate Signal Inclusion and 2024 Performance")
        axis.set_xticks(np.arange(-0.5, len(components), 1), minor=True)
        axis.set_yticks(np.arange(-0.5, len(records), 1), minor=True)
        axis.grid(which="minor", color="white", linewidth=1.0)
        axis.tick_params(which="minor", bottom=False, left=False)
        inventory = _save_figure(
            fig,
            output_dir,
            chart_id="02_candidate_component_heatmap",
            title="Candidate Signal Inclusion and 2024 Performance",
            include_svg=include_svg,
            dpi=dpi,
        )
    finally:
        plt.close(fig)
    inventory["candidateCount"] = len(records)
    inventory["componentCount"] = len(components)
    return inventory


def plot_monthly_stability(
    results: Mapping[str, Any],
    output_dir: str | os.PathLike[str],
    *,
    include_svg: bool = True,
    dpi: int = 160,
) -> dict[str, Any]:
    """Plot Direct Gold and the frozen top four alternatives by 2024 month."""

    results = _mapping(results, context="results")
    records = _candidate_records(results)
    selected = [DIRECT_MODEL] + _top_four_candidates(results, records)
    monthly = _monthly_records(results)
    available: dict[str, dict[str, float]] = {candidate: {} for candidate in selected}
    month_order: list[str] = []
    for row in monthly:
        candidate = str(row["candidate"])
        month = str(row["month"])
        if candidate not in available:
            continue
        available[candidate][month] = float(row["logLoss"])
        if candidate == DIRECT_MODEL and month not in month_order:
            month_order.append(month)
    if len(month_order) < 2:
        raise ChartInputError("monthly2024 must contain at least two DIRECT_MODEL months")
    for candidate in selected:
        candidate_months = set(available[candidate])
        expected_months = set(month_order)
        if candidate_months != expected_months:
            missing = sorted(expected_months.difference(candidate_months))
            extra = sorted(candidate_months.difference(expected_months))
            raise ChartInputError(
                f"monthly2024 coverage mismatch for {candidate!r}; "
                f"missing={missing}, extra={extra}"
            )

    fig, axis = _figure(11.5, 6.4)
    try:
        positions = np.arange(len(month_order))
        for candidate in selected:
            values = [available[candidate][month] for month in month_order]
            axis.plot(
                positions,
                values,
                marker="o",
                linewidth=2.2 if candidate == DIRECT_MODEL else 1.5,
                markersize=5,
                label=_display(candidate),
            )
        axis.set_xticks(positions, month_order, rotation=25, ha="right")
        axis.set_xlabel("2024 month")
        axis.set_ylabel("Multiclass log loss (lower is better)")
        axis.set_title("Monthly 2024 Stability: Direct Gold vs Top Four Alternatives")
        axis.grid(alpha=0.25)
        axis.legend(loc="best", frameon=False)
        inventory = _save_figure(
            fig,
            output_dir,
            chart_id="03_monthly_stability",
            title="Monthly 2024 Stability: Direct Gold vs Top Four Alternatives",
            include_svg=include_svg,
            dpi=dpi,
        )
    finally:
        plt.close(fig)
    inventory["candidates"] = selected
    inventory["monthCount"] = len(month_order)
    return inventory


def plot_calibration_reliability(
    results: Mapping[str, Any],
    output_dir: str | os.PathLike[str],
    *,
    include_svg: bool = True,
    dpi: int = 160,
) -> dict[str, Any]:
    """Plot confidence reliability for Direct Gold and the best ensemble."""

    results = _mapping(results, context="results")
    records = _candidate_records(results)
    direct, best, curves = _calibration_curves(results, records)

    fig, axis = _figure(7.3, 7.0)
    try:
        axis.plot([0.0, 1.0], [0.0, 1.0], "--", color="#666666", label="Perfect calibration")
        for candidate in (direct, best):
            points = curves[candidate]
            counts = np.asarray([point["count"] for point in points], dtype=float)
            positive = counts[counts > 0.0]
            if positive.size:
                scaled = 35.0 + 95.0 * np.sqrt(counts / positive.max())
            else:
                scaled = np.full(len(points), 35.0)
            axis.plot(
                [point["meanConfidence"] for point in points],
                [point["observedAccuracy"] for point in points],
                linewidth=1.8,
                label=_display(candidate),
            )
            axis.scatter(
                [point["meanConfidence"] for point in points],
                [point["observedAccuracy"] for point in points],
                s=scaled,
                alpha=0.8,
            )
        axis.set_xlim(0.0, 1.0)
        axis.set_ylim(0.0, 1.0)
        axis.set_aspect("equal", adjustable="box")
        axis.set_xlabel("Mean predicted confidence")
        axis.set_ylabel("Observed accuracy")
        axis.set_title("2024 Calibration Reliability")
        axis.grid(alpha=0.25)
        axis.legend(loc="best", frameon=False)
        inventory = _save_figure(
            fig,
            output_dir,
            chart_id="04_calibration_reliability",
            title="2024 Calibration Reliability",
            include_svg=include_svg,
            dpi=dpi,
        )
    finally:
        plt.close(fig)
    inventory["candidates"] = [direct, best]
    inventory["pointCounts"] = {
        candidate: len(curves[candidate]) for candidate in (direct, best)
    }
    return inventory


def plot_ensemble_weights(
    results: Mapping[str, Any],
    output_dir: str | os.PathLike[str],
    *,
    include_svg: bool = True,
    dpi: int = 160,
) -> dict[str, Any]:
    """Compare optimized static weights with mean reliability-gated weights."""

    results = _mapping(results, context="results")
    static, gated = _weights(results)
    union = set(static).union(gated)
    components = [item for item in SIGNAL_COMPONENT_ORDER if item in union]
    components.extend(sorted(union.difference(SIGNAL_COMPONENT_ORDER)))
    positions = np.arange(len(components))
    bar_width = 0.38

    fig, axis = _figure(11.5, max(5.3, 0.5 * len(components) + 1.9))
    try:
        static_values = [static.get(component, 0.0) for component in components]
        gated_values = [gated.get(component, 0.0) for component in components]
        axis.barh(
            positions - bar_width / 2.0,
            static_values,
            height=bar_width,
            label="Optimized static",
            color="#4c78a8",
        )
        axis.barh(
            positions + bar_width / 2.0,
            gated_values,
            height=bar_width,
            label="Average reliability-gated",
            color="#f58518",
        )
        axis.set_yticks(positions, [_display(component) for component in components])
        axis.invert_yaxis()
        axis.set_xlim(0.0, max(1.0, max(static_values + gated_values) * 1.12))
        axis.set_xlabel("Mean ensemble weight")
        axis.set_title("Frozen Ensemble Weights")
        axis.grid(axis="x", alpha=0.25)
        axis.legend(loc="best", frameon=False)
        inventory = _save_figure(
            fig,
            output_dir,
            chart_id="05_ensemble_weights",
            title="Frozen Ensemble Weights",
            include_svg=include_svg,
            dpi=dpi,
        )
    finally:
        plt.close(fig)
    inventory["componentCount"] = len(components)
    inventory["optimizedStaticSum"] = float(sum(static.values()))
    inventory["averageGatedSum"] = float(sum(gated.values()))
    return inventory


def plot_disagreement_performance(
    results: Mapping[str, Any],
    output_dir: str | os.PathLike[str],
    *,
    include_svg: bool = True,
    dpi: int = 160,
) -> dict[str, Any]:
    """Plot model performance by Direct-versus-recent-state disagreement bin."""

    results = _mapping(results, context="results")
    rows = _disagreement_records(results)
    best_label = _field(
        results,
        "bestCandidate",
        "best_candidate",
        "bestEnsemble",
        "best_ensemble",
        default="Best ensemble",
    )
    best_label = _display(_name(best_label, context="bestCandidate"))

    fig, (performance_axis, count_axis) = plt.subplots(
        2,
        1,
        figsize=(11.5, 7.5),
        constrained_layout=True,
        sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1.0]},
    )
    fig.patch.set_facecolor("white")
    try:
        positions = np.arange(len(rows))
        performance_axis.plot(
            positions,
            [row["directLogLoss"] for row in rows],
            marker="o",
            linewidth=2.0,
            label="Direct Gold",
        )
        performance_axis.plot(
            positions,
            [row["bestLogLoss"] for row in rows],
            marker="o",
            linewidth=2.0,
            label=best_label,
        )
        performance_axis.set_ylabel("Multiclass log loss (lower is better)")
        performance_axis.set_title(
            "2024 Performance by Direct-vs-Recent-State Disagreement"
        )
        performance_axis.grid(alpha=0.25)
        performance_axis.legend(loc="best", frameon=False)

        counts = [float(row["count"]) for row in rows]
        count_axis.bar(positions, counts, color="#999999", alpha=0.7)
        count_axis.set_ylabel("PAs")
        count_axis.set_xlabel("Disagreement bin (low to high, as governed by results)")
        count_axis.set_xticks(
            positions,
            [str(row["bin"]) for row in rows],
            rotation=25,
            ha="right",
        )
        count_axis.grid(axis="y", alpha=0.2)
        inventory = _save_figure(
            fig,
            output_dir,
            chart_id="06_disagreement_performance",
            title="2024 Performance by Direct-vs-Recent-State Disagreement",
            include_svg=include_svg,
            dpi=dpi,
        )
    finally:
        plt.close(fig)
    inventory["binCount"] = len(rows)
    inventory["rowCount"] = int(round(sum(float(row["count"]) for row in rows)))
    return inventory


def generate_review_charts(
    results: Mapping[str, Any],
    output_dir: str | os.PathLike[str],
    *,
    include_svg: bool = True,
    dpi: int = 160,
) -> list[dict[str, Any]]:
    """Generate all six required Phase 7B4 charts.

    The returned inventory contains only JSON-native scalar/list/dict values,
    absolute output paths, byte counts, and SHA-256 file digests.  Each chart
    validates its own required result series and raises ``ChartInputError`` on
    missing or contradictory evidence.
    """

    results = _mapping(results, context="results")
    generators = (
        plot_log_loss_improvement,
        plot_component_inclusion_heatmap,
        plot_monthly_stability,
        plot_calibration_reliability,
        plot_ensemble_weights,
        plot_disagreement_performance,
    )
    return [
        generator(
            results,
            output_dir,
            include_svg=include_svg,
            dpi=dpi,
        )
        for generator in generators
    ]


__all__ = [
    "ChartInputError",
    "DIRECT_MODEL",
    "SIGNAL_COMPONENT_ORDER",
    "generate_review_charts",
    "plot_calibration_reliability",
    "plot_component_inclusion_heatmap",
    "plot_disagreement_performance",
    "plot_ensemble_weights",
    "plot_log_loss_improvement",
    "plot_monthly_stability",
]
