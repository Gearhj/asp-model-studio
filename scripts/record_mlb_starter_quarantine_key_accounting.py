"""Count quarantined OOT identities without opening any sealed feature/target file.

Only the separately published UNMATERIALIZED Wave 1 key object, authenticated
static player identities, and three explicitly permitted prospective source
feeds are read. A partial source-to-key join is not an exact remaining count.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pyarrow.parquet as pq

from server.sports_current_statcast.mlb_starter_duration_quarantine import (
    ALLOWED, assert_prospective_source_allowed, load_exception_authority,
)
from server.sports_current_statcast.pipeline import _load_player_identity
from server.sports_current_statcast.mlb_starter_duration_history import NON_PA_EVENTS, TERMINAL_EVENTS
from server.sports_silver.canonical_ids import canonical_game_id, canonical_pa_id

GOLD_ROOT = Path("C:/Users/james/asp-data-staging/mlb-current-statcast-gold-v1")
MANIFEST_SHA = "98673b65dc5eab61e39b16d1313c27bbb2cf908c525f80db579cb07a5cfdab33"
KEY_SHA = "350ff402906ede4f39ae164c39719a84c3514529ffdc65deebcab8cf0cf139ba"
IDENTITY_SHA = "ab06c88e7d4fa6e78b397c8a4dfbbc2c8a21a51c03f50fd78ee49de232fb0aaf"
QUARANTINE = ROOT / "outputs/mlb-starter-duration-paired-research-v1/intake/prospective-only-source-quarantine/objects/sha256"
OUTPUT = ROOT / "outputs/mlb-starter-duration-paired-research-v1/quarantine-key-accounting/objects/sha256"


def _read_verified(path, sha):
    blob = Path(path).read_bytes()
    if hashlib.sha256(blob).hexdigest() != sha:
        raise ValueError("QUARANTINE_KEY_SOURCE_CHECKSUM_MISMATCH")
    return blob, {"path": str(Path(path).resolve()), "sha256": sha, "bytes": len(blob)}


def record(sources):
    authority = load_exception_authority()
    path = GOLD_ROOT / "sufficient-statistics/publications/sha256" / MANIFEST_SHA / "manifest.json"
    blob, manifest_ref = _read_verified(path, MANIFEST_SHA)
    manifest = json.loads(blob)
    if (manifest["finalOotKeyRowCount"] != 14067 or not manifest["finalOot"]["keyOnly"]
            or manifest["finalOot"]["payloadStatus"] != "UNMATERIALIZED"):
        raise ValueError("SEPARATE_KEY_AUTHORITY_INVALID")
    descriptors = [p for p in manifest["partitions"] if p["sha256"] == KEY_SHA]
    if len(descriptors) != 1 or descriptors[0]["partitionRole"] != "FINAL_OOT_SEALED":
        raise ValueError("SEPARATE_KEY_PARTITION_INVALID")
    key_path = GOLD_ROOT / descriptors[0]["relativePath"]
    _, key_ref = _read_verified(key_path, KEY_SHA)
    if key_ref["bytes"] != descriptors[0]["byteCount"]:
        raise ValueError("SEPARATE_KEY_BYTES_MISMATCH")
    parquet = pq.ParquetFile(key_path)
    allowed = set(manifest["finalOot"]["allowedNonNullRowFields"])
    # Check null-count footer metadata before projecting only the four key fields.
    for r in range(parquet.metadata.num_row_groups):
        group = parquet.metadata.row_group(r)
        for c, name in enumerate(parquet.schema.names):
            if name not in allowed:
                stats = group.column(c).statistics
                if stats is None or stats.null_count != group.num_rows:
                    raise ValueError("KEY_COMPANION_HAS_MATERIALIZED_PAYLOAD")
    keys = parquet.read(columns=sorted(allowed)).to_pydict()
    if (set(keys["datasetRole"]) != {"FINAL_OOT"}
            or set(keys["materialization_status"]) != {"UNMATERIALIZED"}
            or set(keys["materialization_reason"]) != {"FINAL_OOT_SEALED"}):
        raise ValueError("KEY_COMPANION_ROLE_INVALID")
    keyset = set(keys["canonicalPaId"])
    if len(keyset) != 14067 or len(keys["canonicalPaId"]) != 14067:
        raise ValueError("KEY_COMPANION_POPULATION_MISMATCH")
    players, identity = _load_player_identity(Path("C:/Users/james/asp-data-staging/mlb-silver-v1"))
    if identity["publicationManifestSha256"] != IDENTITY_SHA:
        raise ValueError("ORIGINAL_PLAYER_IDENTITY_AUTHORITY_CHANGED")
    games, matched_union = [], set()
    by_game = {pk: (pitcher, date) for pitcher, pk, date in ALLOWED}
    if len({pk for pk, _ in sources}) != len(sources):
        raise ValueError("DUPLICATE_SOURCE_GAME")
    for pk, raw_path in sorted(sources):
        pitcher, game_date = by_game[pk]
        assert_prospective_source_allowed(pitcher, pk, game_date)
        raw_path = Path(raw_path).resolve()
        if raw_path.parent != QUARANTINE.resolve() or not raw_path.name.endswith(".source.json"):
            raise ValueError("SOURCE_OUTSIDE_PROSPECTIVE_QUARANTINE")
        data_blob, source_ref = _read_verified(raw_path, raw_path.name.split(".")[0])
        data = json.loads(data_blob)
        if (int(data.get("gamePk", -1)) != pk
                or data.get("gameData", {}).get("datetime", {}).get("officialDate") != game_date):
            raise ValueError("AUTHORIZED_SOURCE_GAME_IDENTITY_MISMATCH")
        plays = data.get("liveData", {}).get("plays", {}).get("allPlays", [])
        indices = [p.get("about", {}).get("atBatIndex") for p in plays]
        contiguous = bool(plays) and indices == list(range(len(plays)))
        complete = bool(plays) and all(p.get("about", {}).get("isComplete") is True for p in plays)
        final = data.get("gameData", {}).get("status", {}).get("abstractGameState") == "Final"
        batter_ids = [str(p.get("matchup", {}).get("batter", {}).get("id", "")) for p in plays]
        missing_players = sorted({pid for pid in batter_ids if pid not in players})
        # The complete native allPlays sequence also has runner-only events.
        # Classify only whether an entry is a terminal PA, using the existing
        # reviewed taxonomy. Do not expose event outcomes or compare any model.
        kinds = [p.get("result", {}).get("eventType") for p in plays]
        terminal = [k in TERMINAL_EVENTS and k not in {"other_out", "runner_double_play"} for k in kinds]
        non_pa = [k in NON_PA_EVENTS and k not in {"other_out", "runner_double_play"} for k in kinds]
        semantics_complete = all(t != n for t, n in zip(terminal, non_pa))
        matches = {}
        matched = set()
        terminal_keys = set()
        for offset in (0, 1):
            candidates = [canonical_pa_id(canonical_game_id(pk), idx + offset, players[pid])
                          for idx, pid in zip(indices, batter_ids)
                          if isinstance(idx, int) and pid in players]
            present = set(candidates) & keyset
            matches[str(offset)] = {"candidateCount": len(candidates), "matchedCount": len(present)}
            if offset == 1:
                matched = present
                terminal_keys = {canonical_pa_id(canonical_game_id(pk), idx + offset, players[pid])
                                 for idx, pid, is_terminal in zip(indices, batter_ids, terminal)
                                 if isinstance(idx, int) and pid in players and is_terminal}
        # Every true source PA must match, and no runner-only key may match. Any
        # unexplained omission or ambiguous other-out semantics leaves the count
        # unproven rather than silently adopting a different cohort.
        exact = (contiguous and complete and final and semantics_complete and not missing_players
                 and matched == terminal_keys and len(terminal_keys) == sum(terminal) > 0)
        if matched_union & matched:
            raise ValueError("CROSS_GAME_CANONICAL_KEY_COLLISION")
        matched_union.update(matched)
        games.append({"mlbamGamePk": pk, "canonicalGameId": canonical_game_id(pk),
                      "sourceRef": source_ref, "sourcePlayIdentityCount": len(plays),
                      "sourceIndicesContiguous": contiguous, "sourcePlaysComplete": complete,
                      "sourceGameFinal": final, "sourceTerminalPaCount": sum(terminal),
                      "sourceReviewedNonPaCount": sum(non_pa),
                      "sourcePaSemanticsComplete": semantics_complete,
                      "missingPlayerIdentityCount": len(missing_players),
                      "offsetIdentityJoinChecks": matches,
                      "matchedOriginalOotKeys": sorted(matched),
                      "exactCompleteIdentityJoin": exact})
    exact = len(games) == 3 and all(g["exactCompleteIdentityJoin"] for g in games)
    result = {
        "schemaVersion": "MLB_FINAL_OOT_QUARANTINE_KEY_ACCOUNTING_V1",
        "status": "EXACT_COMPLETE_SOURCE_IDENTITY_JOIN" if exact else "EXACT_REMAINING_COUNT_UNPROVEN",
        "purpose": "PERMANENT_WHOLE_GAME_QUARANTINE_ACCOUNTING_ONLY",
        "authorityRef": authority["authorityRef"], "quarantineRef": authority["quarantineRef"],
        "keyManifestRef": manifest_ref, "keyObjectRef": key_ref, "playerIdentity": identity,
        "originalFinalOotObservationCount": 14067,
        "quarantinedMatchedKeyCount": len(matched_union),
        "remainingFinalOotObservationCount": 14067 - len(matched_union) if exact else None,
        "games": games, "missingAuthorizedGameIds": sorted(set(by_game) - {pk for pk, _ in sources}),
        "sealedGoldFilesReadOrHashed": 0, "sealedFeatureOrTargetColumnsRead": 0,
        "separateUnmaterializedCompanionKeyRowsRead": 14067,
        "modelFits": 0, "evaluations": 0, "networkCalls": 0,
        "limitations": [
            "The count is an identity intersection, never an evaluation or model result.",
            "Source atBatIndex offsets 0 and 1 are checked against original canonical hashes; no sealed target is projected or evaluated.",
            "Two runner-only entries in native allPlays are not plate appearances; the existing reviewed PA/non-PA taxonomy identifies them without reporting event outcomes.",
            "A missing or partial source identity join leaves the exact remaining observation count unproven.",
            "No original sealed Gold payload or any other protected game's source payload is opened.",
        ],
    }
    result["implementationRefs"] = []
    for code_path in (Path(__file__).resolve(), ROOT / "server/sports_silver/canonical_ids.py",
                      ROOT / "server/sports_current_statcast/mlb_starter_duration_history.py"):
        code = code_path.read_bytes()
        result["implementationRefs"].append({"path": str(code_path), "sha256": hashlib.sha256(code).hexdigest(),
                                              "bytes": len(code)})
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    sha = hashlib.sha256(encoded).hexdigest()
    target = OUTPUT / (sha + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != encoded:
            raise ValueError("IMMUTABLE_KEY_ACCOUNTING_CONFLICT")
    else:
        with target.open("xb") as stream:
            stream.write(encoded)
    return {"path": str(target), "sha256": sha, "bytes": len(encoded),
            "status": result["status"], "matchedKeys": len(matched_union),
            "remainingCount": result["remainingFinalOotObservationCount"],
            "games": [{k: v for k, v in g.items() if k not in {"sourceRef", "matchedOriginalOotKeys"}} for g in games]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True, help="AUTHORIZED_GAME_PK=QUARANTINED_SOURCE_PATH")
    args = parser.parse_args()
    print(json.dumps(record([(int(value.split("=", 1)[0]), value.split("=", 1)[1]) for value in args.source]), indent=2))
