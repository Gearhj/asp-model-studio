"""The same two bounded publication cases, using synthetic repaired populations."""
from datetime import datetime, timedelta, timezone
import json

import joblib
import numpy as np
import pandas as pd
import pytest

from server.sports_nfl_m1 import current_state_repaired_publication as publication
from server.sports_nfl_m1.current_state_repaired_model import RATE_NAMES
from server.sports_nfl_m1.labs_simulation import file_record


class FixtureRepairedSystem:
    metadata = {"trainingEnd": "2025-02-09", "repairAuthority": publication.REPAIR_AUTHORITY,
                "evidenceClass": "RETROSPECTIVE_RECONSTRUCTED_AS_OF", "sealed2025Read": False}
    league_prior = {"training_ids": ["2024_22_KC_PHI"]}
    decay, lag_hours = .65, 48
    forbid_prediction = False

    def state(self):
        return {**self.metadata, **publication.AUTHORITY, "contract": publication.MODEL_CONTRACT,
                "inputNames": list(publication.INPUT_NAMES), "meanInputNames": list(publication.MEAN_INPUT_NAMES),
                "uncertaintyOnlyNames": list(publication.UNCERTAINTY_ONLY_NAMES), "selectedInputCount": 52}

    def predict(self, frame, team, qb, *, draws, seed):
        if self.forbid_prediction:
            raise AssertionError("inference must not run after kickoff")
        data = {name: np.ones(len(frame)) for name in publication.INPUT_NAMES}
        for name in RATE_NAMES:
            for suffix, value in (("__effective_exposure", 10), ("__current_exposure", 0),
                                  ("__posterior_sd", 2), ("__source_unknown", 0)):
                data[name + suffix] = np.full(len(frame), value)
        states = pd.concat([frame.reset_index(drop=True), pd.DataFrame(data)], axis=1)
        rng = np.random.default_rng(seed)
        raw_home = rng.choice(np.asarray([3., 20., 38.]), size=(len(frame), draws))
        raw_away = rng.choice(np.asarray([2., 17., 30.]), size=(len(frame), draws))
        result = {"_states": states}
        for index, name in enumerate(publication.MODEL_IDS):
            means = np.tile([20.33331+index, 19.87555-index], (len(frame), 1))
            home = publication.mean_preserving_scores(raw_home, means[:, 0])
            away = publication.mean_preserving_scores(raw_away, means[:, 1])
            result[name] = {"homeDraws": home, "awayDraws": away, "scoreMeans": means,
                "stateUncertainty": np.ones((len(frame), 2)), "fittedLatentResidualVariance": np.ones((len(frame), 2)),
                "actualPopulationVariance": np.column_stack((home.var(axis=1), away.var(axis=1))),
                "stateUncertaintyMeaning": "FITTED_TOTAL_RESIDUAL_SCORE_SD_NOT_PARAMETER_POSTERIOR_SD",
                "branchCounts": {"genericMedianFallbacks": 0}, "residualAuthoritySha256": "a" * 64,
                "repairAuthority": publication.REPAIR_AUTHORITY}
        return result


def _setup(tmp_path, monkeypatch, *, forbid=False):
    monkeypatch.setattr(publication, "REPAIR_ROOT", tmp_path)
    monkeypatch.setattr(publication, "RepairedCurrentStateSystem", FixtureRepairedSystem)
    now = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    events = [{"eventId": "2026_01_NE_SEA", "season": 2026, "week": 1, "homeTeamId": "SEA", "awayTeamId": "NE", "kickoffUtc": (now+timedelta(days=1)).isoformat()},
              {"eventId": "2026_01_OLD_DONE", "season": 2026, "week": 1, "homeTeamId": "DONE", "awayTeamId": "OLD", "kickoffUtc": (now-timedelta(days=1)).isoformat()}]
    monkeypatch.setattr(publication, "schedule_events_from_handoff", lambda: {"events": events, "sourceHandoffs": []})
    monkeypatch.setattr(publication, "_context", lambda *args: {"evidenceClass": "OBSERVED_AS_OF", "numericallyIncorporated": False})
    system = FixtureRepairedSystem()
    system.forbid_prediction = forbid
    model_path = tmp_path / "frozen-model-fixture.joblib"
    joblib.dump(system, model_path)
    model_ref = file_record(model_path)
    study_ref = publication.immutable_json(tmp_path / "study-fixture.json", {**publication.AUTHORITY,
        "contract": "NFL_CURRENT_STATE_RECONSTRUCTED_STUDY_RESULT_V2", "finalOotAccessed": False,
        "completedAtUtc": now.isoformat(), "finalModel": model_ref})
    history = pd.DataFrame({"season": [2024], "game_date": [pd.Timestamp("2025-02-09")]})
    source = {"sealedOotRead": False, "sources": [{"season": 2024, "retrievedAt": "2026-08-29T12:00:00Z", "sha256": "b" * 64, "byteCount": 1}]}
    return now, system, model_ref, study_ref, history, source


