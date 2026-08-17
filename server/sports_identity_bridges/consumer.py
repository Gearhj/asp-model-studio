from __future__ import annotations

import copy
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

import pyarrow.parquet as pq

from ..sports_datasets.consumer import (
    ManifestValidationError,
    _format_utc_now,
    _is_reparse_point,
    _validate_resolved_child,
    canonical_json_bytes,
    filesystem_identity,
    load_strict_json,
    parquet_physical_schema,
    raw_absolute_path,
    reject_reparse_boundary,
    reject_reparse_chain,
    sha256_bytes,
    sha256_file,
    validate_package_relative_uri,
)
from .constants import (
    ALIAS_AUTHORITY_SHA,
    ALIAS_FILE,
    ALIAS_FILE_SHA,
    ALIAS_SCHEMA,
    ALIAS_SCHEMA_FINGERPRINT,
    ALLOWED_PURPOSES,
    BRIDGE_MANIFEST_ID,
    BRIDGE_MANIFEST_SHA,
    BRIDGE_PACKAGE_ID,
    CANONICALIZATION_VERSION,
    CONTRACT_NAME,
    CONTRACT_VERSION,
    DIMENSION_AUTHORITY_SHA,
    DIMENSION_FILE,
    DIMENSION_FILE_SHA,
    DIMENSION_SCHEMA,
    DIMENSION_SCHEMA_FINGERPRINT,
    EVIDENCE_CUTOFF,
    EXPECTED_ACTIVE_PLAYER_ROWS,
    EXPECTED_ALIASES_PER_NAMESPACE,
    EXPECTED_ALIAS_ROWS,
    EXPECTED_FILES,
    EXPECTED_GOVERNED_ACTIVE_PLAYERS,
    EXPECTED_JOIN_CONTRACTS,
    EXPECTED_JOIN_REFERENCES,
    EXPECTED_JOIN_VALIDATION,
    EXPECTED_LIMITATION_IDS,
    EXPECTED_NAMESPACE_COUNT,
    EXPECTED_NAMESPACES,
    EXPECTED_NAMESPACE_SOURCES,
    EXPECTED_PACKAGE_BYTES,
    EXPECTED_PACKAGE_FILES,
    EXPECTED_PRIMARY_GOVERNED_PLAYERS,
    EXPECTED_PRIMARY_PORTABLE_PLAYERS,
    EXPECTED_SEMANTIC_BYTES,
    EXPECTED_SEMANTIC_FILES,
    EXPECTED_Y_MINUS_1,
    EXPECTED_Y_MINUS_1_RECORDS,
    LEAGUE,
    LOGICAL_PACKAGE_ROOT,
    MANIFEST_FILE,
    MANIFEST_FILE_SHA,
    PACKAGE_RELATIVE_ROOT,
    PA_CLASS_ORDER,
    PARENT_DATASET_ID,
    PARENT_DATASET_VERSION_ID,
    PARENT_MANIFEST_ID,
    PARENT_MANIFEST_SHA,
    PARENT_PACKAGE_ID,
    PARENT_PARTITION_AUTHORITY_SHA,
    PROHIBITED_PURPOSES,
    PUBLICATION_TIMESTAMP,
    PUBLISHER,
    README_SHA,
    RIGHTS_CONTROL_IDS,
    SOURCE_RIGHTS_FILE,
    SOURCE_RIGHTS_SHA,
    SPORT,
    VALIDATION_REPORT_FILE,
    VALIDATION_REPORT_SHA,
)


ProgressCallback = Callable[[Mapping[str, Any]], None]
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_UUID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)^[a-z]:[\\/]")
_SENSITIVE_KEYS = {
    "api_key",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "credential",
    "credentials",
    "client_secret",
    "private_key",
}

_MANIFEST_KEYS = {
    "bridge_files",
    "bridge_manifest_id",
    "bridge_manifest_sha256",
    "bridge_package_id",
    "canonicalization_version",
    "contract_name",
    "contract_version",
    "coverage_evidence",
    "evidence_cutoff",
    "identity_namespaces",
    "join_contracts",
    "join_validation",
    "league",
    "limitations",
    "parent_binding",
    "publication_timestamp",
    "publisher",
    "source_lineage",
    "source_rights",
    "sport",
    "totals",
    "y_minus_1_prior_eligibility",
}
_BRIDGE_FILE_KEYS = {
    "byte_count",
    "logical_uri",
    "media_type",
    "physical_schema_fingerprint",
    "row_authority_sha256",
    "row_count",
    "semantic_digest_member",
    "sha256",
}
_PARENT_BINDING_KEYS = {
    "parent_dataset_id",
    "parent_dataset_manifest_id",
    "parent_dataset_manifest_sha256",
    "parent_dataset_version_id",
    "parent_package_id",
    "parent_partition_authority_sha256",
    "plate_appearance_class_order",
}
_NAMESPACE_KEYS = {
    "alias_rows",
    "canonical_players",
    "namespace",
    "source_keys",
    "source_version_ids",
    "unique_source_ids",
}
_JOIN_CONTRACT_KEYS = {
    "duplicate_policy",
    "join_contract_id",
    "join_type",
    "namespace",
    "null_policy",
    "physical_field_name",
    "source_family",
    "target_canonical_field",
    "unresolved_policy",
}
_JOIN_VALIDATION_KEYS = {
    "ambiguous_reference_count",
    "join_contract_id",
    "mapping_rate",
    "multiply_mapped_reference_count",
    "reference_count",
    "resolved_reference_count",
    "seasons",
    "unique_canonical_players",
    "unique_source_ids",
    "unresolved_reference_count",
}
_Y_MINUS_1_KEYS = {
    "ambiguous_identity_rows",
    "eligible_prior_rate",
    "legitimate_missing_prior_rows",
    "maximum_eligible_prior_season",
    "multiply_mapped_identity_rows",
    "reference_rows",
    "role",
    "rows_with_eligible_prior",
    "target_season",
    "unresolved_identity_rows",
}
_LIMITATION_KEYS = {"description", "limitation_id", "scope"}
_REPORT_KEYS = {
    "authorities",
    "bridge_manifest_id",
    "bridge_manifest_sha256",
    "bridge_package_id",
    "checks",
    "contract_name",
    "contract_version",
    "counts",
    "identity_namespaces",
    "join_validation",
    "parent_dataset_manifest_sha256",
    "parent_partition_authority_sha256",
    "schema_version",
    "status",
    "y_minus_1_prior_eligibility",
}
_RIGHTS_KEYS = {
    "identity_checksum",
    "package_allowed_purposes",
    "package_controls",
    "package_prohibited_purposes",
    "parent_schema_version",
    "parent_source_rights_file_sha256",
    "record_count",
    "records",
    "schema_version",
}


