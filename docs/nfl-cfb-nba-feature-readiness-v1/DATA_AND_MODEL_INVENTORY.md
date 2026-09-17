# Data and model inventory

| Sport | Bound historical source | Grain | Current assessed model family | Features | Targets | Distribution status |
|---|---|---|---|---:|---|---|
| NFL | permitted projection of governed NFL Gold, SHA `30737340…9427` | one completed game | fixed `NFL_M1_XGBOOST` score research clone | 197 | home/away points; native probability diagnostic | operational artifacts separate; this run does not rerun simulation |
| CFB | permitted projection of CFB Gen 1 point-in-time features, SHA `03f33aee…458b` | one completed game | Ridge alpha100 | 35 | margin, total, home/away points | existing paired-residual research artifact unchanged |
| NBA | permitted projection of NBA recent score/date features, SHA `680ffe43…277a` | one completed regular-season game | corrected Ridge alpha100 points plus separate Elo | 78 | home/away points; Elo home win | existing paired-residual joint baseline unchanged |

The NFL active producer identity is `NFL_M1_XGBOOST` / `NFL_M1_2026_RESEARCH_SHADOW_V1`; this analysis uses earlier-origin clones rather than its current all-history binary. CFB's retained research configuration is `CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1`. NBA point/Elo is `NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1`; joint research is `NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1`.

The source projections are reproducibility inputs, not complete recovery artifacts or certified historical forecast captures. Production binaries, raw histories, runtime state and exchange packages remain external. `BOUND_INPUT_RECEIPT.json` records exact paths, bytes, dates and hashes used here.
