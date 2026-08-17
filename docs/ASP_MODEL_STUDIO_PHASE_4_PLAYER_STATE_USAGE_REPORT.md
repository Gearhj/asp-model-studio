# ASP Model Studio Phase 4 Player State and Usage Report

## Executive Result

Milestone A completed as governed research. `MLB_DYNAMIC_PLAYER_STATE_V1` selected D3 from 2024-only evidence and registered `DYNAMIC_STATE_RESEARCH_CHALLENGER`. Phase 3 remains `RESEARCH_BASELINE`. Milestone B was not executed in this checkpoint because the session usage budget was nearly exhausted; no lineup, starter-duration, or bullpen result is claimed.

## Phase 3 Baseline Authority

- Run: `sports-pa-research-run:sha256:9ee241378320fb820aab2531a6525d2d4624d42e7ff6c406e147f28c6800fd07`
- Run SHA: `dc62d2bd07df9ddd26494512c748a5859cf9667cdc901f002f6d2a86b619658e`
- Feature contract SHA: `fc3227fe1488f0cf422dc40c634a9b0b1c432828d479a68ea6ba7a0dce038d1e`
- Feature view: `mlb-pa-feature-view:sha256:74b9c24bb57dd75061a5de0f967c4a57e492eab9e016be950a036292bf8f958b`
- Graph: `mlb-pa-model-graph:sha256:c42cec805870c4eae5f935aa406714e5cecd0f46ff0dfd2ca78d57e2397de18b` (20 nodes, 28 edges)
- Status: `RESEARCH_BASELINE`, unchanged.

## Dynamic Player-State Contract

`MLB_DYNAMIC_PLAYER_STATE_V1` has semantic SHA `af4754aaf4ea4b064de8337de4249fc818d5d5f5992b55d29557738daeda5cb0`. It fixes the eight-class Phase 3 order, seven log odds relative to `OTHER_REACH`, effective sample size, entropy, days since evidence, 7/30/90-day counts, explicit missing history, row identities, checksums, dataset/bridge authorities, and source partitions. State schema SHA is `3da739c4a9c2ca53584d21488bbb82f6f1959107f6c0f48a2d43dd6b669119ba`; history schema SHA is `40103cddaed2ab365dc6bb01f79ae8bf7c9307ba47d11057a083520b61a98ed6`.

## Temporal and Same-Date Policy

Only evidence with `final_available_date < target.game_date` is eligible. Same-date games, including earlier doubleheader games, current-game evidence, and future evidence are excluded. Policy tuning is chronological and date-atomic inside 2023. Selection uses 2024 only; 2025 is frozen final evidence.

## Batter-State Construction

Prior completed PAs are exact-joined to canonical batter identity and accumulated in A preseason, B cumulative, and C recency representations. The governing D3 uses B cumulative state. Missing history remains an explicit indicator; player identity is lineage only and never a predictive category.

## Pitcher-State Construction

Prior completed PAs faced are processed under the identical class order, cutoff, shrinkage, uncertainty, and missing-history rules. The governing D3 uses B cumulative pitcher state. No player names, handedness, or manufactured attributes are used.

## Recency and Shrinkage Selection

The bounded 2023 grid selected policy `mlb-dynamic-player-state-policy:sha256:6db7c14882f25b33d63fd5726380306cc429535ee47bcac3e05cb08632b7f3c5`: cumulative/no decay (`halfLifeDays=null`) with prior ESS 300. The PA logistic grid selected `C=0.05` for D1-D4.

## Dynamic PA Candidates

- D0: immutable Phase 3 raw C4 probabilities; no refit or relabel.
- D1: context plus dynamic batter B state.
- D2: context plus dynamic pitcher B state.
- D3: context plus cumulative batter and pitcher B state.
- D4: context plus recency-weighted batter and pitcher C state.

All new candidates use fold-local preprocessing and true multinomial L2 logistic regression with `C` in `{0.05, 0.2, 1.0}`.

## 2024 Dynamic-State Results

| Candidate | Log loss | Summed Brier | Top-label ECE | Runtime seconds |
|---|---:|---:|---:|---:|
| D0 | 1.4842548490 | 0.7067859080 | 0.0117306649 | 0.000 |
| D1 | 1.4821169740 | 0.7061064750 | 0.0085213016 | 276.687 |
| D2 | 1.4903084723 | 0.7094059784 | 0.0079279036 | 302.906 |
| D3 | 1.4765879683 | 0.7038595501 | 0.0057375808 | 360.499 |
| D4 | 1.4765879683 | 0.7038595501 | 0.0057375808 | 359.370 |

D3 and D4 tied on the governing metrics; the frozen ordinal tie-break selected D3.

## 2025 Dynamic-State Results

| Candidate | Log loss | Summed Brier | Top-label ECE |
|---|---:|---:|---:|
| D0 | 1.4816765958 | 0.7063844063 | 0.0037567915 |
| D1 | 1.4796924317 | 0.7057842998 | 0.0034937580 |
| D2 | 1.4889707764 | 0.7092061571 | 0.0035867436 |
| D3 | 1.4740998598 | 0.7035281534 | 0.0028407451 |
| D4 | 1.4740998598 | 0.7035281534 | 0.0028407451 |

These results did not participate in selection.

## Calibration

The 2024 scalar-temperature experiment fitted `T=0.9821039849791475`. It was eligible on 2024 but failed the frozen 2025 non-worsening gate, so it was not retained. Registered final probabilities remain raw; raw and scaled evidence are preserved.

## Bootstrap Comparison

