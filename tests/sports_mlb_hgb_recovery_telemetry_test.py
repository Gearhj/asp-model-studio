"""No sports data and no real estimator fits: exercise the job-thread seam."""
from __future__ import annotations

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier

from server.sports_current_statcast import mlb_hgb_recovery_telemetry as telemetry
from server.sports_current_statcast import stage3_corrected_eligibility as eligibility
from server.sports_gold.contracts import GOLD_CLASS_ORDER
import threadpoolctl


@pytest.fixture
def case(monkeypatch):
    features = [f"source_{n}" for n in range(218)] + [f"prior_{n}" for n in range(55)]
    frame = pd.DataFrame(np.ones((7, 273)), columns=features)
    frame["game_date"] = [f"2024-04-0{n}" for n in range(1, 8)]
    frame["outcome"] = "TARGET_MUST_NOT_ENTER_TREATMENT"
    folds = [{"foldNumber": n, "trainStart": "2024-04-01", "trainEnd": f"2024-04-0{n + 1}",
              "validationStart": f"2024-04-0{n + 2}", "validationEnd": f"2024-04-0{n + 2}",
              "trainRows": n + 1, "validationRows": 1, "checksum": str(n) * 64} for n in range(1, 6)]
    expected = {"recoveryId": "synthetic-recovery", "treatmentManifestChecksum": "a" * 64,
        "featureSetId": "synthetic-V18", "featureSetChecksum": "b" * 64, "modelFeatureSchemaChecksum": "c" * 64,
        "eligibilityChecksum": "d" * 64, "splitContractId": "synthetic-split", "splitChecksum": "e" * 64,
        "orderedFeatures": features, "sourceOrderedFeatures": features[:218], "folds": folds,
        "baseSeed": 100, "hyperparameters": {"learning_rate": 0.1, "max_iter": 2}, "nativeWorkers": 4,
        "targetOrder": list(GOLD_CLASS_ORDER),
        "sourceRows": 7, "eligibleRows": 7, "heldRows": 0,
        "boundSourceHashes": {__file__: hashlib.sha256(__import__("pathlib").Path(__file__).read_bytes()).hexdigest()},
        "estimatorParametersByFold": {str(n): HistGradientBoostingClassifier(learning_rate=0.1, max_iter=2, early_stopping=False, random_state=100 + n).get_params(deep=False) for n in range(1, 6)}}
    # Only the fixed population-size constant is replaced for tiny test frames;
    # all identity, schema, source-hash, parameter and actual-mask guards execute.
    original_validation = telemetry.RecoveryObserver._validate_expectation
    def tiny_population_validation(observer):
        sizes = {key: observer.expected[key] for key in ("sourceRows", "eligibleRows", "heldRows")}
        observer.expected.update(sourceRows=683662, eligibleRows=683606, heldRows=56)
        try:
            original_validation(observer)
        finally:
            observer.expected.update(sizes)
    monkeypatch.setattr(telemetry.RecoveryObserver, "_validate_expectation", tiny_population_validation)
    def mask(source, feature_set):
        assert "outcome" not in source
        return np.ones(len(source), dtype=bool), {"eligibilityChecksum": "d" * 64, "sourceRows": 7, "eligibleRows": 7, "heldRows": 0}
    monkeypatch.setattr(eligibility, "eligibility_mask", mask)
    monkeypatch.setattr(threadpoolctl, "threadpool_info", lambda: [{"user_api": "openmp", "internal_api": "openmp", "num_threads": 4}])
    counters = {"originalFits": 0, "threads": [], "inject": None}
    def synthetic_fit(estimator, X, y):
        import threading
        counters["originalFits"] += 1
        counters["threads"].append(threading.get_ident())
        if counters["inject"] == "fit_failure": raise PermissionError("synthetic thread-pool AccessDenied")
        return estimator
    monkeypatch.setattr(HistGradientBoostingClassifier, "fit", synthetic_fit)
    contract = {"semanticTreatmentVersion": "MLB_SEMANTIC_TREATMENT_V1", "treatmentManifestChecksum": "a" * 64,
        "modelFeatureSchemaChecksum": "c" * 64, "sourceOrderedFeatures": features[:218], "ordered": [{"feature": name} for name in features]}
    feature_set = {"featureSetId": "synthetic-V18", "checksum": "b" * 64, "orderedFeatures": features, "transformationContracts": contract}
    lab = SimpleNamespace(GOLD_CLASS_ORDER=GOLD_CLASS_ORDER)
    def prepare(source, **kwargs):
        fold = kwargs["fold"]
        train = source.iloc[:fold["trainRows"]].drop(columns="outcome").copy()
        valid = source.iloc[fold["trainRows"]:fold["trainRows"] + 1].drop(columns="outcome").copy()
        def guard(value):
            return {"status": "PASS", "modelFeatureCount": 273, "rows": len(value), "ordinaryFallbackRows": 0,
                    "targetColumnsRead": [], "finalOotRowsRead": 0, "evidenceChecksum": "f" * 64}
        payload = {"schemaVersion": "MLB_CORRECTED_FITTED_PREPROCESSING_V1", "orderedFeatures": features,
            "sourceOrderedFeatures": features[:218], "transformationContracts": contract,
            "prior": {"outputSchema": {"orderedFeatures": features, "additions": [{}] * 55}, "fittedTreatmentChecksum": "1" * 64},
            "semantic": {"fittedChecksum": "2" * 64}, "trainingModelInputValidation": guard(train), "validationModelInputValidation": guard(valid)}
        if counters["inject"] == "wrong_prepared_schema": payload["orderedFeatures"] = features[:-1]
        return train, valid, {}, payload
    class Encoder:
        def fit_transform(self, data): return data.to_numpy()
        def get_feature_names_out(self): return np.asarray(features)
    def model(family, seed, hyperparameters=None, *, native_workers=1):
        result = HistGradientBoostingClassifier(**hyperparameters, early_stopping=False, random_state=seed)
        if counters["inject"] == "wrong_parameter": result.max_iter = 3
        return result
    lab._prepare_corrected_fold = prepare
    lab._preprocessor = lambda data, feature_set, **kwargs: (Encoder(), {})
    lab._model = model
    def evaluate(data, **kwargs):
        for fold in kwargs["split"]["contract"]["folds"]:
            train, valid, _, payload = lab._prepare_corrected_fold(data, fold=fold, feature_set=kwargs["feature_set"])
            encoder, _ = lab._preprocessor(train[features], kwargs["feature_set"])
            X = encoder.fit_transform(train[features])
            estimator = lab._model(kwargs["model_family"], kwargs["seed"] + fold["foldNumber"], kwargs["hyperparameters"], native_workers=kwargs["native_workers"])
            estimator.fit(X, np.zeros(len(train)))
            if counters["inject"] == "duplicate_fit": estimator.fit(X, np.zeros(len(train)))
            if counters["inject"] == "after_fit_failure": raise PermissionError("synthetic artifact save failed")
            kwargs["progress_callback"]({"event": "FOLD_ESTIMATOR_FIT_COMPLETED", "fold": fold["foldNumber"]})
            kwargs["progress_callback"]({"event": "FOLD_COMPLETED", "fold": fold["foldNumber"]})
        return {"foldsCompleted": 5}
    lab._evaluate_candidate = evaluate
    jobs = SimpleNamespace(_evaluate_candidate=evaluate, _fold_frame=lambda *a, **k: frame)
    kwargs = {"model_family": "histogram_gradient_boosting", "feature_set": feature_set,
        "split": {"contractId": "synthetic-split", "checksum": "e" * 64, "contract": {"folds": folds}},
        "seed": 100, "hyperparameters": expected["hyperparameters"], "native_workers": 4}
    return SimpleNamespace(frame=frame, expected=expected, lab=lab, jobs=jobs, kwargs=kwargs, counters=counters)


