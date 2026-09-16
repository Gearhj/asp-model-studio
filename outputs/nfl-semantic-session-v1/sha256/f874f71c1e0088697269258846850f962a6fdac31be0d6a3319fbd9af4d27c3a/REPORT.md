# NFL semantic laboratory and football simulation delivery

Implemented semantic NFL preprocessing, completed six targeted XGBoost/HGB designs plus a dynamic score baseline and two bounded tuning studies, persisted reloadable finalist systems, added matched model/market benchmarks, published actual M1 score-distribution supplements and a distinct fitted drive research engine, and integrated old/new evidence in Model Studio. M1 is retained. All new evidence is research-only and unpromoted.

## What baseball's cold-start state actually was

The 240-feature specification contains 64 no-history entries. Accepted V18 selects 218 source fields plus 55 prior outputs, giving 273 pre-categorical inputs. All 21 prior treatments execute in the five verified preprocessing artifacts. Ordinary prior median/mode fallback was **zero recorded**. The 56 governed WHIP population-prior fallbacks are valid and distinct from the held population.

The held 56 Development PAs (51 OOF) have observed zero exposure, prior_missing=false, undefined raw rates and zero companion event counts—not missing component observations. V1 does not authorize that zero-opportunity prior state; the hold remains unchanged. Saved either-player cold-start PAs: 83,174, log loss 1.481061; complementary flag-negative PAs: 418,365, log loss 1.473303. These are overlapping observational subgroups, not proof of treatment uplift. V14's older gaps are not V18's current status. See [full saved-evidence reconciliation](<C:/Users/james/asp-model-studio/outputs/mlb-v18-cold-start-reconciliation-v1/sha256/86b955bf0d4a2b136ac97436f740da31b042b0e95e612d363cb98d7d05a3dc7b/REPORT.md>) and [row-level reconciliation JSON](<C:/Users/james/asp-model-studio/outputs/mlb-v18-cold-start-reconciliation-v1/sha256/86b955bf0d4a2b136ac97436f740da31b042b0e95e612d363cb98d7d05a3dc7b/reconciliation.json>).

## Exact NFL targets and distributions

One completed game is one observation. Source final home_score and away_score become float64 home_points and away_points, including overtime. M1 fits two independent squared-error score regressors; margin and total are derived, not its fitted targets. Margin = home minus away; total = home plus away. AWAY_WIN/TIE/HOME_WIN probabilities come from the joint distribution.

The legacy law adds paired, centered training-period residuals to score means, clips at zero and stochastically integerizes. Its dependence and actual persisted score masses are preserved. This law is not a sequential football scoring engine and can assign implausible low scores. Regressor means and Monte Carlo expectations need not equal after clipping. Separate probability calibration does not imply a calibrated joint simulation. Postseason scores include overtime with explicit game_type; preseason is excluded from this Development experiment. See [executable target contract](<C:/Users/james/asp-model-studio/outputs/nfl-semantic-session-v1/NFL_TARGET_CONTRACT_V1.json>).

Operational M1 includes 2025 training (cutoff 2026-02-08); it is not the unbiased historical comparator. All comparisons here use compatible saved fold-refitted recipe OOF. No sealed 2025 source rows were opened for this session.

## Implemented feature treatment

The catalog has 300 entries: 197 registered M1 inputs, 12 added lagged-personnel inputs, and 91 proposed entries. Of the registered inputs, 196 have executable decisions; roof is excluded because historical open/closed status lacks proven pregame availability. C1 uses 196 active source inputs; C2 and C3 use 208. These counts are distinct from expanded columns below. There is no generic-median branch in new recipes.

C1 reconstructs strictly prior-date team histories, preserving zero completed games separately from undefined opportunity rates. Continuous signed EPA/game-average rates use normal-normal approximations with valid-game counts, four prior-equivalent games, eight-game half-life and 0.65 offseason retention. Rates are not falsely called binomial counts. C2 adds prior-game passer mixtures weighted by previous team usage, player EPA/count history, uncertainty and team-change history; these are not assertions of the target game's known starter. C3 applies training-only simple exposure/experience peer pooling. Team-relative QB adjustment limits double counting of embedded passing strength. Native missingness remains explicit for unavailable rates; the two validation examples are known-zero red-zone opportunity, not measured rates of zero.

