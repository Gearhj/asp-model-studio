# ASP Model Studio NFL Gold Data Foundation Report

## Terminal result

The mandatory NFL core is complete, deeply verified, registered in the existing Sports Data Warehouse, and inactive/read-only. The active MLB authority and every MLB project remain unchanged. No NFL project was created and no model was fitted, scored, calibrated, compared, or promoted.

- Starting branch: `codex/2025-to-2026-walk-forward`
- Starting HEAD: `726708bd698ce007d372f359020d544ab5615349`
- Implementation branch: `codex/nfl-gold-data-foundation`
- Bronze manifest SHA-256: `06fe566284bd7854a6d9d938185dafbb07f96efc7c8a0a454de75413ea66329a`
- Bronze partitions: 326
- Foundation manifest SHA-256: `f3e142f05bf9f503168b256db4e05d83c373e94425e1c3147d0817fdf37f3bbb`
- Dataset version: `asp.nfl.gold-data-foundation.v1:sha256:f3e142f05bf9f503168b256db4e05d83c373e94425e1c3147d0817fdf37f3bbb`
- Registration: `nfl-foundation-d92a5517-8cd3-56ed-8869-6d486193a00b` (`active=false`)
- Verified objects: 28 (26 Silver, 2 Gold), 7,829,486 aggregate rows
- External staging root: `C:\Users\james\asp-data-staging\nfl`
- Exhaustive machine-readable evidence: `C:\Users\james\asp-data-staging\nfl\reports\current-foundation.json`

The machine-readable report contains every exact source partition, content hash, schema fingerprint, release/update timestamp, season/game-type schedule and PBP matrix, per-season source count, object manifest, limitation, and rights record used below.

## 1. Sources acquired and actual coverage

All eight mandatory families are `COMPLETE`. Sixteen of seventeen optional families are `COMPLETE`; `contracts` is the sole unavailable optional family and is explicitly recorded as `RELEASE_ASSET_ABSENT` rather than blocking the core.

| Source family | Required | Status | Partitions | Rows | Actual season/date coverage | Latest source update |
|---|---:|---|---:|---:|---|---|
| schedules/results/market fields | yes | COMPLETE | 1 | 7,548 | seasons 1999–2026; 1999-09-12–2027-01-10 | 2026-08-29T12:36:35Z |
| play-by-play | yes | COMPLETE | 27 | 1,279,628 | seasons 1999–2025; 1999-09-12–2026-02-08 | 2026-08-26T07:33:10Z |
| teams | yes | COMPLETE | 1 | 36 | non-seasonal reference | 2026-03-27T15:49:46Z |
| players/identifiers | yes | COMPLETE | 1 | 25,066 | non-seasonal reference | 2026-08-29T13:33:30Z |
| seasonal rosters | yes | COMPLETE | 107 | 142,615 | seasons 1920–2026 | 2026-08-29T12:55:38Z |
| weekly rosters | yes | COMPLETE | 25 | 909,308 | seasons 2002–2026 | 2026-08-29T12:55:36Z |
| weekly player statistics | yes | COMPLETE | 27 | 476,159 | seasons 1999–2025 | 2026-08-26T07:35:24Z |
| weekly team statistics | yes | COMPLETE | 27 | 14,531 | seasons 1999–2025 | 2026-08-26T07:35:27Z |
| snap counts | no | COMPLETE | 14 | 324,611 | seasons 2012–2025; 2012 is a governed zero-row release | 2026-02-09T13:39:50Z |
| participation/personnel | no | COMPLETE | 10 | 478,989 | seasons 2016–2025 | 2026-02-10T18:54:07Z |
| NGS passing | no | COMPLETE | 1 | 5,933 | seasons 2016–2025 | 2026-02-28T07:26:51Z |
| NGS receiving | no | COMPLETE | 1 | 14,731 | seasons 2016–2025 | 2026-02-28T07:27:04Z |
| NGS rushing | no | COMPLETE | 1 | 6,059 | seasons 2016–2025 | 2026-02-28T07:26:57Z |
| FTN charting | no | COMPLETE | 4 | 185,215 | seasons 2022–2025 | 2026-02-10T13:07:59Z |
| injuries/practice reports | no | COMPLETE | 17 | 90,752 | seasons 2009–2025 | 2026-03-18T12:45:31Z |
| depth charts | no | COMPLETE | 26 | 1,905,588 | seasons 2001–2026 | 2026-08-29T12:56:15Z |
| officials | no | COMPLETE | 1 | 21,900 | source asset is not season-partitioned | 2026-02-05T07:41:35Z |
| PFR advanced passing | no | COMPLETE | 8 | 5,424 | seasons 2018–2025 | 2026-02-11T13:24:09Z |
| PFR advanced rushing | no | COMPLETE | 8 | 18,461 | seasons 2018–2025 | 2026-02-11T13:24:12Z |
| PFR advanced receiving | no | COMPLETE | 8 | 35,724 | seasons 2018–2025 | 2026-02-11T13:24:15Z |
| PFR advanced defense | no | COMPLETE | 8 | 62,345 | seasons 2018–2025 | 2026-02-11T13:24:19Z |
| draft picks | no | COMPLETE | 1 | 12,927 | seasons 1980–2026 | 2026-05-05T07:26:30Z |
| combine | no | COMPLETE | 1 | 8,968 | seasons 2000–2026 | 2026-03-12T17:51:56Z |
| trades | no | COMPLETE | 1 | 4,975 | source asset is not season-partitioned | 2026-05-19T15:28:23Z |
| contracts | no | NOT_AVAILABLE | 0 | 0 | no current nflverse release asset | — |

