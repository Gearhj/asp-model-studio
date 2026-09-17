# Defensive modeling report

## Candidate assessed

The candidate is a team-level empirical-Bayes BIP conversion adjustment. It is the only defensive resolution supported across the retained point-in-time population. A player-position model would require authentic pregame defensive alignments and player fielding estimates; contact-location modeling would additionally require governed batted-ball geometry.

The adjustment operated on 64,232 BIP PAs within a 99,646-PA assessment. It reduced conditional BIP log loss by 0.0000543 and Brier by 0.0000172. Overall eight-class log loss fell by 0.0000350. The 95% date-block interval for the overall log-loss difference was `[-0.0001426, +0.0000624]`, so the candidate failed the frozen gate.

## Ablation

| Variant | Prior strength | Development BIP log loss | Status |
|---|---:|---:|---|
| Team defense, less shrinkage | 100 | 0.609871568 | Not selected |
| Team defense, moderate shrinkage | 400 | 0.609861086 | Not selected |
| Team defense, heavy shrinkage | 1,600 | 0.609852980 | Selected before assessment |
| Exact V18 | n/a | n/a | Assessment baseline |
| Selected team defense | 1,600 | n/a | `NO_INCREMENTAL_VALUE` |

No post-assessment cap, window, class, or team slice search was run. The tiny monotonic Development preference for more shrinkage and the uncertain assessment effect argue against expanding this architecture.

Figures are retained outside Git under `C:\Users\james\asp-data-staging\mlb\structural-innovation-v1\figures` and hash-bound in `ARTIFACT_INDEX.json`.

\n