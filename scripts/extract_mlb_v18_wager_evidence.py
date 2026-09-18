"""Read-only diagnosis using Claude's reconciled positions and exact V18 bundles.

No live database, provider, model execution, outcome source or production writer.
The full positions export is opened only after identity-only quarantine checks.
Nonselected rows are retained producer comparators, not asserted policy candidates.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from statistics import mean
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sports_current_statcast import mlb_starter_duration_quarantine as quarantine
from mlb_v18_wager_evidence_fields import extract_forecast_evidence


def stamp(value):
    return pd.to_datetime(value, utc=True).to_pydatetime()


def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def identity_gate(positions, runtime):
    columns = ["position_id", "game_id", "sport", "kickoff_utc", "era", "forecast_identity", "decision_timestamp_utc"]
    identity = pd.read_csv(positions, usecols=columns, dtype=str, keep_default_na=False)
    if identity.position_id.duplicated().any():
        raise ValueError("DUPLICATE_AUTHORITY_POSITION_ID")
    quarantine.LEDGER = runtime / "server/artifacts/governance/mlb-final-oot-quarantine-v1.json"
    quarantine.LEDGER_ARCHIVE = quarantine.LEDGER.parent / "mlb-final-oot-quarantine-history/sha256"
    mlb = identity[identity.sport.str.upper().eq("MLB")]
    parsed_dates = pd.to_datetime(mlb.kickoff_utc, utc=True, errors="raise")
    if parsed_dates.isna().any():
        raise ValueError("MISSING_MLB_DATE_OUTCOMES_NOT_LOADED")
    dates = parsed_dates.dt.strftime("%Y-%m-%d")
    if dates.between("2026-08-14", "2026-08-27").any():
        raise ValueError("PROTECTED_DATE_IN_AUTHORITY_EXPORT_OUTCOMES_NOT_LOADED")
    if not all(quarantine.final_oot_eligible_key_mask(mlb.game_id)):
        raise ValueError("PERMANENTLY_EXCLUDED_ID_IN_AUTHORITY_EXPORT")
    selected = identity[identity.era.str.contains("MLB V18", regex=False)]
    root = runtime / "outputs/mlb-v18-current-state-pipeline-v1"
    mlbam = []
    for row in selected.to_dict("records"):
        sha = row["forecast_identity"].removeprefix("mlb-v18-daily-")
        if len(sha) != 64 or any(x not in "0123456789abcdef" for x in sha):
            raise ValueError("UNRECOGNIZED_EXACT_FORECAST_IDENTITY")
        forecast = load_json(root / "objects/sha256" / sha / "forecast.json")
        if forecast["gameId"] != row["game_id"]:
            raise ValueError("AUTHORITY_GAME_FORECAST_ID_MISMATCH")
        if abs((stamp(forecast["scheduledStart"]) - stamp(row["kickoff_utc"])).total_seconds()) > 1:
            raise ValueError("AUTHORITY_SCHEDULE_MISMATCH")
        mlbam.append(str(forecast["sourceGameId"]))
    if not all(quarantine.final_oot_eligible_key_mask(mlbam)):
        raise ValueError("PERMANENTLY_EXCLUDED_MLBAM_ALIAS")
    return identity, selected, {"identityOnlyBeforeOutcomeLoad": True, "positionsChecked": len(identity), "mlbRowsChecked": len(mlb), "v18SourceGameAliasesChecked": len(mlbam), "protectedDateRows": 0, "permanentlyExcludedRows": 0, "quarantine": reference(quarantine.LEDGER), "scope": "SEPTEMBER_OPERATIONAL_DIAGNOSIS_NOT_FINAL_OOT"}


def retained_publications(root, dates):
    """Earliest retained handoff clock for each exact object, with original refs."""
    handoff_paths = set()
    for date in sorted(dates):
        for path in (root / "slates" / date / "sha256").glob("*/slate-result.json"):
            receipt = load_json(path)
            if receipt.get("handoffPath"):
                handoff_paths.add(root / receipt["handoffPath"])
    publications = {}
    for path in sorted(handoff_paths):
        handoff = load_json(path)
        published = stamp(handoff["generatedAt"])
        for item in handoff.get("forecasts", []):
            sha = item["objectSha256"]
            if sha not in publications or published < publications[sha][0]:
                publications[sha] = (published, path, item)
    return publications


def descriptive_summary(rows):
    """Small pregame-support accounting; no tuning, causal tests or subgroup search."""
    groups = {
        "selected_all": [r for r in rows if r["population"] == "SELECTED_V18_POSITION"],
        "selected_wins": [r for r in rows if r.get("wager_result") == "WIN"],
        "selected_losses": [r for r in rows if r.get("wager_result") == "LOSS"],
        "nonselected_producer_comparators": [r for r in rows if r["population"] != "SELECTED_V18_POSITION"],
    }
    result = {}
    for name, cohort in groups.items():
        if not cohort:
            result[name] = {"n": 0}
            continue
        item = {
            "n": len(cohort),
            "any_null_starting_matchup_input": sum(r["raw_missing_cells"] > 0 for r in cohort),
            "any_batter_missing_eligible_annual_prior": sum(r["annual_prior_missing_unique_batters"] > 0 for r in cohort),
            "any_starter_missing_eligible_annual_prior": sum(any(r[s + "_starter_prior_missing"] == 1 for s in ("home", "away")) for r in cohort),
            "any_starter_window_below_250_bf": sum(min(r[s + "_starter_last250_bf_count"] for s in ("home", "away")) < 250 for r in cohort),
            "any_batter_low_window": sum(r["home_batter_low_window_count"] + r["away_batter_low_window_count"] > 0 for r in cohort),
            "mean_explicit_legitimate_missing_template_cells": mean(r["explicit_legitimate_missing_cells"] for r in cohort),
            "mean_forecast_total_runs": mean(json.loads(r["retained_expectations_json"])["totalRuns"] for r in cohort),
            "max_draw_probability_reconciliation_error": max(r["p_home_draw_reconciliation_abs"] for r in cohort),
            "genuine_exact_forecast_observer_metadata": sum(r["prospective_observer_status"] == "GENUINE_PROSPECTIVE_EXACT_FORECAST_CAPTURE_METADATA_VERIFIED" for r in cohort),
        }
        if name != "nonselected_producer_comparators":
            item.update({
                "mean_admitted_actual_total_runs": mean(float(r["wager_final_home_score"]) + float(r["wager_final_away_score"]) for r in cohort),
                "mean_selected_side_raw_probability": mean(float(r["wager_p_win_raw"]) for r in cohort),
                "mean_selected_side_controlling_probability": mean(float(r["wager_p_win_controlling"]) for r in cohort),
                "mean_same_book_no_vig_selected_probability": mean(float(r["wager_no_vig_p_selected_same_book"]) for r in cohort),
                "observed_selected_win_fraction": sum(r["wager_result"] == "WIN" for r in cohort) / len(cohort),
            })
        result[name] = item
    return {"schema": "MLB_V18_WAGER_DESCRIPTIVE_DIAGNOSTICS_V1", "interpretation": "Already inspected September operational evidence; descriptive counts only. Wins/losses are presented symmetrically. No hypothesis tests, causal attribution, calibration fit, threshold tuning or model selection. Comparator outcomes are not supplied.", "groups": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=Path(r"C:\Users\james\asp-model-studio"))
    parser.add_argument("--authority", type=Path, default=Path(r"C:\Users\james\aisp-analysis\wagering-record-20260918"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cutoff", default="2026-09-18T20:15:00Z")
    args = parser.parse_args()
    source_refs = {n: reference(args.authority / n) for n in ["positions.csv", "REPORT.md", "summary.json", "analysis.py"]}
    identities, selected_identity, gate = identity_gate(args.authority / "positions.csv", args.runtime)
    # Only here are wager outcome columns admitted, from the authoritative export.
    positions = pd.read_csv(args.authority / "positions.csv", dtype=str, keep_default_na=False)
    selected = positions[positions.position_id.isin(selected_identity.position_id)].copy()
    if not len(selected):
        raise ValueError("NO_V18_AUTHORITY_POSITIONS")
    cutoff = stamp(args.cutoff)
    pipeline = args.runtime / "outputs/mlb-v18-current-state-pipeline-v1"
    local_dates = set(pd.to_datetime(selected.kickoff_utc, utc=True).dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d"))
    publications = retained_publications(pipeline, local_dates)
    selected_games = set(selected.game_id)
    rows, quality, refs = [], [], dict(source_refs)
    ignored = []

    def make_row(sha, position=None):
        directory = pipeline / "objects/sha256" / sha
        decision = position["decision_timestamp_utc"] if position else None
        result = extract_forecast_evidence(directory, decision_utc=decision)
        forecast = load_json(directory / "forecast.json")
        observed = publications.get(sha)
        row = {"position_id": position["position_id"] if position else "", "game_id": forecast["gameId"], "forecast_identity": "mlb-v18-daily-" + sha, "object_sha256": sha, "population": "SELECTED_V18_POSITION" if position else "NONSELECTED_RETAINED_PRODUCER_COMPARATOR", "sport": "MLB", "era": "MLB_V18", "authority_positions_sha256": source_refs["positions.csv"]["sha256"], "authority_cutoff_utc": args.cutoff, "comparison_time_rule": "EXACT_DECISION_NAMED_FORECAST" if position else "LATEST_RETAINED_PUBLISHED_VERSION_BY_KICKOFF_MINUS_15_MINUTES", "consumer_import_or_decision_eligibility_asserted": bool(position), "selected_position_on_game": bool(position), **result}
        row["position_id"] = position["position_id"] if position else ""
        row["game_id"] = forecast["gameId"]
        row["forecast_identity"] = "mlb-v18-daily-" + sha
        clocks = json.loads(row["source_clocks_json"])
        row["source_records_ingested_before_observed"] = sum(bool(c.get("ingestedAt") and c.get("observedAt") and stamp(c["ingestedAt"]) < stamp(c["observedAt"])) for c in clocks)
        row["source_clock_order_interpretation"] = "LITERAL_ORDER_ANOMALY_CLOCK_SEMANTICS_UNRESOLVED; NOT_ITSELF_TARGET_LEAKAGE" if row["source_records_ingested_before_observed"] else "NO_INGESTION_BEFORE_OBSERVATION_IN_RETAINED_STARTER_LINEUP_CLOCKS"
        if observed:
            published, hp, hi = observed
            row["earliest_retained_handoff_utc"] = published.isoformat()
            row["earliest_retained_handoff_path"] = str(hp)
            row["earliest_retained_handoff_sha256"] = reference(hp)["sha256"]
            row["handoff_evidence_readiness_json"] = json.dumps(hi.get("evidenceReadiness"), sort_keys=True, separators=(",", ":"))
            refs[str(hp)] = reference(hp)
        if position:
            # Prefix preserves the consumer meaning and avoids overwriting producer facts.
            for key, value in position.items():
                if key not in {"position_id", "game_id", "forecast_identity"}:
                    row["wager_" + key] = value
            side = position["selected_side"].lower()
            if side not in {"home", "away"}:
                raise ValueError("UNSUPPORTED_SELECTED_SIDE")
            selected_probability = forecast["probabilities"]["homeWin" if side == "home" else "awayWin"]
            row["model_selected_side_probability"] = selected_probability
            row["raw_probability_join_error"] = selected_probability - float(position["p_win_raw"])
            row["forecast_created_before_decision"] = stamp(forecast["forecastCreatedAt"]) <= stamp(decision)
            row["input_snapshot_before_decision"] = stamp(forecast["capturedAt"]) <= stamp(decision)
            row["earliest_handoff_before_decision"] = bool(observed and observed[0] <= stamp(decision))
            if abs(row["raw_probability_join_error"]) > 1e-10:
                quality.append({"kind": "RAW_PROBABILITY_MISMATCH", "position_id": position["position_id"], "difference": row["raw_probability_join_error"]})
            if not row["forecast_created_before_decision"] or not row["input_snapshot_before_decision"]:
                quality.append({"kind": "MODEL_CLOCK_AFTER_DECISION", "position_id": position["position_id"]})
        return row

    for position in selected.to_dict("records"):
        rows.append(make_row(position["forecast_identity"].removeprefix("mlb-v18-daily-"), position))

    comparators = {}
    for sha, (published, path, item) in publications.items():
        if item["gameId"] in selected_games:
            continue
        start = stamp(item["scheduledStart"])
        if start > cutoff or published > min(cutoff, start - timedelta(minutes=15)):
            continue
        forecast = load_json(pipeline / "objects/sha256" / sha / "forecast.json")
        if not all(quarantine.final_oot_eligible_key_mask([str(forecast["sourceGameId"])])):
            raise ValueError("PROTECTED_COMPARATOR_ALIAS")
        date = start.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).strftime('%Y-%m-%d')
        if date not in local_dates or "2026-08-14" <= date <= "2026-08-27":
            continue
        created = stamp(forecast["forecastCreatedAt"])
        if created > start - timedelta(minutes=15):
            continue
        candidate = (created, published, sha)
        if item["gameId"] not in comparators or candidate > comparators[item["gameId"]]:
            comparators[item["gameId"]] = candidate
    for game, (_, _, sha) in sorted(comparators.items()):
        rows.append(make_row(sha))
    for row in positions[~positions.position_id.isin(selected.position_id)].to_dict("records"):
        ignored.append({k: row[k] for k in ["position_id", "game_id", "sport", "era", "forecast_identity"]})
    if len({r["game_id"] for r in rows}) != len(rows):
        raise ValueError("JOIN_GRAIN_BLOWUP")
    for name, before in source_refs.items():
        if reference(args.authority / name) != before:
            raise ValueError("CLAUDE_AUTHORITY_CHANGED_DURING_EXTRACTION")
    args.output.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with (args.output / "model_evidence.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader(); writer.writerows(rows)
    (args.output / "model_evidence.jsonl").write_text("".join(json.dumps(row, sort_keys=True, default=str) + "\n" for row in rows), encoding="utf-8")
    (args.output / "separate_eras.json").write_text(json.dumps(ignored, indent=2) + "\n", encoding="utf-8")
    report = {"schema": "MLB_V18_WAGER_MODEL_EVIDENCE_JOIN_V1", "extractedAtUtc": datetime.now(timezone.utc).isoformat(), "identityGate": gate, "authority": source_refs, "grain": "One exact forecast per selected position; one pre-T-15 retained forecast per distinct nonselected game", "selectedPositions": len(selected), "selectedResults": selected.result.value_counts().to_dict(), "nonselectedProducerComparators": len(comparators), "olderMlbAndOtherSportsSeparate": len(ignored), "tableRows": len(rows), "columns": len(columns), "qualityIssues": quality, "selectedSourceRecordsIngestedBeforeObserved": sum(r["source_records_ingested_before_observed"] for r in rows if r["population"] == "SELECTED_V18_POSITION"), "sourceClockOrderQualification": "Timestamp convention anomaly retained separately from validated predecision availability; no Stage-A clock-order pass asserted", "comparatorOutcomeAuthority": "NOT_PROVIDED_NO_OUTCOMES_JOINED", "comparatorConsumerEligibility": "NOT_ASSERTED_NO_COMPLETE_CONSUMER_CANDIDATE_EXPORT", "comparatorSelection": "Same local slate dates; no position in Claude export; latest version with original retained handoff before kickoff minus 15 minutes; no selection by outcome", "productionChanges": 0, "providerRequests": 0, "modelFitsOrSimulations": 0, "protectedPayloadsOpened": 0, "table": reference(args.output / "model_evidence.csv")}
    (args.output / "JOIN_RECEIPT.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    (args.output / "SOURCE_INDEX.json").write_text(json.dumps({"schema": "MLB_WAGER_DIAGNOSIS_SOURCES_V1", "references": list(refs.values())}, indent=2) + "\n", encoding="utf-8")
    (args.output / "COLUMN_DICTIONARY.json").write_text(json.dumps({"grain": report["grain"], "authorityFields": "wager_* fields are unchanged values from Claude's reconciled export; empty comparator fields are not missing wagers", "evidenceFields": "Producer fields refer to the exact retained forecast bundle; *_json cells preserve structured diagnostics and *_path/_sha256 identify original artifacts", "derivedDiagnostics": "Summaries computed now from retained original inputs or draws do not claim original diagnostic recording", "columns": columns}, indent=2) + "\n", encoding="utf-8")
    (args.output / "DIAGNOSTICS_SUMMARY.json").write_text(json.dumps(descriptive_summary(rows), indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["selectedPositions", "selectedResults", "nonselectedProducerComparators", "tableRows", "columns", "qualityIssues"]}, indent=2))


if __name__ == "__main__":
    main()
