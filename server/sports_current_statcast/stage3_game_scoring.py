"""Governed Stage 3 whole-game scoring and provider-free public readiness.

The executable path in this module accepts only pre-materialized, verified pregame inputs and
an already-loaded research artifact.  Public summary reads are intentionally metadata-only.
No function here discovers schedules, calls lineup/starter providers, opens final OOT targets,
or reads target-game results.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

import numpy as np

from server.persistence.db import Database, json_loads
from server.persistence.repositories.project_repository import ProjectRepository
from server.persistence.repositories.run_repository import RunRepository
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_phase5.game_initialization import RngLineage
from server.sports_phase5.whole_game_monte_carlo import (
    MAX_TEAM_PA,
    FastTransitionSampler,
    GameContribs,
    GameSimResult,
    simulate_game,
)

from .stage3_game_inputs import Stage3GameInputs
from .stage3_game_probability_adapter import (
    FINAL_DEVELOPMENT_MODEL,
    FOLD_VALIDATION_MODEL,
    Stage3PAProbabilityProvider,
    VerifiedStage3ArtifactBinding,
    build_stage3_probability_adapter,
)
from .stage3_model_laboratory import EXPECTED_PROJECT_ID


GAME_SCORING_SCHEMA_VERSION = "SPORTS_STAGE3_GOVERNED_GAME_SCORING_V1"
GAME_SCORING_JOB_TYPE = "sports_stage3_game_scoring"
HISTORICAL_OOF_SCORING = "HISTORICAL_OOF"
PROSPECTIVE_SCORING = "PROSPECTIVE"
FINAL_OOT_START = date(2026, 8, 14)
FINAL_OOT_END = date(2026, 8, 27)
MIN_SIMULATION_DRAWS = 32
MAX_SIMULATION_DRAWS = 1_000_000
_ACTIVE_JOB_STATUSES = {"QUEUED", "RUNNING", "CANCEL_REQUESTED"}
_TRANSITION_SAMPLER_DIGEST_SCHEMA = b"SPORTS_STAGE3_TRANSITION_SAMPLER_CONTENT_V1\0"


class Stage3GameScoringError(RuntimeError):
    """A public-safe, typed game scoring failure."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)

    def public_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self)}


def _error(code: str, message: str, *, status_code: int = 409) -> Stage3GameScoringError:
    return Stage3GameScoringError(code, message, status_code=status_code)


def _parse_date(value: Any, *, label: str) -> date:
    if not isinstance(value, str):
        raise _error("STAGE3_GAME_DATE_INVALID", f"{label} is missing.")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise _error("STAGE3_GAME_DATE_INVALID", f"{label} is invalid.") from exc


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise _error("STAGE3_SCORING_CHECKSUM_INVALID", f"{label} is missing.")
    digest = value.lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise _error("STAGE3_SCORING_CHECKSUM_INVALID", f"{label} must be a SHA-256 digest.")
    return digest


