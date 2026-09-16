"""Pure, bounded V19 Development diagnostics and prior-fold specialist eligibility.

No data loaders, publication side effects or forecast fits live here. Regime
membership never uses targets or realized in-game context. Outcome-based
eligibility sees only explicitly earlier OOF folds. All intervals are descriptive
Development uncertainty, not independent validation or promotion authority.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from server.sports_modeling.metrics import PA_CLASS_ORDER
from .mlb_regime_metrics import metric_contributions, paired_uncertainty


MIN_REGIME_PAS = 2000
MIN_REGIME_GAMES = 100
MIN_PRIOR_FOLDS = 2
MIN_MONTHS = 3
MIN_TEAMS = 10
MIN_EXCESS_LOG_LOSS = .01
MIN_ABSOLUTE_CLASS_BIAS = .005


def _number(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame:
        return np.full(len(frame), np.nan)
    return pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float, na_value=np.nan)


def regime_masks(frame: pd.DataFrame) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    """Return fixed, outcome-independent masks and honest source-applicability.

    Counts describe recorded exposure; annual-prior missing does not assert that
    a player has no career history. A pitcher role prior is not an announcement
    of the role actually performed during the evaluated game.
    """
    specifications = [
        ("EARLY_SEASON", ("game_day_of_season",), "game_day_of_season <= 30", lambda x: x[0] <= 30),
        ("BATTER_ANNUAL_PRIOR_MISSING", ("batter_prior_missing",), "batter_prior_missing == 1; missing annual authority, not career absence", lambda x: x[0] == 1),
        ("PITCHER_ANNUAL_PRIOR_MISSING", ("pitcher_prior_missing",), "pitcher_prior_missing == 1; missing annual authority, not career absence", lambda x: x[0] == 1),
        ("BATTER_LOW_ROLLING_EXPOSURE", ("batter_last100_pa_count",), "0 < observed prior-window PA count < 100", lambda x: (x[0] > 0) & (x[0] < 100)),
        ("PITCHER_LOW_ROLLING_EXPOSURE", ("pitcher_last250_bf_count",), "0 < observed prior-window BF count < 250", lambda x: (x[0] > 0) & (x[0] < 250)),
        ("BATTER_NO_ROLLING_OBSERVATIONS", ("batter_last100_pa_count",), "recorded prior-window PA count == 0; not a claim of no career opportunities", lambda x: x[0] == 0),
        ("PITCHER_NO_ROLLING_OBSERVATIONS", ("pitcher_last250_bf_count",), "recorded prior-window BF count == 0; not a claim of no career opportunities", lambda x: x[0] == 0),
        ("PLATOON_ADVANTAGE", ("matchup_platoon_advantage", "matchup_batter_hand_missing", "matchup_pitcher_hand_missing"), "governed platoon advantage with both handedness values known", lambda x: (x[0] == 1) & (x[1] == 0) & (x[2] == 0)),
        ("BATTING_TRAVEL_SHORT_REST", ("batting_long_travel_x_short_rest",), "batting_long_travel_x_short_rest > 0; schedule-start proxy, not actual recovery duration", lambda x: x[0] > 0),
        ("FIELDING_TRAVEL_SHORT_REST", ("fielding_long_travel_x_short_rest",), "fielding_long_travel_x_short_rest > 0; schedule-start proxy, not actual recovery duration", lambda x: x[0] > 0),
        ("DIVISIONAL_FAMILIARITY", ("batting_same_division",), "batting_same_division == 1; alignment indicator, not measured familiarity", lambda x: x[0] == 1),
        ("RELIEF_ROLE_HISTORICAL_PRIOR", ("pitcher_gs_per_g", "pitcher_prior_missing"), "annual prior GS/G < 0.5 with observed annual authority; not actual in-game role", lambda x: (x[0] < .5) & (x[1] == 0)),
    ]
    masks, registry = {}, []
    for name, fields, definition, rule in specifications:
        columns = [_number(frame, field) for field in fields]
        known = np.isfinite(np.column_stack(columns)).all(axis=1)
        mask = known & rule(columns)
        masks[name] = mask
        registry.append({"name": name, "definition": definition, "fields": list(fields),
                         "availability": "SUPPORTED_RECORDED_FIELDS" if known.any() else "UNAVAILABLE",
                         "knownRows": int(known.sum()), "unknownRows": int((~known).sum()),
                         "regimeRows": int(mask.sum()), "membershipUsesOutcomes": False,
                         "membershipUsesRealizedInGameState": False})
    unsupported = {
        "BULLPEN_FATIGUE": "No historical pregame roster-linked bullpen workload input in the accepted raw contract; a missing-workload flag is not fatigue evidence.",
        "STARTER_UNCERTAINTY": "No historical announcement/confirmation vintage in the accepted Development contract.",
        "LINEUP_CHANGES": "No timestamped historical pregame ordered-lineup vintages.",
        "HIGH_ALTITUDE": "No observed altitude input; an altitude-missing flag cannot be interpreted as altitude.",
        "WEATHER_EXTREMES": "No point-in-time weather observation/forecast vintage in the accepted Development contract.",
        "STRONG_WEAK_GAME_FAVORITES": "PA probabilities are not pregame game-win probabilities.",
        "HIGH_VARIANCE_TEAM_OFFENSE": "No predeclared, training-fitted team variance quantity in this raw contract.",
        "PREGAME_MARKET_DISAGREEMENT": "No event/side/market/timestamp-compatible pregame game probability joined to this PA cohort.",
        "ROOKIE_OR_CHANGED_ROLE": "Missing annual priors and limited recorded exposure do not identify rookie status or transactions.",
    }
    registry.extend({"name": name, "availability": "UNSUPPORTED_HISTORICAL_REGIME",
                     "reason": reason, "regimeRows": None, "membershipUsesOutcomes": False}
                    for name, reason in unsupported.items())
    return masks, registry


def _validate_frame(frame: pd.DataFrame, p: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    required = {"canonicalPaId", "canonicalGameId", "game_date", "foldNumber", "observedClassIndex"}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError("Matched Development PA identity, fold, date and target columns required")
    if frame.canonicalPaId.duplicated().any() or frame[list(required)].isna().any().any():
        raise ValueError("Missing or duplicated evaluation identities")
    if not frame.game_date.astype(str).between("2023-03-30", "2026-08-06").all():
        raise ValueError("Evaluation is restricted to the physically Development-only cache")
    if frame.groupby("canonicalGameId").foldNumber.nunique().max() != 1:
        raise ValueError("Game-atomic fold contract violated")
    y = frame.observedClassIndex.to_numpy(dtype=int)
    return y, metric_contributions(y, p)


def discover_persistent_regimes(frame: pd.DataFrame, baseline_probabilities: np.ndarray, *,
                                before_fold: int, maximum: int = 2) -> dict[str, Any]:
    """Select no more than two specialists using earlier OOF evidence only.

    The caller may pass the entire matched frame: it is filtered before targets
    or probability losses are inspected. At least two adequate earlier folds
    must show stable excess loss or the same material class-residual direction.
    """
    if maximum not in (0, 1, 2) or before_fold not in (1, 2, 3, 4, 5, 6):
        raise ValueError("At most two specialists and registered chronological folds required")
    if len(frame) != len(baseline_probabilities):
        raise ValueError("Probability/PA alignment differs")
    earlier = frame.foldNumber.lt(before_fold).to_numpy()
    historical = frame.loc[earlier].reset_index(drop=True)
    base = np.asarray(baseline_probabilities)[earlier]
    result = {"schemaVersion": "MLB_V19_PRIOR_OOF_REGIME_ELIGIBILITY_V1", "beforeFold": before_fold,
              "selectionScope": "STRICTLY_EARLIER_REGISTERED_OOF_FOLDS", "selected": [], "regimes": [],
              "rules": {"minimumPAsPerFold": MIN_REGIME_PAS, "minimumGamesPerFold": MIN_REGIME_GAMES,
                        "minimumEarlierFolds": MIN_PRIOR_FOLDS, "minimumCalendarMonths": MIN_MONTHS,
                        "minimumTeams": MIN_TEAMS, "minimumExcessLogLoss": MIN_EXCESS_LOG_LOSS,
                        "minimumAbsoluteStableClassResidual": MIN_ABSOLUTE_CLASS_BIAS,
                        "maximumSpecialists": maximum}, "evaluationOutcomeRowsInspected": 0}
    if historical.empty:
        return result
    y, contributions = _validate_frame(historical, base)
    masks, _ = regime_masks(historical)
    result["trainingObservations"] = len(historical)
    result["trainingEnd"] = str(historical.game_date.max())
    for name, mask in masks.items():
        folds = []
        for number in sorted(historical.foldNumber.unique()):
            fold = historical.foldNumber.eq(number).to_numpy()
            local, complement = fold & mask, fold & ~mask
            rows = int(local.sum())
            games = int(historical.loc[local, "canonicalGameId"].nunique())
            adequate = rows >= MIN_REGIME_PAS and games >= MIN_REGIME_GAMES and complement.sum() >= MIN_REGIME_PAS
            folds.append({"foldNumber": int(number), "observations": rows, "games": games,
                          "adequate": bool(adequate),
                          "excessLogLossVsComplement": float(contributions["logLoss"][local].mean() - contributions["logLoss"][complement].mean()) if rows and complement.any() else None,
                          "observedMinusPredictedClassRates": contributions["calibrationResidual"][local].mean(axis=0).tolist() if rows else None})
        adequate = [row for row in folds if row["adequate"]]
        months = int(historical.loc[mask, "game_date"].astype(str).str[:7].nunique())
        teams = set()
        for field in ("homeTeamId", "awayTeamId"):
            if field in historical:
                teams.update(historical.loc[mask, field].dropna().astype(str))
        stable_bias_classes = []
        stable_excess = False
        if len(adequate) >= MIN_PRIOR_FOLDS:
            residuals = np.asarray([row["observedMinusPredictedClassRates"] for row in adequate])
            stable = ((residuals >= MIN_ABSOLUTE_CLASS_BIAS).all(axis=0)
                      | (residuals <= -MIN_ABSOLUTE_CLASS_BIAS).all(axis=0))
            stable_bias_classes = [PA_CLASS_ORDER[index] for index in np.flatnonzero(stable)]
            stable_excess = all(row["excessLogLossVsComplement"] >= MIN_EXCESS_LOG_LOSS for row in adequate)
        eligible = (len(adequate) >= MIN_PRIOR_FOLDS and months >= MIN_MONTHS and len(teams) >= MIN_TEAMS
                    and (stable_excess or bool(stable_bias_classes)))
        pooled_excess = float(contributions["logLoss"][mask].mean() - contributions["logLoss"][~mask].mean()) if mask.any() and (~mask).any() else None
        result["regimes"].append({"name": name, "eligible": bool(eligible), "folds": folds,
                                  "months": months, "teams": len(teams), "stableExcessLoss": stable_excess,
                                  "stableBiasClasses": stable_bias_classes,
                                  "pooledExcessLogLoss": pooled_excess,
                                  "reason": "PERSISTENT_PAST_FOLD_ERROR" if eligible else "INSUFFICIENT_SUPPORT_OR_PERSISTENCE"})
    eligible = [row for row in result["regimes"] if row["eligible"]]
    eligible.sort(key=lambda row: (-float(row["pooledExcessLogLoss"] or 0.), row["name"]))
    result["selected"] = [row["name"] for row in eligible[:maximum]]
    return result


def _metrics(y: np.ndarray, p: np.ndarray, contributions: Mapping[str, np.ndarray], mask: np.ndarray) -> dict[str, Any]:
    if not mask.any():
        return {"observations": 0, "logLoss": None, "brier": None, "perClass": []}
    labels, probabilities = y[mask], p[mask]
    classes = []
    for index, name in enumerate(PA_CLASS_ORDER):
        observed = labels == index
        predicted = probabilities[:, index]
        bins = np.minimum((predicted * 10).astype(int), 9)
        counts = np.bincount(bins, minlength=10)
        expected = np.bincount(bins, weights=predicted, minlength=10)
        actual = np.bincount(bins, weights=observed, minlength=10)
        classes.append({"className": name, "observedCount": int(observed.sum()),
                        "observedRate": float(observed.mean()), "predictedRate": float(predicted.mean()),
                        "rateBias": float(predicted.mean() - observed.mean()),
                        "oneVsRestBrier": float(np.square(predicted - observed).mean()),
                        "expectedCalibrationError": float(np.abs(expected - actual).sum() / len(labels)),
                        "meanTrueClassLogLoss": float(contributions["logLoss"][mask][observed].mean()) if observed.any() else None,
                        "reliability": [{"bin": b, "observations": int(counts[b]),
                                         "meanProbability": float(expected[b] / counts[b]) if counts[b] else None,
                                         "observedRate": float(actual[b] / counts[b]) if counts[b] else None} for b in range(10)]})
    confusion = np.zeros((len(PA_CLASS_ORDER), len(PA_CLASS_ORDER)), dtype=int)
    np.add.at(confusion, (labels, probabilities.argmax(axis=1)), 1)
    return {"observations": int(mask.sum()), "logLoss": float(contributions["logLoss"][mask].mean()),
            "brier": float(contributions["brier"][mask].mean()), "perClass": classes,
            "confusionObservedRowsPredictedColumns": confusion.tolist(),
            "brierDefinition": "SUMMED_EIGHT_CLASS_SQUARED_PROBABILITY_ERROR",
            "exposureWeighting": "ONE_WEIGHT_PER_OBSERVED_PA_NOT_EQUAL_WEIGHT_PER_PLAYER"}


def evaluate_predictions(frame: pd.DataFrame, predictions: Mapping[str, np.ndarray], *,
                         baseline_name: str = "V18", cluster_columns: Sequence[str] = (),
                         interval_regimes: Sequence[str] = (),
                         replicates: int = 500) -> dict[str, Any]:
    """Matched overall, regime/complement, fold/month/team/cluster diagnostics.

    Removal sensitivities deliberately inspect evaluation contributions and are
    labeled descriptive; they must never select a regime or change a gate.
    """
    if baseline_name not in predictions:
        raise ValueError("A matched frozen V18 baseline is required")
    matrices = {name: np.asarray(value, dtype=float) for name, value in predictions.items()}
    y, baseline_contrib = _validate_frame(frame, matrices[baseline_name])
    contributions = {name: metric_contributions(y, value) for name, value in matrices.items()}
    masks, registry = regime_masks(frame)
    all_rows = np.ones(len(frame), dtype=bool)
    groups: list[tuple[str, str, np.ndarray]] = [("overall", "ALL", all_rows)]
    for name, mask in masks.items():
        groups.extend([("regime", name, mask), ("complement", name, ~mask)])
    for dimension in ("foldNumber", "month", "battingTeamId", "fieldingTeamId", *cluster_columns):
        if dimension == "month":
            values = frame.game_date.astype(str).str[:7]
        elif dimension in frame:
            values = frame[dimension].astype(str)
            if dimension in cluster_columns:
                # Cluster numbers are local to their fitted fold, not a common
                # longitudinal identity unless separately aligned/proved.
                values = frame.foldNumber.astype(str) + ":" + values
        else:
            continue
        for value in sorted(values.unique()):
            groups.append((dimension, str(value), values.eq(value).to_numpy()))
    rows = []
    for dimension, group, mask in groups:
        if not mask.any():
            continue
        baseline_ll = float(baseline_contrib["logLoss"][mask].mean())
        baseline_brier = float(baseline_contrib["brier"][mask].mean())
        for name, matrix in matrices.items():
            detail = _metrics(y, matrix, contributions[name], mask)
            # Rich per-class evidence is retained for overall/regime/complement;
            # repeated month/team/cluster tables retain compact rate evidence.
            if dimension not in ("overall", "regime", "complement"):
                for item in detail["perClass"]:
                    item.pop("reliability", None)
                detail.pop("confusionObservedRowsPredictedColumns", None)
            rows.append({"model": name, "dimension": dimension, "group": group,
                         "games": int(frame.loc[mask, "canonicalGameId"].nunique()), **detail,
                         "deltaLogLossVsV18": detail["logLoss"] - baseline_ll,
                         "deltaBrierVsV18": detail["brier"] - baseline_brier})
    unknown_interval_regimes = set(interval_regimes) - set(masks)
    if unknown_interval_regimes:
        raise ValueError("Interval regimes are outside the predeclared registry: " + ", ".join(sorted(unknown_interval_regimes)))
    intervals, regime_intervals, removal = {}, {}, []
    for name, matrix in matrices.items():
        if name == baseline_name:
            continue
        intervals[name] = paired_uncertainty(frame, y, matrices[baseline_name], matrix, replicates=replicates)
        regime_intervals[name] = {}
        for regime in interval_regimes:
            for scope, mask in (("regime", masks[regime]), ("complement", ~masks[regime])):
                key = f"{regime}:{scope}"
                games = int(frame.loc[mask, "canonicalGameId"].nunique())
                if mask.sum() < 100 or games < 20:
                    regime_intervals[name][key] = {"status": "INSUFFICIENT_DESCRIPTIVE_SUPPORT",
                                                   "observations": int(mask.sum()), "games": games}
                else:
                    regime_intervals[name][key] = paired_uncertainty(
                        frame.loc[mask].reset_index(drop=True), y[mask], matrices[baseline_name][mask],
                        matrix[mask], replicates=replicates)
        delta = contributions[name]["logLoss"] - baseline_contrib["logLoss"]
        candidate_groups = {"month": [(str(month), frame.game_date.astype(str).str[:7].eq(month).to_numpy())
                                      for month in sorted(frame.game_date.astype(str).str[:7].unique())],
                            "regime": list(masks.items())}
        teams = set()
        if {"homeTeamId", "awayTeamId"}.issubset(frame.columns):
            teams = set(frame.homeTeamId.astype(str)) | set(frame.awayTeamId.astype(str))
        candidate_groups["team_either_role"] = [(team, (frame.homeTeamId.astype(str).eq(team) | frame.awayTeamId.astype(str).eq(team)).to_numpy()) for team in sorted(teams)]
        candidate_groups["cluster_fold_local"] = [(f"{dimension}:{group}", mask) for dimension, group, mask in groups if dimension in cluster_columns]
        for dimension, choices in candidate_groups.items():
            usable = [(group, mask) for group, mask in choices if mask.sum() >= 100 and (~mask).sum() >= 100]
            if not usable:
                continue
            group, mask = min(usable, key=lambda item: (float(delta[item[1]].mean()), item[0]))
            removal.append({"model": name, "removedDimension": dimension, "removed": group,
                            "removedPAs": int(mask.sum()), "remainingPAs": int((~mask).sum()),
                            "remainingGames": int(frame.loc[~mask, "canonicalGameId"].nunique()),
                            "removedGroupDeltaLogLoss": float(delta[mask].mean()),
                            "remainingDeltaLogLoss": float(delta[~mask].mean()),
                            "scope": "DESCRIPTIVE_EVALUATION_SENSITIVITY_NOT_SELECTION"})
    return {"schemaVersion": "MLB_V19_MATCHED_DEVELOPMENT_EVALUATION_V1", "observations": len(frame),
            "games": int(frame.canonicalGameId.nunique()), "classOrder": list(PA_CLASS_ORDER),
            "regimeRegistry": registry, "metrics": rows, "pairedIntervals": intervals,
            "regimePairedIntervals": regime_intervals,
            "removalSensitivity": removal,
            "interpretation": "REUSED_DEVELOPMENT_DESCRIPTIVE_NOT_INDEPENDENT_CONFIRMATION",
            "finalOotRowsRead": 0, "modelFits": 0,
            "pregameGameMetrics": {"status": "UNSUPPORTED_HISTORICAL_PARTICIPANT_VINTAGES",
                                   "reason": "Realized PA membership, pitch sequence, starters and batting orders do not establish historical pregame inputs."}}


def compare_game_mechanics(frame: pd.DataFrame, baseline: np.ndarray, challenger: np.ndarray, *,
                           transition_model: Any, transition_training_end: str,
                           transition_model_sha256: str, game_truth: pd.DataFrame | None = None,
                           n_sims: int = 500, maximum_games: int = 20) -> dict[str, Any]:
    """Reuse accepted simulation solely as labeled oracle-mechanics sensitivity."""
    from .mlb_regime_simulation import compare_paired_game_mechanics
    eligible = frame.game_date.astype(str).gt(transition_training_end).to_numpy()
    if "foldNumber" in frame:
        # The later fold is fixed prospectively in the research protocol, not
        # chosen for candidate performance or observed final scores.
        eligible &= frame.foldNumber.eq(5).to_numpy()
    return compare_paired_game_mechanics(
        frame.loc[eligible].reset_index(drop=True), np.asarray(baseline)[eligible],
        np.asarray(challenger)[eligible], transition_model=transition_model,
        transition_training_end=transition_training_end, transition_model_sha256=transition_model_sha256,
        n_sims=n_sims, maximum_games=maximum_games, game_truth=game_truth,
    )
