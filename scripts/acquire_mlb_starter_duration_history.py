"""Bounded, source-only intake for the first two-starter prospective pilot.

Only MLB StatsAPI's existing free public transport is used. Protected dates
receive server-projected identities/timing only, never game feeds or statistics.
This is acquisition evidence, not an eligibility/completeness certificate.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from server.sports_current_statcast.mlb_v18_current_sources import RIGHTS, SourceRequestTelemetry
from server.sports_current_statcast.mlb_v18_unattended import single_owner, atomic_state

INTAKE = ROOT / "outputs/mlb-starter-duration-paired-research-v1/intake"
PROTECTED_RAW_ROOT = INTAKE / "prospective-only-source-quarantine"
SCHEMA = "MLB_STARTER_DURATION_BOUNDED_SOURCE_INTAKE_V1"
MAX_REQUESTS, MAX_BYTES = 200, 500 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
PITCHERS = ("690279", "664285")
DECLARATION_SHA = "e73efabea4fa4423f02c46b2c27cdb21a54e5b967f3751a81abceca101a5223f"
PAIR_DECLARATION_SHA = "b3f6debf668aba1cafbe308489255772a593e9d03532d5b3097f101af32bd19b"
CURRENT_SNAPSHOT_SHA = "049dec78f0d8ec1c9ce34987fe847370470de298d66c1a997c267425782c9ae1"
CURRENT_SNAPSHOT = INTAKE / "inventory/sha256/1b70db9ce0b56eb0e4f04dbb2ee81220b4386f721c80808be09b347297ca5dee/current-game-pregame-snapshots.json"
LOG_FIELDS = "stats,splits,date,game,gamePk,gameType,season"
SCHEDULE_FIELDS = ("dates,date,games,gamePk,gameDate,officialDate,gameType,resumeDate,resumeGameDate,"
                   "resumedFrom,resumedFromDate,rescheduledFrom,rescheduledFromDate,status,"
                   "abstractGameState,detailedState,statusCode,codedGameState")


def starter_feed_fields(pitcher_id):
    """Minimum native-feed keys consumed by the frozen-history parser.

    One pitcher box line plus PA identity, ordering, counts, substitutions,
    runner attribution, completion clocks and score reconciliation. No tracking
    measurements or extraneous statistical families are requested.
    """
    pitcher = str(pitcher_id)
    if pitcher not in PITCHERS + ("687312", "695549"):
        raise ValueError("NARROW_STARTER_FEED_PITCHER_OUTSIDE_FIRST_PAIR")
    keys = ("gamePk,metaData,timeStamp,gameData,game,type,teams,home,away,sport,id,"
            "datetime,officialDate,originalDate,dateTime,resumeDate,resumeDateTime,resumeGameDate,"
            "resumedFrom,resumedFromDate,rescheduledFromDate,status,abstractGameState,detailedState,"
            "statusCode,codedGameState,venue,timeZone,liveData,boxscore,players,"
            f"ID{pitcher},stats,pitching,gamesStarted,battersFaced,outs,inningsPitched,pitchers,"
            "teamStats,batting,runs,linescore,plays,allPlays,about,atBatIndex,isTopInning,inning,"
            "isComplete,startTime,endTime,playEvents,index,details,eventType,isOut,player,"
            "count,balls,strikes,isPitch,matchup,pitcher,batter,result,homeScore,awayScore,"
            "runners,runner,movement,start,originBase,end")
    return ",".join(dict.fromkeys(keys.split(",")))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(blob):
    return hashlib.sha256(blob).hexdigest()


def _store(blob, suffix, *, object_root=None):
    digest = _sha(blob)
    root = Path(object_root) if object_root is not None else INTAKE
    if root.resolve() not in {INTAKE.resolve(), PROTECTED_RAW_ROOT.resolve()}:
        raise ValueError("SOURCE_OBJECT_NAMESPACE_NOT_AUTHORIZED")
    path = root / "objects/sha256" / (digest + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != blob:
            raise ValueError("IMMUTABLE_SOURCE_COLLISION")
    else:
        with path.open("xb") as handle:
            handle.write(blob)
    return {"path": str(path), "sha256": digest, "bytes": len(blob)}


def _load_ref(ref):
    path = Path(ref["path"]).resolve()
    if not path.is_relative_to(INTAKE.resolve()):
        raise ValueError("SOURCE_REFERENCE_OUTSIDE_INTAKE")
    blob = path.read_bytes()
    if len(blob) != ref["bytes"] or _sha(blob) != ref["sha256"]:
        raise ValueError("SOURCE_REFERENCE_MISMATCH")
    return json.loads(blob)


def _protected(value):
    return value is not None and "2026-08-14" <= str(value)[:10] <= "2026-08-27"


def _check_projection(payload, fields):
    allowed = set(fields.split(",")) | {"copyright"}
    def visit(value):
        if isinstance(value, dict):
            if set(value) - allowed:
                raise ValueError("SERVER_METADATA_PROJECTION_NOT_HONORED")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(payload)


def _project_native_starter_feed(payload, pitcher_id):
    """Drop StatsAPI's auto-expanded map/runner extras before any consumer use.

    The provider's original bytes remain quarantined. Unknown fields are never
    added to the accepted schema: only the predeclared parser whitelist survives.
    """
    allowed = set(starter_feed_fields(pitcher_id).split(",")) | {"copyright"}
    target = "ID" + str(pitcher_id)
    omitted = set()
    def project(value, path=()):
        if isinstance(value, dict):
            if path == ("gameData", "players"):
                omitted.add("unused_gameData_player_map")
                return {}
            if len(path) == 5 and path[:3] == ("liveData", "boxscore", "teams") and path[-1] == "players":
                if set(value) - {target}:
                    omitted.add("non_target_boxscore_player_records")
                return {target: project(value[target], path + (target,))} if target in value else {}
            result = {}
            for key in value:
                if key in allowed:
                    result[key] = project(value[key], path + (key,))
                else:
                    omitted.add(key)
            return result
        if isinstance(value, list):
            return [project(row, path + ("[]",)) for row in value]
        return value
    projected = project(payload)
    _check_projection(projected, starter_feed_fields(pitcher_id))
    return projected, {"schemaVersion": "MLB_STARTER_DURATION_MINIMAL_NATIVE_PROJECTION_V1",
        "fields": starter_feed_fields(pitcher_id), "pitcherMlbamId": str(pitcher_id),
        "omittedProviderAutoExpandedFieldNames": sorted(omitted),
        "unknownFieldsForwarded": False, "originalBytesPreservedInQuarantine": True,
        "providerLimitation": "Flat fields projection auto-expands dynamic player-map and runner-detail wrappers; these extras are discarded locally, not admitted to the consumer contract."}


def _recover_quarantined_request(url, *, cache_key, cache_scope, index, scope, authority):
    """Revalidate a recorded HTTP200 body locally; never repeat its request."""
    for started_path in sorted((INTAKE / "requests").glob("*.started.json")):
        started = json.loads(started_path.read_text(encoding="utf-8"))
        if started.get("cacheKey") != cache_key or started.get("url") != url:
            continue
        ended_path = started_path.with_name(started_path.name.replace(".started.json", ".completed.json"))
        if not ended_path.exists():
            continue
        ended = json.loads(ended_path.read_text(encoding="utf-8"))
        original_ref = ended.get("authorizedProspectiveQuarantinedSource")
        if (ended.get("httpStatus") != 200 or ended.get("error") != "ValueError:SERVER_METADATA_PROJECTION_NOT_HONORED"
                or not original_ref or not Path(original_ref["path"]).resolve().is_relative_to(PROTECTED_RAW_ROOT.resolve())):
            continue
        original = _load_ref(original_ref)
        projected, transform = _project_native_starter_feed(original, scope["pitcherMlbamId"])
        if (projected.get("gamePk") != int(scope["gamePk"])
                or projected.get("gameData", {}).get("datetime", {}).get("officialDate") != scope["gameDate"]):
            raise ValueError("RECOVERED_PROSPECTIVE_SOURCE_IDENTITY_MISMATCH")
        raw = _store(_bytes(projected), ".source.json", object_root=PROTECTED_RAW_ROOT)
        code_ref = _store(Path(__file__).read_bytes(), ".source-transform.py")
        available = _now()
        receipt = {"schemaVersion": SCHEMA, "url": url,
            "family": "AUTHORIZED_PROSPECTIVE_STARTER_HISTORY_ONLY", "cacheScope": cache_scope,
            "raw": raw, "originalRaw": original_ref, "transformation": transform,
            "transformationCode": code_ref, "requestStartedAt": started["startedAt"],
            "observedAt": ended["completedAt"], "originalTransportCompletedAt": ended["completedAt"],
            "originalSourceIngestedNoLaterThan": ended["completedAt"],
            "ingestedAt": available, "availableAsOf": available, "providerPublishedAt": None,
            "availabilityBasis": "ORIGINAL_RECORDED_TRANSPORT_COMPLETION_BOUND_PLUS_ACTUAL_LOCAL_PROJECTION_AVAILABILITY",
            "fieldsProjection": starter_feed_fields(scope["pitcherMlbamId"]), "rights": RIGHTS,
            "authorization": "JAMES_4414bc09_BOUNDED_FREE_SOURCE_INTAKE", "costUsd": 0, "paidProviderCalls": 0,
            "protectedDerivativeAuthority": authority["authorityRef"], "quarantineRef": authority["quarantineRef"],
            "authorizedTuple": dict(scope), "sourcePurpose": authority["purpose"],
            "sourceUse": "PROSPECTIVE_STARTER_HISTORY_ONLY", "protectedSourceDerivativePermission": True,
            "evaluationAllowed": False, "modelFitAllowed": False, "sealedEvaluationFilesRead": 0,
            "recoveredOriginalAttempt": started["attempt"], "recoveryNetworkRequests": 0,
            "originalFailurePreserved": True,
            "originalRequestReceipt": _store(_bytes({"started": started, "completed": ended}), ".recovered-original-request.json")}
        ref = _store(_bytes(receipt), ".receipt.json")
        index.parent.mkdir(parents=True, exist_ok=True)
        with index.open("xb") as handle:
            handle.write(_bytes(ref))
        return receipt, projected, True
    return None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # No invisible follow-up request can escape the shared budget.
        return None


def _accounting():
    attempts = []
    for path in sorted((INTAKE / "requests").glob("*.started.json")):
        start = json.loads(path.read_text(encoding="utf-8"))
        end = path.with_name(path.name.replace(".started.json", ".completed.json"))
        result = json.loads(end.read_text(encoding="utf-8")) if end.exists() else None
        attempts.append({**start, **(result or {}),
                         "chargedBytes": result["downloadedBytes"] if result else start["reservedBytes"]})
    return {"requestAttempts": len(attempts),
            "downloadedOriginalBytes": sum(a.get("downloadedBytes", 0) for a in attempts),
            "budgetAccountedBytes": sum(a["chargedBytes"] for a in attempts),
            "incompleteAttemptsReservedAtMaximum": sum("completedAt" not in a for a in attempts),
            "costUsd": 0, "paidProviderCalls": 0, "maxRequests": MAX_REQUESTS, "maxBytes": MAX_BYTES,
            "automaticRetries": 0, "redirectsFollowed": 0,
            "ratePolicy": "ONE_SEQUENTIAL_REQUEST_AT_LEAST_ONE_SECOND_APART_STOP_ON_429_NO_AUTOMATIC_RETRY",
            "providerPublishedNumericRateLimit": None}


def _request(url, *, family, cache_scope, projection=None, allow_free_network=False, protected_scope=None):
    protected_authority = None
    if family == "AUTHORIZED_PROSPECTIVE_STARTER_HISTORY_ONLY" and protected_scope is None:
        raise ValueError("PROTECTED_SOURCE_REQUIRES_EXACT_TUPLE_AUTHORITY")
    if protected_scope is not None:
        from server.sports_current_statcast.mlb_starter_duration_quarantine import assert_prospective_source_allowed
        protected_authority = assert_prospective_source_allowed(
            protected_scope["pitcherMlbamId"], protected_scope["gamePk"], protected_scope["gameDate"])
        expected_fields = starter_feed_fields(protected_scope["pitcherMlbamId"])
        expected_url = f"https://statsapi.mlb.com/api/v1.1/game/{int(protected_scope['gamePk'])}/feed/live?" + urlencode({"fields": expected_fields})
        if (url != expected_url or projection != expected_fields
                or family != "AUTHORIZED_PROSPECTIVE_STARTER_HISTORY_ONLY"):
            raise ValueError("PROTECTED_SOURCE_REQUEST_EXCEEDS_MINIMAL_THREE_GAME_SCOPE")
    key = _sha(_bytes({"url": url, "cacheScope": cache_scope}))
    index = INTAKE / "cache" / (key + ".json")
    if index.exists():
        receipt = _load_ref(json.loads(index.read_text(encoding="utf-8")))
        if receipt["url"] != url or receipt["cacheScope"] != cache_scope:
            raise ValueError("SOURCE_CACHE_KEY_MISMATCH")
        if protected_authority is not None and (
            receipt.get("protectedDerivativeAuthority") != protected_authority["authorityRef"]
            or receipt.get("quarantineRef") != protected_authority["quarantineRef"]
            or not Path(receipt["raw"]["path"]).resolve().is_relative_to(PROTECTED_RAW_ROOT.resolve())):
            raise ValueError("PROTECTED_SOURCE_CACHE_AUTHORITY_OR_QUARANTINE_MISMATCH")
        payload = _load_ref(receipt["raw"])
        if projection:
            _check_projection(payload, projection)
        return receipt, payload, True
    if protected_authority is not None:
        recovered = _recover_quarantined_request(url, cache_key=key, cache_scope=cache_scope,
            index=index, scope=protected_scope, authority=protected_authority)
        if recovered is not None:
            return recovered
    if not allow_free_network:
        raise ValueError("FREE_NETWORK_OPT_IN_REQUIRED_FOR_UNCACHED_SOURCE")
    request_dir = INTAKE / "requests"
    request_dir.mkdir(parents=True, exist_ok=True)
    previous = sorted(request_dir.glob("*.started.json"))
    if previous:
        last = json.loads(previous[-1].read_text(encoding="utf-8"))
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last["startedAt"])).total_seconds()
        if elapsed < 1:
            time.sleep(1 - elapsed)
    for path in previous:
        start = json.loads(path.read_text(encoding="utf-8"))
        if start["cacheKey"] != key:
            continue
        end = path.with_name(path.name.replace(".started.json", ".completed.json"))
        if not end.exists():
            raise ValueError("PRIOR_SOURCE_ATTEMPT_UNRESOLVED_NO_AUTOMATIC_RETRY")
        result = json.loads(end.read_text(encoding="utf-8"))
        if result["status"] != "COMPLETED":
            raise ValueError("PRIOR_SOURCE_ATTEMPT_FAILED_NO_AUTOMATIC_RETRY")
    budget = _accounting()
    reserve = min(MAX_RESPONSE_BYTES, MAX_BYTES - budget["budgetAccountedBytes"])
    if protected_authority is not None and protected_authority.get("maxNewRequests") is not None:
        # Supplemental authority is bounded cumulatively across reruns and
        # cache-scope changes. Failed/in-flight attempts consume its allowance.
        permitted_urls = {f"https://statsapi.mlb.com/api/v1.1/game/{int(g['gamePk'])}/feed/live?" +
                          urlencode({"fields": starter_feed_fields(g["pitcherMlbamId"])})
                          for g in protected_authority["allowedTuples"]}
        scoped_attempts, scoped_bytes = 0, 0
        for old_path in previous:
            old_start = json.loads(old_path.read_text(encoding="utf-8"))
            if old_start.get("url") not in permitted_urls:
                continue
            scoped_attempts += 1
            old_end = old_path.with_name(old_path.name.replace(".started.json", ".completed.json"))
            scoped_bytes += (json.loads(old_end.read_text(encoding="utf-8"))["downloadedBytes"]
                             if old_end.exists() else old_start["reservedBytes"])
            if old_start.get("url") == url:
                raise ValueError("AUTHORIZED_SOURCE_ALREADY_ATTEMPTED_REUSE_ITS_CACHE_SCOPE")
        reserve = min(reserve, protected_authority["maxNewOriginalBytes"] - scoped_bytes)
        if scoped_attempts >= protected_authority["maxNewRequests"] or reserve <= 0:
            raise ValueError("EXACT_SIX_SOURCE_AMENDMENT_CEILING_REACHED")
    if budget["requestAttempts"] >= MAX_REQUESTS or reserve <= 0:
        raise ValueError("ASSIGNMENT_SOURCE_CEILING_REACHED")
    attempt = budget["requestAttempts"] + 1
    start = {"attempt": attempt, "startedAt": _now(), "url": url, "family": family,
             "cacheKey": key, "reservedBytes": reserve, "costUsd": 0}
    if protected_authority is not None:
        start.update(protectedDerivativeAuthority=protected_authority["authorityRef"],
                     authorizedTuple=dict(protected_scope))
    started_path = request_dir / f"{attempt:04d}.started.json"
    with started_path.open("xb") as handle:
        handle.write(_bytes(start))
    downloaded, pieces, status_code, retry_after = 0, [], None, None
    error, quarantined = None, None
    telemetry = SourceRequestTelemetry()
    telemetry_id = telemetry.started(family)
    try:
        opener = build_opener(_NoRedirect())
        request = Request(url, headers={"User-Agent": "ASP-Model-Studio-Local-Research/1.0"})
        with opener.open(request, timeout=45) as response:
            status_code = response.status
            if status_code != 200:
                raise ValueError("MLB_SOURCE_STATUS_NOT_200")
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > reserve:
                raise ValueError("SOURCE_RESPONSE_EXCEEDS_REMAINING_BYTE_RESERVATION")
            while downloaded < reserve:
                chunk = response.read(min(65536, reserve - downloaded))
                if not chunk:
                    break
                pieces.append(chunk)
                downloaded += len(chunk)
            if downloaded == reserve:
                raise ValueError("SOURCE_RESPONSE_REACHED_BOUNDED_BYTE_LIMIT")
        blob = b"".join(pieces)
        if family == "SAFE_2025_METADATA_PROJECTION_PROBE":
            quarantined = _store(blob, ".safe-2025-transport.json")
        if protected_authority is not None:
            # Original source bytes are quarantined even if schema validation
            # fails; failure never makes them ordinary model-development data.
            quarantined = _store(blob, ".source.json", object_root=PROTECTED_RAW_ROOT)
        payload = json.loads(blob)
        transform = None
        if protected_authority is not None:
            payload, transform = _project_native_starter_feed(payload, protected_scope["pitcherMlbamId"])
        if projection:
            _check_projection(payload, projection)
        raw = (_store(_bytes(payload), ".source.json", object_root=PROTECTED_RAW_ROOT)
               if protected_authority is not None else _store(blob, ".source.json"))
        observed = _now()
        receipt = {"schemaVersion": SCHEMA, "url": url, "family": family, "cacheScope": cache_scope,
                   "raw": raw, "requestStartedAt": start["startedAt"], "observedAt": observed,
                   "ingestedAt": _now(), "availableAsOf": _now(), "providerPublishedAt": None,
                   "sourcePurpose": "CURRENT_STARTER_DURATION_HISTORY_ONLY",
                   "availabilityBasis": "ACTUAL_CURRENT_RETRIEVAL_NOT_HISTORICAL_PREGAME_VINTAGE",
                   "fieldsProjection": projection, "rights": RIGHTS,
                   "authorization": "JAMES_4414bc09_BOUNDED_FREE_SOURCE_INTAKE",
                   "protectedOutcomePermission": False, "costUsd": 0, "paidProviderCalls": 0}
        if protected_authority is not None:
            receipt.update(protectedDerivativeAuthority=protected_authority["authorityRef"],
                quarantineRef=protected_authority["quarantineRef"], authorizedTuple=dict(protected_scope),
                sourcePurpose=protected_authority["purpose"], sourceUse="PROSPECTIVE_STARTER_HISTORY_ONLY",
                protectedSourceDerivativePermission=True,
                protectedOutcomePermissionMeaning="NO_MODEL_EVALUATION_OR_RESULTS_COMPARISON",
                evaluationAllowed=False, modelFitAllowed=False, sealedEvaluationFilesRead=0)
            receipt.update(originalRaw=quarantined, transformation=transform,
                           transformationCode=_store(Path(__file__).read_bytes(), ".source-transform.py"))
        ref = _store(_bytes(receipt), ".receipt.json")
        index.parent.mkdir(parents=True, exist_ok=True)
        with index.open("xb") as handle:
            handle.write(_bytes(ref))
        return receipt, payload, False
    except Exception as caught:
        error = type(caught).__name__ + ":" + str(caught)[:300]
        if isinstance(caught, HTTPError):
            status_code, retry_after = caught.code, caught.headers.get("Retry-After")
        raise
    finally:
        telemetry.completed(telemetry_id, http_status=status_code, error_type=error)
        result = {"completedAt": _now(), "status": "FAILED" if error else "COMPLETED",
                  "downloadedBytes": downloaded, "httpStatus": status_code,
                  "retryAfter": retry_after, "error": error, "telemetry": telemetry.snapshot(),
                  "safe2025TransportEvidence": quarantined if family == "SAFE_2025_METADATA_PROJECTION_PROBE" else None,
                  "authorizedProspectiveQuarantinedSource": quarantined if protected_authority is not None else None}
        with started_path.with_name(started_path.name.replace(".started.json", ".completed.json")).open("xb") as handle:
            handle.write(_bytes(result))


def _verify_declaration():
    path = INTAKE / "source-use-declaration-v1.json"
    blob = path.read_bytes()
    if _sha(blob) != DECLARATION_SHA:
        raise ValueError("CURRENT_SOURCE_AUTHORITY_DECLARATION_MISMATCH")
    return {"path": str(path), "sha256": DECLARATION_SHA, "bytes": len(blob)}


def _safe_2025_probe(*, allow_free_network=False):
    """Hard-isolated one-URL Development probe: this cannot request2026."""
    _verify_declaration()
    url = "https://statsapi.mlb.com/api/v1/people/664285/stats?" + urlencode({
        "stats": "gameLog", "group": "pitching", "season": 2025, "gameType": "R", "fields": LOG_FIELDS})
    receipt, payload, reused = _request(url, family="SAFE_2025_METADATA_PROJECTION_PROBE",
        cache_scope="SAFE_PROJECTION_PROBE_V1", projection=LOG_FIELDS, allow_free_network=allow_free_network)
    if not payload.get("stats") or not any(block.get("splits") for block in payload["stats"]):
        raise ValueError("SAFE_PROJECTION_PROBE_DID_NOT_RETURN_KNOWN_2025_IDENTITIES")
    return {"status": "SAFE_2025_PROJECTION_VERIFIED", "receipt": receipt, "cached": reused,
            "rows": sum(len(block.get("splits", [])) for block in payload["stats"]), "accounting": _accounting()}


def probe_nonsealed_2025(*, allow_free_network=False):
    with single_owner(INTAKE / "intake.lock") as owned:
        if not owned:
            return {"status": "DEFERRED_INTAKE_LOCK", "accounting": _accounting()}
        return _safe_2025_probe(allow_free_network=allow_free_network)


def acquire_first_pitcher_identity(*, allow_free_network=False):
    """Debut/identity only; proves no numerical model or outcome information."""
    with single_owner(INTAKE / "intake.lock") as owned:
        if not owned:
            return {"status": "DEFERRED_INTAKE_LOCK", "accounting": _accounting()}
        _verify_declaration()
        fields = "people,id,fullName,mlbDebutDate"
        url = "https://statsapi.mlb.com/api/v1/people?" + urlencode({
            "personIds": ",".join(PITCHERS), "fields": fields})
        receipt, payload, reused = _request(url, family="CURRENT_PITCHER_DEBUT_IDENTITY_ONLY",
            cache_scope="FIRST_PAIR_IDENTITY_V1", projection=fields, allow_free_network=allow_free_network)
        people = payload.get("people", [])
        if {str(row.get("id")) for row in people} != set(PITCHERS):
            raise ValueError("PITCHER_DEBUT_IDENTITY_MISMATCH")
        result = {"schemaVersion": SCHEMA, "people": people, "receipt": receipt, "cached": reused,
                  "accounting": _accounting()}
        ref = _store(_bytes(result), ".first-pitcher-identity.json")
        return {"identityRef": ref, **result}


def enumerate_declared_slate_metadata(*, through="2026-09-10", allow_free_network=False):
    """At most26 additional open-slate pitcher identity projections, no feeds.

    This answers only whether permission-free history may exist. It does not
    certify the returned appearance enumeration as complete eligible starts.
    """
    if through != "2026-09-10":
        raise ValueError("METADATA_SCOPE_PINNED_TO_DECLARED_SEPTEMBER11_SLATE")
    with single_owner(INTAKE / "intake.lock") as owned:
        if not owned:
            return {"status": "DEFERRED_INTAKE_LOCK", "accounting": _accounting()}
        _verify_declaration()
        _safe_2025_probe(allow_free_network=allow_free_network)
        declaration_path = INTAKE.parent / "objects/sha256" / PAIR_DECLARATION_SHA / "declaration.json"
        decl_blob, capture_blob = declaration_path.read_bytes(), CURRENT_SNAPSHOT.read_bytes()
        if _sha(decl_blob) != PAIR_DECLARATION_SHA or _sha(capture_blob) != CURRENT_SNAPSHOT_SHA:
            raise ValueError("DECLARED_SLATE_OR_CURRENT_CAPTURE_CHANGED")
        declaration, capture = json.loads(decl_blob), json.loads(capture_blob)
        snapshots = {row["game"]["game_id"]: row for row in capture["snapshots"]}
        result = {"schemaVersion": "MLB_STARTER_DURATION_OPEN_SLATE_PROTECTED_METADATA_V1",
            "startedAt": _now(), "through": through,
            "declaration": {"path": str(declaration_path), "sha256": PAIR_DECLARATION_SHA, "bytes": len(decl_blob)},
            "currentCapture": {"path": str(CURRENT_SNAPSHOT), "sha256": CURRENT_SNAPSHOT_SHA, "bytes": len(capture_blob)},
            "games": [], "pitchers": [], "unresolved": [], "sealedOutcomePayloadsRead": 0,
            "sealedOutcomePayloadsRequested": 0, "gameFeedsRequested": 0}
        by_player = {}
        try:
            for game in sorted(declaration["games"], key=lambda value: (value["deadlineUtc"], value["gameId"])):
                if datetime.fromisoformat(game["deadlineUtc"]) <= datetime.now(timezone.utc):
                    continue
                snapshot = snapshots.get(game["gameId"])
                item = {"gameId": game["gameId"], "deadlineUtc": game["deadlineUtc"],
                        "teams": game["teams"], "starters": [], "reasons": []}
                if not snapshot or str(snapshot["game"]["source_game_id"]) != str(game["sourceGameId"]):
                    item["reasons"].append("CURRENT_GAME_MAPPING_UNAVAILABLE")
                    result["games"].append(item)
                    continue
                for side in sorted(snapshot["sides"], key=lambda value: value["side"]):
                    starter = side.get("starter") or {}
                    pitcher = str(starter.get("mlbamId") or "")
                    if not pitcher.isdigit():
                        item["reasons"].append(side["side"] + "_ANNOUNCED_STARTER_ID_UNAVAILABLE")
                        continue
                    if pitcher not in by_player:
                        if len(set(by_player) - set(PITCHERS)) >= 26 and pitcher not in PITCHERS:
                            raise ValueError("ADDITIONAL_METADATA_PITCHER_SCOPE_EXCEEDED")
                        url = "https://statsapi.mlb.com/api/v1/people/" + pitcher + "/stats?" + urlencode({
                            "stats": "gameLog", "group": "pitching", "season": 2026, "gameType": "R", "fields": LOG_FIELDS})
                        receipt, payload, reused = _request(url, family="PITCHER_APPEARANCE_IDENTITIES_ONLY",
                            cache_scope=through, projection=LOG_FIELDS, allow_free_network=allow_free_network)
                        rows = [row for block in payload.get("stats", []) for row in block.get("splits", [])]
                        identities = sorted({(str(row["date"])[:10], int(row["game"]["gamePk"]))
                                             for row in rows if "2026-01-01" <= str(row["date"])[:10] <= through})
                        protected = [{"gameDate": day, "gamePk": pk} for day, pk in identities if _protected(day)]
                        player = {"pitcherMlbamId": pitcher, "name": starter.get("name"), "receipt": receipt,
                                  "cached": reused, "appearanceIdentityCount": len(identities),
                                  "protectedAppearances": protected,
                                  "enumerationAvailable": bool(payload.get("stats")),
                                  "appearanceRole": "PITCHING_APPEARANCE_NOT_PROOF_OF_START"}
                        by_player[pitcher] = player
                        result["pitchers"].append(player)
                    player = by_player[pitcher]
                    item["starters"].append({"side": side["side"], "pitcherMlbamId": pitcher,
                        "name": starter.get("name"), "protectedAppearances": player["protectedAppearances"],
                        "enumerationAvailable": player["enumerationAvailable"]})
                    if player["protectedAppearances"]:
                        item["reasons"].append(side["side"] + "_PROTECTED_PITCHING_APPEARANCES_REQUIRE_DERIVATIVE_AUTHORITY_OR_PROVEN_EXCLUSION")
                    if not player["enumerationAvailable"]:
                        item["reasons"].append(side["side"] + "_APPEARANCE_ENUMERATION_UNAVAILABLE_NOT_ZERO")
                item["permissionFreeHistoryCandidate"] = len(item["starters"]) == 2 and not item["reasons"]
                result["games"].append(item)
            result["status"] = "METADATA_ONLY_ENUMERATION_COMPLETE"
        except Exception as error:
            result["status"] = "METADATA_ENUMERATION_STOPPED_FAIL_CLOSED"
            result["unresolved"].append({"reason": type(error).__name__ + ":" + str(error)[:400]})
        result["completedAt"] = _now()
        result["accounting"] = _accounting()
        result["permissionFreeHistoryCandidateGames"] = [row["gameId"] for row in result["games"] if row.get("permissionFreeHistoryCandidate")]
        ref = _store(_bytes(result), ".open-slate-metadata.json")
        atomic_state(INTAKE / "open-slate-metadata-latest.json", ref)
        return {"manifestRef": ref, **result}


def run_bounded_intake(*, pitcher_ids=PITCHERS, through="2026-09-10", allow_free_network=False):
    # A newly authorized/cached complete first-pair history must not be replaced
    # by its old intentionally incomplete predecessor during routine resume.
    if (INTAKE / "protected-source-authority.json").exists():
        if set(map(str, pitcher_ids)) != set(PITCHERS) or through != "2026-09-10":
            raise ValueError("THREE_GAME_AUTHORITY_DOES_NOT_CERTIFY_NEW_PITCHERS_OR_COVERAGE_THROUGH")
        return acquire_authorized_three_game_supplement(allow_free_network=allow_free_network)
    with single_owner(INTAKE / "intake.lock") as owned:
        if not owned:
            return {"status": "DEFERRED_INTAKE_LOCK", "accounting": _accounting()}
        return _run_bounded_intake(pitcher_ids=pitcher_ids, through=through, allow_free_network=allow_free_network)


def _intake_evidence(result):
    """Execution accounting is not a new observation or source identity."""
    evidence = json.loads(_bytes(result))
    for key in ("startedAt", "completedAt", "cachedSourcesReused", "accounting", "newRequests"):
        evidence.pop(key, None)
    probe = evidence.get("safe2025ProjectionProbe")
    if probe is not None:
        for key in ("cached", "accounting"):
            probe.pop(key, None)
    return evidence


def _stable_intake_manifest(result):
    """Reuse the earliest exactly compatible source manifest, even legacy ones.

    The code-pinned index records the current verifier, not a false claim that
    an old capture was created by new code. Original clocks and receipts remain
    untouched. A changed observation, disposition, declaration or code identity
    requires a new index; identical evidence still refers to its first capture.
    """
    evidence = _intake_evidence(result)
    evidence_sha = _sha(_bytes(evidence))
    identity = {"schemaVersion": "MLB_STARTER_DURATION_INTAKE_EVIDENCE_IDENTITY_V1",
                "sourceImplementationSha256": _sha(Path(__file__).read_bytes()),
                "sourceEvidenceSha256": evidence_sha}
    key = _sha(_bytes(identity))
    index_path = INTAKE / "evidence-indices" / (key + ".json")
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        manifest = _load_ref(index["manifest"])
        if index["identity"] != identity or _sha(_bytes(_intake_evidence(manifest))) != evidence_sha:
            raise ValueError("IMMUTABLE_INTAKE_EVIDENCE_INDEX_MISMATCH")
        return index["manifest"], manifest, True, identity
    matches = []
    for path in sorted((INTAKE / "objects/sha256").glob("*.intake-manifest.json")):
        ref = {"path": str(path), "sha256": path.name.split(".", 1)[0], "bytes": path.stat().st_size}
        manifest = _load_ref(ref)
        if _sha(_bytes(_intake_evidence(manifest))) == evidence_sha:
            matches.append((manifest.get("completedAt", manifest.get("startedAt", "")), ref, manifest))
    reused = bool(matches)
    if matches:
        _, ref, manifest = min(matches, key=lambda row: (row[0], row[1]["sha256"]))
    else:
        manifest = result
        ref = _store(_bytes(manifest), ".intake-manifest.json")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("xb") as handle:
        handle.write(_bytes({"identity": identity, "manifest": ref,
                             "verification": "EXACT_SOURCE_DESCRIPTORS_AND_DISPOSITIONS_WITH_ORIGINAL_CLOCKS"}))
    return ref, manifest, reused, identity


def acquire_authorized_three_game_supplement(*, allow_free_network=False):
    """Exactly three game/pitcher tuples; permanent whole-game OOT quarantine.

    No broad raw catalog is searched. The old independently validated metadata
    supplies each exact game ID/date, and only minimal native fields are read.
    This successor preserves the source-only predecessor and all old receipts.
    """
    from server.sports_current_statcast.mlb_starter_duration_quarantine import load_exception_authority, assert_prospective_source_allowed
    with single_owner(INTAKE / "intake.lock") as owned:
        if not owned:
            return {"status": "DEFERRED_INTAKE_LOCK", "accounting": _accounting()}
        authority = load_exception_authority()  # Must precede every protected cache/source read.
        old_sha = "d1d29d6ff210ca2793a2974fcab18563ce1c13ee847b40af444809cdf756a6e3"
        old_path = INTAKE / "objects/sha256" / (old_sha + ".intake-manifest.json")
        old_ref = {"path": str(old_path), "sha256": old_sha, "bytes": old_path.stat().st_size}
        original = _load_ref(old_ref)
        result = json.loads(_bytes(original))
        result.update(startedAt=_now(), predecessorIntake=old_ref,
            protectedDerivativeAuthority=authority["authorityRef"], quarantineRef=authority["quarantineRef"],
            sourceUse="PROSPECTIVE_STARTER_HISTORY_ONLY", protectedDerivativeResolutions=[],
            cachedSourcesReused=0, completedAt=None)
        result.pop("sealedOutcomePayloadsRead", None)
        result.pop("sealedOutcomePayloadsRequested", None)
        result["otherProtectedSourceGamesRead"] = 0
        result["retainedLocalFeedLookup"] = {
            "scope": "FILENAME_AND_DIRECTORY_METADATA_ONLY_NO_UNIDENTIFIED_PAYLOAD_OPENED",
            "directories": ["C:/Users/james/ai-sports-predictor/data/raw/mlb_stats_api/2026",
                            "C:/Users/james/ai-sports-predictor/data/raw/historical/mlb_stats_api/2026"],
            "exactGamePathMatches": [],
            "disposition": "OPAQUE_CAPTURE_FILENAMES_NO_VERIFIED_EXACT_THREE_GAME_PAYLOAD_MAP",
            "limitation": "Not a claim that equivalent historical bytes are absent; no broad raw catalog was opened."}
        allowed = sorted(authority["allowedTuples"], key=lambda row: (row["gameDate"], int(row["gamePk"])))
        unresolved_by_pk = {row.get("gamePk"): row for row in original["unresolved"]}
        try:
            for scoped in allowed:
                assert_prospective_source_allowed(scoped["pitcherMlbamId"], scoped["gamePk"], scoped["gameDate"])
                previous = unresolved_by_pk.get(int(scoped["gamePk"]))
                if (previous is None or previous["gameDate"] != scoped["gameDate"]
                        or str(scoped["pitcherMlbamId"]) not in previous["pitcherMlbamIds"]):
                    raise ValueError("AUTHORIZED_GAME_NOT_IN_PREVIOUS_EXACT_PROTECTED_ENUMERATION")
                fields = starter_feed_fields(scoped["pitcherMlbamId"])
                url = f"https://statsapi.mlb.com/api/v1.1/game/{int(scoped['gamePk'])}/feed/live?" + urlencode({"fields": fields})
                source, feed, reused = _request(url, family="AUTHORIZED_PROSPECTIVE_STARTER_HISTORY_ONLY",
                    cache_scope="THREE_GAME_PROSPECTIVE_DERIVATIVE_V1:" + authority["authorityRef"]["sha256"],
                    projection=fields, protected_scope=scoped, allow_free_network=allow_free_network)
                result["cachedSourcesReused"] += int(reused)
                if (int(feed.get("gamePk", -1)) != int(scoped["gamePk"])
                        or feed.get("gameData", {}).get("datetime", {}).get("officialDate") != scoped["gameDate"]):
                    raise ValueError("AUTHORIZED_MINIMAL_FEED_GAME_DATE_IDENTITY_MISMATCH")
                game = {key: value for key, value in previous.items() if key != "reason"}
                game.update(raw=source["raw"], receipt=source,
                    protectedDerivativeAuthority=authority["authorityRef"], quarantineRef=authority["quarantineRef"],
                    sourceUse="PROSPECTIVE_STARTER_HISTORY_ONLY", authorizedTuple=dict(scoped),
                    **{key: source[key] for key in ("observedAt", "availableAsOf", "ingestedAt")})
                result["games"].append(game)
                result["unresolved"] = [row for row in result["unresolved"] if row.get("gamePk") != int(scoped["gamePk"])]
                result["protectedDerivativeResolutions"].append({**scoped, "raw": source["raw"],
                    "protectedDerivativeAuthority": authority["authorityRef"], "quarantineRef": authority["quarantineRef"],
                    "disposition": "SOURCE_ACQUIRED_PENDING_FROZEN_ELIGIBILITY_RECONCILIATION"})
            result["games"].sort(key=lambda row: (row["gameDate"], row["gamePk"]))
            result["status"] = "NARROW_PROSPECTIVE_SOURCE_CAPTURE_COMPLETE_PENDING_ELIGIBILITY"
        except Exception as error:
            result["status"] = "NARROW_PROSPECTIVE_SOURCE_INTAKE_STOPPED_FAIL_CLOSED"
            result["unresolved"].append({"reason": type(error).__name__ + ":" + str(error)[:400]})
        result["completedAt"] = _now()
        result["accounting"] = _accounting()
        result["authorizedProtectedSourceGamesAcquired"] = len(result["protectedDerivativeResolutions"])
        # No sealed evaluation file is ever opened; these are separately acquired
        # and permanently quarantined source records under the new authority.
        result["sealedEvaluationPayloadsRead"] = 0
        ref, manifest, reused, identity = _stable_intake_manifest(result)
        run_ref = _store(_bytes({"schemaVersion": "MLB_STARTER_DURATION_INTAKE_EXECUTION_RECEIPT_V1",
            "startedAt": result["startedAt"], "completedAt": result["completedAt"], "manifest": ref,
            "evidenceIdentity": identity, "sourceManifestReused": reused,
            "cachedSourcesReused": result["cachedSourcesReused"], "accounting": result["accounting"]}), ".intake-run-receipt.json")
        atomic_state(INTAKE / "latest.json", ref)
        atomic_state(INTAKE / "authorized-three-game-latest.json", ref)
        return {**manifest, "manifestRef": ref, "runReceiptRef": run_ref,
                "sourceManifestReused": reused, "accounting": result["accounting"],
                "cachedSourcesReused": result["cachedSourcesReused"]}


def _run_bounded_intake(*, pitcher_ids=PITCHERS, through="2026-09-10", allow_free_network=False):
    pitchers = tuple(sorted({str(value) for value in pitcher_ids}))
    if set(pitchers) != set(PITCHERS):
        raise ValueError("INTAKE_BOUNDED_TO_FIRST_COL_DET_STARTERS")
    if not "2026-01-01" <= through < datetime.now(timezone.utc).date().isoformat():
        raise ValueError("HISTORY_THROUGH_MUST_BE_STRICTLY_PRIOR_2026_DATE")
    INTAKE.mkdir(parents=True, exist_ok=True)
    result = {"schemaVersion": SCHEMA, "startedAt": _now(), "through": through,
              "pitcherMlbamIds": list(pitchers), "enumeration": [], "games": [],
              "protectedAppearances": [], "unresolved": [], "cachedSourcesReused": 0,
              "sealedOutcomePayloadsRead": 0, "sealedOutcomePayloadsRequested": 0,
              "eligibilityCertification": "NOT_PERFORMED_SOURCE_INTAKE_ONLY"}
    try:
        result["sourceUseDeclaration"] = _verify_declaration()
        result["safe2025ProjectionProbe"] = _safe_2025_probe(allow_free_network=allow_free_network)
        candidates = {}
        for pitcher in pitchers:
            url = "https://statsapi.mlb.com/api/v1/people/" + pitcher + "/stats?" + urlencode({
                "stats": "gameLog", "group": "pitching", "season": 2026, "gameType": "R", "fields": LOG_FIELDS})
            receipt, payload, reused = _request(url, family="PITCHER_APPEARANCE_IDENTITIES_ONLY",
                cache_scope=through, projection=LOG_FIELDS, allow_free_network=allow_free_network)
            result["cachedSourcesReused"] += int(reused)
            rows = [row for block in payload.get("stats", []) for row in block.get("splits", [])]
            if not payload.get("stats"):
                raise ValueError("MISSING_PITCHING_ENUMERATION_BLOCK_NOT_PROOF_OF_ZERO_APPEARANCES")
            identities = []
            for row in rows:
                day, pk = str(row["date"])[:10], int(row["game"]["gamePk"])
                if not "2026-01-01" <= day <= through:
                    continue
                item = {"pitcherMlbamId": pitcher, "gamePk": pk, "gameDate": day}
                identities.append(item)
                existing = candidates.setdefault(pk, {"gamePk": pk, "gameDate": day, "pitcherMlbamIds": []})
                if existing["gameDate"] != day:
                    raise ValueError("ENUMERATION_GAME_DATE_CONFLICT")
                if pitcher not in existing["pitcherMlbamIds"]:
                    existing["pitcherMlbamIds"].append(pitcher)
                if _protected(day):
                    result["protectedAppearances"].append(item)
            result["enumeration"].append({"pitcherMlbamId": pitcher, "receipt": receipt,
                "appearanceIdentities": identities, "meaning": "PITCHING_APPEARANCES_NOT_DECLARED_STARTS",
                "completenessDisposition": "REQUIRES_START_AND_FROZEN_ELIGIBILITY_RECONCILIATION"})
        if candidates:
            url = "https://statsapi.mlb.com/api/v1/schedule?" + urlencode({"sportId": 1,
                "gamePks": ",".join(map(str, sorted(candidates))), "fields": SCHEDULE_FIELDS})
            receipt, payload, reused = _request(url, family="GAME_COMPLETION_TIMING_METADATA_ONLY",
                cache_scope=through, projection=SCHEDULE_FIELDS, allow_free_network=allow_free_network)
            result["scheduleMetadataReceipt"] = receipt
            result["cachedSourcesReused"] += int(reused)
            metadata = {int(game["gamePk"]): game for group in payload.get("dates", []) for game in group.get("games", [])}
            for pk, candidate in sorted(candidates.items(), key=lambda value: (value[1]["gameDate"], value[0])):
                game = metadata.get(pk)
                if not game:
                    result["unresolved"].append({**candidate, "reason": "SCHEDULE_IDENTITY_MISSING"})
                    continue
                candidate = {**candidate, "scheduleMetadata": game}
                dates = [candidate["gameDate"]] + [game.get(key) for key in (
                    "officialDate", "gameDate", "resumeDate", "resumeGameDate", "resumedFrom", "resumedFromDate")]
                if any(_protected(value) for value in dates):
                    result["unresolved"].append({**candidate, "reason": "PROTECTED_START_OR_COMPLETION_DERIVATIVE_NOT_AUTHORIZED"})
                    continue
                if str(game.get("officialDate", ""))[:10] != candidate["gameDate"]:
                    result["unresolved"].append({**candidate, "reason": "SOURCE_GAME_DATE_MISMATCH"})
                    continue
                if game.get("status", {}).get("detailedState") not in {"Final", "Completed Early"}:
                    result["unresolved"].append({**candidate, "reason": "NOT_VERIFIED_COMPLETED"})
                    continue
                url = f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live"
                source, feed, reused = _request(url, family="NONSEALED_FINAL_GAME_FEED", cache_scope="FINAL_2026_V1",
                    allow_free_network=allow_free_network)
                result["cachedSourcesReused"] += int(reused)
                if int(feed.get("gamePk", -1)) != pk or str(feed.get("gameData", {}).get("datetime", {}).get("officialDate", ""))[:10] != candidate["gameDate"]:
                    raise ValueError("FINAL_FEED_IDENTITY_OR_DATE_MISMATCH")
                result["games"].append({**candidate, "raw": source["raw"], "receipt": source,
                    **{key: source[key] for key in ("observedAt", "availableAsOf", "ingestedAt")}})
        result["status"] = "NONSEALED_CAPTURE_COMPLETE_WITH_UNRESOLVED_GAPS" if result["unresolved"] else "NONSEALED_CAPTURE_COMPLETE_PENDING_ELIGIBILITY"
    except Exception as error:
        result["status"] = "INTAKE_STOPPED_FAIL_CLOSED"
        result["unresolved"].append({"reason": type(error).__name__ + ":" + str(error)[:400]})
    finally:
        result["completedAt"] = _now()
        result["accounting"] = _accounting()
        ref, manifest, reused, identity = _stable_intake_manifest(result)
        run_receipt = {"schemaVersion": "MLB_STARTER_DURATION_INTAKE_EXECUTION_RECEIPT_V1",
            "startedAt": result["startedAt"], "completedAt": result["completedAt"],
            "manifest": ref, "evidenceIdentity": identity, "sourceManifestReused": reused,
            "cachedSourcesReused": result["cachedSourcesReused"], "accounting": result["accounting"]}
        run_ref = _store(_bytes(run_receipt), ".intake-run-receipt.json")
        atomic_state(INTAKE / "latest.json", ref)
    return {**manifest, "manifestRef": ref, "runReceiptRef": run_ref,
            "sourceManifestReused": reused, "accounting": result["accounting"],
            "cachedSourcesReused": result["cachedSourcesReused"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", default="2026-09-10")
    parser.add_argument("--allow-free-network", action="store_true")
    parser.add_argument("--probe-nonsealed-2025", action="store_true",
                        help="Hard-isolated single2025 identity-projection request; cannot request2026")
    parser.add_argument("--first-pitcher-identity-only", action="store_true")
    parser.add_argument("--slate-protected-metadata-only", action="store_true")
    parser.add_argument("--authorized-three-game-supplement", action="store_true")
    args = parser.parse_args()
    if sum((args.probe_nonsealed_2025, args.first_pitcher_identity_only, args.slate_protected_metadata_only, args.authorized_three_game_supplement)) > 1:
        raise ValueError("SELECT_ONLY_ONE_HARD_ISOLATED_REQUEST_MODE")
    result = (probe_nonsealed_2025(allow_free_network=args.allow_free_network) if args.probe_nonsealed_2025
              else acquire_first_pitcher_identity(allow_free_network=args.allow_free_network) if args.first_pitcher_identity_only
              else enumerate_declared_slate_metadata(through=args.through, allow_free_network=args.allow_free_network) if args.slate_protected_metadata_only
              else acquire_authorized_three_game_supplement(allow_free_network=args.allow_free_network) if args.authorized_three_game_supplement
              else run_bounded_intake(through=args.through, allow_free_network=args.allow_free_network))
    print(json.dumps({key: result.get(key) for key in ("status", "manifestRef", "accounting", "protectedAppearances", "unresolved")}, indent=2))


if __name__ == "__main__":
    main()
