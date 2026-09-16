# Pair construction and estimation

## Game standardization

Each ledger is reduced to one row per canonical game with sport, date, teams, regular/postseason status, predicted home/away/tie probabilities, actual winner, predicted and actual scores, and chronology evidence. Probability mass must reconcile to one. Duplicate canonical game identities fail the run.

NFL outcome classes are governed integers (`0=away`, `1=tie`, `2=home`), verified against retained scores before calculation. NBA and CFB finals have no tie mass in the admitted ledgers.

## Pairs

Pairs are formed only between different games on the same local calendar date. Within each sport/date, every unordered combination appears once. Between sports, each cross-product game pair appears once. Pair IDs sort canonical game IDs, so reverse duplicates cannot enter. A same-game pair is a hard error.

The primary population excludes postseason pairs and any shared-team pair. Shared team means an overlapping team identity within a same-sport pair. It is detected before the primary filter even though the retained population contains zero such pairs.

Start separation uses exact retained start times where present:

- `SAME_START_WINDOW`: at most 60 minutes apart;
- `INTERMEDIATE_START`: more than 60 and at most 180 minutes;
- `SEPARATED_START`: more than 180 minutes;
- `UNKNOWN`: one or both exact starts unavailable.

Potential sequential incentive is a deliberately conservative label for same-sport postseason pairs separated by more than 180 minutes. It is a locator, not proof that incentives changed.

## Residuals and joint events

The five residuals are winner (`actual home win - p_home`), margin, total, home score and away score. Pearson estimates use exchangeable pair products after endpoint standardization. Spearman estimates rank unique game residuals before forming pair products. Covariance uses the same pair orientation. A game residual is verified to be identical everywhere that game appears.

Two joint events are reported:

1. both home teams win, using `p_home_A × p_home_B`;
2. both model-favored teams win, using the larger of each game's home/away probabilities.

No pair is selected using an outcome or sportsbook price. Raw product calibration combines marginal calibration and dependence; residual correlations separately locate common model error.

## Uncertainty and effective sample size

Every interval resamples complete date/slate clusters 2,000 times with seed `20260916`. Game pairs within a date are never treated as independent. Reports include independent date count and a pair-weighted Kish effective slate count, `(sum n_s)^2 / sum(n_s^2)`. The latter describes cluster-weight concentration and is not a replacement for the bootstrap interval.

Normal-approximation p-values derive from whole-slate bootstrap standard errors. Holm adjustment covers the five residual correlations inside each sport-pair segment. Practical conclusions use the frozen effect-size, precision, reliability and coverage gate rather than p-values.
