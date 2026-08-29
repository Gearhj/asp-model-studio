"""Focused, provider-free acceptance tests for the nightly current-Statcast sync.

The existing component suites already prove schedule parsing, immutable Bronze
receipts, PA normalization, Gold date exclusivity, and warehouse registration.
These fixtures therefore exercise only the incremental orchestration contract:
planning, idempotence, correction history, atomic coverage advancement, locking,
and the absence of a model-fit path.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from server.sports_cockpit.interprocess_lock import LockBusy
from server.sports_current_statcast import incremental as INC
from server.sports_current_statcast import incremental_runtime as RUNTIME


BASELINE_DATES = ("2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _partition(
    day: str,
    *,
    revision: str = "v1",
    games: tuple[int, ...] = (1,),
    pitches: int = 8,
    accepted_pitches: int = 8,
    accepted_pas: int = 2,
    reject_reasons: dict[str, int] | None = None,
    status: str = "COMPLETE",
) -> dict[str, Any]:
    rejects = dict(reject_reasons or {})
    return {
        "date": day,
        "status": status,
        "sourceSha256": _sha(f"{day}:{revision}"),
        "games": list(games),
        "sourcePitches": pitches,
        "acceptedPitches": accepted_pitches,
        "acceptedPlateAppearances": accepted_pas,
        "rejectedPlateAppearances": sum(rejects.values()),
        "rejectReasons": rejects,
        "duplicateCount": 0,
        "unresolvedCount": 0,
    }


@dataclass
class _World:
    """Stateful fake for the high-level dependency boundary.

    The fake intentionally creates real immutable marker files for publication
    identities. That makes the correction/history assertions independent of an
    in-memory ``old == old`` comparison.
    """

    root: Path
    completed: dict[str, tuple[int, ...]] = field(default_factory=dict)
    provider: dict[str, dict[str, Any]] = field(default_factory=dict)
    bronze: dict[str, dict[str, Any]] = field(default_factory=dict)
    prior_through: str = "2026-08-27"
    silver_current: str = "silver-baseline"
    gold_current: str = "gold-baseline"
    registration_current: str = "registration-baseline"
    registration_history: list[str] = field(default_factory=list)
    fail_dates: set[str] = field(default_factory=set)
    calls: list[tuple[str, Any]] = field(default_factory=list)
    model_registry_identity: str = "frozen-model-registry"
    block_entered: threading.Event | None = None
    block_release: threading.Event | None = None

    def __post_init__(self) -> None:
        for offset, day in enumerate(BASELINE_DATES, start=1):
            games = (820000 + offset,)
            self.completed.setdefault(day, games)
            self.provider.setdefault(day, _partition(day, games=games))
            self.bronze.setdefault(day, copy.deepcopy(self.provider[day]))
        self._persist_identity(self.silver_current)
        self._persist_identity(self.gold_current)
        self._persist_identity(self.registration_current)

    def _persist_identity(self, identity: str) -> None:
        path = self.root / "immutable" / identity
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(identity, encoding="utf-8")

    def identity_is_verifiable(self, identity: str) -> bool:
        path = self.root / "immutable" / identity
        return path.is_file() and path.read_text(encoding="utf-8") == identity

    def discover_completed(self, config: INC.CurrentStatcastSyncConfig) -> dict[str, Any]:
        through = str(config.through)
        if through == "latest-completed":
            through = max(self.completed)
        eligible = {day: list(games) for day, games in self.completed.items() if day <= through}
        self.calls.append(("discover", through))
        return {
            "requestedThroughDate": through,
            "priorRegisteredThroughDate": self.prior_through,
            "latestMlbFinalDate": max(eligible) if eligible else None,
            "completedGamesByDate": eligible,
        }

    def sync_bronze(
        self,
        _config: INC.CurrentStatcastSyncConfig,
        probe: dict[str, Any],
        inspect_dates: list[str],
    ) -> dict[str, Any]:
        self.calls.append(("bronze", tuple(inspect_dates)))
        if self.block_entered is not None:
            self.block_entered.set()
            assert self.block_release is not None
            assert self.block_release.wait(timeout=10)

        added: list[str] = []
        unchanged: list[str] = []
        corrected: list[str] = []
        failed: list[str] = []
        for day in inspect_dates:
            if day in self.fail_dates:
                failed.append(day)
                continue
            candidate = self.provider.get(day)
            if candidate is None:
                candidate = _partition(
                    day,
                    games=tuple(probe["completedGamesByDate"].get(day, ())),
                    pitches=0,
                    accepted_pitches=0,
                    accepted_pas=0,
                    status="COMPLETE_EMPTY",
                )
                self.provider[day] = candidate
            prior = self.bronze.get(day)
            if prior is None:
                added.append(day)
                self.bronze[day] = copy.deepcopy(candidate)
            elif prior["sourceSha256"] != candidate["sourceSha256"]:
                corrected.append(day)
                self.bronze[day] = copy.deepcopy(candidate)
            else:
                unchanged.append(day)

        represented = sum(len(self.bronze[day]["games"]) for day in inspect_dates if day in self.bronze)
        expected = sum(len(probe["completedGamesByDate"].get(day, ())) for day in inspect_dates)
        selected = [self.bronze[day] for day in inspect_dates if day in self.bronze]
        reasons: Counter[str] = Counter()
        for item in selected:
            reasons.update(item["rejectReasons"])
        return {
            "status": "FAILED" if failed else "COMPLETE",
            "datesAdded": added,
            "datesUnchanged": unchanged,
            "datesCorrected": corrected,
            "failedDates": failed,
            "completeEmptyDates": [item["date"] for item in selected if item["status"] == "COMPLETE_EMPTY"],
            "expectedFinalGames": expected,
            "representedGames": represented,
            "missingGames": max(expected - represented, 0),
            "sourcePitches": sum(item["sourcePitches"] for item in selected),
            "acceptedPitches": sum(item["acceptedPitches"] for item in selected),
            "acceptedPlateAppearances": sum(item["acceptedPlateAppearances"] for item in selected),
            "rejectedPlateAppearances": sum(item["rejectedPlateAppearances"] for item in selected),
            "rejectReasons": dict(sorted(reasons.items())),
            "duplicateCount": sum(item["duplicateCount"] for item in selected),
            "unresolvedCount": sum(item["unresolvedCount"] for item in selected),
            # Existing immutable identities are required in NO_OP/FAILED reports,
            # when downstream publication callables must not be invoked.
            "currentSilverPublicationIdentity": self.silver_current,
            "currentGoldPublicationIdentity": self.gold_current,
            "currentWarehouseRegistrationIdentity": self.registration_current,
            "currentCoverage": {
                "latestDate": self.prior_through,
                "partitionCount": len(self.bronze),
                "completeEmptyPartitionCount": sum(
                    item["status"] == "COMPLETE_EMPTY" for item in self.bronze.values()
                ),
                "goldFeatureCount": 48,
            },
        }

    def sync_silver(
        self,
        _config: INC.CurrentStatcastSyncConfig,
        bronze_delta: dict[str, Any],
        _probe: dict[str, Any],
    ) -> dict[str, Any]:
        changed = bronze_delta["datesAdded"] + bronze_delta["datesCorrected"]
        self.calls.append(("silver", tuple(changed)))
        prior = self.silver_current
        identity = "silver-" + _sha(
            "|".join(f"{day}:{self.bronze[day]['sourceSha256']}" for day in sorted(self.bronze))
        )[:16]
        self.silver_current = identity
        self._persist_identity(identity)
        return {
            "status": "COMPLETE",
            "publicationIdentity": identity,
            "priorPublicationIdentity": prior,
            "changed": identity != prior,
        }

    def sync_gold(
        self,
        _config: INC.CurrentStatcastSyncConfig,
        silver_delta: dict[str, Any],
        affected_target_dates: list[str],
    ) -> dict[str, Any]:
        self.calls.append(("gold", tuple(affected_target_dates)))
        prior = self.gold_current
        identity = "gold-" + _sha(
            f"{silver_delta['publicationIdentity']}|{'|'.join(affected_target_dates)}"
        )[:16]
        self.gold_current = identity
        self._persist_identity(identity)
        return {
            "status": "COMPLETE",
            "publicationIdentity": identity,
            "priorPublicationIdentity": prior,
            "recomputedDates": list(affected_target_dates),
            "featureCount": 48,
            "modelsFitted": 0,
        }

    def sync_warehouse(
        self,
        _config: INC.CurrentStatcastSyncConfig,
        _silver_delta: dict[str, Any],
        gold_delta: dict[str, Any],
        _status: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(("warehouse", tuple(gold_delta["recomputedDates"])))
        prior = self.registration_current
        identity = "registration-" + _sha(
            f"{self.silver_current}|{self.gold_current}|{max(self.bronze)}"
        )[:16]
        if prior != identity:
            self.registration_history.append(prior)
        self.registration_current = identity
        self.prior_through = max(self.bronze)
        self._persist_identity(identity)
        return {
            "status": "COMPLETE",
            "registrationIdentity": identity,
            "priorRegistrationIdentity": prior,
            "historicalRegistrationIdentities": list(self.registration_history),
            "coverage": {
                "latestDate": self.prior_through,
                "partitionCount": len(self.bronze),
                "completeEmptyPartitionCount": sum(
                    item["status"] == "COMPLETE_EMPTY" for item in self.bronze.values()
                ),
                "goldFeatureCount": 48,
            },
        }


def _config(tmp_path: Path, *, through: str = "2026-08-27") -> INC.CurrentStatcastSyncConfig:
    staging = tmp_path / "staging"
    return INC.CurrentStatcastSyncConfig(
        through=through,
        correction_lookback=3,
        legacy_bronze_root=staging / "legacy-bronze",
        current_bronze_root=staging / "current-bronze",
        existing_silver_root=staging / "existing-silver",
        current_silver_root=staging / "current-silver",
        existing_gold_root=staging / "existing-gold",
        current_gold_root=staging / "current-gold",
        contextual_gold_root=staging / "current-context-gold",
        exchange_root=staging / "exchange",
        package_root=staging,
        database_path=tmp_path / "registry.db",
        report_root=tmp_path / "reports",
        lock_path=tmp_path / "nightly.lock",
        registered_by="nightly-test",
    )


def _dependencies(world: _World) -> INC.CurrentStatcastSyncDependencies:
    return INC.CurrentStatcastSyncDependencies(
        discover_completed=world.discover_completed,
        sync_bronze=world.sync_bronze,
        sync_silver=world.sync_silver,
        sync_gold=world.sync_gold,
        sync_warehouse=world.sync_warehouse,
        clock=lambda: datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc),
    )


def _add_completed_day(
    world: _World,
    day: str,
    *,
    game_pk: int = 830001,
    empty: bool = False,
) -> None:
    games = () if empty else (game_pk,)
    world.completed[day] = games
    world.provider[day] = _partition(
        day,
        games=games,
        pitches=0 if empty else 12,
        accepted_pitches=0 if empty else 11,
        accepted_pas=0 if empty else 3,
        reject_reasons={} if empty else {"UNKNOWN_TERMINAL_EVENT": 1},
        status="COMPLETE_EMPTY" if empty else "COMPLETE",
    )


def _run(world: _World, config: INC.CurrentStatcastSyncConfig) -> dict[str, Any]:
    return INC.sync_current_statcast(config, dependencies=_dependencies(world))


def test_noop_through_registered_cutoff_adds_nothing(tmp_path: Path) -> None:
    world = _World(tmp_path)
    report = _run(world, _config(tmp_path))

    assert report["status"] == "NO_OP"
    assert report["datesInspected"] == list(BASELINE_DATES)
    assert report["datesAdded"] == []
    assert report["datesCorrected"] == []
    assert report["duplicateCount"] == 0
    assert report["silverPublicationIdentity"] == "silver-baseline"
    assert report["goldPublicationIdentity"] == "gold-baseline"
    assert report["warehouseRegistrationIdentity"] == "registration-baseline"
    assert [name for name, _ in world.calls] == ["discover", "bronze"]


def test_pending_bronze_mismatch_remains_inspectable_after_lookback(tmp_path: Path) -> None:
    config = _config(tmp_path)
    probe = {
        "requestedThroughDate": "2026-08-27",
        "priorRegisteredThroughDate": "2026-08-27",
        "completedGamesByDate": {
            "2026-08-01": [810001],
            "2026-08-25": [810025],
            "2026-08-26": [810026],
            "2026-08-27": [810027],
        },
        "correctionEligibleDates": ["2026-08-25", "2026-08-26", "2026-08-27"],
        "pendingBronzeDates": ["2026-08-01"],
    }

    assert INC._inspection_dates(config, probe) == [
        "2026-08-01",
        "2026-08-25",
        "2026-08-26",
        "2026-08-27",
    ]


def test_explicit_older_through_is_rejected_before_provider_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, through="2026-08-26")
    downloads: list[str] = []
    monkeypatch.setattr(RUNTIME, "_recover_pending_commit", lambda _config: None)
    monkeypatch.setattr(
        RUNTIME,
        "_coverage_snapshot",
        lambda _config: {"latestDate": "2026-08-27"},
    )
    monkeypatch.setattr(
        RUNTIME,
        "http_download",
        lambda url, _path: downloads.append(url),
    )

    with pytest.raises(
        RUNTIME.CurrentStatcastSyncRuntimeError,
        match="cannot precede current registered coverage",
    ):
        RUNTIME._probe_schedule(config)

    assert downloads == []


def test_schedule_membership_comparison_reports_exact_differences() -> None:
    mismatches = RUNTIME._schedule_membership_mismatches(
        {
            "2026-08-25": [1, 2],
            "2026-08-26": [3, 5],
        },
        {
            "2026-08-25": {1, 2},
            "2026-08-26": {3, 4},
        },
        dates=["2026-08-25", "2026-08-26"],
    )

    assert mismatches == {
        "2026-08-26": {
            "missingFromProbe": [4],
            "unexpectedInProbe": [5],
        }
    }


def test_commit_journal_json_write_is_atomic(tmp_path: Path) -> None:
    journal = tmp_path / "reports" / "commit-journal.json"
    RUNTIME._write_json_atomic(journal, {"registration": "registration-next"})

    assert journal.read_text(encoding="utf-8") == '{"registration":"registration-next"}'
    assert list(journal.parent.glob(".commit-journal.json.tmp-*")) == []


def test_later_completed_date_adds_only_the_new_date(tmp_path: Path) -> None:
    world = _World(tmp_path)
    _add_completed_day(world, "2026-08-28")
    report = _run(world, _config(tmp_path, through="2026-08-28"))

    assert report["datesInspected"] == ["2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]
    assert report["datesAdded"] == ["2026-08-28"]
    assert report["datesCorrected"] == []
    assert set(world.bronze) - set(BASELINE_DATES) == {"2026-08-28"}
    assert report["resultingCoverage"]["latestDate"] == "2026-08-28"


def test_repeating_incremental_run_is_idempotent(tmp_path: Path) -> None:
    world = _World(tmp_path)
    _add_completed_day(world, "2026-08-28")
    config = _config(tmp_path, through="2026-08-28")
    first = _run(world, config)
    counts = (len(world.bronze), len(world.registration_history))
    identities = (
        first["silverPublicationIdentity"],
        first["goldPublicationIdentity"],
        first["warehouseRegistrationIdentity"],
    )

    second = _run(world, config)

    assert second["status"] == "NO_OP"
    assert second["datesAdded"] == second["datesCorrected"] == []
    assert (len(world.bronze), len(world.registration_history)) == counts
    assert (
        second["silverPublicationIdentity"],
        second["goldPublicationIdentity"],
        second["warehouseRegistrationIdentity"],
    ) == identities
    assert second["duplicateCount"] == 0


def test_multi_day_gap_catches_up_every_completed_date(tmp_path: Path) -> None:
    world = _World(tmp_path)
    for offset, day in enumerate(("2026-08-28", "2026-08-29", "2026-08-30")):
        _add_completed_day(world, day, game_pk=830010 + offset)

    report = _run(world, _config(tmp_path, through="2026-08-30"))

    assert report["datesInspected"] == [
        "2026-08-27", "2026-08-28", "2026-08-29", "2026-08-30",
    ]
    assert report["datesAdded"] == ["2026-08-28", "2026-08-29", "2026-08-30"]
    assert report["missingGames"] == 0
    assert report["resultingCoverage"]["latestDate"] == "2026-08-30"


def test_complete_empty_date_is_accounted_without_rows(tmp_path: Path) -> None:
    world = _World(tmp_path)
    _add_completed_day(world, "2026-08-28", empty=True)

    report = _run(world, _config(tmp_path, through="2026-08-28"))

    assert report["datesAdded"] == ["2026-08-28"]
    assert world.bronze["2026-08-28"]["status"] == "COMPLETE_EMPTY"
    assert world.bronze["2026-08-28"]["sourcePitches"] == 0
    assert world.bronze["2026-08-28"]["acceptedPlateAppearances"] == 0
    assert report["resultingCoverage"]["completeEmptyPartitionCount"] == 1
    assert report["resultingCoverage"]["latestDate"] == "2026-08-28"


def test_corrected_recent_partition_creates_a_new_immutable_version(tmp_path: Path) -> None:
    world = _World(tmp_path)
    original_source_sha = world.bronze["2026-08-26"]["sourceSha256"]
    original_silver = world.silver_current
    world.provider["2026-08-26"] = _partition(
        "2026-08-26", revision="corrected", games=world.completed["2026-08-26"]
    )

    report = _run(world, _config(tmp_path))

    assert report["datesCorrected"] == ["2026-08-26"]
    assert world.bronze["2026-08-26"]["sourceSha256"] != original_source_sha
    assert report["silverPublicationIdentity"] != original_silver
    assert world.identity_is_verifiable(original_silver)
    assert world.identity_is_verifiable(report["silverPublicationIdentity"])


def test_prior_registration_remains_historical_and_verifiable(tmp_path: Path) -> None:
    world = _World(tmp_path)
    prior_registration = world.registration_current
    world.provider["2026-08-27"] = _partition(
        "2026-08-27", revision="corrected", games=world.completed["2026-08-27"]
    )

    report = _run(world, _config(tmp_path))

    assert report["warehouseRegistrationIdentity"] != prior_registration
    assert prior_registration in world.registration_history
    assert prior_registration != world.registration_current
    assert world.identity_is_verifiable(prior_registration)
    assert world.identity_is_verifiable(world.registration_current)


def test_only_affected_gold_target_dates_are_recomputed(tmp_path: Path) -> None:
    world = _World(tmp_path)
    world.provider["2026-08-25"] = _partition(
        "2026-08-25", revision="corrected", games=world.completed["2026-08-25"]
    )

    _run(world, _config(tmp_path))

    gold_calls = [value for name, value in world.calls if name == "gold"]
    assert gold_calls == [("2026-08-25", "2026-08-26", "2026-08-27")]


def test_runtime_gold_builds_contextual_candidate_as_unpublished_follow_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, through="2026-08-28")
    config.current_gold_root.mkdir(parents=True)
    (config.current_gold_root / "current.json").write_text(
        json.dumps({"manifestSha256": "gold-prior"}), encoding="utf-8"
    )
    calls: list[tuple[str, dict[str, Any]]] = []

    def build_gold(**kwargs: Any) -> dict[str, Any]:
        calls.append(("gold", kwargs))
        return {
            "manifestSha256": "gold-next",
            "manifestPath": str(config.current_gold_root / "gold-next.json"),
            "featureCount": 48,
            "rowCount": 7,
            "modelsFitted": 0,
            "modelsScored": 0,
            "modelsCalibrated": 0,
            "modelPromoted": False,
        }

    def verify_gold(_root: Path, manifest_sha: str) -> dict[str, Any]:
        calls.append(("verify-gold", {"manifestSha256": manifest_sha}))
        return {"manifestSha256": manifest_sha, "verified": True}

    def build_context(**kwargs: Any) -> dict[str, Any]:
        calls.append(("context", kwargs))
        return {
            "manifestSha256": "context-next",
            "manifestPath": str(config.contextual_gold_root / "context-next.json"),
            "sourceGold": {"manifestSha256": "gold-next"},
            "recomputedTargetDates": ["2026-08-28"],
            "totalFeatureCount": 96,
            "rowCount": 7,
            "modelsFitted": 0,
            "modelsScored": 0,
            "modelsCalibrated": 0,
            "modelPromoted": False,
        }

    monkeypatch.setattr(RUNTIME, "build_current_gold", build_gold)
    monkeypatch.setattr(RUNTIME, "verify_current_gold", verify_gold)
    monkeypatch.setattr(RUNTIME, "build_contextual_gold", build_context)

    result = RUNTIME._sync_gold(
        config,
        {
            "publicationIdentity": "silver-next",
            "manifest": {"dateCoverage": {"latestDate": "2026-08-28"}},
        },
        ["2026-08-28"],
    )

    assert [name for name, _kwargs in calls] == ["gold", "verify-gold", "context"]
    context_kwargs = calls[-1][1]
    assert context_kwargs["current_gold_manifest_sha256"] == "gold-next"
    assert context_kwargs["recompute_dates"] == ["2026-08-28"]
    assert context_kwargs["prior_manifest_sha256"] is None
    assert context_kwargs["publish_current"] is False
    assert result["contextualPublication"]["publicationIdentity"] == "context-next"
    assert result["contextualPublication"]["modelsFitted"] == 0
    assert not (config.contextual_gold_root / "current.json").exists()


def test_warehouse_promotes_contextual_locator_only_after_registry_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, through="2026-08-28")
    events: list[tuple[str, Any]] = []
    fail_registration = {"value": True}

    class FakeDatabase:
        def __init__(self, _path: Path) -> None:
            pass

        def initialize(self) -> None:
            events.append(("database", None))

    class FakeRegistry:
        def __init__(self, _database: FakeDatabase) -> None:
            pass

        @staticmethod
        def _registration_id(_manifest_sha: str) -> str:
            return "registration-next"

        def register(self, _validated: Any, *, user_id: str) -> dict[str, Any]:
            events.append(("register", user_id))
            if fail_registration["value"]:
                raise RuntimeError("registry unavailable")
            return {
                "registration_id": "registration-next",
                "metadata_json": {
                    "supersedesRegistrationId": "registration-prior",
                    "historicalRegistrationIds": ["registration-prior"],
                },
            }

    monkeypatch.setattr(
        RUNTIME,
        "build_current_statcast_warehouse_manifest",
        lambda *_args, **_kwargs: SimpleNamespace(
            manifest={"manifestSha256": "warehouse-next"}
        ),
    )
    monkeypatch.setattr(RUNTIME, "_historical_pa_descriptors", lambda _config: [])
    monkeypatch.setattr(RUNTIME, "Database", FakeDatabase)
    monkeypatch.setattr(RUNTIME, "CurrentStatcastDatasetRegistry", FakeRegistry)
    monkeypatch.setattr(
        RUNTIME,
        "_atomic_locator",
        lambda root, dataset_id, new_sha, _path: events.append(
            ("locator", (Path(root), dataset_id, new_sha))
        ),
    )
    silver = {
        "priorPublicationIdentity": "silver-prior",
        "publicationIdentity": "silver-next",
        "publicationPath": str(config.current_silver_root / "silver-next.json"),
        "manifest": {
            "dateCoverage": {"earliestDate": "2023-03-30", "latestDate": "2026-08-28"},
            "counts": {},
            "partitions": [],
        },
        "bronze": {},
    }
    gold = {
        "priorPublicationIdentity": "gold-prior",
        "publicationIdentity": "gold-next",
        "publicationPath": str(config.current_gold_root / "gold-next.json"),
        "rowCount": 7,
        "featureCount": 48,
        "contextualPublication": {
            "status": "COMPLETE",
            "priorPublicationIdentity": "context-prior",
            "publicationIdentity": "context-next",
            "publicationPath": str(config.contextual_gold_root / "context-next.json"),
            "modelsFitted": 0,
            "modelsScored": 0,
            "modelsCalibrated": 0,
            "modelPromoted": False,
            "verification": {"sourceGoldManifestSha256": "gold-next"},
        },
    }

    with pytest.raises(RuntimeError, match="registry unavailable"):
        RUNTIME._sync_warehouse(config, silver, gold, {})

    assert [event for event in events if event[0] == "locator"] == []
    journal = json.loads(
        (config.report_root / "commit-journal.json").read_text(encoding="utf-8")
    )
    assert journal["contextualGold"] == ["context-prior", "context-next"]

    fail_registration["value"] = False
    result = RUNTIME._sync_warehouse(config, silver, gold, {})

    locators = [value for name, value in events if name == "locator"]
    assert locators == [
        (config.current_silver_root, RUNTIME.CURRENT_STATCAST_DATASET_ID, "silver-next"),
        (config.current_gold_root, "gold-table:gold_mlb_current_pa_v1", "gold-next"),
        (config.contextual_gold_root, RUNTIME.CONTEXT_GOLD_DATASET_ID, "context-next"),
    ]
    assert result["status"] == "COMPLETE"
    assert not (config.report_root / "commit-journal.json").exists()


def test_warehouse_coverage_advances_only_after_verified_publications(tmp_path: Path) -> None:
    world = _World(tmp_path)
    _add_completed_day(world, "2026-08-28")

    report = _run(world, _config(tmp_path, through="2026-08-28"))

    assert [name for name, _ in world.calls] == ["discover", "bronze", "silver", "gold", "warehouse"]
    assert report["status"] == "COMPLETE"
    assert report["resultingCoverage"]["latestDate"] == "2026-08-28"
    assert report["silverPublicationIdentity"] == world.silver_current
    assert report["goldPublicationIdentity"] == world.gold_current
    assert report["warehouseRegistrationIdentity"] == world.registration_current


def test_acquisition_failure_does_not_advance_coverage(tmp_path: Path) -> None:
    world = _World(tmp_path)
    _add_completed_day(world, "2026-08-28")
    world.fail_dates.add("2026-08-28")
    before = (world.prior_through, world.silver_current, world.gold_current, world.registration_current)

    report = _run(world, _config(tmp_path, through="2026-08-28"))

    assert report["status"] == "FAILED"
    assert report["missingGames"] == 1
    assert (world.prior_through, world.silver_current, world.gold_current, world.registration_current) == before
    assert [name for name, _ in world.calls] == ["discover", "bronze"]


def test_concurrent_sync_attempts_do_not_corrupt_registration(tmp_path: Path) -> None:
    world = _World(tmp_path)
    _add_completed_day(world, "2026-08-28")
    world.block_entered = threading.Event()
    world.block_release = threading.Event()
    config = _config(tmp_path, through="2026-08-28")
    holder_result: list[dict[str, Any]] = []

    holder = threading.Thread(target=lambda: holder_result.append(_run(world, config)))
    holder.start()
    assert world.block_entered.wait(timeout=10), "holder never entered the locked sync"
    try:
        try:
            contender = _run(world, config)
        except LockBusy:
            contender_status = "BUSY"
        else:
            contender_status = contender["status"]
        assert contender_status == "BUSY"
    finally:
        world.block_release.set()
        holder.join(timeout=10)

    assert not holder.is_alive()
    assert holder_result[0]["status"] == "COMPLETE"
    assert len([name for name, _ in world.calls if name == "warehouse"]) == 1
    assert len(world.registration_history) == 1
    assert world.identity_is_verifiable(world.registration_current)


def test_sync_has_no_model_fit_or_model_registry_mutation(tmp_path: Path) -> None:
    world = _World(tmp_path)
    _add_completed_day(world, "2026-08-28")
    before_model_registry = world.model_registry_identity

    report = _run(world, _config(tmp_path, through="2026-08-28"))

    assert report["modelFits"] == 0
    assert world.model_registry_identity == before_model_registry
    source = inspect.getsource(INC)
    assert "sports_gold.models" not in source
    assert ".fit(" not in source
    assert "run_fixed_experiment_suite" not in source
