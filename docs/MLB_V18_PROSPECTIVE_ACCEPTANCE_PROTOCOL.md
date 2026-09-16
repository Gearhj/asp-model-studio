# MLB V18 Prospective Acceptance Protocol

Verdict: `V18_PROSPECTIVE_ACCEPTANCE_PROTOCOL_PREDECLARED_AND_EXECUTABLE`

This protocol was frozen before AISP accumulated a prospective V18 result history. It references accepted bundle `mlb-v18-whole-game-a6e7e99122f1b60701a4728b`, SHA-256 `a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27`.

The protocol does not modify that bundle, fit a predictive model, access Final OOT, register anything in AISP, or authorize wagering.

## 1. Acceptance hierarchy

### Stage A — Operational research-shadow acceptance

Stage A asks whether an individual forecast is legitimate and whether the shadow system is functioning. Every forecast fails closed unless it supplies the exact bundle and feature-contract identities, a forecast timestamp before the scheduled start, an evidence cutoff no later than forecast time, timestamped input receipts, recognized lineup and starter states, freshness within the predeclared limits, exactly 246 raw and 273 treated inputs, normalized PA probabilities, at least 5,000 paths, internally consistent Monte Carlo uncertainty, complete termination, zero illegal states, deterministic replay, one persistence receipt, no wagering authority, and no Gen 1 mutation.

Projected lineups must be no more than 48 hours old and confirmed lineups no more than 12 hours old. Projected, probable and confirmed starter observations must be no more than 72, 36 and 12 hours old, respectively. Input observation time must not follow receipt time, and receipt time must not follow forecast time.

Any bundle/checksum mismatch, duplicate identity, illegal state, nontermination, wagering authority or Gen 1 mutation produces `OPERATIONAL_FAILURE`. Once 20 eligible games exist, coverage below 95%, missing/failed forecasts above 5%, or stale exposure above 5% also produces operational failure. Invalid forecasts are excluded rather than repaired or reconstructed.

### Stage B — Preliminary scientific monitoring

Stage B begins descriptive monitoring without superiority language. It reports V18 home-win log loss, Brier score, predicted and actual win rates, run MAEs, total-run ranked probability score when a valid PMF is persisted, one-run and extra-inning rates, coverage, failures, input freshness, lineup confirmation and Monte Carlo uncertainty.

Calibration intercept and slope are not displayed as governance evidence until 250 settled games and at least 30 observations from each binary outcome class exist. Broad reliability bands are `[0,0.4)`, `[0.4,0.5)`, `[0.5,0.6)` and `[0.6,1]`; a band needs at least 30 games.

### Stage C — Paired challenger comparison

The comparison cohort contains only games with legitimate, non-reconstructed V18 and Gen 1 pregame forecasts for the same immutable game identity and one final immutable settlement. Unmatched cohorts are never compared.

The primary endpoint is:

`mean(home-win log loss V18 − home-win log loss Gen1)`

Negative values favor V18. Secondary metrics are paired Brier difference, calibration, run errors where both forecast contracts support them, distributional accuracy where comparable, coverage and operational reliability. Accuracy or winning percentage is not a primary criterion.

The confidence interval is a deterministic 5,000-resample ISO-week chronological block bootstrap with seed `20260907`. Week-level resampling preserves short-range temporal dependence. Daily looks remain descriptive and cannot change the comparative state.

### Stage D — Market-relative monitoring

Sportsbook observations are evaluated separately at `FORECAST_TIME`, `DECISION_TIME` and `CLOSING`. Quotes require timestamped prices and no-vig home probabilities. Maximum quote ages are 30, 15 and 15 minutes for those phases. The evaluator reports model-minus-market probability, paired model and market log loss, market Brier/calibration gap, coverage, quote age/lead time and cross-book dispersion.

When fresh decision and closing quotes coexist, closing-line value is the probability movement from decision to closing toward the side favored by the frozen V18 forecast. This is observational, not a wager return.

Kalshi and Polymarket are counted separately as observational markets. They are never treated as sportsbook closing lines or model forecasts. Missing legitimate sportsbook evidence is `NOT_EVALUABLE`, not zero and not an operational failure.

