from __future__ import annotations

import io
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import server.sports_nfl.bronze_acquisition as bronze_acquisition
from server.sports_nfl.bronze_acquisition import (
    NflBronzeError,
    ReleaseAsset,
    acquire_nflverse_bronze,
    discover_release_asset,
    download_release_asset,
    verify_nflverse_bronze,
)
from server.sports_nfl.source_contracts import (
    MANDATORY_FAMILIES,
    NFLVERSE_SOURCE_FAMILIES,
    OPTIONAL_FAMILIES,
)


class _Response(io.BytesIO):
    def __init__(self, value: bytes, *, status: int = 200, headers: dict[str, str] | None = None) -> None:
        super().__init__(value)
        self.status = status
        self.headers = headers or {}


def _parquet_bytes(tmp_path: Path, name: str, value: dict[str, list[object]]) -> bytes:
    path = tmp_path / name
    pq.write_table(pa.table(value), path)
    return path.read_bytes()


def _official_url(tag: str, name: str) -> str:
    return f"https://github.com/nflverse/nflverse-data/releases/download/{tag}/{name}"


def _provider_fakes(tmp_path: Path, season: int = 2024):
    assets = {
        "schedules": ("games.parquet", _parquet_bytes(tmp_path, "schedule-source.parquet", {
            "game_id": ["2024_01_A_B"], "season": [season], "gameday": ["2024-09-05"],
        })),
        "pbp": (f"play_by_play_{season}.parquet", _parquet_bytes(tmp_path, "pbp-source.parquet", {
            "game_id": ["2024_01_A_B"], "play_id": [1], "season": [season], "game_date": ["2024-09-05"],
        })),
        "teams": ("teams_colors_logos.parquet", _parquet_bytes(tmp_path, "teams-source.parquet", {
            "team_abbr": ["BUF"],
        })),
        "stats_player": (f"stats_player_week_{season}.parquet", _parquet_bytes(tmp_path, "stats-source.parquet", {
            "player_id": ["00-1"], "season": [season], "week": [1],
        })),
        "rosters": (f"roster_{season}.parquet", _parquet_bytes(tmp_path, "roster-source.parquet", {
            "gsis_id": ["00-1"], "season": [season],
        })),
        "players": ("players.parquet", _parquet_bytes(tmp_path, "players-source.parquet", {
            "gsis_id": ["00-1"], "display_name": ["Player One"],
        })),
        "weekly_rosters": (f"roster_weekly_{season}.parquet", _parquet_bytes(tmp_path, "weekly-roster-source.parquet", {
            "gsis_id": ["00-1"], "season": [season], "week": [1],
        })),
        "stats_team": (f"stats_team_week_{season}.parquet", _parquet_bytes(tmp_path, "team-stats-source.parquet", {
            "team": ["BUF"], "season": [season], "week": [1],
        })),
    }
    by_url: dict[str, bytes] = {}
    releases: dict[str, dict[str, object]] = {}
    for tag, (name, content) in assets.items():
        url = _official_url(tag, name)
        by_url[url] = content
        releases[tag] = {
            "tag_name": tag,
            "published_at": "2026-08-28T01:02:03Z",
            "assets": [{
                "id": len(releases) + 100,
                "name": name,
                "size": len(content),
                "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                "updated_at": "2026-08-28T01:03:04Z",
                "browser_download_url": url,
            }],
        }

    def fetch(url: str):
        return releases[url.rsplit("/", 1)[-1]]

    def open_url(request):
        return _Response(by_url[request.full_url])

    return fetch, open_url


def test_family_contracts_freeze_mandatory_optional_and_license() -> None:
    assert MANDATORY_FAMILIES == (
        "schedules", "play_by_play", "teams", "players", "rosters", "weekly_rosters",
        "weekly_player_stats", "weekly_team_stats",
    )
    assert set(OPTIONAL_FAMILIES) >= {
        "snap_counts", "participation", "ngs_passing", "ngs_receiving", "ngs_rushing",
        "ftn_charting", "depth_charts", "injuries", "officials", "pfr_advanced_passing",
        "draft_picks", "combine", "trades", "contracts",
    }
    assert NFLVERSE_SOURCE_FAMILIES["schedules"].license_id == "CC-BY-4.0"
    assert NFLVERSE_SOURCE_FAMILIES["participation"].license_id == "CC-BY-SA-4.0"
    assert NFLVERSE_SOURCE_FAMILIES["participation"].attribution == "FTN Data via nflverse"
    assert NFLVERSE_SOURCE_FAMILIES["participation"].release_tag == "pbp_participation"
    assert NFLVERSE_SOURCE_FAMILIES["participation"].required_columns == ("nflverse_game_id", "play_id")
    assert NFLVERSE_SOURCE_FAMILIES["ngs_passing"].season_scoped is False
    assert NFLVERSE_SOURCE_FAMILIES["ngs_passing"].asset_name_pattern == r"^ngs_passing\.parquet$"
    assert NFLVERSE_SOURCE_FAMILIES["ftn_charting"].required_columns == (
        "nflverse_game_id", "nflverse_play_id",
    )
    assert (
        NFLVERSE_SOURCE_FAMILIES["snap_counts"].available_start_season,
        NFLVERSE_SOURCE_FAMILIES["snap_counts"].available_end_season,
    ) == (2012, 2025)
    assert all(value.file_format == "parquet" for value in NFLVERSE_SOURCE_FAMILIES.values())


