from __future__ import annotations

from contextlib import contextmanager
import gc
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Iterator
import uuid

import pytest

from server.bureau_metadata.restricted_storage import (
    RestrictedStorageConfigurationError,
)
from scripts import run_bureau_metadata_operational_soak as soak


@contextmanager
def _durable_test_root() -> Iterator[Path]:
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA")
        or (Path.home() / "AppData" / "Local")
    )
    parent = local_app_data / "ATLAS-Codex-Synthetic-TestAuthorities"
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / ("catalog-soak-test-" + uuid.uuid4().hex)
    root.mkdir(parents=False, exist_ok=False)
    try:
        yield root.resolve(strict=True)
    finally:
        gc.collect()
        exact = root.resolve(strict=False)
        if exact.parent != parent.resolve(strict=True):
            raise AssertionError("Synthetic test-root cleanup escaped its authority.")
        shutil.rmtree(exact)


@contextmanager
def _temporary_test_root(prefix: str) -> Iterator[Path]:
    """Create a test root without pytest/tempfile owner-only Windows ACLs."""

    hermetic_root = os.environ.get("ATLAS_HERMETIC_ROOT")
    if not hermetic_root:
        with tempfile.TemporaryDirectory(prefix=prefix) as raw:
            yield Path(raw)
        return
    parent = Path(hermetic_root) / "authorities" / "temporary-tests"
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / (prefix + uuid.uuid4().hex)
    root.mkdir(exist_ok=False)
    try:
        yield root.resolve(strict=True)
    finally:
        gc.collect()
        shutil.rmtree(root)


@contextmanager
def _windows_temp_test_root(prefix: str) -> Iterator[Path]:
    """Create an inherited-ACL child of the process's exact Temp authority."""

    parent = Path(tempfile.gettempdir()).resolve(strict=True)
    root = parent / (prefix + uuid.uuid4().hex)
    root.mkdir(exist_ok=False)
    try:
        yield root.resolve(strict=True)
    finally:
        gc.collect()
        shutil.rmtree(root)


def _mini_settings(root: Path) -> soak.SoakSettings:
    return soak.SoakSettings(
        root=root,
        duration_seconds=0,
        user_count=4,
        project_count=2,
        catalog_version_count=2,
        bounded_operation_count=40,
        crosswalk_preview_count=12,
        decision_write_count=8,
        service_reload_count=2,
        unauthorized_attempt_count=8,
        conflict_trial_count=2,
        max_workers=4,
        heartbeat_seconds=0.01,
        enforce_release_minimums=False,
    )


def _write_frontend_reload_evidence(
    evidence_root: Path,
    *,
    frontend_port: int = 5274,
    backend_port: int = 8101,
    reloads: int = 10,
) -> Path:
    evidence_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "classification": soak.FRONTEND_RELOAD_EVIDENCE_CLASSIFICATION,
        "run_id": "synthetic-frontend-reload-test",
        "created_at": "2026-08-05T00:00:00Z",
        "frontend_origin": f"http://127.0.0.1:{frontend_port}",
        "backend_origin": f"http://127.0.0.1:{backend_port}",
        "authenticated_reload_attempts": reloads,
        "authenticated_reload_successes": reloads,
        "synthetic_user_count": 2,
        "synthetic_project_count": 2,
        "synthetic_provider_count": 2,
        "authentication_failures": 0,
        "unexpected_failures": 0,
        "cross_user_contamination": 0,
        "cross_project_contamination": 0,
        "cross_provider_contamination": 0,
        "browser_profile_isolated": True,
        "contains_vendor_content": False,
        "live_authority_accessed": False,
        "live_port_contacted": False,
    }
    payload["evidence_checksum"] = soak._frontend_reload_evidence_checksum(payload)
    path = evidence_root / "synthetic-frontend-reload-evidence.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8-sig")
    return path


