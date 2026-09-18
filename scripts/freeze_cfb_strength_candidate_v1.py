"""One-time private final fit of the already frozen CFB B/lambda4 recipe.

No historical experiment is rerun. Only retained through-2025 features and
chronological B OOF predictions are consumed; season-2026 outcomes are excluded
at parquet materialization. Existing research artifacts are read-only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys

import joblib
import numpy as np
import pandas as pd
import pyarrow
import scipy
import sklearn
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_cfb_gen1 import pipeline as baseline
from server.sports_cfb_gen1 import opponent_strength as strength

STUDY = Path(r"C:\Users\james\asp-model-studio\outputs\cfb-opponent-adjusted-strength-v1")
DEFAULT_OUTPUT = Path(r"C:\Users\james\asp-model-studio\outputs\cfb-strength-prospective-v1")
EXTRA_FEATURES = ["strength_pred_margin", "strength_pred_total"]
SCHEMA = "CFB_STRENGTH_PROSPECTIVE_CANDIDATE_V1"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def binding(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def checked_binding(reference):
    actual = binding(reference["path"])
    if actual["sha256"] != reference["sha256"] or actual["bytes"] != reference["bytes"]:
        raise ValueError(f"Physical binding changed: {reference['path']}")
    return actual


def exclusive_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(canonical(value))
    return binding(path)


def immutable_bytes(root, raw, filename):
    digest = hashlib.sha256(raw).hexdigest()
    path = Path(root) / "sha256" / digest / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
    return binding(path)


def verify_source_compatibility(study, implementation):
    result = []
    for relative in ("server/sports_cfb_gen1/pipeline.py", "server/sports_cfb_gen1/opponent_strength.py"):
        old = next(row for row in implementation["sources"] if row["relativePath"] == relative)
        checked_binding(old)
        current = ROOT / relative
        old_bytes, current_bytes = Path(old["path"]).read_bytes(), current.read_bytes()
        if old_bytes.replace(b"\r\n", b"\n") != current_bytes.replace(b"\r\n", b"\n"):
            raise ValueError(f"Numerical implementation changed: {relative}")
        result.append({"relativePath": relative, "historical": old, "current": binding(current),
                       "byteIdentical": old_bytes == current_bytes, "normalizedTextIdentical": True})
    return result


def load_inputs(study=STUDY):
    study = Path(study)
    package = json.loads((study / "PACKAGE_RECEIPT.json").read_text(encoding="utf-8"))
    index_ref = checked_binding(package["index"])
    index = json.loads(Path(index_ref["path"]).read_text(encoding="utf-8"))
    lookup = {row["relativePath"].replace("\\", "/"): row for row in index["files"]}
    names = ["DESIGN.json", "FROZEN_SELECTION.json", "IMPLEMENTATION_BINDING.json",
             "data/baseline-features-through-2025.parquet", "features/B_lambda4-through-2025.parquet",
             "COMMON_POPULATION_PREDICTIONS.parquet"]
    refs = {name: checked_binding(lookup[name]) for name in names}
    design = json.loads(Path(refs["DESIGN.json"]["path"]).read_text(encoding="utf-8"))
    frozen = json.loads(Path(refs["FROZEN_SELECTION.json"]["path"]).read_text(encoding="utf-8"))
    if frozen["selectedArm"] != "B" or frozen["lambdaPrior"] != 4 or frozen["maximumOutcomeSeasonRead"] != 2022:
        raise ValueError("Historical Development freeze does not match B/lambda4")
    implementation = json.loads(Path(refs["IMPLEMENTATION_BINDING.json"]["path"]).read_text(encoding="utf-8"))
    compatibility = verify_source_compatibility(study, implementation)
    source = checked_binding(design["sourcePopulation"])
    # Physical integrity checks do not materialize excluded season-2026 rows.
    historical = pd.read_parquet(source["path"], filters=[("season", "<=", 2025)])
    features = pd.read_parquet(refs["data/baseline-features-through-2025.parquet"]["path"], filters=[("season", "<=", 2025)])
    sidecar = pd.read_parquet(refs["features/B_lambda4-through-2025.parquet"]["path"])
    oof = pd.read_parquet(refs["COMMON_POPULATION_PREDICTIONS.parquet"]["path"], filters=[("season", "<=", 2025), ("arm", "==", "B")])
    refs.update({"historicalAdmittedSource": source, "historicalArtifactIndex": index_ref,
                 "historicalPackageReceipt": binding(study / "PACKAGE_RECEIPT.json")})
    return features, sidecar, oof, historical, refs, compatibility


def _unique(frame, label):
    if frame.game_id.isna().any() or frame.game_id.duplicated().any():
        raise ValueError(f"Nonunique or missing game identity: {label}")


def prepare_frames(features, sidecar, oof, historical):
    for label, frame in (("features", features), ("oof", oof), ("historical", historical)):
        if frame.season.isna().any() or frame.season.gt(2025).any():
            raise ValueError(f"Season-2026 or missing-season evidence prohibited: {label}")
        _unique(frame, label)
    _unique(sidecar, "sidecar")
    train = features.loc[features.primary & features.is_final].copy()
    history = historical.loc[historical.primary & historical.is_final].sort_values(["scheduled_at", "game_id"]).reset_index(drop=True)
    if train.empty or not set(train.game_id) == set(history.game_id) == set(sidecar.game_id):
        raise ValueError("Final-fit primary population mismatch")
    if train.season.min() != 2014 or train.season.max() != 2025:
        raise ValueError("Expected the complete admitted 2014–2025 primary training range")
    if not np.isfinite(train[["home_score", "away_score", "home_margin", "total_points"]]).all().all():
        raise ValueError("Training scores and targets must be finite")
    train = train.merge(sidecar[["game_id", "origin", "history_latest_kickoff", *EXTRA_FEATURES]], on="game_id", validate="one_to_one")
    if not np.isfinite(train[EXTRA_FEATURES]).all().all():
        raise ValueError("Missing strength features")
    if not train.origin.eq(train.research_origin).all():
        raise ValueError("Strength and baseline origins differ")
    for key in ("history_latest_kickoff", "feature_max_source_game_date"):
        if not (train[key].isna() | train[key].le(train.research_origin - pd.Timedelta(hours=48))).all():
            raise ValueError("Historical feature reconstruction chronology violation")
    identity = ["season", "home_id", "away_id", "home_score", "away_score", "neutral_site"]
    h = history.set_index("game_id")
    if not np.array_equal(train.set_index("game_id")[identity].to_numpy(), h.loc[train.game_id, identity].to_numpy()):
        raise ValueError("Training features do not match admitted score identity/orientation")
    if oof.empty or len(oof) < 500 or not oof.arm.eq("B").all() or not oof.primary.all() or not oof.is_final.all():
        raise ValueError("At least 500 retained primary B OOF donors required")
    if set(oof.season) != set(range(2016, 2026)) or not oof.trainingThroughSeason.lt(oof.season).all():
        raise ValueError("OOF training chronology or coverage mismatch")
    if not set(oof.game_id).issubset(set(history.game_id)):
        raise ValueError("OOF donor is outside admitted primary history")
    if not np.array_equal(oof.set_index("game_id")[identity].to_numpy(), h.loc[oof.game_id, identity].to_numpy()):
        raise ValueError("OOF donor score identity/orientation mismatch")
    if not np.isfinite(oof[["pred_home", "pred_away", "pred_margin", "pred_total", "home_win"]]).all().all():
        raise ValueError("Nonfinite OOF predictions or outcome")
    if not np.allclose(oof.pred_home + oof.pred_away, oof.pred_total, rtol=0, atol=1e-10) or not np.allclose(oof.pred_home - oof.pred_away, oof.pred_margin, rtol=0, atol=1e-10):
        raise ValueError("OOF paired-score prediction identity mismatch")
    donors = oof.sort_values(["scheduled_at", "game_id"]).reset_index(drop=True).copy()
    if donors.home_win.nunique() != 2:
        raise ValueError("OOF calibration requires both winner classes")
    columns = list(baseline.FEATURE_COLUMNS) + EXTRA_FEATURES
    if len(columns) != 37:
        raise ValueError("Fixed 37-feature recipe changed")
    return train, donors, history, columns


def fixed_recipe():
    if strength.PRIOR_DECAY != 2 / 3 or strength.DYNAMIC_SUPPORT_SCALE != 4:
        raise ValueError("Strength pooling law changed")
    return {"arm": "B", "lambdaPrior": 4.0, "dynamic": True, "opponentAdjusted": True,
            "priorTransfer": strength.PRIOR_DECAY, "dynamicSupportScale": strength.DYNAMIC_SUPPORT_SCALE,
            "globalMeanPrior": strength.DEFAULT_MU, "venuePrior": strength.DEFAULT_VENUE,
            "globalMeanPrecision": strength.MU_PRIOR_PRECISION, "venuePrecision": strength.VENUE_PRIOR_PRECISION,
            "ridgeAlpha": 100.0, "preprocessing": ["SimpleImputer(strategy=median)", "StandardScaler"],
            "strengthFeatures": EXTRA_FEATURES, "featureCount": 37, "maximumTrainingSeason": 2025,
            "calibration": {"kind": "LogisticRegression", "C": 1.0, "solver": "lbfgs", "randomState": baseline.SEED, "source": "RETAINED_NESTED_B_OOF_2016_2025"},
            "residualLaw": "UNCHANGED_PAIRED_CHRONOLOGICAL_B_OOF_TEAM_SCORE_RESIDUALS",
            "residualDonorHyperparameters": "ACTUAL_NESTED_HISTORICAL_B_CHOICES_PRESERVED",
            "simulationFunction": "server.sports_cfb_gen1.pipeline.simulate_paired_residuals",
            "simulationModelLabel": "ridge_alpha100", "simulationSeed": baseline.SEED, "drawCount": 10000,
            "scoreTreatment": "NONNEGATIVE_FLOOR_STOCHASTIC_ROUNDING_TIE_CONDITIONING_UNCHANGED",
            "historicalFeatureEvidence": "CLASS_A_RECONSTRUCTED_48_HOUR_EMBARGO_NOT_CERTIFIED_AVAILABILITY",
            "hyperparametersMayUpdate": False, "fittedRegressionMayUpdate": False, "residualDonorsMayUpdate": False,
            "currentSeasonTeamStrengthMayUpdate": "ONLY_FROM_SEPARATELY_ADMITTED_COMPLETION_AWARE_PREORIGIN_HISTORY",
            "productionAuthority": False, "consumerAuthority": False, "providerCalls": 0}


def fit_candidate(train, donors, history, columns, inputs, compatibility):
    with threadpool_limits(limits=1):
        models = {key: baseline.make_model("ridge", {"alpha": 100.0}).fit(train[columns], train[label])
                  for key, label in (("margin", "home_margin"), ("total", "total_points"))}
        calibrator = LogisticRegression(C=1.0, solver="lbfgs", random_state=baseline.SEED).fit(
            donors[["pred_margin"]].to_numpy(), donors.home_win.astype(int).to_numpy())
    keep = ["game_id", "season", "week", "scheduled_at", "home_id", "away_id", "home_score", "away_score", "home_win",
            "pred_margin", "pred_total", "pred_home", "pred_away", "lambda_prior", "trainingThroughSeason"]
    residuals = donors[keep].copy()
    for side in ("home", "away"):
        residuals[f"ridge_alpha100_pred_{side}"] = residuals[f"pred_{side}"]
        residuals[f"{side}Residual"] = residuals[f"{side}_score"] - residuals[f"pred_{side}"]
    return {"schema": SCHEMA, "candidateLabel": "B_LAMBDA4_ALPHA100_FROZEN_THROUGH_2025", "models": models,
            "calibrator": calibrator, "columns": columns, "residualDonors": residuals,
            "historicalPrimary": history, "fixedRecipe": fixed_recipe(), "inputBindings": inputs,
            "numericalSourceCompatibility": compatibility,
            "trainingGameIds": train.game_id.astype(int).tolist(),
            "calibrationGameIds": residuals.game_id.astype(int).tolist(),
            "historicalResearchRerun": False, "season2026OutcomesMaterialized": 0,
            "researchOnly": True, "productionChanged": False}


def freeze(output=DEFAULT_OUTPUT, study=STUDY):
    output, study = Path(output).resolve(), Path(study).resolve()
    if output == study or study in output.parents:
        raise ValueError("Original historical study is immutable")
    if (output / "FROZEN_CANDIDATE.json").exists() or (output / "FINAL_FIT_STARTED.json").exists():
        raise FileExistsError("Final fit already started or completed; refitting this output is forbidden")
    inputs = load_inputs(study)
    features, sidecar, oof, historical, refs, compatibility = inputs
    train, donors, history, columns = prepare_frames(features, sidecar, oof, historical)
    recipe = fixed_recipe()
    environment = {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
                   "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__,
                   "sklearn": sklearn.__version__, "joblib": joblib.__version__, "pyarrow": pyarrow.__version__, "fitThreadLimit": 1}
    code = binding(__file__)
    started = utc_now()
    exclusive_json(output / "FINAL_FIT_STARTED.json", {"schema": "CFB_STRENGTH_SINGLE_FINAL_FIT_V1", "startedAtUtc": started,
                   "fitterCode": code, "fixedRecipe": recipe, "inputBindings": refs, "environment": environment})
    artifact = fit_candidate(train, donors, history, columns, refs, compatibility)
    completed = utc_now()
    artifact["finalFitCompletedAtUtc"] = completed
    artifact["environment"] = environment
    artifact["fitterCode"] = code
    buffer = io.BytesIO()
    joblib.dump(artifact, buffer, compress=3)
    candidate_ref = immutable_bytes(output / "candidate-artifacts", buffer.getvalue(), "candidate.joblib")
    # Round-trip verification evaluates a few feature rows, never historical model quality.
    restored = joblib.load(candidate_ref["path"])
    sample = train.iloc[[0, len(train) // 2, len(train) - 1]][columns]
    for key in ("margin", "total"):
        if not np.array_equal(artifact["models"][key].predict(sample), restored["models"][key].predict(sample)):
            raise ValueError("Serialized point predictions changed")
    if not np.array_equal(calibrated := artifact["calibrator"].predict_proba(donors[["pred_margin"]].iloc[:3].to_numpy()), restored["calibrator"].predict_proba(donors[["pred_margin"]].iloc[:3].to_numpy())):
        raise ValueError("Serialized calibration changed")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    manifest = {"schema": "CFB_STRENGTH_FROZEN_CANDIDATE_MANIFEST_V1", "finalFitStartedAtUtc": started,
                "finalFitCompletedAtUtc": completed, "candidate": candidate_ref, "fixedRecipe": recipe, "columns": columns,
                "trainingGames": len(train), "trainingSeasons": sorted(train.season.astype(int).unique().tolist()),
                "residualDonorGames": len(donors), "residualDonorSeasons": sorted(donors.season.astype(int).unique().tolist()),
                "residualDonorGameIdsSha256": hashlib.sha256(canonical(donors.game_id.astype(int).tolist())).hexdigest(),
                "nestedDonorLambdasBySeason": {str(int(year)): sorted(rows.lambda_prior.unique().tolist()) for year, rows in donors.groupby("season")},
                "historicalPrimaryGames": len(history), "inputBindings": refs, "numericalSourceCompatibility": compatibility,
                "fitterCode": code, "sourceGitHeadAtFinalFit": head, "environment": environment,
                "serializationRoundTripExact": True, "historicalResearchRerun": False,
                "season2026OutcomesMaterialized": 0, "providerCalls": 0, "productionChanged": False,
                "scope": "PRIVATE_PROSPECTIVE_RESEARCH_ONLY_NO_PUBLICATION_OR_CONSUMER_AUTHORITY"}
    manifest_ref = immutable_bytes(output / "candidate-manifests", canonical(manifest), "manifest.json")
    pointer = {"schema": "CFB_STRENGTH_FROZEN_CANDIDATE_POINTER_V1", "finalFitCompletedAtUtc": completed,
               "manifest": manifest_ref, "candidate": candidate_ref, "fixedRecipe": recipe, "researchOnly": True}
    exclusive_json(output / "FROZEN_CANDIDATE.json", pointer)
    return pointer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(freeze(args.output), indent=2))


if __name__ == "__main__":
    main()
