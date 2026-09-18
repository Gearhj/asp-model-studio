"""Freeze concise NBA Gen2 evidence and the append-only acquisition successor."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]


def canonical_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def physical(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               allow_nan=False) + "\n", encoding="utf-8")


def f(value: float) -> str:
    return f"{value:.4f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/nba-gen2-production-readiness-v1")
    parser.add_argument("--docs", type=Path, default=ROOT / "docs/nba-gen2-production-readiness-v1")
    parser.add_argument("--private-root", type=Path,
                        default=Path(r"C:\Users\james\asp-data-staging\nba\gen2-team-box-v1"))
    args = parser.parse_args()
    assessment = json.loads((args.output / "ASSESSMENT.json").read_text(encoding="utf-8"))
    source = json.loads((args.private_root / "acquisition-receipt.json").read_text(encoding="utf-8"))
    prior_path = (args.private_root / "receipts/sha256/632125f21647099fa5df121dc68f872559581628c605758b963faf433da0ec32/acquisition-failure.json")
    if physical(prior_path) != "632125f21647099fa5df121dc68f872559581628c605758b963faf433da0ec32":
        raise RuntimeError("Original failure receipt changed")

    study_dir = args.private_root / "studies/sha256" / assessment["assessmentIdentitySha256"]
    retention_path = study_dir / "RETENTION_RECEIPT.json"
    if not retention_path.exists():
        retained = []
        for source_path in sorted(path for path in args.output.rglob("*") if path.is_file()):
            relative = source_path.relative_to(args.output)
            target_path = study_dir / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists() and physical(target_path) != physical(source_path):
                raise RuntimeError(f"Retained study member differs: {relative}")
            if not target_path.exists():
                shutil.copyfile(source_path, target_path)
            retained.append({"relativePath": relative.as_posix(), "physicalSha256": physical(target_path),
                             "bytes": target_path.stat().st_size})
        write_json(retention_path, {
            "schemaVersion": "nba-gen2-private-study-retention-v1",
            "createdAtUtc": datetime.now(timezone.utc).isoformat(),
            "assessmentIdentitySha256": assessment["assessmentIdentitySha256"],
            "classification": "PRIVATE_RESEARCH_EVIDENCE_OUTSIDE_GIT",
            "members": retained,
        })
    retention_sha = physical(retention_path)

    public_receipt_path = args.docs / "ACQUISITION_SUCCESSOR_RECEIPT.json"
    existing_public = (json.loads(public_receipt_path.read_text(encoding="utf-8"))
                       if public_receipt_path.exists() else None)
    successor = {
        "schemaVersion": "nba-gen2-acquisition-successor-v1",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "predecessor": {"path": str(prior_path), "physicalSha256": physical(prior_path),
                        "preservedUnchanged": True},
        "authorization": "Explicit continuation limited to seven team-box and eight schedule files from SportsDataverse/hoopR CC BY 4.0",
        "revisedAdmission": {
            "reason": "The original stop incorrectly required source total_rebounds to equal OREB + DREB.",
            "rule": "Preserve total_rebounds separately; use OREB and DREB directly for four-factor/rebounding features.",
            "observedIdentity": assessment["populationAudit"]["totalReboundIdentity"],
            "minutes": "Derived as 240 + 25 * overtime periods from matched completed schedule status_period; no minutes fabricated.",
        },
        "acquisition": {
            "receiptPath": str(args.private_root / "acquisition-receipt.json"),
            "receiptPhysicalSha256": physical(args.private_root / "acquisition-receipt.json"),
            "contentIdentitySha256": source["contentIdentitySha256"],
            "successfulRequestsCumulative": source["successfulHttpRequests"],
            "successfulRequestsAdditional": 15,
            "acceptedBytesCumulative": source["responseBytes"],
            "acceptedBytesAdditional": source["responseBytes"] - source["requests"][0]["bytes"],
            "costUsd": source["costUsd"], "nbaComRequests": source["nbaComRequests"],
            "zeroRetries": True,
        },
        "population": {
            "identitySha256": assessment["populationAudit"]["populationIdentitySha256"],
            "games": assessment["populationAudit"]["games"],
            "regularSeasonGames": assessment["populationAudit"]["regularSeasonGames"],
            "playoffGamesSeparate": assessment["populationAudit"]["playoffGames"],
            "integrityQuarantineGameIds": assessment["populationAudit"]["integrityQuarantineGameIds"],
        },
        "assessment": {"identitySha256": assessment["assessmentIdentitySha256"],
                       "disposition": assessment["disposition"],
                       "privateStudyPath": str(study_dir),
                       "retentionReceiptPhysicalSha256": retention_sha},
        "authority": {"productionActivated": False, "schedulerInstalled": False,
                      "aispWrites": 0, "exchangeWrites": 0},
    }
    if existing_public:
        identity = existing_public["successorContentIdentitySha256"]
        receipt_path = Path(existing_public["successorReceiptPath"])
        if (not receipt_path.exists() or physical(receipt_path) != existing_public["successorPhysicalSha256"]
                or json.loads(receipt_path.read_text(encoding="utf-8")).get("contentIdentitySha256") != identity):
            raise RuntimeError("Recorded immutable successor receipt is missing or changed")
    else:
        identity = sha256(canonical_bytes(successor)).hexdigest()
        successor["contentIdentitySha256"] = identity
        receipt_dir = args.private_root / "receipts/sha256" / identity
        receipt_path = receipt_dir / "acquisition-successor.json"
        if receipt_path.exists() and json.loads(receipt_path.read_text(encoding="utf-8")) != successor:
            raise RuntimeError("Immutable successor path already contains different content")
        receipt_dir.mkdir(parents=True, exist_ok=True)
        write_json(receipt_path, successor)

    for name in ("ASSESSMENT.json", "POPULATION_AUDIT.json", "FEATURE_AUDIT.json", "MODEL_RECEIPTS.json"):
        shutil.copyfile(args.output / name, args.docs / name)
    acquisition_public = {
        "schemaVersion": "nba-gen2-acquisition-public-receipt-v1",
        "provider": source["provider"], "underlyingSource": source["underlyingSource"],
        "license": source["license"], "classification": source["classification"],
        "completedAtUtc": source["completedAtUtc"],
        "successfulRequestsCumulative": source["successfulHttpRequests"],
        "successfulRequestsAdditional": 15, "responseBytesCumulative": source["responseBytes"],
        "responseBytesAdditional": source["responseBytes"] - source["requests"][0]["bytes"],
        "costUsd": source["costUsd"], "nbaComRequests": source["nbaComRequests"],
        "sourceReceiptPhysicalSha256": physical(args.private_root / "acquisition-receipt.json"),
        "sourceContentIdentitySha256": source["contentIdentitySha256"],
        "successorReceiptPath": str(receipt_path), "successorContentIdentitySha256": identity,
        "successorPhysicalSha256": physical(receipt_path),
        "privateStudyPath": str(study_dir),
        "retentionReceiptPhysicalSha256": retention_sha,
        "objects": [{key: item[key] for key in ("kind", "seasonEndYear", "sha256", "bytes", "schemaFingerprint")}
                    for item in source["requests"]],
        "historicalVintageQualification": source["historicalVintageQualification"],
    }
    write_json(public_receipt_path, acquisition_public)

    r = assessment["jointResults"]; p = assessment["pairedResults"]
    lines = [
        "# NBA Gen2 team-box acquisition and bounded comparison", "",
        "## Disposition", "", "**GEN1_REMAINS_BASELINE.** The licensed team-box foundation is usable, but neither frozen Gen2 candidate passed the predeclared 2023-24 selection gate. The already staged `NBA_GEN1_PRODUCTION_BASELINE_V1` remains inactive and unchanged. No scheduler or production model was activated.", "",
        "## Acquisition and population", "",
        f"The retained CC BY 4.0 SportsDataverse/hoopR acquisition used {source['successfulHttpRequests']} cumulative successful requests ({15} in the authorized continuation), {source['responseBytes']:,} cumulative bytes, zero retries, zero NBA.com calls and $0. Raw objects remain private outside Git.", "",
        f"The governed population identity is `{assessment['populationAudit']['populationIdentitySha256']}`. It contains {assessment['populationAudit']['games']:,} games: {assessment['populationAudit']['regularSeasonGames']:,} regular-season games, {assessment['populationAudit']['playoffGames']:,} playoffs retained as a separate role, and {assessment['populationAudit']['otherExcludedGames']} other events. The exact common Gen1/Gen2 modeling population contains {assessment['commonPopulation']['rows']:,} games.", "",
        "`total_rebounds` is retained as a separate source statistic. OREB and DREB directly define rebounding features. The source identity differs in 5,459 team rows, concentrated in season end years 2019-21; it becomes equal in later retained seasons. No field was overwritten. Completed schedule periods recover overtime status and team minutes (`240 + 25 × OT`) for every admitted row.", "",
        "One game, ESPN `401704652` (New Orleans at Portland, 2024-10-25), is quarantined before feature history because both team rows fail the scoring identity despite matching schedule finals. Its raw bytes remain unchanged. Fifteen non-franchise exhibition identities were also removed before regular-season modeling.", "",
        "## Frozen comparison", "",
        "Development was 2020-21 through 2022-23, 2023-24 was the frozen selection season, and 2024-25/2025-26 were reused historical stability evidence. Every season was already inspected in prior Gen1 work, so none is called untouched. Models used only earlier-season fitting games; features used only earlier dates and emitted all same-date targets before any update.", "",
        "| 2023-24 configuration | Games | Energy | Team score MAE | Margin CRPS | Total CRPS | Winner LL | Brier |", "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for config in ("GEN1_EXACT_RETAINED", "GEN2_RIDGE_A100_TEAM_BOX_V1", "GEN2_HGB_L2_10_TEAM_BOX_V1"):
        m = r["2024"][config]
        lines.append(f"| {config} | {m['games']:,} | {f(m['jointEnergy'])} | {f(m['teamScoreMae'])} | {f(m['marginCrps'])} | {f(m['totalCrps'])} | {f(m['winnerLogLoss'])} | {f(m['binaryBrier'])} |")
    lines += ["", "### Season stability", "",
              "| Season | Configuration | Energy | Team score MAE | Margin CRPS | Total CRPS | Winner LL |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for season in (2022, 2023, 2024, 2025, 2026):
        for config in ("GEN1_EXACT_RETAINED", "GEN2_RIDGE_A100_TEAM_BOX_V1", "GEN2_HGB_L2_10_TEAM_BOX_V1"):
            m = r[str(season)][config]
            lines.append(f"| {season - 1}-{str(season)[-2:]} | {config} | {f(m['jointEnergy'])} | {f(m['teamScoreMae'])} | {f(m['marginCrps'])} | {f(m['totalCrps'])} | {f(m['winnerLogLoss'])} |")
    ridge = p["2024:GEN2_RIDGE_A100_TEAM_BOX_V1"]["jointEnergy"]
    hgb = p["2024:GEN2_HGB_L2_10_TEAM_BOX_V1"]["jointEnergy"]
    lines += ["", f"Ridge-minus-Gen1 energy was {ridge['difference']:+.4f} (calendar-week 95% interval {ridge['interval95'][0]:+.4f} to {ridge['interval95'][1]:+.4f}). HGB-minus-Gen1 was {hgb['difference']:+.4f} ({hgb['interval95'][0]:+.4f} to {hgb['interval95'][1]:+.4f}). Ridge improved total CRPS slightly but worsened margin CRPS and did not improve team-score MAE. HGB materially worsened the primary metric.", "",
              "Ridge showed better energy and total accuracy in reused 2024-25 and 2025-26 evidence, but that later evidence is diagnostic and cannot satisfy the failed frozen 2023-24 gate. No ensemble was evaluated because neither standalone candidate passed.", "",
              f"On 2023-24, home-win calibration intercept/slope/ECE were {r['2024']['GEN1_EXACT_RETAINED']['calibration']['intercept']:.3f}/{r['2024']['GEN1_EXACT_RETAINED']['calibration']['slope']:.3f}/{r['2024']['GEN1_EXACT_RETAINED']['calibration']['expectedCalibrationError10Bins']:.3f} for Gen1, {r['2024']['GEN2_RIDGE_A100_TEAM_BOX_V1']['calibration']['intercept']:.3f}/{r['2024']['GEN2_RIDGE_A100_TEAM_BOX_V1']['calibration']['slope']:.3f}/{r['2024']['GEN2_RIDGE_A100_TEAM_BOX_V1']['calibration']['expectedCalibrationError10Bins']:.3f} for Ridge Gen2, and {r['2024']['GEN2_HGB_L2_10_TEAM_BOX_V1']['calibration']['intercept']:.3f}/{r['2024']['GEN2_HGB_L2_10_TEAM_BOX_V1']['calibration']['slope']:.3f}/{r['2024']['GEN2_HGB_L2_10_TEAM_BOX_V1']['calibration']['expectedCalibrationError10Bins']:.3f} for HGB. Better HGB bin calibration did not offset worse joint and total scores. Complete 50/80/90% interval coverage and width are retained in `ASSESSMENT.json`.", "",
              "## Overtime sensitivity", "", "Across candidate scoring, 309 observed-overtime games had much larger total CRPS than regulation games. The existing tie-resolution rule activated on about 2.5% of simulated draws and added roughly 0.30 points per team on average. This remains a known distribution limitation; no overtime mechanism was retuned.", "",
              "## Operational outcome", "", "`NBA_GEN1_PRODUCTION_BASELINE_V1` remains the staged production-capable baseline. Its existing exchange handoff and inactive scheduler descriptor remain byte-identical. A 2026-27 prospective team-box capture hook is designed but not installed or activated. Separate authorization is still required to activate the existing NBA owner and production pin.", "",
              "## Reproduction", "", "```powershell", "$env:LOKY_MAX_CPU_COUNT='1'", "$env:OMP_NUM_THREADS='1'", "C:\\Users\\james\\asp-model-studio\\.venv\\Scripts\\python.exe scripts/run_nba_gen2_team_box_study.py", "C:\\Users\\james\\asp-model-studio\\.venv\\Scripts\\python.exe scripts/finalize_nba_gen2_team_box_study.py", "```", "",
              f"Assessment identity: `{assessment['assessmentIdentitySha256']}`. Acquisition successor receipt: `{identity}`.", "",
              f"Private fitted artifacts and complete scoring outputs are retained outside Git at `{study_dir}`; retention receipt physical SHA-256 `{retention_sha}`."]
    (args.docs / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    handoff = f"""# Claude/AISP handoff — NBA production baseline selection

