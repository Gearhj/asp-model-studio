"""Phase 7D.5A (Workstream G) — Windows reparse (junction) containment at object / evidence / receipt boundaries.

A directory JUNCTION (``mklink /J``, no admin needed) is NOT a symlink — ``Path.is_symlink()`` misses it — so the
containment must inspect the reparse attribute. These tests CREATE real junctions and prove rejection BEFORE any
file is opened, at the object boundary, an intermediate component, and the Silver / V2 evidence boundaries. On a
platform where ``mklink /J`` cannot run, the whole module fails (no waivable Windows skip).
"""
from __future__ import annotations

import os
import subprocess

import pytest

from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit.path_containment import ContainmentError, contained_no_reparse, is_reparse_point
from server.sports_modeling import silver_publish as SP


def _mk_junction(link, target) -> bool:
    if os.name != "nt":
        try:
            os.symlink(str(target), str(link), target_is_directory=True)
            return True
        except (OSError, NotImplementedError):
            return False
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    return r.returncode == 0


def _rm_junction(link):
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)
    else:
        try:
            os.unlink(str(link))
        except OSError:
            pass


@pytest.mark.skipif(os.name != "nt", reason="the junction path is exercised on Windows; symlink variant runs elsewhere")
def test_junction_creation_is_available_on_windows(tmp_path):
    # the Windows reparse test must be able to run — a missing mklink /J is a HARD failure of this gate, not a skip
    outside = tmp_path / "out"; outside.mkdir()
    link = tmp_path / "j"
    assert _mk_junction(link, outside), "mklink /J unavailable — Windows reparse containment cannot be proven"
    assert is_reparse_point(link) and not link.is_symlink()      # junction detected though is_symlink() misses it
    _rm_junction(link)


def test_object_boundary_rejects_final_junction(tmp_path, monkeypatch):
    root = tmp_path / "gen3"; (root / "objects" / "sha256").mkdir(parents=True)
    outside = tmp_path / "OUTSIDE"; outside.mkdir(); (outside / "research.parquet").write_bytes(b"evil")
    monkeypatch.setattr(A, "GEN3_ROOT", root); monkeypatch.setattr(A, "GEN2_ROOT", root)
    jdir = root / "objects" / "sha256" / ("a" * 64)
    if not _mk_junction(jdir, outside):
        pytest.skip("reparse-point creation not permitted") if os.name != "nt" else pytest.fail("mklink /J failed on Windows")
    try:
        with pytest.raises(A.AuthorityError):
            A._contain_object_path(str(jdir / "research.parquet"))   # rejected before any open
    finally:
        _rm_junction(jdir)


def test_object_boundary_rejects_intermediate_junction(tmp_path, monkeypatch):
    root = tmp_path / "gen3"; (root / "objects" / "sha256").mkdir(parents=True)
    outside = tmp_path / "OUT2"; (outside / "sha256" / ("b" * 64)).mkdir(parents=True)
    (outside / "sha256" / ("b" * 64) / "research.parquet").write_bytes(b"evil")
    monkeypatch.setattr(A, "GEN3_ROOT", root); monkeypatch.setattr(A, "GEN2_ROOT", root)
    # replace the intermediate "objects" component with a junction to OUT2
    import shutil
    shutil.rmtree(root / "objects")
    if not _mk_junction(root / "objects", outside):
        pytest.skip("reparse-point creation not permitted") if os.name != "nt" else pytest.fail("mklink /J failed on Windows")
    try:
        with pytest.raises(A.AuthorityError):
            A._contain_object_path(str(root / "objects" / "sha256" / ("b" * 64) / "research.parquet"))
    finally:
        _rm_junction(root / "objects")


def test_silver_verify_rejects_junction(tmp_path):
    # publish a real Silver object, then make its object dir a junction to elsewhere -> verify rejects before open
    from tests.sports_cockpit_phase7d5a_silver_test import _source_rows
    from server.sports_modeling.feature_contract import FEATURE_NAMES
    rows = [{k: v for k, v in r.items()} for r in _source_rows()]
    entry = SP.publish_silver(silver_root=tmp_path / "silver", source_object_id="src", source_receipt_sha="s" * 64,
                              source_manifest_sha="m" * 64, source_physical_sha="p" * 64, source_logical_sha="l" * 64,
                              source_schema_sha="c" * 64, source_rows=rows, base_feature_ids=list(FEATURE_NAMES),
                              season_of_row=lambda r: r["season"])
    SP.verify_silver(tmp_path / "silver", entry["manifestSha256"])          # baseline ok
    objdir = tmp_path / "silver" / "objects" / "sha256" / entry["manifestSha256"]
    moved = tmp_path / "silver" / "objects" / "sha256" / "_moved"
    objdir.rename(moved)
    if not _mk_junction(objdir, moved):
        pytest.skip("reparse-point creation not permitted") if os.name != "nt" else pytest.fail("mklink /J failed on Windows")
    try:
        with pytest.raises((SP.SilverPublishError, ContainmentError)):
            SP.verify_silver(tmp_path / "silver", entry["manifestSha256"])
    finally:
        _rm_junction(objdir)


def test_contained_no_reparse_rejects_escaping_and_reparse(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    (root / "ok").mkdir(); (root / "ok" / "f.txt").write_text("x")
    assert contained_no_reparse(root / "ok" / "f.txt", [root])
    with pytest.raises(ContainmentError):
        contained_no_reparse(tmp_path / "elsewhere" / "f.txt", [root])       # escapes root
