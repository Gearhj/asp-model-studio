from __future__ import annotations

import copy
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pyarrow as pa

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER, evaluate_multiclass
from server.sports_phase4.dynamic_state import (
    DynamicStateIntegrityError,
    build_dynamic_player_state_from_tables,
    dynamic_state_table_content_sha,
)
from server.sports_phase4.dynamic_training import (
    DynamicTrainingIntegrityError,
    FrozenD0Fold,
    calibrate_dynamic_experiment,
    dynamic_decision,
    dynamic_training_arrays,
    evaluate_dynamic_experiment,
    run_dynamic_training_experiment,
    run_blocking_with_heartbeat,
)


BATTER_UUID = "00000000-0000-4000-8000-000000000201"
PITCHER_UUID = "00000000-0000-4000-8000-000000000202"


def _history_table() -> pa.Table:
    rows: list[dict[str, object]] = []
    dates = [
        "2021-04-01",
        "2021-08-01",
        "2022-03-01",
        "2022-08-01",
        "2023-04-01",
        "2023-04-02",
        "2023-04-03",
        "2024-04-01",
        "2024-04-02",
        "2025-04-01",
    ]
    for ordinal, game_date in enumerate(dates):
        rows.append(
            {
                "plate_appearance_id": f"history-{ordinal}",
                "game_id": f"history-game-{ordinal}",
                "game_date": game_date,
                "season": int(game_date[:4]),
                "batter_id": "batter-key",
                "pitcher_id": "pitcher-key",
                "outcome": PA_CLASS_ORDER[ordinal % 8],
                "final_available_date": game_date,
                "available_only_after_game_final": True,
                "future_evidence_allowed": False,
                "canonical_identity_resolved": False,
                "target_only_not_pregame_feature": True,
                "strict_same_game_pregame_eligible": False,
                "timing_risk_label": "RETROSPECTIVE_EVENT_OUTCOME_TIMING_RISK",
            }
        )
    return pa.Table.from_pylist(rows)


def _feature_table(*, mutate_2025: bool = False) -> pa.Table:
    rows: list[dict[str, object]] = []
    ordinal = 0
    for season, date_count in ((2023, 5), (2024, 3), (2025, 3)):
        for date_ordinal in range(date_count):
            game_date = f"{season}-05-{date_ordinal + 1:02d}"
            game_id = f"{season}-game-{date_ordinal}"
            for class_index, outcome in enumerate(PA_CLASS_ORDER):
                ordinal += 1
                if mutate_2025 and season == 2025:
                    outcome = PA_CLASS_ORDER[(class_index + 3) % 8]
                rows.append(
                    {
                        "plate_appearance_id": f"target-{ordinal}",
                        "game_id": game_id,
                        "game_date": game_date,
                        "season": season,
                        "outcome": outcome,
                        "batter_canonical_player_uuid": BATTER_UUID,
                        "pitcher_canonical_player_uuid": PITCHER_UUID,
                        "context_inning": 1 + ((class_index + date_ordinal) % 9),
                        "context_top_bottom": (class_index + date_ordinal) % 2,
                        "context_outs_before": (class_index + 2 * date_ordinal) % 3,
                        "context_base_mask_before": (class_index + date_ordinal) % 8,
                        "context_batting_score_diff_before": (class_index % 5) - 2,
                    }
                )
    return pa.Table.from_pylist(rows)


def _state(feature: pa.Table):
    return build_dynamic_player_state_from_tables(
        [_history_table()],
        feature,
        alias_rows={"batter-key": BATTER_UUID, "pitcher-key": PITCHER_UUID},
        dimension_uuids=frozenset({BATTER_UUID, PITCHER_UUID}),
        code_revision="fixture:dynamic-training",
        source_partition_ids=("fixture-pa-history",),
    )


def _d0_fold(feature: pa.Table, season: int, *, sha_character: str) -> FrozenD0Fold:
    rows = [row for row in feature.to_pylist() if row["season"] == season]
    columns: dict[str, object] = {
        "plate_appearance_id": [row["plate_appearance_id"] for row in rows],
        "game_id": [row["game_id"] for row in rows],
        "outcome": [row["outcome"] for row in rows],
    }
    for class_index, class_name in enumerate(PA_CLASS_ORDER):
        values = []
        for row in rows:
            actual = PA_CLASS_ORDER.index(str(row["outcome"]))
            values.append(0.30 if actual == class_index else 0.10)
        columns[f"raw_C4_{class_name}"] = values
    return FrozenD0Fold(season, sha_character * 64, pa.Table.from_pydict(columns))


