from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import FunctionTransformer

from server.sports_current_statcast import stage3_executable_artifact as artifact
from server.sports_current_statcast import stage3_model_laboratory as lab
from server.sports_gold.contracts import GOLD_CLASS_ORDER


class _FixedEstimator:
    def __init__(self) -> None:
        self.classes_ = np.asarray([7, 0, 3, 1, 2, 4, 5, 6], dtype=np.int64)

    def predict_proba(self, values: object) -> np.ndarray:
        rows = int(getattr(values, "shape")[0])
        probability_by_class = np.asarray(
            [0.21, 0.11, 0.03, 0.15, 0.04, 0.01, 0.44, 0.01], dtype=float
        )
        return np.tile(probability_by_class[self.classes_], (rows, 1))


@pytest.fixture
def artifact_root() -> Path:
    base = (
        Path("tests")
        / ".stage3-executable-artifact-test-runtime"
        / uuid.uuid4().hex
    ).resolve()
    base.mkdir(parents=True, exist_ok=False)
    try:
        yield base
    finally:
        if base.is_relative_to(
            (Path("tests") / ".stage3-executable-artifact-test-runtime").resolve()
        ):
            shutil.rmtree(base, ignore_errors=True)


def _pipeline() -> lab.Stage3FittedPipeline:
    transformer = FunctionTransformer(validate=False).fit(
        pd.DataFrame([[1.0, 2.0]], columns=["alpha", "beta"])
    )
    return lab.Stage3FittedPipeline(
        ordered_features=["alpha", "beta"],
        target_order=GOLD_CLASS_ORDER,
        preprocessor=transformer,
        estimator=_FixedEstimator(),
    )


def _chain() -> dict[str, object]:
    eda = SimpleNamespace(
        source_dataset_id="asp.mlb.statcast.current-pa.v1",
        source_manifest_sha="1" * 64,
        gold_manifest_sha=lab.EXPECTED_GOLD_MANIFEST_SHA,
        contextual_manifest_sha="2" * 64,
    )
    resolved = SimpleNamespace(
        project_name="MLB 2026 Current-Data Game Forecast Challenger",
        authority_key="authority-key",
        eda_authority=eda,
        split={
            "contractId": lab.EXPECTED_SPLIT["splitContractId"],
            "contractVersion": 2,
            "checksum": lab.EXPECTED_SPLIT["checksum"],
        },
        outlier_policy=lab.EXPECTED_OUTLIER_POLICY,
        missing_policy=lab.EXPECTED_MISSING_POLICY,
    )
    return {
        "projectId": lab.EXPECTED_PROJECT_ID,
        **artifact.EXPECTED_SELECTION,
        **{
            key: artifact.EXPECTED_CANDIDATE[key]
            for key in (
                "candidateFingerprint",
                "candidateAttemptId",
                "candidateAttemptReceiptSha256",
                "candidateRunId",
                "candidateRunReceiptSha256",
            )
        },
        "featureSetContract": {
            "featureSetId": artifact.EXPECTED_CANDIDATE["featureSetId"],
            "checksum": artifact.EXPECTED_CANDIDATE["featureSetChecksum"],
            "orderedFeatures": [f"feature_{index:03d}" for index in range(234)],
        },
        "sourceRun": {
            "environment": {
                "modelLabImplementationSha256": artifact.EXPECTED_MODEL_LAB_IMPLEMENTATION_SHA256
            }
        },
        "resolvedAuthority": resolved,
    }


