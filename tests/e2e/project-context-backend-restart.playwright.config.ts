import { fileURLToPath } from "node:url";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const configDirectory = path.dirname(fileURLToPath(import.meta.url));
const runtimeRoot = process.env.ATLAS_RESTART_BROWSER_RUNTIME;

if (!runtimeRoot) {
  throw new Error("ATLAS_RESTART_BROWSER_RUNTIME is required.");
}

export default defineConfig({
  testDir: configDirectory,
  testMatch: "project-context-backend-restart.integration.ts",
  outputDir: path.join(runtimeRoot, "playwright-artifacts"),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: [["line"]],
  use: {
    baseURL: process.env.ATLAS_E2E_BASE_URL,
    headless: true,
    actionTimeout: 20_000,
    navigationTimeout: 60_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
});
