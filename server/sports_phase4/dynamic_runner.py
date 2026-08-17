from __future__ import annotations

import copy
import json
import os
import re
import stat
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from server.sports_datasets.constants import (
    PARTITION_AUTHORITY_SHA,
    PROJECT_ID,
    REGISTRATION_ID as DATASET_REGISTRATION_ID,
)
from server.sports_datasets.consumer import (
    ValidatedPackage,
    canonical_json_bytes,
    raw_absolute_path,
    reject_reparse_chain,
    sha256_bytes,
)
from server.sports_identity_bridges.constants import (
    ALIAS_AUTHORITY_SHA,
    BRIDGE_MANIFEST_SHA,
    BRIDGE_REGISTRATION_ID,
    DIMENSION_AUTHORITY_SHA,
)
from server.sports_identity_bridges.consumer import ValidatedIdentityBridge
from server.sports_modeling.feature_contract import (
    EXPECTED_SEASON_ROWS,
    EXPECTED_TOTAL_ROWS,
    feature_contract_sha,
    feature_schema_sha,
)
from server.sports_modeling.feature_view import (
    _arrow_schema as _phase3_feature_arrow_schema,
)
from server.sports_modeling.metrics import PA_CLASS_ORDER

from .dynamic_contract import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CANDIDATE_FEATURES,
    CONTRACT_NAME,
    DESCRIPTOR_SCHEMA_VERSION,
    PHASE3_FEATURE_ARTIFACT_SHA,
    PHASE3_FEATURE_CONTENT_SHA,
    PHASE3_FEATURE_CONTRACT_SHA,
    PHASE3_FEATURE_MATERIALIZATION_ID,
    PHASE3_FEATURE_VIEW_ID,
    PHASE3_FOLD_2024_PREDICTION_SHA,
    PHASE3_FOLD_2025_PREDICTION_SHA,
    PHASE3_RUN_ID,
    PHASE3_RUN_SHA,
    SEMANTIC_VERSION,
    dynamic_history_index_schema_sha,
    dynamic_state_contract_payload,
    dynamic_state_contract_sha,
    dynamic_state_schema_sha,
    validate_dynamic_component_evidence,
)
from .dynamic_state import (
    BuiltDynamicPlayerState,
    BuiltHistoricalDynamicIndex,
    DynamicStateIntegrityError,
    build_mlb_dynamic_player_state_bundle_v1,
    dynamic_state_table_content_sha,
    historical_dynamic_index_descriptor,
    load_historical_dynamic_index,
)
from .dynamic_training import (
    DYNAMIC_TRAINING_SCHEMA_VERSION,
    DynamicEvaluationEvidence,
    DynamicTrainingExperiment,
    FrozenD0Fold,
    evaluate_dynamic_experiment,
    run_dynamic_training_experiment,
)


RUNTIME_NAMESPACE = "mlb-dynamic-player-state-v1"
RUNTIME_URI_PREFIX = f"asp-model-studio-runtime://sports-phase4/{RUNTIME_NAMESPACE}"
PHASE3_RUNTIME_NAMESPACE = "mlb-pa-v1"
PHASE3_RUNTIME_URI_PREFIX = "asp-model-studio-runtime://sports-modeling/mlb-pa-v1"
RUNNER_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_RUNNER_V1"
CHECKPOINT_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_CHECKPOINT_V1"
ARTIFACT_BINDINGS_SCHEMA_VERSION = "MLB_DYNAMIC_PLAYER_STATE_ARTIFACT_BINDINGS_V1"
MAX_OVERALL_SECONDS = 8 * 60 * 60
RUNNER_HEARTBEAT_SECONDS = 45.0
MAX_RSS_BYTES = 8 * 1024**3
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")

_PHASE3_FEATURE_BYTES = 11_574_290
_PHASE3_PREDICTION_BYTES = {2024: 57_339_406, 2025: 36_820_708}
_PHASE3_FEATURE_SCHEMA_SHA = "1660eed54bf3904c2f2306d5a0171e7df6bf87fdc4fa9d39fb5ec2e8e741afd6"
_PHASE3_FILENAMES = {
    "feature": "mlb-pa-feature-view-v1.parquet",
    2024: "fold-2024-predictions.parquet",
    2025: "fold-2025-predictions.parquet",
}
_ARTIFACT_BINDING_KEYS = {
    "schemaVersion",
    "createdAt",
    "codeRevision",
    "datasetManifestSha",
    "identityBridgeManifestSha",
    "phase3FeatureContractSha",
    "componentContractSha",
    "artifactType",
    "temporalFold",
    "sourcePartitionIds",
    "classOrder",
    "targetOrder",
}


class DynamicRunnerError(RuntimeError):
    """Fail-closed Phase 4 runtime, lineage, or artifact-integrity error."""


@dataclass(frozen=True)
class Phase3RuntimeInputs:
    feature_table: pa.Table
    feature_artifact: dict[str, Any]
    prediction_artifacts: dict[int, dict[str, Any]]
    d0_folds: dict[int, FrozenD0Fold]
    source_partition_ids: tuple[str, ...]
    feature_bindings: dict[str, Any]
    prediction_bindings: dict[int, dict[str, Any]]


@dataclass(frozen=True)
class DynamicMaterializationCheckpoint:
    checkpoint_id: str
    code_revision: str
    materialization_bindings: dict[str, Any]
    state_artifact: dict[str, Any]
    history_artifact: dict[str, Any]
    history_descriptor: dict[str, Any]
    state_table: pa.Table

    @property
    def artifacts(self) -> list[dict[str, Any]]:
        return [self.state_artifact, self.history_artifact]


def _emit(progress: Any | None, stage: str, evidence: Mapping[str, Any]) -> None:
    if progress is not None:
        progress(stage, {"stage": stage, **dict(evidence)})


class _OverallHeartbeat:
    def __init__(self, callback: Any | None) -> None:
        self.callback = callback
        self.started = time.monotonic()
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None

    def __enter__(self) -> "_OverallHeartbeat":
        if self.callback is not None:
            self.thread = threading.Thread(
                target=self._run,
                name="dynamic-runner-heartbeat",
                daemon=True,
            )
            self.thread.start()
        return self

    def _run(self) -> None:
        while not self.stopped.wait(RUNNER_HEARTBEAT_SECONDS):
            _emit(
                self.callback,
                "DYNAMIC_RUNNER_HEARTBEAT",
                {
                    "elapsedSeconds": round(time.monotonic() - self.started, 2),
                    "maxOverallSeconds": MAX_OVERALL_SECONDS,
                    "errors": 0,
                },
            )

    def check(self) -> None:
        if time.monotonic() - self.started > MAX_OVERALL_SECONDS:
            raise DynamicRunnerError("dynamic runner exceeded the eight-hour limit")
        try:
            import psutil

            if psutil.Process().memory_info().rss > MAX_RSS_BYTES:
                raise DynamicRunnerError("dynamic runner exceeded the eight-GiB RSS limit")
        except ImportError:
            pass

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        if exc_type is None:
            self.check()


