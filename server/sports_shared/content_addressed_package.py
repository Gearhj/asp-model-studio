"""Portable identity and verification for member-hash addressed packages."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping


IDENTITY_ALGORITHM = "ASP_FILENAME_TO_SHA256_MAP_CANONICAL_JSON_UTF8_V1"


def canonical_identity_bytes(member_hashes: Mapping[str, str]) -> bytes:
    """Encode normalized filenames to physical hashes; byte counts are excluded."""
    normalized: dict[str, str] = {}
    for supplied, digest in member_hashes.items():
        path = PurePosixPath(supplied)
        name = path.as_posix()
        if (not name or name in {".", ".."} or "\\" in supplied or path.is_absolute()
                or any(part in {"", ".", ".."} for part in path.parts) or name != supplied):
            raise ValueError(f"PACKAGE_MEMBER_PATH_NOT_NORMALIZED: {supplied!r}")
        value = str(digest).lower()
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError(f"PACKAGE_MEMBER_SHA256_INVALID: {supplied!r}")
        if name in normalized:
            raise ValueError(f"PACKAGE_MEMBER_PATH_DUPLICATED: {name}")
        normalized[name] = value
    if not normalized:
        raise ValueError("PACKAGE_IDENTITY_REQUIRES_AT_LEAST_ONE_MEMBER")
    return json.dumps(normalized, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def package_content_sha256(member_hashes: Mapping[str, str]) -> str:
    return hashlib.sha256(canonical_identity_bytes(member_hashes)).hexdigest()


def member_records(root: Path, member_paths: Iterable[str]) -> list[dict]:
    records = []
    for name in member_paths:
        canonical_identity_bytes({name: "0" * 64})
        payload = (root / PurePosixPath(name)).read_bytes()
        records.append({"path": name, "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest()})
    return sorted(records, key=lambda row: row["path"])


def verify_package_directory(package_dir: Path, *, manifest_name: str = "package-manifest.json") -> dict:
    """Independently verify raw member bytes and reproduce the directory address."""
    package_dir = Path(package_dir).resolve()
    manifest_bytes = (package_dir / manifest_name).read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("PACKAGE_MANIFEST_FILES_REQUIRED")
    expected: dict[str, str] = {}
    verified = []
    for row in files:
        name = row.get("path")
        canonical_identity_bytes({name: row.get("sha256")})
        path = (package_dir / PurePosixPath(name)).resolve()
        if package_dir not in path.parents:
            raise ValueError("PACKAGE_MEMBER_ESCAPES_DIRECTORY")
        payload = path.read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != row["sha256"]:
            raise ValueError(f"PACKAGE_MEMBER_SHA256_MISMATCH: {name}")
        if len(payload) != int(row["bytes"]):
            raise ValueError(f"PACKAGE_MEMBER_BYTES_MISMATCH: {name}")
        expected[name] = actual
        verified.append({"path": name, "bytes": len(payload), "sha256": actual})
    reproduced = package_content_sha256(expected)
    claimed = manifest.get("packageContentSha256")
    if reproduced != claimed:
        raise ValueError("PACKAGE_CONTENT_IDENTITY_MISMATCH")
    if package_dir.name.lower() != reproduced:
        raise ValueError("PACKAGE_DIRECTORY_ADDRESS_MISMATCH")
    return {"schemaVersion": "ASP_CONTENT_ADDRESSED_PACKAGE_VERIFICATION_V1",
            "identityAlgorithm": IDENTITY_ALGORITHM, "packageContentSha256": reproduced,
            "members": sorted(verified, key=lambda row: row["path"]),
            "manifestPhysicalSha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "manifestBytes": len(manifest_bytes)}
