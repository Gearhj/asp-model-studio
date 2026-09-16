from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.build_prospective_cross_game_evidence_fixtures import (
    availability_fixture,
    post_outcome_fixture,
    pre_outcome_fixture,
    successor_fixture,
)
from server.sports_shared.prospective_cross_game_evidence import (
    DEPENDENCY_KEYS,
    FROZEN_DESIGN_SHA256,
    FROZEN_RESULTS_SHA256,
    FROZEN_THRESHOLDS,
    ProspectiveEvidenceError,
    append_revision,
    classify_pair,
    evidence_sidecar_binding,
    producer_integration_matrix,
    readiness_state,
    sha256_identity,
    unordered_pair_id,
    validate_post_outcome,
    validate_pre_outcome,
    validate_availability_receipt,
    validate_readiness_record,
)


def error_code(error: pytest.ExceptionInfo[ProspectiveEvidenceError]) -> str:
    return error.value.code


def test_valid_envelope_keeps_unknown_and_missing_downstream_times() -> None:
    original = pre_outcome_fixture()
    validated = validate_pre_outcome(original)
    assert validated["timing"]["exchangeDiscoveredAt"] is None
    assert validated["timing"]["consumerAcknowledgedAt"] is None
    assert validated["timing"]["decisionWindowAvailableAt"] is None
    assert set(validated["dependencies"]) == set(DEPENDENCY_KEYS)
    assert all(item["state"] == "UNKNOWN" for item in validated["dependencies"].values())


def test_dependency_observation_cannot_follow_capture() -> None:
    record = pre_outcome_fixture()
    record["dependencies"]["SHARED_VENUE"]["observedAt"] = "2026-09-19T18:31:00-04:00"
    with pytest.raises(ProspectiveEvidenceError) as error:
        validate_pre_outcome(record)
    assert error_code(error) == "DEPENDENCY_TIME_INVALID"


@pytest.mark.parametrize("field", ["sourceCutoff", "forecastCreatedAt", "producerPublishedAt"])
def test_required_timestamps_are_timezone_aware(field: str) -> None:
    record = pre_outcome_fixture()
    record["timing"][field] = "2026-09-19T18:00:00"
    with pytest.raises(ProspectiveEvidenceError) as error:
        validate_pre_outcome(record)
    assert error_code(error) == "TIMESTAMP_TIMEZONE_REQUIRED"


def test_missing_required_timestamp_is_not_inferred() -> None:
    record = pre_outcome_fixture()
    del record["timing"]["producerPublishedAt"]
    with pytest.raises(ProspectiveEvidenceError) as error:
        validate_pre_outcome(record)
    assert error_code(error) == "FIELDS_INVALID"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("sourceCutoff", "2026-09-19T18:11:00-04:00", "PREGAME_CHRONOLOGY_INVALID"),
        ("producerPublishedAt", "2026-09-19T18:09:00-04:00", "PREGAME_CHRONOLOGY_INVALID"),
        ("producerPublishedAt", "2026-09-20T13:01:00-04:00", "PREGAME_CHRONOLOGY_INVALID"),
    ],
)
def test_pregame_chronology_fails_closed(field: str, value: str, code: str) -> None:
    record = pre_outcome_fixture()
    record["timing"][field] = value
    with pytest.raises(ProspectiveEvidenceError) as error:
        validate_pre_outcome(record)
    assert error_code(error) == code


def test_package_and_population_hashes_bind_exactly() -> None:
    record = pre_outcome_fixture()
    record["integrity"]["packageSha256"] = "ABC"
    with pytest.raises(ProspectiveEvidenceError) as error:
        validate_pre_outcome(record)
    assert error_code(error) == "SHA256_INVALID"
    point = pre_outcome_fixture()
    point["integrity"] = {"packageSha256": "1" * 64, "populationSha256": None, "drawCount": 5000}
    with pytest.raises(ProspectiveEvidenceError) as error:
        validate_pre_outcome(point)
    assert error_code(error) == "POPULATION_BINDING_INVALID"


def test_revisions_append_and_bind_exact_predecessor() -> None:
    first = pre_outcome_fixture()
    frozen_first = deepcopy(first)
    second = successor_fixture(first)
    chain = append_revision([first], second)
    assert len(chain) == 2
    assert first == frozen_first
    assert chain[1]["supersedes"]["evidenceSha256"] == sha256_identity(first)
    duplicate = deepcopy(second)
    duplicate["forecastRevision"] = 1
    duplicate["supersedes"] = None
    with pytest.raises(ProspectiveEvidenceError):
        append_revision([first], duplicate)


def test_post_outcome_cannot_mutate_or_rebind_pre_outcome() -> None:
    pre = pre_outcome_fixture()
    post = post_outcome_fixture(pre)
    assert validate_post_outcome(post, pre) == post
    mutated = deepcopy(pre)
    mutated["limitations"].append("retrospective mutation")
    with pytest.raises(ProspectiveEvidenceError) as error:
        validate_post_outcome(post, mutated)
    assert error_code(error) == "PRE_OUTCOME_BINDING_MISMATCH"
    post["frozenGateBinding"]["designSha256"] = "8" * 64
    with pytest.raises(ProspectiveEvidenceError) as error:
        validate_post_outcome(post, pre)
    assert error_code(error) == "FROZEN_GATE_BINDING_INVALID"


