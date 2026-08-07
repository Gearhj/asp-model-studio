"""Synthetic-only tests for restricted bureau catalog ingestion/build contracts."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import uuid

import pytest

from server.bureau_metadata import catalog_builder as builder_module
from server.bureau_metadata.catalog_builder import (
    CatalogBuildConfig,
    CatalogBuildError,
    CatalogBuildResult,
    _compile_special_pattern,
    _finalize_record_checksums,
    _parse_special_values,
    _reconcile_records,
    build_catalog,
    catalog_key_digest,
    deterministic_normalized_hash,
    parse_ordinary_range,
)
from server.bureau_metadata.csv_parser import (
    CsvParseResult,
    looks_like_spreadsheet_date,
    parse_csv_rows,
    parse_csv_stream,
)
from server.bureau_metadata.normalizer import catalog_key_digest as normalized_key_digest
from server.bureau_metadata.pdf_parser import (
    PdfParseResult,
    PdfParserConfig,
    _parse_pdfplumber_tables,
    parse_pdf_pages,
)
from server.bureau_metadata.source_reader import SourceDescriptor
from server.bureau_metadata.validation import (
    catalog_governance_payload,
    calculate_catalog_checksum,
)


def _descriptor(filename: str, digest_character: str) -> SourceDescriptor:
    return SourceDescriptor(
        path=Path("C:/restricted-synthetic") / filename,
        filename=filename,
        suffix=Path(filename).suffix,
        size_bytes=100,
        sha256=digest_character * 64,
    )


def test_public_build_summary_never_discloses_host_paths() -> None:
    result = CatalogBuildResult(
        output_directory=Path("C:/restricted/synthetic/output"),
        manifest_path=Path("C:/restricted/synthetic/output/catalog_manifest.json"),
        catalog_id="synthetic-catalog",
        catalog_checksum="a" * 64,
        attribute_count=1,
        special_value_count=1,
        validation_finding_count=0,
        validation_status="passed",
        aggregate_summary={"synthetic": 1},
    )

    summary = result.public_summary()
    assert "output_directory" not in summary
    assert "manifest" not in summary
    assert "C:/restricted" not in str(summary)


def _config() -> CatalogBuildConfig:
    return CatalogBuildConfig(
        provider="Synthetic Provider",
        product="Synthetic Product",
        edition="Test",
        dictionary_version="v1",
        policy_id="synthetic-policy",
        policy_version="1",
        built_by="test-actor",
        source_control_commit="synthetic",
    )


def _catalog_record(
    *,
    numeric_type: str = "integer",
    special_values: str = "98: synthetic state",
) -> dict[str, object]:
    return {
        "attribute_sequence": "1",
        "source_sequence": "1",
        "attribute_code": "SYN001",
        "description": "Synthetic attribute",
        "units": "count",
        "field_length": "4",
        "numeric_type": numeric_type,
        "valid_value_expression": "0-100" if numeric_type == "integer" else "",
        "staging_ordinary_min": "0" if numeric_type == "integer" else "",
        "staging_ordinary_max": "100" if numeric_type == "integer" else "",
        "special_value_definitions_raw": special_values,
        "versions": "1",
        "cross_bureau_availability": "",
        "leveling_indicator": "",
        "archive_indicator": "",
        "equifax_availability": "",
        "transunion_availability": "",
        "leveling_status": "",
        "archive_availability": "",
        "source_page": 1,
        "source_row": 1,
        "extraction_method": "pdf_text",
        "extraction_confidence": "high",
        "parser_notes": "",
    }


def _external_descriptor(path: Path) -> SourceDescriptor:
    payload = path.read_bytes()
    return SourceDescriptor(
        path=path.resolve(),
        filename=path.name,
        suffix=path.suffix,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _parse_results(
    pdf_source: SourceDescriptor,
    csv_source: SourceDescriptor,
    record: dict[str, object],
) -> tuple[PdfParseResult, CsvParseResult]:
    return (
        PdfParseResult(
            source=pdf_source,
            records=(dict(record),),
            findings=(),
            pages_processed=1,
            pages_without_text=0,
            extraction_method="pdf_text",
            ocr_used=False,
        ),
        CsvParseResult(
            source=csv_source,
            headers=("attribute_code",),
            records=(dict(record),),
            findings=(),
            rows_processed=1,
            date_conversion_detections=0,
        ),
    )


def test_csv_preserves_multiline_cells_and_detects_staging_bounds() -> None:
    stream = StringIO(
        'name,description,length,valid values,derived_minimum,derived_maximum\n'
        'ABC123,"first line\nsecond line",4,13-Jan,1.0,13.00\n'
    )
    result = parse_csv_stream(stream)

    assert result.records[0]["description"] == "first line\nsecond line"
    assert result.records[0]["staging_ordinary_min"] == "1.0"
    assert result.records[0]["staging_ordinary_max"] == "13.00"
    assert result.date_conversion_detections == 1
    assert looks_like_spreadsheet_date("13-Jan")


def test_pdf_text_fallback_preserves_wrapped_special_meaning_and_large_code() -> None:
    result = parse_pdf_pages(
        [
            """1 ABC123 Synthetic
