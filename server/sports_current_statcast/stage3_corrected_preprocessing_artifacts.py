"""Content-addressed, Development-only corrected preprocessing/model evidence.

These local research artifacts are not production exports or promotion records.
Only artifacts produced and hash-authenticated by this module may be reloaded.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from ..sports_datasets.consumer import canonical_json_bytes


class FrozenCorrectedPreprocessor:
    """Frozen semantic/prior treatment followed by training-fitted encoding."""

    def __init__(self, *, prior: Mapping[str, Any], semantic: Mapping[str, Any],
                 encoder: Any, source_columns: Sequence[str],
                 ordered_features: Sequence[str], feature_set: Mapping[str, Any]) -> None:
        self.prior = dict(prior)
        self.semantic = dict(semantic)
        self.encoder = encoder
        self.source_columns = tuple(source_columns)
        self.ordered_features = tuple(ordered_features)
        self.feature_set = dict(feature_set)

    def transform_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        from .stage3_corrected_prior_treatment import transform_prior_frame
        from .stage3_semantic_treatment import transform_semantic_treatment, validate_model_frame

        if not isinstance(frame, pd.DataFrame):
            raise ValueError("Corrected treatment requires a source DataFrame.")
        from .mlb_v18_prospective_transform import has_prospective_authority
        has_prospective_authority(frame)  # Validate any capability before column projection.
        missing = sorted(set(self.source_columns) - set(frame.columns))
        if missing:
            raise ValueError("Corrected source columns missing: " + ", ".join(missing))
        # Targets never enter any treatment transform or its persisted state.
        inputs = frame.loc[:, list(self.source_columns)].copy()
        prior_frame, _ = transform_prior_frame(inputs, self.prior)
        treated, _ = transform_semantic_treatment(prior_frame, self.semantic)
        validate_model_frame(treated, feature_set=self.feature_set, semantic_fitted=self.semantic, prior_fitted=self.prior)
        return treated.loc[:, list(self.ordered_features)]

    def transform(self, frame: pd.DataFrame) -> Any:
        return self.encoder.transform(self.transform_frame(frame))

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        return self.encoder.get_feature_names_out()


def _array_digest(values: Any) -> str:
    array = np.asarray(values.toarray() if hasattr(values, "toarray") else values,
                       dtype=np.float64, order="C")
    digest = hashlib.sha256()
    digest.update(str(array.shape).encode("ascii"))
    # Normalize NaN bits so the checksum represents values, not payload bits.
    for start in range(0, len(array), 4096):
        block = array[start:start + 4096].copy()
        block[np.isnan(block)] = np.nan
        digest.update(block.tobytes(order="C"))
    return digest.hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _install_blob(temporary: Path, *, root: Path, kind: str, suffix: str) -> dict[str, Any]:
    checksum = _file_digest(temporary)
    destination = root / "objects" / kind / "sha256" / (checksum + suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _file_digest(destination) != checksum:
            raise ValueError("Existing content-addressed research artifact is corrupt.")
        temporary.unlink()
    else:
        os.replace(temporary, destination)
    return {"sha256": checksum, "relativePath": destination.relative_to(root).as_posix(),
            "bytes": destination.stat().st_size}


def persist_json(payload: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=root, prefix="corrected-state-", suffix=".tmp", delete=False) as stream:
        stream.write(canonical_json_bytes(dict(payload)))
        temporary = Path(stream.name)
    return _install_blob(temporary, root=root, kind="corrected-preprocessing", suffix=".json")


def persist_and_verify(*, pipeline: Any, preprocessing_payload: Mapping[str, Any],
                       validation_source: pd.DataFrame, validation_values: Any,
                       probabilities: np.ndarray, root: Path) -> dict[str, Any]:
    """Save once, reload without fit, check every validation value/prediction."""
    state = persist_json(preprocessing_payload, root=root)
    with tempfile.NamedTemporaryFile(dir=root, prefix="corrected-model-", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
    joblib.dump(pipeline, temporary, compress=3)
    model = _install_blob(temporary, root=root, kind="research-model", suffix=".joblib")
    reloaded = load_research_pipeline(model, root=root)
    transformed = reloaded.preprocessor.transform(validation_source)
    expected_values_hash = _array_digest(validation_values)
    actual_values_hash = _array_digest(transformed)
    if expected_values_hash != actual_values_hash:
        raise ValueError("Saved corrected transform did not reproduce validation values.")
    actual_probabilities = reloaded.predict_proba(validation_source)
    # The executable wrapper performs only governed row-sum normalization.
    expected = np.asarray(probabilities, dtype=np.float64)
    expected = expected / expected.sum(axis=1, keepdims=True)
    if not np.allclose(actual_probabilities, expected, rtol=0.0, atol=1e-14):
        raise ValueError("Saved research model did not reproduce validation predictions.")
    return {"status": "PERSISTED_AND_RELOADED_WITHOUT_REFITTING",
            "scope": "DEVELOPMENT_LOCAL_RESEARCH_ONLY_NOT_PRODUCTION_EXPORT",
            "preprocessing": state, "model": model,
            "validationRows": len(validation_source),
            "transformedValidationSha256": expected_values_hash,
            "reloadedTransformedValidationSha256": actual_values_hash,
            "probabilityMaximumAbsoluteDifference": float(np.max(np.abs(actual_probabilities - expected))),
            "refitsDuringReload": 0, "finalOotRowsRead": 0}


def load_research_pipeline(reference: Mapping[str, Any], *, root: Path) -> Any:
    """Load only a trusted locally generated research object with verified hash."""
    absolute_root = root.resolve()
    path = (absolute_root / str(reference["relativePath"])).resolve()
    allowed = (absolute_root / "objects" / "research-model" / "sha256").resolve()
    if path.parent != allowed or not path.is_file():
        raise ValueError("Research model is outside its content-addressed store.")
    checksum = str(reference["sha256"])
    if path.name != checksum + ".joblib" or _file_digest(path) != checksum:
        raise ValueError("Research model artifact hash mismatch.")
    return joblib.load(path)
