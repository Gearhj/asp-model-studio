"""Phase 7D.5A.2 (Repair 3) — COMPLETE, output-bound Silver authority + exhaustive tamper matrix.

Every child is inventoried and rehashed; verify fails closed on any missing/extra child, any single altered byte,
any altered value/identity, any child-sha divergence; and an incomplete existing object is fully re-verified (never
silently reused/re-registered) before republication.
"""
from __future__ import annotations

import json

import pytest

from server.sports_modeling import silver_publish as SP
from tests import _silver_fixture as F


def _pub(tmp_path):
    return F.publish_silver_hermetic(tmp_path)


def test_exact_child_set_and_full_verify(tmp_path):
    p = _pub(tmp_path)
    present = {c.name for c in p["object_dir"].iterdir()}
    assert present == set(SP.REQUIRED_SILVER_CHILDREN)
    v = SP.verify_silver(p["silver_root"], p["manifest_sha"])
    assert v["manifest"]["status"] == "SILVER_NORMALIZED" and v["manifest"]["quarantine"] == "QUARANTINED"
    assert v["manifest"]["modelEligible"] is False and v["manifest"]["selectable"] is False


@pytest.mark.parametrize("child", ["feature-family-contract.json", "prior-pa-semantic-contract.json",
                                   "log1p-prior-pa-semantic-contract.json", "object.parquet",
                                   "transform-code-receipt.json", "value-digest.json", "temporal-contract.json"])
def test_deleting_any_required_child_fails_closed(tmp_path, child):
    p = _pub(tmp_path)
    (p["object_dir"] / child).unlink()
    with pytest.raises(SP.SilverPublishError):
        SP.verify_silver(p["silver_root"], p["manifest_sha"])


def test_adding_an_extra_child_fails_closed(tmp_path):
    p = _pub(tmp_path)
    (p["object_dir"] / "sneaky-extra.json").write_bytes(b"{}")
    with pytest.raises(SP.SilverPublishError):
        SP.verify_silver(p["silver_root"], p["manifest_sha"])


@pytest.mark.parametrize("child", ["object.parquet", "feature-family-contract.json", "feature-set-v2-contract.json",
                                   "transform-code-receipt.json", "transformation-receipt.json",
                                   "prior-pa-semantic-contract.json", "source-object-receipt.json"])
def test_altering_one_byte_of_any_child_fails_closed(tmp_path, child):
    p = _pub(tmp_path)
    b = (p["object_dir"] / child).read_bytes()
    (p["object_dir"] / child).write_bytes(b + b"\x00")
    with pytest.raises(SP.SilverPublishError):
        SP.verify_silver(p["silver_root"], p["manifest_sha"])


def test_altering_one_feature_value_fails_closed(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    p = _pub(tmp_path)
    t = pq.read_table(p["object_dir"] / "object.parquet")
    d = t.to_pydict()
    d["log1p_prior_pa_count"][0] = 999.0     # one value changed
    buf = pa.BufferOutputStream()
    pq.write_table(pa.table(d), buf, compression="none", use_dictionary=False, write_statistics=False)
    (p["object_dir"] / "object.parquet").write_bytes(buf.getvalue().to_pybytes())
    with pytest.raises(SP.SilverPublishError):
        SP.verify_silver(p["silver_root"], p["manifest_sha"])


def _mutate_json(path, mutate):
    b = json.loads(path.read_bytes())
    mutate(b)
    path.write_bytes(json.dumps(b).encode())


def test_altering_receipt_output_logical_sha_fails_closed(tmp_path):
    p = _pub(tmp_path)
    _mutate_json(p["object_dir"] / "transformation-receipt.json", lambda b: b.__setitem__("outputLogicalSha256", "0" * 64))
    with pytest.raises(SP.SilverPublishError):
        SP.verify_silver(p["silver_root"], p["manifest_sha"])


def test_altering_embedded_receipt_sha_fails_closed(tmp_path):
    p = _pub(tmp_path)
    _mutate_json(p["object_dir"] / "transformation-receipt.json", lambda b: b.__setitem__("receiptSha256", "0" * 64))
    with pytest.raises(SP.SilverPublishError):
        SP.verify_silver(p["silver_root"], p["manifest_sha"])


def test_altering_transform_params_in_code_receipt_fails_closed(tmp_path):
    p = _pub(tmp_path)
    _mutate_json(p["object_dir"] / "transform-code-receipt.json", lambda b: b["params"].__setitem__("injected", True))
    with pytest.raises(SP.SilverPublishError):
        SP.verify_silver(p["silver_root"], p["manifest_sha"])


def test_manifest_forced_model_eligible_fails_closed(tmp_path):
    p = _pub(tmp_path)
    _mutate_json(p["object_dir"] / "publication-manifest.json", lambda b: b.__setitem__("modelEligible", True))
    with pytest.raises(SP.SilverPublishError):
        SP.verify_silver(p["silver_root"], p["manifest_sha"])


def test_republish_over_incomplete_existing_object_fails_closed(tmp_path):
    p = _pub(tmp_path)
    (p["object_dir"] / "feature-family-contract.json").unlink()     # incomplete existing object at the address
    with pytest.raises(SP.SilverPublishError):
        F.publish_silver_hermetic(tmp_path)                         # republish must FULL-verify before reuse -> reject
    assert not (p["object_dir"] / "feature-family-contract.json").is_file()   # not silently repaired
