from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import tempfile
from typing import Iterator
import uuid

import pytest

from scripts import build_bureau_metadata_crosswalk as cli
from tests.bureau_metadata_core_test import _publish_synthetic_catalog


@contextmanager
def _external_root() -> Iterator[Path]:
    root = Path(tempfile.gettempdir()) / f"atlas-bureau-crosswalk-{uuid.uuid4().hex}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _arguments(
    *,
    catalog_root: Path,
    checksum: str,
    entitlement: Path,
    schema: Path,
    output: Path,
) -> list[str]:
    return [
        "--catalog-root",
        str(catalog_root),
        "--entitlement-json",
        str(entitlement),
        "--principal-id",
        "synthetic-analyst",
        "--provider",
        "Synthetic Bureau",
        "--product",
        "Synthetic Attributes",
        "--edition",
        "Test",
        "--dictionary-version",
        "1.0",
        "--catalog-checksum",
        checksum,
        "--schema-json",
        str(schema),
        "--output-json",
        str(output),
        "--project-id",
        "synthetic-project",
        "--dataset-id",
        "synthetic-dataset",
        "--dataset-version-id",
        "synthetic-version",
        "--target-field",
        "outcome",
        "--target-source-field",
        "source_outcome",
        "--non-catalog-field",
        "workflow_marker",
        "--created-at",
        "2026-08-05T00:00:00Z",
    ]


