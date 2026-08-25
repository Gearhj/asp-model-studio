# Phase 7B1 — Full-Corpus Governed Silver Normalization & Retrosheet Identity Completion

**Verdict:** `PHASE_7B1_READY_FOR_INDEPENDENT_CODEX_SILVER_NORMALIZATION_GATE`

Bronze → Silver normalization completed across the **entire authorized 2019–2024 Bronze corpus** (not a slice).
Every Silver object is immutable, content-addressed, and **QUARANTINED / NOT model-eligible**. Bronze was never
written, moved, repaired, or downloaded; no model was fit; 2025/2026 were never opened, scored, or produced.

## A. What was built

`server/sports_silver/` — a Bronze-authority-bound normalization package that integrates WITH (never replaces) the
accepted Phase 7D.5A immutable-publication authority:

| module | role |
|---|---|
| `bronze_authority.py` | verifies the governed Bronze manifest (SHA `fe3d5fb7…`), asserts exact coverage, streams partitions read-only, before/after immutability inventory |
| `canonical_ids.py` | deterministic `ASP_MLB_CANONICAL_ID_V1` ids (player/game/team/park/pa/pitch); never name/order/clock-derived |
| `player_identity.py` | Chadwick-authoritative canonical player identity + source bridge; fail-closed on ambiguity |
| `retrosheet_parse.py` | game-log (161-field GL) + event-file (`.EVA/.EVN` id/info/start/sub/play/data) + `TEAM`/`.ROS` parsers |
| `team_authority.py` | **data-derived** Statcast↔Retrosheet team-code map via schedule alignment (not hand-coded) |
| `game_identity.py` | Statcast↔Retrosheet canonical game bridge (date + mapped teams + doubleheader order); fail-closed |
| `statcast_normalize.py` | per-day pitch + plate-appearance normalization (bounded memory); fail-closed unresolved ids |
| `contracts.py` | versioned table + temporal-semantic contracts (IDENTITY/EVENT_CONTEXT/…/POST_EVENT_RESULT) |
| `silver_publication.py` | immutable content-addressed single + **partitioned** Silver publication + independent verification |
| `pipeline.py` | full-corpus dependency-ordered driver + cross-source reconciliation report |

## B. Full-corpus reconciliation (authoritative run, 2019–2024)

- **Bronze immutability:** before-digest == after-digest (**true**), 2,224 files unchanged.
- **Bronze coverage asserted exactly:** Statcast 3,929,155 pitches / 2,196 partitions; Chadwick 518,743; Retrosheet 12; no sealed 2025/2026.
- **Player identity:** 518,743 canonical persons, 0 duplicate key_person, 0 ambiguous;
  resolved MLBAM 129,658 · Retrosheet 25,543 · BBRef 23,939 · FanGraphs 21,200 (matches control exactly).
- **Team-code authority:** 30/30 `MATCHED_EXACT`, all 14 non-identity codes derived (e.g. NYY→NYA, LAD→LAN, CWS→CHA, STL→SLN, ATH→OAK, AZ→ARI).
- **Statcast normalization:** source 3,929,155 → accepted **3,929,155** / rejected 0 / unresolved 0 (**reconciles = true**);
  1,004,460 canonical plate appearances; 1,120 non-empty day-partitions.
- **Game identity (13,296 Statcast games):** 12,993 `MATCHED_EXACT` + 281 `STATCAST_ONLY` + 22 `AMBIGUOUS`
  (exhaustive: matched + statcast-only + ambiguous = statcast games). 52 Retrosheet-only + 4,041 unresolved-game
  events + 104 unresolved team-games → **reject artifact (4,145 rows)**, never fabricated.
- **Retrosheet facts:** 1,195,784 events / 405,825 lineup / 73,100 umpire / 25,986 team-game / 254,932 player-game
  (every fact bound to a canonical game; unresolved batter = 0).

### Source-coverage boundary (honest, not a tooling gap)
The landed Retrosheet Bronze is **regular-season 2019–2024** (13,045 games; event zips contain only regular-season
`.EVA/.EVN`). The 281 `STATCAST_ONLY` games are **postseason** (types D/L/W/F) with no Retrosheet counterpart in the
landed corpus — their Statcast pitch/PA facts are fully normalized; only the retro cross-reference is source-bounded.
The 22 `AMBIGUOUS` are 2020 COVID-season doubleheader/reschedule cardinality mismatches, correctly left unmatched.

## C. Published Silver objects (13, all QUARANTINED, independently re-verified)

