"""Compact renderer contract for the accepted 5,000-game V18 population.

This module aggregates already-sampled V18 states.  It does not score a PA,
sample a transition, or alter a game result.  Retrosheet-derived geometry is a
display layer and is kept distinct from persisted V18 state throughout.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast.mlb_v18_play_geometry import (
    COORDINATE_SYSTEM,
    GEOMETRY_MODEL_VERSION,
    PlayGeometryModel,
)
from server.sports_current_statcast.mlb_v18_play_geometry_trace import (
    SELECTORS,
    build_ball_trace,
    enrich_path,
)


SCHEMA_VERSION = "MLB_V18_POPULATION_GEOMETRY_SUPPLEMENT_V1"
COORDINATE_SYSTEM_VERSION = COORDINATE_SYSTEM
CONTACT_GRID = (32, 32)
PATH_GRID = (24, 24)
FRAME_SIZE = 50
EXPECTED_SIMULATIONS = 5_000
PARENT_BUNDLE_SHA256 = "a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27"
PLAY_GEOMETRY_SHA256 = "7b638efe0caab3b4b3ffcf7d06169ba8c51ae7d2c8d2d912d6c4259f5328fa15"
ACCEPTANCE_PROTOCOL_V2_SHA256 = "291243d7abad7f972e08f7610715bf8e693a267ea37a7b6189256f98aa4a4a7b"


class PopulationGeometryError(RuntimeError):
    """A population identity, reconciliation, or artifact check failed."""


def sha(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def population_digest(result: Mapping[str, Any]) -> str:
    """Digest ordered terminal results; the accepted artifact declared no digest."""

    rows = np.column_stack((
        np.arange(int(result["simulationCount"]), dtype=np.int64),
        np.asarray(result["awayRuns"], dtype=np.int64),
        np.asarray(result["homeRuns"], dtype=np.int64),
        np.asarray(result["innings"], dtype=np.int64),
        np.asarray(result["paCounts"], dtype=np.int64),
    ))
    digest = hashlib.sha256()
    digest.update(b"ASP_V18_POPULATION_ARRAY_DIGEST_V1\0")
    digest.update(np.asarray(rows, dtype="<i8").tobytes(order="C"))
    return digest.hexdigest()


def reconcile_forecast(result: Mapping[str, Any], forecast: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "homeWinProbability", "meanAwayRuns", "meanHomeRuns", "meanTotalRuns",
        "meanRunDifferential", "oneRunRate", "extraInningRate",
        "simulationCount", "masterSeed", "illegalStateCount", "nonterminationCount",
    )
    comparisons = {}
    for key in keys:
        actual = result[key]
        expected = forecast[key]
        tolerance = 1e-12 if isinstance(expected, float) else 0
        difference = abs(float(actual) - float(expected))
        comparisons[key] = {
            "accepted": expected, "reconstructed": actual,
            "absoluteDifference": difference, "tolerance": tolerance,
            "matches": difference <= tolerance,
        }
    return {
        "allMetricsMatch": all(row["matches"] for row in comparisons.values()),
        "comparisons": comparisons,
    }


def accumulation_frames(result: Mapping[str, Any], per_simulation: Mapping[str, np.ndarray]) -> list[dict[str, Any]]:
    away = np.asarray(result["awayRuns"], dtype=np.int64)
    home = np.asarray(result["homeRuns"], dtype=np.int64)
    innings = np.asarray(result["innings"], dtype=np.int64)
    if len(away) != EXPECTED_SIMULATIONS:
        raise PopulationGeometryError("population must contain exactly 5,000 simulations")
    frames = []
    for end in range(FRAME_SIZE, EXPECTED_SIMULATIONS + 1, FRAME_SIZE):
        sl = slice(0, end)
        home_wins = int(np.sum(home[sl] > away[sl]))
        away_wins = end - home_wins
        total = home[sl] + away[sl]
        diff = home[sl] - away[sl]
        body = {
            "frameIndex": len(frames),
            "simulationIndexStart": end - FRAME_SIZE,
            "simulationIndexEndInclusive": end - 1,
            "cumulativeSimulationCount": end,
            "cumulativeHomeWins": home_wins,
            "cumulativeAwayWins": away_wins,
            "cumulativeHomeWinProbability": float(home_wins / end),
            "cumulativeAwayWinProbability": float(away_wins / end),
            "cumulativeExpectedHomeRuns": float(np.mean(home[sl])),
            "cumulativeExpectedAwayRuns": float(np.mean(away[sl])),
            "cumulativeExpectedTotal": float(np.mean(total)),
            "cumulativeRunDifferential": float(np.mean(diff)),
            "cumulativeOneRunGameRate": float(np.mean(np.abs(diff) == 1)),
            "cumulativeExtraInningRate": float(np.mean(innings[sl] > 9)),
            "cumulativeContactPlayCount": int(np.sum(per_simulation["contact"][sl])),
            "cumulativeScoringPlayCount": int(np.sum(per_simulation["scoring"][sl])),
            "cumulativeGeometryDensity": int(np.sum(per_simulation["geometry"][sl])),
            "cumulativeRunnerPathTraffic": int(np.sum(per_simulation["runnerSegments"][sl])),
        }
        body["frameDigest"] = sha(body)
        frames.append(body)
    return frames


def _quantile(values: np.ndarray, fraction: float) -> float:
    return float(np.quantile(values.astype(float), fraction, method="nearest"))


def representative_indices(result: Mapping[str, Any], forecast: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    away = np.asarray(result["awayRuns"], dtype=np.int64)
    home = np.asarray(result["homeRuns"], dtype=np.int64)
    innings = np.asarray(result["innings"], dtype=np.int64)
    total = away + home
    diff = home - away
    all_indexes = np.arange(len(away), dtype=np.int64)

    def conditional_medians(pool: np.ndarray) -> tuple[float, float]:
        return float(np.median(total[pool])), float(np.median(diff[pool]))

    used: set[int] = set()

    def nearest(pool: np.ndarray, target_total: float, target_diff: float) -> tuple[int, float, int]:
        if not len(pool):
            raise PopulationGeometryError("a predeclared representative selector has no candidates")
        distance = np.abs(total[pool] - target_total) + np.abs(diff[pool] - target_diff)
        order = np.lexsort((pool, np.abs(diff[pool] - target_diff), distance))
        for rank, position in enumerate(order, 1):
            selected = int(pool[int(position)])
            if selected not in used:
                used.add(selected)
                return selected, float(distance[int(position)]), rank
        raise PopulationGeometryError("a predeclared representative selector has no distinct candidate")

    home_pool = all_indexes[diff > 0]
    away_pool = all_indexes[diff < 0]
    extra_pool = all_indexes[innings > 9]
    pools = {
        "TYPICAL": (all_indexes, float(forecast["meanTotalRuns"]), float(forecast["meanRunDifferential"]), "population means"),
        "HOME_WIN": (*((home_pool,) + conditional_medians(home_pool)), "home-win conditional medians"),
        "AWAY_WIN": (*((away_pool,) + conditional_medians(away_pool)), "away-win conditional medians"),
        "HIGH_SCORING": (all_indexes, _quantile(total, .9), float(np.median(diff)), "population 90th percentile total"),
        "LOW_SCORING": (all_indexes, _quantile(total, .1), float(np.median(diff)), "population 10th percentile total"),
        "EXTRA_INNINGS": (*((extra_pool,) + conditional_medians(extra_pool)), "extra-inning conditional medians"),
    }
    selected = {}
    for name, (pool, target_total, target_diff, target_kind) in pools.items():
        index, distance, rank = nearest(np.asarray(pool), target_total, target_diff)
        selected[name] = {
            "selector": name,
            "definition": SELECTORS[name],
            "simulationIndex": index,
            "candidateCount": int(len(pool)),
            "target": {"kind": target_kind, "totalRuns": target_total, "runDifferential": target_diff},
            "selectionInputs": {
                "awayRuns": int(away[index]), "homeRuns": int(home[index]),
                "totalRuns": int(total[index]), "runDifferential": int(diff[index]),
                "innings": int(innings[index]),
            },
            "distance": distance,
            "rank": rank,
            "tieBreak": "LOWEST_SIMULATION_INDEX_AFTER_DISTANCE_AND_DIFFERENTIAL_DISTANCE",
        }
    return selected


def _cell(point: Mapping[str, Any], dimensions: tuple[int, int]) -> int:
    width, height = dimensions
    x = min(max(float(point["x"]), -1.0), 1.0)
    y = min(max(float(point["y"]), 0.0), 1.0)
    ix = min(width - 1, int((x + 1.0) * .5 * width))
    iy = min(height - 1, int(y * height))
    return iy * width + ix


def _sparse(counter: Counter) -> list[list[int]]:
    return [[int(key), int(value)] for key, value in sorted(counter.items())]


def _layers(event: Mapping[str, Any], geometry: Mapping[str, Any], result_class: Mapping[str, bool]) -> list[str]:
    outcome = str(event["outcome"])
    layers = ["ALL", f"TEAM_{'AWAY' if event['half'] == 'TOP' else 'HOME'}", f"OUTCOME_{outcome}"]
    if outcome in {"SINGLE", "DOUBLE", "TRIPLE", "HOME_RUN"}:
        layers.append("HITS")
    if outcome == "BIP_OUT":
        layers.append("BATTED_BALL_OUTS")
    layers.append("SCORING" if int(event["runsScored"]) else "NON_SCORING")
    layers.append("FOUL" if geometry.get("foulLocation") else "FAIR")
    if geometry.get("battedBallType"):
        layers.append(f"BATTED_BALL_{geometry['battedBallType']}")
    inning = int(event["inning"])
    layers.append("INNING_1_3" if inning <= 3 else "INNING_4_6" if inning <= 6 else "INNING_7_9" if inning <= 9 else "INNING_EXTRA")
    layers.extend(name for name, held in result_class.items() if held)
    return layers


class PopulationAccumulator:
    """Bounded one-dimensional filter layers; never a combinatorial cube."""

    def __init__(self, *, model: PlayGeometryModel, park: str, game_id: str, terminal: Mapping[str, np.ndarray]):
        self.model = model
        self.park = park
        self.game_id = game_id
        self.terminal = terminal
        self.contact = defaultdict(Counter)
        self.paths = defaultdict(Counter)
        self.runner_segments = Counter()
        self.runner_dimensions = defaultdict(Counter)
        self.runner_special = Counter()
        self.per_simulation = {
            name: np.zeros(EXPECTED_SIMULATIONS, dtype=np.int64)
            for name in ("contact", "scoring", "geometry", "runnerSegments")
        }
        self.total_events = 0
        self.contact_events = 0
        self.geometry_events = 0
        self.scoring_events = 0

    def observe(self, simulation_index: int, event: Mapping[str, Any]) -> None:
        self.total_events += 1
        seed = (self.game_id, simulation_index, int(event["pa"]))
        geometry = self.model.sample_geometry(outcome=str(event["outcome"]), park=self.park, seed=seed)
        trace = build_ball_trace(geometry)
        template, level, _ = self.model.sample_runner_template(
            outcome=str(event["outcome"]), mask_before=int(event["baseMaskBefore"]),
            outs_before=int(event["outsBefore"]), runs=int(event["runsScored"]),
            mask_after=int(event["baseMaskAfter"]),
            outs_added=int(event["outsAfter"])-int(event["outsBefore"]),
            batted_ball_type=geometry.get("battedBallType"), seed=seed,
        )
        result_class = {
            "RESULT_HOME_WIN": bool(self.terminal["home"][simulation_index] > self.terminal["away"][simulation_index]),
            "RESULT_AWAY_WIN": bool(self.terminal["away"][simulation_index] > self.terminal["home"][simulation_index]),
            "RESULT_EXTRA_INNINGS": bool(self.terminal["innings"][simulation_index] > 9),
            "RESULT_REGULATION": bool(self.terminal["innings"][simulation_index] <= 9),
            "RESULT_ONE_RUN": bool(abs(self.terminal["home"][simulation_index]-self.terminal["away"][simulation_index]) == 1),
            "RESULT_NON_ONE_RUN": bool(abs(self.terminal["home"][simulation_index]-self.terminal["away"][simulation_index]) != 1),
        }
        layers = _layers(event, geometry, result_class)
        if geometry.get("contactOccurred"):
            self.contact_events += 1
            self.per_simulation["contact"][simulation_index] += 1
        if int(event["runsScored"]):
            self.scoring_events += 1
            self.per_simulation["scoring"][simulation_index] += 1
        point = geometry.get("point")
        if point is not None:
            self.geometry_events += 1
            self.per_simulation["geometry"][simulation_index] += 1
            cell = _cell(point, CONTACT_GRID)
            for layer in layers:
                self.contact[layer][cell] += 1
        if trace is not None:
            origin = _cell(trace["start"], PATH_GRID)
            control = _cell(trace["control"][0], PATH_GRID)
            destination = _cell(trace["end"], PATH_GRID)
            path_key = (origin * PATH_GRID[0] * PATH_GRID[1] + control, destination)
            for layer in layers:
                self.paths[layer][path_key] += 1
        inning = int(event["inning"])
        inning_band = "1_3" if inning <= 3 else "4_6" if inning <= 6 else "7_9" if inning <= 9 else "EXTRA"
        inning_ends = int(event["outsAfter"]) >= 3
        for origin, destination in template:
            self.per_simulation["runnerSegments"][simulation_index] += 1
            segment = f"{origin}_TO_{destination}"
            self.runner_segments[segment] += 1
            role = "BATTER_RUNNER" if origin == "BATTER_BOX" else "EXISTING_RUNNER"
            self.runner_dimensions[f"ROLE_{role}"][segment] += 1
            self.runner_dimensions[f"TEAM_{'AWAY' if event['half'] == 'TOP' else 'HOME'}"][segment] += 1
            self.runner_dimensions[f"OUTCOME_{event['outcome']}"][segment] += 1
            self.runner_dimensions[f"INNING_{inning_band}"][segment] += 1
            self.runner_dimensions["SCORING" if destination == "HOME" else "NON_SCORING"][segment] += 1
            self.runner_dimensions["OUT_MOVEMENT" if destination == "OUT" else "SAFE_MOVEMENT"][segment] += 1
            self.runner_dimensions[f"AUTHORITY_{level}"][segment] += 1
            normalized_origin = "HOME" if origin == "BATTER_BOX" else origin
            normalized_segment = f"{normalized_origin}_TO_{destination}"
            self.runner_special[normalized_segment] += 1
            if destination == "OUT":
                self.runner_special["RUNNER_REMOVED_OR_RETIRED"] += 1
            if inning_ends and destination in {"FIRST", "SECOND", "THIRD"}:
                self.runner_special["RUNNER_STRANDED_END_INNING"] += 1

    def contact_payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "coordinateSystem": COORDINATE_SYSTEM_VERSION,
            "grid": {"width": CONTACT_GRID[0], "height": CONTACT_GRID[1], "xRange": [-1, 1], "yRange": [0, 1], "orientation": "HOME_PLATE_AT_0_0_CENTER_FIELD_POSITIVE_Y"},
            "normalization": "RAW_COUNTS; DISPLAY_VALUE_EQUALS_CELL_COUNT_DIVIDED_BY_LAYER_MAXIMUM",
            "smoothing": {"applied": False, "method": None},
            "layers": {name: {"count": int(sum(counter.values())), "maximumCellCount": int(max(counter.values(), default=0)), "sparseRawCounts": _sparse(counter)} for name, counter in sorted(self.contact.items())},
        }

    def path_payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "coordinateSystem": COORDINATE_SYSTEM_VERSION,
            "representation": "SPARSE_QUADRATIC_PATH_CELLS",
            "grid": {"width": PATH_GRID[0], "height": PATH_GRID[1], "cellEncoding": "row_major", "tupleEncoding": "[originTimes576PlusControl,destination,count]"},
            "layers": {name: [[int(key[0]), int(key[1]), int(value)] for key, value in sorted(counter.items())] for name, counter in sorted(self.paths.items())},
            "semantics": "MODELLED_GEOMETRY aggregated for display; no measured flight path or physical timing.",
        }

    def runner_payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "representation": "ANONYMOUS_SEGMENT_TRAFFIC_COUNTS",
            "allSegments": dict(sorted(self.runner_segments.items())),
            "requiredTrafficCounts": {
                name: int(self.runner_special.get(name, 0))
                for name in (
                    "HOME_TO_FIRST", "FIRST_TO_SECOND", "SECOND_TO_THIRD", "THIRD_TO_HOME",
                    "HOME_TO_SECOND", "HOME_TO_THIRD", "FIRST_TO_THIRD", "FIRST_TO_HOME",
                    "SECOND_TO_HOME", "RUNNER_REMOVED_OR_RETIRED", "RUNNER_STRANDED_END_INNING",
                )
            },
            "dimensions": {name: dict(sorted(counter.items())) for name, counter in sorted(self.runner_dimensions.items())},
            "semantics": "HISTORICAL_RUNNER_TEMPLATE or DETERMINISTIC_LEGAL_BACKOFF; never player identity.",
        }


def attach_representatives(
    selector_rows: Mapping[str, Mapping[str, Any]],
    trace_indices: Sequence[int],
    traces: Sequence[Sequence[Mapping[str, Any]]],
    *, model: PlayGeometryModel, park: str, game_id: str,
) -> dict[str, Any]:
    by_index = {}
    for index, trace in zip(trace_indices, traces, strict=True):
        by_index[int(index)] = enrich_path(model=model, path=trace, park=park, path_index=int(index), game_id=game_id)
    selectors = {}
    for name, selection in selector_rows.items():
        path = by_index[int(selection["simulationIndex"])]
        selectors[name] = {**selection, "pathDigest": path["pathDigest"], "geometryDigest": path["geometryDigest"]}
    duplicates = defaultdict(list)
    for name, row in selectors.items():
        duplicates[int(row["simulationIndex"])].append(name)
    return {
        "selectors": selectors,
        "uniquePathCount": len(by_index),
        "sharedSelections": [
            {"simulationIndex": index, "selectors": names}
            for index, names in sorted(duplicates.items()) if len(names) > 1
        ],
        "paths": [by_index[index] for index in sorted(by_index)],
    }


def verify_manifest(root: Path, *, expected_supplement_sha: str | None = None) -> dict[str, Any]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if expected_supplement_sha and manifest.get("supplementSha256") != expected_supplement_sha:
        raise PopulationGeometryError("population supplement checksum identity differs")
    if manifest.get("parentBundleSha256") != PARENT_BUNDLE_SHA256:
        raise PopulationGeometryError("parent V18 bundle checksum differs")
    if manifest.get("playGeometrySupplementSha256") != PLAY_GEOMETRY_SHA256:
        raise PopulationGeometryError("Play Geometry supplement checksum differs")
    for artifact in manifest.get("artifacts", []):
        path = root / artifact["relativePath"]
        if not path.is_file():
            raise PopulationGeometryError(f"population artifact is missing: {artifact['relativePath']}")
        raw = path.read_bytes()
        if len(raw) != artifact["bytes"] or hashlib.sha256(raw).hexdigest() != artifact["sha256"]:
            raise PopulationGeometryError(f"population artifact checksum differs: {artifact['relativePath']}")
    body = {key: value for key, value in manifest.items() if key not in {"supplementId", "supplementSha256"}}
    if sha(body) != manifest.get("supplementSha256"):
        raise PopulationGeometryError("population manifest identity does not verify")
    return manifest


def load_or_broadcast(root: Path) -> dict[str, Any]:
    try:
        manifest = verify_manifest(root)
        return {"mode": "SIMULATION_POPULATION", "manifest": manifest, "fallback": False}
    except (OSError, ValueError, PopulationGeometryError) as exc:
        return {"mode": "BROADCAST_REPLAY", "fallback": True, "reason": str(exc)}


__all__ = [
    "ACCEPTANCE_PROTOCOL_V2_SHA256", "CONTACT_GRID", "EXPECTED_SIMULATIONS",
    "FRAME_SIZE", "PATH_GRID", "PLAY_GEOMETRY_SHA256", "PARENT_BUNDLE_SHA256",
    "PopulationAccumulator", "PopulationGeometryError", "accumulation_frames",
    "attach_representatives", "load_or_broadcast", "population_digest",
    "reconcile_forecast", "representative_indices", "sha", "verify_manifest",
]
