"""Research-only NBA future forecast builder; no acquisition or publication.

This entry point fails closed without real admitted sources, a current complete
history receipt, chronological residuals and earlier empirical overtime periods.
It never supplies demonstration games or fills an unsupported source gap.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .authority import RESEARCH_FLAGS, RIGHTS, require, verified_bytes
from .distribution import game_seed, simulate, summarize
from .features import build_features, feature_contract
from .models import FittedPointModel


SCHEMA = "NBA_GEN1_RESEARCH_FORECAST_V1"
ENGINE = "NBA_GEN1_TEAM_MARGIN_TOTAL"
VERSION = "NBA_GEN1_RESEARCH_V1"
_TARGET_FIELDS = {
    "game_id", "source_game_id", "season", "season_type", "home_team_id", "away_team_id",
    "scheduled_tipoff_utc", "schedule_available_at_utc", "status", "source_revision",
    "home_team_name", "away_team_name",
}
_REF_KEYS = (
    "sourceIndex", "approvalReceipt", "modelArtifact", "preprocessorArtifact", "featureContract",
    "residualPopulation", "residualReceipt", "overtimePopulation", "historyPopulation",
    "historyCoverageReceipt", "scheduleEvidence",
)


def _utc(value: Any, label: str) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    require(not pd.isna(parsed) and parsed.tzinfo is not None, f"Explicit UTC-convertible clock required: {label}")
    return parsed.tz_convert("UTC")


def _clock_series(frame: pd.DataFrame, column: str) -> pd.Series:
    require(column in frame, "Missing source clock column: " + column)
    return frame[column].map(lambda value: _utc(value, column))


def _json(raw: bytes, label: str) -> dict:
    value = json.loads(raw)
    require(isinstance(value, dict), label + " must contain an object")
    return value


def _same_reference(left: dict, right: dict) -> bool:
    return left["sha256"] == right["sha256"] and left["bytes"] == right["bytes"]


def _target(target: dict, cutoff: pd.Timestamp, now: pd.Timestamp) -> tuple[dict, pd.Timestamp]:
    require(isinstance(target, dict) and not set(target).difference(_TARGET_FIELDS),
            "Target must be identity/schedule only; outcome, box, lineup and undeclared fields are forbidden")
    required = _TARGET_FIELDS.difference({"home_team_name", "away_team_name"})
    require(required <= set(target), "Missing stable source or canonical schedule identity")
    require(target["status"] == "SCHEDULED" and target["season_type"] == "REGULAR",
            "Only a genuinely scheduled NBA regular-season game is eligible")
    for key in ("game_id", "source_game_id", "home_team_id", "away_team_id"):
        require(target[key] is not None and bool(str(target[key]).strip()), "Missing stable " + key)
    require(target["home_team_id"] != target["away_team_id"], "Home/away identity collision")
    require(isinstance(target["season"], (int, np.integer)) and target["season"] >= 1946,
            "Season must be its integer start year")
    require(isinstance(target["source_revision"], (int, np.integer)) and target["source_revision"] >= 1,
            "Schedule source revision must be a positive integer")
    tipoff = _utc(target["scheduled_tipoff_utc"], "scheduled_tipoff_utc")
    schedule_available = _utc(target["schedule_available_at_utc"], "schedule_available_at_utc")
    require(schedule_available < cutoff <= now < tipoff,
            "Require authentic schedule availability < source cutoff <= actual creation time < original tipoff")
    return dict(target), tipoff


def _bound_frame(raw: bytes, supplied: pd.DataFrame, label: str) -> pd.DataFrame:
    retained = pd.read_parquet(io.BytesIO(raw))
    require(isinstance(supplied, pd.DataFrame), label + " must be a DataFrame")
    try:
        pd.testing.assert_frame_equal(retained.reset_index(drop=True), supplied.reset_index(drop=True), check_dtype=False)
    except AssertionError as exc:
        raise ValueError(label + " differs from its physically bound retained population") from exc
    return retained


def _admit_sources(bindings: dict, raw: dict[str, bytes], cutoff: pd.Timestamp, now: pd.Timestamp,
                   target: dict) -> tuple[dict, dict]:
    index = _json(raw["sourceIndex"], "source index")
    require(index.get("dataClassification") == "REAL_UNSCRAMBLED_OFFICIAL_GAMES"
            and index.get("reviewStatus") == "VERIFIED_REAL_TRAINING_AUTHORITY",
            "Real NBA source and named training/use review are required")
    require(index.get("reviewedBy") and index.get("provider"), "Named source review missing")
    require(index.get("timestampSemantics") == "AUTHENTICATED_SOURCE_REVISION_AVAILABILITY",
            "Reconstructed availability is not a future feature clock")
    require(all(index.get("rights", {}).get(key) is True for key in RIGHTS), "Established source/derivative rights are required")
    require(_same_reference(index["approvalReceipt"], bindings["approvalReceipt"]), "Approval receipt source mismatch")
    require(index.get("costAuthorization", {}).get("newSpendingAllowed") is False, "No new spending is authorized")
    require(index.get("rightsEvidence"), "Source rights evidence is missing")
    for bound in index["rightsEvidence"]:
        verified_bytes(bound)
    verified_bytes(index["timestampEvidence"])

    schedule = _json(raw["scheduleEvidence"], "schedule evidence")
    require(schedule.get("schemaVersion") == "NBA_GEN1_SCHEDULE_EVIDENCE_V1", "Unsupported schedule evidence schema")
    require(schedule.get("dataClassification") == "REAL_UNSCRAMBLED_OFFICIAL_GAMES", "Fixture schedule is ineligible")
    require(schedule.get("target") == target, "Schedule evidence does not bind this exact game/revision/orientation")
    require(schedule.get("sourceIndexSha256") == bindings["sourceIndex"]["sha256"], "Schedule source index differs")
    schedule_capture = _utc(schedule["capturedAtUtc"], "schedule capture")
    require(_utc(target["schedule_available_at_utc"], "schedule availability") <= schedule_capture <= cutoff,
            "Schedule capture must actually precede this forecast cutoff")
    verified_bytes(schedule["sourceObject"])

    coverage = _json(raw["historyCoverageReceipt"], "current history coverage")
    require(coverage.get("schemaVersion") == "NBA_GEN1_CURRENT_HISTORY_COVERAGE_V1", "Current history coverage receipt required")
    require(coverage.get("targetGameId") == target["game_id"], "Coverage belongs to another target")
    require(coverage.get("sourceIndexSha256") == bindings["sourceIndex"]["sha256"], "History coverage source mismatch")
    require(set(coverage.get("teamIds", [])) == {target["home_team_id"], target["away_team_id"]},
            "Both target teams require current history coverage")
    require(_utc(coverage["sourceCutoffUtc"], "coverage source cutoff") == cutoff
            and _utc(coverage["completeThroughUtc"], "history complete through") == cutoff,
            "Current history must be certified complete through the exact forecast source cutoff")
    require(coverage.get("membershipComplete") is True and coverage.get("missingGameIds") == [],
            "Intervening team games are missing or uncertified; stale histories are unsupported")
    require(_same_reference(coverage["historyPopulation"], bindings["historyPopulation"]), "Coverage history bytes differ")
    require(coverage.get("reviewedBy") and coverage.get("evidence"), "Named review and retained history-coverage evidence are required")
    require(_utc(coverage["createdAtUtc"], "coverage creation") <= now, "Coverage receipt has a future creation clock")
    for bound in coverage["evidence"]:
        verified_bytes(bound)
    return index, coverage


def build_shadow_forecast(fitted_model: FittedPointModel, history_df: pd.DataFrame, target: dict,
                          residual_frame: pd.DataFrame, overtime_frame: pd.DataFrame, bindings: dict,
                          cutoff_utc: str, draws: int = 10_000, master_seed: int = 20260913) -> dict[str, Any]:
    """Build, but never publish, one eligible real NBA research-shadow forecast.

    All physical references are checked on exact bytes. The passed in-memory
    model must equal the model in the verified artifact. Every historical row
    used must actually have been available/captured before the source cutoff.
    The caller owns the governed source intake; this function cannot certify an
    asserted complete-history flag without its named receipt and bound evidence.
    """
    now = pd.Timestamp(datetime.now(timezone.utc))
    cutoff = _utc(cutoff_utc, "source cutoff")
    target, tipoff = _target(target, cutoff, now)
    require(draws == 10_000, "NBA Gen 1's frozen simulation count is 10,000")
    require(all(key in bindings for key in _REF_KEYS), "Complete physical forecast bindings are required")
    raw = {key: verified_bytes(bindings[key]) for key in _REF_KEYS}
    _admit_sources(bindings, raw, cutoff, now, target)
    retained_contract = _json(raw["featureContract"], "feature contract")
    require(retained_contract == feature_contract(), "Fitted feature contract does not match executing code")
    require(_same_reference(bindings["modelArtifact"], bindings["preprocessorArtifact"]),
            "Gen 1 serializes preprocessing inside the same fitted model artifact; bind both names to it")
    bound_object = joblib.load(io.BytesIO(raw["modelArtifact"]))
    bound_model = bound_object.get("model") if isinstance(bound_object, dict) else bound_object
    require(isinstance(bound_model, FittedPointModel) and isinstance(fitted_model, FittedPointModel),
            "Verified fitted Gen 1 point-model artifact is required")
    require(joblib.hash(bound_model) == joblib.hash(fitted_model), "In-memory model differs from the physically bound artifact")
    require(bindings.get("modelTrainingIdentitySha256") == bound_model.training_identity_sha256,
            "Fitted training identity binding mismatch")
    require(bindings.get("modelConfigurationIdentity"), "Separate locked model configuration identity is required")

    history = _bound_frame(raw["historyPopulation"], history_df, "history")
    require("game_id" in history, "History game identities required")
    # Metadata exclusion precedes any feature or score/box use. A target row can
    # never enter features, irrespective of its accidental status or values.
    target_history_rows = int((history.game_id.astype(str) == str(target["game_id"])).sum())
    history = history[history.game_id.astype(str) != str(target["game_id"])].copy()
    for column in ("source_available_at_utc", "scheduled_tipoff_utc"):
        require((_clock_series(history, column) < cutoff).all(), "History includes a future or post-cutoff " + column)
    require((_clock_series(history, "captured_at_utc") <= cutoff).all(), "History capture occurred after forecast source cutoff")
    require(set(history.status) <= {"FINAL"}, "Future history must contain admitted finals only")
    features, audit = build_features(history, pd.DataFrame([target]))
    require(len(features) == 1 and bool(features.iloc[0].home_history_supported)
            and bool(features.iloc[0].away_history_supported), "Both teams need at least five current/prior-season games")

    residuals = _bound_frame(raw["residualPopulation"], residual_frame, "residual population")
    require({"game_id", "residual_home", "residual_away", "scheduled_tipoff_utc", "source_available_at_utc"} <= set(residuals),
            "Chronological residual columns and clocks are required")
    residual_receipt = _json(raw["residualReceipt"], "residual receipt")
    require(residual_receipt.get("schemaVersion") == "NBA_GEN1_CHRONOLOGICAL_RESIDUAL_RECEIPT_V1"
            and residual_receipt.get("residualType") == "CHRONOLOGICAL_OUT_OF_FOLD_ACTUAL_MINUS_PREDICTED",
            "In-sample or simulated residual donors are not eligible")
    require(_same_reference(residual_receipt["population"], bindings["residualPopulation"]), "Residual receipt does not bind these bytes")
    require(residual_receipt.get("sourceIndexSha256") == bindings["sourceIndex"]["sha256"], "Residual source mismatch")
    require(residual_receipt.get("modelConfigurationIdentity") == bindings["modelConfigurationIdentity"], "Residual family/configuration mismatch")
    require(residual_receipt.get("allTrainingBeforeDonorTipoff") is True
            and residual_receipt.get("allFeatureHistoryBeforeDonorTipoff") is True,
            "Residual training and feature chronology must be certified")
    require(residual_receipt.get("foldEvidence"), "Bound chronological fold evidence required")
    for bound in residual_receipt["foldEvidence"]:
        verified_bytes(bound)
    residuals = residuals[residuals.game_id.astype(str) != str(target["game_id"])].copy()
    require(not residuals.game_id.duplicated().any(), "Residual donors must be intact distinct games")
    residuals = residuals[(_clock_series(residuals, "source_available_at_utc") < cutoff)
                          & (_clock_series(residuals, "scheduled_tipoff_utc") < cutoff)]
    require(len(residuals) >= 200, "At least 200 eligible earlier chronological residual games required")

    overtime = _bound_frame(raw["overtimePopulation"], overtime_frame, "overtime population")
    require({"game_id", "source_revision", "period", "home_points", "away_points", "source_available_at_utc",
             "source_object_sha256"} <= set(overtime),
            "Actual oriented overtime period evidence and source clocks are required")
    overtime = overtime[overtime.game_id.astype(str) != str(target["game_id"])].copy()
    overtime = overtime[_clock_series(overtime, "source_available_at_utc") < cutoff]
    require(not overtime.duplicated(["game_id", "source_revision", "period"]).any(), "Duplicate overtime evidence period")
    latest_history = history.sort_values(["source_revision", "source_available_at_utc"]).drop_duplicates("game_id", keep="last")
    eligible_keys = set(zip(latest_history.game_id.astype(str), latest_history.source_revision.astype(int)))
    overtime = overtime[[key in eligible_keys for key in zip(overtime.game_id.astype(str), overtime.source_revision.astype(int))]]
    require(len(overtime) >= 20, "At least 20 eligible earlier observed overtime periods are required")
    # Each selected complete sequence binds the same governed final revision,
    # clock and source bytes. Intermediate tied periods cannot be cherry-picked
    # away: periods 5..4+OT must reconcile to tied regulation and the final score.
    history_keys = latest_history.assign(_game_key=latest_history.game_id.astype(str)).set_index(["_game_key", "source_revision"])
    for (game_id, revision), group in overtime.groupby(["game_id", "source_revision"], sort=False):
        game = history_keys.loc[(str(game_id), int(revision))]
        ordered = group.sort_values("period")
        require(len(ordered) == int(game.overtime_periods)
                and ordered.period.tolist() == list(range(5, 5 + int(game.overtime_periods))),
                "Included overtime games require their entire consecutive observed period sequence")
        points = ordered[["home_points", "away_points"]].to_numpy(float)
        require(np.isfinite(points).all() and (points >= 0).all() and (points == np.floor(points)).all(),
                "Overtime periods must contain observed nonnegative integer points")
        require((points[:-1, 0] == points[:-1, 1]).all() and points[-1, 0] != points[-1, 1],
                "Observed intermediate overtime periods must tie and the final period must resolve")
        regulation = np.array([game.home_score, game.away_score]) - points.sum(axis=0)
        require((regulation >= 0).all() and regulation[0] == regulation[1],
                "Overtime sequence does not reconcile to tied regulation and the final score")
        for row in ordered.itertuples():
            require(_utc(row.source_available_at_utc, "OT availability") == _utc(game.source_available_at_utc, "final availability"),
                    "Overtime period and final revision clocks differ")
            require(row.source_object_sha256 == game.source_object_sha256,
                    "Overtime period and final revision source bytes differ")

    predicted = bound_model.predict(features)[0]
    seed = game_seed(str(target["game_id"]), str(bindings["modelConfigurationIdentity"]), master_seed)
    simulated = simulate(float(predicted[0]), float(predicted[1]),
                         residuals[["residual_home", "residual_away"]].to_numpy(float), seed=seed, draws=draws,
                         overtime_evidence=overtime[["home_points", "away_points"]].to_numpy(float))
    summary = summarize(simulated["home_runs"], simulated["away_runs"])
    paired = np.column_stack((simulated["home_runs"], simulated["away_runs"])).astype("<i8", copy=False)
    paired_sha = hashlib.sha256(paired.tobytes(order="C")).hexdigest()
    numeric_features = features[list(feature_contract()["numericFeatures"])].iloc[0]
    feature_values = {key: float(value) if pd.notna(value) else None for key, value in numeric_features.items()}
    feature_sha = hashlib.sha256(json.dumps(feature_values, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    audit.update({"forecastSourceCutoffUtc": cutoff.isoformat(), "featureEvaluationTipoffUtc": tipoff.isoformat(),
                  "targetHistoryRowsExcluded": target_history_rows, "featureVectorSha256": feature_sha,
                  "eligibleResidualGames": len(residuals), "eligibleOvertimePeriods": len(overtime)})
    # Record actual completion, then recheck eligibility so slow execution cannot
    # turn a started game's newly generated population into a prospective object.
    completed = pd.Timestamp(datetime.now(timezone.utc))
    require(completed < tipoff, "Simulation completed after original tipoff; no prospective forecast may be published")
    forecast = {
        "schemaVersion": SCHEMA, "engine": ENGINE, "version": VERSION,
        "game": target, "scope": "NBA_REGULAR_SEASON_FULL_GAME_INCLUDING_OVERTIME",
        "sourceCutoffUtc": cutoff.isoformat(), "executionStartedAtUtc": now.isoformat(),
        "createdAtUtc": completed.isoformat(), "publishedAtUtc": None,
        "modelConfigurationIdentity": bindings["modelConfigurationIdentity"],
        "modelFamily": bound_model.family, "modelTrainingIdentitySha256": bound_model.training_identity_sha256,
        "bindings": bindings, "featureVector": feature_values, "featureVectorSha256": feature_sha,
        "pointModelExpectedHomeScore": float(predicted[0]), "pointModelExpectedAwayScore": float(predicted[1]),
        "pointModelExpectedTotal": float(predicted.sum()), "pointModelExpectedHomeMargin": float(predicted[0] - predicted[1]),
        **summary, "simulation": simulated["diagnostics"],
        "population": {"drawCount": draws, "pairedColumns": ["HOME", "AWAY"],
                       "logicalEncoding": "C-order little-endian signed int64 [draw,home/away]",
                       "logicalPairedScoresSha256": paired_sha, "physicalArtifact": None},
        "missingInputs": ["injuries", "projected_starters", "lineups", "player_strength", "travel", "referees", "market_prices"],
        "fallbackDisposition": "NONE_SUPPORTED_TEAM_HISTORY_AND_EMPIRICAL_RESIDUAL_EXECUTION",
        "publicationDisposition": "BUILT_LOCALLY_NOT_PUBLISHED", **RESEARCH_FLAGS,
    }
    identity = {key: forecast[key] for key in ("game", "modelConfigurationIdentity", "modelTrainingIdentitySha256",
                                               "sourceCutoffUtc", "createdAtUtc", "featureVectorSha256")}
    identity.update(drawCount=draws, logicalPairedScoresSha256=paired_sha)
    forecast["forecastId"] = "nba-gen1-shadow-" + hashlib.sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"forecast": forecast, "population": simulated, "featureAudit": audit}
