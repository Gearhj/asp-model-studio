"""Two bounded publisher checks using deterministic non-model populations."""
from datetime import datetime, timedelta, timezone
import json

import numpy as np
import pandas as pd
import pytest

from server.sports_nfl_m1 import current_state_publication as publication


class FixtureSystem:
    metadata = {"trainingEnd": "2025-02-09"}
    league_prior = {"training_ids": ["2024_22_KC_PHI"]}
    decay, lag_hours = .65, 48
    missing_seasons = 0

    def predict(self, frame, team, qb, *, draws, seed):
        data = {name: np.ones(len(frame)) for name in publication.INPUT_NAMES}
        for side in ("home", "away"):
            data[f"{side}_missing_season_uncertainty"] = np.full(len(frame), self.missing_seasons)
        for name in publication.RATE_NAMES:
            for suffix, value in (("__effective_exposure", 10), ("__current_exposure", 0),
                                  ("__posterior_sd", 2), ("__source_unknown", 0)):
                data[name + suffix] = np.full(len(frame), value)
        states = pd.concat([frame.reset_index(drop=True), pd.DataFrame(data)], axis=1)
        rng = np.random.default_rng(seed)
        home = rng.choice(np.asarray([21,24,17], dtype=np.int32), size=(len(frame), draws))
        away = rng.choice(np.asarray([20,24,27], dtype=np.int32), size=(len(frame), draws))
        return {"_states": states, **{name: {"homeDraws": home, "awayDraws": away,
                "scoreMeans": np.tile([20., 23.], (len(frame), 1)), "stateUncertainty": np.ones((len(frame), 2)),
                "branchCounts": {"genericMedianFallbacks": 0}, "residualAuthoritySha256": "a" * 64}
                for name in publication.MODEL_IDS}}


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(publication, "OUTPUTS_ROOT", tmp_path)
    now = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    events = [{"eventId": "2026_01_NE_SEA", "season": 2026, "week": 1, "homeTeamId": "SEA", "awayTeamId": "NE", "kickoffUtc": (now+timedelta(days=1)).isoformat()},
              {"eventId": "2026_01_OLD_DONE", "season": 2026, "week": 1, "homeTeamId": "DONE", "awayTeamId": "OLD", "kickoffUtc": (now-timedelta(days=1)).isoformat()}]
    monkeypatch.setattr(publication, "schedule_events_from_handoff", lambda: {"events": events, "sourceHandoffs": []})
    monkeypatch.setattr(publication, "_context", lambda *args: {"evidenceClass": "OBSERVED_AS_OF", "numericallyIncorporated": False})
    model_ref = publication.immutable_json(tmp_path / "frozen-model-fixture.json", {"fixture": True})
    study_ref = publication.immutable_json(tmp_path / "study-fixture.json", {"fixture": True})
    history = pd.DataFrame({"season": [2024], "game_date": [pd.Timestamp("2025-02-09")]})
    source = {"sealedOotRead": False, "sources": [{"season": 2024, "retrievedAt": "2026-08-29T12:00:00Z", "sha256": "b" * 64, "byteCount": 1}]}
    return now, model_ref, study_ref, history, source


