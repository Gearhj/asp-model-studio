"""Phase 7B1 — governed Silver normalization & identity reconciliation tests.

Deliberately NOT named ``tests/sports_*_test.py`` so it can never alter the frozen Phase 7D.5A isolated-gate
collection. Uses synthetic hermetic data for unit/integration coverage plus read-only real-Bronze authority checks.
Covers Section 18 categories A(Bronze immutability) B(player identity) C/D(normalization) E(temporal) F(Silver
authority) G(quarantine) H(reproducibility).
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_silver import bronze_authority as BA
from server.sports_silver import canonical_ids as CID
from server.sports_silver import contracts as CT
from server.sports_silver import player_identity as PI
from server.sports_silver import silver_publication as SP
from server.sports_silver import statcast_normalize as SN


# ---- canonical ids (Section 23, H) ------------------------------------------------------------------------------
def test_canonical_ids_deterministic_and_non_colliding():
    assert CID.canonical_player_id("key-A") == CID.canonical_player_id("key-A")     # deterministic
    assert CID.canonical_player_id("key-A") != CID.canonical_player_id("key-B")     # distinct entities distinct ids
    # names never an input: two different key_person with identical names -> different ids
    assert CID.canonical_player_id("p1") != CID.canonical_player_id("p2")
    # namespaces never collide on identical material
    assert CID.canonical_id("player", "X") != CID.canonical_id("team", "X")


def test_canonical_id_rejects_empty_material():
    with pytest.raises(ValueError):
        CID.canonical_id("player", "")
    with pytest.raises(ValueError):
        CID.canonical_id("player", None)


# ---- player identity reconciliation (Section 7/24, B) -----------------------------------------------------------
def _persons(rows):
    keys = ("key_person", "key_uuid", "key_mlbam", "key_retro", "key_bbref", "key_fangraphs",
            "name_last", "name_first", "mlb_played_first", "mlb_played_last")
    return [{k: r.get(k, "") for k in keys} for r in rows]


def test_player_exact_match_and_source_coverage():
    rec = PI.reconcile_from_persons(_persons([
        {"key_person": "p1", "key_mlbam": "100", "key_retro": "r1", "name_last": "A"},
        {"key_person": "p2", "key_mlbam": "200", "name_last": "B"},
    ]))
    assert rec.stats["canonicalPlayers"] == 2
    assert rec.stats["bySource"]["mlbam"]["matchedExact"] == 2
    assert rec.resolved["mlbam"]["100"] == CID.canonical_player_id("p1")


def test_player_ambiguous_source_id_fails_closed_no_silent_collapse():
    # one mlbam id claimed by TWO chadwick persons -> AMBIGUOUS, excluded from resolved (no fuzzy auto-resolution)
    rec = PI.reconcile_from_persons(_persons([
        {"key_person": "p1", "key_mlbam": "999"},
        {"key_person": "p2", "key_mlbam": "999"},
    ]))
    amb = [b for b in rec.bridge_player_identity if b["sourceId"] == "999"]
    assert len(amb) == 1 and amb[0]["resolutionStatus"] == PI.AMBIGUOUS
    assert amb[0]["canonicalPlayerId"] is None
    assert sorted(amb[0]["candidateCanonicalPlayerIds"]) == sorted(
        {CID.canonical_player_id("p1"), CID.canonical_player_id("p2")})
    assert "999" not in rec.resolved["mlbam"]           # unusable downstream
    assert rec.stats["bySource"]["mlbam"]["ambiguous"] == 1


def test_player_duplicate_key_person_is_source_conflict():
    rec = PI.reconcile_from_persons(_persons([
        {"key_person": "dup", "key_mlbam": "1"},
        {"key_person": "dup", "key_mlbam": "1"},
    ]))
    assert rec.stats["duplicateKeyPerson"] == 1
    assert any(d["resolutionStatus"] == PI.SOURCE_CONFLICT for d in rec.dim_player)


def test_player_names_never_collapse_distinct_people():
    rec = PI.reconcile_from_persons(_persons([
        {"key_person": "p1", "key_mlbam": "1", "name_last": "Smith", "name_first": "John"},
        {"key_person": "p2", "key_mlbam": "2", "name_last": "Smith", "name_first": "John"},
    ]))
    assert rec.stats["canonicalPlayers"] == 2          # identical names, different people, never merged


# ---- statcast normalization (Section 10/43/44, C/D) -------------------------------------------------------------
_RESOLVED = {"100": CID.canonical_player_id("bp"), "200": CID.canonical_player_id("pp")}


def _syn_manifest_and_root(tmp: Path, rows_csv: str) -> tuple[dict, Path]:
    root = tmp / "bronze"
    (root / "statcast").mkdir(parents=True)
    f = root / "statcast" / "syn.csv"
    f.write_text(rows_csv, encoding="utf-8")
    manifest = {"manifestContract": BA.BRONZE_MANIFEST_CONTRACT, "partitions": [
        {"partitionId": "sc-syn", "source": "statcast", "year": 2019, "relativePath": "statcast/syn.csv",
         "rowCount": rows_csv.strip().count("\n"), "fileSha256": sha256_bytes(f.read_bytes()),
         "status": "COMPLETE", "naturalKeys": None, "columnNames": rows_csv.splitlines()[0].split(",")}]}
    return manifest, root


_SC_HEADER = "game_pk,game_date,game_year,game_type,home_team,away_team,inning,inning_topbot,at_bat_number,pitch_number,batter,pitcher,stand,p_throws,pitch_type,release_speed,bb_type,events,description,des"


def test_statcast_deterministic_pitch_and_pa_lineage(tmp_path):
    csv = _SC_HEADER + "\n" + "\n".join([
        "1,2019-04-01,2019,R,NYY,BOS,1,Top,1,1,100,200,R,R,FF,95.0,,,ball,",
        "1,2019-04-01,2019,R,NYY,BOS,1,Top,1,2,100,200,R,R,SL,88.0,ground_ball,field_out,hit_into_play,groundout",
    ])
    m, root = _syn_manifest_and_root(tmp_path, csv)
    a = SN.normalize_statcast(m, root, _RESOLVED)
    b = SN.normalize_statcast(m, root, _RESOLVED)
    assert [r["canonicalPitchId"] for r in a.fact_pitch] == [r["canonicalPitchId"] for r in b.fact_pitch]  # deterministic
    assert a.stats["sourcePitchRows"] == 2 and a.stats["acceptedPitchRows"] == 2 and a.stats["reconciles"]
    assert len(a.fact_pa) == 1                          # both pitches -> one canonical PA
    pa = a.fact_pa[0]
    assert pa["pitchCount"] == "2" and pa["firstPitchNumber"] == "1" and pa["lastPitchNumber"] == "2"
    assert pa["paEvent"] == "field_out"                 # final-pitch event carries the PA outcome


def test_statcast_unresolved_batter_fails_closed(tmp_path):
    csv = _SC_HEADER + "\n1,2019-04-01,2019,R,NYY,BOS,1,Top,1,1,777,200,R,R,FF,95,,,ball,"
    m, root = _syn_manifest_and_root(tmp_path, csv)
    a = SN.normalize_statcast(m, root, _RESOLVED)       # mlbam 777 not resolved -> unresolved, not fabricated
    assert a.stats["unresolvedPitchRows"] == 1 and a.stats["acceptedPitchRows"] == 0 and a.stats["reconciles"]
    assert a.fact_pitch == []


def test_statcast_duplicate_natural_key_rejected(tmp_path):
    csv = _SC_HEADER + "\n" + "\n".join([
        "1,2019-04-01,2019,R,NYY,BOS,1,Top,1,1,100,200,R,R,FF,95,,,ball,",
        "1,2019-04-01,2019,R,NYY,BOS,1,Top,1,1,100,200,R,R,FF,95,,,ball,",   # dup (game,ab,pitch)
    ])
    m, root = _syn_manifest_and_root(tmp_path, csv)
    a = SN.normalize_statcast(m, root, _RESOLVED)
    assert a.stats["duplicateNaturalKeys"] == 1 and a.stats["acceptedPitchRows"] == 1 and a.stats["reconciles"]


# ---- temporal / seal (Section 12/13, E) -------------------------------------------------------------------------
def test_publication_rejects_sealed_season(tmp_path):
    with pytest.raises(SP.SilverTablePublishError):
        SP.publish_silver_table(silver_root=tmp_path, contract=CT.dim_team_contract([2025]),
                                rows=[{"canonicalTeamId": "team-x", "teamAbbrev": "NYY", "aliases": []}],
                                bronze_manifest={}, source_partition_ids=["p"], code_modules=[SN],
                                field_order=["canonicalTeamId", "teamAbbrev", "aliases"])


def test_pitch_contract_classifies_outcome_fields_as_event_result():
    c = CT.fact_statcast_pitch_contract([2019])
    assert c["fieldClasses"]["events"] == CT.EVENT_RESULT
    assert c["fieldClasses"]["description"] == CT.EVENT_RESULT
    assert c["fieldClasses"]["batterCanonicalPlayerId"] == CT.IDENTITY
    assert "knowledge time unavailable" in " ".join(c["knownLimitations"]).lower()


# ---- silver authority: publish / verify / tamper / clone / partial / quarantine (Section 30/31, F/G) -------------
def _publish_one(silver: Path):
    return SP.publish_silver_table(
        silver_root=silver, contract=CT.dim_team_contract([2019]),
        rows=[{"canonicalTeamId": CID.canonical_team_id("NYY"), "teamAbbrev": "NYY", "aliases": []},
              {"canonicalTeamId": CID.canonical_team_id("BOS"), "teamAbbrev": "BOS", "aliases": []}],
        bronze_manifest={}, source_partition_ids=["sc-1"], code_modules=[SN],
        field_order=["canonicalTeamId", "teamAbbrev", "aliases"])


def test_publish_verify_and_quarantine(tmp_path):
    r = _publish_one(tmp_path)
    assert r["quarantine"] == "QUARANTINED" and r["modelEligible"] is False and r["approvedForTraining"] is False
    v = SP.verify_silver_table(tmp_path, r["manifestSha256"])
    assert v["rowCount"] == 2 and v["quarantine"] == "QUARANTINED"


def test_quarantine_barrier_blocks_model_binding(tmp_path):
    r = _publish_one(tmp_path)
    with pytest.raises(SP.SilverTableNotModelEligibleError):
        SP.assert_not_model_eligible(r["datasetVersionId"])


def test_tampered_object_fails_verification(tmp_path):
    r = _publish_one(tmp_path)
    obj = tmp_path / "objects" / "sha256" / r["manifestSha256"] / "object.parquet"
    obj.write_bytes(obj.read_bytes() + b"x")           # tamper the immutable object bytes
    with pytest.raises(SP.SilverTablePublishError):
        SP.verify_silver_table(tmp_path, r["manifestSha256"])


def test_tampered_registration_fails_verification(tmp_path):
    r = _publish_one(tmp_path)
    reg = tmp_path / "silver-table-registrations" / "objects" / "sha256" / f"{r['registrationSha256']}.json"
    body = json.loads(reg.read_bytes()); body["modelEligible"] = True
    reg.write_bytes(canonical_json_bytes(body))         # content no longer hashes to its filename
    with pytest.raises(SP.SilverTablePublishError):
        SP.verify_silver_table(tmp_path, r["manifestSha256"])


def test_clone_at_unregistered_path_is_not_authoritative(tmp_path):
    r = _publish_one(tmp_path)
    src = tmp_path / "objects" / "sha256" / r["manifestSha256"]
    clone_root = tmp_path / "clone"
    (clone_root / "objects" / "sha256" / r["manifestSha256"]).mkdir(parents=True)
    shutil.copytree(src, clone_root / "objects" / "sha256" / r["manifestSha256"], dirs_exist_ok=True)
    with pytest.raises(SP.SilverTablePublishError):    # no registry at the clone root -> unregistered
        SP.verify_silver_table(clone_root, r["manifestSha256"])


def test_partial_publication_fails_verification(tmp_path):
    r = _publish_one(tmp_path)
    (tmp_path / "objects" / "sha256" / r["manifestSha256"] / "transformation-receipt.json").unlink()
    with pytest.raises(SP.SilverTablePublishError):
        SP.verify_silver_table(tmp_path, r["manifestSha256"])


def test_index_stray_field_rejected(tmp_path):
    r = _publish_one(tmp_path)
    reg = tmp_path / "silver-table-registry.json"
    body = json.loads(reg.read_bytes())
    key = next(iter(body["datasets"]))
    body["datasets"][key]["sourceRoot"] = "/evil"       # index must carry ONLY the locator
    reg.write_bytes(canonical_json_bytes(body))
    with pytest.raises(SP.SilverTablePublishError):
        SP.verify_silver_table(tmp_path, r["manifestSha256"])


# ---- reproducibility (Section 33, H) ----------------------------------------------------------------------------
def test_idempotent_and_input_sensitive_identity(tmp_path):
    r1 = _publish_one(tmp_path)
    r2 = _publish_one(tmp_path)
    assert r1["manifestSha256"] == r2["manifestSha256"]                         # same input -> same identity
    assert len(list((tmp_path / "objects" / "sha256").iterdir())) == 1          # reused, not duplicated
    r3 = SP.publish_silver_table(silver_root=tmp_path, contract=CT.dim_team_contract([2019]),
                                 rows=[{"canonicalTeamId": CID.canonical_team_id("LAD"), "teamAbbrev": "LAD",
                                        "aliases": []}], bronze_manifest={}, source_partition_ids=["sc-1"],
                                 code_modules=[SN], field_order=["canonicalTeamId", "teamAbbrev", "aliases"])
    assert r3["valueDigestSha256"] != r1["valueDigestSha256"]                   # changed input -> changed identity


# ---- Bronze authority + immutability (Section 4/21/32, A) --------------------------------------------------------
def test_bronze_manifest_verifies_against_real_corpus():
    m = BA.verify_bronze_manifest()                    # read-only: SHA + contract + not-model-eligible
    assert m["manifestContract"] == BA.BRONZE_MANIFEST_CONTRACT
    cov = BA.assert_expected_coverage(m)
    assert cov["statcast"]["rows"] == 3929155 and cov["chadwick"]["rows"] == 518743


def test_bronze_seal_violation_rejected():
    bad = {"partitions": [{"partitionId": "x", "source": "statcast", "year": 2025, "rowCount": 1,
                           "status": "COMPLETE", "relativePath": "statcast/x.csv"}]}
    with pytest.raises(BA.BronzeAuthorityError):
        BA.assert_expected_coverage(bad)
