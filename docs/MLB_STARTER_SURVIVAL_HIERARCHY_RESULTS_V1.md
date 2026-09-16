# MLB starter duration and hierarchical PA research

Verdict: **COMPONENT_ONLY_GAME_VALIDATION_BLOCKED**. The nonlinear pregame duration candidate improves held-out BF forecasts over the simple empirical baseline. Observed-state logistic also improves conditional likelihood. Neither is evidence of improved game forecasting. The real PA hierarchy comparison remains blocked; no replacement V18 or game-level research forecasts were produced.

Branch: `codex/mlb-starter-survival-hierarchical-pa-v1`, isolated from `codex/mlb-v18-conditional-champion-v1` at `9f4e000d073c3f310f5fb4a84d74b16b445d8a4b`. The commit containing this report is the assignment's delivery commit.

## Evidence and estimand

The declaration was frozen before fitting: SHA-256 `51b886ecb20137ea7e8ab0ce1abb8601c3f86df0dfe77dae95d07d8ca01bcc9d`. Only physically separate 2023/2024 Retrosheet/FD1 evidence was used for duration training. These years are a declared historical Development component cohort, not a change to V18's registered split: 2025 remains Development and August 14–27, 2026 Final OOT stayed unread.

The supported boundary is immediately after each completed starter PA, conditional on at least one observed BF. Endpoints are CONTINUE, observed all-cause REMOVAL, and GAME_END. Unknown/incomplete observations are excluded, not converted into hooks. No independent-censoring or IPCW assumption is made; results concern eligible complete cases, not all announced starters. GAME_END is a competing terminal event, not evidence that a manager removed the pitcher. [Competing-risks reference](https://scikit-survival.readthedocs.io/en/latest/user_guide/competing-risks.html).

Raw substitution order, PA identity, pitcher attribution and game totals were reconciled. BF, pitching outs, pitch observations and clock time are separate; 5.2 innings is 17 outs. Mid-PA changes and unsupported terminal non-PA boundaries are accounted for, not coerced into between-PA hooks. Inning-break features retain the just-observed score, not later offensive scoring. History uses strictly earlier eligible dates; same-day ordering is conservatively withheld. These are retrospective completed-game reconstructions, **not historical pregame publication vintages**.

| Population | Starts | PA-boundary rows | Games |
|---|---:|---:|---:|
| Training: March 30–October 1, 2023 | 4,767 | 104,529 | 2,411 |
| Earlier calibration/selection: March 20–June 30, 2024 | 2,486 | 55,481 | 1,255 |
| Held out: July 1–September 30, 2024 | 2,302 | 50,240 | 1,162 |
| Eligible total | 9,555 | 210,250 | 4,828 |

All 9,718 starts across 4,859 source games are accounted for. Exclusions: 53 mid-PA changes; 43 unsupported non-PA terminal boundaries; 28 pitcher-attribution mismatches; 18 suspended/resumed-game starts; 14 raw/FD1 event-identity mismatches; 3 existing eligibility-hold intersections; 2 reverted/unknown-finalization starts; 2 declared-starter/first-pitcher mismatches. **373 starts of ≤9 BF remain eligible.** The original 56-PA hold is unchanged: seven mapped 2023/2024 held PAs intersect three eligible starter stints (80 risk rows removed before histories); the other four are outside eligible starter risk.

There are 9,494 removals and 61 game-end terminal stints overall; 13 game-end stints are in the held-out set. A metadata-only immutable successor changes unsupported default-zero totals to NULL for two already excluded starts. Used study manifest `9d12bb87…` remains the training identity; corrected metadata manifest `dcf22ed4…` is not relabeled as the original input. Risk bytes and every eligible start/history are identical; no refit was needed. The preliminary `007f8780…` and `48053e88…` projections predate the hold filter, are preserved as superseded pre-fit evidence, and were never used for model fitting; `duration-data/cohort-disposition.json` records this boundary. Sources remain local-private research, with Retrosheet attribution and commercial-rights review required; raw redistribution is not allowed.

## Fitted candidates and results

The empirical baseline partially pools BF/previous-usage strata. The primary logistic candidate uses a flexible BF spline and regularization; one conditional variant adds supported observed boundary state. The sole nonlinear configuration is fixed HGB (100 iterations, 15 leaves, learning rate .06, minimum leaf 200, L2=10). There was no grid or family expansion. Flexible exposure is not a universal third-trip discontinuity. [Brill, Deshpande and Wyner](https://arxiv.org/abs/2210.06724).

Pregame fields: home/away pitcher orientation, calendar month, prior eligible start count, prior mean BF, rest, missing-history indicator, and the evolving BF clock. Conditional fields additionally include inning, outs in inning, pitching outs, runs so far, pitching-team score margin and base state. No final totals, actual future pitch counts, injury status, manager identity, pitch restrictions, MiLB features or reliever availability enter the model. Learned preprocessing is training-only; bounded scalar temperature calibration uses the earlier disjoint window. HGB was selected before test scoring, using earlier raw mean start-path NLL: **2.6181 vs logistic 2.7715** (empirical 2.6709).

The pregame evaluation integrates the reduced BF-only process analytically, including both terminal causes, without observed future states. It is not a full-game simulation or a pitching-outs distribution. Expectation is `E[min(BF,101)]`; CRPS is summed through BF100. The unresolved tail is preserved rather than forced into a fictional hook; maximum tail across predictions is 0.00010655. Reported interval widths become lower bounds if a quantile lies in that tail.

| Held-out model (calibrated where fitted) | Mean start-path NLL ↓ | BF NLL ↓ | Expected-BF MAE ↓ | BF CRPS ↓ | 90% interval coverage |
|---|---:|---:|---:|---:|---:|
| Pooled empirical | 2.7631 | 2.7392 | 3.0794 | 2.2533 | 92.66% |
| Pregame logistic | 2.8106 | 2.7678 | 2.8400 | 2.0891 | 93.53% |
| Pregame HGB | **2.6911** | **2.6678** | 2.8541 | **2.0310** | 91.09% |
| Observed-state logistic | **2.5270** | Not pregame | Not pregame | Not pregame | Not estimated |

The nonlinear candidate improves over the empirical baseline both in reduced-state pregame duration and path likelihood. Logistic improves duration error/CRPS but **does not beat empirical likelihood**. The conditional logistic likelihood is useful, but cannot be advertised as a pregame distribution. All raw and calibrated versions remain in the machine-readable results.

Paired descriptive 95% intervals use 500 whole-game cluster bootstrap resamples (1,162 games; 2,302 starts), not independent risk rows. HGB minus empirical: path NLL **−0.0719 [−0.0955, −0.0510]**; BF MAE **−0.2254 [−0.3093, −0.1486]**; BF CRPS **−0.2223 [−0.2817, −0.1662]**. HGB expected-BF bias is −0.1385 versus empirical +0.7078; its 80% coverage is 82.45%. Early-exit (≤9 BF) Brier is .0210 versus .0279; long-start (≥27 BF) Brier .0993 versus .1004. These intervals do not establish transport to another season or wagering value.

Improvement is not confined to one month: empirical→HGB BF MAE is July **3.0071→2.8217** (727 starts), August **3.0079→2.8715** (814), September **3.2249→2.8663** (761). It is more concentrated by prior usage: conventional-history proxy **2.8572→2.7724** (2,119 starts), sparse history **5.4805→4.1286** (155), prior-short-usage proxy **6.6025→1.9797** (28). The last group is small and is not a verified announced-opener label. One 2024 held-out era cannot establish cross-era stability or manager/injury causal effects.

### Comparison with the actual existing hook

The existing mechanism is an unfitted sigmoid of inning, BF, runs while the starter is active, and BF-derived TTO; it forces zero removal probability below 9 BF and caps it at .95. It does not consume pitches, rest or bullpen availability. The exact implementation is referenced in the game inventory.

On the same **50,227 non-game-end opportunities**, existing-hook binary log loss/Brier is **.2077/.0500**, empirical **.1253/.0354**, pregame HGB **.1221/.0350**, and observed-state logistic **.1151/.0329**. Existing mean removal probability is .1105 against observed .0456; HGB predicts .0477. This establishes a better **conditional matched-opportunity diagnostic**, not a head-to-head full pregame BF distribution or game forecast for the existing hook.

The new research-only adapter uses REMOVAL/(CONTINUE+REMOVAL) only for an active next pitching opportunity; the game process owns termination. It never draws a second game end, removes an inactive starter, allows reentry, or extrapolates the fitted boundary to BF0. It is deliberately unwired from frozen V18. The existing reliever contract remains an anonymous staff-template mixture, not a reliever-specific availability, exhaustion or substitution model.

## Why PA and game results are withheld

The lossless B/C implementation is complete: shared binary root, OUT indices 0/6, training-smoothed family frequencies for B, learned conditional heads for C, soft normalized eight-class reconstruction, absent-class treatment and full fitted-object persistence. Dropped third strikes, sacrifice outcomes, fielder's choices and runner outs are still governed by the accepted terminal label and transition engine; class families do not redefine actual outs/advancement. Eight-class NLL decomposes into root plus the applicable conditional-head NLL. No lower binary loss is compared to eight-class loss as evidence of improvement.

**Real A/B/C fits and comparative rows: zero.** The earlier timing defect is real: at least 55 of 70 `BOS202406260` PAs occurred after the July 6 frozen fold-2 training cutoff. The bounded later-cohort inventory found 53,244 candidate PAs/709 games for frozen fold1 and 31,710/423 for fold2, but has not authenticated identical completion-ordered last100/last250/context histories and their recursive dependencies. Date eligibility alone is insufficient. New evidence also resolves a narrower concern: all **61 retained `NYN202309280` PAs match innings1–8; zero voided ninth-inning PAs are present**. Unknown reversion-publication timing must not be described as proof of voided training labels.

The smallest remaining local repair is to rebuild/authenticate the shared affected completion-ordered histories, then freeze a later common cohort before fitting B/C. Only if the frozen fitted information remains inadmissible would separate baseline-refit authority be needed. This assignment did not silently repair B/C alone or substitute a new V18.

Recent August28–September10 accounting covers **189 retained FINAL-at-capture schedule events**: 173 lack a retained V18 pregame forecast/complete input authority; 14 have legacy projected/template evidence not equivalent to current-source inputs; two September10 current-source games (COL–NYY, PIT–CWS) are only potential candidates pending the shared timing/PA/reliever gates. Fifteen have prestart publication evidence; that alone does not certify all inputs. The snapshot cannot enumerate canceled/removed events absent from the retained schedule vintage. Full per-game reasons are in the inventory. **Eligible four-arm games: zero; simulations: zero.** No score, margin/total, winner, first-five, predicted-outs, bullpen-exposure or market-return improvement is claimed. Root/branch and paired game-error charts are explicitly unavailable rather than fabricated.

Observed errors cannot yet identify MiLB prior benefit, optimal pitcher usage, or causal error shares among pitching availability and runner transitions. Reliever availability and full shared PA-history chronology are concrete missing capabilities, not evidence that adding them must improve accuracy.

## Artifacts, verification and decision

- [Machine-readable comparison](../outputs/mlb-starter-survival-hierarchical-pa-v1/report/sha256/1e737ec7ebcd9885b01054f99d8b7b54bc4e7cc08346caba53aa26a6aaa05a6f/comparison.json): SHA-256 `1e737ec7ebcd9885b01054f99d8b7b54bc4e7cc08346caba53aa26a6aaa05a6f`. Contains all raw/calibrated metrics, intervals, monthly/subgroup results, model/preprocessor/calibration/fixture identities and explicit null PA/game comparisons.
- [Original duration execution result](../outputs/mlb-starter-survival-hierarchical-pa-v1/duration-study/objects/sha256/af2e6aca3f83a2e4312b555502b2cf598d0939941f7473c03226318d30f6ff84/duration-results.json): immutable SHA-256 `af2e6aca3f83a2e4312b555502b2cf598d0939941f7473c03226318d30f6ff84`.
- [PA eligibility and implemented mechanics](MLB_PA_HIERARCHY_ELIGIBILITY_AND_IMPLEMENTATION_V1.md); [per-game eligibility](../outputs/mlb-starter-survival-hierarchical-pa-v1/game-eligibility/sha256/fa2d011e2dafeda0170dcda26b64f457d8bf6a157ce2a48ae91e5728273855dd/game-eligibility.json); [metadata-only correction](../outputs/mlb-starter-survival-hierarchical-pa-v1/duration-data/excluded-start-null-metadata-correction.json).
- Charts: [removal calibration](../outputs/mlb-starter-survival-hierarchical-pa-v1/report/sha256/3cc337d63d3ed02f57bd78fed5e1c54bdf9e4c1a85539089afead54db1f58fb8/removal-calibration.png), [BF distributions](../outputs/mlb-starter-survival-hierarchical-pa-v1/report/sha256/05fcf5f7b8afe694c981a72153e74c4b8cfce32cfa509b872849f57248bc8aa6/pregame-bf-distributions.png), [paired duration errors](../outputs/mlb-starter-survival-hierarchical-pa-v1/report/sha256/4f17e3edbef8dbc58e8ba7881fd30d7419d0616015b15108b20a080f88e5aa8a/paired-duration-errors.png).

Actual fits: **3 real hazard estimators started/completed, 1 empirical frequency fit, 3 earlier temperature fits**. Model fitting/calibration/scoring/packaging took 23.26 seconds after cohort validation. Four fitted duration bundles each reload 64 saved rows ×3 probabilities with **zero mismatches**, including a fresh reporting-process reload; learned preprocessing, feature order, endpoints, cutoffs and dependency versions are embedded. B/C mechanics had three explicitly synthetic head fits, 16-row reload fixtures and zero mismatches; no real PA estimator was trained.

Focused checks: three parser/timing/inning/endpoint tests, three duration mass/future-state/scoring tests, four hierarchy/cohort-contract/reload tests, and one adapter legality test passed. Data generation and schedule inventory had exact idempotent reruns; input/manifest/source/model/fixture checksums passed. No broad suite or model retry loop ran. A reporting-only Windows physical-core-discovery warning fell back to logical-core counting; the real study recorded no warnings and completed successfully. Earlier PA pytest attempts failed in temporary-directory setup before fits; existing unrelated work and warnings were preserved.

V18's Model Studio conditional-champion registration is preserved (`mv-mlb-v18-conditional-3e8dcc1c50dcdfd2d748e5e0`). The read-only AISP snapshot does **not** establish that its planned switch occurred: existing V2.1 still references AISP_BASELINE. No activation claim is inferred from a shadow import. Pinned deployment, publisher, schedules, 2% threshold, policies, positions, settlements and authority were unchanged. Provider calls, purchases, AISP writes, Final OOT reads, V18 refits and new forecast publications: **zero**.

Retain frozen V18 and preserve HGB as a **duration research candidate**, not an integrated model winner. The single next action is the bounded shared-history timing repair and frozen matched PA cohort; only then run the already-declared B/C and gated 2×2 game pilot. No promotion or wagering-edge recommendation follows from these component results.
