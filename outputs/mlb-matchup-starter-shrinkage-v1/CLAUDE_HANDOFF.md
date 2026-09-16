# Claude handoff: MLB preview dependency and separate shrinkage result

Type: **delivery-status update and non-promotional research assessment**. No forecast import, model activation, AISP write, scheduler change or wagering authority is requested. Claude acknowledgement is unavailable; no import is claimed.

Implementation commit: `d75d75ebcb913280531ab3025858687dfadf6729`. Preserved starting evidence commit: `b9c31ab8b78837f94ec42d858656144765ef70ee`.

## Genuine MLB preview

**No new MLB preview package exists.** Existing 17 NFL/CFB preview packages and all discovery entries remain unchanged. The accepted team-only preview configuration is unchanged.

Target remains MIL at PIT, MLBAM 823334, September 17 at 16:35 UTC / 12:35 America/New_York. The day-before deadline is September 16 at 20:00 UTC / 16:00 America/New_York, followed by a possible 20:30 UTC / 16:30 board freeze. No new forecast has a creation/publication clock and none is represented as on-time.

Missing: one complete admitted current-preview owner export with complete 2025 team/league priors and 2026 MIL/PIT completed-game scores through September15, real completion/capture clocks, source hashes, identity reconciliation and completeness. Preserve the exact existing `CURRENT_INPUT_REQUEST.json` contract. FD1 2025 is not uniformly sealed: its published internal-use permission exists; separate Gen2/Gen3 held objects remain protected. Safe cached daily PA sources are not a complete game-score export. Read **PHASE_A_CLARIFICATION.json together with PHASE_A.json** for the completed source inventory and exact field/source/authority gaps. No exception to sealed outcomes is requested.

Only after such real evidence exists should Model Studio run the existing `check-current --inputs <export>` then `produce --inputs <export>` commands before the true deadline. Do not import this handoff as `AISP_SHOW_PREVIEW_FORECAST_V1`, invent a probability from partial history, or change AISP eligibility.

Retained consumer validator remains the successfully used file `outputs/multisport-show-preview-producer-v1/context/consumer-contract.py`, SHA-256 `1a6771cb0fbf7c41cdc1e05e09141a7a4db513b82a7993399aec64fc6ea9f275`. No validator or contract change was made. Previous preview capability handoff remains at `show-preview-forecasts-v1/handoffs/sha256/3f445ec0648729d905324c74132bae1e2809a110667cdee654a5b1a86d1fda33/`.

## Separate research result

Disposition: **RETAIN_BASELINE** for `MLB_MATCHUP_STARTER_SHRINKAGE_CHALLENGER_V1`.

The frozen team-only season-forward anchor is not final V18. Development 2022–23: 4,858 games. Reused 2024 Validation: 2,429 games. H2H score shrinkage applied to 1,974, exact fallback for 455. 2024 count deviance **2.215138 → 2.215854**, total MAE **3.412327 → 3.413120**. Paired 29-week deviance delta **+0.000715**, 95% interval **[−0.001550,+0.002979]**. No meaningful later-period improvement. Winner probabilities/picks are unchanged; this is not a winner correction.

No Development or assessment means exceed the frozen 7-team-run / 12-total-run thresholds. The upper-total region's positive Development bias reverses in 2024; no hard cap was tested. There is no joint population, so CRPS, energy and interval metrics remain unavailable.

Starter-only is an exact baseline fallback on every game, with zero supported executions. All 19,436 inspected FD1 historical starter identity rows lack announcement time/strict same-game pregame eligibility. Prior charged-run/outs/BF fields do not fix target availability; charged runs are not automatically starter-active runs. The combined arm equals H2H-only. No conclusion about a supported starter-specific correction can be drawn, and no prospective test is started.

## Integrity and reproduction

Assessment physical SHA-256: `7746c0467a429a9763454751c7839d8bf3bff61adf7dc267a58bfa5ba1bf377b` (239,219 bytes).

Use package `manifest.json` to verify each member's exact bytes and SHA-256. Its physical SHA-256 is the advisory handoff directory address under the existing handoff convention, not a forecast identity. The local `DELIVERY_RECEIPT.json` records the eventual physical location and actual publication clock separately. No preview discovery index update is appropriate.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_mlb_matchup_shrinkage
.\.venv\Scripts\python.exe scripts/run_mlb_matchup_shrinkage_v1.py verify
```

Nine focused checks passed. Numerical evidence replay is byte-identical. All 169 bound original preview/research files remain unchanged; no final forecast was written. Provider/sportsbook calls 0, external bytes 0, cost USD0, AISP writes 0, new schedulers 0. NFL EPA remains queued.
