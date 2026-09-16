# ASP Model Studio and AI Sports Predictor: project-management handoff

Prepared September 15, 2026, America/New_York, from retained reports and receipts. This document describes completed work and its evidence; it does not authorize model promotion, acquisition, scheduling, or wagering. Operational observations have their own timestamps below.

## Executive summary

ASP Model Studio now has real forecasting implementations for MLB, NFL, NBA and College Football, supported by source registration, chronological feature construction, model artifacts, simulation, scoring, immutable exchange publication and consumer handoffs. AI Sports Predictor (AISP) consumes those forecasts and owns the market, presentation and decision layers.

- **MLB:** unrestricted V18 is the controlling final-pregame model. Its 5,000-draw game population supports winner probabilities, score distributions and totals. Several duration, transition and score-filtering alternatives have been implemented and assessed without earning promotion. A separate day-before team model improves historical winner probability scores but awaits a complete admitted current-history export.
- **NFL:** M1 is the active XGBoost baseline, separate from the experimental play simulator. A real current-season source defect was repaired without changing fitted weights. The latest inspected consumer observation confirms all 16 Week 2 forecasts and their exact paper-eligibility supplements imported. QB-conditioned residual sampling failed its advancement gate.
- **NBA:** a real score/date model now covers history through 2025–26. Ridge supplies point expectations and Elo supplies independent winner probabilities. A separate paired-residual joint distribution improves distribution scoring on reused historical evidence. Its close-score correction repairs excess one-point mass, with negligible change in overall proper scores. An early BOS–DET research comparison is published.
- **CFB:** a 35-feature Ridge baseline beat the league and Elo benchmarks on the declared historical cohorts. Current CFBD inputs support a genuine Syracuse–Pittsburgh research forecast. Cluster and extended-gap challengers did not qualify for advancement.

No reviewed result establishes sustained betting profitability. Forecast accuracy, distribution quality, operational reliability and wagering economics are different claims.

| Sport / use | Numerical baseline | Retained population | Current evidence-based status |
|---|---|---|---|
| MLB final pregame | V18 histogram gradient boosting PA estimator plus game simulator | 5,000 joint away/home draws | Existing controlling configuration preserved; Windows publisher running under its canonical owner |
| MLB day-before show | Logistic C1 winner model plus independent Poisson alpha1 score means | No joint simulation | Implemented and historically assessed; current-history input dependency remains |
| NFL | NFL_M1_XGBOOST / NFL_M1_2026_RESEARCH_SHADOW_V1 | 10,000 paired residual draws | Research baseline and bound virtual-experiment eligibility; 16 Week 2 imports confirmed |
| NBA | Corrected Ridge alpha100 points; separate Elo probabilities | Original point forecast: 0 draws; separate joint research package: 10,000 | Real fitted research model and early future comparison published |
| CFB | Ridge alpha100; separate Elo and joint-output channels | 10,000 paired residual draws where supported | Real research baseline and current forecast; no cluster/gap promotion |

## 1. What Model Studio has built

Model Studio is the model-development and forecast-production workbench. Its local UI is normally at `http://127.0.0.1:5274`, its backend at port 8101, and its runtime state under `.runtime/asp-model-studio`. An old README understates the current NBA/CFB capability; the later artifacts indexed with this handoff govern those claims.

The implemented system includes:

1. **Data admission and lineage:** retained source objects, physical SHA-256 hashes, actual acquisition clocks, source revisions, identity mappings and recorded permitted uses.
2. **Feature contracts:** explicit feature definitions, treatment/preprocessing bindings, missing-input handling, cutoff checks and model-specific eligibility.
3. **Model development:** transparent benchmarks, bounded candidate screens, chronological folds, frozen selection rules and separately identified refits.
4. **Simulation and probability support:** joint away/home populations, marginal score/total/margin distributions, winner probabilities, interval and tail summaries, and reproducible seeds.
5. **Evaluation:** log loss, Brier, MAE, CRPS, joint energy scores, coverage, reliability, paired uncertainty and clearly identified historical/prospective cohorts.
6. **Production controls:** canonical owners, locks, immutable versions, idempotent reuse, source freshness checks and explicit unsupported/fallback dispositions.
7. **Exchange contracts:** versioned forecast packages, distribution exports, paper-eligibility supplements, preview artifacts, discovery indexes and concise consumer handoffs.
8. **Diagnostics:** passive MLB simulation-population counters, postgame evidence reconciliation, component comparisons and preservation of unsuccessful experiments.

Feature counts are not counts of independent information. The feature audit found MLB's 246 raw dependencies become 273 treated and 436 encoded inputs; NFL uses 197 numerical inputs; NBA uses 78 score/date predictors; CFB uses 35. Some flags or categories are constant or represent missingness rather than additional basketball/football/baseball knowledge.

## 2. How Model Studio and AISP work together

| Responsibility | Model Studio / Codex | AISP / Claude |
|---|---|---|
| Model inputs | Governed intake, retained evidence, identity and feature construction | Consumer-side evidence and operational services within its authority |
| Forecasting | Fit/freeze models; generate predictions and joint populations | Import the exact producer forecast; do not infer unavailable probabilities |
| Integrity | Publish model/input hashes, clocks, configuration and immutable package | Validate bytes, identities, horizon, authority and duplicate imports |
| Sportsbook data | Does not own quote collection or paid sportsbook requests | Collect quotes, preserve actual timestamp/market definitions and provider budgets |
| User experience | Supply structured probabilities, limits and explanation evidence | Theater, live-score UI, Show Board, Over/Under and Parlay Watch |
| Decisions / money | No authority from a research artifact alone | Policy gates, virtual positions, staking, account state and settlement |
| Results | Score frozen forecasts against permitted governed finals | Export final revisions, consumer evaluations and execution/decision receipts |

The shared exchange is `C:\Users\james\asp-model-exchange`; AISP's repository is `C:\Users\james\ai-sports-predictor`. Normal flow is:

**Admitted evidence → Studio features/model → immutable forecast package → AISP validation/import → market comparison and authorized policy → governed final/evaluation evidence → Studio assessment.**

Source availability, acquisition, feature cutoff, forecast creation, publication, import and decision are separate clocks. Republishing identical inputs must not make an old forecast look newly generated. A later forecast is a successor, not an overwrite. Publication does not establish import; import does not establish display, a decision, promotion or profitability.

