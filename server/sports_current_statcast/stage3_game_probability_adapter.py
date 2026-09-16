"""State-aware Stage 3 plate-appearance probability provider.

Unlike the older Direct/E10 card adapter, this provider rebuilds the exact 234-column model
frame on every simulated plate appearance batch.  The 229 pregame values remain frozen while
exactly five values come from :class:`SimulatedPAStateBatch`.

The artifact dependency is intentionally a structural protocol.  Artifact publication owns
durable verification/loading; this module rechecks the immutable manifest, checksum, feature,
target, and research-safety bindings before accepting the loaded pipeline.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np
import pandas as pd

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix
from server.sports_phase5.whole_game_monte_carlo import (
    PAProbabilityProvider,
    SimulatedPAStateBatch,
)

from .stage3_game_inputs import (
    LINEUP_SIZE,
    SIMULATION_STATE_FEATURES,
    Stage3GameInputs,
)


GAME_PROBABILITY_ADAPTER_SCHEMA_VERSION = "SPORTS_STAGE3_STATE_AWARE_PA_ADAPTER_V1"
FINAL_DEVELOPMENT_MODEL = "FINAL_DEVELOPMENT"
FOLD_VALIDATION_MODEL = "FOLD_VALIDATION"
_MODEL_ROLES = {FINAL_DEVELOPMENT_MODEL, FOLD_VALIDATION_MODEL}


class Stage3GameProbabilityAdapterError(ValueError):
    """The verified model binding or one simulator state batch is invalid."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)

    def public_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self)}


@runtime_checkable
class ExecutableStage3ProbabilityPipeline(Protocol):
    """Minimal protocol implemented by the independently loaded Stage 3 pipeline."""

    ordered_features: Sequence[str]
    target_order: Sequence[str]

    def predict_proba(self, frame: pd.DataFrame) -> Any:
        """Return probabilities aligned to ``target_order``."""


@dataclass(frozen=True)
class VerifiedStage3ArtifactBinding:
    """Scoring-safe identity around an already verified executable pipeline."""

    artifact_id: str
    manifest_sha256: str
    model_sha256: str
    feature_set_checksum: str
    ordered_features: tuple[str, ...]
    target_order: tuple[str, ...]
    pipeline: ExecutableStage3ProbabilityPipeline
    model_role: str
    training_end_date: str
    fold_number: int | None = None
    validation_start_date: str | None = None
    validation_end_date: str | None = None

    def record(self) -> dict[str, Any]:
        return {
            "artifactId": self.artifact_id,
            "artifactManifestSha256": self.manifest_sha256,
            "modelBinarySha256": self.model_sha256,
            "featureSetChecksum": self.feature_set_checksum,
            "featureCount": len(self.ordered_features),
            "targetOrder": list(self.target_order),
            "modelRole": self.model_role,
            "trainingEndDate": self.training_end_date,
            "foldNumber": self.fold_number,
            "validationStartDate": self.validation_start_date,
            "validationEndDate": self.validation_end_date,
        }


def _error(code: str, message: str) -> Stage3GameProbabilityAdapterError:
    return Stage3GameProbabilityAdapterError(code, message)


