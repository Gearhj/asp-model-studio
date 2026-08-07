from __future__ import annotations

import os
from pathlib import Path
import uuid


# Every mutable authority is bound before importing any server module. This
# focused suite never opens a live project, live Dataset Library, or holdout.
REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = (REPO_ROOT / ".tmp" / f"special-value-review-{uuid.uuid4().hex}").resolve()
BACKUP_ROOT = (
    Path(os.environ.get("TEMP") or TEST_ROOT.parent)
    / f"special-value-review-backup-{uuid.uuid4().hex}"
).resolve()
ROOTS = {
    "ATLAS_SECURITY_ROOT": TEST_ROOT / "security",
    "ATLAS_SECURITY_DB_PATH": TEST_ROOT / "security" / "security.db",
    "ATLAS_SQLITE_PATH": TEST_ROOT / "persistence" / "atlas.db",
    "ATLAS_CHECKPOINT_PATH": TEST_ROOT / "checkpoint" / "workflow.json",
    "ATLAS_DATASET_LIBRARY_ROOT": TEST_ROOT / "dataset-library",
    "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": BACKUP_ROOT,
    "ATLAS_EVIDENCE_ROOT": TEST_ROOT / "evidence",
    "ATLAS_FEATURE_MANIFEST_ROOT": TEST_ROOT / "feature-manifests",
    "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT": TEST_ROOT / "model-registry",
    "ATLAS_SCORING_RUN_ARTIFACT_ROOT": TEST_ROOT / "scoring-runs",
    "ATLAS_VIF_PLAN_ROOT": TEST_ROOT / "vif-plans",
    "ATLAS_PYTHON_RUNTIME_DIR": TEST_ROOT / "python-runtime",
}
LIVE_ROOTS = {
    (REPO_ROOT / ".runtime").resolve(),
    (REPO_ROOT / "server" / "data").resolve(),
    (REPO_ROOT / "server" / "artifacts").resolve(),
}
for name, path in ROOTS.items():
    resolved = path.resolve()
    allowed = resolved == BACKUP_ROOT if name == "ATLAS_DATASET_LIBRARY_BACKUP_ROOT" else (
        resolved == TEST_ROOT or TEST_ROOT in resolved.parents
    )
    if not allowed:
        raise AssertionError(f"{name} escaped its UUID test root: {resolved}")
    if any(resolved == live or live in resolved.parents for live in LIVE_ROOTS):
        raise AssertionError(f"{name} resolved to live storage: {resolved}")
    if name.endswith("_ROOT") or name.endswith("_DIR"):
        resolved.mkdir(parents=True, exist_ok=True)
    else:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(resolved)
