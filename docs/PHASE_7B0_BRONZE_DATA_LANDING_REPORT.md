# Phase 7B0 — Quarantined Advanced MLB Bronze Data Landing — REPORT

**Branch:** `phase7b0-bronze-data-landing` · **Starting HEAD:** `1aa274a` · **Ending HEAD:** `cc441cd` (before this report's commit)
**Push status:** not pushed. `main` not modified. No history rewrite.

## Verdict

**PHASE_7B0_BRONZE_LANDING_COMPLETE.** The standalone quarantined acquisition tool is complete and tested,
and the approved 2019–2024 source evidence is fully landed, hashed, and manifested: **Statcast 2019–2024**
(all six years, pitch-level, regular + postseason), **Retrosheet 2019–2024** (play-by-play + game logs), and
the **Chadwick** identity register. The only source not landed is **Lahman**, which is DEFERRED because its
canonical source repository now returns 404 (a source-availability issue, not a boundary or time issue). No
joins, features, targets, models, ASP-registry integration, or 2025/2026 access occurred.

## Staging

- **Root (outside the repo):** `C:\Users\james\asp-data-staging\mlb-advanced-bronze-v1`
- **Free space before:** ~244 GB · **after:** ~243 GB (well above the 30/50 GB thresholds)
- **Total raw bytes landed:** ~2.73 GB
- The staging root contains no executable ASP authority. `.gitignore` blocks all Bronze data from Git.

## Sources

### Statcast (Baseball Savant) — `PUBLIC RESEARCH SOURCE / ATTRIBUTION REQUIRED / COMMERCIAL RIGHTS UNCLEAR`
- Endpoint: `https://baseballsavant.mlb.com/statcast_search/csv` (`type=details`, pitch-level).
- **Critical finding:** the CSV endpoint **silently truncates at 25,000 rows** (a full month returns exactly
  25,000). The tool therefore acquires **per-day** partitions (≤ ~9k pitches/day, safely under the cap) and
  flags any chunk that reaches the cap (`TRUNCATED_CAP_HIT`). Regular and postseason are separated by
  `hfGT=R|` vs `hfGT=PO|` into distinct partition trees.
- **2019–2024 — COMPLETE:** 2,196 day-partitions (1,120 game days + 1,076 empty off-days), **0 failed**,
  **3,929,155 total pitches**, 0 natural-key duplicates. **Every landed row is dated within 2019–2024**
  (2025 refusal verified across all six years). Per-year (regular / postseason):

  | Year | Regular pitches | Postseason pitches | Game days |
  |---|---:|---:|---:|
  | 2019 | 735,090 | 11,182 | 210 |
  | 2020 | 264,262 | 16,136 | 90 (COVID-shortened season, expanded playoffs) |
  | 2021 | 712,320 | 10,852 | 206 |
  | 2022 | 710,210 | 11,774 | 200 |
  | 2023 | 720,684 | 11,878 | 205 |
  | 2024 | 711,899 | 12,868 | 209 |

- Natural key for duplicate checks: `(game_pk, at_bat_number, pitch_number)`. No targets, rolling stats, or
  joins were computed.

### Retrosheet — `PUBLIC RESEARCH SOURCE / ATTRIBUTION REQUIRED` (notice recorded)
- **COMPLETE, 2019–2024:** 6 game-log archives (`gl{year}.zip`) + 6 event archives (`{year}eve.zip`),
  **372 extracted members**, ~16.4 MB. Archives extracted with traversal/absolute/symlink rejection; every
  member hashed; source-native formats preserved (no ID conversion, no join).

### Chadwick register — `PUBLIC RESEARCH SOURCE / ATTRIBUTION REQUIRED`
- **COMPLETE:** 16 sharded `people-*.csv`, **518,743 register rows**, **12 identity systems** present
  (`key_uuid`, `key_person`, `key_mlbam`, `key_retro`, `key_bbref`, `key_fangraphs`, `key_bbref_minors`,
  `key_npb`, `key_sr_nfl`/`nba`/`nhl`, `key_wikidata`). No fuzzy matching; no ASP identity bridge built.

### Lahman / baseballdatabank — DEFERRED
- The canonical `github.com/chadwickbureau/baseballdatabank` repository now returns **404** (moved/renamed),
  and no reliable CSV mirror (`cdalzell/Lahman` is `.rda`-only; `WebucatorTraining/lahman-baseball` 404s) was
  locatable within budget. Recorded as **9 FAILED partitions with the 404 reason**; no data landed.
  **DEFERRED — SOURCE UNAVAILABLE AT KNOWN PATH.** The tool supports Lahman once a source URL is confirmed.

### Optional Kaggle mirrors — SKIPPED
- Not attempted. Core completion does not depend on Kaggle; no credentials were used or printed. The listed
  mirror packages cover 2020–2025 / 2024–2025 windows, so downloading them risks pulling sealed 2025 records:
  recorded as **DEFERRED — PACKAGE INCLUDES SEALED YEAR**.

## Manifest

- **Contract:** `MLB_ADVANCED_BRONZE_SOURCE_MANIFEST_V1` (a Bronze acquisition manifest ONLY — not an ASP
  dataset registration).
- **Path:** `<staging>/manifests/bronze-manifest.json` (+ `bronze-manifest.sha256`).
- **Labels:** QUARANTINED BRONZE SOURCE EVIDENCE · NOT REGISTERED · NOT MODEL-ELIGIBLE · NOT FEATURE-ELIGIBLE
  · NOT APPROVED FOR TRAINING. `registeredInAsp: false`, `modelEligible: false`.
- Per partition it records source, scope, query, retrieval UTC, tool version, HTTP status, attempts, filename,
  relative path, size, **file SHA-256**, schema fingerprint, row/column counts, column names, date coverage,
  natural-key duplicate count, license classification, status, and error/retry history. The manifest SHA is
  re-written after each partition and therefore advances as the Statcast backfill lands.

## Boundary proof (2025 / 2026)

- The safety layer refuses every year outside `[2019, 2024]` and every malformed/late date; the CLI refuses a
  `--end-year` > 2024; `statcast_url`/`statcast_partitions` refuse a sealed year. Hermetic tests assert all of
  this (`tests/bronze_acquisition_test.py`).
- **No 2025 was requested, downloaded, inspected, counted, or summarized.** Every landed Statcast maxDate is
  within 2019–2024 (verified across all 2,196 partitions). 2026 was never touched.

## Quality checks

- Statcast: HTML-error-page detection, empty-body rejection, per-day sub-cap sizing + a cap-hit guard,
  header-only (off-day) handling, columnar row/column/schema/date/duplicate inspection (no row-wise Python
  loop). Retrosheet/Chadwick archives + CSVs: archive opens, member inventory + hashes, safe extraction.
- Raw source data was never cleansed or repaired; anomalies are recorded, not mutated.

## Resume

- Proven on real data: the 2024 resume rerun **skipped 209 verified partitions** (no redownload) and
  re-processed only the 157 previously-failed off-days to `COMPLETE_EMPTY` (0 failed). A corrupt/missing
  partition is re-fetched; a valid one is never silently replaced. Hermetic tests cover valid/corrupt resume,
  atomic finalization, and no-overwrite-on-divergent-bytes.

## No integration / no modeling

- Joins performed: 0 · features created: 0 · targets: 0 · point-in-time features: 0 · models trained: 0 ·
  feature-family ablations: 0 · metrics: 0 · 2025 scoring: 0 · D3/C4 access: 0.
- The tool has **no import dependency** on `gen3_authority.py`, the cockpit modeling engine, the ASM/ASP
  dataset registry, `research_object_path`, the ablation service, or any Phase 4/5/6/7 research script.

## Remaining acquisition (transparent)

1. **Lahman** — deferred until a canonical CSV source URL is confirmed (baseballdatabank repo 404). The tool
   supports it once a URL is provided.
2. **Optional Kaggle mirrors** — deferred (windows overlap sealed 2025).

Statcast (2019–2024), Retrosheet (2019–2024), and Chadwick are fully landed; no further acquisition of those
sources is required for this phase.

---

### Final handoff

STARTING HEAD `1aa274a` · ENDING HEAD `cc441cd` (+ this report commit) · BRANCH `phase7b0-bronze-data-landing` · WORKTREE clean (tracked) · PUSH none · COMMITS: tooling, tests, report

**STAGING** — root = `C:\Users\james\asp-data-staging\mlb-advanced-bronze-v1` · free before ≈ 244 GB · after ≈ 243 GB · raw bytes ≈ 2.73 GB · manifest partitions = 2,233 (Statcast 2,196 + Retrosheet 12 + Chadwick 16 + Lahman 9 failed) · manifest sha256 = `fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a`

**STATCAST** — years 2019–2024 COMPLETE · **3,929,155 pitches** (regular + postseason, separated) · 1,120 game-day + 1,076 empty-off-day partitions · 0 failed · 0 duplicates · every row within 2019–2024 · schema = single Baseball Savant `details` schema · resume = proven (209 skipped on the 2024 rerun)

**RETROSHEET** — years 2019–2024 · 6 game-log + 6 event archives · 372 members · hashes recorded

**CHADWICK** — 16 shards · 518,743 rows · 12 identity systems · hashes recorded

**LAHMAN** — DEFERRED (source 404) · 2025 present in package = n/a · 2025 inspected = no

**KAGGLE** — credentials used = no · datasets acquired = 0 · skipped (windows include sealed 2025)

**MANIFEST** — contract = `MLB_ADVANCED_BRONZE_SOURCE_MANIFEST_V1` · status = QUARANTINED BRONZE · registeredInAsp = no · modelEligible = no

**BOUNDARY** — 2025 requested/downloaded/inspected = no/no/no · 2026 requested = no · ASP registry used = no · ASP modeling service used = no · legacy research scripts used = no · joins = 0 · features = 0 · models = 0

TESTS = 29/29 (`tests/bronze_acquisition_test.py`) · PY_COMPILE = pass · DIFF_CHECK = pass

D3 changed = no · D3 retrained = no · champion changed = no · sealed data touched = no · raw data committed = 0 · credentials printed = 0 · external sources outside allowlist = 0 · pushes = 0 · main modified = no