def _publish_crosswalk_catalog(root: Path):
    return _publish_synthetic_catalog(
        root,
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


def _write_entitlement(
    path: Path,
    *,
    key,
    checksum: str,
    operation: str = "crosswalk_candidate",
    principal_id: str = "synthetic-analyst",
) -> None:
    path.write_text(
        json.dumps(
            {
                "grant_id": "synthetic-crosswalk-grant",
                "principal_id": principal_id,
                "tenant_id": None,
                "catalog_key": key.model_dump(mode="json"),
                "catalog_checksum": checksum,
                "operation": operation,
                "expires_at": "2099-01-01T00:00:00Z",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_schema(path: Path, *, include_rows: bool = False) -> None:
    payload: dict[str, object] = {
        "columns": [
            {
                "name": "ATTR_A",
                "dtype": "numeric",
                "min": -9.0,
                "max": 75.0,
            },
            {
                "name": "ATTR_B",
                "dtype": "numeric",
                "min": 0.0,
                "max": 150.0,
            },
            {"name": "outcome", "dtype": "numeric", "min": 0, "max": 1},
            {"name": "source_outcome", "dtype": "categorical"},
            {"name": "workflow_marker", "dtype": "categorical"},
        ]
    }
    if include_rows:
        payload["rows"] = [{"restricted": "row-level input must be rejected"}]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_cli_loads_exact_catalog_and_writes_candidate_only_external_artifact(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _external_root() as root:
        catalog_root = root / "catalog-root"
        catalog_root.mkdir()
        key, checksum, _directory = _publish_crosswalk_catalog(catalog_root)
        entitlement = root / "entitlement.json"
        _write_entitlement(entitlement, key=key, checksum=checksum)
        schema = root / "schema.json"
        output = root / "candidate-crosswalk.json"
        _write_schema(schema)

        result = cli.main(
            _arguments(
                catalog_root=catalog_root,
                checksum=checksum,
                entitlement=entitlement,
                schema=schema,
                output=output,
            )
        )

        stdout = capsys.readouterr().out
        public = json.loads(stdout)
        assert result == 0
        assert public["ok"] is True
        assert public["schema_field_count"] == 5
        assert public["candidate_count"] == 5
        assert public["status_counts"] == {
            "deterministic_target_source": 1,
            "exact_dictionary_code_match": 1,
            "non_catalog_field": 1,
            "target": 1,
            "unresolved_recoding": 1,
        }
        assert public["approved_mapping_count"] == 0
        assert public["entitlement_checked"] is True
        assert public["row_data_accessed"] is False
        assert public["final_holdout_accessed"] is False
        for restricted_fragment in (
            "ATTR_A",
            "outcome",
            "workflow_marker",
            "Attribute-specific special semantics",
            str(root),
        ):
            assert restricted_fragment not in stdout

        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert artifact["analysis_scope"] == {
            "schema_metadata_only": True,
            "entitlement_checked": True,
            "row_data_accessed": False,
            "final_holdout_accessed": False,
            "institutional_aliases_applied": False,
            "mapping_approval_performed": False,
            "dataset_mutated": False,
            "project_mutated": False,
        }
        crosswalk = artifact["crosswalk"]
        assert crosswalk["project_id"] == "synthetic-project"
        assert crosswalk["dataset_id"] == "synthetic-dataset"
        assert crosswalk["dataset_version_id"] == "synthetic-version"
        assert crosswalk["catalog_checksum"] == checksum
        assert crosswalk["candidate_only"] is True
        assert crosswalk["approved_mappings"] == []
        assert crosswalk["dataset_mutated"] is False
        assert crosswalk["governed_feature_set_changed"] is False

        by_field = {row["dataset_field"]: row for row in crosswalk["mappings"]}
        assert by_field["outcome"]["match_status"] == "target"
        assert (
            by_field["source_outcome"]["match_status"]
            == "deterministic_target_source"
        )
        assert by_field["workflow_marker"]["match_status"] == "non_catalog_field"
        assert by_field["ATTR_A"]["match_status"] == "unresolved_recoding"
        assert by_field["ATTR_A"]["valid_range_evidence"]["comparable"] is True
        assert (
            by_field["ATTR_A"]["special_value_evidence"][
                "source_meaning_assignment"
            ]
            == "withheld_pending_durable_recode_evidence"
        )
        assert all(row["candidate_only"] for row in crosswalk["mappings"])
        assert all(not row["approved_mapping"] for row in crosswalk["mappings"])


def test_cli_wrong_exact_checksum_fails_closed_and_redacts_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _external_root() as root:
        catalog_root = root / "catalog-root"
        catalog_root.mkdir()
        key, _checksum, _directory = _publish_crosswalk_catalog(catalog_root)
        entitlement = root / "entitlement.json"
        _write_entitlement(entitlement, key=key, checksum="f" * 64)
        schema = root / "schema.json"
        output = root / "candidate-crosswalk.json"
        _write_schema(schema)

        result = cli.main(
            _arguments(
                catalog_root=catalog_root,
                checksum="f" * 64,
                entitlement=entitlement,
                schema=schema,
                output=output,
            )
        )

        stdout = capsys.readouterr().out
        failure = json.loads(stdout)
        assert result == 2
        assert failure["ok"] is False
        assert "fallback" not in stdout.casefold()
        assert str(root) not in stdout
        assert "ATTR_A" not in stdout
        assert not output.exists()


def test_cli_rejects_row_level_schema_input_without_creating_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _external_root() as root:
        catalog_root = root / "catalog-root"
        catalog_root.mkdir()
        key, checksum, _directory = _publish_crosswalk_catalog(catalog_root)
        entitlement = root / "entitlement.json"
        _write_entitlement(entitlement, key=key, checksum=checksum)
        schema = root / "schema.json"
        output = root / "candidate-crosswalk.json"
        _write_schema(schema, include_rows=True)

        result = cli.main(
            _arguments(
                catalog_root=catalog_root,
                checksum=checksum,
                entitlement=entitlement,
                schema=schema,
                output=output,
            )
        )

        stdout = capsys.readouterr().out
        assert result == 2
        assert "row-level input must be rejected" not in stdout
        assert str(root) not in stdout
        assert not output.exists()


def test_cli_strict_schema_dto_rejects_unknown_and_nested_payloads(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _external_root() as root:
        catalog_root = root / "catalog-root"
        catalog_root.mkdir()
        key, checksum, _directory = _publish_crosswalk_catalog(catalog_root)
        entitlement = root / "entitlement.json"
        _write_entitlement(entitlement, key=key, checksum=checksum)

        cases = (
            "unknown_top_level_holdout",
            "nested_preview_in_description",
            "nested_object_in_special_values",
            "unknown_column_holdout_values",
        )
        for index, case in enumerate(cases):
            schema = root / f"schema-{index}.json"
            output = root / f"crosswalk-{index}.json"
            _write_schema(schema)
            payload = json.loads(schema.read_text(encoding="utf-8"))
            if case == "unknown_top_level_holdout":
                payload["metadata"] = {"final_holdout": [{"secret": 1}]}
            elif case == "nested_preview_in_description":
                payload["columns"][0]["description"] = {
                    "preview": [{"secret": 1}]
                }
            elif case == "nested_object_in_special_values":
                payload["columns"][0]["observedSpecialValues"] = [
                    {"value": -9, "row": {"secret": 1}}
                ]
            else:
                payload["columns"][0]["holdout_values"] = [1, 2, 3]
            schema.write_text(json.dumps(payload), encoding="utf-8")

            result = cli.main(
                _arguments(
                    catalog_root=catalog_root,
                    checksum=checksum,
                    entitlement=entitlement,
                    schema=schema,
                    output=output,
                )
            )
            stdout = capsys.readouterr().out
            assert result == 2
            assert "secret" not in stdout
            assert str(root) not in stdout
            assert not output.exists()


def test_cli_entitlement_denial_occurs_before_candidate_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _external_root() as root:
        catalog_root = root / "catalog-root"
        catalog_root.mkdir()
        key, checksum, _directory = _publish_crosswalk_catalog(catalog_root)
        entitlement = root / "entitlement.json"
        _write_entitlement(
            entitlement,
            key=key,
            checksum=checksum,
            operation="attribute_lookup",
        )
        schema = root / "schema.json"
        output = root / "candidate-crosswalk.json"
        _write_schema(schema)

        result = cli.main(
            _arguments(
                catalog_root=catalog_root,
                checksum=checksum,
                entitlement=entitlement,
                schema=schema,
                output=output,
            )
        )

        stdout = capsys.readouterr().out
        failure = json.loads(stdout)
        assert result == 2
        assert failure["error_type"] == "BureauCatalogAccessDeniedError"
        assert "attribute_lookup" not in stdout
        assert str(root) not in stdout
        assert not output.exists()
