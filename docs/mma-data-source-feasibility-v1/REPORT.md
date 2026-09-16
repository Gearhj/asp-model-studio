# MMA data-source feasibility — UFC Generation 1

**Disposition: `GO_WITH_CONDITIONS`.** A low-cost UFC research prototype is feasible, but a production-quality pipeline is not yet authorized or proven. The least-cost defensible stack is: a version-pinned CC0 historical UFC dataset for development, API-Sports MMA as the first structured schedule/result/stat candidate after a bounded free-key test, The Odds API for timestamped current moneylines, and TheSportsDB only as a card-level cross-check. The unresolved conditions are historical-source provenance review, a real API-Sports coverage/freshness test, a lawful automated source for weigh-ins and missed weights, and an operational result feed proven to meet the five-minute target.

No model was built or fitted. No AISP, exchange, deployed owner, scheduler, or sealed Scotty artifact was read or changed. The current source manifest remains `PLANNED`, non-selectable and non-executable.

## What is established

### Proven

- The work branch was created from clean canonical source-development commit `8067db9f338fde006e2f95ed92646457ab567f69`, not from a deployment or Scotty branch.
- No MMA/API-Sports/SportsGameOdds/The Odds API/Sportradar credential was found in the checked Model Studio and AISP local environment files or the process environment. This does not prove that James has no provider account elsewhere.
- Three permitted TheSportsDB V1 calls used the public key, cost USD 0, and returned 18,325 response bytes. The 2026 season response was capped at 15 card records. The next-UFC response identified `idEvent=2541770`, `UFC 331 Van vs Pantoja 2`, `2026-09-19T21:00:00`, but its event object had no structured home/away fighters. It is therefore not a bout authority.
- UFC.com terms prohibit page scraping, robots and automated extraction. Tapology and Sherdog also prohibit or materially restrict automated collection/aggregation.
- The Odds API terms explicitly permit indefinite retention, model training, analytics and display of derived values, while prohibiting raw-feed resale.

### Documented but untested

- API-Sports advertises all MMA endpoints on a free 100-request/day plan and paid plans from USD 10/month. Indexed documentation describes fights, fighters, categories, results, fighter statistics and odds, but no authenticated MMA response was tested.
- The Odds API documents `mma_mixed_martial_arts`, a 500-credit free plan, 60-second pre-match and 40-second in-play featured-market refreshes, and paid MMA history beginning 2020-06-06. MMA score/result support and replacement identity behavior were not tested.
- Sportradar documents UFC and Dana White's Contender Series schedules, stable event IDs through corrections, competitor merge mappings, created/updated/removed feeds, live summaries with one-second cache TTL, and round statistics. Its trial is 30 days, 1,000 calls per rolling 30 days and 1 QPS; production requires a contract and sales quote.
- A Kaggle dataset labeled CC0 contains nine files, 228 columns and 11.66 MB covering UFC events, fighters and fights from 1994–2025. A 2026 peer-reviewed paper reports using it and independently rechecking 423 of 8,461 retained bouts without a processing discrepancy in selected fields.

### Inferred

- The CC0 dataset is a plausible development seed, but its CC0 label does not itself prove the uploader could license every field originally collected from UFCStats. A rights/provenance review remains prudent before commercial use.
- API-Sports' free quota can almost sustain one 15-minute schedule poll around the clock (`96/day`), but leaves only four requests for results, statistics, retries and validation. The USD 10 Pro plan is the first operationally credible quota if its rights and data pass testing.
- Five UFC cards/month with one US-region h2h poll every ten minutes for six hours costs about `180` The Odds API credits. Adding one daily event-discovery request gives about `210`, within 500 credits. Result polling should use another feed; five-minute result polling throughout five six-hour cards would consume another `360` credits and exceed the free budget.

### Unknown

- API-Sports' actual UFC historical depth, every-bout completeness, promotion list, free-versus-paid response differences, identity stability, correction behavior, and measured latency.
- Whether The Odds API scores endpoint covers MMA and how IDs behave across opponent replacements.
- A lawful automated free source for official weigh-ins/missed weights.
- UFCStats' separate automation/reuse permission; none was located.
- Sportradar production price, retention, model-training and derived-publication rights.
- SportsGameOdds UFC entitlement for the existing account. Its UFC page suggests Amateur access while the general free-plan table's eight leagues omit UFC.

