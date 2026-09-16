import assert from "node:assert/strict";
import { after, beforeEach, test } from "node:test";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP = fileURLToPath(new URL("../.tmp/sports-forecast-contract-persistence", import.meta.url));

globalThis.localStorage = {
  _s: new Map(),
  getItem(key) { return this._s.has(key) ? this._s.get(key) : null; },
  setItem(key, value) { this._s.set(key, String(value)); },
  removeItem(key) { this._s.delete(key); },
};

async function transpile(source, output) {
  let code = await readFile(new URL(source, ROOT), "utf8");
  code = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  code = code.replace(/from\s+["'](\.{1,2}\/[^"']+)["']/g, (match, specifier) =>
    specifier.endsWith(".js") || specifier.endsWith(".json")
      ? match
      : match.replace(specifier, `${specifier}.js`));
  await mkdir(path.dirname(output), { recursive: true });
  await writeFile(output, code, "utf8");
}

await rm(TMP, { recursive: true, force: true });
await transpile("src/lib/api.ts", path.join(TMP, "src/lib/api.js"));
await transpile("src/sports/workflow/workflowState.ts", path.join(TMP, "src/sports/workflow/workflowState.js"));
await transpile("src/sports/workflow/sportsAuthorityErrors.ts", path.join(TMP, "src/sports/workflow/sportsAuthorityErrors.js"));
await transpile("src/sports/workflow/forecastContractPersistence.ts", path.join(TMP, "src/sports/workflow/forecastContractPersistence.js"));

const wf = await import(pathToFileURL(path.join(TMP, "src/sports/workflow/workflowState.js")).href);
const persistence = await import(pathToFileURL(path.join(TMP, "src/sports/workflow/forecastContractPersistence.js")).href);
after(async () => rm(TMP, { recursive: true, force: true }));
beforeEach(() => localStorage._s.clear());

const projectId = "temporal-project";
const coverage = {
  earliestDate: "2021-04-01",
  latestDate: "2025-09-28",
  registrationId: "registration-1",
  datasetId: "asp.mlb.open-data.fd1",
  datasetVersionId: "dataset-version-1",
  manifestSha: "a".repeat(64),
  family: "plate_appearance",
  rowCount: 913349,
  partitionCount: 36,
};

const legacy = {
  projectId,
  version: 1,
  target: "Plate-Appearance Outcome",
  lifecycle: "Pregame — Final",
  developmentSeasons: [2023],
  validationSeason: 2024,
  frozenSeason: 2025,
  prospectiveSeason: 2026,
  evidenceMode: "ENHANCED",
  intendedOutputs: ["Plate-Appearance Outcome"],
  researchPurpose: "legacy",
  notes: "",
  savedAt: "2026-01-01T00:00:00Z",
};

const currentCustom = {
  schemaVersion: "SPORTS_FORECAST_CONTRACT_V2",
  projectId,
  version: 1,
  temporalDesignMode: "CUSTOM_DATES_ROLLING_ORIGIN",
  target: "Plate-Appearance Outcome",
  lifecycle: "Pregame — Final",
  eligibleEvidenceStart: "2023-03-30",
  eligibleEvidenceEnd: "2025-09-28",
  developmentSelectionStart: "2023-03-30",
  developmentSelectionEnd: "2025-08-31",
  finalOotStart: "2025-09-01",
  finalOotEnd: "2025-09-28",
  chronologicalValidation: wf.DEFERRED_CHRONOLOGICAL_VALIDATION,
  coverageAuthority: coverage,
  evidenceMode: "STRICT",
  intendedOutputs: ["Plate-Appearance Outcome"],
  researchPurpose: "custom",
  notes: "",
  savedAt: "2026-08-28T12:00:00Z",
};

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

test("GET is read-only and returns a legacy browser contract only as a compatibility draft", async () => {
  localStorage.setItem(`asp-sports-forecast-contract:${projectId}`, JSON.stringify(legacy));
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return response({ ok: true, contract: null, history: [], coverage });
  };
  const envelope = await persistence.hydrateForecastContract(projectId);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init.method, "GET");
  assert.equal(envelope.contract, null);
  assert.equal(envelope.compatibilityDraft.temporalDesignMode, "SEASON_ROLES");
  assert.equal(JSON.parse(localStorage.getItem(`asp-sports-forecast-contract:${projectId}`)).version, 1);
});

test("PUT sends expectedVersion plus flat exact dates and caches only acknowledged authority", async () => {
  let requestBody = null;
  globalThis.fetch = async (_url, init = {}) => {
    requestBody = JSON.parse(init.body);
    return response({ ok: true, contract: currentCustom, history: [], coverage });
  };
  const domain = wf.normalizeForecastContract(currentCustom, projectId);
  const envelope = await persistence.putForecastContract(projectId, 0, domain);
  assert.equal(requestBody.expectedVersion, 0);
  assert.equal(requestBody.contract.temporalDesignMode, "CUSTOM_DATES_ROLLING_ORIGIN");
  assert.equal(requestBody.contract.eligibleEvidenceStart, "2023-03-30");
  assert.equal(requestBody.contract.finalOotEnd, "2025-09-28");
  assert.equal(requestBody.contract.validationSeason, undefined);
  assert.deepEqual(envelope.contract.finalOot, { startDate: "2025-09-01", endDate: "2025-09-28" });
  const cached = JSON.parse(localStorage.getItem(`asp-sports-forecast-contract:${projectId}`));
  assert.equal(cached.version, 1);
  assert.equal(cached.temporalDesignMode, "CUSTOM_DATES_ROLLING_ORIGIN");
});

test("failed registration surfaces the server coverage error and never updates the cache", async () => {
  globalThis.fetch = async () => response({
    detail: {
      code: "SOURCE_COVERAGE_INSUFFICIENT",
      message: "Registered source evidence currently ends on 2025-09-28. The requested 2026 evaluation period is not available in the Data Warehouse.",
      requestedRange: { start: "2023-03-30", end: "2026-08-27" },
      missingIntervals: [{ start: "2025-09-29", end: "2026-08-27" }],
      coverage,
    },
  }, 422);
  const domain = wf.normalizeForecastContract(currentCustom, projectId);
  await assert.rejects(
    persistence.putForecastContract(projectId, 0, domain),
    /currently ends on 2025-09-28/,
  );
  assert.equal(localStorage.getItem(`asp-sports-forecast-contract:${projectId}`), null);
});

test("backend current wins over a stale local compatibility record", async () => {
  localStorage.setItem(`asp-sports-forecast-contract:${projectId}`, JSON.stringify(legacy));
  globalThis.fetch = async () => response({ ok: true, contract: currentCustom, history: [legacy], coverage });
  const envelope = await persistence.hydrateForecastContract(projectId);
  assert.equal(envelope.contract.temporalDesignMode, "CUSTOM_DATES_ROLLING_ORIGIN");
  assert.equal(envelope.compatibilityDraft, null);
  const cached = JSON.parse(localStorage.getItem(`asp-sports-forecast-contract:${projectId}`));
  assert.equal(cached.temporalDesignMode, "CUSTOM_DATES_ROLLING_ORIGIN");
  assert.deepEqual(cached.finalOot, { startDate: "2025-09-01", endDate: "2025-09-28" });
});
