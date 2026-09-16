"""Bounded identity/timing intake for a declared future survival cohort.

No feeds, BF, outs, scores, plays, label covariates, model loads or fitting.
Uses the existing source transport, cache, cumulative budget and intake lock.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import acquire_mlb_starter_duration_history as prior
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask
from server.sports_current_statcast.mlb_v18_unattended import atomic_state, single_owner

OUT = ROOT / "outputs/mlb-v18-survival-starter-coverage-v1/metadata-intake"
SCHEMA = "MLB_SURVIVAL_SLATE_METADATA_INTAKE_V1"
DECLARATION_SCHEMA = "MLB_V18_SURVIVAL_STARTER_COVERAGE_DECLARATION_V1"
NY = ZoneInfo("America/New_York")
PEOPLE_FIELDS = "people,id,fullName,mlbDebutDate"
FLAGS = {"researchShadowOnly": True, "candidateAuthority": False,
         "wageringAuthority": False, "executionAllowedInAISP": False,
         "runtimeEligible": False, "outcomeReads": 0, "gameFeedRequests": 0,
         "numericalCovariatesConstructed": False, "modelFits": 0}


def now():
    return datetime.now(timezone.utc)


def utc(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("EXPLICIT_SOURCE_TIMEZONE_REQUIRED")
    return result.astimezone(timezone.utc)


def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def verified(item):
    if reference(item["path"]) != {k: item[k] for k in ("path", "sha256", "bytes")}:
        raise ValueError("DECLARATION_REFERENCE_MISMATCH")
    return json.loads(Path(item["path"]).read_bytes())


def day_close(day):
    return datetime.combine(day + timedelta(days=1), time.min, NY).astimezone(timezone.utc)


def coverage_window(slate_day, timestamp):
    target = slate_day - timedelta(days=1)
    completed = timestamp.astimezone(NY).date() - timedelta(days=1)
    prefix = min(target, completed)
    if prefix < date(2026, 1, 1):
        raise ValueError("SOURCE_PREFIX_OUTSIDE_SUPPORTED_2026_SCOPE")
    return {"targetThrough": target.isoformat(), "enumerationPrefixThrough": prefix.isoformat(),
            "completionAsOfFloorUtc": day_close(prefix).isoformat(),
            "targetDateClosed": timestamp >= day_close(target),
            "targetCoverageStatus": "IDENTITY_ENUMERATION_ONLY_NOT_ELIGIBILITY_CERTIFICATION" if timestamp >= day_close(target)
                                    else "TARGET_DAY_STILL_OPEN_FRESH_ENUMERATION_REQUIRED_AFTER_DAY_CLOSE",
            "nextCoverageCheckNotBeforeUtc": day_close(target).isoformat()}


def validate_declaration(path, timestamp):
    descriptor = reference(path)
    data = json.loads(Path(path).read_bytes())
    if (data.get("schemaVersion") != DECLARATION_SCHEMA or data.get("researchShadowOnly") is not True
            or data.get("candidateAuthority") is not False or data.get("outcomeAccess") is not False):
        raise ValueError("FROZEN_SOURCE_DECLARATION_SCHEMA_OR_AUTHORITY_MISMATCH")
    authority = prior._verify_declaration()
    if data.get("sourceAuthority") != authority:
        raise ValueError("ORIGINAL_SOURCE_AUTHORITY_NOT_BOUND")
    verified(data["sourceAuthority"])
    original = data.get("originalUserAuthority")
    if not original or original["sha256"] != "0349a49fde2700fd516468c319f8a06bd85380c65e153a54f3575613048d12f1":
        raise ValueError("EXPLICIT_NEXT_SLATE_SOURCE_AUTHORIZATION_NOT_BOUND")
    if reference(original["path"]) != original:
        raise ValueError("ORIGINAL_USER_SOURCE_AUTHORITY_CHANGED")
    identity = verified(data["identityEvidence"])
    evidence_games = {str(g["gameId"]): g for g in identity["games"]}
    declared = utc(data["declaredAtUtc"])
    slate_day = date.fromisoformat(data["slateDate"])
    if declared > timestamp or slate_day < date(2026, 8, 28):
        raise ValueError("DECLARATION_CLOCK_OR_SEALED_EVENT_DATE_INVALID")
    games = []
    for source in data["games"]:
        game = dict(source)
        gid, pk = str(game["gameId"]), str(game["sourceGameId"])
        start, deadline = utc(game["scheduledStartUtc"]), utc(game["deadlineUtc"])
        if (not gid or not pk.isdigit() or not all(final_oot_eligible_key_mask([gid, pk]))
                or start.astimezone(NY).date() != slate_day or not declared < deadline < start):
            raise ValueError("DECLARED_EVENT_IDENTITY_DATE_OR_DEADLINE_INVALID")
        sides = game["sides"]
        evidence = evidence_games.get(gid)
        if (not evidence or str(evidence["sourceGameId"]) != pk
                or utc(evidence["scheduledStartUtc"]) != start or utc(evidence["deadlineUtc"]) != deadline):
            raise ValueError("DECLARED_GAME_DIFFERS_FROM_RETAINED_IDENTITY_EVIDENCE")
        if {side.get("side") for side in sides} != {"HOME", "AWAY"} or len(sides) != 2:
            raise ValueError("BOTH_UNIQUE_STARTER_SIDES_REQUIRED")
        for side in sides:
            pid = side.get("starterMlbamId")
            if pid is not None and (not str(pid).isdigit() or int(pid) <= 0):
                raise ValueError("DECLARED_STARTER_ID_INVALID")
            original_side = next((s for s in evidence["sides"] if s["side"] == side["side"]), None)
            original_pid = (original_side or {}).get("starter", {}).get("mlbamId")
            if (None if pid is None else str(pid)) != (None if original_pid is None else str(original_pid)):
                raise ValueError("DECLARED_STARTER_DIFFERS_FROM_RETAINED_IDENTITY_EVIDENCE")
        ids = [str(s["starterMlbamId"]) for s in sides if s.get("starterMlbamId") is not None]
        if len(set(ids)) != len(ids):
            raise ValueError("SAME_STARTER_ON_BOTH_SIDES")
        game["gameId"], game["sourceGameId"] = gid, pk
        games.append(game)
    if len({g["gameId"] for g in games}) != len(games) or len({g["sourceGameId"] for g in games}) != len(games):
        raise ValueError("DUPLICATE_DECLARED_GAME")
    return descriptor, data, sorted(games, key=lambda g: (utc(g["deadlineUtc"]), g["gameId"]))


def receipt_clock_ok(receipt, floor, timestamp):
    try:
        observed, available, ingested = (utc(receipt[k]) for k in ("observedAt", "availableAsOf", "ingestedAt"))
        return floor <= observed <= available <= timestamp and ingested <= timestamp
    except (KeyError, ValueError, TypeError):
        return False


def cached_projection(url, fields, floor, timestamp):
    """Only hash-bound, projected identity/timing cache entries are considered."""
    candidates = []
    for index in sorted((prior.INTAKE / "cache").glob("*.json")):
        try:
            descriptor = json.loads(index.read_bytes())
            receipt = prior._load_ref(descriptor)
            if (receipt.get("url") == url and receipt.get("fieldsProjection") == fields
                    and receipt.get("costUsd") == 0 and receipt.get("paidProviderCalls") == 0
                    and receipt_clock_ok(receipt, floor, timestamp)):
                candidates.append((utc(receipt["observedAt"]), descriptor, receipt))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    for _, descriptor, receipt in sorted(candidates, key=lambda r: r[0], reverse=True):
        payload = prior._load_ref(receipt["raw"])
        prior._check_projection(payload, fields)
        return receipt, payload, {"receipt": descriptor, "cached": True, "cacheDecision": "RECORDED_OBSERVATION_COVERS_COMPLETED_PREFIX"}
    return None


def cached_people(selected_ids, timestamp):
    """Reuse accepted identity batches even when their requested ID set differs."""
    found, refs = {}, {}
    floor = datetime(1970, 1, 1, tzinfo=timezone.utc)
    for index in sorted((prior.INTAKE / "cache").glob("*.json")):
        descriptor = json.loads(index.read_bytes())
        receipt = prior._load_ref(descriptor)
        if (not receipt.get("url", "").startswith("https://statsapi.mlb.com/api/v1/people?")
                or receipt.get("fieldsProjection") != PEOPLE_FIELDS
                or receipt.get("costUsd") != 0 or receipt.get("paidProviderCalls") != 0
                or not receipt_clock_ok(receipt, floor, timestamp)):
            continue
        payload = prior._load_ref(receipt["raw"])
        prior._check_projection(payload, PEOPLE_FIELDS)
        for row in payload.get("people", []):
            pid = str(row.get("id"))
            if pid not in selected_ids:
                continue
            if pid not in found or utc(receipt["observedAt"]) > found[pid][0]:
                found[pid] = (utc(receipt["observedAt"]), row, descriptor)
    for _, _, descriptor in found.values():
        refs[descriptor["sha256"]] = descriptor
    return {pid: row for pid, (_, row, _) in found.items()}, list(refs.values())


def projection(url, fields, family, prefix, timestamp, *, allow_free_network, stable_identity=False):
    if not url.startswith("https://statsapi.mlb.com/api/v1/") or "/feed/" in url:
        raise ValueError("ONLY_DECLARED_METADATA_ENDPOINTS_ALLOWED")
    permitted = {"PITCHER_APPEARANCE_IDENTITIES_ONLY": prior.LOG_FIELDS,
                 "GAME_COMPLETION_TIMING_METADATA_ONLY": prior.SCHEDULE_FIELDS,
                 "CURRENT_PITCHER_DEBUT_IDENTITY_ONLY": PEOPLE_FIELDS}
    if permitted.get(family) != fields:
        raise ValueError("METADATA_FAMILY_OR_FIELDS_NOT_ALLOWED")
    floor = datetime(1970, 1, 1, tzinfo=timezone.utc) if stable_identity else day_close(prefix)
    cached = cached_projection(url, fields, floor, timestamp)
    if cached is not None:
        return cached
    scope = "SURVIVAL_SLATE_IDENTITY_V1" if stable_identity else prefix.isoformat()
    receipt, payload, reused = prior._request(url, family=family, cache_scope=scope,
        projection=fields, allow_free_network=allow_free_network)
    if not receipt_clock_ok(receipt, floor, now()):
        raise ValueError("CACHED_SOURCE_PREDATES_COMPLETED_PREFIX_NO_SILENT_REFRESH")
    prior._check_projection(payload, fields)
    key = prior._sha(prior._bytes({"url": url, "cacheScope": scope}))
    descriptor = json.loads((prior.INTAKE / "cache" / (key + ".json")).read_bytes())
    return receipt, payload, {"receipt": descriptor, "cached": reused,
                              "cacheDecision": "EXACT_EXISTING_CACHE" if reused else "MISSING_ADEQUATE_CACHE_REFRESHED"}


def appearances(payload, through):
    blocks = payload.get("stats")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("MISSING_PITCHING_ENUMERATION_NOT_ZERO_HISTORY")
    found = {}
    for block in blocks:
        for row in block.get("splits", []):
            day = date.fromisoformat(str(row["date"])[:10])
            pk = int(row["game"]["gamePk"])
            if not date(2026, 1, 1) <= day <= through:
                continue
            if pk in found and found[pk] != day.isoformat():
                raise ValueError("APPEARANCE_IDENTITY_DATE_CONFLICT")
            found[pk] = day.isoformat()
    return [{"gamePk": pk, "gameDate": day} for pk, day in sorted(found.items(), key=lambda r: (r[1], r[0]))]


def raise_unless_pending(exc):
    """Transport/rate/projection failures stop intake, never trigger more calls."""
    pending = ("FREE_NETWORK_OPT_IN_REQUIRED_FOR_UNCACHED_SOURCE", "MISSING_PITCHING_ENUMERATION_NOT_ZERO_HISTORY")
    if not isinstance(exc, ValueError) or not any(tag in str(exc) for tag in pending):
        raise exc


def ordered_starters(games):
    return list(dict.fromkeys(str(s["starterMlbamId"]) for g in games
        for s in sorted(g["sides"], key=lambda s: s["side"] == "HOME") if s.get("starterMlbamId") is not None))


def acquire(declaration_path, *, max_games=1, allow_free_network=False):
    begun = now()
    declaration_ref, declaration, games = validate_declaration(declaration_path, begun)
    if not 1 <= max_games <= len(games):
        raise ValueError("MAX_GAMES_EXCEEDS_DECLARED_SCOPE")
    window = coverage_window(date.fromisoformat(declaration["slateDate"]), begun)
    prefix = date.fromisoformat(window["enumerationPrefixThrough"])
    selected = [g for g in games if begun < utc(g["deadlineUtc"])][:max_games]
    selected_ids = ordered_starters(selected)
    result = {"schemaVersion": SCHEMA, "startedAtUtc": begun.isoformat(), "declaration": declaration_ref,
              "sourceAuthority": declaration["sourceAuthority"], "slateDate": declaration["slateDate"],
              "selectedGameIds": [g["gameId"] for g in selected], "selectedStarterMlbamIds": selected_ids,
              "scopeRule": "FIRST_OPEN_DECLARED_GAMES_IN_DEADLINE_ORDER_NO_OUTCOME_SELECTION",
              **window, "starters": [], "supportTable": [], "requestTemplates": [], "protectedTuples": [],
              "sourceReceipts": [], "pending": [], "metadataOnly": True, **FLAGS}
    with single_owner(prior.INTAKE / "intake.lock") as owned:
        if not owned:
            return {**result, "status": "DEFERRED_EXISTING_INTAKE_LOCK", "accounting": prior._accounting()}
        before = prior._accounting()
        by_pitcher = {}
        try:
            if selected_ids:
                # Existing cached nonsealed probe verifies the provider projection contract.
                probe = prior._safe_2025_probe(allow_free_network=allow_free_network)
                result["projectionProof"] = {"cached": probe["cached"], "receipt": probe["receipt"]}
            for pid in selected_ids:
                if now() >= min(utc(g["deadlineUtc"]) for g in selected if any(str(s.get("starterMlbamId")) == pid for s in g["sides"])):
                    result["pending"].append({"starterMlbamId": pid, "reason": "GAME_DEADLINE_CLOSED_DURING_METADATA_INTAKE"})
                    continue
                url = "https://statsapi.mlb.com/api/v1/people/" + pid + "/stats?" + urlencode({
                    "stats": "gameLog", "group": "pitching", "season": 2026, "gameType": "R", "fields": prior.LOG_FIELDS})
                result["requestTemplates"].append({"family": "PITCHER_APPEARANCE_IDENTITIES_ONLY", "starterMlbamId": pid, "url": url})
                item = {"starterMlbamId": pid, "status": "PENDING_IDENTITY_ENUMERATION", "runtimeEligible": False}
                try:
                    receipt, payload, reuse = projection(url, prior.LOG_FIELDS, "PITCHER_APPEARANCE_IDENTITIES_ONLY", prefix, begun, allow_free_network=allow_free_network)
                    rows = appearances(payload, prefix)
                    item.update(status="PREFIX_APPEARANCE_IDENTITIES_ONLY", appearanceIdentities=rows,
                        appearanceIdentityCount=len(rows), source= reuse, availableAsOf=receipt["availableAsOf"],
                        disposition="APPEARANCES_NOT_PROOF_OF_START_OR_COMPLETE_ELIGIBLE_HISTORY")
                    result["sourceReceipts"].append(reuse["receipt"])
                    for row in rows:
                        if prior._protected(row["gameDate"]):
                            result["protectedTuples"].append({"pitcherMlbamId": pid, **row, "role": "PITCHING_APPEARANCE_START_STATUS_UNPROVEN", "payloadAccessAllowed": False})
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise_unless_pending(exc)
                    item["reason"] = type(exc).__name__ + ": " + str(exc)
                by_pitcher[pid] = item
                result["starters"].append(item)
            # Optional batched identity/debut metadata; never reconstruct aliases from names.
            if selected_ids:
                people, identity_refs = cached_people(selected_ids, begun)
                result["sourceReceipts"].extend(identity_refs)
                missing_ids = sorted(set(selected_ids) - people.keys())
                result["cachedIdentityPitcherIds"] = sorted(people)
                try:
                    if missing_ids:
                        url = "https://statsapi.mlb.com/api/v1/people?" + urlencode({"personIds": ",".join(missing_ids), "fields": PEOPLE_FIELDS})
                        result["requestTemplates"].append({"family": "CURRENT_PITCHER_DEBUT_IDENTITY_ONLY", "starterMlbamIds": missing_ids, "url": url})
                        receipt, payload, reuse = projection(url, PEOPLE_FIELDS, "CURRENT_PITCHER_DEBUT_IDENTITY_ONLY", prefix, begun, allow_free_network=allow_free_network, stable_identity=True)
                        if {str(p["id"]) for p in payload.get("people", [])} != set(missing_ids):
                            raise ValueError("BATCHED_DECLARED_STARTER_IDENTITIES_DIFFER")
                        people.update({str(p["id"]): p for p in payload["people"]})
                        result["sourceReceipts"].append(reuse["receipt"])
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise_unless_pending(exc)
                    result["pending"].append({"reason": "IDENTITY_METADATA: " + str(exc)})
                result["people"] = [people[pid] for pid in sorted(people)]
            union = sorted({r["gamePk"] for item in by_pitcher.values() for r in item.get("appearanceIdentities", [])})
            if union:
                url = "https://statsapi.mlb.com/api/v1/schedule?" + urlencode({"sportId": 1, "gamePks": ",".join(map(str, union)), "fields": prior.SCHEDULE_FIELDS})
                result["requestTemplates"].append({"family": "GAME_COMPLETION_TIMING_METADATA_ONLY", "url": url})
                try:
                    receipt, payload, reuse = projection(url, prior.SCHEDULE_FIELDS, "GAME_COMPLETION_TIMING_METADATA_ONLY", prefix, begun, allow_free_network=allow_free_network)
                    schedule = [g for block in payload.get("dates", []) for g in block.get("games", [])]
                    if {int(g["gamePk"]) for g in schedule} != set(union):
                        raise ValueError("SCHEDULE_METADATA_COVERAGE_DIFFERS_FROM_ENUMERATION")
                    result["completionMetadata"] = schedule
                    result["sourceReceipts"].append(reuse["receipt"])
                    for item in by_pitcher.values():
                        pks = {r["gamePk"] for r in item.get("appearanceIdentities", [])}
                        for game in schedule:
                            if int(game["gamePk"]) not in pks:
                                continue
                            keys = ("officialDate", "gameDate", "resumeDate", "resumeGameDate", "resumedFrom", "resumedFromDate", "rescheduledFrom", "rescheduledFromDate")
                            protected = {k: game[k] for k in keys if prior._protected(game.get(k))}
                            if protected:
                                result["protectedTuples"].append({"pitcherMlbamId": item["starterMlbamId"], "gamePk": game["gamePk"], "protectedTimingFields": protected, "role": "COMPLETION_OR_RESUMPTION_METADATA_ONLY", "payloadAccessAllowed": False})
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise_unless_pending(exc)
                    result["pending"].append({"reason": "COMPLETION_METADATA: " + str(exc)})
            for game in selected:
                for side in game["sides"]:
                    pid = str(side["starterMlbamId"]) if side.get("starterMlbamId") is not None else None
                    item = by_pitcher.get(pid, {})
                    result["supportTable"].append({"gameId": game["gameId"], "sourceGameId": game["sourceGameId"], "side": side["side"],
                        "starterMlbamId": pid, "starterName": side.get("starterName"), "status": item.get("status", "STARTER_IDENTITY_NOT_AVAILABLE"),
                        "appearanceIdentityCount": item.get("appearanceIdentityCount"), "prefixThrough": prefix.isoformat(),
                        "targetThrough": window["targetThrough"], "protectedAppearanceCount": sum(prior._protected(r["gameDate"]) for r in item.get("appearanceIdentities", [])),
                        "eligibleHistoryCertified": False, "runtimeEligible": False})
            result["status"] = "METADATA_ONLY_INTAKE_COMPLETE_WITH_SUPPORT_PENDING"
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result["status"] = "METADATA_INTAKE_STOPPED_FAIL_CLOSED"
            result["pending"].append({"reason": type(exc).__name__ + ": " + str(exc)})
        after = prior._accounting()
        result["accountingBefore"], result["accountingAfter"] = before, after
        result["newRequests"] = after["requestAttempts"] - before["requestAttempts"]
        result["newOriginalBytes"] = after["downloadedOriginalBytes"] - before["downloadedOriginalBytes"]
        result["newCostUsd"] = after["costUsd"] - before["costUsd"]
        result["remainingRequests"] = after["maxRequests"] - after["requestAttempts"]
        result["remainingBytes"] = after["maxBytes"] - after["budgetAccountedBytes"]
        result["completedAtUtc"], result["implementation"] = now().isoformat(), reference(__file__)
        raw = prior._bytes(result)
        digest = hashlib.sha256(raw).hexdigest()
        path = OUT / "objects/sha256" / digest / "metadata-intake.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(raw)
        descriptor = reference(path)
        atomic_state(OUT / "current.json", descriptor)
        return {"result": descriptor, "status": result["status"], "coverageWindow": window,
                "selectedGames": len(selected), "selectedStarters": len(selected_ids), "newRequests": result["newRequests"],
                "newOriginalBytes": result["newOriginalBytes"], "newCostUsd": result["newCostUsd"], **FLAGS}


def self_check():
    stamp = utc("2026-09-12T23:34:00Z")
    w = coverage_window(date(2026, 9, 13), stamp)
    assert w["targetThrough"] == "2026-09-12" and w["enumerationPrefixThrough"] == "2026-09-11" and not w["targetDateClosed"]
    assert w["completionAsOfFloorUtc"] == "2026-09-12T04:00:00+00:00"
    old = {k: "2026-09-11T19:34:00Z" for k in ("observedAt", "availableAsOf", "ingestedAt")}
    assert not receipt_clock_ok(old, day_close(date(2026, 9, 11)), stamp)
    valid = {"stats": [{"splits": [{"date": "2026-08-25", "game": {"gamePk": 822693}}]}]}
    prior._check_projection(valid, prior.LOG_FIELDS)
    assert appearances(valid, date(2026, 9, 11)) == [{"gamePk": 822693, "gameDate": "2026-08-25"}]
    try:
        prior._check_projection({"stats": [{"splits": [{"stat": {"battersFaced": 10}}]}]}, prior.LOG_FIELDS)
    except ValueError:
        pass
    else:
        raise AssertionError("FORBIDDEN_NUMERICAL_METADATA_ACCEPTED")
    assert ordered_starters([{"sides": [{"side": "HOME", "starterMlbamId": "2"}, {"side": "AWAY", "starterMlbamId": "9"}]},
                             {"sides": [{"side": "AWAY", "starterMlbamId": "9"}, {"side": "HOME", "starterMlbamId": "1"}]}]) == ["9", "2", "1"]
    try:
        projection("https://statsapi.mlb.com/api/v1.1/game/123/feed/live", prior.LOG_FIELDS,
                   "PITCHER_APPEARANCE_IDENTITIES_ONLY", date(2026, 9, 11), stamp, allow_free_network=False)
    except ValueError as exc:
        assert str(exc) == "ONLY_DECLARED_METADATA_ENDPOINTS_ALLOWED"
    else:
        raise AssertionError("GAME_FEED_ENDPOINT_ACCEPTED")
    return {"status": "PASS", "checks": ["NEW_YORK_COMPLETED_DATE_PREFIX", "TARGET_DAY_NOT_CERTIFIED_EARLY", "STALE_CACHE_CLOCK_REJECTED", "IDENTITY_ONLY_PROJECTION", "NUMERICAL_FIELDS_REJECTED", "DEADLINE_ORDER_AWAY_THEN_HOME", "GAME_FEED_ENDPOINT_REJECTED"], "providerCalls": 0, "modelLoads": 0, "outcomeReads": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--declaration", type=Path)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--max-games", type=int, default=1)
    parser.add_argument("--allow-free-network", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        result = self_check()
    else:
        if not args.declaration or not args.metadata_only:
            parser.error("--declaration and --metadata-only are required; no numerical/feed mode exists")
        result = acquire(args.declaration, max_games=args.max_games, allow_free_network=args.allow_free_network)
    print(json.dumps(result, indent=2, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
