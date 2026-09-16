"""Current-input seam for the frozen starter-duration HGB; no fits or network.

Missing source coverage is not the fitted no-prior-start branch. The latter is
permitted only when a complete eligible-start universe establishes count zero.
This module never substitutes an old 2024 summary for a current summary.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "MLB_STARTER_DURATION_CURRENT_INPUTS_V1"
HISTORY_SCHEMA = "MLB_STARTER_DURATION_COMPLETED_HISTORY_V1"
ELIGIBILITY_DEFINITION = "MLB_STARTER_SURVIVAL_RISK_V1"
BASE_SHA = "9d12bb87e31b77c4f088705dd15a713c0b29795fcd9e7e2d32aac4b41420fbc4"
BASE = ROOT / f"outputs/mlb-starter-survival-hierarchical-pa-v1/duration-data/sha256/{BASE_SHA}/manifest.json"
DEFAULT_HISTORY_POINTER = ROOT / "outputs/mlb-starter-duration-paired-research-v1/starter-history/current.json"
HISTORY_ROOT = DEFAULT_HISTORY_POINTER.parent
FEATURES = ("homePitcher", "calendarMonth", "priorStartCount", "priorStartBfMean", "daysRest", "historyMissing")


def _utc(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("SOURCE_TIMESTAMP_REQUIRES_TIMEZONE")
    return parsed.astimezone(timezone.utc)


def _reference(path, expected=None):
    path = Path(path).resolve()
    blob = path.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if expected and digest != expected:
        raise ValueError("HISTORY_ARTIFACT_CHECKSUM_MISMATCH")
    return {"path": str(path), "sha256": digest, "bytes": len(blob)}


def _protected_history_authorization(manifest):
    """Validate the manifest's registered exact grant before derived bytes."""
    count = manifest.get("protectedStartPayloadCount", 0)
    descriptors = manifest.get("protectedStartDescriptors") or []
    if isinstance(count, bool) or not isinstance(count, int) or count != len(descriptors):
        raise ValueError("PROTECTED_START_HISTORY_SCOPE_ACCOUNTING_MISMATCH")
    if count == 0 and not descriptors:
        return set()
    if count < 1:
        raise ValueError("PROTECTED_START_HISTORY_SCOPE_ACCOUNTING_MISMATCH")
    from server.sports_current_statcast.mlb_starter_duration_quarantine import assert_prospective_source_allowed, load_exception_authority
    authority_ref = manifest.get("protectedExceptionAuthority")
    if not isinstance(authority_ref, dict):
        raise ValueError("PROTECTED_START_HISTORY_AUTHORITY_OR_QUARANTINE_MISMATCH")
    authority = load_exception_authority(authority_ref)
    if (count > len(authority["allowedTuples"])
            or authority_ref != authority["authorityRef"]
            or manifest.get("wholeGameQuarantine") != authority["quarantineRef"]):
        raise ValueError("PROTECTED_START_HISTORY_AUTHORITY_OR_QUARANTINE_MISMATCH")
    allowed = set()
    scope = {(str(d["pitcherMlbamId"]), int(d["gamePk"]), d["gameDate"]) for d in authority["allowedTuples"]}
    for descriptor in descriptors:
        key = (str(descriptor["pitcherMlbamId"]), int(descriptor["gamePk"]), descriptor["gameDate"])
        if key not in scope:
            raise ValueError("PROTECTED_HISTORY_OUTSIDE_MANIFEST_SOURCE_GRANT")
        assert_prospective_source_allowed(*key, authority_ref=authority_ref)
        if key in allowed:
            raise ValueError("DUPLICATE_PROTECTED_START_IDENTITY")
        allowed.add(key)
    return allowed


def _protected_row_key(row):
    return (str(row["pitcherMlbamId"]), int(row["gamePk"]), row["gameDate"])


