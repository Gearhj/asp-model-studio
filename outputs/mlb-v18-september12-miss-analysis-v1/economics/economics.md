# September 12 decision economics

All seven virtual positions are now settled: **1 win, 6 losses, net $-12.78 on $14.21 staked**. Only five funded games have eligible governed final-score revisions; PHI's loss and CWS's win are ledger settlements and remain unavailable for governed winner/run scoring.

| Cohort | Stake | Expected wins raw / adjusted | Expected net raw / adjusted | Realized wins | Realized net |
|---|---:|---:|---:|---:|---:|
| All seven original decisions | $14.21 | 3.5660 / 3.4260 | $1.7627 / $1.1006 | 1/7 | $-12.78 |
| Five governed finals / earlier five losses | $10.99 | 2.5112 / 2.4112 | $1.3234 / $0.8020 | 0/5 | $-10.99 |
| Two later settlements, final revisions unavailable | $3.22 | 1.0548 / 1.0148 | $0.4393 / $0.2985 | 1/2 | $-1.79 |

Expected wins and P&L require no independence assumption. They are conditional on the supplied probabilities being correct. Saved adjustments subtract 2 percentage points for starter evidence; they are not a validated recalibration.

| Selection | Stake / price | Raw p | Saved adjusted p | Offered break-even | Adjusted minus break-even | Expected net raw / adjusted | Settlement net | Governed final |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| NYY | $1.04 / -160 | 63.86% | 61.86% | 61.54% | +0.322 pp | $0.0392 / $0.0054 | $-1.04 | revision 1 |
| PIT | $2.48 / +110 | 52.62% | 50.62% | 47.62% | +3.001 pp | $0.2604 / $0.1563 | $-2.48 | revision 1 |
| SF | $2.49 / +160 | 46.38% | 44.38% | 38.46% | +5.918 pp | $0.5126 / $0.3832 | $-2.49 | revision 1 |
| LAA | $2.49 / +115 | 49.80% | 47.80% | 46.51% | +1.288 pp | $0.1760 / $0.0690 | $-2.49 | revision 1 |
| KC | $2.49 / +195 | 38.46% | 36.46% | 33.90% | +2.562 pp | $0.3351 / $0.1882 | $-2.49 | revision 1 |
| PHI | $2.48 / +126 | 51.50% | 49.50% | 44.25% | +5.252 pp | $0.4065 / $0.2944 | $-2.48 | unavailable |
| CWS | $0.74 / -107 | 53.98% | 51.98% | 51.69% | +0.290 pp | $0.0328 / $0.0041 | $0.69 | unavailable |

Offered break-even is 1 / the stored position decimal price. No-vig disagreement is separately retained in JSON. The saved policy edge is adjusted p minus no-vig p. CWS used stored decimal 1.9346; its exact source quote was 1.9345794392523366. Both are preserved. The ledger rounded its gross payout to $1.43.

Assuming both independent games and true supplied probabilities, exact enumeration gives:

| State / event | Raw probabilities | Saved adjusted probabilities |
|---|---:|---:|
| Earlier five: all five lose | 2.84% | 3.47% |
| Current seven: at most one win | 5.44% | 6.74% |
| Current seven: net P&L at most -$12.78 | 1.38% | 1.75% |

These are conditional illustrations, not proof of bad luck or model correctness. Without independence, the same raw marginals permit the earlier all-five-loss probability anywhere from 0.00% to 36.14%; model uncertainty makes even those marginals uncertain. No significance threshold or policy change is selected.

Per-game numerical Monte Carlo SE is approximately 0.7 percentage points if the 5,000 draws are independent. This is separate from uncertainty about whether V18 is accurate. No game-level dependence estimate, calibrated value interval, or superiority claim is available.

Evidence clocks: original decision capture 2026-09-13T01:58:22.169884+00:00; Claude handoff 2026-09-13T02:10:58.934301+00:00; settlement refresh 2026-09-13T14:38:37.414336+00:00. Exact governed final source clocks and all physical hashes are in economics.json. The earlier Claude handoff still showed two positions open; no original artifact was overwritten.

Reproduce offline:

`.venv/Scripts/python.exe -B outputs/mlb-v18-september12-miss-analysis-v1/economics/analyze_economics.py`

capture_settlements.py documents the one bounded read-only settlement refresh; it is not needed for offline reproduction. No provider, model, simulation, policy or AISP write occurred.
