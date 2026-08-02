from __future__ import annotations

from copy import deepcopy

import pytest

from server.core.result_store import ResultStore
from server.governance.selection_integrity import (
    INVALID_FINAL_HOLDOUT_RANKING,
    LEGACY_UNRESOLVED,
    VERIFIED_SELECTION,
    SelectionIntegrityError,
    assert_evaluation_package_integrity,
    assert_locked_candidate_decision,
    assert_selection_integrity,
    classify_selection_integrity,
)


def _selection_metric() -> dict:
    return {
        "name": "pr_auc",
        "value": 0.72,
        "source": "out_of_fold",
        "partition_id": "population-train-1",
        "fold_definition_id": "folds-1",
        "fold_count": 3,
        "fold_values": [0.70, 0.72, 0.74],
        "mean": 0.72,
        "standard_deviation": 0.01633,
        "out_of_fold_prediction_artifact_id": "oof-1",
        "threshold_source": "platform_governed_default",
        "calibration_source": "fold_local_training_only",
        "created_at": "2026-07-31T12:00:00+00:00",
        "holdout_used": False,
    }


def _candidate() -> dict:
    return {
        "project_id": "project-1",
        "dataset_id": "dataset-1",
        "dataset_version_id": "version-1",
        "candidate_id": "candidate-new",
        "training_job_id": "job-new",
        "training_run_id": "run-new",
        "feature_manifest_version": "manifest-1",
        "validation_design_id": "design-1",
        "validation_design_version": "design-version-1",
        "split_id": "split-1",
        "selection_metric": _selection_metric(),
        "selection_integrity_status": VERIFIED_SELECTION,
        "holdout_isolation_status": VERIFIED_SELECTION,
    }


def _decision() -> dict:
    candidate = _candidate()
    return {
        **candidate,
        "decision_id": "decision-1",
        "selected_candidate_id": candidate["candidate_id"],
        "status": "locked",
        "selection_ranking_snapshot_hash": "snapshot-1",
        "selection_locked_at": "2026-07-31T12:01:00+00:00",
        "actor": {"user_id": "user-1"},
    }


def test_known_phase2b1_candidate_is_explicitly_non_promotable() -> None:
    status, reason = classify_selection_integrity(
        {"candidate_id": "candidate-7925f986465de3fc97d9b727"}
    )
    assert status == INVALID_FINAL_HOLDOUT_RANKING
    assert "final-holdout" in reason


def test_missing_provenance_is_legacy_unresolved_not_assumed_invalid_or_valid() -> None:
    assert classify_selection_integrity({"candidate_id": "candidate-old"})[0] == LEGACY_UNRESOLVED


def test_verified_training_only_selection_contract_passes() -> None:
    metric = assert_selection_integrity(_candidate())
    assert metric["source"] == "out_of_fold"
    assert metric["value"] == pytest.approx(0.72)


def test_final_holdout_source_is_rejected_even_when_declared_verified() -> None:
    candidate = _candidate()
    candidate["selection_metric"]["source"] = "final_holdout"
    with pytest.raises(SelectionIntegrityError, match="invalid_final_holdout_ranking"):
        assert_selection_integrity(candidate)


def test_locked_decision_must_bind_the_exact_candidate_and_metric() -> None:
    decision = _decision()
    assert assert_locked_candidate_decision(decision, _candidate())["decision_id"] == "decision-1"
    decision["selected_candidate_id"] = "candidate-other"
    with pytest.raises(SelectionIntegrityError, match="candidate_id"):
        assert_locked_candidate_decision(decision, _candidate())


def test_complete_package_preserves_distinct_selection_and_holdout_evidence() -> None:
    candidate = _candidate()
    decision = _decision()
    package = {
        **candidate,
        "evaluation_package_id": "eval-1",
        "candidate_decision_id": decision["decision_id"],
        "status": "complete",
        "isolation_status": VERIFIED_SELECTION,
        "selection_evidence": {"selection_metric": deepcopy(candidate["selection_metric"])},
        "final_holdout_evidence": {
            "metric_source": "final_holdout",
            "metrics": {"pr_auc": 0.68},
        },
        "holdout_exposure": {
            "status": "evaluated",
            "first_opened_at": "2026-07-31T12:02:00+00:00",
        },
        "recommendations_derived_from_final_holdout": False,
    }
    verified = assert_evaluation_package_integrity(
        package,
        decision=decision,
        candidate=candidate,
    )
    assert verified["selection_evidence"]["selection_metric"]["value"] == pytest.approx(0.72)
    assert verified["final_holdout_evidence"]["metrics"]["pr_auc"] == pytest.approx(0.68)


def test_result_store_keeps_holdout_outside_training_summary_and_freezes_first_open() -> None:
    store = ResultStore()
    store.set_last_summary({"ranked": [{"candidate_id": "candidate-new"}]})
    exposure = {
        "candidate_id": "candidate-new",
        "candidate_decision_id": "decision-1",
        "final_holdout_partition_id": "holdout-1",
        "status": "opened",
    }
    first, created = store.set_holdout_evaluation_if_absent("candidate-new", exposure)
    second, created_again = store.set_holdout_evaluation_if_absent(
        "candidate-new", {**exposure, "candidate_decision_id": "decision-other"}
    )
    assert created is True
    assert created_again is False
    assert second == first
    assert "y_true" not in store.get_last_summary()
    evaluated = store.mark_holdout_evaluated(
        "candidate-new",
        evaluation_package_id="eval-1",
        evaluated_at="2026-07-31T12:03:00+00:00",
    )
    assert evaluated["status"] == "evaluated"
    assert evaluated["evaluation_package_id"] == "eval-1"
