# Ablation, uncertainty, and segment results

## Frozen configurations

Only one major architecture was opened. Its Development-only ablation varied the empirical-Bayes prior strength while holding the class scope and ±0.35 cap fixed.

| Architecture | Prior | Development conditional BIP log loss | Development BIP Brier | Assessment opened |
|---|---:|---:|---:|---|
| Team BIP conversion | 100 | 0.609871568 | 0.209539019 | No |
| Team BIP conversion | 400 | 0.609861086 | 0.209534511 | No |
| Team BIP conversion | 1,600 | 0.609852980 | 0.209530833 | Yes |

The assessment comparison is exact V18 versus the selected 1,600-prior candidate. No cap, window, team, archetype, park, or outcome-class choice was altered after assessment.

## Uncertainty

The resampling unit is calendar date, not PA and not simulation draw. There were 103 blocks and 2,000 deterministic replicates. Candidate-minus-baseline eight-class log loss was -0.000035027 with 95% interval `[-0.000142612, +0.000062384]`. Summed Brier was -0.000003030 with interval `[-0.000051769, +0.000043496]`.

The interval crossing zero is the direct reason for `NO_INCREMENTAL_VALUE`.

## Coverage and segments

Matched coverage was 100% after the frozen delayed-game exclusions. No intended-region segment was registered because the candidate applies to every PA with nonzero BIP mass. Post-assessment team, park, handedness, or contact-heavy slices were not searched. Season stability is not estimable from the single reused 2024 assessment fold. Game-level winner, score, margin, total, CRPS, and energy metrics were not run after the PA module failed its advancement gate.

The missing segment and game-level metrics are unavailable results, not zero effects.

