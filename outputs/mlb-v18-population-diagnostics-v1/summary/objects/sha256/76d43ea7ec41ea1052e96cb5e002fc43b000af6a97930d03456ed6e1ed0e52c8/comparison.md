The three declared cases are selected retrospective explanations, with unchanged original forecasts. This report contains 3 of 3 completed captures. Cells show **observed / simulated mean [5th–95th percentile]**; event-mix cells show **observed / simulated mean**. A/H denotes away/home, and BB+ includes walks, HBP and catcher interference.

| Game | Total PA | Runs A/H | HR and BB+ A/H | Starter BF A/H | Relief BF A/H | Maximum inning runs A/H |
|---|---|---|---|---|---|---|
| PIT–CHC 824630 | 72 / 76.19 [66–89] | A: 3 / 4.46 [0–10]<br>H: 4 / 3.99 [0–9] | A HR 1 / 1.14; BB+ 5 / 3.65<br>H HR 2 / 0.93; BB+ 6 / 3.99 | A: 25 / 18.91 [11–25]<br>H: 27 / 18.68 [11–25] | A: 8 / 18.28 [9–29]<br>H: 12 / 20.33 [11–31] | A: 3 / 2.42 [0–5]<br>H: 2 / 2.25 [0–5] |
| NYM–NYY 823496 | 76 / 75.73 [66–88] | A: 12 / 4.06 [0–10]<br>H: 2 / 5.21 [1–11] | A HR 6 / 1.18; BB+ 2 / 3.71<br>H HR 1 / 1.74; BB+ 1 / 3.88 | A: 26 / 18.14 [10–24]<br>H: 22 / 18.73 [11–25] | A: 8 / 19.32 [10–30]<br>H: 20 / 19.54 [10–31] | A: 5 / 2.22 [0–5]<br>H: 1 / 2.69 [1–6] |
| PHI–ATL 824870 | 75 / 75.72 [65–88] | A: 2 / 4.54 [0–10]<br>H: 12 / 4.20 [0–9] | A HR 2 / 1.16; BB+ 0 / 3.24<br>H HR 2 / 1.18; BB+ 6 / 3.12 | A: 9 / 18.57 [11–25]<br>H: 25 / 18.57 [10–25] | A: 34 / 18.22 [10–29]<br>H: 7 / 20.38 [11–32] | A: 1 / 2.43 [0–5]<br>H: 8 / 2.33 [0–5] |

The JSON retains all eight sampled class counts, probability-sum distributions, observed rates, per-draw simulated rates, pitching exposure and outs, conditional removal innings, inning scoring, transition counts and inclusive empirical tails.

Probability sums describe evolving simulated situations. They are not predictions captured before actual PAs. Mean per-draw class/PA ratios and exposure-weighted ratios of totals are reported separately. Inclusive tails include ties and are descriptive, not p-values or calibration tests.

Starter and relief BF/outs use the pitching-team axis. Runs while a role is active include inherited runners and differ from official pitcher responsibility. Multiple-out PAs are a net-outs proxy, not the grounded-double-play statistic. Third-out LOB excludes unfinished walkoff halves; walkoff remnants are reported separately.

Observed classes use the existing event mapping and V2’s explicit record type. V2 index and game physical hashes verify exactly without normalization; V1’s transport qualification remains historical. V2 “bases before” flags are still empty and were rejected; preceding saved end states and half-inning resets pass runner conservation and official LOB checks. The full slate contains 1,176 play records but 1,173 completed PAs; this subset has 224 records and 223 completed PAs. Runner activity within completed PAs remains separately retained: class-run and transition measures use whole-play boundaries, not terminal-class-only causation.

No fitting, forecast change or intervention choice is made here. Historical training/feature chronology remains uncertified. The detailed JSON preserves original cutoffs and source references.

Reproduce: `.venv/Scripts/python.exe scripts/summarize_mlb_v18_population_diagnostics_v1.py`.