The league center uses the most recent three training seasons as an era adjustment. Both teams' offense/defense inputs inform the matchup learner, but a separate opponent-normalized historical EPA or strength-of-schedule estimator was not implemented. The C1 package also includes roof exclusion and extra uncertainty/state columns, so its effect is not a causally isolated prior correction.

Draft, actual rookie/backup/start-change, injury and contemporaneous weather inputs remain unsupported where their pregame authority is absent. Current roster availability does not repair injury absence. Historical release-vintage uncertainty remains documented. Proposed source rows are not falsely counted as model inputs.

| Fitted fixed recipe | Expanded columns | SHA-256 | Artifact |
|---|---|---|---|
| XGBOOST_C2 | 769 | 0762634712edb6148ddde038c068d36300458b6fd7a48f80cb16991df6a15906 | [forecast-system.joblib](<C:/Users/james/asp-model-studio/outputs/nfl-semantic-lab-v1/runs/7a651ec80b3b77106b018dd6739f55e26e45cbcf5e1f8811d6557f039d372f69/fitted/XGBOOST_C2/forecast-system.joblib>) |
| XGBOOST_C3 | 769 | 91bb6212b59e52075b7a39c62c2fee844bfc04ee6bb9729dcec70341530c5e0d | [forecast-system.joblib](<C:/Users/james/asp-model-studio/outputs/nfl-semantic-lab-v1/runs/7a651ec80b3b77106b018dd6739f55e26e45cbcf5e1f8811d6557f039d372f69/fitted/XGBOOST_C3/forecast-system.joblib>) |

Workbook: [NFL_Feature_Treatment_Specification.xlsx](<C:/Users/james/asp-model-studio/outputs/nfl-semantic-session-v1/NFL_Feature_Treatment_Specification.xlsx>). Machine policy: [feature-treatment-policy.json](<C:/Users/james/asp-model-studio/outputs/nfl-semantic-lab-v1/policy-supplements/sha256/ad3f1e57106f58b76b835cb7cd3912c26d357e05fd85f9495dbccd9367edd6d6/feature-treatment-policy.json>) (SHA-256 `ad3f1e57106f58b76b835cb7cd3912c26d357e05fd85f9495dbccd9367edd6d6`). Editable reviewer decisions are separate from executable/fitted authority. Source coverage, early-season missingness, units, join keys, prior assumptions, state semantics and implementation locations are recorded per feature.

## Did early-season forecasts improve?

**No consistent early-season improvement was established.** C2 and C3 XGBoost calibrated Weeks 1–4 loss is worse than M1 by +0.005565 and +0.008175. C1 XGBoost is nearly unchanged at 0.693572 versus M1 0.693660. Full-season calibrated C3 improves its point estimate to 0.661772 versus 0.665318, but its paired interval includes zero. The best tuned C3 point estimate is 0.661452, difference -0.003866, interval [-0.012094, +0.004296]; it also does not establish advancement. M1 remains retained.

These are exploratory Development comparisons on 1,408 identical validation games across seasons 2020–2024, drawn from 6,991 Development games (1999–2024). Weeks 1–4 contain 319 games; Weeks 1–2 contain 160; 80 games involve a zero-current-season-history team. The lagged-passer low-exposure proxy has only eight games and is descriptive, not an identified rookie/backup effect. Same-date outcomes never enter another target-date forecast. Priors and model fitting are fold-local; the first calibration year remains raw because no earlier OOF exists, and later calibration uses only earlier seasons.

