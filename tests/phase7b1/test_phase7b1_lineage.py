"""Phase 7B1 — final lineage-cleanup tests (fixes 1/2/3).

Covers: (1) evidence-based classification of Statcast-only games (home/away SOURCE_CONFLICT vs
RETROSHEET_SOURCE_ABSENT vs UNRESOLVED_SOURCE_GAP), (2) exact-source-input embedding with the 2,196-partition
accounting, and (3) partitioned lineage regeneration that reuses child bytes unchanged (values preserved) while
producing a new immutable identity with exact governed source ids. Hermetic; no full corpus needed.
"""
from __future__ import annotations

import json

import pytest

from server.sports_silver import canonical_ids as CID
from server.sports_silver import contracts as CT
from server.sports_silver import game_identity as GI
from server.sports_silver import silver_publication as SP
from server.sports_silver import statcast_normalize as SN


# ---- fix 1: evidence-based Statcast-only classification --------------------------------------------------------
def _rg(date, home, vis, gid="g", num="0"):
    return {"gameDate": date, "retroHomeTeam": home, "retroVisTeam": vis, "retroGameId": gid, "gameNumber": num}


def test_classify_home_away_swap_is_source_conflict():
    # Statcast says TOR home vs WSH; Retrosheet has the SAME date+teams with home/away REVERSED (WAS home) -> conflict
    so = [{"mlbamGamePk": "1", "gameDate": "2020-07-29", "homeTeam": "TOR", "awayTeam": "WSH", "season": "2020", "gameType": "R"}]
    retro = [_rg("20200729", "WAS", "TOR", gid="WAS...")]
    out = GI.classify_statcast_only(so, retro, {"TOR": "TOR", "WSH": "WAS"})
    assert out["tally"] == {GI.SOURCE_CONFLICT: 1}
    assert out["perGame"][0]["sourceReason"] == GI.SOURCE_CONFLICT
    assert out["perGame"][0]["retroGameSameDateReversed"] == 1
    assert out["regularSeasonCount"] == 1 and out["postseasonCount"] == 0


def test_classify_no_retro_on_date_is_source_absent():
    # postseason-style: Statcast game on a date the (regular-season) Retrosheet source does not cover at all
    so = [{"mlbamGamePk": "2", "gameDate": "2020-10-20", "homeTeam": "LAD", "awayTeam": "TB", "season": "2020", "gameType": "W"}]
    retro = [_rg("20200715", "LAN", "TBA")]                 # Retrosheet has games, but not on 2020-10-20
    out = GI.classify_statcast_only(so, retro, {"LAD": "LAN", "TB": "TBA"})
    assert out["tally"] == {GI.RETROSHEET_SOURCE_ABSENT: 1}
    assert out["postseasonCount"] == 1 and out["regularSeasonCount"] == 0


def test_classify_teams_meet_but_game_unresolved_is_gap():
    # Retrosheet has games that date and the teams meet that season, but not this exact game/orientation -> gap
    so = [{"mlbamGamePk": "3", "gameDate": "2021-06-01", "homeTeam": "NYY", "awayTeam": "BOS", "season": "2021", "gameType": "R"}]
    retro = [_rg("20210601", "TBA", "TOR"), _rg("20210715", "NYA", "BOS")]   # NYA/BOS meet later, not on 06-01
    out = GI.classify_statcast_only(so, retro, {"NYY": "NYA", "BOS": "BOS", "TB": "TBA", "TOR": "TOR"})
    assert out["perGame"][0]["sourceReason"] == GI.UNRESOLVED_SOURCE_GAP


# ---- fix 3: exact source-input embedding + value-digest independence -------------------------------------------
_FO = ["canonicalTeamId", "teamAbbrev", "aliases"]
_ROWS = [{"canonicalTeamId": CID.canonical_team_id("NYY"), "teamAbbrev": "NYY", "aliases": []}]
_SI = {"bronzeManifestSha256": "b" * 64, "sourceCount": 2, "sources": [
    {"partitionId": "statcast/regular/year=2019/x", "source": "statcast", "fileSha256": "a" * 64, "status": "COMPLETE", "rowCount": 5},
    {"partitionId": "chadwick/shard-00", "source": "chadwick", "fileSha256": "c" * 64}]}