def transition_sampler_sha256(transition_sampler: FastTransitionSampler) -> str:
    """Hash the exact transition probabilities and outcomes used by the simulator.

    ``FastTransitionSampler`` is an optimized projection of the governed transition model.
    Binding its complete cell contents prevents a caller from attaching an unrelated model
    checksum to a different in-memory sampler.
    """

    if not isinstance(transition_sampler, FastTransitionSampler):
        raise TypeError("transition_sampler must be FastTransitionSampler")
    cumulative_by_cell = getattr(transition_sampler, "_cum", None)
    transitions_by_cell = getattr(transition_sampler, "_trans", None)
    expected_cells = set(range(len(PA_CLASS_ORDER) * 3 * 8))
    if (
        not isinstance(cumulative_by_cell, Mapping)
        or not isinstance(transitions_by_cell, Mapping)
        or set(cumulative_by_cell) != expected_cells
        or set(transitions_by_cell) != expected_cells
    ):
        raise _error(
            "SIMULATOR_TRANSITION_SAMPLER_INVALID",
            "The transition sampler does not contain the complete governed base/out cell grid.",
        )

    digest = hashlib.sha256()
    digest.update(_TRANSITION_SAMPLER_DIGEST_SCHEMA)
    for cell in sorted(expected_cells):
        raw_cumulative = np.asarray(cumulative_by_cell[cell])
        raw_transitions = np.asarray(transitions_by_cell[cell])
        if (
            raw_cumulative.ndim != 1
            or raw_cumulative.size == 0
            or raw_cumulative.dtype.kind not in "fiu"
            or raw_transitions.shape != (raw_cumulative.size, 3)
            or raw_transitions.dtype.kind not in "iu"
        ):
            raise _error(
                "SIMULATOR_TRANSITION_SAMPLER_INVALID",
                f"Transition sampler cell {cell} has an invalid shape or dtype.",
            )
        cumulative = np.asarray(raw_cumulative, dtype="<f8")
        transitions = np.asarray(raw_transitions, dtype="<i8")
        if (
            not np.isfinite(cumulative).all()
            or np.any(cumulative < 0.0)
            or np.any(cumulative > 1.0 + 1e-12)
            or np.any(np.diff(cumulative) < -1e-12)
            or not np.isclose(cumulative[-1], 1.0, rtol=0.0, atol=1e-12)
            or np.any(transitions[:, 0] < 0)
            or np.any(transitions[:, 0] > 3)
            or np.any(transitions[:, 1] < 0)
            or np.any(transitions[:, 1] > 7)
            or np.any(transitions[:, 2] < 0)
        ):
            raise _error(
                "SIMULATOR_TRANSITION_SAMPLER_INVALID",
                f"Transition sampler cell {cell} contains invalid probability or state values.",
            )
        digest.update(int(cell).to_bytes(2, byteorder="little", signed=False))
        digest.update(int(cumulative.size).to_bytes(4, byteorder="little", signed=False))
        digest.update(cumulative.tobytes(order="C"))
        digest.update(transitions.tobytes(order="C"))
    return digest.hexdigest()


def validate_scoring_model_usage(
    game_inputs: Stage3GameInputs,
    artifact: VerifiedStage3ArtifactBinding,
    *,
    scoring_mode: str,
) -> dict[str, Any]:
    """Enforce fold-versus-final temporal use before a simulator can run."""

    if not isinstance(game_inputs, Stage3GameInputs):
        raise TypeError("game_inputs must be Stage3GameInputs")
    if not isinstance(artifact, VerifiedStage3ArtifactBinding):
        raise TypeError("artifact must be VerifiedStage3ArtifactBinding")
    mode = str(scoring_mode or "").upper()
    game_date = _parse_date(game_inputs.game_date, label="game date")
    if FINAL_OOT_START <= game_date <= FINAL_OOT_END:
        raise _error(
            "FINAL_OOT_SCORING_PROHIBITED",
            "The locked 2026-08-14 through 2026-08-27 final OOT may not be scored or opened.",
        )

    if mode == HISTORICAL_OOF_SCORING:
        if artifact.model_role != FOLD_VALIDATION_MODEL:
            raise _error(
                "HISTORICAL_OOF_REQUIRES_FOLD_PIPELINE",
                "Historical OOF game simulation must use the fold pipeline whose validation period contains the game.",
            )
        validation_start = _parse_date(
            artifact.validation_start_date, label="fold validation start"
        )
        validation_end = _parse_date(
            artifact.validation_end_date, label="fold validation end"
        )
        if not validation_start <= game_date <= validation_end:
            raise _error(
                "HISTORICAL_GAME_OUTSIDE_FOLD_VALIDATION",
                "The historical game is outside the bound fold's validation period.",
            )
        return {
            "scoringMode": mode,
            "foldModelUsed": f"FOLD_{artifact.fold_number}",
            "validationStartDate": validation_start.isoformat(),
            "validationEndDate": validation_end.isoformat(),
            "finalModelUsed": False,
        }

    if mode == PROSPECTIVE_SCORING:
        if artifact.model_role != FINAL_DEVELOPMENT_MODEL:
            raise _error(
                "PROSPECTIVE_SCORING_REQUIRES_FINAL_DEVELOPMENT_PIPELINE",
                "Prospective scoring requires the verified final development pipeline.",
            )
        training_end = _parse_date(artifact.training_end_date, label="training end date")
        if game_date <= training_end:
            raise _error(
                "FINAL_MODEL_RETROSPECTIVE_USE_PROHIBITED",
                "The final development model cannot be used as OOF evidence for an earlier game.",
            )
        return {
            "scoringMode": mode,
            "foldModelUsed": None,
            "finalModelUsed": True,
            "trainedThrough": training_end.isoformat(),
        }

    raise _error(
        "STAGE3_SCORING_MODE_INVALID",
        "Scoring mode must be HISTORICAL_OOF or PROSPECTIVE.",
    )


