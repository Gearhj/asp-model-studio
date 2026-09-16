# Score-limited V18: exploratory comparison

Correct winner picks: **0/3 → 0/3**. Wrong → right: **0**; right → wrong: **0**.

Unrestricted → score-limited. Mean errors are lower-is-better. The limited forecasts condition on the actually retained draws; neither scores nor sequences are clipped.

| September 12 game; actual A–H | Retained / 5,000; excluded | Pick A → S | p(Home) A → S | Expected A/H: A → S | Log loss A → S (Δ) | Brier A → S (Δ) | Team-score MAE A → S | Total error A → S |
|---|---:|---|---:|---|---:|---:|---:|---:|
| NYM–NYY 823496; 12–2 | 4,600; 8.00% | NYY → NYY | 0.6386 → 0.6365 | 4.062/5.207 → 3.871/4.879 | 1.0178 → 1.0120 (-0.0057) | 0.4078 → 0.4052 (-0.0027) | 5.573 → 5.504 | 4.731 → 5.250 |
| PHI–ATL 824870; 2–12 | 4,660; 6.80% | PHI → PHI | 0.4850 → 0.4871 | 4.538/4.200 → 4.307/3.994 | 0.7236 → 0.7192 (-0.0044) | 0.2652 → 0.2630 (-0.0022) | 5.169 → 5.156 | 5.262 → 5.700 |
| PIT–CHC 824630; 3–4 | 4,656; 6.88% | PIT → PIT | 0.4738 → 0.4725 | 4.458/3.993 → 4.237/3.779 | 0.7470 → 0.7497 (+0.0027) | 0.2769 → 0.2782 (+0.0014) | 0.733 → 0.729 | 1.451 → 1.016 |

Aggregate mean metrics (unrestricted → score-limited): winnerLogLoss 0.82945 → 0.82699 (Δ -0.00246); winnerBrier 0.31664 → 0.31548 (Δ -0.00116); meanTeamScoreAbsoluteError 3.82483 → 3.79640 (Δ -0.02843); totalRunsAbsoluteError 3.81447 → 3.98856 (Δ +0.17409).

p(Home) simulation MCSE, baseline / candidate / paired candidate-minus-baseline: NYM–NYY 0.00679/0.00709/0.00198; PHI–ATL 0.00707/0.00732/0.00191; PIT–CHC 0.00706/0.00732/0.00192.

The saved JSON includes each arm's home, away, total and margin distribution scores, exact final-revision identities, exclusion categories, retained populations, and original forecast bindings.

These post-outcome selected games are exploratory. Winner-pick accuracy is not offered-price betting economics. MCSE measures simulation sampling only; it does not bound model/input error or establish recurring improvement. Future executions are not scored here.

Missing population counters remain separately reported in the bound coverage inventory. No missing game is counted as zero exclusions or a supported challenger.

```powershell
.venv/Scripts/python.exe -B scripts/score_mlb_v18_score_limited_v1.py
```
