# Market Intelligence and RFF Research Laboratory V1

Date: 2026-09-10. Scope: MLB, existing local evidence only. Status: research, not promoted; no wagering authority or AISP model execution.

## 1. Scientific conclusion

The laboratory now has a reproducible point-in-time market tape, explicit coverage ledger, fixed-weight RFF contract and bounded chronological model comparison. It does **not** yet establish an actionable advantage beyond sportsbook consensus. The composite nonlinear challenger has better descriptive outcome scores on 40 held-forward games, while the interpretable alternatives and movement predictor do not improve on their respective benchmarks. A matched nonlinear market-only control explains most of the composite gain against raw consensus; the remaining modest difference is exploratory and cannot establish individual RFF components as useful.

Only two ISO weeks appear in the outcome evaluation. Formal temporal uncertainty requirements fail. Public tickets, handle, coherent sportsbook-relief inputs, validated role-uncertainty assessments and social narrative history are missing; all RFF entries are provisional. No component is evidence of fixing or bookmaker intent. MLB V18, NFL M1, official policies, thresholds and positions remain unchanged.

## 2. Immutable evidence and provenance

The [read-only source manifest](C:/Users/james/asp-model-studio/outputs/market-intelligence-rff-v1/source/sha256/df6ded6fa0356ff12c6e1d33dcb816cff12660c4f627b733a9336e04caefaa27/manifest.json) has SHA-256 `df6ded6fa0356ff12c6e1d33dcb816cff12660c4f627b733a9336e04caefaa27`. It was captured at `2026-09-10T15:34:35.643045+00:00` using an AISP repeatable-read, read-only transaction. Sealed 2026-08-14–27 dates were excluded before payload selection, checking UTC and Eastern dates.

Within 196 market-relevant events, the export contains:

| Evidence | Stored records / qualification |
| --- | --- |
| Sportsbook quotes | 223,546: 218,542 THE_ODDS_API and 5,004 SPORTSGAMEODDS records |
| Gen1 forecasts | 430 total; 181 published before scheduled start; 249 DRAFT excluded from published-forecast comparison |
| Prediction-market snapshots | 183,015; all semantically unreviewed, none eligible for numerical sportsbook disagreement |
| Schedule / final-state observations | 12,275 / 1,246 |
| Lineup / starter observations | 21,135 / 24,550; not a complete news or role-assessment archive |
| Events with outcome-knowledge timestamp | 170; 26 remain unknown |

The source schema inventory covered 2,626 nonsealed MLB events, but only 196 had scoped market/forecast evidence. These counts must not be conflated. Matching final-state observations establish outcome availability; no historical outcome time is invented from a canonical final score. Source insertion time is retained to expose backfill. Provider provenance marked LIVE does not establish prospective availability.

The Gen1 benchmark is AISP's `asp_mlb_ensemble` Gate 2 development track, not Studio V18. Its current recorded version is `2.0.0-gate2-08cca634c81b`; each research row retains its actual model/version and forecast identity. The producer combines deterministic rating, Poisson scoring and untrained development-challenger components. This comparison neither retrains nor upgrades that model.

## 3. Tape construction and point-in-time controls

The tape preserves source/provider, bookmaker, event/side identities, market/period/line, observed/available/created timestamps, prices and probabilities. American-to-decimal conversion is deterministic. For a coherent two-sided pair, raw implied probabilities are `q_A=1/d_A`, `q_B=1/d_B`; bookmaker no-vig probability is `q_A/(q_A+q_B)`. Bookmaker identity and source identity remain distinct.

Paired prices must share compatible event, market, period, threshold, source and observation semantics. An unrelated opposite-side quote is not a legitimate pair. The result contains 111,773 paired snapshots across 153 events. Moneyline, run line/spread and totals remain separate; the fitted primary analysis uses only full-game moneyline.

Opening, 24-hour, 6-hour, 2-hour, 60-, 30-, 15- and 5-minute, and last-valid-pregame checkpoints are reconstructed only from information already available. Operational eligibility requires `max(observed_at, available_as_of, created_at) <= checkpoint`, with checkpoint before the conservative known start. Schedule observations and both team identities must already be known. Missing or stale checkpoints remain explicit rather than being forward-filled from later quotes. Quote age is limited to 60 minutes in this version.

The tape records 5,299 checkpoint rows: 2,918 supported, 1,501 stale-only and 880 without a prior pair. Supported status alone is not model eligibility; the research comparison additionally requires at least two books and target-specific evidence. The 24-hour checkpoint has zero usable coverage. Of source quotes, 19,904 arrived operationally after scheduled start and cannot populate earlier checkpoints.

Consensus, best price, range, dispersion, movement, velocity, acceleration and synchronization retain their source breadth and availability. Acceleration uses matched same-book changes rather than silently changing panel composition. Primary games have nine supported bookmaker identities; 18 source-qualified IDs across two feeds are **not 18 independent bookmaker brands**.