class SportsPhase4DynamicTrainingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.feature = _feature_table()
        cls.state = _state(cls.feature)
        cls.d0 = {
            2024: _d0_fold(cls.feature, 2024, sha_character="a"),
            2025: _d0_fold(cls.feature, 2025, sha_character="b"),
        }
        cls.progress: list[tuple[str, dict[str, object]]] = []
        cls.experiment = run_dynamic_training_experiment(
            cls.feature,
            cls.state.table,
            policy=cls.state.policy,
            dynamic_content_sha=cls.state.content_sha,
            d0_folds=cls.d0,
            progress=lambda stage, evidence: cls.progress.append((stage, evidence)),
        )

    def test_candidate_selection_and_folds_obey_frozen_sequence(self) -> None:
        result = self.experiment
        self.assertEqual([row["candidateId"] for row in result.candidates], ["D0", "D1", "D2", "D3", "D4"])
        self.assertIn(result.selected_candidate_id, {"D1", "D2", "D3", "D4"})
        self.assertEqual(result.candidate("D0")["config"]["refit"], False)
        self.assertEqual(result.candidate("D0")["foldMetrics"][0]["trainingSeasons"], [2023])
        self.assertEqual(result.candidate("D0")["foldMetrics"][1]["trainingSeasons"], [2023, 2024])
        self.assertTrue(
            all(
                candidate["foldMetrics"][1]["status"] == "COMPLETE"
                for candidate in result.candidates
            )
        )
        frozen_index = next(index for index, row in enumerate(self.progress) if row[0] == "DYNAMIC_CANDIDATE_FROZEN")
        final_indices = [index for index, row in enumerate(self.progress) if row[0] == "REFITTING_DYNAMIC_THROUGH_2024_VALIDATING_2025"]
        self.assertTrue(final_indices and all(index > frozen_index for index in final_indices))
        self.assertTrue(all(len(item["inner2023Tuning"]) == 3 for item in result.candidates[1:]))

    def test_2025_labels_and_predictions_cannot_change_2024_selection(self) -> None:
        changed = _feature_table(mutate_2025=True)
        changed_state = _state(changed)
        changed_result = run_dynamic_training_experiment(
            changed,
            changed_state.table,
            policy=changed_state.policy,
            dynamic_content_sha=changed_state.content_sha,
            d0_folds={
                2024: _d0_fold(changed, 2024, sha_character="c"),
                2025: _d0_fold(changed, 2025, sha_character="d"),
            },
        )
        self.assertEqual(changed_result.selected_candidate_id, self.experiment.selected_candidate_id)
        for candidate_id in ("D1", "D2", "D3", "D4"):
            np.testing.assert_array_equal(
                changed_result.folds[2024].probabilities[candidate_id],
                self.experiment.folds[2024].probabilities[candidate_id],
            )

    def test_join_binds_to_exact_dynamic_semantic_content(self) -> None:
        rows = self.state.table.to_pylist()
        rows[0]["log_odds_strikeout"] += 0.01
        semantic = dict(rows[0])
        semantic.pop("stateRowId")
        semantic.pop("rowContentSha")
        rows[0]["rowContentSha"] = sha256_bytes(canonical_json_bytes(semantic))
        tampered = pa.Table.from_pylist(rows, schema=self.state.table.schema)
        tampered_sha = dynamic_state_table_content_sha(tampered, policy=self.state.policy)
        self.assertNotEqual(tampered_sha, self.state.content_sha)
        with self.assertRaisesRegex(DynamicTrainingIntegrityError, "semantic content SHA differs"):
            dynamic_training_arrays(
                self.feature,
                tampered,
                policy=self.state.policy,
                expected_dynamic_content_sha=self.state.content_sha,
            )

    def test_d0_lineage_is_exact_and_never_relabelled(self) -> None:
        rows = self.d0[2024].table.to_pylist()
        rows[0]["plate_appearance_id"] = "wrong-id"
        bad = FrozenD0Fold(2024, "e" * 64, pa.Table.from_pylist(rows))
        with self.assertRaisesRegex(DynamicTrainingIntegrityError, "D0 plate_appearance_id lineage"):
            run_dynamic_training_experiment(
                self.feature,
                self.state.table,
                policy=self.state.policy,
                dynamic_content_sha=self.state.content_sha,
                d0_folds={2024: bad, 2025: self.d0[2025]},
            )

    def test_calibration_requires_both_2024_and_2025_nonworsening(self) -> None:
        fold_2024 = self.experiment.folds[2024]
        raw_2024 = fold_2024.probabilities[self.experiment.selected_candidate_id]
        raw_evidence = evaluate_multiclass(fold_2024.labels, raw_2024)
        fake_fit = SimpleNamespace(
            scaled_probabilities=raw_2024.copy(),
            raw_evidence=raw_evidence,
            scaled_evidence=raw_evidence,
            retained=True,
            fitted_temperature=2.0,
        )
        fold_2025 = self.experiment.folds[2025]
        bad_2025 = np.full_like(fold_2025.probabilities[self.experiment.selected_candidate_id], 1e-9)
        wrong = (fold_2025.encoded_labels + 1) % len(PA_CLASS_ORDER)
        bad_2025[np.arange(wrong.size), wrong] = 1.0 - 7e-9
        with patch("server.sports_phase4.dynamic_training.fit_temperature_scaling", return_value=fake_fit), patch(
            "server.sports_phase4.dynamic_training.temperature_scale", return_value=bad_2025
        ):
            payload, scaled, final = calibrate_dynamic_experiment(self.experiment)
        self.assertTrue(payload["eligibleOn2024"])
        self.assertFalse(payload["nonWorseningOn2025"])
        self.assertFalse(payload["retainedAfter2025Gate"])
        np.testing.assert_array_equal(scaled[2025], bad_2025)
        np.testing.assert_array_equal(
            final[2025],
            fold_2025.probabilities[self.experiment.selected_candidate_id],
        )

    def test_scaled_only_improvement_and_raw_calibration_defect_cannot_earn_challenger(self) -> None:
        altered = copy.deepcopy(self.experiment)
        selected = altered.candidate(altered.selected_candidate_id)
        d0 = altered.candidate("D0")
        for index, season in enumerate((2024, 2025)):
            selected_metrics = selected["foldMetrics"][index]["metrics"]
            d0_metrics = d0["foldMetrics"][index]["metrics"]
            selected_metrics["logLoss"] = d0_metrics["logLoss"] + 0.1
            selected_metrics["brierScore"] = d0_metrics["brierScore"] + 0.1
        fake_calibration = {
            "final": {
                "2024": {"logLoss": 0.0, "brierScore": 0.0},
                "2025": {"logLoss": 0.0, "brierScore": 0.0},
            }
        }
        decision = dynamic_decision(altered, fake_calibration, [])
        self.assertNotEqual(decision["decision"], "DYNAMIC_STATE_RESEARCH_CHALLENGER")
        self.assertFalse(decision["scaledEvidenceCanEarnChallenger"])

        defect = copy.deepcopy(self.experiment)
        selected = defect.candidate(defect.selected_candidate_id)
        d0 = defect.candidate("D0")
        for index in range(2):
            selected_metrics = selected["foldMetrics"][index]["metrics"]
            d0_metrics = d0["foldMetrics"][index]["metrics"]
            selected_metrics["logLoss"] = d0_metrics["logLoss"] - 0.1
            selected_metrics["brierScore"] = d0_metrics["brierScore"]
            selected_metrics["topLabelEce"] = d0_metrics["topLabelEce"] + 0.006
            selected_metrics["classwiseEce"] = dict(d0_metrics["classwiseEce"])
        defect_decision = dynamic_decision(defect, fake_calibration, [])
        self.assertEqual(defect_decision["decision"], "DYNAMIC_STATE_RESEARCH_BASELINE")
        self.assertFalse(defect_decision["noMeaningfulRawCalibrationDefect"])

    def test_evaluation_preserves_raw_scaled_bootstrap_and_subgroups(self) -> None:
        evidence = evaluate_dynamic_experiment(self.experiment, bootstrap_resamples=20)
        self.assertEqual(len(evidence.bootstrap), 4)
        self.assertEqual(
            {(row["validationSeason"], row["probabilityVariant"]) for row in evidence.bootstrap},
            {(2024, "RAW"), (2024, "FINAL"), (2025, "RAW"), (2025, "FINAL")},
        )
        self.assertTrue(evidence.calibration["rawAndScaledPreserved"])
        self.assertEqual(len(evidence.coverage["subgroups"]), 8)
        self.assertIn(evidence.decision["decision"], {
            "DYNAMIC_STATE_RESEARCH_CHALLENGER",
            "DYNAMIC_STATE_RESEARCH_BASELINE",
            "DYNAMIC_STATE_REJECTED",
        })

    def test_blocking_fit_heartbeat_is_two_argument_and_elapsed_gate_is_fail_closed(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        result = run_blocking_with_heartbeat(
            lambda: (time.sleep(0.04), "done")[1],
            stage="FIXTURE_FIT",
            candidate_id="D4",
            progress=lambda stage, evidence: events.append((stage, evidence)),
            heartbeat_seconds=0.01,
            max_elapsed_seconds=1.0,
        )
        self.assertEqual(result, "done")
        self.assertTrue(any(stage == "DYNAMIC_MODEL_FIT_HEARTBEAT" for stage, _ in events))
        self.assertTrue(all(evidence["candidateId"] == "D4" for _, evidence in events))
        with self.assertRaisesRegex(DynamicTrainingIntegrityError, "90-minute limit"):
            run_blocking_with_heartbeat(
                lambda: time.sleep(0.03),
                stage="FIXTURE_FIT",
                candidate_id="D4",
                progress=lambda _stage, _evidence: None,
                heartbeat_seconds=0.01,
                max_elapsed_seconds=0.02,
            )


if __name__ == "__main__":
    unittest.main()