Disposition: `GEN1_REMAINS_BASELINE`.

The new SportsDataverse/hoopR team-box population is valid after one explicit source-integrity quarantine, but neither Gen2 candidate passed the frozen 2023-24 proper-score gate. Do not import or label either Gen2 candidate as production.

Continue to use the already staged inactive handoff:

`C:\\Users\\james\\asp-model-exchange\\nba-production-baseline-v1\\handoffs\\sha256\\4b870c1ff2a4ff537b6533f46019cfc0212bc0e08bd7f7cbe2c6fad9aedf1b5c\\index.json`

Physical SHA-256: `4b870c1ff2a4ff537b6533f46019cfc0212bc0e08bd7f7cbe2c6fad9aedf1b5c`.

This task made zero exchange writes and grants no activation authority. The existing Gen1 package remains staged/inactive. Expected points come from corrected Ridge alpha 100, winner probabilities from Elo as a separately identified output, and joint distributions from the retained Gen1 paired residual model. Historical evidence remains Category A reconstructed finalized records, and the known close-score excess remains disclosed.

Assessment identity: `{assessment['assessmentIdentitySha256']}`.
Population identity: `{assessment['populationAudit']['populationIdentitySha256']}`.
Acquisition successor receipt: `{identity}`.

The exact next activation step remains separate authorization to install the staged single NBA forecast owner and pin AISP to the existing Gen1 handoff. Do not relabel prior forecasts or activate the unselected Gen2 artifacts.
"""
    (args.docs / "CLAUDE_HANDOFF.md").write_text(handoff, encoding="utf-8")
    print(json.dumps({"successorReceipt": str(receipt_path), "successorIdentity": identity,
                      "successorPhysicalSha256": physical(receipt_path),
                      "report": str(args.docs / "REPORT.md")}, indent=2))


if __name__ == "__main__":
    main()