| Pipeline | Raw LL | Calibrated LL | Raw Brier (sum 3) | Margin MAE | Total MAE | Weeks 1–4 raw / calibrated LL | Weeks 1–2 raw / calibrated LL |
|---|---|---|---|---|---|---|---|
| XGBOOST_C1 | 0.675588 | 0.665784 | 0.450015 | 10.1180 | 10.6028 | 0.716899 / 0.693572 | 0.716562 / 0.705591 |
| HGB_C1 | 0.678990 | 0.663719 | 0.452730 | 10.2008 | 10.7308 | 0.720756 / 0.700065 | 0.707066 / 0.696356 |
| XGBOOST_C2 | 0.674027 | 0.662423 | 0.448292 | 10.0945 | 10.6076 | 0.718791 / 0.699225 | 0.719157 / 0.708376 |
| HGB_C2 | 0.677902 | 0.667597 | 0.451375 | 10.1836 | 10.6911 | 0.707854 / 0.695745 | 0.700557 / 0.694728 |
| XGBOOST_C3 | 0.674172 | 0.661772 | 0.448236 | 10.0944 | 10.6019 | 0.719012 / 0.701835 | 0.717574 / 0.706740 |
| HGB_C3 | 0.679935 | 0.667501 | 0.453996 | 10.1974 | 10.6863 | 0.721485 / 0.704624 | 0.718972 / 0.710160 |
| DYNAMIC_TEAM_SCORE_BLEND | 0.695853 | 0.682562 | 0.467909 | 10.3665 | 10.6338 | 0.736567 / 0.714865 | 0.724108 / 0.707299 |
| M1_RECIPE_FOLD_REFIT | 0.674896 | 0.665318 | 0.448840 | 10.0699 | 10.6270 | 0.709628 / 0.693660 | 0.705634 / 0.699470 |
| HIST_GRADIENT_BOOSTING_B_T2 | 0.674775 | 0.662128 | 0.448931 | 10.1357 | 10.6985 | 0.706967 / 0.693378 | 0.703763 / 0.696399 |
| XGBOOST_C2_TUNED | 0.676201 | 0.666660 | 0.450152 | 10.1178 | 10.6064 | 0.721549 / 0.702954 | 0.723126 / 0.714898 |
| XGBOOST_C3_TUNED | 0.673862 | 0.661452 | 0.447821 | 10.0816 | 10.5964 | 0.717748 / 0.700628 | 0.720352 / 0.710773 |

Lower log loss is better. Brier is the sum of squared errors across all three classes. MAE units are points. New candidates use 2,000 paired-residual draws per evaluation event. Full and early-season score-interval coverage, calibration error, subgroup sizes and per-fold diagnostics are in [complete model results](<C:/Users/james/asp-model-studio/outputs/nfl-semantic-lab-v1/runs/7a651ec80b3b77106b018dd6739f55e26e45cbcf5e1f8811d6557f039d372f69/result.json>). Raw distribution 90% intervals and separately calibrated probability metrics must not be conflated.

| Pipeline | Calibrated minus M1 | 95% season/week interval | Weeks 1–4 raw minus M1 | 95% interval |
|---|---|---|---|---|
| DYNAMIC_TEAM_SCORE_BLEND | +0.017244 | [0.005913, 0.028983] | +0.026939 | [0.005904, 0.04832] |
| HGB_C1 | -0.001599 | [-0.010545, 0.007673] | +0.011128 | [-0.001053, 0.022879] |
| HGB_C2 | +0.002279 | [-0.007236, 0.012058] | -0.001775 | [-0.015482, 0.012302] |
| HGB_C3 | +0.002183 | [-0.007243, 0.011986] | +0.011857 | [-0.000866, 0.023908] |
| HIST_GRADIENT_BOOSTING_B_T2 | -0.003190 | [-0.009189, 0.002811] | -0.002661 | [-0.011571, 0.006747] |
| XGBOOST_C1 | +0.000466 | [-0.007608, 0.008798] | +0.007270 | [-0.003617, 0.01685] |
| XGBOOST_C2 | -0.002895 | [-0.011949, 0.005903] | +0.009163 | [-0.008147, 0.023878] |
| XGBOOST_C2_TUNED | +0.001342 | [-0.007865, 0.010493] | +0.011920 | [-0.004675, 0.026747] |
| XGBOOST_C3 | -0.003546 | [-0.012008, 0.004555] | +0.009384 | [-0.004804, 0.022764] |
| XGBOOST_C3_TUNED | -0.003866 | [-0.012094, 0.004296] | +0.008119 | [-0.006903, 0.021229] |

Intervals resample season/week blocks and are exploratory after model/design selection. A favorable point estimate alone does not establish improvement. C2-minus-C1 and C3-minus-C2 paired effects are recorded separately in results, with common candidate simulation draws. The older baseline random streams differ. No whole-package result is attributed solely to QB information, pooling or calibration. The two tuning studies each use two predeclared configurations within chronological outer-training periods; they are not a repeated broad sweep.

