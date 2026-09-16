from __future__ import annotations

import json
import shutil

import joblib
import numpy as np
import pytest
from sklearn.linear_model import Ridge

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_nfl_m1 import artifacts as A


FOUNDATION_SHA = "a" * 64


def _model() -> Ridge:
    features = np.asarray([[0.0], [1.0], [2.0], [3.0]])
    target = np.asarray([17.0, 20.0, 24.0, 27.0])
    return Ridge(alpha=1.0).fit(features, target)


def _publish(root, **overrides):
    arguments = {
        "candidate_id": "nfl-m1-ridge-long-history",
        "foundation_sha256": FOUNDATION_SHA,
        "feature_names": ["elo_difference", "home_rest_days"],
        "recency_strategy": "MOST_RECENT_8_SEASONS",
        "hyperparameters": {"alpha": np.float64(1.0), "seed": np.int64(731001)},
        "calibration": {"method": "OOF_LOGISTIC", "folds": 5},
        "training_cutoff": "2025-12-31",
        "training_row_ids": ["2025_17_A_B", "2025_17_C_D"],
        "training_outcome_dates": ["2025-12-28", "2025-12-31"],
    }
    arguments.update(overrides)
    return A.publish_research_artifact(root, _model(), **arguments)


def test_publication_is_canonical_content_addressed_and_reloads(tmp_path) -> None:
    publication = _publish(tmp_path)
    assert publication.bundle_path.parent.name == "sha256"
    assert publication.bundle_path.name == publication.manifest_sha256
    assert publication.manifest_path.read_bytes() == canonical_json_bytes(publication.manifest)
    assert sha256_bytes(publication.manifest_path.read_bytes()) == publication.manifest_sha256
    assert publication.manifest["foundationManifestSha256"] == FOUNDATION_SHA
    assert publication.manifest["featureNames"] == ["elo_difference", "home_rest_days"]
    assert publication.manifest["recencyStrategy"] == "MOST_RECENT_8_SEASONS"
    assert publication.manifest["hyperparameters"] == {"alpha": 1.0, "seed": 731001}
    assert publication.manifest["training"]["trainingCutoff"] == "2025-12-31"
    assert len(publication.manifest["training"]["rowIdSha256"]) == 64

    loaded = A.load_verified_research_artifact(
        tmp_path,
        expected_manifest_sha256=publication.manifest_sha256,
        expected_artifact_sha256=publication.artifact_sha256,
        expected_foundation_sha256=FOUNDATION_SHA,
    )
    np.testing.assert_allclose(
        loaded.model.predict(np.asarray([[1.5], [2.5]])),
        _model().predict(np.asarray([[1.5], [2.5]])),
    )
    assert loaded.publication.artifact_sha256 == publication.artifact_sha256


def test_2026_training_truth_is_rejected_before_joblib_publication(tmp_path, monkeypatch) -> None:
    calls: list[object] = []
    original_dump = joblib.dump

    def recording_dump(*args, **kwargs):
        calls.append(args)
        return original_dump(*args, **kwargs)

    monkeypatch.setattr(A.joblib, "dump", recording_dump)
    with pytest.raises(A.ResearchArtifactError, match="2026-season training outcomes"):
        _publish(
            tmp_path,
            training_cutoff="2026-01-04",
            training_row_ids=["2025-final", "2026-week-1"],
            training_outcome_dates=["2025-12-31", "2026-01-04"],
            training_seasons=[2025, 2026],
        )
    assert calls == []


def test_completed_2025_postseason_in_2026_calendar_year_is_authorized(tmp_path) -> None:
    publication = _publish(
        tmp_path,
        training_cutoff="2026-02-08",
        training_row_ids=["2025-conf", "2025-super-bowl"],
        training_outcome_dates=["2026-01-25", "2026-02-08"],
        training_seasons=[2025, 2025],
    )
    assert publication.manifest["training"]["seasonEnd"] == 2025
    assert publication.manifest["training"]["contains2026SeasonOutcome"] is False


def test_tampered_model_is_rejected_before_joblib_load(tmp_path, monkeypatch) -> None:
    publication = _publish(tmp_path)
    publication.model_path.write_bytes(b"not-the-pinned-joblib-artifact")
    calls: list[object] = []

    def forbidden_load(*args, **kwargs):
        calls.append(args)
        raise AssertionError("unverified bytes reached joblib.load")

    monkeypatch.setattr(A.joblib, "load", forbidden_load)
    with pytest.raises(A.ResearchArtifactError, match="byte count|checksum"):
        A.load_verified_research_artifact(
            tmp_path,
            expected_manifest_sha256=publication.manifest_sha256,
            expected_artifact_sha256=publication.artifact_sha256,
            expected_foundation_sha256=FOUNDATION_SHA,
        )
    assert calls == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("status", "PROMOTED"),
        ("promotionState", "PROMOTED"),
        ("deploymentEligible", True),
    ],
)
def test_readdressed_manifest_cannot_weaken_research_disposition(
    tmp_path, key: str, value: object
) -> None:
    publication = _publish(tmp_path)
    changed = dict(publication.manifest)
    changed[key] = value
    changed_bytes = canonical_json_bytes(changed)
    changed_sha = sha256_bytes(changed_bytes)
    changed_bundle = tmp_path / "objects" / "sha256" / changed_sha
    changed_bundle.mkdir(parents=True)
    (changed_bundle / "manifest.json").write_bytes(changed_bytes)
    shutil.copyfile(publication.model_path, changed_bundle / "model.joblib")
    with pytest.raises(A.ResearchArtifactError, match="research-only disposition"):
        A.verify_research_artifact(
            tmp_path,
            expected_manifest_sha256=changed_sha,
            expected_artifact_sha256=publication.artifact_sha256,
            expected_foundation_sha256=FOUNDATION_SHA,
        )


def test_wrong_foundation_or_artifact_authority_fails_closed(tmp_path) -> None:
    publication = _publish(tmp_path)
    with pytest.raises(A.ResearchArtifactError, match="foundation identity"):
        A.verify_research_artifact(
            tmp_path,
            expected_manifest_sha256=publication.manifest_sha256,
            expected_artifact_sha256=publication.artifact_sha256,
            expected_foundation_sha256="b" * 64,
        )
    with pytest.raises(A.ResearchArtifactError, match="artifact identity"):
        A.verify_research_artifact(
            tmp_path,
            expected_manifest_sha256=publication.manifest_sha256,
            expected_artifact_sha256="c" * 64,
            expected_foundation_sha256=FOUNDATION_SHA,
        )


def test_training_cutoff_and_row_identity_contracts_fail_closed(tmp_path) -> None:
    with pytest.raises(A.ResearchArtifactError, match="after the declared cutoff"):
        _publish(tmp_path, training_cutoff="2025-12-30")
    with pytest.raises(A.ResearchArtifactError, match="unique"):
        _publish(tmp_path, training_row_ids=["duplicate", "duplicate"])


def test_joblib_failure_leaves_no_visible_or_staged_bundle(tmp_path, monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise OSError("bounded write failure")

    monkeypatch.setattr(A.joblib, "dump", fail)
    with pytest.raises(OSError, match="bounded write failure"):
        _publish(tmp_path)
    objects = tmp_path / "objects"
    assert not objects.exists() or list(objects.iterdir()) == []
