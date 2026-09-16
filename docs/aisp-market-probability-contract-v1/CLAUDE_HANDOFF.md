# Claude handoff — Model Studio market probability contract v1

Model Studio now provides pure probability calculations for immutable paired final-score populations. No exchange package was published and no consumer state was changed. AISP must integrate the library contract or reimplement the documented math inside its own repository.

## Consumer work

1. Select the exact game and forecast revision under AISP’s existing freshness, authority, and decision gates.
2. Verify the source package and its retained joint score population through the sport’s existing importer.
3. Map its cells to `{awayScore, homeScore, count}` and bind sport, game, forecast, model, configuration, package SHA-256, population SHA-256, and draw count.
4. Submit explicitly oriented market legs. Require NFL moneyline tie settlement from the actual market definition.
5. Display win, loss, push, and void probabilities as fractions or format them as percentages only at the UI boundary.
6. Keep sportsbook selection, quote freshness, edge, eligibility, experiment authority, stake, decision, and settlement in AISP.
7. Reject cross-game combinations by default. If AISP exposes research independence, display `INDEPENDENCE_ASSUMPTION` prominently and never give it an empirical draw count.

## Direct support

- MLB controlling unrestricted V18: moneyline, arbitrary run line, arbitrary total, and same-game intersections from 5,000 paired finals.
- NFL M1 exact eligible population: three-way winner, arbitrary spread/total, and same-game intersections from 10,000 paired finals; tie limitation remains visible.
- NBA joint baseline: arbitrary spread/total and same-game intersections from 10,000 paired finals. Published point/Elo alone is unsupported for these queries.
- CFB baseline: arbitrary spread/total and same-game intersections from 10,000 paired finals.

No sport has a retained cross-game joint population.

## Files

- Code: `server/sports_shared/market_probabilities.py`
- Machine matrix: `docs/aisp-market-probability-contract-v1/capability-matrix.json`
- Request/response schemas: `docs/aisp-market-probability-contract-v1/schemas/`
- Orientation and settlement: `docs/aisp-market-probability-contract-v1/ORIENTATION_AND_SETTLEMENT.md`
- Authority/freshness: `docs/aisp-market-probability-contract-v1/AUTHORITY_AND_FRESHNESS.md`
- Errors: `docs/aisp-market-probability-contract-v1/ERRORS.md`
- Synthetic vectors: `docs/aisp-market-probability-contract-v1/fixtures/golden-vectors.json`

This handoff grants no AISP-write, sportsbook, wagering, position, scheduler, or deployment authority. Consumer acknowledgement is absent until AISP records one.
