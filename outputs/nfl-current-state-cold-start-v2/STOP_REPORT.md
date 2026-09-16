# NFL current-state cold-start V2: source-timing stop

## Executive result

Stopped before model development under the assignment's explicit rule: **a required source lacks defensible point-in-time timing**. No V2 model, treatment replacement, fitted evidence, forecast or AISP handoff was produced. This is an evidence receipt, not a completed model card or successful implementation.

The three registered local Bronze manifests contain retrospectively acquired Development play-by-play, not historical as-published weekly vintages. All 26 Development PBP partitions (1999–2024) in each manifest have retrieval time `2026-08-29T13:34:33.063899Z`. The 2018–2024 assets were updated in 2025 or 2026. Their game/clock timestamps establish when football occurred, not when the exact derived statistics became available.

The shared `releasePublishedAt=2022-01-28T02:12:09Z` is the release-tag timestamp. It cannot establish that the contents of a later-updated asset were available in 2020, 2023 or 2024. The existing `semantic_features.make_history_features` explicitly calls its prior-date calculation a historical reconstruction, not proof of an archived release timestamp. A guessed lag, refreshed download or wider prior cannot repair this provenance gap.

## Assignment accounting

| Requested result | Actual disposition |
|---|---|
| Starting state | `codex/nfl-play-level-simulation-engine-v1` at `a3cca9e7d974346f0663070b8b66b671538354af`, as expected. No tracked changes. Existing untracked outputs preserved. |
| Ending branch | Created `codex/nfl-current-state-cold-start-v2` from that exact commit. The resulting commit records only this stop evidence. |
| Development seasons/games/folds | Existing predecessor evidence: 6,991 games in seasons 1999–2024; five outer validation seasons 2020–2024, 1,408 games (269/285/284/285/285). No new folds executed. |
| All 44 former median fields | Exact names and prior descriptions copied from verified existing receipts into `former-median-inventory.json`. Every V2 status is `NOT_IMPLEMENTED_BLOCKED_REQUIRED_HISTORICAL_SOURCE_TIMING`. No field was falsely marked replaced. |
| Generic fallback count | Zero calls executed because no V2 inference ran. **The required fallback-free model has not been implemented or verified.** Existing M1 still has the documented 44 median-treated missing inputs. |
| Current sources | September 8 roster/depth assets retrieved September 9 already exist. They were not refreshed or consumed by a new model. See source timing receipt for exact timestamps, hashes and bytes. |
| Models fitted | Zero estimator starts, zero completions, zero final fits or calibration/ensemble fits. No finalist comparison was preregistered or launched after the gate failed. |
| Week 1 / Weeks 1–4 / full season | No new metrics. Existing comparison below is explicitly predecessor evidence. Predecessor cohort includes 80 Week 1 and 319 Weeks 1–4 games. |
| Calibration and uncertainty | No new calibration, reliability, CRPS, interval, key-number or tie-calibration results. Existing selected-on-Development intervals are not independent V2 validation. |
| Subgroups | No new subgroup evaluation. No current starter, rookie, coach-change, injury, weather or roster-turnover labels were inferred. |
| M1 / HGB-T2 / C2 / C3 | Existing saved results preserved and summarized below; not relabeled V2 or true vintage-controlled replay. |
| Market-aware layer | Not trained or changed. Existing benchmark reports zero authorized timestamp-matched quotes among 1,408 evaluation events. Untimed market references do not authorize blend-weight fitting. |
| Demonstrated improvement | Not established. No new candidate was evaluated. |
| Current 2026 forecasts/skips | Zero new forecasts. Publication was not attempted; new slate/skip counts are not reported as a completed all-skip publication. Existing forecasts remain unchanged. |
| Simulation integration | Existing `NFL_DEVELOPMENT_HIERARCHICAL_PLAY_V1`, score/drive supplements and scenarios preserved; no new current-state conditioning or simulations. |
| Workbook / executable contract / UI | Existing 300-entry workbook and policy preserved. No unverified treatment authority or misleading UI result was published. |
| Handoff / AISP import | None for V2. Exact next AISP action: **do not import a V2 model from this receipt; preserve existing NFL evidence.** No executable import command exists for a nonexistent bundle. |
| Boundaries | No source refresh/provider calls, sealed 2025 payload access, AISP writes, MLB changes, promotion or wagering authority. No model or application code changed. |

## Existing comparison, not new V2 evidence

The four saved OOF files use the same 1,408 event IDs. Lower log loss is better. Calibrated probabilities are separately labeled and are not automatically a calibrated joint score distribution.

| Existing pipeline | Weeks 1–4 calibrated LL | Full calibrated LL | Full raw LL |
|---|---:|---:|---:|
| M1 recipe fold-refit | 0.693660 | 0.665318 | 0.674896 |
| HGB-T2 | 0.693378 | 0.662128 | 0.674775 |
| XGBoost C2 | 0.699225 | 0.662423 | 0.674027 |
| XGBoost C3 | 0.701835 | 0.661772 | 0.674172 |

