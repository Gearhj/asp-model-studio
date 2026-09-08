# MLB V18 acceptance protocol V2 and Gen 1 exploratory bet-readiness cohort

Status: `V18_PROSPECTIVE_ACCEPTANCE_PROTOCOL_V2_PREDECLARED_AND_EXECUTABLE`

This is an immutable successor to protocol V1 SHA-256 `1d72242432e045a7f921e115c8a7ad00ed11c80a8b8503f512ebaec67a087aaf`. It does not alter V1, the accepted V18 bundle, or any prior receipt. It also records a descriptive Gen 1 readiness cohort obtained through a PostgreSQL read-only transaction. AISP registration remains independent and unblocked.

## 1. Corrected statistical definitions

The planning values `0.0686`, `0.0434`, `0.0307`, `0.0194`, and `0.0137` at 20, 50, 100, 250, and 500 paired games are **approximate two-sided 95% confidence-interval half-widths**. They are `1.96 × assumed standard error`; they are not powered minimum detectable effects.

The calculation retains paired log-loss-difference SD `0.14` and temporal design effect `1.25`. Both remain explicit planning assumptions. No artifact establishes that they were empirically estimated from the prospective endpoint, and V2 does not describe them that way. No power study was performed.

## 2. Noninferiority margin disposition

The `+0.020` paired home-win log-loss margin is retained as `PROPOSED_NOT_APPROVED`. Automatic `ADVANCE_AS_NONINFERIOR` is disabled.

The intended use is a practical tolerance for V18-minus-Gen1 prospective home-win log loss if—and only if—it receives separate scientific approval before prospective results are used for that decision. Existing Development evidence does not approve it:

- the matched V18-minus-V14 PA-level multiclass log-loss difference was `+0.0000312364`, with game-clustered 95% CI `[-0.0002119731, +0.0002814535]`; this is a different PA endpoint;
- the E10-minus-Direct-Gold holdout home-win log-loss difference was `-0.0085072983`, with 95% CI `[-0.0250789203, +0.0075511981]`; it compares different game engines on a different evidence population.

These results support continued shadow monitoring, not a scientifically approved whole-game degradation tolerance. If a formal interval falls below `+0.020` but does not establish superiority, V2 reports `NONINFERIORITY_BOUND_MET_MARGIN_NOT_APPROVED` and retains the model as a diversity challenger.

## 3. Temporal blocks and repeated formal looks

V2 retains the deterministic chronological ISO-week block bootstrap and requires at least **eight distinct ISO-week blocks** for formal inference. Eight is a pragmatic minimum: it prevents a nominal interval generated from only a few repeatedly resampled temporal units from authorizing advancement or regression. It is a minimum support rule, not a claim that adjacent games or weeks are fully independent.

Formal inference occurs only when the input carries an immutable formal-look identity:

| Look | Exact chronological cohort | Allocated alpha | Two-sided interval |
|---|---:|---:|---:|
| 1 | First 250 eligible paired games | 0.025 | 97.5% |
| 2 | First 500 eligible paired games | 0.025 | 97.5% |

The fixed Bonferroni allocation bounds familywise alpha by `0.05` across the two looks. Daily reports and the 20-, 50-, and 100-game checkpoints are descriptive and cannot create extra unadjusted opportunities for superiority, noninferiority, or regression. Formal regression uses the same allocated interval and eight-block minimum. Operational failures remain immediately actionable because they are not statistical performance claims.

Superiority still requires the formal CI upper bound below zero and passing calibration/operational gates. Material regression requires the formal CI lower bound above `+0.020`. Insufficient games, missing look identity, or fewer than eight weeks yields descriptive metrics and `FORMAL_INFERENCE_INSUFFICIENT` or `DESCRIPTIVE_ONLY_NO_FORMAL_LOOK` while research-shadow monitoring continues.

## 4. Bet-readiness research separation

The successor contract separates:

1. exploratory readiness and decision-policy description, authorized now;
2. policy selection, not authorized here;
3. independent policy evaluation on a separately frozen cohort, not started;
4. authority to affect virtual positions, not granted by this cohort.

The 250-game V18 comparison threshold does not block the Gen 1 descriptive analysis. This work does not optimize thresholds, recommend relaxed readiness rules, fit a model, claim wagering edge, or authorize real or virtual wagering behavior.

## 5. Read-only AISP cohort source

At `2026-09-08T00:02:54.260756Z`, the existing AISP database was queried using one PostgreSQL transaction explicitly set to `READ ONLY`. The query joined persisted experiments, decisions, games, forecasts/model versions, decision-time odds, final outcomes, virtual positions, and settlements. It made zero provider calls and modified zero AISP rows, files, services, or schema objects.

The canonical source-export SHA-256 is `08ebee12a738dd1154e76e4c76f58c3f7608b8eb993637d6efe4f1687a8ca2a3`. The cohort records preserve one row per policy decision, so one event may contribute multiple phases and policies.