The exchange carries exact game orientation and provider IDs, model/version and preprocessing hashes, probability units, simulation population bindings, checksums and byte counts. Logical content addresses are not always physical manifest hashes. A recent NFL supplement interoperability repair also established the consumer's canonical UTF-8 serialization with `ensure_ascii=False`, sorted keys, compact separators and no NaN; an em-dash must remain the same parsed content across producer and consumer.

### Totals and explanations

Totals use every original paired draw: `total[i] = away[i] + home[i]`. The MLB totals export covered **43 distinct games and 44 exact forecast versions**, each with its original 5,000 draws. Inning counters are unnecessary for totals; 37 objects unsupported by the separate score-limit experiment remained usable for totals.

For Over at line L: win is `total > L`, push is `total = L`, loss is `total < L`; Under reverses win/loss. Probabilities are fractions in [0,1]. Expected net return at decimal price d is `pWin × (d−1) − pLoss`; push-aware fair odds are `1 + pLoss/pWin` when pWin is positive. AISP owns actual quotes, combinations and tickets. A point forecast alone cannot supply an Over probability.

Explanation handoffs distinguish observed postgame events from causal model failures. Simulation probabilities summed along simulated exposures are not probabilities captured before the actual PAs. A large observed inning does not, by itself, identify a transition defect or PA miscalibration.

## 3. Data and evidence qualifications

| Sport | Main retained data | What it supports | Important limit |
|---|---|---|---|
| MLB | Retrosheet game logs/events; admitted FD1 historical research/prior data; MLB official schedule/roster/starter evidence; retained Statcast-derived history | Team models, PA features, transition/duration research, current inputs | Permissions and sealed status are object-specific. Current schedule or daily PA partitions do not prove complete season-score history |
| NFL | nflverse schedules, play-by-play, player/team weekly statistics and retained source vintages | Rolling team efficiency, scoring, pace/explosiveness and residual research | Current data availability does not certify historical pregame revisions or starting-QB knowledge |
| NBA | FiveThirtyEight historical pilot; Neil Paine recent Elo/game history; admitted SportsDataverse ESPN-derived 2025–26 export | Real regular-season scores/dates, Elo, rolling strength/rest and joint residuals | No team boxes, possession efficiency, injuries, projected lineups or player-strength inputs in the 78-feature baseline |
| CFB | SportsDataverse ESPN-derived historical schedules/boxes; configured CFBD current capture | FBS-v-FBS team score, yards, turnover, rest and strength features | Historical reconstruction, missing player/QB availability, restricted primary population |

Source attribution and admissions remain attached: Retrosheet attribution; FiveThirtyEight CC BY; Neil Paine MIT with upstream attribution; admitted SportsDataverse data under its recorded CC BY terms. These are existing source-review conclusions, not a new blanket grant for every external dataset or redistribution use.

We distinguish **A: historical development reconstructed from finalized records**, **B: historical assessment with verified then-available information**, and **C: genuine future forecasts captured before cutoff**. Most recent NBA/CFB/team-preview development is A. Chronological target exclusion helps, but cannot turn today's revised historical file into a vintage that was demonstrably available years ago.

### Protected evidence

MLB's August 14–27, 2026 Final OOT remains sealed. The permanent whole-game quarantine excludes MLBAM **823343, 824235 and 822693** before outcome access. Its identity accounting removes 230 of 14,067 observations, leaving 13,837 sealed; this is not permission to evaluate them. Starter-history permissions do not authorize tuning or assessment.

Not all 2025 MLB data is sealed: admitted FD1 prior/history and separately sealed Gen2/Gen3 evaluation objects have different uses. Earlier metadata-inspection incidents are documented with their qualifications; this handoff does not replace them with a claim that protected information was never surfaced. No protected payload was opened to prepare this report.

## 4. MLB: controlling V18 and the approaches tested

### Model and inputs

V18 predicts eight PA classes: **strikeout, walk/HBP/catcher interference, home run, single, double, triple, ball-in-play out, and other reach**. The frozen histogram-gradient-boosting estimator feeds the accepted base/out/runner simulator. The simulator already includes runner advancement and double plays; it is not a simple independent run generator. Starter removal and anonymous relief-template selection determine pitcher exposure. Named-reliever availability/talent has not been invented from roster membership.

The final path requires authentic confirmed batting orders and sufficiently fresh pitching evidence. It retains **5,000 paired game draws**, full scoring tails and extra-inning behavior, including the automatic runner. The enabled default remains unrestricted V18; calibration is disabled and unpromoted research components remain separate.

The frozen fold-5 estimator hash is `44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b`. Historical fitted-model chronology remains uncertified. Recorded-state PA predictions are not pregame rollouts.

### PA and completed-game evidence

| Evidence population | Size | Retained result | Interpretation |
|---|---:|---|---|
| Saved five-fold Development PA analysis | 501,539 PAs; 6,664 game IDs | V18 log loss **1.474590**; summed eight-class Brier **0.703065** | Descriptive historical comparison; not certified untouched OOT |
| V18 minus V14, same saved rows | Same population | Log-loss difference **+0.000031**, interval roughly −0.000213 to +0.000276 | No established overall V18 superiority |
| Fold-5 V18 doubles probability 5–10% | 14,375 PAs | **5.582% predicted vs 4.536% observed**; 802.42 expected vs 652 observed doubles | Repeated localized excess, without a justified correction |
| September 12 governed finals | 15 games | Winner log loss **0.67147**; binary Brier **0.23919**; total CRPS **3.35576** | One complete observed slate, not recurring-performance proof |

Across all five folds, the doubles band predicted 5.73% versus 4.80% observed on 92,292 PAs. Whole-population doubles bias was only +0.144 percentage points. V14 also overpredicted those V18-selected rows. Supported batter/pitcher-history and platoon contexts did not establish a specialist; no concrete mapping defect justified a blanket doubles reduction.

For September 12, mean predicted-minus-actual total was **−2.76 runs**. The separately reported seven funded positions had one win and six losses, $14.21 staked and −$12.78 net in that retained ledger. This is historical economic evidence for that selected cohort, not evidence that the model always loses or that a reported model-implied edge is a true edge.

### Observability added without changing forecasts

Passive simulation counters retain completed PAs, all eight sampled classes and pre-sampling probability sums, starter/relief exposure, inning runs, runner events and separate non-PA activity. Enabled/disabled comparisons reproduced the original numerical forecasts exactly. These counters are sidecars rather than revisions to the forecast population.