def _write_bundle(root: Path) -> tuple[str, str, Path]:
    staging = root / "staging" / "unit"
    staging.mkdir(parents=True)
    pipeline = _pipeline()
    joblib.dump(pipeline, staging / "model.joblib")
    joblib.dump(pipeline.preprocessor, staging / "preprocessor.joblib")
    fold_dir = staging / "fold-models"
    fold_dir.mkdir()
    for fold in range(1, 6):
        joblib.dump(pipeline, fold_dir / f"fold-{fold}.joblib")
    (staging / "oof-predictions.parquet").write_bytes(b"bounded-test-parquet")
    frame = pd.DataFrame([[1.0, 2.0], [3.0, 4.0]], columns=["alpha", "beta"])
    fixture = {
        "orderedFeatures": ["alpha", "beta"],
        "rows": frame.values.tolist(),
        "expectedProbabilities": pipeline.predict_proba(frame).tolist(),
    }
    artifact._atomic_json(staging / "verification-fixture.json", fixture)
    raw_probability_validation = {
        "status": "PASS",
        "rows": artifact.EXPECTED_OOF_ROWS,
        "columns": len(GOLD_CLASS_ORDER),
        "representation": "FLOAT64_PRESERVING_RAW_ESTIMATOR_VALUES",
        "minimumProbability": 0.01,
        "maximumProbability": 0.44,
        "minimumRowSum": 1.0,
        "maximumRowSum": 1.0,
        "maximumAbsoluteRowSumDeviation": 0.0,
        "rowSumRtol": lab.RAW_PROBABILITY_ROW_SUM_RTOL,
        "rowSumAtol": lab.RAW_PROBABILITY_ROW_SUM_ATOL,
        "normalizationApplied": False,
    }
    artifact._atomic_json(
        staging / "verification-receipt.json",
        {
            "schemaVersion": artifact.EXECUTABLE_ARTIFACT_VERIFICATION_SCHEMA_VERSION,
            "status": "PASS",
            "probabilityContract": artifact._probability_contract(),
            "rawOofProbabilityValidation": raw_probability_validation,
        },
    )
    fold_evidence = [
        {
            "foldNumber": boundary[0],
            "trainStart": boundary[1],
            "trainEnd": boundary[2],
            "trainRows": boundary[3],
            "trainGames": boundary[4],
            "validationStart": boundary[5],
            "validationEnd": boundary[6],
            "validationRows": boundary[7],
            "validationGames": boundary[8],
            "observedLogLoss": artifact.EXPECTED_FOLD_LOG_LOSSES[index],
            "expectedAcceptedLogLoss": artifact.EXPECTED_FOLD_LOG_LOSSES[index],
            "delta": 0.0,
            "absoluteDifference": 0.0,
            "tolerance": artifact._METRIC_ATOL,
            "status": "PASS",
        }
        for index, boundary in enumerate(lab.EXPECTED_FOLDS)
    ]
    files = {
        "model": artifact._file_record(staging / "model.joblib", staging),
        "preprocessor": artifact._file_record(
            staging / "preprocessor.joblib", staging
        ),
        "foldModels": [
            {
                **artifact._file_record(
                    fold_dir / f"fold-{fold}.joblib", staging
                ),
                **fold_evidence[fold - 1],
            }
            for fold in range(1, 6)
        ],
        "oofPredictions": artifact._file_record(
            staging / "oof-predictions.parquet", staging
        ),
        "verificationFixture": artifact._file_record(
            staging / "verification-fixture.json", staging
        ),
        "verificationReceipt": artifact._file_record(
            staging / "verification-receipt.json", staging
        ),
    }
    manifest = {
        "schemaVersion": artifact.EXECUTABLE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "artifactId": "stage3-executable-artifact-unit",
        "authority": {
            "projectId": lab.EXPECTED_PROJECT_ID,
            "sourceDatasetId": lab.EXPECTED_SOURCE_DATASET_ID,
            "sourceManifestSha": artifact.EXPECTED_SOURCE_MANIFEST_SHA256,
            "goldDatasetId": "gold-table:gold_mlb_current_pa_v1",
            "goldManifestSha": lab.EXPECTED_GOLD_MANIFEST_SHA,
            "contextualManifestSha": artifact.EXPECTED_CONTEXTUAL_MANIFEST_SHA256,
            "splitContractId": lab.EXPECTED_SPLIT["splitContractId"],
            "splitVersion": lab.EXPECTED_SPLIT["version"],
            "splitChecksum": lab.EXPECTED_SPLIT["checksum"],
            "outlierPolicyId": lab.EXPECTED_OUTLIER_POLICY["policyId"],
            "outlierPolicyVersion": lab.EXPECTED_OUTLIER_POLICY["policyVersion"],
            "outlierPolicyChecksum": lab.EXPECTED_OUTLIER_POLICY["checksum"],
            "missingPolicyId": lab.EXPECTED_MISSING_POLICY["policyId"],
            "missingPolicyVersion": lab.EXPECTED_MISSING_POLICY["policyVersion"],
            "missingPolicyChecksum": lab.EXPECTED_MISSING_POLICY["checksum"],
            "developmentRows": lab.EXPECTED_DEVELOPMENT[2],
            "developmentStart": lab.EXPECTED_DEVELOPMENT[0],
            "developmentEnd": lab.EXPECTED_DEVELOPMENT[1],
            "finalOotRows": lab.EXPECTED_FINAL_OOT[2],
            "finalOotStart": lab.EXPECTED_FINAL_OOT[0],
            "finalOotEnd": lab.EXPECTED_FINAL_OOT[1],
            "finalOotLocked": True,
            "finalOotTargetAccessed": False,
        },
        "selection": {
            **artifact.EXPECTED_SELECTION,
            **{
                key: artifact.EXPECTED_CANDIDATE[key]
                for key in (
                    "candidateFingerprint",
                    "candidateAttemptId",
                    "candidateAttemptReceiptSha256",
                    "candidateRunId",
                    "candidateRunReceiptSha256",
                )
            },
        },
        "candidate": {
            "modelFamily": "xgboost",
            "estimatorClass": "XGBClassifier",
            "objective": "multi:softprob",
            "evaluationMetric": "mlogloss",
            "featureSetId": artifact.EXPECTED_CANDIDATE["featureSetId"],
            "featureSetChecksum": artifact.EXPECTED_CANDIDATE[
                "featureSetChecksum"
            ],
            "featureCount": artifact.EXPECTED_CANDIDATE["featureCount"],
            "orderedFeaturesSha256": artifact._sha(
                {"orderedFeatures": ["alpha", "beta"]}
            ),
            "hyperparameters": artifact.EXPECTED_HYPERPARAMETERS,
            "seed": artifact.EXPECTED_CANDIDATE["seed"],
            "targetOrder": list(GOLD_CLASS_ORDER),
            "acceptedOofEvidenceSha256": artifact.EXPECTED_OOF_EVIDENCE_SHA256,
            "acceptedModelLabImplementationSha256": artifact.EXPECTED_MODEL_LAB_IMPLEMENTATION_SHA256,
        },
        "targetOrder": list(GOLD_CLASS_ORDER),
        "orderedFeatures": ["alpha", "beta"],
        "probabilityContract": artifact._probability_contract(),
        "training": {
            "scope": "DEVELOPMENT_ONLY",
            "rows": lab.EXPECTED_DEVELOPMENT[2],
            "startDate": lab.EXPECTED_DEVELOPMENT[0],
            "cutoff": lab.EXPECTED_DEVELOPMENT[1],
            "seed": artifact.EXPECTED_CANDIDATE["seed"],
            "finalOotRowsUsed": 0,
            "finalOotTargetAccessed": False,
        },
        "oof": {
            "scope": "FIVE_FOLD_CHRONOLOGICAL_DEVELOPMENT_ONLY",
            "rows": artifact.EXPECTED_OOF_ROWS,
            "foldCount": 5,
            "legacyEvidenceSha256": artifact.EXPECTED_OOF_EVIDENCE_SHA256,
            "folds": fold_evidence,
        },
        "environment": {
            "acceptedCandidateRun": {
                "modelLabImplementationSha256": artifact.EXPECTED_MODEL_LAB_IMPLEMENTATION_SHA256
            }
        },
        "verification": {
            "status": "PASS",
            "metricReproduction": {"status": "PASS"},
            "rawOofProbabilityValidation": raw_probability_validation,
            "reloadVerification": {"status": "PASS", "freshProcess": True},
            "verificationFixture": {"status": "PASS"},
        },
        "files": files,
        "safety": artifact._safety_payload(),
    }
    artifact._atomic_json(staging / "manifest.json", manifest)
    checksum = artifact._sha_file(staging / "manifest.json")
    target = root / "objects" / "sha256" / checksum
    target.parent.mkdir(parents=True)
    # The managed Windows test sandbox does not grant directory-rename rights
    # between these sibling paths; production finalization still uses one
    # atomic rename after verification.
    shutil.copytree(staging, target)
    return f"objects/sha256/{checksum}", checksum, target


