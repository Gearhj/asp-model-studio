"""Assemble the first declared Sep13 starter histories; network is opt-in.

Uses frozen source parsers and the existing source budget/lock. Protected
appearances remain metadata-only gaps. Only this declaration's history pointer
is written; this command neither fits nor simulates nor changes the pilot.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import acquire_mlb_starter_duration_history as transport
import acquire_mlb_survival_slate_history_v1 as metadata
from server.sports_current_statcast import mlb_starter_duration_history as history
from server.sports_current_statcast.mlb_starter_duration_current_inputs import HISTORY_ROOT
from server.sports_current_statcast.mlb_starter_duration_quarantine import (
    final_oot_eligible_key_mask, SIX_ALLOWED, assert_prospective_source_allowed)
from server.sports_current_statcast.mlb_v18_unattended import atomic_state, single_owner

OUT = ROOT / "outputs/mlb-v18-survival-starter-coverage-v1"
DECLARATION_SHA = "fe1fb2ee0363788d08332ad17497e8627ad39b39f82d8e7fedc05be7a8ab54d3"
IDENTITIES = {"687312": "mlbam:player:687312", "695549": "retrosheet:player:jobej001"}
HOLD_PROOF_SHA = "b9d5d18adfef62461e5c8c2ac753ebf2288a93d90d30a215866caf4f8da07f51"
HOLD_PROOF = OUT / "identity-proofs/sha256" / HOLD_PROOF_SHA / "frozen-hold-game-proof.json"
DATE_FIELDS = ("officialDate", "gameDate", "resumeDate", "resumeDateTime", "resumeGameDate",
               "resumedFrom", "resumedFromDate", "rescheduledFrom", "rescheduledFromDate")
SLIM = ("startId", "gameId", "gamePk", "pitcherMlbamId", "pitcherId", "gameDate", "completionDate",
        "eligible", "totalBf", "totalOuts", "disposition", "endpoint", "exclusionReason",
        "availableAsOf", "observedAt", "ingestedAt")


class FeedValidationError(ValueError):
    def __init__(self, reason, source):
        super().__init__(reason)
        self.source = source


def now():
    return datetime.now(timezone.utc)


def ref(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def load(descriptor):
    actual = ref(descriptor["path"])
    if any(actual[k] != descriptor[k] for k in ("path", "sha256", "bytes")):
        raise ValueError("SOURCE_REFERENCE_CHECKSUM_OR_SIZE_CHANGED")
    return json.loads(Path(actual["path"]).read_bytes())


def pointer(path):
    descriptor = json.loads(Path(path).read_bytes())
    return descriptor, load(descriptor)


def save(root, name, value):
    data = value if isinstance(value, bytes) else history.canonical_json_bytes(value)
    digest = hashlib.sha256(data).hexdigest()
    path = Path(root) / "objects/sha256" / digest / name
    history._write(path, data)
    return ref(path)


def protected(day):
    return "2026-08-14" <= str(day or "")[:10] <= "2026-08-27"


def exact_hold_clearance(pid, pk, day, held):
    """Resolve one measured same-date collision without weakening the hold."""
    if (str(pid), int(pk), day) != ("687312", 824332, "2026-07-17"):
        return None
    descriptor = ref(HOLD_PROOF)
    if descriptor["sha256"] != HOLD_PROOF_SHA:
        raise ValueError("EXACT_HOLD_IDENTITY_PROOF_CHANGED")
    proof = load(descriptor)
    for key in ("hold", "canonicalIdentityCode", "sourceIdentityProjection", "sourceProjectionProvenance"):
        if ref(proof[key]["path"]) != proof[key]:
            raise ValueError("EXACT_HOLD_PROOF_SOURCE_CHANGED")
    from server.sports_silver.canonical_ids import canonical_game_id
    candidate = proof["candidate"]
    if (proof["schemaVersion"] != "MLB_FROZEN_HOLD_EXACT_GAME_IDENTITY_PROOF_V1"
            or proof["classification"] != "NO_FROZEN_HOLD_GAME_OR_PA_INTERSECTION"
            or proof["hold"]["sha256"] != history.HOLD_SHA
            or proof["allHeldCanonicalGameIntersectionCount"] != 0
            or proof["allHeldCanonicalPaIntersectionCount"] != 0
            or candidate["canonicalGameId"] != canonical_game_id(pk)
            or candidate["mlbamGamePk"] != str(pk) or candidate["gameDate"] != day
            or candidate["pitcherMlbamId"] != str(pid)
            or candidate["canonicalGameId"] in {r["canonicalGameId"] for r in held["heldObservations"]}
            or not proof["held56Preserved"]):
        raise ValueError("EXACT_HOLD_GAME_CLEARANCE_FAILED")
    return descriptor


def metadata_gate(appearance, schedule, prefix):
    """No feed/cache payload is opened until all known dates and keys pass."""
    pk, day = int(appearance["gamePk"]), str(appearance["gameDate"])
    if not date(2026, 1, 1) <= date.fromisoformat(day) <= prefix:
        raise ValueError("APPEARANCE_OUTSIDE_ENUMERATED_CLOSED_PREFIX")
    if not all(final_oot_eligible_key_mask([str(pk), f"mlbam:game:{pk}"])):
        return "PERMANENT_WHOLE_GAME_QUARANTINE", {}
    if protected(day):
        return "PROTECTED_APPEARANCE_NO_PAYLOAD_AUTHORITY", {"appearanceDate": day}
    if schedule is None:
        return "COMPLETION_METADATA_UNAVAILABLE", {}
    if int(schedule.get("gamePk", 0)) != pk:
        raise ValueError("SCHEDULE_GAME_IDENTITY_MISMATCH")
    fields = {k: schedule[k] for k in DATE_FIELDS if schedule.get(k)}
    for value in fields.values():
        date.fromisoformat(str(value)[:10])
    blocked = {k: v for k, v in fields.items() if protected(v)}
    if blocked:
        return "PROTECTED_COMPLETION_OR_RESUMPTION_NO_PAYLOAD_AUTHORITY", blocked
    if schedule.get("officialDate") != day:
        return "SOURCE_OFFICIAL_DATE_MISMATCH", fields
    if schedule.get("status", {}).get("abstractGameState") != "Final":
        return "NOT_VERIFIED_COMPLETED", fields
    return None, fields


def load_metadata(declaration_path, intake_pointer, timestamp):
    dref, declaration, games = metadata.validate_declaration(declaration_path, timestamp)
    if dref["sha256"] != DECLARATION_SHA:
        raise ValueError("FROZEN_DECLARATION_CHANGED")
    first = games[0]
    if first["sourceGameId"] != "824225" or {str(s["starterMlbamId"]) for s in first["sides"]} != set(IDENTITIES):
        raise ValueError("FIRST_DECLARED_GAME_TWO_STARTER_SCOPE_CHANGED")
    if timestamp >= metadata.utc(first["deadlineUtc"]):
        raise ValueError("DECLARED_GAME_DEADLINE_PASSED")
    mref, intake = pointer(intake_pointer)
    allowed_games = {g["gameId"] for g in games}
    allowed_pitchers = {str(s["starterMlbamId"]) for g in games for s in g["sides"] if s.get("starterMlbamId")}
    selected_games = set(intake.get("selectedGameIds", []))
    selected_pitchers = set(intake.get("selectedStarterMlbamIds", []))
    if (intake.get("schemaVersion") != metadata.SCHEMA or intake.get("declaration") != dref
            or intake.get("metadataOnly") is not True
            or first["gameId"] not in selected_games or not selected_games <= allowed_games
            or not set(IDENTITIES) <= selected_pitchers or not selected_pitchers <= allowed_pitchers):
        raise ValueError("METADATA_INTAKE_DECLARATION_OR_STARTER_SCOPE_MISMATCH")
    prefix = date.fromisoformat(intake["enumerationPrefixThrough"])
    window = metadata.coverage_window(date.fromisoformat(declaration["slateDate"]), timestamp)
    if (prefix > date.fromisoformat(window["enumerationPrefixThrough"])
            or intake["targetThrough"] != window["targetThrough"]
            or metadata.utc(intake["completedAtUtc"]) > timestamp
            or metadata.utc(intake["completionAsOfFloorUtc"]) != metadata.day_close(prefix)):
        raise ValueError("METADATA_INTAKE_PREFIX_OR_CLOCK_INVALID")
    # Refresh after day-close is explicit: an older Sep11 enumeration cannot
    # silently become Sep12 coverage merely because this projection runs later.
    receipts, people, schedules = {}, {}, {}
    selected_pks = {int(a["gamePk"]) for item in intake.get("starters", [])
                    if item.get("starterMlbamId") in IDENTITIES
                    for a in item.get("appearanceIdentities", [])}
    for descriptor in intake.get("sourceReceipts", []):
        if not Path(descriptor["path"]).resolve().is_relative_to(transport.INTAKE.resolve()):
            raise ValueError("SOURCE_RECEIPT_OUTSIDE_EXISTING_INTAKE")
        source = load(descriptor)
        family = source.get("family")
        fields = {"PITCHER_APPEARANCE_IDENTITIES_ONLY": transport.LOG_FIELDS,
                  "GAME_COMPLETION_TIMING_METADATA_ONLY": transport.SCHEDULE_FIELDS,
                  "CURRENT_PITCHER_DEBUT_IDENTITY_ONLY": metadata.PEOPLE_FIELDS}.get(family)
        if fields is None or source.get("fieldsProjection") != fields:
            raise ValueError("NON_METADATA_SOURCE_IN_IDENTITY_INTAKE")
        if family == "PITCHER_APPEARANCE_IDENTITIES_ONLY" and not any(
                source["url"].startswith(f"https://statsapi.mlb.com/api/v1/people/{pid}/stats?") for pid in IDENTITIES):
            continue
        floor = datetime(1970, 1, 1, tzinfo=timezone.utc) if family == "CURRENT_PITCHER_DEBUT_IDENTITY_ONLY" else metadata.day_close(prefix)
        if not metadata.receipt_clock_ok(source, floor, timestamp):
            raise ValueError("ENUMERATION_OR_COMPLETION_SOURCE_CLOCK_INVALID")
        payload = transport._load_ref(source["raw"])
        transport._check_projection(payload, fields)
        receipts[descriptor["sha256"]] = (source, payload)
        if family == "CURRENT_PITCHER_DEBUT_IDENTITY_ONLY":
            for person in payload.get("people", []):
                if str(person["id"]) in IDENTITIES:
                    people[str(person["id"])] = person
        if family == "GAME_COMPLETION_TIMING_METADATA_ONLY":
            for group in payload.get("dates", []):
                for game in group.get("games", []):
                    key = int(game["gamePk"])
                    if key not in selected_pks:
                        continue
                    if key in schedules and schedules[key] != game:
                        raise ValueError("CONFLICTING_COMPLETION_METADATA")
                    schedules[key] = game
    enumerations, gaps = {}, []
    for pid in IDENTITIES:
        items = [x for x in intake.get("starters", []) if x.get("starterMlbamId") == pid]
        if len(items) != 1 or items[0].get("status") != "PREFIX_APPEARANCE_IDENTITIES_ONLY":
            gaps.append({"pitcherMlbamId": pid, "reason": "COMPLETE_APPEARANCE_ENUMERATION_UNAVAILABLE"})
            continue
        item = items[0]
        descriptor = item["source"]["receipt"]
        if descriptor["sha256"] not in receipts:
            raise ValueError("ENUMERATION_SOURCE_NOT_IN_VERIFIED_RECEIPTS")
        source, payload = receipts[descriptor["sha256"]]
        if not source["url"].startswith(f"https://statsapi.mlb.com/api/v1/people/{pid}/stats?"):
            raise ValueError("ENUMERATION_PITCHER_SOURCE_IDENTITY_MISMATCH")
        rows = metadata.appearances(payload, prefix)
        if rows != item["appearanceIdentities"] or len(rows) != item["appearanceIdentityCount"]:
            raise ValueError("ENUMERATION_PROJECTION_DIFFERS_FROM_SOURCE")
        enumerations[pid] = rows
    return dref, first, mref, intake, prefix, window, people, schedules, enumerations, gaps


def cached_prefix(path, declaration_ref, timestamp, people):
    cref, cached = pointer(path)
    if (cached.get("schemaVersion") != "MLB_SURVIVAL_FIRST_SLATE_CACHED_HISTORY_V1"
            or cached.get("declaration") != declaration_ref or cached.get("playerIdentityMap") != IDENTITIES
            or metadata.utc(cached["createdAtUtc"]) > timestamp):
        raise ValueError("CACHED_PREFIX_IDENTITY_OR_AVAILABILITY_MISMATCH")
    old_code = cached["preservedOriginalHistoryCode"]
    if ref(old_code["path"]) != old_code:
        raise ValueError("PRESERVED_FROZEN_PARSER_CODE_CHANGED")
    wanted = {"parse_statsapi_start", "completion_from_observed_clocks"}
    def functions(path):
        return {n.name: ast.dump(n) for n in ast.parse(Path(path).read_bytes()).body
                if isinstance(n, ast.FunctionDef) and n.name in wanted}
    if functions(old_code["path"]) != functions(history.__file__) or len(functions(history.__file__)) != 2:
        raise ValueError("FROZEN_STATSAPI_PARSER_OR_COMPLETION_RULE_CHANGED")
    cert = cached["certified2023And2024"]
    if cert["manifest"]["sha256"] != history.CERTIFIED_SHA:
        raise ValueError("CERTIFIED_BASE_IDENTITY_CHANGED")
    manifest = load(cert["manifest"])
    if any(cert["starts"][k] != manifest["artifacts"]["starts.parquet"][k] for k in ("sha256", "bytes")):
        raise ValueError("CERTIFIED_STARTS_NOT_BOUND_TO_MANIFEST")
    if ref(cert["starts"]["path"]) != cert["starts"]:
        raise ValueError("CERTIFIED_STARTS_CHECKSUM_CHANGED")
    # Registered artifact is only 2023/24. Select identities before BF payload.
    identity = pq.ParquetFile(cert["starts"]["path"]).read(columns=["pitcherId", "gameDate"]).to_pylist()
    if any(not "2023-01-01" <= r["gameDate"] <= "2024-12-31" for r in identity):
        raise ValueError("CERTIFIED_BASE_HAS_OUT_OF_SCOPE_DATES")
    base = pq.read_table(cert["starts"]["path"], filters=[("pitcherId", "in", list(IDENTITIES.values()))]).to_pylist()
    records = []
    for row in base:
        record = {k: row.get(k) for k in SLIM}
        record.update(completionDate=row["gameDate"], disposition="ELIGIBLE" if row["eligible"] else "EXCLUDED")
        records.append(record)
    rref = cached["reconciliation2025"]
    reconciled = load(rref)
    if any(r["pitcherId"] != IDENTITIES["695549"] or not "2025-01-01" <= r["gameDate"] <= "2025-12-31" for r in reconciled["starts"]):
        raise ValueError("RECONCILED_2025_SCOPE_CHANGED")
    records.extend(reconciled["starts"])
    jobe = cached["jobe2025Coverage"]
    jobe_ok = (jobe.get("completeThrough") == "2025-12-31"
               and jobe["candidateStarts"] == jobe["accountedFor"] == len(reconciled["starts"])
               and all(r["disposition"] in ("ELIGIBLE", "EXCLUDED") for r in reconciled["starts"]))
    debut = people.get("687312", {}).get("mlbDebutDate")
    hughes_ok = bool(debut and date.fromisoformat(debut) > date(2025, 12, 31)
                     and date.fromisoformat(debut) <= timestamp.date())
    return records, {"695549": jobe_ok, "687312": hughes_ok}, {
        "cachedHistory": cref, "certifiedManifest": cert["manifest"], "certifiedStarts": cert["starts"],
        "reconciliation2025": rref, "derivedHistoryAvailableAtUtc": cached["createdAtUtc"],
        "hughesNativeDebutDate": debut, "hughesNoPre2026HistoryCertified": hughes_ok,
        "jobePre2026CoverageCertified": jobe_ok}


def acquire_feed(appearance, schedule, prefix, *, allow_free_network, pitcher_id=None):
    key = (str(pitcher_id), int(appearance["gamePk"]), str(appearance["gameDate"]))
    if key in SIX_ALLOWED:
        # Exact user amendment and append-only whole-game quarantine must pass
        # before opening a projected cache entry or contacting the provider.
        authority = assert_prospective_source_allowed(*key)
        if not date(2026, 1, 1) <= date.fromisoformat(key[2]) <= prefix:
            return None, {"reason": "AUTHORIZED_APPEARANCE_OUTSIDE_CLOSED_PREFIX", "payloadRead": False}
        if (schedule is None or int(schedule.get("gamePk", 0)) != key[1]
                or schedule.get("officialDate") != key[2]
                or schedule.get("status", {}).get("abstractGameState") != "Final"):
            return None, {"reason": "AUTHORIZED_APPEARANCE_COMPLETION_METADATA_REQUIRED", "payloadRead": False}
        fields = transport.starter_feed_fields(key[0])
        url = f"https://statsapi.mlb.com/api/v1.1/game/{key[1]}/feed/live?" + urlencode({"fields": fields})
        scope = {"pitcherMlbamId": key[0], "gamePk": key[1], "gameDate": key[2]}
        receipt, feed, reused = transport._request(url,
            family="AUTHORIZED_PROSPECTIVE_STARTER_HISTORY_ONLY",
            cache_scope="SIX_GAME_PROSPECTIVE_HGB_V2:" + authority["authorityRef"]["sha256"],
            projection=fields, protected_scope=scope, allow_free_network=allow_free_network)
        if (receipt.get("protectedDerivativeAuthority") != authority["authorityRef"]
                or receipt.get("quarantineRef") != authority["quarantineRef"]
                or receipt.get("authorizedTuple") != scope
                or receipt.get("evaluationAllowed") is not False
                or receipt.get("sealedEvaluationFilesRead") != 0
                or int(feed.get("gamePk", 0)) != key[1]
                or feed.get("gameData", {}).get("datetime", {}).get("officialDate") != key[2]
                or not metadata.receipt_clock_ok(receipt, datetime(1970, 1, 1, tzinfo=timezone.utc), now())):
            raise FeedValidationError("EXACT_AUTHORIZED_SOURCE_IDENTITY_CLOCK_OR_USE_MISMATCH", receipt)
        return (receipt, feed, reused), None
    reason, dates = metadata_gate(appearance, schedule, prefix)
    if reason:
        return None, {"reason": reason, "timingMetadata": dates, "payloadRead": False}
    pk = int(appearance["gamePk"])
    url = f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live"
    receipt, feed, reused = transport._request(url, family="NONSEALED_FINAL_GAME_FEED",
        cache_scope="FINAL_2026_V1", allow_free_network=allow_free_network)
    if (receipt.get("url") != url or receipt.get("family") != "NONSEALED_FINAL_GAME_FEED"
            or receipt.get("sourcePurpose") != "CURRENT_STARTER_DURATION_HISTORY_ONLY"
            or receipt.get("fieldsProjection") is not None
            or receipt.get("costUsd") != 0 or receipt.get("paidProviderCalls") != 0):
        raise FeedValidationError("FEED_SOURCE_FAMILY_OR_PURPOSE_MISMATCH", receipt)
    if not metadata.receipt_clock_ok(receipt, datetime(1970, 1, 1, tzinfo=timezone.utc), now()):
        raise FeedValidationError("FEED_SOURCE_CLOCK_INVALID", receipt)
    if (int(feed.get("gamePk", 0)) != pk
            or feed.get("gameData", {}).get("datetime", {}).get("officialDate") != appearance["gameDate"]):
        raise FeedValidationError("FEED_GAME_OR_DATE_IDENTITY_MISMATCH", receipt)
    return (receipt, feed, reused), None


def build(args):
    begun = now()
    if args.output_root.resolve() != OUT:
        raise ValueError("FIXED_NEW_COHORT_RESULT_ROOT_REQUIRED")
    with single_owner(transport.INTAKE / "intake.lock") as owned:
        if not owned:
            return {"status": "DEFERRED_EXISTING_INTAKE_LOCK", "accounting": transport._accounting()}
        before = transport._accounting()
        dref, game, mref, intake, prefix, window, people, schedules, enum, gaps = load_metadata(
            args.declaration, args.metadata_pointer, begun)
        records, prior_complete, prior_refs = cached_prefix(args.cached_history_pointer, dref, begun, people)
        hold_ref = ref(history.HOLD)
        if hold_ref["sha256"] != history.HOLD_SHA:
            raise ValueError("FROZEN_56_ROW_HOLD_IDENTITY_CHANGED")
        held = load(hold_ref)
        if held.get("heldRows") != 56 or len(held.get("heldObservations", [])) != 56:
            raise ValueError("FROZEN_56_ROW_HOLD_CHANGED")
        held_dates = {r["gameDate"] for r in held["heldObservations"] if r["gameDate"].startswith("2026-")}
        expected = {(pid, int(a["gamePk"])): a for pid, rows in enum.items() for a in rows}
        if len(expected) != sum(len(rows) for rows in enum.values()):
            raise ValueError("DUPLICATE_EXPECTED_APPEARANCE")
        parsed, unknown, acquisitions = [], [], []
        stopped = None
        for (pid, pk), appearance in sorted(expected.items(), key=lambda x: (x[1]["gameDate"], x[0])):
            ident = {"pitcherMlbamId": pid, "gamePk": pk, "gameDate": appearance["gameDate"]}
            if stopped:
                unknown.append({**ident, "reason": "SOURCE_RUN_STOPPED_FAIL_CLOSED", "payloadRead": False})
                continue
            if now() >= metadata.utc(game["deadlineUtc"]):
                stopped = "DECLARED_GAME_DEADLINE_PASSED_DURING_INTAKE"
                unknown.append({**ident, "reason": stopped, "payloadRead": False})
                continue
            source, feed_opened = None, False
            try:
                value, blocked = acquire_feed(appearance, schedules.get(pk), prefix,
                    allow_free_network=args.allow_free_network, pitcher_id=pid)
                if blocked:
                    unknown.append({**ident, **blocked})
                    continue
                source, feed, reused = value
                feed_opened = True
                candidate = {**appearance, "pitcherMlbamIds": [pid], "scheduleMetadata": schedules[pk]}
                completion = history.completion_from_observed_clocks(candidate, feed)
                row = history.parse_statsapi_start(feed, pitcher_mlbam_id=pid,
                    completion_metadata=completion, source_reference=source["raw"])
                if row.get("disposition") not in {"ELIGIBLE", "EXCLUDED", "UNRESOLVED"} or row.get("eligible") != (row["disposition"] == "ELIGIBLE"):
                    raise ValueError("PARSER_DISPOSITION_IDENTITY_INVALID")
                row["pitcherId"] = IDENTITIES[pid]
                if row["gameDate"] in held_dates:
                    clearance = exact_hold_clearance(pid, pk, row["gameDate"], held)
                    if clearance:
                        row["frozenHoldIdentityProof"] = clearance
                    else:
                        row.update(eligible=False, disposition="UNRESOLVED", unresolvedReasons=["FROZEN_HOLD_GAME_PA_IDENTITY_INTERSECTION_REQUIRES_PROOF"])
                if row.get("completionDate") and row["completionDate"] > prefix.isoformat():
                    raise ValueError("COMPLETION_OUTSIDE_CLOSED_ENUMERATION_PREFIX")
                row.update({k: source[k] for k in ("observedAt", "availableAsOf", "ingestedAt")})
                row["completionEvidence"] = completion
                row["sourceAcquisition"] = source
                if protected(appearance["gameDate"]):
                    row["protectedHistoryDerivative"] = True
                    row["protectedDerivativeAuthority"] = source["protectedDerivativeAuthority"]
                row["sourceTeamMlbamIds"] = {side: team.get("id") for side, team in feed.get("gameData", {}).get("teams", {}).items()}
                parsed.append(row)
                acquisitions.append({**ident, "source": source, "cacheReused": reused})
            except ValueError as error:
                reason = str(error)
                source = getattr(error, "source", None) or source
                unknown.append({**ident, "reason": reason,
                    "payloadRead": True if feed_opened or source else (False if reason == "FREE_NETWORK_OPT_IN_REQUIRED_FOR_UNCACHED_SOURCE" else None),
                    "sourceAcquisition": source,
                    "sourceAccessNote": "Successful feed retrieval is counted even when later parsing fails; interrupted transport access is unknown."})
                if reason != "FREE_NETWORK_OPT_IN_REQUIRED_FOR_UNCACHED_SOURCE":
                    stopped = reason
            except (OSError, KeyError, TypeError) as error:
                stopped = type(error).__name__ + ": " + str(error)
                unknown.append({**ident, "reason": stopped, "payloadRead": True if feed_opened else None,
                                "sourceAcquisition": source})
        created = now().isoformat()
        counts, coverage = {}, {}
        for pid, mapped in IDENTITIES.items():
            rows = [r for r in parsed if r["pitcherMlbamId"] == pid]
            missing = [u for u in unknown if u["pitcherMlbamId"] == pid]
            c = Counter(r["disposition"] for r in rows)
            c["UNRESOLVED"] += len(missing)
            if sum(c.values()) != len(enum.get(pid, [])):
                raise ValueError("APPEARANCE_ACCOUNTING_DOES_NOT_RECONCILE")
            complete = pid in enum and prior_complete[pid] and c["UNRESOLVED"] == 0 and stopped is None
            through = prefix.isoformat() if complete else ("2025-12-31" if prior_complete[pid] else "2022-12-31")
            counts[pid] = {"enumerated2026Appearances": len(enum[pid]) if pid in enum else None,
                           "eligible2026Starts": c["ELIGIBLE"], "justified2026Exclusions": c["EXCLUDED"],
                           "unresolved2026Appearances": c["UNRESOLVED"], "pre2026Certified": prior_complete[pid]}
            coverage[mapped] = {"completeFrom": "2023-01-01", "completeThrough": through,
                "attemptedThrough": prefix.isoformat(), "targetThrough": window["targetThrough"],
                "allScheduledStartsAccountedFor": complete, "eligibleStartDefinitionVerified": True,
                "targetThroughAccountedFor": complete and through == window["targetThrough"],
                "unresolvedProtectedAppearances": [u for u in missing if "PROTECTED" in u["reason"] or "QUARANTINE" in u["reason"]],
                "unresolvedNonsealedStarts": [u for u in missing if "PROTECTED" not in u["reason"] and "QUARANTINE" not in u["reason"]]
                    + [r for r in rows if r["disposition"] == "UNRESOLVED"],
                "enumerationGap": next((g for g in gaps if g["pitcherMlbamId"] == pid), None),
                "observedAt": created, "availableAsOf": created, "ingestedAt": created}
        records.extend(parsed)
        for row in records:
            row["availableAsOf"] = created
            row.setdefault("observedAt", created)
            row.setdefault("ingestedAt", created)
        if len({r["startId"] for r in records}) != len(records):
            raise ValueError("DUPLICATE_HISTORY_START_IDENTITY")
        slim = [{k: r.get(k) for k in SLIM} for r in records]
        buffer = io.BytesIO()
        pd.DataFrame(slim, columns=SLIM).to_parquet(buffer, index=False, compression="zstd")
        payload = buffer.getvalue()
        after = transport._accounting()
        target_complete = all(c["targetThroughAccountedFor"] for c in coverage.values())
        protected_rows = [r for r in parsed if protected(r["gameDate"])]
        protected_descriptors = [{"pitcherMlbamId": r["pitcherMlbamId"], "gamePk": int(r["gamePk"]),
                                  "gameDate": r["gameDate"]} for r in protected_rows]
        protected_authority = None
        for descriptor in protected_descriptors:
            actual = assert_prospective_source_allowed(descriptor["pitcherMlbamId"], descriptor["gamePk"], descriptor["gameDate"])
            if protected_authority is not None and actual["authorityRef"] != protected_authority["authorityRef"]:
                raise ValueError("MIXED_PROTECTED_SOURCE_AUTHORITIES_NOT_SUPPORTED_IN_THIS_COHORT")
            protected_authority = actual
        report = {"schemaVersion": "MLB_STARTER_DURATION_COMPLETED_HISTORY_V1",
            "sourcePurpose": "CURRENT_PREGAME_INPUTS_ONLY", "payloadRole": "CURRENT_STARTER_DURATION_HISTORY_PROJECTION",
            "eligibilityDefinition": "MLB_STARTER_SURVIVAL_RISK_V1", "frozenEligibilityHoldPreserved": True,
            "sealedEvaluationPayloadsRead": 0, "protectedStartPayloadCount": len(protected_descriptors),
            "protectedStartDescriptors": protected_descriptors,
            "protectedExceptionAuthority": protected_authority["authorityRef"] if protected_authority else None,
            "wholeGameQuarantine": protected_authority["quarantineRef"] if protected_authority else None,
            "createdAt": created, "sourceEligibilityCutoff": created,
            "status": "COMPLETE_COMPATIBLE_CURRENT_STARTER_HISTORY" if target_complete else "PARTIAL_COVERAGE_NOT_USABLE_FOR_FORECAST",
            "declaration": dref, "declaredGameId": game["gameId"], "declaredSourceGameId": game["sourceGameId"],
            "playerIdentityMap": IDENTITIES, "coverageByPlayer": coverage, "counts": counts,
            "metadataIntake": mref, "priorHistoryEvidence": prior_refs,
            **window, "latestClosedPrefixThrough": window["enumerationPrefixThrough"],
            "enumerationPrefixThrough": prefix.isoformat(),
            "unresolvedMetadataOnly": unknown + gaps, "parsed2026Dispositions": parsed,
            "sourceAcquisitions": acquisitions, "stoppedReason": stopped,
            "frozenHold2026": {"heldCount": 56, "candidateDateIntersections": sorted(held_dates & {a["gameDate"] for a in expected.values()}),
                               "rule": "Held-date intersections require exact game/PA identity proof. All56 held observations remain unchanged.",
                               "exactClearances": [r["frozenHoldIdentityProof"] for r in parsed if "frozenHoldIdentityProof" in r]},
            "sourceReferences": [dref, mref, prior_refs["cachedHistory"], prior_refs["certifiedManifest"],
                prior_refs["certifiedStarts"], prior_refs["reconciliation2025"], hold_ref]
                + [save(OUT / "history-build/code", Path(path).name, Path(path).read_bytes())
                   for path in (__file__, history.__file__, metadata.__file__, transport.__file__)]
                + [r["frozenHoldIdentityProof"] for r in parsed if "frozenHoldIdentityProof" in r],
            "startsArtifact": {"relativePath": "starts.parquet", "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload), "rows": len(slim)},
            "accountingBefore": before, "accountingAfter": after,
            "newRequests": after["requestAttempts"] - before["requestAttempts"],
            "newOriginalBytes": after["downloadedOriginalBytes"] - before["downloadedOriginalBytes"],
            "publicationAuthority": {"researchOnly": True, "wageringAuthority": False},
            "notes": ["No label-only outcome exports are covariates.", "Appearance counts are not start counts.",
                      "Original source clocks remain in linked source receipts; this projection is available only at its actual new clock.",
                      "The Sep12 target cannot be certified until refreshed enumeration after 2026-09-13T04:00:00Z."]}
        data = history.canonical_json_bytes(report)
        digest = hashlib.sha256(data).hexdigest()
        directory = HISTORY_ROOT / "objects/sha256" / digest
        history._write(directory / "starts.parquet", payload)
        history._write(directory / "manifest.json", data)
        manifest_ref = ref(directory / "manifest.json")
        cohort_pointer = HISTORY_ROOT / "cohorts" / DECLARATION_SHA / "current.json"
        atomic_state(cohort_pointer, manifest_ref)
        result = {"schemaVersion": "MLB_SURVIVAL_COHORT_HISTORY_BUILD_V1", "status": report["status"],
            "startedAtUtc": begun.isoformat(), "completedAtUtc": created, "declaration": dref,
            "manifestRef": manifest_ref, "historyPointer": str(cohort_pointer), "counts": counts,
            "enumerationPrefixThrough": prefix.isoformat(), "targetThrough": window["targetThrough"],
            "targetComplete": target_complete, "stoppedReason": stopped,
            "newRequests": report["newRequests"], "newOriginalBytes": report["newOriginalBytes"],
            "newCostUsd": after["costUsd"] - before["costUsd"], "accountingAfter": after,
            "globalHistoryPointerChanged": False, "priorStudyChanged": False, "modelFits": 0, "simulationRuns": 0}
        result_ref = save(OUT / "history-build", "history-build.json", result)
        atomic_state(OUT / "history-build/current.json", result_ref)
        return {**result, "result": result_ref}


def self_check():
    from unittest.mock import patch
    prefix = date(2026, 9, 11)
    regular = {"gamePk": 999001, "officialDate": "2026-09-10", "status": {"abstractGameState": "Final"}}
    assert metadata_gate({"gamePk": 999001, "gameDate": "2026-09-10"}, regular, prefix)[0] is None
    for pk, day in ((823343, "2026-09-10"), (999001, "2026-08-14"), (999001, "2026-08-27")):
        assert metadata_gate({"gamePk": pk, "gameDate": day}, None, prefix)[0]
    assert metadata_gate({"gamePk": 999001, "gameDate": "2026-09-10"}, {**regular, "resumedFromDate": "2026-08-20"}, prefix)[0].startswith("PROTECTED")
    with patch.object(transport, "_request", side_effect=AssertionError("PROTECTED_PAYLOAD_BOUNDARY_CROSSED")):
        for appearance, schedule in (({"gamePk": 823343, "gameDate": "2026-09-10"}, regular),
                ({"gamePk": 999001, "gameDate": "2026-08-14"}, regular),
                ({"gamePk": 999001, "gameDate": "2026-09-10"}, {**regular, "resumedFromDate": "2026-08-20"})):
            value, blocked = acquire_feed(appearance, schedule, prefix, allow_free_network=True)
            assert value is None and blocked["payloadRead"] is False
    w = metadata.coverage_window(date(2026, 9, 13), metadata.utc("2026-09-12T23:59:00Z"))
    assert w["enumerationPrefixThrough"] == "2026-09-11" and not w["targetDateClosed"]
    try:
        metadata_gate({"gamePk": 999001, "gameDate": "2026-09-12"}, regular, prefix)
    except ValueError:
        pass
    else:
        raise AssertionError("OPEN_TARGET_DAY_WAS_ACCEPTED")
    return {"status": "PASS", "checks": ["quarantine-before-feed", "inclusive-sealed-window", "protected-resumption", "closed-prefix"], "providerCalls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--declaration", type=Path, default=OUT / "declaration.json")
    parser.add_argument("--metadata-pointer", type=Path, default=OUT / "metadata-intake/current.json")
    parser.add_argument("--cached-history-pointer", type=Path, default=OUT / "cached-history/current.json")
    parser.add_argument("--output-root", type=Path, default=OUT)
    parser.add_argument("--allow-free-network", action="store_true", default=False)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(self_check() if args.self_check else build(args), indent=2))
