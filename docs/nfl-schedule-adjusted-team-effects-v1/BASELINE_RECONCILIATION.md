# Baseline reconciliation

## Research clone

The experiment imports `GAME_FEATURES`, `XGBOOST_SCORE_CONFIG`, and `IndependentHomeAwayScoreModel` directly. It uses 197 ordered predictors, seed 731001, independent home/away XGBoost regressors, fold-local preprocessing, and the fixed parameters: 200 estimators, depth 3, learning rate 0.03, minimum child weight 5, subsample 0.9, column sample 0.8, and L2 regularization 5.

For assessment season S, the clone fits on regular-season rows from 2000 through S-1. It does not load or invoke the retained all-history model. Its native normal-CDF home-win probability is used only for non-tie binary diagnostic metrics.

## Retained all-history artifact

- Manifest: `C:/Users/james/asp-data-staging/nfl/m1-modeling-benchmark-v1/research-artifact/objects/sha256/ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9/manifest.json`
- Manifest SHA-256: `ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9`
- Model SHA-256: `7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd`
- Identity: `NFL_M1_XGBOOST` / `NFL_M1_2026_RESEARCH_SHADOW_V1`
- Training: 7,276 games, 1999–2025, cutoff 2026-02-08; `contains2026SeasonOutcome=false`
- Calibration: none
- Promotion state: not promoted; research shadow

That artifact is appropriate for current research forecasts but cannot represent historical out-of-sample predictions for seasons in its training history.

## Operational package

Operational packages bind the all-history point model to exact pregame feature vectors and a separately identified 10,000-draw paired empirical residual population. They expose home/tie/away probabilities and score distributions. This experiment neither regenerated nor modified those packages. Its binary diagnostic probability must not be substituted for the operational three-way convention.

## Reproduction check

The chronological clone reproduced the retained 2022 baseline exactly: 271 games, 5,632 training games, home MAE 6.9577729623, away MAE 7.1445921338, pooled score MAE 7.0511825481, margin MAE 8.9049668717, total MAE 10.6879624757, accuracy 0.6468401487, non-tie log loss 0.6351290073, and Brier 0.2219719966.
