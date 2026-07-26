"""Safe serialization of ATLAS-provided Python runtime context.

Defect repaired here
--------------------
The generated execution prelude embedded `json.dumps(context)` output directly
into Python source:

    ATLAS_CONTEXT = {"previewRows": [{"Amount": null}], ...}

JSON's `null`/`true`/`false` are not Python literals, so the sandbox raised
`NameError: name 'null' is not defined` before the user's program ever ran. Any
dataset cell with a missing value was enough to trigger it.

Approach
--------
Context is normalized to JSON-safe primitives, serialized once with
`json.dumps()`, and embedded as a **quoted Python string literal** produced by
`repr()`. The sandbox then parses it with `json.loads()`. Because the payload is
only ever a string literal, no value inside it can terminate the literal or
inject Python code -- `repr()` escapes quotes, backslashes, and newlines.

Naive `.replace("null", "None")` is deliberately NOT used: it corrupts any
legitimate string containing the word "null".
"""
from __future__ import annotations

import datetime as _datetime
import json
import math
from pathlib import Path, PurePath
from typing import Any, Dict, List, Tuple

#: Cap on how deep a nested structure may be normalized before it is rejected.
MAX_DEPTH = 24


class RuntimeContextError(Exception):
    """Raised when runtime context cannot be prepared. The sandbox is not started."""


def _numpy_scalar_to_python(value: Any) -> Any | None:
    """Converts a NumPy scalar without importing NumPy when it is not loaded."""
    item = getattr(value, "item", None)
    if callable(item) and type(value).__module__.split(".")[0] == "numpy":
        try:
            return item()
        except Exception:  # noqa: BLE001
            return None
    return None


def normalize_runtime_value(value: Any, *, path: str = "$", depth: int = 0, conversions: List[str] | None = None) -> Any:
    """Recursively converts a value into JSON-safe primitives.

    `conversions` accumulates a note for every lossy conversion so nothing is
    silently stringified.
    """
    if conversions is None:
        conversions = []
    if depth > MAX_DEPTH:
        raise RuntimeContextError(f"Runtime context nesting exceeded {MAX_DEPTH} levels at {path}.")

    # Exact primitives first. bool must precede int (bool is a subclass of int).
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            # Non-finite floats have no JSON representation; JSON's NaN/Infinity
            # are also not Python literals. Converted to None and recorded.
            conversions.append(f"{path}: non-finite float converted to None")
            return None
        return value

    numpy_value = _numpy_scalar_to_python(value)
    if numpy_value is not None or type(value).__module__.split(".")[0] == "numpy":
        return normalize_runtime_value(numpy_value, path=path, depth=depth + 1, conversions=conversions)

    if isinstance(value, (_datetime.datetime, _datetime.date, _datetime.time)):
        return value.isoformat()

    if isinstance(value, (Path, PurePath)):
        # Only the final component is exposed; a server artifact tree must never
        # travel into user-visible runtime context.
        conversions.append(f"{path}: path reduced to its file name")
        return value.name

    if isinstance(value, dict):
        normalized: Dict[str, Any] = {}
        for key, item in value.items():
            # JSON object keys must be strings.
            safe_key = key if isinstance(key, str) else str(key)
            if not isinstance(key, str):
                conversions.append(f"{path}.{safe_key}: non-string key converted to string")
            normalized[safe_key] = normalize_runtime_value(
                item, path=f"{path}.{safe_key}", depth=depth + 1, conversions=conversions
            )
        return normalized

    if isinstance(value, (list, tuple, set, frozenset)):
        if isinstance(value, (set, frozenset)):
            conversions.append(f"{path}: set converted to list")
            value = sorted(value, key=repr)
        return [
            normalize_runtime_value(item, path=f"{path}[{index}]", depth=depth + 1, conversions=conversions)
            for index, item in enumerate(value)
        ]

    if isinstance(value, (bytes, bytearray)):
        conversions.append(f"{path}: bytes decoded as UTF-8 with replacement")
        return bytes(value).decode("utf-8", errors="replace")

    # Anything else is stringified, but the conversion is always recorded.
    conversions.append(f"{path}: {type(value).__name__} converted to string")
    return str(value)


def normalize_runtime_context(context: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Normalizes a whole context mapping. Returns (context, conversion notes)."""
    if context is None:
        return {}, []
    if not isinstance(context, dict):
        raise RuntimeContextError("Runtime context must be a mapping.")
    conversions: List[str] = []
    normalized = normalize_runtime_value(context, path="context", conversions=conversions)
    return normalized, conversions


def embed_json_literal(value: Any) -> str:
    """Renders a value as a Python expression that reconstructs it safely.

    The JSON text is embedded as a `repr()`-quoted string literal and parsed at
    runtime, so quotes, apostrophes, newlines, backslashes, and non-ASCII text
    cannot escape the literal or inject code.
    """
    try:
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeContextError(f"Runtime context could not be serialized: {exc}") from exc
    return f"json.loads({payload!r})"


def build_context_assignment(name: str, value: Any) -> str:
    """One `NAME = json.loads('...')` assignment line."""
    return f"{name} = {embed_json_literal(value)}\n"