def _validate_draws(draws: Any) -> int:
    if isinstance(draws, bool) or not isinstance(draws, int):
        raise _error("SIMULATION_DRAW_COUNT_INVALID", "Simulation draws must be an integer.")
    if not MIN_SIMULATION_DRAWS <= draws <= MAX_SIMULATION_DRAWS:
        raise _error(
            "SIMULATION_DRAW_COUNT_INVALID",
            f"Simulation draws must be between {MIN_SIMULATION_DRAWS} and {MAX_SIMULATION_DRAWS}.",
        )
    return draws


def _validate_seed(seed: Any) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**63:
        raise _error(
            "SIMULATION_SEED_INVALID",
            "Simulation seed must be a nonnegative signed 64-bit integer.",
        )
    return seed


def _score_distribution(values: np.ndarray, *, key: str) -> list[dict[str, Any]]:
    counts = Counter(int(value) for value in values.tolist())
    total = int(values.size)
    return [
        {key: value, "count": count, "probability": count / total}
        for value, count in sorted(counts.items())
    ]


def _joint_distribution(away: np.ndarray, home: np.ndarray) -> list[dict[str, Any]]:
    counts = Counter(zip((int(value) for value in away), (int(value) for value in home)))
    total = int(away.size)
    return [
        {
            "awayRuns": away_runs,
            "homeRuns": home_runs,
            "count": count,
            "probability": count / total,
        }
        for (away_runs, home_runs), count in sorted(counts.items())
    ]


def _quantiles(values: np.ndarray) -> dict[str, float]:
    return {
        "p05": float(np.percentile(values, 5)),
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
    }


def _standard_error(values: np.ndarray) -> float:
    if values.size < 2:
        return 0.0
    return float(np.std(values.astype(np.float64), ddof=1) / math.sqrt(values.size))


def _stability(values: Mapping[str, np.ndarray]) -> dict[str, Any]:
    indices = [indices for indices in np.array_split(np.arange(len(next(iter(values.values())))), 4) if indices.size]
    blocks: list[dict[str, Any]] = []
    for block_number, index in enumerate(indices, start=1):
        away = values["away"][index]
        home = values["home"][index]
        blocks.append(
            {
                "block": block_number,
                "draws": int(index.size),
                "expectedAwayRuns": float(away.mean()),
                "expectedHomeRuns": float(home.mean()),
                "homeWinProbability": float((home > away).mean()),
            }
        )

    def spread(key: str) -> float:
        observed = [float(block[key]) for block in blocks]
        return max(observed) - min(observed)

    return {
        "method": "FOUR_SEQUENTIAL_EQUAL_DRAW_BLOCKS",
        "blocks": blocks,
        "maxExpectedAwayRunsSpread": spread("expectedAwayRuns"),
        "maxExpectedHomeRunsSpread": spread("expectedHomeRuns"),
        "maxHomeWinProbabilitySpread": spread("homeWinProbability"),
    }