def test_source_inputs_recorded_and_value_digest_independent(tmp_path):
    vague = SP.publish_silver_table(silver_root=tmp_path, contract=CT.dim_team_contract([2019]), rows=_ROWS,
        bronze_manifest={}, source_partition_ids=["statcast", "retrosheet"], code_modules=[SN], field_order=_FO)
    exact = SP.publish_silver_table(silver_root=tmp_path, contract=CT.dim_team_contract([2019]), rows=_ROWS,
        bronze_manifest={}, source_partition_ids=[], code_modules=[SN], field_order=_FO, source_inputs=_SI)
    # same rows -> identical value digest; different lineage -> different content address (new immutable identity)
    assert exact["valueDigestSha256"] == vague["valueDigestSha256"]
    assert exact["manifestSha256"] != vague["manifestSha256"]
    assert exact["quarantine"] == "QUARANTINED" and exact["modelEligible"] is False
    SP.verify_silver_table(tmp_path, exact["manifestSha256"])
    receipt = json.loads((tmp_path / "objects" / "sha256" / exact["manifestSha256"] / "transformation-receipt.json").read_bytes())
    assert receipt["governedSourceInputs"]["sourceCount"] == 2
    assert receipt["sourcePartitionIds"] == sorted(["statcast/regular/year=2019/x", "chadwick/shard-00"])  # exact, no labels
    assert "statcast" not in receipt["sourcePartitionIds"] and "retrosheet" not in receipt["sourcePartitionIds"]


# ---- fix 2/3: partitioned regeneration reuses child bytes, new identity, exact lineage --------------------------
def _pub_partitioned(silver):
    parts = [("2019", "retrosheet-events-2019", [{"canonicalGameId": "g1", "retroGameId": "r1", "season": "2019"}]),
             ("2020", "retrosheet-events-2020", [{"canonicalGameId": "g2", "retroGameId": "r2", "season": "2020"}])]
    fo = ["canonicalGameId", "retroGameId", "season"]
    # publish via a minimal contract-compatible table (reuse dim_park contract shape is wrong; use retrosheet_event)
    c = CT.fact_retrosheet_event_contract([2019, 2020])
    fo = ["canonicalGameId", "retroGameId", "eventSequence", "retroBatterId", "batterCanonicalPlayerId", "season",
          "inning", "half", "count", "eventText", "pitches", "sourceArchive", "sourceMember", "sourceLine"]
    def rows(rid, y):
        return [{"canonicalGameId": "g" + y, "retroGameId": rid, "eventSequence": "1", "retroBatterId": "b", "season": y}]
    it = [("2019", "retrosheet-events-2019", rows("r1", "2019")), ("2020", "retrosheet-events-2020", rows("r2", "2020"))]
    return SP.publish_partitioned_silver_table(silver_root=silver, contract=c, partitions_iter=iter(it),
        bronze_manifest={}, code_modules=[SN], field_order=fo)


def test_partitioned_regeneration_new_identity_same_child_bytes(tmp_path):
    old = _pub_partitioned(tmp_path)
    old_children = {p.stem for p in (tmp_path / "partitioned" / old["manifestSha256"] / "children").glob("*.parquet")}
    si = {"bronzeManifestSha256": "b" * 64, "sourceCount": 2, "sources": [
        {"partitionId": "retrosheet/events/2019eve", "source": "retrosheet", "fileSha256": "a" * 64},
        {"partitionId": "retrosheet/events/2020eve", "source": "retrosheet", "fileSha256": "d" * 64}]}
    new = SP.regenerate_partitioned_silver_table(silver_root=tmp_path, old_manifest_sha=old["manifestSha256"],
        contract=CT.fact_retrosheet_event_contract([2019, 2020]), code_modules=[SN], source_inputs=si,
        child_source_id_fn=lambda pk, old_id: f"retrosheet/events/{pk}eve")
    assert new["manifestSha256"] != old["manifestSha256"]                       # new immutable identity
    assert new["rowCount"] == old["rowCount"] and new["childCount"] == old["childCount"]
    new_children = {p.stem for p in (tmp_path / "partitioned" / new["manifestSha256"] / "children").glob("*.parquet")}
    assert new_children == old_children                                          # child bytes/shas unchanged (values preserved)
    mf = json.loads((tmp_path / "partitioned" / new["manifestSha256"] / "manifest.json").read_bytes())
    assert mf["governedSourceInputs"]["sourceCount"] == 2
    assert {c["sourcePartitionId"] for c in mf["children"]} == {"retrosheet/events/2019eve", "retrosheet/events/2020eve"}
    SP.verify_partitioned_silver_table(tmp_path, new["manifestSha256"])
    SP.verify_partitioned_silver_table(tmp_path, old["manifestSha256"])          # old object still intact (never edited in place)