Description: first line
second line
Length: 4
Valid Values: 1-13
Special Values: 999999999999999: synthetic state
continued meaning"""
        ],
        source=_descriptor("synthetic.pdf", "a"),
    )
    csv_result = replace(
        parse_csv_rows(
            [
                {
                    "name": "ABC123",
                    "description": "first line\nsecond line",
                    "length": "4",
                    "valid values": "13-Jan",
                    "derived_minimum": "1",
                    "derived_maximum": "13",
                }
            ]
        ),
        source=_descriptor("synthetic.csv", "b"),
    )
    attributes, specials, findings, _ = _reconcile_records(
        result,
        csv_result,
        config=_config(),
        built_at="2026-01-01T00:00:00Z",
    )
    config = _config()
    checksum = calculate_catalog_checksum(
        schema_version="1.0",
        catalog_key=config.catalog_key(),
        attributes=attributes,
        special_values=specials,
        reconciliation_findings=findings,
        governance=catalog_governance_payload(
            license_metadata=config.license_payload(),
            restricted_export=True,
            full_catalog_path=".",
        ),
    )
    _finalize_record_checksums(attributes, specials, catalog_checksum=checksum)

    assert attributes[0]["description"] == "first line\nsecond line"
    assert attributes[0]["ordinary_min"] == "1"
    assert attributes[0]["ordinary_max"] == "13"
    assert specials[0]["value_code"] == "999999999999999"
    assert specials[0]["meaning"] == "synthetic state\ncontinued meaning"
    bound_statuses = [
        finding["reconciliation_status"]
        for finding in findings
        if finding.get("finding_type") == "staging_bound_reconciliation"
    ]
    assert bound_statuses == ["exact_match", "exact_match"]


def test_text_special_codes_parse_without_promoting_narrative_labels() -> None:
    text_code_config = replace(
        _config(),
        special_value_pattern=(
            r"^\s*(?P<value>[A-Z])\s*:\s*(?P<meaning>.+?)\s*$"
        ),
    )
    expression = _compile_special_pattern(text_code_config)

    parsed, unresolved = _parse_special_values(
        "U: Unknown response",
        expression=expression,
    )
    assert parsed == [("U", "Unknown response")]
    assert unresolved is False

    pdf_result, csv_result = _parse_results(
        _descriptor("synthetic.pdf", "a"),
        _descriptor("synthetic.csv", "b"),
        _catalog_record(
            numeric_type="text",
            special_values="U: Unknown response",
        ),
    )
    _, specials, _, _ = _reconcile_records(
        pdf_result,
        csv_result,
        config=text_code_config,
        built_at="2026-01-01T00:00:00Z",
    )
    assert [(record["value_code"], record["meaning"]) for record in specials] == [
        ("U", "Unknown response")
    ]

    parsed, unresolved = _parse_special_values(
        "NOTE: no coded value is assigned",
        expression=expression,
    )
    assert parsed == []
    assert unresolved is True


def test_numeric_equivalent_special_codes_collide_after_type_normalization() -> None:
    pdf_result, csv_result = _parse_results(
        _descriptor("synthetic.pdf", "a"),
        _descriptor("synthetic.csv", "b"),
        _catalog_record(special_values="1: First meaning\n1.0: Equivalent meaning"),
    )

    _, specials, findings, counts = _reconcile_records(
        pdf_result,
        csv_result,
        config=_config(),
        built_at="2026-01-01T00:00:00Z",
    )

    assert [record["value_code"] for record in specials] == ["1"]
    collisions = [
        finding
        for finding in findings
        if finding.get("finding_type") == "duplicate_attribute_special_value"
    ]
    assert len(collisions) == 1
    assert collisions[0]["severity"] == "error"
    assert collisions[0]["reconciliation_status"] == "unresolved"
    assert counts["unresolved_conflicts"] == 1


def test_failed_staged_catalog_validation_never_publishes_snapshot(monkeypatch) -> None:
    external_root = Path(tempfile.gettempdir()) / (
        f"atlas-bureau-ingestion-{uuid.uuid4().hex}"
    )
    source_root = external_root / "source"
    output_root = external_root / "output"
    source_root.mkdir(parents=True)
    pdf_path = source_root / "synthetic.pdf"
    csv_path = source_root / "synthetic.csv"
    pdf_path.write_bytes(b"synthetic pdf")
    csv_path.write_text("attribute_code\nSYN001\n", encoding="utf-8")
    pdf_source = _external_descriptor(pdf_path)
    csv_source = _external_descriptor(csv_path)
    pdf_result, csv_result = _parse_results(
        pdf_source,
        csv_source,
        _catalog_record(special_values="1: First meaning\n1.0: Equivalent meaning"),
    )

    monkeypatch.setattr(builder_module, "parse_pdf", lambda *_args, **_kwargs: pdf_result)
    monkeypatch.setattr(builder_module, "parse_csv", lambda *_args, **_kwargs: csv_result)

    try:
        with pytest.raises(
            CatalogBuildError,
            match="complete pre-publication validation",
        ):
            build_catalog(
                pdf_path=pdf_path,
                csv_path=csv_path,
                output_directory=output_root,
                config=_config(),
            )

        assert not list(output_root.rglob("catalog_manifest.json"))
        assert not [path for path in output_root.rglob("*") if ".staging-" in path.name]
    finally:
        shutil.rmtree(external_root, ignore_errors=True)


def test_pdfplumber_first_table_column_mapping_is_deterministic(monkeypatch) -> None:
    row = [
        "1",
        "ABC123",
        "first line\nsecond line",
        "count",
        "4",
        "1-13",
        "99: synthetic exceptional state",
        "v1",
        "bureau-a/bureau-b",
        "",
        "",
        "leveled",
        "archived",
        "",
        "",
    ]

    class _Page:
        def extract_text(self) -> str:
            return "synthetic text-backed page"

        def extract_tables(self) -> list[list[list[str]]]:
            return [[row], []]

    class _Document:
        pages = [_Page()]

        def __enter__(self) -> "_Document":
            return self

        def __exit__(self, *_: object) -> bool:
            return False

    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _: _Document()))
    result = _parse_pdfplumber_tables(
        Path("C:/restricted-synthetic/synthetic.pdf"),
        config=PdfParserConfig(),
        source=_descriptor("synthetic.pdf", "a"),
    )

    assert result is not None
    assert result.extraction_method == "pdfplumber_table"
    assert result.records[0]["description"] == "first line\nsecond line"
    assert result.records[0]["equifax_availability"] == "bureau-a/bureau-b"
    assert result.records[0]["transunion_availability"] == "bureau-a/bureau-b"


def test_ranges_and_normalized_hashes_are_deterministic() -> None:
    assert parse_ordinary_range("1-13") == ("1", "13", None)
    assert parse_ordinary_range("13-Jan")[2] == "possible_spreadsheet_date_conversion"
    first = deterministic_normalized_hash(
        {"created_at": "2026-01-01T00:00:00Z", "value": "same"}
    )
    second = deterministic_normalized_hash(
        {"created_at": "2026-01-02T00:00:00Z", "value": "same"}
    )
    assert first == second


def test_builder_and_loader_use_the_same_complete_key_digest() -> None:
    key = _config().catalog_key()
    assert catalog_key_digest(key) == normalized_key_digest(key)
