"""Execute the declared, isolated A/B/C pitcher-style survival experiment.

Each stage is immutable and resumable. Training artifacts are frozen before
assessment outcome columns are loaded. No provider, scheduler, or production
publisher is invoked. This is reused Development, not prospective evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import time

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import sklearn
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_current_statcast.mlb_starter_duration_quarantine import (
    LEDGER, quarantine_ledger, final_oot_eligible_key_mask, reference,
)
from server.sports_current_statcast.mlb_pitcher_style_profiles import (
    STYLE_FEATURES, GROUPS, build_profiles,
)
from server.sports_current_statcast.mlb_pitcher_archetype_survival import (
    ArchetypeHazard, ArchetypeMembership, ARCHETYPE_FIELDS, pregame_bf_distribution,
)
from server.sports_current_statcast.mlb_starter_survival_models import (
    PREGAME_FIELDS, ENDPOINTS, losses, target_codes, duration_metrics,
)

OUT = ROOT / "outputs/mlb-pitcher-archetype-survival-v1"
DECLARATION_SHA = "21cfc3edf23278f965030b1fc9a517d6e4a82523d048de9ad5a588237cb1ba27"
DATA = ROOT / "outputs/mlb-starter-survival-hierarchical-pa-v1/duration-data/sha256/dcf22ed438a5da0d5cf34cc9f7595481973c670ada4fb3c5791a63fbed541603"
STARTS_SHA = "e330f89d180787f90bc99aa5560af9b6ae6d7c72f860bfd07222700a6c9706c6"
RISK_SHA = "48322ee4003a758b25e837ff09b9fbdc5b6295c18c75be0cbcf9acda1644d98c"
FROZEN_SHA = "f64f82b4fadf35acd3418bc298548c48bb73cf624fe8c70ba01a87c33e8d2370"
FROZEN = ROOT / "outputs/mlb-starter-survival-hierarchical-pa-v1/duration-study/objects/sha256" / FROZEN_SHA / "fitted-hazard.joblib"
IDENTITY = ["startId", "gameId", "gameDate", "pitcherId", "eligible", "split"]
MODEL_IDS = {"A": "MLB_STYLE_MATCHED_HGB_A_V1", "B": "MLB_STYLE_CONTINUOUS_HGB_B_V1", "C": "MLB_STYLE_ARCHETYPE_HGB_C_V1"}
CODE = [Path(__file__), ROOT / "server/sports_current_statcast/mlb_pitcher_style_profiles.py",
        ROOT / "server/sports_current_statcast/mlb_pitcher_archetype_survival.py"]


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    return value


def encoded(value):
    return (json.dumps(clean(value), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def save(name, data):
    digest = hashlib.sha256(data).hexdigest()
    path = OUT / "objects/sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("IMMUTABLE_RESEARCH_OBJECT_COLLISION")
    else:
        with path.open("xb") as handle:
            handle.write(data)
    return reference(path)


def pointer(name, value):
    ref = save(name + ".json", encoded(value))
    (OUT / (name + ".json")).write_bytes(encoded(ref))
    return ref


def read_ref(ref):
    if reference(ref["path"]) != ref:
        raise ValueError("RESEARCH_ARTIFACT_BYTES_DIFFER")
    return Path(ref["path"])


def read_pointer(name):
    p = OUT / (name + ".json")
    if not p.exists():
        return None
    ref = json.loads(p.read_bytes())
    return json.loads(read_ref(ref).read_bytes())


def verify_code(refs, *, stage):
    # A profile cache binds the actual builder, while later stages also bind
    # estimator/scorer code. Runner-only receipt hardening need not recompute
    # an expensive unchanged profile derivative.
    required = [CODE[1]] if stage == "profiles" else CODE
    by_path = {str(Path(r["path"]).resolve()): r for r in refs}
    for path in required:
        actual = reference(path)
        if by_path.get(str(path.resolve())) != actual:
            raise ValueError("CACHED_STAGE_CODE_CHANGED_REVIEW_REQUIRED:" + stage)


def validate_profiles(profiles, identity):
    expected = identity.loc[identity.eligible, ["startId", "gameId", "gameDate", "pitcherId"]].set_index("startId").sort_index()
    if profiles.startId.duplicated().any() or set(profiles.startId) != set(expected.index):
        raise ValueError("PROFILE_IDENTITY_SET_CHANGED")
    actual = profiles.set_index("startId").loc[expected.index, ["gameId", "gameDate", "pitcherId"]]
    if not actual.equals(expected):
        raise ValueError("PROFILE_GAME_PITCHER_DATE_BINDING_CHANGED")
    supported = profiles.loc[profiles.profileSupported.eq(True)]
    if (supported.profileLatestGameDate.isna().any()
            or (supported.profileLatestGameDate >= supported.gameDate).any()
            or (supported.profilePitchCount < 200).any()
            or (supported.profilePriorDateCount < 3).any()
            or not supported.style_throws_left.isin([0.0, 1.0]).all()):
        raise ValueError("PROFILE_PREGAME_CUTOFF_OR_SUPPORT_FAILED")
    if set(STYLE_FEATURES) - set(profiles):
        raise ValueError("PROFILE_FEATURE_SCHEMA_CHANGED")
    if not np.allclose(supported[[f"style_{g}_usage" for g in GROUPS]].sum(axis=1), 1.0, atol=1e-12):
        raise ValueError("SUPPORTED_PROFILE_USAGE_MASS_CHANGED")


def require_declaration(result, schema):
    if (result.get("schemaVersion") != schema
            or result.get("declaration") != reference(OUT / "declaration.json")):
        raise ValueError("CACHED_STAGE_DECLARATION_OR_SCHEMA_CHANGED")


def parquet(frame):
    stream = io.BytesIO()
    frame.to_parquet(stream, index=False)
    return stream.getvalue()


def fitted(model):
    stream = io.BytesIO()
    joblib.dump(model, stream, compress=3)
    return stream.getvalue()


def guard():
    declaration = OUT / "declaration.json"
    if reference(declaration)["sha256"] != DECLARATION_SHA:
        raise ValueError("PREDECLARED_EXPERIMENT_CHANGED")
    ledger = quarantine_ledger()
    if len(ledger["games"]) != 9:
        raise ValueError("ALL_NINE_PERMANENT_EXCLUSIONS_REQUIRED")
    for name, digest in (("starts.parquet", STARTS_SHA), ("risk.parquet", RISK_SHA)):
        if reference(DATA / name)["sha256"] != digest:
            raise ValueError("EXACT_CORRECTED_DEVELOPMENT_BYTES_REQUIRED")
    # Only identity/eligibility fields before outcome payload access.
    identity = pq.ParquetFile(DATA / "starts.parquet").read(columns=IDENTITY).to_pandas()
    if (not identity.gameDate.between("2023-01-01", "2024-10-31").all()
            or not all(final_oot_eligible_key_mask(identity.gameId))
            or identity.startId.duplicated().any()):
        raise ValueError("DEVELOPMENT_IDENTITY_OR_WHOLE_GAME_QUARANTINE_FAILED")
    return identity


def stage_profiles():
    existing = read_pointer("profiles")
    if existing:
        require_declaration(existing, "MLB_PITCHER_STYLE_PROFILE_EXECUTION_V1")
        if existing["sourceStarts"] != reference(DATA / "starts.parquet") or existing["quarantine"] != reference(LEDGER):
            raise ValueError("CACHED_PROFILE_SOURCE_OR_QUARANTINE_CHANGED")
        verify_code(existing["code"], stage="profiles")
        validate_profiles(pd.read_parquet(read_ref(existing["profileTable"])), guard())
        return existing
    identity = guard()
    safe = identity.groupby("gameId").eligible.agg(["size", "all"])
    prior_games = set(safe.index[(safe["size"] == 2) & safe["all"]])
    started = now()
    profiles, provenance = build_profiles(identity.loc[identity.eligible, IDENTITY].copy(),
                                          permitted_prior_game_ids=prior_games)
    if (profiles.startId.duplicated().any() or set(profiles.startId) != set(identity.loc[identity.eligible, "startId"])
            or set(STYLE_FEATURES) - set(profiles)):
        raise ValueError("PROFILE_COHORT_OR_SCHEMA_MISMATCH")
    validate_profiles(profiles, identity)
    joined = identity.merge(profiles[["startId", "profileSupported", "profileUnsupportedReason"]],
                            on="startId", how="left", validate="one_to_one")
    counts = []
    for split, frame in joined.groupby("split"):
        counts.append({"split": split, "accountedStarts": len(frame), "originalEligibleStarts": int(frame.eligible.sum()),
                       "profileSupportedStarts": int(frame.profileSupported.eq(True).sum()),
                       "originalEligiblePitchers": int(frame.loc[frame.eligible, "pitcherId"].nunique()),
                       "profileSupportedPitchers": int(frame.loc[frame.profileSupported.eq(True), "pitcherId"].nunique()),
                       "profileUnsupportedReasons": frame.loc[frame.eligible & ~frame.profileSupported.eq(True), "profileUnsupportedReason"].value_counts(dropna=False).to_dict()})
    result = {"schemaVersion": "MLB_PITCHER_STYLE_PROFILE_EXECUTION_V1", "startedAtUtc": started,
              "completedAtUtc": now(), "declaration": reference(OUT / "declaration.json"),
              "quarantine": reference(LEDGER), "identityGate": {"identityColumnsReadFirst": IDENTITY,
                "sourceSeasons": [2023, 2024], "nineQuarantinedGamesPresent": 0, "sealedEvaluationPayloadOpened": False},
              "profileTable": save("profiles.parquet", parquet(profiles)), "provenance": provenance,
              "coverage": counts, "permittedPrior2023And2024Games": len(prior_games),
              "sourceStarts": reference(DATA / "starts.parquet"), "code": [reference(p) for p in CODE]}
    pointer("profiles", result)
    print(json.dumps({"event": "PROFILES_COMPLETE", "coverage": clean(counts), "atUtc": now()}), flush=True)
    return result


def frames_for_training(profile_result):
    identity = guard()
    profiles = pd.read_parquet(read_ref(profile_result["profileTable"]))
    validate_profiles(profiles, identity)
    supported = profiles.loc[profiles.profileSupported.eq(True)].copy()
    ids = set(supported.startId)
    # Read only earlier outcome partitions. The physically separate common
    # assessment start IDs are fixed now, but their outcomes stay unopened.
    train_ids = set(identity.loc[identity.eligible & identity.gameDate.lt("2024-01-01"), "startId"]) & ids
    cal_ids = set(identity.loc[identity.eligible & identity.gameDate.between("2024-01-01", "2024-06-30"), "startId"]) & ids
    test_ids = set(identity.loc[identity.eligible & identity.gameDate.ge("2024-07-01"), "startId"]) & ids
    if not min(map(len, (train_ids, cal_ids, test_ids))):
        raise ValueError("EMPTY_PREDECLARED_COMMON_WINDOW")
    risk = pd.read_parquet(DATA / "risk.parquet", filters=[("gameDate", "<", "2024-07-01")])
    risk = risk.loc[risk.startId.isin(train_ids | cal_ids)].copy()
    cols = [c for c in supported if c not in risk or c == "startId"]
    risk = risk.merge(supported[cols], on="startId", validate="many_to_one")
    train = risk.loc[risk.startId.isin(train_ids)].reset_index(drop=True)
    cal = risk.loc[risk.startId.isin(cal_ids)].reset_index(drop=True)
    train_starts = supported.loc[supported.startId.isin(train_ids)].reset_index(drop=True)
    cohort = {"trainingStartIds": sorted(train_ids), "calibrationStartIds": sorted(cal_ids), "assessmentStartIds": sorted(test_ids),
              "trainingRiskRows": len(train), "calibrationRiskRows": len(cal), "outcomeAccess": "TRAIN_AND_CAL_ONLY_BEFORE_MODEL_FREEZE",
              "trainingPitchers": int(identity.loc[identity.startId.isin(train_ids), "pitcherId"].nunique()),
              "calibrationPitchers": int(identity.loc[identity.startId.isin(cal_ids), "pitcherId"].nunique()),
              "assessmentPitchers": int(identity.loc[identity.startId.isin(test_ids), "pitcherId"].nunique())}
    return train, cal, train_starts, cohort


def stage_fit(profile_result):
    existing = read_pointer("fit")
    if existing:
        require_declaration(existing, "MLB_ARCHETYPE_FROZEN_FITS_V1")
        verify_code(existing["code"], stage="fit")
        if existing.get("profileTable") != profile_result["profileTable"] or existing["frozenBenchmark"] != reference(FROZEN):
            raise ValueError("CACHED_FIT_PROFILE_OR_BENCHMARK_CHANGED")
        cohort = json.loads(read_ref(existing["cohort"]).read_bytes())
        profile = pd.read_parquet(read_ref(profile_result["profileTable"]))
        eligible = guard().merge(profile[["startId", "profileSupported"]], on="startId", how="left", validate="one_to_one")
        for label, mask in (("training", eligible.gameDate.lt("2024-01-01")),
                            ("calibration", eligible.gameDate.between("2024-01-01", "2024-06-30")),
                            ("assessment", eligible.gameDate.ge("2024-07-01"))):
            if cohort[label + "StartIds"] != sorted(eligible.loc[eligible.eligible & eligible.profileSupported.eq(True) & mask, "startId"]):
                raise ValueError("CACHED_FIT_COMMON_COHORT_CHANGED")
        expected_arms = ["A", "B", "C"] if existing["C_supported"] else ["A", "B"]
        if [r["arm"] for r in existing["models"]] != expected_arms:
            raise ValueError("CACHED_FIT_ARM_SET_CHANGED")
        read_ref(existing["clusterArtifact"])
        read_ref(existing["clusterSelection"])
        for entry in existing["models"]:
            read_ref(entry["artifact"])
            read_ref(entry["fixture"])
            read_ref(entry["expected"])
        return existing
    train, cal, train_starts, cohort = frames_for_training(profile_result)
    cohort_ref = save("common-cohort.json", encoded(cohort))
    print(json.dumps({"event": "TRAIN_ONLY_CLUSTER_FIT", "starts": len(train_starts), "atUtc": now()}), flush=True)
    membership = ArchetypeMembership(uncertain_below=0.6).fit(train_starts)
    cluster_ref = save("archetype-membership.joblib", fitted(membership))
    cluster_selection = save("cluster-selection.json", encoded(membership.selection))
    if membership.supported:
        # Transformation only; calibration/assessment never fit cluster state.
        train = membership.append_memberships(train)
        cal = membership.append_memberships(cal)
    specs = [("A", tuple(PREGAME_FIELDS)), ("B", tuple(PREGAME_FIELDS) + tuple(STYLE_FEATURES))]
    if membership.supported:
        specs.append(("C", tuple(PREGAME_FIELDS) + tuple(STYLE_FEATURES) + ARCHETYPE_FIELDS[:membership.selected_k]))
    models, telemetry = [], []
    for arm, fields in specs:
        start = time.perf_counter()
        print(json.dumps({"event": "HAZARD_FIT_START", "arm": arm, "riskRows": len(train), "features": len(fields), "atUtc": now()}), flush=True)
        model = ArchetypeHazard(MODEL_IDS[arm], fields).fit(train, train.endpoint)
        calibration = model.fit_temperature(cal, cal.endpoint)
        model.metadata = {"schemaVersion": "MLB_ARCHETYPE_FITTED_TRAINING_IDENTITY_V1", "arm": arm,
                          "declaration": reference(OUT / "declaration.json"), "cohort": cohort_ref,
                          "profileSource": profile_result["profileTable"], "clusterSelection": cluster_selection,
                          "trainingCutoffExclusive": "2024-01-01", "calibrationCutoffExclusive": "2024-07-01",
                          "sourceChronology": "PRIOR_COMPLETED_EVENT_DATE_RECONSTRUCTION_NOT_HISTORICAL_PUBLICATION_VINTAGE",
                          "calibration": calibration, "code": [reference(p) for p in CODE],
                          "dependencies": {"python": sys.version, "numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__},
                          "executionThreadLimit": 1,
                          "promotionAuthority": False, "productionAuthority": False}
        ref = save("fitted-" + arm + ".joblib", fitted(model))
        fixture = cal.head(64)
        expected = model.predict_proba(fixture)
        if not np.array_equal(expected, joblib.load(read_ref(ref)).predict_proba(fixture)):
            raise ValueError("FITTED_RELOAD_CHANGED_PROBABILITIES")
        models.append({"arm": arm, "modelId": model.model_id, "featureOrder": fields,
                       "artifact": ref, "calibration": calibration, "reloadExact": True,
                       "fixture": save("reload-" + arm + ".parquet", parquet(fixture[list(fields)])),
                       "expected": save("reload-p-" + arm + ".parquet", parquet(pd.DataFrame(expected, columns=ENDPOINTS)))})
        telemetry.append({"arm": arm, "fitAndCalibrationSeconds": time.perf_counter() - start, "completedAtUtc": now()})
        print(json.dumps({"event": "HAZARD_FIT_COMPLETE", **telemetry[-1]}), flush=True)
    if reference(FROZEN)["sha256"] != FROZEN_SHA:
        raise ValueError("FROZEN_OPERATIONAL_BENCHMARK_CHANGED")
    result = {"schemaVersion": "MLB_ARCHETYPE_FROZEN_FITS_V1", "frozenAtUtc": now(),
              "assessmentPredictionsOrOutcomesReadByThisStage": False, "cohort": cohort_ref,
              "declaration": reference(OUT / "declaration.json"), "models": models,
              "clusterArtifact": cluster_ref, "clusterSelection": cluster_selection,
              "profileTable": profile_result["profileTable"],
              "C_supported": membership.supported, "frozenBenchmark": reference(FROZEN), "telemetry": telemetry,
              "code": [reference(p) for p in CODE]}
    pointer("fit", result)
    return result


def summarize(frame):
    numeric = frame.select_dtypes(include=["number", "bool"])
    return {"starts": len(frame), "games": int(frame.gameId.nunique()), "pitchers": int(frame.pitcherId.nunique()),
            **{c: float(numeric[c].mean()) for c in numeric if c != "archetype"}}


def paired_interval(scores, metric, candidate, reference_arm, unit):
    cols = ["startId", "gameId", "pitcherId", "arm", metric]
    wide = scores[cols].pivot(index=["startId", "gameId", "pitcherId"], columns="arm", values=metric)
    if candidate not in wide or reference_arm not in wide:
        return None
    difference = (wide[candidate] - wide[reference_arm]).dropna()
    grouped = difference.groupby(level=unit).agg(["sum", "count"])
    rng = np.random.default_rng(20260913)
    index = rng.integers(0, len(grouped), size=(500, len(grouped)))
    draw = grouped["sum"].to_numpy()[index].sum(axis=1) / grouped["count"].to_numpy()[index].sum(axis=1)
    return {"candidate": candidate, "reference": reference_arm, "metric": metric,
            "differenceCandidateMinusReference": float(difference.mean()), "ci95": np.quantile(draw, [.025, .975]).tolist(),
            "resampleUnit": unit, "units": len(grouped), "starts": len(difference), "resamples": 500,
            "interpretation": "DESCRIPTIVE_REUSED_DEVELOPMENT_PAIRED_CLUSTER_INTERVAL_NOT_PROMOTION_TEST"}


def removal_calibration(pred, metadata):
    bins = np.array([0, .01, .025, .05, .1, .2, .4, .6, .8, 1])
    tables = []
    for conditional in (False, True):
        selected = pred.loc[pred.endpoint.ne("GAME_END")].copy() if conditional else pred.copy()
        probability = selected.REMOVAL.to_numpy()
        if conditional:
            probability = probability / (probability + selected.CONTINUE.to_numpy())
        selected["probability"] = probability
        selected["bucket"] = np.minimum(np.searchsorted(bins, probability, side="right") - 1, len(bins) - 2)
        selected["actual"] = selected.endpoint.eq("REMOVAL").astype(float)
        selected["weight"] = 1.0 / selected.groupby("startId").startId.transform("size")
        for bucket in range(len(bins) - 1):
            rows = selected.loc[selected.bucket.eq(bucket)]
            weight = rows.weight.sum()
            tables.append({"conditionalOnNoGameEnd": conditional, "lowerInclusive": bins[bucket], "upper": bins[bucket+1],
                           "riskRows": len(rows), "starts": int(rows.startId.nunique()),
                           "pitchers": int(metadata.loc[metadata.startId.isin(rows.startId), "pitcherId"].nunique()),
                           "expectedRemovalCountAlongObservedRiskSet": float(rows.probability.sum()),
                           "observedRemovalCount": int(rows.actual.sum()),
                           "equalAppearanceWeightedPredictedRate": float(rows.probability @ rows.weight / weight) if weight else None,
                           "equalAppearanceWeightedObservedRate": float(rows.actual @ rows.weight / weight) if weight else None})
    return tables


def stage_assess(profile_result, fit_result):
    existing = read_pointer("assessment")
    if existing:
        require_declaration(existing, "MLB_PITCHER_ARCHETYPE_SURVIVAL_ASSESSMENT_V1")
        verify_code(existing["code"], stage="assessment")
        if existing["fit"] != json.loads((OUT / "fit.json").read_bytes()) or existing["cohort"] != fit_result["cohort"]:
            raise ValueError("CACHED_ASSESSMENT_FIT_BINDING_CHANGED")
        for key in ("scores", "removalCalibration"):
            read_ref(existing[key])
        for entry in existing["predictionArtifacts"]:
            read_ref(entry["riskPredictions"])
            read_ref(entry["durationDistribution"])
        return existing
    identity = guard()
    cohort = json.loads(read_ref(fit_result["cohort"]).read_bytes())
    ids = set(cohort["assessmentStartIds"])
    # Only after declaration, common cohort, cluster selection and fitted models
    # have been persisted do assessment endpoint/count columns enter this stage.
    opened_at = now()
    starts = pd.read_parquet(DATA / "starts.parquet", filters=[("gameDate", ">=", "2024-07-01")])
    starts = starts.loc[starts.startId.isin(ids)].sort_values("startId").reset_index(drop=True)
    risk = pd.read_parquet(DATA / "risk.parquet", filters=[("gameDate", ">=", "2024-07-01")])
    risk = risk.loc[risk.startId.isin(ids)].sort_values(["startId", "bf"]).reset_index(drop=True)
    if set(starts.startId) != ids or set(risk.startId) != ids:
        raise ValueError("HELD_OUT_COMMON_COHORT_CHANGED")
    profile = pd.read_parquet(read_ref(profile_result["profileTable"]))
    validate_profiles(profile, identity)
    for name, frame in (("starts", starts), ("risk", risk)):
        frame = frame.merge(profile[[c for c in profile if c not in frame or c == "startId"]], on="startId", validate="one_to_one" if name == "starts" else "many_to_one")
        if not frame.profileSupported.eq(True).all() or (frame.profileLatestGameDate >= frame.gameDate).any():
            raise ValueError("UNSUPPORTED_OR_FUTURE_PROFILE_IN_COMMON_ASSESSMENT")
        if name == "starts": starts = frame
        else: risk = frame
    membership = joblib.load(read_ref(fit_result["clusterArtifact"]))
    if membership.supported:
        starts, risk = membership.append_memberships(starts), membership.append_memberships(risk)
        starts["archetype"] = membership.predict_proba(starts).argmax(axis=1)
        group_summary = membership.summarize(starts)
    else:
        starts["archetype"] = -1
        group_summary = []
    y = target_codes(risk.endpoint)
    models = [("FROZEN", joblib.load(read_ref(fit_result["frozenBenchmark"])))]
    models += [(entry["arm"], joblib.load(read_ref(entry["artifact"]))) for entry in fit_result["models"]]
    frames, summaries, artifacts, calibration = [], [], [], []
    for arm, model in models:
        print(json.dumps({"event": "ASSESS_ARM", "arm": arm, "starts": len(starts), "atUtc": now()}), flush=True)
        p = model.predict_proba(risk)
        nll, brier = losses(p, y)
        raw_nll, raw_brier = losses(model.predict_proba(risk, calibrated=False), y)
        pred = risk[["startId", "gameId", "gameDate", "bf", "endpoint"]].copy()
        pred[list(ENDPOINTS)] = p
        pred["nll"], pred["brier"], pred["rawNll"], pred["rawBrier"] = nll, brier, raw_nll, raw_brier
        path = pred.groupby("startId", as_index=False).agg(pathNll=("nll", "sum"), boundaryNll=("nll", "mean"),
                    boundaryBrier=("brier", "mean"), rawPathNll=("rawNll", "sum"), rawBoundaryBrier=("rawBrier", "mean"))
        distribution = pregame_bf_distribution(model, starts)
        scores = pd.DataFrame(duration_metrics(distribution, starts.realizedBf))
        scores["startId"] = starts.startId.to_numpy()
        scores = scores.merge(path, on="startId", validate="one_to_one").merge(
            starts[["startId", "gameId", "gameDate", "pitcherId", "endpoint", "realizedBf", "archetype"]], on="startId", validate="one_to_one")
        cause = distribution["causeMass"].sum(axis=1)
        terminal = np.column_stack([cause, distribution["tail"]])
        target = np.where(starts.endpoint.eq("REMOVAL"), 0, 1)
        joint_mass = distribution["causeMass"][np.arange(len(starts)), starts.realizedBf.to_numpy(dtype=int)-1, target]
        integrated_path_nll = -np.log(np.clip(joint_mass, 1e-12, 1))
        path_ordered = path.set_index("startId").loc[starts.startId, "pathNll"].to_numpy()
        if not np.allclose(path_ordered, integrated_path_nll, atol=1e-9, rtol=1e-9):
            raise ValueError("OBSERVED_PATH_AND_INTEGRATED_BF_CAUSE_LOSS_DIVERGED")
        terminal_scores = pd.DataFrame({"startId": starts.startId, "terminalCauseNll": -np.log(np.clip(terminal[np.arange(len(starts)), target], 1e-12, 1)),
                    "terminalCauseBrier": ((terminal - np.eye(3)[target])**2).sum(axis=1)})
        scores = scores.merge(terminal_scores, on="startId", validate="one_to_one")
        scores["arm"] = arm
        frames.append(scores)
        summaries.append({"arm": arm, **summarize(scores)})
        calibration.append({"arm": arm, "bins": removal_calibration(pred, starts)})
        buffer = io.BytesIO()
        np.savez_compressed(buffer, startId=starts.startId.to_numpy(dtype=str), pmf=distribution["pmf"],
                            causeMass=distribution["causeMass"], unresolvedTail=distribution["tail"])
        artifacts.append({"arm": arm, "riskPredictions": save("risk-predictions-"+arm+".parquet", parquet(pred)),
                          "durationDistribution": save("duration-distribution-"+arm+".npz", buffer.getvalue())})
    scores = pd.concat(frames, ignore_index=True)
    contrasts = [row for candidate, baseline in (("A", "FROZEN"), ("B", "A"), ("C", "B"), ("C", "A"))
                 for metric in ("pathNll", "bfCrpsThrough100") for unit in ("gameId", "pitcherId")
                 if (row := paired_interval(scores, metric, candidate, baseline, unit)) is not None]
    groups = [{"arm": arm, "archetype": int(group), **summarize(frame)}
              for (arm, group), frame in scores.groupby(["arm", "archetype"])]
    allocation = []
    mean_bf = scores.pivot(index="startId", columns="arm", values="expectedBfCapped101")
    for candidate, baseline in (("B", "A"), ("C", "B"), ("C", "A")):
        if candidate not in mean_bf: continue
        delta = mean_bf[candidate] - mean_bf[baseline]
        allocation.append({"candidate": candidate, "reference": baseline, "meanExpectedBfChange": float(delta.mean()),
                           "fractionEarlier": float((delta < -1e-9).mean()), "fractionLater": float((delta > 1e-9).mean()),
                           "quantiles": dict(zip(("p05", "p25", "p50", "p75", "p95"), np.quantile(delta, [.05, .25, .5, .75, .95]))),
                           "meanAbsoluteChange": float(delta.abs().mean())})
    advancement = []
    for candidate, baseline in (("B", "A"), ("C", "B")):
        rows = [x for x in contrasts if x["candidate"] == candidate and x["reference"] == baseline]
        loss = [x for x in rows if x["metric"] == "pathNll"]
        crps = next((x for x in rows if x["metric"] == "bfCrpsThrough100"), None)
        shifts = next((x for x in allocation if x["candidate"] == candidate and x["reference"] == baseline), None)
        passes = (len(loss) == 2 and all(x["differenceCandidateMinusReference"] <= -.005 and x["ci95"][1] < 0 for x in loss)
                  and crps is not None and crps["differenceCandidateMinusReference"] <= 0 and shifts is not None
                  and shifts["fractionEarlier"] >= .1 and shifts["fractionLater"] >= .1)
        if candidate == "C" and passes:
            ca = next(x for x in contrasts if x["candidate"] == "C" and x["reference"] == "A" and x["metric"] == "pathNll")
            passes = ca["differenceCandidateMinusReference"] <= 0
        advancement.append({"candidate": candidate, "reference": baseline, "passesPredeclaredDevelopmentPreparationGate": bool(passes),
                            "productionPromotion": False})
    result = {"schemaVersion": "MLB_PITCHER_ARCHETYPE_SURVIVAL_ASSESSMENT_V1", "createdAtUtc": now(),
              "assessmentOutcomeColumnsOpenedAtUtc": opened_at, "fitsFrozenAtUtc": fit_result["frozenAtUtc"],
              "declaration": reference(OUT / "declaration.json"), "fit": json.loads((OUT / "fit.json").read_bytes()),
              "cohort": fit_result["cohort"], "status": "RETROSPECTIVE_REUSED_DEVELOPMENT_NOT_UNTOUCHED_CONFIRMATION",
              "summary": summaries, "pairedUncertainty": contrasts, "allArchetypeMetrics": groups,
              "assessmentArchetypeSupport": group_summary, "allocation": allocation, "advancement": advancement,
              "scores": save("appearance-scores.parquet", parquet(scores)), "predictionArtifacts": artifacts,
              "removalCalibration": save("removal-calibration.json", encoded(calibration)),
              "assessmentTerminalCounts": starts.endpoint.value_counts().to_dict(),
              "coverage": profile_result["coverage"], "providerCalls": 0, "newGameForecasts": 0,
              "code": [reference(p) for p in CODE], "pathNllEqualsIntegratedBfCauseNll": True,
              "existingV18AndResearchArtifactsModified": False, "quarantine": reference(LEDGER)}
    pointer("assessment", result)
    write_note(result, fit_result)
    print(json.dumps({"event": "ASSESSMENT_COMPLETE", "summary": clean(summaries), "advancement": advancement}, indent=2), flush=True)
    return result


def write_note(result, fit_result):
    lines = ["Pitcher-profile and archetype survival comparison", "",
        "Reused 2023–2024 Development; historical pitch availability is reconstructed from prior event dates, not certified publication vintages. Lower scores are better. All arms use identical supported starts; the frozen HGB remains an operational benchmark.", "",
        "| Arm | Starts / pitchers | Path NLL | BF CRPS | BF MAE | BF bias | Early-exit Brier | Long-start Brier |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for s in result["summary"]:
        lines.append(f"| {s['arm']} | {s['starts']} / {s['pitchers']} | {s['pathNll']:.6f} | {s['bfCrpsThrough100']:.4f} | {s['bfCappedMeanAbsoluteError']:.4f} | {s['bfCappedMeanBias']:+.4f} | {s['earlyExitBrier']:.5f} | {s['longStartBrier']:.5f} |")
    lines += ["", "A is a matched refit of the seven existing features; B adds continuous profiles; C additionally adds soft archetypes. CONTINUE/REMOVAL/GAME_END remain distinct. BF scores integrate the reduced pregame process, not full-game rollouts.", "",
              "| Contrast | Path-NLL difference | 95% whole-game interval | 95% pitcher interval |", "|---|---:|---|---|"]
    for candidate, baseline in (("A", "FROZEN"), ("B", "A"), ("C", "B"), ("C", "A")):
        rows = [r for r in result["pairedUncertainty"] if r["candidate"] == candidate and r["reference"] == baseline and r["metric"] == "pathNll"]
        if rows:
            a, b = rows
            lines.append(f"| {candidate} − {baseline} | {a['differenceCandidateMinusReference']:+.6f} | [{a['ci95'][0]:+.6f}, {a['ci95'][1]:+.6f}] | [{b['ci95'][0]:+.6f}, {b['ci95'][1]:+.6f}] |")
    lines += ["", "These paired intervals resample whole games or pitchers; BF rows are not independent observations. Prior assessment exposure and repeated pitcher use limit confirmation claims.", "", "Reproduce without provider access:", "", "```powershell", ".venv/Scripts/python.exe -B scripts/run_mlb_pitcher_archetype_survival.py --stage all", "```", ""]
    (OUT / "COMPARISON.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["all", "profiles", "fit", "assess"], default="all")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    guard()
    # One thread avoids restricted Windows named-pipe primitives; it changes
    # neither the predeclared estimator parameters nor the shared cohort.
    with threadpool_limits(limits=1):
        profile_result = stage_profiles()
        if args.stage == "profiles": return
        fit_result = stage_fit(profile_result)
        if args.stage == "fit": return
        stage_assess(profile_result, fit_result)


if __name__ == "__main__":
    main()