def test_repaired_population_means_labels_and_reuse_are_exact(tmp_path, monkeypatch):
    now, system, model_ref, study_ref, history, source = _setup(tmp_path, monkeypatch)
    args = (system, history, history, model_ref, study_ref, tmp_path / "publication")
    first = publication.publish_repaired_current_v2(*args, source_receipt=source, clock=lambda: now, ensemble_weight=.3)
    assert first["forecastCount"] == 4 and first["eventCount"] == 1 and first["skipCount"] == 1
    handoff = json.loads(open(first["handoff"]["path"]).read())
    assert handoff["publicationDisposition"] == "REPAIRED_HISTORICAL_PRIOR_BASELINE"
    assert {item["modelId"] for item in handoff["artifacts"]} == {f"NFL_CURRENT_STATE_{name}_V2_REPAIRED" for name in (*publication.MODEL_IDS, "ENSEMBLE")}
    for ref in handoff["artifacts"]:
        artifact = publication.verify_object(ref)
        assert artifact["forecastType"] == "HISTORICAL_PRIOR_BASELINE"
        assert artifact["model"]["modelVersion"] == "NFL_UNCERTAINTY_MEAN_SEPARATION_REPAIR_V1"
        assert artifact["evidenceClass"] == "OBSERVED_AS_OF"
        assert artifact["currentContextNumericallyIncorporated"] is artifact["currentRosterDepthNumericallyIncorporated"] is False
        assert artifact["wageringAuthority"] is False and artifact["simulatedDrives"] is None
        mean = artifact["meanPreservation"]
        assert mean["actualIntegerScoreSums"] == mean["expectedIntegerScoreSums"]
        assert np.max(np.abs(np.array(mean["targetConditionalScoreMeans"])-mean["actualPopulationScoreMeans"])) <= .0001 + 1e-12
        assert sum(row["count"] for row in artifact["jointScoreDistribution"]) == 5000
        feature = json.loads(open(artifact["featureEvidence"]["path"]).read())
        assert len(feature["inputs"]) == 58 and sum(row["usedInMeanPredictor"] for row in feature["inputs"]) == 52
        assert all(not row["usedInMeanPredictor"] for row in feature["inputs"] if row["feature"] in publication.UNCERTAINTY_ONLY_NAMES)
    repeated = publication.publish_repaired_current_v2(*args, source_receipt=source, clock=lambda: now+timedelta(hours=1), ensemble_weight=.3)
    assert repeated["reused"] == repeated["forecastCount"] == 4
    assert json.loads(open(repeated["handoff"]["path"]).read())["artifacts"] == handoff["artifacts"]
    bad = {"repairAuthority": publication.REPAIR_AUTHORITY, "scoreMeans": np.array([[20., 20.]]),
           "homeDraws": np.full((1,5000),21), "awayDraws": np.full((1,5000),20)}
    with pytest.raises(ValueError, match="DOES_NOT_PRESERVE"):
        publication._population_mean_check(bad)


def test_repaired_guard_rejects_old_type_corrupt_identity_and_postkickoff(tmp_path, monkeypatch):
    now, system, model_ref, study_ref, history, source = _setup(tmp_path, monkeypatch, forbid=True)
    args = (system, history, history, model_ref, study_ref)
    late = publication.publish_repaired_current_v2(*args, tmp_path / "late", source_receipt=source, clock=lambda: now+timedelta(days=2))
    assert late["forecastCount"] == 0 and late["skipCount"] == 2
    ticks = iter([now, now, now+timedelta(days=2)])
    crossed = publication.publish_repaired_current_v2(*args, tmp_path / "crossed", source_receipt=source,
        clock=lambda: next(ticks, now+timedelta(days=2)))
    assert crossed["forecastCount"] == 0
    assert any(item["reason"] == "KICKOFF_REACHED_ADJACENT_TO_REPAIRED_INFERENCE" for item in crossed["skips"])
    with pytest.raises(ValueError, match="ONLY_FROZEN_REPAIRED_MODEL_CLASS"):
        publication.publish_repaired_current_v2(object(), history, history, model_ref, study_ref,
            tmp_path / "old-type", source_receipt=source, clock=lambda: now)
    with pytest.raises(ValueError, match="PARENT_CHECKSUM"):
        publication.publish_repaired_current_v2(system, history, history, {**model_ref, "sha256": "0" * 64}, study_ref,
            tmp_path / "bad", source_receipt=source, clock=lambda: now)
