"""Deterministic, external-only bureau metadata catalog builder.

The canonical PDF is reconciled with CSV staging rows, but a conflicting CSV
value never overrides the PDF.  Complete extracted content and detailed
findings are written only beneath an explicitly selected external directory.
Publication is a single atomic directory rename performed by ``source_reader``.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from pydantic import ValidationError

from .csv_parser import (
    CANONICAL_FIELDS,
    CsvParseResult,
    CsvParserConfig,
    looks_like_spreadsheet_date,
    normalize_multiline,
    parse_csv,
)
from .pdf_parser import PdfParseResult, PdfParserConfig, parse_pdf
from .normalizer import (
    BureauMetadataNormalizationError,
    catalog_id_for_key,
    catalog_key_digest as normalized_catalog_key_digest,
    catalog_relative_directory,
    normalize_attribute_code,
    normalize_value_code,
)
from .source_reader import (
    SourceDescriptor,
    inspect_external_output_directory,
    paths_overlap,
    sha256_file,
    staged_external_directory,
    write_bytes_fsync,
)
from .types import (
    BureauAttributeDefinition,
    BureauCatalogKey,
    BureauCatalogManifest,
    BureauSpecialValueDefinition,
)
from .validation import (
    BureauCatalogValidationError,
    attribute_record_checksum,
    catalog_governance_payload,
    calculate_catalog_checksum,
    deterministic_normalized_hash as validated_normalized_hash,
    special_definition_checksum,
    special_definition_id,
    validate_catalog,
)


BUILDER_NAME = "atlas_bureau_metadata_catalog_builder"
BUILDER_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"

ATTRIBUTE_FILE = "attribute_definitions.jsonl"
SPECIAL_VALUE_FILE = "special_value_definitions.jsonl"
RECONCILIATION_FILE = "reconciliation_findings.jsonl"
LOOKUP_INDEX_FILE = "lookup_index.json"
VALIDATION_FILE = "catalog_validation_summary.json"
BUILD_LOG_FILE = "catalog_build_log.json"
MANIFEST_FILE = "catalog_manifest.json"

_RECONCILED_FIELDS: tuple[str, ...] = tuple(
    field_name
    for field_name in CANONICAL_FIELDS
    if field_name
    not in {"attribute_code", "staging_ordinary_min", "staging_ordinary_max"}
)
_DECIMAL_TOKEN = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_RANGE_PATTERN = re.compile(
    rf"^\s*(?P<minimum>{_DECIMAL_TOKEN})\s*"
    rf"(?:\.\.|to|through|[-\u2013\u2014])\s*"
    rf"(?P<maximum>{_DECIMAL_TOKEN})\s*$",
    re.IGNORECASE,
)
_DEFAULT_SPECIAL_PATTERN = (
    rf"^\s*(?P<value>{_DECIMAL_TOKEN})\s*"
    r"(?:=|:|\u2013|\u2014|-\s+)\s*(?P<meaning>.+?)\s*$"
)


class CatalogBuildError(RuntimeError):
    """Raised when a catalog cannot be built without a silent decision."""


@dataclass(frozen=True, slots=True)
class CatalogBuildConfig:
    provider: str
    product: str
    edition: str
    dictionary_version: str
    policy_id: str
    policy_version: str
    built_by: str
    source_control_commit: str
    catalog_id: str | None = None
    built_at: str | None = None
    license_classification: str = "restricted_vendor_metadata"
    redistribution_status: str = "prohibited"
    allowed_operations: tuple[str, ...] = (
        "catalog_health",
        "manifest_read",
        "attribute_lookup",
        "special_value_lookup",
        "value_classification",
        "crosswalk_candidate",
    )
    csv_parser: CsvParserConfig = field(default_factory=CsvParserConfig)
    pdf_parser: PdfParserConfig = field(default_factory=PdfParserConfig)
    special_value_pattern: str = _DEFAULT_SPECIAL_PATTERN

    def catalog_key(self) -> dict[str, str]:
        key = {
            "provider": _required_identifier(self.provider, "provider"),
            "product": _required_identifier(self.product, "product"),
            "edition": _required_identifier(self.edition, "edition"),
            "dictionary_version": _required_identifier(
                self.dictionary_version,
                "dictionary_version",
            ),
        }
        return key

    def license_payload(self) -> dict[str, Any]:
        """Materialize the exact restrictive license envelope for hashing."""

        return {
            "classification": self.license_classification,
            "policy_id": _required_identifier(self.policy_id, "policy_id"),
            "policy_version": _required_identifier(
                self.policy_version,
                "policy_version",
            ),
            "allowed_operations": sorted(set(self.allowed_operations)),
            "redistribution_status": self.redistribution_status,
            "source_export_allowed": False,
            "full_catalog_api_allowed": False,
            "tenant_sharing_allowed": False,
            "public_demo_allowed": False,
            "legal_review_required": True,
        }


@dataclass(frozen=True, slots=True)
class CatalogBuildResult:
    output_directory: Path
    manifest_path: Path
    catalog_id: str
    catalog_checksum: str
    attribute_count: int
    special_value_count: int
    validation_finding_count: int
    validation_status: str
    aggregate_summary: Mapping[str, Any]

    def public_summary(self) -> dict[str, Any]:
        """Return aggregate-only CLI/report output."""

        return {
            "ok": self.validation_status != "failed",
            "catalog_id": self.catalog_id,
            "catalog_checksum": self.catalog_checksum,
            "attribute_count": self.attribute_count,
            "special_value_count": self.special_value_count,
            "validation_finding_count": self.validation_finding_count,
            "validation_status": self.validation_status,
            "aggregate_summary": dict(self.aggregate_summary),
        }


def _required_identifier(value: object, field_name: str) -> str:
    normalized = normalize_multiline(value)
    if not normalized or "\n" in normalized:
        raise CatalogBuildError(f"{field_name} must be a non-empty single-line value")
    return normalized


def _canonical_json_bytes(payload: Any, *, pretty: bool = False) -> bytes:
    try:
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CatalogBuildError("catalog payload is not canonical JSON data") from exc
    return (rendered + "\n").encode("utf-8")


def _jsonl_bytes(records: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(_canonical_json_bytes(record) for record in records)


def deterministic_normalized_hash(payload: Any) -> str:
    """Hash normalized content while excluding intentional build timestamps."""

    return validated_normalized_hash(payload)


def catalog_key_digest(catalog_key: Mapping[str, str]) -> str:
    """Return the opaque directory key for one complete catalog identity."""

    return normalized_catalog_key_digest(catalog_key)


def _comparison_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", normalize_multiline(value)).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _decimal_lexeme(value: object) -> str | None:
    text = normalize_multiline(value).replace("\u2212", "-")
    if not text:
        return None
    # Accept conventional thousands separators only when grouping is valid.
    if "," in text:
        if not re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
            return None
        text = text.replace(",", "")
    try:
        decimal = Decimal(text)
    except InvalidOperation:
        return None
    if not decimal.is_finite():
        return None
    rendered = format(decimal, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"-0", "+0", ""} else rendered


def parse_ordinary_range(value: object) -> tuple[str | None, str | None, str | None]:
    """Parse a simple numeric range without treating date text as a range.

    Returns ``(minimum, maximum, finding_type)``.  Complex enumerations remain
    intact in ``valid_range_expression`` and return no numeric bounds.
    """

    text = normalize_multiline(value)
    if not text:
        return None, None, None
    if looks_like_spreadsheet_date(text):
        return None, None, "possible_spreadsheet_date_conversion"
    match = _RANGE_PATTERN.fullmatch(text.replace("\u2212", "-"))
    if not match:
        return None, None, None
    minimum = _decimal_lexeme(match.group("minimum"))
    maximum = _decimal_lexeme(match.group("maximum"))
    if minimum is None or maximum is None:
        return None, None, "malformed_numeric_range"
    if Decimal(minimum) > Decimal(maximum):
        return minimum, maximum, "reversed_numeric_range"
    return minimum, maximum, None


def _split_versions(value: object) -> list[str]:
    text = normalize_multiline(value)
    if not text:
        return []
    return sorted(
        {
            item.strip()
            for item in re.split(r"[,;\n]+", text)
            if item.strip()
        },
        key=lambda item: item.casefold(),
    )


def _safe_int(value: object) -> int | None:
    text = normalize_multiline(value)
    if not text:
        return None
    if not re.fullmatch(r"\d+", text):
        return None
    parsed = int(text)
    return parsed if parsed >= 1 else None


def _split_availability(value: object) -> list[str]:
    text = normalize_multiline(value)
    if not text:
        return []
    return sorted(
        {
            item.strip()
            for item in re.split(r"[,;/\n]+", text)
            if item.strip()
        },
        key=lambda item: item.casefold(),
    )


def _numeric_type(value: object) -> str:
    text = normalize_multiline(value).casefold()
    aliases = {
        "int": "integer",
        "integer": "integer",
        "whole number": "integer",
        "decimal": "decimal",
        "numeric": "decimal",
        "number": "decimal",
        "float": "decimal",
        "string": "text",
        "character": "text",
        "char": "text",
        "text": "text",
        "date": "date",
    }
    return aliases.get(text, "unknown")


def _sequence_sort_key(record: Mapping[str, object]) -> tuple[int, int | str, str]:
    sequence = normalize_multiline(record.get("attribute_sequence", ""))
    code = normalize_multiline(record.get("attribute_code", ""))
    if sequence.isdigit():
        return (0, int(sequence), code)
    return (1, sequence.casefold(), code)


def _index_unique_records(
    records: Sequence[Mapping[str, object]],
    *,
    source_role: str,
    fail_on_duplicate: bool,
) -> tuple[dict[str, Mapping[str, object]], list[dict[str, Any]]]:
    index: dict[str, Mapping[str, object]] = {}
    findings: list[dict[str, Any]] = []
    for record in records:
        code = normalize_multiline(record.get("attribute_code", ""))
        if not code:
            findings.append(
                {
                    "finding_type": "missing_attribute_code",
                    "severity": "error",
                    "source_role": source_role,
                    "source_sequence": normalize_multiline(record.get("source_sequence", "")),
                }
            )
            continue
        if code in index:
            findings.append(
                {
                    "finding_type": "duplicate_attribute_code",
                    "severity": "error",
                    "source_role": source_role,
                    "attribute_code": code,
                    "source_sequence": normalize_multiline(record.get("source_sequence", "")),
                }
            )
            if fail_on_duplicate:
                raise CatalogBuildError("canonical PDF contains duplicate attribute codes")
            continue
        index[code] = record
    return index, findings


def _sequence_index(
    records: Iterable[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    result: dict[str, list[Mapping[str, object]]] = {}
    for record in records:
        sequence = normalize_multiline(record.get("source_sequence", ""))
        if sequence:
            result.setdefault(sequence, []).append(record)
    return result


def _field_reconciliation(
    *,
    attribute_code: str,
    source_sequence: str,
    field_name: str,
    pdf_value: object,
    csv_value: object,
) -> dict[str, Any]:
    pdf_text = normalize_multiline(pdf_value)
    csv_text = normalize_multiline(csv_value)
    if pdf_text and csv_text:
        if pdf_text == csv_text:
            status = "exact_match"
        elif _comparison_text(pdf_text) == _comparison_text(csv_text):
            status = "normalized_formatting_difference"
        else:
            status = "substantive_conflict"
        selected = pdf_text
        basis = "canonical_pdf"
    elif pdf_text:
        status = "pdf_only_value"
        selected = pdf_text
        basis = "canonical_pdf"
    elif csv_text:
        status = "csv_value_missing_from_pdf"
        selected = ""
        basis = "unresolved_pdf_missing"
    else:
        status = "both_empty"
        selected = ""
        basis = "no_value"
    # A substantive CSV disagreement is reviewable evidence, not an unresolved
    # canonical choice: this catalog's declared contract makes the PDF
    # authoritative and preserves both values plus the selection basis below.
    # Absence of a PDF value remains an error because there is then no canonical
    # value to select.
    severity = (
        "error"
        if status == "csv_value_missing_from_pdf"
        else "warning"
        if status in {"normalized_formatting_difference", "substantive_conflict"}
        else "info"
    )
    return {
        "finding_type": "field_reconciliation",
        "severity": severity,
        "attribute_code": attribute_code,
        "source_sequence": source_sequence,
        "field": field_name,
        "pdf_value": pdf_text,
        "csv_value": csv_text,
        "selected_canonical_value": selected,
        "selection_basis": basis,
        "reconciliation_status": status,
    }


def _attribute_status(field_findings: Sequence[Mapping[str, Any]], *, matched: bool) -> str:
    statuses = {str(item.get("reconciliation_status") or "") for item in field_findings}
    if statuses.intersection(
        {
            "substantive_conflict",
            "csv_value_missing_from_pdf",
            "malformed_staging_bound",
            "canonical_bound_not_parseable",
        }
    ):
        return "requires_review"
    if not matched:
        return "pdf_only"
    if "normalized_formatting_difference" in statuses:
        return "reconciled_formatting_difference"
    return "reconciled"


def _source_reference(
    source: SourceDescriptor,
    *,
    locator: str,
    extraction_method: str,
    confidence: str,
) -> dict[str, str]:
    return {
        "source_document_sha256": source.sha256,
        "source_locator": locator,
        "extraction_method": extraction_method,
        "confidence": confidence,
    }


def _parse_special_values(
    raw_value: object,
    *,
    expression: re.Pattern[str],
) -> tuple[list[tuple[str, str]], bool]:
    """Parse line-oriented value/meaning pairs while preserving continuations."""

    text = normalize_multiline(raw_value)
    if not text:
        return [], False
    # The configured expression, rather than the presence of a decimal token,
    # is the authority for deciding whether a line contains a code.  The
    # numeric-source default is intentionally narrow. Providers with text
    # special codes must supply their exact code alphabet through
    # ``special_value_pattern``; this avoids guessing whether an alphabetic
    # label is a code or narrative while still allowing codes such as ``U``.
    parsed: list[tuple[str, str]] = []
    current_value: str | None = None
    current_meaning: list[str] = []
    unparsed = False
    for line in text.split("\n"):
        match = expression.fullmatch(line.strip())
        if match:
            if current_value is not None:
                parsed.append((current_value, normalize_multiline("\n".join(current_meaning))))
            current_value = normalize_multiline(match.group("value"))
            current_meaning = [normalize_multiline(match.group("meaning"))]
        elif current_value is not None:
            current_meaning.append(line.strip())
        elif line.strip():
            unparsed = True
    if current_value is not None:
        parsed.append((current_value, normalize_multiline("\n".join(current_meaning))))
    if not parsed:
        unparsed = True
    return parsed, unparsed


def _compile_special_pattern(config: CatalogBuildConfig) -> re.Pattern[str]:
    try:
        expression = re.compile(config.special_value_pattern)
    except re.error as exc:
        raise CatalogBuildError("special-value parser configuration is invalid") from exc
    required = {"value", "meaning"}
    if not required.issubset(expression.groupindex):
        raise CatalogBuildError("special-value pattern must define value and meaning groups")
    return expression


def _reconcile_records(
    pdf_result: PdfParseResult,
    csv_result: CsvParseResult,
    *,
    config: CatalogBuildConfig,
    built_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    if pdf_result.source is None or csv_result.source is None:
        raise CatalogBuildError("external source descriptors are required for a production build")
    sorted_pdf = sorted(pdf_result.records, key=_sequence_sort_key)
    pdf_by_code, findings = _index_unique_records(
        sorted_pdf,
        source_role="canonical_pdf",
        fail_on_duplicate=True,
    )
    csv_by_code, csv_index_findings = _index_unique_records(
        csv_result.records,
        source_role="csv_staging",
        fail_on_duplicate=False,
    )
    findings.extend(csv_index_findings)
    csv_by_sequence = _sequence_index(csv_result.records)
    used_csv_codes: set[str] = set()
    attributes: list[dict[str, Any]] = []
    specials: list[dict[str, Any]] = []
    special_pattern = _compile_special_pattern(config)
    catalog_key = config.catalog_key()
    counts = {
        "exact_code_matches": 0,
        "source_sequence_matches": 0,
        "pdf_only_attributes": 0,
        "csv_only_attributes": 0,
        "normalized_formatting_differences": 0,
        "substantive_conflicts": 0,
        "unresolved_conflicts": 0,
        "date_conversion_detections": csv_result.date_conversion_detections,
    }

    for pdf_record in sorted_pdf:
        code = normalize_attribute_code(
            normalize_multiline(pdf_record.get("attribute_code", ""))
        )
        if not code or pdf_by_code.get(code) is not pdf_record:
            continue
        sequence = normalize_multiline(pdf_record.get("source_sequence", ""))
        csv_record = csv_by_code.get(code)
        match_basis = "exact_code"
        if csv_record is None and sequence:
            candidates = csv_by_sequence.get(sequence, [])
            if len(candidates) == 1:
                csv_record = candidates[0]
                match_basis = "source_sequence"
                findings.append(
                    {
                        "finding_type": "attribute_code_conflict_at_source_sequence",
                        "severity": "error",
                        "attribute_code": code,
                        "csv_attribute_code": normalize_multiline(
                            csv_record.get("attribute_code", "")
                        ),
                        "source_sequence": sequence,
                        "selected_canonical_value": code,
                        "selection_basis": "canonical_pdf",
                        "reconciliation_status": "requires_review",
                    }
                )
                counts["source_sequence_matches"] += 1
                counts["substantive_conflicts"] += 1
            elif len(candidates) > 1:
                findings.append(
                    {
                        "finding_type": "ambiguous_source_sequence_match",
                        "severity": "error",
                        "attribute_code": code,
                        "source_sequence": sequence,
                        "candidate_count": len(candidates),
                        "reconciliation_status": "unresolved",
                    }
                )
                counts["unresolved_conflicts"] += 1
        if csv_record is not None:
            csv_code = normalize_multiline(csv_record.get("attribute_code", ""))
            used_csv_codes.add(csv_code)
            if match_basis == "exact_code":
                counts["exact_code_matches"] += 1
        else:
            counts["pdf_only_attributes"] += 1
            findings.append(
                {
                    "finding_type": "pdf_only_attribute",
                    "severity": "warning",
                    "attribute_code": code,
                    "source_sequence": sequence,
                    "selection_basis": "canonical_pdf",
                    "reconciliation_status": "pdf_only",
                }
            )

        field_findings: list[dict[str, Any]] = []
        selected_values: dict[str, str] = {}
        for field_name in _RECONCILED_FIELDS:
            field_finding = _field_reconciliation(
                attribute_code=code,
                source_sequence=sequence,
                field_name=field_name,
                pdf_value=pdf_record.get(field_name, ""),
                csv_value=csv_record.get(field_name, "") if csv_record else "",
            )
            field_findings.append(field_finding)
            findings.append(field_finding)
            selected_values[field_name] = str(field_finding["selected_canonical_value"])
            status = field_finding["reconciliation_status"]
            if status == "normalized_formatting_difference":
                counts["normalized_formatting_differences"] += 1
            elif status == "substantive_conflict":
                counts["substantive_conflicts"] += 1
            elif status == "csv_value_missing_from_pdf":
                counts["unresolved_conflicts"] += 1

        minimum, maximum, range_finding = parse_ordinary_range(
            selected_values.get("valid_value_expression", "")
        )
        if range_finding:
            findings.append(
                {
                    "finding_type": range_finding,
                    "severity": (
                        "error"
                        if range_finding != "possible_spreadsheet_date_conversion"
                        else "warning"
                    ),
                    "source_role": "canonical_pdf",
                    "attribute_code": code,
                    "source_sequence": sequence,
                    "field": "valid_value_expression",
                }
            )

        if csv_record is not None:
            for field_name, canonical_bound in (
                ("staging_ordinary_min", minimum),
                ("staging_ordinary_max", maximum),
            ):
                staging_text = normalize_multiline(csv_record.get(field_name, ""))
                if not staging_text:
                    continue
                staging_bound = _decimal_lexeme(staging_text)
                if staging_bound is None:
                    bound_status = "malformed_staging_bound"
                    severity = "error"
                    counts["unresolved_conflicts"] += 1
                elif canonical_bound is None:
                    bound_status = "canonical_bound_not_parseable"
                    severity = "warning"
                    counts["unresolved_conflicts"] += 1
                elif staging_bound == canonical_bound:
                    bound_status = "exact_match"
                    severity = "info"
                else:
                    bound_status = "substantive_conflict"
                    # The derived CSV bound is staging-only validation evidence;
                    # the parsed PDF bound is retained as the explicit canonical
                    # value and the discrepancy remains reviewable.
                    severity = "warning"
                    counts["substantive_conflicts"] += 1
                bound_finding = {
                        "finding_type": "staging_bound_reconciliation",
                        "severity": severity,
                        "attribute_code": code,
                        "source_sequence": sequence,
                        "field": field_name,
                        "pdf_value": canonical_bound or "",
                        "csv_value": staging_text,
                        "selected_canonical_value": canonical_bound or "",
                        "selection_basis": "canonical_pdf",
                        "reconciliation_status": bound_status,
                    }
                findings.append(bound_finding)
                field_findings.append(bound_finding)

        field_length = _safe_int(selected_values.get("field_length", ""))
        if selected_values.get("field_length") and field_length is None:
            findings.append(
                {
                    "finding_type": "malformed_field_length",
                    "severity": "error",
                    "attribute_code": code,
                    "source_sequence": sequence,
                    "field": "field_length",
                }
            )

        source_page = int(pdf_record.get("source_page") or 0)
        extraction_method = normalize_multiline(
            pdf_record.get("extraction_method", pdf_result.extraction_method)
        )
        extraction_confidence = normalize_multiline(
            pdf_record.get("extraction_confidence", "unreviewed")
        )
        source_reference = _source_reference(
            pdf_result.source,
            locator=f"page:{source_page}" if source_page else f"sequence:{sequence}",
            extraction_method=extraction_method or pdf_result.extraction_method,
            confidence=extraction_confidence or "unreviewed",
        )
        status = _attribute_status(field_findings, matched=csv_record is not None)
        combined_availability = selected_values.get("cross_bureau_availability", "")
        if not combined_availability:
            combined_availability = "\n".join(
                value
                for value in (
                    selected_values.get("equifax_availability", ""),
                    selected_values.get("transunion_availability", ""),
                )
                if value
            )
        sequence_number = _safe_int(sequence)
        if sequence_number is None:
            raise CatalogBuildError("canonical PDF attribute sequence is not a positive integer")
        parser_note_text = normalize_multiline(pdf_record.get("parser_notes", ""))
        numeric_type = _numeric_type(selected_values.get("numeric_type", ""))
        record = {
            "catalog_key": catalog_key,
            "sequence": sequence_number,
            "attribute_code": code,
            "description": selected_values.get("description", ""),
            "numeric_type": numeric_type,
            "units": selected_values.get("units", "") or None,
            "field_length": field_length,
            "valid_range_expression": selected_values.get("valid_value_expression", "") or None,
            "ordinary_min": minimum,
            "ordinary_max": maximum,
            "valid_values": [],
            "applicable_versions": _split_versions(selected_values.get("versions", "")),
            "cross_bureau_availability": _split_availability(combined_availability),
            "leveling_indicator": (
                selected_values.get("leveling_indicator", "")
                or selected_values.get("leveling_status", "")
                or None
            ),
            "archive_indicator": (
                selected_values.get("archive_indicator", "")
                or selected_values.get("archive_availability", "")
                or None
            ),
            "source_references": [source_reference],
            "source_row": _safe_int(pdf_record.get("source_row", "")),
            "reconciliation_status": (
                "conflict"
                if status == "requires_review"
                else "pdf_only"
                if status == "pdf_only"
                else "matched"
            ),
            "review_status": "unreviewed",
            "parser_notes": tuple(parser_note_text.split("\n")) if parser_note_text else (),
            "created_at": built_at,
        }
        attributes.append(record)

        parsed_specials, special_unparsed = _parse_special_values(
            selected_values.get("special_value_definitions_raw", ""),
            expression=special_pattern,
        )
        if special_unparsed:
            findings.append(
                {
                    "finding_type": "unresolved_special_value_definition",
                    "severity": "warning",
                    "attribute_code": code,
                    "source_sequence": sequence,
                    "reconciliation_status": "requires_review",
                }
            )
        seen_special_values: set[str] = set()
        for source_order, (value_code, meaning) in enumerate(parsed_specials, start=1):
            try:
                normalized_value_code = normalize_value_code(value_code, numeric_type)
            except BureauMetadataNormalizationError:
                findings.append(
                    {
                        "finding_type": "invalid_attribute_special_value_code",
                        "severity": "error",
                        "attribute_code": code,
                        "source_sequence": sequence,
                        "special_source_sequence": source_order,
                        "reconciliation_status": "unresolved",
                    }
                )
                counts["unresolved_conflicts"] += 1
                continue
            if normalized_value_code in seen_special_values:
                findings.append(
                    {
                        "finding_type": "duplicate_attribute_special_value",
                        "severity": "error",
                        "attribute_code": code,
                        "source_sequence": sequence,
                        "special_source_sequence": source_order,
                        "reconciliation_status": "unresolved",
                    }
                )
                counts["unresolved_conflicts"] += 1
                continue
            seen_special_values.add(normalized_value_code)
            definition_identity = {
                "catalog_key": catalog_key,
                "attribute_code": code,
                "value_code": normalized_value_code,
            }
            specials.append(
                {
                    "catalog_key": catalog_key,
                    "attribute_code": code,
                    "value_code": normalized_value_code,
                    "meaning": meaning,
                    "semantic_family": "other",
                    "semantic_confidence": "unreviewed",
                    "source_page": source_page or None,
                    "source_sequence": source_order,
                    "source_references": [source_reference],
                    "is_bureau_special": True,
                    "is_true_null": False,
                    "is_parse_failure": False,
                    "is_ordinary_outlier": False,
                    "analyst_review_required": True,
                    "review_status": "unreviewed",
                    "treatment_recommendation_status": "unreviewed",
                    "treatment_policy_reference": None,
                    "created_at": built_at,
                    "definition_id": special_definition_id(definition_identity),
                }
            )

    for code, csv_record in sorted(csv_by_code.items(), key=lambda item: item[0]):
        if code in used_csv_codes:
            continue
        counts["csv_only_attributes"] += 1
        findings.append(
            {
                "finding_type": "csv_only_attribute",
                "severity": "error",
                "attribute_code": code,
                "source_sequence": normalize_multiline(csv_record.get("source_sequence", "")),
                "selection_basis": "unresolved_without_canonical_pdf",
                "reconciliation_status": "unresolved",
            }
        )
        counts["unresolved_conflicts"] += 1

    numeric_sequences = sorted(
        {
            int(normalize_multiline(record.get("attribute_sequence", "")))
            for record in sorted_pdf
            if normalize_multiline(record.get("attribute_sequence", "")).isdigit()
        }
    )
    if numeric_sequences:
        for previous, current in zip(numeric_sequences, numeric_sequences[1:]):
            if current > previous + 1:
                findings.append(
                    {
                        "finding_type": "attribute_sequence_gap",
                        "severity": "warning",
                        "gap_start": previous + 1,
                        "gap_end": current - 1,
                        "gap_size": current - previous - 1,
                    }
                )

    attributes.sort(key=_sequence_sort_key)
    specials.sort(
        key=lambda item: (
            normalize_multiline(item.get("attribute_code", "")),
            normalize_multiline(item.get("value_code", "")),
            int(item.get("source_sequence") or 0),
        )
    )
    findings.sort(
        key=lambda item: (
            str(item.get("attribute_code") or ""),
            str(item.get("source_sequence") or ""),
            str(item.get("field") or ""),
            str(item.get("finding_type") or ""),
        )
    )
    return attributes, specials, findings, counts


def _finalize_record_checksums(
    attributes: list[dict[str, Any]],
    specials: list[dict[str, Any]],
    *,
    catalog_checksum: str,
) -> None:
    for index, record in enumerate(attributes):
        record["catalog_checksum"] = catalog_checksum
        record["record_checksum"] = attribute_record_checksum(record)
        attributes[index] = BureauAttributeDefinition.model_validate(record).model_dump(
            mode="json"
        )
    for index, record in enumerate(specials):
        record["catalog_checksum"] = catalog_checksum
        record["definition_checksum"] = special_definition_checksum(record)
        specials[index] = BureauSpecialValueDefinition.model_validate(record).model_dump(
            mode="json"
        )


def _file_descriptor(path: Path, *, record_count: int, media_type: str) -> dict[str, Any]:
    return {
        "relative_path": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "record_count": record_count,
        "media_type": media_type,
    }


def _write_payload(path: Path, payload: bytes) -> None:
    write_bytes_fsync(path, payload)


def _decode_staged_jsonl(
    payload: bytes,
    *,
    model: type[BureauAttributeDefinition] | type[BureauSpecialValueDefinition] | None,
    expected_count: int,
) -> tuple[Any, ...]:
    text = payload.decode("utf-8")
    records: list[Any] = []
    for line in text.splitlines():
        if not line.strip():
            raise CatalogBuildError("staged catalog JSONL contains a blank record")
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise CatalogBuildError("staged catalog JSONL record is not an object")
        records.append(model.model_validate(raw) if model is not None else raw)
    if len(records) != expected_count:
        raise CatalogBuildError("staged catalog record count is contradictory")
    return tuple(records)


def _validate_staged_catalog_contract(
    staging: Path,
    *,
    expected_key: BureauCatalogKey,
    expected_checksum: str,
) -> None:
    """Read back and validate the complete staged snapshot before publication."""

    try:
        manifest_raw = json.loads((staging / MANIFEST_FILE).read_text(encoding="utf-8"))
        if not isinstance(manifest_raw, dict):
            raise CatalogBuildError("staged catalog manifest is not an object")
        manifest = BureauCatalogManifest.model_validate(manifest_raw)

        descriptor_payloads: dict[str, bytes] = {}
        descriptors = (
            manifest.attribute_file,
            manifest.special_value_file,
            manifest.reconciliation_file,
            manifest.lookup_index_file,
            manifest.validation_file,
            manifest.build_log_file,
        )
        staging_root = staging.resolve(strict=True)
        for descriptor in descriptors:
            if descriptor is None:
                continue
            artifact_path = (staging / descriptor.relative_path).resolve(strict=True)
            try:
                artifact_path.relative_to(staging_root)
            except ValueError as exc:
                raise CatalogBuildError(
                    "staged catalog artifact escapes its publication directory"
                ) from exc
            if not artifact_path.is_file():
                raise CatalogBuildError("staged catalog artifact is not a regular file")
            payload = artifact_path.read_bytes()
            if (
                len(payload) != descriptor.size_bytes
                or sha256_file(artifact_path) != descriptor.sha256
            ):
                raise CatalogBuildError(
                    "staged catalog artifact does not match its descriptor"
                )
            descriptor_payloads[descriptor.relative_path] = payload

        attributes = _decode_staged_jsonl(
            descriptor_payloads[manifest.attribute_file.relative_path],
            model=BureauAttributeDefinition,
            expected_count=manifest.attribute_file.record_count,
        )
        specials = _decode_staged_jsonl(
            descriptor_payloads[manifest.special_value_file.relative_path],
            model=BureauSpecialValueDefinition,
            expected_count=manifest.special_value_file.record_count,
        )
        findings: tuple[Any, ...] = ()
        if manifest.reconciliation_file is not None:
            findings = _decode_staged_jsonl(
                descriptor_payloads[manifest.reconciliation_file.relative_path],
                model=None,
                expected_count=manifest.reconciliation_file.record_count,
            )

        for descriptor in (
            manifest.lookup_index_file,
            manifest.validation_file,
            manifest.build_log_file,
        ):
            if descriptor is None:
                continue
            decoded = json.loads(
                descriptor_payloads[descriptor.relative_path].decode("utf-8")
            )
            if not isinstance(decoded, dict):
                raise CatalogBuildError("staged catalog JSON artifact is not an object")

        validate_catalog(
            manifest=manifest,
            expected_key=expected_key,
            expected_checksum=expected_checksum,
            attributes=attributes,
            special_values=specials,
            reconciliation_findings=findings,
        )
    except CatalogBuildError:
        raise
    except (
        BureauCatalogValidationError,
        BureauMetadataNormalizationError,
        FileNotFoundError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        UnicodeError,
        ValidationError,
        ValueError,
    ) as exc:
        raise CatalogBuildError(
            "staged catalog failed complete pre-publication validation"
        ) from exc


def _validation_status(findings: Sequence[Mapping[str, Any]]) -> str:
    if any(str(item.get("severity")) == "error" for item in findings):
        return "failed"
    if any(str(item.get("severity")) == "warning" for item in findings):
        return "passed_with_warnings"
    return "passed"


def _aggregate_findings(findings: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    aggregate: dict[str, int] = {}
    for finding in findings:
        finding_type = str(finding.get("finding_type") or "unknown")
        aggregate[finding_type] = aggregate.get(finding_type, 0) + 1
    return dict(sorted(aggregate.items()))


def build_catalog(
    *,
    pdf_path: str | Path,
    csv_path: str | Path,
    output_directory: str | Path,
    config: CatalogBuildConfig,
) -> CatalogBuildResult:
    """Build and atomically publish one exact catalog version externally."""

    output_root = inspect_external_output_directory(output_directory)
    if output_root.exists() and not output_root.is_dir():
        raise CatalogBuildError("external output root is not a directory")
    pdf_result = parse_pdf(pdf_path, config=config.pdf_parser)
    csv_result = parse_csv(csv_path, config=config.csv_parser)
    if pdf_result.source is None or csv_result.source is None:
        raise CatalogBuildError("production build requires explicit external sources")
    if paths_overlap(pdf_result.source.path, csv_result.source.path):
        raise CatalogBuildError("canonical PDF and CSV staging source must be distinct files")
    built_at = config.built_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    attributes, specials, reconciliation, counts = _reconcile_records(
        pdf_result,
        csv_result,
        config=config,
        built_at=built_at,
    )
    parser_findings = [item.to_mapping() for item in pdf_result.findings]
    parser_findings.extend(item.to_mapping() for item in csv_result.findings)
    reconciliation.extend(parser_findings)
    reconciliation.sort(
        key=lambda item: (
            str(item.get("attribute_code") or ""),
            str(item.get("source_sequence") or ""),
            str(item.get("field") or ""),
            str(item.get("finding_type") or ""),
        )
    )

    license_payload = config.license_payload()
    governance_payload = catalog_governance_payload(
        license_metadata=license_payload,
        restricted_export=True,
        full_catalog_path=".",
    )

    catalog_checksum = calculate_catalog_checksum(
        schema_version=SCHEMA_VERSION,
        catalog_key=config.catalog_key(),
        attributes=attributes,
        special_values=specials,
        reconciliation_findings=reconciliation,
        governance=governance_payload,
    )
    catalog_id = config.catalog_id or catalog_id_for_key(config.catalog_key())
    relative_directory = catalog_relative_directory(
        config.catalog_key(),
        catalog_checksum,
    )
    final_directory = inspect_external_output_directory(
        output_root.joinpath(*relative_directory.parts)
    )
    if paths_overlap(final_directory, pdf_result.source.path) or paths_overlap(
        final_directory, csv_result.source.path
    ):
        raise CatalogBuildError("final catalog directory must not overlap an input source")
    _finalize_record_checksums(attributes, specials, catalog_checksum=catalog_checksum)

    validation_status = _validation_status(reconciliation)
    finding_counts = _aggregate_findings(reconciliation)
    aggregate_summary: dict[str, Any] = {
        "pages_processed": pdf_result.pages_processed,
        "pages_without_text": pdf_result.pages_without_text,
        "ocr_used": pdf_result.ocr_used,
        "csv_rows_processed": csv_result.rows_processed,
        "pdf_attribute_records": len(pdf_result.records),
        "reconciled_attributes": len(attributes),
        "unique_codes": len({item["attribute_code"] for item in attributes}),
        "special_value_definitions": len(specials),
        **counts,
        "finding_counts": finding_counts,
    }
    validation_summary = {
        "schema_version": SCHEMA_VERSION,
        "catalog_id": catalog_id,
        "catalog_key": config.catalog_key(),
        "catalog_checksum": catalog_checksum,
        "validation_status": validation_status,
        "attribute_count": len(attributes),
        "special_value_count": len(specials),
        "validation_finding_count": len(reconciliation),
        "aggregate_summary": aggregate_summary,
    }
    lookup_index = {
        "schema_version": SCHEMA_VERSION,
        "catalog_id": catalog_id,
        "catalog_key": config.catalog_key(),
        "catalog_checksum": catalog_checksum,
        "attributes": {
            item["attribute_code"]: {"line": index + 1}
            for index, item in enumerate(attributes)
        },
        "special_values": {
            f"{item['attribute_code']}\u001f{item['value_code']}": {"line": index + 1}
            for index, item in enumerate(specials)
        },
    }
    build_log = {
        "schema_version": SCHEMA_VERSION,
        "builder_name": BUILDER_NAME,
        "builder_version": BUILDER_VERSION,
        "built_at": built_at,
        "catalog_id": catalog_id,
        "catalog_checksum": catalog_checksum,
        "validation_status": validation_status,
        "aggregate_summary": aggregate_summary,
        "content_logged": False,
    }

    with staged_external_directory(final_directory) as staging:
        attribute_path = staging / ATTRIBUTE_FILE
        special_path = staging / SPECIAL_VALUE_FILE
        reconciliation_path = staging / RECONCILIATION_FILE
        lookup_path = staging / LOOKUP_INDEX_FILE
        validation_path = staging / VALIDATION_FILE
        build_log_path = staging / BUILD_LOG_FILE
        _write_payload(attribute_path, _jsonl_bytes(attributes))
        _write_payload(special_path, _jsonl_bytes(specials))
        _write_payload(reconciliation_path, _jsonl_bytes(reconciliation))
        _write_payload(lookup_path, _canonical_json_bytes(lookup_index, pretty=True))
        _write_payload(validation_path, _canonical_json_bytes(validation_summary, pretty=True))
        _write_payload(build_log_path, _canonical_json_bytes(build_log, pretty=True))

        descriptors = {
            "attribute_file": _file_descriptor(
                attribute_path,
                record_count=len(attributes),
                media_type="application/x-ndjson",
            ),
            "special_value_file": _file_descriptor(
                special_path,
                record_count=len(specials),
                media_type="application/x-ndjson",
            ),
            "reconciliation_file": _file_descriptor(
                reconciliation_path,
                record_count=len(reconciliation),
                media_type="application/x-ndjson",
            ),
            "lookup_index_file": _file_descriptor(
                lookup_path,
                record_count=len(attributes) + len(specials),
                media_type="application/json",
            ),
            "validation_file": _file_descriptor(
                validation_path,
                record_count=1,
                media_type="application/json",
            ),
            "build_log_file": _file_descriptor(
                build_log_path,
                record_count=1,
                media_type="application/json",
            ),
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "catalog_id": catalog_id,
            "catalog_key": config.catalog_key(),
            "catalog_checksum": catalog_checksum,
            **descriptors,
            "source_files": [
                {
                    "role": "canonical_pdf",
                    "filename": pdf_result.source.filename,
                    "suffix": pdf_result.source.suffix,
                    "sha256": pdf_result.source.sha256,
                    "size_bytes": pdf_result.source.size_bytes,
                },
                {
                    "role": "csv_staging",
                    "filename": csv_result.source.filename,
                    "suffix": csv_result.source.suffix,
                    "sha256": csv_result.source.sha256,
                    "size_bytes": csv_result.source.size_bytes,
                },
            ],
            "attribute_count": len(attributes),
            "special_value_count": len(specials),
            "validation_finding_count": len(reconciliation),
            "parse_warning_count": sum(
                1 for item in reconciliation if item.get("severity") == "warning"
            ),
            "reconciliation_conflict_count": counts["substantive_conflicts"],
            "unresolved_count": counts["unresolved_conflicts"],
            "validation_status": validation_status,
            "license": license_payload,
            "restricted_export": True,
            "full_catalog_path": ".",
            "builder_name": BUILDER_NAME,
            "builder_version": BUILDER_VERSION,
            "built_at": built_at,
            "built_by": _required_identifier(config.built_by, "built_by"),
            "source_control_commit": _required_identifier(
                config.source_control_commit,
                "source_control_commit",
            ),
        }
        manifest = BureauCatalogManifest.model_validate(manifest).model_dump(mode="json")
        manifest["license"]["allowed_operations"] = sorted(
            manifest["license"]["allowed_operations"]
        )
        _write_payload(staging / MANIFEST_FILE, _canonical_json_bytes(manifest, pretty=True))
        _validate_staged_catalog_contract(
            staging,
            expected_key=BureauCatalogKey.model_validate(config.catalog_key()),
            expected_checksum=catalog_checksum,
        )

    return CatalogBuildResult(
        output_directory=final_directory,
        manifest_path=final_directory / MANIFEST_FILE,
        catalog_id=catalog_id,
        catalog_checksum=catalog_checksum,
        attribute_count=len(attributes),
        special_value_count=len(specials),
        validation_finding_count=len(reconciliation),
        validation_status=validation_status,
        aggregate_summary=aggregate_summary,
    )


__all__ = [
    "ATTRIBUTE_FILE",
    "BUILDER_NAME",
    "BUILDER_VERSION",
    "BUILD_LOG_FILE",
    "CatalogBuildConfig",
    "CatalogBuildError",
    "CatalogBuildResult",
    "LOOKUP_INDEX_FILE",
    "MANIFEST_FILE",
    "RECONCILIATION_FILE",
    "SCHEMA_VERSION",
    "SPECIAL_VALUE_FILE",
    "VALIDATION_FILE",
    "build_catalog",
    "catalog_key_digest",
    "deterministic_normalized_hash",
    "parse_ordinary_range",
]