def _validate_simulator_result(result: GameSimResult) -> tuple[np.ndarray, ...]:
    if not isinstance(result, GameSimResult):
        raise TypeError("result must be GameSimResult")
    expected = (result.n_sims,)
    arrays = (
        np.asarray(result.away_runs),
        np.asarray(result.home_runs),
        np.asarray(result.innings),
        np.asarray(result.pa_counts),
        np.asarray(result.home_win),
        np.asarray(result.first_five_away_runs),
        np.asarray(result.first_five_home_runs),
    )
    if result.n_sims <= 0 or any(values.shape != expected for values in arrays):
        raise _error(
            "SIMULATOR_OUTPUT_SHAPE_INVALID",
            "Every whole-game simulator output must align to the declared draw count.",
        )
    for label, values in zip(
        ("away runs", "home runs", "innings", "PA counts", "home-win mask", "first-five away runs", "first-five home runs"),
        arrays,
    ):
        if values.dtype.kind not in "iub" or not np.isfinite(values.astype(np.float64)).all():
            raise _error("SIMULATOR_OUTPUT_INVALID", f"Simulator {label} values are invalid.")
    away, home, innings, pa_counts, home_win, first_away, first_home = arrays
    if (
        np.any(away < 0)
        or np.any(home < 0)
        or np.any(innings < 1)
        or np.any(pa_counts < 1)
        or np.any(first_away < 0)
        or np.any(first_home < 0)
    ):
        raise _error(
            "SIMULATOR_OUTPUT_ILLEGAL_STATE",
            "Simulator outputs contain negative scores, incomplete first-five states, or illegal counters.",
        )
    if result.nonterminated != 0 or result.illegal_states != 0 or np.any(away == home):
        raise _error(
            "SIMULATOR_OUTPUT_NOT_RECONCILABLE",
            "Every draw must terminate in a legal, tie-free final state under the declared extra-inning policy.",
        )
    expected_home_win = home > away
    if home_win.dtype != np.bool_ or not np.array_equal(home_win, expected_home_win):
        raise _error(
            "SIMULATOR_WIN_MASK_MISMATCH",
            "The simulator home-win mask does not reconcile to final scores.",
        )
    return away, home, innings, pa_counts, home_win, first_away, first_home


def build_game_distribution_output(result: GameSimResult) -> dict[str, Any]:
    """Create complete distribution output from one legal simulator result."""

    away, home, innings, _, home_win, first_away, first_home = _validate_simulator_result(result)
    total = away + home
    difference = home - away
    first_total = first_away + first_home
    first_difference = first_home - first_away
    joint = _joint_distribution(away, home)
    most_likely = sorted(
        joint,
        key=lambda row: (-float(row["probability"]), int(row["awayRuns"]), int(row["homeRuns"])),
    )[:10]
    home_win_probability = float(home_win.mean())
    result_payload: dict[str, Any] = {
        "draws": result.n_sims,
        "expectedHomeRuns": float(home.mean()),
        "expectedAwayRuns": float(away.mean()),
        "homeWinProbability": home_win_probability,
        "awayWinProbability": 1.0 - home_win_probability,
        "jointScoreDistribution": joint,
        "awayScoreDistribution": _score_distribution(away, key="awayRuns"),
        "homeScoreDistribution": _score_distribution(home, key="homeRuns"),
        "runDifferenceDistribution": _score_distribution(difference, key="homeRunDifference"),
        "totalRunsDistribution": _score_distribution(total, key="totalRuns"),
        "firstFive": {
            "completedDraws": result.n_sims,
            "expectedHomeRuns": float(first_home.mean()),
            "expectedAwayRuns": float(first_away.mean()),
            "homeWinProbability": float((first_difference > 0).mean()),
            "awayWinProbability": float((first_difference < 0).mean()),
            "tieProbability": float((first_difference == 0).mean()),
            "jointScoreDistribution": _joint_distribution(first_away, first_home),
            "totalRunsDistribution": _score_distribution(first_total, key="totalRuns"),
            "predictionIntervals": {
                "awayRuns90": _quantiles(first_away),
                "homeRuns90": _quantiles(first_home),
                "totalRuns90": _quantiles(first_total),
            },
        },
        "mostLikelyScores": [dict(row) for row in most_likely],
        "predictionIntervals": {
            "awayRuns90": _quantiles(away),
            "homeRuns90": _quantiles(home),
            "totalRuns90": _quantiles(total),
            "homeRunDifference90": _quantiles(difference),
        },
        "extraInningProbability": float((innings > 9).mean()),
        "uncertainty": {
            "expectedAwayRunsStandardError": _standard_error(away),
            "expectedHomeRunsStandardError": _standard_error(home),
            "homeWinProbabilityStandardError": math.sqrt(
                home_win_probability * (1.0 - home_win_probability) / result.n_sims
            ),
        },
        "stability": _stability({"away": away, "home": home}),
    }
    result_payload["reconciliation"] = reconcile_game_distribution_output(
        result, result_payload
    )
    return result_payload


