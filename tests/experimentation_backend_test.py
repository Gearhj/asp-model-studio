from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server.experimentation.ab_service as ab_service


TMP_ROOT = ROOT / ".tmp" / "experimentation-backend-test"
VERSION_DIR = TMP_ROOT / "ds-ab-test" / "v1"


def build_full_artifact(rows: int = 1200) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user id": [f"user-{index}" for index in range(rows)],
            "test group": ["ad" if index % 3 else "psa" for index in range(rows)],
            "converted": [bool(index % 11 == 0 or (index % 3 and index % 17 == 0)) for index in range(rows)],
            "total ads": [(index % 35) + 1 for index in range(rows)],
            "most ads day": [["Monday", "Tuesday", "Wednesday", "Thursday"][index % 4] for index in range(rows)],
            "most ads hour": [index % 24 for index in range(rows)],
        }
    )


def mapping() -> dict[str, object]:
    return {
        "unitIdColumn": "user.id",
        "treatmentColumn": "test.group",
        "treatmentValue": "ad",
        "controlValue": "psa",
        "outcomeColumn": "converted",
        "successEvent": "True",
        "exposureColumn": "total.ads",
        "segmentColumns": ["most.ads.day", "most.ads.hour"],
    }


def install_registry_stubs() -> None:
    ab_service.require_dataset = lambda dataset_id: {
        "datasetId": dataset_id,
        "name": "AB Full Artifact Test",
        "versions": [{"versionId": "v1"}],
    }
    ab_service.latest_version_id = lambda dataset: "v1"
    ab_service.version_dir = lambda dataset_id, version_id: VERSION_DIR
    ab_service._analyze_cached.cache_clear()


def test_full_registered_artifact() -> None:
    shutil.rmtree(TMP_ROOT, ignore_errors=True)
    VERSION_DIR.mkdir(parents=True, exist_ok=True)
    frame = build_full_artifact()
    frame.to_csv(VERSION_DIR / "data_full.csv", index=False)
    install_registry_stubs()

    analysis = ab_service.analyze_registered_ab_dataset(
        {"datasetId": "ds-ab-test", "versionId": "v1", "mapping": mapping()}
    )

    assert analysis["status"]["fullDatasetAvailable"] is True
    assert analysis["status"]["previewOnly"] is False
    assert analysis["status"]["source"] == "full_dataset_artifact"
    assert analysis["status"]["rowCount"] == len(frame)
    assert analysis["status"]["validAnalysisRecords"] == len(frame)
    assert analysis["profile"]["uniqueUnits"] == len(frame)
    assert analysis["summary"]["treatmentCount"] == 800
    assert analysis["summary"]["controlCount"] == 400
    assert analysis["daySegments"]
    assert sum(row["treatmentCount"] + row["controlCount"] for row in analysis["daySegments"]) == len(frame)
    assert analysis["hourSegments"]
    assert analysis["aggregates"]["outcomeSuccess"] == analysis["summary"]["treatmentConversions"] + analysis["summary"]["controlConversions"]
    assert analysis["aggregates"]["outcomeNonSuccess"] == len(frame) - analysis["aggregates"]["outcomeSuccess"]
    assert analysis["aggregates"]["exposureAvailable"] is True
    assert sum(row["count"] for row in analysis["aggregates"]["exposureSummary"]) == len(frame)
    assert analysis["aggregates"]["missingByColumn"]["user.id"] == 0
    assert "user.id" in analysis["columns"]
    assert "test.group" in analysis["columns"]
    assert len(analysis["rows"]) == len(frame)


def test_missing_full_artifact_blocks_analysis() -> None:
    shutil.rmtree(TMP_ROOT, ignore_errors=True)
    VERSION_DIR.mkdir(parents=True, exist_ok=True)
    install_registry_stubs()
    try:
        ab_service.analyze_registered_ab_dataset(
            {"datasetId": "ds-ab-test", "versionId": "v1", "mapping": mapping()}
        )
    except HTTPException as error:
        assert error.status_code == 409
        assert "Full dataset artifact is not loaded" in str(error.detail)
    else:
        raise AssertionError("Analysis must be blocked when data_full.csv is absent.")


if __name__ == "__main__":
    try:
        test_full_registered_artifact()
        test_missing_full_artifact_blocks_analysis()
        print("experimentation backend checks passed")
    finally:
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
