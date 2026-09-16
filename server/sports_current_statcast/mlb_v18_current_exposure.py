"""Exact accepted-history PA exposures for current V18 input construction.

Only the frozen 2019--2024 Silver PA authority and individually date-isolated
2025--August 13, 2026 source objects are opened. This is not career or annual
FD1 exposure, and never opens a mixed Gold or Final OOT evaluation payload.
The caller joins separately acquired current history after this base cutoff.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

import joblib
import pandas as pd
import pyarrow.parquet as pq

from .mlb_v18_current_sources import (
    ACCEPTED_SILVER_SHA, CurrentSourceError, SOURCE_ROOT, STAGING,
    _bytes, _clock, _sha, _store, _verified_json,
)

BASE_END = "2026-08-13"
OLD_PA_SHA = "6a56e1af6a10cc6ef7cb3a82ac45cf1a33d31f7dbf495b3256c0adefd95e6b17"
OLD_PA_REGISTRATION = "5679e2e914a55526cce88968b8eb6b256cab4f620b36d266be5dc68b0493b094"
PA_COLUMNS = [
    "canonicalPaId", "canonicalGameId", "mlbamGamePk", "atBatNumber",
    "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "season", "gameDate",
    "stand", "pThrows", "paEvent",
]


def _isolated_pa(path: Path, descriptor: Mapping[str, Any], day: str) -> pd.DataFrame:
    """Verify physical day isolation before hashing or opening source payload."""
    if not "2019-01-01" <= day <= BASE_END:
        raise CurrentSourceError("Base exposure source day is outside its frozen boundary")
    parquet = pq.ParquetFile(path)
    date_column = parquet.schema_arrow.names.index("gameDate")
    # The original immutable 2019--2024 partition writer disabled footer
    # statistics. Its SHA-verified season-separated manifest is the same
    # physical read authority used by accepted Gold; current objects require
    # explicit day footer statistics because their manifest also names OOT days.
    old_season_authority = (descriptor.get("manifestSha256") == OLD_PA_SHA
                            and descriptor.get("seasons") == [day[:4]]
                            and 2019 <= int(day[:4]) <= 2024)
    for group in range(parquet.num_row_groups):
        metadata = parquet.metadata.row_group(group)
        if metadata.num_rows == 0:
            continue
        stats = metadata.column(date_column).statistics
        if not old_season_authority and (stats is None or not stats.has_min_max or str(stats.min)[:10] != day
                or str(stats.max)[:10] != day):
            raise CurrentSourceError("Base exposure object is not physically date-isolated; payload unopened")
    blob = path.read_bytes()
    if len(blob) != descriptor["bytes"] or _sha(blob) != descriptor["sha256"]:
        raise CurrentSourceError("Base exposure source bytes/checksum differ")
    frame = parquet.read(columns=PA_COLUMNS).to_pandas()
    if len(frame) != descriptor["rows"] or (not frame.empty and not frame.gameDate.astype(str).eq(day).all()):
        raise CurrentSourceError("Base exposure source row count/date differs")
    return frame


def _descriptors() -> tuple[list[dict], dict]:
    old_root = STAGING / "mlb-silver-v1"
    registration = _verified_json(old_root / "silver-table-registrations/objects/sha256" /
                                  (OLD_PA_REGISTRATION + ".json"), OLD_PA_REGISTRATION)
    if (registration["publicationManifestSha256"] != OLD_PA_SHA
            or registration["seasons"] != list(range(2019, 2025))
            or registration["tableName"] != "fact_statcast_plate_appearance"):
        raise CurrentSourceError("Accepted historical PA registration differs")
    old_object = old_root / "partitioned" / OLD_PA_SHA
    old = _verified_json(old_object / "manifest.json", OLD_PA_SHA)
    if old["totalRowCount"] != registration["rowCount"]:
        raise CurrentSourceError("Historical PA registration/manifest counts differ")
    sources = []
    for child in old["children"]:
        day = child["partitionKey"].rsplit("/", 1)[-1]
        if not "2019-01-01" <= day <= "2024-12-31":
            raise CurrentSourceError("Historical PA partition date differs")
        sources.append({"path": str(old_object / "children" / (child["childSha256"] + ".parquet")),
                        "sha256": child["childSha256"], "bytes": child["bytes"],
                        "rows": child["rowCount"], "day": day, "seasons": child["seasons"], "manifestSha256": OLD_PA_SHA})
    current_root = STAGING / "mlb-current-statcast-silver-v1"
    current = _verified_json(current_root / "publications/sha256" / ACCEPTED_SILVER_SHA /
                             "manifest.json", ACCEPTED_SILVER_SHA)
    selected = [r for r in current["partitions"] if r["partitionDate"] <= BASE_END]
    expected_dates = set()
    for start, end in (("2025-03-18", "2025-09-28"), ("2026-03-25", BASE_END)):
        cursor, stop = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
        while cursor <= stop:
            expected_dates.add(cursor.isoformat())
            cursor += timedelta(days=1)
    if set(r["partitionDate"] for r in selected) != expected_dates:
        raise CurrentSourceError("Accepted current-source base seasonal date coverage differs")
    for receipt in selected:
        if receipt["sourceStatus"] not in {"COMPLETE", "COMPLETE_EMPTY"}:
            raise CurrentSourceError("Accepted current-source base has an incomplete day")
        obj = receipt["objects"]["plate_appearance"]
        path = (current_root / obj["relativePath"]).resolve()
        if not path.is_relative_to(current_root.resolve()):
            raise CurrentSourceError("Base exposure source escapes its registered root")
        sources.append({"path": str(path), "sha256": obj["sha256"], "bytes": obj["byteCount"],
                        "rows": obj["rowCount"], "day": receipt["partitionDate"],
                        "manifestSha256": ACCEPTED_SILVER_SHA})
    return sources, {
        "historicalPaRegistrationSha256": OLD_PA_REGISTRATION, "historicalPaManifestSha256": OLD_PA_SHA,
        "currentPaManifestSha256": ACCEPTED_SILVER_SHA, "historicalPaRows": registration["rowCount"],
        "currentPaRows": sum(r["counts"]["acceptedPlateAppearances"] for r in selected),
        "currentSourceDates": len(selected),
        "originalCurrentSourceCutoff": max(r["request"]["sourceCutoff"] for r in selected),
        "historicalOriginalIngestionTimestamp": None,
    }


def load_base_exposure(*, as_of_utc: str | datetime) -> dict[str, Any]:
    """Return all accepted pre-gap PA rows, exact role counts and immutable clocks.

    A new reconstruction gets its actual ingestion time, never the caller's
    historical cutoff. On cache reuse that clock and source identity stay fixed.
    """
    cutoff = _clock(as_of_utc)
    if cutoff.date().isoformat() <= BASE_END:
        raise CurrentSourceError("Current exposure reconstruction requires a prospective post-base cutoff")
    sources, identity = _descriptors()
    if _clock(identity["originalCurrentSourceCutoff"]) > cutoff:
        raise CurrentSourceError("Base source authority was not available by the requested cutoff")
    key = _sha(_bytes({"schema": "V18_ACCEPTED_PA_EXPOSURE_BASE_V1", "identity": identity,
                       "sourceChecksums": [s["sha256"] for s in sources],
                       "implementationSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}))
    index_path = SOURCE_ROOT / "exposure-cache/indices" / (key + ".json")
    if index_path.exists():
        index = _verified_json(index_path)
        payload_path = Path(index["payload"]["path"]).resolve()
        if not payload_path.is_relative_to((SOURCE_ROOT / "objects/sha256").resolve()):
            raise CurrentSourceError("Exposure cache escapes its private immutable source root")
        blob = payload_path.read_bytes()
        if _sha(blob) != index["payload"]["sha256"] or len(blob) != index["payload"]["bytes"]:
            raise CurrentSourceError("Exposure cache checksum mismatch")
        result = joblib.load(io.BytesIO(blob))
        result["cache"] = {"reused": True, "key": key, "index": str(index_path), "payload": index["payload"]}
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        frames = list(pool.map(lambda s: _isolated_pa(Path(s["path"]), s, s["day"]), sources))
    frame = pd.concat(frames, ignore_index=True)
    expected = identity["historicalPaRows"] + identity["currentPaRows"]
    if len(frame) != expected or frame.canonicalPaId.isna().any() or frame.canonicalPaId.duplicated().any():
        raise CurrentSourceError("Accepted base PA population row/identity reconciliation failed")
    if frame[["batterCanonicalPlayerId", "pitcherCanonicalPlayerId"]].isna().any().any():
        raise CurrentSourceError("Accepted base PA population has an unresolved participant identity")
    frame = frame.sort_values(["gameDate", "mlbamGamePk", "atBatNumber", "canonicalPaId"], kind="mergesort").reset_index(drop=True)
    counts = {role: {str(player): int(count) for player, count in frame[column].value_counts().items()}
              for role, column in (("batter", "batterCanonicalPlayerId"), ("pitcher", "pitcherCanonicalPlayerId"))}
    if any(sum(values.values()) != expected for values in counts.values()):
        raise CurrentSourceError("Exact cumulative role count reconciliation failed")
    completed = datetime.now(timezone.utc).isoformat()
    authority = {
        "schemaVersion": "MLB_V18_ACCEPTED_PA_EXPOSURE_BASE_V1", "sourceIdentity": key,
        "completeFrom": str(frame.gameDate.min()), "completeThrough": BASE_END,
        "observedAt": completed, "availableAsOf": completed, "ingestedAt": completed,
        "availabilityBasis": "CURRENT_RECONSTRUCTION_OF_FROZEN_ACCEPTED_PA_AUTHORITY_NOT_HISTORICAL_VINTAGE",
        "definition": "Count of accepted Silver plate appearances in frozen 2019–2024 plus current 2025–2026 authority before the target game date; not career, FD1 annual, or season-only exposure",
        "acceptedPaRows": expected, "uniquePaIds": expected, "roleCountSums": {r: sum(v.values()) for r, v in counts.items()},
        "sourceIdentityAuthority": identity, "sourceObjects": sources, "sealedEvaluationPayloadsRead": 0,
        "modelFits": 0, "providerCalls": 0,
    }
    receipt = _store(_bytes(authority), ".accepted-pa-exposure-base.json", SOURCE_ROOT)
    result = {"pa_history": frame, "counts": counts, "authority": authority, "receipt": receipt}
    stream = io.BytesIO()
    joblib.dump(result, stream, compress=3)
    payload = _store(stream.getvalue(), ".normalized-source-bundle.joblib", SOURCE_ROOT)
    index = {"schemaVersion": "MLB_V18_EXPOSURE_BASE_CACHE_V1", "key": key, "payload": payload, "receipt": receipt}
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("xb") as output:
        output.write(_bytes(index))
    result["cache"] = {"reused": False, "key": key, "index": str(index_path), "payload": payload}
    return result
