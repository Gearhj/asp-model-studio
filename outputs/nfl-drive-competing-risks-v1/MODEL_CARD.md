# NFL drive competing-risks survival challenger V1

Identity: `NFL_DRIVE_MULTINOMIAL_L2_C0_1_PROPOSAL_BLEND025_V1`.
Status: research only; final admission disposition is recorded in ASSESSMENT.json. No production replacement, wagering, AISP execution or new forecast authority.

## Evidence and population

Seven already admitted nflverse Development partitions, 2018-2024: 340,587 source records in 1,942 games. Archives were physically acquired on 2026-08-29; retrospective chronological reconstruction does not establish historical release vintages. The authoritative source receipts and physical hashes are in source-bindings.json.

Final drive eligibility supports 28,937 drives / 171,166 predecision states. All 1,942 full-game scores reconcile after using retained order_sequence rather than play_id alone. Endpoint/clock checks remove ambiguous and unsupported complete drives; penalties and compound events are a substantial source of selection bias. Intermediate audit evidence is preserved. No 2025-season payload or 2026 outcome was read.

## Model and folds

One multinomial logistic classifier, L2 C=0.1, StandardScaler, no class rebalancing, max_iter=600. Twenty-five fixed preplay/earlier-drive features, nine mutually exclusive continuation/terminal causes. Neither team IDs nor future drive summaries are classifier inputs. Numeric ranges, scaler and coefficients are fitted inside each earlier-season fold. No imputation, player or weather covariate is fabricated.

Warmup/training begins 2018-2020. Development out-of-fold targets are 2021-2022. 2023 is secondary reused historical evidence; 2024 is reused Validation. Both later cohorts have previously been used by existing NFL research. 2025 stays sealed. The original through-2023 play artifact is reused exactly for2024; earlier baseline folds retain its code, configuration, joint donor law and team shrinkage.

## Simulation

Fixed 25% finite-proposal hazard branch and 75% baseline branch. Sixteen original legal joint-play donors define feasible causes on the hazard branch; the selected donor is unchanged. Raw classifier probabilities differ from the actual integrated law; both are assessed separately. Exact baseline fallback applies to zero weight, unsupported state, and overtime before any additional random draw. Full-game state transitions and regular-season overtime rules are unchanged.

200 full-game draws per arm/target; 108 targets total. Maximum single-game probability MCSE is about 0.0354; it measures sampling precision, not model uncertainty. 128 complete drive futures per origin for fixed identity-selected starts and midpoints. All paired home/away finals and drive populations are retained. No final score clipping, rounding, tie removal, or artificial points are introduced. Original sampling seeds are paired by target but paths may diverge, so no assertion of event-level Monte Carlo coupling is made.

## Limits and costs

The existing donor normalization orders play IDs and excludes period-ending/unsupported clock intervals; those inherited limitations remain attached to its frozen artifact. This study corrects ordering only in new drive labels, not in the operational baseline. Penalty strategy, timeouts, roster, quarterbacks, injuries, personnel and weather are not added. Neutral-site adjustment and unseen-team hazard effects are not fitted. The engine remains regular-season-only for full games; overtime hazards fall back to regulation-trained baseline donors under the existing overtime rules.

Conditional hazard NLL uses a separately declared, symmetric finite-proposal scoring stabilization; it is not a deployed probability calibration. Football weeks/games, not play rows or draws, are uncertainty units. Outcome-selected situation diagnostics cannot establish a causal mechanism or promotion claim.

Measured fit time, simulation time, per-process memory, full scoring, support counts and admission gates are retained in FROZEN_SELECTION.json, per-game assessment files and ASSESSMENT.json. Runtime is baseline-first with a shared donor cache within a worker, so timings are order-dependent; no speedup claim is warranted.

## Commands

```powershell
.\.venv\Scripts\python.exe -B scripts\run_nfl_drive_survival_v1.py --stage replay
```

Study stages are audit, finalize-data, verify-preplay, fit, evaluate --season YEAR, report, index and replay. The optional verify-preplay stage reproduces the source scoreboard target-exclusion check; replay checks retained populations and frozen bindings without repeating that source audit. Existing frozen artifacts are reused; audit refuses to overwrite its declaration, and eligibility changes are forbidden once fitting begins. No stage invokes a provider or publisher.

## Final assessment

Disposition: **RETAIN_EXISTING_PLAY_ENGINE**. The candidate is not advanced and no Claude handoff is issued.

On 36 reused 2024 games, candidate-minus-baseline joint energy is -0.0362 (95% week-block interval -0.2787 to +0.2066). Total CRPS worsens +0.1496; 2023 energy worsens +0.1959. The upper-bound, total-CRPS and cross-season gates fail. Current-decision hazard NLL/Brier gains therefore do not establish a useful full-game improvement. Remaining-drive length CRPS worsens slightly in both later seasons; 2024 incidence Brier also worsens.

Measured whole-game simulation time totals 1,554.6 baseline seconds and 2,702.6 candidate seconds across all 108 targets, about 1.74x overall. Peak worker working set is about 1.07 GB and includes loaded baseline data/cache. No score transformations or illegal states were recorded. Eight complete game sequences, 24 complete drive futures, and eight exact fallback game checks passed; see replay-verification.json for exact accounting.
