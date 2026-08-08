import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";
import {
  isolatedChromiumArguments,
  isolatedHarnessEnvironment,
} from "./helpers/isolatedHarness";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const isolated = isolatedHarnessEnvironment();

export default defineConfig({
  testDir,
  outputDir: path.join(isolated.outputRoot, "artifacts"),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 10 * 60_000,
  expect: { timeout: 30_000 },
  reporter: [
    ["list"],
    ["html", { outputFolder: path.join(isolated.outputRoot, "html-report"), open: "never" }],
    ["json", { outputFile: path.join(isolated.outputRoot, "results.json") }],
  ],
  use: {
    baseURL: isolated.frontendOrigin,
    acceptDownloads: true,
    serviceWorkers: "block",
    proxy: { server: isolated.proxyOrigin },
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 30_000,
    navigationTimeout: 90_000,
    headless: isolated.headless,
    launchOptions: {
      args: isolatedChromiumArguments,
    },
  },
  projects: [
    {
      name: "isolated-chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1600, height: 1000 },
      },
    },
  ],
});