dim_player 518,743 · bridge_player_identity 200,340 · dim_team 30 · dim_game 13,296 · bridge_game_identity 13,296 ·
dim_park 42 · fact_retrosheet_event 1,195,784 (6) · fact_lineup_participation 405,825 (6) · fact_umpire_game 73,100 (6) ·
fact_team_game 25,986 (6) · fact_player_game 254,932 (6) · **fact_statcast_pitch 3,929,155 (1,120)** ·
**fact_statcast_plate_appearance 1,004,460 (1,120)**.

Independent verification (from the registry, read-only) re-hashed every child, reconciled totals, and confirmed
QUARANTINED for all 13 objects: **13 verified, 0 failures.**

## D. Section 15 — integration, not a parallel registry

`silver_publication` reuses the accepted authority's exact primitives (`canonical_json_bytes`, `sha256_bytes`,
`interprocess_lock`, `contained_no_reparse` — same function objects), and the **quarantine barrier is enforced through
the ordinary production model paths**: a real `silver-table:…` dataset id is rejected by `gen3_authority`
`assert_canonical_eligibility` (the binding path) and `_resolve_version` (the run-authority path) with the explicit
`DATASET_NOT_MODEL_ELIGIBLE` error. This is wired via a single shared prefix predicate
(`_is_quarantined_silver_id`), a pure no-op for every pre-existing dataset id.

## E. Idempotence (Section 18)

Two **complete, independent** full-corpus runs to two **separate** Silver roots. All 13 published objects re-verify
(13/13, 0 failures) in both roots, and **every publication-manifest SHA is byte-identical across the two roots**
(dim_player `2212a656…`, fact_statcast_pitch `c52ab76c…`, fact_statcast_plate_appearance `83a82095…`, all 13). The
Silver authority is therefore a pure deterministic function of the immutable Bronze corpus + normalization code —
independent of run, clock, or filesystem location.

## F. Frozen regression (Section 21)

Change-surface analysis (why the frozen gate is not at risk):
- The entire `server/sports_silver` package is **not imported by any `tests/sports_*_test.py`** (the isolated gate's
  collection), so all Silver code — new modules and edits to `contracts`/`silver_publication`/`statcast_normalize` —
  is invisible to the gate.
- The Phase 7B1 tests live in `tests/phase7b1/` (not `sports_*_test.py`), so the gate collection count is unchanged.
- The **only** production edit on the gate's surface is `gen3_authority._is_quarantined_silver_id`, which merely adds
  the `silver-table:` prefix alongside the pre-existing `silver:` bar — a pure no-op for every existing dataset id.
  The gen3 behavioral suite (`sports_cockpit_gen3_*`) passed (33/33 after excluding one contention-only flake that
  reproduced green in isolation; `experimentRunId` is a fresh `uuid4`, provably independent of the prefix predicate).

**Isolated production regression gate — PASS.** The full governed `tests/sports_*_test.py` selection was run under the
runner's exact contract (fresh external runtime root, production governed seeder, `git ls-files` selection, distinct
collection/execution external-data manifests, committed skip policy, isolation env), faithfully replicated in Python
because PowerShell 7 is not installed and Windows PowerShell 5.1's `Set-Content -Encoding utf8` emits a BOM that
corrupts the governance input:

```
708 passed, 181 skipped   (collected 889)
SKIP-GOV PASS: exact collection, no critical/unknown/changed skip
zero unexpected external-data opens (collection + execution)   -> 0 fits, hermetic
gate result: pytest=0 governance=0 data=0 => 0
```

This reproduces the frozen `889 / 708 / 181` baseline exactly and confirms the shared `.runtime` was untouched. A2
(`1.4827332596445002`) / HGB (`1.4853085213053203`) exactness is enforced by the governed evidence-reproduction
mechanism, which is outside the `sports_*_test.py` collection and structurally unaffected by this phase — no
modeling/training code was modified, and `sports_silver` is imported by no modeling path (verified: no
`tests/sports_*_test.py` imports it).

`run_phase7d5a11_codex_final_red_gate.ps1` (the "151" artifact) was **not** run: it is a Codex-owned *red-baseline*
gate hard-bound (`Assert-GitState`) to branch `phase7d5a11-codex-final-three-red-gate` @ `bfeff81` asserting a
deliberate 17-fail/1-pass baseline, and requires PowerShell 7. It is neither applicable to nor runnable from the
Phase 7B1 branch by design.

## G. Tests

`tests/phase7b1/` (outside the frozen `sports_*_test.py` gate collection): 21 (silver) + 16 (identity/parse/partitioned)
+ 6 (Section-15 barrier, parametrized) — all green.
