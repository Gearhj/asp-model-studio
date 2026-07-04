import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/data-acquisition-tests", import.meta.url));

async function transpileSource(sourcePath, outputPath) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output, "utf8");
}

async function compileHelpers() {
  await rm(TMP_DIR, { recursive: true, force: true });
  await transpileSource("src/lib/dataAcquisitionUpload.ts", path.join(TMP_DIR, "src/lib/dataAcquisitionUpload.js"));
  return import(pathToFileURL(path.join(TMP_DIR, "src/lib/dataAcquisitionUpload.js")).href);
}

const helpers = await compileHelpers();

test("small CSV files are routed to browser parsing", () => {
  const decision = helpers.getUploadDecision({ fileName: "TRAIN.csv", fileSize: 2 * 1024 * 1024 });
  assert.equal(decision.mode, "browser");
  assert.equal(decision.extension, "csv");
});

test("small JSON files are routed to browser parsing", () => {
  const decision = helpers.getUploadDecision({ fileName: "sample.json", fileSize: 256 * 1024 });
  assert.equal(decision.mode, "browser");
  assert.equal(decision.extension, "json");
});

test("large CSV files are routed to backend import instead of warning-only failure", () => {
  const decision = helpers.getUploadDecision({ fileName: "TRAIN.csv", fileSize: 82.4 * 1024 * 1024 });
  assert.equal(decision.mode, "backend");
  assert.match(decision.message, /backend/i);
});

test("large TXT delimited files are routed to backend import", () => {
  const decision = helpers.getUploadDecision({ fileName: "TRAIN.txt", fileSize: 80 * 1024 * 1024 });
  assert.equal(decision.mode, "backend");
});

test("large recognized non-CSV files show actionable unsupported guidance", () => {
  const decision = helpers.getUploadDecision({ fileName: "TRAIN.xlsx", fileSize: 80 * 1024 * 1024 });
  assert.equal(decision.mode, "recognized_unsupported");
  assert.match(decision.message, /CSV/i);
});

test("invalid file extensions are rejected inline", () => {
  const decision = helpers.getUploadDecision({ fileName: "malware.exe", fileSize: 10 });
  assert.equal(decision.mode, "invalid");
  assert.match(decision.message, /not an allowed/i);
});

test("backend import payload normalizes schema, row count, target, and preview rows", () => {
  const normalized = helpers.normalizeBackendImportResponse({
    ok: true,
    row_count: 56961,
    cols: 31,
    columns: ["Time", "Amount", "Class"],
    target: "Class",
    selected_columns: ["Time", "Amount"],
    sample_rows: [{ Time: 0, Amount: 1.25, Class: 0 }],
    filename: "TRAIN.csv",
  });
  assert.deepEqual(normalized.headers, ["Time", "Amount", "Class"]);
  assert.equal(normalized.rowCount, 56961);
  assert.equal(normalized.columnCount, 31);
  assert.equal(normalized.target, "Class");
  assert.deepEqual(normalized.selectedColumns, ["Time", "Amount"]);
  assert.equal(normalized.previewRows.length, 1);
});

test("backend import payload can infer target when backend leaves it blank", () => {
  const normalized = helpers.normalizeBackendImportResponse({
    rows_loaded: 1000,
    headers: ["V1", "V2", "Class"],
    sample_rows: [{ V1: 0, V2: 1, Class: 0 }],
  });
  assert.equal(normalized.target, "Class");
  assert.deepEqual(normalized.selectedColumns, ["V1", "V2"]);
});

test("selected dataset view drops deselected columns and keeps the target", () => {
  const view = helpers.buildSelectedDatasetView({
    headers: ["Time", "Amount", "V1", "Class"],
    rows: [
      { Time: 0, Amount: 10, V1: -0.5, Class: 0 },
      { Time: 1, Amount: 20, V1: 0.5, Class: 1 },
    ],
    selectedColumns: ["Amount", "V1"],
    target: "Class",
  });

  assert.deepEqual(view.headers, ["Amount", "V1", "Class"]);
  assert.deepEqual(view.selectedColumns, ["Amount", "V1"]);
  assert.equal("Time" in view.rows[0], false);
  assert.deepEqual(Object.keys(view.rows[0]), ["Amount", "V1", "Class"]);
});

test("CTA disabled reason explains import and target blockers", () => {
  assert.match(
    helpers.dataAcquisitionDisabledReason({ isImporting: true, hasHeaders: false, hasTarget: false }),
    /importing/i
  );
  assert.match(
    helpers.dataAcquisitionDisabledReason({ isImporting: false, hasHeaders: true, hasTarget: false }),
    /target/i
  );
  assert.equal(
    helpers.dataAcquisitionDisabledReason({ isImporting: false, hasHeaders: true, hasTarget: true }),
    ""
  );
  assert.equal(
    helpers.dataAcquisitionDisabledReason({ isImporting: false, hasHeaders: true, hasTarget: true, importError: "Previous file failed" }),
    ""
  );
});

test("frontend source calls backend upload and avoids set_sample for backend-imported datasets", async () => {
  const source = await readFile(new URL("../src/steps/Step01_DataAcquisition.tsx", import.meta.url), "utf8");
  assert.match(source, /\/data\/upload_csv/);
  assert.match(source, /backendImportSynced \? "\/data\/set_target" : "\/data\/set_sample"/);
  assert.match(source, /nextDisabledReason/);
});

test("data preview has one target selector and shared next navigation", async () => {
  const source = await readFile(new URL("../src/steps/Step01_DataAcquisition.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /<Select label="Target"/);
  assert.match(source, /<div className="font-semibold">Target variable<\/div>/);
  assert.match(source, /nextPath="\/step01b"/);
  assert.doesNotMatch(source, /navigate\("\/step01b"\)/);
});

test("backend upload endpoint defaults to 250 MB and returns preview rows", async () => {
  const source = await readFile(new URL("../server/main.py", import.meta.url), "utf8");
  assert.match(source, /250 \* 1024 \* 1024/);
  assert.match(source, /sample_rows/);
  assert.match(source, /rows_loaded/);
  assert.match(source, /max_upload_mb/);
});

test("backend routers use active selected-column dataset view", async () => {
  const datasetStore = await readFile(new URL("../server/core/dataset_store.py", import.meta.url), "utf8");
  const metadataRouter = await readFile(new URL("../server/core/metadata_router.py", import.meta.url), "utf8");
  const edaRouter = await readFile(new URL("../server/eda/eda_router.py", import.meta.url), "utf8");
  const splitRouter = await readFile(new URL("../server/splitting/split_router.py", import.meta.url), "utf8");
  const trainerService = await readFile(new URL("../server/training/trainer_service.py", import.meta.url), "utf8");

  assert.match(datasetStore, /def get_active_df/);
  assert.match(metadataRouter, /DATASTORE\.get_active_df/);
  assert.match(edaRouter, /DATASTORE\.get_active_df/);
  assert.match(splitRouter, /DATASTORE\.get_active_df/);
  assert.match(trainerService, /DATASTORE\.get_active_df/);
});
