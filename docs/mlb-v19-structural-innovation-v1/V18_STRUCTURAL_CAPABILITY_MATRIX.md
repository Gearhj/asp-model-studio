# V18 structural capability matrix

The labels distinguish what V18 actually uses from data merely present elsewhere in Model Studio.

| Baseball structure | Status | Actual V18 support and limitation |
|---|---|---|
| Batter identity | Fully modeled | Canonical ID binds each of 18 ordered pregame templates to batter rolling features. Identity itself is not a learned categorical effect. |
| Pitcher identity | Fully modeled for announced starters | Canonical starter ID binds opposing templates to pitcher histories. Current ordinary V18 does not select named relievers later in the game. |
| Batting order | Fully modeled at freeze | Exactly nine ordered batters per side; confirmed-lineup authority is required. Later substitutions are not forecast. |
| Batter handedness | Fully modeled | Left/switch indicators and missingness are model inputs. |
| Pitcher handedness | Fully modeled | Throws-left and platoon interaction are model inputs. |
| Pitch repertoire | Indirectly represented | Rolling fastball/breaking/offspeed shares summarize repertoire coarsely. Individual pitch types and sequencing are absent. |
| Pitch shape and movement | Absent | No vertical/horizontal movement or release-shape feature in the accepted V18 feature contract. |
| Velocity | Indirectly represented | Rolling average fastball velocity and explicit missingness; no pitch-level in-game velocity path. |
| Contact quality | Absent | No exit velocity, launch angle, hard-hit or barrel probability in the accepted V18 population. |
| Spray/tendency | Absent | No pull/opposite-field or batted-ball direction feature. |
| Park | Indirect/mechanical | Game/venue identity exists in source layers, but the accepted 234-field V18 PA vector has no certified park-factor module. |
| Weather/roof | Blocked by timing/source | Context code retains missing indicators; authoritative pregame weather/roof values are not established for the historical V18 population. |
| Catcher | Mechanical in retrospective replay only | Retrosheet replay identifies starting catcher. V18 does not fit catcher framing/game-calling effects or bind a prospective catcher. |
| Umpire | Present in Silver, absent from V18 | Umpire identities exist in Retrosheet-derived tables but lack certified historical pregame assignment timing and a fitted effect. |
| Named fielders and positions | Present historically, absent prospectively | Retrospective lineup records can reconstruct fielding positions; accepted V18 game inputs carry batting order and starters, not a governed nine-fielder defensive alignment. |
| Defensive skill | Absent | No OAA/DRS/UZR or player fielding latent effect. The V19 candidate uses a team conversion fallback only. |
| Defensive shifts/alignment | Absent | No shift state or positioning geometry. |
| Runner advancement | Fully modeled mechanically | Empirical transition distribution conditions on PA class, outs, and base state, with runner conservation. |
| Double plays | Indirectly represented | Double plays are included within `BIP_OUT` and transition outcomes, not as a distinct PA class or defender-specific probability. |
| Stranding | Fully modeled mechanically | Inning-ending transitions clear bases and record surviving runners as stranded. |
| Baserunner skill | Absent | Runner identities can be propagated, but individual speed/advancement talent is not in the accepted transition probability. |
| Starter removal | Separate research support | A fitted survival component exists separately; unchanged V18 uses its frozen governing configuration and does not gain V19 authority here. |
| Bullpen usage | Mechanical/anonymous | Existing game simulation can continue after starter exposure through templates; named reliever availability and selection are not established in the accepted ordinary path. |
| Reliever availability/fatigue | Blocked by data and timing | Team recent bullpen workload has a missing authority path; named reliever workloads are not available across the chronological population. |
| Manager tendencies | Absent | No manager-level removal, pinch-hit, bullpen-selection, or steal/bunt policy effect. |
| Pinch hitters/substitutions | Retrospective oracle only | Replay can observe them, but pregame input validation explicitly prohibits actual substitutions/relievers. Prospective V18 holds the starting lineup. |
| Scratches/postponements | Governed operationally | Input readiness and immutable forecast rules fail closed or issue a later version; they are not probabilistic participant events inside V18. |
| Game state | Fully modeled | Inning, half, outs, base state, and batting-score differential evolve inside simulation and feed the PA probability adapter. |
| Extra innings | Fully modeled mechanically | Automatic runner on second and continued innings until a winner/watchdog. |

Key implementation anchors are `stage3_game_inputs.py`, `stage3_game_probability_adapter.py`, `whole_game_monte_carlo.py`, `base_out_transition.py`, and `participant_replay.py`.