def _validated_runtime_root(
    runtime_root: Path,
    protected_roots: Sequence[Path] = (),
) -> Path:
    raw_root = raw_absolute_path(Path(runtime_root))
    repository_root = Path(__file__).resolve().parents[2]
    raw_boundary = raw_absolute_path(
        repository_root / ".runtime" / "asp-model-studio" / "sports-modeling"
    )
    if raw_root != raw_boundary and raw_boundary not in raw_root.parents:
        raise DynamicRunnerError(
            "runtime_root must remain inside .runtime/asp-model-studio/sports-modeling"
        )
    reject_reparse_chain(raw_root, label="Dynamic runtime root chain")
    resolved_boundary = raw_boundary.resolve(strict=False)
    resolved_root = raw_root.resolve(strict=False)
    if resolved_root != resolved_boundary and resolved_boundary not in resolved_root.parents:
        raise DynamicRunnerError("runtime_root resolves outside the repository runtime boundary")
    for protected_root in protected_roots:
        protected = Path(protected_root).resolve(strict=True)
        if resolved_root == protected or protected in resolved_root.parents:
            raise DynamicRunnerError("runtime_root may not be inside a read-only authority")
    raw_root.mkdir(parents=True, exist_ok=True)
    reject_reparse_chain(raw_root, label="Dynamic runtime root chain")
    created = raw_root.resolve(strict=True)
    if created != resolved_boundary and resolved_boundary not in created.parents:
        raise DynamicRunnerError("created runtime_root escaped the repository boundary")
    return raw_root