The three post-selected explanations were informative but not conclusive:

- **NYM–NYY:** actual PA exposure was ordinary (76 versus simulated mean 75.73), but NYM hit six HR versus mean 1.175; 12 of 5,000 draws reached at least six. This localizes an unusual event mix without proving conditional PA miscalibration.
- **PHI–ATL:** Philadelphia's starter faced nine batters, near the lower 2.2% of simulations; relief faced 34, near the upper 1.18%. Atlanta's eight-run inning appeared in 23 of 5,000 draws. Exposure and scoring concentration are both plausible contributors.
- **PIT–CHC:** the 3–4 result and event mix were ordinary under the model; observed starter exposure was longer than expected. No single repair was established.

Claude's byte-correct postgame v2 resolved the earlier checksum qualification. Its 1,176 play records comprise **1,173 completed PAs and three inning-ending baserunning outs**; runner activity within a completed PA is not discarded.

### Approaches tried and their disposition

| Approach | What changed / what was learned | Result / decision |
|---|---|---|
| V14 vs V18 PA comparison | Compared retained fitted-fold predictions | Near-zero overall difference; inherited chronology limitations remain |
| Calibration release candidate | Multinomial log-score correction | Failed advancement gate; disabled |
| RF artifact recovery | Looked for the exact earlier RF estimator/preprocessor | Saved predictions existed; reloadable original artifact not found in bounded search. An unrelated XGBoost file was not substituted |
| Hierarchical transition shrinkage | Retained sparse base/out/outcome cells and shrank toward legal backoffs | 16 historical games: log loss 0.625714→0.621315, but total and margin CRPS worsened; insufficient evidence |
| Starter-survival component | Frozen competing-risk continuation/removal/game-end model with six history inputs | Executable with strict history support and exact fallback; one prospective supported game completed |
| Pitcher archetype survival B/C | Continuous style profile and soft three-cluster conditioning | Path NLL A 2.672834, B 2.681120, C 2.684776; neither advanced |
| Score-limited population | Rejected whole draws above 5 runs/team/played half-inning or 14/team/game; never clipped scores | Development-derived 99th-percentile rule; mixed exploratory results and one prospective game; unpromoted |
| Team-only SHOW_PREVIEW | Separate 16-feature Logistic/Poisson model using prior completed scoring history | Historical winner gate passed; current inputs incomplete |
| Preview head-to-head shrinkage | One bounded Development-selected correction to score means | Reused 2024 deviance worsened; retain the team baseline |
| Exact-starter preview correction | Required authenticated target-starter announcement bindings | Zero eligible historical target bindings; unassessed, not a failed signal |

The archetype study used 4,537 training starts, 2,346 temperature-calibration starts and 2,175 later assessment starts, with profiles derived from 1,476,493 prior pitches. Its rejected variants remain useful negative evidence; a small BF-MAE improvement did not override the primary-score failure.

### Formal prospective closeout

Lower log loss, Brier and energy are better. Deltas below are **candidate minus its exact baseline**, using shared revision-1 finals. These are **two independent games**, not three.

| Game / final away–home | Arm | Draws | Home-win probability | Log loss | Binary Brier | Joint energy | Δ energy |
|---|---|---:|---:|---:|---:|---:|---:|
| COL–DET 824225, 1–8 | Baseline | 5,000 | .6258 | .468724 | .140026 | 2.741982 | — |
| Same game | Survival | 5,000 | .6272 | .466490 | .138980 | 2.740247 | −.001736 |
| Same game | Transition | 5,000 | .6256 | .469044 | .140175 | 2.712896 | −.029087 |
| CIN–MIL 823734, 4–3 | Baseline | 5,000 | .4962 | .685576 | .246214 | 1.058870 | — |
| Same game | Score-limited | 4,722 | .493859 | .680939 | .243896 | 1.000716 | −.058154 |

COL–DET survival slightly improved winner and energy scores, while total CRPS worsened by .002457. Transition improved energy but slightly worsened winner scores and total CRPS. CIN–MIL filtering excluded 278/5,000 draws (5.56%); both configurations already selected CIN correctly, and total CRPS improved .931136→.854517. None supports promotion from this sample. Missing matched pitcher counters leave allocation improvement unavailable without blocking whole-game scoring.

### MLB day-before preview: latest completed work

No suitable earlier Gen1/projected-lineup V18 path was established. The separate configuration is **MLB_TEAM_LOGISTIC_C1_POISSON_A1_SHOW_PREVIEW_V1**: 16 score-history features, recent-60 scoring/prevention/win history with shrinkage, prior-season information and support counts. It has no target lineup or starter claim and no joint score population.

The admitted Retrosheet population is **12,993 games, 2019–24**. Earlier history initializes the model; 2022–23 supply 4,858 Development assessment games; 2024 supplies 2,429 reused Validation games. Donor completion dates are conservatively D−2 or earlier. This excludes uncertain preceding-day completions but does not establish authentic historical publication vintages.

| 2024 reused Validation | League benchmark | Team preview |
|---|---:|---:|
| Winner log loss | .692393 | **.682164** |
| Binary Brier | .249623 | **.244537** |
| AUC | .500000 | **.584241** |
| Accuracy | 52.16% | **56.24%** |
| Total-run MAE | 3.421446 | **3.412327** |

Log-loss improvement is −.010229, with paired calendar-week 95% interval [−.016017, −.004589]; both Development seasons also improved. Total MAE's very small gain is uncertain. Unknown personnel is part of this model's defined scope, not a confirmed-lineup fallback.

The latest matchup study tested 48 bounded Development settings and froze a head-to-head shrinkage rule before reused 2024 assessment. Deviance changed **2.215138→2.215854**; total MAE **3.412327→3.413120**; probabilities/picks were unchanged. Neither meets the frozen gate. All 19,436 projected historical starter identity rows lacked the required pregame announcement binding, so starter-only was an exact baseline fallback. **Retain the original team preview.**

The actual remaining production dependency is one complete admitted history-owner export: 2025 MIL/PIT records and league totals for the prior, plus complete 2026 MIL/PIT games through September 15, including completion/revision clocks and last-60 reconciliation. Partial August/September data cannot satisfy it. Target retained in the request: MIL at PIT **823334**, September 17 16:35 UTC / 12:35 EDT; show deadline September 16 **20:00 UTC / 16:00 EDT**. No MLB preview forecast has been published. The separately estimated two-call/20MB/$0 official-source option has not been executed or authorized by this report.