### Exact per-season source row counts

Reference tables without a governed season field are correctly reported as non-seasonal. Every season-scoped source, including sources whose physical rows lack a season column, uses the immutable release partition season as authority.

- Schedules: `1999:259, 2000:259, 2001:259, 2002:267, 2003:267, 2004:267, 2005:267, 2006:267, 2007:267, 2008:267, 2009:267, 2010:267, 2011:267, 2012:267, 2013:267, 2014:267, 2015:267, 2016:267, 2017:267, 2018:267, 2019:267, 2020:269, 2021:285, 2022:284, 2023:285, 2024:285, 2025:285, 2026:272`.
- PBP: `1999:46136, 2000:45491, 2001:44969, 2002:47355, 2003:46811, 2004:46705, 2005:46823, 2006:46299, 2007:46266, 2008:45917, 2009:46519, 2010:46892, 2011:47448, 2012:47834, 2013:48158, 2014:47629, 2015:48122, 2016:47651, 2017:47245, 2018:47109, 2019:47260, 2020:47705, 2021:49922, 2022:49434, 2023:49665, 2024:49492, 2025:48771`.
- Seasonal rosters: `1920:369, 1921:467, 1922:412, 1923:427, 1924:413, 1925:495, 1926:551, 1927:318, 1928:231, 1929:293, 1930:350, 1931:291, 1932:238, 1933:296, 1934:314, 1935:279, 1936:261, 1937:306, 1938:332, 1939:354, 1940:352, 1941:359, 1942:349, 1943:247, 1944:317, 1945:430, 1946:657, 1947:689, 1948:708, 1949:596, 1950:460, 1951:430, 1952:452, 1953:440, 1954:444, 1955:455, 1956:467, 1957:446, 1958:455, 1959:460, 1960:888, 1961:906, 1962:889, 1963:905, 1964:925, 1965:974, 1966:1114, 1967:1196, 1968:1252, 1969:1233, 1970:1225, 1971:1240, 1972:1270, 1973:1280, 1974:1355, 1975:1256, 1976:1410, 1977:1404, 1978:1468, 1979:1460, 1980:1511, 1981:1478, 1982:1505, 1983:1575, 1984:1629, 1985:1527, 1986:1565, 1987:2913, 1988:1608, 1989:1608, 1990:1585, 1991:1732, 1992:1802, 1993:1841, 1994:1750, 1995:1918, 1996:1911, 1997:1923, 1998:1964, 1999:2039, 2000:2046, 2001:2045, 2002:2031, 2003:2034, 2004:2063, 2005:2048, 2006:2061, 2007:2076, 2008:2077, 2009:2104, 2010:2152, 2011:2099, 2012:2120, 2013:2137, 2014:2153, 2015:2190, 2016:3061, 2017:3082, 2018:3142, 2019:3114, 2020:3068, 2021:2961, 2022:3134, 2023:3090, 2024:3216, 2025:3137, 2026:2930`.
- Weekly rosters: `2002:31086, 2003:30938, 2004:31009, 2005:30751, 2006:31323, 2007:31337, 2008:31361, 2009:31632, 2010:31926, 2011:31338, 2012:31431, 2013:31901, 2014:31964, 2015:32098, 2016:35020, 2017:51321, 2018:52238, 2019:51632, 2020:44130, 2021:46696, 2022:46163, 2023:45655, 2024:46579, 2025:46849, 2026:2930`.
- Weekly player stats: `1999:16839, 2000:16623, 2001:16789, 2002:17481, 2003:17232, 2004:17272, 2005:17355, 2006:17214, 2007:17265, 2008:17212, 2009:17690, 2010:17590, 2011:17440, 2012:17419, 2013:17248, 2014:17622, 2015:17613, 2016:17552, 2017:17477, 2018:17414, 2019:17362, 2020:17602, 2021:18969, 2022:18831, 2023:18643, 2024:18983, 2025:19422`.
- Weekly team stats: `1999:517, 2000:514, 2001:510, 2002:526, 2003:534, 2004:534, 2005:534, 2006:534, 2007:534, 2008:534, 2009:534, 2010:534, 2011:534, 2012:534, 2013:534, 2014:534, 2015:534, 2016:534, 2017:534, 2018:534, 2019:534, 2020:538, 2021:570, 2022:568, 2023:570, 2024:570, 2025:570`.
- Snap counts: `2012:0, 2013:23799, 2014:23864, 2015:23842, 2016:23890, 2017:23862, 2018:23877, 2019:23862, 2020:24999, 2021:26468, 2022:26381, 2023:26540, 2024:26615, 2025:26612`.
- Participation: `2016:48434, 2017:47998, 2018:47875, 2019:48034, 2020:48513, 2021:50714, 2022:50150, 2023:46168, 2024:45919, 2025:45184`.
- NGS passing: `2016:573, 2017:575, 2018:578, 2019:576, 2020:581, 2021:608, 2022:603, 2023:620, 2024:614, 2025:605`.
- NGS receiving: `2016:1601, 2017:1422, 2018:1419, 2019:1418, 2020:1520, 2021:1575, 2022:1466, 2023:1473, 2024:1435, 2025:1402`.
- NGS rushing: `2016:579, 2017:595, 2018:594, 2019:588, 2020:596, 2021:618, 2022:617, 2023:623, 2024:601, 2025:648`.
- FTN: `2022:41643, 2023:48225, 2024:48031, 2025:47316`.
- Injuries: `2009:4821, 2010:4491, 2011:4971, 2012:5533, 2013:5070, 2014:5078, 2015:5232, 2016:5115, 2017:5104, 2018:5133, 2019:5392, 2020:5661, 2021:5587, 2022:5682, 2023:5599, 2024:6215, 2025:6068`.
- Depth charts: `2001:36736, 2002:34594, 2003:34298, 2004:28898, 2005:32803, 2006:33721, 2007:38547, 2008:38651, 2009:38423, 2010:38421, 2011:37941, 2012:37312, 2013:37066, 2014:32542, 2015:37058, 2016:36612, 2017:36620, 2018:36560, 2019:36308, 2020:36168, 2021:37487, 2022:37780, 2023:37327, 2024:37312, 2025:554215, 2026:482188`.
- PFR passing: `2018:646, 2019:640, 2020:666, 2021:706, 2022:685, 2023:700, 2024:697, 2025:684`.
- PFR rushing: `2018:2189, 2019:2148, 2020:2266, 2021:2375, 2022:2389, 2023:2380, 2024:2359, 2025:2355`.
- PFR receiving: `2018:4292, 2019:4269, 2020:4428, 2021:4608, 2022:4547, 2023:4594, 2024:4453, 2025:4533`.
- PFR defense: `2018:7277, 2019:7285, 2020:7643, 2021:8442, 2022:7878, 2023:7902, 2024:7992, 2025:7926`.
- Draft: `1980:333, 1981:332, 1982:334, 1983:335, 1984:336, 1985:336, 1986:333, 1987:335, 1988:333, 1989:335, 1990:331, 1991:334, 1992:336, 1993:224, 1994:222, 1995:249, 1996:254, 1997:240, 1998:241, 1999:253, 2000:254, 2001:246, 2002:261, 2003:262, 2004:255, 2005:255, 2006:255, 2007:255, 2008:252, 2009:256, 2010:255, 2011:254, 2012:253, 2013:254, 2014:256, 2015:256, 2016:253, 2017:253, 2018:256, 2019:254, 2020:255, 2021:259, 2022:262, 2023:259, 2024:257, 2025:257, 2026:257`.
- Combine: `2000:321, 2001:321, 2002:320, 2003:319, 2004:335, 2005:331, 2006:328, 2007:326, 2008:330, 2009:327, 2010:326, 2011:329, 2012:324, 2013:332, 2014:333, 2015:322, 2016:332, 2017:327, 2018:336, 2019:336, 2020:337, 2021:464, 2022:324, 2023:319, 2024:321, 2025:329, 2026:319`.

