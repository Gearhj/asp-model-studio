"""Phase 7B1 lineage cleanup (metadata-only regeneration) — fixes 1/2/3 against the EXISTING verified Silver outputs.

Regenerates every Silver object's immutable lineage so it identifies its EXACT governed Bronze inputs (partition/archive/
shard IDs + hashes) instead of aggregate labels, adds the full 2,196-partition Statcast source accounting (1,120
row-contributing + 1,076 COMPLETE_EMPTY), and produces the truthful game-reconciliation report (281 Statcast-only =
251 postseason RETROSHEET_SOURCE_ABSENT + 30 regular SOURCE_CONFLICT). It NEVER reprocesses the 3.9M pitches, never edits
an immutable object in place (each corrected object gets a new content address), and never changes a normalized row value
(value digests are asserted identical to the originals).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from . import bronze_authority as BA
from . import canonical_ids as CID
from . import contracts as CT
from . import game_identity as GI
from . import retrosheet_parse as RP
from . import silver_publication as SP
from . import team_authority as TA

YEARS = (2019, 2020, 2021, 2022, 2023, 2024)
_CODE = [BA, CID, CT, GI, RP, SP, TA]

# which exact Bronze sources each Silver table draws from
_RETRO_EVENT_TABLES = {"fact_retrosheet_event", "fact_lineup_participation", "fact_umpire_game", "fact_player_game"}
_RETRO_GAMELOG_TABLES = {"fact_team_game"}
_STATCAST_TABLES = {"fact_statcast_pitch", "fact_statcast_plate_appearance"}
_CHADWICK_TABLES = {"dim_player", "bridge_player_identity"}
_STATCAST_PLUS_RETRO_EVENT = {"dim_team", "dim_game", "bridge_game_identity"}
_RETRO_EVENT_ONLY_SINGLE = {"dim_park"}

_CONTRACT_FN = {
    "dim_player": CT.dim_player_contract, "bridge_player_identity": CT.bridge_player_identity_contract,
    "dim_team": CT.dim_team_contract, "dim_game": CT.dim_game_contract,
    "bridge_game_identity": CT.bridge_game_identity_contract, "dim_park": CT.dim_park_contract,
    "fact_retrosheet_event": CT.fact_retrosheet_event_contract,
    "fact_lineup_participation": CT.fact_lineup_participation_contract,
    "fact_umpire_game": CT.fact_umpire_game_contract, "fact_team_game": CT.fact_team_game_contract,
    "fact_player_game": CT.fact_player_game_contract, "fact_statcast_pitch": CT.fact_statcast_pitch_contract,
    "fact_statcast_plate_appearance": CT.fact_statcast_plate_appearance_contract,
}


def _bronze_sources(m) -> dict[str, Any]:
    def d(p, with_status=False):
        base = {"partitionId": p.partition_id, "source": p.source, "relativePath": p.relative_path,
                "fileSha256": p.file_sha256}
        if with_status:
            base["status"] = p.status
            base["rowCount"] = int(p.row_count or 0)
        return base

    chad = [d(p) for p in sorted(BA.partitions(m, source="chadwick"), key=lambda x: x.partition_id)]
    retro = {p.relative_path: p for p in BA.partitions(m, source="retrosheet")}
    retro_events = [d(retro[f"retrosheet/events/{y}eve.zip"]) for y in YEARS]
    retro_gls = [d(retro[f"retrosheet/game-logs/gl{y}.zip"]) for y in YEARS]
    statcast = [d(p, with_status=True) for p in sorted(BA.partitions(m, source="statcast"), key=lambda x: x.partition_id)]
    nonempty = [s for s in statcast if s["status"] == "COMPLETE" and s["rowCount"] > 0]
    empty = [s for s in statcast if not (s["status"] == "COMPLETE" and s["rowCount"] > 0)]
    accounting = {"statcastTotalPartitions": len(statcast), "rowContributingPartitions": len(nonempty),
                  "completeEmptyPartitions": len(empty), "reconciles": len(nonempty) + len(empty) == len(statcast)}
    retro_event_ids = {y: retro[f"retrosheet/events/{y}eve.zip"].partition_id for y in YEARS}
    retro_gl_ids = {y: retro[f"retrosheet/game-logs/gl{y}.zip"].partition_id for y in YEARS}
    return {"chadwick": chad, "retro_events": retro_events, "retro_gls": retro_gls, "statcast": statcast,
            "statcastAccounting": accounting, "retroEventIds": retro_event_ids, "retroGlIds": retro_gl_ids}


def _si(sources, accounting=None) -> dict[str, Any]:
    d = {"bronzeManifestSha256": BA.EXPECTED_BRONZE_MANIFEST_SHA256, "sourceCount": len(sources), "sources": sources}
    if accounting:
        d["accounting"] = accounting
    return d


def _source_inputs_for(name: str, S: dict[str, Any]) -> dict[str, Any]:
    if name in _CHADWICK_TABLES:
        return _si(S["chadwick"])
    if name in _STATCAST_TABLES:
        return _si(S["statcast"], S["statcastAccounting"])
    if name in _STATCAST_PLUS_RETRO_EVENT:
        return _si(S["statcast"] + S["retro_events"], S["statcastAccounting"])
    if name in _RETRO_EVENT_TABLES or name in _RETRO_EVENT_ONLY_SINGLE:
        return _si(S["retro_events"])
    if name in _RETRO_GAMELOG_TABLES:
        return _si(S["retro_gls"])
    raise ValueError(f"no governed source mapping for {name}")


def _current_objects(silver_root: Path) -> dict[str, dict[str, Any]]:
    """{tableName: {'manifestSha','partitioned','hasSourceInputs'}} for ORIGINAL objects (those lacking
    governedSourceInputs). Regenerated outputs (which carry governedSourceInputs) are skipped as sources."""
    reg = json.loads((silver_root / "silver-table-registry.json").read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for dsid in reg["datasets"]:
        sha = dsid.rsplit(":sha256:", 1)[-1]
        name = dsid.split(":")[1]
        part_mf = silver_root / "partitioned" / sha / "manifest.json"
        if part_mf.is_file():
            body = json.loads(part_mf.read_bytes().decode("utf-8"))
            has = "governedSourceInputs" in body
            rec = {"manifestSha": sha, "partitioned": True, "hasSourceInputs": has}
        else:
            rc = json.loads((silver_root / "objects" / "sha256" / sha / "transformation-receipt.json").read_bytes().decode("utf-8"))
            has = "governedSourceInputs" in rc
            rec = {"manifestSha": sha, "partitioned": False, "hasSourceInputs": has}
        if not rec["hasSourceInputs"]:
            out.setdefault(name, rec)              # first original per table
    return out


def _reconciliation(silver_root: Path, m, dim_game_sha: str) -> dict[str, Any]:
    dg = pq.read_table(silver_root / "objects" / "sha256" / dim_game_sha / "object.parquet").to_pylist()
    sc_games = [{"mlbamGamePk": r["mlbamGamePk"], "gameDate": r["gameDate"], "homeTeam": r["homeTeam"],
                 "awayTeam": r["awayTeam"], "season": r["season"], "gameType": r["gameType"],
                 "reconciliationStatus": r["reconciliationStatus"]} for r in dg]
    retro = []
    for y in YEARS:
        retro.extend(RP.parse_events(m, BA.DEFAULT_BRONZE_ROOT, y).games)
    team_map = TA.derive_team_map(sc_games, retro)["map"]
    statcast_only = [g for g in sc_games if g["reconciliationStatus"] == GI.STATCAST_ONLY]
    cls = GI.classify_statcast_only(statcast_only, retro, team_map)
    import collections
    by_status = dict(collections.Counter(r["reconciliationStatus"] for r in sc_games))
    return {"schemaVersion": "PHASE_7B1_GAME_RECONCILIATION_V2", "dimGameStatusCounts": by_status,
            "statcastOnlyTotal": len(statcast_only), "statcastOnlyPostseason": cls["postseasonCount"],
            "statcastOnlyRegularSeason": cls["regularSeasonCount"], "statcastOnlyReasonTally": cls["tally"],
            "regularSeasonStatcastOnly": [g for g in cls["perGame"] if g["gameType"] == "R"]}


def regenerate(silver_root: Path) -> dict[str, Any]:
    silver_root = Path(silver_root)
    m = BA.verify_bronze_manifest()
    before = BA.inventory(m, BA.DEFAULT_BRONZE_ROOT)
    S = _bronze_sources(m)
    sources = _current_objects(silver_root)
    if set(sources) != set(_CONTRACT_FN):
        raise RuntimeError(f"expected 13 original objects, got {sorted(sources)}")

    regenerated: list[dict[str, Any]] = []
    for name in sorted(_CONTRACT_FN):
        rec = sources[name]
        contract = _CONTRACT_FN[name](list(YEARS))
        si = _source_inputs_for(name, S)
        if rec["partitioned"]:
            def child_fn(pkey, old, _name=name):
                if _name in _RETRO_EVENT_TABLES:
                    return S["retroEventIds"][int(pkey)]
                if _name in _RETRO_GAMELOG_TABLES:
                    return S["retroGlIds"][int(pkey)]
                return old                          # statcast children already carry exact partition ids
            out = SP.regenerate_partitioned_silver_table(silver_root=silver_root, old_manifest_sha=rec["manifestSha"],
                contract=contract, code_modules=_CODE, source_inputs=si, child_source_id_fn=child_fn)
            old_vd = None
        else:
            existing = SP.read_silver_table(silver_root, rec["manifestSha"])
            out = SP.publish_silver_table(silver_root=silver_root, contract=existing["contract"], rows=existing["rows"],
                bronze_manifest=m, source_partition_ids=[], code_modules=_CODE, field_order=existing["fieldOrder"],
                source_inputs=si)
            old_vd = existing["valueDigestSha256"]
            if out["valueDigestSha256"] != old_vd:
                raise RuntimeError(f"{name}: value digest changed during lineage regeneration (row values altered!)")
        regenerated.append({"table": name, "sourceManifestSha256": rec["manifestSha"],
                            "newManifestSha256": out["manifestSha256"], "newDatasetVersionId": out["datasetVersionId"],
                            "rowCount": out["rowCount"], "childCount": out.get("childCount"),
                            "valueDigestPreserved": (old_vd is None) or (out["valueDigestSha256"] == old_vd),
                            "governedSourceCount": si["sourceCount"], "quarantine": out["quarantine"],
                            "modelEligible": out["modelEligible"]})

    recon = _reconciliation(silver_root, m, sources["dim_game"]["manifestSha"])
    after = BA.inventory(m, BA.DEFAULT_BRONZE_ROOT)
    return {"schemaVersion": "PHASE_7B1_LINEAGE_REGEN_V1",
            "bronzeImmutability": {"beforeDigest": before["inventoryDigest"], "afterDigest": after["inventoryDigest"],
                                   "identical": before["inventoryDigest"] == after["inventoryDigest"]},
            "statcastSourceAccounting": S["statcastAccounting"], "gameReconciliation": recon,
            "regeneratedObjects": regenerated}
