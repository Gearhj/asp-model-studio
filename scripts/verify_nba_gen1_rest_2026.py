"""Focused saved-artifact checks; no fitting, outcome scoring or simulation."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
import sklearn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_nba_gen1_rest_2026 import verify_references
from server.sports_nba_gen1.authority import reference, verified_bytes, json_bytes
from server.sports_nba_gen1.recent_features import FEATURE_COLUMNS
from server.sports_nba_gen1.recent_models import _array_hash
from server.sports_nba_gen1.models import _targets
from server.sports_nba_gen1.recent_study import now, save
from server.sports_nba_gen1.rest_support import CHANGED_COLUMNS, learn_rest_support, transform_rest


def require(condition, description):
    if not condition:
        raise ValueError(description)


def load(path):
    return json.loads(Path(path).read_bytes())


def array_state(array):
    values = np.asarray(array, dtype=float)
    return {"shape": list(values.shape), "canonicalFloat64Sha256": _array_hash(values),
            "values": [float(x) if np.isfinite(x) else None for x in values.reshape(-1)],
            "nonfiniteEncoding": "null in presentation; canonical IEEE float64 values remain hash-bound"}


def preprocessor_state(model):
    if model.family == "elo":
        state = {"family": "elo", "fittedMedianEloDifference": model.estimators["elo_difference_median"],
                 "featureNames": list(model.feature_names), "scaler": None}
    else:
        pipeline = model.estimators["margin_total"]
        imputer, scaler = pipeline.named_steps["imputer"], pipeline.named_steps["scaler"]
        state = {"featureNames": list(model.feature_names),
                 "imputer": {"class": type(imputer).__name__, "strategy": imputer.strategy,
                             "keepEmptyFeatures": imputer.keep_empty_features,
                             "statistics": array_state(imputer.statistics_)},
                 "scaler": {"class": type(scaler).__name__, "withMean": scaler.with_mean,
                            "withStd": scaler.with_std, "trainingSamples": int(scaler.n_samples_seen_),
                            "mean": array_state(scaler.mean_), "scale": array_state(scaler.scale_),
                            "variance": array_state(scaler.var_)}}
    raw = json_bytes(state)
    return {"canonicalStateSha256": hashlib.sha256(raw).hexdigest(), "canonicalStateBytes": len(raw),
            "hashDefinition": "SHA256 of canonical JSON state produced by authority.json_bytes; fitted objects remain inside the bound model artifact.",
            "state": state}


def serialization_check(model, example):
    before = model.predict(example)
    buffer = BytesIO()
    joblib.dump(model, buffer, compress=0)
    raw = buffer.getvalue()
    buffer.seek(0)
    restored = joblib.load(buffer)
    after = restored.predict(example)
    require(np.array_equal(before, after), "Saved model serialization changes point prediction")
    return {"oneInputGameId": str(example.game_id.iloc[0]), "exactHomeAwayReproduction": True,
            "maximumAbsoluteDifference": float(abs(after - before).max()),
            "temporarySerializationSha256": hashlib.sha256(raw).hexdigest(), "temporarySerializationBytes": len(raw),
            "semantics": "Existing input used solely to verify serialization; no forecast publication or outcome assessment.",
            "temporaryBytesRetained": False}


def main_verify(root):
    root = Path(root).resolve()
    output = root / "verification-2026.json"
    if output.exists():
        prior = load(output)
        verify_references(prior["bindings"])
        return {"status": "REUSED_SAVED_FOCUSED_VERIFICATION", "receipt": reference(output)}
    files = {"freeze": root / "assessment-2026-freeze.json", "assessment": root / "assessment-2026/receipt.json",
             "reconciliation": root / "reconciliation-2026.json", "cohort": root / "cohort-2026.json",
             "currentResearch": root / "current-research/receipt.json"}
    bindings = {name: reference(path) for name, path in files.items()}
    values = {name: json.loads(verified_bytes(bound)) for name, bound in bindings.items()}
    for value in values.values():
        verify_references(value)
    frozen, assessment, reconciliation, cohort, current = (values[name] for name in files)
    require(assessment["freeze"] == bindings["freeze"] == reconciliation["modelFreeze"], "Model freeze lineage differs")
    require(current["completedAssessment"] == bindings["assessment"], "Current refit predates a different assessment")
    features = pd.read_parquet(assessment["artifacts"]["features"]["path"])
    prior_features = pd.read_parquet(frozen["oldFeatures"]["path"])
    predictions = pd.read_parquet(assessment["artifacts"]["predictions"]["path"], columns=[
        "game_id", "model_id", "expected_home_score", "expected_away_score", "p_home_win", "p_away_win", "p_tie"])
    target = features[(features.season_end == 2026) & features.target_eligible].copy()
    require(len(target) == 1225 and not target.game_id.duplicated().any(), "Exactly 1,225 oriented target rows required")
    require(not target.neutral_site.any(), "Neutral target entered batch verification")
    expected_metadata = pd.DataFrame(cohort["admittedGames"]).set_index("game_id").sort_index()
    source_metadata = pd.read_parquet(reconciliation["gamesArtifact"]["path"], columns=[
        "game_id", "source_game_id", "game_date", "season_end", "home_team_id", "away_team_id",
        "home_team_code", "away_team_code", "neutral_site", "orientation", "target_eligible"])
    actual_metadata = source_metadata.set_index("game_id").sort_index()
    require(actual_metadata.index.equals(expected_metadata.index), "Normalized source IDs differ from the frozen cohort")
    for column in actual_metadata:
        require(np.array_equal(actual_metadata[column].to_numpy(), expected_metadata[column].to_numpy()),
                f"Source {column} differs from its frozen metadata")
    require(set(target.game_id) == set(source_metadata.loc[source_metadata.target_eligible, "game_id"]), "Target game identities differ")
    models_report = {}
    untouched = [name for name in FEATURE_COLUMNS if name not in CHANGED_COLUMNS]
    require(len(untouched) == 71, "Unexpected rest-treatment scope")
    old_train = prior_features[prior_features.target_eligible].copy()
    expected_support = learn_rest_support(old_train)
    for name, bound in frozen["models"].items():
        model = joblib.load(bound["artifact"]["path"])
        require(list(model.training_game_ids) == old_train.game_id.astype(str).tolist(), "Frozen training IDs differ")
        require(model.training_identity_sha256 == bound["trainingIdentitySha256"], "Fitted identity differs from manifest")
        stored = predictions[predictions.model_id == name].set_index("game_id").loc[target.game_id]
        require(len(stored) == 1225 and not stored.index.duplicated().any(), "Frozen model lacks the exact common target batch")
        replay = model.predict(target)
        expected = stored[["expected_home_score", "expected_away_score"]].to_numpy(float)
        require(np.array_equal(replay, expected), f"Frozen {name} numerical predictions changed")
        mt = model.predict_margin_total(target)
        coherence = max(float(abs(replay[:, 0] - replay[:, 1] - mt[:, 0]).max()),
                        float(abs(replay.sum(axis=1) - mt[:, 1]).max()))
        require(coherence < 1e-10, "Point margin/total expectations do not reconcile")
        require(np.array_equal(stored.p_home_win.to_numpy(), target.elo_home_win_probability.to_numpy()), "Elo channel changed")
        require(np.array_equal(stored.p_away_win.to_numpy(), 1 - stored.p_home_win.to_numpy()), "Away probability differs from complement")
        require((stored.p_tie == 0).all(), "NBA final tie probability is nonzero")
        require(((stored.p_home_win > 0) & (stored.p_home_win < 1)).all(), "Winner probability outside valid range")
        if name == "ridge_a100_rest":
            require(model.rest_support == expected_support, "Rest bound used data outside frozen training support")
            treated, audit = transform_rest(target, model.rest_support)
            require(np.array_equal(treated[untouched].to_numpy(float), target[untouched].to_numpy(float), equal_nan=True),
                    "Rest treatment changed another numeric input")
            saved_audit = pd.read_parquet(assessment["artifacts"]["restInputAudit"]["path"]).drop(columns=["season_end"])
            pd.testing.assert_frame_equal(audit.reset_index(drop=True), saved_audit.reset_index(drop=True))
        models_report[name] = {"modelArtifact": bound["artifact"], "trainingIdentitySha256": model.training_identity_sha256,
                              "targetBatch": 1225, "exactSavedScoreReproduction": True,
                              "maximumScoreDifference": float(abs(replay - expected).max()),
                              "maximumPointCoherenceRoundingError": coherence,
                              "winnerProbabilitiesExactlyPreserved": True,
                              "preprocessor": preprocessor_state(model), "serialization": serialization_check(model, target.iloc[:1])}
    require(predictions.groupby("game_id").p_home_win.nunique().eq(1).all(), "Models use different Elo probabilities")
    require(len(predictions) == 3 * 1225, "Unexpected model/game assessment rows")
    current_train = features[features.target_eligible].copy()
    require(len(current_train) == 8177 and len(features) == 8289, "Current training/history counts differ")
    require(set(features.season_end) == set(range(2020, 2027)), "Current history seasons differ")
    current_targets, current_ids = _targets(current_train, current_train)
    current_models = {}
    for name, bound in current["models"].items():
        model = joblib.load(bound["artifact"]["path"])
        require(list(current_ids) == bound["trainingGameIds"] == list(model.training_game_ids), "Current models use different training games")
        require(model.training_identity_sha256 == bound["trainingIdentitySha256"], "Current model binding differs")
        if name == "ridge_a100_rest":
            support = learn_rest_support(current_train)
            require(support == model.rest_support, "Current rest support does not derive from its training rows")
            treated, _ = transform_rest(current_train, support)
            require(_array_hash(current_train[list(FEATURE_COLUMNS)].to_numpy(float)) == model.raw_training_feature_values_sha256,
                    "Current raw training feature values differ")
            require(_array_hash(treated[list(FEATURE_COLUMNS)].to_numpy(float)) == model.training_feature_values_sha256,
                    "Current treated training feature values differ")
            require(_array_hash(current_targets) == model.training_target_values_sha256, "Current model's fitted labels differ")
        current_models[name] = {"modelArtifact": bound["artifact"], "trainingGames": len(current_ids),
                                "trainingIdentitySha256": model.training_identity_sha256,
                                "preprocessor": preprocessor_state(model), "serialization": serialization_check(model, target.iloc[:1])}
    require(set(current_models) == {"elo", "ridge_a100_rest"}, "Unexpected current model family/configuration")
    require(current["history"]["games"] == assessment["artifacts"]["games"]
            and current["history"]["features"] == assessment["artifacts"]["features"], "Current refit history is not the assessed history")
    freeze_clock = datetime.fromisoformat(frozen["createdAtUtc"])
    conversion_completion = datetime.fromisoformat(reconciliation["createdAtUtc"])
    require(freeze_clock < conversion_completion, "Model freeze does not precede normalized-source completion")
    require(datetime.fromisoformat(cohort["createdAtUtc"]) < freeze_clock, "Identity cohort was not frozen before models")
    require(frozen["outcomes2026Accessed"] is False and cohort["outcomeColumnsLoaded"] is False, "Pre-access qualification is absent")
    adapter = verified_bytes(cohort["adapter"]).decode("utf-8")
    begin = adapter.index("def normalize_current_history(")
    require(adapter.index("freeze.get('outcomes2026Accessed')", begin) < adapter.index("source.to_table(", begin),
            "Bound adapter does not check model freeze before outcome conversion")
    report = {
        "schema": "NBA_GEN1_REST_2026_FOCUSED_ARTIFACT_VERIFICATION_V1", "createdAtUtc": now(),
        "bindings": {**bindings, "verificationScript": reference(Path(__file__))},
        "models": models_report, "cohort": {"normalizedGames": len(source_metadata), "orientedAssessmentGames": len(target),
            "neutralHistoryOnlyGames": int(source_metadata.neutral_site.sum()), "identitiesDatesTeamsOrientationExactlyBound": True,
            "original71TargetInputsExactlyPreserved": True, "restSupportRecomputedFromFrozenTrainingOnly": expected_support,
            "probabilityMassMaximumError": float(abs(predictions.p_home_win + predictions.p_away_win + predictions.p_tie - 1).max())},
        "preAccessChronology": {"cohortFrozenAtUtc": cohort["createdAtUtc"], "modelsFrozenAtUtc": frozen["createdAtUtc"],
            "normalizationCompletedAtUtc": reconciliation["createdAtUtc"], "modelFreezePrecedesNormalizationCompletion": True,
            "boundAdapterChecksFreezeBeforeReadingOutcomeColumns": True, "adapter": cohort["adapter"],
            "normalizationStartClock": None, "qualification": "A separate conversion-start timestamp was not logged. The immutable adapter checks the frozen-model receipt before selecting score columns; completion clock follows the freeze. No contemporaneous game-information claim."},
        "currentRefit": {"models": current_models, "same8177TrainingIdentities": True,
            "boundAssessedHistoryGames": 8289, "latestRecordedGameDate": str(features.game_date.max()),
            "trainingThroughSeasonEnd": 2026, "featureAndTargetValueHashesMatchFittedRestArtifact": True},
        "runtime": {"numpy": np.__version__, "pandas": pd.__version__, "scikitLearn": sklearn.__version__, "joblib": joblib.__version__},
        "scope": {"newFits": 0, "newOutcomeScoresComputed": 0, "simulationDraws": 0, "otherCohortsReassessed": 0,
            "jointDistributionValidated": False, "scoreClipping": False, "originalArtifactsEdited": False},
    }
    for value in values.values():
        verify_references(value)
    bound = save(output, report)
    return {"status": "PASSED_FOCUSED_REAL_ARTIFACT_VERIFICATION", "receipt": bound,
            "reproducedFrozenModelGameRows": 3 * len(target), "currentTrainingGames": len(current_ids)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/nba-gen1-long-gap-v1")
    args = parser.parse_args()
    print(json.dumps(main_verify(args.output), indent=2))