def _load_registered_input(path):
    """Consume an explicit immutable local history projection, never infer one."""
    path = Path(path).resolve()
    root = HISTORY_ROOT.resolve()
    if not path.is_relative_to(root):
        raise ValueError("HISTORY_POINTER_OUTSIDE_RESEARCH_NAMESPACE")
    pointer = json.loads(path.read_text(encoding="utf-8"))
    digest = str(pointer["sha256"])
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("HISTORY_MANIFEST_CONTENT_ADDRESS_INVALID")
    manifest_path = Path(pointer["path"]).resolve()
    expected = root / "objects/sha256" / digest / "manifest.json"
    if manifest_path != expected or not manifest_path.is_relative_to(root):
        raise ValueError("HISTORY_MANIFEST_OUTSIDE_CONTENT_ADDRESSED_NAMESPACE")
    manifest_ref = _reference(manifest_path, digest)
    if manifest_ref["bytes"] != pointer["bytes"]:
        raise ValueError("HISTORY_MANIFEST_BYTE_COUNT_MISMATCH")
    manifest = json.loads(Path(manifest_ref["path"]).read_text(encoding="utf-8"))
    if (manifest.get("schemaVersion") != HISTORY_SCHEMA
            or manifest.get("sourcePurpose") != "CURRENT_PREGAME_INPUTS_ONLY"
            or manifest.get("payloadRole") != "CURRENT_STARTER_DURATION_HISTORY_PROJECTION"
            or manifest.get("sealedEvaluationPayloadsRead") != 0):
        raise ValueError("HISTORY_SCHEMA_MISMATCH")
    # Earlier V18 permission is insufficient. The manifest must bind its exact
    # registered HGB source grant and corresponding permanent game quarantine.
    allowed_protected = _protected_history_authorization(manifest)
    descriptor = manifest["startsArtifact"]
    if descriptor.get("relativePath") != "starts.parquet":
        raise ValueError("HISTORY_PAYLOAD_REQUIRES_FIXED_RELATIVE_PATH")
    row_path = (manifest_path.parent / descriptor["relativePath"]).resolve()
    # Reject arbitrary paths before reading/hashing any Parquet bytes. This is
    # never a route to an original mixed Gold or sealed evaluation artifact.
    if row_path != manifest_path.with_name("starts.parquet") or not row_path.is_relative_to(root):
        raise ValueError("HISTORY_PAYLOAD_OUTSIDE_RESEARCH_MANIFEST_DIRECTORY")
    rows_ref = _reference(row_path, descriptor["sha256"])
    if rows_ref["bytes"] != descriptor["bytes"]:
        raise ValueError("HISTORY_ROWS_BYTE_COUNT_MISMATCH")
    records = pd.read_parquet(rows_ref["path"]).to_dict("records")
    if len(records) != descriptor["rows"]:
        raise ValueError("HISTORY_ROW_COUNT_MISMATCH")
    protected_rows = [r for r in records if "2026-08-14" <= r["gameDate"] <= "2026-08-27"]
    actual_protected = {_protected_row_key(r) for r in protected_rows}
    if len(protected_rows) != len(allowed_protected) or actual_protected != allowed_protected:
        raise ValueError("PROTECTED_HISTORY_ROWS_DIFFER_FROM_AUTHORIZED_DESCRIPTORS")
    manifest["sourceReferences"] = [manifest_ref, rows_ref, *manifest.get("sourceReferences", [])]
    return records, manifest


