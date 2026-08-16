import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  BarChart3,
  ChevronDown,
  ChevronRight,
  Clipboard,
  Code2,
  Copy,
  Database,
  Download,
  FileCode2,
  FolderTree,
  History,
  Play,
  Save,
  Search,
  ShieldAlert,
  Sparkles,
  Table2,
  TerminalSquare,
  Trash2,
  Wand2,
} from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { getDatasetProfile, listDatasets, type DatasetProfile, type DatasetSummary } from "../lib/datasetLibrary";
import { createEvidence } from "../lib/evidenceGraph";
import {
  deleteSqlQuery,
  downloadBlob,
  exportSqlResultExcel,
  listSavedSqlQueries,
  registerSqlResult,
  runSqlPreview,
  safeSqlAlias,
  saveSqlQuery,
  validateSql,
  type SavedSqlQuery,
  type SqlDatasetRef,
  type SqlPreviewResult,
} from "../lib/sqlDataStudio";
import { useWorkflowStore } from "../state/useWorkflowStore";

type SourceType = "dataset_library_preview" | "saved_query" | "external_metadata";
type AssistantTab = "templates" | "sports" | "mapping" | "governance" | "help";
type BottomTab = "results" | "schema" | "profile" | "messages" | "history" | "lineage";
type ObjectExplorerTab = "tables" | "saved" | "results" | "connectors";
type TemplateCategory =
  | "Sports Data Profiling"
  | "Game & Team Analysis"
  | "Player & Participation"
  | "Event & Drive Analysis"
  | "Temporal Integrity"
  | "Model Development"
  | "Forward Monitoring"
  | "Data Quality";

type SqlTemplate = {
  name: string;
  category: TemplateCategory;
  description: string;
  requiredColumns: string[];
  sql: string;
  tags: string[];
};

type QueryHistoryEntry = {
  id: string;
  timestamp: string;
  sql: string;
  status: string;
  runtimeMs: number;
  rowCount: number;
  tablesUsed: string[];
  warnings: string[];
};

const EXTERNAL_CONNECTORS = ["Snowflake", "BigQuery", "Postgres", "Oracle", "SQL Server", "Teradata", "SAS / Viya source"];
const HISTORY_KEY = "atlas-sql-studio-query-history";

const SQL_SNIPPETS = [
  { label: "Insert SELECT *", sql: "SELECT *\nFROM {table}\nLIMIT 100;" },
  { label: "Insert GROUP BY", sql: "\nGROUP BY {column}\nORDER BY COUNT(*) DESC" },
  { label: "Insert LEFT JOIN", sql: "\nLEFT JOIN {table2} b\n    ON a.{key} = b.{key}" },
  { label: "Insert CASE WHEN", sql: "CASE\n    WHEN {column} IS NULL THEN 'Missing'\n    ELSE 'Populated'\nEND AS {column}_flag" },
  { label: "Insert forecast-cutoff filter", sql: "\nWHERE {source_timestamp} <= {forecast_timestamp}" },
  { label: "Insert count distinct games", sql: "COUNT(DISTINCT {game_id}) AS distinct_games" },
  { label: "Insert event sequence", sql: "ROW_NUMBER() OVER (PARTITION BY {game_id} ORDER BY {date_column}) AS event_sequence" },
];