os.environ.update(
    {
        "ATLAS_ENV": "testing",
        "ATLAS_TEST_MODE": "1",
        "ATLAS_AUTH_ENABLED": "true",
        "ATLAS_LOCAL_DEV": "false",
        "ATLAS_DEV_MODE": "false",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
)

import pytest

from server.persistence.db import Database, now_iso
from server.persistence.repositories.special_value_review_repository import (
    SpecialValueReviewConflictError,
    SpecialValueReviewRepository,
    SpecialValueReviewStateError,
)
from server.preprocessing.bureau_detection_types import (
    SpecialValueVariableDecisionInput,
)
from server.preprocessing.special_value_review_service import (
    SpecialValueReviewValidationError,
    detection_fingerprint,
    evaluate_review,
    initial_review_state,
    public_review_contract,
)


PROJECT_ID = "project-special-review"
DATASET_ID = "dataset-special-review"
VERSION_ID = "version-special-review"


def detection(*, second_variable: bool = True) -> dict:
    variables = [
        {
            "variable": "ExternalRiskEstimate",
            "likely_bureau": True,
            "datatype": "float64",
            "special_value_count": 4,
            "special_values": [
                {"value": -9, "count": 3, "definition": "No score"},
                {"value": 98, "count": 1, "definition": "Unavailable"},
            ],
        }
    ]
    if second_variable:
        variables.append(
            {
                "variable": "PercentTradesNeverDelq",
                "likely_bureau": True,
                "special_value_count": 2,
                "special_values": [
                    {"value": 96, "count": 2, "definition": "Bureau exception"}
                ],
            }
        )
    return {
        "ok": True,
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "activation_revision": 3,
        "predictor_authorization_id": "predictor-auth-special",
        "target_contract_id": "target-contract-special",
        "analysis_partition_id": "analysis-partition-special-r1",
        "analysis_partition_revision": 1,
        "development_partition_id": "development-special-r1",
        "analysis_partition_assignment_hash": "assignment-special-r1",
        "analysis_partition_artifact_hash": "artifact-special-r1",
        "development_target_checksum": "development-target-special-r1",
        "source_checksum": "source-special-v1",
        "structural_scope": "full_governed_population_predictors_only",
        "target_analysis_scope": "development_population",
        "full_governed_population_rows": 100,
        "development_rows": 80,
        "target_evidence": {
            "available": True,
            "status": "available",
            "scope": "development_population",
        },
        "target": "bad_flag",
        "detected": True,
        "manual_declaration": "auto",
        "variables": variables,
        "reviewed_at": "volatile timestamp",
        "correlation_id": "volatile correlation",
        "final_holdout_accessed": False,
    }


@pytest.fixture()
def repository():
    path = (TEST_ROOT / "repositories" / f"review-{uuid.uuid4().hex}.db").resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.initialize()
    timestamp = now_iso()
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO projects (
              project_id, project_name, project_type, workflow_type,
              status, created_at, updated_at, metadata_json
            ) VALUES (?, ?, 'predictive-modeling', 'predictive-modeling',
                      'active', ?, ?, '{}')
            """,
            (PROJECT_ID, "Special Review Fixture", timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO projects (
              project_id, project_name, project_type, workflow_type,
              status, created_at, updated_at, metadata_json
            ) VALUES (?, ?, 'predictive-modeling', 'predictive-modeling',
                      'active', ?, ?, '{}')
            """,
            ("other-project", "Other Project", timestamp, timestamp),
        )
    return SpecialValueReviewRepository(database)


def sync_payload(value: dict) -> dict:
    return {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "activation_revision": 3,
        "predictor_authorization_id": "predictor-auth-special",
        "target_contract_id": "target-contract-special",
        "detection_fingerprint": detection_fingerprint(value),
        "detection": value,
        "actor_user_id": "review-owner",
        **initial_review_state(value),
    }


def decisions() -> list[SpecialValueVariableDecisionInput]:
    return [
        SpecialValueVariableDecisionInput(
            variable="ExternalRiskEstimate",
            policy="preserve_informative",
        ),
        SpecialValueVariableDecisionInput(
            variable="PercentTradesNeverDelq",
            policy="convert_to_category",
            overrides=[
                {
                    "value": 96,
                    "policy": "leave_unchanged",
                    "rationale": "Retain the documented exception value.",
                }
            ],
        ),
    ]


def test_detection_fingerprint_ignores_transport_metadata_and_counts_exact_items():
    first = detection()
    second = {**first, "reviewed_at": "later", "correlation_id": "other"}
    assert detection_fingerprint(first) == detection_fingerprint(second)
    assert detection_fingerprint(first) == detection_fingerprint(
        {**first, "activation_revision": 4}
    )
    assert detection_fingerprint(first) != detection_fingerprint(
        {
            **first,
            "variables": [
                {**first["variables"][0], "datatype": "object"},
                first["variables"][1],
            ],
        }
    )
    assert detection_fingerprint(first) != detection_fingerprint(
        {
            **first,
            "analysis_partition_revision": 2,
            "development_target_checksum": "development-target-special-r2",
        }
    )
    state = initial_review_state(first)
    assert state == {
        "status": "not_started",
        "detected_count": 2,
        "reviewed_count": 0,
        "open_count": 2,
        "blocks_confirmation": True,
        "blocks_continuation": True,
    }


