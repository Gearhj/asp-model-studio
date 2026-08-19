// Phase 6E — PA development population authority. Asserts the project contract and the canonical
// modeling matrix cannot silently disagree: the governed development window is 2023 only (2021-2022
// are PRIOR_ONLY_HISTORY), validation is 2024, and 2025 is never a development/selection season.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP = fileURLToPath(new URL("../.tmp/population-authority", import.meta.url));

globalThis.localStorage = {
  _s: new Map(),
  getItem(k) { return this._s.has(k) ? this._s.get(k) : null; },
  setItem(k, v) { this._s.set(k, String(v)); },
  removeItem(k) { this._s.delete(k); },
};

async function transpile(src, out) {
  let code = await readFile(new URL(src, ROOT), "utf8");
  code = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }).outputText;
  code = code.replace(/from\s+["'](\.{1,2}\/[^"']+)["']/g, (m, s) => (s.endsWith(".js") || s.endsWith(".json") ? m : m.replace(s, `${s}.js`)));
  await mkdir(path.dirname(out), { recursive: true });
  await writeFile(out, code, "utf8");
}

await rm(TMP, { recursive: true, force: true });
await transpile("src/sports/workflow/workflowState.ts", path.join(TMP, "src/sports/workflow/workflowState.js"));
const wf = await import(pathToFileURL(path.join(TMP, "src/sports/workflow/workflowState.js")).href);

test("season coverage: governed development window is exactly [2023] (audit-approved)", () => {
  assert.deepEqual(wf.GOVERNED_TEMPORAL.developmentSeasons, [2023]);
  assert.equal(wf.MODELING_START_SEASON, 2023);
});

test("population authority: contract default no longer claims 2021-2023 development", () => {
  // The old default over-claimed [2021, 2022, 2023]; the governed default is the modeling window.
  assert.deepEqual(wf.DEFAULT_TEMPORAL.developmentSeasons, [2023]);
});

test("reconciliation: a legacy [2021,2022,2023] contract is displayed as 2023-only development", () => {
  assert.deepEqual(wf.governedDevelopmentSeasons([2021, 2022, 2023]), [2023]);
  assert.equal(wf.developmentWindowLabel({ developmentSeasons: [2021, 2022, 2023] }), "2023");
  // empty / null falls back to the governed window (never blank, never 2021)
  assert.deepEqual(wf.governedDevelopmentSeasons([]), [2023]);
  assert.deepEqual(wf.governedDevelopmentSeasons(null), [2023]);
});

test("frozen-season: 2025 is never a development/selection season", () => {
  assert.ok(!wf.GOVERNED_TEMPORAL.developmentSeasons.includes(2025));
  assert.deepEqual(wf.governedDevelopmentSeasons([2025]), [2023]); // 2025 dropped, not selectable as dev
  assert.deepEqual(wf.governedDevelopmentSeasons([2023, 2024, 2025]), [2023]); // only 2023 survives
  assert.equal(wf.GOVERNED_TEMPORAL.frozenSeason, 2025);
});

test("validation: 2024 remains the validation season", () => {
  assert.equal(wf.GOVERNED_TEMPORAL.validationSeason, 2024);
  assert.equal(wf.DEFAULT_TEMPORAL.validationSeason, 2024);
});

test("prior-only history: 2021-2022 are source evidence, not modeling targets", () => {
  assert.deepEqual(wf.GOVERNED_TEMPORAL.priorOnlyHistorySeasons, [2021, 2022]);
  assert.deepEqual(wf.GOVERNED_TEMPORAL.sourceEvidenceSeasons, [2021, 2022, 2023, 2024, 2025]);
  for (const s of wf.GOVERNED_TEMPORAL.priorOnlyHistorySeasons) {
    assert.ok(!wf.GOVERNED_TEMPORAL.developmentSeasons.includes(s));
    assert.ok(!wf.governedDevelopmentSeasons([s]).includes(s));
  }
  assert.match(wf.GOVERNED_TEMPORAL.priorOnlyReason, /PRIOR_ONLY_HISTORY|prior.only/i);
});

// ---- static wiring: display surfaces must reconcile through the governed helper, not raw contract ----
const [panel, overview, stageContent] = await Promise.all([
  readFile(new URL("src/sports/workflow/ForecastContractPanel.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/SportsProjectOverview.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/GuidedStageContent.tsx", ROOT), "utf8"),
]);

test("contract panel restricts development selection to governed modeling seasons (no 2021-2022)", () => {
  assert.ok(panel.includes("DEV_YEARS") && panel.includes("MODELING_START_SEASON"));
  assert.ok(panel.includes("governedDevelopmentSeasons"));
  // development dropdowns iterate DEV_YEARS, not the full YEARS list
  assert.ok(panel.includes("DEV_YEARS.filter((y) => y <= devEnd)"));
  assert.ok(panel.includes("Source evidence")); // honest source-vs-development note present
});

test("overview + stage-3 intro display the governed (reconciled) development window", () => {
  assert.ok(overview.includes("developmentWindowLabel(contract)"));
  assert.ok(stageContent.includes("developmentWindowLabel(contract)"));
  // the old hard-coded 2021-2023 fallback is gone from the cockpit intro
  assert.ok(!stageContent.includes('"2021–2023"'));
  // Stage 2 shows the population-authority reconciliation block
  assert.ok(stageContent.includes("source evidence vs. modeling development") || stageContent.includes("Population authority"));
});
