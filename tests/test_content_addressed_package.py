import hashlib
import json
from pathlib import Path

import pytest

from server.sports_shared.content_addressed_package import (
    IDENTITY_ALGORITHM, canonical_identity_bytes, package_content_sha256,
    verify_package_directory,
)


CED67 = "ced67bf4b4a0a4447a67b34f56934729452848f8efc4c1730f7c555fd7b7f972"


def test_published_timing_audit_address_is_independently_reproduced():
    root = Path("outputs/mlb-v18-delivery-timing-audit-v1/sha256") / CED67
    result = verify_package_directory(root)
    assert result["identityAlgorithm"] == IDENTITY_ALGORITHM
    assert result["packageContentSha256"] == CED67
    assert [row["path"] for row in result["members"]] == ["CLAUDE_HANDOFF.md", "timing-audit.json"]


def test_identity_is_utf8_sorted_compact_and_byte_sensitive(tmp_path):
    hashes = {"z.json": hashlib.sha256("—\n".encode("utf-8")).hexdigest(),
              "a.json": hashlib.sha256(b"{}\r\n").hexdigest()}
    expected = json.dumps(hashes, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
    assert canonical_identity_bytes(hashes) == expected
    assert package_content_sha256(hashes) == hashlib.sha256(expected).hexdigest()

    member = tmp_path / "a.json"
    member.write_bytes(b"{}\r\n")
    digest = package_content_sha256({"a.json": hashlib.sha256(member.read_bytes()).hexdigest()})
    package = tmp_path / digest
    package.mkdir()
    (package / "a.json").write_bytes(member.read_bytes())
    manifest = {"schemaVersion": "TEST", "packageContentSha256": digest,
                "files": [{"path": "a.json", "bytes": 4,
                           "sha256": hashlib.sha256(b"{}\r\n").hexdigest()}]}
    (package / "package-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    verify_package_directory(package)
    (package / "a.json").write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="PACKAGE_MEMBER_SHA256_MISMATCH"):
        verify_package_directory(package)


def test_windows_separator_is_rejected():
    with pytest.raises(ValueError, match="PACKAGE_MEMBER_PATH_NOT_NORMALIZED"):
        canonical_identity_bytes({"nested\\member.json": "0" * 64})