### Stage E — Wager-policy eligibility

Market comparison, model performance and wagering performance remain separate. Eligibility for a later bet-readiness study requires at least 250 paired settled games, 95% operational coverage, passing calibration, 80% fresh closing-sportsbook coverage, paired uncertainty estimates, immutable settlements, and two different immutable predeclared cohort identities: policy development and untouched policy evaluation.

Eligibility does not declare model superiority and grants no wagering authority.

## 2. Evidence states and precedence

1. `NOT_STARTED`: no records exist.
2. `OPERATIONAL_FAILURE`: a critical integrity gate fails, or aggregate coverage/freshness gates fail after 20 eligible attempts.
3. `INSUFFICIENT_EVIDENCE`: fewer than 20 paired settled games.
4. `CONTINUE_RESEARCH_SHADOW`: operational acceptance is met but fewer than 100 pairs exist, or the 100-game preliminary checkpoint remains unresolved.
5. `MATERIAL_REGRESSION`: at 100 or more pairs, the lower confidence limit for V18 − Gen 1 log loss exceeds `+0.020`; at 250 or more, a gating calibration failure also produces this state.
6. `RETAIN_AS_DIVERSITY_CHALLENGER`: at 250 or more pairs, operations/calibration pass but the interval is too wide or neither noninferiority nor material regression is proven. This is not equivalence.
7. `ADVANCE_AS_NONINFERIOR`: at 250 or more pairs, the interval half-width is at most `0.020`, the upper limit is below `+0.020`, and superiority is not proven.
8. `ADVANCE_AS_SUPERIOR`: at 250 or more pairs, the interval half-width is at most `0.020` and the upper limit is below zero.
9. `ELIGIBLE_FOR_BET_READINESS_STUDY`: the separate Stage E prerequisites are met; the underlying scientific state is retained independently.

Operational integrity, coverage, calibration, legal transitions and termination are gating. Run errors, distributional summaries, one-run/extra-inning rates, and non-gating regime slices are diagnostic; V18 is not required to win every secondary metric.

## 3. Checkpoints and precision

| Paired games | Use | Comparative authority |
|---:|---|---|
| 20 | Operational checkpoint | None |
| 50 | Early descriptive monitoring | None |
| 100 | Preliminary scientific checkpoint with CI | Comparative monitoring and material-regression detection; no advancement |
| 250 | First formal advancement checkpoint | Noninferiority or superiority may be established |
| 500 | Continued confirmation if available | Confirmation under unchanged rules |

Any comparative claim requires at least 100 pairs. Subgroup results require 50 games and at least 10 home wins and 10 home losses. Subgroups remain exploratory even when reportable. A primary CI half-width above `0.020` prohibits advancement.

Canceled and voided games are permanently excluded. A postponed game is excluded until AISP records a new schedule revision and a fresh forecast. All records sharing duplicate game or forecast identities are excluded fail-closed. No forecast may be reconstructed after the event.

The planning calculation uses a non-OOT paired log-loss-difference SD of `0.14` and a temporal design effect of `1.25`. The two-sided 95% detectable absolute differences are:

| Games | Detectable difference |
|---:|---:|
| 20 | 0.0686 |
| 50 | 0.0434 |
| 100 | 0.0307 |
| 250 | 0.0194 |
| 500 | 0.0137 |

These are planning estimates, not future thresholds. Actual decisions always use the paired chronological block-bootstrap interval. The `0.020` noninferiority margin was chosen before prospective outcomes: it limits tolerated average realized-outcome log-score degradation to approximately a 2.02% likelihood ratio (`exp(0.02)`), while remaining just resolvable near the 250-game planning checkpoint. The same `+0.020` boundary defines material regression in the adverse direction.

## 4. Calibration and operational fairness

At 250 games, calibration fails if any of the following holds:

- absolute calibration intercept exceeds `0.15`;
- calibration slope is outside `[0.70, 1.30]`;
- any eligible broad probability band has an absolute observed-minus-predicted gap above `0.10`.

These thresholds are safety gates rather than claims of perfect calibration. A small sample that cannot estimate them remains insufficient; it is not treated as passing.