## 2. Canonical table inventory

| Layer | Table | Rows |
|---|---|---:|
| Silver | `dim_nfl_team` | 36 |
| Silver | `dim_nfl_player` | 25,066 |
| Silver | `dim_nfl_game` | 7,548 |
| Silver | `dim_nfl_venue` | 67 |
| Silver | `dim_nfl_season_week` | 590 |
| Silver | `fact_nfl_play` | 1,279,628 |
| Silver | `fact_nfl_drive` | 168,485 |
| Silver | `fact_nfl_team_game` | 15,096 |
| Silver | `fact_nfl_player_game` | 476,159 |
| Silver | `fact_nfl_player_week` | 476,159 |
| Silver | `fact_nfl_team_week` | 14,531 |
| Silver | `snapshot_nfl_weekly_roster` | 909,308 |
| Silver | `snapshot_nfl_seasonal_roster` | 142,615 |
| Silver | `snapshot_nfl_schedule` | 7,548 |
| Silver | `snapshot_nfl_market_line` | 7,388 |
| Silver | `fact_nfl_snap_count` | 324,611 |
| Silver | `fact_nfl_participation` | 478,989 |
| Silver | `fact_nfl_nextgen_player_week` | 26,723 |
| Silver | `fact_nfl_ftn_play_charting` | 185,215 |
| Silver | `snapshot_nfl_depth_chart` | 1,905,588 |
| Silver | `snapshot_nfl_injury_report` | 90,752 |
| Silver | `dim_nfl_official` | 21,900 |
| Silver | `fact_nfl_pfr_advanced` | 121,954 |
| Silver | `dim_nfl_draft_pick` | 12,927 |
| Silver | `dim_nfl_combine` | 8,968 |
| Silver | `fact_nfl_trade` | 4,975 |
| Gold | `gold_nfl_game_pregame_v1` | 7,276 |
| Gold | `gold_nfl_play_state_v1` | 1,109,384 |