Actual first-pitch timestamps are absent. “Closing” therefore means the last locally recorded supported consensus before scheduled start, with at least two books and eligible quote age—not a verified official close. All closing-line conclusions inherit that limitation.

## 4. Separate research targets and validation

Three targets are distinguished: subsequent consensus movement; early-price/last-valid-pregame comparison; and home-win outcome prediction conditional on sportsbook consensus. The primary checkpoint is 60 minutes before start, one observation per event. Alternative checkpoints are descriptive views, not additional independent training cases or repeated selection opportunities.

There are 85 eligible primary events and 80 settled events. Settled coverage spans August 28–September 9 across ten Eastern dates and three ISO weeks. Three expanding chronological folds produce 40 outcome OOF predictions over August 31–September 9: seven dates, only two ISO weeks. Games remain atomic. Training labels must be available before the next validation window; feature imputation/scaling is fitted only in training data, with missingness indicators. Unsupported components are not observed zeros.

Target-specific fitting requires at least 60 eligible events, 30 initial training events and three folds with at least ten validation events each. The model-plus-AISP-disagreement-only fit fails supported chronological coverage; it is reported as insufficient rather than filling nonexistent forecasts. Outcome residual models use `logit(p_market)+f(X)`, not an invalid binary classification of `y-p_market`.

## 5. Outcome results and attribution control

The following completed comparisons share the same 40 OOF games. Lower log loss and Brier are better. These are uncalibrated evaluation outputs; no posthoc calibrator was fitted.

| Outcome system | Log loss | Brier | Ten-bin ECE | Mean probability bias |
| --- | ---: | ---: | ---: | ---: |
| Frozen sportsbook consensus | 0.701865 | 0.254497 | 0.135141 | -0.055610 |
| Market + movement/dispersion, regularized offset | 0.705911 | 0.257925 | 0.190957 | -0.019785 |
| Market + supported RFF, regularized offset | 0.729426 | 0.265013 | 0.141822 | -0.048675 |
| Combined interpretable logistic offset | 0.711903 | 0.258360 | 0.130143 | -0.035072 |
| Composite HGB research challenger | 0.650730 | 0.228196 | 0.095010 | -0.076955 |
| Same-architecture market-only HGB control | 0.661061 | 0.234681 | 0.091358 | -0.053367 |

Composite HGB improves descriptive log loss by 0.051135 and Brier by 0.026301 against raw consensus. However, mean home-win probability bias worsens despite lower ECE. With 40 games, sparse reliability bins cannot establish calibration. The Gen1-only OOF benchmark is 0.705256 log loss / 0.256066 Brier on **34**, not 40, available games; market on those same 34 gives 0.710679 / 0.258893. This is a small descriptive matched-population advantage, not a comparison to the full table. On the broader 69-game primary population with both forecasts, Gen1's descriptive log loss is 0.683660 versus market 0.685130; neither difference is a promotion result.

The additional HGB control uses market logit alone, identical hyperparameters and the exact same 40-game folds. It was added **after observing the composite gain**, as an exploratory attribution check, not disguised as an original predeclared confirmatory comparison. No search followed it. Its 0.661061 log loss explains most of the composite's improvement over raw consensus. Against this control, the composite improves log loss by only 0.010331 and Brier by 0.006485; control ECE and mean probability bias are better. This is a modest exploratory composite benefit, not confirmed incremental information, individual-component attribution or causality.

The [final completed comparison](C:/Users/james/asp-model-studio/outputs/market-intelligence-rff-v1/completed/sha256/c0f759a2854e8c620b7936e49c7db930f652b2371f8dba01a904317a1db4402b/model-comparison.json), SHA-256 `98284434ab4963df24bf7f97a7a8eed68fb17ead1cddaf88d8b97a4e47af593d`, preserves per-fold metrics, event IDs, exclusions, calibration bins and references to complete reloadable artifacts. It does not embed every OOF prediction array; saved models and input checkpoints reconstruct those predictions.

## 6. Movement, disagreement survival and CLV

The next-movement target has 67 eligible events and 34 OOF predictions. Regularized regression achieves MAE 0.00110844 and RMSE 0.00176469, worse than the same-event **training-mean** baseline's 0.000937144 and 0.00154176. The separate zero-change baseline gives MAE 0.000916549 and RMSE 0.00156643; six targets are exactly zero. The ridge model trails both. There is no observed improvement in predicting subsequent movement in this bounded comparison.

Disagreement survival means the initial model-minus-market sign remains when measured against last-valid-pregame consensus, holding the original model probability fixed. Only 57 events qualify, below the 60-event fitting gate. The observed 98.25% survival rate is descriptive, heavily imbalanced and potentially consistent with small market movements; it does not justify a fitted classifier or show that the model is correct.

At the primary checkpoint, 66 events have the required last-valid-pregame comparison; mean consensus probability change is -0.000183227 for the canonical home side. Corresponding price-to-closing-fair-probability return proxies average approximately -1.658% home and -1.249% away. These are not realized ROI, an executable strategy, policy-selected returns or certified monetary CLV. No stake, execution, fill, transaction-cost or position process was tested.

