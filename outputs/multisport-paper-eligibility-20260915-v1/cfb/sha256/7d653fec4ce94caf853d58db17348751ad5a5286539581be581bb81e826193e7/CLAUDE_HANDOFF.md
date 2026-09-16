# CLAUDE_HANDOFF — CFB paper eligibility

Artifact: `ASP_CFB_PAPER_RESEARCH_ELIGIBILITY_V1` / `PAPER_RESEARCH_ELIGIBILITY`.
Package: `C:\Users\james\asp-model-exchange\cfb-gen1-research-v1\paper-eligibility\sha256\7d653fec4ce94caf853d58db17348751ad5a5286539581be581bb81e826193e7`
Logical address: `7d653fec4ce94caf853d58db17348751ad5a5286539581be581bb81e826193e7`.
Manifest: `f09af4f48bf99344c505bc57f387a5273c19ea8ed4db73096d6272e24dff8d85` (616 bytes).
Supplement: `f674f8e2362f91cffedf04efed1d5329e9a4b73b3fe6ad8e5eebe5f6b847fef6` (6565 bytes).
Forecast: `cfb-gen1:51e40da85f05b98dc58144627f4a8902606c0aebc10182461c4f0402b8eee1ce`; event `cfbd:401858225`.
Game: `{'away_id': 183, 'away_team': 'Syracuse', 'conference_competition': 1, 'game_id': 401858225, 'home_id': 221, 'home_team': 'Pittsburgh', 'neutral_site': 0, 'scheduled_at': '2026-09-17T23:30:00+00:00'}`.
Controlling probabilities: `{'awayWin': 0.2308, 'homeWin': 0.7692, 'tie': 0.0}` (FRACTIONS_0_TO_1).
Original clocks: `{'sourceCutoffUtc': '2026-09-14T21:59:02.691510+00:00', 'scheduleRevisionCapturedAtUtc': '2026-09-14T21:59:01.147846+00:00', 'forecastCreatedAtUtc': '2026-09-14T22:14:50.206879+00:00', 'originalExchangePublishedAtUtc': '2026-09-14T22:16:01.605132+00:00', 'eligibilityPublishedAtUtc': '2026-09-15T14:13:04.3498282Z'}`.
Policy: experiment `AISP_CFB_PAPER_POLICY_V1:CFB:2026`, virtual $1,000, moneyline only, quarter Kelly, 0.5%/$5 initial position cap, 1% same-game cap, 2% daily cap, 2-point minimum adjusted edge; real money false.
Import the generic research supplement idempotently by supplementId + logical address; identical bytes are a no-op and different bytes under the same supplementId require an explicit successor.
Consumer interface gap: the inspected AISP generic verifier currently hard-codes `ASP_NFL_PAPER_RESEARCH_ELIGIBILITY_V1` and discovers only `nfl-labs-supplements`; register `ASP_CFB_PAPER_RESEARCH_ELIGIBILITY_V1` for sport `CFB` and import this exact package directory through the same byte/binding checks. The prepared sport policy alone does not perform that import.
Return an AISP receipt binding supplement address, physical supplement hash, forecast ID, event ID, experiment ID, import time, activation state, and display state.
Unsupported: spread/total wagering, profitability or champion claims, and every missing input listed in supplement.json.

Verification:
```powershell
.\.venv\Scripts\python.exe scripts\verify_paper_research_eligibility.py 'C:\Users\james\asp-model-exchange\cfb-gen1-research-v1\paper-eligibility\sha256\7d653fec4ce94caf853d58db17348751ad5a5286539581be581bb81e826193e7'
```

Producer publication does not establish consumer import, activation, or display.