[Reporting supplement](<C:/Users/james/asp-model-studio/outputs/nfl-semantic-lab-v1/reporting/sha256/e2f05ee9dd56dff2e67f72b119fb833d8f91d4011b7ed38434f39b03d355f2f5/supplement.json>) adds raw/calibrated early-season paired intervals, five-block low-exposure instability labels, expanded-column counts and actual branch counts: 3,520 prior-only, 244,286 blended, two unresolved-native rate cells per complete candidate validation ledger. The eight-game personnel proxy is descriptive and unstable. Its 44 completed chronological calibration fits are counted from executed fold receipts, not invented fit-start telemetry.

## Matched model and sportsbook evidence

Class A: saved fold-refitted M1/HGB, the transparent dynamic baseline and every new candidate are evaluated on the same 1,408 games. The pinned FiveThirtyEight historical Elo reconstruction matches 269 games in 2020, of which 268 are decisive. Exact as-published timestamps are unverified. It is a historical model reference, not a current sportsbook comparison. nfelo is not imported because permitted historical prediction vintages and repository licensing remain unresolved.

Class B: all 1,408 games match historical moneylines/spreads/totals. Four realized ties are excluded only from the two-way tie-void analytical moneyline comparison, leaving 1,404. Proportional no-vig removes bookmaker margin; model home probability is pHome/(pHome+pAway), leaving the original tie forecast untouched. Market two-way log loss is 0.607054. Positive nflverse spread means expected home winning margin; totals use final scores including OT. There are 32 spread pushes and 18 total pushes. Bookmaker identity, quote time and book-specific settlement terms are unverified, so this is **not an executable backtest or wagering edge**.

| Model | Matched decisive games | Conditional two-way LL | Difference versus market | 95% season/week interval |
|---|---|---|---|---|
| M1_RECIPE_RAW | 1404 | 0.635841 | +0.028787 | [0.018918, 0.038538] |
| M1_RECIPE_CALIBRATED | 1404 | 0.643258 | +0.036204 | [0.023573, 0.048402] |
| HGB_T2_LEGACY_RAW | 1404 | 0.635691 | +0.028637 | [0.017317, 0.039116] |
| HGB_T2_LEGACY_CALIBRATED | 1404 | 0.640318 | +0.033264 | [0.020807, 0.045308] |
| XGBOOST_C1_RAW | 1404 | 0.637085 | +0.030031 | [0.01895, 0.040586] |
| XGBOOST_C1_CALIBRATED | 1404 | 0.644490 | +0.037436 | [0.024921, 0.049673] |
| HGB_C1_RAW | 1404 | 0.640315 | +0.033261 | [0.022172, 0.044365] |
| HGB_C1_CALIBRATED | 1404 | 0.642094 | +0.035040 | [0.023105, 0.047193] |
| XGBOOST_C2_RAW | 1404 | 0.634646 | +0.027592 | [0.016285, 0.03782] |
| XGBOOST_C2_CALIBRATED | 1404 | 0.640770 | +0.033716 | [0.020674, 0.046172] |
| HGB_C2_RAW | 1404 | 0.638618 | +0.031564 | [0.020816, 0.042732] |
| HGB_C2_CALIBRATED | 1404 | 0.645982 | +0.038928 | [0.027168, 0.050663] |
| XGBOOST_C3_RAW | 1404 | 0.634761 | +0.027707 | [0.015768, 0.038413] |
| XGBOOST_C3_CALIBRATED | 1404 | 0.640335 | +0.033281 | [0.020348, 0.045563] |
| HGB_C3_RAW | 1404 | 0.641410 | +0.034356 | [0.023114, 0.045725] |
| HGB_C3_CALIBRATED | 1404 | 0.645401 | +0.038347 | [0.026065, 0.050452] |
| DYNAMIC_TEAM_SCORE_BLEND_RAW | 1404 | 0.655029 | +0.047975 | [0.036052, 0.060006] |
| DYNAMIC_TEAM_SCORE_BLEND_CALIBRATED | 1404 | 0.661255 | +0.054201 | [0.040778, 0.067148] |
| XGBOOST_C2_TUNED_RAW | 1404 | 0.636712 | +0.029658 | [0.018339, 0.040445] |
| XGBOOST_C2_TUNED_CALIBRATED | 1404 | 0.645052 | +0.037998 | [0.023839, 0.05118] |
| XGBOOST_C3_TUNED_RAW | 1404 | 0.634333 | +0.027279 | [0.015949, 0.038266] |
| XGBOOST_C3_TUNED_CALIBRATED | 1404 | 0.639978 | +0.032924 | [0.019973, 0.04539] |

