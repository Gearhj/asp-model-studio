"""Full-corpus Phase 7B1 normalization driver (Sections 9, 12, 13, 17, 22).

Runs the complete Bronze->Silver normalization in dependency order over the authorized 2019-2024 corpus and publishes
every object through the governed (immutable, quarantined, content-addressed) authority. Retrosheet facts are published
partitioned by SEASON and Statcast facts partitioned by DAY, so the 3.9M-pitch corpus is never materialized whole.
Returns a full cross-source reconciliation report. Never writes/moves/repairs Bronze; never makes Silver model-eligible.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from . import bronze_authority as BA
from . import canonical_ids as CID
from . import contracts as CT
from . import game_identity as GI
from . import player_identity as PI
from . import retrosheet_parse as RP
from . import silver_publication as SP
from . import statcast_normalize as SN
from . import team_authority as TA

YEARS = (2019, 2020, 2021, 2022, 2023, 2024)
_CODE = [BA, CID, PI, RP, SN, TA, GI, SP]


def _publish(silver, contract, rows, bronze_manifest, source_parts, field_order, published):
    r = SP.publish_silver_table(silver_root=silver, contract=contract, rows=rows, bronze_manifest=bronze_manifest,
                                source_partition_ids=source_parts, code_modules=_CODE, field_order=field_order)
    published.append(r)
    return r


def run(silver_root: Path, *, years=YEARS, statcast_partition_filter: Callable | None = None) -> dict[str, Any]:
    silver_root = Path(silver_root)
    t0 = time.time()
    stage_times: dict[str, float] = {}
    m = BA.verify_bronze_manifest()
    coverage = BA.assert_expected_coverage(m)
    before = BA.inventory(m, BA.DEFAULT_BRONZE_ROOT)
    published: list[dict[str, Any]] = []
    root = BA.DEFAULT_BRONZE_ROOT
    seasons = list(years)

    # 1-2. player identity ---------------------------------------------------------------------------------------
    t = time.time()
    prec = PI.reconcile_players(m)
    chad_parts = [p.partition_id for p in BA.partitions(m, source="chadwick")]
    dp_fields = ["canonicalPlayerId", "chadwickKeyPerson", "chadwickKeyUuid", "mlbamId", "retrosheetId", "bbrefId",
                 "fangraphsId", "nameLast", "nameFirst", "mlbPlayedFirst", "mlbPlayedLast", "resolutionStatus",
                 "sourceProvenance"]
    br_fields = ["sourceSystem", "sourceId", "canonicalPlayerId", "candidateCanonicalPlayerIds", "resolutionStatus",
                 "resolutionMethod"]
    _publish(silver_root, CT.dim_player_contract(seasons), prec.dim_player, m, chad_parts, dp_fields, published)
    _publish(silver_root, CT.bridge_player_identity_contract(seasons), prec.bridge_player_identity, m, chad_parts,
             br_fields, published)
    resolved_mlbam = prec.resolved["mlbam"]
    resolved_retro = prec.resolved["retrosheet"]
    stage_times["player_identity"] = time.time() - t

    # 3. statcast game metadata (light) -------------------------------------------------------------------------
    t = time.time()
    sc_games = SN.extract_statcast_games(m, root, partition_filter=statcast_partition_filter)
    stage_times["statcast_game_extract"] = time.time() - t

    # 4. retrosheet parse (all years) ---------------------------------------------------------------------------
    t = time.time()
    rs_all_games: list[dict[str, Any]] = []
    team_files: list[dict[str, str]] = []
    events_by_year: dict[int, RP.EventResult] = {}
    gamelogs_by_year: dict[int, RP.GameLogResult] = {}
    for y in years:
        ev = RP.parse_events(m, root, y)
        events_by_year[y] = ev
        rs_all_games.extend(ev.games)
        team_files.extend(RP.parse_team_file(m, root, y))
        gamelogs_by_year[y] = RP.parse_game_logs(m, root, y)
    stage_times["retrosheet_parse"] = time.time() - t

    # 5. team map + game bridge --------------------------------------------------------------------------------
    t = time.time()
    team_map = TA.derive_team_map(sc_games, rs_all_games)
    bridge = GI.reconcile_games(sc_games, rs_all_games, team_map["map"])
    retro_to_canonical = bridge.retro_to_canonical
    retro_team_to_canonical = {rs: CID.canonical_team_id(sc) for sc, rs in team_map["map"].items()}
    stage_times["identity_bridge"] = time.time() - t

    # 6. dims: team, game, bridge_game, park -------------------------------------------------------------------
    t = time.time()
    sc_team_codes = {g["homeTeam"] for g in sc_games} | {g["awayTeam"] for g in sc_games}
    dim_team_rows = TA.dim_team_rows(sc_team_codes, team_map["map"], team_files)
    dt_fields = ["canonicalTeamId", "teamAbbrev", "aliases", "retroTeamCode", "nickname", "city"]
    _publish(silver_root, CT.dim_team_contract(seasons), dim_team_rows, m, ["chadwick-schedule"], dt_fields, published)
    game_fields = ["canonicalGameId", "mlbamGamePk", "gameDate", "season", "homeTeam", "awayTeam", "gameType",
                   "retrosheetGameId", "gameNumber", "reconciliationStatus"]
    _publish(silver_root, CT.dim_game_contract(seasons), bridge.dim_game, m, ["statcast", "retrosheet"], game_fields, published)
    bg_fields = ["canonicalGameId", "mlbamGamePk", "retrosheetGameId", "gameDate", "homeTeam", "awayTeam",
                 "resolutionStatus", "resolutionMethod"]
    _publish(silver_root, CT.bridge_game_identity_contract(seasons), bridge.bridge_game_identity, m,
             ["statcast", "retrosheet"], bg_fields, published)
    # dim_park from retro game sites
    parks: dict[str, dict[str, Any]] = {}
    for g in rs_all_games:
        site = g.get("site")
        if site:
            parks.setdefault(site, {"canonicalParkId": CID.canonical_park_id(site), "retroParkId": site, "seasons": []})
    dim_park_rows = list(parks.values())
    _publish(silver_root, CT.dim_park_contract(seasons), dim_park_rows, m, ["retrosheet"],
             ["canonicalParkId", "retroParkId", "seasons"], published)
    stage_times["dims"] = time.time() - t

    # 7. retrosheet facts (partitioned by season) --------------------------------------------------------------
    t = time.time()
    reject_artifact: list[dict[str, Any]] = []
    rs_recon = _publish_retrosheet_facts(silver_root, m, seasons, events_by_year, gamelogs_by_year,
                                         retro_to_canonical, resolved_retro, retro_team_to_canonical, reject_artifact, published)
    stage_times["retrosheet_facts"] = time.time() - t

    # 8. full statcast normalization (partitioned by day) ------------------------------------------------------
    t = time.time()
    sc_recon = _publish_statcast_facts(silver_root, m, root, seasons, resolved_mlbam, statcast_partition_filter, published)
    stage_times["statcast_facts"] = time.time() - t

    after = BA.inventory(m, BA.DEFAULT_BRONZE_ROOT)
    report = {
        "schemaVersion": "PHASE_7B1_FULL_RECONCILIATION_V1", "years": list(years),
        "bronzeManifestSha256": BA.EXPECTED_BRONZE_MANIFEST_SHA256, "bronzeCoverage": coverage,
        "bronzeImmutability": {"beforeDigest": before["inventoryDigest"], "afterDigest": after["inventoryDigest"],
                               "identical": before["inventoryDigest"] == after["inventoryDigest"], "files": before["fileCount"]},
        "playerIdentity": prec.stats, "teamMap": {"status": team_map["status"], "mapped": team_map["mappedCount"],
                                                  "nonIdentity": {k: v for k, v in team_map["map"].items() if k != v},
                                                  "conflicts": team_map["conflicts"], "unresolved": team_map["unresolvedStatcastCodes"]},
        "gameIdentity": bridge.stats, "retrosheet": rs_recon, "statcast": sc_recon,
        "rejectArtifactRows": len(reject_artifact),
        "publishedObjects": [{"table": p["tableName"], "rows": p.get("rowCount"), "childCount": p.get("childCount"),
                              "manifestSha256": p["manifestSha256"], "quarantine": p["quarantine"],
                              "modelEligible": p["modelEligible"]} for p in published],
        "stageTimesSec": {k: round(v, 1) for k, v in stage_times.items()}, "totalTimeSec": round(time.time() - t0, 1),
    }
    return report


def _publish_retrosheet_facts(silver, m, seasons, events_by_year, gamelogs_by_year, retro_to_canonical, resolved_retro,
                              retro_team_to_canonical, reject_artifact, published) -> dict[str, Any]:
    ev_fields = ["canonicalGameId", "retroGameId", "eventSequence", "retroBatterId", "batterCanonicalPlayerId",
                 "season", "inning", "half", "count", "eventText", "pitches", "sourceArchive", "sourceMember", "sourceLine"]
    lu_fields = ["canonicalGameId", "retroGameId", "retroPlayerId", "playerCanonicalPlayerId", "recordType", "season",
                 "homeAway", "battingOrder", "fieldPosition", "playerName", "sourceArchive", "sourceMember", "sourceLine"]
    ump_fields = ["canonicalGameId", "retroGameId", "umpirePosition", "retroUmpireId", "umpireCanonicalPlayerId",
                  "season", "sourceArchive", "sourceMember"]
    tg_fields = ["canonicalGameId", "retroGameId", "canonicalTeamId", "retroTeamCode", "homeAway", "season", "gameDate",
                 "gameNumber", "retroOpponentCode", "parkId", "runsScored", "runsAllowed", "retroManagerId",
                 "sourceArchive", "sourceMember", "sourceLine"]
    pg_fields = ["canonicalGameId", "canonicalPlayerId", "canonicalTeamId", "retroGameId", "season", "homeAway",
                 "startedGame", "battingOrder", "fieldPosition", "retroPlayerId", "sourceArchive", "sourceMember"]

    def cgame(retro_id):
        return retro_to_canonical.get(retro_id)

    # per-game (home retro code, visitor retro code) from the parsed event game headers -> lets a lineup record's
    # home/away side resolve to the player's canonical team (no fabricated identity; None if the game/side is unknown).
    game_sides: dict[str, tuple] = {}
    for _y, _ev in events_by_year.items():
        for g in _ev.games:
            game_sides[g["retroGameId"]] = (g.get("retroHomeTeam"), g.get("retroVisTeam"))

    def player_team(retro_game_id, home_away):
        sides = game_sides.get(retro_game_id)
        if not sides:
            return None
        retro_code = sides[0] if home_away == "home" else sides[1]
        return retro_team_to_canonical.get(retro_code)

    counts = {"events": 0, "eventsUnresolvedGame": 0, "lineup": 0, "umpires": 0, "teamGames": 0, "playerGames": 0,
              "eventsUnresolvedBatter": 0}

    def ev_parts():
        for y, ev in events_by_year.items():
            rows = []
            for e in ev.events:
                cg = cgame(e["retroGameId"])
                if cg is None:
                    counts["eventsUnresolvedGame"] += 1
                    reject_artifact.append({"stage": "event", "reasonCode": "UNRESOLVED_GAME", "retroGameId": e["retroGameId"]})
                    continue
                bcid = resolved_retro.get(e["retroBatterId"])
                if bcid is None:
                    counts["eventsUnresolvedBatter"] += 1
                rows.append({**e, "canonicalGameId": cg, "batterCanonicalPlayerId": bcid})
                counts["events"] += 1
            yield (str(y), f"retrosheet-events-{y}", rows)

    def lu_parts():
        for y, ev in events_by_year.items():
            rows = []
            for l in ev.lineup:
                cg = cgame(l["retroGameId"])
                if cg is None:
                    continue
                rows.append({**l, "canonicalGameId": cg, "playerCanonicalPlayerId": resolved_retro.get(l["retroPlayerId"])})
                counts["lineup"] += 1
            yield (str(y), f"retrosheet-events-{y}", rows)

    def ump_parts():
        for y, ev in events_by_year.items():
            rows = []
            for u in ev.umpires:
                cg = cgame(u["retroGameId"])
                if cg is None:
                    continue
                rows.append({**u, "canonicalGameId": cg, "umpireCanonicalPlayerId": resolved_retro.get(u["retroUmpireId"])})
                counts["umpires"] += 1
            yield (str(y), f"retrosheet-events-{y}", rows)

    def tg_parts():
        for y, gl in gamelogs_by_year.items():
            rows = []
            for tg in gl.team_games:
                cg = cgame(tg["retroGameId"])
                if cg is None:                       # fail-closed: no team-game fact without a canonical game identity
                    counts["teamGamesUnresolvedGame"] = counts.get("teamGamesUnresolvedGame", 0) + 1
                    reject_artifact.append({"stage": "team_game", "reasonCode": "UNRESOLVED_GAME",
                                            "retroGameId": tg["retroGameId"]})
                    continue
                ctid = retro_team_to_canonical.get(tg["retroTeamCode"])
                rows.append({**tg, "canonicalGameId": cg, "canonicalTeamId": ctid})
                counts["teamGames"] += 1
            yield (str(y), f"retrosheet-gamelog-{y}", rows)

    def pg_parts():
        for y, ev in events_by_year.items():
            seen = set()
            rows = []
            for l in ev.lineup:
                if l["recordType"] != "start":
                    continue
                cg = cgame(l["retroGameId"])
                pcid = resolved_retro.get(l["retroPlayerId"])
                if cg is None or pcid is None:
                    continue
                key = (l["retroGameId"], pcid)
                if key in seen:
                    continue
                seen.add(key)
                # canonical team = the player's start side (home/away) mapped through the game header + derived team map
                rows.append({"canonicalGameId": cg, "canonicalPlayerId": pcid,
                             "canonicalTeamId": player_team(l["retroGameId"], l["homeAway"]),
                             "retroGameId": l["retroGameId"], "season": l["season"], "homeAway": l["homeAway"],
                             "startedGame": "true", "battingOrder": l["battingOrder"], "fieldPosition": l["fieldPosition"],
                             "retroPlayerId": l["retroPlayerId"], "sourceArchive": l["sourceArchive"],
                             "sourceMember": l["sourceMember"]})
                counts["playerGames"] += 1
            yield (str(y), f"retrosheet-events-{y}", rows)

    for contract, gen, fo in [
        (CT.fact_retrosheet_event_contract(seasons), ev_parts, ev_fields),
        (CT.fact_lineup_participation_contract(seasons), lu_parts, lu_fields),
        (CT.fact_umpire_game_contract(seasons), ump_parts, ump_fields),
        (CT.fact_team_game_contract(seasons), tg_parts, tg_fields),
        (CT.fact_player_game_contract(seasons), pg_parts, pg_fields)]:
        r = SP.publish_partitioned_silver_table(silver_root=silver, contract=contract, partitions_iter=gen(),
                                                bronze_manifest=m, code_modules=_CODE, field_order=fo)
        published.append(r)
    return counts


def _publish_statcast_facts(silver, m, root, seasons, resolved_mlbam, sc_filter, published) -> dict[str, Any]:
    acct = {"source": 0, "accepted": 0, "rejected": 0, "unresolved": 0, "dup": 0, "pa": 0, "partitions": 0,
            "bySeason": {}}

    def pitch_parts():
        for p, table in BA.iter_source_frames(m, root, "statcast", only_nonempty=True, partition_filter=sc_filter):
            r = SN.normalize_partition(table, p.partition_id, resolved_mlbam)
            acct["source"] += r.counts["source"]; acct["accepted"] += r.counts["accepted"]
            acct["rejected"] += r.counts["rejected"]; acct["unresolved"] += r.counts["unresolved"]
            acct["dup"] += r.counts["dup"]; acct["partitions"] += 1
            sy = None
            if r.fact_pitch:
                sy = r.fact_pitch[0]["season"] + ("-post" if "postseason" in p.relative_path else "-reg")
                bs = acct["bySeason"].setdefault(sy, {"source": 0, "accepted": 0, "unresolved": 0, "rejected": 0})
                bs["source"] += r.counts["source"]; bs["accepted"] += r.counts["accepted"]
                bs["unresolved"] += r.counts["unresolved"]; bs["rejected"] += r.counts["rejected"]
            yield (p.partition_id, p.partition_id, r.fact_pitch)

    r_pitch = SP.publish_partitioned_silver_table(silver_root=silver, contract=CT.fact_statcast_pitch_contract(seasons),
        partitions_iter=pitch_parts(), bronze_manifest=m, code_modules=_CODE, field_order=SN.PITCH_FIELDS)
    published.append(r_pitch)

    pa_total = {"pa": 0}
    def pa_parts():
        for p, table in BA.iter_source_frames(m, root, "statcast", only_nonempty=True, partition_filter=sc_filter):
            r = SN.normalize_partition(table, p.partition_id, resolved_mlbam)
            pa_total["pa"] += len(r.fact_pa)
            yield (p.partition_id, p.partition_id, r.fact_pa)

    r_pa = SP.publish_partitioned_silver_table(silver_root=silver, contract=CT.fact_statcast_plate_appearance_contract(seasons),
        partitions_iter=pa_parts(), bronze_manifest=m, code_modules=_CODE, field_order=SN.PA_FIELDS)
    published.append(r_pa)

    acct["outputPitches"] = r_pitch["rowCount"]
    acct["canonicalPAs"] = r_pa["rowCount"]
    acct["reconciles"] = (acct["source"] == acct["accepted"] + acct["rejected"] + acct["unresolved"])
    return acct
