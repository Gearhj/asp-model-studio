"""Phase 7B1 — full-corpus identity/parse/partitioned-authority tests (Section 20 expansion).

Covers the modules added for full-corpus completion: Retrosheet game-log + event parsing, data-derived team-code
authority, Statcast<->Retrosheet game identity (incl. doubleheaders / ambiguity / retro-only), the immutable PARTITIONED
Silver publication (missing / extra / reordered / tampered child + total-count fail-closed), and pipeline reconciliation
invariants. Hermetic (synthetic zip fixtures + tiny in-memory frames); no dependence on the full Bronze corpus. Kept out
of the frozen ``tests/sports_*_test.py`` gate collection.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_silver import canonical_ids as CID
from server.sports_silver import contracts as CT
from server.sports_silver import game_identity as GI
from server.sports_silver import retrosheet_parse as RP
from server.sports_silver import silver_publication as SP
from server.sports_silver import statcast_normalize as SN
from server.sports_silver import team_authority as TA


# ============================================================ Retrosheet parsing (Sections 5/6)
def _gl_row(date, gnum, vis, home, visscore, homescore, park, vmgr, hmgr):
    f = [""] * RP.GL_FIELD_COUNT
    f[RP.GL_DATE], f[RP.GL_GAMENUM] = date, gnum
    f[RP.GL_VISTEAM], f[RP.GL_HOMETEAM] = vis, home
    f[RP.GL_VISSCORE], f[RP.GL_HOMESCORE] = visscore, homescore
    f[RP.GL_PARKID] = park
    f[RP.GL_VIS_MANAGER_ID], f[RP.GL_VIS_MANAGER_NAME] = vmgr, "Vis Manager"
    f[RP.GL_HOME_MANAGER_ID], f[RP.GL_HOME_MANAGER_NAME] = hmgr, "Home Manager"
    return ",".join(f)


def _make_bronze(tmp: Path, year: int, *, gamelog_text: str, event_members: dict[str, str]) -> tuple[dict, Path]:
    root = tmp / "bronze"
    (root / "retrosheet" / "game-logs").mkdir(parents=True, exist_ok=True)
    (root / "retrosheet" / "events").mkdir(parents=True, exist_ok=True)
    gl_zip = root / "retrosheet" / "game-logs" / f"gl{year}.zip"
    with zipfile.ZipFile(gl_zip, "w") as z:
        z.writestr(f"gl{year}.txt", gamelog_text)
    ev_zip = root / "retrosheet" / "events" / f"{year}eve.zip"
    with zipfile.ZipFile(ev_zip, "w") as z:
        for name, text in event_members.items():
            z.writestr(name, text)
    manifest = {"manifestContract": "MLB_ADVANCED_BRONZE_SOURCE_MANIFEST_V1", "partitions": [
        {"partitionId": f"rs-gl-{year}", "source": "retrosheet", "year": year,
         "relativePath": f"retrosheet/game-logs/gl{year}.zip", "status": "COMPLETE"},
        {"partitionId": f"rs-ev-{year}", "source": "retrosheet", "year": year,
         "relativePath": f"retrosheet/events/{year}eve.zip", "status": "COMPLETE"}]}
    return manifest, root


def test_gamelog_parses_two_team_games_and_flags_malformed(tmp_path):
    good = _gl_row("20190401", "0", "BOS", "NYA", "3", "5", "NYC01", "mgrV", "mgrH")
    bad = ",".join(["x"] * 10)                              # wrong field count -> structured reject (never field-shift)
    m, root = _make_bronze(tmp_path, 2019, gamelog_text=good + "\n" + bad + "\n", event_members={})
    r = RP.parse_game_logs(m, root, 2019)
    assert r.parsed_games == 1 and len(r.team_games) == 2 and len(r.rejects) == 1
    home = [t for t in r.team_games if t["homeAway"] == "home"][0]
    assert home["retroTeamCode"] == "NYA" and home["runsScored"] == "5" and home["runsAllowed"] == "3"
    assert home["parkId"] == "NYC01" and home["retroGameId"] == "NYA201904010" and home["season"] == "2019"


def test_event_file_parses_identity_lineup_umpires_events(tmp_path):
    eva = "\n".join([
        "id,NYA201904010", "info,visteam,BOS", "info,hometeam,NYA", "info,date,2019/04/01",
        "info,number,0", "info,site,NYC01", "info,umphome,umpHP", "info,ump1b,ump1B",
        "start,bat001,Batter One,1,1,4", "start,bat002,Batter Two,0,1,6",
        "play,1,0,bat002,00,X,S8/G", "play,1,1,bat001,12,BSX,HR/F",
    ])
    m, root = _make_bronze(tmp_path, 2019, gamelog_text="", event_members={"NYA2019.EVA": eva, "TEAM2019": "NYA,A,New York,Yankees\nBOS,A,Boston,Red Sox"})
    ev = RP.parse_events(m, root, 2019)
    assert len(ev.games) == 1 and ev.games[0]["retroGameId"] == "NYA201904010"
    assert ev.games[0]["site"] == "NYC01" and ev.games[0]["season"] == "2019"
    assert ev.stats["events"] == 2 and ev.stats["starts"] == 2
    assert {u["umpirePosition"] for u in ev.umpires} == {"HP", "1B"}
    hr = [e for e in ev.events if e["eventText"].startswith("HR")][0]
    assert hr["retroBatterId"] == "bat001" and hr["inning"] == "1" and hr["eventSequence"] == "2"
    teams = RP.parse_team_file(m, root, 2019)
    assert {t["retroTeamCode"] for t in teams} == {"NYA", "BOS"}


# ============================================================ team-code authority (Section 7)
def _sc(date, home, away):
    return {"gameDate": date, "homeTeam": home, "awayTeam": away}


def _rs(date, home, vis, gid="g", num="0"):
    return {"gameDate": date, "retroHomeTeam": home, "retroVisTeam": vis, "retroGameId": gid, "gameNumber": num}


def test_team_map_derives_nonidentity_codes_by_schedule_alignment():
    # NYY<->NYA and LAD<->LAN are non-identity; BOS is identity. Alignment forces the unknowns uniquely.
    sc = [_sc("2019-04-01", "NYY", "BOS"), _sc("2019-04-02", "LAD", "NYY"), _sc("2019-04-03", "BOS", "LAD")]
    rs = [_rs("20190401", "NYA", "BOS"), _rs("20190402", "LAN", "NYA"), _rs("20190403", "BOS", "LAN")]
    out = TA.derive_team_map(sc, rs)
    assert out["status"] == TA.MATCHED_EXACT
    assert out["map"] == {"BOS": "BOS", "LAD": "LAN", "NYY": "NYA"}
    assert out["unresolvedStatcastCodes"] == []


def test_team_map_reports_conflict_when_two_codes_map_to_one():
    # deliberately inconsistent source: two statcast codes forced onto one retro code -> SOURCE_CONFLICT, not silent pick
    sc = [_sc("2019-04-01", "AAA", "ZZZ"), _sc("2019-04-02", "BBB", "ZZZ")]
    rs = [_rs("20190401", "RRR", "ZZZ"), _rs("20190402", "RRR", "ZZZ")]
    out = TA.derive_team_map(sc, rs)
    assert out["status"] in (TA.SOURCE_CONFLICT, TA.UNMATCHED)  # never a fabricated 1:1


# ============================================================ game identity (Section 8)
def test_game_identity_matches_by_date_and_mapped_teams():
    sc = [{"mlbamGamePk": "100", "gameDate": "2019-04-01", "homeTeam": "NYY", "awayTeam": "BOS", "season": "2019", "gameType": "R"}]
    rs = [_rs("20190401", "NYA", "BOS", gid="NYA201904010")]
    rec = GI.reconcile_games(sc, rs, {"NYY": "NYA", "BOS": "BOS"})
    assert rec.stats["matchedExact"] == 1 and rec.stats["ambiguous"] == 0
    assert rec.retro_to_canonical["NYA201904010"] == CID.canonical_game_id("100")
    assert rec.dim_game[0]["retrosheetGameId"] == "NYA201904010"


def test_game_identity_doubleheader_ordered_by_gamenumber():
    sc = [{"mlbamGamePk": "200", "gameDate": "2019-07-04", "homeTeam": "NYY", "awayTeam": "BOS", "season": "2019", "gameType": "R"},
          {"mlbamGamePk": "201", "gameDate": "2019-07-04", "homeTeam": "NYY", "awayTeam": "BOS", "season": "2019", "gameType": "R"}]
    rs = [_rs("20190704", "NYA", "BOS", gid="NYA201907041", num="1"),
          _rs("20190704", "NYA", "BOS", gid="NYA201907042", num="2")]
    rec = GI.reconcile_games(sc, rs, {"NYY": "NYA", "BOS": "BOS"})
    assert rec.stats["matchedExact"] == 2 and rec.stats["doubleheaderBuckets"] == 1
    # lowest game_pk -> lowest game-number
    assert rec.retro_to_canonical["NYA201907041"] == CID.canonical_game_id("200")
    assert rec.retro_to_canonical["NYA201907042"] == CID.canonical_game_id("201")


def test_game_identity_cardinality_mismatch_is_ambiguous_not_guessed():
    sc = [{"mlbamGamePk": "300", "gameDate": "2019-08-01", "homeTeam": "NYY", "awayTeam": "BOS", "season": "2019", "gameType": "R"},
          {"mlbamGamePk": "301", "gameDate": "2019-08-01", "homeTeam": "NYY", "awayTeam": "BOS", "season": "2019", "gameType": "R"}]
    rs = [_rs("20190801", "NYA", "BOS", gid="only1", num="1")]         # 2 statcast vs 1 retro
    rec = GI.reconcile_games(sc, rs, {"NYY": "NYA", "BOS": "BOS"})
    assert rec.stats["ambiguous"] == 2 and rec.retro_to_canonical == {}  # nothing fabricated


def test_game_identity_retro_only_surfaced():
    sc = [{"mlbamGamePk": "400", "gameDate": "2019-09-01", "homeTeam": "NYY", "awayTeam": "BOS", "season": "2019", "gameType": "R"}]
    rs = [_rs("20190901", "NYA", "BOS", gid="matched"), _rs("20190902", "NYA", "BOS", gid="retroonly")]
    rec = GI.reconcile_games(sc, rs, {"NYY": "NYA", "BOS": "BOS"})
    assert [r["retroGameId"] for r in rec.retro_only] == ["retroonly"]


# ============================================================ partitioned Silver authority (Section 16/30/31)
_PC = ["canonicalTeamId", "teamAbbrev", "aliases", "retroTeamCode", "nickname", "city"]


def _team_rows(*abbrevs):
    return [{"canonicalTeamId": CID.canonical_team_id(a), "teamAbbrev": a, "aliases": [], "retroTeamCode": a,
             "nickname": None, "city": None, "season": "2019"} for a in abbrevs]


def _publish_partitioned(silver: Path):
    parts = [("2019", "src-2019", _team_rows("NYY", "BOS")), ("2020", "src-2020", _team_rows("LAD"))]
    return SP.publish_partitioned_silver_table(silver_root=silver, contract=CT.dim_team_contract([2019, 2020]),
        partitions_iter=iter(parts), bronze_manifest={}, code_modules=[SN], field_order=_PC)


def test_partitioned_publish_and_verify(tmp_path):
    r = _publish_partitioned(tmp_path)
    assert r["childCount"] == 2 and r["rowCount"] == 3 and r["quarantine"] == "QUARANTINED" and r["modelEligible"] is False
    v = SP.verify_partitioned_silver_table(tmp_path, r["manifestSha256"])
    assert v["rowCount"] == 3 and v["childCount"] == 2


def test_partitioned_quarantine_barrier(tmp_path):
    r = _publish_partitioned(tmp_path)
    with pytest.raises(SP.SilverTableNotModelEligibleError):
        SP.assert_not_model_eligible(r["datasetVersionId"])       # partitioned dsid is also model-ineligible


def test_partitioned_idempotent(tmp_path):
    a = _publish_partitioned(tmp_path)
    b = _publish_partitioned(tmp_path)
    assert a["manifestSha256"] == b["manifestSha256"]             # identical inputs -> identical table identity
    assert len(list((tmp_path / "partitioned").glob("*/manifest.json"))) == 1


def test_partitioned_tampered_child_fails(tmp_path):
    r = _publish_partitioned(tmp_path)
    child = next((tmp_path / "partitioned" / r["manifestSha256"] / "children").glob("*.parquet"))
    child.write_bytes(child.read_bytes() + b"x")
    with pytest.raises(SP.SilverTablePublishError):
        SP.verify_partitioned_silver_table(tmp_path, r["manifestSha256"])


def test_partitioned_missing_child_fails(tmp_path):
    r = _publish_partitioned(tmp_path)
    child = next((tmp_path / "partitioned" / r["manifestSha256"] / "children").glob("*.parquet"))
    child.unlink()
    with pytest.raises(SP.SilverTablePublishError):
        SP.verify_partitioned_silver_table(tmp_path, r["manifestSha256"])


def test_partitioned_extra_stray_child_fails(tmp_path):
    r = _publish_partitioned(tmp_path)
    stray = (tmp_path / "partitioned" / r["manifestSha256"] / "children" / ("f" * 64 + ".parquet"))
    stray.write_bytes(b"stray")
    with pytest.raises(SP.SilverTablePublishError):
        SP.verify_partitioned_silver_table(tmp_path, r["manifestSha256"])


def test_partitioned_manifest_tamper_breaks_self_address(tmp_path):
    r = _publish_partitioned(tmp_path)
    mpath = tmp_path / "partitioned" / r["manifestSha256"] / "manifest.json"
    body = json.loads(mpath.read_bytes())
    body["totalRowCount"] = 999                                  # any edit breaks the content address
    mpath.write_bytes(canonical_json_bytes(body))
    with pytest.raises(SP.SilverTablePublishError):
        SP.verify_partitioned_silver_table(tmp_path, r["manifestSha256"])


# ============================================================ reconciliation invariant (Section 17)
def test_game_reconciliation_counts_partition_the_statcast_games():
    sc = [{"mlbamGamePk": str(i), "gameDate": "2019-04-01", "homeTeam": "NYY", "awayTeam": "BOS",
           "season": "2019", "gameType": "R"} for i in range(3)]
    rs = [_rs("20190401", "NYA", "BOS", gid="g1", num="1")]
    rec = GI.reconcile_games(sc, rs, {"NYY": "NYA", "BOS": "BOS"})
    s = rec.stats
    assert s["matchedExact"] + s["statcastOnly"] + s["ambiguous"] == s["statcastGames"] == 3   # exhaustive accounting
