from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from scripts import run_bureau_metadata_schema_crosswalk_diagnostic as diagnostic
from server.bureau_metadata import catalog_registry as registry_module
from server.bureau_metadata import operational_service as operational_module
from server.bureau_metadata.normalizer import canonical_json_bytes
from server.bureau_metadata.operational_service import OperationalCatalogService
from tests.bureau_metadata_core_test import _publish_synthetic_catalog
from tests.hermetic_test_roots import temporary_test_root


PROJECT_ID = "synthetic-project"
DATASET_ID = "synthetic-dataset"
VERSION_ID = "synthetic-version-2"
PRINCIPAL_ID = "synthetic-crosswalk-analyst"
TENANT_ID = "synthetic-tenant"


@pytest.fixture
def tmp_path() -> Path:
    """Keep synthetic crosswalk fixtures inside launcher-owned authority."""

    with temporary_test_root(
        "bureau-schema-crosswalk-",
        scope="bureau-schema-crosswalk-fixtures",
    ) as root:
        yield root


def _allow_synthetic_restricted_root(
    monkeypatch: pytest.MonkeyPatch,
    restricted_root: Path,
) -> None:
    root = restricted_root.resolve(strict=True)

    def validator(value: object, **_kwargs: object) -> Path:
        candidate = Path(str(value)).resolve(strict=True)
        if candidate != root:
            raise AssertionError("synthetic validator received another authority")
        return candidate

    monkeypatch.setattr(diagnostic, "validate_restricted_metadata_root", validator)
    monkeypatch.setattr(
        operational_module,
        "validate_restricted_metadata_root",
        validator,
    )
    monkeypatch.setattr(
        registry_module,
        "validate_restricted_metadata_root",
        validator,
    )


def _schema_columns() -> list[dict[str, object]]:
    return [
        {"name": "ATTR_A", "dtype": "numeric", "min": -9, "max": 75},
        {"name": "ATTR_B", "dtype": "numeric", "min": 0, "max": 150},
        {"name": "outcome", "dtype": "numeric", "min": 0, "max": 1},
        {"name": "source_outcome", "dtype": "categorical"},
    ]


def _profile_columns() -> list[dict[str, object]]:
    return [
        {"name": str(row["name"]), "dtype": str(row["dtype"])}
        for row in _schema_columns()
    ]


def _dataset_registry(*, profile_reference: str | None = None) -> dict[str, Any]:
    exact_profile = (
        profile_reference
        if profile_reference is not None
        else f"{DATASET_ID}/versions/{VERSION_ID}/profile.json"
    )
    return {
        "datasets": [
            {
                "datasetId": DATASET_ID,
                "archived": False,
                "versions": [
                    {
                        "versionId": "synthetic-version-1",
                        "profilePath": (
                            f"{DATASET_ID}/versions/synthetic-version-1/profile.json"
                        ),
                    },
                    {
                        "versionId": VERSION_ID,
                        "profilePath": exact_profile,
                        # These row-bearing artifacts are adversarial sentinels.
                        # The diagnostic must never inspect them.
                        "fullDataPath": (
                            f"{DATASET_ID}/versions/{VERSION_ID}/data_full.csv"
                        ),
                        "previewPath": (
                            f"{DATASET_ID}/versions/{VERSION_ID}/preview.json"
                        ),
                        "samplePath": (
                            f"{DATASET_ID}/versions/{VERSION_ID}/data_sample.csv"
                        ),
                    },
                ],
            }
        ]
    }


def _project_state(*, dataset_version_id: str = VERSION_ID) -> dict[str, Any]:
    return {
        "links": [
            {
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "link_status": "active",
            }
        ],
        "active_selection": {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": dataset_version_id,
            "activation_status": "active",
            "activation_revision": 3,
        },
    }


