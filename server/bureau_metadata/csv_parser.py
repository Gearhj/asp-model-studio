"""Deterministic CSV staging parser for provider-neutral bureau metadata.

The CSV is staging input, never canonical authority.  Every value remains text
unless a later normalizer explicitly validates a typed representation.  Python's
``csv`` module is used with ``newline=''`` so quoted multiline cells and very
large sentinel codes round-trip without spreadsheet-style coercion.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence, TextIO

from .source_reader import SourceDescriptor, inspect_external_source


class BureauCsvParseError(RuntimeError):
    """Raised when the selected CSV cannot be parsed without ambiguity."""


CANONICAL_FIELDS: tuple[str, ...] = (
    "attribute_sequence",
    "attribute_code",
    "description",
    "units",
    "field_length",
    "numeric_type",
    "valid_value_expression",
    "staging_ordinary_min",
    "staging_ordinary_max",
    "special_value_definitions_raw",
    "versions",
    "cross_bureau_availability",
    "leveling_indicator",
    "archive_indicator",
    "equifax_availability",
    "transunion_availability",
    "leveling_status",
    "archive_availability",
)


DEFAULT_COLUMN_ALIASES: Mapping[str, tuple[str, ...]] = {
    "attribute_sequence": (
        "attribute sequence",
        "sequence",
        "sequence number",
        "seq",
        "row",
    ),
    "attribute_code": (
        "attribute code",
        "attribute name",
        "attribute",
        "variable code",
        "variable name",
        "field code",
        "field name",
        "code",
        "name",
    ),
    "description": ("attribute description", "description", "definition"),
    "units": ("units", "unit", "unit of measure"),
    "field_length": ("field length", "length", "size"),
    "numeric_type": ("numeric type", "data type", "datatype", "type"),
    "valid_value_expression": (
        "valid value expression",
        "valid value range",
        "valid values",
        "value range",
        "range",
    ),
    "staging_ordinary_min": (
        "ordinary valid min",
        "ordinary minimum",
        "valid minimum",
        "valid min",
        "range minimum",
        "range min",
        "min value",
        "minimum",
        "min",
    ),
    "staging_ordinary_max": (
        "ordinary valid max",
        "ordinary maximum",
        "valid maximum",
        "valid max",
        "range maximum",
        "range max",
        "max value",
        "maximum",
        "max",
    ),
    "special_value_definitions_raw": (
        "default and exceptional values",
        "default exceptional values",
        "special value definitions",
        "special values",
        "default values",
        "exceptional values",
    ),
    "versions": ("versions", "version", "available versions"),
    "cross_bureau_availability": (
        "cross bureau availability",
        "cross-bureau availability",
        "bureau availability",
    ),
    "leveling_indicator": ("leveling indicator",),
    "archive_indicator": ("archive indicator",),
    "equifax_availability": (
        "equifax availability",
        "equifax",
        "available on equifax",
    ),
    "transunion_availability": (
        "transunion availability",
        "trans union availability",
        "transunion",
        "trans union",
        "available on transunion",
    ),
    "leveling_status": ("leveling status", "leveling", "leveled"),
    "archive_availability": (
        "archive availability",
        "archive available",
        "archive",
    ),
}


_MONTHS = (
    "jan|january|feb|february|mar|march|apr|april|may|jun|june|"
    "jul|july|aug|august|sep|sept|september|oct|october|nov|november|"
    "dec|december"
)
_DATE_DAMAGE_PATTERNS = (
    re.compile(rf"^\s*\d{{1,2}}\s*[-/]\s*(?:{_MONTHS})\s*$", re.IGNORECASE),
    re.compile(rf"^\s*(?:{_MONTHS})\s*[-/]\s*\d{{1,2}}\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d{1,2}/\d{1,2}/(?:19|20)\d{2}\s*$"),
    re.compile(r"^\s*(?:19|20)\d{2}-\d{2}-\d{2}\s*$"),
)


@dataclass(frozen=True, slots=True)
class CsvParserConfig:
    """CSV layout configuration.

    Custom aliases are additive.  A canonical field with multiple matching
    input columns is rejected rather than resolved by column order.
    """

    encoding: str = "utf-8-sig"
    delimiter: str = ","
    quotechar: str = '"'
    required_fields: tuple[str, ...] = ("attribute_code",)
    column_aliases: Mapping[str, Sequence[str]] = field(default_factory=dict)
    keep_unmapped_columns: bool = True


@dataclass(frozen=True, slots=True)
class CsvParseFinding:
    finding_type: str
    severity: str
    source_row: int | None = None
    field: str | None = None

    def to_mapping(self) -> dict[str, str | int | None]:
        return {
            "finding_type": self.finding_type,
            "severity": self.severity,
            "source_row": self.source_row,
            "field": self.field,
        }


@dataclass(frozen=True, slots=True)
class CsvParseResult:
    source: SourceDescriptor | None
    headers: tuple[str, ...]
    records: tuple[dict[str, object], ...]
    findings: tuple[CsvParseFinding, ...]
    rows_processed: int
    date_conversion_detections: int


def normalize_header(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[^a-z0-9]+", "", normalized)


def normalize_multiline(value: object) -> str:
    """Normalize line endings/edge whitespace without collapsing line breaks."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def looks_like_spreadsheet_date(value: object) -> bool:
    """Detect suspicious date rendering without guessing the intended range."""

    text = normalize_multiline(value)
    return bool(text and any(pattern.fullmatch(text) for pattern in _DATE_DAMAGE_PATTERNS))


