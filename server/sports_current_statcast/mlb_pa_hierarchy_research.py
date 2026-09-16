"""Lossless, research-only hierarchy over the unchanged eight V18 PA labels.

OUT_CLASS/NON_OUT_CLASS are terminal-label families, not runner/outs rules.
Dropped third strikes, sacrifices, fielder's choices and runner outs retain the
original label; the existing transition engine determines actual advancement.
This module performs no source acquisition, cohort selection or production I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER

OUT_INDICES = (0, 6)
NON_OUT_INDICES = (1, 2, 3, 4, 5, 7)
CLASS_ORDER = tuple(PA_CLASS_ORDER)
FAMILY_CONTRACT = {
    "classOrder": list(CLASS_ORDER),
    "OUT_CLASS": [CLASS_ORDER[i] for i in OUT_INDICES],
    "NON_OUT_CLASS": [CLASS_ORDER[i] for i in NON_OUT_INDICES],
    "rootPositiveClass": "OUT_CLASS",
    "semantics": "FAMILIES_OF_EXISTING_TERMINAL_LABELS_NOT_NUMBER_OF_ACTUAL_OUTS_OR_SAFE_RUNNERS",
}


def _matrix(values: Any, columns: int, label: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    if result.ndim != 2 or result.shape[1] != columns:
        raise ValueError(f"{label}: expected N x {columns}")
    if not np.isfinite(result).all() or (result < 0).any() or (result > 1).any():
        raise ValueError(f"{label}: invalid probabilities")
    if not np.allclose(result.sum(axis=1), 1.0, rtol=0, atol=1e-12):
        raise ValueError(f"{label}: rows must sum to one")
    return result


def target_indices(labels: Sequence[Any]) -> np.ndarray:
    values = np.asarray(labels)
    if values.ndim != 1:
        raise ValueError("One terminal class per PA is required")
    if np.issubdtype(values.dtype, np.integer):
        result = values.astype(np.int64)
        if ((result < 0) | (result >= len(CLASS_ORDER))).any():
            raise ValueError("Target index outside preserved eight-class order")
        return result
    mapping = {name: i for i, name in enumerate(CLASS_ORDER)}
    try:
        return np.array([mapping[str(value)] for value in values], dtype=np.int64)
    except KeyError as exc:
        raise ValueError("Unknown terminal class; mappings may not be changed") from exc


def assemble_probabilities(out_probability, out_conditional, non_out_conditional) -> np.ndarray:
    """Soft multiplication preserves every class and never hard-routes a PA."""
    q = np.asarray(out_probability, dtype=np.float64)
    out = _matrix(out_conditional, 2, "out head")
    non_out = _matrix(non_out_conditional, 6, "non-out head")
    if q.ndim != 1 or len(q) != len(out) or len(q) != len(non_out):
        raise ValueError("Root/head row identities must align")
    if not np.isfinite(q).all() or (q < 0).any() or (q > 1).any():
        raise ValueError("Root probability outside [0,1]")
    result = np.empty((len(q), 8), dtype=np.float64)
    result[:, OUT_INDICES] = q[:, None] * out
    result[:, NON_OUT_INDICES] = (1.0-q[:, None]) * non_out
    return _matrix(result, 8, "assembled eight-class vector")


def loss_decomposition(probabilities, labels, *, floor: float = 1e-15) -> dict:
    """Score a copy: eight-class NLL = root NLL + relevant conditional NLL.

    Apply the same eight-class floor/row-normalization to every arm before
    decomposition. Stored V18 values remain unchanged. Branch means use only
    observations in that family; branch contributions use all-PA weighting.
    """
    if not 0 < floor < 1/8:
        raise ValueError("Probability floor must be between zero and 1/8")
    original = _matrix(probabilities, 8, "eight-class input")
    y = target_indices(labels)
    if len(y) != len(original) or not len(y):
        raise ValueError("Nonempty identical probability/target populations required")
    p = np.maximum(original, floor)
    p /= p.sum(axis=1, keepdims=True)
    out = np.isin(y, OUT_INDICES)
    q = p[:, OUT_INDICES].sum(axis=1)
    family_probability = np.where(out, q, p[:, NON_OUT_INDICES].sum(axis=1))
    event_probability = p[np.arange(len(y)), y]
    root_loss = -np.log(family_probability)
    branch_loss = -np.log(event_probability/family_probability)
    eight_loss = -np.log(event_probability)
    difference = float(np.max(np.abs(eight_loss-root_loss-branch_loss)))
    if difference > 1e-12:
        raise ValueError("Lossless hierarchy decomposition failed")
    return {"rows": len(y), "rootLogLoss": float(root_loss.mean()),
        "eightClassLogLoss": float(eight_loss.mean()),
        "summedMulticlassBrier": float(np.mean(np.sum((p-np.eye(8)[y])**2, axis=1))),
        "conditionalHeadLogLoss": float(branch_loss.mean()),
        "outRows": int(out.sum()), "nonOutRows": int((~out).sum()),
        "outHeadLogLoss": float(branch_loss[out].mean()) if out.any() else None,
        "nonOutHeadLogLoss": float(branch_loss[~out].mean()) if (~out).any() else None,
        "outHeadAllPaContribution": float(np.where(out, branch_loss, 0).mean()),
        "nonOutHeadAllPaContribution": float(np.where(~out, branch_loss, 0).mean()),
        "classCounts": {name: int((y == i).sum()) for i, name in enumerate(CLASS_ORDER)},
        "maximumDecompositionDifference": difference,
        "maximumNormalizationError": float(np.max(np.abs(p.sum(axis=1)-1))),
        "scoringConvention": {"eightClassFloor": floor, "renormalizeScoringCopy": True,
            "storedPredictionsChanged": False},
        "perRow": {"rootNll": root_loss, "conditionalNll": branch_loss, "eightClassNll": eight_loss,
            "outFamily": out}}


@dataclass
class RegularizedHead:
    """Fitted classifier + declared uniform pseudo-count mass for absent classes.

    No class oversampling or weighting. A one-class training branch receives a
    documented smoothed-frequency head, not an invented fitted classifier.
    """
    estimator: Any
    counts: np.ndarray
    alpha_per_class: float

    @property
    def frequency(self):
        return (self.counts+self.alpha_per_class)/(self.counts.sum()+len(self.counts)*self.alpha_per_class)

    def predict_proba(self, x):
        n, k = len(x), len(self.counts)
        if self.estimator is None:
            return np.tile(self.frequency, (n, 1))
        raw = np.asarray(self.estimator.predict_proba(x), dtype=float)
        aligned = np.zeros((n, k), dtype=float)
        for column, label in enumerate(self.estimator.classes_):
            integer = int(label)
            if label != integer or not 0 <= integer < k:
                raise ValueError("Conditional estimator class contract differs")
            aligned[:, integer] = raw[:, column]
        _matrix(aligned, k, "fitted head")
        weight = self.counts.sum()/(self.counts.sum()+k*self.alpha_per_class)
        return _matrix(weight*aligned+(1-weight)/k, k, "regularized head")


@dataclass
class HierarchicalPaModel:
    mode: str
    feature_order: tuple[str, ...]
    frozen_preprocessor: Any
    root: RegularizedHead
    out_head: RegularizedHead
    non_out_head: RegularizedHead
    training_authority: dict
    fit_accounting: dict

    def _features(self, frame):
        if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != self.feature_order:
            raise ValueError("Exact frozen ordered feature contract required")
        return self.frozen_preprocessor.transform(frame) if self.frozen_preprocessor is not None else frame.to_numpy()

    def predict_proba(self, frame):
        x = self._features(frame)
        root = self.root.predict_proba(x)[:, 1]
        if self.mode == "B_INFORMATION_REDUCTION":
            out = np.tile(self.out_head.frequency, (len(frame), 1))
            non_out = np.tile(self.non_out_head.frequency, (len(frame), 1))
        elif self.mode == "C_LEARNED_HIERARCHY":
            out, non_out = self.out_head.predict_proba(x), self.non_out_head.predict_proba(x)
        else:
            raise ValueError("Unregistered hierarchy mode")
        return assemble_probabilities(root, out, non_out)

    def metadata(self):
        return {"schemaVersion": "MLB_PA_HIERARCHY_RESEARCH_ARTIFACT_V1", "mode": self.mode,
            "featureOrder": list(self.feature_order), "familyContract": FAMILY_CONTRACT,
            "trainingAuthority": self.training_authority, "fitAccounting": self.fit_accounting,
            "calibration": {"status": "IDENTITY_NOT_FITTED", "temperature": 1.0,
                "requirement": "Any later calibrator must fit earlier disjoint evidence on final eight-class vector"},
            "heads": {key: {"counts": head.counts.tolist(), "alphaPerClass": head.alpha_per_class,
                "hasFittedEstimator": head.estimator is not None,
                "missingClassRule": "UNIFORM_PSEUDOCOUNT_MASS_NO_OVERSAMPLING"}
                for key, head in (("root", self.root), ("out", self.out_head), ("nonOut", self.non_out_head))},
            "researchOnly": True, "wageringAuthority": False, "finalOotAccessed": False}


def fit_hierarchies(training_frame, training_labels, *, frozen_preprocessor, estimator_template,
                    training_authority: Mapping, alpha_per_class: float = 0.5):
    """Fit one shared root and at most two learned heads, on one authorized prefix.

    The caller must freeze timing/cohort authority before reading training labels.
    This function never fits a preprocessor, adds features or changes V18.
    """
    authority = dict(training_authority)
    if (authority.get("candidateFitAuthorized") is not True or not authority.get("cohortId")
            or not authority.get("trainingInformationCutoffExclusive")
            or authority.get("scope") not in {"SYNTHETIC_FIXTURE_ONLY", "AUTHORIZED_RECONSTRUCTED_DEVELOPMENT"}):
        raise ValueError("Frozen eligible cohort/declaration authority required before candidate fit")
    if not isinstance(training_frame, pd.DataFrame) or training_frame.columns.duplicated().any():
        raise ValueError("Unique ordered feature DataFrame required")
    if not np.isfinite(alpha_per_class) or alpha_per_class <= 0:
        raise ValueError("Positive predeclared branch regularization required")
    y = target_indices(training_labels)
    if len(y) != len(training_frame) or not len(y):
        raise ValueError("Nonempty matching training population required")
    x = frozen_preprocessor.transform(training_frame) if frozen_preprocessor is not None else training_frame.to_numpy()
    is_out = np.isin(y, OUT_INDICES)
    fits = []

    def fit_head(features, labels, k, name):
        counts = np.bincount(labels, minlength=k)
        estimator = None
        if len(np.unique(labels)) >= 2:
            estimator = clone(estimator_template)
            estimator.fit(features, labels)
            fits.append(name)
        return RegularizedHead(estimator, counts.astype(np.int64), alpha_per_class)

    root = fit_head(x, is_out.astype(int), 2, "ROOT")
    out_map, non_map = {c: i for i, c in enumerate(OUT_INDICES)}, {c: i for i, c in enumerate(NON_OUT_INDICES)}
    out_head = fit_head(x[is_out], np.array([out_map[i] for i in y[is_out]], dtype=int), 2, "OUT_HEAD")
    non_head = fit_head(x[~is_out], np.array([non_map[i] for i in y[~is_out]], dtype=int), 6, "NON_OUT_HEAD")
    accounting = {"actualEstimatorFits": len(fits), "fittedHeads": fits,
        "rootSharedExactlyBetweenBAndC": True, "preprocessorFits": 0,
        "trainingRows": len(y), "trainingOnlyFrequencyStates": 2,
        "scope": authority["scope"]}
    common = dict(feature_order=tuple(training_frame.columns), frozen_preprocessor=frozen_preprocessor,
        root=root, out_head=out_head, non_out_head=non_head,
        training_authority=authority, fit_accounting=accounting)
    return HierarchicalPaModel(mode="B_INFORMATION_REDUCTION", **common), HierarchicalPaModel(mode="C_LEARNED_HIERARCHY", **common)


def persist_and_verify(model: HierarchicalPaModel, fixture: pd.DataFrame, output_root: Path) -> dict:
    """Save full learned state and exact input fixture; reload actual inference."""
    metadata = model.metadata()
    before = model.predict_proba(fixture)
    content = {"model": model, "fixture": fixture, "expectedProbabilities": before, "metadata": metadata}
    import io
    buffer = io.BytesIO()
    joblib.dump(content, buffer, compress=3)
    payload = buffer.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    path = Path(output_root) / "sha256" / digest / "hierarchy.joblib"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("Immutable hierarchy artifact mismatch")
    else:
        with path.open("xb") as stream:
            stream.write(payload)
    restored = load_verified(path, digest)
    after = restored["model"].predict_proba(restored["fixture"])
    if not np.array_equal(before, after):
        raise ValueError("Hierarchy inference reload mismatch")
    return {"path": str(path.resolve()), "sha256": digest, "bytes": len(payload),
        "rowsVerified": len(fixture), "probabilityValuesVerified": int(before.size),
        "mismatchedValues": int(np.count_nonzero(before != after)), "refitsDuringReload": 0,
        "metadata": metadata}


def load_verified(path: Path, expected_sha256: str):
    path = Path(path)
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("Trusted hierarchy artifact digest mismatch")
    import io
    return joblib.load(io.BytesIO(payload))
