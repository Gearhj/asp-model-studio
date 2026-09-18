# NBA Gen1 production activation readiness

## Disposition

`NBA_GEN1_PRODUCTION_READY_AWAITING_ACTIVATION`

The selected Gen1 model is packaged, its inactive publisher deployment is staged, and a new prospective forecast was issued through that exact deployed path. No Windows task was installed and AISP was not changed. One separate authorization remains to install the single canonical producer owner; Claude must then validate and pin the handoff independently.

## Frozen selection

- Configuration: `NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1`.
- Expected scores: ordinary-rest Ridge, alpha 100. Artifact SHA-256 `063e69ffb685a16bd784276fa94bce27f8e2d5e91f744e8c9a60a46f242f70ef`; training identity `fd3d73a6b5cfb071c100c6f2d124cb75e20fc0d8469a4033f040b19fb0b6239f`.
- Winner probabilities: chronological Elo. Artifact SHA-256 `6a1391e7e0f321b722a284292499055323eeea7e238f60eb51c53042487b11fe`.
- Feature contract SHA-256: `8ad07aa94fefc84839c8f369f9ddbe7a0e38b4c384d16f3342f0df4c171cb0ef`.
- Training: 8,177 games through April 12, 2026; retained history contains 8,289 games through season end 2026.
- Distribution: `NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1`, 10,000 draws, master seed `20260914`, residual population SHA-256 `84bd0f9e327f469b3f0c5cd3b337c1b6e3473cad03bcf9ac790a6a321b569f4d`.
- Schedule discovery: retained 2026–27 SportsDataverse/hoopR schedule object SHA-256 `d4ffe0d974dbec227af1ea5d731e0f36426839a170bfd0bbffc39b65f933a090`, captured September 14 at 13:04:43 UTC.
- Close-score challenger: disabled. It was tested and rejected.
- Gen2: `GEN1_REMAINS_BASELINE`; governed team-box population identity `dfb3216a9c7b520d8d6368d7d72eeb60c6566bfd1ea8811a27c9c419aaa74fa2` remains preserved outside Git. No additional model search was run.

Ridge scores, Elo probabilities, and the residual score population are separately estimated channels. Elo is the declared winner-probability channel. The score draws supply home, away, total and margin distributions and must not be represented as the source of the Elo probabilities.

## New prospective forecast

The exact staged deployment issued Philadelphia at New York, ESPN `401909089`, scheduled October 20, 2026 at 23:00 UTC. BOS–DET `401909088` is permanently excluded from this publisher path because it is the earlier research demonstration.

| Field | Value |
|---|---|
| Forecast ID | `nba-production:ab967168951e39a3f1068846b094097be947d2b235913b2ea386eaaaf75a56d0` |
| Prospective effective time | `2026-09-18T01:16:08.176807+00:00` |
| Source cutoff | `2026-09-14T13:04:43.697362+00:00` |
| Created/published | `2026-09-18T01:16:32.611393+00:00` |
| Ridge expected score | PHI 111.1184, NYK 117.0613; total 228.1797; NYK margin 5.9429 |
| Elo win probability | PHI 0.322743, NYK 0.677257, tie 0 |
| Joint expected score | PHI 111.1279, NYK 117.2234; total 228.3513; NYK margin 6.0955 |
| Joint win probability | PHI 0.3181, NYK 0.6819, tie 0; MCSE 0.004657 per side |
| 80% intervals | PHI 96–127; NYK 102–132; total 204–253; NYK margin -12–23 |
| Draws | 10,000 paired HOME/AWAY draws, no ties or discarded draws |

Forecast package/index SHA-256: `8a725a439af9f9ad4828281ff9bcdec5511c2af292c3feac4826b975dfa0d4c2`. Forecast physical SHA-256: `8c69bc25e64c969b0dfd2f0cfe3b3ec7af0f8699358368a44ab4289ba3f46282`. Population Parquet SHA-256: `62b48824b2746656d2ec9e93c5ebcd6b3768e8662b37b0e0703a3a463e1eb17c`; logical ordered HOME/AWAY int64 population SHA-256: `6d7b75fbe79f3803269643f88bf29b117e182730d38b2ba5477d0bb70e2c0bb7`.

