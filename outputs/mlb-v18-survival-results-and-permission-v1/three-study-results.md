Three frozen component studies; **lower log loss, Brier and CRPS are better**. B = baseline, C = candidate, Δ = C − B. Score pairs are away–home. Probability deltas use percentage points; expected-run deltas are forecast changes, without an intrinsic better direction.

| Date / game / actual away–home | Arm | P(home win) | Expected away–home | Log loss / Brier | CRPS home | CRPS away | CRPS total | CRPS margin |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-11 COL–DET 2–6<br>HGB starter duration | B | 61.38% | 4.0254–5.0294 | 0.488086 / 0.149150 | 0.950315 | 1.017968 | 1.036580 | 1.823977 |
|  | C | 61.88% | 4.0854–5.0410 | 0.479973 / 0.145313 | 0.943934 | 1.041377 | 1.036392 | 1.856097 |
|  | Δ | +0.50 pp | +0.0600 / +0.0116 | -0.008113 / -0.003837 | -0.006381 | +0.023409 | -0.000188 | +0.032120 |
| 2026-09-12 NYM–NYY 12–2<br>Conditional transition | B | 63.86% | 4.0620–5.2074 | 1.017770 / 0.407810 | 1.732290 | 6.374331 | 3.090449 | 8.800355 |
|  | C | 63.74% | 4.0722–5.1768 | 1.014455 / 0.406279 | — | — | — | — |
|  | Δ | -0.12 pp | +0.0102 / -0.0306 | -0.003315 / -0.001531 | — | — | — | — |
| 2026-09-12 KC–BOS 1–5<br>Conditional transition | B | 61.54% | 4.2808–5.3468 | 0.485483 / 0.147917 | 0.728096 | 1.778797 | 1.952848 | 1.795344 |
|  | C | 61.42% | 4.3110–5.3304 | 0.487435 / 0.148842 | 0.736254 | 1.790963 | 1.964468 | 1.820268 |
|  | Δ | -0.12 pp | +0.0302 / -0.0164 | +0.001952 / +0.000924 | +0.008158 | +0.012166 | +0.011620 | +0.024924 |

NYM–NYY’s baseline CRPS remains available; candidate distributions were not retained, so its candidate CRPS and CRPS deltas are unavailable. No reconstruction was performed.

Both arms favored the home team in each game. Detroit and Boston won; the Yankees lost. Candidate winner scores were slightly better for COL–DET and NYM–NYY, and worse for KC–BOS. Mean absolute errors improved only for home runs in COL–DET and KC–BOS; away, total and margin mean errors worsened. In NYM–NYY, home, away and margin mean errors improved, while total mean error worsened. Distribution scores differ: COL–DET home and total CRPS improved (total by only 0.000188), but away and margin CRPS worsened; all four KC–BOS CRPS worsened.

These single realized results do not establish recurring gain, a recurring failure, or superiority. Each 5,000-draw simulation represents one observed game; the studies remain separate.

Final revisions are matched within each pair. All three use a derived last-play completion proxy; no explicit provider final-publication timestamp is claimed. Historical training/feature chronology qualifications remain.

Saved evidence: [scoring receipt](<C:/Users/james/asp-model-studio/outputs/mlb-v18-survival-starter-coverage-v1/scoring/objects/sha256/00bb026ffab2f678569c9462f884604df4572f9aa5430ad8e97caec3d54c98a8/scoring-findings.json>); [matched final bindings](<C:/Users/james/asp-model-studio/outputs/mlb-v18-survival-starter-coverage-v1/scoring/final-handoff-binding.json>).

- [COL–DET / MLBAM 824227](<C:/Users/james/asp-model-studio/outputs/mlb-v18-survival-starter-coverage-v1/scoring/objects/sha256/369dcf1d57baba128f1a9ecc7148dede43e28ce39e3afeb8c9d66c0a00b01149/paired-game-score.json>) — final `d999da7f-0830-44cc-989c-a3e6df028f33`, revision 1.
- [NYM–NYY / MLBAM 823496](<C:/Users/james/asp-model-studio/outputs/mlb-v18-survival-starter-coverage-v1/scoring/objects/sha256/24ea5638ab73004327c419781920debc48254a37b83e76d2949b48f82d762bac/paired-game-score.json>) — final `0a69c509-90cd-43dc-a8d5-19b199a43a11`, revision 1.
- [KC–BOS / MLBAM 824712](<C:/Users/james/asp-model-studio/outputs/mlb-v18-survival-starter-coverage-v1/scoring/objects/sha256/2bbcbebcfd49a9d13de21466aab9913678bccc998ad7bbbb9c75dfbbf7fc18ae/paired-game-score.json>) — final `858406c1-d709-48df-9cdb-7192c9fa57e3`, revision 1.

Reproduce the pinned saved-receipt extraction from the repository root:

```powershell
.venv/Scripts/python.exe outputs/mlb-v18-survival-results-and-permission-v1/extract-three-study-results.py
```