def test_fitted_pipeline_aligns_classes_and_rejects_feature_drift() -> None:
    pipeline = _pipeline()
    frame = pd.DataFrame([[1.0, 2.0]], columns=["alpha", "beta"])
    observed = pipeline.predict_proba(frame)
    assert observed.shape == (1, 8)
    assert observed[0].tolist() == pytest.approx(
        [0.21, 0.11, 0.03, 0.15, 0.04, 0.01, 0.44, 0.01]
    )
    with pytest.raises(lab.Stage3ModelLaboratoryError) as reordered:
        pipeline.predict_proba(frame[["beta", "alpha"]])
    assert reordered.value.code == "STAGE3_ARTIFACT_FEATURE_ORDER_MISMATCH"
    with pytest.raises(lab.Stage3ModelLaboratoryError):
        pipeline.predict_proba(frame.assign(extra=1.0))
    pipeline.estimator.classes_ = np.arange(7)
    with pytest.raises(lab.Stage3ModelLaboratoryError) as missing_class:
        pipeline.predict_proba(frame)
    assert missing_class.value.code == "MODEL_LAB_ESTIMATOR_CLASS_ORDER_INVALID"


def test_float32_softmax_roundoff_stays_raw_for_evidence_and_normalizes_for_scoring() -> None:
    raw = np.asarray(
        [
            0.16530278325080872,
            0.2131487876176834,
            0.053714070469141006,
            0.13301485776901245,
            0.08270382881164551,
            0.22062674164772034,
            0.01480624545365572,
            0.11668261885643005,
        ],
        dtype=np.float32,
    )
    raw_matrix = raw[np.newaxis, :]
    raw_as_float64 = raw_matrix.astype(np.float64)
    deviation = abs(float(raw_as_float64.sum()) - 1.0)
    assert 1e-8 < deviation < lab.RAW_PROBABILITY_ROW_SUM_ATOL
    validated = lab._validate_probability_matrix(raw_matrix, expected_rows=1)
    np.testing.assert_array_equal(validated, raw_as_float64)

    class Float32RoundoffEstimator:
        classes_ = np.arange(len(GOLD_CLASS_ORDER))

        def predict_proba(self, _values: object) -> np.ndarray:
            return raw_matrix.copy()

    transformer = FunctionTransformer(validate=False).fit(
        pd.DataFrame([[1.0, 2.0]], columns=["alpha", "beta"])
    )
    pipeline = lab.Stage3FittedPipeline(
        ordered_features=["alpha", "beta"],
        target_order=GOLD_CLASS_ORDER,
        preprocessor=transformer,
        estimator=Float32RoundoffEstimator(),
    )
    executable = pipeline.predict_proba(
        pd.DataFrame([[1.0, 2.0]], columns=["alpha", "beta"])
    )
    assert executable.dtype == np.float64
    assert executable.sum(axis=1).tolist() == [1.0]
    assert not np.array_equal(executable, raw_as_float64)
    np.testing.assert_array_equal(raw_matrix, raw[np.newaxis, :])

    invalid_element = np.zeros((1, len(GOLD_CLASS_ORDER)), dtype=np.float64)
    invalid_element[0, 0] = 1.0 + 1e-7
    with pytest.raises(lab.Stage3ModelLaboratoryError) as invalid:
        lab._validate_probability_matrix(invalid_element, expected_rows=1)
    assert "maximum=1.0000001" in str(invalid.value)
    assert "rowSumAtol=1e-06" in str(invalid.value)


