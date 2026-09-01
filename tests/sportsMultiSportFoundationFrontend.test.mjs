import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const source = (path) => readFile(new URL(path, ROOT), "utf8");

test("SPORT_REGISTRY_V1 freezes canonical sport and league vocabulary", async () => {
  const text = await source("src/sports/shared/sportRegistry.ts");
  for (const value of ["SPORT_REGISTRY_V1", "BASEBALL", "FOOTBALL", "BASKETBALL", "MMA", "MLB", "NFL", "NBA", "WNBA", "UFC", "TEAM", "INDIVIDUAL"]) assert.match(text, new RegExp(`\\b${value}\\b`));
  assert.match(text, /NFL[\s\S]*RESEARCH_SHADOW[\s\S]*RESEARCH_ONLY[\s\S]*projectCreationEnabled: false/);
});

test("workflow manifests are sport-native and planned leagues are non-selectable", async () => {
  const [manifest, registry] = await Promise.all([source("src/sports/shared/workflowManifest.ts"), source("src/sports/shared/sportRegistry.ts")]);
  for (const value of ["SPORT_WORKFLOW_MANIFEST_V1", "MLB_GAME_FORECAST_WORKFLOW_V1", "NFL_GAME_FORECAST_WORKFLOW_V1", "NBA_GAME_FORECAST_WORKFLOW_V1", "WNBA_GAME_FORECAST_WORKFLOW_V1", "UFC_BOUT_FORECAST_WORKFLOW_V1"]) assert.match(manifest, new RegExp(value));
  assert.match(manifest, /NFL_MONTE_CARLO_FIELD_SIMULATOR/);
  assert.match(manifest, /WEEKLY_SLATE_GROUPED/);
  assert.match(manifest, /Player Segmentation/);
  assert.match(manifest, /Team \/ Quarterback Segmentation/);
  assert.doesNotMatch(manifest, /HYPERPARAMETER_TUNING/);
  assert.match(manifest, /MODEL_LABORATORY[\s\S]*EVALUATION/);
  assert.match(registry, /workflowAvailability: "PLANNED"[\s\S]*projectCreationEnabled: false/g);
});

test("project creation follows the governed seven-step sequence", async () => {
  const text = await source("src/sports/NewSportsProject.tsx");
  const labels = ["Select sport", "Select league or promotion", "Select workflow template", "Define forecast contract", "Define development period", "Select target", "Bind eligible governed evidence"];
  let cursor = -1;
  for (const label of labels) { const next = text.indexOf(label); assert.ok(next > cursor, `${label} must appear in order`); cursor = next; }
  assert.match(text, /disabled=\{option\.availability === "PLANNED"\}/);
  assert.match(text, /No workspace dataset is silently linked/);
});

test("sport-aware route guard rejects persisted route mismatches", async () => {
  const [guard, routes, app] = await Promise.all([source("src/sports/shared/workflowRouteGuard.ts"), source("src/sports/sportsProjectRoutes.ts"), source("src/apps/ModelingApp.tsx")]);
  assert.match(guard, /Route league \$\{requestedLeagueCode\} does not match persisted project league/);
  assert.match(guard, /"mlb-forecasting"[\s\S]*MLB_GAME_FORECAST_WORKFLOW_V1/);
  assert.match(guard, /"nfl-forecasting"[\s\S]*NFL_GAME_FORECAST_WORKFLOW_V1/);
  assert.match(routes, /return `\/workflows\/mlb\?\$\{params\.toString\(\)\}`/);
  assert.match(app, /requestedLeagueCode="MLB"/);
  assert.match(app, /requestedLeagueCode="NFL"/);
});

test("projects and warehouse expose read-only All Sports, MLB, and NFL filters", async () => {
  const [projects, warehouse] = await Promise.all([source("src/sports/SportsProjects.tsx"), source("src/sports/SportsEvidenceSurfaces.tsx")]);
  for (const value of ["All Sports", "Sport", "League", "Workflow", "Primary target", "Evidence status"]) assert.match(projects, new RegExp(value));
  for (const value of ["All Sports", "GRAIN", "PREDICTION UNIT", "POINT-IN-TIME DECLARED", "SOURCE RIGHTS"]) assert.match(warehouse, new RegExp(value));
  assert.match(warehouse, /Filters do not change|filtering never changes a registration/i);
});

test("planned workflows have readiness metadata but no functional routes", async () => {
  const app = await source("src/apps/ModelingApp.tsx");
  assert.doesNotMatch(app, /path="\/workflows\/(?:nba|wnba|ufc)"/i);
  assert.match(app, /path="\/workflows\/mlb"/);
  assert.match(app, /path="\/workflows\/nfl"/);
});

test("new sports user-facing surfaces contain no legacy product terminology", async () => {
  const paths = ["src/sports/NewSportsProject.tsx", "src/sports/SportsProjects.tsx", "src/sports/shared/SportAwareWorkflowRoute.tsx"];
  for (const path of paths) assert.doesNotMatch(await source(path), /ATLAS/i, `${path} must not show legacy terminology`);
});
