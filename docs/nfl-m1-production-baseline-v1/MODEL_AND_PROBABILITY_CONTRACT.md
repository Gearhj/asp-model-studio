# NFL M1 model and probability contract

The controlling baseline is the unchanged `NFL_M1_XGBOOST` point model plus the frozen empirical paired-residual distribution. The fitted model produces home and away point means from 197 point-in-time features. A single residual row is sampled as a home/away pair, then both nonnegative latent scores are stochastically rounded. Pairing preserves the residual dependence present in the training authority.

Every forecast retains one joint population of 10,000 integer `(awayScore, homeScore)` draws. Expected scores, margin, total and the outcome probabilities are all functions of this same population. A distribution is admissible only when:

- cell counts sum to exactly 10,000;
- `P(HOME) + P(TIE) + P(AWAY) = 1`;
- score means reproduce the published expected scores;
- margin and total PMFs reproduce the joint population;
- the population's canonical cell hash verifies;
- source cutoff and publication precede kickoff;
- team orientation and canonical/nflverse identities agree.

Tie mass is a distinct outcome and is never allocated to either team. A final tie is evaluated as `TIE`. A two-way moneyline tie pushes/refunds only when the governing house rules say so. The empirical discrete tie mass is retained but has not been separately validated as a dedicated tie model.

Calibration is `NONE`. The production label means a controlling operational baseline with prospective monitoring. It makes no profitability claim and grants no change to wagering thresholds, bankroll or settlement policy.

The optional AISP `forecastPopulations` enforcement map is empty because future revision ids cannot be known before the canonical owner publishes them. The pinned handoff records every seed population for audit; AISP's stored-population adapter independently reconstructs and hashes any later revision and requires the exact model, artifact and 10,000-draw identity.