The deterministic bootstrap used 500 whole-`game_id` resamples (2,429 clusters in 2024 and 2,430 in 2025). Probability D3 was better than D0 was 1.0 for log loss and Brier in both folds.

- 2024 log-loss difference CI: `[-0.0083781188, -0.0069946467]`
- 2024 Brier difference CI: `[-0.0032575103, -0.0025964970]`
- 2025 log-loss difference CI: `[-0.0082291828, -0.0069508445]`
- 2025 Brier difference CI: `[-0.0031607438, -0.0025188771]`

## Dynamic-State Decision

`DYNAMIC_STATE_RESEARCH_CHALLENGER`. D3 improves raw log loss and Brier over D0 in both folds without a governing calibration defect. This does not alter Phase 3, authorize deployment, or create a simulator or bundle.

## Lineup Candidate-Pool Construction

Not executed in this checkpoint. The pending contract requires prior-date participation only, measured pool coverage, no target-game injection, and separate complete-order eligibility.

## Lineup Projection Results

No registered results.

## Lineup Decision

Not configured; no decision has been registered.

## Starter-Duration Features

Not executed. The pending component remains conditional on historical starter identity and must use prior-date workload only.

## Starter-Duration Results

No registered results.

## Starter-Duration Decision

Not configured; no decision has been registered.

## Bullpen Candidate-Pool Construction

Not executed. The pending component requires prior-date relief history, measured pool coverage, and no target-game reliever injection.

## Bullpen-Usage Results

No registered results.

## Bullpen-Usage Decision

Not configured; no decision has been registered.

## Strict and Enhanced Separation

All registered predictors are strict prior-date evidence. Actual participation and usage fields remain retrospective targets only. No enhanced same-date or actual-participant analysis was used for the decision.

## Artifact Lineage

- Registered component: `sports-phase4-component:dynamic-player-state:sha256:0f26a926ba8de5ba542ca41c324f42dcf8735ecd8173e0c9a7ed509e8d0a0433`
- Study: `sports-phase4-study:sha256:d1584bfed29842976dac911fdbbbdbf466b3b7cacaf68ffe68fc808f8d75ffa7`
- Study SHA: `59b1c93227c2b2506503881fa80cc2e49b27c574c6d57f8b6c01cd61a06748a5`
- Checkpoint: `mlb-dynamic-player-state-checkpoint:sha256:54d24d1342bf5d10a8d6b5b7da547f6d2644b82a3f3bbd25ff0b3feac76a8333`
- State artifact: `sports-phase4-artifact:dynamic_player_state:sha256:6117988df812bb35dc0fdafd7f8b78d0c0a62a8454e598e4271f2da148bf3b03`; content SHA `f11fe8fedbc4e105278f2ef59be56f5e8d32e7d4615c98b8e7cd3c2cc8bc86fe`; 621,516 rows.
- History artifact: `sports-phase4-artifact:dynamic_history_index:sha256:316355ab2ddcbab922bf9d00894228612b4b58998e0167dfda55e5b5fb1547c3`; content SHA `482baed9438a428a78c3e8b28d467269eb5f9e78d317dda92bf7c388f07f4fc0`; 347,169 aggregate rows from 913,349 source rows and 1,826,698 resolved references.
- Registered inventory: 32 logical artifact references. Artifact bodies remain outside Git and SQLite.

## Model Graph

Registered graph `sports-phase4-model-graph:sha256:14749dbd4501cbe46657140b55a0a82327bfb4172064561f74ab540e90d47dbd` extends, rather than replaces, the frozen Phase 3 graph. Participation, starter, bullpen, confirmed feeds, platoon, base-out transition, simulator, residual, bundle, and monitoring nodes remain incomplete or not configured as applicable.

## Runtime and Storage

The successful governed run completed in 45m16s. Validation reused all 329 cached dataset entries with zero misses. Runtime Parquet/model/prediction artifacts are beneath ignored repository-owned storage. SQLite contains metadata and logical references only. Two earlier attempts failed closed before fitting or registration while semantic Arrow/Parquet content hashing was corrected; the original checkpoint and artifact identities were preserved.

## Tests

- Dynamic state/training/runner/CLI/supervision: 43/43 passed.
- A-only Phase 4 registry and dataset projection: 38 passed, 1 B compatibility test intentionally deselected.
- Post-registration CLI registered-ID regression: 10/10 passed.
- Full Phase 3, frontend, build, browser, authentication, storage, and provider-disabled gates remain for the Milestone B/final checkpoint.

## Browser QA

Deferred to the final Milestone B checkpoint. No authentication was weakened and no session was injected. The application was not stopped.

## Remaining Data Gaps

No governed handedness, birth date, age, debut date, position, injury, transaction, roster, or announcement-time authority exists. Lineup and bullpen candidate pools therefore retain prospective roster-coverage limitations; platoon modeling remains not configured.

## Remaining Simulator Components

Lineup projection, starter duration, bullpen usage, confirmed-lineup feed, probable-starter feed, injury/transaction feed, platoon, base-out transition, game simulation, residual modeling, bundle export, and forward monitoring remain incomplete or not configured. No game probabilities or betting outputs were produced.

## Recommended Next Step

Resume Milestone B from the preserved source checkpoint. Finish the pending lineup population/bootstrap/calibration corrections, component-local checkpoint/resume behavior, exact dynamic-history lineage, registry schema alignment, focused tests, then run the governed participation CLI. Only after coherent B decisions should the frontend, browser QA, full acceptance gates, and Commit 2 be completed.
