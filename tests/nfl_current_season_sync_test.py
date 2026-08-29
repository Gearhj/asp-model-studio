"""Provider-free tests for the bounded NFL current-season orchestrator."""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

from server.sports_cockpit.interprocess_lock import LockBusy, interprocess_lock
from server.sports_nfl import current_season_sync as SYNC
from server.sports_nfl.pipeline import NflFoundationConfig


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _asset(family: str, revision: int, *, season: int | None = 2026) -> dict[str, Any]:
    return {
        "familyId": family,
        "season": season,
        "status": "COMPLETE",
        "assetId": revision,
    }


@dataclass
class _World:
    source_identity: str = field(default_factory=lambda: _sha("source-current"))
    source_assets: list[dict[str, Any]] = field(
        default_factory=lambda: [_asset("schedules", 1, season=None)]
    )
    authority: dict[str, Any] = field(default_factory=dict)
    build_calls: list[NflFoundationConfig] = field(default_factory=list)
    immutable: set[str] = field(default_factory=set)
    fail_build: bool = False
    model_fits: int = 0

    def __post_init__(self) -> None:
        if not self.authority:
            self.authority = self._authority("baseline", self.source_identity, self.source_assets)
        self.immutable.update(
            {
                self.authority["bronzeManifestSha256"],
                self.authority["foundationManifestSha256"],
                self.authority["registrationIdentity"],
            }
        )

    @staticmethod
    def _authority(
        revision: str,
        source_identity: str,
        assets: list[dict[str, Any]],
        *,
        completed: int = 0,
    ) -> dict[str, Any]:
        foundation = _sha(f"foundation:{revision}:{source_identity}")
        return {
            "status": "VERIFIED",
            "sourceSnapshotIdentity": source_identity,
            "sourceAssets": copy.deepcopy(assets),
            "bronzeManifestSha256": _sha(f"bronze:{revision}:{source_identity}"),
            "foundationManifestSha256": foundation,
            "datasetVersionId": f"asp.nfl.gold-data-foundation.v1:sha256:{foundation}",
            "registrationIdentity": f"registration-{revision}",
            "currentSeasonScheduledGames": 272,
            "currentSeasonCompletedGames": completed,
            "maximumDate": "2027-01-10",
            "modelsFitted": 0,
        }

    def inspect(self, _config: SYNC.NflCurrentSeasonSyncConfig) -> dict[str, Any]:
        return copy.deepcopy(self.authority)

    def probe(self, _config: SYNC.NflCurrentSeasonSyncConfig) -> dict[str, Any]:
        return {
            "sourceSnapshotIdentity": self.source_identity,
            "scope": [{"familyId": item["familyId"]} for item in self.source_assets],
            "assets": copy.deepcopy(self.source_assets),
        }

    def build(self, config: NflFoundationConfig) -> dict[str, Any]:
        self.build_calls.append(config)
        if self.fail_build:
            raise RuntimeError("foundation unavailable")
        if self.model_fits:
            return {
                "status": "COMPLETE",
                "modelsFitted": self.model_fits,
                "modelsScored": 0,
                "modelsPromoted": 0,
            }
        prior = copy.deepcopy(self.authority)
        revision = f"v{len(self.build_calls)}"
        completed = 3 if any(item.get("season") == 2026 for item in self.source_assets) else 0
        self.authority = self._authority(
            revision,
            self.source_identity,
            self.source_assets,
            completed=completed,
        )
        self.immutable.update(
            {
                prior["bronzeManifestSha256"],
                prior["foundationManifestSha256"],
                prior["registrationIdentity"],
                self.authority["bronzeManifestSha256"],
                self.authority["foundationManifestSha256"],
                self.authority["registrationIdentity"],
            }
        )
        return {
            "status": "COMPLETE",
            "modelsFitted": 0,
            "modelsScored": 0,
            "modelsPromoted": 0,
        }

    def verify_prior(
        self,
        _config: SYNC.NflCurrentSeasonSyncConfig,
        prior: Mapping[str, Any],
    ) -> bool:
        return all(
            str(prior[key]) in self.immutable
            for key in (
                "bronzeManifestSha256",
                "foundationManifestSha256",
                "registrationIdentity",
            )
        )


