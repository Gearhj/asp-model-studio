"""Point-in-time NFL M1 2026 feature, forecast, and exchange activation.

The fitted artifact is pinned by two independent hashes and is never refitted.
Feature construction mirrors the registered Gold query: one team/date history
row, strict ``game_date < target game_date`` cutoffs, and the exact ordered 197
LONG_HISTORY_CORE predictors.  Source prices are never read here.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_gold.nfl_shadow_exchange import (
    ASP_SPORTS_FORECAST_EXCHANGE_V1,
    ASP_SPORTS_GAME_FORECAST_V1,
    BUNDLE_OBJECT_FAMILY,
    derive_sports_forecast_bundle_id,
    derive_sports_game_forecast_id,
    verify_sports_forecast_bundle,
    write_nfl_2026_research_shadow_locator,
    write_sports_forecast_bundle,
)
from server.sports_nfl.gold import GAME_FEATURES, ROLLING_METRICS
from server.sports_nfl.publication import verify_foundation
from server.sports_nfl_m1.artifacts import load_verified_research_artifact
from server.sports_nfl_m1.data_authority import DEFAULT_NFL_STAGING_ROOT, resolve_nfl_m1_authority
from server.sports_nfl_m1.distributions import SIMULATION_CONTRACT_VERSION, simulate_joint_scores


MODEL_CANDIDATE = "nfl-m1-xgboost-fixed-research-challenger-2026-shadow"
MODEL_MANIFEST_SHA256 = "ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9"
MODEL_BINARY_SHA256 = "7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd"
FOUNDATION_MANIFEST_SHA256 = "f3e142f05bf9f503168b256db4e05d83c373e94425e1c3147d0817fdf37f3bbb"
TRAINING_CUTOFF = "2026-02-08"
TRAINING_DATASET_VERSION = f"asp.nfl.gold-data-foundation.v1:sha256:{FOUNDATION_MANIFEST_SHA256}"
ARTIFACT_ROOT = DEFAULT_NFL_STAGING_ROOT / "m1-modeling-benchmark-v1" / "research-artifact"
DEFAULT_PUBLICATION_ROOT = DEFAULT_NFL_STAGING_ROOT / "m1-prospective-shadow-v1"
DEFAULT_EXCHANGE_ROOT = Path(r"C:\Users\james\asp-model-exchange")
FEATURE_VECTOR_CONTRACT = "ASP_NFL_M1_PROSPECTIVE_FEATURE_VECTOR_V1"
ACTIVATION_INDEX_CONTRACT = "ASP_NFL_M1_PROSPECTIVE_INDEX_V1"
SIMULATION_SEED = 731_001
SIMULATION_DRAWS = 10_000
EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc


class NflProspectiveShadowError(RuntimeError):
    """The frozen prospective research-shadow path failed closed."""


def _now_utc() -> datetime:
    """Single injectable wall-clock boundary for honest availability tests."""

    return datetime.now(UTC)


@dataclass(frozen=True)
class VerifiedFrozenM1:
    model_bundle: Mapping[str, Any]
    manifest: Mapping[str, Any]
    feature_names: tuple[str, ...]
    feature_contract_sha256: str
    residual_authority_sha256: str


@dataclass(frozen=True)
class FoundationRuntime:
    paths: Any
    objects: Mapping[str, Mapping[str, Any]]
    schedule_as_of_utc: str


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NflProspectiveShadowError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _utc_text(value: str | datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    return value


def verify_frozen_m1(
    *, artifact_root: Path = ARTIFACT_ROOT,
    foundation_root: Path = DEFAULT_NFL_STAGING_ROOT / "foundation-v1",
    publication_root: Path = DEFAULT_PUBLICATION_ROOT,
) -> VerifiedFrozenM1:
    """Verify hashes, training boundary, feature/preprocessing contract, and reload."""

    # The artifact remains bound to its frozen training publication, while the
    # prospective source is allowed to advance through independently verified
    # current foundation manifests with the same dataset/feature contract.
    paths = resolve_nfl_m1_authority(foundation_root, deep_verify=True)
    loaded = load_verified_research_artifact(
        artifact_root,
        expected_manifest_sha256=MODEL_MANIFEST_SHA256,
        expected_artifact_sha256=MODEL_BINARY_SHA256,
        expected_foundation_sha256=FOUNDATION_MANIFEST_SHA256,
    )
    manifest = loaded.publication.manifest
    bundle = loaded.model
    features = tuple(str(name) for name in manifest["featureNames"])
    if features != tuple(GAME_FEATURES) or features != paths.game_ordered_predictors or len(features) != 197:
        raise NflProspectiveShadowError("ordered LONG_HISTORY_CORE feature contract differs")
    expected_bundle = {
        "contract": "ASP_NFL_M1_2026_RESEARCH_SHADOW_BUNDLE_V1",
        "candidateId": MODEL_CANDIDATE,
        "scoreFamilies": ("XGBOOST",),
        "scoreWeights": (1.0,),
        "probabilityWeights": (1.0, 0.0),
        "calibrationMethod": "NONE",
        "foundationManifestSha256": FOUNDATION_MANIFEST_SHA256,
        "trainingCutoff": TRAINING_CUTOFF,
        "status": "RESEARCH_SHADOW",
        "promotionState": "NOT_PROMOTED",
    }
    for key, expected in expected_bundle.items():
        if bundle.get(key) != expected:
            raise NflProspectiveShadowError(f"frozen model bundle differs: {key}")
    if tuple(bundle.get("featureNames") or ()) != features or set(bundle.get("scoreModels") or {}) != {"XGBOOST"}:
        raise NflProspectiveShadowError("frozen XGBoost component/feature identity differs")
    score_model = bundle["scoreModels"]["XGBOOST"]
    state = score_model.state()
    preprocessor = state.get("preprocessor") or {}
    if (
        state.get("featureNames") != list(features)
        or preprocessor.get("featureNames") != list(features)
        or preprocessor.get("numericImputation") != "TRAINING_FOLD_MEDIAN_WITH_MISSING_INDICATOR"
        or preprocessor.get("categoricalTreatment") != "TRAINING_FOLD_ONE_HOT_UNKNOWN_IGNORED"
        or preprocessor.get("trainingRowCount") != 7276
    ):
        raise NflProspectiveShadowError("frozen preprocessing/missing-value behavior differs")
    residuals = bundle.get("pairedResidualAuthority")
    if residuals is None or residuals.training_end != TRAINING_CUTOFF or residuals.contract_version != SIMULATION_CONTRACT_VERSION:
        raise NflProspectiveShadowError("frozen paired-residual authority differs")
    if manifest["training"].get("seasonEnd") != 2025 or manifest["training"].get("contains2026SeasonOutcome") is not False:
        raise NflProspectiveShadowError("2026 outcome exclusion differs")
    result = VerifiedFrozenM1(
        model_bundle=bundle,
        manifest=manifest,
        feature_names=features,
        feature_contract_sha256=hashlib.sha256(canonical_json_bytes(list(features))).hexdigest(),
        residual_authority_sha256=residuals.sha256,
    )
    index_path = Path(publication_root) / "prospective-index.json"
    if index_path.exists():
        index = _read_index(Path(publication_root))
        fixture_sha = index.get("reloadFixtureSha256")
        if fixture_sha:
            verify_activation_reload_fixture(Path(publication_root), str(fixture_sha), result)
    return result


def load_foundation_runtime(
    foundation_root: Path = DEFAULT_NFL_STAGING_ROOT / "foundation-v1",
) -> FoundationRuntime:
    paths = resolve_nfl_m1_authority(foundation_root, deep_verify=True)
    verified = verify_foundation(foundation_root, paths.foundation_manifest_sha256)
    objects = {str(item["manifest"]["tableName"]): item for item in verified["objects"]}
    current = json.loads((Path(foundation_root) / "current.json").read_text(encoding="utf-8"))
    schedule_as_of = _utc_text(current["updatedAt"])
    return FoundationRuntime(paths=paths, objects=objects, schedule_as_of_utc=schedule_as_of)


def _team_daily(team_games: pd.DataFrame, team_id: str, target_date: pd.Timestamp) -> pd.DataFrame:
    rows = team_games.loc[
        team_games["completed"].eq(True)
        & team_games["team_id"].astype(str).eq(str(team_id))
        & (pd.to_datetime(team_games["game_date"]) < target_date)
    ].copy()
    if rows.empty:
        return rows
    rows["game_date"] = pd.to_datetime(rows["game_date"])
    aggregations: dict[str, Any] = {metric: "mean" for metric in ROLLING_METRICS}
    aggregations["canonical_game_id"] = "count"
    return (
        rows.groupby(["team_id", "season", "game_date"], as_index=False, sort=True)
        .agg(aggregations)
        .rename(columns={"canonical_game_id": "games_on_date"})
        .sort_values("game_date", kind="stable")
        .reset_index(drop=True)
    )


def _side_features(
    team_games: pd.DataFrame, *, side: str, team_id: str, target_date: pd.Timestamp, season: int
) -> dict[str, Any]:
    history = _team_daily(team_games, team_id, target_date)
    result: dict[str, Any] = {}
    previous = None if history.empty else history.iloc[-1]
    result[f"{side}_days_since_previous_game"] = None if previous is None else int((target_date - previous["game_date"]).days)
    days = result[f"{side}_days_since_previous_game"]
    result[f"{side}_short_week"] = None if days is None else int(days < 6)
    result[f"{side}_bye_or_long_rest"] = None if days is None else int(days >= 10)
    result[f"{side}_prior_games"] = 0.0 if history.empty else float(history["games_on_date"].sum())
    season_history = history.loc[history["season"].eq(season)] if not history.empty else history
    result[f"{side}_prior_season_games"] = 0.0 if season_history.empty else float(season_history["games_on_date"].sum())
    result[f"{side}_source_era_missing"] = int(history.empty)
    for metric in ROLLING_METRICS:
        series = pd.to_numeric(history[metric], errors="coerce") if not history.empty else pd.Series(dtype="float64")
        season_series = pd.to_numeric(season_history[metric], errors="coerce") if not season_history.empty else pd.Series(dtype="float64")
        result[f"{side}_{metric}_season_to_date"] = None if season_series.dropna().empty else float(season_series.mean())
        for window in (4, 8, 16):
            values = series.tail(window).dropna()
            result[f"{side}_{metric}_last_{window}"] = None if values.empty else float(values.mean())
    return result


def materialize_feature_vector(
    target: Mapping[str, Any], team_games: pd.DataFrame, feature_names: Sequence[str] = GAME_FEATURES
) -> dict[str, Any]:
    """Materialize one vector without reading target-game truth or market fields."""

    target_date = pd.Timestamp(target["game_date"]).normalize()
    season = int(target["season"])
    values: dict[str, Any] = {
        "season": season,
        "week": int(target["week"]),
        "game_type": str(target["game_type"]),
        "game_month": int(target_date.month),
        # DuckDB dayofweek contract: Sunday=0 through Saturday=6.
        "game_weekday": int((target_date.weekday() + 1) % 7),
        "neutral_site": int(str(target.get("location") or "") == "Neutral"),
        "division_game": int(target["division_game"]),
        "roof": None if pd.isna(target.get("roof")) else str(target.get("roof")),
        "surface": None if pd.isna(target.get("surface")) else str(target.get("surface")),
    }
    values.update(_side_features(team_games, side="home", team_id=str(target["canonical_home_team_id"]), target_date=target_date, season=season))
    values.update(_side_features(team_games, side="away", team_id=str(target["canonical_away_team_id"]), target_date=target_date, season=season))
    ordered = tuple(str(name) for name in feature_names)
    if ordered != tuple(GAME_FEATURES) or set(values) != set(ordered):
        raise NflProspectiveShadowError("prospective vector differs from ordered Gold contract")
    return {name: _json_value(values[name]) for name in ordered}


def historical_feature_parity(runtime: FoundationRuntime, *, game_id: str | None = None) -> dict[str, Any]:
    """Compare all 197 derived inputs for one completed 2025 game, without targets."""

    gold = pq.read_table(runtime.paths.game_path, columns=["canonical_game_id", *GAME_FEATURES]).to_pandas()
    candidate = gold.loc[gold["canonical_game_id"].astype(str).str.startswith("2025_")].sort_values("canonical_game_id").iloc[0] if game_id is None else gold.loc[gold["canonical_game_id"].eq(game_id)].iloc[0]
    dim = pq.read_table(runtime.objects["dim_nfl_game"]["path"]).to_pandas()
    schedule = pq.read_table(runtime.paths.schedule_path, columns=["game_id", "div_game"]).to_pandas()
    target = dim.loc[dim["canonical_game_id"].eq(candidate["canonical_game_id"])].iloc[0].to_dict()
    target["division_game"] = int(schedule.loc[schedule["game_id"].eq(candidate["canonical_game_id"]), "div_game"].iloc[0])
    team_games = pq.read_table(runtime.objects["fact_nfl_team_game"]["path"]).to_pandas()
    derived = materialize_feature_vector(target, team_games)
    mismatches: list[str] = []
    for name in GAME_FEATURES:
        expected, actual = _json_value(candidate[name]), derived[name]
        if expected is None or actual is None:
            if expected is not actual: mismatches.append(name)
        elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            if not math.isclose(float(expected), float(actual), rel_tol=1e-12, abs_tol=1e-12): mismatches.append(name)
        elif expected != actual: mismatches.append(name)
    if mismatches:
        raise NflProspectiveShadowError(f"historical Gold derivation parity differs: {mismatches[:10]}")
    return {"canonicalGameId": str(candidate["canonical_game_id"]), "featureCount": len(GAME_FEATURES), "mismatchCount": 0, "targetOutcomesRead": False}


def _scheduled_start(target: Mapping[str, Any]) -> datetime:
    # nflverse schedules document gametime as US Eastern, including neutral games.
    local = datetime.fromisoformat(f"{target['game_date']}T{target['gametime']}").replace(tzinfo=EASTERN)
    return local.astimezone(UTC)


def _load_targets(runtime: FoundationRuntime, *, as_of: datetime) -> tuple[list[dict[str, Any]], pd.DataFrame, dict[str, dict[str, str]]]:
    dim = pq.read_table(runtime.objects["dim_nfl_game"]["path"]).to_pandas()
    schedule = pq.read_table(runtime.paths.schedule_path, columns=["game_id", "div_game"]).to_pandas()
    teams = pq.read_table(runtime.objects["dim_nfl_team"]["path"]).to_pandas()
    names = {str(row.canonical_team_id): {"sourceTeamId": str(row.source_team_abbr), "displayName": str(row.team_name)} for row in teams.itertuples(index=False)}
    rows = dim.loc[dim["season"].eq(2026) & dim["game_type"].isin(["REG", "POST", "WC", "DIV", "CON", "SB"])].copy()
    rows = rows.loc[rows["home_points"].isna() & rows["away_points"].isna()]
    division = dict(zip(schedule["game_id"].astype(str), schedule["div_game"].astype(int), strict=True))
    targets = []
    for raw in rows.sort_values(["game_date", "gametime", "canonical_game_id"], kind="stable").to_dict("records"):
        raw["division_game"] = division[str(raw["canonical_game_id"])]
        raw["scheduled_start_utc"] = _scheduled_start(raw)
        if raw["scheduled_start_utc"] > as_of:
            targets.append(raw)
    return targets, pq.read_table(runtime.objects["fact_nfl_team_game"]["path"]).to_pandas(), names


def _select_slate_targets(
    targets: Sequence[Mapping[str, Any]],
    *,
    slate_date: date | None,
    next_slate_only: bool,
) -> list[Mapping[str, Any]]:
    """Select an exact or next slate without changing target ordering."""

    if slate_date is not None and next_slate_only:
        raise NflProspectiveShadowError("slate_date and next_slate_only are mutually exclusive")
    if slate_date is not None:
        return [target for target in targets if str(target["game_date"]) == slate_date.isoformat()]
    if next_slate_only and targets:
        next_date = min(str(target["game_date"]) for target in targets)
        return [target for target in targets if str(target["game_date"]) == next_date]
    return list(targets)


def _persist_feature_vector(root: Path, record: Mapping[str, Any]) -> tuple[str, Path, bool]:
    payload = canonical_json_bytes(record); digest = hashlib.sha256(payload).hexdigest(); final = root / "feature-vectors" / "sha256" / digest
    final.parent.mkdir(parents=True, exist_ok=True); created = False
    if not final.exists():
        staging = final.parent / f".staging-{uuid.uuid4().hex}"
        staging.mkdir(parents=False, exist_ok=False)
        try:
            with (staging / "feature-vector.json").open("xb") as stream: stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            try: os.replace(staging, final); created = True
            except OSError:
                if not final.exists(): raise
        finally:
            if staging.exists(): shutil.rmtree(staging)
    if (final / "feature-vector.json").read_bytes() != payload:
        raise NflProspectiveShadowError("feature vector content address differs")
    return digest, final / "feature-vector.json", created


def verify_activation_reload_fixture(
    root: Path, fixture_sha256: str, frozen: VerifiedFrozenM1
) -> dict[str, Any]:
    """Rehash fixture/vector bytes and reproduce expected model output without fit."""

    fixture_path = Path(root) / "activation-fixtures" / "sha256" / fixture_sha256 / "fixture.json"
    payload = fixture_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != fixture_sha256:
        raise NflProspectiveShadowError("activation reload fixture content address differs")
    fixture = json.loads(payload)
    if canonical_json_bytes(fixture) != payload or fixture.get("modelManifestSha256") != MODEL_MANIFEST_SHA256 or fixture.get("modelBinarySha256") != MODEL_BINARY_SHA256 or fixture.get("noRefit") is not True:
        raise NflProspectiveShadowError("activation reload fixture authority differs")
    vector_sha = str(fixture.get("featureVectorSha256") or "")
    vector_path = Path(root) / "feature-vectors" / "sha256" / vector_sha / "feature-vector.json"
    vector_payload = vector_path.read_bytes()
    if hashlib.sha256(vector_payload).hexdigest() != vector_sha:
        raise NflProspectiveShadowError("activation fixture feature-vector address differs")
    vector = json.loads(vector_payload)
    if canonical_json_bytes(vector) != vector_payload or vector.get("featureNames") != list(frozen.feature_names):
        raise NflProspectiveShadowError("activation fixture feature contract differs")
    frame = pd.DataFrame([vector["values"]], columns=list(frozen.feature_names))
    prediction = frozen.model_bundle["scoreModels"]["XGBOOST"].predict(frame)
    observed = (
        format(float(prediction.expected_home_points[0]), ".17g"),
        format(float(prediction.expected_away_points[0]), ".17g"),
    )
    if observed != (fixture.get("expectedHomePoints"), fixture.get("expectedAwayPoints")):
        raise NflProspectiveShadowError("activation reload fixture prediction differs")
    return {"fixtureSha256": fixture_sha256, "reproduced": True, "modelsFit": 0}


def _team_ref(target: Mapping[str, Any], names: Mapping[str, Mapping[str, str]], side: str) -> dict[str, str]:
    team_id = str(target[f"canonical_{side}_team_id"]); source_id = str(target[f"source_{side}_team_id"]); abbreviation = team_id
    identity = {"abbreviation": abbreviation, "source": "NFLVERSE", "sourceTeamId": source_id, "teamId": team_id}
    return {**identity, "displayName": names[team_id]["displayName"], "identitySha256": hashlib.sha256(canonical_json_bytes(identity)).hexdigest()}


def _pmf_rows(home: np.ndarray, away: np.ndarray) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    pairs, counts = np.unique(np.column_stack((home, away)), axis=0, return_counts=True); draws = len(home)
    joint = [{"homeScore": int(pair[0]), "awayScore": int(pair[1]), "probability": float(count/draws)} for pair, count in zip(pairs, counts, strict=True)]
    margin_values, margin_counts = np.unique(home-away, return_counts=True); total_values, total_counts = np.unique(home+away, return_counts=True)
    margin = [{"homeMinusAway": int(value), "probability": float(count/draws)} for value, count in zip(margin_values, margin_counts, strict=True)]
    total = [{"totalScore": int(value), "probability": float(count/draws)} for value, count in zip(total_values, total_counts, strict=True)]
    return joint, margin, total


def _git_revision() -> str:
    try: return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.SubprocessError): return "UNKNOWN_REVISION"


def _forecast_record(
    *, target: Mapping[str, Any], vector_sha: str, vector: Mapping[str, Any], names: Mapping[str, Mapping[str, str]],
    simulation_home: np.ndarray, simulation_away: np.ndarray, snapshot_type: str, snapshot_version: int,
    frozen: VerifiedFrozenM1, schedule_as_of: str, source_cutoff: str, forecast_cutoff: str, available_as_of: str,
    producer_revision: str,
) -> dict[str, Any]:
    home = simulation_home.astype(float); away = simulation_away.astype(float); margin = home-away; total = home+away; draws = len(home)
    joint, margin_pmf, total_pmf = _pmf_rows(simulation_home, simulation_away)
    home_win = float(np.mean(margin > 0)); away_win = float(np.mean(margin < 0)); tie = float(np.mean(margin == 0))
    missing = [name for name, value in vector.items() if value is None]
    score = max(0, int(round(100.0 * (1.0 - len(missing)/len(vector)))))
    readiness = {"isReady": score >= 50, "score": score, "threshold": 50, "missingInputs": missing, "reasonCodes": ([] if not missing else ["FROZEN_TRAINING_MEDIAN_IMPUTATION_APPLIED"])}
    spreads = []
    for line in np.arange(-10.5, 11.0, 0.5):
        adjusted = margin + float(line); spreads.append({"line": float(line), "homeCoverProbability": float(np.mean(adjusted > 0)), "awayCoverProbability": float(np.mean(adjusted < 0)), "pushProbability": float(np.mean(adjusted == 0))})
    totals = []
    for line in np.arange(30.0, 61.0, 0.5):
        adjusted = total-float(line); totals.append({"line": float(line), "overProbability": float(np.mean(adjusted > 0)), "underProbability": float(np.mean(adjusted < 0)), "pushProbability": float(np.mean(adjusted == 0))})
    likely = sorted(joint, key=lambda x: (-x["probability"], x["homeScore"], x["awayScore"]))[:5]
    radius = 1.96 * math.sqrt(home_win*(1-home_win)/draws)
    prefixes = [float(np.mean(margin[:n] > 0)) for n in range(1000, draws+1, 1000)]
    record: dict[str, Any] = {
        "schemaVersion": ASP_SPORTS_GAME_FORECAST_V1, "forecastId": "PENDING", "snapshotType": snapshot_type,
        "sport": "NFL", "league": "NFL", "season": 2026, "seasonType": "REG" if target["game_type"] == "REG" else "POST", "week": int(target["week"]),
        "scheduleAsOfUtc": schedule_as_of, "availableAsOfUtc": available_as_of, "snapshotVersion": snapshot_version,
        "eventDate": str(target["game_date"]), "eventId": str(target["canonical_game_id"]), "sourceEventId": f"nflverse:{target['canonical_game_id']}",
        "scheduledStartUtc": _utc_text(target["scheduled_start_utc"]), "forecastCutoffUtc": forecast_cutoff, "sourceCutoffUtc": source_cutoff,
        "homeTeam": _team_ref(target, names, "home"), "awayTeam": _team_ref(target, names, "away"),
        "engine": {"engineId": "NFL_M1_XGBOOST", "engineVersion": "NFL_M1_2026_RESEARCH_SHADOW_V1", "modelManifestSha256": MODEL_MANIFEST_SHA256, "modelBinarySha256": MODEL_BINARY_SHA256, "candidateId": MODEL_CANDIDATE, "featureTier": "LONG_HISTORY_CORE", "trainingCutoff": TRAINING_CUTOFF, "trainingDatasetVersion": TRAINING_DATASET_VERSION, "trainingDatasetManifestSha256": FOUNDATION_MANIFEST_SHA256, "featureContractSha256": frozen.feature_contract_sha256, "producerRevision": producer_revision},
        "features": {"featureCount": len(vector), "featureVectorSha256": vector_sha, "missingFeatureCount": len(missing), "missingFeatures": missing, "missingReasons": {name: "NO_CURRENT_SEASON_PRIOR_HISTORY_OR_SOURCE_MISSING" for name in missing}, "readiness": readiness},
        "readiness": readiness, "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED", "executionStatus": "NOT_EXECUTABLE", "researchShadowOnly": True, "modelPromotionAllowed": False, "executionAllowed": False,
        "expectedHomeScore": float(home.mean()), "expectedAwayScore": float(away.mean()), "homeWinProbability": home_win, "awayWinProbability": away_win, "tieProbability": tie,
        "jointScoreDistribution": joint, "scoreMarginDistribution": margin_pmf, "totalScoreDistribution": total_pmf,
        "spreadCoverProbabilities": spreads, "overUnderProbabilities": totals, "mostLikelyScores": likely,
        "predictionInterval": {"confidenceLevel": 0.90, "homeScoreLower": float(np.quantile(home,.05)), "homeScoreUpper": float(np.quantile(home,.95)), "awayScoreLower": float(np.quantile(away,.05)), "awayScoreUpper": float(np.quantile(away,.95)), "totalLower": float(np.quantile(total,.05)), "totalUpper": float(np.quantile(total,.95)), "marginLower": float(np.quantile(margin,.05)), "marginUpper": float(np.quantile(margin,.95))},
        "uncertainty": {"method": "MONTE_CARLO_NORMAL_95_WITH_PREFIX_STABILITY", "confidenceLevel": .95, "homeWinProbabilityLower": max(0.0,home_win-radius), "homeWinProbabilityUpper": min(1.0,home_win+radius), "expectedTotalScoreStdError": float(np.std(total,ddof=0)/math.sqrt(draws)), "maxBatchProbabilityDelta": max(abs(value-home_win) for value in prefixes)},
        "simulator": {"simulatorId": "NFL_M1_EMPIRICAL_PAIRED_RESIDUAL", "simulatorVersion": SIMULATION_CONTRACT_VERSION, "seed": SIMULATION_SEED, "simulationCount": draws, "completedSimulations": draws},
    }
    record["forecastId"] = derive_sports_game_forecast_id(record)
    return record


def _read_index(root: Path) -> dict[str, Any]:
    path = root / "prospective-index.json"
    if not path.exists(): return {"contract": ACTIVATION_INDEX_CONTRACT, "modelManifestSha256": MODEL_MANIFEST_SHA256, "events": {}, "bundles": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("contract") != ACTIVATION_INDEX_CONTRACT or value.get("modelManifestSha256") != MODEL_MANIFEST_SHA256: raise NflProspectiveShadowError("prospective index authority differs")
    return value


def _write_index(root: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value); temporary = root / f".prospective-index-{os.getpid()}.tmp"
    with temporary.open("wb") as stream: stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, root / "prospective-index.json")


def _publish_current_authority_bundles(
    index: Mapping[str, Any],
    exchange_root: Path,
    *,
    publication_deadline: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Compose one authoritative bundle per slate without erasing history.

    The first EARLY and latest CURRENT/FINAL_PREGAME records are copied byte-for-
    byte as child records into deterministic current-authority bundles. Bundles
    referenced by superseded snapshots remain discoverable as historical objects.
    """

    events = index.get("events")
    if not isinstance(events, Mapping) or not events:
        raise NflProspectiveShadowError("prospective index has no event authority")
    verified_cache: dict[str, Mapping[str, Any]] = {}
    selected_by_date: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    historical_shas: set[str] = set()

    def version(entry: Mapping[str, Any]) -> int:
        value = entry.get("snapshotVersion")
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise NflProspectiveShadowError("indexed snapshot version differs")
        return value

    def resolve(entry: Mapping[str, Any], event_id: str, snapshot: str) -> Mapping[str, Any]:
        digest = str(entry.get("bundleSha256") or "")
        if digest not in verified_cache:
            verified_cache[digest] = verify_sports_forecast_bundle(exchange_root, digest).record
        candidates = [
            child for child in verified_cache[digest]["forecasts"]
            if child["forecastId"] == entry.get("forecastId")
        ]
        if len(candidates) != 1:
            raise NflProspectiveShadowError("indexed forecast does not resolve exactly once")
        child = candidates[0]
        if child["eventId"] != event_id or child["snapshotType"] != snapshot:
            raise NflProspectiveShadowError("indexed forecast event/snapshot identity differs")
        return child

    for event_id, event_value in sorted(events.items()):
        if not isinstance(event_value, Mapping):
            raise NflProspectiveShadowError("prospective event index differs")
        for snapshot in ("EARLY", "CURRENT", "FINAL_PREGAME"):
            entries = event_value.get(snapshot)
            if not isinstance(entries, list):
                raise NflProspectiveShadowError("prospective snapshot index differs")
            if snapshot in {"EARLY", "CURRENT"} and not entries:
                raise NflProspectiveShadowError(f"{event_id} lacks required {snapshot} authority")
            if not entries:
                continue
            ordered = sorted(entries, key=version)
            versions = [version(entry) for entry in ordered]
            if len(versions) != len(set(versions)):
                raise NflProspectiveShadowError("prospective snapshot versions are not unique")
            if snapshot == "EARLY" and len(ordered) != 1:
                raise NflProspectiveShadowError("EARLY authority must be immutable and singular")
            selected = ordered[0] if snapshot == "EARLY" else ordered[-1]
            for superseded in (() if snapshot == "EARLY" else ordered[:-1]):
                historical_shas.add(str(superseded.get("bundleSha256") or ""))
            child = resolve(selected, str(event_id), snapshot)
            selected_by_date[child["eventDate"]].append(child)

    current_bundles: list[dict[str, Any]] = []
    for slate_date, forecasts in sorted(selected_by_date.items()):
        generated = max(str(child["availableAsOfUtc"]) for child in forecasts)
        bundle = {
            "schemaVersion": ASP_SPORTS_FORECAST_EXCHANGE_V1,
            "bundleId": "PENDING",
            "sport": "NFL", "league": "NFL", "season": 2026,
            "slateDate": slate_date,
            "generatedAtUtc": generated,
            "status": "RESEARCH_SHADOW",
            "researchShadowOnly": True,
            "modelPromotionAllowed": False,
            "executionAllowed": False,
            "parlaysAllowed": False,
            "forecasts": forecasts,
        }
        bundle["bundleId"] = derive_sports_forecast_bundle_id(bundle)
        if publication_deadline is not None and _now_utc().astimezone(UTC) > publication_deadline:
            raise NflProspectiveShadowError("current-authority publication missed FINAL_PREGAME cutoff")
        published = write_sports_forecast_bundle(
            exchange_root,
            bundle,
            not_after_utc=publication_deadline,
            now_utc=_now_utc,
        )
        verified = verify_sports_forecast_bundle(exchange_root, published.bundle_sha256)
        current_bundles.append({
            "slateDate": slate_date,
            "bundleSha256": published.bundle_sha256,
            "bundleLogicalUri": f"asp-model-exchange://{BUNDLE_OBJECT_FAMILY}/sha256/{published.bundle_sha256}/bundle.json",
            "forecastCount": len(verified.record["forecasts"]),
            "forecastIds": [child["forecastId"] for child in verified.record["forecasts"]],
        })
    current_shas = {item["bundleSha256"] for item in current_bundles}
    historical_shas -= current_shas
    return current_bundles, sorted(historical_shas)


