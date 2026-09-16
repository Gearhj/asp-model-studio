"""One narrow, free current-player identity supplement; no AISP mutations.

Original lineup nulls remain original evidence. This separately timestamped
source may fill an absent hand field, never overwrite conflicting observations.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .mlb_v18_current_sources import (
    CurrentSourceError, RIGHTS, SOURCE_ROOT, STAGING, _bytes, _clock, _sha, _store, _verified_json,
    _tracked_source_response,
)

SCHEMA = "MLB_V18_CURRENT_PLAYER_IDENTITY_SUPPLEMENT_V1"


def _person(payload: dict, mlbam_id: str) -> dict:
    people = payload.get("people", [])
    if len(people) != 1 or str(people[0].get("id")) != mlbam_id:
        raise CurrentSourceError("Current player identity response does not match the requested MLBAM identity")
    player = people[0]
    bats = (player.get("batSide") or {}).get("code")
    throws = (player.get("pitchHand") or {}).get("code")
    if bats not in {"L", "R", "S"} or throws not in {"L", "R", "S"}:
        raise CurrentSourceError("Current identity response lacks supported explicit handedness")
    return {"bats": bats, "throws": throws}


def acquire_current_identity(mlbam_id: str, *, allow_free_network: bool = False,
                             eligible_current_ids: Iterable[str] | None = None, request_telemetry=None) -> dict:
    """One scoped free identity request, without retry or a wider roster search.

    The dispatcher must derive eligible_current_ids from its captured pregame
    starters and confirmed ordered lineups, using only missing-hand participants.
    This seam checks exact membership and the accepted canonical crosswalk. The
    original explicitly authorized Volpe repair remains the default scope.
    """
    mlbam_id = str(mlbam_id)
    eligible = {str(value) for value in eligible_current_ids or ()}
    if mlbam_id != "683011" and mlbam_id not in eligible:
        raise CurrentSourceError("Requested player is outside the explicit current pregame participant identity scope")
    from .pipeline import _load_player_identity
    mapping, identity_authority = _load_player_identity(STAGING / "mlb-silver-v1")
    if mlbam_id not in mapping:
        raise CurrentSourceError("Requested current player lacks the accepted canonical identity crosswalk")
    url = "https://statsapi.mlb.com/api/v1/people?" + urlencode({
        "personIds": mlbam_id, "fields": "people,id,batSide,code,pitchHand"})
    if not allow_free_network:
        return {"status": "FREE_SOURCE_REQUEST_NOT_EXECUTED", "url": url, "mlbamId": mlbam_id}
    started = datetime.now(timezone.utc)
    request = Request(url, headers={"User-Agent": "ASP-Model-Studio-Local-Research/1.0"})
    with _tracked_source_response(request, family="CURRENT_PLAYER_IDENTITY", timeout=30,
                                  request_telemetry=request_telemetry) as response:
        if response.status != 200:
            raise CurrentSourceError(f"Current player identity source HTTP status {response.status}")
        blob = response.read(100_001)
    observed = datetime.now(timezone.utc)
    if len(blob) > 100_000:
        raise CurrentSourceError("Current identity response exceeded its bounded100KB limit")
    fields = _person(json.loads(blob), mlbam_id)
    raw = _store(blob, ".current-player-identity.raw.json", SOURCE_ROOT)
    ingested = datetime.now(timezone.utc)
    receipt = {"schemaVersion": SCHEMA, "mlbamId": mlbam_id,
        "canonicalPlayerId": mapping[mlbam_id], **fields,
        "source": "MLB_STATS_API", "sourcePurpose": "CURRENT_PLAYER_IDENTITY",
        "requestStartedAt": started.isoformat(), "observedAt": observed.isoformat(),
        "availableAsOf": observed.isoformat(), "ingestedAt": ingested.isoformat(),
        "providerPublishedAt": None, "observationBasis": "CURRENT_HTTP_RETRIEVAL_NOT_HISTORICAL_PUBLICATION_VINTAGE",
        "url": url, "raw": raw, "playerIdentityAuthority": identity_authority,
        "rights": RIGHTS, "paidProviderCalls": 0, "providerCalls": 1,
        "sealedEvaluationPayloadReads": 0, "aispRowsModified": 0,
        "originalLineupEvidenceModified": False}
    stored = _store(_bytes(receipt), ".current-player-identity.json", SOURCE_ROOT)
    return {**receipt, "sourceIdentity": stored["sha256"], "sha256": raw["sha256"], "receipt": stored}


def load_current_identity_evidence(*, as_of_utc: str | datetime) -> list[dict]:
    """Read and authenticate existing supplements only; never calls a provider."""
    from .pipeline import _load_player_identity
    cutoff = _clock(as_of_utc)
    mapping, _ = _load_player_identity(STAGING / "mlb-silver-v1")
    selected = {}
    for path in sorted((SOURCE_ROOT / "objects/sha256").glob("*.current-player-identity.json")):
        expected = path.name.split(".", 1)[0]
        receipt = _verified_json(path, expected)
        if receipt.get("schemaVersion") != SCHEMA or receipt.get("sourcePurpose") != "CURRENT_PLAYER_IDENTITY":
            raise CurrentSourceError("Current identity supplement schema or purpose differs")
        if max(_clock(receipt[k]) for k in ("observedAt", "availableAsOf", "ingestedAt")) > cutoff:
            continue
        if _clock(receipt["observedAt"]) > _clock(receipt["availableAsOf"]):
            raise CurrentSourceError("Current identity supplement availability precedes observation")
        raw = receipt["raw"]
        raw_path = Path(raw["path"]).resolve()
        if not raw_path.is_relative_to((SOURCE_ROOT / "objects/sha256").resolve()):
            raise CurrentSourceError("Current identity raw path escapes its governed root")
        blob = raw_path.read_bytes()
        if _sha(blob) != raw["sha256"] or len(blob) != raw["bytes"]:
            raise CurrentSourceError("Current identity raw checksum/byte count differs")
        fields = _person(json.loads(blob), receipt["mlbamId"])
        if any(receipt[k] != value for k, value in fields.items()) or mapping.get(receipt["mlbamId"]) != receipt["canonicalPlayerId"]:
            raise CurrentSourceError("Current identity source fields or canonical crosswalk differ")
        row = {**receipt, "sourceIdentity": expected, "sha256": raw["sha256"],
            "receipt": {"path": str(path), "sha256": expected, "bytes": path.stat().st_size}}
        previous = selected.get(receipt["mlbamId"])
        if previous is None or _clock(previous["observedAt"]) < _clock(row["observedAt"]):
            selected[receipt["mlbamId"]] = row
    return [selected[key] for key in sorted(selected)]
