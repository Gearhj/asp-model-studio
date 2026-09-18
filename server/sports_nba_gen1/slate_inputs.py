"""Versioned local admission for the frozen NBA score/date model.

No network client. A governed capture receipt is the input, not a filename with
a fresh mtime. Model fitting, numerical definitions and residuals never change.
"""
from __future__ import annotations

from collections import Counter
import copy
import io
import json
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from .authority import reference, verified_bytes
from .current_history_source import _team
from .production import CONFIGURATION, canonical_bytes, digest
from .slate_lifecycle import atomic_json, immutable, now, object_json, owner_lock, read_ref, utc

META = ["id", "game_id", "date", "game_date", "season", "season_type", "type_id",
        "type_abbreviation", "neutral_site", "status_type_name", "status_type_state",
        "status_type_completed", "home_id", "away_id", "home_abbreviation", "away_abbreviation",
        "home_display_name", "away_display_name"]


def classify(frame, source_sha):
    if frame.id.duplicated().any() or not (frame.id == frame.game_id).all():
        raise ValueError("Duplicate/conflicting schedule identity")
    games, finals, contexts, missing = [], [], [], []
    seen_pairs = set()
    for row in frame.sort_values(["date", "id"]).to_dict("records"):
        gid = f"nba-espn:game:{int(row['id'])}"
        result = {"gameId": gid, "sourceGameId": int(row["id"])}
        reason = None
        if int(row["season_type"]) != 2:
            reason = "NOT_REGULAR_SEASON"
        elif int(row["type_id"]) != 1 or row["type_abbreviation"] != "STD":
            reason = "NOT_STANDARD_REGULAR_GAME"
        try:
            h, a = _team(row, "home"), _team(row, "away")
        except ValueError:
            h = a = None
            reason = reason or "UNMAPPED_TEAM"
        if reason:
            result["exclusion"] = reason
            games.append(result)
            if reason == "UNMAPPED_TEAM" and row["status_type_completed"]:
                missing.append(gid)
            # Cup calendar dates matter to the unchanged rest contract; never read Cup scores.
            if row["type_abbreviation"] == "CC" and row["status_type_completed"] and h and a:
                contexts.append({"game_id": gid, "game_date": str(row["game_date"]),
                    "season_end": int(row["season"]), "source_game_id": int(row["id"]),
                    "classification": "NBA_CUP_FINAL_DATE_ONLY",
                    "team_ids": sorted(["nba-neil:franchise:" + h, "nba-neil:franchise:" + a])})
            continue
        tip = utc(row["date"])
        if tip.astimezone(__import__('zoneinfo').ZoneInfo("America/New_York")).date().isoformat() != str(row["game_date"]):
            raise ValueError("Eastern date/original UTC tipoff mismatch")
        if h == a:
            raise ValueError("Same-team schedule")
        scheduled = row["status_type_name"] == "STATUS_SCHEDULED" and row["status_type_state"] == "pre" and not row["status_type_completed"]
        final = row["status_type_name"] == "STATUS_FINAL" and row["status_type_state"] == "post" and bool(row["status_type_completed"])
        target = {"game_id": gid, "source_game_id": int(row["id"]), "season_end": int(row["season"]),
            "game_date": str(row["game_date"]), "home_team_id": "nba-neil:franchise:" + h,
            "away_team_id": "nba-neil:franchise:" + a, "home_team_code": h, "away_team_code": a,
            "neutral_site": bool(row["neutral_site"]), "scheduled_tipoff_utc": tip.isoformat(),
            "season_type": "REGULAR", "status": "SCHEDULED" if scheduled else str(row["status_type_name"]),
            "source_revision": "sha256:" + source_sha}
        if scheduled or final:
            pair = (target["game_date"], *sorted([h, a]))
            if pair in seen_pairs:
                raise ValueError("Duplicate active/final date-team pair; explicit reschedule reconciliation required")
            seen_pairs.add(pair)
        result["target"] = target
        if row["neutral_site"]:
            result["exclusion"] = "NEUTRAL_HISTORY_ONLY"
        games.append(result)
        if final:
            finals.append(target)
        elif row["status_type_completed"]:
            missing.append(gid)
    return games, finals, contexts, missing