def activate_2026_shadow(
    *, publication_root: Path = DEFAULT_PUBLICATION_ROOT, exchange_root: Path = DEFAULT_EXCHANGE_ROOT,
    artifact_root: Path = ARTIFACT_ROOT, foundation_root: Path = DEFAULT_NFL_STAGING_ROOT / "foundation-v1",
    as_of: datetime | None = None, snapshot_types: Sequence[str] = ("EARLY", "CURRENT"), producer_revision: str | None = None,
    slate_date: date | None = None, next_slate_only: bool = False,
) -> dict[str, Any]:
    """Create upcoming 2026 vectors, score once, and publish date bundles.

    ``slate_date`` and ``next_slate_only`` provide a bounded operational path.
    They filter targets before vector construction and scoring, so a current
    refresh cannot silently rescore the full future schedule.
    """

    forecast_cutoff = (as_of or _now_utc()).astimezone(UTC); publication_root = Path(publication_root).resolve(); exchange_root = Path(exchange_root).resolve(); publication_root.mkdir(parents=True, exist_ok=True); exchange_root.mkdir(parents=True, exist_ok=True)
    requested = tuple(dict.fromkeys(str(item) for item in snapshot_types))
    invalid = set(requested)-{"EARLY","CURRENT","FINAL_PREGAME"}
    if invalid: raise NflProspectiveShadowError(f"snapshot types differ: {sorted(invalid)}")
    if slate_date is not None and next_slate_only:
        raise NflProspectiveShadowError("slate_date and next_slate_only are mutually exclusive")
    if "FINAL_PREGAME" in requested and len(requested) != 1:
        raise NflProspectiveShadowError("FINAL_PREGAME must run as a bounded standalone snapshot job")
    frozen = verify_frozen_m1(artifact_root=artifact_root, foundation_root=foundation_root, publication_root=publication_root); runtime = load_foundation_runtime(foundation_root)
    schedule_as_of = _utc(runtime.schedule_as_of_utc)
    if schedule_as_of > forecast_cutoff: raise NflProspectiveShadowError("foundation schedule is newer than activation cutoff")
    parity = historical_feature_parity(runtime)
    targets, team_games, names = _load_targets(runtime, as_of=forecast_cutoff)
    if requested == ("FINAL_PREGAME",):
        targets = [
            target for target in targets
            if 900 <= (target["scheduled_start_utc"] - forecast_cutoff).total_seconds() <= 1_800
        ]
    targets = list(_select_slate_targets(targets, slate_date=slate_date, next_slate_only=next_slate_only))
    if not targets:
        return {
            "status": "NO_ELIGIBLE_UPCOMING_GAMES", "games": 0, "parity": parity,
            "reason": (
                "NO_DUE_FINAL_PREGAME_GAMES" if requested == ("FINAL_PREGAME",)
                else "NO_GAMES_ON_REQUESTED_SLATE" if slate_date is not None
                else "NO_UPCOMING_GAMES"
            ),
        }
    final_publication_deadline = (
        min(target["scheduled_start_utc"] - timedelta(minutes=15) for target in targets)
        if requested == ("FINAL_PREGAME",) else None
    )
    vectors = [materialize_feature_vector(target, team_games, frozen.feature_names) for target in targets]
    value_hashes = [
        hashlib.sha256(
            canonical_json_bytes(
                {"featureNames": list(frozen.feature_names), "values": [vector[name] for name in frozen.feature_names]}
            )
        ).hexdigest()
        for vector in vectors
    ]
    index = _read_index(publication_root)
    revision = producer_revision or _git_revision(); cutoff_text = _utc_text(forecast_cutoff); source_cutoff = runtime.schedule_as_of_utc

    def snapshot_due(
        event_index: Mapping[str, Sequence[Mapping[str, Any]]],
        snapshot: str,
        target: Mapping[str, Any],
        values_sha: str,
    ) -> bool:
        if snapshot == "EARLY" and event_index["EARLY"]: return False
        if any(entry.get("forecastCutoffUtc") == cutoff_text for entry in event_index[snapshot]): return False
        if snapshot in {"CURRENT", "FINAL_PREGAME"} and any(
            entry.get("featureValuesSha256") == values_sha
            and entry.get("sourceFoundationManifestSha256") == runtime.paths.foundation_manifest_sha256
            and entry.get("producerRevision") == revision
            for entry in event_index[snapshot]
        ): return False
        if snapshot == "FINAL_PREGAME":
            seconds = (target["scheduled_start_utc"]-forecast_cutoff).total_seconds()
            # CURRENT carries earlier refreshes. FINAL_PREGAME is a narrow,
            # pre-kickoff freeze and can never be substituted after kickoff.
            if seconds < 900 or seconds > 1_800: return False
        return True

    vector_hashes = []
    for target, vector, values_sha in zip(targets, vectors, value_hashes, strict=True):
        event_id = str(target["canonical_game_id"])
        event_index = index["events"].setdefault(event_id, {"EARLY": [], "CURRENT": [], "FINAL_PREGAME": []})
        matching_existing = next((
            str(entry["featureVectorSha256"])
            for snapshot in ("CURRENT", "EARLY", "FINAL_PREGAME")
            for entry in reversed(event_index[snapshot])
            if entry.get("featureValuesSha256") == values_sha
            and entry.get("sourceFoundationManifestSha256") == runtime.paths.foundation_manifest_sha256
        ), None)
        if matching_existing is not None and not any(
            snapshot_due(event_index, snapshot, target, values_sha) for snapshot in requested
        ):
            vector_hashes.append(matching_existing)
            continue
        vector_record = {"contract": FEATURE_VECTOR_CONTRACT, "eventId": event_id, "season": 2026, "forecastCutoffUtc": cutoff_text, "sourceCutoffUtc": runtime.schedule_as_of_utc, "trainingFoundationManifestSha256": FOUNDATION_MANIFEST_SHA256, "sourceFoundationManifestSha256": runtime.paths.foundation_manifest_sha256, "sourceDatasetVersionId": runtime.paths.dataset_version_id, "modelManifestSha256": MODEL_MANIFEST_SHA256, "featureContractSha256": frozen.feature_contract_sha256, "featureValuesSha256": values_sha, "featureNames": list(frozen.feature_names), "values": [vector[name] for name in frozen.feature_names], "missingFeatures": [name for name in frozen.feature_names if vector[name] is None], "targetOutcomeFieldsRead": False, "marketFieldsRead": False}
        digest, _, _ = _persist_feature_vector(publication_root, vector_record); vector_hashes.append(digest)
    frame = pd.DataFrame(vectors, columns=list(frozen.feature_names)); prediction = frozen.model_bundle["scoreModels"]["XGBOOST"].predict(frame)
    simulation = simulate_joint_scores(predicted_home_mean=prediction.expected_home_points, predicted_away_mean=prediction.expected_away_points, residual_authority=frozen.model_bundle["pairedResidualAuthority"], draws=SIMULATION_DRAWS, seed=SIMULATION_SEED)
    completed_at = _now_utc().astimezone(UTC)
    if completed_at < forecast_cutoff:
        raise NflProspectiveShadowError("completion clock precedes forecast evidence cutoff")
    completed_text = _utc_text(completed_at)
    late_final_omissions = 0
    final_forecasts_published = 0
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for position, (target, vector, vector_sha, values_sha) in enumerate(zip(targets, vectors, vector_hashes, value_hashes, strict=True)):
        event_id = str(target["canonical_game_id"]); event_index = index["events"].setdefault(event_id, {"EARLY": [], "CURRENT": [], "FINAL_PREGAME": []})
        for snapshot in requested:
            if not snapshot_due(event_index, snapshot, target, values_sha): continue
            if completed_at >= target["scheduled_start_utc"]:
                if snapshot == "FINAL_PREGAME": late_final_omissions += 1
                continue
            if snapshot == "FINAL_PREGAME" and completed_at > target["scheduled_start_utc"] - timedelta(minutes=15):
                late_final_omissions += 1
                continue
            version = len(event_index[snapshot]) + 1
            record = _forecast_record(target=target, vector_sha=vector_sha, vector=vector, names=names, simulation_home=simulation.home[position], simulation_away=simulation.away[position], snapshot_type=snapshot, snapshot_version=version, frozen=frozen, schedule_as_of=runtime.schedule_as_of_utc, source_cutoff=source_cutoff, forecast_cutoff=cutoff_text, available_as_of=completed_text, producer_revision=revision)
            if any(entry.get("forecastId") == record["forecastId"] for entry in event_index[snapshot]): continue
            by_date[str(target["game_date"])].append(record)
    publications = []
    for slate_date, forecasts in sorted(by_date.items()):
        publication_check = _now_utc().astimezone(UTC)
        if publication_check < completed_at:
            raise NflProspectiveShadowError("publication clock precedes forecast completion")
        publishable = []
        for row in forecasts:
            kickoff = _utc(row["scheduledStartUtc"])
            if publication_check >= kickoff:
                if row["snapshotType"] == "FINAL_PREGAME": late_final_omissions += 1
                continue
            if row["snapshotType"] == "FINAL_PREGAME" and publication_check > kickoff - timedelta(minutes=15):
                late_final_omissions += 1
                continue
            publishable.append(row)
        if not publishable:
            continue
        publication_text = _utc_text(publication_check)
        bundle = {"schemaVersion": ASP_SPORTS_FORECAST_EXCHANGE_V1, "bundleId": "PENDING", "sport": "NFL", "league": "NFL", "season": 2026, "slateDate": slate_date, "generatedAtUtc": publication_text, "status": "RESEARCH_SHADOW", "researchShadowOnly": True, "modelPromotionAllowed": False, "executionAllowed": False, "parlaysAllowed": False, "forecasts": publishable}
        publication_deadline = min(
            (_utc(row["scheduledStartUtc"]) - timedelta(minutes=15) for row in publishable if row["snapshotType"] == "FINAL_PREGAME"),
            default=None,
        )
        bundle["bundleId"] = derive_sports_forecast_bundle_id(bundle); published = write_sports_forecast_bundle(exchange_root, bundle, not_after_utc=publication_deadline, now_utc=_now_utc); verify_sports_forecast_bundle(exchange_root, published.bundle_sha256)
        logical = f"asp-model-exchange://{BUNDLE_OBJECT_FAMILY}/sha256/{published.bundle_sha256}/bundle.json"
        item = {"slateDate": slate_date, "bundleSha256": published.bundle_sha256, "bundleLogicalUri": logical, "forecastCount": len(publishable), "forecastIds": [row["forecastId"] for row in publishable]}
        final_forecasts_published += sum(row["snapshotType"] == "FINAL_PREGAME" for row in publishable)
        if item["bundleSha256"] not in {entry["bundleSha256"] for entry in index["bundles"]}: index["bundles"].append(item)
        for row in publishable:
            entries = index["events"][row["eventId"]][row["snapshotType"]]
            vector_position = next(index for index, target in enumerate(targets) if str(target["canonical_game_id"]) == row["eventId"])
            entries.append({"forecastId": row["forecastId"], "forecastCutoffUtc": row["forecastCutoffUtc"], "featureVectorSha256": row["features"]["featureVectorSha256"], "featureValuesSha256": value_hashes[vector_position], "sourceFoundationManifestSha256": runtime.paths.foundation_manifest_sha256, "producerRevision": revision, "snapshotVersion": row["snapshotVersion"], "bundleSha256": published.bundle_sha256, "bundleLogicalUri": logical})
        publications.append(item)
    run_completed = _now_utc().astimezone(UTC)
    if run_completed < completed_at:
        raise NflProspectiveShadowError("run-completion clock precedes forecast completion")
    run_completed_text = _utc_text(run_completed)
    index["updatedAtUtc"] = run_completed_text; index["featureContractSha256"] = frozen.feature_contract_sha256; index["modelBinarySha256"] = MODEL_BINARY_SHA256
    existing_fixture_sha = index.get("reloadFixtureSha256")
    if existing_fixture_sha:
        fixture_sha = str(existing_fixture_sha)
        fixture_path = publication_root / "activation-fixtures" / "sha256" / fixture_sha / "fixture.json"
        verify_activation_reload_fixture(publication_root, fixture_sha, frozen)
    else:
        fixture_vector = frame.iloc[[0]]; fixture_prediction = frozen.model_bundle["scoreModels"]["XGBOOST"].predict(fixture_vector)
        fixture = {"contract": "ASP_NFL_M1_ACTIVATION_RELOAD_FIXTURE_V1", "modelManifestSha256": MODEL_MANIFEST_SHA256, "modelBinarySha256": MODEL_BINARY_SHA256, "featureVectorSha256": vector_hashes[0], "eventId": str(targets[0]["canonical_game_id"]), "expectedHomePoints": format(float(fixture_prediction.expected_home_points[0]), ".17g"), "expectedAwayPoints": format(float(fixture_prediction.expected_away_points[0]), ".17g"), "noRefit": True}
        fixture_payload = canonical_json_bytes(fixture); fixture_sha = hashlib.sha256(fixture_payload).hexdigest(); fixture_dir = publication_root / "activation-fixtures" / "sha256" / fixture_sha; fixture_dir.mkdir(parents=True, exist_ok=True); fixture_path = fixture_dir / "fixture.json"
        if fixture_path.exists() and fixture_path.read_bytes() != fixture_payload: raise NflProspectiveShadowError("activation reload fixture differs")
        if not fixture_path.exists(): fixture_path.write_bytes(fixture_payload)
        verify_activation_reload_fixture(publication_root, fixture_sha, frozen)
    index["reloadFixtureSha256"] = fixture_sha; index["sourceFoundationManifestSha256"] = runtime.paths.foundation_manifest_sha256; index["sourceDatasetVersionId"] = runtime.paths.dataset_version_id
    authority_deadline = final_publication_deadline if final_forecasts_published else None
    current_authority_bundles, historical_bundle_shas = _publish_current_authority_bundles(
        index, exchange_root, publication_deadline=authority_deadline
    )
    index["currentAuthorityBundles"] = current_authority_bundles
    index["historicalAuthorityBundleSha256s"] = historical_bundle_shas
    locator = write_nfl_2026_research_shadow_locator(
        exchange_root,
        current_bundle_sha256s=[entry["bundleSha256"] for entry in current_authority_bundles],
        historical_bundle_sha256s=historical_bundle_shas,
        feature_contract_sha256=frozen.feature_contract_sha256,
        updated_at_utc=run_completed_text,
        not_after_utc=authority_deadline,
        now_utc=_now_utc,
    )
    _write_index(publication_root, index)
    locator_path = exchange_root / BUNDLE_OBJECT_FAMILY / "nfl-2026-research-shadow-index.json"
    return {"status": "ACTIVE", "games": len(targets), "selectedSlateDates": sorted({str(target["game_date"]) for target in targets}), "selectionMode": "EXACT_SLATE" if slate_date is not None else "NEXT_SLATE_ONLY" if next_slate_only else "ALL_UPCOMING", "forecastsCreated": sum(item["forecastCount"] for item in publications), "bundleCount": len(publications), "bundles": publications, "forecastCutoffUtc": cutoff_text, "completedAtUtc": run_completed_text, "lateFinalPregameOmissions": late_final_omissions, "modelManifestSha256": MODEL_MANIFEST_SHA256, "modelBinarySha256": MODEL_BINARY_SHA256, "sourceFoundationManifestSha256": runtime.paths.foundation_manifest_sha256, "featureContractSha256": frozen.feature_contract_sha256, "residualAuthoritySha256": frozen.residual_authority_sha256, "featureVectorCount": len(vector_hashes), "reloadFixtureSha256": fixture_sha, "reloadFixturePath": str(fixture_path), "reloadFixtureReproduced": True, "historicalParity": parity, "modelsFit": 0, "modelsPromoted": 0, "marketFieldsRead": False, "indexPath": str(publication_root / "prospective-index.json"), "exchangeLocatorPath": str(locator_path), "exchangeLocatorCurrentBundleCount": locator["currentBundleCount"], "exchangeLocatorCurrentForecastCount": sum(item["forecastCount"] for item in current_authority_bundles), "exchangeLocatorCurrentBundleListSha256": locator["currentBundleListSha256"], "exchangeLocatorHistoricalBundleCount": locator["historicalBundleCount"], "exchangeLocatorHistoricalBundleListSha256": locator["historicalBundleListSha256"], "producerRevision": revision}


__all__ = ["activate_2026_shadow", "historical_feature_parity", "load_foundation_runtime", "materialize_feature_vector", "verify_activation_reload_fixture", "verify_frozen_m1", "NflProspectiveShadowError"]