const SPORTS_TEMPLATES: SqlTemplate[] = [
  template("Dataset row count", "Sports Data Profiling", "Count the rows in the selected immutable dataset version.", [], "SELECT\n    COUNT(*) AS source_row_count\nFROM {table};", ["sports", "profiling"]),
  template("Sports identity overview", "Sports Data Profiling", "Count distinct games, teams, and players without assuming a particular sport grain.", ["game_id", "team_id", "player_id"], "SELECT\n    COUNT(*) AS record_count,\n    COUNT(DISTINCT {game_id}) AS distinct_games,\n    COUNT(DISTINCT {team_id}) AS distinct_teams,\n    COUNT(DISTINCT {player_id}) AS distinct_players\nFROM {table};", ["sports", "identity", "coverage"]),
  template("Sport and league coverage", "Sports Data Profiling", "Inspect the observed sports and leagues represented in the selected dataset.", ["sport_column", "league_column"], "SELECT\n    {sport_column} AS sport,\n    {league_column} AS league,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {sport_column}, {league_column}\nORDER BY records DESC\nLIMIT 100;", ["sports", "league", "coverage"]),
  template("Season coverage", "Sports Data Profiling", "Summarize observed games and records by season.", ["season_column", "game_id"], "SELECT\n    {season_column} AS season,\n    COUNT(DISTINCT {game_id}) AS games,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {season_column}\nORDER BY {season_column};", ["season", "coverage"]),
  template("Observed time range", "Sports Data Profiling", "Inspect the earliest and latest observed timestamps in the registered version.", ["date_column"], "SELECT\n    MIN({date_column}) AS earliest_observation,\n    MAX({date_column}) AS latest_observation,\n    COUNT(*) AS records\nFROM {table};", ["time", "coverage"]),
  template("Forecast target distribution", "Sports Data Profiling", "Profile the observed distribution of the selected forecast target.", ["target_column"], "SELECT\n    {target_column} AS forecast_target,\n    COUNT(*) AS records,\n    COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS population_share\nFROM {table}\nGROUP BY {target_column}\nORDER BY records DESC\nLIMIT 100;", ["target", "distribution"]),
  template("Games by team", "Game & Team Analysis", "Count observed games and records for each team identity.", ["team_id", "game_id"], "SELECT\n    {team_id} AS team,\n    COUNT(DISTINCT {game_id}) AS games,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {team_id}\nORDER BY games DESC\nLIMIT 100;", ["team", "game", "coverage"]),
  template("Home and away identity coverage", "Game & Team Analysis", "Review home and away team identity coverage by game.", ["game_id", "home_team_id", "away_team_id"], "SELECT\n    COUNT(DISTINCT {game_id}) AS games,\n    COUNT(DISTINCT {home_team_id}) AS home_teams,\n    COUNT(DISTINCT {away_team_id}) AS away_teams,\n    SUM(CASE WHEN {home_team_id} IS NULL OR {away_team_id} IS NULL THEN 1 ELSE 0 END) AS records_missing_team_identity\nFROM {table};", ["team", "game", "identity"]),
  template("Team outcomes by season", "Game & Team Analysis", "Summarize the observed target by team and season.", ["team_id", "season_column", "target_column"], "SELECT\n    {season_column} AS season,\n    {team_id} AS team,\n    COUNT(*) AS records,\n    AVG({target_column}) AS average_observed_target\nFROM {table}\nGROUP BY {season_column}, {team_id}\nORDER BY {season_column}, records DESC\nLIMIT 100;", ["team", "season", "target"]),
  template("Venue coverage", "Game & Team Analysis", "Count games and records by observed venue identity.", ["venue_column", "game_id"], "SELECT\n    {venue_column} AS venue,\n    COUNT(DISTINCT {game_id}) AS games,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {venue_column}\nORDER BY games DESC\nLIMIT 100;", ["venue", "game", "coverage"]),
  template("Game score completeness", "Game & Team Analysis", "Count missing home and away final-score fields without inferring results.", ["game_id", "home_score", "away_score"], "SELECT\n    COUNT(DISTINCT {game_id}) AS games,\n    SUM(CASE WHEN {home_score} IS NULL THEN 1 ELSE 0 END) AS missing_home_scores,\n    SUM(CASE WHEN {away_score} IS NULL THEN 1 ELSE 0 END) AS missing_away_scores\nFROM {table};", ["game", "score", "completeness"]),
  template("Schedule density", "Game & Team Analysis", "Count observed games by date for schedule and rest analysis.", ["date_column", "game_id"], "SELECT\n    {date_column} AS game_date,\n    COUNT(DISTINCT {game_id}) AS games\nFROM {table}\nGROUP BY {date_column}\nORDER BY {date_column}\nLIMIT 100;", ["game", "schedule", "time"]),
  template("Player appearance coverage", "Player & Participation", "Count observed games and records for each player identity.", ["player_id", "game_id"], "SELECT\n    {player_id} AS player,\n    COUNT(DISTINCT {game_id}) AS games,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {player_id}\nORDER BY games DESC\nLIMIT 100;", ["player", "participation", "coverage"]),
  template("Players per game", "Player & Participation", "Inspect distinct player coverage at the game grain.", ["game_id", "player_id"], "SELECT\n    {game_id} AS game,\n    COUNT(DISTINCT {player_id}) AS observed_players,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {game_id}\nORDER BY observed_players DESC\nLIMIT 100;", ["player", "game", "coverage"]),
  template("Participation missingness", "Player & Participation", "Measure missing participation state for observed player records.", ["player_id", "participation_column"], "SELECT\n    COUNT(*) AS records,\n    SUM(CASE WHEN {player_id} IS NULL THEN 1 ELSE 0 END) AS missing_player_identity,\n    SUM(CASE WHEN {participation_column} IS NULL THEN 1 ELSE 0 END) AS missing_participation_state\nFROM {table};", ["player", "participation", "data quality"]),
  template("Player usage summary", "Player & Participation", "Summarize observed usage by player without projecting future participation.", ["player_id", "usage_column"], "SELECT\n    {player_id} AS player,\n    COUNT(*) AS records,\n    AVG({usage_column}) AS average_observed_usage,\n    MIN({usage_column}) AS minimum_observed_usage,\n    MAX({usage_column}) AS maximum_observed_usage\nFROM {table}\nGROUP BY {player_id}\nORDER BY records DESC\nLIMIT 100;", ["player", "usage"]),
  template("Starter coverage", "Player & Participation", "Inspect observed starter designations and missingness.", ["starter_column"], "SELECT\n    {starter_column} AS starter_state,\n    COUNT(*) AS records,\n    COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS population_share\nFROM {table}\nGROUP BY {starter_column}\nORDER BY records DESC;", ["starter", "participation"]),
  template("Player-team history", "Player & Participation", "Count observed player-team combinations by season.", ["player_id", "team_id", "season_column"], "SELECT\n    {season_column} AS season,\n    {player_id} AS player,\n    {team_id} AS team,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {season_column}, {player_id}, {team_id}\nORDER BY {season_column}, records DESC\nLIMIT 100;", ["player", "team", "identity"]),
  template("Event taxonomy", "Event & Drive Analysis", "Inspect the observed event outcome vocabulary and frequency.", ["event_type"], "SELECT\n    {event_type} AS event_type,\n    COUNT(*) AS events,\n    COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS event_share\nFROM {table}\nGROUP BY {event_type}\nORDER BY events DESC\nLIMIT 100;", ["event", "taxonomy"]),
  template("Events per game", "Event & Drive Analysis", "Count distinct events and records for each game.", ["game_id", "event_id"], "SELECT\n    {game_id} AS game,\n    COUNT(DISTINCT {event_id}) AS events,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {game_id}\nORDER BY events DESC\nLIMIT 100;", ["event", "game"]),
  template("Plate-appearance outcome coverage", "Event & Drive Analysis", "Profile observed player event outcomes for plate-appearance research.", ["game_id", "player_id", "event_type"], "SELECT\n    {event_type} AS plate_appearance_outcome,\n    COUNT(DISTINCT {game_id}) AS games,\n    COUNT(DISTINCT {player_id}) AS players,\n    COUNT(*) AS plate_appearances\nFROM {table}\nGROUP BY {event_type}\nORDER BY plate_appearances DESC\nLIMIT 100;", ["mlb", "plate appearance", "event"]),
  template("Drive outcome distribution", "Event & Drive Analysis", "Profile observed drive outcomes without asserting a model or simulation result.", ["drive_outcome"], "SELECT\n    {drive_outcome} AS drive_outcome,\n    COUNT(*) AS drives,\n    COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS drive_share\nFROM {table}\nGROUP BY {drive_outcome}\nORDER BY drives DESC\nLIMIT 100;", ["nfl", "drive", "outcome"]),
  template("Drives per game", "Event & Drive Analysis", "Count distinct observed drives for each game.", ["game_id", "drive_id"], "SELECT\n    {game_id} AS game,\n    COUNT(DISTINCT {drive_id}) AS drives,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {game_id}\nORDER BY drives DESC\nLIMIT 100;", ["nfl", "drive", "game"]),
  template("State-transition coverage", "Event & Drive Analysis", "Count observed transitions between sport-specific game states.", ["state_column", "next_state_column"], "SELECT\n    {state_column} AS prior_state,\n    {next_state_column} AS next_state,\n    COUNT(*) AS transitions\nFROM {table}\nGROUP BY {state_column}, {next_state_column}\nORDER BY transitions DESC\nLIMIT 100;", ["event", "state", "transition"]),
  template("Forecast cutoff integrity", "Temporal Integrity", "Identify evidence recorded after its forecast cutoff.", ["source_timestamp", "forecast_timestamp"], "SELECT\n    COUNT(*) AS records,\n    SUM(CASE WHEN {source_timestamp} > {forecast_timestamp} THEN 1 ELSE 0 END) AS records_after_cutoff,\n    SUM(CASE WHEN {source_timestamp} IS NULL OR {forecast_timestamp} IS NULL THEN 1 ELSE 0 END) AS records_missing_timestamps\nFROM {table};", ["time integrity", "leakage", "forecast cutoff"]),
  template("Outcome availability integrity", "Temporal Integrity", "Identify outcomes timestamped at or before the forecast was issued.", ["forecast_timestamp", "outcome_timestamp"], "SELECT\n    COUNT(*) AS records,\n    SUM(CASE WHEN {outcome_timestamp} <= {forecast_timestamp} THEN 1 ELSE 0 END) AS outcomes_not_strictly_after_forecast,\n    SUM(CASE WHEN {outcome_timestamp} IS NULL THEN 1 ELSE 0 END) AS outcomes_not_yet_available\nFROM {table};", ["time integrity", "outcome", "leakage"]),
  template("Duplicate game identity", "Temporal Integrity", "Find repeated game identifiers in data expected at one row per game.", ["game_id"], "SELECT\n    {game_id} AS game,\n    COUNT(*) AS duplicate_count\nFROM {table}\nGROUP BY {game_id}\nHAVING COUNT(*) > 1\nORDER BY duplicate_count DESC\nLIMIT 100;", ["identity", "game", "data quality"]),
  template("Duplicate event identity", "Temporal Integrity", "Find repeated event identifiers within games.", ["game_id", "event_id"], "SELECT\n    {game_id} AS game,\n    {event_id} AS event,\n    COUNT(*) AS duplicate_count\nFROM {table}\nGROUP BY {game_id}, {event_id}\nHAVING COUNT(*) > 1\nORDER BY duplicate_count DESC\nLIMIT 100;", ["identity", "event", "data quality"]),
  template("Evidence timing by season", "Temporal Integrity", "Summarize observed source and forecast timestamps by season.", ["season_column", "source_timestamp", "forecast_timestamp"], "SELECT\n    {season_column} AS season,\n    MIN({source_timestamp}) AS earliest_source_time,\n    MAX({source_timestamp}) AS latest_source_time,\n    MIN({forecast_timestamp}) AS earliest_forecast_time,\n    MAX({forecast_timestamp}) AS latest_forecast_time,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {season_column}\nORDER BY {season_column};", ["season", "time integrity"]),
  template("Historical development population", "Model Development", "Summarize forecast targets across observed seasons for temporal development planning.", ["season_column", "target_column"], "SELECT\n    {season_column} AS season,\n    {target_column} AS forecast_target,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {season_column}, {target_column}\nORDER BY {season_column}, records DESC\nLIMIT 100;", ["modeling", "temporal validation"]),
  template("Temporal fold summary", "Model Development", "Count games and records in each declared temporal fold.", ["fold_column", "game_id"], "SELECT\n    {fold_column} AS temporal_fold,\n    COUNT(DISTINCT {game_id}) AS games,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {fold_column}\nORDER BY {fold_column};", ["modeling", "fold", "validation"]),
  template("Calibration table input", "Model Development", "Prepare observed outcome rates by forecast-probability band.", ["score_column", "target_column"], "SELECT\n    CASE\n        WHEN {score_column} < 0.2 THEN '0.0-0.2'\n        WHEN {score_column} < 0.4 THEN '0.2-0.4'\n        WHEN {score_column} < 0.6 THEN '0.4-0.6'\n        WHEN {score_column} < 0.8 THEN '0.6-0.8'\n        ELSE '0.8-1.0'\n    END AS probability_band,\n    COUNT(*) AS forecasts,\n    AVG({score_column}) AS average_forecast_probability,\n    AVG({target_column}) AS observed_outcome_rate\nFROM {table}\nWHERE {score_column} IS NOT NULL\nGROUP BY probability_band\nORDER BY probability_band;", ["modeling", "calibration", "probability"]),
  template("Forecast completeness", "Model Development", "Count missing forecast probabilities and target outcomes.", ["score_column", "target_column"], "SELECT\n    COUNT(*) AS records,\n    SUM(CASE WHEN {score_column} IS NULL THEN 1 ELSE 0 END) AS missing_forecasts,\n    SUM(CASE WHEN {target_column} IS NULL THEN 1 ELSE 0 END) AS missing_outcomes\nFROM {table};", ["modeling", "missingness"]),
  template("Subgroup forecast stability", "Model Development", "Summarize forecast probability by an observed team, player, venue, or lifecycle subgroup.", ["segment_column", "score_column"], "SELECT\n    {segment_column} AS subgroup,\n    COUNT(*) AS forecasts,\n    AVG({score_column}) AS average_forecast_probability,\n    MIN({score_column}) AS minimum_forecast_probability,\n    MAX({score_column}) AS maximum_forecast_probability\nFROM {table}\nGROUP BY {segment_column}\nORDER BY forecasts DESC\nLIMIT 100;", ["modeling", "stability", "subgroup"]),
  template("Strict versus enhanced evidence", "Model Development", "Compare declared evidence populations without mixing their validation results.", ["evidence_mode", "target_column"], "SELECT\n    {evidence_mode} AS evidence_population,\n    COUNT(*) AS records,\n    AVG({target_column}) AS observed_target_rate\nFROM {table}\nGROUP BY {evidence_mode}\nORDER BY records DESC;", ["modeling", "evidence", "population"]),
  template("Forecast volume over time", "Forward Monitoring", "Count recorded forecasts by issue time.", ["forecast_timestamp"], "SELECT\n    SUBSTR({forecast_timestamp}, 1, 10) AS forecast_date,\n    COUNT(*) AS forecasts\nFROM {table}\nGROUP BY forecast_date\nORDER BY forecast_date\nLIMIT 100;", ["monitoring", "forecast", "time"]),
  template("Outcome maturity over time", "Forward Monitoring", "Count outcomes available and still pending by forecast date.", ["forecast_timestamp", "outcome_timestamp"], "SELECT\n    SUBSTR({forecast_timestamp}, 1, 10) AS forecast_date,\n    COUNT(*) AS forecasts,\n    SUM(CASE WHEN {outcome_timestamp} IS NOT NULL THEN 1 ELSE 0 END) AS matured_outcomes,\n    SUM(CASE WHEN {outcome_timestamp} IS NULL THEN 1 ELSE 0 END) AS pending_outcomes\nFROM {table}\nGROUP BY forecast_date\nORDER BY forecast_date\nLIMIT 100;", ["monitoring", "outcome maturity"]),
  template("Forecast drift by season", "Forward Monitoring", "Track the observed forecast-probability distribution by season.", ["season_column", "score_column"], "SELECT\n    {season_column} AS season,\n    COUNT(*) AS forecasts,\n    AVG({score_column}) AS average_forecast_probability,\n    MIN({score_column}) AS minimum_forecast_probability,\n    MAX({score_column}) AS maximum_forecast_probability\nFROM {table}\nGROUP BY {season_column}\nORDER BY {season_column};", ["monitoring", "drift", "season"]),
  template("Operational and research challenger", "Forward Monitoring", "Compare observed operational and research-challenger predictions without implying promotion.", ["operational_score", "challenger_score"], "SELECT\n    COUNT(*) AS forecasts,\n    AVG({operational_score}) AS average_operational_prediction,\n    AVG({challenger_score}) AS average_research_challenger_prediction,\n    AVG(ABS({operational_score} - {challenger_score})) AS average_absolute_difference\nFROM {table};", ["monitoring", "operational model", "research challenger"]),
  template("OOD status distribution", "Forward Monitoring", "Count declared in-distribution and out-of-distribution states.", ["ood_column"], "SELECT\n    {ood_column} AS ood_status,\n    COUNT(*) AS records,\n    COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS population_share\nFROM {table}\nGROUP BY {ood_column}\nORDER BY records DESC;", ["monitoring", "ood"]),
  template("Required identity missingness", "Data Quality", "Count missing game, team, and player identifiers.", ["game_id", "team_id", "player_id"], "SELECT\n    COUNT(*) AS records,\n    SUM(CASE WHEN {game_id} IS NULL THEN 1 ELSE 0 END) AS missing_game_identity,\n    SUM(CASE WHEN {team_id} IS NULL THEN 1 ELSE 0 END) AS missing_team_identity,\n    SUM(CASE WHEN {player_id} IS NULL THEN 1 ELSE 0 END) AS missing_player_identity\nFROM {table};", ["data quality", "identity"]),
  template("Unexpected event categories", "Data Quality", "Review observed event categories and frequency before defining a taxonomy.", ["event_type"], "SELECT\n    {event_type} AS observed_event_category,\n    COUNT(*) AS records\nFROM {table}\nGROUP BY {event_type}\nORDER BY records DESC\nLIMIT 100;", ["data quality", "event taxonomy"]),
  template("Missing event time", "Data Quality", "Count event or game records without an observed timestamp.", ["date_column"], "SELECT\n    COUNT(*) AS records,\n    SUM(CASE WHEN {date_column} IS NULL THEN 1 ELSE 0 END) AS missing_observation_time\nFROM {table};", ["data quality", "time"]),
  template("Source-version control total", "Data Quality", "Produce a row-count control for the selected immutable dataset version.", [], "SELECT\n    COUNT(*) AS registered_version_row_count\nFROM {table};", ["data quality", "reconciliation"]),
];

