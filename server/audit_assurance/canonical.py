"""Deterministic, side-effect-free serialization for audit-assurance contracts.

This module deliberately has no persistence, runtime-authority, or browser
dependencies.  Hashes produced here are content fingerprints only; they never
resolve an active project, a "latest" artifact, or any other mutable alias.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel


class CanonicalSerializationError(ValueError):
    """Raised when a value cannot be represented canonically and safely."""


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalSerializationError(
            "Audit timestamps must be timezone-aware server timestamps."
        )
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="python", exclude_none=True))
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, datetime):
        return _utc_timestamp(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalSerializationError("Non-finite decimals are not canonical.")
        return format(value.normalize(), "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalSerializationError("Non-finite floats are not canonical.")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalSerializationError(
                    "Canonical audit objects require string mapping keys."
                )
            normalized[key] = _normalize(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        rendered = [_normalize(item) for item in value]
        return sorted(
            rendered,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ),
        )
    if isinstance(value, (bytes, bytearray, memoryview, Path)):
        raise CanonicalSerializationError(
            "Binary content and filesystem paths cannot be embedded in audit contracts."
        )
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise CanonicalSerializationError(
        f"Unsupported canonical audit value type: {type(value).__name__}."
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return stable UTF-8 JSON bytes for a bounded contract value."""

    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Return the wire-contract SHA-256 fingerprint of canonical JSON bytes."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = [
    "CanonicalSerializationError",
    "canonical_json_bytes",
    "canonical_sha256",
]
