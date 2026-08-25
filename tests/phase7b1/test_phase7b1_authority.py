"""Phase 7B1 — current/history registration authority + partitioned value-digest tests (final patch).

Covers: (1) the single registry index records exactly one current registration per logical object with every superseded
registration listed as historical (and rejects contradictions); (2) partitioned objects get a real, deterministic,
non-null value digest computed from the existing child partitions (never Bronze, never None==None), bound into the
current immutable registration/manifest, independently recomputed by verify, and provably equal across objects with
identical child bytes. Hermetic.
"""
from __future__ import annotations

import pytest

from server.sports_silver import canonical_ids as CID
from server.sports_silver import contracts as CT
from server.sports_silver import silver_publication as SP
from server.sports_silver import statcast_normalize as SN

_FO = ["canonicalGameId", "retroGameId", "eventSequence", "retroBatterId", "batterCanonicalPlayerId", "season",
       "inning", "half", "count", "eventText", "pitches", "sourceArchive", "sourceMember", "sourceLine"]
_SI = {"bronzeManifestSha256": "b" * 64, "sourceCount": 2, "sources": [
    {"partitionId": "retrosheet/events/2019eve", "source": "retrosheet", "fileSha256": "a" * 64},
    {"partitionId": "retrosheet/events/2020eve", "source": "retrosheet", "fileSha256": "d" * 64}]}


def _pub(silver):
    c = CT.fact_retrosheet_event_contract([2019, 2020])
    def rows(rid, y):
        return [{"canonicalGameId": "g" + y, "retroGameId": rid, "eventSequence": "1", "retroBatterId": "b", "season": y}]
    it = [("2019", "retrosheet-events-2019", rows("r1", "2019")), ("2020", "retrosheet-events-2020", rows("r2", "2020"))]
    return SP.publish_partitioned_silver_table(silver_root=silver, contract=c, partitions_iter=iter(it),
        bronze_manifest={}, code_modules=[SN], field_order=_FO), c


# ---- fix 2: partitioned value digests -------------------------------------------------------------------------
def test_partitioned_value_digest_nonnull_deterministic(tmp_path):
    old, c = _pub(tmp_path)
    nk = c["naturalKey"]
    a = SP.partitioned_value_digest(tmp_path, old["manifestSha256"], field_order=_FO, natural_key=nk)
    b = SP.partitioned_value_digest(tmp_path, old["manifestSha256"], field_order=_FO, natural_key=nk)
    assert isinstance(a, str) and len(a) == 64 and a == b and a != "0" * 64          # real, deterministic, non-null


def test_partitioned_value_digest_bound_and_reverified_and_equal_across_identical_children(tmp_path):
    old, c = _pub(tmp_path)
    nk = c["naturalKey"]
    vd = SP.partitioned_value_digest(tmp_path, old["manifestSha256"], field_order=_FO, natural_key=nk)
    new = SP.regenerate_partitioned_silver_table(silver_root=tmp_path, old_manifest_sha=old["manifestSha256"],
        contract=c, code_modules=[SN], source_inputs=_SI, value_digest=vd)
    assert new["valueDigestSha256"] == vd and new["manifestSha256"] != old["manifestSha256"]
    v = SP.verify_partitioned_silver_table(tmp_path, new["manifestSha256"])           # verify recomputes + matches
    assert v["valueDigestSha256"] == vd
    # old-vs-new value digests (identical child bytes) genuinely match
    assert SP.partitioned_value_digest(tmp_path, new["manifestSha256"], field_order=_FO, natural_key=nk) == vd


def test_declared_value_digest_that_disagrees_with_children_fails_closed(tmp_path):
    old, c = _pub(tmp_path)
    with pytest.raises(SP.SilverTablePublishError):                                   # wrong (but 64-hex) digest -> reject
        SP.regenerate_partitioned_silver_table(silver_root=tmp_path, old_manifest_sha=old["manifestSha256"],
            contract=c, code_modules=[SN], source_inputs=_SI, value_digest="0" * 64)


# ---- fix 1: current/history registration authority ------------------------------------------------------------
def test_logical_index_current_and_history_roundtrip(tmp_path):
    old, c = _pub(tmp_path)
    nk = c["naturalKey"]
    vd = SP.partitioned_value_digest(tmp_path, old["manifestSha256"], field_order=_FO, natural_key=nk)
    new = SP.regenerate_partitioned_silver_table(silver_root=tmp_path, old_manifest_sha=old["manifestSha256"],
        contract=c, code_modules=[SN], source_inputs=_SI, value_digest=vd)
    SP.write_logical_index(tmp_path, {"fact_retrosheet_event": {
        "currentRegistrationSha256": new["registrationSha256"], "currentDatasetVersionId": new["datasetVersionId"],
        "historicalRegistrationSha256s": [old["registrationSha256"]]}})
    idx = SP.logical_index(tmp_path)["fact_retrosheet_event"]
    assert idx["currentRegistrationSha256"] == new["registrationSha256"]
    assert idx["historicalRegistrationSha256s"] == [old["registrationSha256"]]
    assert idx["currentRegistrationSha256"] not in idx["historicalRegistrationSha256s"]  # one current, not historical


def test_logical_index_rejects_current_listed_as_historical(tmp_path):
    _pub(tmp_path)
    sha = "a" * 64
    with pytest.raises(SP.SilverTablePublishError):
        SP.write_logical_index(tmp_path, {"t": {"currentRegistrationSha256": sha, "currentDatasetVersionId": "silver-table:t:sha256:x",
                                                "historicalRegistrationSha256s": [sha]}})


def test_logical_index_rejects_duplicate_history_and_non_hex(tmp_path):
    _pub(tmp_path)
    with pytest.raises(SP.SilverTablePublishError):
        SP.write_logical_index(tmp_path, {"t": {"currentRegistrationSha256": "a" * 64, "currentDatasetVersionId": "d",
                                                "historicalRegistrationSha256s": ["b" * 64, "b" * 64]}})
    with pytest.raises(SP.SilverTablePublishError):
        SP.write_logical_index(tmp_path, {"t": {"currentRegistrationSha256": "nothex", "currentDatasetVersionId": "d",
                                                "historicalRegistrationSha256s": []}})


def test_logical_index_preserves_content_addressed_lookup(tmp_path):
    # writing currentness must not break the datasets lookup that verify relies on
    old, c = _pub(tmp_path)
    SP.write_logical_index(tmp_path, {"fact_retrosheet_event": {
        "currentRegistrationSha256": old["registrationSha256"], "currentDatasetVersionId": old["datasetVersionId"],
        "historicalRegistrationSha256s": []}})
    SP.verify_partitioned_silver_table(tmp_path, old["manifestSha256"])               # still verifies after index write
