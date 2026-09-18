# Claude/AISP: NBA same-owner refresh successor ready, inactive

This is a **producer-readiness handoff**, not consumer activation or a forecast publication.

- Final deployment `34b4060ff4ae4609f4fb61a2c5bd8518fa0587396e5cd1c489d78ec411d8ccf6`; manifest physical SHA `07c0b9b95578f78fbecee77718ff697f61fb2586e271a9a2f7e77a28891ac5ec`.
- Release `C:\Users\james\asp-model-studio\outputs\nba-gen1-same-owner-refresh-v1\release-final\releases\sha256\515a5e128c1037fb039382e23f3a0dd9820b924eba5fc13cb10bca67e80ec435\release.json`; physical SHA `515a5e128c1037fb039382e23f3a0dd9820b924eba5fc13cb10bca67e80ec435`.
- Exact proposed REFRESH_PLAN physical SHA `f2210fc0d987653bea57db0d37c170db6efde6d021bc2cb53cb32a3eb16ee863`, 10785 bytes.
- Immutable authorization proposal `C:\Users\james\asp-model-studio\outputs\nba-gen1-same-owner-refresh-v1\release-final\refresh-authorization\sha256\9f39f191205b4a3e68c51ef227c28467de436e40dcda969eb28ab3ee1482c9ab\proposal.json`; physical SHA `9f39f191205b4a3e68c51ef227c28467de436e40dcda969eb28ab3ee1482c9ab`. Not approved.
- Existing selected-model handoff `7113b71ff5819c89103ad19d5f9afb22c51dbc92980be12b56ce8826cb34ccaf` remains unchanged. Superseded deployment `0aa50236...` must not be installed.

One future invocation will plan, conditionally capture, admit the whole version, dispatch all due games and publish cumulative discovery. There is no separate capture owner. Zero-network is the default. A failed/incomplete update cannot refresh stale evidence or replace the admitted pointer. 304 revalidation retains the raw object's original clock; unchanged numerical inputs reuse original forecasts and publication clocks.

Retained coverage: 1197 mapped supported identities out of 1206; exclusions {'NEUTRAL_HISTORY_ONLY': 3, 'UNMAPPED_TEAM': 5, 'NOT_STANDARD_REGULAR_GAME': 1}. These are planning identities, not refreshed opening-night evidence. The captured source is from 2026-09-14T13:04:43.697362+00:00. Earliest proposed capture is 2026-10-13T18:00:00+00:00 (2 PM EDT October 13); first publication checkpoint 2026-10-13T19:00:00+00:00 (3 PM EDT October 13), at the first natural tick at/after those times and only if new input eligibility passes. No new real forecast is due or generated today.

Consumer work after separate activation: validate the exact release/model pins and V2 forecast index, member hashes, full 10,000-draw population and **bound publication receipt**. `publishedAtUtc=null` in a prepared V2 package is deliberate; immutable `publicationReceipt.committedAtUtc` in discovery is actual availability. Read `slate-discovery/current.json` -> immutable version, not a single-game index. Keep all prior revisions; honor currentlyEligible and eligibilityValidUntilUtc. On stopped/failed owners the lease expires; an old preserved package is not current evidence.

Keep authorities separate: Ridge alpha100 supplies expected scores; chronological Elo supplies winner probabilities; `NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1` supplies joint scores, totals, margins and joint-derived probabilities from 10,000 draws. Close-score correction stays disabled. One-point finishes were 7.78% simulated versus 4.01% observed; correction was rejected; overtime is harder; no profitability claim. BOS-DET and all earlier packages retain their original research/production identities and clocks.

Do not pin this readiness index as though it were an accepted activation contract. First authorize/install the final producer and exact network plan; independently validate the release and eligible new forecast packages, then use AISP's supported activation path. No AISP code, database, env, service or policy was changed here. No consumer acknowledgement is claimed.
