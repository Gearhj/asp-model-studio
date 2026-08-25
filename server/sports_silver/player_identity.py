"""Chadwick-authoritative canonical player identity reconciliation (Phase 7B1, Sections 7 & 24).

Chadwick is the principal cross-source identity authority. This builds ``dim_player`` (one row per canonical person)
and ``bridge_player_identity`` (one row per (source_system, source_id) -> canonical) with explicit resolution states.
Identity FAILS CLOSED: no fuzzy join, no name/initial/date collapse, no silent selection when multiple plausible
canonical persons claim the same source identifier. A source id claimed by more than one Chadwick person is
SOURCE_CONFLICT / AMBIGUOUS and is excluded from authoritative downstream joins.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from . import bronze_authority as BA
from .canonical_ids import canonical_player_id

# The Chadwick source identity columns we reconcile (source_system -> chadwick column).
SOURCE_ID_COLUMNS = {
    "mlbam": "key_mlbam",
    "retrosheet": "key_retro",
    "bbref": "key_bbref",
    "fangraphs": "key_fangraphs",
}

# resolution states
MATCHED_EXACT = "MATCHED_EXACT"
UNMATCHED = "UNMATCHED"
AMBIGUOUS = "AMBIGUOUS"
SOURCE_CONFLICT = "SOURCE_CONFLICT"


@dataclass
class PlayerReconciliation:
    dim_player: list[dict[str, Any]]
    bridge_player_identity: list[dict[str, Any]]
    stats: dict[str, Any]
    # source_id -> canonical player id, ONLY for unambiguous mappings usable for downstream canonical joins
    resolved: dict[str, dict[str, str]] = field(default_factory=dict)


def _clean(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _load_chadwick_persons(manifest: Mapping[str, Any], root) -> list[dict[str, str]]:
    """Read the 16 Chadwick shards read-only; return one dict per person with the governed identity columns."""
    persons: list[dict[str, str]] = []
    wanted = ["key_person", "key_uuid", "key_mlbam", "key_retro", "key_bbref", "key_fangraphs",
              "name_last", "name_first", "mlb_played_first", "mlb_played_last"]
    for _p, table in BA.iter_source_frames(manifest, root, "chadwick", only_nonempty=True):
        cols = {c: table.column(c).to_pylist() if c in table.column_names else [None] * table.num_rows for c in wanted}
        for i in range(table.num_rows):
            persons.append({c: _clean(cols[c][i]) for c in wanted})
    return persons


def reconcile_players(manifest: Mapping[str, Any], root=BA.DEFAULT_BRONZE_ROOT) -> PlayerReconciliation:
    """Read Chadwick from Bronze (read-only) and reconcile. See ``reconcile_from_persons`` for the pure core."""
    return reconcile_from_persons(_load_chadwick_persons(manifest, root))


def reconcile_from_persons(persons: list[dict[str, str]]) -> PlayerReconciliation:
    """Pure reconciler over Chadwick-shaped person dicts (testable without Bronze). Fail-closed on ambiguity."""
    persons = [{k: _clean(p.get(k)) for k in
                ("key_person", "key_uuid", "key_mlbam", "key_retro", "key_bbref", "key_fangraphs",
                 "name_last", "name_first", "mlb_played_first", "mlb_played_last")} for p in persons]
    # Detect Chadwick register integrity: key_person must be unique (the register's own primary key).
    key_person_counts: dict[str, int] = {}
    for p in persons:
        key_person_counts[p["key_person"]] = key_person_counts.get(p["key_person"], 0) + 1
    duplicate_key_person = {k for k, c in key_person_counts.items() if c > 1 and k}

    # For each source system, map source_id -> set of canonical persons (to detect one-source-id-to-many-persons).
    src_to_persons: dict[str, dict[str, set[str]]] = {s: {} for s in SOURCE_ID_COLUMNS}
    for p in persons:
        if not p["key_person"]:
            continue
        cid = canonical_player_id(p["key_person"])
        for system, col in SOURCE_ID_COLUMNS.items():
            sid = p[col]
            if sid:
                src_to_persons[system].setdefault(sid, set()).add(cid)

    # dim_player (one per canonical person; deduplicated on the canonical id derived from key_person)
    dim_player: list[dict[str, Any]] = []
    seen_cid: set[str] = set()
    for p in sorted(persons, key=lambda x: x["key_person"]):
        if not p["key_person"]:
            continue
        cid = canonical_player_id(p["key_person"])
        if cid in seen_cid:
            continue
        seen_cid.add(cid)
        conflicted = p["key_person"] in duplicate_key_person
        dim_player.append({
            "canonicalPlayerId": cid, "chadwickKeyPerson": p["key_person"], "chadwickKeyUuid": p["key_uuid"],
            "mlbamId": p["key_mlbam"] or None, "retrosheetId": p["key_retro"] or None,
            "bbrefId": p["key_bbref"] or None, "fangraphsId": p["key_fangraphs"] or None,
            "nameLast": p["name_last"] or None, "nameFirst": p["name_first"] or None,
            "mlbPlayedFirst": p["mlb_played_first"] or None, "mlbPlayedLast": p["mlb_played_last"] or None,
            "resolutionStatus": SOURCE_CONFLICT if conflicted else MATCHED_EXACT,
            "sourceProvenance": {"authority": "chadwick_register", "contract": BA.BRONZE_MANIFEST_CONTRACT},
        })

    # bridge_player_identity (one per (source_system, source_id)); ambiguous where >1 canonical claim the id
    bridge: list[dict[str, Any]] = []
    resolved: dict[str, dict[str, str]] = {s: {} for s in SOURCE_ID_COLUMNS}
    counts = {s: {"total": 0, "matched": 0, "ambiguous": 0} for s in SOURCE_ID_COLUMNS}
    for system, mapping in src_to_persons.items():
        for sid, cids in sorted(mapping.items()):
            counts[system]["total"] += 1
            if len(cids) == 1:
                cid = next(iter(cids))
                status = MATCHED_EXACT
                counts[system]["matched"] += 1
                resolved[system][sid] = cid                # ONLY unambiguous ids are usable downstream
            else:
                cid = None
                status = AMBIGUOUS
                counts[system]["ambiguous"] += 1
            bridge.append({"sourceSystem": system, "sourceId": sid,
                           "canonicalPlayerId": cid, "candidateCanonicalPlayerIds": sorted(cids),
                           "resolutionStatus": status, "resolutionMethod": "chadwick_exact_register"})

    stats = {
        "chadwickPersons": len(persons),
        "uniqueKeyPerson": len(key_person_counts),
        "duplicateKeyPerson": len(duplicate_key_person),
        "canonicalPlayers": len(dim_player),
        "playersWithMlbam": sum(1 for d in dim_player if d["mlbamId"]),
        "playersWithRetro": sum(1 for d in dim_player if d["retrosheetId"]),
        "playersWithBbref": sum(1 for d in dim_player if d["bbrefId"]),
        "playersWithFangraphs": sum(1 for d in dim_player if d["fangraphsId"]),
        "bySource": {s: {"uniqueSourceIds": counts[s]["total"], "matchedExact": counts[s]["matched"],
                         "ambiguous": counts[s]["ambiguous"]} for s in SOURCE_ID_COLUMNS},
    }
    return PlayerReconciliation(dim_player=dim_player, bridge_player_identity=bridge, stats=stats, resolved=resolved)
