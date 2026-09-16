# NBA 2025–26 season export admission

Admit SportsDataverse's **hoopR NBA schedule export for season-end 2026** for Category A reconstructed historical research. This is a new, separately bounded intake under the current assignment, not a reset of either previous NBA allowance.

The publisher's [license at the retained revision](https://github.com/sportsdataverse/hoopR-nba-data/blob/ec432186c9aa08ef1267578f0e54ccf50f510452/LICENSE.md) expressly applies CC BY 4.0 to its **data, code, and documentation**. It permits retention, adaptation, and internal model development, including commercial use, with attribution, the license link, and disclosure of changes. It contains no separate prohibition on derived forecasts. This admission relies on the data license, not on an API-client software license. No bespoke permission is needed for the authorized internal research.

The [publisher README](https://github.com/sportsdataverse/hoopR-nba-data/tree/ec432186c9aa08ef1267578f0e54ccf50f510452) documents ESPN as the underlying source and binds the processed schedules to the `espn_nba_schedules` release in `sportsdataverse/sportsdataverse-data`. This intake reads that published export; it does not call ESPN or NBA provider endpoints. The source's build code explicitly constructs season schedules and preserves identifiers, dates, home/away score fields, season/type fields, and source status. Actual selected columns and cohort coverage must still be checked before score access.

Selected asset:

- [nba_schedule_2026.parquet](https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_schedules/nba_schedule_2026.parquet)
- GitHub asset ID `552053438`; **525,802 bytes**.
- Published SHA-256 `b3884aa4aa276d1fcafc71b69394675904a968902068bff634932e5d7afacae4`.
- Asset updated **2026-09-09T05:18:08Z**. This export revision is not evidence of a historical per-game publication vintage.
- Current-task maximum: one logical dataset GET, **600,000 bytes**, **$0**. No account, trial, vendor contact, subscription, provider credential, or sportsbook credit.

The optional `team_box_2026.parquet` is 140,628 bytes, asset `552052211`, SHA-256 `db846dfb39b0f75eee50ad91b1b5b7a7a62dd31d3ec0bb066a0a3bb08e366f7e`. Its metadata was checked, but it is **not selected or authorized by this one-file intake**: the current frozen score/date experiment does not require boxes. Avoid adding this download merely because it is available.

One other concrete option was screened: Wyatt Walsh's Kaggle NBA Database advertises real historical games, boxes, and CC BY-SA 4.0, but its listing was last updated three years ago despite a daily-update description. It did not establish 2025–26 coverage, and no file was acquired. Existing FiveThirtyEight and Neil Paine admissions remain preserved; they were not reopened.

Before outcomes: retain exact source bytes; verify the published size/digest; read schema and identity/scope columns only; reconcile team/game identities and season/status; identify regular-season games, neutral history-only games, and the Cup-final date-only context; then freeze the selected identity list. Do not include publisher odds, outcomes, postgame statistics, or ratings in the metadata pass or feature covariates. Keep actual acquisition clocks. No contemporaneous historical certification, future forecast capture, or AISP publication is established by this export.

Attribution: NBA schedule/game facts published by SportsDataverse/hoopR.nba authors, derived from ESPN, under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). ASP Model Studio filters competition identities, reconstructs earlier-day inputs, and produces independent research estimates. Changes and the historical-vintage limitation are disclosed; no publisher endorsement is implied.

Review traffic is recorded separately from game-corpus acquisition in `admission.json`; preserve all prior usage cumulatively. Browser metadata-review transport bytes are unmeasured and must not be presented as zero.

## Subsequent genuine future schedule capture

After the current-season intake completed, the user-authorized conditional future forecast required the already listed `nba_schedule_2027.parquet`. A **separate addendum recorded before acquisition** bound one additional GET, 100,000-byte maximum, and $0 cost; it did not reset the 2026 allowance. Exact captured size was **86,466 bytes**, with publisher SHA-256 `d4ffe0d974dbec227af1ea5d731e0f36426839a170bfd0bbffc39b65f933a090`.

The first supported target is **Boston at Detroit, ESPN game 401909088, October 20, 2026 at 19:00 UTC**. The retained source explicitly marks that time valid, and its `date`, `start_date`, and Eastern display agree. Acquisition completed **2026-09-14T13:04:43.697362Z**, which is the recorded future source cutoff. This is a real captured schedule, not a historical publication-time reconstruction. Actual forecast creation/export are separate operations by the point-forecast runner.

`future-intake-addendum.json` records the bounded authorization; `../future-schedule-capture.json`, `../future-schedule-clock-validation.json`, and `../future-schedule-evidence-qualified.json` preserve the source/clock chain. `../current-history-coverage.json` reconciles all 8,289 history identities and both historical source captures, checks 82 completed 2025–26 regular games for each target team, and finds no elapsed regular-season game in the captured 2026–27 schedule at cutoff. No future outcome columns were read.

Completed NBA corpus acquisition is now **four logical downloads, 34,273,400 bytes, $0**, including both preserved earlier downloads. This assignment added the 525,802-byte history export and the separately declared 86,466-byte future schedule; no team boxes or provider endpoints were requested.