Class C: zero of 1,408 events has an authorized timestamp-matched quote. The implemented join requires canonical event, bookmaker, original timezone-aware observedAtUtc, both prices, settlement contract, frozen forecast cutoff and kickoff. It excludes quotes after cutoff and non-pregame forecasts; it selects the latest eligible quote per event/book. Missing coverage and the exact bounded export request appear in [benchmark scoreboard](<C:/Users/james/asp-model-studio/outputs/nfl-research-benchmarks-v1/sha256/c48e045a628d4ab8ad6a74b5ccf3a6485ccc6dcedf9f5d948e2267c8d5721bae/scoreboard.json>). Do not purchase historical access. Already entitled quotes or future permitted pre-cutoff collection are needed for this evidence class.

## Actual simulations delivered to Claude

The separate immutable NFL_LABS_CONTRACT_V1 interface preserves old exact three-file forecast bundles. Sixteen M1 supplements recover the exact empirical 10,000-draw joint score distributions, not invented sequences; original generation order is not claimed. Home/away/tie probabilities and score summaries reconcile exactly. No M1 drive paths are fabricated.

Drive engine `NFL_DEVELOPMENT_CONDITIONAL_DRIVE_V2` is a distinct uncalibrated research model. It fits multinomial drive outcomes using field position, time, score differential, possession side and prior offense/defense strength, then samples paired empirical progression/duration conditional on outcome and starting field band. Validation: 6,060 drives from 285 games in 2024; conditional drive log loss 1.521789, unconditional 1.736621. This is observed-drive-state validation, **not pregame game-forecast calibration**.

Final fitting uses 42,205 drives from seasons 2018–2024; the cutoff includes the 2024 postseason ending 2025-02-09, not protected season 2025. There are 32 current drive/scenario supplements across 16 events, each with 1,000 completed simulations and six distinct persisted representative games. BASE and a 0.95 drive-duration sensitivity are separately identified. This pace sensitivity is not a claim of a known tactical intervention. No QB/player/route/tackle identities or within-drive physical paths are invented.

The V2 correction uses only the actual starting kickoff to establish touchback evidence (247 corrected flags; 8 ambiguous and 94 unknown kickoff records excluded from that bank). V1 objects/receipts are preserved. Regulation ties, overtime entry and final ties are separate. Current regular-season overtime includes the 10-minute cap and both-possession opportunity subject to time; postseason continuation is explicitly unsupported. Current kickoff uses the standard 35-yard touchback assumption, with the landing-zone exception, onside kicks and detailed penalty/timeout strategy unsupported. Source/rule assumptions are explicit.

Drive team context remains 2024 history discounted across two offseasons. These are current-created **stale-input mechanics simulations**, not freshly informed 2026 QB/injury forecasts. Metadata successors use the actual registered source retrieval cutoff 2026-08-29T13:34:33.063899+00:00, with historicalEvidenceThroughDate=2025-02-09 separately labeled GAME_DATE precision. They preserve every numerical V2 forecast identity, population and path; retrieval time does not imply fresh team evidence. New semantic candidate production has zero forecasts and 16 explicit skips: no permitted 2025 initialization/current semantic-state authority. Caller-supplied authorization booleans are not accepted as authority. The frozen publisher is exercised on a clearly labeled historical deterministic fixture only, with zero mismatch.

Coordination contract: `C:\Users\james\asp-model-exchange\contracts\NFL_LABS_CONTRACT_V1.json`.
Discovery pointer: `C:\Users\james\asp-model-exchange\nfl-labs-simulation-supplements\current.json`.
Drive handoff: [drive-handoff.json](<C:/Users/james/asp-model-studio/outputs/nfl-labs-simulation-v1/sha256/0db092d91c5250f40f9da809b4e47f337a0d32e40c174177ddd532bc6eefcc63/drive-handoff.json>); SHA-256 `0db092d91c5250f40f9da809b4e47f337a0d32e40c174177ddd532bc6eefcc63`.

