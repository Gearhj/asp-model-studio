from __future__ import annotations

import math
import os
import re
import json
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ..sports_datasets.constants import (
    PARTITION_AUTHORITY_SHA,
    PROJECT_ID,
    REGISTRATION_ID,
)
from ..sports_datasets.consumer import (
    ValidatedPackage,
    canonical_json_bytes,
    raw_absolute_path,
    reject_reparse_chain,
    sha256_bytes,
)
from ..sports_identity_bridges.constants import (
    ALIAS_AUTHORITY_SHA,
    BRIDGE_MANIFEST_SHA,
    BRIDGE_REGISTRATION_ID,
    DIMENSION_AUTHORITY_SHA,
)
from ..sports_identity_bridges.consumer import ValidatedIdentityBridge
from .bootstrap import (
    BOOTSTRAP_SCHEMA_VERSION,
    DEFAULT_BOOTSTRAP_RESAMPLES,
    DEFAULT_BOOTSTRAP_SEED,
    DEFAULT_CONFIDENCE_LEVEL,
    game_cluster_bootstrap,
)
from .calibration import (
    CALIBRATION_SCHEMA_VERSION,
    fit_temperature_scaling,
    temperature_scale,
)
from .feature_contract import (
    DECISION_TOLERANCE,
    FEATURE_CONTRACT_NAME,
    FEATURE_CONTRACT_VERSION,
    FEATURE_NAMES,
    PARENT_MANIFEST_SHA,
    RESEARCH_RUN_SCHEMA_VERSION,
    canonical_sha,
)
from .feature_view import BuiltFeatureView, build_mlb_pa_feature_view_v1
from .metrics import PA_CLASS_ORDER, evaluate_multiclass
from .training import (
    FOLD_2024_ID,
    FOLD_2025_ID,
    TRAINING_SCHEMA_VERSION,
    TrainingExperimentResult,
    run_training_experiment,
)


RUNNER_SCHEMA_VERSION = "MLB_PA_PHASE3_RUNNER_V1"
RUNTIME_NAMESPACE = "mlb-pa-v1"
RUNTIME_URI_PREFIX = f"asp-model-studio-runtime://sports-modeling/{RUNTIME_NAMESPACE}"
_JOIN_AUDIT_ID_RE = re.compile(r"sports-identity-join-audit:sha256:[0-9a-f]{64}\Z")


class SportsPARunnerError(RuntimeError):
    """Fail-closed execution or artifact-integrity error."""


def _validated_runtime_root(runtime_root: Path, protected_roots: tuple[Path, ...]) -> Path:
    raw_root = raw_absolute_path(Path(runtime_root))
    repository_root = Path(__file__).resolve().parents[2]
    raw_allowed_boundary = raw_absolute_path(
        repository_root / ".runtime" / "asp-model-studio" / "sports-modeling"
    )
    if raw_root != raw_allowed_boundary and raw_allowed_boundary not in raw_root.parents:
        raise SportsPARunnerError(
            "runtime_root must remain inside .runtime/asp-model-studio/sports-modeling"
        )
    reject_reparse_chain(raw_root, label="Sports-modeling runtime root chain")
    root = raw_root.resolve(strict=False)
    allowed_boundary = raw_allowed_boundary.resolve(strict=False)
    if root != allowed_boundary and allowed_boundary not in root.parents:
        raise SportsPARunnerError(
            "runtime_root must resolve inside .runtime/asp-model-studio/sports-modeling"
        )
    for protected in protected_roots:
        approved = protected.resolve(strict=True)
        if root == approved or approved in root.parents:
            raise SportsPARunnerError("runtime_root may not be inside an approved read-only package")
    raw_root.mkdir(parents=True, exist_ok=True)
    reject_reparse_chain(raw_root, label="Sports-modeling runtime root chain")
    resolved_after_creation = raw_root.resolve(strict=True)
    if (
        resolved_after_creation != allowed_boundary
        and allowed_boundary not in resolved_after_creation.parents
    ):
        raise SportsPARunnerError(
            "runtime_root resolved outside .runtime/asp-model-studio/sports-modeling"
        )
    return raw_root


class _Progress:
    def __init__(self, callback: Any | None) -> None:
        self.callback = callback
        self.started = time.monotonic()

    def __call__(self, event: Mapping[str, Any]) -> None:
        if self.callback is None:
            return
        payload = {
            "title": "ASP MODEL STUDIO — MLB PA RESEARCH RUN",
            "schemaVersion": RUNNER_SCHEMA_VERSION,
            "elapsedSeconds": round(time.monotonic() - self.started, 2),
            "errors": 0,
            "etaSeconds": None,
            **dict(event),
        }
        self.callback(str(payload["stage"]), payload)