## 5. NFL: M1, current-season repair and research alternatives

### Active M1

**NFL_M1_XGBOOST / NFL_M1_2026_RESEARCH_SHADOW_V1** uses 197 LONG_HISTORY_CORE inputs: 21 context variables plus 22 metrics across four windows for two teams. It uses 10,000 paired empirical-residual score draws, preserving home/away dependence. Its fitted training cutoff is February 8, 2026; manifest SHA is `ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9`.

The demonstrated input defect was a 2025 availability cap on existing nflverse PBP, player and team families. Current 2026 assets were available. The versioned repair preserved 326 earlier partitions, model weights, preprocessing and feature definitions. At the repair snapshot, previously missing PBP metrics now included the two completed games through September 10.

For PIT at NE on September 20, New England's September 9 game changed **80 actual features**, including EPA, turnover and last-4/8/16 aggregates. Expected PIT–NE scores moved **17.6889–24.6129 → 17.8508–24.8582**; NE probability moved .6976→.6989. This is a verified numerical input update, not an accuracy claim. That intake used three asset downloads plus three metadata queries: **2,308,295 response bytes, $0 incremental cost**, with its allowance retained rather than reset.

### Opening completed-game review

The following is the **two-game September 13 report cohort**, not a claim to cover every game completed by the date of this handoff. NFL Brier here is the summed HOME/AWAY/TIE score, range 0–2.

| Game | Predicted away–home | Actual away–home | Winner log loss | Three-class Brier | Absolute margin error | Absolute total error |
|---|---:|---:|---:|---:|---:|---:|
| NE–SEA | 19.94–22.75 | 10–13 | .555823 | .339997 | .1936 | 19.6900 |
| SF–LAR | 22.05–27.06 | 27–7 | 1.096614 | .853096 | 25.0165 | 15.1113 |

Mean log loss was .826219 and Brier .596546; one of two winner picks was correct. Observed QB interruption, turnovers and failed scoring possessions help explain realized pathways, but do not certify a model defect. M1 has no actual-play probability capture with which to assess those conditional predictions.

### Alternatives assessed

| Approach | Evidence | Main result | Decision |
|---|---|---|---|
| Lagged QB-usage-conditioned residual sampler | 838 earlier donors; 570 games in 2023–24; 456 applied/114 exact fallbacks | Energy 8.254915→8.254864; Δ 95% interval −.017956 to +.019055. Log loss .668019→.670767; Brier .447134→.449209 | Reject advancement; retain pooled M1 residuals |
| Separate hierarchical play-level simulator | 340,587 PBP rows / 1,942 games in 2018–24; 287,007 supported outcomes | Held-2024 conditional play log loss 1.182461 versus phase benchmark 1.516647; first 32 game rollouts log loss .708462 | Research engine, not an M1 replacement or matched proof of superiority |
| Drive competing-risk challenger | 108 matched games across three 36-game periods | 2023 energy worsened 8.4513→8.6472; 2024 small energy gain but total CRPS worsened | Retain existing play engine |
| Opponent-adjusted pass/run EPA and matchup features | Feature-audit recommendation using existing local evidence | Not implemented or assessed | Queued; do not start automatically |

QB context was lagged prior usage, not a certified forecast of tonight's starter. The play simulator explicitly evolves downs, possession and clock; its scenarios are sensitivity experiments, not validated counterfactual policy effects. Improving a conditional play score did not establish better full-game forecasts.

### Tie semantics and paper authority

The inspected DEN–KC forecast's 4.30% tie mass was **430 equal-final-score draws out of 10,000**, not an unexplained “other” bucket. That mass has not been validated as the frequency of actual final NFL ties. Do not silently renormalize it or convert its three-class Brier to MLB's binary convention.

The bound NFL virtual authorization is separate from numerical model quality: $1,000 virtual experiment, quarter-Kelly factor .25, 0.5%/$5 position cap, 1% same-game and 2% daily caps, minimum adjusted edge .02 and one daily NFL pregame quote under the recorded contract. AISP owns implementation and execution. A producer eligibility artifact does not authorize real-money operations.

The consumer observation at **September 15 16:17:21.484660 UTC** confirms **16/16 exact Week 2 forecasts and 16/16 corresponding supplements imported**. This is not 16 positions or proof that every UI or decision ran. Future changed forecast objects need their own exact bindings.

## 6. NBA: real-data baseline, robustness repair and joint distributions

### Development progression and data

The first genuine baseline used a 2009–15 FiveThirtyEight pilot. Later work admitted recent score/date history and fitted league/home-court, chronological Elo, Ridge and histogram-gradient-boosting candidates. This replaced fixture-only plumbing with actual modeling evidence.

Current history contains **8,289 regular-season games from 2019–20 through 2025–26**, with 8,177 oriented targets in the current refit. The latest season has 1,230 real games, 82/team; 1,225 are oriented assessment targets and five neutral games supply history only. All-Star, play-in, playoffs and replaced postponed identities are handled separately.

Original roles were 2019–20 initialization, 2020–21 through 2022–23 Development, 2023–24 Validation and 2024–25 historical holdout. Those later seasons are now inspected/reused. The 2025–26 assessment was declared before its first score conversion, but has also now been inspected. None is a fresh untouched test for another correction.

The **78 features** use earlier scores/dates, rolling offense/defense, variability, strength, schedule density, rest and support. They do not include possession-normalized efficiency, effective FG%, turnover/rebound rates or personnel information absent from the admitted data. Preprocessing is fitted within chronological training; target, same-date and later games are excluded.

### Point-model screen

| Original 2024–25 comparison, 1,221 games | Margin MAE | Total MAE | Team-score MSE |
|---|---:|---:|---:|
| Elo point benchmark | 11.095 | 15.950 | 149.778 |
| Ridge alpha100 | **10.947** | **14.898** | **135.576** |
| HGB candidate | 11.234 | 15.454 | 144.012 |

Ridge minus Elo margin MAE was −.148 (95% interval −.259 to −.038); total MAE was −1.052 (−1.356 to −.751). Elo winner log loss was .61674 and binary Brier .21444 versus league .68930/.24808. Ridge and HGB point comparisons retained the same independent Elo winner channel; their score improvement was not a new winner-probability improvement.

