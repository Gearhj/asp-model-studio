import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const required = [
  "src/api/analyticsEngine.ts",
  "src/types/analyticsEngine.ts",
  "src/components/analytics/AnalyticalResultCard.tsx",
  "src/components/analytics/DiagnosticTable.tsx",
  "src/components/analytics/AnalyticalChart.tsx",
  "server/analytics_engine/service.py",
  "server/analytics_engine/router.py",
  "server/persistence/migrations/0009_analytics_engine.sql",
];
required.forEach((path) => assert.ok(existsSync(path), `${path} must exist`));
const router = readFileSync("server/analytics_engine/router.py", "utf8");
assert.match(router, /\/api\/analytics-engine/);
assert.match(router, /time-series\/profile/);
assert.match(router, /classification\/diagnostics/);
const main = readFileSync("server/main.py", "utf8");
assert.match(main, /analytics_engine_router/);
const profile = readFileSync("src/workflows/time-series/TimeSeriesProfile.tsx", "utf8");
assert.match(profile, /requestAnalyticalRun\("time_series_profile"/);
assert.doesNotMatch(readFileSync("src/components/Sidebar.tsx", "utf8"), /Analytical Engine/);
console.log("Analytics engine static tests passed.");