## Ranked recommendation

| Rank | Source | Use | Decision |
|---:|---|---|---|
| 1 | The Odds API | Current and in-play moneylines | Best-documented rights; obtain a free key and test UFC identity/results behavior. |
| 2 | API-Sports MMA | Schedule, bouts, fighter identity, results and statistics | Cheapest structured operational candidate; conditional on free-key validation and rights review. |
| 2 | CC0 UFC 2025 Kaggle dataset | Historical development seed | Admit only as a versioned reconstructed-history source; no point-in-time revision claims. |
| 3 | Sportradar MMA | Professional benchmark/fallback | Strongest documented change and live-stat contract; trial is not production and price is unknown. |
| 4 | TheSportsDB | Card/date/result cross-check | Proven card-level only; crowd-sourced and incomplete for bouts. |
| 5 | SportsGameOdds | Possible operational odds/settlement | Do not train or retain broadly until entitlement and ML/derivative restrictions are cleared in writing. |
| 6 | UFCStats | Historical reference | Permission-required; no scraper or production dependency. |
| 7 | UFC.com | Manual official reconciliation | Official human-readable evidence only; automated collection is prohibited. |
| 8 | Tapology/Sherdog/BestFightOdds/FightMatrix | Broad-promotion reference | Reject as automated dependencies without a licensed API/data agreement. |

Expanding Generation 1 beyond UFC would materially weaken the architecture. Sportradar's documented feed is UFC/DWCS, SportsGameOdds documents UFC, explicitly licensed historical datasets are UFC-centric, and TheSportsDB's broader promotion records are crowd-sourced. The Odds API's mixed-MMA key and API-Sports' competition marketing may broaden odds/schedules, but coverage has not been enumerated. PFL, ONE, RIZIN and Cage Warriors should be a later, separately validated scope.

## Source-of-record architecture

| Domain | Primary candidate | Fallback | Fail-closed condition |
|---|---|---|---|
| Historical bout and round statistics | Versioned CC0 dataset after provenance review | Licensed Sportradar history | No source version/license receipt or irreconcilable bout identity |
| Upcoming schedule and bout identity | API-Sports after validation | Sportradar production; TheSportsDB card check only | No structured bout IDs or capture newer than freshness threshold |
| Card changes/replacements | Append-only API-Sports snapshots and diffs | Sportradar created/updated/removed feeds | Opponent change without predecessor/successor lineage |
| Fighter identity | Source IDs mapped to canonical fighter ID | Sportradar merge mappings; reviewed alias queue | Duplicate/ambiguous alias remains unresolved |
| Weigh-ins/missed weight | Licensed feed or governed human capture of official evidence | null | Missing remains explicit; never infer from contracted class |
| Odds | The Odds API h2h, one selected region | SportsGameOdds only after rights/entitlement clearance | Source update older than 10 minutes |
| Result/method/round/time | API-Sports after measured validation | Sportradar; governed manual official reconciliation | Conflict or result more than five minutes stale is quarantined |
| Settlement | Same frozen result revision used for scoring | second-source reconciliation | No single governed final identity |

Every capture is immutable and stores the request identity, physical SHA-256, byte count, retrieval time, source-published/updated time when supplied, license/terms receipt, schema fingerprint and correction lineage. Source event time and observed time are separate. Feature rows bind exact captures and a cutoff; labels live in a separate result table.

An opponent replacement closes the old bout version as `REPLACED`, creates a successor bout identity and links both. A weight-class or scheduled-round change appends a new version when participants remain the same. A cancellation is never converted to a loss or no-contest. Forecasts may use only versions observed before their cutoff.

## Identity and entity resolution

