"""Read-only current-week/seven-day audit of immutable NFL M1 publications.

Reads schedule identity columns and existing forecast objects only. It never
loads an estimator, target columns, a database or a provider. Consumer receipt
arguments must be actual outputs from AISP's import-model-studio-forecast-bundle
command; the report does not run that command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_gold.nfl_shadow_exchange import (
    _validate_nfl_2026_locator,
    verify_sports_forecast_bundle,
)
from server.sports_nfl.publication import verify_parquet_object

OUTPUT = ROOT / "outputs/nfl-m1-publication-audit-20260912"
EXCHANGE = Path(r"C:\Users\james\asp-model-exchange")
MODEL = "NFL_M1_XGBOOST"
VERSION = "NFL_M1_2026_RESEARCH_SHADOW_V1"
BINARY = "7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd"
MANIFEST = "ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9"
FEATURE_CONTRACT = "ef5c4f9ce8c3dd04a473e7ecb2ea3a255154f65a1bb3fda9d2ebc19bf1cb8f4d"
PRIORITY = {"EARLY": 1, "CURRENT": 2, "FINAL_PREGAME": 3}


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Explicit timezone required")
    return parsed.astimezone(timezone.utc)


def reference(path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verified_reference(record: dict) -> dict:
    path = Path(record["path"])
    observed = reference(path)
    if observed["sha256"] != record["sha256"] or observed["bytes"] != record.get("bytes", record.get("byteCount", observed["bytes"])):
        raise ValueError("SUPPLEMENTAL_EVIDENCE_REFERENCE_MISMATCH")
    return read_json(path)


def owner_review(path: Path | None, as_of: datetime) -> dict | None:
    if path is None:
        return None
    record = read_json(path)
    if utc(record["observedAtUtc"]) > as_of:
        raise ValueError("OWNER_EVIDENCE_POSTDATES_AUDIT")
    if record.get("schemaVersion") == "NFL_M1_PUBLICATION_OWNER_REVIEW_SUCCESSOR_V1":
        original = verified_reference(record["previousReview"])
        job = verified_reference(record["producerJobRun"])
        if job["outcomesRead"] != 0 or job["databaseWrites"] != 0:
            raise ValueError("OWNER_EVIDENCE_IS_NOT_READ_ONLY")
        result = {"reference": reference(path), "owner": original["owner"], "existingSchedule": original["existingSchedule"],
                  "latestSubstantiveProducerRun": job, "producerRunReference": record["producerJobRun"],
                  "actualNextScheduledRunAtUtc": record["actualNextScheduledRunAtUtc"],
                  "nextRunEvidence": record["nextRunEvidence"]}
    else:
        raise ValueError("UNSUPPORTED_OWNER_REVIEW_SCHEMA")
    return result


def publication_execution(path: Path | None, as_of: datetime, foundation_sha: str) -> dict | None:
    if path is None:
        return None
    receipt = read_json(path)
    activation = receipt["activation"]
    summary = {"reference": reference(path), "status": activation["status"],
               "publicationLock": activation.get("publicationLock"),
               "reason": activation.get("reason")}
    if activation["status"] != "ACTIVE":
        return summary
    if (activation["sourceFoundationManifestSha256"] != foundation_sha
            or utc(activation["completedAtUtc"]) > as_of
            or activation["modelBinarySha256"] != BINARY or activation["modelManifestSha256"] != MANIFEST
            or activation["modelsFit"] != 0 or activation["modelsPromoted"] != 0):
        raise ValueError("PUBLICATION_EXECUTION_SOURCE_MODEL_OR_CLOCK_MISMATCH")
    lock = activation.get("publicationLock") or {}
    if (lock.get("mode") != "NONBLOCKING_SHARED_PUBLICATION_ROOT"
            or lock.get("liveOwnerAgeExpiry") is not False or not lock.get("ownerPid")):
        raise ValueError("PUBLICATION_EXECUTION_SHARED_LOCK_EVIDENCE_REQUIRED")
    handoff_ref = receipt["handoff"]
    handoff_path = Path(handoff_ref["handoffPath"])
    handoff_reference = reference(handoff_path)
    if handoff_reference["sha256"] != handoff_ref["handoffSha256"]:
        raise ValueError("PUBLICATION_EXECUTION_HANDOFF_CHECKSUM_MISMATCH")
    from server.sports_nfl_m1.rolling_publication import verify_rolling_handoff
    handoff = verify_rolling_handoff(handoff_path)
    if (handoff["source"]["sourceFoundationManifestSha256"] != foundation_sha
            or handoff["newForecastCount"] != activation["forecastsCreated"]
            or handoff["unchangedForecastCount"] != activation["unchangedEvidenceForecastsReused"]
            or handoff["publicationCompletedAtUtc"] != activation["completedAtUtc"]):
        raise ValueError("PUBLICATION_EXECUTION_HANDOFF_BINDING_MISMATCH")
    return {**summary, "handoff": handoff_reference,
            **{key: activation.get(key) for key in (
                "games", "selectedSlateDates", "selectionMode", "rollingWindowDays", "forecastsCreated",
                "unchangedEvidenceForecastsReused", "forecastInferenceRows", "featureVectorCount",
                "forecastCutoffUtc", "completedAtUtc", "sourceEvidenceAsOfUtc", "sourceFoundationManifestSha256",
                "sourceFoundationChangedSincePreviousSnapshot", "eventPlan")}}


def schedule(evidence: dict, as_of: datetime) -> tuple[list[dict], dict]:
    # The original review locates the governed foundation. Resolve its current
    # pointer so a legitimate later source refresh is reflected without a probe.
    current_path = Path(evidence["scheduleReference"]["foundationCurrent"]["path"])
    foundation = current_path.parent
    current = read_json(current_path)
    if utc(current["updatedAt"]) > as_of:
        raise ValueError("CURRENT_SCHEDULE_POSTDATES_REQUESTED_AS_OF")
    manifest_path = foundation / current["relativeManifestPath"]
    manifest = read_json(manifest_path)
    body = {k: v for k, v in manifest.items() if k not in ("manifestSha256", "datasetVersionId")}
    if hashlib.sha256(canonical_json_bytes(body)).hexdigest() != current["currentManifestSha256"]:
        raise ValueError("FOUNDATION_MANIFEST_IDENTITY_MISMATCH")
    objects = {obj["tableName"]: obj for obj in manifest["objects"]}
    dim = verify_parquet_object(foundation, objects["dim_nfl_game"]["manifestSha256"])
    source = verify_parquet_object(foundation, objects["snapshot_nfl_schedule"]["manifestSha256"])
    columns = ["canonical_game_id", "season", "game_type", "week", "game_date", "gametime",
               "canonical_home_team_id", "canonical_away_team_id", "source_home_team_id", "source_away_team_id",
               "espn_game_id", "old_game_id"]
    rows = pq.read_table(dim["path"], columns=columns, filters=[("season", "=", 2026)]).to_pylist()
    source_columns = ["game_id", "season", "week", "gameday", "gametime", "home_team", "away_team"]
    source_rows = pq.read_table(source["path"], columns=source_columns, filters=[("season", "=", 2026)]).to_pylist()
    keyed = {row["game_id"]: row for row in source_rows}
    if len(keyed) != len(source_rows) or len({r["canonical_game_id"] for r in rows}) != len(rows):
        raise ValueError("DUPLICATE_SCHEDULE_IDENTITIES")
    if set(keyed) != {r["canonical_game_id"] for r in rows}:
        raise ValueError("CANONICAL_AND_SOURCE_SCHEDULE_COVERAGE_DIFFERS")
    events = []
    for row in rows:
        peer = keyed[row["canonical_game_id"]]
        if (row["source_home_team_id"] != peer["home_team"] or row["source_away_team_id"] != peer["away_team"]
                or str(row["game_date"])[:10] != str(peer["gameday"])[:10]
                or row["gametime"] != peer["gametime"] or row["week"] != peer["week"]):
            raise ValueError("SCHEDULE_ORIENTATION_OR_KICKOFF_MISMATCH")
        kickoff = datetime.fromisoformat(f"{str(row['game_date'])[:10]}T{row['gametime']}").replace(
            tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
        events.append({"eventId": row["canonical_game_id"], "sourceEventId": "nflverse:" + row["canonical_game_id"],
                       "espnGameId": row["espn_game_id"], "oldGameId": row["old_game_id"], "week": row["week"],
                       "homeTeamId": row["canonical_home_team_id"], "awayTeamId": row["canonical_away_team_id"],
                       "sourceHomeTeamId": row["source_home_team_id"], "sourceAwayTeamId": row["source_away_team_id"],
                       "kickoffUtc": kickoff.isoformat(), "eventDate": str(row["game_date"])[:10]})
    upcoming = [e for e in events if utc(e["kickoffUtc"]) > as_of]
    if not upcoming:
        raise ValueError("NO_UPCOMING_CURRENT_SEASON_SCHEDULE_COVERAGE")
    week = min(e["week"] for e in upcoming)
    team_games = Counter(team for e in events for team in (e["homeTeamId"], e["awayTeamId"]))
    chosen = [e for e in events if e["week"] == week or as_of <= utc(e["kickoffUtc"]) < as_of + timedelta(days=7)]
    for event in chosen:
        event.update({"isCurrentWeek": event["week"] == week,
                      "inNextSevenDays": as_of <= utc(event["kickoffUtc"]) < as_of + timedelta(days=7),
                      "alreadyStarted": utc(event["kickoffUtc"]) <= as_of})
    return sorted(chosen, key=lambda e: (e["kickoffUtc"], e["eventId"])), {
        "currentWeek": week, "foundationCurrent": reference(current_path), "foundationManifest": reference(manifest_path),
        "foundationManifestSha256": current["currentManifestSha256"],
        "sourceAsOfUtc": current["updatedAt"], "dimManifest": reference(dim["manifestPath"]),
        "sourceScheduleManifest": reference(source["manifestPath"]), "seasonDistinctGames": len(events),
        "teams": len(team_games), "gamesPerTeam": dict(sorted(team_games.items())),
        "structurallyComplete272GameRegularSeason": len(events) == 272 and len(team_games) == 32 and set(team_games.values()) == {17},
        "sourceIdentityOrientationKickoffMismatches": 0,
        "limitation": "Stored governed schedule, without a new provider refresh; changes after source-as-of remain unverified. The partial forward-vintage projection is not the denominator."}


def consumer_receipts(paths: list[Path]) -> tuple[dict, list[dict]]:
    confirmed, references = {}, []
    for path in paths:
        record = read_json(path)
        # These are the actual CLI receipt keys returned after commit/reuse.
        if (not isinstance(record.get("idempotent_reuse"), bool)
                or not isinstance(record.get("forecasts"), int) or not record.get("bundle_id")
                or not record.get("bundle_sha256") or not record.get("slate_date")):
            raise ValueError("UNSUPPORTED_CONSUMER_RECEIPT_USE_ACTUAL_AISP_IMPORT_CLI_OUTPUT")
        ref = reference(path)
        confirmed[record["bundle_sha256"]] = {"record": record, "reference": ref}
        references.append(ref)
    return confirmed, references


def build(*, output_root: Path, as_of: datetime, evidence_path: Path, receipt_paths: list[Path],
          owner_path: Path | None = None, confirmations_path: Path | None = None,
          refresh_path: Path | None = None, publication_path: Path | None = None) -> dict:
    evidence = read_json(evidence_path)
    games, schedule_evidence = schedule(evidence, as_of)
    keys = {e["eventId"] for e in games}
    selected_dates = {e["eventDate"] for e in games}
    index_path = EXCHANGE / "aisp-daily-forecast-bundles/nfl-2026-research-shadow-index.json"
    index_raw = index_path.read_bytes()
    index = _validate_nfl_2026_locator(json.loads(index_raw))
    if canonical_json_bytes(index) != index_raw or (index["modelBinarySha256"], index["modelManifestSha256"], index["featureContractSha256"]) != (BINARY, MANIFEST, FEATURE_CONTRACT):
        raise ValueError("LOCATOR_OR_FROZEN_MODEL_IDENTITY_MISMATCH")
    imports, import_refs = consumer_receipts(receipt_paths)
    operations = owner_review(owner_path, as_of)
    refresh_evidence = None
    if refresh_path is not None:
        refresh = read_json(refresh_path)
        if (refresh.get("contract") != "ASP_NFL_CURRENT_SEASON_SYNC_REPORT_V1"
                or utc(refresh["attemptedAtUtc"]) > as_of):
            raise ValueError("UNSUPPORTED_OR_POSTDATED_SOURCE_REFRESH_RECEIPT")
        refresh_evidence = {"reference": reference(refresh_path), **{name: refresh.get(name) for name in (
            "status", "mode", "attemptedAtUtc", "sourceChanged", "changedFamilies", "resultAuthority")}}
        matches = (refresh.get("resultAuthority", {}).get("foundationManifestSha256")
                   == schedule_evidence["foundationManifestSha256"])
        refresh_evidence["matchesCurrentFoundation"] = matches
        refresh_evidence["freshnessVerified"] = (refresh["status"] in ("COMPLETE", "NO_OP") and matches
            and refresh.get("resultAuthority", {}).get("status") == "VERIFIED")
        if refresh_evidence["freshnessVerified"]:
            schedule_evidence["limitation"] = (
                "The successful governed schedule-refresh receipt matches this foundation. Schedule freshness is verified through its source-as-of; "
                "numerical forecast-input freshness remains separate. The partial forward-vintage projection is not the denominator.")
    studio_publication = publication_execution(publication_path, as_of, schedule_evidence["foundationManifestSha256"])
    confirmations = None
    if confirmations_path is not None:
        confirmations = read_json(confirmations_path)
        if (confirmations.get("schemaVersion") != "NFL_M1_FORECAST_ID_CONSUMER_CONFIRMATIONS_V1"
                or confirmations.get("evidenceType") != "READ_ONLY_DATABASE_FORECAST_ID_AND_BUNDLE_BINDING"
                or confirmations.get("outcomesRead") != 0 or confirmations.get("databaseWrites") != 0
                or utc(confirmations["observedAtUtc"]) > as_of):
            raise ValueError("UNSUPPORTED_OR_POSTDATED_CONSUMER_CONFIRMATIONS")
        import_refs.append(reference(confirmations_path))
    candidates, packages, failures = defaultdict(list), {}, []

    def collect(digests, wanted):
        for digest in digests:
            path = EXCHANGE / "aisp-daily-forecast-bundles/sha256" / digest / "bundle.json"
            try:
                raw = read_json(path)
                if raw.get("slateDate") not in selected_dates or not any(f["eventId"] in wanted for f in raw["forecasts"]):
                    continue
                verified = verify_sports_forecast_bundle(EXCHANGE, digest)
                bundle = verified.record
                packages[digest] = {"bundle": reference(path), "generatedAtUtc": bundle["generatedAtUtc"],
                    "consumerImportFixture": reference(verified.consumer_fixture_path),
                    "validationInstructions": reference(verified.validation_instructions_path),
                    "importWorkingDirectory": r"C:\Users\james\ai-sports-predictor\server",
                    "importInvocation": f'python -m app.cli import-model-studio-forecast-bundle --bundle-dir "{path.parent}"'}
                imported = imports.get(digest)
                if imported and (imported["record"]["forecasts"] != len(bundle["forecasts"])
                                 or imported["record"]["bundle_id"] != bundle["bundleId"]):
                    raise ValueError("CONSUMER_RECEIPT_BUNDLE_IDENTITY_MISMATCH")
                for forecast in bundle["forecasts"]:
                    if forecast["eventId"] in wanted:
                        candidates[forecast["eventId"]].append((forecast, bundle, digest))
            except (OSError, ValueError, RuntimeError) as exc:
                failures.append({"bundleSha256": digest, "failure": str(exc)})

    collect(index["currentBundleSha256s"], keys)
    missing = keys - set(candidates)
    if missing:
        collect(index["historicalBundleSha256s"], missing)
    for game in games:
        valid, rejected = [], []
        for forecast, bundle, digest in candidates[game["eventId"]]:
            engine = forecast["engine"]
            deadline = utc(game["kickoffUtc"]) - (timedelta(minutes=15) if forecast["snapshotType"] == "FINAL_PREGAME" else timedelta())
            identity = (forecast["sourceEventId"] == game["sourceEventId"] and forecast["homeTeam"]["teamId"] == game["homeTeamId"]
                and forecast["awayTeam"]["teamId"] == game["awayTeamId"] and utc(forecast["scheduledStartUtc"]) == utc(game["kickoffUtc"])
                and (engine["engineId"], engine["engineVersion"], engine["modelBinarySha256"], engine["modelManifestSha256"], engine["featureContractSha256"], engine["trainingCutoff"])
                    == (MODEL, VERSION, BINARY, MANIFEST, FEATURE_CONTRACT, "2026-02-08"))
            timing = (utc(forecast["sourceCutoffUtc"]) <= utc(forecast["forecastCutoffUtc"]) <= utc(forecast["availableAsOfUtc"])
                      <= as_of and utc(forecast["availableAsOfUtc"]) < deadline
                      and utc(bundle["generatedAtUtc"]) < deadline and utc(bundle["generatedAtUtc"]) <= as_of)
            if identity and timing and forecast["readiness"]["isReady"]:
                valid.append((forecast, bundle, digest, deadline))
            else:
                rejected.append({"forecastId": forecast["forecastId"], "identityValid": identity, "timingValid": timing,
                                 "ready": forecast["readiness"]["isReady"]})
        game.update({"candidateCount": len(candidates[game["eventId"]]), "validCandidateCount": len(valid),
                     "rejectedCandidates": rejected, "newForecast": False, "consumerImportConfirmed": False})
        if valid:
            forecast, bundle, digest, deadline = max(valid, key=lambda item: (
                PRIORITY[item[0]["snapshotType"]], item[0]["snapshotVersion"], utc(item[0]["availableAsOfUtc"])))
            game.update({"disposition": "VALID_PUBLISHED_REUSED", "forecastId": forecast["forecastId"],
                "snapshotType": forecast["snapshotType"], "snapshotVersion": forecast["snapshotVersion"],
                "sourceCutoffUtc": forecast["sourceCutoffUtc"], "scheduleAsOfUtc": forecast["scheduleAsOfUtc"],
                "forecastCutoffUtc": forecast["forecastCutoffUtc"], "forecastFrozenUtc": forecast["availableAsOfUtc"],
                "bundlePublishedUtc": bundle["generatedAtUtc"], "applicableDeadlineUtc": deadline.isoformat(),
                "bundleSha256": digest, "readinessScore": forecast["readiness"]["score"],
                "missingNumericalFeatures": forecast["features"]["missingFeatureCount"],
                "consumerImportConfirmed": digest in imports,
                "consumerReceipt": imports[digest]["reference"] if digest in imports else None})
        elif game["alreadyStarted"]:
            game.update({"disposition": "MISSED_PREGAME", "reason": "No verified pregame forecast established in the current/historical locator"})
        elif rejected or failures:
            game.update({"disposition": "BLOCKED", "reason": "Published candidate or package verification failed; inspect exact rejections"})
        else:
            game.update({"disposition": "PENDING", "reason": "Upcoming game has no published candidate; producer checkpoint/readiness not established by this read-only audit"})
    if confirmations is not None:
        confirmations_by_id = {row["forecastId"]: row for row in confirmations["games"]}
        if len(confirmations_by_id) != len(confirmations["games"]):
            raise ValueError("DUPLICATE_CONSUMER_FORECAST_CONFIRMATIONS")
        # An unchanged forecast may be reused in a newer package. Confirm its
        # exact original imported child and bundle rather than inventing a new
        # import clock for the newer navigation/package wrapper.
        imported_bundles = {}
        for game in games:
            row = confirmations_by_id.get(game.get("forecastId"))
            if row is None:
                continue
            if (row.get("importConfirmed") is not True or row.get("mismatches") != []
                    or row["canonicalGameId"] != game["eventId"] or row["sourceGameId"] != game["sourceEventId"]
                    or utc(row["kickoffUtc"]) != utc(game["kickoffUtc"])
                    or utc(row["forecastAvailableAtUtc"]) != utc(game["forecastFrozenUtc"])
                    or utc(row["forecastRowCreatedAtUtc"]) > as_of):
                continue
            digest = row["bundleSha256"]
            if digest not in imported_bundles:
                imported_bundles[digest] = verify_sports_forecast_bundle(EXCHANGE, digest).record
            if not any(f["forecastId"] == game["forecastId"] for f in imported_bundles[digest]["forecasts"]):
                raise ValueError("CONSUMER_FORECAST_NOT_IN_BOUND_IMPORTED_BUNDLE")
            game.update({"consumerImportConfirmed": True, "consumerReceipt": reference(confirmations_path),
                         "aispCanonicalGameUuid": row["aispCanonicalGameUuid"],
                         "firstImportedBundleSha256": digest, "firstBundleImportedAtUtc": row["firstBundleImportedAtUtc"],
                         "forecastRowCreatedAtUtc": row["forecastRowCreatedAtUtc"],
                         "importedBeforeKickoff": utc(row["forecastRowCreatedAtUtc"]) < utc(game["kickoffUtc"])})
    if studio_publication and studio_publication["status"] == "ACTIVE":
        actions = {row["eventId"]: row["action"] for row in studio_publication["eventPlan"]}
        for game in games:
            if game.get("forecastId"):
                game["newForecast"] = (actions.get(game["eventId"]) == "PUBLISH_CHANGED_ELIGIBLE_INPUTS"
                    and utc(studio_publication["forecastCutoffUtc"]) <= utc(game["forecastFrozenUtc"])
                    <= utc(studio_publication["completedAtUtc"]))
                if game["newForecast"]:
                    game["disposition"] = "VALID_PUBLISHED_NEW"
    counts = {"distinctGames": len(games), "currentWeekGames": sum(g["isCurrentWeek"] for g in games),
              "nextSevenDaysGames": sum(g["inNextSevenDays"] for g in games),
              "validPublished": sum(g["disposition"].startswith("VALID_PUBLISHED_") for g in games),
              "pending": sum(g["disposition"] == "PENDING" for g in games),
              "blocked": sum(g["disposition"] == "BLOCKED" for g in games),
              "missedPregame": sum(g["disposition"] == "MISSED_PREGAME" for g in games),
              "newForecasts": sum(g["newForecast"] for g in games),
              "reusedForecasts": sum(g["disposition"] == "VALID_PUBLISHED_REUSED" for g in games),
              "consumerImportConfirmed": sum(g["consumerImportConfirmed"] for g in games)}
    report = {"schemaVersion": "NFL_M1_PUBLICATION_AUDIT_V1", "snapshotUtc": as_of.isoformat(),
        "scope": "Current canonical week union next seven days; identity-only schedule projection", "counts": counts,
        "priorScheduleReview": reference(evidence_path), "schedule": schedule_evidence,
        "index": {**reference(index_path), "updatedAtUtc": index["updatedAtUtc"]},
        "model": {"id": MODEL, "version": VERSION, "binarySha256": BINARY, "manifestSha256": MANIFEST,
                  "featureContractSha256": FEATURE_CONTRACT, "trainingCutoff": "2026-02-08"},
        "games": games, "packages": packages, "packageFailures": failures, "consumerReceipts": import_refs,
        "operations": operations,
        "sourceRefresh": refresh_evidence,
        "studioBoundedPublication": studio_publication,
        "limitations": ["Published coverage does not establish current numerical freshness; exact source clocks are retained.",
                        "Consumer import/display/scoring remain unconfirmed without separate actual consumer evidence.",
                        "Producer ownership, next run and input-refresh receipts are supplied separately; this audit does not execute production."],
        "researchShadowOnly": True, "executionAllowedInAISP": False, "wageringAuthority": False,
        "newForecastsProduced": 0, "modelRuns": 0, "providerCalls": 0, "outcomeColumnsRead": [], "aispWrites": 0,
        "code": reference(Path(__file__))}
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "publication-audit.json"
    report_raw = canonical_json_bytes(report)
    report_digest = hashlib.sha256(report_raw).hexdigest()
    saved_report = output_root / "snapshots/sha256" / report_digest / "publication-audit.json"
    saved_report.parent.mkdir(parents=True, exist_ok=True)
    if saved_report.exists() and saved_report.read_bytes() != report_raw:
        raise ValueError("IMMUTABLE_AUDIT_SNAPSHOT_CONFLICT")
    saved_report.write_bytes(report_raw)
    report_path.write_bytes(report_raw)
    lines = [f"NFL M1 publication audit — {as_of.isoformat()}", "",
        f"Week {schedule_evidence['currentWeek']}: {counts['currentWeekGames']} games; next seven days: {counts['nextSevenDaysGames']}; union: {len(games)}.",
        f"Published {counts['validPublished']}; pending {counts['pending']}; blocked {counts['blocked']}; missed {counts['missedPregame']}. New {counts['newForecasts']}; reused {counts['reusedForecasts']}; import-confirmed {counts['consumerImportConfirmed']}.", "",
        "| Game | Kickoff UTC | Publication |", "|---|---|---|"]
    lines += [f"| {g['awayTeamId']} at {g['homeTeamId']} | {g['kickoffUtc']} | {g['disposition']} |" for g in games]
    if operations:
        job = operations["latestSubstantiveProducerRun"]
        lines += ["", f"Producer owner: {operations['owner']['application']}. Latest substantive run `{job['id']}`: {job['status']}, completed {job['completedAtUtc']}; {job['result']['feature_vectors']} input vectors, {job['result']['forecasts_created']} new forecasts. Actual next-run timestamp is {operations['actualNextScheduledRunAtUtc'] or 'not exposed by the inspected owner receipt'}."]
    if refresh_evidence:
        lines += ["", f"Governed source refresh: {refresh_evidence['status']} ({refresh_evidence['mode']}), attempted {refresh_evidence['attemptedAtUtc']}; current foundation freshness verified: {refresh_evidence['freshnessVerified']}. Its receipt is retained separately from the effective forecast source clocks."]
    if studio_publication:
        if studio_publication["status"] == "ACTIVE":
            lines += ["", f"Bounded Studio publication completed {studio_publication['completedAtUtc']}: {studio_publication['games']} supported games, {studio_publication['forecastsCreated']} new forecasts, {studio_publication['unchangedEvidenceForecastsReused']} unchanged forecasts reused, under the shared publication lock. Exact source-check clock and handoff digest are in the JSON receipt."]
        else:
            lines += ["", f"Bounded Studio publication: {studio_publication['status']}; {studio_publication['reason']}."]
    lines += ["", f"Schedule source as of {schedule_evidence['sourceAsOfUtc']}. {schedule_evidence['limitation']}", "",
        "Original source, forecast and publication clocks remain separate. Package paths, hashes, forecast IDs, source identities and Claude's exact import invocations are in the JSON companion. Consumer display/evaluation is unconfirmed.", "",
        f"[Machine-readable audit]({report_path.resolve().as_posix()})", "",
        "Reproduce from Model Studio:", "", "```powershell",
        f'.\\.venv\\Scripts\\python.exe scripts\\report_nfl_m1_publication.py --as-of-utc "{as_of.isoformat()}"'
        + (f' --owner-review "{owner_path}"' if owner_path else '')
        + (f' --consumer-confirmations "{confirmations_path}"' if confirmations_path else ''), "```", ""]
    if refresh_path:
        lines[-3] += f' --source-refresh-receipt "{refresh_path}"'
    if publication_path:
        lines[-3] += f' --publication-execution "{publication_path}"'
    (output_root / "publication-audit.md").write_text("\n".join(lines), encoding="utf-8")
    return {"report": reference(report_path), "immutableReport": reference(saved_report),
            "note": reference(output_root / "publication-audit.md"), "counts": counts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT)
    parser.add_argument("--as-of-utc", type=utc)
    parser.add_argument("--schedule-evidence", type=Path, default=OUTPUT / "schedule-review.json")
    parser.add_argument("--consumer-receipt", type=Path, action="append", default=[], help="Actual AISP import CLI JSON receipt; never a Studio publication receipt")
    parser.add_argument("--owner-review", type=Path, help="Checksummed read-only owner-review successor")
    parser.add_argument("--consumer-confirmations", type=Path, help="Read-only exact forecast-ID and imported-bundle confirmation receipt")
    parser.add_argument("--source-refresh-receipt", type=Path, help="Existing governed current-season sync report; this command never refreshes sources")
    parser.add_argument("--publication-execution", type=Path, help="Completed existing rolling publisher CLI JSON, distinct from the AISP owner receipt")
    args = parser.parse_args()
    print(json.dumps(build(output_root=args.output_root, as_of=args.as_of_utc or datetime.now(timezone.utc),
                           evidence_path=args.schedule_evidence, receipt_paths=args.consumer_receipt,
                           owner_path=args.owner_review, confirmations_path=args.consumer_confirmations,
                           refresh_path=args.source_refresh_receipt, publication_path=args.publication_execution), indent=2))
