"""Deterministic text/table extraction for canonical bureau dictionary PDFs.

The parser uses the repository's existing PyPDF2 dependency and never invokes
OCR.  It offers a configurable labelled-block and table-row strategy so a
provider layout can be described without embedding vendor text in source code.
Extracted values remain strings and all findings are content-free categories.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .csv_parser import (
    CANONICAL_FIELDS,
    DEFAULT_COLUMN_ALIASES,
    normalize_header,
    normalize_multiline,
)
from .source_reader import SourceDescriptor, inspect_external_source


class BureauPdfParseError(RuntimeError):
    """Raised when ordinary PDF text extraction cannot produce a safe result."""


# Bureau products do not universally use a letters-then-digits convention.
# Keep the default structural (uppercase leading character plus a bounded
# identifier alphabet); provider-specific layouts can still tighten it through
# ``PdfParserConfig``.  The numeric source sequence remains the independent
# table-row discriminator, so broadening this identifier shape cannot turn a
# repeated header into an attribute record.
_DEFAULT_CODE_PATTERN = r"(?P<code>[A-Z][A-Z0-9._-]{2,31})"


@dataclass(frozen=True, slots=True)
class PdfParserConfig:
    """Provider layout configuration for deterministic text extraction.

    ``field_patterns`` may contain one regular expression per canonical field.
    Each expression is applied to a single record block with ``MULTILINE`` and
    ``DOTALL`` enabled.  A named ``value`` group is preferred; otherwise the
    first capture group is used.  This supports exact first-source layouts via
    an external JSON configuration without hardcoding licensed labels here.
    """

    attribute_code_pattern: str = _DEFAULT_CODE_PATTERN
    record_line_pattern: str = (
        r"^\s*(?:(?P<sequence>\d{1,7})\s+)?"
        + _DEFAULT_CODE_PATTERN
        + r"(?:\s+|$)(?P<rest>.*)$"
    )
    field_aliases: Mapping[str, Sequence[str]] = field(default_factory=dict)
    field_patterns: Mapping[str, str] = field(default_factory=dict)
    table_columns_after_code: tuple[str, ...] = (
        "description",
        "units",
        "field_length",
        "numeric_type",
        "valid_value_expression",
        "special_value_definitions_raw",
        "versions",
        "equifax_availability",
        "transunion_availability",
        "leveling_status",
        "archive_availability",
    )
    pdfplumber_table_index: int = 0
    pdfplumber_column_map: Mapping[str, int] = field(
        default_factory=lambda: {
            "attribute_sequence": 0,
            "attribute_code": 1,
            "description": 2,
            "units": 3,
            "field_length": 4,
            "valid_value_expression": 5,
            "special_value_definitions_raw": 6,
            "versions": 7,
            # The first registered source exposes one combined cross-bureau
            # cell.  Preserve it through both staging aliases; the builder
            # deduplicates it into the provider-neutral tuple.
            "equifax_availability": 8,
            "transunion_availability": 8,
            "leveling_status": 11,
            "archive_availability": 12,
        }
    )
    prefer_pdfplumber_tables: bool = True
    allow_text_fallback: bool = True
    table_separator_pattern: str = r"(?:\t+|\s{2,})"
    extraction_method: str = "pdf_text"
    require_at_least_one_record: bool = True
    preserve_unparsed_text: bool = False


@dataclass(frozen=True, slots=True)
class PdfParseFinding:
    finding_type: str
    severity: str
    source_page: int | None = None
    source_sequence: str | None = None
    field: str | None = None

    def to_mapping(self) -> dict[str, str | int | None]:
        return {
            "finding_type": self.finding_type,
            "severity": self.severity,
            "source_page": self.source_page,
            "source_sequence": self.source_sequence,
            "field": self.field,
        }


@dataclass(frozen=True, slots=True)
class PdfParseResult:
    source: SourceDescriptor | None
    records: tuple[dict[str, object], ...]
    findings: tuple[PdfParseFinding, ...]
    pages_processed: int
    pages_without_text: int
    extraction_method: str
    ocr_used: bool = False
    table_rows_examined: int = 0
    table_rows_skipped: int = 0


def _normalize_page_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Remove PDF control characters while preserving tabs and record line breaks.
    return "".join(character for character in text if character in "\n\t" or ord(character) >= 32)


def _alias_lookup(config: PdfParserConfig) -> dict[str, str]:
    lookup: dict[str, str] = {}
    combined: dict[str, Sequence[str]] = {
        key: values for key, values in DEFAULT_COLUMN_ALIASES.items()
    }
    for field_name, aliases in config.field_aliases.items():
        if field_name not in CANONICAL_FIELDS:
            raise BureauPdfParseError("PDF alias configuration contains an unknown canonical field")
        combined[field_name] = (*combined.get(field_name, ()), *aliases)
    for field_name, aliases in combined.items():
        for alias in (field_name, *aliases):
            normalized = normalize_header(alias)
            previous = lookup.get(normalized)
            if previous is not None and previous != field_name:
                raise BureauPdfParseError("PDF alias configuration is ambiguous")
            lookup[normalized] = field_name
    return lookup


def _compile_config(config: PdfParserConfig) -> tuple[re.Pattern[str], re.Pattern[str]]:
    try:
        record_pattern = re.compile(config.record_line_pattern, re.MULTILINE)
        code_pattern = re.compile(config.attribute_code_pattern)
        re.compile(config.table_separator_pattern)
        for expression in config.field_patterns.values():
            re.compile(expression, re.MULTILINE | re.DOTALL)
    except re.error as exc:
        raise BureauPdfParseError(
            "PDF parser configuration contains an invalid expression"
        ) from exc
    if "code" not in code_pattern.groupindex:
        raise BureauPdfParseError("attribute_code_pattern must define a named 'code' group")
    return record_pattern, code_pattern


def _match_value(match: re.Match[str]) -> str:
    if "value" in match.re.groupindex:
        return normalize_multiline(match.group("value"))
    if match.lastindex:
        return normalize_multiline(match.group(1))
    return normalize_multiline(match.group(0))


def _extract_pattern_fields(block: str, config: PdfParserConfig) -> dict[str, str]:
    values: dict[str, str] = {}
    for field_name, expression in config.field_patterns.items():
        if field_name not in CANONICAL_FIELDS:
            raise BureauPdfParseError("PDF field-pattern configuration has an unknown field")
        match = re.search(expression, block, re.MULTILINE | re.DOTALL)
        if match:
            values[field_name] = _match_value(match)
    return values


def _extract_labelled_fields(
    block_lines: Sequence[str],
    *,
    aliases: Mapping[str, str],
) -> tuple[dict[str, str], list[str]]:
    fields: dict[str, list[str]] = {}
    unassigned: list[str] = []
    current_field: str | None = None
    for original_line in block_lines:
        line = original_line.strip()
        if not line:
            if current_field and fields.get(current_field):
                fields[current_field].append("")
            continue
        candidate_label = ""
        candidate_value = ""
        if ":" in line:
            candidate_label, candidate_value = line.split(":", 1)
        else:
            # Accept a standalone field label followed by continuation lines.
            candidate_label = line
        canonical = aliases.get(normalize_header(candidate_label))
        if canonical:
            current_field = canonical
            fields.setdefault(canonical, [])
            if candidate_value.strip():
                fields[canonical].append(candidate_value.strip())
            continue
        if current_field:
            fields[current_field].append(line)
        else:
            unassigned.append(line)
    normalized = {
        key: normalize_multiline("\n".join(value)) for key, value in fields.items()
    }
    return normalized, unassigned


def _extract_table_cells(
    initial_rest: str,
    *,
    config: PdfParserConfig,
) -> dict[str, str]:
    if not initial_rest.strip():
        return {}
    cells = [
        normalize_multiline(value)
        for value in re.split(config.table_separator_pattern, initial_rest.strip())
    ]
    cells = [cell for cell in cells if cell]
    if len(cells) <= 1:
        return {"description": cells[0]} if cells else {}
    return {
        field_name: cells[index]
        for index, field_name in enumerate(config.table_columns_after_code)
        if index < len(cells)
    }


def _record_starts(
    page_text: str,
    *,
    record_pattern: re.Pattern[str],
) -> list[re.Match[str]]:
    starts: list[re.Match[str]] = []
    for match in record_pattern.finditer(page_text):
        if "code" not in match.re.groupindex or not normalize_multiline(match.group("code")):
            continue
        starts.append(match)
    return starts


def parse_pdf_pages(
    pages: Iterable[str],
    *,
    config: PdfParserConfig | None = None,
    source: SourceDescriptor | None = None,
) -> PdfParseResult:
    """Parse extracted page text without reading a file or invoking OCR."""

    selected = config or PdfParserConfig()
    record_pattern, _ = _compile_config(selected)
    aliases = _alias_lookup(selected)
    records: list[dict[str, object]] = []
    findings: list[PdfParseFinding] = []
    pages_processed = 0
    pages_without_text = 0

    for page_number, raw_page in enumerate(pages, start=1):
        pages_processed += 1
        page_text = _normalize_page_text(raw_page)
        if not page_text.strip():
            pages_without_text += 1
            findings.append(
                PdfParseFinding("page_without_extractable_text", "warning", page_number)
            )
            continue
        starts = _record_starts(page_text, record_pattern=record_pattern)
        for index, start in enumerate(starts):
            block_start = start.start()
            block_end = (
                starts[index + 1].start()
                if index + 1 < len(starts)
                else len(page_text)
            )
            block = page_text[block_start:block_end]
            code = normalize_multiline(start.group("code"))
            sequence = normalize_multiline(
                start.groupdict().get("sequence", "")
            )
            rest = normalize_multiline(start.groupdict().get("rest", ""))
            block_lines = block.splitlines()[1:]
            labelled, unassigned = _extract_labelled_fields(block_lines, aliases=aliases)
            patterned = _extract_pattern_fields(block, selected)
            table_values = _extract_table_cells(rest, config=selected)

            record: dict[str, object] = {field: "" for field in CANONICAL_FIELDS}
            # Increasing authority: table fallback, labels, explicit patterns.
            record.update(table_values)
            record.update(labelled)
            record.update(patterned)
            record["attribute_code"] = code
            record["attribute_sequence"] = sequence
            record["source_sequence"] = sequence
            record["source_page"] = page_number
            record["extraction_method"] = selected.extraction_method
            record["extraction_confidence"] = (
                "high" if patterned else "medium" if labelled else "low"
            )
            if not normalize_multiline(record.get("description", "")) and unassigned:
                record["description"] = normalize_multiline("\n".join(unassigned))
            if selected.preserve_unparsed_text and unassigned:
                record["parser_notes"] = normalize_multiline("\n".join(unassigned))
            else:
                record["parser_notes"] = ""
            if not normalize_multiline(record.get("description", "")):
                findings.append(
                    PdfParseFinding(
                        "missing_description",
                        "warning",
                        page_number,
                        sequence or None,
                        "description",
                    )
                )
            records.append(record)

    if selected.require_at_least_one_record and not records:
        raise BureauPdfParseError("PDF text extraction found no configured attribute records")
    return PdfParseResult(
        source=source,
        records=tuple(records),
        findings=tuple(findings),
        pages_processed=pages_processed,
        pages_without_text=pages_without_text,
        extraction_method=selected.extraction_method,
        ocr_used=False,
    )


def _parse_pdfplumber_tables(
    path: Path,
    *,
    config: PdfParserConfig,
    source: SourceDescriptor,
) -> PdfParseResult | None:
    """Extract configured table cells with stable page/row provenance.

    ``None`` means the optional dependency is unavailable or no configured
    table record was found; the caller may use the explicitly enabled generic
    text fallback.  Structural parser failures raise instead of silently
    changing extraction methods.
    """

    try:
        import pdfplumber
    except ImportError:
        return None

    _, code_pattern = _compile_config(config)
    column_map = dict(config.pdfplumber_column_map)
    for field_name, column_index in column_map.items():
        if field_name not in CANONICAL_FIELDS:
            raise BureauPdfParseError("PDF table column configuration has an unknown field")
        if not isinstance(column_index, int) or column_index < 0:
            raise BureauPdfParseError("PDF table column indexes must be non-negative integers")
    required_width = max(column_map.values(), default=-1) + 1
    records: list[dict[str, object]] = []
    findings: list[PdfParseFinding] = []
    pages_processed = 0
    pages_without_text = 0
    rows_examined = 0
    rows_skipped = 0
    try:
        with pdfplumber.open(str(path)) as document:
            for page_number, page in enumerate(document.pages, start=1):
                pages_processed += 1
                page_text = page.extract_text() or ""
                if not page_text.strip():
                    pages_without_text += 1
                tables = page.extract_tables() or []
                if config.pdfplumber_table_index >= len(tables):
                    findings.append(
                        PdfParseFinding(
                            "configured_table_missing",
                            "warning",
                            page_number,
                        )
                    )
                    continue
                table = tables[config.pdfplumber_table_index] or []
                for source_row, raw_row in enumerate(table, start=1):
                    rows_examined += 1
                    cells = list(raw_row or [])
                    if len(cells) < required_width:
                        rows_skipped += 1
                        findings.append(
                            PdfParseFinding(
                                "short_table_row",
                                "warning",
                                page_number,
                                str(source_row),
                            )
                        )
                        continue
                    values = {
                        field_name: normalize_multiline(cells[column_index])
                        for field_name, column_index in column_map.items()
                    }
                    sequence = normalize_multiline(values.get("attribute_sequence", ""))
                    code = normalize_multiline(values.get("attribute_code", ""))
                    code_match = code_pattern.fullmatch(code)
                    # Repeated header/footer rows are deliberately ignored by
                    # structural shape, never by matching vendor wording.
                    if not sequence.isdigit() or code_match is None:
                        rows_skipped += 1
                        continue
                    record: dict[str, object] = {
                        field_name: "" for field_name in CANONICAL_FIELDS
                    }
                    record.update(values)
                    record["attribute_code"] = normalize_multiline(code_match.group("code"))
                    record["attribute_sequence"] = sequence
                    record["source_sequence"] = sequence
                    record["source_page"] = page_number
                    record["source_row"] = source_row
                    record["extraction_method"] = "pdfplumber_table"
                    record["extraction_confidence"] = "high"
                    record["parser_notes"] = ""
                    records.append(record)
    except BureauPdfParseError:
        raise
    except Exception as exc:
        raise BureauPdfParseError("PDF table source could not be parsed safely") from exc

    if not records:
        return None
    return PdfParseResult(
        source=source,
        records=tuple(records),
        findings=tuple(findings),
        pages_processed=pages_processed,
        pages_without_text=pages_without_text,
        extraction_method="pdfplumber_table",
        ocr_used=False,
        table_rows_examined=rows_examined,
        table_rows_skipped=rows_skipped,
    )


def _extract_pages_with_pypdf2(path: Path) -> list[str]:
    try:
        from PyPDF2 import PdfReader
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise BureauPdfParseError("PyPDF2 is required for PDF text extraction") from exc
    try:
        reader = PdfReader(str(path), strict=True)
        if reader.is_encrypted:
            raise BureauPdfParseError("encrypted PDF sources are not supported")
        return [page.extract_text() or "" for page in reader.pages]
    except BureauPdfParseError:
        raise
    except Exception as exc:
        # PyPDF2 exposes several backend-specific exception types.  Keep source
        # content and parser exception text out of logs by wrapping generically.
        raise BureauPdfParseError("PDF source could not be parsed safely") from exc


def parse_pdf(
    path: str | Path,
    *,
    config: PdfParserConfig | None = None,
) -> PdfParseResult:
    """Parse one explicit external PDF as canonical source, without OCR."""

    descriptor = inspect_external_source(
        path,
        role="canonical PDF source",
        expected_suffixes=(".pdf",),
    )
    selected = config or PdfParserConfig()
    if selected.prefer_pdfplumber_tables:
        table_result = _parse_pdfplumber_tables(
            descriptor.path,
            config=selected,
            source=descriptor,
        )
        if table_result is not None:
            return table_result
        if not selected.allow_text_fallback:
            raise BureauPdfParseError("configured PDF table extraction produced no records")
    pages = _extract_pages_with_pypdf2(descriptor.path)
    return parse_pdf_pages(pages, config=selected, source=descriptor)


__all__ = [
    "BureauPdfParseError",
    "PdfParseFinding",
    "PdfParseResult",
    "PdfParserConfig",
    "parse_pdf",
    "parse_pdf_pages",
]
