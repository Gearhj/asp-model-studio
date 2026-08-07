"""Run one exact, read-only dataset-schema-to-catalog diagnostic.

The command binds an explicitly named registered dataset version to an
explicitly named, entitlement-controlled bureau catalog version.  It reads
only the immutable Dataset Library profile schema and a caller-supplied schema
document.  It never opens dataset rows, previews, samples, or holdout data and
never persists a mapping decision.  Detailed candidates are written only
under the configured restricted-metadata root; standard output contains safe
aggregate counts and checksums.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_bureau_metadata_crosswalk import (  # noqa: E402
    _canonical_hash,
    _read_schema,
    _required_text,
    _schema_fields,
    _write_atomic,
)
from server.bureau_metadata.catalog_registry import (  # noqa: E402
    RegistryEntitlementProvider,
)
from server.bureau_metadata.catalog_store import _is_link_or_junction  # noqa: E402
from server.bureau_metadata.normalizer import (  # noqa: E402
    canonical_json_bytes,
    validate_sha256,
)
from server.bureau_metadata.operational_service import (  # noqa: E402
    OperationalCatalogService,
)
from server.bureau_metadata.restricted_storage import (  # noqa: E402
    validate_restricted_metadata_root,
)
from server.bureau_metadata.types import (  # noqa: E402
    BureauAttributeMatchCandidate,
    BureauCatalogAccessContext,
    BureauCatalogKey,
    BureauDatasetCrosswalk,
)
from server.datasets import dataset_registry  # noqa: E402
from server.persistence.service import get_persistence_service  # noqa: E402


_MAX_PROFILE_BYTES = 16 * 1024 * 1024
_MAX_IDENTITY_TEXT = 256
_PROHIBITED_PROFILE_KEYS = frozenset(
    {
        "data",
        "finalholdout",
        "final_holdout",
        "holdout",
        "observations",
        "preview",
        "records",
        "rows",
        "sample",
    }
)


class SchemaCrosswalkDiagnosticError(RuntimeError):
    """A safe exact-identity or schema-only diagnostic failure."""


class _RedactingArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise SchemaCrosswalkDiagnosticError(
            "Command arguments are incomplete or invalid."
        )


@dataclass(frozen=True, slots=True)
class SchemaCrosswalkDiagnosticSettings:
    restricted_root: Path
    catalog_version_id: str
    catalog_checksum: str
    principal_id: str
    tenant_id: str | None
    project_id: str
    dataset_id: str
    dataset_version_id: str
    schema_json: Path
    output_json: Path
    target_field: str
    target_source_fields: tuple[str, ...]
    non_catalog_fields: tuple[str, ...] = ()
    target_contract_id: str | None = None
    predictor_authorization_id: str | None = None
    created_at: str | None = None
    semantic_threshold: float = 0.55
    semantic_tie_delta: float = 0.03


def _parser() -> argparse.ArgumentParser:
    parser = _RedactingArgumentParser(description=__doc__)
    parser.add_argument("--restricted-root", type=Path, required=True)
    parser.add_argument("--catalog-version-id", required=True)
    parser.add_argument("--catalog-checksum", required=True)
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--tenant-id")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-version-id", required=True)
    parser.add_argument("--schema-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--target-field", required=True)
    parser.add_argument(
        "--target-source-field",
        action="append",
        required=True,
        help="Exact deterministic target-source column; repeat when necessary.",
    )
    parser.add_argument("--non-catalog-field", action="append", default=[])
    parser.add_argument("--target-contract-id")
    parser.add_argument("--predictor-authorization-id")
    parser.add_argument("--created-at")
    parser.add_argument("--semantic-threshold", type=float, default=0.55)
    parser.add_argument("--semantic-tie-delta", type=float, default=0.03)
    return parser


def _identifier(value: object, label: str) -> str:
    cleaned = _required_text(value, label)
    if len(cleaned) > _MAX_IDENTITY_TEXT or cleaned in {".", ".."}:
        raise SchemaCrosswalkDiagnosticError(f"{label} is invalid.")
    if "/" in cleaned or "\\" in cleaned:
        raise SchemaCrosswalkDiagnosticError(f"{label} is invalid.")
    return cleaned


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _assert_unlinked_chain(root: Path, path: Path, label: str) -> None:
    if not _is_within(path, root):
        raise SchemaCrosswalkDiagnosticError(f"{label} is outside its authority.")
    current = root
    if _is_link_or_junction(current):
        raise SchemaCrosswalkDiagnosticError(f"{label} authority is linked.")
    for component in path.relative_to(root).parts:
        current = current / component
        if current.exists() and _is_link_or_junction(current):
            raise SchemaCrosswalkDiagnosticError(f"{label} cannot use a filesystem link.")


def _read_json_object(path: Path, *, limit: int, label: str) -> tuple[Mapping[str, Any], str]:
    try:
        size = path.stat().st_size
        if size <= 0 or size > limit:
            raise SchemaCrosswalkDiagnosticError(f"{label} exceeds its read limit.")
        raw = path.read_bytes()
        if len(raw) != size or len(raw) > limit:
            raise SchemaCrosswalkDiagnosticError(f"{label} changed during its bounded read.")
        payload = json.loads(raw.decode("utf-8"))
    except SchemaCrosswalkDiagnosticError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SchemaCrosswalkDiagnosticError(f"{label} is unavailable or malformed.") from exc
    if not isinstance(payload, dict):
        raise SchemaCrosswalkDiagnosticError(f"{label} must contain an object.")
    import hashlib

    return payload, hashlib.sha256(raw).hexdigest()


def _exact_registry_version(
    registry: Mapping[str, Any],
    *,
    dataset_id: str,
    dataset_version_id: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    raw_datasets = registry.get("datasets")
    datasets = raw_datasets if isinstance(raw_datasets, list) else []
    matching_datasets = [
        item
        for item in datasets
        if isinstance(item, dict) and str(item.get("datasetId") or "").strip() == dataset_id
    ]
    if len(matching_datasets) != 1 or matching_datasets[0].get("archived"):
        raise SchemaCrosswalkDiagnosticError("The exact registered dataset is unavailable.")
    version_owners: list[tuple[str, Mapping[str, Any]]] = []
    for item in datasets:
        if not isinstance(item, dict):
            continue
        owner_id = str(item.get("datasetId") or "").strip()
        for version in item.get("versions") or ():
            if (
                isinstance(version, dict)
                and str(version.get("versionId") or "").strip() == dataset_version_id
            ):
                version_owners.append((owner_id, version))
    if len(version_owners) != 1:
        raise SchemaCrosswalkDiagnosticError(
            "The exact registered dataset version is missing or contradictory."
        )
    owner_id, version = version_owners[0]
    if owner_id != dataset_id:
        raise SchemaCrosswalkDiagnosticError(
            "The exact registered dataset version belongs to another dataset."
        )
    return matching_datasets[0], version


def _exact_project_state(
    state: Mapping[str, Any],
    *,
    project_id: str,
    dataset_id: str,
    dataset_version_id: str,
) -> int:
    links = state.get("links") if isinstance(state.get("links"), list) else []
    exact_links = [
        link
        for link in links
        if isinstance(link, dict)
        and str(link.get("project_id") or link.get("projectId") or "").strip()
        == project_id
        and str(link.get("dataset_id") or link.get("datasetId") or "").strip()
        == dataset_id
        and str(link.get("link_status") or link.get("linkStatus") or "").strip().casefold()
        == "active"
    ]
    if len(exact_links) != 1:
        raise SchemaCrosswalkDiagnosticError(
            "The exact active project-to-dataset link is unavailable."
        )
    selection = state.get("active_selection")
    if not isinstance(selection, dict):
        raise SchemaCrosswalkDiagnosticError("The exact active dataset selection is unavailable.")
    expected = {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
    }
    for key, expected_value in expected.items():
        camel = {
            "project_id": "projectId",
            "dataset_id": "datasetId",
            "dataset_version_id": "datasetVersionId",
        }[key]
        actual = str(selection.get(key) or selection.get(camel) or "").strip()
        if actual != expected_value:
            raise SchemaCrosswalkDiagnosticError(
                "The active project dataset identity contradicts the exact request."
            )
    status = str(
        selection.get("activation_status") or selection.get("activationStatus") or ""
    ).strip().casefold()
    try:
        revision = int(
            selection.get("activation_revision")
            or selection.get("activationRevision")
            or 0
        )
    except (TypeError, ValueError) as exc:
        raise SchemaCrosswalkDiagnosticError("The active dataset revision is invalid.") from exc
    if status != "active" or revision <= 0:
        raise SchemaCrosswalkDiagnosticError("The active dataset selection is not current.")
    return revision


def _profile_schema(
    *,
    artifact_root: Path,
    profile_reference: object,
    dataset_id: str,
    dataset_version_id: str,
) -> tuple[Mapping[str, Any], str]:
    root = artifact_root.resolve(strict=True)
    if _is_link_or_junction(root) or not root.is_dir():
        raise SchemaCrosswalkDiagnosticError("Dataset artifact authority is unavailable.")
    expected = Path(dataset_id) / "versions" / dataset_version_id / "profile.json"
    supplied = Path(str(profile_reference or ""))
    if supplied.is_absolute() or supplied.parts != expected.parts:
        raise SchemaCrosswalkDiagnosticError(
            "The registered profile reference contradicts the exact dataset version."
        )
    candidate = root.joinpath(*expected.parts)
    _assert_unlinked_chain(root, candidate, "Dataset profile")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SchemaCrosswalkDiagnosticError("The exact dataset profile is unavailable.") from exc
    if not resolved.is_file() or not _is_within(resolved, root):
        raise SchemaCrosswalkDiagnosticError("The exact dataset profile is unavailable.")
    payload, checksum = _read_json_object(
        resolved,
        limit=_MAX_PROFILE_BYTES,
        label="Dataset profile",
    )
    if any(str(key).replace("-", "_").casefold() in _PROHIBITED_PROFILE_KEYS for key in payload):
        raise SchemaCrosswalkDiagnosticError(
            "The dataset profile contains prohibited row-level material."
        )
    return payload, checksum


def _column_identity(columns: object, *, label: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(columns, list) or not columns:
        raise SchemaCrosswalkDiagnosticError(f"{label} contains no schema inventory.")
    identities: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in columns:
        if not isinstance(raw, dict):
            raise SchemaCrosswalkDiagnosticError(f"{label} schema entries are invalid.")
        name_values = [raw[key] for key in ("name", "field_name", "column") if key in raw]
        type_values = [raw[key] for key in ("dtype", "type") if key in raw]
        if len(name_values) != 1 or len(type_values) != 1:
            raise SchemaCrosswalkDiagnosticError(f"{label} schema identity is incomplete.")
        if not isinstance(name_values[0], str) or not isinstance(type_values[0], str):
            raise SchemaCrosswalkDiagnosticError(f"{label} schema identity is invalid.")
        name = _required_text(name_values[0], f"{label} field name")
        dtype = _required_text(type_values[0], f"{label} field type").casefold()
        if name.casefold() in seen:
            raise SchemaCrosswalkDiagnosticError(f"{label} schema fields are not unique.")
        seen.add(name.casefold())
        identities.append((name, dtype))
    return tuple(identities)


def _restricted_output(root: Path, requested: Path) -> Path:
    if not requested.is_absolute() or requested.suffix.casefold() != ".json":
        raise SchemaCrosswalkDiagnosticError(
            "The diagnostic output must be one explicit absolute JSON path."
        )
    diagnostics = root / "diagnostics"
    try:
        diagnostics.mkdir(parents=False, exist_ok=True)
    except OSError as exc:
        raise SchemaCrosswalkDiagnosticError(
            "The restricted diagnostics authority is unavailable."
        ) from exc
    _assert_unlinked_chain(root, diagnostics, "Restricted diagnostics")
    parent = requested.parent
    if parent != diagnostics:
        raise SchemaCrosswalkDiagnosticError(
            "The diagnostic output must be a direct child of the restricted diagnostics authority."
        )
    _assert_unlinked_chain(root, requested, "Restricted diagnostic output")
    if requested.exists():
        raise SchemaCrosswalkDiagnosticError(
            "The exact restricted diagnostic output already exists and was preserved."
        )
    return requested


def _default_project_state_loader(project_id: str) -> Mapping[str, Any]:
    return get_persistence_service().project_dataset_activations.get_project_state(project_id)


def run_schema_crosswalk_diagnostic(
    settings: SchemaCrosswalkDiagnosticSettings,
    *,
    operational_service: OperationalCatalogService | None = None,
    registry_loader: Callable[[], Mapping[str, Any]] | None = None,
    project_state_loader: Callable[[str], Mapping[str, Any]] | None = None,
    dataset_artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Produce one non-authoritative candidate artifact from schema metadata."""

    root = validate_restricted_metadata_root(
        settings.restricted_root,
        repository_root=ROOT,
    )
    service = operational_service or OperationalCatalogService(
        root,
        repository_root=ROOT,
    )
    if service.root.resolve(strict=True) != root.resolve(strict=True):
        raise SchemaCrosswalkDiagnosticError(
            "The operational catalog authority contradicts the configured restricted root."
        )
    if not isinstance(service.catalogs.entitlement_provider, RegistryEntitlementProvider):
        raise SchemaCrosswalkDiagnosticError(
            "The operational catalog service is not bound to the durable entitlement authority."
        )

    catalog_version_id = _identifier(settings.catalog_version_id, "Catalog version ID")
    requested_checksum = validate_sha256(
        settings.catalog_checksum,
        field_name="catalog checksum",
    )
    principal_id = _identifier(settings.principal_id, "Principal ID")
    tenant_id = (
        _identifier(settings.tenant_id, "Tenant ID")
        if settings.tenant_id is not None
        else None
    )
    project_id = _identifier(settings.project_id, "Project ID")
    dataset_id = _identifier(settings.dataset_id, "Dataset ID")
    dataset_version_id = _identifier(settings.dataset_version_id, "Dataset version ID")
    audit_correlation = "bureau-schema-crosswalk-corr-" + uuid.uuid4().hex
    record = service.registry.get_version(catalog_version_id)
    try:
        if record.normalized_catalog_checksum != requested_checksum:
            raise SchemaCrosswalkDiagnosticError(
                "The exact catalog version checksum contradicts the request."
            )
        catalog_key = BureauCatalogKey(
            provider=record.provider_name,
            product=record.product_name,
            edition=record.edition,
            dictionary_version=record.source_release_version,
        )
        # This explicit durable entitlement check intentionally occurs before
        # any restricted catalog file can enter the loader/cache.
        service.registry.entitlement_for(
            principal_id=principal_id,
            tenant_id=tenant_id,
            catalog_version_id=catalog_version_id,
            operation="crosswalk_candidate",
        )

        registry_payload = (registry_loader or dataset_registry.load_registry)()
        if not isinstance(registry_payload, Mapping):
            raise SchemaCrosswalkDiagnosticError("Dataset registry is unavailable.")
        _dataset, version = _exact_registry_version(
            registry_payload,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
        )
        state = (project_state_loader or _default_project_state_loader)(project_id)
        if not isinstance(state, Mapping):
            raise SchemaCrosswalkDiagnosticError("Project dataset authority is unavailable.")
        activation_revision = _exact_project_state(
            state,
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
        )

        profile, profile_checksum = _profile_schema(
            artifact_root=(dataset_artifact_root or dataset_registry.ARTIFACT_ROOT),
            profile_reference=version.get("profilePath"),
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
        )
        schema, schema_checksum = _read_schema(settings.schema_json)
        fields, target, target_sources, _non_catalog = _schema_fields(
            schema,
            target_field=settings.target_field,
            target_source_fields=settings.target_source_fields,
            non_catalog_fields=settings.non_catalog_fields,
        )
        if not target_sources:
            raise SchemaCrosswalkDiagnosticError(
                "At least one deterministic target-source field is required."
            )
        explicit_identity = _column_identity(schema.get("columns"), label="Input schema")
        profile_identity = _column_identity(profile.get("schema"), label="Dataset profile")
        if explicit_identity != profile_identity:
            raise SchemaCrosswalkDiagnosticError(
                "The input schema contradicts the exact registered profile schema."
            )
        schema_identity_checksum = _canonical_hash(
            {"columns": [{"name": name, "dtype": dtype} for name, dtype in explicit_identity]}
        )
        profile_identity_checksum = _canonical_hash(
            {"columns": [{"name": name, "dtype": dtype} for name, dtype in profile_identity]}
        )
        output = _restricted_output(root, settings.output_json)

        context = BureauCatalogAccessContext(
            principal_id=principal_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        crosswalk = service.catalogs.build_dataset_crosswalk_candidates_exact(
            context,
            catalog_key,
            requested_checksum,
            fields,
            target_field=target,
            target_source_fields=target_sources,
            semantic_threshold=float(settings.semantic_threshold),
            semantic_tie_delta=float(settings.semantic_tie_delta),
        )
        typed_mappings = tuple(
            BureauAttributeMatchCandidate.model_validate(mapping)
            for mapping in crosswalk["mappings"]
        )
        protected_statuses = {
            "target": sum(mapping.match_status == "target" for mapping in typed_mappings),
            "deterministic_target_source": sum(
                mapping.match_status == "deterministic_target_source"
                for mapping in typed_mappings
            ),
        }
        if protected_statuses != {
            "target": 1,
            "deterministic_target_source": len(target_sources),
        }:
            raise SchemaCrosswalkDiagnosticError(
                "Target-role exclusion could not be verified in the candidate artifact."
            )
        if any(mapping.institutional_alias_reference for mapping in typed_mappings):
            raise SchemaCrosswalkDiagnosticError(
                "Institutional alias evidence is unavailable for this diagnostic."
            )

        created_at = settings.created_at or datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        identity_payload: dict[str, Any] = {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "schema_checksum": schema_checksum,
            "target_contract_id": settings.target_contract_id,
            "predictor_authorization_id": settings.predictor_authorization_id,
            "catalog_key": catalog_key.model_dump(mode="json"),
            "catalog_checksum": requested_checksum,
            "mappings": [mapping.model_dump(mode="json") for mapping in typed_mappings],
            "crosswalk_status": "candidate_only",
            "candidate_only": True,
            "approved_mappings": [],
            "governed_feature_set_changed": False,
            "dataset_mutated": False,
        }
        crosswalk_id = "bureau-crosswalk-" + _canonical_hash(identity_payload)[:24]
        typed_payload = {
            "crosswalk_id": crosswalk_id,
            "revision": 1,
            **identity_payload,
            "created_by": principal_id,
            "created_at": _required_text(created_at, "Created at"),
        }
        typed = BureauDatasetCrosswalk.model_validate(
            {
                **typed_payload,
                "crosswalk_checksum": _canonical_hash(typed_payload),
            }
        )
        artifact = {
            "artifact_type": "bureau_dataset_schema_crosswalk_diagnostic",
            "artifact_schema_version": "1.0",
            "candidate_only": True,
            "persisted": False,
            "approved_mappings": [],
            "governed_feature_set_changed": False,
            "dataset_mutated": False,
            "project_mutated": False,
            "analysis_scope": {
                "schema_metadata_only": True,
                "profile_schema_only": True,
                "entitlement_checked": True,
                "authorized_operation": "crosswalk_candidate",
                "row_data_accessed": False,
                "preview_accessed": False,
                "sample_accessed": False,
                "final_holdout_accessed": False,
                "institutional_aliases_applied": False,
                "institutional_alias_status": "unavailable_without_governed_alias_authority",
                "mapping_approval_performed": False,
                "mapping_decisions_persisted": False,
                "governed_feature_set_changed": False,
                "dataset_mutated": False,
                "project_mutated": False,
            },
            "identity_verification": {
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "activation_revision": activation_revision,
                "catalog_version_id": catalog_version_id,
                "catalog_checksum": requested_checksum,
                "schema_checksum": schema_checksum,
                "profile_checksum": profile_checksum,
                "schema_identity_checksum": schema_identity_checksum,
                "profile_schema_identity_checksum": profile_identity_checksum,
                "exact_registry_version_verified": True,
                "exact_project_link_verified": True,
                "exact_active_selection_verified": True,
                "profile_schema_identity_verified": True,
            },
            "crosswalk": typed.model_dump(mode="json"),
        }
        _write_atomic(
            output,
            canonical_json_bytes(artifact) + b"\n",
            replace_existing=False,
        )
        status_counts: dict[str, int] = {}
        for mapping in typed.mappings:
            status_counts[mapping.match_status] = (
                status_counts.get(mapping.match_status, 0) + 1
            )
        service.registry.record_access_audit(
            actor=principal_id,
            catalog_version_id=catalog_version_id,
            project_id=project_id,
            action="schema_crosswalk_diagnostic",
            result_status="success",
            correlation_id=audit_correlation,
            safe_detail=f"fields={len(fields)} candidates={len(typed.mappings)}",
        )
        return {
            "ok": True,
            "schema_field_count": len(fields),
            "candidate_count": len(typed.mappings),
            "status_counts": dict(sorted(status_counts.items())),
            "catalog_checksum": requested_checksum,
            "schema_checksum": schema_checksum,
            "profile_checksum": profile_checksum,
            "schema_identity_checksum": schema_identity_checksum,
            "profile_schema_identity_checksum": profile_identity_checksum,
            "crosswalk_checksum": typed.crosswalk_checksum,
            "candidate_only": True,
            "persisted": False,
            "entitlement_checked": True,
            "approved_mapping_count": 0,
            "row_data_accessed": False,
            "preview_accessed": False,
            "sample_accessed": False,
            "final_holdout_accessed": False,
            "governed_feature_set_changed": False,
            "dataset_mutated": False,
            "project_mutated": False,
        }
    except Exception:
        try:
            service.registry.record_access_audit(
                actor=principal_id,
                catalog_version_id=catalog_version_id,
                project_id=project_id,
                action="schema_crosswalk_diagnostic",
                result_status="denied_or_failed",
                correlation_id=audit_correlation,
                safe_detail="candidate artifact not created",
            )
        except Exception:
            pass
        raise


def _safe_error(error_type: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "error_type": error_type,
            "error": "schema crosswalk diagnostic did not complete; inspect restricted diagnostics",
        },
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        summary = run_schema_crosswalk_diagnostic(
            SchemaCrosswalkDiagnosticSettings(
                restricted_root=args.restricted_root,
                catalog_version_id=args.catalog_version_id,
                catalog_checksum=args.catalog_checksum,
                principal_id=args.principal_id,
                tenant_id=args.tenant_id,
                project_id=args.project_id,
                dataset_id=args.dataset_id,
                dataset_version_id=args.dataset_version_id,
                schema_json=args.schema_json,
                output_json=args.output_json,
                target_field=args.target_field,
                target_source_fields=tuple(args.target_source_field),
                non_catalog_fields=tuple(args.non_catalog_field),
                target_contract_id=args.target_contract_id,
                predictor_authorization_id=args.predictor_authorization_id,
                created_at=args.created_at,
                semantic_threshold=args.semantic_threshold,
                semantic_tie_delta=args.semantic_tie_delta,
            )
        )
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:
        print(_safe_error(type(exc).__name__))
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