No empty contract table was fabricated because the optional contracts source was absent.

## 3. Gold authorities and targets

### Game pregame Gold

- Identity: `gold-table:gold_nfl_game_pregame_v1`
- Object manifest: `c13393c738f7629f4f7ff812069fa5cb29402e9bf08690e8d63586dacf9cd295`
- Rows: 7,276; duplicate game identities: 0
- Coverage: 1999-09-12 through 2026-02-08 (NFL seasons 1999–2025)
- Populations: 6,967 regular-season; 309 postseason (`WC`, `DIV`, `CON`, `SB`); preseason remains separately labelled and is not silently mixed.
- Targets: home points, away points, home win, tie, score differential, total points, overtime, final state.
- Point-in-time rule: `COMPLETED_GAME_DATE_LT_TARGET_GAME_DATE`; same-date results are conservatively unavailable.

### Play-state Gold

- Identity: `gold-table:gold_nfl_play_state_v1`
- Object manifest: `3bfbe3ea89d3c29f19ac1a194fdef71582806a8e4cbf843aa150fb5db2a4e841`
- Rows: 1,109,384; duplicate game/play identities: 0
- Coverage: 1999-09-12 through 2026-02-08
- Source plays: 1,279,628
- Governed exclusions: 170,244, exactly classified as missing game/play ID, missing play type, or noncompetitive `no_play`/kneel/spike state.
- Point-in-time rule: `STATE_AT_PLAY_START_ONLY`; future play state is not included.

The drive authority preserves drive result, scoring indicator, touchdown, field goal, turnover, punt, turnover-on-downs, yards, plays, and first downs. The current source contract does not publish a direct drive-points field or a separate end-of-game result; those fields were not improvised from ambiguous score transitions.