def _config(
    root: Path,
    *,
    mode: str = SYNC.NIGHTLY,
    through: str = SYNC.LATEST_COMPLETED,
) -> SYNC.NflCurrentSeasonSyncConfig:
    foundation = NflFoundationConfig(
        staging_root=root / "external-nfl",
        database_path=root / "runtime" / "foundation.db",
        seasons=(2025, 2026),
        include_optional=True,
    )
    return SYNC.NflCurrentSeasonSyncConfig(
        foundation=foundation,
        through=through,
        mode=mode,
        report_root=root / "runtime" / "reports",
        lock_path=root / "runtime" / "locks" / "nfl-sync.lock",
    )


def _dependencies(world: _World) -> SYNC.NflCurrentSeasonSyncDependencies:
    return SYNC.NflCurrentSeasonSyncDependencies(
        inspect_authority=world.inspect,
        probe_sources=world.probe,
        build_foundation=world.build,
        verify_prior=world.verify_prior,
        clock=lambda: datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
    )


def test_verified_unchanged_source_and_foundation_are_noop(tmp_path: Path) -> None:
    world = _World()
    config = _config(tmp_path)

    report = SYNC.sync_nfl_current_season(config, dependencies=_dependencies(world))

    assert report["status"] == "NO_OP"
    assert report["sourceChanged"] is False
    assert report["warehouseAdvanced"] is False
    assert report["modelsFitted"] == report["modelsScored"] == report["modelsPromoted"] == 0
    assert world.build_calls == []
    assert json.loads((config.report_root / "latest-attempt.json").read_text())["status"] == "NO_OP"
    assert json.loads((config.report_root / "latest-success.json").read_text())["status"] == "NO_OP"


def test_optional_probe_failure_uses_the_governed_bronze_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(SYNC, "_allowed_family_ids", lambda _config: ("depth_charts",))

    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise SYNC.NflBronzeError("optional release unavailable")

    monkeypatch.setattr(SYNC, "discover_release_asset", unavailable)

    source = SYNC._default_probe_sources(config)

    assert source["assets"] == [{
        "familyId": "depth_charts",
        "season": 2026,
        "releaseTag": "depth_charts",
        "contractVersion": "NFLVERSE_SOURCE_FAMILY_V1",
        "status": "SOURCE_DISCOVERY_FAILURE",
    }]


def test_repeated_optional_download_gap_is_an_idempotent_noop(tmp_path: Path) -> None:
    prior_assets = [
        _asset("schedules", 1, season=None),
        {**_asset("depth_charts", 1), "status": "DOWNLOAD_FAILURE"},
    ]
    world = _World(
        source_identity=_sha("published-optional-gap"),
        source_assets=prior_assets,
    )
    world.source_identity = _sha("probe-sees-optional-asset")
    world.source_assets = [
        _asset("schedules", 1, season=None),
        _asset("depth_charts", 2),
    ]
    config = _config(tmp_path)

    def unchanged_partial_build(foundation: NflFoundationConfig) -> dict[str, Any]:
        world.build_calls.append(foundation)
        return {
            "status": "COMPLETE",
            "modelsFitted": 0,
            "modelsScored": 0,
            "modelsPromoted": 0,
        }

    dependencies = SYNC.NflCurrentSeasonSyncDependencies(
        inspect_authority=world.inspect,
        probe_sources=world.probe,
        build_foundation=unchanged_partial_build,
        verify_prior=world.verify_prior,
        clock=lambda: datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
    )

    report = SYNC.sync_nfl_current_season(config, dependencies=dependencies)

    assert report["status"] == "NO_OP"
    assert report["warehouseAdvanced"] is False
    assert report["sourceChanged"] is False
    assert report["optionalSourceGapAccepted"] is True
    assert report["optionalProbeIncomplete"] is True
    assert len(world.build_calls) == 1