### Long-gap correction

Nine early Development forecasts had nonpositive scores, down to −138.182. The saved Ridge was fitted on ordinary rest of 0–8/9 days but received **129–287 calendar days** between retained regular-season games. Coefficients and date calculations reproduced: this was unsupported linear extrapolation, not a score-orientation bug.

The frozen repair treats season-openers and unsupported gaps as unavailable ordinary rest, preserves support flags/reasons, and applies training-only median imputation. Current ordinary support is 0–12 days; no final-score clipping was used.

| Development population | Games | Margin MAE before→after | Total MAE before→after |
|---|---:|---:|---:|
| All Development | 3,538 | 11.406→10.949 | 15.976→15.423 |
| Nine failed cases | 9 | 143.678→11.260 | 173.182→17.518 |
| Ordinary supported rest | 3,488 | 10.939→10.947 | 15.451→15.407 |

Reused 2023–24 and 2024–25 results slightly worsened. On 2025–26, corrected Ridge margin/total MAE was **11.393/15.178**, compared with Elo **11.484/16.319**; corrected-versus-original Ridge differences were tiny and uncertain. Elo picked **832/1,225 = 67.92%** correctly, log loss **.606258**, Brier **.208971**. Retain the correction for the demonstrated support failure, not a universal superiority claim.

Current point configuration is **NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1**. Ridge means and Elo probabilities are independently estimated and may legitimately favor different teams; they are not summaries of one simulated population.

### Paired-residual joint model and close-score correction

The separate joint model adds earlier chronological out-of-fold paired residuals to corrected Ridge expectations. It preserves home/away dependence and uses 10,000 draws. Targets/residuals already include overtime, so it does not append synthetic OT periods to regulation predictions. A documented nonnegative, unequal-integer support transformation accounts for ties/discretization rather than dropping draws.

| Reused historical assessment, 7,009 games | Dependence-broken benchmark | Paired residual model |
|---|---:|---:|
| Joint energy score | 10.465254 | **10.434157** |
| Total CRPS | 10.773072 | **10.755059** |
| Margin CRPS | 7.974640 | **7.873538** |
| Winner log loss | .626806 | .625271 |
| Binary Brier | .218509 | .217916 |
| Central 80% total coverage | 75.70% | 82.21% |
| Central 80% margin coverage | 88.87% | 81.01% |

Energy improvement was −.031097, calendar-block interval [−.037189, −.025006], approximately 0.30%. Winner-score differences were uncertain. Low-score tails remained somewhat heavy; joint and Elo winner picks disagreed on 972/7,009 games. This is useful distribution research, not prospective proof.

The next bounded correction, **CLOSE_MARGIN_PARITY_TRANSPORT_R8**, changes close-margin allocation while preserving every draw's total, winner and denominator. Predicted one-point final margins fell **7.78%→4.52%**, against **4.01% observed**. Energy changed only **10.43416→10.43408**, interval spanning zero. Total distributions and winner probabilities remain identical by construction. It is supported for further research, not promoted on a negligible score change.

### Genuine early future package

BOS at DET on October 20 has a retained early research comparison, provider game **401909088**. Baseline joint expectations are **BOS 112.026, DET 113.895**, total **225.921**, with DET probability **.5619**. Independent Elo gives DET **.581125**. The close-score arm changes means slightly to 112.017/113.904 while preserving total and winner probabilities.

Illustrative, not quoted sportsbook lines: at total **226**, Over .4821 / Push .0213 / Under .4966; at **225.5**, Over .5034 / Push 0 / Under .4966. The original point/Elo forecast remains intact with `drawCount=0`; the separate joint package has 10,000. Early schedule/player/lineup limitations remain. No consumer acknowledgement is inferred from publication.

## 7. College Football: fitted Gen 1 and rejected extensions

The admitted primary population is **8,543 real FBS-v-FBS regular-season games across 2014–26** in the original capture. Its 47 completed 2026 primary games were excluded from model selection. Historical roles are 2014–15 warmup; 2016–22 season-forward Development scoring (4,824 games); 2023–24 Validation (1,491); and 2025 reused historical holdout (752).

The model uses **35 features** from earlier team scoring, yards, turnovers, Elo, rest and schedule support. A small Ridge/HGB comparison selected Ridge alpha100. Injuries, expected starting QB and player-level talent are not supplied. The primary model does not silently extend to FBS–non-FBS or bowls/playoffs.

| Cohort / model | Games | Margin MAE | Total MAE | Winner log loss | Binary Brier | Accuracy |
|---|---:|---:|---:|---:|---:|---:|
| 2023–24 league | 1,491 | 15.823 | 13.783 | .6785 | .2427 | 58.6% |
| 2023–24 Ridge100 | 1,491 | **13.272** | **12.913** | **.5601** | **.1898** | **71.2%** |
| 2023–24 HGB | 1,491 | 13.401 | 13.045 | .5627 | .1911 | 70.5% |
| 2025 league | 752 | 16.136 | 13.467 | .6759 | .2414 | 59.3% |
| 2025 Ridge100 | 752 | 13.032 | **12.531** | **.5418** | **.1827** | **71.9%** |
| 2025 HGB | 752 | **13.027** | 12.630 | .5452 | .1841 | 71.4% |

The original 2,695-game paired-residual report gave energy 10.372, total CRPS 9.165 and margin CRPS 9.497; central 80% coverage was 82.2% for both total and margin. A later study found that “earlier kickoff” did not always certify donor completion. Its corrected comparison uses strictly prior-season residuals, leaving original outputs preserved. Do not present the legacy distribution numbers as fully certified historical availability.

The later cluster/gap study retained the global baseline. On 2025, energy was **9.9980 baseline**, **10.0057 cluster** and **9.9960 gap**. Cluster benefit was not stable; the small gap benefit was uncertain and failed the Development gate. No same-season gaps longer than 21 days existed in the 2023–25 assessment, so the experiment could not establish a general extended-hiatus benefit. An earlier provisional gap-advancement statement is superseded by this closeout.

CFBD current-season credential access is configured; no secret belongs in a report. The current capture supplies authentic **Syracuse at Pittsburgh**, September 17 23:30 UTC / 19:30 EDT, game **401858225**. Expected points are **20.51–32.07**; total **52.58**. Pitt probabilities differ by channel: calibrated Ridge **.7478**, Elo **.6693**, joint simulation **.7692**. These are separately identified outputs, not interchangeable labels. Both teams had two eligible prior current-season games with required score/yard/turnover inputs. No cluster or gap challenger was promoted into it.