## 4. Exact feature-family catalog

The following lists are immutable, ordered candidate contracts. A listed candidate is not a claim of full-era availability or model value.

- `LONG_HISTORY_CORE` — 197 materialized predictors. Exact order:

```text
season, week, game_type, game_month, game_weekday, neutral_site, division_game, roof, surface, home_days_since_previous_game, away_days_since_previous_game, home_short_week, away_short_week, home_bye_or_long_rest, away_bye_or_long_rest, home_prior_games, away_prior_games, home_prior_season_games, away_prior_season_games, home_source_era_missing, away_source_era_missing, home_points_for_season_to_date, home_points_for_last_4, home_points_for_last_8, home_points_for_last_16, home_points_against_season_to_date, home_points_against_last_4, home_points_against_last_8, home_points_against_last_16, home_offensive_epa_per_play_season_to_date, home_offensive_epa_per_play_last_4, home_offensive_epa_per_play_last_8, home_offensive_epa_per_play_last_16, home_pass_epa_per_play_season_to_date, home_pass_epa_per_play_last_4, home_pass_epa_per_play_last_8, home_pass_epa_per_play_last_16, home_rush_epa_per_play_season_to_date, home_rush_epa_per_play_last_4, home_rush_epa_per_play_last_8, home_rush_epa_per_play_last_16, home_defensive_epa_per_play_season_to_date, home_defensive_epa_per_play_last_4, home_defensive_epa_per_play_last_8, home_defensive_epa_per_play_last_16, home_defensive_pass_epa_per_play_season_to_date, home_defensive_pass_epa_per_play_last_4, home_defensive_pass_epa_per_play_last_8, home_defensive_pass_epa_per_play_last_16, home_defensive_rush_epa_per_play_season_to_date, home_defensive_rush_epa_per_play_last_4, home_defensive_rush_epa_per_play_last_8, home_defensive_rush_epa_per_play_last_16, home_success_rate_season_to_date, home_success_rate_last_4, home_success_rate_last_8, home_success_rate_last_16, home_defensive_success_rate_season_to_date, home_defensive_success_rate_last_4, home_defensive_success_rate_last_8, home_defensive_success_rate_last_16, home_explosive_pass_rate_season_to_date, home_explosive_pass_rate_last_4, home_explosive_pass_rate_last_8, home_explosive_pass_rate_last_16, home_explosive_rush_rate_season_to_date, home_explosive_rush_rate_last_4, home_explosive_rush_rate_last_8, home_explosive_rush_rate_last_16, home_defensive_explosive_pass_allowed_rate_season_to_date, home_defensive_explosive_pass_allowed_rate_last_4, home_defensive_explosive_pass_allowed_rate_last_8, home_defensive_explosive_pass_allowed_rate_last_16, home_defensive_explosive_rush_allowed_rate_season_to_date, home_defensive_explosive_rush_allowed_rate_last_4, home_defensive_explosive_rush_allowed_rate_last_8, home_defensive_explosive_rush_allowed_rate_last_16, home_early_down_success_rate_season_to_date, home_early_down_success_rate_last_4, home_early_down_success_rate_last_8, home_early_down_success_rate_last_16, home_third_down_conversion_rate_season_to_date, home_third_down_conversion_rate_last_4, home_third_down_conversion_rate_last_8, home_third_down_conversion_rate_last_16, home_fourth_down_conversion_rate_season_to_date, home_fourth_down_conversion_rate_last_4, home_fourth_down_conversion_rate_last_8, home_fourth_down_conversion_rate_last_16, home_red_zone_td_play_rate_season_to_date, home_red_zone_td_play_rate_last_4, home_red_zone_td_play_rate_last_8, home_red_zone_td_play_rate_last_16, home_turnover_rate_season_to_date, home_turnover_rate_last_4, home_turnover_rate_last_8, home_turnover_rate_last_16, home_sack_rate_season_to_date, home_sack_rate_last_4, home_sack_rate_last_8, home_sack_rate_last_16, home_penalty_rate_season_to_date, home_penalty_rate_last_4, home_penalty_rate_last_8, home_penalty_rate_last_16, home_seconds_per_play_season_to_date, home_seconds_per_play_last_4, home_seconds_per_play_last_8, home_seconds_per_play_last_16, away_points_for_season_to_date, away_points_for_last_4, away_points_for_last_8, away_points_for_last_16, away_points_against_season_to_date, away_points_against_last_4, away_points_against_last_8, away_points_against_last_16, away_offensive_epa_per_play_season_to_date, away_offensive_epa_per_play_last_4, away_offensive_epa_per_play_last_8, away_offensive_epa_per_play_last_16, away_pass_epa_per_play_season_to_date, away_pass_epa_per_play_last_4, away_pass_epa_per_play_last_8, away_pass_epa_per_play_last_16, away_rush_epa_per_play_season_to_date, away_rush_epa_per_play_last_4, away_rush_epa_per_play_last_8, away_rush_epa_per_play_last_16, away_defensive_epa_per_play_season_to_date, away_defensive_epa_per_play_last_4, away_defensive_epa_per_play_last_8, away_defensive_epa_per_play_last_16, away_defensive_pass_epa_per_play_season_to_date, away_defensive_pass_epa_per_play_last_4, away_defensive_pass_epa_per_play_last_8, away_defensive_pass_epa_per_play_last_16, away_defensive_rush_epa_per_play_season_to_date, away_defensive_rush_epa_per_play_last_4, away_defensive_rush_epa_per_play_last_8, away_defensive_rush_epa_per_play_last_16, away_success_rate_season_to_date, away_success_rate_last_4, away_success_rate_last_8, away_success_rate_last_16, away_defensive_success_rate_season_to_date, away_defensive_success_rate_last_4, away_defensive_success_rate_last_8, away_defensive_success_rate_last_16, away_explosive_pass_rate_season_to_date, away_explosive_pass_rate_last_4, away_explosive_pass_rate_last_8, away_explosive_pass_rate_last_16, away_explosive_rush_rate_season_to_date, away_explosive_rush_rate_last_4, away_explosive_rush_rate_last_8, away_explosive_rush_rate_last_16, away_defensive_explosive_pass_allowed_rate_season_to_date, away_defensive_explosive_pass_allowed_rate_last_4, away_defensive_explosive_pass_allowed_rate_last_8, away_defensive_explosive_pass_allowed_rate_last_16, away_defensive_explosive_rush_allowed_rate_season_to_date, away_defensive_explosive_rush_allowed_rate_last_4, away_defensive_explosive_rush_allowed_rate_last_8, away_defensive_explosive_rush_allowed_rate_last_16, away_early_down_success_rate_season_to_date, away_early_down_success_rate_last_4, away_early_down_success_rate_last_8, away_early_down_success_rate_last_16, away_third_down_conversion_rate_season_to_date, away_third_down_conversion_rate_last_4, away_third_down_conversion_rate_last_8, away_third_down_conversion_rate_last_16, away_fourth_down_conversion_rate_season_to_date, away_fourth_down_conversion_rate_last_4, away_fourth_down_conversion_rate_last_8, away_fourth_down_conversion_rate_last_16, away_red_zone_td_play_rate_season_to_date, away_red_zone_td_play_rate_last_4, away_red_zone_td_play_rate_last_8, away_red_zone_td_play_rate_last_16, away_turnover_rate_season_to_date, away_turnover_rate_last_4, away_turnover_rate_last_8, away_turnover_rate_last_16, away_sack_rate_season_to_date, away_sack_rate_last_4, away_sack_rate_last_8, away_sack_rate_last_16, away_penalty_rate_season_to_date, away_penalty_rate_last_4, away_penalty_rate_last_8, away_penalty_rate_last_16, away_seconds_per_play_season_to_date, away_seconds_per_play_last_4, away_seconds_per_play_last_8, away_seconds_per_play_last_16
```

