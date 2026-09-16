// Phase 7D.4 Gate 16 (browser) — ASP Model Studio PA Modeling Cockpit acceptance config.
// Distinct from tests/e2e/playwright.config.ts (which targets the out-of-scope consumer app). This config drives
// the ASP Model Studio modeling frontend; the servers (scratch uvicorn + `vite dev` proxying /api to it) are
// started by the Python orchestrator tests/sports_cockpit_phase7d4_browser_test.py, which also provisions the
// isolated V2 scientific state and passes the fixture + baseURL via env. Uses the already-installed Chromium.
import { fileURLToPath } from "node:url";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  testDir: __dirname,
  outputDir: "../../test-results/e2e-cockpit/artifacts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.COCKPIT_E2E_BASE_URL || "http://127.0.0.1:5290",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 20_000,
    navigationTimeout: 60_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
});
