import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page, TestInfo } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// One timestamp per whole audit run, shared across all spec files/workers via env var
// (see tests/e2e/README.md — set E2E_AUDIT_DIR before invoking `npx playwright test`,
// or a fresh timestamp is created the first time this module loads).
const RUN_ID = process.env.E2E_AUDIT_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-");
const CONFIGURED_ROOT = process.env.E2E_AUDIT_DIR?.trim();
const ISOLATED_OUTPUT_ROOT = process.env.ATLAS_PLAYWRIGHT_OUTPUT_ROOT?.trim();
export const AUDIT_ROOT = CONFIGURED_ROOT
  ? path.resolve(CONFIGURED_ROOT)
  : ISOLATED_OUTPUT_ROOT
    ? path.resolve(ISOLATED_OUTPUT_ROOT, "screenshots", RUN_ID)
    : path.resolve(__dirname, "../../../test-results/e2e/screenshots", RUN_ID);

let seq = 0;

export async function shot(page: Page, testInfo: TestInfo, label: string): Promise<string> {
  seq += 1;
  const projectSlug = testInfo.titlePath[0]?.replace(/[^a-z0-9-_]+/gi, "_") || "spec";
  const dir = path.join(AUDIT_ROOT, projectSlug);
  fs.mkdirSync(dir, { recursive: true });
  const safeLabel = label.replace(/[^a-z0-9-_]+/gi, "_").slice(0, 100);
  const file = path.join(dir, `${String(seq).padStart(3, "0")}-${safeLabel}.png`);
  await page.screenshot({ path: file, fullPage: true });
  await testInfo.attach(label, { path: file, contentType: "image/png" });
  return file;
}
