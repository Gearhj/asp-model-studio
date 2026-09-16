# Paired starter-duration pilot: current-input blocker

## Actual result

**15 upcoming games found; 0 eligible pairs published; 15 skips; 0 saved pairs awaiting finals; 0 scored pairs. The prospective pilot is blocked, not complete.** The two-arm producer and scorer were implemented and invoked, but no current game passed the HGB input gate. No game-level performance comparison is available.

Starting branch/HEAD: `codex/mlb-starter-survival-hierarchical-pa-v1`, `2243a1cac73e2924e8902f54f8f8850ba4110499`. Delivery branch: `codex/mlb-starter-duration-paired-research-v1`. Unrelated tracked and untracked operational work remains untouched and outside this commit.

### Actual timestamps and game accounting

All times below are UTC. The initial bounded local inspection found all 15 September 11 slate games before the first start. The immutable declaration was written at **2026-09-11 18:18:23.013136**, after PIT–CHC's 18:15 deadline; that game was not backfilled. HGB current-history evidence was already unsupported at the initial check. The first dispatcher invocation completed at **18:18:34.752483**. The second, after fixing the ingestion-clock check, completed at **18:22:18.870264**, again with zero pairs. The scorer ran at **18:19:44.912523**, with zero saved pairs and therefore no outcome connection/query.

For each still-open game, `H+L+V` means all of:

- `CURRENT_ELIGIBLE_START_HISTORY_AUTHORITY_UNAVAILABLE` for both starters;
- `AWAY_CURRENT_GAME_ORDERED_LINEUP_UNAVAILABLE` and `HOME_CURRENT_GAME_ORDERED_LINEUP_UNAVAILABLE`;
- `COMPLETE_CURRENT_V18_PRODUCER_OBJECT_UNAVAILABLE`.

Reasons overlap; they are not additive game counts. These are the actual 18:22 capture results, not a claim that lineups will remain unavailable later.

| Away–home | Scheduled start | Pair deadline | Actual disposition |
|---|---|---|---|
| PIT–CHC | Sep 11 18:20 | 18:15 | `PREGAME_DEADLINE_CLOSED_NO_BACKFILL` |
| COL–DET | Sep 11 22:40 | 22:35 | H+L+V |
| LAA–WSH | Sep 11 22:45 | 22:40 | H+L+V |
| NYM–NYY | Sep 11 23:05 | 23:00 | H+L+V |
| BAL–TOR | Sep 11 23:07 | 23:02 | H+L+V |
| KC–BOS | Sep 11 23:10 | 23:05 | H+L+V |
| LAD–MIA | Sep 11 23:10 | 23:05 | H+L+V; away starter identity/timestamp unavailable |
| HOU–TB | Sep 11 23:10 | 23:05 | H+L+V |
| PHI–ATL | Sep 11 23:15 | 23:10 | H+L+V |
| CIN–MIL | Sep 11 23:45 | 23:40 | H+L+V |
| CLE–MIN | Sep 12 00:10 | 00:05 | H+L+V |
| CWS–STL | Sep 12 00:15 | 00:10 | H+L+V |
| SEA–ATH | Sep 12 01:40 | 01:35 | H+L+V |
| TEX–AZ | Sep 12 01:40 | 01:35 | H+L+V; home starter identity/timestamp unavailable |
| SD–SF | Sep 12 02:15 | 02:10 | H+L+V |

Canonical event IDs, source IDs, team identities and per-side evidence are retained in the declaration and handoff. No pair creation/freeze timestamp, win probability, score comparison, or signed performance difference is reported because none exists. Missing markets are not a forecast-evaluation gate.

## Narrow source dependency, not the deferred PA-history repair

The fitted HGB uses `homePitcher`, `calendarMonth`, `priorStartCount`, `priorStartBfMean`, `daysRest`, `historyMissing`, and evolving `bf`. Its prior summaries mean **all strictly earlier eligible starts since 2023**, under the frozen start eligibility definition. The cold-start branch is valid only for verified zero eligible starts in a complete history universe. An absent feed cannot legitimately set `historyMissing=true`.

