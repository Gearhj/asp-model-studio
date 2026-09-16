from __future__ import annotations

import hashlib
import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from server.sports_current_statcast import mlb_core_challenger_tuning as tuning
from server.sports_current_statcast.stage3_model_laboratory import GOLD_CLASS_ORDER
from server.sports_datasets.consumer import canonical_json_bytes


def test_compact_grid_and_runtime_rule_are_frozen_before_fit() -> None:
    grids = tuning.exact_grids()
    assert len(grids["histogram_gradient_boosting"]) == 3
    assert len(grids["random_forest"]) == 2
    assert {item["learning_rate"] for item in grids["histogram_gradient_boosting"]} == {
        0.03, 0.07, 0.1
    }
    assert {item["max_leaf_nodes"] for item in grids["histogram_gradient_boosting"]} == {31, 63}
    assert {item["min_samples_leaf"] for item in grids["histogram_gradient_boosting"]} == {20, 50}
    assert {item["l2_regularization"] for item in grids["histogram_gradient_boosting"]} == {1.0, 10.0}
    assert {item["n_estimators"] for item in grids["random_forest"]} == {300, 500}
    assert {item["max_depth"] for item in grids["random_forest"]} == {24, None}
    assert {item["min_samples_leaf"] for item in grids["random_forest"]} == {5, 20}
    assert {item["max_features"] for item in grids["random_forest"]} == {"sqrt", 0.5}
    assert all(item["class_weight"] is None for item in grids["random_forest"])
    estimate = tuning.runtime_estimate()
    assert estimate["configurationCount"] == 5
    assert estimate["officialFoldFits"] == 25
    assert estimate["reductionRequired"] is False
    assert estimate["contingencyEstimateMs"] < estimate["operationalCeilingMs"]


def _attempt(root, name: str, probabilities: np.ndarray, labels: np.ndarray) -> dict:
    rows = len(labels)
    relative = f"objects/oof/sha256/{name}.parquet"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = {
        "canonicalPaId": pa.array([f"pa-{index}" for index in range(rows)]),
        "canonicalGameId": pa.array([f"game-{index // 10}" for index in range(rows)]),
        "foldNumber": pa.array([(index // 80) + 1 for index in range(rows)], type=pa.int8()),
        "observedClassIndex": pa.array(labels, type=pa.int8()),
    }
    for class_index, class_name in enumerate(GOLD_CLASS_ORDER):
        columns[f"probability_{class_name}"] = pa.array(
            probabilities[:, class_index], type=pa.float64()
        )
    pq.write_table(pa.table(columns), path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "evaluationEvidence": {
            "reloadableArtifactRelativePath": relative,
            "reloadableArtifactSha256": digest,
        }
    }


def test_game_clustered_bootstrap_is_paired_and_development_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tuning, "_runtime_root", lambda: tmp_path)
    labels = np.arange(400, dtype=np.int64) % len(GOLD_CLASS_ORDER)
    right = np.full((400, len(GOLD_CLASS_ORDER)), 0.04, dtype=float)
    right[np.arange(400), labels] = 0.72
    right /= right.sum(axis=1, keepdims=True)
    left = np.full((400, len(GOLD_CLASS_ORDER)), 0.03, dtype=float)
    left[np.arange(400), labels] = 0.79
    left /= left.sum(axis=1, keepdims=True)
    result = tuning.paired_game_cluster_bootstrap(
        _attempt(tmp_path, "left", left, labels),
        _attempt(tmp_path, "right", right, labels),
        replicates=400,
        seed=17,
    )
    assert result["rowCount"] == 400
    assert result["gameClusterCount"] == 40
    assert result["replicates"] == 400
    assert result["estimate"] < 0
    assert result["confidenceInterval"]["upper"] < 0
    assert len(result["foldDifferences"]) == 5
    assert result["consistentDirectionAcrossFolds"] is True
    assert result["finalOotTargetAccessed"] is False


def test_latest_tuning_decision_accepts_only_content_addressed_project_object(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(tuning, "_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(tuning, "__file__", str(tmp_path / "mlb_core_challenger_tuning.py"))
    payload = {
        "schemaVersion": tuning.TUNING_SCHEMA_VERSION,
        "projectId": tuning.PROJECT_ID,
        "createdAt": "2026-09-06T20:00:00Z",
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    directory = tmp_path / "tuning-decisions" / "objects" / "sha256"
    directory.mkdir(parents=True)
    (directory / f"{digest}.json").write_bytes(canonical_json_bytes(payload))
    (directory / f"{'0' * 64}.json").write_text(json.dumps(payload), encoding="utf-8")
    result = tuning.latest_tuning_decision(tuning.PROJECT_ID)
    assert result is not None
    assert result["receiptSha256"] == digest
    assert tuning.latest_tuning_decision("another-project") is None