def admit(*, capture_ref, base_model_ref, base_coverage_ref, rights_refs, registry_root,
          season_end, reviewed_by, precommit=None):
    """Normalize a complete season snapshot and publish an append-only input version.

    Capture must be supplied by the authorized source owner. This command cannot
    manufacture a capture clock or extend an old membership certificate to now.
    Current-season finals are selected by metadata before reading their scores.
    """
    if not reviewed_by or season_end < 2027:
        raise ValueError("Named review and prospective 2027+ source required")
    registry = Path(registry_root)
    with owner_lock(registry / "admission.lock"):
        capture = read_ref(capture_ref)
        if capture.get("schema") not in ("nba-gen1-genuine-future-schedule-capture-v1", "NBA_GOVERNED_SCHEDULE_CAPTURE_V1", "NBA_CONDITIONAL_SCHEDULE_CAPTURE_V1"):
            raise ValueError("Unsupported capture receipt")
        source = capture["source"]
        source_raw = verified_bytes(source)
        original_capture = capture["capturedAtUtc"]
        stamp = capture.get("validatedAtUtc", original_capture)
        if (utc(stamp) > utc(now()) or utc(original_capture) > utc(stamp)
                or capture.get("httpStatus") not in (200, 304)):
            raise ValueError("Capture clock/status invalid")
        if capture.get("httpStatus") == 304:
            prior = read_ref(capture["priorObjectReceipt"])
            if prior["source"] != source or prior["capturedAtUtc"] != original_capture or not capture.get("conditionalHeadersSent"):
                raise ValueError("304 must bind an unchanged prior object and real conditional request")
        if not rights_refs:
            raise ValueError("Applicable retained source rights required")
        for ref in rights_refs:
            verified_bytes(ref)
        frame = pd.read_parquet(io.BytesIO(source_raw), columns=META)
        if set(frame.season.astype(int)) != {season_end}:
            raise ValueError("Source season mismatch")
        games, finals, contexts, missing = classify(frame, source["sha256"])
        if any(utc(t["scheduled_tipoff_utc"]) >= utc(stamp) for t in finals):
            raise ValueError("A source FINAL precedes its scheduled start/capture chronology")
        # A stale scheduled/in-progress record whose start has elapsed cannot
        # certify current membership; cancelled/postponed rows are explicit exclusions.
        for row in games:
            t = row.get("target")
            if t and utc(t["scheduled_tipoff_utc"]) <= utc(stamp) and t["status"] not in (
                "STATUS_FINAL", "STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_POSTPONED"):
                missing.append(row["gameId"])
        if missing:
            # In-progress/stale status is not a partial usable update. Keep the
            # admitted pointer unchanged until a complete snapshot is available.
            raise ValueError("SOURCE_FINAL_PENDING:" + ",".join(sorted(set(missing))))
        base = read_ref(base_model_ref)
        coverage = read_ref(base_coverage_ref)
        if base["configurationIdentity"] != CONFIGURATION or coverage["currentResearchReceiptSha256"] != base_model_ref["sha256"]:
            raise ValueError("Wrong frozen model/base coverage")
        if coverage["regularSeasonMembershipComplete"] is not True or coverage["missingGameIds"]:
            raise ValueError("Base historical membership is incomplete")
        if utc(coverage["completeThroughUtc"]) > utc(stamp):
            raise ValueError("New capture predates admitted base")
        for ref in coverage["evidence"]:
            verified_bytes(ref)
        history = pd.read_parquet(io.BytesIO(verified_bytes(base["history"]["games"])))
        if history.game_id.duplicated().any():
            raise ValueError("Duplicate base history identity")
        context = read_ref(base["history"]["contextMetadata"])
        if int(history.season_end.max()) != season_end - 1:
            raise ValueError("Base must cover previous completed season; no silent missing season")
        # Frozen base is never refitted. Add/correct this season's rows from this
        # exact version, so removed/corrected finals cannot persist invisibly.
        records = []
        if finals:
            ids = [t["source_game_id"] for t in finals]
            scores = ds.dataset(source["path"], format="parquet").to_table(
                columns=["id", "home_score", "away_score"], filter=ds.field("id").isin(ids)).to_pandas().set_index("id")
            if len(scores) != len(ids) or not scores.index.is_unique:
                raise ValueError("Final identities do not reconcile")
            for target in finals:
                row = {k: v for k, v in target.items() if k not in ("scheduled_tipoff_utc", "source_revision", "status", "season_type")}
                for side in ("home", "away"):
                    val = float(scores.loc[target["source_game_id"], side + "_score"])
                    if not pd.notna(val) or val < 0 or not val.is_integer():
                        raise ValueError("Invalid complete final score")
                    row[side + "_score"] = int(val)
                if row["home_score"] == row["away_score"]:
                    raise ValueError("Tied NBA final")
                row.update(orientation="PUBLISHER_FOCAL_AXIS_NO_HOME_CLAIM" if row["neutral_site"] else "SOURCE_HOME_AWAY",
                    target_eligible=not row["neutral_site"], competition="NBA_REGULAR_SEASON",
                    evidence_class="A_FINALIZED_RECORDS_CAPTURED_BEFORE_FUTURE_TARGET",
                    record_classification="SOURCE_FINAL_FULL_GAME_INCLUDING_OVERTIME", source_row_numbers=str(row["source_game_id"]))
                records.append(row)
        combined = pd.concat([history, pd.DataFrame(records)], ignore_index=True) if records else history
        if combined.game_id.duplicated().any():
            raise ValueError("Duplicate combined history")
        if records:
            data = io.BytesIO()
            combined.sort_values(["game_date", "game_id"]).to_parquet(data, index=False)
            raw = data.getvalue()
            history_ref = immutable(registry / "objects/sha256" / digest(raw) / "games.parquet", raw)
        else:
            history_ref = base["history"]["games"]
        context = dict(context, contextOnlyEvents=context["contextOnlyEvents"] + contexts)
        context_ref = object_json(registry / "objects", context, "context.json")
        acquisition = object_json(registry / "objects", {"schema": "NBA_GEN1_ROLLING_HISTORY_ACQUISITION_V1",
            "acquiredAtUtc": stamp, "sourceCapture": capture_ref, "base": base["history"]["acquisition"],
            "currentSeasonFinalIds": sorted(t["game_id"] for t in finals), "modelFit": False})
        current = copy.deepcopy(base)
        current["history"].update(games=history_ref, contextMetadata=context_ref, acquisition=acquisition)
        current["history"].pop("features", None)  # Features are rebuilt from admitted finals, never stale saved rows.
        current.update(historyGames=len(combined), inputHistoryLatestGameDate=str(combined.game_date.max()),
                       inputUpdate={"capture": capture_ref, "baseModelReceipt": base_model_ref})
        current_ref = object_json(registry / "objects", current, "model-input-receipt.json")
        counts = Counter(t for row in combined[combined.season_end.isin([season_end-1, season_end])].to_dict("records")
                         for t in (row["home_team_id"], row["away_team_id"]))
        coverage = copy.deepcopy(coverage)
        coverage.update(currentResearchReceiptSha256=current_ref["sha256"], targetGameId=None, teamIds=[],
            historyPopulation=history_ref, contextMetadata=context_ref, sourceCutoffUtc=stamp, completeThroughUtc=stamp,
            missingGameIds=sorted(set(missing)), regularSeasonMembershipComplete=not missing,
            reviewedBy=reviewed_by, createdAtUtc=now(), forecastGenerated=False)
        coverage["sourceCaptures"].append({"source": "SportsDataverse current schedule/finals",
            "capturedAtUtc": original_capture, "sourceObject": source, "rightsEvidence": rights_refs,
            "validatedAtUtc": stamp})
        coverage["evidence"].append(capture_ref)
        coverage["membershipReview"] = {"baseCoverage": base_coverage_ref, "currentSeasonFinalIds": [t["game_id"] for t in finals],
            "teamCurrentAndPriorSupportCounts": dict(sorted(counts.items())), "historyGames": len(combined)}
        coverage_ref = object_json(registry / "objects", coverage, "coverage-template.json")
        pointer = registry / "current.json"
        previous = read_ref(reference(pointer))["inputManifest"] if pointer.exists() else None
        if previous:
            old = read_ref(previous)
            if utc(stamp) < utc(old.get("scheduleValidatedAtUtc", old["scheduleCapturedAtUtc"])):
                raise ValueError("Input version clock regression")
            if capture_ref["sha256"] == old["captureReceipt"]["sha256"]:
                return previous  # Preserve original admission bytes and clocks.
        bundle = {"schema": "NBA_GEN1_SLATE_INPUT_V1", "admittedAtUtc": now(), "reviewedBy": reviewed_by,
            "classification": "REAL_LOCAL_GOVERNED_INPUTS", "predecessor": previous,
            "captureReceipt": capture_ref, "source": source, "rightsEvidence": rights_refs,
            "scheduleCapturedAtUtc": original_capture, "scheduleValidatedAtUtc": stamp,
            "historyCompleteThroughUtc": stamp, "sourceCutoffUtc": stamp,
            "predictionInputIdentity": digest({"source": source["sha256"], "history": history_ref["sha256"],
                "context": context_ref["sha256"], "models": base_model_ref["sha256"]}),
            "seasonEnd": season_end, "baseModelReceipt": base_model_ref, "currentModelReceipt": current_ref,
            "coverageTemplate": coverage_ref, "historyMissingGameIds": sorted(set(missing)),
            "games": games, "teamSupportCounts": dict(sorted(counts.items())), "providerCalls": 0,
            "outcomeUse": "Only metadata-selected current-season finals enter chronological future inputs; no selection or fitting"}
        bound = object_json(registry / "versions", bundle, "input.json")
        if precommit:
            precommit(bundle)
        atomic_json(pointer, {"schema": "NBA_GEN1_SLATE_INPUT_POINTER_V1", "inputManifest": bound})
        return bound