class IdentityBridgeValidationError(ManifestValidationError):
    """Fail-closed bridge error that exposes logical identities only."""


@dataclass(frozen=True)
class ValidatedIdentityBridge:
    package_root: Path
    manifest: dict[str, Any]
    source_rights: dict[str, Any]
    validation_report: dict[str, Any]
    aliases: tuple[dict[str, Any], ...]
    dimensions: tuple[dict[str, Any], ...]
    root_identity: str
    validated_at: str

    @property
    def alias_rows(self) -> tuple[dict[str, Any], ...]:
        """Compatibility projection for callers that use the physical table name."""

        return self.aliases

    @property
    def dimension_rows(self) -> tuple[dict[str, Any], ...]:
        """Compatibility projection for callers that use the physical table name."""

        return self.dimensions

    @property
    def retrosheet_aliases(self) -> dict[str, str]:
        return {
            str(row["parent_join_key"]): str(row["canonical_player_uuid"])
            for row in self.aliases
            if row["namespace"] == "RETROSHEET"
        }

    @property
    def dimension_uuids(self) -> frozenset[str]:
        return frozenset(str(row["canonical_player_uuid"]) for row in self.dimensions)


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], *, code: str, label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise IdentityBridgeValidationError(
            code,
            f"{label} field set differs (missing={sorted(expected - actual)}, extra={sorted(actual - expected)})",
        )


def _require_sha(value: Any, expected: str, *, code: str, label: str) -> None:
    if type(value) is not str or not _SHA_RE.fullmatch(value) or value != expected:
        raise IdentityBridgeValidationError(code, f"{label} differs from the approved SHA-256 authority")


def semantic_bridge_manifest_sha(manifest: Mapping[str, Any]) -> str:
    semantic = copy.deepcopy(dict(manifest))
    for field in (
        "bridge_manifest_id",
        "bridge_manifest_sha256",
        "bridge_package_id",
        "publication_timestamp",
    ):
        if field not in semantic:
            raise IdentityBridgeValidationError("MISSING_IDENTITY_FIELD", f"Missing bridge identity field: {field}")
        del semantic[field]
    return sha256_bytes(canonical_json_bytes(semantic))


def approved_bridge_root(exchange_root: Path) -> Path:
    raw_root = raw_absolute_path(exchange_root)
    reject_reparse_chain(raw_root, label="Configured exchange root chain")
    bridge_root = raw_root
    for component in PACKAGE_RELATIVE_ROOT.parts:
        bridge_root = bridge_root / component
        reject_reparse_boundary(bridge_root, label=f"Configured identity-bridge component {component}")
    return bridge_root


