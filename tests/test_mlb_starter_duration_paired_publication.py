"""Focused new publication gates; no model fits, provider calls or AISP access."""
from datetime import datetime, timedelta, timezone

import pytest

from server.sports_current_statcast.mlb_starter_duration_paired_publication import require_deadline, participant_identity


def test_deadline_closes_both_arms_before_start_and_identity_keeps_order():
    start = datetime(2030, 4, 1, 23, tzinfo=timezone.utc)
    deadline = start-timedelta(minutes=5)
    game = {"scheduledStartUtc": start.isoformat(), "deadlineUtc": deadline.isoformat()}
    require_deadline(game, deadline-timedelta(microseconds=1))
    with pytest.raises(ValueError, match="NO_BACKFILL"):
        require_deadline(game, deadline)
    with pytest.raises(ValueError, match="DOES_NOT_MATCH"):
        require_deadline({**game, "deadlineUtc": start.isoformat()}, deadline-timedelta(minutes=1))
    snapshot = {"sides": [{"side": "HOME", "team": {"uuid": "team"}, "starter": {"mlbamId": "pitcher"},
        "lineup": [{"mlbam": "a"}, {"mlbam": "b"}]}]}
    first = participant_identity(snapshot)
    snapshot["sides"][0]["lineup"].reverse()
    assert participant_identity(snapshot) != first


