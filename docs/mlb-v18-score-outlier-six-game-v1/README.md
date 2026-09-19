# Fixed V18 / six-game exploratory study

Research-only code around original retained V18 score populations. No model execution, acquisition, production change, quote substitution or probability construction.

The predeclared design is `DESIGN.md` (physical SHA256 `fb3325e25ae184363fb346a8096e7dda32b8b499d98ef1be02009b664c262fd2`). Evidence cutoff is September19 2026 at15:17:03.359113 UTC. Source adapters gate identity/date metadata before outcomes, apply the nine-game quarantine, exclude protected August14-27 payloads, and retain source hashes.

Run from this worktree using the existing runtime Python:

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' -B scripts/run_mlb_v18_six_game_study.py
```

The default output is `C:\Users\james\asp-model-studio\outputs\mlb-v18-score-outlier-six-game-20260919-v1`. Its `REPORT.md`, joinable `game_results.csv`, contributor table, exact comparison tables and two PNG charts are the user deliverable. `SOURCE_INDEX.json` and delivery/verification receipts bind provenance. The historical CSV remains Claude's wager authority; legacy positions are kept separate.

Observed result:90 supported completed games,31 selected/59nonselected; all90 team-six references complete,66 H2H available but only3 complete. The fixed team-six blend increased team MAE0.114runs and margin MAE0.211runs; total MAE changed−0.011. No reliable concentration of losing wagers among the fixed2run unusual-mean group. H2H complete-six evidence remains insufficient. Seven uncertainty-defect positions remain actual records. This does not justify changing V18, selection policy, weights or thresholds.

Focused synthetic verification:

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' -B -m unittest tests.test_mlb_v18_six_game_statistics -v
```
