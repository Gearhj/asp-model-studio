# MLB V18 publication without waiting for the slate

The active current-state owner previously completed the sequential simulation loop before exporting its exchange handoff. A finished Cubs–Reds forecast could therefore wait behind unrelated later games. Sorting deadlines did not remove that publication barrier.

The repair threads a synchronous completion callback through `run_mlb_v18_current_state.run` and `mlb_v18_current_publication.publish_slate` into `mlb_v18_unattended.execute_tick`. After an eligible forecast's existing validation and immutable-write path completes, the owner builds a cumulative handoff and import receipt and invokes the existing atomic exchange exporter before starting the next simulation. Required views and full-slate game accounting remain present. The ordinary end-of-tick handoff remains available for final accounting/recovery.

The callback runs outside the inference exception handler. A publication failure cannot relabel a completed numerical object as a failed model fit or silently postpone release until the end of the slate. The owner retains its existing lock, bounded error handling and natural scheduler; there is no second publisher or additional acquisition path.

## Integrity and consumer compatibility

Exchange children are copied and hash-verified in `.staging`. Only after all required files and the manifest exist is the complete directory atomically renamed into the consumer-visible `sha256` directory. The append-only handoff-key index follows verification. Interruption during staging therefore exposes no incomplete importable directory; interruption after atomic commit leaves a complete package even if its index/progress receipt has not yet been written.

The existing AISP contract accepts partial/cumulative nonempty handoffs, requires the receipt's published identities to match the handoff exactly, and imports idempotently by the unchanged forecast object identity. The importer scans committed package directories rather than waiting for a slate-wide completion pointer. Later cumulative packages do not revoke prior forecasts. Empty packages remain accounting-only. No consumer schema or policy change is required by this implementation; deployed consumer acknowledgement remains a separately recorded observation.

Forecast payloads, input/computation timestamps, object identities, required features, model/transition/treatment artifacts, 5,000 draws, calibration, eligibility and player-prop observer behavior are unchanged. Source history and participant acquisition remain with the existing owner. No protected outcomes are accessed.

## Operational evidence

An immutable `incremental-publication.json` is written after each successful completion callback. It binds the completed object, original clocks, actual package exposure/verification clocks, handoff/import receipt and deployment identity. A new package exposure clock is sampled after the atomic rename. Reused packages do not receive an invented original publication time. These receipts survive an interruption in a later game's computation and permit measurement without a manual competing publisher.

Cumulative export can repeat package verification and copy shared immutable children into successive packages. Focused checks measure that cost; a complete package is verified before it becomes discoverable. The change removes the unrelated-simulation wait rather than claiming zero copy/import latency. Consumer polling remains its own cadence.

## Verification and deployment record

Focused tests cover an early complete package being consumer-verifiable while a later game remains blocked in computation, unchanged identities/clocks in a later cumulative package, and interrupted staging leaving only previously committed complete packages visible. Existing exchange/current-publication/owner tests relevant to these contracts accompany those checks. No model tournament or new fitting is required.

The four focused modules passed **25 tests in 18.12 seconds**, including seven new tests. In this source-only checkout, the existing contract loader needs two admitted schema-metadata JSONs from the runtime: hashes `0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9` and `4171306af87bee46e74d2b5141189a5916382967322592243bf71e9eed9cf684`. Only their read-only root binding is supplied; synthetic engines do not load fitted models or source/outcome data. Reproduce with the existing Model Studio Python:

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' -B -c "from pathlib import Path; from server.sports_current_statcast import mlb_v18_current_slate as s; s.ROOT=Path('C:/Users/james/asp-model-studio'); import pytest; raise SystemExit(pytest.main(['-q','tests/test_mlb_v18_incremental_publication.py','tests/test_mlb_v18_unattended.py','tests/test_mlb_v18_current_publication.py','tests/test_mlb_v18_exchange.py']))"
```

The separate AISP read-only verifier acceptance and its timing evidence are retained with the private delivery. Unit fixture results do not claim a natural production run.

Build from the reviewed source commit using the already installed pinned deployment builder's `--commit` support. Make the safe source commit available to the runtime Git object database without checkout or merging; the builder reads committed blobs, not dirty working files. The verified source base matches all 919 existing installed files. The supported installer must observe the canonical task idle before replacing its manifest and re-register the same S4U/Limited/IgnoreNew owner. Retain the prior manifest and deployment for rollback. Do not invoke the producer manually for verification.

Exact source/build/install/verification/natural-run receipts are retained privately at `C:\Users\james\asp-model-studio\outputs\mlb-v18-publication-delay-repair-20260918-v1`. Shared coordination is at `C:\Users\james\asp-model-exchange\mlb-v18-publication-delay-20260918\PRODUCER_STATUS.md`; Claude owns its sibling `CONSUMER_STATUS.md`. The delivery report distinguishes prepared source, installed deployment, observed natural execution and measured fresh-inference latency.

The CFB collector remains unchanged. The separate MLB market pilot's pending consumer export does not block this publication repair.
