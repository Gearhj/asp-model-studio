"""Phase 7A — Gen-3 authority, immutability, blinding, quarantine, and security (Gate 12).

Hermetic fail-closed gates for the parts that do not require the materialized runtime artifact
(contracts, publisher immutability/tamper/idempotency, path-traversal containment, user-Python default),
plus real-artifact acceptance checks that skip cleanly when the v2 authority has not been published.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pytest

from server.sports_modeling import gen3_contracts as C
from server.sports_modeling.gen3_publish import publish_object, logical_content_sha, Gen3PublishError, _schema_sha
from server.sports_cockpit import modeling as M
from server.sports_cockpit.engine import CockpitError

REPO = Path(__file__).resolve().parents[1]
from tests._runtime_probe import GEN3_V2_ROOT as AUTHORITY, HAS_REAL_GEN3_V2 as _HAS_V2  # real published authority content
skip_v2 = pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")

HEX64 = lambda s: isinstance(s, str) and len(s) == 64 and all(ch in "0123456789abcdef" for ch in s)


# ---------------- Gate 1: canonical contracts ----------------
def test_all_seven_contracts_have_canonical_digests_and_are_deterministic():
    contracts = C.all_contracts()
    assert set(contracts) == {"target", "featureSchema", "baseFeature", "knowledgeTime", "temporal", "preprocessing", "population"}
    for name, c in contracts.items():
        assert HEX64(c["sha256"]) and c["id"].endswith(c["sha256"])
    # recomputing yields identical digests (canonical determinism)
    again = C.all_contracts()
    assert {k: v["sha256"] for k, v in contracts.items()} == {k: v["sha256"] for k, v in again.items()}
    assert HEX64(C.contract_bundle_sha())


def test_temporal_contract_seals_2025_and_2026():
    t = C.temporal_contract()["payload"]
    assert t["development"] == [2021, 2022, 2023] and t["validationSelection"] == 2024
    assert t["sealedSecondaryOot"] == 2025 and t["prospectiveSealed"] == 2026
    assert 2025 not in t["development"] and 2025 not in t["researchFrameSeasons"]


def test_preprocessing_contract_declares_governed_mean_standardize():
    p = C.preprocessing_contract()["payload"]
    assert "MEAN" in p["numericImputation"] and "STANDARDIZE" in p["numericScaling"]
    assert p["imputationScope"] == "TRAINING_ROWS_OF_THIS_FIT_ONLY"


# ---------------- Gate 3/4: immutable content-addressed publication ----------------
def _tiny_table(v=1):
    return pa.table({"plate_appearance_id": [f"pa-{v}-{i}" for i in range(4)], "season": pa.array([2023] * 4, pa.int16()),
                     "outcome": ["BIP_OUT"] * 4, "x": pa.array([float(v)] * 4, pa.float64())})


def test_publisher_is_content_addressed_idempotent_and_tamper_safe(tmp_path):
    contracts = C.all_contracts(); bundle = C.contract_bundle_sha()
    t = _tiny_table(1)
    m1 = publish_object(tmp_path, t, object_kind="research", contracts=contracts, contract_bundle_sha=bundle, provenance_extra={})
    sha = m1["logicalContentSha256"]
    obj = tmp_path / "objects" / "sha256" / sha / "research.parquet"
    assert HEX64(sha) and obj.is_file() and not m1["reused"]
    # embedded parquet metadata binds critical identities (Gate 4)
    import pyarrow.parquet as pq
    meta = pq.read_schema(obj).metadata or {}
    assert meta.get(b"contractBundleSha256", b"").decode() == bundle
    assert meta.get(b"logicalContentSha256", b"").decode() == sha
    # idempotent reuse: same table republishes to the same object, reused=True
    m2 = publish_object(tmp_path, t, object_kind="research", contracts=contracts, contract_bundle_sha=bundle, provenance_extra={})
    assert m2["reused"] and m2["logicalContentSha256"] == sha
    # tamper rejection: corrupt the immutable object, republish the same logical table -> reject
    obj.write_bytes(obj.read_bytes() + b"tamper")
    with pytest.raises(Gen3PublishError):
        publish_object(tmp_path, t, object_kind="research", contracts=contracts, contract_bundle_sha=bundle, provenance_extra={})


def test_publisher_rejects_symlinked_object_dir(tmp_path):
    contracts = C.all_contracts(); bundle = C.contract_bundle_sha()
    t = _tiny_table(7)
    m = publish_object(tmp_path, t, object_kind="research", contracts=contracts, contract_bundle_sha=bundle, provenance_extra={})
    obj_dir = tmp_path / "objects" / "sha256" / m["logicalContentSha256"]
    # replace the object dir with a symlink to an attacker dir; publisher must reject on reuse
    import shutil
    evil = tmp_path / "evil"; evil.mkdir(); (evil / "research.parquet").write_bytes(b"x")
    shutil.rmtree(obj_dir)
    try:
        obj_dir.symlink_to(evil, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted in this environment")
    with pytest.raises(Gen3PublishError):
        publish_object(tmp_path, t, object_kind="research", contracts=contracts, contract_bundle_sha=bundle, provenance_extra={})


# ---------------- Gate 11: security containment ----------------
def test_experiment_id_path_traversal_is_rejected():
    for bad in ["../../secret", "..%2f..%2fx", "cockpit-exp-../x", "/etc/passwd", "cockpit-exp-zz", "cockpit-x-abcdef12"]:
        with pytest.raises(CockpitError):
            M.get_experiment(bad)
    assert M.get_experiment("cockpit-exp-deadbeef12345678") is None  # valid form, absent -> None


def test_user_python_execution_is_disabled_by_default():
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_ENABLE_PYTHON_RUN")}
    env.pop("ATLAS_HOSTED_MODE", None)
    out = subprocess.check_output(
        [sys.executable, "-c", "import server.python_execution as p; print(p.EXECUTION_ENABLED)"],
        cwd=str(REPO), env={**env, "PYTHONPATH": str(REPO)}, stderr=subprocess.STDOUT,
    ).decode().strip().splitlines()[-1]
    assert out == "False"


# ---------------- Gate 2/5: real-artifact acceptance (skip if unpublished) ----------------
@skip_v2
def test_registration_binds_research_and_sealed_objects():
    reg = json.loads((AUTHORITY / "registration.json").read_text())
    assert HEX64(reg["research"]["logicalContentSha256"]) and HEX64(reg["sealed2025"]["logicalContentSha256"])
    assert reg["research"]["seasons"] == [2021, 2022, 2023, 2024]
    assert reg["sealed2025"]["seasons"] == [2025]
    assert reg["research"]["logicalContentSha256"] != reg["sealed2025"]["logicalContentSha256"]


@skip_v2
def test_2025_is_physically_absent_from_the_research_object():
    import pyarrow.parquet as pq
    reg = json.loads((AUTHORITY / "registration.json").read_text())
    research = AUTHORITY / "objects" / "sha256" / reg["research"]["logicalContentSha256"] / "research.parquet"
    seasons = set(pq.read_table(research, columns=["season"])["season"].to_pylist())
    assert seasons == {2021, 2022, 2023, 2024} and 2025 not in seasons and 2026 not in seasons
    sealed = AUTHORITY / "objects" / "sha256" / reg["sealed2025"]["logicalContentSha256"] / "sealed-2025.parquet"
    assert set(pq.read_table(sealed, columns=["season"])["season"].to_pylist()) == {2025}


@skip_v2
def test_innings_15_16_are_included_and_only_convention_rows_quarantined():
    import pyarrow.parquet as pq
    reg = json.loads((AUTHORITY / "registration.json").read_text())
    research = AUTHORITY / "objects" / "sha256" / reg["research"]["logicalContentSha256"] / "research.parquet"
    innings = pq.read_table(research, columns=["context_inning"])["context_inning"].to_pylist()
    assert max(innings) >= 15  # long games no longer excluded
    # quarantine is convention-only (139), reconciled in registration
    assert reg["quarantineTotal"] == 139


@skip_v2
def test_quarantine_ledger_is_content_addressed_and_row_level():
    reg = json.loads((AUTHORITY / "registration.json").read_text())
    sha = reg["quarantineLedgerSha256"]
    ledger_path = AUTHORITY / "objects" / "sha256" / sha / "quarantine-ledger.json"
    assert ledger_path.is_file()
    records = json.loads(ledger_path.read_text())["records"]
    assert len(records) == 139
    for r in records:
        assert set(["plate_appearance_id", "game_id", "season", "reasonCode", "decisionRuleVersion"]).issubset(r)
        assert r["reasonCode"] == "BATTING_TEAM_CONVENTION_ANOMALY"
        assert "outcome" not in r  # never an outcome-conditioned exclusion