## 8. Publication, Show Preview and operational readiness

### Final-pregame timing

A real design mismatch existed between MLB's former last research-publication allowance and AISP's earlier decision deadline. The reconciled contract is:

| Relative to canonical start | Purpose |
|---|---|
| T−60 minutes | Input/readiness checkpoint |
| T−45 | Operational delivery target allowing normal import/evaluation latency |
| T−30 | Consumer FINAL_PREGAME window opens |
| T−15 | Consumer decision deadline |
| T−5 | Separate last pregame research-publication allowance; not a wagering deadline |

Import/evaluation cadence is five minutes; owner receipts and observed execution duration support the lead time. UTC and America/New_York conversion, including dates after UTC midnight, are retained. A timely old creation is valid if exact unchanged current inputs are evidenced by the owner reuse receipt. A new timestamp without changed inputs is not a feature refresh.

The September 14 delivery audit found **9/10 V18 games imported before the consumer window**. ATL–CHC was blocked by stale Cubs pitching-roster evidence over 30 hours old. That is an actual input-orchestration failure; the theoretical T−5 allowance did not prove another game was missed. The proposed repair separates roster refresh from an unrelated team-stat timeout and retains the existing owner. This report has not revalidated consumer deployment of that change.

The latest inspected natural MLB tick started **September 16 02:59:10.433806 UTC / September 15 22:59:10 EDT**. It identifies `windows-task-scheduler`, deployment **77d39e1ae08e05be82e19bdb0bab21999fba1d3b**, and status **NOT_DUE_NO_PROVIDER_OR_MODEL_ACTIVITY**. It made zero provider requests and zero AISP writes. This confirms an operating owner at that time; it does not prove every game's inputs were sufficient. Earlier STOP/reinstallation blockers are superseded; do not repeat recovery. NFL archive restoration is also complete.

### SHOW_PREVIEW

The separate contract is **AISP_SHOW_PREVIEW_FORECAST_V1**, horizon exactly **SHOW_PREVIEW**, editorial/research-only. A derived preview binds its original source, actual availability, reused population, limitations and new publication clocks; it does not relabel a final forecast or grant final-pregame authority.

- **NFL:** 16 explicit Week 2 previews published and validated.
- **CFB:** one explicit current preview published and validated.
- **NBA:** adapter tested; no fabricated next-day slate or restamped BOS–DET demonstration.
- **MLB:** separate team model implemented and assessed; no genuine current preview because the complete history export is missing.

The intended daily schedule is **15:00 ET identify slate; 15:15 resolve inputs/produce; by 16:00 publish; 16:30 AISP may freeze; 17:00 recording**. America/New_York rules handle daylight saving. **Automatic preview production remains staged/inactive.** No second Windows scheduler is needed. Actual Show Board import/activation is a consumer responsibility and not established by 17 producer-valid packages.

## 9. Reading the metrics correctly

| Metric | Meaning / direction | Qualification |
|---|---|---|
| Log loss | Penalizes confident wrong probabilities; lower is better | Game winner and eight-class PA values are different prediction problems |
| Binary Brier | Mean `(pHome−homeWin)^2`, range 0–1; lower is better | Used for no-tie binary comparisons, not automatically for NFL |
| Summed multiclass Brier | Sum across outcome classes of squared probability errors | NFL includes HOME/AWAY/TIE; MLB PA has eight classes; values are not directly comparable to binary Brier |
| Accuracy / AUC | Pick correctness / ranking discrimination | Neither assesses all probability calibration or economic value |
| MAE | Average absolute error in runs or points | Team, margin and total are separate quantities |
| CRPS | Proper score for a one-dimensional distribution | Lower is better; requires retained distributions |
| Joint energy | Proper score for paired home/away distributions | Lower is better; compare matched methods on the same games/scoring convention |
| Interval coverage and width | How often outcomes fall in forecast ranges, and how broad they are | High coverage obtained by enormous intervals is not automatically better |
| Reliability/calibration | Whether events occur at predicted frequencies | A small selected set of misses cannot establish general miscalibration |
| Paired uncertainty | Change estimated across games/date or week blocks | 10,000 simulated draws are not 10,000 independent observed games |

Monte Carlo error measures sampling precision conditional on the model and inputs. It does not bound model error, missing-personnel error or provider revisions. Profit additionally depends on actual available prices, timing, stake policy, selection and settlement; lower predicted scores or correct picks alone do not prove better betting decisions.

## 10. Exact handoff references and next dependency

Use the source index accompanying this document for physical hashes and full paths to all supporting reports. Important exchange anchors are:

| Purpose | Exact location / identity | What it means |
|---|---|---|
| Preview discovery | `C:\Users\james\asp-model-exchange\show-preview-forecasts-v1`; retained discovery SHA `146fd0c48a0dab68fbd7acb279a417c48d989a289034925d58dd86aa69bdee59` | 17 existing NFL/CFB packages; no new MLB forecast |
| Latest MLB preview advisory | `show-preview-forecasts-v1\handoffs\sha256\b22f0ba1d54c114269fa15e339972dba4ee3c516041a89d35d90fbb0ef31146d` under exchange | Blocked-input status and rejected shrinkage assessment, not importable forecast |
| NBA joint comparison | `nba-gen1-research-v1\joint-comparison-v1\packages\sha256\00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d\index.json` under exchange | Early BOS–DET baseline/close-score research pair |
| MLB prospective formal assessment | `outputs/mlb-prospective-closeout-and-explanations-v1/formal-revision1/RESULTS.md` | Two games, three interventions; shared revision-1 finals |
| NFL exact import acknowledgement | `outputs/nfl-week2-successor-automation-v1/consumer-observation/sha256/153b12814aa74e0f02680eb96e7110a5e1b4d3ae4ac8eec4a766bbd19cc32a28/consumer-observation.json` | 16 exact forecasts and 16 exact supplements imported at the recorded snapshot |

The latest MLB advisory manifest/address is `b22f0ba1d54c114269fa15e339972dba4ee3c516041a89d35d90fbb0ef31146d`. Its `CLAUDE_HANDOFF.md` physical SHA is `e641f8f168ccf4a8116d56ee65d80d11f7f2f9d0f9a731380a9b834ffa398c3b`. The bound assessment SHA is `7746c0467a429a9763454751c7839d8bf3bff61adf7dc267a58bfa1bf377b`.

