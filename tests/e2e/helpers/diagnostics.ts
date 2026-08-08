import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page, TestInfo } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export type DiagnosticsLog = {
  consoleErrors: string[];
  consoleWarnings: string[];
  pageErrors: string[];
  failedRequests: string[];
  failedResponses: string[];
};

/**
 * Attaches console/network/error listeners to a page for the lifetime of a test
 * and returns the accumulated log. Call dump() in an afterEach (or at any point)
 * to write the log to test-results/e2e/logs/<test-title>.json and attach it to
 * the Playwright report.
 */
export function attachDiagnostics(page: Page, testInfo: TestInfo): { log: DiagnosticsLog; dump: () => Promise<void> } {
  const log: DiagnosticsLog = {
    consoleErrors: [],
    consoleWarnings: [],
    pageErrors: [],
    failedRequests: [],
    failedResponses: [],
  };

  page.on("console", (msg) => {
    const text = `[${msg.type()}] ${msg.text()}`;
    if (msg.type() === "error") log.consoleErrors.push(text);
    if (msg.type() === "warning") log.consoleWarnings.push(text);
  });

  page.on("pageerror", (err) => {
    log.pageErrors.push(err.stack || err.message);
  });

  page.on("requestfailed", (req) => {
    log.failedRequests.push(`${req.method()} ${req.url()} -- ${req.failure()?.errorText ?? "unknown error"}`);
  });

  page.on("response", (res) => {
    if (res.status() >= 400) {
      log.failedResponses.push(`${res.status()} ${res.request().method()} ${res.url()}`);
    }
  });

  const dump = async () => {
    const configuredRoot = process.env.ATLAS_PLAYWRIGHT_OUTPUT_ROOT?.trim();
    const dir = configuredRoot
      ? path.resolve(configuredRoot, "diagnostics")
      : path.resolve(__dirname, "../../../test-results/e2e/logs");
    fs.mkdirSync(dir, { recursive: true });
    const safeName = testInfo.title.replace(/[^a-z0-9-_]+/gi, "_").slice(0, 120);
    const file = path.join(dir, `${safeName}.json`);
    fs.writeFileSync(file, JSON.stringify(log, null, 2));
    await testInfo.attach("diagnostics-log", { path: file, contentType: "application/json" });
  };

  return { log, dump };
}
