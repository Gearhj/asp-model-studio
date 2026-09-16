"""Verify and summarize the bounded NFL M1 current-season publication update."""
from __future__ import annotations
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_nfl_m1.current_shadow import _forecast_summary
from server.sports_gold.nfl_shadow_exchange import verify_sports_forecast_bundle

OUT = ROOT / "outputs/nfl-m1-current-season-update-v1"
EXCHANGE = Path("C:/Users/james/asp-model-exchange")
STAGING = Path("C:/Users/james/asp-data-staging/nfl")


def read(path):
    return json.loads(Path(path).read_bytes())


def ref(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "byteCount": len(raw)}


def forecast(entry):
    verified = verify_sports_forecast_bundle(EXCHANGE, entry["bundleSha256"])
    record = next(f for f in verified.record["forecasts"] if f["forecastId"] == entry["forecastId"])
    vector_path = STAGING / "m1-prospective-shadow-v1/feature-vectors/sha256" / entry["featureVectorSha256"] / "feature-vector.json"
    assert ref(vector_path)["sha256"] == entry["featureVectorSha256"]
    vector = read(vector_path)
    summary = _forecast_summary(record)
    summary["bundle"] = ref(EXCHANGE / "aisp-daily-forecast-bundles/sha256" / entry["bundleSha256"] / "bundle.json")
    summary["featureVector"] = ref(vector_path)
    summary["producerRevision"] = record["engine"]["producerRevision"]
    summary["sourceFoundationManifestSha256"] = vector["sourceFoundationManifestSha256"]
    return summary, dict(zip(vector["featureNames"], vector["values"], strict=True))


