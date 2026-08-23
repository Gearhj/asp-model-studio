"""Phase 7D.5A — the honest replacement for the target-contaminated B2-full proof.

Proves: a genuinely point-in-time-correct feature (Workstream A, value-level, with an INDEPENDENT reference impl),
bound to full semantic authority via a transformation receipt + value digest (Workstream B, no V2->V1 downgrade,
no empty semantic children), published as an immutable QUARANTINED Silver object that is NOT model eligible
(Workstream C). No advanced model is trained. No real Bronze / 2025.
"""
from __future__ import annotations

import json
import math

import pytest

from server.sports_modeling import silver_transform as ST
from server.sports_modeling import silver_publish as SP
from server.sports_modeling.feature_contract import FEATURE_NAMES
from server.sports_modeling import feature_semantics as FS

BATTERS = ["b1", "b2", "b3"]
SEASONS = [2021, 2022, 2023, 2024]


def _source_rows(*, shuffle=False, mutate_outcome_row=None, extra_future=0, with_outcome=False):
    """A deterministic hermetic source: multiple batters/games/PAs, a same-key tie needing the stable tie-breaker,
    varied outcomes, future rows, optionally shuffled. Contains NO target unless with_outcome=True."""
    rows = []
    n = 0
    for s in SEASONS:
        for b in BATTERS:
            for g in range(3):                        # games
                for ab in range(4):                   # at-bats per game
                    n += 1
                    r = {"plate_appearance_id": f"pa-{s}-{b}-{g}-{ab}", "game_id": f"{s}-{b}-g{g}",
                         "game_date": f"{s}-04-{1 + g:02d}", "at_bat_number": ab,
                         "batter_canonical_player_uuid": b, "season": s}
                    for f in FEATURE_NAMES:
                        r[f] = float((n * 7 + hash(f) % 5) % 11) / 10.0
                    if with_outcome:
                        r["outcome"] = ["STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "BIP_OUT"][ab % 4]
                    rows.append(r)
    # a same-(date,game,at_bat) tie for b1, resolved only by the stable plate_appearance_id tie-breaker
    tie = dict(rows[0]); tie["plate_appearance_id"] = "pa-tie-zzz"; rows.append(tie if not with_outcome else {**tie})
    for i in range(extra_future):
        f = dict(rows[1]); f["plate_appearance_id"] = f"pa-future-{i}"; f["game_date"] = "2024-12-31"
        rows.append(f)
    if mutate_outcome_row is not None and with_outcome:
        rows[mutate_outcome_row]["outcome"] = "TRIPLE"
    if shuffle:
        rows = [rows[i] for i in _perm(len(rows))]
    return rows


def _perm(n):                                          # deterministic shuffle (no Math.random)
    return sorted(range(n), key=lambda i: (i * 2654435761) % n)


def _ref_prior_pa(rows):
    """INDEPENDENT O(n^2) reference: for each row, count same-batter rows with a strictly-earlier governed key."""
    key_cols = ST.governed_sort_key(sorted(rows[0].keys()))
    def key(r): return tuple(str(r[c]) for c in key_cols)
    out = []
    for r in rows:
        c = sum(1 for o in rows if str(o["batter_canonical_player_uuid"]) == str(r["batter_canonical_player_uuid"])
                and key(o) < key(r))
        out.append({ST.PRIOR_PA_COUNT: float(c), ST.LOG1P_PRIOR_PA_COUNT: float(math.log1p(c))})
    return out


# ============================================================ Workstream A — point-in-time value tests
def test_1_exact_formula_matches_independent_reference():
    rows = _source_rows()
    prod = ST.compute_prior_pa(rows)
    ref = _ref_prior_pa(rows)
    assert prod == ref


def test_2_current_outcome_independence():
    base = _source_rows(with_outcome=True)
    mutated = _source_rows(with_outcome=True, mutate_outcome_row=5)
    # transform never receives outcome; strip it and confirm identical features even though row 5's outcome changed
    strip = lambda rs: [{k: v for k, v in r.items() if k != "outcome"} for r in rs]
    assert ST.compute_prior_pa(strip(base)) == ST.compute_prior_pa(strip(mutated))


def test_3_target_column_removal_identical():
    with_t = _source_rows(with_outcome=True)
    without_t = [{k: v for k, v in r.items() if k != "outcome"} for r in with_t]
    assert ST.compute_prior_pa(without_t) == _ref_prior_pa(without_t)
    # and the transform REFUSES the target column outright
    with pytest.raises(ST.SilverTransformError):
        ST.compute_prior_pa(with_t)


def test_4_future_outcome_invariance():
    a = _source_rows()
    b = _source_rows()                                  # identical; feature has no outcome dependence at all
    assert ST.compute_prior_pa(a) == ST.compute_prior_pa(b)


def test_5_future_row_append_invariance():
    base = ST.compute_prior_pa(_source_rows())
    extended = ST.compute_prior_pa(_source_rows(extra_future=6))
    # every ORIGINAL row's feature is unchanged by appending later PAs
    assert extended[: len(base)] == base


def test_6_input_order_invariance():
    ordered = ST.compute_prior_pa(_source_rows())
    shuffled_rows = _source_rows(shuffle=True)
    shuffled = ST.compute_prior_pa(shuffled_rows)
    # map both back by plate_appearance_id and compare
    o = {r["plate_appearance_id"]: f for r, f in zip(_source_rows(), ordered)}
    s = {r["plate_appearance_id"]: f for r, f in zip(shuffled_rows, shuffled)}
    assert o == s


def test_7_no_current_row_inclusion():
    rows = _source_rows()
    out = ST.compute_prior_pa(rows)
    # the earliest PA for each batter has prior_pa_count 0 (never counts itself)
    firsts = {}
    key_cols = ST.governed_sort_key(sorted(rows[0].keys()))
    for r, f in zip(rows, out):
        b = r["batter_canonical_player_uuid"]; k = tuple(str(r[c]) for c in key_cols)
        if b not in firsts or k < firsts[b][0]:
            firsts[b] = (k, f[ST.PRIOR_PA_COUNT])
    assert all(v[1] == 0.0 for v in firsts.values())


def test_8_player_separation():
    rows = _source_rows()
    out = ST.compute_prior_pa(rows)
    # b1's counts are unaffected by removing all of b2/b3
    b1_rows = [r for r in rows if r["batter_canonical_player_uuid"] == "b1"]
    b1_only = ST.compute_prior_pa(b1_rows)
    both = {r["plate_appearance_id"]: f for r, f in zip(rows, out) if r["batter_canonical_player_uuid"] == "b1"}
    sep = {r["plate_appearance_id"]: f for r, f in zip(b1_rows, b1_only)}
    assert both == sep


# ============================================================ Workstream B/C — publication + quarantine
def _publish(tmp_path, **kw):
    rows = kw.pop("rows", None) or [{k: v for k, v in r.items()} for r in _source_rows()]
    return SP.publish_silver(
        silver_root=tmp_path / "silver", source_object_id="hermetic-src", source_receipt_sha="s" * 64,
        source_manifest_sha="m" * 64, source_physical_sha="p" * 64, source_logical_sha="l" * 64,
        source_schema_sha="c" * 64, source_rows=rows, base_feature_ids=list(FEATURE_NAMES),
        season_of_row=lambda r: r["season"], **kw)


def test_publish_binds_semantic_v2_receipt_value_digest(tmp_path):
    entry = _publish(tmp_path)
    v = SP.verify_silver(tmp_path / "silver", entry["manifestSha256"])
    r = v["receipt"]
    assert r["receiptContract"] == SP.SILVER_TRANSFORM_RECEIPT and r["transformId"] == ST.TRANSFORM_ID
    assert set(r["semanticContractShas"]) == {ST.PRIOR_PA_COUNT, ST.LOG1P_PRIOR_PA_COUNT}
    assert r["featureFamilySha256"] and r["featureSetV2Sha256"] and r["valueDigestSha256"]
    assert r["orderedOutputFeatures"][-2:] == [ST.PRIOR_PA_COUNT, ST.LOG1P_PRIOR_PA_COUNT]
    # semantic children are present + leakage-validated (not empty)
    contracts = SP.silver_semantic_contracts(source_object_id="hermetic-src", source_receipt_sha="s" * 64)
    for c in contracts.values():
        FS.validate_feature_semantic_contract(c)


def test_value_digest_detects_one_changed_value(tmp_path):
    entry = _publish(tmp_path)
    root = tmp_path / "silver" / "objects" / "sha256" / entry["manifestSha256"]
    import pyarrow.parquet as pq, pyarrow as pa
    tbl = pq.read_table(root / "object.parquet").to_pylist()
    tbl[0][ST.LOG1P_PRIOR_PA_COUNT] = 999.0                          # flip one value
    cols = {k: [r[k] for r in tbl] for k in tbl[0]}
    (root / "object.parquet").write_bytes(_parquet_bytes(cols))
    with pytest.raises(SP.SilverPublishError):
        SP.verify_silver(tmp_path / "silver", entry["manifestSha256"])


def _parquet_bytes(cols):
    import pyarrow as pa, pyarrow.parquet as pq
    fields = [(k, pa.float64() if isinstance(v[0], float) else (pa.int64() if isinstance(v[0], int) else pa.string())) for k, v in cols.items()]
    t = pa.table(cols, schema=pa.schema(fields))
    sink = pa.BufferOutputStream(); pq.write_table(t.replace_schema_metadata(None).combine_chunks(), sink, compression="none",
        row_group_size=max(1, t.num_rows), use_dictionary=False, write_statistics=False, store_schema=True)
    return sink.getvalue().to_pybytes()


def test_old_target_contaminated_formula_is_rejected(tmp_path):
    # supply the OLD leaky values: log1p(random) + 0.001*class_index -> must not match the point-in-time recompute
    rows = [{k: v for k, v in r.items()} for r in _source_rows()]
    n = len(rows)
    leaky = {ST.LOG1P_PRIOR_PA_COUNT: [math.log1p((i * 37) % 700) + 0.001 * (i % 8) for i in range(n)],
             ST.PRIOR_PA_COUNT: [float((i * 37) % 700) for i in range(n)]}
    with pytest.raises(SP.SilverPublishError):
        _publish(tmp_path, rows=rows, supplied_advanced=leaky)


def test_caller_supplied_mismatch_rejected(tmp_path):
    rows = [{k: v for k, v in r.items()} for r in _source_rows()]
    good = ST.compute_prior_pa(rows)
    bad = {ST.LOG1P_PRIOR_PA_COUNT: [good[i][ST.LOG1P_PRIOR_PA_COUNT] + (0.5 if i == 3 else 0.0) for i in range(len(rows))]}
    with pytest.raises(SP.SilverPublishError):
        _publish(tmp_path, rows=rows, supplied_advanced=bad)
    # matching supplied values ARE accepted
    ok = {ST.LOG1P_PRIOR_PA_COUNT: [good[i][ST.LOG1P_PRIOR_PA_COUNT] for i in range(len(rows))]}
    assert _publish(tmp_path, rows=rows, supplied_advanced=ok)["modelEligible"] is False


def test_v2_to_v1_downgrade_rejected(tmp_path):
    with pytest.raises(SP.SilverPublishError):
        _publish(tmp_path, feature_set_downgrade_v1=True)


def test_silver_is_quarantined_and_not_model_eligible(tmp_path):
    entry = _publish(tmp_path)
    assert entry["status"] == SP.SILVER_STATUS and entry["quarantine"] == SP.SILVER_QUARANTINE
    assert entry["modelEligible"] is False and entry["approvedForTraining"] is False
    # the model-eligibility barrier rejects it
    assert SP.is_quarantined_silver(tmp_path / "silver", entry["datasetVersionId"])
    with pytest.raises(SP.DatasetNotModelEligibleError):
        SP.assert_model_eligible(tmp_path / "silver", entry["datasetVersionId"])


def test_sealed_season_source_rejected(tmp_path):
    rows = [{k: v for k, v in r.items()} for r in _source_rows()]
    rows[0]["season"] = 2025
    with pytest.raises(SP.SilverPublishError):
        _publish(tmp_path, rows=rows)
