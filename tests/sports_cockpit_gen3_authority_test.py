"""Phase 7A.1 authority behavior, hardened for 7A.3 (Gate 25 isolation): each test uses its OWN opaque
project so binding supersession never crosses tests. Covers the Gen-2/Gen-3 execution distinction,
physical 2025 blinding through execution, fail-closed forgery/staleness, retry identity, result-authority
echo, activation, and project scoping. Executions use the fast deterministic governed HGB.
"""
from __future__ import annotations

import json
import uuid
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit.gen3_authority import AuthorityError, StaleAuthorityError

REPO = Path(__file__).resolve().parents[1]
_HAS_V2 = (REPO / ".runtime/asp-model-studio/sports-modeling/mlb-pa-gen3-v2/registration.json").is_file()
pytestmark = pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")

ACTOR = "pytest@asp"


def _proj() -> str:
    return "test-7a1-" + uuid.uuid4().hex[:12]  # isolated opaque project per test


def _ids():
    cat = {c["generation"]: c["datasetVersionId"] for c in A.catalog()}
    return cat["GEN2"], cat["GEN3"], cat["GEN3_SEALED"]


def _run(proj: str, dsid: str, family: str = "governed_hgb"):
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=dsid)
    au = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"], model_family=family)
    ev = A.execute(actor=ACTOR, project_id=proj, run_authority_id=au["runAuthorityId"])
    return b, au, ev


@pytest.fixture(scope="module")
def executed():
    A.register_gen3()
    gen2, gen3, _ = _ids()
    p2, p3 = _proj(), _proj()  # each generation in its OWN project so neither supersedes the other
    b2, a2, e2 = _run(p2, gen2)
    b3, a3, e3 = _run(p3, gen3)
    return {"gen2": {"proj": p2, "binding": b2, "authority": a2, "evidence": e2, "dsid": gen2},
            "gen3": {"proj": p3, "binding": b3, "authority": a3, "evidence": e3, "dsid": gen3}}


# ---------------- catalog / binding ----------------
def test_catalog_registers_gen2_gen3_and_restricted_sealed():
    A.register_gen3()
    cat = {c["generation"]: c for c in A.catalog()}
    assert cat["GEN2"]["selectable"] and cat["GEN3"]["selectable"]
    assert not cat["GEN3_SEALED"]["selectable"] and cat["GEN3_SEALED"]["status"] == "SEALED_OOT_RESTRICTED"


def test_sealed_object_is_not_bindable():
    _, _, sealed = _ids()
    with pytest.raises(AuthorityError):
        A.create_binding(actor=ACTOR, project_id=_proj(), dataset_version_id=sealed)


def test_binding_rejects_client_forged_content_sha():
    _, gen3, _ = _ids()
    with pytest.raises(AuthorityError):
        A.create_binding(actor=ACTOR, project_id=_proj(), dataset_version_id=gen3, expected_content_sha="deadbeef" * 8)


# ---------------- Gate 12 (7A.3): Gen-2 / Gen-3 execution distinction ----------------
def test_gen2_selection_executes_gen2_and_gen3_selection_executes_gen3(executed):
    e2, e3 = executed["gen2"]["evidence"], executed["gen3"]["evidence"]
    assert e2["generation"] == "GEN2" and e2["developmentSeasons"] == [2023] and e2["developmentRows"] == 184_104
    assert e3["generation"] == "GEN3" and e3["developmentSeasons"] == [2021, 2022, 2023] and e3["developmentRows"] == 547_835
    assert e2["datasetContentSha256"] != e3["datasetContentSha256"]
    assert e2["validationRows"] == e3["validationRows"] == 182_449
    # generation-specific contracts (A2-04): a Gen-2 result never carries a Gen-3 contract id
    assert "GEN2" in e2["targetContractId"] and "GEN3" in e3["targetContractId"]


def test_2025_is_never_loaded_scored_or_returned(executed):
    e3 = executed["gen3"]["evidence"]
    assert 2025 not in e3["seasonsInObject"] and e3["sealedSeasonsAccessed"] == []
    assert 2025 not in e3["developmentSeasons"] and e3["validationSeason"] != 2025
    assert "2025" not in json.dumps(e3["metrics"])