def _valid_identifier(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise _error("STAGE3_ARTIFACT_IDENTITY_INVALID", f"{label} is missing or invalid.")
    return value


def _valid_sha(value: Any, *, label: str) -> str:
    digest = _valid_identifier(value, label=label).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise _error("STAGE3_ARTIFACT_CHECKSUM_INVALID", f"{label} must be a SHA-256 digest.")
    return digest


def _member(value: Any, *names: str) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _nested(value: Mapping[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current: Any = value
        for name in path:
            if not isinstance(current, Mapping) or name not in current:
                break
            current = current[name]
        else:
            return current
    return None


def _verification_passed(loaded: Any, manifest: Mapping[str, Any]) -> bool:
    explicit = _member(loaded, "verified", "verification_passed", "verificationPassed")
    if explicit is True:
        return True
    verification = manifest.get("verification")
    if not isinstance(verification, Mapping):
        return False
    if verification.get("verified") is True or verification.get("passed") is True:
        return True
    status = str(verification.get("status") or "").upper()
    return status in {
        "PASS",
        "VERIFIED",
        "PASSED",
        "COMPLETE",
        "RELOAD_AND_FIXTURE_VERIFIED",
        "EXECUTABLE_ARTIFACT_VERIFIED",
    }


def bind_verified_stage3_artifact(
    loaded_artifact: Any,
    *,
    expected_manifest_sha256: str,
    model_role: str = FINAL_DEVELOPMENT_MODEL,
    fold_number: int | None = None,
) -> VerifiedStage3ArtifactBinding:
    """Bind an artifact-loader result after independently rechecking its manifest.

    The manifest checksum is required from the caller's governed registry/handoff record.  It
    is compared with canonical manifest bytes; a self-declared checksum is never trusted.
    """

    manifest = _member(loaded_artifact, "manifest")
    if not isinstance(manifest, Mapping):
        raise _error(
            "STAGE3_ARTIFACT_MANIFEST_UNAVAILABLE",
            "The loaded artifact does not carry its verified immutable manifest.",
        )
    try:
        computed_manifest_sha = hashlib.sha256(canonical_json_bytes(dict(manifest))).hexdigest()
    except Exception as exc:
        raise _error(
            "STAGE3_ARTIFACT_MANIFEST_INVALID",
            "The artifact manifest cannot be canonically verified.",
        ) from exc
    expected_sha = _valid_sha(expected_manifest_sha256, label="expected artifact manifest checksum")
    if computed_manifest_sha != expected_sha:
        raise _error(
            "STAGE3_ARTIFACT_MANIFEST_CHECKSUM_MISMATCH",
            "The artifact manifest differs from the governed registry/handoff checksum.",
        )
    if not _verification_passed(loaded_artifact, manifest):
        raise _error(
            "STAGE3_ARTIFACT_NOT_VERIFIED",
            "Fresh-process reload and fixture verification evidence is required before scoring.",
        )

    safety = manifest.get("safety")
    if not isinstance(safety, Mapping) or (
        str(safety.get("modelStatus") or "").upper() != "RESEARCH_CHALLENGER"
        or str(safety.get("promotionStatus") or "").upper() != "NOT_PROMOTED"
        or safety.get("finalOotLocked") is not True
        or safety.get("finalOotTargetAccessed") is not False
        or safety.get("providerCalls") != 0
    ):
        raise _error(
            "STAGE3_ARTIFACT_SAFETY_AUTHORITY_INVALID",
            "Scoring requires the verified research-challenger, not-promoted, zero-OOT, zero-provider artifact authority.",
        )

    pipeline = _member(loaded_artifact, "pipeline")
    if pipeline is None or not callable(getattr(pipeline, "predict_proba", None)):
        raise _error(
            "STAGE3_EXECUTABLE_PIPELINE_UNAVAILABLE",
            "The verified artifact does not contain an executable probability pipeline.",
        )
    manifest_features = tuple(manifest.get("orderedFeatures") or ())
    manifest_targets = tuple(manifest.get("targetOrder") or ())
    pipeline_features = tuple(getattr(pipeline, "ordered_features", ()))
    pipeline_targets = tuple(getattr(pipeline, "target_order", ()))
    if (
        len(manifest_features) != 234
        or len(set(manifest_features)) != 234
        or pipeline_features != manifest_features
    ):
        raise _error(
            "STAGE3_ARTIFACT_FEATURE_ORDER_MISMATCH",
            "The loaded pipeline must preserve the exact ordered 234-feature manifest contract.",
        )
    if manifest_targets != tuple(PA_CLASS_ORDER) or pipeline_targets != tuple(PA_CLASS_ORDER):
        raise _error(
            "STAGE3_ARTIFACT_TARGET_ORDER_MISMATCH",
            "The artifact and pipeline must preserve the exact governed eight-class target order.",
        )

    artifact_id = _valid_identifier(manifest.get("artifactId"), label="artifact ID")
    role = str(model_role or "").upper()
    loaded_fold_number = _member(loaded_artifact, "fold_number", "foldNumber")
    if role not in _MODEL_ROLES:
        raise _error("STAGE3_ARTIFACT_MODEL_ROLE_INVALID", "Artifact model role is invalid.")
    if role == FOLD_VALIDATION_MODEL:
        if (
            isinstance(fold_number, bool)
            or not isinstance(fold_number, int)
            or fold_number not in range(1, 6)
        ):
            raise _error(
                "STAGE3_FOLD_MODEL_AUTHORITY_INCOMPLETE",
                "A historical OOF binding requires a fold number from 1 through 5.",
            )
        if loaded_fold_number != fold_number:
            raise _error(
                "STAGE3_FOLD_MODEL_AUTHORITY_MISMATCH",
                "The loaded fold pipeline identity differs from the selected verified manifest fold.",
            )
    elif fold_number is not None:
        raise _error(
            "STAGE3_FINAL_MODEL_FOLD_IDENTITY_PROHIBITED",
            "The final development model cannot be represented as an OOF fold model.",
        )
    elif loaded_fold_number is not None:
        raise _error(
            "STAGE3_FINAL_MODEL_FOLD_IDENTITY_PROHIBITED",
            "A loaded fold pipeline cannot be bound as the final development model.",
        )

    files = manifest.get("files")
    if role == FOLD_VALIDATION_MODEL and isinstance(files, Mapping):
        fold_files = files.get("foldModels")
        model_file = next(
            (
                item
                for item in fold_files
                if isinstance(item, Mapping) and item.get("foldNumber") == fold_number
            ),
            None,
        ) if isinstance(fold_files, list) else None
    else:
        model_file = files.get("model") if isinstance(files, Mapping) else None

    fold_training_end: str | None = None
    fold_validation_start: str | None = None
    fold_validation_end: str | None = None
    if role == FOLD_VALIDATION_MODEL:
        oof = manifest.get("oof")
        oof_folds = oof.get("folds") if isinstance(oof, Mapping) else None
        oof_fold = next(
            (
                item
                for item in oof_folds
                if isinstance(item, Mapping) and item.get("foldNumber") == fold_number
            ),
            None,
        ) if isinstance(oof_folds, list) else None
        if not isinstance(model_file, Mapping) or not isinstance(oof_fold, Mapping):
            raise _error(
                "STAGE3_FOLD_MODEL_AUTHORITY_INCOMPLETE",
                "The verified manifest does not contain the selected fold's model and OOF authority.",
            )
        fold_training_end = _valid_identifier(
            model_file.get("trainEnd"), label="fold training end date"
        )
        fold_validation_start = _valid_identifier(
            model_file.get("validationStart"), label="fold validation start date"
        )
        fold_validation_end = _valid_identifier(
            model_file.get("validationEnd"), label="fold validation end date"
        )
        if any(
            oof_fold.get(key) != value
            for key, value in (
                ("trainEnd", fold_training_end),
                ("validationStart", fold_validation_start),
                ("validationEnd", fold_validation_end),
            )
        ):
            raise _error(
                "STAGE3_FOLD_MODEL_AUTHORITY_MISMATCH",
                "The selected fold model boundaries differ from the verified OOF manifest authority.",
            )
    model_sha = _valid_sha(
        model_file.get("sha256") if isinstance(model_file, Mapping) else None,
        label="model binary checksum",
    )
    feature_checksum = _valid_sha(
        _nested(
            manifest,
            ("candidate", "featureSetChecksum"),
            ("authority", "featureSetChecksum"),
            ("featureSet", "checksum"),
        ),
        label="feature-set checksum",
    )
    if role == FOLD_VALIDATION_MODEL:
        training_end = fold_training_end
    else:
        training_end = _nested(
            manifest,
            ("training", "endDate"),
            ("training", "developmentEndDate"),
            ("training", "cutoff"),
        )
        training_end = _valid_identifier(training_end, label="training end date")

    return VerifiedStage3ArtifactBinding(
        artifact_id=artifact_id,
        manifest_sha256=expected_sha,
        model_sha256=model_sha,
        feature_set_checksum=feature_checksum,
        ordered_features=manifest_features,
        target_order=manifest_targets,
        pipeline=pipeline,
        model_role=role,
        training_end_date=training_end,
        fold_number=fold_number,
        validation_start_date=fold_validation_start,
        validation_end_date=fold_validation_end,
    )


def _integer_vector(
    values: Any,
    *,
    name: str,
    shape: tuple[int, ...],
    minimum: int | None = None,
    maximum: int | None = None,
) -> np.ndarray:
    raw = np.asarray(values)
    if raw.shape != shape or raw.dtype.kind not in "iu" or raw.dtype.kind == "b":
        raise _error(
            "SIMULATED_STATE_BATCH_INVALID",
            f"{name} must be an aligned integer vector.",
        )
    parsed = raw.astype(np.int64, copy=False)
    if minimum is not None and np.any(parsed < minimum):
        raise _error("SIMULATED_STATE_BATCH_INVALID", f"{name} is below its legal range.")
    if maximum is not None and np.any(parsed > maximum):
        raise _error("SIMULATED_STATE_BATCH_INVALID", f"{name} exceeds its legal range.")
    return parsed


def _validate_state(state: SimulatedPAStateBatch) -> tuple[int, dict[str, np.ndarray]]:
    if not isinstance(state, SimulatedPAStateBatch):
        raise _error(
            "SIMULATED_STATE_BATCH_INVALID",
            "The provider requires SimulatedPAStateBatch from the governed whole-game simulator.",
        )
    inning = np.asarray(state.inning)
    if inning.ndim != 1 or inning.size == 0:
        raise _error(
            "SIMULATED_STATE_BATCH_INVALID",
            "Simulated state arrays must be non-empty one-dimensional vectors.",
        )
    shape = inning.shape
    is_top = np.asarray(state.is_top)
    active = np.asarray(state.active)
    if is_top.shape != shape or is_top.dtype != np.bool_ or active.shape != shape or active.dtype != np.bool_:
        raise _error(
            "SIMULATED_STATE_BATCH_INVALID",
            "Simulated batting side and active masks must be aligned boolean vectors.",
        )
    parsed = {
        "context_inning": _integer_vector(
            inning, name="inning", shape=shape, minimum=1
        ),
        "context_top_bottom": np.where(is_top, 0, 1).astype(np.int64),
        "context_outs_before": _integer_vector(
            state.outs_before, name="outs_before", shape=shape, minimum=0, maximum=2
        ),
        "context_base_mask_before": _integer_vector(
            state.base_mask_before,
            name="base_mask_before",
            shape=shape,
            minimum=0,
            maximum=7,
        ),
        "context_batting_score_diff_before": _integer_vector(
            state.batting_score_diff_before,
            name="batting_score_diff_before",
            shape=shape,
        ),
        "batting_team_pa_ordinal": _integer_vector(
            state.batting_team_pa_ordinal,
            name="batting_team_pa_ordinal",
            shape=shape,
            minimum=0,
        ),
    }
    # Score vectors are validated even though the pipeline consumes only the derived batting
    # differential; this prevents an invalid simulator state from crossing the adapter seam.
    _integer_vector(state.away_score_before, name="away_score_before", shape=shape, minimum=0)
    _integer_vector(state.home_score_before, name="home_score_before", shape=shape, minimum=0)
    return int(inning.size), parsed


@dataclass(frozen=True)
class Stage3PAProbabilityProvider(PAProbabilityProvider):
    """Cycle confirmed starting lineups while scoring current simulated state."""

    game_inputs: Stage3GameInputs
    artifact: VerifiedStage3ArtifactBinding

    def __post_init__(self) -> None:
        if not isinstance(self.game_inputs, Stage3GameInputs):
            raise TypeError("game_inputs must be Stage3GameInputs")
        if not isinstance(self.artifact, VerifiedStage3ArtifactBinding):
            raise TypeError("artifact must be VerifiedStage3ArtifactBinding")
        if self.game_inputs.ordered_features != self.artifact.ordered_features:
            raise _error(
                "STAGE3_SCORING_FEATURE_ORDER_MISMATCH",
                "Pregame templates and the executable artifact do not share the exact 234-feature order.",
            )
        if self.artifact.target_order != tuple(PA_CLASS_ORDER):
            raise _error(
                "STAGE3_SCORING_TARGET_ORDER_MISMATCH",
                "The executable artifact target order differs from the governed eight-class contract.",
            )

    def model_frame(self, state: SimulatedPAStateBatch) -> pd.DataFrame:
        """Return the exact artifact-ordered frame used for one simulator batch."""

        n_rows, simulated = _validate_state(state)
        ordinal = simulated.pop("batting_team_pa_ordinal")
        slots = ordinal % LINEUP_SIZE
        row_indices = np.where(np.asarray(state.is_top), slots, LINEUP_SIZE + slots)
        rows = [self.game_inputs.templates[int(index)] for index in row_indices]
        frozen_by_name = {
            name: [row.frozen_predictor_values[position] for row in rows]
            for position, name in enumerate(self.game_inputs.non_simulation_features)
        }
        columns: dict[str, Any] = {}
        for name in self.artifact.ordered_features:
            if name in simulated:
                columns[name] = simulated[name]
            else:
                columns[name] = frozen_by_name[name]
        frame = pd.DataFrame(columns, columns=list(self.artifact.ordered_features))
        if frame.shape != (n_rows, len(self.artifact.ordered_features)) or tuple(frame.columns) != self.artifact.ordered_features:
            raise _error(
                "STAGE3_SCORING_FRAME_INVALID",
                "The state-aware adapter did not produce the exact artifact input matrix.",
            )
        return frame

    def __call__(self, state: SimulatedPAStateBatch, /) -> np.ndarray:
        frame = self.model_frame(state)
        try:
            raw = self.artifact.pipeline.predict_proba(frame)
            probabilities = validate_probability_matrix(
                raw, class_order=self.artifact.target_order
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            raise _error(
                "STAGE3_PIPELINE_PROBABILITY_INVALID",
                "The executable pipeline failed or returned an invalid probability matrix.",
            ) from exc
        expected_shape = (len(frame), len(PA_CLASS_ORDER))
        if probabilities.shape != expected_shape:
            raise _error(
                "STAGE3_PIPELINE_PROBABILITY_SHAPE_INVALID",
                f"The executable pipeline returned {probabilities.shape}; expected {expected_shape}.",
            )
        frozen = np.frombuffer(
            np.ascontiguousarray(probabilities, dtype=np.float64).tobytes(), dtype=np.float64
        ).reshape(expected_shape)
        return frozen

    def record(self) -> dict[str, Any]:
        return {
            "schemaVersion": GAME_PROBABILITY_ADAPTER_SCHEMA_VERSION,
            "gameId": self.game_inputs.canonical_game_id,
            "artifact": self.artifact.record(),
            "featureVectorSha256": self.game_inputs.feature_vector_sha256,
            "lineupAuthority": dict(self.game_inputs.lineup_authority),
            "starterAuthority": dict(self.game_inputs.starter_authority),
            "featureAuthority": dict(self.game_inputs.feature_authority),
            "featureCutoff": self.game_inputs.source_cutoff,
            "templateCount": len(self.game_inputs.templates),
            "battingOrderPolicy": "CONFIRMED_STARTING_LINEUP_CYCLED",
            "pitcherPolicy": "ANNOUNCED_STARTER_HELD_CONSTANT",
            "simulationGeneratedStateFeatures": list(SIMULATION_STATE_FEATURES),
            "simulationGeneratedStateFeatureCount": len(SIMULATION_STATE_FEATURES),
            "frozenPregameFeatureCount": len(self.game_inputs.non_simulation_features),
            "actualTargetGameStateRead": False,
            "actualSubstitutionsUsed": False,
            "actualRelieversUsed": False,
            "providerCalls": 0,
            "targetOrder": list(PA_CLASS_ORDER),
        }


def build_stage3_probability_adapter(
    game_inputs: Stage3GameInputs,
    artifact: VerifiedStage3ArtifactBinding,
) -> Stage3PAProbabilityProvider:
    """Construct the simulator provider after exact feature/target reconciliation."""

    return Stage3PAProbabilityProvider(game_inputs=game_inputs, artifact=artifact)


__all__ = [
    "ExecutableStage3ProbabilityPipeline",
    "FINAL_DEVELOPMENT_MODEL",
    "FOLD_VALIDATION_MODEL",
    "GAME_PROBABILITY_ADAPTER_SCHEMA_VERSION",
    "Stage3GameProbabilityAdapterError",
    "Stage3PAProbabilityProvider",
    "VerifiedStage3ArtifactBinding",
    "bind_verified_stage3_artifact",
    "build_stage3_probability_adapter",
]
