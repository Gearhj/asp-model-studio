"""Create the review and exchange handoff for the V18 transition component."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.sports_datasets.consumer import canonical_json_bytes

OUT = ROOT / "outputs/mlb-v18-transition-shrinkage-v1"
SLATES = ROOT / "outputs/mlb-v18-current-state-pipeline-v1"
UNATTENDED = ROOT / "outputs/mlb-v18-unattended-v1/objects/sha256"
AISPE = Path(r"C:\Users\james\asp-model-exchange\mlb-v18-simulator-evidence-v1")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha(path), "bytes": path.stat().st_size}


def put(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"Immutable artifact conflict: {path}")
        return
    with path.open("xb") as stream:
        stream.write(raw)


def immutable_copy(path: Path, group: str) -> dict:
    raw = path.read_bytes()
    target = OUT / group / "sha256" / hashlib.sha256(raw).hexdigest() / path.name
    put(target, raw)
    return ref(target)


def latest_tick(logical_handoff_sha: str) -> tuple[dict, Path]:
    matches = []
    for path in UNATTENDED.glob("*/tick.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for slate in payload.get("slates", []):
            if slate.get("handoff", {}).get("logicalHandoffSha256") == logical_handoff_sha:
                matches.append((payload.get("startedAt", ""), payload, path))
    if not matches:
        raise ValueError("No unattended export receipt for the current handoff")
    _, payload, path = max(matches, key=lambda item: item[0])
    return payload, path


def build() -> dict:
    current = json.loads((OUT / "current.json").read_text(encoding="utf-8"))
    result = json.loads(Path(current["result"]["path"]).read_text(encoding="utf-8"))
    pair_pointer = json.loads((OUT / "prospective-pair-current.json").read_text(encoding="utf-8"))
    pair_path = Path(pair_pointer["path"])
    pair = json.loads(pair_path.read_text(encoding="utf-8"))
    consumption_ref = json.loads((OUT / "evidence-consumption-current.json").read_text())
    verification_ref = json.loads((OUT / "delivery-verification-current.json").read_text())
    verification = json.loads(Path(verification_ref["path"]).read_text())
    duration_review = immutable_copy(OUT / "duration-contract-review.json", "review")
    adapter_contract = immutable_copy(OUT / "adapter-contract-v2.md", "contracts")
    supplementary = {"evidenceConsumption": consumption_ref, "deliveryVerification": verification_ref,
                     "durationContractReview": duration_review, "adapterContract": adapter_contract}
    supplementary["focusedVerification"] = json.loads((OUT / "focused-verification-current.json").read_text())
    if (OUT / "adapter-v2/current.json").exists():
        supplementary["adapterEnvelopeIndex"] = immutable_copy(OUT / "adapter-v2/current.json", "adapter-index")
    for key in ("population", "executionReceipt"):
        if key in pair:
            supplementary["prospective" + key[0].upper() + key[1:]] = pair[key]

    locator = json.loads((SLATES / "slates/2026-09-12/latest.json").read_text(encoding="utf-8"))
    receipt_path = SLATES / locator["relativePath"] / "slate-result.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    handoff_path = SLATES / "handoffs/sha256" / receipt["handoffSha256"] / "aisp-handoff.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    tick, tick_path = latest_tick(receipt["handoffSha256"])
    exported = next(row["exchange"] for row in tick["slates"]
                    if row["slateDate"] == "2026-09-12"
                    and row["handoff"]["logicalHandoffSha256"] == receipt["handoffSha256"])

    market_current = json.loads((AISPE / "current.json").read_text(encoding="utf-8"))
    market_path = AISPE / market_current["files"]["market_comparison.json"]["relativePath"]
    market = json.loads(market_path.read_text(encoding="utf-8"))
    imported_ids = {row["forecastId"] for row in market["games"]}
    forecasts = []
    for item in handoff["forecasts"]:
        forecast_path = SLATES / item["relativePath"] / "forecast.json"
        forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
        forecast_id = "mlb-v18-daily-" + item["objectSha256"]
        forecasts.append({
            "forecastId": forecast_id, "objectSha256": item["objectSha256"],
            "canonicalGameId": item["gameId"], "mlbamGamePk": str(forecast["sourceGameId"]),
            "away": forecast["teams"]["AWAY"]["abbreviation"], "home": forecast["teams"]["HOME"]["abbreviation"],
            "scheduledStart": forecast["scheduledStart"], "published": True,
            "consumerImportConfirmed": forecast_id in imported_ids,
        })
    skipped = [row for row in receipt["games"] if row["status"] == "SKIPPED"]
    index = {
        "schemaVersion": "MLB_V18_CURRENT_SLATE_FORECAST_INDEX_V1",
        "slateDate": "2026-09-12", "asOfUtc": tick["startedAt"],
        "produced": len(forecasts), "published": len(forecasts),
        "importConfirmed": sum(row["consumerImportConfirmed"] for row in forecasts),
        "importConfirmationAsOfUtc": market["asOfUtc"],
        "remaining": len(skipped),
        "remainingDispositions": [
            {"canonicalGameId": row["gameId"], "mlbamGamePk": str(row.get("mlbamGamePk") or row.get("localSchedule", {}).get("source_game_id")),
             "status": row["status"], "reason": row.get("reason"), "blockers": row.get("blockers", [])}
            for row in skipped],
        "forecasts": forecasts,
        "studioHandoff": {**ref(handoff_path), "logicalSha256": receipt["handoffSha256"]},
        "studioReceipt": {**ref(receipt_path), "logicalSha256": receipt["receiptSha256"]},
        "exchangePackage": exported,
        "consumerEvidence": {"current": ref(AISPE / "current.json"), "marketComparison": ref(market_path)},
    }
    index_raw = canonical_json_bytes(index)
    index_sha = hashlib.sha256(index_raw).hexdigest()
    index_path = OUT / f"slate/sha256/{index_sha}/forecast-index.json"
    put(index_path, index_raw)

    baseline, change, delta = result["baseline"], result["change"], result["changeMinusBaseline"]
    rows = [
        ("Winner log loss", "winnerLogLoss"), ("Winner Brier", "winnerBrier"),
        ("Home CRPS", "homeCrps"), ("Away CRPS", "awayCrps"),
        ("Total CRPS", "totalCrps"), ("Margin CRPS", "marginCrps"),
    ]
    table = "\n".join(f"| {label} | {baseline[key]:.6f} | {change[key]:.6f} | {delta[key]:+.6f} |"
                      for label, key in rows)
    note = f"""# V18 hierarchical transition shrinkage decision

