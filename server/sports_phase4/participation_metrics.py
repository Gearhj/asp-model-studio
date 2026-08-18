from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pyarrow as pa
from sklearn.metrics import average_precision_score


METRICS_SCHEMA_VERSION = "MLB_PARTICIPATION_METRICS_V1"
CALIBRATION_BINS = 10
MAX_ACCEPTABLE_ECE = 0.05
BOOTSTRAP_RESAMPLES = 500
BOOTSTRAP_SEED = 20_260_817
PROBABILITY_EPSILON = 1e-12


class ParticipationMetricsError(ValueError):
    """Raised when metric evidence is non-finite, incomplete, or misaligned."""


def _numeric(values: Sequence[Any], *, label: str) -> np.ndarray:
    parsed = np.asarray(values, dtype=np.float64)
    if parsed.ndim != 1 or parsed.size == 0 or not np.isfinite(parsed).all():
        raise ParticipationMetricsError(f"{label} must be a non-empty finite vector")
    return parsed


def _binary(labels: Sequence[Any]) -> np.ndarray:
    parsed = np.asarray(labels)
    if parsed.ndim != 1 or parsed.size == 0 or not np.isin(parsed, [False, True, 0, 1]).all():
        raise ParticipationMetricsError("binary labels must contain only 0/1")
    return parsed.astype(np.int8)


def _probabilities(values: Sequence[Any]) -> np.ndarray:
    parsed = _numeric(values, label="probabilities")
    if np.any(parsed < 0.0) or np.any(parsed > 1.0):
        raise ParticipationMetricsError("probabilities must be in [0,1]")
    return parsed


def per_row_binary_log_loss(labels: Sequence[Any], probabilities: Sequence[Any]) -> np.ndarray:
    y = _binary(labels)
    p = np.clip(_probabilities(probabilities), PROBABILITY_EPSILON, 1.0 - PROBABILITY_EPSILON)
    if y.size != p.size:
        raise ParticipationMetricsError("labels and probabilities differ in length")
    return -(y * np.log(p) + (1 - y) * np.log1p(-p))


def _governed_order(
    row_order: Sequence[Any] | None,
    *,
    size: int,
) -> list[str]:
    if row_order is None:
        return [f"row:{index:020d}" for index in range(size)]
    if len(row_order) != size:
        raise ParticipationMetricsError("governed row order differs from calibration rows")
    normalized = [str(value) for value in row_order]
    if any(not value for value in normalized) or len(set(normalized)) != size:
        raise ParticipationMetricsError("governed row order must contain unique non-empty identities")
    return normalized


