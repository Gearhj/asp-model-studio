# NBA Gen 1: exact remaining data request

No qualifying real NBA population exists in the inspected local sources. Current AISP metadata contains **six FIXTURE payloads (8,637 bytes), four fixture game revisions and six fixture team-stat rows; zero REAL rows**. The eight offline ingestion runs are fixture executions. No NBA dataset, source-use approval or provider-access authorization is registered. The source-dependent fitting and assessment steps must remain blocked.

This request is for **one bounded, rights-qualified SportsDataIO NBA package from the existing account or an already retained lawful export**, covering **2020–21 through 2025–26**, regular-season full games including overtime. It is not a request to create an account, start a trial, contact a vendor or spend money.

## Data and delivery

Supply a source manifest, six season schedule files and six season game/team-box files including period lines, plus retained original source objects bound by physical SHA-256 and byte count. Equivalent original immutable API responses are sufficient. A compact export is estimated at **25–100 MB**, capped at **100 MB**; these are planning estimates, not measured vendor payload sizes. Delivery of an existing offline package requires **zero provider requests by Model Studio**.

The corresponding documented source paths are:

- `GET https://api.sportsdata.io/v3/nba/scores/json/Games/{season}` — provider game/team IDs, season and type, home/away identity, scheduled tipoff, status and reschedule lineage.
- `GET https://api.sportsdata.io/v3/nba/stats/json/BoxScoresFinal/{date}` — final scores, both TeamGames rows and all Quarters, including each overtime period's home/away points.

Season parameter identities must come from the source's season manifest; do not guess numeric tokens. These paths were verified in the September 10 official-doc receipt; the current dictionary still identifies their Final Box Score families. The current dynamic API page did not expose endpoint values to the browser renderer. No credentialed call was made. [Official NBA documentation](https://sportsdata.io/developers/api-documentation/nba), [NBA dictionary](https://sportsdata.io/developers/data-dictionary/nba).

If authorized API retrieval is necessary instead of an existing export, the estimate is **6 + D calls**, where D is the number of distinct regular-season dates fixed from schedule metadata before outcome access: approximately **906–1,206 requests**, capped at **1,306**, and **200–500 MB** of original full boxes, capped at **600 MB**. This estimate assumes 150–200 game dates per season and 30–70 KB per full box across roughly 7,000–7,400 games; no real response has been measured. Stop at either cap. No retries or expanded range are implicit. This is one source request with two delivery methods, not a second acquisition project.

Required numerical fields are points, FGM/FGA, 3PM, FTM/FTA, ORB/DRB, turnovers, and elapsed game minutes/seconds for both teams. Retain their units and source nulls. Per-period score pairs must reconcile to final scores. No injury, roster, player-strength, odds or play-by-play feed is needed.

## Timing and permissions that must accompany it

Each exact source revision needs its publication/availability timestamp, timezone semantics, acquisition clock, revision identity and checksum. The scheduled tipoff must have pre-tip schedule-vintage authority, including reschedules and replacement identities. A postgame `Updated` value alone does not certify a pregame schedule. Current archives preserve last revisions rather than earlier snapshots; an honest last-revision timestamp can gate that particular box until its actual publication time, but cannot be replaced by an invented next-day availability rule. [Historical archive semantics](https://sportsdata.io/help/historical-data-integration-guide).

Supply the existing account/product evidence covering real nonscrambled six-season retrieval, retention of original bytes and fitted artifacts, internal model training/evaluation and derived forecasts. Separate derived-output exchange/subscriber-display rights from internal training permission. Document any post-termination retention and attribution conditions. Generic commercial possibilities do not establish this account's agreement. [SportsDataIO licensing scope](https://sportsdata.io/help/data-rights-and-licensing-questions).

**Known future price: unavailable.** The account's NBA entitlement, remaining quota and zero-incremental-charge position are unverified. Any authorized retrieval must cost **$0** and consume no shared sportsbook credits. This assignment used **0 sports-data requests, 0 source bytes and $0**. The earlier 3-game/25,000,000-byte pilot remains unused; it is not a six-season license or expanded allowance.

## Existing evidence

- Current filtered read-only inspection: `outputs/nba-gen1-v1/local-source-inspection.json` (NBA data modes and counts only; no payload content).
- Current connector delivery: `C:/Users/james/ai-sports-predictor/docs/nba-ingestion-v1/NBA_INGESTION_DELIVERY.md`.
- Saved pilot commit `da05d9f6f12ecb628101dab42f67709101d01265`, `docs/nba-sportsdataio-pilot-v1/access-and-request-ledger.json` and `official-access-findings.md`; read through `git show`, without checkout.
- Exact physical references, request fields and accounting: `outputs/nba-gen1-v1/source-qualification.json`.

The proposed roles remain provisional until qualifying metadata verifies coverage: 2020–21 initial history/Development; 2021–22 through 2023–24 chronological Development; 2024–25 Validation; 2025–26 sealed OOT. No fixture performance, champion, model fit, OOT result, or future NBA publication is claimed.