def _write_authority_map(base: Path) -> Path:
    names = sorted(soak.REQUIRED_MAPPED_AUTHORITIES)
    authorities = []
    for name in names:
        authority = base / f"{name}-{uuid.uuid4().hex}"
        authority.mkdir()
        authorities.append(
            {
                "authority": name,
                "canonical_path": str(authority.resolve(strict=True)),
                "classification": "isolated",
                "overlap_result": "distinct",
                "reparse_point": False,
            }
        )
    path = base / "isolated-authority-map.json"
    payload = {
        "schema_version": 1,
        "run_id": uuid.uuid4().hex,
        "base_root": str(base.resolve(strict=True)),
        "repository_root": str(soak.ROOT.resolve(strict=True)),
        "windows_temp_root": str(Path(tempfile.gettempdir()).resolve(strict=True)),
        "authorities": authorities,
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8-sig")
    return path


def test_release_defaults_cannot_be_silently_scaled_down() -> None:
    with _temporary_test_root("atlas-catalog-soak-settings-") as root:
        defaults = soak.SoakSettings(root=root)
        assert defaults.duration_seconds == 1_800
        assert defaults.user_count >= 25
        assert defaults.max_workers >= 25
        assert defaults.project_count >= 10
        assert defaults.catalog_version_count >= 3
        assert defaults.bounded_operation_count >= 10_000
        assert defaults.crosswalk_preview_count >= 1_000
        assert defaults.decision_write_count >= 250
        assert defaults.service_reload_count >= 10
        assert defaults.frontend_authenticated_reload_minimum >= 10

        with pytest.raises(soak.SoakConfigurationError, match="Release soak minimums"):
            soak.SoakSettings(
                root=root,
                duration_seconds=1,
                user_count=4,
                project_count=2,
                catalog_version_count=2,
                bounded_operation_count=40,
                crosswalk_preview_count=12,
                decision_write_count=8,
                service_reload_count=2,
            ).validate()


def test_release_configuration_requires_verified_frontend_reload_evidence() -> None:
    with _temporary_test_root("atlas-catalog-soak-frontend-required-") as root:
        with pytest.raises(
            soak.SoakConfigurationError,
            match="authenticated frontend reload evidence",
        ):
            soak.SoakSettings(root=root).validate()


def test_frontend_reload_evidence_hook_accepts_isolated_ports_and_rejects_live_ports() -> None:
    with _temporary_test_root("atlas-catalog-soak-frontend-hook-") as root:
        evidence_root = root / "test-output"
        accepted = _write_frontend_reload_evidence(evidence_root)
        result = soak._load_frontend_reload_evidence(
            accepted,
            minimum_reloads=10,
            allowed_evidence_root=evidence_root,
        )
        assert result["status"] == "verified"
        assert result["authenticated_reload_successes"] == 10
        assert result["live_port_contacted"] is False

        prohibited = _write_frontend_reload_evidence(
            evidence_root,
            frontend_port=soak.LIVE_FRONTEND_PORT,
        )
        with pytest.raises(soak.SoakConfigurationError, match="live service port"):
            soak._load_frontend_reload_evidence(
                prohibited,
                minimum_reloads=10,
                allowed_evidence_root=evidence_root,
            )


def test_explicit_authority_map_resolves_disjoint_sibling_roots() -> None:
    with _durable_test_root() as base:
        authority_map = _write_authority_map(base)
        paths = soak._load_authority_map(authority_map)
        assert paths.restricted_catalog_root.parent == base
        assert paths.evidence_root.parent == base
        assert paths.temporary_root is not None
        assert paths.temporary_root.parent == base
        assert paths.restricted_catalog_root != paths.evidence_root
        assert paths.authority_map_checksum
        assert paths.mapped_authority_count == len(soak.REQUIRED_MAPPED_AUTHORITIES)
        assert paths.per_run_children_allocated is False
        assert len(paths.top_level_authority_identities) == 3
        settings = soak.SoakSettings(
            root=None,
            authority_map=authority_map,
            enforce_release_minimums=False,
        )
        assert settings.validate() == paths.restricted_catalog_root


def test_mapped_soak_coexists_with_preexisting_acceptance_child_without_mutation() -> None:
    with _durable_test_root() as base:
        authority_map = _write_authority_map(base)
        top_level = soak._load_authority_map(authority_map)
        unrelated = top_level.restricted_catalog_root / (
            "synthetic-acceptance-" + uuid.uuid4().hex
        )
        unrelated.mkdir()
        sentinel = unrelated / "acceptance-sentinel.json"
        sentinel_payload = b'{"classification":"unrelated_synthetic_acceptance"}\n'
        sentinel.write_bytes(sentinel_payload)
        restricted_before = frozenset(top_level.restricted_catalog_root.iterdir())

        result = soak.run_soak(
            soak.SoakSettings(
                root=None,
                authority_map=authority_map,
                duration_seconds=0,
                user_count=4,
                project_count=2,
                catalog_version_count=2,
                bounded_operation_count=40,
                crosswalk_preview_count=12,
                decision_write_count=8,
                service_reload_count=2,
                unauthorized_attempt_count=8,
                conflict_trial_count=2,
                max_workers=4,
                heartbeat_seconds=0.01,
                enforce_release_minimums=False,
            )
        )

        assert result["passed"] is True
        assert sentinel.read_bytes() == sentinel_payload
        assert tuple(unrelated.iterdir()) == (sentinel,)
        restricted_after = frozenset(top_level.restricted_catalog_root.iterdir())
        new_children = restricted_after - restricted_before
        assert len(new_children) == 1
        soak_child = next(iter(new_children))
        assert soak_child.is_dir()
        assert soak_child.name.startswith("catalog-soak-")
        assert (soak_child / soak.ROOT_MARKER).is_file()
        authority_evidence = result["authority_map"]
        assert authority_evidence["used"] is True
        assert authority_evidence["checksum"] == top_level.authority_map_checksum
        assert authority_evidence["authority_map_run_id"] == top_level.authority_map_run_id
        assert authority_evidence["per_run_children_allocated"] is True
        assert authority_evidence["top_level_authority_identities"] == dict(
            top_level.top_level_authority_identities
        )
        assert authority_evidence["per_run_child_identity"]
        assert result["leaked_temporary_entries"] == 0


def test_root_claim_fails_closed_for_unmarked_nonempty_authority() -> None:
    with _temporary_test_root("atlas-catalog-soak-root-") as root:
        (root / "unknown-authority.sqlite3").write_bytes(b"not synthetic")
        with pytest.raises(soak.SoakConfigurationError, match="nonempty"):
            soak._claim_isolated_root(root)
        assert not (root / soak.ROOT_MARKER).exists()


def test_production_validation_still_rejects_windows_temp() -> None:
    with _windows_temp_test_root("atlas-catalog-soak-guard-") as root:
        with pytest.raises(RestrictedStorageConfigurationError):
            soak.run_soak(_mini_settings(root))
        assert not (root / soak.ROOT_MARKER).exists()


def test_scaled_synthetic_soak_exercises_integrity_isolation_and_reload() -> None:
    with _durable_test_root() as root:
        result = soak.run_soak(_mini_settings(root))

        assert result["passed"] is True
        assert result["functional_integrity"] is True
        assert result["configured_thresholds_met"] is True
        assert result["release_thresholds_met"] is False
        assert result["bounded_operations"] >= 40
        assert result["crosswalk_previews"] >= 12
        assert result["decision_writes"] >= 8
        assert result["expected_authorization_denials"] >= 8
        assert result["concurrency_conflicts"] == 2
        assert result["independent_writer_instances"] == 4
        assert result["concurrent_alias_reviews"] == 1
        assert result["catalog_version_switches"] >= 1
        assert result["service_reload_cycles"] == 2
        assert result["reload_child_processes"] == 2
        assert result["exact_identity_negative_checks"] == 16
        assert result["duplicate_revisions"] == 0
        assert result["restart_recovery_failures"] == 0
        assert result["inconsistent_entitlement_results"] == 0
        assert result["cross_user_contamination"] == 0
        assert result["cross_tenant_contamination"] == 0
        assert result["cross_project_contamination"] == 0
        assert result["cross_provider_contamination"] == 0
        assert result["provider_isolation_checks"] >= 2
        assert result["catalog_provider_count"] == 2
        assert result["checksum_failures"] == 1
        assert result["expected_tamper_checksum_failures"] == 1
        assert result["unexpected_checksum_failures"] == 0
        assert result["tamper_probe_count"] == 1
        assert result["tamper_detection_passed"] is True
        assert result["tamper_cache_eviction_passed"] is True
        assert result["tamper_recovery_passed"] is True
        assert result["contains_vendor_content"] is False
        assert result["live_project_accessed"] is False
        assert result["live_service_manipulated"] is False
        assert result["live_ports_contacted"] is False
        assert result["sealed_holdout_accessed"] is False
        assert result["cache_within_limit"] is True
        assert result["leaked_temporary_entries"] == 0
        assert result["latency_sample_count"] > 0
        assert result["frontend_authenticated_reload_coverage"]["status"] == (
            "not_required_for_scaled_test"
        )

        crosswalk_database = root / "registry" / "crosswalk_governance.sqlite3"
        connection = sqlite3.connect(str(crosswalk_database))
        try:
            authority_objects = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','trigger')"
                ).fetchall()
            }
        finally:
            connection.close()
        assert "bureau_crosswalk_revisions" in authority_objects
        assert "bureau_crosswalk_heads" in authority_objects
        assert "bureau_crosswalk_revisions_no_update" in authority_objects
        assert "bureau_crosswalk_revisions_no_delete" in authority_objects

        reload_results = tuple(
            (root / soak.EVIDENCE_DIRECTORY / soak.RELOAD_PROBE_DIRECTORY).glob(
                "*-result.json"
            )
        )
        assert len(reload_results) == 2
        assert all(
            json.loads(path.read_text(encoding="utf-8"))["negative_checks"] == 8
            for path in reload_results
        )

        summary_path = root / soak.EVIDENCE_DIRECTORY / str(result["evidence_file"])
        persisted = json.loads(summary_path.read_text(encoding="utf-8"))
        assert persisted == result
        serialized = summary_path.read_text(encoding="utf-8").casefold()
        assert str(root).casefold() not in serialized
        assert "experian" not in serialized
        assert "heloc" not in serialized
        assert "bad_flag" not in serialized
        assert "restricted_storage_reference" not in serialized
        del persisted
        del result
        gc.collect()


