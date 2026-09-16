"""Paired, non-pregame game-mechanics sensitivity for the MLB regime study.

This module does not turn realized PA contexts into pregame evidence. It averages
each observed batting side's aligned PA probability vectors, then passes those
two vectors through the existing whole-game simulator. Consequently even optional
actual-score diagnostics are ORACLE_MECHANICS_SENSITIVITY_NONPREGAME, not a game
forecast backtest. The same simulator, transition authority and RNG lineage are
held fixed across the global and challenger branches. There are no data loaders,
model fits, publication side effects or provider interfaces here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix
from server.sports_phase5.base_out_transition import TransitionModel
from server.sports_phase5.game_initialization import RngLineage
from server.sports_phase5.whole_game_monte_carlo import (
    MAX_TEAM_PA,
    FastTransitionSampler,
    GameContribs,
    GameSimResult,
    simulate_game,
)


SCHEMA_VERSION = "MLB_REGIME_PAIRED_GAME_MECHANICS_SENSITIVITY_V1"
EVIDENCE_TRACK = "ORACLE_MECHANICS_SENSITIVITY_NONPREGAME"
DEVELOPMENT_END = "2026-08-13"
REQUIRED_COLUMNS = ("canonicalPaId", "canonicalGameId", "game_date", "context_top_bottom")


class RegimeSimulationError(ValueError):
    """Paired identities, chronology, truth or probability authority differed."""


def _dates(values: pd.Series, name: str) -> pd.Series:
    text = values.astype(str)
    if not text.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise RegimeSimulationError(f"{name} requires explicit ISO calendar dates")
    try:
        return pd.to_datetime(text, format="%Y-%m-%d", errors="raise")
    except ValueError as exc:
        raise RegimeSimulationError(f"invalid {name}") from exc


def _summary(result: GameSimResult, truth: tuple[int, int] | None) -> dict[str, Any]:
    away = result.away_runs.astype(float)
    home = result.home_runs.astype(float)
    distributions = {"away": away, "home": home, "margin": home - away, "total": home + away}
    intervals = {
        name: {
            str(level): [float(v) for v in np.quantile(values, [(1 - level) / 2, (1 + level) / 2])]
            for level in (0.5, 0.8, 0.9, 0.95)
        }
        for name, values in distributions.items()
    }
    p_home = float(result.home_win.mean())
    result_hash = hashlib.sha256()
    for values in (result.away_runs, result.home_runs, result.innings, result.pa_counts):
        result_hash.update(np.asarray(values, dtype="<i8").tobytes(order="C"))
    record: dict[str, Any] = {
        "simulations": result.n_sims,
        "probabilityHomeWin": p_home,
        "probabilityAwayWin": 1.0 - p_home,
        "means": {name: float(values.mean()) for name, values in distributions.items()},
        "standardDeviations": {name: float(values.std()) for name, values in distributions.items()},
        "predictionIntervals": intervals,
        "extraInningRate": float(np.mean(result.innings > 9)),
        "meanPlateAppearances": float(result.pa_counts.mean()),
        "illegalStates": result.illegal_states,
        "terminationFailures": result.nonterminated,
        "simulationArraySha256": result_hash.hexdigest(),
        "coherent": bool(
            result.nonterminated == 0 and result.illegal_states == 0
            and np.all(away >= 0) and np.all(home >= 0)
            and np.all(away != home)
            and np.array_equal(result.home_win, home > away)
        ),
        "actualScoreDiagnostics": None,
    }
    if truth is not None:
        actual_away, actual_home = truth
        actual = {"away": actual_away, "home": actual_home, "margin": actual_home - actual_away,
                  "total": actual_home + actual_away}
        y_home = int(actual_home > actual_away)
        probability = np.clip(p_home, 1e-12, 1 - 1e-12)
        record["actualScoreDiagnostics"] = {
            "homeWinLogLoss": float(-y_home * np.log(probability) - (1 - y_home) * np.log1p(-probability)),
            "homeWinBrier": float((p_home - y_home) ** 2),
            "homeWinCalibrationResidual": float(p_home - y_home),
            "scoreErrors": {name: float(values.mean() - actual[name]) for name, values in distributions.items()},
            "intervalCoverage": {
                name: {level: bool(bounds[0] <= actual[name] <= bounds[1]) for level, bounds in levels.items()}
                for name, levels in intervals.items()
            },
        }
    return record


def _aggregate(records: list[dict[str, Any]], branch: str) -> dict[str, Any]:
    summaries = [record[branch] for record in records]
    diagnostics = [row["actualScoreDiagnostics"] for row in summaries if row["actualScoreDiagnostics"] is not None]
    result: dict[str, Any] = {
        "games": len(summaries), "outcomeGames": len(diagnostics),
        "coherentGames": sum(int(row["coherent"]) for row in summaries),
        "illegalStates": sum(row["illegalStates"] for row in summaries),
        "terminationFailures": sum(row["terminationFailures"] for row in summaries),
        "predictiveGameSkillEstablished": False,
        "actualScoreDiagnostics": None,
    }
    if diagnostics:
        score_metrics = {}
        for name in ("away", "home", "margin", "total"):
            errors = np.array([row["scoreErrors"][name] for row in diagnostics])
            score_metrics[name] = {
                "bias": float(errors.mean()), "mae": float(np.abs(errors).mean()),
                "rmse": float(np.sqrt(np.square(errors).mean())),
                "intervalCoverage": {
                    str(level): float(np.mean([row["intervalCoverage"][name][str(level)] for row in diagnostics]))
                    for level in (0.5, 0.8, 0.9, 0.95)
                },
            }
        result["actualScoreDiagnostics"] = {
            **{name: float(np.mean([row[name] for row in diagnostics])) for name in
               ("homeWinLogLoss", "homeWinBrier", "homeWinCalibrationResidual")},
            "scores": score_metrics,
        }
    return result


def compare_paired_game_mechanics(
    observations: pd.DataFrame,
    baseline_probabilities: np.ndarray,
    challenger_probabilities: np.ndarray,
    *,
    transition_model: TransitionModel,
    transition_training_end: str,
    transition_model_sha256: str,
    n_sims: int = 500,
    master_seed: int = 20260910,
    maximum_games: int | None = 20,
    game_truth: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Compare aligned later-Development PA vectors using common random numbers.

    ``observations`` must match both probability matrices row-for-row and contain
    REQUIRED_COLUMNS. ``context_top_bottom`` is 0 for away batting and 1 for home.
    Optional verified truth has canonicalGameId, actualAway, actualHome; it is used
    only after both simulations and never in eligibility or probability construction.
    No claim that the observed PA inventory was knowable pregame is permitted.
    """
    if observations.empty or not set(REQUIRED_COLUMNS).issubset(observations.columns):
        raise RegimeSimulationError("aligned Development PA identities/dates/sides are required")
    frame = observations.loc[:, list(REQUIRED_COLUMNS)].reset_index(drop=True).copy()
    for name in ("canonicalPaId", "canonicalGameId"):
        if frame[name].isna().any() or frame[name].astype(str).str.strip().eq("").any():
            raise RegimeSimulationError(f"missing {name}")
        frame[name] = frame[name].astype(str)
    if frame["canonicalPaId"].duplicated().any():
        raise RegimeSimulationError("duplicate PA identity in paired population")
    dates = _dates(frame["game_date"], "game_date")
    training_end = _dates(pd.Series([transition_training_end]), "transition_training_end").iloc[0]
    if dates.gt(pd.Timestamp(DEVELOPMENT_END)).any():
        raise RegimeSimulationError("sealed/future rows are outside authorized Development")
    if dates.le(training_end).any():
        raise RegimeSimulationError("transition training must precede every comparison game")
    if frame.groupby("canonicalGameId")["game_date"].nunique().gt(1).any():
        raise RegimeSimulationError("game identity maps to multiple dates")
    if not frame["context_top_bottom"].isin([0, 1]).all():
        raise RegimeSimulationError("batting side must be 0 (away) or 1 (home)")
    if not isinstance(transition_model_sha256, str) or len(transition_model_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in transition_model_sha256
    ):
        raise RegimeSimulationError("exact transition artifact SHA-256 is required")
    if not isinstance(n_sims, int) or isinstance(n_sims, bool) or n_sims < 2:
        raise RegimeSimulationError("n_sims must be an integer of at least two")
    if maximum_games is not None and (not isinstance(maximum_games, int) or isinstance(maximum_games, bool) or maximum_games < 1):
        raise RegimeSimulationError("maximum_games must be a positive integer")
    matrices = {
        "baseline": validate_probability_matrix(baseline_probabilities),
        "challenger": validate_probability_matrix(challenger_probabilities),
    }
    if any(len(values) != len(frame) for values in matrices.values()):
        raise RegimeSimulationError("probability population does not match supplied PA identities")
    truths: dict[str, tuple[int, int]] = {}
    if game_truth is not None:
        columns = ["canonicalGameId", "actualAway", "actualHome"]
        if not set(columns).issubset(game_truth.columns) or game_truth["canonicalGameId"].isna().any():
            raise RegimeSimulationError("game truth schema is incomplete")
        if game_truth["canonicalGameId"].astype(str).duplicated().any():
            raise RegimeSimulationError("game truth identity is duplicated")
        for game_id, away, home in game_truth.loc[:, columns].itertuples(index=False, name=None):
            values = np.array([away, home], dtype=float)
            if not np.isfinite(values).all() or np.any(values < 0) or np.any(values != np.floor(values)) or away == home:
                raise RegimeSimulationError("game truth requires nonnegative integer completed non-tied scores")
            truths[str(game_id)] = (int(away), int(home))

    sampler = FastTransitionSampler(transition_model)
    zeros = np.zeros((MAX_TEAM_PA, len(PA_CLASS_ORDER)), dtype=float)
    dummy = GameContribs(zeros, zeros, zeros, zeros, regulation=9)
    records, skipped = [], []
    inventory = frame[["canonicalGameId", "game_date"]].drop_duplicates().sort_values(
        ["game_date", "canonicalGameId"], kind="stable"
    )
    for game_id, day in inventory.itertuples(index=False, name=None):
        positions = np.flatnonzero(frame["canonicalGameId"].eq(game_id).to_numpy())
        sides = frame.iloc[positions]["context_top_bottom"].to_numpy()
        if set(sides) != {0, 1}:
            skipped.append({"canonicalGameId": game_id, "reason": "PA_PROBABILITIES_MISSING_ONE_BATTING_SIDE"})
            continue
        if maximum_games is not None and len(records) >= maximum_games:
            skipped.append({"canonicalGameId": game_id, "reason": "PREDECLARED_DATE_ID_GAME_LIMIT"})
            continue
        lineage = RngLineage(master_seed, f"mlb-regime-mechanics:{game_id}")
        record: dict[str, Any] = {
            "canonicalGameId": game_id, "gameDate": str(day), "evidenceTrack": EVIDENCE_TRACK,
            "observedPaRows": len(positions), "awayPaRows": int(sum(sides == 0)),
            "homePaRows": int(sum(sides == 1)), "rngLineage": lineage.as_dict(),
            "actualAway": truths.get(game_id, (None, None))[0],
            "actualHome": truths.get(game_id, (None, None))[1],
        }
        for branch, matrix in matrices.items():
            side_vectors = np.vstack([matrix[positions[sides == side]].mean(axis=0) for side in (0, 1)])
            # Mean of validated vectors may differ from one by round-off only.
            side_vectors /= side_vectors.sum(axis=1, keepdims=True)

            def provider(state: Any, vectors: np.ndarray = side_vectors) -> np.ndarray:
                return vectors[np.where(state.is_top, 0, 1)]

            simulation = simulate_game(
                game_id=str(game_id), contribs=dummy, fold=None, transition_sampler=sampler,
                rng_lineage=lineage, n_sims=n_sims, check_legality=True, probability_provider=provider,
            )
            record[branch] = _summary(simulation, truths.get(game_id))
            record[branch]["observedSideMeanPaProbabilities"] = side_vectors.tolist()
        record["challengerMinusBaseline"] = {
            "probabilityHomeWin": record["challenger"]["probabilityHomeWin"] - record["baseline"]["probabilityHomeWin"],
            "means": {name: record["challenger"]["means"][name] - record["baseline"]["means"][name]
                      for name in ("away", "home", "margin", "total")},
        }
        records.append(record)
    all_coherent = all(row[branch]["coherent"] for row in records for branch in matrices)
    return {
        "schemaVersion": SCHEMA_VERSION, "evidenceTrack": EVIDENCE_TRACK,
        "status": ("MECHANICS_SENSITIVITY_COMPLETE" if all_coherent else "SIMULATION_CONFORMANCE_FAILED")
        if records else "NO_SUPPORTED_PAIRED_GAMES",
        "classOrder": list(PA_CLASS_ORDER), "transitionModelSha256": transition_model_sha256,
        "transitionTrainingEnd": transition_training_end, "simulationsPerGame": n_sims,
        "commonRandomNumbers": True, "inputPaRows": len(frame), "inputGames": len(inventory),
        "completedGames": len(records), "skippedGames": skipped,
        "gameSelection": "DATE_THEN_CANONICAL_GAME_ID_WITHOUT_OUTCOMES",
        "baseline": _aggregate(records, "baseline"), "challenger": _aggregate(records, "challenger"),
        "games": records, "pregameForecastsProduced": 0, "finalOotRowsRead": 0,
        "wageringAuthority": False, "promotionAuthority": False,
        "limitations": [
            "The caller must verify transition artifact bytes and its declared training cutoff before supplying the in-memory model.",
            "Observed PA membership and original probability contexts are retrospective; no pregame game-skill claim.",
            "Side-average vectors do not preserve batting order, substitutions, state-dependent PA strengths or full player heterogeneity.",
            "The unchanged simulator uses nine-inning regulation and automatic extra-inning runners; shortened-game forecasts are not modeled.",
            "No market quotes, wager returns or prospective participant timing are inferred.",
        ],
    }