- `CORE_TEAM_STRENGTH_CANDIDATES` (24): `rolling_offensive_epa_per_play, rolling_defensive_epa_per_play, rolling_pass_epa_per_play, rolling_rush_epa_per_play, rolling_success_rate, rolling_explosive_play_rate, rolling_early_down_efficiency, rolling_third_down_performance, rolling_fourth_down_performance, rolling_red_zone_performance, rolling_goal_to_go_performance, rolling_turnover_rate, rolling_sack_rate, rolling_penalty_rate, rolling_drive_efficiency, rolling_starting_field_position, rolling_points_per_drive, rolling_pace_seconds_per_play, rolling_special_teams_performance, season_to_date_state, previous_4_game_state, previous_8_game_state, previous_16_game_state, exponentially_weighted_recent_state`.
- `QUARTERBACK` (11): `expected_starting_quarterback_id, prior_passing_epa, prior_cpoe, prior_qb_sack_rate, prior_scramble_rate, prior_air_yards, prior_pressure_performance, prior_qb_starts, recent_qb_usage, starting_quarterback_change, quarterback_cold_start`.
- `ROSTER_AND_USAGE` (12): `prior_snap_share, prior_target_share, prior_rush_share, offensive_line_continuity, skill_position_continuity, defensive_unit_continuity, depth_chart_rank_prior_snapshot, roster_addition_count, roster_departure_count, roster_change_count, prior_personnel_usage, prior_formation_usage`.
- `REST_TRAVEL_AND_CALENDAR` (17): `rest_days, short_week, bye_week, consecutive_road_games, travel_distance_miles, time_zone_change_hours, time_zone_change_direction, local_kickoff_time, body_clock_mismatch_hours, is_thursday, is_monday, is_sunday_night, is_holiday, division_game, conference_game, rematch, recent_opponent`.
- `VENUE_AND_WEATHER` (9): `home_away_neutral, stadium, roof, surface, temperature_f, wind_mph, precipitation, weather_description, altitude_feet`.
- `ADVANCED_TRACKING_AND_PARTICIPATION` (16): `prior_motion_rate, prior_play_action_rate, prior_rpo_rate, prior_screen_rate, prior_no_huddle_rate, prior_formation_usage, prior_personnel_usage, prior_pressure_rate, prior_blitz_rate, prior_pass_rusher_count, prior_man_coverage_rate, prior_zone_coverage_rate, prior_route_usage, prior_time_to_throw, prior_ngs_expected_metric, prior_ngs_above_expected_metric`.
- `RECENT_CHARTING` (5): `prior_screen_rate, prior_no_huddle_rate, prior_qb_fault_sack_rate, prior_interception_worthy_rate, prior_catchable_ball_rate`.
- `CURRENT_SEASON` (4): `current_schedule_available, current_roster_snapshot_available, current_depth_snapshot_available, current_completed_game_evidence_available`.
- `PLAY_STATE` (13): `season, week, game_type, quarter, down, distance, yard_line_100, game_seconds_remaining, score_differential, possession_score, defense_score, possession_team_id, defensive_team_id`.
- `MARKET_BENCHMARK_SEPARATE` (8): `away_moneyline, home_moneyline, spread_line, away_spread_price, home_spread_price, total_line, over_price, under_price`.