def _strict_json(content: bytes, *, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise DynamicRunnerError(f"{label} contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(
                DynamicRunnerError(f"{label} contains non-finite {item}")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DynamicRunnerError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise DynamicRunnerError(f"{label} must be an object")
    return value


def _artifact_path(runtime_root: Path, artifact: Mapping[str, Any]) -> Path:
    uri = artifact.get("logicalUri")
    if not isinstance(uri, str) or not uri.startswith(RUNTIME_URI_PREFIX + "/"):
        raise DynamicRunnerError("dynamic artifact logical URI differs")
    suffix = uri[len(RUNTIME_URI_PREFIX) + 1 :]
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
        raise DynamicRunnerError("dynamic artifact logical URI is unsafe")
    namespace_root = runtime_root / RUNTIME_NAMESPACE
    reject_reparse_chain(namespace_root, label="Dynamic object namespace chain")
    candidate = namespace_root.joinpath(*parsed.parts)
    reject_reparse_chain(candidate, label="Dynamic artifact chain")
    try:
        resolved = candidate.resolve(strict=True)
        resolved_namespace = namespace_root.resolve(strict=True)
    except OSError as exc:
        raise DynamicRunnerError("dynamic artifact is missing") from exc
    if resolved == resolved_namespace or resolved_namespace not in resolved.parents:
        raise DynamicRunnerError("dynamic artifact escaped the namespace")
    metadata = resolved.stat()
    if resolved.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise DynamicRunnerError("dynamic artifact may not be a link")
    return resolved


def _base_artifact_bindings(
    *,
    created_at: str,
    code_revision: str,
    dynamic_source_partition_ids: Sequence[str],
    phase3_source_partition_ids: Sequence[str],
) -> dict[str, Any]:
    if not isinstance(created_at, str) or not created_at.endswith("Z"):
        raise DynamicRunnerError("artifact binding creation time differs")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DynamicRunnerError("artifact binding creation time is invalid") from exc
    if not isinstance(code_revision, str) or not code_revision.strip():
        raise DynamicRunnerError("artifact binding code revision differs")
    dynamic_ids = list(dynamic_source_partition_ids)
    phase3_ids = list(phase3_source_partition_ids)
    for label, values in (
        ("dynamicHistory", dynamic_ids),
        ("phase3Feature", phase3_ids),
    ):
        if values != sorted(values) or len(set(values)) != len(values) or not all(
            isinstance(value, str) and value for value in values
        ):
            raise DynamicRunnerError(f"artifact binding {label} partition identities differ")
    return {
        "schemaVersion": ARTIFACT_BINDINGS_SCHEMA_VERSION,
        "createdAt": created_at,
        "codeRevision": code_revision,
        "datasetManifestSha": dynamic_state_contract_payload()["authorityBindings"]["dataset"]["manifestSha"],
        "identityBridgeManifestSha": BRIDGE_MANIFEST_SHA,
        "phase3FeatureContractSha": PHASE3_FEATURE_CONTRACT_SHA,
        "componentContractSha": dynamic_state_contract_sha(),
        "sourcePartitionIds": {
            "dynamicHistory": dynamic_ids,
            "phase3Feature": phase3_ids,
        },
        "classOrder": list(PA_CLASS_ORDER),
        "targetOrder": list(PA_CLASS_ORDER),
    }


def _artifact_bindings_for_fold(
    base: Mapping[str, Any],
    temporal_fold: str,
    artifact_type: str,
) -> dict[str, Any]:
    if not isinstance(base, Mapping) or set(base) != _ARTIFACT_BINDING_KEYS - {
        "artifactType",
        "temporalFold",
    }:
        raise DynamicRunnerError("artifact base binding fields differ")
    if not isinstance(temporal_fold, str) or not temporal_fold.strip():
        raise DynamicRunnerError("artifact temporal fold differs")
    if not isinstance(artifact_type, str) or not artifact_type.strip():
        raise DynamicRunnerError("artifact type binding differs")
    return {
        **dict(base),
        "artifactType": artifact_type,
        "temporalFold": temporal_fold,
    }


def _bound_parquet_bytes(content: bytes, *, bindings: Mapping[str, Any]) -> bytes:
    if set(bindings) != _ARTIFACT_BINDING_KEYS:
        raise DynamicRunnerError("Parquet artifact binding fields differ")
    try:
        table = pq.read_table(pa.BufferReader(content))
    except Exception as exc:
        raise DynamicRunnerError("dynamic Parquet artifact is unreadable") from exc
    metadata = dict(table.schema.metadata or {})
    metadata[b"artifactBindings"] = canonical_json_bytes(dict(bindings))
    metadata[b"artifactType"] = str(bindings["artifactType"]).encode("utf-8")
    sink = pa.BufferOutputStream()
    pq.write_table(
        table.replace_schema_metadata(metadata),
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


def _validate_artifact_bindings(
    bindings: Mapping[str, Any],
    *,
    expected_artifact_type: str,
) -> dict[str, Any]:
    if not isinstance(bindings, Mapping) or set(bindings) != _ARTIFACT_BINDING_KEYS:
        raise DynamicRunnerError("dynamic artifact binding fields differ")
    normalized = dict(bindings)
    base = dict(normalized)
    temporal_fold = base.pop("temporalFold")
    artifact_type = base.pop("artifactType")
    # Reuse the constructor's timestamp, revision, partition-order, and authority
    # checks, then require byte-for-byte equality with the stored binding.
    source = base.get("sourcePartitionIds")
    if not isinstance(source, Mapping) or set(source) != {"dynamicHistory", "phase3Feature"}:
        raise DynamicRunnerError("dynamic artifact source partition bindings differ")
    expected = _base_artifact_bindings(
        created_at=base.get("createdAt"),
        code_revision=base.get("codeRevision"),
        dynamic_source_partition_ids=source.get("dynamicHistory", ()),
        phase3_source_partition_ids=source.get("phase3Feature", ()),
    )
    if base != expected or artifact_type != expected_artifact_type:
        raise DynamicRunnerError("dynamic artifact authority binding differs")
    if not isinstance(temporal_fold, str) or not temporal_fold.strip():
        raise DynamicRunnerError("dynamic artifact temporal fold differs")
    return normalized


def verify_dynamic_artifact_body(
    runtime_root: Path,
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconcile a dynamic artifact reference with exact body bytes and bindings."""

    reference_fields = {
        "artifactId",
        "artifactType",
        "logicalUri",
        "sha256",
        "byteCount",
        "mediaType",
    }
    if not isinstance(reference, Mapping) or set(reference) != reference_fields:
        raise DynamicRunnerError("dynamic artifact reference fields differ")
    artifact_type = reference.get("artifactType")
    digest = reference.get("sha256")
    byte_count = reference.get("byteCount")
    media_type = reference.get("mediaType")
    if (
        not isinstance(artifact_type, str)
        or not artifact_type
        or not isinstance(digest, str)
        or not _SHA_RE.fullmatch(digest)
        or not isinstance(byte_count, int)
        or isinstance(byte_count, bool)
        or byte_count <= 0
        or reference.get("artifactId")
        != f"sports-phase4-artifact:{artifact_type.casefold()}:sha256:{digest}"
    ):
        raise DynamicRunnerError("dynamic artifact reference identity differs")
    path = _artifact_path(_validated_runtime_root(runtime_root), reference)
    content = path.read_bytes()
    if len(content) != byte_count or sha256_bytes(content) != digest:
        raise DynamicRunnerError("dynamic artifact reference/body integrity differs")
    if media_type == "application/json":
        envelope = _strict_json(content, label="Dynamic JSON artifact")
        if set(envelope) != {
            "schemaVersion",
            "artifactType",
            "artifactBindings",
            "payload",
        }:
            raise DynamicRunnerError("dynamic JSON artifact envelope differs")
        if (
            envelope.get("schemaVersion")
            != "MLB_DYNAMIC_PLAYER_STATE_RUNTIME_ARTIFACT_V1"
            or envelope.get("artifactType") != artifact_type
            or not isinstance(envelope.get("payload"), dict)
        ):
            raise DynamicRunnerError("dynamic JSON artifact body differs")
        bindings = envelope.get("artifactBindings")
    elif media_type == "application/vnd.apache.parquet":
        try:
            metadata = pq.ParquetFile(pa.BufferReader(content)).schema_arrow.metadata or {}
            if metadata.get(b"artifactType") != artifact_type.encode("utf-8"):
                raise DynamicRunnerError("dynamic Parquet artifact type binding differs")
            bindings = _strict_json(
                metadata.get(b"artifactBindings", b""),
                label="Dynamic Parquet artifact bindings",
            )
        except DynamicRunnerError:
            raise
        except Exception as exc:
            raise DynamicRunnerError("dynamic Parquet artifact body is unreadable") from exc
    else:
        raise DynamicRunnerError("dynamic artifact media type differs")
    return _validate_artifact_bindings(
        bindings,
        expected_artifact_type=artifact_type,
    )


@dataclass(frozen=True)
class _ArtifactWriter:
    runtime_root: Path
    base_bindings: dict[str, Any]

    @classmethod
    def create(
        cls,
        runtime_root: Path,
        *,
        base_bindings: Mapping[str, Any],
        protected_roots: Sequence[Path] = (),
    ) -> "_ArtifactWriter":
        if set(base_bindings) != _ARTIFACT_BINDING_KEYS - {
            "artifactType",
            "temporalFold",
        }:
            raise DynamicRunnerError("artifact writer base bindings differ")
        return cls(
            _validated_runtime_root(runtime_root, protected_roots),
            dict(base_bindings),
        )

    def _write(
        self,
        artifact_type: str,
        filename: str,
        content: bytes,
        *,
        media_type: str,
    ) -> dict[str, Any]:
        if not artifact_type or not filename or not isinstance(content, bytes) or not content:
            raise DynamicRunnerError("dynamic artifacts require type, filename, and bytes")
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
        if self.runtime_root not in destination.parents:
            raise DynamicRunnerError("dynamic artifact path escaped the runtime root")
        reject_reparse_chain(destination.parent, label="Dynamic artifact parent chain")
        destination.parent.mkdir(parents=True, exist_ok=True)
        reject_reparse_chain(destination.parent, label="Dynamic artifact parent chain")
        if destination.exists():
            reject_reparse_chain(destination, label="Dynamic artifact chain")
            if destination.is_symlink() or destination.stat().st_nlink != 1:
                raise DynamicRunnerError("existing dynamic artifact may not be a link")
            if destination.read_bytes() != content:
                raise DynamicRunnerError("existing content-addressed dynamic artifact differs")
        else:
            temporary: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=".dynamic-artifact-",
                    suffix=".tmp",
                    dir=destination.parent,
                    delete=False,
                ) as handle:
                    temporary = handle.name
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
                temporary = None
            finally:
                if temporary is not None:
                    Path(temporary).unlink(missing_ok=True)
        reject_reparse_chain(destination, label="Dynamic artifact chain")
        resolved = destination.resolve(strict=True)
        if self.runtime_root.resolve(strict=True) not in resolved.parents:
            raise DynamicRunnerError("dynamic artifact resolved outside the runtime root")
        if resolved.stat().st_nlink != 1:
            raise DynamicRunnerError("dynamic artifact may not be a hardlink")
        return {
            "artifactId": f"sports-phase4-artifact:{artifact_type.casefold()}:sha256:{digest}",
            "artifactType": artifact_type,
            "logicalUri": (
                f"{RUNTIME_URI_PREFIX}/objects/sha256/{digest[:2]}/{digest}/{filename}"
            ),
            "sha256": digest,
            "byteCount": len(content),
            "mediaType": media_type,
        }

    def json(
        self,
        artifact_type: str,
        filename: str,
        payload: Mapping[str, Any],
        *,
        temporal_fold: str,
    ) -> dict[str, Any]:
        bindings = _artifact_bindings_for_fold(
            self.base_bindings,
            temporal_fold,
            artifact_type,
        )
        envelope = {
            "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_RUNTIME_ARTIFACT_V1",
            "artifactType": artifact_type,
            "artifactBindings": bindings,
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
        *,
        temporal_fold: str,
    ) -> dict[str, Any]:
        bindings = _artifact_bindings_for_fold(
            self.base_bindings,
            temporal_fold,
            artifact_type,
        )
        bound = _bound_parquet_bytes(content, bindings=bindings)
        return self._write(
            artifact_type,
            filename,
            bound,
            media_type="application/vnd.apache.parquet",
        )


def _phase3_reference(
    artifact_type: str,
    digest: str,
    byte_count: int,
    filename: str,
) -> dict[str, Any]:
    return {
        "artifactId": f"sports-pa-artifact:{artifact_type.casefold()}:sha256:{digest}",
        "artifactType": artifact_type,
        "logicalUri": (
            f"{PHASE3_RUNTIME_URI_PREFIX}/objects/sha256/{digest[:2]}/{digest}/{filename}"
        ),
        "sha256": digest,
        "byteCount": byte_count,
        "mediaType": "application/vnd.apache.parquet",
    }


def _read_phase3_object(
    root: Path,
    *,
    digest: str,
    byte_count: int,
    filename: str,
) -> bytes:
    candidate = (
        root
        / PHASE3_RUNTIME_NAMESPACE
        / "objects"
        / "sha256"
        / digest[:2]
        / digest
        / filename
    )
    reject_reparse_chain(candidate, label="Phase 3 runtime artifact chain")
    try:
        resolved = candidate.resolve(strict=True)
        namespace = (root / PHASE3_RUNTIME_NAMESPACE).resolve(strict=True)
    except OSError as exc:
        raise DynamicRunnerError("required Phase 3 runtime artifact is missing") from exc
    if namespace not in resolved.parents:
        raise DynamicRunnerError("Phase 3 runtime artifact escaped its namespace")
    metadata = resolved.stat()
    if resolved.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise DynamicRunnerError("Phase 3 runtime artifact may not be a link")
    content = resolved.read_bytes()
    if len(content) != byte_count or sha256_bytes(content) != digest:
        raise DynamicRunnerError("Phase 3 runtime artifact bytes differ from registry authority")
    return content


def _validate_phase3_bindings(
    raw: bytes,
    *,
    expected_run_id: str,
) -> dict[str, Any]:
    bindings = _strict_json(raw, label="Phase 3 artifact bindings")
    if set(bindings) != {
        "schemaVersion",
        "runId",
        "runCreatedAt",
        "projectId",
        "parent",
        "identityBridge",
        "featureContractSha",
        "codeRevision",
    }:
        raise DynamicRunnerError("Phase 3 artifact binding fields differ")
    expected = {
        "schemaVersion": "MLB_PA_ARTIFACT_BINDINGS_V1",
        "runId": expected_run_id,
        "projectId": PROJECT_ID,
        "parent": {
            "manifestSha": dynamic_state_contract_payload()["authorityBindings"]["dataset"]["manifestSha"],
            "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
        },
        "identityBridge": {
            "manifestSha": BRIDGE_MANIFEST_SHA,
            "joinAuditId": dynamic_state_contract_payload()["authorityBindings"]["identityBridge"]["joinAuditId"],
            "aliasAuthoritySha": ALIAS_AUTHORITY_SHA,
            "dimensionAuthoritySha": DIMENSION_AUTHORITY_SHA,
        },
        "featureContractSha": PHASE3_FEATURE_CONTRACT_SHA,
    }
    if any(bindings.get(name) != value for name, value in expected.items()):
        raise DynamicRunnerError("Phase 3 artifact authority binding differs")
    if not isinstance(bindings.get("runCreatedAt"), str) or not bindings["runCreatedAt"].endswith("Z"):
        raise DynamicRunnerError("Phase 3 artifact creation time differs")
    if not isinstance(bindings.get("codeRevision"), str) or not bindings["codeRevision"].strip():
        raise DynamicRunnerError("Phase 3 artifact code revision differs")
    return bindings


def load_phase3_runtime_inputs(runtime_root: Path) -> Phase3RuntimeInputs:
    root = _validated_runtime_root(runtime_root)
    feature_bytes = _read_phase3_object(
        root,
        digest=PHASE3_FEATURE_ARTIFACT_SHA,
        byte_count=_PHASE3_FEATURE_BYTES,
        filename=_PHASE3_FILENAMES["feature"],
    )
    try:
        feature_parquet = pq.ParquetFile(pa.BufferReader(feature_bytes))
        feature_metadata = feature_parquet.schema_arrow.metadata or {}
        feature_table = pq.read_table(pa.BufferReader(feature_bytes))
    except Exception as exc:
        raise DynamicRunnerError("Phase 3 feature artifact is unreadable") from exc
    if feature_table.schema.remove_metadata() != _phase3_feature_arrow_schema():
        raise DynamicRunnerError("Phase 3 feature schema differs")
    expected_feature_metadata = {
        b"artifactSchemaVersion": b"MLB_PA_FEATURE_VIEW_ARTIFACT_V1",
        b"runId": PHASE3_FEATURE_MATERIALIZATION_ID.encode("utf-8"),
        b"featureContentSha": PHASE3_FEATURE_CONTENT_SHA.encode("ascii"),
        b"featureContractSha": PHASE3_FEATURE_CONTRACT_SHA.encode("ascii"),
        b"featureSchemaSha": _PHASE3_FEATURE_SCHEMA_SHA.encode("ascii"),
        b"rowCount": str(EXPECTED_TOTAL_ROWS).encode("ascii"),
    }
    if any(feature_metadata.get(name) != value for name, value in expected_feature_metadata.items()):
        raise DynamicRunnerError("Phase 3 feature Parquet metadata differs")
    if feature_contract_sha() != PHASE3_FEATURE_CONTRACT_SHA or feature_schema_sha() != _PHASE3_FEATURE_SCHEMA_SHA:
        raise DynamicRunnerError("local Phase 3 feature contract differs from registered authority")
    feature_bindings = _validate_phase3_bindings(
        feature_metadata.get(b"artifactBindings", b""),
        expected_run_id=PHASE3_FEATURE_MATERIALIZATION_ID,
    )
    if (
        feature_metadata.get(b"codeRevision") != feature_bindings["codeRevision"].encode("utf-8")
        or feature_metadata.get(b"runCreatedAt") != feature_bindings["runCreatedAt"].encode("utf-8")
    ):
        raise DynamicRunnerError("Phase 3 feature metadata/bindings differ")
    # Parquet decoding can canonicalize NaN payload bits, so the Phase 3 Arrow-stream
    # semantic digest is not recomputable from a decoded table.  The registered
    # Parquet is instead bound by its exact artifact bytes/SHA above and by its
    # immutable content/contract/schema metadata before those same decoded bytes feed
    # every Phase 4 join and fit.
    if feature_table.num_rows != EXPECTED_TOTAL_ROWS:
        raise DynamicRunnerError("Phase 3 feature row count differs")
    seasons = np.asarray(feature_table["season"].combine_chunks().to_numpy(), dtype=np.int64)
    if {season: int(np.count_nonzero(seasons == season)) for season in (2023, 2024, 2025)} != dict(
        EXPECTED_SEASON_ROWS
    ):
        raise DynamicRunnerError("Phase 3 feature season counts differ")
    try:
        source_partition_ids = tuple(
            json.loads(feature_metadata[b"sourcePartitionIds"].decode("utf-8"))
        )
    except Exception as exc:
        raise DynamicRunnerError("Phase 3 feature source partition identities differ") from exc
    if (
        len(source_partition_ids) != 26
        or tuple(sorted(source_partition_ids)) != source_partition_ids
        or len(set(source_partition_ids)) != len(source_partition_ids)
        or not all(isinstance(value, str) and _SHA_RE.fullmatch(value) for value in source_partition_ids)
    ):
        raise DynamicRunnerError("Phase 3 feature source partition identities differ")

    prediction_artifacts: dict[int, dict[str, Any]] = {}
    prediction_bindings: dict[int, dict[str, Any]] = {}
    d0_folds: dict[int, FrozenD0Fold] = {}
    for season, digest in (
        (2024, PHASE3_FOLD_2024_PREDICTION_SHA),
        (2025, PHASE3_FOLD_2025_PREDICTION_SHA),
    ):
        content = _read_phase3_object(
            root,
            digest=digest,
            byte_count=_PHASE3_PREDICTION_BYTES[season],
            filename=_PHASE3_FILENAMES[season],
        )
        try:
            parquet = pq.ParquetFile(pa.BufferReader(content))
            metadata = parquet.schema_arrow.metadata or {}
            table = pq.read_table(pa.BufferReader(content))
        except Exception as exc:
            raise DynamicRunnerError("Phase 3 D0 prediction artifact is unreadable") from exc
        expected_fold_id = (
            "train-2023-validate-2024"
            if season == 2024
            else "train-through-2024-validate-2025"
        )
        expected_metadata = {
            b"artifactSchemaVersion": b"MLB_PA_FOLD_PREDICTIONS_V1",
            b"runId": PHASE3_RUN_ID.encode("utf-8"),
            b"foldId": expected_fold_id.encode("utf-8"),
            b"validationSeason": str(season).encode("ascii"),
            b"rowCount": str(EXPECTED_SEASON_ROWS[season]).encode("ascii"),
            b"selectedCandidateId": b"C4",
            b"classOrder": canonical_json_bytes(list(PA_CLASS_ORDER)),
        }
        if any(metadata.get(name) != value for name, value in expected_metadata.items()):
            raise DynamicRunnerError("Phase 3 D0 prediction metadata differs")
        bindings = _validate_phase3_bindings(
            metadata.get(b"artifactBindings", b""),
            expected_run_id=PHASE3_RUN_ID,
        )
        if (
            metadata.get(b"codeRevision") != bindings["codeRevision"].encode("utf-8")
            or metadata.get(b"runCreatedAt") != bindings["runCreatedAt"].encode("utf-8")
        ):
            raise DynamicRunnerError("Phase 3 D0 metadata/bindings differ")
        reference = _phase3_reference(
            f"FOLD_{season}_PREDICTIONS",
            digest,
            len(content),
            _PHASE3_FILENAMES[season],
        )
        prediction_artifacts[season] = reference
        prediction_bindings[season] = bindings
        d0_folds[season] = FrozenD0Fold(season, digest, table)
    return Phase3RuntimeInputs(
        feature_table=feature_table,
        feature_artifact=_phase3_reference(
            "FEATURE_VIEW",
            PHASE3_FEATURE_ARTIFACT_SHA,
            len(feature_bytes),
            _PHASE3_FILENAMES["feature"],
        ),
        prediction_artifacts=prediction_artifacts,
        d0_folds=d0_folds,
        source_partition_ids=source_partition_ids,
        feature_bindings=feature_bindings,
        prediction_bindings=prediction_bindings,
    )


def _atomic_write(destination: Path, content: bytes) -> None:
    reject_reparse_chain(destination.parent, label="Dynamic checkpoint parent chain")
    destination.parent.mkdir(parents=True, exist_ok=True)
    reject_reparse_chain(destination.parent, label="Dynamic checkpoint parent chain")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".dynamic-checkpoint-",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    reject_reparse_chain(destination, label="Dynamic checkpoint chain")
    if destination.stat().st_nlink != 1:
        raise DynamicRunnerError("dynamic checkpoint may not be a hardlink")


def persist_dynamic_materialization_checkpoint(
    state: BuiltDynamicPlayerState,
    history: BuiltHistoricalDynamicIndex,
    *,
    runtime_root: Path,
    code_revision: str,
    phase3_source_partition_ids: Sequence[str] = (),
    protected_roots: Sequence[Path] = (),
) -> DynamicMaterializationCheckpoint:
    if not isinstance(code_revision, str) or not code_revision.strip():
        raise ValueError("code_revision must be non-empty")
    root = _validated_runtime_root(runtime_root, protected_roots)
    core = {
        "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_CHECKPOINT_IDENTITY_V1",
        "contractSha": state.contract_sha,
        "stateContentSha": state.content_sha,
        "historyContentSha": history.content_sha,
        "policyId": state.policy.policy_id,
        "sourcePartitionIds": list(state.source_partition_ids),
        "phase3SourcePartitionIds": list(phase3_source_partition_ids),
    }
    checkpoint_id = "mlb-dynamic-player-state-checkpoint:sha256:" + sha256_bytes(
        canonical_json_bytes(core)
    )
    pointer = (
        root
        / RUNTIME_NAMESPACE
        / "checkpoints"
        / f"sha256-{checkpoint_id.rsplit(':', 1)[-1]}"
        / "checkpoint.json"
    )
    reject_reparse_chain(pointer.parent, label="Dynamic checkpoint pointer parent chain")
    if pointer.exists():
        reject_reparse_chain(pointer, label="Dynamic checkpoint pointer chain")
        if pointer.is_symlink() or pointer.stat().st_nlink != 1:
            raise DynamicRunnerError("dynamic checkpoint pointer may not be a link")
        stored = _strict_json(pointer.read_bytes(), label="Dynamic materialization checkpoint")
        if set(stored) != {
            "schemaVersion",
            "checkpointId",
            "checkpointCore",
            "codeRevision",
            "materializationBindings",
            "stateArtifact",
            "historyArtifact",
            "historyDescriptor",
        }:
            raise DynamicRunnerError("dynamic checkpoint shape differs")
        if (
            stored.get("schemaVersion") != CHECKPOINT_SCHEMA_VERSION
            or stored.get("checkpointId") != checkpoint_id
            or stored.get("checkpointCore") != core
            or not isinstance(stored.get("codeRevision"), str)
            or not stored["codeRevision"].strip()
        ):
            raise DynamicRunnerError("dynamic checkpoint binding differs")
        materialization_bindings = stored.get("materializationBindings")
        if not isinstance(materialization_bindings, dict):
            raise DynamicRunnerError("dynamic checkpoint materialization binding differs")
        expected_base = _base_artifact_bindings(
            created_at=materialization_bindings.get("createdAt"),
            code_revision=stored["codeRevision"],
            dynamic_source_partition_ids=state.source_partition_ids,
            phase3_source_partition_ids=phase3_source_partition_ids,
        )
        if materialization_bindings != expected_base:
            raise DynamicRunnerError("dynamic checkpoint materialization binding differs")
        writer = _ArtifactWriter.create(
            root,
            base_bindings=materialization_bindings,
            protected_roots=protected_roots,
        )
        references = [stored.get("stateArtifact"), stored.get("historyArtifact")]
        for reference in references:
            if not isinstance(reference, dict) or set(reference) != {
                "artifactId",
                "artifactType",
                "logicalUri",
                "sha256",
                "byteCount",
                "mediaType",
            }:
                raise DynamicRunnerError("dynamic checkpoint artifact reference differs")
        state_path = _artifact_path(writer.runtime_root, references[0])
        history_path = _artifact_path(writer.runtime_root, references[1])
        state_bytes = state_path.read_bytes()
        history_bytes = history_path.read_bytes()
        for content, reference in zip((state_bytes, history_bytes), references, strict=True):
            if len(content) != reference["byteCount"] or sha256_bytes(content) != reference["sha256"]:
                raise DynamicRunnerError("dynamic checkpoint artifact integrity differs")
        # Rebuild the expected bound artifacts from fresh semantic bytes plus the
        # original immutable materialization binding.  Self-declared Parquet
        # metadata or a self-consistent stale checkpoint cannot substitute.
        expected_state_bytes = _bound_parquet_bytes(
            state.parquet_bytes,
            bindings=_artifact_bindings_for_fold(
                materialization_bindings,
                "NOT_APPLICABLE",
                "DYNAMIC_PLAYER_STATE",
            ),
        )
        expected_history_bytes = _bound_parquet_bytes(
            history.parquet_bytes,
            bindings=_artifact_bindings_for_fold(
                materialization_bindings,
                "NOT_APPLICABLE",
                "DYNAMIC_HISTORY_INDEX",
            ),
        )
        if state_bytes != expected_state_bytes or history_bytes != expected_history_bytes:
            raise DynamicRunnerError(
                "dynamic checkpoint bytes differ from freshly materialized state/history"
            )
        state_table = pq.read_table(pa.BufferReader(state_bytes))
        if dynamic_state_table_content_sha(state_table, policy=state.policy) != state.content_sha:
            raise DynamicRunnerError("reused dynamic state semantic content differs")
        try:
            load_historical_dynamic_index(
                history_bytes,
                descriptor=stored["historyDescriptor"],
            )
        except DynamicStateIntegrityError as exc:
            raise DynamicRunnerError(str(exc)) from exc
        return DynamicMaterializationCheckpoint(
            checkpoint_id=checkpoint_id,
            code_revision=stored["codeRevision"],
            materialization_bindings=dict(materialization_bindings),
            state_artifact=dict(references[0]),
            history_artifact=dict(references[1]),
            history_descriptor=dict(stored["historyDescriptor"]),
            state_table=state_table,
        )

    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    materialization_bindings = _base_artifact_bindings(
        created_at=created_at,
        code_revision=code_revision,
        dynamic_source_partition_ids=state.source_partition_ids,
        phase3_source_partition_ids=phase3_source_partition_ids,
    )
    writer = _ArtifactWriter.create(
        root,
        base_bindings=materialization_bindings,
        protected_roots=protected_roots,
    )
    state_artifact = writer.parquet(
        "DYNAMIC_PLAYER_STATE",
        "mlb-dynamic-player-state-v1.parquet",
        state.parquet_bytes,
        temporal_fold="NOT_APPLICABLE",
    )
    history_artifact = writer.parquet(
        "DYNAMIC_HISTORY_INDEX",
        "dynamic-history-index.parquet",
        history.parquet_bytes,
        temporal_fold="NOT_APPLICABLE",
    )
    state_table = pq.read_table(
        pa.BufferReader(_artifact_path(root, state_artifact).read_bytes())
    )
    if dynamic_state_table_content_sha(state_table, policy=state.policy) != state.content_sha:
        raise DynamicRunnerError("new dynamic state semantic content differs")
    history_descriptor = historical_dynamic_index_descriptor(history, history_artifact)
    try:
        load_historical_dynamic_index(
            _artifact_path(root, history_artifact).read_bytes(),
            descriptor=history_descriptor,
        )
    except DynamicStateIntegrityError as exc:
        raise DynamicRunnerError(str(exc)) from exc
    payload = {
        "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
        "checkpointId": checkpoint_id,
        "checkpointCore": core,
        "codeRevision": code_revision,
        "materializationBindings": materialization_bindings,
        "stateArtifact": state_artifact,
        "historyArtifact": history_artifact,
        "historyDescriptor": history_descriptor,
    }
    _atomic_write(pointer, canonical_json_bytes(payload))
    return DynamicMaterializationCheckpoint(
        checkpoint_id=checkpoint_id,
        code_revision=code_revision,
        materialization_bindings=materialization_bindings,
        state_artifact=state_artifact,
        history_artifact=history_artifact,
        history_descriptor=history_descriptor,
        state_table=state_table,
    )


def _prediction_parquet(
    experiment: DynamicTrainingExperiment,
    evidence: DynamicEvaluationEvidence,
    *,
    season: int,
    state_content_sha: str,
) -> bytes:
    fold = experiment.folds[season]
    selected_id = experiment.selected_candidate_id
    columns: dict[str, Any] = {
        "plate_appearance_id": fold.plate_appearance_ids.tolist(),
        "game_id": fold.game_ids.tolist(),
        "outcome": fold.labels.tolist(),
    }
    for candidate_id in ("D0", "D1", "D2", "D3", "D4"):
        matrix = fold.probabilities[candidate_id]
        for index, class_name in enumerate(PA_CLASS_ORDER):
            columns[f"raw_{candidate_id}_{class_name}"] = matrix[:, index]
    for prefix, matrix in (
        (f"scaled_{selected_id}", evidence.scaled_probabilities[season]),
        (f"final_{selected_id}", evidence.final_probabilities[season]),
    ):
        for index, class_name in enumerate(PA_CLASS_ORDER):
            columns[f"{prefix}_{class_name}"] = matrix[:, index]
    table = pa.Table.from_pydict(columns)
    metadata = {
        b"artifactSchemaVersion": b"MLB_DYNAMIC_PLAYER_STATE_FOLD_PREDICTIONS_V1",
        b"contractName": CONTRACT_NAME.encode("utf-8"),
        b"contractSha": dynamic_state_contract_sha().encode("ascii"),
        b"stateContentSha": state_content_sha.encode("ascii"),
        b"foldId": fold.fold_id.encode("utf-8"),
        b"validationSeason": str(season).encode("ascii"),
        b"rowCount": str(fold.labels.size).encode("ascii"),
        b"selectedCandidateId": selected_id.encode("utf-8"),
        b"classOrder": canonical_json_bytes(list(PA_CLASS_ORDER)),
        b"rawAndScaledPreserved": b"true",
    }
    sink = pa.BufferOutputStream()
    pq.write_table(
        table.replace_schema_metadata(metadata),
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


def _public_candidates(experiment: DynamicTrainingExperiment) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in experiment.candidates:
        config = copy.deepcopy(item["config"])
        result.append(
            {
                "candidateId": item["candidateId"],
                "candidateType": item["candidateType"],
                "displayName": item["displayName"],
                "ordinal": item["ordinal"],
                "config": config,
                "configSha": item.get("configSha")
                or sha256_bytes(canonical_json_bytes(config)),
                "runtimeSeconds": item["runtimeSeconds"],
                "convergence": copy.deepcopy(item["convergence"]),
                "foldMetrics": copy.deepcopy(item["foldMetrics"]),
                "eligible": True,
                "rejectionReasons": [],
            }
        )
    return result


def assemble_dynamic_player_state_component(
    *,
    state: BuiltDynamicPlayerState,
    history: BuiltHistoricalDynamicIndex,
    checkpoint: DynamicMaterializationCheckpoint,
    phase3: Phase3RuntimeInputs,
    experiment: DynamicTrainingExperiment,
    evidence: DynamicEvaluationEvidence,
    runtime_root: Path,
    code_revision: str,
    protected_roots: Sequence[Path] = (),
) -> dict[str, Any]:
    run_created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_bindings = _base_artifact_bindings(
        created_at=run_created_at,
        code_revision=code_revision,
        dynamic_source_partition_ids=state.source_partition_ids,
        phase3_source_partition_ids=phase3.source_partition_ids,
    )
    writer = _ArtifactWriter.create(
        runtime_root,
        base_bindings=run_bindings,
        protected_roots=protected_roots,
    )
    artifacts = list(checkpoint.artifacts)
    artifacts.extend(
        [
            writer.json(
                "DYNAMIC_CONTRACT",
                "dynamic-contract.json",
                {"contractSha": state.contract_sha, "contract": state.contract},
                temporal_fold="NOT_APPLICABLE",
            ),
            writer.json(
                "DYNAMIC_STATE_SCHEMA",
                "dynamic-state-schema.json",
                {"schemaSha": state.schema_sha, "schema": state.schema_spec},
                temporal_fold="NOT_APPLICABLE",
            ),
            writer.json(
                "DYNAMIC_HISTORY_SCHEMA",
                "dynamic-history-schema.json",
                {
                    "schemaSha": history.schema_sha,
                    "schema": history.schema_spec,
                },
                temporal_fold="NOT_APPLICABLE",
            ),
            writer.json(
                "DYNAMIC_TUNING",
                "dynamic-tuning.json",
                state.tuning.public(),
                temporal_fold="INNER_2023",
            ),
            writer.json(
                "DYNAMIC_STATE_POSTERIOR_PREDICTIVE",
                "dynamic-state-posterior-predictive.json",
                state.posterior_predictive,
                temporal_fold="MULTI_FOLD",
            ),
        ]
    )
    public_candidates = _public_candidates(experiment)
    by_id = {row["candidateId"]: row for row in public_candidates}
    for (season, candidate_id), model in sorted(experiment.models.items()):
        model_state = dict(model.state())
        preprocessor = model_state.pop("preprocessor")
        common = {
            "candidateId": candidate_id,
            "validationSeason": season,
            "stateContentSha": state.content_sha,
            "featureContentSha": PHASE3_FEATURE_CONTENT_SHA,
        }
        artifacts.append(
            writer.json(
                "DYNAMIC_MODEL_STATE",
                f"model-{candidate_id}-validate-{season}.json",
                {**common, "model": model_state},
                temporal_fold=f"VALIDATE_{season}",
            )
        )
        artifacts.append(
            writer.json(
                "DYNAMIC_PREPROCESSOR_STATE",
                f"preprocessor-{candidate_id}-validate-{season}.json",
                {**common, "preprocessor": preprocessor},
                temporal_fold=f"VALIDATE_{season}",
            )
        )
    for season in (2024, 2025):
        artifacts.append(
            writer.parquet(
                f"DYNAMIC_FOLD_{season}_PREDICTIONS",
                f"dynamic-fold-{season}-predictions.parquet",
                _prediction_parquet(
                    experiment,
                    evidence,
                    season=season,
                    state_content_sha=state.content_sha,
                ),
                temporal_fold=f"VALIDATE_{season}",
            )
        )
    logistic_tuning = {
        row["candidateId"]: copy.deepcopy(row.get("inner2023Tuning", []))
        for row in experiment.candidates
        if row["candidateId"] != "D0"
    }
    artifacts.extend(
        [
            writer.json(
                "DYNAMIC_EXPERIMENT_METRICS",
                "dynamic-experiment-metrics.json",
                {
                    "schemaVersion": DYNAMIC_TRAINING_SCHEMA_VERSION,
                    "candidates": public_candidates,
                    "selectedCandidateId": experiment.selected_candidate_id,
                    "inner2023Split": experiment.split_evidence,
                    "inner2023LogisticTuning": logistic_tuning,
                },
                temporal_fold="MULTI_FOLD",
            ),
            writer.json(
                "DYNAMIC_CALIBRATION",
                "dynamic-calibration.json",
                evidence.calibration,
                temporal_fold="MULTI_FOLD",
            ),
            writer.json(
                "DYNAMIC_BOOTSTRAP",
                "dynamic-bootstrap.json",
                {"comparisons": evidence.bootstrap},
                temporal_fold="MULTI_FOLD",
            ),
            writer.json(
                "DYNAMIC_COVERAGE",
                "dynamic-coverage.json",
                evidence.coverage,
                temporal_fold="MULTI_FOLD",
            ),
            writer.json(
                "DYNAMIC_LINEAGE",
                "dynamic-lineage.json",
                {
                    "dataset": state.contract["authorityBindings"]["dataset"],
                    "identityBridge": state.contract["authorityBindings"]["identityBridge"],
                    "phase3": state.contract["authorityBindings"]["phase3"],
                    "dynamicSourcePartitionIds": list(state.source_partition_ids),
                    "phase3SourcePartitionIds": list(phase3.source_partition_ids),
                    "stateContentSha": state.content_sha,
                    "historyContentSha": history.content_sha,
                    "identityFailures": {
                        "unresolved": 0,
                        "ambiguous": 0,
                        "multiplyMapped": 0,
                    },
                },
                temporal_fold="MULTI_FOLD",
            ),
            writer.json(
                "DYNAMIC_FINAL_CHECKPOINT",
                "dynamic-final-checkpoint.json",
                {
                    "status": "COMPLETE",
                    "checkpointId": checkpoint.checkpoint_id,
                    "selectedCandidateId": experiment.selected_candidate_id,
                    "calibrationRetained": evidence.calibration["retainedAfter2025Gate"],
                    "decision": copy.deepcopy(evidence.decision),
                    "codeRevision": code_revision,
                },
                temporal_fold="MULTI_FOLD",
            ),
        ]
    )
    state_artifact = checkpoint.state_artifact
    state_descriptor = {
        "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_ARTIFACT_DESCRIPTOR_V1",
        "contractName": CONTRACT_NAME,
        "contractSha": state.contract_sha,
        "schemaSha": state.schema_sha,
        "contentSha": state.content_sha,
        "artifactId": state_artifact["artifactId"],
        "artifactSha": state_artifact["sha256"],
        "artifactBytes": state_artifact["byteCount"],
        "logicalUri": state_artifact["logicalUri"],
        "mediaType": state_artifact["mediaType"],
        "rowCount": state.row_count,
        "seasonRows": {str(key): value for key, value in state.season_rows.items()},
        "sourcePartitionIds": list(state.source_partition_ids),
        "selectedPolicy": state.policy.public(),
        "stateKinds": ["A_PRESEASON", "B_CUMULATIVE", "C_RECENCY"],
    }
    descriptor = {
        "schemaVersion": DESCRIPTOR_SCHEMA_VERSION,
        "semanticVersion": SEMANTIC_VERSION,
        "contractSha": state.contract_sha,
        "stateSchemaSha": state.schema_sha,
        "historySchemaSha": dynamic_history_index_schema_sha(),
        "classOrder": list(PA_CLASS_ORDER),
        "referenceClass": "OTHER_REACH",
        "selectedPolicy": state.policy.public(),
        "tuning": {
            "statePolicy": state.tuning.public(),
            "logisticInner2023Split": experiment.split_evidence,
            "logisticByCandidate": logistic_tuning,
        },
        "authorityBindings": copy.deepcopy(state.contract["authorityBindings"]),
        "source": {
            "family": "plate_appearance",
            "seasons": [2021, 2022, 2023, 2024, 2025],
            "partitionIds": list(state.source_partition_ids),
            "rowCount": state.source_row_count,
            "resolvedReferenceCount": state.resolved_reference_count,
            "finalAvailabilityField": "final_available_date",
        },
        "phase3": {
            "runId": PHASE3_RUN_ID,
            "runSha": PHASE3_RUN_SHA,
            "featureViewId": PHASE3_FEATURE_VIEW_ID,
            "featureContentSha": PHASE3_FEATURE_CONTENT_SHA,
            "featureArtifact": phase3.feature_artifact,
            "featureSourcePartitionIds": list(phase3.source_partition_ids),
            "d0PredictionArtifacts": {
                str(season): phase3.prediction_artifacts[season]
                for season in (2024, 2025)
            },
            "d0Candidate": "C4_RAW",
        },
        "dynamicState": state_descriptor,
        "historyIndex": checkpoint.history_descriptor,
        "temporalPolicy": copy.deepcopy(state.contract["temporalPolicy"]),
        "rowIdentityPolicy": copy.deepcopy(
            state.contract["representation"]["rowIdentityPolicy"]
        ),
        "runtime": {
            "checkpointId": checkpoint.checkpoint_id,
            "runCreatedAt": run_created_at,
            "materializationCodeRevision": checkpoint.code_revision,
            "currentCodeRevision": code_revision,
            "crossCodeRevisionImmutableReuseAllowed": True,
            "reuseRequiresExactFreshlyRebuiltBytes": True,
            "maxModelFitSeconds": 90 * 60,
            "maxOverallSeconds": MAX_OVERALL_SECONDS,
            "heartbeatSeconds": RUNNER_HEARTBEAT_SECONDS,
        },
    }
    folds = [
        {
            "foldId": experiment.folds[season].fold_id,
            "status": "COMPLETE",
            "trainingSeasons": [2023] if season == 2024 else [2023, 2024],
            "validationSeason": season,
            "trainingRows": (
                int(np.count_nonzero(experiment.arrays.training.seasons == 2023))
                if season == 2024
                else int(np.count_nonzero(experiment.arrays.training.seasons <= 2024))
            ),
            "validationRows": int(experiment.folds[season].labels.size),
            "candidateIds": ["D0", "D1", "D2", "D3", "D4"],
            "d0SourceArtifactId": phase3.prediction_artifacts[season]["artifactId"],
            "selectionUse": "DYNAMIC_SELECTION" if season == 2024 else "FINAL_EVALUATION_ONLY",
        }
        for season in (2024, 2025)
    ]
    selected = {
        "candidateId": experiment.selected_candidate_id,
        "selectionMetric": "RAW_2024_LOG_LOSS_THEN_BRIER_THEN_ORDINAL",
        "selectionSeason": 2024,
        "probabilityVariant": "RAW",
        "rationale": experiment.selected_rationale,
    }
    metrics = {
        "schemaVersion": DYNAMIC_TRAINING_SCHEMA_VERSION,
        "classOrder": list(PA_CLASS_ORDER),
        "governingProbabilityVariant": "RAW",
        "selectedCandidateId": experiment.selected_candidate_id,
        "baselineCandidateId": "D0",
        "statePosteriorPredictive": copy.deepcopy(state.posterior_predictive),
        "byCandidate": [
            {
                "candidateId": row["candidateId"],
                "foldMetrics": copy.deepcopy(row["foldMetrics"]),
            }
            for row in public_candidates
        ],
    }
    model_card_lineage = {
        "authorityBindings": copy.deepcopy(state.contract["authorityBindings"]),
        "dynamicSourcePartitionIds": list(state.source_partition_ids),
        "phase3SourcePartitionIds": list(phase3.source_partition_ids),
        "state": {
            "contentSha": state.content_sha,
            "artifact": copy.deepcopy(checkpoint.state_artifact),
        },
        "history": {
            "contentSha": history.content_sha,
            "artifact": copy.deepcopy(checkpoint.history_artifact),
            "descriptor": copy.deepcopy(checkpoint.history_descriptor),
        },
        "phase3": {
            "runId": PHASE3_RUN_ID,
            "runSha": PHASE3_RUN_SHA,
            "featureContractSha": PHASE3_FEATURE_CONTRACT_SHA,
            "featureViewId": PHASE3_FEATURE_VIEW_ID,
            "featureArtifact": copy.deepcopy(phase3.feature_artifact),
            "predictionArtifacts": {
                str(season): copy.deepcopy(phase3.prediction_artifacts[season])
                for season in (2024, 2025)
            },
        },
    }
    model_card = {
        "schemaVersion": "MLB_DYNAMIC_PLAYER_STATE_MODEL_CARD_V1",
        "contract": {
            "contractName": CONTRACT_NAME,
            "contractSha": state.contract_sha,
            "researchOnly": True,
            "deploymentAuthorized": False,
        },
        "descriptor": copy.deepcopy(descriptor),
        "selected": copy.deepcopy(selected),
        "folds": copy.deepcopy(folds),
        "candidates": copy.deepcopy(public_candidates),
        "metrics": copy.deepcopy(metrics),
        "calibration": copy.deepcopy(evidence.calibration),
        "bootstrap": copy.deepcopy(evidence.bootstrap),
        "coverage": copy.deepcopy(evidence.coverage),
        "decision": copy.deepcopy(evidence.decision),
        "lineage": model_card_lineage,
        "artifactInventoryExcludingThisCard": copy.deepcopy(artifacts),
        "selfReferenceOmittedToAvoidCircularDigest": True,
        "limitations": [
            "Retrospective research evidence does not authorize deployment.",
            "Same-date plate appearances, including doubleheaders, are excluded from player state.",
            "D0 is the immutable Phase 3 raw C4 baseline and is never refit or relabelled.",
        ],
    }
    artifacts.append(
        writer.json(
            "DYNAMIC_MODEL_CARD",
            "dynamic-model-card.json",
            model_card,
            temporal_fold="MULTI_FOLD",
        )
    )
    artifact_ids = sorted(row["artifactId"] for row in artifacts)
    component_without_id = {
        "componentType": "DYNAMIC_PLAYER_STATE",
        "contractName": CONTRACT_NAME,
        "contractSha": state.contract_sha,
        "descriptor": descriptor,
        "candidates": public_candidates,
        "selected": selected,
        "folds": folds,
        "metrics": metrics,
        "calibration": evidence.calibration,
        "bootstrap": evidence.bootstrap,
        "coverage": evidence.coverage,
        "decision": evidence.decision,
        "artifactIds": artifact_ids,
    }
    component = {
        "componentId": (
            "sports-phase4-component:dynamic-player-state:sha256:"
            + sha256_bytes(canonical_json_bytes(component_without_id))
        ),
        **component_without_id,
    }
    for artifact in artifacts:
        verify_dynamic_artifact_body(writer.runtime_root, artifact)
    validate_dynamic_component_evidence(component, artifact_references=artifacts)
    return {"component": component, "artifacts": artifacts}


def run_mlb_dynamic_player_state(
    *,
    project_id: str,
    parent: ValidatedPackage,
    identity_bridge: ValidatedIdentityBridge,
    runtime_root: Path,
    code_revision: str,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    progress: Any | None = None,
) -> dict[str, Any]:
    if project_id != PROJECT_ID:
        raise DynamicRunnerError("governed project anchor differs")
    if bootstrap_resamples != BOOTSTRAP_RESAMPLES or bootstrap_seed != BOOTSTRAP_SEED:
        raise DynamicRunnerError("governed dynamic evaluation requires the frozen bootstrap policy")
    if (
        parent.manifest.get("manifest_sha256")
        != dynamic_state_contract_payload()["authorityBindings"]["dataset"]["manifestSha"]
        or parent.partition_authority_sha != PARTITION_AUTHORITY_SHA
        or identity_bridge.manifest.get("bridge_manifest_sha256") != BRIDGE_MANIFEST_SHA
    ):
        raise DynamicRunnerError("validated source authority differs from the dynamic contract")
    protected = (parent.package_root, identity_bridge.package_root)
    root = _validated_runtime_root(runtime_root, protected)
    with _OverallHeartbeat(progress) as deadline:
        _emit(progress, "LOADING_EXACT_PHASE3_RUNTIME_INPUTS", {"errors": 0})
        phase3 = load_phase3_runtime_inputs(root)
        deadline.check()
        _emit(
            progress,
            "BUILDING_DYNAMIC_PLAYER_STATE_AND_HISTORY_INDEX",
            {"rowsTotal": EXPECTED_TOTAL_ROWS, "errors": 0},
        )
        state, history = build_mlb_dynamic_player_state_bundle_v1(
            parent,
            identity_bridge,
            phase3.feature_table,
            code_revision=code_revision,
            progress=progress,
        )
        deadline.check()
        _emit(
            progress,
            "PERSISTING_DYNAMIC_MATERIALIZATION_CHECKPOINT",
            {"rowsProcessed": state.row_count, "errors": 0},
        )
        checkpoint = persist_dynamic_materialization_checkpoint(
            state,
            history,
            runtime_root=root,
            code_revision=code_revision,
            phase3_source_partition_ids=phase3.source_partition_ids,
            protected_roots=protected,
        )
        deadline.check()
        _emit(
            progress,
            "RUNNING_DYNAMIC_D0_D4_EXPERIMENT",
            {"rowsProcessed": EXPECTED_TOTAL_ROWS, "errors": 0},
        )
        experiment = run_dynamic_training_experiment(
            phase3.feature_table,
            checkpoint.state_table,
            policy=state.policy,
            dynamic_content_sha=state.content_sha,
            d0_folds=phase3.d0_folds,
            expected_d0_artifact_shas={
                2024: PHASE3_FOLD_2024_PREDICTION_SHA,
                2025: PHASE3_FOLD_2025_PREDICTION_SHA,
            },
            progress=progress,
        )
        deadline.check()
        evidence = evaluate_dynamic_experiment(
            experiment,
            bootstrap_resamples=bootstrap_resamples,
            bootstrap_seed=bootstrap_seed,
            progress=progress,
        )
        deadline.check()
        result = assemble_dynamic_player_state_component(
            state=state,
            history=history,
            checkpoint=checkpoint,
            phase3=phase3,
            experiment=experiment,
            evidence=evidence,
            runtime_root=root,
            code_revision=code_revision,
            protected_roots=protected,
        )
        deadline.check()
        _emit(
            progress,
            "DYNAMIC_PLAYER_STATE_COMPLETE",
            {
                "componentId": result["component"]["componentId"],
                "selectedCandidateId": experiment.selected_candidate_id,
                "decision": evidence.decision["decision"],
                "errors": 0,
            },
        )
        return result


__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "DynamicMaterializationCheckpoint",
    "DynamicRunnerError",
    "MAX_OVERALL_SECONDS",
    "Phase3RuntimeInputs",
    "RUNTIME_NAMESPACE",
    "RUNTIME_URI_PREFIX",
    "RUNNER_SCHEMA_VERSION",
    "assemble_dynamic_player_state_component",
    "load_phase3_runtime_inputs",
    "persist_dynamic_materialization_checkpoint",
    "run_mlb_dynamic_player_state",
    "verify_dynamic_artifact_body",
]