def calibration_evidence(
    labels: Sequence[Any],
    probabilities: Sequence[Any],
    *,
    governed_row_order: Sequence[Any] | None = None,
) -> dict[str, Any]:
    y = _binary(labels)
    p = _probabilities(probabilities)
    if y.size != p.size:
        raise ParticipationMetricsError("labels and probabilities differ in length")
    row_order = _governed_order(governed_row_order, size=int(y.size))
    # Python's sort is stable.  The explicit secondary key makes tied
    # probabilities independent of Arrow chunking, dataframe order, or model
    # implementation details.
    ordered = np.asarray(
        sorted(range(y.size), key=lambda index: (float(p[index]), row_order[index])),
        dtype=np.int64,
    )
    split = np.array_split(ordered, CALIBRATION_BINS)
    bins: list[dict[str, Any]] = []
    weighted_gap = 0.0
    position = 0
    observed_indices: list[int] = []
    for index, indices in enumerate(split):
        count = int(indices.size)
        observed_indices.extend(int(value) for value in indices)
        mean_probability = float(p[indices].mean()) if count else None
        observed_rate = float(y[indices].mean()) if count else None
        absolute_gap = (
            abs(float(mean_probability) - float(observed_rate)) if count else None
        )
        if absolute_gap is not None:
            weighted_gap += count * absolute_gap
        bins.append(
            {
                "binIndex": index,
                "sortedStartInclusive": position,
                "sortedEndExclusive": position + count,
                "count": count,
                "minimumProbability": float(p[indices[0]]) if count else None,
                "maximumProbability": float(p[indices[-1]]) if count else None,
                "meanProbability": mean_probability,
                "observedRate": observed_rate,
                "absoluteGap": absolute_gap,
            }
        )
        position += count
    rows_assigned_exactly_once = (
        position == y.size and sorted(observed_indices) == list(range(y.size))
    )
    if not rows_assigned_exactly_once:
        raise ParticipationMetricsError("equal-count calibration did not assign every row once")
    ece = float(weighted_gap / y.size)
    all_bins_finite_nonempty = all(
        item["count"] > 0
        and item["meanProbability"] is not None
        and math.isfinite(float(item["meanProbability"]))
        and item["observedRate"] is not None
        and math.isfinite(float(item["observedRate"]))
        for item in bins
    )
    return {
        "schemaVersion": "MLB_PARTICIPATION_BINARY_CALIBRATION_V2",
        "rowCount": int(y.size),
        "binCount": CALIBRATION_BINS,
        "binningPolicy": "EQUAL_COUNT_NUMPY_ARRAY_SPLIT",
        "sortPolicy": "PROBABILITY_ASC_THEN_GOVERNED_ROW_ID_ASC",
        "rowsAssignedExactlyOnce": rows_assigned_exactly_once,
        "bins": bins,
        "expectedCalibrationError": ece,
        "acceptableThreshold": MAX_ACCEPTABLE_ECE,
        "allBinsFiniteAndNonempty": all_bins_finite_nonempty,
        "acceptable": ece <= MAX_ACCEPTABLE_ECE and all_bins_finite_nonempty,
    }


def binary_metrics(
    labels: Sequence[Any],
    probabilities: Sequence[Any],
    *,
    governed_row_order: Sequence[Any] | None = None,
) -> dict[str, Any]:
    y = _binary(labels)
    p = _probabilities(probabilities)
    if y.size != p.size:
        raise ParticipationMetricsError("labels and probabilities differ in length")
    losses = per_row_binary_log_loss(y, p)
    brier = float(np.mean(np.square(p - y)))
    average_precision = (
        float(average_precision_score(y, p)) if np.unique(y).size == 2 else float(y[0])
    )
    predicted_label = p >= 0.5
    top_label_confidence = np.maximum(p, 1.0 - p)
    top_label_correct = predicted_label == y.astype(bool)
    return {
        "schemaVersion": METRICS_SCHEMA_VERSION,
        "rowCount": int(y.size),
        "positiveCount": int(y.sum()),
        "negativeCount": int(y.size - y.sum()),
        "binaryLogLoss": float(losses.mean()),
        "brierScore": brier,
        "averagePrecision": average_precision,
        "calibration": calibration_evidence(
            y, p, governed_row_order=governed_row_order
        ),
        "topLabelCalibration": calibration_evidence(
            top_label_correct,
            top_label_confidence,
            governed_row_order=governed_row_order,
        ),
    }


def _columns(table: pa.Table, names: Sequence[str]) -> dict[str, list[Any]]:
    if not isinstance(table, pa.Table) or table.num_rows == 0:
        raise ParticipationMetricsError("metrics require a non-empty pyarrow table")
    missing = sorted(set(names) - set(table.column_names))
    if missing:
        raise ParticipationMetricsError(f"metrics table is missing columns: {missing}")
    return table.select(names).to_pydict()


def probability_weighted_historical_order(
    player_ids: Sequence[str],
    probabilities: Sequence[float],
    historical_means: Sequence[float | None],
    historical_modes: Sequence[float | None],
) -> list[str]:
    if not (
        len(player_ids) == len(probabilities) == len(historical_means) == len(historical_modes)
    ):
        raise ParticipationMetricsError("lineup order inputs differ in length")
    rows: list[tuple[float, float, str]] = []
    for player_id, probability, mean, mode in zip(
        player_ids, probabilities, historical_means, historical_modes, strict=True
    ):
        if not isinstance(player_id, str) or not player_id:
            raise ParticipationMetricsError("lineup player identity is invalid")
        if not math.isfinite(float(probability)) or not 0.0 <= float(probability) <= 1.0:
            raise ParticipationMetricsError("lineup probability is invalid")
        historical = mean if mean is not None and math.isfinite(float(mean)) else mode
        if historical is None or not math.isfinite(float(historical)):
            historical = 5.0
        score = float(probability) * float(historical) + (1.0 - float(probability)) * 5.0
        rows.append((score, -float(probability), player_id))
    return [item[2] for item in sorted(rows)]


