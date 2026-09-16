"""Compact projection of saved three-arm study/scoring/publication receipts.

No model, simulation, database, provider, exchange-write or AISP-write interface.
Run after the bounded driver finishes; package/publication evidence may lag it.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/mlb-v18-three-arm-pregame-comparison-v1"
EXCHANGE_CURRENT = Path("C:/Users/james/asp-model-exchange/mlb-v18-ensemble-research-v1/three-arm-pregame-comparison-v1/current.json")
ARMS = ("V18_BASE", "V18_SURVIVAL_ONLY", "V18_TRANSITION_ONLY")
ORDINARY_TICK = ROOT / "outputs/mlb-v18-unattended-v1/objects/sha256/9129a2fd662035f89edca61710a698f89f8175b98e7f98ca7168656ebd859bff/tick.json"
ORDINARY_SLATE = ROOT / "outputs/mlb-v18-current-state-pipeline-v1/slates/2026-09-12/sha256/17c8a9f98f2a45d385bbc089a40a3c90b9bb919ce39835d407cc1dd8571e67f4/slate-result.json"


def ref(path):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def read_ref(item):
    actual = ref(item["path"])
    if actual["sha256"] != item["sha256"] or actual["bytes"] != item["bytes"]:
        raise ValueError("SAVED_REPORT_SOURCE_HASH_MISMATCH")
    return json.loads(Path(item["path"]).read_bytes())


def resolve(path):
    item = ref(path)
    value = read_ref(item)
    if isinstance(value, dict) and {"path", "sha256", "bytes"} <= value.keys():
        return value, read_ref(value)
    return item, value


def optional(path):
    return resolve(path) if path and Path(path).is_file() else (None, None)


def link(label, item):
    return "[" + label + "](<" + str(item["path"]).replace("\\", "/") + ">)"


def display_summary(summary):
    return f"{100 * summary['homeWinProbability']:.2f}% / {summary['meanTotalRuns']:.3f}"


def display_delta(delta):
    return f"{delta['homeWinPercentagePoints']:+.2f} / {delta['meanTotalRuns']:+.3f}"


def short_fallback(reason):
    marker = "DURATION_HISTORY_UNSUPPORTED: "
    if marker in reason:
        try:
            gaps = json.loads(reason.split(marker, 1)[1])
            if gaps and all(g.get("reason") == "STARTER_MLBAM_TO_HISTORY_IDENTITY_UNRESOLVED" for g in gaps):
                players = ", ".join(g["side"] + " pitcher " + str(g["starterMlbamId"]) for g in gaps)
                return "Certified pre-cutoff starter-history mappings are unresolved for " + players
        except (ValueError, TypeError, KeyError):
            pass
    return reason


def project_pending(future, tick_path, slate_path):
    waiting = [r for r in future if r["status"] == "WAITING_FOR_ORDINARY_PUBLISHER"]
    tick_ref, tick = optional(tick_path)
    slate_ref, slate = optional(slate_path)
    if not waiting or not tick or not slate:
        return None
    projections = []
    for item in waiting:
        pairs = [[r for r in source["games"] if r.get("gameId") == item["gameId"]] for source in (tick, slate)]
        if any(len(rows) != 1 for rows in pairs):
            raise ValueError("PENDING_PUBLISHER_IDENTITY_MISSING_OR_DUPLICATED")
        first, second = pairs[0][0], pairs[1][0]
        for row in (first, second):
            if str(row["mlbamGamePk"]) != item["sourceGameId"]:
                raise ValueError("PENDING_PUBLISHER_SOURCE_GAME_MISMATCH")
        if any(first.get(k) != second.get(k) for k in ("status", "reason", "blockers", "checkpoint")):
            raise ValueError("LATEST_TICK_SLATE_PENDING_DISPOSITION_DIFFERS")
        reasons = (first.get("sourcePreflight") or {}).get("reasons") or [first["reason"]]
        if set(reasons) == {"AWAY_CONFIRMED_ORDERED_NINE_PLAYER_LINEUP_UNAVAILABLE", "AWAY_LINEUP_SOURCE_CLOCK_UNAVAILABLE"}:
            meaning = "Awaiting confirmed away lineup and its source timestamp"
        elif first["reason"] == "CHECKPOINT_NOT_DUE":
            meaning = "Next ordinary source checkpoint is not yet due"
        else:
            meaning = "; ".join(reasons)
        projected = {"gameId": item["gameId"], "sourceGameId": item["sourceGameId"], "status": first["status"],
                     "reason": first["reason"], "reasons": reasons, "checkpoint": first.get("checkpoint"), "meaning": meaning}
        item["ordinaryPublicationDisposition"] = projected
        projections.append(projected)
    return {"schemaVersion": "MLB_THREE_ARM_PENDING_BASELINE_EVIDENCE_V1", "checkedAtUtc": tick["completedAt"],
            "ordinaryTick": tick_ref, "ordinarySlate": slate_ref, "games": projections,
            "scope": "Only absent-baseline declared games; saved publisher dispositions, no new source probe."}


def build(args):
    status_ref, status = resolve(args.study_current)
    scoring_ref, scoring = resolve(args.scoring_current)
    start_ref, start = resolve(args.start_audit)
    support_gap_ref, _ = optional(args.survival_support_gap)
    if status.get("schemaVersion") != "MLB_V18_THREE_ARM_PREGAME_V1_STATUS":
        raise ValueError("COMPLETED_SAVED_DRIVER_STATUS_REQUIRED")
    declaration_ref = status["declaration"]
    declaration = read_ref(declaration_ref)
    records = status["records"]
    if len(records) != len(declaration["games"]) or len({r["gameId"] for r in records}) != len(records):
        raise ValueError("COHORT_IDENTITY_ACCOUNTING_MISMATCH")
    members = {g["gameId"]: g for g in declaration["games"]}
    future = []
    for row in records:
        if row["gameId"] not in members or row["sourceGameId"] != members[row["gameId"]]["sourceGameId"]:
            raise ValueError("SAVED_STATUS_DECLARED_IDENTITY_MISMATCH")
        item = {"gameId": row["gameId"], "sourceGameId": row["sourceGameId"], "status": row["status"],
                "deadlineUtc": row["deadlineUtc"], "scheduledStartUtc": row["scheduledStartUtc"]}
        if "result" in row:
            result = read_ref(row["result"])
            if result.get("schemaVersion") != "MLB_V18_THREE_ARM_PREGAME_V1_RESULT" or result["declaration"] != declaration_ref or result["gameId"] != row["gameId"]:
                raise ValueError("FROZEN_GAME_RECEIPT_MISMATCH")
            summaries = {arm: result["arms"][arm]["summary"] for arm in ARMS}
            base = summaries[ARMS[0]]
            for summary in summaries.values():
                if not all(math.isfinite(float(summary[k])) for k in ("homeWinProbability", "meanTotalRuns")):
                    raise ValueError("NONFINITE_SAVED_FORECAST_SUMMARY")
            changes = {arm: {"homeWinPercentagePoints": 100 * (summaries[arm]["homeWinProbability"] - base["homeWinProbability"]),
                             "meanTotalRuns": summaries[arm]["meanTotalRuns"] - base["meanTotalRuns"]} for arm in ARMS[1:]}
            item.update(result=row["result"], teams=result["teams"], baselineForecastId=result["baselineForecastId"],
                        baselineForecastCreatedAtUtc=result["baselineForecastCreatedAtUtc"],
                        frozenAtUtc=result["frozenAtUtc"], sourceCutoff=result["sourceCutoff"], arms=result["arms"],
                        summaries=summaries, forecastChanges=changes, commonSupported=result["commonSupported"],
                        population=result["population"], classification=result["classification"])
            expected_common = all(result["arms"][a]["status"] == "APPLIED" for a in ARMS[1:])
            if expected_common != result["commonSupported"]:
                raise ValueError("COMMON_SUPPORTED_ACCOUNTING_MISMATCH")
        future.append(item)
    pending_evidence = project_pending(future, args.ordinary_tick, args.ordinary_slate)
    frozen = [r for r in future if "result" in r]
    package_ref, package = optional(args.package_current)
    publication_ref, publication = optional(args.publication)
    published_package_ref = published_package = None
    published_rows = []
    if publication:
        if publication.get("schemaVersion") != "MLB_V18_THREE_ARM_EXCHANGE_PUBLICATION_V1":
            raise ValueError("ACTUAL_THREE_ARM_EXCHANGE_PUBLICATION_RECEIPT_REQUIRED")
        published_package_ref = publication["sourcePackage"]
        published_package = read_ref(published_package_ref)
        if published_package["declaration"] != declaration_ref:
            raise ValueError("PUBLICATION_IS_FOR_ANOTHER_DECLARED_COHORT")
        clock_rows = publication["forecastPublicationClocks"]
        clocks = {r["forecastId"]: r for r in clock_rows}
        if len(clocks) != len(clock_rows):
            raise ValueError("DUPLICATE_PUBLICATION_FORECAST_ID")
        for forecast in published_package["forecasts"]:
            c = clocks.get(forecast["forecastId"])
            if not c or c["objectSha256"] != forecast["objectSha256"]:
                raise ValueError("FORECAST_PUBLICATION_CLOCK_BINDING_MISSING")
            if forecast["canonicalGameId"] not in {r["gameId"] for r in frozen}:
                raise ValueError("PUBLISHED_GAME_NOT_PRESENT_IN_SAVED_FROZEN_COHORT")
            if datetime.fromisoformat(c["firstExchangePublishedAtUtc"].replace("Z", "+00:00")) >= datetime.fromisoformat(c["policyCutoffUtc"].replace("Z", "+00:00")):
                raise ValueError("PUBLICATION_AFTER_ORIGINAL_DEADLINE")
            published_rows.append({**forecast, **c})
    consumer_ref, consumer = optional(args.consumer_evidence)
    source_package_ref = published_package_ref or package_ref
    consumer_matches_package = bool(consumer and source_package_ref and
                                    consumer.get("sourcePackage", {}).get("sha256") == source_package_ref["sha256"])
    imported_ids = set()
    if consumer_matches_package and consumer.get("actualPersistedRowsVerified") is True:
        expected = {r["forecastId"]: r for r in published_rows}
        for row in consumer.get("confirmedForecasts", []):
            f = expected.get(row["forecastId"])
            if not f or any(str(row[k]) != str(f[k]) for k in ("canonicalGameId", "sourceGameId", "objectSha256")) or not row.get("consumerRecordId"):
                raise ValueError("CONSUMER_IMPORT_CONFIRMATION_IDENTITY_MISMATCH")
            imported_ids.add(row["forecastId"])
    counts = {"declaredGames": len(records), "locallyFrozenGames": len(frozen),
              "exchangePublishedGames": len({r["canonicalGameId"] for r in published_rows}), "exchangePublishedCandidateForecasts": len(published_rows),
              "survivalSupportedGames": sum(r["arms"][ARMS[1]]["status"] == "APPLIED" for r in frozen),
              "transitionSupportedGames": sum(r["arms"][ARMS[2]]["status"] == "APPLIED" for r in frozen),
              "commonSupportedGames": sum(r["commonSupported"] for r in frozen),
              "fallbackArms": sum(r["arms"][a]["status"] == "BASELINE_FALLBACK" for r in frozen for a in ARMS[1:]),
              "blockedOrPendingGames": len(records) - len(frozen), "importConfirmedCandidateForecasts": len(imported_ids),
              "importConfirmedGames": len({r["canonicalGameId"] for r in published_rows if r["forecastId"] in imported_ids})}
    for original, projected in {"declared": "declaredGames", "locallyFrozen": "locallyFrozenGames",
            "survivalSupported": "survivalSupportedGames", "transitionSupported": "transitionSupportedGames",
            "commonSupported": "commonSupportedGames", "fallbackArms": "fallbackArms",
            "blockedOrPending": "blockedOrPendingGames"}.items():
        if status["counts"][original] != counts[projected]:
            raise ValueError("SAVED_DRIVER_COUNT_RECONCILIATION_FAILED:" + original)
    handoffs = (publication or package or {}).get("handoffs", {})
    for descriptor in handoffs.values():
        read_ref(descriptor)
    for descriptor in start["restoration"].values():
        read_ref(descriptor)
    source_package = published_package or package
    commands = {"score": ".venv/Scripts/python.exe scripts/score_mlb_frozen_component_pairs_v1.py",
                "plan": ".venv/Scripts/python.exe scripts/run_mlb_v18_three_arm_pregame_v1.py plan",
                "boundedRun": ".venv/Scripts/python.exe scripts/run_mlb_v18_three_arm_pregame_v1.py run --max-games 1 --wall-seconds 1200",
                "packageAndPublish": ".venv/Scripts/python.exe scripts/package_mlb_v18_three_arm_pregame_comparison_v1.py --export",
                "report": ".venv/Scripts/python.exe scripts/report_mlb_v18_three_arm_comparison_v1.py"}
    report = {"schemaVersion": "MLB_V18_THREE_ARM_COMPACT_REPORT_V1", "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
              "taskCommit": args.task_commit, "slateDate": declaration["slateDate"], "declaredAtUtc": declaration["declaredAtUtc"],
              "ordinaryPendingEvidence": pending_evidence,
              "survivalSupportGap": support_gap_ref,
              "stopAfterUtc": declaration["stopAfterUtc"], "counts": counts, "existingStudies": scoring["studies"], "futureGames": future,
              "publishedForecasts": published_rows, "confirmedForecastIds": sorted(imported_ids), "handoffs": handoffs,
              "handoffStatus": "EXCHANGE_PUBLISHED" if publication else "LOCAL_PACKAGE_ONLY" if package else "NOT_YET_PACKAGED",
              "packageDeclaredConsumerStatus": (source_package or {}).get("consumerStatus"),
              "consumerVerification": consumer.get("checks") if consumer_matches_package else None,
              "consumerEvidenceMatchesPackage": consumer_matches_package,
              "aispImport": (source_package or {}).get("aispImport"),
              "claudeGuide": (source_package or {}).get("claudeGuide"), "requiredFinalEvidence": scoring.get("requiredOwnerAction"),
              "nfl": {"status": start["restorationStatus"], "originalDeadlineUtc": start["restoreDeadlineUtc"],
                      "actualRestoredAtUtc": "2026-09-12T20:55:30.619329Z", "actualArchiveRunAtUtc": "2026-09-12T20:55:41.182294Z",
                      "actualSchedulerStatus": start["actualNFLScheduler"]["status"], "receipts": start["restoration"]},
              "verdict": "INSUFFICIENT_EVIDENCE", "performanceClaim": "Forecast changes are not measured accuracy gains. Fallbacks are operational coverage, not component trials. Studies remain separate; direct survival-versus-transition assessment is restricted to common supported games. Five thousand simulations are one observed game, and inherited chronology limitations remain.",
              "commands": commands, "sources": {"driverStatus": status_ref, "declaration": declaration_ref, "scoring": scoring_ref,
                  "startAudit": start_ref, "localPackage": package_ref, "publication": publication_ref, "publishedPackage": published_package_ref,
                  "consumerEvidence": consumer_ref, "reportCode": ref(__file__)}, "newSimulations": 0, "databaseReads": 0, "providerCalls": 0}
    lines = [f"MLB pregame comparison: {declaration['slateDate']}. Verdict: insufficient assessment evidence.", "",
             f"Existing frozen studies: {scoring['scoredGames']} scored and {scoring['pendingGames']} pending. Candidate-minus-baseline losses below zero favor the candidate; signed run error is predicted minus observed.", "",
             "| Existing study | Status / prerequisite | Δ log loss | Δ Brier |", "|---|---|---:|---:|"]
    for row in scoring["studies"]:
        delta = row.get("candidateMinusBaseline")
        disposition = row.get("prerequisite", row["status"])
        if row.get("score"):
            disposition = link("scored metrics", row["score"])
        lines.append(f"| {row['study']} ({row['sourceGameId']}) | {disposition} | " + (f"{delta['winnerLogLoss']:+.6f} | {delta['winnerBrier']:+.6f}" if delta else "— | —") + " |")
    lines += ["", "COL–DET is the September 11 game 824227. NYM–NYY lacks retained candidate distributions, so candidate CRPS, intervals and joint scores remain unavailable. Missing starter BF or transition sequences does not prevent eligible whole-game scoring. " + link("Exact final requirements and scoring evidence", scoring_ref) + ".", "",
              f"Future cohort: **{counts['declaredGames']} declared; {counts['locallyFrozenGames']} locally frozen; {counts['exchangePublishedGames']} {'game' if counts['exchangePublishedGames'] == 1 else 'games'} / {counts['exchangePublishedCandidateForecasts']} candidate forecasts exchange-published; {counts['importConfirmedCandidateForecasts']} imports confirmed**. Supported games: survival {counts['survivalSupportedGames']}, transition {counts['transitionSupportedGames']}, common {counts['commonSupportedGames']}. Fallback arms: {counts['fallbackArms']}; blocked/pending games: {counts['blockedOrPendingGames']}. Stopping boundary: {declaration['stopAfterUtc']}.", "",
              "Cells show home-win probability / mean total runs. Changes are candidate minus baseline in percentage points / runs: **forecast changes, not accuracy gains**. F = exact baseline fallback; pending cells have no frozen comparison.", "",
              "| Game / MLBAM | V18 base | Survival | Transition | Δ survival | Δ transition |", "|---|---:|---:|---:|---:|---:|"]
    for row in future:
        if "summaries" not in row:
            disposition = row.get("ordinaryPublicationDisposition", {}).get("meaning") or ("Baseline ready; comparison unattempted" if row["status"] == "BASELINE_OBJECT_AVAILABLE" else row["status"])
            lines.append(f"| {row['sourceGameId']} | {disposition} | — | — | — | — |")
            continue
        name = row["teams"]["AWAY"]["abbreviation"] + "–" + row["teams"]["HOME"]["abbreviation"] + " / " + row["sourceGameId"]
        cells = [display_summary(row["summaries"][a]) + (" F" if row["arms"][a]["status"] == "BASELINE_FALLBACK" else "") for a in ARMS]
        lines.append("| " + name + " | " + " | ".join(cells + [display_delta(row["forecastChanges"][a]) for a in ARMS[1:]]) + " |")
    reasons = sorted({r["arms"][a]["fallbackReason"] for r in frozen for a in ARMS[1:] if r["arms"][a]["status"] == "BASELINE_FALLBACK"})
    if reasons:
        lines += ["", "Fallback prerequisites: " + "; ".join(short_fallback(r) for r in reasons) + "."]
    if support_gap_ref:
        lines += ["", link("Survival history evidence", support_gap_ref) + ": the registry covers only pilot pitchers 664285/690279 through 2026-09-10. It lacks the required current-starter coverage; repairing identity mappings alone is insufficient."]
    if pending_evidence:
        lines += ["", "Absent-baseline dispositions use the " + link("saved ordinary tick", pending_evidence["ordinaryTick"]) + " completed " + pending_evidence["checkedAtUtc"] + "."]
    lines += ["", "The unchanged V18 PA estimator, preprocessing and default authority remain fixed. Survival and transition are separate interventions; calibration stays disabled. Only common supported games can compare the two interventions directly. The fitted model's inherited training chronology remains uncertified. No superiority claim follows from these integrations or from 5,000 Monte Carlo draws per game.", ""]
    if handoffs:
        lines += ["Claude handoff (" + report["handoffStatus"] + "):", ""]
        for arm, descriptor in handoffs.items():
            lines.append("- " + link(arm, descriptor) + " — SHA256 `" + descriptor["sha256"] + "`.")
        if report["claudeGuide"]:
            lines += ["", link("Exact import command and consumer prerequisites", report["claudeGuide"]) + ". V1 survival import verification and V2 TRANSITION support are distinct from actual imports. Confirm imports/display separately; the existing consumer must retain exact baseline identity and configuration selection."]
        if consumer_matches_package:
            checks = consumer.get("checks", {})
            if (checks.get("survivalV1", {}).get("status") == "PASS" and
                    checks.get("baselineSystemAndForecastBinding", {}).get("status") == "PASS"):
                lines += ["", link("Consumer verification", consumer_ref) + ": survival V1 and exact stored baseline binding passed. " +
                          ("The current consumer refuses the V2 TRANSITION envelope." if checks.get("transitionV2", {}).get("status") == "EXPECTED_CURRENT_CONSUMER_REFUSAL" else "See its exact transition disposition.")]
    else:
        lines += ["No candidate exchange handoff is yet recorded."]
    lines += ["", "NFL restoration: scheduler " + start["actualNFLScheduler"]["status"] + ". Original deadline " + start["restoreDeadlineUtc"] + "; " + link("actual restoration", start["restoration"]["nfl_restored"]) + " at 2026-09-12T20:55:30.619329Z and " + link("actual archive run", start["restoration"]["nfl_archive_resumed"]) + " at 2026-09-12T20:55:41.182294Z. Both preceded this task's 20:56 UTC start.", "",
              "Run in Model Studio:", "```powershell", commands["score"], commands["plan"], commands["boundedRun"], commands["packageAndPublish"], commands["report"], "```", "",
              "Use the bounded run only for still-eligible declared games; preserve original deadlines and existing locks. Task commit: " + (args.task_commit or "not yet recorded") + "."]
    args.output_root.mkdir(parents=True, exist_ok=True)
    if pending_evidence:
        (args.output_root / "ordinary-pending-evidence.json").write_text(json.dumps(pending_evidence, indent=2) + "\n", encoding="utf-8")
    (args.output_root / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    raw = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    target = args.output_root / "report-objects/sha256" / digest / "report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != raw:
        raise ValueError("IMMUTABLE_REPORT_COLLISION")
    if not target.exists():
        target.write_bytes(raw)
    pointer = ref(target)
    (args.output_root / "report-current.json").write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
    return {"report": ref(args.output_root / "REPORT.md"), "machineResult": pointer, "counts": counts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-current", type=Path, default=OUT / "current.json")
    parser.add_argument("--scoring-current", type=Path, default=OUT / "scoring/current.json")
    parser.add_argument("--package-current", type=Path, default=OUT / "package-current.json")
    parser.add_argument("--publication", type=Path, default=EXCHANGE_CURRENT)
    parser.add_argument("--consumer-evidence", type=Path, default=OUT / "consumer-checks-v2.json")
    parser.add_argument("--ordinary-tick", type=Path, default=ORDINARY_TICK)
    parser.add_argument("--ordinary-slate", type=Path, default=ORDINARY_SLATE)
    parser.add_argument("--start-audit", type=Path, default=OUT / "start-preservation-and-restoration.json")
    parser.add_argument("--survival-support-gap", type=Path, default=OUT / "survival-support-gap.json")
    parser.add_argument("--output-root", type=Path, default=OUT)
    parser.add_argument("--task-commit")
    print(json.dumps(build(parser.parse_args()), indent=2))