1. Preserve every source identifier and raw display name; never use a normalized name as the primary key.
2. Normalize Unicode, punctuation, spacing and known transliterations only to generate candidates.
3. Score candidates using date of birth, height/reach, nationality, division and prior opponent overlap; never merge on name alone.
4. Keep direction-neutral bout identity based on promotion event plus the unordered fighter pair, then store red/blue or home/away orientation as a versioned attribute.
5. Route collisions, fighter merges, replacements and reversed participants to a review queue. Record the decision, evidence and reviewer.
6. Preserve aliases with validity intervals so a later name correction does not rewrite old captures.

## Leakage-safe historical bout table

The modeling row is one scheduled bout at one declared pre-fight cutoff. It contains canonical event/bout/fighter IDs, exact schedule version, participants, class, rounds, title status, venue, source captures and missingness. Fighter features are reconstructed from bouts completed strictly before the cutoff. Career totals, records, rankings and averages exposed on a modern fighter page are not historical facts unless a vintage was captured then.

Rolling strikes, takedowns, submissions, control, finish rates, opponent strength, recent form, layoff, prior rounds and experience are derived chronologically. Weigh-in data is available only to forecasts after the weigh-in capture. Market probability uses the last eligible timestamped snapshot, never a later closing line. Short notice is supported only by versioned replacement lineage, not by hindsight from the final card. The full field disposition is in `FIELD_COVERAGE_MATRIX.json`.

## Rights and restrictions

| Source | Automation | Retention/modeling | Derived/public use | Risk |
|---|---|---|---|---|
| The Odds API | API allowed | Explicit indefinite retention and ML use | Derived values allowed; raw resale prohibited | Low–moderate |
| API-Sports | API by plan | Project/app use described; MMA training not explicit | Competition publication rights remain user's responsibility | High until reviewed |
| SportsGameOdds | API by entitlement | Termination deletion and ML/derivative restrictions | Written clarification needed | High |
| TheSportsDB | Official API allowed | Copy/modify API response allowed | Paid plan required for published app; third-party rights remain | Moderate |
| UFC.com | Automated scraping prohibited | Commercial database construction prohibited | Written permission needed | High |
| UFCStats | No supported API or separate permission located | Permission-required | Permission-required | High |
| CC0 Kaggle dataset | File download | CC0 label and ML intent | Upstream provenance still needs review | Moderate |
| Sportradar | Trial/production API | Contract-specific | Contract-specific | Unknown until quote |

This is an engineering rights assessment, not legal advice.

## Freshness evidence

| Source | Schedule/change | Odds | Results/stats | Evidence |
|---|---|---|---|---|
| API-Sports | Platform says as often as 15 seconds | same platform claim | same claim | Marketing, untested; no MMA SLA proven |
| The Odds API | event list; no MMA change SLA | 60s pre-match, 40s in-play featured markets | scores about 30s where sport supported | Documented; MMA behavior untested |
| SportsGameOdds | Amateur 10m, Rookie 3m, Pro sub-minute | same | same | Documented plan cadence; UFC entitlement untested |
| TheSportsDB | no UFC SLA | none | no UFC live guarantee | One current card matched; lag not measured |
| Sportradar | created/updated/removed feeds; 24h change window | separate product | live summary cache TTL 1s | Documented, untested |
| UFC.com/UFCStats/open dataset | no usable SLA | n/a | n/a | Not an authorized automated operational feed |

No tested source currently proves all four desired latency targets. Odds can plausibly meet ten minutes on the free The Odds API tier. The remaining targets are conditions on the API-Sports POC or a paid Sportradar contract.

## Operating budgets

### Free prototype

- The Odds API: `5 cards × 6 hours × 6 h2h polls/hour = 180 credits`; 30 daily discovery calls makes `210/500`, leaving 290 for retries and bounded validation.
- API-Sports: continuous 15-minute schedule/change polling is `96/100 requests/day`, leaving inadequate margin. Use free access only for a two-card validation, not dependable operation.
- TheSportsDB: at most one daily card cross-check plus bounded result checks, well under 30 requests/minute; never treat it as authoritative.
- Historical seed: one future 11.66 MB version-pinned download after explicit acquisition authorization and provenance acceptance.

