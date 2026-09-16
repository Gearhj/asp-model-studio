# Orientation, push, tie, and void definitions

All score pairs are ordered `awayScore`, `homeScore`. `home margin = homeScore - awayScore`; `total = homeScore + awayScore`.

For a spread leg, `line` is attached to the selected side. Thus HOME `-3.5` evaluates `homeScore - 3.5` against `awayScore`; AWAY `+3.5` evaluates `awayScore + 3.5` against `homeScore`. The API does not accept an unlabeled “home spread” field because that creates sign ambiguity.

For a total leg, OVER wins above the line and UNDER wins below it. Equality is a push. Integer scores cannot equal a half-point line.

For a HOME or AWAY moneyline, tied score draws require caller-supplied settlement:

- `PUSH`: tie mass is refunded.
- `LOSS`: tie mass loses, such as a two-way market whose rules explicitly say so.
- `VOID`: tie mass is voided. It stays separate from push for downstream disclosure.

A `TIE` moneyline selection wins only on equal scores and loses otherwise.

For a same-game multi-leg state, any losing leg makes the combined state a loss. If every leg wins it is a win. With no loss, void has precedence over push; otherwise any push makes the combined state a push. This does not encode every sportsbook’s parlay reduction rules. AISP must apply the actual quote’s rules after receiving the raw state probabilities.

The fair-price component uses `1 + pLoss / pWin`; push and void are refunds. It returns null when `pWin` is zero. Probability mass must reconcile exactly across win, loss, push, and void.