def test_thursday_correction_creates_new_version_and_preserves_prior(tmp_path: Path) -> None:
    world = _World(
        source_assets=[_asset("play_by_play", 1)],
    )
    prior = copy.deepcopy(world.authority)
    world.source_identity = _sha("source-corrected")
    world.source_assets = [_asset("play_by_play", 2)]
    config = _config(tmp_path, mode=SYNC.THURSDAY_CORRECTION)

    report = SYNC.sync_nfl_current_season(config, dependencies=_dependencies(world))

    assert report["status"] == "COMPLETE"
    assert report["changedFamilies"] == ["play_by_play"]
    assert report["priorAuthority"]["foundationManifestSha256"] == prior["foundationManifestSha256"]
    assert report["resultAuthority"]["foundationManifestSha256"] != prior["foundationManifestSha256"]
    assert report["historicalAuthorityPreserved"] is True
    assert world.verify_prior(config, prior)
    assert len(world.build_calls) == 1


def test_catch_up_advances_once_then_repeats_as_noop(tmp_path: Path) -> None:
    world = _World()
    world.source_identity = _sha("three-completed-games")
    world.source_assets = [
        _asset("play_by_play", 2),
        _asset("weekly_player_stats", 2),
        _asset("weekly_team_stats", 2),
    ]
    config = _config(tmp_path, mode=SYNC.CATCH_UP, through="2026-09-20")

    first = SYNC.sync_nfl_current_season(config, dependencies=_dependencies(world))
    second = SYNC.sync_nfl_current_season(config, dependencies=_dependencies(world))

    assert first["status"] == "COMPLETE"
    assert first["resultAuthority"]["currentSeasonCompletedGames"] == 3
    assert first["changedFamilies"] == [
        "play_by_play",
        "schedules",
        "weekly_player_stats",
        "weekly_team_stats",
    ]
    assert second["status"] == "NO_OP"
    assert len(world.build_calls) == 1


def test_build_failure_does_not_advance_warehouse_or_latest_success(tmp_path: Path) -> None:
    world = _World()
    prior = copy.deepcopy(world.authority)
    world.source_identity = _sha("unavailable-correction")
    world.source_assets = [_asset("schedules", 2, season=None)]
    world.fail_build = True
    config = _config(tmp_path, mode=SYNC.SCHEDULE_REFRESH)
    config.report_root.mkdir(parents=True)
    prior_success = b'{"status":"NO_OP","sentinel":"preserve"}'
    (config.report_root / "latest-success.json").write_bytes(prior_success)

    report = SYNC.sync_nfl_current_season(config, dependencies=_dependencies(world))

    assert report["status"] == "FAILED"
    assert report["failedStage"] == "FOUNDATION_BUILD"
    assert report["warehouseAdvanced"] is False
    assert world.authority == prior
    assert (config.report_root / "latest-success.json").read_bytes() == prior_success
    assert json.loads((config.report_root / "latest-attempt.json").read_text())["status"] == "FAILED"


def test_nonzero_model_fit_is_rejected_and_reported(tmp_path: Path) -> None:
    world = _World()
    world.source_identity = _sha("changed-source")
    world.source_assets = [_asset("schedules", 2, season=None)]
    world.model_fits = 1
    config = _config(tmp_path)

    report = SYNC.sync_nfl_current_season(config, dependencies=_dependencies(world))

    assert report["status"] == "FAILED"
    assert report["modelsFitted"] == 1
    assert report["warehouseAdvanced"] is False
    assert "model execution" in report["error"]


def test_nonblocking_lock_excludes_overlapping_attempt(tmp_path: Path) -> None:
    config = _config(tmp_path)
    world = _World()
    ready = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with interprocess_lock(config.lock_path, blocking=False):
            ready.set()
            assert release.wait(timeout=10)

    holder = threading.Thread(target=hold)
    holder.start()
    assert ready.wait(timeout=10)
    try:
        with pytest.raises(LockBusy):
            SYNC.sync_nfl_current_season(config, dependencies=_dependencies(world))
    finally:
        release.set()
        holder.join(timeout=10)

    assert not holder.is_alive()
    assert world.build_calls == []
    assert not (config.report_root / "latest-attempt.json").exists()


def test_sync_module_has_no_model_execution_path() -> None:
    source = inspect.getsource(SYNC)

    assert ".fit(" not in source
    assert "sports_modeling" not in source
    assert "run_fixed_experiment_suite" not in source
    assert set(SYNC.SYNC_MODES) == {
        "nightly",
        "thursday-correction",
        "schedule-refresh",
        "catch-up",
    }