def _probability_sum(rows: Sequence[Mapping[str, Any]]) -> float:
    return math.fsum(float(row["probability"]) for row in rows)


def reconcile_game_distribution_output(
    result: GameSimResult, output: Mapping[str, Any]
) -> dict[str, Any]:
    """Fail closed unless joint, marginal, total, margin, win, and F5 outputs agree."""

    away, home, _, _, _, first_away, first_home = _validate_simulator_result(result)
    required_distributions = (
        "jointScoreDistribution",
        "awayScoreDistribution",
        "homeScoreDistribution",
        "runDifferenceDistribution",
        "totalRunsDistribution",
    )
    for name in required_distributions:
        rows = output.get(name)
        if not isinstance(rows, list) or not rows or not math.isclose(
            _probability_sum(rows), 1.0, rel_tol=0.0, abs_tol=1e-12
        ):
            raise _error(
                "GAME_DISTRIBUTION_NORMALIZATION_FAILED",
                f"{name} is missing or does not normalize to one.",
            )
        if any(
            not math.isfinite(float(row.get("probability", math.nan)))
            or float(row.get("probability", -1.0)) < 0.0
            for row in rows
        ):
            raise _error(
                "GAME_DISTRIBUTION_INVALID",
                f"{name} contains invalid probability mass.",
            )

    joint_counts = {
        (int(row["awayRuns"]), int(row["homeRuns"])): int(row["count"])
        for row in output["jointScoreDistribution"]
    }
    actual_joint = Counter(zip((int(value) for value in away), (int(value) for value in home)))
    if joint_counts != actual_joint:
        raise _error(
            "JOINT_SCORE_RECONCILIATION_FAILED",
            "The joint score distribution differs from simulator draws.",
        )

    def counts(rows: Sequence[Mapping[str, Any]], key: str) -> Counter[int]:
        return Counter({int(row[key]): int(row["count"]) for row in rows})

    if (
        counts(output["awayScoreDistribution"], "awayRuns") != Counter(int(value) for value in away)
        or counts(output["homeScoreDistribution"], "homeRuns") != Counter(int(value) for value in home)
        or counts(output["runDifferenceDistribution"], "homeRunDifference")
        != Counter(int(value) for value in home - away)
        or counts(output["totalRunsDistribution"], "totalRuns")
        != Counter(int(value) for value in home + away)
    ):
        raise _error(
            "GAME_MARGINAL_RECONCILIATION_FAILED",
            "One or more marginal, margin, or total distributions differ from the joint draws.",
        )
    if not math.isclose(
        float(output.get("expectedAwayRuns", math.nan)), float(away.mean()), rel_tol=0.0, abs_tol=1e-12
    ) or not math.isclose(
        float(output.get("expectedHomeRuns", math.nan)), float(home.mean()), rel_tol=0.0, abs_tol=1e-12
    ):
        raise _error(
            "EXPECTED_SCORE_RECONCILIATION_FAILED",
            "Expected scores do not equal the simulator-draw marginals.",
        )
    home_win = float((home > away).mean())
    away_win = float((away > home).mean())
    if (
        not math.isclose(float(output.get("homeWinProbability", math.nan)), home_win, abs_tol=1e-12)
        or not math.isclose(float(output.get("awayWinProbability", math.nan)), away_win, abs_tol=1e-12)
        or not math.isclose(home_win + away_win, 1.0, abs_tol=1e-12)
    ):
        raise _error(
            "WIN_PROBABILITY_RECONCILIATION_FAILED",
            "Home and away win probabilities do not reconcile under the tie-free policy.",
        )

    first = output.get("firstFive")
    if not isinstance(first, Mapping):
        raise _error("FIRST_FIVE_RECONCILIATION_FAILED", "First-five output is missing.")
    first_win_sum = math.fsum(
        float(first.get(name, math.nan))
        for name in ("homeWinProbability", "awayWinProbability", "tieProbability")
    )
    first_joint = first.get("jointScoreDistribution")
    first_total = first.get("totalRunsDistribution")
    if (
        not isinstance(first_joint, list)
        or not isinstance(first_total, list)
        or not math.isclose(_probability_sum(first_joint), 1.0, abs_tol=1e-12)
        or not math.isclose(_probability_sum(first_total), 1.0, abs_tol=1e-12)
        or not math.isclose(first_win_sum, 1.0, abs_tol=1e-12)
        or Counter(
            {
                (int(row["awayRuns"]), int(row["homeRuns"])): int(row["count"])
                for row in first_joint
            }
        )
        != Counter(zip((int(value) for value in first_away), (int(value) for value in first_home)))
    ):
        raise _error(
            "FIRST_FIVE_RECONCILIATION_FAILED",
            "First-five score, total, or win distributions do not reconcile.",
        )
    return {
        "status": "PASSED",
        "jointDistributionNormalized": True,
        "jointAndMarginalsReconciled": True,
        "marginAndTotalReconciled": True,
        "expectedScoresReconciled": True,
        "homeAwayWinsReconciled": True,
        "firstFiveReconciled": True,
        "legalBaseOutStates": result.illegal_states == 0,
        "allDrawsTerminated": result.nonterminated == 0,
    }