const TEMPLATE_CATEGORIES: TemplateCategory[] = [
  "Sports Data Profiling",
  "Game & Team Analysis",
  "Player & Participation",
  "Event & Drive Analysis",
  "Temporal Integrity",
  "Model Development",
  "Forward Monitoring",
  "Data Quality",
];

const COLUMN_MAPPINGS = [
  { key: "sport_column", label: "Sport", candidates: ["sport", "sport_code", "sport_name"] },
  { key: "league_column", label: "League", candidates: ["league", "league_id", "competition"] },
  { key: "season_column", label: "Season", candidates: ["season", "season_id", "season_year", "year"] },
  { key: "game_id", label: "Game ID", candidates: ["game_id", "gameid", "match_id", "event_game_id"] },
  { key: "team_id", label: "Team ID", candidates: ["team_id", "teamid", "club_id", "franchise_id"] },
  { key: "home_team_id", label: "Home team ID", candidates: ["home_team_id", "home_team", "home_id"] },
  { key: "away_team_id", label: "Away team ID", candidates: ["away_team_id", "away_team", "visitor_team_id", "away_id"] },
  { key: "player_id", label: "Player ID", candidates: ["player_id", "playerid", "athlete_id", "batter_id", "pitcher_id"] },
  { key: "event_id", label: "Event / play ID", candidates: ["event_id", "play_id", "plate_appearance_id", "pa_id"] },
  { key: "drive_id", label: "Drive ID", candidates: ["drive_id", "possession_id", "series_id"] },
  { key: "date_column", label: "Game / event time", candidates: ["game_date", "event_time", "play_time", "start_time", "game_datetime", "date", "timestamp"] },
  { key: "event_type", label: "Event outcome", candidates: ["event_type", "event_outcome", "play_type", "pa_result", "result"] },
  { key: "drive_outcome", label: "Drive outcome", candidates: ["drive_outcome", "drive_result", "possession_result"] },
  { key: "participation_column", label: "Participation state", candidates: ["participation", "active_status", "appearance", "played", "snap_share"] },
  { key: "usage_column", label: "Usage", candidates: ["usage", "usage_rate", "snap_share", "minutes", "plate_appearances", "opportunities"] },
  { key: "starter_column", label: "Starter state", candidates: ["is_starter", "starter", "started", "starting_lineup"] },
  { key: "venue_column", label: "Venue", candidates: ["venue_id", "venue", "stadium_id", "park_id"] },
  { key: "home_score", label: "Home score", candidates: ["home_score", "home_runs", "home_points", "score_home"] },
  { key: "away_score", label: "Away score", candidates: ["away_score", "away_runs", "away_points", "score_away"] },
  { key: "target_column", label: "Forecast target", candidates: ["target", "actual", "outcome", "home_win", "win_flag", "margin", "total_runs", "total_points"] },
  { key: "score_column", label: "Forecast probability / score", candidates: ["forecast_probability", "win_probability", "home_win_probability", "prediction", "predicted_value", "probability", "score"] },
  { key: "forecast_timestamp", label: "Forecast timestamp", candidates: ["forecast_timestamp", "forecast_time", "prediction_time", "as_of_time", "cutoff_time"] },
  { key: "source_timestamp", label: "Source-available timestamp", candidates: ["source_timestamp", "available_at", "recorded_at", "published_at", "ingested_at"] },
  { key: "outcome_timestamp", label: "Outcome timestamp", candidates: ["outcome_timestamp", "outcome_time", "finalized_at", "result_time"] },
  { key: "fold_column", label: "Temporal fold", candidates: ["temporal_fold", "fold", "validation_fold", "split"] },
  { key: "segment_column", label: "Team / player / lifecycle subgroup", candidates: ["team_id", "player_id", "venue_id", "lifecycle", "season", "league"] },
  { key: "state_column", label: "Prior game state", candidates: ["state", "prior_state", "base_out_state", "field_position_state"] },
  { key: "next_state_column", label: "Next game state", candidates: ["next_state", "result_state", "next_base_out_state", "next_field_position_state"] },
  { key: "evidence_mode", label: "Evidence population", candidates: ["evidence_mode", "evidence_population", "strict_enhanced", "population_type"] },
  { key: "operational_score", label: "Operational prediction", candidates: ["operational_prediction", "operational_score", "production_prediction"] },
  { key: "challenger_score", label: "Research challenger prediction", candidates: ["challenger_prediction", "research_prediction", "challenger_score"] },
  { key: "ood_column", label: "OOD status", candidates: ["ood_status", "is_ood", "distribution_status"] },
];