def lineup_metrics(
    table: pa.Table,
    probabilities: Sequence[Any],
    *,
    uncovered_positive_count: int,
    total_actual_positive_count: int,
) -> dict[str, Any]:
    values = _columns(
        table,
        (
            "candidate_row_id",
            "game_id",
            "team_id",
            "canonical_player_uuid",
            "target_start",
            "target_batting_order",
            "actual_lineup_size",
            "complete_lineup_eligible",
            "trailing_order_mean",
            "trailing_order_mode",
            "early_season_indicator",
        ),
    )
    p = _probabilities(probabilities)
    if p.size != table.num_rows:
        raise ParticipationMetricsError("lineup probabilities differ from table rows")
    if type(uncovered_positive_count) is not int or uncovered_positive_count < 0:
        raise ParticipationMetricsError("uncovered lineup positives must be non-negative")
    if type(total_actual_positive_count) is not int or total_actual_positive_count <= 0:
        raise ParticipationMetricsError("total actual lineup positives must be positive")
    base = binary_metrics(
        values["target_start"],
        p,
        governed_row_order=values["candidate_row_id"],
    )
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, key in enumerate(zip(values["game_id"], values["team_id"], strict=True)):
        grouped[key].append(index)
    true_positive = 0
    predicted_total = 0
    complete_predictions = 0
    recovered = 0
    exact_sets = 0
    exact_orders = 0
    exact_batting_position_hits = 0
    exact_batting_position_count = 0
    order_errors: list[float] = []
    strata = {
        "earlySeason": {"teamGameCount": 0, "actualPositiveCount": 0, "topNineHits": 0},
        "laterSeason": {"teamGameCount": 0, "actualPositiveCount": 0, "topNineHits": 0},
    }
    game_rows: list[dict[str, Any]] = []
    order_eligible_team_games = 0
    for key in sorted(grouped):
        indices = grouped[key]
        ranked = sorted(
            indices,
            key=lambda index: (-p[index], str(values["canonical_player_uuid"][index])),
        )
        selected = ranked[:9]
        actual = {index for index in indices if values["target_start"][index]}
        selected_set = set(selected)
        hits = len(actual & selected_set)
        eligibility_values = {values["complete_lineup_eligible"][index] for index in indices}
        if eligibility_values - {True, False} or len(eligibility_values) != 1:
            raise ParticipationMetricsError("complete-lineup eligibility differs within a team-game")
        order_eligible = eligibility_values == {True}
        true_positive += hits
        predicted_total += len(selected)
        exact_set = order_eligible and len(selected) == 9 and selected_set == actual
        if order_eligible:
            order_eligible_team_games += 1
            complete_predictions += int(len(selected) == 9)
            recovered += int(hits == 9)
            exact_sets += int(exact_set)
        ordered_players = probability_weighted_historical_order(
            [str(values["canonical_player_uuid"][index]) for index in selected],
            [float(p[index]) for index in selected],
            [values["trailing_order_mean"][index] for index in selected],
            [values["trailing_order_mode"][index] for index in selected],
        )
        player_to_predicted_order = {
            player: order for order, player in enumerate(ordered_players, start=1)
        }
        exact_order: bool | None = None
        if order_eligible:
            # Batting-order claims are meaningful only after exact recovery of
            # the governed nine-player set.  A wrong set is an explicit false
            # exact-order result and contributes no partial order distances.
            exact_order = bool(exact_set)
            if exact_set:
                for index in sorted(actual):
                    player = str(values["canonical_player_uuid"][index])
                    target_order = values["target_batting_order"][index]
                    if target_order is None:
                        raise ParticipationMetricsError(
                            "eligible actual lineup starter is missing batting order"
                        )
                    predicted_order = player_to_predicted_order[player]
                    error = abs(predicted_order - int(target_order))
                    order_errors.append(error)
                    exact_batting_position_count += 1
                    exact_batting_position_hits += int(error == 0)
                    exact_order = exact_order and error == 0
            exact_orders += int(exact_order)
        early = bool(values["early_season_indicator"][indices[0]])
        stratum = strata["earlySeason" if early else "laterSeason"]
        stratum["teamGameCount"] += 1
        stratum["actualPositiveCount"] += int(values["actual_lineup_size"][indices[0]])
        stratum["topNineHits"] += hits
        game_rows.append(
            {
                "gameId": key[0],
                "teamId": key[1],
                "candidateCount": len(indices),
                "selectedCount": len(selected),
                "coveredActualCount": len(actual),
                "topNineHits": hits,
                "completeLineupEligible": order_eligible,
                "exactSet": (
                    exact_set
                    if order_eligible
                    else None
                ),
                "exactOrder": exact_order,
                "exactBattingPositionHits": (
                    sum(
                        player_to_predicted_order[
                            str(values["canonical_player_uuid"][index])
                        ]
                        == int(values["target_batting_order"][index])
                        for index in actual
                    )
                    if exact_set
                    else None
                ),
                "exactBattingPositionCount": 9 if exact_set else None,
            }
        )
    game_count = len(grouped)
    precision = true_positive / predicted_total if predicted_total else 0.0
    recall = true_positive / total_actual_positive_count
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    pool_covered = total_actual_positive_count - uncovered_positive_count
    game_eligibility: dict[str, list[bool]] = defaultdict(list)
    game_exact_sets: dict[str, list[bool]] = defaultdict(list)
    game_exact_orders: dict[str, list[bool]] = defaultdict(list)
    for row in game_rows:
        game_eligibility[row["gameId"]].append(bool(row["completeLineupEligible"]))
        if row["completeLineupEligible"]:
            game_exact_sets[row["gameId"]].append(bool(row["exactSet"]))
            game_exact_orders[row["gameId"]].append(bool(row["exactOrder"]))
    eligible_games = [
        game_id
        for game_id, flags in game_eligibility.items()
        if flags and all(flags)
    ]
    exact_set_games = sum(
        len(game_exact_sets[game_id]) == 2 and all(game_exact_sets[game_id])
        for game_id in eligible_games
    )
    exact_order_games = sum(
        len(game_exact_orders[game_id]) == 2 and all(game_exact_orders[game_id])
        for game_id in eligible_games
    )
    stratified_metrics: dict[str, Any] = {}
    for name, raw in strata.items():
        denominator = int(raw["actualPositiveCount"])
        stratified_metrics[name] = {
            **raw,
            "top9Recall": (
                float(raw["topNineHits"] / denominator) if denominator else None
            ),
        }
    return {
        **base,
        "poolCoverage": float(pool_covered / total_actual_positive_count),
        "uncoveredPositiveCount": uncovered_positive_count,
        "totalActualPositiveCount": total_actual_positive_count,
        "teamGameCount": game_count,
        "completeLineupEligibleTeamGameCount": order_eligible_team_games,
        "completeLineupEligibleGameCount": len(eligible_games),
        "orderMetricGameCount": len(eligible_games),
        "top9Recall": float(recall),
        "topNinePrecision": float(precision),
        "topNineF1": float(f1),
        "completeLineupRate": (
            float(complete_predictions / order_eligible_team_games)
            if order_eligible_team_games
            else None
        ),
        "completeLineupRecoveryRate": (
            float(recovered / order_eligible_team_games)
            if order_eligible_team_games
            else None
        ),
        "exactLineupRate": (
            float(exact_set_games / len(eligible_games))
            if eligible_games
            else None
        ),
        "exactOrderRate": (
            float(exact_order_games / len(eligible_games))
            if eligible_games
            else None
        ),
        "battingOrderMae": float(np.mean(order_errors)) if order_errors else None,
        "exactBattingPositionRate": (
            float(exact_batting_position_hits / exact_batting_position_count)
            if exact_batting_position_count
            else None
        ),
        "exactBattingPositionCount": exact_batting_position_hits,
        "exactBattingPositionEligibleCount": exact_batting_position_count,
        "earlySeasonTop9Recall": stratified_metrics["earlySeason"]["top9Recall"],
        "laterSeasonTop9Recall": stratified_metrics["laterSeason"]["top9Recall"],
        "stratifiedMetrics": stratified_metrics,
        "teamGames": game_rows,
    }