## 7. RFF coverage and interpretation

The [component contract](C:/Users/james/asp-model-studio/docs/rff_component_contract_v1.json) fixes ten components at ten points each. Components cover public tickets, public handle, relief proxy, reverse movement, synchronization, dispersion, model disagreement, prediction-market disagreement, availability uncertainty and narrative concentration. Normalizations are explicitly assumption-based V1 research scales, not empirically learned thresholds.

All 775 ledger checkpoints across 152 games are `PROVISIONAL_RFF`. At the 85-game primary checkpoint, 72 have 30% component coverage, 12 have 20%, and one has 10%. Dispersion is computable for 85, synchronization for 83 and model disagreement for 73. Computability is not signal occurrence: only two primary examples meet the three-book synchronization threshold. No public handle is available.

Missing components retain their ten-point unresolved range. Primary mean observed lower bound is 5.2266 points; mean upper bound is 76.8737. These are missing-information bounds, not confidence intervals. A low observed contribution with 70–90% unmeasured weight is not low RFF. Coverage measures completeness, not reliability or predictive confidence. Current RFF features largely re-express existing price/forecast signals; they do not establish independent crowd information.

The relief equations `1-h_A*d_A` and `1-h_B*d_B` are implemented only as a declared same-source, coherent-handle proxy contract. No actual liability is calculated. Reverse movement cannot be inferred without independent timestamped public direction. All prediction-market observations fail semantic review, despite exact event identity, so no numeric disagreement is manufactured.

## 8. Uncertainty, verification and execution accounting

Formal comparison requires at least eight nonoverlapping 28-day temporal blocks. The OOF population contains one such block; formal inference is explicitly insufficient. Reporting a narrow game-only interval would obscure shared days, teams and market conditions. No formal superiority, regression, component-utility or wagering-edge claim is made.

Four focused tests passed in 5.31 seconds, covering bounded point-in-time/pairing/target and artifact behavior. Final verification checked 48 file hashes and reloaded 18 estimator artifacts; full-fold reconstruction had maximum difference zero. Checkpoints reconstruct bitwise identically. The earlier cross-context five-row fixture checks for twelve reused estimators separately passed `1e-12` tolerance: nine were bitwise identical and three movement fixtures differed by at most `2.1684e-19`. Those small fixture differences are preserved rather than relabeled as bitwise equality.

The original HGB launch recorded one actual fit start and `PermissionError(13, 'Access is denied', None, 5, None)`, with no completed fold from that failed launch. A separately identified supported-Windows recovery completed three HGB folds, preserving the failed attempt. Through that recovery there were 16 actual starts and 15 completed fits. The subsequent three-fold attribution control brings the final total to **19 actual fit starts and 18 completed fits**: 15 outcome fits including the control, three movement fits and one preserved failed start. Twelve original completed fits were reused. These are actual accounting events, not scheduled slots. No automatic retry loop or expanded algorithm search was used.

## 9. Deliverables, next evidence and authority

The [recovery manifest](C:/Users/james/asp-model-studio/outputs/market-intelligence-rff-v1/recovery/sha256/e2b6160773769cd41b06e040ad3de06f82547e17c4212ecfaae34e79e2557464/manifest.json), SHA-256 `da9fc17d02f257c6e30284e6c98c2db5db9bcd06776daa569a5ed70dc3138616`, links the source, tape, coverage, ledger, preserved predecessor and fitted artifacts. The [final completed manifest](C:/Users/james/asp-model-studio/outputs/market-intelligence-rff-v1/completed/sha256/c0f759a2854e8c620b7936e49c7db930f652b2371f8dba01a904317a1db4402b/manifest.json), SHA-256 `6f431412f809c08ba00661a8bd0b45fd0465d9f48d58619aae3166c93acf727c`, adds the separately preserved market-only attribution control and final comparison.

The [editable information/contract specification](C:/Users/james/asp-model-studio/docs/MARKET_INFORMATION_CONTRACT_FEATURE_SPEC_V1.md) supplies all requested definitions, timestamps, reliability tiers, entities, mechanisms, leakage risks, missing treatment and historical feasibility. It prioritizes official availability/lineup information and attributable reporting. Contract features target usage/opportunity; no “contract-year motivation” effect is assumed. No new information source was called or acquired.

The smallest next evidence improvement is a longer prospective, consistently sampled multi-book checkpoint archive with original source and receipt clocks, known schedule revisions and observable closing coverage. Complete RFF additionally requires a lawful timestamped same-population ticket/handle archive; social or contract acquisition should follow an explicit question, not a narrative. No component is presently established as incrementally useful beyond consensus. The composite outcome result is a hypothesis for independent observation; the movement result is negative in this sample; complete RFF remains unsupported.

AISP action is **no forecast or policy import**: local read-only research review only. Immutable research artifacts confer no execution, promotion, selection or wagering authority. No providers, social APIs, sealed Final OOT, AISP persistence, official thresholds or positions were changed.
