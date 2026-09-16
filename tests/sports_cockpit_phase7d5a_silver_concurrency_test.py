"""Phase 7D.5A.2 (Repair 5) — transactional Silver registry across SEPARATE OS processes.

Proves the interprocess-locked read-after-lock / validate / merge / atomic-replace / verify-after-write registry is
correct under real contention: identical content converges idempotently; two DIFFERENT valid objects BOTH survive in
the one registry (the exact Codex two-worker/different-seed case); a conflicting same-key content fails closed; and a
failed publication registers nothing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from server.sports_modeling import silver_publish as SP

REPO = Path(__file__).resolve().parents[1]


def _worker(base: Path, seed: int):
    return subprocess.Popen([sys.executable, "-m", "tests._silver_worker", str(base), str(seed)],
                            cwd=str(REPO), env={"PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1", **os.environ},
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _registry(base: Path) -> dict:
    p = base / "silver" / "silver-registry.json"
    return json.loads(p.read_text()) if p.is_file() else {"datasets": {}}


def test_identical_content_converges_idempotently_across_processes(tmp_path):
    a = _worker(tmp_path, 1); b = _worker(tmp_path, 1)          # SAME seed -> byte-identical content
    oa = a.communicate(timeout=180)[0].strip(); ob = b.communicate(timeout=180)[0].strip()
    assert oa.startswith("OK ") and ob.startswith("OK "), (oa, ob)
    assert oa.split()[1] == ob.split()[1]                       # same content address
    assert list((tmp_path / "silver" / "objects" / "sha256").glob(".staging-*")) == []


def test_two_different_objects_both_survive_in_the_registry(tmp_path):
    # the exact Codex race: two DIFFERENT valid publications must not clobber each other's registry entry
    a = _worker(tmp_path, 11); b = _worker(tmp_path, 22)
    oa = a.communicate(timeout=180)[0].strip(); ob = b.communicate(timeout=180)[0].strip()
    assert oa.startswith("OK ") and ob.startswith("OK "), (oa, ob)
    sha_a, sha_b = oa.split()[1], ob.split()[1]
    assert sha_a != sha_b
    ds = _registry(tmp_path)["datasets"]
    # the mutable index is a minimal locator (datasetVersionId -> registrationSha256); the manifest identity lives in
    # the datasetVersionId KEY (silver:{sourceObjectId}:sha256:{manifestSha256}), never as an index field
    have = {k.rsplit(":sha256:", 1)[-1] for k in ds}
    assert sha_a in have and sha_b in have, ("both entries must survive", have)
    # both immutable objects are independently verifiable after contention
    SP.verify_silver(tmp_path / "silver", sha_a)
    SP.verify_silver(tmp_path / "silver", sha_b)


def test_conflicting_same_key_content_fails_closed(tmp_path):
    from tests._silver_fixture import publish_silver_hermetic
    p = publish_silver_hermetic(tmp_path)
    reg_path = tmp_path / "silver" / "silver-registry.json"
    reg = json.loads(reg_path.read_text())
    dsid = next(iter(reg["datasets"]))
    # corrupt the committed entry so a re-put of the SAME key sees divergent content -> must fail closed
    reg["datasets"][dsid] = {**reg["datasets"][dsid], "rows": 999999}
    reg_path.write_text(json.dumps(reg))
    import pytest
    with pytest.raises(SP.SilverPublishError):
        SP._locked_registry_put(SP._silver_registry_path(tmp_path / "silver"), SP._silver_lock_path(tmp_path / "silver"),
                                tmp_path / "silver", "MLB_SILVER_REGISTRY_V1", dsid,
                                {"datasetVersionId": dsid, "status": "SILVER_NORMALIZED", "quarantine": "QUARANTINED",
                                 "modelEligible": False, "approvedForTraining": False, "selectable": False,
                                 "manifestSha256": p["manifest_sha"], "transformReceiptSha256": "x", "rows": 1,
                                 "seasons": [2023], "sourceObjectId": "s"})


def test_failed_publication_leaves_no_registry_entry(tmp_path):
    # a sealed-season source cannot even be published as a source -> nothing registered downstream
    from tests._silver_fixture import source_rows
    import pytest
    rows = source_rows(); rows[0]["season"] = 2025
    with pytest.raises(SP.SourceAuthorityError):
        SP.publish_source_object(source_root=tmp_path / "src", rows=rows, dataset_version_id="bad",
                                 season_of_row=lambda r: r["season"])
    assert not (tmp_path / "silver" / "silver-registry.json").is_file()
