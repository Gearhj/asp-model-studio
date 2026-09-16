Frozen September12 exposure evidence

All15 forecasts retain5000 total-PA and terminal-inning draws, but only one detailed event trace each. Actual exposure/run-conversion labels are unavailable in the inspected exchange; missing is not zero. No model correction is selected.

| Game | Mean simulated PA | PA5–95% | Extra innings | One trace starterBF away/home | Actual comparison |
|---|---:|---|---:|---|---|
| COL–DET (824224) | 75.75 | 65–89 | 9.72% | 23/20 | Unavailable |
| NYM–NYY (823496) | 75.73 | 66–88 | 8.34% | 18/9 | Unavailable |
| PIT–CHC (824630) | 76.19 | 66–89 | 10.20% | 18/20 | Unavailable |
| BAL–TOR (822768) | 75.93 | 66–88 | 9.40% | 22/11 | Unavailable |
| LAA–WSH (822685) | 76.35 | 66–89 | 9.48% | 15/18 | Unavailable |
| SD–SF (823170) | 76.80 | 66–90 | 10.46% | 23/21 | Unavailable |
| KC–BOS (824712) | 76.89 | 66–90 | 9.22% | 23/20 | Unavailable |
| LAD–MIA (823819) | 77.44 | 67–90 | 9.14% | 14/20 | Unavailable |
| CLE–MIN (823657) | 76.52 | 66–89 | 10.44% | 10/19 | Unavailable |
| HOU–TB (822927) | 75.43 | 65–89 | 9.86% | 17/21 | Unavailable |
| CIN–MIL (823737) | 75.19 | 65–88 | 10.60% | 22/21 | Unavailable |
| PHI–ATL (824870) | 75.72 | 65–88 | 10.06% | 19/13 | Unavailable |
| CWS–STL (823009) | 76.19 | 65–89 | 10.42% | 17/18 | Unavailable |
| TEX–AZ (825035) | 76.98 | 66–89 | 8.74% | 14/23 | Unavailable |
| SEA–ATH (824955) | 75.91 | 66–89 | 10.34% | 12/21 | Unavailable |

The BF numbers describe one retained simulation draw, not a typical exposure estimate or an actual start. Half-inning PA/runs, sampled hit/walk/other-reach classes, reliefBF and multiple-out PA proxies are saved pergame in findings.json. Runner identity paths, exact stranded runners and ground-double-play types are unobserved. The latest final reader reports starter evidence unavailable because its pair-specific frozen input descriptor is missing; that is not proof of zero actual pitcher labels in the database.

Retained diagnostics show exposure mechanics and one event path pergame. They cannot attribute any September12 miss to PA miscalibration, starter duration, sequencing or run conversion. A mean run residual and a single trace are insufficient. No exposure/transition parameter change is selected.

One bounded hypothesis remains untested: starter removal and anonymous relief exposure may affect run forecasts. The smallest useful comparison is the already authorized future baseline/survival pair with retained per-draw exposure counters and exact actual usage. This is not evidence that duration explains these losses.

Run: `.venv/Scripts/python.exe scripts/analyze_mlb_v18_september12_exposure_v1.py`

Findings SHA256: d6d38f061b0b8ace7a6df2332210dec17da212965c1d29191747ad2c63c1f2c5
