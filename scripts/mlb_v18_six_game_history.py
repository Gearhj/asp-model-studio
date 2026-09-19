"""Private retained-source adapter for the frozen September 19 six-game study.

No acquisition, fitting or production writes. Current-season identity inventory
defines the last six slots BEFORE missing/protected score records are removed.
Scores are read only from date-isolated, post-seal retained schedule captures.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
SEALED_START, SEALED_END = "2026-08-14", "2026-08-27"
FINAL = {"Final", "Completed Early"}
FROZEN_SOURCE_AS_OF_UTC = "2026-09-19T15:17:03.359113+00:00"


def _clock(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _physical(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": sha256(raw).hexdigest(), "bytes": len(raw)}


def _read(ref):
    if _physical(ref["path"]) != {k: ref[k] for k in ("path", "sha256", "bytes")}:
        raise ValueError("HISTORY_SOURCE_PHYSICAL_BINDING_CHANGED")
    return json.loads(Path(ref["path"]).read_bytes())


def _quarantine(runtime):
    path = runtime / "server/sports_current_statcast/mlb_starter_duration_quarantine.py"
    spec = importlib.util.spec_from_file_location("six_game_original_quarantine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ledger = module.quarantine_ledger()
    if len(ledger["games"]) != 9:
        raise ValueError("CURRENT_NINE_GAME_QUARANTINE_REQUIRED")
    return module, ledger


def _identity(game, group_day):
    teams = game["teams"]
    return {
        "mlbamGamePk": int(game["gamePk"]),
        "gameDate": game.get("officialDate", group_day),
        "scheduledStartUtc": game.get("gameDate"),
        "homeTeamMlbamId": int(teams["home"]["team"]["id"]),
        "awayTeamMlbamId": int(teams["away"]["team"]["id"]),
        "gameNumber": game.get("gameNumber"),
        "doubleHeader": game.get("doubleHeader"),
        "gameType": game.get("gameType"),
        "status": game.get("status", {}).get("detailedState"),
    }


def load_history(runtime, source_as_of_utc=FROZEN_SOURCE_AS_OF_UTC):
    """Return (consolidated final rows, coverage with identityInventory, refs).

    A consolidated row's homeScore/awayScore is the latest retained final
    revision for outcome matching. References separately choose the original
    pre-cutoff revision where present; `revisions` preserves every capture.
    """
    runtime = Path(runtime).resolve()
    source_as_of = _clock(source_as_of_utc)
    quarantine, ledger = _quarantine(runtime)
    source_root = runtime / "outputs/mlb-v18-current-state-pipeline-v1/sources/objects/sha256"
    receipts = []
    later_receipts_ignored = 0
    for path in source_root.glob("*.receipt.json"):
        doc = json.loads(path.read_bytes())  # capture metadata only
        if doc.get("family") in {"SCHEDULE", "SCHEDULE_IDENTITIES_ONLY"}:
            if _clock(doc["observedAt"]) > source_as_of:
                later_receipts_ignored += 1
                continue
            receipts.append((path, doc))
    full = [(p, d) for p, d in receipts if d.get("family") == "SCHEDULE_IDENTITIES_ONLY"
            and d.get("startDate") == "2026-03-25"]
    if not full:
        raise ValueError("FULL_CURRENT_SEASON_IDENTITY_INVENTORY_REQUIRED")
    identity_path, identity_receipt = max(full, key=lambda item: _clock(item[1]["observedAt"]))
    identity_payload = _read(identity_receipt["raw"])
    forbidden_fields = {"score", "runs", "hits", "errors", "linescore", "boxscore", "plays", "allPlays", "stats", "innings"}

    def assert_identity_only(value):
        if isinstance(value, dict):
            if forbidden_fields.intersection(value):
                raise ValueError("IDENTITY_SOURCE_CONTAINS_FORBIDDEN_PAYLOAD")
            for child in value.values():
                assert_identity_only(child)
        elif isinstance(value, list):
            for child in value:
                assert_identity_only(child)

    assert_identity_only(identity_payload)
    identities = {}
    for group in identity_payload.get("dates", []):
        for game in group.get("games", []):
            row = _identity(game, group["date"])
            if row["gameType"] != "R":
                continue
            # The official schedule repeats postponed games under the original
            # calendar group. Use its actual official-date record, not the
            # obsolete postponed listing, preserving the explicit date rule.
            if group["date"] != row["gameDate"]:
                continue
            allowed = quarantine.final_oot_eligible_key_mask([str(row["mlbamGamePk"])])[0]
            row["protected"] = not allowed or SEALED_START <= row["gameDate"] <= SEALED_END
            row["identitySourceSha256"] = identity_receipt["raw"]["sha256"]
            row["identityObservedAtUtc"] = identity_receipt["observedAt"]
            if row["mlbamGamePk"] in identities and identities[row["mlbamGamePk"]] != row:
                raise ValueError("CONFLICTING_CURRENT_SEASON_IDENTITY")
            identities[row["mlbamGamePk"]] = row
    refs = [_physical(quarantine.LEDGER), _physical(identity_path), identity_receipt["raw"]]
    revisions = {}
    rejected = []
    safe_days = []
    excluded_receipts = 0
    suspension_fields = ("resumeDate", "resumeGameDate", "resumedFrom", "rescheduledFrom", "rescheduledFromDate")
    for path, receipt in sorted(receipts, key=lambda item: str(item[0])):
        if receipt.get("family") != "SCHEDULE":
            continue
        day = str(receipt.get("day") or "")
        if not ("2026-08-28" <= day <= "2026-09-30"):
            excluded_receipts += 1
            continue  # protected/raw mixed-date payloads never opened
        query = parse_qs(urlparse(receipt.get("url", "")).query)
        if query.get("date") != [day] or "startDate" in query or "endDate" in query:
            raise ValueError("HISTORY_SOURCE_NOT_SINGLE_SAFE_DAY")
        if receipt.get("rights", {}).get("allowedUse") != "LOCAL_PRIVATE_MODEL_DEVELOPMENT":
            raise ValueError("HISTORY_SOURCE_RESEARCH_RIGHTS_NOT_BOUND")
        expected = {pk: r for pk, r in identities.items() if r["gameDate"] == day}
        if not expected or any(r["protected"] for r in expected.values()):
            raise ValueError("SAFE_DAY_IDENTITY_GATE_FAILED")
        if not all(quarantine.final_oot_eligible_key_mask([str(pk) for pk in expected])):
            raise ValueError("PERMANENTLY_EXCLUDED_HISTORY_GAME")
        # Date-bounded source contract and independent identity gate precede raw access.
        payload = _read(receipt["raw"])
        refs.extend([_physical(path), receipt["raw"]])
        safe_days.append(day)
        for group in payload.get("dates", []):
            if group.get("date") != day:
                raise ValueError("SCHEDULE_RAW_NOT_ISOLATED_TO_RECEIPT_DAY")
            for game in group.get("games", []):
                meta = _identity(game, group["date"])
                pk = meta["mlbamGamePk"]
                if pk not in expected or meta["gameDate"] != day:
                    raise ValueError("SCHEDULE_RAW_IDENTITY_OUTSIDE_SAFE_PROJECTION")
                for key in ("homeTeamMlbamId", "awayTeamMlbamId", "gameType"):
                    if meta[key] != expected[pk][key]:
                        raise ValueError("SCHEDULE_ORIENTATION_CHANGED")
                if meta["status"] not in FINAL:
                    continue
                if meta["gameType"] != "R":
                    continue
                scores = [game["teams"][side].get("score") for side in ("home", "away")]
                if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in scores):
                    rejected.append({"mlbamGamePk": pk, "sourceSha256": receipt["raw"]["sha256"], "reason": "FINAL_SCORES_UNSUPPORTED"})
                    continue
                clocks = {k: receipt[k] for k in ("observedAt", "availableAsOf", "ingestedAt")}
                available = max(_clock(v) for v in clocks.values()).isoformat()
                revision = {
                    **meta, "homeScore": scores[0], "awayScore": scores[1],
                    "completionConfirmedAtUtc": receipt["observedAt"], "completedAtUtc": None,
                    "captureAvailableAtUtc": available, "captureClocks": clocks,
                    "sourceSha256": receipt["raw"]["sha256"], "sourcePath": receipt["raw"]["path"],
                    "receiptSha256": _physical(path)["sha256"],
                    "sourceRevisionIdentity": receipt["raw"]["sha256"] + ":" + str(pk),
                    "providerPublishedAtUtc": receipt.get("providerPublishedAt"),
                    "suspensionOrRescheduleMetadata": {k: game[k] for k in suspension_fields if game.get(k)},
                }
                revisions.setdefault(pk, []).append(revision)
    rows = []
    for pk, items in revisions.items():
        items.sort(key=lambda r: (_clock(r["captureAvailableAtUtc"]), r["sourceSha256"]))
        rows.append({**items[-1], "revisions": items,
                     "finalRevisionCount": len(items),
                     "retainedScoreRevisionCount": len({(r["homeScore"], r["awayScore"]) for r in items})})
    rows.sort(key=lambda r: (r["gameDate"], r["scheduledStartUtc"] or "", r["mlbamGamePk"]))
    refs = list({r["path"]: r for r in refs}.values())
    coverage = {
        "schema": "MLB_V18_SIX_GAME_RETAINED_HISTORY_V1", "safeScheduleCaptureCount": len(safe_days),
        "sourceAsOfUtc": source_as_of.isoformat(), "laterCaptureReceiptsIgnored": later_receipts_ignored,
        "safeDates": sorted(set(safe_days)), "rawFinalGameCount": len(rows),
        "excludedProtectedOrOutOfRangeReceiptCount": excluded_receipts, "quarantineGames": len(ledger["games"]),
        "protectedPayloadsRead": 0, "providerCalls": 0, "rejectedFinalRows": rejected,
        "identityInventory": sorted(identities.values(), key=lambda r: (r["gameDate"], r["mlbamGamePk"])),
        "identityInventoryReceipt": _physical(identity_path),
        "historyLimit": "No raw pre-August28 or protected game payload opened. Exact six slots use the full current-season identity inventory; unavailable slots stay missing. No older-source substitution.",
    }
    return rows, coverage, refs


def reference_for(metadata, rows, identityinventory):
    """Return TEAM_LAST6 and H2H_LAST6; never change requested donor definition.

    metadata requires homeTeamMlbamId, awayTeamMlbamId, scheduledStartUtc,
    cutoffUtc; optional mlbamGamePk. `cutoffUtc` is the earlier retained input
    capture/computation clock, as frozen by the calling study.
    """
    home, away = int(metadata["homeTeamMlbamId"]), int(metadata["awayTeamMlbamId"])
    cutoff = _clock(metadata["cutoffUtc"])
    cutoff_day = cutoff.astimezone(EASTERN).date().isoformat()
    target = int(metadata.get("mlbamGamePk", -1))
    row_index = {r["mlbamGamePk"]: r for r in rows}
    inventory = list(identityinventory)

    def earlier(meta):
        if meta["mlbamGamePk"] == target or meta["gameType"] != "R":
            return False
        if meta["gameDate"] < cutoff_day:
            return meta["status"] in FINAL
        # Same-day donors require an actual retained FINAL capture before cutoff.
        if meta["gameDate"] == cutoff_day:
            return any(_clock(r["captureAvailableAtUtc"]) < cutoff
                       for r in row_index.get(meta["mlbamGamePk"], {}).get("revisions", []))
        return False

    def order(meta):
        return meta["gameDate"], meta.get("scheduledStartUtc") or "", meta.get("gameNumber") or 0, meta["mlbamGamePk"]

    def donor(meta, side, team):
        base = {"side": side, "teamMlbamId": team, "mlbamGamePk": meta["mlbamGamePk"],
                "gameDate": meta["gameDate"], "scheduledStartUtc": meta["scheduledStartUtc"],
                "identitySourceSha256": meta["identitySourceSha256"], "supported": False,
                "runsScored": None}
        if meta["protected"]:
            return {**base, "missingReason": "PROTECTED_OR_PERMANENTLY_QUARANTINED"}
        versions = row_index.get(meta["mlbamGamePk"], {}).get("revisions", [])
        captured = [r for r in versions if _clock(r["captureAvailableAtUtc"]) < cutoff]
        if captured:
            value = captured[-1]
            availability = "GENUINE_RETAINED_FINAL_CAPTURE_BEFORE_CUTOFF"
        elif versions and meta["gameDate"] < cutoff_day:
            value = versions[0]
            if value["suspensionOrRescheduleMetadata"]:
                return {**base, "missingReason": "COMPLETION_DATE_UNCERTAIN_AFTER_SUSPENSION_OR_RESCHEDULE"}
            availability = "RECONSTRUCTED_EARLIER_DATE_FINAL_UNCERTIFIED_HISTORICAL_AVAILABILITY"
        else:
            return {**base, "missingReason": "NO_PERMITTED_ELIGIBLE_RETAINED_FINAL"}
        source_side = "home" if value["homeTeamMlbamId"] == team else "away"
        if team not in (value["homeTeamMlbamId"], value["awayTeamMlbamId"]):
            raise ValueError("REFERENCE_TEAM_ORIENTATION_FAILED")
        return {**base, "supported": True, "runsScored": value[source_side + "Score"],
                "sourceSide": source_side, "availabilityClass": availability,
                **{k: value[k] for k in ("sourceSha256", "sourcePath", "receiptSha256", "sourceRevisionIdentity",
                                         "captureAvailableAtUtc", "completionConfirmedAtUtc", "completedAtUtc")}}

    result = {}
    for definition in ("TEAM_LAST6", "H2H_LAST6"):
        donors, means, counts, slot_counts = [], {}, {}, {}
        for side, team in (("home", home), ("away", away)):
            pool = [r for r in inventory if earlier(r) and team in (r["homeTeamMlbamId"], r["awayTeamMlbamId"])]
            if definition == "H2H_LAST6":
                pool = [r for r in pool if {r["homeTeamMlbamId"], r["awayTeamMlbamId"]} == {home, away}]
            slots = sorted(pool, key=order)[-6:]
            selected = [donor(r, side, team) for r in slots]
            donors.extend(selected)
            supported = [r for r in selected if r["supported"]]
            slot_counts[side] = len(slots)
            counts[side] = len(supported)
            means[side] = sum(r["runsScored"] for r in supported) / len(supported) if supported else None
        complete = all(counts[s] == slot_counts[s] == 6 for s in ("home", "away"))
        classes = {r["availabilityClass"] for r in donors if r["supported"]}
        availability = ("UNSUPPORTED" if not classes else next(iter(classes)) if len(classes) == 1
                        else "MIXED_GENUINE_CAPTURE_AND_RECONSTRUCTED_HISTORY")
        result[definition] = {
            "definition": definition, "homeMean": means["home"], "awayMean": means["away"],
            "homeSupport": counts["home"], "awaySupport": counts["away"], "completeSix": complete,
            "homeIdentitySlots": slot_counts["home"], "awayIdentitySlots": slot_counts["away"],
            "availabilityClass": availability, "cutoffUtc": cutoff.isoformat(),
            "supportClass": "COMPLETE_SIX" if complete else "PARTIAL_ACTUAL_LAST_SIX_SLOTS" if min(counts.values()) else "UNSUPPORTED_ONE_OR_BOTH_TEAMS",
            "historyCompleteness": "CURRENT_SEASON_LAST_SIX_IDENTITIES_COVERED" if min(slot_counts.values()) == 6 else "PRE2026_LAST_SIX_ORDER_UNAVAILABLE",
            "donors": donors,
            "missingGameIds": sorted({r["mlbamGamePk"] for r in donors if not r["supported"]}),
            "sameDayRule": "Excluded unless original retained FINAL capture was available before the cutoff",
            "meanQualification": "Short-support means average only supported actual last-six slots; they are not complete six-game averages" if not complete else "Six supported earlier completed games per team",
        }
    return result
