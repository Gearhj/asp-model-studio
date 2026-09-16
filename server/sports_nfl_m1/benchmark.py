"""End-to-end chronological NFL M1 research benchmark.

The runner in this module is intentionally disconnected from every product
registry.  It reads one verified NFL Foundation authority, selects every
modeling decision from 2020--2024 expanding-window OOF predictions, freezes a
selection receipt, and only then opens the 2025 outcome columns for one final
OOT evaluation.  Large ledgers, simulations, and fitted binaries are written
to an explicitly supplied external directory.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .baselines import EloTeamStrengthBaseline, LeagueHomePrior, RollingScoringMarginBaseline
from .artifacts import load_verified_research_artifact, publish_research_artifact
from .contracts import (
    EXTRA_TREES_SCORE_GRID,
    HGB_SCORE_GRID,
    RANDOM_SEED,
    RIDGE_SCORE_GRID,
    WIN_LOGISTIC_C_GRID,
    XGBOOST_SCORE_CONFIG,
    NflM1IntegrityError,
    ScoreModelConfig,
    assert_no_market_predictors,
    research_only_metadata,
)
from .data_authority import (
    FoundationPaths,
    assess_feature_tiers,
    audit_game_population,
    audit_market_coverage,
    load_eligible_games,
    resolve_nfl_m1_authority,
)
from .distributions import (
    PairedResidualAuthority,
    SimulatedScores,
    make_common_random_numbers,
    reconcile_score_simulation,
    simulate_joint_scores,
    summarize_game_distribution,
)
from .ensemble import fit_convex_blend
from .metrics import (
    binary_probability_metrics,
    calibration_table,
    distribution_metrics,
    empirical_crps,
    line_event_metrics,
    paired_whole_game_bootstrap,
    score_point_metrics,
)
from .models import IndependentHomeAwayScoreModel, RegularizedHomeWinModel, xgboost_capability
from .recency import RECENCY_STRATEGIES, RecencyStrategy, recency_weights
from .reporting import write_m1_research_outputs
from .temporal import TemporalDesign, build_temporal_design


BENCHMARK_CONTRACT = "ASP_NFL_M1_CHRONOLOGICAL_SCORE_DISTRIBUTION_BENCHMARK_V1"
SELECTION_CONTRACT = "ASP_NFL_M1_OOF_SELECTION_RECEIPT_V1"
SIMULATION_ARCHIVE_CONTRACT = "ASP_NFL_M1_EXACT_JOINT_SCORE_DRAWS_V1"
DEFAULT_EXTERNAL_ROOT = Path(r"C:\Users\james\asp-data-staging\nfl\m1-modeling-benchmark-v1")
DEFAULT_DOCS_ROOT = Path(__file__).resolve().parents[2] / "docs" / "nfl_m1"
CATEGORICAL_FEATURES = ("game_type", "roof", "surface")
ID_COLUMNS = (
    "canonical_game_id",
    "season",
    "game_type",
    "week",
    "game_date",
    "canonical_home_team_id",
    "canonical_away_team_id",
    "division_game",
    "roof",
    "surface",
    "home_points",
    "away_points",
    "home_win",
    "tie_game",
    "score_differential",
    "total_points",
    "overtime",
    "governed_population",
)


@dataclass(frozen=True)
class BenchmarkConfig:
    foundation_root: Path
    external_root: Path = DEFAULT_EXTERNAL_ROOT
    docs_root: Path = DEFAULT_DOCS_ROOT
    seed: int = RANDOM_SEED
    oof_draws: int = 2_000
    oot_draws: int = 10_000
    bootstrap_resamples: int = 2_000
    final_oot_season: int = 2025

    def validated(self) -> "BenchmarkConfig":
        if self.oof_draws < 500 or self.oot_draws < 1_000:
            raise NflM1IntegrityError("M1 simulation draw counts are too small")
        if self.bootstrap_resamples < 200:
            raise NflM1IntegrityError("M1 bootstrap resample count is too small")
        external = Path(self.external_root).resolve()
        docs = Path(self.docs_root).resolve()
        repository = Path(__file__).resolve().parents[2]
        try:
            external.relative_to(repository)
        except ValueError:
            pass
        else:
            raise NflM1IntegrityError("large M1 artifacts must remain outside Git")
        return BenchmarkConfig(
            foundation_root=Path(self.foundation_root).resolve(),
            external_root=external,
            docs_root=docs,
            seed=int(self.seed),
            oof_draws=int(self.oof_draws),
            oot_draws=int(self.oot_draws),
            bootstrap_resamples=int(self.bootstrap_resamples),
            final_oot_season=int(self.final_oot_season),
        )


@dataclass(frozen=True)
class SelectedCandidate:
    family: str
    candidate_id: str
    recency_strategy: str
    parameters: Mapping[str, Any]
    feature_tier: str = "LONG_HISTORY_CORE"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _canonical_bytes(payload)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_bytes(body)
    os.replace(temporary, path)
    return _sha256_bytes(body)


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)
    return _sha256_file(path)


def _atomic_simulation_archive(
    path: Path,
    *,
    candidate_id: str,
    scope: str,
    game_ids: Sequence[str],
    simulation: SimulatedScores,
    fold_lineage: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist exact integer joint draws without pickle and verify the result.

    The caller supplies an already validated external artifact root.  IDs use a
    fixed-width Unicode array so loading with ``allow_pickle=False`` is mandatory
    and sufficient; no Python object or executable payload enters the archive.
    """

    path = Path(path)
    ids = tuple(str(value) for value in game_ids)
    if (
        len(ids) != simulation.n_games
        or len(set(ids)) != len(ids)
        or any(not value for value in ids)
    ):
        raise NflM1IntegrityError("simulation archive game identities are invalid")
    reconciliation = reconcile_score_simulation(simulation)
    maximum_id_length = max(len(value) for value in ids)
    id_array = np.asarray(ids, dtype=f"<U{maximum_id_length}")
    home = np.ascontiguousarray(simulation.home, dtype=np.int32)
    away = np.ascontiguousarray(simulation.away, dtype=np.int32)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as handle:
            np.savez_compressed(
                handle,
                canonical_game_id=id_array,
                home_score_draws=home,
                away_score_draws=away,
            )
        # Verify the unpublished temporary bytes before the atomic publication.
        with np.load(temporary, allow_pickle=False) as verified:
            if set(verified.files) != {
                "canonical_game_id",
                "home_score_draws",
                "away_score_draws",
            }:
                raise NflM1IntegrityError("simulation archive schema differs")
            if (
                tuple(verified["canonical_game_id"].astype(str).tolist()) != ids
                or not np.array_equal(verified["home_score_draws"], home)
                or not np.array_equal(verified["away_score_draws"], away)
            ):
                raise NflM1IntegrityError(
                    "simulation archive failed exact reload verification"
                )
        unpublished_sha256 = _sha256_file(temporary)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    archive_sha256 = _sha256_file(path)
    if archive_sha256 != unpublished_sha256:
        raise NflM1IntegrityError("simulation archive changed during atomic publication")
    published_reconciliation = dict(reconciliation)
    if fold_lineage:
        published_reconciliation.pop("residualAuthoritySha256", None)
        published_reconciliation.pop("seed", None)
    record = {
        "candidateId": candidate_id,
        "scope": scope,
        "archivePath": str(path),
        "archiveSha256": archive_sha256,
        "archiveBytes": path.stat().st_size,
        "gameRows": simulation.n_games,
        "drawsPerGame": simulation.draws,
        "gameIdSha256": _sha256_bytes(_canonical_bytes(ids)),
        "drawValuesSha256": _sha256_bytes(home.tobytes(order="C") + away.tobytes(order="C")),
        "scoreDtype": "int32",
        "storageFormat": "NUMPY_NPZ_ALLOW_PICKLE_FALSE",
        "pickleUsed": False,
        "simulationContract": simulation.contract_version,
        "reconciliation": published_reconciliation,
    }
    if fold_lineage:
        record["residualAuthorityStatus"] = (
            "MULTIPLE_FOLD_LOCAL_AUTHORITIES_ENUMERATED"
        )
        record["seedStatus"] = "MULTIPLE_FOLD_LOCAL_SEEDS_ENUMERATED"
        record["foldLineage"] = [dict(value) for value in fold_lineage]
    else:
        record["residualAuthorityStatus"] = "SINGLE_AUTHORITY"
        record["residualAuthoritySha256"] = simulation.residual_authority_sha256
        record["seed"] = simulation.seed
    return record