The evaluator preserves every exclusion with the SHA-256 of the original record and a sorted reason list. Re-evaluating identical input under the same protocol produces the same exclusions, metrics, bootstrap draws, state and result checksum.

## 5. Monte Carlo uncertainty

Every forecast persists simulation count, Monte Carlo standard error, 95% half-width, seed policy and path digest. For independent Bernoulli paths, the evaluator checks `SE = sqrt(p(1-p)/N)` and `95% half-width = 1.96 × SE`.

At `p = 0.5` and `N = 5,000`, SE is `0.007071` and the approximate 95% half-width is `0.01386`. Probability differences smaller than the larger forecast's Monte Carlo half-width are labeled simulation-indistinguishable. This interval covers sampling error only, not model uncertainty.

Common random numbers are recognized only when scenario records carry the same seed lineage and transition draws. Later production qualification may consider more paths or variance reduction after measuring runtime and observed simulation contribution; this protocol does not change the accepted 5,000-path configuration.

## 6. Error and Regime Atlas

AISP should retain the following pregame-identifiable metadata when available: league, season, date/start, teams and home/away, lineup and starter confirmation state, time since lineup confirmation, cold-start and missing-feature counts, starter handedness, batter handedness composition, starter and bullpen quality bands, bullpen workload availability, park, weather availability, travel/rest indicators, divisional status, day/night, forecast lead time, model and market disagreement, market freshness and dispersion, predicted-total and win-probability bands, simulation uncertainty, transition-backoff usage and unsupported-capability flags.

Regime analysis cannot use postgame-identifiable definitions. Every slice carries a multiple-comparison warning. A few large misses cannot automatically create a specialist. A regime becomes a modeling target only after chronological confirmation under an separately approved model-development task.

## 7. Calibration discrepancy reconciliation

The earlier `0.05837229443583025` statistic is the maximum absolute top-class reliability gap across qualifying 0.1-wide bands calculated separately inside each chronological fold and then maximized across folds. Its worst cell was fold 2, `[0.6,0.7)`, with 1,033 observations.

The final `0.030587306750928467` statistic pools all five OOF folds before forming the same 0.1-wide bands and applying the same 1,000-row gate. Its worst qualifying pooled cell was `[0.6,0.7)`, with 4,164 observations.

Thus the discrepancy is caused by foldwise-maximum versus pooled aggregation. It is not caused by Final OOT, changed bin widths, changed minimum support, a different underlying matched OOF family, or PA-model refitting. Both statistics and definitions remain preserved in the contract.

## 8. Executable evaluator and supplement

Run the checked-in fixture:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_mlb_v18_acceptance_protocol.py `
  --input tests\fixtures\mlb_v18_acceptance_records.json `
  --output-root outputs\mlb-v18-acceptance-evaluations
```

The fixture contains one legitimate paired settled game, so the correct state is `INSUFFICIENT_EVIDENCE`; sportsbook status is `NOT_EVALUABLE`.

The evaluator writes `evaluation.json` and `report.md` under `sha256/<result checksum>/`. It performs no provider calls, model training, database writes or AISP mutation.

Evaluation-contract supplement:

- ID: `mlb-v18-acceptance-1d72242432e045a7f921e115`
- SHA-256: `1d72242432e045a7f921e115c8a7ad00ed11c80a8b8503f512ebaec67a087aaf`
- Referenced V18 bundle: `a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27`

The supplement specifies the AISP fields needed for forecast identity, bundle lineage, timestamps, evidence cutoff, input receipts, participant confirmation, probabilities and score distributions, Monte Carlo uncertainty, exact Gen 1 pairing, sportsbook/observational-market evidence, immutable settlement, regime metadata and exclusion lineage.

## 9. Explicit boundaries

- Final OOT opened or scored: **no**.
- New predictive model fitted or tuned: **no**. Calibration intercept/slope in the evaluator is a monitoring statistic, not a forecast model.
- Historical oracle study generated: **no**.
- Accepted V18 bundle modified or replaced: **no**.
- AISP repository, database or registration state modified: **no**.
- Wager policy optimized or champion promoted: **no**.