def _run(case, path):
    with telemetry.observe_recovery(event_path=path, expected=case.expected, lab_module=case.lab, jobs_module=case.jobs) as observer:
        # Match the real job: its imported alias runs in a candidate thread.
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(case.jobs._evaluate_candidate, case.frame, **case.kwargs).result()
    return result, observer.summary()


def test_actual_thread_entry_records_five_starts_fits_and_folds_and_restores(case, tmp_path):
    before = case.lab._evaluate_candidate
    original_fit = HistGradientBoostingClassifier.fit
    result, summary = _run(case, tmp_path / "events.jsonl")
    assert result["foldsCompleted"] == 5
    assert summary["actualFitStarts"] == summary["actualFitCompletions"] == summary["completedFolds"] == 5
    assert summary["status"] == "COMPLETE"
    assert case.counters["originalFits"] == 5
    assert case.lab._evaluate_candidate is case.jobs._evaluate_candidate is before
    assert HistGradientBoostingClassifier.fit is original_fit
    assert summary == telemetry.summarize_events(tmp_path / "events.jsonl")


@pytest.mark.parametrize("fault,starts,completions", [("wrong_parameter", 0, 0), ("wrong_prepared_schema", 0, 0),
    ("fit_failure", 1, 0), ("after_fit_failure", 1, 1), ("duplicate_fit", 1, 1)])