def main():
    before, after = read(OUT / "inputs-before.json"), read(OUT / "inputs-after.json")
    execution = read(OUT / "publication-recovery-execution.json")
    activation = execution["activation"]
    current = read(STAGING / "m1-prospective-shadow-v1/prospective-index.json")
    prior = before["pointers"]["prospective"]["value"]
    # Every previously indexed immutable forecast entry must remain identical.
    preserved = 0
    for game, snapshots in prior["events"].items():
        for snapshot, entries in snapshots.items():
            assert current["events"][game][snapshot][:len(entries)] == entries, (game, snapshot)
            preserved += len(entries)
    for key in ("modelManifestSha256", "modelBinarySha256"):
        assert before[key] == after[key] == activation[key]
    assert activation["modelsFit"] == activation["modelsPromoted"] == 0
    before_targets = {r["canonicalGameId"]: r for r in before["targets"]}
    after_targets = {r["canonicalGameId"]: r for r in after["targets"]}
    assert set(before_targets) == set(after_targets)
    feature_changes = []
    for game, a in after_targets.items():
        b = before_targets[game]
        changes = [{"feature": key, "before": b["features"][key], "after": value}
                   for key, value in a["features"].items() if b["features"][key] != value]
        feature_changes.append({"game": game, "changedFeatureCount": len(changes), "changes": changes})
    comparisons = []
    published_ids = {f for bundle in activation["bundles"] for f in bundle["forecastIds"]}
    for row in activation["eventPlan"]:
        if row["action"] != "PUBLISH_CHANGED_ELIGIBLE_INPUTS":
            continue
        game = row["eventId"]
        old = prior["events"][game]["CURRENT"][-1]
        new = next(e for e in current["events"][game]["CURRENT"] if e["forecastId"] in published_ids)
        assert old["forecastId"] != new["forecastId"]
        bs, bv = forecast(old)
        ns, nv = forecast(new)
        assert bv == before_targets[game]["features"]
        assert nv == after_targets[game]["features"]
        assert datetime.fromisoformat(ns["forecastCreatedUtc"].replace("Z", "+00:00")) < datetime.fromisoformat(ns["kickoffUtc"].replace("Z", "+00:00"))
        kickoff = datetime.fromisoformat(ns["kickoffUtc"].replace("Z", "+00:00"))
        assert datetime.fromisoformat(activation["recovery"]["indexPhysicalLastWriteUtc"]) < kickoff
        assert datetime.fromisoformat(activation["recovery"]["recoveredAtUtc"]) < kickoff
        changes = [{"feature": k, "before": bv[k], "after": nv[k]} for k in bv if bv[k] != nv[k]]
        assert changes
        comparisons.append({"game": game, "before": bs, "after": ns, "changedFeatureCount": len(changes), "changes": changes})
    intake = read(OUT / "source-intake.json")
    old_bronze = read(STAGING / "bronze-v1" / before["pointers"]["bronze"]["value"]["manifestRelativePath"])
    new_bronze = read(STAGING / "bronze-v1/manifests/sha256" / intake["manifestSha256"] / "manifest.json")
    added = {(x["familyId"], x["season"]) for x in intake["currentCorePartitions"]}
    assert [x for x in new_bronze["partitions"] if (x["familyId"], x["season"]) not in added] == old_bronze["partitions"]
    ledger = intake["usage"]
    record = {
        "contract": "NFL_M1_CURRENT_SEASON_UPDATE_RESULT_V1",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "implementationRevision": activation["producerRevision"],
        "inputSnapshots": {"before": ref(OUT / "inputs-before.json"), "after": ref(OUT / "inputs-after.json")},
        "sourceIntake": ref(OUT / "source-intake.json"),
        "foundationBuild": ref(OUT / "foundation-build.json"),
        "numericalFreshness": {"before": before["latestCompletedDateByNumericalMetric"], "after": after["latestCompletedDateByNumericalMetric"]},
        "repairFeatureChanges": feature_changes,
        "futureForecastComparisons": comparisons,
        "deterministicMeanChange": {"receipt": ref(OUT / "verification/deterministic-mean-change.json"), "result": read(OUT / "verification/deterministic-mean-change.json")},
        "publication": {
            "eligibleGames": activation["games"], "newForecastsProduced": activation["forecastsCreated"],
            "newForecastsPublished": sum(b["forecastCount"] for b in activation["bundles"]),
            "unchangedForecastsReused": activation["unchangedEvidenceForecastsReused"],
            "alreadyStartedExcluded": activation["alreadyStartedEvents"],
            "generatedAtUtc": activation["forecastCutoffUtc"], "completedAtUtc": activation["completedAtUtc"],
            "completedAtMeaning": "ORIGINAL_NUMERICAL_RUN_CLOCK_BEFORE_INDEX_WRITE",
            "physicalIndexWrittenAtUtc": activation["recovery"]["indexPhysicalLastWriteUtc"],
            "publicationObservedByUtc": activation["recovery"]["recoveredAtUtc"],
            "derivativeHandoffCompletedAtUtc": execution["handoffRecovery"]["completedAtUtc"],
            "sourceCutoffUtc": activation["sourceEvidenceAsOfUtc"],
            "handoff": ref(execution["handoff"]["handoffPath"]),
            "exchangeIndexAtVerification": ref(activation["exchangeLocatorPath"]),
            "newBundles": [{**b, "physicalFile": ref(EXCHANGE / "aisp-daily-forecast-bundles/sha256" / b["bundleSha256"] / "bundle.json")} for b in activation["bundles"]],
            "consumerAcknowledgement": "NOT_CLAIMED_WITHOUT_EXACT_NEW_FORECAST_IMPORT_EVIDENCE",
            "publicationReceiptRecovery": activation.get("recovery"),
            "handoffRecovery": execution.get("handoffRecovery"),
        },
        "providerUsage": {
            "metadataRequests": 3, "metadataBytes": 1889129,
            "assetRequests": ledger["assetRequests"], "assetBytes": ledger["downloadedBytes"],
            "cumulativeRequests": 3 + ledger["assetRequests"], "cumulativeBytes": 1889129 + ledger["downloadedBytes"],
            "knownCostUsd": ledger["providerCostUsd"],
            "remainingBoundedAssetRequests": ledger["maxAssetRequests"] - ledger["assetRequests"],
            "remainingBoundedAssetBytes": ledger["maxDownloadedBytes"] - ledger["downloadedBytes"],
        },
        "verification": {
            "priorIndexedForecastEntriesPreserved": preserved,
            "all326PriorSourcePartitionsUnchanged": True,
            "originalComparedForecastBundlesAndVectorsChecksumVerified": True,
            "publishedVectorsEqualMeasuredAfterVectors": True,
            "modelAndFittedPreprocessingUnchanged": True,
            "unchangedGoldFeatureContractSha256": activation["featureContractSha256"],
            "unchangedResidualAuthoritySha256": activation["residualAuthoritySha256"],
            "publisherRequiredReloadAndHistoricalFeatureParity": {"reloadFixtureReproduced": activation["reloadFixtureReproduced"], "historicalParity": activation["historicalParity"]},
            "sourcePolicyFocusedChecks": ref(OUT / "verification/core-coverage-focused.json"),
        },
        "qualifications": [
            "This repairs current input coverage; it is not an accuracy-gain claim or a change to fitted components.",
            "The two scored opening games had no completed 2026 prior game at forecast time. This missing later history does not explain their frozen pregame misses.",
            "Published before/after distributions retain their own original 10000-draw residual simulations. Different batch shapes are not certified paired Monte Carlo comparisons.",
            "Weekly player/team statistics are ingested. The frozen 197-feature M1 predictor uses team-game history, not named player or starter features.",
            "The rolling handoff also references the older schedule-only sync receipt. Today's source-intake and Foundation-build receipts above bind the new core evidence; the old sync receipt is not proof of today's ingestion.",
        ],
    }
    raw = (json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    path = OUT / "objects/sha256" / hashlib.sha256(raw).hexdigest() / "update-result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw
    else:
        path.write_bytes(raw)
    pointer = ref(path)
    (OUT / "update-result.json").write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(pointer))
    print(json.dumps({"publication": {k:v for k,v in record["publication"].items() if k in ("eligibleGames", "newForecastsProduced", "newForecastsPublished", "unchangedForecastsReused")}, "comparisons": [{"game":x["game"], "featuresChanged":x["changedFeatureCount"],"before":x["before"],"after":x["after"]} for x in comparisons]}))


if __name__ == "__main__":
    main()
