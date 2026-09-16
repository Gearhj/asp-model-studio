# MLB bounded selection-policy study

Verdict: `MLB_STRICT_POLICY_RETAINED`

Gen 1 and V18 were evaluated separately. V18 contributes 13 research-shadow forecasts and zero policy-decision records; no V18 selection or performance statistic is mixed with Gen 1.

## Funnel

The frozen Gen 1 cohort contains 18,610 evaluations across 154 events. Historical V1 has 7,550 evaluations and zero qualifications; the V2.1 control has 11,060 evaluations, 731 qualified evaluations and 22 distinct selections.

The largest recorded losses are missing complete two-sided market evidence (11,090 overlapping reason occurrences), other policy reasons (7,095), incomplete critical inputs / unconfirmed starters (6,997 each), missing lineups (6,683), readiness below threshold (6,367), non-positive adjusted EV (3,978), and adjusted edge below threshold (2,495). Missing sportsbook evidence is a market-data exclusion, not a model failure.

## Operational reconciliation

Claude's later read-only AISP audit (`eae5c197`) contains 20,679 rows over 169 games, versus the frozen study cohort's 18,610 rows. The later rows reconcile operations but do not replace the frozen evaluation cohort.

At the game level, the historical first blockers were: no forecast 2, no quote 24, stale quote 25, readiness 46, starter 9, and edge/EV 36; 12 final game rows reached QUALIFIED_BET.

For September 8, all 15 games stop first at missing two-sided quotes. The audit confirms 13 imported daily V18 rows, zero V18 shadow-board decisions, and zero positions linked to V18. Thus edge relaxation would change nothing operationally on the current slate.

The audit also resolves quote semantics: Gen 1's board allows 240 minutes of staleness and separately enforces a 15-minute pregame cutoff. The cohort's exploratory 15-minute quote-age label is not substituted for the persisted Gen 1 control gate.

Readiness is structurally suspect: the threshold is 70, while feature completeness, bullpen, and Statcast are never ready and remove 20 possible points. That supports a future graduated-readiness study, but not installation from this outcome-incomplete cohort.

## Gate dispositions

| Gate | Disposition | Evidence-based reason |
|---|---|---|
| FORECAST_IDENTITY_AND_PREGAME_ORDERING | KEEP_HARD | Identity and temporal validity are non-negotiable leakage controls. |
| COMPLETE_TWO_SIDED_MARKET | KEEP_HARD | A no-vig market decision and legitimate return cannot be computed without both sides. |
| QUOTE_AGE | KEEP_HARD_DO_NOT_RELAX | The audit confirms Gen 1 uses a 240-minute board-staleness rule plus a 15-minute pregame cutoff; the cohort's exploratory 15-minute age label is not the Gen 1 control rule. The exact control semantics are retained. |
| LINEUP_CONFIRMATION | KEEP_GRADUATED | The control already permits lineup-pending moneylines with an explicit penalty; no evidence supports either a new hard stop or removal. |
| STARTER_CONFIRMATION | KEEP_HARD | Unstable or missing starter evidence cannot be outcome-scored in this export, so softening is not justified. |
| READINESS | SOFTENING_STRUCTURALLY_MOTIVATED_BUT_NOT_EVIDENCE_APPROVED | The audit shows a 70 threshold while three never-ready components consume 20 points, but the export cannot outcome-score the excluded games. Keep the control unchanged until an outcome-linked graduated challenger can be independently evaluated. |
| ADJUSTED_EDGE | KEEP_CONTROL_AT_0_020 | Lower thresholds add only three to five distinct selections and cannot be independently outcome-scored. |
| MODEL_UNCERTAINTY | KEEP_PENALTY | The adjusted probability already subtracts the recorded uncertainty; no independent evidence supports weakening it. |
| EXTREME_DISAGREEMENT_AND_EVIDENCE_INTEGRITY | KEEP_HARD | These are corruption/review safeguards, not availability thresholds. |

Gate-state coverage confirms the distinction between availability and performance. Lineup evidence was confirmed in 3,090 evaluations and pending-but-allowed in 7,817; their qualified-evaluation counts were 412 and 319. Readiness bands below 50, 50–59.9, and 60+ contained 181, 7750, and 2976 evaluations, with 0, 281, and 450 qualifications. Calibration, error, return, and incremental-information comparisons across these states remain unavailable because the export does not map the selected team to the final home/away score.

