# MLB V18 daily slate publisher

The publisher reads already-persisted AISP schedule, starter, lineup, and weather evidence
inside a read-only transaction. It does not call providers or write AISP. It reuses the
accepted V18 fold-5 PA model and fold-4 transition model without fitting, tuning, or
calibration, runs 5,000 simulations for each eligible game, and publishes content-addressed
research-shadow artifacts.

## Commands

Run the daily slate from the repository virtual environment:

```powershell
.\.venv\Scripts\python.exe -m scripts.publish_mlb_v18_daily_slate --date 2026-09-08 --workers 4
```

Recover or safely rerun one game:

```powershell
.\.venv\Scripts\python.exe -m scripts.publish_mlb_v18_daily_slate --date 2026-09-08 --game GAME-UUID --workers 1
```

Inspect the latest immutable receipt:

```powershell
.\.venv\Scripts\python.exe -m scripts.publish_mlb_v18_daily_slate --date 2026-09-08 --status
```

Rebuild the slate handoff from already verified game objects without source access or model
execution (useful after isolated recovery commands):

```powershell
.\.venv\Scripts\python.exe -m scripts.publish_mlb_v18_daily_slate --date 2026-09-08 --rebuild-handoff
```

A dry run captures and checks pregame source evidence but neither loads V18 nor writes a
publication:

```powershell
.\.venv\Scripts\python.exe -m scripts.publish_mlb_v18_daily_slate --date 2026-09-08 --dry-run
```

Rerunning the same game with unchanged eligible evidence resolves the same publication key,
verifies the existing object, and reports `DUPLICATE_ALREADY_PUBLISHED`. A changed point-in-time
evidence set creates a new immutable forecast object.

## Optional Windows schedule registration

Run the following from an elevated PowerShell prompt only if a local daily task is wanted.
It creates the task disabled by default; enable it deliberately after inspecting the action.

```powershell
$action = New-ScheduledTaskAction -Execute 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' -Argument '-m scripts.publish_mlb_v18_daily_slate --workers 4' -WorkingDirectory 'C:\Users\james\asp-model-studio'
$trigger = New-ScheduledTaskTrigger -Daily -At '10:00 AM'
Register-ScheduledTask -TaskName 'ASP MLB V18 Daily Slate Publisher' -Action $action -Trigger $trigger -Description 'Research-shadow only; reads AISP and publishes Model Studio artifacts.'
Disable-ScheduledTask -TaskName 'ASP MLB V18 Daily Slate Publisher'
```

## AISP boundary

Each slate handoff uses `AISP_MLB_V18_DAILY_SLATE_HANDOFF_V1`. The smallest AISP follow-up is
an adapter that verifies each referenced object manifest and artifact checksum, binds only an
exact existing AISP game UUID, deduplicates by `objectSha256`, and persists the forecast on the
V18 research-shadow track. Unknown games must be skipped. Gen 1 rows, promotion state, and
execution authority remain unchanged.
