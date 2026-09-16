# Producer capability matrix

`DIRECT` means the immutable forecast carries the channel or retained population. `DERIVABLE` means exact enumeration over that same paired population is supported without a model run. `APPROXIMATE` is restricted to an explicitly requested cross-game independence calculation. `UNSUPPORTED` fails closed. `BLOCKED` means the model could support the query but the exact required immutable population is unavailable or does not pass identity verification.

| Sport / forecast | Model and exact retained identity | Winner / tie | Spread / total | Same-game joint | Cross-game | Material limitation |
|---|---|---|---|---|---|---|
| MLB FINAL_PREGAME | `MLB_V18_HGB_PA`; registry `3e8dcc1c…640c2`; representative object `2f07648c…bdac` | Direct; final tie mass is zero under the simulator’s extra-inning policy | Derivable from unrestricted 5,000 paired finals | Derivable by score-cell intersection | Unsupported | Requires exact confirmed-lineup/starter inputs; no research challenger population may substitute. |
| NFL CURRENT / eligible revision | `NFL_M1_XGBOOST`, `NFL_M1_2026_RESEARCH_SHADOW_V1`; binary `7bec0664…8fd`; representative package `5c459282…f117` | Direct three-way; tie mass is retained but not a separately validated overtime/tie model | Derivable from 10,000 paired finals | Derivable | Unsupported | Exact forecast/supplement and consumer gates remain separate. |
| NBA joint baseline | `NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1`; Ridge `063e69ff…70ef`; package `00cd4990…97a9d` | Direct joint channel; zero ties after declared support treatment | Derivable from 10,000 paired finals | Derivable | Unsupported | Joint winner is separate from Elo; close-score arm was not selected. |
| NBA point/Elo | `NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1`; package `85e3d741…e2e0`; forecast bytes `27f766e3…8767` | Elo winner direct, independently estimated | Unsupported (`drawCount=0`) | Unsupported | Unsupported | Expected scores are not a probability distribution. |
| CFB prospective baseline | `CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1`; binary `cb3f2029…70bb6`; package `223bbc35…ff76` | Direct joint channel; tied finals resampled under declared method | Derivable from 10,000 paired finals | Derivable | Unsupported | Ridge-margin, Elo and joint winner channels are distinct; research-only. |

The full machine-readable identities, inputs, limitations and authority are in `capability-matrix.json`. Package SHA values identify retained examples and implementation contracts; a consumer must still bind the exact game forecast and verify its exact package and population hashes before querying.

No cross-game population is retained. Default cross-game behavior is an error. The optional `INDEPENDENCE_ASSUMPTION` mode convolves marginal leg-state distributions, reports no effective draw count or MCSE, and must stay labeled research-only.
