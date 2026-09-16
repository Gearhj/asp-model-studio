"""Synthetic checks for refreshed handoff scope; no models or provider access."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_nfl_m1 import current_shadow as C


def _target(event_id, day, kickoff):
    return {"canonical_game_id": event_id, "canonical_home_team_id": event_id + "_HOME",
            "canonical_away_team_id": event_id + "_AWAY", "game_date": day,
            "scheduled_start_utc": datetime.fromisoformat(kickoff.replace("Z", "+00:00"))}


def _forecast(target):
    event_id = target["canonical_game_id"]
    return {
        "forecastId": event_id + ":current:v9", "eventId": event_id,
        "sourceEventId": "nflverse:" + event_id,
        "homeTeam": {"teamId": target["canonical_home_team_id"]},
        "awayTeam": {"teamId": target["canonical_away_team_id"]},
        "scheduledStartUtc": target["scheduled_start_utc"].isoformat().replace("+00:00", "Z"),
        "availableAsOfUtc": "2026-09-13T16:00:00Z", "forecastCutoffUtc": "2026-09-13T15:59:00Z",
        "sourceCutoffUtc": "2026-09-13T15:00:00Z", "snapshotType": "CURRENT", "snapshotVersion": 9,
        "engine": {"engineId": "NFL_M1_XGBOOST", "engineVersion": "FROZEN",
                   "modelManifestSha256": C.MODEL_MANIFEST_SHA256,
                   "modelBinarySha256": C.MODEL_BINARY_SHA256, "trainingCutoff": C.TRAINING_CUTOFF},
        "expectedHomeScore": 22.25, "expectedAwayScore": 21.75,
        "homeWinProbability": 0.51, "awayWinProbability": 0.47, "tieProbability": 0.02,
        "readiness": {"isReady": True},
    }


@pytest.fixture
def world(tmp_path, monkeypatch):
    targets = [
        _target("STARTED", "2026-09-13", "2026-09-13T17:00:00Z"),
        _target("UPCOMING", "2026-09-13", "2026-09-13T20:25:00Z"),
        _target("SUNDAY_NIGHT", "2026-09-13", "2026-09-14T00:20:00Z"),
        _target("WINDOW_INSIDE", "2026-09-20", "2026-09-20T17:00:00Z"),
        _target("WINDOW_OUTSIDE", "2026-09-20", "2026-09-20T20:25:00Z"),
    ]
    runtime = SimpleNamespace(schedule_as_of_utc="2026-09-13T19:30:00Z",
        paths=SimpleNamespace(foundation_manifest_sha256="f" * 64, dataset_version_id="verified-foundation"))
    publication = tmp_path / "publication"
    publication.mkdir()
    (publication / "prospective-index.json").write_text(json.dumps({"reloadFixtureSha256": "a" * 64}))
    published = {}
    originals = {}
    for day in ("2026-09-13", "2026-09-20"):
        bundle = {"slateDate": day, "generatedAtUtc": "2026-09-13T16:00:00Z",
                  "forecasts": [_forecast(t) for t in targets if t["game_date"] == day]}
        raw = canonical_json_bytes(bundle)
        digest = hashlib.sha256(raw).hexdigest()
        directory = tmp_path / "exchange" / digest
        directory.mkdir(parents=True)
        path = directory / "bundle.json"
        path.write_bytes(raw)
        (directory / "consumer-import-fixture.json").write_bytes(b"{}")
        (directory / "VALIDATION.md").write_bytes(b"synthetic verified fixture")
        published[day] = SimpleNamespace(record=bundle, bundle_path=path, bundle_sha256=digest)
        originals[path] = raw
    monkeypatch.setattr(C, "verify_frozen_m1", lambda **kwargs: object())
    monkeypatch.setattr(C, "load_foundation_runtime", lambda root: runtime)
    monkeypatch.setattr(C, "verify_activation_reload_fixture", lambda *args: None)
    monkeypatch.setattr(C, "_load_targets", lambda source, as_of:
                        ([deepcopy(t) for t in targets if t["scheduled_start_utc"] > as_of], None, {}))
    monkeypatch.setattr(C, "_bundle_for_slate", lambda root, day:
                        ({"currentBundleListSha256": "b" * 64}, published[day.isoformat()]))
    plan = [{"eventId": t["canonical_game_id"],
             "scheduledStartUtc": t["scheduled_start_utc"].isoformat().replace("+00:00", "Z"),
             "action": "REUSE_UNCHANGED_FORECAST"} for t in targets
            if t["canonical_game_id"] in {"UPCOMING", "SUNDAY_NIGHT", "WINDOW_INSIDE"}]
    refresh = {"status": "ACTIVE", "selectionMode": "ROLLING_WINDOW", "rollingWindowDays": 7,
               "selectedSlateDates": ["2026-09-13", "2026-09-20"], "eventPlan": plan,
               "forecastCutoffUtc": "2026-09-13T20:00:00Z", "completedAtUtc": "2026-09-13T20:01:00Z",
               "sourceFoundationManifestSha256": runtime.paths.foundation_manifest_sha256,
               "sourceEvidenceAsOfUtc": runtime.schedule_as_of_utc, "forecastsCreated": 0,
               "unchangedEvidenceForecastsReused": 3, "sourceFoundationChangedSincePreviousSnapshot": False}
    return SimpleNamespace(root=tmp_path, runtime=runtime, targets=targets, publication=publication,
                           published=published, originals=originals, refresh=refresh)


def _build(w, day, **kwargs):
    return C.build_current_slate_handoff(date.fromisoformat(day), exchange_root=w.root / "exchange",
        foundation_root=w.root / "foundation", publication_root=w.publication,
        refresh_evidence=kwargs.pop("refresh_evidence", w.refresh), **kwargs)


def _save(w, record):
    raw = canonical_json_bytes(record)
    path = w.root / "handoffs" / hashlib.sha256(raw).hexdigest() / "handoff.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def test_mixed_started_and_upcoming_slate_preserves_complete_source(world):
    record = _build(world, "2026-09-13")
    assert record["forecastCount"] == record["eventCount"] == 2
    assert record["importAllowed"] is True
    assert {f["eventId"] for f in record["forecasts"]} == {"UPCOMING", "SUNDAY_NIGHT"}
    scope = record["selectionScope"]
    assert [x["eventId"] for x in scope["outsideSelectedSourceEvents"]] == ["STARTED"]
    assert scope["selectedSourceForecastCount"] == 2
    assert scope["outsideSelectedSourceForecastCount"] == 1
    assert record["source"]["sourceBundleForecastCount"] == 3
    assert C.verify_current_slate_handoff(_save(world, record)) == record
    assert all(path.read_bytes() == raw for path, raw in world.originals.items())


def test_future_slate_selects_only_within_declared_rolling_boundary(world):
    record = _build(world, "2026-09-20")
    assert [f["eventId"] for f in record["forecasts"]] == ["WINDOW_INSIDE"]
    assert [x["eventId"] for x in record["selectionScope"]["outsideSelectedSourceEvents"]] == ["WINDOW_OUTSIDE"]
    assert C.verify_current_slate_handoff(_save(world, record)) == record


@pytest.mark.parametrize("case", ["unknown_event", "wrong_kickoff", "past_kickoff", "outside_window", "omitted_member", "wrong_foundation", "wrong_expected_team"])
def test_injected_selection_identity_or_boundary_fails(world, case):
    refresh = deepcopy(world.refresh)
    if case == "unknown_event":
        refresh["eventPlan"][0]["eventId"] = "INJECTED"
    elif case == "wrong_kickoff":
        refresh["eventPlan"][0]["scheduledStartUtc"] = "2026-09-13T21:00:00Z"
    elif case == "past_kickoff":
        refresh["eventPlan"].append({"eventId": "STARTED", "scheduledStartUtc": "2026-09-13T17:00:00Z"})
    elif case == "outside_window":
        refresh["eventPlan"].append({"eventId": "WINDOW_OUTSIDE", "scheduledStartUtc": "2026-09-20T20:25:00Z"})
    elif case == "omitted_member":
        refresh["eventPlan"] = refresh["eventPlan"][1:]
    elif case == "wrong_foundation":
        refresh["sourceFoundationManifestSha256"] = "0" * 64
    else:
        with pytest.raises(C.NflCurrentShadowError, match="expected events differ"):
            _build(world, "2026-09-13", expected_events=[{"eventId": "UPCOMING", "homeTeamId": "WRONG",
                   "awayTeamId": "UPCOMING_AWAY", "scheduledStartUtc": "2026-09-13T20:25:00Z"}])
        return
    with pytest.raises(C.NflCurrentShadowError):
        _build(world, "2026-09-13", refresh_evidence=refresh)


def test_summary_numerical_change_and_outside_accounting_are_rejected(world):
    original = _build(world, "2026-09-13")
    changed = deepcopy(original)
    changed["forecasts"][0]["expectedHomeScore"] += 1
    with pytest.raises(C.NflCurrentShadowError, match="selected forecast differs"):
        C.verify_current_slate_handoff(_save(world, changed))
    changed = deepcopy(original)
    changed["selectionScope"]["outsideSelectedSourceEvents"] = []
    with pytest.raises(C.NflCurrentShadowError, match="outside-selection"):
        C.verify_current_slate_handoff(_save(world, changed))


def test_nonrefresh_build_and_historical_v2_verification_remain_supported(world):
    world.runtime.schedule_as_of_utc = "2026-09-13T15:00:00Z"
    record = _build(world, "2026-09-13", refresh_evidence=None)
    assert record["schemaVersion"] == "ASP_NFL_M1_CURRENT_SLATE_HANDOFF_V2"
    assert record["eventCount"] == record["forecastCount"] == 3
    assert "selectionScope" not in record
    assert C.verify_current_slate_handoff(_save(world, record)) == record
