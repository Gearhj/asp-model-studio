"""Scoped, append-only observation of the single authorized corrected recovery.

This module does not schedule work, load sports data, register authority, retry,
or edit the frozen implementation. Install its context around dispatch AND the
terminal wait: the job module imports its own evaluation alias and uses threads.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from weakref import WeakKeyDictionary

_INSTALL_LOCK = threading.Lock()
EVENT_SCHEMA = "MLB_HGB_RECOVERY_EVENT_V1"
ACCOUNTING_SCHEMA = "MLB_HGB_RECOVERY_FIT_ACCOUNTING_V1"
_TARGETS = {"outcome", "target", "label", "observedClassIndex", "y"}


class RecoveryGuardError(RuntimeError):
    pass


def _bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryGuardError(message)


def summarize_events(path: Path | str) -> dict[str, Any]:
    """Read-only chain verification and counts; never repairs an incomplete log."""
    path = Path(path).resolve()
    raw = path.read_bytes()
    _require(bool(raw) and raw.endswith(b"\n"), "Telemetry is empty or has an incomplete append.")
    rows = [json.loads(line) for line in raw.splitlines()]
    previous = None
    recovery = rows[0].get("recoveryId")
    starts: list[int] = []
    fits: list[int] = []
    folds: list[int] = []
    failures = []
    for index, row in enumerate(rows, 1):
        content = {key: value for key, value in row.items() if key != "eventSha256"}
        _require(row.get("schemaVersion") == EVENT_SCHEMA and row.get("sequence") == index
                 and row.get("previousEventSha256") == previous and row.get("eventSha256") == _sha(content)
                 and row.get("recoveryId") == recovery, "Telemetry sequence, identity or hash chain is invalid.")
        previous = row["eventSha256"]
        event, fold = row.get("event"), row.get("foldNumber")
        if event in {"FIT_STARTED", "FIT_COMPLETED", "FOLD_COMPLETED"}:
            _require(type(fold) is int and 1 <= fold <= 5, "Telemetry fold is outside the five-fit scope.")
            if event == "FIT_STARTED":
                _require(fold not in starts and fold == len(starts) + 1 and len(folds) == len(starts), "A duplicate or overlapping fit start was recorded.")
                starts.append(fold)
            elif event == "FIT_COMPLETED":
                _require(fold in starts and fold not in fits and fold == len(fits) + 1, "Fit completion lacks one unique actual start.")
                fits.append(fold)
            else:
                _require(fold in fits and fold not in folds and fold == len(folds) + 1, "Fold completion lacks a completed actual fit.")
                folds.append(fold)
        if event == "FAILURE":
            failures.append({key: row.get(key) for key in ("sequence", "stage", "foldNumber", "exceptionType", "message", "traceback")})
    complete = folds == [1, 2, 3, 4, 5] and any(row.get("event") == "CANDIDATE_COMPLETED" for row in rows)
    content = {
        "schemaVersion": ACCOUNTING_SCHEMA, "recoveryId": recovery,
        "eventPath": str(path), "eventCount": len(rows), "eventsSha256": hashlib.sha256(raw).hexdigest(),
        "lastEventChecksum": previous, "actualFitStarts": len(starts), "actualFitCompletions": len(fits),
        "completedFolds": len(folds), "startedFoldNumbers": starts, "fitCompletedFoldNumbers": fits,
        "completedFoldNumbers": folds, "status": "FAILED" if failures else "COMPLETE" if complete else "NOT_COMPLETE",
        "failures": failures,
    }
    return {**content, "accountingChecksum": _sha(content)}


class RecoveryObserver:
    def __init__(self, event_path: Path, expected: Mapping[str, Any]) -> None:
        self.expected = copy.deepcopy(dict(expected))
        self.path = event_path.resolve()
        self._lock = threading.RLock()
        self._local = threading.local()
        self._sequence = 0
        self._previous = None
        self._candidate_entered = False
        self._candidate_running = False
        self._models: WeakKeyDictionary[Any, dict[str, Any]] = WeakKeyDictionary()
        self._validate_expectation()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prohibits replay/restart over an earlier attempt.
        self._fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
        self._emit("OBSERVER_INSTALLED", expectationChecksum=_sha(self.expected))

    def _validate_expectation(self) -> None:
        e = self.expected
        _require(bool(e.get("recoveryId")), "An explicit recovery identity is required.")
        for key in ("treatmentManifestChecksum", "featureSetChecksum", "modelFeatureSchemaChecksum", "eligibilityChecksum", "splitChecksum"):
            _require(isinstance(e.get(key), str) and len(e[key]) == 64, f"Exact {key} is required.")
        _require(bool(e.get("featureSetId")), "Exact feature-set identity is required.")
        _require(bool(e.get("splitContractId")), "Exact split identity is required.")
        _require(isinstance(e.get("targetOrder"), list) and len(e["targetOrder"]) == 8 and len(set(e["targetOrder"])) == 8,
                 "The exact eight-class target order is required.")
        _require(e.get("nativeWorkers") == 4, "Recovery requires exactly four native workers.")
        _require(len(e.get("orderedFeatures", [])) == 273 and len(set(e["orderedFeatures"])) == 273
                 and len(e.get("sourceOrderedFeatures", [])) == 218
                 and e["orderedFeatures"][:218] == e["sourceOrderedFeatures"], "Recovery must preserve the 218-source plus55-output schema.")
        _require([fold.get("foldNumber") for fold in e.get("folds", [])] == [1, 2, 3, 4, 5], "Exactly five ordered registered folds are required.")
        _require(e.get("sourceRows") == 683662 and e.get("eligibleRows") == 683606 and e.get("heldRows") == 56,
                 "Recovery must bind the exact reviewed Development eligibility counts.")
        _require(type(e.get("baseSeed")) is int and isinstance(e.get("hyperparameters"), dict), "Exact seed and hyperparameters are required.")
        _require(isinstance(e.get("boundSourceHashes"), dict) and bool(e["boundSourceHashes"]), "Frozen implementation source hashes are required.")
        for fold in range(1, 6):
            parameters = e.get("estimatorParametersByFold", {}).get(str(fold), e.get("estimatorParametersByFold", {}).get(fold))
            _require(isinstance(parameters, dict) and parameters.get("random_state") == e["baseSeed"] + fold
                     and parameters.get("early_stopping") is False, "Every fold requires exact effective estimator parameters and seed.")

    def _emit(self, event: str, **details: Any) -> None:
        with self._lock:
            content = {"schemaVersion": EVENT_SCHEMA, "sequence": self._sequence + 1,
                "previousEventSha256": self._previous, "recoveryId": self.expected["recoveryId"],
                "event": event, "utc": datetime.now(timezone.utc).isoformat(), "processId": os.getpid(),
                "threadId": threading.get_ident(), **details}
            row = {**content, "eventSha256": _sha(content)}
            blob = _bytes(row) + b"\n"
            view = memoryview(blob)
            while view:
                written = os.write(self._fd, view)
                _require(written > 0, "Telemetry append did not advance.")
                view = view[written:]
            os.fsync(self._fd)
            self._sequence += 1
            self._previous = row["eventSha256"]

    def _failure(self, stage: str, exc: BaseException) -> None:
        context = getattr(self._local, "context", None) or {}
        self._emit("FAILURE", stage=stage, foldNumber=context.get("foldNumber"),
                   exceptionType=type(exc).__name__, message=str(exc),
                   traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))

    def _check_sources(self) -> None:
        for path, checksum in self.expected["boundSourceHashes"].items():
            _require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == checksum,
                     f"Frozen implementation source changed: {path}")

    def _contract(self, feature_set: Mapping[str, Any]) -> None:
        e, contract = self.expected, feature_set.get("transformationContracts") or {}
        _require(feature_set.get("featureSetId") == e["featureSetId"] and feature_set.get("checksum") == e["featureSetChecksum"], "Feature-set identity differs from recovery authority.")
        _require(contract.get("semanticTreatmentVersion") == "MLB_SEMANTIC_TREATMENT_V1"
                 and contract.get("treatmentManifestChecksum") == e["treatmentManifestChecksum"]
                 and contract.get("modelFeatureSchemaChecksum") == e["modelFeatureSchemaChecksum"]
                 and contract.get("sourceOrderedFeatures") == e["sourceOrderedFeatures"]
                 and feature_set.get("orderedFeatures") == e["orderedFeatures"], "The actual entry is not the frozen V18 273-input authority.")
        _require([row.get("feature") for row in contract.get("ordered", [])] == e["orderedFeatures"], "Actual ordered transformations do not match the 273-input schema.")

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return summarize_events(self.path)

    def close(self) -> None:
        _require(not self._candidate_running, "Keep the telemetry scope active until the candidate thread is terminal.")
        self._emit("OBSERVER_CLOSED")
        os.close(self._fd)


@contextmanager
def observe_recovery(*, event_path: Path | str, expected: Mapping[str, Any], lab_module: Any = None, jobs_module: Any = None):
    """Observe dispatch-to-terminal execution; never submits or retries a job."""
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import HistGradientBoostingClassifier
    from threadpoolctl import threadpool_info
    from .stage3_corrected_eligibility import eligibility_mask

    if lab_module is None:
        from . import stage3_model_laboratory as lab_module
    if jobs_module is None:
        from . import stage3_model_jobs as jobs_module
    _require(_INSTALL_LOCK.acquire(blocking=False), "A recovery telemetry scope is already active.")
    observer = None
    originals: list[tuple[Any, str, Any]] = []
    try:
        observer = RecoveryObserver(Path(event_path), expected)
        e = observer.expected
        original_evaluate = lab_module._evaluate_candidate
        original_prepare = lab_module._prepare_corrected_fold
        original_model = lab_module._model
        original_preprocessor = lab_module._preprocessor
        original_fit = HistGradientBoostingClassifier.fit
        original_fold_frame = jobs_module._fold_frame

        def fold_frame(*args, **kwargs):
            try:
                return original_fold_frame(*args, **kwargs)
            except BaseException as exc:
                observer._failure("SOURCE_FRAME_LOAD", exc)
                raise

        def evaluate(frame, **kwargs):
            entered = False
            try:
                with observer._lock:
                    _require(not observer._candidate_entered, "Only one candidate invocation is authorized; retries are prohibited.")
                    observer._candidate_entered = observer._candidate_running = True
                    entered = True
                observer._check_sources()
                observer._contract(kwargs.get("feature_set") or {})
                _require(list(lab_module.GOLD_CLASS_ORDER) == e["targetOrder"], "The executable class order differs from frozen recovery authority.")
                _require(kwargs.get("model_family") == "histogram_gradient_boosting"
                         and kwargs.get("seed") == e["baseSeed"] and kwargs.get("hyperparameters") == e["hyperparameters"]
                         and kwargs.get("native_workers") == 4 and not kwargs.get("fold_local_selector")
                         and not kwargs.get("artifact_callback"), "Candidate configuration or scope differs from the one authorized recovery.")
                split = kwargs.get("split") or {}
                _require(split.get("contract", {}).get("folds") == e["folds"]
                         and split.get("contractId") == e["splitContractId"]
                         and split.get("checksum") == e["splitChecksum"], "Actual split identity or folds differ from frozen recovery authority.")
                dates = pd.to_datetime(frame["game_date"], errors="coerce")
                _require(not dates.isna().any() and dates.between("2023-03-30", "2026-08-13").all(), "FINAL_OOT_SEALED: recovery rejected dates before target or feature access.")
                source = frame.drop(columns=[name for name in _TARGETS if name in frame])
                eligible, evidence = eligibility_mask(source, kwargs["feature_set"])
                _require(len(frame) == e["sourceRows"] and int(eligible.sum()) == e["eligibleRows"]
                         and int((~eligible).sum()) == e["heldRows"] and evidence.get("eligibilityChecksum") == e["eligibilityChecksum"]
                         and evidence.get("sourceRows") == e["sourceRows"] and evidence.get("eligibleRows") == e["eligibleRows"]
                         and evidence.get("heldRows") == e["heldRows"], "Actual full Development eligibility differs from the frozen reviewed mask.")
                fold_counts = {}
                for fold in e["folds"]:
                    train = dates.between(fold["trainStart"], fold["trainEnd"]).to_numpy()
                    validation = dates.between(fold["validationStart"], fold["validationEnd"]).to_numpy()
                    _require(int(train.sum()) == fold["trainRows"] and int(validation.sum()) == fold["validationRows"], "Original registered fold counts differ before fit.")
                    fold_counts[fold["foldNumber"]] = {"trainRows": int((train & eligible).sum()), "validationRows": int((validation & eligible).sum())}
                    _require(all(fold_counts[fold["foldNumber"]].values()), "Eligibility emptied an authorized fold.")
                observer._local.context = {"completedFolds": [], "fitStarted": [], "fitCompleted": [], "foldCounts": fold_counts}
                observer._emit("CANDIDATE_AUTHORITY_VERIFIED", eligibilityChecksum=evidence["eligibilityChecksum"],
                               sourceRows=e["sourceRows"], eligibleRows=e["eligibleRows"], heldRows=e["heldRows"],
                               treatmentManifestChecksum=e["treatmentManifestChecksum"], modelFeatureCount=273, physicalSourceFeatureCount=218,
                               targetOrder=e["targetOrder"], foldEligibleCounts=fold_counts)
                old_progress = kwargs.get("progress_callback")
                def progress(event):
                    context = observer._local.context
                    if old_progress is not None:
                        old_progress(event)
                    if event.get("event") == "FOLD_COMPLETED":
                        fold = event.get("fold")
                        _require(fold in context["fitCompleted"] and fold not in context["completedFolds"], "Fold completion lacks a unique completed fit.")
                        observer._emit("FOLD_COMPLETED", foldNumber=fold)
                        context["completedFolds"].append(fold)
                kwargs["progress_callback"] = progress
                result = original_evaluate(frame, **kwargs)
                _require(observer._local.context["completedFolds"] == [1, 2, 3, 4, 5], "Candidate returned without five actual completed folds.")
                observer._emit("CANDIDATE_COMPLETED")
                return result
            except BaseException as exc:
                observer._failure("CANDIDATE_EXECUTION", exc)
                raise
            finally:
                if entered:
                    observer._candidate_running = False
                    observer._local.context = None

        def prepare(frame, **kwargs):
            try:
                context = getattr(observer._local, "context", None)
                _require(context is not None, "Prepared fold is outside the observed candidate thread.")
                fold = kwargs["fold"]["foldNumber"]
                _require(fold == len(context["completedFolds"]) + 1 and kwargs["fold"] == e["folds"][fold - 1], "Prepared fold is duplicated, reordered or outside scope.")
                context["foldNumber"] = fold
                context.pop("attestation", None)
                context.pop("encoder", None)
                observer._contract(kwargs["feature_set"])
                result = original_prepare(frame, **kwargs)
                train, validation, _, payload = result
                schema = payload.get("prior", {}).get("outputSchema", {})
                _require(payload.get("schemaVersion") == "MLB_CORRECTED_FITTED_PREPROCESSING_V1"
                         and payload.get("orderedFeatures") == e["orderedFeatures"]
                         and payload.get("sourceOrderedFeatures") == e["sourceOrderedFeatures"]
                         and schema.get("orderedFeatures") == e["orderedFeatures"] and len(schema.get("additions", [])) == 55
                         and payload.get("transformationContracts") == kwargs["feature_set"]["transformationContracts"], "Prepared fold payload does not attest the frozen corrected schema.")
                for label, value in (("training", train), ("validation", validation)):
                    guard = payload.get(f"{label}ModelInputValidation", {})
                    _require(guard.get("status") == "PASS" and guard.get("modelFeatureCount") == 273
                             and guard.get("rows") == len(value) and guard.get("ordinaryFallbackRows") == 0
                             and guard.get("targetColumnsRead") == [] and guard.get("finalOotRowsRead") == 0
                             and not (_TARGETS & set(value.columns)), "Prepared model-input validation evidence is absent or unsafe.")
                _require(len(train) == context["foldCounts"][fold]["trainRows"] and len(validation) == context["foldCounts"][fold]["validationRows"], "Prepared eligible row counts differ from the verified original mask.")
                attestation = {"foldNumber": fold, "treatmentManifestChecksum": e["treatmentManifestChecksum"],
                    "modelFeatureSchemaChecksum": e["modelFeatureSchemaChecksum"], "modelFeatureCount": 273, "physicalSourceFeatureCount": 218,
                    "trainRows": len(train), "validationRows": len(validation),
                    "trainingValidationChecksum": payload["trainingModelInputValidation"].get("evidenceChecksum"),
                    "validationValidationChecksum": payload["validationModelInputValidation"].get("evidenceChecksum"),
                    "semanticFittedChecksum": payload.get("semantic", {}).get("fittedChecksum"),
                    "priorFittedChecksum": payload.get("prior", {}).get("fittedTreatmentChecksum")}
                context["attestation"] = {**attestation, "attestationChecksum": _sha(attestation)}
                observer._emit("PREPARED_FOLD_ATTESTED", **context["attestation"])
                return result
            except BaseException as exc:
                observer._failure("FOLD_PREPARATION", exc)
                raise

        def preprocessor(frame, feature_set, **kwargs):
            context = getattr(observer._local, "context", None)
            _require(context is not None and context.get("attestation"), "Encoder construction lacks prepared-fold authority.")
            observer._contract(feature_set)
            _require(list(frame.columns) == e["orderedFeatures"] and len(frame) == context["attestation"]["trainRows"], "Encoder input is not the actual prepared273 training schema.")
            result = original_preprocessor(frame, feature_set, **kwargs)
            context["encoder"] = result[0]
            return result

        def model(family, seed, hyperparameters=None, *, native_workers=1):
            context = getattr(observer._local, "context", None)
            _require(context is not None and context.get("attestation") and context.get("encoder") is not None, "Estimator construction lacks actual prepared-fold evidence.")
            fold = context["foldNumber"]
            _require(family == "histogram_gradient_boosting" and seed == e["baseSeed"] + fold
                     and hyperparameters == e["hyperparameters"] and native_workers == 4, "Estimator constructor differs from the authorized configuration.")
            estimator = original_model(family, seed, hyperparameters=hyperparameters, native_workers=native_workers)
            _require(type(estimator) is HistGradientBoostingClassifier, "Estimator is not the exact HGB class.")
            observer._models[estimator] = {"context": context, "fold": fold, "used": False}
            return estimator

        def fit(estimator, X, y, *args, **kwargs):
            try:
                registration = observer._models.get(estimator)
                context = getattr(observer._local, "context", None)
                _require(registration is not None and context is registration["context"] and not registration["used"], "HGB fit is outside the one-shot attested recovery path.")
                fold = registration["fold"]
                _require(fold not in context["fitStarted"] and fold == len(context["fitStarted"]) + 1
                         and len(context["completedFolds"]) == len(context["fitStarted"]), "An extra, duplicate or overlapping fit is prohibited.")
                observer._check_sources()
                expected_params = e["estimatorParametersByFold"].get(str(fold), e["estimatorParametersByFold"].get(fold))
                _require(estimator.get_params(deep=False) == expected_params, "Effective HGB parameters or seed differ immediately before fit.")
                pools = threadpool_info()
                native = [pool for pool in pools if pool.get("user_api") in {"blas", "openmp"}]
                _require(bool(native) and all(pool.get("num_threads") == 4 for pool in native), "Actual native thread pools are not all bounded to four workers.")
                names = context["encoder"].get_feature_names_out().tolist()
                _require(len(X.shape) == 2 and X.shape[0] == len(y) == context["attestation"]["trainRows"]
                         and X.shape[1] == len(names) and len(names) >= 273, "Actual fit matrix does not match the prepared/fitted encoder.")
                _require(not args and not kwargs, "Unexpected fit metadata or sample weighting is not authorized.")
                observer._emit("FIT_STARTED", foldNumber=fold, estimatorParameters=expected_params,
                    actualNativePools=[{key: pool.get(key) for key in ("user_api", "internal_api", "num_threads")} for pool in native],
                    matrixShape=[int(size) for size in X.shape], transformedFeatureNamesChecksum=_sha(names),
                    preparedFoldAttestationChecksum=context["attestation"]["attestationChecksum"])
                registration["used"] = True
                context["fitStarted"].append(fold)
                result = original_fit(estimator, X, y)
                observer._emit("FIT_COMPLETED", foldNumber=fold)
                context["fitCompleted"].append(fold)
                return result
            except BaseException as exc:
                observer._failure("ESTIMATOR_FIT", exc)
                raise

        for owner, name, replacement in ((lab_module, "_evaluate_candidate", evaluate), (jobs_module, "_evaluate_candidate", evaluate),
            (jobs_module, "_fold_frame", fold_frame),
            (lab_module, "_prepare_corrected_fold", prepare), (lab_module, "_preprocessor", preprocessor),
            (lab_module, "_model", model), (HistGradientBoostingClassifier, "fit", fit)):
            originals.append((owner, name, getattr(owner, name)))
            setattr(owner, name, replacement)
        yield observer
    except BaseException as exc:
        if observer is not None:
            observer._failure("OBSERVER_SCOPE", exc)
        raise
    finally:
        # Restoring class hooks while a fit is live would erase the completion
        # observation. The caller must wait for its dispatched job to terminate.
        if observer is not None:
            _require(not observer._candidate_running, "Recovery scope exited while the candidate thread is still live; observation hooks remain installed.")
        for owner, name, original in reversed(originals):
            setattr(owner, name, original)
        try:
            if observer is not None:
                observer.close()
        finally:
            _INSTALL_LOCK.release()