Era contracts explicitly label unavailable families `SOURCE_NOT_AVAILABLE_FOR_ERA`; they are not zero-filled. Starter, target-game participation, weather timing, travel/time-zone/body-clock, and market-timing fields remain excluded from the materialized core unless their pregame timing authority is proven.

## 5. Market evidence

- Market records: 7,388
- Complete two-sided moneyline: 5,407
- Complete two-sided spread: 5,407
- Complete two-sided total: 5,404
- Semantics: `MARKET_SNAPSHOT_TIMING_UNPROVEN`
- Core predictor eligible: false

No line is called opening or closing without evidence. Market fields are physically separated from the core Gold predictors.

## 6. Current 2026 evidence

- Scheduled games: 272
- Completed games: 0
- Schedule coverage: 2026-09-09 through 2027-01-10
- 2026 seasonal rosters: 2,930 rows
- 2026 weekly rosters: 2,930 rows
- 2026 depth records: 482,188 rows
- Completed-game PBP/stat/snap evidence: `NOT_YET_AVAILABLE`

Nothing was fabricated to represent games that have not occurred.

## 7. Identity, reconciliation, missingness, and exclusions

- Duplicate canonical game identities: 0
- Duplicate canonical play identities: 0
- Duplicate canonical player identities: 0
- Ambiguous identities: 0
- PBP games without schedule identity: 0
- Impossible clock rows: 0
- Impossible score games: 0
- Roster rows with missing/blank GSIS linkage: 53,101, retained and reported; no name/fuzzy match was used
- Distinct non-null weekly-stat player IDs unresolved against player authority: 6 (`0`, `00-0017820`, `00-0005765`, `00-0005532`, `XX-0000001`, `00-0016335`), all from 1999–2000 and retained fail-closed
- Depth rows: 1,905,588; distinct exact source-record identities: 1,905,588; missing source-record identities: 0; missing GSIS linkage: 10,943
- Completed 1999–2025 regular/postseason schedule games without source PBP: 3 — `1999_01_BAL_STL`, `2000_03_SD_KC`, `2000_06_BUF_MIA`
- Play-state exclusions: 170,244 under the single explicit noneligible-state category described above
- Valid empty source: 2012 snap counts, zero rows, retained as a complete zero-row partition