def load_accepted_transition(repository_root: Path) -> tuple[TransitionModel, dict[str, Any]]:
    """Load/hash only the accepted fitted JSON, never its training source rows."""
    bundle = Path(repository_root) / "outputs/mlb-v18-whole-game-challenger/sha256" / (
        "a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27"
    )
    path = bundle / "executable/transition-fold4.json"
    content = path.read_bytes()
    expected = "0e5e480f897ddefa5f9dddbc229a8a43bf29f7b81443c25ece611d9d4032b253"
    if len(content) != 20106 or hashlib.sha256(content).hexdigest() != expected:
        raise RegimeSimulationError("accepted fold-4 transition artifact differs")
    evaluation = Path(repository_root) / "outputs/mlb-v18-pa-game-baseline/sha256" / (
        "9ed04b20fb03b5399e77f7cd311db9d6aba50709fc8d368522e3b19f46de6504"
    ) / "transition-evaluation.json"
    evidence = evaluation.read_bytes()
    if hashlib.sha256(evidence).hexdigest() != "18b046f185d01512e04651925608f0beff850536d2de12e05cde831c30d28444":
        raise RegimeSimulationError("transition training-cutoff receipt differs")
    fold = next(item for item in json.loads(evidence)["folds"] if item["foldNumber"] == 4)
    if fold["registered"]["trainEnd"] != "2025-07-27" or fold["transitionArtifact"]["sha256"] != expected:
        raise RegimeSimulationError("transition fold/cutoff linkage differs")
    return TransitionModel.from_dict(json.loads(content)), {
        "path": str(path), "sha256": expected, "bytes": len(content), "selectedFold": 4,
        "trainingEnd": "2025-07-27", "trainingReceiptPath": str(evaluation),
        "trainingSourceRowsRead": 0,
    }
