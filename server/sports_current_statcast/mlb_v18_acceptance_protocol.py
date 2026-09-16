"""Predeclared prospective acceptance evaluator for the MLB V18 shadow challenger.

Pure evaluation code: no providers, model fitting, Final OOT access, persistence service,
or AISP coupling.  Inputs are immutable forecast/settlement record exports.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from server.sports_datasets.consumer import canonical_json_bytes


SCHEMA_VERSION = "MLB_V18_PROSPECTIVE_ACCEPTANCE_INPUT_V1"
OUTPUT_SCHEMA_VERSION = "MLB_V18_PROSPECTIVE_ACCEPTANCE_RESULT_V1"
CONTRACT_SCHEMA_VERSION = "MLB_V18_PROSPECTIVE_ACCEPTANCE_PROTOCOL_V1"
BUNDLE_SHA256 = "a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27"
BUNDLE_ID = "mlb-v18-whole-game-a6e7e99122f1b60701a4728b"
TREATMENT_SPECIFICATION_ID = "stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638"
TREATMENT_MANIFEST_SHA256 = "4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3"
BOOTSTRAP_SEED = 20260907

PROTOCOL: dict[str, Any] = {
    "schemaVersion": CONTRACT_SCHEMA_VERSION,
    "verdict": "V18_PROSPECTIVE_ACCEPTANCE_PROTOCOL_PREDECLARED_AND_EXECUTABLE",
    "referencedBundle": {"bundleId": BUNDLE_ID, "bundleSha256": BUNDLE_SHA256},
    "scope": "PROSPECTIVE_RESEARCH_SHADOW_ONLY",
    "stages": {
        "A": "OPERATIONAL_RESEARCH_SHADOW_ACCEPTANCE",
        "B": "PRELIMINARY_SCIENTIFIC_MONITORING_NO_SUPERIORITY_CLAIMS",
        "C": "EXACTLY_PAIRED_V18_VERSUS_GEN1_COMPARISON",
        "D": "MARKET_RELATIVE_MONITORING_SEPARATE_FROM_MODEL_COMPARISON",
        "E": "PREREQUISITES_FOR_SEPARATE_BET_READINESS_STUDY",
    },
    "checkpoints": [
        {"pairedGames": 20, "purpose": "OPERATIONAL_ONLY"},
        {"pairedGames": 50, "purpose": "EARLY_DESCRIPTIVE_ONLY"},
        {"pairedGames": 100, "purpose": "PRELIMINARY_SCIENTIFIC_WITH_CI_NO_ADVANCEMENT"},
        {"pairedGames": 250, "purpose": "FIRST_FORMAL_ADVANCEMENT_DECISION"},
        {"pairedGames": 500, "purpose": "CONTINUED_CONFIRMATION_IF_AVAILABLE"},
    ],
    "primaryEndpoint": {
        "name": "PAIRED_HOME_WIN_LOG_LOSS_DIFFERENCE",
        "orientation": "V18_MINUS_GEN1_NEGATIVE_IS_BETTER",
        "confidenceInterval": "DETERMINISTIC_CHRONOLOGICAL_ISO_WEEK_BLOCK_BOOTSTRAP_5000_RESAMPLES",
    },
    "secondaryEndpoints": [
        "paired Brier difference", "calibration intercept and slope", "broad-band reliability",
        "home/away/total/run-differential MAE", "discrete total-run ranked probability score",
        "one-run and extra-inning rates", "coverage", "operational reliability",
    ],
    "decisionThresholds": {
        "minimumPairedGamesForAnyComparativeClaim": 100,
        "minimumPairedGamesForAdvancement": 250,
        "noninferiorityMarginLogLoss": 0.02,
        "materialRegressionBoundaryLogLoss": 0.02,
        "acceptableForecastCoverage": 0.95,
        "maximumMissingOrFailedForecastRate": 0.05,
        "maximumStaleInputExposure": 0.05,
        "maximumIllegalStateCount": 0,
        "maximumNonterminationCount": 0,
        "minimumSimulationPaths": 5000,
        "minimumReliabilityBandRows": 30,
        "minimumSubgroupRows": 50,
        "minimumSubgroupOutcomeClassRows": 10,
        "calibrationDisplayMinimumRows": 250,
        "calibrationInterceptAbsoluteMaximum": 0.15,
        "calibrationSlopeRange": [0.70, 1.30],
        "maximumBroadBandCalibrationGap": 0.10,
        "maximumPrimaryCiHalfWidthForDecision": 0.02,
        "marketCoverageForBetReadiness": 0.80,
    },
    "freshnessHours": {
        "lineup": {"PROJECTED": 48, "CONFIRMED": 12},
        "starter": {"PROJECTED": 72, "PROBABLE": 36, "CONFIRMED": 12},
    },
    "decisionRules": {
        "superiority": "at >=250 paired games, primary CI upper bound < 0 and operational/calibration gates pass",
        "noninferiority": "at >=250 paired games, primary CI upper bound < +0.020 and superiority is not established",
        "materialRegression": "at >=100 paired games, primary CI lower bound > +0.020; the same V18-minus-Gen1 orientation is used",
        "unresolved": "failure to prove superiority or noninferiority is not equivalence; continue or retain only as diversity challenger",
        "secondaryMetrics": "diagnostic except operational coverage, calibration safety, illegal states, and termination",
    },
    "planningBasis": {
        "source": "NON_OOT_ANALYTICAL_PAIRED_DESIGN_ASSUMPTION",
        "pairedLogLossDifferenceSd": 0.14,
        "temporalDesignEffect": 1.25,
        "interpretation": "Planning-only correlated-forecast assumption; decisions use the actual paired block-bootstrap CI and never move the 0.020 margin.",
        "detectableTwoSided95AbsoluteDifference": {
            "20": 0.0686, "50": 0.0434, "100": 0.0307, "250": 0.0194, "500": 0.0137,
        },
    },
    "repeatedLooks": {
        "daily": "DESCRIPTIVE_ONLY_NO_NEW_COMPARATIVE_CLAIM",
        "formal": "Only the predeclared 100- and 250-game checkpoints may change comparative state; later confirmation occurs at 500.",
        "wideCi": "If primary CI half-width exceeds 0.020, advancement is prohibited regardless of point estimate.",
    },
    "gameDisposition": {
        "CANCELED": "EXCLUDE_FINAL",
        "VOIDED": "EXCLUDE_FINAL",
        "POSTPONED": "EXCLUDE_UNTIL_NEW_SCHEDULE_REVISION_AND_FRESH_FORECAST",
        "DUPLICATE": "EXCLUDE_ALL_DUPLICATE_IDENTITIES_FAIL_CLOSED",
    },
    "monteCarlo": {
        "publishedPaths": 5000,
        "persist": ["simulationCount", "monteCarloStandardError", "monteCarlo95HalfWidth", "seedPolicy", "pathDigest"],
        "display": "probability with Monte Carlo SE and 95% sampling interval, explicitly excluding model uncertainty",
        "nearHalf": {"standardError": 0.007071, "approximate95HalfWidth": 0.013859},
        "interpretability": "Differences smaller than the larger forecast's 95% Monte Carlo half-width are simulation-indistinguishable.",
        "commonRandomNumbers": "Allowed only when both scenarios persist the same seed lineage and transition draws; otherwise unavailable.",
        "laterQualification": "Reassess paths or variance reduction only after runtime and observed MC contribution are measured; no requirement is changed here.",
    },
    "betReadinessPrerequisites": [
        ">=250 paired settled games", ">=95% operational forecast coverage", "calibration gates pass",
        ">=80% fresh timestamped sportsbook market coverage", "paired uncertainty estimates exist",
        "settlements are immutable", "policy-development cohort predeclared",
        "separate untouched policy-evaluation cohort predeclared", "no model superiority claim is implied",
    ],
    "regimeAtlasFields": [
        "league", "season", "gameDate", "scheduledStart", "homeTeam", "awayTeam",
        "lineupState", "starterState", "timeSinceLineupConfirmationHours", "coldStartPlayerCount",
        "missingFeatureCount", "starterHandedness", "batterHandednessComposition", "starterQualityBand",
        "bullpenQualityBand", "bullpenWorkloadAvailability", "park", "weatherAvailability",
        "travelRestIndicators", "divisionalGame", "dayNight", "forecastLeadTimeMinutes",
        "modelDisagreement", "marketDisagreement", "marketFreshnessMinutes", "marketDispersion",
        "predictedTotalBand", "predictedWinProbabilityBand", "simulationUncertainty",
        "transitionBackoffUsage", "unsupportedCapabilityFlags",
    ],
    "regimeRules": {
        "pregameOnly": True,
        "minimumRows": 50,
        "minimumRowsPerOutcomeClass": 10,
        "multipleComparisonWarningRequired": True,
        "specialistCreationAutomatic": False,
        "modelingTargetRequiresChronologicalConfirmation": True,
    },
    "marketRules": {
        "sportsbookPhases": ["FORECAST_TIME", "DECISION_TIME", "CLOSING"],
        "maximumQuoteAgeMinutes": {"FORECAST_TIME": 30, "DECISION_TIME": 15, "CLOSING": 15},
        "missingSportsbook": "NOT_EVALUABLE",
        "kalshiPolymarket": "SEPARATE_OBSERVATIONAL_MARKETS_NOT_SPORTSBOOK_CLOSING_LINES_OR_MODEL_PREDICTIONS",
        "noVigRequired": True,
    },
    "calibrationReconciliation": {
        "earlier": {
            "value": 0.05837229443583025,
            "definition": "maximum absolute top-class confidence gap across qualifying 0.1-wide bands within each temporal fold, then maximum across folds; minimum 1,000 rows per fold-band",
            "worstCell": {"fold": 2, "band": "[0.6,0.7)", "rows": 1033},
            "artifact": "outputs/mlb-v18-pa-game-baseline/sha256/9ed04b20fb03b5399e77f7cd311db9d6aba50709fc8d368522e3b19f46de6504/calibration-decision.json",
        },
        "final": {
            "value": 0.030587306750928467,
            "definition": "maximum absolute top-class confidence gap across qualifying 0.1-wide bands after pooling all five OOF folds; minimum 1,000 rows per pooled band",
            "worstCell": {"fold": "POOLED_1_TO_5", "band": "[0.6,0.7)", "rows": 4164},
            "artifact": "outputs/mlb-v18-whole-game-challenger/sha256/a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27/calibration.json",
        },
        "resolution": "FOLDWISE_MAXIMUM_VERSUS_POOLED_AGGREGATION; SAME OOF POPULATION_FAMILY_BIN_WIDTH_AND_1000_ROW_GATE; BOTH_RETAINED",
    },
    "requiredForecastFields": [
        "forecastId", "gameId", "bundleId", "bundleSha256", "forecastAt", "evidenceCutoff",
        "inputReceipts", "lineupState", "lineupObservedAt", "starterState", "starterObservedAt",
        "treatmentSpecificationId", "treatmentManifestSha256", "rawInputCount", "treatedInputCount",
        "paProbabilitiesNormalized", "probabilityNormalizationMaxError", "simulationCount",
        "monteCarloStandardError", "monteCarlo95HalfWidth", "seedPolicy", "pathDigest",
        "nonterminationCount", "illegalStateCount", "deterministicReplayVerified", "persistenceCount",
        "homeWinProbability", "expectedHomeRuns", "expectedAwayRuns", "expectedTotalRuns",
        "expectedRunDifferential", "oneRunProbability", "extraInningProbability", "totalRunPmf",
        "wageringAuthority", "gen1HistoryMutated", "regime",
    ],
    "requiredSettlementFields": [
        "settlementId", "gameId", "status", "settledAt", "immutable", "homeRuns", "awayRuns",
        "extraInnings", "lineageSha256",
    ],
    "lineage": {"finalOotOpened": False, "newPredictiveModelFit": False, "aispModified": False},
}


class AcceptanceProtocolError(ValueError):
    pass


def protocol_sha256() -> str:
    return hashlib.sha256(canonical_json_bytes(PROTOCOL)).hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an offset")
    return parsed.astimezone(timezone.utc)


def _probability(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0 or result >= 1.0:
        raise ValueError("probability must be strictly between zero and one")
    return result


def validate_input(payload: Mapping[str, Any]) -> None:
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise AcceptanceProtocolError("input schemaVersion differs from the predeclared contract")
    if payload.get("protocolSha256") != protocol_sha256():
        raise AcceptanceProtocolError("input protocolSha256 differs from the predeclared contract")
    if not isinstance(payload.get("records"), list):
        raise AcceptanceProtocolError("records must be a list")
    allowed_plan = payload.get("policyStudyPlan")
    if allowed_plan is not None and not isinstance(allowed_plan, Mapping):
        raise AcceptanceProtocolError("policyStudyPlan must be an object when present")


def _forecast_reasons(record: Mapping[str, Any], duplicate_games: set[str], duplicate_forecasts: set[str]) -> list[str]:
    reasons: set[str] = set()
    game_id = str(record.get("gameId") or "")
    if not game_id:
        reasons.add("MISSING_GAME_ID")
    if game_id in duplicate_games:
        reasons.add("DUPLICATE_GAME_ID")
    status = str(record.get("gameStatus") or "")
    if status in {"CANCELED", "VOIDED"}:
        reasons.add(f"GAME_{status}")
    if status == "POSTPONED":
        reasons.add("POSTPONED_REQUIRES_NEW_SCHEDULE_REVISION_AND_FRESH_FORECAST")
    forecast = record.get("v18")
    if not isinstance(forecast, Mapping):
        reasons.add("MISSING_V18_FORECAST")
        return sorted(reasons)
    if set(PROTOCOL["requiredForecastFields"]) - set(forecast):
        reasons.add("V18_REQUIRED_FIELDS_MISSING")
    if record.get("league") != "MLB" or not isinstance(record.get("season"), int):
        reasons.add("GAME_LEAGUE_OR_SEASON_INVALID")
    if not record.get("scheduleRevisionId"):
        reasons.add("SCHEDULE_REVISION_ID_MISSING")
    forecast_id = str(forecast.get("forecastId") or "")
    if not forecast_id:
        reasons.add("MISSING_V18_FORECAST_ID")
    if forecast_id in duplicate_forecasts:
        reasons.add("DUPLICATE_V18_FORECAST_ID")
    checks = {
        "gameId": game_id,
        "bundleId": BUNDLE_ID,
        "bundleSha256": BUNDLE_SHA256,
        "treatmentSpecificationId": TREATMENT_SPECIFICATION_ID,
        "treatmentManifestSha256": TREATMENT_MANIFEST_SHA256,
    }
    for name, expected in checks.items():
        if forecast.get(name) != expected:
            reasons.add(f"V18_{name.upper()}_MISMATCH")
    try:
        start, forecast_at, cutoff = _time(record.get("scheduledStart")), _time(forecast.get("forecastAt")), _time(forecast.get("evidenceCutoff"))
        if forecast_at >= start:
            reasons.add("V18_FORECAST_NOT_PREGAME")
        if cutoff > forecast_at:
            reasons.add("V18_EVIDENCE_CUTOFF_AFTER_FORECAST")
        receipts = forecast.get("inputReceipts") or []
        if not receipts:
            reasons.add("V18_INPUT_RECEIPTS_MISSING")
        for receipt in receipts:
            if not isinstance(receipt, Mapping) or not receipt.get("source") or not receipt.get("lineageSha256"):
                reasons.add("V18_INPUT_RECEIPT_INCOMPLETE")
                continue
            observed, received = _time(receipt.get("observedAt")), _time(receipt.get("receivedAt"))
            if observed > received or received > forecast_at:
                reasons.add("V18_INPUT_RECEIPT_TIME_INVALID")
        lineup_state = str(forecast.get("lineupState") or "")
        starter_state = str(forecast.get("starterState") or "")
        lineup_limit = PROTOCOL["freshnessHours"]["lineup"].get(lineup_state)
        starter_limit = PROTOCOL["freshnessHours"]["starter"].get(starter_state)
        if lineup_limit is None:
            reasons.add("V18_LINEUP_STATE_INVALID")
        elif (forecast_at - _time(forecast.get("lineupObservedAt"))).total_seconds() / 3600 > lineup_limit:
            reasons.add("V18_LINEUP_INPUT_STALE")
        if starter_limit is None:
            reasons.add("V18_STARTER_STATE_INVALID")
        elif (forecast_at - _time(forecast.get("starterObservedAt"))).total_seconds() / 3600 > starter_limit:
            reasons.add("V18_STARTER_INPUT_STALE")
    except (TypeError, ValueError):
        reasons.add("V18_TIMESTAMP_CONTRACT_INVALID")
    numeric_checks = {
        "rawInputCount": 246, "treatedInputCount": 273, "persistenceCount": 1,
        "illegalStateCount": 0, "nonterminationCount": 0,
    }
    for name, expected in numeric_checks.items():
        if forecast.get(name) != expected:
            reasons.add(f"V18_{name.upper()}_INVALID")
    if int(forecast.get("simulationCount") or 0) < 5000:
        reasons.add("V18_SIMULATION_PATH_COUNT_INADEQUATE")
    normalization_error = forecast.get("probabilityNormalizationMaxError")
    try:
        normalization_invalid = normalization_error is None or float(normalization_error) > 1e-8
    except (TypeError, ValueError):
        normalization_invalid = True
    if not forecast.get("paProbabilitiesNormalized") or normalization_invalid:
        reasons.add("V18_PA_PROBABILITIES_NOT_NORMALIZED")
    if not forecast.get("deterministicReplayVerified"):
        reasons.add("V18_DETERMINISTIC_REPLAY_FAILED")
    if forecast.get("wageringAuthority") is not False:
        reasons.add("V18_WAGERING_AUTHORITY_FORBIDDEN")
    if forecast.get("gen1HistoryMutated") is not False:
        reasons.add("V18_GEN1_HISTORY_MUTATION_FORBIDDEN")
    for name in ("seedPolicy", "pathDigest"):
        if not forecast.get(name):
            reasons.add(f"V18_{name.upper()}_MISSING")
    regime = forecast.get("regime")
    if not isinstance(regime, Mapping):
        reasons.add("V18_REGIME_METADATA_MISSING")
    elif set(PROTOCOL["regimeAtlasFields"]) - set(regime):
        reasons.add("V18_REGIME_METADATA_INCOMPLETE")
    for name in (
        "expectedHomeRuns", "expectedAwayRuns", "expectedTotalRuns", "expectedRunDifferential",
        "oneRunProbability", "extraInningProbability", "monteCarloStandardError", "monteCarlo95HalfWidth",
    ):
        try:
            if not math.isfinite(float(forecast.get(name))):
                raise ValueError
        except (TypeError, ValueError):
            reasons.add(f"V18_{name.upper()}_INVALID")
    for name in ("oneRunProbability", "extraInningProbability"):
        try:
            if not 0 <= float(forecast.get(name)) <= 1:
                reasons.add(f"V18_{name.upper()}_INVALID")
        except (TypeError, ValueError):
            pass
    try:
        p = _probability(forecast.get("homeWinProbability"))
        paths = int(forecast.get("simulationCount"))
        expected_se = math.sqrt(p * (1.0 - p) / paths)
        reported_se = float(forecast.get("monteCarloStandardError"))
        reported_half = float(forecast.get("monteCarlo95HalfWidth"))
        if abs(reported_se - expected_se) > 1e-6 or abs(reported_half - 1.96 * reported_se) > 1e-6:
            reasons.add("V18_MONTE_CARLO_UNCERTAINTY_INCONSISTENT")
    except (TypeError, ValueError):
        reasons.add("V18_HOME_WIN_PROBABILITY_INVALID")
    return sorted(reasons)


def _pair_reasons(record: Mapping[str, Any], forecast_reasons: Sequence[str]) -> list[str]:
    reasons = set(forecast_reasons)
    game_id = str(record.get("gameId") or "")
    try:
        start = _time(record.get("scheduledStart"))
    except (TypeError, ValueError):
        start = None
        reasons.add("SCHEDULE_TIMESTAMP_INVALID")
    gen1 = record.get("gen1")
    if not isinstance(gen1, Mapping):
        reasons.add("MISSING_GEN1_FORECAST")
    else:
        if gen1.get("gameId") != game_id:
            reasons.add("GEN1_GAME_ID_MISMATCH")
        try:
            if start is None or _time(gen1.get("forecastAt")) >= start:
                reasons.add("GEN1_FORECAST_NOT_PREGAME")
            _probability(gen1.get("homeWinProbability"))
        except (TypeError, ValueError):
            reasons.add("GEN1_FORECAST_CONTRACT_INVALID")
        if gen1.get("reconstructedAfterEvent") is not False:
            reasons.add("GEN1_RECONSTRUCTED_AFTER_EVENT")
        if not gen1.get("forecastId") or int(gen1.get("persistenceCount") or 0) != 1:
            reasons.add("GEN1_IDENTITY_OR_PERSISTENCE_INVALID")
    settlement = record.get("settlement")
    if not isinstance(settlement, Mapping):
        reasons.add("MISSING_FINAL_SETTLEMENT")
    else:
        if settlement.get("gameId") != game_id:
            reasons.add("SETTLEMENT_GAME_ID_MISMATCH")
        if settlement.get("status") != "FINAL" or settlement.get("immutable") is not True:
            reasons.add("SETTLEMENT_NOT_FINAL_IMMUTABLE")
        if not settlement.get("settlementId") or not settlement.get("lineageSha256"):
            reasons.add("SETTLEMENT_LINEAGE_INCOMPLETE")
        for name in ("homeRuns", "awayRuns"):
            if not isinstance(settlement.get(name), int) or settlement[name] < 0:
                reasons.add("SETTLEMENT_SCORE_INVALID")
        try:
            if start is None or _time(settlement.get("settledAt")) <= start:
                reasons.add("SETTLEMENT_TIMESTAMP_INVALID")
        except (TypeError, ValueError):
            reasons.add("SETTLEMENT_TIMESTAMP_INVALID")
    return sorted(reasons)


def _loss(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = np.clip(p.astype(float), 1e-12, 1 - 1e-12)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _brier(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.square(p.astype(float) - y.astype(float))


def chronological_block_ci(values: Sequence[float], dates: Sequence[str], *, resamples: int = 5000) -> dict[str, Any]:
    array = np.asarray(values, dtype=float)
    if len(array) == 0:
        return {"status": "NOT_ESTIMABLE", "lower": None, "upper": None, "mean": None, "resamples": 0}
    groups: dict[str, list[int]] = defaultdict(list)
    for index, value in enumerate(dates):
        stamp = _time(value)
        year, week, _ = stamp.isocalendar()
        groups[f"{year}-W{week:02d}"].append(index)
    blocks = [np.asarray(groups[key], dtype=int) for key in sorted(groups)]
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    samples = np.empty(resamples, dtype=float)
    for iteration in range(resamples):
        selected = rng.integers(0, len(blocks), size=len(blocks))
        indices = np.concatenate([blocks[number] for number in selected])
        samples[iteration] = float(array[indices].mean())
    return {
        "status": "ESTIMATED", "method": "CHRONOLOGICAL_ISO_WEEK_BLOCK_BOOTSTRAP",
        "blocks": len(blocks), "resamples": resamples, "seed": BOOTSTRAP_SEED,
        "mean": float(array.mean()), "lower": float(np.quantile(samples, 0.025)),
        "upper": float(np.quantile(samples, 0.975)),
    }


def _calibration(p: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    if len(y) < 250 or min(int(y.sum()), int(len(y) - y.sum())) < 30:
        return {"status": "INSUFFICIENT_EVIDENCE", "minimumRows": 250, "rows": len(y)}
    x = np.column_stack((np.ones(len(p)), np.log(np.clip(p, 1e-9, 1-1e-9) / np.clip(1-p, 1e-9, 1))))
    beta = np.array([0.0, 1.0])
    for _ in range(50):
        mu = 1.0 / (1.0 + np.exp(-np.clip(x @ beta, -30, 30)))
        weights = np.clip(mu * (1 - mu), 1e-9, None)
        information = x.T @ (weights[:, None] * x)
        step = np.linalg.solve(information + np.eye(2) * 1e-9, x.T @ (y - mu))
        beta += step
        if float(np.max(np.abs(step))) < 1e-10:
            break
    covariance = np.linalg.inv(information + np.eye(2) * 1e-9)
    se = np.sqrt(np.diag(covariance))
    bands = []
    boundaries = ((0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 1.0))
    for lower, upper in boundaries:
        mask = (p >= lower) & (p < upper if upper < 1 else p <= upper)
        count = int(mask.sum())
        bands.append({
            "lower": lower, "upper": upper, "rows": count,
            "meanPredicted": float(p[mask].mean()) if count else None,
            "observed": float(y[mask].mean()) if count else None,
            "absoluteGap": abs(float(p[mask].mean() - y[mask].mean())) if count else None,
            "eligible": count >= 30,
        })
    maximum_gap = max((row["absoluteGap"] for row in bands if row["eligible"]), default=None)
    return {
        "status": "ESTIMATED", "rows": len(y),
        "intercept": float(beta[0]), "interceptCi95": [float(beta[0]-1.96*se[0]), float(beta[0]+1.96*se[0])],
        "slope": float(beta[1]), "slopeCi95": [float(beta[1]-1.96*se[1]), float(beta[1]+1.96*se[1])],
        "broadBands": bands, "maximumEligibleBandGap": maximum_gap,
    }


def _rps(pmf: Any, actual: int) -> float | None:
    if not isinstance(pmf, list) or not pmf:
        return None
    try:
        rows = sorted((int(row["runs"]), float(row["probability"])) for row in pmf)
    except (KeyError, TypeError, ValueError):
        return None
    if rows[0][0] != 0 or any(rows[index][0] != index for index in range(len(rows))) or abs(sum(x[1] for x in rows)-1) > 1e-6:
        return None
    cumulative = np.cumsum([row[1] for row in rows])
    observed = np.asarray([1.0 if actual <= row[0] else 0.0 for row in rows])
    return float(np.square(cumulative - observed).sum())


def _market_summary(paired: Sequence[Mapping[str, Any]], y: np.ndarray, v18_p: np.ndarray) -> dict[str, Any]:
    quote_groups: dict[tuple[int, str], list[tuple[float, float, float]]] = defaultdict(list)
    observational = Counter()
    for index, record in enumerate(paired):
        forecast_at = _time(record["v18"]["forecastAt"])
        for quote in record.get("markets") or []:
            kind = str(quote.get("marketType") or "")
            if kind in {"KALSHI", "POLYMARKET"}:
                observational[kind] += 1
                continue
            if kind != "SPORTSBOOK":
                continue
            try:
                probability = _probability(quote.get("noVigHomeProbability"))
                observed = _time(quote.get("observedAt"))
                start = _time(record.get("scheduledStart"))
                float(quote["homePrice"]); float(quote["awayPrice"])
            except (KeyError, TypeError, ValueError):
                continue
            phase = str(quote.get("phase") or "")
            if observed >= start or phase not in {"FORECAST_TIME", "DECISION_TIME", "CLOSING"}:
                continue
            if phase == "FORECAST_TIME":
                reference = forecast_at
            elif phase == "DECISION_TIME":
                try:
                    reference = _time(quote.get("decisionAt"))
                except (TypeError, ValueError):
                    continue
            else:
                reference = start
            age = (reference-observed).total_seconds()/60
            maximum_age = PROTOCOL["marketRules"]["maximumQuoteAgeMinutes"][phase]
            if age < 0 or age > maximum_age:
                continue
            quote_groups[(index, phase)].append((probability, age, (start-observed).total_seconds()/60))
    if not quote_groups:
        return {"status": "NOT_EVALUABLE", "reason": "NO_LEGITIMATE_TIMESTAMPED_SPORTSBOOK_OBSERVATIONS", "observationalMarkets": dict(observational)}
    phases = {}
    for phase in ("FORECAST_TIME", "DECISION_TIME", "CLOSING"):
        rows = []
        for (index, group_phase), quotes in sorted(quote_groups.items()):
            if group_phase != phase:
                continue
            probabilities = np.asarray([quote[0] for quote in quotes])
            rows.append((index, float(np.median(probabilities)), float(np.mean([quote[1] for quote in quotes])),
                         float(np.mean([quote[2] for quote in quotes])), float(probabilities.max()-probabilities.min())))
        if not rows:
            phases[phase] = {"status": "NOT_EVALUABLE"}
            continue
        indices = np.asarray([row[0] for row in rows], dtype=int)
        market_p = np.asarray([row[1] for row in rows])
        phases[phase] = {
            "status": "EVALUATED", "games": len(rows), "coverage": len(rows)/len(paired),
            "meanV18MinusMarketProbability": float((v18_p[indices]-market_p).mean()),
            "v18LogLoss": float(_loss(v18_p[indices], y[indices]).mean()),
            "marketLogLoss": float(_loss(market_p, y[indices]).mean()),
            "marketBrier": float(_brier(market_p, y[indices]).mean()),
            "marketCalibrationGap": float(market_p.mean()-y[indices].mean()),
            "meanQuoteAgeMinutes": float(np.mean([row[2] for row in rows])),
            "meanQuoteLeadMinutes": float(np.mean([row[3] for row in rows])),
            "meanSportsbookDispersion": float(np.mean([row[4] for row in rows])),
        }
    clv = []
    for index in range(len(paired)):
        decision = quote_groups.get((index, "DECISION_TIME"))
        closing = quote_groups.get((index, "CLOSING"))
        if not decision or not closing:
            continue
        decision_home = float(np.median([row[0] for row in decision]))
        closing_home = float(np.median([row[0] for row in closing]))
        home_side = v18_p[index] >= 0.5
        clv.append((closing_home-decision_home) if home_side else ((1-closing_home)-(1-decision_home)))
    closing_line = {
        "status": "EVALUATED", "games": len(clv), "meanProbabilityMovementTowardV18Lean": float(np.mean(clv)),
        "meaning": "OBSERVATIONAL_ONLY_NOT_WAGER_RETURN",
    } if clv else {"status": "NOT_EVALUABLE", "reason": "MATCHED_FRESH_DECISION_AND_CLOSING_QUOTES_UNAVAILABLE"}
    return {"status": "EVALUATED", "phases": phases, "observationalMarkets": dict(observational),
            "closingLineValue": closing_line}


def _checkpoint(count: int) -> dict[str, Any]:
    reached = [row for row in PROTOCOL["checkpoints"] if count >= row["pairedGames"]]
    upcoming = next((row for row in PROTOCOL["checkpoints"] if count < row["pairedGames"]), None)
    return {"latestReached": reached[-1] if reached else None, "next": upcoming}


def _subgroup_summary(paired: Sequence[Mapping[str, Any]], y: np.ndarray) -> dict[str, Any]:
    fields = (
        "lineupState", "starterState", "starterHandedness", "starterQualityBand",
        "bullpenQualityBand", "bullpenWorkloadAvailability", "park", "weatherAvailability",
        "divisionalGame", "dayNight", "predictedTotalBand", "predictedWinProbabilityBand",
        "transitionBackoffUsage",
    )
    rows = []
    for field in fields:
        groups: dict[str, list[int]] = defaultdict(list)
        for index, record in enumerate(paired):
            value = (record["v18"].get("regime") or {}).get(field)
            if value is not None:
                groups[str(value)].append(index)
        for value, indices in sorted(groups.items()):
            outcomes = y[indices]
            eligible = len(indices) >= 50 and min(int(outcomes.sum()), int(len(indices)-outcomes.sum())) >= 10
            row = {"field": field, "value": value, "rows": len(indices), "eligible": eligible}
            if eligible:
                p = np.asarray([paired[index]["v18"]["homeWinProbability"] for index in indices], dtype=float)
                row.update({"homeWinLogLoss": float(_loss(p, outcomes).mean()), "homeWinBrier": float(_brier(p, outcomes).mean())})
            else:
                row["reason"] = "MINIMUM_50_ROWS_AND_10_PER_OUTCOME_CLASS_NOT_MET"
            rows.append(row)
    return {
        "status": "ELIGIBLE_FOR_DESCRIPTIVE_REPORTING" if any(row["eligible"] for row in rows) else "INSUFFICIENT_EVIDENCE",
        "minimumRows": 50, "minimumPerOutcomeClass": 10, "segments": rows,
        "multipleComparisonWarning": "Exploratory segments do not change the primary decision and require chronological confirmation before modeling action.",
    }


def evaluate(payload: Mapping[str, Any]) -> dict[str, Any]:
    validate_input(payload)
    records = list(payload["records"])
    game_counts = Counter(str(row.get("gameId") or "") for row in records)
    forecast_counts = Counter(str((row.get("v18") or {}).get("forecastId") or "") for row in records if isinstance(row.get("v18"), Mapping))
    duplicate_games = {key for key, count in game_counts.items() if key and count > 1}
    duplicate_forecasts = {key for key, count in forecast_counts.items() if key and count > 1}
    exclusions, paired = [], []
    operational_valid = 0
    operational_valid_records: list[Mapping[str, Any]] = []
    stale_attempts = 0
    eligible_for_forecast = 0
    critical = 0
    critical_tokens = ("CHECKSUM", "BUNDLE", "ILLEGAL", "NONTERMINATION", "WAGERING", "MUTATION", "DUPLICATE")
    for record in records:
        if record.get("gameStatus") not in {"CANCELED", "VOIDED", "POSTPONED"}:
            eligible_for_forecast += 1
        forecast_reasons = _forecast_reasons(record, duplicate_games, duplicate_forecasts)
        if any("STALE" in reason for reason in forecast_reasons):
            stale_attempts += 1
        if any(token in reason for reason in forecast_reasons for token in critical_tokens):
            critical += 1
        if not forecast_reasons:
            operational_valid += 1
            operational_valid_records.append(record)
        pair_reasons = _pair_reasons(record, forecast_reasons)
        exclusion = {
            "gameId": record.get("gameId"), "recordSha256": _digest(record),
            "forecastReasons": forecast_reasons, "pairReasons": pair_reasons,
            "operationalIncluded": not forecast_reasons, "pairedIncluded": not pair_reasons,
        }
        exclusions.append(exclusion)
        if not pair_reasons:
            paired.append(record)
    exclusions.sort(key=lambda row: (str(row["gameId"]), row["recordSha256"]))
    paired.sort(key=lambda row: (_time(row["scheduledStart"]), str(row["gameId"])))
    coverage = operational_valid / eligible_for_forecast if eligible_for_forecast else 0.0
    failure_rate = 1.0 - coverage if eligible_for_forecast else 0.0
    attempts = sum(isinstance(row.get("v18"), Mapping) for row in records)
    stale_rate = stale_attempts / attempts if attempts else 0.0
    lineup_states = Counter(str(row["v18"]["lineupState"]) for row in operational_valid_records)
    starter_states = Counter(str(row["v18"]["starterState"]) for row in operational_valid_records)
    monte_carlo_standard_errors = [float(row["v18"]["monteCarloStandardError"]) for row in operational_valid_records]
    monte_carlo_half_widths = [float(row["v18"]["monteCarlo95HalfWidth"]) for row in operational_valid_records]
    simulation_counts = [int(row["v18"]["simulationCount"]) for row in operational_valid_records]
    metrics: dict[str, Any] = {"status": "INSUFFICIENT_EVIDENCE", "pairedGames": len(paired)}
    market = {"status": "NOT_EVALUABLE", "reason": "NO_PAIRED_SETTLED_GAMES"}
    calibration: dict[str, Any] = {"status": "INSUFFICIENT_EVIDENCE", "rows": len(paired), "minimumRows": 250}
    subgroup_summary = _subgroup_summary([], np.asarray([], dtype=float))
    primary_ci = chronological_block_ci([], [])
    calibration_failure = False
    if paired:
        y = np.asarray([int(row["settlement"]["homeRuns"] > row["settlement"]["awayRuns"]) for row in paired], dtype=float)
        v18_p = np.asarray([float(row["v18"]["homeWinProbability"]) for row in paired])
        gen1_p = np.asarray([float(row["gen1"]["homeWinProbability"]) for row in paired])
        v18_loss, gen1_loss = _loss(v18_p, y), _loss(gen1_p, y)
        loss_delta = v18_loss - gen1_loss
        brier_delta = _brier(v18_p, y) - _brier(gen1_p, y)
        dates = [row["scheduledStart"] for row in paired]
        primary_ci = chronological_block_ci(loss_delta, dates)
        calibration = _calibration(v18_p, y)
        if calibration.get("status") == "ESTIMATED":
            slope_low, slope_high = PROTOCOL["decisionThresholds"]["calibrationSlopeRange"]
            calibration_failure = bool(
                abs(calibration["intercept"]) > PROTOCOL["decisionThresholds"]["calibrationInterceptAbsoluteMaximum"]
                or not slope_low <= calibration["slope"] <= slope_high
                or (calibration["maximumEligibleBandGap"] or 0) > PROTOCOL["decisionThresholds"]["maximumBroadBandCalibrationGap"]
            )
        run_fields = (
            ("homeRuns", "expectedHomeRuns"), ("awayRuns", "expectedAwayRuns"),
        )
        run_metrics = {}
        for actual_name, expected_name in run_fields:
            run_metrics[f"{actual_name}Mae"] = float(np.mean([
                abs(float(row["v18"][expected_name]) - int(row["settlement"][actual_name])) for row in paired
            ]))
        gen1_run_fields = ("expectedHomeRuns", "expectedAwayRuns", "expectedTotalRuns", "expectedRunDifferential")
        gen1_runs_comparable = all(all(name in row["gen1"] for name in gen1_run_fields) for row in paired)
        actual_total = np.asarray([row["settlement"]["homeRuns"] + row["settlement"]["awayRuns"] for row in paired])
        actual_diff = np.asarray([row["settlement"]["homeRuns"] - row["settlement"]["awayRuns"] for row in paired])
        total_rps = [_rps(row["v18"].get("totalRunPmf"), int(total)) for row, total in zip(paired, actual_total)]
        usable_rps = [value for value in total_rps if value is not None]
        metrics = {
            "status": "EVALUATED", "pairedGames": len(paired),
            "primary": {
                "orientation": "V18_MINUS_GEN1_NEGATIVE_IS_BETTER",
                "v18LogLoss": float(v18_loss.mean()), "gen1LogLoss": float(gen1_loss.mean()),
                "difference": float(loss_delta.mean()), "confidenceInterval": primary_ci,
            },
            "secondary": {
                "v18Brier": float(_brier(v18_p, y).mean()), "gen1Brier": float(_brier(gen1_p, y).mean()),
                "pairedBrierDifference": float(brier_delta.mean()),
                **run_metrics,
                "totalRunsMae": float(np.mean(np.abs(np.asarray([row["v18"]["expectedTotalRuns"] for row in paired])-actual_total))),
                "runDifferentialMae": float(np.mean(np.abs(np.asarray([row["v18"]["expectedRunDifferential"] for row in paired])-actual_diff))),
                "totalRunRankedProbabilityScore": float(np.mean(usable_rps)) if usable_rps else None,
                "distributionalScoreStatus": "EVALUATED" if usable_rps else "NOT_EVALUABLE",
                "meanPredictedHomeWinRate": float(v18_p.mean()), "observedHomeWinRate": float(y.mean()),
                "meanPredictedOneRunRate": float(np.mean([row["v18"]["oneRunProbability"] for row in paired])),
                "observedOneRunRate": float(np.mean(np.abs(actual_diff) == 1)),
                "meanPredictedExtraInningRate": float(np.mean([row["v18"]["extraInningProbability"] for row in paired])),
                "observedExtraInningRate": float(np.mean([bool(row["settlement"]["extraInnings"]) for row in paired])),
                "gen1RunMetricsStatus": "EVALUATED" if gen1_runs_comparable else "NOT_EVALUABLE_FORECAST_CONTRACT_NOT_COMPARABLE",
            },
            "calibration": calibration,
        }
        if gen1_runs_comparable:
            metrics["secondary"].update({
                "gen1HomeRunsMae": float(np.mean([abs(float(row["gen1"]["expectedHomeRuns"])-row["settlement"]["homeRuns"]) for row in paired])),
                "gen1AwayRunsMae": float(np.mean([abs(float(row["gen1"]["expectedAwayRuns"])-row["settlement"]["awayRuns"]) for row in paired])),
                "gen1TotalRunsMae": float(np.mean(np.abs(np.asarray([row["gen1"]["expectedTotalRuns"] for row in paired])-actual_total))),
                "gen1RunDifferentialMae": float(np.mean(np.abs(np.asarray([row["gen1"]["expectedRunDifferential"] for row in paired])-actual_diff))),
            })
        market = _market_summary(paired, y, v18_p)
        subgroup_summary = _subgroup_summary(paired, y)
    count = len(paired)
    ci_lower, ci_upper = primary_ci.get("lower"), primary_ci.get("upper")
    ci_half = None if ci_lower is None else (ci_upper-ci_lower)/2
    thresholds = PROTOCOL["decisionThresholds"]
    operational_failure = bool(
        critical > 0
        or (eligible_for_forecast >= 20 and coverage < thresholds["acceptableForecastCoverage"])
        or (eligible_for_forecast >= 20 and failure_rate > thresholds["maximumMissingOrFailedForecastRate"])
        or (attempts >= 20 and stale_rate > thresholds["maximumStaleInputExposure"])
    )
    if not records:
        scientific_state = "NOT_STARTED"
    elif operational_failure:
        scientific_state = "OPERATIONAL_FAILURE"
    elif count < 20:
        scientific_state = "INSUFFICIENT_EVIDENCE"
    elif count < 100:
        scientific_state = "CONTINUE_RESEARCH_SHADOW"
    elif ci_lower is not None and ci_lower > thresholds["materialRegressionBoundaryLogLoss"]:
        scientific_state = "MATERIAL_REGRESSION"
    elif count < 250:
        scientific_state = "CONTINUE_RESEARCH_SHADOW"
    elif calibration_failure:
        scientific_state = "MATERIAL_REGRESSION"
    elif ci_half is None or ci_half > thresholds["maximumPrimaryCiHalfWidthForDecision"]:
        scientific_state = "RETAIN_AS_DIVERSITY_CHALLENGER"
    elif ci_upper < 0:
        scientific_state = "ADVANCE_AS_SUPERIOR"
    elif ci_upper < thresholds["noninferiorityMarginLogLoss"]:
        scientific_state = "ADVANCE_AS_NONINFERIOR"
    else:
        scientific_state = "RETAIN_AS_DIVERSITY_CHALLENGER"
    plan = payload.get("policyStudyPlan") or {}
    closing = (market.get("phases") or {}).get("CLOSING") or {}
    bet_ready = bool(
        scientific_state in {"ADVANCE_AS_SUPERIOR", "ADVANCE_AS_NONINFERIOR", "RETAIN_AS_DIVERSITY_CHALLENGER"}
        and count >= 250 and not calibration_failure and coverage >= 0.95
        and closing.get("coverage", 0) >= 0.80
        and plan.get("immutable") is True and plan.get("developmentCohortId") and plan.get("evaluationCohortId")
        and plan.get("developmentCohortId") != plan.get("evaluationCohortId")
    )
    evidence_state = "ELIGIBLE_FOR_BET_READINESS_STUDY" if bet_ready else scientific_state
    result = {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "protocolSha256": protocol_sha256(), "inputSha256": _digest(payload),
        "evidenceState": evidence_state, "scientificState": scientific_state,
        "checkpoint": _checkpoint(count),
        "operational": {
            "eligibleGames": eligible_for_forecast, "validForecasts": operational_valid,
            "coverage": coverage, "missingOrFailedRate": failure_rate, "staleInputExposure": stale_rate,
            "participantStateCoverage": {
                "lineupStateCounts": dict(sorted(lineup_states.items())),
                "lineupConfirmationCoverage": lineup_states.get("CONFIRMED", 0) / operational_valid if operational_valid else 0.0,
                "starterStateCounts": dict(sorted(starter_states.items())),
                "starterConfirmationCoverage": starter_states.get("CONFIRMED", 0) / operational_valid if operational_valid else 0.0,
            },
            "monteCarloUncertainty": {
                "status": "EVALUATED" if simulation_counts else "NOT_EVALUABLE",
                "minimumSimulationCount": min(simulation_counts) if simulation_counts else None,
                "maximumSimulationCount": max(simulation_counts) if simulation_counts else None,
                "meanStandardError": float(np.mean(monte_carlo_standard_errors)) if monte_carlo_standard_errors else None,
                "maximumStandardError": max(monte_carlo_standard_errors) if monte_carlo_standard_errors else None,
                "mean95HalfWidth": float(np.mean(monte_carlo_half_widths)) if monte_carlo_half_widths else None,
                "maximum95HalfWidth": max(monte_carlo_half_widths) if monte_carlo_half_widths else None,
                "samplingUncertaintyOnly": True,
            },
            "criticalFailures": critical, "accepted": not operational_failure and operational_valid >= 20,
        },
        "metrics": metrics, "market": market,
        "decision": {
            "calibrationFailure": calibration_failure,
            "primaryCiHalfWidth": ci_half,
            "precisionAdequate": ci_half is not None and ci_half <= thresholds["maximumPrimaryCiHalfWidthForDecision"],
            "comparativeClaimAllowed": count >= thresholds["minimumPairedGamesForAnyComparativeClaim"],
            "advancementAllowed": count >= thresholds["minimumPairedGamesForAdvancement"],
            "betReadinessPrerequisitesMet": bet_ready,
        },
        "exclusions": exclusions,
        "subgroups": subgroup_summary,
        "lineage": {"finalOotOpened": False, "newPredictiveModelFit": False, "aispModified": False},
    }
    result["resultSha256"] = _digest(result)
    return result


def human_report(result: Mapping[str, Any]) -> str:
    operational = result["operational"]
    metrics = result["metrics"]
    lines = [
        "# MLB V18 prospective acceptance evaluation", "",
        f"- Evidence state: `{result['evidenceState']}`",
        f"- Scientific state: `{result['scientificState']}`",
        f"- Paired settled games: {metrics.get('pairedGames', 0)}",
        f"- Operational coverage: {operational['coverage']:.1%}",
        f"- Missing/failed rate: {operational['missingOrFailedRate']:.1%}",
        f"- Market status: `{result['market']['status']}`", "",
    ]
    primary = metrics.get("primary")
    if primary:
        ci = primary["confidenceInterval"]
        lines.extend([
            "## Primary paired endpoint", "",
            f"V18 − Gen1 home-win log-loss difference: {primary['difference']:.6f} "
            f"(95% chronological block-bootstrap CI {ci['lower']:.6f}, {ci['upper']:.6f}).",
            "Negative values favor V18. Failure to prove superiority is not equivalence.", "",
        ])
    else:
        lines.extend(["The paired comparative endpoint is not estimable yet.", ""])
    lines.extend([
        "## Governance", "",
        "Final OOT remained sealed. No predictive model was fitted. AISP was not modified.",
        f"Protocol: `{result['protocolSha256']}`", f"Result: `{result['resultSha256']}`", "",
    ])
    return "\n".join(lines)


def write_evaluation(payload: Mapping[str, Any], output_root: Path) -> Path:
    result = evaluate(payload)
    target = output_root / "sha256" / result["resultSha256"]
    target.mkdir(parents=True, exist_ok=True)
    (target / "evaluation.json").write_bytes(canonical_json_bytes(result))
    (target / "report.md").write_text(human_report(result), encoding="utf-8", newline="\n")
    return target


__all__ = [
    "PROTOCOL", "SCHEMA_VERSION", "OUTPUT_SCHEMA_VERSION", "BUNDLE_SHA256",
    "AcceptanceProtocolError", "protocol_sha256", "validate_input", "chronological_block_ci",
    "evaluate", "human_report", "write_evaluation",
]
