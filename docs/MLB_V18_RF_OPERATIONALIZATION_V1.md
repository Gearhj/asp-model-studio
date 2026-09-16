# V18 / original RF operationalization — 2026-09-10

## Decision

**NOT_OPERATIONALLY_USABLE_PUBLICATION_BLOCKED.** No ensemble forecast or AISP handoff was published. V18 remains official; the ensemble remains preserved Development research. No retraining, prior estimation, Final OOT payload access, providers, AISP activity, policy/position/settlement changes or wagering authority occurred.

Started on `codex/mlb-regime-hybrid-ensemble-v1` at `d391d274668bc33c0ef64f0881ef0db1fe0b3770`. Existing unrelated NFL and untracked work was preserved.

## Exact recovery versus executable reproduction

| Check | Result |
|---|---|
| Original RF identity | Candidate `stage3-candidate-5a26360c71194c10b2c101d27f253bdf`; candidate receipt `15e7e65f2cf6931fc57b922f3be5fdce1e9244b38b31582d026db7d15cd45440` |
| Ordered source schema and treatment rules | Recovered all 218 names and ordered transformations. Fold-encoded widths are 249 / 251 / 252 / 252 / 253, not one universal 253-column schema. |
| Historical V1 fitted priors | All five complete historical authority checksums recovered exactly from existing serialized parameters, with only original metadata restored. No parameter estimation. |
| Archived RF predictions on study population | Bitwise identical on 494,432 PAs / 6,570 games; zero mismatched values and zero numerical difference. Original RF OOF file has 501,590 rows. This checks archival prediction reuse, **not estimator replay**. |
| Original fitted RF estimator and complete preprocessor | Not recovered. The relevant stores and current/legacy Model Studio registrations contain no matching executable asset. Original receipts persisted OOF probabilities and preprocessing hashes, not the learned trees and complete fitted preprocessing state. |
| Preserved ensemble artifact | Reloaded unchanged; bitwise-identical blend on the matched archived inputs. Contains ensemble/correction parameters, not either base estimator. |
| Actual original RF estimator inference calls | **0**; exact RF estimator reproduction remains blocked, not passed with zero mismatch. |

The RF used 500 trees, `min_samples_leaf=20`, `max_features=0.5`, bootstrap, no class weights and seed 20260906. Its source transformations comprise 21 governed posterior-mean fields, 99 retained raw fields, 91 binary passthrough fields, four fold-mode binary fields and three categorical fields. Numeric missing values use training-fold medians; categorical null/unseen values map to UNKNOWN and training-ordered one-hot columns. There is no standardization or ordinal substitution. Numeric medians, binary modes and category levels remain missing as complete original fitted state; their receipt hashes were retained.

All 218 RF source names occur in V18's 246-name raw schema, but matching names do not establish V14/V18 transformation parity or prospective evidence support. The separate V18 273-input semantic representation cannot replace the RF's original preprocessing.

Frozen ensemble weights remain `[0.8920347405861558, 0.10796525941384416, 0.0]`, including the existing 0.03 per-class correction cap and saved temperature `1.001024923325094`. No rounded-weight replacement, recalibration, specialist refitting or reopened study was performed.

## Game-level prospective accounting

**Verified supported next-slate games: 0. Actual next-slate scheduled/withheld count: unknown**, because no timestamped future MLB slate/input bundle was established in the bounded local inspection. This is not a claim that no MLB games are scheduled.

Every locally published September 8 game is now expired. Its original forecast and participant evidence remain historical/replay evidence, not authority to produce a pregame forecast today.