**Immediate next dependency:** obtain the complete admitted MLB preview history-owner export described above, then use the existing fail-closed producer and validator for a deadline-valid preview. Do not substitute partial histories, invent starters or weaken the deadline. No new acquisition is authorized merely by copying this handoff.

After that operational dependency, the queued NFL opponent-adjusted EPA experiment remains a separate work package. NBA close-score, CFB cluster/gap, MLB archetype, score-limit and QB-residual studies already have decisions; do not restart them as though no comparison exists. Future assessment should use genuine newly frozen evidence rather than repeatedly retuning on the inspected cohorts.

## 11. Starting instructions for the new project-management chat

Work in `C:\Users\james\asp-model-studio`. At this report's repository snapshot:

- Branch: `codex/mlb-starter-duration-source-intake-v1`.
- HEAD: `0c786297534c1ffc9892fbcd199d7d7af5ec8bae` — latest retained MLB preview input/shrinkage evidence.
- Implementation predecessor: `d75d75ebcb913280531ab3025858687dfadf6729`.
- Earlier preview framework: `de992b1d`, `92c526a3`; team-preview implementation: `21a911557abc9837ed34f47627e7b060da56bebb`.
- Current deployed MLB owner is the separately recorded `77d39e1ae08e05be82e19bdb0bab21999fba1d3b`, not necessarily checkout HEAD.

Read applicable instructions and check newer compatible commits, current immutable pointers and dirty files before acting. Independent owners can advance artifact locators. Preserve existing work; no reset, merge or push is implied. The eight pre-existing tracked modifications are recorded in `REPORT_RECEIPT.json`; there is also unrelated untracked work.

Studio owns research/production/artifacts; Claude owns AISP ingestion, market collection, Show Board/UI, final policy, positions and settlement. Do not edit AISP or its database from a Model Studio assignment. Do not activate preview scheduling, alter wagering authority, open sealed evidence or begin a queued experiment without an applicable assignment.

This handoff was assembled from completed reports and operational receipts. No model was fitted or rerun, no forecast regenerated, no outcome-bearing dataset reopened for assessment, no provider requested, and no AISP record changed. Current profitability, current UI state and every live consumer setting were not re-audited. Source snapshot dates are preserved rather than advertised as uniformly current.


## Appendix: source catalog

Physical checksums and byte counts are in SOURCE_INDEX.json. These links point to retained local evidence; later reports may explicitly supersede earlier conclusions.