The replay verified every package member and all distribution accounting, then returned `REUSED_IMMUTABLE` with the same forecast/package hashes. The earlier BOS–DET forecast remains SHA-256 `27f766e341cc211317d61e7ed842d7bbff7521664da5b27a0776bfc5394a8767`; its joint baseline remains `2fb6a1c382a3eda10633a067863745ecb8fbd3b6eec2f31659c9a583d8774d99`.

## Performance and monitoring

The retained 7,009-game joint assessment reported energy score 10.434157, total CRPS 10.755059, margin CRPS 7.873538, winner log loss 0.625271 and Brier 0.217916. On the frozen 2023–24 Gen2 selection comparison, exact retained Gen1 had energy 10.2954, team-score MAE 9.3408, margin CRPS 7.9886, total CRPS 10.4177, log loss 0.6214 and Brier 0.2163. These are reused historical results, not a fresh production test.

The first production review is fixed at 50 completed games. The 100-game review adds calibration and distribution diagnostics. Both reviews retain score, margin and total MAE; winner log loss and binary Brier; energy score and home/away/total/margin CRPS; one-point-finish frequency; and regulation-versus-overtime performance.

Known limitations remain explicit:

- simulated one-point finishes were 7.78% versus 4.01% observed;
- the close-score correction was tested and rejected;
- overtime games remain materially harder;
- player availability, lineups, injuries and projected minutes are absent;
- no profitability claim has been established.

## Deployment and activation

Deployment `7e04b1cc6f68ad4a4c0a3833f28751fdbfc54957e019e2cb5743946eeae25716` is staged and not installed. Manifest SHA-256: `5d34687595d35837528be0655080b00d006c38b5414e33ffb7448c9e19cb360e`; all 26 members were rehashed successfully. Live inventory found zero tasks named `ASP NBA Forecast Publisher`, so no duplicate owner exists.

The installer creates exactly one current-user S4U/Limited/IgnoreNew task at a 15-minute cadence. It is not authorized or active. The exact Administrator command, removal rollback, and AISP pins are in the immutable activation package. Current-season evidence must be refreshed after governed finals; the owner fails closed rather than treating stale opening-slate history as current.

## Immutable handoff

- Model handoff index: `C:\Users\james\asp-model-exchange\nba-gen1-production-v1\handoffs\sha256\7113b71ff5819c89103ad19d5f9afb22c51dbc92980be12b56ce8826cb34ccaf\index.json`.
- Prospective forecast index: `C:\Users\james\asp-model-exchange\nba-gen1-production-v1\forecasts\sha256\8a725a439af9f9ad4828281ff9bcdec5511c2af292c3feac4826b975dfa0d4c2\index.json`.
- Final activation/Claude delivery: `C:\Users\james\asp-model-exchange\nba-gen1-production-v1\activation-readiness\sha256\a2c828a1c2692571495fba8e3c072d66491c12a58f9a02ae10903ce1a9024b63\index.json`.

The final delivery index SHA-256 is its package address, `a2c828a1c2692571495fba8e3c072d66491c12a58f9a02ae10903ce1a9024b63`. `ACTIVATION.md` SHA-256 is `6c371597dcc552557f95b74ea78aacd9812b235c46ac72ae3b112cc31dd2aa3d`; `CLAUDE_HANDOFF.md` SHA-256 is `adb7d22ea513ec770c3c96c35bdbabd59811229d8a67f4536ef928b806462239`.

No provider call, source byte download, paid request, sportsbook call, AISP write, scheduler install or model fit occurred. Consumer acknowledgement remains absent.

## Verification

Focused production tests passed for population count and mass, orientation, PMFs, mean coherence, intervals, totals semantics, disabled close-score behavior and tamper rejection. Existing joint-residual checks also passed. A larger combined run completed 20 tests before six legacy point-forecast fixture setups hit a Windows ACL denial while pytest created temporary directories; those errors occurred before the six test bodies. Python compilation and PowerShell parser checks passed. The deployed package was verified twice, including the immutable replay.