def validate_bundle(bundle, release):
    if bundle.get("classification") != "REAL_LOCAL_GOVERNED_INPUTS":
        raise ValueError("Fixtures cannot enter the real publisher")
    base = read_ref(bundle["baseModelReceipt"])
    current = read_ref(bundle["currentModelReceipt"])
    if bundle["baseModelReceipt"]["sha256"] != release["baseModelReceipt"]["sha256"] or base["models"] != current["models"]:
        raise ValueError("Frozen fitted configuration changed")
    coverage = read_ref(bundle["coverageTemplate"])
    capture = read_ref(bundle["captureReceipt"])
    if (capture["source"] != bundle["source"] or capture["capturedAtUtc"] != bundle["scheduleCapturedAtUtc"]
            or capture.get("validatedAtUtc", capture["capturedAtUtc"]) != bundle.get("scheduleValidatedAtUtc", bundle["scheduleCapturedAtUtc"])
            or coverage["completeThroughUtc"] != bundle["historyCompleteThroughUtc"]
            or coverage["sourceCutoffUtc"] != bundle["sourceCutoffUtc"]
            or coverage["currentResearchReceiptSha256"] != bundle["currentModelReceipt"]["sha256"]):
        raise ValueError("Input capture/coverage clocks or identities changed")
    # Reconcile identity-only projection again so registry metadata cannot silently
    # override a cancellation, tipoff, participant or provider identifier.
    frame = pd.read_parquet(io.BytesIO(verified_bytes(bundle["source"])), columns=META)
    games, _, _, _ = classify(frame, bundle["source"]["sha256"])
    if bundle["games"] != games:
        raise ValueError("Admitted schedule differs from source metadata")
    for model in current["models"].values():
        verified_bytes(model["artifact"])
        for module in model["numericalModules"].values():
            verified_bytes(module)
    for ref in [bundle["source"], bundle["captureReceipt"], bundle["coverageTemplate"],
                current["history"]["games"], current["history"]["contextMetadata"], current["history"]["acquisition"],
                *bundle["rightsEvidence"]]:
        verified_bytes(ref)
    method = read_ref(release["jointMethod"])
    verified_bytes(method["residuals"])
    if method["engine"] != release["distributionConfigurationIdentity"] or method["drawCountPerGamePerArm"] != 10000:
        raise ValueError("Joint distribution changed")
