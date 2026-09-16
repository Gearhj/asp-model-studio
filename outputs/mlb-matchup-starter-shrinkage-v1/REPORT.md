# MLB current preview inputs and matchup shrinkage

**RETAIN_BASELINE.** The feasible head-to-head correction does not meet the frozen improvement gate. The exact-starter hypothesis remains unassessed because no eligible pre-cutoff target-starter identities exist in the retained historical source. No model, preview or final forecast was changed or published.

## Phase A: precise remaining input dependency

The frozen team-only preview remains blocked by a **complete, admitted full-game score-history owner export**, not missing lineups. The target retained from the existing request is MIL at PIT, MLBAM **823334**, September 17 at **16:35 UTC / 12:35 EDT**. Its September 16 show deadline is **20:00 UTC / 16:00 EDT**. There is no newly generated forecast, no late forecast and no discovery update.

This inventory corrects the earlier overbroad implication that all 2025 data is sealed. FD1 includes admitted 2025 internal research/prior history. Separate Gen2/Gen3 2025 evaluation objects remain sealed. The current Bronze metadata also lists 195 daily 2025 partitions and 156 daily 2026 partitions (March 25–August 27), of which 142 2026 days are outside the sealed dates. Their presence does not supply the required complete certified team-score export: the safe reader returns PA/pitch rows and an empty games list; its authority explicitly says allHistoryComplete=false. The newer rolling-owner cache covers August/September only. Team-game context has no final score columns. The seasonal schedule identity projection intentionally excludes scores.

The smallest remaining delivery is one `MLB_TEAM_PREVIEW_CURRENT_INPUTS_V1` input with a bound `MLB_TEAM_PREVIEW_ADMITTED_HISTORY_V1` owner export and admission receipt, containing:

- Complete 2025 MIL/PIT records and full league totals required by the frozen prior, plus admitted earlier 2019–24 history.
- Complete 2026 MIL/PIT games through September 15, scores, completion dates and suspended-game handling; last-60 ordering and season counts must reconcile.
- Exact identities, FINAL/completion observation, actual capture/source clocks, revisions, physical source hashes, completeness and `protectedPayloadsUsed=false`.

Use independently permissible evidence. No blanket 2025/2026 or OOT exception is requested. The existing two-call/20MB/USD0 official-source option is an estimate for separate owner authority if cached sources cannot supply the export; **zero calls were executed or authorized by this assignment**. No allowance was reset. `PHASE_A.json`, `PHASE_A_CLARIFICATION.json` and `CURRENT_SOURCE_METADATA.json` bind the exact source/use distinctions and code locations. No partial August history or invented prior was passed to `check-current`/`produce`; those commands require the missing real export.

## Historical diagnosis and design

Anchor: unchanged `MLB_TEAM_LOGISTIC_C1_POISSON_A1_SHOW_PREVIEW_V1`, with independent Logistic winner probabilities and Poisson conditional score means. This is a frozen research anchor, **not final V18**. There is no joint simulation population. All 12,993 admitted 2019–24 games retain their original identity/orientation and historical results. The anchor was trained through the season preceding each 2022/2023/2024 forecast.

Development contains 4,858 games (2022–23); 2024 has 2,429 reused Validation games. Development scores select the correction and are not unbiased confirmation of that selection. The selected correction is frozen before the 2024 comparison. The 2024 period was already inspected in prior work and is not a fresh holdout. No 2025/2026 outcome payload was used for fitting, selection or assessment. A source manifest inspection surfaced outcome-derived 2025 class-count metadata; that metadata did not enter this study. The inspection qualification is retained in Phase A.

For each target, donors must have completion dates strictly before the preceding calendar day (D-2 or earlier). Suspended games are delayed to completion. This is a conservative reconstructed day-before cutoff, not a claim of certified historical publication vintages. Raw Retrosheet archives were acquired August 21, 2026. Target venue is reconstructed from admitted Retrosheet park identity; historical schedule revision availability is uncertified. No target actual starter, target batting order, odds or own-pitcher offensive run support enters the correction.

Before correction, frozen thresholds were team mean >7 and total >12; neither occurred in Development or 2024. Development maxima were **6.609 team runs / 10.536 total runs**. The frozen upper-decile boundaries were **5.125631 team runs / 9.485751 total runs**. The team-decile slice means *games with either team above the team-observation cutoff* and therefore is not 10% of games. The Development-selected positive residual-risk bin is expected total [9,10).

The high-total slice overpredicted by **0.521 runs** in Development (486 games; calendar-week 95% interval **−0.059 to +1.033**) but **underpredicted by 0.402** in 2024 (154 games; **−1.061 to +0.233**). This does not establish a stable runaway-score defect. No cap or separate tail stabilizer was tested.

## One frozen bounded correction

The 48-point Development grid selected: last **12** head-to-head meetings, **180-day** half-life, maximum age **360 days**, minimum **2** meetings, prior strength **32**, same-park weight 1 and other-park weight **0.5**. Pseudo-observation shrinkage toward the frozen mean is weighted by decayed count and an observed overdispersion penalty. Uncertain/sparse samples receive less weight. Age is a staleness proxy; team identity is not evidence of roster continuity. No 50/50 averaging or output clipping.

