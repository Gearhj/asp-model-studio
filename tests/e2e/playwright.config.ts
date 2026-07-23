import { fileURLToPath } from "node:url";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ATLAS Predictive Modeling E2E audit harness (Stage 7).
// Points at the already-running dev stack (frontend :5174 proxying to backend :8001).
// See tests/e2e/README.md for how to run this against a freshly started stack instead.
export default defineConfig({
  testDir: __dirname,
  outputDir: "../../test-results/e2e/artifacts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 20_000 },
  reporter: [
    ["list"],
    ["html", { outputFolder: "../../test-results/e2e/html-report", open: "never" }],
    ["json", { outputFile: "../../test-results/e2e/results.json" }],
  ],
  use: {
    baseURL: process.env.ATLAS_E2E_BASE_URL || "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 20_000,
    navigationTimeout: 60_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
});
