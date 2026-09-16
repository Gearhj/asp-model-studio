# Score-limited V18: exploratory comparison

Correct winner picks: **0/3 → 0/3**. Wrong → right: **0**; right → wrong: **0**.

Unrestricted → score-limited. Mean errors are lower-is-better. Fixed limits: **5 runs per team per played half-inning and 14 runs per team per game**. The limits are symmetric and strict exceedances exclude complete draws. The limited forecasts condition on the actually retained draws; neither scores nor sequences are clipped.

| September 12 game; actual A–H | Retained / 5,000; excluded | Pick V18 → limited | p(Home) V18 → limited | Expected A/H: V18 → limited | Log loss V18 → limited (Δ) | Brier V18 → limited (Δ) | Team-score MAE V18 → limited | Total error V18 → limited |
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

## Separate prospective comparison

The September 13 game below is excluded from all historical accuracy and error aggregates above. Its outcome was not accessed. This is a distinct score-limited configuration, separate from survival and transition studies.

| Future game | Retained / 5,000; excluded | Pick V18 → limited | p(Home) V18 → limited | Expected A/H V18 → limited | Freeze UTC | Original cutoff UTC |
|---|---:|---|---:|---|---|---|
| CIN–MIL 823734 | 4,722; 5.56% | CIN → CIN | 0.4962 → 0.4939 | 4.112/3.854 → 3.942/3.668 | 16:44:13.820226Z | 17:55:00Z |

p(Home) MCSE: V18 0.00707; limited 0.00728; paired difference 0.00172. This measures simulation precision, not uncertainty about predictive improvement.