def test_failed_attempt_never_inflates_start_or_fold_counts(case, tmp_path, fault, starts, completions):
    case.counters["inject"] = fault
    path = tmp_path / "events.jsonl"
    with pytest.raises((PermissionError, telemetry.RecoveryGuardError)):
        _run(case, path)
    summary = telemetry.summarize_events(path)
    assert summary["actualFitStarts"] == starts
    assert summary["actualFitCompletions"] == completions
    assert summary["completedFolds"] == 0
    assert summary["status"] == "FAILED"
    assert summary["failures"][-1]["traceback"]


@pytest.mark.parametrize("fault", ["manifest", "eligibility", "split", "workers", "seed", "target_order"])
def test_entry_mismatch_is_rejected_before_original_fit(case, tmp_path, fault):
    if fault == "manifest": case.kwargs["feature_set"]["transformationContracts"]["treatmentManifestChecksum"] = "f" * 64
    elif fault == "eligibility": case.expected["eligibilityChecksum"] = "f" * 64
    elif fault == "split": case.kwargs["split"]["checksum"] = "f" * 64
    elif fault == "workers": case.kwargs["native_workers"] = 1
    elif fault == "target_order": case.lab.GOLD_CLASS_ORDER = tuple(reversed(GOLD_CLASS_ORDER))
    else: case.kwargs["seed"] = 101
    with pytest.raises(telemetry.RecoveryGuardError): _run(case, tmp_path / "events.jsonl")
    assert case.counters["originalFits"] == 0
    assert telemetry.summarize_events(tmp_path / "events.jsonl")["actualFitStarts"] == 0


def test_native_pools_checked_immediately_before_original_fit(case, tmp_path, monkeypatch):
    monkeypatch.setattr(threadpoolctl, "threadpool_info", lambda: [{"user_api": "openmp", "num_threads": 1}])
    with pytest.raises(telemetry.RecoveryGuardError, match="four workers"):
        _run(case, tmp_path / "events.jsonl")
    assert case.counters["originalFits"] == 0


def test_source_failure_before_evaluate_has_durable_traceback(case, tmp_path):
    def broken_source(*args, **kwargs): raise PermissionError("synthetic source AccessDenied")
    case.jobs._fold_frame = broken_source
    path = tmp_path / "events.jsonl"
    with pytest.raises(PermissionError):
        with telemetry.observe_recovery(event_path=path, expected=case.expected, lab_module=case.lab, jobs_module=case.jobs):
            case.jobs._fold_frame()
    summary = telemetry.summarize_events(path)
    assert summary["actualFitStarts"] == 0
    assert summary["failures"][0]["stage"] == "SOURCE_FRAME_LOAD"


def test_final_oot_is_rejected_before_eligibility_or_target_access(case, tmp_path, monkeypatch):
    case.frame.loc[0, "game_date"] = "2026-08-14"
    monkeypatch.setattr(eligibility, "eligibility_mask", lambda *a, **k: pytest.fail("OOT feature payload accessed"))
    with pytest.raises(telemetry.RecoveryGuardError, match="FINAL_OOT_SEALED"):
        _run(case, tmp_path / "events.jsonl")
    assert case.counters["originalFits"] == 0


def test_log_is_append_only_and_hash_tampering_is_never_repaired(case, tmp_path):
    path = tmp_path / "events.jsonl"
    _run(case, path)
    original = path.read_bytes()
    with pytest.raises(FileExistsError): _run(case, path)
    assert path.read_bytes() == original
    rows = original.splitlines()
    changed = json.loads(rows[1])
    changed["eligibleRows"] = 123
    rows[1] = json.dumps(changed).encode()
    path.write_bytes(b"\n".join(rows) + b"\n")
    with pytest.raises(telemetry.RecoveryGuardError, match="hash chain"):
        telemetry.summarize_events(path)


