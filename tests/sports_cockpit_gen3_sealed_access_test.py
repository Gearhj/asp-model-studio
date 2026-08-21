"""Phase 7C Gate 27 — hermetic PRODUCTION-RESOLVER proof that the ordinary scientist workflow never opens a
sealed object and never reads a 2025 target row, metric, or prediction.

Unlike the earlier stub-based test, this exercises the REAL production catalog/registry resolver against the
REAL published immutable objects (Gen-2 research/sealed + Gen-3 research/sealed). Only the per-project
authority STATE is isolated to a temp root. Every registered-object open is instrumented through
`gen3_authority._record_open`; the legacy in-process engine is proven research-only behaviorally.

Assertions: sealed object opens = 0; research objects DO open (non-vacuous); no sealed season enters a fold;
no 2025 payload appears in evidence/diagnostics; the legacy engine frame is 2023-2024 only.
"""
from __future__ import annotations

import json

import pytest

from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit import engine as E


def _sealed_object_paths() -> set[str]:
    """Resolve the on-disk paths of the sealed objects from the real registrations (never opened here)."""
    paths = set()
    for root, kinds in ((A.GEN2_ROOT, ("gen2-sealed-2025",)), (A.GEN3_ROOT, ("sealed-2025",))):
        reg = json.loads((root / "registration.json").read_text(encoding="utf-8"))
        sha = reg["sealed2025"]["logicalContentSha256"]
        for kind in kinds:
            p = root / "objects" / "sha256" / sha / f"{kind}.parquet"
            paths.add(str(p.resolve()))
    return paths


@pytest.fixture()
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "STATE_ROOT", tmp_path / "authority")
    A.reset_object_open_log()
    A._VERIFIED_OBJECT_CACHE.clear()
    return {"sealed": _sealed_object_paths()}


def _research_entry(generation: str) -> dict:
    return next(e for e in A.catalog() if e["generation"] == generation)


def test_catalog_opens_no_object(isolated_state):
    A.reset_object_open_log()
    cat = A.catalog()
    assert A.object_open_log() == [], f"catalog opened objects: {A.object_open_log()}"
    assert {e["generation"] for e in cat} == {"GEN2", "GEN2_SEALED", "GEN3", "GEN3_SEALED"}
    # sealed entries are not selectable and carry no ordinary objectPath
    for e in cat:
        if e["generation"].endswith("_SEALED"):
            assert e["selectable"] is False and not e.get("objectPath")


@pytest.mark.parametrize("generation", ["GEN2", "GEN3"])
def test_ordinary_flow_never_opens_a_sealed_object(isolated_state, generation):
    proj = f"hermetic-7c-{generation.lower()}"
    A.reset_object_open_log()
    research = _research_entry(generation)
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=research["datasetVersionId"])
    au = A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"],
                               model_family="governed_hgb", hyperparameters={"maxIter": 30})
    ev = A.execute(actor="t@asp", project_id=proj, run_authority_id=au["runAuthorityId"])
    A.activate_candidate(actor="t@asp", project_id=proj, run_id=ev["experimentRunId"])
    ce = A.active_candidate_evaluation(project_id=proj)
    rc = A.recompute_validation_logloss(project_id=proj, run_id=ev["experimentRunId"])

    opens = A.object_open_log()
    # (a) SEAL: no sealed object path is ever opened by the ordinary flow
    assert not (set(opens) & isolated_state["sealed"]), "a sealed object was opened by the ordinary flow"
    # (b) non-vacuous: the research object WAS opened
    assert any(research["logicalContentSha256"] in p for p in opens), "research object was not opened (vacuous)"
    # (c) no sealed season in the executed fold or the object
    assert 2025 not in ev["seasonsInObject"] and ev["sealedSeasonsAccessed"] == []
    assert 2025 not in ev["developmentSeasons"] and ev["validationSeason"] == 2024
    # (d) no 2025 payload anywhere in evidence / diagnostics
    assert "2025" not in json.dumps(ev["metrics"])
    assert "2025" not in json.dumps(ce["diagnostics"])
    assert "frozen2025" not in json.dumps(ce)
    # (e) independent recomputation from persisted artifacts matches the stored metric
    assert ce["recomputationMatchesStored"] is True
    assert abs(rc["recomputedLogLoss"] - float(ev["metrics"]["logLoss"])) < 1e-9


def test_binding_a_sealed_object_is_refused_and_never_opens_it(isolated_state):
    A.reset_object_open_log()
    sealed_ids = [e["datasetVersionId"] for e in A.catalog() if e["generation"].endswith("_SEALED")]
    for sid in sealed_ids:
        with pytest.raises(A.AuthorityError):
            A.create_binding(actor="t@asp", project_id="hermetic-refuse", dataset_version_id=sid)
    assert not (set(A.object_open_log()) & isolated_state["sealed"])


def test_binding_population_derives_without_opening_any_object(isolated_state):
    proj = "hermetic-7c-pop"
    A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=_research_entry("GEN3")["datasetVersionId"])
    A.reset_object_open_log()
    pop = A.binding_population(project_id=proj)
    assert A.object_open_log() == [], "binding_population opened an object"
    assert pop["generation"] == "GEN3" and pop["validationSeason"] == 2024
    assert pop["sealedSeasons"] == [2025] and 2025 not in pop["developmentSeasons"]
    assert pop["knowledgeTimeSafetyClass"] == "CONDITIONAL_PRE_TERMINAL_PA_STATE"
    # per-season rows are the registered receipts (not fabricated by equal division)
    dev = [s for s in pop["seasons"] if s["role"] == "DEVELOPMENT"]
    assert {s["rows"] for s in dev} != {None} and len({s["rows"] for s in dev}) >= 2  # not all equal


def test_legacy_engine_frame_is_research_only(isolated_state):
    # The retired combined 2023-2025 object is never the ordinary engine frame.
    path = E._feature_view_path()
    assert path.name == "gen2-research.parquet"
    frame = E.load_frame()
    seasons = sorted(set(int(s) for s in frame["season"].unique()))
    assert seasons == [2023, 2024], f"legacy engine frame exposed {seasons}"
    assert "2025" not in json.dumps([s["season"] for s in E.target_analysis()["perSeason"]])
