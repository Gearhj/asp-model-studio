NFL M1 publication audit — 2026-09-12T20:01:10.591277+00:00

Week 1: 16 games; next seven days: 15; union: 17.
Published 17; pending 0; blocked 0; missed 0. New 0; reused 17; import-confirmed 17.

| Game | Kickoff UTC | Publication |
|---|---|---|
| NE at SEA | 2026-09-10T00:20:00+00:00 | VALID_PUBLISHED_REUSED |
| SF at LAR | 2026-09-11T00:35:00+00:00 | VALID_PUBLISHED_REUSED |
| ATL at PIT | 2026-09-13T17:00:00+00:00 | VALID_PUBLISHED_REUSED |
| BAL at IND | 2026-09-13T17:00:00+00:00 | VALID_PUBLISHED_REUSED |
| BUF at HOU | 2026-09-13T17:00:00+00:00 | VALID_PUBLISHED_REUSED |
| CHI at CAR | 2026-09-13T17:00:00+00:00 | VALID_PUBLISHED_REUSED |
| CLE at JAX | 2026-09-13T17:00:00+00:00 | VALID_PUBLISHED_REUSED |
| NO at DET | 2026-09-13T17:00:00+00:00 | VALID_PUBLISHED_REUSED |
| NYJ at TEN | 2026-09-13T17:00:00+00:00 | VALID_PUBLISHED_REUSED |
| TB at CIN | 2026-09-13T17:00:00+00:00 | VALID_PUBLISHED_REUSED |
| ARI at LAC | 2026-09-13T20:25:00+00:00 | VALID_PUBLISHED_REUSED |
| GB at MIN | 2026-09-13T20:25:00+00:00 | VALID_PUBLISHED_REUSED |
| MIA at LV | 2026-09-13T20:25:00+00:00 | VALID_PUBLISHED_REUSED |
| WAS at PHI | 2026-09-13T20:25:00+00:00 | VALID_PUBLISHED_REUSED |
| DAL at NYG | 2026-09-14T00:20:00+00:00 | VALID_PUBLISHED_REUSED |
| DEN at KC | 2026-09-15T00:15:00+00:00 | VALID_PUBLISHED_REUSED |
| DET at BUF | 2026-09-18T00:15:00+00:00 | VALID_PUBLISHED_REUSED |

Producer owner: AISP existing scheduler/orchestrator. Latest substantive run `27963e27-9d9f-4eeb-b6e0-8b2c03cd438a`: succeeded, completed 2026-09-12T19:36:51.390661+00:00; 270 input vectors, 0 new forecasts. Actual next-run timestamp is not exposed by the inspected owner receipt.

Governed source refresh: COMPLETE (schedule-refresh), attempted 2026-09-12T19:43:35.181876Z; current foundation freshness verified: True. Its receipt is retained separately from the effective forecast source clocks.

Bounded Studio publication completed 2026-09-12T19:47:14.184996Z: 15 supported games, 0 new forecasts, 15 unchanged forecasts reused, under the shared publication lock. Exact source-check clock and handoff digest are in the JSON receipt.

Schedule source as of 2026-09-12T19:44:59.784362+00:00. The successful governed schedule-refresh receipt matches this foundation. Schedule freshness is verified through its source-as-of; numerical forecast-input freshness remains separate. The partial forward-vintage projection is not the denominator.

Original source, forecast and publication clocks remain separate. Package paths, hashes, forecast IDs, source identities and Claude's exact import invocations are in the JSON companion. Consumer display/evaluation is unconfirmed.

[Machine-readable audit](C:/Users/james/asp-model-exchange/aisp-daily-forecast-bundles/nfl-m1-publication-audit-20260912/publication-audit.json)

Reproduce from Model Studio:

```powershell
.\.venv\Scripts\python.exe scripts\report_nfl_m1_publication.py --as-of-utc "2026-09-12T20:01:10.591277+00:00" --owner-review "outputs\nfl-m1-publication-audit-20260912\objects\sha256\cc53fd72391b2135ef9c40349d022bceee489f7f954009a7d2c4af1efc12ecf0\owner-review-successor.json" --consumer-confirmations "outputs\nfl-m1-publication-audit-20260912\objects\sha256\31dd1bfcf535a5861d137a914bf22d8943da087342860864a08106f20aded489\consumer-confirmations.json" --source-refresh-receipt "outputs\nfl-m1-publication-audit-20260912\schedule-refresh-execution.json" --publication-execution "outputs\nfl-m1-publication-audit-20260912\rolling-publication-execution.json"
```