| Existing September 8 record | Original status | Status at this check |
|---|---|---|
| CLE–BAL | Published | Expired; no current RF input authority |
| NYM–MIA | Published | Expired; no current RF input authority |
| MIN–DET | Published | Expired; no current RF input authority |
| HOU–PHI | Published | Expired; no current RF input authority |
| LAA–BOS | Published | Expired; no current RF input authority |
| COL–NYY | Published | Expired; no current RF input authority |
| TB–ATL | Published | Expired; no current RF input authority |
| CHC–MIL | Published | Expired; no current RF input authority |
| PIT–CWS | Published | Expired; no current RF input authority |
| TOR–ATH | Published | Expired; no current RF input authority |
| WSH–SD | Published | Expired; no current RF input authority |
| STL–SF | Published | Expired; no current RF input authority |
| CIN–LAD | Published | Expired; no current RF input authority |
| `801941c8-b68b-4735-b7c4-d5ee2dac3ae6` | Skipped: starter lacks accepted template evidence | Original skip preserved; expired |
| `aec50764-6ec6-4833-be28-901331b1f8f3` | Skipped: away starter identity/timestamp missing | Original skip preserved; expired |

The machine-readable accounting preserves full canonical IDs, source IDs, team IDs, start/capture/participant evidence times, reasons, hashes and original objects for all 15 records. The 13 published historical event/team mappings reconcile; the two skip receipts lack complete mappings. No observed mismatch is falsely inferred from an unavailable identity. No future-game identity mapping is verified.

Missing/incompatible evidence: next-slate schedule and participant snapshot, complete original RF fitted state and verified per-model prospective input vectors. Stale/wrong-event evidence: September 8 lineups/starters and historical event context. V18 numerical templates use April 1–August 13, with July 15–August 13 bullpen templates; those historical priors are not current bullpen availability. The composer refreshes handedness/platoon and five simulated PA-state fields, but does not rebuild calendar/rest/travel context for a new game. Exact feature-name requirements are retained in `rf-feature-contract.json`.

## Implemented and verified

Implemented an exact-checksum zero-fit prior recovery utility; archived-prediction/identity verification; explicit separation of OOF reuse from executable RF reproduction; and a metadata-only prospective support gate requiring actual execution before first pitch. These are preparation and fail-closed verification helpers, **not a newly enabled publisher**. Existing V18 publisher behavior was not changed.

Three focused tests passed: one-bit RF prediction mismatch and identity rejection; OOF-only evidence cannot unlock publication; stale execution, original skip preservation, source cutoff and missing input authority. Actual checks recovered all five prior authorities idempotently and verified saved probabilities plus ensemble reload on the entire matched cohort. No broad suite or study rerun.

Evidence lives under `outputs/mlb-v18-rf-operationalization-v1/`: `current-input-accounting.json`, `rf-artifact-inventory.json`, immutable `prior-recovery/` authorities, and content-addressed `sha256/` feature-contract and operationalization receipts. All original artifacts remain unchanged.

Final operationalization receipt: `outputs/mlb-v18-rf-operationalization-v1/sha256/445de2b7b695d8f2cef425151b5f30f9805ffa63aeb3222e15c10aaeb4522846/operationalization-result.json`; SHA-256 `445de2b7b695d8f2cef425151b5f30f9805ffa63aeb3222e15c10aaeb4522846` (6,418 bytes). This is a blocked operationalization receipt, not an AISP forecast handoff.

## Smallest concrete repair / next action

1. Restore the **original candidate's** five learned RF estimators and original fitted preprocessors from an existing backup or run host, with verifiable lineage. Run exact inference against the 494,432 matched IDs and designate the frozen prospective RF artifact/cutoff. Recovered V1 priors can be reused only because their historical hashes match.
2. Supply an existing timestamped local next-slate export: canonical event/team/source IDs, UTC first pitch/status, original observed/available timestamps, both starters, ordered nine-player lineups, and event-specific context plus player/state inputs satisfying both frozen contracts. Missing fields must remain explicit; do not fabricate them or relabel old evidence as refreshed.

If the original learned state was never saved, exact original RF recovery is impossible from probability files and hashes. A newly persisted RF would require separate authorization and new evidence; it would not be the reproduced original. **AISP action now: none—there is no justified ensemble forecast handoff to import.**
