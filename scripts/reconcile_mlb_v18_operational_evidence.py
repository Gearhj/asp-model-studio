"""Audit retained September 10 operational evidence without executing V18.

Reads only an explicit allowlist of operational JSON and frozen preprocessing
metadata. Never imports a source loader, estimator, database client or provider.
Generated evidence is content addressed and append only.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "outputs/mlb-v18-current-state-pipeline-v1"
BRIDGE = ROOT / "outputs/mlb-v18-current-slate-v1"
DEST = ROOT / "outputs/mlb-v18-unattended-v1/evidence"
FINAL = "565432444ead71f1f985aea5936b5ea82014fdc0af471b15e8c3a4dde835c5aa"
FIRST = "284d38fda651c32668df4d434cc365f8326ef0d07e16ea3d3961d4a0fe91547b"
REPLAY = "b756e73f56e3467325f83eccc2452220162ea285e553e0d0db44400b1af555b4"
EARLY = "9e293e46269965807925270447c5c628003e33db7d7678aeb69fe9c1f32f341a"
BRIDGE_SHA = "1b15231ac3e29c2756f92325334563386a0ba559ef290f12f682d06a5e175bca"
METADATA = ROOT / ".runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/4171306af87bee46e74d2b5141189a5916382967322592243bf71e9eed9cf684.json"
SCHEDULE_RECEIPT = OLD / "sources/objects/sha256/036bc0dbcb06f001b2460d476742fbe3663540aa25d28bfae9a6882f2ef79a3a.receipt.json"
READS: dict[str, dict] = {}


def utc(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def ref(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def read(path, expected=None):
    path = Path(path).resolve()
    allowed = path.is_relative_to(OLD) or path.is_relative_to(BRIDGE) or path == METADATA
    if not allowed or path.suffix != ".json":
        raise ValueError("Only explicitly scoped operational JSON / frozen metadata allowed")
    actual = ref(path)
    if expected and any(actual[k] != expected[k] for k in ("sha256", "bytes") if k in expected):
        raise ValueError(f"Immutable reference mismatch: {path}")
    READS[str(path)] = actual
    return json.loads(path.read_text(encoding="utf-8"))


def read_ref(reference):
    return read(reference["path"], reference)


def obj(digest, name="complete-run.json", root=OLD):
    path = root / "objects/sha256" / digest / name
    return read(path, {"sha256": digest})


def unique(values):
    return list({json.dumps(v, sort_keys=True): v for v in values}.values())


def clocks(value):
    return {k: value[k] for k in ("sourceIdentity", "source", "observedAt", "availableAsOf", "ingestedAt", "requestStartedAt", "providerPublishedAt", "sha256", "payloadChecksum", "observationId") if k in value}


def verify_clocks(value, cutoff):
    if isinstance(value, dict):
        for key in ("observedAt", "availableAsOf", "ingestedAt"):
            if value.get(key):
                assert utc(value[key]) <= cutoff, (key, value[key], cutoff)
        if value.get("observedAt") and value.get("availableAsOf"):
            assert utc(value["observedAt"]) <= utc(value["availableAsOf"])
        for child in value.values():
            verify_clocks(child, cutoff)
    elif isinstance(value, list):
        for child in value:
            verify_clocks(child, cutoff)


def sources_for(field_report, composition, field, index, annual_authority, evidence):
    sources = []
    for provenance in field_report["provenance"]:
        section = provenance.get("evidenceSection")
        if section == "sourceEvidence.player.annual":
            sources.extend({**clocks(r.get("source", annual_authority)), "sourceSeason": r.get("sourceSeason"),
                            "playerId": r.get("playerId"), "historyStatus": r["status"]}
                           for r in composition["sourceEvidence"]["player"]["annual"]
                           if r["targetIndex"] == index and field.startswith(r["role"] + "_"))
        elif section == "sourceEvidence.player":
            sources.append(clocks(composition["sourceEvidence"]["player"]["source"]))
        elif section == "sourceEvidence.context":
            sources.append(clocks(composition["sourceEvidence"]["context"]["source"]))
            if field.startswith(("batting_", "fielding_")):
                sources.append(clocks(composition["sourceEvidence"]["player"]["source"]))
        else:
            candidates = list(evidence["gameState"]) if isinstance(evidence["gameState"], list) else [evidence["gameState"]]
            for side in evidence["sides"]:
                candidates.extend([side["starter"], side["lineupAuthority"]])
            original = next((c for c in candidates if c.get("observedAt") == provenance.get("observedAt")
                             and c.get("availableAsOf") == provenance.get("availableAsOf")), {})
            sources.append({**clocks(original), **provenance})
    return unique(sources)


def dependency_fields(binding):
    keys = ("feature", "exposureFeature", "playerIdentityFeature")
    fields = {binding[k] for k in keys if isinstance(binding.get(k), str)}
    for key in ("requiredSufficientStatistics", "numeratorComponents", "denominatorComponents", "missingIndicatorFeatures"):
        fields.update(binding.get(key, []))
    return fields


def build():
    final, first, replay, early = (obj(v) for v in (FINAL, FIRST, REPLAY, EARLY))
    bridge = obj(BRIDGE_SHA, "bridge-receipt.json", BRIDGE)
    contract = read_ref(final["fieldContract"])
    metadata = read(METADATA, {"sha256": METADATA.stem})
    registration = read_ref(final["modelRegistration"])
    read_ref(final["acceptedReload"])
    for key in ("paArtifact", "transitionArtifact"):
        actual = ref(registration[key]["path"])
        assert all(actual[k] == registration[key][k] for k in ("sha256", "bytes"))
        READS[actual["path"]] = {**actual, "accessPurpose": "Frozen executable checksum only; no deserialization or inference"}
    source_summaries = {FIRST: read_ref(first["sourceSummary"]), FINAL: read_ref(final["sourceSummary"])}
    handoff = read_ref(final["handoff"])
    read_ref(final["aispImportReceipt"])
    assert contract["sourceOrder"] == metadata["sourceColumns"] and len(contract["fields"]) == 246
    assert metadata["transformationContracts"]["globalImputation"] == "PROHIBITED"
    assert replay["newForecastCount"] == 0 and replay["handoff"] == final["handoff"]
    schedule_receipt = read(SCHEDULE_RECEIPT)
    schedule = read_ref(schedule_receipt["raw"])
    schedule_games = next(g["games"] for g in schedule["dates"] if g["date"] == "2026-09-10")
    early_fields = read_ref(bridge["games"][0]["inputCoverage"])["rows"][0]["coverage"]
    supported33 = {f["field"] for f in early_fields["fields"] if f["supported"]}
    assert len(supported33) == 33
    published, datasets = [], {}
    for record in final["games"]:
        directory = OLD / record["relativePath"]
        manifest = read(directory / "manifest.json")
        children = {r["relativePath"]: read(directory / r["relativePath"], r) for r in manifest["artifacts"]}
        forecast, execution, evidence = (children[n] for n in ("forecast.json", "execution-inputs.json", "pregame-evidence.json"))
        feature = read_ref(execution["featureSnapshot"])
        composition = feature["composition"]
        annual_authority = source_summaries[FINAL if record["newInference"] else FIRST]["annualAuthority"]
        gid = forecast["gameId"]
        assert composition["rows"] == execution["rawTemplates"]
        assert composition["providerInputs"] == execution["providerInputs"]
        assert len(execution["treatedFeatureOrder"]) == 273
        assert utc(forecast["capturedAt"]) <= utc(forecast["forecastCreatedAt"]) < utc(forecast["scheduledStart"])
        verify_clocks(composition, utc(forecast["capturedAt"]))
        verify_clocks(evidence, utc(forecast["capturedAt"]))
        assert not composition["historicalTemplatesBorrowed"] and not composition["genericImputation"]
        rerun_game = next(g for g in replay["games"] if g["gameId"] == gid)
        assert rerun_game["objectSha256"] == record["objectSha256"] and not rerun_game["newInference"]
        population = execution["population"]
        assert len(population["homeRuns"]) == len(population["awayRuns"]) == 5000
        for key, observed in (("homeRuns", sum(population["homeRuns"])/5000),
                              ("awayRuns", sum(population["awayRuns"])/5000)):
            assert abs(observed - forecast["expectations"][key]) < 1e-12
        assert sum(h > a for h, a in zip(population["homeRuns"], population["awayRuns"])) / 5000 == forecast["probabilities"]["homeWin"]
        templates = composition["rows"] + composition["providerInputs"]["homeBullpen"] + composition["providerInputs"]["awayBullpen"]
        # Match field receipts by identity, not by the order of provider collections.
        by_id = {r["canonicalPaId"]: r for r in templates}
        reports = composition["fieldReports"]
        assert len(by_id) == len(reports) == 34
        datasets[gid] = {"composition": composition, "reports": reports, "rows": by_id, "execution": execution,
                         "annualAuthority": annual_authority, "evidence": evidence}
        participants = []
        for side in evidence["sides"]:
            side_rows = [r for r in composition["rows"] if f':{side["side"]}:' in r["canonicalPaId"]]
            lineup = []
            for member in side["lineup"]:
                r = next(r for r in reports if r.get("battingSide") == side["side"] and r.get("battingOrder") == member["batting_order"])
                lineup.append({**member, "canonicalPlayerId": by_id[r["canonicalPaId"]]["batterCanonicalPlayerId"]})
            opposing_rows = [r for r in composition["rows"] if r not in side_rows]
            participants.append({"side": side["side"], "team": side["team"], "orderedLineup": lineup,
                                 "lineupAuthority": side["lineupAuthority"], "starter": {**side["starter"],
                                 "canonicalPlayerId": opposing_rows[0]["pitcherCanonicalPlayerId"]}})
        raw_nulls = Counter(name for row in by_id.values() for name in contract["sourceOrder"] if row[name] is None)
        flags = {name: sorted({row[name] for row in by_id.values() if row[name] is not None})
                 for name in contract["sourceOrder"] if name.endswith("_missing")}
        published.append({"gameId": gid, "sourceGameId": forecast["sourceGameId"], "teams": forecast["teams"],
                          "scheduledFirstPitch": forecast["scheduledStart"], "forecastCreatedAt": forecast["forecastCreatedAt"],
                          "evidenceCutoff": forecast["capturedAt"], "sourceCutoff": forecast["sourceCutoff"],
                          "minutesBeforeScheduledFirstPitch": (utc(forecast["scheduledStart"])-utc(forecast["forecastCreatedAt"])).total_seconds()/60,
                          "originalSourceEvidence": {"history": composition["sourceEvidence"]["player"]["source"],
                              "context": composition["sourceEvidence"]["context"]["source"],
                              "annual": unique([clocks(r.get("source", annual_authority)) for r in composition["sourceEvidence"]["player"]["annual"]]),
                              "roster": composition["sourceEvidence"]["currentRoster"],
                              "identitySupplements": composition["sourceEvidence"].get("currentPlayerIdentitySupplements", [])},
                          "participants": participants, "parentAuthority": forecast["parentAuthority"],
                          "probabilities": forecast["probabilities"], "expectations": forecast["expectations"],
                          "simulation": forecast["simulation"], "monteCarloUncertainty": forecast["monteCarloUncertainty"],
                          "rawTemplateRows": 34, "startingRows": 18, "staffRows": 16, "requiredRawFields": 246,
                          "unsupportedFieldCells": sum(not f["supported"] for r in reports for f in r["fields"]),
                          "rawNullCellCount": sum(raw_nulls.values()), "rawFieldsWithNulls": dict(raw_nulls),
                          "missingIndicatorValues": flags, "knownLimitations": forecast["knownLimitations"],
                          "forecastObject": {"objectId": manifest["objectId"], "objectSha256": manifest["objectSha256"],
                              "manifest": ref(directory / "manifest.json"), "artifacts": manifest["artifacts"]},
                          "actualExecutionFeatureSnapshot": execution["featureSnapshot"],
                          "publicationKey": record["publicationKey"], "replay": rerun_game,
                          "pregameProof": "Retained original evidence clocks <= capture <= actual creation < scheduled first pitch; retained status SCHEDULED. No actual first-pitch outcome payload read for this audit.",
                          "researchAuthority": {k: forecast[k] for k in ("status", "researchShadowOnly", "promotionStatus", "executionAllowedInAISP", "wageringAuthority")}})
    fields = []
    model_columns = metadata["transformationContracts"]["modelFeatureColumns"]
    bindings = metadata["prior"]["outputSchema"]["bindings"]
    for entry in contract["fields"]:
        name, family = entry["field"], entry["sourceFamily"]
        direct = [c for c in model_columns if c["sourceFeature"] == name]
        dependent = {b: [c["feature"] for c in model_columns if c["sourceFeature"] == b]
                     for b, binding in bindings.items() if name in dependency_fields(binding)}
        dependency_slots = sorted({c for columns in dependent.values() for c in columns})
        numeric = bool(direct or dependency_slots) and family != "CANONICAL_IDENTITY_METADATA"
        treatment = entry["v18Transformation"]
        semantic_rule = treatment.get("semanticRule") or {}
        if name in metadata["transformationContracts"]["wave1SourceFeatures"]:
            null_treatment = "Retain raw null; append frozen population/posterior mean, effective N, reliability, posterior standard deviation and history-state predictors. The prior_missing flag authorizes the absent annual domain."
        elif name in metadata["transformationContracts"]["wave2SourceFeatures"]:
            null_treatment = "Replace the existing model slot with the frozen component-posterior mean under the verified missing-prior domain; no new median or fit."
        elif semantic_rule.get("kind") == "COLD_EXPOSURE":
            null_treatment = "Frozen COLD_EXPOSURE maps verified absent annual-prior exposure to 0, preserving prior_missing; this is not an assertion of zero career/current-season PA."
        elif family == "ANNUAL_PLAYER_PRIOR" and not direct:
            null_treatment = "Retain null sufficient statistics in the raw dependency contract; frozen component prior consumes the authorized prior_missing branch. No direct estimator slot or fabricated observation."
        else:
            null_treatment = "Apply only the attached frozen semantic rule/native-missing authorization; no absent raw cells of this field occurred in these two publications."
        per_game = {}
        for gid, data in datasets.items():
            cells = []
            for index, row_report in enumerate(data["reports"]):
                report = next(f for f in row_report["fields"] if f["field"] == name)
                row = data["rows"][row_report["canonicalPaId"]]
                value = row[name]
                actual_treated = None
                if value is None and index < 18:
                    actual_treated = {c: data["execution"]["treatedRows"][index][c]
                                      for c in sorted({d["feature"] for d in direct} | set(dependency_slots))
                                      if c in data["execution"]["treatedRows"][index]}
                cells.append({"templateId": row_report["canonicalPaId"], "value": value,
                              "populated": value is not None, "supported": report["supported"],
                              "treatmentApplied": report["status"],
                              "recordedTreatedOutputsForAbsentStartingRow": actual_treated,
                              "sourceEvidence": sources_for(report, data["composition"], name, index, data["annualAuthority"], data["evidence"])})
            per_game[gid] = {"templateCount": len(cells), "populatedCount": sum(c["populated"] for c in cells),
                             "absentCount": sum(not c["populated"] for c in cells),
                             "unsupportedCount": sum(not c["supported"] for c in cells), "cells": cells}
        refresh = {"ANNUAL_PLAYER_PRIOR": "Current pipeline reloads verified local FD1 prior archive; acquisition of a new annual FD1 release is not automated by this adapter.",
                   "COMPLETED_PA_PITCH_HISTORY": "Automatic after bounded prior-completed-date schedule/Statcast capture and exact player-window/exposure verification; same-date games excluded.",
                   "TEAM_SCHEDULE_VENUE_CONTEXT": "Automatic from current schedule identity, prior completed games and fixed venue/team registry; missing end/duration/workload/temperature remains explicit.",
                   "CURRENT_SCHEDULE_CALENDAR": "Automatic from current event schedule and fixed venue timezone/calendar rules.",
                   "CONFIRMED_PARTICIPANT_HANDEDNESS": "Automatic from current lineup/starter/roster or independently timestamped MLB player identity supplement; unknown hand is rejected.",
                   "SIMULATED_PA_STATE": "Recomputed for each hypothetical plate appearance by the frozen simulator.",
                   "CANONICAL_IDENTITY_METADATA": "Automatic current event/player canonical mapping and hypothetical PA identity; never an observed PA."}[family]
        fields.append({**{k: entry[k] for k in ("order", "field", "definition", "entityGrain", "sourceFamily", "lookbackWindow")},
                       "currentSlateAvailability": "All 34 templates supported in each original Sept10 publication; raw null values remain separately enumerated.",
                       "eventPlayerTeamOrPrior": "PRIOR_BASED_PLAYER" if family == "ANNUAL_PLAYER_PRIOR" else entry["entityGrain"],
                       "transformation": entry["v18Transformation"], "missingValueTreatment": entry["missingValueTreatment"],
                       "actualAbsentTreatment": null_treatment,
                       "frozenMissingTreatment": {"partOfFrozenV18": True, "metadataSha256": METADATA.stem,
                           "semanticRule": entry["v18Transformation"]["semanticRule"],
                           "nativeMissingWhenAuthorized": entry["v18Transformation"]["nativeMissingWhenAuthorized"],
                           "priorMethod": entry["v18Transformation"]["priorMethod"], "genericMedian": False},
                       "numericalRole": {"affectsProbabilityMeansThroughEstimatorInputs": numeric,
                           "directModelColumns": direct, "priorDependencyModelColumns": dependent,
                           "uncertaintyOnly": False, "simulationOnly": False,
                           "dynamicSimulationStateAlsoAffectsProbabilityMeans": family == "SIMULATED_PA_STATE",
                           "metadataOrEligibilityOnly": family == "CANONICAL_IDENTITY_METADATA",
                           "effectSizeMeasured": False,
                           "interpretation": "Selected posterior uncertainty/exposure columns are HGB predictors and may change probability means; no raw field is an uncertainty-only control. Slot/dependency membership establishes a possible numerical path, not a measured nonzero effect."},
                       "automaticRefresh": {"existingSourceCanBeRecomputedAutomatically": True,
                           "newAnnualSourceAcquisitionImplemented": False if family == "ANNUAL_PLAYER_PRIOR" else None,
                           "description": refresh}, "supportedInOriginal33Bridge": name in supported33, "perGame": per_game})
    full_slate = []
    early_by_game = {g["gameId"]: g for g in early["games"]}
    for bridge_game in bridge["games"]:
        gid = bridge_game["gameId"]
        teams = {t["side"]: t for t in bridge_game["teams"]}
        source = next(g for g in schedule_games if g["teams"]["away"]["team"]["name"] == teams["AWAY"]["name"] and g["teams"]["home"]["team"]["name"] == teams["HOME"]["name"])
        pub = next((p for p in published if p["gameId"] == gid), None)
        assert utc(bridge["checkedAtUtc"]) < utc(bridge_game["scheduledStartUtc"])
        full_slate.append({"gameId": gid, "sourceGameId": source["gamePk"], "matchup": teams["AWAY"]["abbreviation"] + "–" + teams["HOME"]["abbreviation"],
                           "scheduledFirstPitch": source["gameDate"], "status": "Published before first pitch" if pub else "Explicitly skipped before first pitch",
                           "firstBlockingReason": None if pub else bridge_game["skipReasons"][0],
                           "originalPregameSkipReasons": bridge_game["skipReasons"],
                           "initialDiscoveryCutoff": bridge["sourceCapturedAtUtc"], "skipReceiptCreatedAt": bridge["checkedAtUtc"],
                           "startedByOperationalSourceAvailability": utc(source["gameDate"]) < utc("2026-09-10T21:07:30.438839Z"),
                           "laterCurrentStateBlockers": early_by_game.get(gid, {}).get("blockers", []),
                           "publicationObjectSha256": pub["forecastObject"]["objectSha256"] if pub else None,
                           "continuingIssue": None if pub else "Original missing current-input pipeline was repaired after this game's cutoff. Preserve skip; do not backfill a forecast.",
                           "originalEvidence": bridge_game["sourceEvidence"], "originalInputCoverage": bridge_game["inputCoverage"]})
    assert len(full_slate) == len(schedule_games) == 5
    result = {"schemaVersion": "MLB_V18_SEPT10_OPERATIONAL_EVIDENCE_AUDIT_V1", "auditDate": "2026-09-10",
              "readScope": "Retained operational JSON, original current feature templates and frozen preprocessing metadata; no source/history payload loader, estimator execution, network or AISP writes.",
              "sourceCalls": 0, "sourceCostsUsd": 0, "fits": 0, "inference": 0, "finalOotPayloadReads": 0, "aispWrites": 0,
              "fullSlate": full_slate, "slateCounts": dict(Counter(g["status"] for g in full_slate)),
              "scheduledSlateIdentityReceipt": {**ref(SCHEDULE_RECEIPT), "originalClocks": clocks(schedule_receipt)},
              "publishedGames": published, "modelRegistration": registration, "fieldCount": len(fields),
              "sourceFamilyCounts": contract["sourceFamilyCounts"], "fields": fields,
              "coverageEvolution": {"originalBridge": ref(BRIDGE / "objects/sha256" / BRIDGE_SHA / "bridge-receipt.json"),
                  "originalRawSupported": 33, "originalRawAbsent": 213,
                  "addedFieldsByFamily": dict(Counter(f["sourceFamily"] for f in fields if not f["supportedInOriginal33Bridge"])),
                  "intermediateHOUCoverage": next(g["coverage"] for g in early["games"] if g["gameId"] == "8a0a0c75-60fc-478c-ba5d-5502ba52d2d2"),
                  "finalSupportedPerTemplate": 246,
                  "repair": "Player annual priors and sufficient statistics; exact current last100 PA / last250 BF windows and accepted-history exposure; complete schedule/rest/travel calculations; active pitching-staff source templates; prospective frozen transform seam; current missing-hand supplement. No historical player template or generic median substitution."},
              "exactRerun": {"receipt": ref(OLD / "objects/sha256" / REPLAY / "complete-run.json"),
                  "completedAt": replay["completedAt"], "newForecastCount": replay["newForecastCount"],
                  "sameHandoff": replay["handoff"] == final["handoff"], "gameCompositionReuse": replay["gameCompositionReuse"]},
              "handoff": final["handoff"], "handoffContent": handoff,
              "semanticLimits": ["PROBABLE starter observations; current ordered lineups CONFIRMED.",
                  "Active nonstarter staff pool does not establish individual bullpen availability. Starter rest/workload fields in participant evidence are null.",
                  "Raw recent_bullpen_workload_missing and pregame_temperature_missing indicators do not constitute numeric workload or temperature measurements.",
                  "Annual priors are latest eligible historical FD1 season, not an updated 2026 annual skill estimate.",
                  "Frozen TRUE_COLD_START annual-prior labels mean NO_ELIGIBLE_FROZEN_FD1_PRIOR here; they must not be interpreted as no career history or no current rolling PA evidence.",
                  "Previous-game end and duration are missing; rest calculations use available start-to-start schedule intervals. No end-to-start recovery is claimed.",
                  "Current operational history may have retrospective acquisition dates, but every original availability and ingestion clock precedes these forecasts. No historical forecast-vintage claim.",
                  "HGB posterior uncertainty columns can affect means; Monte Carlo standard error is computed from sample count and win probability, not a raw-feature uncertainty multiplier.",
                  "Full-day denominator was 5, although final future-only run receipt reports 2. TB–ATL already had an earlier explicit pregame skip."]}
    result["verifiedInputReferences"] = sorted(READS.values(), key=lambda r: r["path"])
    blob = (json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(blob).hexdigest()
    path = DEST / "sha256" / digest / "sept10-operational-evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == blob
    else:
        with path.open("xb") as stream:
            stream.write(blob)
    return {"artifact": ref(path), "slateCounts": result["slateCounts"],
            "fieldCount": len(fields), "newFields": result["coverageEvolution"]["addedFieldsByFamily"],
            "games": [{"gameId": p["gameId"], "rawNullCellCount": p["rawNullCellCount"],
                       "rawFieldsWithNulls": p["rawFieldsWithNulls"], "probabilities": p["probabilities"],
                       "expectations": p["expectations"], "createdAt": p["forecastCreatedAt"]} for p in published]}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