def test_minimum_two_user_configuration_has_an_exact_cross_project_nonmember() -> None:
    with _durable_test_root() as root:
        result = soak.run_soak(
            soak.SoakSettings(
                root=root,
                duration_seconds=0,
                user_count=2,
                project_count=1,
                catalog_version_count=1,
                bounded_operation_count=4,
                crosswalk_preview_count=2,
                decision_write_count=1,
                service_reload_count=1,
                unauthorized_attempt_count=1,
                conflict_trial_count=1,
                max_workers=2,
                heartbeat_seconds=0.01,
                enforce_release_minimums=False,
            )
        )
        assert result["passed"] is True
        assert result["cross_project_contamination"] == 0
        assert result["exact_identity_negative_checks"] == 4


def test_failure_path_releases_production_sqlite_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _durable_test_root() as root:
        def fail_reload(**_kwargs):  # type: ignore[no-untyped-def]
            raise soak.SoakInvariantError("Synthetic injected reload failure.")

        monkeypatch.setattr(soak, "_run_reload_probe_subprocess", fail_reload)
        with pytest.raises(soak.SoakInvariantError, match="Synthetic catalog soak failed"):
            soak.run_soak(_mini_settings(root))

        gc.collect()
        databases = tuple(root.rglob("*.sqlite3"))
        assert databases
        for database in databases:
            connection = sqlite3.connect(str(database), timeout=0.1)
            try:
                connection.execute("BEGIN EXCLUSIVE")
                connection.rollback()
            finally:
                connection.close()


def test_cli_requires_an_explicit_root() -> None:
    with pytest.raises(SystemExit) as raised:
        soak._parser().parse_args([])
    assert raised.value.code == 2
