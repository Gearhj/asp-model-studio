# MLB V19 Structural Baseball Model Innovation Program

## Disposition

`NO_INCREMENTAL_VALUE`

The program produced one fitted, executable structural challenger and a matched comparison against the exact retained V18 probabilities. The challenger adds a shrunk team-level ball-in-play conversion effect while preserving every non-BIP class and total BIP mass. Its point estimates were slightly better, but the predeclared calendar-date bootstrap interval crossed zero. It therefore failed the frozen advancement gate. V18 remains the only controlling model; no forecast, exchange, AISP, scheduler, or production artifact changed.

## Why this was the defensible first module

V18 already models named batter and announced-starter identities through player rolling features, handedness, coarse pitch mix, fastball velocity, ordered confirmed lineups, simulated game state, and an empirical base/out transition model. It does not bind named pregame fielders and positions, contact geometry, catcher/umpire effects, named reliever availability, manager tendencies, or prospective substitutions. The retained historical table can identify the fielding team but cannot honestly attribute conversion to a specific fielder.

The smallest executable increment was therefore a team-level defense fallback. It estimates the fielding team's historical hit rate conditional on a ball in play, shrinks it toward the league rate, converts the difference to a capped log-odds shift, and changes only the conditional split among `SINGLE`, `DOUBLE`, `TRIPLE`, and `BIP_OUT`. It preserves the V18 relative single/double/triple mix. This is an associational team conversion effect, not a fielding-runs or player-defense model.

## Frozen chronology and evidence

The design was committed before assessment in commit `cd6aac5`. A verifier correction distinguishing a logical directory identity from the physical Parquet member hash was committed in `ba35f6d` before the assessment succeeded.

| Role | Evidence | Use |
|---|---|---|
| Development | 2023 fold 0 | Select one of three prior strengths on 2023-08-01 through 2023-10-01 |
| Assessment | Reused 2024 fold 1, 2024-03-20 through 2024-07-06 | Matched diagnostic comparison only |
| Excluded | Two delayed assessment games; one unresolved 2023 finalization from all history | Completion-aware protection |
| Prohibited | 2025, 2026, Final OOT, sealed August 14–27, 2026 | Zero rows/bytes read |

Known delayed games enter history only after their retained completion-date proxy. Same-date outcomes never enter a target's state. The exact V18 numerical predictions retain the inherited suspended-game chronology limitation documented by the earlier V19 attempt, so even a numerical win could not have supported promotion.

## Result

The assessment contains 99,646 PAs, 64,232 BIP PAs, 1,328 games, 103 calendar dates, and 100% matched coverage.

| Metric (lower is better) | Exact V18 | Defense challenger | Candidate − baseline |
|---|---:|---:|---:|
| Eight-class log loss | 1.480388736 | 1.480353709 | -0.000035027 |
| Summed eight-class Brier | 0.703736181 | 0.703733151 | -0.000003030 |
| Conditional BIP log loss | 0.605916367 | 0.605862028 | -0.000054339 |
| Conditional BIP Brier | 0.207588343 | 0.207571114 | -0.000017229 |
| Conditional BIP ECE | 0.019714250 | 0.018126380 | -0.001587869 |

The selected prior strength was 1,600 BIP opportunities. All three frozen Development candidates were nearly tied; 1,600 had the lowest Development log loss. Assessment shifts ranged from -0.10148 to +0.09680 log odds, with mean absolute shift 0.03203 and no capped rows.

Calendar-date bootstrap, 2,000 replicates, seed 20260917:

| Difference | Mean | 95% interval | Gate |
|---|---:|---:|---|
| Eight-class log loss | -0.000035027 | [-0.000142612, +0.000062384] | Failed: upper bound is above zero |
| Summed Brier | -0.000003030 | [-0.000051769, +0.000043496] | No material harm, but no established gain |

The effect is too small and uncertain to justify a game-simulation challenger, a mixture-of-experts gate, or a prospective shadow contract.

## What the program learned

1. Team defense conversion is executable from existing retained Development evidence, but this simple aggregate adjustment does not add established predictive value over V18.
2. The baseline's conditional BIP calibration slope is low (0.252); the challenger changes it to 0.283. That movement is descriptive and does not establish a correction because the overall proper-score uncertainty crosses zero.
3. Coarse pitcher archetypes are already mechanically supported, but the retained timing defect invalidates the prior V19 cluster comparison. No new archetype claim was made.
4. Named bullpen selection and manager policy remain blocked by point-in-time reliever availability, role, and workload histories. Anonymous or oracle reliever sequences cannot validate that module.
5. A mixture of experts was not fit. Only one valid candidate reached assessment, and it failed its gate.

## Integrity and operations

- Non-BIP probabilities changed by exactly `0.0`.
- Maximum BIP mass difference was `2.22e-16`; maximum row mass error was `4.44e-16`.
- A full deterministic replay changed zero of eight retained artifact hashes.
- Provider calls: 0. Provider bytes: 0. Cost: $0.
- AISP writes: 0. Exchange writes: 0. Forecasts: 0.
- Production owners, V18 artifacts, and the deployed checkout were not modified.

The next justified dependency is a completion-aware rebuild of the baseline rolling histories, followed by a frozen common-population comparison. After that, the highest-value structural data increment is timestamped pregame named-reliever availability and workload, not another aggregate defense adjustment.

\n