@dataclass(frozen=True)
class GovernedGameScoringResult:
    payload: Mapping[str, Any]

    def record(self) -> dict[str, Any]:
        return dict(self.payload)


def score_governed_game(
    game_inputs: Stage3GameInputs,
    artifact: VerifiedStage3ArtifactBinding,
    *,
    transition_sampler: FastTransitionSampler,
    transition_model_sha256: str,
    expected_transition_model_sha256: str,
    draws: int,
    seed: int,
    scoring_mode: str,
) -> GovernedGameScoringResult:
    """Run one fixed-seed whole-game simulation from fully governed evidence."""

    n_sims = _validate_draws(draws)
    master_seed = _validate_seed(seed)
    if not isinstance(transition_sampler, FastTransitionSampler):
        raise TypeError("transition_sampler must be FastTransitionSampler")
    transition_sha = _sha256(transition_model_sha256, label="transition model checksum")
    expected_transition_sha = _sha256(
        expected_transition_model_sha256, label="expected transition model checksum"
    )
    sampler_sha = transition_sampler_sha256(transition_sampler)
    if transition_sha != expected_transition_sha or transition_sha != sampler_sha:
        raise _error(
            "SIMULATOR_TRANSITION_AUTHORITY_MISMATCH",
            "The actual base/out transition sampler differs from the declared or expected scoring authority.",
        )
    usage = validate_scoring_model_usage(
        game_inputs, artifact, scoring_mode=scoring_mode
    )
    provider: Stage3PAProbabilityProvider = build_stage3_probability_adapter(
        game_inputs, artifact
    )
    zeros = np.zeros((MAX_TEAM_PA, 8), dtype=np.float64)
    contribs = GameContribs(
        away_batter=zeros.copy(),
        away_pitcher=zeros.copy(),
        home_batter=zeros.copy(),
        home_pitcher=zeros.copy(),
        regulation=9,
    )
    rng = RngLineage(master_seed, game_inputs.canonical_game_id)
    try:
        simulation = simulate_game(
            game_id=game_inputs.canonical_game_id,
            contribs=contribs,
            fold=None,
            transition_sampler=transition_sampler,
            rng_lineage=rng,
            n_sims=n_sims,
            check_legality=True,
            probability_provider=provider,
        )
    except Stage3GameScoringError:
        raise
    except Exception as exc:
        raise _error(
            "STAGE3_WHOLE_GAME_SIMULATION_FAILED",
            "The governed whole-game simulator failed; no partial score was published.",
        ) from exc
    if transition_sampler_sha256(transition_sampler) != sampler_sha:
        raise _error(
            "SIMULATOR_TRANSITION_AUTHORITY_MUTATED",
            "The base/out transition sampler changed during scoring; no result was published.",
        )
    distributions = build_game_distribution_output(simulation)
    receipt_base = {
        "schemaVersion": GAME_SCORING_SCHEMA_VERSION,
        "gameId": game_inputs.canonical_game_id,
        "gameDate": game_inputs.game_date,
        "evidenceStatus": "GOVERNED_PREGAME_EVIDENCE_VERIFIED",
        **usage,
        "lineupAuthority": dict(game_inputs.lineup_authority),
        "starterAuthority": dict(game_inputs.starter_authority),
        "featureAuthority": dict(game_inputs.feature_authority),
        "featureCutoff": game_inputs.source_cutoff,
        "artifactId": artifact.artifact_id,
        "artifactManifestSha256": artifact.manifest_sha256,
        "modelBinarySha256": artifact.model_sha256,
        "featureVectorSha256": game_inputs.feature_vector_sha256,
        "transitionModelSha256": transition_sha,
        "draws": n_sims,
        "seed": master_seed,
        "rngLineage": rng.as_dict(),
        "externalProviderCalls": 0,
        "actualTargetOutcomesRead": False,
        "actualSubstitutionsUsed": False,
        "actualRelieversUsed": False,
        "sportsbookPredictorsUsed": False,
        **distributions,
    }
    result_sha = hashlib.sha256(canonical_json_bytes(receipt_base)).hexdigest()
    return GovernedGameScoringResult(
        payload={**receipt_base, "scoringReceiptSha256": result_sha}
    )


