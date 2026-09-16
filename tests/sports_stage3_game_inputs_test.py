"""Hermetic contracts for Stage 3 governed pregame input materialization."""

from __future__ import annotations

import pytest

from server.sports_current_statcast import stage3_game_inputs as gi


def feature_order() -> tuple[str, ...]:
    frozen = ["batter_identity", "pitcher_identity", *[f"pregame_{i:03d}" for i in range(227)]]
    return tuple(
        [
            frozen[0],
            gi.SIMULATION_STATE_FEATURES[0],
            frozen[1],
            gi.SIMULATION_STATE_FEATURES[1],
            *frozen[2:80],
            gi.SIMULATION_STATE_FEATURES[2],
            *frozen[80:160],
            gi.SIMULATION_STATE_FEATURES[3],
            *frozen[160:],
            gi.SIMULATION_STATE_FEATURES[4],
        ]
    )


def evidence(*, lineup_status: str = "CONFIRMED", receipt: str = "2026-05-10T15:20:00Z"):
    features = feature_order()
    frozen = tuple(name for name in features if name not in gi.SIMULATION_STATE_FEATURES)
    away = [
        {"battingOrderSlot": slot, "canonicalPlayerId": f"player:away:{slot}"}
        for slot in range(1, 10)
    ]
    home = [
        {"battingOrderSlot": slot, "canonicalPlayerId": f"player:home:{slot}"}
        for slot in range(1, 10)
    ]
    rows = []
    for side, lineup, pitcher in (
        ("AWAY", away, "player:home:starter"),
        ("HOME", home, "player:away:starter"),
    ):
        for entry in lineup:
            predictors = {
                name: (
                    entry["canonicalPlayerId"]
                    if name == "batter_identity"
                    else pitcher
                    if name == "pitcher_identity"
                    else float(entry["battingOrderSlot"])
                )
                for name in frozen
            }
            rows.append(
                {
                    "battingSide": side,
                    "battingOrderSlot": entry["battingOrderSlot"],
                    "batterCanonicalPlayerId": entry["canonicalPlayerId"],
                    "pitcherCanonicalPlayerId": pitcher,
                    "predictors": predictors,
                }
            )
    return {
        "canonicalGameId": "mlb:game:2026-05-10:a-h",
        "canonicalAwayTeamId": "mlb:team:away",
        "canonicalHomeTeamId": "mlb:team:home",
        "scheduledFirstPitch": "2026-05-10T17:00:00Z",
        "sourceCutoff": "2026-05-10T15:00:00Z",
        "observationTimestamp": "2026-05-10T15:10:00Z",
        "receiptTimestamp": receipt,
        "lineupEvidence": {
            "status": lineup_status,
            "authorityId": "lineups:v1",
            "sourceId": "governed:lineups",
            "checksumSha256": "a" * 64,
            "away": away,
            "home": home,
        },
        "starterEvidence": {
            "status": "ANNOUNCED_CONFIRMED",
            "authorityId": "starters:v1",
            "sourceId": "governed:starters",
            "checksumSha256": "b" * 64,
            "away": {"canonicalPlayerId": "player:away:starter"},
            "home": {"canonicalPlayerId": "player:home:starter"},
        },
        "featureEvidence": {
            "status": "VERIFIED",
            "authorityId": "features:v1",
            "sourceId": "governed:pregame-features",
            "checksumSha256": "c" * 64,
            "templates": rows,
        },
    }


def test_materializes_exact_eighteen_templates_and_freezes_229_predictors():
    inputs = gi.build_stage3_game_inputs(evidence(), ordered_features=feature_order())

    assert len(inputs.ordered_features) == 234
    assert len(inputs.non_simulation_features) == 229
    assert len(inputs.templates) == 18
    assert tuple(row.batting_side for row in inputs.templates) == ("AWAY",) * 9 + ("HOME",) * 9
    assert tuple(row.batting_order_slot for row in inputs.templates) == tuple(range(1, 10)) * 2
    assert inputs.home_starter_id == "player:home:starter"
    assert inputs.away_starter_id == "player:away:starter"
    assert len(inputs.feature_vector_sha256) == 64
    assert inputs.record()["targetGameOutcomesRead"] is False
    assert inputs.record()["actualSubstitutionsUsed"] is False


def test_simulated_state_must_not_come_from_target_game_evidence():
    raw = evidence()
    raw["featureEvidence"]["templates"][0]["predictors"]["context_inning"] = 1

    with pytest.raises(gi.Stage3GameInputError) as raised:
        gi.build_stage3_game_inputs(raw, ordered_features=feature_order())
    assert raised.value.code == "ACTUAL_TARGET_GAME_STATE_PROHIBITED"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda raw: raw.update(receiptTimestamp="2026-05-10T17:00:00Z"), "PREGAME_EVIDENCE_LATE"),
        (
            lambda raw: raw["lineupEvidence"].update(status="PROJECTED"),
            "GOVERNED_PREGAME_LINEUP_AUTHORITY_UNAVAILABLE",
        ),
        (
            lambda raw: raw["starterEvidence"].pop("home"),
            "PREGAME_EVIDENCE_FIELD_MISSING",
        ),
        (
            lambda raw: raw["featureEvidence"]["templates"].pop(),
            "PREGAME_FEATURE_TEMPLATE_COUNT_INVALID",
        ),
        (
            lambda raw: raw["lineupEvidence"].update(
                observationTimestamp="2026-05-10T17:01:00Z"
            ),
            "GOVERNED_PREGAME_LINEUP_EVIDENCE_LATE",
        ),
        (
            lambda raw: raw["featureEvidence"]["templates"][0].update(
                actualOutcome="HOME_RUN"
            ),
            "TARGET_GAME_RESULT_OR_PARTICIPANT_EVIDENCE_PROHIBITED",
        ),
    ],
)
def test_missing_projected_or_late_evidence_fails_closed(mutation, code):
    raw = evidence()
    mutation(raw)
    prepared = gi.prepare_stage3_game_inputs(raw, ordered_features=feature_order())

    assert prepared.game_inputs is None
    assert prepared.readiness.scoreable is False
    assert prepared.readiness.blocked_reasons[0]["code"] == code


def test_only_registered_missingness_can_authorize_a_missing_value():
    raw = evidence()
    raw["featureEvidence"]["templates"][0]["predictors"]["pregame_000"] = None

    with pytest.raises(gi.Stage3GameInputError) as raised:
        gi.build_stage3_game_inputs(raw, ordered_features=feature_order())
    assert raised.value.code == "PREGAME_REQUIRED_FEATURE_MISSING"

    inputs = gi.build_stage3_game_inputs(
        raw,
        ordered_features=feature_order(),
        authorized_missing_predictors=("pregame_000",),
    )
    assert inputs.templates[0].predictor_mapping()["pregame_000"] is None


def test_absent_inventory_is_honestly_blocked_without_fabricating_a_game():
    prepared = gi.prepare_stage3_game_inputs(None, ordered_features=feature_order())
    readiness = prepared.readiness.record()

    assert prepared.game_inputs is None
    assert readiness["gameId"] is None
    assert readiness["scoreable"] is False
    assert [reason["code"] for reason in readiness["blockedReasons"]] == [
        "GOVERNED_PREGAME_GAME_AUTHORITY_UNAVAILABLE",
        "GOVERNED_PREGAME_LINEUP_AUTHORITY_UNAVAILABLE",
        "GOVERNED_PREGAME_STARTER_AUTHORITY_UNAVAILABLE",
    ]