def test_unregistered_hgb_fit_and_second_candidate_are_prohibited(case, tmp_path):
    path = tmp_path / "events.jsonl"
    with telemetry.observe_recovery(event_path=path, expected=case.expected, lab_module=case.lab, jobs_module=case.jobs):
        with pytest.raises(telemetry.RecoveryGuardError, match="one-shot"):
            HistGradientBoostingClassifier().fit(np.ones((2, 2)), np.zeros(2))
        case.jobs._evaluate_candidate(case.frame, **case.kwargs)
        with pytest.raises(telemetry.RecoveryGuardError, match="retries"):
            case.jobs._evaluate_candidate(case.frame, **case.kwargs)
    summary = telemetry.summarize_events(path)
    assert summary["actualFitStarts"] == 5
    assert summary["status"] == "FAILED"


def test_real_model_lab_entry_and_preprocessor_are_reached_with_stubbed_fits(case, tmp_path, monkeypatch):
    from server.sports_current_statcast import stage3_model_laboratory as real_lab
    from server.sports_current_statcast import stage3_corrected_preprocessing_artifacts as artifacts
    case.frame["canonicalGameId"] = [f"game-{n}" for n in range(7)]
    case.frame["canonicalPaId"] = [f"pa-{n}" for n in range(7)]
    case.frame["outcome"] = list(real_lab.GOLD_CLASS_ORDER)[:7]
    for fold in case.expected["folds"]:
        fold["trainGames"] = fold["trainRows"]
        fold["validationGames"] = fold["validationRows"]
    # The caller's split and expected folds share these fixture dictionaries.
    for row in case.kwargs["feature_set"]["transformationContracts"]["ordered"]:
        row["steps"] = ["SEMANTIC_NUMERIC_PASSTHROUGH"]
    stub_prepare = case.lab._prepare_corrected_fold
    def prepared(source, **kwargs):
        train, valid, evidence, payload = stub_prepare(source, **kwargs)
        payload.update(sourceColumns=[name for name in source if name != "outcome"],
            trainingBranchCounts={}, validationBranchCounts={}, rowEligibility={})
        return train, valid, evidence, payload
    monkeypatch.setattr(real_lab, "_prepare_corrected_fold", prepared)
    def fit_stub(estimator, X, y):
        case.counters["originalFits"] += 1
        estimator.classes_ = np.arange(8)
        estimator.n_features_in_ = X.shape[1]
        estimator._predictors = [[]]
        return estimator
    monkeypatch.setattr(HistGradientBoostingClassifier, "fit", fit_stub)
    monkeypatch.setattr(HistGradientBoostingClassifier, "predict_proba", lambda estimator, X: np.full((len(X), 8), 0.125))
    # Persistence itself has separate integration coverage; no stubbed model is
    # exported. This test uses the real evaluate, encoder and model constructor.
    monkeypatch.setattr(artifacts, "persist_json", lambda *a, **k: {"sha256": "1" * 64})
    monkeypatch.setattr(artifacts, "persist_and_verify", lambda **k: {
        "preprocessing": {"sha256": "2" * 64}, "model": {"sha256": "3" * 64},
        "status": "SYNTHETIC_STUB_NO_MODEL_EXPORTED"})
    monkeypatch.setenv("ATLAS_STAGE3_MODEL_LAB_ROOT", str(tmp_path))
    case.expected["estimatorParametersByFold"] = {
        str(fold): real_lab._model("histogram_gradient_boosting", 100 + fold,
            hyperparameters=case.expected["hyperparameters"], native_workers=4).get_params(deep=False)
        for fold in range(1, 6)
    }
    case.lab = real_lab
    case.jobs = SimpleNamespace(_evaluate_candidate=real_lab._evaluate_candidate, _fold_frame=lambda *a, **k: case.frame)
    result, summary = _run(case, tmp_path / "actual-entry-events.jsonl")
    assert result["foldsCompleted"] == 5
    assert summary["actualFitStarts"] == summary["actualFitCompletions"] == summary["completedFolds"] == 5
    assert case.counters["originalFits"] == 5
