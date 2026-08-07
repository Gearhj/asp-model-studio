"""Build a candidate-only dataset-to-bureau-catalog crosswalk.

The command reads one explicit schema document and one exact, checksum-qualified
catalog snapshot.  Detailed mappings are written only to a caller-selected
external restricted path.  Standard output contains aggregate counts and
checksums only; field names, descriptions, source paths, and source-derived
content are never logged.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.bureau_metadata.catalog_service import (  # noqa: E402
    BureauCatalogAccessDeniedError,
    BureauCatalogService,
)
from server.bureau_metadata.catalog_store import (  # noqa: E402
    BureauCatalogLoader,
    BureauCatalogStore,
    validate_external_catalog_root,
)
from server.bureau_metadata.normalizer import (  # noqa: E402
    canonical_json_bytes,
    validate_sha256,
)
from server.bureau_metadata.types import (  # noqa: E402
    BureauAttributeMatchCandidate,
    BureauCatalogAccessContext,
    BureauCatalogAccessGrant,
    BureauCatalogKey,
    BureauDatasetCrosswalk,
    CatalogOperation,
)


_MAX_SCHEMA_BYTES = 16 * 1024 * 1024
_MAX_ENTITLEMENT_BYTES = 64 * 1024
_SCHEMA_TOP_LEVEL_KEYS = frozenset({"columns", "schemaVersion", "schema_version"})
_SCHEMA_COLUMN_KEYS = frozenset(
    {
        "name",
        "field_name",
        "column",
        "dtype",
        "type",
        "description",
        "label",
        "units",
        "unit",
        "min",
        "minimum",
        "observed_min",
        "max",
        "maximum",
        "observed_max",
        "mean",
        "std",
        "distinctSample",
        "distinct_count",
        "missingCountSample",
        "missing_count",
        "missingPctSample",
        "missing_pct",
        "observed_special_values",
        "observedSpecialValues",
        "special_values",
        "specialValues",
    }
)
_SPECIAL_VALUE_KEYS = (
    "observed_special_values",
    "observedSpecialValues",
    "special_values",
    "specialValues",
)


class CrosswalkBuildError(RuntimeError):
    """Raised when an exact, schema-only crosswalk cannot be produced safely."""


class _RedactingArgumentParser(argparse.ArgumentParser):
    """Prevent argparse from echoing restricted path or content fragments."""

    def error(self, _message: str) -> None:
        raise CrosswalkBuildError("Command arguments are incomplete or invalid.")


class _ExactGrantProvider:
    """One externally supplied grant; never discovers or broadens entitlement."""

    def __init__(self, grant: BureauCatalogAccessGrant) -> None:
        self.grant = grant

    def authorize(
        self,
        context: BureauCatalogAccessContext,
        catalog_key: BureauCatalogKey,
        catalog_checksum: str,
        operation: CatalogOperation,
    ) -> BureauCatalogAccessGrant:
        grant = self.grant
        if (
            grant.principal_id != context.principal_id
            or grant.tenant_id != context.tenant_id
            or grant.catalog_key != catalog_key
            or grant.catalog_checksum != catalog_checksum
            or grant.operation != operation
        ):
            raise BureauCatalogAccessDeniedError(
                "Bureau catalog access is not authorized."
            )
        return grant


@dataclass(frozen=True, slots=True)
class CrosswalkBuildSettings:
    catalog_root: Path
    entitlement_json: Path
    principal_id: str
    tenant_id: str | None
    provider: str
    product: str
    edition: str
    dictionary_version: str
    catalog_checksum: str
    schema_json: Path
    output_json: Path
    project_id: str
    dataset_id: str
    dataset_version_id: str
    target_field: str
    target_source_fields: tuple[str, ...] = ()
    non_catalog_fields: tuple[str, ...] = ()
    target_contract_id: str | None = None
    predictor_authorization_id: str | None = None
    created_by: str = "atlas-offline-crosswalk-builder"
    created_at: str | None = None
    semantic_threshold: float = 0.55
    semantic_tie_delta: float = 0.03
    replace_existing: bool = False


def _parser() -> argparse.ArgumentParser:
    parser = _RedactingArgumentParser(description=__doc__)
    parser.add_argument("--catalog-root", type=Path, required=True)
    parser.add_argument("--entitlement-json", type=Path, required=True)
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--tenant-id")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--edition", required=True)
    parser.add_argument("--dictionary-version", required=True)
    parser.add_argument("--catalog-checksum", required=True)
    parser.add_argument("--schema-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-version-id", required=True)
    parser.add_argument("--target-field", required=True)
    parser.add_argument("--target-source-field", action="append", default=[])
    parser.add_argument("--non-catalog-field", action="append", default=[])
    parser.add_argument("--target-contract-id")
    parser.add_argument("--predictor-authorization-id")
    parser.add_argument(
        "--created-by",
        default="atlas-offline-crosswalk-builder",
    )
    parser.add_argument("--created-at")
    parser.add_argument("--semantic-threshold", type=float, default=0.55)
    parser.add_argument("--semantic-tie-delta", type=float, default=0.03)
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Explicitly replace an existing external candidate artifact.",
    )
    return parser


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CrosswalkBuildError(f"{label} is required.")
    cleaned = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise CrosswalkBuildError(f"{label} contains unsupported characters.")
    return cleaned


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _reject_unknown_keys(
    payload: Mapping[str, Any],
    allowed: frozenset[str],
    label: str,
) -> None:
    if any(not isinstance(key, str) for key in payload):
        raise CrosswalkBuildError(f"{label} keys must be strings.")
    if set(payload).difference(allowed):
        raise CrosswalkBuildError(f"{label} contains unsupported metadata.")


def _scalar_metadata(value: object, label: str) -> object:
    if isinstance(value, (Mapping, list, tuple, set, frozenset)):
        raise CrosswalkBuildError(
            f"{label} cannot contain nested row, preview, value, or holdout payloads."
        )
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise CrosswalkBuildError(f"{label} contains an unsupported metadata value.")


def _read_schema(path: Path) -> tuple[Mapping[str, Any], str]:
    if not path.is_absolute():
        raise CrosswalkBuildError("The schema path must be explicit and absolute.")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CrosswalkBuildError("The exact schema document is unavailable.") from exc
    if not resolved.is_file() or resolved.suffix.casefold() != ".json":
        raise CrosswalkBuildError("The schema document must be one JSON file.")
    try:
        if resolved.stat().st_size > _MAX_SCHEMA_BYTES:
            raise CrosswalkBuildError("The schema document exceeds its read limit.")
        raw = resolved.read_bytes()
    except OSError as exc:
        raise CrosswalkBuildError("The schema document could not be read.") from exc
    if len(raw) > _MAX_SCHEMA_BYTES:
        raise CrosswalkBuildError("The schema document exceeds its read limit.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise CrosswalkBuildError("The schema document is malformed.") from exc
    if not isinstance(payload, dict):
        raise CrosswalkBuildError("The schema document must contain an object.")
    _reject_unknown_keys(payload, _SCHEMA_TOP_LEVEL_KEYS, "Schema document")
    for key in ("schemaVersion", "schema_version"):
        if key in payload:
            _scalar_metadata(payload[key], "Schema version")
    if "schemaVersion" in payload and "schema_version" in payload:
        raise CrosswalkBuildError("Schema version metadata is contradictory.")
    return payload, hashlib.sha256(raw).hexdigest()


def _read_entitlement(path: Path) -> BureauCatalogAccessGrant:
    if not path.is_absolute() or path.suffix.casefold() != ".json":
        raise CrosswalkBuildError(
            "The entitlement must be an explicit absolute external JSON path."
        )
    try:
        parent = validate_external_catalog_root(path.parent, repository_root=ROOT)
        resolved = (parent / path.name).resolve(strict=True)
    except Exception as exc:
        raise CrosswalkBuildError("The exact entitlement is unavailable.") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise CrosswalkBuildError("The entitlement must be a regular external file.")
    try:
        size = resolved.stat().st_size
        if size > _MAX_ENTITLEMENT_BYTES:
            raise CrosswalkBuildError("The entitlement exceeds its read limit.")
        raw = resolved.read_bytes()
    except OSError as exc:
        raise CrosswalkBuildError("The exact entitlement could not be read.") from exc
    if len(raw) > _MAX_ENTITLEMENT_BYTES or len(raw) != size:
        raise CrosswalkBuildError("The entitlement changed or exceeded its read limit.")
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("entitlement is not an object")
        return BureauCatalogAccessGrant.model_validate(payload)
    except Exception as exc:
        raise CrosswalkBuildError("The entitlement contract is invalid.") from exc


def _column_name(column: Mapping[str, Any]) -> str:
    value = _value(column, "name", "field_name", "column")
    if value is None:
        raise CrosswalkBuildError("Every schema column requires an exact field name.")
    return _required_text(value, "Schema field name")


def _value(column: Mapping[str, Any], *keys: str) -> Any:
    present = [key for key in keys if key in column]
    if len(present) > 1:
        raise CrosswalkBuildError("Schema column aliases are contradictory.")
    return column[present[0]] if present else None


def _numeric_string(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not numeric.is_finite():
        return None
    rendered = format(numeric, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _explicit_special_values(column: Mapping[str, Any]) -> list[str]:
    raw = _value(column, *_SPECIAL_VALUE_KEYS)
    if raw is None:
        return []
    if isinstance(raw, (str, int, float, Decimal)) and not isinstance(raw, bool):
        values: Iterable[object] = (raw,)
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        values = raw
    else:
        raise CrosswalkBuildError("Observed special-value metadata is malformed.")
    materialized = tuple(values)
    if len(materialized) > 4_096:
        raise CrosswalkBuildError("Observed special-value metadata exceeds its limit.")
    normalized: set[str] = set()
    for value in materialized:
        if value is None or isinstance(value, (bool, Mapping, list, tuple, set, frozenset)):
            raise CrosswalkBuildError(
                "Observed special values must be bounded scalar metadata."
            )
        normalized.add(_required_text(str(value), "Observed special value"))
    return sorted(normalized)


def _schema_fields(
    schema: Mapping[str, Any],
    *,
    target_field: str,
    target_source_fields: Sequence[str],
    non_catalog_fields: Sequence[str],
) -> tuple[list[dict[str, Any]], str, tuple[str, ...], tuple[str, ...]]:
    raw_columns = schema.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        raise CrosswalkBuildError("The schema contains no column inventory.")

    columns: list[Mapping[str, Any]] = []
    names: dict[str, str] = {}
    for raw in raw_columns:
        if not isinstance(raw, dict):
            raise CrosswalkBuildError("Every schema column must be an object.")
        _reject_unknown_keys(raw, _SCHEMA_COLUMN_KEYS, "Schema column")
        for key, value in raw.items():
            if key not in _SPECIAL_VALUE_KEYS:
                _scalar_metadata(value, "Schema column metadata")
        name = _column_name(raw)
        folded = name.casefold()
        if folded in names:
            raise CrosswalkBuildError("Schema field names must be unique.")
        names[folded] = name
        columns.append(raw)

    def exact_schema_name(value: str, label: str) -> str:
        requested = _required_text(value, label)
        resolved = names.get(requested.casefold())
        if resolved is None:
            raise CrosswalkBuildError(f"{label} is absent from the exact schema.")
        return resolved

    exact_target = exact_schema_name(target_field, "Target field")
    exact_sources = tuple(
        exact_schema_name(value, "Deterministic target-source field")
        for value in target_source_fields
    )
    exact_non_catalog = tuple(
        exact_schema_name(value, "Non-catalog field") for value in non_catalog_fields
    )
    if len({value.casefold() for value in exact_sources}) != len(exact_sources):
        raise CrosswalkBuildError("Deterministic target-source fields must be unique.")
    if len({value.casefold() for value in exact_non_catalog}) != len(exact_non_catalog):
        raise CrosswalkBuildError("Non-catalog fields must be unique.")
    protected_roles = {exact_target.casefold(), *(value.casefold() for value in exact_sources)}
    if protected_roles & {value.casefold() for value in exact_non_catalog}:
        raise CrosswalkBuildError("Target roles cannot also be non-catalog fields.")
    if exact_target.casefold() in {value.casefold() for value in exact_sources}:
        raise CrosswalkBuildError("The target cannot also be its deterministic source.")

    non_catalog_lookup = {value.casefold() for value in exact_non_catalog}
    fields: list[dict[str, Any]] = []
    for column in columns:
        name = _column_name(column)
        observed_min = _value(column, "min", "minimum", "observed_min")
        observed_max = _value(column, "max", "maximum", "observed_max")
        special_values = _explicit_special_values(column)
        normalized_min = _numeric_string(observed_min)
        # A negative observed minimum is durable evidence of a potential
        # institution-level recode, but not evidence of its source meaning.
        # Conservatively surface that code for unresolved analyst review.
        if normalized_min is not None and Decimal(normalized_min) < 0:
            special_values = sorted({*special_values, normalized_min})
        field: dict[str, Any] = {
            "field_name": name,
            "catalog_eligible": name.casefold() not in non_catalog_lookup,
        }
        for output_key, keys in (
            ("description", ("description", "label")),
            ("units", ("units", "unit")),
        ):
            candidate = _value(column, *keys)
            if isinstance(candidate, str) and candidate.strip():
                field[output_key] = candidate.strip()
        if observed_min is not None:
            field["observed_min"] = observed_min
        if observed_max is not None:
            field["observed_max"] = observed_max
        if special_values:
            field["observed_special_values"] = special_values
        fields.append(field)
    return fields, exact_target, exact_sources, exact_non_catalog


def _external_output_path(path: Path) -> Path:
    if not path.is_absolute() or path.suffix.casefold() != ".json":
        raise CrosswalkBuildError(
            "The output must be an explicit absolute external JSON path."
        )
    try:
        parent = validate_external_catalog_root(path.parent, repository_root=ROOT)
    except Exception as exc:
        raise CrosswalkBuildError(
            "The output parent must be an existing external restricted directory."
        ) from exc
    candidate = parent / path.name
    if candidate.is_symlink():
        raise CrosswalkBuildError("The external output cannot be a filesystem link.")
    if candidate.exists() and not candidate.is_file():
        raise CrosswalkBuildError("The external output target is not a regular file.")
    return candidate


def _write_atomic(path: Path, payload: bytes, *, replace_existing: bool) -> None:
    if path.exists() and not replace_existing:
        raise CrosswalkBuildError(
            "The external output already exists; replacement requires explicit approval."
        )
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.partial"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and not replace_existing:
            raise CrosswalkBuildError(
                "The external output appeared concurrently and was preserved."
            )
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def build_crosswalk_artifact(settings: CrosswalkBuildSettings) -> dict[str, Any]:
    key = BureauCatalogKey(
        provider=_required_text(settings.provider, "Provider"),
        product=_required_text(settings.product, "Product"),
        edition=_required_text(settings.edition, "Edition"),
        dictionary_version=_required_text(
            settings.dictionary_version,
            "Dictionary version",
        ),
    )
    checksum = validate_sha256(
        settings.catalog_checksum,
        field_name="catalog checksum",
    )
    schema, schema_checksum = _read_schema(settings.schema_json)
    fields, target, target_sources, _non_catalog = _schema_fields(
        schema,
        target_field=settings.target_field,
        target_source_fields=settings.target_source_fields,
        non_catalog_fields=settings.non_catalog_fields,
    )
    grant = _read_entitlement(settings.entitlement_json)
    context = BureauCatalogAccessContext(
        principal_id=_required_text(settings.principal_id, "Principal ID"),
        tenant_id=(
            _required_text(settings.tenant_id, "Tenant ID")
            if settings.tenant_id is not None
            else None
        ),
    )
    service = BureauCatalogService(
        BureauCatalogLoader(BureauCatalogStore(settings.catalog_root)),
        _ExactGrantProvider(grant),
    )
    crosswalk = service.build_dataset_crosswalk_candidates_exact(
        context,
        key,
        checksum,
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
    created_at = settings.created_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    identity_payload: dict[str, Any] = {
        "project_id": _required_text(settings.project_id, "Project ID"),
        "dataset_id": _required_text(settings.dataset_id, "Dataset ID"),
        "dataset_version_id": _required_text(
            settings.dataset_version_id,
            "Dataset version ID",
        ),
        "schema_checksum": schema_checksum,
        "target_contract_id": settings.target_contract_id,
        "predictor_authorization_id": settings.predictor_authorization_id,
        "catalog_key": key.model_dump(mode="json"),
        "catalog_checksum": checksum,
        "mappings": [mapping.model_dump(mode="json") for mapping in typed_mappings],
        "crosswalk_status": "candidate_only",
        "candidate_only": True,
        "approved_mappings": [],
        "governed_feature_set_changed": False,
        "dataset_mutated": False,
    }
    crosswalk_id = f"bureau-crosswalk-{_canonical_hash(identity_payload)[:24]}"
    typed_payload: dict[str, Any] = {
        "crosswalk_id": crosswalk_id,
        "revision": 1,
        **identity_payload,
        "created_by": _required_text(settings.created_by, "Created by"),
        "created_at": _required_text(created_at, "Created at"),
    }
    typed = BureauDatasetCrosswalk.model_validate(
        {
            **typed_payload,
            "crosswalk_checksum": _canonical_hash(typed_payload),
        }
    )
    artifact = {
        "artifact_type": "bureau_dataset_crosswalk_candidate",
        "artifact_schema_version": "1.0",
        "analysis_scope": {
            "schema_metadata_only": True,
            "entitlement_checked": True,
            "row_data_accessed": False,
            "final_holdout_accessed": False,
            "institutional_aliases_applied": False,
            "mapping_approval_performed": False,
            "dataset_mutated": False,
            "project_mutated": False,
        },
        "crosswalk": typed.model_dump(mode="json"),
    }
    output = _external_output_path(settings.output_json)
    _write_atomic(
        output,
        canonical_json_bytes(artifact) + b"\n",
        replace_existing=settings.replace_existing,
    )
    status_counts: dict[str, int] = {}
    for mapping in typed.mappings:
        status_counts[mapping.match_status] = status_counts.get(mapping.match_status, 0) + 1
    return {
        "ok": True,
        "schema_field_count": len(fields),
        "candidate_count": len(typed.mappings),
        "status_counts": dict(sorted(status_counts.items())),
        "catalog_checksum": checksum,
        "schema_checksum": schema_checksum,
        "crosswalk_checksum": typed.crosswalk_checksum,
        "candidate_only": True,
        "entitlement_checked": True,
        "approved_mapping_count": 0,
        "row_data_accessed": False,
        "final_holdout_accessed": False,
        "dataset_mutated": False,
        "project_mutated": False,
    }


def _safe_error(error_type: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "error_type": error_type,
            "error": "candidate crosswalk build did not complete; consult restricted diagnostics",
        },
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        summary = build_crosswalk_artifact(
            CrosswalkBuildSettings(
                catalog_root=args.catalog_root,
                entitlement_json=args.entitlement_json,
                principal_id=args.principal_id,
                tenant_id=args.tenant_id,
                provider=args.provider,
                product=args.product,
                edition=args.edition,
                dictionary_version=args.dictionary_version,
                catalog_checksum=args.catalog_checksum,
                schema_json=args.schema_json,
                output_json=args.output_json,
                project_id=args.project_id,
                dataset_id=args.dataset_id,
                dataset_version_id=args.dataset_version_id,
                target_field=args.target_field,
                target_source_fields=tuple(args.target_source_field),
                non_catalog_fields=tuple(args.non_catalog_field),
                target_contract_id=args.target_contract_id,
                predictor_authorization_id=args.predictor_authorization_id,
                created_by=args.created_by,
                created_at=args.created_at,
                semantic_threshold=args.semantic_threshold,
                semantic_tie_delta=args.semantic_tie_delta,
                replace_existing=args.replace_existing,
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
