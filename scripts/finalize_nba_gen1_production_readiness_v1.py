"""Publish the final immutable NBA Gen1 activation-readiness delivery."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


HANDOFF = Path(r"C:\Users\james\asp-model-exchange\nba-gen1-production-v1\handoffs\sha256\7113b71ff5819c89103ad19d5f9afb22c51dbc92980be12b56ce8826cb34ccaf\index.json")
FORECAST = Path(r"C:\Users\james\asp-model-exchange\nba-gen1-production-v1\forecasts\sha256\8a725a439af9f9ad4828281ff9bcdec5511c2af292c3feac4826b975dfa0d4c2\index.json")
DEPLOYMENT = Path(r"C:\Users\james\asp-model-studio\.deployments\nba-gen1-publisher\7e04b1cc6f68ad4a4c0a3833f28751fdbfc54957e019e2cb5743946eeae25716\deployment-manifest.json")
EXCHANGE = Path(r"C:\Users\james\asp-model-exchange\nba-gen1-production-v1")
EFFECTIVE = "2026-09-18T01:16:08.176807+00:00"


def blob(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def ref(path):
    p = Path(path); raw = p.read_bytes()
    return {"path": str(p), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def main():
    if ref(HANDOFF)["sha256"] != HANDOFF.parent.name or ref(FORECAST)["sha256"] != FORECAST.parent.name:
        raise RuntimeError("Bound content address changed")
    created = datetime.now(timezone.utc).isoformat()
    delivery = {"schemaVersion": "NBA_GEN1_PRODUCTION_ACTIVATION_READINESS_V1", "createdAtUtc": created,
        "status": "NBA_GEN1_PRODUCTION_READY_AWAITING_ACTIVATION", "prospectiveEffectiveAtUtc": EFFECTIVE,
        "deployment": {"deploymentId": DEPLOYMENT.parent.name, "manifest": ref(DEPLOYMENT),
            "installed": False, "canonicalTaskName": "ASP NBA Forecast Publisher", "verifiedOwnerCount": 0},
        "productionHandoff": ref(HANDOFF), "prospectiveForecastPackage": ref(FORECAST),
        "forecastGame": {"provider": "ESPN", "sourceGameId": 401909089,
            "canonicalGameId": "nba-espn:game:401909089", "away": "PHI", "home": "NYK",
            "tipoffUtc": "2026-10-20T23:00:00+00:00"},
        "publication": {"forecastId": "nba-production:ab967168951e39a3f1068846b094097be947d2b235913b2ea386eaaaf75a56d0",
            "publishedAtUtc": "2026-09-18T01:16:32.611393+00:00", "drawCount": 10000,
            "idempotentReplay": "REUSED_IMMUTABLE", "consumerAcknowledged": False},
        "activation": {"authorizationRequired": True, "remainingProducerSteps": 1,
            "aispPinsRequiredSeparately": True},
        "externalActivity": {"providerCalls": 0, "providerBytes": 0, "costUsd": 0,
            "aispWrites": 0, "authenticatedSportsbookCalls": 0}}
    staging = Path(tempfile.mkdtemp(prefix="nba-final-", dir=EXCHANGE))
    (staging / "delivery.json").write_bytes(blob(delivery))
    install = rf"& 'C:\Users\james\asp-model-studio\.tmp\nba-gen2-production-readiness-v1\scripts\install_nba_gen1_publisher.ps1' -Mode Install -RepositoryRoot 'C:\Users\james\asp-model-studio' -DeploymentId '{DEPLOYMENT.parent.name}' -HandoffPath '{HANDOFF}' -HandoffSha256 '{HANDOFF.parent.name}' -EffectiveAtUtc '{EFFECTIVE}'"
    rollback = rf"& 'C:\Users\james\asp-model-studio\.tmp\nba-gen2-production-readiness-v1\scripts\install_nba_gen1_publisher.ps1' -Mode Remove -RepositoryRoot 'C:\Users\james\asp-model-studio'"
    activation = f"""# NBA Gen1 activation instructions

No owner is installed. Run the following once in Administrator PowerShell only after explicit authorization:

```powershell
{install}
```

Then allow the existing task to invoke naturally; verify exactly one `ASP NBA Forecast Publisher` task, S4U/Limited/IgnoreNew, the runtime/deployment/handoff hashes, and an idempotent forecast receipt. Do not manually start a competing publisher.

Claude/AISP pins, applied separately after consumer validation:

```text
NBA_PRODUCTION_HANDOFF_PATH={HANDOFF}
NBA_PRODUCTION_HANDOFF_SHA256={HANDOFF.parent.name}
```

Rollback this first installation without deleting deployment or evidence:

```powershell
{rollback}
```
"""
    (staging / "ACTIVATION.md").write_text(activation, encoding="utf-8", newline="\n")
    handoff = f"""# Claude/AISP handoff

Validate `{HANDOFF}` at SHA-256 `{HANDOFF.parent.name}`, then import forecast package `{FORECAST}` at SHA-256 `{FORECAST.parent.name}`. The game is PHI at NYK, ESPN `401909089`; this is a newly issued prospective forecast, not the BOS–DET research artifact. Ridge scores, Elo win probabilities and the paired residual population are separate channels. Use Elo as the declared winner channel and the 10,000 paired draws for score/margin/total distributions. Keep the close-score challenger disabled. Import by forecast ID and physical hash, preserve all clocks, and write a consumer receipt before calling the import acknowledged. No wagering or profitability authority is granted.
"""
    (staging / "CLAUDE_HANDOFF.md").write_text(handoff, encoding="utf-8", newline="\n")
    members = []
    for p in sorted(staging.iterdir()):
        b = ref(p); members.append({"relativePath": p.name, "sha256": b["sha256"], "bytes": b["bytes"]})
    index_raw = blob({"schemaVersion": "NBA_GEN1_PRODUCTION_ACTIVATION_DELIVERY_INDEX_V1",
                      "createdAtUtc": created, "members": members})
    address = hashlib.sha256(index_raw).hexdigest()
    destination = EXCHANGE / "activation-readiness/sha256" / address
    if destination.exists():
        if (destination / "index.json").read_bytes() != index_raw: raise RuntimeError("Delivery conflict")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staging, destination)
        (destination / "index.json").write_bytes(index_raw)
    shutil.rmtree(staging)
    print(json.dumps({"status": delivery["status"], "deliveryAddress": address,
        "index": ref(destination / "index.json"), "activation": ref(destination / "ACTIVATION.md"),
        "claudeHandoff": ref(destination / "CLAUDE_HANDOFF.md")}, indent=2))


if __name__ == "__main__":
    main()
