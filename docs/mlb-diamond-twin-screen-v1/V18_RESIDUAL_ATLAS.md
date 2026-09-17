# V18 residual atlas

Positive differences are candidate minus V18 and therefore worse.

| Variant | Coverage | Conditional BIP log loss | BIP Brier | Eight-class log loss | Summed eight-class Brier |
|---|---:|---:|---:|---:|---:|
| Actual starting defense oracle | 100% | +0.001824 | +0.000791 | +0.001181 | +0.000574 |
| Prior-date carry-forward starters | 100% | +0.001854 | +0.000782 | +0.001200 | +0.000541 |
| Catcher identity only | 100% | +0.000218 | +0.000092 | +0.000141 | +0.000068 |
| Infield identity only | 100% | +0.000908 | +0.000386 | +0.000588 | +0.000292 |
| Outfield identity only | 100% | +0.000616 | +0.000274 | +0.000399 | +0.000193 |

The oracle conditional-BIP log-loss interval was +0.001104 to +0.002538. The carry-forward interval was +0.001108 to +0.002577. Neither reveals a stable residual improvement. The ordering of ablations is descriptive reused evidence; it was not used to select another model.

Unsupported residual systems were not approximated with substitute variables. There is no exact-population joint game-draw artifact, so joint energy/CRPS scoring is unavailable. Game metrics in this study are a realized-PA exposure proxy and are not frozen pregame distributions.
