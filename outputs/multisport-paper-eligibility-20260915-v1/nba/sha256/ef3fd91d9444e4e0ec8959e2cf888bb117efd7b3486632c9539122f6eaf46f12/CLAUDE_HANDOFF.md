# CLAUDE_HANDOFF — NBA paper eligibility

Artifact: `ASP_NBA_PAPER_RESEARCH_ELIGIBILITY_V1` / `PAPER_RESEARCH_ELIGIBILITY`.
Package: `C:\Users\james\asp-model-exchange\nba-gen1-research-v1\paper-eligibility\sha256\ef3fd91d9444e4e0ec8959e2cf888bb117efd7b3486632c9539122f6eaf46f12`
Logical address: `ef3fd91d9444e4e0ec8959e2cf888bb117efd7b3486632c9539122f6eaf46f12`.
Manifest: `e91a2ab95108cfdd0330390625d6ff0bfeeb3ea1891e0c5cbb4cf74fa58f0e75` (628 bytes).
Supplement: `f8d711542e1ee5d663e9163f8bc636f4d4b4aed14f3931e026f21ca348624189` (6940 bytes).
Forecast: `nba-joint:3ee2c1a130aa621a787b5094b990228d2c612f9fbeb9a3c22071c0b4a46828a0`; event `nba-espn:game:401909088`.
Game: `{'away_team_code': 'BOS', 'away_team_id': 'nba-neil:franchise:BOS', 'game_date': '2026-10-20', 'game_id': 'nba-espn:game:401909088', 'home_team_code': 'DET', 'home_team_id': 'nba-neil:franchise:DET', 'neutral_site': False, 'scheduled_tipoff_utc': '2026-10-20T19:00:00+00:00', 'season_end': 2027, 'season_type': 'REGULAR', 'source_game_id': 401909088, 'source_revision': 'github-asset:552084615:sha256:d4ffe0d974dbec227af1ea5d731e0f36426839a170bfd0bbffc39b65f933a090', 'status': 'SCHEDULED'}`.
Controlling probabilities: `{'awayWin': 0.43810000000000004, 'homeWin': 0.5619, 'tie': 0.0}` (FRACTIONS_0_TO_1).
Original clocks: `{'sourceCutoffUtc': '2026-09-14T19:47:38.320128+00:00', 'forecastCreatedAtUtc': '2026-09-14T19:50:04.630535+00:00', 'originalExchangePublishedAtUtc': '2026-09-14T20:30:45.607349+00:00', 'eligibilityPublishedAtUtc': '2026-09-15T14:13:04.3498282Z'}`.
Policy: experiment `AISP_NBA_PAPER_POLICY_V1:NBA:2026-27`, virtual $1,000, moneyline only, quarter Kelly, 0.5%/$5 initial position cap, 1% same-game cap, 2% daily cap, 2-point minimum adjusted edge; real money false.
Import the generic research supplement idempotently by supplementId + logical address; identical bytes are a no-op and different bytes under the same supplementId require an explicit successor.
Consumer interface gap: the inspected AISP generic verifier currently hard-codes `ASP_NFL_PAPER_RESEARCH_ELIGIBILITY_V1` and discovers only `nfl-labs-supplements`; register `ASP_NBA_PAPER_RESEARCH_ELIGIBILITY_V1` for sport `NBA` and import this exact package directory through the same byte/binding checks. The prepared sport policy alone does not perform that import.
Return an AISP receipt binding supplement address, physical supplement hash, forecast ID, event ID, experiment ID, import time, activation state, and display state.
Unsupported: spread/total wagering, profitability or champion claims, and every missing input listed in supplement.json.

Verification:
```powershell
.\.venv\Scripts\python.exe scripts\verify_paper_research_eligibility.py 'C:\Users\james\asp-model-exchange\nba-gen1-research-v1\paper-eligibility\sha256\ef3fd91d9444e4e0ec8959e2cf888bb117efd7b3486632c9539122f6eaf46f12'
```

Producer publication does not establish consumer import, activation, or display.
