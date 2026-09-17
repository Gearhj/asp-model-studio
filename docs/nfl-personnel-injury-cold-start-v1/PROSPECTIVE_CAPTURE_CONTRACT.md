# Prospective capture contract

The inactive capture planner targets seven public nflverse release assets: schedule, injuries, weekly roster, depth chart, snap counts, players and draft picks. One manual capture permits at most seven GETs, 64 MiB of response bytes and 2 GiB retained. Raw bytes remain outside Git, content-addressed by SHA-256. Receipts retain release tag, asset name, URL, ETag/Last-Modified when supplied, retrieval time, physical hash, byte count and license. Identical objects are reused.

Scheduling is inactive. A later authorized owner can run:

```powershell
python scripts/capture_nfl_personnel_evidence_v1.py --season 2026
python scripts/capture_nfl_personnel_evidence_v1.py --season 2026 --execute --rights-approved
```

The first command is always zero-network. The second is the explicit live path and must use the external default root. Captures grant research evidence only and no model, forecast, AISP, exchange, policy or scheduler authority.