@dataclass(frozen=True)
class _ArtifactWriter:
    runtime_root: Path
    bindings: dict[str, Any]

    @classmethod
    def create(
        cls,
        runtime_root: Path,
        *,
        bindings: Mapping[str, Any],
        protected_roots: tuple[Path, ...],
    ) -> _ArtifactWriter:
        if not isinstance(bindings, Mapping) or not bindings:
            raise ValueError("artifact bindings must be established before persistence")
        root = _validated_runtime_root(runtime_root, protected_roots)
        return cls(root, dict(bindings))

    def _write(
        self,
        artifact_type: str,
        filename: str,
        content: bytes,
        *,
        media_type: str,
    ) -> dict[str, Any]:
        if not artifact_type or not filename or not content:
            raise SportsPARunnerError("runtime artifacts require type, name, and non-empty content")
        digest = sha256_bytes(content)
        relative = (
            Path(RUNTIME_NAMESPACE)
            / "objects"
            / "sha256"
            / digest[:2]
            / digest
            / filename
        )
        destination = self.runtime_root / relative
        if self.runtime_root != destination and self.runtime_root not in destination.parents:
            raise SportsPARunnerError("runtime artifact path escaped the approved runtime root")
        reject_reparse_chain(destination.parent, label="Sports-modeling artifact parent chain")
        destination.parent.mkdir(parents=True, exist_ok=True)
        reject_reparse_chain(destination.parent, label="Sports-modeling artifact parent chain")
        if destination.exists():
            reject_reparse_chain(destination, label="Sports-modeling artifact chain")
            if destination.is_symlink() or destination.stat().st_nlink != 1:
                raise SportsPARunnerError("runtime artifact may not be a link")
            if destination.read_bytes() != content:
                raise SportsPARunnerError("existing content-addressed runtime artifact differs")
        else:
            temporary_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=".mlb-pa-artifact-",
                    suffix=".tmp",
                    dir=destination.parent,
                    delete=False,
                ) as handle:
                    temporary_name = handle.name
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_name, destination)
                temporary_name = None
            finally:
                if temporary_name is not None:
                    Path(temporary_name).unlink(missing_ok=True)
        reject_reparse_chain(destination, label="Sports-modeling artifact chain")
        resolved_root = self.runtime_root.resolve(strict=True)
        resolved_destination = destination.resolve(strict=True)
        if resolved_root not in resolved_destination.parents:
            raise SportsPARunnerError("runtime artifact resolved outside the approved runtime root")
        if resolved_destination.stat().st_nlink != 1:
            raise SportsPARunnerError("runtime artifact may not be a hardlink")
        logical_uri = f"{RUNTIME_URI_PREFIX}/objects/sha256/{digest[:2]}/{digest}/{filename}"
        return {
            "artifactId": f"sports-pa-artifact:{artifact_type.lower()}:sha256:{digest}",
            "artifactType": artifact_type,
            "logicalUri": logical_uri,
            "sha256": digest,
            "byteCount": len(content),
            "mediaType": media_type,
        }

    def json(
        self,
        artifact_type: str,
        filename: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        envelope = {
            "schemaVersion": "MLB_PA_RUNTIME_ARTIFACT_V1",
            "artifactType": artifact_type,
            "bindings": self.bindings,
            "payload": dict(payload),
        }
        return self._write(
            artifact_type,
            filename,
            canonical_json_bytes(envelope),
            media_type="application/json",
        )

    def parquet(
        self,
        artifact_type: str,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        try:
            metadata = pq.ParquetFile(pa.BufferReader(content)).schema_arrow.metadata or {}
        except Exception as exc:
            raise SportsPARunnerError("runtime Parquet artifact is unreadable") from exc
        if metadata.get(b"artifactBindings") != canonical_json_bytes(self.bindings):
            raise SportsPARunnerError("runtime Parquet artifact lacks the exact run/authority bindings")
        return self._write(
            artifact_type,
            filename,
            content,
            media_type="application/vnd.apache.parquet",
        )


def _prediction_parquet(
    fold: Any,
    *,
    selected_candidate_id: str,
    scaled_selected: np.ndarray,
    final_selected: np.ndarray,
    bindings: Mapping[str, Any],
) -> bytes:
    columns: dict[str, Any] = {
        "plate_appearance_id": fold.plate_appearance_ids.tolist(),
        "game_id": fold.game_ids.tolist(),
        "outcome": fold.labels.tolist(),
    }
    for candidate_id in sorted(fold.probabilities):
        matrix = fold.probabilities[candidate_id]
        for index, class_name in enumerate(PA_CLASS_ORDER):
            columns[f"raw_{candidate_id}_{class_name}"] = matrix[:, index]
    for prefix, matrix in (
        (f"scaled_{selected_candidate_id}", scaled_selected),
        (f"final_{selected_candidate_id}", final_selected),
    ):
        for index, class_name in enumerate(PA_CLASS_ORDER):
            columns[f"{prefix}_{class_name}"] = matrix[:, index]
    table = pa.Table.from_pydict(columns)
    metadata = {
        b"artifactSchemaVersion": b"MLB_PA_FOLD_PREDICTIONS_V1",
        b"artifactBindings": canonical_json_bytes(dict(bindings)),
        b"runId": str(bindings["runId"]).encode("utf-8"),
        b"runCreatedAt": str(bindings["runCreatedAt"]).encode("utf-8"),
        b"codeRevision": str(bindings["codeRevision"]).encode("utf-8"),
        b"foldId": fold.fold_id.encode("utf-8"),
        b"validationSeason": str(fold.validation_season).encode("ascii"),
        b"rowCount": str(fold.labels.size).encode("ascii"),
        b"selectedCandidateId": selected_candidate_id.encode("utf-8"),
        b"classOrder": canonical_json_bytes(list(PA_CLASS_ORDER)),
    }
    table = table.replace_schema_metadata(metadata)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        compression_level=9,
        use_dictionary=False,
        write_statistics=True,
        version="2.6",
        data_page_version="1.0",
        row_group_size=65_536,
    )
    return sink.getvalue().to_pybytes()


def _bound_feature_parquet(
    feature_view: BuiltFeatureView,
    *,
    bindings: Mapping[str, Any],
) -> bytes:
    metadata = {
        b"artifactSchemaVersion": b"MLB_PA_FEATURE_VIEW_ARTIFACT_V1",
        b"artifactBindings": canonical_json_bytes(dict(bindings)),
        b"runId": str(bindings["runId"]).encode("utf-8"),
        b"runCreatedAt": str(bindings["runCreatedAt"]).encode("utf-8"),
        b"codeRevision": str(bindings["codeRevision"]).encode("utf-8"),
        b"featureContentSha": feature_view.content_sha.encode("ascii"),
        b"featureContractSha": feature_view.contract_sha.encode("ascii"),
        b"featureSchemaSha": feature_view.schema_sha.encode("ascii"),
        b"rowCount": str(feature_view.row_count).encode("ascii"),
        b"sourcePartitionIds": canonical_json_bytes(list(feature_view.source_partition_ids)),
    }
    table = feature_view.table.replace_schema_metadata(metadata)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        compression_level=9,
        use_dictionary=False,
        write_statistics=True,
        version="2.6",
        data_page_version="1.0",
        row_group_size=65_536,
    )
    return sink.getvalue().to_pybytes()


@dataclass(frozen=True)
class _FeatureMaterializationCheckpoint:
    materialization_id: str
    created_at: str
    bindings: dict[str, Any]
    feature_artifact: dict[str, Any]
    manifest_artifact: dict[str, Any]

    @property
    def artifacts(self) -> list[dict[str, Any]]:
        return [self.feature_artifact, self.manifest_artifact]


def _atomic_write_bytes(destination: Path, content: bytes) -> None:
    reject_reparse_chain(destination.parent, label="Sports-modeling checkpoint parent chain")
    destination.parent.mkdir(parents=True, exist_ok=True)
    reject_reparse_chain(destination.parent, label="Sports-modeling checkpoint parent chain")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".mlb-pa-checkpoint-",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    reject_reparse_chain(destination, label="Sports-modeling checkpoint chain")
    if destination.stat().st_nlink != 1:
        raise SportsPARunnerError("feature checkpoint may not be a hardlink")


def _artifact_physical_path(runtime_root: Path, artifact: Mapping[str, Any]) -> Path:
    prefix = RUNTIME_URI_PREFIX + "/"
    uri = str(artifact.get("logicalUri", ""))
    if not uri.startswith(prefix):
        raise SportsPARunnerError("feature checkpoint logical URI differs")
    suffix = uri[len(prefix) :]
    parsed = PurePosixPath(suffix)
    if (
        not suffix
        or "\\" in suffix
        or suffix.startswith("/")
        or parsed.is_absolute()
        or parsed.as_posix() != suffix
        or any(part in {"", ".", ".."} for part in parsed.parts)
        or PureWindowsPath(suffix).is_absolute()
        or bool(PureWindowsPath(suffix).drive)
    ):
        raise SportsPARunnerError("feature checkpoint logical URI is unsafe")
    object_root = (runtime_root / RUNTIME_NAMESPACE).resolve(strict=True)
    candidate = object_root.joinpath(*parsed.parts)
    reject_reparse_chain(candidate, label="Feature checkpoint artifact chain")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SportsPARunnerError("feature checkpoint artifact is missing") from exc
    if resolved == object_root or object_root not in resolved.parents:
        raise SportsPARunnerError("feature checkpoint artifact escaped the runtime root")
    return resolved


