from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from server.sports_datasets.consumer import (
    canonical_json_bytes,
    raw_absolute_path,
    reject_reparse_chain,
    sha256_bytes,
    sha256_file,
)

from .source_contracts import (
    BRONZE_CURRENT_CONTRACT,
    BRONZE_MANIFEST_CONTRACT,
    NFLVERSE_SOURCE_FAMILIES,
    PROVIDER_ID,
    PROVIDER_REPOSITORY,
    BRONZE_MANIFEST_CONTRACT_V2,
    COVERAGE_POLICY_V2,
    CORE_2026_FAMILIES,
    source_families_for_manifest,
    source_contract_for_partition,
    SourceFamilyContract,
)


RELEASE_API = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags/{tag}"
OFFICIAL_DOWNLOAD_HOSTS = frozenset({"github.com", "objects.githubusercontent.com"})
MANIFEST_KEYS = frozenset({
    "contract", "version", "provider", "providerRepository", "sport", "seasons",
    "requestedFamilies", "partitions", "optionalMissing", "modelsFitted",
})
PARTITION_KEYS = frozenset({
    "familyId", "sourceContractVersion", "mandatory", "season", "releaseTag",
    "releasePublishedAt", "assetId", "assetUpdatedAt", "retrievedAt", "sourceDigest",
    "assetName", "sourceUrl", "license", "relativePath",
    "fileSha256", "byteCount", "rowCount", "physicalSchema", "physicalSchemaSha256",
    "coverage", "status",
})


class NflBronzeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseAsset:
    family_id: str
    release_tag: str
    release_published_at: str
    name: str
    source_url: str
    byte_count: int
    asset_id: int
    source_digest: str | None
    asset_updated_at: str
    retrieved_at: str


JsonFetcher = Callable[[str], Mapping[str, Any]]
UrlOpener = Callable[[urllib.request.Request], Any]
Clock = Callable[[], datetime]
ReleaseCache = dict[str, tuple[Mapping[str, Any], str]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_external_staging_root(root: Path) -> Path:
    absolute = raw_absolute_path(Path(root))
    repository = _repo_root()
    if absolute == repository or _is_relative_to(absolute, repository):
        raise NflBronzeError("NFL Bronze staging root must be external to the repository")
    reject_reparse_chain(absolute, label="NFL Bronze staging root")
    return absolute


def _safe_under(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or not posix.parts or any(part in {"", ".", ".."} for part in posix.parts):
        raise NflBronzeError("unsafe Bronze relative path")
    candidate = raw_absolute_path(root.joinpath(*posix.parts))
    if not _is_relative_to(candidate, root):
        raise NflBronzeError("Bronze path escapes staging root")
    reject_reparse_chain(candidate, label="NFL Bronze path")
    if must_exist and not candidate.is_file():
        raise NflBronzeError("declared Bronze file is missing")
    return candidate


def _validate_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise NflBronzeError(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NflBronzeError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise NflBronzeError(f"{label} must include a timezone")
    return value


def _validate_source_url(value: Any) -> str:
    if not isinstance(value, str):
        raise NflBronzeError("release asset URL is missing")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_DOWNLOAD_HOSTS:
        raise NflBronzeError("release asset URL is not an official HTTPS nflverse URL")
    if parsed.hostname == "github.com" and not parsed.path.startswith("/nflverse/nflverse-data/releases/download/"):
        raise NflBronzeError("GitHub asset URL is outside nflverse-data releases")
    return value


def _season_is_available(contract: SourceFamilyContract, season: int) -> bool:
    return not (
        (contract.available_start_season is not None and season < contract.available_start_season)
        or (contract.available_end_season is not None and season > contract.available_end_season)
    )


def _default_json_fetcher(url: str) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "asp-model-studio"})
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.load(response)
    if not isinstance(value, Mapping):
        raise NflBronzeError("release API returned a non-object")
    return value


def discover_release_asset(
    contract: SourceFamilyContract,
    season: int,
    *,
    json_fetcher: JsonFetcher = _default_json_fetcher,
    release_cache: ReleaseCache | None = None,
    clock: Clock = _utc_now,
) -> ReleaseAsset | None:
    if not _season_is_available(contract, season):
        return None
    cache = release_cache if release_cache is not None else {}
    cached = cache.get(contract.release_tag)
    if cached is None:
        payload = json_fetcher(RELEASE_API.format(tag=contract.release_tag))
        observed_at = clock()
        if observed_at.tzinfo is None:
            raise NflBronzeError("retrieval clock must be timezone-aware")
        retrieved_at = _validate_timestamp(observed_at.astimezone(timezone.utc).isoformat(), "retrieved_at")
        cache[contract.release_tag] = (payload, retrieved_at)
    else:
        payload, retrieved_at = cached
    if payload.get("tag_name") != contract.release_tag:
        raise NflBronzeError(f"release tag mismatch for {contract.family_id}")
    published = _validate_timestamp(payload.get("published_at"), "release published_at")
    pattern = re.compile(contract.asset_name_pattern.format(season=season))
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise NflBronzeError("release assets are missing")
    matches = [asset for asset in assets if isinstance(asset, Mapping) and pattern.fullmatch(str(asset.get("name", "")))]
    if not matches:
        if contract.mandatory:
            raise NflBronzeError(f"mandatory nflverse asset missing: {contract.family_id}/{season}")
        return None
    if len(matches) != 1:
        raise NflBronzeError(f"ambiguous nflverse asset: {contract.family_id}/{season}")
    asset = matches[0]
    byte_count = asset.get("size")
    if not isinstance(byte_count, int) or byte_count < 0:
        raise NflBronzeError("release asset byte size is invalid")
    asset_id = asset.get("id")
    if not isinstance(asset_id, int) or asset_id <= 0:
        raise NflBronzeError("release asset id is invalid")
    asset_updated_at = _validate_timestamp(asset.get("updated_at"), "asset updated_at")
    digest = asset.get("digest")
    if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)):
        raise NflBronzeError("release asset digest is invalid")
    return ReleaseAsset(
        family_id=contract.family_id,
        release_tag=contract.release_tag,
        release_published_at=published,
        name=str(asset["name"]),
        source_url=_validate_source_url(asset.get("browser_download_url")),
        byte_count=byte_count,
        asset_id=asset_id,
        source_digest=digest,
        asset_updated_at=asset_updated_at,
        retrieved_at=retrieved_at,
    )


