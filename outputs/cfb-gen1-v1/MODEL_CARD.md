# College Football Gen 1 model card

Selected point model: `ridge_alpha100`. Chronological Elo remains the separate winner benchmark.

Scope: FBS-versus-FBS, regular-season weeks 1–14, full-game final scores including overtime. Research only.

Validation: margin MAE 13.272, total MAE 12.913. Reused 2025 historical holdout: margin MAE 13.032, total MAE 12.531.

Inputs: schedule-derived chronology, neutral and conference indicators, Elo, rest/support, score trends, total-yards and turnover summaries when available, and shrunk prior-season summaries. No odds, injuries, quarterbacks, lineups, weather, recruiting, transfers or player strength.

Point-model winner probabilities use a logistic mapping fitted once on 2016–2022 chronological Development predictions. Elo probabilities remain separately identified.

The paired residual distribution uses only earlier season-forward residual donors, retains home/away residual pairs, floors negative sampled scores, applies stochastic integer rounding, and explicitly resamples any tied discrete final from the same earlier donor population. This represents final-score uncertainty; it is not the older overtime simulator.

Historical performance is reconstructed evidence, not prospective accuracy. Conference championship classification is unavailable, 2020 is a distinct schedule regime, and 2026 schedule coverage is partial.