The source has prior charged runs, pitching outs and BF, but charged runs are not automatically runs scored while a starter was active. An identity-only projection of all **19,436** 2021–24 FD1 starter records found **zero** announcement timestamps and **zero** strict same-game pregame eligibility flags. Prior-after-final eligibility exists; it cannot certify today's starter. The frozen 2026 survival component is not chronologically valid for these historical targets. Consequently starter-only is exactly the anchor, and combined is exactly H2H-only. These are disclosed missing-evidence fallbacks, not measured successful starter executions or evidence against the starter hypothesis. Starter parameters, starter/bullpen-controlled run shares and combination weights could not legitimately be fitted.

## Results

Lower is better for all errors/scores below. Signed bias is predicted minus actual runs. Count score is mean per-team Poisson deviance; using this proper score for means does not assert a Poisson predictive distribution.

| Period | Games | Baseline deviance | H2H deviance | Baseline total MAE | H2H total MAE |
|---|---:|---:|---:|---:|---:|
| 2022 Development | 2,428 | 2.266766 | 2.265321 | 3.494991 | 3.491601 |
| 2023 Development | 2,430 | 2.289234 | 2.288424 | 3.615236 | 3.613471 |
| 2024 reused Validation | 2,429 | 2.215138 | 2.215854 | 3.412327 | 3.413120 |

All arms on the same 2,429-game 2024 cohort:

| Arm | Winner log loss | Binary Brier | Away MAE | Home MAE | Total MAE | Deviance |
|---|---:|---:|---:|---:|---:|---:|
| Frozen anchor | 0.682164 | 0.244537 | 2.467938 | 2.369987 | 3.412327 | 2.215138 |
| Head-to-head | 0.682164 | 0.244537 | 2.468993 | 2.369936 | 3.413120 | 2.215854 |
| Starter-only: exact fallback | 0.682164 | 0.244537 | 2.467938 | 2.369987 | 3.412327 | 2.215138 |
| Combined: H2H only supported | 0.682164 | 0.244537 | 2.468993 | 2.369936 | 3.413120 | 2.215854 |

Candidate-minus-baseline deviance is **+0.000715** (paired 29-calendar-week 95% interval **−0.001550 to +0.002979**). Total MAE changes **+0.000793** (interval **−0.002783 to +0.004455**). These do not pass the predeclared ≥0.01 deviance improvement or uncertainty gates. The small Development improvement reverses in 2024. The upper-total 2024 slice also worsens: MAE **4.093154 → 4.100381**, deviance **2.413552 → 2.423966**. The [9,10) bin's small MAE improvement does not offset absent overall benefit.

Winner probabilities/picks are identical by construction: AUC **0.584241**, accuracy **56.237%**, no changed picks. Brier is mean `(pHome−homeWin)^2`, range 0–1. This study cannot claim winner improvement from changed score means. CRPS, energy score and 50/80/90 interval coverage/width are explicitly **unavailable**, since no joint population or intervals exist. Prediction availability is 100% because exact baseline fallbacks are retained.

Assessment head-to-head support before the selected shorter-age rule: **0 meetings: 0; 1–3: 324; 4–7: 378; 8–12: 1,727** (capped at 12 within 730 days). The selected H2H correction applies to **1,974 games** and falls back exactly on **455**. Eligible exact-starter cases: **0**, due to missing target binding, not missing all historical pitcher data. All targets lack certified preview starters/lineups; there is no informative known-versus-missing split. Full per-season, month, favorite-side, venue and fixed-anchor tail metrics, reliability bins, donor identities/weights, all 48 Development results and paired block intervals are retained in JSON.

## Reproduction and preservation

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_mlb_matchup_shrinkage
.\.venv\Scripts\python.exe scripts/run_mlb_matchup_shrinkage_v1.py verify
```

Stages are `diagnose`, `select`, `assess`, followed by deterministic `verify`. Verification regenerates numerical evidence and requires exact bytes to match. `STAGE_CLOCKS.json` records actual observed Windows creation/last-write clocks and ordering. Nine focused synthetic tests cover chronology/completion, orientation, source-season rejection, exact fallback, shrinkage/replay, winner mass, uncertainty weighting, unavailable starter rejection, fixed tail membership and count-score/distribution semantics. They are software checks, not additional forecasting observations.

All **169** recorded original preview/feasibility files remain byte-identical. Existing final forecasts were not written; the eight pre-existing tracked modifications and unrelated untracked work are preserved. Automatic scheduling remains inactive and no new owner exists. External/provider/sportsbook calls **0**, external bytes **0**, cost **USD0**, AISP writes **0**. No consumer import or acknowledgement is claimed. The handoff is a blocked-input status plus non-promotional research assessment, not an importable forecast.

The next dependency is the complete admitted current-history owner export. A starter-specific study additionally needs eligible pre-cutoff target-starter bindings; no prospective study or acquisition is started here. The NFL EPA challenger remains queued.

Retrosheet attribution: The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at www.retrosheet.org.