def _decode_job(row: Mapping[str, Any]) -> dict[str, Any]:
    raw_results = json_loads(row.get("artifacts_json"), [])
    if isinstance(raw_results, Mapping) and isinstance(raw_results.get("games"), list):
        results = list(raw_results["games"])
    elif isinstance(raw_results, list):
        results = list(raw_results)
    else:
        results = []
    raw_error = json_loads(row.get("error_json"), {})
    return {
        "jobId": row.get("run_id"),
        "projectId": row.get("project_id"),
        "status": str(row.get("status") or "").upper(),
        "createdBy": row.get("created_by"),
        "startedAt": row.get("started_at"),
        "completedAt": row.get("completed_at"),
        "request": json_loads(row.get("parameters_json"), {}),
        "progress": json_loads(row.get("metrics_json"), {}),
        "results": results,
        "error": dict(raw_error) if isinstance(raw_error, Mapping) and raw_error else None,
    }


def _artifact_public_identity(database: Database, project_id: str) -> dict[str, Any]:
    """Read completed artifact identity from SQLite without hashing/loading model members."""

    completed = next(
        (
            row
            for row in RunRepository(database).list_for_project(project_id)
            if row.get("run_type") == "sports_stage3_executable_artifact"
            and str(row.get("status") or "").upper() == "COMPLETE"
        ),
        None,
    )
    artifacts = json_loads(completed.get("artifacts_json"), {}) if completed else {}
    artifact = artifacts.get("artifact") if isinstance(artifacts, Mapping) else None
    if not isinstance(artifact, Mapping):
        return {}
    return {
        "artifactId": artifact.get("artifactId"),
        "artifactManifestSha256": artifact.get("manifestSha256")
        or artifact.get("artifactManifestSha256"),
        "artifactStatus": artifact.get("status"),
    }


def _require_project(database: Database, project_id: str) -> None:
    if project_id != EXPECTED_PROJECT_ID:
        raise _error(
            "STAGE3_GAME_SCORING_PROJECT_NOT_CONFIGURED",
            "Governed Stage 3 game scoring is not configured for that project.",
        )
    if ProjectRepository(database).get(project_id) is None:
        raise _error(
            "STAGE3_GAME_SCORING_PROJECT_NOT_FOUND",
            "The canonical project record is unavailable.",
            status_code=404,
        )


