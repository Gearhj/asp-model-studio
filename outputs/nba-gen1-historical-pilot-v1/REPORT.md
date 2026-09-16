# NBA Gen 1: genuine-data historical point/Elo pilot

Two genuine NBA benchmarks are fitted and assessed. Rebuilt chronological Elo improves winner probabilities and expected margins over the league/home-court benchmark in every assessed season. This is the first **reduced-feature Category-A research baseline**, not a selected full joint-distribution Gen 1 champion or a current-season forecasting release.

The historical development dependency is resolved through FiveThirtyEight’s publisher-distributed, CC BY 4.0 NBA dataset. No new source permission request is pending. The previous SportsDataIO inventory remains unchanged as a historical receipt; its six-season paid-provider request is superseded for this reduced internal pilot.

| Source option | Verified usable evidence and rights | Access/usage | Decision |
|---|---|---|---|
| Existing SportsDataIO configuration/retained export | Prior inspection found six fixture payloads (8,637 bytes); no real NBA training population or verified NBA entitlement/training authorization. Real seasons and prospective derived rights remain unestablished. | Existing configuration reused for inspection; zero new paid-source requests, no account/trial/credit. | Fixtures are ineligible. No paid endpoint probe. |
| FiveThirtyEight official nba-elo/nbaallelo.csv | Real final game scores, NBA/ABA identity, season, game date, source team/franchise aliases and H/A/N orientation, 1947–2015. Publisher explicitly licenses datasets CC BY 4.0; retention, adaptation and internal training permitted with attribution. No separate derived-forecast prohibition found. | One anonymous dataset GET, 18,173,265 physical bytes, $0. | Admitted latest six seasons for Category A only. No third option needed. |

Rights review used four retained documentation/metadata responses (91,512 bytes) plus two preceding successful metadata probes whose response sizes were not retained. Total measured response bytes including the dataset are 18,264,777; cumulative bytes for the two unmeasured probes are explicitly unknown. No spend, sportsbook credits, account, trial or vendor contact. The one-call dataset allowance is exhausted; reruns reuse cached exact bytes.

Actual acquisition: **2026-09-14T01:50:46.819078+00:00**. Source file SHA-256 `d46ed3540ee8d9eca31b3e94cc8c777e0be5156173d814ebf65b8195e8d616bc`. The December 2022 publisher file commit is a formatting revision, not a per-game availability clock. [Retained rights and attribution](SOURCE.md) and [source option review](source-option-review.json) document the published license; the MIT software license is not the data-rights basis.

| Season | Declared role | Real games retained | Home/away fitting or assessment targets | Neutral history only |
|---|---|---:|---:|---:|
| 2009-10 | INITIAL_FIT_WARMUP | 1,230 | 1,230 | 0 |
| 2010-11 | DEVELOPMENT | 1,230 | 1,228 | 2 |
| 2011-12 | DEVELOPMENT | 990 | 990 | 0 |
| 2012-13 | DEVELOPMENT | 1,229 | 1,228 | 1 |
| 2013-14 | VALIDATION | 1,230 | 1,229 | 1 |
| 2014-15 | FINAL_CATEGORY_A_HOLDOUT | 1,230 | 1,228 | 2 |

**7,139 real games** are retained as history; 7,133 have source home/away orientation. The 1,230 initial-fit games are not assessment units; **5,903 distinct games** are assessed. Six neutral games update earlier-date history and Elo with zero home advantage; their publisher focal axis is never asserted as actual home and is excluded from target fitting/scoring. The source’s 2011–12 population contains 990 games and 2012–13 contains 1,229. This is verified archive coverage, not certification of a complete schedule/cancellation ledger.

Both mirrored rows reconcile in score, result, team/franchise, date and location. Each game counts once. The normalization preserves stable publisher game IDs and season-specific source aliases mapped to exact publisher franchise IDs. It does not invent NBA.com IDs or replacement schedules. [Reconciliation](holdout/reconciliation.json).

Metadata-only selection and roles were frozen before score conversion. The new Category-A final holdout is 2014–15; it is not the originally proposed modern 2025–26 OOT population. The original strict NBA pipeline and protected MLB/NFL partitions were untouched. [Declaration](declaration.json).

