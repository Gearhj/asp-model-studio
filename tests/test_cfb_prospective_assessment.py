"""Synthetic tests only: no retained football result populations are opened."""
from copy import deepcopy
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from sports_cfb_gen1 import prospective_assessment as a
from sports_cfb_gen1 import prospective_collection as c


def protocol():
    return {"frozenAtUtc": "2026-09-18T20:00:00Z", "enrollmentEndsAtUtc": "2026-10-01T00:00:00Z",
            "kickoffBeforeUtc": "2026-10-01T00:00:00Z", "acquisitionExpiresAtUtc": "2026-10-01T00:00:00Z",
            "finalEvidencePointer": "synthetic-only", "assessmentSchedule": [
                {"id": "interim", "kind": "interim", "atUtc": "2026-09-22T16:00:00Z"},
                {"id": "final", "kind": "final", "atUtc": "2026-10-01T12:00:00Z"},
                {"id": "closure", "kind": "closure", "atUtc": "2026-10-02T12:00:00Z"}],
            "adequacy": {"overall": {"minimumGames": 80, "minimumUtcDates": 6, "minimumIsoWeeks": 2},
                         "low_support": {"minimumGames": 40, "minimumUtcDates": 3, "minimumIsoWeeks": 2},
                         "zero_prior_support": {"descriptiveOnly": True}}}


def make_pair(tmp_path, pref, game_id=99):
    target = {"game_id": game_id, "season": 2026, "week": 3, "scheduled_at": "2026-09-19T16:00:00Z",
              "home_id": 1, "away_id": 2, "neutral_site": 0, "conference_competition": 0}
    # Repeated synthetic draws have a known score-space distance and CRPS.
    draws = pd.DataFrame({"home_score": np.full(10000, 24, dtype=np.int16),
                          "away_score": np.full(10000, 14, dtype=np.int16)})
    base = c.save_frame(tmp_path, draws, "synthetic-gen1.parquet")
    draws["home_score"] = np.int16(27)
    challenger = c.save_frame(tmp_path, draws, "synthetic-b.parquet")
    points = {"pred_home": 24., "pred_away": 14., "pred_margin": 10., "pred_total": 38.}
    pair = {"target": target, "protocol": pref, "createdAtUtc": "2026-09-18T20:10:00Z",
            "originalInputCutoffUtc": "2026-09-18T20:05:00Z",
            "support": {"home_current_support": 1, "away_current_support": 2, "home_prior_support": 10,
                        "away_prior_support": 0, "low_support": True, "zero_prior_support": True},
            "gen1Points": points, "bPoints": {**points, "pred_home": 27., "pred_margin": 13., "pred_total": 41.},
            "artifacts": {"gen1Draws": base, "bDraws": challenger}}
    ref = c.save_json(tmp_path, pair, "synthetic-pair.json")
    commit = {"protocol": pref, "pair": ref, "gameId": game_id,
              "committedAtUtc": "2026-09-18T20:10:01Z", "cutoffUtc": "2026-09-19T15:30:00Z"}
    return c.save_json(tmp_path, commit, "synthetic-commit.json"), pair


def final_row(captured="2026-09-19T20:00:00Z", home=27):
    return {"sourceGameId": 99, "homeTeamId": 1, "awayTeamId": 2, "homeFinalPoints": home,
            "awayFinalPoints": 14, "season": 2026, "scheduledKickoffUtc": "2026-09-19T16:00:00Z",
            "capturedAtUtc": captured, "completed": True, "sourceCompleted": True}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    p = protocol()
    pref = c.save_json(tmp_path, p, "synthetic-protocol.json")
    cref, pair = make_pair(tmp_path, pref)
    source = {"rows": [final_row()], "bindings": {"synthetic": True}}
    monkeypatch.setattr(c, "load_protocol", lambda out: (pref, p))
    monkeypatch.setattr(c, "pair_index", lambda out: {"99": cref})
    monkeypatch.setattr(a, "load_final_evidence", lambda pointer, as_of_utc: deepcopy(source))
    return tmp_path, p, pref, cref, pair, source