def test_current_population_checksum_reconciliation_and_idempotent_identity(tmp_path, monkeypatch):
    now, model_ref, study_ref, history, source = _setup(tmp_path, monkeypatch)
    schedule = publication.schedule_events_from_handoff()
    schedule["events"].insert(1, {"eventId": "2026_01_CIN_BUF", "season": 2026, "week": 1,
        "homeTeamId": "BUF", "awayTeamId": "CIN", "kickoffUtc": (now+timedelta(days=2)).isoformat()})
    monkeypatch.setattr(publication, "schedule_events_from_handoff", lambda: schedule)
    args = (FixtureSystem(), history, history, model_ref, study_ref, tmp_path / "publication")
    first = publication.publish_current_v2(*args, source_receipt=source, clock=lambda: now, ensemble_weight=.3)
    assert first["forecastCount"] == 8 and first["eventCount"] == 2
    assert first["skips"][0]["reason"] == "KICKOFF_REACHED_BEFORE_INFERENCE"
    handoff = json.loads(open(first["handoff"]["path"]).read())
    assert handoff["evidenceClass"] == "OBSERVED_AS_OF"
    for ref in handoff["artifacts"]:
        artifact = publication.verify_object(ref)
        assert artifact["evidenceClass"] == "OBSERVED_AS_OF"
        assert json.loads(open(ref["manifest"]["path"]).read())["evidenceClass"] == "OBSERVED_AS_OF"
        assert json.loads(open(artifact["featureEvidence"]["path"]).read())["evidenceClass"] == "RETROSPECTIVE_RECONSTRUCTED_AS_OF"
        assert artifact["drawCount"] == 5000
        assert sum(row["count"] for row in artifact["jointScoreDistribution"]) == 5000
        assert sum(row["probability"] for row in artifact["jointScoreDistribution"]) == pytest.approx(1)
        assert artifact["sourceCutoffUtc"] == "2026-08-29T12:00:00+00:00"
        assert artifact["trainingEvidenceClass"] == "RETROSPECTIVE_RECONSTRUCTED_AS_OF"
        assert artifact["currentContextNumericallyIncorporated"] is False
        assert artifact["wageringAuthority"] is False and artifact["simulatedDrives"] is None
    second = publication.publish_current_v2(*args, source_receipt=source, clock=lambda: now+timedelta(hours=1), ensemble_weight=.3)
    assert second["reused"] == 8
    repeated = json.loads(open(second["handoff"]["path"]).read())
    assert repeated["artifacts"] == handoff["artifacts"]
    # Removing the first game must not shift the remaining event's CRN row or
    # its home/away rounding stream, or create a replacement forecast identity.
    third = publication.publish_current_v2(*args, source_receipt=source,
        clock=lambda: now+timedelta(days=1, hours=1), ensemble_weight=.3)
    assert third["forecastCount"] == third["reused"] == 4
    retained = json.loads(open(third["handoff"]["path"]).read())
    assert retained["artifacts"] == [item for item in handoff["artifacts"] if item["eventId"] == "2026_01_CIN_BUF"]
    # A previously unvalidated missing-season regime may not publish the
    # hierarchical mean, its HGB correction, or their ensemble.
    affected = FixtureSystem()
    affected.missing_seasons = 1
    guarded = publication.publish_current_v2(affected, history, history, model_ref, study_ref,
        tmp_path / "publication", source_receipt=source, clock=lambda: now, ensemble_weight=.3)
    guarded_handoff = json.loads(open(guarded["handoff"]["path"]).read())
    assert guarded["forecastCount"] == 2 and guarded["eventCount"] == 2
    assert {item["modelId"] for item in guarded_handoff["artifacts"]} == {"NFL_CURRENT_STATE_DYNAMIC_V2"}
    withheld = [item for item in guarded["skips"] if item.get("component")]
    assert len(withheld) == 6
    assert {item["component"] for item in withheld} == {"HIERARCHICAL", "RESIDUAL", "ENSEMBLE"}
    assert all(item["reason"] == publication.MISSING_SEASON_ADMISSION_REASON for item in withheld)
    again = publication.publish_current_v2(affected, history, history, model_ref, study_ref,
        tmp_path / "publication", source_receipt=source, clock=lambda: now, ensemble_weight=.3)
    assert again["forecastCount"] == again["reused"] == 2


def test_no_postkickoff_inference_and_corrupt_parent_rejected(tmp_path, monkeypatch):
    now, model_ref, study_ref, history, source = _setup(tmp_path, monkeypatch)
    system = FixtureSystem()
    def forbidden(*args, **kwargs):
        raise AssertionError("inference must not run after kickoff")
    system.predict = forbidden
    late = publication.publish_current_v2(system, history, history, model_ref, study_ref,
        tmp_path / "late", source_receipt=source, clock=lambda: now+timedelta(days=2))
    assert late["forecastCount"] == 0 and late["skipCount"] == 2
    ticks = iter([now, now, now, now+timedelta(days=2)])
    crossed = publication.publish_current_v2(system, history, history, model_ref, study_ref,
        tmp_path / "crossed", source_receipt=source, clock=lambda: next(ticks, now+timedelta(days=2)))
    assert crossed["forecastCount"] == 0
    assert any(item["reason"] == "KICKOFF_REACHED_AT_BATCH_INFERENCE_GUARD" for item in crossed["skips"])
    wrong = {**model_ref, "sha256": "0" * 64}
    with pytest.raises(ValueError, match="PARENT_CHECKSUM"):
        publication.publish_current_v2(system, history, history, wrong, study_ref,
            tmp_path / "bad", source_receipt=source, clock=lambda: now)
