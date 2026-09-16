"""Bounded current V18 source loading, with a physically sealed date boundary.

This module does not fit, infer, register, or mutate AISP. Existing daily Silver
objects are opened only after their footer proves isolation to an explicitly
requested safe day. Optional acquisition uses free public MLB endpoints only,
requires explicit caller opt-in, and writes immutable Model Studio objects.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
from threading import Lock
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from server.sports_silver.canonical_ids import canonical_game_id
from server.sports_silver.current_statcast_pa import normalize_current_partition


STAGING = Path("C:/Users/james/asp-data-staging")
SOURCE_ROOT = (Path(__file__).resolve().parents[2] / "outputs/mlb-v18-current-state-pipeline-v1/sources").resolve()
ACCEPTED_SILVER_SHA = "fcfb95724f2cc44ae45555897365497c538f5ea6303fe041dd4afa9697c62d2a"
SEALED_START, SEALED_END = date(2026, 8, 14), date(2026, 8, 27)
POST_SEALED_START = date(2026, 8, 28)
OPERATIONAL_PURPOSE = "CURRENT_PREGAME_INPUTS_ONLY"
OPERATIONAL_AUTHORIZATION = "JAMES_2026_09_10_NEW_FINALIZED_SOURCE_HISTORY_EXCEPTION_V1"
OPERATIONAL_AUTHORIZED_AFTER = "2026-09-10T16:55:00+00:00"
RIGHTS = {
    "allowedUse": "LOCAL_PRIVATE_MODEL_DEVELOPMENT",
    "statcastStatus": "GOVERNED_LOCAL_RESEARCH_ONLY",
    "attributionRequired": True, "commercialRightsReviewRequired": True,
    "publicRawRedistributionAllowed": False,
}


class CurrentSourceError(ValueError):
    pass


class SourceRequestTelemetry:
    """Thread-safe accounting at the existing public urlopen invocation boundary.

    Counts attempted calls, including transport/read failures, rather than stored
    captures. No URLs, response data, or exception messages are copied into this
    operational summary. urllib's internal redirects are not separate invocations.
    """

    def __init__(self):
        self._lock = Lock()
        self._attempts = []

    def started(self, family: str) -> int:
        with self._lock:
            attempt_id = len(self._attempts)
            self._attempts.append({
                "attemptId": attempt_id + 1, "family": family,
                "startedAt": datetime.now(timezone.utc).isoformat(),
                "completedAt": None, "status": "STARTED", "httpStatus": None,
                "errorType": None, "sourceAccess": "FREE_PUBLIC_SOURCE",
                "paidProviderCalls": 0, "sourceCostUsd": 0,
            })
            return attempt_id

    def completed(self, attempt_id: int, *, http_status=None, error_type=None):
        with self._lock:
            self._attempts[attempt_id].update(
                completedAt=datetime.now(timezone.utc).isoformat(),
                status="FAILED" if error_type else "COMPLETED", httpStatus=http_status,
                errorType=error_type,
            )

    def snapshot(self) -> dict:
        with self._lock:
            attempts = [dict(attempt) for attempt in self._attempts]
        families = {}
        for family in ("SCHEDULE", "STATCAST", "SCHEDULE_IDENTITIES_ONLY", "CURRENT_PLAYER_IDENTITY"):
            selected = [attempt for attempt in attempts if attempt["family"] == family]
            families[family] = {
                "requestAttemptCount": len(selected),
                "completedRequestCount": sum(a["status"] == "COMPLETED" for a in selected),
                "failedRequestCount": sum(a["status"] == "FAILED" for a in selected),
                "inFlightRequestCount": sum(a["status"] == "STARTED" for a in selected),
            }
        return {
            "schemaVersion": "MLB_V18_PUBLIC_SOURCE_REQUEST_TELEMETRY_V1",
            "measurementBoundary": "URLOPEN_INVOCATIONS_INCLUDING_FAILURES_EXCLUDING_INTERNAL_REDIRECT_HOPS",
            "requestAttemptCount": len(attempts),
            "completedRequestCount": sum(a["status"] == "COMPLETED" for a in attempts),
            "failedRequestCount": sum(a["status"] == "FAILED" for a in attempts),
            "inFlightRequestCount": sum(a["status"] == "STARTED" for a in attempts),
            "byFamily": families, "attempts": attempts,
            "sourceAccess": "FREE_PUBLIC_SOURCE", "paidProviderCalls": 0, "sourceCostUsd": 0,
            "automaticRetriesAdded": 0,
        }


@contextmanager
def _tracked_source_response(request, *, family: str, timeout: int,
                             request_telemetry: SourceRequestTelemetry | None):
    # The counter advances immediately before the one existing urlopen call.
    # Date validation, cached reuse, and no-network previews never reach here.
    attempt_id = request_telemetry.started(family) if request_telemetry is not None else None
    http_status = None
    try:
        with urlopen(request, timeout=timeout) as response:
            http_status = getattr(response, "status", None)
            yield response
    except BaseException as error:
        if request_telemetry is not None:
            request_telemetry.completed(attempt_id, http_status=getattr(error, "code", http_status),
                                        error_type=type(error).__name__)
        raise
    else:
        if request_telemetry is not None:
            request_telemetry.completed(attempt_id, http_status=http_status)


@dataclass
class CurrentHistory:
    pa_history: pd.DataFrame
    pitches: pd.DataFrame
    games: list[dict[str, Any]]
    authority: dict[str, Any]


@dataclass(frozen=True)
class VerifiedOperationalHistory:
    """Capability issued only after new operational receipts are authenticated."""
    purpose: str
    authorization: str
    receipt_days: tuple[tuple[str, str], ...]
    latest_ingested_at: str


def operational_capture_day(value: str, *, purpose: str | None = None,
                            before: str | date | None = None) -> str:
    day = date.fromisoformat(value)
    if SEALED_START <= day <= SEALED_END and purpose == OPERATIONAL_PURPOSE:
        if before is not None and day >= (before if isinstance(before, date) else date.fromisoformat(before)):
            raise CurrentSourceError("Target-date or future operational history is forbidden")
        return value
    return safe_day(value, before=before)


def authenticate_operational_receipt(receipt: Mapping) -> bool:
    """Authenticate a newly captured source; never grant existing OOT paths access."""
    day = date.fromisoformat(str(receipt["day"]))
    if not SEALED_START <= day <= SEALED_END:
        return False
    descriptor = receipt.get("receipt", {})
    path = Path(descriptor.get("path", "")).resolve()
    if not path.is_relative_to((SOURCE_ROOT / "objects/sha256").resolve()) or path.suffix != ".json":
        raise CurrentSourceError("Operational exception cannot open an evaluation or legacy artifact")
    expected = descriptor.get("sha256")
    if not expected or path.name != expected + ".receipt.json":
        raise CurrentSourceError("Operational receipt is not content addressed")
    original = _verified_json(path, expected)
    if (original.get("purpose") != OPERATIONAL_PURPOSE
        or original.get("authorization") != OPERATIONAL_AUTHORIZATION
        or original.get("day") != str(receipt["day"])
        or original.get("raw") != receipt.get("raw")
        or original.get("family") != receipt.get("family")
        or _clock(original["requestStartedAt"]) < _clock(OPERATIONAL_AUTHORIZED_AFTER)):
        raise CurrentSourceError("New operational source authorization/provenance is invalid")
    raw = Path(original["raw"]["path"]).resolve()
    if not raw.is_relative_to((SOURCE_ROOT / "objects/sha256").resolve()):
        raise CurrentSourceError("Operational source cannot alias evaluation artifacts")
    return True


def verify_operational_source_rows(frame: pd.DataFrame, history_authority: Mapping, *, as_of_utc: Any) -> bool:
    """Pure capability/provenance check used by the feature boundary, no file reads."""
    dates = frame["gameDate"].astype(str).str[:10]
    protected = frame[dates.between(SEALED_START.isoformat(), SEALED_END.isoformat())]
    if protected.empty:
        return True
    capability = history_authority.get("_operationalSourceCapability")
    if not isinstance(capability, VerifiedOperationalHistory) or capability.purpose != OPERATIONAL_PURPOSE:
        raise CurrentSourceError("Protected dates require authenticated NEW operational source history")
    if capability.authorization != OPERATIONAL_AUTHORIZATION or _clock(capability.latest_ingested_at) > _clock(as_of_utc):
        raise CurrentSourceError("Operational source purpose or pregame cutoff is invalid")
    allowed = set(capability.receipt_days)
    if "sourceIdentity" not in protected or "sourcePurpose" not in protected:
        raise CurrentSourceError("Operational row lacks exact source provenance")
    if not protected.sourcePurpose.eq(OPERATIONAL_PURPOSE).all() or any(
        (str(row.sourceIdentity), str(row.gameDate)[:10]) not in allowed for row in protected.itertuples()):
        raise CurrentSourceError("Protected row is not from the verified new operational capture")
    return True


def _clock(value: str | datetime) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise CurrentSourceError("A source clock cannot be timezone-naive")
    return result.astimezone(timezone.utc)


def safe_day(value: str | date, *, before: str | date | None = None) -> str:
    day = value if isinstance(value, date) else date.fromisoformat(value)
    if day.year not in (2025, 2026) or SEALED_START <= day <= SEALED_END:
        raise CurrentSourceError(f"SOURCE_DATE_NOT_AUTHORIZED_OR_FINAL_OOT_SEALED: {day}")
    if before is not None and day >= (before if isinstance(before, date) else date.fromisoformat(before)):
        raise CurrentSourceError("Target-date, later same-day, and future source history are not permitted")
    return day.isoformat()


def _bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _verified_json(path: Path, expected_sha: str | None = None) -> dict:
    payload = path.read_bytes()
    if expected_sha is not None and _sha(payload) != expected_sha:
        raise CurrentSourceError(f"Source manifest checksum mismatch: {path}")
    return json.loads(payload)


def inventory_local_sources(staging_root: Path = STAGING) -> dict[str, Any]:
    """Inspect only source manifests and file names; never hash raw/OOT payloads."""
    root = Path(staging_root)
    bronze_path = root / "mlb-current-statcast-bronze-v1/manifests/bronze-manifest.json"
    bronze = _verified_json(bronze_path)
    partitions = list(bronze.get("partitions", []))
    yearly = {}
    for year in (2025, 2026):
        selected = [r for r in partitions if int(r.get("year", 0)) == year]
        days = sorted(r["query"]["date"] for r in selected if r.get("query", {}).get("date"))
        safe = [d for d in days if not SEALED_START.isoformat() <= d <= SEALED_END.isoformat()]
        yearly[str(year)] = {"partitionCount": len(selected), "firstDate": min(days, default=None),
                             "lastDate": max(days, default=None), "safePartitionDates": safe,
                             "latestRecordedRetrieval": max((r.get("retrievalUtc", "") for r in selected), default=None)}
    recent = [r for r in partitions if str(r.get("query", {}).get("date", "")) >= POST_SEALED_START.isoformat()]
    return {
        "schemaVersion": "MLB_V18_CURRENT_LOCAL_SOURCE_INVENTORY_V1",
        "bronzeManifestPath": str(bronze_path), "bronzeManifestSha256": _sha(bronze_path.read_bytes()),
        "yearly": yearly, "postSealedDailyPartitions": len(recent),
        "safeAnnualPriorSource": "FROZEN_FD1_PLAYER_PRIOR_2021_TO_2025_VIA_gold._load_player_priors",
        "safePlayerIdentitySource": "VERIFIED_SILVER_DIM_PLAYER_MLBAM_TO_CHADWICK_CANONICAL",
        "lastCompletedSyncReceipt": str(Path(__file__).resolve().parents[2] / ".runtime/asp-model-studio/current-statcast-sync/latest-success.json"),
        "sealedPayloadsRead": 0, "rights": RIGHTS,
    }


def load_frozen_annual_priors(*, as_of_utc: str | datetime, target_season: int = 2026,
                             exchange_root: Path = Path("C:/Users/james/asp-model-exchange"),
                             staging_root: Path = STAGING) -> tuple[list[dict], dict]:
    """Load exact accepted FD1 prior facts, not reconstructed Statcast annuals.

    The existing verifier selects only player_prior families through2025 before
    opening files. The package publication clock is preserved separately from
    this current adapter ingestion; missing old local-ingestion clocks are not
    represented as historically known. No event or Final OOT payload is opened.
    """
    from .gold import FD1_MANIFEST_SHA, _load_dim_player, _load_player_priors
    as_of = _clock(as_of_utc)
    if target_season != 2026:
        raise CurrentSourceError("This current frozen-prior adapter is authorized for2026 only")
    table, source = _load_player_priors(Path(exchange_root))
    canonical_to_chadwick, identity = _load_dim_player(Path(staging_root) / "mlb-silver-v1")
    by_chadwick = {}
    for canonical, chadwick in canonical_to_chadwick.items():
        if chadwick in by_chadwick and by_chadwick[chadwick] != canonical:
            raise CurrentSourceError("Ambiguous exact FD1-to-Silver player identity")
        by_chadwick[chadwick] = canonical
    package = Path(exchange_root) / "datasets/mlb-fd1" / f"sha256-{FD1_MANIFEST_SHA}"
    manifest = _verified_json(package / "sports-dataset-manifest.json")
    published = _clock(manifest["published_at"])
    if published > as_of:
        raise CurrentSourceError("Frozen annual-prior package was not published at cutoff")
    # Freeze the first current adapter registration. Re-reading identical priors
    # does not create a fictitiously refreshed source/ingestion timestamp.
    registration_key = _sha(_bytes({"adapter": "MLB_V18_FROZEN_FD1_ANNUAL_PRIOR_ADAPTER_V1",
        "fd1ManifestSha256": FD1_MANIFEST_SHA, "identityManifestSha256": identity["publicationManifestSha256"]}))
    registration_path = SOURCE_ROOT / "registrations" / f"{registration_key}.json"
    registration_path.parent.mkdir(parents=True, exist_ok=True)
    if not registration_path.exists():
        registration = {"registrationKey": registration_key, "fd1ManifestSha256": FD1_MANIFEST_SHA,
                        "adapterFirstObservedAt": as_of.isoformat(), "sourcePublishedAt": published.isoformat(),
                        "historicalLocalIngestedAt": None}
        try:
            with registration_path.open("xb") as handle:
                handle.write(_bytes(registration))
        except FileExistsError:
            pass
    registration = _verified_json(registration_path)
    if registration.get("registrationKey") != registration_key or registration.get("fd1ManifestSha256") != FD1_MANIFEST_SHA:
        raise CurrentSourceError("Immutable frozen-prior adapter registration differs")
    ingestion = _clock(registration["adapterFirstObservedAt"])
    if ingestion > as_of:
        raise CurrentSourceError("Frozen-prior adapter was first registered after the requested cutoff")
    rows, excluded = [], Counter()
    for row in table.to_pylist():
        if row["domain"] not in {"BATTING", "PITCHING"}:
            excluded["OTHER_DOMAIN"] += 1
            continue
        if row["identity_resolution_status"] != "EXACT" or row["canonical_player_id"] not in by_chadwick:
            excluded["IDENTITY_MAPPING_UNAVAILABLE"] += 1
            continue
        if int(row["season"]) >= target_season or int(row["eligible_from_season"]) > target_season or row["same_season_predictor_eligible"]:
            excluded["PRIOR_SEASON_INELIGIBLE"] += 1
            continue
        metrics = json.loads(row["metrics_json"])
        rows.append({"canonicalPlayerId": by_chadwick[row["canonical_player_id"]],
                     "fd1CanonicalPlayerId": row["canonical_player_id"], "domain": row["domain"],
                     "season": int(row["season"]), "eligibleFromSeason": int(row["eligible_from_season"]),
                     "metrics": metrics, "sourceIdentity": FD1_MANIFEST_SHA,
                     "observedAt": published.isoformat(), "availableAsOf": published.isoformat(),
                     "publishedAt": published.isoformat(), "ingestedAt": ingestion.isoformat(),
                     "historicalLocalIngestedAt": None,
                     "availabilityBasis": "FROZEN_FD1_PACKAGE_PUBLICATION_WITH_CURRENT_ADAPTER_INGESTION"})
    authority = {"schemaVersion": "MLB_V18_FROZEN_FD1_ANNUAL_PRIOR_ADAPTER_V1", **source,
                 "sourceIdentity": FD1_MANIFEST_SHA, "targetSeason": target_season,
                 "normalizedPriorRows": len(rows), "countsByDomainSeason": dict(Counter(f'{r["domain"]}/{r["season"]}' for r in rows)),
                 "excluded": dict(excluded), "identityAuthority": identity,
                 "observedAt": published.isoformat(), "availableAsOf": published.isoformat(),
                 "ingestedAt": ingestion.isoformat(), "publishedAt": published.isoformat(),
                 "adapterRegistrationPath": str(registration_path),
                 "adapterRegistrationSha256": _sha(registration_path.read_bytes()),
                 "frozenPriorFamilyComplete": True,
                 "completePriorDomainPopulation": ["BATTING", "PITCHING"],
                 "absenceMeaning": "NO_ELIGIBLE_ROW_IN_COMPLETE_FROZEN_FD1_2021_TO_2025_AUTHORITY_NOT_PROOF_OF_NO_CAREER_HISTORY",
                 "selectionRule": "EXACT_FROZEN_GOLD_PRIOR_LOOKUP_LATEST_ELIGIBLE_DOMAIN_SEASON_BEFORE_TARGET",
                 "knownZeroPreserved": True, "metricsRecalculated": False,
                 "sourceRightsIds": manifest["source_rights_ids"], "rights": RIGHTS,
                 "sealedEventPayloadsRead": 0}
    return rows, authority


def _read_isolated_object(root: Path, descriptor: Mapping[str, Any], day: str) -> pd.DataFrame:
    safe_day(day)
    path = (root / str(descriptor["relativePath"])).resolve()
    if not path.is_relative_to(root.resolve()):
        raise CurrentSourceError("Source object escapes its governed source root")
    parquet = pq.ParquetFile(path)
    index = parquet.schema_arrow.names.index("gameDate")
    for group in range(parquet.num_row_groups):
        stats = parquet.metadata.row_group(group).column(index).statistics
        if stats is None or not stats.has_min_max or str(stats.min) != day or str(stats.max) != day:
            raise CurrentSourceError("MIXED_OR_UNPROVEN_SOURCE_ROW_GROUP: no payload opened or hashed")
    # Only after the physical row-group boundary is established may payloads be hashed/read.
    blob = path.read_bytes()
    if len(blob) != descriptor["byteCount"] or _sha(blob) != descriptor["sha256"]:
        raise CurrentSourceError("Isolated source object checksum mismatch")
    frame = parquet.read().to_pandas()
    if not frame.empty and not frame["gameDate"].astype(str).eq(day).all():
        raise CurrentSourceError("Date-isolated source object failed its content boundary")
    return frame


def _history_authority(pa_frame: pd.DataFrame, pitch_frame: pd.DataFrame, sources: list[dict],
                       *, requested_dates: Sequence[str], missing_dates: Sequence[str], as_of: datetime) -> dict:
    safe_dates = sorted(set(requested_dates) - set(missing_dates))
    post = pa_frame[pa_frame["gameDate"].astype(str).ge(POST_SEALED_START.isoformat())] if not pa_frame.empty else pa_frame
    by_batter = dict(Counter(post["batterCanonicalPlayerId"].astype(str))) if not post.empty else {}
    by_pitcher = dict(Counter(post["pitcherCanonicalPlayerId"].astype(str))) if not post.empty else {}
    contiguous = bool(safe_dates) and not missing_dates and all(
        date.fromisoformat(b) - date.fromisoformat(a) == timedelta(days=1) for a, b in zip(safe_dates, safe_dates[1:]))
    clocks = {name: max((s[name] for s in sources if s.get(name)), default=None)
              for name in ("observedAt", "availableAsOf", "ingestedAt", "completionConfirmedAt")}
    return {
        "schemaVersion": "MLB_V18_CURRENT_COMPLETED_HISTORY_AUTHORITY_V1",
        "sourceIdentity": _sha(_bytes(sources)), "asOfUtc": as_of.isoformat(),
        "completeFrom": min(safe_dates, default=None), "completeThrough": max(safe_dates, default=None),
        "contiguousRequestedDatesComplete": contiguous, "allHistoryComplete": False,
        "missingDates": sorted(missing_dates), "requestedDates": list(requested_dates),
        "sealedGap": {"from": SEALED_START.isoformat(), "through": SEALED_END.isoformat(), "payloadsRead": 0},
        "postGapBatterPaCounts": by_batter, "postGapPitcherBfCounts": by_pitcher,
        "cumulativeExposure": {},
        "limitations": ["Observed post-gap counts are not full-history cumulative exposure.",
                        "A rolling window crossing the sealed interval remains incomplete; missing evidence is not rookie/no-history.",
                        "Current source reconstruction is not historical publication-vintage evidence."],
        "acceptedPlateAppearances": len(pa_frame), "acceptedPitches": len(pitch_frame),
        "sources": sources, **clocks, "rights": RIGHTS,
    }


def load_existing_daily_history(days: Sequence[str], *, as_of_utc: str | datetime,
                                staging_root: Path = STAGING) -> CurrentHistory:
    """Load specifically requested safe daily facts, never a mixed yearly file.

    Existing immutable normalization receipts prove FINAL game membership, but
    do not contain the original schedule observation timestamp. Therefore this
    read is expressly a current reconstruction; caller's observation clock is
    not represented as the original historical source-publication time.
    """
    as_of = _clock(as_of_utc)
    days = sorted({safe_day(day, before=as_of.date()) for day in days})
    root = Path(staging_root) / "mlb-current-statcast-silver-v1"
    manifest_path = root / "publications/sha256" / ACCEPTED_SILVER_SHA / "manifest.json"
    manifest = _verified_json(manifest_path, ACCEPTED_SILVER_SHA)
    by_date = {r["partitionDate"]: r for r in manifest["partitions"]}
    pas, pitches, sources, missing = [], [], [], []
    for day in days:
        receipt = by_date.get(day)
        if receipt is None or receipt.get("sourceStatus") not in {"COMPLETE", "COMPLETE_EMPTY"}:
            missing.append(day)
            continue
        source_cutoff = _clock(receipt["request"]["sourceCutoff"])
        if source_cutoff > as_of:
            missing.append(day)
            continue
        source = {"sourceIdentity": receipt["requestSha256"], "gameDate": day,
                  "observedAt": source_cutoff.isoformat(), "availableAsOf": as_of.isoformat(),
                  "ingestedAt": as_of.isoformat(), "completionConfirmedAt": as_of.isoformat(),
                  "originalSourceRetrievedAt": source_cutoff.isoformat(),
                  "availabilityBasis": "CURRENT_RECONSTRUCTION_OF_PREVIOUSLY_FINAL_NORMALIZED_SOURCE_NOT_HISTORICAL_VINTAGE",
                  "finalGamePks": receipt["request"]["finalGamePks"],
                  "knownRejectedPlateAppearances": receipt["counts"]["rejectedPlateAppearances"],
                  "sourceManifestSha256": ACCEPTED_SILVER_SHA}
        sources.append(source)
        for family, destination in (("plate_appearance", pas), ("pitch", pitches)):
            frame = _read_isolated_object(root, receipt["objects"][family], day)
            for key in ("sourceIdentity", "observedAt", "availableAsOf", "ingestedAt", "completionConfirmedAt"):
                frame[key] = source[key]
            frame["completedAt"] = None
            frame["status"] = "FINAL"
            destination.append(frame)
    pa_frame = pd.concat(pas, ignore_index=True) if pas else pd.DataFrame()
    pitch_frame = pd.concat(pitches, ignore_index=True) if pitches else pd.DataFrame()
    authority = _history_authority(pa_frame, pitch_frame, sources, requested_dates=days, missing_dates=missing, as_of=as_of)
    return CurrentHistory(pa_frame, pitch_frame, [], authority)


def _store(blob: bytes, suffix: str, output_root: Path) -> dict:
    root = Path(output_root).resolve()
    if not root.is_relative_to(SOURCE_ROOT.resolve()):
        raise CurrentSourceError("New current evidence must stay inside its Model Studio output root")
    sha = _sha(blob)
    path = root / "objects/sha256" / f"{sha}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != blob:
            raise CurrentSourceError("Immutable current-source object collision")
    else:
        with path.open("xb") as handle:
            handle.write(blob)
    return {"path": str(path), "sha256": sha, "bytes": len(blob)}


def acquire_free_daily_source(day: str, *, family: str, allow_free_network: bool = False,
                              output_root: Path = SOURCE_ROOT, timeout_seconds: int = 45,
                              purpose: str | None = None,
                              request_telemetry: SourceRequestTelemetry | None = None) -> dict:
    """One bounded free request, without automatic retries or paid endpoints.

    Only dated post-seal MLB schedule or Statcast requests are allowed. The
    capture records retrieval, availability and local ingestion separately;
    absent provider publication times remain explicitly null.
    """
    day = operational_capture_day(day, purpose=purpose)
    now = datetime.now(timezone.utc)
    minimum = SEALED_START if purpose == OPERATIONAL_PURPOSE else POST_SEALED_START
    if date.fromisoformat(day) < minimum or date.fromisoformat(day) > now.date() + timedelta(days=7):
        raise CurrentSourceError("Free acquisition is bounded to post-seal current evidence")
    if family == "STATCAST":
        operational_capture_day(day, purpose=purpose, before=now.date())
        from tools.bronze_acquisition.sources import nightly_current_statcast_partitions
        url = nightly_current_statcast_partitions(day, day)[0].url
        suffix = ".csv"
    elif family == "SCHEDULE":
        url = "https://statsapi.mlb.com/api/v1/schedule?" + urlencode({
            "sportId": 1, "gameTypes": "R", "date": day,
            "hydrate": "team,venue,probablePitcher,linescore"})
        suffix = ".json"
    else:
        raise CurrentSourceError("Only free MLB schedule and Statcast daily sources are supported")
    if not allow_free_network:
        return {"status": "FREE_SOURCE_REQUEST_NOT_EXECUTED", "family": family, "day": day, "url": url}
    requested = datetime.now(timezone.utc)
    request = Request(url, headers={"User-Agent": "ASP-Model-Studio-Local-Research/1.0"})
    with _tracked_source_response(request, family=family, timeout=timeout_seconds,
                                  request_telemetry=request_telemetry) as response:
        if response.status != 200:
            raise CurrentSourceError(f"Free MLB source HTTP status {response.status}")
        blob = response.read(30_000_001)
        if len(blob) > 30_000_000:
            raise CurrentSourceError("Daily source exceeded bounded 30MB response limit")
        content_type = response.headers.get("Content-Type")
    observed = datetime.now(timezone.utc)
    raw = _store(blob, suffix, output_root)
    ingested = datetime.now(timezone.utc)
    receipt = {"schemaVersion": "MLB_V18_FREE_DAILY_SOURCE_CAPTURE_V1", "status": "CAPTURED_NOT_YET_NORMALIZED",
               "family": family, "day": day, "url": url, "requestStartedAt": requested.isoformat(),
               "observedAt": observed.isoformat(), "availableAsOf": observed.isoformat(),
               "ingestedAt": ingested.isoformat(), "providerPublishedAt": None,
               "observationBasis": "HTTP_RESPONSE_RETRIEVAL_NOT_PROVIDER_PUBLICATION",
               "contentType": content_type, "raw": raw, "rights": RIGHTS,
               "paidProviderCalls": 0, "sealedEvaluationPayloadsRequested": 0,
               "purpose": purpose, "authorization": OPERATIONAL_AUTHORIZATION if purpose == OPERATIONAL_PURPOSE else None,
               "protectedCalendarOperationalSourceRequested": SEALED_START <= date.fromisoformat(day) <= SEALED_END}
    stored = _store(_bytes(receipt), ".receipt.json", output_root)
    return {**receipt, "receipt": stored, "sourceIdentity": stored["sha256"]}


SCHEDULE_IDENTITY_FIELDS = (
    "dates,date,games,gamePk,gameDate,officialDate,gameType,teams,home,away,team,id,name,"
    "abbreviation,venue,seriesGameNumber,gamesInSeries,gameNumber,doubleHeader,"
    "status,abstractGameState,detailedState,statusCode,codedGameState"
)


def acquire_schedule_identity_projection(*, start: str, through: str, allow_free_network: bool = False,
                                         output_root: Path = SOURCE_ROOT,
                                         request_telemetry: SourceRequestTelemetry | None = None) -> dict:
    """Full-season schedule metadata ONLY, including otherwise sealed dates.

    The provider-side fields projection excludes outcome/PA/lineup/innings
    payload before retrieval. This narrowly authorized schedule identity source
    cannot be used to make sealed PA history or result-derived features readable.
    """
    first, last = date.fromisoformat(start), date.fromisoformat(through)
    today = datetime.now(timezone.utc).date()
    if first.year != 2026 or last.year != 2026 or first > last or last > today + timedelta(days=7):
        raise CurrentSourceError("Schedule-only projection must be bounded to current2026 season")
    url = "https://statsapi.mlb.com/api/v1/schedule?" + urlencode({"sportId": 1, "gameTypes": "R",
        "startDate": start, "endDate": through, "fields": SCHEDULE_IDENTITY_FIELDS})
    if not allow_free_network:
        return {"status": "FREE_SOURCE_REQUEST_NOT_EXECUTED", "family": "SCHEDULE_IDENTITIES_ONLY", "url": url}
    requested = datetime.now(timezone.utc)
    with _tracked_source_response(Request(url, headers={"User-Agent": "ASP-Model-Studio-Local-Research/1.0"}),
                                  family="SCHEDULE_IDENTITIES_ONLY", timeout=45,
                                  request_telemetry=request_telemetry) as response:
        blob = response.read(10_000_001)
    observed = datetime.now(timezone.utc)
    if len(blob) > 10_000_000:
        raise CurrentSourceError("Projected schedule exceeded10MB metadata bound")
    payload = json.loads(blob)
    forbidden = {"score", "runs", "hits", "errors", "linescore", "lineup", "innings", "boxscore", "plays", "allPlays", "stats"}
    def check(value):
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise CurrentSourceError("Provider violated schedule-only field projection")
            for v in value.values(): check(v)
        elif isinstance(value, list):
            for v in value: check(v)
    check(payload)
    raw = _store(blob, ".schedule-identities.json", output_root)
    receipt = {"schemaVersion": "MLB_V18_SCHEDULE_IDENTITY_ONLY_CAPTURE_V1", "family": "SCHEDULE_IDENTITIES_ONLY",
        "sourceIdentity": raw["sha256"], "startDate": start, "throughDate": through, "url": url,
        "observedAt": observed.isoformat(), "availableAsOf": observed.isoformat(),
        "ingestedAt": datetime.now(timezone.utc).isoformat(), "requestStartedAt": requested.isoformat(),
        "providerPublishedAt": None, "raw": raw, "fieldsProjection": SCHEDULE_IDENTITY_FIELDS,
        "sealedDateScope": "SCHEDULE_IDENTITY_METADATA_ONLY_NO_OUTCOME_PA_LINEUP_INNINGS_PAYLOAD",
        "rights": RIGHTS}
    return {**receipt, "receipt": _store(_bytes(receipt), ".receipt.json", output_root)}


def schedule_identity_rows(receipt: Mapping) -> list[dict]:
    if receipt.get("family") != "SCHEDULE_IDENTITIES_ONLY":
        raise CurrentSourceError("Expected the provider-projected schedule-only contract")
    payload = _verified_json(Path(receipt["raw"]["path"]), receipt["raw"]["sha256"])
    rows = []
    for group in payload.get("dates", []):
        for game in group.get("games", []):
            teams = game.get("teams", {})
            rows.append({"canonicalGameId": canonical_game_id(game["gamePk"]), "mlbamGamePk": int(game["gamePk"]),
                "gameDate": game.get("officialDate", group["date"]), "scheduledStartUtc": game.get("gameDate"),
                "homeTeamMlbamId": teams.get("home", {}).get("team", {}).get("id"),
                "awayTeamMlbamId": teams.get("away", {}).get("team", {}).get("id"),
                "venueMlbamId": game.get("venue", {}).get("id"),
                "seriesGameNumber": game.get("seriesGameNumber"), "gamesInSeries": game.get("gamesInSeries"),
                "gameNumber": game.get("gameNumber"), "doubleHeader": game.get("doubleHeader"),
                "status": game.get("status", {}).get("detailedState"),
                "sourceIdentity": receipt["sourceIdentity"], "scheduleOnly": True,
                **{k: receipt[k] for k in ("observedAt", "availableAsOf", "ingestedAt")}})
    return rows


def completed_games_from_schedule(receipt: Mapping[str, Any], *, as_of_utc: str | datetime) -> list[dict]:
    """Accept FINAL official schedule observations with known capture clocks."""
    as_of = _clock(as_of_utc)
    operational = authenticate_operational_receipt(receipt)
    day = operational_capture_day(str(receipt["day"]), purpose=OPERATIONAL_PURPOSE if operational else None, before=as_of.date())
    if receipt.get("family") != "SCHEDULE" or max(_clock(receipt[k]) for k in ("observedAt", "availableAsOf", "ingestedAt")) > as_of:
        raise CurrentSourceError("Schedule source was not available at this source cutoff")
    payload = _verified_json(Path(receipt["raw"]["path"]), receipt["raw"]["sha256"])
    games = []
    for day_group in payload.get("dates", []):
        if day_group.get("date") != day:
            raise CurrentSourceError("Schedule response has a date outside its safe single-day request")
        for game in day_group.get("games", []):
            if game.get("officialDate") != day:
                continue
            state = game.get("status", {}).get("detailedState")
            if state not in {"Final", "Completed Early"} or game.get("gameType") != "R":
                continue
            pk = int(game["gamePk"])
            teams = game["teams"]
            games.append({"canonicalGameId": canonical_game_id(pk), "mlbamGamePk": pk, "gameDate": day,
                          "homeTeamMlbamId": int(teams["home"]["team"]["id"]),
                          "awayTeamMlbamId": int(teams["away"]["team"]["id"]),
                          "homeTeamAbbreviation": teams["home"]["team"].get("abbreviation"),
                          "awayTeamAbbreviation": teams["away"]["team"].get("abbreviation"),
                          "scheduledStartUtc": game.get("gameDate"), "venueMlbamId": game.get("venue", {}).get("id"),
                          "seriesGameNumber": game.get("seriesGameNumber"), "gamesInSeries": game.get("gamesInSeries"),
                          "inningsPlayed": game.get("linescore", {}).get("currentInning"),
                          "durationMinutes": None, "completedAt": None, "status": "FINAL",
                          "completionConfirmedAt": receipt["observedAt"], "sourceIdentity": receipt["sourceIdentity"],
                          "sourcePurpose": OPERATIONAL_PURPOSE if operational else "CURRENT_SOURCE_HISTORY",
                          **{k: receipt[k] for k in ("observedAt", "availableAsOf", "ingestedAt")}})
    return games


def normalize_captured_history(statcast_receipts: Sequence[Mapping], schedule_receipts: Sequence[Mapping],
                               *, as_of_utc: str | datetime, resolved_mlbam: Mapping[str, str]) -> CurrentHistory:
    """Reuse the accepted normalizer; never reinterpret missing games as no history."""
    as_of = _clock(as_of_utc)
    schedules = {r["day"]: r for r in schedule_receipts}
    pas, pitches, games, sources, missing = [], [], [], [], []
    operational_receipts = [r for r in (*statcast_receipts, *schedule_receipts) if authenticate_operational_receipt(r)]
    days = sorted({operational_capture_day(str(r["day"]), purpose=OPERATIONAL_PURPOSE if r in operational_receipts else None,
                                          before=as_of.date()) for r in statcast_receipts})
    for receipt in sorted(statcast_receipts, key=lambda r: r["day"]):
        operational = receipt in operational_receipts
        day = operational_capture_day(str(receipt["day"]), purpose=OPERATIONAL_PURPOSE if operational else None, before=as_of.date())
        if day not in schedules:
            missing.append(day)
            continue
        if receipt.get("family") != "STATCAST" or max(_clock(receipt[k]) for k in ("observedAt", "availableAsOf", "ingestedAt")) > as_of:
            raise CurrentSourceError("Statcast source was not available before this source cutoff")
        final = completed_games_from_schedule(schedules[day], as_of_utc=as_of)
        blob = Path(receipt["raw"]["path"]).read_bytes()
        if _sha(blob) != receipt["raw"]["sha256"]:
            raise CurrentSourceError("Current Statcast raw checksum mismatch")
        table = pacsv.read_csv(io.BytesIO(blob), read_options=pacsv.ReadOptions(block_size=1 << 24))
        dates = {str(v) for v in table["game_date"].to_pylist()}
        if dates - {day}:
            raise CurrentSourceError("Unexpected date outside the safe Statcast request")
        if table.num_rows >= 25000:
            raise CurrentSourceError("Statcast row cap reached: truncated day cannot prove completeness")
        expected = {g["mlbamGamePk"] for g in final}
        present = {int(v) for v in table["game_pk"].to_pylist() if v is not None}
        if present != expected:
            missing.append(day)
        result = normalize_current_partition(table, partition_id=f"current-prospective/{day}", partition_date=day,
            source_cutoff=receipt["availableAsOf"], source_partition_sha256=receipt["raw"]["sha256"],
            source_manifest_sha256=receipt["sourceIdentity"], final_game_pks=expected, resolved_mlbam=resolved_mlbam)
        source = {"sourceIdentity": receipt["sourceIdentity"], "gameDate": day,
                  "observedAt": receipt["observedAt"],
                  "availableAsOf": max(receipt["availableAsOf"], schedules[day]["availableAsOf"]),
                  "ingestedAt": max(receipt["ingestedAt"], schedules[day]["ingestedAt"]),
                  "completionConfirmedAt": schedules[day]["observedAt"],
                  "rawSha256": receipt["raw"]["sha256"], "scheduleSha256": schedules[day]["raw"]["sha256"],
                  "expectedGames": len(expected), "representedGames": len(present & expected),
                  "missingGamePks": sorted(expected - present), "unexpectedGamePks": sorted(present - expected),
                  "normalizationCounts": result.counts,
                  "sourcePurpose": OPERATIONAL_PURPOSE if operational else "CURRENT_SOURCE_HISTORY",
                  "availabilityBasis": "CURRENT_RETRIEVED_FINAL_GAME_SOURCE_NOT_HISTORICAL_PUBLICATION_VINTAGE"}
        sources.append(source)
        games.extend(final)
        for records, destination in ((result.fact_pa, pas), (result.fact_pitch, pitches)):
            frame = pd.DataFrame(records)
            for key in ("sourceIdentity", "observedAt", "availableAsOf", "ingestedAt", "completionConfirmedAt"):
                frame[key] = source[key]
            frame["sourcePurpose"] = source["sourcePurpose"]
            frame["completedAt"] = None
            frame["status"] = "FINAL"
            destination.append(frame)
    pa_frame = pd.concat(pas, ignore_index=True) if pas else pd.DataFrame()
    pitch_frame = pd.concat(pitches, ignore_index=True) if pitches else pd.DataFrame()
    authority = _history_authority(pa_frame, pitch_frame, sources, requested_dates=days, missing_dates=missing, as_of=as_of)
    if operational_receipts:
        authority["_operationalSourceCapability"] = VerifiedOperationalHistory(OPERATIONAL_PURPOSE, OPERATIONAL_AUTHORIZATION,
            tuple((r["sourceIdentity"], r["day"]) for r in operational_receipts), max(r["ingestedAt"] for r in operational_receipts))
        authority["operationalSourceException"] = {"purpose": OPERATIONAL_PURPOSE, "authorization": OPERATIONAL_AUTHORIZATION,
            "dates": sorted({r["day"] for r in operational_receipts}), "receipts": [r["receipt"] for r in operational_receipts],
            "evaluationArtifactsRead": 0, "evaluationSelectionUseAllowed": False}
    return CurrentHistory(pa_frame, pitch_frame, games, authority)


def _build_current_source_bundle(acquisition_attempt_path: Path, *, as_of_utc: str | datetime,
                                staging_root: Path = STAGING,
                                exchange_root: Path = Path("C:/Users/james/asp-model-exchange")) -> dict:
    """Explicit immutable attempt -> source bundle for the pure feature builder.

    No implicit latest-file scan, no acquisition, no legacy yearly/history scan.
    Complete frozen annual priors remain distinct from incomplete post-gap PA
    history. The bundle makes no claim that source ingestion has scored V18.
    """
    from .pipeline import _load_player_identity
    path = Path(acquisition_attempt_path).resolve()
    if not path.is_relative_to(SOURCE_ROOT.resolve()):
        raise CurrentSourceError("Expected an explicit Model Studio current-source acquisition attempt")
    expected = path.name.split(".", 1)[0]
    attempt = _verified_json(path, expected)
    as_of = _clock(as_of_utc)
    if _clock(attempt["completedAt"]) > as_of:
        raise CurrentSourceError("Source attempt completed after the chosen input cutoff")
    identity_map, identity_authority = _load_player_identity(Path(staging_root) / "mlb-silver-v1")
    receipts = [r for r in attempt["receipts"] if r.get("status") == "CAPTURED_NOT_YET_NORMALIZED"]
    history = normalize_captured_history([r for r in receipts if r["family"] == "STATCAST"],
        [r for r in receipts if r["family"] == "SCHEDULE"], as_of_utc=as_of, resolved_mlbam=identity_map)
    requested = set(attempt["requestedDates"])
    captured = {r["day"] for r in receipts if r["family"] == "STATCAST"}
    missing = set(history.authority["missingDates"]) | (requested - captured)
    history.authority.update(missingDates=sorted(missing), requestedDates=sorted(requested),
                             sourceAcquisitionFailures=attempt["failures"])
    if missing:
        history.authority["contiguousRequestedDatesComplete"] = False
    annual_priors, annual_authority = load_frozen_annual_priors(as_of_utc=as_of,
        exchange_root=exchange_root, staging_root=staging_root)
    current_players = set()
    if not history.pa_history.empty:
        current_players.update(history.pa_history["batterCanonicalPlayerId"].astype(str))
        current_players.update(history.pa_history["pitcherCanonicalPlayerId"].astype(str))
    annual_authority["completePlayerDomains"] = sorted(f"{player}:{domain}" for player in current_players
                                                      for domain in ("BATTING", "PITCHING"))
    schedule_receipt = attempt.get("scheduleIdentityReceipt")
    schedule_rows = schedule_identity_rows(schedule_receipt) if schedule_receipt and schedule_receipt.get("raw") else []
    return {"pa_history": history.pa_history, "pitches": history.pitches, "games": history.games,
            "authority": history.authority, "annual_priors": annual_priors, "annual_authority": annual_authority,
            "mlbam_to_canonical": identity_map, "player_identity_authority": identity_authority,
            "schedule_identity_rows": schedule_rows, "schedule_identity_authority": schedule_receipt,
            "acquisitionAttemptPath": str(path), "acquisitionAttemptSha256": expected,
            "asOfUtc": as_of.isoformat(), "rawPaidProviderCalls": 0, "sealedEvaluationPayloadReads": 0}


def load_current_source_bundle(acquisition_attempt_path: Path, *, as_of_utc: str | datetime,
                               staging_root: Path = STAGING,
                               exchange_root: Path = Path("C:/Users/james/asp-model-exchange")) -> dict:
    """Hash-verified immutable source cache; unchanged inputs never renormalize.

    Cache identity binds active receipt contents and original source clocks,
    implementation bytes, frozen FD1 and player identity. Acquisition attempts
    remain separate audit references: a successful refresh of unchanged evidence
    does not force normalization or rewrite original ingestion clocks.
    """
    import joblib
    from .gold import FD1_MANIFEST_SHA
    from server.sports_silver import silver_publication
    path = Path(acquisition_attempt_path).resolve()
    if not path.is_relative_to(SOURCE_ROOT.resolve()):
        raise CurrentSourceError("Acquisition attempt must be inside the immutable current-source root")
    acquisition_sha = path.name.split(".", 1)[0]
    attempt = _verified_json(path, acquisition_sha)
    as_of = _clock(as_of_utc)
    if _clock(attempt["completedAt"]) > as_of:
        raise CurrentSourceError("Acquisition attempt is newer than evaluation cutoff")
    silver_root = Path(staging_root) / "mlb-silver-v1"
    item = silver_publication.logical_index(silver_root)["dim_player"]
    registration = silver_publication._load_registration(silver_root, item["currentRegistrationSha256"])
    active_receipts = sorted(({
        "day": r["day"], "family": r["family"], "rawSha256": r["raw"]["sha256"],
        **{k: r[k] for k in ("observedAt", "availableAsOf", "ingestedAt")}}
        for r in attempt["receipts"] if r.get("status") == "CAPTURED_NOT_YET_NORMALIZED"),
        key=lambda r: (r["day"], r["family"]))
    schedule = attempt.get("scheduleIdentityReceipt")
    schedule_state = ({"rawSha256": schedule["raw"]["sha256"],
        **{k: schedule[k] for k in ("observedAt", "availableAsOf", "ingestedAt")}}
        if schedule and schedule.get("raw") else None)
    content_state = {"requestedDates": sorted(attempt["requestedDates"]),
                     "activeReceipts": active_receipts, "scheduleIdentityState": schedule_state}
    identity = {"contentStateSha256": _sha(_bytes(content_state)),
                "sourceImplementationSha256": _sha(Path(__file__).read_bytes()),
                "normalizerImplementationSha256": _sha(Path(__file__).resolve().parents[1].joinpath("sports_silver/current_statcast_pa.py").read_bytes()),
                "fd1ManifestSha256": FD1_MANIFEST_SHA,
                "playerIdentityManifestSha256": registration["publicationManifestSha256"],
                "schemaVersion": "MLB_V18_NORMALIZED_CURRENT_SOURCE_CACHE_V1"}
    key = _sha(_bytes(identity))
    index_path = SOURCE_ROOT / "normalized-cache/indices" / f"{key}.json"
    if index_path.exists():
        index = _verified_json(index_path)
        if index["identity"] != identity or index["cacheKey"] != key:
            raise CurrentSourceError("Normalized source-cache identity mismatch")
        object_path = Path(index["object"]["path"]).resolve()
        if not object_path.is_relative_to(SOURCE_ROOT.resolve()):
            raise CurrentSourceError("Normalized source-cache path escapes the source root")
        blob = object_path.read_bytes()
        if len(blob) != index["object"]["bytes"] or _sha(blob) != index["object"]["sha256"]:
            raise CurrentSourceError("Normalized source-cache payload checksum mismatch")
        bundle = joblib.load(io.BytesIO(blob))
        if _clock(bundle["asOfUtc"]) > as_of:
            raise CurrentSourceError("Normalized source-cache was built after the requested cutoff")
        bundle["cache"] = {"reused": True, "cacheKey": key, "indexPath": str(index_path), **index["object"]}
        bundle["evaluationAsOfUtc"] = as_of.isoformat()
        bundle["currentAcquisitionAttemptPath"] = str(path)
        bundle["currentAcquisitionAttemptSha256"] = acquisition_sha
        return bundle
    bundle = _build_current_source_bundle(path, as_of_utc=as_of, staging_root=staging_root, exchange_root=exchange_root)
    buffer = io.BytesIO()
    joblib.dump(bundle, buffer, compress=3, protocol=5)
    blob = buffer.getvalue()
    descriptor = _store(blob, ".normalized-source-bundle.joblib", SOURCE_ROOT)
    # Immediate content-addressed reload equality protects the actual data, not a fitted model.
    reloaded = joblib.load(io.BytesIO(Path(descriptor["path"]).read_bytes()))
    if not bundle["pa_history"].equals(reloaded["pa_history"]) or not bundle["pitches"].equals(reloaded["pitches"]):
        raise CurrentSourceError("Normalized source-cache DataFrame reload mismatch")
    if bundle["authority"] != reloaded["authority"] or bundle["annual_priors"] != reloaded["annual_priors"]:
        raise CurrentSourceError("Normalized source-cache evidence reload mismatch")
    index = {"cacheKey": key, "identity": identity, "object": descriptor,
             "sourceCutoff": bundle["authority"].get("availableAsOf"), "firstBuiltAt": bundle["asOfUtc"],
             "acceptedPaRows": len(bundle["pa_history"]), "acceptedPitchRows": len(bundle["pitches"]),
             "reloadEquality": True}
    index_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with index_path.open("xb") as handle:
            handle.write(_bytes(index))
    except FileExistsError:
        existing = _verified_json(index_path)
        if existing["identity"] != identity:
            raise CurrentSourceError("Concurrent normalized-cache publication has conflicting identity")
    bundle["cache"] = {"reused": False, "cacheKey": key, "indexPath": str(index_path), **descriptor}
    bundle["evaluationAsOfUtc"] = as_of.isoformat()
    bundle["currentAcquisitionAttemptPath"] = str(path)
    bundle["currentAcquisitionAttemptSha256"] = acquisition_sha
    return bundle


def _selected_historical_pitches(pa_rows: pd.DataFrame, *, authority: Mapping,
                                  staging_root: Path) -> tuple[pd.DataFrame, list[dict]]:
    """Read only daily pitch objects needed by exact current-player PA windows.

    Legacy/evaluation payloads from the protected dates are never eligible.
    Every daily child's date is proved in its footer before hashing or reading.
    """
    if pa_rows.empty:
        return pd.DataFrame(), []
    projection = ["canonicalPaId", "gameDate", "pitchType", "releaseSpeed", "pitchResultType"]
    daily_root = Path(staging_root) / "mlb-current-statcast-silver-v1"
    daily = _verified_json(daily_root / "publications/sha256" / ACCEPTED_SILVER_SHA / "manifest.json",
                           ACCEPTED_SILVER_SHA)
    descriptors = {r["partitionDate"]: (daily_root, r["objects"]["pitch"], r["partitionDate"])
                   for r in daily["partitions"] if r["partitionDate"] < SEALED_START.isoformat()}
    old_sha = "352b2df31e98655acefa9ff27de30c42f80030e16e5abe8f23f83819049d1281"
    old_root = Path(staging_root) / "mlb-silver-v1/partitioned" / old_sha
    old = _verified_json(old_root / "manifest.json", old_sha)
    if old["tableName"] != "fact_statcast_pitch" or set(old["seasons"]) != {2019, 2020, 2021, 2022, 2023, 2024}:
        raise CurrentSourceError("Accepted historical pitch source identity changed")
    for child in old["children"]:
        partition = child["partitionKey"].rsplit("/", 1)[-1]
        if partition in descriptors:
            raise CurrentSourceError("Historical pitch partition maps to duplicate sources")
        if child["seasons"] != [partition[:4]] or not "2019-01-01" <= partition <= "2024-12-31":
            raise CurrentSourceError("Historical pitch child is outside its frozen season authority")
        descriptors[partition] = (old_root, {"relativePath": f"children/{child['childSha256']}.parquet",
            "sha256": child["childSha256"], "byteCount": child["bytes"],
            "historicalManifestSha256": old_sha, "partitionDay": partition}, None)
    selected, source_rows = [], []
    grouped = pa_rows.copy()
    grouped["_pitchPhysicalPartition"] = grouped.gameDate.astype(str).str[:10]
    for partition, rows in grouped.groupby("_pitchPhysicalPartition", sort=True):
        day = str(rows.gameDate.iloc[0])[:10]
        if rows.gameDate.astype(str).str[:10].ge(SEALED_START.isoformat()).any():
            raise CurrentSourceError("Historical-window loader cannot read protected legacy or current source dates")
        if partition not in descriptors:
            raise CurrentSourceError(f"Historical pitch child missing for exact selected window: {partition}")
        root, descriptor, required_day = descriptors[partition]
        path = (root / descriptor["relativePath"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise CurrentSourceError("Historical pitch child path escapes registered root")
        parquet = pq.ParquetFile(path)
        date_index = parquet.schema_arrow.names.index("gameDate")
        for group in range(parquet.num_row_groups):
            stats = parquet.metadata.row_group(group).column(date_index).statistics
            if stats is None or not stats.has_min_max:
                # The accepted2019--2024 writer disabled statistics. Its pinned,
                # SHA-verified season-separated object manifest is the physical
                # source authority; it cannot name a2026 evaluation object.
                if descriptor.get("historicalManifestSha256") == old_sha:
                    continue
                raise CurrentSourceError("Historical pitch footer does not prove physical date isolation")
            first, last = str(stats.min)[:10], str(stats.max)[:10]
            if required_day is not None:
                allowed = first == required_day == last
            else:
                allowed = "2019-01-01" <= first <= last <= "2024-12-31"
            if not allowed:
                raise CurrentSourceError("Historical pitch footer is outside its registered safe date authority")
        blob = path.read_bytes()
        if len(blob) != descriptor["byteCount"] or _sha(blob) != descriptor["sha256"]:
            raise CurrentSourceError("Historical pitch child checksum differs")
        frame = parquet.read(columns=projection).to_pandas()
        if not frame.gameDate.astype(str).str[:10].eq(partition).all():
            raise CurrentSourceError("Historical pitch source dates differ from physical partition authority")
        ids = set(rows.canonicalPaId.astype(str))
        frame = frame[frame.canonicalPaId.astype(str).isin(ids)].copy()
        if set(frame.canonicalPaId.astype(str)) != ids:
            raise CurrentSourceError("Exact historical window lacks its complete PA pitch evidence")
        source_id = descriptor["sha256"]
        frame["sourceIdentity"] = source_id
        for name in ("observedAt", "availableAsOf", "ingestedAt", "completionConfirmedAt"):
            frame[name] = authority[name]
        frame["sourcePurpose"] = OPERATIONAL_PURPOSE
        frame["completedAt"] = None
        frame["status"] = "FINAL"
        selected.append(frame)
        source_rows.append({"partitionKey": partition, "path": str(path), "sha256": source_id,
                            "bytes": len(blob), "selectedPaCount": len(ids), "selectedPitchCount": len(frame)})
    return pd.concat(selected, ignore_index=True), source_rows


def extend_history_for_current_players(bundle: Mapping, required_mlbam_ids: Sequence[str], *,
                                       as_of_utc: str | datetime,
                                       staging_root: Path = STAGING) -> dict:
    """Complete exact frozen 2019-to-current exposure and last-N current inputs.

    This does not reopen an evaluation artifact. Its historical rows come only
    from physically isolated, source-only daily children before August14; the
    separately authenticated NEW operational capture bridges August14 onward.
    Only current participants' required historical windows require pitch reads.
    """
    import joblib
    from .mlb_v18_current_exposure import load_base_exposure
    as_of = _clock(as_of_utc)
    required = sorted({str(v) for v in required_mlbam_ids if v is not None})
    identity_map = bundle["mlbam_to_canonical"]
    missing = [v for v in required if v not in identity_map]
    if missing:
        raise CurrentSourceError("Current participant source identity missing: " + ",".join(missing))
    players = sorted({str(identity_map[v]) for v in required})
    base = load_base_exposure(as_of_utc=as_of)
    base_authority = {**base["authority"], "completionConfirmedAt": base["authority"].get(
        "completionConfirmedAt", base["authority"]["availableAsOf"])}
    if _clock(base_authority["availableAsOf"]) > as_of or _clock(base_authority["ingestedAt"]) > as_of:
        raise CurrentSourceError("Historical operational adapter is newer than the prospective cutoff")
    if bundle["authority"].get("completeFrom") != SEALED_START.isoformat() or bundle["authority"].get("missingDates"):
        raise CurrentSourceError("Exact current input reconstruction requires complete NEW August14-forward capture")
    verify_operational_source_rows(bundle["pa_history"], bundle["authority"], as_of_utc=as_of)
    identity = {"schemaVersion": "MLB_V18_CURRENT_PLAYER_WINDOW_CACHE_V1", "players": players,
        "historySourceIdentity": bundle["authority"]["sourceIdentity"],
        "baseExposureIdentity": base_authority["sourceIdentity"],
        "sourceImplementationSha256": _sha(Path(__file__).read_bytes()),
        "exposureImplementationSha256": _sha(Path(__file__).with_name("mlb_v18_current_exposure.py").read_bytes())}
    key = _sha(_bytes(identity))
    index_path = SOURCE_ROOT / "current-window-cache/indices" / f"{key}.json"
    if index_path.exists():
        index = _verified_json(index_path)
        if index["identity"] != identity:
            raise CurrentSourceError("Current-window cache identity changed")
        descriptor = index["object"]
        path = Path(descriptor["path"]).resolve()
        if not path.is_relative_to(SOURCE_ROOT.resolve()):
            raise CurrentSourceError("Current-window cache escaped its source root")
        blob = path.read_bytes()
        if len(blob) != descriptor["bytes"] or _sha(blob) != descriptor["sha256"]:
            raise CurrentSourceError("Current-window cache checksum mismatch")
        result = joblib.load(io.BytesIO(blob))
        result["windowCache"] = {"reused": True, "cacheKey": key, "indexPath": str(index_path), **descriptor}
        result["evaluationAsOfUtc"] = as_of.isoformat()
        return result
    recent = bundle["pa_history"]
    combined = pd.concat([base["pa_history"], recent], ignore_index=True)
    if combined.canonicalPaId.duplicated().any():
        raise CurrentSourceError("Base accepted PA history overlaps the new operational archive")
    order = ["gameDate", "mlbamGamePk", "atBatNumber", "canonicalPaId"]
    combined = combined.sort_values(order, kind="mergesort")
    selected_ids, complete_players, exposures, proofs = set(), {}, {}, []
    last_day = bundle["authority"]["completeThrough"]
    clocks = {name: max(base_authority[name], bundle["authority"][name], key=_clock)
              for name in ("observedAt", "availableAsOf", "ingestedAt", "completionConfirmedAt")}
    for role, size in (("batter", 100), ("pitcher", 250)):
        column = role + "CanonicalPlayerId"
        recent_counts = Counter(recent[column].astype(str))
        complete_players[role], exposures[role] = [], {}
        groups = {str(player): rows for player, rows in combined[combined[column].astype(str).isin(players)].groupby(column, sort=False)}
        for player in players:
            rows = groups.get(player, combined.iloc[0:0])
            total = int(base["counts"][role].get(player, 0)) + int(recent_counts.get(player, 0))
            if len(rows) != total:
                raise CurrentSourceError("Exact accepted cumulative exposure differs from source PA identities")
            tail = rows.tail(size)
            selected_ids.update(tail.canonicalPaId.astype(str))
            complete_players[role].append(player)
            exposures[role][player] = {"value": total, "completeThrough": last_day,
                "sourceIdentity": key, **{k: clocks[k] for k in ("observedAt", "availableAsOf", "ingestedAt")}}
            proofs.append({"role": role, "playerId": player, "acceptedCumulativeExposure": total,
                "window": size, "selectedPaCount": len(tail),
                "orderedPaIdsSha256": _sha(_bytes(tail.canonicalPaId.astype(str).tolist())),
                "selection": "EXACT_ACCEPTED_GOLD_ORDER_LAST_N_FROM_FULL_ACCEPTED_2019_TO_CURRENT_SOURCE_UNIVERSE"})
    historical = base["pa_history"][base["pa_history"].canonicalPaId.astype(str).isin(selected_ids)].copy()
    source_authority = {**base_authority, "completionConfirmedAt": base_authority.get("completionConfirmedAt", base_authority["availableAsOf"])}
    for name in ("observedAt", "availableAsOf", "ingestedAt", "completionConfirmedAt"):
        historical[name] = source_authority[name]
    historical["sourceIdentity"] = base_authority["sourceIdentity"]
    historical["sourcePurpose"] = OPERATIONAL_PURPOSE
    historical["completedAt"] = None
    historical["status"] = "FINAL"
    pitches, pitch_sources = _selected_historical_pitches(historical, authority=source_authority, staging_root=staging_root)
    result = dict(bundle)
    result["pa_history"] = pd.concat([historical, recent], ignore_index=True)
    result["pitches"] = pd.concat([pitches, bundle["pitches"]], ignore_index=True)
    if set(result["pa_history"].canonicalPaId) != set(result["pitches"].canonicalPaId):
        raise CurrentSourceError("Extended current PA/pitch population is not exact")
    result["authority"] = {**bundle["authority"], **clocks, "sourceIdentity": key,
        "cumulativeExposure": exposures, "completeWindowPlayers": complete_players,
        "windowSelectionProof": {"identity": identity, "rows": proofs, "baseAuthority": base_authority,
                                 "historicalPitchSources": pitch_sources},
        "allHistoryComplete": False, "selectedHistoricalPaRows": len(historical),
        "selectedHistoricalPitchRows": len(pitches), "sealedEvaluationPayloadsRead": 0,
        "limitations": ["Historical source reconstruction is used only for current pregame inputs, not evaluation or model selection.",
                        "Exposure is the accepted 2019-forward V18 source universe, not a claim of complete career statistics before2019."]}
    buffer = io.BytesIO()
    joblib.dump(result, buffer, compress=3, protocol=5)
    descriptor = _store(buffer.getvalue(), ".normalized-source-bundle.joblib", SOURCE_ROOT)
    reloaded = joblib.load(io.BytesIO(Path(descriptor["path"]).read_bytes()))
    if not result["pa_history"].equals(reloaded["pa_history"]) or not result["pitches"].equals(reloaded["pitches"]) or result["authority"] != reloaded["authority"]:
        raise CurrentSourceError("Current historical-window artifact reload differs")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("xb") as handle:
        handle.write(_bytes({"identity": identity, "object": descriptor, "reloadEquality": True}))
    result["windowCache"] = {"reused": False, "cacheKey": key, "indexPath": str(index_path), **descriptor}
    return result