def _prepare_catalog(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
) -> tuple[OperationalCatalogService, str, str]:
    restricted = root / "restricted"
    restricted.mkdir()
    repository_marker = root / "repository-marker"
    repository_marker.mkdir()
    _allow_synthetic_restricted_root(monkeypatch, restricted)
    _key, checksum, exact_directory = _publish_synthetic_catalog(
        restricted,
        allowed_operations=frozenset(
            {
                "catalog_health",
                "manifest_read",
                "attribute_lookup",
                "special_value_lookup",
                "value_classification",
                "crosswalk_candidate",
            }
        ),
    )
    manifest_path = exact_directory / "catalog_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_files"] = [
        {
            "role": "canonical_pdf",
            "filename": "synthetic-source.pdf",
            "suffix": ".pdf",
            "sha256": "a" * 64,
            "size_bytes": 1,
        }
    ]
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    service = OperationalCatalogService(
        restricted,
        repository_root=repository_marker,
    )
    loaded = service.store.load_exact(_key, checksum)
    version = service.registry.register_manifest(
        loaded.manifest,
        storage_reference="restricted-catalog:" + "c" * 32,
        actor="synthetic-catalog-administrator",
    )
    entitlement = service.registry.grant_entitlement(
        principal_id=PRINCIPAL_ID,
        tenant_id=TENANT_ID,
        catalog_version_id=version.catalog_version_id,
        operations=("crosswalk_candidate",),
        granted_by="synthetic-catalog-administrator",
    )
    service.loader.clear()
    return service, version.catalog_version_id, entitlement.entitlement_id


def _prepare_dataset_artifacts(root: Path) -> tuple[Path, Path, tuple[Path, ...]]:
    artifacts = root / "dataset-artifacts"
    version_root = artifacts / DATASET_ID / "versions" / VERSION_ID
    version_root.mkdir(parents=True)
    profile = version_root / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "rowCount": 50,
                "columnCount": 4,
                "profiledRows": 50,
                "schema": _profile_columns(),
                "targetCandidates": ["outcome"],
                "warnings": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    row_paths = (
        version_root / "data_full.csv",
        version_root / "preview.json",
        version_root / "data_sample.csv",
    )
    for path in row_paths:
        path.write_text("ROW_LEVEL_SENTINEL_MUST_NOT_BE_READ", encoding="utf-8")
    schema = root / "input-schema.json"
    schema.write_text(json.dumps({"columns": _schema_columns()}), encoding="utf-8")
    return artifacts, schema, row_paths


def _settings(
    service: OperationalCatalogService,
    catalog_version_id: str,
    schema: Path,
    *,
    output: Path | None = None,
) -> diagnostic.SchemaCrosswalkDiagnosticSettings:
    version = service.registry.get_version(catalog_version_id)
    return diagnostic.SchemaCrosswalkDiagnosticSettings(
        restricted_root=service.root,
        catalog_version_id=catalog_version_id,
        catalog_checksum=version.normalized_catalog_checksum,
        principal_id=PRINCIPAL_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        dataset_version_id=VERSION_ID,
        schema_json=schema,
        output_json=output or (service.root / "diagnostics" / "candidate.json"),
        target_field="outcome",
        target_source_fields=("source_outcome",),
        created_at="2026-08-05T00:00:00Z",
    )


