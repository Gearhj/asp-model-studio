"""Verify private prospective V18 player-prop packages without reading outcomes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.sports_current_statcast.mlb_v18_player_prop_sidecar import (
    canonical_json_bytes, verify_sidecar,
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _contained(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError("REFERENCE_OUTSIDE_CAPTURE_ROOT")
    return resolved


def verify(root: Path) -> dict:
    root = root.resolve()
    rows = []
    for key_path in sorted((root / "forecast-keys").glob("*.json")):
        key_raw = key_path.read_bytes()
        key = json.loads(key_raw)
        if canonical_json_bytes(key) != key_raw or key_path.stem != key["forecastObjectSha256"]:
            raise ValueError("FORECAST_KEY_INVALID")
        discovery_ref = key["discovery"]
        discovery_path = _contained(Path(discovery_ref["path"]), root)
        discovery_raw = discovery_path.read_bytes()
        if (len(discovery_raw) != discovery_ref["bytes"] or _sha(discovery_raw) != discovery_ref["sha256"]
                or canonical_json_bytes(json.loads(discovery_raw)) != discovery_raw):
            raise ValueError("DISCOVERY_REFERENCE_INVALID")
        discovery = json.loads(discovery_raw)
        package = discovery["package"]
        package_root = _contained(Path(package["path"]), root)
        manifest_raw = (package_root / "manifest.json").read_bytes()
        manifest = json.loads(manifest_raw)
        body = {name: value for name, value in manifest.items() if name not in {"packageId", "packageSha256"}}
        if (_sha(canonical_json_bytes(body)) != package["sha256"]
                or manifest["packageSha256"] != package["sha256"]
                or _sha(manifest_raw) != package["manifestPhysicalSha256"]):
            raise ValueError("PACKAGE_IDENTITY_INVALID")
        for member in manifest["members"]:
            raw = (package_root / member["relativePath"]).read_bytes()
            if len(raw) != member["bytes"] or _sha(raw) != member["sha256"]:
                raise ValueError("PACKAGE_MEMBER_INVALID")
        sidecar_raw = (package_root / "sidecar.json").read_bytes()
        sidecar = verify_sidecar(sidecar_raw, next(
            member["sha256"] for member in manifest["members"] if member["relativePath"] == "sidecar.json"
        ))
        registration = json.loads((package_root / "registration.json").read_bytes())
        capture = json.loads((package_root / "capture.json").read_bytes())
        if (registration["role"] != "DEVELOPMENT" or registration["validationResultAccessAuthorized"] is not False
                or capture["assessmentEligible"] is not True
                or sidecar["binding"]["forecastObjectSha256"] != key_path.stem
                or manifest["forecastObjectSha256"] != key_path.stem):
            raise ValueError("PROSPECTIVE_ROLE_OR_BINDING_INVALID")
        rows.append({"gameId": manifest["gameId"], "forecastObjectSha256": key_path.stem,
                     "packageSha256": package["sha256"], "role": "DEVELOPMENT",
                     "drawCount": sidecar["binding"]["simulationCount"]})
    return {"status": "VERIFIED", "captureCount": len(rows), "captures": rows,
            "outcomeReads": 0, "providerCalls": 0, "aispWrites": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.root), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
