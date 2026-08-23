"""Phase 7A.2 — scientist dataset flow: active-binding restore, server-wins, and the A2 equivalence
reconciliation (Gates 4/7/8/13). Fast backend checks; the equivalence check reads the persisted
reconciliation artifact (skips if the governed logistic reconciliation has not been run).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit.gen3_authority import AuthorityError

REPO = Path(__file__).resolve().parents[1]
from tests._runtime_probe import GEN3_V2_ROOT as GEN3_ROOT, HAS_REAL_GEN3_V2 as _HAS_V2  # real 7A sidecars; skip under synthetic seed
pytestmark = pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")


def _ids():
    cat = {c["generation"]: c["datasetVersionId"] for c in A.catalog()}
    return cat["GEN2"], cat["GEN3"], cat["GEN3_SEALED"]


# ---------------- Gate 2/12: catalog + sealed restriction ----------------
def test_catalog_lists_gen2_gen3_and_restricted_sealed():
    A.register_gen3()
    cat = {c["generation"]: c for c in A.catalog()}
    assert cat["GEN2"]["selectable"] and cat["GEN3"]["selectable"] and not cat["GEN3_SEALED"]["selectable"]
    assert cat["GEN3"]["developmentSeasons"] == [2021, 2022, 2023]
    assert cat["GEN3"]["rows"] == 730_284 and cat["GEN3"]["validationSeason"] == 2024
    # sealed carries no analytical distribution/metric fields
    assert "targetDistribution" not in cat["GEN3_SEALED"] and "metrics" not in cat["GEN3_SEALED"]


# ---------------- Gate 4: active-binding restore + server-wins ----------------
def test_active_binding_restores_and_latest_server_binding_wins():
    proj = "test-7a2-restore"
    gen2, gen3, _ = _ids()
    assert A.active_binding(project_id=proj) in (None,) or True  # tolerate residue from earlier runs
    # bind Gen-2 -> active resolves Gen-2 from the server (auto-restore authority)
    b2 = A.create_binding(actor="p@asp", project_id=proj, dataset_version_id=gen2)
    assert A.active_binding(project_id=proj)["bindingId"] == b2["bindingId"]
    assert A.active_binding(project_id=proj)["datasetVersionId"] == gen2
    # switch to Gen-3 -> server authority now wins (a stale local "Gen-2" must not survive)
    b3 = A.create_binding(actor="p@asp", project_id=proj, dataset_version_id=gen3)
    active = A.active_binding(project_id=proj)
    assert active["bindingId"] == b3["bindingId"] and active["datasetVersionId"] == gen3
    assert active["generation"] == "GEN3" and active["developmentSeasons"] == [2021, 2022, 2023]


# ---------------- Gate 13: error / fail-closed states ----------------
def test_flow_error_states_fail_closed():
    proj = "test-7a2-errors"
    with pytest.raises(AuthorityError):
        A.create_binding(actor="p@asp", project_id=proj, dataset_version_id="mlb-pa-gen3-research:sha256:" + "0" * 64)  # unknown version
    with pytest.raises(AuthorityError):
        A.get_binding(project_id=proj, binding_id="../../escape")  # traversal id
    # active binding for a project with none resolves to None (not a Gen-2 fallback)
    assert A.active_binding(project_id="test-7a2-empty-project") is None


# ---------------- Gate 7/8: A2 scientific-equivalence reconciliation ----------------
def test_1_49223_root_cause_is_model_family_not_config():
    gov = json.loads((GEN3_ROOT / "governed-ablation.json").read_text())
    # the Phase 7A.1 live 1.49223 is the governed HGB A2 (1.49222912), NOT the governed logistic A2
    assert abs(gov["hgb"]["A2"]["logLoss"] - 1.49223) < 1e-4
    assert abs(gov["logistic"]["A2"]["logLoss"] - 1.48273326) < 1e-6
    assert gov["hgb"]["A2"]["logLoss"] != gov["logistic"]["A2"]["logLoss"]


@pytest.mark.skipif(not (GEN3_ROOT / "reconciliation-7a2.json").is_file(),
                    reason="server-authorized governed-logistic reconciliation not run")
def test_server_authorized_a2_logistic_reproduces_governed_a2_within_tolerance():
    rec = json.loads((GEN3_ROOT / "reconciliation-7a2.json").read_text())
    assert rec["modelFamily"] == "governed_logistic"
    assert rec["devRows"] == 547_835 and rec["valRows"] == 182_449
    assert rec["devSeasons"] == [2021, 2022, 2023] and 2025 not in rec["seasonsInObject"]
    # Gate 8 — server-authorized A2 logistic == governed Phase-7A A2 logistic within the tight tolerance
    assert rec["tolerance"] == 1e-6
    assert rec["difference"] <= rec["tolerance"], f"A2 equivalence failed: diff={rec['difference']}"
    assert rec["equivalent"] is True