def _status(response: Any) -> int:
    value = getattr(response, "status", None)
    if value is None:
        value = response.getcode()
    return int(value)


def download_release_asset(
    asset: ReleaseAsset,
    destination: Path,
    *,
    opener: UrlOpener = urllib.request.urlopen,
    chunk_size: int = 1024 * 1024,
) -> Path:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    reject_reparse_chain(destination, label="NFL Bronze destination")
    partial = destination.with_name(destination.name + ".part")
    reject_reparse_chain(partial, label="NFL Bronze partial download")
    if destination.exists():
        if destination.stat().st_size != asset.byte_count:
            raise NflBronzeError("existing Bronze asset has unexpected byte size")
        if asset.source_digest and sha256_file(destination, logical_uri=f"nfl-bronze:{asset.family_id}") != asset.source_digest.removeprefix("sha256:"):
            raise NflBronzeError("existing Bronze asset does not match the upstream SHA-256 digest")
        return destination
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > asset.byte_count:
        raise NflBronzeError("partial download is larger than the release asset")
    headers = {"Accept": "application/octet-stream", "User-Agent": "asp-model-studio"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(asset.source_url, headers=headers)
    response = opener(request)
    try:
        status = _status(response)
        mode = "ab"
        if offset:
            if status == 206:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {offset}-"):
                    raise NflBronzeError("resume response has the wrong Content-Range")
            elif status == 200:
                offset = 0
                mode = "wb"
            else:
                raise NflBronzeError(f"resume request returned HTTP {status}")
        elif status not in {200, 206}:
            raise NflBronzeError(f"download returned HTTP {status}")
        with partial.open(mode) as output:
            while True:
                block = response.read(chunk_size)
                if not block:
                    break
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
    finally:
        close = getattr(response, "close", None)
        if close:
            close()
    if partial.stat().st_size != asset.byte_count:
        raise NflBronzeError("downloaded Bronze asset byte count does not match release metadata")
    if asset.source_digest and sha256_file(partial, logical_uri=f"nfl-bronze:{asset.family_id}") != asset.source_digest.removeprefix("sha256:"):
        raise NflBronzeError("downloaded Bronze asset does not match the upstream SHA-256 digest")
    os.replace(partial, destination)
    return destination


def _schema_value(schema: pa.Schema) -> list[dict[str, Any]]:
    return [{"name": field.name, "arrowType": str(field.type), "nullable": field.nullable} for field in schema]


def _scalar_text(value: Any) -> str | int | float | bool | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def inspect_parquet(path: Path, contract: SourceFamilyContract, season: int) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    missing = [name for name in contract.required_columns if name not in schema.names]
    if missing:
        raise NflBronzeError(f"{contract.family_id} missing required columns: {', '.join(missing)}")
    physical_schema = _schema_value(schema)
    coverage: dict[str, Any] = {"requestedSeason": season}
    columns = [name for name in (contract.season_column, contract.date_column) if name]
    missing_coverage_columns = [name for name in columns if name not in schema.names]
    if missing_coverage_columns:
        raise NflBronzeError(
            f"{contract.family_id} missing coverage columns: {', '.join(missing_coverage_columns)}"
        )
    table = parquet.read(columns=columns) if columns else None
    if contract.season_column:
        values = {int(value.as_py()) for value in pc.unique(table[contract.season_column]) if value.as_py() is not None}
        if contract.season_scoped and values and values != {season}:
            raise NflBronzeError(f"{contract.family_id} contains out-of-scope seasons")
        coverage["seasons"] = sorted(values)
        coverage["rowCountsBySeason"] = [
            {"season": int(item["values"]), "rowCount": int(item["counts"])}
            for item in sorted(
                (
                    item for item in pc.value_counts(table[contract.season_column]).to_pylist()
                    if item["values"] is not None
                ),
                key=lambda item: int(item["values"]),
            )
        ]
    else:
        coverage["seasons"] = []
        coverage["rowCountsBySeason"] = []
    if contract.date_column:
        non_null = pc.drop_null(table[contract.date_column])
        coverage["minimumDate"] = _scalar_text(pc.min(non_null).as_py()) if len(non_null) else None
        coverage["maximumDate"] = _scalar_text(pc.max(non_null).as_py()) if len(non_null) else None
    else:
        coverage["minimumDate"] = None
        coverage["maximumDate"] = None
    return {
        "rowCount": parquet.metadata.num_rows,
        "physicalSchema": physical_schema,
        "physicalSchemaSha256": sha256_bytes(canonical_json_bytes(physical_schema)),
        "coverage": coverage,
    }


def _partition_relative(contract: SourceFamilyContract, season: int, asset: ReleaseAsset) -> str:
    scope = f"season={season}" if contract.season_scoped else "all-seasons"
    digest_identity = (
        asset.source_digest.removeprefix("sha256:")
        if asset.source_digest else "github-digest-unavailable"
    )
    updated_identity = sha256_bytes(asset.asset_updated_at.encode("utf-8"))[:16]
    return (
        f"objects/{contract.family_id}/{scope}/{asset.release_tag}/"
        f"asset={asset.asset_id}/updated={updated_identity}/sha256={digest_identity}/{asset.name}"
    )


def _partition_record(root: Path, contract: SourceFamilyContract, season: int, asset: ReleaseAsset, path: Path) -> dict[str, Any]:
    inspected = inspect_parquet(path, contract, season)
    return {
        "familyId": contract.family_id,
        "sourceContractVersion": contract.contract_version,
        "mandatory": contract.mandatory,
        "season": season if contract.season_scoped else None,
        "releaseTag": asset.release_tag,
        "releasePublishedAt": asset.release_published_at,
        "assetId": asset.asset_id,
        "assetUpdatedAt": asset.asset_updated_at,
        "retrievedAt": asset.retrieved_at,
        "sourceDigest": asset.source_digest,
        "assetName": asset.name,
        "sourceUrl": asset.source_url,
        "license": {
            "id": contract.license_id, "name": contract.license_name,
            "url": contract.license_url, "attribution": contract.attribution,
        },
        "relativePath": path.relative_to(root).as_posix(),
        "fileSha256": sha256_file(path, logical_uri=f"nfl-bronze:{contract.family_id}"),
        "byteCount": path.stat().st_size,
        **inspected,
        "status": "COMPLETE",
    }


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(canonical_json_bytes(value))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def acquire_nflverse_bronze(
    staging_root: Path,
    seasons: Iterable[int],
    *,
    family_ids: Iterable[str] | None = None,
    json_fetcher: JsonFetcher = _default_json_fetcher,
    opener: UrlOpener = urllib.request.urlopen,
    clock: Clock = _utc_now,
) -> str:
    root = validate_external_staging_root(staging_root)
    root.mkdir(parents=True, exist_ok=True)
    previous_by_identity: dict[
        tuple[str, int | None, int, str | None, str, str, str, str], str
    ] = {}
    if (root / "current.json").is_file():
        previous = verify_nflverse_bronze(root)
        for item in previous["partitions"]:
            previous_by_identity[(
                item["familyId"], item["season"], item["assetId"],
                item["sourceDigest"], item["assetUpdatedAt"],
                item["releasePublishedAt"], item["sourceUrl"], item["relativePath"],
            )] = item["retrievedAt"]
    requested_seasons = tuple(sorted(set(int(value) for value in seasons)))
    if not requested_seasons:
        raise NflBronzeError("at least one NFL season is required")
    requested = tuple(family_ids or NFLVERSE_SOURCE_FAMILIES.keys())
    if len(set(requested)) != len(requested) or any(value not in NFLVERSE_SOURCE_FAMILIES for value in requested):
        raise NflBronzeError("requested NFL source families are invalid")
    partitions: list[dict[str, Any]] = []
    optional_missing: list[dict[str, Any]] = []
    release_cache: ReleaseCache = {}
    for family_id in requested:
        contract = NFLVERSE_SOURCE_FAMILIES[family_id]
        available_requested = tuple(
            season for season in requested_seasons if _season_is_available(contract, season)
        )
        family_seasons = (
            available_requested
            if contract.season_scoped
            else ((available_requested[-1],) if available_requested else ())
        )
        if contract.mandatory and not family_seasons:
            raise NflBronzeError(f"requested seasons do not intersect mandatory family coverage: {family_id}")
        for season in family_seasons:
            contract = source_contract_for_partition(NFLVERSE_SOURCE_FAMILIES, family_id,
                                                     season if contract.season_scoped else None)
            stage = "SOURCE_DISCOVERY"
            try:
                asset = discover_release_asset(
                    contract, season, json_fetcher=json_fetcher,
                    release_cache=release_cache, clock=clock,
                )
            except (NflBronzeError, OSError, ValueError):
                if contract.mandatory:
                    raise
                optional_missing.append({
                    "familyId": family_id,
                    "season": season if contract.season_scoped else None,
                    "reason": f"{stage}_FAILURE",
                })
                continue
            if asset is None:
                if contract.mandatory:
                    raise NflBronzeError(
                        f"mandatory NFL release asset is absent: family={family_id}, season={season}"
                    )
                optional_missing.append({"familyId": family_id, "season": season if contract.season_scoped else None, "reason": "RELEASE_ASSET_ABSENT"})
                continue
            try:
                stage = "DOWNLOAD"
                relative = _partition_relative(contract, season, asset)
                path = _safe_under(root, relative)
                download_release_asset(asset, path, opener=opener)
                prior_retrieved_at = previous_by_identity.get((
                    contract.family_id, season if contract.season_scoped else None,
                    asset.asset_id, asset.source_digest, asset.asset_updated_at,
                    asset.release_published_at, asset.source_url, relative,
                ))
                if prior_retrieved_at is not None:
                    asset = replace(asset, retrieved_at=prior_retrieved_at)
                stage = "SCHEMA_INSPECTION"
                partitions.append(_partition_record(root, contract, season, asset, path))
            except (NflBronzeError, OSError, ValueError):
                if contract.mandatory:
                    raise
                optional_missing.append({
                    "familyId": family_id,
                    "season": season if contract.season_scoped else None,
                    "reason": f"{stage}_FAILURE",
                })
    manifest = {
        "contract": BRONZE_MANIFEST_CONTRACT_V2,
        "version": 2,
        "coveragePolicy": COVERAGE_POLICY_V2,
        "provider": PROVIDER_ID,
        "providerRepository": PROVIDER_REPOSITORY,
        "sport": "NFL",
        "seasons": list(requested_seasons),
        "requestedFamilies": list(requested),
        "partitions": sorted(partitions, key=lambda item: (item["familyId"], item["season"] or 0, item["assetName"])),
        "optionalMissing": sorted(optional_missing, key=lambda item: (item["familyId"], item["season"] or 0)),
        "modelsFitted": 0,
    }
    manifest_sha = sha256_bytes(canonical_json_bytes(manifest))
    manifest_path = _safe_under(root, f"manifests/sha256/{manifest_sha}/manifest.json")
    if manifest_path.exists() and manifest_path.read_bytes() != canonical_json_bytes(manifest):
        raise NflBronzeError("content-addressed Bronze manifest collision")
    if not manifest_path.exists():
        _atomic_json(manifest_path, manifest)
    verify_nflverse_bronze(root, manifest_sha)
    _atomic_json(root / "current.json", {
        "contract": BRONZE_CURRENT_CONTRACT,
        "manifestSha256": manifest_sha,
        "manifestRelativePath": manifest_path.relative_to(root).as_posix(),
    })
    return manifest_sha


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NflBronzeError("invalid NFL Bronze JSON authority") from exc
    if not isinstance(value, dict):
        raise NflBronzeError("NFL Bronze JSON authority must be an object")
    return value


# Observed official release metadata, not invented source availability. The
# container publication clocks predate this season and are retained separately
# from each asset update and this task's actual retrieval clock.
CORE_2026_RELEASE_PINS = (
    ("play_by_play", "pbp", "play_by_play_2026.parquet", 561296169, 294820,
     "19d4f814ec030d9cba5822ba018c412acf2c4701b12bc9b97c5326bd423493e8",
     "2022-01-28T02:12:09Z", "2026-09-13T13:48:37Z"),
    ("weekly_player_stats", "stats_player", "stats_player_week_2026.parquet", 561298428, 71654,
     "5fd9d3d6797db82a962b6239b2cc65449e5d1267ee90c4672e00223f44fdfa8e",
     "2025-07-31T18:47:44Z", "2026-09-13T13:50:13Z"),
    ("weekly_team_stats", "stats_team", "stats_team_week_2026.parquet", 561298494, 52692,
     "bd257f2aabcf0f6943621adbe0a41cb80ff28b4934ee37073f99b39f6b05536c",
     "2025-07-31T18:48:46Z", "2026-09-13T13:50:16Z"),
)
CORE_2026_MAX_ASSET_REQUESTS = 3
CORE_2026_MAX_BYTES = 419166


def acquire_nflverse_current_core_2026(
    staging_root: Path, *, opener: UrlOpener = urllib.request.urlopen,
    clock: Clock = _utc_now,
    lock_path: Path = Path(r".runtime\asp-model-studio\locks\nfl-current-season-sync.lock"),
) -> dict[str, Any]:
    """Append the three pinned current assets; no historical/provider rescan.

    Uses the existing sync owner lock and Bronze acquisition/verification path.
    Historical and optional partition records remain byte-equivalent. No model
    is loaded or run. A changed upstream asset fails its pinned digest/size;
    it does not silently expand this intake or authorize further requests.
    """
    from server.sports_cockpit.interprocess_lock import interprocess_lock

    root = validate_external_staging_root(staging_root)
    with interprocess_lock(lock_path, blocking=False, stale_after=12 * 60 * 60):
        before_pointer = (root / "current.json").read_bytes()
        previous_sha = json.loads(before_pointer)["manifestSha256"]
        previous = verify_nflverse_bronze(root, previous_sha)
        if 2026 not in previous["seasons"] or not set(CORE_2026_FAMILIES).issubset(previous["requestedFamilies"]):
            raise NflBronzeError("Existing governed Bronze must already declare 2026 and all core families")
        started = _validate_timestamp(clock().isoformat(), "intake startedAt")
        usage = {"assetRequests": 0, "downloadedBytes": 0, "maxAssetRequests": CORE_2026_MAX_ASSET_REQUESTS,
                 "maxDownloadedBytes": CORE_2026_MAX_BYTES, "providerCostUsd": 0,
                 "metadataRequests": 0, "source": "PINNED_OFFICIAL_METADATA_OBSERVED_2026-09-13T19:01:25Z"}
        pins_sha = sha256_bytes(canonical_json_bytes(CORE_2026_RELEASE_PINS))
        usage_path = _safe_under(root, "current-core-2026-intake-usage-v1.json")
        if usage_path.exists():
            ledger = _load_object(usage_path)
            if ledger.get("pinsSha256") != pins_sha or ledger.get("contract") != "NFLVERSE_CURRENT_CORE_INTAKE_USAGE_V1":
                raise NflBronzeError("Current-core allowance ledger identity differs")
            saved = ledger["usage"]
            for key in usage:
                if key not in ("assetRequests", "downloadedBytes") and saved.get(key) != usage[key]:
                    raise NflBronzeError("Current-core allowance limits differ")
            usage = dict(saved)
            if not (0 <= usage["assetRequests"] <= CORE_2026_MAX_ASSET_REQUESTS
                    and 0 <= usage["downloadedBytes"] <= CORE_2026_MAX_BYTES):
                raise NflBronzeError("Current-core allowance already exhausted or invalid")
        initial_usage = dict(usage)

        def retain_usage():
            _atomic_json(usage_path, {"contract":"NFLVERSE_CURRENT_CORE_INTAKE_USAGE_V1",
                "pinsSha256":pins_sha,"updatedAtUtc":_validate_timestamp(clock().isoformat(), "usage updatedAt"),
                "usage":usage})
        allowed = {f"https://github.com/nflverse/nflverse-data/releases/download/{pin[1]}/{pin[2]}": pin[4]
                   for pin in CORE_2026_RELEASE_PINS}

        class LimitedResponse:
            def __init__(self, response, maximum):
                self.response, self.maximum, self.used = response, maximum, 0
                self.headers = response.headers
                self.status = _status(response)
            def read(self, size=-1):
                # Read at most one byte beyond the bound to detect overflow.
                limit = min(self.maximum-self.used, CORE_2026_MAX_BYTES-usage["downloadedBytes"]) + 1
                block = self.response.read(limit if size < 0 else min(size, limit))
                self.used += len(block)
                usage["downloadedBytes"] += len(block)
                retain_usage()
                if self.used > self.maximum or usage["downloadedBytes"] > CORE_2026_MAX_BYTES:
                    raise NflBronzeError("Bounded current-core download byte allowance exceeded")
                return block
            def close(self):
                self.response.close()

        def bounded_opener(request):
            if request.full_url not in allowed or usage["assetRequests"] >= CORE_2026_MAX_ASSET_REQUESTS:
                raise NflBronzeError("Bounded current-core request scope exceeded")
            usage["assetRequests"] += 1
            retain_usage()  # Count attempted requests durably, including failures.
            return LimitedResponse(opener(request), allowed[request.full_url])

        targets = {(family, 2026) for family in CORE_2026_FAMILIES}
        records = {(p["familyId"], p["season"]): p for p in previous["partitions"]}
        added = []
        for family, tag, name, asset_id, size, digest, published, updated in CORE_2026_RELEASE_PINS:
            contract = NFLVERSE_SOURCE_FAMILIES[family]
            old = records.get((family, 2026))
            if old is not None:
                if (old["assetId"], old["sourceDigest"], old["assetUpdatedAt"], old["byteCount"]) != (asset_id, "sha256:"+digest, updated, size):
                    raise NflBronzeError("Newer/different current-core evidence already exists; pinned intake must not replace it")
                added.append(old)
                continue
            captured = _validate_timestamp(clock().isoformat(), "asset capture")
            asset = ReleaseAsset(family, tag, published, name,
                f"https://github.com/nflverse/nflverse-data/releases/download/{tag}/{name}",
                size, asset_id, "sha256:"+digest, updated, captured)
            # Reuse discovery's exact schema/name validation without another
            # network call; source bytes still must match the upstream digest.
            discovered = discover_release_asset(contract, 2026, clock=clock,
                json_fetcher=lambda url, a=asset: {"tag_name":a.release_tag,
                    "published_at":a.release_published_at,"assets":[{"name":a.name,"id":a.asset_id,
                    "size":a.byte_count,"updated_at":a.asset_updated_at,"digest":a.source_digest,
                    "browser_download_url":a.source_url}]})
            if discovered is None:
                raise NflBronzeError("Pinned current-core discovery failed")
            path = _safe_under(root, _partition_relative(contract, 2026, asset))
            download_release_asset(asset, path, opener=bounded_opener)
            # Retrieval metadata follows completion, never a historical clock.
            asset = replace(asset, retrieved_at=_validate_timestamp(clock().isoformat(), "asset retrievedAt"))
            added.append(_partition_record(root, contract, 2026, asset, path))
        preserved = [p for p in previous["partitions"] if (p["familyId"],p["season"]) not in targets]
        manifest = {**previous, "contract":BRONZE_MANIFEST_CONTRACT_V2,"version":2,
            "coveragePolicy":COVERAGE_POLICY_V2,
            "partitions":sorted(preserved+added,key=lambda p:(p["familyId"],p["season"] or 0,p["assetName"]))}
        if [p for p in manifest["partitions"] if (p["familyId"],p["season"]) not in targets] != preserved:
            raise NflBronzeError("Historical/optional partition records changed")
        raw = canonical_json_bytes(manifest)
        manifest_sha = sha256_bytes(raw)
        relative = f"manifests/sha256/{manifest_sha}/manifest.json"
        path = _safe_under(root, relative)
        if path.exists() and path.read_bytes() != raw:
            raise NflBronzeError("Content-addressed Bronze manifest collision")
        if not path.exists():
            _atomic_json(path, manifest)
        verify_nflverse_bronze(root, manifest_sha)
        if (root/"current.json").read_bytes() != before_pointer:
            raise NflBronzeError("Bronze authority advanced during bounded intake")
        _atomic_json(root/"current.json",{"contract":BRONZE_CURRENT_CONTRACT,
            "manifestSha256":manifest_sha,"manifestRelativePath":relative})
        return {"contract":"NFLVERSE_CURRENT_CORE_2026_INTAKE_V1","startedAtUtc":started,
            "completedAtUtc":_validate_timestamp(clock().isoformat(), "intake completedAt"),
            "previousManifestSha256":previous_sha,"manifestSha256":manifest_sha,
            "coveragePolicy":COVERAGE_POLICY_V2,"preservedPartitionCount":len(preserved),
            "currentCorePartitions":added,"usage":usage,"modelsFitted":0,
            "thisRunUsage":{"assetRequests":usage["assetRequests"]-initial_usage["assetRequests"],
                "downloadedBytes":usage["downloadedBytes"]-initial_usage["downloadedBytes"]},
            "usageLedgerRelativePath":usage_path.relative_to(root).as_posix(),"releasePinsSha256":pins_sha,
            "releaseMetadataEvidence":{"type":"RECORDED_OFFICIAL_API_FIELDS_RAW_RESPONSE_NOT_RETAINED",
                "observedAtUtcByTag":{"pbp":"2026-09-13T19:01:25.584864+00:00",
                    "stats_player":"2026-09-13T19:01:26.215678+00:00",
                    "stats_team":"2026-09-13T19:01:26.838469+00:00"},
                "apiUrls":[RELEASE_API.format(tag=p[1]) for p in CORE_2026_RELEASE_PINS],
                "originalMetadataRequests":3,"originalMetadataResponseBytes":1889129,
                "clockMeaning":"Release-container publication, asset update, metadata observation and payload retrieval are distinct"},
            "historicalPartitionRecordsUnchanged":True,"optionalMissingUnchanged":True}


def verify_nflverse_bronze(staging_root: Path, manifest_sha256: str | None = None) -> dict[str, Any]:
    root = validate_external_staging_root(staging_root)
    if manifest_sha256 is None:
        current = _load_object(_safe_under(root, "current.json", must_exist=True))
        if set(current) != {"contract", "manifestSha256", "manifestRelativePath"} or current["contract"] != BRONZE_CURRENT_CONTRACT:
            raise NflBronzeError("invalid NFL Bronze current locator")
        manifest_sha256 = current["manifestSha256"]
        expected_relative = f"manifests/sha256/{manifest_sha256}/manifest.json"
        if current["manifestRelativePath"] != expected_relative:
            raise NflBronzeError("NFL Bronze current locator path mismatch")
    if not isinstance(manifest_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise NflBronzeError("invalid NFL Bronze manifest SHA")
    manifest_path = _safe_under(root, f"manifests/sha256/{manifest_sha256}/manifest.json", must_exist=True)
    if sha256_file(manifest_path, logical_uri="nfl-bronze:manifest") != manifest_sha256:
        raise NflBronzeError("NFL Bronze manifest content address mismatch")
    manifest = _load_object(manifest_path)
    try:
        families = source_families_for_manifest(manifest)
    except ValueError as exc:
        raise NflBronzeError(str(exc)) from exc
    expected_manifest_keys = MANIFEST_KEYS | ({"coveragePolicy"} if manifest["version"] == 2 else set())
    if set(manifest) != expected_manifest_keys:
        raise NflBronzeError("NFL Bronze manifest has an invalid schema")
    if manifest["provider"] != PROVIDER_ID or manifest["sport"] != "NFL" or manifest["modelsFitted"] != 0:
        raise NflBronzeError("NFL Bronze manifest identity mismatch")
    if manifest["providerRepository"] != PROVIDER_REPOSITORY:
        raise NflBronzeError("NFL Bronze provider repository mismatch")
    seasons = manifest["seasons"]
    requested = manifest["requestedFamilies"]
    if not isinstance(seasons, list) or seasons != sorted(set(seasons)) or not seasons:
        raise NflBronzeError("NFL Bronze seasons are invalid")
    if not isinstance(requested, list) or len(requested) != len(set(requested)) or any(value not in families for value in requested):
        raise NflBronzeError("NFL Bronze requested families are invalid")
    seen: set[tuple[str, int | None]] = set()
    if not isinstance(manifest["partitions"], list) or not isinstance(manifest["optionalMissing"], list):
        raise NflBronzeError("NFL Bronze partition outcomes must be lists")
    for partition in manifest["partitions"]:
        if not isinstance(partition, dict) or set(partition) != PARTITION_KEYS:
            raise NflBronzeError("NFL Bronze partition schema is invalid")
        contract = families.get(partition["familyId"])
        if contract is None or partition["familyId"] not in requested:
            raise NflBronzeError("NFL Bronze partition family is not authorized")
        contract = source_contract_for_partition(families, partition["familyId"], partition["season"])
        key = (contract.family_id, partition["season"])
        if key in seen:
            raise NflBronzeError("duplicate NFL Bronze family/season partition")
        seen.add(key)
        expected_season = partition["season"]
        if contract.season_scoped and expected_season not in seasons:
            raise NflBronzeError("NFL Bronze partition season is out of scope")
        if not contract.season_scoped and expected_season is not None:
            raise NflBronzeError("all-season NFL Bronze partition has a season")
        if partition["sourceContractVersion"] != contract.contract_version or partition["mandatory"] != contract.mandatory:
            raise NflBronzeError("NFL Bronze source contract mismatch")
        if partition["releaseTag"] != contract.release_tag or partition["status"] != "COMPLETE":
            raise NflBronzeError("NFL Bronze release/status mismatch")
        season_for_pattern = (
            partition["season"]
            if partition["season"] is not None
            else int((partition.get("coverage") or {}).get("requestedSeason", seasons[-1]))
        )
        if season_for_pattern not in seasons or not _season_is_available(contract, season_for_pattern):
            raise NflBronzeError("all-season NFL Bronze requested-season evidence is out of scope")
        if not re.fullmatch(contract.asset_name_pattern.format(season=season_for_pattern), str(partition["assetName"])):
            raise NflBronzeError("NFL Bronze asset name does not satisfy its source contract")
        _validate_timestamp(partition["releasePublishedAt"], "releasePublishedAt")
        if not isinstance(partition["assetId"], int) or partition["assetId"] <= 0:
            raise NflBronzeError("NFL Bronze asset id is invalid")
        _validate_timestamp(partition["assetUpdatedAt"], "assetUpdatedAt")
        _validate_timestamp(partition["retrievedAt"], "retrievedAt")
        source_digest = partition["sourceDigest"]
        if source_digest is not None and (not isinstance(source_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", source_digest)):
            raise NflBronzeError("NFL Bronze upstream digest is invalid")
        source_url = _validate_source_url(partition["sourceUrl"])
        if source_url != f"https://github.com/nflverse/nflverse-data/releases/download/{contract.release_tag}/{partition['assetName']}":
            raise NflBronzeError("NFL Bronze source URL does not bind the declared release asset")
        expected_license = {"id": contract.license_id, "name": contract.license_name, "url": contract.license_url, "attribution": contract.attribution}
        if partition["license"] != expected_license:
            raise NflBronzeError("NFL Bronze license metadata mismatch")
        path = _safe_under(root, partition["relativePath"], must_exist=True)
        if path.name != partition["assetName"] or path.stat().st_size != partition["byteCount"]:
            raise NflBronzeError("NFL Bronze asset identity/size mismatch")
        if sha256_file(path, logical_uri=f"nfl-bronze:{contract.family_id}") != partition["fileSha256"]:
            raise NflBronzeError("NFL Bronze asset SHA mismatch")
        if source_digest and partition["fileSha256"] != source_digest.removeprefix("sha256:"):
            raise NflBronzeError("NFL Bronze asset does not match its upstream SHA-256 digest")
        inspected = inspect_parquet(path, contract, season_for_pattern)
        for field in ("rowCount", "physicalSchema", "physicalSchemaSha256", "coverage"):
            if partition[field] != inspected[field]:
                raise NflBronzeError(
                    f"NFL Bronze {field} verification failed: "
                    f"family={contract.family_id}, season={expected_season}"
                )
    missing_records: set[tuple[str, int | None]] = set()
    optional_outcomes = {
        "RELEASE_ASSET_ABSENT",
        "SOURCE_DISCOVERY_FAILURE",
        "DOWNLOAD_FAILURE",
        "SCHEMA_INSPECTION_FAILURE",
    }
    for item in manifest["optionalMissing"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"familyId", "season", "reason"}
            or item["reason"] not in optional_outcomes
        ):
            raise NflBronzeError("invalid optional-missing authority")
        contract = families.get(item["familyId"])
        if contract is None or contract.mandatory or item["familyId"] not in requested:
            raise NflBronzeError("mandatory/unknown family declared optional-missing")
        key = (contract.family_id, item["season"])
        if key in seen or key in missing_records:
            raise NflBronzeError("conflicting optional-missing authority")
        missing_records.add(key)
    for family_id in requested:
        contract = families[family_id]
        expected_keys = (
            {(family_id, season) for season in seasons if _season_is_available(contract, season)}
            if contract.season_scoped else {(family_id, None)}
        )
        if contract.mandatory and not expected_keys.issubset(seen):
            raise NflBronzeError(f"mandatory NFL Bronze family incomplete: {family_id}")
        if not contract.mandatory and not expected_keys.issubset(seen | missing_records):
            raise NflBronzeError(f"optional NFL Bronze family lacks an explicit outcome: {family_id}")
    return manifest


def focused_current_core_checks() -> dict[str, Any]:
    """Tiny synthetic contracts; no provider, estimator or real outcome access."""
    from .source_contracts import NFLVERSE_SOURCE_FAMILIES_V1
    from .current_season_sync import NflCurrentSeasonSyncConfig, _available_seasons
    from .pipeline import NflFoundationConfig
    checks = {}
    cfg = NflCurrentSeasonSyncConfig(foundation=NflFoundationConfig(seasons=(2025, 2026)))
    checks["v1CoreEnds2025"] = all(NFLVERSE_SOURCE_FAMILIES_V1[f].available_end_season == 2025 for f in CORE_2026_FAMILIES)
    checks["v2CoreProbes2026"] = all(_available_seasons(cfg, NFLVERSE_SOURCE_FAMILIES[f]) == (2026,) for f in CORE_2026_FAMILIES)
    checks["v1ScopeUnchanged"] = all(_available_seasons(cfg, NFLVERSE_SOURCE_FAMILIES_V1[f]) == () for f in CORE_2026_FAMILIES)
    checks["optionalPoliciesUnchanged"] = all(NFLVERSE_SOURCE_FAMILIES[f] == c for f,c in NFLVERSE_SOURCE_FAMILIES_V1.items() if f not in CORE_2026_FAMILIES)
    checks["pinnedBudget"] = sum(p[4] for p in CORE_2026_RELEASE_PINS) == CORE_2026_MAX_BYTES and len(CORE_2026_RELEASE_PINS) == CORE_2026_MAX_ASSET_REQUESTS
    with tempfile.TemporaryDirectory(prefix="nfl-current-core-contract-") as temporary:
        root = validate_external_staging_root(Path(temporary))
        parts = []
        for season in (2025,2026):
            for family in CORE_2026_FAMILIES:
                contract = source_contract_for_partition(NFLVERSE_SOURCE_FAMILIES, family, season)
                data = {"season":[season]}
                for column in contract.required_columns:
                    if column not in data:
                        data[column] = [1 if column in {"play_id","week"} else "SYNTHETIC_ID"]
                if contract.date_column:
                    data[contract.date_column] = [f"{season}-09-01"]
                name = contract.asset_name_pattern.format(season=season).removeprefix("^").removesuffix("$").replace("\\.",".")
                path = root/"fixtures"/family/name
                path.parent.mkdir(parents=True,exist_ok=True)
                pq.write_table(pa.table(data),path)
                digest = sha256_file(path,logical_uri="synthetic")
                asset = ReleaseAsset(family,contract.release_tag,"2026-09-13T00:00:00Z",name,
                    f"https://github.com/nflverse/nflverse-data/releases/download/{contract.release_tag}/{name}",
                    path.stat().st_size,1,"sha256:"+digest,"2026-09-13T00:00:00Z","2026-09-13T00:00:00Z")
                parts.append(_partition_record(root,contract,season,asset,path))
        def put(manifest):
            raw=canonical_json_bytes(manifest);digest=sha256_bytes(raw)
            _atomic_json(root/f"manifests/sha256/{digest}/manifest.json",manifest)
            return digest
        old={"contract":BRONZE_MANIFEST_CONTRACT,"version":1,"provider":PROVIDER_ID,
            "providerRepository":PROVIDER_REPOSITORY,"sport":"NFL","seasons":[2025,2026],
            "requestedFamilies":list(CORE_2026_FAMILIES),"partitions":[p for p in parts if p["season"]==2025],
            "optionalMissing":[],"modelsFitted":0}
        old_sha=put(old)
        checks["oldV1StillVerifies"] = verify_nflverse_bronze(root,old_sha) == old
        new={**old,"contract":BRONZE_MANIFEST_CONTRACT_V2,"version":2,"coveragePolicy":COVERAGE_POLICY_V2,"partitions":parts}
        new_sha=put(new)
        checks["newV2CompleteVerifies"] = verify_nflverse_bronze(root,new_sha) == new
        checks["oldV1VerifiesAfterV2"] = verify_nflverse_bronze(root,old_sha) == old
        cases={"v2MissingCurrentRejected":{**new,"partitions":old["partitions"]},
            "v1CurrentNotSmuggled":{**old,"partitions":parts},
            "wrongCoveragePolicyRejected":{**new,"coveragePolicy":"UNKNOWN"},
            "wrongPartitionVersionRejected":{**new,"partitions":[{**p,"sourceContractVersion":"NFLVERSE_SOURCE_FAMILY_V1"} if p["season"]==2026 else p for p in parts]}}
        for name,manifest in cases.items():
            try:
                verify_nflverse_bronze(root,put(manifest))
            except NflBronzeError:
                checks[name]=True
            else:
                checks[name]=False
    if not all(checks.values()):
        raise AssertionError(checks)
    return {"contract":"NFLVERSE_CURRENT_CORE_FOCUSED_CHECKS_V1","data":"SYNTHETIC_ONLY",
        "allPassed":True,"checks":checks,"providerRequests":0,"modelsFitted":0}
