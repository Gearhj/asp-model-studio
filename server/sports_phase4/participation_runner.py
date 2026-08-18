from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from server.sports_phase4.dynamic_contract import (
    PHASE3_FEATURE_CONTRACT_SHA,
    dynamic_state_contract_payload,
    validate_dynamic_component_evidence,
)
from server.sports_phase4.dynamic_runner import (
    RUNTIME_NAMESPACE as DYNAMIC_RUNTIME_NAMESPACE,
    RUNTIME_URI_PREFIX as DYNAMIC_RUNTIME_URI_PREFIX,
    verify_dynamic_artifact_body,
)
from server.sports_phase4.dynamic_state import (
    FrozenDynamicPolicy,
    dynamic_state_rows_for_keys,
    load_historical_dynamic_index,
)

from server.sports_datasets.constants import (
    MANIFEST_SHA,
    PARTITION_AUTHORITY_SHA,
    PROJECT_ID,
    REGISTRATION_ID,
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

from .participation_contract import contract_set_payload, validate_dynamic_descriptor
from .participation_features import (
    BuiltParticipationFeatureViews,
    DynamicStateSource,
    build_mlb_participation_feature_views_v1,
)
from .participation_metrics import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED
from .participation_training import (
    ComponentExperimentResult,
    ParticipationExperimentResult,
    run_participation_experiments,
)


RUNNER_SCHEMA_VERSION = "MLB_PARTICIPATION_USAGE_RUNNER_V1"
RUN_SCHEMA_VERSION = "MLB_PARTICIPATION_USAGE_RUN_V1"
RUNTIME_NAMESPACE = "mlb-participation-usage-v1"
RUNTIME_URI_PREFIX = f"asp-model-studio-runtime://sports-phase4/{RUNTIME_NAMESPACE}"
PROGRESS_HEARTBEAT_SECONDS = 30.0
COMPONENT_KEYS = frozenset(
    {
        "componentId",
        "componentType",
        "contractName",
        "contractSha",
        "descriptor",
        "candidates",
        "selected",
        "folds",
        "metrics",
        "calibration",
        "bootstrap",
        "coverage",
        "decision",
        "artifactIds",
    }
)
COMPONENT_TYPES = ("LINEUP_PROJECTION", "STARTER_DURATION", "BULLPEN_USAGE")
TARGET_ORDER_AUTHORITY: dict[str, Any] = {
    "LINEUP_PROJECTION": {
        "binaryClassOrder": ["NOT_IN_STARTING_LINEUP", "IN_STARTING_LINEUP"],
        "battingOrder": list(range(1, 10)),
        "targetFields": ["actual_starting_lineup", "actual_batting_order"],
    },
    "STARTER_DURATION": {
        "targetOrder": ["BFP", "OUTS", "REACH_15_OUTS", "REACH_18_OUTS", "REACH_21_OUTS"],
        "primaryTargetField": "stat_p_bfp",
        "secondaryTargetField": "stat_p_ipouts",
    },
    "BULLPEN_USAGE": {
        "binaryClassOrder": ["NO_RELIEF_APPEARANCE", "RELIEF_APPEARANCE"],
        "targetFields": ["actual_appearance_target", "stat_p_bfp", "stat_p_ipouts"],
    },
}
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_ARTIFACT_ID_RE = re.compile(r"sports-phase4-artifact:[a-z0-9_]+:sha256:[0-9a-f]{64}\Z")
_COMPONENT_LOCATOR_KEYS = {
    "artifactid",
    "artifactids",
    "artifactsha",
    "artifactbytes",
    "logicaluri",
    "uri",
}


class ParticipationRunnerError(RuntimeError):
    """Fail-closed runtime or evidence-persistence error."""


def _dynamic_artifact_path(
    runtime_root: Path,
    reference: Mapping[str, Any],
) -> Path:
    logical_uri = reference.get("logicalUri")
    if not isinstance(logical_uri, str) or not logical_uri.startswith(
        DYNAMIC_RUNTIME_URI_PREFIX + "/"
    ):
        raise ParticipationRunnerError("dynamic artifact logical URI differs")
    suffix = logical_uri[len(DYNAMIC_RUNTIME_URI_PREFIX) + 1 :]
    parsed = PurePosixPath(suffix)
    if (
        not suffix
        or "\\" in suffix
        or suffix.startswith("/")
        or parsed.is_absolute()
        or parsed.as_posix() != suffix
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ParticipationRunnerError("dynamic artifact logical URI is unsafe")
    root = raw_absolute_path(Path(runtime_root))
    namespace = root / DYNAMIC_RUNTIME_NAMESPACE
    reject_reparse_chain(namespace, label="Dynamic input namespace chain")
    candidate = namespace.joinpath(*parsed.parts)
    reject_reparse_chain(candidate, label="Dynamic input artifact chain")
    try:
        resolved_namespace = namespace.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ParticipationRunnerError("dynamic input artifact is missing") from exc
    if resolved == resolved_namespace or resolved_namespace not in resolved.parents:
        raise ParticipationRunnerError("dynamic input artifact escaped its namespace")
    metadata = resolved.stat()
    if resolved.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ParticipationRunnerError("dynamic input artifact may not be a link")
    return resolved


def dynamic_state_source_from_run(
    dynamic_run: Mapping[str, Any],
    *,
    runtime_root: Path,
) -> DynamicStateSource:
    """Bind an exact Milestone A result and its history index for on-demand states."""

    if not isinstance(dynamic_run, Mapping) or set(dynamic_run) != {"component", "artifacts"}:
        raise ParticipationRunnerError("dynamic run input shape differs")
    component = dynamic_run.get("component")
    artifacts = dynamic_run.get("artifacts")
    if not isinstance(component, Mapping) or not isinstance(artifacts, list):
        raise ParticipationRunnerError("dynamic run component/artifacts differ")
    try:
        # ``public_active()`` returns the registry-canonical componentId (the semantic hash
        # that excludes locator fields). ``validate_dynamic_component_evidence`` recomputes the
        # strict with-locators identity, so reconcile the componentId exactly as the Phase 4
        # registry itself does at registration (its ``callback_component`` reconstruction)
        # before validating. This binds the same frozen evidence without weakening the check.
        strict_core = {key: value for key, value in component.items() if key != "componentId"}
        strict_component = {
            **component,
            "componentId": "sports-phase4-component:dynamic-player-state:sha256:"
            + sha256_bytes(canonical_json_bytes(strict_core)),
        }
        validate_dynamic_component_evidence(strict_component, artifact_references=artifacts)
    except (TypeError, ValueError) as exc:
        raise ParticipationRunnerError("dynamic component evidence differs") from exc
    descriptor = component.get("descriptor")
    if not isinstance(descriptor, Mapping):
        raise ParticipationRunnerError("dynamic component descriptor differs")
    required_descriptor = {
        "authorityBindings",
        "selectedPolicy",
        "dynamicState",
        "historyIndex",
    }
    if not required_descriptor.issubset(descriptor):
        raise ParticipationRunnerError("dynamic component descriptor is incomplete")
    frozen_authorities = dynamic_state_contract_payload()["authorityBindings"]
    if descriptor["authorityBindings"] != frozen_authorities:
        raise ParticipationRunnerError("dynamic component authorities differ")
    state_descriptor = descriptor["dynamicState"]
    history_descriptor = descriptor["historyIndex"]
    selected_policy = descriptor["selectedPolicy"]
    if not all(
        isinstance(value, Mapping)
        for value in (state_descriptor, history_descriptor, selected_policy)
    ):
        raise ParticipationRunnerError("dynamic state/history/policy descriptor differs")
    if state_descriptor.get("selectedPolicy") != selected_policy:
        raise ParticipationRunnerError("dynamic state selected policy differs")
    try:
        policy = FrozenDynamicPolicy.create(
            half_life_days=selected_policy.get("halfLifeDays"),
            prior_ess=selected_policy.get("priorEffectiveSampleSize"),
        )
    except Exception as exc:
        raise ParticipationRunnerError("dynamic state selected policy is invalid") from exc
    if policy.public() != dict(selected_policy):
        raise ParticipationRunnerError("dynamic state selected policy identity differs")
    by_id = {
        item.get("artifactId"): item
        for item in artifacts
        if isinstance(item, Mapping) and isinstance(item.get("artifactId"), str)
    }
    if len(by_id) != len(artifacts):
        raise ParticipationRunnerError("dynamic artifact identities are duplicated or invalid")
    state_reference = by_id.get(state_descriptor.get("artifactId"))
    history_reference = by_id.get(history_descriptor.get("artifactId"))
    if not isinstance(state_reference, Mapping) or not isinstance(
        history_reference, Mapping
    ):
        raise ParticipationRunnerError("dynamic state/history artifact reference is missing")
    descriptor_reference_fields = {
        "artifactId": "artifactId",
        "artifactSha": "sha256",
        "artifactBytes": "byteCount",
        "logicalUri": "logicalUri",
        "mediaType": "mediaType",
    }
    for label, item_descriptor, reference in (
        ("state", state_descriptor, state_reference),
        ("history", history_descriptor, history_reference),
    ):
        if any(
            item_descriptor.get(descriptor_name) != reference.get(reference_name)
            for descriptor_name, reference_name in descriptor_reference_fields.items()
        ):
            raise ParticipationRunnerError(
                f"dynamic {label} descriptor/reference binding differs"
            )
        try:
            verify_dynamic_artifact_body(runtime_root, reference)
        except Exception as exc:
            raise ParticipationRunnerError(
                f"dynamic {label} artifact body differs"
            ) from exc
    history_bytes = _dynamic_artifact_path(runtime_root, history_reference).read_bytes()
    try:
        history = load_historical_dynamic_index(
            history_bytes,
            descriptor=history_descriptor,
        )
    except Exception as exc:
        raise ParticipationRunnerError("dynamic historical index differs") from exc
    normalized_descriptor = validate_dynamic_descriptor(
        {
            "contractName": state_descriptor.get("contractName"),
            "contractSha": state_descriptor.get("contractSha"),
            "schemaSha": state_descriptor.get("schemaSha"),
            "contentSha": state_descriptor.get("contentSha"),
            "artifactSha": state_descriptor.get("artifactSha"),
            "artifactBytes": state_descriptor.get("artifactBytes"),
            "logicalUri": state_descriptor.get("logicalUri"),
            "parent": frozen_authorities["dataset"],
            "identityBridge": frozen_authorities["identityBridge"],
            "phase3": frozen_authorities["phase3"],
            "selectedPolicy": dict(selected_policy),
            "historyIndex": dict(history_descriptor),
            "dynamicComponentId": component["componentId"],
        }
    )

    def load_rows(
        _descriptor: Mapping[str, Any],
        keys: Sequence[tuple[str, str, str]],
    ) -> pa.Table:
        try:
            return dynamic_state_rows_for_keys(history, keys, policy=policy)
        except Exception as exc:
            raise ParticipationRunnerError("on-demand dynamic-state derivation failed") from exc

    return DynamicStateSource(descriptor=normalized_descriptor, loader=load_rows)


class _Progress:
    def __init__(self, callback: Any | None) -> None:
        self.callback = callback
        self.started = time.monotonic()

    def __call__(self, stage: str, evidence: Mapping[str, Any]) -> None:
        if self.callback is None:
            return
        if not isinstance(stage, str) or not stage:
            raise ParticipationRunnerError("heartbeat stage must be non-empty")
        elapsed = time.monotonic() - self.started
        evidence_values = dict(evidence)
        rows = evidence_values.get("rowsProcessed")
        throughput = (
            float(rows) / elapsed
            if isinstance(rows, int) and not isinstance(rows, bool) and elapsed > 0.0
            else None
        )
        payload = {
            "title": "ASP MODEL STUDIO — MLB PARTICIPATION & USAGE RESEARCH",
            "milestone": "PHASE_4_MILESTONE_B",
            "schemaVersion": RUNNER_SCHEMA_VERSION,
            "stage": stage,
            "currentComponent": evidence_values.get("componentType")
            or evidence_values.get("modelStage")
            or "MULTI_COMPONENT",
            "elapsedSeconds": round(elapsed, 2),
            "seasonsProcessed": evidence_values.get("seasonsProcessed"),
            "seasonsTotal": 3,
            "partitionsProcessed": evidence_values.get("partitionsProcessed"),
            "partitionsTotal": evidence_values.get("partitionsTotal"),
            "rowsProcessed": rows,
            "rowsTotal": evidence_values.get("rowsTotal"),
            "candidate": evidence_values.get("candidateId"),
            "throughputRowsPerSecond": throughput,
            "errors": 0,
            "memoryMiB": None,
            "etaSeconds": None,
            **evidence_values,
        }
        self.callback(stage, payload)


def _with_progress_heartbeat(
    *,
    stage: str,
    callback: Any,
    reporter: _Progress,
    current_component: str,
) -> Any:
    """Keep long synchronous preparation work observable at a frozen 30-second cadence."""

    started = time.monotonic()
    with ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="participation-preparation",
    ) as executor:
        future = executor.submit(callback)
        while True:
            try:
                return future.result(timeout=PROGRESS_HEARTBEAT_SECONDS)
            except FutureTimeoutError:
                reporter(
                    f"{stage}_HEARTBEAT",
                    {
                        "componentType": current_component,
                        "stageElapsedSeconds": time.monotonic() - started,
                    },
                )


def estimate_participation_runtime(*, enable_optional_hgb: bool = False) -> dict[str, Any]:
    lower = 900 if not enable_optional_hgb else 1_200
    upper = 2_100 if not enable_optional_hgb else 2_700
    return {
        "schemaVersion": "MLB_PARTICIPATION_RUNTIME_ESTIMATE_V1",
        "estimateOnly": True,
        "estimatedSecondsLower": lower,
        "estimatedSecondsUpper": upper,
        "estimatedArtifactBytesUpper": 200_000_000,
        "assumptions": [
            "single local CPU process",
            "registered FD1 package and identity bridge already validated",
            "Milestone A history-index artifact available locally",
            "500 game-cluster bootstrap resamples",
            "optional bounded HGB " + ("enabled" if enable_optional_hgb else "disabled"),
        ],
        "liveRunStarted": False,
    }


def _validated_runtime_root(
    runtime_root: Path,
    *,
    protected_roots: Sequence[Path],
    fixture_mode: bool,
) -> Path:
    raw_root = raw_absolute_path(Path(runtime_root))
    repository_root = Path(__file__).resolve().parents[2]
    approved = raw_absolute_path(repository_root / ".runtime" / "asp-model-studio" / "sports-phase4")
    if not fixture_mode and raw_root != approved:
        raise ParticipationRunnerError(
            "live runtime_root must be the repository-owned ignored sports-phase4 root"
        )
    if fixture_mode:
        try:
            raw_root.relative_to(repository_root)
        except ValueError as exc:
            raise ParticipationRunnerError("fixture runtime_root must remain inside the repository") from exc
    reject_reparse_chain(raw_root, label="Participation runtime root chain")
    root = raw_root.resolve(strict=False)
    for protected in protected_roots:
        approved_protected = protected.resolve(strict=True)
        if root == approved_protected or approved_protected in root.parents:
            raise ParticipationRunnerError("runtime_root may not be inside a read-only authority")
    raw_root.mkdir(parents=True, exist_ok=True)
    reject_reparse_chain(raw_root, label="Participation runtime root chain")
    resolved = raw_root.resolve(strict=True)
    if not fixture_mode and resolved != approved.resolve(strict=False):
        raise ParticipationRunnerError("runtime_root resolved outside its governed boundary")
    return raw_root


def _atomic_write(destination: Path, content: bytes, *, prefix: str) -> None:
    reject_reparse_chain(destination.parent, label="Participation artifact parent chain")
    destination.parent.mkdir(parents=True, exist_ok=True)
    reject_reparse_chain(destination.parent, label="Participation artifact parent chain")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=prefix,
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
        protected_roots: Sequence[Path],
        fixture_mode: bool,
    ) -> "_ArtifactWriter":
        if not isinstance(bindings, Mapping) or not bindings:
            raise ParticipationRunnerError("artifact bindings are required")
        return cls(
            _validated_runtime_root(
                runtime_root, protected_roots=protected_roots, fixture_mode=fixture_mode
            ),
            dict(bindings),
        )

    def artifact_binding(
        self,
        artifact_type: str,
        *,
        component_type: str | None,
        temporal_fold: str,
    ) -> dict[str, Any]:
        if temporal_fold not in {"2024", "2025", "MULTI_FOLD", "NOT_APPLICABLE"}:
            raise ParticipationRunnerError("artifact temporal fold differs")
        if component_type is not None and component_type not in COMPONENT_TYPES:
            raise ParticipationRunnerError("artifact componentType differs")
        return {
            "artifactType": artifact_type,
            "componentType": component_type,
            "componentContract": (
                self.bindings["componentContracts"][component_type]
                if component_type is not None
                else None
            ),
            "temporalFold": temporal_fold,
            "targetOrder": (
                self.bindings["targetOrderAuthority"][component_type]
                if component_type is not None
                else None
            ),
        }

    def write(
        self,
        artifact_type: str,
        filename: str,
        content: bytes,
        *,
        media_type: str,
        component_type: str | None = None,
        temporal_fold: str = "NOT_APPLICABLE",
    ) -> dict[str, Any]:
        if (
            not isinstance(artifact_type, str)
            or not artifact_type
            or not isinstance(filename, str)
            or not filename
            or not isinstance(content, bytes)
            or not content
        ):
            raise ParticipationRunnerError("runtime artifact declaration is invalid")
        if media_type == "application/json":
            try:
                parsed = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ParticipationRunnerError("runtime JSON artifact is unreadable") from exc
            if (
                not isinstance(parsed, Mapping)
                or "bindings" not in parsed
                or canonical_json_bytes(parsed["bindings"])
                != canonical_json_bytes(self.bindings)
            ):
                raise ParticipationRunnerError("runtime JSON artifact bindings differ")
            expected_artifact_binding = self.artifact_binding(
                artifact_type,
                component_type=component_type,
                temporal_fold=temporal_fold,
            )
            if parsed.get("artifactBinding") != expected_artifact_binding:
                raise ParticipationRunnerError("runtime JSON per-artifact binding differs")
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
            raise ParticipationRunnerError("runtime artifact escaped its root")
        if destination.exists():
            reject_reparse_chain(destination, label="Participation artifact chain")
            if destination.is_symlink() or destination.stat().st_nlink != 1:
                raise ParticipationRunnerError("runtime artifact may not be a link")
            if destination.read_bytes() != content:
                raise ParticipationRunnerError("existing content-addressed artifact differs")
        else:
            _atomic_write(destination, content, prefix=".mlb-participation-artifact-")
        reject_reparse_chain(destination, label="Participation artifact chain")
        if destination.stat().st_nlink != 1:
            raise ParticipationRunnerError("runtime artifact may not be a hardlink")
        logical_uri = (
            f"{RUNTIME_URI_PREFIX}/objects/sha256/{digest[:2]}/{digest}/{filename}"
        )
        return {
            "artifactId": f"sports-phase4-artifact:{artifact_type.casefold()}:sha256:{digest}",
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
        *,
        component_type: str | None = None,
        temporal_fold: str = "NOT_APPLICABLE",
    ) -> dict[str, Any]:
        artifact_binding = self.artifact_binding(
            artifact_type,
            component_type=component_type,
            temporal_fold=temporal_fold,
        )
        envelope = {
            "schemaVersion": "MLB_PARTICIPATION_RUNTIME_ARTIFACT_V1",
            "artifactType": artifact_type,
            "componentType": component_type,
            "bindings": self.bindings,
            "artifactBinding": artifact_binding,
            "payload": dict(payload),
        }
        return self.write(
            artifact_type,
            filename,
            canonical_json_bytes(envelope),
            media_type="application/json",
            component_type=component_type,
            temporal_fold=temporal_fold,
        )

    def parquet(
        self,
        artifact_type: str,
        filename: str,
        content: bytes,
        *,
        component_type: str,
        temporal_fold: str,
    ) -> dict[str, Any]:
        try:
            table = pq.read_table(pa.BufferReader(content))
        except Exception as exc:
            raise ParticipationRunnerError("runtime Parquet artifact is unreadable") from exc
        metadata = dict(table.schema.metadata or {})
        if not metadata:
            raise ParticipationRunnerError("runtime Parquet artifact lacks metadata")
        artifact_binding = self.artifact_binding(
            artifact_type,
            component_type=component_type,
            temporal_fold=temporal_fold,
        )
        metadata.update(
            {
                b"artifactBindings": canonical_json_bytes(self.bindings),
                b"artifactBinding": canonical_json_bytes(artifact_binding),
                b"artifactType": artifact_type.encode("ascii"),
                b"componentType": component_type.encode("ascii"),
                b"componentContractSha": artifact_binding["componentContract"][
                    "contractSha"
                ].encode("ascii"),
                b"temporalFold": temporal_fold.encode("ascii"),
                b"createdAt": str(self.bindings["createdAt"]).encode("utf-8"),
                b"codeRevision": str(self.bindings["codeRevision"]).encode("utf-8"),
                b"sourcePartitionIds": canonical_json_bytes(
                    self.bindings["sourcePartitionIds"]
                ),
                b"targetOrderAuthority": canonical_json_bytes(
                    artifact_binding["targetOrder"]
                ),
            }
        )
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
        rebound = sink.getvalue().to_pybytes()
        rebound_metadata = pq.read_metadata(pa.BufferReader(rebound)).metadata or {}
        if (
            rebound_metadata.get(b"artifactBindings")
            != canonical_json_bytes(self.bindings)
            or rebound_metadata.get(b"artifactBinding")
            != canonical_json_bytes(artifact_binding)
        ):
            raise ParticipationRunnerError("runtime Parquet artifact bindings were not persisted")
        return self.write(
            artifact_type,
            filename,
            rebound,
            media_type="application/vnd.apache.parquet",
            component_type=component_type,
            temporal_fold=temporal_fold,
        )


