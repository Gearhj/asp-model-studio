"""Governed data-preview contract for the PA modeling matrix (Phase 6C.5).

The scientist must SEE real bound data before modeling. These tests prove the preview is real
(registered rows, real schema/roles/target), bounded (never a large payload), season-filterable,
and leakage-honest — with no file-path leakage. Skips when the feature view is not materialized.
No heavy modeling is exercised.
"""

from __future__ import annotations

import json

import pytest

from server.sports_cockpit import engine as E
from server.sports_modeling.metrics import PA_CLASS_ORDER

_HAS_VIEW = True
try:
    E._feature_view_path()
except Exception:
    _HAS_VIEW = False

pytestmark = pytest.mark.skipif(not _HAS_VIEW, reason="D3 feature view not materialized")


def test_preview_is_bounded():
    assert len(E.data_preview(limit=10)["rows"]) == 10
    assert len(E.data_preview(limit=25)["rows"]) == 25
    assert len(E.data_preview(limit=999)["rows"]) <= 50  # clamp — never a large payload


def test_preview_rows_are_real_registered_records():
    p = E.data_preview(limit=25)
    assert p["grain"] == "PLATE_APPEARANCE"
    assert p["matrix"] == "MLB_PA_FEATURE_VIEW_V1"
    r0 = p["rows"][0]
    assert r0["outcome"] in PA_CLASS_ORDER          # real 8-class target value
    assert isinstance(r0["game_id"], str) and r0["game_id"]  # real registered game id
    assert r0["season"] in (2023, 2024, 2025)
    # not synthetic fixtures: a real retrosheet-style game id and a uuid batter
    assert "-" in str(r0["batter_canonical_player_uuid"])


def test_preview_schema_roles():
    schema = {s["name"]: s for s in E.data_preview(limit=5)["schema"]}
    assert schema["outcome"]["role"] == "TARGET"
    assert schema["game_date"]["role"] == "TIME"
    assert schema["season"]["role"] == "TIME"
    assert schema["game_id"]["role"] == "GROUPING"
    assert schema["plate_appearance_id"]["role"] == "IDENTIFIER"
    assert schema["batter_canonical_player_uuid"]["role"] == "IDENTIFIER"
    assert schema["batter_avg"]["role"] == "FEATURE"
    assert schema["pitcher_era9"]["role"] == "FEATURE"
    # missing % is a real fraction; batter priors carry real missingness, ids do not
    assert schema["batter_avg"]["missingPct"] > 0.0
    assert schema["game_id"]["missingPct"] == 0.0


def test_preview_target_distribution_and_splits():
    p = E.data_preview(limit=5)
    classes = {t["class"] for t in p["targetDistribution"]}
    assert classes == set(PA_CLASS_ORDER)
    assert sum(t["count"] for t in p["targetDistribution"]) == p["filteredRows"]
    roles = {s["role"]: s["rows"] for s in p["splitCounts"]}
    assert set(roles) == {"development", "validation", "frozen_final"}
    assert all(v > 100_000 for v in roles.values())  # real per-season counts


def test_preview_season_filter():
    p = E.data_preview(season=2024, limit=25)
    assert p["season"] == 2024
    assert p["filteredRows"] == roles_2024()
    assert all(r["season"] == 2024 for r in p["rows"])


def roles_2024() -> int:
    frame = E.load_frame()
    return int((frame["season"] == 2024).sum())


def test_preview_leaks_no_filesystem_paths():
    payload = json.dumps(E.data_preview(limit=25))
    for banned in ("C:\\\\", "C:/Users", ".runtime", ".parquet", "asp-model-exchange", "sha256"):
        assert banned not in payload, f"preview payload leaked a path token: {banned}"
