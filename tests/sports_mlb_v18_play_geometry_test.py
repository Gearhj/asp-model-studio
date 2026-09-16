"""Focused tests for the V18 Play Geometry trace supplement.

They guard the boundary between what the registered evidence supports and what
the supplement may claim, and every conservation rule a movement template and
enriched path must satisfy.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from server.sports_current_statcast.mlb_v18_play_geometry import (
    COORDINATE_SYSTEM_DEFINITION,
    UNSUPPORTED_GEOMETRY_FIELDS,
    ConditionalSampler,
    PlayGeometryError,
    PlayGeometryModel,
    enumerate_legal_templates,
    legal_backoff_template,
    mask_bases,
    observed_runner_template,
    parse_event_text,
    template_is_legal,
    zone_to_point,
)
from server.sports_current_statcast.mlb_v18_play_geometry_trace import (
    RunnerRegistry,
    build_ball_trace,
    enrich_path,
    select_representative_paths,
    verify_v18_invariance,
)


# -- schema and coordinate system ------------------------------------------

def test_coordinate_system_declares_its_semantics() -> None:
    definition = COORDINATE_SYSTEM_DEFINITION
    assert definition["origin"] == "HOME_PLATE"
    assert definition["foulLines"] == {"leftFieldDegrees": -45.0, "rightFieldDegrees": 45.0}
    assert "feet" in definition["units"]
    for key in ("transformation", "clipping", "nullBehaviour"):
        assert definition[key]
    # No presentation detail leaks into the Model Studio artifact.
    payload = json.dumps(definition).lower()
    assert "#" not in payload and "px" not in payload.replace("expressed", "")


@pytest.mark.parametrize(
    "zone,depth,expected_sign",
    [("7", None, -1), ("9", None, 1), ("8", None, 0), ("5", "D", -1), ("3", "S", 1)],
)
def test_zone_transformation_is_deterministic_and_oriented(zone, depth, expected_sign) -> None:
    point = zone_to_point(zone, depth)
    assert point is not None
    assert point == zone_to_point(zone, depth)
    assert (0 if point["x"] == 0 else (1 if point["x"] > 0 else -1)) == expected_sign
    assert point["fairTerritory"] is True
    assert 0.02 <= point["depth"] <= 1.35


def test_an_unknown_zone_yields_no_point_rather_than_a_guess() -> None:
    assert zone_to_point(None, None) is None
    assert zone_to_point("99", None) is None


# -- Retrosheet parsing -----------------------------------------------------

@pytest.mark.parametrize("event_text", ["K", "K23", "W", "IW", "HP", "SB2", "WP.3-H"])
def test_non_contact_events_carry_no_geometry(event_text: str) -> None:
    parsed = parse_event_text(event_text)
    assert parsed.contact is False
    assert parsed.trajectory is None and parsed.zone is None


@pytest.mark.parametrize(
    "event_text,trajectory,zone,depth,foul",
    [
        ("43/G34", "GROUND_BALL", "34", None, False),
        ("9/F89", "FLY_BALL", "89", None, False),
        ("D9/L9LD", "LINE_DRIVE", "9", "D", False),
        ("5/P5F/FL", "POPUP", "5", None, True),
        ("HR/F7D.1-H", "FLY_BALL", "7", "D", False),
    ],
)
def test_batted_ball_geometry_is_read_from_the_event(
    event_text, trajectory, zone, depth, foul,
) -> None:
    parsed = parse_event_text(event_text)
    assert parsed.contact is True
    assert (parsed.trajectory, parsed.zone, parsed.depth, parsed.foul) == (
        trajectory, zone, depth, foul,
    )


# -- base masks and legality ------------------------------------------------

@pytest.mark.parametrize(
    "mask,bases",
    [(0, ()), (1, (1,)), (2, (2,)), (3, (1, 2)), (4, (3,)), (5, (1, 3)), (6, (2, 3)), (7, (1, 2, 3))],
)
def test_all_eight_base_masks_decode(mask: int, bases: tuple[int, ...]) -> None:
    assert mask_bases(mask) == bases


def test_a_template_may_not_let_a_runner_pass_another() -> None:
    passing = (("THIRD", "THIRD"), ("FIRST", "HOME"), ("BATTER_BOX", "OUT"))
    assert not template_is_legal(
        passing, mask_before=5, mask_after=4, runs=1, outs_added=1, outs_before=0)


def test_a_template_may_not_double_occupy_a_base() -> None:
    doubled = (("FIRST", "SECOND"), ("SECOND", "SECOND"), ("BATTER_BOX", "OUT"))
    assert not template_is_legal(
        doubled, mask_before=3, mask_after=2, runs=0, outs_added=1, outs_before=0)


def test_runs_and_outs_must_reconcile_exactly() -> None:
    template = (("THIRD", "HOME"), ("BATTER_BOX", "FIRST"))
    assert template_is_legal(
        template, mask_before=4, mask_after=1, runs=1, outs_added=0, outs_before=1)
    # The same template with the wrong declared run count is rejected.
    assert not template_is_legal(
        template, mask_before=4, mask_after=1, runs=0, outs_added=0, outs_before=1)
    assert not template_is_legal(
        template, mask_before=4, mask_after=1, runs=1, outs_added=1, outs_before=1)


def test_ending_occupancy_must_equal_the_persisted_mask() -> None:
    template = (("BATTER_BOX", "FIRST"),)
    assert template_is_legal(
        template, mask_before=0, mask_after=1, runs=0, outs_added=0, outs_before=0)
    assert not template_is_legal(
        template, mask_before=0, mask_after=2, runs=0, outs_added=0, outs_before=0)


def test_the_third_out_strands_survivors_instead_of_retiring_them() -> None:
    # Runner on first, batter retired for the third out: the inning ends with
    # the bases clear, and the runner is stranded rather than counted as an out.
    template = legal_backoff_template(
        mask_before=1, mask_after=0, runs=0, outs_added=1, outs_before=2)
    assert template == (("FIRST", "FIRST"), ("BATTER_BOX", "OUT"))
    assert sum(1 for _, destination in template if destination == "OUT") == 1


def test_a_home_run_clears_every_runner() -> None:
    template = legal_backoff_template(
        mask_before=7, mask_after=0, runs=4, outs_added=0, outs_before=0)
    assert template is not None
    assert all(destination == "HOME" for _, destination in template)
    assert len(template) == 4


def test_every_enumerated_template_is_legal_and_the_backoff_is_one_of_them() -> None:
    for mask_before in range(8):
        for mask_after in range(8):
            for runs in range(4):
                for outs_added in range(3):
                    for outs_before in (0, 2):
                        legal = enumerate_legal_templates(
                            mask_before=mask_before, mask_after=mask_after,
                            runs=runs, outs_added=outs_added, outs_before=outs_before)
                        for template in legal:
                            assert template_is_legal(
                                template, mask_before=mask_before, mask_after=mask_after,
                                runs=runs, outs_added=outs_added, outs_before=outs_before)
                        backoff = legal_backoff_template(
                            mask_before=mask_before, mask_after=mask_after,
                            runs=runs, outs_added=outs_added, outs_before=outs_before)
                        assert (backoff is None) == (not legal)
                        if backoff is not None:
                            assert backoff in legal


# -- observed template recovery --------------------------------------------

def test_an_observed_template_is_recovered_from_registered_runner_ids() -> None:
    row = {
        "base_mask_before": 4, "base_mask_after": 1, "runs_scored": 1,
        "outs_before": 1, "outs_after": 1, "batter_id": "B",
        "runner_on_third_before": "R3",
        "runner_on_first_after": "B",
    }
    assert observed_runner_template(row) == (("THIRD", "HOME"), ("BATTER_BOX", "FIRST"))


def test_inconsistent_runner_identifiers_yield_no_template() -> None:
    # The declared mask says first is occupied but no identifier is recorded.
    row = {
        "base_mask_before": 1, "base_mask_after": 0, "runs_scored": 0,
        "outs_before": 0, "outs_after": 1, "batter_id": "B",
    }
    assert observed_runner_template(row) is None


# -- geometry sampling ------------------------------------------------------

def _fitted_model() -> PlayGeometryModel:
    model = PlayGeometryModel(fold_id="TEST")
    rows = []
    for index in range(200):
        rows.append({
            "pa_outcome": "SINGLE", "event_text": "S7/L7", "park_id": "P1",
            "base_mask_before": 0, "base_mask_after": 1, "runs_scored": 0,
            "outs_before": 0, "outs_after": 0, "batter_id": f"B{index}",
            "runner_on_first_after": f"B{index}",
        })
        rows.append({
            "pa_outcome": "STRIKEOUT", "event_text": "K", "park_id": "P1",
            "base_mask_before": 0, "base_mask_after": 0, "runs_scored": 0,
            "outs_before": 0, "outs_after": 1, "batter_id": f"S{index}",
        })
    return model.fit(rows)


def test_non_contact_outcomes_receive_null_geometry_and_no_ball_trace() -> None:
    model = _fitted_model()
    for outcome in ("STRIKEOUT", "WALK_HBP_CI"):
        geometry = model.sample_geometry(outcome=outcome, park="P1", seed=("g", 1))
        assert geometry["contactOccurred"] is False
        assert geometry["battedBallType"] is None
        assert geometry["point"] is None
        assert build_ball_trace(geometry) is None


def test_unsupported_geometry_fields_are_always_null() -> None:
    model = _fitted_model()
    geometry = model.sample_geometry(outcome="SINGLE", park="P1", seed=("g", 1))
    assert geometry["contactOccurred"] is True
    for name in UNSUPPORTED_GEOMETRY_FIELDS:
        assert geometry[name] is None, f"{name} must never be fabricated"


def test_contact_geometry_is_compatible_and_deterministic() -> None:
    model = _fitted_model()
    first = model.sample_geometry(outcome="SINGLE", park="P1", seed=("g", 7))
    second = model.sample_geometry(outcome="SINGLE", park="P1", seed=("g", 7))
    assert first == second
    assert first["battedBallType"] == "LINE_DRIVE"
    trace = build_ball_trace(first)
    assert trace is not None
    assert trace["start"] == {"x": 0.0, "y": 0.0}
    assert "NOT_A_MEASURED_FLIGHT_PATH" in trace["semantics"]


def test_a_sampler_without_support_reports_no_support() -> None:
    sampler = ConditionalSampler(minimum_support=10)
    sampler.fit("outcome", ("SINGLE",), "value")
    value, level, support = sampler.sample([("outcome", ("SINGLE",))], seed=1)
    assert (value, level, support) == (None, "NO_SUPPORT", 0)


def test_an_impossible_transition_raises_rather_than_inventing_a_template() -> None:
    model = _fitted_model()
    with pytest.raises(PlayGeometryError):
        model.sample_runner_template(
            outcome="SINGLE", mask_before=0, outs_before=0, runs=5,
            mask_after=0, outs_added=0, batted_ball_type=None, seed=1)


# -- runner identity continuity --------------------------------------------

def test_runner_identities_persist_across_plate_appearances() -> None:
    registry = RunnerRegistry("game", 0)
    first = registry.apply((("BATTER_BOX", "FIRST"),))
    runner_id = first[0]["anonymousRunnerId"]
    second = registry.apply((("FIRST", "SECOND"), ("BATTER_BOX", "FIRST")))
    advanced = next(move for move in second if move["from"] == "FIRST")
    assert advanced["anonymousRunnerId"] == runner_id
    assert registry.mask() == 3


def test_a_half_inning_change_clears_the_bases() -> None:
    registry = RunnerRegistry("game", 0)
    registry.apply((("BATTER_BOX", "FIRST"),))
    assert registry.mask() == 1
    registry.reset_half_inning()
    assert registry.mask() == 0


def test_identities_are_deterministic_under_replay() -> None:
    def run() -> list[str]:
        registry = RunnerRegistry("game", 3)
        moves = registry.apply((("BATTER_BOX", "FIRST"),))
        moves += registry.apply((("FIRST", "THIRD"), ("BATTER_BOX", "FIRST")))
        return [move["anonymousRunnerId"] for move in moves]

    assert run() == run()


# -- path enrichment and invariance ----------------------------------------

def _path() -> list[dict]:
    return [
        {"pa": 1, "inning": 1, "half": "TOP", "battingOrderPosition": 1,
         "pitcherState": "STARTER", "pitchingChange": False, "outcome": "STRIKEOUT",
         "outsBefore": 0, "outsAfter": 1, "baseMaskBefore": 0, "baseMaskAfter": 0,
         "runsScored": 0, "homeScoreAfter": 0, "awayScoreAfter": 0},
        {"pa": 2, "inning": 1, "half": "TOP", "battingOrderPosition": 2,
         "pitcherState": "STARTER", "pitchingChange": False, "outcome": "SINGLE",
         "outsBefore": 1, "outsAfter": 1, "baseMaskBefore": 0, "baseMaskAfter": 1,
         "runsScored": 0, "homeScoreAfter": 0, "awayScoreAfter": 0},
        {"pa": 3, "inning": 1, "half": "TOP", "battingOrderPosition": 3,
         "pitcherState": "STARTER", "pitchingChange": False, "outcome": "STRIKEOUT",
         "outsBefore": 1, "outsAfter": 2, "baseMaskBefore": 1, "baseMaskAfter": 1,
         "runsScored": 0, "homeScoreAfter": 0, "awayScoreAfter": 0},
    ]


def test_enrichment_preserves_every_persisted_v18_field() -> None:
    model = _fitted_model()
    path = _path()
    enriched = enrich_path(model=model, path=path, park="P1", path_index=0, game_id="G")
    forecast = {"traces": [path], "meanTotalRuns": 8.0, "meanRunDifferential": 0.0}
    invariance = verify_v18_invariance(forecast, [enriched])
    assert invariance["allInvariantsHeld"] is True
    for before, after in zip(path, enriched["events"]):
        for name, value in before.items():
            assert after[name] == value


def test_enrichment_reconciles_state_on_every_plate_appearance() -> None:
    model = _fitted_model()
    enriched = enrich_path(model=model, path=_path(), park="P1", path_index=0, game_id="G")
    for event in enriched["events"]:
        movements = event["runnerMovements"]
        scored = sum(1 for move in movements if move["scored"])
        outs = sum(1 for move in movements if move["out"])
        assert scored == event["runsScored"]
        assert outs == event["outsAfter"] - event["outsBefore"]
        destinations = [move["to"] for move in movements if move["to"] in {"FIRST", "SECOND", "THIRD"}]
        assert len(destinations) == len(set(destinations))
        # Presentation sequencing only; never presented as measured timing.
        for move in movements:
            assert 0.0 <= move["startFraction"] <= move["endFraction"] <= 1.0


def test_enrichment_is_deterministic_under_replay() -> None:
    model = _fitted_model()
    first = enrich_path(model=model, path=_path(), park="P1", path_index=0, game_id="G")
    second = enrich_path(model=model, path=_path(), park="P1", path_index=0, game_id="G")
    assert first["geometryDigest"] == second["geometryDigest"]
    assert first["pathDigest"] == second["pathDigest"]


def test_a_single_retained_path_never_claims_six_representatives() -> None:
    model = _fitted_model()
    enriched = enrich_path(model=model, path=_path(), park="P1", path_index=0, game_id="G")
    selection = select_representative_paths([enriched], {"meanTotalRuns": 8.0, "meanRunDifferential": 0.0})
    assert selection["selectionDegenerate"] is True
    assert selection["satisfied"] == {}
    assert len(selection["unavailable"]) == 6


# -- published artifact -----------------------------------------------------

def test_the_published_supplement_verifies_and_fails_closed() -> None:
    from pathlib import Path

    latest = Path("outputs/mlb-v18-play-geometry/latest.json")
    if not latest.is_file():
        pytest.skip("supplement has not been built in this checkout")
    target = Path(json.loads(latest.read_text(encoding="utf-8"))["path"])
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    supplement = json.loads((target / "play-geometry-supplement.json").read_text(encoding="utf-8"))
    handoff = json.loads((target / "aisp-play-geometry-handoff.json").read_text(encoding="utf-8"))

    canonical = json.dumps(supplement, sort_keys=True, separators=(",", ":"), default=str).encode()
    assert hashlib.sha256(canonical).hexdigest() == manifest["supplementSha256"]
    assert handoff["supplementSha256"] == manifest["supplementSha256"]

    for artifact in manifest["artifacts"]:
        payload = (target / artifact["relativePath"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]

    # Governance flags must be fail-closed in both the supplement and handoff.
    for document in (supplement, handoff):
        assert document["wageringAuthority"] is False
        assert document["promotionStatus"] == "NOT_PROMOTED"
        assert document["executionAllowedInAISP"] is False
        assert document["displayAuthority"] == "RESEARCH_SHADOW_PLAY_GEOMETRY"
    assert supplement["finalOotOpened"] is False
    assert supplement["parentBundleSha256"] == handoff["parentBundleSha256"]
    assert supplement["v18Invariance"]["allInvariantsHeld"] is True
    assert "failClosed" in handoff["rendering"]
