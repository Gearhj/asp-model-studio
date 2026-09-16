from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OUTPUT_ROOT = Path("outputs/cfb-gen1-v1")
MAX_NEW_BYTES = 150 * 1024 * 1024
REPOSITORY = "sportsdataverse/sportsdataverse-data"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}/releases/tags"
USER_AGENT = "asp-model-studio-cfb-gen1-private-research/1.0"

RELEASES = {
    "espn_cfb_schedules": {
        "seasons": range(2014, 2027),
        "asset": "cfb_schedule_{season}.parquet",
        "purpose": "schedule, identity, status, orientation, final score and current-season targets",
    },
    "espn_cfb_team_box": {
        "seasons": range(2014, 2026),
        "asset": "team_box_{season}.parquet",
        "purpose": "completed-game team box statistics for chronological features",
    },
    "espn_cfb_teams": {
        "seasons": range(2014, 2027),
        "asset": "cfb_teams_{season}.parquet",
        "purpose": "season-aware team, conference and division identity",
    },
    "espn_cfb_linescores": {
        "seasons": range(2014, 2026),
        "asset": "linescores_{season}.parquet",
        "purpose": "small retained period-score asset for overtime and score reconciliation",
    },
}

EVIDENCE_URLS = {
    "sportsdataverse-data-README.Rmd":
        "https://raw.githubusercontent.com/sportsdataverse/sportsdataverse-data/main/README.Rmd",
    "sportsdataverse-data-DESCRIPTION":
        "https://raw.githubusercontent.com/sportsdataverse/sportsdataverse-data/main/DESCRIPTION",
    "sportsdataverse-data-LICENSE":
        "https://raw.githubusercontent.com/sportsdataverse/sportsdataverse-data/main/LICENSE",
    "cfbfastR-cfb-data-README.md":
        "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-cfb-data/main/README.md",
    "cfbfastR-cfb-data-DATASETS.md":
        "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-cfb-data/main/DATASETS.md",
    "cfbfastR-cfb-data-DESCRIPTION":
        "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-cfb-data/main/DESCRIPTION",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def fetch(url: str) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read(), {key.lower(): value for key, value in response.headers.items()}


def write_exact(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    if path.read_bytes() != value:
        raise RuntimeError(f"byte replay failed for {path}")


def acquire(output_root: Path) -> dict[str, Any]:
    source_root = output_root / "sources"
    prior_path = output_root / "source-manifest.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8")) if prior_path.exists() else None
    prior_assets = {
        (item["tag"], item["name"]): item for item in (prior or {}).get("assets", [])
    }
    prior_evidence = {
        item["name"]: item for item in (prior or {}).get("licenseAndSchemaEvidence", [])
    }
    release_meta: dict[str, dict[str, Any]] = {}
    selected: list[dict[str, Any]] = []
    network_bytes = 0

    for tag, spec in RELEASES.items():
        raw, headers = fetch(f"{API_ROOT}/{tag}")
        network_bytes += len(raw)
        api_path = source_root / "release-metadata" / f"{tag}.json"
        write_exact(api_path, raw)
        release = json.loads(raw)
        assets = {asset["name"]: asset for asset in release["assets"]}
        release_meta[tag] = {
            "apiUrl": release["url"],
            "htmlUrl": release["html_url"],
            "releaseId": release["id"],
            "tag": release["tag_name"],
            "targetCommitish": release["target_commitish"],
            "publishedAt": release["published_at"],
            "updatedAt": release["updated_at"],
            "apiResponsePath": str(api_path.resolve()),
            "apiResponseBytes": len(raw),
            "apiResponseSha256": sha256_bytes(raw),
            "apiEtag": headers.get("etag"),
        }
        for season in spec["seasons"]:
            name = spec["asset"].format(season=season)
            if name not in assets:
                raise RuntimeError(f"required release asset is absent: {tag}/{name}")
            asset = assets[name]
            selected.append({
                "tag": tag,
                "season": season,
                "name": name,
                "purpose": spec["purpose"],
                "url": asset["browser_download_url"],
                "declaredBytes": int(asset["size"]),
                "publisherCreatedAt": asset["created_at"],
                "publisherUpdatedAt": asset["updated_at"],
                "assetId": asset["id"],
                "contentType": asset["content_type"],
            })

    declared = sum(item["declaredBytes"] for item in selected)
    if declared > MAX_NEW_BYTES:
        raise RuntimeError(
            f"selected assets require {declared} bytes, exceeding {MAX_NEW_BYTES}; no assets downloaded"
        )

    acquired: list[dict[str, Any]] = []
    reused_bytes = 0
    for item in selected:
        path = source_root / item["tag"] / item["name"]
        acquired_at = datetime.now(timezone.utc).isoformat()
        if path.exists() and path.stat().st_size == item["declaredBytes"]:
            raw = path.read_bytes()
            disposition = "REUSED_EXACT_LOCAL_BYTES"
            reused_bytes += len(raw)
            response_headers: dict[str, str] = {}
            previous = prior_assets.get((item["tag"], item["name"]), {})
            acquired_at = previous.get("acquiredAt", acquired_at)
        else:
            raw, response_headers = fetch(item["url"])
            if len(raw) != item["declaredBytes"]:
                raise RuntimeError(
                    f"declared/actual byte disagreement for {item['name']}: "
                    f"{item['declaredBytes']} != {len(raw)}"
                )
            write_exact(path, raw)
            disposition = "DOWNLOADED"
            network_bytes += len(raw)
        acquired.append({
            **item,
            "path": str(path.resolve()),
            "actualBytes": len(raw),
            "physicalSha256": sha256_bytes(raw),
            "acquiredAt": acquired_at,
            "format": "application/vnd.apache.parquet",
            "disposition": disposition,
            "responseEtag": response_headers.get("etag"),
            "responseLastModified": response_headers.get("last-modified"),
        })

    evidence: list[dict[str, Any]] = []
    for name, url in EVIDENCE_URLS.items():
        path = source_root / "license-and-schema-evidence" / name
        previous = prior_evidence.get(name, {})
        if path.exists() and previous and sha256_bytes(path.read_bytes()) == previous.get("physicalSha256"):
            raw = path.read_bytes()
            headers: dict[str, str] = {}
            acquired_at = previous["acquiredAt"]
            disposition = "REUSED_EXACT_LOCAL_BYTES"
        else:
            raw, headers = fetch(url)
            write_exact(path, raw)
            network_bytes += len(raw)
            acquired_at = datetime.now(timezone.utc).isoformat()
            disposition = "DOWNLOADED"
        evidence.append({
            "name": name,
            "url": url,
            "path": str(path.resolve()),
            "actualBytes": len(raw),
            "physicalSha256": sha256_bytes(raw),
            "acquiredAt": acquired_at,
            "disposition": disposition,
            "responseEtag": headers.get("etag"),
            "responseLastModified": headers.get("last-modified"),
        })

    prior_requests = int((prior or {}).get("cumulativeRequestCount", (prior or {}).get("requestCount", 0)))
    current_requests = len(RELEASES) + sum(1 for item in acquired if item["disposition"] == "DOWNLOADED") + sum(
        1 for item in evidence if item["disposition"] == "DOWNLOADED"
    )
    prior_network = int((prior or {}).get("cumulativeNetworkBytes", (prior or {}).get("networkBytes", 0)))
    if prior and "networkBytesIncludesReleaseMetadata" not in prior:
        prior_network += sum(int(item["apiResponseBytes"]) for item in prior["releaseMetadata"].values())
    manifest = {
        "schemaVersion": "CFB_GEN1_SOURCE_MANIFEST_V1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "repository": REPOSITORY,
        "privateResearchOnly": True,
        "displayOrRedistributionAuthorized": False,
        "licenseQualification": {
            "dataReleaseStatement": "SportsDataverse release hub identifies processed data as CC BY 4.0 with attribution.",
            "softwareStatement": "Producer and loader software metadata use their own software licenses, including MIT; those software licenses are not treated as independent permission for upstream ESPN-derived fields.",
            "remainingQualification": "This pilot retains and analyzes the bytes privately. Any consumer display or redistribution of source-derived fields requires a separate review of attribution and upstream-field terms.",
        },
        "incrementalCostUsd": 0.0,
        "requestCount": current_requests,
        "cumulativeRequestCount": prior_requests + current_requests,
        "selectedDeclaredBytes": declared,
        "networkBytes": network_bytes,
        "networkBytesIncludesReleaseMetadata": True,
        "cumulativeNetworkBytes": prior_network + network_bytes,
        "reusedLocalBytes": reused_bytes,
        "maximumNewDownloadBytes": MAX_NEW_BYTES,
        "releaseMetadata": release_meta,
        "assets": acquired,
        "licenseAndSchemaEvidence": evidence,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode("utf-8")
    manifest_path = output_root / "source-manifest.json"
    write_exact(manifest_path, manifest_bytes)
    locator = {
        "schemaVersion": "CFB_GEN1_SOURCE_MANIFEST_LOCATOR_V1",
        "path": str(manifest_path.resolve()),
        "bytes": len(manifest_bytes),
        "physicalSha256": sha256_bytes(manifest_bytes),
        "contentSha256": sha256_bytes(canonical_json(manifest)),
    }
    write_exact(
        output_root / "source-manifest-locator.json",
        json.dumps(locator, sort_keys=True, indent=2).encode("utf-8"),
    )
    return locator | {
        "assetCount": len(acquired),
        "networkBytes": network_bytes,
        "reusedLocalBytes": reused_bytes,
        "incrementalCostUsd": 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(acquire(args.output_root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