The transition increment retains exact-state evidence that V18's 20-observation cutoff discards, replacing uniform smoothing with outcome/outs-based shrinkage of fixed strength 20 and a `1e-6` legal floor. PA estimation, fitted preprocessing, eight classes and pitcher usage stay frozen.

Duration is already integrated in the paired runner. Claude's 66 starter observations have null rest/workload/pitch fields; all 38 observations matching 19 forecasts arrived after their source snapshots. Studio's additional certified history covers only the preserved pilot starters. This evidence cannot expand the existing duration contract. Both incoming handoffs and all referenced objects were verified; the 20,870 historical appearance labels were not used as pregame covariates.

## Fixed 16-game historical pregame replay

| Metric (lower is better) | Frozen V18 | Change | Change − baseline |
| --- | ---: | ---: | ---: |
{table}

Included: 16 fixed September 10–11 games, 5,000 draws per arm/game, seed 20260907; 0 fallbacks. One COL–DET pilot is excluded from 17 historical published games. The three quarantine games and sealed August 14–27 window are absent. Baselines have verified prospective source clocks; all changed arms are historical pregame replays. Original arrays and scores are preserved.

Winner and away-run scores improve slightly; home, total and margin CRPS worsen. Mean total changes by {verification['pairedDrawMeanChange']['total']['mean']:+.4f} runs (within-game paired Monte Carlo SE {verification['pairedDrawMeanChange']['total']['pairedMonteCarloStandardError']:.4f}). This measures simulation noise, not uncertainty about predictive improvement.

On 485,522 training transitions, run-conversion MAE changes {result['componentLocalization']['baseline']['runConversionMae']:.6f} → {result['componentLocalization']['change']['runConversionMae']:.6f}; double-play Brier changes {result['componentLocalization']['changeMinusBaseline']['doublePlayOpportunityBrier']:+.6f}. These are training-count reconstructions with no selection authority.

## Decision

**Verdict: insufficient evidence.** Game `{pair['sourceGameId']}` has a new unscored prospective pair frozen at `{pair['pairFrozenAtUtc']}`, before `{pair['policyCutoffUtc']}`, with both arms' draws retained. Home-win probability changes {pair['baseline']['homeWinProbability']:.4f} → {pair['change']['homeWinProbability']:.4f}; mean total changes {pair['baseline']['meanTotalRuns']:.4f} → {pair['change']['meanTotalRuns']:.4f}.

