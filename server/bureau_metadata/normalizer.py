"""Deterministic normalization helpers for bureau catalog artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
from typing import Any, Iterable, Mapping

from pydantic import BaseModel

from .types import BureauCatalogKey, NumericType


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BureauMetadataNormalizationError(ValueError):
    """Raised when metadata cannot be normalized without guessing."""


@dataclass(frozen=True, slots=True)
class NormalizedObservedValue:
    is_null: bool
    parsed: bool
    canonical_code: str | None
    numeric_value: Decimal | None
    reason: str


def normalize_identifier(value: object, *, field_name: str = "identifier") -> str:
    if not isinstance(value, str):
        raise BureauMetadataNormalizationError(f"{field_name} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise BureauMetadataNormalizationError(f"{field_name} cannot be blank.")
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise BureauMetadataNormalizationError(
            f"{field_name} cannot contain control characters."
        )
    return cleaned


def normalize_attribute_code(value: object) -> str:
    """Preserve the exact code spelling after whitespace/control validation."""

    return normalize_identifier(value, field_name="attribute_code")


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise BureauMetadataNormalizationError("Numeric codes must be finite.")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "+0", "-0"} else rendered


def parse_decimal_lexeme(value: object) -> Decimal:
    if not isinstance(value, str):
        raise BureauMetadataNormalizationError(
            "Catalog numeric values must be supplied as strings."
        )
    cleaned = normalize_identifier(value, field_name="numeric value")
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation as exc:
        raise BureauMetadataNormalizationError(
            "Catalog numeric value is not a valid decimal lexeme."
        ) from exc
    if not parsed.is_finite():
        raise BureauMetadataNormalizationError("Catalog numeric value must be finite.")
    return parsed


def normalize_value_code(value: object, data_type: NumericType = "text") -> str:
    """Normalize one catalog code while requiring a string at the boundary.

    Numeric normalization is attribute-specific. Text/unknown/date codes keep
    their exact trimmed spelling; no global sentinel interpretation occurs.
    """

    cleaned = normalize_identifier(value, field_name="value_code")
    if data_type in {"text", "unknown", "date"}:
        return cleaned
    parsed = parse_decimal_lexeme(cleaned)
    if data_type == "integer":
        integral = parsed.to_integral_value()
        if parsed != integral:
            raise BureauMetadataNormalizationError(
                "Integer attribute codes cannot contain a fractional value."
            )
        return str(int(integral))
    if data_type == "decimal":
        return _canonical_decimal(parsed)
    raise BureauMetadataNormalizationError("Unsupported bureau attribute data type.")


def _is_null(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, Decimal):
        return value.is_nan()
    if isinstance(value, float):
        return math.isnan(value)
    return False


def canonicalize_observed_value(
    value: object,
    data_type: NumericType,
) -> NormalizedObservedValue:
    """Convert an observed value without assigning bureau semantics."""

    if _is_null(value):
        return NormalizedObservedValue(True, False, None, None, "true_null")

    if data_type in {"integer", "decimal"}:
        if isinstance(value, bool):
            return NormalizedObservedValue(
                False, False, None, None, "boolean_is_not_numeric_attribute_data"
            )
        if isinstance(value, str):
            raw = value.strip()
        elif isinstance(value, (int, float, Decimal)):
            raw = str(value)
        else:
            return NormalizedObservedValue(
                False, False, None, None, "unsupported_numeric_runtime_type"
            )
        if not raw:
            return NormalizedObservedValue(
                False, False, None, None, "blank_numeric_value"
            )
        try:
            parsed = Decimal(raw)
        except InvalidOperation:
            return NormalizedObservedValue(
                False, False, None, None, "numeric_parse_failure"
            )
        if not parsed.is_finite():
            return NormalizedObservedValue(
                False, False, None, None, "non_finite_numeric_value"
            )
        if data_type == "integer" and parsed != parsed.to_integral_value():
            return NormalizedObservedValue(
                False, False, None, parsed, "fractional_value_for_integer_attribute"
            )
        canonical = (
            str(int(parsed.to_integral_value()))
            if data_type == "integer"
            else _canonical_decimal(parsed)
        )
        return NormalizedObservedValue(False, True, canonical, parsed, "parsed")

    if data_type == "date":
        if isinstance(value, datetime):
            canonical = value.isoformat()
        elif isinstance(value, date):
            canonical = value.isoformat()
        elif isinstance(value, str):
            raw = value.strip()
            if not raw:
                return NormalizedObservedValue(
                    False, False, None, None, "blank_date_value"
                )
            try:
                canonical = datetime.fromisoformat(raw).isoformat()
            except ValueError:
                try:
                    canonical = date.fromisoformat(raw).isoformat()
                except ValueError:
                    return NormalizedObservedValue(
                        False, False, None, None, "date_parse_failure"
                    )
        else:
            return NormalizedObservedValue(
                False, False, None, None, "unsupported_date_runtime_type"
            )
        return NormalizedObservedValue(False, True, canonical, None, "parsed")

    if data_type in {"text", "unknown"}:
        canonical = str(value).strip()
        if not canonical:
            return NormalizedObservedValue(
                False, False, None, None, "blank_text_value"
            )
        return NormalizedObservedValue(False, True, canonical, None, "parsed")

    return NormalizedObservedValue(
        False, False, None, None, "unsupported_attribute_data_type"
    )


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_ready(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_json_ready(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def canonical_json_bytes(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            _json_ready(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise BureauMetadataNormalizationError(
            "Catalog payload is not canonical JSON data."
        ) from exc
    return rendered.encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def checksum_model_payload(
    value: Any,
    *,
    exclude: Iterable[str] = (),
) -> str:
    excluded = set(exclude)
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude=excluded)
    elif isinstance(value, Mapping):
        payload = {key: item for key, item in value.items() if str(key) not in excluded}
    else:
        payload = value
    return sha256_bytes(canonical_json_bytes(payload))


def validate_sha256(value: object, *, field_name: str = "checksum") -> str:
    cleaned = normalize_identifier(value, field_name=field_name).lower()
    if not _SHA256.fullmatch(cleaned):
        raise BureauMetadataNormalizationError(
            f"{field_name} must be a lowercase 64-character SHA-256 digest."
        )
    return cleaned


def validate_relative_artifact_path(value: object) -> str:
    cleaned = normalize_identifier(value, field_name="relative artifact path")
    if "\\" in cleaned:
        raise BureauMetadataNormalizationError(
            "Catalog artifact paths must use forward slashes."
        )
    candidate = PurePosixPath(cleaned)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise BureauMetadataNormalizationError(
            "Catalog artifact path must be a contained relative path."
        )
    return candidate.as_posix()


def catalog_key_payload(key: BureauCatalogKey | Mapping[str, object]) -> dict[str, str]:
    parsed = key if isinstance(key, BureauCatalogKey) else BureauCatalogKey.model_validate(key)
    return {
        "provider": parsed.provider,
        "product": parsed.product,
        "edition": parsed.edition,
        "dictionary_version": parsed.dictionary_version,
    }


def catalog_key_digest(key: BureauCatalogKey | Mapping[str, object]) -> str:
    return sha256_bytes(canonical_json_bytes(catalog_key_payload(key)))


def catalog_id_for_key(key: BureauCatalogKey | Mapping[str, object]) -> str:
    return "bureau-catalog-key-" + catalog_key_digest(key)[:24]


def catalog_relative_directory(
    key: BureauCatalogKey | Mapping[str, object],
    catalog_checksum: str,
) -> PurePosixPath:
    checksum = validate_sha256(catalog_checksum, field_name="catalog_checksum")
    return PurePosixPath("catalogs", catalog_key_digest(key), checksum)


__all__ = [
    "BureauMetadataNormalizationError",
    "NormalizedObservedValue",
    "canonical_json_bytes",
    "canonicalize_observed_value",
    "catalog_id_for_key",
    "catalog_key_digest",
    "catalog_key_payload",
    "catalog_relative_directory",
    "checksum_model_payload",
    "normalize_attribute_code",
    "normalize_identifier",
    "normalize_value_code",
    "parse_decimal_lexeme",
    "sha256_bytes",
    "validate_relative_artifact_path",
    "validate_sha256",
]
