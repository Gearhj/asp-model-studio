# CLAUDE_HANDOFF — original V18 totals V1

Package/index: `C:\Users\james\asp-model-exchange\mlb-v18-current\totals-v1\sha256\73d958132a401dbe3748b33dc9983262dd2b4b421ada78932fbac3bf6c0672a7\index.json`
Physical SHA-256: `73d958132a401dbe3748b33dc9983262dd2b4b421ada78932fbac3bf6c0672a7`; **199,269 bytes**.
Sibling `manifest.json` binds every copied file by physical SHA-256 and bytes.
Actual derivative publication: **2026-09-13T17:21:11.715942+00:00**. Original forecast clocks are unchanged.

Schema `MLB_V18_TOTALS_DISTRIBUTION_INDEX_V1`; all probabilities **FRACTION_0_TO_1**.
The existing complete `distributions.totalRuns` PMF is reused byte-for-byte,
including the full scoring tail and extra innings. Read `CONTRACT.md`.
Coverage: **43 distinct games / 44 exact forecast versions**;
latest slate 2026-09-13: **11 distinct supported games**.
Missing slate forecasts and historical/legacy dependencies are explicit in index.
All 5,000 original draws per supported version are used; no inning counters are required.

Use the exact `baselineForecastId`, object hash, canonical identity and gamePk.
Match an already imported ordinary MLB_V18_WHOLE_GAME baseline; never substitute
another version or a SCORE_LIMIT, SURVIVAL or TRANSITION candidate. Reuse
ShadowForecast.distributions.totalRunDistribution. If the baseline is missing,
the dependency is its ordinary daily import; this index does not manufacture it.
For the board, map only the V18 total PMF into existing total-market pricing;
do not fabricate full_game/first_five or coarse >20-tail payloads.

Example: **CIN–MIL 823734**, canonical `3c7a6820-7c95-4e91-87fa-6acb89c013d7`,
forecast `mlb-v18-daily-05f86403fb40fc60600d479b94821a46e17b91471afbf6c8ac3c48e18ceeaeaa`, original **5,000** draws, mean **7.9656**.
Lines below are **illustrative**, not actual recorded sportsbook lines. Fractions:

| Line | Side | pWin | pPush | pLoss |
|---:|---|---:|---:|---:|
| 8.0 | over | 0.408200 | 0.076400 | 0.515400 |
| 8.0 | under | 0.515400 | 0.076400 | 0.408200 |
| 8.5 | over | 0.408200 | 0.000000 | 0.591800 |
| 8.5 | under | 0.591800 | 0.000000 | 0.408200 |

Over wins T>L, pushes T=L, loses T<L; Under reverses win/loss.
At supplied decimal odds D: expected net return per unit stake = pWin*(D-1)-pLoss.
Push-aware fair decimal odds = 1+pLoss/pWin when pWin>0; otherwise unavailable.
Do not substitute conditional non-push probabilities in expected net return.
Claude owns quotes, compatible settlement, pricing, filters and parlay decisions.
The modeled total includes extras and automatic second-base runners; not F5 or regulation-only.

Verify the manifest and exact baseline bindings, then use the existing PMF or the
included pure `line_probabilities(rows, sample_count, line, decimal_odds=None)` helper.
Return an acknowledgement naming the exact index SHA, accepted forecast IDs,
distinct games, actual attachment/import time and missing baselines.
Publication is complete; **no consumer acknowledgement or UI integration is claimed**.


Display rounding: Theater formats expected away/home/total runs independently with JavaScript `toFixed(2)`, after full-precision calculation (SimulationAverageHeader.tsx:30; InningLineScore.tsx:142–144,194; PopulationStatOverlay.tsx:20,48). CIN/MIL means 4.1116/3.8540 display as 4.11/3.85, while the original total 7.9656 displays as 7.97. Adding displayed team means gives 7.96; that 0.01 display difference is rounding, not missing probability mass. Use the complete PMF for line queries.

At the frozen inventory time 17:14:29.907599Z, September 13 missing forecasts were KC–BOS 824708, SEA–ATH 824952, TEX–AZ 825033 and SD–SF 823171, each CHECKPOINT_NOT_DUE in the bound publisher receipt. Their missing dependency is an ordinary V18 forecast; do not force readiness or treat them as totals-counter failures. September 14 entries are a separately dated future slate, not today's missing count. Thirteen September 8 legacy objects retain PMFs but lack their original paired population and separate creation clock; they remain separately disclosed historical lineage rather than replacements for current-source forecasts.

All 37 forecast objects lacking inning counters in the score-limit study are included here with their full original populations. This export includes the original pilot baseline and both distinct versions of game 822682. No baseline or study has been altered. The existing complete PMF is sufficient; the remaining consumer task is the narrow V18 totals mapping and exact-baseline attachment, not another model or provider request.
