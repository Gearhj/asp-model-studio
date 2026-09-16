import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const [api, surface, workflow] = await Promise.all([
  readFile(new URL("src/sports/sportsEvidenceApi.ts", ROOT), "utf8"),
  readFile(new URL("src/sports/SportsEvidenceSurfaces.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/ForecastWorkflow.tsx", ROOT), "utf8"),
]);

test("NFL Warehouse response fields are typed and normalized as public evidence", () => {
  for (const field of [
    "sourceProvider?", "sourceFamilies?", "featureFamilies?", "featureEraContracts?",
    "quality?", "nflCurrentSync?", "goldPregameGames?", "goldPlayStates?",
  ]) assert.ok(api.includes(field), `missing NFL Warehouse contract field ${field}`);
  for (const normalizer of [
    "normalizeSportsSourceFamilies", "normalizeFeatureFamilies", "normalizeFeatureEraContracts", "normalizeNflQuality",
  ]) assert.ok(api.includes(normalizer), `missing NFL normalization boundary ${normalizer}`);
  assert.ok(api.includes("sanitizePublicEvidenceValue(raw.nflCurrentSync)"));
});

test("NFL Warehouse renders football-native totals instead of baseball zero cards", () => {
  const start = surface.indexOf('if (dataset.league.trim().toUpperCase() === "NFL")');
  const end = surface.indexOf("const currentStatcast", start);
  assert.ok(start >= 0 && end > start, "NFL MetricGrid branch is missing");
  const nflMetrics = surface.slice(start, end);
  for (const label of [
    "Games", "Plays", "Drives", "Team-game rows", "Player-game rows",
    "Gold pregame games", "Gold play states", "Registered tables",
  ]) assert.ok(nflMetrics.includes(label), `NFL metrics missing ${label}`);
  assert.doesNotMatch(nflMetrics, /Plate appearances|Transitions|Starter targets|Bullpen appearances/);
});

test("NFL Warehouse exposes exact coverage, feature inventory, quality, market, and rights context", () => {
  for (const label of [
    "NFL season and current-2026 coverage", "NFL source-family coverage",
    "NFL Gold feature-family authority", "Feature-era contracts",
    "NFL identity, reconciliation, and market review", "Historical market coverage",
    "Duplicate game identities", "PBP games without schedule", "Core predictor eligible",
    "Source rights", "Known limitations",
  ]) assert.ok(surface.includes(label), `NFL Warehouse section missing ${label}`);
  assert.ok(surface.includes("features.map((feature, index)"), "exact ordered feature names must be rendered");
  assert.ok(surface.includes("family.releaseTags.join") && surface.includes("family.licenseIds.join"));
  assert.ok(surface.includes("workspaceActivationEligible === false"));
  assert.ok(surface.includes("READ-ONLY AUTHORITY"));
});

test("MLB details remain on their existing path and NFL remains a no-model foundation", () => {
  assert.ok(surface.includes("isNfl ? <NflSeasonAndCurrentCoverage") && surface.includes(": <SeasonCoverage"));
  assert.ok(surface.includes("!isNfl ? <>") && surface.includes("<IdentityBridgeAuthority dataset={dataset} />"));
  assert.ok(workflow.includes("Workflow foundation only. No NFL models or data are configured."));
});
