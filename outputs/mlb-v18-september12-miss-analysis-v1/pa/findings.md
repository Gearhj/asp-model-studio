PA calibration is **unavailable for all 15 games**, including the seven funded selections. The immutable forecasts retain 270 eight-class initial lineup vectors, all keyed as simulation inputs. None is a retained prediction tied to an actual observed PA.

| Game | MLBAM | Funded side | Initial vectors | Actual-PA captures found | Calibration |
|---|---|---|---:|---:|---|
| COL–DET | 824224 | — | 18 | 0 | Unavailable |
| NYM–NYY | 823496 | NYY | 18 | 0 | Unavailable |
| PIT–CHC | 824630 | PIT | 18 | 0 | Unavailable |
| BAL–TOR | 822768 | — | 18 | 0 | Unavailable |
| LAA–WSH | 822685 | LAA | 18 | 0 | Unavailable |
| SD–SF | 823170 | SF | 18 | 0 | Unavailable |
| KC–BOS | 824712 | KC | 18 | 0 | Unavailable |
| LAD–MIA | 823819 | — | 18 | 0 | Unavailable |
| CLE–MIN | 823657 | — | 18 | 0 | Unavailable |
| HOU–TB | 822927 | — | 18 | 0 | Unavailable |
| CIN–MIL | 823737 | — | 18 | 0 | Unavailable |
| PHI–ATL | 824870 | PHI | 18 | 0 | Unavailable |
| CWS–STL | 823009 | CWS | 18 | 0 | Unavailable |
| TEX–AZ | 825035 | — | 18 | 0 | Unavailable |
| SEA–ATH | 824955 | — | 18 | 0 | Unavailable |

All eight classes—strikeout, walk/HBP/CI, home run, single, double, triple, ball-in-play out and other reach—therefore have unavailable predicted-versus-observed PA counts/rates, residuals, log loss and Brier. Unavailable values are null, not zero.

The template records retain batter SLG, pitcher HR allowance and platoon fields, but these describe initial hypothetical matchups. They do not provide coverage of actual batter/pitcher encounters or changing base/out states. Simulation traces and event totals are handled separately in the exposure analysis.

The previous doubles finding used frozen fold5 predictions for May 2–August 13. It cannot establish whether the excess recurred on September 12 or explain the funded losses. The reviewed exchange simulator manifest lists 2025 appearance labels and current pregame context, not an actual-PA prediction/outcome export.

A future calibration check requires original actual-PA vectors with stable PA and player identities, original pre-PA clocks, and governed matching outcomes. No missing capture was reconstructed here.

Machine evidence: [availability.json](<C:/Users/james/asp-model-studio/outputs/mlb-v18-september12-miss-analysis-v1/pa/availability.json>). Reproduce from the repository root:

```powershell
.venv/Scripts/python.exe outputs/mlb-v18-september12-miss-analysis-v1/pa/build-availability.py
```
