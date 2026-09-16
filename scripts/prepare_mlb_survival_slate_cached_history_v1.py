"""Prepare retained 2023–25 source history for the first declared September 13 pair.

No provider, database, 2026 source payload, model-fit or publication interface.
The pilot registry is unchanged. Native Hughes debut proof remains pending.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_current_statcast import mlb_starter_duration_history as history

OUT = ROOT / "outputs/mlb-v18-survival-starter-coverage-v1"
DECLARATION_SHA = "fe1fb2ee0363788d08332ad17497e8627ad39b39f82d8e7fedc05be7a8ab54d3"
OLD_HISTORY_SHA = "cbf81ae8979be49bdd84ae90bb1fa9e2e8adde07510ffeb2e3c67a72409b2550"
PARSER_SHA = "ef3f8d0daaaa62cea101ef45a2e6fea7803ff0cc65b0fca45a3854b1b2369113"
DIM = Path("C:/Users/james/asp-data-staging/mlb-silver-v1/objects/sha256/ab06c88e7d4fa6e78b397c8a4dfbbc2c8a21a51c03f50fd78ee49de232fb0aaf")
EXPECTED = {"687312": ("player-1627711a952b43bcb8181d60", None),
            "695549": ("player-99d5d06daee947ef9eb488a4", "jobej001")}


def ref(path):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def verified(path, sha, size=None):
    r = ref(path)
    if r["sha256"] != sha or (size is not None and r["bytes"] != size):
        raise ValueError("CACHED_HISTORY_SOURCE_IDENTITY_CHANGED: " + str(path))
    return r


def save(root, name, data):
    raw = data if isinstance(data, bytes) else history.canonical_json_bytes(data)
    digest = hashlib.sha256(raw).hexdigest()
    path = root / "objects/sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("IMMUTABLE_CACHED_HISTORY_COLLISION")
    if not path.exists():
        path.write_bytes(raw)
    return ref(path)


def focused_checks(old_path):
    """Check only the changed mapping boundary and unchanged default body."""
    old = next(n for n in ast.parse(old_path.read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == "reconcile_retained_2025")
    new = next(n for n in ast.parse(Path(history.__file__).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == old.name)
    class Rename(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.copy_location(ast.Name(id="identity_map", ctx=node.ctx), node) if node.id == "CURRENT_IDENTITIES" else node
    old_tail = old.body[4:]
    start = next(i for i, n in enumerate(new.body) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) and n.value.func.id == "_retained_archive")
    assert [ast.dump(Rename().visit(n)) for n in old_tail] == [ast.dump(n) for n in new.body[start:]]
    assert history.CURRENT_IDENTITIES == {"664285": "retrosheet:player:valdf001", "690279": "mlbam:player:690279"}
    reached = RuntimeError("STOP_BEFORE_ANY_SOURCE_PAYLOAD")
    with patch.object(history, "_retained_archive", side_effect=reached):
        for kwargs in ({}, {"pitcher_ids": ("695549",), "player_identity_map": {"695549": "retrosheet:player:jobej001"}}):
            try:
                history.reconcile_retained_2025(**kwargs)
            except RuntimeError as e:
                assert e is reached
            else:
                raise AssertionError("VALID_MAPPING_DID_NOT_REACH_SOURCE_BOUNDARY")
        for value in ({"695549": "mlbam:player:687312"}, {"695549": "retrosheet:player:jobej001", "687312": "mlbam:player:687312"}):
            try:
                history.reconcile_retained_2025(pitcher_ids=("695549",), player_identity_map=value)
            except ValueError:
                pass
            else:
                raise AssertionError("INVALID_OR_OUT_OF_SCOPE_IDENTITY_ACCEPTED")
    return {"status": "PASS", "defaultPilotScopePreserved": True,
            "defaultReconciliationBodyUnchangedExceptLocalMapReference": True,
            "explicitExactMapAccepted": True, "wrongNativeIdentityAndExtraScopeRejectedBeforePayload": True,
            "sourcePayloadReads": 0, "providerCalls": 0}


def main(args):
    out = args.output_root.resolve()
    if not out.is_relative_to(OUT.resolve()):
        raise ValueError("NEW_DECLARED_RESULT_NAMESPACE_REQUIRED")
    declaration_ref = verified(args.declaration, DECLARATION_SHA)
    declaration = json.loads(args.declaration.read_bytes())
    first = min(declaration["games"], key=lambda g: (g["deadlineUtc"], g["gameId"]))
    if (first["sourceGameId"] != "824225" or first["scheduledStartUtc"][:10] != "2026-09-13"
            or {s["starterMlbamId"] for s in first["sides"]} != set(EXPECTED)):
        raise ValueError("FIRST_DECLARED_TWO_STARTER_SCOPE_CHANGED")
    source_identity = declaration["identityEvidence"]
    verified(source_identity["path"], source_identity["sha256"], source_identity["bytes"])
    identity_evidence = json.loads(Path(source_identity["path"]).read_bytes())
    source_game = next(g for g in identity_evidence["games"] if g["sourceGameId"] == "824225")
    if (source_game["canonicalGameId"] != first["gameId"]
            or any(s["starter"]["mlbamId"] != next(x["starterMlbamId"] for x in first["sides"] if x["side"] == s["side"])
                   for s in source_game["sides"])):
        raise ValueError("DECLARATION_STARTER_SOURCE_BINDING_CHANGED")

    old_path = OUT / "cached-history/source-code/sha256" / OLD_HISTORY_SHA / "mlb_starter_duration_history.py"
    old_ref = verified(old_path, OLD_HISTORY_SHA)
    checks = focused_checks(old_path)
    checks_ref = save(out, "focused-checks.json", checks)
    parser = ROOT / "server/sports_current_statcast/mlb_starter_survival_data.py"
    verified(parser, PARSER_SHA)
    prior_reconciliation = history.RESEARCH / "starter-history/reconciliations/sha256/380268e820ed5030483f53139e872143b286af27dc0a2d7099521e9a9198174d/reconciliation.json"
    prior_ref = verified(prior_reconciliation, "380268e820ed5030483f53139e872143b286af27dc0a2d7099521e9a9198174d")
    prior = json.loads(prior_reconciliation.read_bytes())
    if next(s for s in prior["sources"] if Path(s["path"]).name == parser.name)["sha256"] != PARSER_SHA:
        raise ValueError("ACCEPTED_2025_PARSER_BINDING_CHANGED")
    code_refs = [save(out, p.name, p.read_bytes()) for p in (Path(__file__), Path(history.__file__), parser)]

    manifest_path = DIM / "publication-manifest.json"
    dim_manifest = json.loads(manifest_path.read_bytes())
    if dim_manifest["manifestSha256"] != DIM.name or dim_manifest["tableName"] != "dim_player":
        raise ValueError("DIM_PLAYER_MANIFEST_IDENTITY_CHANGED")
    child = dim_manifest["children"]["object.parquet"]
    dim_ref = verified(DIM / "object.parquet", child["sha256"], child["bytes"])
    cols = ["canonicalPlayerId", "mlbamId", "retrosheetId", "chadwickKeyUuid", "mlbPlayedFirst", "resolutionStatus", "sourceProvenance"]
    identities = [r for r in pq.ParquetFile(dim_ref["path"]).read(columns=cols).to_pylist() if r["mlbamId"] in EXPECTED]
    if len(identities) != 2 or {r["mlbamId"] for r in identities} != set(EXPECTED):
        raise ValueError("MISSING_OR_DUPLICATED_STARTER_DIM_IDENTITY")
    for row in identities:
        if (row["resolutionStatus"] != "MATCHED_EXACT" or
                (row["canonicalPlayerId"], row["retrosheetId"]) != EXPECTED[row["mlbamId"]]):
            raise ValueError("DECLARED_STARTER_MAPPING_NOT_EXACT")

    cert_manifest = json.loads(history._read(history.CERTIFIED / "manifest.json", history.CERTIFIED_SHA))
    source_declaration = cert_manifest["declaration"]
    verified(source_declaration["path"], source_declaration["sha256"], source_declaration["bytes"])
    source_scope = json.loads(Path(source_declaration["path"]).read_bytes())["duration"]
    if source_scope["training"] != ["2023-01-01", "2023-12-31"] or source_scope["heldOutEvaluation"] != ["2024-07-01", "2024-10-31"]:
        raise ValueError("CERTIFIED_HISTORICAL_SCOPE_CHANGED")
    artifact = cert_manifest["artifacts"]["starts.parquet"]
    cert_ref = verified(history.CERTIFIED / "starts.parquet", artifact["sha256"], artifact["bytes"])
    identity_rows = pq.ParquetFile(cert_ref["path"]).read(columns=["startId", "gameId", "pitcherId", "gameDate", "eligible", "exclusionReason"]).to_pylist()
    if any(not "2023-01-01" <= r["gameDate"] <= "2024-12-31" for r in identity_rows):
        raise ValueError("CERTIFIED_LEDGER_OUTSIDE_AUTHORIZED_YEARS")
    jobe_ids = [r for r in identity_rows if r["pitcherId"] == "retrosheet:player:jobej001"]
    if jobe_ids:
        raise ValueError("FIRST_MATCHUP_BASE_STARTER_COUNT_CHANGED")

    rights_path = history.FD1 / "source-rights.json"
    verified(rights_path, "8215be7ed1a472dfaad6f93c3253be8ce3e8393e685d7395171bed20800311f7")
    rights = json.loads(rights_path.read_bytes())
    if "LOCAL_PRIVATE_MODEL_DEVELOPMENT" not in next(r for r in rights["records"] if r["record_key"] == "RETROSHEET")["allowed_purposes"]:
        raise ValueError("RETAINED_RETROSHEET_SOURCE_USE_NOT_SUPPORTED")
    # Pure helper returns data; never call save_reconciliation or activate pilot registry.
    result = history.reconcile_retained_2025(pitcher_ids=("695549",), player_identity_map={"695549": "retrosheet:player:jobej001"})
    if any(not "2025-01-01" <= s["gameDate"] <= "2025-12-31" for s in result["starts"]):
        raise ValueError("DERIVED_HISTORY_OUTSIDE_AUTHORIZED_2025")
    expected_games = {"SEA202503310", "DET202504060", "MIN202504120", "DET202504180", "HOU202504300",
                      "COL202505070", "DET202505120", "TOR202505180", "DET202505230", "DET202505280"}
    if {s["gameId"].removeprefix("retrosheet:game:") for s in result["starts"]} != expected_games:
        raise ValueError("PREDECLARED_2025_STARTER_IDENTITY_COHORT_CHANGED")
    result["sources"] = [next((r for r in code_refs if Path(r["path"]).name == Path(s["path"]).name), s) for s in result["sources"]]
    reconciliation_ref = save(out, "reconciliation-2025.json", result)
    created = datetime.now(timezone.utc).isoformat()
    counts = result["enumeration"]["countsByMlbam"]["695549"]
    report = {"schemaVersion": "MLB_SURVIVAL_FIRST_SLATE_CACHED_HISTORY_V1", "createdAtUtc": created,
        "purpose": "FROZEN_HISTORICAL_SOURCE_DERIVATION_NOT_FORECAST_EVALUATION", "declaration": declaration_ref,
        "game": first, "identityEvidence": source_identity, "identityRows": identities,
        "playerIdentityMap": {"687312": "mlbam:player:687312", "695549": "retrosheet:player:jobej001"},
        "dimPlayer": {"manifest": ref(manifest_path), "identityTable": dim_ref, "use": "IDENTITY_ONLY_NOT_MODEL_FEATURES"},
        "certified2023And2024": {"manifest": ref(history.CERTIFIED / "manifest.json"), "starts": cert_ref,
            "identityRows": len(identity_rows), "jobeStarterRows": 0, "hughesZeroCertified": False},
        "reconciliation2025": reconciliation_ref, "jobe2025Counts": counts,
        "jobe2025Coverage": {"candidateStarts": result["enumeration"]["candidateStarts"], "accountedFor": sum(counts.values()),
            "completeFrom": "2025-01-01", "completeThrough": "2025-12-31" if counts.get("UNRESOLVED", 0) == 0 else None,
            "definition": "ELIGIBLE_PLUS_FROZEN_JUSTIFIED_EXCLUSIONS", "sourceObservedAtUtc": max(s["observedAt"] for s in result["starts"]),
            "derivedHistoryAvailableAtUtc": created},
        "hughesDisposition": "PENDING_NATIVE_DEBUT_METADATA_NO_CERTIFIED_ZERO_HISTORY",
        "current2026Coverage": "NOT_PARSED_OR_CERTIFIED_BY_THIS_COMMAND",
        "missingPrerequisites": ["Native Hughes debut/no-prior-history evidence", "Complete authorized 2026 appearance accounting for both starters",
            "September12 day-close enumeration before a new original forecast cutoff", "Confirmed ordinary V18 pregame inputs"],
        "accepted2025Parser": {"sha256": PARSER_SHA, "priorAcceptedReconciliation": prior_ref},
        "sourceCode": code_refs, "preservedOriginalHistoryCode": old_ref, "focusedChecks": checks_ref,
        "activity": {"providerCalls": 0, "databaseReads": 0, "source2026PayloadReads": 0, "sealedPayloadReads": 0,
            "forecastOutcomeEvaluation": 0, "modelFits": 0, "simulationRuns": 0, "pilotRegistryWrites": 0, "exchangeWrites": 0},
        "candidateAuthority": False, "status": "CACHED_PREFIX_PREPARED_CURRENT_STARTER_HISTORY_STILL_INCOMPLETE"}
    report_ref = save(out, "cached-history-preparation.json", report)
    (out / "current.json").write_text(json.dumps(report_ref, indent=2) + "\n", encoding="utf-8")
    return {"result": report_ref, "jobe2025Counts": counts, "hughesDisposition": report["hughesDisposition"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--declaration", type=Path, default=OUT / "declaration.json")
    parser.add_argument("--output-root", type=Path, default=OUT / "cached-history")
    print(json.dumps(main(parser.parse_args()), indent=2))