def test_exact_version_reactivation_preserves_confirmed_decisions(repository):
    value = detection()
    row = repository.sync_detection(sync_payload(value))
    confirmed_state = evaluate_review(value, decisions(), intent="confirm")
    confirmed = repository.save_review(
        {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "detection_fingerprint": row["detection_fingerprint"],
            "actor_user_id": "review-owner",
            **confirmed_state,
        },
        expected_revision=1,
    )
    reactivated = {**value, "activation_revision": 4}
    payload = {**sync_payload(reactivated), "activation_revision": 4}
    refreshed = repository.sync_detection(payload)
    assert refreshed["revision"] == confirmed["revision"] + 1
    assert refreshed["activation_revision"] == 4
    assert refreshed["status"] == "confirmed"
    assert refreshed["decisions_json"] == confirmed["decisions_json"]


def test_repository_rejects_type_invalid_and_special_code_replacements(repository):
    value = detection(second_variable=False)
    row = repository.sync_detection(sync_payload(value))
    for replacement in (True, "not-a-number", -9):
        with pytest.raises(
            SpecialValueReviewStateError,
            match="valid governed replacement",
        ):
            repository.save_review(
                {
                    "project_id": PROJECT_ID,
                    "dataset_id": DATASET_ID,
                    "dataset_version_id": VERSION_ID,
                    "detection_fingerprint": row["detection_fingerprint"],
                    "actor_user_id": "review-owner",
                    "status": "confirmed",
                    "detected_count": 1,
                    "reviewed_count": 1,
                    "open_count": 0,
                    "blocks_confirmation": False,
                    "blocks_continuation": False,
                    "decisions": [
                        {
                            "variable": "ExternalRiskEstimate",
                            "policy": "documented_domain_mapping",
                            "replacement_value": replacement,
                            "rationale": "Use a governed valid value.",
                            "overrides": [],
                        }
                    ],
                },
                expected_revision=1,
            )


def test_review_policy_validation_is_backend_detection_bound_and_fail_closed():
    value = detection()
    with pytest.raises(SpecialValueReviewValidationError) as incomplete:
        evaluate_review(value, decisions()[:1], intent="confirm")
    assert incomplete.value.code == "special_value_review_incomplete"
    assert incomplete.value.open_items == ["PercentTradesNeverDelq"]

    with pytest.raises(SpecialValueReviewValidationError) as unknown:
        evaluate_review(
            value,
            [
                SpecialValueVariableDecisionInput(
                    variable="BrowserOnlyVariable",
                    policy="preserve_informative",
                )
            ],
            intent="draft",
        )
    assert unknown.value.code == "unknown_special_value_variable"

    with pytest.raises(SpecialValueReviewValidationError) as rationale:
        evaluate_review(
            value,
            [
                SpecialValueVariableDecisionInput(
                    variable="ExternalRiskEstimate",
                    policy="exclude_variable",
                )
            ],
            intent="draft",
        )
    assert rationale.value.code == "special_value_rationale_required"

    with pytest.raises(SpecialValueReviewValidationError) as replacement:
        evaluate_review(
            value,
            [
                SpecialValueVariableDecisionInput(
                    variable="ExternalRiskEstimate",
                    policy="documented_domain_mapping",
                    rationale="Use an observed, valid score value.",
                )
            ],
            intent="draft",
        )
    assert replacement.value.code == "governed_replacement_value_required"

    with pytest.raises(SpecialValueReviewValidationError) as special_code:
        evaluate_review(
            value,
            [
                SpecialValueVariableDecisionInput(
                    variable="ExternalRiskEstimate",
                    policy="documented_domain_mapping",
                    replacement_value=-9,
                    rationale="Attempt an invalid governed value.",
                )
            ],
            intent="draft",
        )
    assert special_code.value.code == "governed_replacement_value_invalid"

    mapped = evaluate_review(
        value,
        [
            SpecialValueVariableDecisionInput(
                variable="ExternalRiskEstimate",
                policy="documented_domain_mapping",
                replacement_value="72",
                rationale="Use an observed, valid score value.",
            )
        ],
        intent="draft",
    )
    assert mapped["decisions"][0]["replacement_value"] == 72.0


