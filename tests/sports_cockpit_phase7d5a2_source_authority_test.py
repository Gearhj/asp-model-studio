"""Phase 7D.5A.2 (Repair 2) — SERVER-RESOLVED source authority + transform-code identity, adversarially.

The publisher must resolve+rehash the governed source server-side (never trust caller SHAs/rows), issue a
non-forgeable handle, and bind the ACTUAL transform implementation digest.
"""
from __future__ import annotations

import json
import inspect

import pytest

from server.sports_modeling import silver_publish as SP
from server.sports_modeling import silver_transform as ST
from tests import _silver_fixture as F


# ---------------------------------------------------------------- server resolution + non-forgeable handle
def test_resolve_verifies_and_issues_handle(tmp_path):
    F.publish_source(tmp_path / "src")
    handle, rows = SP.resolve_verified_source(tmp_path / "src", F.SRC_ID)
    assert handle.dataset_version_id == F.SRC_ID and handle.row_count == len(rows)
    assert SP._HEX64.match(handle.physical_sha256) and SP._HEX64.match(handle.logical_sha256)


def test_handle_cannot_be_forged_from_caller_values():
    with pytest.raises(SP.SourceAuthorityError):
        SP.VerifiedSourceHandle(dataset_version_id="x", object_path="y", physical_sha256="a" * 64,
                                logical_sha256="a" * 64, schema_sha256="a" * 64, receipt_sha256="a" * 64,
                                manifest_sha256="a" * 64, seasons=(2023,), row_count=1)


def test_publish_silver_takes_no_caller_source_rows_or_shas():
    params = set(inspect.signature(SP.publish_silver).parameters)
    for forbidden in ("source_rows", "source_receipt_sha", "source_physical_sha", "source_logical_sha",
                      "source_schema_sha", "source_manifest_sha", "supplied_advanced"):
        assert forbidden not in params, f"publish_silver must not accept caller-attested {forbidden}"
    assert "source_dataset_version_id" in params and "source_root" in params


def test_nonexistent_source_identity_rejected(tmp_path):
    F.publish_source(tmp_path / "src")
    with pytest.raises(SP.SourceAuthorityError):
        SP.resolve_verified_source(tmp_path / "src", "no-such-source")


def test_non_hex_registered_source_sha_rejected(tmp_path):
    F.publish_source(tmp_path / "src")
    reg = tmp_path / "src" / "silver-source-registry.json"
    r = json.loads(reg.read_text())
    r["datasets"][F.SRC_ID]["logicalSha256"] = "NOTHEX"
    reg.write_text(json.dumps(r))
    with pytest.raises(SP.SourceAuthorityError):
        SP.resolve_verified_source(tmp_path / "src", F.SRC_ID)


def _src_child(tmp_path):
    F.publish_source(tmp_path / "src")
    reg = json.loads((tmp_path / "src" / "silver-source-registry.json").read_text())
    logical = reg["datasets"][F.SRC_ID]["logicalSha256"]
    return tmp_path / "src" / "objects" / "sha256" / logical


@pytest.mark.parametrize("child", ["source-receipt.json", "source-publication-manifest.json"])
def test_source_receipt_or_manifest_tamper_rejected(tmp_path, child):
    d = _src_child(tmp_path)
    b = json.loads((d / child).read_bytes())
    b["rowCount"] = 99999
    (d / child).write_bytes(json.dumps(b).encode())
    with pytest.raises(SP.SourceAuthorityError):
        SP.resolve_verified_source(tmp_path / "src", F.SRC_ID)


def test_source_object_bytes_tamper_rejected(tmp_path):
    d = _src_child(tmp_path)
    (d / "source.parquet").write_bytes((d / "source.parquet").read_bytes() + b"\x00tamper")
    with pytest.raises(SP.SourceAuthorityError):
        SP.resolve_verified_source(tmp_path / "src", F.SRC_ID)


# ---------------------------------------------------------------- transform-code identity
def test_transform_code_receipt_binds_implementation_and_files():
    tcr = SP.transform_code_receipt(params={"a": 1})
    assert tcr["transformId"] == ST.TRANSFORM_ID
    assert SP._HEX64.match(tcr["implementationDigest"])
    for f in ("silver_transform.py", "silver_publish.py", "feature_semantics.py", "gen3_contracts.py", "consumer.py"):
        assert SP._HEX64.match(tcr["fileShas"][f])


def test_changing_transform_implementation_changes_the_digest(monkeypatch):
    before = SP.transform_code_receipt(params={})["implementationDigest"]

    def _different(rows, **kw):     # a DIFFERENT implementation with the SAME contract name
        return [{"prior_pa_count": 0.0, "log1p_prior_pa_count": 0.0} for _ in rows]

    monkeypatch.setattr(ST, "compute_prior_pa", _different)
    after = SP.transform_code_receipt(params={})["implementationDigest"]
    assert after != before, "implementation change must alter the transform authority digest (contract name unchanged)"
    assert ST.TRANSFORM_ID == "MLB_SILVER_PRIOR_PA_TRANSFORM_V1"     # same contract name, different digest


def test_transform_params_change_the_receipt_digest():
    a = SP.transform_code_receipt(params={"x": 1})
    b = SP.transform_code_receipt(params={"x": 2})
    assert a["sha256"] != b["sha256"]