def receipt(result, entry_id):
    return c.read(next(item["receipt"] for item in result["assessmentReceipts"] if item["id"] == entry_id))


def test_monitor_does_not_score_or_read_draws_before_due(setup, monkeypatch):
    out, _, pref, _, _, _ = setup
    monkeypatch.setattr(a, "score_pair", lambda *args: pytest.fail("Monitoring scored outcomes"))
    monkeypatch.setattr(a, "_draws", lambda *args: pytest.fail("Monitoring opened draw populations"))
    result = a.monitor_and_assess(out, clock=lambda: "2026-09-20T00:00:00Z")
    assert result["newOutcomeRevisions"] == result["activeSourceFinals"] == 1
    assert result["assessmentReceipts"] == [] and result["metricsComputedThisTick"] is False
    assert not (out / "ASSESSMENTS.json").exists()
    monitor = c.read(result["monitorReceipt"])
    assert monitor["metricsComputed"] is monitor["drawPopulationsRead"] is False
    assert len(a._index(out, "OUTCOMES.json", "revisions", pref)["99"]) == 1


@pytest.mark.parametrize("change", [
    {"completed": "true"}, {"sourceCompleted": False}, {"sourceGameId": 999}, {"homeTeamId": 2},
    {"scheduledKickoffUtc": "2026-09-19T17:00:00Z"}, {"season": 2025}, {"homeFinalPoints": -1},
    {"homeFinalPoints": 1.5}, {"homeFinalPoints": True}, {"homeFinalPoints": 14},
    {"capturedAtUtc": "2026-09-19T16:00:00Z"}, {"capturedAtUtc": "2026-10-01T00:00:00Z"},
    {"capturedAtUtc": "2026-09-21T00:00:00Z"},
])
def test_invalid_final_never_admitted(setup, change):
    _, _, _, cref, pair, _ = setup
    with pytest.raises(ValueError):
        a._outcome({**final_row(), **change}, pair["target"], c.read(cref),
                   c.utc("2026-10-01T00:00:00Z"), c.utc("2026-09-20T00:00:00Z"))


