# NBA Gen2 team-box acquisition and bounded comparison

## Disposition

**GEN1_REMAINS_BASELINE.** The licensed team-box foundation is usable, but neither frozen Gen2 candidate passed the predeclared 2023-24 selection gate. The already staged `NBA_GEN1_PRODUCTION_BASELINE_V1` remains inactive and unchanged. No scheduler or production model was activated.

## Acquisition and population

The retained CC BY 4.0 SportsDataverse/hoopR acquisition used 16 cumulative successful requests (15 in the authorized continuation), 2,554,300 cumulative bytes, zero retries, zero NBA.com calls and $0. Raw objects remain private outside Git.

The governed population identity is `dfb3216a9c7b520d8d6368d7d72eeb60c6566bfd1ea8811a27c9c419aaa74fa2`. It contains 10,224 games: 9,521 regular-season games, 672 playoffs retained as a separate role, and 31 other events. The exact common Gen1/Gen2 modeling population contains 8,172 games.

`total_rebounds` is retained as a separate source statistic. OREB and DREB directly define rebounding features. The source identity differs in 5,459 team rows, concentrated in season end years 2019-21; it becomes equal in later retained seasons. No field was overwritten. Completed schedule periods recover overtime status and team minutes (`240 + 25 × OT`) for every admitted row.

One game, ESPN `401704652` (New Orleans at Portland, 2024-10-25), is quarantined before feature history because both team rows fail the scoring identity despite matching schedule finals. Its raw bytes remain unchanged. Fifteen non-franchise exhibition identities were also removed before regular-season modeling.

## Frozen comparison

Development was 2020-21 through 2022-23, 2023-24 was the frozen selection season, and 2024-25/2025-26 were reused historical stability evidence. Every season was already inspected in prior Gen1 work, so none is called untouched. Models used only earlier-season fitting games; features used only earlier dates and emitted all same-date targets before any update.

| 2023-24 configuration | Games | Energy | Team score MAE | Margin CRPS | Total CRPS | Winner LL | Brier |
|---|---:|---:|---:|---:|---:|---:|---:|
| GEN1_EXACT_RETAINED | 1,225 | 10.2954 | 9.3408 | 7.9886 | 10.4177 | 0.6214 | 0.2163 |
| GEN2_RIDGE_A100_TEAM_BOX_V1 | 1,225 | 10.2945 | 9.3516 | 8.0822 | 10.3301 | 0.6258 | 0.2183 |
| GEN2_HGB_L2_10_TEAM_BOX_V1 | 1,225 | 10.4781 | 9.5460 | 8.0352 | 10.6733 | 0.6221 | 0.2163 |

### Season stability