def test_downstream_availability_appends_without_mutating_envelope() -> None:
    pre = pre_outcome_fixture()
    frozen = deepcopy(pre)
    receipt = availability_fixture(pre)
    assert validate_availability_receipt(receipt, pre) == receipt
    assert pre == frozen
    late = deepcopy(receipt)
    late["observedAt"] = "2026-09-20T13:01:00-04:00"
    late["capturedAt"] = "2026-09-20T13:02:00-04:00"
    late["pregameAvailable"] = True
    with pytest.raises(ProspectiveEvidenceError) as error:
        validate_availability_receipt(late, pre)
    assert error_code(error) == "PREGAME_AVAILABILITY_INVALID"
    late["pregameAvailable"] = False
    assert validate_availability_receipt(late, pre)["pregameAvailable"] is False


def test_pair_identity_is_unordered_and_same_game_is_rejected() -> None:
    assert unordered_pair_id("game-b", "game-a") == "game-a|game-b"
    with pytest.raises(ProspectiveEvidenceError) as error:
        unordered_pair_id("game-a", "game-a")
    assert error_code(error) == "SAME_GAME_PAIR_FORBIDDEN"


def test_shared_team_mlb_pair_is_classified_as_doubleheader() -> None:
    first = pre_outcome_fixture(game_id="mlb-a", participants=("TEAM-X", "TEAM-Y"))
    second = pre_outcome_fixture(game_id="mlb-b", forecast_id="forecast-b", participants=("TEAM-X", "TEAM-Z"))
    for record in (first, second):
        record["sport"] = "MLB"
    pair = classify_pair(first, second)
    assert pair["sharedParticipant"]["state"] == "CONFIRMED"
    assert pair["doubleheader"]["state"] == "CONFIRMED"
    assert pair["eligibleForUnrelatedCategory"] is False


def readiness_rows() -> list[dict[str, object]]:
    rows = []
    for index in range(1000):
        date_index = index % 50
        left = f"game-{index * 2:04d}"
        right = f"game-{index * 2 + 1:04d}"
        rows.append({
            "pairId": unordered_pair_id(left, right),
            "gameIds": sorted([left, right]),
            "slateDate": f"2026-{1 + date_index // 28:02d}-{1 + date_index % 28:02d}",
            "probabilityBand": "0.20-0.30" if index < 500 else "0.30-0.40",
            "eligible": True,
        })
    return rows


def test_readiness_counts_reconcile_without_executing_assessment() -> None:
    state = readiness_state("UNRELATED_REGULAR", readiness_rows())
    assert state["coverage"]["games"] == 2000
    assert state["coverage"]["dates"] == 50
    assert state["coverage"]["uniqueUnorderedPairs"] == 1000
    assert state["coverage"]["supportedReliabilityBands"] == 2
    assert state["readiness"] == "READY_FOR_FROZEN_ASSESSMENT"
    assert state["assessmentAuthorized"] is False
    assert state["assessmentExecuted"] is False
    assert state["thresholds"] == FROZEN_THRESHOLDS
    assert state["frozenGateBinding"] == {
        "designSha256": FROZEN_DESIGN_SHA256,
        "resultsSha256": FROZEN_RESULTS_SHA256,
    }
    assert validate_readiness_record(state) == state
    changed = deepcopy(state)
    changed["thresholds"]["minimumGames"] = 499
    with pytest.raises(ProspectiveEvidenceError) as error:
        validate_readiness_record(changed)
    assert error_code(error) == "FROZEN_THRESHOLDS_INVALID"


def test_duplicate_pair_is_rejected() -> None:
    row = readiness_rows()[0]
    with pytest.raises(ProspectiveEvidenceError) as error:
        readiness_state("X", [row, deepcopy(row)])
    assert error_code(error) == "PAIR_DUPLICATED"


def test_sidecar_is_additive_and_all_sport_adapters_are_inactive_descriptors() -> None:
    binding = evidence_sidecar_binding(pre_outcome_fixture())
    assert binding["existingPackageMutation"] is False
    assert binding["discoveryUpdate"] is False
    assert binding["activationState"] == "INACTIVE_NOT_PUBLISHED"
    adapters = producer_integration_matrix()
    assert set(adapters) == {"MLB", "NFL", "NBA", "CFB", "MMA"}


def test_module_has_no_side_effect_clients() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "server" / "sports_shared" / "prospective_cross_game_evidence.py").read_text("utf-8")
    for forbidden in ("requests", "httpx", "sqlalchemy", "boto3", "subprocess", "asp-model-exchange"):
        assert forbidden not in source


def test_json_schemas_bind_frozen_hashes_and_thresholds() -> None:
    root = Path(__file__).resolve().parents[1] / "docs" / "prospective-cross-game-evidence-v1" / "schemas"
    schemas = {path.name: json.loads(path.read_text(encoding="utf-8")) for path in root.glob("*.json")}
    assert len(schemas) == 5
    readiness = schemas["readiness-state.schema.json"]["properties"]
    assert readiness["thresholds"]["properties"]["minimumGames"]["const"] == 500
    binding = readiness["frozenGateBinding"]["properties"]
    assert binding["designSha256"]["const"] == FROZEN_DESIGN_SHA256
    assert binding["resultsSha256"]["const"] == FROZEN_RESULTS_SHA256