def test_duplicate_source_final_fails_closed(setup):
    out, _, _, _, _, source = setup
    source["rows"].append(deepcopy(source["rows"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        a.monitor_and_assess(out, clock=lambda: "2026-09-20T00:00:00Z")
    assert not (out / "OUTCOMES.json").exists()


def test_revisions_preserve_lineage_and_late_interim_cutoff(setup):
    out, _, pref, _, _, source = setup
    a.monitor_and_assess(out, clock=lambda: "2026-09-20T00:00:00Z")
    original = a._index(out, "OUTCOMES.json", "revisions", pref)["99"][0]
    original_bytes = c.verified(original)
    # Identical recapture does not rewrite or multiply the original revision.
    source["rows"] = [final_row("2026-09-21T10:00:00Z")]
    unchanged = a.monitor_and_assess(out, clock=lambda: "2026-09-21T11:00:00Z")
    assert unchanged["newOutcomeRevisions"] == 0
    source["rows"] = [final_row("2026-09-22T18:00:00Z", home=30)]
    result = a.monitor_and_assess(out, clock=lambda: "2026-09-22T19:00:00Z")
    revisions = a._index(out, "OUTCOMES.json", "revisions", pref)["99"]
    assert len(revisions) == 2
    corrected = c.read(revisions[-1])
    assert corrected["predecessor"] == original and corrected["revisionNumber"] == 2
    assert c.verified(original) == original_bytes
    report = receipt(result, "interim")
    assert report["executedAtUtc"] == "2026-09-22T19:00:00Z"
    assert c.utc(report["logicalSourceCaptureCutoffUtc"]) == c.utc("2026-09-22T16:00:00Z")
    assert report["pairedPopulation"][0]["outcomeRevision"] == original
    scores = pd.read_parquet(report["scores"]["path"])
    assert scores.outcomeRevisionSha256.nunique() == 1
    assert scores.home_score.tolist() == [27, 27]
    assert scores.set_index("arm").loc["baseline", "jointEnergyScore"] == 3
    assert scores.set_index("arm").loc["B", "jointEnergyScore"] == 0
    assert report["groups"]["overall"]["metrics"]["jointEnergyScore"]["delta"] == -3
    assert report["groups"]["low_support"]["games"] == 1
    assert report["decision"]["disposition"] == "INTERIM_DESCRIPTIVE_NO_POSITIVE_STOP"


def test_only_later_capture_does_not_backdate_interim(setup):
    out, _, _, _, _, source = setup
    source["rows"] = [final_row("2026-09-22T18:00:00Z")]
    result = a.monitor_and_assess(out, clock=lambda: "2026-09-22T19:00:00Z")
    report = receipt(result, "interim")
    assert report["pairedFinalGames"] == 0 and report["scores"] is None
    assert report["metricsComputed"] is result["metricsComputedThisTick"] is False
    assert report["decision"]["disposition"] == "NO_ELIGIBLE_PAIRED_FINALS"
    assert report["groups"]["overall"]["games"] == 0


def test_one_time_receipt_is_not_recomputed(setup, monkeypatch):
    out, _, pref, _, _, _ = setup
    result = a.monitor_and_assess(out, clock=lambda: "2026-09-22T16:00:00Z")
    report = result["assessmentReceipts"][0]["receipt"]
    monkeypatch.setattr(a, "score_pair", lambda *args: pytest.fail("One-time assessment recomputed"))
    second = a.monitor_and_assess(out, clock=lambda: "2026-09-23T00:00:00Z")
    assert second["assessmentReceipts"] == [] and second["metricsComputedThisTick"] is False
    assert a._index(out, "ASSESSMENTS.json", "assessments", pref)["interim"] == report


def test_source_final_before_expiry_can_be_admitted_after_expiry(setup):
    out, _, _, _, _, source = setup
    source["rows"] = [final_row("2026-09-30T23:59:59Z")]
    result = a.monitor_and_assess(out, clock=lambda: "2026-10-01T12:30:00Z")
    assert receipt(result, "interim")["pairedFinalGames"] == 0
    final = receipt(result, "final")
    assert final["pairedFinalGames"] == 1
    assert c.utc(final["logicalSourceCaptureCutoffUtc"]) == c.utc("2026-10-01T00:00:00Z")
    source["rows"] = [final_row("2026-10-01T00:00:01Z", home=31)]
    closure = a.monitor_and_assess(out, clock=lambda: "2026-10-02T12:00:00Z")
    report = receipt(closure, "closure")
    assert report["pairedPopulation"] == final["pairedPopulation"]
    assert closure["newOutcomeRevisions"] == 0
    assert "outside acquisition" in closure["rejectedEvidence"][0]["reason"]


def test_missing_final_retracts_previous_without_rewriting_it(setup):
    out, _, pref, _, _, source = setup
    a.monitor_and_assess(out, clock=lambda: "2026-09-20T00:00:00Z")
    source["rows"] = [{**final_row("2026-09-22T10:00:00Z"), "sourceGameId": 100}]
    result = a.monitor_and_assess(out, clock=lambda: "2026-09-22T16:00:00Z")
    revisions = a._index(out, "OUTCOMES.json", "revisions", pref)["99"]
    assert len(revisions) == 2
    assert c.read(revisions[-1])["result"]["status"] == "WITHHELD_SOURCE_FINAL_ABSENT"
    assert receipt(result, "interim")["pairedFinalGames"] == 0


def test_incompatible_later_revision_withholds_old_final(setup):
    out, _, pref, _, _, source = setup
    a.monitor_and_assess(out, clock=lambda: "2026-09-20T00:00:00Z")
    source["rows"] = [{**final_row("2026-09-22T10:00:00Z"), "scheduledKickoffUtc": "2026-09-19T17:00:00Z"}]
    result = a.monitor_and_assess(out, clock=lambda: "2026-09-22T16:00:00Z")
    revisions = a._index(out, "OUTCOMES.json", "revisions", pref)["99"]
    assert len(revisions) == 2
    assert c.read(revisions[-1])["result"]["status"] == "WITHHELD_SOURCE_FINAL_INCOMPATIBLE"
    assert receipt(result, "interim")["pairedFinalGames"] == 0
    earlier = a.select_revision(revisions, c.utc("2026-09-21T16:00:00Z"))
    assert earlier[1]["result"]["status"] == "SOURCE_FINAL"


def synthetic_scores():
    rows = []
    dates = ["2026-09-18", "2026-09-19", "2026-09-20", "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-27"]
    for gid, day in enumerate(dates):
        for arm in ("baseline", "B"):
            rows.append({"game_id": gid, "arm": arm, "scheduled_at": pd.Timestamp(day, tz="UTC"),
                         "outcomeRevisionSha256": "same-" + str(gid), "low_support": gid < 4,
                         "zero_prior_support": gid == 0, **{key: 2.0 - (arm == "B") for key in a.METRICS}})
    return pd.DataFrame(rows)


def test_paired_uncertainty_uses_games_and_dates_not_draws():
    rows = synthetic_scores()
    result = a.paired_statistics(rows)
    assert (result["games"], result["utcDates"], result["isoWeeks"]) == (7, 7, 2)
    assert result["bootstrapReplicates"] == 2000
    assert [week["games"] for week in result["perWeek"]] == [3, 4]
    for values in result["metrics"].values():
        assert values == {"delta": -1., "low95": -1., "high95": -1., "gen1Mean": 2., "bMean": 1.}
    for values in result["gameBootstrapSensitivity"].values():
        assert values == {"low95": -1., "high95": -1.}


@pytest.mark.parametrize("change", ["population", "outcome", "metadata", "nonfinite"])
def test_different_paired_evidence_fails_closed(change):
    rows = synthetic_scores()
    if change == "population":
        rows = rows.iloc[1:]
    elif change == "outcome":
        rows.loc[1, "outcomeRevisionSha256"] = "another"
    elif change == "metadata":
        rows.loc[1, "low_support"] = False
    else:
        rows.loc[1, "jointEnergyScore"] = np.nan
    with pytest.raises(ValueError):
        a.paired_statistics(rows)


def groups(energy=-.2, high=-.1, margin=0., low_games=40, games=80):
    metrics = {key: {"delta": 0., "high95": .001, "low95": -.001} for key in a.METRICS}
    metrics["jointEnergyScore"] = {"delta": energy, "low95": energy-.1, "high95": high}
    metrics["marginCrps"]["delta"] = margin
    overall = {"games": games, "utcDates": 6, "isoWeeks": 2, "metrics": deepcopy(metrics)}
    low = {"games": low_games, "utcDates": 3, "isoWeeks": 2, "metrics": deepcopy(metrics)}
    return {"overall": overall, "low_support": low, "zero_prior_support": {"games": 2}}


def test_frozen_final_pilot_gate_cannot_promote_or_ignore_subgroup():
    p = protocol()
    decision = a.decide("final", groups(), p)
    assert decision["disposition"] == "PROMISING_PROSPECTIVE_PILOT"
    assert decision["productionAuthority"] is decision["promotionAuthority"] is decision["broadShadowRecommendation"] is False
    assert decision["zeroPriorSupportDisposition"] == "INSUFFICIENT_SUBGROUP_EVIDENCE_DESCRIPTIVE_CASES_ONLY"
    assert a.decide("final", groups(low_games=39), p)["disposition"] == "INCOMPLETE_SUBGROUP_EVIDENCE"
    assert a.decide("final", groups(games=79), p)["disposition"] == "INCOMPLETE_OVERALL_EVIDENCE"
    assert a.decide("final", groups(high=0.), p)["disposition"] == "NO_PROMISING_PROSPECTIVE_PILOT_SIGNAL"
    assert a.decide("final", groups(margin=.051), p)["disposition"] == "NO_PROMISING_PROSPECTIVE_PILOT_SIGNAL"


def test_interim_never_positive_and_harm_requires_both_metrics_and_games():
    p = protocol()
    assert a.decide("interim", groups(), p)["disposition"] == "INTERIM_DESCRIPTIVE_NO_POSITIVE_STOP"
    assert a.decide("interim", groups(energy=.5, margin=.5, games=30), p)["stopEnrollment"] is True
    assert a.decide("interim", groups(energy=.5, margin=.5, games=29), p)["stopEnrollment"] is False
    assert a.decide("interim", groups(energy=.5, margin=.49), p)["stopEnrollment"] is False
    assert a.decide("interim", groups(energy=.49, margin=.5), p)["stopEnrollment"] is False


def test_stop_marker_is_persisted_before_one_time_index(setup, monkeypatch):
    out, _, pref, _, _, _ = setup
    original_decide = a.decide
    monkeypatch.setattr(a, "decide", lambda kind, results, p: original_decide(kind, groups(energy=.5, margin=.5), p))
    real_index = a._put_index
    def checked_index(output, filename, *args):
        if filename == "ASSESSMENTS.json":
            assert (out / "STOP_ENROLLMENT.json").exists()
        return real_index(output, filename, *args)
    monkeypatch.setattr(a, "_put_index", checked_index)
    result = a.monitor_and_assess(out, clock=lambda: "2026-09-22T16:00:00Z")
    assert result["assessmentReceipts"][0]["disposition"] == "INTERIM_HARM_STOP_ENROLLMENT"
    stop = c.read(c.read(c.reference(out / "STOP_ENROLLMENT.json"))["receipt"])
    assert stop["resumeAutomatically"] is False and stop["protocol"] == pref
    assert "leave authorized production owner unchanged" in stop["scope"]


def test_mismatched_index_and_mutated_immutable_receipt_fail_closed(setup):
    out, _, pref, _, _, _ = setup
    a._put_index(out, "OUTCOMES.json", "revisions", {}, {"wrong": True}, "2026-09-20T00:00:00Z")
    with pytest.raises(ValueError, match="protocol binding"):
        a.monitor_and_assess(out, clock=lambda: "2026-09-20T00:00:00Z")
    bound = c.save_json(out, {"sample": True}, "sample.json")
    Path(bound["path"]).write_text('{"sample":false}')
    with pytest.raises(ValueError, match="Physical binding"):
        a.select_revision([bound], c.utc("2026-09-22T16:00:00Z"))


def test_pair_late_commit_and_support_drift_are_rejected(setup):
    out, p, pref, cref, pair, _ = setup
    commit = c.read(cref)
    commit["committedAtUtc"] = "2026-09-19T15:30:00Z"
    late = c.save_json(out, commit, "late-commit.json")
    with pytest.raises(ValueError, match="cutoff"):
        a._pair(pref, p, "99", late)
    pair["support"]["low_support"] = False
    commit = c.read(cref)
    commit["pair"] = c.save_json(out, pair, "invalid-support.json")
    invalid = c.save_json(out, commit, "invalid-support-commit.json")
    with pytest.raises(ValueError, match="low-support"):
        a._pair(pref, p, "99", invalid)


def test_frozen_protocol_rejects_changed_threshold_or_schedule():
    p = protocol()
    a._validate_protocol(p)
    p["adequacy"]["low_support"]["minimumGames"] = 39
    with pytest.raises(ValueError, match="adequacy"):
        a._validate_protocol(p)
    p = protocol()
    p["assessmentSchedule"][0]["atUtc"] = "2026-09-22T17:00:00Z"
    with pytest.raises(ValueError, match="schedule"):
        a._validate_protocol(p)