| Season | Configuration | Energy | Team score MAE | Margin CRPS | Total CRPS | Winner LL |
|---|---|---:|---:|---:|---:|---:|
| 2021-22 | GEN1_EXACT_RETAINED | 10.4415 | 9.4639 | 8.0778 | 10.5954 | 0.6402 |
| 2021-22 | GEN2_RIDGE_A100_TEAM_BOX_V1 | 10.7378 | 9.7416 | 8.3497 | 10.8319 | 0.6606 |
| 2021-22 | GEN2_HGB_L2_10_TEAM_BOX_V1 | 10.6629 | 9.6546 | 8.2497 | 10.8033 | 0.6550 |
| 2022-23 | GEN1_EXACT_RETAINED | 10.1868 | 9.2269 | 7.2865 | 10.8307 | 0.6501 |
| 2022-23 | GEN2_RIDGE_A100_TEAM_BOX_V1 | 10.1638 | 9.2246 | 7.4171 | 10.6712 | 0.6519 |
| 2022-23 | GEN2_HGB_L2_10_TEAM_BOX_V1 | 10.1274 | 9.1299 | 7.3692 | 10.6621 | 0.6527 |
| 2023-24 | GEN1_EXACT_RETAINED | 10.2954 | 9.3408 | 7.9886 | 10.4177 | 0.6214 |
| 2023-24 | GEN2_RIDGE_A100_TEAM_BOX_V1 | 10.2945 | 9.3516 | 8.0822 | 10.3301 | 0.6258 |
| 2023-24 | GEN2_HGB_L2_10_TEAM_BOX_V1 | 10.4781 | 9.5460 | 8.0352 | 10.6733 | 0.6221 |
| 2024-25 | GEN1_EXACT_RETAINED | 10.2696 | 9.2913 | 7.8309 | 10.5278 | 0.6072 |
| 2024-25 | GEN2_RIDGE_A100_TEAM_BOX_V1 | 10.2408 | 9.2456 | 7.8332 | 10.4816 | 0.6034 |
| 2024-25 | GEN2_HGB_L2_10_TEAM_BOX_V1 | 10.3927 | 9.3770 | 8.0412 | 10.5601 | 0.6213 |
| 2025-26 | GEN1_EXACT_RETAINED | 10.6224 | 9.5895 | 8.1643 | 10.8207 | 0.5985 |
| 2025-26 | GEN2_RIDGE_A100_TEAM_BOX_V1 | 10.5362 | 9.5275 | 8.1800 | 10.6573 | 0.6005 |
| 2025-26 | GEN2_HGB_L2_10_TEAM_BOX_V1 | 10.7035 | 9.6758 | 8.2306 | 10.9167 | 0.6026 |

Ridge-minus-Gen1 energy was -0.0010 (calendar-week 95% interval -0.0858 to +0.0857). HGB-minus-Gen1 was +0.1826 (+0.0741 to +0.2915). Ridge improved total CRPS slightly but worsened margin CRPS and did not improve team-score MAE. HGB materially worsened the primary metric.

Ridge showed better energy and total accuracy in reused 2024-25 and 2025-26 evidence, but that later evidence is diagnostic and cannot satisfy the failed frozen 2023-24 gate. No ensemble was evaluated because neither standalone candidate passed.

On 2023-24, home-win calibration intercept/slope/ECE were -0.395/1.130/0.071 for Gen1, -0.346/1.043/0.070 for Ridge Gen2, and 0.097/1.194/0.037 for HGB. Better HGB bin calibration did not offset worse joint and total scores. Complete 50/80/90% interval coverage and width are retained in `ASSESSMENT.json`.

## Overtime sensitivity

Across candidate scoring, 309 observed-overtime games had much larger total CRPS than regulation games. The existing tie-resolution rule activated on about 2.5% of simulated draws and added roughly 0.30 points per team on average. This remains a known distribution limitation; no overtime mechanism was retuned.

## Operational outcome

`NBA_GEN1_PRODUCTION_BASELINE_V1` remains the staged production-capable baseline. Its existing exchange handoff and inactive scheduler descriptor remain byte-identical. A 2026-27 prospective team-box capture hook is designed but not installed or activated. Separate authorization is still required to activate the existing NBA owner and production pin.

## Reproduction

```powershell
$env:LOKY_MAX_CPU_COUNT='1'
$env:OMP_NUM_THREADS='1'
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe scripts/run_nba_gen2_team_box_study.py
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe scripts/finalize_nba_gen2_team_box_study.py
```

Assessment identity: `4f95c4b039378659f3f7aa37645ebefb1ca765a375fac53495001bf33dbe75e0`. Acquisition successor receipt: `99d2bc8518a81f6415d412267b4e53d0e5d00231f1e3c17f6b8086cb31128558`.

Private fitted artifacts and complete scoring outputs are retained outside Git at `C:\Users\james\asp-data-staging\nba\gen2-team-box-v1\studies\sha256\4f95c4b039378659f3f7aa37645ebefb1ca765a375fac53495001bf33dbe75e0`; retention receipt physical SHA-256 `1e44ae9b6c374c69916bb8aaaabb862a675cb5b7937540b8348226e2880e0d42`.