The reusable certified start ledger ends September 30, 2024. Local FD1 transition evidence and AISP's read-only governed starter history extend through September 28, 2025: **4,860 started-pitcher rows across 2,430 games; zero 2026 rows**. The 2025 material is a source candidate, not an already-certified eligible-start projection. Current V18 source captures include SCHEDULE and STATCAST through September 10, 2026. Last-250-PA windows are not complete starter stints. Full pitch/PA records do not authenticate the complete declared-starter, substitution and non-pitch event ledger needed to reproduce the fitted start exclusions. Annual games-started and combined starter/reliever BF are not equivalent inputs.

Smallest missing source: **2026 completed-game declared-starter identity, attributed BF, and relevant substitution/non-PA eligibility evidence (or an equivalent certified ledger), scoped to slate starters, with original completion and availability clocks**. Append a compatible 2025 projection and the existing 2023/24 history. No model refit, new duration model, or shared historical PA-feature reconstruction is necessary. Unknown source coverage, mid-PA ambiguity, suspended games and the original hold must remain explicit exclusions.

Evidence: [bounded current-input findings](../outputs/mlb-starter-duration-paired-research-v1/current-starter-input-evidence.json), SHA-256 `83b4927c27fa9c4f9395619340ff16a4e314e37738fa520251890e905fcee286`.

Exact intake contract: [required starter-history export](../outputs/mlb-starter-duration-paired-research-v1/required-starter-history-export-contract.json), SHA-256 `a651010a8f279cf2a3ce5538fdf5b95ac2e40cfaca4ea9491341a2a578962685`. This is a required contract, **not acquired evidence**. The manifest binds source rights, identities, complete coverage, exclusions, original clocks and checksummed rows. Current retrospective retrieval would not become a historical pregame vintage. Sealed or mixed evaluation payloads are not accepted.

## Reuse decision and scientific interpretation

The [bounded reuse table](MLB_STARTER_DURATION_PAIRED_REUSE_V1.md) covers four named repositories, one unsuccessful fifth repository inspection, and Spencer's article. No external implementation was adopted or executed. Existing Chadwick identity authority and local immutable captures were reused; the alternatives would add a different PA model, ingestion dependency or unfitted duration method. The review stayed below the five-repository/90-minute limit. Three cold-start/MiLB questions were recorded as backlog only.

The frozen HGB's BF-distribution results versus pooled empirical duration and conditional removal scores versus the old hook remain distinct component evidence. Neither demonstrates improved full-game forecasts. The original selection, calibration and [accepted results](MLB_STARTER_SURVIVAL_HIERARCHY_RESULTS_V1.md) are unchanged.

## Implemented, repeatable execution path

The reference preserves frozen V18 PA, transition, calibration, lineup, relief mixture and scoring mechanics. Only the challenger starter-removal rule changes. The selected HGB artifact remains `f64f82b4fadf35acd3418bc298548c48bb73cf624fe8c70ba01a87c33e8d2370`; frozen simulator source remains `d9e5151141c697d6d8080e47c3c50ebfc5297764155a7f16de455152939bcac7`.

The adapter applies calibrated `REMOVAL / (CONTINUE + REMOVAL)` after supported BF>=1, at the next defensive opportunity. The game simulator alone owns GAME_END. It never draws a second termination event, predicts a BF-zero removal, re-enters a removed starter or uses actual future hook/run data. Anonymous relief-staff representation is shared and is **not measured bullpen availability**.

The declaration freezes **5,000 draws per arm**, seed **20260907**, 64-draw mechanics checks repeated twice, four native workers, at most one numerical attempt per game and no automatic numerical retries. Separate PA/advancement/hook streams preserve reference identity and within-arm repeatability. A real eligible publication must reload the frozen artifacts, reproduce initial PA probabilities and reproduce all four saved reference-population arrays exactly. Both arms must finish and become discoverable before start minus five minutes; partial or late artifacts are not published.

The small one-shot dispatcher has an exclusive research lock, STOP-file checks, bounded tick/attempt gates, production-lock deferral and immutable/idempotent pair reuse. **No research recurring task was installed.** There were two observed substantive eligibility invocations, not a claim of unattended paired forecasting. The existing pinned production publisher was not replaced. The STOP path is `outputs/mlb-starter-duration-paired-research-v1/STOP`.

After the required certified input pointer exists and the live producer has complete compatible participants, execute from Model Studio:

