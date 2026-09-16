"""Versioned compatibility reader for immutable V18 forecast creation clocks."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "MLB_V18_FORECAST_CREATED_AT_COMPATIBILITY_V1"


class ForecastCreationClockError(ValueError):
    """The original creation clock could not be authenticated."""


def _aware(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ForecastCreationClockError(f"{field}_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ForecastCreationClockError(f"{field}_INVALID") from exc
    if parsed.tzinfo is None:
        raise ForecastCreationClockError(f"{field}_TIMEZONE_MISSING")
    return parsed


def _physical(path: Path, expected_sha256: str | None = None,
              expected_bytes: int | None = None) -> dict[str, Any]:
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != str(expected_sha256).lower():
        raise ForecastCreationClockError(f"FORECAST_CLOCK_ARTIFACT_SHA256_MISMATCH:{path.name}")
    if expected_bytes is not None and len(payload) != int(expected_bytes):
        raise ForecastCreationClockError(f"FORECAST_CLOCK_ARTIFACT_BYTES_MISMATCH:{path.name}")
    return {"path": str(path), "bytes": len(payload), "sha256": digest, "payload": payload}


def _artifact_paths(binding: Mapping[str, Any], output_root: Path | None) -> tuple[Path, Path] | None:
    forecast_object = binding.get("forecastObject")
    if isinstance(forecast_object, Mapping):
        manifest_ref = forecast_object.get("manifest")
        if isinstance(manifest_ref, Mapping) and manifest_ref.get("path"):
            manifest_path = Path(str(manifest_ref["path"]))
            return manifest_path, manifest_path.parent / "forecast.json"
    relative = binding.get("relativePath")
    if relative and output_root is not None:
        root = Path(output_root).resolve()
        object_dir = (root / str(relative)).resolve()
        if root != object_dir and root not in object_dir.parents:
            raise ForecastCreationClockError("FORECAST_CLOCK_OBJECT_PATH_ESCAPES_ROOT")
        return object_dir / str(binding.get("manifestFile") or "manifest.json"), (
            object_dir / str(binding.get("forecastFile") or "forecast.json")
        )
    return None


def _from_artifact(binding: Mapping[str, Any], output_root: Path | None) -> dict[str, Any] | None:
    paths = _artifact_paths(binding, output_root)
    if paths is None:
        return None
    manifest_path, forecast_path = paths
    forecast_object = binding.get("forecastObject")
    manifest_ref = (forecast_object.get("manifest") if isinstance(forecast_object, Mapping) else None)
    manifest_physical = _physical(
        manifest_path,
        manifest_ref.get("sha256") if isinstance(manifest_ref, Mapping) else None,
        manifest_ref.get("bytes") if isinstance(manifest_ref, Mapping) else None,
    )
    try:
        manifest = json.loads(manifest_physical["payload"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ForecastCreationClockError("FORECAST_CLOCK_MANIFEST_INVALID_JSON_UTF8") from exc
    manifest_body = {key: value for key, value in manifest.items()
                     if key not in {"objectId", "objectSha256"}}
    logical_sha256 = hashlib.sha256(json.dumps(
        manifest_body, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    if logical_sha256 != manifest.get("objectSha256"):
        raise ForecastCreationClockError("FORECAST_CLOCK_MANIFEST_LOGICAL_IDENTITY_MISMATCH")
    artifact_row = next((row for row in manifest.get("artifacts", [])
                         if row.get("relativePath") == forecast_path.name), None)
    if artifact_row is None:
        raise ForecastCreationClockError("FORECAST_CLOCK_FORECAST_ARTIFACT_NOT_BOUND")
    forecast_physical = _physical(forecast_path, artifact_row.get("sha256"), artifact_row.get("bytes"))
    try:
        forecast = json.loads(forecast_physical["payload"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ForecastCreationClockError("FORECAST_CLOCK_FORECAST_INVALID_JSON_UTF8") from exc
    claimed_object = binding.get("objectSha256")
    if isinstance(forecast_object, Mapping):
        claimed_object = forecast_object.get("objectSha256") or claimed_object
    if claimed_object and manifest.get("objectSha256") != claimed_object:
        raise ForecastCreationClockError("FORECAST_CLOCK_OBJECT_IDENTITY_MISMATCH")
    if binding.get("gameId") and forecast.get("gameId") != binding["gameId"]:
        raise ForecastCreationClockError("FORECAST_CLOCK_GAME_IDENTITY_MISMATCH")
    return {"forecast": forecast,
            "manifest": {key: value for key, value in manifest_physical.items() if key != "payload"},
            "forecastArtifact": {key: value for key, value in forecast_physical.items() if key != "payload"}}


def resolve_forecast_created_at_v1(binding: Mapping[str, Any], *,
                                   output_root: Path | None = None) -> dict[str, Any]:
    """Resolve the original clock without current-time fallback or state mutation.

    A bound immutable forecast artifact wins. A retained direct field is allowed
    for already-authenticated documents. If both exist they must agree exactly.
    """
    if not isinstance(binding, Mapping):
        raise ForecastCreationClockError("FORECAST_CLOCK_BINDING_INVALID")
    artifact = _from_artifact(binding, output_root)
    direct = binding.get("forecastCreatedAt")
    nested = binding.get("forecast")
    if direct is None and isinstance(nested, Mapping):
        direct = nested.get("forecastCreatedAt")
    if artifact is not None:
        value = artifact["forecast"].get("forecastCreatedAt")
        _aware(value, "FORECAST_CREATED_AT")
        if direct is not None and direct != value:
            raise ForecastCreationClockError("FORECAST_CREATED_AT_BINDING_ARTIFACT_MISMATCH")
        source = "BOUND_IMMUTABLE_FORECAST_ARTIFACT"
    elif direct is not None:
        value = direct
        _aware(value, "FORECAST_CREATED_AT")
        source = "AUTHENTICATED_RETAINED_FORECAST_FIELD"
    else:
        raise ForecastCreationClockError(
            "FORECAST_CREATED_AT_UNRESOLVED_NO_AUTHORITATIVE_RETAINED_FIELD_OR_BOUND_ARTIFACT"
        )
    forecast = artifact["forecast"] if artifact is not None else (
        nested if isinstance(nested, Mapping) else binding
    )
    captured = forecast.get("capturedAt")
    scheduled = forecast.get("scheduledStart")
    if captured is not None and _aware(captured, "CAPTURED_AT") > _aware(value, "FORECAST_CREATED_AT"):
        raise ForecastCreationClockError("FORECAST_CREATED_AT_PRECEDES_CAPTURE")
    if scheduled is not None and _aware(value, "FORECAST_CREATED_AT") >= _aware(scheduled, "SCHEDULED_START"):
        raise ForecastCreationClockError("FORECAST_CREATED_AT_NOT_PREGAME")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "forecastCreatedAt": value,
        "source": source,
        "currentTimeFallbackUsed": False,
        "historicalStateRewritten": False,
        **({"artifact": {"manifest": artifact["manifest"],
                         "forecast": artifact["forecastArtifact"]}} if artifact is not None else {}),
    }
