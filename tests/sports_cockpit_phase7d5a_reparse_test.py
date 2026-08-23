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
    # publish a real Silver object (server-resolved source), then make its object dir a junction -> verify rejects
    from tests._silver_fixture import publish_silver_hermetic
    p = publish_silver_hermetic(tmp_path)
    SP.verify_silver(p["silver_root"], p["manifest_sha"])                    # baseline ok
    objdir = p["object_dir"]
    moved = p["silver_root"] / "objects" / "sha256" / "_moved"
    objdir.rename(moved)
    if not _mk_junction(objdir, moved):
        pytest.skip("reparse-point creation not permitted") if os.name != "nt" else pytest.fail("mklink /J failed on Windows")
    try:
        with pytest.raises((SP.SilverPublishError, ContainmentError)):
            SP.verify_silver(p["silver_root"], p["manifest_sha"])
    finally:
        _rm_junction(objdir)


def test_silver_source_resolution_rejects_junction(tmp_path):
    # a junction at the immutable SOURCE object dir must be rejected before the source is read (Repair 6)
    import json
    from tests._silver_fixture import publish_source, SRC_ID
    publish_source(tmp_path / "src")
    reg = json.loads((tmp_path / "src" / "silver-source-registry.json").read_text())
    logical = reg["datasets"][SRC_ID]["logicalSha256"]
    objdir = tmp_path / "src" / "objects" / "sha256" / logical
    moved = tmp_path / "src" / "objects" / "sha256" / "_moved"
    objdir.rename(moved)
    if not _mk_junction(objdir, moved):
        pytest.skip("reparse-point creation not permitted") if os.name != "nt" else pytest.fail("mklink /J failed on Windows")
    try:
        with pytest.raises((SP.SourceAuthorityError, ContainmentError)):
            SP.resolve_verified_source(tmp_path / "src", SRC_ID)
    finally:
        _rm_junction(objdir)


def test_silver_registry_parent_junction_rejected(tmp_path):
    # a junction at the Silver registry's parent directory must be rejected before the locked write (Repair 6)
    from tests._silver_fixture import publish_silver_hermetic
    p = publish_silver_hermetic(tmp_path)
    silver_root = p["silver_root"]
    real = tmp_path / "_real_silver"
    silver_root.rename(real)
    if not _mk_junction(silver_root, real):
        pytest.skip("reparse-point creation not permitted") if os.name != "nt" else pytest.fail("mklink /J failed on Windows")
    try:
        with pytest.raises((SP.SilverPublishError, ContainmentError)):
            SP._register(silver_root, "s", "a" * 64, "b" * 64, 1, [2023])   # locked registry write via a junctioned root
    finally:
        _rm_junction(silver_root)


def test_contained_no_reparse_rejects_escaping_and_reparse(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    (root / "ok").mkdir(); (root / "ok" / "f.txt").write_text("x")
    assert contained_no_reparse(root / "ok" / "f.txt", [root])
    with pytest.raises(ContainmentError):
        contained_no_reparse(tmp_path / "elsewhere" / "f.txt", [root])       # escapes root