Evidence A: finalized records acquired today support qualified historical reconstruction. Evidence B (verified historical information availability) is unavailable. Evidence C (future evidence captured before cutoff) has not been produced. The earlier instruction prohibiting reconstructed pregame facts without valid timestamps is superseded for A by the user’s explicit continuation; strict B/C gates remain unchanged.

The separate builder emits 50 supported numeric fields: reconstructed Elo; earlier team scoring and allowance; prior-season/shrunk last-20 scoring; rest, back-to-back and 3/7/14-day density; and support counters. It does not manufacture the original 65 box/efficiency features. All targets on date D are emitted before any D result updates state; no tipoff or next-day publication timestamp is invented. Earlier dates are an ordering rule, not certification that their finalized revision was available then.

Feature audit: 81 initial/warmup history-limited rows across the retained population; **zero assessed games** lack the five-game current/prior history support flag. Same-day repeated-team ambiguities: 0. All final history dates precede target dates. Early current-season games remain assessed, backed by prior-season history. [Feature contract and audit](holdout/feature-audit.json).

The original `models.fit_model` code is unchanged. League fits mean home margin and total from earlier seasons, and uses the same training cohort’s home-win fraction. Elo is rebuilt from wins with initial rating 1500, K=20, home advantage 65, scale 400 and 2/3 between-season regression; margin is the existing training-only linear association with the Elo difference, while total stays at the earlier-season mean. Elo winner probability uses its fixed logistic rating formula. The point-score link and winner link are distinct; no coherent joint-distribution claim follows.

Ten model artifacts are retained: both families for each assessment season. Fit parameters use strictly earlier seasons and stay frozen within that season; Elo history updates from earlier dates only. No random CV, calibration, tuning or blend. Ridge and HGB were **not fitted** because their declared possession/box feature population is absent. The existing library’s fitted-input gates were not loosened.

| Role / games per model | Model | Correct picks | Log loss ↓ | Binary Brier ↓ | Home MAE ↓ | Away MAE ↓ | Margin MAE ↓ | Total MAE ↓ |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| DEVELOPMENT / 3,446 | league | 2,073 (60.16%) | 0.6725 | 0.2398 | 9.379 | 9.429 | 10.441 | 15.771 |
| DEVELOPMENT / 3,446 | elo | 2,324 (67.44%) | 0.5987 | 0.2061 | 9.098 | 9.198 | 9.329 | 15.771 |
| VALIDATION / 1,229 | league | 714 (58.10%) | 0.6807 | 0.2438 | 9.621 | 9.480 | 10.593 | 15.770 |
| VALIDATION / 1,229 | elo | 807 (65.66%) | 0.6092 | 0.2112 | 9.267 | 9.295 | 9.489 | 15.770 |
| FINAL_CATEGORY_A_HOLDOUT / 1,228 | league | 706 (57.49%) | 0.6828 | 0.2448 | 9.182 | 9.356 | 10.787 | 14.913 |
| FINAL_CATEGORY_A_HOLDOUT / 1,228 | elo | 828 (67.43%) | 0.6031 | 0.2081 | 8.932 | 9.064 | 9.628 | 14.913 |

Brier is binary `(pHomeWin − I(home win))²`. Away win probability is exactly `1 − pHomeWin`; final NBA tie probability is zero. These probabilities do not come from simulation draws. Log loss uses the probability of the observed winner. All point errors are absolute points. [Development/Validation results, season and predeclared subgroup tables](development-validation/assessment.json); [one-time holdout results](holdout/assessment.json).

| Holdout Elo minus league | Mean difference | Paired 95% interval |
|---|---:|---:|
| log_loss | -0.07968 | [-0.09989, -0.05991] |
| binary_brier | -0.03673 | [-0.04624, -0.02777] |
| home_mae | -0.25060 | [-0.36010, -0.15318] |
| away_mae | -0.29270 | [-0.43186, -0.17897] |
| margin_mae | -1.15827 | [-1.45642, -0.85737] |
| total_mae | +0.00000 | [+0.00000, +0.00000] |