def test_acquire_and_independently_verify_content_addressed_bronze(tmp_path: Path) -> None:
    fetch, open_url = _provider_fakes(tmp_path)
    root = tmp_path / "external-nfl-bronze"
    manifest_sha = acquire_nflverse_bronze(
        root, [2024], family_ids=MANDATORY_FAMILIES, json_fetcher=fetch, opener=open_url,
        clock=lambda: datetime(2026, 8, 28, 2, 3, 4, tzinfo=timezone.utc),
    )

    verified = verify_nflverse_bronze(root, manifest_sha)
    assert len(verified["partitions"]) == 8
    assert verified["modelsFitted"] == 0
    assert all(item["fileSha256"] and item["physicalSchemaSha256"] for item in verified["partitions"])
    assert all(item["releasePublishedAt"] == "2026-08-28T01:02:03Z" for item in verified["partitions"])
    assert all(item["assetId"] and item["assetUpdatedAt"] for item in verified["partitions"])
    assert all(item["retrievedAt"] == "2026-08-28T02:03:04+00:00" for item in verified["partitions"])
    assert all(item["sourceDigest"] == "sha256:" + item["fileSha256"] for item in verified["partitions"])
    assert json.loads((root / "current.json").read_text())["manifestSha256"] == manifest_sha
    assert acquire_nflverse_bronze(
        root, [2024], family_ids=MANDATORY_FAMILIES, json_fetcher=fetch, opener=open_url,
        clock=lambda: datetime(2026, 8, 29, 9, 10, 11, tzinfo=timezone.utc),
    ) == manifest_sha


def test_verifier_rejects_changed_source_bytes(tmp_path: Path) -> None:
    fetch, open_url = _provider_fakes(tmp_path)
    root = tmp_path / "external-nfl-bronze"
    manifest_sha = acquire_nflverse_bronze(
        root, [2024], family_ids=MANDATORY_FAMILIES, json_fetcher=fetch, opener=open_url,
    )
    manifest = verify_nflverse_bronze(root, manifest_sha)
    target = root.joinpath(*manifest["partitions"][0]["relativePath"].split("/"))
    with target.open("ab") as output:
        output.write(b"tamper")
    with pytest.raises(NflBronzeError, match="size mismatch"):
        verify_nflverse_bronze(root, manifest_sha)


def test_resumable_part_download_requires_exact_content_range(tmp_path: Path) -> None:
    content = b"0123456789"
    destination = tmp_path / "asset.parquet"
    destination.with_name("asset.parquet.part").write_bytes(content[:4])
    seen_range: list[str | None] = []

    def open_url(request):
        seen_range.append(request.get_header("Range"))
        return _Response(content[4:], status=206, headers={"Content-Range": "bytes 4-9/10"})

    asset = ReleaseAsset(
        "play_by_play", "pbp", "2026-08-28T01:02:03Z",
        "play_by_play_2024.parquet", _official_url("pbp", "play_by_play_2024.parquet"), len(content),
        123, "sha256:" + hashlib.sha256(content).hexdigest(),
        "2026-08-28T01:03:04Z", "2026-08-28T02:03:04Z",
    )
    assert download_release_asset(asset, destination, opener=open_url).read_bytes() == content
    assert seen_range == ["bytes=4-"]
    assert not destination.with_name("asset.parquet.part").exists()


def test_optional_missing_is_explicit_and_repo_root_is_rejected(tmp_path: Path) -> None:
    def fetch(_url: str):
        return {"tag_name": "snap_counts", "published_at": "2026-08-28T01:02:03Z", "assets": []}

    root = tmp_path / "external-nfl-bronze"
    manifest_sha = acquire_nflverse_bronze(root, [2024], family_ids=["snap_counts"], json_fetcher=fetch)
    manifest = verify_nflverse_bronze(root, manifest_sha)
    assert manifest["partitions"] == []
    assert manifest["optionalMissing"] == [
        {"familyId": "snap_counts", "season": 2024, "reason": "RELEASE_ASSET_ABSENT"},
    ]
    repository = Path(__file__).resolve().parents[1]
    with pytest.raises(NflBronzeError, match="external"):
        acquire_nflverse_bronze(repository / ".runtime" / "nfl", [2024], family_ids=["snap_counts"], json_fetcher=fetch)


def test_missing_mandatory_release_asset_fails_closed(tmp_path: Path) -> None:
    def fetch(_url: str):
        return {"tag_name": "schedules", "published_at": "2026-08-28T01:02:03Z", "assets": []}

    with pytest.raises(
        NflBronzeError,
        match=r"mandatory nflverse asset missing: schedules/2024",
    ):
        acquire_nflverse_bronze(
            tmp_path / "external-nfl-bronze",
            [2024],
            family_ids=["schedules"],
            json_fetcher=fetch,
        )


