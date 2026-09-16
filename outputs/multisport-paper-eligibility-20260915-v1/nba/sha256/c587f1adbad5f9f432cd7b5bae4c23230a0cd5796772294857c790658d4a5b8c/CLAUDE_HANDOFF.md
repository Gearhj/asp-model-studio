# CLAUDE_HANDOFF — NBA paper eligibility

Artifact: `ASP_NBA_PAPER_RESEARCH_ELIGIBILITY_V1` / `PAPER_RESEARCH_ELIGIBILITY`.
Package: `C:\Users\james\asp-model-exchange\nba-gen1-research-v1\paper-eligibility\sha256\c587f1adbad5f9f432cd7b5bae4c23230a0cd5796772294857c790658d4a5b8c`
Logical address: `c587f1adbad5f9f432cd7b5bae4c23230a0cd5796772294857c790658d4a5b8c`.
Manifest: `dc7fe663b1e7d351aab6157c62d6972b0764eab7164b8833e925fdbd104eaf68` (626 bytes).
Supplement: `872be1957a1d7eb2d8d1d2d31d15b26675bc8880c2e91a4b9d4bae098623f776` (5517 bytes).
Forecast: `nba-joint:3ee2c1a130aa621a787b5094b990228d2c612f9fbeb9a3c22071c0b4a46828a0`; event `nba-espn:game:401909088`.
Game: `{'away_team_code': 'BOS', 'away_team_id': 'nba-neil:franchise:BOS', 'game_date': '2026-10-20', 'game_id': 'nba-espn:game:401909088', 'home_team_code': 'DET', 'home_team_id': 'nba-neil:franchise:DET', 'neutral_site': False, 'scheduled_tipoff_utc': '2026-10-20T19:00:00+00:00', 'season_end': 2027, 'season_type': 'REGULAR', 'source_game_id': 401909088, 'source_revision': 'github-asset:552084615:sha256:d4ffe0d974dbec227af1ea5d731e0f36426839a170bfd0bbffc39b65f933a090', 'status': 'SCHEDULED'}`.
Controlling probabilities: `{'awayWin': 0.43810000000000004, 'homeWin': 0.5619, 'tie': 0.0}` (FRACTIONS_0_TO_1).
Original clocks: `{'sourceCutoffUtc': '2026-09-14T19:47:38.320128+00:00', 'forecastCreatedAtUtc': '2026-09-14T19:50:04.630535+00:00', 'originalExchangePublishedAtUtc': '2026-09-14T20:30:45.607349+00:00', 'eligibilityPublishedAtUtc': '2026-09-15T14:06:39.2898903Z'}`.
Policy: experiment `AISP_NBA_VIRTUAL_PAPER_RESEARCH_V1`, virtual $1,000, moneyline only, quarter Kelly, 0.5%/$5 initial position cap, 1% same-game cap, 2% daily cap, 2-point minimum adjusted edge; real money false.
Import the generic research supplement idempotently by supplementId + logical address; identical bytes are a no-op and different bytes under the same supplementId require an explicit successor.
Return an AISP receipt binding supplement address, physical supplement hash, forecast ID, event ID, experiment ID, import time, activation state, and display state.
Unsupported: spread/total wagering, profitability or champion claims, and every missing input listed in supplement.json.

Verification:
```powershell
.\.venv\Scripts\python.exe scripts\verify_paper_research_eligibility.py 'C:\Users\james\asp-model-exchange\nba-gen1-research-v1\paper-eligibility\sha256\c587f1adbad5f9f432cd7b5bae4c23230a0cd5796772294857c790658d4a5b8c'
```

Producer publication does not establish consumer import, activation, or display.