## 6. Opportunity funnel

| Population | Decisions | Events | Qualified evaluations | Distinct qualified selections | Virtual positions | Settled positions |
|---|---:|---:|---:|---:|---:|---:|
| All | 18,610 | 154 | 731 | 22 | 10 | 9 |
| V1 `AISP_OPPORTUNITY_POLICY_V1` | 7,550 | 154 | 0 | 0 | 0 | 0 |
| V2.1 practical policy | 11,060 | 96 | 731 | 22 | 10 | 9 |

There are 17,879 rejected decision evaluations. Policy phases are 12,169 morning, 263 lineup-confirmed, and 6,178 final-pregame. These are decision rows, not independent events or bets.

The persisted forecasting-model identity is `asp_mlb_ensemble::2.0.0-gate2-08cca634c81b` for 18,206 decisions. Model identity/version is absent for 404 decisions. The two decision-policy and two staking-policy identities remain explicit in every cohort row.

## 7. Coverage and readiness loss

Independent coverage over 18,610 decisions:

- eligible recorded event status: 18,610;
- decision before event start: 18,610;
- legitimate forecast identity and timing: 18,204;
- any contemporaneous-price record: 12,661;
- price fresh within the fixed 15-minute decision-age rule: 10,433;
- final outcome available: 15,649 (`84.09%`);
- lineup and starter readiness metadata recorded: 11,060 each.

Price coverage is 10,433 fresh (`56.06%`), 5,949 missing (`31.97%`), and 2,228 stale (`11.97%`). Missing sportsbook evidence is a material limitation, not zero-valued evidence.

Sequentially applying event status, pregame timing, forecast legitimacy, price presence, price freshness, and outcome availability leaves 8,794 fully describable decisions (`47.25%`). Losses at each step are 0, 0, 406, 5,544, 2,228, and 1,638; sequential losses differ from independent missing counts when defects overlap.

Median decision lead time is `276.22` minutes (IQR `149.59–465.88`), median forecast age at decision is `171.81` minutes (IQR `72.79–329.02`), and median observed quote age is `5.22` minutes (IQR `4.30–5.89`). Two slightly negative forecast-age cases contribute to the 406 failed forecast-legitimacy rows and are not repaired.

## 8. Rejection evidence and answerable questions

Recorded rejection categories are overlapping because one rejected decision may carry several qualification reasons. The largest recorded categories are missing complete two-sided market evidence (11,090 reason occurrences), other recorded policy reasons (7,095), critical inputs incomplete (6,997), starter not confirmed (6,997), lineup missing (6,683), readiness below the policy threshold (6,367), adjusted expected value not positive (3,978), starter evidence inadequate (3,792), adjusted edge below the policy threshold (2,495), stale market quote (1,409), forecast unavailable (612), and extreme disagreement (345). These counts describe the frozen policies; they are not recommendations to change them.

The cohort can answer the opportunity funnel, recorded rejection-reason distribution, timestamp/price coverage, lead-time distributions, outcome coverage, and actual virtual-position inventory. It contains 8,479 rejected decision rows with a fresh contemporaneous price, valid pregame forecast/timing, and final outcome; those rows may support bounded descriptive counterfactual work later, but V2 computes no rejected-bet profit and makes no causal or wagering-edge claim.

Threshold optimization, policy selection, causal policy comparison, recommendations to loosen readiness gates, and wagering-edge claims are not authorized or answerable here.

## 9. Exact remaining data requirements

The read-only export contract is complete, but source evidence remains missing for some rows. A later refresh would need these exact keyed observations—not inferred replacements:

- 2,961 decisions: `eventId` plus immutable final status, scores, and final timestamp;
- 5,949 decisions: `decisionId`, sportsbook, complete two-sided price, and `quoteObservedAt` at the decision;
- 2,228 decisions: a price observed within 15 minutes of the decision rather than the recorded stale quote;
- 406 decisions: `forecastId`, model identity/version, generated timestamp, and cutoff supporting a legitimate pregame ordering;
- 7,550 decisions: lineup and starter readiness as observed at the decision cutoff.

The content-addressed export contract is suitable for Claude if a future AISP-side export is preferred. No missing field may be backfilled from post-event knowledge.

## 10. Immutable artifacts and boundaries

- V2 protocol SHA-256: `291243d7abad7f972e08f7610715bf8e693a267ea37a7b6189256f98aa4a4a7b`.
- Gen 1 descriptive cohort SHA-256: `cd44ef70d6d4a5f3258cfad2cd6222accc5a39431d131184cf7b851ecced5785`.
- Bet-readiness export-contract SHA-256: `3d255a6beed4347451fa76f63ea2c71f75172e7d0d4788eae12659c02c87ef64`.
- Accepted V18 bundle remains `a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27`.

Final OOT remained sealed. No predictive or specialist model was fitted. No provider was called. AISP was read only and was not modified. No policy was selected, optimized, evaluated as causal, or granted authority over virtual positions.