def _merged_aliases(config: CsvParserConfig) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {
        key: {normalize_header(key), *(normalize_header(item) for item in values)}
        for key, values in DEFAULT_COLUMN_ALIASES.items()
    }
    for key, values in config.column_aliases.items():
        if key not in CANONICAL_FIELDS:
            raise BureauCsvParseError("CSV alias configuration contains an unknown canonical field")
        aliases.setdefault(key, {normalize_header(key)}).update(
            normalize_header(item) for item in values
        )
    return aliases


def _resolve_columns(
    fieldnames: Sequence[str],
    config: CsvParserConfig,
) -> dict[str, str]:
    aliases = _merged_aliases(config)
    normalized_headers: dict[str, list[str]] = {}
    for header in fieldnames:
        normalized_headers.setdefault(normalize_header(header), []).append(header)

    resolved: dict[str, str] = {}
    for canonical, candidates in aliases.items():
        matches: list[str] = []
        for candidate in candidates:
            matches.extend(normalized_headers.get(candidate, ()))
        matches = list(dict.fromkeys(matches))
        if len(matches) > 1:
            raise BureauCsvParseError(
                f"CSV contains ambiguous columns for canonical field '{canonical}'"
            )
        if matches:
            resolved[canonical] = matches[0]

    # Spreadsheet exports often synthesize bound columns with tool-specific
    # punctuation or word order.  Treat one unambiguous header containing both
    # a bound token and a domain token as staging evidence only.  These columns
    # can validate, but never replace, the canonical PDF range.
    for canonical, bound_tokens in (
        ("staging_ordinary_min", ("min", "minimum", "lower", "low", "start")),
        ("staging_ordinary_max", ("max", "maximum", "upper", "high", "end")),
    ):
        if canonical in resolved:
            continue
        structural_matches = [
            header
            for header in fieldnames
            if any(token in normalize_header(header) for token in bound_tokens)
            and any(
                token in normalize_header(header)
                for token in ("valid", "range", "ordinary", "numeric", "bound")
            )
        ]
        structural_matches = list(dict.fromkeys(structural_matches))
        if len(structural_matches) > 1:
            raise BureauCsvParseError(
                f"CSV contains ambiguous columns for canonical field '{canonical}'"
            )
        if structural_matches:
            resolved[canonical] = structural_matches[0]

    # If the exporter uses opaque tool-specific prefixes, accept a lone
    # min/max pair only when both are still unmapped and neither column has
    # another canonical role.  Any multiplicity remains a hard ambiguity.
    if (
        "staging_ordinary_min" not in resolved
        and "staging_ordinary_max" not in resolved
    ):
        already_mapped = set(resolved.values())
        remaining = [header for header in fieldnames if header not in already_mapped]
        minimum_matches = [
            header for header in remaining if "min" in normalize_header(header)
        ]
        maximum_matches = [
            header for header in remaining if "max" in normalize_header(header)
        ]
        if len(minimum_matches) == 1 and len(maximum_matches) == 1:
            resolved["staging_ordinary_min"] = minimum_matches[0]
            resolved["staging_ordinary_max"] = maximum_matches[0]
    missing = [field for field in config.required_fields if field not in resolved]
    if missing:
        raise BureauCsvParseError("CSV is missing one or more required canonical columns")
    return resolved


