"""Private, read-only reconstruction of already admitted forecast source clocks.

No database, provider, outcome, model, protected-history or production access.
Only an explicitly supplied new private output directory receives output.
Existing diagnostic files are never overwritten. Original artifacts are hashed
before and after, and exact pregame evidence hashes are checked before decoding.
"""
import argparse
import csv
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\james\asp-model-studio")
AISP = Path(r"C:\Users\james\ai-sports-predictor")
PRIOR = ROOT / "outputs/mlb-v18-wager-evidence-20260918-v1"
OUTPUT: Path


def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def clock(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def write_csv(name, rows):
    with (OUTPUT / name).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(name, value):
    with (OUTPUT / name).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def main():
    global OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True,
                        help="New private directory below the original Model Studio outputs root; existing diagnostic files are refused.")
    args = parser.parse_args()
    if not args.output_root.is_absolute():
        parser.error("--output-root must be an explicit absolute private path")
    OUTPUT = args.output_root.resolve()
    private_root = (ROOT / "outputs").resolve()
    if OUTPUT == private_root or not OUTPUT.is_relative_to(private_root):
        parser.error("--output-root must be a directory below the original Model Studio outputs root")
    targets = ("timestamp_records.csv", "timestamp_affected_records.csv",
               "TIMESTAMP_FINDINGS.json", "TIMESTAMP_SOURCE_INDEX.json")
    if any((OUTPUT / name).exists() for name in targets):
        parser.error("Refusing to overwrite existing timestamp diagnostic artifacts; supply a new private output directory")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    inputs = {name: reference(PRIOR / name) for name in ("model_evidence.csv", "JOIN_RECEIPT.json", "SOURCE_INDEX.json")}
    with (PRIOR / "model_evidence.csv").open(encoding="utf-8-sig", newline="") as stream:
        selected = [row for row in csv.DictReader(stream) if row["population"] == "SELECTED_V18_POSITION"]
    assert len(selected) == 31
    assert all(clock(row["scheduled_start"]).date().isoformat() >= "2026-08-28" for row in selected)
    rows, sources = [], []
    for row in selected:
        bound = json.loads(row["artifact_refs_json"])["pregame-evidence.json"]
        evidence_path = Path(bound["path"]).resolve()
        allowed_root = ROOT / "outputs/mlb-v18-current-state-pipeline-v1/objects/sha256"
        assert evidence_path.is_relative_to(allowed_root) and evidence_path.name == "pregame-evidence.json"
        assert reference(evidence_path) == bound
        evidence = load(evidence_path)
        sources.append(bound)
        expected = {(side["side"], kind): side[kind] for side in evidence["sides"] for kind in ("starter", "lineupAuthority")}
        for item in json.loads(row["source_clocks_json"]):
            original = expected[item["side"], item["kind"]]
            assert all(item.get(key) == original.get(key) for key in ("observedAt", "availableAsOf", "ingestedAt", "observationId", "payloadChecksum", "source"))
            observed, available, ingested = (clock(item[key]) for key in ("observedAt", "availableAsOf", "ingestedAt"))
            captured, created, handoff, decision, start = (clock(row[key]) for key in ("input_captured_at", "forecast_created_at", "earliest_retained_handoff_utc", "decision_utc", "scheduled_start"))
            assert max(observed, available, ingested) <= captured <= created <= handoff <= decision < start
            rows.append({
                "diagnostic_class": "RECONSTRUCTED_NOW_FROM_RETAINED_PREGAME_CLOCKS",
                "position_id": row["position_id"], "game_id": row["game_id"], "source_game_id": row["source_game_id"],
                "forecast_identity": row["forecast_identity"], "forecast_object_sha256": row["object_sha256"],
                "side": item["side"], "evidence_kind": item["kind"], "observation_id": item["observationId"],
                "payload_checksum": item["payloadChecksum"], "source": item["source"],
                "observed_at_original": item["observedAt"], "available_as_of_original": item["availableAsOf"], "ingested_at_original": item["ingestedAt"],
                "observed_at_utc": observed.isoformat(), "available_as_of_utc": available.isoformat(), "ingested_at_utc": ingested.isoformat(),
                "ingested_before_observed": ingested < observed, "observed_minus_ingested_seconds": (observed - ingested).total_seconds(),
                "observed_equals_available": observed == available,
                "input_declared_capture_utc": captured.isoformat(), "forecast_created_utc": created.isoformat(),
                "earliest_retained_handoff_utc": handoff.isoformat(), "decision_utc": decision.isoformat(), "scheduled_start_utc": start.isoformat(),
                "latest_source_clock_to_declared_capture_seconds": (captured - max(observed, available, ingested)).total_seconds(),
                "latest_source_clock_to_decision_seconds": (decision - max(observed, available, ingested)).total_seconds(),
                "all_source_clocks_before_declared_capture": True,
                "original_pregame_evidence_path": bound["path"], "original_pregame_evidence_sha256": bound["sha256"], "original_pregame_evidence_bytes": bound["bytes"],
                "individual_insert_commit_receipt_retained": False, "historical_runtime_deployment_attested": False,
                "outcomes_used_for_this_diagnostic": False,
            })
    affected = [row for row in rows if row["ingested_before_observed"]]
    assert len(rows) == 124 and len(affected) == 94 and len({row["observation_id"] for row in rows}) == 124
    write_csv("timestamp_records.csv", rows)
    write_csv("timestamp_affected_records.csv", affected)
    by_kind = {}
    for kind in ("starter", "lineupAuthority"):
        subset = [row for row in rows if row["evidence_kind"] == kind]
        signed = [row["observed_minus_ingested_seconds"] for row in subset]
        positive = [value for value in signed if value > 0]
        by_kind[kind] = {"records": len(subset), "earlier_ingested": len(positive), "not_earlier": len(signed) - len(positive),
                         "signed_observed_minus_ingested_seconds": {"min": min(signed), "median": statistics.median(signed), "max": max(signed)},
                         "earlier_ingested_lead_seconds": {"min": min(positive), "median": statistics.median(positive), "max": max(positive)}}
    code_specs = [
        (ROOT / "scripts/inventory_mlb_current_slate.py", [46, 55, 56, 122, 133, 161, 168, 252, 278, 300]),
        (ROOT / "server/sports_current_statcast/mlb_v18_current_publication.py", [163, 165, 167]),
        (ROOT / "server/sports_current_statcast/mlb_v18_current_features.py", [96, 97]),
        (AISP / "server/app/models/entities.py", [165, 166, 309, 312, 313, 314]),
        (AISP / "server/alembic/versions/20260812_0003_gate2_point_in_time.py", [25]),
        (AISP / "server/app/data_sources/mlb.py", [618, 622, 770, 771, 772, 805, 812]),
        (AISP / "server/app/ingestion/normalizer.py", [478, 479, 507, 535, 536]),
        (AISP / "server/app/jobs/orchestrator.py", [342, 347, 358, 368, 371, 372, 395, 399, 417, 419]),
        (AISP / "server/app/core/config.py", [395, 396]),
    ]
    code = []
    for path, line_numbers in code_specs:
        content = path.read_text(encoding="utf-8-sig").splitlines()
        code.append({**reference(path), "citations": [{"line": number, "text": content[number - 1]} for number in line_numbers]})
    web = {"title": "PostgreSQL 18 documentation, section 9.9.5 Current Date/Time", "url": "https://www.postgresql.org/docs/18/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT",
           "claim": "now() and CURRENT_TIMESTAMP denote transaction start; clock_timestamp() denotes current wall time.", "accessed_date": "2026-09-18"}
    findings = {
        "schema": "MLB_V18_TIMESTAMP_ORDER_DIAGNOSTIC_V1", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "31 reconciled selected current-source V18 forecasts; starter and lineup source clocks only. No outcome-based analysis.",
        "diagnostic_type": "RECONSTRUCTED_NOW_FROM_RETAINED_CLOCKS_AND_READ_ONLY_CURRENT_SOURCE_REVIEW",
        "counts": {"selected_forecasts": 31, "clock_records": 124, "unique_observation_ids": 124, "ingested_before_observed": 94,
                   "affected_forecasts": len({row["forecast_identity"] for row in affected}), "observed_equals_available": 124,
                   "all_source_clocks_before_declared_capture": 124, "all_source_clocks_before_decision": 124},
        "by_kind": by_kind,
        "minimum_latest_source_clock_to_declared_capture_seconds": min(row["latest_source_clock_to_declared_capture_seconds"] for row in rows),
        "minimum_latest_source_clock_to_decision_seconds": min(row["latest_source_clock_to_decision_seconds"] for row in rows),
        "conclusion": "Apparent reversals are explained by exporting transaction-start created_at as ingestedAt. This is a metadata-semantic ambiguity, not evidence that later information entered forecasts. No model-input corruption defect is established.",
        "field_semantics": {
            "observedAt": "For reviewed MLB source paths: local post-response fetch time, not a separately retained provider publication/event clock.",
            "availableAsOf": "Copied from the same local fetch time; not an independently retained database commit timestamp.",
            "ingestedAt": "Exporter aliases observation.created_at; ORM/schema default is PostgreSQL now()/CURRENT_TIMESTAMP (transaction start), not insertion or commit wall time.",
            "capturedAt": "Declared as-of assigned before opening the export transaction; query/export completion is not separately retained in this field.",
        },
        "proven": [
            "All 124 literal source-clock triplets match hash-verified exact forecast-bound pregame evidence.",
            "All source clocks precede declared capture and decision; original forecast/handoff also precedes the reconciled decision.",
            "The retained snapshot contains the observations and proves they were available when the export read executed.",
            "Reviewed exporter directly aliases created_at to ingestedAt; reviewed AISP default uses transaction start while adapter observed/available use fetch completion.",
            "Reviewed poll performs database reads before source fetch and commits afterward, which permits this reversal without any backdating.",
        ],
        "unresolved": [
            "Exact per-observation insertion/commit and first cross-process visibility times, and transaction IDs, are not retained in these fields.",
            "Current clean source hashes explain semantics but are not historical runtime-deployment attestations for every forecast.",
            "Declared capturedAt precedes export transaction setup, so readable snapshot content does not independently prove commit at or before that precise declared instant.",
            "No independent provider publication timestamp is retained in the examined fields.",
        ],
        "prospective_guidance": [
            "Preserve all original clocks and the existing Stage A cutoff/order meaning. Do not backdate, relabel, or impose a new historical ingestedAt >= observedAt gate.",
            "The reviewed V18 participant gate requires observedAt <= availableAsOf <= cutoff, plus a separate ingestedAt <= cutoff; it does not require ingestedAt >= observedAt. Preserve that distinction.",
            "Append a genuine local receipt/verification-completed timestamp after reading and hashing all required snapshot bytes; append durable receipt time after persistence when supported. Neither may be copied from created_at.",
            "Use this separate local receipt for prospective availability together with existing original cutoff gates; it cannot replace the original input clock or relax a cutoff.",
            "Withhold if receipt completion crosses the applicable cutoff; retain the attempt and reason.",
        ],
        "source_identity": {"aisp_current_head": "3e8d530c05e8ec7a5dae6d7adc3ff476e91068a8", "model_studio_runtime_head": "0c786297534c1ffc9892fbcd199d7d7af5ec8bae",
                            "reviewed_paths_tracked_status": "CLEAN_AT_READ", "historical_deployment_attestation": False},
        "external_semantics_reference": web, "prior_input_bindings": inputs,
        "quarantine_identity_gate": load(PRIOR / "JOIN_RECEIPT.json")["identityGate"],
        "execution_scope": {"production_writes": 0, "database_connections": 0, "sports_provider_requests": 0, "model_runs": 0,
                            "outcome_analysis": 0, "protected_payloads_opened": 0, "historical_source_links_followed": 0, "prior_diagnosis_modified": False},
        "tables": {name: reference(OUTPUT / name) for name in ("timestamp_records.csv", "timestamp_affected_records.csv")},
        "reconstruction_script": reference(__file__),
    }
    write_json("TIMESTAMP_FINDINGS.json", findings)
    write_json("TIMESTAMP_SOURCE_INDEX.json", {"schema": "MLB_V18_TIMESTAMP_SOURCE_BINDINGS_V1", "prior_artifacts": inputs,
                "exact_pregame_evidence": sources, "current_code": code, "web_semantics_reference": web, "code_is_historical_deployment_attestation": False})
    assert all(reference(PRIOR / name) == bound for name, bound in inputs.items())
    print(json.dumps({"counts": findings["counts"], "by_kind": by_kind, "output": str(OUTPUT)}, indent=2))


if __name__ == "__main__":
    main()
