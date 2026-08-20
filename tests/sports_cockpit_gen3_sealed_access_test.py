"""Phase 7A.4 Gate 13 — hermetic proof that the ordinary scientist workflow never opens the sealed 2025
object. Uses STUB research (2021-2024) + STUB sealed (2025) parquet fixtures (NOT the real sealed object),
instruments every registered-object open in gen3_authority, exercises the full flow
(catalog -> bind -> run authority -> execute -> activate -> active candidate), and asserts the sealed
object's path is opened 0 times and no 2025 payload appears in the result.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from server.sports_cockpit import gen3_authority as A
from server.sports_modeling.feature_contract import FEATURE_NAMES
from server.sports_modeling.metrics import PA_CLASS_ORDER

_CATEG = {"context_top_bottom": [0, 1], "context_outs_before": [0, 1, 2], "context_base_mask_before": list(range(8))}


def _stub_table(seasons, per_class=12, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for s in seasons:
        for cls_i, cls in enumerate(PA_CLASS_ORDER):
            for k in range(per_class):
                r = {"plate_appearance_id": f"{s}-{cls_i}-{k}-{rng.integers(1e9)}",
                     "game_id": f"g{s}{k % 3}", "game_date": f"{s}-0{1 + (k % 2)}-15",
                     "season": s, "outcome": cls}
                for f in FEATURE_NAMES:
                    if f in _CATEG:
                        r[f] = float(rng.choice(_CATEG[f]))
                    elif f == "context_inning":
                        r[f] = float(rng.integers(1, 10))
                    elif f == "context_batting_score_diff_before":
                        r[f] = float(rng.integers(-5, 6))
                    else:
                        r[f] = float(rng.random())
                rows.append(r)
    cols = {k: [r[k] for r in rows] for k in rows[0]}
    schema = pa.schema([("plate_appearance_id", pa.string()), ("game_id", pa.string()), ("game_date", pa.string()),
                        ("season", pa.int16()), ("outcome", pa.string()), *[(f, pa.float64()) for f in FEATURE_NAMES]])
    return pa.table({k: (pa.array(v, pa.int16()) if k == "season" else v) for k, v in cols.items()}, schema=schema)


def _publish_stub(objects_root: Path, kind: str, table: pa.Table):
    sha = hashlib.sha256(table.to_pandas().to_json().encode()).hexdigest()
    d = objects_root / "objects" / "sha256" / sha
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{kind}.parquet"
    pq.write_table(table, p)
    return sha, p, hashlib.sha256(p.read_bytes()).hexdigest(), table.num_rows, sorted(set(int(x) for x in table["season"].to_pylist()))


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "STATE_ROOT", tmp_path / "authority")
    research = _stub_table([2021, 2022, 2023, 2024], seed=1)
    sealed = _stub_table([2025], per_class=6, seed=2)
    r_sha, r_path, r_phys, r_rows, r_seasons = _publish_stub(tmp_path, "research", research)
    s_sha, s_path, s_phys, s_rows, s_seasons = _publish_stub(tmp_path, "sealed-2025", sealed)

    def stub_catalog():
        return [
            {"datasetVersionId": f"stub-research:sha256:{r_sha}", "label": "Stub Research", "generation": "GEN3",
             "status": "GOVERNED_RESEARCH_DATASET", "selectable": True, "logicalContentSha256": r_sha,
             "physicalParquetSha256": r_phys, "objectPath": str(r_path), "seasons": r_seasons,
             "developmentSeasons": [2021, 2022, 2023], "validationSeason": 2024, "sealedSeasons": [2025],
             "rows": r_rows, "featureCount": len(FEATURE_NAMES), "target": "outcome"},
            {"datasetVersionId": f"stub-sealed:sha256:{s_sha}", "label": "Stub Sealed", "generation": "GEN3_SEALED",
             "status": "SEALED_OOT_RESTRICTED", "selectable": False, "logicalContentSha256": s_sha,
             "objectPath": str(s_path), "seasons": s_seasons, "developmentSeasons": [], "validationSeason": None,
             "sealedSeasons": [2025], "rows": s_rows, "target": "outcome"},
        ]
    monkeypatch.setattr(A, "catalog", stub_catalog)
    return {"research_id": f"stub-research:sha256:{r_sha}", "sealed_path": str(s_path.resolve())}


def test_ordinary_workflow_never_opens_the_sealed_object(hermetic):
    A.reset_object_open_log()
    proj = "hermetic-sealed"
    # full ordinary flow
    _ = A.catalog()
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=hermetic["research_id"])
    au = A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"], model_family="governed_hgb")
    ev = A.execute(actor="t@asp", project_id=proj, run_authority_id=au["runAuthorityId"])
    A.activate_candidate(actor="t@asp", project_id=proj, run_id=ev["experimentRunId"])
    A.get_active_candidate(project_id=proj)

    opens = A.object_open_log()
    sealed_opens = [p for p in opens if p == hermetic["sealed_path"]]
    assert sealed_opens == [], f"sealed object was opened {len(sealed_opens)} times"
    # the research object WAS opened (proves instrumentation is live, not vacuous)
    assert any("research.parquet" in p for p in opens)
    # no 2025 payload in the result
    assert 2025 not in ev["seasonsInObject"] and ev["sealedSeasonsAccessed"] == []
    assert ev["validationSeason"] == 2024 and 2025 not in ev["developmentSeasons"]
    assert "2025" not in json.dumps(ev["metrics"])


def test_binding_a_sealed_object_is_refused_and_never_opens_it(hermetic):
    A.reset_object_open_log()
    sealed_id = next(c["datasetVersionId"] for c in A.catalog() if c["generation"] == "GEN3_SEALED")
    with pytest.raises(A.AuthorityError):
        A.create_binding(actor="t@asp", project_id="hermetic-refuse", dataset_version_id=sealed_id)
    assert hermetic["sealed_path"] not in A.object_open_log()


# ---------------- Gate 8/9: authorized autopilot / tuning suite ----------------
def test_authorized_suite_runs_every_candidate_through_the_single_path(hermetic):
    proj = "hermetic-suite"
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=hermetic["research_id"])
    out = A.run_authorized_suite(actor="t@asp", project_id=proj, binding_id=b["bindingId"], source="autopilot",
                                 candidates=[{"family": "governed_hgb", "label": "hgb-a", "hyperparameters": {"maxIter": 40}},
                                             {"family": "governed_hgb", "label": "hgb-b", "hyperparameters": {"maxIter": 60}}])
    assert out["source"] == "autopilot" and out["candidateCount"] == 2
    run_ids = set()
    for c in out["candidates"]:
        assert c["runAuthorityId"] and c["experimentRunId"]        # every candidate has a server run authority
        assert c["generation"] == "GEN3" and c["validationRows"] > 0
        assert c["sealedSeasonsAccessed"] == []                    # never scores 2025
        run_ids.add(c["experimentRunId"])
    assert len(run_ids) == 2                                        # unique immutable run ids
    assert out["best"] in run_ids                                  # best selected by run id
    # each candidate is independently resolvable as immutable run evidence
    for rid in run_ids:
        assert A.get_run(project_id=proj, run_id=rid)["status"] == "COMPLETE"
    assert hermetic["sealed_path"] not in A.object_open_log()


def test_authorized_suite_is_blocked_without_an_active_binding(hermetic):
    with pytest.raises(A.AuthorityError):
        A.run_authorized_suite(actor="t@asp", project_id="hermetic-nobinding", binding_id="0" * 32,
                               candidates=[{"family": "governed_hgb"}])
