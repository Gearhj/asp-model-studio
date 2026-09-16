# Public The Odds API market and cost matrix

Public documentation was inspected on 2026-09-16 without an API key. No API endpoint was called.

| Requested prop | Current market key | Access | Documented current cost | Free-plan qualification |
|---|---|---|---|---|
| Batter hit O/U | `batter_hits` | `/v4/sports/baseball_mlb/events/{eventId}/odds` | unique markets returned × regions; one market in one region costs 1 credit | Current odds and all betting markets are advertised on the 500-credit/month free plan; actual bookmaker/market availability varies. |
| Batter total bases O/U | `batter_total_bases` | Same | Same | Same |
| Batter home runs O/U | `batter_home_runs` | Same | Same | Same |
| Pitcher strikeouts O/U | `pitcher_strikeouts` | Same | Same | Same |

All four markets can be requested together for one event and one region. If all four are returned, documented cost is 4 credits. Empty data costs zero, and the response headers report last/used/remaining credits. Event discovery at `/v4/sports/baseball_mlb/events` is documented as zero quota cost but still requires authentication. The event-markets endpoint costs 1 credit and reports only recently observed keys, not a comprehensive guarantee.

Player props are one-event-at-a-time, mainly US sports/US bookmakers, and coverage may appear closer to game time. Additional markets update at one-minute intervals. Current odds are available on the free plan; historical player-prop snapshots are paid-plan only, available from May 3, 2023 at five-minute intervals, and cost 10 × unique markets returned × regions per event snapshot.

Official sources:

- https://the-odds-api.com/sports-odds-data/betting-markets.html
- https://the-odds-api.com/liveapi/guides/v4/
- https://the-odds-api.com/sports/mlb-odds.html
- https://the-odds-api.com/

No credential was read from AISP or any local environment file. Provider activity: 0 authenticated calls, 0 response bytes, 0 credits, $0.