def _persist_simulation_bundle(
    external_root: Path,
    *,
    scope: str,
    candidates: Mapping[str, tuple[Sequence[str], SimulatedScores]],
    candidate_fold_lineage: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Atomically persist and manifest every exact candidate simulation."""

    if not candidates:
        raise NflM1IntegrityError("simulation bundle has no candidates")
    records = []
    for candidate_id, (game_ids, simulation) in sorted(candidates.items()):
        if not candidate_id or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
            for character in candidate_id
        ):
            raise NflM1IntegrityError(f"unsafe simulation candidate identity: {candidate_id!r}")
        records.append(
            _atomic_simulation_archive(
                Path(external_root) / "simulations" / scope / f"{candidate_id}.npz",
                candidate_id=candidate_id,
                scope=scope,
                game_ids=game_ids,
                simulation=simulation,
                fold_lineage=(candidate_fold_lineage or {}).get(candidate_id),
            )
        )
    body = {
        "contract": SIMULATION_ARCHIVE_CONTRACT,
        "scope": scope,
        "candidateCount": len(records),
        "marketUsedForSelection": False,
        "archives": records,
    }
    manifest_path = Path(external_root) / "simulations" / scope / "manifest.json"
    manifest_sha256 = _atomic_json(manifest_path, body)
    if _sha256_file(manifest_path) != manifest_sha256:
        raise NflM1IntegrityError("simulation archive manifest changed after publication")
    return {
        "manifestPath": str(manifest_path),
        "manifestSha256": manifest_sha256,
        **body,
    }


def _complete_seasons_from_foundation_manifest(paths: FoundationPaths) -> tuple[int, ...]:
    manifest_path = (
        paths.foundation_root
        / "manifests"
        / "sha256"
        / paths.foundation_manifest_sha256
        / "foundation-manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_body = {
        key: value
        for key, value in manifest.items()
        if key not in {"manifestSha256", "datasetVersionId"}
    }
    actual_manifest_sha256 = _sha256_bytes(_canonical_bytes(manifest_body))
    expected_version = f"{manifest.get('datasetId')}:sha256:{actual_manifest_sha256}"
    if (
        actual_manifest_sha256 != paths.foundation_manifest_sha256
        or manifest.get("manifestSha256") != actual_manifest_sha256
        or manifest.get("datasetVersionId") != expected_version
        or paths.dataset_version_id != expected_version
    ):
        raise NflM1IntegrityError("NFL Foundation manifest identity changed")
    schedule_rows = (manifest.get("quality") or {}).get("scheduleBySeasonAndGameType") or []
    totals: dict[int, list[int]] = {}
    for row in schedule_rows:
        season = int(row["season"])
        values = totals.setdefault(season, [0, 0])
        values[0] += int(row["scheduledGames"])
        values[1] += int(row["completedGames"])
    complete = tuple(
        season
        for season, (scheduled, completed) in sorted(totals.items())
        if scheduled > 0 and completed == scheduled
    )
    if not complete:
        raise NflM1IntegrityError("foundation manifest identifies no completed NFL seasons")
    return complete


def _load_temporal_identity_rows(paths: FoundationPaths) -> list[dict[str, Any]]:
    # Selection needs membership and dates for the held-out season, never its
    # target values. Keep the outcome columns physically out of this read.
    columns = ["canonical_game_id", "season", "game_date"]
    frame = pd.read_parquet(paths.game_path, columns=columns, engine="pyarrow")
    frame["game_date"] = pd.to_datetime(frame["game_date"], errors="raise").dt.date
    frame = frame.sort_values(["game_date", "canonical_game_id"], kind="mergesort").reset_index(drop=True)
    if len(frame) != paths.game_row_count or frame["canonical_game_id"].astype(str).duplicated().any():
        raise NflM1IntegrityError("temporal identity authority differs from registered Gold")
    return frame.to_dict(orient="records")


def _load_development_gold(paths: FoundationPaths, design: TemporalDesign) -> pd.DataFrame:
    columns = tuple(dict.fromkeys((*ID_COLUMNS, *paths.game_ordered_predictors)))
    frame = pd.read_parquet(
        paths.game_path,
        columns=list(columns),
        filters=[("season", "<", int(design.final_oot_season))],
        engine="pyarrow",
    )
    frame["game_date"] = pd.to_datetime(frame["game_date"], errors="raise").dt.date
    frame = frame.sort_values(["game_date", "canonical_game_id"], kind="mergesort").reset_index(drop=True)
    expected_ids = set(design.folds[-1].train_game_ids) | set(design.folds[-1].validation_game_ids)
    actual_ids = set(frame["canonical_game_id"].astype(str))
    if actual_ids != expected_ids or len(frame) != len(expected_ids):
        raise NflM1IntegrityError("development Gold differs from frozen temporal membership")
    if frame["canonical_game_id"].astype(str).duplicated().any() or int(frame["season"].max()) >= design.final_oot_season:
        raise NflM1IntegrityError("development Gold intersects final OOT")
    return frame


def _development_frame(frame: pd.DataFrame, design: TemporalDesign) -> pd.DataFrame:
    authorized = set(design.oof_game_ids)
    earlier = frame[frame["season"] < min(f.validation_season for f in design.folds)]
    oof = frame[frame["canonical_game_id"].isin(authorized)]
    development = pd.concat([earlier, oof], ignore_index=True).sort_values(
        ["game_date", "canonical_game_id"], kind="mergesort"
    ).reset_index(drop=True)
    if int(development["season"].max()) != 2024 or set(development["canonical_game_id"]) & set(design.final_oot_game_ids):
        raise NflM1IntegrityError("development population intersects final OOT")
    return development


def _fold_rows(frame: pd.DataFrame, game_ids: Sequence[str]) -> pd.DataFrame:
    wanted = set(str(value) for value in game_ids)
    result = frame[frame["canonical_game_id"].isin(wanted)].copy()
    result = result.sort_values(["game_date", "canonical_game_id"], kind="mergesort").reset_index(drop=True)
    if len(result) != len(wanted) or set(result["canonical_game_id"]) != wanted:
        raise NflM1IntegrityError("fold membership does not reconcile with the Gold frame")
    return result


def _home_win_truth(frame: pd.DataFrame) -> np.ndarray:
    # The frozen binary event is literally home team wins; tied finals are non-wins.
    return (frame["home_points"].to_numpy(float) > frame["away_points"].to_numpy(float)).astype(int)


def _loss_vector(truth: np.ndarray, probability: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(probability, float), 1e-12, 1.0 - 1e-12)
    y = np.asarray(truth, float)
    return -(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))


def _metric_row(ledger: pd.DataFrame) -> dict[str, Any]:
    truth = ledger["actual_home_win"].to_numpy(int)
    probability = ledger["predicted_home_win_probability"].to_numpy(float)
    binary = binary_probability_metrics(truth, probability)
    result: dict[str, Any] = {
        "rows": len(ledger),
        **binary,
        "fitSeconds": float(ledger["fit_seconds"].sum()),
        "scoreSeconds": float(ledger["score_seconds"].sum()),
    }
    if ledger["predicted_home_points"].notna().all() and ledger["predicted_away_points"].notna().all():
        result.update(
            score_point_metrics(
                actual_home=ledger["actual_home_points"],
                actual_away=ledger["actual_away_points"],
                predicted_home=ledger["predicted_home_points"],
                predicted_away=ledger["predicted_away_points"],
            )
        )
    return result


def _ledger_rows(
    validation: pd.DataFrame,
    *,
    fold_id: str,
    candidate_id: str,
    family: str,
    recency: str,
    predicted_home: np.ndarray | None,
    predicted_away: np.ndarray | None,
    predicted_probability: np.ndarray,
    fit_seconds: float,
    score_seconds: float,
    training_rows: int,
    training_start_season: int,
    training_end_season: int,
) -> pd.DataFrame:
    count = len(validation)
    home = np.full(count, np.nan) if predicted_home is None else np.asarray(predicted_home, float)
    away = np.full(count, np.nan) if predicted_away is None else np.asarray(predicted_away, float)
    probability = np.asarray(predicted_probability, float)
    if home.size != count or away.size != count or probability.size != count:
        raise NflM1IntegrityError("candidate predictions do not align with validation rows")
    fit_timing = np.zeros(count, dtype=float)
    score_timing = np.zeros(count, dtype=float)
    if count:
        fit_timing[0] = float(fit_seconds)
        score_timing[0] = float(score_seconds)
    return pd.DataFrame(
        {
            "canonical_game_id": validation["canonical_game_id"].astype(str),
            "game_date": validation["game_date"].astype(str),
            "season": validation["season"].astype(int),
            "game_type": validation["game_type"].astype(str),
            "week": validation["week"].astype(int),
            "fold_id": fold_id,
            "candidate_id": candidate_id,
            "family": family,
            "feature_tier": "LONG_HISTORY_CORE",
            "recency_strategy": recency,
            "actual_home_points": validation["home_points"].astype(float),
            "actual_away_points": validation["away_points"].astype(float),
            "actual_home_win": _home_win_truth(validation),
            "actual_tie": validation["tie_game"].astype(int),
            "predicted_home_points": home,
            "predicted_away_points": away,
            "predicted_home_win_probability": probability,
            # Durations describe the fold execution, not every scored game.
            # Storing them once lets summary aggregation use an ordinary sum.
            "fit_seconds": fit_timing,
            "score_seconds": score_timing,
            "training_rows": int(training_rows),
            "training_start_season": int(training_start_season),
            "training_end_season": int(training_end_season),
        }
    )


def _run_score_candidate_oof(
    development: pd.DataFrame,
    design: TemporalDesign,
    features: tuple[str, ...],
    config: ScoreModelConfig,
    recency: RecencyStrategy,
    *,
    seed: int,
) -> pd.DataFrame:
    outputs = []
    seasons = development["season"].to_numpy(int)
    for index, fold in enumerate(design.folds):
        weights = recency_weights(seasons, fold.validation_season, recency)
        train = development.loc[weights.eligible_mask].reset_index(drop=True)
        validation = _fold_rows(development, fold.validation_game_ids)
        model = IndependentHomeAwayScoreModel(
            config=config,
            feature_names=features,
            categorical_features=tuple(name for name in CATEGORICAL_FEATURES if name in features),
            seed=seed + index * 101,
        )
        started = time.perf_counter()
        model.fit(
            train,
            train["home_points"],
            train["away_points"],
            sample_weight=weights.sample_weights[weights.eligible_mask],
            training_row_ids=train["canonical_game_id"].astype(str).tolist(),
        )
        fit_seconds = time.perf_counter() - started
        started = time.perf_counter()
        prediction = model.predict(validation)
        score_seconds = time.perf_counter() - started
        outputs.append(
            _ledger_rows(
                validation,
                fold_id=fold.fold_id,
                candidate_id=config.candidate_id,
                family=config.family,
                recency=recency.value,
                predicted_home=prediction.expected_home_points,
                predicted_away=prediction.expected_away_points,
                predicted_probability=prediction.home_win_probability,
                fit_seconds=fit_seconds,
                score_seconds=score_seconds,
                training_rows=len(train),
                training_start_season=int(train["season"].min()),
                training_end_season=int(train["season"].max()),
            )
        )
    result = pd.concat(outputs, ignore_index=True)
    if len(result) != design.oof_game_count or result["canonical_game_id"].duplicated().any():
        raise NflM1IntegrityError("score candidate did not produce genuine one-row-per-game OOF")
    return result


def _run_logistic_candidate_oof(
    development: pd.DataFrame,
    design: TemporalDesign,
    features: tuple[str, ...],
    c_value: float,
    recency: RecencyStrategy,
    *,
    seed: int,
) -> pd.DataFrame:
    outputs = []
    seasons = development["season"].to_numpy(int)
    candidate_id = f"home-win-logistic-c-{c_value:g}"
    for index, fold in enumerate(design.folds):
        weights = recency_weights(seasons, fold.validation_season, recency)
        train = development.loc[weights.eligible_mask].reset_index(drop=True)
        validation = _fold_rows(development, fold.validation_game_ids)
        model = RegularizedHomeWinModel(
            feature_names=features,
            categorical_features=tuple(name for name in CATEGORICAL_FEATURES if name in features),
            c_value=float(c_value),
            seed=seed + index * 101,
        )
        started = time.perf_counter()
        model.fit(
            train,
            _home_win_truth(train),
            sample_weight=weights.sample_weights[weights.eligible_mask],
            training_row_ids=train["canonical_game_id"].astype(str).tolist(),
        )
        fit_seconds = time.perf_counter() - started
        started = time.perf_counter()
        probability = model.predict_home_win_proba(validation)
        score_seconds = time.perf_counter() - started
        outputs.append(
            _ledger_rows(
                validation,
                fold_id=fold.fold_id,
                candidate_id=candidate_id,
                family="LOGISTIC_HOME_WIN",
                recency=recency.value,
                predicted_home=None,
                predicted_away=None,
                predicted_probability=probability,
                fit_seconds=fit_seconds,
                score_seconds=score_seconds,
                training_rows=len(train),
                training_start_season=int(train["season"].min()),
                training_end_season=int(train["season"].max()),
            )
        )
    result = pd.concat(outputs, ignore_index=True)
    if len(result) != design.oof_game_count or result["canonical_game_id"].duplicated().any():
        raise NflM1IntegrityError("win candidate did not produce genuine one-row-per-game OOF")
    return result


def _baseline_ledgers(development: pd.DataFrame, design: TemporalDesign) -> list[pd.DataFrame]:
    outputs: list[pd.DataFrame] = []
    for fold in design.folds:
        train = _fold_rows(development, fold.train_game_ids)
        validation = _fold_rows(development, fold.validation_game_ids)
        specifications = (
            ("league-home-team-prior", "LEAGUE_PRIOR", LeagueHomePrior()),
            ("rolling-scoring-margin-8", "ROLLING_SCORING", RollingScoringMarginBaseline(8)),
            ("elo-team-strength-baseline", "ELO", EloTeamStrengthBaseline()),
        )
        for candidate_id, family, model in specifications:
            started = time.perf_counter()
            if isinstance(model, LeagueHomePrior):
                model.fit(train["home_points"], train["away_points"])
            else:
                model.fit(train)
            fit_seconds = time.perf_counter() - started
            started = time.perf_counter()
            if isinstance(model, LeagueHomePrior):
                prediction = model.predict(len(validation))
            else:
                # Earlier validation dates update later dates, but every calendar
                # date is predicted before any truth from that date is applied.
                prediction = model.predict(validation, update_with_truth=True)
            score_seconds = time.perf_counter() - started
            outputs.append(
                _ledger_rows(
                    validation,
                    fold_id=fold.fold_id,
                    candidate_id=candidate_id,
                    family=family,
                    recency="CHRONOLOGICAL_NATIVE",
                    predicted_home=prediction.expected_home_points,
                    predicted_away=prediction.expected_away_points,
                    predicted_probability=prediction.home_win_probability,
                    fit_seconds=fit_seconds,
                    score_seconds=score_seconds,
                    training_rows=len(train),
                    training_start_season=int(train["season"].min()),
                    training_end_season=int(train["season"].max()),
                )
            )
    return [pd.concat([row for row in outputs if row["candidate_id"].iat[0] == candidate], ignore_index=True)
            for candidate in dict.fromkeys(row["candidate_id"].iat[0] for row in outputs)]


def summarize_point_ledgers(ledgers: Sequence[pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for ledger in ledgers:
        first = ledger.iloc[0]
        metric = _metric_row(ledger)
        rows.append(
            {
                "candidateId": first["candidate_id"],
                "family": first["family"],
                "featureTier": first["feature_tier"],
                "recencyStrategy": first["recency_strategy"],
                **metric,
            }
        )
    return pd.DataFrame(rows)


def _screening_configs() -> tuple[ScoreModelConfig, ...]:
    # One declared representative per family compares all six recency policies;
    # the remaining tiny grid is evaluated only after that family-level recency
    # decision, still using OOF evidence only.
    families = {}
    configs = [*RIDGE_SCORE_GRID, *HGB_SCORE_GRID, *EXTRA_TREES_SCORE_GRID]
    if bool(xgboost_capability().get("available")):
        configs.append(XGBOOST_SCORE_CONFIG)
    for config in configs:
        families.setdefault(config.family, config)
    return tuple(families.values())


def _all_score_configs() -> tuple[ScoreModelConfig, ...]:
    values = [*RIDGE_SCORE_GRID, *HGB_SCORE_GRID, *EXTRA_TREES_SCORE_GRID]
    if bool(xgboost_capability().get("available")):
        values.append(XGBOOST_SCORE_CONFIG)
    return tuple(values)


def _select_screening_recency(leaderboard: pd.DataFrame) -> dict[str, str]:
    selected = {}
    score = leaderboard[leaderboard["family"].isin({c.family for c in _screening_configs()})]
    for family, group in score.groupby("family", sort=True):
        row = group.sort_values(
            ["meanTeamPointsMae", "scoreDifferentialMae", "logLoss", "recencyStrategy"],
            kind="mergesort",
        ).iloc[0]
        selected[str(family)] = str(row["recencyStrategy"])
    logistic = leaderboard[(leaderboard["family"] == "LOGISTIC_HOME_WIN") & (leaderboard["candidateId"] == "home-win-logistic-c-1")]
    if not logistic.empty:
        selected["LOGISTIC_HOME_WIN"] = str(
            logistic.sort_values(["logLoss", "brierScore", "recencyStrategy"], kind="mergesort").iloc[0]["recencyStrategy"]
        )
    return selected


def _select_family_candidates(leaderboard: pd.DataFrame) -> dict[str, SelectedCandidate]:
    selected: dict[str, SelectedCandidate] = {}
    for family, group in leaderboard.groupby("family", sort=True):
        if family in {"LEAGUE_PRIOR", "ROLLING_SCORING", "ELO"}:
            continue
        if family == "LOGISTIC_HOME_WIN":
            row = group.sort_values(["logLoss", "brierScore", "candidateId"], kind="mergesort").iloc[0]
        else:
            row = group.sort_values(
                ["meanTeamPointsMae", "scoreDifferentialMae", "logLoss", "candidateId"], kind="mergesort"
            ).iloc[0]
        config = next((c for c in _all_score_configs() if c.candidate_id == row["candidateId"]), None)
        parameters: Mapping[str, Any]
        if family == "LOGISTIC_HOME_WIN":
            parameters = {"C": float(str(row["candidateId"]).rsplit("-", 1)[-1])}
        else:
            if config is None:
                raise NflM1IntegrityError(f"selected score candidate has no config: {row['candidateId']}")
            parameters = dict(config.parameters)
        selected[str(family)] = SelectedCandidate(
            family=str(family),
            candidate_id=str(row["candidateId"]),
            recency_strategy=str(row["recencyStrategy"]),
            parameters=parameters,
        )
    return selected


def run_oof_point_selection(
    development: pd.DataFrame,
    design: TemporalDesign,
    features: tuple[str, ...],
    *,
    seed: int,
    progress: Any | None = None,
) -> tuple[list[pd.DataFrame], pd.DataFrame, dict[str, SelectedCandidate]]:
    """Run bounded staged tuning without touching any final-OOT label."""

    assert_no_market_predictors(features)
    ledgers = _baseline_ledgers(development, design)
    completed: set[tuple[str, str]] = set()
    for config in _screening_configs():
        for recency in RECENCY_STRATEGIES:
            if progress is not None:
                progress(f"OOF screening {config.candidate_id} / {recency.value}")
            ledgers.append(
                _run_score_candidate_oof(development, design, features, config, recency, seed=seed)
            )
            completed.add((config.candidate_id, recency.value))
    for recency in RECENCY_STRATEGIES:
        if progress is not None:
            progress(f"OOF screening home-win-logistic-c-1 / {recency.value}")
        ledgers.append(
            _run_logistic_candidate_oof(development, design, features, 1.0, recency, seed=seed)
        )
        completed.add(("home-win-logistic-c-1", recency.value))

    screening = summarize_point_ledgers(ledgers)
    recency_by_family = _select_screening_recency(screening)
    for config in _all_score_configs():
        recency_name = recency_by_family.get(config.family)
        if recency_name is None or (config.candidate_id, recency_name) in completed:
            continue
        recency = RecencyStrategy(recency_name)
        if progress is not None:
            progress(f"OOF tuning {config.candidate_id} / {recency.value}")
        ledgers.append(
            _run_score_candidate_oof(development, design, features, config, recency, seed=seed)
        )
        completed.add((config.candidate_id, recency.value))
    logistic_recency = RecencyStrategy(recency_by_family["LOGISTIC_HOME_WIN"])
    for c_value in WIN_LOGISTIC_C_GRID:
        candidate_id = f"home-win-logistic-c-{c_value:g}"
        if (candidate_id, logistic_recency.value) not in completed:
            if progress is not None:
                progress(f"OOF tuning {candidate_id} / {logistic_recency.value}")
            ledgers.append(
                _run_logistic_candidate_oof(
                    development, design, features, c_value, logistic_recency, seed=seed
                )
            )
    leaderboard = summarize_point_ledgers(ledgers)
    selected = _select_family_candidates(leaderboard)
    return ledgers, leaderboard, selected


@dataclass
class DistributionFoldResult:
    fold_id: str
    validation: pd.DataFrame
    calibration: pd.DataFrame
    simulation: SimulatedScores
    fit_seconds: float
    score_seconds: float


@dataclass
class DistributionCandidateResult:
    selected: SelectedCandidate
    folds: dict[str, DistributionFoldResult]
    ledger: pd.DataFrame
    summary: Mapping[str, Any]


def _config_for_selected(selected: SelectedCandidate) -> ScoreModelConfig:
    for config in _all_score_configs():
        if config.candidate_id == selected.candidate_id:
            return config
    raise NflM1IntegrityError(f"no declared score config for {selected.candidate_id}")


def _fit_score_at_cutoff(
    development: pd.DataFrame,
    *,
    cutoff_season: int,
    selected: SelectedCandidate,
    features: tuple[str, ...],
    seed: int,
) -> tuple[IndependentHomeAwayScoreModel, pd.DataFrame, np.ndarray, float]:
    strategy = RecencyStrategy(selected.recency_strategy)
    authority = recency_weights(development["season"].to_numpy(int), cutoff_season, strategy)
    train = development.loc[authority.eligible_mask].reset_index(drop=True)
    model = IndependentHomeAwayScoreModel(
        config=_config_for_selected(selected),
        feature_names=features,
        categorical_features=tuple(name for name in CATEGORICAL_FEATURES if name in features),
        seed=seed,
    )
    started = time.perf_counter()
    model.fit(
        train,
        train["home_points"],
        train["away_points"],
        sample_weight=authority.sample_weights[authority.eligible_mask],
        training_row_ids=train["canonical_game_id"].astype(str).tolist(),
    )
    return model, train, authority.sample_weights[authority.eligible_mask], time.perf_counter() - started


def _oos_residual_calibration(
    development: pd.DataFrame,
    *,
    calibration_season: int,
    selected: SelectedCandidate,
    features: tuple[str, ...],
    seed: int,
) -> tuple[pd.DataFrame, PairedResidualAuthority, float]:
    model, _, _, fit_seconds = _fit_score_at_cutoff(
        development,
        cutoff_season=calibration_season,
        selected=selected,
        features=features,
        seed=seed,
    )
    calibration = development[development["season"] == calibration_season].copy()
    calibration = calibration.sort_values(["game_date", "canonical_game_id"], kind="mergesort").reset_index(drop=True)
    if calibration.empty:
        raise NflM1IntegrityError(f"residual calibration season {calibration_season} is empty")
    prediction = model.predict(calibration)
    evidence = pd.DataFrame(
        {
            "canonical_game_id": calibration["canonical_game_id"].astype(str),
            "game_date": calibration["game_date"].astype(str),
            "season": calibration["season"].astype(int),
            "actual_home_points": calibration["home_points"].astype(float),
            "actual_away_points": calibration["away_points"].astype(float),
            "predicted_home_points": prediction.expected_home_points,
            "predicted_away_points": prediction.expected_away_points,
        }
    )
    residuals = PairedResidualAuthority.fit(
        actual_home=evidence["actual_home_points"],
        actual_away=evidence["actual_away_points"],
        predicted_home=evidence["predicted_home_points"],
        predicted_away=evidence["predicted_away_points"],
        row_ids=evidence["canonical_game_id"].tolist(),
        row_dates=evidence["game_date"].tolist(),
        training_end=evidence["game_date"].max(),
    )
    return evidence, residuals, fit_seconds


def _per_game_distribution_ledger(
    validation: pd.DataFrame,
    simulation: SimulatedScores,
    *,
    fold_id: str,
    candidate_id: str,
    family: str,
    recency_strategy: str,
    fit_seconds: float,
    score_seconds: float,
) -> pd.DataFrame:
    actual_home = validation["home_points"].to_numpy(int)
    actual_away = validation["away_points"].to_numpy(int)
    home = simulation.home.astype(float)
    away = simulation.away.astype(float)
    margin = home - away
    total = home + away
    p_home = np.mean(margin > 0.0, axis=1)
    p_away = np.mean(margin < 0.0, axis=1)
    p_tie = np.mean(margin == 0.0, axis=1)
    full = distribution_metrics(
        simulation,
        actual_home=actual_home,
        actual_away=actual_away,
    )
    lower = 0.05
    upper = 0.95
    home_bounds = np.quantile(home, [lower, upper], axis=1)
    away_bounds = np.quantile(away, [lower, upper], axis=1)
    margin_bounds = np.quantile(margin, [lower, upper], axis=1)
    total_bounds = np.quantile(total, [lower, upper], axis=1)
    actual_margin = actual_home - actual_away
    actual_total = actual_home + actual_away
    rows = []
    for index, game in validation.reset_index(drop=True).iterrows():
        compact = summarize_game_distribution(simulation, index, top_scores=5)
        rows.append(
            {
                "canonical_game_id": str(game["canonical_game_id"]),
                "game_date": str(game["game_date"]),
                "season": int(game["season"]),
                "game_type": str(game["game_type"]),
                "week": int(game["week"]),
                "fold_id": fold_id,
                "candidate_id": candidate_id,
                "family": family,
                "feature_tier": "LONG_HISTORY_CORE",
                "recency_strategy": recency_strategy,
                "actual_home_points": int(actual_home[index]),
                "actual_away_points": int(actual_away[index]),
                "actual_home_win": int(actual_margin[index] > 0),
                "actual_tie": int(actual_margin[index] == 0),
                "predicted_home_points": float(home[index].mean()),
                "predicted_away_points": float(away[index].mean()),
                "predicted_home_win_probability": float(p_home[index]),
                "predicted_away_win_probability": float(p_away[index]),
                "predicted_tie_probability": float(p_tie[index]),
                "expected_score_differential": compact["expectedScoreDifferential"],
                "expected_total_points": compact["expectedTotalPoints"],
                "score_differential_interval_90_lower": compact[
                    "scoreDifferentialInterval90"
                ][0],
                "score_differential_interval_90_upper": compact[
                    "scoreDifferentialInterval90"
                ][1],
                "total_points_interval_90_lower": compact["totalPointsInterval90"][0],
                "total_points_interval_90_upper": compact["totalPointsInterval90"][1],
                "most_likely_final_scores_json": _canonical_bytes(
                    compact["mostLikelyFinalScores"]
                ).decode("utf-8"),
                "overtime_probability": compact["overtimeProbability"],
                "overtime_probability_status": compact["overtimeProbabilityStatus"],
                "joint_score_nll": float(full["jointScoreNegativeLogLikelihoodByGame"][index]),
                "home_points_crps": empirical_crps(home[index], actual_home[index]),
                "away_points_crps": empirical_crps(away[index], actual_away[index]),
                "score_differential_crps": empirical_crps(margin[index], actual_margin[index]),
                "total_points_crps": empirical_crps(total[index], actual_total[index]),
                "home_interval_90_covered": int(home_bounds[0, index] <= actual_home[index] <= home_bounds[1, index]),
                "away_interval_90_covered": int(away_bounds[0, index] <= actual_away[index] <= away_bounds[1, index]),
                "margin_interval_90_covered": int(margin_bounds[0, index] <= actual_margin[index] <= margin_bounds[1, index]),
                "total_interval_90_covered": int(total_bounds[0, index] <= actual_total[index] <= total_bounds[1, index]),
                "fit_seconds": float(fit_seconds) if index == 0 else 0.0,
                "score_seconds": float(score_seconds) if index == 0 else 0.0,
                "draws": simulation.draws,
                "simulation_contract_version": simulation.contract_version,
                "residual_authority_sha256": simulation.residual_authority_sha256,
            }
        )
    return pd.DataFrame(rows)


def _concatenate_oof_simulation(
    result: DistributionCandidateResult,
    design: TemporalDesign,
) -> tuple[tuple[str, ...], SimulatedScores]:
    """Concatenate fold-local exact draws in frozen chronological fold order."""

    ids: list[str] = []
    home: list[np.ndarray] = []
    away: list[np.ndarray] = []
    predicted_home: list[np.ndarray] = []
    predicted_away: list[np.ndarray] = []
    residual_authorities: list[str] = []
    seeds: list[int] = []
    draws: int | None = None
    for fold in design.folds:
        item = result.folds.get(fold.fold_id)
        if item is None:
            raise NflM1IntegrityError(
                f"distribution candidate lacks frozen fold {fold.fold_id}"
            )
        fold_ids = tuple(item.validation["canonical_game_id"].astype(str))
        if fold_ids != fold.validation_game_ids:
            raise NflM1IntegrityError(
                f"distribution fold identities differ: {result.selected.candidate_id} / {fold.fold_id}"
            )
        if draws is None:
            draws = item.simulation.draws
        elif item.simulation.draws != draws:
            raise NflM1IntegrityError("OOF simulation draw counts differ across folds")
        ids.extend(fold_ids)
        home.append(item.simulation.home)
        away.append(item.simulation.away)
        predicted_home.append(item.simulation.predicted_home_mean)
        predicted_away.append(item.simulation.predicted_away_mean)
        residual_authorities.append(item.simulation.residual_authority_sha256)
        seeds.append(item.simulation.seed)
    if tuple(ids) != tuple(
        result.ledger.sort_values(["game_date", "canonical_game_id"], kind="mergesort")[
            "canonical_game_id"
        ].astype(str)
    ):
        raise NflM1IntegrityError("combined OOF simulation differs from candidate ledger")
    combined = SimulatedScores(
        home=np.concatenate(home, axis=0),
        away=np.concatenate(away, axis=0),
        predicted_home_mean=np.concatenate(predicted_home),
        predicted_away_mean=np.concatenate(predicted_away),
        residual_authority_sha256=_sha256_bytes(_canonical_bytes(residual_authorities)),
        seed=int(_sha256_bytes(_canonical_bytes(seeds))[:15], 16),
    )
    reconcile_score_simulation(combined)
    return tuple(ids), combined


def _oof_simulation_candidates(
    results: Mapping[str, DistributionCandidateResult],
    ensemble: DistributionCandidateResult,
    design: TemporalDesign,
) -> dict[str, tuple[tuple[str, ...], SimulatedScores]]:
    candidates = {
        item.selected.candidate_id: _concatenate_oof_simulation(item, design)
        for item in results.values()
    }
    candidates[ensemble.selected.candidate_id] = _concatenate_oof_simulation(
        ensemble, design
    )
    if len(candidates) != len(results) + 1:
        raise NflM1IntegrityError("OOF simulation candidate identities collide")
    return candidates


def _oof_simulation_fold_lineage(
    results: Mapping[str, DistributionCandidateResult],
    ensemble: DistributionCandidateResult,
    design: TemporalDesign,
) -> dict[str, list[dict[str, Any]]]:
    lineage: dict[str, list[dict[str, Any]]] = {}
    for result in [*results.values(), ensemble]:
        records = []
        row_start = 0
        for fold in design.folds:
            simulation = result.folds[fold.fold_id].simulation
            row_stop = row_start + simulation.n_games
            records.append(
                {
                    "foldId": fold.fold_id,
                    "rowStartInclusive": row_start,
                    "rowStopExclusive": row_stop,
                    "gameRows": simulation.n_games,
                    "gameIdSha256": _sha256_bytes(
                        _canonical_bytes(fold.validation_game_ids)
                    ),
                    "residualAuthoritySha256": simulation.residual_authority_sha256,
                    "seed": simulation.seed,
                }
            )
            row_start = row_stop
        lineage[result.selected.candidate_id] = records
    return lineage


def _summarize_distribution_ledger(ledger: pd.DataFrame) -> dict[str, Any]:
    binary = binary_probability_metrics(
        ledger["actual_home_win"].to_numpy(int),
        ledger["predicted_home_win_probability"].to_numpy(float),
    )
    point = score_point_metrics(
        actual_home=ledger["actual_home_points"],
        actual_away=ledger["actual_away_points"],
        predicted_home=ledger["predicted_home_points"],
        predicted_away=ledger["predicted_away_points"],
    )
    return {
        "rows": len(ledger),
        **binary,
        **point,
        "jointScoreNegativeLogLikelihood": float(ledger["joint_score_nll"].mean()),
        "homePointsCrps": float(ledger["home_points_crps"].mean()),
        "awayPointsCrps": float(ledger["away_points_crps"].mean()),
        "scoreDifferentialCrps": float(ledger["score_differential_crps"].mean()),
        "totalPointsCrps": float(ledger["total_points_crps"].mean()),
        "homeInterval90Coverage": float(ledger["home_interval_90_covered"].mean()),
        "awayInterval90Coverage": float(ledger["away_interval_90_covered"].mean()),
        "marginInterval90Coverage": float(ledger["margin_interval_90_covered"].mean()),
        "totalInterval90Coverage": float(ledger["total_interval_90_covered"].mean()),
        "fitSeconds": float(ledger["fit_seconds"].sum()),
        "scoreSeconds": float(ledger["score_seconds"].sum()),
    }


def run_selected_distribution_oof(
    development: pd.DataFrame,
    design: TemporalDesign,
    features: tuple[str, ...],
    selected: SelectedCandidate,
    *,
    draws: int,
    seed: int,
) -> DistributionCandidateResult:
    if selected.family == "LOGISTIC_HOME_WIN":
        raise NflM1IntegrityError("a win-only model cannot create a joint score distribution")
    folds: dict[str, DistributionFoldResult] = {}
    ledgers = []
    for index, fold in enumerate(design.folds):
        model, _, _, fit_seconds = _fit_score_at_cutoff(
            development,
            cutoff_season=fold.validation_season,
            selected=selected,
            features=features,
            seed=seed + 10_000 + index * 307,
        )
        calibration, residuals, inner_fit_seconds = _oos_residual_calibration(
            development,
            calibration_season=fold.validation_season - 1,
            selected=selected,
            features=features,
            seed=seed + 20_000 + index * 307,
        )
        validation = _fold_rows(development, fold.validation_game_ids)
        started = time.perf_counter()
        point = model.predict(validation)
        randoms = make_common_random_numbers(
            n_games=len(validation), draws=draws, seed=seed + 30_000 + index
        )
        simulation = simulate_joint_scores(
            predicted_home_mean=point.expected_home_points,
            predicted_away_mean=point.expected_away_points,
            residual_authority=residuals,
            draws=draws,
            common_random_numbers=randoms,
        )
        reconcile_score_simulation(simulation)
        score_seconds = time.perf_counter() - started
        ledger = _per_game_distribution_ledger(
            validation,
            simulation,
            fold_id=fold.fold_id,
            candidate_id=selected.candidate_id,
            family=selected.family,
            recency_strategy=selected.recency_strategy,
            fit_seconds=fit_seconds + inner_fit_seconds,
            score_seconds=score_seconds,
        )
        folds[fold.fold_id] = DistributionFoldResult(
            fold_id=fold.fold_id,
            validation=validation,
            calibration=calibration,
            simulation=simulation,
            fit_seconds=fit_seconds + inner_fit_seconds,
            score_seconds=score_seconds,
        )
        ledgers.append(ledger)
    combined = pd.concat(ledgers, ignore_index=True)
    if len(combined) != design.oof_game_count or combined["canonical_game_id"].duplicated().any():
        raise NflM1IntegrityError("distribution candidate OOF coverage differs")
    return DistributionCandidateResult(
        selected=selected,
        folds=folds,
        ledger=combined,
        summary=_summarize_distribution_ledger(combined),
    )


def _ordered_candidate_matrix(
    results: Mapping[str, DistributionCandidateResult],
    *,
    fold_id: str | None = None,
    field: str,
) -> tuple[pd.DataFrame, np.ndarray, tuple[str, ...]]:
    families = tuple(sorted(results))
    frames = []
    for family in families:
        ledger = results[family].ledger
        if fold_id is not None:
            ledger = ledger[ledger["fold_id"] == fold_id]
        frames.append(
            ledger[["canonical_game_id", field]]
            .sort_values("canonical_game_id", kind="mergesort")
            .reset_index(drop=True)
        )
    reference = frames[0]["canonical_game_id"].tolist()
    if any(frame["canonical_game_id"].tolist() != reference for frame in frames[1:]):
        raise NflM1IntegrityError("candidate OOF ledgers are not identity-aligned")
    matrix = np.column_stack([frame[field].to_numpy(float) for frame in frames])
    return frames[0][["canonical_game_id"]], matrix, families


def _chronological_score_blend_weights(
    results: Mapping[str, DistributionCandidateResult],
    design: TemporalDesign,
) -> tuple[dict[str, tuple[float, ...]], tuple[float, ...], tuple[str, ...]]:
    _, _, families = _ordered_candidate_matrix(results, field="predicted_home_points")
    fold_weights: dict[str, tuple[float, ...]] = {}
    earlier_fold_ids: list[str] = []
    for fold in design.folds:
        if not earlier_fold_ids:
            fold_weights[fold.fold_id] = tuple(float(1.0 / len(families)) for _ in families)
        else:
            rows = []
            targets = []
            for field, actual in (
                ("predicted_home_points", "actual_home_points"),
                ("predicted_away_points", "actual_away_points"),
            ):
                subset_frames = []
                for family in families:
                    ledger = results[family].ledger
                    ledger = ledger[ledger["fold_id"].isin(earlier_fold_ids)].sort_values(
                        "canonical_game_id", kind="mergesort"
                    )
                    subset_frames.append(ledger)
                ids = subset_frames[0]["canonical_game_id"].tolist()
                if any(frame["canonical_game_id"].tolist() != ids for frame in subset_frames[1:]):
                    raise NflM1IntegrityError("chronological ensemble training rows differ")
                rows.append(np.column_stack([frame[field].to_numpy(float) for frame in subset_frames]))
                targets.append(subset_frames[0][actual].to_numpy(float))
            blend = fit_convex_blend(np.vstack(rows), np.concatenate(targets), objective="mse")
            fold_weights[fold.fold_id] = blend.weights
        earlier_fold_ids.append(fold.fold_id)

    full_rows = []
    full_targets = []
    for field, actual in (
        ("predicted_home_points", "actual_home_points"),
        ("predicted_away_points", "actual_away_points"),
    ):
        _, matrix, _ = _ordered_candidate_matrix(results, field=field)
        reference = results[families[0]].ledger.sort_values("canonical_game_id", kind="mergesort")
        full_rows.append(matrix)
        full_targets.append(reference[actual].to_numpy(float))
    final = fit_convex_blend(np.vstack(full_rows), np.concatenate(full_targets), objective="mse")
    return fold_weights, final.weights, families


def _fit_probability_blend(
    ensemble_probability: np.ndarray,
    logistic_probability: np.ndarray,
    truth: np.ndarray,
) -> tuple[float, float]:
    matrix = np.column_stack((ensemble_probability, logistic_probability))
    return fit_convex_blend(matrix, truth, objective="binary_log_loss").weights  # type: ignore[return-value]


def _tilt_simulation(
    simulation: SimulatedScores,
    target_home_win_probability: np.ndarray,
    *,
    seed: int,
) -> SimulatedScores:
    """Reweight/resample a joint PMF to a separately calibrated home-win mass.

    Conditional score distributions within HOME_WIN and NOT_HOME_WIN are
    retained; only their group mass changes.  The output therefore remains one
    coherent empirical joint distribution rather than a detached probability
    head.
    """

    target = np.clip(np.asarray(target_home_win_probability, float), 1e-4, 1.0 - 1e-4)
    if target.shape != (simulation.n_games,):
        raise NflM1IntegrityError("joint-distribution tilt probabilities do not align")
    rng = np.random.default_rng(seed)
    home_out = np.empty_like(simulation.home)
    away_out = np.empty_like(simulation.away)
    for game in range(simulation.n_games):
        wins = np.flatnonzero(simulation.home[game] > simulation.away[game])
        nonwins = np.flatnonzero(simulation.home[game] <= simulation.away[game])
        if wins.size == 0 or nonwins.size == 0:
            home_out[game] = simulation.home[game]
            away_out[game] = simulation.away[game]
            continue
        win_count = int(np.clip(round(target[game] * simulation.draws), 1, simulation.draws - 1))
        indices = np.concatenate(
            (
                rng.choice(wins, size=win_count, replace=True),
                rng.choice(nonwins, size=simulation.draws - win_count, replace=True),
            )
        )
        rng.shuffle(indices)
        home_out[game] = simulation.home[game, indices]
        away_out[game] = simulation.away[game, indices]
    digest = _sha256_bytes(
        _canonical_bytes(
            {
                "baseResidualAuthoritySha256": simulation.residual_authority_sha256,
                "tiltProbabilitySha256": _sha256_bytes(target.tobytes()),
                "seed": seed,
                "contract": "ASP_NFL_M1_COHERENT_HOME_WIN_MASS_TILT_V1",
            }
        )
    )
    result = SimulatedScores(
        home=home_out,
        away=away_out,
        predicted_home_mean=home_out.mean(axis=1),
        predicted_away_mean=away_out.mean(axis=1),
        residual_authority_sha256=digest,
        seed=seed,
    )
    reconcile_score_simulation(result)
    return result


def _fit_platt(probability: np.ndarray, truth: np.ndarray) -> tuple[float, float]:
    p = np.clip(np.asarray(probability, float), 1e-6, 1.0 - 1e-6)
    y = np.asarray(truth, float)
    logit = np.log(p / (1.0 - p))

    def objective(parameters: np.ndarray) -> float:
        linear = parameters[0] + parameters[1] * logit
        return float(np.mean(np.logaddexp(0.0, linear) - y * linear))

    fitted = minimize(objective, np.asarray([0.0, 1.0]), method="BFGS")
    if not fitted.success or not np.isfinite(fitted.x).all():
        raise NflM1IntegrityError("OOF Platt calibration failed")
    return float(fitted.x[0]), float(fitted.x[1])


def _apply_platt(probability: np.ndarray, parameters: tuple[float, float]) -> np.ndarray:
    p = np.clip(np.asarray(probability, float), 1e-6, 1.0 - 1e-6)
    linear = parameters[0] + parameters[1] * np.log(p / (1.0 - p))
    return np.clip(1.0 / (1.0 + np.exp(-linear)), 1e-6, 1.0 - 1e-6)


@dataclass
class EnsembleSelection:
    score_families: tuple[str, ...]
    chronological_score_weights: Mapping[str, tuple[float, ...]]
    final_score_weights: tuple[float, ...]
    chronological_probability_weights: Mapping[str, tuple[float, float]]
    final_probability_weights: tuple[float, float]
    calibration_method: str
    chronological_platt: Mapping[str, tuple[float, float] | None]
    final_platt: tuple[float, float] | None


def build_oof_ensemble(
    results: Mapping[str, DistributionCandidateResult],
    logistic_ledger: pd.DataFrame,
    design: TemporalDesign,
    *,
    draws: int,
    seed: int,
) -> tuple[DistributionCandidateResult, EnsembleSelection]:
    fold_score_weights, final_score_weights, families = _chronological_score_blend_weights(results, design)
    raw_folds: dict[str, DistributionFoldResult] = {}
    raw_ledgers = []
    probability_weights: dict[str, tuple[float, float]] = {}
    earlier_fold_ids: list[str] = []
    for index, fold in enumerate(design.folds):
        weights = np.asarray(fold_score_weights[fold.fold_id], float)
        family_folds = [results[family].folds[fold.fold_id] for family in families]
        validation = family_folds[0].validation
        calibration = family_folds[0].calibration.copy()
        if any(
            item.validation["canonical_game_id"].tolist() != validation["canonical_game_id"].tolist()
            or item.calibration["canonical_game_id"].tolist() != calibration["canonical_game_id"].tolist()
            for item in family_folds[1:]
        ):
            raise NflM1IntegrityError("ensemble distribution inputs are not identity-aligned")
        predicted_home = np.column_stack(
            [item.simulation.home.mean(axis=1) for item in family_folds]
        ) @ weights
        predicted_away = np.column_stack(
            [item.simulation.away.mean(axis=1) for item in family_folds]
        ) @ weights
        calibration_home = np.column_stack(
            [item.calibration["predicted_home_points"].to_numpy(float) for item in family_folds]
        ) @ weights
        calibration_away = np.column_stack(
            [item.calibration["predicted_away_points"].to_numpy(float) for item in family_folds]
        ) @ weights
        calibration["predicted_home_points"] = calibration_home
        calibration["predicted_away_points"] = calibration_away
        residuals = PairedResidualAuthority.fit(
            actual_home=calibration["actual_home_points"],
            actual_away=calibration["actual_away_points"],
            predicted_home=calibration_home,
            predicted_away=calibration_away,
            row_ids=calibration["canonical_game_id"].tolist(),
            row_dates=calibration["game_date"].tolist(),
            training_end=calibration["game_date"].max(),
        )
        base = simulate_joint_scores(
            predicted_home_mean=predicted_home,
            predicted_away_mean=predicted_away,
            residual_authority=residuals,
            draws=draws,
            common_random_numbers=make_common_random_numbers(
                n_games=len(validation), draws=draws, seed=seed + 40_000 + index
            ),
        )
        joint_probability = np.mean(base.home > base.away, axis=1)
        logistic_fold = logistic_ledger[logistic_ledger["fold_id"] == fold.fold_id].sort_values(
            "canonical_game_id", kind="mergesort"
        )
        order = np.argsort(validation["canonical_game_id"].astype(str).to_numpy())
        inverse = np.empty_like(order)
        inverse[order] = np.arange(order.size)
        logistic_sorted_ids = logistic_fold["canonical_game_id"].astype(str).tolist()
        if logistic_sorted_ids != sorted(validation["canonical_game_id"].astype(str).tolist()):
            raise NflM1IntegrityError("logistic and score OOF identities differ")
        logistic_probability = logistic_fold["predicted_home_win_probability"].to_numpy(float)[inverse]
        if not earlier_fold_ids:
            p_weights = (1.0, 0.0)
        else:
            prior_joint = []
            prior_logistic = []
            prior_truth = []
            for earlier in earlier_fold_ids:
                prior_ledger = pd.concat(raw_ledgers, ignore_index=True)
                prior_ledger = prior_ledger[prior_ledger["fold_id"] == earlier].sort_values(
                    "canonical_game_id", kind="mergesort"
                )
                prior_log = logistic_ledger[logistic_ledger["fold_id"] == earlier].sort_values(
                    "canonical_game_id", kind="mergesort"
                )
                prior_joint.extend(prior_ledger["score_only_home_win_probability"].tolist())
                prior_logistic.extend(prior_log["predicted_home_win_probability"].tolist())
                prior_truth.extend(prior_ledger["actual_home_win"].tolist())
            p_weights = _fit_probability_blend(
                np.asarray(prior_joint), np.asarray(prior_logistic), np.asarray(prior_truth)
            )
        probability_weights[fold.fold_id] = p_weights
        target_probability = p_weights[0] * joint_probability + p_weights[1] * logistic_probability
        tilted = _tilt_simulation(base, target_probability, seed=seed + 50_000 + index)
        ledger = _per_game_distribution_ledger(
            validation,
            tilted,
            fold_id=fold.fold_id,
            candidate_id="development-cross-fitted-score-win-ensemble",
            family="ENSEMBLE",
            recency_strategy="COMPONENT_SPECIFIC_OOF_SELECTED",
            fit_seconds=sum(item.fit_seconds for item in family_folds),
            score_seconds=sum(item.score_seconds for item in family_folds),
        )
        # Preserve the pure score-distribution probability. The reported fold
        # ledger is an honest chronological score+Logistic blend, while the
        # final meta-weights must be fitted on the exact pure-score + Logistic
        # inputs that will also be supplied at final OOT.
        ledger["score_only_home_win_probability"] = joint_probability
        raw_ledgers.append(ledger)
        raw_folds[fold.fold_id] = DistributionFoldResult(
            fold_id=fold.fold_id,
            validation=validation,
            calibration=calibration,
            simulation=tilted,
            fit_seconds=sum(item.fit_seconds for item in family_folds),
            score_seconds=sum(item.score_seconds for item in family_folds),
        )
        earlier_fold_ids.append(fold.fold_id)

    raw_combined = pd.concat(raw_ledgers, ignore_index=True)
    # Genuine chronological calibration: fold 1 stays identity; later folds use
    # only earlier OOF labels.  The decision to keep or reject Platt is made on
    # these cross-fitted predictions, never on labels used to fit their mapping.
    platt_by_fold: dict[str, tuple[float, float] | None] = {}
    calibrated_probability = np.empty(len(raw_combined), dtype=float)
    for fold in design.folds:
        validation_mask = raw_combined["fold_id"].to_numpy(str) == fold.fold_id
        earlier_mask = np.isin(
            raw_combined["fold_id"].to_numpy(str),
            [item.fold_id for item in design.folds if item.validation_season < fold.validation_season],
        )
        if not earlier_mask.any():
            platt_by_fold[fold.fold_id] = None
            calibrated_probability[validation_mask] = raw_combined.loc[
                validation_mask, "predicted_home_win_probability"
            ]
        else:
            parameters = _fit_platt(
                raw_combined.loc[earlier_mask, "predicted_home_win_probability"].to_numpy(float),
                raw_combined.loc[earlier_mask, "actual_home_win"].to_numpy(int),
            )
            platt_by_fold[fold.fold_id] = parameters
            calibrated_probability[validation_mask] = _apply_platt(
                raw_combined.loc[validation_mask, "predicted_home_win_probability"].to_numpy(float),
                parameters,
            )
    truth = raw_combined["actual_home_win"].to_numpy(int)
    raw_loss = float(_loss_vector(truth, raw_combined["predicted_home_win_probability"].to_numpy(float)).mean())
    calibrated_loss = float(_loss_vector(truth, calibrated_probability).mean())
    calibration_method = "PLATT_LOGIT" if calibrated_loss < raw_loss else "NONE"
    final_platt = None
    final_ledgers = []
    final_folds: dict[str, DistributionFoldResult] = {}
    for index, fold in enumerate(design.folds):
        item = raw_folds[fold.fold_id]
        if calibration_method == "PLATT_LOGIT":
            mask = raw_combined["fold_id"] == fold.fold_id
            target_probability = calibrated_probability[mask.to_numpy()]
            simulation = _tilt_simulation(
                item.simulation, target_probability, seed=seed + 60_000 + index
            )
        else:
            simulation = item.simulation
        ledger = _per_game_distribution_ledger(
            item.validation,
            simulation,
            fold_id=fold.fold_id,
            candidate_id="development-cross-fitted-score-win-ensemble",
            family="ENSEMBLE",
            recency_strategy="COMPONENT_SPECIFIC_OOF_SELECTED",
            fit_seconds=item.fit_seconds,
            score_seconds=item.score_seconds,
        )
        final_ledgers.append(ledger)
        final_folds[fold.fold_id] = DistributionFoldResult(
            fold_id=fold.fold_id,
            validation=item.validation,
            calibration=item.calibration,
            simulation=simulation,
            fit_seconds=item.fit_seconds,
            score_seconds=item.score_seconds,
        )
    combined = pd.concat(final_ledgers, ignore_index=True)
    ordered_raw = raw_combined.sort_values("canonical_game_id", kind="mergesort")
    ordered_log = logistic_ledger.sort_values("canonical_game_id", kind="mergesort")
    if ordered_raw["canonical_game_id"].tolist() != ordered_log["canonical_game_id"].tolist():
        raise NflM1IntegrityError("final probability blend OOF identities differ")
    final_probability_weights = _fit_probability_blend(
        ordered_raw["score_only_home_win_probability"].to_numpy(float),
        ordered_log["predicted_home_win_probability"].to_numpy(float),
        ordered_raw["actual_home_win"].to_numpy(int),
    )
    final_blend_probability = (
        final_probability_weights[0]
        * ordered_raw["score_only_home_win_probability"].to_numpy(float)
        + final_probability_weights[1]
        * ordered_log["predicted_home_win_probability"].to_numpy(float)
    )
    if calibration_method == "PLATT_LOGIT":
        # ``final_blend_probability`` follows canonical-game order.  Keep its
        # truth vector in that identical order; using concatenation order here
        # would silently misalign labels whenever Platt wins OOF selection.
        final_platt = _fit_platt(
            final_blend_probability,
            ordered_raw["actual_home_win"].to_numpy(int),
        )
    selection = EnsembleSelection(
        score_families=families,
        chronological_score_weights=fold_score_weights,
        final_score_weights=final_score_weights,
        chronological_probability_weights=probability_weights,
        final_probability_weights=final_probability_weights,
        calibration_method=calibration_method,
        chronological_platt=platt_by_fold,
        final_platt=final_platt,
    )
    result = DistributionCandidateResult(
        selected=SelectedCandidate(
            family="ENSEMBLE",
            candidate_id="development-cross-fitted-score-win-ensemble",
            recency_strategy="COMPONENT_SPECIFIC_OOF_SELECTED",
            parameters={
                "scoreFamilies": list(families),
                "finalScoreWeights": list(final_score_weights),
                "finalProbabilityWeights": list(final_probability_weights),
                "calibrationMethod": calibration_method,
            },
        ),
        folds=final_folds,
        ledger=combined,
        summary=_summarize_distribution_ledger(combined),
    )
    return result, selection


@dataclass
class FinalScoreResult:
    selected: SelectedCandidate
    model: IndependentHomeAwayScoreModel
    calibration: pd.DataFrame
    simulation: SimulatedScores
    ledger: pd.DataFrame
    summary: Mapping[str, Any]


@dataclass
class FinalLogisticResult:
    selected: SelectedCandidate
    model: RegularizedHomeWinModel
    ledger: pd.DataFrame
    summary: Mapping[str, Any]


def _load_final_oot(paths: FoundationPaths, design: TemporalDesign) -> pd.DataFrame:
    columns = tuple(dict.fromkeys((*ID_COLUMNS, *paths.game_ordered_predictors)))
    frame = pd.read_parquet(
        paths.game_path,
        columns=list(columns),
        filters=[("season", "==", int(design.final_oot_season))],
    )
    frame["game_date"] = pd.to_datetime(frame["game_date"], errors="raise").dt.date
    frame = frame.sort_values(["game_date", "canonical_game_id"], kind="mergesort").reset_index(drop=True)
    if (
        len(frame) != design.final_oot_count
        or tuple(frame["canonical_game_id"].astype(str)) != design.final_oot_game_ids
    ):
        raise NflM1IntegrityError("final OOT physical rows differ from frozen membership")
    return frame


def score_selected_final_oot(
    development: pd.DataFrame,
    oot: pd.DataFrame,
    features: tuple[str, ...],
    selected: SelectedCandidate,
    *,
    draws: int,
    seed: int,
) -> FinalScoreResult:
    model, _, _, fit_seconds = _fit_score_at_cutoff(
        development,
        cutoff_season=int(oot["season"].min()),
        selected=selected,
        features=features,
        seed=seed,
    )
    calibration, residuals, inner_fit_seconds = _oos_residual_calibration(
        development,
        calibration_season=int(oot["season"].min()) - 1,
        selected=selected,
        features=features,
        seed=seed + 10_000,
    )
    started = time.perf_counter()
    point = model.predict(oot)
    simulation = simulate_joint_scores(
        predicted_home_mean=point.expected_home_points,
        predicted_away_mean=point.expected_away_points,
        residual_authority=residuals,
        draws=draws,
        common_random_numbers=make_common_random_numbers(
            n_games=len(oot), draws=draws, seed=seed + 20_000
        ),
    )
    score_seconds = time.perf_counter() - started
    ledger = _per_game_distribution_ledger(
        oot,
        simulation,
        fold_id="FINAL_OOT_2025",
        candidate_id=selected.candidate_id,
        family=selected.family,
        recency_strategy=selected.recency_strategy,
        fit_seconds=fit_seconds + inner_fit_seconds,
        score_seconds=score_seconds,
    )
    return FinalScoreResult(
        selected=selected,
        model=model,
        calibration=calibration,
        simulation=simulation,
        ledger=ledger,
        summary=_summarize_distribution_ledger(ledger),
    )


def score_selected_logistic_final_oot(
    development: pd.DataFrame,
    oot: pd.DataFrame,
    features: tuple[str, ...],
    selected: SelectedCandidate,
    *,
    seed: int,
) -> FinalLogisticResult:
    strategy = RecencyStrategy(selected.recency_strategy)
    authority = recency_weights(
        development["season"].to_numpy(int), int(oot["season"].min()), strategy
    )
    train = development.loc[authority.eligible_mask].reset_index(drop=True)
    c_value = float(selected.parameters["C"])
    model = RegularizedHomeWinModel(
        feature_names=features,
        categorical_features=tuple(name for name in CATEGORICAL_FEATURES if name in features),
        c_value=c_value,
        seed=seed,
    )
    started = time.perf_counter()
    model.fit(
        train,
        _home_win_truth(train),
        sample_weight=authority.sample_weights[authority.eligible_mask],
        training_row_ids=train["canonical_game_id"].astype(str).tolist(),
    )
    fit_seconds = time.perf_counter() - started
    started = time.perf_counter()
    probability = model.predict_home_win_proba(oot)
    score_seconds = time.perf_counter() - started
    ledger = _ledger_rows(
        oot,
        fold_id="FINAL_OOT_2025",
        candidate_id=selected.candidate_id,
        family=selected.family,
        recency=selected.recency_strategy,
        predicted_home=None,
        predicted_away=None,
        predicted_probability=probability,
        fit_seconds=fit_seconds,
        score_seconds=score_seconds,
        training_rows=len(train),
        training_start_season=int(train["season"].min()),
        training_end_season=int(train["season"].max()),
    )
    return FinalLogisticResult(selected=selected, model=model, ledger=ledger, summary=_metric_row(ledger))


def _fit_logistic_at_cutoff(
    frame: pd.DataFrame,
    *,
    cutoff_season: int,
    selected: SelectedCandidate,
    features: tuple[str, ...],
    seed: int,
) -> tuple[RegularizedHomeWinModel, pd.DataFrame]:
    strategy = RecencyStrategy(selected.recency_strategy)
    authority = recency_weights(frame["season"].to_numpy(int), cutoff_season, strategy)
    train = frame.loc[authority.eligible_mask].reset_index(drop=True)
    model = RegularizedHomeWinModel(
        feature_names=features,
        categorical_features=tuple(name for name in CATEGORICAL_FEATURES if name in features),
        c_value=float(selected.parameters["C"]),
        seed=seed,
    )
    model.fit(
        train,
        _home_win_truth(train),
        sample_weight=authority.sample_weights[authority.eligible_mask],
        training_row_ids=train["canonical_game_id"].astype(str).tolist(),
    )
    return model, train


def build_final_ensemble(
    score_results: Mapping[str, FinalScoreResult],
    logistic: FinalLogisticResult,
    selection: EnsembleSelection,
    oot: pd.DataFrame,
    *,
    draws: int,
    seed: int,
) -> tuple[SimulatedScores, pd.DataFrame, Mapping[str, Any]]:
    families = selection.score_families
    if set(families) != set(score_results):
        raise NflM1IntegrityError("final ensemble components differ from frozen OOF selection")
    ordered = [score_results[family] for family in families]
    weights = np.asarray(selection.final_score_weights, float)
    predicted_home = np.column_stack(
        [item.simulation.home.mean(axis=1) for item in ordered]
    ) @ weights
    predicted_away = np.column_stack(
        [item.simulation.away.mean(axis=1) for item in ordered]
    ) @ weights
    calibration = ordered[0].calibration.copy()
    if any(
        item.ledger["canonical_game_id"].tolist() != ordered[0].ledger["canonical_game_id"].tolist()
        or item.calibration["canonical_game_id"].tolist() != calibration["canonical_game_id"].tolist()
        for item in ordered[1:]
    ):
        raise NflM1IntegrityError("final ensemble component identities differ")
    calibration_home = np.column_stack(
        [item.calibration["predicted_home_points"].to_numpy(float) for item in ordered]
    ) @ weights
    calibration_away = np.column_stack(
        [item.calibration["predicted_away_points"].to_numpy(float) for item in ordered]
    ) @ weights
    residuals = PairedResidualAuthority.fit(
        actual_home=calibration["actual_home_points"],
        actual_away=calibration["actual_away_points"],
        predicted_home=calibration_home,
        predicted_away=calibration_away,
        row_ids=calibration["canonical_game_id"].tolist(),
        row_dates=calibration["game_date"].tolist(),
        training_end=calibration["game_date"].max(),
    )
    base = simulate_joint_scores(
        predicted_home_mean=predicted_home,
        predicted_away_mean=predicted_away,
        residual_authority=residuals,
        draws=draws,
        common_random_numbers=make_common_random_numbers(
            n_games=len(oot), draws=draws, seed=seed + 70_000
        ),
    )
    score_probability = np.mean(base.home > base.away, axis=1)
    logistic_probability = logistic.ledger["predicted_home_win_probability"].to_numpy(float)
    probability_weights = np.asarray(selection.final_probability_weights, float)
    target_probability = (
        probability_weights[0] * score_probability
        + probability_weights[1] * logistic_probability
    )
    if selection.calibration_method == "PLATT_LOGIT":
        if selection.final_platt is None:
            raise NflM1IntegrityError("frozen Platt selection lacks final OOF parameters")
        target_probability = _apply_platt(target_probability, selection.final_platt)
    tilted = _tilt_simulation(base, target_probability, seed=seed + 80_000)
    ledger = _per_game_distribution_ledger(
        oot,
        tilted,
        fold_id="FINAL_OOT_2025",
        candidate_id="frozen-score-win-ensemble",
        family="ENSEMBLE",
        recency_strategy="COMPONENT_SPECIFIC_OOF_SELECTED",
        fit_seconds=sum(float(item.ledger["fit_seconds"].sum()) for item in ordered)
        + float(logistic.ledger["fit_seconds"].sum()),
        score_seconds=sum(float(item.ledger["score_seconds"].sum()) for item in ordered)
        + float(logistic.ledger["score_seconds"].sum()),
    )
    return tilted, ledger, _summarize_distribution_ledger(ledger)


def _final_baseline_ledgers(
    development: pd.DataFrame,
    oot: pd.DataFrame,
) -> list[pd.DataFrame]:
    outputs = []
    specifications = (
        ("league-home-team-prior", "LEAGUE_PRIOR", LeagueHomePrior()),
        ("rolling-scoring-margin-8", "ROLLING_SCORING", RollingScoringMarginBaseline(8)),
        ("elo-team-strength-baseline", "ELO", EloTeamStrengthBaseline()),
    )
    for candidate_id, family, model in specifications:
        started = time.perf_counter()
        if isinstance(model, LeagueHomePrior):
            model.fit(development["home_points"], development["away_points"])
        else:
            model.fit(development)
        fit_seconds = time.perf_counter() - started
        started = time.perf_counter()
        if isinstance(model, LeagueHomePrior):
            prediction = model.predict(len(oot))
        else:
            prediction = model.predict(oot, update_with_truth=True)
        score_seconds = time.perf_counter() - started
        outputs.append(
            _ledger_rows(
                oot,
                fold_id="FINAL_OOT_2025",
                candidate_id=candidate_id,
                family=family,
                recency="CHRONOLOGICAL_NATIVE",
                predicted_home=prediction.expected_home_points,
                predicted_away=prediction.expected_away_points,
                predicted_probability=prediction.home_win_probability,
                fit_seconds=fit_seconds,
                score_seconds=score_seconds,
                training_rows=len(development),
                training_start_season=int(development["season"].min()),
                training_end_season=int(development["season"].max()),
            )
        )
    return outputs


def _american_probability(values: pd.Series) -> np.ndarray:
    odds = pd.to_numeric(values, errors="coerce").to_numpy(float)
    probability = np.full(odds.shape, np.nan, dtype=float)
    negative = np.isfinite(odds) & (odds < 0.0)
    nonnegative = np.isfinite(odds) & ~negative
    probability[negative] = -odds[negative] / (-odds[negative] + 100.0)
    probability[nonnegative] = 100.0 / (odds[nonnegative] + 100.0)
    return probability


def _binary_metrics_or_unavailable(
    truth: np.ndarray,
    probability: np.ndarray,
    *,
    unavailable_status: str = "NOT_AVAILABLE_NO_COMPLETE_TWO_SIDED_PRICE",
) -> dict[str, Any]:
    if truth.size:
        return binary_probability_metrics(truth, probability)
    return {
        "rows": 0,
        "logLoss": None,
        "brierScore": None,
        "ece": None,
        "calibrationIntercept": None,
        "calibrationSlope": None,
        "calibrationStatus": unavailable_status,
        "accuracy": None,
    }


def _complete_numeric_rows(frame: pd.DataFrame, columns: Sequence[str]) -> np.ndarray:
    numeric = frame.loc[:, list(columns)].apply(pd.to_numeric, errors="coerce")
    return np.isfinite(numeric.to_numpy(float)).all(axis=1)


def _align_simulation_to_ids(
    game_ids: Sequence[str],
    simulation: SimulatedScores,
    target_ids: Sequence[str],
) -> SimulatedScores:
    source = tuple(str(value) for value in game_ids)
    target = tuple(str(value) for value in target_ids)
    if (
        len(source) != simulation.n_games
        or len(set(source)) != len(source)
        or set(source) != set(target)
    ):
        raise NflM1IntegrityError("market simulation identities differ")
    lookup = {game_id: index for index, game_id in enumerate(source)}
    order = np.asarray([lookup[game_id] for game_id in target], dtype=np.int64)
    aligned = SimulatedScores(
        home=simulation.home[order],
        away=simulation.away[order],
        predicted_home_mean=simulation.predicted_home_mean[order],
        predicted_away_mean=simulation.predicted_away_mean[order],
        residual_authority_sha256=simulation.residual_authority_sha256,
        seed=simulation.seed,
        contract_version=simulation.contract_version,
    )
    reconcile_score_simulation(aligned)
    return aligned


def _subset_simulation(simulation: SimulatedScores, mask: np.ndarray) -> SimulatedScores:
    selection = np.asarray(mask, dtype=bool)
    if selection.shape != (simulation.n_games,) or not selection.any():
        raise NflM1IntegrityError("simulation subset mask is invalid or empty")
    return SimulatedScores(
        home=simulation.home[selection],
        away=simulation.away[selection],
        predicted_home_mean=simulation.predicted_home_mean[selection],
        predicted_away_mean=simulation.predicted_away_mean[selection],
        residual_authority_sha256=simulation.residual_authority_sha256,
        seed=simulation.seed,
        contract_version=simulation.contract_version,
    )


def _event_metric_columns(prefix: str, event: Mapping[str, Any]) -> dict[str, Any]:
    metrics = event.get("metrics")
    predicted_push = event.get("meanPredictedPushProbability")
    status = (
        metrics.get("calibrationStatus")
        if metrics is not None
        else "NOT_AVAILABLE_ALL_COMPLETE_LINE_ROWS_PUSH"
    )
    return {
        f"{prefix}Rows": int(event["eligibleRows"]),
        f"{prefix}ActualPushRows": int(event["pushRows"]),
        f"{prefix}MeanPredictedPushProbability": None
        if predicted_push is None
        else float(predicted_push),
        f"{prefix}LogLoss": None if metrics is None else metrics["logLoss"],
        f"{prefix}BrierScore": None if metrics is None else metrics["brierScore"],
        f"{prefix}Ece": None if metrics is None else metrics["ece"],
        f"{prefix}CalibrationIntercept": None
        if metrics is None
        else metrics["calibrationIntercept"],
        f"{prefix}CalibrationSlope": None
        if metrics is None
        else metrics["calibrationSlope"],
        f"{prefix}CalibrationStatus": status,
        f"{prefix}Accuracy": None if metrics is None else metrics["accuracy"],
    }


def _unavailable_event_columns(prefix: str, status: str) -> dict[str, Any]:
    return {
        f"{prefix}Rows": 0,
        f"{prefix}ActualPushRows": 0,
        f"{prefix}MeanPredictedPushProbability": None,
        f"{prefix}LogLoss": None,
        f"{prefix}BrierScore": None,
        f"{prefix}Ece": None,
        f"{prefix}CalibrationIntercept": None,
        f"{prefix}CalibrationSlope": None,
        f"{prefix}CalibrationStatus": status,
        f"{prefix}Accuracy": None,
    }


def _sportsbook_event_metrics(
    *,
    detail: pd.DataFrame,
    mask: np.ndarray,
    probability: np.ndarray,
    event: str,
) -> dict[str, Any]:
    if event == "homeCover":
        adjusted = (
            detail["actual_margin"].to_numpy(float)
            - pd.to_numeric(detail["spread_line"], errors="coerce").to_numpy(float)
        )
    elif event == "over":
        adjusted = (
            detail["actual_total"].to_numpy(float)
            - pd.to_numeric(detail["total_line"], errors="coerce").to_numpy(float)
        )
    else:
        raise NflM1IntegrityError(f"unknown market line event: {event}")
    eligible = mask & (adjusted != 0.0)
    actual_pushes = mask & (adjusted == 0.0)
    metrics = _binary_metrics_or_unavailable(
        (adjusted[eligible] > 0.0).astype(int),
        probability[eligible],
        unavailable_status=(
            "NOT_AVAILABLE_ALL_COMPLETE_LINE_ROWS_PUSH"
            if mask.any()
            else "NOT_AVAILABLE_NO_COMPLETE_TWO_SIDED_PRICE"
        ),
    )
    return {
        "eligibleRows": int(eligible.sum()),
        "pushRows": int(actual_pushes.sum()),
        "meanPredictedPushProbability": None,
        "metrics": metrics if eligible.any() else None,
        "status": metrics["calibrationStatus"],
    }


def market_comparison_table(
    paths: FoundationPaths,
    oot: pd.DataFrame,
    candidate_ledgers: Mapping[str, pd.DataFrame],
    candidate_simulations: Mapping[
        str, tuple[Sequence[str], SimulatedScores]
    ] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    market = pd.read_parquet(paths.market_path)
    market = market[market["canonical_game_id"].isin(set(oot["canonical_game_id"]))].copy()
    if market["canonical_game_id"].duplicated().any():
        raise NflM1IntegrityError("final OOT market evidence has duplicate game identities")
    market_ids = set(market["canonical_game_id"].astype(str))
    truth = oot[["canonical_game_id", "home_points", "away_points"]].copy()
    truth = truth.sort_values("canonical_game_id", kind="mergesort").reset_index(drop=True)
    detail = truth.merge(
        market,
        on="canonical_game_id",
        how="left",
        validate="one_to_one",
        sort=False,
    )
    detail["market_row_available"] = detail["canonical_game_id"].astype(str).isin(market_ids)
    detail["complete_moneyline"] = _complete_numeric_rows(
        detail, ("home_moneyline", "away_moneyline")
    )
    # Zero is not a valid American price and must not become an artificial 100%
    # implied probability.
    detail["complete_moneyline"] &= (
        pd.to_numeric(detail["home_moneyline"], errors="coerce") != 0.0
    ) & (pd.to_numeric(detail["away_moneyline"], errors="coerce") != 0.0)
    detail["complete_spread"] = _complete_numeric_rows(
        detail, ("spread_line", "home_spread_price", "away_spread_price")
    )
    detail["complete_spread"] &= (
        pd.to_numeric(detail["home_spread_price"], errors="coerce") != 0.0
    ) & (pd.to_numeric(detail["away_spread_price"], errors="coerce") != 0.0)
    detail["complete_total"] = _complete_numeric_rows(
        detail, ("total_line", "over_price", "under_price")
    )
    detail["complete_total"] &= (
        pd.to_numeric(detail["over_price"], errors="coerce") != 0.0
    ) & (pd.to_numeric(detail["under_price"], errors="coerce") != 0.0)
    moneyline_mask = detail["complete_moneyline"].to_numpy(bool)
    no_vig_home = np.full(len(detail), np.nan, dtype=float)
    if moneyline_mask.any():
        home_implied = _american_probability(detail.loc[moneyline_mask, "home_moneyline"])
        away_implied = _american_probability(detail.loc[moneyline_mask, "away_moneyline"])
        no_vig_home[moneyline_mask] = home_implied / (home_implied + away_implied)
    actual_home_win = (
        detail["home_points"].to_numpy(float) > detail["away_points"].to_numpy(float)
    ).astype(int)
    actual_moneyline_push = (
        detail["home_points"].to_numpy(float) == detail["away_points"].to_numpy(float)
    )
    moneyline_evaluation_mask = moneyline_mask & ~actual_moneyline_push
    market_binary = _binary_metrics_or_unavailable(
        actual_home_win[moneyline_evaluation_mask],
        no_vig_home[moneyline_evaluation_mask],
    )
    rows = []
    detail["market_home_probability_no_vig"] = no_vig_home
    detail["actual_home_win"] = actual_home_win
    detail["actual_moneyline_push"] = actual_moneyline_push
    detail["moneyline_evaluation_eligible"] = moneyline_evaluation_mask
    detail["actual_margin"] = detail["home_points"].to_numpy(float) - detail["away_points"].to_numpy(float)
    detail["actual_total"] = detail["home_points"].to_numpy(float) + detail["away_points"].to_numpy(float)
    spread_mask = detail["complete_spread"].to_numpy(bool)
    total_mask = detail["complete_total"].to_numpy(bool)
    market_home_cover = np.full(len(detail), np.nan, dtype=float)
    if spread_mask.any():
        home_spread_implied = _american_probability(
            detail.loc[spread_mask, "home_spread_price"]
        )
        away_spread_implied = _american_probability(
            detail.loc[spread_mask, "away_spread_price"]
        )
        market_home_cover[spread_mask] = home_spread_implied / (
            home_spread_implied + away_spread_implied
        )
    market_over = np.full(len(detail), np.nan, dtype=float)
    if total_mask.any():
        over_implied = _american_probability(detail.loc[total_mask, "over_price"])
        under_implied = _american_probability(detail.loc[total_mask, "under_price"])
        market_over[total_mask] = over_implied / (over_implied + under_implied)
    detail["market_home_cover_probability_no_vig"] = market_home_cover
    detail["market_over_probability_no_vig"] = market_over
    # nflverse ``spread_line`` is the market's projected home scoring margin
    # (positive means the home team is favored), not the signed home handicap.
    # Therefore a home cover is home margin > spread_line, while the equivalent
    # additive handicap passed to the generic simulator evaluator is -spread_line.
    detail["market_projected_margin"] = np.where(
        spread_mask, pd.to_numeric(detail["spread_line"], errors="coerce"), np.nan
    )
    detail["market_margin_absolute_error"] = np.where(
        spread_mask,
        np.abs(detail["market_projected_margin"] - detail["actual_margin"]),
        np.nan,
    )
    detail["market_total_absolute_error"] = np.where(
        total_mask,
        np.abs(pd.to_numeric(detail["total_line"], errors="coerce") - detail["actual_total"]),
        np.nan,
    )
    sportsbook_cover = _sportsbook_event_metrics(
        detail=detail,
        mask=spread_mask,
        probability=market_home_cover,
        event="homeCover",
    )
    sportsbook_over = _sportsbook_event_metrics(
        detail=detail,
        mask=total_mask,
        probability=market_over,
        event="over",
    )
    sportsbook_line_fields = {
        **(
            _event_metric_columns("homeCover", sportsbook_cover)
            if spread_mask.any()
            else _unavailable_event_columns(
                "homeCover", "NOT_AVAILABLE_NO_COMPLETE_TWO_SIDED_PRICE"
            )
        ),
        **(
            _event_metric_columns("over", sportsbook_over)
            if total_mask.any()
            else _unavailable_event_columns(
                "over", "NOT_AVAILABLE_NO_COMPLETE_TWO_SIDED_PRICE"
            )
        ),
    }
    rows.append(
        {
            "candidateId": "SPORTSBOOK_NO_VIG",
            "timingSemantics": "MARKET_SNAPSHOT_TIMING_UNPROVEN",
            "moneylineProbabilitySemantics": "TWO_SIDED_NO_VIG_CONDITIONAL_ON_NONPUSH",
            "moneylineActualPushRows": int((moneyline_mask & actual_moneyline_push).sum()),
            "lineProbabilitySemantics": "TWO_SIDED_NO_VIG_CONDITIONAL_ON_NONPUSH",
            **market_binary,
            **sportsbook_line_fields,
            "scoreDifferentialMae": float(detail["market_margin_absolute_error"].mean()),
            "totalPointsMae": float(detail["market_total_absolute_error"].mean()),
        }
    )
    simulations = candidate_simulations or {}
    unknown_simulations = set(simulations) - set(candidate_ledgers)
    if unknown_simulations:
        raise NflM1IntegrityError(
            f"market simulations lack matching ledgers: {sorted(unknown_simulations)}"
        )
    for candidate_id, ledger in candidate_ledgers.items():
        aligned = ledger.sort_values("canonical_game_id", kind="mergesort").reset_index(drop=True)
        if aligned["canonical_game_id"].tolist() != detail["canonical_game_id"].tolist():
            raise NflM1IntegrityError(f"market comparison identities differ: {candidate_id}")
        probability = aligned["predicted_home_win_probability"].to_numpy(float)
        simulation: SimulatedScores | None = None
        market_probability = probability.copy()
        simulated_moneyline_push = np.full(len(detail), np.nan, dtype=float)
        if candidate_id in simulations:
            simulation_ids, unaligned_simulation = simulations[candidate_id]
            simulation = _align_simulation_to_ids(
                simulation_ids,
                unaligned_simulation,
                detail["canonical_game_id"].astype(str).tolist(),
            )
            simulated_home_win = np.mean(simulation.home > simulation.away, axis=1)
            simulated_away_win = np.mean(simulation.home < simulation.away, axis=1)
            simulated_moneyline_push = np.mean(
                simulation.home == simulation.away, axis=1
            )
            nonpush = simulated_home_win + simulated_away_win
            market_probability = np.divide(
                simulated_home_win,
                nonpush,
                out=np.full(simulated_home_win.shape, 0.5),
                where=nonpush > 0.0,
            )
        binary = _binary_metrics_or_unavailable(
            actual_home_win[moneyline_evaluation_mask],
            market_probability[moneyline_evaluation_mask],
        )
        row = {
            "candidateId": candidate_id,
            "timingSemantics": "MODEL_PREGAME_VS_MARKET_SNAPSHOT_TIMING_UNPROVEN",
            "moneylineProbabilitySemantics": (
                "SIMULATED_HOME_WIN_CONDITIONAL_ON_NONPUSH_WITH_PUSH_MASS_REPORTED"
                if simulation is not None
                else "UNCONDITIONAL_HOME_WIN_TIE_MASS_NOT_IDENTIFIED"
            ),
            "moneylineActualPushRows": int(
                (moneyline_mask & actual_moneyline_push).sum()
            ),
            "moneylineMeanPredictedPushProbability": (
                float(np.mean(simulated_moneyline_push[moneyline_mask]))
                if simulation is not None and moneyline_mask.any()
                else None
            ),
            "lineProbabilitySemantics": (
                "SIMULATED_EVENT_PROBABILITY_CONDITIONAL_ON_NONPUSH_WITH_PUSH_MASS_REPORTED"
                if candidate_id in simulations
                else "NOT_AVAILABLE_NO_SCORE_DISTRIBUTION"
            ),
            **binary,
            "meanModelMinusMarketProbability": float(
                np.mean(
                    market_probability[moneyline_evaluation_mask]
                    - no_vig_home[moneyline_evaluation_mask]
                )
            )
            if moneyline_evaluation_mask.any()
            else None,
            "meanAbsoluteModelMarketDisagreement": float(
                np.mean(
                    np.abs(
                        market_probability[moneyline_evaluation_mask]
                        - no_vig_home[moneyline_evaluation_mask]
                    )
                )
            )
            if moneyline_evaluation_mask.any()
            else None,
        }
        if simulation is not None:
            home_cover_probability = np.full(len(detail), np.nan, dtype=float)
            spread_push_probability = np.full(len(detail), np.nan, dtype=float)
            over_probability = np.full(len(detail), np.nan, dtype=float)
            total_push_probability = np.full(len(detail), np.nan, dtype=float)
            if spread_mask.any():
                adjusted_margin = (
                    simulation.home[spread_mask] - simulation.away[spread_mask]
                    - detail.loc[spread_mask, "spread_line"].to_numpy(float)[:, None]
                )
                cover = np.mean(adjusted_margin > 0.0, axis=1)
                push = np.mean(adjusted_margin == 0.0, axis=1)
                nonpush = 1.0 - push
                home_cover_probability[spread_mask] = np.divide(
                    cover,
                    nonpush,
                    out=np.full(cover.shape, 0.5),
                    where=nonpush > 0.0,
                )
                spread_push_probability[spread_mask] = push
            if total_mask.any():
                adjusted_total = (
                    simulation.home[total_mask] + simulation.away[total_mask]
                    - detail.loc[total_mask, "total_line"].to_numpy(float)[:, None]
                )
                over = np.mean(adjusted_total > 0.0, axis=1)
                push = np.mean(adjusted_total == 0.0, axis=1)
                nonpush = 1.0 - push
                over_probability[total_mask] = np.divide(
                    over,
                    nonpush,
                    out=np.full(over.shape, 0.5),
                    where=nonpush > 0.0,
                )
                total_push_probability[total_mask] = push
            detail[f"{candidate_id}_conditional_home_cover_probability"] = (
                home_cover_probability
            )
            detail[f"{candidate_id}_spread_push_probability"] = spread_push_probability
            detail[f"{candidate_id}_conditional_over_probability"] = over_probability
            detail[f"{candidate_id}_total_push_probability"] = total_push_probability
            detail[f"{candidate_id}_home_cover_probability_status"] = np.where(
                ~spread_mask,
                "NOT_AVAILABLE_NO_COMPLETE_TWO_SIDED_PRICE",
                np.where(
                    spread_push_probability == 1.0,
                    "UNIDENTIFIED_ALL_SIMULATED_MASS_PUSH",
                    "AVAILABLE_CONDITIONAL_ON_SIMULATED_NONPUSH",
                ),
            )
            detail[f"{candidate_id}_over_probability_status"] = np.where(
                ~total_mask,
                "NOT_AVAILABLE_NO_COMPLETE_TWO_SIDED_PRICE",
                np.where(
                    total_push_probability == 1.0,
                    "UNIDENTIFIED_ALL_SIMULATED_MASS_PUSH",
                    "AVAILABLE_CONDITIONAL_ON_SIMULATED_NONPUSH",
                ),
            )
            if spread_mask.any():
                spread_simulation = _subset_simulation(simulation, spread_mask)
                spread_events = line_event_metrics(
                    spread_simulation,
                    actual_home=detail.loc[spread_mask, "home_points"].to_numpy(int),
                    actual_away=detail.loc[spread_mask, "away_points"].to_numpy(int),
                    home_spread=-detail.loc[spread_mask, "spread_line"].to_numpy(float),
                    # The total branch is intentionally ignored in this call; the
                    # real total authority can have independent partial coverage.
                    total_line=np.zeros(int(spread_mask.sum()), dtype=float),
                )["homeCover"]
                row.update(_event_metric_columns("homeCover", spread_events))
            else:
                row.update(
                    _unavailable_event_columns(
                        "homeCover", "NOT_AVAILABLE_NO_COMPLETE_TWO_SIDED_PRICE"
                    )
                )
            if total_mask.any():
                total_simulation = _subset_simulation(simulation, total_mask)
                total_events = line_event_metrics(
                    total_simulation,
                    actual_home=detail.loc[total_mask, "home_points"].to_numpy(int),
                    actual_away=detail.loc[total_mask, "away_points"].to_numpy(int),
                    # The spread branch is ignored; zero is a finite dummy required
                    # by the shared line-event evaluator.
                    home_spread=np.zeros(int(total_mask.sum()), dtype=float),
                    total_line=detail.loc[total_mask, "total_line"].to_numpy(float),
                )["over"]
                row.update(_event_metric_columns("over", total_events))
            else:
                row.update(
                    _unavailable_event_columns(
                        "over", "NOT_AVAILABLE_NO_COMPLETE_TWO_SIDED_PRICE"
                    )
                )
        else:
            row.update(
                _unavailable_event_columns(
                    "homeCover", "NOT_AVAILABLE_NOT_A_SCORE_DISTRIBUTION_CANDIDATE"
                )
            )
            row.update(
                _unavailable_event_columns(
                    "over", "NOT_AVAILABLE_NOT_A_SCORE_DISTRIBUTION_CANDIDATE"
                )
            )
        if aligned["predicted_home_points"].notna().all():
            margin = aligned["predicted_home_points"].to_numpy(float) - aligned["predicted_away_points"].to_numpy(float)
            total = aligned["predicted_home_points"].to_numpy(float) + aligned["predicted_away_points"].to_numpy(float)
            row["scoreDifferentialMae"] = (
                float(np.mean(np.abs(margin[spread_mask] - detail.loc[spread_mask, "actual_margin"].to_numpy(float))))
                if spread_mask.any()
                else None
            )
            row["totalPointsMae"] = (
                float(np.mean(np.abs(total[total_mask] - detail.loc[total_mask, "actual_total"].to_numpy(float))))
                if total_mask.any()
                else None
            )
        rows.append(row)
        detail[f"{candidate_id}_home_probability"] = probability
        detail[f"{candidate_id}_market_conditional_home_probability"] = (
            market_probability
        )
        detail[f"{candidate_id}_moneyline_push_probability"] = (
            simulated_moneyline_push
        )
        detail[f"{candidate_id}_minus_market"] = market_probability - no_vig_home
    return pd.DataFrame(rows), detail


def _compact_market_line_metrics(row: pd.Series) -> dict[str, Any]:
    def value(name: str, *, integer: bool = False) -> Any:
        raw = row.get(name)
        if raw is None or pd.isna(raw):
            return None
        return int(raw) if integer else float(raw)

    return {
        "lineProbabilitySemantics": row.get("lineProbabilitySemantics"),
        "homeCover": {
            "rows": value("homeCoverRows", integer=True),
            "actualPushRows": value("homeCoverActualPushRows", integer=True),
            "meanPredictedPushProbability": value(
                "homeCoverMeanPredictedPushProbability"
            ),
            "logLoss": value("homeCoverLogLoss"),
            "brierScore": value("homeCoverBrierScore"),
            "ece": value("homeCoverEce"),
            "calibrationIntercept": value("homeCoverCalibrationIntercept"),
            "calibrationSlope": value("homeCoverCalibrationSlope"),
            "calibrationStatus": row.get("homeCoverCalibrationStatus"),
        },
        "over": {
            "rows": value("overRows", integer=True),
            "actualPushRows": value("overActualPushRows", integer=True),
            "meanPredictedPushProbability": value("overMeanPredictedPushProbability"),
            "logLoss": value("overLogLoss"),
            "brierScore": value("overBrierScore"),
            "ece": value("overEce"),
            "calibrationIntercept": value("overCalibrationIntercept"),
            "calibrationSlope": value("overCalibrationSlope"),
            "calibrationStatus": row.get("overCalibrationStatus"),
        },
    }


def _per_game_log_loss(ledger: pd.DataFrame) -> np.ndarray:
    return _loss_vector(
        ledger["actual_home_win"].to_numpy(int),
        ledger["predicted_home_win_probability"].to_numpy(float),
    )


def bootstrap_comparisons(
    *,
    ensemble: pd.DataFrame,
    best_single: pd.DataFrame,
    elo: pd.DataFrame,
    rolling: pd.DataFrame,
    market_detail: pd.DataFrame,
    resamples: int,
    seed: int,
) -> dict[str, Any]:
    def aligned(left: pd.DataFrame, right: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        a = left.sort_values("canonical_game_id", kind="mergesort").reset_index(drop=True)
        b = right.sort_values("canonical_game_id", kind="mergesort").reset_index(drop=True)
        if a["canonical_game_id"].tolist() != b["canonical_game_id"].tolist():
            raise NflM1IntegrityError("paired bootstrap identities differ")
        return a, b

    result: dict[str, Any] = {}
    for label, candidate, baseline in (
        ("ensemble_vs_best_single", ensemble, best_single),
        ("best_single_vs_elo", best_single, elo),
        ("best_single_vs_rolling", best_single, rolling),
    ):
        candidate, baseline = aligned(candidate, baseline)
        comparison = {
            "homeWinLogLoss": paired_whole_game_bootstrap(
                _per_game_log_loss(candidate),
                _per_game_log_loss(baseline),
                resamples=resamples,
                seed=seed,
            )
        }
        if candidate["predicted_home_points"].notna().all() and baseline["predicted_home_points"].notna().all():
            candidate_score = 0.5 * (
                np.abs(candidate["predicted_home_points"] - candidate["actual_home_points"])
                + np.abs(candidate["predicted_away_points"] - candidate["actual_away_points"])
            )
            baseline_score = 0.5 * (
                np.abs(baseline["predicted_home_points"] - baseline["actual_home_points"])
                + np.abs(baseline["predicted_away_points"] - baseline["actual_away_points"])
            )
            comparison["meanTeamPointsAbsoluteError"] = paired_whole_game_bootstrap(
                candidate_score,
                baseline_score,
                resamples=resamples,
                seed=seed + 1,
            )
        result[label] = comparison

    eligibility_column = (
        "moneyline_evaluation_eligible"
        if "moneyline_evaluation_eligible" in market_detail.columns
        else "complete_moneyline"
    )
    market = market_detail[market_detail[eligibility_column].astype(bool)].sort_values(
        "canonical_game_id", kind="mergesort"
    ).reset_index(drop=True)
    if market.empty:
        result["best_single_vs_market"] = {
            "homeWinLogLoss": {
                "games": 0,
                "resamples": int(resamples),
                "seed": int(seed + 2),
                "confidence": 0.95,
                "pointEstimate": None,
                "standardError": None,
                "lower": None,
                "upper": None,
                "differenceDirection": "CANDIDATE_MINUS_BASELINE",
                "status": "NOT_AVAILABLE_NO_COMPLETE_TWO_SIDED_PRICE",
            }
        }
    else:
        single = best_single[
            best_single["canonical_game_id"].isin(set(market["canonical_game_id"]))
        ].sort_values("canonical_game_id", kind="mergesort").reset_index(drop=True)
        if single["canonical_game_id"].tolist() != market["canonical_game_id"].tolist():
            raise NflM1IntegrityError("market bootstrap identities differ")
        candidate_id = str(single["candidate_id"].iat[0])
        conditional_column = (
            f"{candidate_id}_market_conditional_home_probability"
        )
        if conditional_column not in market.columns:
            raise NflM1IntegrityError(
                "market bootstrap lacks the candidate's non-push-conditioned probability"
            )
        candidate_loss = _loss_vector(
            market["actual_home_win"].to_numpy(int),
            market[conditional_column].to_numpy(float),
        )
        market_loss = _loss_vector(
            market["actual_home_win"].to_numpy(int),
            market["market_home_probability_no_vig"].to_numpy(float),
        )
        result["best_single_vs_market"] = {
            "homeWinLogLoss": paired_whole_game_bootstrap(
                candidate_loss, market_loss, resamples=resamples, seed=seed + 2
            )
        }
    return result


def _summary_row(
    candidate_id: str,
    family: str,
    scope: str,
    summary: Mapping[str, Any],
    *,
    feature_tier: str = "LONG_HISTORY_CORE",
    recency_strategy: str | None = None,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "family": family,
        "scope": scope,
        "feature_tier": feature_tier,
        "recency_strategy": recency_strategy,
        "rows": summary.get("rows"),
        "home_win_log_loss": summary.get("logLoss"),
        "brier_score": summary.get("brierScore"),
        "ece": summary.get("ece"),
        "calibration_intercept": summary.get("calibrationIntercept"),
        "calibration_slope": summary.get("calibrationSlope"),
        "winner_accuracy": summary.get("accuracy"),
        "joint_score_nll": summary.get("jointScoreNegativeLogLikelihood"),
        "home_points_mae": summary.get("homePointsMae"),
        "away_points_mae": summary.get("awayPointsMae"),
        "mean_team_points_mae": summary.get("meanTeamPointsMae"),
        "score_differential_mae": summary.get("scoreDifferentialMae"),
        "total_points_mae": summary.get("totalPointsMae"),
        "home_points_rmse": summary.get("homePointsRmse"),
        "away_points_rmse": summary.get("awayPointsRmse"),
        "score_differential_rmse": summary.get("scoreDifferentialRmse"),
        "total_points_rmse": summary.get("totalPointsRmse"),
        "home_points_crps": summary.get("homePointsCrps"),
        "away_points_crps": summary.get("awayPointsCrps"),
        "score_differential_crps": summary.get("scoreDifferentialCrps"),
        "total_points_crps": summary.get("totalPointsCrps"),
        "home_interval_90_coverage": summary.get("homeInterval90Coverage"),
        "away_interval_90_coverage": summary.get("awayInterval90Coverage"),
        "margin_interval_90_coverage": summary.get("marginInterval90Coverage"),
        "total_interval_90_coverage": summary.get("totalInterval90Coverage"),
        "fit_seconds": summary.get("fitSeconds"),
        "score_seconds": summary.get("scoreSeconds"),
    }


def _temporal_frame(design: TemporalDesign) -> pd.DataFrame:
    rows = []
    for fold in design.folds:
        rows.append(
            {
                "fold_id": fold.fold_id,
                "role": "EXPANDING_WINDOW_VALIDATION",
                "train_start_date": fold.train_start_date,
                "train_end_date": fold.train_end_date,
                "train_start_season": fold.train_start_season,
                "train_end_season": fold.train_end_season,
                "train_rows": fold.train_count,
                "validation_season": fold.validation_season,
                "validation_start_date": fold.validation_start_date,
                "validation_end_date": fold.validation_end_date,
                "validation_rows": fold.validation_count,
                "date_atomic": True,
            }
        )
    rows.append(
        {
            "fold_id": "FINAL_OOT_2025",
            "role": "FINAL_UNTOUCHED_OOT",
            "train_start_date": design.folds[0].train_start_date,
            "train_end_date": design.folds[-1].validation_end_date,
            "train_start_season": design.folds[0].train_start_season,
            "train_end_season": 2024,
            "train_rows": design.folds[-1].train_count + design.folds[-1].validation_count,
            "validation_season": design.final_oot_season,
            "validation_start_date": design.final_oot_start_date,
            "validation_end_date": design.final_oot_end_date,
            "validation_rows": design.final_oot_count,
            "date_atomic": True,
        }
    )
    return pd.DataFrame(rows)


def _feature_tier_frame(paths: FoundationPaths) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "feature_tier": item.tier,
                "status": item.status,
                "usable_feature_count": len(item.usable_columns),
                "usable_columns": list(item.usable_columns),
                "unavailable_requirements": list(item.unavailable_requirements),
                "distinct_from_long_history_core": item.distinct_from_long_history_core,
                "reason": item.reason,
                "oof_selection_eligible": item.status == "MATERIALIZED",
            }
            for item in assess_feature_tiers(paths)
        ]
    )


def _missingness_frame(
    development: pd.DataFrame,
    oot: pd.DataFrame,
    features: Sequence[str],
) -> pd.DataFrame:
    rows = []
    for feature in features:
        nonnull = pd.concat(
            [
                development.loc[development[feature].notna(), ["season"]],
                oot.loc[oot[feature].notna(), ["season"]],
            ],
            ignore_index=True,
        )
        first = int(nonnull["season"].min()) if not nonnull.empty else None
        rows.append(
            {
                "feature": feature,
                "development_rows": len(development),
                "development_missing_rows": int(development[feature].isna().sum()),
                "development_missing_pct": float(development[feature].isna().mean()),
                "final_oot_rows": len(oot),
                "final_oot_missing_rows": int(oot[feature].isna().sum()),
                "final_oot_missing_pct": float(oot[feature].isna().mean()),
                "first_nonnull_season": first,
                "source_era_status": "SOURCE_NOT_AVAILABLE_FOR_ERA"
                if first is not None and first > int(development["season"].min())
                else "AVAILABLE_FROM_EARLIEST_GOLD_SEASON",
                "missing_treatment": "FOLD_LOCAL_MEDIAN_PLUS_INDICATOR"
                if feature not in CATEGORICAL_FEATURES
                else "FOLD_LOCAL_EXPLICIT_MISSING_CATEGORY",
            }
        )
    return pd.DataFrame(rows)


def _calibration_frame(ledgers: Mapping[str, tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    rows = []
    for candidate_id, (scope, ledger) in ledgers.items():
        table = calibration_table(
            ledger["actual_home_win"].to_numpy(int),
            ledger["predicted_home_win_probability"].to_numpy(float),
        )
        for item in table:
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "scope": scope,
                    "bin": item["bin"],
                    "bin_lower": item["lower"],
                    "bin_upper": item["upper"],
                    "count": item["count"],
                    "mean_probability": item["meanProbability"],
                    "event_rate": item["eventRate"],
                }
            )
    return pd.DataFrame(rows)


def _fold_metric_frame(
    point_ledger: pd.DataFrame,
    distribution_ledger: pd.DataFrame,
) -> pd.DataFrame:
    """Report every genuine fold prediction without collapsing fold identity."""

    rows: list[dict[str, Any]] = []
    grouping = ["candidate_id", "family", "recency_strategy", "fold_id"]
    for keys, group in point_ledger.groupby(grouping, sort=True, dropna=False):
        candidate_id, family, recency, fold_id = keys
        rows.append(
            {
                "candidate_id": candidate_id,
                "family": family,
                "recency_strategy": recency,
                "fold_id": fold_id,
                "probability_source": "POINT_MODEL",
                **_summary_row(
                    str(candidate_id),
                    str(family),
                    "OOF_FOLD",
                    _metric_row(group),
                    recency_strategy=str(recency),
                ),
            }
        )
    for keys, group in distribution_ledger.groupby(grouping, sort=True, dropna=False):
        candidate_id, family, recency, fold_id = keys
        rows.append(
            {
                "candidate_id": candidate_id,
                "family": family,
                "recency_strategy": recency,
                "fold_id": fold_id,
                "probability_source": "JOINT_SCORE_DISTRIBUTION",
                **_summary_row(
                    str(candidate_id),
                    str(family),
                    "OOF_FOLD",
                    _summarize_distribution_ledger(group),
                    recency_strategy=str(recency),
                ),
            }
        )
    return pd.DataFrame(rows)


def _fold_calibration_frame(
    point_ledger: pd.DataFrame,
    distribution_ledger: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    grouping = ["candidate_id", "family", "recency_strategy", "fold_id"]
    for source, frame in (
        ("POINT_MODEL", point_ledger),
        ("JOINT_SCORE_DISTRIBUTION", distribution_ledger),
    ):
        for keys, group in frame.groupby(grouping, sort=True, dropna=False):
            candidate_id, family, recency, fold_id = keys
            for item in calibration_table(
                group["actual_home_win"].to_numpy(int),
                group["predicted_home_win_probability"].to_numpy(float),
            ):
                rows.append(
                    {
                        "candidate_id": candidate_id,
                        "family": family,
                        "recency_strategy": recency,
                        "fold_id": fold_id,
                        "probability_source": source,
                        "bin": item["bin"],
                        "bin_lower": item["lower"],
                        "bin_upper": item["upper"],
                        "count": item["count"],
                        "mean_probability": item["meanProbability"],
                        "event_rate": item["eventRate"],
                    }
                )
    return pd.DataFrame(rows)


def _missing_reason_summary(
    development: pd.DataFrame,
    oot: pd.DataFrame,
) -> pd.DataFrame:
    """Expose the three governed cold-start/source-era reasons explicitly.

    Counts are game rows and may overlap across reasons.  The operational
    definitions are feature-only and never inspect target values.
    """

    rows: list[dict[str, Any]] = []
    for scope, frame in (("DEVELOPMENT", development), ("FINAL_OOT", oot)):
        home_prior = pd.to_numeric(frame["home_prior_games"], errors="coerce")
        away_prior = pd.to_numeric(frame["away_prior_games"], errors="coerce")
        source_missing = (
            pd.to_numeric(frame["home_source_era_missing"], errors="coerce").fillna(1)
            > 0
        ) | (
            pd.to_numeric(frame["away_source_era_missing"], errors="coerce").fillna(1)
            > 0
        )
        missing_history = (home_prior.fillna(0) <= 0) | (away_prior.fillna(0) <= 0)
        insufficient_history = (
            ~missing_history
            & ((home_prior < 4) | (away_prior < 4))
        )
        for reason, mask, definition in (
            (
                "SOURCE_NOT_AVAILABLE_FOR_ERA",
                source_missing,
                "either registered home/away source-era-missing flag is set",
            ),
            (
                "MISSING_HISTORY",
                missing_history,
                "either team has zero prior governed games",
            ),
            (
                "INSUFFICIENT_HISTORY",
                insufficient_history,
                "neither team is missing history and either has 1-3 prior governed games",
            ),
        ):
            rows.append(
                {
                    "scope": scope,
                    "reason": reason,
                    "definition": definition,
                    "rows": int(mask.sum()),
                    "population_rows": len(frame),
                    "prevalence": float(mask.mean()),
                    "mutually_exclusive": False,
                    "target_values_used": False,
                }
            )
    return pd.DataFrame(rows)


def _distribution_coverage_frame(
    ledgers: Mapping[str, tuple[str, pd.DataFrame]]
) -> pd.DataFrame:
    rows = []
    for candidate_id, (scope, ledger) in ledgers.items():
        rows.extend(
            {
                "candidate_id": candidate_id,
                "scope": scope,
                "quantity": quantity,
                "nominal_coverage": 0.9,
                "observed_coverage": float(ledger[column].mean()),
                "rows": len(ledger),
            }
            for quantity, column in (
                ("HOME_POINTS", "home_interval_90_covered"),
                ("AWAY_POINTS", "away_interval_90_covered"),
                ("SCORE_DIFFERENTIAL", "margin_interval_90_covered"),
                ("TOTAL_POINTS", "total_interval_90_covered"),
            )
        )
    return pd.DataFrame(rows)


def _slice_metrics(ledger: pd.DataFrame, oot: pd.DataFrame, market_detail: pd.DataFrame) -> pd.DataFrame:
    detail = ledger.merge(
        oot[
            [
                "canonical_game_id",
                "game_date",
                "week",
                "game_type",
                "division_game",
                "roof",
                "home_short_week",
                "away_short_week",
                "home_bye_or_long_rest",
                "away_bye_or_long_rest",
            ]
        ],
        on="canonical_game_id",
        suffixes=("", "_gold"),
        validate="one_to_one",
    )
    market = market_detail[
        [
            "canonical_game_id",
            "market_home_probability_no_vig",
            "total_line",
            "complete_moneyline",
            "complete_total",
        ]
    ]
    detail = detail.merge(market, on="canonical_game_id", how="left", validate="one_to_one")
    dates = pd.to_datetime(detail["game_date"])
    detail["month"] = dates.dt.to_period("M").astype(str)
    detail["season_phase"] = np.where(
        detail["week"] <= 6, "EARLY", np.where(detail["week"] <= 12, "MID", "LATE")
    )
    detail["season_type"] = np.where(detail["game_type"] == "REG", "REGULAR", "POSTSEASON")
    detail["division_slice"] = np.where(detail["division_game"].astype(bool), "DIVISIONAL", "NON_DIVISIONAL")
    detail["rest_slice"] = np.where(
        detail[["home_bye_or_long_rest", "away_bye_or_long_rest"]].astype(bool).any(axis=1),
        "BYE_OR_LONG_REST",
        np.where(
            detail[["home_short_week", "away_short_week"]].astype(bool).any(axis=1),
            "SHORT_WEEK",
            "NORMAL_REST",
        ),
    )
    detail["venue_slice"] = np.where(
        detail["roof"].astype(str).str.lower().isin({"dome", "closed"}), "DOME_CLOSED", "OUTDOOR_OR_OPEN"
    )
    complete_moneyline = detail["complete_moneyline"].fillna(False).astype(bool)
    market_probability = pd.to_numeric(detail["market_home_probability_no_vig"], errors="coerce")
    detail["favorite_slice"] = np.where(
        ~complete_moneyline,
        "MARKET_NOT_AVAILABLE",
        np.where(market_probability >= 0.5, "HOME_MARKET_FAVORITE", "HOME_MARKET_UNDERDOG"),
    )
    complete_total = detail["complete_total"].fillna(False).astype(bool)
    numeric_total = pd.to_numeric(detail["total_line"], errors="coerce")
    median_total = float(numeric_total[complete_total].median()) if complete_total.any() else math.nan
    detail["total_slice"] = np.where(
        ~complete_total,
        "MARKET_NOT_AVAILABLE",
        np.where(numeric_total >= median_total, "HIGH_TOTAL", "LOW_TOTAL"),
    )
    candidate_id = str(ledger["candidate_id"].iat[0])
    conditional_probability_column = (
        f"{candidate_id}_market_conditional_home_probability"
    )
    model_market_probability = (
        pd.to_numeric(detail[conditional_probability_column], errors="coerce")
        if conditional_probability_column in detail.columns
        else pd.to_numeric(
            detail["predicted_home_win_probability"], errors="coerce"
        )
    )
    disagreement = np.abs(model_market_probability - market_probability)
    disagreement_cutoff = (
        float(disagreement[complete_moneyline].median()) if complete_moneyline.any() else math.nan
    )
    detail["disagreement_slice"] = np.where(
        ~complete_moneyline,
        "MARKET_NOT_AVAILABLE",
        np.where(disagreement >= disagreement_cutoff, "HIGH_DISAGREEMENT", "LOW_DISAGREEMENT"),
    )
    detail["qb_continuity_slice"] = "NOT_AVAILABLE_TIMING_UNPROVEN"

    rows = []
    for family, column in (
        ("WEEK", "week"),
        ("MONTH", "month"),
        ("SEASON_PHASE", "season_phase"),
        ("SEASON_TYPE", "season_type"),
        ("FAVORITE_UNDERDOG", "favorite_slice"),
        ("DIVISION", "division_slice"),
        ("QUARTERBACK_CONTINUITY", "qb_continuity_slice"),
        ("REST", "rest_slice"),
        ("VENUE", "venue_slice"),
        ("TOTAL_LEVEL", "total_slice"),
        ("MODEL_MARKET_DISAGREEMENT", "disagreement_slice"),
    ):
        for value, group in detail.groupby(column, dropna=False, sort=True):
            metrics = _summarize_distribution_ledger(group)
            rows.append(
                {
                    "slice_family": family,
                    "slice_value": value,
                    "rows": len(group),
                    "home_win_log_loss": metrics["logLoss"],
                    "brier_score": metrics["brierScore"],
                    "winner_accuracy": metrics["accuracy"],
                    "home_points_mae": metrics["homePointsMae"],
                    "away_points_mae": metrics["awayPointsMae"],
                    "mean_team_points_mae": metrics["meanTeamPointsMae"],
                    "score_differential_mae": metrics["scoreDifferentialMae"],
                    "total_points_mae": metrics["totalPointsMae"],
                    "joint_score_nll": metrics["jointScoreNegativeLogLikelihood"],
                }
            )
    for side, actual_column, predicted_column in (
        ("HOME_TEAM_SCORE", "actual_home_points", "predicted_home_points"),
        ("AWAY_TEAM_SCORE", "actual_away_points", "predicted_away_points"),
    ):
        absolute_error = np.abs(
            detail[predicted_column].to_numpy(float)
            - detail[actual_column].to_numpy(float)
        )
        rows.append(
            {
                "slice_family": "HOME_AWAY",
                "slice_value": side,
                "rows": len(detail),
                "home_win_log_loss": np.nan,
                "brier_score": np.nan,
                "winner_accuracy": np.nan,
                "home_points_mae": float(absolute_error.mean())
                if side == "HOME_TEAM_SCORE"
                else np.nan,
                "away_points_mae": float(absolute_error.mean())
                if side == "AWAY_TEAM_SCORE"
                else np.nan,
                "mean_team_points_mae": float(absolute_error.mean()),
                "score_differential_mae": np.nan,
                "total_points_mae": np.nan,
                "joint_score_nll": np.nan,
            }
        )
    return pd.DataFrame(rows)


def _coefficient_frame(logistic: FinalLogisticResult) -> pd.DataFrame:
    preprocessor = logistic.model.preprocessor
    estimator = logistic.model.estimator
    if preprocessor is None or estimator is None:
        raise NflM1IntegrityError("final logistic artifact is not fitted")
    names = preprocessor.expanded_feature_names
    coefficients = estimator.coef_[0]
    if len(names) != len(coefficients):
        raise NflM1IntegrityError("coefficient names differ from fitted logistic vector")
    return pd.DataFrame(
        {
            "candidate_id": logistic.selected.candidate_id,
            "expanded_feature": names,
            "coefficient": coefficients,
            "absolute_coefficient": np.abs(coefficients),
            "interpretation": "FOLD_LOCAL_STANDARDIZED_OR_ONE_HOT_LOG_ODDS_COEFFICIENT",
        }
    ).sort_values("absolute_coefficient", ascending=False, kind="mergesort")


def _recency_frame(point_leaderboard: pd.DataFrame) -> pd.DataFrame:
    frame = point_leaderboard[
        point_leaderboard["recencyStrategy"].isin([item.value for item in RECENCY_STRATEGIES])
    ].copy()
    return frame.rename(
        columns={
            "candidateId": "candidate_id",
            "recencyStrategy": "recency_strategy",
            "logLoss": "home_win_log_loss",
            "meanTeamPointsMae": "mean_team_points_mae",
            "scoreDifferentialMae": "score_differential_mae",
            "totalPointsMae": "total_points_mae",
        }
    )


def _oof_selection_receipt(
    *,
    paths: FoundationPaths,
    design: TemporalDesign,
    selected: Mapping[str, SelectedCandidate],
    distribution_results: Mapping[str, DistributionCandidateResult],
    ensemble: DistributionCandidateResult,
    ensemble_selection: EnsembleSelection,
    feature_tiers: pd.DataFrame,
    point_ledger_sha256: str,
    distribution_ledger_sha256: str,
    simulation_manifest_sha256: str,
) -> dict[str, Any]:
    distribution_ranking = sorted(
        (
            {
                "family": family,
                "candidateId": result.selected.candidate_id,
                "jointScoreNegativeLogLikelihood": result.summary["jointScoreNegativeLogLikelihood"],
                "homeWinLogLoss": result.summary["logLoss"],
                "meanTeamPointsMae": result.summary["meanTeamPointsMae"],
            }
            for family, result in distribution_results.items()
        ),
        key=lambda row: (
            row["jointScoreNegativeLogLikelihood"],
            row["homeWinLogLoss"],
            row["meanTeamPointsMae"],
            row["candidateId"],
        ),
    )
    best_single = distribution_ranking[0]
    overall_ranking = sorted(
        [
            *distribution_ranking,
            {
                "family": "ENSEMBLE",
                "candidateId": ensemble.selected.candidate_id,
                "jointScoreNegativeLogLikelihood": ensemble.summary[
                    "jointScoreNegativeLogLikelihood"
                ],
                "homeWinLogLoss": ensemble.summary["logLoss"],
                "meanTeamPointsMae": ensemble.summary["meanTeamPointsMae"],
            },
        ],
        key=lambda row: (
            row["jointScoreNegativeLogLikelihood"],
            row["homeWinLogLoss"],
            row["meanTeamPointsMae"],
            row["candidateId"],
        ),
    )
    research_challenger = overall_ranking[0]
    body = {
        "contract": SELECTION_CONTRACT,
        "foundationManifestSha256": paths.foundation_manifest_sha256,
        "gameGoldManifestSha256": paths.game_manifest_sha256,
        "playGoldManifestSha256": paths.play_manifest_sha256,
        "developmentValidationSeasons": [fold.validation_season for fold in design.folds],
        "developmentOofRows": design.oof_game_count,
        "finalOotSeason": design.final_oot_season,
        "finalOotRows": design.final_oot_count,
        "finalOotOutcomeValuesMaterialized": False,
        "foundationObjectBytesCryptographicallyVerified": True,
        "selectionCriterion": "OOF_JOINT_SCORE_NLL_THEN_HOME_WIN_LOG_LOSS_THEN_MEAN_TEAM_POINTS_MAE",
        "featureTier": "LONG_HISTORY_CORE",
        "featureTierStatuses": feature_tiers.to_dict(orient="records"),
        "familySelections": {family: asdict(value) for family, value in sorted(selected.items())},
        "distributionRanking": distribution_ranking,
        "overallRanking": overall_ranking,
        "bestSingleFamily": best_single["family"],
        "bestSingleCandidateId": best_single["candidateId"],
        "researchChallengerFamily": research_challenger["family"],
        "researchChallengerCandidateId": research_challenger["candidateId"],
        "ensemble": {
            "candidateId": ensemble.selected.candidate_id,
            "oofMetrics": dict(ensemble.summary),
            "scoreFamilies": list(ensemble_selection.score_families),
            "finalScoreWeights": list(ensemble_selection.final_score_weights),
            "finalProbabilityWeights": list(ensemble_selection.final_probability_weights),
            "calibrationMethod": ensemble_selection.calibration_method,
            "finalPlatt": ensemble_selection.final_platt,
            "crossFitted": True,
            "firstFoldMetaPolicy": "PREDECLARED_SCORE_EQUAL_WEIGHTS_AND_SCORE_ONLY_WIN_MASS",
        },
        "pointOofLedgerSha256": point_ledger_sha256,
        "distributionOofLedgerSha256": distribution_ledger_sha256,
        "distributionOofSimulationManifestSha256": simulation_manifest_sha256,
        "marketUsedForSelection": False,
        "ootUsedForSelection": False,
        "promotionAuthorized": False,
    }
    body["selectionSha256"] = _sha256_bytes(_canonical_bytes(body))
    return body


def _write_definitive_report(path: Path, summary: Mapping[str, Any]) -> None:
    folds = summary["temporalDesign"]
    configuration = summary["configuration"]
    verification = summary.get("verification", {})
    final_line_metrics = summary["market"]["lineProbabilityMetrics"]["FINAL_OOT"]
    ensemble_cover = final_line_metrics["FROZEN_SCORE_WIN_ENSEMBLE"]["homeCover"]
    ensemble_over = final_line_metrics["FROZEN_SCORE_WIN_ENSEMBLE"]["over"]

    def metric_text(value: Any) -> str:
        return "NOT_AVAILABLE" if value is None else f"{float(value):.6f}"

    line_result = (
        "Final OOT ensemble conditional-on-nonpush home-cover metrics: "
        f"rows **{ensemble_cover['rows']}**, log loss **{metric_text(ensemble_cover['logLoss'])}**, "
        f"Brier **{metric_text(ensemble_cover['brierScore'])}**, ECE **{metric_text(ensemble_cover['ece'])}**. "
        "Conditional-on-nonpush over metrics: "
        f"rows **{ensemble_over['rows']}**, log loss **{metric_text(ensemble_over['logLoss'])}**, "
        f"Brier **{metric_text(ensemble_over['brierScore'])}**, ECE **{metric_text(ensemble_over['ece'])}**. "
        "Exact modeled spread/total push mass is retained separately; sportsbook no-vig line metrics are in the same compact market table. "
        "The governed nflverse spread is interpreted as projected home scoring margin (home cover iff actual home margin exceeds the line)."
    )
    if summary["market"]["ootCompleteMoneylines"]:
        interval_crosses_zero = (
            summary["market"]["bestModelMinusMarketCiLower"] <= 0.0
            <= summary["market"]["bestModelMinusMarketCiUpper"]
        )
        market_conclusion = (
            "The interval crosses zero, so the selected model did not clearly improve on the market benchmark."
            if interval_crosses_zero
            else "The paired interval does not cross zero; its signed direction is reported without a deployment claim."
        )
        market_result = (
            f"Sportsbook no-vig home-win log loss: **{summary['market']['sportsbookLogLoss']:.6f}**; "
            f"Brier: **{summary['market']['sportsbookBrier']:.6f}**. "
            f"Best selected model minus market log-loss point estimate: "
            f"**{summary['market']['bestModelMinusMarketLogLoss']:.6f}** with paired 95% interval "
            f"**[{summary['market']['bestModelMinusMarketCiLower']:.6f}, "
            f"{summary['market']['bestModelMinusMarketCiUpper']:.6f}]**. "
            f"{market_conclusion} Model and market probabilities are conditioned on non-tied moneyline settlements; "
            f"{summary['market']['ootMoneylinePushRows']} tied final is reported as a push and excluded from log loss."
        )
    else:
        market_result = (
            "No complete two-sided OOT moneyline prices were available; sportsbook probability "
            "metrics and the paired model-versus-market interval are `NOT_AVAILABLE`, not zero."
        )
    bootstrap_lines: list[str] = []
    for comparison, metrics in summary["bootstrap"].items():
        for metric_name, interval in metrics.items():
            point = interval.get("pointEstimate")
            lower = interval.get("lower")
            upper = interval.get("upper")
            if point is None or lower is None or upper is None:
                conclusion = str(interval.get("status", "NOT_AVAILABLE"))
                bootstrap_lines.append(
                    f"| {comparison} | {metric_name} | — | — | {conclusion} |"
                )
                continue
            conclusion = (
                "INCONCLUSIVE_INTERVAL_CROSSES_ZERO"
                if lower <= 0.0 <= upper
                else "CLEAR_CANDIDATE_IMPROVEMENT"
                if upper < 0.0
                else "CLEAR_BASELINE_IMPROVEMENT"
            )
            bootstrap_lines.append(
                f"| {comparison} | {metric_name} | {point:.6f} | "
                f"[{lower:.6f}, {upper:.6f}] | {conclusion} |"
            )
    season_type_result = ""
    if summary.get("stability", {}).get("regularSeasonRows") is not None:
        season_type_result = (
            f"Regular season: **{summary['stability']['regularSeasonRows']} games**, log loss "
            f"**{summary['stability']['regularSeasonLogLoss']:.6f}**, team-points MAE "
            f"**{summary['stability']['regularSeasonMeanTeamPointsMae']:.6f}**. "
            f"Postseason: **{summary['stability']['postseasonRows']} games**, log loss "
            f"**{summary['stability']['postseasonLogLoss']:.6f}**, team-points MAE "
            f"**{summary['stability']['postseasonMeanTeamPointsMae']:.6f}**; the postseason sample is descriptive and small."
        )
    lines = [
        "# ASP NFL M1 Chronological Score-Distribution Modeling Benchmark",
        "",
        f"**Research disposition:** `RESEARCH_SHADOW` / `NOT_PROMOTED`",
        f"**Foundation:** `{summary['foundation']['datasetVersionId']}`",
        f"**Selection receipt:** `{summary['selection']['selectionSha256']}`",
        "",
        "## Executive result",
        "",
        f"The only fully materialized, point-in-time game-level feature tier was **{summary['selection']['featureTier']}**. "
        f"The OOF-selected recency and model decisions were frozen before final OOT outcome rows were materialized. "
        f"The selected research challenger is **{summary['researchArtifact']['candidateId']}**; it remains disconnected from product deployment.",
        "",
        "## Population and exclusions",
        "",
        f"- Pregame Gold: **{summary['foundation']['gameRows']:,} games**, {summary['foundation']['gamePredictors']} ordered predictors, seasons 1999–2025.",
        f"  Authority: `{summary['foundation']['gameGoldId']}` / manifest `{summary['foundation']['gameGoldManifestSha256']}`.",
        f"- Play-state Gold: **{summary['foundation']['playRows']:,} rows**; preserved for later work and not modeled here.",
        f"  Authority: `{summary['foundation']['playGoldId']}` / manifest `{summary['foundation']['playGoldManifestSha256']}`.",
        f"- Eligible modeled games: **{summary['population']['eligibleGoldRows']:,}**; Gold exclusions: `{summary['population']['goldExclusions']}`.",
        f"- Source schedule exclusions: `{summary['population']['sourceExclusions']}` (the 272 rows are prospective 2026 games without final truth).",
        "- Preseason, cancelled/postponed, missing-score, and invalid-identity rows were never silently dropped; every category was audited.",
        "",
        "## Exact chronological design",
        "",
        "| Fold | Train dates | Train games | Validation dates | Validation games |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in folds["folds"]:
        lines.append(
            f"| {row['foldId']} | {row['trainStart']}–{row['trainEnd']} | {row['trainCount']:,} | "
            f"{row['validationStart']}–{row['validationEnd']} | {row['validationCount']:,} |"
        )
    lines.extend(
        [
            "",
            f"Combined OOF: **{folds['oofRows']:,} games**. Final untouched OOT: **{folds['ootRows']:,} games**, "
            f"{folds['ootStart']}–{folds['ootEnd']}. Games were grouped and date-atomic; preprocessing and recency weights were refit inside each fold.",
            "",
            "## Feature-tier result",
            "",
            "`LONG_HISTORY_CORE` is the exact 197-column registered predictor order. Recent 4/8/16 and season-to-date form is already embedded in it. "
            "Quarterback, roster/usage, travel/weather, and recent-rich source families were not silently zero-filled or improvised: their pregame game-level timing contracts are not materialized in the current Gold authority. "
            "Accordingly, they are reported as unavailable/partial rather than treated as failed models.",
            "",
            "## Declared model and simulation configuration",
            "",
            f"- Fixed seed: **{configuration['randomSeed']}**; OOF draws: **{configuration['oofSimulationDrawsPerCandidateGame']:,}** per candidate/game; "
            f"final OOT draws: **{configuration['finalOotSimulationDrawsPerCandidateGame']:,}**; paired bootstrap resamples: **{configuration['pairedBootstrapResamples']:,}**.",
            f"- Logistic C grid: `{configuration['logisticCGrid']}`.",
            f"- Score grid: `{configuration['scoreModelGrid']}`.",
            f"- Objectives: `{configuration['scoreObjective']}` and `{configuration['winObjective']}`.",
            f"- Preprocessing: `{configuration['preprocessing']}`. Distribution: `{configuration['jointDistribution']}` with common random numbers.",
            "",
            "## OOF selection",
            "",
            f"- Best feature tier: **{summary['selection']['featureTier']}**.",
            f"- Best recency strategy: **{summary['selection']['bestRecencyStrategy']}** for the best single score family.",
            f"- Best single model: **{summary['selection']['bestSingleCandidateId']}** ({summary['selection']['bestSingleFamily']}).",
            f"- Best ensemble: **{summary['selection']['ensembleCandidateId']}**, score components `{summary['selection']['scoreFamilies']}` with weights `{summary['selection']['scoreWeights']}`; "
            f"probability components `{summary['selection']['probabilityComponents']}` with weights `{summary['selection']['probabilityWeights']}`; calibration `{summary['selection']['calibrationMethod']}`.",
            "- Second-level weights were genuine chronological cross-fits: a fold's labels never fit the weights used to score that fold. Fold 1 used a predeclared neutral/score-only meta policy because no earlier OOF fold existed.",
            "",
            "### OOF metrics",
            "",
            "| Candidate | Joint NLL | Win log loss | Brier | Team-points MAE | Margin MAE | Total MAE |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in summary["oofLeaderboard"]:
        def f(key: str) -> str:
            value = row.get(key)
            return "—" if value is None else f"{float(value):.6f}"
        lines.append(
            f"| {row['candidateId']} | {f('jointScoreNegativeLogLikelihood')} | {f('logLoss')} | "
            f"{f('brierScore')} | {f('meanTeamPointsMae')} | {f('scoreDifferentialMae')} | {f('totalPointsMae')} |"
        )
    lines.extend(
        [
            "",
            "## Final 2025 OOT",
            "",
            "| Candidate | Joint NLL | Win log loss | Brier | ECE | Accuracy | Team-points MAE | Margin MAE | Total MAE |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in summary["finalOotLeaderboard"]:
        def g(key: str) -> str:
            value = row.get(key)
            return "—" if value is None else f"{float(value):.6f}"
        lines.append(
            f"| {row['candidateId']} | {g('jointScoreNegativeLogLikelihood')} | {g('logLoss')} | "
            f"{g('brierScore')} | {g('ece')} | {g('accuracy')} | {g('meanTeamPointsMae')} | "
            f"{g('scoreDifferentialMae')} | {g('totalPointsMae')} |"
        )
    lines.extend(
        [
            "",
            "## Historical market comparison",
            "",
            f"Line semantics remain **`MARKET_SNAPSHOT_TIMING_UNPROVEN`**. Final OOT had {summary['market']['ootCompleteMoneylines']} complete two-sided moneylines, "
            f"{summary['market']['ootCompleteSpreads']} spreads, and {summary['market']['ootCompleteTotals']} totals. "
            f"The frozen five-fold OOF population had {summary['market']['oofCompleteMoneylines']} complete moneylines, "
            f"{summary['market']['oofCompleteSpreads']} spreads, and {summary['market']['oofCompleteTotals']} totals. "
            "Market fields were joined only after forecasts; zero market fields were predictors. No ROI or bankroll result is reported.",
            "",
            market_result,
            "",
            line_result,
            f"Final OOT score projection errors on complete line rows: sportsbook spread MAE **{metric_text(summary['market']['sportsbookSpreadMae'])}**, "
            f"ensemble score-margin MAE **{metric_text(summary['market']['ensembleSpreadMae'])}**; sportsbook total MAE **{metric_text(summary['market']['sportsbookTotalMae'])}**, "
            f"ensemble projected-total MAE **{metric_text(summary['market']['ensembleTotalMae'])}**.",
            "",
            "## Bootstrap and stability",
            "",
            "All intervals are paired whole-game bootstrap intervals (candidate minus baseline). A difference is not called clear when its interval crosses zero.",
            "",
            "| Comparison | Metric | Difference | Paired 95% interval | Conclusion |",
            "|---|---|---:|---:|---|",
            *bootstrap_lines,
            "",
            f"The 2020 sensitivity changed the selected OOF challenger: **{summary['sensitivity']['selectionChangedWithout2020Validation']}**. "
            f"The frozen best single model's OOT log loss after excluding 2020 from training was **{summary['sensitivity']['ootLogLossExcluding2020Training']:.6f}**.",
            f"Final OOT weekly log loss ranged from **{summary['stability']['bestWeekHomeWinLogLoss']:.6f}** (week {summary['stability']['bestWeekByHomeWinLogLoss']}) "
            f"to **{summary['stability']['worstWeekHomeWinLogLoss']:.6f}** (week {summary['stability']['worstWeekByHomeWinLogLoss']}); "
            f"home-score MAE was **{summary['stability']['homePointsMae']:.6f}** and away-score MAE was **{summary['stability']['awayPointsMae']:.6f}**. "
            "These slices were descriptive only and did not affect selection.",
            season_type_result,
            "",
            "Detailed week/month/season-phase, regular/postseason, home/away score, favorite/underdog, divisional, rest, venue, total, and model-market disagreement slices are in "
            "`docs/nfl_m1/stability_slices.csv`. Quarterback-continuity slicing is explicitly unavailable because starter timing is unproven.",
            "",
            "## Distribution methodology",
            "",
            "Home and away expected points are modeled jointly through paired, out-of-sample residual simulation. The paired residual bank preserves empirical home/away error correlation; fixed common random numbers make candidate comparisons reproducible. "
            "The score/win ensemble changes OUTCOME-GROUP mass by deterministic resampling while preserving conditional score distributions, so its home-win probability remains part of a coherent joint score PMF. "
            "Every PMF was checked finite, nonnegative, integral, and unit-mass. Overtime probability is not identified by final-score residuals and is therefore `NOT_SUPPORTED`, not fabricated.",
            "",
            "## Research-only 2026 artifact",
            "",
            f"- Candidate: `{summary['researchArtifact']['candidateId']}`",
            f"- Manifest SHA-256: `{summary['researchArtifact']['manifestSha256']}`",
            f"- Artifact SHA-256: `{summary['researchArtifact']['artifactSha256']}`",
            f"- Training cutoff: `{summary['researchArtifact']['trainingCutoff']}` (complete NFL season 2025; no season-2026 outcomes).",
            "- Status: `RESEARCH_SHADOW`, `NOT_PROMOTED`, not deployed, not published to AI Sports Predictor.",
            "",
            "## Limitations",
            "",
            "- Only `LONG_HISTORY_CORE` is fully materialized at game level; requested rich tiers await governed pregame derivations.",
            "- Historical market timestamps are unproven, so they are not described as opening or closing lines.",
            "- Residual simulation is empirical and final-score based; it does not model play states or separately identify overtime incidence.",
            "- The sample is one league era with 1,408 development OOF games and 285 final OOT games; paired intervals govern claims.",
            "- 2026 has schedule/roster evidence but no completed outcomes in the foundation, so no 2026 performance claim is made.",
            "",
            "## Verification and artifacts",
            "",
            f"- External OOF prediction ledger: `{summary['artifacts']['pointOofLedger']}` (`{summary['artifacts']['pointOofLedgerSha256']}`).",
            f"- External OOF distribution ledger: `{summary['artifacts']['distributionOofLedger']}` (`{summary['artifacts']['distributionOofLedgerSha256']}`).",
            f"- External final OOT predictions: `{summary['artifacts']['finalOotLedger']}` (`{summary['artifacts']['finalOotLedgerSha256']}`).",
            f"- Exact OOF joint draws manifest: `{summary['artifacts']['oofSimulationManifest']}` (`{summary['artifacts']['oofSimulationManifestSha256']}`).",
            f"- Exact final OOT joint draws manifest: `{summary['artifacts']['finalSimulationManifest']}` (`{summary['artifacts']['finalSimulationManifestSha256']}`).",
            f"- OOF/final market evaluation: `{summary['artifacts']['oofMarketLedger']}` and `{summary['artifacts']['marketLedger']}`.",
            "- Charts and compact CSV evidence: `docs/nfl_m1/`; the manifest includes aggregate and per-fold metrics/calibration, feature coefficients, source-era missingness, semantic missing-reason counts, market evidence, stability slices, and exact temporal splits.",
            f"- Focused NFL M1 tests: **{verification.get('testsPassed', 'PENDING_FINAL_HANDOFF')} passed**, "
            f"command `{verification.get('testCommand', 'reported in final handoff')}`.",
            "- The runner contains no promotion or product-registry call, and sportsbook fields are guarded from predictors.",
            "",
            "ASP_NFL_M1_MODELING_BENCHMARK_COMPLETE",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    os.replace(temporary, path)


def finalize_benchmark_verification(
    summary_path: Path,
    report_path: Path,
    *,
    tests_passed: int,
    test_command: str,
) -> dict[str, Any]:
    """Attach post-run test evidence without refitting or rescoring a model."""

    if int(tests_passed) <= 0 or not str(test_command).strip():
        raise NflM1IntegrityError("positive test evidence and its command are required")
    summary_file = Path(summary_path).resolve()
    report_file = Path(report_path).resolve()
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    if summary.get("promotion", {}).get("performed") is not False:
        raise NflM1IntegrityError("verification finalizer requires a non-promoted M1 run")
    summary["verification"] = {
        "testCommand": str(test_command).strip(),
        "testsPassed": int(tests_passed),
        "frontendChanged": False,
        "frontendTestsRequired": False,
    }
    summary.pop("postRunCorrection", None)
    artifacts = summary.setdefault("artifacts", {})
    bootstrap_path = summary_file.parent / "metrics" / "paired-bootstrap.json"
    if bootstrap_path.exists():
        artifacts["pairedBootstrap"] = str(bootstrap_path)
        artifacts["pairedBootstrapSha256"] = _sha256_file(bootstrap_path)
    reporting_manifest = Path(str(artifacts.get("reportingManifest", "")))
    if reporting_manifest.is_file():
        artifacts["reportingManifestSha256"] = _sha256_file(reporting_manifest)
        stability_path = reporting_manifest.parent / "stability_slices.csv"
        if stability_path.is_file():
            stability = pd.read_csv(stability_path)
            season = stability[
                stability["slice_family"] == "SEASON_TYPE"
            ].set_index("slice_value")
            if {"REGULAR", "POSTSEASON"}.issubset(season.index):
                summary.setdefault("stability", {}).update(
                    {
                        "regularSeasonRows": int(season.loc["REGULAR", "rows"]),
                        "regularSeasonLogLoss": float(
                            season.loc["REGULAR", "home_win_log_loss"]
                        ),
                        "regularSeasonMeanTeamPointsMae": float(
                            season.loc["REGULAR", "mean_team_points_mae"]
                        ),
                        "postseasonRows": int(
                            season.loc["POSTSEASON", "rows"]
                        ),
                        "postseasonLogLoss": float(
                            season.loc["POSTSEASON", "home_win_log_loss"]
                        ),
                        "postseasonMeanTeamPointsMae": float(
                            season.loc["POSTSEASON", "mean_team_points_mae"]
                        ),
                    }
                )
    summary_sha = _atomic_json(summary_file, summary)
    summary["artifacts"]["summaryPath"] = str(summary_file)
    summary["artifacts"]["summarySha256"] = summary_sha
    _write_definitive_report(report_file, summary)
    return {
        "summaryPath": str(summary_file),
        "summarySha256": summary_sha,
        "reportPath": str(report_file),
        "testsPassed": int(tests_passed),
        "modelsFitted": 0,
        "modelsScored": 0,
    }


def run_benchmark(
    config: BenchmarkConfig,
    *,
    progress: Any | None = None,
) -> dict[str, Any]:
    """Execute the complete bounded benchmark and return its definitive summary."""

    config = config.validated()
    emit = progress or (lambda message: None)
    config.external_root.mkdir(parents=True, exist_ok=True)
    config.docs_root.mkdir(parents=True, exist_ok=True)
    emit("Verifying the immutable NFL Foundation authority")
    paths = resolve_nfl_m1_authority(config.foundation_root, deep_verify=True)
    complete_seasons = _complete_seasons_from_foundation_manifest(paths)
    temporal_rows = _load_temporal_identity_rows(paths)
    design = build_temporal_design(
        temporal_rows,
        requested_oot_season=config.final_oot_season,
        complete_seasons=complete_seasons,
    )
    feature_tiers = _feature_tier_frame(paths)
    development = _load_development_gold(paths, design)
    if int(development["season"].max()) != 2024:
        raise NflM1IntegrityError("OOF selection input includes final OOT outcomes")
    features = assert_no_market_predictors(paths.game_ordered_predictors)

    emit("Running staged six-strategy expanding-window OOF selection")
    point_ledgers, point_leaderboard, selected = run_oof_point_selection(
        development,
        design,
        features,
        seed=config.seed,
        progress=emit,
    )
    point_ledger = pd.concat(point_ledgers, ignore_index=True)
    point_path = config.external_root / "predictions" / "five-fold-oof-point-predictions.parquet"
    point_sha = _atomic_parquet(point_ledger, point_path)

    logistic_selected = selected["LOGISTIC_HOME_WIN"]
    logistic_oof = next(
        ledger
        for ledger in point_ledgers
        if ledger["candidate_id"].iat[0] == logistic_selected.candidate_id
        and ledger["recency_strategy"].iat[0] == logistic_selected.recency_strategy
    )
    score_selections = {
        family: item for family, item in selected.items() if family != "LOGISTIC_HOME_WIN"
    }
    distribution_results: dict[str, DistributionCandidateResult] = {}
    for family, item in sorted(score_selections.items()):
        emit(f"Building honest OOF joint distributions for {item.candidate_id}")
        distribution_results[family] = run_selected_distribution_oof(
            development,
            design,
            features,
            item,
            draws=config.oof_draws,
            seed=config.seed,
        )
    emit("Cross-fitting the score/win ensemble without same-row label reuse")
    ensemble_oof, ensemble_selection = build_oof_ensemble(
        distribution_results,
        logistic_oof,
        design,
        draws=config.oof_draws,
        seed=config.seed,
    )
    distribution_ledger = pd.concat(
        [*(item.ledger for item in distribution_results.values()), ensemble_oof.ledger],
        ignore_index=True,
    )
    distribution_path = config.external_root / "predictions" / "five-fold-oof-distribution-predictions.parquet"
    distribution_sha = _atomic_parquet(distribution_ledger, distribution_path)
    oof_simulations = _oof_simulation_candidates(
        distribution_results, ensemble_oof, design
    )
    oof_simulation_manifest = _persist_simulation_bundle(
        config.external_root,
        scope="five-fold-oof",
        candidates=oof_simulations,
        candidate_fold_lineage=_oof_simulation_fold_lineage(
            distribution_results, ensemble_oof, design
        ),
    )
    receipt = _oof_selection_receipt(
        paths=paths,
        design=design,
        selected=selected,
        distribution_results=distribution_results,
        ensemble=ensemble_oof,
        ensemble_selection=ensemble_selection,
        feature_tiers=feature_tiers,
        point_ledger_sha256=point_sha,
        distribution_ledger_sha256=distribution_sha,
        simulation_manifest_sha256=oof_simulation_manifest["manifestSha256"],
    )
    selection_path = config.external_root / "selection" / "oof-selection-receipt.json"
    selection_file_sha = _atomic_json(selection_path, receipt)
    if receipt["selectionSha256"] != _sha256_bytes(
        _canonical_bytes({key: value for key, value in receipt.items() if key != "selectionSha256"})
    ):
        raise NflM1IntegrityError("OOF selection receipt identity differs")
    if _sha256_file(selection_path) != selection_file_sha:
        raise NflM1IntegrityError("OOF selection receipt file changed after freeze")
    oof_ranked = sorted(
        [*distribution_results.values(), ensemble_oof],
        key=lambda item: (
            item.summary["jointScoreNegativeLogLikelihood"],
            item.summary["logLoss"],
            item.summary["meanTeamPointsMae"],
            item.selected.candidate_id,
        ),
    )
    best_oof = oof_ranked[0]
    if (
        receipt["researchChallengerCandidateId"]
        != best_oof.selected.candidate_id
        or receipt["researchChallengerFamily"] != best_oof.selected.family
    ):
        raise NflM1IntegrityError(
            "frozen OOF research-challenger decision differs from its ranking"
        )

    emit("Selection is frozen; auditing population and opening the 285-game final 2025 OOT once")
    population = audit_game_population(paths)
    authority_rows = load_eligible_games(paths)
    if design.final_oot_season not in population.complete_eligible_seasons:
        raise NflM1IntegrityError("frozen final OOT is not a fully completed eligible season")
    if {str(row["canonical_game_id"]) for row in authority_rows} != {
        str(row["canonical_game_id"]) for row in temporal_rows
    }:
        raise NflM1IntegrityError("post-selection population audit differs from frozen identities")
    market_audit = audit_market_coverage(paths, authority_rows)
    # Draw archives and all market evaluation are intentionally created only
    # after the market-free OOF selection receipt has been frozen and verified.
    oof_candidate_ledgers: dict[str, pd.DataFrame] = {
        item.selected.candidate_id: item.ledger
        for item in distribution_results.values()
    }
    oof_candidate_ledgers[ensemble_oof.selected.candidate_id] = ensemble_oof.ledger
    oof_truth = ensemble_oof.ledger[
        ["canonical_game_id", "actual_home_points", "actual_away_points"]
    ].rename(
        columns={
            "actual_home_points": "home_points",
            "actual_away_points": "away_points",
        }
    )
    oof_market_summary, oof_market_detail = market_comparison_table(
        paths,
        oof_truth,
        oof_candidate_ledgers,
        oof_simulations,
    )
    oof_market_summary_path = (
        config.external_root / "metrics" / "five-fold-oof-market-summary.parquet"
    )
    oof_market_summary_sha = _atomic_parquet(
        oof_market_summary, oof_market_summary_path
    )
    oof_market_detail_path = (
        config.external_root
        / "predictions"
        / "five-fold-oof-market-comparison.parquet"
    )
    oof_market_detail_sha = _atomic_parquet(oof_market_detail, oof_market_detail_path)
    oot = _load_final_oot(paths, design)
    final_scores: dict[str, FinalScoreResult] = {}
    for family, item in sorted(score_selections.items()):
        emit(f"Final OOT: {item.candidate_id}")
        final_scores[family] = score_selected_final_oot(
            development,
            oot,
            features,
            item,
            draws=config.oot_draws,
            seed=config.seed + 100_000,
        )
    final_logistic = score_selected_logistic_final_oot(
        development,
        oot,
        features,
        logistic_selected,
        seed=config.seed + 110_000,
    )
    final_ensemble_simulation, final_ensemble_ledger, final_ensemble_summary = build_final_ensemble(
        final_scores,
        final_logistic,
        ensemble_selection,
        oot,
        draws=config.oot_draws,
        seed=config.seed + 120_000,
    )
    baseline_ledgers = _final_baseline_ledgers(development, oot)

    best_single_family = str(receipt["bestSingleFamily"])
    best_single_final = final_scores[best_single_family]
    final_candidate_ledgers: dict[str, pd.DataFrame] = {
        item.selected.candidate_id: item.ledger for item in final_scores.values()
    }
    final_candidate_ledgers["frozen-score-win-ensemble"] = final_ensemble_ledger
    final_candidate_ledgers[final_logistic.selected.candidate_id] = final_logistic.ledger
    for ledger in baseline_ledgers:
        final_candidate_ledgers[str(ledger["candidate_id"].iat[0])] = ledger

    final_simulations: dict[str, tuple[Sequence[str], SimulatedScores]] = {
        item.selected.candidate_id: (
            item.ledger["canonical_game_id"].astype(str).tolist(),
            item.simulation,
        )
        for item in final_scores.values()
    }
    final_simulations["frozen-score-win-ensemble"] = (
        final_ensemble_ledger["canonical_game_id"].astype(str).tolist(),
        final_ensemble_simulation,
    )
    final_simulation_manifest = _persist_simulation_bundle(
        config.external_root,
        scope="final-oot",
        candidates=final_simulations,
    )

    emit("Joining historical market evidence after all model forecasts are frozen")
    market_summary, market_detail = market_comparison_table(
        paths, oot, final_candidate_ledgers, final_simulations
    )
    elo_final = next(row for row in baseline_ledgers if row["family"].iat[0] == "ELO")
    rolling_final = next(
        row for row in baseline_ledgers if row["family"].iat[0] == "ROLLING_SCORING"
    )
    bootstrap = bootstrap_comparisons(
        ensemble=final_ensemble_ledger,
        best_single=best_single_final.ledger,
        elo=elo_final,
        rolling=rolling_final,
        market_detail=market_detail,
        resamples=config.bootstrap_resamples,
        seed=config.seed + 130_000,
    )
    bootstrap_path = config.external_root / "metrics" / "paired-bootstrap.json"
    bootstrap_sha = _atomic_json(bootstrap_path, bootstrap)

    # 2020 sensitivity is descriptive only and cannot change the frozen receipt.
    oof_without_2020 = []
    for item in [*distribution_results.values(), ensemble_oof]:
        ledger = item.ledger[item.ledger["season"] != 2020]
        oof_without_2020.append((item.selected.candidate_id, _summarize_distribution_ledger(ledger)))
    ranked_without_2020 = sorted(
        oof_without_2020,
        key=lambda item: (
            item[1]["jointScoreNegativeLogLikelihood"],
            item[1]["logLoss"],
            item[0],
        ),
    )
    development_without_2020 = development[development["season"] != 2020].reset_index(drop=True)
    sensitivity_final = score_selected_final_oot(
        development_without_2020,
        oot,
        features,
        best_single_final.selected,
        draws=config.oot_draws,
        seed=config.seed + 140_000,
    )

    final_distribution_path = config.external_root / "predictions" / "final-2025-oot-game-predictions.parquet"
    final_distribution_ledger = pd.concat(
        [*(item.ledger for item in final_scores.values()), final_ensemble_ledger],
        ignore_index=True,
    )
    final_distribution_sha = _atomic_parquet(final_distribution_ledger, final_distribution_path)
    market_detail_path = config.external_root / "predictions" / "final-2025-market-comparison.parquet"
    market_detail_sha = _atomic_parquet(market_detail, market_detail_path)
    market_summary_path = config.external_root / "metrics" / "final-2025-market-summary.parquet"
    market_summary_sha = _atomic_parquet(market_summary, market_summary_path)

    emit("Refitting the OOF-selected challenger through completed season 2025")
    through_2025 = pd.concat([development, oot], ignore_index=True).sort_values(
        ["game_date", "canonical_game_id"], kind="mergesort"
    ).reset_index(drop=True)
    artifact_models: dict[str, IndependentHomeAwayScoreModel] = {}
    component_training: dict[str, Any] = {}
    for family in ensemble_selection.score_families:
        model, train, _, _ = _fit_score_at_cutoff(
            through_2025,
            cutoff_season=2026,
            selected=score_selections[family],
            features=features,
            seed=config.seed + 150_000,
        )
        artifact_models[family] = model
        component_training[family] = {
            "rowCount": len(train),
            "startSeason": int(train["season"].min()),
            "endSeason": int(train["season"].max()),
            "rowIdSha256": _sha256_bytes(_canonical_bytes(train["canonical_game_id"].astype(str).tolist())),
            "recencyStrategy": score_selections[family].recency_strategy,
        }
    artifact_logistic, logistic_train = _fit_logistic_at_cutoff(
        through_2025,
        cutoff_season=2026,
        selected=logistic_selected,
        features=features,
        seed=config.seed + 160_000,
    )
    selected_artifact_is_ensemble = best_oof.selected.family == "ENSEMBLE"
    if selected_artifact_is_ensemble:
        residual_predictions = [
            final_scores[family].model.predict(oot)
            for family in ensemble_selection.score_families
        ]
        residual_weights = np.asarray(ensemble_selection.final_score_weights, float)
        residual_home = np.column_stack(
            [item.expected_home_points for item in residual_predictions]
        ) @ residual_weights
        residual_away = np.column_stack(
            [item.expected_away_points for item in residual_predictions]
        ) @ residual_weights
    else:
        residual_prediction = final_scores[best_oof.selected.family].model.predict(oot)
        residual_home = residual_prediction.expected_home_points
        residual_away = residual_prediction.expected_away_points
    # The 2026 shadow artifact's residual law is bound to the same raw score
    # model (or raw weighted score ensemble) that the bundle actually carries.
    # Complete 2025 OOT residuals become authorized past evidence only after
    # the one-shot evaluation has finished.
    artifact_residuals = PairedResidualAuthority.fit(
        actual_home=oot["home_points"],
        actual_away=oot["away_points"],
        predicted_home=residual_home,
        predicted_away=residual_away,
        row_ids=oot["canonical_game_id"].tolist(),
        row_dates=oot["game_date"].tolist(),
        training_end=oot["game_date"].max(),
    )
    artifact_candidate_id = (
        "nfl-m1-frozen-score-win-ensemble-2026-shadow"
        if selected_artifact_is_ensemble
        else f"nfl-m1-{best_oof.selected.candidate_id}-2026-shadow"
    )
    serialized_score_families = (
        ensemble_selection.score_families
        if selected_artifact_is_ensemble
        else (best_oof.selected.family,)
    )
    serialized_component_training = {
        family: component_training[family] for family in serialized_score_families
    }
    serialized_component_selection = {
        family: asdict(score_selections[family]) for family in serialized_score_families
    }
    artifact_bundle = {
        "contract": "ASP_NFL_M1_2026_RESEARCH_SHADOW_BUNDLE_V1",
        "candidateId": artifact_candidate_id,
        "scoreModels": artifact_models
        if selected_artifact_is_ensemble
        else {best_oof.selected.family: artifact_models[best_oof.selected.family]},
        "logisticModel": artifact_logistic if selected_artifact_is_ensemble else None,
        "scoreFamilies": serialized_score_families,
        "scoreWeights": ensemble_selection.final_score_weights if selected_artifact_is_ensemble else (1.0,),
        "probabilityWeights": ensemble_selection.final_probability_weights if selected_artifact_is_ensemble else (1.0, 0.0),
        "calibrationMethod": ensemble_selection.calibration_method if selected_artifact_is_ensemble else "NONE",
        "platt": ensemble_selection.final_platt if selected_artifact_is_ensemble else None,
        "pairedResidualAuthority": artifact_residuals,
        "featureNames": features,
        "foundationManifestSha256": paths.foundation_manifest_sha256,
        "trainingCutoff": str(through_2025["game_date"].max()),
        "status": "RESEARCH_SHADOW",
        "promotionState": "NOT_PROMOTED",
        "componentTraining": serialized_component_training,
    }
    publication = publish_research_artifact(
        config.external_root / "research-artifact",
        artifact_bundle,
        candidate_id=artifact_candidate_id,
        foundation_sha256=paths.foundation_manifest_sha256,
        feature_names=features,
        recency_strategy="COMPONENT_SPECIFIC_OOF_SELECTED"
        if selected_artifact_is_ensemble
        else best_oof.selected.recency_strategy,
        hyperparameters={
            "selectedFrom": "2020_2024_OOF_ONLY",
            "components": serialized_component_selection,
            "scoreWeights": list(artifact_bundle["scoreWeights"]),
            "probabilityWeights": list(artifact_bundle["probabilityWeights"]),
            "componentTraining": serialized_component_training,
        },
        training_cutoff=through_2025["game_date"].max(),
        training_row_ids=through_2025["canonical_game_id"].astype(str).tolist(),
        training_outcome_dates=through_2025["game_date"].astype(str).tolist(),
        training_seasons=through_2025["season"].astype(int).tolist(),
        calibration={
            "method": artifact_bundle["calibrationMethod"],
            "parameters": artifact_bundle["platt"],
            "fitPopulation": "2020_2024_OOF_ONLY",
        },
    )
    loaded = load_verified_research_artifact(
        publication.root,
        expected_manifest_sha256=publication.manifest_sha256,
        expected_artifact_sha256=publication.artifact_sha256,
        expected_foundation_sha256=paths.foundation_manifest_sha256,
    )
    if loaded.model.get("candidateId") != artifact_candidate_id:
        raise NflM1IntegrityError("reloaded research artifact identity differs")

    # Compact committed evidence and charts.
    point_reporting = _recency_frame(point_leaderboard)
    oof_rows = [
        _summary_row(
            item.selected.candidate_id,
            item.selected.family,
            "OOF",
            item.summary,
            recency_strategy=item.selected.recency_strategy,
        )
        for item in [*distribution_results.values(), ensemble_oof]
    ]
    selected_point_oof_ledgers = [
        ledger
        for ledger in point_ledgers
        if str(ledger["family"].iat[0]) in {"LEAGUE_PRIOR", "ROLLING_SCORING", "ELO"}
        or (
            str(ledger["family"].iat[0]) == "LOGISTIC_HOME_WIN"
            and str(ledger["candidate_id"].iat[0]) == logistic_selected.candidate_id
            and str(ledger["recency_strategy"].iat[0])
            == logistic_selected.recency_strategy
        )
    ]
    oof_rows.extend(
        _summary_row(
            str(ledger["candidate_id"].iat[0]),
            str(ledger["family"].iat[0]),
            "OOF",
            _metric_row(ledger),
            recency_strategy=str(ledger["recency_strategy"].iat[0]),
        )
        for ledger in selected_point_oof_ledgers
    )
    final_rows = [
        _summary_row(
            item.selected.candidate_id,
            item.selected.family,
            "FINAL_OOT",
            item.summary,
            recency_strategy=item.selected.recency_strategy,
        )
        for item in final_scores.values()
    ]
    final_rows.append(
        _summary_row(
            "frozen-score-win-ensemble",
            "ENSEMBLE",
            "FINAL_OOT",
            final_ensemble_summary,
            recency_strategy="COMPONENT_SPECIFIC_OOF_SELECTED",
        )
    )
    final_rows.append(
        _summary_row(
            final_logistic.selected.candidate_id,
            "LOGISTIC_HOME_WIN",
            "FINAL_OOT",
            final_logistic.summary,
            recency_strategy=final_logistic.selected.recency_strategy,
        )
    )
    for ledger in baseline_ledgers:
        final_rows.append(
            _summary_row(
                str(ledger["candidate_id"].iat[0]),
                str(ledger["family"].iat[0]),
                "FINAL_OOT",
                _metric_row(ledger),
                recency_strategy="CHRONOLOGICAL_NATIVE",
            )
        )
    candidate_reporting = pd.DataFrame([*oof_rows, *final_rows])
    feature_tiers_reporting = feature_tiers.copy()
    feature_tiers_reporting["home_win_log_loss"] = np.where(
        feature_tiers_reporting["feature_tier"] == "LONG_HISTORY_CORE",
        float(best_oof.summary["logLoss"]),
        np.nan,
    )
    calibration_reporting = _calibration_frame(
        {
            ensemble_oof.selected.candidate_id: ("OOF", ensemble_oof.ledger),
            "frozen-score-win-ensemble": ("FINAL_OOT", final_ensemble_ledger),
            best_single_final.selected.candidate_id: ("FINAL_OOT", best_single_final.ledger),
        }
    )
    coverage_reporting = _distribution_coverage_frame(
        {
            ensemble_oof.selected.candidate_id: ("OOF", ensemble_oof.ledger),
            "frozen-score-win-ensemble": ("FINAL_OOT", final_ensemble_ledger),
            best_single_final.selected.candidate_id: ("FINAL_OOT", best_single_final.ledger),
        }
    )
    slices = _slice_metrics(final_ensemble_ledger, oot, market_detail)
    missingness = _missingness_frame(development, oot, features)
    missing_reasons = _missing_reason_summary(development, oot)
    coefficients = _coefficient_frame(final_logistic)
    fold_metrics = _fold_metric_frame(point_ledger, distribution_ledger)
    fold_calibration = _fold_calibration_frame(point_ledger, distribution_ledger)
    final_market_reporting = market_summary.copy()
    final_market_reporting["scope"] = "FINAL_OOT"
    oof_market_reporting = oof_market_summary.copy()
    oof_market_reporting["scope"] = "OOF"
    market_reporting = pd.concat(
        [final_market_reporting, oof_market_reporting],
        ignore_index=True,
        sort=False,
    ).rename(
        columns={
            "candidateId": "candidate_id",
            "scoreDifferentialMae": "spread_mae",
            "totalPointsMae": "total_mae",
        }
    )
    ensemble_market_probability_column = (
        "frozen-score-win-ensemble_market_conditional_home_probability"
    )
    market_points = market_detail[
        [
            "canonical_game_id",
            ensemble_market_probability_column,
            "market_home_probability_no_vig",
            "moneyline_evaluation_eligible",
        ]
    ].rename(
        columns={
            ensemble_market_probability_column: "model_probability",
            "market_home_probability_no_vig": "market_probability",
        }
    )
    market_points["candidate_id"] = "frozen-score-win-ensemble"
    market_points["scope"] = "FINAL_OOT"
    market_reporting = pd.concat([market_reporting, market_points], ignore_index=True, sort=False)
    game_reporting = final_ensemble_ledger.copy()
    game_reporting["candidate_id"] = "frozen-score-win-ensemble"
    game_reporting["model_log_loss"] = _per_game_log_loss(game_reporting)
    market_baseline = market_detail[
        [
            "canonical_game_id",
            "actual_home_win",
            "market_home_probability_no_vig",
            "moneyline_evaluation_eligible",
        ]
    ].copy()
    market_baseline["baseline_log_loss"] = np.nan
    complete_market = market_baseline[
        "moneyline_evaluation_eligible"
    ].astype(bool).to_numpy()
    if complete_market.any():
        market_baseline.loc[complete_market, "baseline_log_loss"] = _loss_vector(
            market_baseline.loc[complete_market, "actual_home_win"].to_numpy(int),
            market_baseline.loc[
                complete_market, "market_home_probability_no_vig"
            ].to_numpy(float),
        )
    game_reporting = game_reporting.merge(
        market_baseline[["canonical_game_id", "baseline_log_loss"]],
        on="canonical_game_id",
        how="left",
        validate="one_to_one",
    )
    game_reporting = game_reporting.sort_values(["game_date", "canonical_game_id"], kind="mergesort")
    reporting = write_m1_research_outputs(
        config.docs_root,
        temporal_splits=_temporal_frame(design),
        feature_tiers=feature_tiers_reporting,
        candidate_leaderboard=candidate_reporting,
        calibration=calibration_reporting,
        market=market_reporting,
        slices=slices,
        recency_leaderboard=point_reporting,
        game_predictions=game_reporting,
        distribution_coverage=coverage_reporting,
        fold_metrics=fold_metrics,
        fold_calibration=fold_calibration,
        feature_coefficients=coefficients,
        missingness_source_era=missingness,
        missing_reason_summary=missing_reasons,
    )

    sportsbook_row = market_summary[market_summary["candidateId"] == "SPORTSBOOK_NO_VIG"].iloc[0]
    oof_sportsbook_row = oof_market_summary[
        oof_market_summary["candidateId"] == "SPORTSBOOK_NO_VIG"
    ].iloc[0]
    oof_ensemble_market_row = oof_market_summary[
        oof_market_summary["candidateId"] == ensemble_oof.selected.candidate_id
    ].iloc[0]
    final_ensemble_market_row = market_summary[
        market_summary["candidateId"] == "frozen-score-win-ensemble"
    ].iloc[0]
    model_market_ci = bootstrap["best_single_vs_market"]["homeWinLogLoss"]
    best_model_market_row = market_summary[
        market_summary["candidateId"] == best_single_final.selected.candidate_id
    ].iloc[0]
    weekly_stability = slices[slices["slice_family"] == "WEEK"].sort_values(
        "home_win_log_loss", kind="mergesort"
    )
    home_away_stability = slices[
        slices["slice_family"] == "HOME_AWAY"
    ].set_index("slice_value")
    season_type_stability = slices[
        slices["slice_family"] == "SEASON_TYPE"
    ].set_index("slice_value")
    stability_findings = {
        "bestWeekByHomeWinLogLoss": None
        if weekly_stability.empty
        else int(weekly_stability.iloc[0]["slice_value"]),
        "bestWeekHomeWinLogLoss": None
        if weekly_stability.empty
        else float(weekly_stability.iloc[0]["home_win_log_loss"]),
        "worstWeekByHomeWinLogLoss": None
        if weekly_stability.empty
        else int(weekly_stability.iloc[-1]["slice_value"]),
        "worstWeekHomeWinLogLoss": None
        if weekly_stability.empty
        else float(weekly_stability.iloc[-1]["home_win_log_loss"]),
        "homePointsMae": float(
            home_away_stability.loc["HOME_TEAM_SCORE", "mean_team_points_mae"]
        ),
        "awayPointsMae": float(
            home_away_stability.loc["AWAY_TEAM_SCORE", "mean_team_points_mae"]
        ),
        "regularSeasonRows": int(
            season_type_stability.loc["REGULAR", "rows"]
        ),
        "regularSeasonLogLoss": float(
            season_type_stability.loc["REGULAR", "home_win_log_loss"]
        ),
        "regularSeasonMeanTeamPointsMae": float(
            season_type_stability.loc["REGULAR", "mean_team_points_mae"]
        ),
        "postseasonRows": int(
            season_type_stability.loc["POSTSEASON", "rows"]
        ),
        "postseasonLogLoss": float(
            season_type_stability.loc["POSTSEASON", "home_win_log_loss"]
        ),
        "postseasonMeanTeamPointsMae": float(
            season_type_stability.loc["POSTSEASON", "mean_team_points_mae"]
        ),
        "sliceUseForSelection": False,
    }
    summary = {
        "contract": BENCHMARK_CONTRACT,
        "configuration": {
            "randomSeed": config.seed,
            "oofSimulationDrawsPerCandidateGame": config.oof_draws,
            "finalOotSimulationDrawsPerCandidateGame": config.oot_draws,
            "pairedBootstrapResamples": config.bootstrap_resamples,
            "logisticCGrid": list(WIN_LOGISTIC_C_GRID),
            "scoreModelGrid": [item.state() for item in _all_score_configs()],
            "scoreObjective": "INDEPENDENT_EXPECTED_HOME_AND_AWAY_POINTS_WITH_PAIRED_OOS_RESIDUAL_SIMULATION",
            "winObjective": "BINARY_HOME_WIN_LOG_LOSS",
            "preprocessing": "FOLD_LOCAL_MEDIAN_PLUS_MISSING_INDICATORS_AND_EXPLICIT_CATEGORICAL_MISSING",
            "jointDistribution": "CORRELATED_EMPIRICAL_PAIRED_OOS_RESIDUAL_SIMULATION",
            "commonRandomNumbers": True,
        },
        "foundation": {
            "datasetVersionId": paths.dataset_version_id,
            "foundationManifestSha256": paths.foundation_manifest_sha256,
            "gameGoldId": paths.game_gold_id,
            "gameGoldManifestSha256": paths.game_manifest_sha256,
            "gameRows": paths.game_row_count,
            "gamePredictors": len(features),
            "playGoldId": paths.play_gold_id,
            "playGoldManifestSha256": paths.play_manifest_sha256,
            "playRows": paths.play_row_count,
        },
        "population": {
            "eligibleGoldRows": population.eligible_gold_rows,
            "goldExclusions": dict(population.gold_exclusions),
            "sourceExclusions": dict(population.source_exclusions),
            "duplicateGoldIdentities": population.duplicate_gold_identities,
        },
        "temporalDesign": {
            "folds": [
                {
                    "foldId": fold.fold_id,
                    "trainStart": str(fold.train_start_date),
                    "trainEnd": str(fold.train_end_date),
                    "trainCount": fold.train_count,
                    "validationStart": str(fold.validation_start_date),
                    "validationEnd": str(fold.validation_end_date),
                    "validationCount": fold.validation_count,
                }
                for fold in design.folds
            ],
            "oofRows": design.oof_game_count,
            "ootSeason": design.final_oot_season,
            "ootStart": str(design.final_oot_start_date),
            "ootEnd": str(design.final_oot_end_date),
            "ootRows": design.final_oot_count,
            "dateAtomic": design.date_atomic,
        },
        "selection": {
            "selectionSha256": receipt["selectionSha256"],
            "selectionFileSha256": selection_file_sha,
            "featureTier": "LONG_HISTORY_CORE",
            "bestSingleFamily": best_single_family,
            "bestSingleCandidateId": best_single_final.selected.candidate_id,
            "bestRecencyStrategy": best_single_final.selected.recency_strategy,
            "ensembleCandidateId": ensemble_oof.selected.candidate_id,
            "scoreFamilies": list(ensemble_selection.score_families),
            "scoreWeights": list(ensemble_selection.final_score_weights),
            "probabilityComponents": ["SCORE_ENSEMBLE", "LOGISTIC_HOME_WIN"],
            "probabilityWeights": list(ensemble_selection.final_probability_weights),
            "calibrationMethod": ensemble_selection.calibration_method,
            "researchChallengerFromOof": receipt[
                "researchChallengerCandidateId"
            ],
            "researchChallengerFamily": receipt["researchChallengerFamily"],
            "ootUsed": False,
            "marketUsed": False,
        },
        "oofLeaderboard": [
            {
                "candidateId": row["candidate_id"],
                "family": row["family"],
                "recencyStrategy": row["recency_strategy"],
                "rows": row["rows"],
                "jointScoreNegativeLogLikelihood": row["joint_score_nll"],
                "logLoss": row["home_win_log_loss"],
                "brierScore": row["brier_score"],
                "ece": row["ece"],
                "accuracy": row["winner_accuracy"],
                "meanTeamPointsMae": row["mean_team_points_mae"],
                "scoreDifferentialMae": row["score_differential_mae"],
                "totalPointsMae": row["total_points_mae"],
            }
            for row in oof_rows
        ],
        "finalOotLeaderboard": [
            {
                "candidateId": row["candidate_id"],
                "family": row["family"],
                "jointScoreNegativeLogLikelihood": row["joint_score_nll"],
                "logLoss": row["home_win_log_loss"],
                "brierScore": row["brier_score"],
                "ece": row["ece"],
                "accuracy": row["winner_accuracy"],
                "meanTeamPointsMae": row["mean_team_points_mae"],
                "scoreDifferentialMae": row["score_differential_mae"],
                "totalPointsMae": row["total_points_mae"],
            }
            for row in final_rows
        ],
        "market": {
            "timingSemantics": list(market_audit.timing_semantics),
            "moneylineProbabilitySemantics": "TWO_SIDED_NO_VIG_AND_MODEL_CONDITIONAL_ON_NONPUSH",
            "oofCompleteMoneylines": int(oof_market_detail["complete_moneyline"].sum()),
            "oofMoneylineSettlementRows": int(
                oof_market_detail["moneyline_evaluation_eligible"].sum()
            ),
            "oofMoneylinePushRows": int(
                (
                    oof_market_detail["complete_moneyline"]
                    & oof_market_detail["actual_moneyline_push"]
                ).sum()
            ),
            "oofCompleteSpreads": int(oof_market_detail["complete_spread"].sum()),
            "oofCompleteTotals": int(oof_market_detail["complete_total"].sum()),
            "ootCompleteMoneylines": int(market_detail["complete_moneyline"].sum()),
            "ootMoneylineSettlementRows": int(
                market_detail["moneyline_evaluation_eligible"].sum()
            ),
            "ootMoneylinePushRows": int(
                (
                    market_detail["complete_moneyline"]
                    & market_detail["actual_moneyline_push"]
                ).sum()
            ),
            "ootCompleteSpreads": int(market_detail["complete_spread"].sum()),
            "ootCompleteTotals": int(market_detail["complete_total"].sum()),
            "sportsbookLogLoss": None
            if pd.isna(sportsbook_row["logLoss"])
            else float(sportsbook_row["logLoss"]),
            "sportsbookBrier": None
            if pd.isna(sportsbook_row["brierScore"])
            else float(sportsbook_row["brierScore"]),
            "sportsbookSpreadMae": None
            if pd.isna(sportsbook_row["scoreDifferentialMae"])
            else float(sportsbook_row["scoreDifferentialMae"]),
            "sportsbookTotalMae": None
            if pd.isna(sportsbook_row["totalPointsMae"])
            else float(sportsbook_row["totalPointsMae"]),
            "ensembleSpreadMae": None
            if pd.isna(final_ensemble_market_row["scoreDifferentialMae"])
            else float(final_ensemble_market_row["scoreDifferentialMae"]),
            "ensembleTotalMae": None
            if pd.isna(final_ensemble_market_row["totalPointsMae"])
            else float(final_ensemble_market_row["totalPointsMae"]),
            "bestModelLogLoss": None
            if pd.isna(best_model_market_row["logLoss"])
            else float(best_model_market_row["logLoss"]),
            "bestModelMinusMarketLogLoss": model_market_ci["pointEstimate"],
            "bestModelMinusMarketCiLower": model_market_ci["lower"],
            "bestModelMinusMarketCiUpper": model_market_ci["upper"],
            "lineProbabilityMetrics": {
                "OOF": {
                    "SPORTSBOOK_NO_VIG": _compact_market_line_metrics(
                        oof_sportsbook_row
                    ),
                    "FROZEN_SCORE_WIN_ENSEMBLE": _compact_market_line_metrics(
                        oof_ensemble_market_row
                    ),
                },
                "FINAL_OOT": {
                    "SPORTSBOOK_NO_VIG": _compact_market_line_metrics(
                        sportsbook_row
                    ),
                    "FROZEN_SCORE_WIN_ENSEMBLE": _compact_market_line_metrics(
                        final_ensemble_market_row
                    ),
                },
            },
            "roiReported": False,
        },
        "bootstrap": bootstrap,
        "stability": stability_findings,
        "sensitivity": {
            "bestWithout2020Validation": ranked_without_2020[0][0],
            "selectionChangedWithout2020Validation": ranked_without_2020[0][0]
            != best_oof.selected.candidate_id,
            "ootLogLossExcluding2020Training": sensitivity_final.summary["logLoss"],
            "ootJointNllExcluding2020Training": sensitivity_final.summary[
                "jointScoreNegativeLogLikelihood"
            ],
            "usedForSelection": False,
        },
        "researchArtifact": {
            "candidateId": artifact_candidate_id,
            "manifestSha256": publication.manifest_sha256,
            "artifactSha256": publication.artifact_sha256,
            "trainingCutoff": publication.manifest["training"]["trainingCutoff"],
            "trainingSeasonEnd": publication.manifest["training"]["seasonEnd"],
            "status": "RESEARCH_SHADOW",
            "promotionState": "NOT_PROMOTED",
            "reloadVerified": True,
        },
        "artifacts": {
            "pointOofLedger": str(point_path),
            "pointOofLedgerSha256": point_sha,
            "distributionOofLedger": str(distribution_path),
            "distributionOofLedgerSha256": distribution_sha,
            "finalOotLedger": str(final_distribution_path),
            "finalOotLedgerSha256": final_distribution_sha,
            "marketLedger": str(market_detail_path),
            "marketLedgerSha256": market_detail_sha,
            "marketSummary": str(market_summary_path),
            "marketSummarySha256": market_summary_sha,
            "oofMarketLedger": str(oof_market_detail_path),
            "oofMarketLedgerSha256": oof_market_detail_sha,
            "oofMarketSummary": str(oof_market_summary_path),
            "oofMarketSummarySha256": oof_market_summary_sha,
            "oofSimulationManifest": oof_simulation_manifest["manifestPath"],
            "oofSimulationManifestSha256": oof_simulation_manifest[
                "manifestSha256"
            ],
            "finalSimulationManifest": final_simulation_manifest["manifestPath"],
            "finalSimulationManifestSha256": final_simulation_manifest[
                "manifestSha256"
            ],
            "reportingManifest": str(reporting.manifest_path),
            "reportingManifestSha256": _sha256_file(reporting.manifest_path),
            "pairedBootstrap": str(bootstrap_path),
            "pairedBootstrapSha256": bootstrap_sha,
        },
        "limitations": [
            "ONLY_LONG_HISTORY_CORE_FULLY_MATERIALIZED",
            "MARKET_SNAPSHOT_TIMING_UNPROVEN",
            "OVERTIME_PROBABILITY_NOT_IDENTIFIED",
            "NO_2026_OUTCOME_EVIDENCE",
        ],
        "verification": {
            "testCommand": "python -m pytest -p no:cacheprovider tests/nfl_m1_*_test.py -q",
            "testsPassed": None,
            "frontendChanged": False,
            "frontendTestsRequired": False,
        },
        "promotion": {"performed": False, "authorized": False},
        "productPublication": {"performed": False},
    }
    summary_path = config.external_root / "benchmark-summary.json"
    summary_sha = _atomic_json(summary_path, summary)
    summary["artifacts"]["summaryPath"] = str(summary_path)
    summary["artifacts"]["summarySha256"] = summary_sha
    _write_definitive_report(
        config.docs_root.parent / "ASP_NFL_M1_MODELING_BENCHMARK_REPORT.md",
        summary,
    )
    return summary


__all__ = [
    "BENCHMARK_CONTRACT",
    "BenchmarkConfig",
    "DistributionCandidateResult",
    "EnsembleSelection",
    "SelectedCandidate",
    "build_oof_ensemble",
    "finalize_benchmark_verification",
    "market_comparison_table",
    "run_benchmark",
    "run_oof_point_selection",
    "run_selected_distribution_oof",
]
