"""Stage the immutable Gen1 deployment and publish its activation handoff.

No scheduled task or AISP setting is changed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def raw(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ref(path):
    p = Path(path).resolve(); b = p.read_bytes()
    return {"path": str(p), "sha256": sha(b), "bytes": len(b)}


def now():
    return datetime.now(timezone.utc).isoformat()


def copy_checked(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repository-root", default=r"C:\Users\james\asp-model-studio")
    ap.add_argument("--exchange-root", default=r"C:\Users\james\asp-model-exchange")
    ap.add_argument("--source-root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()
    source, repository, exchange = Path(args.source_root), Path(args.repository_root), Path(args.exchange_root)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    files = [source / "scripts/publish_nba_gen1_production_forecast.py",
             source / "scripts/invoke_nba_gen1_publisher.ps1",
             source / "server/__init__.py"]
    files += sorted((source / "server/sports_nba_gen1").glob("*.py"))
    members = []
    for path in files:
        rel = path.relative_to(source).as_posix()
        bound = ref(path)
        members.append({"relativePath": rel, "sha256": bound["sha256"], "bytes": bound["bytes"]})
    identity = {"schema": "NBA_GEN1_PUBLISHER_DEPLOYMENT_IDENTITY_V1", "sourceCommit": commit,
        "configurationIdentity": "NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1",
        "distributionConfigurationIdentity": "NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1",
        "drawCount": 10000, "masterSeed": 20260914, "excludedLegacyResearchGameIds": [401909088],
        "members": members}
    deployment_id = sha(raw(identity))
    deployment = repository / ".deployments/nba-gen1-publisher" / deployment_id
    for path in files:
        copy_checked(path, deployment / path.relative_to(source))
    manifest = {**identity, "deploymentId": deployment_id, "createdAtUtc": now(),
        "status": "STAGED_NOT_INSTALLED", "canonicalTaskName": "ASP NBA Forecast Publisher",
        "schedule": "Every 15 minutes, S4U/Limited/IgnoreNew, after explicit installation",
        "dataRoot": str(repository / "outputs"), "exchangeRoot": str(exchange),
        "activationAuthority": False}
    manifest_path = deployment / "deployment-manifest.json"
    manifest_path.write_bytes(raw(manifest))
    effective = now()
    current = json.loads((repository / "outputs/nba-gen1-long-gap-v1/current-research/receipt.json").read_bytes())
    method = json.loads((repository / "outputs/nba-gen1-joint-residual-v1/method-freeze.json").read_bytes())
    gen2 = json.loads((source / "outputs/nba-gen2-production-readiness-v1/assessment.json").read_bytes())
    if gen2["disposition"] != "GEN1_REMAINS_BASELINE":
        raise RuntimeError("Authoritative Gen2 disposition changed")
    package_manifest = {"schemaVersion": "NBA_GEN1_PRODUCTION_BASELINE_HANDOFF_V2", "createdAtUtc": effective,
        "prospectiveEffectiveAtUtc": effective, "status": "READY_AWAITING_ACTIVATION",
        "configurationIdentity": current["configurationIdentity"],
        "pointModel": {"method": "Ridge alpha 100 ordinary-rest", **current["models"]["ridge_a100_rest"]},
        "winnerModel": {"method": "chronological Elo, separately estimated", **current["models"]["elo"]},
        "distribution": {"configurationIdentity": method["engine"], "drawCount": 10000,
            "masterSeed": method["masterSeed"], "residualPopulation": method["residuals"],
            "supportTreatment": method["supportTreatment"], "closeScoreChallengerEnabled": False},
        "featureContract": current["freeze"]["featureContract"],
        "training": {"lastDate": current["latestRecordedGameDate"], "throughSeasonEnd": current["trainingThroughSeasonEnd"],
            "trainingGames": current["trainingGames"], "historyGames": current["historyGames"]},
        "scheduleDiscovery": ref(repository / "outputs/nba-gen1-long-gap-v1/future-schedule-evidence-qualified.json"),
        "deployment": {"deploymentId": deployment_id, "manifest": ref(manifest_path),
            "canonicalTaskName": "ASP NBA Forecast Publisher", "installed": False, "verifiedExistingOwnerCount": 0},
        "selection": {"gen2Disposition": gen2["disposition"], "assessmentIdentitySha256": gen2["assessmentIdentitySha256"],
            "governedGen2PopulationPreserved": True, "additionalSearchPerformed": False},
        "monitoring": {"reviewAtCompletedGames": [50, 100],
            "metrics": ["score/margin/total MAE", "winner log loss and binary Brier", "energy score and CRPS",
                        "one-point-finish frequency", "regulation versus overtime performance"]},
        "disclosures": ["Ridge score and Elo winner channels are separately estimated",
            "Simulated one-point finishes were 7.78% versus 4.01% observed",
            "Close-score correction was tested and rejected", "Overtime games remain materially harder",
            "No profitability claim has been established"],
        "authority": {"producerReady": True, "producerActivated": False, "aispActivated": False,
            "wageringAuthority": False, "decisionAuthority": False, "positionAuthority": False}}
    staging = Path(tempfile.mkdtemp(prefix="nba-handoff-", dir=repository / ".runtime"))
    (staging / "manifest.json").write_bytes(raw(package_manifest))
    activation = f"""# NBA Gen1 activation\n\nStatus: ready, not installed. Effective time: `{effective}`.\n\nAdministrator install (the one remaining producer authorization step):\n\n```powershell\n& '{source / 'scripts/install_nba_gen1_publisher.ps1'}' -Mode Install -RepositoryRoot '{repository}' -DeploymentId '{deployment_id}' -HandoffPath '<HANDOFF_INDEX>' -HandoffSha256 '<HANDOFF_SHA256>' -EffectiveAtUtc '{effective}'\n```\n\nVerify with the same command using `-Mode Verify`. Roll back this first installation with `-Mode Remove -RepositoryRoot '{repository}' -DeploymentId '{deployment_id}' -HandoffPath '<HANDOFF_INDEX>' -HandoffSha256 '<HANDOFF_SHA256>' -EffectiveAtUtc '{effective}'`; this removes only the NBA task and runtime binding and preserves deployment/evidence.\n\nAISP pins, applied separately by Claude after validating the handoff:\n\n```text\nNBA_PRODUCTION_HANDOFF_PATH=<HANDOFF_INDEX>\nNBA_PRODUCTION_HANDOFF_SHA256=<HANDOFF_SHA256>\n```\n"""
    (staging / "ACTIVATION.md").write_text(activation, encoding="utf-8", newline="\n")
    handoff = """# Claude/AISP handoff — NBA Gen1 production baseline\n\nValidate the package index and every member byte-for-byte. Ridge point expectations, Elo winner probabilities and the paired residual score population are separate channels. Consume only forecast packages whose creation is on or after `prospectiveEffectiveAtUtc`; never relabel BOS–DET or another research forecast. Import idempotently by forecast ID plus physical hash. Distributions have 10,000 paired HOME/AWAY full-game draws including overtime. Keep the close-score challenger disabled and display the retained limitations. Publication is not consumer acknowledgement and grants no wagering authority.\n"""
    (staging / "CLAUDE_HANDOFF.md").write_text(handoff, encoding="utf-8", newline="\n")
    indexed = []
    for p in sorted(staging.iterdir()):
        b = ref(p); indexed.append({"relativePath": p.name, "sha256": b["sha256"], "bytes": b["bytes"]})
    index = {"schemaVersion": "NBA_GEN1_PRODUCTION_HANDOFF_INDEX_V2", "createdAtUtc": effective, "members": indexed}
    index_raw = raw(index); address = sha(index_raw)
    destination = exchange / "nba-gen1-production-v1/handoffs/sha256" / address
    if destination.exists():
        if (destination / "index.json").read_bytes() != index_raw: raise RuntimeError("Handoff address conflict")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staging, destination)
        (destination / "index.json").write_bytes(index_raw)
    shutil.rmtree(staging)
    result = {"status": "NBA_GEN1_PRODUCTION_READY_AWAITING_ACTIVATION", "effectiveAtUtc": effective,
        "deploymentId": deployment_id, "deploymentManifest": ref(manifest_path),
        "handoffAddress": address, "handoffIndex": ref(destination / "index.json"),
        "providerCalls": 0, "costUsd": 0, "aispWrites": 0, "taskInstalled": False}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
