"""Inactive, bounded capture path for NFL personnel evidence.

Planning is the default.  Live execution requires two explicit acknowledgements
and writes only to an external content-addressed evidence root.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping

from .personnel_evidence import canonical_json_bytes, sha256_json


CONTRACT = "NFL_PERSONNEL_PROSPECTIVE_CAPTURE_V1"
DEFAULT_ROOT = Path(r"C:\Users\james\asp-data-staging\nfl\personnel-captures-v1")
MAX_REQUESTS_PER_CAPTURE = 7
MAX_RESPONSE_BYTES_PER_CAPTURE = 64 * 1024 * 1024
MAX_RETAINED_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class CaptureAsset:
    family_id: str
    release_tag: str
    asset_name: str
    url: str
    role: str
    license_id: str = "CC-BY-4.0"


@dataclass(frozen=True)
class CapturePlan:
    season: int
    assets: tuple[CaptureAsset, ...]
    maximum_requests: int = MAX_REQUESTS_PER_CAPTURE
    maximum_response_bytes: int = MAX_RESPONSE_BYTES_PER_CAPTURE
    maximum_retained_bytes: int = MAX_RETAINED_BYTES

    def content(self) -> dict[str, object]:
        return {
            "schemaVersion": CONTRACT,
            "season": self.season,
            "assets": [asdict(item) for item in self.assets],
            "requestBudget": {"maximumRequests": self.maximum_requests,
                              "maximumResponseBytes": self.maximum_response_bytes},
            "storageBudget": {"maximumRetainedBytes": self.maximum_retained_bytes},
            "defaultMode": "DRY_RUN_NO_NETWORK",
            "retention": "raw bytes content-addressed by SHA-256; append-only receipt; unchanged bytes reused",
            "authority": "research evidence only; no model, forecast, AISP, exchange, or scheduler authority",
        }


def build_capture_plan(season: int = 2026) -> CapturePlan:
    if season < 2026:
        raise ValueError("V1 capture is prospective from 2026; historical replay is forbidden")
    base = "https://github.com/nflverse/nflverse-data/releases/download"
    assets = (
        CaptureAsset("schedules", "schedules", "games.parquet", f"{base}/schedules/games.parquet", "game identity and kickoff"),
        CaptureAsset("injuries", "injuries", f"injuries_{season}.parquet", f"{base}/injuries/injuries_{season}.parquet", "practice/game status"),
        CaptureAsset("weekly_rosters", "weekly_rosters", f"roster_weekly_{season}.parquet", f"{base}/weekly_rosters/roster_weekly_{season}.parquet", "roster identity/status"),
        CaptureAsset("depth_charts", "depth_charts", f"depth_charts_{season}.parquet", f"{base}/depth_charts/depth_charts_{season}.parquet", "expected role; source semantics must be reverified"),
        CaptureAsset("snap_counts", "snap_counts", f"snap_counts_{season}.parquet", f"{base}/snap_counts/snap_counts_{season}.parquet", "completed-prior-game role only"),
        CaptureAsset("players", "players", "players.parquet", f"{base}/players/players.parquet", "identity crosswalk"),
        CaptureAsset("draft_picks", "draft_picks", "draft_picks.parquet", f"{base}/draft_picks/draft_picks.parquet", "draft identity and pre-career facts only"),
    )
    return CapturePlan(season=season, assets=assets)


def _retained_bytes(root: Path) -> int:
    objects = root / "objects" / "sha256"
    return sum(path.stat().st_size for path in objects.glob("*/*") if path.is_file()) if objects.exists() else 0


def execute_capture(plan: CapturePlan, *, output_root: Path = DEFAULT_ROOT, allow_network: bool = False,
                    rights_approved: bool = False,
                    fetcher: Callable[[CaptureAsset, Mapping[str, str]], tuple[bytes | None, Mapping[str, str]]] | None = None,
                    captured_at_utc: str | None = None) -> dict[str, object]:
    """Capture exact bytes via an injected transport after explicit approval.

    The repository CLI supplies a standard-library HTTP transport only in its
    guarded execution mode.  Unit tests inject synthetic bytes and never touch
    the network.
    """
    if not allow_network or not rights_approved or fetcher is None:
        raise PermissionError("capture requires --execute, --rights-approved, and an explicit transport")
    if len(plan.assets) > plan.maximum_requests:
        raise RuntimeError("planned requests exceed the frozen request ceiling")
    root = Path(output_root).resolve()
    if ".git" in root.parts:
        raise RuntimeError("raw capture root must remain outside Git")
    retained_before = _retained_bytes(root)
    rows: list[dict[str, object]] = []
    source_states: list[tuple[Path, dict[str, object]]] = []
    response_bytes = 0
    new_retained_bytes = 0
    captured_at = captured_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for asset in plan.assets:
        source_key = hashlib.sha256(asset.url.encode("utf-8")).hexdigest()
        state_path = root / "source-state" / "sha256" / source_key / "current.json"
        prior = json.loads(state_path.read_bytes()) if state_path.exists() else None
        conditional = {}
        if prior and prior.get("etag"):
            conditional["If-None-Match"] = str(prior["etag"])
        if prior and prior.get("lastModified"):
            conditional["If-Modified-Since"] = str(prior["lastModified"])
        payload, headers = fetcher(asset, conditional)
        normalized_headers = {str(k).lower(): str(v) for k, v in headers.items()}
        if payload is None:
            if not prior:
                raise RuntimeError("not-modified response has no retained predecessor")
            digest = str(prior["physicalSha256"])
            destination = Path(str(prior["objectPath"])).resolve()
            if not destination.exists() or hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise RuntimeError("retained not-modified object is missing or corrupt")
            byte_count = int(prior["byteCount"])
            disposition = "REUSED_NOT_MODIFIED"
        else:
            response_bytes += len(payload)
            if response_bytes > plan.maximum_response_bytes:
                raise RuntimeError("capture response bytes exceed the frozen ceiling")
            digest = hashlib.sha256(payload).hexdigest()
            byte_count = len(payload)
            destination = root / "objects" / "sha256" / digest / asset.asset_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            disposition = "REUSED_IDENTICAL_OBJECT" if destination.exists() else "WRITTEN_NEW_OBJECT"
            if destination.exists() and destination.read_bytes() != payload:
                raise RuntimeError("content-address collision")
        if payload is not None and not destination.exists():
            if retained_before + new_retained_bytes + len(payload) > plan.maximum_retained_bytes:
                raise RuntimeError("retained evidence would exceed the storage ceiling")
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(destination)
            new_retained_bytes += len(payload)
        state = {"sourceUrl": asset.url, "releaseTag": asset.release_tag, "assetName": asset.asset_name,
                 "physicalSha256": digest, "byteCount": byte_count, "objectPath": str(destination),
                 "etag": normalized_headers.get("etag") or (prior or {}).get("etag"),
                 "lastModified": normalized_headers.get("last-modified") or (prior or {}).get("lastModified"),
                 "lastCheckedAtUtc": captured_at}
        source_states.append((state_path, state))
        rows.append({"familyId": asset.family_id, "releaseTag": asset.release_tag,
                     "assetName": asset.asset_name, "sourceUrl": asset.url,
                     "responseHeaders": {str(k).lower(): str(v) for k, v in sorted(headers.items())
                                         if str(k).lower() in {"etag", "last-modified", "content-type"}},
                     "retrievedAtUtc": captured_at, "physicalSha256": digest,
                     "byteCount": byte_count, "objectPath": str(destination),
                     "disposition": disposition, "licenseId": asset.license_id})
    current_path = root / "current.json"
    predecessor = None
    if current_path.exists():
        current = json.loads(current_path.read_bytes())
        predecessor = str(current["receiptSha256"])
        predecessor_path = Path(str(current["receiptPath"])).resolve()
        if not predecessor_path.exists() or hashlib.sha256(predecessor_path.read_bytes()).hexdigest() != predecessor:
            raise RuntimeError("capture predecessor pointer is missing or corrupt")
    receipt = {**plan.content(), "status": "CAPTURED", "capturedAtUtc": captured_at,
               "requestCount": len(rows), "responseBytes": response_bytes, "objects": rows,
               "predecessorReceiptSha256": predecessor}
    receipt_id = sha256_json(receipt)
    receipt_path = root / "receipts" / "sha256" / receipt_id / "receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json_bytes(receipt)
    if receipt_path.exists() and receipt_path.read_bytes() != raw:
        raise RuntimeError("receipt identity collision")
    if not receipt_path.exists():
        temporary = receipt_path.with_suffix(".tmp")
        temporary.write_bytes(raw)
        temporary.replace(receipt_path)
    for state_path, state in source_states:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_tmp = state_path.with_suffix(".tmp")
        state_tmp.write_bytes(canonical_json_bytes(state))
        state_tmp.replace(state_path)
    current_raw = canonical_json_bytes({"receiptSha256": receipt_id, "receiptPath": str(receipt_path)})
    current_tmp = current_path.with_suffix(".tmp")
    current_tmp.write_bytes(current_raw)
    current_tmp.replace(current_path)
    return {"receiptPath": str(receipt_path), "receiptSha256": hashlib.sha256(raw).hexdigest(),
            "requestCount": len(rows), "responseBytes": response_bytes,
            "newObjects": sum(row["disposition"] == "WRITTEN_NEW_OBJECT" for row in rows)}


__all__ = ["CaptureAsset", "CapturePlan", "CONTRACT", "DEFAULT_ROOT", "build_capture_plan", "execute_capture"]
