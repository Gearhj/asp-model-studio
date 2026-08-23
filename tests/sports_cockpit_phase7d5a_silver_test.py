"""Phase 7D.5A / 7D.5A.2 — semantic-authority binding + quarantine model-barrier for the immutable Silver object.

The point-in-time chronology itself is proven adversarially in ``sports_cockpit_phase7d5a2_chronology_test`` and the
server-resolved source / integrity tamper matrix in the ``_source_authority`` / ``_silver_integrity`` suites. This
file proves the SEMANTIC binding (transformation receipt + value digest + V2 chain, no V1 downgrade) and the
QUARANTINE model-ineligibility barrier through the new server-resolved publisher.
"""
from __future__ import annotations

import math

import pytest

from server.sports_modeling import silver_publish as SP
from server.sports_modeling import silver_transform as ST
from server.sports_modeling.feature_contract import FEATURE_NAMES
from tests import _silver_fixture as F


def test_value_digest_binds_actual_values_not_just_names():
    rows = F.source_rows()
    feats = ST.compute_prior_pa(rows)
    out = [{**r, "prior_pa_count": f["prior_pa_count"], "log1p_prior_pa_count": f["log1p_prior_pa_count"]}
           for r, f in zip(rows, feats)]
    base = SP.value_digest(out, ST.OUTPUT_FEATURES, id_col="plate_appearance_id")
    mutated = [dict(r) for r in out]
    mutated[0]["log1p_prior_pa_count"] = mutated[0]["log1p_prior_pa_count"] + 1e-9
    assert SP.value_digest(mutated, ST.OUTPUT_FEATURES, id_col="plate_appearance_id") != base


def test_log1p_is_exactly_log1p_of_prior_count():
    feats = ST.compute_prior_pa(F.source_rows())
    for f in feats:
        assert f["log1p_prior_pa_count"] == math.log1p(f["prior_pa_count"])


def test_publish_binds_transformation_receipt_and_value_digest(tmp_path):
    p = F.publish_silver_hermetic(tmp_path)
    v = SP.verify_silver(p["silver_root"], p["manifest_sha"])
    r = v["receipt"]
    assert r["receiptContract"] == SP.SILVER_TRANSFORM_RECEIPT
    assert r["transformId"] == ST.TRANSFORM_ID
    assert r["valueDigestSha256"] == v["valueDigestSha256"]
    assert r["featureSetBindsOutputLogicalSha256"] == r["outputLogicalSha256"]      # OUTPUT-bound V2
    assert list(r["producedAdvancedFeatures"]) == list(ST.OUTPUT_FEATURES)


def test_v2_to_v1_downgrade_is_refused(tmp_path):
    F.publish_source(tmp_path / "src")
    with pytest.raises(SP.SilverPublishError):
        SP.publish_silver(silver_root=tmp_path / "silver", source_root=tmp_path / "src",
                          source_dataset_version_id=F.SRC_ID, base_feature_ids=list(FEATURE_NAMES),
                          season_of_row=lambda r: r["season"], feature_set_downgrade_v1=True)


def test_published_silver_is_quarantined_and_not_model_eligible(tmp_path):
    p = F.publish_silver_hermetic(tmp_path)
    e = p["entry"]
    assert e["status"] == "SILVER_NORMALIZED" and e["quarantine"] == "QUARANTINED"
    assert e["modelEligible"] is False and e["approvedForTraining"] is False and e["selectable"] is False
    assert SP.is_quarantined_silver(p["silver_root"], e["datasetVersionId"])
    with pytest.raises(SP.DatasetNotModelEligibleError):
        SP.assert_model_eligible(p["silver_root"], e["datasetVersionId"])


def test_any_silver_prefixed_id_is_model_ineligible(tmp_path):
    with pytest.raises(SP.DatasetNotModelEligibleError):
        SP.assert_model_eligible(tmp_path / "silver", "silver:anything:sha256:" + "a" * 64)
