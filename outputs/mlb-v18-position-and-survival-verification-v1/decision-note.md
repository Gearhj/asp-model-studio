All seven funded positions used the exact original Studio V18 forecasts. The verified observation is correct frozen attribution followed by five unfavorable results, with two positions still open at the saved assessment. No artifact, home/away orientation or selected-quote mismatch was found. A recurring modeling weakness remains unestablished; no model or policy change follows from this slate.

| Frozen V18 cohort | Governed finals | Winner log loss | Brier | CRPS home / away / total / margin |
|---|---:|---:|---:|---|
| All eligible September 12 games | 9 of 15 | 0.711244 | 0.258561 | 1.494 / 1.794 / 2.313 / 2.283 |
| Funded-position subset | 5 of 7 | 0.712525 | 0.259146 | 1.140 / 2.280 / 2.093 / 2.738 |

These scores use the original retained 5,000 draws per forecast and latest eligible governed finals, selected after freezing all 15 forecast identities. Six slate games remain unscored. The draws measure simulation precision, not independent games. Exact forecasts, clocks, distributions and score receipts are bound by the [slate summary](C:/Users/james/asp-model-studio/outputs/mlb-v18-position-and-survival-verification-v1/slate-assessment-summary.json), SHA256 `240c8e8d1f33c48f79a82b0abdec399e7b2d864a25f967670f2592ac52c3e0b5`.

The first stored position was **NYY ML −160**, not NYM. Game **823496** is NYM away at NYY home; the final is **NYM 12–NYY 2**, revision 1, outcome ID `0a69c509-90cd-43dc-a8d5-19b199a43a11`. Game **824712** is KC away at BOS home; the final is **KC 1–BOS 5**, revision 1, outcome ID `858406c1-d709-48df-9cdb-7192c9fa57e3`. Home–away 5–1 and away–home 1–5 describe the same KC result. The correctly oriented scoring inputs need no replacement. Both identities are retained in the [governed final receipt](C:/Users/james/asp-model-studio/outputs/mlb-v18-position-and-survival-verification-v1/slate-assessment-final-read.json), SHA256 `b464080840ae6f71afeac99546bbfc1ffe7b8214279831c5d5b3429edb174055`.

The [seven-position table](C:/Users/james/asp-model-studio/outputs/mlb-v18-position-and-survival-verification-v1/positions/position-audit.md) gives each selected-side probability, offered price, break-even probability and policy edge. Stored `decision.edge` is raw model probability minus offered-price break-even. The actual policy used `(model probability − 0.02 probable-starter penalty) − no-vig market probability`, plus positive adjusted expected value. These are distinct quantities. The CWS policy decimal-price rounding does not change its positive adjusted-EV result.

All 14 tested ordered lineups matched their latest retained observations by decision time, and all 14 starter identities matched saved qualification evidence. However, complete invalidation/supersession history, changes after placement through cutoff/start, and other feature-vintage corrections were not independently verified. Correct attribution does not establish that inputs were never stale or invalidated. The exact coverage limit is in the [invalidation note](C:/Users/james/asp-model-studio/outputs/mlb-v18-position-and-survival-verification-v1/positions/invalidation-coverage-note.json).

V18 had higher observed winner losses than the matched earlier Gen 1 and market snapshots. Gen 1 remains a **secondary descriptive published-morning comparison**: its historical operational usability is unknown, with stale-roster, 27 missing-feature and provisional-lineup flags. It is not an independently validated usable benchmark. Gen 1 horizons were 7.15–10.14 hours before start versus V18 1.63–2.64 hours; market snapshots spanned 2.65–24.03 hours and were not closing quotes. Preserve these qualifications from the [Gen 1 eligibility note](C:/Users/james/asp-model-studio/outputs/mlb-v18-position-and-survival-verification-v1/slate-assessment-gen1-eligibility.json); no superiority claim is supported.

The six authorized history reads completed: **6 calls, 940,466 bytes, $0**. Cumulative usage is **107 calls, 34,092,341 bytes, $0**. Hughes now has 11 eligible starts and Jobe 16, with their histories complete through September 11 and no unresolved protected appearances in that prefix. September 12 still requires a genuine census after **2026-09-13T04:00:00Z**. Current supported survival executions **0**, publications **0**, new fallbacks **0**; there is no new survival forecast handoff or import confirmation.

Implementation commit: `98a0cac709351722b2ec52459a20a524f0301b96`. The same-task heartbeat `complete-first-supported-mlb-survival-pair` continues the authorized census and existing COL–DET **824225** comparison. It preserves the original **2026-09-13T15:55:00Z** deadline and ordinary publisher locks, and stops on the first supported publication, terminal failure or expiry. [Execution instructions](C:/Users/james/asp-model-studio/outputs/mlb-v18-position-and-survival-verification-v1/future-execution.md) retain the exact commands and prerequisites. The producer verification handoff is being packaged separately; this note is not a forecast publication receipt.

Reproduce the frozen assessment without refreshing finals or simulating:

```powershell
.venv/Scripts/python.exe scripts/assess_mlb_v18_frozen_slate_20260912_v1.py --score
.venv/Scripts/python.exe scripts/assess_mlb_v18_frozen_slate_20260912_v1.py --comparators
.venv/Scripts/python.exe -B outputs/mlb-v18-position-and-survival-verification-v1/positions/verify_positions.py
```