def _materialize_bound_parquet(
    content: bytes,
    *,
    component_type: str,
    bindings: Mapping[str, Any],
) -> bytes:
    try:
        table = pq.read_table(pa.BufferReader(content))
    except Exception as exc:
        raise ParticipationRunnerError("feature-view Parquet is unreadable") from exc
    metadata = dict(table.schema.metadata or {})
    if metadata.get(b"component") != component_type.encode("ascii"):
        raise ParticipationRunnerError("feature-view component metadata differs")
    if metadata.get(b"contractSha") != str(bindings["contractSetSha"]).encode("ascii"):
        raise ParticipationRunnerError("feature-view contract metadata differs")
    if metadata.get(b"dynamicBinding") != canonical_json_bytes(bindings["dynamicState"]):
        raise ParticipationRunnerError("feature-view dynamic-state metadata differs")
    metadata.update(
        {
            b"componentType": component_type.encode("ascii"),
            b"artifactBindings": canonical_json_bytes(dict(bindings)),
            b"createdAt": str(bindings["createdAt"]).encode("utf-8"),
            b"codeRevision": str(bindings["codeRevision"]).encode("utf-8"),
            b"sourcePartitionIds": canonical_json_bytes(bindings["sourcePartitionIds"]),
            b"targetOrderAuthority": canonical_json_bytes(bindings["targetOrderAuthority"]),
        }
    )
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
    rebound = sink.getvalue().to_pybytes()
    rebound_metadata = pq.read_metadata(pa.BufferReader(rebound)).metadata or {}
    if rebound_metadata.get(b"artifactBindings") != canonical_json_bytes(dict(bindings)):
        raise ParticipationRunnerError("feature-view artifact binding was not persisted")
    return rebound


