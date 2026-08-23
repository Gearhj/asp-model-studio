"""Phase 7D.5A (Workstream I) — Silver publication concurrency across SEPARATE OS processes.

Proves the content-addressed, create-once, atomic Silver publisher is safe under real interprocess contention:
identical content converges idempotently; divergent content under the same address fails closed; an atomic publish
leaves no partial/staging directory; the completed object stays verifiable; and a failed publish leaves no
model-eligible registry entry.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling import silver_publish as SP

REPO = Path(__file__).resolve().parents[1]


def _worker(silver_root: Path, seed: int):
    return subprocess.Popen([sys.executable, "-m", "tests._silver_worker", str(silver_root), str(seed)],
                            cwd=str(REPO), env={"PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1",
                                                **__import__("os").environ},
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def test_identical_content_converges_idempotently_across_processes(tmp_path):
    root = tmp_path / "silver"
    a = _worker(root, 1); b = _worker(root, 1)                 # SAME seed -> byte-identical content
    oa = a.communicate(timeout=120)[0].strip(); ob = b.communicate(timeout=120)[0].strip()
    assert oa.startswith("OK ") and ob.startswith("OK "), (oa, ob)
    assert oa.split()[1] == ob.split()[1]                      # same content-address; converged
    # the completed object is verifiable after contention
    manifest_sha = oa.split()[1]
    v = SP.verify_silver(root, manifest_sha)
    assert v["manifest"]["modelEligible"] is False
    # no partial/staging directory left behind
    assert list((root / "objects" / "sha256").glob(".staging-*")) == []


def test_divergent_content_under_same_address_fails_closed(tmp_path):
    # publish once, then attempt to place DIVERGENT bytes at the same content-address -> conflict fail-closed
    a = _worker(tmp_path / "silver", 2)
    out = a.communicate(timeout=120)[0].strip()
    assert out.startswith("OK "), out
    manifest_sha = out.split()[1]
    final = tmp_path / "silver" / "objects" / "sha256" / manifest_sha
    # corrupt the published manifest bytes so a re-publish of the SAME address sees divergent content
    (final / "manifest.json").write_bytes(canonical_json_bytes({"tampered": True}))
    b = _worker(tmp_path / "silver", 2)                        # same seed -> same target address, but bytes diverge
    out2 = b.communicate(timeout=120)[0].strip()
    assert out2.startswith("ERR ") and "conflict" in out2.lower(), out2


def test_failed_publication_leaves_no_model_eligible_entry(tmp_path):
    # a publish that fails (sealed-season source) must not register anything
    root = tmp_path / "silver"
    from tests.sports_cockpit_phase7d5a_silver_test import _source_rows
    from server.sports_modeling.feature_contract import FEATURE_NAMES
    rows = [{k: v for k, v in r.items()} for r in _source_rows()]
    rows[0]["season"] = 2025
    import pytest
    with pytest.raises(SP.SilverPublishError):
        SP.publish_silver(silver_root=root, source_object_id="x", source_receipt_sha="s" * 64,
                          source_manifest_sha="m" * 64, source_physical_sha="p" * 64, source_logical_sha="l" * 64,
                          source_schema_sha="c" * 64, source_rows=rows, base_feature_ids=list(FEATURE_NAMES),
                          season_of_row=lambda r: r["season"])
    reg = root / "silver-registry.json"
    if reg.is_file():
        import json
        assert not (json.loads(reg.read_text()).get("datasets") or {})     # nothing registered
