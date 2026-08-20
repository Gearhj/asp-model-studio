"""Phase 7A.1 — Gen-3 server authority + execution binding (Gates 12/13/15/17/18).

Proves the invariant UI = SERVER = TRAINING = RESULT authority (fail-closed): registration + catalog,
server-authoritative project binding, run authority with a canonical effective-config fingerprint,
fail-closed validation (forged dataset/target/temporal/feature/preprocessing SHA + stale binding +
project mismatch), Gen-2/Gen-3 execution distinction, physical 2025 blinding through the execution path,
unique retry run ids with a constant config fingerprint (append-only), result-authority echo, candidate
activation, project scoping, and opaque-id containment. Executions use the fast deterministic governed
HGB. Skips cleanly if the Gen-3 v2 authority has not been published.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit.gen3_authority import AuthorityError

REPO = Path(__file__).resolve().parents[1]
_HAS_V2 = (REPO / ".runtime/asp-model-studio/sports-modeling/mlb-pa-gen3-v2/registration.json").is_file()
pytestmark = pytest.mark.skipif(not _HAS_V2, reason="Gen-3 v2 authority not published")

PROJ = "test-gen3-authority"
ACTOR = "pytest@asp"


def _ids():
    cat = {c["generation"]: c["datasetVersionId"] for c in A.catalog()}
    return cat["GEN2"], cat["GEN3"], cat["GEN3_SEALED"]


@pytest.fixture(scope="module")
def executed():
    A.register_gen3()
    gen2, gen3, _ = _ids()
    out = {}
    for name, dsid in (("gen2", gen2), ("gen3", gen3)):
        b = A.create_binding(actor=ACTOR, project_id=PROJ, dataset_version_id=dsid)
        au = A.issue_run_authority(actor=ACTOR, project_id=PROJ, binding_id=b["bindingId"], model_family="governed_hgb")
        ev = A.execute(actor=ACTOR, project_id=PROJ, run_authority_id=au["runAuthorityId"])
        out[name] = {"binding": b, "authority": au, "evidence": ev, "datasetVersionId": dsid}
    return out


# ---------------- registration + catalog (Gate 1/2) ----------------
def test_catalog_registers_gen2_gen3_and_restricted_sealed():
    A.register_gen3()
    cat = {c["generation"]: c for c in A.catalog()}
    assert cat["GEN2"]["selectable"] and cat["GEN3"]["selectable"]
    assert not cat["GEN3_SEALED"]["selectable"] and cat["GEN3_SEALED"]["status"] == "SEALED_OOT_RESTRICTED"
    assert cat["GEN3"]["developmentSeasons"] == [2021, 2022, 2023] and cat["GEN3"]["validationSeason"] == 2024
    assert 2025 not in cat["GEN3"]["seasons"]
    reg = json.loads((A.ASP_REGISTRY).read_text())
    assert any(d["datasetVersionId"] == cat["GEN3"]["datasetVersionId"] for d in reg["datasets"])


# ---------------- binding (Gate 4) ----------------
def test_sealed_object_is_not_bindable():
    _, _, sealed = _ids()
    with pytest.raises(AuthorityError):
        A.create_binding(actor=ACTOR, project_id=PROJ, dataset_version_id=sealed)


def test_binding_rejects_client_forged_content_sha():
    _, gen3, _ = _ids()
    with pytest.raises(AuthorityError):
        A.create_binding(actor=ACTOR, project_id=PROJ, dataset_version_id=gen3, expected_content_sha="deadbeef" * 8)


# ---------------- Gate 12: Gen-2 / Gen-3 execution distinction ----------------
def test_gen2_selection_executes_gen2_and_gen3_selection_executes_gen3(executed):
    e2, e3 = executed["gen2"]["evidence"], executed["gen3"]["evidence"]
    assert e2["generation"] == "GEN2" and e2["developmentSeasons"] == [2023] and e2["developmentRows"] == 184_104
    assert e3["generation"] == "GEN3" and e3["developmentSeasons"] == [2021, 2022, 2023] and e3["developmentRows"] == 547_835
    assert e2["datasetContentSha256"] != e3["datasetContentSha256"]           # different immutable objects
    assert e2["validationRows"] == e3["validationRows"] == 182_449            # common 2024 validation


def test_gen3_fit_contains_2021_2022_2023_and_validation_is_2024_only(executed):
    e3 = executed["gen3"]["evidence"]
    for y in (2021, 2022, 2023):
        assert y in e3["developmentSeasons"]
    assert e3["validationSeason"] == 2024


# ---------------- Gate 13: physical 2025 blinding through execution ----------------
def test_2025_is_never_loaded_scored_or_returned_for_gen3(executed):
    e3 = executed["gen3"]["evidence"]
    assert 2025 not in e3["seasonsInObject"] and 2026 not in e3["seasonsInObject"]
    assert e3["sealedSeasonsLoaded"] == []
    assert 2025 not in e3["developmentSeasons"] and e3["validationSeason"] != 2025
    # the sealed object is a separate registration and never appears as an executed object
    assert "2025" not in json.dumps(e3["metrics"])


# ---------------- Gate 8: fail-closed forgery / staleness rejection ----------------
def _fresh_authority(dsid):
    b = A.create_binding(actor=ACTOR, project_id=PROJ, dataset_version_id=dsid)
    return A.issue_run_authority(actor=ACTOR, project_id=PROJ, binding_id=b["bindingId"], model_family="governed_hgb")


@pytest.mark.parametrize("field", ["datasetContentSha256", "targetContractSha256", "temporalContractSha256",
                                   "featureContractSha256", "preprocessingContractSha256"])
def test_execute_fails_closed_on_any_forged_authority_sha(field):
    _, gen3, _ = _ids()
    au = _fresh_authority(gen3)
    path = A.STATE_ROOT / "authorities" / PROJ / f"{au['runAuthorityId']}.json"
    forged = json.loads(path.read_text()); forged[field] = "deadbeef" * 8
    path.write_text(json.dumps(forged))
    with pytest.raises(AuthorityError):
        A.execute(actor=ACTOR, project_id=PROJ, run_authority_id=au["runAuthorityId"])


def test_execute_fails_closed_on_forged_feature_set():
    _, gen3, _ = _ids()
    au = _fresh_authority(gen3)
    path = A.STATE_ROOT / "authorities" / PROJ / f"{au['runAuthorityId']}.json"
    forged = json.loads(path.read_text()); forged["featureSet"] = forged["featureSet"][:-1]
    path.write_text(json.dumps(forged))
    with pytest.raises(AuthorityError):
        A.execute(actor=ACTOR, project_id=PROJ, run_authority_id=au["runAuthorityId"])


def test_run_authority_rejects_stale_binding():
    _, gen3, _ = _ids()
    b = A.create_binding(actor=ACTOR, project_id=PROJ, dataset_version_id=gen3)
    path = A.STATE_ROOT / "bindings" / PROJ / f"{b['bindingId']}.json"
    stale = json.loads(path.read_text()); stale["datasetContentSha256"] = "deadbeef" * 8
    path.write_text(json.dumps(stale))
    with pytest.raises(AuthorityError):
        A.issue_run_authority(actor=ACTOR, project_id=PROJ, binding_id=b["bindingId"], model_family="governed_hgb")


# ---------------- Gate 9/11: identity, retry, echo ----------------
def test_result_authority_echoes_run_authority(executed):
    for k in ("gen2", "gen3"):
        au, ev = executed[k]["authority"], executed[k]["evidence"]
        assert ev["runAuthorityId"] == au["runAuthorityId"]
        assert ev["canonicalEffectiveConfigSha256"] == au["canonicalEffectiveConfigSha256"]
        assert ev["datasetContentSha256"] == au["datasetContentSha256"]


def test_retries_get_unique_run_ids_with_a_constant_config_fingerprint(executed):
    au = executed["gen3"]["authority"]
    a = A.execute(actor=ACTOR, project_id=PROJ, run_authority_id=au["runAuthorityId"])
    b = A.execute(actor=ACTOR, project_id=PROJ, run_authority_id=au["runAuthorityId"])
    assert a["experimentRunId"] != b["experimentRunId"]                       # append-only, never overwrite
    assert a["canonicalEffectiveConfigSha256"] == b["canonicalEffectiveConfigSha256"]
    # both are independently resolvable from the backend (persistence)
    assert A.get_run(project_id=PROJ, run_id=a["experimentRunId"])["status"] == "COMPLETE"
    assert A.get_run(project_id=PROJ, run_id=b["experimentRunId"])["status"] == "COMPLETE"


# ---------------- Gate 15: project scoping + Gate 14 activation ----------------
def test_runs_are_project_scoped(executed):
    run_id = executed["gen3"]["evidence"]["experimentRunId"]
    assert A.get_run(project_id=PROJ, run_id=run_id)["experimentRunId"] == run_id
    with pytest.raises(AuthorityError):
        A.get_run(project_id="some-other-project", run_id=run_id)  # not found for a different project


def test_candidate_activation_binds_run_identity_without_touching_champion(executed):
    run_id = executed["gen3"]["evidence"]["experimentRunId"]
    act = A.activate_candidate(actor=ACTOR, project_id=PROJ, run_id=run_id)
    assert act["experimentRunId"] == run_id and act["runAuthorityId"]
    assert act["schemaVersion"] == "CANDIDATE_ACTIVATION_V1"
    # activation carries no champion/D3/2025 semantics
    blob = json.dumps(act)
    assert "champion" not in blob.lower() and "2025" not in blob


def test_opaque_ids_are_validated():
    for bad in ["../x", "..%2f", "not-hex", "z" * 32]:
        with pytest.raises(AuthorityError):
            A.get_run(project_id=PROJ, run_id=bad)
        with pytest.raises(AuthorityError):
            A.get_run_authority(project_id=PROJ, run_authority_id=bad)
