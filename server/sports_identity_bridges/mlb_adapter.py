from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

import pyarrow.parquet as pq

from ..sports_datasets.constants import EXPECTED_TOTALS as PARENT_EXPECTED_TOTALS
from ..sports_datasets.consumer import (
    SportsDatasetManifestConsumer,
    ValidatedPackage,
    _validate_resolved_child,
    filesystem_identity,
    raw_absolute_path,
    reject_reparse_chain,
    validate_package_relative_uri,
)
from .constants import (
    BRIDGE_MANIFEST_SHA,
    EXPECTED_ACTIVE_PLAYER_ROWS,
    EXPECTED_ALIAS_ROWS,
    EXPECTED_JOIN_CONTRACTS,
    EXPECTED_JOIN_REFERENCES,
    EXPECTED_JOIN_VALIDATION,
    EXPECTED_PRIMARY_PA_ROWS,
    EXPECTED_Y_MINUS_1,
    PARENT_MANIFEST_SHA,
    PARENT_PARTITION_AUTHORITY_SHA,
)
from .consumer import (
    IdentityBridgeValidationError,
    MlbFd1IdentityBridgeAdapter,
    ProgressCallback,
    ValidatedIdentityBridge,
)


_TARGET_SEASONS = (2023, 2024, 2025)
_ROLE_DOMAIN_FIELDS = (
    ("BATTER", "BATTING", "batter_id"),
    ("PITCHER", "PITCHING", "pitcher_id"),
)


