from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from sports_cfb_gen1 import prospective_collection as c


def protocol():
    return {"frozenAtUtc": "2026-09-18T20:00:00Z", "enrollmentEndsAtUtc": "2026-10-01T00:00:00Z",
            "kickoffBeforeUtc": "2026-10-01T00:00:00Z"}


def target():
    return {"game_id": 99, "season": 2026, "week": 3, "scheduled_at": "2026-09-18T23:30:00Z"}


@pytest.mark.parametrize("clock", ["2026-09-18T19:59:59Z", "2026-09-18T23:00:00Z", "2026-10-01T00:00:00Z"])
def test_no_retrospective_or_late_enrollment(clock):
    with pytest.raises(ValueError):
        c.validate_enrollment(protocol(), target(), clock)


def test_postfreeze_precutoff_enrollment():
    c.validate_enrollment(protocol(), target(), "2026-09-18T22:59:59Z")


def history_row(gid, date, season=2026):
    return {"game_id": gid, "season": season, "scheduled_at": pd.Timestamp(date), "primary": True,
            "is_final": True, "home_score": 21, "away_score": 14, "source_captured_at": pd.Timestamp("2026-09-18T16:00:00Z")}


def fixture():
    historical = pd.DataFrame([history_row(1, "2025-11-01T00:00:00Z", 2025)])
    source = {"currentHistory": pd.DataFrame([history_row(2, "2026-09-16T00:00:00Z"),
                                             history_row(3, "2026-09-17T00:00:00Z")]),
              "inputCutoffUtc": "2026-09-18T17:00:00Z", "observedAtUtc": "2026-09-18T20:01:00Z"}
    return {"historicalPrimary": historical}, source


def test_final_capture_and_embargo_both_required():
    candidate, source = fixture()
    history = c.eligible_strength_history(candidate, source, target())
    assert history.game_id.tolist() == [1, 2]
    source["currentHistory"].loc[0, "source_captured_at"] = pd.Timestamp("2026-09-18T18:00:00Z")
    with pytest.raises(ValueError, match="not observed"):
        c.eligible_strength_history(candidate, source, target())


def test_kickoff_cannot_replace_final_status():
    candidate, source = fixture()
    source["currentHistory"].loc[0, "is_final"] = False
    with pytest.raises(ValueError, match="source-declared"):
        c.eligible_strength_history(candidate, source, target())


def test_duplicate_identity_fails_closed():
    candidate, source = fixture()
    source["currentHistory"].loc[0, "game_id"] = 1
    with pytest.raises(ValueError, match="Duplicate"):
        c.eligible_strength_history(candidate, source, target())


def test_physical_binding_detects_mutation(tmp_path):
    ref = c.save_json(tmp_path, {"selectedArm": "B", "lambda": 4}, "candidate.json")
    assert c.read(ref)["selectedArm"] == "B"
    Path(ref["path"]).write_text('{"selectedArm":"A"}')
    with pytest.raises(ValueError, match="Physical binding"):
        c.read(ref)


def test_naive_clocks_rejected():
    with pytest.raises(ValueError, match="UTC-aware"):
        c.utc("2026-09-18T20:01:00")


def collection_fixture(tmp_path, monkeypatch):
    import io
    import joblib
    from sports_cfb_gen1 import prospective_sources as sources
    config = {**protocol(), "canonicalModelBindings": {}, "canonicalHistoricalGames": {}, "discoveryPointer": "synthetic"}
    buffer = io.BytesIO()
    joblib.dump({"synthetic": True}, buffer)
    artifact = c.save_bytes(tmp_path, buffer.getvalue(), "candidate.joblib")
    config["candidateManifest"] = c.save_json(tmp_path, {"candidate": artifact}, "candidate-manifest.json")
    protocol_ref = c.save_json(tmp_path, config, "protocol.json")
    monkeypatch.setattr(c, "load_protocol", lambda out: (protocol_ref, config))
    bundle = c.save_json(tmp_path, {"games": [{"gameId": 99, "target": target()}]}, "bundle.json")
    snapshot = {"document": {"inputVersion": bundle}, "manifest": bundle, "packages": [{"gameId": 99}]}
    monkeypatch.setattr(sources, "load_discovery", lambda *args, **kwargs: snapshot)
    clock = ["2026-09-18T20:01:00Z"]
    draws = pd.DataFrame({"home_score": [21]*10000, "away_score": [14]*10000,
                          "home_margin": [7]*10000, "total": [35]*10000})
    source = {"target": target(), "inputCutoffUtc": "2026-09-18T17:00:00Z", "observedAtUtc": clock[0],
              "forecast": {"modelBindings": {}}, "baselineDraws": draws, "baselinePoints": {},
              "packageReceipt": {}, "currentEligibilityEvaluatedAtUtc": clock[0],
              "bindings": {"historicalGames": {}, "currentEligibilityValidUntilUtc": "2026-09-18T20:20:00Z"}}
    monkeypatch.setattr(sources, "load_pair_source", lambda *args, **kwargs: source)
    prediction = {"draws": draws, "features": pd.DataFrame({"synthetic": [1]}),
                  "history": pd.DataFrame({"game_id": [1]}), "strength": {}, "points": {},
                  "support": {"low_support": True, "zero_prior_support": False}, "accounting": {}}
    monkeypatch.setattr(c, "predict_candidate", lambda *args: prediction)
    return clock, prediction


def test_actual_pair_is_durable_and_idempotent(tmp_path, monkeypatch):
    clock, _ = collection_fixture(tmp_path, monkeypatch)
    first = c.collect(tmp_path, clock=lambda: clock[0])
    second = c.collect(tmp_path, clock=lambda: clock[0])
    assert first["captured"] == 1 and second["captured"] == 0
    assert second["totalEnrolled"] == 1
    commit = c.read(c.pair_index(tmp_path)["99"])
    pair = c.read(commit["pair"])
    assert c.utc(pair["createdAtUtc"]) >= c.utc("2026-09-18T20:00:00Z")
    assert c.utc(commit["committedAtUtc"]) < c.utc(commit["cutoffUtc"])
    (tmp_path / "PAIRS.json").unlink()
    recovered = c.collect(tmp_path, clock=lambda: clock[0])
    assert recovered["captured"] == 0 and recovered["totalEnrolled"] == 1
    assert c.read(c.pair_index(tmp_path)["99"]) == commit


def test_lease_or_cutoff_expiring_during_fit_does_not_enroll(tmp_path, monkeypatch):
    clock, predicted = collection_fixture(tmp_path, monkeypatch)
    def delayed(*args):
        clock[0] = "2026-09-18T20:20:01Z"
        return predicted
    monkeypatch.setattr(c, "predict_candidate", delayed)
    result = c.collect(tmp_path, clock=lambda: clock[0])
    assert result["captured"] == 0 and not c.pair_index(tmp_path)
    assert "expired" in result["excludedAttempts"][0]["reason"]
