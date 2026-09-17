"""Build an immutable source deployment for the NFL personnel capture owner."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.sports_nfl_m1.personnel_evidence import canonical_json_bytes


FILES = (
    "scripts/run_nfl_personnel_prospective_capture.py",
    "scripts/status_nfl_personnel_capture.py",
    "scripts/invoke_nfl_personnel_capture.ps1",
    "scripts/install_nfl_personnel_capture.ps1",
    "server/__init__.py", "server/sports_nfl_m1/__init__.py",
    "server/sports_nfl_m1/personnel_capture.py",
    "server/sports_nfl_m1/personnel_evidence.py",
    "server/sports_nfl_m1/personnel_prospective.py",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--deployment-root", type=Path, default=Path(r"C:\Users\james\asp-model-studio\.deployments\nfl-personnel-capture"))
    args = parser.parse_args()
    source = args.source_root.resolve()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=source, text=True).strip():
        raise RuntimeError("deployment source worktree must be clean")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    members = []
    for rel in FILES:
        path = source / rel
        if not path.is_file():
            raise RuntimeError(f"missing deployment member: {rel}")
        members.append({"path": rel.replace("\\", "/"), "sha256": sha(path), "byteCount": path.stat().st_size})
    identity_content = {"schemaVersion": "NFL_PERSONNEL_CAPTURE_DEPLOYMENT_IDENTITY_V1",
                        "members": members, "taskName": "ASP NFL Personnel Evidence Capture",
                        "ownerMarker": "ASP_NFL_PERSONNEL_EVIDENCE_OWNER_V1"}
    deployment_id = hashlib.sha256(canonical_json_bytes(identity_content)).hexdigest()
    target = args.deployment_root.resolve() / deployment_id
    if target.exists():
        existing = json.loads((target / "deployment-manifest.json").read_bytes())
        if existing["identitySha256"] != deployment_id:
            raise RuntimeError("existing deployment identity mismatch")
    else:
        for item in members:
            destination = target / item["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / item["path"], destination)
        manifest = {**identity_content, "identitySha256": deployment_id, "sourceCommit": commit,
                    "authority": "data capture only; no model, forecast, AISP, exchange, decision, position, or outcome authority"}
        (target / "deployment-manifest.json").write_bytes(canonical_json_bytes(manifest))
    for item in members:
        if sha(target / item["path"]) != item["sha256"]:
            raise RuntimeError(f"deployed member verification failed: {item['path']}")
    print(json.dumps({"deploymentId": deployment_id, "deploymentPath": str(target),
                      "sourceCommit": commit, "manifestSha256": sha(target / "deployment-manifest.json"),
                      "memberCount": len(members)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