Negative differences above favor Elo. Intervals resample paired whole-game scores in calendar-week blocks (2,000 replicates, seed 731101; holdout has 25 weeks). This quantifies variation across these historical games under that block scheme, not source-vintage error or current-era transportability. Simulations are not independent observations; this pilot generated none.

Elo improves all five seasons’ winner log loss/Brier and home, away and margin MAE. Totals are identical because both configurations use the same constant expected total. The final-holdout point-model coefficients are associations, not causes:

`{"coefficient": 0.038531940821649534, "constantTotal": 198.37002540220152, "feature": "home_elo_minus_away_elo", "intercept": 2.929876978828046, "interpretation": "Training-only OLS association; Elo ratings themselves come from earlier games. Intercept represents learned league home advantage, not a causal estimate.", "target": "HOME_MINUS_AWAY_MARGIN", "trainingDifferenceMedian": 0.0}`

The 60–70% Elo home-win band is close to observed frequency: Validation 65.02% versus 65.33% (225 games), holdout 65.04% versus 65.24% (233). The 80–90% band predicts 84.08% versus 86.99% observed in Validation (123), and 84.14% versus 87.23% in holdout (141). These descriptive gaps do not justify fitting a calibration adjustment. Early-season (<10 current games for either team) log loss is worse in each role, but margin error is not consistently worse. Back-to-back comparisons reverse direction in holdout; no stable rest mechanism is established.

Pace, opponent-adjusted efficiency, four-factor statistics, injuries, lineups, player strength and original revision vintages are absent. No conclusion is possible about pace-specific or joint-score tail error. Full-game residual pairs are retained in the prediction parquet for later governed use, but overtime-period evidence needed by the existing joint simulator is missing. No tied simulated scores were discarded, no overtime adjustment was applied, and no energy/CRPS/interval or validated joint-calibration claim is made. The original primary joint-energy selection gate therefore remains unassessed; both benchmarks are preserved without champion promotion.

**Single remaining data dependency for full/current Gen 1:** a permitted current NBA game/team-box source with actual capture and revision lineage, genuine future schedule/tipoff identities, and the overtime-period evidence required by the existing joint simulator. The present licensed archive ends in 2015. This is an evidence/coverage dependency, not a pending bespoke permission for the completed internal pilot. No current forecast or AISP package/import is claimed; the strict future runner remains available once its genuine inputs exist.

**One next modeling step:** with that box population, run the existing bounded regularized margin/total screen on a separately declared later chronological population. Matchup-independent expected totals are the concrete current limitation (holdout total MAE 14.913 points). Do not tune on this inspected 2014–15 holdout or build a specialist now.

Reproduce/verify from the repository root (existing receipts are reused without re-assessing holdout):

```powershell
.venv/Scripts/python.exe -B scripts/acquire_nba_gen1_historical_source.py
.venv/Scripts/python.exe -B scripts/declare_nba_gen1_historical_pilot.py
.venv/Scripts/python.exe -B scripts/run_nba_gen1_historical_pilot.py --stage development-validation
.venv/Scripts/python.exe -B scripts/run_nba_gen1_historical_pilot.py --stage holdout
.venv/Scripts/python.exe -B scripts/verify_nba_gen1_historical_pilot.py
```

Fresh numerical reconstruction can be run in a separate output directory containing copies of the declaration pointer and acquisition/rights receipts; the pinned original source remains the same. Such a repeat is reproduction of an already observed holdout, not a new untouched assessment. Timestamps belong to the actual repeat and must not replace the saved receipts.

Focused verification: 22 source/date-history checks and 3 scorer/pairing checks passed. Reloading all 10 fitted artifacts exactly reproduced expected scores and winner probabilities for all 11,806 model-game rows. Paired cohorts, probability mass, target exclusion, neutral policy and declaration/freeze ordering passed. All 21 original tracked NBA files and all 8 inherited dirty files retain their prior state. [Verification receipt](verification.json).

NBA remains research-only and unfunded. No model promotion, AISP writes, scheduler, account, wager, source spend or MLB/NFL operational changes.

Attribution: Game data published by FiveThirtyEight, with game-information provenance credited to Basketball-Reference.com, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). ASP Model Studio filtered regular seasons, reconciled identities, reconstructed histories and fitted independent benchmarks. No publisher endorsement is implied.
