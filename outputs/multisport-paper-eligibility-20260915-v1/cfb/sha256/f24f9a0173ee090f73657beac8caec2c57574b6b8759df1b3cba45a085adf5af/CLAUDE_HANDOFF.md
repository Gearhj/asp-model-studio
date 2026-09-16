# CLAUDE_HANDOFF — CFB paper eligibility

Artifact: `ASP_CFB_PAPER_RESEARCH_ELIGIBILITY_V1` / `PAPER_RESEARCH_ELIGIBILITY`.
Package: `C:\Users\james\asp-model-exchange\cfb-gen1-research-v1\paper-eligibility\sha256\f24f9a0173ee090f73657beac8caec2c57574b6b8759df1b3cba45a085adf5af`
Logical address: `f24f9a0173ee090f73657beac8caec2c57574b6b8759df1b3cba45a085adf5af`.
Manifest: `d3c41085c6ec9bba4332c82d0d4ac6e8a629cdfd7e80f2e7bbffbfa0377d6f08` (617 bytes).
Supplement: `6f80ed7e8d703c0a20d82422ec9c35289b3ff90f333cca490c1822603ed67137` (5183 bytes).
Forecast: `cfb-gen1:51e40da85f05b98dc58144627f4a8902606c0aebc10182461c4f0402b8eee1ce`; event `cfbd:401858225`.
Game: `{'away_id': 183, 'away_team': 'Syracuse', 'conference_competition': 1, 'game_id': 401858225, 'home_id': 221, 'home_team': 'Pittsburgh', 'neutral_site': 0, 'scheduled_at': '2026-09-17T23:30:00+00:00'}`.
Controlling probabilities: `{'awayWin': 0.2308, 'homeWin': 0.7692, 'tie': 0.0}` (FRACTIONS_0_TO_1).
Original clocks: `{'sourceCutoffUtc': '2026-09-14T21:59:02.691510+00:00', 'scheduleRevisionCapturedAtUtc': '2026-09-14T21:59:01.147846+00:00', 'forecastCreatedAtUtc': '2026-09-14T22:14:50.206879+00:00', 'originalExchangePublishedAtUtc': '2026-09-14T22:16:01.605132+00:00', 'eligibilityPublishedAtUtc': '2026-09-15T14:06:39.2898903Z'}`.
Policy: experiment `AISP_CFB_VIRTUAL_PAPER_RESEARCH_V1`, virtual $1,000, moneyline only, quarter Kelly, 0.5%/$5 initial position cap, 1% same-game cap, 2% daily cap, 2-point minimum adjusted edge; real money false.
Import the generic research supplement idempotently by supplementId + logical address; identical bytes are a no-op and different bytes under the same supplementId require an explicit successor.
Return an AISP receipt binding supplement address, physical supplement hash, forecast ID, event ID, experiment ID, import time, activation state, and display state.
Unsupported: spread/total wagering, profitability or champion claims, and every missing input listed in supplement.json.

Verification:
```powershell
.\.venv\Scripts\python.exe scripts\verify_paper_research_eligibility.py 'C:\Users\james\asp-model-exchange\cfb-gen1-research-v1\paper-eligibility\sha256\f24f9a0173ee090f73657beac8caec2c57574b6b8759df1b3cba45a085adf5af'
```

Producer publication does not establish consumer import, activation, or display.