def test_optional_source_failure_is_governed_and_does_not_block_core(tmp_path: Path) -> None:
    def fetch(_url: str):
        raise OSError("provider unavailable")

    root = tmp_path / "external-nfl-bronze"
    manifest_sha = acquire_nflverse_bronze(
        root,
        [2024],
        family_ids=["snap_counts"],
        json_fetcher=fetch,
    )
    manifest = verify_nflverse_bronze(root, manifest_sha)
    assert manifest["partitions"] == []
    assert manifest["optionalMissing"] == [{
        "familyId": "snap_counts",
        "season": 2024,
        "reason": "SOURCE_DISCOVERY_FAILURE",
    }]


def test_verifier_rejects_reparse_partition_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fetch, open_url = _provider_fakes(tmp_path)
    root = tmp_path / "external-nfl-bronze"
    manifest_sha = acquire_nflverse_bronze(
        root, [2024], family_ids=MANDATORY_FAMILIES, json_fetcher=fetch, opener=open_url,
    )
    manifest = verify_nflverse_bronze(root, manifest_sha)
    target = root.joinpath(*manifest["partitions"][0]["relativePath"].split("/"))
    original_guard = bronze_acquisition.reject_reparse_chain

    def reject_declared_partition(path: Path, *, label: str) -> None:
        if Path(path) == target:
            raise NflBronzeError("test reparse boundary rejected")
        original_guard(path, label=label)

    monkeypatch.setattr(bronze_acquisition, "reject_reparse_chain", reject_declared_partition)
    with pytest.raises(RuntimeError, match="reparse"):
        verify_nflverse_bronze(root, manifest_sha)


def test_release_discovery_cache_fetches_shared_tag_once() -> None:
    calls: list[str] = []
    assets = []
    for index, family_id in enumerate(("ngs_passing", "ngs_receiving", "ngs_rushing"), start=1):
        name = f"{family_id}.parquet"
        assets.append({
            "id": index,
            "name": name,
            "size": index,
            "digest": None,
            "updated_at": "2026-08-28T01:03:04Z",
            "browser_download_url": _official_url("nextgen_stats", name),
        })

    def fetch(url: str):
        calls.append(url)
        return {"tag_name": "nextgen_stats", "published_at": "2026-08-28T01:02:03Z", "assets": assets}

    cache = {}
    for family_id in ("ngs_passing", "ngs_receiving", "ngs_rushing"):
        assert discover_release_asset(
            NFLVERSE_SOURCE_FAMILIES[family_id], 2025, json_fetcher=fetch,
            release_cache=cache,
            clock=lambda: datetime(2026, 8, 28, 2, 3, 4, tzinfo=timezone.utc),
        ) is not None
    assert len(calls) == 1


def test_same_name_corrected_asset_gets_new_path_and_preserves_history(tmp_path: Path) -> None:
    root = tmp_path / "external-nfl-bronze"
    source_one = _parquet_bytes(tmp_path, "snap-one.parquet", {
        "season": [2024], "week": [1], "player": ["00-1"],
    })
    source_two = _parquet_bytes(tmp_path, "snap-two.parquet", {
        "season": [2024], "week": [1], "player": ["00-2"],
    })
    state = {"id": 101, "content": source_one}
    url = _official_url("snap_counts", "snap_counts_2024.parquet")

    def fetch(_url: str):
        content = state["content"]
        return {
            "tag_name": "snap_counts",
            "published_at": "2026-08-28T01:02:03Z",
            "assets": [{
                "id": state["id"], "name": "snap_counts_2024.parquet",
                "size": len(content), "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                "updated_at": "2026-08-28T01:03:04Z", "browser_download_url": url,
            }],
        }

    def open_url(_request):
        return _Response(state["content"])

    first_sha = acquire_nflverse_bronze(
        root, [2024], family_ids=["snap_counts"], json_fetcher=fetch, opener=open_url,
        clock=lambda: datetime(2026, 8, 28, 2, 3, 4, tzinfo=timezone.utc),
    )
    first_manifest = verify_nflverse_bronze(root, first_sha)
    first_relative = first_manifest["partitions"][0]["relativePath"]
    first_path = root.joinpath(*first_relative.split("/"))
    assert first_path.read_bytes() == source_one

    state.update(id=202, content=source_two)
    second_sha = acquire_nflverse_bronze(
        root, [2024], family_ids=["snap_counts"], json_fetcher=fetch, opener=open_url,
        clock=lambda: datetime(2026, 8, 29, 2, 3, 4, tzinfo=timezone.utc),
    )
    second_manifest = verify_nflverse_bronze(root, second_sha)
    second_relative = second_manifest["partitions"][0]["relativePath"]

    assert second_sha != first_sha
    assert first_relative != second_relative
    assert "asset=101" in first_relative and "asset=202" in second_relative
    assert first_path.read_bytes() == source_one
    assert root.joinpath(*second_relative.split("/")).read_bytes() == source_two
    assert verify_nflverse_bronze(root, first_sha)["partitions"][0]["fileSha256"] == hashlib.sha256(source_one).hexdigest()