## Exact retained control rules

| Parameter | Rule |
|---|---|
| Readiness | >= 70.0 |
| Adjusted edge | >= 0.020 |
| Adjusted EV | > 0 |
| Extreme disagreement | Hard stop at 0.15 |
| Quote timing | <= 240 minutes old and observed before the 15-minute pregame cutoff |
| Starters | both probable pitchers CONFIRMED (V1) / CONFIRMED or PROBABLE_STABLE (V2.1) |
| Lineups | lineup adequate (not MISSING) for full-game moneyline |
| Uncertainty | Preserve recorded adjusted-probability penalty |
| Stake | 0.25 Kelly; 0.005 unit, 0.010 position, 0.020 same-game, 0.050 daily caps |

## Compact comparison

| Policy | Eval qualifications | Distinct selections | Added | Mean adjusted edge | Outcome metrics |
|---|---:|---:|---:|---:|---|
| V2.1 control, edge ≥ 0.020 | 731 | 22 | — | 0.0387 | Actual positions only |
| GEN1_EDGE_0175_RESEARCH_CANDIDATE | 846 | 25 | 3 | 0.0361 | Unavailable: participant mapping missing |
| GEN1_EDGE_0150_RESEARCH_CANDIDATE | 894 | 27 | 5 | 0.0340 | Unavailable: participant mapping missing |

The exact control arithmetic replayed with zero decision mismatches. The actual control inventory has 9 settled positions on 22.5 stake units, P/L -2.72, return on stake -12.09%, and maximum drawdown 7.80. This sample is descriptive only.

## Candidate-only additional games (not recommended selections)

### GEN1_EDGE_0175_RESEARCH_CANDIDATE

| Event | Selection | Decision | Edge | Price |
|---|---|---|---:|---:|
| `8814a14e-0ba4-4714-ad6f-6a338fdca96a` | AZ ML | `0036c419-a660-49c6-ae41-faaf243f81a2` | 0.0183 | 2.2100 |
| `2ae5d4fb-7795-4bef-9210-afa39c915c00` | TB ML | `ab3b22f5-9e5b-45eb-8b83-3f54530b36a6` | 0.0182 | 1.9524 |
| `209883ba-5e1b-4347-9fa6-ce902bd33afd` | SF ML | `0f0e3f04-006e-4fe7-8e7e-2a32b3114617` | 0.0185 | 2.4500 |

### GEN1_EDGE_0150_RESEARCH_CANDIDATE

| Event | Selection | Decision | Edge | Price |
|---|---|---|---:|---:|
| `3c1ca6b1-d96e-4d57-94da-e5983c527fca` | MIL ML | `67b37694-9065-4608-a35d-e9ba003e6846` | 0.0171 | 2.1400 |
| `a4001e32-dabc-4f61-90ac-b88ab4553bde` | ATH ML | `93d9208a-4630-49b2-827a-4acc866f0ff1` | 0.0158 | 2.9400 |
| `8814a14e-0ba4-4714-ad6f-6a338fdca96a` | AZ ML | `0036c419-a660-49c6-ae41-faaf243f81a2` | 0.0183 | 2.2100 |
| `2ae5d4fb-7795-4bef-9210-afa39c915c00` | TB ML | `ab3b22f5-9e5b-45eb-8b83-3f54530b36a6` | 0.0182 | 1.9524 |
| `209883ba-5e1b-4347-9fa6-ce902bd33afd` | SF ML | `0f0e3f04-006e-4fe7-8e7e-2a32b3114617` | 0.0185 | 2.4500 |

No challenger is installed. The five-game maximum incremental sample, one selection week, missing event-team outcome mapping, and only nine settled positions in the frozen control snapshot do not support a defensible relaxation. The operational audit independently shows that current selections stop at missing odds before edge or readiness is reached. Consequently there is no challenger identity, no official additional selection list, and no AISP shadow-policy handoff.

Final OOT stayed sealed. No model fit, provider call, AISP write, position mutation, or wagering authority occurred.
