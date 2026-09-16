"""Frozen-model uncertainty-field impact trace. No fitting or predict calls.

Read only the accepted Development study's saved metadata, sufficient statistics,
validation states and models, plus its existing current contribution diagnostic.
The only replay is cheap missing-season/gap metadata; no raw PBP or 2025 input.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1"
OUTPUT = ROOT / "outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1"
EVIDENCE = "RETROSPECTIVE_RECONSTRUCTED_AS_OF"
FIELDS = tuple(f"{side}_{name}" for name in ("qb_posterior_sd", "prior_season_gap", "missing_season_uncertainty")
               for side in ("home", "away"))
GAP_FIELDS = tuple(name for name in FIELDS if "qb_posterior" not in name)


def check(condition, reason):
    if not condition:
        raise ValueError(reason)


def record(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest(), "byteCount": path.stat().st_size}


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def put(name, payload):
    digest = hashlib.sha256(payload).hexdigest()
    path = OUTPUT / "diagnostics" / "sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:
        check(path.read_bytes() == payload, "IMMUTABLE_DIAGNOSTIC_DIFFERS")
    return record(path)


def load_json(ref, protected):
    path = Path(ref["path"]).resolve(strict=True)
    check(path.is_relative_to(PREDECESSOR.resolve()) and path.suffix == ".json", "ONLY_PREDECESSOR_JSON_ALLOWED")
    actual = record(path)
    check(all(actual[k] == ref[k] for k in ("sha256", "byteCount")), "PREDECESSOR_JSON_IDENTITY_DIFFERS")
    protected[str(path)] = actual
    return json.loads(path.read_bytes())


def saved_ref(result, path):
    refs = [ref for ref in result["artifacts"] if Path(ref["path"]).resolve() == Path(path).resolve()]
    check(len(refs) == 1, "EXACT_SAVED_ARTIFACT_REQUIRED:" + str(path))
    return refs[0]


def parquet(ref, columns, protected, filters=None):
    path = Path(ref["path"]).resolve(strict=True)
    check(path.is_relative_to((PREDECESSOR / "runs").resolve()), "ONLY_FROZEN_DEVELOPMENT_PARQUET_ALLOWED")
    actual = record(path)
    check(all(actual[k] == ref[k] for k in ("sha256", "byteCount")), "SAVED_PARQUET_CHANGED")
    protected[str(path)] = actual
    metadata = pq.ParquetFile(path)
    season_index = metadata.schema_arrow.names.index("season")
    for row_group in range(metadata.metadata.num_row_groups):
        stats = metadata.metadata.row_group(row_group).column(season_index).statistics
        check(stats is not None and stats.has_min_max and stats.min >= 1999 and stats.max <= 2024,
              "PHYSICAL_DEVELOPMENT_ONLY_ROW_GROUP_REQUIRED")
    frame = pd.read_parquet(path, columns=columns, filters=filters)
    check(frame.season.between(1999, 2024).all(), "NON_DEVELOPMENT_PAYLOAD")
    return frame


def replay_gap_metadata(games, points, lag):
    """Exact frozen flag formula, independent of pooled rates/decay/QB models."""
    available = pd.to_datetime(points[f"available_{lag}h_utc"], utc=True)
    output = []
    for (season, week, cutoff), slate in games.groupby(["season", "week", "slate_cutoff_utc"], sort=True):
        eligible = points.loc[available.lt(pd.Timestamp(cutoff)) & points.season.le(season)
                              & ~points.canonical_game_id.isin(slate.canonical_game_id)]
        if week == 1:
            eligible = eligible.loc[eligible.season.lt(season)]
        latest = eligible.groupby("team_id").season.max().to_dict()
        counts = eligible.groupby("team_id").canonical_game_id.nunique().to_dict()
        for game in slate.itertuples(index=False):
            row = {"canonical_game_id": game.canonical_game_id, "season": int(season), "week": int(week),
                   "game_date": str(pd.Timestamp(game.game_date).date()), "slate_cutoff_utc": str(cutoff), "lagHours": lag}
            for side in ("home", "away"):
                team = getattr(game, f"canonical_{side}_team_id")
                last = latest.get(team)
                gap = int(season) - int(last) if last is not None else int(season) - 1999
                row.update({f"{side}_team": team, f"{side}_latest_eligible_season": int(last) if last is not None else None,
                            f"{side}_eligible_games": int(counts.get(team, 0)), f"{side}_prior_season_gap": gap,
                            f"{side}_missing_season_uncertainty": max(0, gap - 1)})
            output.append(row)
    return pd.DataFrame(output).set_index("canonical_game_id", drop=False)


def summary(values):
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    return {"rows": len(values), "finiteRows": len(finite), "nonzeroRows": int(np.count_nonzero(finite)),
            "minimum": float(finite.min()) if len(finite) else None,
            "maximum": float(finite.max()) if len(finite) else None,
            "mean": float(finite.mean()) if len(finite) else None,
            "sum": float(finite.sum()) if len(finite) else None}


def tree_usage(core, input_names):
    names = [*input_names, "derived_dynamic_home_mean", "derived_dynamic_away_mean",
             "derived_hierarchical_home_mean", "derived_hierarchical_away_mean"]
    reports = []
    for label, model in zip(("HOME", "AWAY"), core.residual_models):
        splits = Counter()
        for stage in model._predictors:
            for tree in stage:
                nodes = tree.nodes
                check({"is_leaf", "feature_idx"}.issubset(nodes.dtype.names), "UNKNOWN_SAVED_HGB_NODE_SCHEMA")
                splits.update(names[int(index)] for index in nodes["feature_idx"][nodes["is_leaf"] == 0])
        reports.append({"target": label, "totalNonleafSplits": sum(splits.values()),
                        "uncertaintyOnlyInputSplits": {name: splits[name] for name in FIELDS},
                        "derivedHierarchicalMeanSplits": {name: splits[name] for name in names[-2:]},
                        "meaning": "Saved tree structure only; no traversal, prediction, counterfactual or causal effect estimate."})
    return reports


def analyze_system(tag, model_ref, state_ref, validation_ref, result, run, replay, protected):
    state = load_json(state_ref, protected)
    names = state["inputNames"]
    check(len(names) == 58 and set(FIELDS).issubset(names), "EXPECTED_FROZEN_58_INPUT_SYSTEM")
    actual = record(model_ref["path"])
    check(all(actual[k] == model_ref[k] for k in ("sha256", "byteCount")), "SAVED_MODEL_CHANGED")
    protected[actual["path"]] = actual
    # Deserialize trusted, hash-verified local estimators; never call their
    # predict/fit/state/feature methods (current repair code may be changing).
    model = joblib.load(actual["path"])
    core = model.core
    supported = np.flatnonzero(core.supported_columns)
    locations = {names[index]: position for position, index in enumerate(supported)}
    train_ids = state["leaguePrior"]["training_ids"]
    training = replay.loc[train_ids]
    check(len(training) == state["trainingRows"], "TRAINING_FLAG_REPLAY_IDS_DIFFER")
    coefficients = []
    for field in FIELDS:
        index, position = names.index(field), locations[field]
        center, scale = float(core.centers[index]), float(core.scales[index])
        item = {"feature": field, "center": center, "scale": scale, "trainingRows": len(training),
                "homeCoefficient": float(core.ridge.coef_[0, position]), "awayCoefficient": float(core.ridge.coef_[1, position]),
                "homeMissingIndicatorCoefficient": float(core.ridge.coef_[0, len(supported) + position]),
                "awayMissingIndicatorCoefficient": float(core.ridge.coef_[1, len(supported) + position])}
        if field in GAP_FIELDS:
            raw = training[field].to_numpy(float)
            expected_scale = float(np.sqrt(max(np.var(raw), 1e-12)))
            check(abs(raw.mean() - center) < 1e-12 and abs(expected_scale - scale) < 1e-12,
                  "REPLAY_TRAINING_FLAG_MOMENTS_DIFFER:" + tag + ":" + field)
            item["replayedTrainingValues"] = summary(raw)
            item["valueCounts"] = {str(key): int(value) for key, value in training[field].value_counts().sort_index().items()}
        else:
            item["trainingNonzeroCount"] = None
            item["trainingCountLimitation"] = "Full QB training states not saved; moments/coefficients are saved, but nonzero counts are not inferred from them."
        coefficients.append(item)
    report = {"system": tag, "lagHours": state["lagHours"], "trainingRows": len(training),
              "trainingEnd": state["trainingEnd"], "coefficients": coefficients,
              "savedHgbStructure": tree_usage(core, names), "validation": None}
    if validation_ref is None:
        return report, [], []
    columns = ["canonical_game_id", "season", "week", "game_date", *names]
    columns += [f"{side}_points_{kind}_season_to_date__posterior_sd" for side in ("home", "away") for kind in ("for", "against")]
    values = parquet(validation_ref, columns, protected)
    expected = replay.loc[values.canonical_game_id]
    for field in GAP_FIELDS:
        check(np.array_equal(values[field].to_numpy(), expected[field].to_numpy()), "VALIDATION_FLAG_REPLAY_DIFFERS:" + field)
    x = values[names].to_numpy(float)
    finite = np.isfinite(x)
    z = np.zeros_like(x)
    np.subtract(x, core.centers, out=z, where=finite)
    z /= core.scales
    design = np.column_stack((z[:, supported], (~finite)[:, supported].astype(float)))
    all_linear_terms = design @ core.ridge.coef_.T
    terms, field_summaries = [], []
    joint_removed_terms = np.zeros((len(values), 2))
    for field in FIELDS:
        index, position = names.index(field), locations[field]
        effects = z[:, index, None] * core.ridge.coef_[:, position]
        missing_effects = (~finite[:, index, None]).astype(float) * core.ridge.coef_[:, len(supported) + position]
        joint_removed_terms += effects + missing_effects
        field_summaries.append({"feature": field, "rawValues": summary(x[:, index]), "standardizedValues": summary(z[:, index]),
                               "homeLinearContribution": summary(effects[:, 0]), "awayLinearContribution": summary(effects[:, 1]),
                               "marginLinearContribution": summary(effects[:, 0] - effects[:, 1]),
                               "missingIndicatorRows": int((~finite[:, index]).sum())})
        for i, row in enumerate(values.itertuples(index=False)):
            terms.append({"system": tag, "lagHours": state["lagHours"], "canonical_game_id": row.canonical_game_id,
                          "season": int(row.season), "week": int(row.week), "evidenceClass": EVIDENCE, "feature": field,
                          "rawValue": float(x[i, index]), "trainingCenter": float(core.centers[index]), "trainingScale": float(core.scales[index]),
                          "standardizedValue": float(z[i, index]), "homeLinearContribution": float(effects[i, 0]),
                          "awayLinearContribution": float(effects[i, 1]), "marginLinearContribution": float(effects[i, 0] - effects[i, 1]),
                          "homeMissingIndicatorContribution": float(missing_effects[i, 0]), "awayMissingIndicatorContribution": float(missing_effects[i, 1])})
    gaps = values[["home_missing_season_uncertainty", "away_missing_season_uncertainty"]].to_numpy(float)
    multiplier = 1 + np.square(gaps).mean(axis=1)
    unknown = np.isnan(x).mean(axis=1)
    base = np.column_stack([np.square(values[[f"{side}_points_for_season_to_date__posterior_sd",
        f"{opponent}_points_against_season_to_date__posterior_sd"]].to_numpy(float)).sum(axis=1) / 4
        for side, opponent in (("home", "away"), ("away", "home"))])
    variance = base * multiplier[:, None] + unknown[:, None] * np.maximum(base, 1)
    variance_rows, variance_summary = [], []
    for component, bank in model.residual_banks.items():
        bank_variance = np.var(np.column_stack((bank.home, bank.away)), axis=0)
        reference = np.asarray(model.reference_uncertainty)
        aleatoric = np.maximum(bank_variance - reference, 1.0)
        scale = np.sqrt((aleatoric + variance) / (aleatoric + reference))
        variance_summary.append({"component": component, "residualBankVariance": bank_variance.tolist(),
            "referenceScoreMeanVariance": reference.tolist(), "oldAleatoricVariance": aleatoric.tolist(),
            "onePointVarianceFloorActive": (bank_variance - reference < 1).tolist(),
            "homeResidualScale": summary(scale[:, 0]), "awayResidualScale": summary(scale[:, 1])})
        for i, row in enumerate(values.itertuples(index=False)):
            variance_rows.append({"system": tag, "component": component, "lagHours": state["lagHours"],
                "canonical_game_id": row.canonical_game_id, "season": int(row.season), "week": int(row.week), "evidenceClass": EVIDENCE,
                "missingSeasonMultiplier": float(multiplier[i]), "unknownInputFraction": float(unknown[i]),
                "homeBaseScoreVariance": float(base[i, 0]), "awayBaseScoreVariance": float(base[i, 1]),
                "homeTotalScoreVariance": float(variance[i, 0]), "awayTotalScoreVariance": float(variance[i, 1]),
                "homeOldResidualScale": float(scale[i, 0]), "awayOldResidualScale": float(scale[i, 1])})
    report["validation"] = {"games": len(values), "fieldSummaries": field_summaries,
        "combinedSixFieldHomeLinearContribution": summary(joint_removed_terms[:, 0]),
        "combinedSixFieldAwayLinearContribution": summary(joint_removed_terms[:, 1]),
        "combinedSixFieldMarginLinearContribution": summary(joint_removed_terms[:, 0] - joint_removed_terms[:, 1]),
        "allLinearTermFinite": bool(np.isfinite(all_linear_terms).all()),
        "missingSeasonInflationMultiplier": summary(multiplier), "unknownInputFraction": summary(unknown),
        "oldVarianceHeuristic": variance_summary}
    return report, terms, variance_rows


def run(study, current_diagnostic):
    started = time.perf_counter()
    protected = {}
    study_ref = record(study)
    result = load_json(study_ref, protected)
    check(result.get("contract") == "NFL_CURRENT_STATE_RECONSTRUCTED_STUDY_RESULT_V2" and result.get("finalOotAccessed") is False,
          "COMPLETED_DEVELOPMENT_PREDECESSOR_REQUIRED")
    run_path = Path(study).resolve().parent
    game_columns = ["canonical_game_id", "season", "week", "game_date", "canonical_home_team_id", "canonical_away_team_id", "slate_cutoff_utc"]
    games = parquet(saved_ref(result, run_path / "development-cohort.parquet"), game_columns, protected)
    points = parquet(saved_ref(result, run_path / "sufficient-statistics-team.parquet"),
        ["canonical_game_id", "season", "team_id", "available_48h_utc", "available_72h_utc"], protected, filters=[("metric", "==", "points_for")])
    check(len(games) == result["developmentGames"] and len(points) == 2 * len(games), "SAVED_COHORT_COUNTS_DIFFER")
    replays = {lag: replay_gap_metadata(games, points, lag) for lag in (48, 72)}
    trigger_rows = []
    for lag, replay in replays.items():
        selected = replay.loc[replay.season.ge(2000) & ((replay.home_missing_season_uncertainty > 0) | (replay.away_missing_season_uncertainty > 0))]
        trigger_rows.extend(selected.astype(object).where(pd.notna(selected), None).to_dict("records"))
    systems, linear, variances = [], [], []
    for ref in result["fittedModels"]:
        tag = f"lag{ref['lagHours']}-season{ref['validationSeason']}"
        folder = run_path / tag
        report, terms, variance_rows = analyze_system(tag, ref, saved_ref(result, folder / "fitted-state.json"),
            saved_ref(result, folder / "feature-states.parquet"), result, run_path, replays[ref["lagHours"]], protected)
        systems.append(report); linear.extend(terms); variances.extend(variance_rows)
    final_folder = Path(result["finalModel"]["path"]).parent
    final, _, _ = analyze_system("final-through2024-lag48", result["finalModel"], saved_ref(result, final_folder / "fitted-state.json"),
        None, result, run_path, replays[48], protected)
    current_ref = record(current_diagnostic)
    current = load_json(current_ref, protected)
    check(current["study"] == study_ref and current["model"] == result["finalModel"], "CURRENT_DIAGNOSIS_AUTHORITY_DIFFERS")
    current_terms = [{"eventId": row["eventId"], "missingInterveningSeasons": row["missingInterveningSeasons"],
                      "terms": [term for term in row["terms"] if term["feature"] in FIELDS]} for row in current["events"]]
    # All old files must remain byte-for-byte unchanged before outputs publish.
    check(all(record(path) == ref for path, ref in protected.items()), "PREDECESSOR_MUTATED_DURING_DIAGNOSIS")
    tables = {}
    for name, rows in (("validation-linear-contributions.parquet", linear), ("validation-old-variance-components.parquet", variances)):
        buffer = io.BytesIO(); pd.DataFrame(rows).to_parquet(buffer, index=False)
        tables[name] = put(name, buffer.getvalue())
    diagnostic = {"contract": "NFL_UNCERTAINTY_REPAIR_PREDECESSOR_IMPACT_TRACE_V1", "status": "RESEARCH_DIAGNOSTIC_ONLY",
        "evidenceClass": "OBSERVED_AS_OF", "trainingAndValidationEvidenceClass": EVIDENCE,
        "createdAtUtc": datetime.now(timezone.utc).isoformat(), "sourceStudy": study_ref, "sourceCurrentDiagnostic": current_ref,
        "diagnosticCode": record(__file__), "uncertaintyOnlyMeanFields": list(FIELDS), "triggeringTrainingRows": trigger_rows,
        "gapReplayMethod": "Exact saved formula over prior eligible points_for team-game rows: strict availableAt<whole-slate cutoff, no target/same-slate IDs, Week1 excludes same season; no team history uses targetSeason-1999; missing=max(0,gap-1). No full treatment reconstruction.",
        "trainingFlagMomentsAndValidationFlagsVerified": True, "outerSystems": systems, "finalSystem": final,
        "currentSavedLinearTerms": current_terms, "currentMissingSeasonDiagnosis": current["summary"],
        "historicalImpactInterpretation": [
            "Raw missing-season flag effects must be distinguished from centered linear terms: even raw zero can carry a nonzero standardized contribution when training center is nonzero.",
            "These are exact additive saved Ridge terms, not causal effects or the effect of refitting without the fields. Correlated predictors, intercepts and residual target construction also change under a repair.",
            "All learned outer systems and the final system consume the removed fields; HIERARCHICAL score means, downstream residual training targets/banks, and ENSEMBLE weights/laws cannot be assumed unaffected just because validation missing-season counts are zero.",
            "DYNAMIC scoring-only means do not use these six fields. Its old distribution still uses the shared score-variance heuristic; a new fitted variance law requires separate validation.",
            "Old variance is (own points-for posterior SD squared + opponent points-against posterior SD squared)/4, multiplied by 1+mean(two missing-season counts squared), plus missing-input fraction times max(base,1). QB posterior SD and prior_season_gap are not separately propagated variance terms; they only enter the old means and potentially the missing-input fraction.",
            "Old residual scaling subtracts a saved inner-holdout reference score variance from empirical paired residual variance, floors at1, then scales by the square-root total/reference ratio. This is a heuristic, not learned or calibrated uncertainty.",
            "Other per-rate posterior_sd metadata were not old mean inputs. No tree counterfactual prediction, regenerated forecast, outcome evaluation, fit or calibrator fit is performed here."],
        "necessaryRepairScope": {"outerSystems": len(systems), "finalSystems": 1,
            "affectedLearnedComponents": ["HIERARCHICAL", "RESIDUAL", "ENSEMBLE"],
            "dynamicMeanRefitRequiredBySixFieldRemoval": False,
            "uncertaintyLawValidationRequiredForAllDistributionComponents": True,
            "scopeMeaning": "Scope supported by saved dependencies, not authorization or a new fit budget."},
        "tables": tables, "exactLinearContributionRows": len(linear), "oldVarianceRows": len(variances),
        "protectedInputs": list(protected.values()), "allProtectedInputsUnchanged": True,
        "modelFits": 0, "modelPredictCalls": 0, "newForecastInference": 0, "rawSourceReads": 0,
        "sealed2025Read": False, "providerCalls": 0, "aispAccess": False, "runtimeSeconds": time.perf_counter() - started}
    ref = put("diagnostic.json", canonical(diagnostic))
    print(json.dumps({"diagnostic": ref, "triggeringTrainingRows": trigger_rows, "outerSystems": len(systems),
                      "linearRows": len(linear), "varianceRows": len(variances), "runtimeSeconds": diagnostic["runtimeSeconds"]}, indent=2))
    return ref


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--current-diagnostic", type=Path, required=True)
    args = parser.parse_args()
    run(args.study, args.current_diagnostic)
