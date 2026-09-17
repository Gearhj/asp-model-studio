# NFL M1 production baseline readiness and activation report

**Decision: `NFL_M1_PRODUCTION_READY_AWAITING_EXPLICIT_ACTIVATION`.**

Model Studio published the exact production handoff and AISP's live adapter accepts its bytes. AISP has not pinned those bytes: the live `/api/v1/research/nfl-production-status` response remained `NOT_RECEIVED` at 2026-09-17 16:10 ET. Model Studio cannot truthfully claim activation, a natural post-activation invocation, or a production-labelled AISP forecast until the consumer owner sets the two supported pins and reloads the existing backend owner.

## Frozen baseline

| Item | Verified value |
|---|---|
| Model | `NFL_M1_XGBOOST` |
| Configuration | `NFL_M1_2026_RESEARCH_SHADOW_V1` |
| Candidate/revision | `nfl-m1-xgboost-fixed-research-challenger-2026-shadow` |
| Model binary SHA-256 | `7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd` |
| Model manifest SHA-256 | `ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9` |
| Feature contract | 197 ordered `LONG_HISTORY_CORE` features, SHA-256 `ef5c4f9ce8c3dd04a473e7ecb2ea3a255154f65a1bb3fda9d2ebc19bf1cb8f4d` |
| Training | 7,276 games through 2026-02-08; no 2026-season outcome in fitting |
| Preprocessing | training-fold median plus missing indicator for numeric fields; training-fold one-hot with unknown ignored for categorical fields |
| Calibration | none |
| Distribution | `NFL_M1_EMPIRICAL_PAIRED_RESIDUAL` / `NFL_M1_EMPIRICAL_CORRELATED_RESIDUAL_V1` |
| Residual authority SHA-256 | `34b95d42f55d5be424752b73b4450d8b8d17a9a3e434659ac0b0cc9a185984be` |
| Simulation | 10,000 paired draws, seed 731001 |

`verify_frozen_m1` rehashed and reloaded the artifact without fitting. Reload fixture `6ff9b65fb1963d75462a3d9e257483e9746e44bc07bf39d2d372cdb5a64de691` reproduced its saved point output. The production verifier then reconstructed every selected paired-score population from whole draw counts and reconciled home/tie/away probabilities, expected home/away scores, margin PMF and total PMF.

## Operational scope

The handoff is prospective from **2026-09-20T17:00:00Z** (Sunday 1:00 PM ET), the first governed kickoff. It does not relabel Week 1 or DET at BUF on September 17. The discovery snapshot contains 255 scheduled games from that effective time through the retained 2026 schedule, each bound to the current immutable forecast, source bundle and population hash at issuance. Later eligible pre-kickoff revisions remain admissible only when they match the exact model, configuration, artifact, 10,000-draw contract and pass AISP's independent package/population verification.

The handoff deliberately leaves optional `forecastPopulations` empty. Pre-pinning that optional map would make any legitimate future `FINAL_PREGAME` revision fail `FORECAST_NOT_LISTED`. Exact seed hashes remain inside the hash-pinned handoff under `seedForecastPopulationEvidence`; AISP independently hashes every imported population before governance.

## Integrity gates

| Gate | Result |
|---|---|
| Artifact, manifest, feature and residual identities | PASS |
| Training chronology and 2026-outcome exclusion | PASS |
| Team orientation and nflverse identities, including LA/LAR alias | PASS |
| Source/cutoff/publication/kickoff chronology | PASS |
| Three-way probability mass | PASS |
| Paired score, margin and total accounting | PASS |
| Deterministic artifact reload | PASS |
| AISP exact handoff adapter | PASS; production label allowed for the supplied bytes |
| Week 2 scoring readiness | PASS; 16/16 `READY_AFTER_GOVERNED_FINAL` |
| Consumer operator pin | **PENDING**; live status `NOT_RECEIVED` |
| Natural invocation after activation | NOT APPLICABLE UNTIL PINNED |

## Existing evidence

Week 1 contains 16 independent game assessments: 10/16 expected winners correct (62.5%), log loss 0.715185, three-way summed Brier 0.491197, pooled team-score MAE 9.131, margin MAE 12.150 and total MAE 12.886. These are small-sample diagnostics and do not show profitability, stable calibration or permanent model validity.

The failed missingness, cold-start, EPA-matchup and schedule-adjusted challengers remain rejected. Personnel capture remains Development evidence and is not an M1 input. The play-level simulator is explicitly barred as a substitute.

## Owners and activity

The sole operational scheduler is the running `ASP Backend 8010` S4U task, which owns Model Studio generation/import jobs internally. No second NFL forecast scheduler was created. The separate `ASP NFL Personnel Evidence Capture` task remains unchanged. `ASP MLB V18 Research Publisher` remains unchanged.

This work made zero provider calls, incurred zero cost, wrote no AISP record or database row, changed no decision/position/settlement, and executed no model fit. Two immutable Model Studio exchange publications were created; the second is the final commit-bound successor. Existing forecasts and exchange objects were not changed.