Estimated prototype subscription cost is **USD 0/month**, but it does not yet meet the full operational contract. No key was created and no dataset was downloaded here.

### Paid envelope

- API-Sports Pro: USD 10/month, 7,500 requests/day.
- The Odds API: remain free for bounded current h2h; USD 30/month for 20,000 credits and historical access if later authorized.
- Combined practical low-cost envelope: **USD 10/month current operations**, or **USD 40/month** with paid historical odds.
- SportsGameOdds: USD 99/month Rookie or USD 299/month Pro; not recommended until rights/entitlement are cleared.
- Sportradar: sales quote required. TheSportsDB pricing pages conflict and it adds no critical bout authority.

## Bounded proof of concept

No calls in this plan are authorized by this report. After James obtains free keys and separately authorizes the POC:

1. Pin the CC0 dataset version and metadata; download at most 20 MB once. Validate IDs, duplicates, missingness and chronological reconstructability without model fitting.
2. API-Sports: maximum 80 requests across two UFC cards. Capture categories, fighters, fights, results, fighter statistics and odds; poll the next card every 15 minutes for a six-hour window and around one known card revision. Retain only if terms review permits.
3. The Odds API: maximum 80 credits across the same cards, one region and h2h only. Verify event ID stability, fighter orientation, draw representation, bookmaker timestamps and one in-play transition.
4. Compare three completed cards (UFC Paris 2026-09-05, Noche UFC 2026-09-12, UFC 330 2026-08-15), upcoming UFC 331, a cancellation/missed-weight case (Road to UFC 2026-08-28), and UFC 294 no-contests. The sample contains decisions, KO/TKO and submissions.
5. Measure first-seen schedule changes, official result lag, round-stat lag, bout completeness, identity joins, method/round/time agreement and corrections. Use retrieval clocks, not page dates, for measured latency.
6. Acceptance: 100% scheduled-bout identity after review, at least 99% completed-bout result agreement, no unresolved opponent replacement, 95th-percentile change/result/stat lags within 15/5/15 minutes, and odds age at capture at most ten minutes. Rights must allow retention, internal modeling and derived forecast publication.
7. Stop after two cards. If API-Sports fails, request a Sportradar quote and contract terms; do not widen scraping.

## Required actions and conclusion

James must create or identify a free API-Sports account/key and a free The Odds API key, accepting each provider's terms personally; no credit card is documented as required for the free tiers. Before data acquisition, approve the exact POC ceilings above and the CC0 dataset version. Obtain written clarification from API-Sports on retention, internal model training and derived forecast publication. SportsGameOdds needs both UFC entitlement confirmation and a written ML/derived-use clarification before use.

The decision is `GO_WITH_CONDITIONS`: proceed to a bounded, no-model data POC once those keys and permissions exist. Do not begin ingestion, fitting, AISP integration or scheduling from this report.

## Source list and call accounting

Primary sources consulted are linked in `PROVIDER_MATRIX.json`; notable supporting sources include the [CC0 dataset](https://www.kaggle.com/datasets/aminealibi/ufc-fights-fighters-and-events-dataset), its [peer-reviewed use](https://doi.org/10.1186/s13102-026-01804-8), [UFC terms](https://www.ufc.com/news/terms-use), [TheSportsDB documentation](https://www.thesportsdb.com/documentation), [The Odds API terms](https://the-odds-api.com/terms-and-conditions.html), [API-Sports terms](https://api-sports.io/terms), [SportsGameOdds terms](https://sportsgameodds.com/terms), and [Sportradar MMA documentation](https://developer.sportradar.com/mma/reference/mma-overview).

Provider API calls: TheSportsDB 3 successful requests, 18,325 physical response bytes, USD 0. API-Sports 0; SportsGameOdds 0 objects/requests; The Odds API 0 credits; Sportradar 0; paid calls 0. Public documentation and webpage reads used the research browser, were not retained as provider payloads, and the browser did not expose reliable physical byte counts.

Reproduce the local consistency checks with:

```powershell
python docs/mma-data-source-feasibility-v1/scripts/validate_mma_feasibility.py
```
