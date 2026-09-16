"""Pure orchestration and score-gate checks; no fitting or NBA performance."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from server.sports_nba_gen1 import assessment as a
from server.sports_nba_gen1 import runner as r
from server.sports_nba_gen1.authority import NbaAdmissionError


def test_context_verifies_bound_source_values_before_index(monkeypatch):
    sources = {"one.py": {"path": "UNIT_ONLY_ONE", "sha256": "0" * 64},
               "two.py": {"path": "UNIT_ONLY_TWO", "sha256": "1" * 64}}
    source_index = {"path": "UNIT_ONLY_INDEX"}
    plan = {"outcomesOpened": False,
            "scope": "NBA_REGULAR_SEASON_FULL_GAME_INCLUDING_OVERTIME",
            "numericalSources": sources, "featureContract": r.feature_contract(),
            "sourceIndex": source_index}
    seen = []
    monkeypatch.setattr(r, "load_pointer", lambda *_: (plan, {"unitOnly": True}))
    monkeypatch.setattr(r, "numerical_source_bindings", lambda: sources)

    def check(bound):
        assert isinstance(bound, dict)
        seen.append(bound)
        return json.dumps({"unitOnly": True}).encode()

    monkeypatch.setattr(r, "verified_bytes", check)
    _, _, index = r.context("UNIT_NO_FILES")
    assert seen == [*sources.values(), source_index]
    assert index == {"unitOnly": True}
    monkeypatch.setattr(r, "numerical_source_bindings", lambda: {
        **sources, "one.py": {"path": "UNIT_ONLY_CHANGED", "sha256": "2" * 64}})
    with pytest.raises(NbaAdmissionError, match="Numerical implementation changed"):
        r.context("UNIT_NO_FILES")


def test_fit_labels_obey_availability_revision_and_prior_season():
    cutoff = "2024-10-01T00:00:00Z"
    rows = [
        dict(game_id="UNIT_A", season=2023, source_revision=1,
             source_available_at_utc="2024-09-01T00:00:00Z", status="FINAL"),
        dict(game_id="UNIT_A", season=2023, source_revision=2,
             source_available_at_utc=cutoff, status="FINAL"),
        dict(game_id="UNIT_B", season=2022, source_revision=1,
             source_available_at_utc="2023-04-01T00:00:00Z", status="FINAL"),
        dict(game_id="UNIT_FUTURE", season=2024, source_revision=1,
             source_available_at_utc="2024-09-01T00:00:00Z", status="FINAL"),
        dict(game_id="UNIT_NOT_FINAL", season=2023, source_revision=1,
             source_available_at_utc="2024-09-01T00:00:00Z", status="POSTPONED"),
    ]
    games = pd.DataFrame(rows)
    features = pd.DataFrame({"game_id": ["UNIT_B", "UNIT_FUTURE", "UNIT_A"], "x": [2, 99, 1]})
    x, labels = r.fitting_rows(games, features, cutoff, 2024, minimum=2)
    assert set(labels.game_id) == {"UNIT_A", "UNIT_B"}
    assert labels.set_index("game_id").loc["UNIT_A", "source_revision"] == 1
    assert x.game_id.tolist() == labels.game_id.tolist()
    assert dict(zip(x.game_id, x.x)) == {"UNIT_A": 1, "UNIT_B": 2}
    with pytest.raises(NbaAdmissionError, match="Insufficient earlier"):
        r.fitting_rows(games, features, cutoff, 2024, minimum=3)


def test_overtime_evidence_matches_training_revision_and_clock():
    labels = pd.DataFrame({"game_id": ["UNIT_A"], "source_revision": [1]})
    periods = pd.DataFrame([
        {"game_id": "UNIT_A", "source_revision": 1, "source_available_at_utc": "2024-04-01T00:00:00Z"},
        {"game_id": "UNIT_A", "source_revision": 2, "source_available_at_utc": "2024-04-02T00:00:00Z"},
        {"game_id": "UNIT_B", "source_revision": 1, "source_available_at_utc": "2024-04-01T00:00:00Z"},
        {"game_id": "UNIT_A", "source_revision": 1, "source_available_at_utc": "2024-10-01T00:00:00Z"},
    ])
    chosen = r.ot_training(periods, labels, "2024-10-01T00:00:00Z")
    assert chosen.index.tolist() == [0]
    empty = r.ot_training(periods.iloc[:0], labels, "2024-10-01T00:00:00Z")
    assert len(empty) == 0 and list(empty.columns) == list(periods.columns)


def test_oot_requires_selection_before_any_outcome_load(tmp_path, monkeypatch):
    plan = {"roles": {"development": [2020, 2021, 2022], "validation": [2023], "oot": [2024]}}
    monkeypatch.setattr(r, "context", lambda *_: (plan, {}, {}))
    calls = []

    def pointer(_, name):
        calls.append(name)
        if name == "selection":
            raise NbaAdmissionError("Required earlier phase missing: selection")
        assert name == "development"
        return {}, {}

    monkeypatch.setattr(r, "load_pointer", pointer)
    monkeypatch.setattr(r, "load_seasons", lambda *_: pytest.fail("Outcome access preceded locked selection"))
    with pytest.raises(NbaAdmissionError, match="selection"):
        r.season_assessment(tmp_path, "oot")
    assert calls == ["development", "selection"]
    assert not (tmp_path / "oot-access.json").exists()


def test_oot_access_marker_prevents_silent_second_open(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "context", lambda *_: ({}, {}, {}))
    monkeypatch.setattr(r, "load_pointer", lambda _, name: (
        {"ootOpened": False, "lockedFamily": "league"} if name == "selection" else {}, {}))
    (tmp_path / "oot-access.json").write_text("UNIT_ONLY_PREVIOUS_OPEN", encoding="utf-8")
    monkeypatch.setattr(r, "load_seasons", lambda *_: pytest.fail("Repeated OOT access"))
    with pytest.raises(NbaAdmissionError, match="already opened"):
        r.season_assessment(tmp_path, "oot")


def _score_rows():
    dates = pd.date_range("2024-01-01", periods=16, freq="7D", tz="UTC")
    frame = pd.DataFrame({"game_id": [f"UNIT_{i}" for i in range(16)],
                          "scheduled_tipoff_utc": dates, "pHome": .6, "yHome": [0, 1] * 8})
    for column in a.SCORE_COLUMNS:
        frame[column] = 10.0 if column != "binaryBrier" else .2
    for marginal in ("home", "away", "total", "margin"):
        for level in ("0.5", "0.8", "0.9"):
            frame[marginal + "Coverage" + level] = float(level)
            frame[marginal + "Width" + level] = 20.0
    return frame


def test_game_block_intervals_and_winner_guardrail_are_independent_of_draw_count():
    base = _score_rows()
    candidate = base.copy()
    candidate["energy"] -= 1.0
    candidate["logLoss"] += .02
    # These are arbitrary unit values, not generated forecasts or NBA scores.
    plan = {"gate": {"minimumRelativeEnergyImprovement": .01,
                     "maximumLogLossDeterioration": .005, "maximumBrierDeterioration": .002,
                     "maximumMarginalCrpsRelativeDeterioration": .01,
                     "maximumAbsoluteCoverageDeterioration": .02,
                     "minimumWidthRatio": .9, "maximumWidthRatio": 1.2}}
    result = a.advancement_gate(base, candidate, plan)
    assert result["checks"]["energyEffect"] and result["checks"]["pairedEnergy"]
    assert not result["checks"]["logLoss"] and not result["advance"]
    interval = result["energyInterval"]
    assert interval["games"] == interval["calendarWeekBlocks"] == 16
    assert interval["lower95"] == interval["upper95"] == -1.0
    with pytest.raises(ValueError, match="Same game identities"):
        a.paired_interval(base, candidate.iloc[::-1], "energy")
    small = a.paired_interval(base.iloc[:7], candidate.iloc[:7], "energy")
    assert small["status"] == "INSUFFICIENT_OBSERVED_BLOCKS"
    assert small["lower95"] is small["upper95"] is None


def test_residual_rows_preserve_target_identity_and_chronological_label_clock():
    targets = pd.DataFrame([{"game_id": "UNIT_ONLY", "season": 2023,
                             "scheduled_tipoff_utc": "2023-11-01T00:00:00Z",
                             "source_available_at_utc": "2023-11-02T00:00:00Z",
                             "source_revision": 2, "home_score": 110, "away_score": 100}])
    result = r.residual_frame(targets, np.array([[105., 99.]]), "2023-10-01T00:00:00Z", "league")
    assert result.game_id.tolist() == ["UNIT_ONLY"]
    assert result.source_revision.tolist() == [2]
    assert result.residual_home.tolist() == [5.0]
    assert result.residual_away.tolist() == [1.0]
    assert result.residual_kind.tolist() == ["SEASON_FORWARD_OUT_OF_FOLD"]
    assert result.source_available_at_utc.tolist() == targets.source_available_at_utc.tolist()


def test_evaluation_donor_gate_removes_same_season_and_unavailable_revisions(monkeypatch):
    targets = pd.DataFrame([{"game_id": "UNIT_TARGET", "season": 2024,
                             "scheduled_tipoff_utc": "2024-11-01T00:00:00Z"}])
    donors = pd.DataFrame([
        {"game_id": "UNIT_A", "season": 2023, "source_available_at_utc": "2024-01-01T00:00:00Z",
         "residual_home": 1., "residual_away": 2.},
        {"game_id": "UNIT_B", "season": 2022, "source_available_at_utc": "2024-01-01T00:00:00Z",
         "residual_home": 3., "residual_away": 4.},
        {"game_id": "UNIT_LATE", "season": 2023, "source_available_at_utc": "2024-11-01T00:00:00Z",
         "residual_home": 99., "residual_away": 99.},
        {"game_id": "UNIT_CURRENT", "season": 2024, "source_available_at_utc": "2024-10-01T00:00:00Z",
         "residual_home": 88., "residual_away": 88.},
    ])
    donors["residual_kind"] = "SEASON_FORWARD_OUT_OF_FOLD"
    overtime = pd.DataFrame({"home_points": [2], "away_points": [1]})
    plan = {"minimumOvertimePeriods": 1, "minimumResidualDonors": 2, "draws": 10000, "seed": 1}

    class UnitGateReached(Exception):
        pass

    def stop_before_simulation(home, away, bank, **kwargs):
        np.testing.assert_array_equal(bank, [[1., 2.], [3., 4.]])
        assert kwargs["draws"] == 10000
        raise UnitGateReached

    monkeypatch.setattr(r, "simulate", stop_before_simulation)
    with pytest.raises(UnitGateReached):
        r.evaluate("UNIT_NO_FILES", "UNIT_ONLY", targets, np.array([[100., 99.]]),
                   donors, overtime, plan, pd.DataFrame(), [])
    donors.loc[0, "residual_kind"] = "IN_SAMPLE"
    with pytest.raises(NbaAdmissionError, match="In-sample residuals"):
        r.evaluate("UNIT_NO_FILES", "UNIT_ONLY", targets, np.array([[100., 99.]]),
                   donors, overtime, plan, pd.DataFrame(), [])