**Exact Claude instruction:** Read NFL_LABS_CONTRACT_V1.json and the separate nfl-labs-simulation-supplements/current.json. Verify each immutable artifact and manifest checksum/byte count. Import the 16 unchanged M1 score-distribution supplements and 32 current V2 drive/scenario supplements. Keep M1 scores separate from the independent drive engine and BASE separate from pace sensitivity. Display stale source dates and unsupported scenarios. Do not execute models, modify old three-file bundles, promote a track or grant wagering authority.

## Runtime, preservation and verification

| Attempt | Estimator starts | Estimator completions | Completed outer folds | Dynamic fits | Logged final calibrator starts |
|---|---|---|---|---|---|
| 4fda808e99d1404e6eab1acc7c31933d51e7533e223c1b2c114235a203f8c2c5 | 21 | 20 | 5 | 0 | 0 |
| 7a651ec80b3b77106b018dd6739f55e26e45cbcf5e1f8811d6557f039d372f69 | 248 | 248 | 45 | 10 | 2 |

These are actual receipts, not scheduled fit slots. Each score system has separate home/away estimators plus training-only residual-calibration fits. The first attempt stopped at Windows joblib CreateFile WinError 5; its receipts and completed work remain intact. The supported Windows recovery used a new code-addressed identity after correcting undefined-opportunity handling. Final calibrator starts in the table are explicitly logged; chronological OOF calibration fits are also performed and separately accounted in the session verification receipt. Dynamic parameter estimation is not called an XGBoost/HGB estimator fit. Completed main run elapsed time: 1588.3 seconds. Drive fitting has two fits per version, four total including preserved V1; no broad grid.

Focused verification covers prior-date availability, native undefined-rate handling, frozen reload, original score reproduction, drive accounting/kickoff clocks, import checksums, timestamp-quote joins and project-authorized UI artifact links. Fourteen distinct focused tests and one relevant TypeScript/Vite build passed. No entire repository suite was run. [Session verification receipt](<C:/Users/james/asp-model-studio/outputs/nfl-semantic-session-v1/SESSION_VERIFICATION.json>) records actual counts and final browser evidence. The signed-in browser showed 35 result rows (24 prior + nine new + two reused baselines) and 228 verified artifact links. The representative artifact endpoint returned HTTP 200, but direct JSON navigation was blocked by the in-app client (net::ERR_BLOCKED_BY_CLIENT); its download/view completion is not claimed. Local artifact links remain supplied. No AISP writes, paid provider requests, official model/policy/position changes or sealed OOT reads occurred.

## Visible results and next action

[Model Studio NFL laboratory](http://127.0.0.1:5274/workflows/nfl?projectId=sports-project-nfl-overnight-model-lab-v1#nfl-laboratory) contains the previous 22 screens plus two tuning results and the new semantic results, definitions, raw/calibrated comparison chart, early-season filtering and verified artifact downloads. Gen 1/V2.1 and V18 remain separate and unchanged.

Next: Claude can import the simulation supplements now. Before a genuinely current semantic candidate forecast, obtain a separately authorized, checksummed operational prior/current-state packet that does not reopen sealed evaluation data. Before any market-edge claim, obtain entitled timestamped prices with bookmaker/settlement metadata and freeze the evaluation rule. The present Development evidence does not promote a challenger.

## Primary method/source references

- [nflverse release timing](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html): injury interruption after 2024, and differing release timing across source families.
- [nflverse schedule dictionary](https://nflreadr.nflverse.com/articles/dictionary_schedules.html): target fields, schedule time and spread signs.
- [FiveThirtyEight historical Elo implementation](https://github.com/fivethirtyeight/nfl-elo-game): pinned historical reconstruction, not timestamped prospective predictions.
- [PFF Bayesian QB discussion](https://www.pff.com/news/nfl-2020-quarterback-rankings): conceptual prior/uncertainty reference; no proprietary grades ingested.
- [nfelo QB reference](https://github.com/greerreNFL/nfeloqb) and [market-informed nfelo ratings](https://www.nfeloapp.com/nfl-power-ratings/): reviewed, not unlicensed copied predictors.
- [Historical odds access](https://the-odds-api.com/historical-odds-data/): paid history not requested.
- [Official NFL playing rules](https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf): regulation and overtime rules used by the independent research engine, with unsupported exceptions disclosed above.
- [Sportradar Custom Bet](https://docs.sportradar.com/uof/custombet-cb/intro): simulation-based dependence/pricing concept, not a disclosed reproducible cold-start model.