def persist_feature_materialization_checkpoint(
    *,
    project_id: str,
    join_audit_id: str,
    feature_view: BuiltFeatureView,
    runtime_root: Path,
    code_revision: str,
    protected_roots: tuple[Path, ...],
) -> _FeatureMaterializationCheckpoint:
    """Persist/reuse the immutable feature checkpoint before any model fit begins."""

    if project_id != PROJECT_ID:
        raise SportsPARunnerError("feature checkpoint project anchor differs")
    if not isinstance(join_audit_id, str) or not _JOIN_AUDIT_ID_RE.fullmatch(join_audit_id):
        raise SportsPARunnerError("feature checkpoint requires the exact persisted join-audit ID")
    root = _validated_runtime_root(runtime_root, protected_roots)
    pointer = (
        root
        / RUNTIME_NAMESPACE
        / "feature-materializations"
        / f"sha256-{feature_view.content_sha}"
        / "checkpoint.json"
    )
    reject_reparse_chain(pointer.parent, label="Feature checkpoint pointer parent chain")
    if pointer.exists():
        reject_reparse_chain(pointer, label="Feature checkpoint pointer chain")
        if pointer.is_symlink() or pointer.stat().st_nlink != 1:
            raise SportsPARunnerError("feature materialization checkpoint may not be a link")
        def duplicate_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            output: dict[str, Any] = {}
            for key, value in pairs:
                if key in output:
                    raise SportsPARunnerError("feature checkpoint contains duplicate JSON keys")
                output[key] = value
            return output

        try:
            stored = json.loads(
                pointer.read_text(encoding="utf-8"),
                object_pairs_hook=duplicate_guard,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    SportsPARunnerError(f"feature checkpoint contains {value}")
                ),
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SportsPARunnerError("feature materialization checkpoint is unreadable") from exc
        if not isinstance(stored, dict) or set(stored) != {
            "schemaVersion",
            "featureContentSha",
            "materializationId",
            "createdAt",
            "codeRevision",
            "bindings",
            "featureArtifact",
            "manifestArtifact",
        }:
            raise SportsPARunnerError("feature materialization checkpoint shape differs")
        expected = {
            "schemaVersion": "MLB_PA_FEATURE_MATERIALIZATION_CHECKPOINT_V1",
            "featureContentSha": feature_view.content_sha,
        }
        if any(stored.get(key) != value for key, value in expected.items()):
            raise SportsPARunnerError("feature materialization checkpoint binding differs")
        created_at = stored.get("createdAt")
        if not isinstance(created_at, str) or not created_at.endswith("Z"):
            raise SportsPARunnerError("feature materialization creation time differs")
        try:
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SportsPARunnerError("feature materialization creation time is invalid") from exc
        materialization_revision = stored.get("codeRevision")
        if not isinstance(materialization_revision, str) or not materialization_revision.strip():
            raise SportsPARunnerError("feature materialization code revision is invalid")
        expected_core = {
            "schemaVersion": "MLB_PA_FEATURE_MATERIALIZATION_IDENTITY_V1",
            "createdAt": created_at,
            "codeRevision": materialization_revision,
            "projectId": project_id,
            "parentManifestSha": PARENT_MANIFEST_SHA,
            "parentPartitionAuthoritySha": PARTITION_AUTHORITY_SHA,
            "identityBridgeManifestSha": BRIDGE_MANIFEST_SHA,
            "joinAuditId": join_audit_id,
            "aliasAuthoritySha": ALIAS_AUTHORITY_SHA,
            "dimensionAuthoritySha": DIMENSION_AUTHORITY_SHA,
            "featureContractSha": feature_view.contract_sha,
            "featureSchemaSha": feature_view.schema_sha,
            "featureContentSha": feature_view.content_sha,
            "rowCount": feature_view.row_count,
            "sourcePartitionIds": list(feature_view.source_partition_ids),
        }
        expected_materialization_id = (
            "sports-pa-feature-materialization:sha256:"
            + sha256_bytes(canonical_json_bytes(expected_core))
        )
        expected_bindings = {
            "schemaVersion": "MLB_PA_ARTIFACT_BINDINGS_V1",
            "runId": expected_materialization_id,
            "runCreatedAt": created_at,
            "projectId": project_id,
            "parent": {
                "manifestSha": PARENT_MANIFEST_SHA,
                "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
            },
            "identityBridge": {
                "manifestSha": BRIDGE_MANIFEST_SHA,
                "joinAuditId": join_audit_id,
                "aliasAuthoritySha": ALIAS_AUTHORITY_SHA,
                "dimensionAuthoritySha": DIMENSION_AUTHORITY_SHA,
            },
            "featureContractSha": feature_view.contract_sha,
            "codeRevision": materialization_revision,
        }
        if (
            stored.get("materializationId") != expected_materialization_id
            or stored.get("bindings") != expected_bindings
        ):
            raise SportsPARunnerError("feature materialization authority binding differs")
        checkpoint = _FeatureMaterializationCheckpoint(
            materialization_id=str(stored["materializationId"]),
            created_at=str(stored["createdAt"]),
            bindings=dict(stored["bindings"]),
            feature_artifact=dict(stored["featureArtifact"]),
            manifest_artifact=dict(stored["manifestArtifact"]),
        )
        for artifact in checkpoint.artifacts:
            if not isinstance(artifact, dict) or set(artifact) != {
                "artifactId", "artifactType", "logicalUri", "sha256", "byteCount", "mediaType"
            } or not str(artifact.get("artifactId", "")).endswith(str(artifact.get("sha256", ""))):
                raise SportsPARunnerError("feature checkpoint artifact declaration differs")
            physical = _artifact_physical_path(root, artifact)
            if not physical.exists() or physical.is_symlink() or physical.stat().st_nlink != 1:
                raise SportsPARunnerError("feature checkpoint artifact is missing or linked")
            content = physical.read_bytes()
            if (
                sha256_bytes(content) != artifact["sha256"]
                or len(content) != artifact["byteCount"]
            ):
                raise SportsPARunnerError("feature checkpoint artifact integrity differs")
        feature_path = _artifact_physical_path(root, checkpoint.feature_artifact)
        feature_content = feature_path.read_bytes()
        expected_feature_content = _bound_feature_parquet(
            feature_view,
            bindings=expected_bindings,
        )
        if feature_content != expected_feature_content:
            raise SportsPARunnerError(
                "feature checkpoint Parquet content differs from rebuilt feature view"
            )
        try:
            feature_metadata = (
                pq.ParquetFile(pa.BufferReader(feature_content)).schema_arrow.metadata or {}
            )
        except Exception as exc:
            raise SportsPARunnerError("feature checkpoint Parquet is unreadable") from exc
        if (
            feature_metadata.get(b"artifactBindings") != canonical_json_bytes(expected_bindings)
            or feature_metadata.get(b"featureContentSha") != feature_view.content_sha.encode("ascii")
            or feature_metadata.get(b"featureSchemaSha") != feature_view.schema_sha.encode("ascii")
            or feature_metadata.get(b"rowCount") != str(feature_view.row_count).encode("ascii")
        ):
            raise SportsPARunnerError("feature checkpoint Parquet metadata differs")
        manifest_path = _artifact_physical_path(root, checkpoint.manifest_artifact)
        try:
            manifest_envelope = json.loads(
                manifest_path.read_text(encoding="utf-8"),
                object_pairs_hook=duplicate_guard,
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SportsPARunnerError("feature materialization manifest is unreadable") from exc
        expected_manifest_payload = {
            "materializationIdentity": expected_core,
            "materializationId": expected_materialization_id,
            "featureArtifact": checkpoint.feature_artifact,
            "featureSchema": feature_view.schema_spec,
            "seasonRows": feature_view.season_rows,
            "eligiblePriorCoverage": list(feature_view.prior_coverage),
        }
        expected_manifest_envelope = {
            "schemaVersion": "MLB_PA_RUNTIME_ARTIFACT_V1",
            "artifactType": "FEATURE_MATERIALIZATION_MANIFEST",
            "bindings": expected_bindings,
            "payload": expected_manifest_payload,
        }
        if canonical_json_bytes(manifest_envelope) != canonical_json_bytes(
            expected_manifest_envelope
        ):
            raise SportsPARunnerError("feature materialization manifest content differs")
        return checkpoint

    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    materialization_core = {
        "schemaVersion": "MLB_PA_FEATURE_MATERIALIZATION_IDENTITY_V1",
        "createdAt": created_at,
        "codeRevision": code_revision,
        "projectId": project_id,
        "parentManifestSha": PARENT_MANIFEST_SHA,
        "parentPartitionAuthoritySha": PARTITION_AUTHORITY_SHA,
        "identityBridgeManifestSha": BRIDGE_MANIFEST_SHA,
        "joinAuditId": join_audit_id,
        "aliasAuthoritySha": ALIAS_AUTHORITY_SHA,
        "dimensionAuthoritySha": DIMENSION_AUTHORITY_SHA,
        "featureContractSha": feature_view.contract_sha,
        "featureSchemaSha": feature_view.schema_sha,
        "featureContentSha": feature_view.content_sha,
        "rowCount": feature_view.row_count,
        "sourcePartitionIds": list(feature_view.source_partition_ids),
    }
    materialization_sha = sha256_bytes(canonical_json_bytes(materialization_core))
    materialization_id = f"sports-pa-feature-materialization:sha256:{materialization_sha}"
    bindings = {
        "schemaVersion": "MLB_PA_ARTIFACT_BINDINGS_V1",
        "runId": materialization_id,
        "runCreatedAt": created_at,
        "projectId": project_id,
        "parent": {
            "manifestSha": PARENT_MANIFEST_SHA,
            "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
        },
        "identityBridge": {
            "manifestSha": BRIDGE_MANIFEST_SHA,
            "joinAuditId": join_audit_id,
            "aliasAuthoritySha": ALIAS_AUTHORITY_SHA,
            "dimensionAuthoritySha": DIMENSION_AUTHORITY_SHA,
        },
        "featureContractSha": feature_view.contract_sha,
        "codeRevision": code_revision,
    }
    writer = _ArtifactWriter.create(
        root,
        bindings=bindings,
        protected_roots=protected_roots,
    )
    feature_artifact = writer.parquet(
        "FEATURE_VIEW",
        "mlb-pa-feature-view-v1.parquet",
        _bound_feature_parquet(feature_view, bindings=bindings),
    )
    manifest_artifact = writer.json(
        "FEATURE_MATERIALIZATION_MANIFEST",
        "feature-materialization.json",
        {
            "materializationIdentity": materialization_core,
            "materializationId": materialization_id,
            "featureArtifact": feature_artifact,
            "featureSchema": feature_view.schema_spec,
            "seasonRows": feature_view.season_rows,
            "eligiblePriorCoverage": list(feature_view.prior_coverage),
        },
    )
    checkpoint_payload = {
        "schemaVersion": "MLB_PA_FEATURE_MATERIALIZATION_CHECKPOINT_V1",
        "featureContentSha": feature_view.content_sha,
        "materializationId": materialization_id,
        "createdAt": created_at,
        "codeRevision": code_revision,
        "bindings": bindings,
        "featureArtifact": feature_artifact,
        "manifestArtifact": manifest_artifact,
    }
    _atomic_write_bytes(pointer, canonical_json_bytes(checkpoint_payload))
    return _FeatureMaterializationCheckpoint(
        materialization_id=materialization_id,
        created_at=created_at,
        bindings=bindings,
        feature_artifact=feature_artifact,
        manifest_artifact=manifest_artifact,
    )


def _calibration_payload(
    experiment: TrainingExperimentResult,
) -> tuple[dict[str, Any], dict[int, np.ndarray], dict[int, np.ndarray]]:
    selected_id = experiment.selected_candidate_id
    fold_2024 = experiment.folds[2024]
    fold_2025 = experiment.folds[2025]
    raw_2024 = fold_2024.probabilities[selected_id]
    raw_2025 = fold_2025.probabilities[selected_id]
    fit = fit_temperature_scaling(
        fold_2024.labels,
        raw_2024,
        source_seasons=np.full(fold_2024.labels.size, 2024, dtype=np.int64),
    )
    scaled_2025 = temperature_scale(raw_2025, fit.fitted_temperature)
    raw_2025_evidence = evaluate_multiclass(fold_2025.labels, raw_2025)
    scaled_2025_evidence = evaluate_multiclass(fold_2025.labels, scaled_2025)
    final_2025 = scaled_2025 if fit.retained else raw_2025
    final_2025_evidence = scaled_2025_evidence if fit.retained else raw_2025_evidence
    payload = {
        "schemaVersion": CALIBRATION_SCHEMA_VERSION,
        "decision": "RETAINED" if fit.retained else "REJECTED",
        "method": "SCALAR_TEMPERATURE_ON_LOG_PROBABILITIES",
        "sourceSeason": 2024,
        "candidateId": selected_id,
        "fittedTemperature": fit.fitted_temperature,
        "retainedTemperature": fit.retained_temperature,
        "retained": fit.retained,
        "raw2024": fit.raw_evidence,
        "scaled2024": fit.scaled_evidence,
        "raw2025": raw_2025_evidence,
        "scaled2025": scaled_2025_evidence,
        "final2025": final_2025_evidence,
        "rationale": (
            "Temperature was fit only on 2024 selected-model probabilities and retained only "
            "when both 2024 log loss and summed multiclass Brier did not worsen within 1e-10; "
            "the fitted temperature was frozen before application to 2025."
        ),
    }
    final_2024 = fit.final_probabilities
    return payload, {2024: fit.scaled_probabilities, 2025: scaled_2025}, {
        2024: final_2024,
        2025: final_2025,
    }


def _bootstrap_payloads(
    experiment: TrainingExperimentResult,
    *,
    n_resamples: int,
    seed: int,
    progress: _Progress,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    selected_id = experiment.selected_candidate_id
    for season in (2024, 2025):
        fold = experiment.folds[season]
        for comparator in ("C0", "C1"):
            progress(
                {
                    "stage": "GAME_CLUSTER_BOOTSTRAP",
                    "foldId": fold.fold_id,
                    "validationSeason": season,
                    "candidateId": selected_id,
                    "baselineCandidateId": comparator,
                    "validationRows": int(fold.labels.size),
                    "resamples": n_resamples,
                }
            )
            evidence = game_cluster_bootstrap(
                fold.labels,
                fold.probabilities[selected_id],
                fold.probabilities[comparator],
                fold.game_ids,
                n_resamples=n_resamples,
                seed=seed,
                confidence_level=DEFAULT_CONFIDENCE_LEVEL,
            )
            rows.append(
                {
                    "schemaVersion": BOOTSTRAP_SCHEMA_VERSION,
                    "candidateId": selected_id,
                    "baselineCandidateId": comparator,
                    "foldId": fold.fold_id,
                    "validationSeason": season,
                    "clusterUnit": "game_id",
                    "seed": seed,
                    "resamples": n_resamples,
                    "confidenceLevel": DEFAULT_CONFIDENCE_LEVEL,
                    "evidence": evidence,
                }
            )
    return rows


def _fold_metrics(candidate: Mapping[str, Any], season: int) -> Mapping[str, Any]:
    return next(
        item["metrics"]
        for item in candidate["foldMetrics"]
        if item["validationSeason"] == season
    )


def _decision(
    experiment: TrainingExperimentResult,
    calibration: Mapping[str, Any],
) -> dict[str, Any]:
    candidates = {item["candidateId"]: item for item in experiment.candidates}
    c0_2024 = _fold_metrics(candidates["C0"], 2024)
    c0_2025 = _fold_metrics(candidates["C0"], 2025)
    final_2024 = calibration["scaled2024"] if calibration["retained"] else calibration["raw2024"]
    final_2025 = calibration["final2025"]

    def challenger_fold(selected: Mapping[str, Any], baseline: Mapping[str, Any]) -> bool:
        return (
            selected["logLoss"] < baseline["logLoss"] - DECISION_TOLERANCE
            and selected["brierScore"] <= baseline["brierScore"] + DECISION_TOLERANCE
            and selected["topLabelEce"] <= baseline["topLabelEce"] + DECISION_TOLERANCE
            and all(
                math.isfinite(float(selected["classwiseEce"][class_name]))
                for class_name in PA_CLASS_ORDER
            )
        )

    challenger = challenger_fold(final_2024, c0_2024) and challenger_fold(final_2025, c0_2025)

    def worse_on_both(candidate_metrics: Mapping[str, Any], baseline: Mapping[str, Any]) -> bool:
        return (
            candidate_metrics["logLoss"] > baseline["logLoss"] + DECISION_TOLERANCE
            and candidate_metrics["brierScore"] > baseline["brierScore"] + DECISION_TOLERANCE
        )

    all_substantive_worse_2024 = all(
        item["eligible"] is not True
        or item["convergence"]["status"] != "CONVERGED"
        or worse_on_both(_fold_metrics(item, 2024), c0_2024)
        for item in experiment.candidates
        if item["candidateId"] != "C0"
    )
    rejected = all_substantive_worse_2024 and worse_on_both(final_2025, c0_2025)
    if challenger:
        terminal = "RESEARCH_CHALLENGER"
        rationale = (
            "The frozen selected model strictly improves global-baseline log loss, does not "
            "worsen Brier or top-label ECE, and has finite classwise calibration in both "
            "rolling-origin validation folds. This remains research evidence only."
        )
    elif rejected:
        terminal = "REJECTED_BASELINE"
        rationale = (
            "Every substantive contextual/prior candidate is worse than the global baseline "
            "on both 2024 governing losses, and the frozen selected pipeline is also worse "
            "on both losses in 2025."
        )
    else:
        terminal = "RESEARCH_BASELINE"
        rationale = (
            "The run is valid, but frozen-fold evidence is mixed, small, or uncertain under "
            "the predeclared challenger and rejection predicates."
        )
    limitations = [
        "This is a conditional plate appearance component, not a standalone pregame or game forecast.",
        "Handedness and platoon fields are absent from the approved FD1 inputs.",
        "Future participation, simulation, and export are not configured by this research run.",
        "Retrospective reconstruction is not prospective availability or performance evidence.",
    ]
    return {
        "terminalStatus": terminal,
        "rationale": rationale,
        "researchOnly": True,
        "deploymentAuthorized": False,
        "limitations": limitations,
        "recommendedNextStep": (
            "Review fold metrics, calibration, and whole-game bootstrap evidence before any "
            "separate simulator, prospective-validation, or deployment authorization work."
        ),
    }


def _graph(experiment: TrainingExperimentResult, content_sha: str) -> dict[str, Any]:
    nodes = [
        {"nodeId": "dataset-manifest", "nodeType": "DATASET_MANIFEST", "label": "MLB FD1 Dataset Manifest", "status": "COMPLETE", "candidateId": None},
        {"nodeId": "identity-bridge", "nodeType": "IDENTITY_BRIDGE", "label": "SPORTS_IDENTITY_BRIDGE_V1", "status": "COMPLETE", "candidateId": None},
        {"nodeId": "y-minus-1-prior-join", "nodeType": "PRIOR_JOIN", "label": "Exact Y-minus-1 Prior Join", "status": "COMPLETE", "candidateId": None},
        {"nodeId": "feature-view", "nodeType": "FEATURE_VIEW", "label": "MLB_PA_FEATURE_VIEW_V1", "status": "COMPLETE", "candidateId": None},
        {"nodeId": "selected-pa-baseline", "nodeType": "SELECTED_MODEL", "label": "Selected Multinomial PA Baseline", "status": "COMPLETE", "candidateId": experiment.selected_candidate_id},
        {"nodeId": "temperature-calibration", "nodeType": "CALIBRATION", "label": "Optional Temperature Calibration", "status": "COMPLETE", "candidateId": experiment.selected_candidate_id},
        {"nodeId": "retrospective-evaluation", "nodeType": "EVALUATION", "label": "Retrospective Evaluation Evidence", "status": "COMPLETE", "candidateId": experiment.selected_candidate_id},
    ]
    for candidate in experiment.candidates:
        nodes.append(
            {
                "nodeId": f"candidate-{candidate['candidateId'].lower()}",
                "nodeType": "MODEL_CANDIDATE",
                "label": candidate["displayName"],
                "status": "EVALUATED",
                "candidateId": candidate["candidateId"],
            }
        )
    future = (
        ("future-dynamic-player-state", "Dynamic Player State"),
        ("future-lineup-model", "Lineup Model"),
        ("future-starter-duration", "Starter-Duration"),
        ("future-bullpen-usage", "Bullpen-Usage"),
        ("future-base-out-transition", "Base-Out Transition"),
        ("future-game-simulator", "Game Simulator"),
        ("future-residual-model", "Residual Model"),
        ("future-standalone-asp-bundle", "Standalone ASP Bundle"),
    )
    nodes.extend(
        {
            "nodeId": node_id,
            "nodeType": "FUTURE_COMPONENT",
            "label": label,
            "status": "NOT_CONFIGURED",
            "candidateId": None,
        }
        for node_id, label in future
    )
    edges: list[dict[str, Any]] = [
        {"edgeId": "chain-01-dataset-to-bridge", "sourceNodeId": "dataset-manifest", "targetNodeId": "identity-bridge", "relation": "BINDS_IDENTITY"},
        {"edgeId": "chain-02-bridge-to-prior-join", "sourceNodeId": "identity-bridge", "targetNodeId": "y-minus-1-prior-join", "relation": "ENABLES_EXACT_JOIN"},
        {"edgeId": "chain-03-prior-join-to-feature-view", "sourceNodeId": "y-minus-1-prior-join", "targetNodeId": "feature-view", "relation": "MATERIALIZES"},
        {"edgeId": "chain-04-feature-to-selected", "sourceNodeId": "feature-view", "targetNodeId": "selected-pa-baseline", "relation": "TRAINS_FROZEN_SELECTION"},
        {"edgeId": "chain-05-selected-to-calibration", "sourceNodeId": "selected-pa-baseline", "targetNodeId": "temperature-calibration", "relation": "OPTIONALLY_CALIBRATES"},
        {"edgeId": "chain-06-calibration-to-evaluation", "sourceNodeId": "temperature-calibration", "targetNodeId": "retrospective-evaluation", "relation": "PRODUCES_RETROSPECTIVE_EVIDENCE"},
    ]
    for candidate in experiment.candidates:
        candidate_id = candidate["candidateId"]
        edges.append(
            {
                "edgeId": f"branch-feature-to-{candidate_id.lower()}",
                "sourceNodeId": "feature-view",
                "targetNodeId": f"candidate-{candidate_id.lower()}",
                "relation": "EVALUATES_CANDIDATE",
            }
        )
        edges.append(
            {
                "edgeId": f"branch-{candidate_id.lower()}-to-evaluation",
                "sourceNodeId": f"candidate-{candidate_id.lower()}",
                "targetNodeId": "retrospective-evaluation",
                "relation": "CONTRIBUTES_COMPARATOR_EVIDENCE",
            }
        )
    edges.extend(
        [
            {"edgeId": "future-evaluation-to-dynamic-state", "sourceNodeId": "retrospective-evaluation", "targetNodeId": "future-dynamic-player-state", "relation": "FUTURE_NOT_CONFIGURED"},
            {"edgeId": "future-evaluation-to-lineup", "sourceNodeId": "retrospective-evaluation", "targetNodeId": "future-lineup-model", "relation": "FUTURE_NOT_CONFIGURED"},
            {"edgeId": "future-evaluation-to-starter", "sourceNodeId": "retrospective-evaluation", "targetNodeId": "future-starter-duration", "relation": "FUTURE_NOT_CONFIGURED"},
            {"edgeId": "future-evaluation-to-bullpen", "sourceNodeId": "retrospective-evaluation", "targetNodeId": "future-bullpen-usage", "relation": "FUTURE_NOT_CONFIGURED"},
            {"edgeId": "future-evaluation-to-base-out", "sourceNodeId": "retrospective-evaluation", "targetNodeId": "future-base-out-transition", "relation": "FUTURE_NOT_CONFIGURED"},
            {"edgeId": "future-dynamic-to-simulator", "sourceNodeId": "future-dynamic-player-state", "targetNodeId": "future-game-simulator", "relation": "FUTURE_DEPENDENCY"},
            {"edgeId": "future-lineup-to-simulator", "sourceNodeId": "future-lineup-model", "targetNodeId": "future-game-simulator", "relation": "FUTURE_DEPENDENCY"},
            {"edgeId": "future-starter-to-simulator", "sourceNodeId": "future-starter-duration", "targetNodeId": "future-game-simulator", "relation": "FUTURE_DEPENDENCY"},
            {"edgeId": "future-bullpen-to-simulator", "sourceNodeId": "future-bullpen-usage", "targetNodeId": "future-game-simulator", "relation": "FUTURE_DEPENDENCY"},
            {"edgeId": "future-base-out-to-simulator", "sourceNodeId": "future-base-out-transition", "targetNodeId": "future-game-simulator", "relation": "FUTURE_DEPENDENCY"},
            {"edgeId": "future-simulator-to-residual", "sourceNodeId": "future-game-simulator", "targetNodeId": "future-residual-model", "relation": "FUTURE_DEPENDENCY"},
            {"edgeId": "future-residual-to-bundle", "sourceNodeId": "future-residual-model", "targetNodeId": "future-standalone-asp-bundle", "relation": "FUTURE_DEPENDENCY"},
        ]
    )
    graph_semantic = {"featureContentSha": content_sha, "nodes": nodes, "edges": edges}
    return {
        "graphId": f"mlb-pa-model-graph:sha256:{canonical_sha(graph_semantic)}",
        "nodes": nodes,
        "edges": edges,
    }


def assemble_mlb_pa_research_run(
    *,
    project_id: str,
    join_audit_id: str,
    feature_view: BuiltFeatureView,
    experiment: TrainingExperimentResult,
    runtime_root: Path,
    code_revision: str,
    protected_roots: tuple[Path, ...],
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    progress: Any | None = None,
    feature_checkpoint: _FeatureMaterializationCheckpoint | None = None,
) -> dict[str, Any]:
    """Persist content-addressed runtime evidence and assemble the strict run payload."""

    if project_id != PROJECT_ID:
        raise SportsPARunnerError("project_id differs from the frozen MLB FD1 project anchor")
    if not isinstance(join_audit_id, str) or not _JOIN_AUDIT_ID_RE.fullmatch(join_audit_id):
        raise SportsPARunnerError("join_audit_id must be the persisted content-bound identity audit ID")
    if bootstrap_replicates != DEFAULT_BOOTSTRAP_RESAMPLES:
        raise SportsPARunnerError("governed runs require exactly 500 bootstrap resamples")
    if bootstrap_seed != DEFAULT_BOOTSTRAP_SEED:
        raise SportsPARunnerError("governed runs require the frozen bootstrap seed 20260817")
    reporter = _Progress(progress)
    if feature_checkpoint is None:
        feature_checkpoint = persist_feature_materialization_checkpoint(
            project_id=project_id,
            join_audit_id=join_audit_id,
            feature_view=feature_view,
            runtime_root=runtime_root,
            code_revision=code_revision,
            protected_roots=protected_roots,
        )
    calibration, scaled_probabilities, final_probabilities = _calibration_payload(experiment)
    bootstrap = _bootstrap_payloads(
        experiment,
        n_resamples=bootstrap_replicates,
        seed=bootstrap_seed,
        progress=reporter,
    )
    decision = _decision(experiment, calibration)
    experiment_semantic = {
        "featureContentSha": feature_view.content_sha,
        "objective": "Eight-class conditional terminal plate-appearance outcome research",
        "seed": bootstrap_seed,
        "trainingContractVersion": FEATURE_CONTRACT_VERSION,
    }
    governed_experiment = {
        "experimentId": f"mlb-pa-experiment:sha256:{canonical_sha(experiment_semantic)}",
        "objective": experiment_semantic["objective"],
        "seed": bootstrap_seed,
        "trainingContractVersion": FEATURE_CONTRACT_VERSION,
    }
    parent_anchor = {
        "registrationId": REGISTRATION_ID,
        "manifestSha": PARENT_MANIFEST_SHA,
        "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
    }
    bridge_anchor = {
        "registrationId": BRIDGE_REGISTRATION_ID,
        "manifestSha": BRIDGE_MANIFEST_SHA,
        "joinAuditId": join_audit_id,
    }
    feature_core = {
        "featureViewId": f"mlb-pa-feature-view:sha256:{feature_view.content_sha}",
        "contractName": FEATURE_CONTRACT_NAME,
        "contractVersion": FEATURE_CONTRACT_VERSION,
        "contentSha": feature_view.content_sha,
        "rowCount": feature_view.row_count,
        "featureCount": len(FEATURE_NAMES),
        "featureNames": list(FEATURE_NAMES),
        "population": "strict_deployable",
        "seasons": [2023, 2024, 2025],
    }
    selected = {
        "candidateId": experiment.selected_candidate_id,
        "selectionMetric": "2024_LOG_LOSS_THEN_BRIER_THEN_ORDINAL",
        "rationale": experiment.selected_rationale,
    }
    graph = _graph(experiment, feature_view.content_sha)
    core_projection = {
        "schemaVersion": RESEARCH_RUN_SCHEMA_VERSION,
        "projectId": project_id,
        "parent": parent_anchor,
        "identityBridge": bridge_anchor,
        "classOrder": list(PA_CLASS_ORDER),
        "featureView": feature_core,
        "experiment": governed_experiment,
        "candidates": experiment.candidates,
        "selected": selected,
        "calibration": calibration,
        "bootstrapComparisons": bootstrap,
        "graph": graph,
        "decision": decision,
    }
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    core_wrapper = {
        "schemaVersion": "MLB_PA_RUN_IDENTITY_CORE_V1",
        "createdAt": created_at,
        "codeRevision": code_revision,
        "coreProjection": core_projection,
    }
    core_sha = sha256_bytes(canonical_json_bytes(core_wrapper))
    run_id = f"sports-pa-research-run:sha256:{core_sha}"
    run_identity = {
        "schemaVersion": "MLB_PA_RUN_IDENTITY_V1",
        "coreSha": core_sha,
        "createdAt": created_at,
        "codeRevision": code_revision,
    }
    artifact_bindings = {
        "schemaVersion": "MLB_PA_ARTIFACT_BINDINGS_V1",
        "runId": run_id,
        "runCreatedAt": created_at,
        "projectId": project_id,
        "parent": {
            "manifestSha": PARENT_MANIFEST_SHA,
            "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
        },
        "identityBridge": {
            "manifestSha": BRIDGE_MANIFEST_SHA,
            "joinAuditId": join_audit_id,
            "aliasAuthoritySha": ALIAS_AUTHORITY_SHA,
            "dimensionAuthoritySha": DIMENSION_AUTHORITY_SHA,
        },
        "featureContractSha": feature_view.contract_sha,
        "codeRevision": code_revision,
    }
    writer = _ArtifactWriter.create(
        runtime_root,
        bindings=artifact_bindings,
        protected_roots=protected_roots,
    )
    feature_artifact = feature_checkpoint.feature_artifact
    artifacts: list[dict[str, Any]] = [feature_artifact]
    artifacts.append(
        writer.json(
            "FEATURE_VIEW_RUN_BINDING",
            "feature-view-run-binding.json",
            {
                "materializationId": feature_checkpoint.materialization_id,
                "materializationCreatedAt": feature_checkpoint.created_at,
                "materializationCodeRevision": feature_checkpoint.bindings["codeRevision"],
                "featureViewId": f"mlb-pa-feature-view:sha256:{feature_view.content_sha}",
                "featureContentSha": feature_view.content_sha,
                "featureArtifact": feature_artifact,
            },
        )
    )
    artifacts.extend(
        [
            writer.json(
                "FEATURE_CONTRACT",
                "feature-contract.json",
                {"contractSha256": feature_view.contract_sha, "contract": feature_view.contract},
            ),
            writer.json(
                "FEATURE_SCHEMA",
                "feature-schema.json",
                {"schemaSha256": feature_view.schema_sha, "schema": feature_view.schema_spec},
            ),
            writer.json(
                "CLASS_ORDER",
                "class-order.json",
                {"classOrder": list(PA_CLASS_ORDER), "classCount": len(PA_CLASS_ORDER)},
            ),
        ]
    )
    candidates_by_id = {item["candidateId"]: item for item in experiment.candidates}
    for (season, candidate_id), model in sorted(experiment.models.items()):
        model_state = dict(model.state())
        preprocessor_state = model_state.pop("preprocessor", None)
        fold_record = next(
            item
            for item in candidates_by_id[candidate_id]["foldMetrics"]
            if item["validationSeason"] == season
        )
        common_model_payload = {
            "foldId": fold_record["foldId"],
            "trainingSeasons": fold_record["trainingSeasons"],
            "validationSeason": season,
            "trainingRows": fold_record["trainingRows"],
            "validationRows": fold_record["validationRows"],
            "candidateId": candidate_id,
            "featureViewContentSha": feature_view.content_sha,
        }
        artifacts.append(
            writer.json(
                "MODEL_STATE",
                f"model-{candidate_id}-validate-{season}.json",
                {**common_model_payload, "model": model_state},
            )
        )
        if preprocessor_state is not None:
            artifacts.append(
                writer.json(
                    "PREPROCESSOR_STATE",
                    f"preprocessor-{candidate_id}-validate-{season}.json",
                    {**common_model_payload, "preprocessor": preprocessor_state},
                )
            )
    for season in (2024, 2025):
        fold = experiment.folds[season]
        prediction_bytes = _prediction_parquet(
            fold,
            selected_candidate_id=experiment.selected_candidate_id,
            scaled_selected=scaled_probabilities[season],
            final_selected=final_probabilities[season],
            bindings=artifact_bindings,
        )
        artifacts.append(
            writer.parquet(
                f"FOLD_{season}_PREDICTIONS",
                f"fold-{season}-predictions.parquet",
                prediction_bytes,
            )
        )
    artifacts.extend(
        [
            writer.json(
                "EXPERIMENT_METRICS",
                "experiment-metrics.json",
                {
                    "schemaVersion": TRAINING_SCHEMA_VERSION,
                    "splitEvidence": experiment.split_evidence,
                    "candidates": experiment.candidates,
                    "selectedCandidateId": experiment.selected_candidate_id,
                },
            ),
            writer.json(
                "CONFUSION_MATRICES",
                "confusion-matrices.json",
                {
                    "schemaVersion": "MLB_PA_CONFUSION_MATRICES_V1",
                    "classOrder": list(PA_CLASS_ORDER),
                    "matrices": [
                        {
                            "candidateId": candidate["candidateId"],
                            "foldId": fold["foldId"],
                            "validationSeason": fold["validationSeason"],
                            "rowCount": fold["metrics"]["rowCount"],
                            "axes": fold["metrics"]["confusionMatrixAxes"],
                            "confusionMatrix": fold["metrics"]["confusionMatrix"],
                        }
                        for candidate in experiment.candidates
                        for fold in candidate["foldMetrics"]
                        if fold["status"] == "COMPLETE"
                    ],
                },
            ),
            writer.json("CALIBRATION_EVIDENCE", "calibration.json", calibration),
            writer.json("BOOTSTRAP_EVIDENCE", "bootstrap-comparisons.json", {"comparisons": bootstrap}),
            writer.json(
                "LINEAGE",
                "lineage.json",
                {
                    "featureMaterializationId": feature_checkpoint.materialization_id,
                    "parentRegistrationId": REGISTRATION_ID,
                    "parentManifestSha": PARENT_MANIFEST_SHA,
                    "parentPartitionAuthoritySha": PARTITION_AUTHORITY_SHA,
                    "identityBridgeRegistrationId": BRIDGE_REGISTRATION_ID,
                    "identityBridgeManifestSha": BRIDGE_MANIFEST_SHA,
                    "joinAuditId": join_audit_id,
                    "aliasAuthoritySha": ALIAS_AUTHORITY_SHA,
                    "dimensionAuthoritySha": DIMENSION_AUTHORITY_SHA,
                    "featureContractSha": feature_view.contract_sha,
                    "featureSchemaSha": feature_view.schema_sha,
                    "featureContentSha": feature_view.content_sha,
                    "sourcePartitionIds": list(feature_view.source_partition_ids),
                    "eligiblePriorCoverage": list(feature_view.prior_coverage),
                    "identityFailures": {"unresolved": 0, "ambiguous": 0, "multiplyMapped": 0},
                },
            ),
            writer.json(
                "MODEL_CARD",
                "model-card.json",
                {
                    "schemaVersion": "MLB_PA_MODEL_CARD_V1",
                    "selected": selected,
                    "calibration": calibration,
                    "decision": decision,
                    "candidateSummaries": [
                        {
                            "candidateId": item["candidateId"],
                            "runtimeSeconds": item["runtimeSeconds"],
                            "convergence": item["convergence"],
                            "foldMetrics": item["foldMetrics"],
                        }
                        for item in experiment.candidates
                    ],
                },
            ),
            writer.json(
                "FINAL_CHECKPOINT",
                "final-checkpoint.json",
                {
                    "status": "COMPLETE",
                    "runId": run_id,
                    "featureContentSha": feature_view.content_sha,
                    "selectedCandidateId": experiment.selected_candidate_id,
                    "calibrationDecision": calibration["decision"],
                    "terminalStatus": decision["terminalStatus"],
                },
            ),
        ]
    )
    payload: dict[str, Any] = {
        **core_projection,
        "runId": run_id,
        "runSha": "0" * 64,
        "runIdentity": run_identity,
        "featureView": {
            **feature_core,
            "logicalUri": feature_artifact["logicalUri"],
            "artifactSha": feature_artifact["sha256"],
            "artifactBytes": feature_artifact["byteCount"],
        },
        "artifacts": artifacts,
    }
    semantic = dict(payload)
    semantic.pop("runId")
    semantic.pop("runSha")
    run_sha = sha256_bytes(canonical_json_bytes(semantic))
    payload["runSha"] = run_sha
    reporter(
        {
            "stage": "RESEARCH_RUN_COMPLETE",
            "validationSeason": 2025,
            "trainingRows": 366_553,
            "validationRows": 182_926,
            "selectedCandidateId": experiment.selected_candidate_id,
            "terminalStatus": decision["terminalStatus"],
        }
    )
    return payload


def run_mlb_pa_research(
    *,
    project_id: str,
    parent: ValidatedPackage,
    identity_bridge: ValidatedIdentityBridge,
    join_audit_id: str,
    runtime_root: Path,
    code_revision: str,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    progress: Any | None = None,
) -> dict[str, Any]:
    """Run Phase 3 from already validated immutable package authorities."""

    reporter = _Progress(progress)
    reporter({"stage": "BUILDING_FEATURE_VIEW", "trainingRows": 184_104, "validationRows": 182_449})
    feature_view = build_mlb_pa_feature_view_v1(
        parent,
        identity_bridge,
        code_revision=code_revision,
        progress=reporter,
    )
    reporter(
        {
            "stage": "PERSISTING_FEATURE_MATERIALIZATION_CHECKPOINT",
            "rowsProcessed": feature_view.row_count,
        }
    )
    feature_checkpoint = persist_feature_materialization_checkpoint(
        project_id=project_id,
        join_audit_id=join_audit_id,
        feature_view=feature_view,
        runtime_root=runtime_root,
        code_revision=code_revision,
        protected_roots=(parent.package_root, identity_bridge.package_root),
    )
    reporter({"stage": "RUNNING_FROZEN_EXPERIMENT", "rowsProcessed": feature_view.row_count})
    experiment = run_training_experiment(feature_view.table, progress=reporter)
    return assemble_mlb_pa_research_run(
        project_id=project_id,
        join_audit_id=join_audit_id,
        feature_view=feature_view,
        experiment=experiment,
        runtime_root=runtime_root,
        code_revision=code_revision,
        protected_roots=(parent.package_root, identity_bridge.package_root),
        bootstrap_replicates=bootstrap_replicates,
        bootstrap_seed=bootstrap_seed,
        progress=progress,
        feature_checkpoint=feature_checkpoint,
    )


__all__ = [
    "RUNNER_SCHEMA_VERSION",
    "RUNTIME_NAMESPACE",
    "RUNTIME_URI_PREFIX",
    "SportsPARunnerError",
    "assemble_mlb_pa_research_run",
    "persist_feature_materialization_checkpoint",
    "run_mlb_pa_research",
]
