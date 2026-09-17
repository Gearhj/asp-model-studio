# NFL M1 production baseline readiness and activation report

**Decision: `NFL_M1_PRODUCTION_BASELINE_ACTIVATED`.**

Model Studio published the exact production handoff, AISP pinned and accepted it, and the existing canonical backend completed a natural import during an uninterrupted 40-minute verification window. `/api/v1/research/nfl-production-status` reports `NFL_M1_PRODUCTION_BASELINE_PROSPECTIVE_MONITORING`, `accepted=true`, `production_label_allowed=true`, and the exact handoff SHA-256. The effective boundary remains prospective at 2026-09-20 13:00 ET.

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
| Consumer operator pin | PASS; exact path and SHA pins active |
| Natural invocation after activation | PASS; job `72ebb57f-3905-4e57-a331-a3ed8c8eeaaa` succeeded |

## Existing evidence

Week 1 contains 16 independent game assessments: 10/16 expected winners correct (62.5%), log loss 0.715185, three-way summed Brier 0.491197, pooled team-score MAE 9.131, margin MAE 12.150 and total MAE 12.886. These are small-sample diagnostics and do not show profitability, stable calibration or permanent model validity.

The failed missingness, cold-start, EPA-matchup and schedule-adjusted challengers remain rejected. Personnel capture remains Development evidence and is not an M1 input. The play-level simulator is explicitly barred as a substitute.

## Owners and activity

The sole operational scheduler is the running `ASP Backend 8010` S4U task, which owns Model Studio generation/import jobs internally. No second NFL forecast scheduler was created. The separate `ASP NFL Personnel Evidence Capture` task remains unchanged. `ASP MLB V18 Research Publisher` remains unchanged.

Activation made zero provider calls, incurred zero cost, changed no decision/position/settlement policy, and executed no model fit. The natural importer reused all 515 selected bundles and 3,005 forecast children, created zero forecast rows, and opened no unlisted objects. Two immutable Model Studio exchange publications remain unchanged; existing forecasts and exchange objects were not changed.



## Activation closeout

The existing `ASP Backend 8010` task was restarted once outside the NFL final-pregame window. The new listener was PID `48856`, created at 2026-09-17 18:16:41.395060 ET. Scheduler ownership token `c236b61a188145e8a0b692d5ee81ae0f` was claimed at 18:16:41 ET; the scheduler-start log is bounded by the first immediate scheduled run at 18:16:48.993743 ET.

The quiet verification ran through 18:56:41 ET with 152 observations. The PID, listener count and scheduler-owner token never changed. The natural `import-nfl-shadow-forecast-bundle` run `72ebb57f-3905-4e57-a331-a3ed8c8eeaaa` succeeded from 18:48:51.916069 through 18:50:29.026846 ET. It reused 515/515 selected bundles and all 3,005 forecast children, created no replacement row, and did not open an unlisted object.

All 15 Sunday/Monday Week 2 games pass the production binding: exact model, configuration, artifact, immutable package, verified population, 10,000 draws and pre-kickoff publication. DET-BUF remains `BEFORE_EFFECTIVE_FROM`. Week 2 remains 16/16 `READY_AFTER_GOVERNED_FINAL`.

The 16:44, 17:15 and 17:21 backend replacements observed during the earlier attempt coincide with separately documented AISP deployment work. The uninterrupted quiet window supplies no evidence of an autonomous repeated-supervisor defect; no supervisor or task-definition change was made.