- [feature_audit](C:/Users/james/asp-model-studio/outputs/multisport-feature-engineering-audit-v1/REPORT.md): `79a95208247d85df9256e8bb2abda211e5e28fbd988647f1f18334484d220c82` (11,783 bytes)
- [mlb_pa](C:/Users/james/asp-model-studio/outputs/mlb-v18-empirical-diagnosis-v1/REPORT.md): `809439705a6cc25227ee68dc0ba51f427af81eb75dcec3131d5182ded890b11d` (18,084 bytes)
- [mlb_doubles](C:/Users/james/asp-model-studio/outputs/mlb-v18-doubles-followup-v1/decision.md): `4598d70504a92ff489120d2ccbedb43a36d048fc850233b6746c0489499442e3` (4,621 bytes)
- [mlb_misses](C:/Users/james/asp-model-studio/outputs/mlb-v18-september12-miss-analysis-v1/decision-note.md): `82b33eba087320863bf7d1c153a24250ae97a1687d2db728a13bd05b0c8e9c7c` (13,846 bytes)
- [mlb_counters](C:/Users/james/asp-model-studio/outputs/mlb-v18-population-diagnostics-v1/decision-note.md): `ada1901c29aaa3790a9ac9f80f269d48fadfce7b4ba0ab00484fe39089439950` (7,458 bytes)
- [mlb_calibration](C:/Users/james/asp-model-studio/outputs/mlb-v18-ensemble-release-candidate-v1/DECISION.md): `8364b6a66f390339f38dc430bf347d645d6b80f13fcf3ed80b2b46d5ab302dfb` (2,447 bytes)
- [mlb_rf](C:/Users/james/asp-model-studio/outputs/mlb-v18-rf-operationalization-v1/rf-artifact-inventory.json): `a573b1466e62e960f7d1afc0fa0ae9042aaef27d459af60542210abeb9af06d1` (9,709 bytes)
- [mlb_transitions](C:/Users/james/asp-model-studio/outputs/mlb-v18-transition-shrinkage-v1/notes/sha256/c3ac6638a154c8b2a3b17a242c923a46b31adadf6979ba9c192feffcc6374b1b/DECISION.md): `c3ac6638a154c8b2a3b17a242c923a46b31adadf6979ba9c192feffcc6374b1b` (3,399 bytes)
- [mlb_archetype](C:/Users/james/asp-model-studio/outputs/mlb-pitcher-archetype-survival-v1/DECISION.md): `4c93293edf13bc4cbef3834c49e4a692db1592bdc3028b3143caa7eecbec47bd` (10,680 bytes)
- [mlb_filter](C:/Users/james/asp-model-studio/outputs/mlb-v18-score-limited-v1/decision-note.md): `8fc37bc5b8d63a250a0d89e0f13abf5ac77d7d436f5efacf78cf4199df52fb9a` (5,462 bytes)
- [mlb_formal](C:/Users/james/asp-model-studio/outputs/mlb-prospective-closeout-and-explanations-v1/formal-revision1/RESULTS.md): `f4f3a7c67803b6395e4b2efd0dfe95c409a92ff135900c06b794523a60f25337` (3,687 bytes)
- [mlb_totals](C:/Users/james/asp-model-studio/outputs/mlb-v18-totals-distribution-v1/completion-note.md): `651c31fd0b6606ce3bb0de56dc5ce241df27eb54c02d22057d5d2eba960c0811` (2,370 bytes)
- [mlb_preview](C:/Users/james/asp-model-studio/outputs/mlb-show-preview-feasibility-v1/REPORT.md): `6868cbc806679a8dbd82ce00273beb4be7cecbe8872f85151788ab2d476e6b81` (4,698 bytes)
- [mlb_shrinkage](C:/Users/james/asp-model-studio/outputs/mlb-matchup-starter-shrinkage-v1/REPORT.md): `89eea8ff46c16dfe4888719c5cb7178f61795f079f530bb5cfc96071b604cf3d` (11,039 bytes)
- [nfl_update](C:/Users/james/asp-model-studio/outputs/nfl-m1-current-season-update-v1/DECISION.md): `f1e63aa2042ecc6ea2cd258c51eaea9fcf5218e9e356e2d1a637a876889902cf` (13,155 bytes)
- [nfl_qb](C:/Users/james/asp-model-studio/outputs/nfl-m1-qb-context-residual-v1/RESULTS.md): `0db433e18416a4f3ab16e114adf5059997cc2844f11e31000b468c15b7066a24` (6,280 bytes)
- [nfl_play](C:/Users/james/asp-model-studio/outputs/nfl-play-level-engine-v1/MODEL_CARD.md): `fba425e609fa542b7c62bf71b843142a402fad08e0d41c7080448df0f48fe38d` (11,445 bytes)
- [nfl_drive](C:/Users/james/asp-model-studio/outputs/nfl-drive-competing-risks-v1/REPORT.md): `437d228c4caea1dc4493995c48bcc2805015a3df543c310d160eca926d29839f` (8,181 bytes)
- [nfl_import](C:/Users/james/asp-model-studio/outputs/nfl-week2-successor-automation-v1/consumer-observation/sha256/153b12814aa74e0f02680eb96e7110a5e1b4d3ae4ac8eec4a766bbd19cc32a28/consumer-observation.json): `153b12814aa74e0f02680eb96e7110a5e1b4d3ae4ac8eec4a766bbd19cc32a28` (12,215 bytes)
- [nfl_eligibility](C:/Users/james/asp-model-studio/outputs/nfl-week2-paper-eligibility-20260915-v1/batch/sha256/82d2a87fd4a24deb9c1a7b26dfc4f11347e9a3daf9f1a39d9ea4ac5aacc890b1/CLAUDE_HANDOFF.md): `7034da90a35cca6e1d2ecc6acce61ea9e3e55ea99d6ec00d8d1af1ae3b46154c` (6,592 bytes)
- [nba_recent](C:/Users/james/asp-model-studio/outputs/nba-gen1-recent-v1/REPORT.md): `734527866d02bc05b8daa3ef741be59b884d4f8d8591381ae0a0c48b920fb320` (14,807 bytes)
- [nba_rest](C:/Users/james/asp-model-studio/outputs/nba-gen1-long-gap-v1/REPORT.md): `a80f81ab7d0c456571a1ee8067b6972c2097a085e3dc0488d27c46f90045e393` (9,848 bytes)
- [nba_joint](C:/Users/james/asp-model-studio/outputs/nba-gen1-joint-residual-v1/REPORT.md): `09afa9adf35066e798aa46269d67adf2ffb818b1ef699964bf4cd458c5f6043a` (11,093 bytes)
- [nba_close](C:/Users/james/asp-model-studio/outputs/nba-gen1-close-score-v1/completed/REPORT.md): `6de4f458d72185d83230a297735f41babaa5d7122cda5a4709e9c613d2f5b0e2` (6,033 bytes)
- [nba_future](C:/Users/james/asp-model-studio/outputs/nba-gen1-joint-prospective-v1/final/package/sha256/00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d/CLAUDE_HANDOFF.md): `959163f2d77f981fdf41839fbe5a3b7a7b7268e8ce8bbe62e3866914f9a830cd` (2,641 bytes)
- [cfb_source](C:/Users/james/asp-model-studio/outputs/cfb-gen1-v1/SOURCE_REVIEW.md): `7b18e47ee3b7e0b22b2af33a1cfa9bced3d1f9d0aec284b3684a2de886676c52` (1,669 bytes)
- [cfb_initial](C:/Users/james/asp-model-studio/outputs/cfb-gen1-v1/REPORT.md): `84b1ca8dfd05b9b5ae40117330bd7b1061aff5b832ccc0c9d7e010b14a26436c` (3,475 bytes)
- [cfb_current](C:/Users/james/asp-model-studio/outputs/cfb-gen1-current-v1/REPORT.md): `0ad433c039677e966eb9285b2e149f570341c96309a7ec47a2acf75dff5be3a7` (1,552 bytes)
- [cfb_extensions](C:/Users/james/asp-model-studio/outputs/cfb-archetype-extended-gap-v1/REPORT.md): `e6fa58fe908809c83a9ad3e3266b9b6f135d82cbf32665045c4bcf40523ca0d1` (9,193 bytes)
- [preview](C:/Users/james/asp-model-studio/outputs/multisport-show-preview-producer-v1/REPORT.md): `215941375dcc2361646bfd2d5c12befbd70cb13eb36469a4087cc90db8b01c25` (4,975 bytes)
- [preview_handoff](C:/Users/james/asp-model-studio/outputs/multisport-show-preview-producer-v1/CLAUDE_HANDOFF.md): `a2ccecf82284195e6fc08720042775c0e4d3b80e92dcf7a8c177a5ee46797f33` (7,552 bytes)
- [timing](C:/Users/james/asp-model-studio/outputs/mlb-v18-delivery-timing-audit-v1/sha256/ced67bf4b4a0a4447a67b34f56934729452848f8efc4c1730f7c555fd7b7f972/CLAUDE_HANDOFF.md): `18ef32b112c05bcd1354f5520d064b85c0e276d1215c6051db7c58809f515ba6` (3,394 bytes)
- [roster](C:/Users/james/asp-model-studio/outputs/mlb-roster-freshness-repair-v1/sha256/abe9ee20b75dc992b5926063b7ac631820c3cb6748a7c0f5c8b84387549d7522/CLAUDE_HANDOFF.md): `61d46e1bf745cfb18c45d52e019e694b20d91589008193fda33f929656cf7eba` (2,359 bytes)
- [natural_tick](C:/Users/james/asp-model-studio/outputs/mlb-v18-unattended-v1/objects/sha256/498926e2c02df8791669595896dc6787e6b19be78400369ba8182f4936e3fed7/tick.json): `498926e2c02df8791669595896dc6787e6b19be78400369ba8182f4936e3fed7` (2,015 bytes)
- [governance](C:/Users/james/asp-model-studio/AGENTS.md): `c19eb2bc21bb38b003087d6a43b91b90e19fe1d353a2dc6bc7be71e57b6b75a7` (1,276 bytes)
