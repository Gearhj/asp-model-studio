# Prospective cross-game evidence infrastructure v1

## Verdict

`ASP_PROSPECTIVE_FORECAST_EVIDENCE_V1` is implemented and validated as an **inactive, research-only evidence contract**. It does not publish forecasts, update discovery, write AISP, execute the frozen assessment, or authorize a cross-game display.

The design closes the main limitation in the completed historical study: future evidence can bind an exact forecast revision, physical package and population hashes, source cutoff, creation/publication clocks, explicit dependency states, and an exact calibration-certificate disposition before outcomes are accessed.

## Architecture and ownership

Model Studio owns creation and validation of producer-side pre-outcome evidence. Existing sport publishers remain the only forecast owners. The additive evidence sidecar is created after an existing immutable forecast package passes its own verification and before any future evidence discovery update. The original package is never rewritten.

AISP remains the consumer owner. A later consumer acknowledgement is a separate `ASP_PROSPECTIVE_AVAILABILITY_RECEIPT_V1` bound to the pre-outcome evidence SHA-256. It does not fill a null field in place. Outcome owners later create `ASP_PROSPECTIVE_FORECAST_ASSESSMENT_V1`, which binds the unchanged pre-outcome evidence and governed final revision.

The four record layers are:

1. **Pre-outcome envelope:** immutable forecast, participant, model, integrity, timing, dependency, market and calibration bindings.
2. **Availability receipt:** append-only exchange discovery, consumer acknowledgement or decision-window availability clock.
3. **Post-outcome assessment:** final-result revision and inclusion/exclusion record, stored separately after outcome availability.
4. **Readiness state:** coverage accounting only. It cannot authorize or execute the frozen assessment.

Canonical identity is SHA-256 over UTF-8 JSON serialized with `ensure_ascii=False`, `allow_nan=False`, sorted keys and compact separators. Package and population SHA-256 values remain physical bindings supplied by the verified producer package; they are not recomputed from labels.

## Clock semantics

The contract distinguishes, without inference:

- source cutoff;
- physical forecast creation;
- producer publication;
- exchange discovery;
- consumer acknowledgement;
- decision-window availability;
- scheduled start;
- pre-outcome capture;
- outcome availability; and
- post-outcome capture.

Required clocks must be timezone-aware. Source cutoff must not follow creation; creation must not follow publication; publication and the initial capture must precede the scheduled start. Nullable downstream clocks stay null until supported. A later availability receipt records its actual observed time and derives whether it was pregame; a late receipt remains late.

## Revision and correction behavior

Each forecast series begins at revision 1. A successor increments the latest revision exactly and binds its predecessor forecast ID, revision, package SHA-256 and evidence SHA-256. Prior records are deep-copied into the returned chain and never overwritten. Corrections to results, dependencies or downstream clocks are new linked receipts rather than edits.

## Frozen-gate compatibility

The library hard-codes and validates:

- design SHA-256 `5749b2457b52589a612b3a2597341185a5baf9b814d300715ec115a4c8dda87f`;
- result SHA-256 `fafc0b9bd9997e65fa6db209bceb6dacb91943528e136ed23603daf922ffef24`;
- 500 games;
- 50 dates;
- 1,000 unique unordered pairs; and
- two reliability bands with at least 200 pairs and 20 dates each.

Readiness logic rejects same-game and duplicate pairs, uses a stable unordered pair identity, counts only explicitly eligible observations, and reports either `COLLECTING` or `READY_FOR_FROZEN_ASSESSMENT`. Both `assessmentAuthorized` and `assessmentExecuted` remain false in either state.

## Calibration disposition

MLB, NFL, NBA, CFB and MMA are all `UNCERTIFIED` under the new prospective contract. Existing historical or reconstructed results are preserved but lack the complete timestamp-certified evaluation and artifact binding needed by this new record. MMA also lacks a fitted governing forecast model. No model was recalibrated or promoted.

## Producer integration

The shared library exposes inactive descriptors for MLB, NFL, NBA, CFB and future MMA publication. The minimal integration hook is after package verification and before discovery/publication of the evidence sidecar. No existing publisher imports this module, and no scheduler or production owner changed.

When later authorized, immutable sidecars use:

`prospective-cross-game-evidence-v1/objects/sha256/<evidence-sha256>/pre-outcome-evidence.json`

That path is proposed and returned by the pure binding helper. Nothing was written to the exchange in this assignment.

## Verification and accounting

Synthetic fixtures use no provider data. Focused tests cover clocks, null preservation, revision chains, hashes, dependency tri-state handling, pre/post separation, pair identity, doubleheaders, readiness counts, frozen hashes and side-effect boundaries. Existing probability-contract and historical-validation tests remain in the focused suite.

Provider calls, sportsbook calls, cost, sealed reads, Final OOT reads, model runs, model promotions, AISP writes, exchange writes and scheduler changes are all zero.
