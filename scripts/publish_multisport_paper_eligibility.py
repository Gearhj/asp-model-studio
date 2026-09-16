"""Publish NBA and CFB eligibility bound to existing prospective baselines."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_shared.paper_research_eligibility import (
    GOVERNANCE,
    KIND,
    SCHEMA,
    canonical_json_bytes,
    immutable_bytes,
    immutable_json,
    physical,
    publish_document,
)


NBA_ADDRESS = "00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d"
CFB_ADDRESS = "72a91840c7f0a88a7248d3a36c9723e4011dd75969859e05d65b7be971ae298f"


def policy(sport: str) -> dict:
    policy_version = f"AISP_{sport}_PAPER_POLICY_V1"
    season = "2026-27" if sport == "NBA" else "2026"
    return {
        "experimentId": f"{policy_version}:{sport}:{season}",
        "experimentIdMeaning": "STABLE_POLICY_SPORT_SEASON_KEY_NOT_AISP_DATABASE_UUID",
        "experimentName": f"ASP {sport} RESEARCH PAPER BANKROLL — 2026 V1",
        "policyVersion": policy_version,
        "mode": "VIRTUAL_RESEARCH_ONLY",
        "consumerVirtualExperimentAuthorized": True,
        "realMoneyAuthorized": False,
        "virtualInitialBankrollUsd": 1000,
        "marketScope": ["MONEYLINE"],
        "kellyFraction": 0.25,
        "positionCapFraction": 0.005,
        "initialPositionCapUsd": 5,
        "sameGameCapFraction": 0.01,
        "dailyCapFraction": 0.02,
        "minimumAdjustedEdgeFraction": 0.02,
        "realMoneyExecutionAllowed": False,
        "wageringOutsideAispAllowed": False,
        "modelPromotionClaim": False,
        "quoteAuthority": "SPORTSGAMEODDS_RESEARCH_QUOTES_ONLY_UNDER_SEPARATE_CONSUMER_POLICY",
        "authorizedBy": "James",
        "authorizationSource": "Current user instruction",
    }


def load_nba(exchange: Path, published_utc: str) -> dict:
    root = exchange / "nba-gen1-research-v1/joint-comparison-v1/packages/sha256" / NBA_ADDRESS
    index_path = root / "index.json"
    forecast_path = root / "forecasts/baseline.json"
    population_path = root / "populations/baseline-joint-draws.parquet"
    publication_path = root / "publication-receipt.json"
    index = json.loads(index_path.read_bytes())
    forecast = json.loads(forecast_path.read_bytes())
    publication = json.loads(publication_path.read_bytes())
    arm = next(item for item in index["arms"] if item["arm"] == "baseline")
    if arm["forecastId"] != forecast["forecastId"] or arm["forecast"]["sha256"] != physical(forecast_path)["sha256"]:
        raise ValueError("NBA published baseline binding differs")
    if arm["population"]["artifact"]["sha256"] != physical(population_path)["sha256"]:
        raise ValueError("NBA published population binding differs")
    joint = forecast["jointSimulation"]
    return {
        "schemaVersion": SCHEMA,
        "artifactVersion": "ASP_NBA_PAPER_RESEARCH_ELIGIBILITY_V1",
        "supplementId": "nba-paper-eligibility:AISP_NBA_PAPER_POLICY_V1:NBA:2026-27:nba-espn:game:401909088:v2",
        "predecessorSupplementAddress": "c587f1adbad5f9f432cd7b5bae4c23230a0cd5796772294857c790658d4a5b8c",
        "kind": KIND,
        "sport": "NBA",
        "governance": GOVERNANCE,
        "binding": {
            "eventId": index["game"]["game_id"],
            "engineId": "NBA_GEN1_JOINT_BASELINE",
            "providerGameId": str(index["game"]["source_game_id"]),
            "forecastId": forecast["forecastId"],
            "modelArtifactSha256": "063e69ffb685a16bd784276fa94bce27f8e2d5e91f744e8c9a60a46f242f70ef",
            "configurationIdentity": forecast["configurationIdentity"],
            "sourcePackageAddress": NBA_ADDRESS,
        },
        "sourceCutoffUtc": forecast["sourceCutoffUtc"],
        "publishedUtc": published_utc,
        "simulation": {"kind": "NONE", "count": 0},
        "summaries": {
            "producerDisposition": "ELIGIBLE_EVIDENCE_FOR_AUTHORIZED_VIRTUAL_RESEARCH_WITH_LIMITATIONS",
            "authorization": policy("NBA"),
            "game": index["game"],
            "originalClocks": {
                "sourceCutoffUtc": forecast["sourceCutoffUtc"],
                "forecastCreatedAtUtc": forecast["createdAtUtc"],
                "originalExchangePublishedAtUtc": publication["publishedAtUtc"],
                "eligibilityPublishedAtUtc": published_utc,
            },
            "frozenForecast": {
                "arm": "baseline",
                "forecastId": forecast["forecastId"],
                "forecastSha256": physical(forecast_path)["sha256"],
                "configurationIdentity": forecast["configurationIdentity"],
                "ridgeExpectedScores": forecast["ridgePointExpectations"],
                "population": {"forecastId": forecast["forecastId"], **arm["population"]},
            },
            "frozenConfiguration": {
                "forecastId": forecast["forecastId"],
                "configurationIdentity": forecast["configurationIdentity"],
                "engineId": "NBA_GEN1_JOINT_BASELINE",
                "modelArtifactSha256": "063e69ffb685a16bd784276fa94bce27f8e2d5e91f744e8c9a60a46f242f70ef",
                "awayWinProbability": joint["winnerProbabilities"]["awayBOS"],
                "homeWinProbability": joint["winnerProbabilities"]["homeDET"],
                "tieProbability": joint["winnerProbabilities"]["tie"],
                "executionAllowed": False,
                "modelPromotionAllowed": False,
                "originalPopulation": {"drawCount": arm["population"]["drawCount"], "artifact": physical(population_path)},
            },
            "probabilityChannels": {
                "controllingChannel": "JOINT_PAIRED_OOF_BASELINE",
                "controllingJoint": {
                    "awayWin": joint["winnerProbabilities"]["awayBOS"],
                    "homeWin": joint["winnerProbabilities"]["homeDET"],
                    "tie": joint["winnerProbabilities"]["tie"],
                },
                "separateElo": forecast["separateEloProbabilities"],
                "ridgeRole": "EXPECTED_POINTS_ONLY; DO_NOT_INFER WIN PROBABILITY",
                "units": "FRACTIONS_0_TO_1",
            },
            "probabilitySemantics": {
                "units": "FRACTION_0_TO_1",
                "controllingChannel": "JOINT_PAIRED_OOF_BASELINE",
                "settlementMustBeExplicit": True,
                "tieMeaning": "NBA_FINALS_HAVE_NO_TIE_OUTCOME",
                "quoteProvidedByProducer": False,
            },
            "unsupported": {
                "wagerMarkets": ["SPREAD", "TOTAL"],
                "displayOnly": ["EXPECTED_SCORES", "TOTAL_DISTRIBUTION", "MARGIN_DISTRIBUTION"],
                "missingInputs": ["PLAYERS", "LINEUPS", "INJURIES", "POSSESSIONS", "TEAM_BOXES"],
                "closeScoreArmControlling": False,
                "profitabilityEstablished": False,
            },
            "consumerContract": {
                "idempotencyKey": ["supplementId", "supplementSha256"],
                "sameBytes": "NO_DUPLICATE",
                "differentBytesSameSupplementId": "REJECT_OR_REQUIRE_EXPLICIT_SUCCESSOR",
                "requiredReceipt": "AISP import + experiment activation receipt with supplement/forecast/game/policy bindings",
                "consumerMustVerifySeparateQuotePolicy": True,
            },
        },
        "producer": {
            "forecastRegenerated": False,
            "modelExecution": False,
            "providerRequests": 0,
            "physicalReferences": [
                physical(index_path), physical(forecast_path), physical(population_path), physical(publication_path)
            ],
        },
    }


def load_cfb(exchange: Path, published_utc: str) -> dict:
    root = exchange / "cfb-gen1-research-v1/current-v1/packages/sha256" / CFB_ADDRESS
    index_path = root / "index.json"
    forecast_path = root / "forecast.json"
    population_path = root / "baseline-joint-draws.parquet"
    publication_path = root / "publication-receipt.json"
    index = json.loads(index_path.read_bytes())
    forecast = json.loads(forecast_path.read_bytes())
    publication = json.loads(publication_path.read_bytes())
    if index["forecastId"] != forecast["forecastId"] or physical(index_path)["sha256"] != CFB_ADDRESS:
        raise ValueError("CFB published forecast/index binding differs")
    baseline = forecast["baseline"]
    return {
        "schemaVersion": SCHEMA,
        "artifactVersion": "ASP_CFB_PAPER_RESEARCH_ELIGIBILITY_V1",
        "supplementId": "cfb-paper-eligibility:AISP_CFB_PAPER_POLICY_V1:CFB:2026:cfbd:401858225:v2",
        "predecessorSupplementAddress": "f24f9a0173ee090f73657beac8caec2c57574b6b8759df1b3cba45a085adf5af",
        "kind": KIND,
        "sport": "CFB",
        "governance": GOVERNANCE,
        "binding": {
            "eventId": "cfbd:401858225",
            "engineId": "CFB_GEN1_JOINT_BASELINE",
            "providerGameId": "401858225",
            "forecastId": forecast["forecastId"],
            "modelArtifactSha256": forecast["modelBindings"]["selectedModel"]["physicalSha256"],
            "configurationIdentity": baseline["configuration"],
            "sourcePackageAddress": CFB_ADDRESS,
        },
        "sourceCutoffUtc": forecast["sourceCutoff"],
        "publishedUtc": published_utc,
        "simulation": {"kind": "NONE", "count": 0},
        "summaries": {
            "producerDisposition": "ELIGIBLE_EVIDENCE_FOR_AUTHORIZED_VIRTUAL_RESEARCH_WITH_LIMITATIONS",
            "authorization": policy("CFB"),
            "game": forecast["game"],
            "originalClocks": {
                "sourceCutoffUtc": forecast["sourceCutoff"],
                "scheduleRevisionCapturedAtUtc": forecast["scheduleRevisionCapturedAt"],
                "forecastCreatedAtUtc": forecast["createdAt"],
                "originalExchangePublishedAtUtc": publication["publishedAtUtc"],
                "eligibilityPublishedAtUtc": published_utc,
            },
            "frozenForecast": {
                "arm": "baseline",
                "forecastId": forecast["forecastId"],
                "forecastSha256": physical(forecast_path)["sha256"],
                "configurationIdentity": baseline["configuration"],
                "expectedScores": {
                    "away": baseline["expectedAwayPoints"], "home": baseline["expectedHomePoints"],
                    "homeMargin": baseline["expectedHomeMargin"], "total": baseline["expectedTotal"],
                },
                "population": {
                    "forecastId": forecast["forecastId"],
                    "drawCount": baseline["drawCount"],
                    "artifact": physical(population_path),
                },
            },
            "frozenConfiguration": {
                "forecastId": forecast["forecastId"],
                "configurationIdentity": baseline["configuration"],
                "engineId": "CFB_GEN1_JOINT_BASELINE",
                "modelArtifactSha256": forecast["modelBindings"]["selectedModel"]["physicalSha256"],
                "awayWinProbability": baseline["jointAwayWinProbability"],
                "homeWinProbability": baseline["jointHomeWinProbability"],
                "tieProbability": baseline["tieProbability"],
                "executionAllowed": False,
                "modelPromotionAllowed": False,
                "originalPopulation": {"drawCount": baseline["drawCount"], "artifact": physical(population_path)},
            },
            "probabilityChannels": {
                "controllingChannel": "JOINT_PAIRED_RESIDUAL_BASELINE",
                "controllingJoint": {
                    "awayWin": baseline["jointAwayWinProbability"],
                    "homeWin": baseline["jointHomeWinProbability"],
                    "tie": baseline["tieProbability"],
                },
                "separateRidge": {"awayWin": baseline["ridgeAwayWinProbability"], "homeWin": baseline["ridgeHomeWinProbability"]},
                "separateElo": {"awayWin": baseline["eloAwayWinProbability"], "homeWin": baseline["eloHomeWinProbability"]},
                "units": "FRACTIONS_0_TO_1",
            },
            "probabilitySemantics": {
                "units": "FRACTION_0_TO_1",
                "controllingChannel": "JOINT_PAIRED_RESIDUAL_BASELINE",
                "settlementMustBeExplicit": True,
                "tieMeaning": "CFB_FINALS_HAVE_NO_TIE_OUTCOME",
                "quoteProvidedByProducer": False,
            },
            "evidenceClassification": {
                "historical": "CATEGORY_A_RECONSTRUCTED_FINAL_RECORDS",
                "target": "ONE_PROSPECTIVE_RESEARCH_FORECAST",
            },
            "unsupported": {
                "wagerMarkets": ["SPREAD", "TOTAL"],
                "missingInputs": ["PLAYERS", "INJURIES", "QUARTERBACKS", "LINEUPS", "WEATHER", "RECRUITING", "TRANSFERS"],
                "openerExtendedGapArmApplied": False,
                "profitabilityEstablished": False,
                "championClaim": False,
            },
            "consumerContract": {
                "idempotencyKey": ["supplementId", "supplementSha256"],
                "sameBytes": "NO_DUPLICATE",
                "differentBytesSameSupplementId": "REJECT_OR_REQUIRE_EXPLICIT_SUCCESSOR",
                "requiredReceipt": "AISP import + experiment activation receipt with supplement/forecast/game/policy bindings",
                "consumerMustVerifySeparateQuotePolicy": True,
            },
        },
        "producer": {
            "forecastRegenerated": False,
            "modelExecution": False,
            "providerRequests": 0,
            "physicalReferences": [
                physical(index_path), physical(forecast_path), physical(population_path), physical(publication_path)
            ],
        },
    }


def handoff(receipt: dict, document: dict) -> str:
    auth = document["summaries"]["authorization"]
    probs = document["summaries"]["probabilityChannels"]
    game = document["summaries"]["game"]
    return "\n".join([
        f"# CLAUDE_HANDOFF — {document['sport']} paper eligibility",
        "",
        f"Artifact: `{document['artifactVersion']}` / `{document['kind']}`.",
        f"Package: `{receipt['exchangeDirectory']}`",
        f"Logical address: `{receipt['supplementAddress']}`.",
        f"Manifest: `{receipt['manifest']['sha256']}` ({receipt['manifest']['bytes']} bytes).",
        f"Supplement: `{receipt['supplement']['sha256']}` ({receipt['supplement']['bytes']} bytes).",
        f"Forecast: `{document['binding']['forecastId']}`; event `{document['binding']['eventId']}`.",
        f"Game: `{game}`.",
        f"Controlling probabilities: `{probs['controllingJoint']}` ({probs['units']}).",
        f"Original clocks: `{document['summaries']['originalClocks']}`.",
        f"Policy: experiment `{auth['experimentId']}`, virtual $1,000, moneyline only, quarter Kelly, 0.5%/$5 initial position cap, 1% same-game cap, 2% daily cap, 2-point minimum adjusted edge; real money false.",
        "Import the generic research supplement idempotently by supplementId + logical address; identical bytes are a no-op and different bytes under the same supplementId require an explicit successor.",
        f"Consumer interface gap: the inspected AISP generic verifier currently hard-codes `ASP_NFL_PAPER_RESEARCH_ELIGIBILITY_V1` and discovers only `nfl-labs-supplements`; register `{document['artifactVersion']}` for sport `{document['sport']}` and import this exact package directory through the same byte/binding checks. The prepared sport policy alone does not perform that import.",
        "Return an AISP receipt binding supplement address, physical supplement hash, forecast ID, event ID, experiment ID, import time, activation state, and display state.",
        "Unsupported: spread/total wagering, profitability or champion claims, and every missing input listed in supplement.json.",
        "",
        "Verification:",
        "```powershell",
        f".\\.venv\\Scripts\\python.exe scripts\\verify_paper_research_eligibility.py '{receipt['exchangeDirectory']}'",
        "```",
        "",
        "Producer publication does not establish consumer import, activation, or display.",
        "",
    ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--published-utc", required=True)
    parser.add_argument("--exchange-root", type=Path, default=Path(r"C:\Users\james\asp-model-exchange"))
    parser.add_argument("--delivery-root", type=Path, default=None,
                        help="Optional destination root; source evidence still comes from --exchange-root")
    parser.add_argument("--output-root", type=Path, default=Path("outputs/multisport-paper-eligibility-20260915-v1"))
    args = parser.parse_args()
    documents = [load_nba(args.exchange_root, args.published_utc), load_cfb(args.exchange_root, args.published_utc)]
    receipts = []
    destination = args.delivery_root or args.exchange_root
    for document in documents:
        family = destination / ("nba-gen1-research-v1" if document["sport"] == "NBA" else "cfb-gen1-research-v1")
        receipt = publish_document(document, exchange_family_root=family, output_root=args.output_root)
        local = args.output_root / document["sport"].lower() / "sha256" / receipt["supplementAddress"]
        handoff_raw = handoff(receipt, document).encode("utf-8")
        local_handoff = local / "CLAUDE_HANDOFF.md"
        receipt["localHandoff"] = immutable_bytes(local_handoff, handoff_raw)
        exchange_handoff = (
            family / "paper-eligibility" / "handoffs" / "sha256"
            / receipt["localHandoff"]["sha256"] / "CLAUDE_HANDOFF.md"
        )
        receipt["exchangeHandoff"] = immutable_bytes(exchange_handoff, handoff_raw)
        immutable_json(local / "delivery-with-handoff.json", receipt)
        receipts.append(receipt)
    summary = {"schemaVersion": "ASP_MULTISPORT_PAPER_ELIGIBILITY_RUN_V1", "receipts": receipts}
    (args.output_root / "run.json").write_bytes(canonical_json_bytes(summary))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