Governed final scores and postgame transitions are needed to assess that pair. Reject the component if the predeclared transition log-loss/Brier, double-play Brier and run-conversion gate fails. That gate remains unassessed; no replacement gate or correction was selected after scores.

The runner now falls back explicitly to authenticated V18 and gates identities before outcome decoding. Focused checks and a 16-revision reconciliation passed. Qualifications remain: uncertified PA training chronology; historical reuse; the original reader's late local pilot check; and the old NYM–NYY pair's missing candidate draws. The verification receipt preserves these limitations.

Claude's adapter needs the packaged V2/`TRANSITION` extension. Import is unconfirmed; candidate authority remains false.

Reproduce the retained game's configuration (automatically labeled replay after kickoff):

```powershell
.\\.venv\\Scripts\\python.exe scripts\\run_mlb_v18_transition_shrinkage_v1.py --forecast-object-sha {pair['sourceForecastObjectSha256']} --simulations 5000 --seed 20260907
```
"""
    note_raw = note.encode("utf-8")
    note_sha = hashlib.sha256(note_raw).hexdigest()
    note_path = OUT / f"notes/sha256/{note_sha}/DECISION.md"
    put(note_path, note_raw)

    code = [ROOT / "server/sports_phase5/hierarchical_transition.py",
            ROOT / "scripts/build_mlb_v18_transition_shrinkage_v1.py",
            ROOT / "scripts/run_mlb_v18_transition_shrinkage_v1.py",
            ROOT / "scripts/freeze_mlb_v18_transition_shadow_v1.py",
            ROOT / "scripts/consume_mlb_v18_simulator_evidence_v1.py",
            ROOT / "scripts/verify_mlb_v18_transition_delivery_v1.py",
            ROOT / "scripts/package_mlb_v18_transition_adapter_v2.py",
            Path(__file__).resolve()]
    exchange_handoff = {
        "schemaVersion": "MLB_V18_TRANSITION_SHRINKAGE_EXCHANGE_HANDOFF_V1",
        "componentId": result["componentId"], "verdict": result["verdict"],
        "result": current["result"], "resultManifest": current["manifest"],
        "population": current["population"], "component": current["component"],
        "protocol": result["protocol"], "prospectivePair": ref(pair_path),
        "forecastIndex": ref(index_path), "decisionNote": ref(note_path),
        "supplementary": supplementary,
        "code": [ref(path) for path in code],
        "runnableCommand": ".\\.venv\\Scripts\\python.exe scripts\\run_mlb_v18_transition_shrinkage_v1.py --forecast-object-sha " + pair["sourceForecastObjectSha256"] + " --simulations 5000 --seed 20260907",
        "fallback": "FROZEN_V18_WHEN_COMPONENT_OR_SUPPORTED_INPUT_EVIDENCE_IS_UNAVAILABLE",
        "contractExtensionRequired": True,
        "consumerImplementationStatus": "PENDING_CLAUDE_V2_TRANSITION_ROLE",
        "transitionImportConfirmed": False,
        "researchShadowOnly": True, "candidateAuthority": False,
        "executionAllowedInAisp": False, "wageringAuthority": False,
        "aispWrites": 0, "officialV18PointersModified": 0,
    }
    handoff_raw = canonical_json_bytes(exchange_handoff)
    handoff_sha = hashlib.sha256(handoff_raw).hexdigest()
    handoff_path_local = OUT / f"handoffs/sha256/{handoff_sha}/aisp-handoff.json"
    put(handoff_path_local, handoff_raw)
    package = {"schemaVersion": "MLB_V18_TRANSITION_SHRINKAGE_PACKAGE_V1",
               "componentId": result["componentId"], "verdict": result["verdict"],
               "handoff": ref(handoff_path_local), "forecastIndex": ref(index_path),
               "decisionNote": ref(note_path), "prospectivePair": ref(pair_path),
               "researchShadowOnly": True, "candidateAuthority": False,
               "executionAllowedInAisp": False, "wageringAuthority": False}
    package_raw = canonical_json_bytes(package)
    package_sha = hashlib.sha256(package_raw).hexdigest()
    package_path = OUT / f"packages/sha256/{package_sha}/package.json"
    put(package_path, package_raw)
    packaged_current = {**current, "package": ref(package_path), "handoff": ref(handoff_path_local),
                        "forecastIndex": ref(index_path), "decisionNote": ref(note_path),
                        "prospectivePair": ref(pair_path)}
    (OUT / "current.json").write_bytes(canonical_json_bytes(packaged_current))
    return packaged_current


if __name__ == "__main__":
    print(json.dumps(build(), indent=2), flush=True)