def _without_component_locators(value: Any) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in _COMPONENT_LOCATOR_KEYS:
                continue
            output[str(key)] = _without_component_locators(item)
        return output
    if isinstance(value, (list, tuple)):
        return [_without_component_locators(item) for item in value]
    return value


def _component_identity(experiment: ComponentExperimentResult) -> str:
    semantic = _without_component_locators({
        "componentType": experiment.component_type,
        "contractName": experiment.contract_name,
        "contractSha": experiment.contract_sha,
        "descriptor": experiment.descriptor,
        "candidates": list(experiment.candidates),
        "selected": experiment.selected,
        "folds": list(experiment.folds),
        "metrics": experiment.metrics,
        "calibration": experiment.calibration,
        "bootstrap": experiment.bootstrap,
        "coverage": experiment.coverage,
        "decision": experiment.decision,
    })
    component_type = re.sub(
        r"[^a-z0-9]+", "-", experiment.component_type.casefold()
    ).strip("-")
    return (
        f"sports-phase4-component:{component_type}:sha256:"
        f"{sha256_bytes(canonical_json_bytes(semantic))}"
    )


def _component_identity_from_wrapper(component: Mapping[str, Any]) -> str:
    semantic = _without_component_locators({
        "componentType": component["componentType"],
        "contractName": component["contractName"],
        "contractSha": component["contractSha"],
        "descriptor": component["descriptor"],
        "candidates": component["candidates"],
        "selected": component["selected"],
        "folds": component["folds"],
        "metrics": component["metrics"],
        "calibration": component["calibration"],
        "bootstrap": component["bootstrap"],
        "coverage": component["coverage"],
        "decision": component["decision"],
    })
    component_type = re.sub(
        r"[^a-z0-9]+", "-", str(component["componentType"]).casefold()
    ).strip("-")
    return (
        f"sports-phase4-component:{component_type}:sha256:"
        f"{sha256_bytes(canonical_json_bytes(semantic))}"
    )