def _scan_json_security(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in _SENSITIVE_KEYS:
                raise IdentityBridgeValidationError("CREDENTIAL_FIELD_REJECTED", f"Credential-shaped field rejected at {path}")
            _scan_json_security(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_json_security(item, path=f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    if (
        _WINDOWS_ABSOLUTE_RE.match(value)
        or value.startswith(("/", "\\\\", "file:"))
        or "\\.runtime\\" in value.casefold()
        or "/.runtime/" in value.casefold()
    ):
        raise IdentityBridgeValidationError("NON_PORTABLE_PATH_REJECTED", f"Physical or runtime path rejected at {path}")


class SportsIdentityBridgeV1Consumer:
    """Strict structural consumer for SPORTS_IDENTITY_BRIDGE_V1."""

    def __init__(self, package_root: Path, *, progress: ProgressCallback | None = None) -> None:
        raw_root = raw_absolute_path(package_root)
        reject_reparse_chain(raw_root, label="Configured identity-bridge root chain")
        self.package_root = raw_root.resolve(strict=False)
        self.progress = progress
        self._started = time.monotonic()

    def _emit(self, stage: str, *, files: int = 0, rows: int = 0, errors: int = 0) -> None:
        if self.progress is None:
            return
        self.progress(
            {
                "title": "ASP MODEL STUDIO — MLB IDENTITY BRIDGE",
                "stage": stage,
                "elapsedSeconds": round(time.monotonic() - self._started, 2),
                "filesProcessed": files,
                "filesTotal": EXPECTED_PACKAGE_FILES,
                "rowsProcessed": rows,
                "rowsTotal": EXPECTED_ALIAS_ROWS + EXPECTED_ACTIVE_PLAYER_ROWS,
                "errors": errors,
                "etaSeconds": None,
            }
        )

    @staticmethod
    def validate_v1_contract(manifest: Mapping[str, Any]) -> None:
        _require_exact_keys(manifest, _MANIFEST_KEYS, code="BRIDGE_MANIFEST_FIELDS_MISMATCH", label="Bridge manifest")
        exact = {
            "contract_name": CONTRACT_NAME,
            "contract_version": CONTRACT_VERSION,
            "canonicalization_version": CANONICALIZATION_VERSION,
        }
        for key, expected in exact.items():
            if type(manifest.get(key)) is not str or manifest[key] != expected:
                raise IdentityBridgeValidationError("BRIDGE_CONTRACT_MISMATCH", f"{key} differs from SPORTS_IDENTITY_BRIDGE_V1")

    @staticmethod
    def validate_manifest_contract(manifest: Mapping[str, Any]) -> None:
        """Validate the one frozen MLB FD1 adapter supported by V1.

        Keeping dispatch here gives integrations a single strict consumer entry point
        while the adapter-specific authority remains isolated below.
        """

        MlbFd1IdentityBridgeAdapter.validate_manifest_contract(manifest)

    def validate(self) -> ValidatedIdentityBridge:
        adapter = MlbFd1IdentityBridgeAdapter(
            self.package_root,
            progress=self.progress,
        )
        adapter._started = self._started
        return adapter.validate()


class MlbFd1IdentityBridgeAdapter(SportsIdentityBridgeV1Consumer):
    """Frozen MLB FD1 adapter layered on the strict V1 bridge consumer."""

    @staticmethod
    def validate_manifest_contract(manifest: Mapping[str, Any]) -> None:
        SportsIdentityBridgeV1Consumer.validate_v1_contract(manifest)
        exact = {
            "publisher": PUBLISHER,
            "sport": SPORT,
            "league": LEAGUE,
            "evidence_cutoff": EVIDENCE_CUTOFF,
            "publication_timestamp": PUBLICATION_TIMESTAMP,
        }
        for key, expected in exact.items():
            if type(manifest.get(key)) is not str or manifest[key] != expected:
                raise IdentityBridgeValidationError("BRIDGE_ADAPTER_AUTHORITY_MISMATCH", f"{key} differs from the MLB FD1 bridge authority")

        digest = semantic_bridge_manifest_sha(manifest)
        if digest != BRIDGE_MANIFEST_SHA or manifest.get("bridge_manifest_sha256") != digest:
            raise IdentityBridgeValidationError("BRIDGE_SEMANTIC_DIGEST_MISMATCH", "Bridge semantic SHA-256 differs")
        if manifest.get("bridge_manifest_id") != f"sports-identity-bridge-manifest:sha256:{digest}":
            raise IdentityBridgeValidationError("BRIDGE_DERIVED_ID_MISMATCH", "Bridge manifest ID is not digest-derived")
        if manifest.get("bridge_package_id") != f"sha256-{digest}":
            raise IdentityBridgeValidationError("BRIDGE_DERIVED_ID_MISMATCH", "Bridge package ID is not digest-derived")

        binding = manifest.get("parent_binding")
        if type(binding) is not dict:
            raise IdentityBridgeValidationError("PARENT_BINDING_MISSING", "Bridge parent binding is required")
        _require_exact_keys(binding, _PARENT_BINDING_KEYS, code="PARENT_BINDING_FIELDS_MISMATCH", label="Parent binding")
        expected_binding = {
            "parent_dataset_id": PARENT_DATASET_ID,
            "parent_dataset_manifest_id": PARENT_MANIFEST_ID,
            "parent_dataset_manifest_sha256": PARENT_MANIFEST_SHA,
            "parent_dataset_version_id": PARENT_DATASET_VERSION_ID,
            "parent_package_id": PARENT_PACKAGE_ID,
            "parent_partition_authority_sha256": PARENT_PARTITION_AUTHORITY_SHA,
            "plate_appearance_class_order": list(PA_CLASS_ORDER),
        }
        if binding != expected_binding:
            raise IdentityBridgeValidationError("PARENT_BINDING_MISMATCH", "Bridge is not bound to the exact registered MLB FD1 authority")

        MlbFd1IdentityBridgeAdapter._validate_declared_files(manifest)
        MlbFd1IdentityBridgeAdapter._validate_namespaces(manifest)
        MlbFd1IdentityBridgeAdapter._validate_join_contracts(manifest)
        MlbFd1IdentityBridgeAdapter._validate_join_validation(manifest.get("join_validation"))
        MlbFd1IdentityBridgeAdapter._validate_y_minus_1(manifest.get("y_minus_1_prior_eligibility"))
        MlbFd1IdentityBridgeAdapter._validate_rights_projection(manifest)
        MlbFd1IdentityBridgeAdapter._validate_one_player_limitation(manifest)
        MlbFd1IdentityBridgeAdapter._validate_source_boundary(manifest)
        _scan_json_security(manifest)

    @staticmethod
    def _validate_declared_files(manifest: Mapping[str, Any]) -> None:
        rows = manifest.get("bridge_files")
        if type(rows) is not list or len(rows) != EXPECTED_SEMANTIC_FILES:
            raise IdentityBridgeValidationError("BRIDGE_FILE_DECLARATION_COUNT_MISMATCH", "Exactly four semantic bridge files are required")
        expected_semantic = {
            DIMENSION_FILE: (183_341, DIMENSION_FILE_SHA, EXPECTED_ACTIVE_PLAYER_ROWS, DIMENSION_SCHEMA_FINGERPRINT, DIMENSION_AUTHORITY_SHA),
            "attribution.md": (1_424, EXPECTED_FILES["attribution.md"][1], None, None, None),
            ALIAS_FILE: (1_848_549, ALIAS_FILE_SHA, EXPECTED_ALIAS_ROWS, ALIAS_SCHEMA_FINGERPRINT, ALIAS_AUTHORITY_SHA),
            SOURCE_RIGHTS_FILE: (9_576, SOURCE_RIGHTS_SHA, None, None, None),
        }
        observed: list[str] = []
        for row in rows:
            if type(row) is not dict:
                raise IdentityBridgeValidationError("INVALID_BRIDGE_FILE_DECLARATION", "Bridge file declarations must be objects")
            _require_exact_keys(row, _BRIDGE_FILE_KEYS, code="BRIDGE_FILE_FIELDS_MISMATCH", label="Bridge file declaration")
            uri = validate_package_relative_uri(row.get("logical_uri"))
            observed.append(uri)
            if uri not in expected_semantic:
                raise IdentityBridgeValidationError("UNAPPROVED_SEMANTIC_FILE", "Semantic bridge file is not approved", logical_uri=uri)
            expected_bytes, expected_sha, expected_rows, expected_schema, expected_authority = expected_semantic[uri]
            if (
                row.get("byte_count") != expected_bytes
                or row.get("sha256") != expected_sha
                or row.get("row_count") != expected_rows
                or row.get("physical_schema_fingerprint") != expected_schema
                or row.get("row_authority_sha256") != expected_authority
                or row.get("semantic_digest_member") is not True
            ):
                raise IdentityBridgeValidationError("BRIDGE_FILE_AUTHORITY_MISMATCH", "Bridge file declaration differs", logical_uri=uri)
        if observed != [DIMENSION_FILE, "attribution.md", ALIAS_FILE, SOURCE_RIGHTS_FILE]:
            raise IdentityBridgeValidationError("BRIDGE_FILE_ORDER_MISMATCH", "Semantic bridge file order differs")

        totals = manifest.get("totals")
        expected_totals = {
            "active_player_rows": EXPECTED_ACTIVE_PLAYER_ROWS,
            "alias_authority_sha256": ALIAS_AUTHORITY_SHA,
            "alias_rows": EXPECTED_ALIAS_ROWS,
            "dimension_authority_sha256": DIMENSION_AUTHORITY_SHA,
            "final_package_file_count": EXPECTED_PACKAGE_FILES,
            "join_contract_count": EXPECTED_JOIN_CONTRACTS,
            "join_validation_count": EXPECTED_JOIN_CONTRACTS,
            "namespace_count": EXPECTED_NAMESPACE_COUNT,
            "semantic_file_bytes": EXPECTED_SEMANTIC_BYTES,
            "semantic_file_count": EXPECTED_SEMANTIC_FILES,
            "y_minus_1_eligibility_records": EXPECTED_Y_MINUS_1_RECORDS,
        }
        if totals != expected_totals:
            raise IdentityBridgeValidationError("BRIDGE_TOTALS_MISMATCH", "Bridge totals differ from frozen authority")

    @staticmethod
    def _validate_namespaces(manifest: Mapping[str, Any]) -> None:
        rows = manifest.get("identity_namespaces")
        if type(rows) is not list or len(rows) != EXPECTED_NAMESPACE_COUNT:
            raise IdentityBridgeValidationError("NAMESPACE_COUNT_MISMATCH", "Exactly five identity namespaces are required")
        if tuple(row.get("namespace") for row in rows if isinstance(row, dict)) != EXPECTED_NAMESPACES:
            raise IdentityBridgeValidationError("NAMESPACE_ORDER_MISMATCH", "Identity namespaces differ or are reordered")
        for row in rows:
            _require_exact_keys(row, _NAMESPACE_KEYS, code="NAMESPACE_FIELDS_MISMATCH", label="Namespace evidence")
            namespace = row["namespace"]
            source_key, version_id, _identity_sha = EXPECTED_NAMESPACE_SOURCES[namespace]
            expected = {
                "alias_rows": EXPECTED_ALIASES_PER_NAMESPACE,
                "canonical_players": EXPECTED_ACTIVE_PLAYER_ROWS,
                "namespace": namespace,
                "source_keys": [source_key],
                "source_version_ids": [version_id],
                "unique_source_ids": EXPECTED_ALIASES_PER_NAMESPACE,
            }
            if row != expected:
                raise IdentityBridgeValidationError("NAMESPACE_AUTHORITY_MISMATCH", f"Namespace evidence differs: {namespace}")

    @staticmethod
    def _validate_join_contracts(manifest: Mapping[str, Any]) -> None:
        rows = manifest.get("join_contracts")
        if type(rows) is not list or len(rows) != EXPECTED_JOIN_CONTRACTS:
            raise IdentityBridgeValidationError("JOIN_CONTRACT_COUNT_MISMATCH", "Exactly ten join contracts are required")
        ids: list[str] = []
        for row in rows:
            if type(row) is not dict:
                raise IdentityBridgeValidationError("INVALID_JOIN_CONTRACT", "Join contracts must be objects")
            _require_exact_keys(row, _JOIN_CONTRACT_KEYS, code="JOIN_CONTRACT_FIELDS_MISMATCH", label="Join contract")
            contract_id = row.get("join_contract_id")
            if contract_id not in EXPECTED_JOIN_VALIDATION or contract_id in ids:
                raise IdentityBridgeValidationError("JOIN_CONTRACT_ID_MISMATCH", "Join contract identity differs or is duplicated")
            ids.append(contract_id)
            if row.get("null_policy") != "REJECT_NULL_OR_BLANK" or row.get("unresolved_policy") != "FAIL_CLOSED":
                raise IdentityBridgeValidationError("JOIN_FAIL_CLOSED_POLICY_MISMATCH", f"Join contract is not fail-closed: {contract_id}")
            if contract_id.startswith("player_prior."):
                expected = (
                    row.get("join_type") == "EXACT_CANONICAL_UUID"
                    and row.get("duplicate_policy") == "ALLOW_MULTIPLE_PRIOR_ROWS_PER_CANONICAL_UUID"
                    and row.get("target_canonical_field") == "active-player-dimension.canonical_player_uuid"
                )
            else:
                expected = (
                    row.get("join_type") == "EXACT_PARENT_JOIN_KEY_TO_ALIAS"
                    and row.get("namespace") == "RETROSHEET"
                    and row.get("duplicate_policy") == "REQUIRE_ONE_TARGET_PER_NAMESPACE_SOURCE_ID"
                    and row.get("target_canonical_field") == "player-identity-aliases.canonical_player_uuid"
                )
            if not expected:
                raise IdentityBridgeValidationError("JOIN_CONTRACT_SEMANTICS_MISMATCH", f"Join contract semantics differ: {contract_id}")

    @staticmethod
    def _validate_join_validation(value: Any) -> None:
        if type(value) is not list or len(value) != EXPECTED_JOIN_CONTRACTS:
            raise IdentityBridgeValidationError("JOIN_VALIDATION_COUNT_MISMATCH", "Exactly ten join-validation records are required")
        total = 0
        seen: set[str] = set()
        for row in value:
            if type(row) is not dict:
                raise IdentityBridgeValidationError("INVALID_JOIN_VALIDATION", "Join-validation evidence must be objects")
            _require_exact_keys(row, _JOIN_VALIDATION_KEYS, code="JOIN_VALIDATION_FIELDS_MISMATCH", label="Join validation")
            contract_id = row.get("join_contract_id")
            if contract_id not in EXPECTED_JOIN_VALIDATION or contract_id in seen:
                raise IdentityBridgeValidationError("JOIN_VALIDATION_ID_MISMATCH", "Join-validation identity differs or is duplicated")
            seen.add(contract_id)
            expected_count, expected_source_ids, expected_players = EXPECTED_JOIN_VALIDATION[contract_id]
            if (
                row.get("reference_count") != expected_count
                or row.get("resolved_reference_count") != expected_count
                or row.get("unique_source_ids") != expected_source_ids
                or row.get("unique_canonical_players") != expected_players
                or row.get("seasons") != [2021, 2022, 2023, 2024, 2025]
                or row.get("mapping_rate") != 1.0
                or row.get("unresolved_reference_count") != 0
                or row.get("ambiguous_reference_count") != 0
                or row.get("multiply_mapped_reference_count") != 0
            ):
                raise IdentityBridgeValidationError("JOIN_VALIDATION_AUTHORITY_MISMATCH", f"Join validation differs: {contract_id}")
            total += expected_count
        if total != EXPECTED_JOIN_REFERENCES:
            raise IdentityBridgeValidationError("JOIN_REFERENCE_TOTAL_MISMATCH", "Validated join-reference total differs")

    @staticmethod
    def _validate_y_minus_1(value: Any) -> None:
        if type(value) is not list or len(value) != EXPECTED_Y_MINUS_1_RECORDS:
            raise IdentityBridgeValidationError("Y_MINUS_1_COUNT_MISMATCH", "Exactly six Y-minus-1 records are required")
        seen: set[tuple[int, str]] = set()
        for row in value:
            if type(row) is not dict:
                raise IdentityBridgeValidationError("INVALID_Y_MINUS_1_RECORD", "Y-minus-1 evidence must be objects")
            _require_exact_keys(row, _Y_MINUS_1_KEYS, code="Y_MINUS_1_FIELDS_MISMATCH", label="Y-minus-1 evidence")
            key = (row.get("target_season"), row.get("role"))
            if key not in EXPECTED_Y_MINUS_1 or key in seen:
                raise IdentityBridgeValidationError("Y_MINUS_1_IDENTITY_MISMATCH", "Y-minus-1 record identity differs or is duplicated")
            seen.add(key)
            references, eligible, missing, maximum = EXPECTED_Y_MINUS_1[key]
            if (
                row.get("reference_rows") != references
                or row.get("rows_with_eligible_prior") != eligible
                or row.get("legitimate_missing_prior_rows") != missing
                or row.get("maximum_eligible_prior_season") != maximum
                or row.get("eligible_prior_rate") != eligible / references
                or row.get("unresolved_identity_rows") != 0
                or row.get("ambiguous_identity_rows") != 0
                or row.get("multiply_mapped_identity_rows") != 0
            ):
                raise IdentityBridgeValidationError("Y_MINUS_1_AUTHORITY_MISMATCH", f"Y-minus-1 evidence differs: {key}")

    @staticmethod
    def _validate_rights_projection(manifest: Mapping[str, Any]) -> None:
        rights = manifest.get("source_rights")
        if type(rights) is not dict:
            raise IdentityBridgeValidationError("RIGHTS_PROJECTION_MISSING", "Bridge rights projection is required")
        if (
            rights.get("allowed_purposes") != list(ALLOWED_PURPOSES)
            or rights.get("prohibited_purposes") != list(PROHIBITED_PURPOSES)
            or rights.get("rights_control_ids") != list(RIGHTS_CONTROL_IDS)
            or rights.get("legal_conclusion") != "NO_NEW_LEGAL_CONCLUSIONS"
            or any(
                rights.get(key) is not False
                for key in (
                    "identity_data_resale_authorized",
                    "public_raw_bridge_download_authorized",
                    "public_raw_redistribution_authorized",
                    "unrestricted_commercial_redistribution_authorized",
                )
            )
        ):
            raise IdentityBridgeValidationError("RIGHTS_PROJECTION_MISMATCH", "Bridge rights projection differs")

    @staticmethod
    def _validate_one_player_limitation(manifest: Mapping[str, Any]) -> None:
        limitations = manifest.get("limitations")
        if type(limitations) is not list or len(limitations) != len(EXPECTED_LIMITATION_IDS):
            raise IdentityBridgeValidationError("LIMITATION_COUNT_MISMATCH", "Bridge limitation count differs")
        ids: list[str] = []
        for limitation in limitations:
            if type(limitation) is not dict:
                raise IdentityBridgeValidationError("INVALID_LIMITATION", "Bridge limitations must be objects")
            _require_exact_keys(limitation, _LIMITATION_KEYS, code="LIMITATION_FIELDS_MISMATCH", label="Bridge limitation")
            ids.append(str(limitation.get("limitation_id")))
        if tuple(ids) != EXPECTED_LIMITATION_IDS:
            raise IdentityBridgeValidationError("LIMITATION_ID_MISMATCH", "Bridge limitation identities differ")
        coverage = manifest.get("coverage_evidence")
        required = {
            "active_unique_players_2021_2025": EXPECTED_GOVERNED_ACTIVE_PLAYERS,
            "portable_parent_unique_players_2021_2025": EXPECTED_ACTIVE_PLAYER_ROWS,
            "primary_unique_players_2023_2025": EXPECTED_PRIMARY_GOVERNED_PLAYERS,
            "portable_parent_unique_players_2023_2025": EXPECTED_PRIMARY_PORTABLE_PLAYERS,
            "unrepresented_governed_players_2021_2025": 1,
            "unrepresented_governed_players_2023_2025": 1,
            "downstream_impacted_rows": 0,
            "exact_reference_rate_2021_2025": 1.0,
            "exact_reference_rate_2023_2025": 1.0,
        }
        if type(coverage) is not dict or any(coverage.get(key) != expected for key, expected in required.items()):
            raise IdentityBridgeValidationError("ONE_PLAYER_LIMITATION_MISMATCH", "One-player portable limitation lacks exact zero-impact evidence")

    @staticmethod
    def _validate_source_boundary(manifest: Mapping[str, Any]) -> None:
        lineage = manifest.get("source_lineage")
        if type(lineage) is not dict:
            raise IdentityBridgeValidationError("SOURCE_LINEAGE_MISSING", "Source lineage is required")
        if (
            lineage.get("database_transaction_mode") != "READ_ONLY"
            or lineage.get("database_writes") != 0
            or lineage.get("external_network_calls") != 0
            or lineage.get("provider_network_calls") != 0
        ):
            raise IdentityBridgeValidationError("SOURCE_BOUNDARY_MISMATCH", "Bridge source-boundary evidence differs")
        for artifact in lineage.get("evidence_artifacts") or []:
            if type(artifact) is not dict:
                raise IdentityBridgeValidationError("INVALID_LINEAGE_ARTIFACT", "Lineage artifacts must be objects")
            validate_package_relative_uri(artifact.get("logical_uri"))

    def _inventory(self) -> dict[str, Path]:
        if not self.package_root.is_dir():
            raise IdentityBridgeValidationError("BRIDGE_PACKAGE_UNAVAILABLE", "Approved identity-bridge package is unavailable")
        root = self.package_root.resolve(strict=True)
        found: dict[str, Path] = {}
        for current, directories, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            if current_path != root:
                raise IdentityBridgeValidationError("UNDECLARED_DIRECTORY", "Identity-bridge package must be flat")
            for name in directories:
                child = current_path / name
                relative = child.relative_to(root).as_posix()
                if child.is_symlink() or _is_reparse_point(child):
                    raise IdentityBridgeValidationError("LINK_ESCAPE_RISK", "Symlink or junction directory rejected", logical_uri=relative)
                raise IdentityBridgeValidationError("UNDECLARED_DIRECTORY", "Undeclared package directory rejected", logical_uri=relative)
            for name in files:
                child = current_path / name
                relative = child.relative_to(root).as_posix()
                validate_package_relative_uri(relative)
                found[relative] = _validate_resolved_child(root, child, logical_uri=relative)
        if set(found) != set(EXPECTED_FILES) or len(found) != EXPECTED_PACKAGE_FILES:
            raise IdentityBridgeValidationError(
                "BRIDGE_FILE_INVENTORY_MISMATCH",
                f"Bridge inventory differs (missing={sorted(set(EXPECTED_FILES) - set(found))}, undeclared={sorted(set(found) - set(EXPECTED_FILES))})",
            )
        return found

    @staticmethod
    def _validate_file_hashes(inventory: Mapping[str, Path]) -> None:
        total_bytes = 0
        for logical_uri, (expected_bytes, expected_sha) in EXPECTED_FILES.items():
            path = inventory[logical_uri]
            actual_bytes = path.stat().st_size
            total_bytes += actual_bytes
            if actual_bytes != expected_bytes or sha256_file(path, logical_uri=logical_uri) != expected_sha:
                raise IdentityBridgeValidationError("BRIDGE_FILE_HASH_MISMATCH", "Bridge file bytes or SHA-256 differ", logical_uri=logical_uri)
        if total_bytes != EXPECTED_PACKAGE_BYTES:
            raise IdentityBridgeValidationError("BRIDGE_PACKAGE_BYTE_COUNT_MISMATCH", "Bridge package byte count differs")

    @staticmethod
    def _validate_source_rights(rights: Mapping[str, Any]) -> None:
        _require_exact_keys(rights, _RIGHTS_KEYS, code="RIGHTS_FIELDS_MISMATCH", label="Bridge source rights")
        if (
            rights.get("schema_version") != "SPORTS_IDENTITY_BRIDGE_SOURCE_RIGHTS_V1"
            or rights.get("parent_schema_version") != "SPORTS_DATASET_SOURCE_RIGHTS_V1"
            or rights.get("record_count") != len(RIGHTS_CONTROL_IDS)
            or rights.get("package_allowed_purposes") != list(ALLOWED_PURPOSES)
            or rights.get("package_prohibited_purposes") != list(PROHIBITED_PURPOSES)
            or tuple(row.get("rights_control_id") for row in rights.get("records") or []) != RIGHTS_CONTROL_IDS
        ):
            raise IdentityBridgeValidationError("RIGHTS_AUTHORITY_MISMATCH", "Bridge source-right authority differs")
        controls = rights.get("package_controls") or {}
        if controls != {
            "legal_conclusion": "NO_NEW_LEGAL_CONCLUSIONS",
            "public_redistribution_authorized": False,
            "raw_redistribution_authorized": False,
            "unreviewed_commercial_redistribution_authorized": False,
        }:
            raise IdentityBridgeValidationError("RIGHTS_CONTROL_MISMATCH", "Bridge source-right controls differ")
        _scan_json_security(rights)

    @staticmethod
    def _validate_report(report: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        _require_exact_keys(report, _REPORT_KEYS, code="VALIDATION_REPORT_FIELDS_MISMATCH", label="Bridge validation report")
        if (
            report.get("schema_version") != "SPORTS_IDENTITY_BRIDGE_VALIDATION_REPORT_V1"
            or report.get("status") != "PASS"
            or report.get("contract_name") != CONTRACT_NAME
            or report.get("contract_version") != CONTRACT_VERSION
            or report.get("bridge_manifest_id") != BRIDGE_MANIFEST_ID
            or report.get("bridge_manifest_sha256") != BRIDGE_MANIFEST_SHA
            or report.get("bridge_package_id") != BRIDGE_PACKAGE_ID
            or report.get("parent_dataset_manifest_sha256") != PARENT_MANIFEST_SHA
            or report.get("parent_partition_authority_sha256") != PARENT_PARTITION_AUTHORITY_SHA
        ):
            raise IdentityBridgeValidationError("VALIDATION_REPORT_IDENTITY_MISMATCH", "Bridge validation-report identity differs")
        expected_counts = {
            "active_player_rows": EXPECTED_ACTIVE_PLAYER_ROWS,
            "alias_rows": EXPECTED_ALIAS_ROWS,
            "final_package_files": EXPECTED_PACKAGE_FILES,
            "join_contracts": EXPECTED_JOIN_CONTRACTS,
            "join_references": EXPECTED_JOIN_REFERENCES,
            "namespaces": EXPECTED_NAMESPACE_COUNT,
            "parent_player_prior_rows": 21_823,
            "parent_retrosheet_players": EXPECTED_ACTIVE_PLAYER_ROWS,
            "semantic_files": EXPECTED_SEMANTIC_FILES,
            "y_minus_1_records": EXPECTED_Y_MINUS_1_RECORDS,
        }
        if report.get("counts") != expected_counts or any(value is not True for value in (report.get("checks") or {}).values()):
            raise IdentityBridgeValidationError("VALIDATION_REPORT_CHECK_MISMATCH", "Bridge validation-report checks or counts differ")
        authorities = report.get("authorities") or {}
        if authorities != {
            "alias_file_sha256": ALIAS_FILE_SHA,
            "alias_row_authority_sha256": ALIAS_AUTHORITY_SHA,
            "alias_schema_fingerprint": ALIAS_SCHEMA_FINGERPRINT,
            "dimension_file_sha256": DIMENSION_FILE_SHA,
            "dimension_row_authority_sha256": DIMENSION_AUTHORITY_SHA,
            "dimension_schema_fingerprint": DIMENSION_SCHEMA_FINGERPRINT,
        }:
            raise IdentityBridgeValidationError("VALIDATION_REPORT_AUTHORITY_MISMATCH", "Bridge validation-report authorities differ")
        if report.get("identity_namespaces") != manifest.get("identity_namespaces"):
            raise IdentityBridgeValidationError("VALIDATION_REPORT_NAMESPACE_MISMATCH", "Bridge namespace evidence does not reconcile")
        if report.get("join_validation") != manifest.get("join_validation"):
            raise IdentityBridgeValidationError("VALIDATION_REPORT_JOIN_MISMATCH", "Bridge join evidence does not reconcile")
        if report.get("y_minus_1_prior_eligibility") != manifest.get("y_minus_1_prior_eligibility"):
            raise IdentityBridgeValidationError("VALIDATION_REPORT_Y_MINUS_1_MISMATCH", "Bridge Y-minus-1 evidence does not reconcile")
        _scan_json_security(report)

    @staticmethod
    def _validate_row_sha(row: Mapping[str, Any], *, logical_uri: str) -> None:
        claimed = row.get("row_sha256")
        if type(claimed) is not str or not _SHA_RE.fullmatch(claimed):
            raise IdentityBridgeValidationError("ROW_SHA_INVALID", "Bridge row SHA-256 is invalid", logical_uri=logical_uri)
        semantic = dict(row)
        del semantic["row_sha256"]
        if sha256_bytes(canonical_json_bytes(semantic)) != claimed:
            raise IdentityBridgeValidationError("ROW_SHA_MISMATCH", "Bridge row SHA-256 differs", logical_uri=logical_uri)

    @classmethod
    def _validate_alias_rows(cls, rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
        materialized = tuple(dict(row) for row in rows)
        if len(materialized) != EXPECTED_ALIAS_ROWS:
            raise IdentityBridgeValidationError("ALIAS_ROW_COUNT_MISMATCH", "Alias row count differs")
        if list(materialized) != sorted(materialized, key=lambda row: (row["namespace"], row["source_player_id"], row["canonical_player_uuid"])):
            raise IdentityBridgeValidationError("ALIAS_SORT_MISMATCH", "Alias rows are not canonically sorted")
        natural_keys: set[tuple[str, str]] = set()
        canonical_namespaces: dict[str, set[str]] = defaultdict(set)
        namespace_counts: Counter[str] = Counter()
        primary_by_uuid: dict[str, bool] = {}
        for row in materialized:
            cls._validate_row_sha(row, logical_uri=ALIAS_FILE)
            uuid = row.get("canonical_player_uuid")
            namespace = row.get("namespace")
            source_id = row.get("source_player_id")
            if type(uuid) is not str or not _UUID_RE.fullmatch(uuid):
                raise IdentityBridgeValidationError("ALIAS_UUID_INVALID", "Alias canonical UUID is invalid")
            if namespace not in EXPECTED_NAMESPACES:
                raise IdentityBridgeValidationError("ALIAS_NAMESPACE_MISMATCH", "Alias namespace differs")
            if type(source_id) is not str or not source_id or source_id != source_id.strip():
                raise IdentityBridgeValidationError("ALIAS_SOURCE_ID_INVALID", "Alias source ID is blank or non-canonical")
            natural_key = (namespace, source_id)
            if natural_key in natural_keys:
                raise IdentityBridgeValidationError("ALIAS_NATURAL_KEY_CONFLICT", "Alias natural key is duplicated")
            natural_keys.add(natural_key)
            canonical_namespaces[uuid].add(namespace)
            namespace_counts[namespace] += 1
            source_key, version_id, version_sha = EXPECTED_NAMESPACE_SOURCES[namespace]
            if (
                row.get("source_key") != source_key
                or row.get("source_version_id") != version_id
                or row.get("source_version_identity_sha256") != version_sha
                or row.get("mapping_confidence") != "EXACT"
                or row.get("mapping_status") != "RESOLVED"
                or row.get("mapping_basis") != "EXPLICIT_IDENTIFIER_EXACT"
            ):
                raise IdentityBridgeValidationError("ALIAS_SOURCE_BINDING_MISMATCH", "Alias source-version or exact-mapping authority differs")
            join_key = row.get("parent_join_key")
            expected_join_key = f"retrosheet:player:{source_id}" if namespace == "RETROSHEET" else source_id if namespace == "LAHMAN" else None
            if join_key != expected_join_key:
                raise IdentityBridgeValidationError("ALIAS_PARENT_JOIN_KEY_MISMATCH", "Stored parent join key differs from exact namespace authority")
            if row.get("source_row_identity") != f"sha256:{row.get('source_row_sha256')}":
                raise IdentityBridgeValidationError("ALIAS_SOURCE_ROW_IDENTITY_MISMATCH", "Alias source-row identity differs")
            validate_package_relative_uri(row.get("evidence_logical_uri"))
            current_primary = row.get("primary_2023_2025")
            if type(current_primary) is not bool:
                raise IdentityBridgeValidationError("ALIAS_PRIMARY_FLAG_INVALID", "Alias primary flag must be boolean")
            if uuid in primary_by_uuid and primary_by_uuid[uuid] is not current_primary:
                raise IdentityBridgeValidationError("ALIAS_PRIMARY_FLAG_CONFLICT", "Alias primary flag conflicts within a canonical UUID")
            primary_by_uuid[uuid] = current_primary
        if set(namespace_counts) != set(EXPECTED_NAMESPACES) or any(namespace_counts[item] != EXPECTED_ALIASES_PER_NAMESPACE for item in EXPECTED_NAMESPACES):
            raise IdentityBridgeValidationError("ALIAS_NAMESPACE_COVERAGE_MISMATCH", "Alias namespace coverage differs")
        if len(canonical_namespaces) != EXPECTED_ACTIVE_PLAYER_ROWS or any(namespaces != set(EXPECTED_NAMESPACES) for namespaces in canonical_namespaces.values()):
            raise IdentityBridgeValidationError("ALIAS_CANONICAL_COVERAGE_MISMATCH", "Each canonical player must have exactly five namespace aliases")
        if sha256_bytes(canonical_json_bytes(list(materialized))) != ALIAS_AUTHORITY_SHA:
            raise IdentityBridgeValidationError("ALIAS_ROW_AUTHORITY_MISMATCH", "Alias row-authority SHA-256 differs")
        return materialized

    @classmethod
    def _validate_dimension_rows(cls, rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
        materialized = tuple(dict(row) for row in rows)
        if len(materialized) != EXPECTED_ACTIVE_PLAYER_ROWS:
            raise IdentityBridgeValidationError("DIMENSION_ROW_COUNT_MISMATCH", "Active-player dimension row count differs")
        if list(materialized) != sorted(materialized, key=lambda row: row["canonical_player_uuid"]):
            raise IdentityBridgeValidationError("DIMENSION_SORT_MISMATCH", "Dimension rows are not canonically sorted")
        uuids: set[str] = set()
        primary_count = 0
        for row in materialized:
            cls._validate_row_sha(row, logical_uri=DIMENSION_FILE)
            uuid = row.get("canonical_player_uuid")
            if type(uuid) is not str or not _UUID_RE.fullmatch(uuid):
                raise IdentityBridgeValidationError("DIMENSION_UUID_INVALID", "Dimension canonical UUID is invalid")
            if uuid in uuids:
                raise IdentityBridgeValidationError("DIMENSION_UUID_CONFLICT", "Dimension canonical UUID is duplicated")
            uuids.add(uuid)
            if any(row.get(field) is not True for field in (
                "has_retrosheet_alias",
                "has_lahman_alias",
                "has_chadwick_alias",
                "has_mlbam_alias",
                "has_baseball_reference_alias",
                "has_player_prior",
            )):
                raise IdentityBridgeValidationError("DIMENSION_COVERAGE_FLAG_MISMATCH", "Dimension alias/prior coverage flag differs")
            if row.get("primary_active_2023_2025") is True:
                primary_count += 1
            for field in ("batter_reference_count", "pitcher_reference_count", "other_player_reference_count", "player_prior_row_count"):
                if type(row.get(field)) is not int or row[field] < 0:
                    raise IdentityBridgeValidationError("DIMENSION_COUNT_INVALID", "Dimension reference counts must be non-negative integers")
        if primary_count != EXPECTED_PRIMARY_PORTABLE_PLAYERS:
            raise IdentityBridgeValidationError("DIMENSION_PRIMARY_COUNT_MISMATCH", "Portable primary-player count differs")
        if sha256_bytes(canonical_json_bytes(list(materialized))) != DIMENSION_AUTHORITY_SHA:
            raise IdentityBridgeValidationError("DIMENSION_ROW_AUTHORITY_MISMATCH", "Dimension row-authority SHA-256 differs")
        return materialized

    @staticmethod
    def _validate_parquet(
        path: Path,
        *,
        logical_uri: str,
        expected_schema: tuple[tuple[str, str], ...],
        expected_fingerprint: str,
        expected_rows: int,
    ) -> list[dict[str, Any]]:
        physical_schema, row_count = parquet_physical_schema(path, logical_uri=logical_uri)
        expected_projection = [{"name": name, "dtype": dtype} for name, dtype in expected_schema]
        if physical_schema != expected_projection or row_count != expected_rows:
            raise IdentityBridgeValidationError("BRIDGE_PARQUET_SCHEMA_MISMATCH", "Bridge Parquet ordered schema or row count differs", logical_uri=logical_uri)
        if sha256_bytes(canonical_json_bytes(physical_schema)) != expected_fingerprint:
            raise IdentityBridgeValidationError("BRIDGE_PARQUET_FINGERPRINT_MISMATCH", "Bridge Parquet schema fingerprint differs", logical_uri=logical_uri)
        try:
            return pq.read_table(path, use_threads=False).to_pylist()
        except Exception as exc:
            raise IdentityBridgeValidationError("BRIDGE_PARQUET_READ_FAILED", "Bridge Parquet rows could not be read", logical_uri=logical_uri) from exc

    @staticmethod
    def _reconcile_alias_dimension(alias_rows: Iterable[Mapping[str, Any]], dimension_rows: Iterable[Mapping[str, Any]]) -> None:
        aliases = list(alias_rows)
        dimensions = {str(row["canonical_player_uuid"]): row for row in dimension_rows}
        alias_uuids = {str(row["canonical_player_uuid"]) for row in aliases}
        if alias_uuids != set(dimensions):
            raise IdentityBridgeValidationError("ALIAS_DIMENSION_UUID_MISMATCH", "Alias and dimension canonical UUID populations differ")
        primary_aliases = {
            str(row["canonical_player_uuid"])
            for row in aliases
            if row["primary_2023_2025"] is True
        }
        primary_dimension = {
            uuid for uuid, row in dimensions.items() if row["primary_active_2023_2025"] is True
        }
        if primary_aliases != primary_dimension or len(primary_dimension) != EXPECTED_PRIMARY_PORTABLE_PLAYERS:
            raise IdentityBridgeValidationError("ALIAS_DIMENSION_PRIMARY_MISMATCH", "Alias and dimension primary populations differ")

    def validate(self) -> ValidatedIdentityBridge:
        if self.__class__ is SportsIdentityBridgeV1Consumer:
            adapter = MlbFd1IdentityBridgeAdapter(
                self.package_root,
                progress=self.progress,
            )
            adapter._started = self._started
            return adapter.validate()
        self._emit("VALIDATING_BRIDGE_MANIFEST")
        reject_reparse_chain(raw_absolute_path(self.package_root), label="Configured identity-bridge root chain")
        root_identity = filesystem_identity(self.package_root)
        manifest = load_strict_json(self.package_root / MANIFEST_FILE, logical_uri=MANIFEST_FILE)
        self.validate_manifest_contract(manifest)
        inventory = self._inventory()
        self._emit("VALIDATING_BRIDGE_FILES", files=1)
        self._validate_file_hashes(inventory)
        if sha256_file(inventory[MANIFEST_FILE], logical_uri=MANIFEST_FILE) != MANIFEST_FILE_SHA:
            raise IdentityBridgeValidationError("BRIDGE_MANIFEST_FILE_HASH_MISMATCH", "Bridge manifest file SHA-256 differs")

        source_rights = load_strict_json(inventory[SOURCE_RIGHTS_FILE], logical_uri=SOURCE_RIGHTS_FILE)
        validation_report = load_strict_json(inventory[VALIDATION_REPORT_FILE], logical_uri=VALIDATION_REPORT_FILE)
        self._validate_source_rights(source_rights)
        self._validate_report(validation_report, manifest)

        try:
            readme = inventory["README.md"].read_bytes().decode("utf-8", errors="strict")
            attribution = inventory["attribution.md"].read_bytes().decode("utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            raise IdentityBridgeValidationError("BRIDGE_MARKDOWN_INVALID", "Bridge markdown must be strict UTF-8") from exc
        if f"validation-report-sha256: `{VALIDATION_REPORT_SHA}`" not in readme:
            raise IdentityBridgeValidationError("README_REPORT_BINDING_MISMATCH", "Bridge README does not bind the validation report")
        for text, label in ((readme, "README.md"), (attribution, "attribution.md")):
            if _WINDOWS_ABSOLUTE_RE.search(text) or "file://" in text.casefold():
                raise IdentityBridgeValidationError("BRIDGE_MARKDOWN_PATH_REJECTED", "Physical path rejected", logical_uri=label)
        if sha256_file(inventory["README.md"], logical_uri="README.md") != README_SHA:
            raise IdentityBridgeValidationError("README_HASH_MISMATCH", "Bridge README SHA-256 differs")

        self._emit("VALIDATING_ALIAS_ROWS", files=EXPECTED_PACKAGE_FILES, rows=0)
        alias_raw = self._validate_parquet(
            inventory[ALIAS_FILE],
            logical_uri=ALIAS_FILE,
            expected_schema=ALIAS_SCHEMA,
            expected_fingerprint=ALIAS_SCHEMA_FINGERPRINT,
            expected_rows=EXPECTED_ALIAS_ROWS,
        )
        alias_rows = self._validate_alias_rows(alias_raw)
        self._emit("VALIDATING_DIMENSION_ROWS", files=EXPECTED_PACKAGE_FILES, rows=len(alias_rows))
        dimension_raw = self._validate_parquet(
            inventory[DIMENSION_FILE],
            logical_uri=DIMENSION_FILE,
            expected_schema=DIMENSION_SCHEMA,
            expected_fingerprint=DIMENSION_SCHEMA_FINGERPRINT,
            expected_rows=EXPECTED_ACTIVE_PLAYER_ROWS,
        )
        dimension_rows = self._validate_dimension_rows(dimension_raw)
        self._reconcile_alias_dimension(alias_rows, dimension_rows)
        self._emit("BRIDGE_VALID", files=EXPECTED_PACKAGE_FILES, rows=len(alias_rows) + len(dimension_rows))
        return ValidatedIdentityBridge(
            package_root=self.package_root,
            manifest=manifest,
            source_rights=source_rights,
            validation_report=validation_report,
            aliases=alias_rows,
            dimensions=dimension_rows,
            root_identity=root_identity,
            validated_at=_format_utc_now(),
        )


__all__ = [
    "IdentityBridgeValidationError",
    "MlbFd1IdentityBridgeAdapter",
    "SportsIdentityBridgeV1Consumer",
    "ValidatedIdentityBridge",
    "approved_bridge_root",
    "semantic_bridge_manifest_sha",
]
