import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP = fileURLToPath(new URL("../.tmp/sports-custom-temporal-design", import.meta.url));

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
await transpile("src/sports/workflow/workflowState.ts", path.join(TMP, "src/sports/workflow/workflowState.js"));
const wf = await import(pathToFileURL(path.join(TMP, "src/sports/workflow/workflowState.js")).href);
after(async () => rm(TMP, { recursive: true, force: true }));

const coverage = {
  earliestDate: "2021-04-01",
  latestDate: "2025-09-28",
  registrationId: "registration-1",
  datasetId: "asp.mlb.open-data.fd1",
  datasetVersionId: "dataset-version-1",
  manifestSha: "a".repeat(64),
  family: "plate_appearance",
};

const validRanges = () => ({
  eligibleEvidence: { startDate: "2023-03-30", endDate: "2025-09-28" },
  developmentSelection: { startDate: "2023-03-30", endDate: "2025-08-31" },
  finalOot: { startDate: "2025-09-01", endDate: "2025-09-28" },
});

test("custom dates validate exactly inside registered PA coverage", () => {
  const result = wf.validateCustomTemporalDesign(validRanges(), coverage);
  assert.equal(result.valid, true);
  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.missingIntervals, []);
  assert.equal(result.coverageMessage, null);
});

test("the intended 2026 custom contract is fully covered by current Statcast authority", () => {
  const currentCoverage = {
    ...coverage,
    earliestDate: "2023-03-30",
    latestDate: "2026-08-27",
    registrationId: "sports-dataset-current-statcast-03ca6dab30e760b2",
    datasetId: "asp.mlb.statcast.current-pa.v1",
    datasetVersionId: "asp.mlb.statcast.current-pa.v1:partition-authority-sha256:6e134d8726587ad88d0807effb6e6b12ad39f39b99acb7f523ae6ae98155df34",
  };
  const result = wf.validateCustomTemporalDesign({
    eligibleEvidence: { startDate: "2023-03-30", endDate: "2026-08-27" },
    developmentSelection: { startDate: "2023-03-30", endDate: "2026-08-13" },
    finalOot: { startDate: "2026-08-14", endDate: "2026-08-27" },
  }, currentCoverage);
  assert.equal(result.valid, true);
  assert.deepEqual(result.missingIntervals, []);
  assert.equal(result.coverageMessage, null);
});

test("2026 is blocked with the exact registered end and missing interval", () => {
  const input = validRanges();
  input.eligibleEvidence.endDate = "2026-08-27";
  input.developmentSelection.endDate = "2026-08-13";
  input.finalOot = { startDate: "2026-08-14", endDate: "2026-08-27" };
  const result = wf.validateCustomTemporalDesign(input, coverage);
  assert.equal(result.valid, false);
  assert.equal(
    result.coverageMessage,
    "Registered source evidence currently ends on 2025-09-28. The requested 2026 evaluation period is not available in the Data Warehouse.",
  );
  assert.deepEqual(result.missingIntervals, [{ startDate: "2025-09-29", endDate: "2026-08-27" }]);
});

test("calendar validity, nesting, ordering, and overlap fail closed", () => {
  const invalidDate = validRanges();
  invalidDate.finalOot.endDate = "2025-02-30";
  assert.equal(wf.validateCustomTemporalDesign(invalidDate, coverage).fieldErrors.finalOotEnd, "Enter a valid calendar date.");

  const reversed = validRanges();
  reversed.developmentSelection = { startDate: "2025-09-01", endDate: "2025-08-31" };
  assert.match(wf.validateCustomTemporalDesign(reversed, coverage).errors.join(" "), /start must not be after/i);

  const outside = validRanges();
  outside.developmentSelection.startDate = "2023-03-29";
  assert.match(wf.validateCustomTemporalDesign(outside, coverage).errors.join(" "), /within the eligible/i);

  const overlap = validRanges();
  overlap.finalOot.startDate = overlap.developmentSelection.endDate;
  assert.match(wf.validateCustomTemporalDesign(overlap, coverage).errors.join(" "), /must not overlap/i);
});

test("missing coverage is reported on both sides without truncation", () => {
  assert.deepEqual(
    wf.missingCoverageIntervals({ startDate: "2020-01-01", endDate: "2026-01-02" }, coverage),
    [
      { startDate: "2020-01-01", endDate: "2021-03-31" },
      { startDate: "2025-09-29", endDate: "2026-01-02" },
    ],
  );
});

test("season roles cannot turn the unavailable 2026 season into evidence", () => {
  assert.equal(wf.seasonRoleCoverageError(2023, 2025, coverage), null);
  assert.equal(
    wf.seasonRoleCoverageError(2023, 2026, coverage),
    "Registered source evidence currently ends on 2025-09-28. Frozen final season 2026 is not available in the Data Warehouse. Missing interval: 2025-09-29 through 2026-12-31.",
  );
  assert.match(wf.seasonRoleCoverageError(2023, 2025, null), /coverage is unavailable/i);
});