def build_current_duration_inputs(snapshot, *, as_of_utc, history_rows=None,
                                  history_authority=None, history_pointer=None):
    """Return supported fixed pregame fields, or exact per-starter skip reasons.

    An explicit history authority must prove each player's complete eligible-start
    coverage since the frozen 2023 foundation through the prior local date. Rows
    use the original ``startId/pitcherId/gameDate/eligible/totalBf`` contract plus
    completionDate and availableAsOf. ``playerIdentityMap`` binds current MLBAM
    IDs to those row IDs; names and fuzzy matching are never used. A complete
    empty history gives count0/meanNULL/restNULL/historyMissing=true exactly.
    ``bf`` is deliberately absent: the simulator supplies its supported BF>=1.
    """
    cutoff, start = _utc(as_of_utc), _utc(snapshot["game"]["starts_at"])
    result = {"schemaVersion": SCHEMA, "status": "UNSUPPORTED", "gameId": snapshot["game"]["game_id"],
              "asOfUtc": cutoff.isoformat(), "home": None, "away": None, "starterInputs": [],
              "sourceReferences": [], "missingReasons": [], "evidenceCutoff": None,
              "featureOrder": list(FEATURES), "historyDefinition": ELIGIBILITY_DEFINITION,
              "providerCalls": 0, "fits": 0}
    if cutoff >= start:
        result["missingReasons"] = [{"reason": "PREGAME_DEADLINE_PASSED"}]
        return result
    game_day = start.astimezone(ZoneInfo("America/New_York")).date()
    prior_day = game_day-timedelta(days=1)
    if date(2026, 8, 14) <= game_day <= date(2026, 8, 27):
        result["missingReasons"] = [{"reason": "FINAL_OOT_EVENT_FORBIDDEN"}]
        return result
    authority = history_authority
    if authority is None:
        pointer = Path(history_pointer) if history_pointer else DEFAULT_HISTORY_POINTER
        if pointer.exists():
            history_rows, authority = _load_registered_input(pointer)
        else:
            # The exact fitted history is known but stops in2024. It is evidence
            # of the feature definition, never a current-input fallback.
            result["sourceReferences"].append(_reference(BASE, BASE_SHA))
            authority, history_rows = {}, []
    authority = dict(authority)
    result["sourceReferences"].extend(authority.get("sourceReferences", []))
    records = list(history_rows or [])
    allowed_protected = _protected_history_authorization(authority)
    source_times = []
    definition_ok = (authority.get("schemaVersion") == HISTORY_SCHEMA
                     and authority.get("eligibilityDefinition") == ELIGIBILITY_DEFINITION
                     and authority.get("frozenEligibilityHoldPreserved") is True)
    if records and len({r["startId"] for r in records}) != len(records):
        raise ValueError("DUPLICATE_HISTORY_START_IDENTITY")
    identity_map = authority.get("playerIdentityMap", {})
    for side in snapshot.get("sides", []):
        label, starter = side["side"], side.get("starter") or {}
        mlbam = str(starter.get("mlbamId") or "")
        detail = {"side": label, "starterMlbamId": mlbam or None, "status": "UNSUPPORTED",
                  "values": None, "reasons": []}
        reasons = detail["reasons"]
        if label not in ("HOME", "AWAY"):
            reasons.append("STARTER_SIDE_INVALID")
        if sum(s.get("side") == label for s in snapshot.get("sides", [])) != 1:
            reasons.append("STARTER_SIDE_NOT_UNIQUE")
        if not mlbam:
            reasons.append("STARTER_IDENTITY_MISSING")
        try:
            observed = _utc(starter["observedAt"])
            available = _utc(starter["availableAsOf"])
            ingested = _utc(starter["ingestedAt"])
            detail["starterSourceTimestamps"] = {key: starter[key] for key in ("observedAt", "availableAsOf", "ingestedAt")}
            if not observed <= available <= cutoff or ingested > cutoff:
                reasons.append("STARTER_SOURCE_NOT_AVAILABLE_AT_CUTOFF")
            else:
                source_times.append(max(observed, available, ingested))
        except (KeyError, ValueError, TypeError):
            reasons.append("STARTER_SOURCE_TIMESTAMPS_MISSING")
        if not definition_ok:
            reasons.append("CURRENT_ELIGIBLE_START_HISTORY_AUTHORITY_UNAVAILABLE")
        pid = identity_map.get(mlbam)
        if definition_ok and not pid:
            reasons.append("STARTER_MLBAM_TO_HISTORY_IDENTITY_UNRESOLVED")
        coverage = authority.get("coverageByPlayer", {}).get(str(pid), {})
        if coverage.get("unresolvedProtectedAppearances"):
            reasons.append("PROTECTED_START_HISTORY_PROSPECTIVE_USE_NOT_AUTHORIZED")
        if definition_ok and pid:
            try:
                if (coverage.get("completeFrom") != "2023-01-01"
                        or date.fromisoformat(coverage["completeThrough"]) < prior_day
                        or coverage.get("allScheduledStartsAccountedFor") is not True
                        or coverage.get("eligibleStartDefinitionVerified") is not True):
                    reasons.append("CURRENT_START_HISTORY_COVERAGE_INCOMPLETE")
                observed = _utc(coverage["observedAt"])
                available = _utc(coverage["availableAsOf"])
                ingested = _utc(coverage["ingestedAt"])
                detail["historySourceTimestamps"] = {key: coverage[key] for key in ("observedAt", "availableAsOf", "ingestedAt")}
                if not observed <= available <= cutoff or ingested > cutoff:
                    reasons.append("HISTORY_AUTHORITY_NOT_AVAILABLE_AT_CUTOFF")
                else:
                    source_times.append(max(observed, available, ingested))
            except (KeyError, ValueError, TypeError):
                reasons.append("CURRENT_START_HISTORY_COVERAGE_UNPROVEN")
        chosen = []
        for row in records:
            if row.get("pitcherId") != pid:
                continue
            row_day = date.fromisoformat(row["gameDate"])
            if date(2026, 8, 14) <= row_day <= date(2026, 8, 27):
                try:
                    permitted = _protected_row_key(row) in allowed_protected and str(row["pitcherMlbamId"]) == mlbam
                except (KeyError, ValueError, TypeError, OverflowError):
                    permitted = False
                if not permitted:
                    reasons.append("PROTECTED_START_HISTORY_PROSPECTIVE_USE_NOT_AUTHORIZED")
                    continue
            if not row.get("eligible"):
                continue
            if not date(2023, 1, 1) <= row_day < game_day:
                continue  # Strict prior-date semantics, including no same-day update.
            try:
                completed = date.fromisoformat(row["completionDate"])
                available = _utc(row["availableAsOf"])
                observed, ingested = _utc(row["observedAt"]), _utc(row["ingestedAt"])
                if completed != row_day:
                    reasons.append("SUSPENDED_START_IN_ELIGIBLE_HISTORY")
                timing_valid = observed <= available <= cutoff and ingested <= cutoff
                if not timing_valid:
                    reasons.append("HISTORY_ROW_NOT_AVAILABLE_AT_CUTOFF")
                bf = row["totalBf"]
                if isinstance(bf, bool) or int(bf) != bf or bf < 1:
                    reasons.append("HISTORY_BF_UNSUPPORTED")
                chosen.append((row_day, int(bf), row["startId"]))
                if timing_valid:
                    source_times.append(max(observed, available, ingested))
            except (KeyError, ValueError, TypeError, OverflowError):
                reasons.append("HISTORY_ROW_AVAILABILITY_OR_BF_UNPROVEN")
        detail["reasons"] = sorted(set(reasons))
        if not detail["reasons"]:
            chosen.sort()
            count = len(chosen)
            values = {"homePitcher": int(label == "HOME"), "calendarMonth": game_day.month,
                      "priorStartCount": count, "priorStartBfMean": sum(r[1] for r in chosen)/count if count else None,
                      "daysRest": (game_day-chosen[-1][0]).days-1 if count else None, "historyMissing": count == 0}
            detail.update(status="SUPPORTED", values=values, priorStartIds=[r[2] for r in chosen],
                          latestHistoryCompletionDate=chosen[-1][0].isoformat() if count else None)
            result[label.lower()] = values
        result["starterInputs"].append(detail)
        result["missingReasons"].extend({"side": label, "starterMlbamId": mlbam or None, "reason": reason}
                                        for reason in detail["reasons"])
    if {s["side"] for s in result["starterInputs"]} != {"HOME", "AWAY"}:
        result["missingReasons"].append({"reason": "BOTH_STARTER_SIDES_REQUIRED"})
    if not result["missingReasons"] and result["home"] is not None and result["away"] is not None:
        result["status"] = "SUPPORTED"
    result["evidenceCutoff"] = max(source_times).isoformat() if source_times else None
    return result