export default function SqlDataStudio() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [sourceType, setSourceType] = useState<SourceType>("dataset_library_preview");
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [profiles, setProfiles] = useState<Record<string, DatasetProfile>>({});
  const [savedQueries, setSavedQueries] = useState<SavedSqlQuery[]>([]);
  const [queryName, setQueryName] = useState("Sports Dataset Preview");
  const [description, setDescription] = useState("");
  const [sql, setSql] = useState("SELECT *\nFROM SPORTS_DATASET\nLIMIT 100;");
  const [validation, setValidation] = useState<{ status: string; warnings: string[]; error?: string } | null>(null);
  const [preview, setPreview] = useState<SqlPreviewResult | null>(null);
  const [registeredDataset, setRegisteredDataset] = useState<DatasetSummary | null>(null);
  const [message, setMessage] = useState("");
  const [working, setWorking] = useState(false);
  const [expandedTables, setExpandedTables] = useState<Record<string, boolean>>({});
  const [objectExplorerTab, setObjectExplorerTab] = useState<ObjectExplorerTab>("tables");
  const [assistantTab, setAssistantTab] = useState<AssistantTab>("sports");
  const [bottomTab, setBottomTab] = useState<BottomTab>("results");
  const [expandedCategory, setExpandedCategory] = useState<TemplateCategory>("Sports Data Profiling");
  const [templateSearch, setTemplateSearch] = useState("");
  const [selectedTemplateName, setSelectedTemplateName] = useState("Dataset row count");
  const [columnMap, setColumnMap] = useState<Record<string, string>>({});
  const [queryHistory, setQueryHistory] = useState<QueryHistoryEntry[]>(() => readHistory());
  const [focusMode, setFocusMode] = useState(false);
  const [showRegisterPanel, setShowRegisterPanel] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement | null>(null);

  const selectedDatasets = useMemo(
    () => datasets.filter((dataset) => selectedIds.includes(dataset.datasetId) && dataset.latestVersion?.versionId),
    [datasets, selectedIds]
  );
  const datasetRefs: SqlDatasetRef[] = useMemo(
    () =>
      selectedDatasets.map((dataset) => ({
        datasetId: dataset.datasetId,
        versionId: dataset.latestVersion?.versionId || "",
        alias: safeSqlAlias(dataset),
      })),
    [selectedDatasets]
  );
  const selectedProfile = selectedDatasets[0] ? profiles[selectedDatasets[0].datasetId] : null;
  const selectedTemplate = SPORTS_TEMPLATES.find((item) => item.name === selectedTemplateName) ?? SPORTS_TEMPLATES[0];
  const availableColumns = useMemo(() => selectedDatasets.flatMap((dataset) => profiles[dataset.datasetId]?.schema?.map((column) => column.name) ?? []), [profiles, selectedDatasets]);
  const detectedMap = useMemo(() => autoDetectColumnMap(availableColumns), [availableColumns]);
  const activeColumnMap = { ...detectedMap, ...columnMap };
  const mappedTemplateSql = applyTemplate(selectedTemplate, datasetRefs, activeColumnMap);
  const templateIssues = selectedTemplate.requiredColumns.filter((field) => !activeColumnMap[field]);
  const filteredTemplates = SPORTS_TEMPLATES.filter((item) => {
    const needle = templateSearch.trim().toLowerCase();
    if (!needle) return true;
    return [item.name, item.category, item.description, item.tags.join(" ")].join(" ").toLowerCase().includes(needle);
  });
  const lineCount = Math.max(1, sql.split("\n").length);
  const cursorPosition = editorRef.current ? getCursorPosition(sql, editorRef.current.selectionStart) : { line: 1, column: 1 };
  const messages = buildMessages(validation, preview, datasetRefs, sourceType);
  const sqlResults = datasets.filter((dataset) => isSqlResultDataset(dataset));

  async function refresh() {
    setWorking(true);
    setMessage("");
    try {
      const payload = await listDatasets();
      const usable = payload.datasets.filter((dataset) => dataset.latestVersion?.versionId);
      setDatasets(usable);
      if (!selectedIds.length && usable[0]) {
        setSelectedIds([usable[0].datasetId]);
        const ref = { datasetId: usable[0].datasetId, versionId: usable[0].latestVersion?.versionId || "", alias: safeSqlAlias(usable[0]) };
        setSql(generateSelectTemplate([ref]));
      }
      setSavedQueries((await listSavedSqlQueries()).queries);
    } catch (error) {
      setMessage(sqlLabError(error, "ASP Model Studio could not load SQL Lab."));
    } finally {
      setWorking(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    selectedDatasets.forEach((dataset) => {
      const versionId = dataset.latestVersion?.versionId;
      if (!versionId || profiles[dataset.datasetId]) return;
      getDatasetProfile(dataset.datasetId, versionId)
        .then((payload) => setProfiles((current) => ({ ...current, [dataset.datasetId]: payload.profile })))
        .catch(() => undefined);
    });
  }, [profiles, selectedDatasets]);

  useEffect(() => {
    setColumnMap((current) => ({ ...detectedMap, ...current }));
  }, [detectedMap]);

  async function validateCurrentSql() {
    setWorking(true);
    setMessage("");
    try {
      const result = await validateSql({ sql, datasetRefs, limit: 100 });
      setValidation(result);
      setBottomTab("messages");
    } catch (error) {
      setValidation({ status: "error", warnings: [], error: sqlLabError(error, "Validation failed.") });
      setBottomTab("messages");
    } finally {
      setWorking(false);
    }
  }

  async function runPreview() {
    setWorking(true);
    setMessage("");
    setRegisteredDataset(null);
    const started = performance.now();
    try {
      const result = await runSqlPreview({ sql, datasetRefs, limit: 100 });
      setPreview(result);
      setValidation({ status: result.ok ? "valid" : result.status, warnings: result.warnings, error: result.error });
      recordHistory({
        id: `qh_${Date.now()}`,
        timestamp: new Date().toISOString(),
        sql,
        status: result.status,
        runtimeMs: result.runtimeMs ?? Math.round(performance.now() - started),
        rowCount: result.returnedRows ?? 0,
        tablesUsed: datasetRefs.map((ref) => ref.alias),
        warnings: result.warnings ?? [],
      });
      setBottomTab("results");
    } catch (error) {
      const errorMessage = sqlLabError(error, "Preview failed.");
      setPreview(null);
      setValidation({ status: "error", warnings: [], error: errorMessage });
      recordHistory({
        id: `qh_${Date.now()}`,
        timestamp: new Date().toISOString(),
        sql,
        status: "error",
        runtimeMs: Math.round(performance.now() - started),
        rowCount: 0,
        tablesUsed: datasetRefs.map((ref) => ref.alias),
        warnings: [errorMessage],
      });
      setBottomTab("messages");
    } finally {
      setWorking(false);
    }
  }

  async function saveCurrentQuery() {
    setWorking(true);
    try {
      const saved = await saveSqlQuery({
        name: queryName,
        description,
        sql,
        datasetRefs,
        linkedProjectId: projectId,
        tags: inferTags(sql, selectedTemplate),
      });
      setMessage(`Saved SQL query "${saved.query.name}".`);
      setSavedQueries((await listSavedSqlQueries()).queries);
    } catch (error) {
      setMessage(sqlLabError(error, "ASP Model Studio could not save this SQL query."));
    } finally {
      setWorking(false);
    }
  }

  async function deleteSavedQuery(query: SavedSqlQuery) {
    const confirmed = window.confirm(`Delete saved SQL query "${query.name}"?`);
    if (!confirmed) return;
    await deleteSqlQuery(query.queryId);
    setSavedQueries((await listSavedSqlQueries()).queries);
  }

  async function registerResult() {
    if (!preview?.rows?.length) {
      setMessage("Run Preview before registering a SQL result as a Dataset Library asset.");
      return;
    }
    setWorking(true);
    try {
      const payload = await registerSqlResult({
        queryName,
        description,
        sql,
        datasetRefs,
        resultRows: preview.rows,
        resultColumns: preview.columns,
        linkedProjectId: projectId,
        tags: inferTags(sql, selectedTemplate),
      });
      setRegisteredDataset(payload.dataset);
      setMessage(`Registered SQL Result dataset "${payload.dataset.name}".`);
      setBottomTab("lineage");
    } catch (error) {
      setMessage(sqlLabError(error, "ASP Model Studio could not register this SQL result."));
    } finally {
      setWorking(false);
    }
  }

  async function exportPreview() {
    if (!preview) {
      setMessage("Run Preview before exporting query results.");
      return;
    }
    try {
      const blob = await exportSqlResultExcel({
        queryName,
        sql,
        rows: preview.rows,
        columns: preview.columns,
        schemaProfile: preview.schemaProfile ?? [],
        datasetRefs,
        warnings: preview.warnings,
        lineage: { createdBy: "ASP Model Studio SQL Lab", sourceType, linkedProjectId: projectId },
      });
      downloadBlob(blob, "asp-model-studio-sql-lab-result.xlsx");
    } catch (error) {
      setMessage(sqlLabError(error, "ASP Model Studio could not export the SQL result."));
    }
  }

  async function saveQueryAsEvidence() {
    try {
      await createEvidence({
        projectId,
        projectName,
        evidenceType: "sql_query",
        title: `SQL Query: ${queryName}`,
        summary: description || `Governed SQL query using ${datasetRefs.length} source dataset(s).`,
        sourcePage: "SQL Lab",
        sourceRoute: "/sql-lab",
        artifactType: "sql_query",
        artifactId: queryName,
        datasetIds: datasetRefs.map((ref) => ref.datasetId),
        supportsSections: ["Lineage", "Appendix"],
        tags: ["governance", "sports_modeling", ...inferTags(sql, selectedTemplate)],
        status: validation?.status === "valid" ? "ready" : "needs_review",
        importance: "high",
        lineage: { datasetRefs, sourceType, validationStatus: validation?.status ?? "not_validated" },
        payload: { sqlPreview: sql.slice(0, 4000) },
        governance: { note: "SQL query text is captured for lineage review. Result rows are not duplicated in Model Graph evidence." },
      });
      setMessage("SQL query saved to Model Graph evidence.");
    } catch (error) {
      setMessage(sqlLabError(error, "ASP Model Studio could not save SQL query evidence."));
    }
  }

  async function saveSqlResultAsEvidence() {
    if (!preview) {
      setMessage("Run Preview before saving SQL result evidence.");
      return;
    }
    try {
      await createEvidence({
        projectId,
        projectName,
        evidenceType: "sql_result",
        title: `SQL Result: ${queryName}`,
        summary: `Preview returned ${preview.returnedRows} row(s), ${preview.columns.length} column(s), and ${preview.warnings?.length ?? 0} warning(s).`,
        sourcePage: "SQL Lab",
        sourceRoute: "/sql-lab",
        artifactType: "sql_result_preview",
        artifactId: registeredDataset?.datasetId || queryName,
        datasetIds: [...datasetRefs.map((ref) => ref.datasetId), registeredDataset?.datasetId].filter(Boolean) as string[],
        supportsSections: ["Lineage", "Data Quality"],
        tags: ["governance", "sports_modeling", ...inferTags(sql, selectedTemplate)],
        status: preview.ok ? "ready" : "needs_review",
        importance: "high",
        lineage: { datasetRefs, registeredDatasetId: registeredDataset?.datasetId, runtimeMs: preview.runtimeMs, returnedRows: preview.returnedRows },
        payload: { columns: preview.columns, warningCount: preview.warnings?.length ?? 0 },
        governance: { note: "SQL result evidence stores compact schema and lineage only; preview rows remain in SQL Lab output artifacts." },
      });
      setMessage("SQL result saved to Model Graph evidence.");
    } catch (error) {
      setMessage(sqlLabError(error, "ASP Model Studio could not save SQL result evidence."));
    }
  }

  function recordHistory(entry: QueryHistoryEntry) {
    setQueryHistory((current) => {
      const next = [entry, ...current].slice(0, 30);
      writeHistory(next);
      return next;
    });
  }

  function insertSnippet(snippet: string, mode: "replace" | "append" = "append") {
    const next = mode === "replace" ? snippet : `${sql.trim()}\n${snippet}`.trim();
    setSql(next);
    setPreview(null);
    setValidation(null);
    requestAnimationFrame(() => editorRef.current?.focus());
  }

  function insertTemplate(mode: "replace" | "append") {
    insertSnippet(mappedTemplateSql, mode);
    setQueryName(selectedTemplate.name);
    setDescription(selectedTemplate.description);
  }

  function openSavedQuery(query: SavedSqlQuery) {
    setQueryName(query.name);
    setDescription(query.description ?? "");
    setSql(query.sql);
    setSelectedIds((current) => {
      const ids = query.datasetRefs?.map((ref) => ref.datasetId).filter(Boolean) ?? [];
      return ids.length ? ids : current;
    });
    setBottomTab("messages");
  }

  function duplicateSavedQuery(query: SavedSqlQuery) {
    setQueryName(`${query.name} copy`);
    setDescription(query.description ?? "");
    setSql(query.sql);
  }

  async function renameSavedQuery(query: SavedSqlQuery) {
    const nextName = window.prompt("Rename saved SQL query", query.name)?.trim();
    if (!nextName || nextName === query.name) return;
    setWorking(true);
    try {
      await saveSqlQuery({
        name: nextName,
        description: query.description ?? "",
        sql: query.sql,
        datasetRefs: query.datasetRefs ?? [],
        linkedProjectId: query.linkedProjectId,
        tags: query.tags ?? [],
      });
      await deleteSqlQuery(query.queryId);
      setSavedQueries((await listSavedSqlQueries()).queries);
      setMessage(`Renamed SQL query "${query.name}" to "${nextName}".`);
    } catch (error) {
      setMessage(sqlLabError(error, "ASP Model Studio could not rename this SQL query."));
    } finally {
      setWorking(false);
    }
  }

  function handleEditorKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.ctrlKey && event.key === "Enter") {
      event.preventDefault();
      runPreview();
    }
    if (event.ctrlKey && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveCurrentQuery();
    }
    if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "f") {
      event.preventDefault();
      setSql(formatSql(sql));
    }
  }

  return (
    <div className="w-full atlas-theme-sql">
      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex min-h-[64px] flex-wrap items-center justify-between gap-3 border-b border-teal-300/30 bg-gradient-to-r from-slate-950 via-slate-900 to-teal-950 px-3 py-2 text-white">
          <div className="flex min-w-[260px] items-center gap-3">
            <BrandLogo size="sm" variant="dark" showSubtitle={false} />
            <div>
              <div className="flex items-center gap-2">
                <Database size={18} className="text-teal-200" />
                <h1 className="text-base font-semibold text-white">SQL Lab</h1>
                <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-teal-50">Sports research IDE</span>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-teal-50/80">
                <span>Source: {sourceType === "dataset_library_preview" ? "Dataset Preview SQL" : sourceType}</span>
                <span>Query: {validation?.status ?? "not validated"}</span>
                <span>Rows: {preview?.returnedRows?.toLocaleString?.() ?? "-"}</span>
                <span>Runtime: {preview ? `${preview.runtimeMs} ms` : "-"}</span>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <ToolbarButton icon={<ShieldAlert size={14} />} label="Validate" onClick={validateCurrentSql} />
            <ToolbarButton icon={<Play size={14} />} label="Run Preview" onClick={runPreview} primary />
            <ToolbarButton icon={<Wand2 size={14} />} label="Format" onClick={() => setSql(formatSql(sql))} />
            <ToolbarButton icon={<Save size={14} />} label="Save Query" onClick={saveCurrentQuery} />
            <ToolbarButton icon={<Database size={14} />} label="Register Result" onClick={() => setShowRegisterPanel(true)} />
            <ToolbarButton icon={<Download size={14} />} label="Export" onClick={exportPreview} />
            <ToolbarButton icon={<Copy size={14} />} label="Copy SQL" onClick={() => navigator.clipboard?.writeText(sql)} />
            <Link to={`/research-tools?datasetId=${selectedDatasets[0]?.datasetId || ""}&versionId=${selectedDatasets[0]?.latestVersion?.versionId || ""}`} className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:border-blue-300 hover:text-blue-800">
              Open Research Tools
            </Link>
            <ToolbarButton icon={<ShieldAlert size={14} />} label="Save Query Evidence" onClick={saveQueryAsEvidence} />
            <ToolbarButton icon={<ShieldAlert size={14} />} label="Save Result Evidence" onClick={saveSqlResultAsEvidence} />
            <Link to="/model-graph" className="rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-xs font-semibold text-blue-800 hover:bg-blue-100">
              Open Model Graph
            </Link>
            <button type="button" onClick={() => setFocusMode((current) => !current)} className={`rounded-lg border px-2.5 py-1.5 text-xs font-semibold ${focusMode ? "border-blue-300 bg-blue-50 text-blue-800" : "border-slate-300 bg-white text-slate-700"}`}>
              Focus Mode
            </button>
          </div>
        </div>
        {message && <div className="border-b border-teal-200 bg-teal-50 px-3 py-2 text-sm text-teal-950">{message}</div>}

        <div
          className="grid min-h-[560px] gap-3 bg-teal-50/50 p-3"
          style={{
            height: "calc(100vh - 170px)",
            gridTemplateColumns: focusMode ? "minmax(700px, 1fr)" : "260px minmax(520px, 1fr) 320px",
            gridTemplateRows: focusMode ? "minmax(0, 1fr) 280px" : "minmax(0, 1fr) 260px",
          }}
        >
          {!focusMode && (
            <aside className="col-start-1 row-start-1 row-span-2 grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden rounded-xl border border-slate-200 bg-slate-50 shadow-sm">
              <PaneHeader icon={<FolderTree size={15} />} title="Object Explorer" subtitle="Tables, Saved Queries, SQL Results, Connectors" />
              <div className="flex border-b border-slate-200 bg-white">
                {[
                  ["tables", "Tables"],
                  ["saved", "Saved"],
                  ["results", "Results"],
                  ["connectors", "Connectors"],
                ].map(([id, label]) => (
                  <button key={id} type="button" onClick={() => setObjectExplorerTab(id as ObjectExplorerTab)} className={`flex-1 px-2 py-2 text-[11px] font-semibold ${objectExplorerTab === id ? "bg-blue-50 text-blue-800" : "text-slate-600 hover:bg-slate-50"}`}>
                    {label}
                  </button>
                ))}
              </div>
              <div className="min-h-0 overflow-auto p-2">
                {objectExplorerTab === "tables" && (
                  <div className="space-y-2">
                    <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                      Data Source
                    </label>
                    <select value={sourceType} onChange={(event) => setSourceType(event.target.value as SourceType)} className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs">
                      <option value="dataset_library_preview">Dataset Library Preview SQL</option>
                      <option value="saved_query">Saved SQL Query</option>
                      <option value="external_metadata">External Source Metadata</option>
                    </select>
                    {datasets.map((dataset) => {
                      const checked = selectedIds.includes(dataset.datasetId);
                      const alias = safeSqlAlias(dataset);
                      const expanded = expandedTables[dataset.datasetId];
                      const schema = profiles[dataset.datasetId]?.schema ?? [];
                      return (
                        <div key={dataset.datasetId} className={`rounded-lg border text-xs ${checked ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white"}`}>
                          <div className="flex items-center gap-2 px-2 py-1.5">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(event) =>
                                setSelectedIds((current) => event.target.checked ? [...current, dataset.datasetId] : current.filter((id) => id !== dataset.datasetId))
                              }
                            />
                            <button type="button" onClick={() => setExpandedTables((current) => ({ ...current, [dataset.datasetId]: !expanded }))} className="text-slate-500">
                              {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                            </button>
                            <div className="min-w-0">
                              <div className="truncate font-semibold text-slate-950">{alias}</div>
                              <div className="truncate text-[11px] text-slate-500">{dataset.latestVersion?.rowCount?.toLocaleString() ?? "-"} rows | {dataset.latestVersion?.columnCount ?? "-"} cols</div>
                            </div>
                          </div>
                          {expanded && (
                            <div className="max-h-44 overflow-auto border-t border-slate-200 bg-white px-2 py-1">
                              {schema.slice(0, 60).map((column) => (
                                <button key={column.name} type="button" onClick={() => insertSnippet(column.name)} className="flex w-full items-center justify-between rounded px-1.5 py-1 text-left hover:bg-slate-50">
                                  <span className="truncate font-mono text-[11px] text-slate-800">{column.name}</span>
                                  <span className="rounded bg-slate-100 px-1 text-[10px] text-slate-500">{column.dtype}</span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
                {objectExplorerTab === "saved" && (
                  <div className="space-y-2">
                    {savedQueries.slice(0, 16).map((query) => (
                      <div key={query.queryId} className="rounded-lg border border-slate-200 bg-white p-2 text-xs">
                        <div className="font-semibold text-slate-950">{query.name}</div>
                        <div className="mt-1 truncate text-[11px] text-slate-500">Updated {query.updatedAt ? new Date(query.updatedAt).toLocaleString() : "-"}</div>
                        <div className="mt-1 truncate text-[11px] text-slate-500">Status: Saved | Tags: {(query.tags ?? []).join(", ") || "-"}</div>
                        <div className="mt-2 flex flex-wrap gap-1">
                          <SmallButton label="Open" onClick={() => openSavedQuery(query)} />
                          <SmallButton label="Run" onClick={() => { openSavedQuery(query); setTimeout(runPreview, 0); }} />
                          <SmallButton label="Duplicate" onClick={() => duplicateSavedQuery(query)} />
                          <SmallButton label="Rename" onClick={() => renameSavedQuery(query)} />
                          <SmallButton label="Delete" onClick={() => deleteSavedQuery(query)} />
                          <SmallButton label="Export SQL" onClick={() => exportSqlDefinition(query.name, query.sql, query.datasetRefs ?? [])} />
                        </div>
                      </div>
                    ))}
                    {!savedQueries.length && <p className="text-xs leading-5 text-slate-500">Saved governed queries will appear here.</p>}
                  </div>
                )}
                {objectExplorerTab === "results" && (
                  <div className="space-y-2">
                    {sqlResults.slice(0, 12).map((dataset) => (
                      <Link key={dataset.datasetId} to={`/datasets/${dataset.datasetId}`} className="block rounded-lg border border-indigo-200 bg-indigo-50 px-2 py-2 text-xs font-semibold text-indigo-900">
                        {dataset.name}
                      </Link>
                    ))}
                    {!sqlResults.length && <p className="text-xs leading-5 text-slate-500">Registered SQL result datasets will appear here.</p>}
                  </div>
                )}
                {objectExplorerTab === "connectors" && (
                  <details className="rounded-lg border border-slate-200 bg-white p-2 text-xs" open>
                    <summary className="cursor-pointer font-semibold text-slate-800">External Connectors</summary>
                    <p className="mt-2 leading-5 text-slate-500">No external sports warehouse is connected. Use registered target-local dataset versions until immutable manifest connections are enabled.</p>
                    <div className="mt-2 space-y-1">
                      {EXTERNAL_CONNECTORS.map((connector) => (
                        <div key={connector} className="flex justify-between rounded bg-slate-50 px-2 py-1 text-slate-600">
                          <span>{connector}</span>
                          <span>Not configured</span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            </aside>
          )}

          <main className={`${focusMode ? "col-start-1" : "col-start-2"} row-start-1 grid min-h-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm grid-rows-[auto_minmax(0,1fr)]`}>
            <div className="border-b border-slate-200 bg-slate-50 px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="inline-flex rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-900">Query 1 - Active</div>
                <div className="text-[11px] text-slate-500">Ctrl+Enter run preview / Ctrl+S save query / Ctrl+Shift+F format SQL</div>
              </div>
              <div className="mt-2 grid gap-2 md:grid-cols-[minmax(0,0.7fr)_minmax(0,1fr)]">
                <input value={queryName} onChange={(event) => setQueryName(event.target.value)} className="rounded-md border border-slate-300 px-2 py-1.5 text-sm" placeholder="Query title" />
                <input value={description} onChange={(event) => setDescription(event.target.value)} className="rounded-md border border-slate-300 px-2 py-1.5 text-sm" placeholder="Description / governance purpose" />
              </div>
            </div>
            <div className="grid min-h-0 grid-cols-[46px_minmax(0,1fr)] bg-slate-950">
              <pre className="select-none overflow-hidden border-r border-slate-800 bg-slate-900 px-2 py-3 text-right font-mono text-xs leading-6 text-slate-500">
                {Array.from({ length: lineCount }, (_, index) => index + 1).join("\n")}
              </pre>
              <textarea
                ref={editorRef}
                value={sql}
                onChange={(event) => {
                  setSql(event.target.value);
                  setPreview(null);
                  setValidation(null);
                }}
                onKeyDown={handleEditorKeyDown}
                spellCheck={false}
                className="h-full min-h-0 w-full resize-none bg-slate-950 px-4 py-3 font-mono text-sm leading-6 text-slate-100 outline-none"
              />
            </div>
          </main>

          {!focusMode && (
            <aside className="col-start-3 row-start-1 grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden rounded-xl border border-slate-200 bg-slate-50 shadow-sm">
              <PaneHeader icon={<Sparkles size={15} />} title="Sports SQL Assistant" subtitle="Profiling, game, player, event, drive, time-integrity, and governance patterns" />
              <div className="flex border-b border-slate-200 bg-white">
                {[
                  ["templates", "Templates"],
                  ["sports", "Sports"],
                  ["mapping", "Mapping"],
                  ["governance", "Governance"],
                  ["help", "Help"],
                ].map(([id, label]) => (
                  <button key={id} type="button" onClick={() => setAssistantTab(id as AssistantTab)} className={`flex-1 px-2 py-2 text-[11px] font-semibold ${assistantTab === id ? "bg-blue-50 text-blue-800" : "text-slate-600 hover:bg-slate-50"}`}>
                    {label}
                  </button>
                ))}
              </div>
              <div className="min-h-0 overflow-auto p-2">
                {assistantTab === "templates" && (
                  <Panel title="SQL Templates">
                    <div className="space-y-1">
                      {SQL_SNIPPETS.map((snippet) => (
                        <button key={snippet.label} type="button" onClick={() => insertSnippet(resolveSnippet(snippet.sql, datasetRefs, activeColumnMap))} className="flex w-full items-center justify-between rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-left text-xs font-semibold text-slate-700 hover:border-blue-200 hover:bg-blue-50">
                          {snippet.label}
                          <ChevronRight size={13} />
                        </button>
                      ))}
                    </div>
                  </Panel>
                )}
                {assistantTab === "sports" && (
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1.5">
                      <Search size={13} className="text-slate-500" />
                      <input value={templateSearch} onChange={(event) => setTemplateSearch(event.target.value)} placeholder="Search sports SQL patterns..." className="w-full bg-transparent text-xs outline-none" />
                    </label>
                    <Panel title="Selected Template Preview">
                      <div className="space-y-2 text-xs">
                        <div className="font-semibold text-slate-950">{selectedTemplate.name}</div>
                        <div className="text-[11px] text-slate-500">Required columns: {selectedTemplate.requiredColumns.join(", ") || "none"}</div>
                        {templateIssues.length > 0 && <div className="rounded border border-amber-200 bg-amber-50 p-2 text-amber-900">Needs mapping: {templateIssues.join(", ")}</div>}
                        <pre className="max-h-28 overflow-auto rounded-lg bg-slate-950 p-2 text-[11px] leading-5 text-slate-100">{mappedTemplateSql}</pre>
                        <div className="grid grid-cols-2 gap-1">
                          <button type="button" onClick={() => insertTemplate("replace")} className="rounded bg-slate-950 px-2 py-1.5 text-xs font-semibold text-white">Replace editor SQL</button>
                          <button type="button" onClick={() => insertTemplate("append")} className="rounded border border-slate-300 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700">Append to editor SQL</button>
                        </div>
                      </div>
                    </Panel>
                    <Panel title="Sports Research SQL Patterns">
                      <div className="space-y-1">
                        {TEMPLATE_CATEGORIES.map((category) => {
                          const items = filteredTemplates.filter((item) => item.category === category);
                          if (!items.length) return null;
                          const open = expandedCategory === category;
                          return (
                            <div key={category} className="rounded-lg border border-slate-200 bg-white">
                              <button type="button" onClick={() => setExpandedCategory(open ? "Sports Data Profiling" : category)} className="flex w-full items-center justify-between px-2 py-1.5 text-left text-xs font-semibold text-slate-800">
                                {category}
                                {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                              </button>
                              {open && (
                                <div className="border-t border-slate-100 p-1">
                                  {items.map((item) => (
                                    <div key={item.name} className={`rounded-md border p-2 text-xs ${item.name === selectedTemplateName ? "border-blue-300 bg-blue-50" : "border-transparent bg-white"}`}>
                                      <button type="button" onClick={() => setSelectedTemplateName(item.name)} className="w-full text-left">
                                        <div className="font-semibold text-slate-950">{item.name}</div>
                                        <div className="mt-1 line-clamp-2 text-[11px] text-slate-500">{item.description}</div>
                                        <div className="mt-1 text-[10px] text-slate-500">Required: {item.requiredColumns.join(", ") || "none"}</div>
                                      </button>
                                      <div className="mt-2 flex gap-1">
                                        <SmallButton label="Insert" onClick={() => insertTemplate("replace")} />
                                        <SmallButton label="Preview" onClick={() => setSelectedTemplateName(item.name)} />
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </Panel>
                  </div>
                )}
                {assistantTab === "mapping" && (
                  <Panel title="Column Mapping">
                    {selectedTemplate ? (
                      <div className="space-y-2">
                        {COLUMN_MAPPINGS.map((mapping) => (
                          <label key={mapping.key} className="block text-xs font-semibold text-slate-600">
                            {mapping.label}
                            <select value={activeColumnMap[mapping.key] ?? ""} onChange={(event) => setColumnMap((current) => ({ ...current, [mapping.key]: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-900">
                              <option value="">Not mapped</option>
                              {availableColumns.map((column) => <option key={`${mapping.key}-${column}`} value={column}>{column}</option>)}
                            </select>
                          </label>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">Select a template to map required columns.</p>
                    )}
                  </Panel>
                )}
                {assistantTab === "governance" && (
                  <div className="space-y-2">
                    <Panel title="Governance Controls">
                      <ul className="space-y-1 text-xs leading-5 text-slate-700">
                        <li>Read-only SELECT only.</li>
                        <li>Preview/sample-row execution only.</li>
                        <li>No external sports warehouse execution.</li>
                        <li>Immutable dataset lineage is required before registration.</li>
                        <li>Review source rights, identity coverage, and point-in-time integrity.</li>
                      </ul>
                    </Panel>
                    <Panel title="Current query lineage">
                      <LineagePanel refs={datasetRefs} registeredDataset={registeredDataset} sql={sql} compact />
                    </Panel>
                  </div>
                )}
                {assistantTab === "help" && (
                  <Panel title="How to use SQL Lab">
                    <ol className="list-decimal space-y-1 pl-5 text-xs leading-5 text-slate-700">
                      <li>Select Dataset Library tables.</li>
                      <li>Insert a template or write SQL.</li>
                      <li>Validate and run preview.</li>
                      <li>Review Messages and Lineage.</li>
                      <li>Register approved SQL results.</li>
                    </ol>
                  </Panel>
                )}
                {showRegisterPanel && (
                  <Panel title="Register Result Form">
                    <div className="space-y-2 text-xs">
                      <Meta label="Dataset name" value={queryName} />
                      <Meta label="Dataset role" value="SQL Result" />
                      <Meta label="Preview row count" value={preview?.returnedRows?.toLocaleString() ?? "-"} />
                      <Meta label="Source datasets" value={datasetRefs.map((ref) => ref.alias).join(", ") || "-"} />
                      <Meta label="Linked project" value={projectId} />
                      <div className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-amber-900">Lineage warning: register only validated queries with approved source datasets.</div>
                      <button type="button" onClick={registerResult} className="w-full rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white">Register SQL Result</button>
                      {registeredDataset && (
                        <div className="grid gap-1">
                          <Link className="rounded bg-slate-950 px-2 py-1.5 text-center text-xs font-semibold text-white" to={`/datasets/${registeredDataset.datasetId}`}>Open Dataset Detail</Link>
                          <Link className="rounded bg-slate-950 px-2 py-1.5 text-center text-xs font-semibold text-white" to={`/analytics?datasetId=${registeredDataset.datasetId}`}>Open Analytics Workbench</Link>
                          <Link className="rounded bg-slate-950 px-2 py-1.5 text-center text-xs font-semibold text-white" to={`/visualization-studio?datasetId=${registeredDataset.datasetId}`}>Open Visualization Studio</Link>
                          <Link className="rounded bg-slate-950 px-2 py-1.5 text-center text-xs font-semibold text-white" to="/model-documentation">Open Model Documentation</Link>
                        </div>
                      )}
                    </div>
                  </Panel>
                )}
              </div>
            </aside>
          )}

          <section className={`${focusMode ? "col-start-1" : "col-start-2 col-span-2"} row-start-2 min-h-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm`}>
            <div className="flex flex-wrap border-b border-slate-200 bg-slate-50">
              {[
                ["results", "Results"],
                ["schema", "Schema"],
                ["profile", "Profile"],
                ["messages", "Messages"],
                ["history", "Query History"],
                ["lineage", "Lineage"],
              ].map(([id, label]) => (
                <button key={id} type="button" onClick={() => setBottomTab(id as BottomTab)} className={`border-r border-slate-200 px-3 py-2 text-xs font-semibold ${bottomTab === id ? "bg-white text-blue-700" : "text-slate-600 hover:bg-white"}`}>
                  {label}
                </button>
              ))}
              <div className="ml-auto px-3 py-2 text-xs text-slate-500">Status: {working ? "Working..." : validation?.status ?? "Idle"} | Cursor: {cursorPosition.line}:{cursorPosition.column}</div>
            </div>
            <div className="h-[calc(100%-37px)] overflow-auto p-3">
              {bottomTab === "results" && <ResultsGrid preview={preview} />}
              {bottomTab === "schema" && <SchemaGrid columns={preview?.columns ?? []} />}
              {bottomTab === "profile" && <SchemaProfile profile={preview?.schemaProfile ?? []} />}
              {bottomTab === "messages" && <MessagesPanel messages={messages} />}
              {bottomTab === "history" && <QueryHistoryPanel entries={queryHistory} onOpen={(entry) => setSql(entry.sql)} onRerun={(entry) => { setSql(entry.sql); setTimeout(runPreview, 0); }} onSave={(entry) => { setSql(entry.sql); setQueryName(`Saved from history ${new Date(entry.timestamp).toLocaleString()}`); }} />}
              {bottomTab === "lineage" && <LineagePanel refs={datasetRefs} registeredDataset={registeredDataset} sql={sql} />}
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}

function template(name: string, category: TemplateCategory, description: string, requiredColumns: string[], sql: string, tags: string[]): SqlTemplate {
  return { name, category, description, requiredColumns, sql, tags };
}

function ToolbarButton({ icon, label, onClick, primary = false }: { icon: React.ReactNode; label: string; onClick: () => void; primary?: boolean }) {
  return (
    <button type="button" onClick={onClick} className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold shadow-sm ${primary ? "bg-blue-700 text-white hover:bg-blue-800" : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}>
      {icon}
      {label}
    </button>
  );
}

function PaneHeader({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle: string }) {
  return (
    <div className="border-b border-slate-200 bg-white px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">{icon}{title}</div>
      <div className="mt-1 text-xs text-slate-500">{subtitle}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      {children}
    </section>
  );
}

function StatusPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-xs font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return <span className="inline-flex rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-700">{children}</span>;
}

function Meta({ label, value }: { label: string; value?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 break-words text-xs font-medium text-slate-800">{value || "-"}</div>
    </div>
  );
}

function ResultsGrid({ preview }: { preview: SqlPreviewResult | null }) {
  if (!preview) return <EmptyState icon={<Table2 size={24} />} title="No query results yet" text="Run Preview to populate the IDE result grid." />;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 text-xs">
        <Chip>{preview.returnedRows.toLocaleString()} rows returned</Chip>
        <Chip>{preview.columns.length.toLocaleString()} columns</Chip>
        <Chip>{preview.runtimeMs} ms</Chip>
      </div>
      <div className="overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-left text-xs">
          <thead className="sticky top-0 z-10 bg-slate-100 text-slate-600">
            <tr>
              {preview.columns.map((column) => (
                <th key={column.name} className="whitespace-nowrap px-3 py-2 font-semibold">
                  {column.name}
                  <span className="ml-2 rounded-full bg-white px-1.5 py-0.5 text-[10px] text-slate-500">{column.type}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {preview.rows.map((row, index) => (
              <tr key={index} className="odd:bg-white even:bg-slate-50">
                {preview.columns.map((column) => (
                  <td key={`${index}-${column.name}`} className="max-w-[260px] whitespace-nowrap px-3 py-2 text-slate-700">
                    {row[column.name] == null ? <span className="italic text-slate-400">NULL</span> : String(row[column.name])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SchemaGrid({ columns }: { columns: Array<{ name: string; type: string }> }) {
  if (!columns.length) return <EmptyState icon={<Code2 size={24} />} title="No result schema" text="Run Preview to infer result columns and types." />;
  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
      {columns.map((column) => (
        <div key={column.name} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="font-mono text-xs font-semibold text-slate-950">{column.name}</div>
          <div className="mt-1 text-[11px] uppercase text-slate-500">{column.type}</div>
        </div>
      ))}
    </div>
  );
}

function SchemaProfile({ profile }: { profile: Array<{ name: string; type: string; missingCount: number; distinctCount: number; min?: number; max?: number; mean?: number; sampleValues?: string[] }> }) {
  if (!profile.length) return <EmptyState icon={<BarChart3 size={24} />} title="No profile yet" text="Run Preview to calculate compact schema profile statistics." />;
  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
      {profile.map((column) => (
        <div key={column.name} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
          <div className="font-semibold text-slate-950">{column.name}</div>
          <div className="mt-1 text-slate-600">{column.type} / missing {column.missingCount} / distinct {column.distinctCount}</div>
          {column.type === "numeric" ? <div className="mt-1 text-slate-500">min {fmt(column.min)} / max {fmt(column.max)} / mean {fmt(column.mean)}</div> : <div className="mt-1 truncate text-slate-500">{column.sampleValues?.join(", ")}</div>}
        </div>
      ))}
    </div>
  );
}

function MessagesPanel({ messages }: { messages: string[] }) {
  return (
    <div className="space-y-2">
      {messages.map((item) => (
        <div key={item} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">{item}</div>
      ))}
    </div>
  );
}

function QueryHistoryPanel({ entries, onOpen, onRerun, onSave }: { entries: QueryHistoryEntry[]; onOpen: (entry: QueryHistoryEntry) => void; onRerun: (entry: QueryHistoryEntry) => void; onSave: (entry: QueryHistoryEntry) => void }) {
  if (!entries.length) return <EmptyState icon={<History size={24} />} title="No query history" text="Each preview run records compact history: status, runtime, row count, tables, and warnings." />;
  return (
    <div className="space-y-2">
      {entries.map((entry) => (
        <div key={entry.id} className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold text-slate-950">{new Date(entry.timestamp).toLocaleString()}</div>
              <div className="mt-1 text-xs text-slate-500">{entry.status} / {entry.runtimeMs} ms / {entry.rowCount} rows / {entry.tablesUsed.join(", ") || "no tables"}</div>
            </div>
            <div className="flex flex-wrap gap-1">
              <SmallButton label="Open SQL" onClick={() => onOpen(entry)} />
              <SmallButton label="Rerun" onClick={() => onRerun(entry)} />
              <SmallButton label="Save as Query" onClick={() => onSave(entry)} />
            </div>
          </div>
          <pre className="mt-2 max-h-24 overflow-auto rounded bg-slate-950 p-2 text-[11px] text-slate-100">{entry.sql}</pre>
        </div>
      ))}
    </div>
  );
}

function LineagePanel({ refs, registeredDataset, sql, compact = false }: { refs: SqlDatasetRef[]; registeredDataset: DatasetSummary | null; sql: string; compact?: boolean }) {
  return (
    <div className="space-y-3">
      <div className={`grid gap-2 ${compact ? "" : "md:grid-cols-3"}`}>
        <Meta label="Source datasets" value={refs.map((ref) => ref.alias).join(", ") || "-"} />
        <Meta label="Versions" value={refs.map((ref) => ref.versionId).join(", ") || "-"} />
        <Meta label="Registered result" value={registeredDataset?.name ?? "Not registered"} />
      </div>
      {!compact && <pre className="max-h-48 overflow-auto rounded-lg bg-slate-950 p-3 text-xs leading-5 text-slate-100">{sql}</pre>}
    </div>
  );
}

function EmptyState({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center">
      <div className="text-blue-700">{icon}</div>
      <div className="mt-2 text-sm font-semibold text-slate-950">{title}</div>
      <p className="mt-1 max-w-md text-xs leading-5 text-slate-500">{text}</p>
    </div>
  );
}

function SmallButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50">{label}</button>;
}

function sqlLabError(error: unknown, fallback: string) {
  const message = error instanceof Error ? error.message : fallback;
  return message
    .replace(/\bATLAS\b/g, "ASP Model Studio")
    .replace(/SQL Data Studio/g, "SQL Lab");
}

function fmt(value: unknown) {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(4) : "-";
}

function generateSelectTemplate(refs: SqlDatasetRef[]) {
  return `SELECT *\nFROM ${firstAlias(refs)}\nLIMIT 100;`;
}

function firstAlias(refs: SqlDatasetRef[]) {
  return refs[0]?.alias || "SPORTS_DATASET";
}

function applyTemplate(item: SqlTemplate, refs: SqlDatasetRef[], mapping: Record<string, string>) {
  let next = item.sql.replaceAll("{table}", firstAlias(refs));
  Object.entries(mapping).forEach(([key, value]) => {
    if (!value) return;
    next = next.replaceAll(`{${key}}`, value);
    next = next.replace(new RegExp(`\\b${key}\\b`, "g"), value);
  });
  return next;
}

function resolveSnippet(value: string, refs: SqlDatasetRef[], mapping: Record<string, string>) {
  let next = value.replaceAll("{table}", firstAlias(refs)).replaceAll("{table2}", refs[1]?.alias ?? "SECOND_TABLE");
  Object.entries(mapping).forEach(([key, mapped]) => {
    if (mapped) next = next.replaceAll(`{${key}}`, mapped).replaceAll(key, mapped);
  });
  return next.replaceAll("{column}", mapping.segment_column ?? mapping.event_type ?? "column_name").replaceAll("{key}", mapping.game_id ?? mapping.player_id ?? "id");
}

function autoDetectColumnMap(columns: string[]) {
  const lower = new Map(columns.map((column) => [column.toLowerCase(), column]));
  const result: Record<string, string> = {};
  COLUMN_MAPPINGS.forEach((mapping) => {
    const found = mapping.candidates.find((candidate) => lower.has(candidate.toLowerCase()));
    if (found) result[mapping.key] = lower.get(found.toLowerCase()) ?? found;
  });
  return result;
}

function formatSql(value: string) {
  const keywords = ["select", "from", "where", "left join", "right join", "inner join", "join", "on", "group by", "order by", "having", "limit", "union all", "union"];
  let next = value.trim().replace(/\s+/g, " ");
  keywords.forEach((keyword) => {
    const upper = keyword.toUpperCase();
    next = next.replace(new RegExp(`\\b${keyword}\\b`, "gi"), `\n${upper}`);
  });
  next = next.replace(/^\n/, "").replace(/^SELECT\s+/i, "SELECT\n    ");
  next = next.replace(/,\s*/g, ",\n    ");
  next = next.replace(/\n\s*(FROM|WHERE|LEFT JOIN|RIGHT JOIN|INNER JOIN|JOIN|ON|GROUP BY|ORDER BY|HAVING|LIMIT|UNION ALL|UNION)\b/g, "\n$1");
  return next.replace(/\n{2,}/g, "\n").trim();
}

function buildMessages(validation: { status: string; warnings: string[]; error?: string } | null, preview: SqlPreviewResult | null, refs: SqlDatasetRef[], sourceType: SourceType) {
  const messages = [
    `Source mode: ${sourceType}.`,
    `Tables selected: ${refs.map((ref) => ref.alias).join(", ") || "none"}.`,
  ];
  if (validation?.status) messages.push(`Validation status: ${validation.status}.`);
  if (validation?.error) messages.push(`Error: ${validation.error}`);
  validation?.warnings?.forEach((warning) => messages.push(`Warning: ${warning}`));
  if (preview) {
    messages.push(`Preview returned ${preview.returnedRows} rows and ${preview.columns.length} columns in ${preview.runtimeMs} ms.`);
    preview.warnings?.forEach((warning) => messages.push(`Preview warning: ${warning}`));
  }
  if (!preview) messages.push("Run Preview to populate runtime, row count, schema, and result-grid messages.");
  return messages;
}

function inferTags(sql: string, templateItem: SqlTemplate) {
  const tags = new Set(["sql-lab", "sports", ...templateItem.tags]);
  const text = sql.toLowerCase();
  ["game", "team", "player", "participation", "event", "drive", "time integrity", "monitoring", "data quality", "modeling"].forEach((tag) => {
    if (text.includes(tag.replace(" ", "_")) || text.includes(tag)) tags.add(tag);
  });
  return Array.from(tags);
}

function getCursorPosition(value: string, index: number) {
  const prefix = value.slice(0, index);
  const lines = prefix.split("\n");
  return { line: lines.length, column: lines[lines.length - 1].length + 1 };
}

function readHistory(): QueryHistoryEntry[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const parsed = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.slice(0, 30) : [];
  } catch {
    return [];
  }
}

function writeHistory(entries: QueryHistoryEntry[]) {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, 30)));
  } catch {
    // Query history is convenience state only; do not block SQL workbench actions.
  }
}

function exportSqlDefinition(queryName: string, sql: string, refs: SqlDatasetRef[]) {
  const payload = { queryName, sql, sourceDatasets: refs, exportedAt: new Date().toISOString() };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  downloadBlob(blob, "asp-model-studio-sql-definition-lineage.json");
}

function isSqlResultDataset(dataset: DatasetSummary) {
  return (
    dataset.datasetRole === "sql_result" ||
    dataset.sourceType === "sql_studio" ||
    dataset.sourceInfo?.sourceType === "sql_studio" ||
    dataset.sourceInfo?.datasetRole === "sql_result"
  );
}
