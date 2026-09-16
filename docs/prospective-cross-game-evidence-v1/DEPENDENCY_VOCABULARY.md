# Dependency vocabulary

Every pre-outcome envelope contains every dependency key. Each assertion uses `CONFIRMED`, `RULED_OUT` or `UNKNOWN`; missing evidence is never encoded as false. Every assertion also records evidence source, observed time, rule or reviewer, confidence, review state and related game IDs.

| Key | Meaning |
|---|---|
| `SHARED_PARTICIPANT` | A canonical team, fighter or other participant appears in both games |
| `DOUBLEHEADER` | MLB same-date games share a team under the frozen doubleheader rule |
| `SHARED_VENUE` | The games use the same venue or operational site |
| `GEOGRAPHIC_WEATHER_SYSTEM` | Governed evidence links both games to the same weather system or geographic condition |
| `SHARED_WEATHER_INPUT_REVISION` | Both forecasts depend on one exact weather-input revision |
| `SHARED_PLAYER_ROSTER_UNCERTAINTY` | A player, roster or availability uncertainty affects both games |
| `SHARED_INJURY_SOURCE_UNCERTAINTY` | Both forecasts rely on the same unresolved injury-source evidence |
| `TOURNAMENT_POSTSEASON_LINKAGE` | Tournament or postseason structure links the games |
| `SEQUENTIAL_INCENTIVE` | An earlier result can change later-game incentives |
| `STANDINGS_QUALIFICATION` | Standings, qualification or elimination state links the games |
| `SHARED_SOURCE_INCIDENT` | A known upstream source incident affects both forecasts |
| `SHARED_FEATURE_PIPELINE_INCIDENT` | A known feature/pipeline incident affects both forecasts |
| `AMBIGUOUS_REVISION` | The controlling forecast or evidence revision is not unambiguous |
| `PARTICIPANT_REPLACEMENT` | A participant replacement is known or unresolved |
| `UNSUPPORTED_DEPENDENCY_STATE` | Another material dependency cannot be represented or ruled out |

`CONFIRMED` requires supporting evidence. `RULED_OUT` requires an explicit rule or review. `UNKNOWN` is the required state when evidence is missing, incomplete or not reviewed.

The pure pair classifier independently derives shared-participant and MLB doubleheader state from canonical participant identities. It excludes a shared-participant pair from the unrelated-game category even if an envelope assertion was mistakenly left unknown.
