# Original V18 totals distribution contract V1

The existing `MLB_V18_DAILY_GAME_FORECAST_V1` field
`distributions.totalRuns` is already the complete empirical mass function.
This export copies those original forecast bytes unchanged and indexes the
existing field; it does not replace the forecast, simulate, or create a new PMF.
The file's other numerical fields and original clocks remain unchanged.

Each row is `{value: integer total runs, probability: fraction from 0 to 1}`.
Absent integer bins have zero probability. All retained integer tail bins count;
never collapse them into an open-ended `>20` bin or infer probabilities from a
middle-80% range, a rounded mean, or independently combined team marginals.
The exact original paired population has `total[i]=awayRuns[i]+homeRuns[i]`.
Every valid original draw is used, with denominator `originalSimulationCount`.
No inning counter or score-limit mask is required. The original CIN-MIL 823734
baseline is 5,000 draws; its separate 4,722-draw score-limited study is unrelated.

For integer and half-run line L:
Over pWin=P(T>L), pPush=P(T=L), pLoss=P(T<L).
Under pWin=P(T<L), pPush=P(T=L), pLoss=P(T>L).
Each triplet sums to one. Half-run pushes are zero because totals are integers.
All probability fields in this contract use FRACTION_0_TO_1, never percent.
Display percentages multiply a fraction by 100 exactly once.

With supplied decimal odds D, expected net return per unit stake is
`pWin*(D-1)-pLoss`; a push refunds the stake. When pWin>0, fair decimal odds
are `1+pLoss/pWin`; otherwise the exported helper returns null with a reason.
Conditional non-push probability pWin/(pWin+pLoss), if used for a no-vig
comparison, is a separate quantity and must not replace raw pWin in EV.
Claude owns market lines, quotes, compatibility, pricing and selections.
Example lines 8 and 8.5 are illustrative, not recorded sportsbook quotes.

Settlement is full-game scoring INCLUDING simulated extra innings, natural
walk-offs, and an automatic runner on second beyond scheduled regulation.
The original simulator's zero-nontermination requirement is enforced.
Match only compatible full-game market rules. This final-total PMF cannot
provide regulation-only/F5 totals or independently establish a parlay's joint
probability. No parlay or selection engine is added here.

Bind by both canonical game ID and MLBAM gamePk, exact baseline forecast ID
`mlb-v18-daily-{FULL_OBJECT_SHA}`, engine MLB_V18_WHOLE_GAME, simulator
V18_WHOLE_GAME_MONTE_CARLO, original population schema and version, N/seed,
source cutoff and immutable source checksums. Never bind by teams/date alone.
Both versions of a game remain distinct; latest-at-inventory is a discovery
hint, not authorization to overwrite an already bound forecast or selection.

The existing AISP daily importer maps this field unchanged to
ShadowForecast.distributions.totalRunDistribution. Its Theater reader exposes
population.total_run_distribution; that PMF remains fractions even though
Theater's winner display uses percentages. Reuse the exact already imported
baseline when present. If absent, import its ordinary baseline through the
existing authorized daily adapter before attaching totals. This derivative
index is NOT itself an ordinary daily-forecast importer input.

For Over/Under, Overs Only and Parlay Watch, add only the narrow V18 mapping
from totalRunDistribution to the existing total-market pricing functions.
The generic board's distributions.full_game/first_five schema and old coarse
tail reader are different contracts; do not manufacture those payloads.
All original authority settings remain unchanged; this package grants none.

Index exportCreatedAtUtc and publication receipt publishedAtUtc are actual
new derivative clocks. originalCapturedAt/originalForecastCreatedAt and any
bound prior slate receipt keep their original meanings. A later slate receipt
is not represented as the first publication clock. A historical derivative
does not establish pregame availability or repair a missed deadline.

Verify package manifest file SHA-256/byte counts on delivered bytes without
newline normalization. Then verify the forecast file bound by each index row,
PMF mass and N, and exact baseline identity. The producer verification also
compares every bin against all paired totals and their full-precision mean.
Rounding for UI display must happen only after this calculation.
Return a consumer acknowledgement with index SHA, exact accepted forecast IDs,
actual import/attachment time, distinct games and precise rejected dependencies.
Publication alone is not import or end-to-end UI confirmation.