Existing calibrated candidate-minus-M1 season/week 95% intervals:

| Existing pipeline | Full difference [interval] | Weeks 1–4 difference [interval] |
|---|---|---|
| HGB-T2 | -0.003190 [-0.009189, +0.002811] | -0.000282 [-0.010347, +0.009667] |
| C2 | -0.002895 [-0.011949, +0.005903] | +0.005565 [-0.012297, +0.021621] |
| C3 | -0.003546 [-0.012008, +0.004555] | +0.008175 [-0.006017, +0.021068] |

These are exploratory comparisons after Development selection, with unverified historical source vintages. None establishes V2 improvement. The operational frozen M1 is also **not** the historical fold comparator: its metadata records 7,276 training games, seasons 1999–2025 and cutoff `2026-02-08`. Only its manifest was read; its binary and sealed training payload were not loaded. The saved fold-refitted M1 recipe is the appropriate existing historical reference.

## Current evidence is not wholly absent

| Existing 2026 family | Snapshot rows | Asset updated UTC | Retrieved UTC |
|---|---:|---|---|
| Rosters | 2,955 | 2026-09-08 11:56:47 | 2026-09-09 00:36:09.868295 |
| Weekly rosters | 2,955 | 2026-09-08 11:56:44 | 2026-09-09 00:36:11.953298 |
| Depth charts | 505,422 | 2026-09-08 11:57:05 | 2026-09-09 00:36:19.939060 |

These are source snapshot rows, not counts of confirmed current starters or unique active players. Depth charts contain `dt`, `gsis_id`, `pos_rank` and `pos_slot`. Their presence does not establish an accepted starter/injury scenario or historical vintage-controlled performance. No 2026 injury partition is registered. Missing current optional context may eventually use declared priors; it is not the primary reason this run stopped.

The standard sync entry point constructs `ALL_SEASONS` and full verification/materialization reads historical partitions. It was not executed because this assignment requires sealed 2025 evidence to remain physically unread. Refreshing current roster/depth assets would not recover historical PBP vintages anyway.

## Exact evidence needed to resume

Provide authorized, immutable **historical schedule and completed-game PBP/statistic vintages for the Development replay**, containing canonical identities, season/week, the exact source version/hash/bytes, original publication or defensible first-available timestamp, effective event time separately, and correction/supersession lineage. The actual values used must be available before their replay cutoff. Weekly updates also need evidence that the source game had completed and its statistics were available. No 2025 Final OOT payload is requested.

Alternatively, James would need to explicitly change the requested validation standard to a clearly labeled retrospective, date-lagged study, accepting that historical as-published validity is unverified. That is a different assignment and was **not assumed approved**. It would not justify relabeling old results as true point-in-time forecasts or automatically promoting a model.

Current optional QB/roster/coach/injury sources require their own supported semantics if used, but they cannot substitute for the missing historical timing evidence. No claim is made that such archives do not exist outside the three registered local manifests inspected here.

## Evidence and verification

- Local Bronze metadata: `source-timing-stop-receipt.json`, including all three manifest identities, selected Development source receipts and current roster/depth receipts. Checksums bind the metadata; no source payload hash/read is claimed for this run.
- Exact 44-field receipt: `former-median-inventory.json`, sourced from handoff `761ea4cf43c3413692533fbd46b07fe4e5f4e6ec8ac62b0febcd6e5a0bc85477`, `forecasts[0]`, CURRENT v7 ATL–PIT. It reports `FROZEN_TRAINING_MEDIAN_IMPUTATION_APPLIED`.
- Existing specification identity: `ad3f1e57106f58b76b835cb7cd3912c26d357e05fd85f9495dbccd9367edd6d6`. Its 197 registered inputs, 12 additions and 91 proposed entries are predecessor work. Fixed 0.65 offseason retention in that work is not relabeled a learned V2 decay.
- Existing result: `outputs/nfl-semantic-lab-v1/runs/7a651ec80b3b77106b018dd6739f55e26e45cbcf5e1f8811d6557f039d372f69/result.json`, SHA-256 `2ccce6a00e27f8b56edf40736a4eaecf3884e59e7c857c05dbb65ddc5c020488`.
- Existing interval supplement: `outputs/nfl-semantic-lab-v1/reporting/sha256/e2f05ee9dd56dff2e67f72b119fb833d8f91d4011b7ed38434f39b03d355f2f5/supplement.json`.
- Operational M1 training metadata: `C:/Users/james/asp-data-staging/nfl/m1-modeling-benchmark-v1/research-artifact/objects/sha256/ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9/manifest.json`.

Only focused JSON/provenance checks are applicable to this documentation-only stop. No model tests or full suite were run. File hashes and byte counts for this receipt are in `manifest.json`; they do not represent a forecast handoff.

**Verdict: NFL_CURRENT_STATE_BLOCKED**