def game_scoring_summary(database: Database, project_id: str) -> dict[str, Any]:
    """Return metadata-only readiness; never discover games or call providers."""

    _require_project(database, project_id)
    jobs = [
        _decode_job(row)
        for row in RunRepository(database).list_for_project(project_id)
        if row.get("run_type") == GAME_SCORING_JOB_TYPE
    ]
    current = next(
        (job for job in jobs if job["status"] in _ACTIVE_JOB_STATUSES), None
    )
    completed_results = [
        result
        for job in jobs
        if job["status"] == "COMPLETE"
        for result in job["results"]
    ]
    artifact_identity = _artifact_public_identity(database, project_id)
    blocker = {
        "code": "GOVERNED_PREGAME_LINEUP_STARTER_AUTHORITY_UNAVAILABLE",
        "message": (
            "Model Studio has no configured confirmed point-in-time lineup and announced-"
            "starter authority; prospective games remain empty and no provider was called."
        ),
    }
    return {
        "ok": True,
        "schemaVersion": GAME_SCORING_SCHEMA_VERSION,
        "authority": {
            "projectId": project_id,
            "artifactId": artifact_identity.get("artifactId"),
            "artifactManifestSha256": artifact_identity.get("artifactManifestSha256"),
            "artifactStatus": artifact_identity.get("artifactStatus"),
            "modelStatus": "RESEARCH_CHALLENGER",
            "promotionStatus": "NOT_PROMOTED",
            "finalOotLocked": True,
        },
        "readiness": {
            "ready": False,
            "status": "BLOCKED_MISSING_GOVERNED_PREGAME_AUTHORITY",
            "blockers": [blocker],
        },
        "games": [],
        "currentJob": current,
        "results": completed_results,
        "activity": {
            "providerCalls": 0,
            "finalOotTargetAccessed": False,
            "actualTargetOutcomesRead": False,
            "gamesDiscovered": 0,
            "jobs": jobs,
        },
    }


def enqueue_game_scoring_job(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    """Fail closed before job creation while governed participant authority is absent."""

    _require_project(database, project_id)
    if not isinstance(payload, Mapping):
        raise _error(
            "STAGE3_GAME_SCORING_REQUEST_INVALID",
            "The game scoring request must be a JSON object.",
            status_code=422,
        )
    if not isinstance(actor_user_id, str) or not actor_user_id.strip():
        raise _error(
            "STAGE3_GAME_SCORING_ACTOR_REQUIRED",
            "An authenticated actor is required.",
            status_code=403,
        )
    # There is intentionally no provider-discovery fallback here.  Once a separately governed
    # lineup/starter inventory is registered, integration can feed its prepared evidence into
    # ``score_governed_game`` and persist the resulting receipt.
    raise _error(
        "GOVERNED_PREGAME_LINEUP_STARTER_AUTHORITY_UNAVAILABLE",
        "Confirmed point-in-time lineup and announced-starter authority is unavailable; no game scoring job was created and no provider was called.",
    )


def get_game_scoring_job(
    database: Database, project_id: str, job_id: str
) -> dict[str, Any]:
    _require_project(database, project_id)
    row = RunRepository(database).get(job_id)
    if (
        row is None
        or row.get("project_id") != project_id
        or row.get("run_type") != GAME_SCORING_JOB_TYPE
    ):
        raise _error(
            "STAGE3_GAME_SCORING_JOB_NOT_FOUND",
            "The project-scoped governed game scoring job does not exist.",
            status_code=404,
        )
    return {"ok": True, "job": _decode_job(row)}


__all__ = [
    "FINAL_OOT_END",
    "FINAL_OOT_START",
    "GAME_SCORING_JOB_TYPE",
    "GAME_SCORING_SCHEMA_VERSION",
    "GovernedGameScoringResult",
    "HISTORICAL_OOF_SCORING",
    "MAX_SIMULATION_DRAWS",
    "MIN_SIMULATION_DRAWS",
    "PROSPECTIVE_SCORING",
    "Stage3GameScoringError",
    "build_game_distribution_output",
    "enqueue_game_scoring_job",
    "game_scoring_summary",
    "get_game_scoring_job",
    "reconcile_game_distribution_output",
    "score_governed_game",
    "transition_sampler_sha256",
    "validate_scoring_model_usage",
]
