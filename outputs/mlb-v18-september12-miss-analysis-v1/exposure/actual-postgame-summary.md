Actual postgame exposure is supported for all 15 frozen September 12 games. All 30 starter BF/outs values match the admitted official records. These are retrospective labels, never pregame covariates.

Actual PA can increase because more hitters reach base or score. It does not independently identify the cause of a run miss. The frozen simulation has 5,000 PA counts but only one retained usage/transition trace, so no population starter-BF or run-conversion bias is claimed.

A/H always means away/home. LOB uses the linescore team field; the separate batting aggregate LOB has a different meaning and is retained separately. Movement tallies are source records, not reconstructed conditional transition opportunities.

| Game | Actual PA | Sim PA mean [5–95%] | Starter BF A/H | Relief BF A/H | Hits A/H | BB+HBP A/H | GIDP A/H | LOB A/H | Runs 7+ A/H | Fields |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| COL–DET 824224 | 91 | 75.75 [65–89] | 22/22 | 26/21 | 12/18 | 5/7 | 1/1 | 9/13 | 1/7 | 12/12 |
| NYM–NYY 823496 | 76 | 75.73 [66–88] | 26/22 | 8/20 | 14/7 | 2/1 | 0/1 | 3/5 | 7/0 | 12/12 |
| PIT–CHC 824630 | 72 | 76.19 [66–89] | 25/27 | 8/12 | 6/5 | 5/6 | 0/2 | 9/5 | 0/2 | 12/12 |
| BAL–TOR 822768 | 77 | 75.93 [66–88] | 17/9 | 22/29 | 6/11 | 4/7 | 0/2 | 8/8 | 2/1 | 12/12 |
| LAA–WSH 822685 | 84 | 76.35 [66–89] | 28/26 | 15/15 | 4/11 | 7/4 | 0/0 | 7/10 | 5/2 | 12/12 |
| SD–SF 823170 | 81 | 76.80 [66–90] | 25/26 | 9/21 | 13/8 | 6/0 | 0/1 | 13/1 | 1/3 | 12/12 |
| KC–BOS 824712 | 67 | 76.89 [66–90] | 21/26 | 13/7 | 5/10 | 1/2 | 0/0 | 5/5 | 0/2 | 12/12 |
| LAD–MIA 823819 | 74 | 77.44 [67–90] | 22/16 | 16/20 | 4/7 | 5/7 | 0/1 | 6/10 | 1/0 | 12/12 |
| CLE–MIN 823657 | 71 | 76.52 [66–89] | 7/21 | 29/14 | 5/7 | 3/5 | 0/0 | 5/8 | 0/0 | 12/12 |
| HOU–TB 822927 | 68 | 75.43 [65–89] | 22/23 | 11/12 | 5/7 | 3/4 | 0/1 | 6/6 | 0/1 | 12/12 |
| CIN–MIL 823737 | 86 | 75.19 [65–88] | 25/17 | 19/25 | 14/14 | 3/6 | 1/0 | 6/7 | 4/0 | 12/12 |
| PHI–ATL 824870 | 75 | 75.72 [65–88] | 9/25 | 34/7 | 7/13 | 0/6 | 2/2 | 3/7 | 1/3 | 12/12 |
| CWS–STL 823009 | 83 | 76.19 [65–89] | 6/11 | 35/31 | 6/8 | 10/6 | 1/0 | 9/9 | 2/1 | 12/12 |
| TEX–AZ 825035 | 77 | 76.98 [66–89] | 16/31 | 20/10 | 13/6 | 2/3 | 1/0 | 8/7 | 0/0 | 12/12 |
| SEA–ATH 824955 | 91 | 75.91 [66–89] | 24/12 | 12/43 | 23/5 | 7/3 | 2/0 | 9/8 | 10/0 | 12/12 |

All feeds contain per-inning runs and runner sequences. The JSON preserves raw event types without introducing a new eight-class mapping. Frozen actual-PA probability captures and comparable population usage/transition diagnostics remain unavailable.

Reproduce from the same retained files: `.venv/Scripts/python.exe scripts/summarize_mlb_v18_september12_postgame_v1.py` (an existing result is reused).

Evidence: [actual-postgame-summary.json](C:\Users\james\asp-model-studio\outputs\mlb-v18-september12-miss-analysis-v1\exposure\actual-postgame-summary.json), [starter-evidence-supplement-v3.json](C:\Users\james\asp-model-studio\outputs\mlb-v18-september12-miss-analysis-v1\exposure\starter-evidence-supplement-v3.json).
