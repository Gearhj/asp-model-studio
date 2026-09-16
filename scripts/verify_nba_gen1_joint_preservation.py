"""Capture/verify physical preservation of inherited NBA artifacts and dirty work.

Only NBA index metadata is parsed. Other payloads (including inherited MLB/NFL
files) are hashed as opaque bytes. Neither forecast clocks nor old files change.
The Git HEAD is provenance, not an immutability gate: new scoped commits may
advance it while every inherited byte remains unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/nba-gen1-joint-residual-v1"
MANIFEST = OUTPUT / "starting-preservation.json"
OLD_INDEX = ROOT / "outputs/nba-gen1-long-gap-v1/index.json"
OLD_INDEX_SHA = "0bace150f409c354401e3879551152b7244cf913dc178914256cd970354e6086"
FORECAST_SHA = "27f766e341cc211317d61e7ed842d7bbff7521664da5b27a0776bfc5394a8767"
LOCAL_INDEX_SHA = "22a6748510653c50820aea4391a79040058d55230a793a3ee059597bc82d4a7a"
EXCHANGE_INDEX_SHA = "85e3d7414ccaac4b79c524096af3f7fa894169041e143ee3dc5894002f53e2e0"
EXCHANGE_INDEX = (
    ROOT.parent / "asp-model-exchange/nba-gen1-research-v1/point-elo-v1/packages/sha256"
    / EXCHANGE_INDEX_SHA / "index.json"
)
DIRTY = (
    "outputs/mlb-starter-duration-paired-research-v1/current.json",
    "outputs/mlb-starter-duration-paired-research-v1/monitoring/current.json",
    "outputs/mlb-starter-duration-paired-research-v1/readiness-state.json",
    "outputs/mlb-v18-current-state-pipeline-v1/slates/2026-09-10/latest.json",
    "outputs/mlb-v18-current-state-pipeline-v1/slates/2026-09-11/latest.json",
    "outputs/nfl-forward-vintages-v1/CURRENT.json",
    "outputs/nfl-play-level-engine-v1/CURRENT.json",
    "server/sports_current_statcast/mlb_v18_prospective_transform.py",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ref(path: Path) -> dict:
    path = path.resolve(strict=True)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": size}


def require_ref(expected: dict) -> dict:
    actual = ref(Path(expected["path"]))
    if (actual["sha256"], actual["bytes"]) != (expected["sha256"], expected["bytes"]):
        raise ValueError(f"Physical preservation failure: {expected['path']}")
    return actual


def git_state() -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    return {
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "trackedStatusPorcelainV1": git("status", "--porcelain=v1", "-uno").splitlines(),
    }


def write_new(path: Path, value: dict) -> dict:
    path = path.resolve()
    if not path.is_relative_to(OUTPUT.resolve()):
        raise ValueError("Verification outputs must be new files under the joint-residual output root")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as handle:
        handle.write(data)
    return ref(path)


def capture() -> dict:
    if MANIFEST.exists():
        raise FileExistsError(f"Refusing to replace original capture: {MANIFEST}")
    old_index_ref = ref(OLD_INDEX)
    if old_index_ref["sha256"] != OLD_INDEX_SHA:
        raise ValueError("Original completed NBA index does not match its declared identity")
    index = json.loads(OLD_INDEX.read_bytes())
    artifacts = [require_ref(item) for item in index["artifacts"]]
    code = [require_ref(item) for item in index["code"]]
    if len(artifacts) != index["artifactFiles"] or sum(x["bytes"] for x in artifacts) != index["artifactBytes"]:
        raise ValueError("Original NBA artifact index accounting does not reconcile")
    local_dir = OLD_INDEX.parent / "future-point-export/sha256" / FORECAST_SHA
    forecast = ref(local_dir / "forecast.json")
    local_index = ref(local_dir / "index.json")
    if forecast["sha256"] != FORECAST_SHA or local_index["sha256"] != LOCAL_INDEX_SHA:
        raise ValueError("Original local forecast/index bytes have changed")
    exchange_index_ref = ref(EXCHANGE_INDEX)
    if exchange_index_ref["sha256"] != EXCHANGE_INDEX_SHA:
        raise ValueError("Published NBA index does not match its content-addressed identity")
    exchange = json.loads(EXCHANGE_INDEX.read_bytes())
    exchange_files = []
    for item in exchange["files"]:
        path = (EXCHANGE_INDEX.parent / item["relativePath"]).resolve()
        if not path.is_relative_to(EXCHANGE_INDEX.parent.resolve()):
            raise ValueError("Exchange relative path escapes its immutable package")
        exchange_files.append(require_ref({"path": str(path), "sha256": item["sha256"], "bytes": item["bytes"]}))
        require_ref(item["originalSource"])
    # Bind publication receipt separately; the immutable forecast retains its
    # original null publication field and this receipt carries the later clock.
    publication = ref(EXCHANGE_INDEX.parent / "publication-receipt.json")
    core = [ref(ROOT / "server/sports_nba_gen1/distribution.py"), ref(ROOT / "server/sports_nba_gen1/rest_support.py")]
    dirty = [ref(ROOT / path) for path in DIRTY]
    groups = {
        "inheritedDirtyTrackedFiles": dirty,
        "originalNbaIndex": [old_index_ref],
        "originalNbaIndexedArtifacts": artifacts,
        "originalNbaIndexedCode": code,
        "originalDistributionAndRestCode": core,
        "originalLocalForecastAndIndex": [forecast, local_index],
        "originalExchangeIndex": [exchange_index_ref],
        "originalExchangeFiles": exchange_files,
        "originalExchangePublicationReceipt": [publication],
    }
    unique = {}
    for name, items in groups.items():
        for item in items:
            key = str(Path(item["path"]).resolve()).casefold()
            if key in unique and unique[key]["sha256"] != item["sha256"]:
                raise ValueError("Conflicting physical bindings for one path")
            unique.setdefault(key, {**item, "groups": []})["groups"].append(name)
    state = {
        "schema": "NBA_GEN1_JOINT_STARTING_PRESERVATION_V1",
        "capturedAtUtc": now(),
        "git": git_state(),
        "scope": "Physical preservation capture during additive joint-residual work; new files do not imply an earlier capture clock.",
        "verificationSemantics": "SHA-256 and byte counts of original bytes; no newline normalization. HEAD advancement from new scoped commits is recorded, not treated as a file failure.",
        "outcomeAccess": "NBA index metadata only; inherited MLB/NFL payloads hashed as opaque bytes without parsing.",
        "groupCounts": {name: len(items) for name, items in groups.items()},
        "indexedNbaArtifactBytes": sum(item["bytes"] for item in artifacts),
        "uniqueBoundFiles": len(unique),
        "files": sorted(unique.values(), key=lambda value: value["path"]),
        "originalIndexVerified": True,
        "exchangeIndexAndFilesVerified": True,
    }
    return {"capture": write_new(MANIFEST, state), "uniqueBoundFiles": len(unique), "groupCounts": state["groupCounts"]}


def verify() -> dict:
    capture_ref = ref(MANIFEST)
    manifest = json.loads(MANIFEST.read_bytes())
    failures = []
    checked = 0
    for item in manifest["files"]:
        try:
            require_ref(item)
            checked += 1
        except (ValueError, OSError) as error:
            failures.append({"path": item["path"], "error": str(error)})
    current_git = git_state()
    return {
        "schema": "NBA_GEN1_JOINT_PRESERVATION_VERIFICATION_V1",
        "verifiedAtUtc": now(), "startingCapture": capture_ref,
        "allBoundBytesUnchanged": not failures,
        "checkedFiles": checked, "expectedFiles": len(manifest["files"]),
        "groupCounts": manifest["groupCounts"],
        "failures": failures,
        "startingGit": manifest["git"], "currentGit": current_git,
        "headUnchanged": current_git["head"] == manifest["git"]["head"],
        "headIsProvenanceNotFileGate": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="Create starting-preservation.json once, after verifying old identities")
    parser.add_argument("--output", type=Path, help="Write a NEW verification JSON under the joint-residual output root")
    args = parser.parse_args()
    if args.capture and args.output:
        parser.error("--capture uses its fixed immutable manifest path; --output is for later verification")
    result = capture() if args.capture else verify()
    if args.output:
        result = {"verification": write_new(args.output, result), "allBoundBytesUnchanged": result["allBoundBytesUnchanged"]}
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result.get("allBoundBytesUnchanged", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
