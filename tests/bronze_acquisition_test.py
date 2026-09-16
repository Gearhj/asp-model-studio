"""Hermetic tests for the quarantined Bronze acquisition tool (Phase 7B0). No real network: downloads use
local file:// URLs; archives are built in-memory. Proves the year boundary (no 2025/2026), path/traversal
containment, safe archive extraction, atomic + resumable download, hash integrity, secret redaction,
manifest canonicalization, and source/game-type separation."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from tools.bronze_acquisition import safety, download, manifest, sources
from tools.bronze_acquisition.safety import BronzeBoundaryError


def _file_url(p: Path) -> str:
    return "file:///" + str(p.resolve()).replace("\\", "/")


# ---------------- year boundary ----------------
@pytest.mark.parametrize("bad", [2025, 2026, 2030, 2018])
def test_year_boundary_rejected(bad):
    with pytest.raises(BronzeBoundaryError):
        safety.assert_year_allowed(bad)


@pytest.mark.parametrize("good", [2019, 2020, 2021, 2022, 2023, 2024])
def test_year_boundary_allowed(good):
    assert safety.assert_year_allowed(good) == good


@pytest.mark.parametrize("bad", ["2025-01-01", "2025-12-31", "2026-04-01", "2024-13-01", "notadate"])
def test_date_boundary_rejected(bad):
    with pytest.raises(BronzeBoundaryError):
        safety.assert_date_allowed(bad)


def test_statcast_url_refuses_sealed_year():
    with pytest.raises(BronzeBoundaryError):
        sources.statcast_url("R", "2025-04-01", "2025-04-01")
    with pytest.raises(BronzeBoundaryError):
        sources.statcast_partitions(2024, 2025)


def test_current_statcast_extension_is_explicit_and_cutoff_bounded():
    assert safety.assert_current_statcast_date_allowed("2025-03-01") == "2025-03-01"
    assert safety.assert_current_statcast_date_allowed("2026-08-27") == "2026-08-27"
    for bad in ("2024-12-31", "2026-08-28", "2027-01-01"):
        with pytest.raises(BronzeBoundaryError):
            safety.assert_current_statcast_date_allowed(bad)

    parts = sources.current_statcast_partitions("2026-08-25", "2026-08-27")
    assert [part.query["date"] for part in parts] == ["2026-08-25", "2026-08-26", "2026-08-27"]
    assert all(part.scope == "regular" and "hfGT=R%7C" in part.url for part in parts)
    assert all(part.natural_keys == ["game_pk", "at_bat_number", "pitch_number"] for part in parts)


# ---------------- path containment ----------------
def test_contained_path_rejects_traversal_and_absolute(tmp_path):
    safety.contained_path(tmp_path, "a", "b.csv")            # ok
    with pytest.raises(BronzeBoundaryError):
        safety.contained_path(tmp_path, "..", "evil.csv")
    with pytest.raises(BronzeBoundaryError):
        safety.contained_path(tmp_path, "C:/Windows/evil.csv")


def test_safe_filename_normalizes():
    assert safety.safe_filename("../../etc/passwd") == "passwd"
    assert safety.safe_filename("gl2024.zip") == "gl2024.zip"
    with pytest.raises(BronzeBoundaryError):
        safety.safe_filename("..")


# ---------------- secret redaction ----------------
def test_redact_removes_secrets():
    assert "<redacted>" in safety.redact("https://x/y?token=SECRETVALUE&a=1")
    assert "SECRETVALUE" not in safety.redact("https://x/y?token=SECRETVALUE&a=1")
    assert "AKIAsigned" not in safety.redact("https://s3/x?X-Amz-Signature=AKIAsigned")


# ---------------- safe archive extraction ----------------
def _zip_with(members: dict, symlink_name: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
        if symlink_name:
            info = zipfile.ZipInfo(symlink_name)
            info.external_attr = 0o120777 << 16  # symlink mode
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


def test_safe_extract_normal(tmp_path):
    z = tmp_path / "ok.zip"; z.write_bytes(_zip_with({"a.txt": "hello", "sub/b.txt": "world"}))
    out = safety.safe_extract_zip(z, tmp_path / "out")
    assert sorted(out) == ["a.txt", "sub/b.txt"]
    assert (tmp_path / "out" / "a.txt").read_text() == "hello"


def test_safe_extract_rejects_traversal(tmp_path):
    z = tmp_path / "evil.zip"; z.write_bytes(_zip_with({"../evil.txt": "x"}))
    with pytest.raises(BronzeBoundaryError):
        safety.safe_extract_zip(z, tmp_path / "out")


def test_safe_extract_rejects_symlink(tmp_path):
    z = tmp_path / "sym.zip"; z.write_bytes(_zip_with({"ok.txt": "x"}, symlink_name="link"))
    with pytest.raises(BronzeBoundaryError):
        safety.safe_extract_zip(z, tmp_path / "out")


# ---------------- download: atomic, resumable, integrity ----------------
def test_download_atomic_and_reuse(tmp_path):
    src = tmp_path / "src.csv"; src.write_text("game_pk,at_bat_number,pitch_number\n1,1,1\n")
    dest = tmp_path / "landing" / "out.csv"
    r1 = download.http_download(_file_url(src), dest, max_retries=1)
    assert dest.is_file() and r1["reused"] is False and r1["bytes"] > 0
    assert not dest.with_suffix(".csv.partial").exists()          # partial cleaned up
    r2 = download.http_download(_file_url(src), dest, max_retries=1)  # second call reuses (no redownload)
    assert r2["reused"] is True and r2["sha256"] == r1["sha256"]


def test_download_rejects_html(tmp_path):
    html = tmp_path / "err.html"; html.write_text("<!DOCTYPE html><html><title>error</title></html>")
    with pytest.raises(download.DownloadError):
        download.http_download(_file_url(html), tmp_path / "o.csv", max_retries=1)


def test_download_rejects_empty(tmp_path):
    empty = tmp_path / "empty.csv"; empty.write_bytes(b"")
    with pytest.raises(download.DownloadError):
        download.http_download(_file_url(empty), tmp_path / "o.csv", max_retries=1)


def test_download_no_overwrite_divergent(tmp_path):
    dest = tmp_path / "o.csv"; dest.write_text("existing verified bytes")
    src = tmp_path / "src.csv"; src.write_text("DIFFERENT bytes")
    # dest already exists -> reused by sha (no redownload, no overwrite)
    r = download.http_download(_file_url(src), dest, max_retries=1)
    assert r["reused"] is True and dest.read_text() == "existing verified bytes"


# ---------------- manifest: canonicalization + resume ----------------
def test_manifest_canonicalization_stable(tmp_path):
    import hashlib
    (tmp_path / "a.csv").write_text("hi")
    m = manifest.BronzeManifest(tmp_path)
    m.upsert({"partitionId": "s/1", "source": "s", "status": "COMPLETE", "relativePath": "a.csv",
              "fileSha256": hashlib.sha256((tmp_path / "a.csv").read_bytes()).hexdigest()})
    sha_a = m.write()
    m2 = manifest.BronzeManifest(tmp_path); sha_b = m2.write()
    assert sha_a == sha_b                                          # deterministic
    assert m2.has_valid("s/1")                                    # resume sees the completed partition
    assert not m2.has_valid("s/does-not-exist")


def test_manifest_resume_rehashes_recorded_bytes(tmp_path):
    target = tmp_path / "a.csv"
    target.write_text("original")
    import hashlib
    m = manifest.BronzeManifest(tmp_path)
    m.upsert({"partitionId": "s/1", "source": "s", "status": "COMPLETE", "relativePath": "a.csv",
              "fileSha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    m.write()
    assert m.has_valid("s/1")
    target.write_text("tampered")
    assert not m.has_valid("s/1")


def test_inspect_csv_counts_and_dupes(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("game_pk,at_bat_number,pitch_number,game_date\n1,1,1,2024-04-01\n1,1,1,2024-04-01\n1,1,2,2024-04-02\n")
    info = manifest.inspect_csv(p, natural_keys=["game_pk", "at_bat_number", "pitch_number"], date_col="game_date")
    assert info["rowCount"] == 3 and info["columnCount"] == 4
    assert info["naturalKeyDuplicateCount"] == 1                  # one duplicate (game_pk,ab,pitch) tuple
    assert info["minDate"] == "2024-04-01" and info["maxDate"] == "2024-04-02"


# ---------------- source / game-type separation ----------------
def test_statcast_regular_and_postseason_separated():
    parts = sources.statcast_partitions(2024, 2024)
    regular = [p for p in parts if p.scope == "regular"]
    post = [p for p in parts if p.scope == "postseason"]
    assert regular and post
    assert all("regular" in p.rel_dir and "hfGT=R%7C" in p.url for p in regular)
    assert all("postseason" in p.rel_dir and "hfGT=PO%7C" in p.url for p in post)
    assert all(p.natural_keys == ["game_pk", "at_bat_number", "pitch_number"] for p in parts)
    # per-day partitions (safe under the Savant row cap), never monthly
    assert all(p.query.get("date") for p in parts)