def validate_component_shape(component: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(component, Mapping) or set(component) != COMPONENT_KEYS:
        raise ParticipationRunnerError("component wrapper keys differ from the common registry shape")
    component_type = component.get("componentType")
    if component_type not in COMPONENT_TYPES:
        raise ParticipationRunnerError("componentType differs")
    expected_contract = {
        "LINEUP_PROJECTION": "MLB_LINEUP_PROJECTION_V1",
        "STARTER_DURATION": "MLB_STARTER_DURATION_V1",
        "BULLPEN_USAGE": "MLB_BULLPEN_USAGE_V1",
    }[component_type]
    if component.get("contractName") != expected_contract:
        raise ParticipationRunnerError("component contractName differs")
    if not isinstance(component.get("contractSha"), str) or _SHA_RE.fullmatch(
        str(component["contractSha"])
    ) is None:
        raise ParticipationRunnerError("component contractSha differs")
    if component.get("componentId") != _component_identity_from_wrapper(component):
        raise ParticipationRunnerError("componentId differs")
    candidates = component.get("candidates")
    selected = component.get("selected")
    if not isinstance(candidates, list) or not candidates or not isinstance(selected, Mapping):
        raise ParticipationRunnerError("component candidates/selected differ")
    candidate_ids = [item.get("candidateId") for item in candidates if isinstance(item, Mapping)]
    if len(candidate_ids) != len(candidates) or len(set(candidate_ids)) != len(candidate_ids):
        raise ParticipationRunnerError("component candidate IDs differ")
    if selected.get("candidateId") not in candidate_ids or selected.get("selectionSeason") != 2024:
        raise ParticipationRunnerError("component selection differs")
    folds = component.get("folds")
    if not isinstance(folds, list) or [item.get("validationSeason") for item in folds] != [2024, 2025]:
        raise ParticipationRunnerError("component folds must contain only frozen 2024/2025 folds")
    descriptor = component.get("descriptor")
    if not isinstance(descriptor, Mapping) or not isinstance(descriptor.get("inner2023Tuning"), Mapping):
        raise ParticipationRunnerError("component inner-2023 tuning descriptor differs")
    artifact_ids = component.get("artifactIds")
    if (
        not isinstance(artifact_ids, list)
        or not artifact_ids
        or artifact_ids != sorted(set(artifact_ids))
        or any(not isinstance(value, str) or _ARTIFACT_ID_RE.fullmatch(value) is None for value in artifact_ids)
    ):
        raise ParticipationRunnerError("component artifactIds differ")
    for key in ("metrics", "coverage", "decision"):
        if not isinstance(component.get(key), Mapping):
            raise ParticipationRunnerError(f"component {key} must be an object")
    if component.get("calibration") is not None and not isinstance(component.get("calibration"), Mapping):
        raise ParticipationRunnerError("component calibration must be object or null")
    if component.get("bootstrap") is not None and not isinstance(component.get("bootstrap"), Mapping):
        raise ParticipationRunnerError("component bootstrap must be object or null")
    return dict(component)


def _prediction_parquet(
    view: pa.Table,
    experiment: ComponentExperimentResult,
    *,
    season: int,
    bindings: Mapping[str, Any],
    component_id: str,
) -> bytes:
    seasons = np.asarray(view["season"].combine_chunks().to_pylist(), dtype=np.int64)
    table = view.filter(pa.array(seasons == season))
    columns: dict[str, Any] = {}
    lineage_names = [
        name
        for name in (
            "candidate_row_id",
            "target_row_id",
            "game_id",
            "game_date",
            "season",
            "team_id",
            "canonical_player_uuid",
            "target_start",
            "target_batting_order",
            "target_appearance",
            "target_bfp",
            "target_outs",
        )
        if name in table.column_names
    ]
    for name in lineage_names:
        columns[name] = table[name]
    for (prediction_season, candidate_id), prediction in sorted(experiment.predictions.items()):
        if prediction_season != season:
            continue
        for name, values in sorted(prediction.items()):
            parsed = np.asarray(values, dtype=np.float64)
            if parsed.size != table.num_rows or not np.isfinite(parsed).all():
                raise ParticipationRunnerError("fold prediction values differ")
            columns[f"{candidate_id.casefold()}_{name}"] = pa.array(parsed, type=pa.float64())
    output = pa.table(columns)
    metadata = {
        b"schemaVersion": b"MLB_PARTICIPATION_FOLD_PREDICTIONS_V1",
        b"componentType": experiment.component_type.encode("ascii"),
        b"componentId": component_id.encode("ascii"),
        b"validationSeason": str(season).encode("ascii"),
        b"artifactBindings": canonical_json_bytes(dict(bindings)),
        b"createdAt": str(bindings["createdAt"]).encode("utf-8"),
        b"codeRevision": str(bindings["codeRevision"]).encode("utf-8"),
        b"sourcePartitionIds": canonical_json_bytes(bindings["sourcePartitionIds"]),
        b"targetOrderAuthority": canonical_json_bytes(bindings["targetOrderAuthority"]),
    }
    sink = pa.BufferOutputStream()
    pq.write_table(
        output.replace_schema_metadata(metadata),
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


def _write_feature_checkpoint(
    writer: _ArtifactWriter,
    views: BuiltParticipationFeatureViews,
    artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    payload = {
        "schemaVersion": "MLB_PARTICIPATION_FEATURE_CHECKPOINT_V1",
        "artifactType": "FEATURE_CHECKPOINT",
        "componentType": None,
        "bindings": writer.bindings,
        "artifactBinding": writer.artifact_binding(
            "FEATURE_CHECKPOINT",
            component_type=None,
            temporal_fold="MULTI_FOLD",
        ),
        "combinedContentSha": views.combined_content_sha,
        "componentContentShas": views.content_shas,
        "rowCounts": views.row_counts,
        "sourcePartitionIds": list(views.source_partition_ids),
        "dynamicBinding": views.dynamic_binding,
        "featureArtifactIds": [item["artifactId"] for item in artifacts],
    }
    content = canonical_json_bytes(payload)
    digest = sha256_bytes(content)
    destination = (
        writer.runtime_root
        / RUNTIME_NAMESPACE
        / "checkpoints"
        / "sha256"
        / digest[:2]
        / digest
        / "feature-checkpoint.json"
    )
    if destination.exists():
        if destination.read_bytes() != content:
            raise ParticipationRunnerError("existing content-addressed feature checkpoint differs")
    else:
        _atomic_write(destination, content, prefix=".mlb-participation-checkpoint-")
    return writer.write(
        "FEATURE_CHECKPOINT",
        "feature-checkpoint.json",
        content,
        media_type="application/json",
        temporal_fold="MULTI_FOLD",
    )


def assemble_participation_run(
    *,
    project_id: str,
    views: BuiltParticipationFeatureViews,
    experiment: ParticipationExperimentResult,
    runtime_root: Path,
    code_revision: str,
    protected_roots: Sequence[Path] = (),
    fixture_mode: bool = False,
    created_at: str | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    if project_id != PROJECT_ID:
        raise ParticipationRunnerError("project_id differs from the frozen MLB project")
    if not isinstance(code_revision, str) or not code_revision.strip():
        raise ParticipationRunnerError("code_revision must be a non-empty content-bound descriptor")
    if not isinstance(views, BuiltParticipationFeatureViews) or not isinstance(
        experiment, ParticipationExperimentResult
    ):
        raise TypeError("assembly requires built views and participation experiment evidence")
    created = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if not isinstance(created, str) or not created.endswith("Z"):
        raise ParticipationRunnerError("created_at must be canonical UTC ISO-8601")
    try:
        parsed_created = datetime.fromisoformat(created.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ParticipationRunnerError("created_at must be canonical UTC ISO-8601") from exc
    if parsed_created.tzinfo is None or parsed_created.utcoffset() != timezone.utc.utcoffset(parsed_created):
        raise ParticipationRunnerError("created_at must be canonical UTC ISO-8601")
    source_partition_ids = list(views.source_partition_ids)
    if (
        not source_partition_ids
        or any(not isinstance(value, str) or not value for value in source_partition_ids)
        or source_partition_ids != sorted(set(source_partition_ids))
    ):
        raise ParticipationRunnerError("participation sourcePartitionIds differ")
    contracts: dict[str, dict[str, str]] = {}
    for component in experiment.components:
        if component.component_type not in COMPONENT_TYPES:
            raise ParticipationRunnerError("experiment component type differs")
        if component.component_type in contracts:
            raise ParticipationRunnerError("experiment contains duplicate component types")
        contracts[component.component_type] = {
            "contractName": component.contract_name,
            "contractSha": component.contract_sha,
        }
    if tuple(sorted(contracts, key=COMPONENT_TYPES.index)) != COMPONENT_TYPES:
        raise ParticipationRunnerError("experiment component contract set differs")
    reporter = _Progress(progress)
    bindings = {
        "schemaVersion": "MLB_PARTICIPATION_ARTIFACT_BINDINGS_V1",
        "projectId": project_id,
        "createdAt": created,
        "codeRevision": code_revision,
        "parent": {
            "registrationId": REGISTRATION_ID,
            "manifestSha": MANIFEST_SHA,
            "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
        },
        "identityBridge": {
            "registrationId": BRIDGE_REGISTRATION_ID,
            "manifestSha": BRIDGE_MANIFEST_SHA,
            "aliasAuthoritySha": ALIAS_AUTHORITY_SHA,
            "dimensionAuthoritySha": DIMENSION_AUTHORITY_SHA,
            "joinAuditId": views.dynamic_binding.get("identityBridge", {}).get("joinAuditId"),
        },
        "dynamicState": views.dynamic_binding,
        "phase3FeatureAuthority": (
            views.dynamic_binding["phase3"]
            if isinstance(views.dynamic_binding.get("phase3"), Mapping)
            else {
                "status": "MISSING_FIXTURE_ONLY",
                "featureContractSha": PHASE3_FEATURE_CONTRACT_SHA,
            }
        ),
        "sourcePartitionIds": source_partition_ids,
        "temporalPolicy": {
            "sourceFinalAvailableDate": "STRICTLY_BEFORE_TARGET_GAME_DATE",
            "sameDateEvidenceExcluded": True,
            "doubleheaderSameDateEvidenceExcluded": True,
            "innerTuningSeason": 2023,
            "selectionSeason": 2024,
            "finalEvaluationSeason": 2025,
        },
        "componentContracts": contracts,
        "targetOrderAuthority": TARGET_ORDER_AUTHORITY,
        "featureCombinedContentSha": views.combined_content_sha,
        "contractSetSha": views.contract_sha,
    }
    writer = _ArtifactWriter.create(
        runtime_root,
        bindings=bindings,
        protected_roots=protected_roots,
        fixture_mode=fixture_mode,
    )
    artifacts: list[dict[str, Any]] = []
    feature_artifacts: dict[str, dict[str, Any]] = {}
    for component, content in views.parquet_bytes.items():
        component_type = {
            "lineup": "LINEUP_PROJECTION",
            "starter": "STARTER_DURATION",
            "bullpen": "BULLPEN_USAGE",
        }[component]
        artifact = writer.parquet(
            f"{component_type}_FEATURE_VIEW",
            f"{component}-feature-view.parquet",
            _materialize_bound_parquet(
                content,
                component_type=component_type,
                bindings=bindings,
            ),
            component_type=component_type,
            temporal_fold="MULTI_FOLD",
        )
        artifacts.append(artifact)
        feature_artifacts[component_type] = artifact
    shared_artifacts = [
        writer.json(
            "PARTICIPATION_CONTRACT_SET",
            "participation-contract-set.json",
            {"contractSet": contract_set_payload(), "contractSetSha": views.contract_sha},
            temporal_fold="NOT_APPLICABLE",
        ),
        writer.json(
            "DYNAMIC_STATE_BINDING",
            "dynamic-state-binding.json",
            views.dynamic_binding,
            temporal_fold="MULTI_FOLD",
        ),
        writer.json(
            "PARTICIPATION_COVERAGE",
            "participation-coverage.json",
            {key: list(value) for key, value in views.coverage.items()},
            temporal_fold="MULTI_FOLD",
        ),
    ]
    artifacts.extend(shared_artifacts)
    feature_checkpoint = _write_feature_checkpoint(
        writer, views, [*feature_artifacts.values(), *shared_artifacts]
    )
    artifacts.append(feature_checkpoint)
    reporter("FEATURE_CHECKPOINT_COMPLETE", {"artifactId": feature_checkpoint["artifactId"]})

    component_wrappers: list[dict[str, Any]] = []
    view_by_type = {
        "LINEUP_PROJECTION": views.lineup,
        "STARTER_DURATION": views.starter,
        "BULLPEN_USAGE": views.bullpen,
    }
    for component in experiment.components:
        component_id = _component_identity(component)
        component_artifacts: list[dict[str, Any]] = [
            feature_artifacts[component.component_type],
            *shared_artifacts,
            feature_checkpoint,
        ]
        for (season, candidate_id), state in sorted(component.model_states.items()):
            component_artifacts.append(
                writer.json(
                    "MODEL_STATE",
                    f"{component.component_type.casefold()}-{candidate_id}-validate-{season}.json",
                    {
                        "componentId": component_id,
                        "candidateId": candidate_id,
                        "validationSeason": season,
                        "model": state,
                    },
                    component_type=component.component_type,
                    temporal_fold=str(season),
                )
            )
        for season in (2024, 2025):
            component_artifacts.append(
                writer.parquet(
                    f"{component.component_type}_FOLD_{season}_PREDICTIONS",
                    f"{component.component_type.casefold()}-fold-{season}-predictions.parquet",
                    _prediction_parquet(
                        view_by_type[component.component_type],
                        component,
                        season=season,
                        bindings=bindings,
                        component_id=component_id,
                    ),
                    component_type=component.component_type,
                    temporal_fold=str(season),
                )
            )
        component_artifacts.extend(
            [
                writer.json(
                    "EXPERIMENT_EVIDENCE",
                    f"{component.component_type.casefold()}-experiment.json",
                    {
                        "componentId": component_id,
                        "descriptor": component.descriptor,
                        "candidates": list(component.candidates),
                        "selected": component.selected,
                        "folds": list(component.folds),
                        "metrics": component.metrics,
                    },
                    component_type=component.component_type,
                    temporal_fold="MULTI_FOLD",
                ),
                writer.json(
                    "CANDIDATE_POOL_EVIDENCE",
                    f"{component.component_type.casefold()}-candidate-pool.json",
                    {
                        "componentId": component_id,
                        "featureViewArtifactId": feature_artifacts[
                            component.component_type
                        ]["artifactId"],
                        "featureViewContentSha": component.descriptor[
                            "featureViewContentSha"
                        ],
                        "coverage": component.coverage,
                    },
                    component_type=component.component_type,
                    temporal_fold="MULTI_FOLD",
                ),
                writer.json(
                    "METRICS_EVIDENCE",
                    f"{component.component_type.casefold()}-metrics.json",
                    {
                        "componentId": component_id,
                        "selected": component.selected,
                        "folds": list(component.folds),
                        "metrics": component.metrics,
                    },
                    component_type=component.component_type,
                    temporal_fold="MULTI_FOLD",
                ),
                writer.json(
                    "CALIBRATION_EVIDENCE",
                    f"{component.component_type.casefold()}-calibration.json",
                    {"componentId": component_id, "calibration": component.calibration},
                    component_type=component.component_type,
                    temporal_fold="MULTI_FOLD",
                ),
                writer.json(
                    "LINEAGE_EVIDENCE",
                    f"{component.component_type.casefold()}-lineage.json",
                    {
                        "componentId": component_id,
                        "dataset": bindings["parent"],
                        "identityBridge": bindings["identityBridge"],
                        "phase3": bindings["phase3FeatureAuthority"],
                        "dynamicState": views.dynamic_binding,
                        "sourcePartitionIds": source_partition_ids,
                        "featureCombinedContentSha": views.combined_content_sha,
                        "featureComponentContentSha": component.descriptor[
                            "featureViewContentSha"
                        ],
                    },
                    component_type=component.component_type,
                    temporal_fold="MULTI_FOLD",
                ),
                writer.json(
                    "DECISION_EVIDENCE",
                    f"{component.component_type.casefold()}-decision.json",
                    {"componentId": component_id, "decision": component.decision},
                    component_type=component.component_type,
                    temporal_fold="MULTI_FOLD",
                ),
                writer.json(
                    "BOOTSTRAP_EVIDENCE",
                    f"{component.component_type.casefold()}-bootstrap.json",
                    {"componentId": component_id, "bootstrap": component.bootstrap},
                    component_type=component.component_type,
                    temporal_fold="MULTI_FOLD",
                ),
                writer.json(
                    "COMPONENT_CARD",
                    f"{component.component_type.casefold()}-component-card.json",
                    {
                        "componentId": component_id,
                        "componentType": component.component_type,
                        "contractName": component.contract_name,
                        "contractSha": component.contract_sha,
                        "selected": component.selected,
                        "coverage": component.coverage,
                        "decision": component.decision,
                    },
                    component_type=component.component_type,
                    temporal_fold="MULTI_FOLD",
                ),
            ]
        )
        for artifact in component_artifacts:
            if artifact not in artifacts:
                artifacts.append(artifact)
        wrapper = {
            "componentId": component_id,
            "componentType": component.component_type,
            "contractName": component.contract_name,
            "contractSha": component.contract_sha,
            "descriptor": component.descriptor,
            "candidates": [dict(item) for item in component.candidates],
            "selected": dict(component.selected),
            "folds": [dict(item) for item in component.folds],
            "metrics": dict(component.metrics),
            "calibration": dict(component.calibration) if component.calibration is not None else None,
            "bootstrap": dict(component.bootstrap) if component.bootstrap is not None else None,
            "coverage": dict(component.coverage),
            "decision": dict(component.decision),
            "artifactIds": sorted({item["artifactId"] for item in component_artifacts}),
        }
        component_wrappers.append(validate_component_shape(wrapper))
        reporter(
            "COMPONENT_ARTIFACTS_COMPLETE",
            {
                "componentType": component.component_type,
                "selectedCandidateId": component.selected["candidateId"],
                "artifactCount": len(component_artifacts),
            },
        )
    component_wrappers.sort(key=lambda item: COMPONENT_TYPES.index(item["componentType"]))
    run_core = {
        "schemaVersion": RUN_SCHEMA_VERSION,
        "projectId": project_id,
        "createdAt": created,
        "codeRevision": code_revision,
        "parent": bindings["parent"],
        "identityBridge": bindings["identityBridge"],
        "dynamicState": views.dynamic_binding,
        "featureViews": {
            "combinedContentSha": views.combined_content_sha,
            "componentContentShas": views.content_shas,
            "rowCounts": views.row_counts,
            "sourcePartitionIds": list(views.source_partition_ids),
            "checkpointArtifactId": feature_checkpoint["artifactId"],
        },
        "components": component_wrappers,
        "runtimeEstimate": estimate_participation_runtime(
            enable_optional_hgb=any(
                candidate.get("candidateId") in {"L2", "S3", "B2"}
                and candidate.get("eligible") is True
                for component in component_wrappers
                for candidate in component["candidates"]
            )
        ),
    }
    run_id_sha = sha256_bytes(canonical_json_bytes(_without_component_locators(run_core)))
    run_id = f"sports-participation-usage-run:sha256:{run_id_sha}"
    final_checkpoint = writer.json(
        "FINAL_CHECKPOINT",
        "final-checkpoint.json",
        {
            "status": "COMPLETE",
            "runId": run_id,
            "componentIds": [item["componentId"] for item in component_wrappers],
            "selectedCandidates": {
                item["componentType"]: item["selected"]["candidateId"]
                for item in component_wrappers
            },
            "decisions": {
                item["componentType"]: item["decision"]["decision"]
                for item in component_wrappers
            },
        },
        temporal_fold="MULTI_FOLD",
    )
    artifacts.append(final_checkpoint)
    for component in component_wrappers:
        component["artifactIds"] = sorted(
            {*component["artifactIds"], final_checkpoint["artifactId"]}
        )
        validate_component_shape(component)
    artifacts.sort(key=lambda item: item["artifactId"])
    payload = {
        **run_core,
        "runId": run_id,
        "runSha": "0" * 64,
        "artifacts": artifacts,
        "finalCheckpointArtifactId": final_checkpoint["artifactId"],
    }
    semantic = dict(payload)
    semantic.pop("runSha")
    payload["runSha"] = sha256_bytes(canonical_json_bytes(semantic))
    reporter(
        "PARTICIPATION_USAGE_RUN_COMPLETE",
        {
            "runId": run_id,
            "componentCount": 3,
            "artifactCount": len(artifacts),
        },
    )
    return payload


def run_mlb_participation_usage(
    *,
    project_id: str,
    parent: ValidatedPackage,
    identity_bridge: ValidatedIdentityBridge,
    dynamic_state: DynamicStateSource,
    runtime_root: Path,
    code_revision: str,
    enable_optional_hgb: bool = False,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    progress: Any | None = None,
) -> dict[str, Any]:
    """Execute live Milestone B from validated authorities; this function performs no registration."""

    reporter = _Progress(progress)
    reporter("BUILDING_PARTICIPATION_FEATURE_VIEWS", {})
    views = _with_progress_heartbeat(
        stage="BUILDING_PARTICIPATION_FEATURE_VIEWS",
        current_component="MULTI_COMPONENT",
        reporter=reporter,
        callback=lambda: build_mlb_participation_feature_views_v1(
            parent,
            identity_bridge,
            dynamic_state=dynamic_state,
            progress=reporter,
        ),
    )
    reporter("RUNNING_PARTICIPATION_EXPERIMENTS", {"rowCounts": views.row_counts})
    experiment = run_participation_experiments(
        views,
        enable_optional_hgb=enable_optional_hgb,
        bootstrap_resamples=bootstrap_resamples,
        fixture_mode=False,
        progress=reporter,
    )
    return assemble_participation_run(
        project_id=project_id,
        views=views,
        experiment=experiment,
        runtime_root=runtime_root,
        code_revision=code_revision,
        protected_roots=(parent.package_root, identity_bridge.package_root),
        fixture_mode=False,
        progress=progress,
    )


__all__ = [
    "COMPONENT_KEYS",
    "COMPONENT_TYPES",
    "RUNNER_SCHEMA_VERSION",
    "RUN_SCHEMA_VERSION",
    "RUNTIME_NAMESPACE",
    "RUNTIME_URI_PREFIX",
    "ParticipationRunnerError",
    "assemble_participation_run",
    "dynamic_state_source_from_run",
    "estimate_participation_runtime",
    "run_mlb_participation_usage",
    "validate_component_shape",
]
