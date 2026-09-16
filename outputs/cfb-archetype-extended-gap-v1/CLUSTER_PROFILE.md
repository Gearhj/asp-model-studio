# Cluster profile

Family: KMeans; Development complexity settings 2, 3, 4; frozen selection k=2. Labels are ordered by centroid Elo, not by outcome.

The same earlier-Development imputer and scaler transform home and away team states independently. Eight inputs describe scoring, yardage, turnovers and strength. Team ID, conference and target outcomes are excluded.

| k | Bootstrap ARI mean | Silhouette | Quality gate | Supported ordered matchup cells |
|---:|---:|---:|---|---:|
| 2 | 0.976 | 0.246 | True | 4/4 |
| 3 | 0.894 | 0.161 | True | 9/9 |
| 4 | 0.868 | 0.164 | True | 11/16 |

## Cluster 0

3850 team appearances, 123 distinct teams; largest team fraction 0.017, largest conference fraction 0.138.

| Variable | Original-unit centroid |
|---|---:|
| points_for_season | 24.834 |
| points_allowed_season | 31.494 |
| total_yards_season | 373.012 |
| yards_allowed_season | 421.366 |
| turnovers_season | 1.668 |
| takeaways_season | 1.370 |
| elo | 1456.011 |
| prior_margin_shrunk | -3.796 |

Conference counts: Conference USA: 531, Mid-American Conference: 516, Sun Belt Conference: 453, Mountain West Conference: 412, Atlantic Coast Conference: 354, American Conference: 349, Big Ten Conference: 338, Pac-12 Conference: 284, Southeastern Conference: 281, Big 12 Conference: 184, FBS Independents: 148.
Season counts: 2016: 590, 2017: 619, 2018: 575, 2019: 615, 2020: 303, 2021: 578, 2022: 570.

## Cluster 1

4296 team appearances, 121 distinct teams; largest team fraction 0.016, largest conference fraction 0.140.

| Variable | Original-unit centroid |
|---|---:|
| points_for_season | 35.221 |
| points_allowed_season | 21.191 |
| total_yards_season | 445.862 |
| yards_allowed_season | 345.131 |
| turnovers_season | 1.268 |
| takeaways_season | 1.666 |
| elo | 1556.089 |
| prior_margin_shrunk | 5.472 |

Conference counts: Southeastern Conference: 601, Atlantic Coast Conference: 551, Big Ten Conference: 544, Big 12 Conference: 480, Pac-12 Conference: 442, American Conference: 390, Mountain West Conference: 326, Conference USA: 309, Sun Belt Conference: 266, Mid-American Conference: 222, FBS Independents: 165.
Season counts: 2016: 658, 2017: 647, 2018: 691, 2019: 633, 2020: 277, 2021: 692, 2022: 698.

## Migration and interpretation

The selected two clusters primarily separate stronger scoring/score-prevention and yardage states from weaker states. These variables already enter Ridge; structural stability alone does not establish added predictive information. Points and margins are points per game, yardage is yards per game, turnovers/takeaways are counts per game, and Elo is on its original rating scale.

- development: 743/7434 consecutive within-season appearances changed cluster (10.0%).
- reused_validation: 263/2715 consecutive within-season appearances changed cluster (9.7%).
- reused_2025: 140/1368 consecutive within-season appearances changed cluster (10.2%).

ARI is based on ten calendar-week bootstrap refits including preprocessing. Full per-fold profiles show temporal changes and sensitivity to k. Migration measures observed state changes, not a causal change in team talent. Conference concentration is inspected, never used as a cluster input. No favorable cell is promoted independently.