test("legacy season contracts remain season-role contracts without data loss", () => {
  const legacy = wf.normalizeForecastContract({
    projectId: "legacy-project",
    version: 4,
    target: "Plate-Appearance Outcome",
    lifecycle: "Pregame — Final",
    developmentSeasons: [2023],
    validationSeason: 2024,
    frozenSeason: 2025,
    prospectiveSeason: 2026,
    evidenceMode: "ENHANCED",
    intendedOutputs: ["Plate-Appearance Outcome"],
    researchPurpose: "legacy",
    notes: "preserve",
    savedAt: "2026-01-01T00:00:00Z",
  }, "legacy-project");
  assert.equal(legacy.temporalDesignMode, "SEASON_ROLES");
  assert.deepEqual(legacy.developmentSeasons, [2023]);
  assert.equal(legacy.validationSeason, 2024);
  assert.equal(legacy.frozenSeason, 2025);
  assert.equal(legacy.evidenceMode, "ENHANCED");
});

test("flat backend custom dates round-trip to the domain without hidden season authority", () => {
  const custom = wf.normalizeForecastContract({
    projectId: "custom-project",
    version: 2,
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
    intendedOutputs: [],
    researchPurpose: "custom",
    notes: "",
    registeredAt: "2026-08-28T12:00:00Z",
  }, "custom-project");
  assert.deepEqual(custom.eligibleEvidence, validRanges().eligibleEvidence);
  assert.deepEqual(custom.developmentSelection, validRanges().developmentSelection);
  assert.deepEqual(custom.finalOot, validRanges().finalOot);
  assert.deepEqual(custom.developmentSeasons, []);
  assert.equal(custom.validationSeason, null);
  assert.equal(custom.frozenSeason, null);
  assert.equal(custom.savedAt, "2026-08-28T12:00:00Z");
  assert.equal(wf.temporalPolicyLabel(custom), "2023-03-30–2025-08-31 → OOT 2025-09-01–2025-09-28");
});

test("Stage 1 records five-fold constraints but no fold dates", () => {
  assert.deepEqual(wf.DEFERRED_CHRONOLOGICAL_VALIDATION, {
    required: true,
    configurationStage: "VALIDATION_CALIBRATION",
    foldCount: 5,
    window: "EXPANDING",
    validationBlocks: "DATE_ATOMIC",
    grouping: "CANONICAL_GAME",
    shuffle: false,
    preprocessing: "FOLD_LOCAL",
    boundaryOptions: ["BALANCED_BY_GAME_COUNT", "MANUAL_DATE_RANGES"],
    finalOotUse: "REPORTING_ONLY",
    exactBoundaries: null,
  });
});

const [panel, guided, overview, stageContent] = await Promise.all([
  readFile(new URL("src/sports/workflow/ForecastContractPanel.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/GuidedWorkflow.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/SportsProjectOverview.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/GuidedStageContent.tsx", ROOT), "utf8"),
]);

test("Stage 1 exposes the exact required UI and defers fold generation", () => {
  assert.ok(panel.includes("Custom dates / rolling-origin") && panel.includes("Season roles"));
  for (const label of [
    "Eligible evidence start", "Eligible evidence end",
    "Development and model-selection start", "Development and model-selection end",
    "Final OOT start", "Final OOT end",
  ]) assert.ok(panel.includes(label), `missing date control ${label}`);
  assert.ok(panel.includes('type="date"'));
  assert.ok(panel.includes("Exact chronological fold boundaries, grouping, and preprocessing rules will be configured in Validation &amp; Calibration."));
  assert.ok(panel.includes("Only evidence proven available before first pitch."));
  assert.ok(panel.includes("May include research-only evidence with timing limitations and is not automatically deployment-safe."));
  assert.ok(panel.includes("CustomDateTimeline") && panel.includes("Earlier registered evidence, derived from the selected boundary"));
});

test("workflow and downstream summaries use backend authority and mode-aware labels", () => {
  assert.ok(guided.includes("useForecastContract") && guided.includes("compatibilityDraft"));
  assert.ok(guided.includes("await contractAuthority.register(draft)"));
  assert.ok(overview.includes("useForecastContract") && overview.includes("temporalPolicyLabel"));
  assert.ok(stageContent.includes("validationWindowLabel") && stageContent.includes("finalOotWindowLabel"));
  assert.ok(!stageContent.includes("String(contract.validationSeason)"));
  assert.ok(!stageContent.includes("String(contract.frozenSeason)"));
});