Every Silver object manifest records its exact identity contract, required-field missing counts, schema and schema SHA, source lineage, row/byte/file SHA, season/date coverage, and governance state. The exhaustive schedule/PBP season-and-game-type reconciliation and per-source schema-variant counts are in `current-foundation.json`.

## 8. Temporal integrity

- Game features use only completed team history with `game_date < target_game_date`.
- A same-day earlier result is intentionally unavailable under the conservative contract.
- Rolling windows are lagged and preprocessing/imputation is not fitted here.
- Target-game plays, snaps, participation, results, and actual starters are excluded.
- Play-state Gold contains state at play start only.
- Missing-history and source-era indicators are explicit.
- Source and object manifests bind every cutoff/lineage relationship.

## 9. Current-season synchronization

The existing architecture exposes one locked, audited, atomic sync command:

```powershell
python -m scripts.sync_nfl_current_season --through latest-completed
python -m scripts.sync_nfl_current_season --through latest-completed --mode thursday-correction
python -m scripts.sync_nfl_current_season --through latest-completed --mode schedule-refresh
python -m scripts.sync_nfl_current_season --through latest-completed --mode catch-up
```

Normal runs refresh current schedules, teams/players, rosters/depth, completed-game PBP/stat evidence, snaps and NGS when published. They deep-verify before advancing the inactive NFL registration, preserve prior immutable versions, reject overlapping runs, catch up after downtime, and return `NO_OP` when authority is unchanged. Repeated optional discovery/download/schema gaps remain explicit but idempotent and cannot weaken mandatory identity.

## 10. Rights boundary

- Overall status: `LOCAL_PRIVATE_RESEARCH`
- nflverse/nflverse-data: CC-BY-4.0 attribution retained; third-party field rights are not assumed
- FTN/participation: CC-BY-SA-4.0 attribution/share-alike review retained
- PFR/OverTheCap-derived evidence: public redistribution/commercial reuse prohibited pending source-specific rights review
- Raw and generated datasets remain outside Git; no public redistribution occurred

## 11. Data Warehouse UI

The existing registry/API/UI now display NFL-native dataset/version identity, source family coverage with per-season counts, football table totals, 2026 status, Gold/target/feature-era contracts, reconciliation and missingness, market coverage, source update times, rights, limitations, and latest sync state. The NFL registration is read-only and filtered out of the MLB workflow. No NFL modeling project is created automatically.

The in-app Warehouse route was reached and its authentication guard behaved correctly. Because that browser session was signed out, rendered authenticated evidence was verified through the focused registry/API/presentation contracts rather than by entering user credentials.

## 12. Verification

- Deep Bronze verification: 326/326 immutable partitions rehashed and verified
- Deep Foundation verification: 28/28 object manifests and Parquet objects rehashed and verified
- Focused backend: 32 passed
- Focused Warehouse/frontend contracts: 12 passed
- TypeScript: `npx tsc -b` passed
- Production build: `npm run build` passed
- Build emitted only pre-existing browser-data/chunk-size advisory warnings
- `git diff --check`: required before commit
- Model fits: 0
- Model scores: 0
- Model promotions: 0
- NFL modeling projects created: 0

## 13. Git and safety

- Branch: `codex/nfl-gold-data-foundation`
- `main` remains `924db29511f93909f9d785855bfa056775443690`
- No push or remote mutation
- No NFL raw source data, Parquet, fitted models, or predictions were added by this change; pre-existing unrelated repository artifacts were untouched
- The pre-existing preserved Codex report remains untracked and unchanged; this implementation report is the only new repository documentation artifact
- This report is included in the one focused local implementation commit; the final commit SHA and clean-status proof are reported in the terminal handoff

ASP_NFL_GOLD_DATA_FOUNDATION_COMPLETE