def test_no_backend_detected_special_values_do_not_manufacture_a_blocker():
    value = {**detection(second_variable=False), "variables": []}
    assert initial_review_state(value) == {
        "status": "not_required",
        "detected_count": 0,
        "reviewed_count": 0,
        "open_count": 0,
        "blocks_confirmation": False,
        "blocks_continuation": False,
    }
    evaluated = evaluate_review(value, [], intent="confirm")
    assert evaluated["status"] == "not_required"
    assert evaluated["blocks_continuation"] is False


def test_repository_is_exact_scoped_revisioned_and_confirmation_is_durable(repository):
    value = detection()
    initial = repository.sync_detection(sync_payload(value))
    assert initial["revision"] == 1
    assert initial["status"] == "not_started"
    assert initial["detected_count"] == initial["open_count"] == 2
    assert repository.get_exact(PROJECT_ID, DATASET_ID, "wrong-version") is None
    assert repository.get_exact("other-project", DATASET_ID, VERSION_ID) is None

    # Identical backend detection is idempotent; volatile timestamps cannot
    # invalidate a review or manufacture a revision.
    same = repository.sync_detection(sync_payload({**value, "reviewed_at": "later"}))
    assert same["revision"] == 1

    evaluated = evaluate_review(value, decisions()[:1], intent="draft")
    draft = repository.save_review(
        {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "detection_fingerprint": initial["detection_fingerprint"],
            "reviewer_rationale": "Draft review.",
            "actor_user_id": "review-owner",
            **evaluated,
        },
        expected_revision=1,
    )
    assert draft["revision"] == 2
    assert draft["status"] == "in_review"
    assert draft["reviewed_count"] == draft["open_count"] == 1
    assert draft["blocks_continuation"] == 1

    with pytest.raises(SpecialValueReviewConflictError) as stale:
        repository.save_review(
            {
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                "detection_fingerprint": initial["detection_fingerprint"],
                "actor_user_id": "review-owner",
                **evaluated,
            },
            expected_revision=1,
        )
    assert stale.value.current["revision"] == 2

    confirmed_state = evaluate_review(value, decisions(), intent="confirm")
    confirmed = repository.save_review(
        {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "detection_fingerprint": initial["detection_fingerprint"],
            "reviewer_rationale": "Exact review complete.",
            "actor_user_id": "review-owner",
            **confirmed_state,
        },
        expected_revision=2,
    )
    contract = public_review_contract(confirmed)
    assert contract["revision"] == 3
    assert contract["status"] == "confirmed"
    assert contract["open_count"] == 0
    assert contract["open_items"] == []
    assert contract["blocks_confirmation"] is False
    assert contract["blocks_continuation"] is False
    assert contract["browser_cache_authority"] is False
    assert contract["authority"] == "backend_durable_exact_version"
    events = repository.events(PROJECT_ID, DATASET_ID, VERSION_ID)
    assert [event["event_type"] for event in events] == [
        "detection_initialized",
        "draft_saved",
        "confirmed",
    ]
    assert events[-1]["payload_json"]["detection_fingerprint"] == initial[
        "detection_fingerprint"
    ]
    assert events[-1]["payload_json"]["reviewed_count"] == 2
    assert [
        decision["variable"] for decision in events[-1]["payload_json"]["decisions"]
    ] == ["ExternalRiskEstimate", "PercentTradesNeverDelq"]


def test_changed_backend_detection_invalidates_confirmed_decisions(repository):
    original = detection()
    row = repository.sync_detection(sync_payload(original))
    evaluated = evaluate_review(original, decisions(), intent="confirm")
    confirmed = repository.save_review(
        {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "detection_fingerprint": row["detection_fingerprint"],
            "actor_user_id": "review-owner",
            **evaluated,
        },
        expected_revision=1,
    )
    assert confirmed["status"] == "confirmed"

    changed = detection(second_variable=False)
    refreshed = repository.sync_detection(sync_payload(changed))
    assert refreshed["revision"] == 3
    assert refreshed["status"] == "not_started"
    assert refreshed["decisions_json"] == []
    assert refreshed["detected_count"] == refreshed["open_count"] == 1
    assert refreshed["blocks_continuation"] == 1
    assert refreshed["confirmed_at"] is None
    assert changed["final_holdout_accessed"] is False
