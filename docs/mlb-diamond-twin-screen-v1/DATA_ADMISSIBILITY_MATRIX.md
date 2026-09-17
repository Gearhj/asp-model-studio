# Data and admissibility matrix

| Evidence | Classification | Retained support | Consequence |
|---|---|---|---|
| Target starting defensive lineup and position | `ORACLE_ONLY` | Retrosheet-derived 2024 Silver starts at positions 2–9, complete for all assessed team-games | Used only in quarantined actual-participant oracle. |
| Prior expected defensive lineup | `PRIOR_ONLY_RECONSTRUCTABLE` | Latest complete starting defense from a strictly earlier date | Tested as a carry-forward research proxy; historical publication timing remains uncertified. |
| Player defensive performance | `PRIOR_ONLY_RECONSTRUCTABLE` / `UNTIMESTAMPED` | Development-only player-position residual effects can be estimated; no governed direct fielding-quality table is bound | Cannot support deployment or causal player quality claims. |
| Batter pull/opposite-field/contact direction | `MISSING` | No governed prior spray feature in exact V18 population | Matchup defense test blocked. |
| Pitcher ground-ball/fly-ball/contact tendency | `MISSING` | Exact V18 rows retain pitch mix and velocity, not governed GB/FB tendency | Pitcher × defense test blocked. |
| Catcher framing/blocking/throwing | `MISSING` | Catcher starter identity only | Catcher-quality screen blocked. |
| Pitcher-catcher identity | `ORACLE_ONLY` | Actual target catcher and pitcher identities can be joined retrospectively | Not admissible as pregame input. |
| BIP direction, launch angle, exit velocity | `MISSING` | Retained Silver pitch rows expose BIP type but not the required measured coordinates/quality | Spatial ceiling blocked. |
| Actual positional alignment | `ORACLE_ONLY` | Starting field positions, not measured shifts or coordinates | Used in identity oracle only. |
| Manager identity | `ORACLE_ONLY` / `UNTIMESTAMPED` | Retrospective team-game manager ID | No point-in-time manager-policy claim. |
| Starter hook state | `MISSING` for the exact common population | Separate diagnostic evidence exists outside this common assessment contract | Manager/hook screen not run. |
| Named reliever availability/workload/usage | `MISSING` | Anonymous bullpen mechanism only | Bullpen selection screen blocked. |
| Bench and substitution history | `ORACLE_ONLY` | Retrospective lineup substitutions exist | Cannot be prospective participation evidence. |
| Park context | `AVAILABLE_PREGAME` | Bound V18 context and park identities | Already in baseline; no new park challenger. |
| Weather context | `AVAILABLE_PREGAME` but incomplete | V18 missingness/context fields exist; no new governed weather source was acquired | Not expanded in this screen. |
| 2024 final scores | `ORACLE_ONLY` / reused diagnostic | Quarantined Silver team-game rows | Used only for explicitly labeled game proxy. |

Both Silver manifests are `SILVER_NORMALIZED`, `modelEligible=false`, and `approvedForTraining=false`. No classification in this table changes that authority barrier.