class MLBFD1IdentityAdapter:
    """Execute the frozen MLB FD1 bridge's ten exact parent joins.

    The adapter accepts already validated package authorities and emits only a
    logical, public-safe audit. Artifact persistence and registration remain
    separate concerns.
    """

    def __init__(
        self,
        validated_bridge: ValidatedIdentityBridge,
        validated_parent: ValidatedPackage,
        progress: ProgressCallback | None = None,
        *,
        batch_size: int = 65_536,
    ) -> None:
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        self.bridge = validated_bridge
        self.parent = validated_parent
        self.progress = progress
        self.batch_size = batch_size
        self._started = time.monotonic()
        self._partitions_processed = 0
        self._references_processed = 0
        self._audit_partition_total = 0

    def _emit(self, stage: str, *, errors: int = 0) -> None:
        if self.progress is None:
            return
        self.progress(
            {
                "title": "ASP MODEL STUDIO — MLB IDENTITY JOIN AUDIT",
                "stage": stage,
                "elapsedSeconds": round(time.monotonic() - self._started, 2),
                "partitionsProcessed": self._partitions_processed,
                "partitionsTotal": self._audit_partition_total,
                "referencesProcessed": self._references_processed,
                "referencesTotal": EXPECTED_JOIN_REFERENCES,
                "errors": errors,
                "etaSeconds": None,
            }
        )

    def _validate_bindings(self) -> None:
        if not isinstance(self.bridge, ValidatedIdentityBridge):
            raise IdentityBridgeValidationError(
                "BRIDGE_VALIDATION_REQUIRED",
                "Exact join audit requires a validated identity bridge",
            )
        if not isinstance(self.parent, ValidatedPackage):
            raise IdentityBridgeValidationError(
                "PARENT_VALIDATION_REQUIRED",
                "Exact join audit requires a validated parent dataset",
            )
        MlbFd1IdentityBridgeAdapter.validate_manifest_contract(self.bridge.manifest)
        SportsDatasetManifestConsumer.validate_manifest_contract(self.parent.manifest)
        if self.bridge.manifest.get("bridge_manifest_sha256") != BRIDGE_MANIFEST_SHA:
            raise IdentityBridgeValidationError(
                "BRIDGE_AUDIT_BINDING_MISMATCH",
                "Join audit bridge authority differs",
            )
        if (
            self.parent.manifest.get("manifest_sha256") != PARENT_MANIFEST_SHA
            or self.parent.partition_authority_sha != PARENT_PARTITION_AUTHORITY_SHA
        ):
            raise IdentityBridgeValidationError(
                "PARENT_AUDIT_BINDING_MISMATCH",
                "Join audit parent authority differs",
            )
        if len(self.bridge.aliases) != EXPECTED_ALIAS_ROWS or len(self.bridge.dimensions) != EXPECTED_ACTIVE_PLAYER_ROWS:
            raise IdentityBridgeValidationError(
                "BRIDGE_AUDIT_POPULATION_MISMATCH",
                "Join audit bridge populations differ",
            )

        for package_root, expected_identity, label in (
            (self.bridge.package_root, self.bridge.root_identity, "identity-bridge"),
            (self.parent.package_root, self.parent.root_identity, "parent-dataset"),
        ):
            reject_reparse_chain(raw_absolute_path(package_root), label=f"Configured {label} root chain")
            if filesystem_identity(package_root) != expected_identity:
                raise IdentityBridgeValidationError(
                    "PACKAGE_ROOT_IDENTITY_MISMATCH",
                    f"Validated {label} root identity changed before the join audit",
                )

        partitions = self.parent.partitions
        expected_partition_count = int(PARENT_EXPECTED_TOTALS["parquet_files"])
        if type(partitions) is not list or len(partitions) != expected_partition_count:
            raise IdentityBridgeValidationError(
                "PARENT_PARTITION_COUNT_MISMATCH",
                "Join audit requires the exact 329-partition parent authority",
            )
        uris = [str(item.get("package_relative_uri", "")) for item in partitions if isinstance(item, Mapping)]
        if len(uris) != expected_partition_count or len(set(uris)) != expected_partition_count:
            raise IdentityBridgeValidationError(
                "PARENT_PARTITION_IDENTITY_MISMATCH",
                "Parent partition logical identities differ or are duplicated",
            )

    @staticmethod
    def _alias_targets(bridge: ValidatedIdentityBridge) -> dict[str, frozenset[str]]:
        targets: dict[str, set[str]] = defaultdict(set)
        for row in bridge.aliases:
            if row.get("namespace") == "RETROSHEET":
                key = row.get("parent_join_key")
                canonical = row.get("canonical_player_uuid")
                if type(key) is not str or not key or type(canonical) is not str:
                    raise IdentityBridgeValidationError(
                        "RETROSHEET_ALIAS_KEY_INVALID",
                        "RETROSHEET aliases require exact stored parent join keys",
                    )
                targets[key].add(canonical)
        return {key: frozenset(values) for key, values in targets.items()}

    @staticmethod
    def _resolve_exact(
        value: Any,
        *,
        alias_targets: Mapping[str, frozenset[str]] | None = None,
        dimension_uuids: frozenset[str] | None = None,
    ) -> tuple[str, str | None]:
        """Resolve only the stored key or UUID; never normalize or infer."""

        if type(value) is not str or not value or value != value.strip():
            return "UNRESOLVED", None
        if alias_targets is not None:
            targets = alias_targets.get(value, frozenset())
            if not targets:
                return "UNRESOLVED", None
            if len(targets) != 1:
                return "MULTIPLY_MAPPED", None
            return "RESOLVED", next(iter(targets))
        if dimension_uuids is not None and value in dimension_uuids:
            return "RESOLVED", value
        return "UNRESOLVED", None

    @staticmethod
    def _new_stats(contract: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "contract": dict(contract),
            "reference_count": 0,
            "resolved_count": 0,
            "unresolved_count": 0,
            "ambiguous_count": 0,
            "multiply_mapped_count": 0,
            "source_ids": set(),
            "canonical_players": set(),
            "seasons": set(),
        }

    @staticmethod
    def _record(
        stats: dict[str, Any],
        value: Any,
        season: Any,
        *,
        alias_targets: Mapping[str, frozenset[str]] | None = None,
        dimension_uuids: frozenset[str] | None = None,
    ) -> tuple[str, str | None]:
        stats["reference_count"] += 1
        if type(season) is int:
            stats["seasons"].add(season)
        if type(value) is str:
            stats["source_ids"].add(value)
        resolution, canonical = MLBFD1IdentityAdapter._resolve_exact(
            value,
            alias_targets=alias_targets,
            dimension_uuids=dimension_uuids,
        )
        if resolution == "RESOLVED":
            stats["resolved_count"] += 1
            stats["canonical_players"].add(canonical)
        elif resolution == "MULTIPLY_MAPPED":
            stats["ambiguous_count"] += 1
            stats["multiply_mapped_count"] += 1
        else:
            stats["unresolved_count"] += 1
        return resolution, canonical

    def _safe_partition_path(self, partition: Mapping[str, Any]) -> Path:
        uri = validate_package_relative_uri(partition.get("package_relative_uri"))
        root = self.parent.package_root.resolve(strict=True)
        candidate = root.joinpath(*PurePosixPath(uri).parts)
        return _validate_resolved_child(root, candidate, logical_uri=uri)

    def _scan_partition(
        self,
        partition: Mapping[str, Any],
        contracts: list[Mapping[str, Any]],
        stats_by_id: dict[str, dict[str, Any]],
        alias_targets: Mapping[str, frozenset[str]],
        dimension_uuids: frozenset[str],
        eligible_players: dict[tuple[int, str], set[str]],
        maximum_prior_season: dict[tuple[int, str], int],
        coverage: dict[tuple[int, str], dict[str, int]],
    ) -> None:
        family = str(partition["family"])
        path = self._safe_partition_path(partition)
        fields = [str(item["physical_field_name"]) for item in contracts]
        columns = list(dict.fromkeys([*fields, "season"]))
        if family == "player_prior":
            columns.extend(name for name in ("eligible_from_season", "domain") if name not in columns)
        scanned_rows = 0
        try:
            parquet = pq.ParquetFile(path)
            for batch in parquet.iter_batches(
                batch_size=self.batch_size,
                columns=columns,
                use_threads=False,
            ):
                values = {name: batch.column(name).to_pylist() for name in columns}
                row_count = batch.num_rows
                scanned_rows += row_count
                for index in range(row_count):
                    season = values["season"][index]
                    resolved_by_field: dict[str, tuple[str, str | None]] = {}
                    for contract in contracts:
                        contract_id = str(contract["join_contract_id"])
                        field = str(contract["physical_field_name"])
                        if family == "player_prior":
                            result = self._record(
                                stats_by_id[contract_id],
                                values[field][index],
                                season,
                                dimension_uuids=dimension_uuids,
                            )
                        else:
                            result = self._record(
                                stats_by_id[contract_id],
                                values[field][index],
                                season,
                                alias_targets=alias_targets,
                            )
                        resolved_by_field[field] = result
                        self._references_processed += 1

                    if family == "player_prior":
                        canonical = values[fields[0]][index]
                        eligible_from = values["eligible_from_season"][index]
                        domain = values["domain"][index]
                        if type(season) is not int or type(eligible_from) is not int:
                            raise IdentityBridgeValidationError(
                                "PLAYER_PRIOR_TEMPORAL_FIELD_INVALID",
                                "Player-prior temporal keys must be integers",
                            )
                        if eligible_from <= season:
                            raise IdentityBridgeValidationError(
                                "SAME_SEASON_PRIOR_ELIGIBILITY_REJECTED",
                                "Player-prior evidence may not be eligible in its source season",
                            )
                        if domain in {"BATTING", "PITCHING"}:
                            for target_season in _TARGET_SEASONS:
                                if season <= target_season - 1 and eligible_from <= target_season:
                                    eligible_players[(target_season, domain)].add(str(canonical))
                                    maximum_prior_season[(target_season, domain)] = max(
                                        maximum_prior_season[(target_season, domain)],
                                        season,
                                    )
                    elif family == "plate_appearance" and season in _TARGET_SEASONS:
                        for role, domain, field in _ROLE_DOMAIN_FIELDS:
                            item = coverage[(season, role)]
                            item["reference_rows"] += 1
                            resolution, canonical = resolved_by_field[field]
                            if resolution == "RESOLVED":
                                if canonical in eligible_players[(season, domain)]:
                                    item["rows_with_eligible_prior"] += 1
                                else:
                                    item["legitimate_missing_prior_rows"] += 1
                            elif resolution == "MULTIPLY_MAPPED":
                                item["ambiguous_identity_rows"] += 1
                                item["multiply_mapped_identity_rows"] += 1
                            else:
                                item["unresolved_identity_rows"] += 1
        except IdentityBridgeValidationError:
            raise
        except Exception as exc:
            raise IdentityBridgeValidationError(
                "PARENT_PARTITION_SCAN_FAILED",
                "A registered parent partition could not be scanned",
                logical_uri=str(partition.get("package_relative_uri", "")),
            ) from exc
        if scanned_rows != partition.get("row_count"):
            raise IdentityBridgeValidationError(
                "PARENT_PARTITION_ROW_COUNT_MISMATCH",
                "Scanned parent partition rows differ from its registered authority",
                logical_uri=str(partition.get("package_relative_uri", "")),
            )
        self._partitions_processed += 1
        if self._partitions_processed == 1 or self._partitions_processed % 10 == 0 or self._partitions_processed == self._audit_partition_total:
            self._emit("SCANNING_REGISTERED_PARENT_PARTITIONS")

    @staticmethod
    def _join_projection(stats: Mapping[str, Any]) -> dict[str, Any]:
        contract = stats["contract"]
        references = int(stats["reference_count"])
        resolved = int(stats["resolved_count"])
        return {
            "joinContractId": contract["join_contract_id"],
            "sourceFamily": contract["source_family"],
            "physicalFieldName": contract["physical_field_name"],
            "namespace": contract["namespace"],
            "joinType": contract["join_type"],
            "referenceCount": references,
            "resolvedReferenceCount": resolved,
            "mappingRate": resolved / references if references else 0.0,
            "unresolvedReferenceCount": int(stats["unresolved_count"]),
            "ambiguousReferenceCount": int(stats["ambiguous_count"]),
            "multiplyMappedReferenceCount": int(stats["multiply_mapped_count"]),
            "uniqueSourceIds": len(stats["source_ids"]),
            "uniqueCanonicalPlayers": len(stats["canonical_players"]),
            "seasons": sorted(stats["seasons"]),
        }

    @staticmethod
    def _assert_join_authority(joins: list[Mapping[str, Any]]) -> None:
        if len(joins) != EXPECTED_JOIN_CONTRACTS:
            raise IdentityBridgeValidationError(
                "JOIN_AUDIT_CONTRACT_COUNT_MISMATCH",
                "Exact join audit did not execute all ten contracts",
            )
        total = 0
        for row in joins:
            contract_id = str(row["joinContractId"])
            expected = EXPECTED_JOIN_VALIDATION.get(contract_id)
            if expected is None:
                raise IdentityBridgeValidationError(
                    "JOIN_AUDIT_CONTRACT_ID_MISMATCH",
                    "Exact join audit produced an unknown contract",
                )
            references, unique_source_ids, unique_players = expected
            if (
                row["referenceCount"] != references
                or row["resolvedReferenceCount"] != references
                or row["mappingRate"] != 1.0
                or row["unresolvedReferenceCount"] != 0
                or row["ambiguousReferenceCount"] != 0
                or row["multiplyMappedReferenceCount"] != 0
                or row["uniqueSourceIds"] != unique_source_ids
                or row["uniqueCanonicalPlayers"] != unique_players
                or row["seasons"] != [2021, 2022, 2023, 2024, 2025]
            ):
                raise IdentityBridgeValidationError(
                    "JOIN_AUDIT_AUTHORITY_MISMATCH",
                    f"Exact join evidence differs for {contract_id}",
                )
            total += references
        if total != EXPECTED_JOIN_REFERENCES:
            raise IdentityBridgeValidationError(
                "JOIN_AUDIT_REFERENCE_TOTAL_MISMATCH",
                "Exact join reference total differs",
            )

    @staticmethod
    def _coverage_projection(
        coverage: Mapping[tuple[int, str], Mapping[str, int]],
        maximum_prior_season: Mapping[tuple[int, str], int],
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for target_season in _TARGET_SEASONS:
            for role, domain, _field in _ROLE_DOMAIN_FIELDS:
                raw = coverage[(target_season, role)]
                references, eligible, missing, maximum = EXPECTED_Y_MINUS_1[(target_season, role)]
                if (
                    raw["reference_rows"] != references
                    or raw["rows_with_eligible_prior"] != eligible
                    or raw["legitimate_missing_prior_rows"] != missing
                    or raw["unresolved_identity_rows"] != 0
                    or raw["ambiguous_identity_rows"] != 0
                    or raw["multiply_mapped_identity_rows"] != 0
                    or maximum_prior_season[(target_season, domain)] != maximum
                    or references != EXPECTED_PRIMARY_PA_ROWS[target_season]
                ):
                    raise IdentityBridgeValidationError(
                        "Y_MINUS_1_AUDIT_AUTHORITY_MISMATCH",
                        f"Exact Y-minus-one evidence differs for {target_season} {role}",
                    )
                output.append(
                    {
                        "targetSeason": target_season,
                        "role": role,
                        "referenceRows": references,
                        "rowsWithEligiblePrior": eligible,
                        "legitimateMissingPriorRows": missing,
                        "eligiblePriorRate": eligible / references,
                        "unresolvedIdentityRows": 0,
                        "ambiguousIdentityRows": 0,
                        "multiplyMappedIdentityRows": 0,
                        "maximumEligiblePriorSeason": maximum,
                    }
                )
        return output

    def build_join_audit(self) -> dict[str, Any]:
        self._emit("VALIDATING_JOIN_AUDIT_BINDINGS")
        self._validate_bindings()
        contracts = [dict(item) for item in self.bridge.manifest["join_contracts"]]
        stats_by_id = {
            str(contract["join_contract_id"]): self._new_stats(contract)
            for contract in contracts
        }
        contracts_by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for contract in contracts:
            contracts_by_family[str(contract["source_family"])].append(contract)

        alias_targets = self._alias_targets(self.bridge)
        dimension_uuids = self.bridge.dimension_uuids
        eligible_players = {
            (season, domain): set()
            for season in _TARGET_SEASONS
            for domain in ("BATTING", "PITCHING")
        }
        maximum_prior_season = {
            (season, domain): 0
            for season in _TARGET_SEASONS
            for domain in ("BATTING", "PITCHING")
        }
        coverage = {
            (season, role): {
                "reference_rows": 0,
                "rows_with_eligible_prior": 0,
                "legitimate_missing_prior_rows": 0,
                "unresolved_identity_rows": 0,
                "ambiguous_identity_rows": 0,
                "multiply_mapped_identity_rows": 0,
            }
            for season in _TARGET_SEASONS
            for role, _domain, _field in _ROLE_DOMAIN_FIELDS
        }

        relevant = [
            item
            for item in self.parent.partitions
            if item.get("family") in contracts_by_family
        ]
        prior = [item for item in relevant if item.get("family") == "player_prior"]
        remaining = [item for item in relevant if item.get("family") != "player_prior"]
        self._audit_partition_total = len(relevant)
        self._emit("SCANNING_REGISTERED_PARENT_PARTITIONS")
        for partition in [*prior, *remaining]:
            family = str(partition["family"])
            self._scan_partition(
                partition,
                contracts_by_family[family],
                stats_by_id,
                alias_targets,
                dimension_uuids,
                eligible_players,
                maximum_prior_season,
                coverage,
            )

        joins = [
            self._join_projection(stats_by_id[str(contract["join_contract_id"])])
            for contract in contracts
        ]
        self._assert_join_authority(joins)
        y_minus_one = self._coverage_projection(coverage, maximum_prior_season)
        total_references = sum(int(item["referenceCount"]) for item in joins)
        resolved_references = sum(int(item["resolvedReferenceCount"]) for item in joins)
        audit = {
            "status": "PASS",
            "parentManifestSha": PARENT_MANIFEST_SHA,
            "parentPartitionAuthoritySha": PARENT_PARTITION_AUTHORITY_SHA,
            "bridgeManifestSha": BRIDGE_MANIFEST_SHA,
            "totalReferences": total_references,
            "resolvedReferences": resolved_references,
            "mappingRate": resolved_references / total_references,
            "unresolvedReferences": sum(int(item["unresolvedReferenceCount"]) for item in joins),
            "ambiguousReferences": sum(int(item["ambiguousReferenceCount"]) for item in joins),
            "multiplyMappedReferences": sum(int(item["multiplyMappedReferenceCount"]) for item in joins),
            "joins": joins,
            "yMinus1Coverage": y_minus_one,
            "noNamesOrFuzzyMatching": True,
        }
        self._emit("JOIN_AUDIT_PASS")
        return audit


__all__ = ["MLBFD1IdentityAdapter"]
