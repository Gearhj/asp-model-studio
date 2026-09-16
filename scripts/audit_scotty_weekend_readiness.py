"""Read-only, bounded audit of the sealed demo's exact artifacts and owner receipts.

No provider, database, model execution, discovery update or scheduler invocation.
The separate previously captured consumer observation used a READ ONLY transaction.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.scotty_demo_release import (
    NY, checked, clock, now, physical, read, validate_release,
    verify_index_package, write,
)
from server.sports_shared.content_addressed_package import verify_package_directory

REPO = Path(r"C:\Users\james\asp-model-studio")
EXCHANGE = Path(r"C:\Users\james\asp-model-exchange")
STAGING = Path(r"C:\Users\james\asp-data-staging\nfl")
LOCAL = REPO / ".runtime/scotty-weekend-readiness-20260916-v1"
RELEASE = EXCHANGE / "demo-releases-v1/sha256/f0e87d7a48d33566c7b76bb4490503ed25b49bff72e63b9107de3b1580f8889a"
SCHEDULE = REPO / "outputs/mlb-v18-current-state-pipeline-v1/sources/objects/sha256/0133f2e759578aee80e1e2793a8438239c73aed650b32420d658ef4b4ccb04fb.schedule-identities.json"
CONSUMER = LOCAL / "consumer-observation/sha256/f68a9a883c5ff555b14a4a69ef2270da2e4af2b0e6ceb8618c3b5717318b8392/consumer-observation.json"


def bounded_audit():
    references = []

    def bind(path):
        ref = physical(path)
        references.append(ref)
        return ref

    # Code references are snapshots, not immutable publications. Later legitimate
    # source work must not invalidate historical package verification.
    consumer_code = Path(r"C:\Users\james\ai-sports-predictor\server\app")
    code_bindings = [physical(p) for p in [
        consumer_code / "jobs/scheduler.py", consumer_code / "jobs/orchestrator.py",
        consumer_code / "services/mlb_event_bridge.py", consumer_code / "jobs/v18_exchange_consumer.py",
        REPO / "server/sports_nfl_m1/prospective_shadow.py",
        REPO / ".deployments/mlb-v18-unattended/77d39e1ae08e05be82e19bdb0bab21999fba1d3b/server/sports_current_statcast/mlb_v18_unattended.py",
        REPO / "server/sports_current_statcast/mlb_v18_current_publication.py",
        Path(r"C:\Users\james\asp-model-studio-spatial\scripts\publish_nfl_play_level.py"),
    ]]

    sealed = verify_package_directory(RELEASE)
    release = read(RELEASE / "release.json")
    validate_release(release)
    # Check every member now, then again at the end; never touch discovery.
    preserved = [bind(p) for p in RELEASE.rglob("*") if p.is_file()]
    discovery = physical(EXCHANGE / "demo-releases-v1/discovery.json")
    assert discovery["sha256"] == "7977342c8eb87692b81bc253acd95f616bb44b9ab8e9e67ae54394f20c52ddf6"

    schedule_ref = bind(SCHEDULE)
    assert schedule_ref["sha256"] == SCHEDULE.name.split(".")[0]
    weekend = []
    for day in read(SCHEDULE)["dates"]:
        if day["date"] not in ("2026-09-19", "2026-09-20"):
            continue
        for game in day["games"]:
            start = clock(game["gameDate"])
            times = {"start": start, **{f"T{n}": start - timedelta(minutes=n) for n in (60, 45, 30, 15, 5)}}
            weekend.append({
                "slateDateEastern": day["date"], "mlbamGamePk": game["gamePk"],
                "canonicalGameId": None, "away": game["teams"]["away"]["team"],
                "home": game["teams"]["home"]["team"],
                "utc": {k: v.isoformat() for k, v in times.items()},
                "eastern": {k: v.astimezone(NY).isoformat() for k, v in times.items()},
                "disposition": "NOT_YET_DUE_CANONICAL_AND_PARTICIPANT_CAPTURE_PENDING",
            })
    assert len(weekend) == 30 and len({g["mlbamGamePk"] for g in weekend}) == 30
    inventories = []
    for ref in read(LOCAL / "mlb-inventory-references.json"):
        checked({"path": ref["inventoryPath"], "sha256": ref["sha256"], "bytes": Path(ref["inventoryPath"]).stat().st_size})
        item = read(ref["inventoryPath"])
        inventories.append({"receipt": bind(ref["inventoryPath"]),
            "capturedAtUtc": item["capturedAtUtc"], "slateDateEastern": item["slateDateEastern"],
            "scheduledGameCount": item["scheduledGameCount"],
            "currentParticipantCompleteGameCount": item["currentParticipantCompleteGameCount"],
            "latestRosterIngestion": item["rosterRefreshOwner"]["latestIngestionRuns"][0]})
    owner = REPO / ".runtime/mlb-v18-unattended"
    deployment = bind(owner / "deployment.json")
    state = read(owner / "state.json")
    tick_ref = checked(state["latestReceipt"])
    references.append(tick_ref)
    tick = read(tick_ref["path"])
    assert tick["deploymentIdentity"]["commit"] == "77d39e1ae08e05be82e19bdb0bab21999fba1d3b"
    assert tick["owner"] == "windows-task-scheduler" and tick["status"] == "BOUNDED_TICK_COMPLETED"
    assert not (owner / "STOP").exists()
    publication_checks = []
    for slate in tick["slates"]:
        e = slate.get("exchange", {})
        entry = {k: e.get(k) for k in ("packageContentSha256", "packageRoot", "published", "forecastCount", "gameCount", "manifest", "handoff", "receipt")}
        try:
            entry["physicalChecks"] = [checked(e[k]) for k in ("manifest", "handoff", "receipt")]
            references.extend(entry["physicalChecks"])
            entry["physicalCheckStatus"] = "VERIFIED"
        except PermissionError:
            entry["physicalCheckStatus"] = "ACCESS_DENIED_RETAIN_NATURAL_OWNER_RECEIPT_QUALIFICATION"
        publication_checks.append(entry)

    nfl = []
    index = read(STAGING / "m1-prospective-shadow-v1/prospective-index.json")
    for forecast in read(RELEASE / "nfl-week2-audit.json"):
        checked(forecast["package"])
        checked(forecast["eligibility"])
        references.extend([forecast["package"], forecast["eligibility"]])
        latest = max(index["events"][forecast["eventId"]]["CURRENT"], key=lambda x: x["snapshotVersion"])
        assert latest["forecastId"] == forecast["forecastId"], "SUCCESSOR_REQUIRES_EXPLICIT_NEW_AUDIT"
        vector_ref = bind(STAGING / "m1-prospective-shadow-v1/feature-vectors/sha256" / latest["featureVectorSha256"] / "feature-vector.json")
        assert vector_ref["sha256"] == latest["featureVectorSha256"]
        vector = read(vector_ref["path"])
        assert len(vector["featureNames"]) == len(vector["values"]) == 197
        assert not any(word in name.lower() for name in vector["featureNames"] for word in ("quarterback", "injur", "roster", "weather", "wind", "temperature", "qb_"))
        nfl.append({k: forecast[k] for k in ("eventId", "forecastId", "version", "package", "eligibility", "clocks", "engine")})
        nfl[-1].update(featureValuesSha256=latest["featureValuesSha256"],
            featureVector=vector_ref, featureCount=197,
            currentIndexStillMatches=True, personnel="NO_CURRENT_PLAYER_OR_ROSTER_FEATURES",
            injuries="NOT_MODELED", weather="NOT_MODELED_ROOF_AND_SURFACE_ARE_SCHEDULE_FEATURES",
            successorEligibility="NEW_EXACT_FORECAST_REQUIRES_NEW_SUPPLEMENT_EXISTING_PUBLISHER_DOES_THIS")
    assert len(nfl) == 16
    consumer = read(CONSUMER)
    bind(CONSUMER)
    assert consumer["transactionReadOnly"] and consumer["aispWrites"] == 0
    assert consumer["exactForecastRegistrations"]["allPresent"] and consumer["exactSupplementImports"]["allPresent"]
    foundation_pointer = read(STAGING / "foundation-v1/current.json")
    # Immutable manifest metadata only; no Foundation table or outcome payload.
    foundation_ref = bind(STAGING / "foundation-v1" / foundation_pointer["relativeManifestPath"])

    unchanged = []
    for forecast in release["forecasts"]:
        if forecast["sport"] not in ("NBA", "CFB"):
            continue
        checked(forecast["package"])
        _, result = verify_index_package(Path(forecast["package"]["path"]).parent)
        refs = [result["index"], *result["members"]]
        references.extend(refs)
        unchanged.append({"sport": forecast["sport"], "eventId": forecast["eventId"],
            "forecastId": forecast["forecastId"], "clocks": forecast["clocks"], "package": result,
            "discovery": "UNCHANGED_SEALED_DEMO_RELEASE", "paperSupplementCreated": False})

    legacy_pointer = EXCHANGE / "nfl-labs-simulation-supplements/current.json"
    legacy = read(legacy_pointer)
    related = [a for a in legacy["artifacts"] if a.get("artifactSchemaVersion") == "NFL_LABS_SCORE_DISTRIBUTION_V1"]
    optional = {"disposition": "FEASIBILITY_STOP_NO_SIMULATION_EXECUTED", "eventId": "2026_02_IND_KC",
        "kickoffUtc": "2026-09-21T00:20:00+00:00", "kickoffEastern": "2026-09-20T20:20:00-04:00",
        "existingParentDiscovery": physical(legacy_pointer), "availableM1DistributionParents": len(related),
        "matchingWeek2Parents": sum(a.get("eventId") == "2026_02_IND_KC" for a in related),
        "reason": "Verified publisher enforces exactly 16 Week 1 M1 distribution parents; no current IND-KC distribution-supplement parent. Existing CURRENT bundle and paper eligibility are different contracts. No relabeling or forced cohort execution.",
        "nextEngineeringPrerequisite": "Review a one-event adapter binding the exact existing CURRENT M1 population as parent, preserving V2 spatial/geometry validation, before any simulation. No refit inherently required.",
        "modelLimitation": "Independent play engine trained through 2024; no current named personnel, injury or weather model. Does not explain or replace M1."}
    assert optional["matchingWeek2Parents"] == 0
    cfb_paper = []
    for p in sorted((EXCHANGE / "cfb-gen1-research-v1/paper-eligibility/sha256").glob("*/supplement.json")):
        supplement = read(p)
        cfb_paper.append({"reference": bind(p), "binding": supplement.get("forecastBinding", supplement.get("binding"))})
        assert "401869940" not in p.read_text(encoding="utf-8"), "NEW_COASTAL_ELIGIBILITY_REQUIRES_EXPLICIT_AUDIT"
    for ref in preserved + [discovery]:
        checked(ref)
    return {
        "schemaVersion": "ASP_SCOTTY_WEEKEND_READINESS_V1", "observedAtUtc": now(),
        "disposition": "READY_WITH_DISCLOSURES", "release": str(RELEASE),
        "sealedReleaseVerified": True, "sealedMemberCount": len(preserved), "discoveryUnchanged": discovery,
        "mlb": {"deployment": deployment, "tick": tick_ref,
            "naturalOwner": {k: tick[k] for k in ("status", "owner", "deploymentIdentity", "startedAt", "completedAt", "timingContract", "requestTelemetry")},
            "nextExpectedSubstantiveTickUtc": state["nextTickUtc"],
            "scheduledTaskApi": "ACCESS_DENIED_NO_PERMISSION_BYPASS; health inferred from successive natural receipts",
            "stopAbsent": True, "schedule": schedule_ref, "weekendGames": weekend,
            "inputInventories": inventories, "recentPublications": publication_checks,
            "weatherTreatment": "Current V18 publication passes temperature=None; retained weather is not a fresh weather forecast and not a confirmed-participant gate.",
            "consumerImportAcknowledgement": None},
        "nfl": {"forecasts": nfl, "consumerObservation": physical(CONSUMER),
            "forecastImports": consumer["exactForecastRegistrations"], "supplementImports": consumer["exactSupplementImports"],
            "latestJobs": consumer["latestJobs"], "foundationCurrentMetadata": foundation_pointer,
            "foundationManifest": foundation_ref,
            "receiptQualification": "Consumer inspector configuredOwner text says five-minute FINAL generation. Current scheduler code specifies ONE-minute event-gate; import/freeze remain five minutes. Job times and import rows are actual observations.",
            "refresh": "05:30 America/New_York daily CURRENT owner syncs Foundation. Identical eligible 197-feature vectors reuse exact CURRENT. FINAL generation polls each minute in T30..T15; completion required by T21 for six-minute import reserve; no fresh Foundation acquisition on FINAL path. First FINAL can differ in horizon without requiring changed CURRENT vector. Exact existing FINAL is reused.",
            "sundayConclusion": "September 14-15 CURRENT objects may remain correct latest numerical objects if vectors unchanged. New Foundation admitted September 16; daily checks continue. All 14 Sunday games remain structurally blind to current personnel, injuries and weather."},
        "cfbNbaUnchanged": unchanged, "optionalIndKc": optional,
        "existingCfbPaperSupplements": cfb_paper, "codeBindingsAtInspection": code_bindings,
        "immutableEvidenceReferences": references,
        "activity": {"providerCallsInitiated": 0, "externalBytesRequested": 0, "costUsd": 0,
            "aispWrites": 0, "modelRuns": 0, "modelFits": 0, "schedulerChanges": 0,
            "manualOwnerInvocations": 0, "forecastPublicationsByThisTask": 0,
            "sealedOutcomePayloadReads": 0, "productionRepairs": 0},
    }


def verify_report(path):
    report = read(path)
    for reference in report["immutableEvidenceReferences"]:
        checked(reference)
    for game in report["mlb"]["weekendGames"]:
        start = clock(game["utc"]["start"])
        assert start.astimezone(NY).date().isoformat() == game["slateDateEastern"]
        for n in (60, 45, 30, 15, 5):
            assert clock(game["utc"][f"T{n}"]) == start - timedelta(minutes=n)
            assert clock(game["eastern"][f"T{n}"]) == start - timedelta(minutes=n)
    assert clock(report["optionalIndKc"]["kickoffUtc"]) == clock(report["optionalIndKc"]["kickoffEastern"])
    assert len(report["nfl"]["forecasts"]) == 16
    # Discovery/legacy pointers can legitimately change later: compare frozen report
    # separately; immutable packages and receipts remain the verification targets.
    return {"immutableBindingsVerified": len(report["immutableEvidenceReferences"]),
            "report": physical(path)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        result = verify_report(args.verify)
    elif args.output:
        result = write(args.output, bounded_audit())
    else:
        parser.error("--output or --verify is required")
    import json
    print(json.dumps(result, indent=2))
