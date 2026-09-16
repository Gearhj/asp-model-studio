These are three selected retrospective explanation cases, with unchanged original forecasts. Cells show **observed / simulated mean [5th–95th percentile]**; A/H denotes away/home.

| Game | Total PA | Runs A/H | HR A/H | Starter BF A/H | Relief BF A/H | Multiout PA A/H | Third-out LOB A/H |
|---|---|---|---|---|---|---|---|
| PIT–CHC 824630 | 72 / 76.19 [66–89] | A: 3 / 4.46 [0–10]<br>H: 4 / 3.99 [0–9] | A: 1 / 1.14 [0–3]<br>H: 2 / 0.93 [0–3] | A: 25 / 18.91 [11–25]<br>H: 27 / 18.68 [11–25] | A: 8 / 18.28 [9–29]<br>H: 12 / 20.33 [11–31] | A: 0 / 0.94 [0–3]<br>H: 2 / 0.89 [0–3] | A: 9 / 7.27 [3–12]<br>H: 5 / 7.11 [3–11] |

Partial result; pending sidecars: 823496, 824870.

The JSON retains all eight sampled class counts, probability-sum distributions, observed rates, per-draw simulated rates, pitching exposure and outs, conditional removal innings, inning scoring, transition counts and inclusive empirical tails.

Probability sums describe evolving simulated situations. They are not predictions captured before actual PAs. Mean per-draw class/PA ratios and exposure-weighted ratios of totals are reported separately. Inclusive tails include ties and are descriptive, not p-values or calibration tests.

Starter and relief BF/outs use the pitching-team axis. Runs while a role is active include inherited runners and differ from official pitcher responsibility. Multiple-out PAs are a net-outs proxy, not the grounded-double-play statistic. Third-out LOB excludes unfinished walkoff halves; walkoff remnants are reported separately.

Observed classes use the existing event mapping. The source export’s empty “bases before” flags were rejected; preceding saved end states and half-inning resets passed runner conservation and official LOB checks. Source bytes and normalized transport hashes remain qualified. The full slate contains 1,176 play records but 1,173 completed PAs; this subset has 224 records and 223 completed PAs.

No fitting, forecast change or intervention choice is made here. Historical training/feature chronology remains uncertified. The detailed JSON preserves original cutoffs and source references.

Reproduce: `.venv/Scripts/python.exe scripts/summarize_mlb_v18_population_diagnostics_v1.py --partial`.