def test_raw_probability_diagnostics_reject_impossible_pass_summaries() -> None:
    valid = {
        "status": "PASS",
        "rows": artifact.EXPECTED_OOF_ROWS,
        "columns": len(GOLD_CLASS_ORDER),
        "representation": "FLOAT64_PRESERVING_RAW_ESTIMATOR_VALUES",
        "minimumProbability": 0.01,
        "maximumProbability": 0.44,
        "minimumRowSum": 1.0 - 1e-8,
        "maximumRowSum": 1.0 + 2e-8,
        "maximumAbsoluteRowSumDeviation": 2e-8,
        "rowSumRtol": lab.RAW_PROBABILITY_ROW_SUM_RTOL,
        "rowSumAtol": lab.RAW_PROBABILITY_ROW_SUM_ATOL,
        "normalizationApplied": False,
    }
    assert artifact._valid_raw_probability_diagnostics(
        valid, expected_rows=artifact.EXPECTED_OOF_ROWS
    )

    impossible_values = (
        {"minimumProbability": 0.9, "maximumProbability": -1.0},
        {"minimumRowSum": 1.0000001, "maximumRowSum": 0.9999999},
        {"maximumAbsoluteRowSumDeviation": -99.0},
        {"maximumAbsoluteRowSumDeviation": 0.0},
    )
    for mutation in impossible_values:
        assert not artifact._valid_raw_probability_diagnostics(
            {**valid, **mutation}, expected_rows=artifact.EXPECTED_OOF_ROWS
        )


