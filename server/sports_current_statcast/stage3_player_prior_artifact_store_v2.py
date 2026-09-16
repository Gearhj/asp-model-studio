"""Immutable local artifact store for governed MLB Wave 2 prior fits."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..sports_datasets.consumer import canonical_json_bytes


DEFAULT_AUTHORITY_ROOT = Path(
    os.getenv(
        "ASP_MLB_PLAYER_PRIOR_V2_ROOT",
        r".runtime\asp-model-studio\stage3-player-prior-authorities-v2",
    )
)


class PriorArtifactStoreV2Error(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_write_exact(path: Path, content: bytes) -> bool:
    """Create/replace atomically and flush bytes before publication."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == content:
        return False
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def publish_artifact(
    payload: Mapping[str, Any],
    *,
    root: Path = DEFAULT_AUTHORITY_ROOT,
) -> dict[str, Any]:
    """Publish one timing-free canonical JSON object under its SHA-256."""

    content = canonical_json_bytes(dict(payload))
    checksum = _sha256_bytes(content)
    target = Path(root) / "objects" / "sha256" / checksum / "manifest.json"
    if target.exists() and target.read_bytes() != content:
        raise PriorArtifactStoreV2Error(
            "PRIOR_V2_CONTENT_ADDRESS_CONFLICT",
            f"Existing object bytes do not match content address {checksum}.",
        )
    created = _atomic_write_exact(target, content)
    return {
        "sha256": checksum,
        "path": str(target.resolve()),
        "byteCount": len(content),
        "created": created,
    }


def load_artifact(
    checksum: str,
    *,
    root: Path = DEFAULT_AUTHORITY_ROOT,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", str(checksum or "")):
        raise PriorArtifactStoreV2Error(
            "PRIOR_V2_ARTIFACT_SHA_INVALID", "Artifact SHA-256 is malformed."
        )
    path = Path(root) / "objects" / "sha256" / checksum / "manifest.json"
    if not path.is_file():
        raise PriorArtifactStoreV2Error(
            "PRIOR_V2_ARTIFACT_MISSING", f"Artifact {checksum} is missing."
        )
    content = path.read_bytes()
    if _sha256_bytes(content) != checksum:
        raise PriorArtifactStoreV2Error(
            "PRIOR_V2_ARTIFACT_CHECKSUM_MISMATCH",
            f"Artifact {checksum} failed content verification.",
        )
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PriorArtifactStoreV2Error(
            "PRIOR_V2_ARTIFACT_JSON_INVALID", f"Artifact {checksum} is not canonical JSON."
        ) from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != content:
        raise PriorArtifactStoreV2Error(
            "PRIOR_V2_ARTIFACT_NOT_CANONICAL",
            f"Artifact {checksum} is not canonical JSON.",
        )
    return value


def publish_current_bundle(
    project_id: str,
    bundle_payload: Mapping[str, Any],
    *,
    root: Path = DEFAULT_AUTHORITY_ROOT,
) -> dict[str, Any]:
    project = str(project_id or "").strip()
    if not project or any(token in project for token in ("/", "\\", "..")):
        raise PriorArtifactStoreV2Error(
            "PRIOR_V2_PROJECT_ID_INVALID", "A safe project identity is required."
        )
    receipt = publish_artifact(bundle_payload, root=root)
    pointer = Path(root) / "projects" / project / "current.json"
    pointer_payload = {
        "schemaVersion": "MLB_PLAYER_STATE_PRIOR_V2_CURRENT_POINTER_V1",
        "projectId": project,
        "authoritySha256": receipt["sha256"],
        "manifestRelativePath": (
            Path("objects") / "sha256" / receipt["sha256"] / "manifest.json"
        ).as_posix(),
    }
    pointer_created = _atomic_write_exact(pointer, canonical_json_bytes(pointer_payload))
    return {**receipt, "pointerPath": str(pointer.resolve()), "pointerChanged": pointer_created}


def load_current_bundle(
    project_id: str,
    *,
    root: Path = DEFAULT_AUTHORITY_ROOT,
) -> dict[str, Any] | None:
    project = str(project_id or "").strip()
    pointer = Path(root) / "projects" / project / "current.json"
    if not pointer.is_file():
        return None
    try:
        raw = pointer.read_bytes()
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PriorArtifactStoreV2Error(
            "PRIOR_V2_CURRENT_POINTER_INVALID", "Current Wave 2 pointer is unreadable."
        ) from exc
    if (
        not isinstance(data, dict)
        or canonical_json_bytes(data) != raw
        or data.get("schemaVersion") != "MLB_PLAYER_STATE_PRIOR_V2_CURRENT_POINTER_V1"
        or data.get("projectId") != project
    ):
        raise PriorArtifactStoreV2Error(
            "PRIOR_V2_CURRENT_POINTER_INVALID", "Current Wave 2 pointer contract differs."
        )
    checksum = str(data.get("authoritySha256") or "")
    expected_relative = (
        Path("objects") / "sha256" / checksum / "manifest.json"
    ).as_posix()
    if data.get("manifestRelativePath") != expected_relative:
        raise PriorArtifactStoreV2Error(
            "PRIOR_V2_CURRENT_POINTER_INVALID", "Current Wave 2 pointer path differs."
        )
    return load_artifact(checksum, root=root)


__all__ = [
    "DEFAULT_AUTHORITY_ROOT",
    "PriorArtifactStoreV2Error",
    "load_artifact",
    "load_current_bundle",
    "publish_artifact",
    "publish_current_bundle",
]
