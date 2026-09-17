# Counterfactual materiality

This calculation holds the realized PA exposure fixed and moves the fitted BIP log-odds effect from average to the development-exposure-weighted 10th or 90th percentile. Full-unit scenarios use the 10th/90th percentiles of observed assessment lineup effects. It is noncausal and not a pregame forecast.

| Replacement | Mean absolute opposing-run change | Mean absolute win-probability change | Team-games moving ≥2 pp |
|---|---:|---:|---:|
| Average to elite shortstop | 0.223 | 3.12 pp | 97.1% |
| Average to poor shortstop | 0.212 | 2.95 pp | 96.3% |
| Average to elite center field | 0.254 | 3.54 pp | 98.2% |
| Average to poor center field | 0.251 | 3.50 pp | 98.9% |
| Average to elite catcher identity | 0.251 | 3.51 pp | 98.1% |
| Average to poor catcher identity | 0.260 | 3.62 pp | 99.0% |
| Average to elite full unit | 0.686 | 9.50 pp | 100% |
| Average to poor full unit | 0.794 | 10.86 pp | 100% |

These large mechanical changes are not evidence of useful defense information. The same fitted effects worsened proper scores out of period, so the substitution calculation shows sensitivity to the adjustment, not predictive value or causal run prevention. The detailed 10,096-row distribution is retained in `counterfactual-materiality.parquet`.