def starter_metrics(
    table: pa.Table,
    predicted_bfp: Sequence[Any],
    predicted_outs: Sequence[Any],
    reach_probabilities: Mapping[int, Sequence[Any]],
) -> dict[str, Any]:
    values = _columns(
        table,
        (
            "target_row_id",
            "target_bfp",
            "target_outs",
            "early_season_indicator",
            "previous_start_bfp",
        ),
    )
    target_bfp = _numeric(values["target_bfp"], label="starter target BFP")
    target_outs = _numeric(values["target_outs"], label="starter target outs")
    bfp = np.maximum(_numeric(predicted_bfp, label="predicted BFP"), 0.0)
    outs = np.maximum(_numeric(predicted_outs, label="predicted outs"), 0.0)
    if not (target_bfp.size == target_outs.size == bfp.size == outs.size):
        raise ParticipationMetricsError("starter prediction arrays differ in length")
    bfp_error = bfp - target_bfp
    outs_error = outs - target_outs
    output: dict[str, Any] = {
        "schemaVersion": METRICS_SCHEMA_VERSION,
        "rowCount": int(target_bfp.size),
        "bfpMae": float(np.mean(np.abs(bfp_error))),
        "bfpRmse": float(np.sqrt(np.mean(np.square(bfp_error)))),
        "bfpMedianAbsoluteError": float(np.median(np.abs(bfp_error))),
        "outsMae": float(np.mean(np.abs(outs_error))),
        "outsRmse": float(np.sqrt(np.mean(np.square(outs_error)))),
        "outsMedianAbsoluteError": float(np.median(np.abs(outs_error))),
    }
    for threshold in (15, 18, 21):
        if threshold not in reach_probabilities:
            raise ParticipationMetricsError(f"starter reach probability {threshold} is missing")
        labels = target_outs >= threshold
        metrics = binary_metrics(
            labels,
            reach_probabilities[threshold],
            governed_row_order=values["target_row_id"],
        )
        output[f"reach{threshold}LogLoss"] = metrics["binaryLogLoss"]
        output[f"reach{threshold}Brier"] = metrics["brierScore"]
        output[f"reach{threshold}Calibration"] = metrics["calibration"]
    early = np.asarray(values["early_season_indicator"], dtype=np.float64) == 1.0
    output["earlySeasonBfpMae"] = (
        float(np.mean(np.abs(bfp_error[early]))) if np.any(early) else None
    )
    has_history = np.asarray(
        [value is not None for value in values["previous_start_bfp"]],
        dtype=np.bool_,
    )
    history_strata: dict[str, Any] = {}
    for name, mask in (
        ("withPriorStartHistory", has_history),
        ("withoutPriorStartHistory", ~has_history),
    ):
        history_strata[name] = {
            "rowCount": int(mask.sum()),
            "bfpMae": float(np.mean(np.abs(bfp_error[mask]))) if np.any(mask) else None,
            "bfpRmse": (
                float(np.sqrt(np.mean(np.square(bfp_error[mask]))))
                if np.any(mask)
                else None
            ),
            "outsMae": float(np.mean(np.abs(outs_error[mask]))) if np.any(mask) else None,
            "outsRmse": (
                float(np.sqrt(np.mean(np.square(outs_error[mask]))))
                if np.any(mask)
                else None
            ),
        }
    output["priorStartHistoryCoverage"] = float(has_history.mean())
    output["historyStratifiedMetrics"] = history_strata
    return output


