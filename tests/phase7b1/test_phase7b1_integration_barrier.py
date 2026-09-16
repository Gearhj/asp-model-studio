"""Phase 7B1 — Section 15: silver_publication is an INTEGRATION layer over the accepted authority (not a parallel
registry), and the QUARANTINE BARRIER is enforced through the ordinary PRODUCTION model paths.

Proves, against real (temp) published Silver objects:
  * a real ``silver-table:...`` dataset id is rejected by the accepted-authority PRODUCTION eligibility functions
    (``assert_canonical_eligibility`` — called by ``create_binding``; ``_resolve_version`` — called by the
    run-authority ``_run_datasets_eligible``), with the explicit DATASET_NOT_MODEL_ELIGIBLE barrier — for BOTH the
    single-table and the partitioned publication id shapes;
  * silver_publication reuses the accepted content-addressing / locking / containment PRIMITIVES (same function
    objects), rather than reimplementing a parallel authority.
"""
from __future__ import annotations

import pytest

from server.sports_cockpit import gen3_authority as GA
from server.sports_cockpit import interprocess_lock as IL
from server.sports_cockpit import path_containment as PC
from server.sports_datasets import consumer as CN
from server.sports_silver import canonical_ids as CID
from server.sports_silver import contracts as CT
from server.sports_silver import silver_publication as SP
from server.sports_silver import statcast_normalize as SN

_TEAM_FO = ["canonicalTeamId", "teamAbbrev", "aliases", "retroTeamCode", "nickname", "city"]


def _row(a):
    return {"canonicalTeamId": CID.canonical_team_id(a), "teamAbbrev": a, "aliases": [], "retroTeamCode": a,
            "nickname": None, "city": None, "season": "2019"}


def _publish_single(silver):
    return SP.publish_silver_table(silver_root=silver, contract=CT.dim_team_contract([2019]), rows=[_row("NYY")],
                                   bronze_manifest={}, source_partition_ids=["p"], code_modules=[SN], field_order=_TEAM_FO)


def _publish_partitioned(silver):
    return SP.publish_partitioned_silver_table(silver_root=silver, contract=CT.dim_team_contract([2019]),
        partitions_iter=iter([("2019", "src", [_row("NYY"), _row("BOS")])]), bronze_manifest={},
        code_modules=[SN], field_order=_TEAM_FO)


@pytest.mark.parametrize("publish", [_publish_single, _publish_partitioned])
def test_production_binding_path_rejects_real_silver_dsid(tmp_path, publish):
    dsid = publish(tmp_path)["datasetVersionId"]
    assert dsid.startswith("silver-table:")
    # accepted-authority eligibility decision (the one create_binding invokes) fails closed
    with pytest.raises(GA.AuthorityError, match="DATASET_NOT_MODEL_ELIGIBLE"):
        GA.assert_canonical_eligibility(dsid)
    # accepted-authority version resolver (the one run-authority invokes) fails closed
    with pytest.raises(GA.AuthorityError, match="DATASET_NOT_MODEL_ELIGIBLE"):
        GA._resolve_version(dsid)
    # and silver_publication's own consumer-side barrier agrees
    with pytest.raises(SP.SilverTableNotModelEligibleError):
        SP.assert_not_model_eligible(dsid)


def test_accepted_authority_prefix_predicate_covers_phase7b1_prefix():
    # single-source prefix decision must recognize BOTH the accepted "silver:" and Phase 7B1 "silver-table:" ids
    assert GA._is_quarantined_silver_id("silver:foo") is True
    assert GA._is_quarantined_silver_id("silver-table:dim_team:sha256:" + "a" * 64) is True
    assert GA._is_quarantined_silver_id("mlb-pa-gen3-base:sha256:" + "a" * 64) is False   # a real model-eligible id


def test_silver_publication_reuses_accepted_primitives_not_a_parallel_stack():
    assert SP.canonical_json_bytes is CN.canonical_json_bytes
    assert SP.sha256_bytes is CN.sha256_bytes
    assert SP.interprocess_lock is IL.interprocess_lock
    assert SP.contained_no_reparse is PC.contained_no_reparse
