"""Phase 7D.5A.2 (Repair 7) — fully data-hermetic isolated runner + external-data access guard.

Proves the hardcoded model-exchange fallback is gone under the isolated gate, and that the data-access guard blocks
any open of the real model-exchange corpus or the real ``.runtime`` while allowing isolated-root / temp opens.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server.sports_cockpit import game_preps as GP
from tests import _isolated_data_guard as G


def test_play_transition_glob_avoids_model_exchange_under_isolation(monkeypatch):
    monkeypatch.setenv("ASP_REQUIRE_ISOLATED_RUNTIME", "1")
    monkeypatch.setenv("ASP_MODEL_EXCHANGE_ROOT", r"C:/Users/james/asp-model-exchange")
    g = GP.resolve_play_transition_glob()
    assert "asp-model-exchange" not in g.replace("\\", "/")
    assert "ISOLATED-UNAVAILABLE" in g       # resolves to a non-existent path beneath the isolated runtime root


def test_play_transition_glob_uses_exchange_when_not_isolated(monkeypatch):
    monkeypatch.delenv("ASP_REQUIRE_ISOLATED_RUNTIME", raising=False)
    monkeypatch.setenv("ASP_MODEL_EXCHANGE_ROOT", r"C:/some/exchange")
    g = GP.resolve_play_transition_glob()
    assert "some/exchange" in g.replace("\\", "/")


def _guarded(monkeypatch, tmp_path):
    """Activate the guard's decision with controlled roots (no global reader wrapping in this unit test). The
    intentional violations these tests trigger are captured in a LOCAL list so they never contaminate the real
    isolated-gate session manifest."""
    monkeypatch.setitem(G._installed, "on", True)
    monkeypatch.setattr(G, "_violations", [])       # isolate this test's intentional violations
    monkeypatch.setattr(G, "_current_nodeid", {"id": "<unit-test>"})
    iso_runtime = tmp_path / "iso-runtime"
    repo = tmp_path / "repo"
    real_rt = repo / ".runtime"
    for p in (iso_runtime, repo, real_rt):
        p.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(G, "_allowed_roots", lambda: [iso_runtime.resolve(), Path(tmp_path).resolve()])
    monkeypatch.setattr(G, "_repo_root", lambda: repo.resolve())
    monkeypatch.setattr(G, "_real_runtime", lambda: real_rt.resolve())
    return iso_runtime, repo, real_rt


def test_guard_blocks_real_model_exchange_open(monkeypatch, tmp_path):
    _guarded(monkeypatch, tmp_path)
    with pytest.raises(G.IsolatedDataViolation):
        G.check_open(r"C:/Users/james/asp-model-exchange/datasets/mlb-fd1/x.parquet", "pyarrow.parquet.read_table")


def test_guard_blocks_real_runtime_sealed_open(monkeypatch, tmp_path):
    _iso, _repo, real_rt = _guarded(monkeypatch, tmp_path)
    with pytest.raises(G.IsolatedDataViolation) as ei:
        G.check_open(str(real_rt / "sports-modeling" / "sealed-2025.parquet"), "pandas.read_parquet")
    assert "2025" in str(ei.value) or "sealed" in str(ei.value).lower()


def test_guard_allows_isolated_runtime_and_temp_opens(monkeypatch, tmp_path):
    iso_runtime, repo, _real = _guarded(monkeypatch, tmp_path)
    G.check_open(str(iso_runtime / "sports-modeling" / "obj.parquet"), "pyarrow.parquet.read_table")
    G.check_open(str(tmp_path / "scratch.parquet"), "pandas.read_parquet")
    # a NON-data file is never guarded
    G.check_open(r"C:/Users/james/asp-model-exchange/config.json", "pandas.read_json")


def test_guard_ignores_when_not_installed(monkeypatch, tmp_path):
    monkeypatch.setitem(G._installed, "on", False)
    G.check_open(r"C:/Users/james/asp-model-exchange/x.parquet", "pyarrow.parquet.read_table")  # inert