```powershell
.\.venv\Scripts\python.exe scripts/run_mlb_starter_duration_paired.py tick --declaration outputs/mlb-starter-duration-paired-research-v1/objects/sha256/b3f6debf668aba1cafbe308489255772a593e9d03532d5b3097f101af32bd19b/declaration.json
.\.venv\Scripts\python.exe scripts/run_mlb_starter_duration_paired.py export
.\.venv\Scripts\python.exe scripts/run_mlb_starter_duration_paired.py score
```

This declaration cannot backfill expired games. A later date requires a new pre-outcome declaration from a legitimate current capture. Do not keep retrying an expired slate or infer source refresh from a new publication timestamp.

The scorer reads only persisted finals for saved, already-started pairs, retains corrected-final identities, and keeps one latest result per pair. It implements winner log loss/Brier, team/margin/total errors, marginal CRPS, joint energy score and interval coverage; actual starter BF/outs require their own final source lineage. Paired simulation uncertainty is separate from across-game sampling uncertainty. The synthetic scoring test is not an observed pilot result.

## Handoff and exact next action

Actual exchange index: `C:\Users\james\asp-model-exchange\mlb-starter-duration-research-v1\current.json`.

- Index SHA-256: `747352b15b01371284fdaae37b7cd82b9b843055320cc7f59a1c7b1fb9578521`; 12,955 bytes.
- Latest [local skip-only handoff](../outputs/mlb-starter-duration-paired-research-v1/objects/sha256/a20e96e469b041e95cdb040e8764b26114175765c39b8b6e3e8229653afadbf8/aisp-paired-handoff.json): SHA-256 `a20e96e469b041e95cdb040e8764b26114175765c39b8b6e3e8229653afadbf8`; 13,270 bytes.
- Seventeen copied research artifacts verified with zero byte-count/hash failures. `pairCount=0`, `NO_FORECAST_IMPORT_WHILE_PAIR_COUNT_ZERO`.
- Original first handoff, declaration, input captures and empty scoring receipt remain immutable.

**Next Model Studio action:** supply the narrow source-backed completed-start ledger described above, certify its compatible history projection, then run the existing dispatcher only for still-open eligible games. Obtaining the missing source is a distinct intake action; the pilot did not call a provider or invent a proxy.

**Exact future Claude instruction:** “Read `C:\Users\james\asp-model-exchange\mlb-starter-duration-research-v1\current.json`. While `pairCount=0`, import no forecasts. Once valid pairs exist, resolve research descriptors using `artifactsBySha256`, verify bytes/hashes, canonical event IDs and both-arm pregame receipts, then import the two precomputed arms as separate research-only evidence. Do not execute models or change the champion, policy, thresholds, positions, settlements or wagering authority.”

## Focused verification and boundaries

Seven focused tests passed: three paired mechanics/orientation/timing tests, one current-input/clock regression, one scorer/lineage test and two publication/reuse/deadline tests. Synthetic positive-publication tests do not count as current forecasts. The reference test exactly matched the frozen implementation's score arrays and complete 64-draw traces. Hash verification covered the actual exchange copy.

The [actual frozen-HGB reload/mechanics receipt](../outputs/mlb-starter-duration-paired-research-v1/mechanics/objects/sha256/9b0d37bed1ea35e2817011a973cc12cec6026ff59d815dca4261f060ba1f52bb/actual-hgb-mechanics-receipt.json) was generated at **18:30:56.724128–18:30:58.357912 UTC**, runtime **1.634 seconds**. All **64 saved fixture rows / 192 probabilities reproduced exactly**. Two 64-draw paired executions repeated all 14 population arrays per arm and traces exactly; one additional 64-draw frozen reference-loop check also matched exactly. Total: 320 explicitly synthetic simulated games, three HGB prediction calls / 864 rows, zero fits and zero V18 PA inference. This uses unchanged historical fixture covariates, authenticated transition fold 4 and a clearly synthetic PA provider. It is `NONPREGAME_SYNTHETIC_MECHANICS`, not a historical/current forecast, and cannot satisfy the missing-current-input gate.

No model fits, recalibration, sports-provider requests, AISP writes, sealed Final OOT reads, policy/threshold/position changes, V19 expansion, RF recovery, or historical PA repair occurred. The original 56-observation hold and all prior artifacts remain protected. The live V18 producer and pinned deployment are unchanged.

**Conclusion: the implementation and explicit skips are delivered; legitimate prospective paired forecasts remain blocked by current starter-history evidence. No full-game improvement claim is supported.**