def test_evaluate_candidate_capture_is_fold_local_and_preserves_fold_seed() -> None:
    train = pd.DataFrame(
        {
            "feature": np.arange(16, dtype=float),
            "game_date": ["2023-04-01"] * 16,
            "outcome": list(GOLD_CLASS_ORDER) * 2,
            "canonicalGameId": ["train-game"] * 16,
        }
    )
    validation = pd.DataFrame(
        {
            "feature": [np.nan, *np.arange(100, 107, dtype=float)],
            "game_date": ["2024-04-01"] * 8,
            "outcome": list(GOLD_CLASS_ORDER),
            "canonicalGameId": ["validation-game"] * 8,
        }
    )
    frame = pd.concat([train, validation], ignore_index=True)
    split = {
        "contract": {
            "folds": [
                {
                    "foldNumber": 1,
                    "trainStart": "2023-04-01",
                    "trainEnd": "2023-04-01",
                    "trainRows": 16,
                    "trainGames": 1,
                    "validationStart": "2024-04-01",
                    "validationEnd": "2024-04-01",
                    "validationRows": 8,
                    "validationGames": 1,
                }
            ]
        }
    }
    feature_set = {
        "featureSetId": "test-features",
        "checksum": "f" * 64,
        "orderedFeatures": ["feature"],
        "transformationContracts": {
            "ordered": [{"feature": "feature", "steps": ["RETAIN_RAW"]}]
        },
    }
    captures: list[dict[str, object]] = []
    progress_events: list[dict[str, object]] = []
    result = lab._evaluate_candidate(
        frame,
        model_family="multinomial_logistic",
        feature_set=feature_set,
        split=split,
        seed=100,
        hyperparameters={"C": 1.0, "max_iter": 100, "tol": 1e-4, "solver": "lbfgs"},
        progress_callback=progress_events.append,
        artifact_callback=captures.append,
    )
    assert result["foldsCompleted"] == 1
    assert len(captures) == 1
    captured = captures[0]
    fitted = captured["pipeline"]
    assert isinstance(fitted, lab.Stage3FittedPipeline)
    assert fitted.estimator.random_state == 101
    statistic = fitted.preprocessor.named_transformers_["numeric"].named_steps[
        "imputer"
    ].statistics_[0]
    assert statistic == pytest.approx(7.5)
    assert captured["preprocessing"]["validationRowsUsedForParameters"] == 0
    assert captured["preprocessing"]["finalOotRowsUsedForParameters"] == 0
    event_names = [event["event"] for event in progress_events]
    assert event_names.index("FOLD_ESTIMATOR_FIT_COMPLETED") < event_names.index(
        "FOLD_COMPLETED"
    )


def test_plan_is_immutable_deterministic_and_zero_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(artifact, "_resolved_chain", lambda _db, _pid: _chain())
    first = artifact.plan_executable_artifact(
        object(), lab.EXPECTED_PROJECT_ID, {"nativeWorkers": 2}, actor_user_id="a"
    )["plan"]
    second = artifact.plan_executable_artifact(
        object(), lab.EXPECTED_PROJECT_ID, {"nativeWorkers": 2}, actor_user_id="b"
    )["plan"]
    assert first["planId"] == second["planId"]
    assert first["checksum"] == second["checksum"]
    assert first["workload"] == {
        "foldCount": 5,
        "oofRows": 501590,
        "finalFitRows": 683662,
        "modelFits": 6,
        "estimatedSecondsFromAcceptedRun": 1529.298,
    }
    assert first["candidate"]["seed"] == 20260901
    assert first["candidate"]["hyperparameters"] == artifact.EXPECTED_HYPERPARAMETERS
    assert first["candidate"]["targetOrder"] == list(GOLD_CLASS_ORDER)
    assert first["safety"] == {
        "modelStatus": "RESEARCH_CHALLENGER",
        "promotionStatus": "NOT_PROMOTED",
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "providerCalls": 0,
        "modelsPromoted": 0,
        "championsMutated": 0,
    }
    assert "oof-predictions.parquet" in first["expectedArtifacts"]
    with pytest.raises(lab.Stage3ModelLaboratoryError) as forbidden:
        artifact.plan_executable_artifact(
            object(),
            lab.EXPECTED_PROJECT_ID,
            {"seed": 7},
            actor_user_id="a",
        )
    assert forbidden.value.code == "STAGE3_EXECUTABLE_ARTIFACT_PLAN_OPTION_FORBIDDEN"