def test_synthetic_both_arm_artifacts_publish_and_reuse_without_inference(tmp_path, monkeypatch):
    """Packaging fixture only: no fitted model, real source or game forecast."""
    from contextlib import nullcontext
    import json
    from types import SimpleNamespace

    import numpy as np

    from server.sports_current_statcast import mlb_starter_duration_paired_publication as pub
    from server.sports_current_statcast import mlb_starter_duration_paired_simulation as sim
    from scripts import inventory_mlb_current_slate as inventory_module
    from scripts.run_mlb_starter_duration_paired import published_pairs

    monkeypatch.setattr(pub, "ROOT", tmp_path)
    monkeypatch.setattr(pub, "production_busy", lambda: False)
    monkeypatch.setattr(pub, "single_owner", lambda path: nullcontext(True))
    current_time = datetime(2030, 4, 1, 20, tzinfo=timezone.utc)
    monkeypatch.setattr(pub, "now", lambda: current_time)
    start = current_time+timedelta(hours=3)
    game = {"gameId": "SYNTHETIC_PACKAGE_ONLY", "sourceGameId": "SYNTHETIC",
        "scheduledStartUtc": start.isoformat(), "deadlineUtc": (start-timedelta(minutes=5)).isoformat(),
        "teams": {"HOME": {"uuid": "H"}, "AWAY": {"uuid": "A"}}}
    snapshot = {"capturedAt": (current_time-timedelta(minutes=5)).isoformat(),
        "game": {"game_id": game["gameId"], "starts_at": game["scheduledStartUtc"]},
        "sides": [{"side": side, "team": {"uuid": side}, "starter": {"mlbamId": side+"P"},
                   "lineup": [{"mlbam": side+"B"}]} for side in ("HOME", "AWAY")]}
    root = tmp_path/"SYNTHETIC_NOT_FORECAST"
    declaration = {"games": [game], "nativeWorkers": 1, "masterSeed": 123,
        "mechanicsDrawsPerArm": 2, "simulationsPerArm": 4, "maxTickWallSeconds": 10,
        "syntheticFixtureOnly": True}
    declaration_ref = pub.save("declaration.json", declaration, root)
    feature_ref = pub.save("synthetic-feature.json", {"composition": {}}, root)
    source = tmp_path/"synthetic-producer"
    source.mkdir()
    (source/"pregame-evidence.json").write_text(json.dumps(snapshot), encoding="utf-8")
    base = {"homeRuns": [2]*4, "awayRuns": [1]*4, "innings": [9]*4, "paCounts": [70]*4}
    (source/"execution-inputs.json").write_text(json.dumps({"featureSnapshot": feature_ref, "population": base}), encoding="utf-8")
    calls = []

    def fake_simulation(**kwargs):
        calls.append(kwargs["n_sims"])
        arm = {name: np.repeat(values[0], kwargs["n_sims"]) for name, values in base.items()}
        return {"gameId": game["gameId"], "reference": arm, "challenger": {**arm, "homeRuns": arm["homeRuns"]+1},
                "syntheticFixtureOnly": True}

    monkeypatch.setattr(sim, "simulate_paired_game", fake_simulation)
    def fake_load_duration_model(*, before_inference=None):
        if before_inference:
            before_inference()
        return object(), {"syntheticFixtureOnly": True}
    monkeypatch.setattr(pub, "load_duration_model", fake_load_duration_model)
    monkeypatch.setattr(pub, "CurrentV18Engine", lambda: SimpleNamespace(transition=object(), model_identity={"syntheticFixtureOnly": True}))
    monkeypatch.setattr(pub, "build_provider", lambda *args: (object(), {"syntheticFixtureOnly": True}))
    published = pub.publish_pair(game, snapshot,
        (source, {"sourceCutoff": snapshot["capturedAt"], "forecastCreatedAt": snapshot["capturedAt"]}, {"syntheticFixtureOnly": True}),
        {"status": "SUPPORTED", "home": {}, "away": {}, "syntheticFixtureOnly": True}, declaration_ref, root=root)
    pair = pub.read(published["pair"])
    population = pub.read(pair["population"])
    assert calls == [2, 2, 4]
    assert len(population["reference"]["homeRuns"]) == len(population["challenger"]["homeRuns"]) == 4
    assert population["syntheticFixtureOnly"] is True
    assert published_pairs(root)[0][0]["commonPairId"] == pair["commonPairId"]
    assert pub.utc(pair["frozenAt"]) < pub.utc(game["deadlineUtc"])
    capture_file = tmp_path/"synthetic-capture.json"
    capture_file.write_text(json.dumps({"snapshots": [snapshot], "capturedAt": snapshot["capturedAt"]}), encoding="utf-8")
    monkeypatch.setattr(inventory_module, "capture_current_slate", lambda **kwargs: (
        {"games": [{"game": snapshot["game"]}]}, {"snapshotsPath": str(capture_file)}))
    monkeypatch.setattr(pub, "find_producer_objects", lambda declaration: {})
    reused = pub.tick(declaration_ref, root=root)
    assert reused["pairCount"] == 1
    assert reused["games"][0]["status"] == "EXACT_PAIR_REUSED"
    assert reused["games"][0]["pair"] == published["pair"]
    assert calls == [2, 2, 4]
    pointer = {"pair": published["pair"], "publicationReceipt": published["publicationReceipt"]}
    assert pub.verify_published_pointer(pointer, expected_game_id=game["gameId"])[0] == pair
    with pytest.raises(ValueError, match="TIMING_OR_LINEAGE"):
        pub.verify_published_pointer(pointer, expected_game_id="DIFFERENT_SYNTHETIC_GAME")
    wrong_deadline = (start-timedelta(minutes=4)).isoformat()
    wrong_pair = pub.save("wrong-deadline-synthetic-pair.json", {**pair, "deadlineUtc": wrong_deadline}, root)
    receipt = pub.read(published["publicationReceipt"])
    wrong_receipt = pub.save("wrong-deadline-synthetic-receipt.json", {
        **receipt, "pair": wrong_pair, "deadlineUtc": wrong_deadline}, root)
    with pytest.raises(ValueError, match="TIMING_OR_LINEAGE"):
        pub.verify_published_pointer({"pair": wrong_pair, "publicationReceipt": wrong_receipt})
    population_path = pub.verified(pair["population"])
    population_path.write_bytes(population_path.read_bytes()+b" ")
    with pytest.raises(ValueError, match="CHECKSUM"):
        pub.verify_published_pointer(pointer)
    with pytest.raises(ValueError, match="CHECKSUM"):
        pub.tick(declaration_ref, root=root)
    assert calls == [2, 2, 4]


