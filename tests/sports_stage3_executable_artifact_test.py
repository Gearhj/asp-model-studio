from __future__ import annotations

import json
import shutil
import uuid
from contextlib import nullcontext
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


class _MemoryRunRepository:
    def __init__(self, *rows: dict[str, object]) -> None:
        self.rows = {str(row["run_id"]): dict(row) for row in rows}

    def get(self, run_id: str) -> dict[str, object] | None:
        row = self.rows.get(run_id)
        return dict(row) if row is not None else None

    def list_for_project(self, project_id: str) -> list[dict[str, object]]:
        return [
            dict(row)
            for row in reversed(list(self.rows.values()))
            if row.get("project_id") == project_id
        ]

    def upsert(self, row: dict[str, object]) -> dict[str, object]:
        self.rows[str(row["run_id"])] = dict(row)
        return dict(row)


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
        source_manifest_sha=artifact.EXPECTED_SOURCE_MANIFEST_SHA256,
        gold_manifest_sha=lab.EXPECTED_GOLD_MANIFEST_SHA,
        contextual_manifest_sha=artifact.EXPECTED_CONTEXTUAL_MANIFEST_SHA256,
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


def _write_bundle(
    root: Path, *, source_plan: dict[str, object] | None = None
) -> tuple[str, str, Path]:
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
    verification_receipt = {
        "schemaVersion": artifact.EXECUTABLE_ARTIFACT_VERIFICATION_SCHEMA_VERSION,
        "status": "PASS",
        "probabilityContract": artifact._probability_contract(),
        "rawOofProbabilityValidation": raw_probability_validation,
    }
    if source_plan is not None:
        verification_receipt["planChecksum"] = source_plan["checksum"]
    artifact._atomic_json(
        staging / "verification-receipt.json", verification_receipt
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
        "artifactId": (
            "stage3-executable-artifact-" + str(source_plan["checksum"])[:32]
            if source_plan is not None
            else "stage3-executable-artifact-unit"
        ),
        "projectId": lab.EXPECTED_PROJECT_ID,
        "authority": source_plan["authority"]
        if source_plan is not None
        else {
            "projectId": lab.EXPECTED_PROJECT_ID,
            "projectName": "MLB 2026 Current-Data Game Forecast Challenger",
            "sourceDatasetId": lab.EXPECTED_SOURCE_DATASET_ID,
            "sourceManifestSha": artifact.EXPECTED_SOURCE_MANIFEST_SHA256,
            "goldDatasetId": "gold-table:gold_mlb_current_pa_v1",
            "goldManifestSha": lab.EXPECTED_GOLD_MANIFEST_SHA,
            "contextualManifestSha": artifact.EXPECTED_CONTEXTUAL_MANIFEST_SHA256,
            "authorityKey": "authority-key",
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
            "targetOrder": list(GOLD_CLASS_ORDER),
        },
        "selection": source_plan["selection"]
        if source_plan is not None
        else {
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
            "modelStatus": "RESEARCH_CHALLENGER",
            "promotionStatus": "NOT_PROMOTED",
        },
        "candidate": source_plan["candidate"]
        if source_plan is not None
        else {
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
        "environment": source_plan["environment"]
        if source_plan is not None
        else {
            "acceptedCandidateRun": {
                "modelLabImplementationSha256": artifact.EXPECTED_MODEL_LAB_IMPLEMENTATION_SHA256
            }
        },
        "verification": {
            "status": "PASS",
            "metricReproduction": {
                "status": "PASS",
                "maxAbsoluteDifference": 0.0,
            },
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

    monkeypatch.setattr(artifact, "_directory_replace", forbidden_replace)
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


def test_windows_process_liveness_is_positive_only_and_system_error_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if artifact.os.name != "nt":
        pytest.skip("Windows liveness contract")
    monkeypatch.setattr(artifact, "_windows_process_alive", lambda _pid: False)
    assert artifact._process_alive(987654321) is False
    monkeypatch.setattr(artifact, "_windows_process_alive", lambda _pid: True)
    assert artifact._process_alive(987654321) is True

    def system_error(_pid: int) -> bool:
        raise SystemError("inconclusive Windows process query")

    monkeypatch.setattr(artifact, "_windows_process_alive", system_error)
    assert artifact._process_alive(987654321) is True
    assert artifact._process_alive(True) is True
    assert artifact._process_alive(None) is True


def test_active_synchronous_recovery_is_not_reconciled_after_startup_grace() -> None:
    job_id = "stage3-executable-artifact-recovery-live"
    row = {
        "run_id": job_id,
        "project_id": lab.EXPECTED_PROJECT_ID,
        "run_type": artifact.EXECUTABLE_ARTIFACT_JOB_TYPE,
        "status": "RUNNING",
        "parameters_json": "{}",
        "metrics_json": json.dumps({"state": "RUNNING"}),
        "artifacts_json": json.dumps(
            {
                "coordinatorProcessId": artifact.os.getpid(),
                "coordinatorInstanceId": artifact._COORDINATOR_INSTANCE_ID,
                "coordinatorRegisteredClock": artifact.time.time() - 31.0,
            }
        ),
        "error_json": "{}",
    }
    with artifact._FUTURES_GUARD:
        artifact._SYNCHRONOUS_RECOVERY_JOBS.add(job_id)
    try:
        reconciled = artifact._reconcile_interrupted_job(object(), row)
    finally:
        with artifact._FUTURES_GUARD:
            artifact._SYNCHRONOUS_RECOVERY_JOBS.discard(job_id)
    assert reconciled["status"] == "RUNNING"


def test_publication_retries_transient_windows_sharing_error_then_verifies(
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
    calls: list[int] = []

    def sharing_then_success(source: object, destination: object) -> None:
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise PermissionError(
                13, "transient sharing violation", str(source), 32
            )
        shutil.copytree(Path(source), Path(destination))
        shutil.rmtree(Path(source))

    monkeypatch.setattr(artifact, "_directory_replace", sharing_then_success)
    monkeypatch.setattr(artifact.time, "sleep", lambda _delay: None)
    publication = artifact._finalize_staging(staging, checksum)
    assert publication.artifact_path == target
    assert publication.reused is False
    assert publication.protocol == artifact._ATOMIC_DIRECTORY_RENAME_PROTOCOL
    assert publication.fallback_used is False
    assert calls == [1, 2, 3]
    assert artifact.verify_artifact_bundle(
        f"objects/sha256/{checksum}", expected_manifest_sha256=checksum
    )["status"] == "PASS"


def test_publication_retry_exhaustion_commits_manifest_last_after_pre_marker_rejection(
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
    expected_manifest_bytes = (staging / "manifest.json").read_bytes()
    calls: list[int] = []
    pre_commit_observations: list[str] = []

    def sharing_failure(_source: object, _destination: object) -> None:
        calls.append(len(calls) + 1)
        raise PermissionError(
            13, "persistent sharing violation", "staging", 32
        )

    original_install = artifact._install_manifest_commit_marker

    def observe_pre_marker(**kwargs: object) -> bool:
        assert target.is_dir()
        assert staging.is_dir()
        assert not (target / "manifest.json").exists()
        with pytest.raises(lab.Stage3ModelLaboratoryError) as unpublished:
            artifact.verify_artifact_bundle(
                f"objects/sha256/{checksum}",
                expected_manifest_sha256=checksum,
            )
        pre_commit_observations.append(unpublished.value.code)
        return original_install(**kwargs)

    monkeypatch.setattr(artifact, "_directory_replace", sharing_failure)
    monkeypatch.setattr(
        artifact, "_install_manifest_commit_marker", observe_pre_marker
    )
    monkeypatch.setattr(artifact.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(artifact, "_PUBLICATION_RETRY_ATTEMPTS", 3)
    publication = artifact._finalize_staging(staging, checksum)
    assert publication.artifact_path == target
    assert publication.reused is False
    assert publication.protocol == artifact._MANIFEST_COMMIT_PROTOCOL
    assert publication.fallback_used is True
    assert calls == [1, 2, 3]
    assert pre_commit_observations == [
        "STAGE3_ARTIFACT_MANIFEST_CHECKSUM_MISMATCH"
    ]
    assert (target / "manifest.json").read_bytes() == expected_manifest_bytes
    assert not staging.exists()
    assert artifact.verify_artifact_bundle(
        f"objects/sha256/{checksum}", expected_manifest_sha256=checksum
    )["status"] == "PASS"


def test_manifest_commit_marker_failure_preserves_verified_source_and_unpublished_target(
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

    def sharing_failure(_source: object, _destination: object) -> None:
        raise PermissionError(13, "persistent sharing violation", "staging", 32)

    marker_attempts = 0

    def marker_failure(_source: object, _destination: object) -> None:
        nonlocal marker_attempts
        marker_attempts += 1
        raise PermissionError(13, "manifest marker sharing violation", "manifest", 32)

    monkeypatch.setattr(artifact, "_directory_replace", sharing_failure)
    monkeypatch.setattr(artifact, "_manifest_rename", marker_failure)
    monkeypatch.setattr(artifact.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(artifact, "_PUBLICATION_RETRY_ATTEMPTS", 2)
    with pytest.raises(lab.Stage3ModelLaboratoryError) as exhausted:
        artifact._finalize_staging(staging, checksum)
    assert (
        exhausted.value.code
        == "STAGE3_ARTIFACT_MANIFEST_COMMIT_RETRY_EXHAUSTED"
    )
    assert marker_attempts == 2
    assert staging.is_dir()
    assert target.is_dir()
    assert not (target / "manifest.json").exists()
    with pytest.raises(lab.Stage3ModelLaboratoryError) as unpublished:
        artifact.load_executable_artifact(
            f"objects/sha256/{checksum}", expected_manifest_sha256=checksum
        )
    assert unpublished.value.code == "STAGE3_ARTIFACT_MANIFEST_CHECKSUM_MISMATCH"


def test_manifest_commit_resumes_exact_valid_subset_and_cleans_only_recognized_temp(
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
    manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
    model_relative = manifest["files"]["model"]["relativePath"]
    target.mkdir()
    shutil.copy2(staging / model_relative, target / model_relative)
    temporary = target / artifact._manifest_commit_temp_name(
        target / "preprocessor.joblib", checksum, token="a" * 32
    )
    temporary.write_bytes(b"interrupted copy")

    monkeypatch.setattr(
        artifact,
        "_directory_replace",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("an existing manifestless target must resume directly")
        ),
    )
    publication = artifact._finalize_staging(staging, checksum)
    assert publication.artifact_path == target
    assert publication.protocol == artifact._MANIFEST_COMMIT_PROTOCOL
    assert publication.fallback_used is True
    assert publication.reused is False
    assert not temporary.exists()
    assert not staging.exists()
    assert artifact.verify_artifact_bundle(
        f"objects/sha256/{checksum}", expected_manifest_sha256=checksum
    )["status"] == "PASS"


def test_manifest_commit_reuses_valid_member_that_wins_atomic_name_race(
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
    raced_destination: Path | None = None
    raced_file_id: int | None = None
    original_member_rename = artifact._member_rename

    def directory_failure(_source: object, _destination: object) -> None:
        raise PermissionError(13, "persistent sharing violation", "staging", 32)

    def member_race(source: Path, destination: Path) -> None:
        nonlocal raced_destination, raced_file_id
        if raced_destination is None:
            relative = destination.relative_to(target)
            shutil.copy2(staging / relative, destination)
            raced_destination = destination
            raced_file_id = destination.stat().st_ino
            raise FileExistsError(17, "another publisher installed member", destination, 183)
        original_member_rename(source, destination)

    monkeypatch.setattr(artifact, "_directory_replace", directory_failure)
    monkeypatch.setattr(artifact, "_member_rename", member_race)
    monkeypatch.setattr(artifact, "_PUBLICATION_RETRY_ATTEMPTS", 1)
    publication = artifact._finalize_staging(staging, checksum)
    assert publication.protocol == artifact._MANIFEST_COMMIT_PROTOCOL
    assert publication.fallback_used is True
    assert raced_destination is not None
    assert raced_destination.stat().st_ino == raced_file_id
    assert artifact.verify_artifact_bundle(
        f"objects/sha256/{checksum}", expected_manifest_sha256=checksum
    )["status"] == "PASS"


def test_manifest_commit_removes_losing_temp_before_verifying_marker_race(
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
    winning_manifest_file_id: int | None = None

    def directory_failure(_source: object, _destination: object) -> None:
        raise PermissionError(13, "persistent sharing violation", "staging", 32)

    def manifest_race(_source: Path, destination: Path) -> None:
        nonlocal winning_manifest_file_id
        shutil.copy2(staging / "manifest.json", destination)
        winning_manifest_file_id = destination.stat().st_ino
        raise FileExistsError(17, "another publisher installed manifest", destination, 183)

    monkeypatch.setattr(artifact, "_directory_replace", directory_failure)
    monkeypatch.setattr(artifact, "_manifest_rename", manifest_race)
    monkeypatch.setattr(artifact, "_PUBLICATION_RETRY_ATTEMPTS", 1)
    publication = artifact._finalize_staging(staging, checksum)
    assert publication.protocol == artifact._MANIFEST_COMMIT_PROTOCOL
    assert publication.fallback_used is True
    assert publication.reused is True
    assert (target / "manifest.json").stat().st_ino == winning_manifest_file_id
    assert not any(
        artifact._MANIFEST_COMMIT_TEMP_TAG in path.name
        for path in target.rglob("*")
    )
    assert not staging.exists()
    assert artifact.verify_artifact_bundle(
        f"objects/sha256/{checksum}", expected_manifest_sha256=checksum
    )["status"] == "PASS"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            "tampered-member",
            "STAGE3_ARTIFACT_PUBLICATION_TARGET_MEMBER_MISMATCH",
        ),
        (
            "unexpected-file",
            "STAGE3_ARTIFACT_PUBLICATION_TARGET_UNEXPECTED_CONTENT",
        ),
        (
            "unexpected-directory",
            "STAGE3_ARTIFACT_PUBLICATION_TARGET_UNEXPECTED_CONTENT",
        ),
        (
            "unrecognized-temp",
            "STAGE3_ARTIFACT_PUBLICATION_TARGET_UNEXPECTED_CONTENT",
        ),
        ("reparse-member", "STAGE3_ARTIFACT_REPARSE_POINT_REJECTED"),
    ],
)
def test_manifest_commit_resume_rejects_tamper_unexpected_and_reparse_content(
    artifact_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_code: str,
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
    target.mkdir()
    if mutation in {"tampered-member", "reparse-member"}:
        shutil.copy2(staging / "model.joblib", target / "model.joblib")
    if mutation == "tampered-member":
        (target / "model.joblib").write_bytes(b"tampered resume member")
    elif mutation == "unexpected-file":
        (target / "undeclared.txt").write_text("unexpected", encoding="utf-8")
    elif mutation == "unexpected-directory":
        (target / "undeclared-directory").mkdir()
    elif mutation == "unrecognized-temp":
        lookalike = (
            f".model.joblib{artifact._MANIFEST_COMMIT_TEMP_TAG}"
            f"{checksum[:16]}-not-a-uuid.tmp"
        )
        (target / lookalike).write_bytes(b"must not be cleaned")
    else:
        original_reparse_check = artifact._path_is_reparse_point
        poisoned = (target / "model.joblib").resolve()
        monkeypatch.setattr(
            artifact,
            "_path_is_reparse_point",
            lambda path: Path(path).resolve() == poisoned
            or original_reparse_check(Path(path)),
        )

    with pytest.raises(lab.Stage3ModelLaboratoryError) as rejected:
        artifact._finalize_staging(staging, checksum)
    assert rejected.value.code == expected_code
    assert staging.is_dir()
    assert not (target / "manifest.json").exists()


def test_publication_race_reuses_only_a_verified_existing_target(
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
    calls: list[int] = []

    def concurrent_winner(source: object, destination: object) -> None:
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise PermissionError(
                13, "transient sharing violation", str(source), 32
            )
        shutil.copytree(Path(source), Path(destination))
        raise PermissionError(13, "another publisher won", str(source), 32)

    monkeypatch.setattr(artifact, "_directory_replace", concurrent_winner)
    monkeypatch.setattr(artifact.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(artifact, "_PUBLICATION_RETRY_ATTEMPTS", 3)
    publication = artifact._finalize_staging(staging, checksum)
    assert publication.artifact_path == target
    assert publication.reused is True
    assert publication.protocol == artifact._VERIFIED_EXISTING_TARGET_PROTOCOL
    assert publication.fallback_used is False
    assert target.is_dir()
    assert not staging.exists()
    assert calls == [1, 2, 3]


def test_publication_does_not_retry_nonsharing_error_or_accept_corrupt_race_target(
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
    attempts = 0

    def nonsharing_failure(_source: object, _destination: object) -> None:
        nonlocal attempts
        attempts += 1
        raise PermissionError(13, "permission failure without a sharing winerror")

    monkeypatch.setattr(artifact, "_directory_replace", nonsharing_failure)
    with pytest.raises(PermissionError):
        artifact._finalize_staging(staging, checksum)
    assert attempts == 1
    assert staging.is_dir()

    def corrupt_concurrent_winner(source: object, destination: object) -> None:
        shutil.copytree(Path(source), Path(destination))
        (Path(destination) / "model.joblib").write_bytes(b"corrupt race target")
        raise PermissionError(
            13, "another publisher won with corrupt bytes", str(source), 32
        )

    monkeypatch.setattr(
        artifact, "_directory_replace", corrupt_concurrent_winner
    )
    with pytest.raises(lab.Stage3ModelLaboratoryError) as corrupt:
        artifact._finalize_staging(staging, checksum)
    assert corrupt.value.code == "STAGE3_ARTIFACT_MEMBER_CHECKSUM_MISMATCH"
    assert staging.is_dir()


def _recovery_source_row(
    *, source_job_id: str, plan: dict[str, object], staging: Path
) -> dict[str, object]:
    return {
        "run_id": source_job_id,
        "project_id": lab.EXPECTED_PROJECT_ID,
        "run_type": artifact.EXECUTABLE_ARTIFACT_JOB_TYPE,
        "workflow_type": "sports_stage3_executable_artifact",
        "status": "FAILED",
        "started_at": "2026-09-03T17:57:52+00:00",
        "completed_at": "2026-09-03T18:32:32+00:00",
        "parameters_json": plan,
        "metrics_json": {
            "state": "FAILED",
            "oofRowsPersisted": artifact.EXPECTED_OOF_ROWS,
            "finalFitState": "COMPLETE",
            "modelFitsByPurpose": {"oofFold": 5, "finalDevelopment": 1},
        },
        "artifacts_json": {
            "artifact": None,
            "stagingPath": str(staging),
            "safety": artifact._safety_payload(),
        },
        "error_json": {
            "code": "STAGE3_EXECUTABLE_ARTIFACT_EXECUTION_FAILED",
            "message": "transient Windows publication failure",
        },
        "created_by": "source-actor",
    }


def _prepare_recovery_test(
    artifact_root: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[_MemoryRunRepository, dict[str, object], str, Path, Path]:
    monkeypatch.setenv("ATLAS_STAGE3_EXECUTABLE_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setattr(
        artifact,
        "EXPECTED_CANDIDATE",
        {**artifact.EXPECTED_CANDIDATE, "featureCount": 2},
    )
    chain = _chain()
    chain["featureSetContract"] = {
        **chain["featureSetContract"],
        "orderedFeatures": ["alpha", "beta"],
    }
    monkeypatch.setattr(artifact, "_resolved_chain", lambda _db, _project: chain)
    plan = artifact.plan_executable_artifact(
        object(), lab.EXPECTED_PROJECT_ID, {"nativeWorkers": 2}, actor_user_id="a"
    )["plan"]
    _relative, manifest_sha, target = _write_bundle(
        artifact_root, source_plan=plan
    )
    staging = artifact_root / "staging" / "unit"
    source = _recovery_source_row(source_job_id="unit", plan=plan, staging=staging)
    repository = _MemoryRunRepository(source)
    monkeypatch.setattr(artifact, "RunRepository", lambda _database: repository)
    monkeypatch.setattr(
        artifact, "interprocess_lock", lambda *_args, **_kwargs: nullcontext()
    )
    monkeypatch.setattr(
        artifact,
        "_fresh_process_reload_check",
        lambda *_args, **_kwargs: {
            "status": "PASS",
            "freshProcess": True,
            "maxAbsoluteDifference": 0.0,
            "rows": 2,
        },
    )
    return repository, plan, manifest_sha, staging, target


def test_recovery_creates_new_complete_audit_run_without_refitting_and_is_idempotent(
    artifact_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, plan, manifest_sha, staging, target = _prepare_recovery_test(
        artifact_root, monkeypatch
    )
    shutil.rmtree(target)
    target.mkdir()
    shutil.copy2(staging / "model.joblib", target / "model.joblib")
    interrupted_temp = target / artifact._manifest_commit_temp_name(
        target / "preprocessor.joblib", manifest_sha, token="b" * 32
    )
    interrupted_temp.write_bytes(b"interrupted recovery publication")
    monkeypatch.setattr(
        artifact,
        "_directory_replace",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("recovery must resume the exact manifestless target")
        ),
    )
    monkeypatch.setattr(
        artifact,
        "fit_stage3_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("publication recovery must not fit")
        ),
    )
    # Recovery intentionally preserves the fit-time production identity in the
    # frozen source plan. It must not regenerate a plan from newly edited
    # recovery code.
    monkeypatch.setattr(
        artifact,
        "_production_environment",
        lambda _chain: {"artifactProduction": {"changedAfterFit": True}},
    )
    payload = {
        "expectedManifestSha256": manifest_sha,
        "expectedSourcePlanChecksum": plan["checksum"],
    }
    first = artifact.recover_failed_executable_artifact_publication(
        object(),
        lab.EXPECTED_PROJECT_ID,
        "unit",
        payload,
        actor_user_id="recovery-actor",
    )["job"]
    assert first["status"] == "COMPLETE"
    assert first["publicationRecovery"]["fitPerformed"] is False
    assert (
        first["publicationRecovery"]["publicationProtocol"]
        == artifact._MANIFEST_COMMIT_PROTOCOL
    )
    assert first["publicationRecovery"]["publicationFallbackUsed"] is True
    assert first["publicationRecovery"]["existingTargetReused"] is False
    assert first["progress"]["modelFitsPerformedByThisJob"] == {
        "oofFold": 0,
        "finalDevelopment": 0,
    }
    assert first["progress"]["artifactStagingState"] == "COMPLETE"
    assert (
        first["progress"]["publicationProtocol"]
        == artifact._MANIFEST_COMMIT_PROTOCOL
    )
    assert first["progress"]["publicationFallbackUsed"] is True
    assert first["artifact"]["publicationProtocol"] == artifact._MANIFEST_COMMIT_PROTOCOL
    assert first["artifact"]["publicationFallbackUsed"] is True
    assert isinstance(first["progress"]["elapsedSeconds"], float)
    assert first["progress"]["elapsedSeconds"] >= 0.0
    assert repository.get("unit")["status"] == "FAILED"
    assert len(repository.rows) == 2
    assert target.is_dir()
    assert not interrupted_temp.exists()
    assert not staging.exists()
    summary = artifact.executable_artifact_summary(
        object(), lab.EXPECTED_PROJECT_ID
    )
    assert summary["currentJob"]["jobId"] == first["jobId"]
    assert summary["currentJob"]["status"] == "COMPLETE"
    assert summary["artifact"]["manifestSha256"] == manifest_sha
    assert repository.get("unit")["status"] == "FAILED"

    second = artifact.recover_failed_executable_artifact_publication(
        object(),
        lab.EXPECTED_PROJECT_ID,
        "unit",
        payload,
        actor_user_id="recovery-actor",
    )["job"]
    assert second["jobId"] == first["jobId"]
    assert second["idempotentReplay"] is True
    assert len(repository.rows) == 2


def test_recovery_completes_after_crash_window_when_only_public_target_exists(
    artifact_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, plan, manifest_sha, staging, target = _prepare_recovery_test(
        artifact_root, monkeypatch
    )
    shutil.rmtree(staging)
    monkeypatch.setattr(
        artifact,
        "_finalize_staging",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("existing target recovery must not republish")
        ),
    )
    result = artifact.recover_failed_executable_artifact_publication(
        object(),
        lab.EXPECTED_PROJECT_ID,
        "unit",
        {
            "expectedManifestSha256": manifest_sha,
            "expectedSourcePlanChecksum": plan["checksum"],
        },
        actor_user_id="recovery-actor",
    )["job"]
    assert result["status"] == "COMPLETE"
    assert result["publicationRecovery"]["existingTargetReused"] is True
    assert repository.get("unit")["status"] == "FAILED"
    assert target.is_dir()


def test_recovery_prefers_verified_public_target_over_partial_redundant_staging(
    artifact_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, plan, manifest_sha, staging, target = _prepare_recovery_test(
        artifact_root, monkeypatch
    )
    (staging / "model.joblib").write_bytes(b"partially cleaned private staging")
    result = artifact.recover_failed_executable_artifact_publication(
        object(),
        lab.EXPECTED_PROJECT_ID,
        "unit",
        {
            "expectedManifestSha256": manifest_sha,
            "expectedSourcePlanChecksum": plan["checksum"],
        },
        actor_user_id="recovery-actor",
    )["job"]
    assert result["status"] == "COMPLETE"
    assert result["publicationRecovery"]["existingTargetReused"] is True
    assert target.is_dir()
    assert not staging.exists()
    assert repository.get("unit")["status"] == "FAILED"


def test_recovery_rejects_tampered_staging_before_creating_audit_run(
    artifact_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, plan, manifest_sha, staging, target = _prepare_recovery_test(
        artifact_root, monkeypatch
    )
    shutil.rmtree(target)
    (staging / "model.joblib").write_bytes(b"tampered")
    with pytest.raises(lab.Stage3ModelLaboratoryError) as rejected:
        artifact.recover_failed_executable_artifact_publication(
            object(),
            lab.EXPECTED_PROJECT_ID,
            "unit",
            {
                "expectedManifestSha256": manifest_sha,
                "expectedSourcePlanChecksum": plan["checksum"],
            },
            actor_user_id="recovery-actor",
        )
    assert rejected.value.code == "STAGE3_ARTIFACT_MEMBER_CHECKSUM_MISMATCH"
    assert list(repository.rows) == ["unit"]
    assert repository.get("unit")["status"] == "FAILED"