def test_bundle_reload_tamper_partial_and_path_guards(
    artifact_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        artifact,
        "EXPECTED_CANDIDATE",
        {**artifact.EXPECTED_CANDIDATE, "featureCount": 2},
    )
    monkeypatch.setenv("ATLAS_STAGE3_EXECUTABLE_ARTIFACT_ROOT", str(artifact_root))
    relative, checksum, target = _write_bundle(artifact_root)
    verified = artifact.verify_artifact_bundle(
        relative, expected_manifest_sha256=checksum
    )
    assert verified["status"] == "PASS"
    loaded = artifact.load_executable_artifact(
        relative, expected_manifest_sha256=checksum
    )
    assert loaded.pipeline.predict_proba(
        pd.DataFrame([[1.0, 2.0]], columns=["alpha", "beta"])
    ).shape == (1, 8)
    loaded_fold = artifact.load_executable_artifact(
        relative, expected_manifest_sha256=checksum, fold_number=3
    )
    assert loaded_fold.verified is True
    assert loaded_fold.fold_number == 3
    with pytest.raises(lab.Stage3ModelLaboratoryError) as traversal:
        artifact.resolve_executable_artifact_path("objects/sha256/../escape")
    assert traversal.value.code == "STAGE3_ARTIFACT_PATH_INVALID"

    model_path = target / "model.joblib"
    model_path.write_bytes(b"tampered pickle")
    called = False

    def unsafe_load(_path: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("deserialization must not occur")

    monkeypatch.setattr(artifact.joblib, "load", unsafe_load)
    with pytest.raises(lab.Stage3ModelLaboratoryError) as tampered:
        artifact.load_executable_artifact(
            relative, expected_manifest_sha256=checksum
        )
    assert tampered.value.code == "STAGE3_ARTIFACT_MEMBER_CHECKSUM_MISMATCH"
    assert called is False


def test_partial_bundle_is_never_loadable(
    artifact_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        artifact,
        "EXPECTED_CANDIDATE",
        {**artifact.EXPECTED_CANDIDATE, "featureCount": 2},
    )
    monkeypatch.setenv("ATLAS_STAGE3_EXECUTABLE_ARTIFACT_ROOT", str(artifact_root))
    relative, checksum, target = _write_bundle(artifact_root)
    (target / "fold-models" / "fold-5.joblib").unlink()
    with pytest.raises(lab.Stage3ModelLaboratoryError) as partial:
        artifact.verify_artifact_bundle(
            relative, expected_manifest_sha256=checksum
        )
    assert partial.value.code == "STAGE3_ARTIFACT_MEMBER_CHECKSUM_MISMATCH"


def test_staged_reload_hashes_before_deserialization(
    artifact_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_STAGE3_EXECUTABLE_ARTIFACT_ROOT", str(artifact_root))
    staging = artifact_root / "staging" / "one"
    staging.mkdir(parents=True)
    pipeline = _pipeline()
    joblib.dump(pipeline, staging / "model.joblib")
    fixture = {
        "orderedFeatures": ["alpha", "beta"],
        "rows": [[1.0, 2.0]],
        "expectedProbabilities": pipeline.predict_proba(
            pd.DataFrame([[1.0, 2.0]], columns=["alpha", "beta"])
        ).tolist(),
    }
    artifact._atomic_json(staging / "verification-fixture.json", fixture)
    result = artifact.verify_staged_model(
        staging,
        expected_model_sha256=artifact._sha_file(staging / "model.joblib"),
        expected_fixture_sha256=artifact._sha_file(
            staging / "verification-fixture.json"
        ),
    )
    assert result["status"] == "PASS"
    with pytest.raises(lab.Stage3ModelLaboratoryError):
        artifact.verify_staged_model(
            staging,
            expected_model_sha256="0" * 64,
            expected_fixture_sha256=artifact._sha_file(
                staging / "verification-fixture.json"
            ),
        )


def test_metric_reproduction_reports_first_exact_mismatch() -> None:
    reproduced = dict(artifact.EXPECTED_METRICS)
    assert artifact._metric_reconciliation(
        reproduced, artifact.EXPECTED_METRICS
    )["maxAbsoluteDifference"] == 0.0
    reproduced["meanOofLogLoss"] += 1e-5
    with pytest.raises(lab.Stage3ModelLaboratoryError) as mismatch:
        artifact._metric_reconciliation(reproduced, artifact.EXPECTED_METRICS)
    assert mismatch.value.code == "STAGE3_EXECUTABLE_ARTIFACT_METRIC_REPRODUCTION_FAILED"


def test_fold_reproduction_is_durable_and_manifest_authority_validates_it(
    artifact_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reproduced = {
        "folds": [
            {
                "foldNumber": boundary[0],
                "trainStart": boundary[1],
                "trainEnd": boundary[2],
                "trainRows": boundary[3],
                "trainGames": boundary[4],
                "validationStart": boundary[5],
                "validationEnd": boundary[6],
                "validationRows": boundary[7],
                "validationGames": boundary[8],
                "metrics": {
                    "multiclassLogLoss": artifact.EXPECTED_FOLD_LOG_LOSSES[index]
                },
            }
            for index, boundary in enumerate(lab.EXPECTED_FOLDS)
        ]
    }
    evidence = artifact._fold_metric_reconciliation(reproduced)
    assert [item["status"] for item in evidence] == ["PASS"] * 5
    assert [item["delta"] for item in evidence] == [0.0] * 5

    monkeypatch.setattr(
        artifact,
        "EXPECTED_CANDIDATE",
        {**artifact.EXPECTED_CANDIDATE, "featureCount": 2},
    )
    monkeypatch.setenv("ATLAS_STAGE3_EXECUTABLE_ARTIFACT_ROOT", str(artifact_root))
    relative, checksum, _target = _write_bundle(artifact_root)
    manifest = artifact.verify_artifact_bundle(
        relative, expected_manifest_sha256=checksum
    )["manifest"]
    tampered = json.loads(json.dumps(manifest))
    tampered["oof"]["folds"][2]["observedLogLoss"] += 1e-4
    with pytest.raises(lab.Stage3ModelLaboratoryError) as invalid:
        artifact._validate_manifest_authority(tampered)
    assert invalid.value.code == "STAGE3_ARTIFACT_MANIFEST_AUTHORITY_INVALID"


def test_finalize_rehashes_every_staged_member_before_atomic_rename(
    artifact_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        artifact,
        "EXPECTED_CANDIDATE",
        {**artifact.EXPECTED_CANDIDATE, "featureCount": 2},
    )
    monkeypatch.setenv("ATLAS_STAGE3_EXECUTABLE_ARTIFACT_ROOT", str(artifact_root))
    _relative, checksum, target = _write_bundle(artifact_root)
    shutil.rmtree(target)
    staging = artifact_root / "staging" / "unit"
    (staging / "model.joblib").write_bytes(b"changed after manifest creation")
    replace_called = False

    def forbidden_replace(_source: object, _target: object) -> None:
        nonlocal replace_called
        replace_called = True
        raise AssertionError("publication rename must not run")

    monkeypatch.setattr(artifact.os, "replace", forbidden_replace)
    with pytest.raises(lab.Stage3ModelLaboratoryError) as mismatch:
        artifact._finalize_staging(staging, checksum)
    assert mismatch.value.code == "STAGE3_ARTIFACT_MEMBER_CHECKSUM_MISMATCH"
    assert replace_called is False


def test_job_decode_normalizes_empty_and_malformed_errors_to_null() -> None:
    row = {
        "run_id": "job",
        "project_id": lab.EXPECTED_PROJECT_ID,
        "status": "COMPLETE",
        "parameters_json": "{}",
        "metrics_json": "{}",
        "artifacts_json": "{}",
        "error_json": "{}",
    }
    assert artifact._decode_job(row)["error"] is None
    assert artifact._decode_job({**row, "error_json": "[]"})["error"] is None
    assert artifact._decode_job(
        {
            **row,
            "status": "FAILED",
            "error_json": json.dumps({"code": "FAILED", "message": "exact"}),
        }
    )["error"] == {"code": "FAILED", "message": "exact"}


def test_manifest_is_canonical_content_address(artifact_root: Path) -> None:
    value = {"z": 1, "a": [2, 3]}
    path = artifact_root / "manifest.json"
    artifact._atomic_json(path, value)
    assert path.read_bytes() == artifact.canonical_json_bytes(value)
    assert artifact._sha_file(path) == artifact._sha(value)
