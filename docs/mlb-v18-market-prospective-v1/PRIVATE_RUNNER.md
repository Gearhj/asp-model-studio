# Private collection implementation

The frozen September pilot `f75aeccd8f0e472b399d1f470c29d6a443d77078f7c69333023292019d956bf7` and its original rule document remain unchanged. This source implements collection and scheduled reporting; it adds no model, calibration, policy, acquisition, wagering or formal advancement authority.

## Owners and execution

The existing AISP `asp-rx-v18-market-pilot-seal` job remains the sole writer of genuine pregame packets, on its existing two-minute research export lane. Model Studio runs `scripts/run_mlb_v18_market_private_v1.py` from this independent source worktree through the existing hourly task heartbeat. Its exclusive private lock prevents concurrent reader/writer runs. It does not use a provider, database, producer, Windows task or production discovery API. The CFB collector and its assessment dates stay unchanged.

The ten-minute T-15 to T-5 allowance belongs to the AISP sealer. An hourly Model Studio validation is feasible because it validates the packet already sealed before T-5, retaining actual seal completion and later validation times separately. Missing pregame seals can never be reconstructed by this reader. The reader cannot widen the seal window. A stale private lock is reported; it is never automatically forced.

`RUNNER_FROZEN.json` binds the reviewed code files, unchanged protocol, actual readiness time and consumer acknowledgement before enrollment. Its date is an implementation-readiness clock, not a new protocol freeze. Do not replace the binding. A concrete future operational repair needs an explicit successor receipt preserving previously admitted evidence and the original protocol; no tuning is permitted.

## Retained records

The reader verifies the complete hash chain in `consumer-packets/attempt-ledger.jsonl`. Consumer line hashes exclude the newline; the archived prefix hash binds all original bytes including newlines. A partial final line is not a receipt. Earlier consumed prefixes cannot change. `SEALED.writtenAtUtc`, not the packet's build-start `sealedAtUtc`, establishes completion. Both packet/evidence hashes, sidecar, matching episode and original attempt line must verify.

Identity and quarantine checks precede producer inputs or outcome access. Phase uses the exact sealed, sanitized schedule metadata and a hash-only check of the referenced permitted September source file; raw schedule outcomes are not parsed. Only the two byte-exact frozen documents may be resolved from an identical authoritative location if an old consumer worktree disappeared. Such reference recovery is recorded; forecast/input substitution is forbidden.

For the named forecast only, the reader verifies its original manifest, pregame evidence, 246/273 input contract, model artifact bytes (without deserialization), existing participant freshness gates, 5,000 legal original paired scores, probabilities, MCSE and immutable input identity. Missing consumer model fields are separately verified from that exact object. Generation time is not treated as publication: use matching recorded atomic exposure or completed matching consumer import as an upper bound. Actual-decision anchors retain the named forecast. Research anchors require the original publication candidates to prove the latest eligible selection.

Original packets/evidence are archived under `private-collection/sealed/<packet-sha>/`. A later verification receipt remains distinct, and an episode index is exposed only after the immutable receipt and its hash binding are complete. Interrupted indexing reuses the original verification receipt and clocks. Rejected packets are retained once in `rejected-episodes/`. Universe metadata, no-forecast, unpriced, superseded schedule episodes and missed seals remain visible. One completed game contributes at most once; an unproved later schedule episode is excluded pending an actual reviewed postponement case.

The structural schema and the scientific checks are separate. Consumer eligibility flags are preserved as source claims. The reader independently verifies each book pair, raw-to-decimal arithmetic, quote clocks/availability, same event/response/period/conventions and deterministic book rule. The evidence profile uses the existing schema's permitted supporting references to establish those facts. An evidence note asserting a raw-response hash is not substituted for missing per-leg clocks or unknown conventions. Current SGO exports store the older clock on both sides and lack pitcher/action conventions, so they remain UNPRICED even when both stored ages are below 15 minutes. No extra acquisition is performed to fill these gaps.

## Reports and outcomes

Each run writes a hash-addressed operational receipt, `COLLECTION_STATUS.json` and `private-collection/COVERAGE.md`. These contain counts and exclusions only. Synthetic tests never write to enrollment. The first authentic packet is reported only after the real sealer produces one and the reader validates it.

Scheduled assessments run at the next heartbeat after September 22, September 29 and October 2 at 16:00 UTC. They preserve the exact logical cutoff and actual execution time. No unscheduled performance metric is calculated. Per-game immutable consumer-admitted final revisions come from the separate `consumer-outcomes/<game-id>/<physical-sha>.json` lane described in the shared integration note. The historical wagering CSV is never an input to this pilot. Both arms use the same admitted revision. Pushes, ties, refunds, voids and no-contests are counted and excluded from both binary scores; pending is not a loss. Cancellation can be known before scheduled start. Source capture authority remains bounded by the existing October 1 expiry.

The primary metric is mean paired home-win log loss, V18 minus the fresh no-vig market. Brier, fixed reliability bands, per-game/date/week differences, and original model score/margin/total errors/CRPS are secondary. Unknown selection stays in the full population. Resampling uses games/date blocks, never the 5,000 simulation draws. Descriptive percentile intervals are labeled 95%, using 5,000 resamples and seed 20260919; this presentation choice is not a formal advancement gate. Minimum frozen support rules and the additional September 29 100-pair interval requirement are enforced. No market score distribution is invented.

Systemic provenance, changed numerical identity or duplicate replacement stops private admission. Ordinary per-game stale or missing evidence excludes that observation and preserves unaffected games. Low coverage never changes the rule. The runner cannot stop or alter production, the CFB collector or existing acquisition.

## Focused verification

Run only the three new test files with the retained Python environment:

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' -B -m pytest -q tests/test_mlb_v18_market_admission.py tests/test_mlb_v18_market_assessment.py tests/test_mlb_v18_market_runner.py
```

Tests use synthetic temporary files outside enrollment. They cover positive contract integration, incomplete writes, immutable indexing, altered hashes, relative refs, strict freshness, per-leg evidence, book order, schedule/anchor identity, original draws, quarantine, pushes, revisions and scheduled assessment gates. They do not repeat model or consumer compatibility tests.