def parse_csv_stream(
    stream: TextIO,
    *,
    config: CsvParserConfig | None = None,
    source: SourceDescriptor | None = None,
) -> CsvParseResult:
    """Parse an already-open CSV stream without performing any path lookup."""

    selected = config or CsvParserConfig()
    reader = csv.DictReader(
        stream,
        delimiter=selected.delimiter,
        quotechar=selected.quotechar,
        strict=True,
    )
    if not reader.fieldnames:
        raise BureauCsvParseError("CSV does not contain a header row")
    headers = tuple(normalize_multiline(value) for value in reader.fieldnames)
    if any(not header for header in headers):
        raise BureauCsvParseError("CSV contains an empty header")
    resolved = _resolve_columns(headers, selected)
    mapped_headers = set(resolved.values())

    records: list[dict[str, object]] = []
    findings: list[CsvParseFinding] = []
    date_detections = 0
    try:
        for source_row, raw in enumerate(reader, start=2):
            if None in raw:
                raise BureauCsvParseError("CSV row contains more fields than the header")
            normalized_raw = {
                normalize_multiline(key): normalize_multiline(value)
                for key, value in raw.items()
            }
            if not any(normalized_raw.values()):
                continue
            record: dict[str, object] = {
                field: normalize_multiline(normalized_raw.get(header, ""))
                for field, header in resolved.items()
            }
            for canonical_field in CANONICAL_FIELDS:
                record.setdefault(canonical_field, "")
            record["source_row"] = source_row
            record["source_sequence"] = normalize_multiline(
                record.get("attribute_sequence", "")
            )
            if selected.keep_unmapped_columns:
                record["staging_extras"] = {
                    header: normalized_raw.get(header, "")
                    for header in headers
                    if header not in mapped_headers
                }
            code = normalize_multiline(record.get("attribute_code", ""))
            if not code:
                findings.append(
                    CsvParseFinding(
                        finding_type="missing_attribute_code",
                        severity="error",
                        source_row=source_row,
                        field="attribute_code",
                    )
                )
            if looks_like_spreadsheet_date(record.get("valid_value_expression", "")):
                date_detections += 1
                findings.append(
                    CsvParseFinding(
                        finding_type="possible_spreadsheet_date_conversion",
                        severity="warning",
                        source_row=source_row,
                        field="valid_value_expression",
                    )
                )
            records.append(record)
    except csv.Error as exc:
        raise BureauCsvParseError("CSV structure is malformed") from exc

    return CsvParseResult(
        source=source,
        headers=headers,
        records=tuple(records),
        findings=tuple(findings),
        rows_processed=len(records),
        date_conversion_detections=date_detections,
    )


def parse_csv_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    config: CsvParserConfig | None = None,
) -> CsvParseResult:
    """Parse synthetic/in-memory rows using the same canonical mapping rules."""

    materialized = [dict(row) for row in rows]
    if not materialized:
        return CsvParseResult(None, (), (), (), 0, 0)
    headers = tuple(str(value) for value in materialized[0].keys())
    selected = config or CsvParserConfig()
    resolved = _resolve_columns(headers, selected)
    mapped_headers = set(resolved.values())
    records: list[dict[str, object]] = []
    findings: list[CsvParseFinding] = []
    detections = 0
    for offset, raw in enumerate(materialized, start=2):
        record: dict[str, object] = {
            field: normalize_multiline(raw.get(header, ""))
            for field, header in resolved.items()
        }
        for canonical_field in CANONICAL_FIELDS:
            record.setdefault(canonical_field, "")
        record["source_row"] = offset
        record["source_sequence"] = normalize_multiline(
            record.get("attribute_sequence", "")
        )
        if selected.keep_unmapped_columns:
            record["staging_extras"] = {
                header: normalize_multiline(raw.get(header, ""))
                for header in headers
                if header not in mapped_headers
            }
        if not normalize_multiline(record.get("attribute_code", "")):
            findings.append(
                CsvParseFinding("missing_attribute_code", "error", offset, "attribute_code")
            )
        if looks_like_spreadsheet_date(record.get("valid_value_expression", "")):
            detections += 1
            findings.append(
                CsvParseFinding(
                    "possible_spreadsheet_date_conversion",
                    "warning",
                    offset,
                    "valid_value_expression",
                )
            )
        records.append(record)
    return CsvParseResult(
        source=None,
        headers=headers,
        records=tuple(records),
        findings=tuple(findings),
        rows_processed=len(records),
        date_conversion_detections=detections,
    )


def parse_csv(
    path: str | Path,
    *,
    config: CsvParserConfig | None = None,
) -> CsvParseResult:
    """Parse one explicit external CSV source."""

    descriptor = inspect_external_source(
        path,
        role="CSV staging source",
        expected_suffixes=(".csv",),
    )
    selected = config or CsvParserConfig()
    try:
        with descriptor.path.open("r", encoding=selected.encoding, newline="") as stream:
            return parse_csv_stream(stream, config=selected, source=descriptor)
    except (OSError, UnicodeError) as exc:
        raise BureauCsvParseError("CSV staging source could not be decoded") from exc


__all__ = [
    "BureauCsvParseError",
    "CANONICAL_FIELDS",
    "CsvParseFinding",
    "CsvParseResult",
    "CsvParserConfig",
    "DEFAULT_COLUMN_ALIASES",
    "looks_like_spreadsheet_date",
    "normalize_header",
    "normalize_multiline",
    "parse_csv",
    "parse_csv_rows",
    "parse_csv_stream",
]