def bullpen_metrics(
    table: pa.Table,
    probabilities: Sequence[Any],
    predicted_bfp: Sequence[Any],
    predicted_outs: Sequence[Any],
    *,
    coverage_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    values = _columns(
        table,
        (
            "candidate_row_id",
            "game_id",
            "team_id",
            "target_appearance",
            "target_bfp",
            "target_outs",
            "actual_team_reliever_count",
            "early_season_indicator",
            "canonical_player_uuid",
            "appeared_yesterday",
            "appeared_on_two_consecutive_prior_days",
        ),
    )
    p = _probabilities(probabilities)
    pred_bfp = np.maximum(_numeric(predicted_bfp, label="bullpen predicted BFP"), 0.0)
    pred_outs = np.maximum(_numeric(predicted_outs, label="bullpen predicted outs"), 0.0)
    if p.size != table.num_rows or pred_bfp.size != table.num_rows or pred_outs.size != table.num_rows:
        raise ParticipationMetricsError("bullpen prediction arrays differ from table rows")
    required_coverage = {
        "targetTeamGames",
        "zeroRelieverTeamGames",
        "actualPositiveRows",
        "coveredPositiveRows",
        "uncoveredPositiveRows",
        "emptyCandidatePools",
        "emptyPoolZeroRelieverTeamGames",
        "emptyPoolPositiveRelieverTeamGames",
        "emptyPoolActualPositiveRows",
        "earlySeasonActualPositiveRows",
    }
    if not isinstance(coverage_evidence, Mapping) or not required_coverage.issubset(
        coverage_evidence
    ):
        raise ParticipationMetricsError("bullpen coverage evidence is incomplete")
    for key in required_coverage:
        if type(coverage_evidence[key]) is not int or coverage_evidence[key] < 0:
            raise ParticipationMetricsError(f"bullpen coverage {key} must be non-negative integer")
    total_actual_positive_count = int(coverage_evidence["actualPositiveRows"])
    uncovered_positive_count = int(coverage_evidence["uncoveredPositiveRows"])
    target_team_games = int(coverage_evidence["targetTeamGames"])
    empty_pools = int(coverage_evidence["emptyCandidatePools"])
    empty_zero = int(coverage_evidence["emptyPoolZeroRelieverTeamGames"])
    empty_positive = int(coverage_evidence["emptyPoolPositiveRelieverTeamGames"])
    empty_actual_rows = int(coverage_evidence["emptyPoolActualPositiveRows"])
    if empty_zero + empty_positive != empty_pools:
        raise ParticipationMetricsError("bullpen empty-pool counts do not reconcile")
    base = binary_metrics(
        values["target_appearance"],
        p,
        governed_row_order=values["candidate_row_id"],
    )
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, key in enumerate(zip(values["game_id"], values["team_id"], strict=True)):
        grouped[key].append(index)
    set_recalls: list[float] = []
    jaccards: list[float] = []
    count_errors: list[float] = []
    expected_count_errors: list[float] = []
    top3_hits = 0
    top5_hits = 0
    actual_total_from_groups = 0
    zero_correct = 0
    zero_total = 0
    early_hits = 0
    duration_bfp_errors: list[float] = []
    duration_out_errors: list[float] = []
    recent_use_indices: dict[str, list[int]] = {
        "zeroRecentUseDays": [],
        "oneRecentUseDay": [],
        "multipleRecentUseDays": [],
    }
    for key in sorted(grouped):
        indices = grouped[key]
        ranked = sorted(
            indices,
            key=lambda index: (-p[index], str(values["canonical_player_uuid"][index])),
        )
        actual = {index for index in indices if values["target_appearance"][index]}
        actual_count = int(values["actual_team_reliever_count"][indices[0]])
        uncovered_actual = actual_count - len(actual)
        if uncovered_actual < 0:
            raise ParticipationMetricsError("bullpen covered positives exceed actual relievers")
        expected_count = float(sum(p[index] for index in indices))
        predicted_count = min(len(indices), max(0, int(math.floor(expected_count + 0.5))))
        selected = set(ranked[:predicted_count])
        intersection = len(actual & selected)
        # Actual relievers absent from the governed candidate pool still belong
        # to the set union.  Omitting them would inflate Jaccard while coverage
        # is incomplete.
        union = len(actual | selected) + uncovered_actual
        set_recalls.append(intersection / actual_count if actual_count else float(not selected))
        jaccards.append(intersection / union if union else 1.0)
        count_errors.append(abs(predicted_count - actual_count))
        expected_count_errors.append(abs(expected_count - actual_count))
        top3_hits += len(actual & set(ranked[:3]))
        top5_hits += len(actual & set(ranked[:5]))
        actual_total_from_groups += actual_count
        if actual_count == 0:
            zero_total += 1
            zero_correct += int(predicted_count == 0)
        if bool(values["early_season_indicator"][indices[0]]):
            early_hits += len(actual & selected)
        for index in indices:
            if bool(values["appeared_on_two_consecutive_prior_days"][index]):
                recent_use_indices["multipleRecentUseDays"].append(index)
            elif bool(values["appeared_yesterday"][index]):
                recent_use_indices["oneRecentUseDay"].append(index)
            else:
                recent_use_indices["zeroRecentUseDays"].append(index)
        for index in actual:
            if values["target_bfp"][index] is not None:
                duration_bfp_errors.append(abs(pred_bfp[index] - float(values["target_bfp"][index])))
            if values["target_outs"][index] is not None:
                duration_out_errors.append(abs(pred_outs[index] - float(values["target_outs"][index])))
    if len(grouped) + empty_pools != target_team_games:
        raise ParticipationMetricsError("bullpen team-game denominator does not reconcile")
    if actual_total_from_groups + empty_actual_rows != total_actual_positive_count:
        raise ParticipationMetricsError("bullpen actual-positive denominator does not reconcile")
    if zero_total + empty_zero != int(coverage_evidence["zeroRelieverTeamGames"]):
        raise ParticipationMetricsError("bullpen zero-reliever denominator does not reconcile")
    set_recalls.extend([1.0] * empty_zero)
    set_recalls.extend([0.0] * empty_positive)
    jaccards.extend([1.0] * empty_zero)
    jaccards.extend([0.0] * empty_positive)
    count_error_sum = float(sum(count_errors) + empty_actual_rows)
    expected_count_error_sum = float(sum(expected_count_errors) + empty_actual_rows)
    zero_correct += empty_zero
    zero_total += empty_zero
    early_actual = int(coverage_evidence["earlySeasonActualPositiveRows"])
    recent_use_strata: dict[str, Any] = {}
    labels = np.asarray(values["target_appearance"], dtype=np.int8)
    for name, raw_indices in recent_use_indices.items():
        indices = np.asarray(raw_indices, dtype=np.int64)
        if indices.size:
            losses = per_row_binary_log_loss(labels[indices], p[indices])
            brier = np.square(p[indices] - labels[indices])
            positives = int(labels[indices].sum())
            recent_use_strata[name] = {
                "rowCount": int(indices.size),
                "positiveCount": positives,
                "binaryLogLoss": float(losses.mean()),
                "brierScore": float(brier.mean()),
            }
        else:
            recent_use_strata[name] = {
                "rowCount": 0,
                "positiveCount": 0,
                "binaryLogLoss": None,
                "brierScore": None,
            }
    return {
        **base,
        "poolCoverage": float(
            (total_actual_positive_count - uncovered_positive_count) / total_actual_positive_count
        )
        if total_actual_positive_count
        else 1.0,
        "uncoveredPositiveCount": uncovered_positive_count,
        "totalActualPositiveCount": total_actual_positive_count,
        "teamGameCount": target_team_games,
        "teamGameSetRecall": float(np.mean(set_recalls)),
        "teamGameSetJaccard": float(np.mean(jaccards)),
        "top3Recall": float(top3_hits / total_actual_positive_count)
        if total_actual_positive_count
        else 1.0,
        "top5Recall": float(top5_hits / total_actual_positive_count)
        if total_actual_positive_count
        else 1.0,
        "relieverCountMae": float(count_error_sum / target_team_games),
        "expectedRelieverCountMae": float(expected_count_error_sum / target_team_games),
        "zeroRelieverAccuracy": float(zero_correct / zero_total) if zero_total else None,
        "conditionalBfpMae": float(np.mean(duration_bfp_errors)) if duration_bfp_errors else None,
        "conditionalOutsMae": float(np.mean(duration_out_errors)) if duration_out_errors else None,
        "earlySeasonSetRecall": float(early_hits / early_actual) if early_actual else None,
        "recentUseStratifiedMetrics": recent_use_strata,
    }


def game_cluster_bootstrap_difference(
    game_ids: Sequence[Any],
    selected_losses: Sequence[Any],
    baseline_losses: Sequence[Any],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    ids = np.asarray(game_ids, dtype=object)
    selected = _numeric(selected_losses, label="selected bootstrap losses")
    baseline = _numeric(baseline_losses, label="baseline bootstrap losses")
    if ids.ndim != 1 or not (ids.size == selected.size == baseline.size):
        raise ParticipationMetricsError("bootstrap vectors differ in length")
    if type(resamples) is not int or resamples < 2 or type(seed) is not int:
        raise ParticipationMetricsError("bootstrap policy is invalid")
    unique = np.unique(ids)
    if unique.size < 2:
        raise ParticipationMetricsError("cluster bootstrap requires at least two games")
    cluster_selected_sums = np.asarray(
        [float(np.sum(selected[ids == game])) for game in unique], dtype=np.float64
    )
    cluster_baseline_sums = np.asarray(
        [float(np.sum(baseline[ids == game])) for game in unique], dtype=np.float64
    )
    cluster_row_counts = np.asarray(
        [int(np.sum(ids == game)) for game in unique], dtype=np.int64
    )
    if np.any(cluster_row_counts <= 0):
        raise ParticipationMetricsError("bootstrap contains an empty game cluster")
    rng = np.random.default_rng(seed)
    draws = np.empty(resamples, dtype=np.float64)
    for index in range(resamples):
        sampled = rng.integers(0, unique.size, size=unique.size)
        sampled_rows = int(cluster_row_counts[sampled].sum())
        draws[index] = float(
            cluster_selected_sums[sampled].sum() / sampled_rows
            - cluster_baseline_sums[sampled].sum() / sampled_rows
        )
    lower, upper = np.quantile(draws, [0.025, 0.975], method="linear")
    return {
        "schemaVersion": "MLB_PARTICIPATION_GAME_CLUSTER_BOOTSTRAP_V2",
        "differenceOrder": "SELECTED_MINUS_BASELINE_LOWER_IS_BETTER",
        "clusterSamplingPolicy": "WHOLE_GAME_IDS_WITH_REPLACEMENT",
        "replicateEstimator": (
            "TOTAL_SAMPLED_CLUSTER_LOSS_SUM_DIVIDED_BY_"
            "TOTAL_SAMPLED_CLUSTER_ROW_COUNT"
        ),
        "pointEstimate": float(np.mean(selected - baseline)),
        "standardError": float(np.std(draws, ddof=1)),
        "confidenceLevel": 0.95,
        "interval": {"lower": float(lower), "upper": float(upper)},
        "clusterCount": int(unique.size),
        "resamples": resamples,
        "seed": seed,
        "replicateDifferences": draws.tolist(),
    }


__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "CALIBRATION_BINS",
    "MAX_ACCEPTABLE_ECE",
    "METRICS_SCHEMA_VERSION",
    "ParticipationMetricsError",
    "binary_metrics",
    "bullpen_metrics",
    "calibration_evidence",
    "game_cluster_bootstrap_difference",
    "lineup_metrics",
    "per_row_binary_log_loss",
    "probability_weighted_historical_order",
    "starter_metrics",
]