# ---------------- Gate 8/11: fail-closed forgery / staleness / drift ----------------
@pytest.mark.parametrize("field", ["datasetContentSha256", "targetContractSha256", "temporalContractSha256",
                                   "featureContractSha256", "preprocessingContractSha256", "knowledgeTimeContractSha256"])
def test_execute_fails_closed_on_any_forged_authority_sha(field):
    proj = _proj()
    _, gen3, _ = _ids()
    b = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=gen3)
    au = A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb")
    path = A._state(proj, "authorities", f"{au['runAuthorityId']}.json")
    forged = json.loads(path.read_text()); forged[field] = "deadbeef" * 8
    path.write_text(json.dumps(forged))
    with pytest.raises(AuthorityError):
        A.execute(actor=ACTOR, project_id=proj, run_authority_id=au["runAuthorityId"])


def test_superseded_binding_cannot_issue_or_execute():
    proj = _proj()
    gen2, gen3, _ = _ids()
    b1 = A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=gen2)
    A.create_binding(actor=ACTOR, project_id=proj, dataset_version_id=gen3)  # supersedes b1
    with pytest.raises(StaleAuthorityError):
        A.issue_run_authority(actor=ACTOR, project_id=proj, binding_id=b1["bindingId"], model_family="governed_hgb")


# ---------------- Gate 9/10/11: identity, retry, complete echo ----------------
def test_result_authority_echoes_run_authority_with_full_receipt(executed):
    for k in ("gen2", "gen3"):
        au, ev = executed[k]["authority"], executed[k]["evidence"]
        assert ev["runAuthorityId"] == au["runAuthorityId"]
        assert ev["canonicalEffectiveConfigSha256"] == au["canonicalEffectiveConfigSha256"]
        assert ev["datasetContentSha256"] == au["datasetContentSha256"] == ev["objectReceipt"]["logicalContentSha256"]
        assert ev["bindingRevision"] == au["bindingRevision"]
        for f in ("predictionFingerprint", "modelFingerprint", "preprocessorFingerprint", "worktreeContentSha256"):
            assert ev[f] and ev[f] != "UNKNOWN"


def test_retries_get_unique_run_ids_with_a_constant_config_fingerprint(executed):
    proj, au = executed["gen3"]["proj"], executed["gen3"]["authority"]
    a = A.execute(actor=ACTOR, project_id=proj, run_authority_id=au["runAuthorityId"])
    b = A.execute(actor=ACTOR, project_id=proj, run_authority_id=au["runAuthorityId"])
    assert a["experimentRunId"] != b["experimentRunId"]
    assert a["canonicalEffectiveConfigSha256"] == b["canonicalEffectiveConfigSha256"]
    assert A.get_run(project_id=proj, run_id=a["experimentRunId"])["status"] == "COMPLETE"


# ---------------- Gate 14/15: activation + project scoping ----------------
def test_runs_are_project_scoped(executed):
    proj, run_id = executed["gen3"]["proj"], executed["gen3"]["evidence"]["experimentRunId"]
    assert A.get_run(project_id=proj, run_id=run_id)["experimentRunId"] == run_id
    with pytest.raises(AuthorityError):
        A.get_run(project_id="test-7a1-other-" + uuid.uuid4().hex[:8], run_id=run_id)


def test_candidate_activation_and_downstream_resolution(executed):
    proj, run_id = executed["gen3"]["proj"], executed["gen3"]["evidence"]["experimentRunId"]
    act = A.activate_candidate(actor=ACTOR, project_id=proj, run_id=run_id)
    assert act["experimentRunId"] == run_id and act["schemaVersion"] == "ACTIVE_CANDIDATE_REVIEW_V2"
    # downstream resolves the active candidate by run id from the backend (A2-14), never a browser result
    dc = A.get_active_candidate(project_id=proj)
    assert dc["experimentRunId"] == run_id and dc["run"]["runAuthorityId"] == act["runAuthorityId"]
    blob = json.dumps(act)
    assert "champion" not in blob.lower() and "2025" not in blob


def test_opaque_ids_are_validated():
    proj = _proj()
    for bad in ["../x", "..%2f", "not-hex", "z" * 32]:
        with pytest.raises(AuthorityError):
            A.get_run(project_id=proj, run_id=bad)