def test_open_input_rechecks_cool_down_without_attempt_and_deadline_is_terminal(tmp_path, monkeypatch):
    """Regression: readiness was previously called SKIPPED and preflight used an attempt."""
    from contextlib import nullcontext
    import json
    from server.sports_current_statcast import mlb_starter_duration_paired_publication as pub
    from server.sports_current_statcast import mlb_starter_duration_current_inputs as inputs_module
    from scripts import inventory_mlb_current_slate as inventory_module

    clock = [datetime(2030, 4, 1, 20, tzinfo=timezone.utc)]
    monkeypatch.setattr(pub, "now", lambda: clock[0])
    monkeypatch.setattr(pub, "ROOT", tmp_path)
    monkeypatch.setattr(pub, "single_owner", lambda path: nullcontext(True))
    monkeypatch.setattr(pub, "production_busy", lambda: False)
    game = {"gameId": "SYNTHETIC_PENDING_ONLY", "scheduledStartUtc": (clock[0]+timedelta(minutes=15)).isoformat(),
        "deadlineUtc": (clock[0]+timedelta(minutes=10)).isoformat()}
    root = tmp_path/"research"
    declaration = pub.save("declaration.json", {"games": [game], "maxTickWallSeconds": 30}, root)
    snapshot = {"capturedAt": clock[0].isoformat(), "sides": [],
        "game": {"game_id": game["gameId"], "starts_at": game["scheduledStartUtc"]}}
    capture_file = tmp_path/"capture.json"
    capture_file.write_text(json.dumps({"capturedAt": clock[0].isoformat(), "snapshots": [snapshot]}))
    captures, supported = [], [False]

    def capture(**kwargs):
        captures.append(kwargs["game_ids"])
        return {"games": [{"game": snapshot["game"]}]}, {"snapshotsPath": str(capture_file)}

    monkeypatch.setattr(inventory_module, "capture_current_slate", capture)
    missing = {"side": "AWAY", "reason": "CURRENT_START_HISTORY_COVERAGE_INCOMPLETE",
        "pitcherId": "SYNTHETIC_PITCHER", "unresolvedDates": ["2030-03-28"]}
    monkeypatch.setattr(inputs_module, "build_current_duration_inputs", lambda *a, **k:
        {"status": "SUPPORTED" if supported[0] else "UNSUPPORTED", "missingReasons": [missing, dict(missing), "MISSING_START_HISTORY"]})
    source = tmp_path/"source"
    source.mkdir()
    # A newly available producer is still incompatible; this pure-input check
    # must remain pending and cannot reserve a numerical attempt.
    wrong = {**snapshot, "game": {**snapshot["game"], "starts_at": (clock[0]+timedelta(hours=4)).isoformat()}}
    (source/"pregame-evidence.json").write_text(json.dumps(wrong))
    (source/"execution-inputs.json").write_text("{}")
    monkeypatch.setattr(pub, "find_producer_objects", lambda declaration: {game["gameId"]: (source, {}, {})})
    first = pub.tick(declaration, root=root)
    assert first["pendingCount"] == 1 and first["skippedCount"] == 0
    assert first["games"][0]["reasons"] == [missing, "MISSING_START_HISTORY"]
    assert first["games"][0]["nextCheckUtc"] == (clock[0]+timedelta(minutes=5)).isoformat()
    assert not (root/"attempts").exists()
    clock[0] += timedelta(minutes=2)
    waiting = pub.tick(declaration, root=root)
    assert waiting["games"][0]["cooldownActive"] and len(captures) == 1
    assert waiting["games"][0]["checkedAt"] == first["games"][0]["checkedAt"]
    clock[0] += timedelta(minutes=3)
    supported[0] = True
    preflight = pub.tick(declaration, root=root)
    assert len(captures) == 2 and preflight["pendingCount"] == 1
    assert preflight["games"][0]["reasons"] == ["CURRENT_PARTICIPANTS_OR_START_DIFFER_FROM_COMPLETE_PRODUCER_INPUT"]
    assert not (root/"attempts").exists()
    clock[0] += timedelta(minutes=5)
    closed = pub.tick(declaration, root=root)
    assert closed["pendingCount"] == 0 and closed["terminalSkippedCount"] == 1
    assert closed["games"][0]["reasons"] == ["PREGAME_DEADLINE_CLOSED_NO_BACKFILL"]
    assert closed["games"][0]["nextCheckUtc"] is None and len(captures) == 2
    assert not (root/"attempts").exists()