def _run(
    settings: diagnostic.SchemaCrosswalkDiagnosticSettings,
    service: OperationalCatalogService,
    artifacts: Path,
    *,
    registry: Mapping[str, Any] | None = None,
    state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return diagnostic.run_schema_crosswalk_diagnostic(
        settings,
        operational_service=service,
        registry_loader=lambda: registry or _dataset_registry(),
        project_state_loader=lambda _project_id: state or _project_state(),
        dataset_artifact_root=artifacts,
    )


def test_exact_entitled_diagnostic_is_candidate_only_and_never_reads_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, catalog_version_id, _entitlement_id = _prepare_catalog(
        monkeypatch,
        tmp_path,
    )
    artifacts, schema, row_paths = _prepare_dataset_artifacts(tmp_path)
    settings = _settings(service, catalog_version_id, schema)
    original_read_bytes = Path.read_bytes
    reads: list[Path] = []

    def tracked_read_bytes(path: Path) -> bytes:
        reads.append(path.resolve())
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", tracked_read_bytes)
    summary = _run(settings, service, artifacts)

    assert summary["ok"] is True
    assert summary["candidate_only"] is True
    assert summary["persisted"] is False
    assert summary["approved_mapping_count"] == 0
    assert summary["row_data_accessed"] is False
    assert summary["preview_accessed"] is False
    assert summary["sample_accessed"] is False
    assert summary["final_holdout_accessed"] is False
    assert all(path.resolve() not in reads for path in row_paths)

    artifact = json.loads(settings.output_json.read_text(encoding="utf-8"))
    assert artifact["candidate_only"] is True
    assert artifact["persisted"] is False
    assert artifact["approved_mappings"] == []
    assert artifact["governed_feature_set_changed"] is False
    assert artifact["dataset_mutated"] is False
    assert artifact["project_mutated"] is False
    assert artifact["identity_verification"]["activation_revision"] == 3
    assert artifact["identity_verification"]["exact_registry_version_verified"] is True
    assert artifact["identity_verification"]["exact_project_link_verified"] is True
    assert artifact["identity_verification"]["profile_schema_identity_verified"] is True
    scope = artifact["analysis_scope"]
    assert scope["institutional_aliases_applied"] is False
    assert scope["mapping_decisions_persisted"] is False
    mappings = artifact["crosswalk"]["mappings"]
    by_field = {mapping["dataset_field"]: mapping for mapping in mappings}
    assert by_field["outcome"]["match_status"] == "target"
    assert (
        by_field["source_outcome"]["match_status"]
        == "deterministic_target_source"
    )
    assert all(mapping["institutional_alias_reference"] is None for mapping in mappings)
    assert all(mapping["candidate_only"] is True for mapping in mappings)
    assert all(mapping["approved_mapping"] is False for mapping in mappings)


def test_unauthorized_principal_is_denied_before_catalog_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, catalog_version_id, entitlement_id = _prepare_catalog(monkeypatch, tmp_path)
    artifacts, schema, _row_paths = _prepare_dataset_artifacts(tmp_path)
    service.registry.revoke_entitlement(
        entitlement_id,
        revoked_by="synthetic-catalog-administrator",
    )
    settings = _settings(service, catalog_version_id, schema)
    loads = 0

    def forbidden_load(*_args: object, **_kwargs: object) -> object:
        nonlocal loads
        loads += 1
        raise AssertionError("catalog bytes were loaded before authorization")

    monkeypatch.setattr(service.loader, "load_exact", forbidden_load)
    with pytest.raises(PermissionError):
        _run(settings, service, artifacts)
    assert loads == 0
    assert not settings.output_json.exists()


def test_cross_version_active_selection_fails_closed_before_catalog_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, catalog_version_id, _entitlement_id = _prepare_catalog(monkeypatch, tmp_path)
    artifacts, schema, _row_paths = _prepare_dataset_artifacts(tmp_path)
    settings = _settings(service, catalog_version_id, schema)
    loads = 0

    def forbidden_load(*_args: object, **_kwargs: object) -> object:
        nonlocal loads
        loads += 1
        raise AssertionError("catalog bytes were loaded for contradictory lineage")

    monkeypatch.setattr(service.loader, "load_exact", forbidden_load)
    with pytest.raises(diagnostic.SchemaCrosswalkDiagnosticError):
        _run(
            settings,
            service,
            artifacts,
            state=_project_state(dataset_version_id="synthetic-version-1"),
        )
    assert loads == 0
    assert not settings.output_json.exists()


def test_version_owned_by_another_dataset_fails_closed_before_catalog_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, catalog_version_id, _entitlement_id = _prepare_catalog(monkeypatch, tmp_path)
    artifacts, schema, _row_paths = _prepare_dataset_artifacts(tmp_path)
    settings = _settings(service, catalog_version_id, schema)
    contradictory_registry = {
        "datasets": [
            {
                "datasetId": DATASET_ID,
                "archived": False,
                "versions": [],
            },
            {
                "datasetId": "synthetic-other-dataset",
                "archived": False,
                "versions": [
                    {
                        "versionId": VERSION_ID,
                        "profilePath": (
                            "synthetic-other-dataset/versions/"
                            f"{VERSION_ID}/profile.json"
                        ),
                    }
                ],
            },
        ]
    }
    loads = 0

    def forbidden_load(*_args: object, **_kwargs: object) -> object:
        nonlocal loads
        loads += 1
        raise AssertionError("catalog bytes were loaded for cross-dataset lineage")

    monkeypatch.setattr(service.loader, "load_exact", forbidden_load)
    with pytest.raises(diagnostic.SchemaCrosswalkDiagnosticError):
        _run(
            settings,
            service,
            artifacts,
            registry=contradictory_registry,
        )
    assert loads == 0
    assert not settings.output_json.exists()


def test_profile_schema_mismatch_fails_closed_before_catalog_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, catalog_version_id, _entitlement_id = _prepare_catalog(monkeypatch, tmp_path)
    artifacts, schema, _row_paths = _prepare_dataset_artifacts(tmp_path)
    profile = artifacts / DATASET_ID / "versions" / VERSION_ID / "profile.json"
    payload = json.loads(profile.read_text(encoding="utf-8"))
    payload["schema"][0]["dtype"] = "categorical"
    profile.write_text(json.dumps(payload), encoding="utf-8")
    settings = _settings(service, catalog_version_id, schema)
    loads = 0

    def forbidden_load(*_args: object, **_kwargs: object) -> object:
        nonlocal loads
        loads += 1
        raise AssertionError("catalog bytes were loaded for mismatched schema")

    monkeypatch.setattr(service.loader, "load_exact", forbidden_load)
    with pytest.raises(diagnostic.SchemaCrosswalkDiagnosticError):
        _run(settings, service, artifacts)
    assert loads == 0
    assert not settings.output_json.exists()


def test_output_and_profile_path_escape_are_rejected_without_catalog_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, catalog_version_id, _entitlement_id = _prepare_catalog(monkeypatch, tmp_path)
    artifacts, schema, _row_paths = _prepare_dataset_artifacts(tmp_path)
    loads = 0

    def forbidden_load(*_args: object, **_kwargs: object) -> object:
        nonlocal loads
        loads += 1
        raise AssertionError("catalog bytes were loaded for an escaped path")

    monkeypatch.setattr(service.loader, "load_exact", forbidden_load)
    escaped_output = tmp_path / "escaped-candidate.json"
    output_settings = _settings(
        service,
        catalog_version_id,
        schema,
        output=escaped_output,
    )
    with pytest.raises(diagnostic.SchemaCrosswalkDiagnosticError):
        _run(output_settings, service, artifacts)
    assert not escaped_output.exists()

    profile_settings = _settings(service, catalog_version_id, schema)
    escaped_registry = _dataset_registry(profile_reference="../outside/profile.json")
    with pytest.raises(diagnostic.SchemaCrosswalkDiagnosticError):
        _run(
            profile_settings,
            service,
            artifacts,
            registry=escaped_registry,
        )
    assert loads == 0
    assert not profile_settings.output_json.exists()


def test_cli_errors_never_emit_paths_or_schema_content(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(_settings: object) -> object:
        raise RuntimeError("restricted field ATTR_A at C:/restricted/source")

    monkeypatch.setattr(diagnostic, "run_schema_crosswalk_diagnostic", fail)
    result = diagnostic.main(
        [
            "--restricted-root",
            "C:/restricted/root",
            "--catalog-version-id",
            "synthetic-catalog-version",
            "--catalog-checksum",
            "a" * 64,
            "--principal-id",
            PRINCIPAL_ID,
            "--tenant-id",
            TENANT_ID,
            "--project-id",
            PROJECT_ID,
            "--dataset-id",
            DATASET_ID,
            "--dataset-version-id",
            VERSION_ID,
            "--schema-json",
            "C:/restricted/schema.json",
            "--output-json",
            "C:/restricted/root/diagnostics/result.json",
            "--target-field",
            "outcome",
            "--target-source-field",
            "source_outcome",
        ]
    )
    stdout = capsys.readouterr().out
    assert result == 2
    assert "ATTR_A" not in stdout
    assert "C:/restricted" not in stdout
    assert json.loads(stdout)["error_type"] == "RuntimeError"
